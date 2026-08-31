#!/usr/bin/env node
/** recompute_p12_shared_core_and_popup_align.mjs — 8-30-002 codex 报告 P1-2/P1-3 数据复算收尾(2026-08-31)
 *
 * 目的:
 *   P1-2 共享核双份实现跨文件独立复算: common.js _gihRealizeRealForce vs lab.js _kellyAihlineRealizeReal,
 *     同输入逐字段(pr/rp/hd/sell_price/flag)对比, 确认边界条件下行为一致(codex 报告 fix 建议原文执行)。
 *   P1-3 card-vs-popup 修复后口径对齐回算: 8-30 修复(lab.js 弹窗改 S06 per-date 动态键集)后,
 *     弹窗链(=S06 动态谓词+posCapK1) 与卡面链(同谓词)笔数应逐位一致;
 *     verify_card_vs_popup.mjs 内置弹窗链=静态 NEW14(修复前口径), 跑出的差异即修复前样本, 本脚本补修复后对齐回算。
 * 方法: node vm 从 static-site/common.js + lab.js 提取上线函数原码, trades.json+accum_nav_map.json 驱动。
 * 输入: static-site/data/{signal_kelly_trades.json, accum_nav_map.json, kelly_mode_s06_state.json,
 *       kelly_loss_features.json, signal_kelly_backtest.json}, static-site/{common.js,lab.js}
 * 输出: docs/kelly/analysis/data/p12-recompute-out.json
 * 复现: node docs/kelly/analysis/scripts/recompute_p12_shared_core_and_popup_align.mjs
 * 口径: 卡面链=S06动态+posCapK1+每日池+(G/H/I套GIH sim); 弹窗链(修复后)=S06动态+cutoff+posCapK1(无sim, 原始持仓行)
 */
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..", "..", "..", "..");
const TRADES_JSON = path.join(ROOT, "static-site/data/signal_kelly_trades.json");
const S06_JSON = path.join(ROOT, "static-site/data/kelly_mode_s06_state.json");
const FEAT_JSON = path.join(ROOT, "static-site/data/kelly_loss_features.json");
const COMMON_JS = path.join(ROOT, "static-site/common.js");
const LAB_JS = path.join(ROOT, "static-site/lab.js");
const OUT_JSON = path.join(__dirname, "..", "data", "p12-recompute-out.json");

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
  if (p >= src.length) return null; // 简单 var decl(如 var x = null;)交由调用方 stub
  const openCh = src[p];
  const bodyEnd = scanBlock(p, openCh);
  if (bodyEnd < 0) return null;
  let end = bodyEnd + 1;
  while (end < src.length && /\s/.test(src[end])) { if (src[end] === ";") { end++; break; } end++; }
  return src.slice(start, end);
}

function extractAndEval(srcText, symList, ctx) {
  const missing = [];
  for (const name of symList) {
    const code = sliceDecl(srcText, name);
    if (code == null) { missing.push(name); continue; }
    vm.runInContext(code, ctx, { filename: name });
  }
  return missing;
}

const commonSrc = fs.readFileSync(COMMON_JS, "utf8");
const labSrc = fs.readFileSync(LAB_JS, "utf8");
const td = JSON.parse(fs.readFileSync(TRADES_JSON, "utf8"));
const s06 = JSON.parse(fs.readFileSync(S06_JSON, "utf8"));
const featDoc = JSON.parse(fs.readFileSync(FEAT_JSON, "utf8"));
const realNav = JSON.parse(fs.readFileSync(path.join(ROOT, "static-site/data/accum_nav_map.json"), "utf8"));
const fIdx = {};
(td.fields || []).forEach((f, i) => { fIdx[f] = i; });

const baseGlobals = { console: { error: () => {}, log: () => {} }, JSON, Math, Date, isFinite, parseFloat, parseInt, String, Number, Boolean, Array, Object, Map, Set, NaN };

// ============ P1-2: 共享核双份实现同输入逐字段对比 ============
const ctxCommon = vm.createContext({ ...baseGlobals, window: { _kkellyRealNav: realNav } });
extractAndEval(commonSrc, ["_gihIsShEtf", "_gihDaySpan", "_gihRealizeRealForce"], ctxCommon);

