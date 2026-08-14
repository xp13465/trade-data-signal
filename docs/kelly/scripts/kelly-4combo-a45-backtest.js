// ============================================================
// 用途: 4组合+a45 凯利回测复刻(从 lab.js 提取纯函数 + 复刻 _kellyApplyFeeRecompute 的 all 象限+allYearly 计算)
// 日期/来源: 2026-08-12 / tmp
// 结论: 4组合+a45 的 pool vs fixed 回测, 用于组合对比
// 依赖: 无(读取 static-site/lab.js + trades/backtest json)
// 输入/输出: 读 lab.js + signal_kelly_trades/backtest.json, 输出 /tmp/kelly-4combo-a45-backtest.json
// 复现: node kelly-4combo-a45-backtest.js
// 注意: 原文件含硬编码绝对路径; 如需重跑请确认路径或改相对路径
// ============================================================
// 凯利回测复刻: 从 lab.js 提取纯函数 + 复刻 _kellyApplyFeeRecompute 的 all 象限+allYearly 计算
// 只读不改; 输出 /tmp/kelly-4combo-a45-backtest.json
const fs = require("fs");
const LABJS = "/Users/linhuichen/code/trade/static-site/lab.js";
const TRADES = "/Users/linhuichen/code/trade/static-site/data/signal_kelly_trades.json";
const BACKTEST = "/Users/linhuichen/code/trade/static-site/data/signal_kelly_backtest.json";

const src = fs.readFileSync(LABJS, "utf8");
const lines = src.split("\n");
// 提取 L6978(const KELLY_ORIG_SLIPPAGE) 到 L7602(_kellyMaxConcurrentCapital 结束) 的纯函数块
const block = lines.slice(6977, 7604).join("\n");
eval(block);

const td = JSON.parse(fs.readFileSync(TRADES, "utf8"));
const bt = JSON.parse(fs.readFileSync(BACKTEST, "utf8"));
const fields = td.fields;
const fIdx = {};
fields.forEach((f, i) => { fIdx[f] = i; });
const buyAmount = td.buy_amount || 10000;
const config = bt.config;
const periods = config.periods;
const cutoffs = config.period_cutoffs;
const sellModes = config.sell_modes;
const quads = td.quadrants;

// quadsAll = rating_high+mid+low 并集 per mode
const quadsAll = {};
for (const mk in sellModes) {
  let arr = [];
  ["rating_high", "rating_mid", "rating_low"].forEach((rk) => { arr = arr.concat(quads[rk][mk] || []); });
  quadsAll[mk] = arr;
}
const tradeDims = _kellyBuildTradeDims(td, fIdx);
const feeParams = { commission_rate: 0.0003, min_commission: 5, slippage: 0.001, transfer_fee_rate_sh: 0.00001, stamp_duty_rate: 0 };

