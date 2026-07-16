// === 策略实验室 tab：22策略多周期回测矩阵 + BB_upper_revert 实验图表 ===
// 纯前端 JS 实时算，不碰后端 signals.py / signal_daily。
// BB: mid=MA20(close), sd=std(close,ddof=0), bu=mid+2σ, bl=mid-2σ（与 _bollinger() 一致）
// 触发: close[i-1] > bu[i-1] && close[i] < bu[i]（参考 a-stock-data/backtest_strategies.py:193）
function computeBBLab(ohlc) {
  const N = 20, K = 2.0;
  const closes = ohlc.map((d) => d.close);
  const bu = [], bl = [], mid = [];
  for (let i = 0; i < ohlc.length; i++) {
    if (i < N - 1) { bu.push(null); bl.push(null); mid.push(null); continue; }
    const slice = closes.slice(i - N + 1, i + 1);
    const m = slice.reduce((a, b) => a + b, 0) / N;
    const variance = slice.reduce((a, b) => a + (b - m) * (b - m), 0) / N; // ddof=0
    const sd = Math.sqrt(variance);
    mid.push(m); bu.push(m + K * sd); bl.push(m - K * sd);
  }
  const signals = [];
  for (let i = 1; i < ohlc.length; i++) {
    if (bu[i - 1] == null || bu[i] == null) continue;
    if (closes[i - 1] > bu[i - 1] && closes[i] < bu[i]) {
      signals.push({ date: ohlc[i].date, close: closes[i] });
    }
  }
  return { bu, bl, mid, signals };
}

// BB_lower_revert：布林下轨回归辅买信号（复用 computeBBLab 的 BB 带，信号逻辑镜像 BB_upper_revert）
// 触发: 前日 close < bl[i-1]（跌破下轨）且 当日 close > bl[i]（收回下轨之上）
function computeBBLowerRevertLab(ohlc) {
  const bb = computeBBLab(ohlc); // {bu, bl, mid, signals(上轨回落，忽略)}
  const closes = ohlc.map((d) => d.close);
  const signals = [];
  for (let i = 1; i < ohlc.length; i++) {
    if (bb.bl[i - 1] == null || bb.bl[i] == null) continue;
    if (closes[i - 1] < bb.bl[i - 1] && closes[i] > bb.bl[i]) {
      signals.push({ date: ohlc[i].date, close: closes[i] });
    }
  }
  return { bu: bb.bu, bl: bb.bl, mid: bb.mid, signals };
}

// Supertrend(10,3) 翻多买：ATR(10) Wilder平滑 × 3 乘数的动态趋势线
// 趋势线=多头下轨(绿)/空头上轨(红)；翻多信号=前日空头、当日多头
function computeSupertrendLab(ohlc) {
  const N = 10, K = 3.0, len = ohlc.length;
  // True Range
  const tr = new Array(len).fill(0);
  for (let i = 0; i < len; i++) {
    if (i === 0) { tr[i] = ohlc[i].high - ohlc[i].low; continue; }
    const pc = ohlc[i - 1].close;
    tr[i] = Math.max(ohlc[i].high - ohlc[i].low, Math.abs(ohlc[i].high - pc), Math.abs(ohlc[i].low - pc));
  }
  // ATR(Wilder RMA)：前 N 个用 SMA 作种子，之后 (prev*(N-1)+tr)/N
  const atr = new Array(len).fill(null);
  if (len >= N) {
    let sum = 0;
    for (let i = 0; i < N; i++) sum += tr[i];
    atr[N - 1] = sum / N;
    for (let i = N; i < len; i++) atr[i] = (atr[i - 1] * (N - 1) + tr[i]) / N;
  }
  // basic/final bands + supertrend + direction
  const fUp = new Array(len).fill(null);
  const fLo = new Array(len).fill(null);
  const st = new Array(len).fill(null);
  const dir = new Array(len).fill(0); // 1=多头, -1=空头
  for (let i = 0; i < len; i++) {
    if (atr[i] == null) continue;
    const hl2 = (ohlc[i].high + ohlc[i].low) / 2;
    const bUp = hl2 + K * atr[i];
    const bLo = hl2 - K * atr[i];
    if (fUp[i - 1] == null) { // 首个有效 bar，默认多头
      fUp[i] = bUp; fLo[i] = bLo; dir[i] = 1; st[i] = fLo[i]; continue;
    }
    fUp[i] = (bUp < fUp[i - 1] || ohlc[i - 1].close > fUp[i - 1]) ? bUp : fUp[i - 1];
    fLo[i] = (bLo > fLo[i - 1] || ohlc[i - 1].close < fLo[i - 1]) ? bLo : fLo[i - 1];
    if (dir[i - 1] === -1) { // 前日空头
      if (ohlc[i].close > fUp[i]) { dir[i] = 1; st[i] = fLo[i]; }   // 翻多
      else { dir[i] = -1; st[i] = fUp[i]; }                          // 维持空头
    } else { // 前日多头
      if (ohlc[i].close < fLo[i]) { dir[i] = -1; st[i] = fUp[i]; }  // 翻空
      else { dir[i] = 1; st[i] = fLo[i]; }                           // 维持多头
    }
  }
  // 翻多信号
  const signals = [];
  for (let i = 1; i < len; i++) {
    if (!dir[i] || !dir[i - 1]) continue;
    if (dir[i - 1] === -1 && dir[i] === 1) signals.push({ date: ohlc[i].date, close: ohlc[i].close });
  }
  // 拆分多头(绿)/空头(红)线段，翻转点双重赋值以视觉连接
  const stBull = new Array(len).fill(null);
  const stBear = new Array(len).fill(null);
  for (let i = 0; i < len; i++) {
    if (st[i] == null) continue;
    if (dir[i] === 1) stBull[i] = st[i]; else stBear[i] = st[i];
    if (i > 0 && dir[i] && dir[i - 1] && dir[i] !== dir[i - 1]) {
      if (dir[i - 1] === -1) stBear[i] = st[i]; else stBull[i] = st[i];
    }
  }
  return { st, stBull, stBear, dir, signals };
}

// MA5/MA20 死叉卖：MA5 前日>=MA20 且 当日<MA20（5日下穿20日）
function computeMADeathCrossLab(ohlc) {
  const S = 5, L = 20;
  const closes = ohlc.map((d) => d.close);
  const ma5 = new Array(closes.length).fill(null);
  const ma20 = new Array(closes.length).fill(null);
  for (let i = 0; i < closes.length; i++) {
    if (i >= S - 1) {
      let s = 0; for (let j = i - S + 1; j <= i; j++) s += closes[j];
      ma5[i] = s / S;
    }
    if (i >= L - 1) {
      let s = 0; for (let j = i - L + 1; j <= i; j++) s += closes[j];
      ma20[i] = s / L;
    }
  }
  const signals = [];
  for (let i = 1; i < closes.length; i++) {
    if (ma5[i - 1] == null || ma20[i - 1] == null || ma5[i] == null || ma20[i] == null) continue;
    if (ma5[i - 1] >= ma20[i - 1] && ma5[i] < ma20[i]) {
      signals.push({ date: ohlc[i].date, close: closes[i] });
    }
  }
  return { ma5, ma20, signals };
}

// === 通用指标计算辅助（复刻 a-stock-data/backtest_strategies.py 指标定义）===
// 信号逻辑严格对齐 backtest_strategies.gen_buy_signals / gen_sell_signals，
// 使图表信号点与回测矩阵统计同源。

// EWM (exponentially weighted mean), adjust=False, seed=首个非null值
// 复刻 pandas Series.ewm(alpha, adjust=False).mean()
function _ewmLab(values, alpha) {
  const n = values.length;
  const out = new Array(n).fill(null);
  let started = false, prev = 0;
  for (let i = 0; i < n; i++) {
    const v = values[i];
    if (v == null || (typeof v === "number" && isNaN(v))) continue;
    if (!started) { prev = v; started = true; out[i] = v; }
    else { prev = (1 - alpha) * prev + alpha * v; out[i] = prev; }
  }
  return out;
}
// 简单移动平均（min_periods=n，前 n-1 个为 null）
function _smaLab(values, n) {
  const out = new Array(values.length).fill(null);
  for (let i = n - 1; i < values.length; i++) {
    let s = 0; for (let j = i - n + 1; j <= i; j++) s += values[j];
    out[i] = s / n;
  }
  return out;
}
// RSI(14)：EWM α=1/14, adjust=False（复刻 backtest_strategies.rsi）
function computeRSILab(ohlc, period) {
  period = period || 14;
  const closes = ohlc.map((d) => d.close);
  const n = closes.length;
  const delta = new Array(n).fill(null);
  for (let i = 1; i < n; i++) delta[i] = closes[i] - closes[i - 1];
  const gain = delta.map((d) => (d == null ? null : d > 0 ? d : 0));
  const loss = delta.map((d) => (d == null ? null : d < 0 ? -d : 0));
  const avgGain = _ewmLab(gain, 1 / period);
  const avgLoss = _ewmLab(loss, 1 / period);
  const rsi = new Array(n).fill(null);
  for (let i = 0; i < n; i++) {
    if (avgGain[i] == null || avgLoss[i] == null) continue;
    if (avgLoss[i] === 0) rsi[i] = 100;
    else rsi[i] = 100 - 100 / (1 + avgGain[i] / avgLoss[i]);
  }
  return rsi;
}
// Donchian 通道：upper=前 n 日最高(不含当日), lower=前 n 日最低(不含当日)
// 复刻 backtest_strategies: du20 = high.rolling(20).max().shift(1)
function computeDonchianLab(ohlc, n) {
  const highs = ohlc.map((d) => d.high);
  const lows = ohlc.map((d) => d.low);
  const len = ohlc.length;
  const upper = new Array(len).fill(null);
  const lower = new Array(len).fill(null);
  for (let i = n; i < len; i++) {
    let mx = -Infinity, mn = Infinity;
    for (let j = i - n; j <= i - 1; j++) {
      if (highs[j] > mx) mx = highs[j];
      if (lows[j] < mn) mn = lows[j];
    }
    upper[i] = mx; lower[i] = mn;
  }
  return { upper, lower };
}
// MACD(12,26,9)：DIF=EMA12-EMA26, DEA=EMA(DIF,9)
function computeMACDLab(ohlc) {
  const closes = ohlc.map((d) => d.close);
  const ef = _ewmLab(closes, 2 / 13);
  const es = _ewmLab(closes, 2 / 27);
  const dif = closes.map((_, i) => (ef[i] == null || es[i] == null ? null : ef[i] - es[i]));
  const dea = _ewmLab(dif, 2 / 10);
  return { dif, dea };
}
// KDJ(9)：RSV=(close-low_n)/(high_n-low_n)*100, K=EMA(RSV,3), D=EMA(K,3)
function computeKDJLab(ohlc, n) {
  n = n || 9;
  const highs = ohlc.map((d) => d.high);
  const lows = ohlc.map((d) => d.low);
  const closes = ohlc.map((d) => d.close);
  const len = ohlc.length;
  const rsv = new Array(len).fill(null);
  for (let i = n - 1; i < len; i++) {
    let mn = Infinity, mx = -Infinity;
    for (let j = i - n + 1; j <= i; j++) {
      if (lows[j] < mn) mn = lows[j];
      if (highs[j] > mx) mx = highs[j];
    }
    rsv[i] = mx === mn ? 0 : (closes[i] - mn) / (mx - mn) * 100;
  }
  const k = _ewmLab(rsv, 1 / 3);
  const d = _ewmLab(k, 1 / 3);
  return { k, d };
}
// ATR(14) 追踪止损：trail = 近20日最高close - 3×ATR(14)
// 复刻 backtest_strategies: close < hc20 - 3*atr 且 前日未破
function computeATRTrailLab(ohlc) {
  const closes = ohlc.map((d) => d.close);
  const len = ohlc.length;
  const tr = new Array(len).fill(null);
  if (len) tr[0] = ohlc[0].high - ohlc[0].low;
  for (let i = 1; i < len; i++) {
    tr[i] = Math.max(ohlc[i].high - ohlc[i].low, Math.abs(ohlc[i].high - closes[i - 1]), Math.abs(ohlc[i].low - closes[i - 1]));
  }
  const atr = _ewmLab(tr, 1 / 14);
  const hc20 = new Array(len).fill(null);
  for (let i = 19; i < len; i++) {
    let mx = -Infinity;
    for (let j = i - 19; j <= i; j++) if (closes[j] > mx) mx = closes[j];
    hc20[i] = mx;
  }
  const trail = new Array(len).fill(null);
  for (let i = 0; i < len; i++) if (hc20[i] != null && atr[i] != null) trail[i] = hc20[i] - 3 * atr[i];
  const signals = [];
  for (let i = 1; i < len; i++) {
    if (trail[i] == null || trail[i - 1] == null) continue;
    if (closes[i] < trail[i] && closes[i - 1] >= trail[i - 1]) signals.push({ date: ohlc[i].date, close: closes[i] });
  }
  return { trail, signals };
}
// D1：20日最高high回落5%阈值线 + 信号
// 复刻 backtest_strategies: th = hh20*0.95, close前日>=th且当日<th
function computeD1Lab(ohlc) {
  const closes = ohlc.map((d) => d.close);
  const highs = ohlc.map((d) => d.high);
  const len = ohlc.length;
  const hh20 = new Array(len).fill(null);
  for (let i = 19; i < len; i++) {
    let mx = -Infinity;
    for (let j = i - 19; j <= i; j++) if (highs[j] > mx) mx = highs[j];
    hh20[i] = mx;
  }
  const th = hh20.map((v) => (v == null ? null : v * 0.95));
  const signals = [];
  for (let i = 1; i < len; i++) {
    if (th[i] == null || th[i - 1] == null) continue;
    if (closes[i - 1] >= th[i - 1] && closes[i] < th[i]) signals.push({ date: ohlc[i].date, close: closes[i] });
  }
  return { th, signals };
}

// Vol_breakout：放量突破买（成交额代理成交量）
// 触发: amount > 2×20日均额 且 close 涨幅>2%（复刻 backtest_strategies.Vol_breakout: vol>2*vma & pct>0.02）
// 指数无 volume 字段，用 amount(成交额) 代理；A 股宽基 amount 为空时量比为 null、不出信号
function computeVolBreakoutLab(ohlc) {
  const N = 20;
  const len = ohlc.length;
  const amounts = ohlc.map((d) => d.amount);
  const closes = ohlc.map((d) => d.close);
  // 20日均额（min_periods=10，跳过 null/NaN/0 的 amount）
  const vma = new Array(len).fill(null);
  for (let i = N - 1; i < len; i++) {
    let sum = 0, cnt = 0;
    for (let j = i - N + 1; j <= i; j++) {
      const a = amounts[j];
      if (a != null && !isNaN(a) && a > 0) { sum += a; cnt++; }
    }
    if (cnt >= 10) vma[i] = sum / cnt;
  }
  // 量比 = amount / vma（>2 放量，<1 缩量）
  const vratio = new Array(len).fill(null);
  for (let i = 0; i < len; i++) {
    const a = amounts[i];
    if (a != null && !isNaN(a) && vma[i] != null && vma[i] > 0) vratio[i] = a / vma[i];
  }
  // 信号：量比 > 2 且 close 涨幅 > 2%
  const signals = [];
  for (let i = 1; i < len; i++) {
    if (vratio[i] == null) continue;
    const pct = closes[i - 1] > 0 ? closes[i] / closes[i - 1] - 1 : 0;
    if (vratio[i] > 2.0 && pct > 0.02) signals.push({ date: ohlc[i].date, close: closes[i] });
  }
  return { vratio, signals };
}

// 通用实验图表：收盘价折线 + 自定义指标线 + 信号 markPoint
// indicators: [{name, data, color, dash}]  data 与 ohlc 等长（null=无值）
// signalLabel 用策略中文名，label 以彩色标签框显示在 pin 上方，hideOverlap 防密集重叠
function renderLabChartEx(title, ohlc, indicators, signals, container, chartArr, signalLabel, signalColor) {
  const c = mkCard(title, 400, null, container, chartArr);
  const dates = ohlc.map((d) => d.date);
  const lblColor = signalColor || "#9c27b0";
  // 每个信号可自带 color/label（买卖合一展示时买红卖绿），未带则回退全局 signalLabel/signalColor
  const markData = signals.map((s) => {
    const c0 = s.color || lblColor;
    const lbl0 = s.label || signalLabel || "信号";
    return {
      coord: [s.date, s.close],
      value: lbl0,
      itemStyle: { color: c0 },
      label: { backgroundColor: c0 },
    };
  });
  const legendData = ["收盘价"].concat(indicators.map((it) => it.name));
  // 含副图指标（RSI/MACD/KDJ，axis:'osc'）时启用双 y 轴：左轴价格、右轴指标(0-100量级)
  const hasOsc = indicators.some((it) => it.axis === "osc");
  const yAxis = [{ type: "value", scale: true, name: hasOsc ? "价格" : "" }];
  if (hasOsc) yAxis.push({ type: "value", scale: true, name: "指标", splitLine: { show: false }, axisLabel: { fontSize: 9 } });
  const indSeries = indicators.map((it) => ({
    name: it.name, type: "line", symbol: "none", data: it.data, smooth: true,
    lineStyle: { width: 1, type: it.dash ? "dashed" : "solid", color: it.color || cssVar('--text-4') },
    connectNulls: false,
    yAxisIndex: it.axis === "osc" ? 1 : 0,
  }));
  c.setOption({
    tooltip: { trigger: "axis" },
    legend: { top: 0, data: legendData },
    grid: { left: 55, right: hasOsc ? 55 : 20, top: 35, bottom: 50 },
    xAxis: { type: "category", data: dates },
    yAxis,
    dataZoom: dzOpts(),
    series: [
      {
        name: "收盘价", type: "line", smooth: true, symbol: "none",
        data: ohlc.map((d) => d.close), lineStyle: { width: 1.5 },
        markPoint: {
          symbol: "pin", symbolSize: 30,
          label: {
            fontSize: 9, color: "#fff",
            position: "top", distance: 2,
            backgroundColor: lblColor,
            padding: [2, 5], borderRadius: 10, borderWidth: 0,
          },
          data: markData,
        },
        labelLayout: { hideOverlap: true },
      },
      ...indSeries,
    ],
  });
  return c;
}

// BB_upper_revert 兼容封装
function renderLabChart(title, ohlc, bb, signals, container, chartArr) {
  return renderLabChartEx(title, ohlc, [
    { name: "布林上轨", data: bb.bu, color: cssVar('--text-4'), dash: true },
    { name: "布林下轨", data: bb.bl, color: cssVar('--text-4'), dash: true },
  ], signals, container, chartArr, "布林上轨回落卖", "#9c27b0");
}