const ctxLab = vm.createContext({
  ...baseGlobals,
  window: {}, // 不挂 _kkellyRealizeRealForce → 走 lab.js 本体实现(浏览器中 lab 优先用 common 共享核, 此处单独验证本体)
  KELLY_ORIG_SLIPPAGE: 0.001,
});
vm.runInContext("var _kellyRealNav = null;", ctxLab);
vm.runInContext("_kellyRealNav = __NAV__;", Object.assign(ctxLab, { __NAV__: realNav }));
const lMiss2 = extractAndEval(labSrc, ["_kellyIsShEtf", "_kellyAihlineDaySpan", "_kellyAihlineRealizeReal"], ctxLab);

// 用例: G/H/I 真实行(buy_price>0)×(nav 命中日 / nav 缺失日) + 边界用例
function navHitDates(code, k) {
  const m = realNav[code] || {};
  return Object.keys(m).filter((d) => m[d] > 0).slice(0, k);
}
const cases = [];
const giModes = ["G", "H", "I"];
for (const mk of giModes) {
  const arr = [];
  for (const rk of ["rating_high", "rating_mid", "rating_low"]) {
    const q = (td.quadrants[rk] || {})[mk] || [];
    for (const t of q) {
      if ((t[fIdx.buy_price] || 0) > 0) arr.push(t);
      if (arr.length >= 16) break;
    }
    if (arr.length >= 16) break;
  }
  for (const t of arr) {
    const code = String(t[fIdx.etf_code] || "");
    const hits = navHitDates(code, 1);
    cases.push({ kind: "real_nav_hit", mode: mk, sel: { etf_code: code, buy_date: String(t[fIdx.buy_date] || ""), buy_price: t[fIdx.buy_price], amount: t[fIdx.amount] || 10000 }, dt: hits[0] || String(t[fIdx.sell_date] || "") });
    cases.push({ kind: "real_nav_missing", mode: mk, sel: { etf_code: code, buy_date: String(t[fIdx.buy_date] || ""), buy_price: t[fIdx.buy_price], amount: t[fIdx.amount] || 10000 }, dt: "19990101" });
  }
}
cases.push({ kind: "edge_null_sel", sel: null, dt: "20260801" });
cases.push({ kind: "edge_no_code", sel: { buy_date: "20260801", buy_price: 1.5, amount: 10000 }, dt: "20260801" });
cases.push({ kind: "edge_buy_price_0", sel: { etf_code: "510300", buy_date: "20260801", buy_price: 0, amount: 10000 }, dt: "20260801" });

const cmpFields = ["pr", "rp", "hd", "sell_price", "flag"];
const p12Rows = [];
let p12Same = 0, p12Diff = 0, p12Struct = 0;
for (const c of cases) {
  let rCommon = null, rLab = null, labErr = null;
  try { rCommon = vm.runInContext("_gihRealizeRealForce(__SEL__, __DT__)", Object.assign(ctxCommon, { __SEL__: c.sel, __DT__: c.dt })); }
  catch (e) { rCommon = { __threw__: String(e.message) }; }
  try { rLab = vm.runInContext("_kellyAihlineRealizeReal(__SEL__, __DT__)", Object.assign(ctxLab, { __SEL__: c.sel, __DT__: c.dt })); }
  catch (e) { labErr = String(e.message); rLab = { __threw__: labErr }; }
  const diffs = [];
  const keys = new Set([...Object.keys(rCommon || {}), ...Object.keys(rLab || {})]);
  for (const k of cmpFields) {
    if (!keys.has(k)) continue;
    const a = rCommon ? rCommon[k] : undefined, b = rLab ? rLab[k] : undefined;
    if (a !== b) diffs.push({ field: k, common: a, lab: b });
  }
  const extraKeys = [...keys].filter((k) => !cmpFields.includes(k) && k !== "__threw__");
  if (extraKeys.length) p12Struct++;
  if (diffs.length || (rCommon || {}).__threw__ || (rLab || {}).__threw__) p12Diff++; else p12Same++;
  p12Rows.push({ kind: c.kind, mode: c.mode || "", etf: (c.sel && c.sel.etf_code) || "", dt: c.dt, common: rCommon, lab: rLab, field_diffs: diffs, struct_extra_keys: extraKeys });
}
console.log(`P1-2 共享核对比: 用例 ${p12Rows.length} | 逐字段一致 ${p12Same} | 差异 ${p12Diff} | 结构差异(单方多键) ${p12Struct}`);
for (const r of p12Rows) {
  if (r.field_diffs.length || (r.common || {}).__threw__ || (r.lab || {}).__threw__ || r.struct_extra_keys.length) {
    console.log(`  DIFF [${r.kind}] ${r.etf}@${r.dt} common=${JSON.stringify(r.common)} lab=${JSON.stringify(r.lab)}`);
  }
}

