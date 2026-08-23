#!/usr/bin/env node
/**
 * AI降亏过滤谓词·规格化迁移一致性校验(T3-1 2026-08-23, §23.2 修bug三铁律②自测完成)。
 *
 * 【目的】断言「老37键迁 spec-driven 规格」前后, lab.js/app.js 两份重放谓词在全量信号行×57键上
 *         命中集合逐位一致(0 不一致)。方法=T1 check_loss_rules_vs_mining.py 同精神:
 *         不重写判定逻辑做影子对照, 而是把真实源码里的函数体切片提取后放进 vm 沙箱执行,
 *         保证验的就是上线代码本身。
 * 【方法】① 从源码文本按符号名切片提取函数体(引号/注释感知的括号配平, 不整文件 eval——
 *           lab/app 顶层有 DOM/window 依赖无法直接加载);
 *         ② 三份源码参与: common.js(新规格单源, 旧版无此符号自动跳过) + lab.js + app.js;
 *         ③ 数据=signal_kelly_trades.json 全部象限 mode A 行(谓词不感知卖出模式, A 并集即全量基笔);
 *            _tradeDims 用真实 _kellyBuildTradeDims 构建; T1 20 新键经 meta.rules(kelly_loss_features.json)
 *            注入 stub(state/_simLossFeatData);
 *         ④ 对每个键 k: filters=默认集+k 单开, monthMask=真实 activeMonthMask(filters), 逐行判定,
 *            收集每键命中行 id 集合; 新旧两版逐键比对。
 * 【输入】env TRADES_JSON(默认主仓库 static-site/data/signal_kelly_trades.json; worktree 无 gitignored
 *         数据产物必须指绝对路径) + env FEAT_JSON(同) ;--ref <gitref> 取历史版本源码(git show)。
 * 【输出】终端逐键 PASS/FAIL + 总结; 任一不一致 exit 1。
 * 【复现】迁移前基线:  node scripts/check_fade_predicate_parity.mjs --ref cf66741d5 --out /tmp/t31-base.json
 *         迁移后对比:  node scripts/check_fade_predicate_parity.mjs --base /tmp/t31-base.json
 *         (--base 缺省时自动用 --ref cf66741d5 现场重提旧版对照)
 */
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { execSync } from "node:child_process";

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const REF = (() => {
  const i = process.argv.indexOf("--ref");
  return i > 0 ? process.argv[i + 1] : null;
})();
const BASE = (() => {
  const i = process.argv.indexOf("--base");
  return i > 0 ? process.argv[i + 1] : null;
})();
const OUT = (() => {
  const i = process.argv.indexOf("--out");
  return i > 0 ? process.argv[i + 1] : null;
})();

const TRADES_JSON = process.env.TRADES_JSON || "/Users/linhuichen/code/trade/static-site/data/signal_kelly_trades.json";
const FEAT_JSON = process.env.FEAT_JSON || "/Users/linhuichen/code/trade/static-site/data/kelly_loss_features.json";

// ---------------------------------------------------------------------------
// 源码获取: --ref 时 git show 历史版本, 否则读当前工作区
// ---------------------------------------------------------------------------
function srcOf(rel) {
  if (REF) return execSync(`git show ${REF}:${rel}`, { cwd: ROOT, maxBuffer: 64 << 20 }).toString();
  return fs.readFileSync(path.join(ROOT, rel), "utf8");
}