// === 22策略元数据注册表（分区/状态/触发/结论/理论/场景/注意/回测报告结论）===
// 文案来源：买卖点策略深度回测.md（重跑于 2026-07-11，244资产全史/近10年/近5年/近3年/近1年 × 5d/10d/20d/60d）
// zone: buy=候选买点 / sell=候选卖点 / excluded=已排除 / prod=生产参考
// status: live=已上线生产 / experimental=实验中 / dev=开发中 / excluded=已排除
const LAB_STRATEGIES = {
  // --- 候选买点区（7个） ---
  BB_lower_revert: {
    name: "布林下轨回归买", side: "buy", zone: "buy", status: "experimental",
    trigger: "前一日收盘价跌破布林带下轨，当日收盘价收回下轨之上（超卖反弹）",
    conclusion: "3/4窗口达标并列第1，近3年60d盈亏比1.84最高，与C1语义互补",
    theory: "布林带下轨回归。价格跌破下轨后收回，意味超卖极端已过、反弹拐点出现。与C1同为「超卖反弹」语义，但用价格穿越布林带下轨而非相对强弱指标(RSI)阈值，强势市更敏感。",
    scenario: "震荡市/下跌市超卖反弹；强势市中相对强弱指标未到30但价格已破下轨时补C1盲区。",
    note: "近1年是唯一达标买点（52.1%/1.23），与C1互补性最强。实验中：已实现图表（收盘价+布林带轨道+绿色实验买标注），未写入signal_daily。",
    report: "回测报告：布林下轨回归买达标数3/4（近10年/近3年/近1年），与C1并列第1。近3年60d盈亏比1.79、均值+4.7%为买点最高。近1年（强势单边市）是唯一达标买点，补强C1在强势市的盲区。语义与C1正交（价格穿越 vs 相对强弱阈值），适合做互补买点。",
  },
  Supertrend_buy: {
    name: "Supertrend翻多买", side: "buy", zone: "buy", status: "experimental",
    trigger: "真实波幅ATR(10)×3 趋势线从翻空转为翻多（趋势跟踪买点）",
    conclusion: "2/4达标，语义与C1正交（趋势启动 vs 超卖反弹），最佳互补候选",
    theory: "超级趋势(Supertrend)指标基于真实波幅(ATR)的动态趋势线。翻多意味趋势已确认启动，与C1的「超卖反弹」正交，捕捉的是趋势延续而非拐点。",
    scenario: "趋势启动确认；与C1互补覆盖不同市场状态。",
    note: "近3年全持有期胜率≥48.8%，盈亏比1.40-1.61。信号较C1稀疏。实验中：已实现图表（收盘价+超级趋势线+绿色实验买标注），未写入signal_daily。",
    report: "回测报告：Supertrend翻多买全史达标（51.4%/1.21），近3年20d/60d胜率≥49.7%盈亏比≥1.45。语义与C1正交（趋势启动 vs 超卖反弹），是最佳互补候选。近3年10d均值+1.0%，60d均值+3.8%。",
  },
  Donchian20_up: {
    name: "唐奇安20日突破买", side: "buy", zone: "buy", status: "experimental",
    trigger: "收盘价突破近20日最高价（通道突破买）",
    conclusion: "2/4达标，近3年胜率<50%，趋势跟踪型信号",
    theory: "唐奇安通道突破。价格创新高意味多头力量突破，经典趋势跟踪系统。",
    scenario: "强趋势市突破入场；震荡市假信号多。",
    note: "近3年10d胜率47.7%低于50%，但近1年51.0%转正。60d盈亏比1.56较高。",
    report: "回测报告：唐奇安20日突破买全史+近1年达标（2/4），近3年胜率47.7%低于50%。全史样本38731最大之一，但胜率平庸。近3年60d盈亏比1.56、均值+2.3%。",
  },
  Donchian55_up: {
    name: "海龟55日突破买", side: "buy", zone: "buy", status: "experimental",
    trigger: "收盘价突破近55日最高价（海龟交易法System 2）",
    conclusion: "2/4达标，胜率<50%，长周期突破信号滞后",
    theory: "海龟交易法 System 2 入场。55日突破捕捉中长期趋势启动，经典趋势跟踪。",
    scenario: "中长期趋势确认入场；短周期信号滞后。",
    note: "近3年胜率47.1%，但近1年51.0%。60d盈亏比1.45。",
    report: "回测报告：海龟55日突破买全史+近1年达标（2/4），近3年胜率47.1%低于50%。全史样本20895，60d均值+3.4%。海龟系统长周期突破信号滞后但盈亏比尚可。",
  },
  MA_golden_5_20: {
    name: "MA5/MA20金叉买", side: "buy", zone: "buy", status: "experimental",
    trigger: "5日均线上穿20日均线（短期金叉买点）",
    conclusion: "1/4达标，信号密集胜率平庸",
    theory: "双均线金叉。短期均线上穿长期均线意味短期动量转强，经典趋势确认信号。",
    scenario: "趋势确认入场；震荡市频繁假金叉。",
    note: "信号最多（全史30754），但近3年胜率49.8%接近随机。60d盈亏比1.75较高。",
    report: "回测报告：MA5/MA20金叉买仅全史达标（1/4），近3年10d胜率49.8%接近随机。信号密集（全史30754个），胜率平庸。近3年60d盈亏比1.75、均值+4.9%是唯一亮点。",
  },
  MA_golden_10_60: {
    name: "MA10/MA60金叉买", side: "buy", zone: "buy", status: "experimental",
    trigger: "10日均线上穿60日均线（中长期金叉买点）",
    conclusion: "2/4达标，滞后严重",
    theory: "中长期双均线金叉。10日均线上穿60日均线确认中长期趋势转多，但60日均线滞后严重。",
    scenario: "中长期趋势确认；信号滞后，入场点偏晚。",
    note: "近3年胜率47.1%低于50%。全史样本11809较少。",
    report: "回测报告：MA10/MA60金叉买全史+近1年达标（2/4），近3年胜率47.1%低于50%。60日均线滞后严重，信号少且入场偏晚。全史60d均值+2.1%。",
  },
  MACD_golden: {
    name: "MACD金叉买", side: "buy", zone: "buy", status: "experimental",
    trigger: "差离值(DIF)上穿信号线(DEA)（MACD金叉买点）",
    conclusion: "1/4达标，信号最多但平庸",
    theory: "MACD金叉。差离值(DIF)上穿信号线(DEA)意味短期动量强于长期，经典趋势确认。MACD(12,26,9)业界标准参数。",
    scenario: "趋势确认入场；震荡市假金叉多。",
    note: "信号全史最多（38930），但近3年胜率49.1%接近随机。",
    report: "回测报告：MACD金叉买仅全史达标（1/4），近3年10d胜率49.1%接近随机。信号全史最多（38930个），但胜率平庸。近3年60d盈亏比1.76、均值+4.6%。",
  },
  // --- 候选卖点区（7个） ---
  BB_upper_revert: {
    name: "布林上轨回落卖", side: "sell", zone: "sell", status: "experimental",
    trigger: "前一日收盘价突破布林带上轨，当日收盘价回落至上轨下方（短周期止盈）",
    conclusion: "近3年5d/10d胜率第1(57%/54%)，与D1(20d最强)时间维度互补",
    theory: "布林带上轨回归。价格从上轨上方回落至下方，意味超买极端已过、短周期止盈拐点。与D1的「20日高回落5%」时间维度互补。",
    scenario: "短周期止盈/减仓提示；与D1（20d最强）双重确认。",
    note: "实验中，已实现图表（收盘价折线+布林带轨道+紫色实验卖标注）。未写入signal_daily。",
    report: "回测报告：布林上轨回落卖近3年5d胜率56.8%/10d胜率54.1%为卖点最高，短周期止盈最强。但样本仅5549（D1一半），20d后衰减。适合做D1的短周期互补（候选C）。全史PL0.87<1（卖点结构性问题），但方向胜率top1。",
  },
  MA_death_5_20: {
    name: "MA5/MA20死叉卖", side: "sell", zone: "sell", status: "experimental",
    trigger: "5日均线下穿20日均线（短期死叉卖点）",
    conclusion: "近3年20d胜率56.3%最高，短周期偏弱但中周期强",
    theory: "双均线死叉。短期均线下穿长期均线意味短期动量转弱，经典趋势转弱确认。",
    scenario: "趋势转弱减仓；震荡市频繁假死叉。",
    note: "近3年20d胜率54.8%较高，但5d/10d偏弱。PL0.90<1。实验中：已实现图表（收盘价+5日/20日均线+紫色实验卖标注），未写入signal_daily。",
    report: "回测报告：MA5/MA20死叉卖近3年20d胜率54.8%为卖点较高，10d胜率53.2%。均值-0.1%（方向正确）。但5d/10d偏弱，PL0.90<1（卖点结构性问题）。",
  },
  BB_middle_break: {
    name: "跌破布林中轨卖", side: "sell", zone: "sell", status: "experimental",
    trigger: "收盘价跌破布林中轨（20日均线），中轨破位卖",
    conclusion: "中规中矩，PL偏低",
    theory: "布林中轨破位。中轨=20日均线，跌破意味价格回到均线下方，趋势转弱确认。",
    scenario: "趋势转弱确认减仓；信号密集。",
    note: "近3年10d胜率52.6%，PL0.82偏低。样本最大（10177）。",
    report: "回测报告：跌破布林中轨卖近3年10d胜率52.6%、PL0.82。样本10177最大。中规中矩，无突出优势。",
  },
  Donchian10_down: {
    name: "跌破10日最低卖", side: "sell", zone: "sell", status: "experimental",
    trigger: "收盘价跌破近10日最低价（海龟退出信号）",
    conclusion: "胜率刚过50%",
    theory: "唐奇安通道下破/海龟退出。跌破短期低点意味短期趋势已破，海龟System 2退出信号。",
    scenario: "短期趋势破位退出；信号密集。",
    note: "近3年10d胜率52.4%，PL0.89。样本10731较大。",
    report: "回测报告：跌破10日最低卖近3年10d胜率52.4%、PL0.89。胜率刚过50%，无突出优势。样本10731较大。",
  },
  Donchian20_down: {
    name: "跌破20日最低卖", side: "sell", zone: "sell", status: "experimental",
    trigger: "收盘价跌破近20日最低价（通道下破卖）",
    conclusion: "PL相对高但平庸",
    theory: "唐奇安通道下破。跌破20日低点意味中期趋势已破，比10日更滞后但更可靠。",
    scenario: "中期趋势破位减仓；信号较稀疏。",
    note: "近3年10d胜率51.8%、PL0.88。全史PL0.94相对高。",
    report: "回测报告：跌破20日最低卖近3年10d胜率51.8%、PL0.88。全史PL0.94为卖点相对高，但整体平庸。样本7533。",
  },
  MACD_death: {
    name: "MACD死叉卖", side: "sell", zone: "sell", status: "experimental",
    trigger: "差离值(DIF)下穿信号线(DEA)（MACD死叉卖点）",
    conclusion: "PL0.79偏低",
    theory: "MACD死叉。差离值(DIF)下穿信号线(DEA)意味短期动量弱于长期，经典趋势转弱确认。MACD(12,26,9)业界标准。",
    scenario: "趋势转弱减仓；震荡市假死叉多。",
    note: "近3年10d胜率51.8%，PL0.83偏低。样本6844较大。",
    report: "回测报告：MACD死叉卖近3年10d胜率51.8%、PL0.83偏低。样本6844。信号密集但PL偏低，卖点结构性问题突出。",
  },
  ATR_trail_stop: {
    name: "ATR追踪止损卖", side: "sell", zone: "sell", status: "experimental",
    trigger: "收盘价 < 近20日最高收盘价 − 3×真实波幅ATR(14)（追踪止损）",
    conclusion: "胜率刚过50%",
    theory: "真实波幅(ATR)追踪止损。基于波动率的动态止损线，价格跌破意味趋势已反转。真实波幅(ATR)自适应波动率。",
    scenario: "趋势跟踪止损；波动率大时止损线更宽。",
    note: "近3年10d胜率51.1%，PL0.86。全史PL0.96相对高。",
    report: "回测报告：ATR追踪止损卖近3年10d胜率51.1%、PL0.86。全史PL0.96为卖点最高之一。追踪止损型信号，胜率刚过50%。",
  },
  // --- 已排除反面教材区（6个） ---
  BB_upper_break: {
    name: "突破布林上轨买", side: "buy", zone: "excluded", status: "excluded",
    trigger: "收盘价突破布林上轨（追高买）",
    conclusion: "0/4达标，追高被套，胜率长期<50%",
    theory: "布林上轨突破。价格突破上轨意味强势，但A股追高易被套。",
    scenario: "不推荐使用。",
    note: "已排除。近3年10d胜率45.5%，全史48.8%均<50%。",
    report: "回测报告：突破布林上轨买 0/4达标，全史+近3年+近1年胜率均<50%（48.8%/45.5%/48.4%）。追高被套，明确排除。",
  },
  KDJ_golden_oversold: {
    name: "KDJ超卖金叉买", side: "buy", zone: "excluded", status: "excluded",
    trigger: "随机指标(KDJ)金叉且 K<35（超卖金叉买）",
    conclusion: "0/4达标，近3年10d胜率46.1%",
    theory: "随机指标(KDJ)超卖金叉。随机指标(KDJ)在超卖区金叉意味短期反弹，但A股随机指标(KDJ)信号噪声大。",
    scenario: "不推荐使用。",
    note: "已排除。近3年10d胜率45.5%<50%。",
    report: "回测报告：KDJ超卖金叉买 0/4达标，近3年10d胜率45.5%<50%。信号密集（6839）但胜率低，明确排除。",
  },
  Vol_breakout: {
    name: "放量突破买", side: "buy", zone: "excluded", status: "excluded",
    trigger: "成交量 > 2×20日均量 且 当日收盘价涨幅>2%（放量突破）",
    conclusion: "0/4达标，近3年胜率42.6%反向指标",
    theory: "放量突破。量价齐升意味资金入场，但A股个股放量突破后常回调。",
    scenario: "不推荐使用。在A股个股上反而是反向指标。",
    note: "已排除。近3年10d胜率43.0%，全史44.8%均<50%。",
    report: "回测报告：放量突破买 0/4达标，近3年10d胜率43.0%为所有策略最低。放量突破在A股个股上反而是反向指标（追高被套），明确排除。",
  },
  B0_RSI70: {
    name: "RSI下穿70卖", side: "sell", zone: "excluded", status: "excluded",
    trigger: "RSI(14) 前日≥70 且 当日<70（超买结束卖）",
    conclusion: "PL0.81最差，旧基线已弃",
    theory: "相对强弱指标(RSI)超买结束。相对强弱指标(RSI)从≥70回落意味超买结束，但回测显示方向相反（信号后价格仍涨）。",
    scenario: "不推荐使用。已弃用，改用D1。",
    note: "已排除。全史PL0.84最差，旧基线。已被D1_high20_drop5替代。",
    report: "回测报告：RSI下穿70卖 0/4达标，全史10d胜率48.7%/PL0.84/均值+0.9%（方向相反，信号后价格仍涨）。是所有卖点中最差的，旧基线已弃，改用D1。",
  },
  KDJ_death_overbought: {
    name: "KDJ超买死叉卖", side: "sell", zone: "excluded", status: "excluded",
    trigger: "随机指标(KDJ)死叉且 K>70（超买死叉卖）",
    conclusion: "近3年10d胜率46.3%失效",
    theory: "随机指标(KDJ)超买死叉。随机指标(KDJ)在超买区死叉意味短期转弱，但近年失效。",
    scenario: "不推荐使用。近年失效。",
    note: "已排除。近3年10d胜率47.8%<50%。",
    report: "回测报告：KDJ超买死叉卖 0/4达标，近3年10d胜率47.8%<50%。近年失效，明确排除。全史10d胜率45.4%也低。",
  },
  Supertrend_sell: {
    name: "Supertrend翻空卖", side: "sell", zone: "excluded", status: "excluded",
    trigger: "真实波幅ATR(10)×3 趋势线从翻多转为翻空（趋势跟踪卖）",
    conclusion: "全史唯一PL≥1但近3年48.9%失效",
    theory: "超级趋势(Supertrend)翻空。趋势线翻空意味趋势已反转，但近年A股向上漂移致失效。",
    scenario: "不推荐使用。近年失效。",
    note: "已排除。全史PL0.95（接近1），但近3年胜率48.9%<50%失效。",
    report: "回测报告：Supertrend翻空卖 全史唯一PL≥1（0.95接近1，胜率51.9%），但近3年10d胜率48.9%/PL0.85失效。近年A股向上漂移致趋势跟踪卖点失效，明确排除。",
  },
  // --- 生产参考区（2个） ---
  C1_RSI30: {
    name: "RSI上穿30买", side: "buy", zone: "prod", status: "live",
    trigger: "RSI(14) 从 ≤30 升回 >30 那天（超卖结束、价格有望反弹）",
    conclusion: "3/4达标，结构最稳健，当前主买点",
    theory: "相对强弱指标(RSI)经典超卖回归。相对强弱指标(RSI)≤30表示超卖，升回30之上意味空头力量衰竭、反弹拐点出现。事件化（仅穿越当日标）。",
    scenario: "震荡市/下跌市超卖反弹；通用主买点。按指数可收紧阈值至相对强弱指标上穿25（kc50/电力设备/传媒已配）。",
    note: "已上线生产。signal='buy'。近3年全持有期胜率>50%，盈亏比随持有期单调上升。",
    report: "回测报告：RSI上穿30买 达标数3/4（全史/近10年/近3年）并列第1。近3年全持有期胜率>50%（5d54.2%/10d52.6%/20d56.5%/60d55.0%），盈亏比随持有期单调上升（1.38->1.17->1.52->1.68），60d均值+5.3%。结构最稳健，当前主买点，无需改买点。",
  },
  D1_high20_drop5: {
    name: "20日高回落5%卖", side: "sell", zone: "prod", status: "live",
    trigger: "收盘价从近20日最高价回落 5%（前日≥阈 且 当日<阈），且收盘价>60日均线，且差离值<信号线",
    conclusion: "20d胜率55.7%样本最大，当前主卖点",
    theory: "基于最高价的回落止盈。从20日最高价回落5%意味趋势转弱，叠加60日均线多头过滤+MACD死叉确认。反应型信号（不预测顶部，反应已发生的弱势）。",
    scenario: "趋势转弱/止盈减仓提示；非做空/反向交易指令。胜率≈50%接近随机，不可作独立卖出指令。",
    note: "已上线生产。signal='sell'。卖点本质难预测（PL<1），D1是「最不坏」方案非「好」方案。",
    report: "回测报告：20日高回落5%卖 近3年20d胜率55.9%为卖点最高，样本9873最大（统计最稳）。10d均值-0.1%（方向正确）。盈亏比0.86<1（卖点结构性问题：A股向上漂移），但在所有卖点中PL仍属前列。维持现状合理，是「最不坏」方案。",
  },
};

// 4分区定义
const LAB_ZONES = [
  { key: "buy", label: "🧪 候选买点", count: 7, desc: "候选买点策略（含BB下轨/Supertrend实验中）" },
  { key: "sell", label: "🧪 候选卖点", count: 7, desc: "候选卖点策略（含BB上轨/MA死叉实验中）" },
  { key: "excluded", label: "📋 已排除", count: 6, desc: "反面教材（回测不达标已弃用）" },
  { key: "prod", label: "✅ 生产参考", count: 2, desc: "已上线生产策略" },
];

// 状态标签映射
const LAB_STATUS_TAGS = {
  live: { label: "已上线生产", cls: "lab-tag-live" },
  partial: { label: "部分上线", cls: "lab-tag-partial" },
  experimental: { label: "实验中", cls: "lab-tag-exp" },
  dev: { label: "开发中", cls: "lab-tag-dev" },
  excluded: { label: "已排除", cls: "lab-tag-excluded" },
  pending: { label: "待回测", cls: "lab-tag-pending" },
};

// === 融合信号注册表（多信号同日AND共振）===
// 字段与 LAB_STRATEGIES 对齐，新增 conditions 数组（组成条件列表）
const LAB_FUSION_STRATEGIES = {
  // --- 生产参考区（2个，主项目提取） ---
  F_D1_S1_MACD: {
    name: "D1回落5%+MA60多头+MACD死叉 融合卖", side: "sell", zone: "prod", status: "live",
    conditions: ["20日高回落5%", "MA60多头", "MACD死叉"],
    trigger: "同日AND：close从20日最高价回落5% 且 close>MA60 且 DIF<DEA",
    conclusion: "主项目生产卖点核心。降噪39%（卖点59830→36289），加MACD后凯利建议率18.3%→43.3%",
    theory: "多信号融合卖点。20日高回落5%捕捉趋势转弱，叠加MA60多头过滤（确保在上升趋势中止盈而非下跌中加空）和MACD死叉确认（动量转弱）。三条件同日AND，大幅降噪。",
    scenario: "上升趋势中回落止盈/减仓；三条件共振过滤假信号。非做空指令。",
    note: "主项目生产卖点核心。加MACD后降噪39%（卖点59830→36289），凯利建议率18.3%→43.3%。已上线signal_daily。",
    report: "回测：加MACD死叉后信号从59830降至36289（降噪39%），凯利建议率从18.3%升至43.3%，信号质量显著提升。主项目生产卖点D1_high20_drop5的融合形态。",
  },
  F_D1_S1: {
    name: "D1回落5%+MA60多头（豁免MACD） 融合卖", side: "sell", zone: "prod", status: "live",
    conditions: ["20日高回落5%", "MA60多头"],
    trigger: "同日AND：close从20日最高价回落5% 且 close>MA60（s.*情绪分序列豁免MACD，因加MACD后样本n=106→7不足）",
    conclusion: "主项目s.*情绪分变体。对比F_D1_S1_MACD可看MACD过滤的增益",
    theory: "D1回落5%+MA60多头双条件融合。豁免MACD条件，因s.*情绪分序列加MACD后样本从106降至7，不足统计。用于对比F_D1_S1_MACD可单独看MACD过滤的增益。",
    scenario: "s.*情绪分变体的融合卖点；与F_D1_S1_MACD对比MACD过滤增益。",
    note: "主项目s.*情绪分变体。加MACD后样本n=106→7不足，故豁免MACD。",
    report: "回测：s.*情绪分变体的基础形态（不含MACD）。对比F_D1_S1_MACD可看MACD过滤的增益效果。",
  },
  // --- 候选买点区（3个） ---
  F_B1_RSI40: {
    name: "BB下轨回归+RSI上穿40 融合买", side: "buy", zone: "candidate_buy", status: "partial",
    conditions: ["BB下轨回归", "RSI上穿40"],
    trigger: "同日AND：close从BB下轨下方回归上轨 且 RSI从≤40上穿>40",
    conclusion: "主项目10指数已配置 buy_aux rsi_cross_40。f -38.5%->+16.2%转正（家电/轻工回测），胜率44.8%->54.5%，盈亏比0.66->1.19",
    theory: "多信号融合买点。BB下轨回归捕捉超卖反弹拐点，叠加RSI上穿40确认动量转强。两条件同日AND，过滤单一BB下轨穿越的假信号。",
    scenario: "超卖反弹+动量确认共振入场；震荡市/下跌市效果好。",
    note: "已作为 buy_aux 辅买点（per-index 增强）上线于 10 个指数：中证1000/创业板指/家电/轻工/医药/公用事业/房地产/社会服务/传媒/通信。非全局融合信号生产实现（B1基线+RSI上穿40过滤，signals.py:312-314）.",
    report: "回测：加RSI上穿40后f从-38.5%转正至+16.2%（家电/轻工样本），胜率44.8%->54.5%，盈亏比0.66->1.19。已扩展至10指数配置。",
  },
  F_B1_rebound2pct: {
    name: "BB下轨回归+反弹2% 融合买", side: "buy", zone: "candidate_buy", status: "partial",
    conditions: ["BB下轨回归", "反弹2%"],
    trigger: "同日AND：close从BB下轨回归 且 close>下轨*1.02（过滤barely-crossed假信号/dead cat bounce）",
    conclusion: "主项目8指数已配置 buy_aux close_above_bl_2pct。f -21%->+20%转正（基础化工回测），5d/10d/20d三horizon一致，n=19<30样本警示",
    theory: "多信号融合买点。BB下轨回归捕捉超卖反弹，叠加反弹2%过滤（close>下轨*1.02），过滤barely-crossed假信号和dead cat bounce。",
    scenario: "超卖反弹确认入场；过滤假突破/死猫反弹。",
    note: "已作为 buy_aux 辅买点（per-index 增强）上线于 8 个指数：农林牧渔/基础化工/电子/纺织服饰/交通运输/机械设备/国防军工/计算机。非全局融合信号生产实现（B1基线+反弹2%过滤，signals.py:315-318）.",
    report: "回测：加反弹2%过滤后f从-21%转正至+20%（基础化工样本），5d/10d/20d三horizon一致。样本n=19<30偏小，需持续观察。已扩展至8指数配置。",
  },
  F_C1_MACD_golden: {
    name: "RSI上穿30+MACD金叉 融合买（实验性新组合）", side: "buy", zone: "candidate_buy", status: "experimental",
    conditions: ["RSI上穿30", "MACD金叉"],
    trigger: "同日AND：RSI从≤30上穿>30（超卖反弹） 且 DIF上穿DEA（动量确认）",
    conclusion: "实验性新组合。超卖反弹+动量确认共振，待回测验证",
    theory: "实验性新组合。RSI上穿30捕捉超卖反弹拐点，叠加MACD金叉确认动量转强。两条件同日AND共振。",
    scenario: "超卖反弹+动量确认共振入场；实验性，待回测验证。",
    note: "实验室新组合，非主项目提取。需阶段二回测验证是否有价值。",
    report: "实验性新组合，暂无回测数据。阶段二将验证超卖反弹+动量确认共振的有效性。",
  },
  // --- 候选卖点区（1个） ---
  F_D1_MA_death: {
    name: "D1回落5%+MA5/20死叉 融合卖（实验性新组合）", side: "sell", zone: "candidate_sell", status: "experimental",
    conditions: ["20日高回落5%", "MA5/20死叉"],
    trigger: "同日AND：close从20日最高价回落5% 且 MA5下穿MA20（均线死叉共振）",
    conclusion: "实验性新组合。回落+均线死叉共振，待回测验证",
    theory: "实验性新组合。20日高回落5%捕捉趋势转弱，叠加MA5/20死叉确认均线转弱。两条件同日AND共振。",
    scenario: "趋势转弱+均线死叉共振减仓；实验性，待回测验证。",
    note: "实验室新组合，非主项目提取。需阶段二回测验证是否有价值。",
    report: "实验性新组合，暂无回测数据。阶段二将验证回落+均线死叉共振的有效性。",
  },
};

// === 候选融合信号生成器（自动两两组合）===
// 从 LAB_STRATEGIES 取候选买点7个 + 候选卖点7个，生成三类候选：
// 1) 买×卖配对：7×7=49，zone=candidate_buy
// 2) 买×买共振：C(7,2)=21，zone=candidate_buy
// 3) 卖×卖共振：C(7,2)=21，zone=candidate_sell
function _generateFusionCandidates() {
  // 提取候选买点和卖点
  const buyCandidates = Object.entries(LAB_STRATEGIES)
    .filter(([k, v]) => v.zone === "buy" && v.status === "experimental")
    .map(([k, v]) => ({ key: k, ...v }));
  const sellCandidates = Object.entries(LAB_STRATEGIES)
    .filter(([k, v]) => v.zone === "sell" && v.status === "experimental")
    .map(([k, v]) => ({ key: k, ...v }));

  // 短名映射：从 name 提取可读短名
  const shortName = (s) => {
    const n = s.name;
    if (n.includes("布林下轨")) return "BB下轨";
    if (n.includes("Supertrend")) return "Supertrend";
    if (n.includes("唐奇安")) return "唐奇安" + (n.includes("55") ? "55" : "20");
    if (n.includes("海龟")) return "海龟55";
    if (n.includes("MA")) return "MA" + (n.includes("5/20") ? "5/20" : "10/60");
    if (n.includes("MACD")) return "MACD";
    if (n.includes("布林上轨")) return "BB上轨";
    if (n.includes("跌破布林中轨")) return "BB中轨";
    if (n.includes("跌破10日")) return "破10日低";
    if (n.includes("跌破20日")) return "破20日低";
    if (n.includes("ATR")) return "ATR止损";
    return n.substring(0, 6);
  };

  const candidates = {};
  let idx = 1;

  // 1) 买×卖配对（49个）— A类：可查 lab_sim_{index}_stats.json 回测
  buyCandidates.forEach((buy) => {
    sellCandidates.forEach((sell) => {
      const key = `F_pending_${idx++}`;
      candidates[key] = {
        name: `F_${shortName(buy)}_${shortName(sell)}`,
        side: "buy",
        zone: "candidate_buy",
        status: "pending",
        conditions: [buy.name, sell.name],
        trigger: `同日AND：${buy.trigger && buy.trigger.substring(0, 30)}… && ${sell.trigger && sell.trigger.substring(0, 30)}…`,
        conclusion: `配对候选：${buy.name} 作为买点 + ${sell.name} 作为卖点，待回测验证效果`,
        _isPending: true,
        _pairType: "buy_sell",
        _buyKey: buy.key,
        _sellKey: sell.key,
      };
    });
  });

  // 2) 买×买共振（C(7,2)=21个）— B类：同向共振，回测开发中
  for (let i = 0; i < buyCandidates.length; i++) {
    for (let j = i + 1; j < buyCandidates.length; j++) {
      const b1 = buyCandidates[i], b2 = buyCandidates[j];
      const key = `F_pending_${idx++}`;
      candidates[key] = {
        name: `F_${shortName(b1)}_${shortName(b2)}`,
        side: "buy",
        zone: "candidate_buy",
        status: "pending",
        conditions: [b1.name, b2.name],
        trigger: `同日AND共振：${b1.trigger && b1.trigger.substring(0, 30)}… && ${b2.trigger && b2.trigger.substring(0, 30)}…`,
        conclusion: `双买共振候选：${b1.name} + ${b2.name} 双信号确认，待回测验证效果`,
        _isPending: true,
        _pairType: "buy_buy",
        _buyKey: b1.key,
        _sellKey: b2.key,
      };
    }
  }

  // 3) 卖×卖共振（C(7,2)=21个）— B类：同向共振，回测开发中
  for (let i = 0; i < sellCandidates.length; i++) {
    for (let j = i + 1; j < sellCandidates.length; j++) {
      const s1 = sellCandidates[i], s2 = sellCandidates[j];
      const key = `F_pending_${idx++}`;
      candidates[key] = {
        name: `F_${shortName(s1)}_${shortName(s2)}`,
        side: "sell",
        zone: "candidate_sell",
        status: "pending",
        conditions: [s1.name, s2.name],
        trigger: `同日AND共振：${s1.trigger && s1.trigger.substring(0, 30)}… && ${s2.trigger && s2.trigger.substring(0, 30)}…`,
        conclusion: `双卖共振候选：${s1.name} + ${s2.name} 双信号确认，待回测验证效果`,
        _isPending: true,
        _pairType: "sell_sell",
        _buyKey: s1.key,
        _sellKey: s2.key,
      };
    }
  }

  return candidates;
}

// 融合候选池：运行时生成一次
const LAB_FUSION_PENDING = _generateFusionCandidates();

// 融合信号4分区定义（zone key 与 LAB_FUSION_STRATEGIES 的 zone 字段对齐）
const LAB_FUSION_ZONES = [
  { key: "candidate_buy", label: "🧪 候选买点", count: "3+70", desc: "融合候选买点（多信号共振入场，含70+自动生成待回测）" },
  { key: "candidate_sell", label: "🧪 候选卖点", count: "1+21", desc: "融合候选卖点（多信号共振出场，含21自动生成待回测）" },
  { key: "excluded", label: "📋 已排除", count: 0, desc: "回测不达标已弃用的融合信号" },
  { key: "prod", label: "✅ 生产参考", count: 2, desc: "已上线生产的融合信号" },
];

// 矩阵窗口/horizon 定义
const LAB_WINDOWS = ["全史", "近10年", "近5年", "近3年", "近1年"];
const LAB_HORIZONS = ["5d", "10d", "20d", "60d"];

// === 5窗口切换（数据源 lab_sim_{index}_stats.json / _full.json：stats/trades切片/equity切片 均按窗口独立）===
// win key -> 矩阵中文窗口名（用于行高亮）
const LAB_WIN_CN = { all: "全史", y10: "近10年", y5: "近5年", y3: "近3年", y1: "近1年" };
const LAB_WIN_DEFS = [
  { k: "all", l: "全历史" },
  { k: "y10", l: "近10年" },
  { k: "y5", l: "近5年" },
  { k: "y3", l: "近3年" },
  { k: "y1", l: "近1年" },
];

// 配对查找：新结构 pairs 按 "buyKey|sellKey" 存一份（配对去重），直接取
function _labGetPair(simData, buyKey, sellKey) {
  return simData.pairs && simData.pairs[buyKey + "|" + sellKey];
}

// 取某窗口的数据：stats(单窗口) + trades(按 tw 切片) + equity_curve(该窗口独立)
// equity_curve 为每窗口独立从 INITIAL_CAPITAL 起算的净值曲线 dict {all,y10,y5,y3,y1}
// hasFull 标记 full 数据(trades/equity_curve)是否已加载，未加载时仅 stats 可用
function _labPairWinData(pairData, mode, win, simData) {
  const md = pairData && pairData[mode];
  if (!md) return null;
  const stats = (md.stats && md.stats[win]) || null;
  const tw = md.tw && md.tw[win];
  const trades = (tw && md.trades) ? md.trades.slice(tw[0], tw[1]) : (md.trades || []);
  // equity_curve: 新结构为 dict {all,y10,...}，旧结构为数组(全史)兼容
  const ec = md.equity_curve;
  let equity_curve;
  if (Array.isArray(ec)) {
    equity_curve = ec;  // 旧结构兼容
  } else if (ec && ec[win]) {
    equity_curve = ec[win];
  } else {
    equity_curve = [];
  }
  const hasFull = !!md.trades || !!ec;
  return { stats, trades, equity_curve, hasFull };
}

// 窗口切换 tabs HTML（默认近1年：全史太密）
function _labWinTabsHTML() {
  const cur = state.labSimWindow || "y5";
  return '<div class="lab-win-tabs">' + LAB_WIN_DEFS.map((w) =>
    `<button type="button" class="lab-win-tab${w.k === cur ? " active" : ""}" data-win="${w.k}">${w.l}</button>`
  ).join("") + "</div>";
}

// 有图表实现的策略 key（仅这4个有指标+信号图表）
const LAB_CHART_KEYS = {
  // 候选买点
  BB_lower_revert: 1, Supertrend_buy: 1, Donchian20_up: 1, Donchian55_up: 1,
  MA_golden_5_20: 1, MA_golden_10_60: 1, MACD_golden: 1,
  // 候选卖点
  BB_upper_revert: 1, MA_death_5_20: 1, BB_middle_break: 1, Donchian10_down: 1,
  Donchian20_down: 1, MACD_death: 1, ATR_trail_stop: 1,
  // 已排除（反面教材仍出图便于直观对比）
  BB_upper_break: 1, KDJ_golden_oversold: 1, Vol_breakout: 1, B0_RSI70: 1, KDJ_death_overbought: 1, Supertrend_sell: 1,
  // 生产参考
  C1_RSI30: 1, D1_high20_drop5: 1,
};

// 策略 → 用到的技术指标 key（散户白话释义用，仅列出图策略实际用到的指标）
const LAB_STRATEGY_INDICATORS = {
  BB_upper_revert: ["BB"], BB_lower_revert: ["BB"], BB_middle_break: ["BB"], BB_upper_break: ["BB"],
  Supertrend_buy: ["Supertrend"], Supertrend_sell: ["Supertrend"],
  MA_death_5_20: ["MA"], MA_golden_5_20: ["MA"], MA_golden_10_60: ["MA"],
  Donchian20_up: ["Donchian"], Donchian55_up: ["Donchian"], Donchian10_down: ["Donchian"], Donchian20_down: ["Donchian"],
  MACD_golden: ["MACD"], MACD_death: ["MACD"],
  KDJ_golden_oversold: ["KDJ"], KDJ_death_overbought: ["KDJ"],
  C1_RSI30: ["RSI"], B0_RSI70: ["RSI"],
  ATR_trail_stop: ["ATR"],
  D1_high20_drop5: ["Drop5"],
  Vol_breakout: ["Vol"],
};

