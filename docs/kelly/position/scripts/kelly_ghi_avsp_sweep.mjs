#!/usr/bin/env node
/** kelly_ghi_avsp_sweep.mjs — A法(满仓不买) vs P法(P3d先卖年轻) 同池同cap真实价矩阵扫描(v1.1.7 baseline)
 *
 * 目的: 干净判定「买入参与方式本身的价值」——同一 647 信号池(同池)同 cap 下, A法(holdCap, 满仓不买到cap
 *       停) vs P法(p3dCap, P≤3d先卖年轻仓腾位续买) 全真实价(real)对比扫描. 消混叠: 不拿 阶段1 G(10万)/I(9万)
 *       /H(5万) 直接比(信号池+cap 双重混叠), 统一 647 池逐cap对比.
 * 方法: 复用阶段1 vm 提取上线函数(sweep 同路径) + real 增强(仅 P 法强平日卖出=主库 accum_nav 真实净值,
 *       决策下单顺序不变), A 法无强平直接取 holdCap kept(自然卖出 recompute 真实盈亏).
 * 口径: v1.1.7 基准(base, S06 NoBull), posCap K1, 每日池, fee etf_main. 每格: 峰持仓/绝对净利/收益率
 *       (对峰持仓)/强平笔数/强平盈亏合计/按年分解. 关键分解: 每 P 格 强平亏损合计 vs 与同cap A法净利差
 *       (= 腾位续买增量收益).
 * 输入依赖: static-site/data/{signal_kelly_trades, signal_kelly_backtest, kelly_mode_s06_state,
 *           kelly_loss_features}.json + docs/kelly/position/scripts/accum_nav_map.json + static-site/lab.js,
 *           static-site/common.js(内核提取源).
 * 输出: docs/kelly/position/scripts/kelly_ghi_avsp_out.json(独立文件, 不覆盖阶段1 kelly_ghi_real_price_out.json)
 * 复现: node docs/kelly/position/scripts/kelly_ghi_avsp_sweep.mjs
 */
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..", "..", "..", "..");

const TRADES_JSON = path.join(ROOT, "static-site/data/signal_kelly_trades.json");
const BACKTEST_JSON = path.join(ROOT, "static-site/data/signal_kelly_backtest.json");
const S06_JSON = path.join(ROOT, "static-site/data/kelly_mode_s06_state.json");
const FEAT_JSON = path.join(ROOT, "static-site/data/kelly_loss_features.json");
const COMMON_JS = path.join(ROOT, "static-site/common.js");
const LAB_JS = path.join(ROOT, "static-site/lab.js");
const NAV_JSON = path.join(__dirname, "accum_nav_map.json");
const OUT_JSON = path.join(__dirname, "kelly_ghi_avsp_out.json");

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

// ===== Load sources + sandbox =====
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

const ctx = vm.createContext({ console, JSON, Math, Date, isFinite, parseFloat, parseInt, String, Number, Boolean, Array, Object, Map, Set, NaN });

vm.runInContext(`
  var _tdsS06State = null, _tdsS06ByDate = null, _tdsS06LoadErr = null, _tdsS06FiltersCache = null;
  var __stubState = { kellyLossFeatData: null, kellyLossSpecMap: {}, labSigKellyFilters: null };
  var state = __stubState;
  var KELLY_ORIG_SLIPPAGE = 0.001;
  var AIHLINE_CAL_RATIO = 1.498;
  var _KGIHP3_DAYS = 3;
  var KELLY_FEE_PRESETS = [];
  var __NAV__ = null;
`, ctx);

console.log("Extracting common.js symbols...");
const cMiss = extractAndEval(commonSrc, COMMON_SYMBOLS, ctx);
console.log(`  missing: ${cMiss.join(",") || "none"}`);
console.log("Extracting lab.js symbols...");
const lMiss = extractAndEval(labSrc, LAB_SYMBOLS, ctx);
console.log(`  missing: ${lMiss.join(",") || "none"}`);

const bk = JSON.parse(fs.readFileSync(BACKTEST_JSON, "utf8"));
const td = JSON.parse(fs.readFileSync(TRADES_JSON, "utf8"));
const s06 = JSON.parse(fs.readFileSync(S06_JSON, "utf8"));
const featDoc = JSON.parse(fs.readFileSync(FEAT_JSON, "utf8"));
const navMap = JSON.parse(fs.readFileSync(NAV_JSON, "utf8"));
vm.runInContext("__NAV__ = __NAVMAP__;", Object.assign(ctx, { __NAVMAP__: navMap }));

