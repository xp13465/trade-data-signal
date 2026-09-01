// part1: 头文件与 sliceDecl
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = "/Users/linhuichen/code/trade";
const TRADES_JSON = ROOT + "/static-site/data/signal_kelly_trades.json";
const BACKTEST_JSON = ROOT + "/static-site/data/signal_kelly_backtest.json";
const S06_JSON = ROOT + "/static-site/data/kelly_mode_s06_state.json";
const FEAT_JSON = ROOT + "/static-site/data/kelly_loss_features.json";
const NAV_JSON = ROOT + "/static-site/data/accum_nav_map.json";
const COMMON_JS = ROOT + "/static-site/common.js";
const LAB_JS = ROOT + "/static-site/lab.js";
const OUT_JSON = ROOT + "/docs/kelly/analysis/data/trade-method-final-repro-out.json";
function sliceDecl(src, name) {
  const pats = [
    new RegExp("(?:^|\\n)\\s*function\\s+" + name + "\\s*\\("),
    new RegExp("(?:^|\\n)\\s*(?:var|const|let)\\s+" + name + "\\s*="),
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
const COMMON_SYMBOLS = [
  "_KELLY_FADE_FRONT_KEY_ORDER", "_KELLY_FADE_GATE_KEY_ORDER", "_KELLY_FADE_T1_KEYS", "_KELLY_FADE_ALL_KEYS",
  "_KELLY_FADE_LEGACY_SPECS", "_KELLY_FADE_MODE_PRESETS", "_tdsFadeModeById", "_tdsFadeSpecHit",
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
    catch (e) { throw new Error("vm eval " + name + ": " + e.message + " at " + (e.stack ? e.stack.split("\n")[1] : "")); }
  }
  return missing;
}
// part2: 上下文/提取/数据/谓词/池
const commonSrc = fs.readFileSync(COMMON_JS, "utf8");
const labSrc = fs.readFileSync(LAB_JS, "utf8");
const ctx = vm.createContext({ console, JSON, Math, Date, isFinite, parseFloat, parseInt, String, Number, Boolean, Array, Object, Map, Set, NaN });
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
const cMiss = extractAndEval(commonSrc, COMMON_SYMBOLS, ctx);
const lMiss = extractAndEval(labSrc, LAB_SYMBOLS, ctx);
console.log("extract common missing: " + (cMiss.join(",") || "none") + "; lab missing: " + (lMiss.join(",") || "none"));
const bk = JSON.parse(fs.readFileSync(BACKTEST_JSON, "utf8"));
const td = JSON.parse(fs.readFileSync(TRADES_JSON, "utf8"));
const s06 = JSON.parse(fs.readFileSync(S06_JSON, "utf8"));
const featDoc = JSON.parse(fs.readFileSync(FEAT_JSON, "utf8"));
const navDoc = JSON.parse(fs.readFileSync(NAV_JSON, "utf8"));
const fIdx = {};
(td.fields || []).forEach(function (f, i) { fIdx[f] = i; });
vm.runInContext(`
  _tdsS06State = __S06__;
  _tdsS06ByDate = {};
  for (var i = 0; i < __S06__.daily.length; i++) _tdsS06ByDate[_tdsS06NormalizeDate(__S06__.daily[i].date)] = __S06__.daily[i];
`, Object.assign(ctx, { __S06__: s06 }));
vm.runInContext(`
  __stubState.kellyLossFeatData = __FEAT__;
  ((__FEAT__.meta && __FEAT__.meta.rules) || []).forEach(function (r) { __stubState.kellyLossSpecMap[r.key] = r; });
`, Object.assign(ctx, { __FEAT__: featDoc }));
vm.runInContext("_kellyRealNav = __REALNAV__;", Object.assign(ctx, { __REALNAV__: navDoc }));
const dims = vm.runInContext("_kellyBuildTradeDims(__TD__, __FIDX__)", Object.assign(ctx, { __TD__: td, __FIDX__: fIdx }));
ctx.__dims = dims; ctx.__fIdx = fIdx; ctx.__td = td; ctx.__bk = bk;
const SELL_MODES = (bk.config && bk.config.sell_modes) || {};
const BUY_AMOUNT = td.buy_amount || 10000;
const FEE_MAIN = { commission_rate: 0.00005, min_commission: 0.1, slippage: 0.001, transfer_fee_rate_sh: 0.00001, stamp_duty_rate: 0 };
const cutoffs = (bk.config && bk.config.period_cutoffs) || {};
const ratingKeys = ["rating_high", "rating_mid", "rating_low"];
const GIH_STRAT = { G: { method: "P", cap: 100000 }, H: { method: "A", cap: 50000 }, I: { method: "P", cap: 90000 } };
const featCache = new Map();
function staticFilters(modeId) {
  const p = vm.runInContext("_tdsFadeModeById(__ID__)", Object.assign(ctx, { __ID__: modeId }));
  const allK = vm.runInContext("_KELLY_FADE_ALL_KEYS", ctx);
  const f = {};
  for (const k of allK) f[k] = false;
  if (p && Array.isArray(p.keys)) for (const k of p.keys) f[k] = true;
  return f;
}
function passesStaticFade(t, filters) {
  const mm = vm.runInContext("_kellyActiveMonthMask(__FS__)", Object.assign(ctx, { __FS__: filters }));
  return vm.runInContext("_kellyPassesFadeFilters(__T__, __FIDX__, __FS__, __FC__, __dims, __MM__)",
    Object.assign(ctx, { __T__: t, __FIDX__: fIdx, __FS__: filters, __FC__: featCache, __dims: dims, __MM__: mm }));
}
function passesS06(t) {
  const dStr = String(t[fIdx.signal_date] || "");
  const f6 = vm.runInContext("_tdsS06FiltersForDate(__D6__)", Object.assign(ctx, { __D6__: dStr }));
  if (!f6) return true;
  return passesStaticFade(t, f6);
}
const _s6NB = {};
function s06NoBull(t) {
  const dStr = String(t[fIdx.signal_date] || "");
  const b = vm.runInContext("_tdsS06BaseForDate(__D6__)", Object.assign(ctx, { __D6__: dStr }));
  if (!b || !b.ok) return null;
  if (!_s6NB[b.base]) {
    const allK = vm.runInContext("_KELLY_FADE_ALL_KEYS", ctx);
    const f = {};
    for (const k of allK) f[k] = false;
    const p = vm.runInContext("_tdsFadeModeById(__ID__)", Object.assign(ctx, { __ID__: b.base }));
    if (p && Array.isArray(p.keys)) for (const k of p.keys) f[k] = true;
    f.bullAuxBackupStop = false;
    _s6NB[b.base] = f;
  }
  return _s6NB[b.base];
}
function buildPoolWith(passFn) {
  const pool = [], seen = new Set();
  for (const rk of ratingKeys) {
    const qk = td.quadrants[rk];
    if (!qk) continue;
    for (const mk of Object.keys(SELL_MODES)) {
      const arr = qk[mk] || [];
      for (let i = 0; i < arr.length; i++) {
        const t = arr[i];
        if (!passFn(t)) continue;
        const bk2 = vm.runInContext("_kellyBaseKey(__T__, __FIDX__)", Object.assign(ctx, { __T__: t, __FIDX__: fIdx }));
        if (!seen.has(bk2)) { seen.add(bk2); pool.push(t); }
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
// 完整单 mode 复算: raw 三评级并集 -> 谓词 -> kept -> 各周期 recompute+stats; GIH 额外 sim
function modeAll(modeKey, passFn, kept, dayCounts, passFnNB, keptNB, dayCountsNB, useNB) {
  const isGih = modeKey === "G" || modeKey === "H" || modeKey === "I";
  const pf = (useNB && isGih && passFnNB) ? passFnNB : passFn;
  const kp = (useNB && isGih && keptNB) ? keptNB : kept;
  const dc = (useNB && isGih && dayCountsNB) ? dayCountsNB : dayCounts;
  const raw = [];
  for (const rk of ratingKeys) {
    const arr = (td.quadrants[rk] || {})[modeKey] || [];
    for (let i = 0; i < arr.length; i++) raw.push(arr[i]);
  }
  const allTrades = [];
  for (const t of raw) {
    if (!pf(t)) continue;
    const bk2 = vm.runInContext("_kellyBaseKey(__T__, __FIDX__)", Object.assign(ctx, { __T__: t, __FIDX__: fIdx }));
    if (!kp[bk2]) continue;
    const sd = String(t[fIdx.signal_date] || "");
    const amt = BUY_AMOUNT / (dc[sd] || 1);
    const r = vm.runInContext("_kellyRecomputeTrade(__T__, __FIDX__, __FP__, __AMT__)",
      Object.assign(ctx, { __T__: t, __FIDX__: fIdx, __FP__: FEE_MAIN, __AMT__: amt }));
    allTrades.push({ profit: r.profit, return_pct: r.return_pct, fee_cost: r.fee_cost,
      buy_date: String(t[fIdx.buy_date] || ""), sell_date: String(t[fIdx.sell_date] || ""),
      hold_days: t[fIdx.hold_days] || 0, amount: amt,
      etf_code: t[fIdx.etf_code] != null ? String(t[fIdx.etf_code]) : "",
      index_id: t[fIdx.index_id] != null ? String(t[fIdx.index_id]) : "",
      signal: t[fIdx.signal] != null ? String(t[fIdx.signal]) : "",
      signal_date: String(t[fIdx.signal_date] || ""),
      sell_reason: t[fIdx.sell_reason] != null ? String(t[fIdx.sell_reason]) : "",
      rating: t[fIdx.rating] != null ? String(t[fIdx.rating]) : "",
      track_score: t[fIdx.track_score] != null ? Number(t[fIdx.track_score]) : null });
  }
  const out = {};
  for (const pk of Object.keys(cutoffs)) {
    const c = cutoffs[pk];
    let wnd = allTrades;
    if (c && c !== "0") wnd = allTrades.filter(function (t) { return t.buy_date >= c; });
    out[pk] = {};
    out[pk]["base"] = vm.runInContext("_kellyComputeStats(__K__, __PK__, 10000)", Object.assign(ctx, { __K__: wnd, __PK__: pk }));
    if (isGih) {
      const strat = GIH_STRAT[modeKey];
      const app = vm.runInContext("_kellyAihlineApply(__TR__, __ST__, __PK__)", Object.assign(ctx, { __TR__: wnd, __ST__: strat, __PK__: pk }));
      const real = (app && app.real) ? app.real.filter(function (k) { return k.profit !== null && k.profit !== undefined; }) : [];
      out[pk]["gihreal"] = vm.runInContext("_kellyComputeStats(__K2__, __PK2__, 10000)", Object.assign(ctx, { __K2__: real, __PK2__: pk }));
      out[pk]["gihpeak"] = app ? app.peak : 0;
    }
  }
  out["_allTrades"] = allTrades;
  return out;
}
// part3: 主驱动 + 扩展维度
const MODES_OF_INTEREST = ["A", "F", "J", "G", "H", "I", "B", "C", "D", "E"];
const PERIOD_KEYS = Object.keys(cutoffs); // y1/y3/y5/y10/all
function modeCfg(baseId) {
  if (baseId === "s06") {
    return { passFn: passesS06, passFnNB: s06NoBull, useNB: true };
  }
  const fs_ = staticFilters(baseId);
  const fNB_ = Object.assign({}, fs_); fNB_.bullAuxBackupStop = false;
  return {
    passFn: function (t) { return passesStaticFade(t, fs_); },
    passFnNB: function (t) { return passesStaticFade(t, fNB_); },
    useNB: !!fs_.bullAuxBackupStop,
  };
}
const result = { generated_at: new Date().toISOString(), config: { buy_amount: BUY_AMOUNT, fee: FEE_MAIN, periods: bk.config.periods, period_cutoffs: cutoffs, gih: GIH_STRAT }, bases: {} };
for (const baseId of ["s06", "new14", "a9"]) {
  const cfg = modeCfg(baseId);
  const pool = buildPoolWith(cfg.passFn);
  const kept = keptFrom(pool, 1);
  const dc = dayCountsFrom(kept);
  let keptNB = null, dcNB = null;
  if (cfg.useNB) {
    const poolNB = buildPoolWith(cfg.passFnNB);
    keptNB = keptFrom(poolNB, 1);
    dcNB = dayCountsFrom(keptNB);
  }
  const modes = {};
  for (const mk of MODES_OF_INTEREST) {
    if (!SELL_MODES[mk]) continue;
    const m = modeAll(mk, cfg.passFn, kept, dc, cfg.passFnNB, keptNB, dcNB, cfg.useNB);
    modes[mk] = m;
  }
  result.bases[baseId] = { pool_n: pool.length, kept_n: Object.keys(kept).length, keptNB_n: keptNB ? Object.keys(keptNB).length : null, modes: {} };
  for (const mk of Object.keys(modes)) {
    const m = modes[mk];
    result.bases[baseId].modes[mk] = {};
    for (const pk of PERIOD_KEYS) {
      const st = m[pk].base;
      const g = m[pk].gihreal || null;
      const row = {
        n: st.n, win_rate: st.win_rate, total_profit: st.total_profit, total_invest: st.total_invest,
        total_return_pct: st.total_return_pct, return_pct_max_holding: st.return_pct_max_holding,
        max_concurrent_capital: st.max_concurrent_capital, max_concurrent: st.max_concurrent,
        avg_hold_days: st.avg_hold_days, max_drawdown: st.max_drawdown, max_drawdown_pct: st.max_drawdown_pct,
        annualized_return: st.annualized_return, sharpe: st.sharpe, calmar: st.calmar,
        holding_count: st.holding_count, holding_capital: st.holding_capital, total_fee_cost: st.total_fee_cost,
      };
      if (g) {
        row.gihreal = {
          n: g.n, win_rate: g.win_rate, total_profit: g.total_profit, total_invest: g.total_invest,
          total_return_pct: g.total_return_pct, return_pct_max_holding: g.return_pct_max_holding,
          max_concurrent_capital: g.max_concurrent_capital, max_concurrent: g.max_concurrent,
          avg_hold_days: g.avg_hold_days, max_drawdown: g.max_drawdown, max_drawdown_pct: g.max_drawdown_pct,
          annualized_return: g.annualized_return, sharpe: g.sharpe, calmar: g.calmar,
          holding_count: g.holding_count, holding_capital: g.holding_capital, total_fee_cost: g.total_fee_cost,
        };
        row.gihpeak = m[pk].gihpeak;
      }
      result.bases[baseId].modes[mk][pk] = row;
    }
    // 全周期 trade 序列(供扩展维度) 仅存 s06 基座(逐笔太巨大)
    if (baseId === "s06") {
      result._trades_s06 = result._trades_s06 || {};
      result._trades_s06[mk] = m._allTrades.map(function (t) { return { bd: t.buy_date, sd: t.sell_date, p: t.profit, a: t.amount, pr: t.return_pct }; });
    }
  }
}
// ---- 扩展维度 ----
const ext = {};
// 1) 按年分解(s06 基座, 各 mode 含 GIH): 年 profit / peak_capital / peak_return_pct / peak_dd_pct
const yearTrades = result._trades_s06 || {};
function maxConcurrentCapitalSimple(list) {
  if (!list.length) return 0;
  const deltas = {}, dates = [];
  for (const t of list) {
    const bd = t.bd, sd = t.sd || "99999999";
    (deltas[bd] = deltas[bd] || { b: 0, s: 0 }); deltas[bd].b += t.a;
    (deltas[sd] = deltas[sd] || { b: 0, s: 0 }); deltas[sd].s += t.a;
    dates.push(bd); dates.push(sd);
  }
  dates.sort();
  let cur = 0, mx = 0;
  for (const d of dates) { cur -= deltas[d].s; cur += deltas[d].b; if (cur > mx) mx = cur; }
  return Math.round(mx * 10000) / 10000;
}
function yearlyFor(mk, tradeList) {
  const ymap = {};
  for (const t of tradeList) {
    const yr = String(t.bd).substring(0, 4);
    if (!yr) continue;
    if (!ymap[yr]) ymap[yr] = { profit: 0, n: 0, trades: [] };
    ymap[yr].profit += t.p; ymap[yr].n++; ymap[yr].trades.push(t);
  }
  for (const yr of Object.keys(ymap)) {
    const v = ymap[yr];
    const cap = maxConcurrentCapitalSimple(v.trades);
    v.peak_capital = cap;
    v.peak_return_pct = cap > 0 ? Math.round(v.profit / cap * 100 * 10000) / 10000 : 0;
    delete v.trades;
  }
  return ymap;
}
ext.yearly = {};
for (const mk of Object.keys(yearTrades)) {
  ext.yearly[mk] = yearlyFor(mk, yearTrades[mk]);
}
// 2) 稳定性: 分半(全周期按 signal_date 排序, 前/后半各自 profit+peak_return)+ 按年方向一致率(正/负年计数)
ext.stability = {};
for (const mk of Object.keys(yearTrades)) {
  const list = yearTrades[mk].slice().sort(function (a, b) { return a.bd < b.bd ? -1 : 1; });
  const half = Math.floor(list.length / 2);
  const f = yearlyFor(mk, list.slice(0, half)); const s = yearlyFor(mk, list.slice(half));
  let fp = 0, sp = 0, fc = 0, sc = 0;
  for (const y of Object.keys(f)) { fp += f[y].profit; fc += f[y].peak_capital; }
  for (const y of Object.keys(s)) { sp += s[y].profit; sc += s[y].peak_capital; }
  const yys = ext.yearly[mk];
  let pos = 0, neg = 0;
  for (const y of Object.keys(yys)) { if (yys[y].profit > 0) pos++; else if (yys[y].profit < 0) neg++; }
  ext.stability[mk] = {
    half_n: half, first_profit: Math.round(fp * 100) / 100, second_profit: Math.round(sp * 100) / 100,
    first_peak_return_pct: fc > 0 ? Math.round(fp / fc * 10000) / 100 : null,
    second_peak_return_pct: sc > 0 ? Math.round(sp / sc * 10000) / 100 : null,
    pos_years: pos, neg_years: neg,
    direction_consistent: pos > 0 && neg === 0,
  };
}
// 3) 回撤与恢复(全周期 equity 曲线: 按 buy_date 逐笔累加 profit, 找最大回撤谷日/恢复日/恢复期交易日)
function drawdownRecovery(list) {
  const asc = list.slice().sort(function (a, b) { return a.bd < b.bd ? -1 : 1; });
  let peak = 0, cur = 0, maxAbs = 0, valleyDate = "", peakDate = "", recoverDate = "";
  let i = 0, found = false;
  const sorted = [];
  for (const t of asc) { sorted.push({ d: t.bd, p: t.p }); }
  for (const e of sorted) {
    cur += e.p;
    if (cur > peak) { peak = cur; peakDate = e.d; }
    const dd = peak - cur;
    if (dd > maxAbs) { maxAbs = dd; valleyDate = e.d; found = true; }
  }
  if (found && valleyDate > peakDate) {
    for (const e of sorted) { if (e.d > valleyDate && cur >= peak) { recoverDate = e.d; break; } }
  }
  // 恢复期 = valley 到 recover 的交易日数(粗略按 distinct buy dates 数)
  let recovTrading = 0;
  if (recoverDate) {
    const ds = sorted.filter(function (e) { return e.d > valleyDate && e.d <= recoverDate; });
    recovTrading = new Set(ds.map(function (e) { return e.d; })).size;
  }
  return { max_drawdown_abs: Math.round(maxAbs * 100) / 100, peak_date: peakDate, valley_date: valleyDate, recover_date: recoverDate || null, recovery_trading_days: recovTrading };
}
ext.drawdown = {};
for (const mk of Object.keys(yearTrades)) ext.drawdown[mk] = drawdownRecovery(yearTrades[mk]);
// 4) 大熊市窗口专项(用 s06 基座 trades, 按 buy_date 窗口切片算 profit 与 peak_return)
const BEAR_WINDOWS = [
  { id: "2015-股灾", s: "20150615", e: "20160229" },
  { id: "2018-单边熊", s: "20180101", e: "20181231" },
  { id: "2022-阴跌", s: "20220101", e: "20221031" },
  { id: "2024-初微盘崩", s: "20240101", e: "20240229" },
  { id: "2026-近端", s: "20260101", e: "20260901" },
];
ext.bear = {};
for (const mk of Object.keys(yearTrades)) {
  ext.bear[mk] = {};
  for (const w of BEAR_WINDOWS) {
    const seg = yearTrades[mk].filter(function (t) { return t.bd >= w.s && t.bd <= w.e; });
    const ym = yearlyFor(mk, seg);
    let profit = 0, cap = 0;
    for (const y of Object.keys(ym)) { profit += ym[y].profit; cap += ym[y].peak_capital; }
    ext.bear[mk][w.id] = { n: seg.length, profit: Math.round(profit * 100) / 100, peak_return_pct: cap > 0 ? Math.round(profit / cap * 10000) / 100 : null };
  }
}
// 5) 可操作性打分(基于 s06 各 mode all 周期: 最大持仓/单次本金倍数/操作复杂度/强平)
ext.operability = {};
for (const mk of Object.keys(result.bases["s06"].modes)) {
  const all = result.bases["s06"].modes[mk]["all"];
  const g = all.gihreal;
  const target = g ? g : all;
  const mcc = target.max_concurrent_capital || 0;
  const mult = Math.round(mcc / 10000 * 100) / 100;
  let complexity = "", forceClose = "无";
  if (mk === "A") { complexity = "固定10天自动卖, 无需盯盘"; }
  else if (mk === "E") { complexity = "持有5天自动卖"; }
  else if (mk === "F") { complexity = "持有15天自动卖"; }
  else if (mk === "J") { complexity = "固定20天自动卖"; }
  else if (mk === "B" || mk === "C" || mk === "D") { complexity = "固定10天+止盈自动卖"; }
  else if (mk === "G") { complexity = "按指数卖出信号卖(需盯信号)"; forceClose = "GIH P法@10万含强平(先卖年轻仓)"; }
  else if (mk === "H") { complexity = "满仓不买@5万: 到5万停买, 自然卖出腾位再买, 无需强平"; forceClose = "无强平(手段A)"; }
  else if (mk === "I") { complexity = "卖出信号卖+追关注额外受追止损; GIH P法@9万含强平"; forceClose = "GIH P法@9万含强平"; }
  ext.operability[mk] = {
    max_concurrent_capital: mcc, multiple_of_principal: mult,
    operable_20x: mcc <= 200000, complexity: complexity, force_close: forceClose,
    avg_hold_days: target.avg_hold_days, n: target.n,
  };
}
result.ext = ext;
delete result._trades_s06;
fs.writeFileSync(OUT_JSON, JSON.stringify(result, null, 1));
console.log("WROTE " + OUT_JSON);
// ---- 摘要表 ----
function fmtRow(mk) {
  const m = result.bases["s06"].modes[mk];
  const cells = [];
  for (const pk of ["y1", "y3", "y5", "y10", "all"]) {
    const r = m[pk]; const g = r.gihreal;
    const t = g || r;
    cells.push(pk + ": " + t.return_pct_max_holding + "% | +" + t.total_profit + " | " + t.max_concurrent_capital + "元" + (g ? "(gih)" : ""));
  }
  return mk + " :: " + cells.join("  ;  ");
}
for (const mk of MODES_OF_INTEREST) {
  if (result.bases["s06"].modes[mk]) console.log(fmtRow(mk));
}
