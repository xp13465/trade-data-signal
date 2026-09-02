#!/usr/bin/env node
/** kelly_ghi_real_price_rebase.mjs — GHI(P法强平)真实价格重算(v1.1.7 baseline)
 *
 * 目的: 对 G=p3d10w(P≤3d, 10万) / I=p3d9w(P≤3d, 9万) 的 P法强平订单, 用强平日真实
 *       累计净值(accum_nav = trades.json 卖价同口径, 已验证 sell_price/0.999 逐位一致)
 *       重算强平盈亏, 替代 b0(记0利)/b1(按持有时间线性折算)估算; H=hold5w(A法满仓不买,
 *       无强平) 作对照基线. 得出唯一权威数字.
 * 方法: 从 lab.js/common.js vm 提取上线函数(sweep 同路径, b0/b1 先复现权威数字验证无漂移),
 *       再字符串替换 _kellyAihlineP3dCap 为 real 增强版(仅强平日卖出侧换真实净值, 决策下单顺序不变).
 * 口径: v1.1.7 基准(base, S06 NoBull), posCap K1, 每日池, fee etf_main.
 * 输出: docs/kelly/position/scripts/kelly_ghi_real_price_out.json
 * 复现: node docs/kelly/position/scripts/kelly_ghi_real_price_rebase.mjs
 */
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..", "..", "..", "..");

// ===== Data files =====
const TRADES_JSON = path.join(ROOT, "static-site/data/signal_kelly_trades.json");
const BACKTEST_JSON = path.join(ROOT, "static-site/data/signal_kelly_backtest.json");
const S06_JSON = path.join(ROOT, "static-site/data/kelly_mode_s06_state.json");
const FEAT_JSON = path.join(ROOT, "static-site/data/kelly_loss_features.json");
const COMMON_JS = path.join(ROOT, "static-site/common.js");
const LAB_JS = path.join(ROOT, "static-site/lab.js");
const NAV_JSON = path.join(__dirname, "accum_nav_map.json");
const OUT_JSON = path.join(__dirname, "kelly_ghi_real_price_out.json");

// ===== sliceDecl from parity script =====
function sliceDecl(src, name) {
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
  let i = start, inS = null, esc = false;
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
  if (kind === "fn") {
    let p = src.indexOf("(", start);
    if (p < 0) return null;
    const pEnd = scanBlock(p, "(");
    if (pEnd < 0) return null;
    let b = pEnd + 1;
    while (b < src.length && /\s/.test(src[b])) b++;
    if (src[b] !== "{") return null;
    const bodyEnd = scanBlock(b, "{");
    if (bodyEnd < 0) return null;
    return src.slice(start, bodyEnd + 1);
  }
  let p = start;
  while (p < src.length && !"([{".includes(src[p])) p++;
  if (p >= src.length) return null;
  const openCh = src[p];
  const bodyEnd = scanBlock(p, openCh);
  if (bodyEnd < 0) return null;
  let end = bodyEnd + 1;
  while (end < src.length && /\s/.test(src[end])) { if (src[end] === ";") { end++; break; } end++; }
  return src.slice(start, end);
}

// ===== Load sources =====
const commonSrc = fs.readFileSync(COMMON_JS, "utf8");
const labSrc = fs.readFileSync(LAB_JS, "utf8");

const COMMON_SYMBOLS = [
  "_KELLY_FADE_LEGACY_SPECS", "_KELLY_FADE_FRONT_KEY_ORDER", "_KELLY_FADE_GATE_KEY_ORDER",
  "_tdsFadeSpecHit", "_KELLY_FADE_MODE_PRESETS", "_tdsFadeModeById", "_KELLY_FADE_T1_KEYS", "_KELLY_FADE_ALL_KEYS",
  "_tdsS06NormalizeDate", "_tdsS06BaseForDate", "_tdsS06FiltersForDate",
];
const LAB_SYMBOLS = [
  "_KELLY_LOSS_NEW_KEYS", "_kellyBuyWeekday", "_kellyBuypriceBin", "_kellyBuildTradeDims",
  "_kellyDefaultFilters", "_kellyTradeFeatures", "_kellyMonthMask", "_kellyActiveMonthMask",
  "_kellyLossRuleHit", "_kellyPassesFadeFilters",
  "_kellyBaseKey", "_kellyPositionCapKeptKeys", "_kellyKeptDayCounts", "_kellyPerTradeAmount",
  "_kellyIsShEtf", "_kellyRecomputeTrade",
  "_kellyComputeStats", "_kellyMaxConcurrentCapital", "_kellyMaxDrawdown", "_kellyMaxConcurrent",
  "_kellyAnnualizedReturn", "_kellyYearsFromTrades", "_kellyDateDiffDays", "_kellyComputeKelly",
  "_kellyAihlineCalSpan", "_kellyAihlineRealize", "_kellyAihlineRealizeReal", "_kellyAihlineDaySpan",
  "_kellyAihlineFifoCap", "_kellyAihlineP3dCap", "_kellyAihlineHoldCap",
  "_kellyAihlineSim", "_kellyAihlineApply",
];