// 技术指标散户白话释义（初中生能懂）
const LAB_INDICATOR_PLAIN = {
  BB: { name: "BB 布林带", plain: "用近20日均价和波动幅度画的价格通道。触及上轨=近期偏贵可能回落，触及下轨=偏便宜可能反弹，中轨=20日均线。" },
  Supertrend: { name: "Supertrend 超级趋势", plain: "基于波动率(ATR)画的趋势跟踪线。翻红=转多(买)，翻绿=转空(卖)。" },
  MA: { name: "MA 均线", plain: "近N个交易日的平均价。短期均线在长期均线之上=多头排列、趋势向上，反之=空头、趋势向下。" },
  Donchian: { name: "Donchian 通道", plain: "近N日最高价和最低价画的通道。价格突破上轨=创新高看多，跌破下轨=创新低看空。" },
  MACD: { name: "MACD", plain: "动量指标。DIF上穿DEA=金叉看多，DIF下穿DEA=死叉看空。" },
  KDJ: { name: "KDJ", plain: "超买超卖指标。K线上穿D线=金叉(低位更准)，K线下穿D线=死叉(高位更准)。" },
  RSI: { name: "RSI 相对强弱", plain: "0-100的强弱指标。<30超卖(跌多了可能反弹)，>70超买(涨多了可能回落)。" },
  ATR: { name: "ATR 真实波幅", plain: "衡量波动剧烈程度，数值越大波动越猛。追踪止损线=近期高点-3倍ATR，跌破即止损。" },
  Drop5: { name: "20日高回落5%", plain: "近20日最高价下跌5%触发止盈。回落阈值线会随创新高而上移。" },
  Vol: { name: "量比 成交额比值", plain: "今日成交额除以近20日平均成交额。>2=放量（资金涌入），<1=缩量。指数无成交量字段，用成交额代理。" },
};

// 构建策略图表配置（指标线+信号+标注文案），供 renderLabDetail 和买卖信号弹窗复用
// 返回 { indicators, signals, signalLabel, signalColor, chartTitle, statLabel } 或 null（无图表实现）
// 信号逻辑严格对齐 a-stock-data/backtest_strategies.py 的 gen_buy_signals/gen_sell_signals
function _labBuildChartConfig(key, ohlc, indexName) {
  if (!LAB_CHART_KEYS[key]) return null;
  const meta = LAB_STRATEGIES[key];
  const signalLabel = meta.name; // 信号标注用策略中文名
  const name = indexName || "";
  const isBuy = meta.side === "buy";
  const sigColor = isBuy ? "#2e7d32" : "#9c27b0";   // 买绿卖紫（单策略详情图）
  const statLabel = isBuy ? "买点" : "卖点";

  if (key === "BB_upper_revert") {
    const bb = computeBBLab(ohlc);
    return {
      indicators: [
        { name: "布林上轨", data: bb.bu, color: cssVar('--text-4'), dash: true },
        { name: "布林下轨", data: bb.bl, color: cssVar('--text-4'), dash: true },
      ],
      signals: bb.signals, signalLabel, signalColor: "#9c27b0",
      chartTitle: `${name} · 布林上轨回落实验`, statLabel: "实验卖点",
    };
  } else if (key === "BB_lower_revert") {
    const r2 = computeBBLowerRevertLab(ohlc);
    return {
      indicators: [
        { name: "布林上轨", data: r2.bu, color: cssVar('--text-4'), dash: true },
        { name: "布林下轨", data: r2.bl, color: cssVar('--text-4'), dash: true },
      ],
      signals: r2.signals, signalLabel, signalColor: "#2e7d32",
      chartTitle: `${name} · 布林下轨回归实验`, statLabel: "实验买点",
    };
  } else if (key === "Supertrend_buy") {
    const r2 = computeSupertrendLab(ohlc);
    return {
      indicators: [
        { name: "趋势线(多)", data: r2.stBull, color: "#2e7d32", dash: false },
        { name: "趋势线(空)", data: r2.stBear, color: "#c92a2a", dash: false },
      ],
      signals: r2.signals, signalLabel, signalColor: "#2e7d32",
      chartTitle: `${name} · Supertrend翻多实验`, statLabel: "实验买点",
    };
  } else if (key === "MA_death_5_20") {
    const r2 = computeMADeathCrossLab(ohlc);
    return {
      indicators: [
        { name: "MA5", data: r2.ma5, color: "#1f6feb", dash: false },
        { name: "MA20", data: r2.ma20, color: "#f0883e", dash: false },
      ],
      signals: r2.signals, signalLabel, signalColor: "#9c27b0",
      chartTitle: `${name} · MA5/20死叉实验`, statLabel: "实验卖点",
    };
  }

  // --- BB 族扩展：中轨破位 / 上轨突破 ---
  if (key === "BB_middle_break") {
    const bb = computeBBLab(ohlc);
    const closes = ohlc.map((d) => d.close);
    const signals = [];
    for (let i = 1; i < closes.length; i++) {
      if (bb.mid[i - 1] == null || bb.mid[i] == null) continue;
      if (closes[i - 1] >= bb.mid[i - 1] && closes[i] < bb.mid[i]) signals.push({ date: ohlc[i].date, close: closes[i] });
    }
    return {
      indicators: [
        { name: "布林上轨", data: bb.bu, color: cssVar('--text-4'), dash: true },
        { name: "布林中轨MA20", data: bb.mid, color: cssVar('--text-3'), dash: false },
        { name: "布林下轨", data: bb.bl, color: cssVar('--text-4'), dash: true },
      ],
      signals, signalLabel, signalColor: sigColor,
      chartTitle: `${name} · 跌破布林中轨`, statLabel,
    };
  } else if (key === "BB_upper_break") {
    const bb = computeBBLab(ohlc);
    const closes = ohlc.map((d) => d.close);
    const signals = [];
    for (let i = 1; i < closes.length; i++) {
      if (bb.bu[i - 1] == null || bb.bu[i] == null) continue;
      if (closes[i - 1] <= bb.bu[i - 1] && closes[i] > bb.bu[i]) signals.push({ date: ohlc[i].date, close: closes[i] });
    }
    return {
      indicators: [
        { name: "布林上轨", data: bb.bu, color: cssVar('--text-4'), dash: true },
        { name: "布林下轨", data: bb.bl, color: cssVar('--text-4'), dash: true },
      ],
      signals, signalLabel, signalColor: sigColor,
      chartTitle: `${name} · 突破布林上轨`, statLabel,
    };
  }

  // --- Supertrend 翻空卖 ---
  if (key === "Supertrend_sell") {
    const r2 = computeSupertrendLab(ohlc);
    const signals = [];
    for (let i = 1; i < r2.dir.length; i++) {
      if (!r2.dir[i] || !r2.dir[i - 1]) continue;
      if (r2.dir[i - 1] === 1 && r2.dir[i] === -1) signals.push({ date: ohlc[i].date, close: ohlc[i].close });
    }
    return {
      indicators: [
        { name: "趋势线(多)", data: r2.stBull, color: "#2e7d32", dash: false },
        { name: "趋势线(空)", data: r2.stBear, color: "#c92a2a", dash: false },
      ],
      signals, signalLabel, signalColor: sigColor,
      chartTitle: `${name} · Supertrend翻空`, statLabel,
    };
  }

  // --- Donchian 通道突破（20买/55买/10卖/20卖）---
  if (key === "Donchian20_up" || key === "Donchian55_up" || key === "Donchian10_down" || key === "Donchian20_down") {
    const nMap = { Donchian20_up: 20, Donchian55_up: 55, Donchian10_down: 10, Donchian20_down: 20 };
    const n = nMap[key];
    const dc = computeDonchianLab(ohlc, n);
    const closes = ohlc.map((d) => d.close);
    const isUp = key.indexOf("_up") > 0;
    const band = isUp ? dc.upper : dc.lower;
    const signals = [];
    for (let i = 1; i < closes.length; i++) {
      if (band[i] == null || band[i - 1] == null) continue;
      if (isUp) { if (closes[i] > band[i] && closes[i - 1] <= band[i - 1]) signals.push({ date: ohlc[i].date, close: closes[i] }); }
      else { if (closes[i] < band[i] && closes[i - 1] >= band[i - 1]) signals.push({ date: ohlc[i].date, close: closes[i] }); }
    }
    const bandName = isUp ? `${n}日最高(前)` : `${n}日最低(前)`;
    return {
      indicators: [{ name: bandName, data: band, color: isUp ? "#2e7d32" : "#c92a2a", dash: false }],
      signals, signalLabel, signalColor: sigColor,
      chartTitle: `${name} · ${meta.name}`, statLabel,
    };
  }

  // --- MA 金叉/死叉 ---
  if (key === "MA_golden_5_20" || key === "MA_golden_10_60") {
    const S = key === "MA_golden_5_20" ? 5 : 10;
    const L = key === "MA_golden_5_20" ? 20 : 60;
    const closes = ohlc.map((d) => d.close);
    const maS = _smaLab(closes, S), maL = _smaLab(closes, L);
    const signals = [];
    for (let i = 1; i < closes.length; i++) {
      if (maS[i] == null || maL[i] == null || maS[i - 1] == null || maL[i - 1] == null) continue;
      if (maS[i - 1] <= maL[i - 1] && maS[i] > maL[i]) signals.push({ date: ohlc[i].date, close: closes[i] });
    }
    return {
      indicators: [
        { name: `MA${S}`, data: maS, color: "#1f6feb", dash: false },
        { name: `MA${L}`, data: maL, color: "#f0883e", dash: false },
      ],
      signals, signalLabel, signalColor: sigColor,
      chartTitle: `${name} · ${meta.name}`, statLabel,
    };
  }

  // --- MACD 金叉/死叉（副图 osc 轴）---
  if (key === "MACD_golden" || key === "MACD_death") {
    const m = computeMACDLab(ohlc);
    const golden = key === "MACD_golden";
    const signals = [];
    for (let i = 1; i < m.dif.length; i++) {
      if (m.dif[i] == null || m.dea[i] == null || m.dif[i - 1] == null || m.dea[i - 1] == null) continue;
      if (golden) { if (m.dif[i - 1] <= m.dea[i - 1] && m.dif[i] > m.dea[i]) signals.push({ date: ohlc[i].date, close: ohlc[i].close }); }
      else { if (m.dif[i - 1] >= m.dea[i - 1] && m.dif[i] < m.dea[i]) signals.push({ date: ohlc[i].date, close: ohlc[i].close }); }
    }
    return {
      indicators: [
        { name: "DIF", data: m.dif, color: "#1f6feb", dash: false, axis: "osc" },
        { name: "DEA", data: m.dea, color: "#f0883e", dash: false, axis: "osc" },
      ],
      signals, signalLabel, signalColor: sigColor,
      chartTitle: `${name} · ${meta.name}`, statLabel,
    };
  }

  // --- KDJ 金叉/死叉（副图 osc 轴）---
  if (key === "KDJ_golden_oversold" || key === "KDJ_death_overbought") {
    const kd = computeKDJLab(ohlc, 9);
    const golden = key === "KDJ_golden_oversold";
    const signals = [];
    for (let i = 1; i < kd.k.length; i++) {
      if (kd.k[i] == null || kd.d[i] == null || kd.k[i - 1] == null || kd.d[i - 1] == null) continue;
      if (golden) { if (kd.k[i - 1] <= kd.d[i - 1] && kd.k[i] > kd.d[i] && kd.k[i] < 35) signals.push({ date: ohlc[i].date, close: ohlc[i].close }); }
      else { if (kd.k[i - 1] >= kd.d[i - 1] && kd.k[i] < kd.d[i] && kd.k[i] > 70) signals.push({ date: ohlc[i].date, close: ohlc[i].close }); }
    }
    const len = kd.k.length;
    return {
      indicators: [
        { name: "K", data: kd.k, color: "#1f6feb", dash: false, axis: "osc" },
        { name: "D", data: kd.d, color: "#f0883e", dash: false, axis: "osc" },
        { name: "超卖35", data: new Array(len).fill(35), color: "#2e7d32", dash: true, axis: "osc" },
        { name: "超买70", data: new Array(len).fill(70), color: "#c92a2a", dash: true, axis: "osc" },
      ],
      signals, signalLabel, signalColor: sigColor,
      chartTitle: `${name} · ${meta.name}`, statLabel,
    };
  }

  // --- RSI 上穿30买 / 下穿70卖（副图 osc 轴）---
  if (key === "C1_RSI30" || key === "B0_RSI70") {
    const rsi = computeRSILab(ohlc, 14);
    const crossUp = key === "C1_RSI30";
    const signals = [];
    for (let i = 1; i < rsi.length; i++) {
      if (rsi[i] == null || rsi[i - 1] == null) continue;
      if (crossUp) { if (rsi[i - 1] <= 30 && rsi[i] > 30) signals.push({ date: ohlc[i].date, close: ohlc[i].close }); }
      else { if (rsi[i - 1] >= 70 && rsi[i] < 70) signals.push({ date: ohlc[i].date, close: ohlc[i].close }); }
    }
    const len = rsi.length;
    return {
      indicators: [
        { name: "RSI(14)", data: rsi, color: "#1f6feb", dash: false, axis: "osc" },
        { name: "超卖30", data: new Array(len).fill(30), color: "#2e7d32", dash: true, axis: "osc" },
        { name: "超买70", data: new Array(len).fill(70), color: "#c92a2a", dash: true, axis: "osc" },
      ],
      signals, signalLabel, signalColor: sigColor,
      chartTitle: `${name} · ${meta.name}`, statLabel,
    };
  }

  // --- ATR 追踪止损 ---
  if (key === "ATR_trail_stop") {
    const r = computeATRTrailLab(ohlc);
    return {
      indicators: [{ name: "ATR追踪止损线", data: r.trail, color: "#c92a2a", dash: true }],
      signals: r.signals, signalLabel, signalColor: sigColor,
      chartTitle: `${name} · ATR追踪止损`, statLabel,
    };
  }

  // --- D1 20日高回落5% ---
  if (key === "D1_high20_drop5") {
    const r = computeD1Lab(ohlc);
    return {
      indicators: [{ name: "回落阈值(-5%)", data: r.th, color: "#c92a2a", dash: true }],
      signals: r.signals, signalLabel, signalColor: sigColor,
      chartTitle: `${name} · 20日高回落5%`, statLabel,
    };
  }

  // --- Vol_breakout 放量突破（成交额代理，副图 osc 轴）---
  if (key === "Vol_breakout") {
    const r = computeVolBreakoutLab(ohlc);
    const len = ohlc.length;
    return {
      indicators: [
        { name: "量比(成交额/20均)", data: r.vratio, color: "#1f6feb", dash: false, axis: "osc" },
        { name: "放量阈值2.0", data: new Array(len).fill(2.0), color: "#c92a2a", dash: true, axis: "osc" },
      ],
      signals: r.signals, signalLabel, signalColor: sigColor,
      chartTitle: `${name} · 放量突破（成交额代理）`, statLabel,
    };
  }

  return null;
}

// 获取 lab_backtest.json 数据（缓存到 state.labData）
// web 版走 /static/ 挂载点（main.py 的 StaticFiles(directory=web)），static 版走 ./data/
async function fetchLabData() {
  if (state.labData) return state.labData;
  try {
    state.labData = await fetchJSON("/static/data/lab/lab_backtest.json");
  } catch (e) {
    state.labData = null;
  }
  return state.labData;
}

// 获取按指数拆分的矩阵数据（lab_backtest_{index}.json）
// idx="all" 时加载全市场聚合数据（lab_backtest.json），复用 fetchLabData 缓存
async function fetchLabMatrixData(idx) {
  idx = idx || "all";
  if (idx === "all") return fetchLabData();
  if (!state.labMatrixDataMap) state.labMatrixDataMap = {};
  if (state.labMatrixDataMap[idx]) return state.labMatrixDataMap[idx];
  try {
    state.labMatrixDataMap[idx] = await fetchJSON("/static/data/lab/lab_backtest_" + idx + ".json");
  } catch (e) {
    state.labMatrixDataMap[idx] = null;
  }
  return state.labMatrixDataMap[idx];
}

// 模拟回测可选指数（每个指数一个 JSON 文件，前端按需加载）
// 9个A股宽基指数：覆盖大盘/成长/价值/中小盘全谱系（含北证50，历史较短2022起），须与 lab_simulate.py 的 SIM_INDEXES 同步
const LAB_SIM_INDEXES = [
  { id: "sh", name: "上证指数" },
  { id: "sz", name: "深证成指" },
  { id: "cyb", name: "创业板指" },
  { id: "kc50", name: "科创50" },
  { id: "bj50", name: "北证50" },
  { id: "sz50", name: "上证50" },
  { id: "hs300", name: "沪深300" },
  { id: "csi500", name: "中证500" },
  { id: "csi1000", name: "中证1000" },
];

// 获取 lab_sim_{index}_stats.json 数据（小文件，推荐榜/矩阵/配对卡片秒开）
// per-index 缓存到 state.labSimDataMap。详情(trades/equity_curve)由 fetchLabSimFullData 按需加载并合并。
// web 版走 /static/ 挂载点（main.py 的 StaticFiles(directory=web)），static 版走 ./data/
async function fetchLabSimData(index) {
  index = index || "sh";
  if (!state.labSimDataMap) state.labSimDataMap = {};
  if (state.labSimDataMap[index]) return state.labSimDataMap[index];
  try {
    state.labSimDataMap[index] = await fetchJSON("/static/data/lab/lab_sim_" + index + "_stats.json");
  } catch (e) {
    state.labSimDataMap[index] = null;
  }
  return state.labSimDataMap[index];
}

// 获取 lab_retest_{index}.json 数据（二次测试：分年/样本外/极端行情，per-index 缓存）
async function fetchLabRetestData(index) {
  index = index || "sh";
  if (!state.labRetestDataMap) state.labRetestDataMap = {};
  if (state.labRetestDataMap[index]) return state.labRetestDataMap[index];
  try {
    state.labRetestDataMap[index] = await fetchJSON("/static/data/lab/lab_retest_" + index + ".json");
  } catch (e) {
    state.labRetestDataMap[index] = null;
  }
  return state.labRetestDataMap[index];
}

// 检查某指数 full 数据是否已合并入缓存（用于判断详情是否需显示 loading）
function _labSimFullLoaded(index) {
  index = index || "sh";
  return !!(state.labSimFullMap && state.labSimFullMap[index] === true);
}

// 带 HTTP 进度的 fetch JSON（读 ReadableStream 累计 received/Content-Length 算百分比）
// 无 Content-Length 或不支持流时降级为普通 fetchJSON，onProgress(-1) 表示无法测算
async function fetchJSONProgress(url, onProgress, signal) {
  try {
    const resp = await fetch(url, signal ? { signal } : undefined);
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    const total = parseInt(resp.headers.get("Content-Length") || "0", 10);
    if (!total || !resp.body || !resp.body.getReader) {
      if (onProgress) onProgress(-1, 0);
      return resp.json();
    }
    const reader = resp.body.getReader();
    let received = 0;
    const chunks = [];
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      if (value) { chunks.push(value); received += value.length; if (onProgress) onProgress(received, total); }
    }
    if (onProgress) onProgress(total, total);
    const blob = new Blob(chunks);
    const txt = await blob.text();
    return JSON.parse(txt);
  } catch (e) {
    if (e && e.name === "AbortError") throw e; // 中止不降级，向上抛
    // 流式读取失败（如浏览器不支持），降级普通 fetch
    if (onProgress) onProgress(-1, 0);
    return fetchJSON(url);
  }
}

// 加载完整数据(trades/equity_curve/tw/ew)，合并入已缓存的 stats 数据
// onProgress(received, total) 用于进度条；total<0 表示无法测算
// 返回合并后的 simData（即 state.labSimDataMap[index]）
async function fetchLabSimFullData(index, onProgress, signal) {
  index = index || "sh";
  if (!state.labSimFullMap) state.labSimFullMap = {};
  if (state.labSimFullMap[index] === true) return state.labSimDataMap[index]; // 已合并
  if (state.labSimFullMap[index] === "loading") {
    // 已有加载中请求，轮询等待完成（避免重复下载）
    for (let i = 0; i < 600; i++) {
      await new Promise((r) => setTimeout(r, 100));
      if (state.labSimFullMap[index] === true) return state.labSimDataMap[index];
      if (state.labSimFullMap[index] === null) break;
      if (signal && signal.aborted) return state.labSimDataMap[index]; // 中止轮询
    }
    return state.labSimDataMap[index];
  }
  const stats = state.labSimDataMap && state.labSimDataMap[index];
  if (!stats) return null;
  state.labSimFullMap[index] = "loading";
  try {
    const full = await fetchJSONProgress("./data/lab/lab_sim_" + index + "_full.json", onProgress, signal);
    if (full && full.pairs && stats.pairs) {
      for (const pk in full.pairs) {
        const fp = full.pairs[pk];
        const sp = stats.pairs[pk];
        if (!sp) continue;
        for (const mode of ["full_in", "fixed_10k"]) {
          if (fp[mode]) {
            if (!sp[mode]) sp[mode] = {};
            sp[mode].equity_curve = fp[mode].equity_curve;
            sp[mode].trades = fp[mode].trades;
            sp[mode].tw = fp[mode].tw;
          }
        }
      }
    }
    state.labSimFullMap[index] = true;
  } catch (e) {
    state.labSimFullMap[index] = null;
  }
  return state.labSimDataMap[index];
}

// 模拟回测净值曲线 SVG（轻量纯SVG，不依赖 ECharts）
// gradId 用于双图并列时避免 gradient id 冲突
function _labSimSVG(curve, initCapital, gradId) {
  gradId = gradId || "labSimGrad";
  if (!curve || curve.length < 2) return '<div class="lab-sim-empty">净值数据不足</div>';
  const vals = curve.map((e) => e.value);
  const dates = curve.map((e) => e.date);
  let yMin = Math.min(...vals, initCapital) * 0.95;
  let yMax = Math.max(...vals, initCapital) * 1.05;
  if (yMax <= yMin) yMax = yMin + 1;
  const W = 800, H = 160, ml = 70, mr = 10, mt = 8, mb = 24;
  const pw = W - ml - mr, ph = H - mt - mb;
  const n = vals.length;
  const sy = (v) => mt + ph - ((v - yMin) / (yMax - yMin)) * ph;
  const sx = (i) => ml + (n > 1 ? (i / (n - 1)) * pw : 0);
  const baselineY = sy(initCapital);
  const finalVal = vals[n - 1];
  const peakVal = Math.max(...vals);
  const peakIdx = vals.indexOf(peakVal);
  const minVal = Math.min(...vals);
  const pts = vals.map((v, i) => `${sx(i).toFixed(1)},${sy(v).toFixed(1)}`);
  const areaPts = pts.join(" ") + ` ${sx(n - 1).toFixed(1)},${(mt + ph).toFixed(1)} ${sx(0).toFixed(1)},${(mt + ph).toFixed(1)}`;
  const fmtV = (v) => (v >= 10000 ? `${(v / 10000).toFixed(1)}万` : v.toFixed(0));
  const yLabels = [
    { l: "起始", v: initCapital, c: "var(--text-3)" },
    { l: "最低", v: minVal, c: "#2e7d32" },
    { l: "峰值", v: peakVal, c: "#c92a2a" },
    { l: "期末", v: finalVal, c: "#3370ff" },
  ].map((it) => `<text x="${ml - 4}" y="${sy(it.v).toFixed(1)}" text-anchor="end" font-size="10" style="fill:${it.c}" dominant-baseline="middle">${it.l} ${fmtV(it.v)}</text>`).join("");
  const tickCount = Math.min(7, Math.max(3, Math.floor(n / 2)));
  const step = n > 1 ? (n - 1) / (tickCount - 1) : 1;
  const xLabels = [];
  for (let k = 0; k < tickCount; k++) {
    const i = Math.min(Math.round(k * step), n - 1);
    xLabels.push(`<text x="${sx(i).toFixed(1)}" y="${H - 4}" text-anchor="middle" font-size="9" style="fill:var(--text-3)">${dates[i].substring(0, 7)}</text>`);
  }
  const lineColor = finalVal >= initCapital ? "#c92a2a" : "#2e7d32";
  return `<svg width="100%" height="150" viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" style="display:block;margin-top:8px;border-radius:6px;background:var(--bg-hover)">
    <defs><linearGradient id="${gradId}" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="${lineColor}" stop-opacity="0.12"/><stop offset="100%" stop-color="${lineColor}" stop-opacity="0.01"/></linearGradient></defs>
    <line x1="${ml}" y1="${baselineY.toFixed(1)}" x2="${sx(n - 1).toFixed(1)}" y2="${baselineY.toFixed(1)}" style="stroke:var(--border-strong)" stroke-dasharray="6,4" stroke-width="1"/>
    <polygon points="${areaPts}" fill="url(#${gradId})"/>
    <polyline points="${pts.join(" ")}" fill="none" stroke="${lineColor}" stroke-width="1.5" stroke-linejoin="round"/>
    ${yLabels}
    <circle cx="${sx(peakIdx).toFixed(1)}" cy="${sy(peakVal).toFixed(1)}" r="3" fill="#c92a2a" style="stroke:var(--bg-card)" stroke-width="1"/>
    <circle cx="${sx(n - 1).toFixed(1)}" cy="${sy(finalVal).toFixed(1)}" r="3" fill="#3370ff" style="stroke:var(--bg-card)" stroke-width="1"/>
    ${xLabels.join("")}
  </svg>`;
}

// 三色分级辅助
function _labLvl(val, thresholds) {
  if (val > thresholds.good) return "good";
  if (val < thresholds.bad) return "bad";
  return "warn";
}

// 最大回撤配色：统一绿色渐变（浅绿=回撤小好，深绿=回撤大差），连续线性插值不分档
// t = min(max_dd/50, 1)，文字色 = lerp(#c8f7c5, #1b5e20, t)，只改文字色不加背景/padding/radius
// 返回 inline style 的 color 项，调用方直接 style="${_labDdColor(dd)}"
function _labDdColor(dd) {
  var t = Math.min(Math.max((dd || 0) / 50, 0), 1);
  var r = Math.round(0xc8 + (0x1b - 0xc8) * t);
  var g = Math.round(0xf7 + (0x5e - 0xf7) * t);
  var b = Math.round(0xc5 + (0x20 - 0xc5) * t);
  return "color:rgb(" + r + "," + g + "," + b + ");";
}

// 提取策略触发简述：优先取中文括号内内容，否则取逗号前
function _labTriggerBrief(trigger) {
  if (!trigger) return "";
  var m = trigger.match(/[（]([^）]+)[）]/);
  if (m) return m[1];
  return trigger.split(/[，,]/)[0];
}

