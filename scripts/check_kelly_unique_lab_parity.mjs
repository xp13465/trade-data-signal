#!/usr/bin/env node
/**
 * lab.js 前端三表解析器对账(L42 数据瘦身 Phase C, 2026-09-21)。
 *
 * 用途: node 喂同一个 unique.json 与旧 trades.json, 分别用
 * 「lab.js 真实三表解析器(_labKellyParseTrades + 形态 C _kellyBuildTradeDims / 形态 B _kellyCollectBasePool)」与
 * 「lab.js 真实旧路径(_kellyBuildTradeDims 吃 quadrants / _kellyCollectBasePool 吃 quadrants)」构建
 * 维度表与基笔池, 断言键集 / 值 / 27 列逐位一致(方案 §四.1-3 lab 维度表 + pool 对账)。
 *
 * 关键(§5.4⑦ 同构对账铁律): 两路实现**必须来自 lab.js 源码本体**, 由本脚本从 static-site/lab.js
 * 源码提取真实函数体 eval, 不是脚本重写一份 —— 否则=第二份实现, 静默漂移无法发现。
 *
 * 用法:
 *   node scripts/check_kelly_unique_lab_parity.mjs \
 *     --unique /tmp/kelly-unique-phasea-out/signal_kelly_trades_unique.json \
 *     --trades static-site/data/signal_kelly_trades.json
 *   (可选 --lab static-site/lab.js 指定 lab.js 源码路径)
 *   (sdc 档: --unique ..._sdc_unique.json --trades ..._sdc.json)
 *
 * 内部实现提取(存在第二次实现的候选函数已剥离非本体路径):
 *   - 形态 A 还原 = _labKellyParseTrades → 惰性还原 quadrants(供 merge/热区/NavCodes 照旧)
 *   - 形态 C = _kellyBuildTradeDims(吃 td.base/variants)
 *   - 形态 B = _kellyCollectBasePool(吃 td.base/variants)
 * 对账锚点: lab 维度表「键集相等 + 值相等」、collectPool「键集相等 + 27 列逐位 + 维度逐位」。
 * 只比「集合 + 逐位值」, 不比行顺序(旧实现按 rating组×mode 遍历序, 新实现按 base 遍历序, 顺序差异是预期的)。
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
const labJsPath = args.lab || path.join(path.dirname(new URL(import.meta.url).pathname), "..", "static-site", "lab.js");
const labSrc = fs.readFileSync(labJsPath, "utf8");
if (!uniqPath || !tradesPath) {
  console.error("用法: node check_kelly_unique_lab_parity.mjs --unique <unique.json> --trades <trades.json> [--lab <lab.js>]");
  process.exit(2);
}

const uniq = JSON.parse(fs.readFileSync(uniqPath, "utf8"));
const trades = JSON.parse(fs.readFileSync(tradesPath, "utf8"));

// ── lab.js 真实函数体提取(不重写=无第二份实现) ──
// 与 check_kelly_unique_frontend_parity.mjs 同机制: 定位声明后按花括号配平截取, 跳过字符串/模板串/注释。
function extractBlock(src, declRe, name) {
  const re = new RegExp(declRe, "g");
  re.lastIndex = 0;
  const m = re.exec(src);
  if (!m) throw new Error("lab.js 未找到声明: " + name + " (declRe=" + declRe + ")");
  // async 前缀(lab 的 _kellyCollectBasePool 声明为 `async function`), 往前含入否则 eval 后非 async 函数
  const pre = src.slice(Math.max(0, m.index - 6), m.index);
  const start = /^async\s+$/.test(pre) ? m.index - 6 : m.index;
  let i = src.indexOf("{", start);
  if (i < 0) throw new Error("lab.js 声明无函数体: " + name);
  let depth = 0;
  let quote = null, lineCm = false, blockCm = false;
  for (let j = i; j < src.length; j++) {
    const ch = src[j], nx = src[j + 1];
    if (lineCm) { if (ch === "\n") lineCm = false; continue; }
    if (blockCm) { if (ch === "*" && nx === "/") { blockCm = false; j++; } continue; }
    if (quote) {
      if (ch === "\\") { j++; continue; }
      if (ch === quote) quote = null;
      continue;
    }
    if (ch === "/" && nx === "/") { lineCm = true; j++; continue; }
    if (ch === "/" && nx === "*") { blockCm = true; j++; continue; }
    if (ch === '"' || ch === "'") { quote = ch; continue; }
    if (ch === "{") depth++;
    else if (ch === "}") { depth--; if (depth === 0) return src.slice(start, j + 1); }
  }
  throw new Error("lab.js 声明花括号未配平: " + name);
}
const blkFields27 = extractBlock(labSrc, "const\\s+_LAB_UNIQUE_FIELDS27\\s*=\\s*\\[", "_LAB_UNIQUE_FIELDS27");
const blkParts = ["_labKellyParseTrades", "_labKellyParseUnique", "_kellySynthRow27", "_labKellyMergeShards",
  "_kellyBaseKey", "_kellyBuildTradeDims", "_kellyBuildTradeDimsUnique",
  "_kellyCollectBasePool", "_kellyCollectBasePoolUnique"].map((n) =>
  extractBlock(labSrc, "function\\s+" + n + "\\s*\\(", n));
// 统一 scope eval(函数声明提升 + const 首置 + _kellyYield 补齐), 导出真实实现
const _labSandbox = new Function(
  "var _kellyYield = function () { return new Promise(function (r) { setTimeout(r, 0); }); };\n" +
  [blkFields27, ...blkParts].join("\n") +
  "\nreturn { _LAB_UNIQUE_FIELDS27, _labKellyParseTrades, _labKellyMergeShards, _kellyBuildTradeDims, _kellyCollectBasePool, _kellyBaseKey };"
);
const { _LAB_UNIQUE_FIELDS27, _labKellyParseTrades, _labKellyMergeShards, _kellyBuildTradeDims, _kellyCollectBasePool, _kellyBaseKey } = _labSandbox();

// ── 列映射: 旧 trades.fields(27 列)为基准列序 ──
const tradeFields = trades.fields;
const fIdxOld = {};
tradeFields.forEach((f, i) => { fIdxOld[f] = i; });

// ── 对账主流程 ─────────────────────────────────────
let allOk = true;
function assert(cond, label, detail) {
  console.log(`  ${cond ? "PASS" : "FAIL"}  ${label}${detail ? "  " + detail : ""}`);
  if (!cond) allOk = false;
}
function fmtKey(k) { return k.split("|").slice(0, 2).join("|"); }

// 守卫: lab 27 列合成序必须与旧 trades.fields 完全一致(逐位对账的前提)
{
  const same = _LAB_UNIQUE_FIELDS27.length === tradeFields.length &&
    _LAB_UNIQUE_FIELDS27.every((f, i) => f === tradeFields[i]);
  assert(same, "lab _LAB_UNIQUE_FIELDS27 == 旧 trades.fields 列序", `lab27=${_LAB_UNIQUE_FIELDS27.length} old27=${tradeFields.length}`);
  if (!same) { console.error("RESULT: FAIL (列序不符, 无法逐位对账)"); process.exit(1); }
}

// 新路径(真实 lab): unique 三表 → 解析(透传 base/variants + 惰性还原形态 A quadrants)
const parsedUniq = _labKellyParseTrades(uniq);
// 老路径(真实 lab legacy): 旧 trades quadrants 直读, 包装成 oldData(fields/fIdx/quadrants)
const oldData = { fields: tradeFields, fIdx: fIdxOld, quadrants: trades.quadrants || {} };

// sellModes 参数(形态 B 只取 key 遍历, 内容不重要): 用 uniq.modes 构造 {A:{},...}
const modes = uniq.modes || ["A", "B", "C", "D", "E", "F", "J", "G", "H", "I"];
const sellModes = {};
for (const m of modes) sellModes[m] = {};

// ── 1) 形态 A 还原 quadrants 逐位 == 旧 quadrants(merge/热区/NavCodes/统计桶消费还原行) ──
{
  let rowMismatch = 0, lenMismatch = 0, missing = 0, sample = null;
  const oldQs = trades.quadrants || {};
  const newQs = parsedUniq.quadrants || {};
  const qkSet = new Set([...Object.keys(oldQs), ...Object.keys(newQs)]);
  for (const qk of qkSet) {
    const om = oldQs[qk] || {};
    const nm = newQs[qk] || {};
    const mkSet = new Set([...Object.keys(om), ...Object.keys(nm)]);
    for (const mk of mkSet) {
      const oarr = om[mk] || [];
      const narr = nm[mk] || [];
      if (oarr.length !== narr.length) { missing++; if (!sample) sample = { qk, mk, d: `len ${oarr.length} vs ${narr.length}` }; continue; }
      for (let i = 0; i < oarr.length; i++) {
        const o = oarr[i], n = narr[i];
        if (o.length !== n.length) { lenMismatch++; if (!sample) sample = { qk, mk, d: `rowlen ${o.length} vs ${n.length}` }; continue; }
        for (let ci = 0; ci < o.length; ci++) {
          if (o[ci] !== n[ci]) { rowMismatch++; if (!sample) sample = { qk, mk, col: tradeFields[ci], ov: o[ci], nv: n[ci] }; }
        }
      }
    }
  }
  assert(missing === 0 && rowMismatch === 0 && lenMismatch === 0,
    "形态A还原 quadrants 逐位 == 旧 quadrants",
    `行数不等=${missing} 行长不等=${lenMismatch} 列不一致=${rowMismatch}` +
    (sample ? `  [样例 ${sample.qk}/${sample.mk} ${sample.col || ""}: "${sample.ov}" vs "${sample.nv}"${sample.d ? " " + sample.d : ""}]` : ""));
}

// ── 2) lab 维度表(形态 C vs 旧 _kellyBuildTradeDims): 键集相等 + 值相等 ──
{
  const dimsNew = _kellyBuildTradeDims(parsedUniq, fIdxOld);   // 三表 → 形态 C
  const dimsOld = _kellyBuildTradeDims(oldData, fIdxOld);      // 老 quadrants → 旧路径
  const oldKeys = Object.keys(dimsOld);
  const newSet = new Set(Object.keys(dimsNew));
  const onlyOld = oldKeys.filter((k) => !newSet.has(k));
  const onlyNew = Object.keys(dimsNew).filter((k) => !(k in dimsOld));
  let valMismatch = 0, dimSample = null;
  for (const k of oldKeys) {
    const o = dimsOld[k], n = dimsNew[k];
    if (!n) continue;
    const dimsSet = new Set([...Object.keys(o), ...Object.keys(n)]);
    for (const d of dimsSet) {
      if (String(o[d] === undefined ? "" : o[d]) !== String(n[d] === undefined ? "" : n[d])) {
        valMismatch++;
        if (!dimSample) dimSample = { key: fmtKey(k), dim: d, ov: o[d], nv: n[d] };
      }
    }
  }
  assert(onlyOld.length === 0 && onlyNew.length === 0,
    "维度表键集相等", `旧独有=${onlyOld.length}(前2: ${onlyOld.slice(0, 2).map(fmtKey).join(", ")}) 新独有=${onlyNew.length}(前2: ${onlyNew.slice(0, 2).map(fmtKey).join(", ")})`);
  assert(valMismatch === 0, "维度表值逐位相等",
    `不一致=${valMismatch}` + (dimSample ? `  [样例 ${dimSample.key} ${dimSample.d}: "${dimSample.ov}" vs "${dimSample.nv}"]` : ""));
  console.log(`  [维度表] 旧 key=${oldKeys.length} 新 key=${Object.keys(dimsNew).length}  (期望 n_base×mode = ${uniq.n_base}×${modes.length})`);
}

// ── 3) lab 基笔池(形态 B vs 旧): 键集相等 + 27 列逐位 + 无重复 ──
async function poolCompare(skipLabel, skipKey) {
  // 旧路径第一参期望 quadrants 对象本体(旧调用点传 td.quadrants), 非包装对象
  const oldPool = await _kellyCollectBasePool(trades.quadrants || {}, sellModes, fIdxOld, null, skipKey);
  const newPool = await _kellyCollectBasePool(parsedUniq, sellModes, fIdxOld, null, skipKey);
  const oldByKey = new Map();
  for (const rec of oldPool) oldByKey.set(_kellyBaseKey(rec, fIdxOld), rec);
  const newByKey = new Map();
  for (const rec of newPool) newByKey.set(_kellyBaseKey(rec, fIdxOld), rec);
  const oldKeys = new Set(oldByKey.keys());
  const newKeys = new Set(newByKey.keys());
  const onlyOld = [...oldKeys].filter((k) => !newKeys.has(k));
  const onlyNew = [...newKeys].filter((k) => !oldKeys.has(k));
  const dupNew = newByKey.size - newPool.length;
  console.log(`\n[${skipLabel}] 旧 pool=${oldByKey.size} 新 pool=${newByKey.size} (base=${uniq.n_base})`);
  assert(onlyOld.length === 0 && onlyNew.length === 0,
    "pool 键集相等", `原独有=${onlyOld.length}(前3: ${onlyOld.slice(0, 3).map(fmtKey).join(", ")}) 新独有=${onlyNew.length}(前3: ${onlyNew.slice(0, 3).map(fmtKey).join(", ")})`);
  assert(dupNew === 0, "新 pool 无重复 base_key", `重复=${dupNew}`);
  let colMismatch = 0, lenMismatch = 0, missing = 0, colDiffSample = null;
  for (const k of oldKeys) {
    if (!newByKey.has(k)) { missing++; continue; }
    const o = oldByKey.get(k);
    const n = newByKey.get(k);
    if (o.length !== n.length) { lenMismatch++; continue; }
    for (let ci = 0; ci < o.length; ci++) {
      if (o[ci] !== n[ci]) {
        colMismatch++;
        if (!colDiffSample) colDiffSample = { key: fmtKey(k), col: tradeFields[ci], ov: o[ci], nv: n[ci] };
      }
    }
  }
  assert(lenMismatch === 0 && colMismatch === 0 && missing === 0,
    "pool 27 列逐位相等", `行缺失=${missing} 行长不等=${lenMismatch} 列不一致=${colMismatch}` +
    (colDiffSample ? `  [样例 ${colDiffSample.key} ${colDiffSample.col}: "${colDiffSample.ov}" vs "${colDiffSample.nv}"]` : ""));
}
await poolCompare("全池", null);
await poolCompare("剔rating_high(s06p1 K=1)", "rating_high");

// ── 4) 分片 merge 透传冒烟(本次改造点 _labKellyMergeShards 的 base/variants 透传合并, R7) ──
// 分片按 signal_date 互斥、base 与 variants 行对齐; 把全量 unique 切成「伪两片」各自 parse 再 merge,
// 断言合并后 base/variants/quadrants 与全量逐位一致、消费(形态C维度表/形态B pool)与全量一致。
{
  const full = _labKellyParseTrades(uniq);
  const half = Math.floor(uniq.base.length / 2);
  const mkUniq = (i0, i1) => {
    const vs = {};
    for (const m of modes) vs[m] = (uniq.variants[m] || []).slice(i0, i1);
    return { fields: uniq.fields, variant_fields: uniq.variant_fields, qk_groups: uniq.qk_groups,
      base_key_fields: uniq.base_key_fields, base: uniq.base.slice(i0, i1), variants: vs };
  };
  const s1 = _labKellyParseTrades(mkUniq(0, half));
  const s2 = _labKellyParseTrades(mkUniq(half, uniq.base.length));
  const merged = _labKellyMergeShards([s1, s2]);
  let alignFail = 0;
  if (merged.base.length !== full.base.length) alignFail++;
  for (let i = 0; i < full.base.length && i < merged.base.length; i++) {
    if (merged.base[i] !== full.base[i]) { alignFail++; break; }
  }
  for (const m of modes) {
    const mv = merged.variants[m] || [], fv = full.variants[m] || [];
    if (mv.length !== fv.length) { alignFail++; continue; }
    for (let i = 0; i < fv.length; i++) if (mv[i] !== fv[i]) { alignFail++; break; }
  }
  assert(alignFail === 0, "merge base/variants 透传合并与全量对齐(引用级)",
    `base=${merged.base.length}/${full.base.length} 不一致=${alignFail}`);
  // merge 后消费与全量一致: 形态 C 维度表 + 形态 B pool
  const dimsM = _kellyBuildTradeDims(merged, fIdxOld);
  const dimsF = _kellyBuildTradeDims(full, fIdxOld);
  const dmKeys = new Set(Object.keys(dimsM));
  let dimDiff = 0;
  for (const k of Object.keys(dimsF)) {
    if (!dmKeys.has(k)) { dimDiff++; continue; }
    const o = dimsF[k], n = dimsM[k];
    const ds = new Set([...Object.keys(o), ...Object.keys(n)]);
    for (const d of ds) if (String(o[d] === undefined ? "" : o[d]) !== String(n[d] === undefined ? "" : n[d])) dimDiff++;
  }
  assert(Object.keys(dimsM).length === Object.keys(dimsF).length && dimDiff === 0,
    "merge 后形态C 维度表与全量一致", `key=${Object.keys(dimsM).length}/${Object.keys(dimsF).length} 不一致=${dimDiff}`);
  const poolM = await _kellyCollectBasePool(merged, sellModes, fIdxOld, null, null);
  const poolF = await _kellyCollectBasePool(full, sellModes, fIdxOld, null, null);
  const pm = new Set(poolM.map((r) => _kellyBaseKey(r, fIdxOld)));
  const pf = new Set(poolF.map((r) => _kellyBaseKey(r, fIdxOld)));
  let poolMiss = 0;
  for (const k of pf) if (!pm.has(k)) poolMiss++;
  assert(poolM.length === poolF.length && poolMiss === 0,
    "merge 后形态B pool 与全量一致", `pool=${poolM.length}/${poolF.length} 缺=${poolMiss}`);
}

// ── 汇总 ───────────────────────────────────────────
console.log("");
if (allOk) {
  console.log(`RESULT: ALL PASS (${uniq.n_base} 基笔 × ${modes.length} mode 对账, 解析器来自 lab.js 本体)`);
  process.exit(0);
}
console.log("RESULT: FAIL");
process.exit(1);