// ---------------------------------------------------------------------------
// 切片提取: 定位声明起点, 引号/注释感知括号配平到语句结束
// ---------------------------------------------------------------------------
function sliceDecl(src, name) {
  // 匹配 function NAME( ... ) / var|const|let NAME = ...
  const pats = [
    new RegExp(`(?:^|\\n)\\s*function\\s+${name}\\s*\\(`),
    new RegExp(`(?:^|\\n)\\s*(?:var|const|let)\\s+${name}\\s*=`),
  ];
  let start = -1, kind = null;
  for (let i = 0; i < pats.length; i++) {
    const m = src.match(pats[i]);
    if (m) { start = m.index + (/^\n/.test(m[0]) ? 1 : 0); kind = i === 0 ? "fn" : "decl"; break; }
  }
  if (start < 0) return null;
  // 扫描器: 跳过字符串/模板串/注释后做括号配平
  // fn 形态: 先配平参数表 ( ... ), 再配平函数体 { ... }; decl 形态: 配平第一个括号组后吃分号
  let i = start, inS = null, esc = false;
  const isPair = (a, b) => (a === "(" && b === ")") || (a === "{" && b === "}") || (a === "[" && b === "]");
  function scanBlock(from, openCh) {
    let depth = 0, j = from;
    for (; j < src.length; j++) {
      const c = src[j], n = src[j + 1];
      if (inS === "//") { if (c === "\n") inS = null; continue; }
      if (inS === "/*") { if (c === "*" && n === "/") { inS = null; j++; } continue; }
      if (inS === "'" || inS === '"' || inS === "`") { if (esc) { esc = false; continue; } if (c === "\\") { esc = true; continue; } if (c === inS) inS = null; continue; }
      if (c === "'" || c === '"' || c === "`") { inS = c; continue; }
      if (c === "/" && n === "/") { inS = "//"; j++; continue; }
      if (c === "/" && n === "*") { inS = "/*"; j++; continue; }
      if (c === openCh) depth++;
      else if (c === (openCh === "(" ? ")" : openCh === "{" ? "}" : "]")) { depth--; if (depth === 0) return j; }
    }
    return -1;
  }
  let bodyEnd = -1;
  if (kind === "fn") {
    // 跳过函数名与参数表: 找第一个 "(" 配平, 然后找其后的第一个 "{"
    let p = src.indexOf("(", start);
    if (p < 0) return null;
    const pEnd = scanBlock(p, "(");
    if (pEnd < 0) return null;
    let b = pEnd + 1;
    while (b < src.length && /\s/.test(src[b])) b++;
    if (src[b] !== "{") return null;
    bodyEnd = scanBlock(b, "{");
    if (bodyEnd < 0) return null;
    return src.slice(start, bodyEnd + 1);
  }
  // decl: 第一个开括号组配平 + 可选分号
  let p = start;
  while (p < src.length && !"([{".includes(src[p])) p++;
  if (p >= src.length) return null;
  const openCh = src[p];
  bodyEnd = scanBlock(p, openCh);
  if (bodyEnd < 0) return null;
  let end = bodyEnd + 1;
  while (end < src.length && /\s/.test(src[end])) { if (src[end] === ";") { end++; break; } end++; }
  return src.slice(start, end);
}

function buildContext(sources) {
  // sources: [{rel, text}]; 先 common 后 lab/app(消费方依赖 common 符号)
  const ctx = vm.createContext({ console, JSON, Math, Date, isFinite, parseFloat, parseInt, String, Number, Boolean, Array, Object });
  const missing = [];
  for (const s of sources) {
    ctx.__srcRel__ = s.rel;
    for (const name of s.symbols) {
      const code = sliceDecl(s.text, name);
      if (code == null) { missing.push(`${s.rel}#${name}`); continue; }
      try { vm.runInContext(code, ctx, { filename: `${s.rel}::${name}` }); }
      catch (e) { throw new Error(`eval ${s.rel}#${name}: ${e.message}`); }
    }
  }
  return { ctx, missing };
}

// ---------------------------------------------------------------------------
// 主流程
// ---------------------------------------------------------------------------
const COMMON_SYMBOLS = [
  "_KELLY_FADE_LEGACY_SPECS", "_KELLY_FADE_GATE_KEY_ORDER", "_KELLY_FADE_FRONT_KEY_ORDER",
  "_tdsFadeSpecHit", "_KELLY_FADE_MODE_PRESETS", "_tdsFadeModeApply", "_tdsFadeModeSelectHTML",
];
const LAB_SYMBOLS = [
  "_KELLY_LOSS_NEW_KEYS", "_kellyBuyWeekday", "_kellyBuypriceBin", "_kellyBuildTradeDims",
  "_kellyDefaultFilters", "_kellyTradeFeatures", "_kellyMonthMask", "_kellyActiveMonthMask",
  "_kellyLossRuleHit", "_kellyPassesFadeFilters",
];
const APP_SYMBOLS = [
  "_SIM_LOSS_NEW_KEYS", "_simBuyWeekday", "_simBuypriceBin", "_simQkDim", "_simBaseKey",
  "_simBuildModePool", "_simDefaultFadeFilters", "_simMonthMask", "_simActiveMonthMask",
  "_simLossRuleHit", "_simPassesFade", "_simPassesBullStop",
];