function run(filters, amountMode) {
  const featCache = new Map();
  const monthMask = _kellyActiveMonthMask(filters);
  const passesFade = (t) => _kellyPassesFadeFilters(t, fIdx, filters, featCache, tradeDims, monthMask);
  let posCapKept = null, countByDate = null;
  if ((filters.positionCap && filters.positionCapK > 0) || amountMode === "pool") {
    const basePool = _kellyCollectBasePool(quads, sellModes, fIdx, passesFade);
    if (filters.positionCap && filters.positionCapK > 0) posCapKept = _kellyPositionCapKeptKeys(basePool, fIdx, filters.positionCapK);
    if (amountMode === "pool") {
      const keptPool = posCapKept ? basePool.filter((t) => !!posCapKept[_kellyBaseKey(t, fIdx)]) : basePool;
      countByDate = _kellyCountByDate(keptPool, fIdx);
    }
  }
  const result = { all: {} };
  for (const periodKey in periods) result.all[periodKey] = {};
  const recompCache = new Map();
  const recompute = (t) => {
    const amt = _kellyPerTradeAmount(t, fIdx, buyAmount, amountMode, countByDate);
    let c = recompCache.get(t);
    if (!c || c.amt !== amt) { c = { amt: amt, r: _kellyRecomputeTrade(t, fIdx, feeParams, amt) }; recompCache.set(t, c); }
    return c.r;
  };
  for (const modeKey in sellModes) {
    const raw = quadsAll[modeKey] || [];
    const toggled = raw.filter((t) => {
      if (!passesFade(t)) return false;
      if (posCapKept && !posCapKept[_kellyBaseKey(t, fIdx)]) return false;
      return true;
    });
    for (const periodKey in periods) {
      const cutoff = cutoffs[periodKey] || "0";
      const trades = (cutoff && cutoff !== "0") ? toggled.filter((t) => (t[fIdx.buy_date] || "") >= cutoff) : toggled;
      const recomputed = trades.map((t) => {
        const r = recompute(t);
        return { profit: r.profit, return_pct: r.return_pct, fee_cost: r.fee_cost,
                 buy_date: t[fIdx.buy_date] || "", sell_date: t[fIdx.sell_date] || "",
                 hold_days: t[fIdx.hold_days] || 0, amount: _kellyPerTradeAmount(t, fIdx, buyAmount, amountMode, countByDate) };
      });
      result.all[periodKey][modeKey] = _kellyComputeStats(recomputed, periodKey, buyAmount);
    }
  }
  // allYearly(跨模式合并)
  const yearlyMap = {};
  for (const mk in sellModes) {
    for (const t of (quadsAll[mk] || [])) {
      if (!passesFade(t)) continue;
      if (posCapKept && !posCapKept[_kellyBaseKey(t, fIdx)]) continue;
      const yr = (t[fIdx.buy_date] || "").substring(0, 4);
      if (!yr) continue;
      const r = recompute(t);
      const amt = _kellyPerTradeAmount(t, fIdx, buyAmount, amountMode, countByDate);
      if (!yearlyMap[yr]) yearlyMap[yr] = { profit: 0, n: 0, wins: 0, loss: 0, _trades: [] };
      const yk = yearlyMap[yr];
      yk.profit += r.profit; yk.n++;
      if (r.profit > 0) yk.wins++; else yk.loss++;
      yk._trades.push({ buy_date: t[fIdx.buy_date] || "", sell_date: t[fIdx.sell_date] || "", amount: amt });
    }
  }
  for (const yy in yearlyMap) {
    const yv = yearlyMap[yy];
    const mcc = _kellyMaxConcurrentCapital(yv._trades);
    yv.peak_capital = mcc;
    yv.peak_return_pct = mcc > 0 ? Math.round(yv.profit / mcc * 100 * 10000) / 10000 : 0;
    delete yv._trades;
  }
  result.allYearly = yearlyMap;
  // 统计被过滤掉的基笔数(降亏+positionCap, 供重叠度分析)
  return result;
}

// 组合定义
const COMBO4 = {
  n2NovSpecialIndustry: true, n3NovSpecialMon: true, v4d: true,
  r8PureNonMay: true, greedy15: true,
  janMidRating: true, janMidSpecial: true
};
const POSCAP2 = { positionCap: true, positionCapK: 2 };
const SB = { excludeSpecialBear: true };
const A5 = { a5NovMidSpecial: true };
const A45 = { a45NovMidLateSpecial: true };
const DEFAULT_REC = Object.assign({}, POSCAP2, SB, A5, A45);

function mergeFilters() {
  const o = {};
  for (const a of arguments) Object.assign(o, a);
  return o;
}

