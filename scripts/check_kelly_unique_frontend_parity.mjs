#!/usr/bin/env node
/**
 * 前端三表解析器对账(L42 数据瘦身前端改造 Phase A, 2026-09-20)。
 *
 * 用途: Phase B/C 实施期的回归基线 —— node 喂同一个 unique.json, 分别用
 * 「新三表解析器」与「旧 quadrants 直读(临时对比桩)」构建同一 mode pool,
 * 断言 pool 键集 / 27 列逐位 / _mktD/_etfD/_ratD 一致 (§四.1-3 前端解析器对账)。
 *
 * 用法:
 *   node scripts/check_kelly_unique_frontend_parity.mjs \
 *     --unique /tmp/kelly-unique-phasea-out/signal_kelly_trades_unique.json \
 *     --trades static-site/data/signal_kelly_trades.json
 *   (sdc 档: --unique ..._sdc_unique.json --trades ..._sdc.json)
 *
 * 只比「集合 + 逐位值」, 不比行顺序: 旧实现按 qk 遍历序见首写入, 新实现按
 * base 遍历序直建, 顺序差异是预期的(方案 §四.1-3)。任意断言 FAIL 退出码 1。
 *
 * 硬约束(R1/R8): 三表 fields=19 列, 旧 27 列中的 8 个卖出字段(sell_date 等)只
 * 在 variants 表, 故解析器必须把 base(19)+variants(8)拼回 27 列完整行再喂对比;
 * 变体行可能为 null 哨兵(R8), 拼行时 if (v==null) continue 跳过该 (基笔,mode)。
 */
import fs from "node:fs";
import path from "node:path";

// ── CLI ─────────────────────────────────────────────
const args = {};
for (let i = 2; i < process.argv.length; i++) {
  const a = process.argv[i];
  if (a.startsWith("--")) { args[a.slice(2)] = process.argv[i + 1]; i++; }
}
const uniqPath = args.unique;
const tradesPath = args.trades;
if (!uniqPath || !tradesPath) {
  console.error("用法: node check_kelly_unique_frontend_parity.mjs --unique <unique.json> --trades <trades.json>");
  process.exit(2);
}

const uniq = JSON.parse(fs.readFileSync(uniqPath, "utf8"));
const trades = JSON.parse(fs.readFileSync(tradesPath, "utf8"));

// ── 前端三表解析器(新路径, 形态 B: 直接构建 pool) ──
// 等价 app.js _simBaseKey / _simQkDim(实施期临时对比桩同源; 后续 Phase B/C 前端
// 实现改完后, 本脚本用前端函数本体构建, 洗掉「脚本自实现=第二份实现」漂移)。
function baseKey(row27, fIdx) {
  return [fIdx.signal_date, fIdx.index_id, fIdx.signal, fIdx.buy_date, fIdx.etf_code]
    .map((i) => row27[i] ?? "").join("|");
}
function qkDim(qk) {
  if (qk.startsWith("mkt_")) return { type: "mkt", val: qk.slice(4) };
  if (qk.startsWith("etf_")) return { type: "etf", val: qk.slice(4) };
  if (qk.startsWith("sig_")) return { type: "sig", val: qk.slice(4) };
  if (qk.startsWith("rating_")) return { type: "rating", val: qk.slice(7) };
  return null;
}

// 列映射: 以 trades.fields(27 列旧序)为基准, unique.fields(19 共享)在旧序中的位置
// 决定该列取自 base, 其余(8 卖出字段)取自 variant。
const tradeFields = trades.fields;              // 27 列
const fIdx = {};
tradeFields.forEach((f, i) => { fIdx[f] = i; });
const uFieldSet = new Set(uniq.fields);         // 19 共享字段名
// isShare[colIndex] = true → 该列来自 base, false → 来自 variant
const isShare = tradeFields.map((f) => uFieldSet.has(f));

/**
 * 新路径: 三表直接构建 mode pool(形态 B, 方案 §2.1 buildModePool)。
 * 遍历 base(每基笔一行, 无重复) → 4 枚举码归属 → 取该基笔该 mode 的 variant 行拼
 * 27 列 → 直接落 _mktD/_etfD/_ratD(qk 前缀派生, 与旧 _simBuildModePool 同规则)。
 * 返回 { records, byKey } records 保留 base 遍历序(新路径预期顺序), byKey 供对账。
 */
function newBuildModePool(mode) {
  const records = [];
  const byKey = new Map();
  const nShare = uniq.fields.length;            // 19
  const groupNames = Object.keys(uniq.qk_groups); // rating/etf/sig/mkt 与 base 枚举码同序
  const variants = (uniq.variants[mode] || []);
  for (let i = 0; i < uniq.base.length; i++) {
    const brow = uniq.base[i];
    const vrow = variants[i];
    if (vrow == null) continue;                 // R8: null 哨兵跳过
    // 按旧 27 列序拼行: 列在 19 共享 → base 值(顺序取), 否则 → variant 值(顺序取)
    const row27 = [];
    let si = 0, vi = 0;
    for (let ci = 0; ci < tradeFields.length; ci++) {
      row27.push(isShare[ci] ? brow[si++] : vrow[vi++]);
    }
    // 归属: 4 枚举码 → qk 名 → 前缀派生 3 聚合维度(等价 _simQkDim)
    const attr = brow.slice(nShare);            // 4 枚举码, 顺序 = groupNames
    let _mktD = "", _etfD = "", _ratD = "";
    for (let gi = 0; gi < groupNames.length; gi++) {
      const code = attr[gi];
      if (code < 0) continue;
      const qk = uniq.qk_groups[groupNames[gi]][code];
      if (qk === undefined) continue;
      const dim = qkDim(qk);
      if (!dim) continue;
      if (dim.type === "mkt" && !_mktD) _mktD = dim.val;
      else if (dim.type === "etf" && !_etfD) _etfD = dim.val;
      else if (dim.type === "rating" && !_ratD) _ratD = dim.val;
    }
    row27._mktD = _mktD; row27._etfD = _etfD; row27._ratD = _ratD;
    const bk = baseKey(row27, fIdx);
    records.push(row27);
    byKey.set(bk, row27);
  }
  return { records, byKey };
}