// 渲染单个交易模式区块详情（4数字 + 净值曲线 + 折叠交易记录）
// 区块标题由外层 _labSimSectionHTML 的 .lab-sim-strat-head 提供，此处不含 head
// winData = {stats, trades, equity_curve}，已按当前窗口切片（_labPairWinData 产出）
function _labSimModeBlock(mode, winData, initCapital, page, isOpen, signalBtnHTML, pairLabel) {
  const s = winData && winData.stats;
  if (!s) {
    return `<div class="lab-sim-mode-block" data-mode="${mode}">` +
      (pairLabel ? `<div class="lab-sim-cur-pair">当前配对：${pairLabel}</div>` : "") +
      `<div class="lab-sim-empty">该模式无交易数据</div></div>`;
  }

  const retColor = s.total_ret >= 0 ? "#c92a2a" : "#2e7d32";
  const winColor = s.win_rate >= 50 ? "#c92a2a" : "#2e7d32";
  const winTrades = Math.round((s.win_rate / 100) * s.n_trades);
  const loseTrades = s.n_trades - winTrades;
  const gradId = "labSimGrad_" + mode;
  const svgHTML = _labSimSVG(winData.equity_curve, initCapital, gradId);
  const trades = winData.trades || [];

  // 分页
  const perPage = 20;
  const totalPages = Math.max(1, Math.ceil(trades.length / perPage));
  let currentPage = page || 0;
  if (currentPage >= totalPages) currentPage = totalPages - 1;
  if (currentPage < 0) currentPage = 0;
  const startIdx = currentPage * perPage;
  const showTrades = trades.slice(startIdx, startIdx + perPage);
  const totalReal = s.n_trades;
  const truncated = totalReal > trades.length;
  const truncNote = truncated ? `（仅展示前${trades.length}笔）` : "";

  const tradeRows = showTrades.map((t, i) => {
    const gi = startIdx + i;  // 全局索引（用于取上一笔算"较上次"差值）
    const prev = gi > 0 ? trades[gi - 1] : null;
    const tc = t.ret > 0 ? "#c92a2a" : (t.ret < 0 ? "#2e7d32" : "#86909c");
    const cpVal = t.cp != null ? t.cp : 0;                // 累计盈亏金额
    const crVal = cpVal / initCapital * 100;              // 累计收益率（前端由 cp 算，省 JSON 体积）
    const pc = crVal >= 0 ? "#c92a2a" : "#2e7d32";
    const at = t.at != null ? Math.round(t.at).toLocaleString() : "-";
    const cpStr = t.cp != null ? (cpVal >= 0 ? "+" : "") + Math.round(cpVal).toLocaleString() : "-";
    const crStr = t.cp != null ? (crVal >= 0 ? "+" : "") + crVal.toFixed(2) + "%" : "-";
    // "较上次"列：本笔累计收益率/累计盈亏 - 上一笔的差值（本笔赚还是亏）。首笔显示"-"
    let deltaHTML = '<span style="color:var(--text-4)">-</span>';
    if (prev && t.cp != null && prev.cp != null) {
      const dr = crVal - (prev.cp / initCapital * 100);   // 累计收益率差（百分点）
      const dp = cpVal - prev.cp;                         // 累计盈亏差=本笔盈亏金额
      const dc = dp >= 0 ? "#c92a2a" : "#2e7d32";         // 国人配色 红赚绿亏
      deltaHTML = `<span style="color:${dc};font-weight:600">${dr >= 0 ? "+" : ""}${dr.toFixed(2)}%</span>` +
        `<br><span style="color:${dc};font-size:11px">${dp >= 0 ? "+" : ""}${Math.round(dp).toLocaleString()}</span>`;
    }
    return `<tr><td>${gi + 1}</td><td>${t.bd}</td><td>${t.bp}</td><td>${t.sd}</td><td>${t.sp}</td><td style="color:${tc};font-weight:600">${t.ret > 0 ? "+" : ""}${t.ret}%</td><td>${t.hd}天</td><td>${at}</td><td style="color:${pc}">${cpStr}</td><td style="color:${pc};font-weight:600">${crStr}</td><td>${deltaHTML}</td></tr>`;
  }).join("");

  const pagerHTML = totalPages > 1
    ? `<div class="lab-sim-pager">` +
      `<button class="lab-sim-prev" data-mode="${mode}"${currentPage === 0 ? " disabled" : ""}>上一页</button>` +
      `<span class="lab-sim-page-info">第 ${currentPage + 1}/${totalPages} 页（共 ${totalReal} 笔${truncNote}）</span>` +
      `<button class="lab-sim-next" data-mode="${mode}"${currentPage >= totalPages - 1 ? " disabled" : ""}>下一页</button>` +
      `</div>`
    : trades.length > 0
      ? `<div class="lab-sim-pager"><span class="lab-sim-page-info">共 ${totalReal} 笔交易${truncNote}</span></div>`
      : "";

  const tradesBody = isOpen
    ? `<div class="lab-sim-trades-body">` +
      `<div class="lab-sim-table-wrap"><table><thead><tr><th>#</th><th>买入日期</th><th>买入价</th><th>卖出日期</th><th>卖出价</th><th>收益率</th><th>持有</th><th>账户总资金</th><th>累计盈亏</th><th>累计收益率</th><th data-tip="本笔累计收益率/累计盈亏相较上一笔的差值，红赚绿亏">较上次</th></tr></thead><tbody>` +
      (tradeRows || '<tr><td colspan="11" style="text-align:center;color:var(--text-4)">无交易记录</td></tr>') +
      `</tbody></table></div>${pagerHTML}</div>`
    : "";

  // full 数据未加载时，stats 数字可见（来自小 stats 文件），净值曲线/交易记录显示加载占位
  const detailHTML = winData.hasFull
    ? `<div class="lab-sim-equity"><div class="lab-sim-equity-label">📈 净值曲线（虚线=初始本金）</div>${svgHTML}</div>` +
      `<div class="lab-sim-trades">` +
      `<div class="lab-sim-trades-header" data-mode="${mode}">` +
      `<span class="lab-sim-trades-label">📋 交易记录 共 ${totalReal} 笔${truncNote}</span>` +
      `<span class="lab-sim-trades-toggle">${isOpen ? "收起 ▲" : "展开 ▼"}</span>` +
      `</div>` +
      tradesBody +
      `</div>`
    : `<div class="lab-sim-full-loading">⏳ 加载明细数据（净值曲线/交易记录）中…</div>`;

  return `<div class="lab-sim-mode-block" data-mode="${mode}">` +
    (pairLabel ? `<div class="lab-sim-cur-pair">当前配对：${pairLabel}</div>` : "") +
    `<div class="lab-sim-stats">` +
    `<div class="lab-sim-stat"><span class="k">总收益率</span><span class="v" style="color:${retColor}">${s.total_ret > 0 ? "+" : ""}${s.total_ret}%</span><span class="sub">期末 ${Math.round(s.final_total).toLocaleString()} 元</span></div>` +
    `<div class="lab-sim-stat"><span class="k">年化收益</span><span class="v" style="color:${retColor}">${s.annual_ret > 0 ? "+" : ""}${s.annual_ret}%</span><span class="sub">${s.years} 年</span></div>` +
    `<div class="lab-sim-stat"><span class="k">最大回撤</span><span class="v" style="${_labDdColor(s.max_drawdown)}">${s.max_drawdown}%</span><span class="sub">峰值最大跌幅</span></div>` +
    `<div class="lab-sim-stat"><span class="k">胜率</span><span class="v" style="color:${winColor}">${s.win_rate}%</span><span class="sub">${winTrades}胜/${loseTrades}负 · ${s.n_trades}笔</span></div>` +
    `</div>` +
    (signalBtnHTML || "") +
    detailHTML +
    `</div>`;
}

// 渲染单个策略区块（标题+描述 -> 配对卡片切换 -> 详情）
// 上下两区各自独立：配对卡片切换、4数字、净值曲线、折叠交易记录都各自一套
// 新结构：pairs 在 simData.pairs 按 "buyKey|sellKey" 去重存储，按 mainKey 的 side 决定 partner 方向
function _labSimSectionHTML(mode, simData, mainKey, side, pairKeys, defaultPair, initCapital, pairSideLabel) {
  const modeName = mode === "full_in" ? "全仓交易策略" : "定额（10%）交易策略";
  const modeDesc = mode === "full_in"
    ? "每次全仓买入卖出，本金复利滚动，收益和风险都放大"
    : "每次固定买入1万元分批建仓，卖信号清仓，风险更分散";
  const win = state.labSimWindow || "y5";

  // 各 mode 独立的配对选择
  const pairStateKey = mode === "full_in" ? "labSimPairFi" : "labSimPairFk";
  let currentPair = state[pairStateKey] || defaultPair;
  if (pairKeys.indexOf(currentPair) < 0) currentPair = pairKeys[0];
  state[pairStateKey] = currentPair;
  // 当前配对名（吸顶时常驻显示，让用户滚动看详情时仍知当前配的是什么）
  const curPairName = (LAB_STRATEGIES[currentPair] && LAB_STRATEGIES[currentPair].name) || currentPair;

  // 配对策略卡片列表（仅显示本 mode 的 ret/胜率/样本，按当前窗口 stats）
  const pairCards = pairKeys.map((pk) => {
    const meta = LAB_STRATEGIES[pk];
    const name = meta ? meta.name : pk;
    const buyKey = side === "buy" ? mainKey : pk;
    const sellKey = side === "buy" ? pk : mainKey;
    const pairData = _labGetPair(simData, buyKey, sellKey);
    const wd = _labPairWinData(pairData, mode, win, simData);
    const st = wd && wd.stats;
    let lvl = "warn";
    if (st) {
      const retLv = _labLvl(st.total_ret, { good: 5, bad: -5 });
      const winLv = _labLvl(st.win_rate, { good: 55, bad: 45 });
      const goods = [retLv, winLv].filter((x) => x === "good").length;
      const bads = [retLv, winLv].filter((x) => x === "bad").length;
      lvl = goods >= 2 ? "good" : bads >= 2 ? "bad" : "warn";
    }
    const activeCls = pk === currentPair ? " active" : "";
    const retStr = st ? `${st.total_ret > 0 ? "+" : ""}${st.total_ret}%` : "-";
    const retCls = st ? `pc-lvl-${_labLvl(st.total_ret, { good: 5, bad: -5 })}` : "";
    const winStr = st ? `胜${st.win_rate}%` : "";
    const winCls = st ? `pc-lvl-${_labLvl(st.win_rate, { good: 55, bad: 45 })}` : "";
    const nStr = st ? `n=${st.n_trades}` : "";
    return `<button type="button" class="lab-sim-pair-card lab-matrix-${lvl}${activeCls}" data-pair="${pk}" data-mode="${mode}">` +
      `<span class="pc-name" data-tip="${name}">${name}</span>` +
      (st ? `<span class="pc-ret ${retCls}">${retStr}</span>` +
       `<span class="pc-meta"><span class="pc-win ${winCls}">${winStr}</span><span class="pc-n">${nStr}</span></span>` : "") +
      `</button>`;
  }).join("");

  const pairListHTML =
    `<div class="lab-sim-pair-section"><div class="lab-sim-pair-label">配对${pairSideLabel}（点卡片切换 · 红好/绿差）</div>` +
    `<div class="lab-sim-pair-list">${pairCards}</div></div>`;

  // 当前配对的窗口切片数据
  const buyKey = side === "buy" ? mainKey : currentPair;
  const sellKey = side === "buy" ? currentPair : mainKey;
  const pairData = _labGetPair(simData, buyKey, sellKey);
  const winData = _labPairWinData(pairData, mode, win, simData);

  // 配对买卖点描述（策略卡与数据卡片之间的内容隔断 + 当前配对标注）
  const buyMeta = LAB_STRATEGIES[buyKey] || {};
  const sellMeta = LAB_STRATEGIES[sellKey] || {};
  const buyName = buyMeta.name || buyKey;
  const sellName = sellMeta.name || sellKey;
  const buyBrief = _labTriggerBrief(buyMeta.trigger);
  const sellBrief = _labTriggerBrief(sellMeta.trigger);
  const pairLabel = buyName + " × " + sellName;
  const pairDescHTML = `<div class="lab-sim-pair-desc">` +
    `<span class="ps-buy"><span class="ps-tag">买</span>${buyName}${buyBrief ? `<span class="ps-trig">${buyBrief}</span>` : ""}</span>` +
    `<span class="ps-x">×</span>` +
    `<span class="ps-sell"><span class="ps-tag">卖</span>${sellName}${sellBrief ? `<span class="ps-trig">${sellBrief}</span>` : ""}</span>` +
    `</div>`;

  // 区块标题：策略名 + 当前配对名 + 描述（sticky 吸顶时常驻）
  const headHTML = `<div class="lab-sim-strat-head"><span class="lab-sim-strat-name">${modeName}</span><span class="lab-sim-strat-pair">· 配 ${curPairName}</span><span class="lab-sim-strat-desc">${modeDesc}</span></div>`;
  // 买卖信号弹窗入口：买策略+卖策略 key
  const signalBtnHTML = `<div class="lab-sim-signal-btn-wrap"><button type="button" class="lab-sim-signal-btn" data-buy="${buyKey}" data-sell="${sellKey}">📊 查看买卖信号</button></div>`;
  if (!winData || !winData.stats) {
    return `<div class="lab-sim-strat-section" data-mode="${mode}">` +
      headHTML + pairListHTML + pairDescHTML + '<div class="lab-sim-empty">该模式无交易数据</div>' + signalBtnHTML + '</div>';
  }

  const page = mode === "full_in" ? (state.labSimPageFi || 0) : (state.labSimPageFk || 0);
  const isOpen = mode === "full_in" ? !!state.labSimFiOpen : !!state.labSimFkOpen;
  const detailBlock = _labSimModeBlock(mode, winData, initCapital, page, isOpen, signalBtnHTML, pairLabel);

  return `<div class="lab-sim-strat-section" data-mode="${mode}">` +
    headHTML + pairListHTML + pairDescHTML + detailBlock + '</div>';
}

// 渲染模拟回测卡片（双策略上下常驻 · 各自独立配对切换 · 5窗口切换 · 指数切换）
function _labSimCardHTML(key, simData) {
  const simIdxId = (simData && simData.index_id) || state.labSimIdx || "sh";
  const idxBtns = LAB_SIM_INDEXES.map((x) =>
    `<button type="button" class="lab-idx-tab${x.id === simIdxId ? " active" : ""}" data-sidx="${x.id}">${x.name}</button>`
  ).join("");
  const idxBarHTML = `<div class="lab-win-bar"><span class="lab-win-bar-label">选择指数</span><div class="lab-win-tabs">${idxBtns}</div></div>`;
  if (!simData || !simData.strategies || !simData.strategies[key] || !simData.pairs) {
    const idxName = (simData && simData.index_name) || "该指数";
    return `<h3>💰 模拟回测（${idxName} · 配对交易）</h3>` + idxBarHTML +
      `<div class="lab-sim-empty">${simData ? "该策略暂无模拟回测数据" : "暂无模拟回测数据"}</div>`;
  }
  const strat = simData.strategies[key];
  const side = strat.side;
  const pairKeys = strat.partners || [];
  if (pairKeys.length === 0) {
    return '<h3>💰 模拟回测（配对交易）</h3>' + idxBarHTML + '<div class="lab-sim-empty">暂无模拟回测数据</div>';
  }

  // 默认配对：买策略配 D1 卖，卖策略配 C1 买
  const defaultPair = side === "buy" ? "D1_high20_drop5" : "C1_RSI30";
  const initCapital = simData.initial_capital || 100000;
  const pairSideLabel = side === "buy" ? "卖点" : "买点";

  // 上区：全仓交易策略 / 下区：定额（10%）交易策略（各自独立配对切换+详情）
  const fiSection = _labSimSectionHTML("full_in", simData, key, side, pairKeys, defaultPair, initCapital, pairSideLabel);
  const fkSection = _labSimSectionHTML("fixed_10k", simData, key, side, pairKeys, defaultPair, initCapital, pairSideLabel);

  // 窗口切换 tabs（默认近1年）
  const winLabel = LAB_WIN_DEFS.find((w) => w.k === (state.labSimWindow || "y5"));
  const idxName = simData.index_name || "";
  return `<h3>💰 模拟回测（${idxName} · 配对交易）</h3>` +
    idxBarHTML +
    `<div class="lab-win-bar"><span class="lab-win-bar-label">时间窗口</span>${_labWinTabsHTML()}<span class="lab-win-bar-cur">${winLabel ? winLabel.l : ""}</span></div>` +
    fiSection + fkSection;
}

// 模拟回测卡片交互绑定（窗口切换 / per-mode 配对切换 / 交易记录折叠 / 分页）
function _labSimAttachHandlers(key, simData, simCard, rerender) {
  // 窗口切换
  simCard.querySelectorAll(".lab-win-tab").forEach((btn) => {
    btn.onclick = () => {
      state.labSimWindow = btn.dataset.win;
      // 切窗口重置分页（不同窗口交易笔数不同）
      state.labSimPageFi = 0;
      state.labSimPageFk = 0;
      rerender();
      // 同步：同时切换实验图表窗口
      if (state.labWinSync) {
        state.labChartWin = btn.dataset.win;
        const chartWinBar = document.querySelector(".lab-chart-section .lab-win-bar");
        if (chartWinBar) chartWinBar.querySelectorAll(".lab-win-tab").forEach((b) => b.classList.toggle("active", b.dataset.cwin === btn.dataset.win));
        if (state._labChartRerender) state._labChartRerender();
      }
    };
  });
  // 配对策略卡片切换（各 mode 独立）
  simCard.querySelectorAll(".lab-sim-pair-card").forEach((card) => {
    card.onclick = () => {
      const mode = card.dataset.mode;
      if (mode === "full_in") {
        state.labSimPairFi = card.dataset.pair;
        state.labSimPageFi = 0;
      } else {
        state.labSimPairFk = card.dataset.pair;
        state.labSimPageFk = 0;
      }
      rerender();
    };
  });
  // 交易记录折叠/展开（点击 header 整行）
  simCard.querySelectorAll(".lab-sim-trades-header").forEach((hdr) => {
    hdr.onclick = () => {
      const mode = hdr.dataset.mode;
      if (mode === "full_in") state.labSimFiOpen = !state.labSimFiOpen;
      else state.labSimFkOpen = !state.labSimFkOpen;
      rerender();
    };
  });
  // 分页
  simCard.querySelectorAll(".lab-sim-prev").forEach((btn) => {
    btn.onclick = () => {
      const mode = btn.dataset.mode;
      if (mode === "full_in" && (state.labSimPageFi || 0) > 0) { state.labSimPageFi--; rerender(); }
      else if (mode === "fixed_10k" && (state.labSimPageFk || 0) > 0) { state.labSimPageFk--; rerender(); }
    };
  });
  simCard.querySelectorAll(".lab-sim-next").forEach((btn) => {
    btn.onclick = () => {
      const mode = btn.dataset.mode;
      if (mode === "full_in") { state.labSimPageFi = (state.labSimPageFi || 0) + 1; rerender(); }
      else { state.labSimPageFk = (state.labSimPageFk || 0) + 1; rerender(); }
    };
  });
  // 买卖信号弹窗入口
  simCard.querySelectorAll(".lab-sim-signal-btn").forEach((btn) => {
    btn.onclick = () => _labSignalOpenModal(btn.dataset.buy, btn.dataset.sell);
  });
}

// 格式化矩阵单元格值
function _labFmt(v, isPct) {
  if (v == null || isNaN(v)) return "-";
  if (isPct) return (v * 100).toFixed(1) + "%";
  return v.toFixed(2);
}

// 渲染多周期回测矩阵（散户化：胜率/平均收益/100元换算/盈亏比/样本 + 三色分级）
function renderLabMatrix(strategyData) {
  if (!strategyData || !strategyData.periods) {
    return '<div class="lab-matrix-empty">暂无回测数据</div>';
  }
  const periods = strategyData.periods;
  let html = '<table class="lab-matrix-table"><thead><tr><th>窗口\\持有期</th>';
  LAB_HORIZONS.forEach((h) => { html += `<th>${h}</th>`; });
  html += '</tr></thead><tbody>';
  LAB_WINDOWS.forEach((w) => {
    const wp = periods[w];
    // 高亮当前选中窗口行（窗口切换按钮联动矩阵）
    const curWin = LAB_WIN_CN[state.labSimWindow || "y5"];
    const rowHi = w === curWin ? " lab-matrix-row-active" : "";
    html += `<tr class="${rowHi.trim()}"><td class="lab-matrix-rowhead">${w}</td>`;
    LAB_HORIZONS.forEach((h) => {
      const cell = wp && wp[h];
      if (!cell) {
        html += '<td class="lab-matrix-cell lab-matrix-na">-</td>';
      } else {
        const winPct = (cell.win * 100).toFixed(1) + "%";
        const pl = cell.pl.toFixed(2);
        const n = cell.n;
        const meanStr = (cell.mean > 0 ? "+" : "") + (cell.mean * 100).toFixed(1) + "%";
        const yuan100 = (100 * (1 + cell.mean)).toFixed(1);
        // 三色分级：综合 win/pl/mean
        const winLv = cell.win > 0.55 ? "good" : cell.win >= 0.45 ? "warn" : "bad";
        const plLv = cell.pl > 1.3 ? "good" : cell.pl >= 1.0 ? "warn" : "bad";
        const meanLv = cell.mean > 0 ? "good" : "bad";
        const goods = [winLv, plLv, meanLv].filter(x => x === "good").length;
        const bads = [winLv, plLv, meanLv].filter(x => x === "bad").length;
        const lvl = goods >= 2 ? "good" : bads >= 2 ? "bad" : "warn";
        // 达标边框（保留原逻辑）
        const pass = cell.win > 0.5 && cell.pl > 1;
        const cls = `lab-matrix-cell lab-matrix-${lvl}` + (pass ? " lab-matrix-pass" : "");
        html += `<td class="${cls}">` +
          `<span class="lab-mw">胜率 ${winPct}</span>` +
          `<span class="lab-mm">平均 ${meanStr}</span>` +
          `<span class="lab-my">100元→${yuan100}元</span>` +
          `<span class="lab-mp">盈亏比 ${pl}</span>` +
          `<span class="lab-mn">样本 n=${n}</span>` +
          `</td>`;
      }
    });
    html += '</tr>';
  });
  html += '</tbody></table>';
  return html;
}

// 窗口切换后同步矩阵当前行高亮（DOM 直接 toggle，无需重渲染矩阵）
function _labUpdateMatrixRowHighlight() {
  const curWin = LAB_WIN_CN[state.labSimWindow || "y5"];
  document.querySelectorAll(".lab-matrix-table tbody tr").forEach((tr) => {
    const head = tr.querySelector(".lab-matrix-rowhead");
    tr.classList.toggle("lab-matrix-row-active", !!(head && head.textContent === curWin));
  });
}

// 实验图表窗口切片：按年数截取 ohlc/指标/信号（指标在全历史算好后切片，避免预热失真）
// winKey: all/y10/y5/y3/y1。返回 {ohlc, indicators, signals}
function _labChartSlice(ohlcFull, indicators, signals, winKey) {
  if (winKey === "all" || !ohlcFull || !ohlcFull.length) {
    return { ohlc: ohlcFull, indicators, signals };
  }
  const yrMap = { y10: 10, y5: 5, y3: 3, y1: 1 };
  const yrs = yrMap[winKey];
  if (!yrs) return { ohlc: ohlcFull, indicators, signals };
  const last = ohlcFull[ohlcFull.length - 1].date;
  if (!last || last.length < 8) return { ohlc: ohlcFull, indicators, signals };
  const y = parseInt(last.substring(0, 4), 10);
  const m = parseInt(last.substring(4, 6), 10);
  const d = parseInt(last.substring(6, 8), 10);
  let cy = y - yrs, cm = m, cd = d;
  if (cm === 2 && cd === 29) cd = 28;
  const cutoff = `${cy}${String(cm).padStart(2, "0")}${String(cd).padStart(2, "0")}`;
  const startIdx = ohlcFull.findIndex((x) => x.date >= cutoff);
  const s = startIdx < 0 ? ohlcFull.length : startIdx;
  return {
    ohlc: ohlcFull.slice(s),
    indicators: indicators.map((it) => ({ ...it, data: it.data.slice(s) })),
    signals: signals.filter((x) => x.date >= cutoff),
  };
}

// 实验室自白黄块 HTML（列表页 + 详情页共用）
function _labWarningEssayHTML(status) {
  const head = status === "excluded" ? "⚠ 已排除策略 · 反面参考"
    : status === "experimental" ? "⚠ 实验中策略 · 非生产信号"
    : status === "live" ? "⚠ 生产策略 · 已上线参考"
    : status ? "⚠ 开发中策略 · 非生产信号"
    : "⚠ 候选/实验中策略非生产信号，仅供参考";
  return `<div class="lab-warning-head">${head}</div>` +
    `<p>本实验室用历史数据回测，校验网上流传的交易策略与买卖信号是否真的可靠，避免盲目跟风。我们会定期收录热门策略在此验证，表现稳健的将纳入主功能图表融合上线。</p>` +
    `<p>有好的策略建议或测试想法，欢迎抖音私信交流（抖音号：<strong>kant2218</strong>）。</p>`;
}

// 融合信号实验自白黄块
function _labFusionEssayHTML() {
  return `<div class="lab-warning-head">⚠ 融合信号实验 · 多信号共振</div>` +
    `<p>融合信号=多个单一信号同日AND触发，通过多条件共振过滤假信号、提升信号质量。本页展示从主项目提取的融合策略及实验性新组合。</p>` +
    `<p>阶段一仅展示条件描述与说明，阶段二将开放回测数据/图表/推荐榜。欢迎抖音私信交流（抖音号：<strong>kant2218</strong>）。</p>`;
}