function extractAndEval(srcText, symList, ctx) {
  const missing = [];
  for (const name of symList) {
    const code = sliceDecl(srcText, name);
    if (code == null) { missing.push(name); continue; }
    try { vm.runInContext(code, ctx, { filename: name }); }
    catch (e) { throw new Error(`vm eval ${name}: ${e.message} at ${e.stack?.split("\n")[1]}`); }
  }
  return missing;
}

// ===== Build sandbox + load data =====
const ctx = vm.createContext({ console, JSON, Math, Date, isFinite, parseFloat, parseInt, String, Number, Boolean, Array, Object, Map, Set, NaN });

// --- module-level vars for common.js ---
vm.runInContext(`
  var _tdsS06State = null, _tdsS06ByDate = null, _tdsS06LoadErr = null, _tdsS06FiltersCache = null;
  var __stubState = { kellyLossFeatData: null, kellyLossSpecMap: {}, labSigKellyFilters: null };
  var state = __stubState;
  var KELLY_ORIG_SLIPPAGE = 0.001;   // 模块级常量(简单标量, 不走 sliceDecl)
  var AIHLINE_CAL_RATIO = 1.498;     // 日历日/交易日中位比
  var _KGIHP3_DAYS = 3;              // P 保护窗口: 持有≤3天 视为年轻仓
  var KELLY_FEE_PRESETS = [];        // 不消费(费率参数直接传), 占位防引用
  var _kellyRealNav = null;          // 真实净值映射 {etf_code:{YYYYMMDD:accum_nav}}, 由外部注入(与前端同名同源)
`, ctx);

console.log("Extracting common.js symbols...");
const cMiss = extractAndEval(commonSrc, COMMON_SYMBOLS, ctx);
console.log(`  missing: ${cMiss.join(",") || "none"}`);

console.log("Extracting lab.js symbols...");
const lMiss = extractAndEval(labSrc, LAB_SYMBOLS, ctx);
console.log(`  missing: ${lMiss.join(",") || "none"}`);

// --- Load data ---
const bk = JSON.parse(fs.readFileSync(BACKTEST_JSON, "utf8"));
const td = JSON.parse(fs.readFileSync(TRADES_JSON, "utf8"));
const s06 = JSON.parse(fs.readFileSync(S06_JSON, "utf8"));
const featDoc = JSON.parse(fs.readFileSync(FEAT_JSON, "utf8"));
const navMap = JSON.parse(fs.readFileSync(NAV_JSON, "utf8"));

// Inject NAV map (真实净值) into sandbox — 与前端 _kellyRealNav 同名同源(lab.js _kellyAihlineRealizeReal 依赖)
vm.runInContext("_kellyRealNav = __NAVMAP__;", Object.assign(ctx, { __NAVMAP__: navMap }));

const fIdx = {};
(td.fields || []).forEach((f, i) => { fIdx[f] = i; });

// --- Inject S06 state ---
vm.runInContext(`
  _tdsS06State = __S06__;
  _tdsS06ByDate = {};
  for (var i = 0; i < __S06__.daily.length; i++) _tdsS06ByDate[_tdsS06NormalizeDate(__S06__.daily[i].date)] = __S06__.daily[i];
`, Object.assign(ctx, { __S06__: s06 }));

// --- Inject feature data ---
vm.runInContext(`
  __stubState.kellyLossFeatData = __FEAT__;
  ((__FEAT__.meta && __FEAT__.meta.rules) || []).forEach(function (r) { __stubState.kellyLossSpecMap[r.key] = r; });
`, Object.assign(ctx, { __FEAT__: featDoc }));