/**
 * 旧路径(实施期临时对比桩): 遍历 quadrants[qk][mode] 数组, 跨 qk 按 base_key 去重,
 * 首见写入 orig.slice() + 维度补值 —— 与 app.js _simBuildModePool 逐行等价。
 */
function oldBuildModePool(mode) {
  const quadrants = trades.quadrants || {};
  const seen = new Map();
  const records = [];
  for (const qk in quadrants) {
    const dim = qkDim(qk);
    const arr = (quadrants[qk] && quadrants[qk][mode]) || [];
    for (let i = 0; i < arr.length; i++) {
      const orig = arr[i];
      const bk = baseKey(orig, fIdx);
      let rec = seen.get(bk);
      if (!rec) {
        rec = orig.slice();
        rec._mktD = ""; rec._etfD = ""; rec._ratD = "";
        seen.set(bk, rec);
        records.push(rec);
      }
      if (dim) {
        if (dim.type === "mkt") { if (!rec._mktD) rec._mktD = dim.val; }
        else if (dim.type === "etf") { if (!rec._etfD) rec._etfD = dim.val; }
        else if (dim.type === "rating") { if (!rec._ratD) rec._ratD = dim.val; }
      }
    }
  }
  return { records, byKey: seen };
}

// ── 对账主流程 ─────────────────────────────────────
let allOk = true;
function assert(cond, label, detail) {
  console.log(`  ${cond ? "PASS" : "FAIL"}  ${label}${detail ? "  " + detail : ""}`);
  if (!cond) allOk = false;
}
function fmtKey(k) { return k.split("|").slice(0, 2).join("|"); }

const modes = uniq.modes || ["G"];
for (const mode of modes) {
  const oldPool = oldBuildModePool(mode);
  const newPool = newBuildModePool(mode);
  console.log(`\n[mode=${mode}] 旧 pool=${oldPool.byKey.size} 新 pool=${newPool.byKey.size}`);

  // 1) 键集相等 + 无重复
  const oldKeys = new Set(oldPool.byKey.keys());
  const newKeys = new Set(newPool.byKey.keys());
  const onlyOld = [...oldKeys].filter((k) => !newKeys.has(k));
  const onlyNew = [...newKeys].filter((k) => !oldKeys.has(k));
  const dupNew = newPool.byKey.size - newPool.records.length;
  assert(onlyOld.length === 0 && onlyNew.length === 0,
    "pool 键集相等", `原独有=${onlyOld.length}(前3: ${onlyOld.slice(0, 3).map(fmtKey).join(", ")}) 新独有=${onlyNew.length}(前3: ${onlyNew.slice(0, 3).map(fmtKey).join(", ")})`);
  assert(dupNew === 0, "新 pool 无重复 base_key", `重复=${dupNew}`);

  // 2) 每行 27 列逐位相等(排除顺序: 按 key 索引两侧行)
  let colMismatch = 0, lenMismatch = 0, missing = 0;
  let colDiffSample = null;
  for (const k of oldKeys) {
    if (!newPool.byKey.has(k)) { missing++; continue; }
    const o = oldPool.byKey.get(k);
    const n = newPool.byKey.get(k);
    if (o.length !== n.length) { lenMismatch++; continue; }
    for (let ci = 0; ci < o.length; ci++) {
      if (o[ci] !== n[ci]) {
        colMismatch++;
        if (!colDiffSample) {
          colDiffSample = { key: fmtKey(k), col: tradeFields[ci], ov: o[ci], nv: n[ci] };
        }
      }
    }
  }
  assert(lenMismatch === 0 && colMismatch === 0 && missing === 0,
    "27 列逐位相等", `行缺失=${missing} 行长不等=${lenMismatch} 列不一致=${colMismatch}` +
    (colDiffSample ? `  [样例 ${colDiffSample.key} ${colDiffSample.col}: "${colDiffSample.ov}" vs "${colDiffSample.nv}"]` : ""));

  // 3) _mktD/_etfD/_ratD 逐位相等
  let dimMismatch = 0; let dimSample = null;
  for (const k of oldKeys) {
    const o = oldPool.byKey.get(k);
    const n = newPool.byKey.get(k);
    if (!o || !n) continue;
    for (const d of ["_mktD", "_etfD", "_ratD"]) {
      if (o[d] !== n[d]) {
        dimMismatch++;
        if (!dimSample) dimSample = { key: fmtKey(k), dim: d, ov: o[d], nv: n[d] };
      }
    }
  }
  assert(dimMismatch === 0, "$_mktD/_etfD/_ratD 逐位相等".replace("$", ""),
    `不一致=${dimMismatch}` + (dimSample ? `  [样例 ${dimSample.key} ${dimSample.dim}: "${dimSample.ov}" vs "${dimSample.nv}"]` : ""));
}

// ── 汇总 ───────────────────────────────────────────
console.log("");
if (allOk) {
  console.log(`RESULT: ALL PASS (${uniq.n_base} 基笔 × ${modes.length} mode 对账)`);
  process.exit(0);
}
console.log("RESULT: FAIL");
process.exit(1);