// 渲染策略详情页
async function renderLabDetail(key, container) {
  const meta = LAB_STRATEGIES[key];
  if (!meta) { if (!container) { state.labStrategy = null; renderSignalLab(); } return; }

  const data = await fetchLabData();
  const tag = LAB_STATUS_TAGS[meta.status] || LAB_STATUS_TAGS.dev;
  const isModal = !!container;
  const target = container || content;

  target.innerHTML = "";

  // 返回按钮（弹窗模式有关闭 X，不显示返回按钮）
  if (!isModal) {
    const backBtn = document.createElement("button");
    backBtn.className = "lab-back-btn";
    backBtn.innerHTML = "← 返回策略列表";
    backBtn.onclick = () => { state.labStrategy = null; renderSignalLab(); };
    target.appendChild(backBtn);
  }

  // 标题 + 状态标签
  const header = document.createElement("div");
  header.className = "lab-detail-header";
  header.innerHTML = `<h2 class="lab-detail-title">${meta.name}</h2>` +
    `<span class="lab-tag ${tag.cls}">${tag.label}</span>` +
    `<span class="lab-tag-side">${meta.side === "buy" ? "买点" : "卖点"}</span>`;
  target.appendChild(header);

  // 实验室自白黄块（所有策略都显示，通用介绍 + 抖音号）
  const warn = document.createElement("div");
  warn.className = "lab-warning lab-warning-essay";
  warn.innerHTML = _labWarningEssayHTML(meta.status);
  target.appendChild(warn);

  // 文案区
  const docCard = document.createElement("div");
  docCard.className = "chart-card lab-doc-card";
  // 指标释义折叠：列出该策略用到的技术指标 + 散户白话（仅出图策略有指标）
  const indKeys = LAB_STRATEGY_INDICATORS[key];
  const indItems = (indKeys || []).map((k) => LAB_INDICATOR_PLAIN[k]).filter(Boolean);
  const indHtml = indItems.length
    ? '<details class="indicator-explain"><summary>📖 指标释义（这些指标怎么看？）</summary>' +
      '<div class="indicator-explain-body">' +
      indItems.map((it) => `<div><b>${it.name}</b>：${it.plain}</div>`).join("") +
      '</div></details>'
    : "";
  docCard.innerHTML =
    '<h3>📖 策略说明</h3>' +
    '<div class="lab-doc-content">' +
    `<p><b>触发逻辑：</b>${meta.trigger}</p>` +
    `<p><b>理论依据：</b>${meta.theory}</p>` +
    `<p><b>适用场景：</b>${meta.scenario}</p>` +
    `<p><b>注意事项：</b>${meta.note}</p>` +
    `<p><b>回测结论：</b>${meta.report}</p>` +
    '</div>' + indHtml;
  target.appendChild(docCard);

  // 图表区
  const chartSection = document.createElement("div");
  chartSection.className = "lab-chart-section";
  target.appendChild(chartSection);

  // 图表区：实验中策略显示指标曲线+信号标注，开发中策略显示占位
  if (LAB_CHART_KEYS[key]) {
    // 窗口切换条（独立于模拟回测窗口，默认全历史）
    if (!state.labChartWin) state.labChartWin = "y5";
    const winBar = document.createElement("div");
    winBar.className = "lab-win-bar";
    winBar.innerHTML = '<span class="lab-win-bar-label">时间窗口</span>' +
      '<div class="lab-win-tabs">' + LAB_WIN_DEFS.map((w) =>
        `<button type="button" class="lab-win-tab${w.k === state.labChartWin ? " active" : ""}" data-cwin="${w.k}">${w.l}</button>`
      ).join("") + "</div>" +
      `<button type="button" class="lab-win-sync-btn" data-tip="开启后实验图表窗口跟随模拟回测窗口联动" style="margin-left:6px;padding:2px 8px;border:1px solid var(--border);border-radius:5px;background:${state.labWinSync ? "var(--bg-hover)" : "var(--bg-card)"};color:${state.labWinSync ? "var(--text-1)" : "var(--text-3)"};font-size:12px;cursor:pointer;white-space:nowrap;${state.labWinSync ? "font-weight:600;" : ""}">🔗 同步${state.labWinSync ? "✓" : ""}</button>`;
    chartSection.appendChild(winBar);

    // 指数选择器（实验策略共用）
    const filterBar = document.createElement("div");
    filterBar.className = "filter-bar";
    const label = document.createElement("label");
    label.textContent = "选择指数";
    filterBar.appendChild(label);
    const select = document.createElement("select");
    const groups = [
      ["A股宽基", ["sh", "sz", "cyb", "csi500", "csi1000", "kc50", "hs300", "sz50"]],
      ["港股", ["hsi", "hscei", "hstech"]],
      ["美股", ["us_dji", "us_ixic", "us_spx", "us_ndx"]],
      ["红利/低波", ["div_lowvol", "csi_div", "sz_div"]],
    ];
    groups.forEach(([gname, ids]) => {
      const og = document.createElement("optgroup");
      og.label = gname;
      ids.forEach((id) => {
        const opt = document.createElement("option");
        opt.value = id;
        opt.textContent = _INDEX_NAME_MAP[id] || id;
        if (id === state.labIndex) opt.selected = true;
        og.appendChild(opt);
      });
      select.appendChild(og);
    });
    select.onchange = () => { state.labIndex = select.value; renderLabDetail(key, container); };
    filterBar.appendChild(select);
    chartSection.appendChild(filterBar);

    const chartDiv = document.createElement("div");
    chartDiv.innerHTML = '<div class="loading">加载中…</div>';
    chartSection.appendChild(chartDiv);

    try {
      const r = await fetchJSON(`./data/index/${state.labIndex}-all.json`);
      const ohlcFull = r.ohlc;
      if (!ohlcFull || !ohlcFull.length) {
        chartDiv.innerHTML = '<div class="empty-note">该指数暂无数据</div>';
      } else {
        const name = _INDEX_NAME_MAP[state.labIndex] || state.labIndex;
        // 指标/信号在全历史上算好后切片（避免窗口边界预热失真）
        const cfg = _labBuildChartConfig(key, ohlcFull, name);
        const localChart = { inst: null };
        const renderChart = () => {
          if (localChart.inst) {
            try { localChart.inst.dispose(); } catch (e) {}
            const i = charts.indexOf(localChart.inst);
            if (i >= 0) charts.splice(i, 1);
          }
          const sliced = _labChartSlice(ohlcFull, cfg.indicators, cfg.signals, state.labChartWin);
          chartDiv.innerHTML = "";
          localChart.inst = renderLabChartEx(cfg.chartTitle, sliced.ohlc, sliced.indicators, sliced.signals, chartDiv, charts, cfg.signalLabel, cfg.signalColor);
          const winLabel = (LAB_WIN_DEFS.find((w) => w.k === state.labChartWin) || {}).l || "全历史";
          const statDiv = document.createElement("div");
          statDiv.className = "lab-signal-stat";
          statDiv.innerHTML = `共触发 <b>${sliced.signals.length}</b> 个${cfg.statLabel}（${winLabel}）`;
          chartDiv.appendChild(statDiv);
        };
        renderChart();
        state._labChartRerender = renderChart;
        // 同步窗口开关
        const syncBtn = winBar.querySelector(".lab-win-sync-btn");
        if (syncBtn) {
          syncBtn.onclick = () => {
            state.labWinSync = !state.labWinSync;
            syncBtn.style.background = state.labWinSync ? "var(--bg-hover)" : "var(--bg-card)";
            syncBtn.style.color = state.labWinSync ? "var(--text-1)" : "var(--text-3)";
            syncBtn.style.fontWeight = state.labWinSync ? "600" : "normal";
            syncBtn.textContent = `🔗 同步${state.labWinSync ? "✓" : ""}`;
            if (state.labWinSync) {
              // 开启同步：chart 窗口立即跟随 sim 窗口
              state.labChartWin = state.labSimWindow || "y5";
              winBar.querySelectorAll(".lab-win-tab").forEach((b) => b.classList.toggle("active", b.dataset.cwin === state.labChartWin));
              renderChart();
            }
          };
        }
        // 窗口切换：局部刷新图表，不整页 reload
        winBar.querySelectorAll(".lab-win-tab").forEach((btn) => {
          btn.onclick = () => {
            state.labChartWin = btn.dataset.cwin;
            winBar.querySelectorAll(".lab-win-tab").forEach((b) => b.classList.toggle("active", b === btn));
            renderChart();
            // 同步：同时切换模拟回测窗口
            if (state.labWinSync) {
              state.labSimWindow = btn.dataset.cwin;
              if (state._labSimRerender) state._labSimRerender();
            }
          };
        });
      }
    } catch (e) {
      chartDiv.innerHTML = `<div class="loading">加载失败：${e}</div>`;
    }
  } else {
    // 无图策略兜底（当前22策略均有图，此处为安全网）
    chartSection.innerHTML =
      '<div class="lab-placeholder">' +
      '<div class="lab-placeholder-icon">📊</div>' +
      '<div class="lab-placeholder-text">该策略暂无图表实现</div>' +
      '<div class="lab-placeholder-sub">下方仍可看多周期回测矩阵。</div>' +
      '</div>';
  }

  // 回测区：多周期矩阵（指数切换：全市场聚合 + 8个A股宽基指数独立回测）
  const matrixCard = document.createElement("div");
  matrixCard.className = "chart-card lab-matrix-card";
  if (!state.labMatrixIdx) state.labMatrixIdx = "all";
  const _matrixIdxName = (id) => id === "all" ? "全市场" :
    (LAB_SIM_INDEXES.find((x) => x.id === id) || {}).name || id;
  const matrixIdxBtns = '<button type="button" class="lab-idx-tab' + (state.labMatrixIdx === "all" ? " active" : "") + '" data-midx="all">全市场</button>' +
    LAB_SIM_INDEXES.map((x) =>
      '<button type="button" class="lab-idx-tab' + (state.labMatrixIdx === x.id ? " active" : "") + '" data-midx="' + x.id + '">' + x.name + '</button>'
    ).join("");
  matrixCard.innerHTML =
    '<h3>📊 多周期回测矩阵</h3>' +
    '<div class="lab-win-bar"><span class="lab-win-bar-label">选择指数</span><div class="lab-win-tabs">' + matrixIdxBtns + '</div><span class="lab-win-bar-cur">' + _matrixIdxName(state.labMatrixIdx) + '</span></div>' +
    '<div class="lab-matrix-legend"><b>怎么看这张表：</b>' +
    '<span><b>胜率</b>=信号后上涨(买)/下跌(卖)概率</span>' +
    '<span><b>平均收益</b>=每次操作平均赚多少(含亏的)</span>' +
    '<span><b>盈亏比</b>=平均赚÷平均亏，&gt;1才划算</span>' +
    '<span><b>样本</b>=测试了多少次信号</span></div>' +
    '<div class="lab-matrix-tip">⚠ 以上为单次操作平均收益，非连续复利；信号触发不定期，不可直接相乘。</div>' +
    '<div class="lab-matrix-wrap"><div class="lab-matrix-loading">加载中…</div></div>' +
    '<div class="lab-matrix-foot">' +
    '<div class="lab-matrix-source">数据来源：买卖点策略深度回测（基于历史数据验证）</div>' +
    '<div class="lab-matrix-note"><b>这张表怎么测的：</b>信号触发当天按收盘价买入，持有 N 个交易日后按收盘价卖出，统计所有历史信号的平均效果。5d/10d/20d/60d = 持有 5/10/20/60 个交易日。<b>买点胜率</b>=信号后上涨占比；<b>卖点胜率</b>=信号后下跌占比（方向相反）。<b>这是单边统计</b>（每个信号独立看 N 日后涨跌），不是配对交易；真实配对实战收益见下方模拟回测。</div>' +
    '<div class="lab-matrix-legend-color"><span class="lab-matrix-good">红=好</span><span class="lab-matrix-warn">黄=一般</span><span class="lab-matrix-bad">绿=差</span></div>' +
    '</div>';
  target.appendChild(matrixCard);
  // 异步加载矩阵数据并渲染（指数切换时局部刷新）
  const matrixWrap = matrixCard.querySelector(".lab-matrix-wrap");
  const renderMatrix = async () => {
    const mIdx = state.labMatrixIdx || "all";
    const mData = await fetchLabMatrixData(mIdx);
    const mStratData = mData && mData.strategies ? mData.strategies[key] : null;
    const mGenAt = mData ? mData.generated_at : "";
    matrixWrap.innerHTML = renderLabMatrix(mStratData);
    const srcEl = matrixCard.querySelector(".lab-matrix-source");
    if (srcEl) srcEl.textContent = '数据来源：买卖点策略深度回测（' + _matrixIdxName(mIdx) + '，基于历史数据验证，重跑于 ' + (mGenAt || '2026-07-11') + '）';
    _labUpdateMatrixRowHighlight();
  };
  renderMatrix();
  matrixCard.querySelectorAll(".lab-idx-tab").forEach((btn) => {
    btn.onclick = async () => {
      state.labMatrixIdx = btn.dataset.midx;
      matrixCard.querySelectorAll(".lab-idx-tab").forEach((b) => b.classList.toggle("active", b === btn));
      const curEl = matrixCard.querySelector(".lab-win-bar-cur");
      if (curEl) curEl.textContent = _matrixIdxName(state.labMatrixIdx);
      matrixWrap.innerHTML = '<div class="lab-matrix-loading">加载中…</div>';
      await renderMatrix();
    };
  });

  // 模拟回测卡片（配对交易 + 净值曲线 + 交易记录 + 买点切换 + 模式切换 + 分页 + 指数切换）
  // lab_simulate_{index}.json 按指数拆分，前端按 state.labSimIdx 按需加载
  // 局部刷新：切指数只重渲染 simCard，不整页 reload（保留 tab/配对/模式/窗口上下文）
  state.labSimPairFi = null;
  state.labSimPairFk = null;
  state.labSimPageFi = 0;
  state.labSimPageFk = 0;
  state.labSimFiOpen = false;
  state.labSimFkOpen = false;
  if (!state.labSimIdx) state.labSimIdx = state.labIndex || "sh";
  const simCard = document.createElement("div");
  simCard.className = "chart-card lab-sim-card";
  target.appendChild(simCard);

  const renderSimCard = async () => {
    const simIdxId = state.labSimIdx || "sh";
    const simIdxName = (LAB_SIM_INDEXES.find((x) => x.id === simIdxId) || {}).name || simIdxId;
    simCard.innerHTML = `<h3>💰 模拟回测（${simIdxName} · 配对交易）</h3><div class="lab-sim-empty">⏳ 加载模拟回测数据中…</div>`;
    const simData = await fetchLabSimData(simIdxId);
    if (!simData) {
      simCard.innerHTML = `<h3>💰 模拟回测（${simIdxName} · 配对交易）</h3><div class="lab-sim-empty">模拟回测数据加载失败，请稍后重试</div>`;
      return;
    }
    const _rerenderSim = () => {
      simCard.innerHTML = _labSimCardHTML(key, simData);
      _labSimAttachHandlers(key, simData, simCard, _rerenderSim);
      // 指数切换：重置配对/分页状态后重新加载该指数数据
      simCard.querySelectorAll(".lab-idx-tab").forEach((btn) => {
        btn.onclick = () => {
          state.labSimIdx = btn.dataset.sidx;
          state.labSimPairFi = null;
          state.labSimPairFk = null;
          state.labSimPageFi = 0;
          state.labSimPageFk = 0;
          state.labSimFiOpen = false;
          state.labSimFkOpen = false;
          renderSimCard();
        };
      });
      // 窗口切换后同步矩阵行高亮（矩阵与 sim 卡片在同一详情页）
      _labUpdateMatrixRowHighlight();
    };
    state._labSimRerender = _rerenderSim;
    _rerenderSim();
    // 分阶段加载：stats 已渲染（配对卡片秒开），异步加载 full 数据后重渲染详情(trades/equity_curve)
    if (!_labSimFullLoaded(simIdxId)) {
      fetchLabSimFullData(simIdxId).then(() => _rerenderSim()).catch(() => {});
    }
  };
  await renderSimCard();
  // F5 恢复：更新 hash + 恢复滚动位置（弹窗模式跳过，弹窗本身不参与 URL 恢复）
  if (!isModal) {
    _labSetHash("#lab/" + key);
    _labRestoreScroll();
  }
}

// === 回测推荐榜（列表页底部，128组配对多维度排序 + 点击弹窗细节）===
// 数据源：lab_sim_{index}_stats.json（_full 按需合并）。新结构 pairs 按 "buyKey|sellKey" 去重存储（只存一份），
// 直接遍历 simData.pairs 即得 8买×8卖×2模式=128 组去重配对。窗口切换共用 state.labSimWindow。
const LAB_RANK_TABS = [
  { key: "composite", label: "🏆 综合推荐" },
  { key: "ret", label: "📈 收益率" },
  { key: "win", label: "🎯 胜率" },
  { key: "stable", label: "🛡 稳健(回撤小)" },
  { key: "risk_adj", label: "⚖ 风险调整" },
];

// 排行榜过滤维度（4维 min/max，留空=该边界不限制）。字段单位：均为百分比数值(如36.26=36.26%)，n_trades 为整数次数。
const LAB_RANK_FILTERS = [
  { label: "收益(%)", minKey: "retMin", maxKey: "retMax", field: "total_ret" },
  { label: "胜率(%)", minKey: "winMin", maxKey: "winMax", field: "win_rate" },
  { label: "回撤(%)", minKey: "ddMin", maxKey: "ddMax", field: "max_drawdown" },
  { label: "样本数", minKey: "nMin", maxKey: "nMax", field: "n_trades" },
];
const _LAB_FSTYLE = {
  panel: "display:flex;flex-wrap:wrap;gap:6px 10px;align-items:center;padding:8px 10px;background:var(--bg-hover);border-radius:8px;margin-bottom:8px;",
  lbl: "font-size:12px;color:var(--text-2);white-space:nowrap;display:flex;align-items:center;gap:3px;",
  input: "width:54px;padding:4px 5px;border:1px solid var(--border);border-radius:5px;font-size:12px;text-align:center;background:var(--bg-card);-webkit-appearance:none;appearance:none;-moz-appearance:textfield;",
  dash: "color:var(--text-4);font-size:11px;",
  reset: "padding:4px 12px;border:1px solid var(--border-strong);border-radius:6px;background:var(--bg-card);color:var(--text-2);font-size:12px;cursor:pointer;margin-left:auto;transition:background .15s;",
};

function _labRankDefaultFilter() {
  return { retMin: "", retMax: "", winMin: "", winMax: "", ddMin: "", ddMax: "", nMin: "", nMax: "" };
}

// 过滤：AND 组合，min/max 闭区间(>=min 且 <=max)。作用于当前窗口统计值（rows 已按 state.labSimWindow 聚合）。
function _labRankApplyFilter(rows) {
  const f = state.labRankFilter;
  if (!f) return rows;
  const has = LAB_RANK_FILTERS.some((d) => f[d.minKey] !== "" || f[d.maxKey] !== "");
  if (!has) return rows; // 过滤为空时行为与原版完全一致
  return rows.filter((r) => {
    for (const d of LAB_RANK_FILTERS) {
      const mn = f[d.minKey], mx = f[d.maxKey];
      if (mn !== "" && mn != null && r[d.field] < +mn) return false;
      if (mx !== "" && mx != null && r[d.field] > +mx) return false;
    }
    return true;
  });
}

// 过滤面板 HTML（输入框值绑 state.labRankFilter）。实时过滤只刷新结果区、不重建本面板，保留输入焦点。
function _labRankFilterHTML() {
  if (!state.labRankFilter) state.labRankFilter = _labRankDefaultFilter();
  const f = state.labRankFilter;
  const items = LAB_RANK_FILTERS.map((d) =>
    `<label style="${_LAB_FSTYLE.lbl}">${d.label}` +
    `<input type="number" class="lab-rank-finput" data-fk="${d.minKey}" placeholder="最小" value="${f[d.minKey] != null ? f[d.minKey] : ""}" style="${_LAB_FSTYLE.input}">` +
    `<span style="${_LAB_FSTYLE.dash}">~</span>` +
    `<input type="number" class="lab-rank-finput" data-fk="${d.maxKey}" placeholder="最大" value="${f[d.maxKey] != null ? f[d.maxKey] : ""}" style="${_LAB_FSTYLE.input}">` +
    `</label>`
  ).join("");
  return `<div class="lab-rank-filter" style="${_LAB_FSTYLE.panel}">` +
    `<span style="font-size:12px;color:#9c27b0;font-weight:600;white-space:nowrap;">🔍 过滤</span>` + items +
    `<button type="button" class="lab-rank-freset" style="${_LAB_FSTYLE.reset}">重置</button></div>`;
}

// 聚合128组配对 + 算综合评分与风险调整
// 新结构：simData.pairs 按 "buyKey|sellKey" 去重存储（配对只存一份），直接遍历即得 8买×8卖×2模式=128 组
// opt.experimentalOnly=true 时仅保留实验中(experimental)策略的买×卖配对（融合模式用，7买×7卖=49配对），默认 false 保持单信号原行为
function _labRankAggregate(simData, win, opt) {
  opt = opt || {};
  if (!simData || !simData.pairs) return [];
  const rows = [];
  for (const pairKey in simData.pairs) {
    const parts = pairKey.split("|");
    const bk = parts[0], sk = parts[1];
    // 融合模式：仅保留实验中(experimental)策略的买×卖配对，过滤掉已上线(live)生产策略配对
    if (opt.experimentalOnly && ((LAB_STRATEGIES[bk] || {}).status !== "experimental" || (LAB_STRATEGIES[sk] || {}).status !== "experimental")) continue;
    const pairData = simData.pairs[pairKey];
    for (const mode of ["full_in", "fixed_10k"]) {
      const wd = _labPairWinData(pairData, mode, win, simData);
      if (!wd || !wd.stats) continue;
      const s = wd.stats;
      rows.push({
        buyKey: bk, sellKey: sk, mode,
        buyName: (LAB_STRATEGIES[bk] || {}).name || bk,
        sellName: (LAB_STRATEGIES[sk] || {}).name || sk,
        modeName: mode === "full_in" ? "全仓" : "定额（10%）",
        total_ret: s.total_ret, annual_ret: s.annual_ret,
        max_drawdown: s.max_drawdown, win_rate: s.win_rate,
        n_trades: s.n_trades, years: s.years, final_total: s.final_total,
      });
    }
  }
  // 风险调整：年化/最大回撤（类 Calmar）。回撤极小且年化为正时给大值，避免除0。
  rows.forEach((r) => {
    if (r.max_drawdown > 0.5) r.risk_adj = r.annual_ret / r.max_drawdown;
    else r.risk_adj = r.annual_ret > 0 ? 999 : -999;
  });
  // 综合评分：各项 min-max 归一化到 [0,1] 后加权。norm(v)=(v-min)/(max-min)。
  // 回撤用 -max_drawdown 归一化（回撤越小→值越大→分越高）。
  const mm = (acc) => {
    const vs = rows.map(acc);
    const mn = Math.min(...vs), mx = Math.max(...vs);
    return (v) => (mx === mn ? 0.5 : (v - mn) / (mx - mn));
  };
  const nRet = mm((r) => r.total_ret);
  const nWin = mm((r) => r.win_rate);
  const nDd = mm((r) => -r.max_drawdown);
  const nN = mm((r) => r.n_trades);
  rows.forEach((r) => {
    r.score = 0.4 * nRet(r.total_ret) + 0.3 * nWin(r.win_rate) +
              0.2 * nDd(-r.max_drawdown) + 0.1 * nN(r.n_trades);
    // ⭐️进入二次测试候选筛选：综合评分top档+样本充分+回撤可控，或单项突出（胜率/风险调整）
    r.retest = (r.score >= 0.6 && r.n_trades >= 30 && r.max_drawdown <= 50) ||
               r.win_rate >= 55 || r.risk_adj >= 1.0;
  });
  return rows;
}

function _labRankSort(rows, tab) {
  const arr = rows.slice();
  if (tab === "ret") arr.sort((a, b) => b.total_ret - a.total_ret);
  else if (tab === "win") arr.sort((a, b) => b.win_rate - a.win_rate);
  else if (tab === "stable") arr.sort((a, b) => a.max_drawdown - b.max_drawdown);
  else if (tab === "risk_adj") arr.sort((a, b) => b.risk_adj - a.risk_adj);
  else arr.sort((a, b) => b.score - a.score); // composite
  return arr;
}

function _labRankItemHTML(row, rank, tab) {
  const retC = row.total_ret >= 0 ? "#c92a2a" : "#2e7d32";
  const winC = row.win_rate >= 50 ? "#c92a2a" : "#2e7d32";
  const ddC = _labDdColor(row.max_drawdown);
  const medal = rank === 1 ? "🥇" : rank === 2 ? "🥈" : rank === 3 ? "🥉" : "";
  let extra = "";
  if (tab === "composite") extra = `<span class="lab-rank-score">评分 ${(row.score * 100).toFixed(0)}</span>`;
  else if (tab === "risk_adj") extra = `<span class="lab-rank-score">${row.risk_adj >= 998 ? "∞" : row.risk_adj.toFixed(2)}</span>`;
  if (row.retest) extra += '<span class="lab-rank-retest" title="进入二次测试规则:综合评分≥0.6 且 交易≥30次 且 最大回撤≤50%,或 胜率≥55%,或 风险调整≥1.0">⭐️进入二次测试</span>';
  return `<button type="button" class="lab-rank-item clickable-card" data-buy="${row.buyKey}" data-sell="${row.sellKey}" data-mode="${row.mode}">` +
    `<span class="lab-rank-no">${medal || "#" + rank}</span>` +
    `<span class="lab-rank-name">买${row.buyName} × 卖${row.sellName} · ${row.modeName}</span>` +
    `<span class="lab-rank-stats">` +
      `<span style="color:${retC}">收益${row.total_ret > 0 ? "+" : ""}${row.total_ret}%</span>` +
      `<span style="color:${winC}">胜${row.win_rate}%</span>` +
      `<span style="${ddC}">回撤${row.max_drawdown}%</span>` +
      `<span class="lab-rank-n">n=${row.n_trades}</span>` +
    `</span>` + extra + `</button>`;
}

function _labRankHTML(simData) {
  if (!simData) return '<div class="lab-rank-empty">推荐榜数据加载失败，请稍后重试</div>';
  const win = state.labSimWindow || "y5";
  // 融合信号模式：推荐榜仅展示实验中策略的买×卖配对（7买×7卖=49配对），与左侧融合候选卡片范围一致
  const rows = _labRankAggregate(simData, win, { experimentalOnly: state.labSubMode === "fusion" });
  if (rows.length === 0) return '<div class="lab-rank-empty">暂无推荐榜数据</div>';
  state.labRankRows = rows;
  const tab = state.labRankTab || "composite";
  const tabsHTML = LAB_RANK_TABS.map((t) =>
    `<button type="button" class="lab-rank-tab${t.key === tab ? " active" : ""}" data-tab="${t.key}">${t.label}</button>`
  ).join("");
  const legend = tab === "composite"
    ? "综合评分 = 收益率(40%) + 胜率(30%) + 回撤倒数(20%) + 样本量(10%)，各项 min-max 归一化到[0,1]后加权再×100，越高越好。"
    : tab === "risk_adj"
      ? "风险调整 = 年化收益 ÷ 最大回撤（类 Calmar 比率），衡量每承担1%回撤换来多少年化收益，越高越好。"
      : tab === "stable"
        ? "稳健榜按最大回撤从小到大排序，回撤越小越稳。"
        : tab === "ret"
          ? "收益率榜按总收益率从高到低排序。"
          : "胜率榜按胜率从高到低排序。";
  return `<div class="lab-win-bar"><span class="lab-win-bar-label">时间窗口</span>${_labWinTabsHTML()}</div>` +
    `<div class="lab-rank-tabs">${tabsHTML}</div>` +
    `<div class="lab-rank-legend">${legend} 点击任意配对查看完整净值曲线与交易记录。红=好，绿=差。</div>` +
    `<div class="lab-rank-retest-rule">⭐️进入二次测试：综合评分≥0.6 且 交易≥30次 且 最大回撤≤50%，或 胜率≥55%，或 风险调整≥1.0</div>` +
    _labRankFilterHTML() +
    `<div class="lab-rank-results">${_labRankResultsHTML()}</div>`;
}

// === 二次测试 tab 渲染（分年回测 / 样本外 / 极端行情三件套）===
// 数据源 lab_retest_{index}.json，per-index 缓存到 state.labRetestDataMap
// ret/dd/win 为小数(0.xxxx)，显示时 ×100 加 %；null 显示 "-"
const _LAB_RETEST_RULE = "🔬 二次测试(稳健性验证三件套):①分年回测-防某年暴利拉高整体 ②样本外-前70%训练后30%验证防过拟合 ③极端行情-2015股灾/2018熊/2020疫情/2024反弹各regime回撤。优先做这3种因其为验证核心(通过/筛掉),成本低结论明确;其余7方向(蒙特卡洛/参数敏感/消融/手续费/多空/标的泛化)属优化/归因靠后。⭐️候选=综合分≥0.6且交易≥30且回撤≤50";

function _labRetestPct(v) {
  if (v == null) return "-";
  return (v * 100).toFixed(2) + "%";
}

function _labRetestColor(v) {
  if (v == null) return "";
  return v >= 0 ? "#c92a2a" : "#2e7d32"; // 红正绿负（A股惯例）
}

// 二次测试内容区：检查缓存，未加载显示 loading，null 显示暂无
function _labRetestContentHTML(simData) {
  const idx = (simData && simData.index_id) || (state.labSimIndex || "sh");
  const rd = state.labRetestDataMap && state.labRetestDataMap[idx];
  if (rd === undefined) {
    return `<div class="lab-retest-rule">${_LAB_RETEST_RULE}</div>` +
      '<div class="lab-rank-loading">⏳ 加载二次测试数据中…</div>';
  }
  if (rd === null) {
    return `<div class="lab-retest-rule">${_LAB_RETEST_RULE}</div>` +
      '<div class="lab-rank-empty">暂无二次测试数据</div>';
  }
  const pks = rd.pairs ? Object.keys(rd.pairs) : [];
  if (pks.length === 0) {
    return `<div class="lab-retest-rule">${_LAB_RETEST_RULE}</div>` +
      '<div class="lab-rank-empty">暂无二次测试候选配对</div>';
  }
  const pairsHTML = pks.map((pk) => _labRetestPairHTML(pk, rd.pairs[pk])).join("");
  return `<div class="lab-retest-rule">${_LAB_RETEST_RULE}</div>` +
    `<div class="lab-retest-meta">指数: ${rd.index_name || idx} · 生成: ${rd.generated_at || "-"} · 候选: ${pks.length} 个配对</div>` +
    `<div class="lab-retest-pairs">${pairsHTML}</div>`;
}