// --- Build trade dims ---
const dims = vm.runInContext("_kellyBuildTradeDims(__TD__, __FIDX__)", Object.assign(ctx, { __TD__: td, __FIDX__: fIdx }));
ctx.__dims = dims;
ctx.__fIdx = fIdx;
ctx.__td = td;
ctx.__bk = bk;

const SELL_MODES = bk.config?.sell_modes || {};
const BUY_AMOUNT = td.buy_amount || 10000;
const FEE_MAIN = { commission_rate: 0.00005, min_commission: 0.1, slippage: 0.001, transfer_fee_rate_sh: 0.00001, stamp_duty_rate: 0 };

// ===== Build per-date NoBull filter =====
// In sandbox: all 58 keys false → preset keys true → bullAuxBackupStop=false
vm.runInContext(`
  var _s06NoBullCache = {};
  function harnessNBForDate(dStr) {
    var f6 = _tdsS06FiltersForDate(dStr); // returns {ok}? wait — returns filter obj or null
    if (!f6) return null; // fail-open
    // f6 has all 58 keys with base preset. For NoBull, override bullAuxBackupStop=false
    var nb = _s06NoBullCache[0]; // single dummy — just use f6
    // actually for base a9/new15, f6 has bullAuxBackupStop on for a9. We need NoBull variant.
    // Let's look up base
    var r = _tdsS06BaseForDate(dStr);
    if (!r || !r.ok) return null;
    var cKey = r.base;
    if (!_s06NoBullCache[cKey]) {
      var nb2 = {};
      var allK = _KELLY_FADE_ALL_KEYS;
      for (var i = 0; i < allK.length; i++) nb2[allK[i]] = false;
      var p = _tdsFadeModeById(r.base);
      if (p && Array.isArray(p.keys)) for (var j = 0; j < p.keys.length; j++) nb2[p.keys[j]] = true;
      nb2.bullAuxBackupStop = false;
      _s06NoBullCache[cKey] = nb2;
    }
    return _s06NoBullCache[cKey];
  }
`, ctx);

// ===== Pipeline: Collect base pool (NoBull) =====
console.log("Building base pool under S06 NoBull...");
const ratingKeys = ["rating_high", "rating_mid", "rating_low"];
const sellModeKeys = Object.keys(SELL_MODES);

// --- In sandbox: per-trade NoBull predicate ---
// _tdsS06BaseForDate is already extracted. harnessNBForDate creates NoBull filter.
// _kellyPassesFadeFilters(t, fIdx, nb, featCache, dims, monthMask)
const featCache = new Map();

function passesNB(t) {
  const dStr = String(t[fIdx.signal_date] || "");
  const nb = vm.runInContext("harnessNBForDate(__DSTR__)", Object.assign(ctx, { __DSTR__: dStr }));
  if (!nb) return true; // fail-open
  const mm = vm.runInContext("_kellyActiveMonthMask(__NB__)", Object.assign(ctx, { __NB__: nb }));
  ctx.__tmpNB = nb; ctx.__tmpMM = mm;
  return vm.runInContext("_kellyPassesFadeFilters(__T__, __FIDX__, __tmpNB, __FC__, __dims, __tmpMM)", 
    Object.assign(ctx, { __T__: t, __FIDX__: fIdx, __FC__: featCache, __dims: dims, __tmpNB: nb, __tmpMM: mm }));
}

// Build basePoolNB: iterate rating quads × modes × rows, filter, dedupe by baseKey
const seen = new Set();
const basePoolNB = [];
for (const rk of ratingKeys) {
  const qk = td.quadrants[rk];
  if (!qk) continue;
  for (const mk of sellModeKeys) {
    const arr = qk[mk] || [];
    for (let i = 0; i < arr.length; i++) {
      const t = arr[i];
      if (passesNB(t)) {
        const bk = vm.runInContext("_kellyBaseKey(__T__, __FIDX__)", Object.assign(ctx, { __T__: t, __FIDX__: fIdx }));
        if (!seen.has(bk)) { seen.add(bk); basePoolNB.push(t); }
      }
    }
  }
}
console.log(`  basePoolNB: ${basePoolNB.length} unique keys from ${seen.size} seen`);

// --- positionCap K=1 ---
vm.runInContext("var __pkNB = _kellyPositionCapKeptKeys(__POOL__, __FIDX__, 1)", 
  Object.assign(ctx, { __POOL__: basePoolNB, __FIDX__: fIdx }));