// 老 37 键(bullAuxBackupStop 在 app 侧为独立谓词, 由 _simPassesBullStop 单独校验)
const LEGACY_37 = [
  "excludeAux", "marketTiming", "excludeMonth", "excludeRatingLow", "excludeAuxCross",
  "excludeSpecialBear", "legacyMa60Special", "declinePhaseSpecial", "excludeSpecialBearCyb",
  "bullAuxBackupStop",
  "n1MarTueHigh", "n2NovSpecialIndustry", "r8PureNonMay", "n3NovSpecialMon", "n4AMay",
  "r7MayReinforced", "n5MayVlow", "n6MidMay", "r10May6NonMay",
  "v4cSimple", "v4b", "greedy7", "v4d", "v4j", "v4i", "greedy10", "v4f", "v4g", "v4m", "v4k", "greedy15",
  "a5NovMidSpecial", "a45NovMidLateSpecial", "janMidRating", "janMidSpecial",
  "k2c5HkChase", "k3ConceptBuy",
];

console.log(`[parity] ref=${REF || "(working tree)"} trades=${TRADES_JSON}`);
const td = JSON.parse(fs.readFileSync(TRADES_JSON, "utf8"));
let featDoc = null;
try { featDoc = JSON.parse(fs.readFileSync(FEAT_JSON, "utf8")); } catch { featDoc = null; }

const fIdx = {};
(td.fields || []).forEach((f, i) => { fIdx[f] = i; });
if (fIdx.signal == null || fIdx.buy_date == null) throw new Error("fields 缺 signal/buy_date");

// 行集 = 全部象限 × mode A(谓词不感知 mode, A 并集=全量基笔; 含跨象限重复, 判定幂等)
const rowsLab = [];   // 原始行(lab 谓词输入, 维度走 dims map)
for (const qk of Object.keys(td.quadrants || {})) {
  const arr = (td.quadrants[qk] || {}).A || [];
  for (const r of arr) rowsLab.push(r);
}
console.log(`[parity] mode A 行数(含象限重复)=${rowsLab.length}`);

function runSide(tag) {
  const sources = [
    { rel: "static-site/common.js", symbols: COMMON_SYMBOLS },
    { rel: "static-site/lab.js", symbols: LAB_SYMBOLS },
    { rel: "static-site/app.js", symbols: APP_SYMBOLS },
  ].map((s) => ({ rel: s.rel, symbols: s.symbols, text: srcOf(s.rel) }));
  const { ctx, missing } = buildContext(sources);
  if (missing.length) {
    const needSpec = missing.some((m) => m.includes("LEGACY_SPECS") || m.includes("_tdsFade"));
    console.log(`[parity][${tag}] 未提取符号(${missing.length}): ${missing.join(", ")}${needSpec ? "  ← 规格层不存在=旧实现路径(正常)" : ""}`);
  }
  vm.runInContext(`
    var __stubState = { kellyLossFeatData: null, kellyLossSpecMap: {} };
    var state = __stubState;
    var _simLossFeatData = null;   // app.js 模块级 let 的沙箱替身
  `, ctx);
  if (featDoc) {
    vm.runInContext(`
      __stubState.kellyLossFeatData = __FEAT__;
      _simLossFeatData = __FEAT__;
      ((__FEAT__.meta && __FEAT__.meta.rules) || []).forEach(function (r) { __stubState.kellyLossSpecMap[r.key] = r; });
    `, Object.assign(ctx, { __FEAT__: featDoc }));
  }
  // 数据注入(结构化克隆进沙箱)
  vm.runInContext(`
    var __td = __TD__, __fIdx = __FIDX__;
    var __dims = _kellyBuildTradeDims(__td, __fIdx);
    var __poolData = { fIdx: __fIdx, quadrants: __td.quadrants };
    var __recs = _simBuildModePool(__poolData, "A");
  `, Object.assign(ctx, { __TD__: td, __FIDX__: fIdx }));
  const nRec = vm.runInContext("__recs.length", ctx);

  const keys = [];
  const defaultsLab = vm.runInContext("JSON.stringify(_kellyDefaultFilters())", ctx);
  const defaultsApp = vm.runInContext("JSON.stringify(_simDefaultFadeFilters())", ctx);
  const t1Keys = vm.runInContext("_KELLY_LOSS_NEW_KEYS.map(function(p){return p[0];})", ctx);
  const allKeys = LEGACY_37.concat(t1Keys);
  const result = { lab: {}, sim: {}, simBullStop: null, nRows: rowsLab.length, nRec };

  for (const k of allKeys) {
    // --- lab 侧 ---
    const fLab = JSON.parse(defaultsLab); fLab[k] = true;
    ctx.__fLab = fLab;
    result.lab[k] = vm.runInContext(`
      (function () {
        var mm = _kellyActiveMonthMask(__fLab);
        var cache = new Map();
        var hits = [];
        for (var i = 0; i < rowsRef.length; i++) {
          if (!_kellyPassesFadeFilters(rowsRef[i], __fIdx, __fLab, cache, __dims, mm)) hits.push(rowsRef[i]);
        }
        return hits;
      })()
    `, Object.assign(ctx, { rowsRef: rowsLab })).map((t) => rowId(t));
    // --- sim 侧 ---
    const fApp = JSON.parse(defaultsApp); fApp[k] = true;
    ctx.__fApp = fApp;
    result.sim[k] = vm.runInContext(`
      (function () {
        var mm = _simActiveMonthMask(__fApp);
        var hits = [];
        for (var i = 0; i < __recs.length; i++) {
          if (!_simPassesFade(__recs[i], __fIdx, __fApp, mm)) hits.push(_simBaseKey(__recs[i], __fIdx));
        }
        return hits;
      })()
    `, ctx);
  }
  // sim bullstop 独立谓词(单键语义 AND, 无 filters 参数)
  result.simBullStop = vm.runInContext(`
    (function () {
      var hits = [];
      for (var i = 0; i < __recs.length; i++) { if (!_simPassesBullStop(__recs[i], __fIdx)) hits.push(_simBaseKey(__recs[i], __fIdx)); }
      return hits;
    })()
  `, ctx);
  return result;
}