// 单个候选配对的二次测试卡片：pair_meta + 分年 + 样本外 + 极端行情
function _labRetestPairHTML(pk, pd) {
  const meta = pd.pair_meta || {};
  // 信息头
  const headHTML = '<div class="lab-retest-pair-head">' +
    `<span class="lab-retest-pair-strat">⭐️ ${_labRetestPairCN(meta.strategy || pk)}</span>` +
    `<span class="lab-retest-pair-win">窗口: ${_labRetestWinCN(meta.window)}</span>` +
    `<span>综合分: ${meta.score != null ? (meta.score * 100).toFixed(0) : "-"}</span>` +
    `<span>交易: ${meta.n != null ? meta.n : "-"}</span>` +
    `<span style="${_labDdColor(meta.dd)}">回撤: ${_labRetestPct(meta.dd)}</span>` +
    `<span style="color:${_labRetestColor(meta.win)}">胜率: ${_labRetestPct(meta.win)}</span>` +
    "</div>";

  // ① 分年回测表
  const yearly = pd.yearly || {};
  const yKeys = Object.keys(yearly).sort();
  const yRows = yKeys.length > 0 ? yKeys.map((yr) => {
    const d = yearly[yr] || {};
    return "<tr>" +
      `<td>${yr}</td>` +
      `<td style="color:${_labRetestColor(d.ret)}">${_labRetestPct(d.ret)}</td>` +
      `<td>${_labRetestPct(d.win)}</td>` +
      `<td style="${_labDdColor(d.dd)}">${_labRetestPct(d.dd)}</td>` +
      `<td>${d.n != null ? d.n : "-"}</td>` +
      "</tr>";
  }).join("") : '<tr><td colspan="5">无数据</td></tr>';
  const yearlyHTML = '<div class="lab-retest-section">' +
    '<div class="lab-retest-section-title">① 分年回测（防某年暴利拉高整体）</div>' +
    '<table class="lab-retest-yearly"><thead><tr><th>年份</th><th>收益率</th><th>胜率</th><th>回撤</th><th>交易数</th></tr></thead>' +
    `<tbody>${yRows}</tbody></table></div>`;

  // ② 样本外对比表
  const oos = pd.oos || {};
  const tr = oos.train || {}, te = oos.test || {};
  const oosRow = (label, field) => {
    const tv = tr[field], sv = te[field];
    const fmt = (v) => field === "n" ? (v != null ? v : "-") : _labRetestPct(v);
    return "<tr>" +
      `<td>${label}</td>` +
      `<td style="color:${field === "n" ? "" : _labRetestColor(tv)}">${fmt(tv)}</td>` +
      `<td style="color:${field === "n" ? "" : _labRetestColor(sv)}">${fmt(sv)}</td>` +
      "</tr>";
  };
  const oosHTML = '<div class="lab-retest-section">' +
    '<div class="lab-retest-section-title">② 样本外测试（前70%训练 → 后30%验证，防过拟合）</div>' +
    '<table class="lab-retest-oos"><thead><tr><th>指标</th><th>训练集 (train)</th><th>测试集 (test)</th></tr></thead>' +
    "<tbody>" + oosRow("收益率", "ret") + oosRow("胜率", "win") + oosRow("回撤", "dd") + oosRow("交易数", "n") + "</tbody>" +
    "</table></div>";

  // ③ 极端行情 4 regime 卡片
  const regimes = pd.regimes || {};
  const regDefs = [
    ["crash2015", "2015 股灾"],
    ["bear2018", "2018 熊市"],
    ["covid2020", "2020 疫情"],
    ["rally2024", "2024 反弹"],
  ];
  const regCards = regDefs.map(([k, label]) => {
    const r = regimes[k] || {};
    return '<div class="lab-retest-regime-card">' +
      `<div class="lab-retest-regime-name">${label}</div>` +
      `<div class="lab-retest-regime-ret" style="color:${_labRetestColor(r.ret)}">${_labRetestPct(r.ret)}</div>` +
      `<div class="lab-retest-regime-dd" style="${_labDdColor(r.dd)}">回撤 ${_labRetestPct(r.dd)}</div>` +
      "</div>";
  }).join("");
  const regimesHTML = '<div class="lab-retest-section">' +
    '<div class="lab-retest-section-title">③ 极端行情回撤（各 regime 表现）</div>' +
    `<div class="lab-retest-regimes">${regCards}</div></div>`;

  return `<div class="lab-retest-pair">${headHTML}${yearlyHTML}${oosHTML}${regimesHTML}</div>`;
}

// 结果区(数量提示+列表+更多按钮)：聚合后用 state.labRankRows，过滤->排序->分页。过滤输入时只刷新本区，不重建过滤面板(保焦点)。
function _labRankResultsHTML() {
  const rows = state.labRankRows || [];
  const tab = state.labRankTab || "composite";
  const filtered = _labRankApplyFilter(rows);
  const sorted = _labRankSort(filtered, tab);
  const showAll = !!state.labRankShowAll;
  const shown = showAll ? sorted : sorted.slice(0, 20);
  const countHTML = `<div style="font-size:12px;color:var(--text-3);margin-bottom:6px;">符合 <b style="color:#9c27b0;">${filtered.length}</b> / 共 ${rows.length} 个配对</div>`;
  const itemsHTML = shown.length > 0
    ? shown.map((r, i) => _labRankItemHTML(r, i + 1, tab)).join("")
    : '<div class="lab-rank-empty">当前过滤条件下无匹配配对</div>';
  const moreBtn = sorted.length > 20
    ? `<button type="button" class="lab-rank-more">${showAll ? "收起 ▲" : `显示全部 ${sorted.length} 组 ▼`}</button>`
    : "";
  return countHTML + `<div class="lab-rank-list">${itemsHTML}</div>` + moreBtn;
}

function _labRankAttachHandlers(section, simData) {
  // 窗口切换
  section.querySelectorAll(".lab-win-tab").forEach((btn) => {
    btn.onclick = () => { state.labSimWindow = btn.dataset.win; _labRankRerender(section, simData); };
  });
  section.querySelectorAll(".lab-rank-tab").forEach((btn) => {
    btn.onclick = () => { state.labRankTab = btn.dataset.tab; state.labRankShowAll = false; _labRankRerender(section, simData); };
  });
  // 过滤输入：实时过滤（只刷新结果区，保留输入焦点不重建面板）
  section.querySelectorAll(".lab-rank-finput").forEach((inp) => {
    let _labFilterTimer;
    inp.addEventListener("input", () => {
      if (!state.labRankFilter) state.labRankFilter = _labRankDefaultFilter();
      state.labRankFilter[inp.dataset.fk] = inp.value;
      state.labRankShowAll = false;
      clearTimeout(_labFilterTimer);
      _labFilterTimer = setTimeout(() => _labRankRerenderResults(section, simData), 100);
    });
  });
  const reset = section.querySelector(".lab-rank-freset");
  if (reset) reset.onclick = () => {
    state.labRankFilter = _labRankDefaultFilter();
    state.labRankShowAll = false;
    _labRankRerender(section, simData); // 重置需重建面板清空输入框
  };
  // 列表项 + 更多按钮（结果区内部）
  _labRankAttachResultsHandlers(section, simData);
}

// 结果区事件绑定（列表项点击+更多按钮）。全量重渲染和仅结果重渲染都调用本函数。
function _labRankAttachResultsHandlers(section, simData) {
  section.querySelectorAll(".lab-rank-item").forEach((item) => {
    item.onclick = () => _labRankOpenModal(simData, item.dataset.buy, item.dataset.sell, item.dataset.mode);
  });
  const more = section.querySelector(".lab-rank-more");
  if (more) more.onclick = () => { state.labRankShowAll = !state.labRankShowAll; _labRankRerenderResults(section, simData); };
}

// 仅刷新结果区(过滤输入/更多按钮)：不重建过滤面板，输入焦点不丢失
function _labRankRerenderResults(section, simData) {
  const res = section.querySelector(".lab-rank-results");
  if (!res) return;
  res.innerHTML = _labRankResultsHTML();
  _labRankAttachResultsHandlers(section, simData);
}

function _labRankRerender(section, simData) {
  const body = section.querySelector(".lab-rank-body");
  if (body) body.innerHTML = _labRankHTML(simData);
  _labRankAttachHandlers(section, simData);
}

// 推荐榜弹窗：复用 _labSimModeBlock 渲染 4数字+净值曲线+交易记录
function _labRankOpenModal(simData, buyKey, sellKey, mode) {
  let overlay = document.getElementById("labRankOverlay");
  if (!overlay) {
    overlay = document.createElement("div");
    overlay.id = "labRankOverlay";
    overlay.className = "lab-rank-overlay";
    document.body.appendChild(overlay);
  }
  state.labRankModal = { buyKey, sellKey, mode, page: 0, open: true };
  _labRankModalRender(overlay, simData);
  overlay.classList.add("show");
  document.body.style.overflow = "hidden";
  overlay.onclick = (e) => { if (e.target === overlay) _labRankCloseModal(); };
  // 详情需 full 数据(trades/equity_curve)，未加载则按需加载（带进度条）并重渲染
  const idx = (simData && simData.index_id) || (state.labSimIndex || "sh");
  if (!_labSimFullLoaded(idx)) _labRankEnsureFull(overlay, simData, idx);
}

// 弹窗内按需加载 full 数据：更新 loading 占位为进度条，加载完重渲染
async function _labRankEnsureFull(overlay, simData, idx) {
  const setProg = (pct) => {
    const el = overlay.querySelector(".lab-sim-full-loading");
    if (!el) return;
    if (pct < 0) { el.textContent = "⏳ 加载明细数据中…"; return; }
    el.innerHTML = `⏳ 加载明细数据中… ${pct}%<div class="lab-full-prog"><div style="width:${pct}%"></div></div>`;
  };
  // 超时取消：15s 后 abort 请求并显示重试按钮
  const controller = new AbortController();
  let timedOut = false;
  const slowTimer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, 15000);
  try {
    await fetchLabSimFullData(idx, (received, total) => {
      setProg(total > 0 ? Math.round(received / total * 100) : -1);
    }, controller.signal);
  } finally {
    clearTimeout(slowTimer);
  }
  // 加载成功则重渲染弹窗；失败/超时则显示重试按钮
  if (_labSimFullLoaded(idx)) {
    if (state.labRankModal) _labRankModalRender(overlay, simData);
  } else {
    const el = overlay.querySelector(".lab-sim-full-loading");
    if (el) {
      el.innerHTML = `<span>${timedOut ? "⏳ 加载超时" : "⚠ 加载失败"}</span> ` +
        `<button type="button" class="lab-full-retry" style="margin-left:8px;padding:3px 12px;border:1px solid var(--border-strong);border-radius:5px;background:var(--bg-card);color:var(--text-1);font-size:12px;cursor:pointer;">重试</button>`;
      const retryBtn = el.querySelector(".lab-full-retry");
      if (retryBtn) retryBtn.onclick = () => _labRankEnsureFull(overlay, simData, idx);
    }
  }
}

function _labRankCloseModal() {
  const overlay = document.getElementById("labRankOverlay");
  if (overlay) { overlay.classList.remove("show"); overlay.innerHTML = ""; overlay.onclick = null; }
  document.body.style.overflow = "";
  state.labRankModal = null;
}

function _labRankModalRender(overlay, simData) {
  const m = state.labRankModal;
  if (!m) return;
  const win = state.labSimWindow || "y5";
  const pairData = _labGetPair(simData, m.buyKey, m.sellKey);
  const winData = _labPairWinData(pairData, m.mode, win, simData);
  const buyName = (LAB_STRATEGIES[m.buyKey] || {}).name || m.buyKey;
  const sellName = (LAB_STRATEGIES[m.sellKey] || {}).name || m.sellKey;
  const modeName = m.mode === "full_in" ? "全仓" : "定额（10%）";
  const winLabel = (LAB_WIN_DEFS.find((w) => w.k === win) || {}).l || "";
  const initCapital = simData.initial_capital || 100000;
  let bodyHTML;
  if (!winData || !winData.stats) {
    bodyHTML = '<div class="lab-rank-modal-empty">该配对无交易数据</div>';
  } else {
    // 同步 page 到有效范围（_labSimModeBlock 内部也会 clamp，此处保持 state 一致）
    const trades = winData.trades || [];
    const totalPages = Math.max(1, Math.ceil(trades.length / 20));
    if (m.page > totalPages - 1) m.page = totalPages - 1;
    if (m.page < 0) m.page = 0;
    bodyHTML = _labSimModeBlock(m.mode, winData, initCapital, m.page, m.open);
  }
  overlay.innerHTML = `<div class="lab-rank-modal">` +
    `<div class="lab-rank-modal-head">` +
    `<span class="lab-rank-modal-title">买${buyName} × 卖${sellName} · ${modeName}（${winLabel}）</span>` +
    `<button type="button" class="lab-rank-modal-close" aria-label="关闭">✕</button>` +
    `</div>` +
    `<div class="lab-rank-modal-body">${bodyHTML}</div>` +
    `</div>`;
  overlay.querySelector(".lab-rank-modal-close").onclick = _labRankCloseModal;
  const hdr = overlay.querySelector(".lab-sim-trades-header");
  if (hdr) hdr.onclick = () => { m.open = !m.open; _labRankModalRender(overlay, simData); };
  const prev = overlay.querySelector(".lab-sim-prev");
  if (prev) prev.onclick = () => { if (m.page > 0) { m.page--; _labRankModalRender(overlay, simData); } };
  const next = overlay.querySelector(".lab-sim-next");
  if (next && !next.disabled) next.onclick = () => { m.page++; _labRankModalRender(overlay, simData); };
}

// === 买卖信号弹窗：配对详情入口，显示买/卖策略图表+品类切换 ===
function _labSignalOpenModal(buyKey, sellKey) {
  let overlay = document.getElementById("labSignalOverlay");
  if (!overlay) {
    overlay = document.createElement("div");
    overlay.id = "labSignalOverlay";
    overlay.className = "lab-signal-overlay";
    document.body.appendChild(overlay);
  }
  // 同步外部选择：指数取模拟回测 labSimIdx（信号按钮在 sim 卡片内）+ 窗口取 labSimWindow
  state.labSignalModal = {
    buyKey, sellKey,
    index: state.labSimIdx || state.labIndex || "sh",
    win: state.labSimWindow || "y5",
    charts: [],
  };
  _labSignalModalRender(overlay);
  overlay.classList.add("show");
  document.body.style.overflow = "hidden";
  overlay.onclick = (e) => { if (e.target === overlay) _labSignalCloseModal(); };
}

function _labSignalCloseModal() {
  const overlay = document.getElementById("labSignalOverlay");
  if (overlay) { overlay.classList.remove("show"); overlay.innerHTML = ""; overlay.onclick = null; }
  document.body.style.overflow = "";
  if (state.labSignalModal && state.labSignalModal.charts) {
    state.labSignalModal.charts.forEach((c) => { try { c.dispose(); } catch (e) {} });
  }
  state.labSignalModal = null;
}

// 买卖信号弹窗窗口切片：根据全历史 ohlc 末日回推 N 年，返回 YYYYMMDD 截止日（含）
// winKey: all/y10/y5/y3/y1。all 返回 null（不过滤）。ohlc 末日为YYYYMMDD字符串。
function _labSignalCutoffDate(ohlc, winKey) {
  if (!ohlc || !ohlc.length || winKey === "all") return null;
  const last = ohlc[ohlc.length - 1].date;
  if (!last || last.length < 8) return null;
  const y = parseInt(last.substring(0, 4), 10);
  const m = parseInt(last.substring(4, 6), 10);
  const d = parseInt(last.substring(6, 8), 10);
  const yrMap = { y10: 10, y5: 5, y3: 3, y1: 1 };
  const yrs = yrMap[winKey];
  if (!yrs) return null;
  let cy = y - yrs, cm = m, cd = d;
  if (cm === 2 && cd === 29) cd = 28; // 闰日简化
  return `${cy}${String(cm).padStart(2, "0")}${String(cd).padStart(2, "0")}`;
}

async function _labSignalModalRender(overlay) {
  const m = state.labSignalModal;
  if (!m) return;
  const buyName = (LAB_STRATEGIES[m.buyKey] || {}).name || m.buyKey;
  const sellName = (LAB_STRATEGIES[m.sellKey] || {}).name || m.sellKey;
  const buyHasChart = !!LAB_CHART_KEYS[m.buyKey];
  const sellHasChart = !!LAB_CHART_KEYS[m.sellKey];

  // 指数选择器 options
  const groups = [
    ["A股宽基", ["sh", "sz", "cyb", "csi500", "csi1000", "kc50", "hs300", "sz50"]],
    ["港股", ["hsi", "hscei", "hstech"]],
    ["美股", ["us_dji", "us_ixic", "us_spx", "us_ndx"]],
    ["红利/低波", ["div_lowvol", "csi_div", "sz_div"]],
  ];
  const selectHTML = groups.map(([gname, ids]) =>
    `<optgroup label="${gname}">` +
    ids.map((id) => `<option value="${id}"${id === m.index ? " selected" : ""}>${_INDEX_NAME_MAP[id] || id}</option>`).join("") +
    `</optgroup>`
  ).join("");

  const win = m.win || "y1";
  const periodBtnsHTML = LAB_WIN_DEFS.map((w) =>
    `<button type="button" class="lab-signal-period-btn${w.k === win ? " active" : ""}" data-win="${w.k}">${w.l}</button>`
  ).join("");

  overlay.innerHTML = `<div class="lab-signal-modal">` +
    `<div class="lab-signal-modal-head">` +
    `<span class="lab-signal-modal-title">📊 买卖信号 · 买${buyName} × 卖${sellName}</span>` +
    `<button type="button" class="lab-rank-modal-close" aria-label="关闭">✕</button>` +
    `</div>` +
    `<div class="lab-signal-modal-body">` +
    `<div class="lab-signal-filter"><label>选择指数</label><select class="lab-signal-index">${selectHTML}</select>` +
    `<span class="lab-signal-period">${periodBtnsHTML}</span>` +
    `<span class="lab-signal-legend"><i style="background:#c92a2a"></i>买信号${buyHasChart ? "" : "(无图)"}<i style="background:#2e7d32"></i>卖信号${sellHasChart ? "" : "(无图)"}</span>` +
    `</div>` +
    `<div class="lab-signal-chart-area"><div class="loading">加载中…</div></div>` +
    `</div></div>`;

  overlay.querySelector(".lab-rank-modal-close").onclick = _labSignalCloseModal;
  overlay.querySelector(".lab-signal-index").onchange = (e) => { m.index = e.target.value; _labSignalModalRender(overlay); };
  overlay.querySelectorAll(".lab-signal-period-btn").forEach((b) => {
    b.onclick = () => { m.win = b.dataset.win; _labSignalModalRender(overlay); };
  });

  // 释放旧图表
  if (m.charts) m.charts.forEach((c) => { try { c.dispose(); } catch (e) {} });
  m.charts = [];

  const chartArea = overlay.querySelector(".lab-signal-chart-area");
  if (!buyHasChart && !sellHasChart) {
    chartArea.innerHTML = '<div class="lab-signal-no-chart">🔧 买卖策略图表均开发中</div>';
    return;
  }
  try {
    // 按窗口传 range 减少下载：取比窗口大一档作指标预热缓冲（最长MA60≈60根），
    // 再由下方 cutoff 切到目标窗口。y10/all 无对应 range 用 all。
    // 静态版无 ranged JSON 固定取 -all.json 由 cutoff 前端切（全历史预热正确）。
    const apiRange = ({ y1: "3y", y3: "5y", y5: "5y", y10: "all", all: "all" }[win]) || "all";
    const r = await fetchJSON(`./data/index/${m.index}-all.json`);
    const ohlcFull = r.ohlc;
    if (!ohlcFull || !ohlcFull.length) {
      chartArea.innerHTML = '<div class="lab-signal-no-chart">该指数暂无数据</div>';
      return;
    }
    const indexName = _INDEX_NAME_MAP[m.index] || m.index;
    // 在全历史 ohlc 上分别构建买/卖配置（指标预热正确），再合并到一张图
    const buyCfg = buyHasChart ? _labBuildChartConfig(m.buyKey, ohlcFull, indexName) : null;
    const sellCfg = sellHasChart ? _labBuildChartConfig(m.sellKey, ohlcFull, indexName) : null;

    // 合并指标线（按 name 去重，避免 BB 双轨重复绘制）
    const indMap = new Map();
    [buyCfg, sellCfg].forEach((cfg) => {
      if (!cfg) return;
      cfg.indicators.forEach((it) => { if (!indMap.has(it.name)) indMap.set(it.name, it); });
    });
    const indicators = Array.from(indMap.values());

    // 合并信号：买=红 / 卖=绿（A股习惯），每个信号带 color+label 供 renderLabChartEx 逐点着色
    const BUY_COLOR = "#c92a2a", SELL_COLOR = "#2e7d32";
    const buySigs = ((buyCfg && buyCfg.signals) || []).map((s) => ({ date: s.date, close: s.close, color: BUY_COLOR, label: "买" }));
    const sellSigs = ((sellCfg && sellCfg.signals) || []).map((s) => ({ date: s.date, close: s.close, color: SELL_COLOR, label: "卖" }));
    const allSignals = buySigs.concat(sellSigs).sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));

    // 按窗口切片 ohlc + 指标 + 信号（指标在全历史算好后切片，避免窗口边界预热失真）
    const cutoff = _labSignalCutoffDate(ohlcFull, win);
    let ohlc = ohlcFull, slicedInd = indicators, sigs = allSignals;
    if (cutoff) {
      const startIdx = ohlcFull.findIndex((d) => d.date >= cutoff);
      const s = startIdx < 0 ? ohlcFull.length : startIdx;
      ohlc = ohlcFull.slice(s);
      slicedInd = indicators.map((it) => ({ ...it, data: it.data.slice(s) }));
      sigs = allSignals.filter((x) => x.date >= cutoff);
    }

    if (!ohlc.length) {
      chartArea.innerHTML = '<div class="lab-signal-no-chart">该周期内无数据</div>';
      return;
    }

    const winLabel = LAB_WIN_CN[win] || "近1年";
    const title = `${indexName} · 买卖信号（${winLabel}）`;
    chartArea.innerHTML = "";
    renderLabChartEx(title, ohlc, slicedInd, sigs, chartArea, m.charts, "信号", "#9c27b0");
    const buyCnt = sigs.filter((x) => x.color === BUY_COLOR).length;
    const sellCnt = sigs.filter((x) => x.color === SELL_COLOR).length;
    const statDiv = document.createElement("div");
    statDiv.className = "lab-signal-stat";
    statDiv.innerHTML = `${winLabel}触发：<b style="color:${BUY_COLOR}">买 ${buyCnt}</b> · <b style="color:${SELL_COLOR}">卖 ${sellCnt}</b>`;
    chartArea.appendChild(statDiv);
  } catch (e) {
    chartArea.innerHTML = `<div class="loading">加载失败：${e}</div>`;
  }
}

// ESC 关闭弹窗
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    const ov = document.getElementById("labRankOverlay");
    if (ov && ov.classList.contains("show")) _labRankCloseModal();
    const sv = document.getElementById("labSignalOverlay");
    if (sv && sv.classList.contains("show")) _labSignalCloseModal();
    const fv = document.getElementById("labFusionPairOverlay");
    if (fv && fv.classList.contains("show")) _labFusionPairCloseModal();
    const rv = document.getElementById("labRetestPairOverlay");
    if (rv && rv.classList.contains("show")) _labRetestPairCloseModal();
    const dv = document.getElementById("labSignalDetailOverlay");
    if (dv && dv.classList.contains("show")) _labSignalDetailCloseModal();
  }
});

// 渲染策略实验室主入口（分区tab + 卡片列表 / 详情页）
// === 二级导航（单一信号实验 / 融合信号实验）===
function _renderLabSubNav() {
  const cur = state.labSubMode || "single";
  const subNav = document.createElement("div");
  subNav.className = "lab-subnav";
  const _LAB_SUB_TABS = [
    { key: "single", label: "单一信号实验" },
    { key: "fusion", label: "融合信号实验" },
    { key: "retest", label: "🔬 二次测试实验" },
  ];
  subNav.innerHTML = _LAB_SUB_TABS.map((t) =>
    `<button type="button" class="lab-subnav-tab${cur === t.key ? " active" : ""}" data-sub="${t.key}">${t.label}</button>`
  ).join("");
  subNav.querySelectorAll(".lab-subnav-tab").forEach((btn) => {
    btn.onclick = () => {
      state.labSubMode = btn.dataset.sub;
      state.labStrategy = null; // 切换模式时清空策略选择，避免串模式
      renderSignalLab();
    };
  });
  content.appendChild(subNav);
}

// === 融合信号列表页（阶段一：仅展示元数据，不跑回测）===
async function renderFusionLab() {
  // 左右2栏布局：融合策略卡左 + 回测推荐榜右（照搬 renderSignalLab 列表页 .lab-list-2col 模式）
  const wrapper = document.createElement("div");
  wrapper.className = "lab-list-2col";
  const leftCol = document.createElement("div");
  const rightCol = document.createElement("div");

  // 实验室自白黄块
  const essayWarn = document.createElement("div");
  essayWarn.className = "lab-warning lab-warning-essay";
  essayWarn.innerHTML = _labFusionEssayHTML();
  leftCol.appendChild(essayWarn);

  // 分区 tab
  const curZone = state.labFusionZone || "prod";
  const zoneTabs = document.createElement("div");
  zoneTabs.className = "lab-zone-tabs";
  LAB_FUSION_ZONES.forEach((z) => {
    const btn = document.createElement("button");
    btn.className = "lab-zone-tab" + (curZone === z.key ? " active" : "");
    btn.innerHTML = `${z.label} <span class="lab-zone-count">${z.count}</span>`;
    btn.onclick = () => { state.labFusionZone = z.key; renderSignalLab(); };
    zoneTabs.appendChild(btn);
  });
  leftCol.appendChild(zoneTabs);

  // 搜索框（按策略名/条件/触发条件模糊过滤卡片列表，大小写不敏感）
  const searchWrap = document.createElement("div");
  searchWrap.className = "lab-fusion-search-wrap";
  searchWrap.innerHTML = '<input type="text" class="lab-fusion-search" placeholder="搜索策略名/条件…" autocomplete="off">';
  leftCol.appendChild(searchWrap);

  // 分区描述
  const zMeta = LAB_FUSION_ZONES.find((z) => z.key === curZone) || LAB_FUSION_ZONES[0];
  const zoneDesc = document.createElement("div");
  zoneDesc.className = "lab-zone-desc";
  zoneDesc.textContent = zMeta.desc;
  leftCol.appendChild(zoneDesc);

  // 策略卡片列表：硬编码在前，候选在后
  const list = document.createElement("div");
  list.className = "lab-strategy-list";
  const hardcodedStrategies = Object.entries(LAB_FUSION_STRATEGIES).filter(([k, v]) => v.zone === curZone);
  const pendingStrategies = Object.entries(LAB_FUSION_PENDING).filter(([k, v]) => v.zone === curZone);
  const zoneStrategies = [...hardcodedStrategies, ...pendingStrategies];
  if (zoneStrategies.length === 0) {
    list.innerHTML = '<div class="lab-fusion-empty">暂无融合信号</div>';
  } else {
    zoneStrategies.forEach(([key, meta]) => {
      const tag = LAB_STATUS_TAGS[meta.status] || LAB_STATUS_TAGS.dev;
      const condsHTML = (meta.conditions && meta.conditions.length)
        ? `<div class="lab-fusion-conditions"><span class="lab-fusion-cond-label">组成条件</span>` +
          meta.conditions.map((c) => `<span class="lab-fusion-cond">${c}</span>`).join("") +
          `</div>`
        : "";
      const card = document.createElement("div");
      card.className = "lab-strategy-card lab-fusion-card" + (meta._isPending ? " lab-fusion-pending" : "");
      card.innerHTML =
        `<div class="lab-card-top">` +
        `<span class="lab-card-name">${meta.name}</span>` +
        `<span class="lab-tag ${tag.cls}">${tag.label}</span>` +
        `</div>` +
        condsHTML +
        `<div class="lab-card-trigger">${meta.trigger}</div>` +
        `<div class="lab-card-conclusion">${meta.conclusion}</div>` +
        (meta._pairType === "buy_sell"
          ? `<div class="lab-fusion-pair-hint">📊 点击查看配对回测（胜率·收益·5窗口）▸</div>`
          : "");
      if (meta._pairType === "buy_sell") {
        card.classList.add("lab-fusion-clickable");
        card.title = "点击查看配对回测（胜率/收益/5窗口）";
      } else {
        card.title = "同向共振回测开发中，点击查看说明";
      }
      card.onclick = () => { _labFusionPairOpenModal(meta); };
      list.appendChild(card);
    });
  }
  leftCol.appendChild(list);

  // 阶段提示
  const phaseNote = document.createElement("div");
  phaseNote.className = "lab-fusion-phase-note";
  phaseNote.innerHTML = "📌 <b>买×卖配对</b>候选已接入回测数据（点击卡片查看胜率/收益/5窗口）。<b>同向共振</b>（买×买/卖×卖）回测开发中。";
  leftCol.appendChild(phaseNote);

  // 搜索框事件：按卡片可见文本模糊过滤（大小写不敏感，匹配 name/conditions/trigger/conclusion）
  const searchInput = searchWrap.querySelector(".lab-fusion-search");
  searchInput.addEventListener("input", () => {
    const q = searchInput.value.trim().toLowerCase();
    const cards = list.querySelectorAll(".lab-strategy-card");
    cards.forEach((card) => {
      if (!q) { card.style.display = ""; return; }
      card.style.display = card.textContent.toLowerCase().includes(q) ? "" : "none";
    });
  });

  // 回测推荐榜（右栏，照搬 renderSignalLab 列表页推荐榜结构：指数选择器+排序tab+过滤+body）
  const rankSection = document.createElement("div");
  rankSection.className = "chart-card lab-rank-card";
  const _curIdx = state.labSimIndex || "sh";
  const rankIdxBtns = LAB_SIM_INDEXES.map((x) =>
    `<button type="button" class="lab-idx-tab${x.id === _curIdx ? " active" : ""}" data-idx="${x.id}">${x.name}</button>`
  ).join("");
  rankSection.innerHTML = '<h3>🏆 回测推荐榜</h3>' +
    `<div class="lab-win-bar"><span class="lab-win-bar-label">选择指数</span><div class="lab-win-tabs">${rankIdxBtns}</div></div>` +
    '<div class="lab-rank-body"><div class="lab-rank-loading">⏳ 加载推荐榜数据中…</div></div>';
  rightCol.appendChild(rankSection);
  // 组装2栏
  wrapper.appendChild(leftCol);
  wrapper.appendChild(rightCol);
  content.appendChild(wrapper);
  // 加载推荐榜数据（融合模式：_labRankHTML 依 state.labSubMode==='fusion' 仅展示实验中策略买×卖配对）
  const _loadRank = async () => {
    const idx = state.labSimIndex || "sh";
    const simData = await fetchLabSimData(idx);
    _labRankRerender(rankSection, simData);
  };
  _loadRank();
  // 指数切换：切换 active 按钮，重新加载该指数数据并重渲染 rank body
  rankSection.querySelectorAll(".lab-idx-tab").forEach((btn) => {
    btn.onclick = () => {
      state.labSimIndex = btn.dataset.idx;
      state.labRankShowAll = false;
      rankSection.querySelectorAll(".lab-idx-tab").forEach((b) => b.classList.toggle("active", b === btn));
      const body = rankSection.querySelector(".lab-rank-body");
      if (body) body.innerHTML = '<div class="lab-rank-loading">⏳ 加载中…</div>';
      _loadRank();
    };
  });
}