const posCapKeptNB = vm.runInContext("__pkNB", ctx);
const posDayCountsNB = vm.runInContext("_kellyKeptDayCounts(__pkNB)", ctx);
console.log(`  posCapKeptNB: ${Object.keys(posCapKeptNB).length} keys, ${Object.keys(posDayCountsNB).length} dates`);

// ===== Build recomputed trade array per mode =====
function buildRecomputed(modeKey) {
  // Gather all rows for this mode from rating quadrants (like quadsAll)
  const raw = [];
  for (const rk of ratingKeys) {
    const arr = (td.quadrants[rk] || {})[modeKey] || [];
    for (let i = 0; i < arr.length; i++) raw.push(arr[i]);
  }
  // Filter by passesFadeNoBull && posCapKeptNB
  const keptTrades = [];
  for (const t of raw) {
    if (!passesNB(t)) continue;
    const bk = vm.runInContext("_kellyBaseKey(__T__, __FIDX__)", Object.assign(ctx, { __T__: t, __FIDX__: fIdx }));
    if (!posCapKeptNB[bk]) continue;
    const sd = String(t[fIdx.signal_date] || "");
    const dayCount = posDayCountsNB[sd] || 1;
    const amt = BUY_AMOUNT / dayCount;
    const r = vm.runInContext("_kellyRecomputeTrade(__T__, __FIDX__, __FP__, __AMT__)",
      Object.assign(ctx, { __T__: t, __FIDX__: fIdx, __FP__: FEE_MAIN, __AMT__: amt }));
    keptTrades.push({
      profit: r.profit, return_pct: r.return_pct, fee_cost: r.fee_cost,
      buy_date: String(t[fIdx.buy_date] || ""),
      sell_date: String(t[fIdx.sell_date] || ""),
      hold_days: t[fIdx.hold_days] || 0,
      amount: amt,
      etf_code: String(t[fIdx.etf_code] || ""),
      buy_price: t[fIdx.buy_price] || 0,
    });
  }
  return keptTrades;
}

// ===== P3dCap: real 模式直接复用 lab.js 原生函数 =====
// 2026-09-01 修复(v1.1.14 review FAIL): lab.js 的 _kellyAihlineP3dCap 已原生支持 model="real"
// (_kellyAihlineRealize → _kellyAihlineRealizeReal 读 _kellyRealNav), kept.push 已带 etf_code/buy_price/sell_price/forced/flag。
// 旧版字符串替换注入 __realizeReal 自复刻(锚点随 lab.js 变更失效, L332 realize replace failed)已废弃,
// 直接别名原生函数 = 与前端渲染路径逐位一致(§5.4⑦ 同构对账), 消除第二份实现漂移。
const P3D_FN_SRC = sliceDecl(labSrc, "_kellyAihlineP3dCap");
if (!P3D_FN_SRC) throw new Error("P3dCap not found");
vm.runInContext("var _kellyAihlineP3dCapReal = _kellyAihlineP3dCap;", ctx, { filename: "_kellyAihlineP3dCapReal" });

console.log("Building recomputed arrays...");
const reconG = buildRecomputed("G");
const reconH = buildRecomputed("H");
const reconI = buildRecomputed("I");
console.log(`  G: ${reconG.length}, H: ${reconH.length}, I: ${reconI.length}`);

// ===== GHI 三档真实价格重算 =====
// 档位: G=P≤3d@10万(方法P), I=P≤3d@9万(方法P), H=满仓不买@5万(方法A, 无强平=对照)
const STRATS = [
  { mode: "G", method: "P", cap: 100000, label: "G=P≤3d@10万", recomputed: reconG },
  { mode: "I", method: "P", cap: 90000, label: "I=P≤3d@9万", recomputed: reconI },
  { mode: "H", method: "A", cap: 50000, label: "H=满仓不买@5万(对照A法)", recomputed: reconH },
];

function fmtNum(v) { return v != null ? (typeof v === 'number' ? Math.round(v * 10000) / 10000 : v) : null; }
function pct1(v) { return v != null ? (+v).toFixed(2) + "%" : "-"; }
function yuan(v) { return v != null ? Math.round(v).toLocaleString() : "-"; }
function cmpKept(a, b) {
  if (!a || !b) return "nil";
  if (a.length !== b.length) return `len ${a.length} vs ${b.length}`;
  let d = 0;
  for (let i = 0; i < a.length; i++) {
    if (Math.abs(a[i].profit - b[i].profit) > 1e-6 || Math.abs(a[i].amount - b[i].amount) > 1e-6) d++;
  }
  return d === 0 ? "EQ(逐位一致)" : `DIFF ${d}/${a.length}`;
}