function rowId(t) {
  return [t[fIdx.signal_date], t[fIdx.index_id], t[fIdx.signal], t[fIdx.buy_date], t[fIdx.etf_code]].join("|");
}
function setOf(arr) { return new Set(arr); }
function diffSets(a, b) {
  const A = setOf(a), B = setOf(b);
  let d = 0;
  for (const x of A) if (!B.has(x)) d++;
  for (const x of B) if (!A.has(x)) d++;
  return d;
}

// ---------------------------------------------------------------------------
// 执行: cur = 当前(--ref 则为历史版); old = 对照版
// ---------------------------------------------------------------------------
const cur = runSide("cur");
const old = BASE
  ? JSON.parse(fs.readFileSync(BASE, "utf8"))
  : (REF ? runSide("old") : null);

if (OUT) { fs.writeFileSync(OUT, JSON.stringify(cur)); console.log(`[parity] 当前版结果已落盘 ${OUT}`); }

if (!old) { console.log("[parity] 单边运行(未指定 --ref/--base), 仅输出不对比"); process.exit(0); }

let totalDiff = 0, badKeys = [];
const report = [];
for (const side of ["lab", "sim"]) {
  const keys = Object.keys(cur[side]);
  for (const k of keys) {
    const d = diffSets(cur[side][k], old[side][k]);
    if (d > 0) badKeys.push(`${side}.${k}(±${d})`);
    totalDiff += d;
    report.push(`${side.padEnd(4)} ${k.padEnd(24)} cur=${cur[side][k].length} old=${old[side][k].length} diff=${d}`);
  }
}
{
  const d = diffSets(cur.simBullStop, old.simBullStop);
  if (d > 0) badKeys.push(`sim.bullstop(±${d})`);
  totalDiff += d;
  report.push(`sim  bullstop(独立谓词)      cur=${cur.simBullStop.length} old=${old.simBullStop.length} diff=${d}`);
}
console.log(report.join("\n"));
console.log(`[parity] 总结: 键数=${Object.keys(cur.lab).length + Object.keys(cur.sim).length + 1} 总不一致=${totalDiff} ${totalDiff === 0 ? "PASS ✅" : "FAIL ❌ " + badKeys.join(", ")}`);
process.exit(totalDiff === 0 ? 0 : 1);