// === 二次测试实验分区（照抄融合信号区布局：左配对卡片 + 右维度排行榜）===
// 数据源 lab_retest_{index}.json，per-index 缓存到 state.labRetestDataMap（fetchLabRetestData）
// pairs{"buyKey|sellKey":{pair_meta:{strategy(英文pk|pk),window,score,n,dd,win,ret 全小数×100%},yearly,oos,regimes}}

// 英文名词中文化：meta.strategy("BB_lower_revert|BB_upper_revert") -> "买布林下轨回归买 × 卖布林上轨回落卖"
// 复用 LAB_STRATEGIES[k].name（已含买/卖字样），映射不到保留原英文并 console.warn
function _labRetestPairCN(strategy) {
  if (!strategy) return "-";
  const parts = strategy.split("|");
  const bk = parts[0], sk = parts[1];
  const bm = LAB_STRATEGIES[bk];
  const sm = LAB_STRATEGIES[sk];
  if (!bm) console.warn("retest 中文化:未知买策略 key", bk);
  if (!sm) console.warn("retest 中文化:未知卖策略 key", sk);
  return `买${(bm && bm.name) || bk} × 卖${(sm && sm.name) || sk}`;
}

// meta.window("y5"等) -> 中文窗口名（复用 LAB_WIN_CN）
function _labRetestWinCN(win) {
  const cn = LAB_WIN_CN[win];
  if (!cn && win) console.warn("retest 中文化:未知窗口 key", win);
  return cn || win || "-";
}

// retest 维度榜 tabs（8维：综合1 + 整体4 + 二次测试3。整体4维支持5窗口切换，二次测试3维窗口无关）
const LAB_RETEST_RANK_TABS = [
  { key: "score", label: "🏆综合(二次)" },
  { key: "ret", label: "📈收益率" },
  { key: "win", label: "🎯胜率" },
  { key: "dd", label: "🛡稳健" },
  { key: "n", label: "📊样本量" },
  { key: "yearly", label: "📅分年" },
  { key: "oos", label: "🔬样本外" },
  { key: "regimes", label: "⚡极端行情" },
];

// min-max 归一化工厂：返回 fn(v)->0~1。null/NaN 返回 0.5（中性，不奖惩缺失数据）。
// 调用方按方向使用：正向（越大越好）直接 norm；负向（越小越好，如回撤/波动/过拟合）用 1-norm。
function _labRetestMinMax(rows, key) {
  const vals = rows.map((r) => r[key]).filter((v) => v != null && !isNaN(v));
  if (vals.length === 0) return () => 0.5;
  const mn = Math.min.apply(null, vals);
  const mx = Math.max.apply(null, vals);
  const rng = mx - mn;
  return (v) => (v == null || isNaN(v)) ? 0.5 : (rng === 0 ? 0.5 : (v - mn) / rng);
}

// 聚合 retest pairs -> 行：算8维指标（归一化 across 该指数所有 pair）+ 各综合分。
// pair_meta 全小数（0.27=27%），显示时×100%。归一化在同一指数内所有 pair 一起算 min/max。
function _labRetestRankRows(rd, simData, winKey) {
  if (!rd || !rd.pairs) return [];
  const pks = Object.keys(rd.pairs);
  const wk = winKey || "y5"; // 5窗口切换：默认 y5（与 retest 后端窗口一致）
  // Pass1：收集每对原始指标
  const raw = pks.map((pk) => {
    const pd = rd.pairs[pk] || {};
    const meta = pd.pair_meta || {};
    // 整体4维(ret/win/dd/n)：优先用单信号 simData 该窗口 stats（支持5窗口切换）；
    // simData 缺失或该窗口无数据时回退 pair_meta（后端 y5 full_in 值）。
    // 单信号 stats 为百分数(10.87)，pair_meta 为小数(0.1087)，统一为小数。
    let ret = meta.ret != null ? meta.ret : 0;
    let winRate = meta.win != null ? meta.win : 0;
    let dd = meta.dd != null ? meta.dd : 0;
    let n = meta.n != null ? meta.n : 0;
    if (simData && meta.strategy) {
      const parts = meta.strategy.split("|");
      const pd2 = _labGetPair(simData, parts[0], parts[1]);
      const s = pd2 && pd2.full_in && pd2.full_in.stats && pd2.full_in.stats[wk];
      if (s) {
        ret = s.total_ret / 100;
        winRate = s.win_rate / 100;
        dd = s.max_drawdown / 100;
        n = s.n_trades;
      }
    }
    const yearly = pd.yearly || {};
    const yKeys = Object.keys(yearly).sort();
    const yearRets = yKeys.map((yr) => yearly[yr] && yearly[yr].ret).filter((v) => v != null);
    const minYearRet = yearRets.length ? Math.min.apply(null, yearRets) : 0; // 最差年收益
    const profitYears = yearRets.filter((v) => v > 0).length;
    const profitYearRatio = yearRets.length ? profitYears / yearRets.length : 0; // 盈利年占比(0-1不归一)
    let yearVol = 0; // 逐年收益标准差
    if (yearRets.length > 1) {
      const mean = yearRets.reduce((a, b) => a + b, 0) / yearRets.length;
      yearVol = Math.sqrt(yearRets.reduce((a, b) => a + (b - mean) * (b - mean), 0) / yearRets.length);
    }
    const oos = pd.oos || {};
    const tr = oos.train || {}, te = oos.test || {};
    const testRet = te.ret != null ? te.ret : 0;
    const overfit = (tr.ret != null && te.ret != null) ? Math.abs(tr.ret - te.ret) : 0; // 过拟合度
    const testWin = te.win != null ? te.win : 0;
    const regimes = pd.regimes || {};
    const crash = regimes.crash2015 || null;
    const bear = regimes.bear2018 || null;
    const rally = regimes.rally2024 || null;
    const covid = regimes.covid2020 || null; // null=无交易
    // 小样本标注：某年 n<3 或 oos test n<10
    const yearSmall = yKeys.some((yr) => yearly[yr] && yearly[yr].n != null && yearly[yr].n < 3);
    const oosSmall = (te.n != null && te.n < 10);
    return {
      pk,
      strategy: meta.strategy || pk,
      window: meta.window || "-",
      cn: _labRetestPairCN(meta.strategy || pk),
      winCn: _labRetestWinCN(meta.window),
      modeCn: "全仓", // retest 后端用 full_in 跑二次测试（pair_meta 无 mode 字段）
      // 整体原始（5窗口切换时取自单信号 simData stats[wk]，默认 y5 与 pair_meta 一致）
      ret,
      win: winRate,
      dd,
      n,
      // 分年原始
      minYearRet, profitYearRatio, yearVol, profitYears, yearCount: yearRets.length,
      // 样本外原始
      testRet, overfit, testWin,
      // 极端原始（null=缺失）
      crashDd: crash ? crash.dd : null,
      bearDd: bear ? bear.dd : null,
      rallyRet: rally ? rally.ret : null,
      covidDd: covid ? covid.dd : null,
      covidNull: !covid,
      // 小样本
      yearSmall, oosSmall,
    };
  });
  // Pass2：各指标 min-max 归一（across 该指数所有 pair）
  const retN = _labRetestMinMax(raw, "ret");
  const winN = _labRetestMinMax(raw, "win");
  const ddN = _labRetestMinMax(raw, "dd");
  const nN = _labRetestMinMax(raw, "n");
  const minYearRetN = _labRetestMinMax(raw, "minYearRet");
  const yearVolN = _labRetestMinMax(raw, "yearVol");
  const testRetN = _labRetestMinMax(raw, "testRet");
  const overfitN = _labRetestMinMax(raw, "overfit");
  const testWinN = _labRetestMinMax(raw, "testWin");
  const crashDdN = _labRetestMinMax(raw, "crashDd");
  const bearDdN = _labRetestMinMax(raw, "bearDd");
  const rallyRetN = _labRetestMinMax(raw, "rallyRet");
  const covidDdN = _labRetestMinMax(raw, "covidDd");
  // Pass3：各综合分（归一化加权）
  return raw.map((r) => {
    // 整体归一 = 0.4*ret_norm + 0.3*win_norm + 0.2*(1-dd_norm) + 0.1*n_norm
    const wholeScore = 0.4 * retN(r.ret) + 0.3 * winN(r.win) + 0.2 * (1 - ddN(r.dd)) + 0.1 * nN(r.n);
    // 分年综合分 = 0.4*min年ret_norm + 0.4*盈利年占比 + 0.2*(1-波动norm)
    const yearlyScore = 0.4 * minYearRetN(r.minYearRet) + 0.4 * r.profitYearRatio + 0.2 * (1 - yearVolN(r.yearVol));
    // oos综合分 = 0.4*test_ret_norm + 0.4*(1-过拟合度norm) + 0.2*test_win_norm
    const oosScore = 0.4 * testRetN(r.testRet) + 0.4 * (1 - overfitN(r.overfit)) + 0.2 * testWinN(r.testWin);
    // regime综合分：covid有值4项各0.25；null则3项 crash0.3+bear0.3+rally0.4
    const crashNorm = 1 - crashDdN(r.crashDd); // 抗跌
    const bearNorm = 1 - bearDdN(r.bearDd);
    const rallyNorm = rallyRetN(r.rallyRet); // 能涨
    let regimeScore;
    if (r.covidNull) {
      regimeScore = 0.3 * crashNorm + 0.3 * bearNorm + 0.4 * rallyNorm;
    } else {
      const covidNorm = 1 - covidDdN(r.covidDd);
      regimeScore = 0.25 * crashNorm + 0.25 * bearNorm + 0.25 * rallyNorm + 0.25 * covidNorm;
    }
    // 综合(二次测试) = 0.3*整体 + 0.25*分年 + 0.25*oos + 0.2*regime
    const score = 0.3 * wholeScore + 0.25 * yearlyScore + 0.25 * oosScore + 0.2 * regimeScore;
    return Object.assign({}, r, { wholeScore, yearlyScore, oosScore, regimeScore, score });
  });
}

function _labRetestRankSort(rows, tab) {
  const arr = rows.slice();
  if (tab === "ret") arr.sort((a, b) => b.ret - a.ret);
  else if (tab === "win") arr.sort((a, b) => b.win - a.win);
  else if (tab === "dd") arr.sort((a, b) => a.dd - b.dd); // 回撤小优先
  else if (tab === "n") arr.sort((a, b) => b.n - a.n);
  else if (tab === "yearly") arr.sort((a, b) => b.yearlyScore - a.yearlyScore);
  else if (tab === "oos") arr.sort((a, b) => b.oosScore - a.oosScore);
  else if (tab === "regimes") arr.sort((a, b) => b.regimeScore - a.regimeScore);
  else arr.sort((a, b) => b.score - a.score); // 综合(新公式，含三切片)
  return arr;
}

// 小样本灰色标注 tag（某年n<3 或 oos test n<10）
function _labRetestSmallTag(flag) {
  return flag ? ' <span class="lab-rank-small">小样本</span>' : "";
}

function _labRetestRankItemHTML(row, rank, tab) {
  const medal = rank === 1 ? "🥇" : rank === 2 ? "🥈" : rank === 3 ? "🥉" : "";
  // 基础 stats 行（所有 tab 共享上下文：收益/胜/回撤/n）
  const baseStats =
    `<span style="color:${_labRetestColor(row.ret)}">收益${_labRetestPct(row.ret)}</span>` +
    `<span style="color:${_labRetestColor(row.win)}">胜${_labRetestPct(row.win)}</span>` +
    `<span style="${_labDdColor(row.dd)}">回撤${_labRetestPct(row.dd)}</span>` +
    `<span class="lab-rank-n">n=${row.n}</span>`;
  let extra = "";
  if (tab === "score") {
    extra = `<span class="lab-rank-dim-sub">综合 ${(row.score * 100).toFixed(1)} · 整体${(row.wholeScore * 100).toFixed(0)} 分年${(row.yearlyScore * 100).toFixed(0)} 样外${(row.oosScore * 100).toFixed(0)} 极端${(row.regimeScore * 100).toFixed(0)}</span>`;
  } else if (tab === "yearly") {
    extra = `<span class="lab-rank-dim-sub">最差年${_labRetestPct(row.minYearRet)} · 盈利${row.profitYears}/${row.yearCount}年 · 波动${_labRetestPct(row.yearVol)}${_labRetestSmallTag(row.yearSmall)}</span>`;
  } else if (tab === "oos") {
    extra = `<span class="lab-rank-dim-sub">test${_labRetestPct(row.testRet)} · 过拟合${_labRetestPct(row.overfit)} · test胜${_labRetestPct(row.testWin)}${_labRetestSmallTag(row.oosSmall)}</span>`;
  } else if (tab === "regimes") {
    const covidNote = row.covidNull
      ? ' · <span class="lab-rank-small">疫情无交易</span>'
      : ` · 疫情回撤${_labRetestPct(row.covidDd)}`;
    extra = `<span class="lab-rank-dim-sub">股灾回撤${_labRetestPct(row.crashDd)} · 熊市回撤${_labRetestPct(row.bearDd)} · 反弹收益${_labRetestPct(row.rallyRet)}${covidNote}</span>`;
  }
  // ret/win/dd/n 维度的值已在 baseStats 中显示，排序即体现排名，不加冗余 extra
  return `<button type="button" class="lab-rank-item clickable-card" data-pk="${row.pk}">` +
    `<span class="lab-rank-no">${medal || "#" + rank}</span>` +
    `<span class="lab-rank-name">${row.cn} · ${row.modeCn}</span>` +
    `<span class="lab-rank-stats">${baseStats}</span>` +
    extra + `</button>`;
}

function _labRetestRankHTML(rd, simData) {
  if (!rd) return '<div class="lab-rank-empty">二次测试数据加载失败，请稍后重试</div>';
  const winKey = state.labRetestRankWindow || "y5"; // 5窗口切换：整体4维取自 simData stats[winKey]
  const rows = _labRetestRankRows(rd, simData, winKey);
  if (rows.length === 0) return '<div class="lab-rank-empty">暂无二次测试候选配对</div>';
  state.labRetestRankRows = rows;
  const tab = state.labRetestRankTab || "score";
  const tabsHTML = LAB_RETEST_RANK_TABS.map((t) =>
    `<button type="button" class="lab-rank-tab${t.key === tab ? " active" : ""}" data-tab="${t.key}">${t.label}</button>`
  ).join("");
  // 5窗口切换器（独立 state.labRetestRankWindow，不影响推荐榜 state.labSimWindow）
  const winTabsHTML = '<div class="lab-win-tabs">' + LAB_WIN_DEFS.map((w) =>
    `<button type="button" class="lab-win-tab${w.k === winKey ? " active" : ""}" data-win="${w.k}">${w.l}</button>`
  ).join("") + "</div>";
  const legend = tab === "score"
    ? "综合分(二次测试)=0.3整体+0.25分年+0.25样本外+0.2极端，归一化加权，越高越稳健。"
    : tab === "dd"
      ? "稳健榜按最大回撤从小到大排序，回撤越小越稳。"
      : tab === "ret"
        ? "收益率榜按总收益率从高到低排序。"
        : tab === "win"
          ? "胜率榜按胜率从高到低排序。"
          : tab === "n"
            ? "样本量榜按交易次数从多到少排序。"
            : tab === "yearly"
              ? "分年榜=0.4最差年收益+0.4盈利年占比+0.2低波动（防某年暴利拉高整体）。"
              : tab === "oos"
                ? "样本外榜=0.4test收益+0.4低过拟合+0.2test胜率（前70%训练后30%验证防过拟合）。"
                : "极端行情榜=股灾/熊市抗跌+反弹能涨（疫情无交易则跳过不扣分）。";
  return `<div class="lab-win-bar"><span class="lab-win-bar-label">时间窗口</span>${winTabsHTML}<span class="lab-win-bar-cur">${(LAB_WIN_DEFS.find((w) => w.k === winKey) || {}).l || ""}</span></div>` +
    `<div class="lab-rank-tabs">${tabsHTML}</div>` +
    `<div class="lab-rank-legend">${legend} 点击任意配对查看整体回测详情+二次测试三切片。红=好，绿=差。</div>` +
    `<div class="lab-rank-results">${_labRetestRankResultsHTML()}</div>`;
}

function _labRetestRankResultsHTML() {
  const rows = state.labRetestRankRows || [];
  const tab = state.labRetestRankTab || "score";
  const sorted = _labRetestRankSort(rows, tab);
  const showAll = !!state.labRetestRankShowAll;
  const shown = showAll ? sorted : sorted.slice(0, 20);
  const countHTML = `<div style="font-size:12px;color:var(--text-3);margin-bottom:6px;">共 <b style="color:#9c27b0;">${rows.length}</b> 个候选配对</div>`;
  const itemsHTML = shown.length > 0
    ? shown.map((r, i) => _labRetestRankItemHTML(r, i + 1, tab)).join("")
    : '<div class="lab-rank-empty">暂无数据</div>';
  const moreBtn = sorted.length > 20
    ? `<button type="button" class="lab-rank-more">${showAll ? "收起 ▲" : `显示全部 ${sorted.length} 组 ▼`}</button>`
    : "";
  return countHTML + `<div class="lab-rank-list">${itemsHTML}</div>` + moreBtn;
}

function _labRetestRankAttachHandlers(section, rd, simData) {
  section.querySelectorAll(".lab-rank-tab").forEach((btn) => {
    btn.onclick = () => { state.labRetestRankTab = btn.dataset.tab; state.labRetestRankShowAll = false; _labRetestRankRerender(section, rd, simData); };
  });
  // 5窗口切换（整体4维随窗口从 simData stats[win] 重算重排）
  section.querySelectorAll(".lab-win-tab[data-win]").forEach((btn) => {
    btn.onclick = () => { state.labRetestRankWindow = btn.dataset.win; state.labRetestRankShowAll = false; _labRetestRankRerender(section, rd, simData); };
  });
  section.querySelectorAll(".lab-rank-item").forEach((item) => {
    item.onclick = () => _labRetestPairOpenModal(rd, item.dataset.pk);
  });
  const more = section.querySelector(".lab-rank-more");
  if (more) more.onclick = () => { state.labRetestRankShowAll = !state.labRetestRankShowAll; _labRetestRankRerenderResults(section, rd, simData); };
}

function _labRetestRankRerenderResults(section, rd, simData) {
  const res = section.querySelector(".lab-rank-results");
  if (!res) return;
  res.innerHTML = _labRetestRankResultsHTML();
  section.querySelectorAll(".lab-rank-item").forEach((item) => {
    item.onclick = () => _labRetestPairOpenModal(rd, item.dataset.pk);
  });
  const more = section.querySelector(".lab-rank-more");
  if (more) more.onclick = () => { state.labRetestRankShowAll = !state.labRetestRankShowAll; _labRetestRankRerenderResults(section, rd, simData); };
}

function _labRetestRankRerender(section, rd, simData) {
  const body = section.querySelector(".lab-rank-body");
  if (body) body.innerHTML = _labRetestRankHTML(rd, simData);
  _labRetestRankAttachHandlers(section, rd, simData);
}

// 左栏候选配对卡片：每配对1张紧凑卡（中文名+窗口+综合分+胜率/回撤/n），点击弹窗
function _labRetestRenderCards(list, rd) {
  if (!rd) { list.innerHTML = '<div class="lab-rank-empty">二次测试数据加载失败</div>'; return; }
  if (rd === null) { list.innerHTML = '<div class="lab-rank-empty">暂无二次测试数据</div>'; return; }
  const pks = rd.pairs ? Object.keys(rd.pairs) : [];
  if (pks.length === 0) { list.innerHTML = '<div class="lab-rank-empty">暂无二次测试候选配对</div>'; return; }
  list.innerHTML = pks.map((pk) => {
    const meta = (rd.pairs[pk] && rd.pairs[pk].pair_meta) || {};
    const cn = _labRetestPairCN(meta.strategy || pk);
    const winCn = _labRetestWinCN(meta.window);
    const score = meta.score != null ? (meta.score * 100).toFixed(0) : "-";
    return `<div class="lab-strategy-card lab-retest-card clickable-card" data-pk="${pk}">` +
      `<div class="lab-card-top">` +
      `<span class="lab-card-name">⭐️ ${cn}</span>` +
      `<span class="lab-rank-score">评分 ${score}</span>` +
      `</div>` +
      `<div class="lab-card-trigger">窗口: ${winCn} · 样本: ${meta.n != null ? meta.n : "-"}</div>` +
      `<div class="lab-card-conclusion">收益 ${_labRetestPct(meta.ret)} · 胜率 <span style="color:${_labRetestColor(meta.win)}">${_labRetestPct(meta.win)}</span> · 回撤 <span style="${_labDdColor(meta.dd)}">${_labRetestPct(meta.dd)}</span></div>` +
      `<div class="lab-fusion-pair-hint">📊 点击查看分年/样本外/极端行情 ▸</div>` +
      `</div>`;
  }).join("");
  list.querySelectorAll(".lab-retest-card").forEach((card) => {
    card.onclick = () => _labRetestPairOpenModal(rd, card.dataset.pk);
  });
}

// 二次测试实验分区主入口（照抄 renderFusionLab 结构：左自白+指数选择器+配对卡片 / 右维度榜）
async function renderRetestLab() {
  const wrapper = document.createElement("div");
  wrapper.className = "lab-list-2col";
  const leftCol = document.createElement("div");
  const rightCol = document.createElement("div");

  // 自白黄块（包二次测试规则文案）
  const essayWarn = document.createElement("div");
  essayWarn.className = "lab-warning lab-warning-essay";
  essayWarn.innerHTML = `<p>${_LAB_RETEST_RULE}</p>`;
  leftCol.appendChild(essayWarn);

  // 指数选择器（复用 LAB_SIM_INDEXES，代替融合的 zone-tabs）
  const curIdx = state.labSimIndex || "sh";
  const idxBtns = LAB_SIM_INDEXES.map((x) =>
    `<button type="button" class="lab-idx-tab${x.id === curIdx ? " active" : ""}" data-idx="${x.id}">${x.name}</button>`
  ).join("");
  const idxBar = document.createElement("div");
  idxBar.className = "lab-win-bar";
  idxBar.innerHTML = `<span class="lab-win-bar-label">选择指数</span><div class="lab-win-tabs">${idxBtns}</div>`;
  leftCol.appendChild(idxBar);

  // 候选配对卡片列表
  const list = document.createElement("div");
  list.className = "lab-strategy-list lab-retest-list";
  list.innerHTML = '<div class="lab-rank-loading">⏳ 加载二次测试数据中…</div>';
  leftCol.appendChild(list);

  // 阶段提示
  const phaseNote = document.createElement("div");
  phaseNote.className = "lab-fusion-phase-note";
  phaseNote.innerHTML = "📌 <b>二次测试(稳健性验证三件套)</b>：分年回测 / 样本外 / 极端行情。点击配对卡片或右侧维度榜查看完整细节。";
  leftCol.appendChild(phaseNote);

  // 右栏：retest 维度排行榜（5窗口切换器，整体4维随窗口从 simData stats 重算）
  const rankSection = document.createElement("div");
  rankSection.className = "chart-card lab-rank-card";
  rankSection.innerHTML = '<h3>🔬 二次测试维度榜</h3>' +
    '<div class="lab-rank-body"><div class="lab-rank-loading">⏳ 加载二次测试数据中…</div></div>';
  rightCol.appendChild(rankSection);

  wrapper.appendChild(leftCol);
  wrapper.appendChild(rightCol);
  content.appendChild(wrapper);

  // 加载 + 渲染（左卡片 + 右榜）
  const _load = async () => {
    const idx = state.labSimIndex || "sh";
    const rd = await fetchLabRetestData(idx);
    // 加载单信号 stats simData（含融合候选，排行榜5窗口切换需读 stats[win]）
    const simData = await fetchLabSimData(idx);
    _labRetestRenderCards(list, rd);
    _labRetestRankRerender(rankSection, rd, simData);
  };
  _load();

  // 指数切换：重新加载该指数数据并重渲染
  idxBar.querySelectorAll(".lab-idx-tab").forEach((btn) => {
    btn.onclick = () => {
      state.labSimIndex = btn.dataset.idx;
      idxBar.querySelectorAll(".lab-idx-tab").forEach((b) => b.classList.toggle("active", b === btn));
      list.innerHTML = '<div class="lab-rank-loading">⏳ 加载中…</div>';
      const body = rankSection.querySelector(".lab-rank-body");
      if (body) body.innerHTML = '<div class="lab-rank-loading">⏳ 加载中…</div>';
      _load();
    };
  });
}

// === 二次测试配对弹窗（上半=整体回测详情照抄单一信号实验，下半=三切片强化）===
// 用户原话："单一测试里有的功能你都要带过来。你二次测试是优化，不是舍弃原有的判定标准，是在此之上的强化"
function _labRetestPairOpenModal(rd, pk) {
  let overlay = document.getElementById("labRetestPairOverlay");
  if (!overlay) {
    overlay = document.createElement("div");
    overlay.id = "labRetestPairOverlay";
    overlay.className = "lab-signal-overlay";
    document.body.appendChild(overlay);
  }
  const pd = rd && rd.pairs ? rd.pairs[pk] : null;
  const meta = (pd && pd.pair_meta) || {};
  state.labRetestPairModal = {
    rd, pk,
    mode: "full_in",              // retest 后端用 full_in 跑二次测试（pair_meta 无 mode 字段）
    win: meta.window || "y5",     // 默认 retest 窗口
    page: 0,
    open: true,
  };
  _labRetestPairModalRender(overlay);
  overlay.classList.add("show");
  document.body.style.overflow = "hidden";
  overlay.onclick = (e) => { if (e.target === overlay) _labRetestPairCloseModal(); };
}