const out = { generated_at: new Date().toISOString(), trades_generated_at: td.generated_at,
  s06_snapshot_at: s06.generated_at,
  baseline: "v1.1.7 S06 + passesFadeNoBull + posCap K1 + daily pool + fee etf_main(P法强平日用主库真实accum_nav重算)",
  basePoolNB: basePoolNB.length, strats: {} };
let reportText = "";

function runStrat(strat) {
  const stratObj = { method: strat.method, cap: strat.cap };
  // 原版权威 b0/b1
  const applyRes = vm.runInContext("_kellyAihlineApply(__TR__, __STRAT__, 'all')",
    Object.assign(ctx, { __TR__: strat.recomputed, __STRAT__: stratObj }));
  const stB0 = applyRes.b0 ? vm.runInContext("_kellyComputeStats(__K__, 'all', 10000)", Object.assign(ctx, { __K__: applyRes.b0 })) : null;
  const stB1 = applyRes.b1 ? vm.runInContext("_kellyComputeStats(__K2__, 'all', 10000)", Object.assign(ctx, { __K2__: applyRes.b1 })) : null;
  const peakAmt = applyRes.peak;
  // 增强版 real(方法P才有强平)
  let stReal = null, realKept = null, forced = [], fallbackN = 0, xcheck = null;
  if (strat.method === "P") {
    const rr = vm.runInContext("_kellyAihlineP3dCapReal(__TR__, __CAP__, 'real')",
      Object.assign(ctx, { __TR__: strat.recomputed, __CAP__: strat.cap }));
    realKept = rr.kept;
    stReal = vm.runInContext("_kellyComputeStats(__K__, 'all', 10000)", Object.assign(ctx, { __K__: realKept }));
    // 交叉验证: 增强版 b0/b1 与原版逐位一致(仅 real 分支不同)
    const rb0 = vm.runInContext("_kellyAihlineP3dCapReal(__TR__, __CAP__, 'b0')", Object.assign(ctx, { __TR__: strat.recomputed, __CAP__: strat.cap }));
    const rb1 = vm.runInContext("_kellyAihlineP3dCapReal(__TR__, __CAP__, 'b1')", Object.assign(ctx, { __TR__: strat.recomputed, __CAP__: strat.cap }));
    xcheck = { b0: cmpKept(applyRes.b0, rb0.kept), b1: cmpKept(applyRes.b1, rb1.kept) };
    forced = realKept.filter(t => t.forced);
    fallbackN = forced.filter(t => t.flag === "b1_fallback").length;
  } else {
    // A 法无强平: real=b0(=b1)
    stReal = stB0; realKept = applyRes.b0; forced = [];
  }
  return { mode: strat.mode, method: strat.method, cap: strat.cap, label: strat.label,
    nRecon: strat.recomputed.length, stB0, stB1, stReal, peakAmt, realKept, forced, fallbackN, xcheck };
}

function byYearStats(keptArr) {
  if (!keptArr || !keptArr.length) return null;
  const byY = {};
  for (const t of keptArr) {
    const y = (t.buy_date || "").substring(0, 4);
    if (!byY[y]) byY[y] = [];
    byY[y].push(t);
  }
  const res = {};
  for (const y of Object.keys(byY).sort()) {
    const st = vm.runInContext("_kellyComputeStats(__K__, 'all', 10000)", Object.assign(ctx, { __K__: byY[y] }));
    res[y] = { n: st.n, total_profit: st.total_profit, return_pct_max_holding: st.return_pct_max_holding, win_rate: st.win_rate, max_concurrent_capital: st.max_concurrent_capital };
  }
  return res;
}