// ============ P1-3: 修复后口径(S06 动态)弹窗链 vs 卡面链 对齐回算 ============
const ctx = vm.createContext({ ...baseGlobals, window: {}, isFinite, NaN });
vm.runInContext(`
  var _tdsS06State = null, _tdsS06ByDate = null, _tdsS06LoadErr = null, _tdsS06FiltersCache = null;
  var __stubState = { kellyLossFeatData: null, kellyLossSpecMap: {}, labSigKellyFilters: null };
  var state = __stubState;
  var KELLY_ORIG_SLIPPAGE = 0.001;
  var AIHLINE_CAL_RATIO = 1.498;
  var _KGIHP3_DAYS = 3;
  var KELLY_FEE_PRESETS = [];
  var _kellyRealNav = null;
`, ctx);
const cMiss = extractAndEval(commonSrc, [
  "_KELLY_FADE_LEGACY_SPECS", "_KELLY_FADE_FRONT_KEY_ORDER", "_KELLY_FADE_GATE_KEY_ORDER",
  "_tdsFadeSpecHit", "_KELLY_FADE_MODE_PRESETS", "_tdsFadeModeById", "_KELLY_FADE_T1_KEYS", "_KELLY_FADE_ALL_KEYS",
  "_tdsS06NormalizeDate", "_tdsS06BaseForDate", "_tdsS06FiltersForDate",
], ctx);
const lMiss = extractAndEval(labSrc, [
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
], ctx);
vm.runInContext(`
  _tdsS06State = __S06__;
  _tdsS06ByDate = {};
  for (var i = 0; i < __S06__.daily.length; i++) _tdsS06ByDate[_tdsS06NormalizeDate(__S06__.daily[i].date)] = __S06__.daily[i];
`, Object.assign(ctx, { __S06__: s06 }));
vm.runInContext(`
  __stubState.kellyLossFeatData = __FEAT__;
  ((__FEAT__.meta && __FEAT__.meta.rules) || []).forEach(function (r) { __stubState.kellyLossSpecMap[r.key] = r; });
`, Object.assign(ctx, { __FEAT__: featDoc }));
const dims = vm.runInContext("_kellyBuildTradeDims(__TD__, __FIDX__)", Object.assign(ctx, { __TD__: td, __FIDX__: fIdx }));
ctx.__dims = dims; ctx.__fIdx = fIdx; ctx.__td = td;

