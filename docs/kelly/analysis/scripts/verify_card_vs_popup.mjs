#!/usr/bin/env node
/** kelly_ghi_sweep_v117.mjs — G/H/I 最大持仓金额全谱穷举挖掘(v1.1.7 baseline: S06 + posCap K1 + daily pool + etf_main fee)
 *
 * 目的: 对 G/H/I 三长线模式做 cap 5-20万每1万穷举, G 额外 11.5-13.5万每5000 细扫,
 *       确认/翻案 codex 交接报告定稿(G=13万/H=7万/I=15万).
 * 方法: 从 lab.js/common.js vm 提取上线函数, 驱动 S06 per-date 谓词+58键过滤+posCap K1+每日池+费率重算+aihline内核.
 * 口径: v1.1.7 基准(base, S06), G/H/I 使用 passesFadeNoBull 长线豁免版.
 * 输出: docs/kelly/position/scripts/kelly_ghi_sweep_out.json
 * 复现: node docs/kelly/position/scripts/kelly_ghi_sweep_v117.mjs
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
const OUT_JSON = "/tmp/verify_card_vs_popup_out.json";

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
  "_kellyAihlineCalSpan", "_kellyAihlineRealize", "_kellyAihlineDaySpan",
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
    });
  }
  return keptTrades;
}

console.log("Building recomputed arrays...");
const reconG = buildRecomputed("G");
const reconH = buildRecomputed("H");
const reconI = buildRecomputed("I");
console.log(`  G: ${reconG.length}, H: ${reconH.length}, I: ${reconI.length}`);

// ===== GIH sim + stats per cap =====
function evalCap(mode, method, capVal, tradesRecomputed) {
  const strat = { method: method, cap: capVal };
  const applyRes = vm.runInContext("_kellyAihlineApply(__TR__, __STRAT__, 'all')",
    Object.assign(ctx, { __TR__: tradesRecomputed, __STRAT__: strat }));
  
  const stB0 = applyRes.b0 ? vm.runInContext("_kellyComputeStats(__K__, 'all', 10000)", Object.assign(ctx, { __K__: applyRes.b0 })) : null;
  const stB1 = applyRes.b1 ? vm.runInContext("_kellyComputeStats(__K2__, 'all', 10000)", Object.assign(ctx, { __K2__: applyRes.b1 })) : null;
  return { b0: stB0, b1: stB1, peak: applyRes.peak };
}



// =====================================================================
// 验证主逻辑(替换 sweep 的 CAP SWEEP): 卡面链 vs 弹窗链
// =====================================================================
const cutoffs = (bk.config && bk.config.period_cutoffs) || {};
const periodKeys = ["all"].concat(Object.keys(cutoffs));

// ---------- 弹窗路径: 静态 NEW14 谓词(state.labSigKellyFilters || _kellyDefaultFilters) ----------
const staticFilters = vm.runInContext("_kellyDefaultFilters()", ctx);
const staticMonthMask = vm.runInContext("_kellyActiveMonthMask(__FS__)", Object.assign(ctx, { __FS__: staticFilters }));
function passesStatic(t) {
  return vm.runInContext("_kellyPassesFadeFilters(__T__, __FIDX__, __FS2__, __FC__, __dims, __MS2__)",
    Object.assign(ctx, { __T__: t, __FIDX__: fIdx, __FS2__: staticFilters, __FC__: featCache, __dims: dims, __MS2__: staticMonthMask }));
}

// ---------- 卡面路径(A-F 主谓词): s06 per-date ----------
function passS06(t) {
  const dStr = String(t[fIdx.signal_date] || "");
  const f6 = vm.runInContext("_tdsS06FiltersForDate(__D6__)", Object.assign(ctx, { __D6__: dStr }));
  if (!f6) return true;   // fail-open
  const mm6 = vm.runInContext("_kellyActiveMonthMask(__F6__)", Object.assign(ctx, { __F6__: f6 }));
  return vm.runInContext("_kellyPassesFadeFilters(__T__, __FIDX__, __F6__, __FC__, __dims, __MM6__)",
    Object.assign(ctx, { __T__: t, __FIDX__: fIdx, __F6__: f6, __FC__: featCache, __dims: dims, __MM6__: mm6 }));
}

// ---------- 通用池构建(与 _kellyCollectBasePool 同构: 跨 rating×mode, baseKey 去重) ----------
function buildPoolWith(passFn) {
  const pool = [], seen = new Set();
  for (const rk of ratingKeys) {
    const qk = td.quadrants[rk];
    if (!qk) continue;
    for (const mk of sellModeKeys) {
      const arr = (qk[mk] || []);
      for (let i = 0; i < arr.length; i++) {
        const t = arr[i];
        if (!passFn(t)) continue;
        const bk = vm.runInContext("_kellyBaseKey(__T__, __FIDX__)", Object.assign(ctx, { __T__: t, __FIDX__: fIdx }));
        if (!seen.has(bk)) { seen.add(bk); pool.push(t); }
      }
    }
  }
  return pool;
}
function keptFrom(pool, K) {
  return vm.runInContext("_kellyPositionCapKeptKeys(__POOL__, __FIDX__, __KK__)",
    Object.assign(ctx, { __POOL__: pool, __FIDX__: fIdx, __KK__: K }));
}
function dayCountsFrom(kept) {
  return vm.runInContext("_kellyKeptDayCounts(__KEPT__)", Object.assign(ctx, { __KEPT__: kept }));
}

// ---------- 构建两套池 ----------
console.log("构建弹窗静态 NEW14 池...");
const poolStatic = buildPoolWith(passesStatic);
const keptStatic = keptFrom(poolStatic, 1);          // 弹窗 positionCap K=1
const dayCntStatic = dayCountsFrom(keptStatic);
console.log("  poolStatic=" + poolStatic.length + " kept=" + Object.keys(keptStatic).length);

console.log("构建卡面 s06 池(A-F 主谓词)...");
const poolS06 = buildPoolWith(passS06);
const keptS06 = keptFrom(poolS06, 1);
const dayCntS06 = dayCountsFrom(keptS06);
console.log("  poolS06=" + poolS06.length + " kept=" + Object.keys(keptS06).length);
console.log("  复用 head: G/H/I NoBull 池 basePoolNB=" + basePoolNB.length +
            " keptNB=" + Object.keys(posCapKeptNB).length);

// ---------- 卡面链 recompute(某 mode, 给定谓词+kept+dayCounts) ----------
function recomputeMode(modeKey, passFn, kept, dayCounts) {
  const raw = [];
  for (const rk of ratingKeys) {
    const arr = (td.quadrants[rk] || {})[modeKey] || [];
    for (let i = 0; i < arr.length; i++) raw.push(arr[i]);
  }
  const out = [];
  for (const t of raw) {
    if (!passFn(t)) continue;
    const bk = vm.runInContext("_kellyBaseKey(__T__, __FIDX__)", Object.assign(ctx, { __T__: t, __FIDX__: fIdx }));
    if (!kept[bk]) continue;
    const sd = String(t[fIdx.signal_date] || "");
    const amt = BUY_AMOUNT / (dayCounts[sd] || 1);
    const r = vm.runInContext("_kellyRecomputeTrade(__T__, __FIDX__, __FP__, __AMT__)",
      Object.assign(ctx, { __T__: t, __FIDX__: fIdx, __FP__: FEE_MAIN, __AMT__: amt }));
    out.push({ profit: r.profit, return_pct: r.return_pct, fee_cost: r.fee_cost,
      buy_date: String(t[fIdx.buy_date] || ""), sell_date: String(t[fIdx.sell_date] || ""),
      hold_days: t[fIdx.hold_days] || 0, amount: amt,
      etf_code: t[fIdx.etf_code] != null ? String(t[fIdx.etf_code]) : "",
      index_id: t[fIdx.index_id] != null ? String(t[fIdx.index_id]) : "",
      signal: t[fIdx.signal] != null ? String(t[fIdx.signal]) : "",
      signal_date: String(t[fIdx.signal_date] || ""),
      sell_reason: t[fIdx.sell_reason] != null ? String(t[fIdx.sell_reason]) : "" });
  }
  return out;
}

// ---------- 弹窗链 filtered(某 mode, cutoff; static 谓词 + static kept) ----------
function popupTrades(modeKey, cutoff) {
  const raw = [];
  for (const rk of ratingKeys) {
    const arr = (td.quadrants[rk] || {})[modeKey] || [];
    for (let i = 0; i < arr.length; i++) raw.push(arr[i]);
  }
  const out = [];
  for (const t of raw) {
    if (cutoff && cutoff !== "0" && (t[fIdx.buy_date] || "") < cutoff) continue;
    if (!passesStatic(t)) continue;
    const bk = vm.runInContext("_kellyBaseKey(__T__, __FIDX__)", Object.assign(ctx, { __T__: t, __FIDX__: fIdx }));
    if (!keptStatic[bk]) continue;
    const sd = String(t[fIdx.signal_date] || "");
    const amt = BUY_AMOUNT / (dayCntStatic[sd] || 1);
    const r = vm.runInContext("_kellyRecomputeTrade(__T__, __FIDX__, __FP2__, __AMT2__)",
      Object.assign(ctx, { __T__: t, __FIDX__: fIdx, __FP2__: FEE_MAIN, __AMT2__: amt }));
    const nt = t.slice();
    nt[fIdx.profit] = r.profit;
    nt[fIdx.return_pct] = r.return_pct;
    out.push(nt);
  }
  return out;
}

// ---------- 主循环对比 ----------
const GIH_STRAT = { G: { method: "P", cap: 100000 }, H: { method: "A", cap: 50000 }, I: { method: "P", cap: 90000 } };
console.log("\n===== 卡面链 vs 弹窗链 对比(all 全信号象限) =====");
const sumRows = [];
for (const mk of sellModeKeys) {
  for (const pk of periodKeys) {
    const cutoff = cutoffs[pk] || "0";
    const isGih = (mk === "G" || mk === "H" || mk === "I");
    // 卡面链
    let cardTrades;
    if (isGih) {
      cardTrades = recomputeMode(mk, passesNB, posCapKeptNB, posDayCountsNB);
    } else {
      cardTrades = recomputeMode(mk, passS06, keptS06, dayCntS06);
    }
    // 周期 cutoff 子集
    let wnd = cardTrades;
    if (cutoff && cutoff !== "0") wnd = cardTrades.filter((t) => (t.buy_date || "") >= cutoff);
    let st;
    if (isGih) {
      const strat = GIH_STRAT[mk];
      const app = vm.runInContext("_kellyAihlineApply(__TR__, __ST__, __PK__)",
        Object.assign(ctx, { __TR__: wnd, __ST__: strat, __PK__: pk }));
      const b1 = (app && app.b1) || [];
      st = vm.runInContext("_kellyComputeStats(__B1__, __PK2__, 10000)", Object.assign(ctx, { __B1__: b1, __PK2__: pk }));
    } else {
      st = vm.runInContext("_kellyComputeStats(__WND__, __PK3__, 10000)", Object.assign(ctx, { __WND__: wnd, __PK3__: pk }));
    }
    // 弹窗链
    const pop = popupTrades(mk, cutoff);
    const popHold = pop.filter((t2) => !t2[fIdx.sell_date]).length;
    sumRows.push({ mode: mk, period: pk, card_holding: st.holding_count,
      card_maxconc: st.max_concurrent, card_n: st.n,
      pop_holding: popHold, pop_total: pop.length });
    console.log(mk + "@" + pk + " | 卡面 holding=" + st.holding_count + " maxConc=" + st.max_concurrent +
      " n=" + st.n + " | 弹窗 持仓中=" + popHold + " 共=" + pop.length);
  }
}

// ---------- 详细构成: G 弹窗持仓明细 / A/J 卡面 vs 弹窗 持仓明细 ----------
console.log("\n===== G 弹窗持仓明细(all 周期) =====");
const gPop = popupTrades("G", "0");
const gHold = gPop.filter((t) => !t[fIdx.sell_date]);
console.log("G 弹窗持仓笔数=" + gHold.length);
gHold.forEach((t) => {
  console.log("  " + t[fIdx.buy_date] + " " + t[fIdx.etf_code] + " " + (t[fIdx.etf_name]||"") +
    " sig=" + t[fIdx.signal] + " hold=" + t[fIdx.hold_days] + "d");
});

console.log("\n===== A/J/E 卡面(stats holding) vs 弹窗持仓明细(all) =====");
for (const mk of ["A", "J", "E"]) {
  const recA = recomputeMode(mk, passS06, keptS06, dayCntS06);
  const stA = vm.runInContext("_kellyComputeStats(__WND__, __PK3__, 10000)", Object.assign(ctx, { __WND__: recA, __PK3__: "all" }));
  const popA = popupTrades(mk, "0");
  const holdA = popA.filter((t) => !t[fIdx.sell_date]);
  console.log(mk + " 卡面 holding=" + stA.holding_count + " 弹窗持仓=" + holdA.length);
  holdA.forEach((t) => {
    console.log("  弹窗持仓: " + t[fIdx.buy_date] + " " + t[fIdx.etf_code] + " " + (t[fIdx.etf_name]||"") +
      " sig=" + t[fIdx.signal] + " hold=" + t[fIdx.hold_days] + "d");
  });
}



// ===== 逐笔诊断: A 模式卡面独有持仓(8/17,8/18,8/20)在两条链的谓词/posCap 判定 =====
console.log("\n===== 逐笔判定诊断(A 模式卡面独有持仓) =====");
const diagRows = [
  { bd: "20260817", eco: "516390", sig: "buy_special" },
  { bd: "20260818", eco: "512580", sig: "buy_special" },
  { bd: "20260820", eco: "516250", sig: "buy_aux" },
  { bd: "20260824", eco: "562870", sig: "buy_aux" },
];
// 从 rating 三分区找到 A 模式的原始行
for (const dr of diagRows) {
  let found = null;
  for (const rk of ratingKeys) {
    const arr = (td.quadrants[rk] || {})["A"] || [];
    for (const t of arr) {
      if (String(t[fIdx.buy_date]) === dr.bd && String(t[fIdx.etf_code]) === dr.eco) { found = t; break; }
    }
    if (found) break;
  }
  if (!found) { console.log(dr.bd + " " + dr.eco + ": 未找到原始行!"); continue; }
  const s06ok = passS06(found);
  const stok = passesStatic(found);
  const bk = vm.runInContext("_kellyBaseKey(__T__, __FIDX__)", Object.assign(ctx, { __T__: found, __FIDX__: fIdx }));
  const keptS06ok = !!keptS06[bk];
  const keptStok = !!keptStatic[bk];
  const sd = String(found[fIdx.signal_date]);
  const amtS06 = (10000 / (dayCntS06[sd] || 1)).toFixed(0);
  const amtSt = (10000 / (dayCntStatic[sd] || 1)).toFixed(0);
  console.log(dr.bd + " " + dr.eco + " " + dr.sig +
    " | s06谓词=" + s06ok + " 静态NEW14谓词=" + stok +
    " | posCapK1 @s06池=" + keptS06ok + " 静态池=" + keptStok +
    " | 当日保留数 s06=" + (dayCntS06[sd] || 0) + " 静态=" + (dayCntStatic[sd] || 0) +
    " 金额 s06=" + amtS06 + " 静态=" + amtSt);
}

// ===== 追加探针: 卡面持仓明细 + 与弹窗差集 =====
// baseKey 对齐(signal_date|index_id|signal|buy_date|etf_code, 同 _kellyBaseKey)
function bkOf(rec) {
  return rec.signal_date + "|" + rec.index_id + "|" + rec.signal + "|" + rec.buy_date + "|" + rec.etf_code;
}
function bkOfRaw(t) {
  return String(t[fIdx.signal_date] || "") + "|" +
    (t[fIdx.index_id] != null ? String(t[fIdx.index_id]) : "") + "|" +
    (t[fIdx.signal] != null ? String(t[fIdx.signal]) : "") + "|" +
    String(t[fIdx.buy_date] || "") + "|" +
    (t[fIdx.etf_code] != null ? String(t[fIdx.etf_code]) : "");
}
console.log("\n===== A/J/E/G 卡面(未套sim recompute)持仓明细 vs 弹窗持仓明细 =====");
for (const mk of ["A", "J", "E", "G"]) {
  let cardTrades;
  if (mk === "G") cardTrades = recomputeMode(mk, passesNB, posCapKeptNB, posDayCountsNB);
  else cardTrades = recomputeMode(mk, passS06, keptS06, dayCntS06);
  const cardHold = cardTrades.filter((t) => !t.sell_date);
  const popT = popupTrades(mk, "0");
  const popHold = popT.filter((t) => !t[fIdx.sell_date]);
  const popKeys = new Set();
  for (const ph of popHold) popKeys.add(bkOfRaw(ph));
  console.log("\n### " + mk + " 卡面(recompute)持仓=" + cardHold.length + " 弹窗持仓=" + popHold.length);
  // 弹窗持仓明细
  console.log("  -- 弹窗持仓明细 --");
  for (const ph of popHold) {
    console.log("    [弹窗] " + String(ph[fIdx.buy_date]) + " " + (ph[fIdx.etf_code]||"") +
      " " + (ph[fIdx.etf_name]||"") + " sig=" + (ph[fIdx.signal]||"") + " hold=" + ph[fIdx.hold_days] + "d");
  }
  console.log("  -- 卡面持仓明细 --");
  for (const ct of cardHold) {
    const has = popKeys.has(bkOf(ct));
    console.log("    [卡面] " + ct.buy_date + " " + ct.etf_code + " " + ct.signal +
      " hold=" + ct.hold_days + "d" + (has ? "  (弹窗也有)" : "  <<仅卡面"));
  }
}

// ===== 结果 JSON 存证(§23.5) =====
const OUT_JSON2 = path.join(__dirname, "..", "data", "card-vs-popup-consistency.json");
const sumDoc = {
  generated_at: new Date().toISOString(),
  trades_generated_at: td.generated_at,
  s06_snapshot_at: s06.generated_at,
  baseline: "卡面=S06动态+posCapK1+每日池+(G/H/I套GIH sim b1); 弹窗=静态NEW14+cutoff+posCapK1",
  rows: sumRows,
};
fs.writeFileSync(OUT_JSON2, JSON.stringify(sumDoc, null, 1));
console.log("JSON written to " + OUT_JSON2 + " rows=" + sumRows.length);

console.log("\ndone");
