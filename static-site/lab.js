// === 策略实验 tab：22策略多周期回测矩阵 + BB_upper_revert 实验图表 ===
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

// 同日多信号拼色 pin（2026-07-22 方案A）：参照 app.js _buildSignalMarkData + _ntMultiColor。
// 单信号保持原单色 pin + label backgroundColor 彩色标签框样式；
// 多信号同日合并 1 个拼色 pin（symbolSize:44 + _ntMultiColor 渐变 + 金描边 + 光晕），
// 修复"每 signal 一个 pin -> 同日必重叠后画盖先画"问题。
// 信号字段：s.date/s.close（coord）+ s.color/s.label（可选，未带回退 lblColor/signalLabel）。
// _ntMultiColor 直接调 app.js 全局（lab.min.js 由 app.js L51 动态注入，加载顺序保证）。
function _labBuildMarkData(signals, lblColor, signalLabel) {
  const byDate = {};
  for (const s of signals) {
    if (!byDate[s.date]) byDate[s.date] = [];
    byDate[s.date].push(s);
  }
  const markData = [];
  for (const date of Object.keys(byDate).sort()) {
    const daySigs = byDate[date];
    const y = daySigs[0].close;
    if (daySigs.length === 1) {
      // 单信号：保持原样式（label backgroundColor 彩色标签框）
      const s = daySigs[0];
      const c0 = s.color || lblColor;
      const lbl0 = s.label || signalLabel || "信号";
      markData.push({
        coord: [date, y],
        value: lbl0,
        itemStyle: { color: c0 },
        label: { backgroundColor: c0 },
      });
    } else {
      // 多信号同日：拼色 pin（金描边+光晕）
      const labels = daySigs.map((s) => s.label || signalLabel || "信号");
      const segColors = daySigs.map((s) => s.color || lblColor);
      markData.push({
        coord: [date, y],
        value: labels.join("+"),
        symbolSize: 44,
        itemStyle: {
          color: _ntMultiColor(segColors),
          borderColor: "#ffd700",
          borderWidth: 3,
          shadowBlur: 8,
          shadowColor: "rgba(255,215,0,0.6)",
        },
        label: { fontSize: 11, color: "#fff", formatter: labels.join("\n"), lineHeight: 13 },
      });
    }
  }
  return markData;
}

// 通用实验图表：收盘价折线 + 自定义指标线 + 信号 markPoint
// indicators: [{name, data, color, dash}]  data 与 ohlc 等长（null=无值）
// signalLabel 用策略中文名，label 以彩色标签框显示在 pin 上方，hideOverlap 防密集重叠
function renderLabChartEx(title, ohlc, indicators, signals, container, chartArr, signalLabel, signalColor) {
  const c = mkCard(title, 400, null, container, chartArr);
  const dates = ohlc.map((d) => d.date);
  const lblColor = signalColor || "#9c27b0";
  // 同日多信号合并为 1 个拼色 pin（单信号保持单色 pin 原样式），避免重叠盖住
  const markData = _labBuildMarkData(signals, lblColor, signalLabel);
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
    name: "下轨拐点买", side: "buy", zone: "prod", status: "partial",
    trigger: "前一日收盘价跌破布林带下轨，当日收盘价收回下轨之上（超卖反弹）",
    conclusion: "3/4窗口达标并列靠前，近3年60d盈亏比1.84较高，与C1语义互补",
    theory: "布林带下轨回归。价格跌破下轨后收回，意味超卖极端已过、反弹拐点出现。与C1同为「超卖反弹」语义，但用价格穿越布林带下轨而非相对强弱指标(RSI)阈值，强势市更敏感。",
    scenario: "震荡市/下跌市超卖反弹；强势市中相对强弱指标未到30但价格已破下轨时补C1盲区。",
    note: "近1年是唯一达标买点（52.1%/1.23），与C1互补性较高。实验中：已实现图表（收盘价+布林带轨道+绿色实验买标注），未写入signal_daily。",
    report: "回测报告：布林下轨回归买达标数3/4（近10年/近3年/近1年），与C1并列靠前。近3年60d盈亏比1.79、均值+4.7%为买点较高。近1年（强势单边市）是唯一达标买点，补强C1在强势市的盲区。语义与C1正交（价格穿越 vs 相对强弱阈值），适合做互补买点。",
  },
  Supertrend_buy: {
    name: "趋势转向买", side: "buy", zone: "buy", status: "experimental",
    trigger: "真实波幅ATR(10)×3 趋势线从翻空转为翻多（趋势转向买）",
    conclusion: "2/4达标，语义与C1正交（趋势启动 vs 超卖反弹），互补性较高的候选",
    theory: "超级趋势(Supertrend)指标基于真实波幅(ATR)的动态趋势线。翻多意味趋势已确认启动，与C1的「超卖反弹」正交，捕捉的是趋势延续而非拐点。",
    scenario: "趋势启动确认；与C1互补覆盖不同市场状态。",
    note: "近3年全持有期胜率≥48.8%，盈亏比1.40-1.61。信号较C1稀疏。实验中：已实现图表（收盘价+超级趋势线+绿色实验买标注），未写入signal_daily。",
    report: "回测报告：超级趋势翻多买全史达标（51.4%/1.21），近3年20d/60d胜率≥49.7%盈亏比≥1.45。语义与C1正交（趋势启动 vs 超卖反弹），是互补性较高的候选。近3年10d均值+1.0%，60d均值+3.8%。",
  },
  Donchian20_up: {
    name: "上轨突破买", side: "buy", zone: "buy", status: "experimental",
    trigger: "收盘价突破近20日最高价（上轨突破买）",
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
    name: "均线5/20金叉买", side: "buy", zone: "buy", status: "experimental",
    trigger: "5日均线上穿20日均线（短期金叉买点）",
    conclusion: "1/4达标，信号密集胜率平庸",
    theory: "双均线金叉。短期均线上穿长期均线意味短期动量转强，经典趋势确认信号。",
    scenario: "趋势确认入场；震荡市频繁假金叉。",
    note: "信号最多（全史30754），但近3年胜率49.8%接近随机。60d盈亏比1.75较高。",
    report: "回测报告：均线5/20金叉买仅全史达标（1/4），近3年10d胜率49.8%接近随机。信号密集（全史30754个），胜率平庸。近3年60d盈亏比1.75、均值+4.9%是唯一亮点。",
  },
  MA_golden_10_60: {
    name: "均线10/60金叉买", side: "buy", zone: "buy", status: "experimental",
    trigger: "10日均线上穿60日均线（中长期金叉买点）",
    conclusion: "2/4达标，滞后严重",
    theory: "中长期双均线金叉。10日均线上穿60日均线确认中长期趋势转多，但60日均线滞后严重。",
    scenario: "中长期趋势确认；信号滞后，入场点偏晚。",
    note: "近3年胜率47.1%低于50%。全史样本11809较少。",
    report: "回测报告：均线10/60金叉买全史+近1年达标（2/4），近3年胜率47.1%低于50%。60日均线滞后严重，信号少且入场偏晚。全史60d均值+2.1%。",
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
    conclusion: "近3年5d/10d胜率居前(57%/54%)，与D1(20d较强)时间维度互补",
    theory: "布林带上轨回归。价格从上轨上方回落至下方，意味超买极端已过、短周期止盈拐点。与D1的「20日高回落5%」时间维度互补。",
    scenario: "短周期止盈/减仓提示；与D1（20d较强）双重确认。",
    note: "实验中，已实现图表（收盘价折线+布林带轨道+紫色实验卖标注）。未写入signal_daily。",
    report: "回测报告：布林上轨回落卖近3年5d胜率56.8%/10d胜率54.1%为卖点较高，短周期止盈较强。但样本仅5549（D1一半），20d后衰减。适合做D1的短周期互补（候选C）。全史PL0.87<1（卖点结构性问题），但方向胜率居前。",
  },
  MA_death_5_20: {
    name: "均线5/20死叉卖", side: "sell", zone: "sell", status: "experimental",
    trigger: "5日均线下穿20日均线（短期死叉卖点）",
    conclusion: "近3年20d胜率56.3%较高，短周期偏弱但中周期强",
    theory: "双均线死叉。短期均线下穿长期均线意味短期动量转弱，经典趋势转弱确认。",
    scenario: "趋势转弱减仓；震荡市频繁假死叉。",
    note: "近3年20d胜率54.8%较高，但5d/10d偏弱。PL0.90<1。实验中：已实现图表（收盘价+5日/20日均线+紫色实验卖标注），未写入signal_daily。",
    report: "回测报告：均线5/20死叉卖近3年20d胜率54.8%为卖点较高，10d胜率53.2%。均值-0.1%（方向正确）。但5d/10d偏弱，PL0.90<1（卖点结构性问题）。",
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
    name: "真实波幅追踪止损卖", side: "sell", zone: "sell", status: "experimental",
    trigger: "收盘价 < 近20日最高收盘价 − 3×真实波幅ATR(14)（追踪止损）",
    conclusion: "胜率刚过50%",
    theory: "真实波幅(ATR)追踪止损。基于波动率的动态止损线，价格跌破意味趋势已反转。真实波幅(ATR)自适应波动率。",
    scenario: "趋势跟踪止损；波动率大时止损线更宽。",
    note: "近3年10d胜率51.1%，PL0.86。全史PL0.96相对高。",
    report: "回测报告：真实波幅追踪止损卖近3年10d胜率51.1%、PL0.86。全史PL0.96为卖点较高之一。追踪止损型信号，胜率刚过50%。",
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
    name: "相对强弱下穿70卖", side: "sell", zone: "excluded", status: "excluded",
    trigger: "RSI(14) 前日≥70 且 当日<70（超买结束卖）",
    conclusion: "PL0.81最差，旧基线已弃",
    theory: "相对强弱指标(RSI)超买结束。相对强弱指标(RSI)从≥70回落意味超买结束，但回测显示方向相反（信号后价格仍涨）。",
    scenario: "不推荐使用。已弃用，改用D1。",
    note: "已排除。全史PL0.84最差，旧基线。已被“20日高回落5%卖”替代。",
    report: "回测报告：相对强弱下穿70卖 0/4达标，全史10d胜率48.7%/PL0.84/均值+0.9%（方向相反，信号后价格仍涨）。是所有卖点中最差的，旧基线已弃，改用D1。",
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
    name: "超级趋势翻空卖", side: "sell", zone: "excluded", status: "excluded",
    trigger: "真实波幅ATR(10)×3 趋势线从翻多转为翻空（趋势跟踪卖）",
    conclusion: "全史唯一PL≥1但近3年48.9%失效",
    theory: "超级趋势(Supertrend)翻空。趋势线翻空意味趋势已反转，但近年A股向上漂移致失效。",
    scenario: "不推荐使用。近年失效。",
    note: "已排除。全史PL0.95（接近1），但近3年胜率48.9%<50%失效。",
    report: "回测报告：超级趋势翻空卖 全史唯一PL≥1（0.95接近1，胜率51.9%），但近3年10d胜率48.9%/PL0.85失效。近年A股向上漂移致趋势跟踪卖点失效，明确排除。",
  },
  // --- 生产参考区（2个） ---
  C1_RSI30: {
    name: "超卖拐点买", side: "buy", zone: "prod", status: "live",
    trigger: "RSI(14) 从 ≤30 升回 >30 那天（超卖结束、价格有望反弹）",
    conclusion: "3/4达标，结构较稳健，当前主买点",
    theory: "相对强弱指标(RSI)经典超卖回归。相对强弱指标(RSI)≤30表示超卖，升回30之上意味空头力量衰竭、反弹拐点出现。事件化（仅穿越当日标）。",
    scenario: "震荡市/下跌市超卖反弹；通用主买点。按指数可收紧阈值至相对强弱指标上穿25（kc50/电力设备/传媒已配）。",
    note: "已上线生产。signal='buy'。近3年全持有期胜率>50%，盈亏比随持有期单调上升。",
    report: "回测报告：相对强弱上穿30买 达标数3/4（全史/近10年/近3年）并列靠前。近3年全持有期胜率>50%（5d54.2%/10d52.6%/20d56.5%/60d55.0%），盈亏比随持有期单调上升（1.38->1.17->1.52->1.68），60d均值+5.3%。结构较稳健，当前主用买点（回测表现较稳）。",
  },
  D1_high20_drop5: {
    name: "趋势转弱卖", side: "sell", zone: "prod", status: "live",
    trigger: "收盘价从近20日最高价回落 5%（前日≥阈 且 当日<阈），且收盘价>60日均线，且差离值<信号线",
    conclusion: "20d胜率55.7%样本最大，当前主卖点",
    theory: "基于最高价的回落止盈。从20日最高价回落5%意味趋势转弱，叠加60日均线多头过滤+MACD死叉确认。反应型信号（不预测顶部，反应已发生的弱势）。",
    scenario: "趋势转弱/止盈减仓提示；非做空/反向交易指令。胜率≈50%接近随机，不可作独立卖出指令。",
    note: "已上线生产。signal='sell'。卖点本质难预测（PL<1），D1是「最不坏」方案非「好」方案。",
    report: "回测报告：20日高回落5%卖 近3年20d胜率55.9%为卖点较高，样本9873最大（统计最稳）。10d均值-0.1%（方向正确）。盈亏比0.86<1（卖点结构性问题：A股向上漂移），但在所有卖点中PL仍属前列。维持现状合理，是「最不坏」方案。",
  },
};

// 策略释义映射（tooltip 悬停显示中文释义，仅展示用不改后端key）
const _LAB_STRAT_EN = {
  Supertrend_buy: "趋势转向买", Supertrend_sell: "超级趋势翻空卖",
  B0_RSI70: "相对强弱下穿70卖", C1_RSI30: "超卖拐点买",
  MA_golden_5_20: "均线5/20金叉买", MA_golden_10_60: "均线10/60金叉买",
  MA_death_5_20: "均线5/20死叉卖", ATR_trail_stop: "真实波幅追踪止损卖",
  BB_lower_revert: "下轨拐点买", BB_upper_revert: "布林上轨回落卖",
  BB_middle_break: "跌破布林中轨卖", BB_upper_break: "突破布林上轨买",
  Donchian20_up: "上轨突破买", Donchian55_up: "海龟55日突破买",
  Donchian10_down: "跌破10日最低卖", Donchian20_down: "跌破20日最低卖",
  MACD_golden: "MACD金叉买", MACD_death: "MACD死叉卖",
  KDJ_golden_oversold: "KDJ超卖金叉买", KDJ_death_overbought: "KDJ超买死叉卖",
  Vol_breakout: "放量突破买", D1_high20_drop5: "趋势转弱卖",
  F_D1_S1_MACD: "D1回落5%+60日均线多头+MACD死叉 融合卖", F_D1_S1: "D1回落5%+60日均线多头(豁免MACD) 融合卖",
  F_B1_RSI40: "布林下轨回归+相对强弱上穿40 融合买", F_B1_rebound2pct: "布林下轨回归+反弹2% 融合买",
  F_C1_MACD_golden: "相对强弱上穿30+MACD金叉 融合买", F_D1_MA_death: "D1回落5%+均线5/20死叉 融合卖",
};
// 策略名带释义 tooltip：<span title="中文释义">中文名</span>（echarts/纯文本场景请直接用 meta.name）
function _labStratNameHTML(key, name) {
  const en = _LAB_STRAT_EN[key];
  return en ? `<span title="${en}">${name}</span>` : (name || "");
}

