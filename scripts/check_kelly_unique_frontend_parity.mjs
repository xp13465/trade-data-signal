#!/usr/bin/env node
/**
 * 前端三表解析器对账(L42 数据瘦身前端改造 Phase A 基建 / Phase B 实施验收, 2026-09-20/21)。
 *
 * 用途: node 喂同一个 unique.json 与旧 trades.json, 分别用
 * 「app.js 真实三表解析器(形态 B: _simParseTrades + _simBuildModePool)」与
 * 「app.js 真实旧路径(_simBuildModePoolLegacy, quadrants 直读)」构建同一 mode pool,
 * 断言 pool 键集 / 27 列逐位 / _mktD/_etfD/_ratD 一致 (§四.1-3 前端解析器对账)。
 *
 * 关键(§5.4⑦ 同构对账铁律, Phase B 验收要求): 两路解析器/建池函数**必须来自 app.js 源码本体**,
 * 由本脚本从 static-site/app.js 源码提取真实函数体 eval, 不是脚本重写一份 —— 否则=第二份实现, 静默漂移无法发现。
 *
 * 用法:
 *   node scripts/check_kelly_unique_frontend_parity.mjs \
 *     --unique /tmp/kelly-unique-phasea-out/signal_kelly_trades_unique.json \
 *     --trades static-site/data/signal_kelly_trades.json
 *   (可选 --app static-site/app.js 指定 app.js 源码路径)
 *   (sdc 档: --unique ..._sdc_unique.json --trades ..._sdc.json)
 *
 * 只比「集合 + 逐位值」, 不比行顺序: 旧实现按 qk 遍历序见首写入, 新实现按 base 遍历序直建,
 * 顺序差异是预期的(方案 §四.1-3)。任意断言 FAIL 退出码 1。
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
const appJsPath = args.app || path.join(path.dirname(new URL(import.meta.url).pathname), "..", "static-site", "app.js");
const appSrc = fs.readFileSync(appJsPath, "utf8");
if (!uniqPath || !tradesPath) {
  console.error("用法: node check_kelly_unique_frontend_parity.mjs --unique <unique.json> --trades <trades.json> [--app <app.js>]");
  process.exit(2);
}

const uniq = JSON.parse(fs.readFileSync(uniqPath, "utf8"));
const trades = JSON.parse(fs.readFileSync(tradesPath, "utf8"));

// ── app.js 真实函数体提取(不重写=无第二份实现) ──
// 迷你词法器: 定位目标声明后按花括号配平截取, 跳过字符串/模板串/注释内容, 防「字符串里的花括号」误切。
function extractBlock(src, declRe, name) {
  const re = new RegExp(declRe, "g");
  re.lastIndex = 0;
  const m = re.exec(src);
  if (!m) throw new Error("app.js 未找到声明: " + name + " (declRe=" + declRe + ")");
  let i = src.indexOf("{", m.index);
  if (i < 0) throw new Error("app.js 声明无函数体: " + name);
  let depth = 0;
  let quote = null, tpl = false, lineCm = false, blockCm = false;
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
    else if (ch === "}") { depth--; if (depth === 0) return src.slice(m.index, j + 1); }
  }
  throw new Error("app.js 声明花括号未配平: " + name);
}
const blkFields27 = extractBlock(appSrc, "var\\s+_SIM_UNIQUE_FIELDS27\\s*=\\s*\\[", "_SIM_UNIQUE_FIELDS27");
const blkParts = ["_simQkDim", "_simBaseKey", "_simSynthRow27", "_simParseTrades", "_simParseUnique",
  "_simBuildModePool", "_simBuildModePoolLegacy"].map((n) =>
  extractBlock(appSrc, "function\\s+" + n + "\\s*\\(", n));
// 统一 scope eval(函数间交叉引用靠函数声明提升 + var 共享), 导出真实实现
const _appSandbox = new Function(
  [blkFields27, ...blkParts].join("\n") +
  "\nreturn { _SIM_UNIQUE_FIELDS27, _simParseTrades, _simBuildModePool, _simBuildModePoolLegacy, _simBaseKey, _simQkDim };"
);
const { _SIM_UNIQUE_FIELDS27, _simParseTrades, _simBuildModePool, _simBuildModePoolLegacy, _simBaseKey, _simQkDim } = _appSandbox();

// ── 列映射: 旧 trades.fields(27 列)为基准列序 ──
const tradeFields = trades.fields;              // 27 列
const fIdxOld = {};
tradeFields.forEach((f, i) => { fIdxOld[f] = i; });

// ── 对账主流程 ─────────────────────────────────────
let allOk = true;
function assert(cond, label, detail) {
  console.log(`  ${cond ? "PASS" : "FAIL"}  ${label}${detail ? "  " + detail : ""}`);
  if (!cond) allOk = false;
}
function fmtKey(k) { return k.split("|").slice(0, 2).join("|"); }

// 守卫: app.js 27 列合成序必须与旧 trades.fields 完全一致(逐位对账的前提)
{
  const same = _SIM_UNIQUE_FIELDS27.length === tradeFields.length &&
    _SIM_UNIQUE_FIELDS27.every((f, i) => f === tradeFields[i]);
  assert(same, "app.js _SIM_UNIQUE_FIELDS27 == 旧 trades.fields 列序", `app27=${_SIM_UNIQUE_FIELDS27.length} old27=${tradeFields.length}`);
  if (!same) { console.error("RESULT: FAIL (列序不符, 无法逐位对账)"); process.exit(1); }
}

// 新路径(真实 app.js): unique 三表 → 解析 → 形态 B 建池
const parsedUniq = _simParseTrades(uniq);
// 老路径(真实 app.js legacy): 旧 trades quadrants 直读
const oldData = { fIdx: fIdxOld, quadrants: trades.quadrants || {} };

const modes = uniq.modes || ["G"];
for (const mode of modes) {
  const oldPool = _simBuildModePoolLegacy(oldData, mode);
  const newPool = _simBuildModePool(parsedUniq, mode);
  // byKey 映射(base_key → row27)
  const oldByKey = new Map();
  for (const rec of oldPool) oldByKey.set(_simBaseKey(rec, fIdxOld), rec);
  const newByKey = new Map();
  for (const rec of newPool) newByKey.set(_simBaseKey(rec, fIdxOld), rec);
  console.log(`\n[mode=${mode}] 旧 pool=${oldByKey.size} 新 pool=${newByKey.size}`);

  // 1) 键集相等 + 无重复
  const oldKeys = new Set(oldByKey.keys());
  const newKeys = new Set(newByKey.keys());
  const onlyOld = [...oldKeys].filter((k) => !newKeys.has(k));
  const onlyNew = [...newKeys].filter((k) => !oldKeys.has(k));
  const dupNew = newByKey.size - newPool.length;
  assert(onlyOld.length === 0 && onlyNew.length === 0,
    "pool 键集相等", `原独有=${onlyOld.length}(前3: ${onlyOld.slice(0, 3).map(fmtKey).join(", ")}) 新独有=${onlyNew.length}(前3: ${onlyNew.slice(0, 3).map(fmtKey).join(", ")})`);
  assert(dupNew === 0, "新 pool 无重复 base_key", `重复=${dupNew}`);

  // 2) 每行 27 列逐位相等(排除顺序: 按 key 索引两侧行)
  let colMismatch = 0, lenMismatch = 0, missing = 0;
  let colDiffSample = null;
  for (const k of oldKeys) {
    if (!newByKey.has(k)) { missing++; continue; }
    const o = oldByKey.get(k);
    const n = newByKey.get(k);
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
    const o = oldByKey.get(k);
    const n = newByKey.get(k);
    if (!o || !n) continue;
    for (const d of ["_mktD", "_etfD", "_ratD"]) {
      if (o[d] !== n[d]) {
        dimMismatch++;
        if (!dimSample) dimSample = { key: fmtKey(k), dim: d, ov: o[d], nv: n[d] };
      }
    }
  }
  assert(dimMismatch === 0, "_mktD/_etfD/_ratD 逐位相等",
    `不一致=${dimMismatch}` + (dimSample ? `  [样例 ${dimSample.key} ${dimSample.dim}: "${dimSample.ov}" vs "${dimSample.nv}"]` : ""));
}

// 4) 形态 A 还原(2026-09-21 Phase B 追加): app.js _simParseTrades 还原的 quadrants 逐位 == 旧 trades quadrants
//    (merge/热区消费还原行, 必须与旧结构逐位一致才保证分片路径数值零改动)
{
  let rowMismatch = 0, lenMismatch = 0, missing = 0, extra = 0;
  let sample = null;
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
          if (o[ci] !== n[ci]) {
            rowMismatch++;
            if (!sample) sample = { qk, mk, col: tradeFields[ci], ov: o[ci], nv: n[ci] };
          }
        }
      }
    }
  }
  // 边数: 旧全 16 qk × 10 mode; 新还原应相同条数(求和规约成异常计数)
  assert(extra === 0 && rowMismatch === 0 && lenMismatch === 0 && missing === 0,
    "形态A还原 quadrants 逐位 == 旧 quadrants",
    `行长不等=${lenMismatch} 行数不等=${missing} 列不一致=${rowMismatch}` +
    (sample ? `  [样例 ${sample.qk}/${sample.mk} ${sample.col || ""}: "${sample.ov}" vs "${sample.nv}"${sample.d ? " " + sample.d : ""}]` : ""));
}

// ── 汇总 ───────────────────────────────────────────
console.log("");
if (allOk) {
  console.log(`RESULT: ALL PASS (${uniq.n_base} 基笔 × ${modes.length} mode 对账, 解析器来自 app.js 本体)`);
  process.exit(0);
}
console.log("RESULT: FAIL");
process.exit(1);