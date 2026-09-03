// s06-eliminate-fallback-impact.mjs - 方案2消灭110笔永久兜底「影响面一次性量化」(研究, 只读不改)
//
// 【目的】用户拍板(2026-09-02)消灭 110 笔老信号(20110119~20141113, rating_low, unique base 110 笔)的
//   「NEW14 永久兜底」: 2014 前段改按 csi500_ret20 - hs300_ret20 价差 sticky(同现快照 CONFIRM=15/MIN_HOLD=10,
//   阈值 -3.524224785046781)判 a9/new14。本脚本 = 权威对账脚本 trade-method-final-repro.mjs 的镜像副本
//   (切片 common.js/lab.js 单源跑 VM), 注入 2014 前段预覆盖行(方案2 sticky 基座)后重跑 s06 全链路,
//   量化「110 笔改判」对全周期数字/按年/110笔子集的影响。
//
// 【方法口径】
//   - 基线 = 现快照(kelly_mode_s06_state.json, 覆盖期 20141114 起, 110 笔走 out_of_range_fallback → off_base=new14)
//   - 场景 = 现快照 + 预覆盖行(20100104~20141113, 方案2 csi500-hs300 sticky 基座, T日收盘判定 T+1 生效)
//   - 两态同引擎同批跑, 逐位可比(§5.1⑥ 防前视: 预覆盖行只用该日及之前因子; 阈值/参数全固定常数)
//   - 口径: K=1 每日池等分(每笔 10000/当日保留数) → _kellyRecomputeTrade(etf_main 费率) → _kellyComputeStats
//
// 【输入依赖】
//   - $ROOT/static-site/data/{signal_kelly_trades,signal_kelly_backtest,kelly_mode_s06_state,kelly_loss_features,accum_nav_map}.json
//   - $ROOT/static-site/data/index/{csi500,hs300}-all.json(只读; 主树与 trade-data 双树 md5 一致已验证)
//   - $ROOT/static-site/{common,lab}.js(切片源)
// 【输出】stdout 对比表 + $OUT 结果 JSON(默认 /tmp/s06-eliminate-fallback-impact.json)
// 【关键参数种子】THRESHOLD=-3.524224785046781 CONFIRM_DAYS=15 MIN_HOLD_DAYS=10 LOOKBACK=20 K=1 PRE_OFF='new14'
//   预覆盖段因子 = csi500_ret20 - hs300_ret20(2014 前 csi1000 无数据, 方案2 代理因子, 用户拍板)
// 【复现命令】node docs/kelly/analysis/scripts/s06-eliminate-fallback-impact.mjs
// 【诚实标注】本脚本为「第二份实现」(JS 复刻 s06_segment_style_backtest.py 的 build_base_sticky), 已与
//   s06_segment_style_backtest.py 输出对账(2011-2014 段 方案2 sticky net 5,943.58 一致); 全周期数字以
//   本脚本两态对比为准, 上线后须 §5.4⑦ 同构对账机检(页面真实渲染 vs 本脚本输出逐位)。
// part1: 头文件与 sliceDecl
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
const __dirname = path.dirname(fileURLToPath(import.meta.url));
// ROOT 默认主树;在 worktree/分支跑切片时用 REPRO_ROOT=<worktree根> 指到含改动逻辑的树,避开主树
//(2026-09-02 曾因默认写主树覆盖主树磁盘 repro-out.json 为 fail-open 旧数 → 加 REPRO_ROOT/REPRO_OUT 双开关)
const ROOT = process.env.REPRO_ROOT || "/Users/linhuichen/code/trade";
// NOTE: 兜底态权威数字(230.83%)= 本脚本在工作树 feat/s06-offbase-new14(quickly切片含 out_of_range_fallback 逻辑 + V2 快照 off_base=new14)重跑得出;
// 主树 merge 后 主树 common.js 也含该逻辑 + s06_snapshot.sh 同步 V2 快照后,本脚本默认路径即可逐位复现。
// 输出默认落在 ROOT 下;不想覆盖已有产物时用 REPRO_OUT 指到临时/本分支路径(如 REPRO_OUT=/tmp/repro-out.json)。
const TRADES_JSON = ROOT + "/static-site/data/signal_kelly_trades.json";
const BACKTEST_JSON = ROOT + "/static-site/data/signal_kelly_backtest.json";
const S06_JSON = ROOT + "/static-site/data/kelly_mode_s06_state.json";
const FEAT_JSON = ROOT + "/static-site/data/kelly_loss_features.json";
const NAV_JSON = ROOT + "/static-site/data/accum_nav_map.json";
const COMMON_JS = ROOT + "/static-site/common.js";
const LAB_JS = ROOT + "/static-site/lab.js";
const OUT_JSON = process.env.REPRO_OUT || "/tmp/s06-eliminate-fallback-impact.json";
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
// 可重入: 注入任意 daily 数组 → 重建 _tdsS06State/_tdsS06ByDate(基线=原快照, 场景=原快照+预覆盖行)
function setS06Daily(dailyArr) {
  const snap = Object.assign({}, s06, { daily: dailyArr });
  vm.runInContext(`
    _tdsS06State = __S06__;
    _tdsS06ByDate = {};
    for (var i = 0; i < __S06__.daily.length; i++) _tdsS06ByDate[_tdsS06NormalizeDate(__S06__.daily[i].date)] = __S06__.daily[i];
    _tdsS06FiltersCache = null;
  `, Object.assign(ctx, { __S06__: snap }));
}
// ── 方案2 预覆盖段基座: csi500_ret20 - hs300_ret20, sticky 状态机(js 复刻 s06_segment_style_backtest.py
//    build_base_sticky, 逐行对照; 参数=现快照 CONFIRM_DAYS=15/MIN_HOLD_DAYS=10, 阈值=现冻结值)
const THRESHOLD = s06.threshold;         // -3.524224785046781
const CONFIRM_DAYS = s06.confirm_days || 15;
const MIN_HOLD_DAYS = s06.min_hold_days || 10;
const LOOKBACK = s06.lookback_days || 20;
const PRE_OFF = s06.off_base || "new14";
function loadIdxCloses(name) {
  const d = JSON.parse(fs.readFileSync(ROOT + "/static-site/data/index/" + name + "-all.json", "utf8"));
  const m = {};
  for (const x of d.ohlc || []) if (x.close != null) m[String(x.date)] = Number(x.close);
  return m;
}
function rollRet(series, dates, n) {
  const vals = dates.map(function (d) { return series[d]; });
  const out = {};
  for (let i = n; i < vals.length; i++) {
    if (vals[i] == null || vals[i - n] == null) continue;
    out[dates[i]] = (vals[i] / vals[i - n] - 1) * 100;
  }
  return out;
}
function buildPreDaily() {
  const c5 = loadIdxCloses("csi500"), hs = loadIdxCloses("hs300");
  const common = Object.keys(c5).filter(function (d) { return hs[d] != null; }).sort();
  const rc5 = rollRet(c5, common, LOOKBACK), rhs = rollRet(hs, common, LOOKBACK);
  const spread = {};
  for (const d of common) if (rc5[d] != null && rhs[d] != null) spread[d] = rc5[d] - rhs[d];
  const seg = common.filter(function (d) { return d >= "20100101" && d < "20141114" && spread[d] != null; });
  // sticky 状态机(premise T 日收盘判定 → T+1 生效; 与 gen_kelly_mode_s06_state.py build_daily 同语义)
  const rows = [];
  let cur = PRE_OFF, broken = 0, held = 0, prev = null;
  for (const d of seg) {
    const sv = spread[d];
    let ex, dec_date = null;
    if (prev === null) {
      ex = PRE_OFF;
    } else {
      const p = spread[prev];
      const hit = (p != null && p < THRESHOLD);
      if (cur === "a9") {
        broken = hit ? 0 : broken + 1;
        held += 1;
        const stay = (broken < CONFIRM_DAYS) || (held < MIN_HOLD_DAYS);
        ex = stay ? "a9" : PRE_OFF;
        if (!stay) held = 0;
      } else {
        ex = hit ? "a9" : PRE_OFF;
        if (ex === "a9") { held = 1; broken = 0; }
      }
      dec_date = prev;
    }
    rows.push({ date: d, size_spread: sv, premise: (sv == null ? null : sv < THRESHOLD), effective_mode: ex, decision_date: dec_date });
    cur = ex; prev = d;
  }
  return rows;
}
const PRE_DAILY = buildPreDaily();
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
  // [2026-09-02 修复] 原实现 `return _s6NB[b.base]` 返回过滤器对象(恒 truthy) → NoBull 过滤形同虚设,
  //   与页面 lab.js L8517-8524 passesFadeNoBull(返回布尔) 不一致。修正为返回 `passesStaticFade(...)` 布尔。
  //   同步页面 lab.js passesFadeNoBull: 覆盖期外 → _tdsS06BaseForDate 返回 {ok:true, base:off_base, reason:"out_of_range_fallback"},
  //   按 off_base(快照运行时字段) 构建键集真过滤, 不 fail-open 也不拒绝(兜底态);
  //   ok:false 仅限 not_loaded/load_err/no_row 真降级 → fail-open 放行, 与 passesS06(L150 `if (!f6) return true`) 同构。
  const dStr = String(t[fIdx.signal_date] || "");
  const b = vm.runInContext("_tdsS06BaseForDate(__D6__)", Object.assign(ctx, { __D6__: dStr }));
  if (!b || !b.ok) return true;   // 仅真降级(not_loaded/load_err/no_row) fail-open
  if (!_s6NB[b.base]) {
    const allK = vm.runInContext("_KELLY_FADE_ALL_KEYS", ctx);
    const f = {};
    for (const k of allK) f[k] = false;
    const p = vm.runInContext("_tdsFadeModeById(__ID__)", Object.assign(ctx, { __ID__: b.base }));
    if (p && Array.isArray(p.keys)) for (const k of p.keys) f[k] = true;
    f.bullAuxBackupStop = false;
    _s6NB[b.base] = f;
  }
  return passesStaticFade(t, _s6NB[b.base]);   // 布尔(真过滤), 对齐页面 L8523
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
      // [2026-09-02 修复] 补 buy_price/sell_price: P 法(G/I)强平 real 通路 _kellyAihlineRealizeReal 依赖
      //   sel.buy_price 算真实盈亏, 缺了它会落 no_buy_price 分支按 pr=0(非 null)计入 → G/I 强平利润被压掉(页面不符)。
      buy_price: t[fIdx.buy_price] != null ? Number(t[fIdx.buy_price]) : 0,
      sell_price: t[fIdx.sell_price] != null ? Number(t[fIdx.sell_price]) : 0,
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
// part3: 主驱动 + 扩展维度
function runBase(baseId, dailyArr) {
  if (baseId === "s06") setS06Daily(dailyArr);
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
  const out = { pool_n: pool.length, kept_n: Object.keys(kept).length, keptNB_n: keptNB ? Object.keys(keptNB).length : null, modes: {} };
  const trades_s06 = {};
  for (const mk of Object.keys(modes)) {
    const m = modes[mk];
    out.modes[mk] = {};
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
      out.modes[mk][pk] = row;
    }
    // 全周期 trade 序列(供扩展维度) 仅存 s06 基座(逐笔太巨大)
    if (baseId === "s06") {
      trades_s06[mk] = m._allTrades.map(function (t) { return { bd: t.buy_date, sd: t.sell_date, p: t.profit, a: t.amount, pr: t.return_pct }; });
    }
  }
  out._trades_s06 = baseId === "s06" ? trades_s06 : null;
  return out;
}
// ---- 扩展维度(参数化: tradesS06 + basesS06, 基线/场景各算一份) ----
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
  let recovTrading = 0;
  if (recoverDate) {
    const ds = sorted.filter(function (e) { return e.d > valleyDate && e.d <= recoverDate; });
    recovTrading = new Set(ds.map(function (e) { return e.d; })).size;
  }
  return { max_drawdown_abs: Math.round(maxAbs * 100) / 100, peak_date: peakDate, valley_date: valleyDate, recover_date: recoverDate || null, recovery_trading_days: recovTrading };
}
const BEAR_WINDOWS = [
  { id: "2015-股灾", s: "20150615", e: "20160229" },
  { id: "2018-单边熊", s: "20180101", e: "20181231" },
  { id: "2022-阴跌", s: "20220101", e: "20221031" },
  { id: "2024-初微盘崩", s: "20240101", e: "20240229" },
  { id: "2026-近端", s: "20260101", e: "20260901" },
];
function computeExt(tradesS06, basesS06) {
  const ext = {};
  const yearTrades = tradesS06 || {};
  ext.yearly = {};
  for (const mk of Object.keys(yearTrades)) ext.yearly[mk] = yearlyFor(mk, yearTrades[mk]);
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
  ext.drawdown = {};
  for (const mk of Object.keys(yearTrades)) ext.drawdown[mk] = drawdownRecovery(yearTrades[mk]);
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
  ext.operability = {};
  for (const mk of Object.keys(basesS06.modes)) {
    const all = basesS06.modes[mk]["all"];
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
  return ext;
}
// ── 驱动: 基线(现快照, 110笔走 off_base=new14) vs 场景(方案2 pre 行 + 现快照) ──
const S06_BASE = runBase("s06", s06.daily);
const S06_SCEN = runBase("s06", PRE_DAILY.concat(s06.daily));
// new14/a9 静态基座与 s06 daily 无关, 只跑一次(场景数字同, 供对照): s06 场景下 kept 池内 2014前段日金额变化会微调各模式池, 但两静态档不读 s06 → 逐位同基线。
const N14 = runBase("new14", null);
const A9 = runBase("a9", null);
setS06Daily(s06.daily); // 复位到基线(防后续意外依赖)
const result = {
  generated_at: new Date().toISOString(),
  config: { buy_amount: BUY_AMOUNT, fee: FEE_MAIN, periods: bk.config.periods, period_cutoffs: cutoffs, gih: GIH_STRAT, threshold: THRESHOLD, confirm_days: CONFIRM_DAYS, min_hold_days: MIN_HOLD_DAYS, pre_segment: "20100104~20141113 csi500_ret20 - hs300_ret20 sticky", note: "基线=现快照(110笔 off_base=new14); 场景=方案2 预覆盖行注入" },
  baseline: { s06: S06_BASE, ext: null, new14: null, a9: null },
  scenario: { s06: S06_SCEN, ext: null, new14: N14, a9: A9 },
};
result.baseline.new14 = N14; result.baseline.a9 = A9;
result.baseline.ext = computeExt(S06_BASE._trades_s06, S06_BASE);
result.scenario.ext = computeExt(S06_SCEN._trades_s06, S06_SCEN);
const summary = { baseline: S06_BASE, scenario: S06_SCEN };
fs.writeFileSync(OUT_JSON, JSON.stringify({ summary: summary, baseline_ext: result.baseline.ext, scenario_ext: result.scenario.ext, pre_daily_n: PRE_DAILY.length, pre_a9_days: PRE_DAILY.filter(function (r) { return r.effective_mode === "a9"; }).length }, null, 1));
console.log("WROTE " + OUT_JSON);
// ---- 对比表: 各 mode all 周期(现快照 vs 方案2) ----
console.log("pre_daily_n=" + PRE_DAILY.length + "  (2014前段 a9 天数=" + PRE_DAILY.filter(function (r) { return r.effective_mode === "a9"; }).length + ")");
console.log("probe: pre 首日=" + PRE_DAILY[0].date + " 末日=" + PRE_DAILY[PRE_DAILY.length - 1].date);
console.log("pool baseline=" + S06_BASE.pool_n + " kept=" + S06_BASE.kept_n + " | scenario pool=" + S06_SCEN.pool_n + " kept=" + S06_SCEN.kept_n);
const col = function (pk, r, g) { const t = g || r; return pk + ": " + t.return_pct_max_holding + "% | +" + t.total_profit + " | mcc=" + t.max_concurrent_capital + "元 | n=" + t.n + (g ? "(gih)" : ""); };
function rowDiff(mk) {
  const b = S06_BASE.modes[mk], s = S06_SCEN.modes[mk];
  const cellsB = [], cellsS = [];
  for (const pk of ["all", "y1", "y3", "y5", "y10"]) {
    if (!b[pk]) continue;
    const rb = b[pk], rs = s[pk];
    const tb = rb.gihreal || rb, ts = rs.gihreal || rs;
    const dProfit = Math.round((ts.total_profit - tb.total_profit) * 100) / 100;
    const dPct = Math.round((ts.return_pct_max_holding - tb.return_pct_max_holding) * 10000) / 10000;
    cellsB.push(pk + ": " + tb.return_pct_max_holding + "% | +" + tb.total_profit + (rb.gihreal ? "(gih)" : ""));
    cellsS.push(pk + ": " + ts.return_pct_max_holding + "% | +" + ts.total_profit + (rs.gihreal ? "(gih)" : ""));
    if (pk === "all") { if (rb.gihreal || rs.gihreal) console.log("  " + mk + " all Δprofit=" + dProfit + "  Δpct=" + dPct + "pp  (gih);  n " + tb.n + "→" + ts.n); else console.log("  " + mk + " all Δprofit=" + dProfit + "  Δpct=" + dPct + "pp;  n " + tb.n + "→" + ts.n); }
  }
  return { b: mk + " :: " + cellsB.join("  ;  "), s: mk + " :: " + cellsS.join("  ;  ") };
}
console.log("───── 全周期(all)影响对比 ─────");
for (const mk of MODES_OF_INTEREST) {
  if (S06_BASE.modes[mk]) rowDiff(mk);
}
console.log("───── 按年 Δprofit(方案2 - 基线, s06 H 卡) ─────");
const yb = result.baseline.ext.yearly["H"] || {}, ys2 = result.scenario.ext.yearly["H"] || {};
const yrs = new Set(Object.keys(yb).concat(Object.keys(ys2)));
for (const yr of [...yrs].sort()) {
  const b = yb[yr] || { profit: 0, n: 0 }, s = ys2[yr] || { profit: 0, n: 0 };
  console.log("  " + yr + ": baseline +" + Math.round(b.profit * 100) / 100 + " (n=" + b.n + ") → scenario +" + Math.round(s.profit * 100) / 100 + " (n=" + s.n + ")  Δ=" + Math.round((s.profit - b.profit) * 100) / 100);
}
console.log("───── 2014前段专属(2011~2014 按 buy_date, s06 H 卡) ─────");
let pb = 0, ps = 0, nb = 0, ns = 0;
// [2026-09-02 对账修复] 原来只遍历 scenario 年份键: 方案2 下 H 卡 2012 年零交易 → scenario 无 2012 键 →
//   baseline 的 2012(+2051.04/n2)被静默漏掉, 段专属 baseline 误报 n=17/+12298.63(真值 n=19/+16349.68)。
//   改为遍历 baseline∪scenario 并集(与上方按年表一致)。
const allYr = new Set(Object.keys(yb).concat(Object.keys(ys2)));
for (const yr of [...allYr].sort()) { if (yr === "2011" || yr === "2012" || yr === "2013" || yr === "2014") { pb += yb[yr] ? yb[yr].profit : 0; nb += yb[yr] ? yb[yr].n : 0; ps += ys2[yr] ? ys2[yr].profit : 0; ns += ys2[yr] ? ys2[yr].n : 0; } }
console.log("  2011-2014 baseline n=" + nb + " +" + Math.round(pb * 100) / 100 + " → scenario n=" + ns + " +" + Math.round(ps * 100) / 100 + "  Δ=" + Math.round((ps - pb) * 100) / 100);
