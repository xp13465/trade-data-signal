#!/usr/bin/env node
/**
 * check_posrating_parity.mjs - K 档评级 Python 后端 vs lab.js 前端 逐位对账机检(§5.4⑦)
 *
 * 【目的】断言 scripts/kelly_posrating.py 的输出与 lab.js _kellyApplyFeeRecompute K 档段
 *         (A模式 all 伪象限 + S06 per-date passesFade + 每日池等分 top-K) 在真实数据上逐位一致
 *         (n/retNum/ddNum 全部相等)。方法=check_fade_predicate_parity.mjs 同精神:
 *         不重写判定逻辑做影子对照, 而是把 lab.js/common.js 真实源码函数体切片提取进 vm 沙箱执行,
 *         保证验的就是上线代码本身。
 * 【输入】env TRADES_JSON(默认主仓库 static-site/data/signal_kelly_trades.json) + BT_JSON
 *         + S06_JSON + FEAT_JSON(绝对路径; worktree 无 gitignored 数据产物必须指绝对路径)
 * 【输出】四档逐位对比 + basePool/posRaw 计数 + PASS/FAIL; 任一不一致 exit 1。
 * 【复现】TRADES_JSON=... BT_JSON=... S06_JSON=... FEAT_JSON=... node scripts/check_posrating_parity.mjs
 */
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const env = process.env;
const TRADES_JSON = env.TRADES_JSON || "/Users/linhuichen/code/trade/static-site/data/signal_kelly_trades.json";
const BT_JSON = env.BT_JSON || "/Users/linhuichen/code/trade/static-site/data/signal_kelly_backtest.json";
const S06_JSON = env.S06_JSON || "/Users/linhuichen/code/trade/static-site/data/kelly_mode_s06_state.json";
const FEAT_JSON = env.FEAT_JSON || "/Users/linhuichen/code/trade/static-site/data/kelly_loss_features.json";