function _labRetestPairCloseModal() {
  const overlay = document.getElementById("labRetestPairOverlay");
  if (overlay) { overlay.classList.remove("show"); overlay.innerHTML = ""; overlay.onclick = null; }
  document.body.style.overflow = "";
  state.labRetestPairModal = null;
}

// 弹窗内窗口切换 tabs（复用 LAB_WIN_DEFS，独立于排行榜窗口 state.labRetestRankWindow）
function _labRetestModalWinTabsHTML(win) {
  return '<div class="lab-win-tabs">' + LAB_WIN_DEFS.map((w) =>
    `<button type="button" class="lab-win-tab${w.k === win ? " active" : ""}" data-win="${w.k}">${w.l}</button>`
  ).join("") + "</div>";
}

// 弹窗内按需加载 full 数据（trades/equity_curve），照抄 _labRankEnsureFull
async function _labRetestEnsureFull(overlay, idx) {
  const setProg = (pct) => {
    const el = overlay.querySelector(".lab-sim-full-loading");
    if (!el) return;
    if (pct < 0) { el.textContent = "⏳ 加载明细数据中…"; return; }
    el.innerHTML = `⏳ 加载明细数据中… ${pct}%<div class="lab-full-prog"><div style="width:${pct}%"></div></div>`;
  };
  const controller = new AbortController();
  let timedOut = false;
  const slowTimer = setTimeout(() => { timedOut = true; controller.abort(); }, 15000);
  try {
    await fetchLabSimFullData(idx, (received, total) => {
      setProg(total > 0 ? Math.round(received / total * 100) : -1);
    }, controller.signal);
  } finally {
    clearTimeout(slowTimer);
  }
  if (_labSimFullLoaded(idx)) {
    if (state.labRetestPairModal) _labRetestPairModalRender(overlay);
  } else {
    const el = overlay.querySelector(".lab-sim-full-loading");
    if (el) {
      el.innerHTML = `<span>${timedOut ? "⏳ 加载超时" : "⚠ 加载失败"}</span> ` +
        `<button type="button" class="lab-full-retry" style="margin-left:8px;padding:3px 12px;border:1px solid var(--border-strong);border-radius:5px;background:var(--bg-card);color:var(--text-1);font-size:12px;cursor:pointer;">重试</button>`;
      const retryBtn = el.querySelector(".lab-full-retry");
      if (retryBtn) retryBtn.onclick = () => _labRetestEnsureFull(overlay, idx);
    }
  }
}

async function _labRetestPairModalRender(overlay) {
  const m = state.labRetestPairModal;
  if (!m) return;
  const pd = m.rd && m.rd.pairs ? m.rd.pairs[m.pk] : null;
  const meta = (pd && pd.pair_meta) || {};
  const cn = _labRetestPairCN(meta.strategy || m.pk);
  const winCn = _labRetestWinCN(meta.window);
  const score = meta.score != null ? (meta.score * 100).toFixed(0) : "-";
  // loading 骨架
  overlay.innerHTML = `<div class="lab-signal-modal">` +
    `<div class="lab-signal-modal-head">` +
    `<span class="lab-signal-modal-title">🔬 ${cn} · ${winCn} · 评分 ${score}</span>` +
    `<button type="button" class="lab-rank-modal-close" aria-label="关闭">✕</button>` +
    `</div>` +
    `<div class="lab-signal-modal-body"><div class="loading">加载回测数据…</div></div></div>`;
  overlay.querySelector(".lab-rank-modal-close").onclick = _labRetestPairCloseModal;

  // 加载单信号 stats simData（含融合候选 91 组，per-index 缓存；retest 候选是其子集）
  const idx = (m.rd && m.rd.index_id) || (state.labSimIndex || "sh");
  const simData = await fetchLabSimData(idx);
  const initCapital = (simData && simData.initial_capital) || 100000;
  // 拆 strategy("buyKey|sellKey") -> 取整体回测配对数据
  const parts = (meta.strategy || m.pk).split("|");
  const buyKey = parts[0], sellKey = parts[1];
  const buyName = (LAB_STRATEGIES[buyKey] || {}).name || buyKey;
  const sellName = (LAB_STRATEGIES[sellKey] || {}).name || sellKey;
  const pairData = simData ? _labGetPair(simData, buyKey, sellKey) : null;
  const mode = m.mode || "full_in";
  const win = m.win || meta.window || "y5";
  const winData = pairData ? _labPairWinData(pairData, mode, win, simData) : null;
  const modeName = mode === "full_in" ? "全仓" : "定额（10%）";
  const winLabel = (LAB_WIN_DEFS.find((w) => w.k === win) || {}).l || "";

  // 上半部分：整体回测详情（4数字+净值曲线+交易记录），照抄单一信号实验弹窗 _labRankModalRender
  let detailHTML;
  if (!simData) {
    detailHTML = '<div class="lab-rank-modal-empty">回测数据加载失败</div>';
  } else if (!winData || !winData.stats) {
    detailHTML = `<div class="lab-rank-modal-empty">配对 ${buyKey}|${sellKey} 在 ${idx} 无整体回测数据</div>`;
  } else {
    // 同步 page 到有效范围（_labSimModeBlock 内部也 clamp，此处保持 state 一致）
    const trades = winData.trades || [];
    const totalPages = Math.max(1, Math.ceil(trades.length / 20));
    if (m.page > totalPages - 1) m.page = totalPages - 1;
    if (m.page < 0) m.page = 0;
    // 买卖模式切换 tabs（全仓 / 定额10%）
    const modeBar = '<div class="lab-win-bar"><span class="lab-win-bar-label">买卖模式</span>' +
      '<div class="lab-win-tabs">' +
      `<button type="button" class="lab-win-tab${mode === "full_in" ? " active" : ""}" data-mode="full_in">全仓</button>` +
      `<button type="button" class="lab-win-tab${mode === "fixed_10k" ? " active" : ""}" data-mode="fixed_10k">定额（10%）</button>` +
      '</div></div>';
    // 5窗口切换器（近1年/近3年/近5年/近10年/全史）
    const winBar = `<div class="lab-win-bar"><span class="lab-win-bar-label">时间窗口</span>${_labRetestModalWinTabsHTML(win)}<span class="lab-win-bar-cur">${winLabel}</span></div>`;
    detailHTML = modeBar + winBar + _labSimModeBlock(mode, winData, initCapital, m.page, m.open);
  }

  // 下半部分：二次测试三切片（保留原有判定强化：分年/样本外/极端行情）
  const retestHTML = pd ? _labRetestPairHTML(m.pk, pd) : '<div class="lab-rank-modal-empty">暂无二次测试数据</div>';

  const bodyHTML =
    `<div class="lab-retest-modal-section">` +
    `<div class="lab-retest-modal-section-title">📊 整体回测详情 · 买${buyName} × 卖${sellName} · ${modeName}（${winLabel}）</div>` +
    `<div class="lab-retest-modal-hint">该配对的标准回测（4数字结论 + 净值曲线 + 交易记录），即原有判定标准。</div>` +
    detailHTML +
    `</div>` +
    `<div class="lab-retest-modal-section">` +
    `<div class="lab-retest-modal-section-title">🔬 二次测试（在此之上的强化：分年 / 样本外 / 极端行情）</div>` +
    retestHTML +
    `</div>`;

  const body = overlay.querySelector(".lab-signal-modal-body");
  if (body) body.innerHTML = bodyHTML;

  // 绑定：买卖模式切换 / 窗口切换（切换重置分页）
  overlay.querySelectorAll(".lab-win-tab[data-mode]").forEach((btn) => {
    btn.onclick = () => { m.mode = btn.dataset.mode; m.page = 0; _labRetestPairModalRender(overlay); };
  });
  overlay.querySelectorAll(".lab-win-tab[data-win]").forEach((btn) => {
    btn.onclick = () => { m.win = btn.dataset.win; m.page = 0; _labRetestPairModalRender(overlay); };
  });
  // 交易记录折叠/展开
  const hdr = overlay.querySelector(".lab-sim-trades-header");
  if (hdr) hdr.onclick = () => { m.open = !m.open; _labRetestPairModalRender(overlay); };
  // 交易记录分页
  const prev = overlay.querySelector(".lab-sim-prev");
  if (prev) prev.onclick = () => { if (m.page > 0) { m.page--; _labRetestPairModalRender(overlay); } };
  const next = overlay.querySelector(".lab-sim-next");
  if (next && !next.disabled) next.onclick = () => { m.page++; _labRetestPairModalRender(overlay); };

  // full 数据(trades/equity_curve)按需加载，加载完重渲染（净值曲线/交易记录显示 loading 占位直到加载完）
  if (simData && !_labSimFullLoaded(idx)) _labRetestEnsureFull(overlay, idx);
}

// === 融合候选配对回测弹窗（A类买×卖查 lab_sim_{index}_stats.json；B类同向共振显示开发中）===
// 指数选择器分组（融合候选为A股策略，仅列A股宽基）
const LAB_FUSION_PAIR_INDEX_GROUPS = [
  ["A股宽基", ["sh", "sz", "cyb", "csi500", "csi1000", "kc50", "hs300", "sz50"]],
];
const LAB_FUSION_WIN_LABELS = [
  { k: "all", label: "全史" },
  { k: "y10", label: "近10年" },
  { k: "y5", label: "近5年" },
  { k: "y3", label: "近3年" },
  { k: "y1", label: "近1年" },
];

function _labFusionPairOpenModal(meta) {
  let overlay = document.getElementById("labFusionPairOverlay");
  if (!overlay) {
    overlay = document.createElement("div");
    overlay.id = "labFusionPairOverlay";
    overlay.className = "lab-signal-overlay";
    document.body.appendChild(overlay);
  }
  state.labFusionPairModal = {
    meta: meta,
    index: state.labSimIdx || state.labIndex || "sh",
  };
  _labFusionPairModalRender(overlay);
  overlay.classList.add("show");
  document.body.style.overflow = "hidden";
  overlay.onclick = (e) => { if (e.target === overlay) _labFusionPairCloseModal(); };
}

function _labFusionPairCloseModal() {
  const overlay = document.getElementById("labFusionPairOverlay");
  if (overlay) { overlay.classList.remove("show"); overlay.innerHTML = ""; overlay.onclick = null; }
  document.body.style.overflow = "";
  state.labFusionPairModal = null;
}

// === 单一信号策略详情弹窗（全搬 renderLabDetail 整页内容进全屏 modal）===
function _labSignalDetailOpenModal(key) {
  let overlay = document.getElementById("labSignalDetailOverlay");
  if (!overlay) {
    overlay = document.createElement("div");
    overlay.id = "labSignalDetailOverlay";
    overlay.className = "lab-signal-overlay";
    document.body.appendChild(overlay);
  }
  const meta = LAB_STRATEGIES[key] || {};
  const tag = LAB_STATUS_TAGS[meta.status] || LAB_STATUS_TAGS.dev;
  const titleHTML = meta.name
    ? `📊 ${meta.name} <span class="lab-tag ${tag.cls}">${tag.label}</span>`
    : "📊 策略详情";
  // 渲染 loading 骨架（标题在 sticky head，关闭 X）
  overlay.innerHTML = `<div class="lab-signal-modal">` +
    `<div class="lab-signal-modal-head">` +
    `<span class="lab-signal-modal-title">${titleHTML}</span>` +
    `<button type="button" class="lab-rank-modal-close" aria-label="关闭">✕</button>` +
    `</div>` +
    `<div class="lab-signal-modal-body"><div class="loading">加载策略详情…</div></div></div>`;
  overlay.classList.add("show");
  document.body.style.overflow = "hidden";
  overlay.onclick = (e) => { if (e.target === overlay) _labSignalDetailCloseModal(); };
  overlay.querySelector(".lab-rank-modal-close").onclick = _labSignalDetailCloseModal;
  // 异步渲染详情到 modal body（renderLabDetail 已支持 container 参数）
  const body = overlay.querySelector(".lab-signal-modal-body");
  renderLabDetail(key, body).catch((e) => {
    if (body) body.innerHTML = `<div class="lab-rank-modal-empty">加载失败：${e}</div>`;
  });
  // 滚到顶部
  overlay.scrollTop = 0;
}

function _labSignalDetailCloseModal() {
  const overlay = document.getElementById("labSignalDetailOverlay");
  if (overlay) {
    // 释放弹窗内 echarts 实例（图表+净值曲线），避免内存泄漏
    for (let i = charts.length - 1; i >= 0; i--) {
      try {
        const dom = charts[i].getDom && charts[i].getDom();
        if (dom && overlay.contains(dom)) { charts[i].dispose(); charts.splice(i, 1); }
      } catch (e) {}
    }
    overlay.classList.remove("show");
    overlay.innerHTML = "";
    overlay.onclick = null;
  }
  document.body.style.overflow = "";
  state._labSimRerender = null;
  state._labChartRerender = null;
}

async function _labFusionPairModalRender(overlay) {
  const m = state.labFusionPairModal;
  if (!m) return;
  const meta = m.meta;
  const isAPair = meta._pairType === "buy_sell";
  const buyName = (LAB_STRATEGIES[meta._buyKey] || {}).name || meta._buyKey;
  const sellName = (LAB_STRATEGIES[meta._sellKey] || {}).name || meta._sellKey;

  if (!isAPair) {
    // B类：同向共振回测开发中
    const resonanceType = meta._pairType === "buy_buy" ? "双买共振" : "双卖共振";
    overlay.innerHTML = `<div class="lab-signal-modal">` +
      `<div class="lab-signal-modal-head">` +
      `<span class="lab-signal-modal-title">🔬 ${resonanceType} · ${buyName} + ${sellName}</span>` +
      `<button type="button" class="lab-rank-modal-close" aria-label="关闭">✕</button>` +
      `</div>` +
      `<div class="lab-signal-modal-body">` +
      `<div class="lab-rank-modal-empty">🚧 同向共振回测开发中<br>` +
      `<span style="font-size:12px">当前仅支持买×卖配对回测，同向（买×买 / 卖×卖）共振回测待后续开放。</span></div>` +
      `</div></div>`;
    overlay.querySelector(".lab-rank-modal-close").onclick = _labFusionPairCloseModal;
    return;
  }

  // A类：先渲染 loading 骨架
  overlay.innerHTML = `<div class="lab-signal-modal">` +
    `<div class="lab-signal-modal-head">` +
    `<span class="lab-signal-modal-title">📊 配对回测 · 买${buyName} × 卖${sellName}</span>` +
    `<button type="button" class="lab-rank-modal-close" aria-label="关闭">✕</button>` +
    `</div>` +
    `<div class="lab-signal-modal-body"><div class="loading">加载回测数据…</div></div></div>`;
  overlay.querySelector(".lab-rank-modal-close").onclick = _labFusionPairCloseModal;

  // 加载 stats json（fetchLabSimData 带 per-index 缓存）
  const simData = await fetchLabSimData(m.index);
  const pairId = meta._buyKey + "|" + meta._sellKey;
  const pair = simData && simData.pairs ? simData.pairs[pairId] : null;

  // 指数选择器
  const selectHTML = LAB_FUSION_PAIR_INDEX_GROUPS.map(([gname, ids]) =>
    `<optgroup label="${gname}">` +
    ids.map((id) => `<option value="${id}"${id === m.index ? " selected" : ""}>${_INDEX_NAME_MAP[id] || id}</option>`).join("") +
    `</optgroup>`
  ).join("");

  let bodyHTML;
  if (!pair) {
    bodyHTML = `<div class="lab-fusion-pair-filter"><label>选择指数</label><select class="lab-fusion-pair-index">${selectHTML}</select></div>` +
      `<div class="lab-rank-modal-empty">暂无回测数据<br>` +
      `<span style="font-size:12px">配对 ${pairId} 在 ${_INDEX_NAME_MAP[m.index] || m.index} 未找到回测结果。</span></div>`;
  } else {
    bodyHTML = `<div class="lab-fusion-pair-filter"><label>选择指数</label><select class="lab-fusion-pair-index">${selectHTML}</select>` +
      `<span class="lab-fusion-pair-legend">红=好，绿=差 · 回撤≤20%优</span></div>` +
      _labFusionPairStatsHTML(pair, "full_in", "全仓投入") +
      _labFusionPairStatsHTML(pair, "fixed_10k", "定额（10%）");
  }

  const body = overlay.querySelector(".lab-signal-modal-body");
  if (body) {
    body.innerHTML = bodyHTML;
    const sel = body.querySelector(".lab-fusion-pair-index");
    if (sel) sel.onchange = (e) => { m.index = e.target.value; _labFusionPairModalRender(overlay); };
  }
}

// 配对回测统计表 HTML：2模式 × 5窗口（全史/近10年/近5年/近3年/近1年）
function _labFusionPairStatsHTML(pair, mode, modeName) {
  const md = pair[mode];
  if (!md || !md.stats) return "";
  const stats = md.stats;
  const rows = LAB_FUSION_WIN_LABELS.map((w) => {
    const s = stats[w.k];
    if (!s) return "";
    const retC = s.total_ret >= 0 ? "#c92a2a" : "#2e7d32";
    const winC = s.win_rate >= 50 ? "#c92a2a" : "#2e7d32";
    const ddC = s.max_drawdown <= 20 ? "#c92a2a" : (s.max_drawdown <= 50 ? "#e67e22" : "#2e7d32");
    return `<tr>` +
      `<td class="lab-fp-win">${w.label}</td>` +
      `<td class="lab-fp-ret" style="color:${retC}">${s.total_ret > 0 ? "+" : ""}${s.total_ret.toFixed(1)}%</td>` +
      `<td class="lab-fp-winrate" style="color:${winC}">${s.win_rate.toFixed(1)}%</td>` +
      `<td class="lab-fp-ann">${s.annual_ret.toFixed(1)}%</td>` +
      `<td class="lab-fp-dd" style="color:${ddC}">${s.max_drawdown.toFixed(1)}%</td>` +
      `<td class="lab-fp-n">${s.n_trades}</td>` +
      `</tr>`;
  }).join("");
  return `<div class="lab-fusion-pair-section">` +
    `<div class="lab-fusion-pair-mode">${modeName}</div>` +
    `<table class="lab-fusion-pair-table">` +
    `<thead><tr><th>窗口</th><th>总收益</th><th>胜率</th><th>年化</th><th>最大回撤</th><th>笔数</th></tr></thead>` +
    `<tbody>${rows}</tbody></table></div>`;
}

async function renderSignalLab() {
  // 如果有选中的策略，进详情页（仅单一信号模式）
  if (state.labStrategy && state.labSubMode !== "fusion" && state.labSubMode !== "retest") {
    await renderLabDetail(state.labStrategy);
    return;
  }

  content.innerHTML = "";

  // === 二级导航（单一信号实验 / 融合信号实验）===
  _renderLabSubNav();

  // 融合信号模式 -> 渲染融合列表页（阶段一：仅元数据，不跑回测）
  if (state.labSubMode === "fusion") {
    await renderFusionLab();
    _labSetHash("#lab");
    _labRestoreScroll();
    return;
  }

  // 二次测试模式 -> 渲染二次测试实验分区（照抄融合区布局：左配对卡片+右维度榜）
  if (state.labSubMode === "retest") {
    await renderRetestLab();
    _labSetHash("#lab");
    _labRestoreScroll();
    return;
  }

  // 实验室自白黄块（列表页也显示，通用介绍 + 抖音号；移入左栏与策略列表同栏）
  const essayWarn = document.createElement("div");
  essayWarn.className = "lab-warning lab-warning-essay";
  essayWarn.innerHTML = _labWarningEssayHTML();

  // 预加载回测数据（用于卡片摘要）
  const data = await fetchLabData();

  // 左右2栏布局：策略卡左 + 回测推荐榜右
  const wrapper = document.createElement("div");
  wrapper.className = "lab-list-2col";
  const leftCol = document.createElement("div");
  const rightCol = document.createElement("div");

  // 分区 tab
  const zoneTabs = document.createElement("div");
  zoneTabs.className = "lab-zone-tabs";
  LAB_ZONES.forEach((z) => {
    const btn = document.createElement("button");
    btn.className = "lab-zone-tab" + (state.labZone === z.key ? " active" : "");
    btn.innerHTML = `${z.label} <span class="lab-zone-count">${z.count}</span>`;
    btn.onclick = () => { state.labZone = z.key; renderSignalLab(); };
    zoneTabs.appendChild(btn);
  });
  leftCol.appendChild(essayWarn);
  leftCol.appendChild(zoneTabs);

  // 搜索框（按策略名/条件模糊过滤卡片列表，大小写不敏感）
  const searchWrap = document.createElement("div");
  searchWrap.className = "lab-fusion-search-wrap";
  searchWrap.innerHTML = '<input type="text" class="lab-fusion-search" placeholder="搜索策略名/条件…" autocomplete="off">';
  leftCol.appendChild(searchWrap);

  // 分区描述
  const curZone = LAB_ZONES.find((z) => z.key === state.labZone) || LAB_ZONES[1];
  const zoneDesc = document.createElement("div");
  zoneDesc.className = "lab-zone-desc";
  zoneDesc.textContent = curZone.desc;
  leftCol.appendChild(zoneDesc);

  // 策略卡片列表
  const list = document.createElement("div");
  list.className = "lab-strategy-list";
  const zoneStrategies = Object.entries(LAB_STRATEGIES).filter(([k, v]) => v.zone === state.labZone);
  zoneStrategies.forEach(([key, meta]) => {
    const tag = LAB_STATUS_TAGS[meta.status] || LAB_STATUS_TAGS.dev;
    // 10d摘要：取近3年10d win/pl
    let summary = "";
    if (data && data.strategies && data.strategies[key] && data.strategies[key].periods) {
      const p = data.strategies[key].periods["近3年"];
      if (p && p["10d"]) {
        const c = p["10d"];
        summary = `近3年10d：胜率${(c.win * 100).toFixed(1)}% / PL ${c.pl.toFixed(2)} / n=${c.n}`;
      }
    }
    const card = document.createElement("div");
    card.className = "lab-strategy-card";
    card.innerHTML =
      `<div class="lab-card-top">` +
      `<span class="lab-card-name">${meta.name}</span>` +
      `<span class="lab-tag ${tag.cls}">${tag.label}</span>` +
      `</div>` +
      `<div class="lab-card-trigger">${meta.trigger}</div>` +
      (summary ? `<div class="lab-card-summary">${summary}</div>` : "") +
      `<div class="lab-card-conclusion">${meta.conclusion}</div>`;
    card.onclick = () => { _labSignalDetailOpenModal(key); };
    list.appendChild(card);
  });
  leftCol.appendChild(list);

  // 搜索框事件：按卡片可见文本模糊过滤（大小写不敏感）
  const searchInput = searchWrap.querySelector(".lab-fusion-search");
  searchInput.addEventListener("input", () => {
    const q = searchInput.value.trim().toLowerCase();
    const cards = list.querySelectorAll(".lab-strategy-card");
    cards.forEach((card) => {
      if (!q) { card.style.display = ""; return; }
      card.style.display = card.textContent.toLowerCase().includes(q) ? "" : "none";
    });
  });

  // 回测推荐榜（列表页底部空白区，按指数加载 lab_simulate_{index}.json，不阻塞上方骨架）
  const rankSection = document.createElement("div");
  rankSection.className = "chart-card lab-rank-card";
  // 指数选择器（持久，不随 rank body 重渲染消失）。按钮组样式与"时间窗口"一致。
  const _curIdx = state.labSimIndex || "sh";
  const rankIdxBtns = LAB_SIM_INDEXES.map((x) =>
    `<button type="button" class="lab-idx-tab${x.id === _curIdx ? " active" : ""}" data-idx="${x.id}">${x.name}</button>`
  ).join("");
  rankSection.innerHTML = '<h3>🏆 回测推荐榜</h3>' +
    `<div class="lab-win-bar"><span class="lab-win-bar-label">选择指数</span><div class="lab-win-tabs">${rankIdxBtns}</div></div>` +
    '<div class="lab-rank-body"><div class="lab-rank-loading">⏳ 加载推荐榜数据中…</div></div>';
  rightCol.appendChild(rankSection);
  // 组装2栏
  wrapper.appendChild(leftCol);
  wrapper.appendChild(rightCol);
  content.appendChild(wrapper);
  const _loadRank = async () => {
    const idx = state.labSimIndex || "sh";
    const simData = await fetchLabSimData(idx);
    _labRankRerender(rankSection, simData);
  };
  _loadRank();
  // 指数切换：切换 active 按钮，重新加载该指数数据并重渲染 rank body
  rankSection.querySelectorAll(".lab-idx-tab").forEach((btn) => {
    btn.onclick = () => {
      state.labSimIndex = btn.dataset.idx;
      state.labRankShowAll = false;
      rankSection.querySelectorAll(".lab-idx-tab").forEach((b) => b.classList.toggle("active", b === btn));
      const body = rankSection.querySelector(".lab-rank-body");
      if (body) body.innerHTML = '<div class="lab-rank-loading">⏳ 加载中…</div>';
      _loadRank();
    };
  });

  // F5 恢复：更新 hash + 恢复滚动位置
  _labSetHash("#lab");
  _labRestoreScroll();
}

// === F5 刷新恢复：URL hash 记 tab+策略，sessionStorage 记滚动位置 ===
// 不改 app.js 的 tab 逻辑，通过 lab.js 自身初始化钩子实现恢复
let _labInitialRestore = false; // 仅首次加载时恢复滚动

// 更新 URL hash（replaceState 不触发 hashchange）
function _labSetHash(hash) {
  if (location.hash === hash) return;
  try { history.replaceState(null, "", location.pathname + location.search + hash); } catch (e) {}
}

// 恢复滚动位置（仅首次加载时执行一次）
function _labRestoreScroll() {
  if (!_labInitialRestore) return;
  _labInitialRestore = false;
  try {
    const y = parseInt(sessionStorage.getItem("labScrollY") || "0", 10);
    if (y > 0) requestAnimationFrame(() => window.scrollTo(0, y));
  } catch (e) {}
}

// 滚动位置持续保存到 sessionStorage（debounced）
let _labScrollTimer = null;
window.addEventListener("scroll", () => {
  if (state.tab !== "lab") return;
  if (_labScrollTimer) clearTimeout(_labScrollTimer);
  _labScrollTimer = setTimeout(() => {
    try { sessionStorage.setItem("labScrollY", String(window.scrollY)); } catch (e) {}
  }, 200);
}, { passive: true });

// 离开 lab tab 时清除 hash（避免从其他 tab F5 又跳回 lab）
document.querySelectorAll("button[data-tab]").forEach((b) => {
  if (b.dataset.tab !== "lab") {
    b.addEventListener("click", () => {
      if (location.hash.startsWith("#lab")) _labSetHash("");
    });
  }
});

// 初始加载：读 hash 恢复 tab + 策略（lab.js 在 app.js 之后加载，renderTab 已启动）
(function _labInitHashRestore() {
  const h = location.hash;
  if (!h || !h.startsWith("#lab")) return;
  _labInitialRestore = true;
  state.tab = "lab";
  const parts = h.slice(1).split("/"); // "lab/key" -> ["lab", "key"]
  if (parts[1] && LAB_STRATEGIES[parts[1]]) {
    state.labStrategy = parts[1];
  }
  // 激活 lab tab 按钮 -> 触发 renderTab -> renderSignalLab/renderLabDetail
  setTimeout(() => {
    const labBtn = document.querySelector('button[data-tab="lab"]');
    if (labBtn) labBtn.click();
  }, 0);
})();