for (const strat of STRATS) {
  const r = runStrat(strat);
  const b0 = r.stB0 || {}, b1 = r.stB1 || {}, rl = r.stReal || {};
  const peak = r.peakAmt || 0;
  const op = peak <= 200000 ? "OK" : "NO";
  const nForced = r.forced.length;
  const seg = {
    nRecon: r.nRecon,
    peak: peak,
    operable: op,
    b0: { total_profit: fmtNum(b0.total_profit), return_pct_max_holding: fmtNum(b0.return_pct_max_holding), total_return_pct: fmtNum(b0.total_return_pct), annualized_return: fmtNum(b0.annualized_return), win_rate: fmtNum(b0.win_rate), n: b0.n },
    b1: { total_profit: fmtNum(b1.total_profit), return_pct_max_holding: fmtNum(b1.return_pct_max_holding), total_return_pct: fmtNum(b1.total_return_pct), annualized_return: fmtNum(b1.annualized_return), win_rate: fmtNum(b1.win_rate), n: b1.n },
    real: { total_profit: fmtNum(rl.total_profit), return_pct_max_holding: fmtNum(rl.return_pct_max_holding), total_return_pct: fmtNum(rl.total_return_pct), annualized_return: fmtNum(rl.annualized_return), win_rate: fmtNum(rl.win_rate), n: rl.n, max_concurrent_capital: fmtNum(rl.max_concurrent_capital) },
    forcedN: nForced, fallbackN: r.fallbackN, xcheck: r.xcheck,
    forced: r.forced ? r.forced.slice(0, 20) : [],
    by_year: byYearStats(r.method === "P" ? r.realKept : r.realKept),
  };
  out.strats[r.mode] = seg;

  reportText += `
======== ${r.label} (方法${r.method}, cap=${(r.cap / 10000).toFixed(0)}万) ========
  原始信号 n=${r.nRecon} 峰持仓=${yuan(peak)}(${(peak / 10000).toFixed(1)}x ${op})
`;
  reportText += `  | 口径 | 净利 | 收益率(对峰持仓) | 年化 | 胜率 | n |
  |> b0(强平记0利) | ${yuan(b0.total_profit)} | ${pct1(b0.return_pct_max_holding)} | ${pct1(b0.annualized_return)} | ${pct1(b0.win_rate)} | ${b0.n} |
  |> b1(按持有时间线性折) | ${yuan(b1.total_profit)} | ${pct1(b1.return_pct_max_holding)} | ${pct1(b1.annualized_return)} | ${pct1(b1.win_rate)} | ${b1.n} |
  |> real(强平日真实净值) | ${yuan(rl.total_profit)} | ${pct1(rl.return_pct_max_holding)} | ${pct1(rl.annualized_return)} | ${pct1(rl.win_rate)} | ${rl.n} |
  强平笔数=${nForced}(fallback=${r.fallbackN}) 交叉验证: b0=${r.xcheck ? r.xcheck.b0 : "-"} b1=${r.xcheck ? r.xcheck.b1 : "-"}
`;
}

reportText += "\n\n====== 按年分解(real 口径, 每档单独) =====\n";
for (const mode of Object.keys(out.strats)) {
  const seg = out.strats[mode];
  reportText += `\n--- ${mode} real 按年 ---\n`;
  const by = seg.by_year;
  if (by) for (const y of Object.keys(by).sort()) {
    reportText += `  ${y}: n=${by[y].n} 净利=${yuan(by[y].total_profit)} 收=${pct1(by[y].return_pct_max_holding)} wr=${pct1(by[y].win_rate)}\n`;
  }
}

// 强平单明细(前12条 per P档)
for (const strat of STRATS) {
  if (strat.method !== "P") continue;
  const r = out.strats[strat.mode];
  const forcedArr = r.forced || [];
  reportText += `\n--- ${strat.label} 强平订单明细(共${forcedArr.length}笔, 前${Math.min(20, forcedArr.length)}笔) ---\n`;
  for (const t of (forcedArr || []).slice(0, Math.min(20, (forcedArr || []).length))) {
    const navVal = (navMap[t.etf_code] || {})[t.sell_date];
    reportText += `  buy=${t.buy_date} 强平=${t.sell_date} etf=${t.etf_code} 真实卖价(nav)=${navVal != null ? navVal.toFixed(6) : "N/A"} 强平净利=${yuan(t.profit)} 强平收益=${pct1(t.return_pct)}${t.flag ? " [" + t.flag + "]" : ""}\n`;
  }
}

out._reportText = reportText;
fs.writeFileSync(OUT_JSON, JSON.stringify(out, null, 1));
console.log(`Written to ${OUT_JSON}`);
console.log(reportText);