const configs = {
  base_none: mergeFilters(),                                   // 全关(无降亏无poscap)
  base_poscap: mergeFilters(POSCAP2),                          // 仅poscap
  C_defaultRec: mergeFilters(DEFAULT_REC),                     // 默认推荐组合
  A_combo4: mergeFilters(COMBO4),                              // 4宏全开(不含A45/poscap/sb/a5)
  A_combo4_poscap_sb: mergeFilters(COMBO4, POSCAP2, SB),       // 4宏全开+poscap+熊市(仍无A45/A5)
  A_combo4_poscap_sb_a5: mergeFilters(COMBO4, POSCAP2, SB, A5),// 4宏全开+poscap+熊市+A5(无A45)
  B_combo4_a45: mergeFilters(COMBO4, A45),                     // 4宏全开+A45(纯)
  B_combo4_poscap_sb_a45: mergeFilters(COMBO4, POSCAP2, SB, A45), // 4宏全开+poscap+熊市+A45(无A5)
  B_full: mergeFilters(COMBO4, POSCAP2, SB, A5, A45),          // 4宏全开+全部默认推荐(用户实际所见)
  D_defaultRec_combo4: mergeFilters(DEFAULT_REC, COMBO4),      // 默认推荐+4宏全开(等价于B_full)
  E_combo4_only_A5: mergeFilters(COMBO4, A5),                  // 4宏全开+A5(对比A45边际)
  F_poscap_sb_a5: mergeFilters(POSCAP2, SB, A5),               // 默认推荐除A45(对照C看A45在推荐内的边际)
};

const out = { generated_at: new Date().toISOString(), config: { periods: periods, cutoffs: cutoffs, sell_modes: sellModes, buy_amount: buyAmount }, runs: {} };
for (const ck in configs) {
  out.runs[ck] = run(configs[ck], "pool");
}
fs.writeFileSync("/tmp/kelly-4combo-a45-backtest.json", JSON.stringify(out, null, 1));
console.log("DONE runs:", Object.keys(configs).length);

// ===== 验证段: 对齐 positionCap tip 锚点(G模式) =====
const VALID = {
  V_nopos_A45_A5_SB: mergeFilters(SB, A5, A45),                    // 关poscap(默认降亏) -> tip 38.28%/171.7万
  V_poscap1_A45_A5_SB: mergeFilters(POSCAP2, SB, A5, A45, { positionCapK: 1 }), // K=1 -> 48.88%/78.7万/161万
  V_poscap2_A45_SB: mergeFilters(POSCAP2, SB, A45),                // K=2 无A5
  V_poscap2_A45: mergeFilters(POSCAP2, A45),                       // K=2 仅A45
  V_poscap2_only: mergeFilters(POSCAP2),                           // K=2 无降亏
};
for (const ck in VALID) out.runs[ck] = run(VALID[ck], "pool");
fs.writeFileSync("/tmp/kelly-4combo-a45-backtest.json", JSON.stringify(out, null, 1));
console.log("VALID done");

// ===== 拓展: 默认推荐上逐个/组合加 combo, 找最优 G 配置 =====
const YE = { n2NovSpecialIndustry: true, n3NovSpecialMon: true, v4d: true };
const SC = { r8PureNonMay: true };
const MLC = { greedy15: true };
const JA = { janMidRating: true, janMidSpecial: true };
const N2 = { n2NovSpecialIndustry: true };
const N3 = { n3NovSpecialMon: true };
const EXT = {
  T_def_ye: mergeFilters(DEFAULT_REC, YE),
  T_def_sc: mergeFilters(DEFAULT_REC, SC),
  T_def_mlc: mergeFilters(DEFAULT_REC, MLC),
  T_def_ja: mergeFilters(DEFAULT_REC, JA),
  T_def_n2: mergeFilters(DEFAULT_REC, N2),
  T_def_n3: mergeFilters(DEFAULT_REC, N3),
  T_def_combo4_nogreedy: mergeFilters(DEFAULT_REC, YE, SC, JA),   // 4宏除greedy15
  T_def_ye_mlc: mergeFilters(DEFAULT_REC, YE, MLC),              // 年末+最大化
  T_combo4_ye_sc_mlc: mergeFilters(DEFAULT_REC, YE, SC, MLC),    // 默认+年末+稳健+最大化(无1月)
};
for (const ck in EXT) out.runs[ck] = run(EXT[ck], "pool");
fs.writeFileSync("/tmp/kelly-4combo-a45-backtest.json", JSON.stringify(out, null, 1));
console.log("EXT done");