const fIdx = {};
(td.fields || []).forEach((f, i) => { fIdx[f] = i; });

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
ctx.__dims = dims; ctx.__fIdx = fIdx; ctx.__td = td; ctx.__bk = bk;

const SELL_MODES = bk.config?.sell_modes || {};
const BUY_AMOUNT = td.buy_amount || 10000;
const FEE_MAIN = { commission_rate: 0.00005, min_commission: 0.1, slippage: 0.001, transfer_fee_rate_sh: 0.00001, stamp_duty_rate: 0 };
const ratingKeys = ["rating_high", "rating_mid", "rating_low"];
const sellModeKeys = Object.keys(SELL_MODES);

vm.runInContext(`
  var _s06NoBullCache = {};
  function harnessNBForDate(dStr) {
    var f6 = _tdsS06FiltersForDate(dStr);
    if (!f6) return null;
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

const featCache = new Map();
function passesNB(t) {
  const dStr = String(t[fIdx.signal_date] || "");
  const nb = vm.runInContext("harnessNBForDate(__DSTR__)", Object.assign(ctx, { __DSTR__: dStr }));
  if (!nb) return true;
  const mm = vm.runInContext("_kellyActiveMonthMask(__NB__)", Object.assign(ctx, { __NB__: nb }));
  ctx.__tmpNB = nb; ctx.__tmpMM = mm;
  return vm.runInContext("_kellyPassesFadeFilters(__T__, __FIDX__, __tmpNB, __FC__, __dims, __tmpMM)",
    Object.assign(ctx, { __T__: t, __FIDX__: fIdx, __FC__: featCache, __dims: dims, __tmpNB: nb, __tmpMM: mm }));
}

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
        const bk2 = vm.runInContext("_kellyBaseKey(__T__, __FIDX__)", Object.assign(ctx, { __T__: t, __FIDX__: fIdx }));
        if (!seen.has(bk2)) { seen.add(bk2); basePoolNB.push(t); }
      }
    }
  }
}
console.log(`  basePoolNB: ${basePoolNB.length} unique keys`);

vm.runInContext("var __pkNB = _kellyPositionCapKeptKeys(__POOL__, __FIDX__, 1)",
  Object.assign(ctx, { __POOL__: basePoolNB, __FIDX__: fIdx }));
const posCapKeptNB = vm.runInContext("__pkNB", ctx);
const posDayCountsNB = vm.runInContext("_kellyKeptDayCounts(__pkNB)", ctx);
console.log(`  posCapKeptNB: ${Object.keys(posCapKeptNB).length} keys`);

function buildRecomputed(modeKey) {
  const raw = [];
  for (const rk of ratingKeys) {
    const arr = (td.quadrants[rk] || {})[modeKey] || [];
    for (let i = 0; i < arr.length; i++) raw.push(arr[i]);
  }
  const keptTrades = [];
  for (const t of raw) {
    if (!passesNB(t)) continue;
    const bk2 = vm.runInContext("_kellyBaseKey(__T__, __FIDX__)", Object.assign(ctx, { __T__: t, __FIDX__: fIdx }));
    if (!posCapKeptNB[bk2]) continue;
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

// ===== Enhanced P3dCap: real 模式 =====
const REALIZE_REAL_SRC = `
function __realizeReal(sel, dt, model) {
  if (model !== "real") {
    return _kellyAihlineRealize(sel.profit, sel.return_pct, sel.buy_date, sel.sell_date, sel.hold_days, sel.amount, dt, model);
  }
  var nav = null;
  if (sel.etf_code) { var m = __NAV__[sel.etf_code]; if (m) nav = m[dt]; }
  if (!nav || nav <= 0) {
    var fb = _kellyAihlineRealize(sel.profit, sel.return_pct, sel.buy_date, sel.sell_date, sel.hold_days, sel.amount, dt, "b1");
    return { pr: fb.pr, rp: fb.rp, hd: fb.hd, flag: "b1_fallback" };
  }
  var bp = sel.buy_price || 0;
  if (bp <= 0) return { pr: 0, rp: 0, hd: Math.round(_kellyAihlineDaySpan(sel.buy_date, dt)), flag: "no_buy_price" };
  var closeBuy = bp / (1 + KELLY_ORIG_SLIPPAGE);
  var amt = sel.amount || 0;
  var c = 0.00005, s = 0.001, minC = 0.1;
  var sh = _kellyIsShEtf(sel.etf_code) ? 0.00001 : 0;
  var stamp = 0;
  var buyPriceNew = closeBuy * (1 + s);
  if (buyPriceNew <= 0) return { pr: 0, rp: 0, hd: Math.round(_kellyAihlineDaySpan(sel.buy_date, dt)), flag: "buy_zero" };
  var sharesNew = amt / (buyPriceNew * (1 + c + sh));
  var grossNew = sharesNew * buyPriceNew;
  var commBuy = grossNew * c;
  if (commBuy < minC) {
    sharesNew = (amt - minC) / (buyPriceNew * (1 + sh));
    grossNew = sharesNew * buyPriceNew;
    commBuy = minC;
  }
  var sellPriceNew = nav * (1 - s);
  var sellAmountNew = sharesNew * sellPriceNew;
  var commSell = Math.max(sellAmountNew * c, minC);
  var transferFeeSell = sellAmountNew * sh;
  var stampDuty = sellAmountNew * stamp;
  var netNew = sellAmountNew - commSell - transferFeeSell - stampDuty;
  var profitNew = netNew - amt;
  var returnPctNew = profitNew / amt * 100;
  var hdReal = Math.round(_kellyAihlineDaySpan(sel.buy_date, dt));
  return { pr: Math.round(profitNew * 10000)/10000, rp: Math.round(returnPctNew * 10000)/10000, hd: hdReal };
}
`;
const P3D_FN_SRC = sliceDecl(labSrc, "_kellyAihlineP3dCap");
if (!P3D_FN_SRC) throw new Error("P3dCap not found");
let p3dReal = P3D_FN_SRC
  .replace("function _kellyAihlineP3dCap", "function _kellyAihlineP3dCapReal")
  .replace("amount: t.amount || 0, closed: null", "amount: t.amount || 0, closed: null, etf_code: t.etf_code || '', buy_price: t.buy_price || 0")
  .replace("_kellyAihlineRealize(sel.profit, sel.return_pct, sel.buy_date, sel.sell_date, sel.hold_days, sel.amount, dt, model)", "__realizeReal(sel, dt, model)")
  .replace("kept.push({ profit: r.pr, return_pct: r.rp, buy_date: sel.buy_date, sell_date: dt, hold_days: r.hd, amount: sel.amount, fee_cost: sel.fee_cost });",
           "kept.push({ profit: r.pr, return_pct: r.rp, buy_date: sel.buy_date, sell_date: dt, hold_days: r.hd, amount: sel.amount, fee_cost: sel.fee_cost, etf_code: sel.etf_code || '', buy_price: sel.buy_price || 0, forced: true });");
if (!p3dReal.includes("__realizeReal(sel")) throw new Error("realize replace failed");
vm.runInContext(REALIZE_REAL_SRC + "\n" + p3dReal, ctx, { filename: "_kellyAihlineP3dCapReal" });

// ===== Build recomputed pools: G/H/I 同 647 信号, 差异仅卖出模式(sell_date) =====
const reconG = buildRecomputed("G");
const reconH = buildRecomputed("H");
const reconI = buildRecomputed("I");
console.log(`  reconG: ${reconG.length}, reconH: ${reconH.length}, reconI: ${reconI.length}`);

// ===== 池一致性校验: 三池是否同一批信号(同 etf_code+buy_date), 差异仅 sell_date =====
function fp(arr) { const s = new Set(); for (const t of arr) s.add(t.etf_code + "|" + t.buy_date); return s; }
function fpSD(arr) { const s = new Set(); for (const t of arr) s.add(t.etf_code + "|" + t.buy_date + "|" + (t.sell_date || "")); return s; }
const fg = fp(reconG), fh = fp(reconH), fi = fp(reconI);
let interGH = 0, interGI = 0;
for (const k of fg) { if (fh.has(k)) interGH++; if (fi.has(k)) interGI++; }
const poolCheck = {
  n_G: reconG.length, n_H: reconH.length, n_I: reconI.length,
  same_signal_by_buydate: {
    G_vs_H: fg.size === fh.size && interGH === fg.size ? "SAME(buy_date 同批)" : `DIFF inter=${interGH}/${fg.size} vs ${fh.size}`,
    G_vs_I: fg.size === fi.size && interGI === fg.size ? "SAME(buy_date 同批)" : `DIFF inter=${interGI}/${fg.size} vs ${fi.size}`,
  },
  sell_date_diff_keys_G_vs_H: (function(){ const a=fpSD(reconG), b=fpSD(reconH); let d=0; for(const k of a) if(!b.has(k)) d++; for(const k of b) if(!a.has(k)) d++; return d; })(),
  sell_date_diff_sample: (function(){ const a=fpSD(reconG), b=fpSD(reconH); for(const k of a) if(!b.has(k)) return k; return "none"; })(),
};
console.log("poolCheck:", JSON.stringify(poolCheck));

// ===== 统计/格式 helpers =====
function fmtNum(v) { return v != null ? (typeof v === 'number' ? Math.round(v * 10000) / 10000 : v) : null; }
function pct1(v) { return v != null ? (+v).toFixed(2) + "%" : "-"; }
function yuan(v) { return v != null ? Math.round(v).toLocaleString() : "-"; }
function statsOf(keptArr) {
  if (!keptArr) return null;
  return vm.runInContext("_kellyComputeStats(__K__, 'all', 10000)", Object.assign(ctx, { __K__: keptArr }));
}
function byYearStats(keptArr) {
  if (!keptArr || !keptArr.length) return null;
  const byY = {};
  for (const t of keptArr) { const y = (t.buy_date || "").substring(0, 4); if (!byY[y]) byY[y] = []; byY[y].push(t); }
  const res = {};
  for (const y of Object.keys(byY).sort()) {
    const st = statsOf(byY[y]);
    res[y] = { n: st.n, total_profit: st.total_profit, return_pct_max_holding: st.return_pct_max_holding, win_rate: st.win_rate, max_concurrent_capital: st.max_concurrent_capital };
  }
  return res;
}
function cmpKept(a, b) {
  if (!a || !b) return "nil";
  if (a.length !== b.length) return `len ${a.length} vs ${b.length}`;
  let d = 0;
  for (let i = 0; i < a.length; i++) {
    if (Math.abs(a[i].profit - b[i].profit) > 1e-6 || Math.abs(a[i].amount - b[i].amount) > 1e-6) d++;
  }
  return d === 0 ? "EQ(逐位一致)" : `DIFF ${d}/${a.length}`;
}

// ===== 单格运行 =====
function runCell(method, cap) {
  if (method === "A") {
    const hr = vm.runInContext("_kellyAihlineHoldCap(__TR__, __CAP__)", Object.assign(ctx, { __TR__: reconG, __CAP__: cap }));
    const st = statsOf(hr.kept);
    return { method: "A", cap, n_kept: hr.kept.length, peak: hr.peak || cap, st, kept: hr.kept, forcedN: 0, forcedProfitSum: 0, forcedKept: [], xcheck: null };
  }
  const pr = vm.runInContext("_kellyAihlineP3dCapReal(__TR__, __CAP__, 'real')", Object.assign(ctx, { __TR__: reconG, __CAP__: cap }));
  const st = statsOf(pr.kept);
  const forcedKept = pr.kept.filter(t => t.forced);
  const forcedProfitSum = Math.round(forcedKept.reduce((s, t) => s + (t.profit || 0), 0) * 10000) / 10000;
  const fallbackN = forcedKept.filter(t => t.flag === "b1_fallback").length;
  const rb0 = vm.runInContext("_kellyAihlineP3dCapReal(__TR__, __CAP__, 'b0')", Object.assign(ctx, { __TR__: reconG, __CAP__: cap }));
  const rb1 = vm.runInContext("_kellyAihlineP3dCapReal(__TR__, __CAP__, 'b1')", Object.assign(ctx, { __TR__: reconG, __CAP__: cap }));
  const ob0 = vm.runInContext("_kellyAihlineP3dCap(__TR__, __CAP__, 'b0')", Object.assign(ctx, { __TR__: reconG, __CAP__: cap }));
  const ob1 = vm.runInContext("_kellyAihlineP3dCap(__TR__, __CAP__, 'b1')", Object.assign(ctx, { __TR__: reconG, __CAP__: cap }));
  const fByYear = {}, fWL = { winN: 0, lossN: 0, winSum: 0, lossSum: 0 };
  for (const t of forcedKept) {
    const y = (t.buy_date || "").substring(0, 4);
    if (!fByYear[y]) fByYear[y] = { n: 0, sum: 0 };
    fByYear[y].n++; fByYear[y].sum += t.profit || 0;
    if ((t.profit || 0) >= 0) { fWL.winN++; fWL.winSum += t.profit || 0; }
    else { fWL.lossN++; fWL.lossSum += t.profit || 0; }
  }
  for (const y of Object.keys(fByYear)) { fByYear[y].sum = Math.round(fByYear[y].sum * 10000) / 10000; }
  fWL.winSum = Math.round(fWL.winSum * 10000) / 10000;
  fWL.lossSum = Math.round(fWL.lossSum * 10000) / 10000;
  return { method: "P", cap, n_kept: pr.kept.length, peak: pr.peak || cap, st, kept: pr.kept, forcedN: forcedKept.length, forcedProfitSum, fallbackN, forcedKept, forcedByYear: fByYear, forcedWL: fWL, xcheck: { b0: cmpKept(ob0.kept, rb0.kept), b1: cmpKept(ob1.kept, rb1.kept) } };
}

// ===== 矩阵扫描 =====
const CAPS = [30000, 50000, 70000, 90000, 100000];
const out = {
  generated_at: new Date().toISOString(), trades_generated_at: td.generated_at, s06_snapshot_at: s06.generated_at,
  baseline: "v1.1.7 S06 NoBull + posCap K1 + 每日池 + fee etf_main(real=强平日主库真实accum_nav重算卖出), 同池=reconG(647 信号)",
  same_pool_n: reconG.length, pool_check: poolCheck, caps: CAPS, grid: {}, anchors: {},
};

for (const cap of CAPS) {
  const capK = cap / 10000;
  const A = runCell("A", cap);
  const P = runCell("P", cap);
  const aSt = A.st, pSt = P.st;
  const cell = {
    cap, capK,
    A: {
      n_kept: A.n_kept, peak: A.peak, operable: A.peak <= 200000 ? "OK" : "NO",
      real: { total_profit: fmtNum(aSt.total_profit), return_pct_max_holding: fmtNum(aSt.return_pct_max_holding), total_return_pct: fmtNum(aSt.total_return_pct), annualized_return: fmtNum(aSt.annualized_return), win_rate: fmtNum(aSt.win_rate), n: aSt.n, max_concurrent_capital: fmtNum(aSt.max_concurrent_capital) },
      forcedN: 0, forcedProfitSum: 0,
      by_year: byYearStats(A.kept),
    },
    P: {
      n_kept: P.n_kept, peak: P.peak, operable: P.peak <= 200000 ? "OK" : "NO",
      real: { total_profit: fmtNum(pSt.total_profit), return_pct_max_holding: fmtNum(pSt.return_pct_max_holding), total_return_pct: fmtNum(pSt.total_return_pct), annualized_return: fmtNum(pSt.annualized_return), win_rate: fmtNum(pSt.win_rate), n: pSt.n, max_concurrent_capital: fmtNum(pSt.max_concurrent_capital) },
      forcedN: P.forcedN, fallbackN: P.fallbackN, forcedProfitSum: fmtNum(P.forcedProfitSum), forcedByYear: P.forcedByYear, forcedWL: P.forcedWL, xcheck: P.xcheck,
      by_year: byYearStats(P.kept),
      forced_sample: P.forcedKept.slice(0, 5).map(t => ({ buy: t.buy_date, sell: t.sell_date, etf: t.etf_code, profit: t.profit, rp: t.return_pct })),
    },
  };
  out.grid[`${capK}w`] = cell;
}

// ===== 锚点验证 =====
// 锚1: reconG 池 P3d@10w real = 157,742.64 / 157.74% / forced 420 (阶段1 G 权威)
// 锚2: reconH 池 holdCap@5w = 115,157.21 / 230.31% / n=373 (阶段1 H 权威, 验证内核无漂移)
const anchorH = vm.runInContext("_kellyAihlineHoldCap(__TR__, __CAP__)", Object.assign(ctx, { __TR__: reconH, __CAP__: 50000 }));
const aHst = statsOf(anchorH.kept);
out.anchors = {
  G10w_P_reconG: { got: out.grid["10w"].P.real.total_profit, expect: 157742.6423, ok: out.grid["10w"].P.real.total_profit === 157742.6423, forcedN: out.grid["10w"].P.forcedN, expectForced: 420 },
  H5w_A_reconH: { got_total: fmtNum(aHst.total_profit), expect_total: 115157.2138, got_n: aHst.n, expect_n: 373, ok: Math.abs(aHst.total_profit - 115157.2138) < 0.01 && aHst.n === 373, got_ret: fmtNum(aHst.return_pct_max_holding) },
  all: null,
};
out.anchors.all = out.anchors.G10w_P_reconG.ok && out.anchors.H5w_A_reconH.ok;
console.log("anchors:", JSON.stringify(out.anchors, null, 1));

// ===== 关键分解 + 判定 =====
const summary = [];
for (const cap of CAPS) {
  const capK = cap / 10000;
  const a = out.grid[`${capK}w`].A, p = out.grid[`${capK}w`].P;
  const aNet = a.real.total_profit, pNet = p.real.total_profit;
  const delta = fmtNum(pNet - aNet);           // P - A 净利差
  const fpSum = p.forcedProfitSum;             // 强平盈亏合计(负=亏损)
  // 关键分解: Δ(P-A净利差) 已经扣除强平亏损 → 续买增量毛收益 = Δ - 强平合计(强平盈利为负损失)
  // relayIncrement = Δ - fpSum(毛续买增量);若 A 法与 P 法唯一差异=强平腾位续买, 则 P净利 = A净利 + 强平合计 + 续买增量
  const relayInc = fmtNum(delta - fpSum);
  let verdict;
  if (pNet > aNet && fpSum >= 0) {
    verdict = `P法净利>A法(+${yuan(delta)}), 强平合计反盈 ${yuan(fpSum)} → P3d 有价值`;      // 强平平仓不亏反盈, 纯增益
  } else if (pNet > aNet && relayInc > Math.abs(fpSum)) {
    verdict = `P法净利>A法(+${yuan(delta)}), 续买增量 +${yuan(relayInc)} > 强平亏损 ${yuan(Math.abs(fpSum))} → P3d 价值确认(强平成本被增量覆盖)`;   // 增量>强平成本=净正
  } else if (pNet > aNet) {
    verdict = `P法净利>A法(+${yuan(delta)}), 但续买增量 ${yuan(relayInc)} < 强平亏损 ${yuan(Math.abs(fpSum))} → 价值被强平成本侵蚀(仍净正)`;          // 增量≤强平成本=价值弱
  } else {
    verdict = `P法净利≤A法(${yuan(delta)}), 强平亏损 ${yuan(Math.abs(fpSum))} → P3d 价值命题=证伪`;
  }
  summary.push({ cap: `${capK}万`, A_n: a.n_kept, P_n: p.n_kept, A_net: aNet, P_net: pNet, delta: delta, relayIncrement: relayInc, forcedN: p.forcedN, forcedProfitSum: fpSum, A_ret: a.real.return_pct_max_holding, P_ret: p.real.return_pct_max_holding, verdict });
}
out.summary = summary;

// ===== 按年 P-A 净利差 =====
const yearDelta = {};
for (const y of Object.keys(out.grid["10w"].A.by_year || {})) {
  const a = out.grid["10w"].A.by_year[y], p = out.grid["10w"].P.by_year[y];
  yearDelta[y] = p ? { A: a.total_profit, P: p.total_profit, delta: fmtNum(p.total_profit - a.total_profit) } : { A: a.total_profit, P: null };
}
out.year_delta_10w = yearDelta;

fs.writeFileSync(OUT_JSON, JSON.stringify(out, null, 1));
console.log(`\nWritten to ${OUT_JSON}`);

console.log("\n======== 矩阵摘要(同 647 池) ========");
console.log("cap      A法净利      P法净利      强平盈亏    P-A净利差     A收%      P收%     判定");
for (const row of summary) {
  console.log(`${row.cap.padEnd(6)} ${yuan(row.A_net).padStart(10)} ${yuan(row.P_net).padStart(10)} ${(row.forcedProfitSum >= 0 ? "+" : "") + yuan(row.forcedProfitSum).padStart(9)} ${(row.delta >= 0 ? "+" : "") + yuan(row.delta).padStart(9)} ${pct1(row.A_ret).padStart(8)} ${pct1(row.P_ret).padStart(8)}  ${row.verdict}`);
}
console.log("\n======== 按年 P-A 净利差(10万格) ========");
for (const y of Object.keys(yearDelta).sort()) {
  const d = yearDelta[y];
  console.log(`  ${y}: A=${yuan(d.A)} P=${d.P != null ? yuan(d.P) : "-"} Δ=${d.P != null ? (d.delta >= 0 ? "+" : "") + yuan(d.delta) : "-"}`);
}