// ---------------------------------------------------------------------------
// 切片提取(与 check_fade_predicate_parity.mjs 同一工具)
// ---------------------------------------------------------------------------
function sliceDecl(src, name) {
  const pats = [
    new RegExp(`(?:^|\\n)\\s*(?:async\\s+)?function\\s+${name}\\s*\\(`),
    new RegExp(`(?:^|\\n)\\s*(?:var|const|let)\\s+${name}\\s*=`),
  ];
  let start = -1, kind = null;
  for (let i = 0; i < pats.length; i++) {
    const m = src.match(pats[i]);
    if (m) { start = m.index + (/^\n/.test(m[0]) ? 1 : 0); kind = i === 0 ? "fn" : "decl"; break; }
  }
  if (start < 0) return null;
  let inS = null, esc = false;
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
  const ctx = vm.createContext({ console, JSON, Math, Date, isFinite, parseFloat, parseInt, String, Number, Boolean, Array, Object, Map, Set, Promise, NaN, Infinity, undefined });
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
// 函数与常量清单(common.js 规格/判定/S06; lab.js 计算链)
// ---------------------------------------------------------------------------
const COMMON_SYMBOLS = [
  "_KELLY_FADE_LEGACY_SPECS", "_KELLY_FADE_FRONT_KEY_ORDER", "_KELLY_FADE_GATE_KEY_ORDER",
  "_KELLY_FADE_T1_KEYS", "_KELLY_FADE_ALL_KEYS",
  "_tdsFadeSpecHit", "_KELLY_FADE_MODE_PRESETS", "_tdsFadeModeById",
  "_tdsS06NormalizeDate", "_tdsS06BaseForDate", "_tdsS06FiltersForDate",
];
const LAB_SYMBOLS = [
  "_kellyIsShEtf", "_kellyBuyWeekday", "_kellyBuypriceBin", "_kellyBuildTradeDims",
  "_kellyBaseKey", "_kellyTradeFeatures", "_kellyMonthMask", "_kellyActiveMonthMask",
  "_kellyLossRuleHit", "_kellyPassesFadeFilters", "_kellyPositionCapKeptKeys",
  "_kellyCollectBasePool", "_kellyKeptDayCounts", "_kellyPerTradeAmount",
  "_kellyMaxConcurrent", "_kellyMaxConcurrentCapital", "_kellyDateDiffDays",
  "_kellyYearsFromTrades", "_kellyMaxDrawdown", "_kellyComputeKelly",
  "_kellyAnnualizedReturn", "_kellyComputeStats", "_kellyRecomputeTrade",
];

const td = JSON.parse(fs.readFileSync(TRADES_JSON, "utf8"));
const bt = JSON.parse(fs.readFileSync(BT_JSON, "utf8"));
const s06 = JSON.parse(fs.readFileSync(S06_JSON, "utf8"));
let featDoc = null;
try { featDoc = JSON.parse(fs.readFileSync(FEAT_JSON, "utf8")); } catch { featDoc = null; }

const sources = [
  { rel: "static-site/common.js", symbols: COMMON_SYMBOLS, text: fs.readFileSync(path.join(ROOT, "static-site/common.js"), "utf8") },
  { rel: "static-site/lab.js", symbols: LAB_SYMBOLS, text: fs.readFileSync(path.join(ROOT, "static-site/lab.js"), "utf8") },
];
const { ctx, missing } = buildContext(sources);
if (missing.length) console.log(`[parity] 未提取符号(${missing.length}): ${missing.join(", ")}`);
const KELLY_ORIG_SLIPPAGE = 0.001;
const FEE_ETF_MAIN = { commission_rate: 0.00005, min_commission: 0.1, slippage: 0.001, transfer_fee_rate_sh: 0.00001, stamp_duty_rate: 0 };

// S06 沙箱态 + 特征规格 stub + 计算链胶水(K 档段逻辑逐行对齐 lab.js L8440-8791)
vm.runInContext(`
  var KELLY_ORIG_SLIPPAGE = ${KELLY_ORIG_SLIPPAGE};
  var _tdsS06State = __S06__;
  var _tdsS06ByDate = {};
  ((__S06__.daily)||[]).forEach(function(r){ _tdsS06ByDate[String(r.date).replace(/[^0-9]/g,"")] = r; });
  var _tdsS06FiltersCache = null;
  var state = { kellyLossFeatData: null, kellyLossSpecMap: {} };
  var _kellyTradeFeatureCache = new Map();
  var _kellyYield = function () { return Promise.resolve(); };
`, Object.assign(ctx, { __S06__: s06 }));
if (featDoc) {
  vm.runInContext(`
    state.kellyLossFeatData = __FEAT__;
    ((__FEAT__.meta && __FEAT__.meta.rules)||[]).forEach(function(r){ state.kellyLossSpecMap[r.key] = r; });
  `, Object.assign(ctx, { __FEAT__: featDoc }));
}

const fIdx = {};
(td.fields || []).forEach((f, i) => { fIdx[f] = i; });
const buyAmount = td.buy_amount || (bt.config && bt.config.buy_amount) || 10000;
const sellModes = (bt.config && bt.config.sell_modes) || {};
const quads = td.quadrants || {};

vm.runInContext(`
  var __td = __TD__, __fIdx = __FIDX__, __sellModes = __SELLMODES__;
  var _tradeDims = _kellyBuildTradeDims(__td, __fIdx);
  var quadsAll = {};
  for (var _qmk in __sellModes) {
    var _qa = [];
    ["rating_high","rating_mid","rating_low"].forEach(function(_rk){ _qa = _qa.concat((__td.quadrants[_rk]||{})[_qmk]||[]); });
    quadsAll[_qmk] = _qa;
  }
  var passesFade = function (t) {
    var f6 = _tdsS06FiltersForDate(String(t[__fIdx.signal_date] || ""));
    if (!f6) return true;
    return _kellyPassesFadeFilters(t, __fIdx, f6, _kellyTradeFeatureCache, _tradeDims, _kellyActiveMonthMask(f6));
  };
`, Object.assign(ctx, { __TD__: td, __FIDX__: fIdx, __SELLMODES__: sellModes }));

const outRaw = vm.runInContext(`
  (async function () {
    var basePool = await _kellyCollectBasePool(__td.quadrants, __sellModes, __fIdx, passesFade);
    var _posModeKey = null;
    for (var _pmk in __sellModes) { if (_pmk === "A") { _posModeKey = _pmk; break; } }
    if (!_posModeKey) return { err: "no A mode" };
    var _posBase = basePool;
    var _posRaw = quadsAll[_posModeKey];
    var _posVals = {};
    var _k1KeptKeys = null;
    var feeParams = __FEE__;
    for (var _pk = 1; _pk <= 4; _pk++) {
      var _kept = _kellyPositionCapKeptKeys(_posBase, __fIdx, _pk);
      var _posDayCounts = _kellyKeptDayCounts(_kept);
      var _keptArr = [];
      for (var _ti = 0; _ti < _posRaw.length; _ti++) {
        var _tb = _posRaw[_ti];
        if (!passesFade(_tb)) continue;
        if (!_kept[_kellyBaseKey(_tb, __fIdx)]) continue;
        _keptArr.push(_tb);
      }
      if (_pk === 1) _k1KeptKeys = _keptArr.map(function (tt) { return _kellyBaseKey(tt, __fIdx); });
      var _recomp = _keptArr.map(function (tt) {
        var _amt = _kellyPerTradeAmount(tt, __fIdx, ${buyAmount}, _posDayCounts ? _posDayCounts[tt[__fIdx.signal_date]] : null);
        var _r = _kellyRecomputeTrade(tt, __fIdx, feeParams, _amt);
        return { profit: _r.profit, return_pct: _r.return_pct, fee_cost: _r.fee_cost,
                 buy_date: tt[__fIdx.buy_date] || "", sell_date: tt[__fIdx.sell_date] || "",
                 hold_days: tt[__fIdx.hold_days] || 0, amount: _amt };
      });
      var _st = _kellyComputeStats(_recomp, "all", ${buyAmount});
      var _ret = _st.return_pct_max_holding;
      var _dd = _st.max_concurrent_capital > 0 ? Math.round(_st.max_drawdown / _st.max_concurrent_capital * 100 * 10000) / 10000 : 0;
      _posVals[_pk] = { name: "", ret: _ret.toFixed(2) + "%", dd: _dd.toFixed(2) + "%",
        ra: _dd > 0 ? (_ret / _dd).toFixed(2) : "-", n: _st.n.toLocaleString("en-US"),
        retNum: _ret, ddNum: _dd, nNum: _st.n,
        totalProfit: _st.total_profit, concCap: _st.max_concurrent_capital,
        mdd: _st.max_drawdown, sumAmt: _recomp.reduce(function(s,t){return s+(t.amount||0);},0) };
    }
return { basePool: basePool.length, posRaw: _posRaw.length, values: _posVals, k1KeptKeys: _k1KeptKeys,
           basePoolKeys: basePool.map(function(tt){ return _kellyBaseKey(tt, __fIdx); }) };
  })()
`, Object.assign(ctx, { __FEE__: FEE_ETF_MAIN }));
const out = await outRaw;
if (!out || out.err) throw new Error("沙箱计算失败: " + JSON.stringify(out));
console.log(`[parity] lab basePool=${out.basePool} posRaw=${out.posRaw}`);
for (let k = 1; k <= 4; k++) {
  const v = out.values[k];
  console.log(`[parity] K${k}: ret=${v.ret} dd=${v.dd} ra=${v.ra} n=${v.n} (retNum=${v.retNum} ddNum=${v.ddNum} nNum=${v.nNum})`);
  if (k === 1) console.log(`[parity] K1 中间量: totalProfit=${v.totalProfit} concCap=${v.concCap} mdd=${v.mdd} sumAmt=${v.sumAmt}`);
}
if (out.k1KeptKeys) {
  fs.writeFileSync("/tmp/lab_k1_kept.json", JSON.stringify(out.k1KeptKeys));
  console.log(`[parity] 已写 /tmp/lab_k1_kept.json (${out.k1KeptKeys.length} 笔)`);
}
if (out.basePoolKeys) {
  fs.writeFileSync("/tmp/lab_basepool.json", JSON.stringify(out.basePoolKeys));
  console.log(`[parity] 已写 /tmp/lab_basepool.json (${out.basePoolKeys.length} 笔)`);
}

// 与 Python 产物对比(env PY_JSON 传入 latest_posrating.json; 缺失则仅打印 lab 侧)
const PY_JSON = env.PY_JSON || null;
let py = null;
if (PY_JSON && fs.existsSync(PY_JSON)) py = JSON.parse(fs.readFileSync(PY_JSON, "utf8"));
let fail = 0;
if (py && py.values) {
  for (let k = 1; k <= 4; k++) {
    const lv = out.values[k], pv = py.values[k];
    if (!lv || !pv) { console.log(`[parity] K${k}: 缺侧值(lab=${!!lv} py=${!!pv})`); fail++; continue; }
    const cmp = (a, b) => Math.abs(a - b) < 0.011; // 0.01pp 差异容差(§5.4⑦)
    const okN = lv.nNum === pv.nNum;
    const okR = cmp(lv.retNum, pv.retNum);
    const okD = cmp(lv.ddNum, pv.ddNum);
    const tag = okN && okR && okD ? "PASS" : "FAIL";
    if (tag === "FAIL") fail++;
    console.log(`[parity] K${k} 对比: lab n=${lv.nNum}(ret=${lv.retNum},dd=${lv.ddNum}) py n=${pv.nNum}(ret=${pv.retNum},dd=${pv.ddNum}) => ${tag}`);
  }
  console.log(fail === 0 ? "[parity] 全部 PASS" : `[parity] ${fail} 档 FAIL`);
  process.exit(fail === 0 ? 0 : 1);
} else {
  console.log("[parity] 未提供 PY_JSON, 仅输出 lab 侧结果");
  process.exit(0);
}