const featCache = new Map();
function passS06(t) {
  const dStr = String(t[fIdx.signal_date] || "");
  const f6 = vm.runInContext("_tdsS06FiltersForDate(__D6__)", Object.assign(ctx, { __D6__: dStr }));
  if (!f6) return true;
  const mm6 = vm.runInContext("_kellyActiveMonthMask(__F6__)", Object.assign(ctx, { __F6__: f6 }));
  return vm.runInContext("_kellyPassesFadeFilters(__T__, __FIDX__, __F6__, __FC__, __dims, __MM6__)",
    Object.assign(ctx, { __T__: t, __FIDX__: fIdx, __F6__: f6, __FC__: featCache, __dims: dims, __MM6__: mm6 }));
}
// NoBull per-date 谓词(G/H/I 卡面/修复后弹窗同口径, lab.js L11655-11676 同款: 当日基座键集 - bullAuxBackupStop)
vm.runInContext(`
  var _s06NoBullCache = {};
  function harnessNBForDate(dStr) {
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
function passNB(t) {
  const dStr = String(t[fIdx.signal_date] || "");
  const nb = vm.runInContext("harnessNBForDate(__DN__)", Object.assign(ctx, { __DN__: dStr }));
  if (!nb) return true;
  const mm = vm.runInContext("_kellyActiveMonthMask(__NB__)", Object.assign(ctx, { __NB__: nb }));
  return vm.runInContext("_kellyPassesFadeFilters(__T__, __FIDX__, __NBM__, __FC__, __dims, __MMN__)",
    Object.assign(ctx, { __T__: t, __FIDX__: fIdx, __NBM__: nb, __FC__: featCache, __dims: dims, __MMN__: mm }));
}

// 修复后弹窗链池 = S06 谓词 + posCapK1(A-F/J); G/H/I = NoBull per-date + posCapK1(lab.js L11651-11655 注释口径)
const ratingKeys = ["rating_high", "rating_mid", "rating_low"];
const sellModeKeys = ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"];
const poolS06 = [], seen = new Set();
for (const rk of ratingKeys) {
  const qk = td.quadrants[rk];
  if (!qk) continue;
  for (const mk of sellModeKeys) {
    for (const t of (qk[mk] || [])) {
      if (!passS06(t)) continue;
      const bk = vm.runInContext("_kellyBaseKey(__T__, __FIDX__)", Object.assign(ctx, { __T__: t, __FIDX__: fIdx }));
      if (!seen.has(bk)) { seen.add(bk); poolS06.push(t); }
    }
  }
}
const keptS06 = vm.runInContext("_kellyPositionCapKeptKeys(__POOL__, __FIDX__, 1)", Object.assign(ctx, { __POOL__: poolS06, __FIDX__: fIdx }));
const dayCntS06 = vm.runInContext("_kellyKeptDayCounts(__KEPT__)", Object.assign(ctx, { __KEPT__: keptS06 }));
const poolNB = [], seenNB = new Set();
for (const rk of ratingKeys) {
  const qk = td.quadrants[rk];
  if (!qk) continue;
  for (const mk of ["G", "H", "I"]) {
    for (const t of (qk[mk] || [])) {
      if (!passNB(t)) continue;
      const bk3 = vm.runInContext("_kellyBaseKey(__T__, __FIDX__)", Object.assign(ctx, { __T__: t, __FIDX__: fIdx }));
      if (!seenNB.has(bk3)) { seenNB.add(bk3); poolNB.push(t); }
    }
  }
}
const keptNB = vm.runInContext("_kellyPositionCapKeptKeys(__POOL__, __FIDX__, 1)", Object.assign(ctx, { __POOL__: poolNB, __FIDX__: fIdx }));
const dayCntNB = vm.runInContext("_kellyKeptDayCounts(__KEPT__)", Object.assign(ctx, { __KEPT__: keptNB }));

// 卡面链 stats 基准: 直接复算(与 verify_card_vs_popup.mjs 同构), 不读其输出避免二手依赖
const bk = JSON.parse(fs.readFileSync(path.join(ROOT, "static-site/data/signal_kelly_backtest.json"), "utf8"));
const cutoffs = (bk.config && bk.config.period_cutoffs) || {};
const BUY_AMOUNT = td.buy_amount || 10000;
const FEE_MAIN = { commission_rate: 0.00005, min_commission: 0.1, slippage: 0.001, transfer_fee_rate_sh: 0.00001, stamp_duty_rate: 0 };
const GIH_STRAT = { G: { method: "P", cap: 100000 }, H: { method: "A", cap: 50000 }, I: { method: "P", cap: 90000 } };

function cardTradesFor(mk) {
  const isG = (mk === "G" || mk === "H" || mk === "I");
  const passFn = isG ? passNB : passS06;
  const keptMap = isG ? keptNB : keptS06;
  const dayCnt = isG ? dayCntNB : dayCntS06;
  const raw = [];
  for (const rk of ratingKeys) for (const t of ((td.quadrants[rk] || {})[mk] || [])) raw.push(t);
  const out = [];
  for (const t of raw) {
    if (!passFn(t)) continue;
    const bk2 = vm.runInContext("_kellyBaseKey(__T__, __FIDX__)", Object.assign(ctx, { __T__: t, __FIDX__: fIdx }));
    if (!keptMap[bk2]) continue;
    const sd = String(t[fIdx.signal_date] || "");
    const amt = BUY_AMOUNT / (dayCnt[sd] || 1);
    const r = vm.runInContext("_kellyRecomputeTrade(__T__, __FIDX__, __FP__, __AMT__)",
      Object.assign(ctx, { __T__: t, __FIDX__: fIdx, __FP__: FEE_MAIN, __AMT__: amt }));
    out.push({ profit: r.profit, return_pct: r.return_pct, buy_date: String(t[fIdx.buy_date] || ""), sell_date: String(t[fIdx.sell_date] || ""), hold_days: t[fIdx.hold_days] || 0, amount: amt,
      etf_code: t[fIdx.etf_code] != null ? String(t[fIdx.etf_code]) : "", index_id: t[fIdx.index_id] != null ? String(t[fIdx.index_id]) : "", signal: t[fIdx.signal] != null ? String(t[fIdx.signal]) : "" });
  }
  return out;
}

const p13Rows = [];
let p13TotalEq = 0, p13TotalNe = 0;
for (const mk of sellModeKeys) {
  const trades = cardTradesFor(mk);
  const isGih = mk in GIH_STRAT;
  let cardHoldAll = null;
  if (isGih) {
    const app = vm.runInContext("_kellyAihlineApply(__TR__, __ST__, 'all')", Object.assign(ctx, { __TR__: trades, __ST__: GIH_STRAT[mk] }));
    const st = vm.runInContext("_kellyComputeStats(__B1__, 'all', 10000)", Object.assign(ctx, { __B1__: (app && app.b1) || [] }));
    cardHoldAll = { n: st.n, holding: st.holding_count };
  } else {
    const st = vm.runInContext("_kellyComputeStats(__WND__, 'all', 10000)", Object.assign(ctx, { __WND__: trades }));
    cardHoldAll = { n: st.n, holding: st.holding_count };
  }
  // 修复后弹窗链: 同池同谓词同 kept, 仅加 cutoff + 数原始行(无 sim)
  for (const pk of ["all", ...Object.keys(cutoffs)]) {
    const cutoff = cutoffs[pk] || "0";
    const wnd = trades.filter((t) => (t.buy_date || "") >= cutoff);
    const popTotal = wnd.length;
    const popHold = wnd.filter((t) => !t.sell_date).length;
    let cardN, cardHolding;
    if (isGih) {
      const w2 = trades.filter((t) => (t.buy_date || "") >= cutoff);
      const app = vm.runInContext("_kellyAihlineApply(__TR2__, __ST2__, __PK__)", Object.assign(ctx, { __TR2__: w2, __ST2__: GIH_STRAT[mk], __PK__: pk }));
      const st = vm.runInContext("_kellyComputeStats(__B2__, __PK2__, 10000)", Object.assign(ctx, { __B2__: (app && app.b1) || [], __PK2__: pk }));
      cardN = st.n; cardHolding = st.holding_count;
    } else {
      const st = vm.runInContext("_kellyComputeStats(__WND2__, __PK2__, 10000)", Object.assign(ctx, { __WND2__: wnd, __PK2__: pk }));
      cardN = st.n; cardHolding = st.holding_count;
    }
    const totalEq = popTotal === cardN;
    if (totalEq) p13TotalEq++; else p13TotalNe++;
    p13Rows.push({ mode: mk, period: pk, popup_fixed_total: popTotal, popup_fixed_holding_raw: popHold,
      card_n: cardN, card_holding: cardHolding,
      total_eq: totalEq,
      holding_note: isGih ? "GIH: 卡面=gihsim强平后持仓, 弹窗=原始未卖行(语义本不同, 弹窗不做sim)" : (popHold === cardHolding ? "一致" : "差异") });
  }
}
console.log(`P1-3 修复后口径回算: total 对比 ${p13TotalEq}/${p13Rows.length} 一致`);
for (const r of p13Rows) {
  if (!r.total_eq) console.log(`  NEQ ${r.mode}@${r.period} popup=${r.popup_fixed_total} card=${r.card_n}`);
  else if (r.mode === "A" || r.mode === "J" || r.mode === "E" || r.mode === "G") console.log(`  EQ  ${r.mode}@${r.period} popup_total=${r.popup_fixed_total} popup_hold_raw=${r.popup_fixed_holding_raw} card_n=${r.card_n} card_hold=${r.card_holding}`);
}
console.log(`missing symbols: common=[${cMiss}] lab=[${lMiss}] labP12=[${lMiss2}]`);

fs.writeFileSync(OUT_JSON, JSON.stringify({
  generated_at: new Date().toISOString(),
  trades_generated_at: td.generated_at,
  p12: { cases: p12Rows.length, same: p12Same, diff: p12Diff, struct_extra: p12Struct, rows: p12Rows },
  p13: { rows: p13Rows, total_eq: p13TotalEq, total_neq: p13TotalNe },
}, null, 1));
console.log("JSON written to " + OUT_JSON);
console.log("done");