// 4分区定义
const LAB_ZONES = [
  { key: "buy", label: "🧪 候选参考点(买)", count: 7, desc: "候选买方向参考点策略（含布林下轨/超级趋势实验中）" },
  { key: "sell", label: "🧪 候选参考点(卖)", count: 7, desc: "候选卖方向参考点策略（含布林上轨/均线死叉实验中）" },
  { key: "excluded", label: "📋 已排除", count: 6, desc: "反面教材（回测不达标已弃用）" },
  { key: "prod", label: "✅ 生产参考", count: 3, desc: "已上线生产策略" },
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

// === 融合信号注册表（多信号同日同时满足共振）===
// 字段与 LAB_STRATEGIES 对齐，新增 conditions 数组（组成条件列表）
const LAB_FUSION_STRATEGIES = {
  // --- 生产参考区（2个，主项目提取） ---
  F_D1_S1_MACD: {
    name: "D1回落5%+60日均线多头+MACD死叉 融合卖", side: "sell", zone: "prod", status: "live",
    conditions: ["20日高回落5%", "60日均线多头", "MACD死叉"],
    trigger: "同日同时满足：20日高回落5% + 60日均线多头 + MACD死叉",
    conclusion: "主项目生产卖点核心。降噪39%（卖点59830→36289），加MACD后历史回测正期望强度18.3%→43.3%",
    theory: "多信号融合卖点。20日高回落5%捕捉趋势转弱，叠加60日均线多头过滤（确保在上升趋势中止盈而非下跌中加空）和MACD死叉确认（动量转弱）。三条件同日同时满足，大幅降噪。",
    scenario: "上升趋势中回落止盈/减仓；三条件共振过滤假信号。非做空指令。",
    note: "主项目生产卖点核心。加MACD后降噪39%（卖点59830→36289），历史回测正期望强度18.3%→43.3%。已上线signal_daily。",
    report: "回测：加MACD死叉后信号从59830降至36289（降噪39%），历史回测正期望强度从18.3%升至43.3%，信号质量显著提升。主项目生产卖点“20日高回落5%卖”的融合形态。",
  },
  F_D1_S1: {
    name: "D1回落5%+60日均线多头（豁免MACD） 融合卖", side: "sell", zone: "prod", status: "live",
    conditions: ["20日高回落5%", "60日均线多头"],
    trigger: "同日同时满足：20日高回落5% + 60日均线多头（豁免MACD）",
    conclusion: "主项目s.*情绪分变体。对比“D1回落5%+60日均线多头+MACD死叉融合卖”可看MACD过滤的增益",
    theory: "D1回落5%+60日均线多头双条件融合。豁免MACD条件，因s.*情绪分序列加MACD后样本从106降至7，不足统计。用于对比“D1回落5%+60日均线多头+MACD死叉融合卖”可单独看MACD过滤的增益。",
    scenario: "s.*情绪分变体的融合卖点；与“D1回落5%+60日均线多头+MACD死叉融合卖”对比MACD过滤增益。",
    note: "主项目s.*情绪分变体。加MACD后样本n=106→7不足，故豁免MACD。",
    report: "回测：s.*情绪分变体的基础形态（不含MACD）。对比“D1回落5%+60日均线多头+MACD死叉融合卖”可看MACD过滤的增益效果。",
  },
  // --- 候选买点区（3个） ---
  F_B1_RSI40: {
    name: "布林下轨回归+相对强弱上穿40 融合买", side: "buy", zone: "candidate_buy", status: "partial",
    conditions: ["布林下轨回归", "相对强弱上穿40"],
    trigger: "同日同时满足：布林下轨回归 + 相对强弱上穿40",
    conclusion: "主项目10指数已配置 buy_aux rsi_cross_40。正期望强度 -38.5%->+16.2%转正（家电/轻工回测），胜率44.8%->54.5%，盈亏比0.66->1.19",
    theory: "多信号融合买点。布林下轨回归捕捉超卖反弹拐点，叠加相对强弱上穿40确认动量转强。两条件同日同时满足，过滤单一布林下轨穿越的假信号。",
    scenario: "超卖反弹+动量确认共振入场；震荡市/下跌市效果好。",
    note: "已作为 buy_aux 辅买点（per-index 增强）上线于 10 个指数：中证1000/创业板指/家电/轻工/医药/公用事业/房地产/社会服务/传媒/通信。非全局融合信号生产实现（B1基线+相对强弱上穿40过滤，signals.py:312-314）.",
    report: "回测：加相对强弱上穿40后正期望强度从-38.5%转正至+16.2%（家电/轻工样本），胜率44.8%->54.5%，盈亏比0.66->1.19。已扩展至10指数配置。",
  },
  F_B1_rebound2pct: {
    name: "布林下轨回归+反弹2% 融合买", side: "buy", zone: "candidate_buy", status: "partial",
    conditions: ["布林下轨回归", "反弹2%"],
    trigger: "同日同时满足：布林下轨回归 + 反弹2%（收盘价高于下轨2%）",
    conclusion: "主项目8指数已配置 buy_aux close_above_bl_2pct。正期望强度 -21%->+20%转正（基础化工回测），5d/10d/20d三horizon一致，n=19<30样本警示",
    theory: "多信号融合买点。布林下轨回归捕捉超卖反弹，叠加反弹2%过滤（close>下轨*1.02），过滤勉强穿越假信号和死猫反弹。",
    scenario: "超卖反弹确认入场；过滤假突破/死猫反弹。",
    note: "已作为 buy_aux 辅买点（per-index 增强）上线于 8 个指数：农林牧渔/基础化工/电子/纺织服饰/交通运输/机械设备/国防军工/计算机。非全局融合信号生产实现（B1基线+反弹2%过滤，signals.py:315-318）.",
    report: "回测：加反弹2%过滤后正期望强度从-21%转正至+20%（基础化工样本），5d/10d/20d三horizon一致。样本n=19<30偏小，需持续观察。已扩展至8指数配置。",
  },
  F_C1_MACD_golden: {
    name: "相对强弱上穿30+MACD金叉 融合买（实验性新组合）", side: "buy", zone: "candidate_buy", status: "experimental",
    conditions: ["相对强弱上穿30", "MACD金叉"],
    trigger: "同日同时满足：相对强弱上穿30 + MACD金叉",
    conclusion: "实验性新组合。超卖反弹+动量确认共振，待回测验证",
    theory: "实验性新组合。相对强弱上穿30捕捉超卖反弹拐点，叠加MACD金叉确认动量转强。两条件同日同时满足共振。",
    scenario: "超卖反弹+动量确认共振入场；实验性，待回测验证。",
    note: "实验室新组合，非主项目提取。需阶段二回测验证是否有价值。",
    report: "实验性新组合，暂无回测数据。阶段二将验证超卖反弹+动量确认共振的有效性。",
  },
  // --- 候选卖点区（1个） ---
  F_D1_MA_death: {
    name: "D1回落5%+均线5/20死叉 融合卖（实验性新组合）", side: "sell", zone: "candidate_sell", status: "experimental",
    conditions: ["20日高回落5%", "均线5/20死叉"],
    trigger: "同日同时满足：20日高回落5% + 均线5/20死叉",
    conclusion: "实验性新组合。回落+均线死叉共振，待回测验证",
    theory: "实验性新组合。20日高回落5%捕捉趋势转弱，叠加均线5/20死叉确认均线转弱。两条件同日同时满足共振。",
    scenario: "趋势转弱+均线死叉共振减仓；实验性，待回测验证。",
    note: "实验室新组合，非主项目提取。需阶段二回测验证是否有价值。",
    report: "实验性新组合，暂无回测数据。阶段二将验证回落+均线死叉共振的有效性。",
  },
};

// === 策略实验室术语词典（白话解释，统一入口）===
// key -> { name: 术语名, desc: 白话释义 }。_labHelpIcon(termKey) 与 ❓词典modal 共用此表。
const _LAB_GLOSSARY = {
  co_resonance: {
    name: "同向共振（双买/双卖共振）",
    desc: "两个同方向（都买或都卖）的信号在同一天同时触发才算有效。双买共振=两个买点同日触发，买点更可靠；双卖共振=两个卖点同日触发，卖点更确认。与“配对”（一买一卖组完整交易）不同，共振是同向叠加增强。本实验室把7个候选买点两两组合（C(7,2)=21对）、7个候选卖点两两组合（21对）自动回测。",
  },
  fusion_signal: {
    name: "融合信号（F_ 前缀）",
    desc: "把多个单一信号用“同日同时满足”组合成一个新信号——所有条件同日都满足才触发，用多条件共振过滤假信号。分两类：①6个预定义（F_开头，主项目提取已验证）；②运行时自动两两组合的候选（待回测）。与同向共振区别：融合是异向多条件同时满足成新策略，同向共振是同向两信号叠加。",
  },
  pair: {
    name: "配对（买点+卖点）",
    desc: "一个买点信号+一个卖点信号组成一对完整交易（买入→卖出算一笔）。7买×7卖=49对。配对回测=按这对信号模拟历史交易，算净值曲线/胜率/回撤。",
  },
  score: {
    name: "综合评分（0-100）",
    desc: "0-100分=收益率(35%)+胜率(25%)+回撤倒数(15%)+风险调整(15%)+样本量(10%)，收益/胜率/回撤/风险调整先winsorize(前后1%截断)抗极端值再min-max归一化到[0,1]，样本量用凹函数1-exp(-n/30)抗大样本线性通胀，加权后×100，越高越综合优秀。",
  },
  windows: {
    name: "5窗口（时间窗口）",
    desc: "分全史/近10/5/3/1年5档，看策略在不同时段是否都稳定（防只在某段行情碰巧赚钱）。默认近5年兼顾样本量与时效；全历史样本最大但含远古行情可能失真；近1年看当前市场适配度。",
  },
  status: {
    name: "状态：生产参考 / 实验中 / 开发中 / 已排除",
    desc: "生产参考=已上线主功能图表的策略，可信度最高；实验中=回测达标但未上线，仅供参考验证；开发中=待回测；已排除=回测不达标弃用，作反面教材。实验中策略不可直接实盘。",
  },
  count: {
    name: "候选数量（91/128/182）",
    desc: "候选池：7买×7卖=49配对 + 买×买C(7,2)=21 + 卖×卖C(7,2)=21，共91候选；配对对比榜按2回测模式（全仓/定额）展开为多组排序。",
  },
  risk_adjust: {
    name: "风险调整（类 Calmar）",
    desc: "Calmar比率=年化收益率÷最大回撤，分母下限2%（回撤极小时保守视作2%，避免微小回撤算出虚高分）。衡量“每承受1%回撤能换多少收益”，越高越好，比单看收益更能反映风险性价比。",
  },
  profit_factor: {
    name: "利润因子（Profit Factor）",
    desc: "总盈利笔收益和÷总亏损笔收益和绝对值。>1盈利系统，>2优秀。全胜（无亏损笔）时显示∞。百分比口径与胜率同源。",
  },
  payoff_ratio: {
    name: "盈亏比（Payoff Ratio）",
    desc: "平均盈利÷平均亏损绝对值。如1.5=每笔赚的是亏的1.5倍。高盈亏比可弥补低胜率。全胜时显示∞。",
  },
  sharpe: {
    name: "夏普比率（Sharpe）",
    desc: "年化夏普=收益率均值÷标准差×√252（无风险利率0）。衡量每承担1单位总波动换多少超额收益，>1尚可，>2优秀。基于事件点收益率近似（与回撤同源非完整日K）。",
  },
  sortino: {
    name: "索提诺比率（Sortino）",
    desc: "年化索提诺=收益率均值÷下行波动×√252。与夏普类似但只计下行风险（亏损方向波动），对“上涨波动”不惩罚，比夏普更贴合投资者真实感受，通常≥夏普。",
  },
  expectancy: {
    name: "期望值（Expectancy）",
    desc: "单笔期望收益率%=胜率×平均盈利+败率×平均亏损。正值=长期每笔期望赚钱，负值=亏钱。综合胜率与盈亏比，是策略可行性的核心指标。",
  },
  win_rate: {
    name: "胜率",
    desc: "盈利交易笔数÷总交易笔数。70%=10笔里约7笔赚。需结合盈亏比看，高胜率低盈亏比未必赚钱。",
  },
  max_drawdown: {
    name: "最大回撤",
    desc: "历史从最高点到最低点的最大跌幅。27.4%=曾经最多亏27.4%，衡量最坏情况下的亏损幅度。",
  },
  retest: {
    name: "二次测试（稳健性三件套）",
    desc: "稳健性验证三件套：①分年回测-防某年暴利拉高整体 ②样本外-前70%训练后30%验证防过拟合 ③极端行情-2015股灾/2018熊/2020疫情/2024反弹各regime回撤。优先做这3种因其为验证核心，成本低结论明确。⭐️进入规则:近5/3/1年三窗口最大回撤均≤10%且交易≥10次，且(综合评分≥0.6 且 胜率≥55% 且 风险调整≥1.5)三者同时满足(AND收紧)。",
  },
};

// === 术语词典 modal + ❓图标（解释层，不碰任何业务逻辑）===
// _labHelpIcon(termKey)：返回小❓图标HTML，点击打开词典modal并定位高亮该词。
// 全局事件委托绑定 [data-glossary] click（参考 app.js [data-tip] 委托模式，但在 lab.js 自建）。
// 注意：此函数不得依赖 _LAB_GLOSSARY（该 const 定义在后），因 F_D1_S1_MACD.conclusion 在
// 模块加载期即调用本函数（对象字面量求值），此时 _LAB_GLOSSARY 尚处 TDZ。故此处不读取它，
// 仅生成 data-glossary 锚点；术语名校验/释义展示由 modal 端（_labGlossaryModalHTML，点击时才跑）负责。
function _labHelpIcon(termKey) {
  return `<span class="lab-help-icon" data-glossary="${termKey}" role="button" tabindex="0" aria-label="查看术语解释">❓</span>`;
}

// 词典 modal HTML（复用 lab-signal-modal 容器样式）
function _labGlossaryModalHTML(termKey) {
  const items = Object.entries(_LAB_GLOSSARY).map(([k, v]) =>
    `<div class="lab-glossary-item${k === termKey ? " lab-glossary-highlight" : ""}" data-gkey="${k}">` +
    `<div class="lab-glossary-name">${v.name}</div>` +
    `<div class="lab-glossary-desc">${v.desc}</div>` +
    `</div>`
  ).join("");
  return `<div class="lab-signal-modal lab-glossary-modal">` +
    `<div class="lab-signal-modal-head">` +
    `<span class="lab-signal-modal-title">📖 策略实验室 · 术语词典</span>` +
    `<button type="button" class="lab-rank-modal-close" aria-label="关闭">✕</button>` +
    `</div>` +
    `<div class="lab-signal-modal-body">` +
    `<div class="lab-glossary-search-wrap"><input type="text" class="lab-glossary-search" placeholder="搜索术语名/释义…" autocomplete="off"></div>` +
    `<div class="lab-glossary-list">${items}</div>` +
    `<div class="lab-glossary-foot">共 ${Object.keys(_LAB_GLOSSARY).length} 个术语 · 点❓图标可定位到对应解释</div>` +
    `</div></div>`;
}

function _labGlossaryOpenModal(termKey) {
  let overlay = document.getElementById("labGlossaryOverlay");
  if (!overlay) {
    overlay = document.createElement("div");
    overlay.id = "labGlossaryOverlay";
    overlay.className = "lab-signal-overlay";
    document.body.appendChild(overlay);
  }
  overlay.innerHTML = _labGlossaryModalHTML(termKey);
  overlay.classList.add("show");
  document.body.style.overflow = "hidden";
  overlay.onclick = (e) => { if (e.target === overlay) _labGlossaryCloseModal(); };
  overlay.querySelector(".lab-rank-modal-close").onclick = _labGlossaryCloseModal;
  // 搜索过滤：按 name/desc 模糊匹配（大小写不敏感）
  const search = overlay.querySelector(".lab-glossary-search");
  if (search) {
    search.addEventListener("input", () => {
      const q = search.value.trim().toLowerCase();
      overlay.querySelectorAll(".lab-glossary-item").forEach((it) => {
        if (!q) { it.style.display = ""; return; }
        it.style.display = it.textContent.toLowerCase().includes(q) ? "" : "none";
      });
    });
  }
  // 定位高亮：滚动到目标术语
  if (termKey) {
    const hi = overlay.querySelector(".lab-glossary-highlight");
    if (hi) setTimeout(() => { try { hi.scrollIntoView({ block: "center", behavior: "smooth" }); } catch (e) {} }, 60);
  }
}

function _labGlossaryCloseModal() {
  const overlay = document.getElementById("labGlossaryOverlay");
  if (overlay) {
    overlay.classList.remove("show");
    overlay.innerHTML = "";
    overlay.onclick = null;
  }
  document.body.style.overflow = "";
}

// 全局事件委托：点 [data-glossary] 或键盘 Enter/Space 触发 -> 打开词典并定位
// ⚠️ click 用 capture 阶段：❓常嵌在排行榜行(.lab-rank-item)内，冒泡委托的 stopPropagation 来不及
// 阻止行 onclick(冒泡更早在 item 层已触发配对详情弹窗，致双弹窗)。capture 在 document 层先于
// item 冒泡触发，stopPropagation 阻止事件继续到 target/冒泡，行 onclick 不触发，只弹词典 modal。
(function _initLabGlossaryDelegation() {
  document.addEventListener("click", (e) => {
    const el = e.target.closest("[data-glossary]");
    if (!el) return;
    e.preventDefault();
    e.stopPropagation();
    _labGlossaryOpenModal(el.getAttribute("data-glossary"));
  }, true); // capture：先于排行榜行 onclick(冒泡)，stopPropagation 才能生效
  document.addEventListener("keydown", (e) => {
    if ((e.key === "Enter" || e.key === " ") && e.target && e.target.closest && e.target.closest("[data-glossary]")) {
      e.preventDefault();
      _labGlossaryOpenModal(e.target.getAttribute("data-glossary"));
    }
  });
})();

// lab❓ hover pop 预览（"全要"：hover 简短释义 + 点击完整词典 modal）。
// _labHelpIcon 因 TDZ 不能在生成时读 _LAB_GLOSSARY，故用 capture 阶段 mouseover 懒填充 data-tip：
// hover 时（_LAB_GLOSSARY 已定义）取 desc 截断填入 data-tip，交由 app.js termTip 冒泡委托显示 .term-pop 浮层。
// 点击仍走上方 [data-glossary] click capture -> _labGlossaryOpenModal。
(function _initLabGlossaryHoverPop() {
  document.addEventListener("mouseover", function (e) {
    var el = e.target.closest && e.target.closest("[data-glossary]");
    if (!el || el.hasAttribute("data-tip")) return; // 已有 data-tip 不重复填（避免覆盖 termTip/原生 title 迁移值）
    var key = el.getAttribute("data-glossary");
    var entry = typeof _LAB_GLOSSARY !== "undefined" && _LAB_GLOSSARY[key];
    if (!entry) return;
    var desc = String(entry.desc || "").replace(/\s+/g, " ").trim();
    if (desc.length > 140) desc = desc.slice(0, 140) + "…";
    el.setAttribute("data-tip", (entry.name ? entry.name + "：" : "") + desc + "（点击❓查看完整词典）");
  }, true); // capture：先于 app.js 冒泡 mouseover 填充，让其接管显示
})();

// 6硬编码融合策略 -> base单一策略key映射（仅用于信号图/多周期矩阵/查看买卖信号按钮，
// 模拟回测仍走真实F_pair融合回测数据，非_coreKey代理）
const FUSION_CHART_BASE = {
  F_D1_S1_MACD: "D1_high20_drop5",
  F_D1_S1: "D1_high20_drop5",
  F_B1_RSI40: "BB_lower_revert",
  F_B1_rebound2pct: "BB_lower_revert",
  F_C1_MACD_golden: "C1_RSI30",
  F_D1_MA_death: "D1_high20_drop5",
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
    if (n.includes("下轨拐点")) return "下轨拐点";
    if (n.includes("超卖拐点")) return "超卖拐点";
    if (n.includes("趋势转弱")) return "趋势转弱";
    if (n.includes("布林下轨")) return "布林下轨";
    if (n.includes("超级趋势")) return "超级趋势";
    if (n.includes("趋势转向")) return "趋势转向";
    if (n.includes("唐奇安")) return "唐奇安" + (n.includes("55") ? "55" : "20");
    if (n.includes("上轨突破")) return "上轨突破";
    if (n.includes("海龟")) return "海龟55";
    if (n.includes("均线")) return "均线" + (n.includes("5/20") ? "5/20" : "10/60");
    if (n.includes("MACD")) return "MACD";
    if (n.includes("布林上轨")) return "布林上轨";
    if (n.includes("跌破布林中轨")) return "布林中轨";
    if (n.includes("跌破10日")) return "破10日低";
    if (n.includes("跌破20日")) return "破20日低";
    if (n.includes("真实波幅")) return "真实波幅止损";
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
        trigger: `同日同时满足：${buy.trigger} 且 ${sell.trigger}`,
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
        trigger: `同日同时满足：${b1.trigger} 且 ${b2.trigger}`,
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
        trigger: `同日同时满足：${s1.trigger} 且 ${s2.trigger}`,
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
  { key: "candidate_buy", label: "🧪 候选参考点(买)", count: "3+70", desc: "融合候选买方向参考点（多信号共振入场，含70+自动生成待回测）" },
  { key: "candidate_sell", label: "🧪 候选参考点(卖)", count: "1+21", desc: "融合候选卖方向参考点（多信号共振出场，含21自动生成待回测）" },
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

// 取某窗口的数据：stats(单窗口) + trades(优先 win_trades 窗口独立 sim,回退 tw 切片) + equity_curve(该窗口独立)
// equity_curve 为每窗口独立从 INITIAL_CAPITAL 起算的净值曲线 dict {all,y10,y5,y3,y1}
// hasFull 标记 full 数据(trades/equity_curve/win_trades)是否已加载，未加载时仅 stats 可用
function _labPairWinData(pairData, mode, win, simData) {
  const md = pairData && pairData[mode];
  if (!md) return null;
  const stats = (md.stats && md.stats[win]) || null;
  const tw = md.tw && md.tw[win];
  // 优先读 win_trades(每窗口独立 sim 的 trades,at/cp 均从 INITIAL_CAPITAL 起算,与该窗口
  // stats final_total/total_ret 同源同口径)。回退旧 JSON:trades 按 tw 切片 + win_base_cp 调整。
  const wtd = md.win_trades && md.win_trades[win];
  let trades, fromWinSim;
  if (wtd) {
    trades = wtd;
    fromWinSim = true;
  } else {
    trades = (tw && md.trades) ? md.trades.slice(tw[0], tw[1]) : (md.trades || []);
    fromWinSim = false;
  }
  // winBaseCp: 窗口起点"前一笔"的累计盈亏(全历史值)。仅旧路径(fromWinSim=false)需要:
  // 渲染时用 (t.cp - winBaseCp) 把窗口内累计从0重算,与上方总收益率卡片对齐。
  // 优先读后端预计算的精确值(横跨交易已补 pre-window P&L，消除首条 cpVal 偏移/符号翻转)；
  // 回退现逻辑(旧 JSON 兼容)：tw[0]=0 时无前一笔 winBaseCp=0，否则取前一笔全史累计盈亏。
  let winBaseCp = 0;
  if (!fromWinSim) {
    if (md.win_base_cp && md.win_base_cp[win] != null) {
      winBaseCp = md.win_base_cp[win];
    } else if (tw && md.trades && tw[0] > 0) {
      const prevTrade = md.trades[tw[0] - 1];
      if (prevTrade && prevTrade.cp != null) winBaseCp = prevTrade.cp;
    }
  }
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
  const hasFull = !!md.trades || !!ec || !!md.win_trades;
  // open_positions: 未平仓持仓(按收盘价重估浮盈亏),每窗口独立 {all,y10,y5,y3,y1}
  const openPositions = (md.open_positions && md.open_positions[win]) || [];
  return { stats, trades, equity_curve, hasFull, winBaseCp, fromWinSim, openPositions };
}

// 窗口切换 tabs HTML（默认近1年：全史太密）
function _labWinTabsHTML() {
  const cur = state.labSimWindow || "y5";
  return '<div class="lab-win-tabs">' + LAB_WIN_DEFS.map((w) =>
    `<button type="button" class="lab-win-tab${w.k === cur ? " active" : ""}" data-win="${w.k}">${w.l}</button>`
  ).join("") + "</div>";
}

// 弹窗内窗口切换 tabs（接收当前 win 参数，独立于全局 state.labSimWindow；单一信号/融合弹窗三区一致复用）
function _labModalWinTabsHTML(win) {
  return '<div class="lab-win-tabs">' + LAB_WIN_DEFS.map((w) =>
    `<button type="button" class="lab-win-tab${w.k === win ? " active" : ""}" data-win="${w.k}">${w.l}</button>`
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
  BB: { name: "布林带", en: "Bollinger Bands", plain: "用近20日均价和波动幅度画的价格通道。触及上轨=近期偏贵可能回落，触及下轨=偏便宜可能反弹，中轨=20日均线。" },
  Supertrend: { name: "超级趋势", en: "Supertrend", plain: "基于波动率(ATR)画的趋势跟踪线。翻红=转多(买)，翻绿=转空(卖)。" },
  MA: { name: "均线", en: "Moving Average", plain: "近N个交易日的平均价。短期均线在长期均线之上=多头排列、趋势向上，反之=空头、趋势向下。" },
  Donchian: { name: "唐奇安通道", en: "Donchian Channel", plain: "近N日最高价和最低价画的通道。价格突破上轨=创新高看多，跌破下轨=创新低看空。" },
  MACD: { name: "MACD", en: "MACD", plain: "动量指标。DIF上穿DEA=金叉看多，DIF下穿DEA=死叉看空。" },
  KDJ: { name: "KDJ", en: "KDJ", plain: "超买超卖指标。K线上穿D线=金叉(低位更准)，K线下穿D线=死叉(高位更准)。" },
  RSI: { name: "相对强弱", en: "Relative Strength Index", plain: "0-100的强弱指标。<30超卖(跌多了可能反弹)，>70超买(涨多了可能回落)。" },
  ATR: { name: "真实波幅", en: "Average True Range", plain: "衡量波动剧烈程度，数值越大波动越猛。追踪止损线=近期高点-3倍ATR，跌破即止损。" },
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
      chartTitle: `${name} · 趋势转向实验`, statLabel: "实验买点",
    };
  } else if (key === "MA_death_5_20") {
    const r2 = computeMADeathCrossLab(ohlc);
    return {
      indicators: [
        { name: "5日均线", data: r2.ma5, color: "#1f6feb", dash: false },
        { name: "20日均线", data: r2.ma20, color: "#f0883e", dash: false },
      ],
      signals: r2.signals, signalLabel, signalColor: "#9c27b0",
      chartTitle: `${name} · 均线5/20死叉实验`, statLabel: "实验卖点",
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
        { name: "布林中轨(20日均线)", data: bb.mid, color: cssVar('--text-3'), dash: false },
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
      chartTitle: `${name} · 超级趋势翻空`, statLabel,
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
      indicators: [{ name: "真实波幅追踪止损线", data: r.trail, color: "#c92a2a", dash: true }],
      signals: r.signals, signalLabel, signalColor: sigColor,
      chartTitle: `${name} · 真实波幅追踪止损`, statLabel,
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

// === 融合信号与图表配置（方向B：前端实现多条件同日同时满足交集，画融合信号点，非基础策略代理）===
// 6硬编码融合策略的英文成分条件兜底（优先用 fusion_meta.components，对齐 fusion_signals.py HARDCODED_FUSIONS）
const FUSION_HARDCODED_COMPONENTS = {
  F_D1_S1_MACD: ['D1_high20_drop5', 'MA60_bull', 'MACD_below_signal'],
  F_D1_S1: ['D1_high20_drop5', 'MA60_bull'],
  F_B1_RSI40: ['BB_lower_revert', 'RSI_cross_40'],
  F_B1_rebound2pct: ['BB_lower_revert', 'close_above_bl_2pct'],
  F_C1_MACD_golden: ['C1_RSI30', 'MACD_golden'],
  F_D1_MA_death: ['D1_high20_drop5', 'MA_death_5_20'],
};

// 过滤条件（状态/穿越，非单信号策略）触发日期 Set，对齐 fusion_signals._gen_filter_masks
// MA60_bull: close>MA60；MACD_below_signal: DIF<DEA；RSI_cross_40: rp<=40 & r>40；close_above_bl_2pct: close>bl*1.02
function _labFusionFilterDateSet(key, ohlc) {
  const closes = ohlc.map((d) => d.close);
  const len = ohlc.length;
  const s = new Set();
  if (key === 'MA60_bull') {
    const ma60 = _smaLab(closes, 60);
    for (let i = 0; i < len; i++) if (ma60[i] != null && closes[i] > ma60[i]) s.add(ohlc[i].date);
    return s;
  }
  if (key === 'MACD_below_signal') {
    const m = computeMACDLab(ohlc);
    for (let i = 0; i < len; i++) if (m.dif[i] != null && m.dea[i] != null && m.dif[i] < m.dea[i]) s.add(ohlc[i].date);
    return s;
  }
  if (key === 'RSI_cross_40') {
    const r = computeRSILab(ohlc, 14);
    for (let i = 1; i < len; i++) if (r[i] != null && r[i - 1] != null && r[i - 1] <= 40 && r[i] > 40) s.add(ohlc[i].date);
    return s;
  }
  if (key === 'close_above_bl_2pct') {
    const bb = computeBBLab(ohlc);
    for (let i = 0; i < len; i++) if (bb.bl[i] != null && closes[i] > bb.bl[i] * 1.02) s.add(ohlc[i].date);
    return s;
  }
  return null;
}

// 单信号策略触发日期 Set（复用 _labBuildChartConfig 的 signals）
function _labSignalDateSet(key, ohlc) {
  if (!LAB_CHART_KEYS[key]) return null;
  const cfg = _labBuildChartConfig(key, ohlc, '');
  if (!cfg || !cfg.signals) return null;
  const s = new Set();
  cfg.signals.forEach((sig) => s.add(sig.date));
  return s;
}

// 成分条件触发日期 Set（单信号策略走 _labSignalDateSet，过滤条件走 _labFusionFilterDateSet）
function _labComponentDateSet(key, ohlc) {
  return LAB_CHART_KEYS[key] ? _labSignalDateSet(key, ohlc) : _labFusionFilterDateSet(key, ohlc);
}

// 构建融合信号图配置（91候选 A/A/A 方案：合并双策略指标 indMap 去重 + 双色信号点）
// - 91候选(buy_sell/buy_buy/sell_sell)：复用 _labSignalOpenModal 的 indMap 去重 + 双色信号逻辑，
//   两成分策略指标按 name 去重合并、信号按 side 着色（买红/卖绿，同侧第二成分用区分色），不再 buy_sell return null
// - 6硬编码：保留同时满足共振（主信号 baseKey 指标 + 交集信号单色），有独立融合语义
// components: 成分条件英文 key 数组（6硬编码从 fusion_meta.components 取）
function _labBuildFusionChartConfig(meta, ohlc, idxName, isHardcoded, components) {
  if (isHardcoded) {
    const compKeys = components || FUSION_HARDCODED_COMPONENTS[meta._fusionKey];
    const baseKey = FUSION_CHART_BASE[meta._fusionKey];
    const fmeta = LAB_FUSION_STRATEGIES[meta._fusionKey] || meta;
    const side = fmeta.side;
    if (!compKeys || !baseKey || !LAB_CHART_KEYS[baseKey]) return null;
    const baseCfg = _labBuildChartConfig(baseKey, ohlc, idxName);
    if (!baseCfg) return null;
    // 各成分触发日期 Set，取交集
    const sets = [];
    for (const k of compKeys) {
      const s = _labComponentDateSet(k, ohlc);
      if (!s) return null;
      sets.push(s);
    }
    let fusion = sets[0];
    for (let i = 1; i < sets.length; i++) {
      const next = new Set();
      fusion.forEach((d) => { if (sets[i].has(d)) next.add(d); });
      fusion = next;
    }
    const signals = ohlc.filter((d) => fusion.has(d.date)).map((d) => ({ date: d.date, close: d.close }));
    const isBuy = side === 'buy';
    return {
      indicators: baseCfg.indicators,
      signals,
      signalLabel: fmeta.name || '融合信号',
      signalColor: isBuy ? '#2e7d32' : '#9c27b0',
      chartTitle: `${idxName} · ${fmeta.name || '融合信号'}（同时满足共振）`,
      statLabel: isBuy ? '融合买点' : '融合卖点',
    };
  }
  // 91候选：合并双策略指标(indMap 去重) + 双色信号（复用 _labSignalOpenModal 合并逻辑）
  const pt = meta._pairType;
  const k1 = meta._buyKey, k2 = meta._sellKey;
  if (!k1 || !k2) return null;
  const cfg1 = LAB_CHART_KEYS[k1] ? _labBuildChartConfig(k1, ohlc, idxName) : null;
  const cfg2 = LAB_CHART_KEYS[k2] ? _labBuildChartConfig(k2, ohlc, idxName) : null;
  if (!cfg1 && !cfg2) return null;
  // 合并指标线（按 name 去重，避免 BB 双轨/MA 重复绘制）
  const indMap = new Map();
  [cfg1, cfg2].forEach((cfg) => {
    if (!cfg) return;
    cfg.indicators.forEach((it) => { if (!indMap.has(it.name)) indMap.set(it.name, it); });
  });
  const indicators = Array.from(indMap.values());
  // 双色信号：按成分策略 side 着色，同侧第二成分用区分色（买红/卖绿，第二买橙/第二卖紫）
  const s1Meta = LAB_STRATEGIES[k1] || {}, s2Meta = LAB_STRATEGIES[k2] || {};
  const side1 = s1Meta.side, side2 = s2Meta.side;
  const name1 = s1Meta.name || k1, name2 = s2Meta.name || k2;
  const BUY_C = '#c92a2a', SELL_C = '#2e7d32', BUY_C2 = '#f0883e', SELL_C2 = '#9c27b0';
  const color1 = side1 === 'sell' ? SELL_C : BUY_C;
  const color2 = (side2 !== side1)
    ? (side2 === 'sell' ? SELL_C : BUY_C)
    : (side2 === 'sell' ? SELL_C2 : BUY_C2);
  const sigs1 = ((cfg1 && cfg1.signals) || []).map((s) => ({ date: s.date, close: s.close, color: color1, label: name1 }));
  const sigs2 = ((cfg2 && cfg2.signals) || []).map((s) => ({ date: s.date, close: s.close, color: color2, label: name2 }));
  const signals = sigs1.concat(sigs2).sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
  const typeLabel = pt === 'buy_sell' ? '配对' : (pt === 'buy_buy' ? '双买共振' : '双卖共振');
  return {
    indicators,
    signals,
    signalLabel: '成分信号',
    signalColor: color1,
    chartTitle: `${idxName} · ${name1} × ${name2}（${typeLabel}·成分策略合并）`,
    statLabel: '成分策略信号',
    signalParts: [
      { label: name1, color: color1 },
      { label: name2, color: color2 },
    ],
  };
}

// 获取按指数拆分的融合矩阵数据（lab_backtest_fusion_{index}.json，97候选 5窗口×4horizon）
async function fetchLabFusionMatrixData(idx) {
  idx = idx || "sh";
  if (!state.labFusionMatrixDataMap) state.labFusionMatrixDataMap = {};
  if (state.labFusionMatrixDataMap[idx]) return state.labFusionMatrixDataMap[idx];
  try {
    state.labFusionMatrixDataMap[idx] = await fetchJSON("https://ssd.fx8.store/lab/lab_backtest_fusion_" + idx + ".json");
  } catch (e) {
    state.labFusionMatrixDataMap[idx] = null;
  }
  return state.labFusionMatrixDataMap[idx];
}

// 获取 lab_backtest.json 数据（缓存到 state.labData）
// web 版走 /static/ 挂载点（main.py 的 StaticFiles(directory=web)），static 版走 ./data/
async function fetchLabData() {
  if (state.labData) return state.labData;
  try {
    state.labData = await fetchJSON("https://ssd.fx8.store/lab/lab_backtest.json");
  } catch (e) {
    state.labData = null;
  }
  return state.labData;
}

// 获取手续费/滑点成本对比数据（毛/净收益对比，缓存到 state.labCostCompare）
// 口径：top10策略配对/指数 × 3成本档(gross/low/high) × 2窗口(all/y5)，与模拟回测同源同口径
// 覆盖范围有限(仅top10配对+2窗口)，非覆盖时回退通用毛收益提示
async function fetchLabCostCompare() {
  if (state._labCostCompare !== undefined) return state._labCostCompare;
  try {
    state._labCostCompare = await fetchJSON("./data/lab_cost_compare.json");
  } catch (e) {
    state._labCostCompare = null;
  }
  return state._labCostCompare;
}

// 查某(index_id, pair_id, mode, window) 的成本对比数据
// 返回 {gross_ret, low_ret, high_ret, low_decay_ratio, high_decay_ratio, detail} 或 null
function _labLookupCost(cc, indexId, pairId, mode, win) {
  if (!cc || !cc.indexes) return null;
  const ix = cc.indexes.find((x) => x.index_id === indexId);
  if (!ix || !ix.pairs) return null;
  const p = ix.pairs.find((x) => x.pair_id === pairId);
  if (!p) return null;
  const md = p[mode];
  if (!md) return null;
  return md[win] || null;
}

// 获取按指数拆分的矩阵数据（lab_backtest_{index}.json）
// idx="all" 时加载全市场聚合数据（lab_backtest.json），复用 fetchLabData 缓存
async function fetchLabMatrixData(idx) {
  idx = idx || "all";
  if (idx === "all") return fetchLabData();
  if (!state.labMatrixDataMap) state.labMatrixDataMap = {};
  if (state.labMatrixDataMap[idx]) return state.labMatrixDataMap[idx];
  try {
    state.labMatrixDataMap[idx] = await fetchJSON("https://ssd.fx8.store/lab/lab_backtest_" + idx + ".json");
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

// 指数 ID -> 中文名（复用 LAB_SIM_INDEXES，取不到兜底显示原始 ID，避免 undefined）
function _labIdxName(id) {
  if (!id) return "";
  return (LAB_SIM_INDEXES.find((x) => x.id === id) || {}).name || id;
}

// 获取 lab_sim_{index}_stats.json 数据（小文件，配对排行/矩阵/配对卡片秒开）
// per-index 缓存到 state.labSimDataMap。详情(trades/equity_curve)由 fetchLabSimFullData 按需加载并合并。
// web 版走 /static/ 挂载点（main.py 的 StaticFiles(directory=web)），static 版走 ./data/
async function fetchLabSimData(index) {
  index = index || "sh";
  if (!state.labSimDataMap) state.labSimDataMap = {};
  if (state.labSimDataMap[index]) return state.labSimDataMap[index];
  try {
    state.labSimDataMap[index] = await fetchJSON("https://ssd.fx8.store/lab/lab_sim_" + index + "_stats.json");
  } catch (e) {
    state.labSimDataMap[index] = null;
  }
  return state.labSimDataMap[index];
}

// 获取 lab_sim_{index}_fusion_stats.json 数据（融合91对：49买×卖 + 21买×买 + 21卖×卖共振）
// per-index 缓存到 state.labSimFusionDataMap（独立于单信号 stats 缓存，避免互相覆盖）
async function fetchLabFusionSimData(index) {
  index = index || "sh";
  if (!state.labSimFusionDataMap) state.labSimFusionDataMap = {};
  if (state.labSimFusionDataMap[index]) return state.labSimFusionDataMap[index];
  try {
    state.labSimFusionDataMap[index] = await fetchJSON("https://ssd.fx8.store/lab/lab_sim_" + index + "_fusion_stats.json");
  } catch (e) {
    state.labSimFusionDataMap[index] = null;
  }
  return state.labSimFusionDataMap[index];
}

// 检查某指数 fusion full 数据是否已合并入 fusion 缓存
function _labSimFusionFullLoaded(index) {
  index = index || "sh";
  return !!(state.labSimFusionFullMap && state.labSimFusionFullMap[index] === true);
}

// 获取 lab_sim_{index}_fusion_full.json（trades/equity_curve），合并入 fusion stats 缓存
// 照抄 fetchLabSimFullData，独立缓存 labSimFusionFullMap，避免与单信号 full 互相覆盖
async function fetchLabFusionSimFullData(index, onProgress, signal) {
  index = index || "sh";
  if (!state.labSimFusionFullMap) state.labSimFusionFullMap = {};
  if (state.labSimFusionFullMap[index] === true) return state.labSimFusionDataMap[index];
  if (state.labSimFusionFullMap[index] === "loading") {
    for (let i = 0; i < 600; i++) {
      await new Promise((r) => setTimeout(r, 100));
      if (state.labSimFusionFullMap[index] === true) return state.labSimFusionDataMap[index];
      if (state.labSimFusionFullMap[index] === null) break;
      if (signal && signal.aborted) return state.labSimFusionDataMap[index];
    }
    return state.labSimFusionDataMap[index];
  }
  const stats = state.labSimFusionDataMap && state.labSimFusionDataMap[index];
  if (!stats) return null;
  state.labSimFusionFullMap[index] = "loading";
  try {
    const full = await fetchJSONProgress("https://ssd.fx8.store/lab/lab_sim_" + index + "_fusion_full.json", onProgress, signal);
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
            sp[mode].win_trades = fp[mode].win_trades;
            sp[mode].win_base_cp = fp[mode].win_base_cp;
            sp[mode].open_positions = fp[mode].open_positions;
          }
        }
      }
    }
    state.labSimFusionFullMap[index] = true;
  } catch (e) {
    state.labSimFusionFullMap[index] = null;
  }
  return state.labSimFusionDataMap[index];
}

// 获取 lab_retest_{index}.json 数据（二次测试：分年/样本外/极端行情，per-index 缓存）
async function fetchLabRetestData(index) {
  index = index || "sh";
  if (!state.labRetestDataMap) state.labRetestDataMap = {};
  if (state.labRetestDataMap[index]) return state.labRetestDataMap[index];
  try {
    state.labRetestDataMap[index] = await fetchJSON("https://ssd.fx8.store/lab/lab_retest_" + index + ".json");
  } catch (e) {
    state.labRetestDataMap[index] = null;
  }
  return state.labRetestDataMap[index];
}

// 荣誉共享标注表(全局单文件，9指数×5窗口 Top3 荣誉，由 scripts/lab/lab_retest_honors.py 预计算)
// 缓存到 state.labRetestHonors，retest 维度榜每行查本 pair 的"其他条件"Top3 排名徽章
async function fetchLabRetestHonors() {
  if (state.labRetestHonors !== undefined) return state.labRetestHonors;
  try {
    state.labRetestHonors = await fetchJSON("https://ssd.fx8.store/lab/lab_retest_honors.json");
  } catch (e) {
    state.labRetestHonors = null;
  }
  return state.labRetestHonors;
}

// 检查某指数 full 数据是否已合并入缓存（用于判断详情是否需显示 loading）
function _labSimFullLoaded(index) {
  index = index || "sh";
  return !!(state.labSimFullMap && state.labSimFullMap[index] === true);
}

// 带 HTTP 进度的 fetch JSON（读 ReadableStream 累计 received/Content-Length 算百分比）
// 无 Content-Length 或不支持流时降级为普通 fetchJSON，onProgress(-1) 表示无法测算
async function fetchJSONProgress(url, onProgress, signal) {
  // JSON gz 方案B/Y: 支持 url 带 query string, .gz 插在 .json 后 query 前
  // 方案Y: export.py GZ_THRESHOLD=0 全量生成 .gz,.gz 优先不再 404
  const _qIdx = url.indexOf("?");
  const _base = _qIdx >= 0 ? url.slice(0, _qIdx) : url;
  const _query = _qIdx >= 0 ? url.slice(_qIdx) : "";
  const tryGz = _base.startsWith("./data/") && _base.endsWith(".json");
  const gzUrl = tryGz ? _base + ".gz" + _query : null;
  try {
    const fetchUrl = gzUrl || url;
    const resp = await fetch(fetchUrl, signal ? { signal } : undefined);
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    const total = parseInt(resp.headers.get("Content-Length") || "0", 10);
    // .gz 路径: 先按压缩流累计进度,再 pipe DecompressionStream 解压
    if (gzUrl && resp.body && resp.body.getReader && typeof DecompressionStream !== "undefined") {
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
      // Blob.stream() -> pipeThrough(DecompressionStream) -> Response.text()
      const ds = new DecompressionStream("gzip");
      const decStream = blob.stream().pipeThrough(ds);
      const txt = await new Response(decStream).text();
      return JSON.parse(txt);
    }
    // 非 .gz 路径(原逻辑): 流式累计 + text parse
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
    // .gz 失败(404/解压错/不支持) -> fallback 原 .json 走 fetchJSON
    if (gzUrl) {
      if (onProgress) onProgress(-1, 0);
      return fetchJSON(url);
    }
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
    const full = await fetchJSONProgress("https://ssd.fx8.store/lab/lab_sim_" + index + "_full.json", onProgress, signal);
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
            sp[mode].win_trades = fp[mode].win_trades;
            sp[mode].win_base_cp = fp[mode].win_base_cp;
            sp[mode].open_positions = fp[mode].open_positions;
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
function _labSimModeBlock(mode, winData, initCapital, page, isOpen, signalBtnHTML, pairLabel, midHTML, idx, pairId) {
  const s = winData && winData.stats;
  const idxName = idx ? _labIdxName(idx) : "";  // 交易品种名（每行直接标注，不只靠区块/弹窗标题）
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
  // 口径分两路:
  //  fromWinSim=true(新 JSON win_trades): trades 来自窗口独立 sim,cp 已从 0 起、at 已是窗口相对
  //   (~100k-140k 量级,与卡片 final_total 对齐)。直接用 t.cp/t.at,分母恒为 initCapital(=100k,
  //   与卡片 total_ret=(final_total-INITIAL_CAPITAL)/INITIAL_CAPITAL 同口径)。
  //  fromWinSim=false(旧 JSON): 走 win_base_cp 调整,cpVal=t.cp-winBaseCp(窗口内从0起算),
  //   full_in 分母=initCapital+winBaseCp,fixed_10k 分母=initCapital。全历史窗口 winBaseCp=0 不变。
  const winBaseCp = winData.winBaseCp || 0;
  const fromWinSim = !!winData.fromWinSim;
  const crDenom = fromWinSim ? initCapital : (mode === "full_in" ? (initCapital + winBaseCp) : initCapital);

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
    const hasCp = t.cp != null;
    const cpVal = hasCp ? (fromWinSim ? t.cp : (t.cp - winBaseCp)) : 0;         // 窗口内累计盈亏(从0起算)
    const crVal = crDenom > 0 ? cpVal / crDenom * 100 : 0; // 窗口内累计收益率(与卡片同口径)
    const pc = crVal >= 0 ? "#c92a2a" : "#2e7d32";
    const at = t.at != null ? Math.round(t.at).toLocaleString() : "-";
    const cpStr = hasCp ? (cpVal >= 0 ? "+" : "") + Math.round(cpVal).toLocaleString() : "-";
    const crStr = hasCp ? (crVal >= 0 ? "+" : "") + crVal.toFixed(2) + "%" : "-";
    // "较上次"列：本笔累计收益率/累计盈亏 - 上一笔的差值（本笔赚还是亏）。首笔显示"-"
    let deltaHTML = '<span style="color:var(--text-4)">-</span>';
    if (prev && hasCp && prev.cp != null) {
      const prevCpVal = fromWinSim ? prev.cp : (prev.cp - winBaseCp);
      const prevCrVal = crDenom > 0 ? prevCpVal / crDenom * 100 : 0;
      const dr = crVal - prevCrVal;                         // 累计收益率差（百分点）
      const dp = cpVal - prevCpVal;                         // 累计盈亏差=本笔盈亏金额
      const dc = dp >= 0 ? "#c92a2a" : "#2e7d32";           // 国人配色 红赚绿亏
      deltaHTML = `<span style="color:${dc};font-weight:600">${dr >= 0 ? "+" : ""}${dr.toFixed(2)}%</span>` +
        `<br><span style="color:${dc};font-size:11px">${dp >= 0 ? "+" : ""}${Math.round(dp).toLocaleString()}</span>`;
    }
    return `<tr><td style="white-space:nowrap"><span style="color:var(--text-2);font-size:12px;font-weight:500">${idxName || "-"}</span></td><td>${gi + 1}</td><td>${t.bd}</td><td>${t.bp}</td><td>${t.sd}</td><td>${t.sp}</td><td style="color:${tc};font-weight:600">${t.ret > 0 ? "+" : ""}${t.ret}%</td><td>${t.hd}天</td><td>${at}</td><td style="color:${pc}">${cpStr}</td><td style="color:${pc};font-weight:600">${crStr}</td><td>${deltaHTML}</td></tr>`;
  }).join("");

  // A方案:未平仓持仓行 -- 读 open_positions,展示当前仍持有的仓位(浮盈亏按收盘价重估)
  // 字段对齐已成交行12列:品种/#/买入日/买入价/卖出日/卖出价/收益率/持有/账户资金/累计盈亏/累计收益率/较上次
  const openPositions = winData.openPositions || [];
  // 持仓中行账户资金/累计收益率/较上次: 以末次已成交 at 为 baseAt, 逐笔累加 unrealized_pnl。
  // 末笔账户资金 = baseAt + sum(unrealized_pnl) ≈ stats.final_total(顶部期末资金, 含未平仓重估),
  // 末笔累计收益率 ≈ total_ret(顶部总收益率), 与顶部卡片直观对齐。
  // 注意 baseAt 取全 trades 末笔(该窗口全量, 非分页切片 showTrades 末笔)。
  const lastTrade = trades.length ? trades[trades.length - 1] : null;
  const baseAt = (lastTrade && lastTrade.at != null) ? lastTrade.at : initCapital;
  let cumAt = baseAt;  // 逐笔累加账户资金, 初始=末次已成交 at; 每行 += 本笔 unrealized_pnl
  const holdingRows = openPositions.map((p) => {
    const isProfit = p.unrealized_pnl >= 0;
    const pc = isProfit ? "var(--mx-good-fg)" : "var(--mx-bad-fg)";
    const pnlPctStr = (isProfit ? "+" : "") + p.unrealized_pnl_pct + "%";
    // 账户资金 = 上一行账户资金 + 本笔浮盈(第1笔上一行=baseAt=末次已成交 at)
    cumAt = cumAt + p.unrealized_pnl;
    const atStr = Math.round(cumAt).toLocaleString();
    // 累计盈亏 = 账户资金 - initCapital, 与同行账户资金/累计收益率同口径(累计, 非个体浮盈亏)
    const cumPnl = cumAt - initCapital;
    const cumPC = cumPnl >= 0 ? "var(--mx-good-fg)" : "var(--mx-bad-fg)";
    const pnlStr = (cumPnl >= 0 ? "+" : "") + Math.round(cumPnl).toLocaleString();
    // 累计收益率 = (账户资金 - initCapital)/initCapital*100, 与顶部 total_ret 同口径(分母恒 initCapital)
    const crVal = initCapital > 0 ? (cumAt - initCapital) / initCapital * 100 : 0;
    const crPC = crVal >= 0 ? "#c92a2a" : "#2e7d32";
    const crStr = (crVal >= 0 ? "+" : "") + crVal.toFixed(2) + "%";
    // 较上次: 本笔账户资金 - 上一行账户资金 = 本笔 unrealized_pnl; 收益率差 = dp/initCapital*100
    const dp = p.unrealized_pnl;
    const dr = initCapital > 0 ? dp / initCapital * 100 : 0;
    const dc = dp >= 0 ? "#c92a2a" : "#2e7d32";
    const deltaHTML = `<span style="color:${dc};font-weight:600">${dr >= 0 ? "+" : ""}${dr.toFixed(2)}%</span>` +
      `<br><span style="color:${dc};font-size:11px">${dp >= 0 ? "+" : ""}${Math.round(dp).toLocaleString()}</span>`;
    return `<tr class="lab-sim-holding-row">` +
      `<td style="white-space:nowrap"><span style="color:var(--text-2);font-size:12px;font-weight:500">${idxName || "-"}</span></td>` +
      `<td><span class="lab-sim-holding-tag">持仓中</span></td>` +
      `<td>${p.buy_date}</td><td>${p.buy_price}</td>` +
      `<td style="color:var(--text-4)">持仓中</td><td>${p.last_close}</td>` +
      `<td style="color:${pc};font-weight:600">${pnlPctStr}</td>` +
      `<td>${p.hold_days}天</td>` +
      `<td>${atStr}</td>` +
      `<td style="color:${cumPC}">${pnlStr}</td>` +
      `<td style="color:${crPC};font-weight:600">${crStr}</td>` +
      `<td>${deltaHTML}</td>` +
      `</tr>`;
  }).join("");
  const holdingNote = openPositions.length ? ` · ${openPositions.length}笔持仓中` : "";

  const pagerHTML = totalPages > 1
    ? `<div class="lab-sim-pager">` +
      `<button class="lab-sim-prev" data-mode="${mode}"${currentPage === 0 ? " disabled" : ""}>上一页</button>` +
      `<span class="lab-sim-page-info">第 ${currentPage + 1}/${totalPages} 页（共 ${totalReal} 笔${truncNote}${holdingNote}）</span>` +
      `<button class="lab-sim-next" data-mode="${mode}"${currentPage >= totalPages - 1 ? " disabled" : ""}>下一页</button>` +
      `</div>`
    : trades.length > 0
      ? `<div class="lab-sim-pager"><span class="lab-sim-page-info">共 ${totalReal} 笔交易${truncNote}${holdingNote}</span></div>`
      : "";

  const tradesBody = isOpen
    ? `<div class="lab-sim-trades-body">` +
      `<div class="lab-sim-table-wrap"><table><thead><tr><th>品种</th><th>#</th><th>买入日期</th><th>买入价</th><th>卖出日期</th><th>卖出价</th><th>收益率</th><th>持有</th><th>账户总资金</th><th>累计盈亏</th><th>累计收益率</th><th data-tip="本笔累计收益率/累计盈亏相较上一笔的差值，红赚绿亏">较上次</th></tr></thead><tbody>` +
      (tradeRows || '<tr><td colspan="12" style="text-align:center;color:var(--text-4)">无交易记录</td></tr>') +
      holdingRows +
      `</tbody></table></div>${pagerHTML}</div>`
    : "";

  // full 数据未加载时，stats 数字可见（来自小 stats 文件），净值曲线/交易记录显示加载占位
  const detailHTML = winData.hasFull
    ? `<div class="lab-sim-equity"><div class="lab-sim-equity-label">📈 净值曲线（虚线=初始本金）</div>${svgHTML}</div>` +
      (midHTML || "") +
      `<div class="lab-sim-trades">` +
      `<div class="lab-sim-trades-header" data-mode="${mode}">` +
      `<span class="lab-sim-trades-label">📋 交易记录${idx ? " · " + _labIdxName(idx) : ""} 共 ${totalReal} 笔${truncNote}${holdingNote}</span>` +
      `<span class="lab-sim-trades-toggle">${isOpen ? "收起 ▲" : "展开 ▼"}</span>` +
      `</div>` +
      tradesBody +
      `</div>`
    : `<div class="lab-sim-full-loading">⏳ 加载明细数据（净值曲线/交易记录）中…</div>`;

  // 成本对比数据查找：口径与模拟回测同源(同 index/pair/mode/window 的 gross 值已校验一致)
  // 覆盖范围=top10配对×2窗口(all/y5)，非覆盖时回退通用毛收益提示
  const _ccWin = state.labSimWindow || "y5";
  const _ccIdx = idx || state.labSimIdx || "sh";
  const costData = pairId ? _labLookupCost(state._labCostCompare, _ccIdx, pairId, mode, _ccWin) : null;
  // 毛收益角标 + 复利放大角标(full_in 模式)
  const grossTag = '<span class="lab-gross-tag">毛</span>';
  const compoundTag = mode === "full_in" ? '<span class="lab-compound-tag">复利放大</span>' : "";
  // 成本披露块
  let costBlock = "";
  if (costData && costData.detail) {
    const g = costData.detail.gross || {};
    const lo = costData.detail.low || {};
    const hi = costData.detail.high || {};
    const fmtPct = (v) => (v == null ? "-" : (v > 0 ? "+" : "") + v + "%");
    const loDecay = costData.low_decay_ratio != null ? Math.abs(costData.low_decay_ratio).toFixed(0) : null;
    const hiDecay = costData.high_decay_ratio != null ? Math.abs(costData.high_decay_ratio).toFixed(0) : null;
    costBlock = `<div class="lab-cost-block">` +
      `<div class="lab-cost-warn">⚠ 以上为<strong>毛收益</strong>,未计手续费/滑点。计入成本后年化约降 ${loDecay || "?"}~${hiDecay || "?"}%</div>` +
      `<table class="lab-cost-table"><thead><tr><th>成本档</th><th>手续费</th><th>滑点</th><th>年化</th><th>总收益</th><th>胜率</th></tr></thead><tbody>` +
      `<tr><td>毛收益</td><td>-</td><td>-</td><td>${fmtPct(g.annual_ret)}</td><td>${fmtPct(g.total_ret)}</td><td>${g.win_rate != null ? g.win_rate + "%" : "-"}</td></tr>` +
      `<tr><td>低档</td><td>万3</td><td>千1</td><td>${fmtPct(lo.annual_ret)}</td><td>${fmtPct(lo.total_ret)}</td><td>${lo.win_rate != null ? lo.win_rate + "%" : "-"}</td></tr>` +
      `<tr><td>高档</td><td>万5</td><td>千2</td><td>${fmtPct(hi.annual_ret)}</td><td>${fmtPct(hi.total_ret)}</td><td>${hi.win_rate != null ? hi.win_rate + "%" : "-"}</td></tr>` +
      `</tbody></table>` +
      `<div class="lab-cost-note">成本档说明：低档=万3手续费+千1滑点(ETF/低费率)；高档=万5手续费+千2滑点(个股常规)。高频策略成本侵蚀更大。</div>` +
      `</div>`;
  } else {
    costBlock = `<div class="lab-cost-block lab-cost-block-generic"><div class="lab-cost-warn">⚠ 以上为<strong>毛收益</strong>,未计手续费/滑点,实际收益约低 5%~30%(高频交易成本侵蚀更大)</div></div>`;
  }

  return `<div class="lab-sim-mode-block" data-mode="${mode}">` +
    (pairLabel ? `<div class="lab-sim-cur-pair">当前配对：${pairLabel}</div>` : "") +
    `<div class="lab-sim-stats">` +
    `<div class="lab-sim-stat"><span class="k">总收益率</span><span class="v" style="color:${retColor}">${s.total_ret > 0 ? "+" : ""}${s.total_ret}%${grossTag}</span><span class="sub">期末 ${Math.round(s.final_total).toLocaleString()} 元${openPositions.length ? '<br><span style="color:var(--text-3);font-size:11px">含未平仓持仓按收盘价重估</span>' : ""}</span></div>` +
    `<div class="lab-sim-stat"><span class="k">历史回测年化</span><span class="v" style="color:${retColor}">${s.annual_ret > 0 ? "+" : ""}${s.annual_ret}%${grossTag}${compoundTag}</span><span class="sub">${s.years} 年${mode === "full_in" ? '<br><span style="color:var(--text-3);font-size:11px">复利放大,非固定仓位收益</span>' : ""}</span></div>` +
    `<div class="lab-sim-stat"><span class="k">最大回撤${_labHelpIcon("max_drawdown")}</span><span class="v" style="${_labDdColor(s.max_drawdown)}">${s.max_drawdown}%</span><span class="sub">峰值最大跌幅</span></div>` +
    `<div class="lab-sim-stat"><span class="k">胜率${_labHelpIcon("win_rate")}</span><span class="v" style="color:${winColor}">${s.win_rate}%</span><span class="sub">${winTrades}胜/${loseTrades}负 · ${s.n_trades}笔</span></div>` +
    `</div>` +
    costBlock +
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
  const idx = (simData && simData.index_id) || state.labSimIdx || "sh";

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
  const pairId = buyKey + "|" + sellKey;  // 成本对比数据查找键
  const detailBlock = _labSimModeBlock(mode, winData, initCapital, page, isOpen, signalBtnHTML, pairLabel, null, idx, pairId);

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
        const winPct = (cell.win != null ? (cell.win * 100).toFixed(1) + "%" : "-");
        const pl = (cell.pl != null ? cell.pl.toFixed(2) : "-");
        const n = (cell.n != null ? cell.n : "-");
        const meanStr = (cell.mean != null ? (cell.mean > 0 ? "+" : "") + (cell.mean * 100).toFixed(1) + "%" : "-");
        const yuan100 = (cell.mean != null ? (100 * (1 + cell.mean)).toFixed(1) : "-");
        // 三色分级：综合 win/pl/mean
        const winLv = cell.win != null ? (cell.win > 0.55 ? "good" : cell.win >= 0.45 ? "warn" : "bad") : null;
        const plLv = cell.pl != null ? (cell.pl > 1.3 ? "good" : cell.pl >= 1.0 ? "warn" : "bad") : null;
        const meanLv = cell.mean != null ? (cell.mean > 0 ? "good" : "bad") : null;
        const lvls = [winLv, plLv, meanLv].filter(x => x !== null);
        const goods = lvls.filter(x => x === "good").length;
        const bads = lvls.filter(x => x === "bad").length;
        const lvl = lvls.length === 0 ? "warn" : (goods >= 2 ? "good" : bads >= 2 ? "bad" : "warn");
        // 达标边框（保留原逻辑）
        const pass = (cell.win != null && cell.pl != null) ? (cell.win > 0.5 && cell.pl > 1) : false;
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
    `<p>有好的策略建议或测试想法，欢迎抖音私信交流（抖音号：<strong>kant2218</strong>）。</p>` +
    `<p class="lab-backtest-disclaimer">⚠ <strong>回测非投资建议；过往表现不代表未来收益。</strong>以下为历史回测统计，含幸存者偏差与过拟合风险，实盘收益通常低于回测。回测基于历史数据理想化模拟，未考虑实盘滑点、流动性冲击与极端行情。所有收益/胜率/年化均为历史回测结果，非投资建议或收益承诺。</p>`;
}

// C: 实验室顶部合规声明（置顶显著，非折叠，教育研究定位）
function _labTopDisclaimerHTML() {
  return `<div class="lab-top-disclaimer">` +
    `<span class="lab-top-title">📚 教育研究工具声明</span>` +
    `本实验室为个人学习/研究用途，<b>非持牌证券投资咨询机构</b>。⚠ 以下为历史回测统计，含<b>幸存者偏差与过拟合风险</b>，实盘收益通常低于回测。所有策略与信号均为历史数据回测统计与技术分析参考，<b>不构成任何投资建议或交易指令</b>。所有收益/胜率/年化均为历史回测结果，<b>不代表未来收益，非投资建议或收益承诺</b>。投资有风险，决策需谨慎。` +
    `</div>`;
}

// P2-3: 新手引导卡（置顶常驻，可折叠，<details> 原生折叠免 JS）
// 三步导览：①推荐榜(综合评分)起点 ②点开看净值曲线 ③二次测试三切片验稳健
function _labNewbieGuideHTML() {
  return `<details class="lab-newbie-guide" open>` +
    `<summary class="lab-newbie-guide-summary">🧭 新手引导 · 不熟悉回测？先看这三步 <span class="lab-newbie-toggle"></span></summary>` +
    `<div class="lab-newbie-guide-body">` +
    `<div class="lab-newbie-step">` +
    `<span class="lab-newbie-step-no">1</span>` +
    `<div><b>先看「推荐榜（综合评分）」</b>：综合评分 = 收益率(35%)+胜率(25%)+回撤倒数(15%)+风险调整(15%)+样本量(10%)，评分越高综合表现越好，从高到低看起。` +
    `</div></div>` +
    `<div class="lab-newbie-step">` +
    `<span class="lab-newbie-step-no">2</span>` +
    `<div><b>点开看回测净值曲线</b>：点击任意配对查看完整净值曲线与逐笔交易记录，确认收益曲线是否平滑向上、回撤是否可承受。` +
    `</div></div>` +
    `<div class="lab-newbie-step">` +
    `<span class="lab-newbie-step-no">3</span>` +
    `<div><b>看「二次测试」三切片是否稳健</b>：标⭐️的配对可进入二次测试，看①分年回测（防某年暴利拉高）②样本外（防过拟合）③极端行情（2015股灾/2018熊/2020疫情/2024反弹各regime回撤），三者都稳才是真稳健，非偶然。` +
    `</div></div>` +
    `<div class="lab-newbie-tip">💡 融合实验中 <b>n&lt;30</b> 的候选已标灰「样本不足，仅供参考」——样本量小统计意义弱，收益/胜率易被极端值拉偏，谨慎参考。</div>` +
    `</div></details>`;
}

// 融合信号实验自白黄块
function _labFusionEssayHTML() {
  return `<div class="lab-warning-head">⚠ 融合信号实验 · 多信号共振</div>` +
    `<p>融合信号=多个单一信号同日同时满足才触发，通过多条件共振过滤假信号、提升信号质量。${_labHelpIcon("fusion_signal")}注意：融合是异向多条件同时满足成新策略，与同向共振（同向两信号叠加增强）${_labHelpIcon("co_resonance")}不同。本页展示从主项目提取的融合策略及实验性新组合。</p>` +
    `<p>阶段一仅展示条件描述与说明，阶段二将开放回测数据/图表/配对排行。欢迎抖音私信交流（抖音号：<strong>kant2218</strong>）。</p>`;
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
  header.innerHTML = `<h2 class="lab-detail-title">${_labStratNameHTML(key, meta.name)}</h2>` +
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
      indItems.map((it) => `<div><b title="${it.en || ''}">${it.name}</b>：${it.plain}</div>`).join("") +
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
    winBar.innerHTML = '<span class="lab-win-bar-label">时间窗口' + _labHelpIcon("windows") + '</span>' +
      '<div class="lab-win-tabs">' + LAB_WIN_DEFS.map((w) =>
        `<button type="button" class="lab-win-tab${w.k === state.labChartWin ? " active" : ""}" data-cwin="${w.k}">${w.l}</button>`
      ).join("") + "</div>" +
      `<button type="button" class="lab-win-sync-btn" data-tip="开启后实验图表窗口跟随模拟回测窗口联动" style="margin-left:6px;padding:2px 8px;border:1px solid var(--border);border-radius:5px;background:${state.labWinSync ? "var(--bg-hover)" : "var(--bg-card)"};color:${state.labWinSync ? "var(--text-1)" : "var(--text-3)"};font-size:12px;cursor:pointer;white-space:nowrap;${state.labWinSync ? "font-weight:600;" : ""}">🔗 同步${state.labWinSync ? "✓" : ""}</button>`;
    chartSection.appendChild(winBar);

    // 指数选择器（实验策略共用，按钮组对齐时间窗口样式，与融合弹窗一致）
    const idxGroups = [
      ["A股宽基", ["sh", "sz", "cyb", "csi500", "csi1000", "kc50", "hs300", "sz50"]],
      ["港股", ["hsi", "hscei", "hstech"]],
      ["美股", ["us_dji", "us_ixic", "us_spx", "us_ndx"]],
      ["红利/低波", ["div_lowvol", "csi_div", "sz_div"]],
    ];
    const idxBtnsHTML = idxGroups.map(([gname, ids]) =>
      ids.map((id) => `<button type="button" class="lab-idx-tab${id === state.labIndex ? " active" : ""}" data-lidx="${id}">${_INDEX_NAME_MAP[id] || id}</button>`).join("")
    ).join("");
    const filterBar = document.createElement("div");
    filterBar.className = "lab-win-bar";
    filterBar.innerHTML = `<span class="lab-win-bar-label">选择指数</span><div class="lab-win-tabs">${idxBtnsHTML}</div>`;
    filterBar.querySelectorAll(".lab-idx-tab").forEach((btn) => {
      btn.onclick = () => { state.labIndex = btn.dataset.lidx; renderLabDetail(key, container); };
    });
    chartSection.appendChild(filterBar);

    const chartDiv = document.createElement("div");
    chartDiv.innerHTML = '<div class="loading">加载中…</div>';
    chartSection.appendChild(chartDiv);

    try {
      const r = await fetchJSON(`https://ssd.fx8.store/index/${state.labIndex}-all.json`);
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
    if (srcEl) srcEl.textContent = '数据来源：买卖点策略深度回测（' + _matrixIdxName(mIdx) + '，基于历史数据验证' + (mGenAt ? '，重跑于 ' + mGenAt : '') + '）';
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
    // 并行加载模拟回测数据 + 成本对比数据(成本数据加载失败不阻塞渲染)
    const [simData] = await Promise.all([fetchLabSimData(simIdxId), fetchLabCostCompare()]);
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

// === 回测配对对比榜（列表页底部，128组配对多维度排序 + 点击弹窗细节）===
// 数据源：lab_sim_{index}_stats.json（_full 按需合并）。新结构 pairs 按 "buyKey|sellKey" 去重存储（只存一份），
// 直接遍历 simData.pairs 即得 8买×8卖×2模式=128 组去重配对。窗口切换共用 state.labSimWindow。
const LAB_RANK_TABS = [
  { key: "composite", label: "🏆 综合评分" },
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

// 过滤：且组合，min/max 闭区间(>=min 且 <=max)。作用于当前窗口统计值（rows 已按 state.labSimWindow 聚合）。
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

// winsorize 截断前后1%极端值(P1-2 抗离群点:实测有-88%收益/dd91%拉偏min-max)。
// 返回与 vals 等长的 clamped 数组；<4个样本时 quantile 不稳，原样返回副本。
// 与后端 lab_retest._winsorize 一致(线性插值分位数)。
function _labWinsor(vals, lo, hi) {
  lo = lo == null ? 0.01 : lo; hi = hi == null ? 0.99 : hi;
  const n = vals.length;
  if (n < 4) return vals.slice();
  const vs = vals.slice().sort((a, b) => a - b);
  const qi = (p) => { const i = p * (n - 1), f = Math.floor(i), c = Math.ceil(i); return f === c ? vs[f] : vs[f] + (vs[c] - vs[f]) * (i - f); };
  const loV = qi(lo), hiV = qi(hi);
  return vals.map((v) => Math.min(Math.max(v, loV), hiV));
}

// 格式化质量指标值(P0-1/P2-2 展示用):
// kind="sentinel": profit_factor/payoff_ratio 无亏损笔时 999 哨兵显示 ∞;
// kind="pct": expectancy 加 % 并带正负号; 默认: toFixed(2)。
function _labFmtQuality(v, kind) {
  if (v == null || isNaN(v)) return "-";
  if (kind === "sentinel" && v >= 998) return "∞";
  if (kind === "pct") return (v >= 0 ? "+" : "") + v.toFixed(2) + "%";
  return v.toFixed(2);
}
// 质量指标5字段 HTML(盈亏比/利润因子/夏普/索提诺/期望值),复用于主榜与retest榜行。
// 紧凑灰字单行,hover title 给中文释义,详细解释见术语词典(_labHelpIcon)。
function _labQualityHTML(row) {
  return `<span class="lab-rank-quality" title="质量指标(点页内❓查词典): 盈亏比=平均盈利/平均亏损; 利润因子=总盈利/总亏损; 夏普/索提诺=年化风险调整收益(索提诺仅算下行波动); 期望值=单笔期望收益率%">` +
    `盈亏比${_labFmtQuality(row.payoff_ratio, "sentinel")} · 利润因子${_labFmtQuality(row.profit_factor, "sentinel")} · 夏普${_labFmtQuality(row.sharpe)} · 索提诺${_labFmtQuality(row.sortino)} · 期望${_labFmtQuality(row.expectancy, "pct")}</span>`;
}

// 聚合配对 + 算综合评分与风险调整（三榜隔离：single 只显买×卖；fusion 只显 F_融合+同向共振）
// 新结构：simData.pairs 按 "buyKey|sellKey" 去重存储（配对只存一份），直接遍历即得配对组
// opt.subMode: "single"=单一实验榜(只 buy_sell) / "fusion"=融合实验榜(F_融合+buy_buy/sell_sell共振，砍 plain buy_sell)
function _labRankAggregate(simData, win, opt) {
  opt = opt || {};
  if (!simData || !simData.pairs) return [];
  const subMode = opt.subMode || "single";
  // ⭐️二次测试候选集：后端 lab_retest_{index}.json 已按三窗口dd≤10%+n≥10+OR判定通过，前端查 pair 存在性，与后端一致（不按选中窗口动态算）
  const _reIdx = (simData.index_id) || (state.labSimIndex || "sh");
  const _reRd = state.labRetestDataMap && state.labRetestDataMap[_reIdx];
  const retestSet = _reRd && _reRd.pairs ? new Set(Object.keys(_reRd.pairs).filter((pk) => !_reRd.pairs[pk].substitute)) : null;
  const rows = [];
  for (const pairKey in simData.pairs) {
    const parts = pairKey.split("|");
    const bk = parts[0], sk = parts[1]; // sk=undefined 表示 F_ 独立融合策略(无|)
    // 配对类型判定：is_fusion(任一方 F_) / buy_buy / sell_sell / buy_sell(按 LAB_STRATEGIES zone)
    const isFusion = bk.indexOf("F_") === 0 || (sk && sk.indexOf("F_") === 0);
    const bz = (LAB_STRATEGIES[bk] || {}).zone;
    const sz = sk ? (LAB_STRATEGIES[sk] || {}).zone : null;
    let pair_type;
    if (isFusion) pair_type = "fusion";
    else if (bz === "buy" && sz === "buy") pair_type = "buy_buy";
    else if (bz === "sell" && sz === "sell") pair_type = "sell_sell";
    else pair_type = "buy_sell";
    // 三榜隔离：fusion 榜只显 融合(F_)+同向共振(buy_buy/sell_sell)，单一榜只显 buy_sell
    if (subMode === "fusion") {
      if (pair_type === "buy_sell") continue; // 砍掉纯单一买×卖(归单一实验)
    } else {
      if (pair_type !== "buy_sell") continue; // 砍掉融合/共振(归融合实验)
    }
    const pairData = simData.pairs[pairKey];
    // 名称：F_ 融合策略用 LAB_FUSION_STRATEGIES 名，单一策略用 LAB_STRATEGIES 名
    const buyName = (isFusion && bk.indexOf("F_") === 0)
      ? ((LAB_FUSION_STRATEGIES[bk] || {}).name || bk)
      : ((LAB_STRATEGIES[bk] || {}).name || bk);
    const sellName = !sk ? "" // F_ 独立融合策略无卖方
      : ((isFusion && sk.indexOf("F_") === 0)
        ? ((LAB_FUSION_STRATEGIES[sk] || {}).name || sk)
        : ((LAB_STRATEGIES[sk] || {}).name || sk));
    for (const mode of ["full_in", "fixed_10k"]) {
      const wd = _labPairWinData(pairData, mode, win, simData);
      if (!wd || !wd.stats) continue;
      const s = wd.stats;
      rows.push({
        buyKey: bk, sellKey: sk || "", mode,
        buyName, sellName,
        pair_type, is_fusion: pair_type === "fusion", is_standalone: !sk,
        modeName: mode === "full_in" ? "全仓" : "定额（10%）",
        total_ret: s.total_ret, annual_ret: s.annual_ret,
        max_drawdown: s.max_drawdown, win_rate: s.win_rate,
        n_trades: s.n_trades, years: s.years, final_total: s.final_total,
        // 5质量指标(P0-1展示,阶段1已上线)
        profit_factor: s.profit_factor, payoff_ratio: s.payoff_ratio,
        sharpe: s.sharpe, sortino: s.sortino, expectancy: s.expectancy,
      });
    }
  }
  // 风险调整：年化/最大回撤（类 Calmar），分母 floor 2.0% 消除 999 哨兵（与后端 _calc_risk_adj 一致）。
  rows.forEach((r) => {
    r.risk_adj = r.annual_ret / Math.max(r.max_drawdown, 2.0);
  });
  // 综合评分（P1-1/P1-2/P2-1，与后端 _normalize_and_score 一致）：
  //   0.35*ret + 0.25*win + 0.15*dd + 0.15*risk_adj + 0.1*(1-exp(-n/30))；ret/win/dd/risk_adj 先 winsorize(前后1%截断)抗极端值再 min-max 归一化；n 用凹函数 1-exp(-n/30) 替代线性(边际递减)。
  const mm = (acc) => {
    const wv = _labWinsor(rows.map(acc));
    const mn = Math.min.apply(null, wv), mx = Math.max.apply(null, wv);
    return (v) => { const x = mx === mn ? 0.5 : (v - mn) / (mx - mn); return Math.max(0, Math.min(1, x)); };
  };
  const nRet = mm((r) => r.total_ret);
  const nWin = mm((r) => r.win_rate);
  const nDd = mm((r) => -r.max_drawdown);
  const nRisk = mm((r) => r.risk_adj);
  rows.forEach((r) => {
    r.score = 0.35 * nRet(r.total_ret) + 0.25 * nWin(r.win_rate) +
              0.15 * nDd(-r.max_drawdown) + 0.15 * nRisk(r.risk_adj) +
              0.1 * (1 - Math.exp(-r.n_trades / 30));
    // ⭐️进入二次测试：查 retest JSON 存在性(后端已按 AND质量门 判定)，与后端一致，不按选中窗口动态算
    r.retest = retestSet ? retestSet.has(r.buyKey + "|" + r.sellKey) : false;
  });
  return rows;
}

// 主榜样本量分档：n≥10 大样本(优先) / 1≤n<10 小样本(居中) / n=0 无交易(沉底)。
// 小样本交易次数少、统计意义弱，收益/胜率/回撤易被极端值拉偏，故不与大样本同档竞争，单独居中。
function _rankTier(n){ return n >= 10 ? 0 : n > 0 ? 1 : 2; }

function _labRankSort(rows, tab) {
  const arr = rows.slice();
  // 三档前置：大样本优先 > 小样本居中 > 无交易沉底(避免回撤0被当最小排第一)。
  // 各档内按原维度排序；composite/risk_adj 同样走三档前置(小样本通胀同样影响这两维)。
  arr.sort((a, b) => {
    const t = _rankTier(a.n_trades) - _rankTier(b.n_trades);
    if (t !== 0) return t; // 大样本优先，小样本居中，无交易沉底
    if (tab === "ret") return b.total_ret - a.total_ret;
    if (tab === "win") return b.win_rate - a.win_rate;
    if (tab === "stable") return a.max_drawdown - b.max_drawdown; // 回撤小优先
    if (tab === "risk_adj") return b.risk_adj - a.risk_adj;
    return b.score - a.score; // composite
  });
  return arr;
}

function _labRankItemHTML(row, rank, tab) {
  const retC = row.total_ret >= 0 ? "#c92a2a" : "#2e7d32";
  const winC = row.win_rate >= 50 ? "#c92a2a" : "#2e7d32";
  const ddC = _labDdColor(row.max_drawdown);
  const medal = rank === 1 ? "🥇" : rank === 2 ? "🥈" : rank === 3 ? "🥉" : "";
  let extra = "";
  if (tab === "composite") extra = `<span class="lab-rank-score">评分 ${(row.score * 100).toFixed(0)}</span>`;
  else if (tab === "risk_adj") extra = `<span class="lab-rank-score">${row.risk_adj >= 100 ? "∞" : row.risk_adj.toFixed(2)}</span>`;
  if (row.retest) extra += '<span class="lab-rank-retest" title="点击跳转到「🔬 二次测试实验」页，对该配对做独立回测验证（分年回测/样本外/极端行情三件套）并高亮定位。进入规则:近5/3/1年三窗口最大回撤均≤10% 且 交易≥10次,且(综合评分≥0.6 且 胜率≥55% 且 风险调整≥1.5 三者同时满足)">⭐️进入二次测试</span>';
  // 配对类型 -> 名称格式 + 视觉标识（紫色 #9c27b0）
  const pt = row.pair_type || "buy_sell";
  let nameHTML, tagHTML, itemCls = "lab-rank-item clickable-card";
  if (pt === "fusion") {
    itemCls += " lab-rank-fusion";
    tagHTML = '<span class="lab-rank-tag lab-rank-tag-fusion">🔀融合</span>' + _labHelpIcon("fusion_signal");
    nameHTML = row.is_standalone ? `${row.buyName}（独立回测）` : `买${row.buyName} × 卖${row.sellName}`;
  } else if (pt === "buy_buy") {
    itemCls += " lab-rank-fusion";
    tagHTML = '<span class="lab-rank-tag lab-rank-tag-fusion">🔀双买共振</span>' + _labHelpIcon("co_resonance");
    nameHTML = `双买共振 ${row.buyName} × ${row.sellName}`;
  } else if (pt === "sell_sell") {
    itemCls += " lab-rank-fusion";
    tagHTML = '<span class="lab-rank-tag lab-rank-tag-fusion">🔀双卖共振</span>' + _labHelpIcon("co_resonance");
    nameHTML = `双卖共振 ${row.buyName} × ${row.sellName}`;
  } else {
    tagHTML = "";
    nameHTML = `买${row.buyName} × 卖${row.sellName}`;
  }
  // P2-3: 融合候选(91对:fusion/buy_buy/sell_sell)样本量门槛 n<30 标灰「样本不足,仅供参考」
  // 融合组合多、单配对交易次数偏少，n<30 统计意义弱（收益/胜率/回撤易被极端值拉偏），灰态+标注提示可信度存疑。
  // 单一配对(buy_sell)沿用原 n<10「小样本」门槛不变。
  const isFusionType = pt !== "buy_sell";
  const fusionLowN = isFusionType && row.n_trades > 0 && row.n_trades < 30;
  if (fusionLowN) itemCls += " lab-rank-low-n";
  const nBadge = fusionLowN
    ? ' <span class="lab-rank-small lab-rank-low-n-tag">样本不足,仅供参考</span>'
    : (row.n_trades > 0 && row.n_trades < 10 ? ' <span class="lab-rank-small">小样本</span>' : "");
  return `<button type="button" class="${itemCls}" data-buy="${row.buyKey}" data-sell="${row.sellKey}" data-mode="${row.mode}">` +
    `<span class="lab-rank-no">${medal || "#" + rank}</span>` +
    `<span class="lab-rank-name">${nameHTML} · ${row.modeName}</span>${tagHTML}` +
    `<span class="lab-rank-stats">` +
      `<span style="color:${retC}">收益${row.total_ret > 0 ? "+" : ""}${row.total_ret}%</span>` +
      `<span style="color:${winC}">胜${row.win_rate}%</span>` +
      `<span style="${ddC}">回撤${row.max_drawdown}%</span>` +
      `<span class="lab-rank-n">n=${row.n_trades}${nBadge}</span>` +
    `</span>` + _labQualityHTML(row) + extra + `</button>`;
}

function _labRankHTML(simData) {
  if (!simData) return '<div class="lab-rank-empty">配对排行数据加载失败，请稍后重试</div>';
  const win = state.labSimWindow || "y5";
  // 三榜隔离：single 只显买×卖；fusion 只显 F_融合+同向共振(buy_buy/sell_sell)
  const rows = _labRankAggregate(simData, win, { subMode: state.labSubMode });
  if (rows.length === 0) return '<div class="lab-rank-empty">暂无配对排行数据</div>';
  state.labRankRows = rows;
  const tab = state.labRankTab || "composite";
  const tabsHTML = LAB_RANK_TABS.map((t) =>
    `<button type="button" class="lab-rank-tab${t.key === tab ? " active" : ""}" data-tab="${t.key}">${t.label}</button>`
  ).join("");
  const legend = tab === "composite"
    ? "综合评分 = 收益率(35%)+胜率(25%)+回撤倒数(15%)+风险调整(15%)+样本量(10%)，收益/胜率/回撤/风险调整先winsorize(前后1%截断)抗极端值再min-max归一化，样本量用凹函数1-exp(-n/30)抗大样本通胀，加权×100越高越好。" + _labHelpIcon("score")
    : tab === "risk_adj"
      ? "风险调整 = 年化收益 ÷ 最大回撤（类 Calmar 比率），衡量每承担1%回撤换来多少年化收益，越高越好。" + _labHelpIcon("risk_adjust")
      : tab === "stable"
        ? "稳健榜按最大回撤从小到大排序，回撤越小越稳。"
        : tab === "ret"
          ? "收益率榜按总收益率从高到低排序。"
          : "胜率榜按胜率从高到低排序。";
  const _isFusionRank = state.labSubMode === "fusion";
  const sampleNote = _isFusionRank
    ? "融合候选样本量门槛更高：n<30 标灰「样本不足,仅供参考」（融合组合多、单配对交易少，统计意义弱），n=0(无交易)沉底。"
    : "排序：n≥10 大样本优先，0<n<10 小样本配对居中并标\"小样本\"提示可信度存疑，n=0(无交易)沉底。";
  return `<div class="lab-win-bar"><span class="lab-win-bar-label">时间窗口${_labHelpIcon("windows")}</span>${_labWinTabsHTML()}</div>` +
    `<div class="lab-rank-tabs">${tabsHTML}</div>` +
    `<div class="lab-rank-legend">${legend} 点击任意配对查看完整净值曲线与交易记录。红=好，绿=差。${sampleNote}</div>` +
    `<div class="lab-rank-retest-rule">⭐️进入二次测试：近5/3/1年三窗口最大回撤均≤10% 且 交易≥10次，且（综合评分≥0.6 且 胜率≥55% 且 风险调整≥1.5 三者同时满足）</div>` +
    _labRankFilterHTML() +
    `<div class="lab-rank-results">${_labRankResultsHTML()}</div>`;
}

// === 二次测试 tab 渲染（分年回测 / 样本外 / 极端行情三件套）===
// 数据源 lab_retest_{index}.json，per-index 缓存到 state.labRetestDataMap
// ret/dd/win 为小数(0.xxxx)，显示时 ×100 加 %；null 显示 "-"
const _LAB_RETEST_RULE = "🔬 二次测试(稳健性验证三件套):①分年回测-防某年暴利拉高整体 ②样本外-前70%训练后30%验证防过拟合 ③极端行情-2015股灾/2018熊/2020疫情/2024反弹各regime回撤。优先做这3种因其为验证核心(通过/筛掉),成本低结论明确;其余7方向(蒙特卡洛/参数敏感/消融/手续费/多空/标的泛化)属优化/归因靠后。⭐️候选=近5/3/1年三窗口回撤均≤10%且交易≥10,且(综合分≥0.6 且 胜率≥55% 且 风险调整≥1.5 三者同时满足)" + _labHelpIcon("retest");

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
  const starN = pks.filter((pk) => !rd.pairs[pk].substitute).length;
  const subN = pks.length - starN;
  const exhNote = rd.substitute_pool_exhausted
    ? ' · <span class="lab-retest-exhausted">达标候选不足10，已展示全部可用</span>'
    : "";
  const pairsHTML = pks.map((pk) => _labRetestPairHTML(pk, rd.pairs[pk])).join("");
  return `<div class="lab-retest-rule">${_LAB_RETEST_RULE}</div>` +
    `<div class="lab-retest-meta">指数: ${rd.index_name || idx} · 生成: ${rd.generated_at || "-"} · ⭐️候选: ${starN} · 🔵替补: ${subN}${exhNote}</div>` +
    `<div class="lab-retest-pairs">${pairsHTML}</div>`;
}

// 单个候选配对的二次测试卡片：pair_meta + 分年 + 样本外 + 极端行情
// 二次测试三切片 HTML（分年 + 样本外 + 极端行情），可独立用作弹窗 midHTML 注入净值曲线与交易记录之间
function _labRetestPairSlicesHTML(pd) {
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
    '<div class="lab-retest-section-title">② 样本外测试（前70%训练 -> 后30%验证，防过拟合）</div>' +
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

  return yearlyHTML + oosHTML + regimesHTML;
}

function _labRetestPairHTML(pk, pd) {
  const meta = pd.pair_meta || {};
  // 替补候选：未达⭐️质量门(综合分≥0.6 且 胜率≥55% 且 风险调整≥1.5)，标🔵并展示未达标原因
  const isSub = !!pd.substitute;
  const subReason = pd.reason || "未达标";
  const badge = isSub ? "🔵" : "⭐️";
  const subTag = isSub ? ` <span class="lab-retest-sub-reason" title="${subReason}">替补·${subReason}</span>` : "";
  // 信息头
  const headHTML = '<div class="lab-retest-pair-head">' +
    `<span class="lab-retest-pair-strat">${badge} ${_labRetestPairCN(meta.strategy || pk)}</span>` +
    subTag +
    `<span class="lab-retest-pair-win">窗口: ${_labRetestWinCN(meta.window)}</span>` +
    `<span>综合分: ${meta.score != null ? (meta.score * 100).toFixed(0) : "-"}</span>` +
    `<span>交易: ${meta.n != null ? meta.n : "-"}</span>` +
    `<span style="${_labDdColor(meta.dd)}">回撤: ${_labRetestPct(meta.dd)}</span>` +
    `<span style="color:${_labRetestColor(meta.win)}">胜率: ${_labRetestPct(meta.win)}</span>` +
    "</div>";


  return `<div class="lab-retest-pair">${headHTML}${_labRetestPairSlicesHTML(pd)}</div>`;
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

// 通用 hover 双向关联高亮（单一/融合/二次测试三实验共用）：
// ① 右榜行 hover -> 全局匹配左卡片加 .lab-hover-link（不判可见，加 class 后滚动可见即可见高亮）
// ② 左卡片 hover -> 右榜可见范围内匹配行加 .lab-hover-link（不可见不高亮，不自动滚动；用 getBoundingClientRect 判与视口/滚动容器交集）
// 左卡用 data-lab-hover-bound 标记防重复绑定（右榜局部 rerender 时左卡不变，跳过重绑）。
// opts: { rankScope, cardSelector, itemSelector, cardKey(card)->str, itemKey(item)->str, isRelated(cardKey,itemKey)->bool, itemContainer()->el|null }
function _labHoverLinkVisible(el, container) {
  var r = el.getBoundingClientRect();
  if (!r.width || !r.height) return false;
  var vh = (typeof window !== "undefined" && window.innerHeight) || (document.documentElement && document.documentElement.clientHeight) || 0;
  if (r.bottom <= 0 || r.top >= vh) return false; // 不在视口纵向
  if (container) {
    var cr = container.getBoundingClientRect();
    if (r.bottom <= cr.top || r.top >= cr.bottom) return false; // 不在滚动容器纵向可见区
  }
  return true;
}
function _labHoverLinkAttach(opts) {
  var rankScope = opts.rankScope;
  if (!rankScope) return;
  var cardSelector = opts.cardSelector, itemSelector = opts.itemSelector;
  var cardKey = opts.cardKey, itemKey = opts.itemKey, isRelated = opts.isRelated;
  // ① 右榜行 hover -> 左卡（每次 rerender 右榜行是新元素，直接绑无重复）
  rankScope.querySelectorAll(itemSelector).forEach(function (item) {
    item.addEventListener("mouseenter", function () {
      var ik = itemKey(item); if (!ik) return;
      document.querySelectorAll(cardSelector).forEach(function (c) {
        if (isRelated(cardKey(c), ik)) c.classList.add("lab-hover-link");
      });
    });
    item.addEventListener("mouseleave", function () {
      document.querySelectorAll(".lab-hover-link").forEach(function (c) { c.classList.remove("lab-hover-link"); });
    });
  });
  // ② 左卡 hover -> 右榜可见行（左卡用标记防重复；右榜行现场查，rerender 后自动指向新行）
  document.querySelectorAll(cardSelector).forEach(function (card) {
    if (card.getAttribute("data-lab-hover-bound") === "1") return;
    card.setAttribute("data-lab-hover-bound", "1");
    card.addEventListener("mouseenter", function () {
      var ck = cardKey(card); if (!ck) return;
      var container = opts.itemContainer ? opts.itemContainer() : null;
      rankScope.querySelectorAll(itemSelector).forEach(function (it) {
        if (!isRelated(ck, itemKey(it))) return;
        if (_labHoverLinkVisible(it, container)) it.classList.add("lab-hover-link");
      });
    });
    card.addEventListener("mouseleave", function () {
      document.querySelectorAll(".lab-hover-link").forEach(function (c) { c.classList.remove("lab-hover-link"); });
    });
  });
}

// 结果区事件绑定（列表项点击+更多按钮）。全量重渲染和仅结果重渲染都调用本函数。
function _labRankAttachResultsHandlers(section, simData) {
  section.querySelectorAll(".lab-rank-item").forEach((item) => {
    item.onclick = () => _labRankOpenModal(simData, item.dataset.buy, item.dataset.sell, item.dataset.mode);
  });
  // ⭐️进入二次测试 标记点击：阻止冒泡到行按钮(不弹配对详情)，跳转到二次测试tab并高亮该配对
  section.querySelectorAll(".lab-rank-retest").forEach((span) => {
    span.onclick = (e) => {
      e.stopPropagation();
      e.preventDefault();
      const item = span.closest(".lab-rank-item");
      const bk = item ? item.dataset.buy : "";
      const sk = item ? item.dataset.sell : "";
      if (bk && sk) _labRankRetestJump(bk, sk);
    };
  });
  const more = section.querySelector(".lab-rank-more");
  if (more) more.onclick = () => { state.labRankShowAll = !state.labRankShowAll; _labRankRerenderResults(section, simData); };
  // 双向 hover 关联高亮：右榜行 <-> 左卡片同策略（单一/融合实验，成分匹配 buyKey|sellKey）
  _labHoverLinkAttach({
    rankScope: section,
    cardSelector: ".lab-strategy-list .lab-strategy-card[data-key]",
    itemSelector: ".lab-rank-item",
    cardKey: function (c) { return c.getAttribute("data-key") || ""; },
    itemKey: function (it) { return (it.dataset.buy || "") + "|" + (it.dataset.sell || ""); },
    isRelated: function (ck, ik) { if (!ck || !ik) return false; var p = ik.split("|"); return ck === p[0] || ck === p[1]; },
    itemContainer: function () { return section.querySelector(".lab-rank-list"); },
  });
}

// 推荐榜"⭐️进入二次测试"点击跳转：切到二次测试tab，传高亮key，渲染后定位+高亮该配对卡片
function _labRankRetestJump(buyKey, sellKey) {
  state.labRetestHighlight = buyKey + "|" + sellKey; // 一次性高亮key，消费于 _labRetestRenderCards 末尾
  state.labSubMode = "retest";
  state.labStrategy = null; // 切模式清空策略选择，避免串模式
  renderSignalLab();
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

// 配对排行弹窗：复用 _labSimModeBlock 渲染 4数字+净值曲线+交易记录
function _labRankOpenModal(simData, buyKey, sellKey, mode) {
  let overlay = document.getElementById("labRankOverlay");
  if (!overlay) {
    overlay = document.createElement("div");
    overlay.id = "labRankOverlay";
    overlay.className = "lab-rank-overlay";
    document.body.appendChild(overlay);
  }
  state.labRankModal = { buyKey, sellKey, mode: mode || "full_in", win: state.labSimWindow || "y5", page: 0, open: true };
  _labRankModalRender(overlay, simData);
  overlay.classList.add("show");
  document.body.style.overflow = "hidden";
  overlay.onclick = (e) => { if (e.target === overlay) _labRankCloseModal(); };
  // 详情需 full 数据(trades/equity_curve)，未加载则按需加载（带进度条）并重渲染
  // 融合tab的simData来自融合缓存，full也必须合并入融合缓存，故按 isFusion 分流
  const idx = (simData && simData.index_id) || (state.labSimIndex || "sh");
  const isFusion = state.labSubMode === "fusion";
  if (isFusion ? !_labSimFusionFullLoaded(idx) : !_labSimFullLoaded(idx)) _labRankEnsureFull(overlay, simData, idx);
}

// 弹窗内按需加载 full 数据：更新 loading 占位为进度条，加载完重渲染
async function _labRankEnsureFull(overlay, simData, idx) {
  const isFusion = state.labSubMode === "fusion";
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
  // 融合tab用融合full源(独立缓存labSimFusionFullMap)，单信号tab用单信号full源
  const fullLoader = isFusion ? fetchLabFusionSimFullData : fetchLabSimFullData;
  try {
    await fullLoader(idx, (received, total) => {
      setProg(total > 0 ? Math.round(received / total * 100) : -1);
    }, controller.signal);
  } finally {
    clearTimeout(slowTimer);
  }
  // 加载成功则重渲染弹窗；失败/超时则显示重试按钮
  if (isFusion ? _labSimFusionFullLoaded(idx) : _labSimFullLoaded(idx)) {
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
  const mode = m.mode || "full_in";
  const win = m.win || "y5";
  const pairData = _labGetPair(simData, m.buyKey, m.sellKey);
  const winData = _labPairWinData(pairData, mode, win, simData);
  const buyName = (LAB_STRATEGIES[m.buyKey] || {}).name || m.buyKey;
  const sellName = (LAB_STRATEGIES[m.sellKey] || {}).name || m.sellKey;
  const modeName = mode === "full_in" ? "全仓" : "定额（10%）";
  const winLabel = (LAB_WIN_DEFS.find((w) => w.k === win) || {}).l || "";
  const initCapital = (simData && simData.initial_capital) || 100000;
  const idx = (simData && simData.index_id) || state.labSimIndex || "sh";
  let bodyHTML;
  if (!winData || !winData.stats) {
    bodyHTML = '<div class="lab-rank-modal-empty">该配对无交易数据</div>';
  } else {
    // 同步 page 到有效范围（_labSimModeBlock 内部也会 clamp，此处保持 state 一致）
    const trades = winData.trades || [];
    const totalPages = Math.max(1, Math.ceil(trades.length / 20));
    if (m.page > totalPages - 1) m.page = totalPages - 1;
    if (m.page < 0) m.page = 0;
    // 三区一致：买卖模式切换 + 时间窗口切换 + 用法说明（照抄 retest 弹窗）
    const modeBar = '<div class="lab-win-bar"><span class="lab-win-bar-label">买卖模式</span>' +
      '<div class="lab-win-tabs">' +
      `<button type="button" class="lab-win-tab${mode === "full_in" ? " active" : ""}" data-mode="full_in">全仓</button>` +
      `<button type="button" class="lab-win-tab${mode === "fixed_10k" ? " active" : ""}" data-mode="fixed_10k">定额（10%）</button>` +
      '</div></div>';
    const winBar = `<div class="lab-win-bar"><span class="lab-win-bar-label">时间窗口</span>${_labModalWinTabsHTML(win)}<span class="lab-win-bar-cur">${winLabel}</span></div>`;
    const switchHint = '<div class="lab-retest-modal-switch-hint">💡 可切换时间窗口和买卖模式，查看该策略在不同条件下的战绩</div>';
    bodyHTML = modeBar + switchHint + _labSimModeBlock(mode, winData, initCapital, m.page, m.open, null, null, null, idx);
  }
  overlay.innerHTML = `<div class="lab-rank-modal">` +
    `<div class="lab-rank-modal-head">` +
    `<span class="lab-rank-modal-title">买${buyName} × 卖${sellName} · ${modeName}（${winLabel}） · ${_labIdxName(idx)}</span>` +
    `<button type="button" class="lab-rank-modal-close" aria-label="关闭">✕</button>` +
    `</div>` +
    `<div class="lab-rank-modal-body">${bodyHTML}</div>` +
    `</div>`;
  overlay.querySelector(".lab-rank-modal-close").onclick = _labRankCloseModal;
  // 三区一致：模式/窗口切换（切换重置分页）
  overlay.querySelectorAll(".lab-win-tab[data-mode]").forEach((btn) => {
    btn.onclick = () => { m.mode = btn.dataset.mode; m.page = 0; _labRankModalRender(overlay, simData); };
  });
  overlay.querySelectorAll(".lab-win-tab[data-win]").forEach((btn) => {
    btn.onclick = () => { m.win = btn.dataset.win; m.page = 0; _labRankModalRender(overlay, simData); };
  });
  const hdr = overlay.querySelector(".lab-sim-trades-header");
  if (hdr) hdr.onclick = () => { m.open = !m.open; _labRankModalRender(overlay, simData); };
  const prev = overlay.querySelector(".lab-sim-prev");
  if (prev) prev.onclick = () => { if (m.page > 0) { m.page--; _labRankModalRender(overlay, simData); } };
  const next = overlay.querySelector(".lab-sim-next");
  if (next && !next.disabled) next.onclick = () => { m.page++; _labRankModalRender(overlay, simData); };
}

// === 买卖信号弹窗：配对详情入口，显示买/卖策略图表+品类切换 ===
function _labSignalOpenModal(buyKey, sellKey, idxOverride) {
  let overlay = document.getElementById("labSignalOverlay");
  if (!overlay) {
    overlay = document.createElement("div");
    overlay.id = "labSignalOverlay";
    overlay.className = "lab-signal-overlay";
    document.body.appendChild(overlay);
  }
  // 同步外部选择：指数取模拟回测 labSimIdx（信号按钮在 sim 卡片内）+ 窗口取 labSimWindow
  // 融合弹窗传 idxOverride=m.index 避免用旧 state.labSimIdx 串台（切指数后 state.labSimIdx 未同步）
  state.labSignalModal = {
    buyKey, sellKey,
    index: idxOverride || state.labSimIdx || state.labIndex || "sh",
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
    ["A股宽基", ["sh", "sz", "cyb", "csi500", "csi1000", "kc50", "hs300", "sz50", "bj50"]],
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
    const r = await fetchJSON(`https://ssd.fx8.store/index/${m.index}-all.json`);
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
    const gv = document.getElementById("labGlossaryOverlay");
    if (gv && gv.classList.contains("show")) _labGlossaryCloseModal();
    const av = document.getElementById("labAIScoreOverlay");
    if (av && av.classList.contains("show")) _labAIScoreCloseModal();
  }
});

// 渲染策略实验主入口（分区tab + 卡片列表 / 详情页）
// === 二级导航（单一信号实验 / 融合信号实验）===
function _renderLabSubNav() {
  const cur = state.labSubMode || "single";
  const subNav = document.createElement("div");
  subNav.className = "lab-subnav";
  // 信号扫描(scan)为父tab，下挂3个三级子tab(信号拆解/多空对称/参数扫描)
  const _LAB_SUB_TABS = [
    { key: "scan", label: "信号扫描" },
    { key: "experiment", label: "信号实验" },
    { key: "retest", label: "🔬 二次测试实验" },
    { key: "custom", label: "🎯 自定义分析" },
    { key: "aiscore", label: "📈 AI评分" },
  ];
  const _SCAN_CHILDREN = ["ablation", "symmetry", "paramscan"];
  const _SCAN_CHILD_LABELS = { ablation: "🧩 信号拆解", symmetry: "⚖️ 多空对称", paramscan: "🎛 参数扫描" };
  const _EXPERIMENT_CHILDREN = ["single", "fusion"];
  const _EXPERIMENT_CHILD_LABELS = { single: "单一信号实验", fusion: "融合信号实验" };
  const isScanActive = _SCAN_CHILDREN.includes(cur);
  const isExperimentActive = _EXPERIMENT_CHILDREN.includes(cur);
  subNav.innerHTML = _LAB_SUB_TABS.map((t) => {
    const active = t.key === "scan" ? isScanActive : t.key === "experiment" ? isExperimentActive : cur === t.key;
    return `<button type="button" class="lab-subnav-tab${active ? " active" : ""}" data-sub="${t.key}">${t.label}</button>`;
  }).join("") +
  `<button type="button" class="lab-subnav-tab lab-subnav-glossary" data-glossary-btn="1">❓ 术语词典</button>`;
  subNav.querySelectorAll(".lab-subnav-tab").forEach((btn) => {
    btn.onclick = () => {
      // 术语词典按钮：打开词典modal，不切模式
      if (btn.dataset.glossaryBtn) { _labGlossaryOpenModal(); return; }
      // scan 父tab点击 -> 默认进第一个子tab(ablation)
      state.labSubMode = btn.dataset.sub === "scan" ? "ablation" : btn.dataset.sub === "experiment" ? "single" : btn.dataset.sub;
      state.labStrategy = null; // 切换模式时清空策略选择，避免串模式
      renderSignalLab();
    };
  });
  content.appendChild(subNav);

  // 三级子nav：信号扫描父tab active 时，在二级nav下方渲染一行子tab(信号拆解/多空对称/参数扫描)
  if (isScanActive) {
    const childNav = document.createElement("div");
    childNav.className = "lab-subnav lab-subnav-child";
    childNav.innerHTML = _SCAN_CHILDREN.map((k) =>
      `<button type="button" class="lab-subnav-tab${cur === k ? " active" : ""}" data-sub="${k}">${_SCAN_CHILD_LABELS[k]}</button>`
    ).join("");
    childNav.querySelectorAll(".lab-subnav-tab").forEach((btn) => {
      btn.onclick = () => {
        state.labSubMode = btn.dataset.sub;
        state.labStrategy = null;
        renderSignalLab();
      };
    });
    content.appendChild(childNav);
  }

  // 三级子nav：信号实验父tab active 时，在二级nav下方渲染一行子tab(单一信号实验/融合信号实验)
  if (isExperimentActive) {
    const childNav = document.createElement("div");
    childNav.className = "lab-subnav lab-subnav-child";
    childNav.innerHTML = _EXPERIMENT_CHILDREN.map((k) =>
      `<button type="button" class="lab-subnav-tab${cur === k ? " active" : ""}" data-sub="${k}">${_EXPERIMENT_CHILD_LABELS[k]}</button>`
    ).join("");
    childNav.querySelectorAll(".lab-subnav-tab").forEach((btn) => {
      btn.onclick = () => {
        state.labSubMode = btn.dataset.sub;
        state.labStrategy = null;
        renderSignalLab();
      };
    });
    content.appendChild(childNav);
  }
}

// === 融合信号列表页（阶段一：仅展示元数据，不跑回测）===
async function renderFusionLab() {
  // 左右2栏布局：融合策略卡左 + 回测配对对比榜右（照搬 renderSignalLab 列表页 .lab-list-2col 模式）
  const wrapper = document.createElement("div");
  wrapper.className = "lab-list-2col";
  const leftCol = document.createElement("div");
  const rightCol = document.createElement("div");

  // 实验室自白黄块
  const essayWarn = document.createElement("div");
  essayWarn.className = "lab-warning lab-warning-essay";
  essayWarn.innerHTML = _labFusionEssayHTML();
  const purposeNote = document.createElement("div");
  purposeNote.className = "lab-purpose-note";
  purposeNote.innerHTML = "💡 <b>这板块有什么用</b>：把多个信号同日共振组合成融合策略回测--看组合共振是否比单信号更准、更能过滤假信号。<b>怎么解读</b>：融合卡显示组成条件和触发逻辑；点击看配对回测（买×卖）或同向共振回测的胜率/收益/5窗口。融合优于单一=共振有效，否则多信号没带来增量。";
  leftCol.appendChild(purposeNote);
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
  zoneTabs.insertAdjacentHTML("beforeend", _labHelpIcon("status"));
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
      card.dataset.key = key;
      card.innerHTML =
        `<div class="lab-card-top">` +
        `<span class="lab-card-name">${_labStratNameHTML(key, meta.name)}${_labHelpIcon("fusion_signal")}</span>` +
        `<span class="lab-tag ${tag.cls}">${tag.label}</span>` +
        `</div>` +
        condsHTML +
        `<div class="lab-card-trigger">${meta.trigger}</div>` +
        `<div class="lab-card-conclusion">${meta.conclusion}</div>` +
        (meta._pairType
          ? `<div class="lab-fusion-pair-hint">${meta._pairType === "buy_sell" ? "📊 点击查看配对回测" : "🔬 点击查看同向共振回测"}（胜率·收益·5窗口）▸</div>`
          : `<div class="lab-fusion-pair-hint">🔬 点击查看融合回测（胜率·收益·5窗口）▸</div>`);
      card.classList.add("lab-fusion-clickable");
      card.title = meta._pairType
        ? `点击查看${meta._pairType === "buy_sell" ? "配对" : "同向共振"}回测（胜率/收益/5窗口）`
        : "点击查看融合回测（胜率/收益/5窗口）";
      card.onclick = () => { _labFusionPairOpenModal({ ...meta, _fusionKey: key }); };
      list.appendChild(card);
    });
  }
  leftCol.appendChild(list);

  // 阶段提示
  const phaseNote = document.createElement("div");
  phaseNote.className = "lab-fusion-phase-note";
  phaseNote.innerHTML = "📌 <b>买×卖配对</b>（49对）+ <b>同向共振</b>" + _labHelpIcon("co_resonance") + "（买×买/卖×卖各21对）均已接入回测数据，点击卡片查看胜率/收益/5窗口。" + _labHelpIcon("count");
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

  // 回测配对对比榜（右栏，照搬 renderSignalLab 列表页配对排行结构：指数选择器+排序tab+过滤+body）
  const rankSection = document.createElement("div");
  rankSection.className = "chart-card lab-rank-card";
  const _curIdx = state.labSimIndex || "sh";
  const rankIdxBtns = LAB_SIM_INDEXES.map((x) =>
    `<button type="button" class="lab-idx-tab${x.id === _curIdx ? " active" : ""}" data-idx="${x.id}">${x.name}</button>`
  ).join("");
  rankSection.innerHTML = '<h3>🏆 回测配对对比榜' + _labHelpIcon("pair") + '</h3>' +
    '<div class="lab-rank-sub-note">一个买点+一个卖点组成一对完整交易，7买×7卖=49对</div>' +
    `<div class="lab-win-bar"><span class="lab-win-bar-label">选择指数</span><div class="lab-win-tabs">${rankIdxBtns}</div></div>` +
    `<div class="lab-win-bar lab-shape-bar"><span class="lab-win-bar-label">形态分析</span><button type="button" class="lab-shape-btn" title="取近20日归一化日收益率，在全历史中滑窗匹配最相似时段">🔮 当前指数相似形态匹配</button><span class="lab-shape-hint">A10 · 历史相似时段 + top1 延伸走势参考</span></div>` +
    '<div class="lab-rank-body"><div class="lab-rank-loading">⏳ 加载配对排行数据中…</div></div>';
  rightCol.appendChild(rankSection);
  // 组装2栏
  wrapper.appendChild(leftCol);
  wrapper.appendChild(rightCol);
  content.appendChild(wrapper);
  // 加载配对排行数据（融合模式：_labRankHTML 依 state.labSubMode==='fusion' 仅展示实验中策略买×卖配对）
  // 注意：融合tab必须读融合源 lab_sim_{index}_fusion_stats.json（145配对），单信号源只有64配对会漏显示
  const _loadRank = async () => {
    const idx = state.labSimIndex || "sh";
    const [simData] = await Promise.all([fetchLabFusionSimData(idx), fetchLabRetestData(idx)]);
    _labRankRerender(rankSection, simData);
  };
  _loadRank();
  // A10 相似形态：点击用当前选中指数打开 trade_sim modal 的相似形态视图（复用 app.js 实现）
  const _shapeBtn = rankSection.querySelector(".lab-shape-btn");
  if (_shapeBtn) {
    _shapeBtn.onclick = () => {
      const idx = state.labSimIndex || "sh";
      if (typeof _tradeSimOpenModal === "function") _tradeSimOpenModal(idx, "shape");
    };
  }
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
  if (!sk) {
    // F_ 独立融合策略(无|)
    const fm = LAB_FUSION_STRATEGIES[bk];
    return fm ? `${fm.name}（独立）` : bk;
  }
  const isFusion = bk.indexOf("F_") === 0 || sk.indexOf("F_") === 0;
  const bm = LAB_STRATEGIES[bk], sm = LAB_STRATEGIES[sk];
  const bn = (bm && bm.name) || bk, sn = (sm && sm.name) || sk;
  if (!bm && !isFusion) console.warn("retest 中文化:未知买策略 key", bk);
  if (!sm && !isFusion) console.warn("retest 中文化:未知卖策略 key", sk);
  // 同向共振(buy_buy/sell_sell)按共振格式，不再硬编码"买X×卖Y"
  const bz = bm && bm.zone, sz = sm && sm.zone;
  if (!isFusion && bz === "buy" && sz === "buy") return `双买共振 ${bn} × ${sn}`;
  if (!isFusion && bz === "sell" && sz === "sell") return `双卖共振 ${bn} × ${sn}`;
  return `买${bn} × 卖${sn}`;
}

// meta.window("y5"等) -> 中文窗口名（复用 LAB_WIN_CN）
function _labRetestWinCN(win) {
  const cn = LAB_WIN_CN[win];
  if (!cn && win) console.warn("retest 中文化:未知窗口 key", win);
  return cn || win || "-";
}

// 二次测试分类按钮(融合9指数后,按候选类型过滤:主候选/替补/全部)
const LAB_RETEST_ZONES = [
  { key: "star", label: "⭐️ 主候选" },
  { key: "sub", label: "🔵 替补" },
  { key: "all", label: "全部" },
];

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

// 聚合 retest pairs -> 行：算8维指标（归一化 across 全部9指数所有 pair）+ 各综合分。
// pair_meta 全小数（0.27=27%），显示时×100%。融合9指数后归一化跨全部指数一起算 min/max。
function _labRetestRankRows(allPairs, simMap, winKey) {
  if (!allPairs || allPairs.length === 0) return [];
  const wk = winKey || "y5"; // 5窗口切换：默认 y5（与 retest 后端窗口一致）
  // 从单个 data( top-level=full_in 或 pd.fixed_10k )提取一行原始指标
  // mode 决定整体4维从 simData pd2[mode].stats[wk] 取，以及 modeCn 标注
  // simData 按 pair 所属指数从 simMap 取(融合9指数,每 pair 对应各自指数的 simData)
  const extract = (pk, data, mode, simData) => {
    const meta = data.pair_meta || {};
    // 整体4维(ret/win/dd/n)：优先用单信号 simData 该窗口该模式 stats（支持5窗口切换）；
    // simData 缺失或该窗口无数据时回退 pair_meta（后端 y5 值）。
    // 单信号 stats 为百分数(10.87)，pair_meta 为小数(0.1087)，统一为小数。
    let ret = meta.ret != null ? meta.ret : 0;
    let winRate = meta.win != null ? meta.win : 0;
    let dd = meta.dd != null ? meta.dd : 0;
    let n = meta.n != null ? meta.n : 0;
    // annual_ret + 5质量指标(P0-1展示/B2 wholeScore): 仅 simData stats 有,pair_meta 无,回退0。
    let annualRet = 0;
    let pf = 0, pr = 0, sh = 0, so = 0, ex = 0;
    if (simData && meta.strategy) {
      const parts = meta.strategy.split("|");
      const pd2 = _labGetPair(simData, parts[0], parts[1]);
      const s = pd2 && pd2[mode] && pd2[mode].stats && pd2[mode].stats[wk];
      if (s) {
        ret = s.total_ret / 100;
        winRate = s.win_rate / 100;
        dd = s.max_drawdown / 100;
        n = s.n_trades;
        annualRet = s.annual_ret;
        pf = s.profit_factor; pr = s.payoff_ratio;
        sh = s.sharpe; so = s.sortino; ex = s.expectancy;
      }
    }
    // risk_adj: 年化/回撤(类Calmar),分母floor 2.0%(dd为小数,×100与annualRet百分数对齐;与后端一致)
    const risk_adj = annualRet / Math.max(dd * 100, 2.0);
    const yearly = data.yearly || {};
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
    const oos = data.oos || {};
    const tr = oos.train || {}, te = oos.test || {};
    const testRet = te.ret != null ? te.ret : 0;
    const overfit = (tr.ret != null && te.ret != null) ? Math.abs(tr.ret - te.ret) : 0; // 过拟合度
    const testWin = te.win != null ? te.win : 0;
    const regimes = data.regimes || {};
    const crash = regimes.crash2015 || null;
    const bear = regimes.bear2018 || null;
    const rally = regimes.rally2024 || null;
    const covid = regimes.covid2020 || null; // null=无交易
    // 小样本标注：某年 n<3 或 oos test n<10
    const yearSmall = yKeys.some((yr) => yearly[yr] && yearly[yr].n != null && yearly[yr].n < 3);
    const oosSmall = (te.n != null && te.n < 10);
    return {
      pk,
      mode,
      strategy: meta.strategy || pk,
      window: meta.window || "-",
      cn: _labRetestPairCN(meta.strategy || pk),
      winCn: _labRetestWinCN(meta.window),
      modeCn: mode === "full_in" ? "全仓" : "定额10%",
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
      // 风险调整 + 5质量指标(P0-1展示/B2 wholeScore)
      risk_adj, annual_ret: annualRet,
      profit_factor: pf, payoff_ratio: pr, sharpe: sh, sortino: so, expectancy: ex,
    };
  };
  // Pass1：每对出2行(全仓 full_in + 定额10% fixed_10k)，fixed_10k 缺失则只出 full_in。
  // 融合9指数:遍历 allPairs,每 pair 按所属指数取 simData,行携带 index/index_name/cardid
  const raw = [];
  allPairs.forEach((item) => {
    const pd = item.pd || {};
    const isSub = !!item.substitute;
    const subReason = item.reason || "";
    const sd = simMap ? (simMap[item.index] || null) : null;
    const fr = extract(item.pk, pd, "full_in", sd);
    fr.substitute = isSub; fr.subReason = subReason;
    fr.index = item.index; fr.index_name = item.index_name; fr.cardid = item.cardid;
    raw.push(fr);
    if (pd.fixed_10k) {
      const fxr = extract(item.pk, pd.fixed_10k, "fixed_10k", sd);
      fxr.substitute = isSub; fxr.subReason = subReason;
      fxr.index = item.index; fxr.index_name = item.index_name; fxr.cardid = item.cardid;
      raw.push(fxr);
    }
  });
  // Pass2：各指标 min-max 归一（across 全部9指数所有 pair 的全仓+定额行）
  const retN = _labRetestMinMax(raw, "ret");
  const winN = _labRetestMinMax(raw, "win");
  const ddN = _labRetestMinMax(raw, "dd");
  const riskN = _labRetestMinMax(raw, "risk_adj");
  const minYearRetN = _labRetestMinMax(raw, "minYearRet");
  const yearVolN = _labRetestMinMax(raw, "yearVol");
  const testRetN = _labRetestMinMax(raw, "testRet");
  const overfitN = _labRetestMinMax(raw, "overfit");
  const testWinN = _labRetestMinMax(raw, "testWin");
  const crashDdN = _labRetestMinMax(raw, "crashDd");
  const bearDdN = _labRetestMinMax(raw, "bearDd");
  const rallyRetN = _labRetestMinMax(raw, "rallyRet");
  const covidDdN = _labRetestMinMax(raw, "covidDd");
  // Pass3：各综合分（归一化加权，across 所有模式行；full_in 与定额10%各自三切片独立算分）
  return raw.map((r) => {
    // 整体归一 = 0.35*ret + 0.25*win + 0.15*(1-dd) + 0.15*risk_adj + 0.1*(1-exp(-n/30))
    // (P1-1 与主榜/后端一致: risk_adj 第5因子 + 凹n; retest候选集小故不winsorize,用min-max)
    const wholeScore = 0.35 * retN(r.ret) + 0.25 * winN(r.win) + 0.15 * (1 - ddN(r.dd)) + 0.15 * riskN(r.risk_adj) + 0.1 * (1 - Math.exp(-r.n / 30));
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
  // 无交易(n<=0/null/NaN)的配对所有维度排末尾：避免回撤0被当最小排第一(与_labRankSort同因)。
  arr.sort((a, b) => {
    const an = a.n > 0, bn = b.n > 0;
    if (an !== bn) return an ? -1 : 1; // 有交易优先，无交易沉底
    if (tab === "ret") return b.ret - a.ret;
    if (tab === "win") return b.win - a.win;
    if (tab === "dd") return a.dd - b.dd; // 回撤小优先
    if (tab === "n") return b.n - a.n;
    if (tab === "yearly") return b.yearlyScore - a.yearlyScore;
    if (tab === "oos") return b.oosScore - a.oosScore;
    if (tab === "regimes") return b.regimeScore - a.regimeScore;
    return b.score - a.score; // 综合(新公式，含三切片)
  });
  return arr;
}

// 小样本灰色标注 tag（某年n<3 或 oos test n<10）
function _labRetestSmallTag(flag) {
  return flag ? ' <span class="lab-rank-small">小样本</span>' : "";
}

// 荣誉共享标注：返回 row.pk 在"其他(指数×窗口)"下的 Top3 排名徽章 HTML。
// 融合9指数后每行有自己的 index,排除该行自身(idx,win)的荣誉(只标其他条件)；最多显示 4 枚避免拥挤。
// 徽章 = 奖牌emoji + 短标签(同指数显窗口名/异指数显指数名+窗口名)，点击跳转对应条件。
function _labRetestHonorsHTML(pk, rowIdx, rowWin) {
  const honors = state.labRetestHonors;
  if (!honors || !pk) return "";
  const list = honors[pk];
  if (!list || !list.length) return "";
  const curIdx = rowIdx || state.labSimIndex || "sh";
  const curWin = rowWin || state.labRetestRankWindow || "y5";
  // 排除当前(idx,win)；荣誉已按 rank 升序存，取前 4 条
  const shown = list.filter((h) => !(h.idx === curIdx && h.win === curWin)).slice(0, 4);
  if (!shown.length) return "";
  const idxName = (id) => ((LAB_SIM_INDEXES.find((x) => x.id === id) || {}).name) || id;
  const winLabel = (w) => ((LAB_WIN_DEFS.find((x) => x.k === w) || {}).l) || w;
  const medal = (r) => (r === 1 ? "🥇" : r === 2 ? "🥈" : r === 3 ? "🥉" : "");
  const badges = shown.map((h) => {
    const label = h.idx === curIdx ? winLabel(h.win) : (idxName(h.idx) + " " + winLabel(h.win));
    return `<span class="lab-rank-honor-badge" data-rank="${h.rank}" data-hidx="${h.idx}" data-hwin="${h.win}" ` +
      `title="该策略在 ${idxName(h.idx)}·${winLabel(h.win)} 排第${h.rank}，点击跳转">` +
      `${medal(h.rank)}${label}</span>`;
  }).join("");
  return `<span class="lab-rank-honors">🏆其他条件排名 ${badges}</span>`;
}

// 荣誉徽章点击：跳转到对应(指数,窗口)。融合9指数后无单指数切换,直接切窗口重渲染右榜+复合键高亮。
function _labRetestHonorJump(hidx, hwin, focusPk) {
  state.labRetestRankWindow = hwin;
  state.labRetestRankShowAll = false;
  // 复合键高亮:融合后 pk 跨指数重复,用 hidx::pk 精确定位行/卡片
  const focusKey = focusPk ? (hidx + "::" + focusPk) : null;
  state._labRetestRankFocusPk = focusKey; // 右榜行高亮(消费于 rerender/rerenderResults 末尾)
  const sec = state._labRetestRankSection;
  if (sec) {
    _labRetestRankRerender(sec, state.labRetestAllPairs || [], state.labRetestSimMap || {});
  }
  // 左卡片高亮(卡片未重渲,直接定位;若被 zone 过滤不可见则静默放弃)
  if (focusKey) _labRetestHighlightCard(document.querySelector(".lab-retest-list"), focusKey);
}

// 跳转后高亮焦点行:滚动到视图中央 + 金色高亮边框 + 短暂闪烁,让用户一眼看到跳转到哪了。
// 消费 state._labRetestRankFocusPk(一次性)。目标行若被"前20"截断则自动展开全部重渲再定位;仍找不到(被过滤)则静默放弃。
function _labRetestRankFindItem(section, key) {
  let found = null;
  // 融合9指数后 pk 跨指数重复,优先按复合键 cardid 精确匹配,回退按 pk 匹配首个
  section.querySelectorAll(".lab-rank-item").forEach((n) => {
    if (n.dataset.cardid === key || (!found && n.dataset.pk === key)) found = n;
  });
  return found;
}
function _labRetestRankFocusHighlight(section, allPairs, simMap) {
  const pk = state._labRetestRankFocusPk;
  if (!pk) return;
  state._labRetestRankFocusPk = null; // 先消费,避免下方展开重渲时 rerenderResults 递归重复高亮
  let el = _labRetestRankFindItem(section, pk);
  if (!el && !state.labRetestRankShowAll) {
    state.labRetestRankShowAll = true; // 目标在前20之外,展开全部
    _labRetestRankRerenderResults(section, allPairs, simMap); // 内部再调本函数时 pk 已空,直接 return
    el = _labRetestRankFindItem(section, pk);
  }
  if (!el) return; // 被过滤面板挡掉,放弃
  // 清除上一焦点的残留 class
  section.querySelectorAll(".lab-rank-focus").forEach((n) => n.classList.remove("lab-rank-focus", "lab-rank-focus-flash"));
  try { el.scrollIntoView({ block: "center", behavior: "smooth" }); } catch (_) {}
  el.classList.add("lab-rank-focus", "lab-rank-focus-flash");
  clearTimeout(state._labRetestFocusTimer);
  state._labRetestFocusTimer = setTimeout(() => {
    el.classList.remove("lab-rank-focus-flash"); // 停止闪烁
    setTimeout(() => el.classList.remove("lab-rank-focus"), 3500); // 再持续高亮几秒后恢复
  }, 2400);
}

// 绑定荣誉徽章点击(阻止冒泡到行按钮触发弹窗)
function _labRetestRankAttachBadges(section) {
  section.querySelectorAll(".lab-rank-honor-badge").forEach((b) => {
    b.onclick = (e) => {
      e.stopPropagation();
      e.preventDefault();
      const item = b.closest(".lab-rank-item");
      const pk = item ? item.dataset.pk : ""; // 跳转后高亮该 pk 行
      _labRetestHonorJump(b.dataset.hidx, b.dataset.hwin, pk);
    };
  });
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
  const subBadge = row.substitute
    ? `<span class="lab-retest-rank-sub" title="${row.subReason || "未达标"}">🔵替补</span>`
    : "";
  const idxTag = row.index_name ? `<span class="lab-idx-tag">${row.index_name}</span>` : "";
  return `<button type="button" class="lab-rank-item clickable-card" data-pk="${row.pk}" data-idx="${row.index || ""}" data-cardid="${row.cardid || ""}" data-mode="${row.mode}">` +
    `<span class="lab-rank-no">${medal || "#" + rank}</span>` +
    `<span class="lab-rank-name">${row.cn} · ${row.modeCn}</span>` +
    idxTag +
    subBadge +
    `<span class="lab-rank-stats">${baseStats}</span>` +
    _labQualityHTML(row) + extra + _labRetestHonorsHTML(row.pk, row.index, state.labRetestRankWindow || "y5") + `</button>`;
}

// retest 排行榜过滤维度（值是小数 0.1=10%，isPct 字段过滤时×100 与输入百分数比较）
const LAB_RETEST_RANK_FILTERS = [
  { label: "收益(%)", minKey: "retMin", maxKey: "retMax", field: "ret", isPct: true },
  { label: "胜率(%)", minKey: "winMin", maxKey: "winMax", field: "win", isPct: true },
  { label: "回撤(%)", minKey: "ddMin", maxKey: "ddMax", field: "dd", isPct: true },
  { label: "样本数", minKey: "nMin", maxKey: "nMax", field: "n", isPct: false },
];

function _labRetestRankDefaultFilter() {
  return { retMin: "", retMax: "", winMin: "", winMax: "", ddMin: "", ddMax: "", nMin: "", nMax: "" };
}

// 过滤：且组合，min/max 闭区间。isPct 字段把 row 小数×100 与输入百分数比较。
function _labRetestRankApplyFilter(rows) {
  const f = state.labRetestRankFilter;
  if (!f) return rows;
  const has = LAB_RETEST_RANK_FILTERS.some((d) => f[d.minKey] !== "" || f[d.maxKey] !== "");
  if (!has) return rows;
  return rows.filter((r) => {
    for (const d of LAB_RETEST_RANK_FILTERS) {
      const mn = f[d.minKey], mx = f[d.maxKey];
      const val = d.isPct ? r[d.field] * 100 : r[d.field];
      if (mn !== "" && mn != null && val < +mn) return false;
      if (mx !== "" && mx != null && val > +mx) return false;
    }
    return true;
  });
}

// 过滤面板 HTML（复用 _LAB_FSTYLE，绑 state.labRetestRankFilter）。实时过滤只刷新结果区、不重建本面板，保留输入焦点。
function _labRetestRankFilterHTML() {
  if (!state.labRetestRankFilter) state.labRetestRankFilter = _labRetestRankDefaultFilter();
  const f = state.labRetestRankFilter;
  const items = LAB_RETEST_RANK_FILTERS.map((d) =>
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

function _labRetestRankHTML(allPairs, simMap) {
  if (!allPairs) return '<div class="lab-rank-empty">二次测试数据加载失败，请稍后重试</div>';
  const winKey = state.labRetestRankWindow || "y5"; // 5窗口切换：整体4维取自 simData stats[winKey]
  // 融合9指数:无指数选择器(已由左栏分类按钮 zone 替代),行跨全部指数归一化
  const rows = _labRetestRankRows(allPairs, simMap, winKey);
  if (rows.length === 0) return '<div class="lab-rank-empty">暂无二次测试候选配对</div>';
  state.labRetestRankRows = rows;
  const tab = state.labRetestRankTab || "score";
  const tabsHTML = LAB_RETEST_RANK_TABS.map((t) =>
    `<button type="button" class="lab-rank-tab${t.key === tab ? " active" : ""}" data-tab="${t.key}">${t.label}</button>`
  ).join("");
  // 5窗口切换器（独立 state.labRetestRankWindow，不影响配对排行 state.labSimWindow）
  const winTabsHTML = '<div class="lab-win-tabs">' + LAB_WIN_DEFS.map((w) =>
    `<button type="button" class="lab-win-tab${w.k === winKey ? " active" : ""}" data-win="${w.k}">${w.l}</button>`
  ).join("") + "</div>";
  const legend = tab === "score"
    ? "综合分(二次测试)=0.3整体+0.25分年+0.25样本外+0.2极端，归一化加权，越高越稳健。整体分=0.35收益+0.25胜率+0.15回撤+0.15风险调整+0.1样本量(凹函数)，含风险调整第5因子(与主榜一致)。" + _labHelpIcon("score")
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
    _labRetestRankFilterHTML() +
    `<div class="lab-rank-results">${_labRetestRankResultsHTML()}</div>`;
}

function _labRetestRankResultsHTML() {
  const rows = state.labRetestRankRows || [];
  const tab = state.labRetestRankTab || "score";
  let filtered = _labRetestRankApplyFilter(rows);
  // zone 过滤(与左卡片一致:star=主候选 !substitute / sub=替补 substitute / all=全部)
  const zone = state.labRetestZone || "star";
  if (zone === "star") filtered = filtered.filter((r) => !r.substitute);
  else if (zone === "sub") filtered = filtered.filter((r) => r.substitute);
  const sorted = _labRetestRankSort(filtered, tab);
  const showAll = !!state.labRetestRankShowAll;
  const shown = showAll ? sorted : sorted.slice(0, 20);
  const countHTML = `<div style="font-size:12px;color:var(--text-3);margin-bottom:6px;">符合 <b style="color:#9c27b0;">${filtered.length}</b> / 共 ${rows.length} 个候选配对</div>`;
  const itemsHTML = shown.length > 0
    ? shown.map((r, i) => _labRetestRankItemHTML(r, i + 1, tab)).join("")
    : '<div class="lab-rank-empty">暂无数据</div>';
  const moreBtn = sorted.length > 20
    ? `<button type="button" class="lab-rank-more">${showAll ? "收起 ▲" : `显示全部 ${sorted.length} 组 ▼`}</button>`
    : "";
  return countHTML + `<div class="lab-rank-list">${itemsHTML}</div>` + moreBtn;
}

// retest 右榜行 hover：hover 某行时，若左侧卡片有同配对(指数+策略)，加 lab-hover-link 弱化高亮提示关联。
// 双向：左卡片 hover -> 右榜可见范围内同配对行高亮（不可见不高亮，不自动滚动）。
// 融合9指数后 pk 跨指数重复,改用复合键 cardid(index::pk) 精确匹配。
function _labRetestRankAttachItemHover(section) {
  _labHoverLinkAttach({
    rankScope: section,
    cardSelector: ".lab-retest-card",
    itemSelector: ".lab-rank-item",
    cardKey: function (c) { return c.getAttribute("data-cardid") || c.getAttribute("data-pk") || ""; },
    itemKey: function (it) { return it.dataset.cardid || it.dataset.pk || ""; },
    isRelated: function (a, b) { return !!a && a === b; },
    itemContainer: function () { return section.querySelector(".lab-rank-list"); },
  });
}

function _labRetestRankAttachHandlers(section, allPairs, simMap) {
  // 过滤输入：实时过滤（只刷新结果区，保留输入焦点不重建面板）
  section.querySelectorAll(".lab-rank-finput").forEach((inp) => {
    let _labRetestFilterTimer;
    inp.addEventListener("input", () => {
      if (!state.labRetestRankFilter) state.labRetestRankFilter = _labRetestRankDefaultFilter();
      state.labRetestRankFilter[inp.dataset.fk] = inp.value;
      state.labRetestRankShowAll = false;
      clearTimeout(_labRetestFilterTimer);
      _labRetestFilterTimer = setTimeout(() => _labRetestRankRerenderResults(section, allPairs, simMap), 100);
    });
  });
  const freset = section.querySelector(".lab-rank-freset");
  if (freset) freset.onclick = () => {
    state.labRetestRankFilter = _labRetestRankDefaultFilter();
    state.labRetestRankShowAll = false;
    _labRetestRankRerender(section, allPairs, simMap); // 重置需重建面板清空输入框
  };
  section.querySelectorAll(".lab-rank-tab").forEach((btn) => {
    btn.onclick = () => { state.labRetestRankTab = btn.dataset.tab; state.labRetestRankShowAll = false; _labRetestRankRerender(section, allPairs, simMap); };
  });
  // 5窗口切换（整体4维随窗口从 simMap 对应指数 stats[win] 重算重排）
  section.querySelectorAll(".lab-win-tab[data-win]").forEach((btn) => {
    btn.onclick = () => { state.labRetestRankWindow = btn.dataset.win; state.labRetestRankShowAll = false; _labRetestRankRerender(section, allPairs, simMap); };
  });
  section.querySelectorAll(".lab-rank-item").forEach((item) => {
    item.onclick = () => {
      // 融合后同一 pk 可跨指数出现,按行的 data-idx 取对应指数的 rd 传给弹窗
      const idx = item.dataset.idx;
      const rd = (state.labRetestDataMap && state.labRetestDataMap[idx]) || null;
      _labRetestPairOpenModal(rd, item.dataset.pk, item.dataset.mode);
    };
  });
  _labRetestRankAttachItemHover(section); // hover 行高亮左卡片同配对(复合键匹配)
  _labRetestRankAttachBadges(section); // 荣誉徽章点击(跳转其他条件，stopPropagation 不触发行弹窗)
  const more = section.querySelector(".lab-rank-more");
  if (more) more.onclick = () => { state.labRetestRankShowAll = !state.labRetestRankShowAll; _labRetestRankRerenderResults(section, allPairs, simMap); };
}

function _labRetestRankRerenderResults(section, allPairs, simMap) {
  const res = section.querySelector(".lab-rank-results");
  if (!res) return;
  res.innerHTML = _labRetestRankResultsHTML();
  section.querySelectorAll(".lab-rank-item").forEach((item) => {
    item.onclick = () => {
      const idx = item.dataset.idx;
      const rd = (state.labRetestDataMap && state.labRetestDataMap[idx]) || null;
      _labRetestPairOpenModal(rd, item.dataset.pk, item.dataset.mode);
    };
  });
  _labRetestRankAttachItemHover(section); // 局部刷新后重绑 hover
  _labRetestRankAttachBadges(section); // 局部刷新结果区后重绑徽章
  const more = section.querySelector(".lab-rank-more");
  if (more) more.onclick = () => { state.labRetestRankShowAll = !state.labRetestRankShowAll; _labRetestRankRerenderResults(section, allPairs, simMap); };
  _labRetestRankFocusHighlight(section, allPairs, simMap); // 跳转高亮(无 focusKey 时直接 return)
}

function _labRetestRankRerender(section, allPairs, simMap) {
  const body = section.querySelector(".lab-rank-body");
  if (body) body.innerHTML = _labRetestRankHTML(allPairs, simMap);
  _labRetestRankAttachHandlers(section, allPairs, simMap);
  _labRetestRankFocusHighlight(section, allPairs, simMap); // 跳转高亮(切窗口/荣誉跳转均经此)
}

// 左卡片高亮（共用）：定位+滚动+金色边框 lab-retest-focus + 短暂闪烁。返回是否找到并高亮。
// 用于：①推荐榜"⭐️进入二次测试"跳转 ②荣誉徽章(🥇近10年等)跳转后高亮左卡片。
// 纯高亮，不设右榜焦点（右榜焦点由调用方通过 _labRetestRankFocusPk 单独设）。
function _labRetestHighlightCard(list, key) {
  if (!list || !key) return false;
  let card = null;
  // 融合9指数后 pk 跨指数重复,优先按复合键 cardid(index::pk)精确匹配,回退按 pk 匹配首个
  list.querySelectorAll(".lab-retest-card").forEach((c) => {
    if (c.dataset.cardid === key || (!card && c.dataset.pk === key)) card = c;
  });
  if (!card) return false;
  list.querySelectorAll(".lab-retest-focus").forEach((n) => n.classList.remove("lab-retest-focus", "lab-retest-focus-flash"));
  try { card.scrollIntoView({ block: "center", behavior: "smooth" }); } catch (_) {}
  card.classList.add("lab-retest-focus", "lab-retest-focus-flash");
  clearTimeout(state._labRetestCardFocusTimer);
  state._labRetestCardFocusTimer = setTimeout(() => {
    card.classList.remove("lab-retest-focus-flash"); // 停止闪烁
    setTimeout(() => card.classList.remove("lab-retest-focus"), 3500); // 再持续高亮几秒后恢复
  }, 2400);
  return true;
}

// 左栏候选配对卡片：融合9指数后按 zone(主候选/替补/全部)过滤,每卡标所属指数+⭐️/🔵,点击弹窗
function _labRetestRenderCards(list, allPairs) {
  if (!allPairs || allPairs.length === 0) { list.innerHTML = '<div class="lab-rank-empty">暂无二次测试候选配对</div>'; return; }
  // 按 zone 过滤 (star=主候选 !substitute / sub=替补 substitute / all=全部)
  const zone = state.labRetestZone || "star";
  let shown = allPairs;
  if (zone === "star") shown = allPairs.filter((a) => !a.substitute);
  else if (zone === "sub") shown = allPairs.filter((a) => a.substitute);
  if (shown.length === 0) {
    const tip = zone === "star" ? "主候选暂无达标配对(均未达 0.6 分/55% 胜率/1.5 风险调整阈值)，试试 🔵替补" :
      zone === "sub" ? "替补暂无配对" : "暂无二次测试候选配对";
    list.innerHTML = `<div class="lab-rank-empty">${tip}</div>`;
    return;
  }
  list.innerHTML = shown.map((item) => {
    const meta = (item.pd && item.pd.pair_meta) || {};
    const cn = _labRetestPairCN(meta.strategy || item.pk);
    const winCn = _labRetestWinCN(meta.window);
    const score = meta.score != null ? (meta.score * 100).toFixed(0) : "-";
    const starBadge = item.substitute ? "🔵" : "⭐️";
    const idxTag = `<span class="lab-idx-tag">${item.index_name}</span>`;
    return `<div class="lab-strategy-card lab-retest-card clickable-card" data-pk="${item.pk}" data-idx="${item.index}" data-cardid="${item.cardid}">` +
      `<div class="lab-card-top">` +
      `<span class="lab-card-name">${starBadge} ${cn} ${idxTag}</span>` +
      `<span class="lab-rank-score">评分 ${score}</span>` +
      `</div>` +
      `<div class="lab-card-trigger">窗口: ${winCn} · 样本: ${meta.n != null ? meta.n : "-"}</div>` +
      `<div class="lab-card-conclusion">收益 ${_labRetestPct(meta.ret)} · 胜率 <span style="color:${_labRetestColor(meta.win)}">${_labRetestPct(meta.win)}</span> · 回撤 <span style="${_labDdColor(meta.dd)}">${_labRetestPct(meta.dd)}</span></div>` +
      `<div class="lab-fusion-pair-hint">📊 点击查看分年/样本外/极端行情 ▸</div>` +
      `</div>`;
  }).join("");
  list.querySelectorAll(".lab-retest-card").forEach((card) => {
    card.onclick = () => {
      // 融合后同一 pk 可跨指数出现,按 card 的 data-idx 取对应指数的 rd 传给弹窗
      const idx = card.dataset.idx;
      const rd = (state.labRetestDataMap && state.labRetestDataMap[idx]) || null;
      _labRetestPairOpenModal(rd, card.dataset.pk);
    };
  });
  // 跳转高亮：从推荐榜"⭐️进入二次测试"/荣誉徽章跳转来时，定位+高亮该配对卡片
  // 消费 state.labRetestHighlight（一次性，可为 pk 或复合 cardid）。key 找不到则静默放弃（不报错）。
  if (state.labRetestHighlight) {
    const key = state.labRetestHighlight;
    state.labRetestHighlight = null;
    if (_labRetestHighlightCard(list, key)) {
      // 转写给右排行榜:右榜随后渲染(_labRetestRankRerender 在本函数之后调用),
      // 其末尾 _labRetestRankFocusHighlight 会消费 _labRetestRankFocusPk,
      // 自动 scrollIntoView + lab-rank-focus 金色高亮(含前20外自动展开),复用现成机制。
      state._labRetestRankFocusPk = key;
    }
  }
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
  const purposeNote = document.createElement("div");
  purposeNote.className = "lab-purpose-note";
  purposeNote.innerHTML = "💡 <b>这板块有什么用</b>：对配对策略做分年/样本外/极端行情三套稳健性检验--防止策略只在某段行情碰巧赚钱(过拟合)，换个时段就失效。<b>怎么解读</b>：分年回测看各年是否都盈利；样本外看未参与调参的区间表现；极端行情看暴跌暴涨时是否扛得住。三套都稳定=策略稳健，某套崩=过拟合风险。";
  leftCol.appendChild(purposeNote);
  leftCol.appendChild(essayWarn);

  // 分类按钮(融合9指数:主候选/替补/全部,代替原9指数选择器。用户不再需要逐个指数点击找有数据的)
  if (!state.labRetestZone) state.labRetestZone = "star";
  const zoneBar = document.createElement("div");
  zoneBar.className = "lab-zone-tabs";
  LAB_RETEST_ZONES.forEach((z) => {
    const btn = document.createElement("button");
    btn.className = "lab-zone-tab" + (state.labRetestZone === z.key ? " active" : "");
    btn.textContent = z.label;
    btn.onclick = () => {
      if (state.labRetestZone === z.key) return;
      state.labRetestZone = z.key;
      zoneBar.querySelectorAll(".lab-zone-tab").forEach((b) => b.classList.toggle("active", b === btn));
      state.labRetestRankShowAll = false;
      _labRetestRenderCards(list, state.labRetestAllPairs || []);
      _labRetestRankRerenderResults(rankSection, state.labRetestAllPairs || [], state.labRetestSimMap || {});
      _applyRetestSearch();
    };
    zoneBar.appendChild(btn);
  });
  leftCol.appendChild(zoneBar);

  // 搜索框（按策略名/条件模糊过滤配对卡片列表，大小写不敏感，照搬单一信号/融合实验左侧搜索）
  const searchWrap = document.createElement("div");
  searchWrap.className = "lab-fusion-search-wrap";
  searchWrap.innerHTML = '<input type="text" class="lab-fusion-search" placeholder="搜索策略名/条件…" autocomplete="off">';
  leftCol.appendChild(searchWrap);

  // 候选配对卡片列表
  const list = document.createElement("div");
  list.className = "lab-strategy-list lab-retest-list";
  list.innerHTML = '<div class="lab-rank-loading">⏳ 加载二次测试数据中…</div>';
  leftCol.appendChild(list);

  // 搜索框事件：按卡片可见文本模糊过滤（大小写不敏感，匹配策略名/窗口/收益胜率回撤等条件）
  const searchInput = searchWrap.querySelector(".lab-fusion-search");
  const _applyRetestSearch = () => {
    const q = searchInput.value.trim().toLowerCase();
    const cards = list.querySelectorAll(".lab-strategy-card");
    cards.forEach((card) => {
      if (!q) { card.style.display = ""; return; }
      card.style.display = card.textContent.toLowerCase().includes(q) ? "" : "none";
    });
  };
  searchInput.addEventListener("input", _applyRetestSearch);

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
  state._labRetestRankSection = rankSection; // 供荣誉徽章同指数切窗口时直接重渲染右榜

  wrapper.appendChild(leftCol);
  wrapper.appendChild(rightCol);
  content.appendChild(wrapper);

  // 加载 + 渲染（左卡片 + 右榜）：Promise.all 聚合9个 lab_retest_{index}.json + 9个 simData
  const _load = async () => {
    const [retestList, simList] = await Promise.all([
      Promise.all(LAB_SIM_INDEXES.map((x) => fetchLabRetestData(x.id))),
      Promise.all(LAB_SIM_INDEXES.map((x) => fetchLabSimData(x.id))),
    ]);
    await fetchLabRetestHonors(); // 荣誉共享标注表(全局单文件，首次加载后缓存)
    // simMap: { index_id -> simData }，8维整体4维按 pair 所属指数取对应 simData stats
    const simMap = {};
    LAB_SIM_INDEXES.forEach((x, i) => { simMap[x.id] = simList[i]; });
    state.labRetestSimMap = simMap;
    // 聚合 allPairs: 合并9个 rd.pairs，每个 pair 补 index/index_name(指数在 rd 顶层,pair 内无此字段)
    // 复合键 cardid = index::pk (pk 跨指数重复,19/30 个策略对在多指数出现,须用复合键区分)
    const allPairs = [];
    retestList.forEach((rd) => {
      if (!rd || !rd.pairs) return;
      const index = rd.index_id;
      const index_name = rd.index_name || _labIdxName(index);
      Object.keys(rd.pairs).forEach((pk) => {
        const pd = rd.pairs[pk];
        allPairs.push({
          pk, pd, index, index_name,
          cardid: index + "::" + pk,
          substitute: !!pd.substitute,
          reason: pd.reason || "",
        });
      });
    });
    // 跨指数按 pair_meta.score 降序(主候选在前,替补在后;同分按 cardid 字母序稳定排序)
    allPairs.sort((a, b) => {
      const sa = (a.pd.pair_meta && a.pd.pair_meta.score != null) ? a.pd.pair_meta.score : -1;
      const sb = (b.pd.pair_meta && b.pd.pair_meta.score != null) ? b.pd.pair_meta.score : -1;
      if (sb !== sa) return sb - sa;
      return a.cardid < b.cardid ? -1 : 1;
    });
    state.labRetestAllPairs = allPairs;
    _labRetestRenderCards(list, allPairs);
    _labRetestRankRerender(rankSection, allPairs, simMap);
    _applyRetestSearch(); // 重渲染卡片后，重新应用搜索过滤（保留搜索状态）
  };
  _load();
}

// === 二次测试配对弹窗（上半=整体回测详情照抄单一信号实验，下半=三切片强化）===
// 用户原话："单一测试里有的功能你都要带过来。你二次测试是优化，不是舍弃原有的判定标准，是在此之上的强化"
function _labRetestPairOpenModal(rd, pk, mode) {
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
    mode: mode || "full_in",      // 排行榜定额10%行点击默认定额，卡片/缺省默认全仓
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
  const idx = (m.rd && m.rd.index_id) || (state.labSimIndex || "sh");
  // loading 骨架
  overlay.innerHTML = `<div class="lab-signal-modal">` +
    `<div class="lab-signal-modal-head">` +
    `<span class="lab-signal-modal-title">🔬 ${cn} · ${winCn} · 评分 ${score}${_labHelpIcon("score")} · ${_labIdxName(idx)}</span>` +
    `<button type="button" class="lab-rank-modal-close" aria-label="关闭">✕</button>` +
    `</div>` +
    `<div class="lab-signal-modal-body"><div class="loading">加载回测数据…</div></div></div>`;
  overlay.querySelector(".lab-rank-modal-close").onclick = _labRetestPairCloseModal;

  // 加载单信号 stats simData（含融合候选 91 组，per-index 缓存；retest 候选是其子集）
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
    // 用法说明（点4）：提示用户可切换窗口与模式查看不同条件战绩
    const switchHint = '<div class="lab-retest-modal-switch-hint">💡 可切换时间窗口和买卖模式，查看该策略在不同条件下的战绩</div>';
    // 二次测试三切片（点5）：按当前买卖模式选数据源(full_in=top-level, fixed_10k=pd.fixed_10k)，注入净值曲线与交易记录之间
    const sliceData = mode === "fixed_10k" ? (pd && pd.fixed_10k ? pd.fixed_10k : pd) : pd;
    const slicesHTML = sliceData ? _labRetestPairSlicesHTML(sliceData) : "";
    detailHTML = modeBar + switchHint + _labSimModeBlock(mode, winData, initCapital, m.page, m.open, null, null, slicesHTML, idx);
  }

  const bodyHTML =
    `<div class="lab-retest-modal-section">` +
    `<div class="lab-retest-modal-section-title">📊 整体回测详情 · 买${buyName} × 卖${sellName} · ${modeName}（${winLabel}） · ${_labIdxName(idx)}</div>` +
    `<div class="lab-retest-modal-hint">4数字结论 + 净值曲线 + 二次测试三切片（分年/样本外/极端行情）+ 交易记录，原有判定标准与稳健性强化一并展示。</div>` +
    detailHTML +
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

// === 融合候选配对回测弹窗（buy_sell/buy_buy/sell_sell 三类查 lab_sim_{index}_fusion_stats.json；硬编码独立策略展示文本）===
// 指数选择器分组（融合候选为A股策略，仅列A股宽基）
const LAB_FUSION_PAIR_INDEX_GROUPS = [
  ["A股宽基", ["sh", "sz", "cyb", "csi500", "csi1000", "kc50", "hs300", "sz50", "bj50"]],
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
    mode: "full_in",
    win: "y5",
    page: 0,
    open: true,
  };
  _labFusionPairModalRender(overlay);
  overlay.classList.add("show");
  document.body.style.overflow = "hidden";
  overlay.onclick = (e) => { if (e.target === overlay) _labFusionPairCloseModal(); };
}

function _labFusionPairCloseModal() {
  const overlay = document.getElementById("labFusionPairOverlay");
  if (overlay) {
    // 释放弹窗内 echarts 实例（核心策略图表+净值曲线），避免内存泄漏
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
  state.labFusionPairModal = null;
  state._labSimRerender = null;
  state._labChartRerender = null;
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
    ? `📊 ${_labStratNameHTML(key, meta.name)} <span class="lab-tag ${tag.cls}">${tag.label}</span>`
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

// 硬编码独立融合策略详情（Bug-A：6个无 _pairType 的策略，展示其回测结论文本，不走配对回测）
function _labFusionHardcodedHTML(meta) {
  const tag = LAB_STATUS_TAGS[meta.status] || LAB_STATUS_TAGS.dev;
  const fields = [
    ["组成条件", meta.conditions && meta.conditions.join("、")],
    ["触发条件", meta.trigger],
    ["回测结论", meta.report],
    ["理论依据", meta.theory],
    ["适用场景", meta.scenario],
    ["备注", meta.note],
  ];
  const rows = fields.filter(([, v]) => v).map(([k, v]) =>
    `<div class="lab-fusion-detail-row"><span class="lab-fusion-detail-label">${k}</span><span class="lab-fusion-detail-value">${v}</span></div>`
  ).join("");
  return `<div class="lab-fusion-hardcoded">` +
    `<div class="lab-fusion-detail-tag"><span class="lab-tag ${tag.cls}">${tag.label}</span></div>` +
    (meta.conclusion ? `<div class="lab-fusion-detail-conclusion">${meta.conclusion}</div>` : "") +
    rows +
    `</div>`;
}

async function _labFusionPairModalRender(overlay) {
  const m = state.labFusionPairModal;
  if (!m) return;
  const meta = m.meta;

  const mode = m.mode || "full_in";
  const win = m.win || "y5";
  const modeName = mode === "full_in" ? "全仓" : "定额（10%）";
  const winLabel = (LAB_WIN_DEFS.find((w) => w.k === win) || {}).l || "";

  // 确定 pairId / 标题 / 说明文案
  // - 6硬编码（无 _pairType，有 _fusionKey）：pairId=F_key，走真实融合回测数据
  // - 配对候选（有 _pairType）：pairId=_buyKey|_sellKey
  // - 兜底（无 _pairType 无 _fusionKey）：仅展示文案
  let pairId, titleText, descHTML;
  const isHardcoded = !meta._pairType && meta._fusionKey;
  if (isHardcoded) {
    pairId = meta._fusionKey;
    titleText = `🔬 ${meta.name || "融合策略"} · ${modeName}（${winLabel}） · ${_labIdxName(m.index)}`;
    descHTML = _labFusionHardcodedHTML(meta);
  } else if (meta._pairType) {
    // 配对候选（buy_sell / buy_buy / sell_sell）：标题按 pair_type 区分
    const pairType = meta._pairType;
    const name1 = (LAB_STRATEGIES[meta._buyKey] || {}).name || meta._buyKey;
    const name2 = (LAB_STRATEGIES[meta._sellKey] || {}).name || meta._sellKey;
    const isBuySell = pairType === "buy_sell";
    const typeLabel = isBuySell ? "配对回测" : (pairType === "buy_buy" ? "双买共振" : "双卖共振");
    const titlePair = isBuySell ? `买${name1} × 卖${name2}` : `${name1} + ${name2}`;
    const titleIcon = isBuySell ? "📊" : "🔬";
    pairId = meta._buyKey + "|" + meta._sellKey;
    titleText = `${titleIcon} ${typeLabel} · ${titlePair} · ${modeName}（${winLabel}） · ${_labIdxName(m.index)}`;
    // 融合策略说明（组成条件/触发/结论），补齐成分策略 theory/scenario/note/report（折叠）
    const condHTML = (meta.conditions && meta.conditions.length)
      ? `<div class="lab-fusion-detail-row"><span class="lab-fusion-detail-label">组成条件</span><span class="lab-fusion-detail-value">${meta.conditions.join("、")}</span></div>`
      : "";
    // 从成分策略 LAB_STRATEGIES 补 theory/scenario/note/report（91候选自身无这些字段）
    const _comp1 = LAB_STRATEGIES[meta._buyKey] || {};
    const _comp2 = LAB_STRATEGIES[meta._sellKey] || {};
    const _compFields = [
      ["理论依据", [_comp1.theory, _comp2.theory].filter(Boolean).join(" / ")],
      ["适用场景", [_comp1.scenario, _comp2.scenario].filter(Boolean).join(" / ")],
      ["注意事项", [_comp1.note, _comp2.note].filter(Boolean).join(" / ")],
      ["回测结论", [_comp1.report, _comp2.report].filter(Boolean).join(" / ")],
    ];
    const _compRows = _compFields.filter(([, v]) => v).map(([k, v]) =>
      `<div class="lab-fusion-detail-row"><span class="lab-fusion-detail-label">${k}</span><span class="lab-fusion-detail-value">${v}</span></div>`
    ).join("");
    const compDetailHTML = _compRows ? `<details class="lab-fusion-comp-details"><summary>📋 成分策略详细说明</summary>${_compRows}</details>` : "";
    descHTML = `<div class="lab-fusion-hardcoded">` +
      (meta.conclusion ? `<div class="lab-fusion-detail-conclusion">${meta.conclusion}</div>` : "") +
      condHTML +
      (meta.trigger ? `<div class="lab-fusion-detail-row"><span class="lab-fusion-detail-label">触发条件</span><span class="lab-fusion-detail-value">${meta.trigger}</span></div>` : "") +
      compDetailHTML +
      `</div>`;
  } else {
    // 兜底：无 _pairType 无 _fusionKey，仅展示融合策略说明文案
    const headHTML = `<div class="lab-signal-modal-head">` +
      `<span class="lab-signal-modal-title">🔬 ${meta.name || "融合策略"} · ${_labIdxName(m.index)}</span>` +
      `<button type="button" class="lab-rank-modal-close" aria-label="关闭">✕</button>` +
      `</div>`;
    overlay.innerHTML = `<div class="lab-signal-modal">` + headHTML +
      `<div class="lab-signal-modal-body">${_labFusionHardcodedHTML(meta)}</div></div>`;
    overlay.querySelector(".lab-rank-modal-close").onclick = _labFusionPairCloseModal;
    return;
  }

  // 局部更新对齐单一信号弹窗：切换买卖模式/时间窗口/指数时不重建弹窗骨架，
  // 仅更新标题+内容区，保留旧内容直到新数据就绪，保持滚动位置（modal 元素不重建=>scrollTop 不归零）
  const existingModal = overlay.querySelector(".lab-signal-modal");
  if (existingModal) {
    // re-render：仅更新标题文本，body 旧内容保留到 await 后再替换（避免骨架闪烁+跳顶部）
    const titleEl = overlay.querySelector(".lab-signal-modal-title");
    if (titleEl) titleEl.innerHTML = titleText;
  } else {
    // 首次打开：渲染 loading 骨架（标题在 sticky head，关闭 X）
    overlay.innerHTML = `<div class="lab-signal-modal">` +
      `<div class="lab-signal-modal-head">` +
      `<span class="lab-signal-modal-title">${titleText}</span>` +
      `<button type="button" class="lab-rank-modal-close" aria-label="关闭">✕</button>` +
      `</div>` +
      `<div class="lab-signal-modal-body"><div class="loading">加载回测数据…</div></div></div>`;
    overlay.querySelector(".lab-rank-modal-close").onclick = _labFusionPairCloseModal;
  }

  // 信号图/多周期矩阵的 base 策略 key（6硬编码用 FUSION_CHART_BASE 映射，91候选用 _buyKey）
  const chartBaseKey = isHardcoded
    ? (FUSION_CHART_BASE[meta._fusionKey] || null)
    : (meta._buyKey || meta._sellKey || null);
  const chartBaseName = chartBaseKey ? ((LAB_STRATEGIES[chartBaseKey] || {}).name || chartBaseKey) : "";

  // generation counter：防止 stale async 渲染覆盖最新
  m._gen = (m._gen || 0) + 1;
  const myGen = m._gen;

  // 并行加载：融合回测数据 + 信号图指数数据 + 融合矩阵数据
  const simDataP = fetchLabFusionSimData(m.index);
  const chartDataP = fetchJSON(`https://ssd.fx8.store/index/${m.index}-all.json`).catch(() => null);
  const fusionMatrixP = fetchLabFusionMatrixData(m.index).catch(() => null);
  const [simData, chartData, fusionMatrixData] = await Promise.all([simDataP, chartDataP, fusionMatrixP]);
  if (m._gen !== myGen) return; // stale render

  // 异步加载 full 数据（trades/equity_curve），加载完成后重渲染显示交易记录
  // 对齐单一弹窗 renderSimCard 的分阶段加载：stats 秒开（显收益率）→ full 到账后补净值曲线/交易记录
  if (!_labSimFusionFullLoaded(m.index)) {
    fetchLabFusionSimFullData(m.index).then(() => {
      if (m._gen === myGen) _labFusionPairModalRender(overlay);
    }).catch(() => {});
  }

  // Bug-C：加载 fusion_stats（91对 + 6硬编码），非单信号 stats（64对）
  const pair = simData && simData.pairs ? simData.pairs[pairId] : null;
  const initCapital = (simData && simData.initial_capital) || 100000;

  // 时间窗口（对齐单一信号弹窗：指数选择上方显示时间窗口切换条，切换重渲染）
  const winBar = `<div class="lab-win-bar"><span class="lab-win-bar-label">时间窗口</span>${_labModalWinTabsHTML(win)}<span class="lab-win-bar-cur">${winLabel}</span></div>`;

  // 指数选择器（融合候选为A股策略，可切指数查看同配对不同指数回测）
  // 对齐单一信号弹窗：用按钮组(.lab-idx-tab)而非下拉框，与时间窗口/买卖模式切换交互一致
  const idxBtns = LAB_FUSION_PAIR_INDEX_GROUPS.flatMap(([gname, ids]) => ids)
    .map((id) => `<button type="button" class="lab-idx-tab${id === m.index ? " active" : ""}" data-fidx="${id}">${_INDEX_NAME_MAP[id] || id}</button>`).join("");
  const filterHTML = `<div class="lab-win-bar"><span class="lab-win-bar-label">选择指数</span><div class="lab-win-tabs">${idxBtns}</div></div>`;

  // 查看买卖信号按钮：buy/sell key 按 pair_type 推导（buy_buy/sell_sell 用 ref_side 补反面）
  const fmInfo = simData && simData.fusion_meta ? simData.fusion_meta[pairId] : null;
  const refSide = fmInfo ? fmInfo.ref_side : null;
  let sigBuyKey = null, sigSellKey = null;
  if (isHardcoded) {
    const baseKey = FUSION_CHART_BASE[meta._fusionKey];
    if (meta.side === "buy") { sigBuyKey = baseKey; sigSellKey = refSide; }
    else { sigBuyKey = refSide; sigSellKey = baseKey; }
  } else {
    const pt = meta._pairType;
    if (pt === "buy_sell") { sigBuyKey = meta._buyKey; sigSellKey = meta._sellKey; }
    else if (pt === "buy_buy") { sigBuyKey = meta._buyKey; sigSellKey = refSide; }
    else if (pt === "sell_sell") { sigBuyKey = refSide; sigSellKey = meta._buyKey; }
  }
  const signalBtnHTML = (sigBuyKey && sigSellKey)
    ? `<div class="lab-sim-signal-btn-wrap"><button type="button" class="lab-sim-signal-btn" data-buy="${sigBuyKey}" data-sell="${sigSellKey}">📊 查看买卖信号</button></div>`
    : "";

  // 信号图：91候选=双图上下排列(策略A上图+策略B下图，各自独立 echarts)；6硬编码=同时满足共振单图；失败回退 chartBaseKey 代理
  let chartSectionHTML = "";
  let chartCfg = null, chartSliced = null;             // 单图（6硬编码/代理）
  let chartCfgA = null, chartCfgB = null;               // 双图（91候选 策略A/B）
  let chartSlicedA = null, chartSlicedB = null;
  let isDualChart = false;
  if (chartData && chartData.ohlc && chartData.ohlc.length) {
    const idxName = _INDEX_NAME_MAP[m.index] || m.index;
    const cWinLabel = (LAB_WIN_DEFS.find((w) => w.k === win) || {}).l || "";
    if (!isHardcoded && meta._pairType) {
      // 91候选：双图上下排列，各自独立 echarts 实例，共享当前指数+窗口时间范围
      // 复用 _labBuildChartConfig/_labChartSlice/renderLabChartEx（均纯函数，双图各调一次传不同 key+容器）
      const k1 = meta._buyKey, k2 = meta._sellKey;
      const s1Meta = LAB_STRATEGIES[k1] || {}, s2Meta = LAB_STRATEGIES[k2] || {};
      const name1 = s1Meta.name || k1, name2 = s2Meta.name || k2;
      const side1 = s1Meta.side, side2 = s2Meta.side;
      // 买红卖绿（对齐 A 股习惯 + 现有融合合并图配色 BUY_C/SELL_C）
      const color1 = side1 === 'sell' ? '#2e7d32' : '#c92a2a';
      const color2 = side2 === 'sell' ? '#2e7d32' : '#c92a2a';
      const statLabel1 = side1 === 'buy' ? '买点' : '卖点';
      const statLabel2 = side2 === 'buy' ? '买点' : '卖点';
      chartCfgA = LAB_CHART_KEYS[k1] ? _labBuildChartConfig(k1, chartData.ohlc, idxName) : null;
      chartCfgB = LAB_CHART_KEYS[k2] ? _labBuildChartConfig(k2, chartData.ohlc, idxName) : null;
      if (chartCfgA) chartSlicedA = _labChartSlice(chartData.ohlc, chartCfgA.indicators, chartCfgA.signals, win);
      if (chartCfgB) chartSlicedB = _labChartSlice(chartData.ohlc, chartCfgB.indicators, chartCfgB.signals, win);
      isDualChart = true;
      const cnt1 = chartSlicedA ? chartSlicedA.signals.length : 0;
      const cnt2 = chartSlicedB ? chartSlicedB.signals.length : 0;
      // 单子图 HTML（内联 style，不新增 CSS class；占位复用现有 .lab-fusion-chart-ph 样式）
      const subHTML = (nm, side, color, cnt, statLabel, phCls, hasChart) =>
        '<div style="margin-top:14px;">' +
        '<div style="font-size:13px;font-weight:600;margin-bottom:4px;display:flex;align-items:center;gap:6px;color:var(--text-1);">' +
        '<i style="display:inline-block;width:10px;height:10px;border-radius:2px;background:' + color + '"></i>' +
        nm + '（' + (side === 'buy' ? '买' : '卖') + '）</div>' +
        (hasChart
          ? '<div class="lab-fusion-chart-ph ' + phCls + '"><div class="loading">加载中…</div></div>' +
            '<div class="lab-signal-stat">共触发 <b style="color:' + color + '">' + cnt + '</b> 个' + statLabel + '（' + cWinLabel + '）</div>'
          : '<div class="empty-note">该策略暂无图表实现</div>') +
        '</div>';
      chartSectionHTML = '<div class="chart-card lab-chart-section">' +
        '<h3>📈 信号图（成分策略分图）</h3>' +
        '<div class="lab-fusion-chart-legend"><span><i style="background:#c92a2a"></i>买</span><span><i style="background:#2e7d32"></i>卖</span></div>' +
        subHTML(name1, side1, color1, cnt1, statLabel1, 'lab-fusion-chart-ph-a', !!chartCfgA) +
        subHTML(name2, side2, color2, cnt2, statLabel2, 'lab-fusion-chart-ph-b', !!chartCfgB) +
        '</div>';
    } else {
      // 6硬编码：同时满足共振单图 / chartBaseKey 代理（保持原逻辑不回归）
      const components = fmInfo ? fmInfo.components : null;
      chartCfg = _labBuildFusionChartConfig(meta, chartData.ohlc, idxName, isHardcoded, components);
      let chartTitleSuffix = "（同时满足共振）";
      if (!chartCfg && chartBaseKey && LAB_CHART_KEYS[chartBaseKey]) {
        chartCfg = _labBuildChartConfig(chartBaseKey, chartData.ohlc, idxName);
        chartTitleSuffix = "（基础策略「" + chartBaseName + "」代理）";
      }
      if (chartCfg) {
        chartSliced = _labChartSlice(chartData.ohlc, chartCfg.indicators, chartCfg.signals, win);
        const statHTML = '<div class="lab-signal-stat">共触发 <b>' + chartSliced.signals.length + '</b> 个' + chartCfg.statLabel + '（' + cWinLabel + '）</div>';
        chartSectionHTML = '<div class="chart-card lab-chart-section">' +
          '<h3>📈 信号图' + chartTitleSuffix + '</h3>' +
          '<div class="lab-fusion-chart-ph"><div class="loading">加载中…</div></div>' +
          statHTML +
          '</div>';
      } else {
        chartSectionHTML = '<div class="chart-card lab-chart-section"><h3>📈 信号图</h3><div class="empty-note">该融合策略暂不支持信号图</div></div>';
      }
    }
  } else {
    chartSectionHTML = '<div class="chart-card lab-chart-section"><h3>📈 信号图</h3><div class="empty-note">该指数暂无数据</div></div>';
  }
  // 指标释义折叠（对齐单一信号 renderLabDetail @2007：合并两成分策略的指标白话释义，点击展开）
  let indExplainHTML = "";
  if (!isHardcoded && meta._pairType) {
    const _ik1 = LAB_STRATEGY_INDICATORS[meta._buyKey] || [];
    const _ik2 = LAB_STRATEGY_INDICATORS[meta._sellKey] || [];
    const _mergedKeys = [];
    _ik1.concat(_ik2).forEach((k) => { if (_mergedKeys.indexOf(k) < 0) _mergedKeys.push(k); });
    const _indItems = _mergedKeys.map((k) => LAB_INDICATOR_PLAIN[k]).filter(Boolean);
    if (_indItems.length) {
      indExplainHTML = '<div class="chart-card"><details class="indicator-explain"><summary>📖 指标释义（这些指标怎么看？）</summary>' +
        '<div class="indicator-explain-body">' +
        _indItems.map((it) => `<div><b title="${it.en || ''}">${it.name}</b>：${it.plain}</div>`).join("") +
        '</div></details></div>';
    }
  }

  // 多周期回测矩阵（融合策略自己的矩阵，lab_backtest_fusion_{idx}.json，97候选5窗口×4horizon）
  let matrixSectionHTML = "";
  if (fusionMatrixData) {
    const mStratData = fusionMatrixData.strategies ? fusionMatrixData.strategies[pairId] : null;
    const mGenAt = fusionMatrixData.generated_at || "";
    state.labSimWindow = win; // 矩阵行高亮用
    const mTitleName = meta.name || pairId;
    matrixSectionHTML = '<div class="chart-card lab-matrix-card">' +
      '<h3>📊 多周期回测矩阵（融合策略）</h3>' +
      '<div class="lab-matrix-legend"><b>怎么看这张表：</b>' +
      '<span><b>胜率</b>=信号后上涨(买)/下跌(卖)概率</span>' +
      '<span><b>平均收益</b>=每次操作平均赚多少(含亏的)</span>' +
      '<span><b>盈亏比</b>=平均赚÷平均亏，&gt;1才划算</span>' +
      '<span><b>样本</b>=测试了多少次信号</span></div>' +
      '<div class="lab-matrix-tip">⚠ 以上为单次操作平均收益，非连续复利；信号触发不定期，不可直接相乘。</div>' +
      '<div class="lab-matrix-wrap">' + renderLabMatrix(mStratData) + '</div>' +
      '<div class="lab-matrix-foot"><div class="lab-matrix-source">数据来源：融合策略深度回测（' + mTitleName + '，基于历史数据验证' + (mGenAt ? '，重跑于 ' + mGenAt : '') + '）</div>' +
      '<div class="lab-matrix-legend-color"><span class="lab-matrix-good">红=好</span><span class="lab-matrix-warn">黄=一般</span><span class="lab-matrix-bad">绿=差</span></div></div>' +
      '</div>';
  }

  // 自白黄块（对齐单一信号弹窗）
  const essayHTML = '<div class="lab-warning-essay">' + _labWarningEssayHTML(meta.status) + '</div>';

  let bodyHTML;
  if (!pair) {
    bodyHTML = essayHTML + descHTML + winBar + filterHTML + chartSectionHTML + indExplainHTML + matrixSectionHTML +
      `<div class="lab-rank-modal-empty">暂无回测数据<br>` +
      `<span style="font-size:12px">融合策略 ${pairId} 在 ${_INDEX_NAME_MAP[m.index] || m.index} 未找到回测结果。</span></div>`;
  } else {
    // modeBar/switchHint（winBar 已提到指数选择上方，对齐单一信号弹窗）
    const modeBar = '<div class="lab-win-bar"><span class="lab-win-bar-label">买卖模式</span>' +
      '<div class="lab-win-tabs">' +
      `<button type="button" class="lab-win-tab${mode === "full_in" ? " active" : ""}" data-mode="full_in">全仓</button>` +
      `<button type="button" class="lab-win-tab${mode === "fixed_10k" ? " active" : ""}" data-mode="fixed_10k">定额（10%）</button>` +
      '</div></div>';
    const switchHint = '<div class="lab-retest-modal-switch-hint">💡 可切换时间窗口和买卖模式，查看该策略在不同条件下的战绩</div>';

    // 6硬编码：F_xxx × 8 partner 配对卡片列表 + 点卡片切换（m.pair 局部管理，防与单一弹窗全局state冲突）
    // 91候选：本身是配对结果，无配对切换，直接用 _labSimModeBlock
    let detailHTML;
    const fStrat = simData.strategies && simData.strategies[pairId] ? simData.strategies[pairId] : null;
    const partners = (fStrat && fStrat.partners) || [];
    const fSide = fStrat ? fStrat.side : (isHardcoded ? meta.side : (meta._pairType === "sell_sell" ? "sell" : "buy"));

    if (isHardcoded && partners.length > 1) {
      // 配对卡片列表
      if (!m.pair || partners.indexOf(m.pair) < 0) m.pair = partners[0];
      const pairSideLabel = fSide === "buy" ? "卖点" : "买点";
      const pairCards = partners.map((pk) => {
        const buyKey = fSide === "buy" ? pairId : pk;
        const sellKey = fSide === "buy" ? pk : pairId;
        const pData = _labGetPair(simData, buyKey, sellKey);
        const wd = _labPairWinData(pData, mode, win, simData);
        const st = wd && wd.stats;
        let lvl = "warn";
        if (st) {
          const retLv = _labLvl(st.total_ret, { good: 5, bad: -5 });
          const winLv = _labLvl(st.win_rate, { good: 55, bad: 45 });
          const goods = [retLv, winLv].filter((x) => x === "good").length;
          const bads = [retLv, winLv].filter((x) => x === "bad").length;
          lvl = goods >= 2 ? "good" : bads >= 2 ? "bad" : "warn";
        }
        const activeCls = pk === m.pair ? " active" : "";
        const pName = (LAB_STRATEGIES[pk] && LAB_STRATEGIES[pk].name) || pk;
        const retStr = st ? `${st.total_ret > 0 ? "+" : ""}${st.total_ret}%` : "-";
        const retCls = st ? `pc-lvl-${_labLvl(st.total_ret, { good: 5, bad: -5 })}` : "";
        const winStr = st ? `胜${st.win_rate}%` : "";
        const winCls = st ? `pc-lvl-${_labLvl(st.win_rate, { good: 55, bad: 45 })}` : "";
        const nStr = st ? `n=${st.n_trades}` : "";
        return `<button type="button" class="lab-sim-pair-card lab-matrix-${lvl}${activeCls}" data-fpair="${pk}" data-mode="${mode}">` +
          `<span class="pc-name" data-tip="${pName}">${pName}</span>` +
          (st ? `<span class="pc-ret ${retCls}">${retStr}</span>` +
           `<span class="pc-meta"><span class="pc-win ${winCls}">${winStr}</span><span class="pc-n">${nStr}</span></span>` : "") +
          `</button>`;
      }).join("");
      const pairListHTML = `<div class="lab-sim-pair-section"><div class="lab-sim-pair-label">配对${pairSideLabel}（点卡片切换 · 红好/绿差）</div><div class="lab-sim-pair-list">${pairCards}</div></div>`;
      // 当前配对详情
      const curBuyKey = fSide === "buy" ? pairId : m.pair;
      const curSellKey = fSide === "buy" ? m.pair : pairId;
      const curPairData = _labGetPair(simData, curBuyKey, curSellKey);
      const winData = _labPairWinData(curPairData, mode, win, simData);
      const curPairLabel = ((LAB_STRATEGIES[curBuyKey] || {}).name || curBuyKey) + " × " + ((LAB_STRATEGIES[curSellKey] || {}).name || curSellKey);
      if (!winData || !winData.stats) {
        detailHTML = modeBar + switchHint + pairListHTML + '<div class="lab-sim-empty">该配对无交易数据</div>';
      } else {
        const trades = winData.trades || [];
        const totalPages = Math.max(1, Math.ceil(trades.length / 20));
        if (m.page > totalPages - 1) m.page = totalPages - 1;
        if (m.page < 0) m.page = 0;
        detailHTML = modeBar + switchHint + pairListHTML + _labSimModeBlock(mode, winData, initCapital, m.page, m.open, signalBtnHTML, curPairLabel, null, m.index);
      }
    } else {
      // 91候选：本身是配对结果，无配对切换
      const winData = _labPairWinData(pair, mode, win, simData);
      if (!winData || !winData.stats) {
        detailHTML = modeBar + switchHint + `<div class="lab-rank-modal-empty">该融合策略在 ${_INDEX_NAME_MAP[m.index] || m.index} 无交易数据</div>`;
      } else {
        const trades = winData.trades || [];
        const totalPages = Math.max(1, Math.ceil(trades.length / 20));
        if (m.page > totalPages - 1) m.page = totalPages - 1;
        if (m.page < 0) m.page = 0;
        detailHTML = modeBar + switchHint + _labSimModeBlock(mode, winData, initCapital, m.page, m.open, signalBtnHTML, null, null, m.index);
      }
    }
    bodyHTML = essayHTML + descHTML + winBar + filterHTML + chartSectionHTML + indExplainHTML + matrixSectionHTML + detailHTML;
  }

  // 释放上一次渲染的 echarts 实例（re-render 时避免内存泄漏；放在 await 之后，旧图表在数据加载期间保持可见）
  for (let i = charts.length - 1; i >= 0; i--) {
    try {
      const dom = charts[i].getDom && charts[i].getDom();
      if (dom && overlay.contains(dom)) { charts[i].dispose(); charts.splice(i, 1); }
    } catch (e) {}
  }
  const body = overlay.querySelector(".lab-signal-modal-body");
  if (body) {
    body.innerHTML = bodyHTML;
    // 渲染信号图 echarts（数据已并行加载完毕，同步渲染进占位容器）
    const chartPh = body.querySelector(".lab-fusion-chart-ph");
    if (chartPh && chartCfg && chartSliced) {
      chartPh.innerHTML = "";
      renderLabChartEx(chartCfg.chartTitle, chartSliced.ohlc, chartSliced.indicators, chartSliced.signals, chartPh, charts, chartCfg.signalLabel, chartCfg.signalColor);
    }
    // 91候选双图：上下两图各自独立 echarts 实例（策略A + 策略B），signalColor 按 side 买红卖绿
    // 实例 push 进全局 charts 数组，re-render 时由上方 dispose 循环自动释放（防泄漏）
    if (isDualChart) {
      const _k1 = meta._buyKey, _k2 = meta._sellKey;
      const _s1 = LAB_STRATEGIES[_k1] || {}, _s2 = LAB_STRATEGIES[_k2] || {};
      const _c1 = _s1.side === 'sell' ? '#2e7d32' : '#c92a2a';
      const _c2 = _s2.side === 'sell' ? '#2e7d32' : '#c92a2a';
      const phA = body.querySelector(".lab-fusion-chart-ph-a");
      const phB = body.querySelector(".lab-fusion-chart-ph-b");
      if (phA && chartCfgA && chartSlicedA) {
        phA.innerHTML = "";
        renderLabChartEx(chartCfgA.chartTitle, chartSlicedA.ohlc, chartSlicedA.indicators, chartSlicedA.signals, phA, charts, chartCfgA.signalLabel, _c1);
      }
      if (phB && chartCfgB && chartSlicedB) {
        phB.innerHTML = "";
        renderLabChartEx(chartCfgB.chartTitle, chartSlicedB.ohlc, chartSlicedB.indicators, chartSlicedB.signals, phB, charts, chartCfgB.signalLabel, _c2);
      }
    }
    // 矩阵行高亮
    _labUpdateMatrixRowHighlight();
    // 指数切换（按钮组，对齐单一信号弹窗）
    body.querySelectorAll(".lab-idx-tab[data-fidx]").forEach((btn) => {
      btn.onclick = () => { m.index = btn.dataset.fidx; m.page = 0; _labFusionPairModalRender(overlay); };
    });
    // 三区一致：模式/窗口切换（切换重置分页）
    overlay.querySelectorAll(".lab-win-tab[data-mode]").forEach((btn) => {
      btn.onclick = () => { m.mode = btn.dataset.mode; m.page = 0; _labFusionPairModalRender(overlay); };
    });
    overlay.querySelectorAll(".lab-win-tab[data-win]").forEach((btn) => {
      btn.onclick = () => { m.win = btn.dataset.win; m.page = 0; _labFusionPairModalRender(overlay); };
    });
    // 6硬编码配对卡片切换（m.pair 局部管理，防与单一弹窗全局state冲突）
    overlay.querySelectorAll(".lab-sim-pair-card[data-fpair]").forEach((btn) => {
      btn.onclick = () => { m.pair = btn.dataset.fpair; m.page = 0; _labFusionPairModalRender(overlay); };
    });
    // 交易记录折叠/展开 + 分页
    const hdr = overlay.querySelector(".lab-sim-trades-header");
    if (hdr) hdr.onclick = () => { m.open = !m.open; _labFusionPairModalRender(overlay); };
    const prev = overlay.querySelector(".lab-sim-prev");
    if (prev) prev.onclick = () => { if (m.page > 0) { m.page--; _labFusionPairModalRender(overlay); } };
    const next = overlay.querySelector(".lab-sim-next");
    if (next && !next.disabled) next.onclick = () => { m.page++; _labFusionPairModalRender(overlay); };
    // 查看买卖信号按钮（融合弹窗传当前 m.index，避免用旧 state.labSimIdx 串台）
    body.querySelectorAll(".lab-sim-signal-btn").forEach((btn) => {
      btn.onclick = () => _labSignalOpenModal(btn.dataset.buy, btn.dataset.sell, m.index);
    });
  }

  // full 数据(trades/equity_curve)按需加载，加载完重渲染（净值曲线/交易记录显示 loading 占位直到加载完）
  if (simData && pair && !_labSimFusionFullLoaded(m.index)) _labFusionEnsureFull(overlay, m.index);
}

// 弹窗内按需加载 fusion full 数据（trades/equity_curve），照抄 _labRetestEnsureFull
async function _labFusionEnsureFull(overlay, idx) {
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
    await fetchLabFusionSimFullData(idx, (received, total) => {
      setProg(total > 0 ? Math.round(received / total * 100) : -1);
    }, controller.signal);
  } finally {
    clearTimeout(slowTimer);
  }
  if (_labSimFusionFullLoaded(idx)) {
    if (state.labFusionPairModal) _labFusionPairModalRender(overlay);
  } else {
    const el = overlay.querySelector(".lab-sim-full-loading");
    if (el) {
      el.innerHTML = `<span>${timedOut ? "⏳ 加载超时" : "⚠ 加载失败"}</span> ` +
        `<button type="button" class="lab-full-retry" style="margin-left:8px;padding:3px 12px;border:1px solid var(--border-strong);border-radius:5px;background:var(--bg-card);color:var(--text-1);font-size:12px;cursor:pointer;">重试</button>`;
      const retryBtn = el.querySelector(".lab-full-retry");
      if (retryBtn) retryBtn.onclick = () => _labFusionEnsureFull(overlay, idx);
    }
  }
}

// === 二次测试扩展方向：信号叠加消融 / 多空对称 / 参数敏感扫描（3方向，全局单文件JSON）===
// 数据源 lab_ablation.json / lab_short_symmetry.json / lab_param_scan.json（static-site/data/ 顶层）
// 与 retest 三件套(分年/样本外/极端行情)互补，属"其余7方向"中的归因/优化类。
// 3 方向数据获取（全局单文件，缓存到 state；web 版 ./data/，static 版 ./data/）
async function fetchLabAblationData() {
  if (state.labAblationData !== undefined) return state.labAblationData;
  try { state.labAblationData = await fetchJSON("./data/lab_ablation.json"); }
  catch (e) { state.labAblationData = null; }
  return state.labAblationData;
}
async function fetchLabSymmetryData() {
  if (state.labSymmetryData !== undefined) return state.labSymmetryData;
  try { state.labSymmetryData = await fetchJSON("./data/lab_short_symmetry.json"); }
  catch (e) { state.labSymmetryData = null; }
  return state.labSymmetryData;
}
async function fetchLabParamScanData() {
  if (state.labParamScanData !== undefined) return state.labParamScanData;
  try { state.labParamScanData = await fetchJSON("./data/lab_param_scan.json"); }
  catch (e) { state.labParamScanData = null; }
  return state.labParamScanData;
}

// 通用指数选择器 bar HTML（接收 index 列表 + 当前选中）
function _labExtIdxBarHTML(idxList, curIdx) {
  return idxList.map((x) =>
    `<button type="button" class="lab-idx-tab${x.id === curIdx ? " active" : ""}" data-idx="${x.id}">${x.name}</button>`
  ).join("");
}

// === 新方向实验通用工具：组件/参数中文名 + 涨跌色（红涨绿跌，复用 --mx-good-fg/--mx-bad-fg 适配3套皮肤）===
// 子组件中文名（策略 key 复用 LAB_STRATEGIES[].name，此处仅补非策略子信号）
const _LAB_COMP_NAME = {
  MA60_bull: "60日均线多头",
  MACD_below_signal: "MACD低于信号线",
  RSI_cross_40: "相对强弱上穿40",
  close_above_bl_2pct: "收盘高于下轨2%",
};
function _labCompLabel(key) {
  if (LAB_FUSION_STRATEGIES[key] && LAB_FUSION_STRATEGIES[key].name) return LAB_FUSION_STRATEGIES[key].name;
  if (LAB_STRATEGIES[key] && LAB_STRATEGIES[key].name) return LAB_STRATEGIES[key].name;
  return _LAB_COMP_NAME[key] || key;
}
// pair_id -> 中文：融合ID优先查LAB_FUSION_STRATEGIES取name（F_D1_S1_MACD等6融合策略）；单一策略查LAB_STRATEGIES；a|b 拆分分别取name
function _labPairLabel(pairId) {
  if (LAB_FUSION_STRATEGIES[pairId] && LAB_FUSION_STRATEGIES[pairId].name) return LAB_FUSION_STRATEGIES[pairId].name;
  if (LAB_STRATEGIES[pairId] && LAB_STRATEGIES[pairId].name) return LAB_STRATEGIES[pairId].name;
  if (pairId && pairId.indexOf("|") >= 0) return pairId.split("|").map(_labCompLabel).join(" ｜ ");
  return _labCompLabel(pairId);
}
// 参数维度名 -> 中文（维度 key 仍用于索引 params，仅展示用中文）
const _LAB_DIM_NAME = {
  rsi_period: "RSI周期",
  threshold: "RSI阈值",
  n: "周期N",
  k: "标准差倍数",
  period: "周期",
};
function _labDimLabel(name) { return _LAB_DIM_NAME[name] || name; }
// 涨跌色（红涨绿跌）：_UP/_DOWN 供内联 style 用 var()；_retEc 供 echarts canvas 用 cssVar() 解析
const _UP = "var(--mx-good-fg)", _DOWN = "var(--mx-bad-fg)"; // 正=红 / 负=绿
const _retFg = (v) => (v >= 0 ? _UP : _DOWN);               // 内联样式用
const _retEc = (v) => (v >= 0 ? cssVar("--mx-good-fg") : cssVar("--mx-bad-fg")); // echarts 用

// === 🧩 信号叠加消融：6硬编码融合 N-1 子集贡献（定位核心贡献组件）===
const _LAB_ABLATION_RULE = "🧩 信号拆解测试（消融分析）：对6硬编码融合策略逐一去掉一个组件(去一组件子集)，对比收益变化定位核心贡献组件。贡献率=完整融合收益-去该组件后收益；正值=该组件提升收益，负值=去掉反而更好(该组件拖累)。20日高回落5%卖 平均贡献+769%为核心组件（贡献最大），布林下轨回归买/相对强弱上穿30买 贡献为负(作为融合组件反而拖累)。";

async function renderAblationLab() {
  const wrapper = document.createElement("div");
  wrapper.className = "lab-list-2col lab-list-1col";
  const leftCol = document.createElement("div");
  const rightCol = document.createElement("div");

  const essayWarn = document.createElement("div");
  essayWarn.className = "lab-warning lab-warning-essay";
  essayWarn.innerHTML = `<p>${_LAB_ABLATION_RULE}</p>`;
  const purposeNote = document.createElement("div");
  purposeNote.className = "lab-purpose-note";
  purposeNote.innerHTML = "💡 <b>这板块有什么用</b>：把融合信号拆开，单独看每个子信号对收益贡献多少--判断哪个是真本领、哪个是蹭车的，防止被无用信号拖累。<b>怎么解读</b>：贡献率为正=该子信号提升收益（有用）；为负=去掉反而更好（拖累，可考虑剔除）。";
  leftCol.appendChild(purposeNote);
  leftCol.appendChild(essayWarn);

  const data = await fetchLabAblationData();
  const idxList = (data && data.indexes) ? data.indexes.map((x) => ({ id: x.index_id, name: x.index_name })) : [];
  const curIdx = state.labAblationIdx || (idxList[0] && idxList[0].id) || "sh";
  state.labAblationIdx = curIdx;
  const idxBar = document.createElement("div");
  idxBar.className = "lab-win-bar";
  idxBar.innerHTML = `<span class="lab-win-bar-label">选择指数</span><div class="lab-win-tabs">${_labExtIdxBarHTML(idxList, curIdx)}</div>`;
  leftCol.appendChild(idxBar);

  const list = document.createElement("div");
  list.className = "lab-strategy-list lab-retest-list lab-ablation-list";
  list.innerHTML = '<div class="lab-rank-loading">⏳ 加载拆解数据中…</div>';
  leftCol.appendChild(list);

  const phaseNote = document.createElement("div");
  phaseNote.className = "lab-fusion-phase-note";
  phaseNote.innerHTML = "📌 <b>信号拆解测试</b>（消融分析）：6硬编码融合策略 × 3指数。右侧为全局组件平均贡献图。";
  leftCol.appendChild(phaseNote);

  const rankSection = document.createElement("div");
  rankSection.className = "chart-card lab-rank-card";
  rankSection.innerHTML = '<h3>🧩 组件平均贡献率</h3><div class="lab-rank-body"><div class="lab-rank-loading">⏳ 加载中…</div></div>';
  rightCol.appendChild(rankSection);

  wrapper.appendChild(leftCol);
  wrapper.appendChild(rightCol);
  content.appendChild(wrapper);

  const _render = () => {
    const idx = state.labAblationIdx;
    const idxData = data && data.indexes ? data.indexes.find((x) => x.index_id === idx) : null;
    if (!idxData || !idxData.fusions) {
      list.innerHTML = '<div class="lab-rank-empty">暂无拆解数据</div>';
    } else {
      list.innerHTML = idxData.fusions.map((f) => _labAblationCardHTML(f)).join("");
    }
    _labAblationChart(rankSection, data);
  };
  _render();
  idxBar.querySelectorAll(".lab-idx-tab").forEach((btn) => {
    btn.onclick = () => {
      state.labAblationIdx = btn.dataset.idx;
      idxBar.querySelectorAll(".lab-idx-tab").forEach((b) => b.classList.toggle("active", b === btn));
      _render();
    };
  });
}

function _labAblationCardHTML(f) {
  const fs = f.full_stats || {};
  const sideLabel = f.side === "buy" ? "买" : "卖";
  const sideCls = f.side === "buy" ? "lab-tag-live" : "lab-tag-exp";
  const fmtPct = (v) => (v != null && !isNaN(v)) ? (Math.abs(v) >= 1000 ? v.toFixed(0) : v.toFixed(2)) + "%" : "-";
  const ablationRows = (f.ablations || []).map((a) => {
    const contrib = a.ret_contribution;
    const color = contrib > 0 ? _UP : (contrib < 0 ? _DOWN : "var(--text-3)");
    const sign = contrib > 0 ? "+" : "";
    return `<tr><td style="color:var(--text-3)">-${_labCompLabel(a.dropped)}</td><td>${a.kept.map(_labCompLabel).join(" + ")}</td><td>${a.n_signals}</td>` +
      `<td style="color:${color};font-weight:600">${sign}${contrib.toFixed(2)}%</td></tr>`;
  }).join("");
  return `<div class="lab-strategy-card lab-retest-pair">` +
    `<div class="lab-retest-pair-head">` +
    `<span class="lab-retest-pair-strat">${_labPairLabel(f.pair_id)}</span>` +
    `<span class="lab-tag ${sideCls}">${sideLabel}点融合</span>` +
    `<span style="color:${_retFg(fs.total_ret)};font-weight:600">完整收益: ${fmtPct(fs.total_ret)}</span>` +
    `<span style="color:var(--text-3)">胜率: ${fmtPct(fs.win_rate)}</span>` +
    `<span style="color:var(--text-3)">交易: ${fs.n_trades != null ? fs.n_trades : "-"}</span>` +
    `</div>` +
    `<div class="lab-retest-section">` +
    `<div class="lab-retest-section-title">N-1 子集拆解（消融：去掉一个组件后的收益贡献率）</div>` +
    `<table class="lab-retest-yearly"><thead><tr><th>去掉组件</th><th>保留</th><th>信号数</th><th>收益贡献</th></tr></thead>` +
    `<tbody>${ablationRows}</tbody></table></div></div>`;
}

function _labAblationChart(container, data) {
  const body = container.querySelector(".lab-rank-body");
  if (!body) return;
  const summary = data && data.summary;
  if (!summary || !summary.component_contributions) {
    body.innerHTML = '<div class="lab-rank-empty">暂无组件贡献数据</div>';
    return;
  }
  body.innerHTML = "";
  const items = summary.component_contributions.slice().sort((a, b) => b.avg_contribution - a.avg_contribution);
  const gainPct = summary.fusion_gain_positive_pct != null ? summary.fusion_gain_positive_pct : "-";
  const hint = document.createElement("div");
  hint.className = "lab-zone-desc";
  hint.innerHTML = `融合增益为正占比: <b style="color:${gainPct >= 50 ? _UP : _DOWN}">${gainPct}%</b> · 共 ${summary.n_fusion_index_pairs || "-"} 个融合×指数组合`;
  body.appendChild(hint);
  const c = mkCard("各组件平均收益贡献（%, 正=提升 / 负=拖累）", 340, null, body, []);
  c.setOption(withTheme({
    tooltip: { trigger: "axis", formatter: (p) => {
      const it = items[p[0].dataIndex];
      return `${_labCompLabel(it.component)}<br/>平均贡献: ${it.avg_contribution.toFixed(2)}%<br/>正贡献占比: ${it.positive_pct}%<br/>样本数: ${it.n_samples}`;
    }},
    grid: { left: 60, right: 20, top: 20, bottom: 70 },
    xAxis: { type: "category", data: items.map((x) => _labCompLabel(x.component)), axisLabel: { rotate: 35, fontSize: 10 } },
    yAxis: { type: "value", name: "贡献率(%)" },
    series: [{
      type: "bar", barMaxWidth: 42,
      data: items.map((x) => ({ value: x.avg_contribution, itemStyle: { color: _retEc(x.avg_contribution) } })),
      label: { show: true, position: "top", fontSize: 10, formatter: (p) => (p.value >= 0 ? "+" : "") + p.value.toFixed(1) },
    }],
  }));
}

// === ⚖️ 多空对称：做多(buy->sell) vs 做空(sell->buy)镜像对比 ===
const _LAB_SYMMETRY_RULE = "⚖️ 多空对称：做多(先买后卖) vs 做空(先卖后买)镜像对比。A股长期向上漂移，做多盈利/做空亏损属正常不对称；对称比 越接近0越对称(可做空)，越负越偏向做多。做空盈利占比仅9.7%(72配对中7个)，印证A股不适合裸做空。";

async function renderSymmetryLab() {
  const wrapper = document.createElement("div");
  wrapper.className = "lab-list-2col lab-list-1col";
  const leftCol = document.createElement("div");
  const rightCol = document.createElement("div");

  const essayWarn = document.createElement("div");
  essayWarn.className = "lab-warning lab-warning-essay";
  essayWarn.innerHTML = `<p>${_LAB_SYMMETRY_RULE}</p>`;
  const purposeNote = document.createElement("div");
  purposeNote.className = "lab-purpose-note";
  purposeNote.innerHTML = "💡 <b>这板块有什么用</b>：测同一策略做多和做空是否对称--有的策略只适合做多、做空就亏，看这个能判断策略方向适用性。<b>怎么解读</b>：对称比越接近0越对称（可双向做）；越负越偏做多。A股长期向上，做多盈利、做空亏损属正常，不代表策略失效。";
  leftCol.appendChild(purposeNote);
  leftCol.appendChild(essayWarn);

  const data = await fetchLabSymmetryData();
  const idxList = (data && data.indexes) ? data.indexes.map((x) => ({ id: x.index_id, name: x.index_name })) : LAB_SIM_INDEXES;
  const curIdx = state.labSymmetryIdx || (idxList[0] && idxList[0].id) || "sh";
  state.labSymmetryIdx = curIdx;
  const idxBar = document.createElement("div");
  idxBar.className = "lab-win-bar";
  idxBar.innerHTML = `<span class="lab-win-bar-label">选择指数</span><div class="lab-win-tabs">${_labExtIdxBarHTML(idxList, curIdx)}</div>`;
  leftCol.appendChild(idxBar);

  const list = document.createElement("div");
  list.className = "lab-strategy-list lab-retest-list";
  list.innerHTML = '<div class="lab-rank-loading">⏳ 加载对称数据中…</div>';
  leftCol.appendChild(list);

  const phaseNote = document.createElement("div");
  phaseNote.className = "lab-fusion-phase-note";
  phaseNote.innerHTML = "📌 <b>多空对称测试</b>：top8配对做多/做空对比。A股向上漂移致做多盈利、做空亏损属正常不对称。";
  leftCol.appendChild(phaseNote);

  const rankSection = document.createElement("div");
  rankSection.className = "chart-card lab-rank-card";
  rankSection.innerHTML = '<h3>⚖️ 各指数做多 vs 做空平均收益</h3><div class="lab-rank-body"><div class="lab-rank-loading">⏳ 加载中…</div></div>';
  rightCol.appendChild(rankSection);

  wrapper.appendChild(leftCol);
  wrapper.appendChild(rightCol);
  content.appendChild(wrapper);

  const _render = () => {
    const idx = state.labSymmetryIdx;
    const idxData = data && data.indexes ? data.indexes.find((x) => x.index_id === idx) : null;
    if (!idxData || !idxData.pairs) {
      list.innerHTML = '<div class="lab-rank-empty">暂无对称数据</div>';
    } else {
      list.innerHTML = idxData.pairs.map((p) => _labSymmetryCardHTML(p)).join("");
    }
    _labSymmetryChart(rankSection, data);
  };
  _render();
  idxBar.querySelectorAll(".lab-idx-tab").forEach((btn) => {
    btn.onclick = () => {
      state.labSymmetryIdx = btn.dataset.idx;
      idxBar.querySelectorAll(".lab-idx-tab").forEach((b) => b.classList.toggle("active", b === btn));
      _render();
    };
  });
}

function _labSymmetryCardHTML(p) {
  const longRet = p.long && p.long.total_ret;
  const shortRet = p.short && p.short.total_ret;
  const fmt = (v) => (v != null && !isNaN(v)) ? (Math.abs(v) >= 1000 ? v.toFixed(0) : v.toFixed(2)) + "%" : "-";
  const symColor = p.symmetry_ratio >= 0 ? _UP : (p.symmetry_ratio <= -0.3 ? _DOWN : "#f0883e");
  const badge = p.both_positive ? '<span class="lab-tag lab-tag-live">双向盈利</span>'
    : (p.long_pos_short_neg ? '<span class="lab-tag lab-tag-exp">多盈空亏</span>' : "");
  return `<div class="lab-strategy-card lab-retest-pair">` +
    `<div class="lab-retest-pair-head">` +
    `<span class="lab-retest-pair-strat">#${p.rank} ${_labPairLabel(p.pair_id)}</span>` +
    `<span class="lab-retest-pair-win">对称比: <span style="color:${symColor};font-weight:700">${p.symmetry_ratio.toFixed(3)}</span></span>` +
    badge + `</div>` +
    `<div class="lab-retest-section"><div class="lab-retest-regimes lab-symmetry-regimes">` +
    `<div class="lab-retest-regime-card"><div class="lab-retest-regime-name">📈 做多 (买→卖)</div>` +
    `<div class="lab-retest-regime-ret" style="color:${_retFg(longRet)}">${fmt(longRet)}</div>` +
    `<div class="lab-retest-regime-dd">胜率 ${(p.long && p.long.win_rate != null) ? p.long.win_rate.toFixed(1) + "%" : "-"} · ${(p.long && p.long.n_trades) || 0}笔</div></div>` +
    `<div class="lab-retest-regime-card"><div class="lab-retest-regime-name">📉 做空 (卖→买)</div>` +
    `<div class="lab-retest-regime-ret" style="color:${_retFg(shortRet)}">${fmt(shortRet)}</div>` +
    `<div class="lab-retest-regime-dd">胜率 ${(p.short && p.short.win_rate != null) ? p.short.win_rate.toFixed(1) + "%" : "-"} · ${(p.short && p.short.n_trades) || 0}笔</div></div>` +
    `</div></div></div>`;
}

function _labSymmetryChart(container, data) {
  const body = container.querySelector(".lab-rank-body");
  if (!body) return;
  const summary = data && data.summary;
  if (!summary || !summary.by_index) {
    body.innerHTML = '<div class="lab-rank-empty">暂无对称汇总数据</div>';
    return;
  }
  body.innerHTML = "";
  const lp = summary.long_positive_pct != null ? summary.long_positive_pct : "-";
  const sp = summary.short_positive_pct != null ? summary.short_positive_pct : "-";
  const hint = document.createElement("div");
  hint.className = "lab-zone-desc";
  hint.innerHTML = `做多盈利占比: <b style="color:${_UP}">${lp}%</b> · 做空盈利占比: <b style="color:${sp >= 50 ? _UP : _DOWN}">${sp}%</b> · 平均对称比: <b>${summary.avg_symmetry_ratio != null ? summary.avg_symmetry_ratio.toFixed(3) : "-"}</b>`;
  body.appendChild(hint);
  const items = summary.by_index.slice().sort((a, b) => b.avg_long_ret - a.avg_long_ret);
  const c = mkCard("各指数做多/做空平均收益（%）", 360, null, body, []);
  c.setOption(withTheme({
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    legend: { top: 0, data: ["做多平均收益", "做空平均收益"] },
    grid: { left: 60, right: 20, top: 40, bottom: 70 },
    xAxis: { type: "category", data: items.map((x) => x.index_name), axisLabel: { rotate: 30, fontSize: 10 } },
    yAxis: { type: "value", name: "收益(%)" },
    series: [
      { name: "做多平均收益", type: "bar", barMaxWidth: 26, data: items.map((x) => x.avg_long_ret), itemStyle: { color: cssVar("--mx-good-fg") } },
      { name: "做空平均收益", type: "bar", barMaxWidth: 26, data: items.map((x) => x.avg_short_ret), itemStyle: { color: cssVar("--mx-bad-fg") } },
    ],
  }));
}

// === 🎛 参数敏感扫描：7策略参数网格（验证默认参数处于稳定高原而非过拟合尖峰）===
const _LAB_PARAMSCAN_RULE = "🎛 参数敏感扫描：对7策略做参数网格扫描，验证默认参数处于稳定高原而非孤立尖峰(过拟合)。判定:稳健高原=默认参数附近都盈利,尖锐尖峰=仅个别参数盈利(过拟合风险)。上轨突破买/趋势转向买=稳健高原;相对强弱上穿30买/布林带族/20日高回落5%卖=尖锐尖峰,默认参数非回测最优点。";

async function renderParamScanLab() {
  const wrapper = document.createElement("div");
  wrapper.className = "lab-list-2col lab-list-1col";
  const leftCol = document.createElement("div");
  const rightCol = document.createElement("div");

  const essayWarn = document.createElement("div");
  essayWarn.className = "lab-warning lab-warning-essay";
  essayWarn.innerHTML = `<p>${_LAB_PARAMSCAN_RULE}</p>`;
  const purposeNote = document.createElement("div");
  purposeNote.className = "lab-purpose-note";
  purposeNote.innerHTML = "💡 <b>这板块有什么用</b>：调参数看结果怎么变--判断策略对参数敏不敏感，太敏感=过拟合风险（实盘换组参数就失效）。<b>怎么解读</b>：稳健高原=默认参数附近都盈利（靠谱）；尖锐尖峰=仅个别参数盈利（过拟合，慎用）。";
  leftCol.appendChild(purposeNote);
  leftCol.appendChild(essayWarn);

  const data = await fetchLabParamScanData();
  const scans = (data && data.scans) || [];
  // 策略选择器
  const stratList = scans.map((s) => ({ id: s.strategy_key, name: ((LAB_STRATEGIES[s.strategy_key] || {}).name) || s.strategy_key }));
  const curStrat = state.labParamScanStrat || (stratList[0] && stratList[0].id) || "";
  state.labParamScanStrat = curStrat;
  const stratBar = document.createElement("div");
  stratBar.className = "lab-win-bar";
  stratBar.innerHTML = `<span class="lab-win-bar-label">选择策略</span><div class="lab-win-tabs" style="flex-wrap:wrap">${stratList.map((x) =>
    `<button type="button" class="lab-idx-tab${x.id === curStrat ? " active" : ""}" data-strat="${x.id}">${x.name}</button>`
  ).join("")}</div>`;
  leftCol.appendChild(stratBar);

  // 指数选择器（sh/hs300/cyb，从首个 scan 的 per_index 派生）
  const firstScan = scans[0];
  const idxList = firstScan ? firstScan.per_index.map((x) => ({ id: x.index_id, name: x.index_name })) : [];
  const curIdx = state.labParamScanIdx || (idxList[0] && idxList[0].id) || "sh";
  state.labParamScanIdx = curIdx;
  const idxBar = document.createElement("div");
  idxBar.className = "lab-win-bar";
  idxBar.innerHTML = `<span class="lab-win-bar-label">选择指数</span><div class="lab-win-tabs">${_labExtIdxBarHTML(idxList, curIdx)}</div>`;
  leftCol.appendChild(idxBar);

  const list = document.createElement("div");
  list.className = "lab-strategy-list lab-retest-list";
  list.innerHTML = '<div class="lab-rank-loading">⏳ 加载扫描数据中…</div>';
  leftCol.appendChild(list);

  const phaseNote = document.createElement("div");
  phaseNote.className = "lab-fusion-phase-note";
  phaseNote.innerHTML = "📌 <b>参数敏感扫描</b>：7策略参数网格。右侧为所选策略+指数的参数热力图/柱状图，标记默认(○)与回测最优(★)参数。";
  leftCol.appendChild(phaseNote);

  const rankSection = document.createElement("div");
  rankSection.className = "chart-card lab-rank-card";
  rankSection.innerHTML = '<h3>🎛 参数网格收益</h3><div class="lab-rank-body"><div class="lab-rank-loading">⏳ 加载中…</div></div>';
  rightCol.appendChild(rankSection);

  wrapper.appendChild(leftCol);
  wrapper.appendChild(rightCol);
  content.appendChild(wrapper);

  const _render = () => {
    list.innerHTML = _labParamScanOverviewHTML(data, state.labParamScanIdx);
    _labParamScanChart(rankSection, data, state.labParamScanStrat, state.labParamScanIdx);
  };
  _render();
  stratBar.querySelectorAll(".lab-idx-tab").forEach((btn) => {
    btn.onclick = () => {
      state.labParamScanStrat = btn.dataset.strat;
      stratBar.querySelectorAll(".lab-idx-tab").forEach((b) => b.classList.toggle("active", b === btn));
      _render();
    };
  });
  idxBar.querySelectorAll(".lab-idx-tab").forEach((btn) => {
    btn.onclick = () => {
      state.labParamScanIdx = btn.dataset.idx;
      idxBar.querySelectorAll(".lab-idx-tab").forEach((b) => b.classList.toggle("active", b === btn));
      _render();
    };
  });
}

function _labParamScanOverviewHTML(data, idx) {
  const scans = (data && data.scans) || [];
  if (!scans.length) return '<div class="lab-rank-empty">暂无扫描数据</div>';
  const fmt = (v) => (v != null && !isNaN(v)) ? (Math.abs(v) >= 1000 ? v.toFixed(0) : v.toFixed(1)) + "%" : "-";
  const rows = scans.map((s) => {
    const pi = s.per_index.find((x) => x.index_id === idx);
    if (!pi) return "";
    const vLabel = pi.verdict === "robust_profitable" ? "稳健高原" : "尖锐尖峰";
    const vCls = pi.verdict === "robust_profitable" ? "lab-tag-verdict-good" : "lab-tag-verdict-bad";
    const name = ((LAB_STRATEGIES[s.strategy_key] || {}).name) || s.strategy_key;
    return `<tr><td style="font-weight:600">${name}</td>` +
      `<td style="color:${_retFg(pi.default_ret)}">${fmt(pi.default_ret)}</td>` +
      `<td style="color:${_retFg(pi.best_ret)}">${fmt(pi.best_ret)}</td>` +
      `<td>${pi.neighbor_avg_ret != null ? pi.neighbor_avg_ret.toFixed(1) + "%" : "-"}</td>` +
      `<td>${(pi.profitable_frac * 100).toFixed(0)}%</td>` +
      `<td><span class="lab-tag ${vCls}">${vLabel}</span></td></tr>`;
  }).join("");
  return `<div class="lab-retest-pair lab-paramscan-overview"><div class="lab-retest-section">` +
    `<div class="lab-retest-section-title">7策略参数扫描概览（指数 ${idx}）</div>` +
    `<table class="lab-retest-yearly"><thead><tr><th>策略</th><th>默认收益</th><th>回测最优收益</th><th>邻域均值</th><th>盈利占比</th><th>判定</th></tr></thead>` +
    `<tbody>${rows}</tbody></table></div></div>`;
}

function _labParamScanChart(container, data, stratKey, idx) {
  const body = container.querySelector(".lab-rank-body");
  if (!body) return;
  const scan = (data && data.scans) ? data.scans.find((s) => s.strategy_key === stratKey) : null;
  const pi = scan ? scan.per_index.find((x) => x.index_id === idx) : null;
  if (!scan || !pi) {
    body.innerHTML = '<div class="lab-rank-empty">暂无该策略/指数的参数扫描数据</div>';
    return;
  }
  body.innerHTML = "";
  const stratName = ((LAB_STRATEGIES[stratKey] || {}).name) || stratKey;
  const vColor = pi.verdict === "robust_profitable" ? _UP : _DOWN;
  const hint = document.createElement("div");
  hint.className = "lab-zone-desc";
  hint.innerHTML = `${stratName} · ${pi.index_name} · 默认收益 <b style="color:${_retFg(pi.default_ret)}">${pi.default_ret.toFixed(1)}%</b> · 回测最优 <b style="color:${_retFg(pi.best_ret)}">${pi.best_ret.toFixed(1)}%</b> · <span style="color:${vColor};font-weight:600">${pi.verdict === "robust_profitable" ? "稳健高原" : "尖锐尖峰(过拟合风险)"}</span>${pi.best_is_default ? " · 默认即回测最优✓" : ""}`;
  body.appendChild(hint);

  const dims = scan.param_dims || [];
  const combos = pi.combos || [];
  const dp = pi.default_params || scan.default_params || {};
  const bp = pi.best_params || {};
  if (dims.length >= 2) {
    // 热力图（2维参数网格）
    const xName = dims[0].name, yName = dims[1].name;
    const xVals = dims[0].values, yVals = dims[1].values;
    const heatData = [];
    let mn = Infinity, mx = -Infinity;
    combos.forEach((cb) => {
      const xi = xVals.indexOf(cb.params[xName]), yi = yVals.indexOf(cb.params[yName]);
      if (xi < 0 || yi < 0) return;
      const v = cb.total_ret;
      if (v == null || isNaN(v)) { heatData.push([xi, yi, null]); return; }
      heatData.push([xi, yi, v]);
      if (v < mn) mn = v;
      if (v > mx) mx = v;
    });
    if (!isFinite(mn)) { mn = -50; mx = 50; }
    if (mn === mx) { mn -= 1; mx += 1; }
    const c = mkCard(`${_labDimLabel(xName)} × ${_labDimLabel(yName)} 参数网格收益率(%)`, 400, "○=默认参数  ◇=回测最优参数", body, []);
    const dxi = xVals.indexOf(dp[xName]), dyi = yVals.indexOf(dp[yName]);
    const bxi = xVals.indexOf(bp[xName]), byi = yVals.indexOf(bp[yName]);
    const markPoints = [];
    if (dxi >= 0 && dyi >= 0) markPoints.push({ coord: [dxi, dyi], symbol: "circle", symbolSize: 16, itemStyle: { color: "transparent", borderColor: cssVar("--primary"), borderWidth: 2.5 } });
    if (bxi >= 0 && byi >= 0 && !(bxi === dxi && byi === dyi)) markPoints.push({ coord: [bxi, byi], symbol: "diamond", symbolSize: 16, itemStyle: { color: "transparent", borderColor: cssVar("--mx-warn-fg"), borderWidth: 2.5 } });
    c.setOption(withTheme({
      tooltip: { formatter: (p) => {
        const d = p.data;
        if (Array.isArray(d)) {
          return `${_labDimLabel(xName)}=${xVals[d[0]] != null ? xVals[d[0]] : d[0]}, ${_labDimLabel(yName)}=${yVals[d[1]] != null ? yVals[d[1]] : d[1]}<br/>收益: ${d[2] != null ? d[2].toFixed(2) + "%" : "无信号"}`;
        }
        // markPoint hover: p.data = {coord:[xi,yi],...}
        if (d && Array.isArray(d.coord)) {
          const [xi, yi] = d.coord;
          const cell = heatData.find((h) => h[0] === xi && h[1] === yi);
          const v = cell ? cell[2] : null;
          return `${_labDimLabel(xName)}=${xVals[xi] != null ? xVals[xi] : xi}, ${_labDimLabel(yName)}=${yVals[yi] != null ? yVals[yi] : yi}<br/>收益: ${v != null ? v.toFixed(2) + "%" : "无信号"}`;
        }
        return "无数据";
      } },
      grid: { left: 70, right: 20, top: 30, bottom: 80 },
      xAxis: { type: "category", data: xVals.map(String), name: _labDimLabel(xName), nameLocation: "middle", nameGap: 32, splitArea: { show: true } },
      yAxis: { type: "category", data: yVals.map(String), name: _labDimLabel(yName), splitArea: { show: true } },
      visualMap: { min: mn, max: mx, calculable: true, orient: "horizontal", left: "center", bottom: 5,
        inRange: { color: [cssVar("--mx-bad-fg"), cssVar("--mx-warn-fg"), cssVar("--mx-good-fg")] }, textStyle: { color: cssVar("--text-1") } },
      series: [{ type: "heatmap", data: heatData,
        label: { show: true, fontSize: 9, color: cssVar("--bg-card"), textBorderColor: "rgba(0,0,0,0.25)", textBorderWidth: 1.5, formatter: (p) => (Array.isArray(p.data) && p.data[2] != null) ? p.data[2].toFixed(0) : "—" },
        emphasis: { itemStyle: { shadowBlur: 10 } },
        markPoint: { data: markPoints, symbolKeepAspect: false } }],
    }));
  } else if (dims.length === 1) {
    // 柱状图（1维参数）
    const xName = dims[0].name, xVals = dims[0].values;
    const barData = xVals.map((v) => {
      const cb = combos.find((x) => x.params[xName] === v);
      const ret = cb ? cb.total_ret : null;
      return (ret != null && !isNaN(ret)) ? ret : null;
    });
    const c = mkCard(`${_labDimLabel(xName)} 参数扫描收益率(%)`, 360, "📌=默认参数  ★=回测最优参数", body, []);
    const di = xVals.indexOf(dp[xName]);
    const bi = xVals.indexOf(bp[xName]);
    const markPoints = [];
    if (di >= 0) markPoints.push({ coord: [di, barData[di] || 0], symbol: "pin", symbolSize: 36, itemStyle: { color: cssVar("--primary") }, label: { formatter: "默", color: "#fff", fontSize: 9 } });
    if (bi >= 0 && bi !== di) markPoints.push({ coord: [bi, barData[bi] || 0], symbol: "pin", symbolSize: 36, itemStyle: { color: cssVar("--mx-warn-fg") }, label: { formatter: "优", color: "#fff", fontSize: 9 } });
    c.setOption(withTheme({
      tooltip: { trigger: "axis", formatter: (p) => `${_labDimLabel(xName)}=${xVals[p[0].dataIndex]}<br/>收益: ${p[0].value != null ? p[0].value.toFixed(2) + "%" : "无信号"}` },
      grid: { left: 60, right: 20, top: 30, bottom: 50 },
      xAxis: { type: "category", data: xVals.map(String), name: _labDimLabel(xName) },
      yAxis: { type: "value", name: "收益(%)" },
      series: [{ type: "bar", barMaxWidth: 54,
        data: barData.map((v) => ({ value: v, itemStyle: { color: v == null ? cssVar("--text-4") : _retEc(v) } })),
        markPoint: { data: markPoints } }],
    }));
  } else {
    const empty = document.createElement("div");
    empty.className = "lab-rank-empty";
    empty.textContent = "该策略无参数维度";
    body.appendChild(empty);
  }
}

async function renderSignalLab() {
  // 如果有选中的策略，进详情页（仅单一信号模式）
  if (state.labStrategy && state.labSubMode !== "fusion" && state.labSubMode !== "retest"
      && state.labSubMode !== "ablation" && state.labSubMode !== "symmetry" && state.labSubMode !== "paramscan"
      && state.labSubMode !== "custom") {
    await renderLabDetail(state.labStrategy);
    return;
  }

  content.innerHTML = "";

  // C: 顶部合规声明（置顶显著，全子模式可见，非折叠）
  content.insertAdjacentHTML("beforeend", _labTopDisclaimerHTML());

  // P2-3: 新手引导卡（置顶常驻，可折叠，全子模式可见）
  content.insertAdjacentHTML("beforeend", _labNewbieGuideHTML());

  // === 二级导航（单一信号实验 / 融合信号实验）===
  _renderLabSubNav();

  // 融合信号模式 -> 渲染融合列表页（阶段一：仅元数据，不跑回测）
  if (state.labSubMode === "fusion") {
    await renderFusionLab();
    _labSetHash("#lab?sub=fusion");
    _labRestoreScroll();
    return;
  }

  // 二次测试模式 -> 渲染二次测试实验分区（照抄融合区布局：左配对卡片+右维度榜）
  if (state.labSubMode === "retest") {
    await renderRetestLab();
    _labSetHash("#lab?sub=retest");
    _labRestoreScroll();
    return;
  }

  // 信号叠加消融 -> 渲染消融分区（左6融合N-1子集卡片+右组件贡献柱状图）
  if (state.labSubMode === "ablation") {
    await renderAblationLab();
    _labSetHash("#lab?sub=ablation");
    _labRestoreScroll();
    return;
  }

  // 多空对称 -> 渲染对称分区（左top8配对做多/做空卡片+右各指数对比柱状图）
  if (state.labSubMode === "symmetry") {
    await renderSymmetryLab();
    _labSetHash("#lab?sub=symmetry");
    _labRestoreScroll();
    return;
  }

  // 参数敏感扫描 -> 渲染扫描分区（左7策略概览表+右参数网格热力图/柱状图）
  if (state.labSubMode === "paramscan") {
    await renderParamScanLab();
    _labSetHash("#lab?sub=paramscan");
    _labRestoreScroll();
    return;
  }

  // C7 P4-β: 自定义分析 -> 渲染情绪告警+维度拆解+历史类比分区
  if (state.labSubMode === "custom") {
    await renderCustomAnalyzeLab();
    _labSetHash("#lab?sub=custom");
    _labRestoreScroll();
    return;
  }

  // P1-新-C: AI评分 -> 渲染ETF买清单+卖清单(用户输入持仓代码查high_alert)
  if (state.labSubMode === "aiscore") {
    await renderAIScoreListLab();
    _labSetHash("#lab?sub=aiscore");
    _labRestoreScroll();
    return;
  }

  // 实验室自白黄块（列表页也显示，通用介绍 + 抖音号；移入左栏与策略列表同栏）
  const essayWarn = document.createElement("div");
  essayWarn.className = "lab-warning lab-warning-essay";
  essayWarn.innerHTML = _labWarningEssayHTML();
  const purposeNote = document.createElement("div");
  purposeNote.className = "lab-purpose-note";
  purposeNote.innerHTML = "💡 <b>这板块有什么用</b>：逐个测试每条买卖信号单独触发的效果--看哪个信号真有用、胜率收益如何，点进卡片还能看配对回测的净值曲线和交易记录。<b>怎么解读</b>：卡片摘要的10d胜率/PL是单边统计（信号触发后10日涨跌占比）；点进详情的模拟回测才是真实配对交易（买×卖配对算净值）。胜率高+PL为正=信号有效。";

  // 预加载回测数据（用于卡片摘要）
  const data = await fetchLabData();

  // 左右2栏布局：策略卡左 + 回测配对对比榜右
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
  leftCol.appendChild(purposeNote);
  leftCol.appendChild(essayWarn);
  zoneTabs.insertAdjacentHTML("beforeend", _labHelpIcon("status"));
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
    card.dataset.key = key;
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

  // 回测配对对比榜（列表页底部空白区，按指数加载 lab_simulate_{index}.json，不阻塞上方骨架）
  const rankSection = document.createElement("div");
  rankSection.className = "chart-card lab-rank-card";
  // 指数选择器（持久，不随 rank body 重渲染消失）。按钮组样式与"时间窗口"一致。
  const _curIdx = state.labSimIndex || "sh";
  const rankIdxBtns = LAB_SIM_INDEXES.map((x) =>
    `<button type="button" class="lab-idx-tab${x.id === _curIdx ? " active" : ""}" data-idx="${x.id}">${x.name}</button>`
  ).join("");
  rankSection.innerHTML = '<h3>🏆 回测配对对比榜' + _labHelpIcon("pair") + '</h3>' +
    '<div class="lab-rank-sub-note">一个买点+一个卖点组成一对完整交易，7买×7卖=49对</div>' +
    `<div class="lab-win-bar"><span class="lab-win-bar-label">选择指数</span><div class="lab-win-tabs">${rankIdxBtns}</div></div>` +
    '<div class="lab-rank-body"><div class="lab-rank-loading">⏳ 加载配对排行数据中…</div></div>';
  rightCol.appendChild(rankSection);
  // 组装2栏
  wrapper.appendChild(leftCol);
  wrapper.appendChild(rightCol);
  content.appendChild(wrapper);
  const _loadRank = async () => {
    const idx = state.labSimIndex || "sh";
    const [simData] = await Promise.all([fetchLabSimData(idx), fetchLabRetestData(idx)]);
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

  // F5 恢复：更新 hash（含 labSubMode 保位）+ 恢复滚动位置
  _labSetHash("#lab?sub=single");
  _labRestoreScroll();
}

// === C7 P4-β: 🎯 自定义分析 tab（情绪告警 + 8+8 维度拆解 + 历史类比 Top3 + 合规底栏）===
// 数据源：static-site/data/alert_analyze_{iid}.json（55 个静态快照：9 宽基 + 3 红利 + 3 港股 + 9 全球 + 31 申万行业）
// 线上 MaoziYun 静态托管无后端，前端直接 fetch JSON；sh.json 是 error JSON，需容错显示"数据不足"
// C7 P4 market 融合:10 个 _labCustom* 函数 + _LAB_CUSTOM_BROAD/_SW 常量已抽出到 common.js(全 tab 共享)
// 此处用 var 别名引用 window._labCustom*,保持 lab.js 内调用点不变
var _LAB_CUSTOM_BROAD = window._LAB_CUSTOM_BROAD;
var _LAB_CUSTOM_SW = window._LAB_CUSTOM_SW;
var _LAB_CUSTOM_DIV = window._LAB_CUSTOM_DIV;
var _LAB_CUSTOM_HK = window._LAB_CUSTOM_HK;
var _LAB_CUSTOM_GLOBAL = window._LAB_CUSTOM_GLOBAL;
var _labCustomCacheBust = window._labCustomCacheBust;
var _labCustomLevelClass = window._labCustomLevelClass;
var _labCustomLevelText = window._labCustomLevelText;
var _labCustomLevelTooltip = window._labCustomLevelTooltip;
var _labCustomDefaultHuman = window._labCustomDefaultHuman;
var _labCustomScoreSummary = window._labCustomScoreSummary;

// F2: 主渲染函数
// C7 P4 fix: 切换标的只局部更新 host(保留旧内容+顶部细条 spinner),fetch 完淡入替换,不重建整个 wrapper/不全屏 ⏳加载中
async function renderCustomAnalyzeLab() {
  const curIid = state.labCustomIid || "hs300";

  // 判断是首次加载还是切换标的:已有 wrapper 则复用,只更新 host
  const existingWrap = content.querySelector(".lab-custom-wrap");
  const isSwitch = !!existingWrap;
  let wrapper, host;

  if (isSwitch) {
    // 切换:复用 wrapper/intro/selector,只同步 select 选中值 + host 加轻量加载指示
    wrapper = existingWrap;
    host = wrapper.querySelector(".lab-custom-host");
    const sel = wrapper.querySelector(".lab-custom-select");
    if (sel && sel.value !== curIid) sel.value = curIid;
    // C7 P4 select 检索:清空检索框+恢复全部 options 可见(避免上次筛选残留致 curIid 的 option 被隐藏)
    const searchInput = wrapper.querySelector(".lab-custom-search");
    if (searchInput && searchInput.value) {
      searchInput.value = "";
      if (sel) {
        sel.querySelectorAll("option").forEach((o) => { o.style.display = ""; });
        sel.querySelectorAll("optgroup").forEach((g) => { g.style.display = ""; });
      }
      const hint = wrapper.querySelector(".lab-custom-hint");
      if (hint) {
        hint.innerHTML = `共 ${_LAB_CUSTOM_BROAD.length + _LAB_CUSTOM_SW.length + _LAB_CUSTOM_DIV.length + _LAB_CUSTOM_HK.length + _LAB_CUSTOM_GLOBAL.length} 个预生成快照（每日收盘后更新）`;
        hint.style.color = "";
      }
    }
    // 旧内容保留(半透明+禁用交互),顶部细条 spinner,不全屏清空
    host.classList.add("lab-custom-host--loading");
  } else {
    // 首次:构建 wrapper + 顶部说明 + 选择器 + host(显示 ⏳加载中)
    // 左右两栏：左侧=选择器+分数卡+维度表，右侧=历史类比+阈值表（移动端自动堆叠）
    wrapper = document.createElement("div");
    wrapper.className = "lab-custom-wrap";

    // 顶部说明
    const intro = document.createElement("div");
    intro.className = "lab-purpose-note";
    intro.innerHTML = "💡 <b>这板块有什么用</b>：对单个指数/行业做情绪告警分析--看高位风险分(过热?)和低位机会分(冰点?)，拆解 8+8 维度贡献，并找历史相似时段看后续涨跌。<b>怎么解读</b>：高位分>70=过热警惕，低位分>70=偏冷关注企稳；历史类比仅作统计参考，不代表未来必然走势。";
    wrapper.appendChild(intro);

    // 标的选择器
    const selector = document.createElement("div");
    selector.className = "lab-custom-selector";
    const opts = ['<optgroup label="宽基指数">' +
      _LAB_CUSTOM_BROAD.map((t) => `<option value="${t.iid}"${t.iid === curIid ? " selected" : ""}>${t.name}</option>`).join("") +
      "</optgroup>",
      '<optgroup label="申万一级行业">' +
      _LAB_CUSTOM_SW.map((t) => `<option value="${t.iid}"${t.iid === curIid ? " selected" : ""}>${t.name}</option>`).join("") +
      "</optgroup>",
      '<optgroup label="红利指数">' +
      _LAB_CUSTOM_DIV.map((t) => `<option value="${t.iid}"${t.iid === curIid ? " selected" : ""}>${t.name}</option>`).join("") +
      "</optgroup>",
      '<optgroup label="港股指数">' +
      _LAB_CUSTOM_HK.map((t) => `<option value="${t.iid}"${t.iid === curIid ? " selected" : ""}>${t.name}</option>`).join("") +
      "</optgroup>",
      '<optgroup label="全球指数">' +
      _LAB_CUSTOM_GLOBAL.map((t) => `<option value="${t.iid}"${t.iid === curIid ? " selected" : ""}>${t.name}</option>`).join("") +
      "</optgroup>"].join("");
    selector.innerHTML =
      `<input class="lab-custom-search" type="search" placeholder="检索代码/名称筛选…" autocomplete="off" aria-label="检索标的">` +
      `<label class="lab-custom-selector-label">分析标的：</label>` +
      `<select class="lab-custom-select">${opts}</select>` +
      `<span class="lab-custom-hint">共 ${_LAB_CUSTOM_BROAD.length + _LAB_CUSTOM_SW.length + _LAB_CUSTOM_DIV.length + _LAB_CUSTOM_HK.length + _LAB_CUSTOM_GLOBAL.length} 个预生成快照（每日收盘后更新）</span>`;
    // C7 P4 select 检索:oninput 实时筛选 select options(代码+名称,不区分大小写)
    selector.querySelector(".lab-custom-search").oninput = (e) => {
      const q = (e.target.value || "").trim().toLowerCase();
      const sel = selector.querySelector(".lab-custom-select");
      if (!sel) return;
      let visible = 0;
      sel.querySelectorAll("option").forEach((opt) => {
        const txt = (opt.textContent || "").toLowerCase();
        const val = (opt.value || "").toLowerCase();
        const match = !q || txt.includes(q) || val.includes(q);
        opt.style.display = match ? "" : "none";
        if (match) visible++;
      });
      // optgroup 无可见子 option 时隐藏
      sel.querySelectorAll("optgroup").forEach((grp) => {
        const hasVis = Array.from(grp.querySelectorAll("option")).some((o) => o.style.display !== "none");
        grp.style.display = hasVis ? "" : "none";
      });
      const hint = selector.querySelector(".lab-custom-hint");
      if (hint) {
        if (q && visible === 0) {
          hint.textContent = `无匹配标的（关键词"${e.target.value}"）`;
          hint.style.color = "#d4380d";
        } else {
          hint.innerHTML = `共 ${_LAB_CUSTOM_BROAD.length + _LAB_CUSTOM_SW.length + _LAB_CUSTOM_DIV.length + _LAB_CUSTOM_HK.length + _LAB_CUSTOM_GLOBAL.length} 个预生成快照（每日收盘后更新）`;
          hint.style.color = "";
        }
      }
    };
    selector.querySelector(".lab-custom-select").onchange = (e) => {
      state.labCustomIid = e.target.value;
      // 切换标的时清空检索框+恢复全部 options 可见(避免筛选残留)
      const searchInput = selector.querySelector(".lab-custom-search");
      if (searchInput && searchInput.value) {
        searchInput.value = "";
        searchInput.dispatchEvent(new Event("input", { bubbles: true }));
      }
      renderCustomAnalyzeLab();
    };
    wrapper.appendChild(selector);

    // 加载区(首次才显示全屏 ⏳加载中)
    host = document.createElement("div");
    host.className = "lab-custom-host";
    host.innerHTML = '<div class="lab-custom-loading">⏳ 加载中…</div>';
    wrapper.appendChild(host);

    // 移除旧 wrapper(若有)避免内容累加
    content.querySelectorAll(".lab-custom-wrap").forEach((el) => el.remove());
    content.appendChild(wrapper);
  }

  // fetch 静态 JSON
  const v = _labCustomCacheBust();
  const url = `./data/alert_analyze_${curIid}.json?v=${v}`;
  let data = null;
  try {
    data = await fetchJSON(url);
  } catch (e) {
    host.classList.remove("lab-custom-host--loading");
    host.innerHTML = `<div class="lab-custom-error">⚠️ 加载失败：${e.message || e}<br><button type="button" class="lab-custom-retry">重试</button></div>`;
    host.querySelector(".lab-custom-retry").onclick = () => renderCustomAnalyzeLab();
    return;
  }

  // error JSON 容错（如 sh=上证指数 数据不足）
  if (!data || data.error) {
    host.classList.remove("lab-custom-host--loading");
    const errMsg = (data && data.error) ? data.error : "未知错误";
    host.innerHTML =
      `<div class="lab-custom-error">` +
      `<div class="lab-custom-error-title">⚠️ 数据不足，暂无法分析此标的</div>` +
      `<div class="lab-custom-error-detail">${errMsg}</div>` +
      `<div class="lab-custom-error-hint">该标的后端计算异常（如指数数据缺失/dtype 异常），待后端修复后自动恢复。</div>` +
      `<button type="button" class="lab-custom-retry">重试</button>` +
      `</div>`;
    host.querySelector(".lab-custom-retry").onclick = () => renderCustomAnalyzeLab();
    return;
  }

  // 渲染各分区(切换时新内容淡入过渡,避免硬替换闪烁)
  host.innerHTML = "";
  host.classList.remove("lab-custom-host--loading");
  const alert = data.alert || {};
  const reason = data.reason || {};

  // F3: 分数卡
  host.insertAdjacentHTML("beforeend", _labCustomScoreCardHTML(data, alert, reason.human_text));
  // F4: 8+8 维度表
  host.insertAdjacentHTML("beforeend", _labCustomDimsTableHTML(reason.dim_hits, alert.dims, alert.adapt));
  // F5: 历史类比
  host.insertAdjacentHTML("beforeend", _labCustomHistoryHTML(reason.history_analogy, reason.human_text));
  // F6: 数据阈值表（折叠）
  host.insertAdjacentHTML("beforeend", _labCustomThresholdsHTML(reason.data_thresholds));
  // F7: 合规底栏
  host.insertAdjacentHTML("beforeend", _labCustomFooterHTML(reason.compliance_footer, reason.no_data_hint));

  // C7 P4 fix: 切换/首次加载完成后,新内容淡入(从轻微下移+透明 到 正常)
  if (host.animate) {
    host.animate(
      [{ opacity: 0, transform: "translateY(4px)" }, { opacity: 1, transform: "translateY(0)" }],
      { duration: 220, easing: "ease" }
    );
  }

  // 折叠阈值表交互
  const toggle = host.querySelector(".lab-custom-thresh-toggle");
  if (toggle) {
    toggle.onclick = () => {
      const body = host.querySelector(".lab-custom-thresh-body");
      const open = body && body.style.display !== "none";
      if (body) body.style.display = open ? "none" : "block";
      toggle.textContent = open ? "展开数据阈值表 ▾" : "收起数据阈值表 ▴";
    };
  }
}

// === P1-新-C: 📈 AI评分 tab（ETF买清单+卖清单/持仓自查）===
// 数据源：static-site/data/etf_score_list.json（后端收盘后生成）
//   {date, buy_list:[{etf_code,name,score,hands,high_alert,low_alert,is_national_team,reason_summary}],
//    sell_list:[{etf_code,name,score,high_alert,low_alert,sell_signal,is_national_team,reason_summary}]}
// 线上静态托管无后端，前端直接 fetch JSON；JSON 未生成/缺失时兜底"数据加载中/暂无"
// 单标的分析(modal+持仓自查)复用 common.js 的 _labCustom*HTML 10函数（与 🎯自定义分析 tab 同源，前端0重写）
// 国家队ETF代码->iid 映射（用于点击行打开详情 modal / 持仓自查输入框）
var _LAB_AISCORE_ETF_TO_IID = {
  "510050": "sz50", "510300": "hs300", "510310": "hs300", "510500": "csi500",
  "159919": "hs300", "159915": "cyb", "159922": "csi500", "159920": "cyb",
  "588000": "kc50", "588050": "kc50", "512100": "csi1000", "512760": "kc50",
  "515050": "sz50", "588090": "kc50", "159949": "csi_div",
  "510880": "sz_div", "515080": "csi_div", "512890": "div_lowvol",
  "159845": "csi1000", "159952": "cyb",
  "513050": "hstech", "510900": "hsi", "513100": "hscei",
};
// 取 ETF code（兼容 etf_code/code 两种字段名,后端用 etf_code）
function _labAIScoreCode(it) {
  return (it && (it.etf_code || it.code)) || "";
}
async function renderAIScoreListLab() {
  // wrapper：顶部说明 + 买清单 + 卖清单 + 持仓自查
  const wrapper = document.createElement("div");
  wrapper.className = "lab-aiscore-wrap";

  // 顶部说明
  const intro = document.createElement("div");
  intro.className = "lab-purpose-note";
  intro.innerHTML = "💡 <b>这板块有什么用</b>：基于 🎯自定义分析 的 8+8 维度 AI 评分,对全市场 ETF 做买卖清单排序--低位机会分高的进买清单(按手数 3/2/1 建议买入量),高位风险分高的进卖清单(给卖出建议)。<b>怎么解读</b>:买清单按 AI 评分降序排,手数 badge 表示建议仓位(3手=机会最强/2手=关注/1手=少量);卖清单列出全部 ETF 的 high_alert + sell_signal 持有/减仓建议。点击行可看完整 8+8 维度拆解 modal(复用 🎯自定义分析 数据),也可用持仓自查输入任意 ETF 代码查询。";
  wrapper.appendChild(intro);

  // 买清单 host
  const buyHost = document.createElement("div");
  buyHost.className = "lab-aiscore-section lab-aiscore-buy";
  buyHost.innerHTML = '<div class="lab-custom-loading">⏳ 加载买清单…</div>';
  wrapper.appendChild(buyHost);

  // 卖清单 host
  const sellHost = document.createElement("div");
  sellHost.className = "lab-aiscore-section lab-aiscore-sell";
  wrapper.appendChild(sellHost);

  // 持仓自查 host（额外功能:输入任意ETF代码查询）
  const queryHost = document.createElement("div");
  queryHost.className = "lab-aiscore-section lab-aiscore-query";
  wrapper.appendChild(queryHost);

  content.querySelectorAll(".lab-aiscore-wrap").forEach((el) => el.remove());
  content.appendChild(wrapper);

  // fetch etf_score_list.json（后端生成,不存在时兜底）
  const v = _labCustomCacheBust();
  const url = `./data/etf_score_list.json?v=${v}`;
  let data = null;
  try {
    data = await fetchJSON(url);
  } catch (e) {
    buyHost.innerHTML = `<div class="lab-custom-error">` +
      `<div class="lab-custom-error-title">⚠️ 买清单数据加载失败</div>` +
      `<div class="lab-custom-error-detail">${e.message || e}</div>` +
      `<div class="lab-custom-error-hint">etf_score_list.json 不存在或网络异常。后端生成后自动恢复（每日收盘后更新）。</div>` +
      `<button type="button" class="lab-custom-retry">重试</button></div>`;
    buyHost.querySelector(".lab-custom-retry").onclick = () => renderAIScoreListLab();
    _renderAIScoreSellSection(sellHost, [], {});
    _renderAIScoreQuerySection(queryHost, {});
    return;
  }
  if (!data || data.error || !Array.isArray(data.buy_list)) {
    buyHost.innerHTML = `<div class="lab-custom-error">` +
      `<div class="lab-custom-error-title">⚠️ 买清单暂未生成</div>` +
      `<div class="lab-custom-error-detail">${(data && data.error) || "etf_score_list.json 结构异常或为空"}</div>` +
      `<div class="lab-custom-error-hint">后端未生成买清单数据,收盘后跑完评分即自动恢复。可先去 🎯自定义分析 tab 看单标的分析。</div>` +
      `<button type="button" class="lab-custom-retry">重试</button></div>`;
    buyHost.querySelector(".lab-custom-retry").onclick = () => renderAIScoreListLab();
    _renderAIScoreSellSection(sellHost, [], {});
    _renderAIScoreQuerySection(queryHost, {});
    return;
  }

  // === 公共映射:ETF code -> iid（后端 buy_list 不含 iid,用前端 _LAB_AISCORE_ETF_TO_IID 兜底）===
  const codeToIid = {};
  Object.keys(_LAB_AISCORE_ETF_TO_IID).forEach((c) => {
    codeToIid[c] = _LAB_AISCORE_ETF_TO_IID[c];
  });

  // === 买清单渲染（按 score 降序,展示前12行）===
  const date = data.date || "";
  const dateStr = date && date.length === 8 ? `${date.slice(0,4)}-${date.slice(4,6)}-${date.slice(6,8)}` : date;
  const sorted = data.buy_list.slice().sort((a, b) => (b.score || 0) - (a.score || 0)).slice(0, 12);
  const rowsHTML = sorted.map((it, idx) => {
    const code = _labAIScoreCode(it);
    const iid = codeToIid[code] || "";
    const score = it.score != null ? Number(it.score).toFixed(1) : "-";
    const hands = it.hands != null ? Number(it.hands) : 0;
    const handsCls = `hands-${[3, 2, 1, 0].includes(hands) ? hands : 0}`;
    const nt = it.is_national_team ? `<span class="lab-aiscore-nt">国家队</span>` : "";
    const reason = it.reason_summary ? `<span class="lab-aiscore-reason">${it.reason_summary}</span>` : "";
    return `<tr class="lab-aiscore-row" data-code="${code}" data-iid="${iid}" data-name="${it.name || ""}">` +
      `<td class="aiscore-rank">${idx + 1}</td>` +
      `<td class="aiscore-code">${code || "-"}</td>` +
      `<td class="aiscore-name">${it.name || "-"}${nt}</td>` +
      `<td class="aiscore-score">${score}</td>` +
      `<td class="aiscore-hands"><span class="hands-badge ${handsCls}">${hands}手</span></td>` +
      `<td class="aiscore-reason-cell">${reason}</td>` +
    `</tr>`;
  }).join("");
  const emptyRow = sorted.length === 0 ? `<tr><td colspan="6" class="lab-aiscore-empty">暂无买清单数据</td></tr>` : "";
  buyHost.innerHTML =
    `<div class="lab-aiscore-section-head">` +
      `<div class="lab-aiscore-section-title">📈 AI买清单 <span class="lab-aiscore-date">📅 ${dateStr || "未注明日期"}</span></div>` +
      `<div class="lab-aiscore-section-sub">按低位机会分降序 · 手数 3/2/1 建议买入量 · 0手不入清单</div>` +
    `</div>` +
    `<div class="lab-aiscore-table-wrap">` +
      `<table class="lab-aiscore-table">` +
        `<thead><tr><th>#</th><th>代码</th><th>名称</th><th>AI分</th><th>建议</th><th>理由摘要</th></tr></thead>` +
        `<tbody>${rowsHTML}${emptyRow}</tbody>` +
      `</table>` +
    `</div>`;
  // 点击行弹理由 modal（复用 _labCustom*HTML 5函数）
  buyHost.querySelectorAll(".lab-aiscore-row").forEach((tr) => {
    tr.onclick = () => {
      const iid = tr.dataset.iid;
      const code = tr.dataset.code;
      const name = tr.dataset.name;
      if (!iid) {
        _labAIScoreOpenModal(`<div class="lab-custom-error"><div class="lab-custom-error-title">⚠️ 无 iid 映射</div><div class="lab-custom-error-detail">ETF ${code}(${name}) 未配置 iid,无法加载 8+8 维度拆解。可去 🎯自定义分析 tab 手动选标的查看。</div></div>`);
        return;
      }
      _labAIScoreOpenDetailModal(code, name, iid);
    };
  });

  // === 卖清单渲染（直接渲染 sell_list 表格 + 持仓自查）===
  _renderAIScoreSellSection(sellHost, data.sell_list || [], codeToIid);
  _renderAIScoreQuerySection(queryHost, codeToIid);
}

// 卖清单渲染:直接展示 sell_list 表格(high_alert + sell_signal + 理由)
function _renderAIScoreSellSection(host, sellList, codeToIid) {
  sellList = sellList || [];
  codeToIid = codeToIid || {};
  const sortedSell = sellList.slice().sort((a, b) => (b.high_alert || 0) - (a.high_alert || 0));
  const rowsHTML = sortedSell.map((it, idx) => {
    const code = _labAIScoreCode(it);
    const iid = codeToIid[code] || "";
    const high = it.high_alert != null ? Number(it.high_alert).toFixed(1) : "-";
    const low = it.low_alert != null ? Number(it.low_alert).toFixed(1) : "-";
    const sig = it.sell_signal || "-";
    // 危险词:含"减仓/卖出/清仓"等明确卖出动作;中性词:含"持有/观望";其余(如"偏热留意")=warn
    // 注意:"持有(未过热)"含"过热"但语义中性,故只匹配"减仓/卖/清仓"动作词
    const sigCls = /减仓|卖出|清仓|卖/.test(sig) ? "sig-danger" : /持有|观望/.test(sig) ? "sig-neutral" : "sig-warn";
    const nt = it.is_national_team ? `<span class="lab-aiscore-nt">国家队</span>` : "";
    const reason = it.reason_summary ? `<span class="lab-aiscore-reason">${it.reason_summary}</span>` : "";
    return `<tr class="lab-aiscore-row" data-code="${code}" data-iid="${iid}" data-name="${it.name || ""}">` +
      `<td class="aiscore-rank">${idx + 1}</td>` +
      `<td class="aiscore-code">${code || "-"}</td>` +
      `<td class="aiscore-name">${it.name || "-"}${nt}</td>` +
      `<td class="aiscore-high">${high}</td>` +
      `<td class="aiscore-low">${low}</td>` +
      `<td class="aiscore-signal"><span class="sell-signal ${sigCls}">${sig}</span></td>` +
      `<td class="aiscore-reason-cell">${reason}</td>` +
    `</tr>`;
  }).join("");
  const empty = sortedSell.length === 0 ? `<tr><td colspan="7" class="lab-aiscore-empty">暂无卖清单数据（等后端生成）</td></tr>` : "";
  host.innerHTML =
    `<div class="lab-aiscore-section-head">` +
      `<div class="lab-aiscore-section-title">📉 AI卖清单 <span class="lab-aiscore-section-sub-inline">按 high_alert 降序 · sell_signal=持有/减仓建议</span></div>` +
    `</div>` +
    `<div class="lab-aiscore-table-wrap">` +
      `<table class="lab-aiscore-table lab-aiscore-table-sell">` +
        `<thead><tr><th>#</th><th>代码</th><th>名称</th><th>high_alert</th><th>low_alert</th><th>sell_signal</th><th>理由摘要</th></tr></thead>` +
        `<tbody>${rowsHTML}${empty}</tbody>` +
      `</table>` +
    `</div>`;
  host.querySelectorAll(".lab-aiscore-row").forEach((tr) => {
    tr.onclick = () => {
      const iid = tr.dataset.iid;
      const code = tr.dataset.code;
      const name = tr.dataset.name;
      if (!iid) {
        _labAIScoreOpenModal(`<div class="lab-custom-error"><div class="lab-custom-error-title">⚠️ 无 iid 映射</div><div class="lab-custom-error-detail">ETF ${code}(${name}) 未配置 iid,无法加载 8+8 维度拆解。可去 🎯自定义分析 tab 手动选标的查看。</div></div>`);
        return;
      }
      _labAIScoreOpenDetailModal(code, name, iid);
    };
  });
}

// 持仓自查:输入任意ETF代码 -> fetch alert_analyze -> 展示 high_alert + sell_signal + 理由
function _renderAIScoreQuerySection(host, codeToIid) {
  codeToIid = codeToIid || {};
  host.innerHTML =
    `<div class="lab-aiscore-section-head">` +
      `<div class="lab-aiscore-section-title">🔍 持仓自查（输入任意 ETF 代码查 high_alert）</div>` +
      `<div class="lab-aiscore-section-sub">输入持仓 ETF 代码（如 510300）查高位风险分 + 卖出建议 + 完整维度拆解</div>` +
    `</div>` +
    `<div class="lab-aiscore-sell-input-wrap">` +
      `<input type="text" class="lab-aiscore-sell-input" placeholder="ETF代码(如510300)" autocomplete="off" inputmode="numeric">` +
      `<button type="button" class="lab-aiscore-sell-btn">查 high_alert</button>` +
    `</div>` +
    `<div class="lab-aiscore-sell-result"></div>`;
  const input = host.querySelector(".lab-aiscore-sell-input");
  const btn = host.querySelector(".lab-aiscore-sell-btn");
  const resultHost = host.querySelector(".lab-aiscore-sell-result");
  const runQuery = async () => {
    const code = (input.value || "").trim();
    if (!code) { resultHost.innerHTML = `<div class="lab-custom-error">请输入 ETF 代码</div>`; return; }
    const iid = codeToIid[code] || _LAB_AISCORE_ETF_TO_IID[code];
    if (!iid) {
      resultHost.innerHTML = `<div class="lab-custom-error"><div class="lab-custom-error-title">⚠️ 未识别 ETF 代码</div><div class="lab-custom-error-detail">${code} 未配置 iid 映射(仅支持国家队等常见 ETF)。</div><div class="lab-custom-error-hint">常见:510050/510300/510500/159915/588000/510880/513050/510900 等,或去 🎯自定义分析 tab 选标的。</div></div>`;
      return;
    }
    resultHost.innerHTML = `<div class="lab-custom-loading">⏳ 加载 ${code} 的 high_alert…</div>`;
    const v = _labCustomCacheBust();
    const url = `./data/alert_analyze_${iid}.json?v=${v}`;
    let data = null;
    try {
      data = await fetchJSON(url);
    } catch (e) {
      resultHost.innerHTML = `<div class="lab-custom-error"><div class="lab-custom-error-title">⚠️ 加载失败</div><div class="lab-custom-error-detail">${e.message || e}</div><button type="button" class="lab-custom-retry">重试</button></div>`;
      const rt = resultHost.querySelector(".lab-custom-retry");
      if (rt) rt.onclick = runQuery;
      return;
    }
    if (!data || data.error) {
      resultHost.innerHTML = `<div class="lab-custom-error"><div class="lab-custom-error-title">⚠️ 数据不足</div><div class="lab-custom-error-detail">${(data && data.error) || "未知错误"}</div><div class="lab-custom-error-hint">该标的后端计算异常(如指数数据缺失),待后端修复后自动恢复。</div></div>`;
      return;
    }
    const alert = data.alert || {};
    const reason = data.reason || {};
    const high = alert.high;
    const highLvl = alert.high_level || "";
    const highTooltip = _labCustomLevelTooltip(high, "high");
    const highCls = _labCustomLevelClass(high, "high");
    // sell_signal: high >= 70 建议减仓 / 50-70 偏热留意 / <50 暂无卖出信号
    const sellSignal = (high != null && !isNaN(high)) ?
      (high >= 70 ? "🔴 建议减仓" : high >= 50 ? "🟡 偏热留意" : "🟢 暂无卖出信号") : "无数据";
    const highHuman = (reason.human_text && reason.human_text.high) || _labCustomDefaultHuman("high", high);
    resultHost.innerHTML =
      `<div class="lab-aiscore-sell-card">` +
        `<div class="lab-aiscore-sell-head">` +
          `<div class="lab-aiscore-sell-title">${data.target_name || code} <span class="lab-aiscore-sell-code">${code}</span> <span class="lab-aiscore-sell-iid">iid=${iid}</span></div>` +
          `<div class="lab-aiscore-sell-date">📅 ${alert.date || ""}</div>` +
        `</div>` +
        `<div class="lab-aiscore-sell-grid">` +
          `<div class="lab-aiscore-sell-cell ${highCls}">` +
            `<div class="lab-aiscore-sell-cell-label">高位风险分 high_alert</div>` +
            `<div class="lab-aiscore-sell-cell-score">${high != null ? Number(high).toFixed(2) : "-"}</div>` +
            `<div class="lab-aiscore-sell-cell-level" title="${highTooltip}">${highLvl}</div>` +
            `<div class="lab-aiscore-sell-cell-desc">分越高越接近过热 · ≥70 建议减仓</div>` +
          `</div>` +
          `<div class="lab-aiscore-sell-cell">` +
            `<div class="lab-aiscore-sell-cell-label">卖出建议 sell_signal</div>` +
            `<div class="lab-aiscore-sell-cell-signal">${sellSignal}</div>` +
            `<div class="lab-aiscore-sell-cell-desc">基于 high_alert 阈值(70/50)派生,仅作参考</div>` +
          `</div>` +
        `</div>` +
        `<div class="lab-aiscore-sell-human">${highHuman}</div>` +
        `<button type="button" class="lab-aiscore-sell-detail-btn">查看完整 8+8 维度拆解 -></button>` +
      `</div>`;
    const detailBtn = resultHost.querySelector(".lab-aiscore-sell-detail-btn");
    if (detailBtn) detailBtn.onclick = () => _labAIScoreOpenDetailModal(code, data.target_name || code, iid);
  };
  btn.onclick = runQuery;
  input.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); runQuery(); } };
}

// 单标的分析 modal（复用 _labCustom*HTML 5函数,fetch alert_analyze_{iid}.json）
async function _labAIScoreOpenDetailModal(code, name, iid) {
  // 先打开 modal 显示加载中
  let overlay = document.getElementById("labAIScoreOverlay");
  if (!overlay) {
    overlay = document.createElement("div");
    overlay.id = "labAIScoreOverlay";
    overlay.className = "lab-signal-overlay";
    document.body.appendChild(overlay);
  }
  overlay.innerHTML =
    `<div class="lab-signal-modal lab-aiscore-modal">` +
      `<div class="lab-signal-modal-head">` +
        `<span class="lab-signal-modal-title">📈 ${code} ${name} · AI 评分详情</span>` +
        `<button type="button" class="lab-rank-modal-close" aria-label="关闭">✕</button>` +
      `</div>` +
      `<div class="lab-signal-modal-body"><div class="lab-custom-loading">⏳ 加载 alert_analyze_${iid}.json…</div></div>` +
    `</div>`;
  overlay.classList.add("show");
  document.body.style.overflow = "hidden";
  overlay.onclick = (e) => { if (e.target === overlay) _labAIScoreCloseModal(); };
  overlay.querySelector(".lab-rank-modal-close").onclick = _labAIScoreCloseModal;
  const body = overlay.querySelector(".lab-signal-modal-body");

  const v = _labCustomCacheBust();
  const url = `./data/alert_analyze_${iid}.json?v=${v}`;
  let data = null;
  try {
    data = await fetchJSON(url);
  } catch (e) {
    body.innerHTML = `<div class="lab-custom-error"><div class="lab-custom-error-title">⚠️ 加载失败</div><div class="lab-custom-error-detail">${e.message || e}</div><button type="button" class="lab-custom-retry">重试</button></div>`;
    const rt = body.querySelector(".lab-custom-retry");
    if (rt) rt.onclick = () => _labAIScoreOpenDetailModal(code, name, iid);
    return;
  }
  if (!data || data.error) {
    body.innerHTML = `<div class="lab-custom-error"><div class="lab-custom-error-title">⚠️ 数据不足</div><div class="lab-custom-error-detail">${(data && data.error) || "未知错误"}</div><div class="lab-custom-error-hint">该标的后端计算异常(如指数数据缺失),待后端修复后自动恢复。</div></div>`;
    return;
  }
  const alert = data.alert || {};
  const reason = data.reason || {};
  body.innerHTML = "";
  // F3: 分数卡
  body.insertAdjacentHTML("beforeend", _labCustomScoreCardHTML(data, alert, reason.human_text));
  // F4: 8+8 维度表
  body.insertAdjacentHTML("beforeend", _labCustomDimsTableHTML(reason.dim_hits, alert.dims, alert.adapt));
  // F5: 历史类比
  body.insertAdjacentHTML("beforeend", _labCustomHistoryHTML(reason.history_analogy, reason.human_text));
  // F6: 数据阈值表（折叠）
  body.insertAdjacentHTML("beforeend", _labCustomThresholdsHTML(reason.data_thresholds));
  // F7: 合规底栏
  body.insertAdjacentHTML("beforeend", _labCustomFooterHTML(reason.compliance_footer, reason.no_data_hint));
  // 折叠阈值表交互
  const toggle = body.querySelector(".lab-custom-thresh-toggle");
  if (toggle) {
    toggle.onclick = () => {
      const tBody = body.querySelector(".lab-custom-thresh-body");
      const open = tBody && tBody.style.display !== "none";
      if (tBody) tBody.style.display = open ? "none" : "block";
      toggle.textContent = open ? "展开数据阈值表 ▾" : "收起数据阈值表 ▴";
    };
  }
}

// 简单 HTML 内容 modal（无数据时的兜底弹窗）
function _labAIScoreOpenModal(html) {
  let overlay = document.getElementById("labAIScoreOverlay");
  if (!overlay) {
    overlay = document.createElement("div");
    overlay.id = "labAIScoreOverlay";
    overlay.className = "lab-signal-overlay";
    document.body.appendChild(overlay);
  }
  overlay.innerHTML =
    `<div class="lab-signal-modal lab-aiscore-modal">` +
      `<div class="lab-signal-modal-head">` +
        `<span class="lab-signal-modal-title">📈 AI 评分详情</span>` +
        `<button type="button" class="lab-rank-modal-close" aria-label="关闭">✕</button>` +
      `</div>` +
      `<div class="lab-signal-modal-body">${html}</div>` +
    `</div>`;
  overlay.classList.add("show");
  document.body.style.overflow = "hidden";
  overlay.onclick = (e) => { if (e.target === overlay) _labAIScoreCloseModal(); };
  overlay.querySelector(".lab-rank-modal-close").onclick = _labAIScoreCloseModal;
}

function _labAIScoreCloseModal() {
  const overlay = document.getElementById("labAIScoreOverlay");
  if (overlay) {
    overlay.classList.remove("show");
    overlay.innerHTML = "";
    overlay.onclick = null;
  }
  document.body.style.overflow = "";
}

var _labCustomScoreCardHTML = window._labCustomScoreCardHTML;

var _labCustomDimsTableHTML = window._labCustomDimsTableHTML;
var _labCustomHistoryHTML = window._labCustomHistoryHTML;
var _labCustomThresholdsHTML = window._labCustomThresholdsHTML;
var _labCustomFooterHTML = window._labCustomFooterHTML;

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

// 初始加载：读 hash 恢复 tab + 策略 + labSubMode（lab.js 在 app.js 之后加载，renderTab 已启动）
// hash 格式：#lab?sub={labSubMode}（列表页保位）或 #lab/{strategyKey}（详情页）或 #lab（旧版默认 single）
(function _labInitHashRestore() {
  const h = location.hash;
  if (!h || !h.startsWith("#lab")) return;
  _labInitialRestore = true;
  state.tab = "lab";
  // 分离 path 与 query：#lab?sub=fusion -> path="lab", query="sub=fusion"
  //                     #lab/Supertrend_buy -> path="lab/Supertrend_buy", query=""
  const qIdx = h.indexOf("?");
  const pathPart = qIdx >= 0 ? h.slice(1, qIdx) : h.slice(1);
  const queryPart = qIdx >= 0 ? h.slice(qIdx + 1) : "";
  const parts = pathPart.split("/"); // "lab/key" -> ["lab", "key"]
  if (parts[1] && LAB_STRATEGIES[parts[1]]) {
    state.labStrategy = parts[1];
  }
  // 解析 ?sub= 恢复 labSubMode（列表页保位，避免 F5 回 single）
  if (queryPart) {
    const sub = new URLSearchParams(queryPart).get("sub");
    if (sub && ["single", "fusion", "retest", "ablation", "symmetry", "paramscan", "custom", "aiscore"].includes(sub)) {
      state.labSubMode = sub;
    }
  }
  // 激活 lab tab 按钮 -> 触发 renderTab -> renderSignalLab/renderLabDetail
  setTimeout(() => {
    const labBtn = document.querySelector('button[data-tab="lab"]');
    if (labBtn) labBtn.click();
  }, 0);
})();
