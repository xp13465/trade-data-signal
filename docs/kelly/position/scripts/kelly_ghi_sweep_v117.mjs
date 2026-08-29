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
const OUT_JSON = path.join(__dirname, "kelly_ghi_sweep_out.json");

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

// ===== CAP SWEEP =====
const caps = [];
for (let c = 5; c <= 20; c++) caps.push(c * 10000);
// G fine sweep near peak
const gFine = [115000, 120000, 125000, 130000, 135000];
for (const f of gFine) if (!caps.includes(f)) caps.push(f);
caps.sort((a, b) => a - b);

console.log(`Sweeping ${caps.length} caps: ${caps.map(c => c/10000+"万").join(", ")}`);

const result = {
  generated_at: new Date().toISOString(),
  trades_generated_at: td.generated_at,
  s06_snapshot_at: s06.generated_at,
  baseline: "v1.1.7 S06 + passesFadeNoBull + posCap K1 + daily pool + fee etf_main",
  basePoolNB: basePoolNB.length,
  g: { nTrades: reconG.length, caps: {} },
  h: { nTrades: reconH.length, caps: {} },
  i: { nTrades: reconI.length, caps: {} },
};

for (const cap of caps) {
  const gRes = evalCap("G", "P", cap, reconG);
  const hRes = evalCap("H", "A", cap, reconH);
  const iRes = evalCap("I", "A", cap, reconI);
  result.g.caps[cap] = { b0: gRes.b0, b1: gRes.b1, peak: gRes.peak };
  result.h.caps[cap] = { b0: hRes.b0, b1: hRes.b1, peak: hRes.peak };
  result.i.caps[cap] = { b0: iRes.b0, b1: iRes.b1, peak: iRes.peak };
  if (caps.indexOf(cap) % 4 === 0) console.log(`  cap ${cap/10000}万 done`);
}

// ===== Summary table (for report) =====
function fmtNum(v) { return v != null ? (typeof v === 'number' ? +v.toFixed(4) : v) : null; }
function rowStr(c, m, mode) {
  const r = result[mode].caps[c];
  if (!r) return "";
  const b0 = r.b0 || {}, b1 = r.b1 || {};
  const peak = r.peak || 0;
  const mult = peak / 10000;
  const op = peak <= 200000 ? "OK" : "NO";
  return `${(c/10000).toFixed(2)}万 | `+
    `净b0=${fmtNum(b0.total_profit)} b1=${fmtNum(b1.total_profit)} | `+
    `收b0=${fmtNum(b0.return_pct_max_holding)}% b1=${fmtNum(b1.return_pct_max_holding)}% | `+
    `calmar=${fmtNum(b1.calmar)} | `+
    `peak=${peak} ${mult.toFixed(1)}x ${op} | `+
    `wr=${fmtNum(b1.win_rate)}% n=${r.b0?.n || 0}`;
}

let out = "";
out += `\n====== G (P≤3d, method P) ======\n`;
out += `G recon n=${reconG.length}\n`;
out += `cap | 净b0/b1 | 收b0/b1% | calmar | peak x倍数 可操作 | winRate n\n`;
for (const c of caps.filter(c => c >= 50000 && c <= 200000)) out += rowStr(c, "G", "g") + "\n";
out += `\n--- G fine near peak ---\n`;
for (const c of gFine) out += rowStr(c, "G", "g") + "\n";

out += `\n====== H (method A, b0=b1) ======\n`;
out += `H recon n=${reconH.length}\n`;
out += `cap | 净b0=b1 | 收% | calmar | peak x倍数 可操作 | winRate n\n`;
for (let c = 5; c <= 20; c++) out += rowStr(c * 10000, "H", "h") + "\n";

out += `\n====== I (method A, b0=b1) ======\n`;
out += `I recon n=${reconI.length}\n`;
out += `cap | 净b0=b1 | 收% | calmar | peak x倍数 可操作 | winRate n\n`;
for (let c = 5; c <= 20; c++) out += rowStr(c * 10000, "I", "i") + "\n";

// ===== By-year decomposition (for selected cap) =====
function byYearStats(tradesRecomputed, strat) {
  const applyRes = vm.runInContext("_kellyAihlineApply(__TR__, __STRAT__, 'all')",
    Object.assign(ctx, { __TR__: tradesRecomputed, __STRAT__: strat }));
  const kept = applyRes.b1; // use b1 (optimistic) for comparison
  if (!kept || !kept.length) return null;
  const byYear = {};
  for (const t of kept) {
    const y = (t.buy_date || "").substring(0, 4);
    if (!byYear[y]) byYear[y] = [];
    byYear[y].push(t);
  }
  const res = {};
  for (const y of Object.keys(byYear).sort()) {
    const st = vm.runInContext("_kellyComputeStats(__K__, 'all', 10000)", Object.assign(ctx, { __K__: byYear[y] }));
    res[y] = { n: st.n, total_profit: st.total_profit, return_pct_max_holding: st.return_pct_max_holding, win_rate: st.win_rate, max_concurrent_capital: st.max_concurrent_capital };
  }
  return res;
}

// Selected cap per mode for by-year analysis: G=13万, H=7万, I=15万 (codex handoff defaults)
out += `\n\n====== By-year: G@13万 ======\n`;
const gy = byYearStats(reconG, { method: "P", cap: 130000 });
if (gy) for (const y of Object.keys(gy).sort()) out += `  ${y}: n=${gy[y].n} profit=${fmtNum(gy[y].total_profit)} ret=${fmtNum(gy[y].return_pct_max_holding)}% wr=${fmtNum(gy[y].win_rate)}\n`;

out += `\n====== By-year: H@7万 ======\n`;
const hy = byYearStats(reconH, { method: "A", cap: 70000 });
if (hy) for (const y of Object.keys(hy).sort()) out += `  ${y}: n=${hy[y].n} profit=${fmtNum(hy[y].total_profit)} ret=${fmtNum(hy[y].return_pct_max_holding)}% wr=${fmtNum(hy[y].win_rate)}\n`;

out += `\n====== By-year: I@15万 ======\n`;
const iy = byYearStats(reconI, { method: "A", cap: 150000 });
if (iy) for (const y of Object.keys(iy).sort()) out += `  ${y}: n=${iy[y].n} profit=${fmtNum(iy[y].total_profit)} ret=${fmtNum(iy[y].return_pct_max_holding)}% wr=${fmtNum(iy[y].win_rate)}\n`;

// ===== Write output =====
result._summaryText = out;
fs.writeFileSync(OUT_JSON, JSON.stringify(result, null, 1));
console.log(`\nWritten to ${OUT_JSON}`);
console.log(out);
