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
// ATR(14) 追踪风控：trail = 近20日最高close - 3×ATR(14)
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
// 文案来源：买风险点策略深度回测.md（重跑于 2026-07-11，244资产全史/近10年/近5年/近3年/近1年 × 5d/10d/20d/60d）
// zone: buy=候选关注点 / sell=候选风险点 / excluded=已排除 / prod=生产参考
// status: live=已上线生产 / experimental=实验中 / dev=开发中 / excluded=已排除
const LAB_STRATEGIES = {
  // --- 候选关注点区（7个） ---
  BB_lower_revert: {
    name: "下轨拐点买", side: "buy", zone: "prod", status: "partial",
    trigger: "前一日收盘价跌破布林带下轨，当日收盘价收回下轨之上（超卖反弹）",
    conclusion: "3/4窗口达标并列靠前，近3年60d盈亏比1.84较高，与C1语义互补",
    theory: "布林带下轨回归。价格跌破下轨后收回，意味超卖极端已过、反弹拐点出现。与C1同为「超卖反弹」语义，但用价格穿越布林带下轨而非相对强弱指标(RSI)阈值，强势市更敏感。",
    scenario: "震荡市/下跌市超卖反弹；强势市中相对强弱指标未到30但价格已破下轨时补C1盲区。",
    note: "近1年是唯一达标关注点（52.1%/1.23），与C1互补性较高。实验中：已实现图表（收盘价+布林带轨道+绿色实验买标注），未写入signal_daily。",
    report: "回测报告：布林下轨回归买达标数3/4（近10年/近3年/近1年），与C1并列靠前。近3年60d盈亏比1.79、均值+4.7%为关注点较高。近1年（强势单边市）是唯一达标关注点，补强C1在强势市的盲区。语义与C1正交（价格穿越 vs 相对强弱阈值），适合做互补关注点。",
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
    trigger: "5日均线上穿20日均线（短期金叉关注点）",
    conclusion: "1/4达标，信号密集胜率平庸",
    theory: "双均线金叉。短期均线上穿长期均线意味短期动量转强，经典趋势确认信号。",
    scenario: "趋势确认入场；震荡市频繁假金叉。",
    note: "信号最多（全史30754），但近3年胜率49.8%接近随机。60d盈亏比1.75较高。",
    report: "回测报告：均线5/20金叉买仅全史达标（1/4），近3年10d胜率49.8%接近随机。信号密集（全史30754个），胜率平庸。近3年60d盈亏比1.75、均值+4.9%是唯一亮点。",
  },
  MA_golden_10_60: {
    name: "均线10/60金叉买", side: "buy", zone: "buy", status: "experimental",
    trigger: "10日均线上穿60日均线（中长期金叉关注点）",
    conclusion: "2/4达标，滞后严重",
    theory: "中长期双均线金叉。10日均线上穿60日均线确认中长期趋势转多，但60日均线滞后严重。",
    scenario: "中长期趋势确认；信号滞后，入场点偏晚。",
    note: "近3年胜率47.1%低于50%。全史样本11809较少。",
    report: "回测报告：均线10/60金叉买全史+近1年达标（2/4），近3年胜率47.1%低于50%。60日均线滞后严重，信号少且入场偏晚。全史60d均值+2.1%。",
  },
  MACD_golden: {
    name: "MACD金叉买", side: "buy", zone: "buy", status: "experimental",
    trigger: "差离值(DIF)上穿信号线(DEA)（MACD金叉关注点）",
    conclusion: "1/4达标，信号最多但平庸",
    theory: "MACD金叉。差离值(DIF)上穿信号线(DEA)意味短期动量强于长期，经典趋势确认。MACD(12,26,9)业界标准参数。",
    scenario: "趋势确认入场；震荡市假金叉多。",
    note: "信号全史最多（38930），但近3年胜率49.1%接近随机。",
    report: "回测报告：MACD金叉买仅全史达标（1/4），近3年10d胜率49.1%接近随机。信号全史最多（38930个），但胜率平庸。近3年60d盈亏比1.76、均值+4.6%。",
  },
  // --- 候选风险点区（7个） ---
  BB_upper_revert: {
    name: "布林上轨回落卖", side: "sell", zone: "sell", status: "experimental",
    trigger: "前一日收盘价突破布林带上轨，当日收盘价回落至上轨下方（短周期收益兑现）",
    conclusion: "近3年5d/10d胜率居前(57%/54%)，与D1(20d较强)时间维度互补",
    theory: "布林带上轨回归。价格从上轨上方回落至下方，意味超买极端已过、短周期收益兑现拐点。与D1的「20日高回落5%」时间维度互补。",
    scenario: "短周期收益兑现/调整提示；与D1（20d较强）双重确认。",
    note: "实验中，已实现图表（收盘价折线+布林带轨道+紫色实验卖标注）。未写入signal_daily。",
    report: "回测报告：布林上轨回落卖近3年5d胜率56.8%/10d胜率54.1%为风险点较高，短周期收益兑现较强。但样本仅5549（D1一半），20d后衰减。适合做D1的短周期互补（候选C）。全史PL0.87<1（风险点结构性问题），但方向胜率居前。",
  },
  MA_death_5_20: {
    name: "均线5/20死叉卖", side: "sell", zone: "sell", status: "experimental",
    trigger: "5日均线下穿20日均线（短期死叉风险点）",
    conclusion: "近3年20d胜率56.3%较高，短周期偏弱但中周期强",
    theory: "双均线死叉。短期均线下穿长期均线意味短期动量转弱，经典趋势转弱确认。",
    scenario: "趋势转弱调整；震荡市频繁假死叉。",
    note: "近3年20d胜率54.8%较高，但5d/10d偏弱。PL0.90<1。实验中：已实现图表（收盘价+5日/20日均线+紫色实验卖标注），未写入signal_daily。",
    report: "回测报告：均线5/20死叉卖近3年20d胜率54.8%为风险点较高，10d胜率53.2%。均值-0.1%（方向正确）。但5d/10d偏弱，PL0.90<1（风险点结构性问题）。",
  },
  BB_middle_break: {
    name: "跌破布林中轨卖", side: "sell", zone: "sell", status: "experimental",
    trigger: "收盘价跌破布林中轨（20日均线），中轨破位卖",
    conclusion: "中规中矩，PL偏低",
    theory: "布林中轨破位。中轨=20日均线，跌破意味价格回到均线下方，趋势转弱确认。",
    scenario: "趋势转弱确认调整；信号密集。",
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
    scenario: "中期趋势破位调整；信号较稀疏。",
    note: "近3年10d胜率51.8%、PL0.88。全史PL0.94相对高。",
    report: "回测报告：跌破20日最低卖近3年10d胜率51.8%、PL0.88。全史PL0.94为风险点相对高，但整体平庸。样本7533。",
  },
  MACD_death: {
    name: "MACD死叉卖", side: "sell", zone: "sell", status: "experimental",
    trigger: "差离值(DIF)下穿信号线(DEA)（MACD死叉风险点）",
    conclusion: "PL0.79偏低",
    theory: "MACD死叉。差离值(DIF)下穿信号线(DEA)意味短期动量弱于长期，经典趋势转弱确认。MACD(12,26,9)业界标准。",
    scenario: "趋势转弱调整；震荡市假死叉多。",
    note: "近3年10d胜率51.8%，PL0.83偏低。样本6844较大。",
    report: "回测报告：MACD死叉卖近3年10d胜率51.8%、PL0.83偏低。样本6844。信号密集但PL偏低，风险点结构性问题突出。",
  },
  ATR_trail_stop: {
    name: "真实波幅追踪风控卖", side: "sell", zone: "sell", status: "experimental",
    trigger: "收盘价 < 近20日最高收盘价 − 3×真实波幅ATR(14)（追踪风控）",
    conclusion: "胜率刚过50%",
    theory: "真实波幅(ATR)追踪风控。基于波动率的动态风控线，价格跌破意味趋势已反转。真实波幅(ATR)自适应波动率。",
    scenario: "趋势跟踪风控；波动率大时风控线更宽。",
    note: "近3年10d胜率51.1%，PL0.86。全史PL0.96相对高。",
    report: "回测报告：真实波幅追踪风控卖近3年10d胜率51.1%、PL0.86。全史PL0.96为风险点较高之一。追踪风控型信号，胜率刚过50%。",
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
    report: "回测报告：相对强弱下穿70卖 0/4达标，全史10d胜率48.7%/PL0.84/均值+0.9%（方向相反，信号后价格仍涨）。是所有风险点中最差的，旧基线已弃，改用D1。",
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
    report: "回测报告：超级趋势翻空卖 全史唯一PL≥1（0.95接近1，胜率51.9%），但近3年10d胜率48.9%/PL0.85失效。近年A股向上漂移致趋势跟踪风险点失效，明确排除。",
  },
  // --- 生产参考区（2个） ---
  C1_RSI30: {
    name: "超卖拐点买", side: "buy", zone: "prod", status: "live",
    trigger: "RSI(14) 从 ≤30 升回 >30 那天（超卖结束、价格有望反弹）",
    conclusion: "3/4达标，结构较稳健，当前主关注点",
    theory: "相对强弱指标(RSI)经典超卖回归。相对强弱指标(RSI)≤30表示超卖，升回30之上意味空头力量衰竭、反弹拐点出现。事件化（仅穿越当日标）。",
    scenario: "震荡市/下跌市超卖反弹；通用主关注点。按指数可收紧阈值至相对强弱指标上穿25（kc50/电力设备/传媒已配）。",
    note: "已上线生产。signal='buy'。近3年全持有期胜率>50%，盈亏比随持有期单调上升。",
    report: "回测报告：相对强弱上穿30买 达标数3/4（全史/近10年/近3年）并列靠前。近3年全持有期胜率>50%（5d54.2%/10d52.6%/20d56.5%/60d55.0%），盈亏比随持有期单调上升（1.38->1.17->1.52->1.68），60d均值+5.3%。结构较稳健，当前主用关注点（回测表现较稳）。",
  },
  D1_high20_drop5: {
    name: "趋势转弱卖", side: "sell", zone: "prod", status: "live",
    trigger: "收盘价从近20日最高价回落 5%（前日≥阈 且 当日<阈），且收盘价>60日均线，且差离值<信号线",
    conclusion: "20d胜率55.7%样本最大，当前主风险点",
    theory: "基于最高价的回落收益兑现。从20日最高价回落5%意味趋势转弱，叠加60日均线多头过滤+MACD死叉确认。反应型信号（不预测顶部，反应已发生的弱势）。",
    scenario: "趋势转弱/收益兑现调整提示；非做空/反向交易指令。胜率≈50%接近随机，不可作独立留意高位预警指令。",
    note: "已上线生产。signal='sell'。风险点本质难预测（PL<1），D1是「最不坏」方案非「好」方案。",
    report: "回测报告：20日高回落5%卖 近3年20d胜率55.9%为风险点较高，样本9873最大（统计最稳）。10d均值-0.1%（方向正确）。盈亏比0.86<1（风险点结构性问题：A股向上漂移），但在所有风险点中PL仍属前列。维持现状合理，是「最不坏」方案。",
  },
};

// 策略释义映射（tooltip 悬停显示中文释义，仅展示用不改后端key）
const _LAB_STRAT_EN = {
  Supertrend_buy: "趋势转向买", Supertrend_sell: "超级趋势翻空卖",
  B0_RSI70: "相对强弱下穿70卖", C1_RSI30: "超卖拐点买",
  MA_golden_5_20: "均线5/20金叉买", MA_golden_10_60: "均线10/60金叉买",
  MA_death_5_20: "均线5/20死叉卖", ATR_trail_stop: "真实波幅追踪风控卖",
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
    conclusion: "主项目生产风险点核心。降噪39%（风险点59830→36289），加MACD后历史回测正期望强度18.3%→43.3%",
    theory: "多信号融合风险点。20日高回落5%捕捉趋势转弱，叠加60日均线多头过滤（确保在上升趋势中收益兑现而非下跌中加空）和MACD死叉确认（动量转弱）。三条件同日同时满足，大幅降噪。",
    scenario: "上升趋势中回落收益兑现/调整；三条件共振过滤假信号。非做空指令。",
    note: "主项目生产风险点核心。加MACD后降噪39%（风险点59830→36289），历史回测正期望强度18.3%→43.3%。已上线signal_daily。",
    report: "回测：加MACD死叉后信号从59830降至36289（降噪39%），历史回测正期望强度从18.3%升至43.3%，信号质量显著提升。主项目生产风险点“20日高回落5%卖”的融合形态。",
  },
  F_D1_S1: {
    name: "D1回落5%+60日均线多头（豁免MACD） 融合卖", side: "sell", zone: "prod", status: "live",
    conditions: ["20日高回落5%", "60日均线多头"],
    trigger: "同日同时满足：20日高回落5% + 60日均线多头（豁免MACD）",
    conclusion: "主项目s.*情绪分变体。对比“D1回落5%+60日均线多头+MACD死叉融合卖”可看MACD过滤的增益",
    theory: "D1回落5%+60日均线多头双条件融合。豁免MACD条件，因s.*情绪分序列加MACD后样本从106降至7，不足统计。用于对比“D1回落5%+60日均线多头+MACD死叉融合卖”可单独看MACD过滤的增益。",
    scenario: "s.*情绪分变体的融合风险点；与“D1回落5%+60日均线多头+MACD死叉融合卖”对比MACD过滤增益。",
    note: "主项目s.*情绪分变体。加MACD后样本n=106→7不足，故豁免MACD。",
    report: "回测：s.*情绪分变体的基础形态（不含MACD）。对比“D1回落5%+60日均线多头+MACD死叉融合卖”可看MACD过滤的增益效果。",
  },
  // --- 候选关注点区（3个） ---
  F_B1_RSI40: {
    name: "布林下轨回归+相对强弱上穿40 融合买", side: "buy", zone: "candidate_buy", status: "partial",
    conditions: ["布林下轨回归", "相对强弱上穿40"],
    trigger: "同日同时满足：布林下轨回归 + 相对强弱上穿40",
    conclusion: "主项目10指数已配置 buy_aux rsi_cross_40。正期望强度 -38.5%->+16.2%转正（家电/轻工回测），胜率44.8%->54.5%，盈亏比0.66->1.19",
    theory: "多信号融合关注点。布林下轨回归捕捉超卖反弹拐点，叠加相对强弱上穿40确认动量转强。两条件同日同时满足，过滤单一布林下轨穿越的假信号。",
    scenario: "超卖反弹+动量确认共振入场；震荡市/下跌市效果好。",
    note: "已作为 buy_aux 辅关注点（per-index 增强）上线于 10 个指数：中证1000/创业板指/家电/轻工/医药/公用事业/房地产/社会服务/传媒/通信。非全局融合信号生产实现（B1基线+相对强弱上穿40过滤，signals.py:312-314）.",
    report: "回测：加相对强弱上穿40后正期望强度从-38.5%转正至+16.2%（家电/轻工样本），胜率44.8%->54.5%，盈亏比0.66->1.19。已扩展至10指数配置。",
  },
  F_B1_rebound2pct: {
    name: "布林下轨回归+反弹2% 融合买", side: "buy", zone: "candidate_buy", status: "partial",
    conditions: ["布林下轨回归", "反弹2%"],
    trigger: "同日同时满足：布林下轨回归 + 反弹2%（收盘价高于下轨2%）",
    conclusion: "主项目8指数已配置 buy_aux close_above_bl_2pct。正期望强度 -21%->+20%转正（基础化工回测），5d/10d/20d三horizon一致，n=19<30样本警示",
    theory: "多信号融合关注点。布林下轨回归捕捉超卖反弹，叠加反弹2%过滤（close>下轨*1.02），过滤勉强穿越假信号和死猫反弹。",
    scenario: "超卖反弹确认入场；过滤假突破/死猫反弹。",
    note: "已作为 buy_aux 辅关注点（per-index 增强）上线于 8 个指数：农林牧渔/基础化工/电子/纺织服饰/交通运输/机械设备/国防军工/计算机。非全局融合信号生产实现（B1基线+反弹2%过滤，signals.py:315-318）.",
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
  // --- 候选风险点区（1个） ---
  F_D1_MA_death: {
    name: "D1回落5%+均线5/20死叉 融合卖（实验性新组合）", side: "sell", zone: "candidate_sell", status: "experimental",
    conditions: ["20日高回落5%", "均线5/20死叉"],
    trigger: "同日同时满足：20日高回落5% + 均线5/20死叉",
    conclusion: "实验性新组合。回落+均线死叉共振，待回测验证",
    theory: "实验性新组合。20日高回落5%捕捉趋势转弱，叠加均线5/20死叉确认均线转弱。两条件同日同时满足共振。",
    scenario: "趋势转弱+均线死叉共振调整；实验性，待回测验证。",
    note: "实验室新组合，非主项目提取。需阶段二回测验证是否有价值。",
    report: "实验性新组合，暂无回测数据。阶段二将验证回落+均线死叉共振的有效性。",
  },
};

// === 策略实验室术语词典（白话解释，统一入口）===
// key -> { name: 术语名, desc: 白话释义 }。_labHelpIcon(termKey) 与 ❓词典modal 共用此表。
const _LAB_GLOSSARY = {
  co_resonance: {
    name: "同向共振（双买/双卖共振）",
    desc: "两个同方向（都买或都卖）的信号在同一天同时触发才算有效。双买共振=两个关注点同日触发，关注点更可靠；双卖共振=两个风险点同日触发，风险点更确认。与“配对”（一买一卖组完整交易）不同，共振是同向叠加增强。本实验室把7个候选关注点两两组合（C(7,2)=21对）、7个候选风险点两两组合（21对）自动回测。",
  },
  fusion_signal: {
    name: "融合信号（F_ 前缀）",
    desc: "把多个单一信号用“同日同时满足”组合成一个新信号——所有条件同日都满足才触发，用多条件共振过滤假信号。分两类：①6个预定义（F_开头，主项目提取已验证）；②运行时自动两两组合的候选（待回测）。与同向共振区别：融合是异向多条件同时满足成新策略，同向共振是同向两信号叠加。",
  },
  pair: {
    name: "配对（关注点+风险点）",
    desc: "一个关注点信号+一个风险点信号组成一对完整交易（关注低位机会→留意高位预警算一笔）。7买×7卖=49对。配对回测=按这对信号模拟历史交易，算净值曲线/胜率/回撤。",
  },
  score: {
    name: "综合评分（0-100）",
    desc: "0-100分=收益率(35%)+胜率(25%)+回撤倒数(15%)+风险调整(15%)+样本量(10%)，收益/胜率/回撤/风险调整先缩尾处理(winsorize,前后1%截断)抗极端值再min-max归一化到[0,1]，样本量用凹函数1-exp(-n/30)抗大样本线性通胀，加权后×100，越高越综合优秀。1:1例（真实配对）：科创50·唐奇安20上轨买×MACD死叉卖整体五维=收益率归一1.00、胜率归一0.96、回撤倒数0.67、风险调整归一1.00、样本量凹函数0.41→0.35×1.00+0.25×0.96+0.15×0.67+0.15×1.00+0.1×0.41=0.88（核实源=lab_retest_kc50.json）。",
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
    desc: "Calmar比率=年化收益率÷最大回撤，分母下限2%（回撤极小时保守视作2%，避免微小回撤算出虚高分）。衡量“每承受1%回撤能换多少收益”，越高越好，比单看收益更能反映风险性价比。1:1例：年化10%、最大回撤5%→Calmar=2.0，即每承受1个点的回撤换来2个点的年化收益（示例数值）。",
  },
  profit_factor: {
    name: "利润因子（Profit Factor）",
    desc: "总盈利笔收益和÷总亏损笔收益和绝对值。>1盈利系统，>2优秀。全胜（无亏损笔）时显示∞。百分比口径与胜率同源。1:1例：总盈利18块÷总亏损10块=1.8，即总赚1.8块对总亏1块（示例数值）。",
  },
  payoff_ratio: {
    name: "盈亏比（Payoff Ratio）",
    desc: "平均盈利÷平均亏损绝对值。如1.5=每笔赚的是亏的1.5倍。高盈亏比可弥补低胜率。全胜时显示∞。1:1例：平均每笔盈利150元÷平均每笔亏损100元=1.5，即每亏1块钱赚1.5块钱（示例数值）。",
  },
  sharpe: {
    name: "夏普比率（Sharpe）",
    desc: "年化夏普=收益率均值÷标准差×√252（无风险利率0）。衡量每承担1单位总波动换多少超额收益，>1尚可，>2优秀。基于事件点收益率近似（与回撤同源非完整日K）。1:1例：夏普1.5=每承担1单位波动换1.5单位超额收益（示例数值）。",
  },
  sortino: {
    name: "索提诺比率（Sortino）",
    desc: "年化索提诺=收益率均值÷下行波动×√252。与夏普类似但只计下行风险（亏损方向波动），对“上涨波动”不惩罚，比夏普更贴合投资者真实感受，通常≥夏普。1:1例：同是年化10%、只算下跌波动时风险更小→索提诺往往比夏普更高，如夏普1.5、索提诺1.8，下跌波动越小数值越漂亮（示例数值）。",
  },
  expectancy: {
    name: "期望值（Expectancy）",
    desc: "单笔期望收益率%=胜率×平均盈利+败率×平均亏损。正值=长期每笔期望赚钱，负值=亏钱。综合胜率与盈亏比，是策略可行性的核心指标。1:1例：胜率60%×平均盈150元−败率40%×平均亏100元=+50元/笔，即长期每笔平均期望赚50元（示例数值）。",
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
    desc: "稳健性验证三件套：①分年回测-防某年暴利拉高整体 ②样本外-前70%训练后30%验证防过拟合 ③极端行情-2015股灾/2018熊/2020疫情/2024反弹各场景回撤。优先做这3种因其为验证核心，成本低结论明确。⭐️进入规则:近5/3/1年三窗口最大回撤均≤10%且交易≥10次，且(综合评分≥0.6 且 胜率≥55% 且 风险调整≥1.5)三者同时满足(AND收紧)。1:1例(科创50·唐奇安20上轨买×MACD死叉卖,核实源=lab_retest_kc50.json)：2020疫情回撤2.0%、2024反弹+19.25%、样本外后30%验证+135.8%胜率88.9%、逐年全为正→三件套全稳标⭐️(回撤4.3%≤10%、交易16≥10、综合分0.84≥0.6、胜率87.5%≥55%、风险调整5.35≥1.5)。",
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
// 从 LAB_STRATEGIES 取候选关注点7个 + 候选风险点7个，生成三类候选：
// 1) 买×卖配对：7×7=49，zone=candidate_buy
// 2) 买×买共振：C(7,2)=21，zone=candidate_buy
// 3) 卖×卖共振：C(7,2)=21，zone=candidate_sell
function _generateFusionCandidates() {
  // 提取候选关注点和风险点
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
    if (n.includes("真实波幅")) return "真实波幅风控";
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
        conclusion: `配对候选：${buy.name} 作为关注点 + ${sell.name} 作为风险点，待回测验证效果`,
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
  // 候选关注点
  BB_lower_revert: 1, Supertrend_buy: 1, Donchian20_up: 1, Donchian55_up: 1,
  MA_golden_5_20: 1, MA_golden_10_60: 1, MACD_golden: 1,
  // 候选风险点
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
  ATR: { name: "真实波幅", en: "Average True Range", plain: "衡量波动剧烈程度，数值越大波动越猛。追踪风控线=近期高点-3倍ATR，跌破即风控。" },
  Drop5: { name: "20日高回落5%", plain: "近20日最高价下跌5%触发收益兑现。回落阈值线会随创新高而上移。" },
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
  const statLabel = isBuy ? "关注点" : "风险点";

  if (key === "BB_upper_revert") {
    const bb = computeBBLab(ohlc);
    return {
      indicators: [
        { name: "布林上轨", data: bb.bu, color: cssVar('--text-4'), dash: true },
        { name: "布林下轨", data: bb.bl, color: cssVar('--text-4'), dash: true },
      ],
      signals: bb.signals, signalLabel, signalColor: "#9c27b0",
      chartTitle: `${name} · 布林上轨回落实验`, statLabel: "实验风险点",
    };
  } else if (key === "BB_lower_revert") {
    const r2 = computeBBLowerRevertLab(ohlc);
    return {
      indicators: [
        { name: "布林上轨", data: r2.bu, color: cssVar('--text-4'), dash: true },
        { name: "布林下轨", data: r2.bl, color: cssVar('--text-4'), dash: true },
      ],
      signals: r2.signals, signalLabel, signalColor: "#2e7d32",
      chartTitle: `${name} · 布林下轨回归实验`, statLabel: "实验关注点",
    };
  } else if (key === "Supertrend_buy") {
    const r2 = computeSupertrendLab(ohlc);
    return {
      indicators: [
        { name: "趋势线(多)", data: r2.stBull, color: "#2e7d32", dash: false },
        { name: "趋势线(空)", data: r2.stBear, color: "#c92a2a", dash: false },
      ],
      signals: r2.signals, signalLabel, signalColor: "#2e7d32",
      chartTitle: `${name} · 趋势转向实验`, statLabel: "实验关注点",
    };
  } else if (key === "MA_death_5_20") {
    const r2 = computeMADeathCrossLab(ohlc);
    return {
      indicators: [
        { name: "5日均线", data: r2.ma5, color: "#1f6feb", dash: false },
        { name: "20日均线", data: r2.ma20, color: "#f0883e", dash: false },
      ],
      signals: r2.signals, signalLabel, signalColor: "#9c27b0",
      chartTitle: `${name} · 均线5/20死叉实验`, statLabel: "实验风险点",
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

  // --- ATR 追踪风控 ---
  if (key === "ATR_trail_stop") {
    const r = computeATRTrailLab(ohlc);
    return {
      indicators: [{ name: "真实波幅追踪风控线", data: r.trail, color: "#c92a2a", dash: true }],
      signals: r.signals, signalLabel, signalColor: sigColor,
      chartTitle: `${name} · 真实波幅追踪风控`, statLabel,
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
      statLabel: isBuy ? '融合关注点' : '融合风险点',
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
    state.labFusionMatrixDataMap[idx] = await fetchJSON("https://ss.fx8.store/r2/lab/lab_backtest_fusion_" + idx + ".json");
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
    state.labData = await fetchJSON("https://ss.fx8.store/r2/lab/lab_backtest.json");
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
    state.labMatrixDataMap[idx] = await fetchJSON("https://ss.fx8.store/r2/lab/lab_backtest_" + idx + ".json");
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
    state.labSimDataMap[index] = await fetchJSON("https://ss.fx8.store/r2/lab/lab_sim_" + index + "_stats.json");
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
    state.labSimFusionDataMap[index] = await fetchJSON("https://ss.fx8.store/r2/lab/lab_sim_" + index + "_fusion_stats.json");
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
    // perf批一 P8-D(2026-08-24): 补 timeoutMs=60000, 有进度+abort 但原无超时, 弱网挂起可自救。
    const full = await fetchJSONProgress("https://ss.fx8.store/r2/lab/lab_sim_" + index + "_fusion_full.json", onProgress, signal, 60000);
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
    state.labRetestDataMap[index] = await fetchJSON("https://ss.fx8.store/r2/lab/lab_retest_" + index + ".json");
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
    state.labRetestHonors = await fetchJSON("https://ss.fx8.store/r2/lab/lab_retest_honors.json");
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
// timeoutMs(perf批一 P8-D 2026-08-24): 可选超时(ms), 大文件 _full.json 弱网防永久挂起; 不传=原行为零变化。
// 超时/外部 signal 取消统一走内部 controller abort(AbortError 向上抛不降级); fallback fetchJSON 透传同额超时。
async function fetchJSONProgress(url, onProgress, signal, timeoutMs) {
  // 2026-08-01 全部跳过 .gz，统一走 .json + CF br 压缩（与 app.js fetchJSON 同步，根治 CF .gz 4h edge 缓存滞后）
  // .gz fallback 逻辑保留(防御性), 但 tryGz=false 时 gzUrl=null 不触发。
  const _qIdx = url.indexOf("?");
  const _base = _qIdx >= 0 ? url.slice(0, _qIdx) : url;
  const _query = _qIdx >= 0 ? url.slice(_qIdx) : "";
  const tryGz = false;
  const gzUrl = tryGz ? _base + ".gz" + _query : null;
  // 超时装配: 仅传了 timeoutMs 才接管信号(内部 controller 链接外部 signal, 任一触发都 abort)
  const _useTimeout = timeoutMs && timeoutMs > 0;
  const _timeoutCtrl = new AbortController();
  const _ctrlAbort = () => _timeoutCtrl.abort();
  let _timer = null, _timedOut = false, _onOuterAbort = null;
  if (_useTimeout) {
    if (signal) {
      if (signal.aborted) _ctrlAbort();
      else {
        _onOuterAbort = _ctrlAbort;
        signal.addEventListener("abort", _onOuterAbort);
      }
    }
    _timer = setTimeout(() => { _timedOut = true; _ctrlAbort(); }, timeoutMs);
  }
  const _sig = _useTimeout ? _timeoutCtrl.signal : signal;
  try {
    const fetchUrl = gzUrl || url;
    const resp = await fetch(fetchUrl, _sig ? { signal: _sig } : undefined);
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
    if (e && e.name === "AbortError") {
      // perf批一 P8-D: 超时触发的 abort 记日志便于排查弱网问题(外部手动取消不打扰)
      if (_timedOut) console.error("fetchJSONProgress timeout (" + timeoutMs + "ms): " + url);
      throw e; // 中止不降级，向上抛
    }
    // .gz 失败(404/解压错/不支持) -> fallback 原 .json 走 fetchJSON (透传同额超时)
    if (gzUrl) {
      if (onProgress) onProgress(-1, 0);
      return fetchJSON(url, timeoutMs);
    }
    // 流式读取失败（如浏览器不支持），降级普通 fetch (透传同额超时)
    if (onProgress) onProgress(-1, 0);
    return fetchJSON(url, timeoutMs);
  } finally {
    // perf批一 P8-D: 清理超时定时器+外部 signal 监听(所有返回路径统一走 finally, 防泄漏)
    if (_timer) clearTimeout(_timer);
    if (_onOuterAbort && signal) signal.removeEventListener("abort", _onOuterAbort);
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
    // perf批一 P8-D(2026-08-24): 补 timeoutMs=60000(同 fusion_full 点)。
    const full = await fetchJSONProgress("https://ss.fx8.store/r2/lab/lab_sim_" + index + "_full.json", onProgress, signal, 60000);
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
  // 字段对齐已成交行12列:品种/#/关注低位机会日/关注价/留意高位预警日/风险价/收益率/持有/账户资金/累计盈亏/累计收益率/较上次
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
      `<div class="lab-sim-table-wrap"><table><thead><tr><th>品种</th><th>#</th><th>关注日期</th><th>关注价</th><th>风险日期</th><th>风险价</th><th>收益率</th><th>持有</th><th>账户总资金(元)</th><th>累计盈亏(元)</th><th>累计收益率</th><th data-tip="累计盈亏=账户资金−初始本金(1万)；累计收益率=累计盈亏÷初始本金×100%；较上次=本笔累计收益率/累计盈亏(元)相较上一笔的差值，红赚绿亏(首笔显示-)。例(上证「BB下轨反抽×MACD死叉」固定1万·近5年)：①2021-10-29买3537.07、12-20卖,本笔+1.6%,账户100,319.65(累计盈亏+319.65、累计收益率+0.32%),较上次=-(首笔)；②2022-01-17买、02-14卖,本笔-1.6%,账户99,999.16(累计-0.84、累计收益率-0.00%),较上次=收益率差-0.32pp、盈亏差-320.49元(绿亏)【核实源:lab_sim_sh_full.json win_trades.y5】">较上次</th></tr></thead><tbody>` +
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
      `<div class="lab-cost-warn">⚠ 以上为<strong>毛收益</strong>,未计手续费/滑点。计入成本后<strong>总收益</strong>约降 ${loDecay || "?"}~${hiDecay || "?"}%(折算年化约降 0.4~5.4 个百分点,视成本档与策略而定,见下表年化列)【核实源:lab_cost_compare.json】</div>` +
      `<table class="lab-cost-table"><thead><tr><th>成本档</th><th>手续费</th><th>滑点</th><th>年化</th><th>总收益</th><th>胜率</th></tr></thead><tbody>` +
      `<tr><td>毛收益</td><td>-</td><td>-</td><td>${fmtPct(g.annual_ret)}</td><td>${fmtPct(g.total_ret)}</td><td>${g.win_rate != null ? g.win_rate + "%" : "-"}</td></tr>` +
      `<tr><td>低档</td><td>万3</td><td>千1</td><td>${fmtPct(lo.annual_ret)}</td><td>${fmtPct(lo.total_ret)}</td><td>${lo.win_rate != null ? lo.win_rate + "%" : "-"}</td></tr>` +
      `<tr><td>高档</td><td>万5</td><td>千2</td><td>${fmtPct(hi.annual_ret)}</td><td>${fmtPct(hi.total_ret)}</td><td>${hi.win_rate != null ? hi.win_rate + "%" : "-"}</td></tr>` +
      `</tbody></table>` +
      `<div class="lab-cost-note">成本档说明：低档=万3手续费+千1滑点(ETF/低费率)；高档=万5手续费+千2滑点(个股常规)。高频策略成本侵蚀更大。例(上证「Donchian20突破×MACD死叉」全仓进出·全史,看下表毛/低/高三行年化列)：毛年化 +20.4% → 含费低档 +18.9% → 高档 +17.5%,逐档约降 1.5~2.9 个百分点(手续费/滑点越重侵蚀越多)【核实源:lab_cost_compare.json】</div>` +
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
    ? "每次全仓关注低位机会留意高位预警，本金复利滚动，收益和风险都放大"
    : "每次固定关注低位机会1万元分批建仓，卖信号防范风险，风险更分散";
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

  // 配对买风险点描述（策略卡与数据卡片之间的内容隔断 + 当前配对标注）
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
    const idxName = (_INDEX_NAME_MAP[simIdxId] || (simData && simData.index_name) || "该指数");
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
  const pairSideLabel = side === "buy" ? "风险点" : "关注点";

  // 上区：全仓交易策略 / 下区：定额（10%）交易策略（各自独立配对切换+详情）
  const fiSection = _labSimSectionHTML("full_in", simData, key, side, pairKeys, defaultPair, initCapital, pairSideLabel);
  const fkSection = _labSimSectionHTML("fixed_10k", simData, key, side, pairKeys, defaultPair, initCapital, pairSideLabel);

  // 窗口切换 tabs（默认近1年）
  const winLabel = LAB_WIN_DEFS.find((w) => w.k === (state.labSimWindow || "y5"));
  const idxName = (_INDEX_NAME_MAP[simIdxId] || simData.index_name || "");
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
    `<div><b>看「二次测试」三切片是否稳健</b>：标⭐️的配对可进入二次测试，看①分年回测（防某年暴利拉高）②样本外（防过拟合）③极端行情（2015股灾/2018熊/2020疫情/2024反弹各场景回撤），三者都稳才是真稳健，非偶然。` +
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
    `<span class="lab-tag-side">${meta.side === "buy" ? "关注点" : "风险点"}</span>`;
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
      const r = await fetchJSON(`https://ss.fx8.store/r2/index/${state.labIndex}-all.json`);
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
    '<div class="lab-matrix-source">数据来源：买风险点策略深度回测（基于历史数据验证）</div>' +
    '<div class="lab-matrix-note"><b>这张表怎么测的：</b>信号触发当天按收盘价关注低位机会，持有 N 个交易日后按收盘价留意高位预警，统计所有历史信号的平均效果。5d/10d/20d/60d = 持有 5/10/20/60 个交易日。<b>关注点胜率</b>=信号后上涨占比；<b>风险点胜率</b>=信号后下跌占比（方向相反）。<b>这是单边统计</b>（每个信号独立看 N 日后涨跌），不是配对交易；真实配对实战收益见下方模拟回测。</div>' +
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
    if (srcEl) srcEl.textContent = '数据来源：买风险点策略深度回测（' + _matrixIdxName(mIdx) + '，基于历史数据验证' + (mGenAt ? '，重跑于 ' + mGenAt : '') + '）';
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

  // 模拟回测卡片（配对交易 + 净值曲线 + 交易记录 + 关注点切换 + 模式切换 + 分页 + 指数切换）
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
  return `<span class="lab-rank-quality" title="质量指标(点页内❓查词典): 盈亏比=平均盈利/平均亏损; 利润因子=总盈利/总亏损; 夏普/索提诺=年化风险调整收益(索提诺仅算下行波动); 期望值=单笔期望收益率%。例(上证「BB下轨反抽×BB中轨突破」全仓进出·全史,n=141笔): 胜率55.3%+盈亏比1.59+期望+2.38%怎么一起读→约10笔里5.5笔赚;赚的一笔平均是亏的一笔的1.59倍(赚的厚度盖过胜率不足);单笔平均期望+2.38%(三数都高=稳赚,胜率低但盈亏比高也ok)【核实源:lab_sim_sh_stats.json】">` +
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
    ? "综合评分 = 收益率(35%)+胜率(25%)+回撤倒数(15%)+风险调整(15%)+样本量(10%)，收益/胜率/回撤/风险调整先缩尾处理(winsorize,前后1%截断)抗极端值再min-max归一化，样本量用凹函数1-exp(-n/30)抗大样本通胀，加权×100越高越好。" + _labHelpIcon("score")
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
const _LAB_RETEST_RULE = "🔬 二次测试(稳健性验证三件套):①分年回测-防某年暴利拉高整体 ②样本外-前70%训练后30%验证防过拟合 ③极端行情-2015股灾/2018熊/2020疫情/2024反弹各场景回撤。优先做这3种因其为验证核心(通过/筛掉),成本低结论明确;其余7方向(蒙特卡洛/参数敏感/消融/手续费/多空/标的泛化)属优化/归因靠后。⭐️候选=近5/3/1年三窗口回撤均≤10%且交易≥10,且(综合分≥0.6 且 胜率≥55% 且 风险调整≥1.5 三者同时满足)。1:1例(科创50·唐奇安20上轨买×MACD死叉卖,核实源=lab_retest_kc50.json):①分年2020/21/22/23/24/25/26逐年+11.0%/+2.7%/+3.0%/+11.8%/+27.6%/+33.4%/+40.2%全为正,无某年暴利虚高;②样本外前70%训练16笔+32.7%,后30%验证9笔+135.8%胜率88.9%,验证段不崩=未过拟合;③极端行情2020疫情回撤2.0%、2024反弹+19.25%(2015股灾/2018熊市因科创50于2019才上市无交易,跳过不扣分)。三件套全稳→标⭐️:近5/3/1年回撤4.3%/4.3%/0%均≤10%、交易16≥10、综合分0.84≥0.6、胜率87.5%≥55%、风险调整5.35≥1.5。" + _labHelpIcon("retest");

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
    `<div class="lab-retest-meta">指数: ${_INDEX_NAME_MAP[idx] || rd.index_name || idx} · 生成: ${rd.generated_at || "-"} · ⭐️候选: ${starN} · 🔵替补: ${subN}${exhNote}</div>` +
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
    '<table class="lab-retest-oos"><thead><tr><th>指标</th><th>训练集</th><th>测试集</th></tr></thead>' +
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
    '<div class="lab-retest-section-title">③ 极端行情回撤（各场景表现）</div>' +
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
    const r = await fetchJSON(`https://ss.fx8.store/r2/index/${m.index}-all.json`);
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

// 量策略实验室 2/3 级 nav 实际高度写 CSS 变量 --lab-subnav-h / --lab-subnav-child-h（兜底 40px），
// 供 .lab-subnav-child / .lab-sigkelly-bar sticky top 层层叠加用（--tab-h 由 app.js initStickyOffset 量）。
let _labStickyResizeBound = false;
function labStickyOffset() {
  const set = () => {
    const subnav = document.querySelector('.lab-subnav');
    if (subnav) document.documentElement.style.setProperty('--lab-subnav-h', subnav.offsetHeight + 'px');
    const child = document.querySelector('.lab-subnav-child');
    if (child) document.documentElement.style.setProperty('--lab-subnav-child-h', child.offsetHeight + 'px');
  };
  set();
  // DOM 刚 append，下一帧再量一次兜底（字体/布局异步未定形时首测可能偏）
  requestAnimationFrame(set);
  if (!_labStickyResizeBound) {
    _labStickyResizeBound = true;
    window.addEventListener('resize', set);
    window.addEventListener('load', set);
  }
}

// 渲染策略实验主入口（分区tab + 卡片列表 / 详情页）
// === 二级导航（单一信号实验 / 融合信号实验）===
function _renderLabSubNav() {
  const cur = state.labSubMode || "single";
  const subNav = document.createElement("div");
  subNav.className = "lab-subnav";
  // 信号扫描(scan)为父tab，下挂3个三级子tab(信号拆解/多空对称/参数扫描)
  // 自定义分析(custom)为父tab，下挂2个三级子tab(AI预警/AI评分)
  const _LAB_SUB_TABS = [
    { key: "scan", label: "信号扫描" },
    { key: "experiment", label: "信号实验" },
    { key: "retest", label: "🔬 二次测试实验" },
    { key: "custom", label: "🎯 自定义分析" },
  ];
  const _SCAN_CHILDREN = ["ablation", "symmetry", "paramscan"];
  const _SCAN_CHILD_LABELS = { ablation: "🧩 信号拆解", symmetry: "⚖️ 多空对称", paramscan: "🎛 参数扫描" };
  const _EXPERIMENT_CHILDREN = ["single", "fusion"];
  const _EXPERIMENT_CHILD_LABELS = { single: "单一信号实验", fusion: "融合信号实验" };
  // custom 父tab 3级子tab: AI预警(原 custom 内容) + AI评分(原 aiscore 2级 tab 移入)
  const _CUSTOM_CHILDREN = ["aiwarn", "aiscore", "sigkelly"];
  const _CUSTOM_CHILD_LABELS = { aiwarn: "🚨 AI预警", aiscore: "📈 AI评分", sigkelly: "📊 信号凯利回测" };
  const isScanActive = _SCAN_CHILDREN.includes(cur);
  const isExperimentActive = _EXPERIMENT_CHILDREN.includes(cur);
  const isCustomActive = _CUSTOM_CHILDREN.includes(cur);
  subNav.innerHTML = _LAB_SUB_TABS.map((t) => {
    const active = t.key === "scan" ? isScanActive : t.key === "experiment" ? isExperimentActive : t.key === "custom" ? isCustomActive : cur === t.key;
    return `<button type="button" class="lab-subnav-tab${active ? " active" : ""}" data-sub="${t.key}">${t.label}</button>`;
  }).join("") +
  `<button type="button" class="lab-subnav-tab lab-subnav-glossary" data-glossary-btn="1">❓ 术语词典</button>`;
  subNav.querySelectorAll(".lab-subnav-tab").forEach((btn) => {
    btn.onclick = () => {
      // 术语词典按钮：打开词典modal，不切模式
      if (btn.dataset.glossaryBtn) { _labGlossaryOpenModal(); return; }
      // 父tab点击 -> 默认进第一个子tab(scan->ablation / experiment->single / custom->aiwarn)
      const sub = btn.dataset.sub;
      state.labSubMode = sub === "scan" ? "ablation" : sub === "experiment" ? "single" : sub === "custom" ? "aiwarn" : sub;
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

  // 三级子nav：自定义分析父tab active 时，在二级nav下方渲染一行子tab(AI预警/AI评分)
  if (isCustomActive) {
    const childNav = document.createElement("div");
    childNav.className = "lab-subnav lab-subnav-child";
    childNav.innerHTML = _CUSTOM_CHILDREN.map((k) =>
      `<button type="button" class="lab-subnav-tab${cur === k ? " active" : ""}" data-sub="${k}">${_CUSTOM_CHILD_LABELS[k]}</button>`
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
  // 2/3 级 nav 已渲染（含 sigkelly 所在的 custom 父 tab 三级子 nav），量高度写 CSS 变量供 sticky top 叠加
  labStickyOffset();
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
  renderPurposeNote(leftCol, PURPOSE_NOTES["lab.fusion"], {variant:"lab-sm"});
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
    '<div class="lab-rank-sub-note">一个关注点+一个风险点组成一对完整交易，7买×7卖=49对</div>' +
    `<div class="lab-win-bar"><span class="lab-win-bar-label">选择指数</span><div class="lab-win-tabs">${rankIdxBtns}</div></div>` +
    `<div class="lab-win-bar lab-shape-bar"><span class="lab-win-bar-label">形态分析</span><button type="button" class="lab-shape-btn" title="取近20日归一化日收益率，在全历史中滑窗匹配最相似时段">🔮 当前指数相似形态匹配</button><span class="lab-shape-hint">A10 · 历史相似时段 + 最相似1个延伸走势参考</span></div>` +
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
function _labRetestMinMax(rows, key, pctCap) {
  let vals = rows.map((r) => r[key]).filter((v) => v != null && !isNaN(v));
  if (vals.length === 0) return () => 0.5;
  // pctCap(0-1)分位截断抗极端离群值：超分位的钳到分位值再算 min/max，防单个离群值压平整个 min-max 归一化。
  // 与全站 _labWinsor 抗极端惯例一致；仅 overfit 维度使用(样本外榜「低过拟合」曾因 full_in 全仓复利 519.63 离群被压平)。
  let cap = null;
  if (pctCap != null && pctCap > 0 && pctCap < 1 && vals.length >= 4) {
    const vs = vals.slice().sort((a, b) => a - b);
    const i = pctCap * (vals.length - 1), f = Math.floor(i), c = Math.ceil(i);
    cap = f === c ? vs[f] : vs[f] + (vs[c] - vs[f]) * (i - f);
    vals = vals.map((v) => Math.min(v, cap));
  }
  const mn = Math.min.apply(null, vals);
  const mx = Math.max.apply(null, vals);
  const rng = mx - mn;
  // 归一化时同样把输入钳到 cap，保证超分位值映射到 1.0（与建 min/max 用的截断数组一致）
  return (v) => {
    if (v == null || isNaN(v)) return 0.5;
    const cv = cap != null ? Math.min(v, cap) : v;
    return rng === 0 ? 0.5 : (cv - mn) / rng;
  };
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
  const overfitN = _labRetestMinMax(raw, "overfit", 0.95); // 95%分位截断抗 full_in 全仓复利极端离群值
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
    extra = `<span class="lab-rank-dim-sub">测试集${_labRetestPct(row.testRet)} · 过拟合${_labRetestPct(row.overfit)} · 测试集胜率${_labRetestPct(row.testWin)}${_labRetestSmallTag(row.oosSmall)}</span>`;
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
  const idxTag = row.index_name ? `<span class="lab-idx-tag">${_INDEX_NAME_MAP[row.index] || row.index_name}</span>` : "";
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
    ? "综合分(二次测试)=0.3整体+0.25分年+0.25样本外+0.2极端，归一化加权，越高越稳健。整体分=0.35收益+0.25胜率+0.15回撤+0.15风险调整+0.1样本量(凹函数)，含风险调整第5因子(与主榜一致)。1:1例(科创50·唐奇安20上轨买×MACD死叉卖,核实源=lab_retest_kc50.json)：四项真实得分=整体0.88、分年0.91、样本外0.90、极端0.61→0.3×0.88+0.25×0.91+0.25×0.90+0.2×0.61=综合0.84。" + _labHelpIcon("score")
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
                ? "样本外榜=0.4test收益+0.4低过拟合+0.2test胜率（前70%训练后30%验证防过拟合）。低过拟合维度已按95%分位截断抗极端值（防单个full_in全仓复利离群把轴拉平，与全站winsorize抗极端惯例一致）。1:1例(科创50·唐奇安20上轨买×MACD死叉卖,核实源=lab_retest_kc50.json)：样本外(后30%验证)收益+135.8%→归一0.80、低过拟合0.983(该轴按全部配对min-max归一+95%分位截断)、样本外胜率88.9%→归一0.89→0.4×0.80+0.4×0.983+0.2×0.89=样本外分0.89。本维度当前局限：已截断抗离群，但全仓复利与定额两种收益尺度仍同池，跨模式比较需谨慎。"
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
    const idxTag = `<span class="lab-idx-tag">${_INDEX_NAME_MAP[item.index] || item.index_name}</span>`;
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
  renderPurposeNote(leftCol, PURPOSE_NOTES["lab.retest"], {variant:"lab-sm"});
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
      const index_name = (_INDEX_NAME_MAP[index] || rd.index_name || _labIdxName(index));
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
  const chartDataP = fetchJSON(`https://ss.fx8.store/r2/index/${m.index}-all.json`).catch(() => null);
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
      const statLabel1 = side1 === 'buy' ? '关注点' : '风险点';
      const statLabel2 = side2 === 'buy' ? '关注点' : '风险点';
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
      const pairSideLabel = fSide === "buy" ? "风险点" : "关注点";
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
  renderPurposeNote(leftCol, PURPOSE_NOTES["lab.ablation"], {variant:"lab-sm"});
  leftCol.appendChild(essayWarn);

  const data = await fetchLabAblationData();
  const idxList = (data && data.indexes) ? data.indexes.map((x) => ({ id: x.index_id, name: (_INDEX_NAME_MAP[x.index_id] || x.index_name) })) : [];
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
  renderPurposeNote(leftCol, PURPOSE_NOTES["lab.symmetry"], {variant:"lab-sm"});
  leftCol.appendChild(essayWarn);

  const data = await fetchLabSymmetryData();
  const idxList = (data && data.indexes) ? data.indexes.map((x) => ({ id: x.index_id, name: (_INDEX_NAME_MAP[x.index_id] || x.index_name) })) : LAB_SIM_INDEXES;
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
  phaseNote.innerHTML = "📌 <b>多空对称测试</b>：前8配对做多/做空对比。A股向上漂移致做多盈利、做空亏损属正常不对称。";
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
    xAxis: { type: "category", data: items.map((x) => (_INDEX_NAME_MAP[x.index_id] || x.index_name)), axisLabel: { rotate: 30, fontSize: 10 } },
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
  renderPurposeNote(leftCol, PURPOSE_NOTES["lab.paramscan"], {variant:"lab-sm"});
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
  const idxList = firstScan ? firstScan.per_index.map((x) => ({ id: x.index_id, name: (_INDEX_NAME_MAP[x.index_id] || x.index_name) })) : [];
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
  hint.innerHTML = `${stratName} · ${_INDEX_NAME_MAP[pi.index_id] || pi.index_name} · 默认收益 <b style="color:${_retFg(pi.default_ret)}">${pi.default_ret.toFixed(1)}%</b> · 回测最优 <b style="color:${_retFg(pi.best_ret)}">${pi.best_ret.toFixed(1)}%</b> · <span style="color:${vColor};font-weight:600">${pi.verdict === "robust_profitable" ? "稳健高原" : "尖锐尖峰(过拟合风险)"}</span>${pi.best_is_default ? " · 默认即回测最优✓" : ""}`;
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
      && state.labSubMode !== "aiwarn" && state.labSubMode !== "aiscore" && state.labSubMode !== "sigkelly") {
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

  // C7 P4-β: 自定义分析 > AI预警子tab -> 渲染情绪告警+维度拆解+历史类比分区(原 custom 内容打包到此)
  if (state.labSubMode === "aiwarn") {
    await renderCustomAnalyzeLab();
    _labSetHash("#lab?sub=aiwarn");
    _labRestoreScroll();
    return;
  }

  // P1-新-C: 自定义分析 > AI评分子tab -> 渲染ETF买清单+卖清单(用户输入持仓代码查high_alert)
  if (state.labSubMode === "aiscore") {
    await renderAIScoreListLab();
    _labSetHash("#lab?sub=aiscore");
    _labRestoreScroll();
    return;
  }

  // 自定义分析 > 信号凯利回测子tab -> 渲染6象限(3评级+3 ETF归类)×4模式×3周期半凯利仓位回测
  if (state.labSubMode === "sigkelly") {
    await renderSigKellyLab();
    _labSetHash("#lab?sub=sigkelly");
    _labRestoreScroll();
    return;
  }

  // 实验室自白黄块（列表页也显示，通用介绍 + 抖音号；移入左栏与策略列表同栏）
  const essayWarn = document.createElement("div");
  essayWarn.className = "lab-warning lab-warning-essay";
  essayWarn.innerHTML = _labWarningEssayHTML();

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
  renderPurposeNote(leftCol, PURPOSE_NOTES["lab.single"], {variant:"lab-sm"});
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
    '<div class="lab-rank-sub-note">一个关注点+一个风险点组成一对完整交易，7买×7卖=49对</div>' +
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
    renderPurposeNote(wrapper, PURPOSE_NOTES["lab.aiwarn"], {variant:"lab-sm"});

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
// 汪汪队ETF代码->iid 映射（用于点击行打开详情 modal / 持仓自查输入框）
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

// ============ AI评分tab分页常量 + state(参照 app.js ETF评分模式) ============
// 2026-07-27: buy 227只折叠Top20+展开50/页, hold 951只50/页分页, sell 31只全量
const _LAB_AISCORE_PAGE_SIZE = 50;        // buy/hold 区页大小
const _LAB_AISCORE_COLLAPSE_TOP = 20;     // buy 区折叠态显 Top N(按 score 降序)
const _labAiscoreState = {
  data: null,        // 缓存 etf_score_list buy+sell 合并(含空 hold_list, 懒加载后填充), 翻页/展开不重新 fetch
  codeToIid: {},     // ETF code -> iid 映射缓存
  buyPage: 1,        // buy 区当前页(展开态)
  buyExpanded: false,// buy 区展开状态(折叠Top20 / 展开50页)
  holdPage: 1,       // hold 区当前页
  holdLoaded: false, // P0-2: hold JSON 懒加载状态(初始 false, 点"加载持有观察"后 true)
  holdLoading: null, // P0-2: hold 懒加载进行中 promise(防并发重复 fetch)
};
// buyExpanded 从 localStorage 恢复(记忆用户偏好)
try { if (localStorage.getItem("lab_aiscore_buy_expanded") === "1") _labAiscoreState.buyExpanded = true; } catch (e) {}

// 分页器HTML(复用 .etf-page-btn 全局样式; scope="buy"/"hold" 区分)
function _labAiscorePager(scope, page, pages, total) {
  let html = '<div class="etf-score-pager">';
  html += '<button class="etf-page-btn" data-scope="' + scope + '" data-page="' + (page > 1 ? page - 1 : 1) + '"' + (page <= 1 ? ' disabled' : '') + '>上一页</button>';
  const pageBtns = [];
  const addPage = (p) => { if (pageBtns.indexOf(p) < 0) pageBtns.push(p); };
  addPage(1); addPage(pages);
  for (let p = page - 2; p <= page + 2; p++) {
    if (p > 1 && p < pages) addPage(p);
  }
  pageBtns.sort((a, b) => a - b);
  let prev = 0;
  pageBtns.forEach((p) => {
    if (p - prev > 1) html += '<span class="etf-page-ellipsis">…</span>';
    html += '<button class="etf-page-btn' + (p === page ? " active" : "") + '" data-scope="' + scope + '" data-page="' + p + '">' + p + '</button>';
    prev = p;
  });
  html += '<button class="etf-page-btn" data-scope="' + scope + '" data-page="' + (page < pages ? page + 1 : pages) + '"' + (page >= pages ? ' disabled' : '') + '>下一页</button>';
  html += '<span class="etf-page-info">' + page + ' / ' + pages + ' 页（' + total + ' 只）</span>';
  html += '</div>';
  return html;
}

async function renderAIScoreListLab() {
  // wrapper：顶部说明 + 持仓自查 + (买清单|卖清单 左右并排)
  const wrapper = document.createElement("div");
  wrapper.className = "lab-aiscore-wrap";

  // 顶部说明
  renderPurposeNote(wrapper, PURPOSE_NOTES["lab.aiscore"], {variant:"lab-sm"});

  // 持仓自查 host（额外功能:输入任意ETF代码查询）— 移至最前,1列
  const queryHost = document.createElement("div");
  queryHost.className = "lab-aiscore-section lab-aiscore-query";
  wrapper.appendChild(queryHost);

  // 买清单 + 卖清单 + 持有建议 三列并排容器(grid 1fr 1fr 1fr, 窄屏降1列)
  // 顺序:买清单 -> 卖清单 -> 持有建议(买卖清单优先看,持有建议靠后)
  const gridHost = document.createElement("div");
  gridHost.className = "lab-aiscore-grid";

  // 买清单 host（非持仓 + side=buy）
  const buyHost = document.createElement("div");
  buyHost.className = "lab-aiscore-section lab-aiscore-buy";
  buyHost.innerHTML = '<div class="lab-custom-loading">⏳ 加载买清单…</div>';
  gridHost.appendChild(buyHost);

  // 卖清单 host（非持仓 + side=sell）
  const sellHost = document.createElement("div");
  sellHost.className = "lab-aiscore-section lab-aiscore-sell";
  gridHost.appendChild(sellHost);

  // 持有建议 host（用户持有的ETF,从买/卖清单分离,单独成列;放最后,买卖清单优先看）
  const holdHost = document.createElement("div");
  holdHost.className = "lab-aiscore-section lab-aiscore-hold";
  gridHost.appendChild(holdHost);

  wrapper.appendChild(gridHost);

  content.querySelectorAll(".lab-aiscore-wrap").forEach((el) => el.remove());
  content.appendChild(wrapper);

  // fetch etf_score_list_{buy,sell}.json (P0-2 2026-08-05 拆分懒加载, 原单文件 18MB -> buy+sell ~2.6MB)
  // R2 直链(对齐 app.js, .gitignore 已踢出 git 线上 ./data/ 三域名全 404)
  // hold JSON (~13MB) 懒加载: 初始 holdHost 显示"加载持有观察"按钮, 点后才 fetch
  const urlBuy = "https://ss.fx8.store/r2/data/etf_score_list_buy.json";
  const urlSell = "https://ss.fx8.store/r2/data/etf_score_list_sell.json";
  let dataBuy = null, dataSell = null;
  try {
    [dataBuy, dataSell] = await Promise.all([
      // perf批一 P3-D(2026-08-24): buy/sell 分件与 hold 同源同参统一 timeoutMs=60000。
      fetchJSON(urlBuy, 60000),
      fetchJSON(urlSell, 60000),
    ]);
  } catch (e) {
    buyHost.innerHTML = `<div class="lab-custom-error">` +
      `<div class="lab-custom-error-title">⚠️ 买清单数据加载失败</div>` +
      `<div class="lab-custom-error-detail">${e.message || e}</div>` +
      `<div class="lab-custom-error-hint">etf_score_list_buy/sell.json 不存在或网络异常。后端生成后自动恢复（每日收盘后更新）。</div>` +
      `<button type="button" class="lab-custom-retry">重试</button></div>`;
    buyHost.querySelector(".lab-custom-retry").onclick = () => renderAIScoreListLab();
    _renderAIScoreHoldSection(holdHost, [], {});
    _renderAIScoreSellSection(sellHost, [], {});
    _renderAIScoreQuerySection(queryHost, {});
    return;
  }
  // buy JSON 含完整 meta(buy_count/sell_count/hold_count); sell JSON 同 meta
  // 合并成兼容旧 data 结构(buy_list + sell_list + hold_list=空 + meta 字段), 复用下游渲染
  const data = {
    date: dataBuy.date, updated_at: dataBuy.updated_at, source: dataBuy.source,
    universe_count: dataBuy.universe_count, full_market: dataBuy.full_market,
    buy_count: dataBuy.buy_count, sell_count: dataBuy.sell_count, hold_count: dataBuy.hold_count,
    buy_list: Array.isArray(dataBuy.buy_list) ? dataBuy.buy_list : [],
    sell_list: Array.isArray(dataSell.sell_list) ? dataSell.sell_list : [],
    hold_list: [],  // P0-2: hold 懒加载, 初始空
  };
  if (!data || data.error || !Array.isArray(data.buy_list)) {
    buyHost.innerHTML = `<div class="lab-custom-error">` +
      `<div class="lab-custom-error-title">⚠️ 买清单暂未生成</div>` +
      `<div class="lab-custom-error-detail">${(data && data.error) || "etf_score_list_buy.json 结构异常或为空"}</div>` +
      `<div class="lab-custom-error-hint">后端未生成买清单数据,收盘后跑完评分即自动恢复。可先去 🎯自定义分析 tab 看单标的分析。</div>` +
      `<button type="button" class="lab-custom-retry">重试</button></div>`;
    buyHost.querySelector(".lab-custom-retry").onclick = () => renderAIScoreListLab();
    _renderAIScoreHoldSection(holdHost, [], {});
    _renderAIScoreSellSection(sellHost, [], {});
    _renderAIScoreQuerySection(queryHost, {});
    return;
  }

  // === 公共映射:ETF code -> iid（后端 buy_list 不含 iid,用前端 _LAB_AISCORE_ETF_TO_IID 兜底）===
  const codeToIid = {};
  Object.keys(_LAB_AISCORE_ETF_TO_IID).forEach((c) => {
    codeToIid[c] = _LAB_AISCORE_ETF_TO_IID[c];
  });

  // === 持有建议列:hold_list 独立字段(2026-07-27 修复原从 sell_list 过滤"持有"永远空 bug) ===
  // 注:持有建议 = data.hold_list(不够格buy但不过热 high<60 的持有观察项),非用户持仓
  // 后端 export_etf_score_list.py:558 已将 hold 拆独立字段, sell_list 31只全是过热项(high>=60)不含"持有"
  const buyListRaw = Array.isArray(data.buy_list) ? data.buy_list : [];
  const sellListRaw = Array.isArray(data.sell_list) ? data.sell_list : [];
  // P0-2: hold_list 懒加载, 初始空(hold_count 从 buy JSON meta 取, 显示"加载持有观察 X 只"按钮)
  const holdItems = Array.isArray(data.hold_list) ? data.hold_list : [];
  const holdCount = (data.hold_count != null) ? data.hold_count : 0;
  // 卖清单:sell_list 全是过热风险提示信号(high>=60), hold 已拆独立字段, 直接用
  const sellListFiltered = sellListRaw;
  // 缓存到 state, 翻页/展开/收起时不重新 fetch, 只重渲染对应区
  _labAiscoreState.data = data;
  _labAiscoreState.codeToIid = codeToIid;
  _labAiscoreState.buyPage = 1;
  _labAiscoreState.holdPage = 1;
  _labAiscoreState.holdLoaded = false;  // P0-2: hold 懒加载状态
  _labAiscoreState.holdLoading = null;
  // 日期字符串(用于 section-head)
  const date = data.date || "";
  const dateStr = date && date.length === 8 ? `${date.slice(0,4)}-${date.slice(4,6)}-${date.slice(6,8)}` : date;

  // === 买清单渲染(折叠Top20+展开50/页, 参照 app.js ETF评分模式) ===
  _renderLabAiscoreBuySection(buyHost, buyListRaw, codeToIid, dateStr);

  // === 持有建议渲染（P0-2: hold 懒加载, 初始显示"加载持有观察"按钮）===
  _renderAIScoreHoldSection(holdHost, holdItems, codeToIid, dateStr, holdCount);

  // === 卖清单渲染（直接渲染 sell_list 表格 + 持仓自查）===
  _renderAIScoreSellSection(sellHost, sellListFiltered, codeToIid);
  // 持仓自查:传入 buy+sell 全量清单(含持仓标的,便于查任意ETF)+ dateStr
  // 修复2026-07-24:515030等非汪汪队ETF在etf_score_list有评分但无iid,原逻辑报"未识别",现先查etf_score_list降级显示评分卡片
  _renderAIScoreQuerySection(queryHost, codeToIid, buyListRaw.concat(sellListRaw), dateStr);
}

// P0-2 (2026-08-05): 懒加载 hold JSON -- lab AI评分 tab 点"加载持有观察"按钮触发
// fetch etf_score_list_hold.json (~13MB, br~783KB), 解析 hold_list 后重渲染 hold 区
// _labAiscoreState.holdLoaded 跟踪状态, holdLoading 缓存进行中 promise 防并发重复 fetch
async function _ensureLabHoldLoaded(holdHost, codeToIid, dateStr, holdCount) {
  const st = _labAiscoreState;
  if (st.holdLoaded) return true;
  if (st.holdLoading) return st.holdLoading;
  st.holdLoading = (async () => {
    try {
      // perf批一 P3-D(2026-08-24): hold 分件大, 补 timeoutMs=60000(对齐 app.js _ensureHoldLoaded 同源点)。
      const r = await fetchJSON("https://ss.fx8.store/r2/data/etf_score_list_hold.json", 60000);
      const holdItems = Array.isArray(r.hold_list) ? r.hold_list : [];
      if (st.data) st.data.hold_list = holdItems;
      st.holdLoaded = true;
      _renderAIScoreHoldSection(holdHost, holdItems, codeToIid, dateStr, holdItems.length);
      return true;
    } catch (e) {
      console.error("[lab ensureHoldLoaded] fetch hold JSON failed:", e);
      // 重渲染显示错误 + 重试按钮
      _renderAIScoreHoldSection(holdHost, [], codeToIid, dateStr, holdCount, (e && e.message) || String(e));
      return false;
    } finally {
      st.holdLoading = null;
    }
  })();
  return st.holdLoading;
}

// buy 区渲染:折叠Top20+展开50/页(参照 app.js _renderEtfScoreBody buy 区)
// 2026-07-27: 原 slice(0,12) 截断只显12只, 改为折叠Top20+展开分页, buy 227只可全量浏览
function _renderLabAiscoreBuySection(buyHost, buyList, codeToIid, dateStr) {
  buyList = buyList || [];
  codeToIid = codeToIid || {};
  // 按 score 降序
  const sorted = buyList.slice().sort((a, b) => (b.score || 0) - (a.score || 0));
  const st = _labAiscoreState;
  // 单行 HTML 生成(buy 区共用)
  const rowHTML = (it, idx) => {
    const code = _labAIScoreCode(it);
    const iid = codeToIid[code] || "";
    const score = it.score != null ? Number(it.score).toFixed(1) : "-";
    const hands = it.hands != null ? Number(it.hands) : 0;
    const handsCls = `hands-${[3, 2, 1, 0].includes(hands) ? hands : 0}`;
    const nt = it.is_national_team ? `<span class="lab-aiscore-nt">汪汪队</span>` : "";
    const reason = it.reason_summary ? `<span class="lab-aiscore-reason" title="${it.reason_summary}">${it.reason_summary}</span>` : "";
    return `<tr class="lab-aiscore-row" data-code="${code}" data-iid="${iid}" data-name="${it.name || ""}">` +
      `<td class="aiscore-rank">${idx + 1}</td>` +
      `<td class="aiscore-code">${code || "-"}</td>` +
      `<td class="aiscore-name">${it.name || "-"}${nt}</td>` +
      `<td class="aiscore-score">${score}</td>` +
      `<td class="aiscore-hands"><span class="hands-badge ${handsCls}">${hands}手</span></td>` +
      `<td class="aiscore-reason-cell">${reason}</td>` +
    `</tr>`;
  };
  let rowsHTML = "";
  let pagerHTML = "";
  let collapseHTML = "";
  const emptyRow = sorted.length === 0 ? `<tr><td colspan="6" class="lab-aiscore-empty">暂无买清单数据</td></tr>` : "";
  if (st.buyExpanded) {
    // 展开态: 50/页分页
    const pages = Math.max(1, Math.ceil(sorted.length / _LAB_AISCORE_PAGE_SIZE));
    if (st.buyPage > pages) st.buyPage = pages;
    if (st.buyPage < 1) st.buyPage = 1;
    const start = (st.buyPage - 1) * _LAB_AISCORE_PAGE_SIZE;
    const slice = sorted.slice(start, start + _LAB_AISCORE_PAGE_SIZE);
    rowsHTML = slice.map((it, idx) => rowHTML(it, start + idx)).join("");
    if (pages > 1) pagerHTML = _labAiscorePager("buy", st.buyPage, pages, sorted.length);
    collapseHTML = `<div class="lab-aiscore-collapse-wrap"><button type="button" class="lab-aiscore-collapse" data-action="collapse-buy">收起（仅显示 Top ${_LAB_AISCORE_COLLAPSE_TOP}）</button></div>`;
  } else {
    // 折叠态: Top20 + 展开按钮
    const top = sorted.slice(0, _LAB_AISCORE_COLLAPSE_TOP);
    rowsHTML = top.map((it, idx) => rowHTML(it, idx)).join("");
    if (sorted.length > _LAB_AISCORE_COLLAPSE_TOP) {
      const pages = Math.ceil(sorted.length / _LAB_AISCORE_PAGE_SIZE);
      collapseHTML = `<div class="lab-aiscore-collapse-wrap"><button type="button" class="lab-aiscore-collapse" data-action="expand-buy">展开全部 ${sorted.length} 只（共 ${pages} 页）</button></div>`;
    }
  }
  buyHost.innerHTML =
    `<div class="lab-aiscore-section-head">` +
      `<div class="lab-aiscore-section-title">📈 AI买清单 <span class="lab-aiscore-date">📅 ${dateStr || "未注明日期"}</span></div>` +
      `<div class="lab-aiscore-section-sub">按低位机会降序 · 手数 3/2/1 建议关注量 · 0手不入清单</div>` +
    `</div>` +
    `<div class="lab-aiscore-table-wrap">` +
      `<table class="lab-aiscore-table">` +
        `<thead><tr><th>#</th><th>代码</th><th>名称</th><th>AI分</th><th>建议</th><th>理由摘要</th></tr></thead>` +
        `<tbody>${rowsHTML}${emptyRow}</tbody>` +
      `</table>` +
    `</div>` + pagerHTML + collapseHTML;
  // 点击行弹理由 modal（复用 _labCustom*HTML 5函数）
  buyHost.querySelectorAll(".lab-aiscore-row").forEach((tr) => {
    tr.onclick = () => {
      const iid = tr.dataset.iid;
      const code = tr.dataset.code;
      const name = tr.dataset.name;
      if (!iid) {
        _labAIScoreOpenModal(`<div class="lab-custom-error"><div class="lab-custom-error-title">⚠️ 无指数ID(iid)映射</div><div class="lab-custom-error-detail">ETF ${code}(${name}) 未配置 iid,无法加载 8+8 维度拆解。可去 🎯自定义分析 tab 手动选标的查看。</div></div>`);
        return;
      }
      _labAIScoreOpenDetailModal(code, name, iid);
    };
  });
  // 绑定分页器按钮(buy 区)
  buyHost.querySelectorAll(".etf-page-btn[data-page]").forEach((b) => {
    b.onclick = () => {
      if (b.disabled) return;
      const p = parseInt(b.dataset.page, 10) || 1;
      if ((b.dataset.scope || "buy") === "buy") st.buyPage = p;
      _renderLabAiscoreBuySection(buyHost, sorted, codeToIid, dateStr);
      const top = buyHost.getBoundingClientRect().top + window.scrollY - 80;
      window.scrollTo({ top: Math.max(0, top), behavior: "smooth" });
    };
  });
  // 绑定展开/收起按钮(localStorage 记忆 buyExpanded)
  buyHost.querySelectorAll(".lab-aiscore-collapse[data-action]").forEach((b) => {
    b.onclick = () => {
      const act = b.dataset.action;
      if (act === "expand-buy") {
        st.buyExpanded = true;
        try { localStorage.setItem("lab_aiscore_buy_expanded", "1"); } catch (e) {}
        st.buyPage = 1;
      } else if (act === "collapse-buy") {
        st.buyExpanded = false;
        try { localStorage.setItem("lab_aiscore_buy_expanded", "0"); } catch (e) {}
      }
      _renderLabAiscoreBuySection(buyHost, sorted, codeToIid, dateStr);
    };
  });
}

// 持有建议渲染:从 data.hold_list 读(951只, 50/页分页), 按 high_alert 降序
// 2026-07-27 修复双重bug: ①从 data.hold_list 读(原 sellListRaw.filter 永远空) ②读 hold_reason(原 sell_signal 字段在 hold_list 不存在)
// 每项展示:ETF代码/名称 + 高位预警 + 低位机会 + 持有建议(hold_reason 文本) + 理由
// P0-2 (2026-08-05): holdCount + errorMsg 参数支持懒加载(holdItems 空时显示"加载持有观察"按钮)
function _renderAIScoreHoldSection(host, holdItems, codeToIid, dateStr, holdCount, errorMsg) {
  holdItems = holdItems || [];
  codeToIid = codeToIid || {};
  holdCount = (holdCount != null) ? holdCount : holdItems.length;
  const st = _labAiscoreState;
  // P0-2: hold 未加载(holdItems 空且 holdLoaded=false)时显示懒加载按钮, 不走表格渲染
  if (holdItems.length === 0 && !st.holdLoaded) {
    host.innerHTML =
      `<div class="lab-aiscore-section-head">` +
        `<div class="lab-aiscore-section-title">💼 未过热持有建议 <span class="lab-aiscore-section-sub-inline">未加载(懒加载)${holdCount ? ` · ${holdCount}只` : ""}</span></div>` +
      `</div>` +
      `<div class="lab-aiscore-hold-placeholder">` +
        (errorMsg ? `<div class="lab-custom-error-detail" style="margin-bottom:8px">⚠️ ${_esc(errorMsg)}</div>` : "") +
        `<button type="button" class="lab-aiscore-load-hold-btn">📥 加载持有观察 ${holdCount} 只(约 800KB)</button>` +
      `</div>`;
    host.querySelector(".lab-aiscore-load-hold-btn").onclick = async () => {
      const btn = host.querySelector(".lab-aiscore-load-hold-btn");
      if (btn) { btn.textContent = "⏳ 加载中…"; btn.disabled = true; }
      await _ensureLabHoldLoaded(host, codeToIid, dateStr, holdCount);
    };
    return;
  }
  // 排序:按 high_alert 降序(风险高的排前)
  const sortedHold = holdItems.slice().sort((a, b) => (b.high_alert || 0) - (a.high_alert || 0));
  // 单行 HTML 生成(hold 区共用)
  const rowHTML = (it, idx) => {
    const code = _labAIScoreCode(it);
    const iid = codeToIid[code] || "";
    const high = it.high_alert != null ? Number(it.high_alert).toFixed(1) : "-";
    const low = it.low_alert != null ? Number(it.low_alert).toFixed(1) : "-";
    // 持有建议:hold_list 用 hold_reason 字段(非 sell_signal), 无则"持有观察"
    const advice = it.hold_reason || it.sell_signal || "持有观察";
    const adviceCls = "hold-advice-warn";
    const nt = it.is_national_team ? `<span class="lab-aiscore-nt">汪汪队</span>` : "";
    const reason = it.reason_summary ? `<span class="lab-aiscore-reason" title="${it.reason_summary}">${it.reason_summary}</span>` : "";
    return `<tr class="lab-aiscore-row lab-aiscore-hold-row" data-code="${code}" data-iid="${iid}" data-name="${it.name || ""}">` +
      `<td class="aiscore-rank">${idx + 1}</td>` +
      `<td class="aiscore-code">${code || "-"}</td>` +
      `<td class="aiscore-name">${it.name || "-"}${nt}</td>` +
      `<td class="aiscore-high">${high}</td>` +
      `<td class="aiscore-low">${low}</td>` +
      `<td class="aiscore-advice"><span class="hold-advice ${adviceCls}">${advice}</span></td>` +
      `<td class="aiscore-reason-cell">${reason}</td>` +
    `</tr>`;
  };
  const hc = sortedHold.length;  // 已加载后的实际 hold 数量(覆盖入参 holdCount)
  // 50/页分页(951只用50/页约20页, 避免一次性渲染卡顿)
  const pages = Math.max(1, Math.ceil(hc / _LAB_AISCORE_PAGE_SIZE));
  if (st.holdPage > pages) st.holdPage = pages;
  if (st.holdPage < 1) st.holdPage = 1;
  const start = (st.holdPage - 1) * _LAB_AISCORE_PAGE_SIZE;
  const slice = sortedHold.slice(start, start + _LAB_AISCORE_PAGE_SIZE);
  const rowsHTML = slice.map((it, idx) => rowHTML(it, start + idx)).join("");
  const empty = hc === 0
    ? `<tr><td colspan="7" class="lab-aiscore-empty">暂无未过热持有项</td></tr>`
    : "";
  const pagerHTML = (hc > 0 && pages > 1) ? _labAiscorePager("hold", st.holdPage, pages, hc) : "";
  host.innerHTML =
    `<div class="lab-aiscore-section-head">` +
      `<div class="lab-aiscore-section-title">💼 未过热持有建议 <span class="lab-aiscore-section-sub-inline">未过热持有项${hc ? ` · ${hc}只` : ""}</span></div>` +
    `</div>` +
    `<div class="lab-aiscore-table-wrap">` +
      `<table class="lab-aiscore-table lab-aiscore-table-hold">` +
        `<thead><tr><th>#</th><th>代码</th><th>名称</th><th>高位预警</th><th>低位机会</th><th>持有建议</th><th>理由摘要</th></tr></thead>` +
        `<tbody>${rowsHTML}${empty}</tbody>` +
      `</table>` +
    `</div>` + pagerHTML;
  // 点击行弹理由 modal
  host.querySelectorAll(".lab-aiscore-row").forEach((tr) => {
    tr.onclick = () => {
      const iid = tr.dataset.iid;
      const code = tr.dataset.code;
      const name = tr.dataset.name;
      if (!iid) {
        _labAIScoreOpenModal(`<div class="lab-custom-error"><div class="lab-custom-error-title">⚠️ 无指数ID(iid)映射</div><div class="lab-custom-error-detail">ETF ${code}(${name}) 未配置 iid,无法加载 8+8 维度拆解。可去 🎯自定义分析 tab 手动选标的查看。</div></div>`);
        return;
      }
      _labAIScoreOpenDetailModal(code, name, iid);
    };
  });
  // 绑定分页器按钮(hold 区)
  host.querySelectorAll(".etf-page-btn[data-page]").forEach((b) => {
    b.onclick = () => {
      if (b.disabled) return;
      const p = parseInt(b.dataset.page, 10) || 1;
      if ((b.dataset.scope || "hold") === "hold") st.holdPage = p;
      _renderAIScoreHoldSection(host, sortedHold, codeToIid, dateStr);
      const top = host.getBoundingClientRect().top + window.scrollY - 80;
      window.scrollTo({ top: Math.max(0, top), behavior: "smooth" });
    };
  });
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
    // 危险词:含"调整/留意高位预警/防范风险"等明确留意高位预警动作;中性词:含"持有/观望";其余(如"偏热留意")=warn
    // 注意:"持有(未过热)"含"过热"但语义中性,故只匹配"调整/卖/防范风险"动作词
    const sigCls = /减仓|卖出|清仓|卖/.test(sig) ? "sig-danger" : /持有|观望/.test(sig) ? "sig-neutral" : "sig-warn";
    const nt = it.is_national_team ? `<span class="lab-aiscore-nt">汪汪队</span>` : "";
    const reason = it.reason_summary ? `<span class="lab-aiscore-reason" title="${it.reason_summary}">${it.reason_summary}</span>` : "";
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
      `<div class="lab-aiscore-section-title">📉 AI卖清单 <span class="lab-aiscore-section-sub-inline">按高位预警降序 · 风险提示信号=持有/调整建议</span></div>` +
    `</div>` +
    `<div class="lab-aiscore-table-wrap">` +
      `<table class="lab-aiscore-table lab-aiscore-table-sell">` +
        `<thead><tr><th>#</th><th>代码</th><th>名称</th><th>高位预警</th><th>低位机会</th><th>风险提示信号</th><th>理由摘要</th></tr></thead>` +
        `<tbody>${rowsHTML}${empty}</tbody>` +
      `</table>` +
    `</div>`;
  host.querySelectorAll(".lab-aiscore-row").forEach((tr) => {
    tr.onclick = () => {
      const iid = tr.dataset.iid;
      const code = tr.dataset.code;
      const name = tr.dataset.name;
      if (!iid) {
        _labAIScoreOpenModal(`<div class="lab-custom-error"><div class="lab-custom-error-title">⚠️ 无指数ID(iid)映射</div><div class="lab-custom-error-detail">ETF ${code}(${name}) 未配置 iid,无法加载 8+8 维度拆解。可去 🎯自定义分析 tab 手动选标的查看。</div></div>`);
        return;
      }
      _labAIScoreOpenDetailModal(code, name, iid);
    };
  });
}

// 持仓自查:输入任意ETF代码 -> 先查 etf_score_list(评分卡片) -> 有iid再 fetch alert_analyze(8+8拆解)
// 修复2026-07-24:515030等非汪汪队ETF在etf_score_list有评分但无iid映射,原逻辑直接报"未识别ETF代码"
// 现逻辑:①先查etf_score_list(buy+sell 50只,模糊匹配etf_code/name)②命中显示评分卡片不报错
//        ③若有iid再fetch alert_analyze显示8+8维度拆解 ④无iid降级提示"有评分但无8+8拆解"
//        ⑤完全不在etf_score_list也不在iid表才报"未识别"
function _renderAIScoreQuerySection(host, codeToIid, etfList, dateStr) {
  codeToIid = codeToIid || {};
  etfList = Array.isArray(etfList) ? etfList : [];
  host.innerHTML =
    `<div class="lab-aiscore-section-head">` +
      `<div class="lab-aiscore-section-title">🔍 持仓自查（输入任意 ETF 代码查 AI 评分 / 高位预警）</div>` +
      `<div class="lab-aiscore-section-sub">输入持仓 ETF 代码（如 510300 / 515030）查 AI 评分 + 高位预警 + 风险提示建议 + 完整维度拆解</div>` +
    `</div>` +
    `<div class="lab-aiscore-sell-input-wrap">` +
      `<input type="text" class="lab-aiscore-sell-input" placeholder="ETF代码(如510300/515030)" autocomplete="off" inputmode="numeric">` +
      `<button type="button" class="lab-aiscore-sell-btn">查高位预警</button>` +
    `</div>` +
    `<div class="lab-aiscore-sell-result"></div>`;
  const input = host.querySelector(".lab-aiscore-sell-input");
  const btn = host.querySelector(".lab-aiscore-sell-btn");
  const resultHost = host.querySelector(".lab-aiscore-sell-result");
  const runQuery = async () => {
    const code = (input.value || "").trim();
    if (!code) { resultHost.innerHTML = `<div class="lab-custom-error">请输入 ETF 代码</div>`; return; }
    const codeLow = String(code).toLowerCase();
    // 1. 先查 etf_score_list(模糊匹配 etf_code 或 name,同 _applyEtfScoreFilter 逻辑)
    const matched = etfList.find((e) => {
      const ec = e && (e.etf_code || e.code);
      return (ec && String(ec).toLowerCase().includes(codeLow)) ||
             (e && e.name && String(e.name).toLowerCase().includes(codeLow));
    });
    const matchedCode = matched ? (matched.etf_code || matched.code || code) : code;
    // 2. 查 iid 映射(优先用 matchedCode 精确查,再用输入 code 兜底)
    const iid = codeToIid[matchedCode] || _LAB_AISCORE_ETF_TO_IID[matchedCode] ||
                codeToIid[code] || _LAB_AISCORE_ETF_TO_IID[code] || "";
    // 3. 完全不在 etf_score_list 也不在 iid 表:报"未识别"
    if (!matched && !iid) {
      resultHost.innerHTML = `<div class="lab-custom-error"><div class="lab-custom-error-title">⚠️ 未识别 ETF 代码</div><div class="lab-custom-error-detail">${code} 既不在当日 ETF评分清单(${etfList.length} 只)中,也未配置 iid 映射。</div><div class="lab-custom-error-hint">常见:510050/510300/510500/159915/588000/510880/513050/510900/515030 等,或去 🎯自定义分析 tab 选标的。</div></div>`;
      return;
    }
    // 4. 命中 etf_score_list 但无 iid:降级显示评分卡片,不报错
    if (matched && !iid) {
      resultHost.innerHTML = _buildEtfScoreOnlyCardHTML(matched, dateStr, "");
      return;
    }
    // 5. 有 iid:fetch alert_analyze,显示完整 high_alert 卡片(若同时 matched,顶部补评分 badge)
    resultHost.innerHTML = `<div class="lab-custom-loading">⏳ 加载 ${matchedCode} 的高位预警…</div>`;
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
      // alert_analyze 缺失:若 matched 有评分,降级显示评分卡片;否则报数据不足
      if (matched) {
        resultHost.innerHTML = _buildEtfScoreOnlyCardHTML(matched, dateStr, `⚠️ 8+8 维度快照加载异常:${(data && data.error) || "未知"},已降级显示评分卡片`);
        return;
      }
      resultHost.innerHTML = `<div class="lab-custom-error"><div class="lab-custom-error-title">⚠️ 数据不足</div><div class="lab-custom-error-detail">${(data && data.error) || "未知错误"}</div><div class="lab-custom-error-hint">该标的后端计算异常(如指数数据缺失),待后端修复后自动恢复。</div></div>`;
      return;
    }
    const alert = data.alert || {};
    const reason = data.reason || {};
    const high = alert.high;
    const highLvl = alert.high_level || "";
    const highTooltip = _labCustomLevelTooltip(high, "high");
    const highCls = _labCustomLevelClass(high, "high");
    // sell_signal: high >= 70 建议调整 / 50-70 偏热留意 / <50 暂无风险提示信号
    const sellSignal = (high != null && !isNaN(high)) ?
      (high >= 70 ? "🔴 建议调整" : high >= 50 ? "🟡 偏热留意" : "🟢 暂无风险提示信号") : "无数据";
    const highHuman = (reason.human_text && reason.human_text.high) || _labCustomDefaultHuman("high", high);
    // 评分 badge(若 matched):顶部显示 AI评分 + hands + reason_summary
    const scoreBadgeHTML = matched ? _buildEtfScoreBadgeHTML(matched) : "";
    resultHost.innerHTML =
      `<div class="lab-aiscore-sell-card">` +
        scoreBadgeHTML +
        `<div class="lab-aiscore-sell-head">` +
          `<div class="lab-aiscore-sell-title">${data.target_name || matchedCode} <span class="lab-aiscore-sell-code">${matchedCode}</span> <span class="lab-aiscore-sell-iid">iid(指数ID)=${iid}</span></div>` +
          `<div class="lab-aiscore-sell-date">📅 ${alert.date || dateStr || ""}</div>` +
        `</div>` +
        `<div class="lab-aiscore-sell-grid">` +
          `<div class="lab-aiscore-sell-cell ${highCls}">` +
            `<div class="lab-aiscore-sell-cell-label">高位预警</div>` +
            `<div class="lab-aiscore-sell-cell-score">${high != null ? Number(high).toFixed(2) : "-"}</div>` +
            `<div class="lab-aiscore-sell-cell-level" title="${highTooltip}">${highLvl}</div>` +
            `<div class="lab-aiscore-sell-cell-desc">分越高越接近过热 · ≥70 建议调整</div>` +
          `</div>` +
          `<div class="lab-aiscore-sell-cell">` +
            `<div class="lab-aiscore-sell-cell-label">风险提示建议</div>` +
            `<div class="lab-aiscore-sell-cell-signal">${sellSignal}</div>` +
            `<div class="lab-aiscore-sell-cell-desc">基于高位预警阈值(70/50)派生,仅作参考</div>` +
          `</div>` +
        `</div>` +
        `<div class="lab-aiscore-sell-human">${highHuman}</div>` +
        `<button type="button" class="lab-aiscore-sell-detail-btn">查看完整 8+8 维度拆解 -></button>` +
      `</div>`;
    const detailBtn = resultHost.querySelector(".lab-aiscore-sell-detail-btn");
    if (detailBtn) detailBtn.onclick = () => _labAIScoreOpenDetailModal(matchedCode, data.target_name || matchedCode, iid);
  };
  btn.onclick = runQuery;
  input.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); runQuery(); } };
}

// 评分卡片(无iid降级显示):用 etf_score_list 数据展示 score/hands/high_alert/low_alert/sell_signal/reason_summary
// 复用 .lab-aiscore-sell-card/.lab-aiscore-sell-grid/.lab-aiscore-sell-cell/.hands-badge 样式,不加新CSS
function _buildEtfScoreOnlyCardHTML(item, dateStr, warnMsg) {
  const code = (item && (item.etf_code || item.code)) || "";
  const name = (item && item.name) || code;
  const score = (item && item.score != null) ? Number(item.score).toFixed(2) : "-";
  const hands = (item && item.hands != null) ? Number(item.hands) : 0;
  const high = (item && item.high_alert != null) ? Number(item.high_alert).toFixed(2) : "-";
  const low = (item && item.low_alert != null) ? Number(item.low_alert).toFixed(2) : "-";
  const sig = (item && item.sell_signal) || "";
  const reason = (item && item.reason_summary) || "";
  const handsCls = `hands-${[3, 2, 1, 0].includes(hands) ? hands : 0}`;
  const sellSignalCell = sig ?
    `<div class="lab-aiscore-sell-cell">` +
      `<div class="lab-aiscore-sell-cell-label">风险提示建议</div>` +
      `<div class="lab-aiscore-sell-cell-signal">${sig}</div>` +
      `<div class="lab-aiscore-sell-cell-desc">后端基于高位预警阈值派生</div>` +
    `</div>` : "";
  const warnHTML = warnMsg ? `<div class="lab-aiscore-sell-human" style="border-left-color:#faad14">${warnMsg}</div>` : "";
  const iidCount = Object.keys(_LAB_AISCORE_ETF_TO_IID).length;
  return `<div class="lab-aiscore-sell-card">` +
    `<div class="lab-aiscore-sell-head">` +
      `<div class="lab-aiscore-sell-title">${name} <span class="lab-aiscore-sell-code">${code}</span> <span class="lab-aiscore-sell-iid">无iid(指数ID,评分降级)</span></div>` +
      `<div class="lab-aiscore-sell-date">📅 ${dateStr || ""}</div>` +
    `</div>` +
    `<div class="lab-aiscore-sell-grid">` +
      `<div class="lab-aiscore-sell-cell">` +
        `<div class="lab-aiscore-sell-cell-label">AI评分</div>` +
        `<div class="lab-aiscore-sell-cell-score">${score}</div>` +
        `<div class="lab-aiscore-sell-cell-desc">低位机会 · 越高越接近冰点反弹</div>` +
      `</div>` +
      `<div class="lab-aiscore-sell-cell">` +
        `<div class="lab-aiscore-sell-cell-label">建议手数</div>` +
        `<div class="lab-aiscore-sell-cell-signal"><span class="hands-badge ${handsCls}">${hands}手</span></div>` +
        `<div class="lab-aiscore-sell-cell-desc">3手=机会最强 / 2手=关注 / 1手=少量</div>` +
      `</div>` +
    `</div>` +
    `<div class="lab-aiscore-sell-grid">` +
      `<div class="lab-aiscore-sell-cell">` +
        `<div class="lab-aiscore-sell-cell-label">高位预警</div>` +
        `<div class="lab-aiscore-sell-cell-score">${high}</div>` +
        `<div class="lab-aiscore-sell-cell-desc">≥70 建议调整</div>` +
      `</div>` +
      `<div class="lab-aiscore-sell-cell">` +
        `<div class="lab-aiscore-sell-cell-label">低位机会</div>` +
        `<div class="lab-aiscore-sell-cell-score">${low}</div>` +
        `<div class="lab-aiscore-sell-cell-desc">越高越接近底部机会</div>` +
      `</div>` +
    `</div>` +
    (sellSignalCell ? `<div class="lab-aiscore-sell-grid">${sellSignalCell}</div>` : "") +
    (reason ? `<div class="lab-aiscore-sell-human">${reason}</div>` : "") +
    warnHTML +
    `<div class="lab-aiscore-sell-human" style="border-left-color:#59a9ff">ℹ️ 该 ETF 有 AI 评分,但暂无 8+8 维度拆解快照(仅汪汪队等 ${iidCount} 只 ETF 有指数ID(iid)映射)。如需完整拆解可去 🎯自定义分析 tab 选标的。</div>` +
  `</div>`;
}

// 评分 badge(有iid且matched时,附在 high_alert 卡片顶部):AI评分 + hands + reason_summary
function _buildEtfScoreBadgeHTML(item) {
  const score = (item && item.score != null) ? Number(item.score).toFixed(1) : "-";
  const hands = (item && item.hands != null) ? Number(item.hands) : 0;
  const handsCls = `hands-${[3, 2, 1, 0].includes(hands) ? hands : 0}`;
  const reason = (item && item.reason_summary) ? `<span class="lab-aiscore-reason">${item.reason_summary}</span>` : "";
  return `<div class="lab-aiscore-sell-human" style="border-left-color:#52c41a">` +
    `<b>AI 评分 ${score}</b> · <span class="hands-badge ${handsCls}">${hands}手</span> · ${reason}` +
  `</div>`;
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

// === 凯利回测费率客调(方案A: 前端完整重算) ===
// docs/kelly/analysis/kelly-fee-adjust.md §2 + docs/kelly/analysis/kelly-fee-presets.md §4.3
// 原始后端费率(生成 trades.json 时所用): SLIPPAGE=0.001, 用于还原 close 价格
const KELLY_ORIG_SLIPPAGE = 0.001;
const KELLY_FEE_PRESETS = [
  { key: "zero",      label: "0%剥离",    commission_rate: 0,       min_commission: 0,   slippage: 0,     transfer_fee_rate_sh: 0,       stamp_duty_rate: 0,      desc: "看纯信号alpha",           shortcut: "0" },
  { key: "etf_def",   label: "ETF默认",   commission_rate: 0.0003,  min_commission: 5,   slippage: 0.001, transfer_fee_rate_sh: 0.00001, stamp_duty_rate: 0,      desc: "万3 最低5 当前",          shortcut: "1" },
  { key: "etf_main",  label: "ETF主流",   commission_rate: 0.00005, min_commission: 0.1, slippage: 0.001, transfer_fee_rate_sh: 0.00001, stamp_duty_rate: 0,      desc: "万0.5 最低0.1",           shortcut: "2" },
  { key: "etf_cheap", label: "ETF最便宜", commission_rate: 0.00001, min_commission: 0,   slippage: 0.001, transfer_fee_rate_sh: 0.00001, stamp_duty_rate: 0,      desc: "万0.1 免5",               shortcut: "3" },
  { key: "stock_def", label: "股票默认",  commission_rate: 0.0005,  min_commission: 5,   slippage: 0.002, transfer_fee_rate_sh: 0.00001, stamp_duty_rate: 0.0005, desc: "万5 印花税万5 对比",       shortcut: "4" },
  { key: "custom",    label: "自定义",    desc: "5参数任意组合",                                                                shortcut: "C" },
];

// 沪市 ETF 判断(复用 simulate_trade.py _is_sh_etf 逻辑)
function _kellyIsShEtf(etfCode) {
  if (!etfCode) return false;
  return etfCode.startsWith("51") || etfCode.startsWith("58");
}

// 方案A: 按新费率重算单笔 trade 的 profit/return_pct(docs/kelly/analysis/kelly-fee-adjust.md §2.3)
function _kellyRecomputeTrade(tradeArr, fIdx, feeParams, buyAmount) {
  const bp = tradeArr[fIdx.buy_price] || 0;
  const sp = tradeArr[fIdx.sell_price] || 0;
  const cp = tradeArr[fIdx.current_price] || 0;
  const ec = tradeArr[fIdx.etf_code] || "";
  const sellDate = tradeArr[fIdx.sell_date] || "";
  if (bp <= 0) return { profit: 0, return_pct: 0 };
  // 还原无滑点收盘价(用原始 SLIPPAGE=0.001 还原)
  const closeBuy = bp / (1 + KELLY_ORIG_SLIPPAGE);
  const closeSell = sellDate ? (sp / (1 - KELLY_ORIG_SLIPPAGE)) : cp;
  var c = feeParams.commission_rate, s = feeParams.slippage, minC = feeParams.min_commission;
  var sh = _kellyIsShEtf(ec) ? feeParams.transfer_fee_rate_sh : 0;
  var stamp = feeParams.stamp_duty_rate;
  // 买入(复用 _buy_with_fees 逻辑)
  var buyPriceNew = closeBuy * (1 + s);
  if (buyPriceNew <= 0) return { profit: 0, return_pct: 0 };
  var sharesNew = buyAmount / (buyPriceNew * (1 + c + sh));
  var grossNew = sharesNew * buyPriceNew;
  var commBuy = grossNew * c;
  if (commBuy < minC) {
    sharesNew = (buyAmount - minC) / (buyPriceNew * (1 + sh));
    grossNew = sharesNew * buyPriceNew;
    commBuy = minC;
  }
  // 卖出(复用 _sell_with_fees 逻辑 + 印花税)
  var sellPriceNew = closeSell * (1 - s);
  var sellAmountNew = sharesNew * sellPriceNew;
  var commSell = Math.max(sellAmountNew * c, minC);
  var transferFeeSell = sellAmountNew * sh;
  var stampDuty = sellAmountNew * stamp;
  var netNew = sellAmountNew - commSell - transferFeeSell - stampDuty;
  var profitNew = netNew - buyAmount;
  var returnPctNew = profitNew / buyAmount * 100;
  // 费率消耗 = 毛收益(0%费率) - 含费收益(精确关系: 含费profit = 毛profit - 费率消耗)
  var shares0 = buyAmount / closeBuy;
  var profit0 = shares0 * closeSell - buyAmount;
  var feeCost = profit0 - profitNew;
  return { profit: Math.round(profitNew * 10000) / 10000, return_pct: Math.round(returnPctNew * 10000) / 10000, fee_cost: Math.round(feeCost * 10000) / 10000 };
}

// 凯利公式(复用 signal_kelly_backtest.py _compute_kelly)
function _kellyComputeKelly(winRate, plRatio) {
  var p = winRate, q = 1 - p, b = (plRatio && plRatio > 0) ? plRatio : 0;
  var fStar = b > 0 ? (p - q / b) : 0;
  fStar = Math.max(0, Math.min(1, fStar));
  var halfKelly = fStar / 2 * 100;
  halfKelly = Math.max(0, Math.min(90, halfKelly));
  var tier = halfKelly < 30 ? "保守" : halfKelly < 60 ? "均衡" : "激进";
  return { f_star: Math.round(fStar * 10000) / 10000, half_kelly: Math.round(halfKelly * 100) / 100, kelly_tier: tier };
}

// 最大同时持仓(复用 _max_concurrent, 扫描线)
// 优化: 按日期分桶(buy/sell计数)而非对2n个事件排序, 只排序出现的日期数(远小于2n), 语义逐位等价
// (同日 FIFO 强平+新买入 场景必须【先减后加】——与仿真内核 _kellyAihlineFifoCap 同序, cap后峰值精确回到 cap 内笔数; 普通模式无同日买卖, 顺序无关, 对 A-F 基线零漂移)
function _kellyMaxConcurrent(trades) {
  if (!trades.length) return 0;
  var SENTINEL = "99999999", deltas = {}, dates = [];
  for (var i = 0; i < trades.length; i++) {
    var bd = trades[i].buy_date;
    var sd = trades[i].sell_date || SENTINEL;
    var db = deltas[bd];
    if (!db) { db = deltas[bd] = { b: 0, s: 0 }; dates.push(bd); }
    db.b++;
    var ds = deltas[sd];
    if (!ds) { ds = deltas[sd] = { b: 0, s: 0 }; dates.push(sd); }
    ds.s++;
  }
  dates.sort();
  var cur = 0, maxConc = 0;
  for (var i = 0; i < dates.length; i++) {
    var d = deltas[dates[i]];
    cur -= d.s;  // 先减当日卖出/强平
    cur += d.b;  // 再加当日买入
    if (cur > maxConc) maxConc = cur;
  }
  return maxConc;
}

// 日期差天数(YYYYMMDD 字符串)
function _kellyDateDiffDays(d1, d2) {
  try {
    var dd1 = new Date(+d1.slice(0, 4), +d1.slice(4, 6) - 1, +d1.slice(6, 8));
    var dd2 = new Date(+d2.slice(0, 4), +d2.slice(4, 6) - 1, +d2.slice(6, 8));
    return Math.max(Math.round((dd2 - dd1) / 86400000), 0);
  } catch (e) { return 0; }
}

// 从 trade 跨度算年数(复用 _years_from_trades)
function _kellyYearsFromTrades(trades) {
  if (!trades.length) return 1.0;
  var dates = trades.map(function (t) { return t.buy_date; });
  var dMin = dates.reduce(function (a, b) { return a < b ? a : b; });
  var dMax = dates.reduce(function (a, b) { return a > b ? a : b; });
  var days = _kellyDateDiffDays(dMin, dMax);
  return Math.max(days / 365.25, 1.0 / 365.25);
}

// 最大回撤(复用 _max_drawdown; 2026-08-13: 总投入=每笔 amount 求和, 每日资金池等分口径每笔已摊薄自动算对, 不按"笔数×1万")
function _kellyMaxDrawdown(trades, buyAmount) {
  if (!trades.length) return { abs: 0, pct: 0 };
  var sorted = trades.slice().sort(function (a, b) {
    var da = a.sell_date || "99999999", db = b.sell_date || "99999999";
    return da < db ? -1 : da > db ? 1 : 0;
  });
  var cumulative = 0, peak = 0, maxDdAbs = 0;
  for (var i = 0; i < sorted.length; i++) {
    cumulative += sorted[i].profit;
    if (cumulative > peak) peak = cumulative;
    var dd = peak - cumulative;
    if (dd > maxDdAbs) maxDdAbs = dd;
  }
  var totalInvest = 0;
  for (var j = 0; j < trades.length; j++) totalInvest += (trades[j].amount || buyAmount);
  var pct = totalInvest > 0 ? maxDdAbs / totalInvest * 100 : 0;
  return { abs: Math.round(maxDdAbs * 10000) / 10000, pct: Math.round(pct * 10000) / 10000 };
}

// 年化收益率(复用 _annualized_return, D修正: 基于峰值资金收益率开方非平均化)
// r = return_pct_max_holding / 100 (峰值资金收益率=总盈亏/峰值占用资金*100)
// 负收益 r<=-1 返回0(无法开方)
function _kellyAnnualizedReturn(returnPctMaxHolding, periodKey, trades) {
  var r = returnPctMaxHolding / 100;
  if (r <= -1) return 0;
  if (periodKey === "y1") return Math.round(returnPctMaxHolding * 10000) / 10000;
  if (periodKey === "y3") return Math.round((Math.pow(1 + r, 1 / 3) - 1) * 100 * 10000) / 10000;
  if (periodKey === "y5") return Math.round((Math.pow(1 + r, 1 / 5) - 1) * 100 * 10000) / 10000;
  if (periodKey === "y10") return Math.round((Math.pow(1 + r, 1 / 10) - 1) * 100 * 10000) / 10000;
  var years = _kellyYearsFromTrades(trades);
  if (years <= 0) return Math.round(returnPctMaxHolding * 10000) / 10000;
  return Math.round((Math.pow(1 + r, 1 / years) - 1) * 100 * 10000) / 10000;
}

// 完整统计计算(复用 _compute_stats, ~120行)
function _kellyComputeStats(trades, periodKey, buyAmount) {
  var n = trades.length;
  if (n === 0) {
    return { n: 0, win_count: 0, lose_count: 0, win_rate: 0, pl_ratio: null,
      mean_return: 0, total_return: 0, avg_hold_days: 0, kelly_f: 0, half_kelly: 0, kelly_tier: "保守",
      max_single_win: 0, max_single_loss: 0, win_streak_max: 0, lose_streak_max: 0,
      total_invest: 0, total_profit: 0, total_return_pct: 0, max_concurrent: 0, max_concurrent_capital: 0,
      return_pct_max_holding: 0, annualized_return: 0, sharpe: 0, max_drawdown: 0, max_drawdown_pct: 0, calmar: 0,
      holding_count: 0, holding_capital: 0, total_fee_cost: 0 };
  }
  var wins = [], losses = [];
  for (var i = 0; i < trades.length; i++) {
    if (trades[i].profit > 0) wins.push(trades[i]); else losses.push(trades[i]);
  }
  var winCount = wins.length, loseCount = losses.length, winRate = winCount / n;
  var avgWin = winCount ? wins.reduce(function (s, t) { return s + t.return_pct; }, 0) / winCount : 0;
  var avgLossAbs = loseCount ? Math.abs(losses.reduce(function (s, t) { return s + t.return_pct; }, 0) / loseCount) : 0;
  var plRatio;
  if (loseCount > 0 && avgLossAbs > 0) plRatio = avgWin / avgLossAbs;
  else if (winCount > 0 && loseCount === 0) plRatio = 999.0;
  else plRatio = null;
  var meanReturn = trades.reduce(function (s, t) { return s + t.return_pct; }, 0) / n;
  // 2026-08-13: 总投入=每笔 amount 求和(每日资金池等分口径每笔=10000/当日保留数, 自动正确; fixed口径下每笔=buyAmount)
  var totalAmount = trades.reduce(function (s, t) { return s + (t.amount || buyAmount); }, 0);
  var totalReturn = totalAmount > 0 ? trades.reduce(function (s, t) { return s + t.profit; }, 0) / totalAmount * 100 : 0;
  var avgHold = trades.reduce(function (s, t) { return s + t.hold_days; }, 0) / n;
  var kelly = _kellyComputeKelly(winRate, plRatio);
  var maxWin = trades.reduce(function (m, t) { return Math.max(m, t.return_pct); }, 0);
  var maxLoss = trades.reduce(function (m, t) { return Math.min(m, t.return_pct); }, 0);
  // 连胜连败(按 buy_date 排序)
  var sortedTrades = trades.slice().sort(function (a, b) { return a.buy_date < b.buy_date ? -1 : 1; });
  var winStreak = 0, loseStreak = 0, maxWinStreak = 0, maxLoseStreak = 0;
  for (var i = 0; i < sortedTrades.length; i++) {
    if (sortedTrades[i].profit > 0) { winStreak++; loseStreak = 0; maxWinStreak = Math.max(maxWinStreak, winStreak); }
    else { loseStreak++; winStreak = 0; maxLoseStreak = Math.max(maxLoseStreak, loseStreak); }
  }
  var totalInvest = Math.round(totalAmount * 10000) / 10000;
  var totalProfit = Math.round(trades.reduce(function (s, t) { return s + t.profit; }, 0) * 10000) / 10000;
  var totalReturnPct = totalInvest > 0 ? Math.round(totalProfit / totalInvest * 100 * 10000) / 10000 : 0;
  var maxConc = _kellyMaxConcurrent(trades);
  var maxConcurrentCapital = _kellyMaxConcurrentCapital(trades);
  var returnPctMaxHolding = maxConcurrentCapital > 0 ? Math.round(totalProfit / maxConcurrentCapital * 100 * 10000) / 10000 : 0;
  var annualized = _kellyAnnualizedReturn(returnPctMaxHolding, periodKey, trades);
  // 夏普
  var returns = trades.map(function (t) { return t.return_pct; });
  var sharpe = 0;
  if (n > 1) {
    var mean = returns.reduce(function (s, x) { return s + x; }, 0) / n;
    var variance = returns.reduce(function (s, x) { return s + Math.pow(x - mean, 2); }, 0) / (n - 1);
    var std = Math.sqrt(variance);
    sharpe = std > 0 ? Math.round(mean / std * 10000) / 10000 : 0;
  }
  var dd = _kellyMaxDrawdown(trades, buyAmount);
  var calmar = dd.pct > 0 ? Math.round(annualized / dd.pct * 10000) / 10000 : 0;
  var holdingTrades = trades.filter(function (t) { return !t.sell_date; });
  var holdingCount = holdingTrades.length;
  var holdingCapital = holdingTrades.reduce(function (s, t) { return s + (t.amount || buyAmount); }, 0);
  return {
    n: n, win_count: winCount, lose_count: loseCount,
    win_rate: Math.round(winRate * 10000) / 10000,
    pl_ratio: plRatio != null ? Math.round(plRatio * 100) / 100 : null,
    mean_return: Math.round(meanReturn * 10000) / 10000,
    total_return: Math.round(totalReturn * 10000) / 10000,
    avg_hold_days: Math.round(avgHold * 100) / 100,
    kelly_f: kelly.f_star, half_kelly: kelly.half_kelly, kelly_tier: kelly.kelly_tier,
    max_single_win: Math.round(maxWin * 10000) / 10000, max_single_loss: Math.round(maxLoss * 10000) / 10000,
    win_streak_max: maxWinStreak, lose_streak_max: maxLoseStreak,
    total_invest: totalInvest, total_profit: totalProfit, total_return_pct: totalReturnPct,
    max_concurrent: maxConc, max_concurrent_capital: maxConcurrentCapital,
    return_pct_max_holding: returnPctMaxHolding,
    annualized_return: annualized, sharpe: sharpe,
    max_drawdown: dd.abs, max_drawdown_pct: dd.pct, calmar: calmar,
    holding_count: holdingCount, holding_capital: holdingCapital,
    total_fee_cost: Math.round(trades.reduce(function (s, t) { return s + (t.fee_cost || 0); }, 0) * 10000) / 10000,
  };
}

// 降亏标志v3 helper: 买入星期(Python weekday约定 0=周一 1=周二 2=周三)
function _kellyBuyWeekday(buyDateStr) {
  if (!buyDateStr) return -1;
  var s = String(buyDateStr);
  if (s.length < 8) return -1;
  var y = parseInt(s.substring(0, 4), 10);
  var m = parseInt(s.substring(4, 6), 10);
  var d = parseInt(s.substring(6, 8), 10);
  var jsDay = new Date(y, m - 1, d).getDay(); // JS: 0=Sun...6=Sat
  return (jsDay + 6) % 7; // 转Python: 0=Mon 1=Tue 2=Wed...
}
// 降亏标志v3 helper: 买入价位五分位(全数据quintile精确边界)
function _kellyBuypriceBin(price) {
  if (price == null) return "";
  if (price <= 0.841441) return "vlow";
  if (price <= 1.015314) return "low";
  if (price <= 1.194593) return "mid";
  if (price <= 1.446645) return "high";
  return "vhigh";
}
// 降亏标志v3 helper: 从quadrant keys构建trade维度查找map(独立遍历所有quadrant key,非dedup内)
function _kellyBuildTradeDims(td, fIdx) {
  var dims = {};
  var quads = td.quadrants || {};
  for (var qk in quads) {
    var parts = qk.split('_');
    var dimType = parts[0]; // rating, etf, sig, mkt
    var dimVal = parts.slice(1).join('_'); // high, mid, low, a, industry, etc.
    for (var mk in quads[qk]) {
      var arr = quads[qk][mk];
      for (var i = 0; i < arr.length; i++) {
        var t = arr[i];
        var key = (t[fIdx.signal_date] || "") + '|' + (t[fIdx.index_id] || "") + '|' + (t[fIdx.signal] || "") + '|' + (t[fIdx.buy_date] || "") + '|' + (t[fIdx.etf_code] || "") + '|' + (t[fIdx.sell_date] || "");
        if (!dims[key]) dims[key] = {};
        dims[key][dimType] = dimVal;
      }
    }
  }
  return dims;
}
// 降亏过滤默认state(AI宏=新默认, 2026-08-12用户拍板"替换默认(AI宏=新默认)"; 数据支撑 /tmp/agent-progress-kelly-ai-macro.md):
// 默认开启 positionCap(每日只买最优K个,K=1主推) + 3个降亏推荐基础(追关注×熊市交叉/1月中旬+中评级/1月中旬+追关注/n2 11月+追关注+行业)
// + 3元(2026-08-13 穷举v2 加入默认: r7 5月强化+3稳定非5月 + exclAuxCross 辅关注×3/5月交叉 + greedy15 Greedy-15组合),
// 其余降亏toggle默认false(数据证明负边际/过拟合, 见 docs/kelly/position/kelly-position-cap-k-sensitivity.md)
// AI宏(含3元) vs 旧默认(+A45/A5): 穷举v2(406,336配置全扫, 固定每笔1万口径) 3元叠加AI_BASE 最优: K1 A=77.36%/F=73.68%/G=47.40%; K2 A=66.22%/F=63.76%/G=42.08%; K3(默认) A=68.40%(2026-08-13 定默认)
// ⚠ 2026-08-14 #48: 以上穷举v2数值为 fixed(每笔1万)口径历史决策依据; 每日池(等分+top-K)恢复后已重算 docs/kelly/position/kelly-dailypool-exhaustive-rerun.md §2: 每日池 A K1=86.60%/K2=74.93%/K3=78.91%/K4=79.96%。
// ⚠ 2026-08-14 #BC B包: 上述 #48 每日池数值未含最低佣金5元费率重算(比例法); 静态快照改为费率重算口径后 K1=86.60%/K2=67.61%/K3=66.24%/K4=63.17%(含min佣金, §22 与动态一致);
// ⚠ 2026-08-14 #BC C包: 默认 K 取 1(#50 原不改默认; 用户"主推K1"拍板 2026-08-14 → 默认档改 1)
// ⚠ v1.1.5(2026-08-24 用户拍板): 默认组合从八键(v1.1.2 AI宏5+3+1)切换为 NEW14(NEW 14键)。
//   依据=mine28(AUTO 状态轮动样本外全 FAIL+天花板作弊仍输单持→维持单模式)+mine30 记分板(NEW14 全史第一
//   +122,648/mdd -4,178 vs 八键 +66,530/-18,190, 费后 K1 V2 回补 cap13 口径)。
//   构成=hist 键 6(r10May6NonMay/greedy15/janMidSpecial/k2c5HkChase/k3ConceptBuy/declinePhaseSpecial)
//   +规则键 8(n1NorthOutflow/t1LowTurnSpecial/d1LowDivYield/q1QvixLowPct/h1VolChgHighA/m1MarginDownBull/p1LowDivBackup/r2bSpecialGlobal),
//   与 common.js _KELLY_FADE_MODE_PRESETS new14 预设逐位一致(单源校验 scripts/check_loss_rules_vs_mining.py 同源规格)。
//   八键成员中不在 NEW14 的 5 个(n2/janMidRating/r7/exclAuxCross/exclSpecialBear)转 false, 可经模式下拉「8键」一键回选(不删档 §23.7)。
function _kellyDefaultFilters() {
  return {
    // round3新候选(11月系, 2026-08-10 verify验证: A45 5.75>A5 5.49); 2026-08-12 曾并入默认, v1.1.5 起=非默认(可手动开)
    a5NovMidSpecial: false, a45NovMidLateSpecial: false,
    // v3新标志; n2 2026-08-12 并入八键默认 → v1.1.5 起移出默认(NEW14 不含, 经「8键」档可回选)
    n1MarTueHigh: false, n2NovSpecialIndustry: false, r8PureNonMay: false,
    n3NovSpecialMon: false, n4AMay: false, r7MayReinforced: false,
    n5MayVlow: false, n6MidMay: false,
    r10May6NonMay: true, // v1.1.5 NEW14 hist键(5月+6非5月组合)
    // 现有标志; exclAuxCross/exclSpecialBear 2026-08-13/08-12 曾并入八键默认 → v1.1.5 起移出默认(NEW14 不含)
    excludeAuxCross: false, excludeSpecialBear: false, excludeMonth: false,
    excludeAux: false, marketTiming: false, excludeRatingLow: false,
    // v4新标志(第一梯队: Greedy-7组合/V4-C简化/V4-B)
    greedy7: false, v4cSimple: false, v4b: false,
    // v4新标志(第二梯队: Greedy-10组合/V4-D/V4-J/V4-I)
    greedy10: false, v4d: false, v4j: false, v4i: false,
    // v4新标志(第三梯队); greedy15 2026-08-13 并入 → v1.1.5 起=NEW14 成员继续默认开
    greedy15: true, v4f: false, v4g: false, v4m: false, v4k: false,
    // 1月调整; janMidRating 移出默认(v1.1.5), janMidSpecial=NEW14 成员继续默认开
    janMidRating: false, janMidSpecial: true,
    // positionCap 仓位控制过滤(2026-08-12): 同日只买最优K个(基笔级,模式之前统一生效), K可配置1-4默认3; 默认开启
    // 2026-08-14 #BC C包: 主推 K1(收益率最高) → 默认档 3→1(v1.1.5 维持不变)
    positionCap: true, positionCapK: 1,
    // K2C5 港股追涨 / K3 主关注×概念 (2026-08-15 #86 新增); v1.1.5 起 K2C5=NEW14 成员继续默认开, K3=NEW14 成员转默认开
    k2c5HkChase: true, k3ConceptBuy: true,
    // v1.1.2(2026-08-17 用户拍板) 三键: excludeSpecialBear 语义升四档(曾默认开, v1.1.5 起移出默认——NEW14 用
    //   declinePhaseSpecial 替代其「下降期」拦截位且不保留熊市主跌段); 备选键 legacyMa60Special 维持默认关。
    // #69(2026-08-19) cyb 四档版 excludeSpecialBearCyb 维持默认关非默认推荐。
    // v1.1.5: declinePhaseSpecial 转默认开(NEW14 hist 键, 下降期×追关注全市场)。
    legacyMa60Special: false, declinePhaseSpecial: true, excludeSpecialBearCyb: false,
    // #xx(2026-08-22 用户拍板) 新增第 5 个降亏键 bullAuxBackupStop(默认关, 纯新增 §23.7): 牛市·主升×(辅买∪备买)全停——
    //   hs300四档=「牛市·主升」 且 signal∈{buy_aux,buy_backup} → 该买入信号被拦下(时段级全停)。
    //   判定源=trades market_tier 字段(后端已按 A股类注入, 非A股为 "" 天然不命中 = A股限定, 与主键 excludeSpecialBear 同构守卫)。
    //   ⚠作用域: 仅适用 mode A-F(A股短线); G/H/I 长线不适配不套用(挖掘报告 §6.4: G/I 全史 +3,624 长线持有逻辑不同)——
    //   豁免由统计链桶过滤层实现(见 _kellyStatsFor passesFadeNoBull / 弹窗 _pcFadeFn), 谓词本身不带 mode。
    //   数据支撑: docs/kelly/analysis/sim-window-loss-mining-20260822.md(补位口径=前端真实链路: mode A K1 5-8月 -5,166→-1,030 / 4月零误伤 /
    //   2026全年 +5,626→+7,490 / 全史 +66,530→+73,103(+6,573) / 五窗全改善; 理想对照=被拦笔直接消失口径: -256 / +10,596 / +76,426(+9,895))。默认关供用户实测。
    bullAuxBackupStop: false,
    // T1(2026-08-23 用户拍板·AI降亏方法池57→全量) 20 条新键; v1.1.5 起 NEW14 的 7 条规则键转默认开
    //   (n1/t1/d1/q1/h1/m1/p1/r2b 共 8 条中 r2b 也在内——其余 12 条维持默认关 §23.7 非默认成员不动):
    //   规格单源=scripts/loss_rules.py(RULE_SPECS/QTH 阈值快照), 前端经 data/kelly_loss_features.json
    //   的 meta.rules 读同一份规格驱动判定(spec-driven, 与 queries.py rule_hit 同构), 不在前端硬编码阈值。
    //   ⚠语义与挖掘版逐字对齐(层2 校验 scripts/check_loss_rules_vs_mining.py 5100 行全等): 特征按 buy_date 查值
    //   (回测 buy_date≡signal_date)/缺失值不拦/无月门(独立于上方 monthMask 门控组)。
    n1NorthOutflow: true, t1LowTurnSpecial: true, d1LowDivYield: true, q1QvixLowPct: true,
    h1VolChgHighA: true, m1MarginDownBull: true, d2LowDivBull: false, p1LowDivBackup: true,
    v1HighVol20: false, s1SentALow: false, r1VolRatioLow: false, r2bSpecialGlobal: true, r2gLowRatingQ3: false,
    n2NorthOutConcept: false, v2Vol20Gt25: false, s2SentHs300Low: false, w1BackupDecline: false,
    a1BullAllStop: false, v3Vol20LowPct: false, ad1AdlineHot: false,
    // X1(2026-08-24 mine29c 用户拍板·纯新增 §23.7 默认关; 同日用户拍板扩围剔 none+null): 整剔
    //   track_tier=none/null 象限(best ETF 无强关联/相关/近似档跟踪标的的信号=「有跟踪ETF」全卡,
    //   与首页筛选档4口径统一)——NEW14+1·15键可选档(new15)成员, 判定走 trades track_tier 列直读。
    //   数据支撑: 全史仅剔 17 笔毛 +584.62(净 +225.56), 主收益=回撤改善 mdd -4,178→-3,550(mine29c)。
    excludeTierNone: false
  };
}

// ===== 降亏过滤卡顿优化(方案A+B): 缓存 + 去冗余 + loading真显示 + 防重入 =====
// ① 按(qk,mode)只过滤一次, 5个period从过滤结果按cutoff取子集(扫描5->1遍)
// ② v3/v4特征预计算缓存: 每个trade的weekday/quintile/维度key只算一次, 消灭new Date/字符串拼接重复
// ③ feeParams未变时同一trade费率重算结果复用
// ④ filters+feeParams签名缓存stats: 连点命中直接复用不重算
// ⑤ loading真显示: 双rAF让loading先paint再执行同步重算
// ⑥ 防重入: busy flag防交错 + latest-wins(重算中再来点击记pending, 本轮跑完按最新状态再跑一轮)
var _kellyTradeFeatureCache = new Map();   // trade对象 -> 特征(只算一次)
var _kellyRecomputeCache = new Map();      // trade对象 -> {sig, r}(feeParams未变复用)
var _kellyStatsCacheKey = "";              // filters+feeParams签名
var _kellyStatsCacheVal = null;
var _kellyBucketStatsCache = new Map();    // (qk|mode) -> {feeSig, toggled, stats} 逐桶复用(仅被toggle改动影响的桶重算)
var _kellyRecomputeBusy = false;           // 防重入: 重算进行中
var _kellyRecomputePending = false;        // 重算中来新点击/改费率: 记待处理
// #49 fix(issue49): G/H/I 对比表 展开/收起状态(独立于开关, 由 9124 按钮点击控制, 重渲染 bar 时保持) — 默认收起
var _gihCompareOpen = false;

// 费率参数签名(判断是否变化, 变化才重算费率部分)
function _kellyFeeSig(fp) {
  return (fp.commission_rate || 0) + "|" + (fp.min_commission || 0) + "|" + (fp.slippage || 0) + "|" + (fp.transfer_fee_rate_sh || 0) + "|" + (fp.stamp_duty_rate || 0);
}

// 清空计算缓存(重新加载trades.json时调用, 防脏缓存)
function _kellyClearComputeCaches() {
  if (_kellyTradeFeatureCache) _kellyTradeFeatureCache.clear();
  if (_kellyRecomputeCache) _kellyRecomputeCache.clear();
  _kellyStatsCacheKey = "";
  _kellyStatsCacheVal = null;
  if (_kellyBucketStatsCache) _kellyBucketStatsCache.clear();
}

// 两trade数组是否逐元素同一(同对象引用同顺序; toggle未删任何trade时即复用桶stats)
function _kellySameTradeArray(a, b) {
  if (a === b) return true;
  if (!a || !b || a.length !== b.length) return false;
  for (var i = 0; i < a.length; i++) { if (a[i] !== b[i]) return false; }
  return true;
}

// 预计算单个trade的v3/v4过滤所需全部特征(纯函数, 只算一次)
function _kellyTradeFeatures(t, fIdx, _tradeDims) {
  var bd = String(t[fIdx.buy_date] || "");
  var mm = bd.substring(4, 6);
  var dd = parseInt(bd.substring(6, 8), 10) || 0; // 日(round3 A5/A45 11月中旬/中下旬范围)
  var sig = fIdx.signal != null ? String(t[fIdx.signal] || "") : "";
  var wd = _kellyBuyWeekday(bd);
  var bpb = fIdx.buy_price != null ? _kellyBuypriceBin(t[fIdx.buy_price]) : "";
  var mktD = "", ratD = "";
  if (_tradeDims) {
    var dk = (t[fIdx.signal_date] || "") + '|' + (t[fIdx.index_id] || "") + '|' + sig + '|' + bd + '|' + (t[fIdx.etf_code] || "") + '|' + (t[fIdx.sell_date] || "");
    var dims = _tradeDims[dk] || {};
    mktD = dims.mkt || ""; ratD = dims.rating || "";
  }
  var ts = fIdx.track_score != null ? Number(t[fIdx.track_score]) : 999;
  var etfD = fIdx.track_tier != null ? String(t[fIdx.track_tier] || "") : "";
  var q = mm ? Math.ceil(parseInt(mm, 10) / 3) : 0;
  return { mm: mm, dd: dd, sig: sig, wd: wd, bpb: bpb, mktD: mktD, ratD: ratD, ts: ts, etfD: etfD, q: q };
}

// ===== T1(2026-08-23) AI降亏 20 条新键·特征数据通道 + spec-driven 谓词 =====
// 数据=data/kelly_loss_features.json(scripts/gen_kelly_loss_features.py 产出, R2 data/ 前缀上线):
//   meta.rules=规格单源(与 scripts/loss_rules.py RULE_SPECS 同源, queries.py rule_hit 同构判定),
//   features=12 特征全史序列{feat: {YYYYMMDD: value}}。阈值=硬编码快照不滚动重算(§23.6 口径一致性)。
// 加载策略: renderSigKellyLab 拉凯利数据时并行预取(state.kellyLossFeatData); 失败容忍=null
//   (规格单源=meta.rules, JSON 加载失败时 spec 取不到一律 return false 不拦——特征类键与
//    纯字段键 w1/a1/r2b/r2g 同此诚实降级; 「纯字段键照判」仅对后端 queries.py 成立,
//    因 loss_rules.py 内存规格不依赖 JSON)。
// state.kellyLossFeatData / state.kellyLossSpecMap 由 _kellyEnsureLossFeatData 填充
async function _kellyEnsureLossFeatData() {
  if (state.kellyLossFeatData !== undefined && state.kellyLossFeatData !== null) return state.kellyLossFeatData;
  if (!state.kellyLossFeatPromise) {
    state.kellyLossFeatPromise = fetchJSON("./data/kelly_loss_features.json").then((d) => {
      state.kellyLossFeatData = d || null;
      state.kellyLossSpecMap = {};
      ((d && d.meta && d.meta.rules) || []).forEach((r) => { state.kellyLossSpecMap[r.key] = r; });
      return state.kellyLossFeatData;
    }).catch(() => { state.kellyLossFeatData = null; return null; });
  }
  await state.kellyLossFeatPromise;
  return state.kellyLossFeatData;
}
// spec-driven 谓词: 与 Python loss_rules.rule_hit 逐分支同构(缺失值→不拦; low=v<th high=v>th;
// R2g ts 缺失视为 999; X1 track_tier spec 支持 str/Array 多值, ctx ""(无映射)→不命中、"null"(极弱/无分)→命中)。ctx={sig,mkt,tier,track_tier,date,smonth,rating,ts}。
// T1+X1 新键清单单源(JS 侧): [filterKey, toggleCls后缀]; _kellyDefaultFilters 内 21 个 false 显式条目
//   与此一一对应, 新增键须同步两处 + scripts/loss_rules.py RULE_SPECS(§22 单源咬合)。
const _KELLY_LOSS_NEW_KEYS = [
  ["r2gLowRatingQ3", "r2gq3"],
  ["n1NorthOutflow", "n1out"], ["t1LowTurnSpecial", "t1turn"], ["d1LowDivYield", "d1div"],
  ["q1QvixLowPct", "q1qvix"], ["h1VolChgHighA", "h1volchg"], ["m1MarginDownBull", "m1margin"],
  ["d2LowDivBull", "d2div"], ["p1LowDivBackup", "p1div"], ["v1HighVol20", "v1vol20"],
  ["s1SentALow", "s1senta"], ["r1VolRatioLow", "r1volratio"], ["r2bSpecialGlobal", "r2bglobal"],
  ["n2NorthOutConcept", "n2nout"], ["v2Vol20Gt25", "v2vol25"], ["s2SentHs300Low", "s2sent300"],
  ["w1BackupDecline", "w1backup"], ["a1BullAllStop", "a1bull"], ["v3Vol20LowPct", "v3vollow"],
  ["ad1AdlineHot", "ad1hot"],
  // X1(mine29c 2026-08-24, NEW14+1·15键可选档): 整剔 track_tier=none 象限, 判定走 ctx.track_tier
  ["excludeTierNone", "xtnone"]
];
function _kellyLossRuleHit(key, ctx) {
  const spec = state.kellyLossSpecMap && state.kellyLossSpecMap[key];
  if (!spec) return false;                       // 规格未加载(特征JSON缺失/键未知) → 不拦, 诚实降级
  if (spec.feature) {
    const series = state.kellyLossFeatData && state.kellyLossFeatData.features && state.kellyLossFeatData.features[spec.feature];
    const v = series ? series[String(ctx.date || "")] : null;
    if (v == null) return false;                 // FR 工厂语义: 特征缺失该日 → 整条不命中
    if (spec.direction === "low") { if (!(v < spec.threshold)) return false; }
    else { if (!(v > spec.threshold)) return false; }
  }
  if (spec.sig != null && String(ctx.sig || "") !== spec.sig) return false;
  if (spec.tier != null && String(ctx.tier || "") !== spec.tier) return false;
  if (spec.mkt != null && String(ctx.mkt || "") !== spec.mkt) return false;
  if (spec.track_tier != null) {  // X1(2026-08-24 扩围): spec 支持 str 或 Array 多值(none/null); ctx ""=无映射不命中, "null"=极弱/无分档命中
    var _ctxTt = String(ctx.track_tier || "");
    if (Array.isArray(spec.track_tier) ? spec.track_tier.indexOf(_ctxTt) < 0 : _ctxTt !== spec.track_tier) return false;
  }
  if (spec.rating != null) {
    if (String(ctx.rating || "") !== spec.rating) return false;
    const tv = (ctx.ts == null || ctx.ts === "") ? 999 : Number(ctx.ts);
    if (!(tv < spec.max_ts)) return false;       // mine22: 空 ts 视为 999 → 不命中
    if ((spec.months || []).indexOf(String(ctx.smonth || "")) < 0) return false;  // signal_date 月(mine22 str(t[0]))
  }
  return true;
}

// 月门控: 每个v3/v4谓词都有月或季度约束(逐条核对), 该trade月份不可能匹配任何活跃toggle则直接通过,
// 跳过昂贵的weekday/quintile/维度特征计算(单toggle点击如n1MarTueHigh只匹配03月, 11/12交易直接跳过)
var _kellyMonthMask = {
  a5NovMidSpecial: 1 << 10,                         // 11
  a45NovMidLateSpecial: 1 << 10,                    // 11
  n1MarTueHigh: 1 << 2,                             // 03
  n2NovSpecialIndustry: 1 << 10,                    // 11
  r8PureNonMay: (1 << 2) | (1 << 10),               // 03,11
  n3NovSpecialMon: 1 << 10,                         // 11
  n4AMay: 1 << 4,                                   // 05
  r7MayReinforced: (1 << 4) | (1 << 2) | (1 << 10), // 05,03,11
  n5MayVlow: 1 << 4,                                // 05
  n6MidMay: 1 << 4,                                 // 05
  r10May6NonMay: (1 << 4) | (1 << 2) | (1 << 10),   // 05,03,11
  v4cSimple: 1 << 2,                                // 03
  v4b: 1 << 4,                                      // 05
  greedy7: (1 << 4) | (1 << 10) | (1 << 2) | (1 << 0) | (1 << 3) | (1 << 5), // 05,11,03,01,04,06(q2)
  v4d: 1 << 11,                                     // 12
  v4j: 1 << 4,                                      // 05
  v4i: 1 << 4,                                      // 05
  greedy10: (1 << 4) | (1 << 10) | (1 << 2) | (1 << 0) | (1 << 3) | (1 << 5) | (1 << 11), // +12
  v4f: 1 << 5,                                      // 06
  v4g: (1 << 0) | (1 << 1) | (1 << 2),              // q1=01,02,03
  v4m: 1 << 8,                                      // 09
  v4k: 1 << 0,                                      // 01
  greedy15: (1 << 0) | (1 << 1) | (1 << 2) | (1 << 3) | (1 << 4) | (1 << 5) | (1 << 8) | (1 << 10) | (1 << 11), // greedy10+q1+09
  janMidRating: 1 << 0,                             // 01
  janMidSpecial: 1 << 0,                            // 01
  // K2C5/K3 无月份约束(按 signal×market 过滤, 全年适用), 全12月掩码 0x1FFF, 防月门控短路跳过 hk/concept 交易遗漏过滤
  k2c5HkChase: 0x1FFF, k3ConceptBuy: 0x1FFF
};
function _kellyActiveMonthMask(filters) {
  var mask = 0;
  for (var k in _kellyMonthMask) { if (filters[k]) mask |= _kellyMonthMask[k]; }
  return mask;
}

// 降亏toggle过滤谓词(不含period cutoff, 语义与原filter的toggle部分逐条一致)
// featCache: 特征缓存Map(trade对象->特征), v3/v4开启时才惰性取/算特征(和原filter一致: 全关时零特征开销)
function _kellyPassesFadeFilters(t, fIdx, filters, featCache, _tradeDims, monthMask) {
  // 前置简单键 spec-driven(T3-1 迁移): 规格单源=common.js _KELLY_FADE_LEGACY_SPECS(gate=0), 判定与原逐条
  // 硬编码逐位一致(parity 校验脚本断言)。ctx 惰性组装=全关时零开销(与原行为同); 原 fIdx.xxx != null 守卫
  // 为死代码(fields 静态含全列), ctx 组装侧已保留同源守卫语义。
  var _frontCtx = null;
  for (var _fki = 0; _fki < _KELLY_FADE_FRONT_KEY_ORDER.length; _fki++) {
    var _fkF = _KELLY_FADE_FRONT_KEY_ORDER[_fki];
    if (!filters[_fkF]) continue;
    if (!_frontCtx) {
      _frontCtx = {
        sig: fIdx.signal != null ? String(t[fIdx.signal] || "") : "",
        mm: fIdx.buy_date != null ? String(t[fIdx.buy_date] || "").substring(4, 6) : "",
        rating: fIdx.rating != null ? String(t[fIdx.rating] || "") : "",
        tier: fIdx.market_tier != null ? String(t[fIdx.market_tier] || "") : "",
        tierAll: fIdx.market_tier_all != null ? String(t[fIdx.market_tier_all] || "") : "",
        tierCyb: fIdx.market_tier_cyb != null ? String(t[fIdx.market_tier_cyb] || "") : "",
        mstate: fIdx.market_state != null ? t[fIdx.market_state] : undefined
      };
    }
    if (_tdsFadeSpecHit(_fkF, _frontCtx)) return false;
  }
  // v3新9 toggle(比值>3, 按比值倒序: 10.06>6.63>5.87>5.24>4.67>4.18>4.02>3.35>3.31)
  var _v3On = filters.n1MarTueHigh || filters.n2NovSpecialIndustry || filters.r8PureNonMay || filters.n3NovSpecialMon || filters.n4AMay || filters.r7MayReinforced || filters.n5MayVlow || filters.n6MidMay || filters.r10May6NonMay;
  // v4新12 toggle(三梯队全量上线)
  var _v4On = filters.greedy7 || filters.greedy10 || filters.greedy15 || filters.v4cSimple || filters.v4b || filters.v4d || filters.v4j || filters.v4i || filters.v4f || filters.v4g || filters.v4m || filters.v4k;
  // round3新2 toggle(11月系, 2026-08-10 verify验证: A45 5.75 / A5 5.49)
  var _r3On = filters.a5NovMidSpecial || filters.a45NovMidLateSpecial;
  // 1月调整2 toggle(2026-08-11 元素级重组: 1月中旬(11-20日)+中评级 / 1月中旬+追关注)
  var _janOn = filters.janMidRating || filters.janMidSpecial;
  // K2C5/K3 按 signal×market 过滤, 需 mktD 特征(2026-08-15 #86)才能判定, 故并入特征计算触发集合(坑1: 否则 _mktD3 惰性不计算, 新键永不生效)
  var _k2On = filters.k2c5HkChase || filters.k3ConceptBuy;
  if (_v3On || _v4On || _r3On || _janOn || _k2On) {
    // 月门控: 该trade月份不在任何活跃toggle的月集合内 => 不可能命中任何谓词, 直接通过(跳过昂贵特征)
    if (monthMask) {
      var _mmG = (t[fIdx.buy_date] || "").substring(4, 6);
      var _mmInt = _mmG ? parseInt(_mmG, 10) : 0;
      if (_mmInt && !(monthMask & (1 << (_mmInt - 1)))) return true;
    }
    // ② 特征惰性预计算缓存: 每个trade的weekday/quintile/维度key只算一次, 后续O(1)查表
    var feats = featCache.get(t);
    if (!feats) { feats = _kellyTradeFeatures(t, fIdx, _tradeDims); featCache.set(t, feats); }
    var _mm3 = feats.mm, _dd3 = feats.dd, _sig3 = feats.sig, _wd3 = feats.wd, _bpb3 = feats.bpb;
    var _mktD3 = feats.mktD, _ratD3 = feats.ratD, _ts3 = feats.ts, _etfD3 = feats.etfD, _q3 = feats.q;
    // v3/v4/r3/jan/k2 共27键 spec-driven(T3-1 迁移): 规格单源=common.js _KELLY_FADE_LEGACY_SPECS(gate=1),
    // feats 字段名(mm/dd/sig/wd/bpb/mktD/ratD/ts/etfD/q)即评估器 ctx, 判定与原逐条硬编码逐位一致
    // (scripts/check_fade_predicate_parity.mjs 断言)。月门 mask 表与短路逻辑保留原值不动(mask 手工值
    // 含 q 组件隐含季度展开, 不从规格派生——见 common.js 头注)。
    for (var _gki = 0; _gki < _KELLY_FADE_GATE_KEY_ORDER.length; _gki++) {
      var _gkG = _KELLY_FADE_GATE_KEY_ORDER[_gki];
      if (filters[_gkG] && _tdsFadeSpecHit(_gkG, feats)) return false;
    }
  }
  // === T1(2026-08-23) AI降亏 20 条新键(spec-driven, 规格单源=scripts/loss_rules.py) ===
  // ⚠独立于上方月门控块: 新键语义与挖掘版逐字对齐=无月门(mine21 FR 工厂/mine22 build_r2 均无月份短路),
  //   故不能放进上面的 if(_v3On||...) 门控内(会被 monthMask 短路漏拦)。新键全关时 _m20On=false 零开销。
  var _m20On = filters.n1NorthOutflow || filters.t1LowTurnSpecial || filters.d1LowDivYield || filters.q1QvixLowPct ||
    filters.h1VolChgHighA || filters.m1MarginDownBull || filters.d2LowDivBull || filters.p1LowDivBackup ||
    filters.v1HighVol20 || filters.s1SentALow || filters.r1VolRatioLow || filters.r2bSpecialGlobal || filters.r2gLowRatingQ3 ||
    filters.n2NorthOutConcept || filters.v2Vol20Gt25 || filters.s2SentHs300Low || filters.w1BackupDecline ||
    filters.a1BullAllStop || filters.v3Vol20LowPct || filters.ad1AdlineHot || filters.excludeTierNone;
  if (_m20On) {
    // 组装判定 ctx(trades 字段直读; mktD 从 _tradeDims 维度表取, 与 _kellyTradeFeatures dk 同构):
    // tier=market_tier 字段(A股类限定注入, 非A股 "" 天然不命中); date=buy_date(≡signal_date);
    // smonth 取 signal_date 月(R2g 口径=mine22 str(t[0]))。
    var _bd20 = String(t[fIdx.buy_date] || "");
    var _sd20 = String(fIdx.signal_date != null ? t[fIdx.signal_date] || "" : "");
    var _sig20 = fIdx.signal != null ? String(t[fIdx.signal] || "") : "";
    var _mkt20 = "";
    if (_tradeDims) {
      var _dk20 = _sd20 + "|" + (fIdx.index_id != null ? t[fIdx.index_id] || "" : "") + "|" + _sig20 + "|" + _bd20 + "|" + (fIdx.etf_code != null ? t[fIdx.etf_code] || "" : "") + "|" + (fIdx.sell_date != null ? t[fIdx.sell_date] || "" : "");
      _mkt20 = (_tradeDims[_dk20] || {}).mkt || "";
    }
    var _ctx20 = {
      sig: _sig20,
      mkt: _mkt20,
      tier: fIdx.market_tier != null ? String(t[fIdx.market_tier] || "") : "",
      track_tier: (function () {  // X1 判定(trades 列直读三态: 显式 null→"null" 命中扩围后 X1; 缺列/越界 undefined→"" 诚实不命中; §23.13 口径统一)
        if (fIdx.track_tier == null) return "";
        var _v = t[fIdx.track_tier];
        return _v === undefined ? "" : (_v === null ? "null" : String(_v));
      })(),
      date: _bd20,
      smonth: _sd20.substring(4, 6),
      rating: fIdx.rating != null ? String(t[fIdx.rating] || "") : "",
      ts: fIdx.track_score != null ? t[fIdx.track_score] : null
    };
    if (filters.n1NorthOutflow && _kellyLossRuleHit("n1NorthOutflow", _ctx20)) return false;
    if (filters.t1LowTurnSpecial && _kellyLossRuleHit("t1LowTurnSpecial", _ctx20)) return false;
    if (filters.d1LowDivYield && _kellyLossRuleHit("d1LowDivYield", _ctx20)) return false;
    if (filters.q1QvixLowPct && _kellyLossRuleHit("q1QvixLowPct", _ctx20)) return false;
    if (filters.h1VolChgHighA && _kellyLossRuleHit("h1VolChgHighA", _ctx20)) return false;
    if (filters.m1MarginDownBull && _kellyLossRuleHit("m1MarginDownBull", _ctx20)) return false;
    if (filters.d2LowDivBull && _kellyLossRuleHit("d2LowDivBull", _ctx20)) return false;
    if (filters.p1LowDivBackup && _kellyLossRuleHit("p1LowDivBackup", _ctx20)) return false;
    if (filters.v1HighVol20 && _kellyLossRuleHit("v1HighVol20", _ctx20)) return false;
    if (filters.s1SentALow && _kellyLossRuleHit("s1SentALow", _ctx20)) return false;
    if (filters.r1VolRatioLow && _kellyLossRuleHit("r1VolRatioLow", _ctx20)) return false;
    if (filters.r2bSpecialGlobal && _kellyLossRuleHit("r2bSpecialGlobal", _ctx20)) return false;
    if (filters.r2gLowRatingQ3 && _kellyLossRuleHit("r2gLowRatingQ3", _ctx20)) return false;
    if (filters.n2NorthOutConcept && _kellyLossRuleHit("n2NorthOutConcept", _ctx20)) return false;
    if (filters.v2Vol20Gt25 && _kellyLossRuleHit("v2Vol20Gt25", _ctx20)) return false;
    if (filters.s2SentHs300Low && _kellyLossRuleHit("s2SentHs300Low", _ctx20)) return false;
    if (filters.w1BackupDecline && _kellyLossRuleHit("w1BackupDecline", _ctx20)) return false;
    if (filters.a1BullAllStop && _kellyLossRuleHit("a1BullAllStop", _ctx20)) return false;
    if (filters.v3Vol20LowPct && _kellyLossRuleHit("v3Vol20LowPct", _ctx20)) return false;
    if (filters.ad1AdlineHot && _kellyLossRuleHit("ad1AdlineHot", _ctx20)) return false;
    // X1(2026-08-24): 整剔 track_tier=none 象限(best ETF 无跟踪档位 → 该信号被拦)
    if (filters.excludeTierNone && _kellyLossRuleHit("excludeTierNone", _ctx20)) return false;
  }
  return true;
}

// ===== positionCap 仓位控制过滤 (2026-08-13; 金额口径=每日资金池等分+top-K, 2026-08-13用户纠正恢复原口径) =====
// 需求: "一天100个信号不可能买100次, 同日只买最优K个" + "一天2个信号就各买5000, 每天交易额不变"
// positionCap: 按 signal_date 分组当日全部基笔信号, 组内排序 track_score DESC→rating(high>mid>low)→signal类型(buy_backup>buy>buy_aux>buy_special)→buy_date ASC, 保留前K个
// 过滤时机: 基笔信号级(10卖出模式A-J共享同一批基笔信号, 过滤在模式之前统一生效; 同一信号同一天只算一次, 跨模式不重复计)
// 金额口径(2026-08-13 用户纠正恢复): 每日资金池等分+top-K = 当日保留前K基笔(后续positionCap保留), 每笔=10000/当日保留数, 每日总投入恒1万 → K档最大持仓恒定(~11万)。
//   当初(2026-08-12 5d047aef2)把"每日资金池整体删除""1w还分30个信号买30份没意义,仓位控制1/2/3/4已足以"是理解错误——用户反对的是"每日池+买全部"(每份太小), 而非每日池本身;"仓位控制K/4已足以"正是要每日池+top-K(每份=10000/当日保留个数, 有实操意义)
// 基笔身份: signal_date|index_id|signal|buy_date|etf_code (买侧身份, 卖出模式不影响)
function _kellyBaseKey(t, fIdx) {
  return (t[fIdx.signal_date] || "") + "|" + (t[fIdx.index_id] || "") + "|" + (t[fIdx.signal] || "") + "|" + (t[fIdx.buy_date] || "") + "|" + (t[fIdx.etf_code] || "");
}
// 计算 positionCap 保留基笔 key 集合(top K per signal_date, 排序口径见上方注释)
function _kellyPositionCapKeptKeys(pool, fIdx, K) {
  var kept = {};
  if (!K || K <= 0 || !pool || !pool.length) return kept;
  var RATING_RANK = { high: 0, mid: 1, low: 2, "": 3 };
  var SIG_RANK = { buy_backup: 0, buy: 1, buy_aux: 2, buy_special: 3, "": 9 };
  var byDate = {};
  for (var i = 0; i < pool.length; i++) {
    var sd = String(pool[i][fIdx.signal_date] || "");
    if (!sd) continue;
    (byDate[sd] || (byDate[sd] = [])).push(pool[i]);
  }
  for (var sd in byDate) {
    var rows = byDate[sd];
    rows.sort(function (a, b) {
      var sa = fIdx.track_score != null ? Number(a[fIdx.track_score]) : -1;
      var sb = fIdx.track_score != null ? Number(b[fIdx.track_score]) : -1;
      if (sb !== sa) return sb - sa; // track_score DESC
      // 注意: 0||3 陷阱——rank 0(high/buy_backup)是合法最小值, 必须用 hasOwnProperty 判定, 不能用 || 兜底
      var rak = fIdx.rating != null ? String(a[fIdx.rating] || "") : "";
      var ra = Object.prototype.hasOwnProperty.call(RATING_RANK, rak) ? RATING_RANK[rak] : 3;
      var rbk = fIdx.rating != null ? String(b[fIdx.rating] || "") : "";
      var rb = Object.prototype.hasOwnProperty.call(RATING_RANK, rbk) ? RATING_RANK[rbk] : 3;
      if (ra !== rb) return ra - rb; // rating high>mid>low
      var sgak = fIdx.signal != null ? String(a[fIdx.signal] || "") : "";
      var sga = Object.prototype.hasOwnProperty.call(SIG_RANK, sgak) ? SIG_RANK[sgak] : 9;
      var sgbk = fIdx.signal != null ? String(b[fIdx.signal] || "") : "";
      var sgb = Object.prototype.hasOwnProperty.call(SIG_RANK, sgbk) ? SIG_RANK[sgbk] : 9;
      if (sga !== sgb) return sga - sgb; // signal 类型 buy_backup>buy>buy_aux>buy_special
      var da = String(a[fIdx.buy_date] || ""), db = String(b[fIdx.buy_date] || "");
      if (da !== db) return da < db ? -1 : 1; // buy_date ASC
      return 0;
    });
    var n = Math.min(K, rows.length);
    for (var j = 0; j < n; j++) kept[_kellyBaseKey(rows[j], fIdx)] = true;
  }
  return kept;
}
// 收集 positionCap 基笔池: 跨全部卖出模式 × rating 三分区(互斥全量), 按 baseKey 去重, 只保留通过 passFn 的基笔
// 基笔池构建改异步分片(2026-08-23 性能专项): 原 3象限×10模式 ≈100k 次谓词判定一个同步块(~200-400ms),
// 改为每 (象限,模式) 桶后让步一帧; 唯一调用方 _kellyApplyFeeRecompute 本就是 async, 语义零变化。
async function _kellyCollectBasePool(quads, sellModes, fIdx, passFn) {
  var pool = [], seen = {};
  var _rks = ["rating_high", "rating_mid", "rating_low"];
  for (var _ri = 0; _ri < _rks.length; _ri++) {
    var _rk = _rks[_ri];
    for (var _mk in sellModes) {
      var _arr = (quads[_rk] || {})[_mk] || [];
      for (var _i = 0; _i < _arr.length; _i++) {
        var _t = _arr[_i];
        if (passFn && !passFn(_t)) continue;
        var _bk = _kellyBaseKey(_t, fIdx);
        if (!seen[_bk]) { seen[_bk] = 1; pool.push(_t); }
      }
      await _kellyYield();
    }
  }
  return pool;
}
// 每日资金池等分+top-K 金额口径(2026-08-13 恢复, 用户纠正最初理解错误):
//  当日保留前K基笔(全mode共享同一批kept), 每笔=10000/当日保留数, 每日总投入恒1万 → K档最大持仓恒定(~11万), 恢复分仓实操意义
//  当初(5d047aef2)把"每日资金池"整体删除是错误理解——用户反对的是"每日池+买全部"(每份太小), 而非每日池本身; 仓位控制X/4已足以=要每日池+top-K
//  当日保留数基于 posCapKept 保留集合全集(跨mode)统计, 保证同一天同一基笔在所有mode/场景金额统一(§22 跨展示位一致)
function _kellyKeptDayCounts(kept) {
  var m = {};
  if (!kept) return m;
  for (var k in kept) {
    var sd = String(k || "").split("|")[0];
    if (sd) m[sd] = (m[sd] || 0) + 1;
  }
  return m;
}
// 单笔买入金额: 每日资金池+top-K 口径 = buyAmount(10000) / 当日保留基笔数(dayKeptCount); positionCap 未开或无数时退化为固定 buyAmount
function _kellyPerTradeAmount(t, fIdx, buyAmount, dayKeptCount) {
  if (dayKeptCount && dayKeptCount > 0) return buyAmount / dayKeptCount;
  return buyAmount;
}
// 最大同时持仓占用资金(按日期分桶累加买入/卖出金额; 同日 FIFO 强平+新买入 场景必须【先减后加】——先平旧仓再入新仓, 才与仿真内核 _kellyAihlineFifoCap 同序, cap 后峰值才精确回到 cap(20万); 若先加后减会把同日"待强平+新入"同时计入峰值而超 cap)
// 注: 全 144 象限×模式普通交易无"同日既买又卖"(仅 GIH FIFO 强平产生), 故改先减后加对 A-F 基线零漂移(等价), 语义与 _kellyMaxConcurrent 一致
function _kellyMaxConcurrentCapital(trades) {
  if (!trades.length) return 0;
  var SENTINEL = "99999999", deltas = {}, dates = [];
  for (var i = 0; i < trades.length; i++) {
    var bd = trades[i].buy_date, sd = trades[i].sell_date || SENTINEL;
    var amt = trades[i].amount || 0;
    var db = deltas[bd]; if (!db) { db = deltas[bd] = { b: 0, s: 0 }; dates.push(bd); }
    db.b += amt;
    var ds = deltas[sd]; if (!ds) { ds = deltas[sd] = { b: 0, s: 0 }; dates.push(sd); }
    ds.s += amt;
  }
  dates.sort();
  var cur = 0, maxC = 0;
  for (var i = 0; i < dates.length; i++) {
    var d = deltas[dates[i]];
    cur -= d.s;  // 先减当日卖出/强平
    cur += d.b;  // 再加当日买入
    if (cur > maxC) maxC = cur;
  }
  return Math.round(maxC * 10000) / 10000;
}
// 共享设置: positionCap 开关 + K 档位(交易页标灰联动, localStorage 双页共享; 默认 开启/K=1(2026-08-14 #BC 主推K1, 原默认K=3)
function _kellySharedPosCap() {
  var def = { on: true, k: 1 };
  try {
    var raw = localStorage.getItem("tds_poscap");
    if (raw) { var p = JSON.parse(raw); if (typeof p.k === "number" && p.k >= 1 && p.k <= 4) def.k = p.k; def.on = !!p.on; }
  } catch (e) {}
  return def;
}
function _kellySetSharedPosCap(on, k) {
  try { localStorage.setItem("tds_poscap", JSON.stringify({ on: !!on, k: k || 3 })); } catch (e) {}
}

// ===== ai长线模式(G/H/I)仓位管理 (2026-08-14 #49+#xx; 可扩展架构: 按钮=长线族群总入口, 内部按模式配置独立策略) =====
// 用户定义: 只记「ai长线模式(G/H/I)仓位管理」一个开关, 背后是 G/H/I 长线族群的完整交易方法论。
// v2.1 (2026-08-29 codex#001 定稿, docs/kelly/position/kelly-g-mode-recheck.md §0): G/H/I 不再统一 FIFO 20万——
//   G = P≤3d「先卖年轻仓」+ 13万定稿单档(删 15/20 档自选); H = 满仓不买@7万(手段A); I = 满仓不买@16万(手段A, 用户拍板原15万上调)。
// 架构核心: 模式→策略映射结构, 不写死"三模式同一个逻辑"。每模式独立指向策略。
const AIHLINE_STRATS = {
  // 手段B = FIFO 强制平最久持仓, 回cap内再买入(旧 v1 统一策略, 保留供对照)
  fifo20w: { label: "FIFO 20万", cap: 200000, method: "B" },
  // 手段P = P≤3d「先卖年轻仓」: 超cap时先卖持有≤3天的年轻仓(几笔年轻仓里先卖持有最久那笔), 无年轻仓才卖最老(FIFO)
  // v2.1 定稿单档 13万(删 15/20 档自选, v1.1.7 基准 188.88% 全 G 档收益最高; 峰持仓 13 倍=可操作)
  p3d13w: { label: "P≤3d 13万", cap: 130000, method: "P", gTier: "13万", gTierNote: "定稿最优·收益率最高" },
  // 手段A = 满仓不买: 到 cap 就停买(当日超容整批跳过), 不强制平仓, 自然卖出腾位再买(b0=b1 无强平)
  hold7w: { label: "满仓不买@7万", cap: 70000, method: "A" },
  hold15w: { label: "满仓不买@16万", cap: 160000, method: "A" } // key 名 hold15w 保留(语义已是 16 万, 存策略 key 的 localStorage 不破坏)
};
// G 档位(2026-08-29 codex#001 定稿: 只保留 13万一档, 删 15/20 档自选)。函数兼容保留(返回固定 13万),
// localStorage tds_gih_g_tier 历史用户值(15万/20万)自动归一为 13万, 不破坏已有数据
function _kellyGihGTier() {
  return "13万"; // 定稿单档: G=P≤3d@13万(v1.1.7 基准 188.88%, 峰持仓 13 倍=可操作)
}
function _kellySetGihGTier(t) {
  try { localStorage.setItem("tds_gih_g_tier", String(t || "13万")); } catch (e) {}
}
function _kellyGihGStratKey() { return "p3d13w"; }
// 模式→策略映射(v2.1: G 固定 P≤3d 13万, H=满仓不买7万, I=满仓不买16万; key 值可扩展其他策略名)
function _kellyGihStrategyKey(m) {
  if (m === "G") return _kellyGihGStratKey();
  if (m === "H") return "hold7w";
  if (m === "I") return "hold15w";
  return "fifo20w"; // 非G/H/I理论不进此分支, 兜底
}
// G/H/I 判定(与 _sigKellyModeSpanKey 同源, 全站长线族群统一定义)
function _kellyIsGih(modeKey) { return modeKey === "G" || modeKey === "H" || modeKey === "I"; }
// #25 A包: 可操作层判据 = 峰值同时持仓资金 ≤ 20万(20倍单次本金1万), 用户2026-08-14原话"优秀数据首先看可操作性其次看收益率"
// 首页/实验室单次本金基准 = buy_amount(默认10000/daily池每笔=10000/K). A-F 短线天然≤20倍; G/H/I 长持原始仓位易>20倍(136万/111万/45万)不可操作, 开ai长线(GIH on)后套20万FIFO硬控→可操作
var _KELLY_OPERABLE_CAP = 200000; // 峰持仓资金≤20万 = 单次本金倍数≤20(可操作性硬标准, memory kelly-operability-20x-principal)
function _kellyOperableRow(pdata, modeKey, gihOn) {
  // GIH on: G/H/I 取 __gihb1(20万FIFO硬控后乐观b1口径, 可操作); 否则用原始stats. A-F 恒定原始
  if (gihOn && _kellyIsGih(modeKey)) {
    const cap = pdata[modeKey + "__gihb1"];
    if (!cap) return { r: pdata[modeKey], operable: false, capOn: false };
    return { r: cap, operable: true, capOn: true };
  }
  const r = pdata[modeKey];
  if (!r) return null;
  const mcc = r.max_concurrent_capital || 0;
  return { r: r, operable: mcc <= _KELLY_OPERABLE_CAP, capOn: false };
}
// 卡片行(renderSigKellyCard)/水印/三玩法表/对比表/全信号表/弹窗 通用的"不可操作淘汰"判定 + 理由 + 角标文案, §23.3 举一反三共用(不重复定义)
// #25 A包(2026-08-14) 两个触发源统一用"峰持仓≤20万=可操作"判据, 理由按触发源分类:
//   需求② = positionCap ON 但 GIH off(G/H/I 未套20万FIFO硬控)且原始峰持仓>20倍 → 理由"无操作性"
//   需求D = positionCap OFF(K关, 无仓位限制每笔固定1万全买)导致峰持仓>20倍 → 理由"无仓位限制·无法实操"
// 返回 null(不可用) 或 { r, operable, eliminated, reason, tip } —— eliminated=应标"淘汰", operable=该模式是否可操作(供 TOP1 候选过滤)
// 触发源合并: K-OFF 时即使 GIH on(A cap后)也可能因无仓位限制疯长? 否——K-OFF+GIHon 时 G/H/I 取 cap, 但 A-F 仍无仓位限制每笔1万全买; 峰持仓超限才淘汰, 不预设
function _kellyOpElimination(pdata, modeKey, gihOn, posCapOn) {
  const o = _kellyOperableRow(pdata, modeKey, gihOn);
  if (!o) return null;
  const mcc = (o.r.max_concurrent_capital || 0);
  const mult = (mcc / 10000) || 0;
  const operable = mcc <= _KELLY_OPERABLE_CAP;
  if (operable) return { r: o.r, operable: true, eliminated: false, reason: "", tip: "" };
  // 峰持仓超20倍 → 不可操作. 理由分类:
  // 需求D: positionCap OFF(无仓位限制, 每笔1万全买)是主因(即使GIH cap后A-F/非cap模式也会疯长)
  if (!posCapOn) {
    return {
      r: o.r, operable: false, eliminated: true, reason: "无仓位限制·无法实操",
      tip: `淘汰=无仓位限制·无法实操: K档已「关」(positionCap OFF), 每笔固定 1 万、无仓位限制, 当日全部信号都买 → 峰值同时持仓 ${(mult >= 1 ? mult.toFixed(0) : mult)} 万(${mult >= 1 ? mult.toFixed(0) : mult}倍单次本金) 远超 20 倍可操作上限。为验证数据变化保留展示, 切换 K=1-4(每笔=10000/当日保留数, 有仓位控制)后回归可操作。`
    };
  }
  // 需求②: positionCap ON 但 GIH off(G/H/I 未套20万硬控)且原始峰持仓>20倍 → 无操作性; A-F 在 K ON 下有仓位控制自然≤20倍不进此分支
  return {
    r: o.r, operable: false, eliminated: true, reason: "无操作性",
    tip: `淘汰=无操作性: 本模式(${modeKey})原始仓位峰值同时持仓 ${(mult >= 1 ? mult.toFixed(0) : mult)} 万 = ${(mult >= 1 ? mult.toFixed(0) : mult)} 倍单次本金, 超出 20 倍可操作上限(${_KELLY_OPERABLE_CAP / 10000}万)。开上方「ai长线(G/H/I)仓位管理」套对应模式仓位法(G=P≤3d@13万/H=满仓不买@7万/I=满仓不买@16万)后可操作, 才参与 TOP1 推荐。`
  };
}
// 弹窗交易记录态: 被不可操作淘汰的模式(GIH off 无操作性 / K-OFF 无仓位限制), 弹窗顶部给淘汰理由提示(§23.3 举一反三补齐该展示位), 与卡片行/水印同判据同文案
function _kellyOpModalNote(quadKey, modeKey, period) {
  const fs = state.labSigKellyFeeStats;
  const pdata = (fs && fs[quadKey] && fs[quadKey][period]) ? fs[quadKey][period] : null;
  if (!pdata) return "";
  const posCapOn = !!((state.labSigKellyFilters || {}).positionCap);
  const flag = _kellyOpElimination(pdata, modeKey, !!state.labSigKellyGihOn, posCapOn);
  if (!flag || !flag.eliminated) return "";
  const mcc = (pdata[modeKey] && pdata[modeKey].max_concurrent_capital) || 0;
  const mult = (mcc / 10000) || 0;
  return `<div class="lab-sigkelly-gih-modal-note lab-sigkelly-opelim-modal-note" title="${flag.reason}">⚠️ 本模式已「<b>${flag.reason}</b>」：当前峰值同时持仓 ${(mult >= 1 ? mult.toFixed(0) : mult)} 万(${(mult >= 1 ? mult.toFixed(0) : mult)}倍单次本金) 超出 20 倍可操作上限，${flag.tip}</div>`;
}
// 共享设置: 开关状态(localStorage, 默认开(2026-08-29 codex#001 定稿: 首页模拟回测弹窗 G/H/I 档位默认开启+首页展示);
// 影响实验室 G/H/I 卡片 + 首页 sim 弹窗 G/H/I 管位入口, §22 口径)
function _kellySharedGih() {
  var def = { on: true };
  try {
    var raw = localStorage.getItem("tds_gihpos");
    if (raw) { var p = JSON.parse(raw); def.on = !!p.on; }
  } catch (e) {}
  return def;
}
function _kellySetSharedGih(on) {
  try { localStorage.setItem("tds_gihpos", JSON.stringify({ on: !!on })); } catch (e) {}
}
// 当前模式策略(未来某模式优化后改 _kellyGihStrategyKey 即生效, 不动按钮整体; G 档位动态)
function _kellyGihStrat(modeKey) { return AIHLINE_STRATS[_kellyGihStrategyKey(modeKey)] || AIHLINE_STRATS["fifo20w"] || null; }
// 模式当前策略的展示短线标签(卡片角标/水印/三玩法等共用, §22/§23.3): 返回如 "P≤3d 13万" / "满仓不买@7万" / "满仓不买@16万"
function _kellyGihStratShort(modeKey) {
  var st = _kellyGihStrat(modeKey);
  if (!st) return "";
  return st.label || "";
}
// 模式当前策略的白话一句话玩法说明(hoverpop/面板文案用, §22/§23.3 与内核一致)
function _kellyGihStratExplain(modeKey) {
  var key = _kellyGihStrategyKey(modeKey);
  if (key === "hold7w") return "满仓不买@7万: 到 7 万就停买、不强制平仓, 等有自然卖出腾出资金再买新信号(手段A, 无强平→b0=b1)";
  if (key === "hold15w") return "满仓不买@16万(用户拍板原15万上调): 到 16 万就停买、不强制平仓, 等有自然卖出腾出资金再买新信号(手段A, 无强平→b0=b1)";
  if (key === "p3d13w") return "P≤3d「先卖年轻仓」: 超仓先卖持有≤3天的年轻仓、无年轻仓才卖最老, 保老仓砍新仓(手段P); 档位 " + (_kellyGihStrat(modeKey).gTier) + "(" + (_kellyGihStrat(modeKey).gTierNote) + ")";
  return "FIFO 强制平最久持仓";
}

// ---- 下面为策略 fifo20w 的具体仿真内核(JS 端口 of /tmp/cap_sim.py simulate_capped method='B' + realize) ----
// 已按报告 §7.2(K1 版)自验逐位对齐: G/H/I × b0/b1 六格 净利/收益率/峰值全对齐, 见 /tmp/gih49/fifo_test.js
const AIHLINE_CAL_RATIO = 1.498; // 日历日/交易日中位比(与 python cap_sim 一致)
// 真实强平盈亏不可知(b0 0利 保守 / b1 按持有时间线性 乐观), 真实值在区间, 不把 b1 当承诺
function _kellyAihlineCalSpan(bd, sd) {
  if (!bd || !sd || sd < bd) return 0;
  var d1 = new Date(+bd.slice(0, 4), +bd.slice(4, 6) - 1, +bd.slice(6, 8));
  var d2 = new Date(+sd.slice(0, 4), +sd.slice(4, 6) - 1, +sd.slice(6, 8));
  return Math.max(Math.round((d2 - d1) / 86400000), 0);
}
// 强平笔利润实现(pr=profit, rp=return_pct, amt=amount, closeDate=强制平仓日)
function _kellyAihlineRealize(pr, rp, bd, sd, hd, amt, closeDate, model) {
  var ns = sd ? _kellyAihlineCalSpan(bd, sd) : (hd ? hd * AIHLINE_CAL_RATIO : 0);
  var cs = closeDate ? _kellyAihlineCalSpan(bd, closeDate) : ns;
  if (ns <= 0 || cs >= ns) return { pr: pr, rp: rp, hd: hd };
  var f = cs / ns;
  if (model === "b0") return { pr: 0, rp: 0, hd: Math.round(hd * f) };
  if (model === "b1") return { pr: pr * f, rp: (pr * f / amt * 100), hd: Math.round(hd * f) };
  return { pr: 0, rp: 0, hd: 0 };
}
// 策略 fifo20w 仿真: 传入已 K 过滤/费率重算的 trade 数组 {profit,return_pct,buy_date,sell_date,hold_days,amount},
// 返回 {kept(强平后成交数组), peak(仿真峰值持仓)}。model='b0'保守 / 'b1'乐观。
function _kellyAihlineFifoCap(trades, cap, model) {
  var trs = trades.map(function (t) {
    return { profit: t.profit, return_pct: t.return_pct, buy_date: t.buy_date, sell_date: t.sell_date || null, hold_days: t.hold_days, amount: t.amount || 0, closed: null, fee_cost: t.fee_cost || 0 };
  });
  var buysByDate = {}, datesSet = {}, allDates = [];
  for (var i = 0; i < trs.length; i++) {
    var bd = trs[i].buy_date;
    (buysByDate[bd] || (buysByDate[bd] = [])).push(trs[i]);
    if (!datesSet[bd]) { datesSet[bd] = 1; allDates.push(bd); }
    var sd2 = trs[i].sell_date;
    if (sd2 && !datesSet[sd2]) { datesSet[sd2] = 1; allDates.push(sd2); }
  }
  allDates.sort();
  var openTrs = [], kept = [], cur = 0, peak = 0;
  for (var d = 0; d < allDates.length; d++) {
    var dt = allDates[d];
    var newOpen = [];
    for (var o = 0; o < openTrs.length; o++) {
      var t = openTrs[o];
      if (t.sell_date === dt && t.closed === null) {
        t.closed = "natural";
        cur -= t.amount;
        kept.push({ profit: t.profit, return_pct: t.return_pct, buy_date: t.buy_date, sell_date: t.sell_date, hold_days: t.hold_days, amount: t.amount, fee_cost: t.fee_cost });
      } else newOpen.push(t);
    }
    openTrs = newOpen;
    var dayTrs = buysByDate[dt];
    if (dayTrs) {
      var dayTotal = 0;
      for (var k = 0; k < dayTrs.length; k++) dayTotal += dayTrs[k].amount;
      var needed = cur + dayTotal - cap;
      if (needed > 1e-6) {
        // 手段B: FIFO 强制平最久持仓, 回cap内再买入
        while (needed > 1e-6 && openTrs.length) {
          var tr = openTrs.shift();
          var r = _kellyAihlineRealize(tr.profit, tr.return_pct, tr.buy_date, tr.sell_date, tr.hold_days, tr.amount, dt, model);
          kept.push({ profit: r.pr, return_pct: r.rp, buy_date: tr.buy_date, sell_date: dt, hold_days: r.hd, amount: tr.amount, fee_cost: tr.fee_cost });
          cur -= tr.amount;
          needed = cur + dayTotal - cap;
        }
        if (needed <= 1e-6) { openTrs = openTrs.concat(dayTrs); cur += dayTotal; }
        // else 当日跳过(不入池)
      } else { openTrs = openTrs.concat(dayTrs); cur += dayTotal; }
    }
    if (cur > peak) peak = cur;
  }
  for (var z = 0; z < openTrs.length; z++) {
    var tz = openTrs[z];
    if (tz.closed === null) kept.push({ profit: tz.profit, return_pct: tz.return_pct, buy_date: tz.buy_date, sell_date: tz.sell_date || "", hold_days: tz.hold_days, amount: tz.amount, fee_cost: tz.fee_cost });
  }
  return { kept: kept, peak: Math.round(peak * 10000) / 10000 };
}
// 策略 P≤3d「先卖年轻仓」仿真(method P, 2026-08-14 #xx): 超 cap 时先卖「持有≤3天」的年轻仓
// (几笔年轻仓里先卖持有最久那笔), 只有手上一笔年轻仓都没有才轮到卖最老仓(FIFO)。白话=保老仓(21-100天利润引擎)砍新仓(刚买没攒利润)。
// 数据定稿 docs/kelly/position/kelly-g-mode-recheck.md(P3d 15起始全胜FIFO, b0/b1区间4-24pp最可信)。
const _KGIHP3_DAYS = 3; // P 保护窗口: 持有≤3天 视为年轻仓
function _kellyAihlineDaySpan(bd, sd) {
  if (!bd || sd < bd) return 0;
  var d1 = new Date(+bd.slice(0, 4), +bd.slice(4, 6) - 1, +bd.slice(6, 8));
  var d2 = new Date(+sd.slice(0, 4), +sd.slice(4, 6) - 1, +sd.slice(6, 8));
  return Math.max(Math.round((d2 - d1) / 86400000), 0);
}
function _kellyAihlineP3dCap(trades, cap, model) {
  var trs = trades.map(function (t) {
    return { profit: t.profit, return_pct: t.return_pct, buy_date: t.buy_date, sell_date: t.sell_date || null, hold_days: t.hold_days, amount: t.amount || 0, closed: null, fee_cost: t.fee_cost || 0 };
  });
  var buysByDate = {}, datesSet = {}, allDates = [];
  for (var i = 0; i < trs.length; i++) {
    var bd = trs[i].buy_date;
    (buysByDate[bd] || (buysByDate[bd] = [])).push(trs[i]);
    if (!datesSet[bd]) { datesSet[bd] = 1; allDates.push(bd); }
    var sd2 = trs[i].sell_date;
    if (sd2 && !datesSet[sd2]) { datesSet[sd2] = 1; allDates.push(sd2); }
  }
  allDates.sort();
  var openTrs = [], kept = [], cur = 0, peak = 0;
  for (var d = 0; d < allDates.length; d++) {
    var dt = allDates[d];
    var newOpen = [];
    for (var o = 0; o < openTrs.length; o++) {
      var t = openTrs[o];
      if (t.sell_date === dt && t.closed === null) {
        t.closed = "natural";
        cur -= t.amount;
        kept.push({ profit: t.profit, return_pct: t.return_pct, buy_date: t.buy_date, sell_date: t.sell_date, hold_days: t.hold_days, amount: t.amount, fee_cost: t.fee_cost });
      } else newOpen.push(t);
    }
    openTrs = newOpen;
    var dayTrs = buysByDate[dt];
    if (dayTrs) {
      var dayTotal = 0;
      for (var k = 0; k < dayTrs.length; k++) dayTotal += dayTrs[k].amount;
      var needed = cur + dayTotal - cap;
      if (needed > 1e-6) {
        // 手段P: 先卖「持有≤3天」的年轻仓(几笔年轻仓里先卖持有最久=买日最早那笔), 全部年轻仓卖完仍超cap再 FIFO 卖最老
        while (needed > 1e-6 && openTrs.length) {
          // 找年轻仓(持有≤3天)中"持有最久"(买日最早)的一笔; 无年轻仓则退化为 FIFO 最老
          var sel = null, selBuy = null;
          for (var p = 0; p < openTrs.length; p++) {
            var ot = openTrs[p];
            if (ot.closed !== null) continue;
            if (_kellyAihlineDaySpan(ot.buy_date, dt) <= _KGIHP3_DAYS) {
              if (!sel || ot.buy_date < selBuy) { sel = ot; selBuy = ot.buy_date; }
            }
          }
          if (!sel) {
            // 无任何年轻仓 → FIFO 卖最老(买日最早)
            sel = openTrs[0];
            for (var p2 = 0; p2 < openTrs.length; p2++) {
              var ot2 = openTrs[p2];
              if (ot2.closed !== null) continue;
              if (!sel || ot2.buy_date < sel.buy_date) sel = ot2;
            }
          }
          var r = _kellyAihlineRealize(sel.profit, sel.return_pct, sel.buy_date, sel.sell_date, sel.hold_days, sel.amount, dt, model);
          kept.push({ profit: r.pr, return_pct: r.rp, buy_date: sel.buy_date, sell_date: dt, hold_days: r.hd, amount: sel.amount, fee_cost: sel.fee_cost });
          cur -= sel.amount;
          sel.closed = "p3d";
          // 从 openTrs 移除该笔(按索引)
          for (var rp = openTrs.length - 1; rp >= 0; rp--) { if (openTrs[rp] === sel) openTrs.splice(rp, 1); }
          needed = cur + dayTotal - cap;
        }
        if (needed <= 1e-6) { openTrs = openTrs.concat(dayTrs); cur += dayTotal; }
      } else { openTrs = openTrs.concat(dayTrs); cur += dayTotal; }
    }
    if (cur > peak) peak = cur;
  }
  for (var z = 0; z < openTrs.length; z++) {
    var tz = openTrs[z];
    if (tz.closed === null) kept.push({ profit: tz.profit, return_pct: tz.return_pct, buy_date: tz.buy_date, sell_date: tz.sell_date || "", hold_days: tz.hold_days, amount: tz.amount, fee_cost: tz.fee_cost });
  }
  return { kept: kept, peak: Math.round(peak * 10000) / 10000 };
}
// 策略 手段A「满仓不买」仿真(method A, 2026-08-14 #xx): 到 cap 就停买(当日超容整批跳过), 不强制平仓,
// 自然卖出腾位再买。无强平 → 强平日盈亏不存在的场景, b0=b1 同值。数据定稿 docs/kelly/position/kelly-ghi-continuous-cap-sweep.md(H@7万/I@16万)。
function _kellyAihlineHoldCap(trades, cap) {
  var trs = trades.map(function (t) {
    return { profit: t.profit, return_pct: t.return_pct, buy_date: t.buy_date, sell_date: t.sell_date || null, hold_days: t.hold_days, amount: t.amount || 0, closed: null, fee_cost: t.fee_cost || 0 };
  });
  var buysByDate = {}, datesSet = {}, allDates = [];
  for (var i = 0; i < trs.length; i++) {
    var bd = trs[i].buy_date;
    (buysByDate[bd] || (buysByDate[bd] = [])).push(trs[i]);
    if (!datesSet[bd]) { datesSet[bd] = 1; allDates.push(bd); }
    var sd2 = trs[i].sell_date;
    if (sd2 && !datesSet[sd2]) { datesSet[sd2] = 1; allDates.push(sd2); }
  }
  allDates.sort();
  var openTrs = [], kept = [], cur = 0, peak = 0;
  for (var d = 0; d < allDates.length; d++) {
    var dt = allDates[d];
    var newOpen = [];
    for (var o = 0; o < openTrs.length; o++) {
      var t = openTrs[o];
      if (t.sell_date === dt && t.closed === null) {
        t.closed = "natural";
        cur -= t.amount;
        kept.push({ profit: t.profit, return_pct: t.return_pct, buy_date: t.buy_date, sell_date: t.sell_date, hold_days: t.hold_days, amount: t.amount, fee_cost: t.fee_cost });
      } else newOpen.push(t);
    }
    openTrs = newOpen;
    var dayTrs = buysByDate[dt];
    if (dayTrs) {
      var dayTotal = 0;
      for (var k = 0; k < dayTrs.length; k++) dayTotal += dayTrs[k].amount;
      var needed = cur + dayTotal - cap;
      if (needed > 1e-6) {
        // 手段A: 满仓不买——当日超容, 整批跳过不入池(不强制平仓, 等自然卖出腾位再买)
      } else { openTrs = openTrs.concat(dayTrs); cur += dayTotal; }
    }
    if (cur > peak) peak = cur;
  }
  for (var z = 0; z < openTrs.length; z++) {
    var tz = openTrs[z];
    if (tz.closed === null) kept.push({ profit: tz.profit, return_pct: tz.return_pct, buy_date: tz.buy_date, sell_date: tz.sell_date || "", hold_days: tz.hold_days, amount: tz.amount, fee_cost: tz.fee_cost });
  }
  return { kept: kept, peak: Math.round(peak * 10000) / 10000 };
}
// 策略 → 仿真内核选择(method: B=FIFO / P=P≤3d 先卖年轻 / A=满仓不买)
function _kellyAihlineSim(method, trades, cap, model) {
  if (method === "P") return _kellyAihlineP3dCap(trades, cap, model);
  if (method === "A") return _kellyAihlineHoldCap(trades, cap);
  return _kellyAihlineFifoCap(trades, cap, model);
}
// 包装: 对单个 mode 的 K 过滤 trade 数组按当前策略仿真(返回 b0/b1 两套 kept 数组 + 峰值)
function _kellyAihlineApply(trades, strategy, periodKey) {
  var out = { b0: null, b1: null, peak: 0, stratKey: null };
  if (!strategy) return out;
  out.stratKey = strategy;
  var method = strategy.method || "B";
  var b0 = _kellyAihlineSim(method, trades, strategy.cap, "b0");
  var b1 = (method === "A") ? b0 : _kellyAihlineSim(method, trades, strategy.cap, "b1");
  out.b0 = b0.kept;
  out.b1 = b1.kept;
  out.peak = b0.peak;
  return out;
}

// 让loading先paint: 双rAF(第一帧调度, 第二帧在paint后恢复, 再执行同步重算)
function _kellyNextPaint() {
  return new Promise(function (resolve) {
    requestAnimationFrame(function () { requestAnimationFrame(resolve); });
  });
}

// 凯利重算统一入口(方案B: loading真显示+防重入)
// busy flag防交错; latest-wins: 重算中再来点击记pending, 本轮跑完按最新状态再跑一轮, 最终渲染一次
// 让出主线程一帧(2026-08-23 性能专项): 重算按 (象限×模式) 桶分片, 桶间 setTimeout(0) 让步,
// 把原本 ~600-900ms 的单个同步长任务拆成多个 <200ms 短任务(硬指标), 输入/输出/计算顺序零改动。
// 合批仍由 _kellyRunRecompute 的 busy/pending 负责: 让步期间的新触发只置 pending, 收尾用最新态重跑一次。
function _kellyYield() {
  return new Promise(function (r) { setTimeout(r, 0); });
}

async function _kellyRunRecompute(host, loadingHtml, onResult, onDone) {
  if (_kellyRecomputeBusy) { _kellyRecomputePending = true; return; }
  _kellyRecomputeBusy = true;
  do {
    _kellyRecomputePending = false;
    // 2026-08-11 交互优化: 不整卡清空(卡片保持挂载, 半透明+顶部细条 loading), 便于对照打勾前后数值
    host.classList.add("lab-custom-host--loading");
    await _kellyNextPaint();
    var stats = await _kellyApplyFeeRecompute(state.labSigKellyFeeParams);
    onResult(stats);
  } while (_kellyRecomputePending);
  _kellyRecomputeBusy = false;
  // 【P0 防御兜底 2026-08-24】await 让步期间(trades.json 慢载/桶间 setTimeout 让步)host 可能被其他路径
  //   整区重建替换——闭包捕获的 host 脱离 DOM 成死节点, onResult/onDone 写死节点 = 页面在册新 host
  //   永远停留「⏳ 计算中…」。收尾前检测 isConnected, 失联则重取当前在册 host 再收尾(onDone(h) 以实参
  //   传入新 host, 各调用方 onDone 以参数优先/闭包值兜底), 救所有「onDone 时 host 已被换」场景。
  if (!host.isConnected) {
    var liveHost = document.querySelector(".lab-sigkelly-host");
    if (liveHost) host = liveHost;
  }
  host.classList.remove("lab-custom-host--loading");
  onDone(host);
}

// sigkelly 分片加载模块(2026-08-28): recent.json 首屏快速预览 + 全量兜底 + 合并各年数据
var _labKellyFullFallback = false;     // 分片链路失败已回退全量(true 后跳过分片逻辑)
var _labKellyLoadErr = null;           // 加载错误信息
var _labKellyLoadProgress = { done: 0, total: 16, lastYear: "" }; // 分片加载进度(「计算中」占位显示用, 2026-08-29 小步2)
// URL helpers
function _labKellyTradesUrl(name) { var v = _labCustomCacheBust(); return "https://ss.fx8.store/data/" + name + (v ? "?v=" + v : ""); }
function _labKellyTradesUrlCf(name) { var v = _labCustomCacheBust(); return "./data/" + name + (v ? "?v=" + v : ""); }

// P1-01(2026-08-29): kelly-reports-content / kelly-review-notes 懒加载
// 原 index.html defer 同步加载 379KB,首页/信号卡/KPI 完全不需要,改为点击报告弹窗时动态加载
var _kellyReportsLoaded = false;
var _kellyReviewNotesLoaded = false;
function _loadKellyReports() {
  if (_kellyReportsLoaded) return Promise.resolve();
  return new Promise(function(resolve, reject) {
    var s = document.createElement('script');
    s.src = './kelly-reports-content.min.js?v=' + _labCustomCacheBust();
    s.onload = function() { _kellyReportsLoaded = true; resolve(); };
    s.onerror = function() { reject(new Error('Failed to load kelly-reports-content.min.js')); };
    document.head.appendChild(s);
  });
}
function _loadKellyReviewNotes() {
  if (_kellyReviewNotesLoaded) return Promise.resolve();
  return new Promise(function(resolve, reject) {
    var s = document.createElement('script');
    s.src = './kelly-review-notes.min.js?v=' + _labCustomCacheBust();
    s.onload = function() { _kellyReviewNotesLoaded = true; resolve(); };
    s.onerror = function() { reject(new Error('Failed to load kelly-review-notes.min.js')); };
    document.head.appendChild(s);
  });
}
function _labKellyFetchTrades(name) {
  var r2 = _labKellyTradesUrl(name);
  var cf = _labKellyTradesUrlCf(name);
  var controller = new AbortController();
  var to = setTimeout(function() { controller.abort(); }, 60000);
  return fetch(r2, { signal: controller.signal })
    .then(function(r) { clearTimeout(to); if (!r.ok) throw new Error("R2 " + r.status); return r.json(); })
    .catch(function() {
      clearTimeout(to);
      var c2 = new AbortController();
      var t2 = setTimeout(function() { c2.abort(); }, 60000);
      return fetch(cf, { signal: c2.signal })
        .then(function(r) { clearTimeout(t2); if (!r.ok) throw new Error("CF " + r.status); return r.json(); })
        .catch(function(e2) { clearTimeout(t2); throw e2; });
    });
}
// 分片带重试的 fetch(2026-08-29): 单片至多 attempts 次尝试(首次+重试), 每次失败按 delays 指数退避后重试, 全败才抛出
//   - 重试仍用同一个 _labKellyFetchTrades(R2→CF 双源都有各自超时/回退), 只是失败后稍等再试, 兜底瞬时网络抖动
function _labKellyFetchTradesRetry(name, attempts, delays) {
  attempts = attempts || 3;                 // 首次 + 2 次重试 = 至多 3 次
  delays = delays || [1000, 2000];          // 指数退避: 第1次重试等1s, 第2次重试等2s
  function attempt(n) {
    return _labKellyFetchTrades(name).catch(function (e) {
      if (n < attempts - 1) {
        var wait = delays[n] >= 0 ? delays[n] : delays[delays.length - 1];
        return new Promise(function (res) { setTimeout(function () { res(attempt(n + 1)); }, wait); });
      }
      throw e; // 重试耗尽, 抛给上层 decide 回退
    });
  }
  return attempt(0);
}
function _labKellyParseTrades(tr) {
  var fields = tr.fields;
  var fIdx = {};
  for (var i = 0; i < fields.length; i++) fIdx[fields[i]] = i;
  return { fields: fields, fIdx: fIdx, quadrants: tr.quadrants || {} };
}
// 分片合并(quadrants 同 key 拼接)
function _labKellyMergeShards(shards) {
  var first = shards[0];
  var quadrants = {};
  for (var s = 0; s < shards.length; s++) {
    var qs = shards[s].quadrants;
    for (var qk in qs) {
      if (!quadrants[qk]) quadrants[qk] = {};
      var mk = qs[qk];
      for (var k in mk) {
        if (!quadrants[qk][k]) quadrants[qk][k] = [];
        quadrants[qk][k] = quadrants[qk][k].concat(mk[k]);
      }
    }
  }
  return { fields: first.fields, fIdx: first.fIdx, quadrants: quadrants };
}
// 全量兜底
async function _labKellyLoadFull() {
  try {
    console.warn("[sigkelly] 分片加载失败, 回退全量 signal_kelly_trades.json(约69MB)");
    var tr = await _labKellyFetchTrades("signal_kelly_trades.json");
    state.labSigKellyTradesData = _labKellyParseTrades(tr);
    _labKellyFullFallback = true;
    return true;
  } catch (e) {
    _labKellyLoadErr = e && e.message ? e.message : String(e);
    state.labSigKellyTradesData = null;
    return false;
  }
}
// localStorage 缓存: _labKellySetCache 用于 recent.json 版本标记(不含合并后全量数据)
function _labKellySetCache(name, data, meta) {
  try {
    var obj = { data: data, genAt: meta };
    var s = JSON.stringify(obj);
    if (s.length > 5 * 1024 * 1024) return false; // 超5MB不用缓存
    localStorage.setItem("tdp_kelly_" + name + "_v1", s);
    return true;
  } catch (e) { return false; }
}
// 加载各年数据(当年为 recent.json)并合并成完整数据
async function _labKellyLoadYearParts() {
  if (state.labSigKellyTradesData && !_labKellyFullFallback) return true; // 已就绪
  if (_labKellyFullFallback) return !!state.labSigKellyTradesData;

  try {
    // 按年份加载并合并(t2026.json -> t2025.json -> t2024.json...)
    // 2026-08-29 小步1: 串行 for await 改 Promise.all 并行16年(下载从 69MB 累加降到最大单年~16MB);
    //   Promise.all 结果按输入序返回 → results 保持按年有序(_labKellyMergeShards 顺序无关也安全)。
    //   每片成功/失败都推进一次 _labKellyLoadProgress(进度按片计, 不计重试)。
    var years = ["2026", "2025", "2024", "2023", "2022", "2021", "2020", "2019", "2018", "2017", "2016", "2015", "2014", "2013", "2012", "2011"];
    _labKellyLoadProgress = { done: 0, total: years.length, lastYear: "" };
    // 2026-08-29 小步(重试+诚实回退): 每片带 _labKellyFetchTradesRetry(首次+2次重试+退避),
    //   结果用 {year, ok, data} 收敛(不静默丢弃失败年); 全 settle 后若有任一年重试仍失败 → 不渲染缺年数据, 回退全量。
    // 进度语义: 每片最终 done+=1 一次(不计重试, 16片维度不变)。
    var results = await Promise.all(years.map(function (y) {
      return _labKellyFetchTradesRetry("signal_kelly_trades_parts/t" + y + ".json")
        .then(function (yearFile) {
          var parsed = _labKellyParseTrades(yearFile);
          _labKellyLoadProgress.done += 1;
          _labKellyLoadProgress.lastYear = y;
          _labKellyProgressTickUI();
          console.log("[sigkelly] 已加载 t" + y);
          return { year: y, ok: true, data: parsed };
        })
        .catch(function (e) {
          console.warn("[sigkelly] t" + y + " 重试后仍失败(将回退全量):", e);
          _labKellyLoadProgress.done += 1;   // 每片最终仍推进一次进度(16片尝试完毕)
          _labKellyLoadProgress.lastYear = y;
          _labKellyProgressTickUI();
          return { year: y, ok: false, data: null };
        });
    }));

    // 收集重试后仍失败的年份; 有任何一片失败 → 不再用不完整数据渲染, 回退全量(比静默丢年+假全信号更诚实, §22)
    var failYears = [];
    for (var ri = 0; ri < results.length; ri++) {
      if (!results[ri].ok) failYears.push(results[ri].year);
    }
    if (failYears.length > 0) {
      console.warn("[sigkelly] 分片 t" + failYears.join(",") + " 重试后仍失败, 回退全量 signal_kelly_trades.json(约69MB)");
      return await _labKellyLoadFull();
    }

    // 全部年份都成功(不含 null)才合并渲染
    var merged = _labKellyMergeShards(results.map(function (r) { return r.data; }));
    state.labSigKellyTradesData = merged;

    return true;
  } catch (e) {
    _labKellyLoadErr = e && e.message ? e.message : String(e);
    console.error("[sigkelly] 分片加载失败, 回退全量:", e);
    return await _labKellyLoadFull();
  }
}

// 分片加载进度字符串(「⏳ 计算中…」占位/预览提示显示): 全量分片下载中返回 " · 已加载 t20xx(N/16)", 就绪后返回空串
function _labKellyProgStr() {
  var p = _labKellyLoadProgress;
  if (!p || !p.total || p.done >= p.total) return "";
  return " · 已加载 t" + (p.lastYear || "--") + "(" + p.done + "/" + p.total + ")";
}

// 分片加载进度实时刷新(2026-08-29 小步2): 每片完成把在册「⏳ 计算中…」占位文本就地换为最新进度,
//   让用户看到 "已加载 t20xx(N/16)" 一直在走, 不等整次渲染; 就绪后占位会随 recompute 整建消失
function _labKellyProgressTickUI() {
  var els = document.querySelectorAll(".lab-sigkelly-all-loading");
  if (!els.length) return;
  var txt = "⏳ 计算中…" + _labKellyProgStr();
  for (var i = 0; i < els.length; i++) els[i].textContent = txt;
}

// 主入口: 分片加载(t2011-t2026 合并)
// 返回 Promise<true>就绪 / <false>失败(错误已记录在 _labKellyLoadErr)
// 内存态(state.labSigKellyTradesData)已就绪时直接返回,不重复网络请求。
async function _labKellyTradesEnsure(opt) {
  if (state.labSigKellyTradesData && !_labKellyFullFallback) return true; // 已就绪
  if (_labKellyFullFallback) return !!state.labSigKellyTradesData;

  // 加载完整分片数据(recent + t2011-t2026 合并, localStorage 不缓存合并后全量)
  return await _labKellyLoadYearParts();
}

// 加载 trades.json 并重算所有 quadrant x period x mode 统计(方案A)
async function _kellyApplyFeeRecompute(feeParams) {
  var data = state.labSigKellyData;
  if (!data || !data.quadrants) return null;
  // S06(codex-task-20260825-001): 动态基座态先确保快照就绪再进计算(单例 promise, 已就绪时立即 resolve;
  // 失败返回 null → 谓词层 fail-open 放行 + result._s6warn 可见警示, 绝不静默退回其他模式)。
  if (state.labSigKellyFadeModeBase === "s06" && typeof window._tdsS06StateEnsure === "function") {
    await window._tdsS06StateEnsure();
  }
  // 加载 trades.json(分片加载+localStorage缓存, 2026-08-28)
  if (!state.labSigKellyTradesData) {
    var ok = await _labKellyTradesEnsure();
    if (!ok) { console.error("[sigkelly] trades.json load failed"); return null; }
    _kellyClearComputeCaches();
  }
  var td = state.labSigKellyTradesData;
  var fields = td.fields || [];
  var fIdx = {};
  fields.forEach(function (f, i) { fIdx[f] = i; });
  var buyAmount = td.buy_amount || (data.config && data.config.buy_amount) || 10000;
  var cutoffs = (data.config && data.config.period_cutoffs) || {};
  var quads = td.quadrants || {};
  var quadMeta = data.quadrants || {};
  quadMeta.all = { label: "全信号", desc: "评级高低分区并集(rating_high+mid+low 互斥全量), 全量信号不拆分, 按最新降亏组合实时预估" };
  var periods = (data.config && data.config.periods) || { y1: "近1年", y3: "近3年", all: "全部" };
  var sellModes = (data.config && data.config.sell_modes) || {};
  // 全信号伪象限「all」: rating_high+mid+low 分区并集(互斥全量覆盖 = 全量信号不拆分), 供「最后结果」全信号表实时计算(随toggle/费率/周期变化)
  var quadsAll = {};
  var _qAllRatingKeys = ["rating_high", "rating_mid", "rating_low"];
  for (var _qmk in sellModes) {
    var _qa = [];
    _qAllRatingKeys.forEach(function (_rk) { var _qq = (quads[_rk] || {})[_qmk] || []; _qa = _qa.concat(_qq); });
    quadsAll[_qmk] = _qa;
  }
  // 降亏过滤toggle(正交叠加: filter交易集 vs 费率改profit, 独立不互斥)
  // 性能专项(2026-08-23): 本函数含 await 让步(桶间分片), 让步期间用户可能继续改 toggle 原地 mutate
  // labSigKellyFilters → 单轮内口径撕裂。此处拍快照(浅拷贝), 本轮全程用快照算完; 用户新态由
  // _kellyRunRecompute 的 pending 合批收尾再跑一轮, 最终一致。
  var filters = Object.assign({}, state.labSigKellyFilters || _kellyDefaultFilters());
  // v3标志需维度查找map(mkt_dim/rating_dim不在trade数组内,编码在quadrant key里)
  var _tradeDims = state.labSigKellyTradeDims;
  if (!_tradeDims && td.quadrants) {
    _tradeDims = _kellyBuildTradeDims(td, fIdx);
    state.labSigKellyTradeDims = _tradeDims;
  }
  // ④ filters+feeParams+金额口径签名缓存: 连点命中直接复用, 不重算
  var feeSig = _kellyFeeSig(feeParams);
  // 金额口径(2026-08-13 用户纠正恢复): 每日资金池等分+top-K(每笔=10000/当日保留基笔数, 每日总投入恒1万 → K档最大持仓恒定; 撤销2026-08-12"每笔固定1万"fixed口径)
  // #49 fix(issue49): ai长线(G/H/I)仓位管理 开关态并入顶层缓存签名——否则 7827 短路命中旧缓存(result 无 __gihb1)致开关无效(卡片G/H/I恒显原始值), 须切换强制重算
  // #xx: G 档位也并入签名(档位切换同开关态一样强制重算, 否则短路命中旧档 __gihb1)
  // S06(2026-08-25): 动态基座态并入缓存签名(+快照覆盖期末日), 否则 s06↔静态档切换会命中脏缓存
  // (filters 静态快照相同但判定层 per-date 结果不同); 快照更新(coverage_end 前移)也强制重算。
  var _labS06 = (state.labSigKellyFadeModeBase === "s06");
  var cacheKey = feeSig + "|pool|" + JSON.stringify(filters) + "|gih" + (state.labSigKellyGihOn ? ("1|" + _kellyGihGTier()) : "0")
    + (_labS06 ? ("|s06|" + (((typeof window._tdsS06Status === "function") && window._tdsS06Status().coverageEnd) || "")) : "");
  if (_kellyStatsCacheKey === cacheKey && _kellyStatsCacheVal) {
    return _kellyStatsCacheVal;
  }
  var result = {};
  // 降亏toggle过滤谓词(只算一次, positionCap/仓位控制共用)
  var monthMask = _kellyActiveMonthMask(filters);
  // S06(codex-task-20260825-001): 动态基座态 → passesFade 改 per-date: 按每笔 signal_date 取当日生效基座
  // (a9/new15)的完整键集过滤; 快照不可用/日期超覆盖期 = 该笔 fail-open 放行 + _s6OpenSet 收集唯一笔
  // (result._s6warn 可见警示, 绝不静默退回其他模式); 非 s06 态路径逐位不变(§23.7 纯新增)。
  // 计数去重(2026-08-26): 同一笔在统计链被多 passFn 多遍扫描(主池/NB池/阶段1 toggledByMode/posCap K1-4),
  // 原计数器每调用 ++ 致警示 N 虚高(7370 vs 真实~2640); 改 Set 按 _kellyBaseKey 唯一化, 警示取 .size。
  var _s6OpenSet = new Set();
  var _s6F6 = function (t) {
    return (typeof window._tdsS06FiltersForDate === "function") ? window._tdsS06FiltersForDate(String(t[fIdx.signal_date] || "")) : null;
  };
  var passesFade;
  if (_labS06) {
    passesFade = function (t) {
      var f6 = _s6F6(t);
      if (!f6) { _s6OpenSet.add(_kellyBaseKey(t, fIdx)); return true; }   // fail-open + 可见计数(按唯一笔去重)
      return _kellyPassesFadeFilters(t, fIdx, f6, _kellyTradeFeatureCache, _tradeDims, _kellyActiveMonthMask(f6));
    };
  } else {
    passesFade = function (t) {
      return _kellyPassesFadeFilters(t, fIdx, filters, _kellyTradeFeatureCache, _tradeDims, monthMask);
    };
  }
  // #xx(2026-08-22) bullAuxBackupStop(牛市·主升×辅备买全停) G/H/I 长线豁免: 该键仅适用 mode A-F 短线,
  //   G/H/I 长线不适配不套用(挖掘报告 §6.4)。实现=构造 filtersNoBull 变体(仅 bullAuxBackupStop=false, 其余同),
  //   G/H/I 桶的 fade 谓词与 positionCap 基笔池/每日池计数都用 NoBull 版 → 开关键后 G/H/I 统计与关时逐位一致(§22)。
  //   默认关(_bullOn=false)时 NoBull 变体恒 null, 全部回落原路径, 零行为差异(§23.7 纯新增)。
  // S06 态: a9 基座含 bullAuxBackupStop、new15 不含 → A-F 桶 per-date 天然按日生效; G/H/I 长线恒豁免,
  //   故强制 _bullOn=true 走 per-date NoBull 版(当日基座键集 − bullAuxBackupStop, 共享缓存变体)。
  var _bullOn = _labS06 ? true : !!filters.bullAuxBackupStop;
  var passesFadeNoBull = null;
  if (_labS06) {
    var _s6NoBullCache = {};   // baseId -> 键集−牛停 共享只读变体(a9/new15 至多两份)
    var _s6BuildNB = function (baseId) {
      var f = {};
      var allK = window._KELLY_FADE_ALL_KEYS || [];
      for (var i = 0; i < allK.length; i++) f[allK[i]] = false;
      var p = (typeof window._tdsFadeModeById === "function") ? window._tdsFadeModeById(baseId) : null;
      if (p && Array.isArray(p.keys)) for (var j = 0; j < p.keys.length; j++) f[p.keys[j]] = true;
      f.bullAuxBackupStop = false;
      return f;
    };
    passesFadeNoBull = function (t) {
      var dStr = String(t[fIdx.signal_date] || "");
      var b = (typeof window._tdsS06BaseForDate === "function") ? window._tdsS06BaseForDate(dStr) : null;
      if (!b || !b.ok) { _s6OpenSet.add(_kellyBaseKey(t, fIdx)); return true; }   // fail-open 与主谓词同口径(共享同一 Set)
      if (!_s6NoBullCache[b.base]) _s6NoBullCache[b.base] = _s6BuildNB(b.base);
      var nb = _s6NoBullCache[b.base];
      return _kellyPassesFadeFilters(t, fIdx, nb, _kellyTradeFeatureCache, _tradeDims, _kellyActiveMonthMask(nb));
    };
  } else if (_bullOn) {
    var filtersNoBull = {};
    for (var _fbk in filters) filtersNoBull[_fbk] = filters[_fbk];
    filtersNoBull.bullAuxBackupStop = false;
    passesFadeNoBull = (function (_fNB) {
      return function (t) {
        return _kellyPassesFadeFilters(t, fIdx, _fNB, _kellyTradeFeatureCache, _tradeDims, monthMask);
      };
    })(filtersNoBull);
  }
  // G/H/I 判定助手(与 _sigKellyModeSpanKey/_kellyIsGih 同口径: G/H/I=中长线)
  var _isLongMode = function (mk) { return mk === "G" || mk === "H" || mk === "I"; };
  // positionCap 仓位控制过滤: 统一在模式之前生效(10模式共享同一批基笔, 同一信号同一天只算一次跨模式不重复计)
  // #xx: 新键开启时基笔池算两份(A-F 口径含新键 / G-H-I 豁免版不含), 两模式组各用各的 kept/dayCounts(§22)
  var posCapKept = null;
  var posDayCounts = null; // 每日资金池等分: 当日保留基笔数{signal_date:count}, 基于保留集合全集(跨mode)统计(2026-08-13恢复)
  var posCapKeptNB = null; // G/H/I 豁免版(仅 _bullOn 时计算)
  var posDayCountsNB = null;
  if (filters.positionCap && filters.positionCapK > 0) {
    var basePool = await _kellyCollectBasePool(quads, sellModes, fIdx, passesFade);
    posCapKept = _kellyPositionCapKeptKeys(basePool, fIdx, filters.positionCapK);
    posDayCounts = _kellyKeptDayCounts(posCapKept);
    if (_bullOn) {
      var basePoolNB = await _kellyCollectBasePool(quads, sellModes, fIdx, passesFadeNoBull);
      posCapKeptNB = _kellyPositionCapKeptKeys(basePoolNB, fIdx, filters.positionCapK);
      posDayCountsNB = _kellyKeptDayCounts(posCapKeptNB);
    }
  }
  // ① 按(qk,mode)只过滤一次(不含period cutoff), 5个period从过滤结果按cutoff取子集(扫描5->1遍)
  // ② v3/v4特征经缓存Map只算一次, 后续O(1)查表
  for (var qk in quadMeta) {
    result[qk] = {};
    // 阶段1: 每个(qk,mode)只跑一次toggle过滤(昂贵的v3/v4特征分支只算一遍)
    var toggledByMode = {};
    for (var modeKey in sellModes) {
      var rawTrades = (qk === "all") ? (quadsAll[modeKey] || []) : ((quads[qk] || {})[modeKey] || []);
      // #xx: G/H/I 且新键开 → 用豁免版谓词+kept(同步 filter, 闭包捕获当前 _pf/_pk 无延迟执行问题)
      var _pf = (_bullOn && _isLongMode(modeKey)) ? passesFadeNoBull : passesFade;
      var _pk = (_bullOn && _isLongMode(modeKey) && posCapKeptNB) ? posCapKeptNB : posCapKept;
      toggledByMode[modeKey] = rawTrades.filter(function (t) {
        if (!_pf(t)) return false;
        if (_pk && !_pk[_kellyBaseKey(t, fIdx)]) return false;
        return true;
      });
      await _kellyYield(); // 桶间让步(2026-08-23 性能专项): 单模式过滤 ~10-30ms, 10 模式连排原为 ~100-300ms 同步块
    }
    // 阶段2: 每个period从toggled结果按cutoff取子集(轻量字符串比较)
    // 逐桶缓存: toggle改动只影响匹配到删除trade的桶, 未被影响的桶(feeSig+toggled数组未变)直接复用上次stats(纯函数, 结果精确一致; fixed口径每笔金额恒定, 桶缓存安全)
    for (var periodKey in periods) result[qk][periodKey] = {};
    for (var modeKey in sellModes) {
      var toggled = toggledByMode[modeKey];
      var bKey = qk + "|" + modeKey;
      // #49: ai长线(G/H/I)仓位管理 开关态并入桶缓存签名, 切换时强制重算(否则桶命中不更新 G/H/I 硬控 stats)
      var _gihCk = (!!state.labSigKellyGihOn) ? ("G1|" + _kellyGihGTier()) : "G0";
      var cachedBucket = _kellyBucketStatsCache.get(bKey);
      var statsByPeriod;
      if (cachedBucket && cachedBucket.gih === _gihCk && cachedBucket.feeSig === feeSig && _kellySameTradeArray(cachedBucket.toggled, toggled)) {
        statsByPeriod = cachedBucket.stats;
      } else {
        statsByPeriod = {};
        for (var periodKey in periods) {
          var cutoff = cutoffs[periodKey] || "0";
          var trades;
          if (cutoff && cutoff !== "0") {
            // 周期cutoff子集(保持原filter语义: buy_date < cutoff 排除)
            trades = toggled.filter(function (t) { return (t[fIdx.buy_date] || "") >= cutoff; });
          } else {
            trades = toggled;
          }
          // ③ 费率重算缓存(feeParams+单笔金额未变同一trade只算一次, 消灭跨bucket重复)
          // #xx: G/H/I 且新键开 → 每日池计数用豁免版(与该桶 kept 口径一致 §22)
          var _pdcM = (_bullOn && _isLongMode(modeKey) && posDayCountsNB) ? posDayCountsNB : posDayCounts;
          var recomputed = trades.map(function (t) {
            var amt = _kellyPerTradeAmount(t, fIdx, buyAmount, _pdcM ? _pdcM[t[fIdx.signal_date]] : null);
            var c = _kellyRecomputeCache.get(t);
            if (!c || c.sig !== feeSig || c.amt !== amt) {
              var r = _kellyRecomputeTrade(t, fIdx, feeParams, amt);
              c = { sig: feeSig, amt: amt, r: r };
              _kellyRecomputeCache.set(t, c);
            }
            return { profit: c.r.profit, return_pct: c.r.return_pct, fee_cost: c.r.fee_cost,
                     buy_date: t[fIdx.buy_date] || "", sell_date: t[fIdx.sell_date] || "",
                     hold_days: t[fIdx.hold_days] || 0, amount: amt };
          });
          statsByPeriod[periodKey] = _kellyComputeStats(recomputed, periodKey, buyAmount);
          // #49+#xx ai长线模式(G/H/I)仓位管理: 开时对 G/H/I 模式额外套各模式独立仓位策略(G=P≤3d@13万/H=满仓不买@7万/I=满仓不买@16万),
          // b0(保守)/b1(乐观) stats 直接写入 statsByPeriod(随桶缓存)。内核 _kellyAihlineSim 按 strategy.method 分发
          // (B=FIFO/P=P≤3d先卖年轻/A=满仓不买), 已按报告逐位对齐(§21); 下方 result 赋值处注册为 result[qk][period][mode+"__gihb0/b1"]
          if (_kellyIsGih(modeKey) && state.labSigKellyGihOn && _kellyGihStrat(modeKey)) {
            var _gihSim = _kellyAihlineApply(recomputed, _kellyGihStrat(modeKey), periodKey);
            statsByPeriod[periodKey + "__gihb0"] = _kellyComputeStats(_gihSim.b0, periodKey, buyAmount);
            statsByPeriod[periodKey + "__gihb1"] = _kellyComputeStats(_gihSim.b1, periodKey, buyAmount);
            statsByPeriod[periodKey + "__gihpeak"] = _gihSim.peak;
          }
        }
        // 缓存上限保护: 只保留最近~5个过滤状态(144桶×5=720), 防无界增长
        if (_kellyBucketStatsCache.size >= 720) _kellyBucketStatsCache.clear();
        _kellyBucketStatsCache.set(bKey, { feeSig: feeSig, toggled: toggled, stats: statsByPeriod, gih: _gihCk });
      }
      for (var periodKey in periods) result[qk][periodKey][modeKey] = statsByPeriod[periodKey];
      // #49+#xx: ai长线各模式独立策略 stats 从 statsByPeriod 注册到 result[qk][period][mode+"__gihb0/b1"], 卡片/对比表按 modeKey 取用(§22)
      if (state.labSigKellyGihOn && _kellyIsGih(modeKey)) {
        for (var periodKey in periods) {
          if (statsByPeriod[periodKey + "__gihb0"] !== undefined) {
            result[qk][periodKey][modeKey + "__gihb0"] = statsByPeriod[periodKey + "__gihb0"];
            result[qk][periodKey][modeKey + "__gihb1"] = statsByPeriod[periodKey + "__gihb1"];
            result[qk][periodKey][modeKey + "__gihpeak"] = statsByPeriod[periodKey + "__gihpeak"];
          }
        }
      }
      await _kellyYield(); // 桶间让步(2026-08-23 性能专项): 冷桶(费率重算+统计)单桶可达 ~50-150ms, 桶间让步防 >200ms 连排
    }
    // 全信号伪象限: 按年聚合(「最后结果」表用, 全周期口径非当前period窗口, 与toggle/费率联动)
    // 2026-08-14 #BC 按年窗口口径归正(方案1): 仅累加 G 模式(当前推荐卖出法, 与「总建议=遵守G模式卖出」语义对齐);
    //   原实现遍历全 sellModes(A-J 10模式)累加 → 同一基笔信号 10 模式各一条 × 全累加 → +1,049万 量级虚高(名实不符)
    // 2026-08-14 扩展: 按年窗口增长表支持 A-G 各模式独立查看(下拉切换)。allYearlyByMode = {modeKey: yearlyMap},
    //   每个模式各自独立按年聚合(不做"全模式回退", 除非该模式无 signal); allYearly 仍取 G 模式(总建议语义, 兼容原展示)。
    //   每个模式用 toggledByMode[modeKey](已随降亏组合/费率/周期过滤) → 与 toggle/费率/周期联动(§22); 重算复用 _kellyRecomputeCache 不重复计算。
    if (qk === "all") {
      // 2026-08-12 按年峰值资金收益率 = 该年累计净盈亏 / 该年峰值同时持仓资金 × 100 (与卡面/建议面板 return_pct_max_holding 同口径, §22)
      var _aggYearlyMap = function (_ymTrades, _pdcY) {
        var _ymap = {};
        for (var _bi = 0; _bi < _ymTrades.length; _bi++) {
          var _bT = _ymTrades[_bi];
          var _bYr = (_bT[fIdx.buy_date] || "").substring(0, 4);
          if (!_bYr) continue;
          var _bAmt = _kellyPerTradeAmount(_bT, fIdx, buyAmount, _pdcY ? _pdcY[_bT[fIdx.signal_date]] : null);
          var _bC = _kellyRecomputeCache.get(_bT);
          if (!_bC || _bC.sig !== feeSig || _bC.amt !== _bAmt) {
            var _bR = _kellyRecomputeTrade(_bT, fIdx, feeParams, _bAmt);
            _bC = { sig: feeSig, amt: _bAmt, r: _bR };
            _kellyRecomputeCache.set(_bT, _bC);
          }
          var _bK = _ymap[_bYr];
          if (!_bK) { _bK = _ymap[_bYr] = { profit: 0, n: 0, wins: 0, loss: 0, _trades: [] }; }
          _bK.profit += _bC.r.profit;
          _bK.n++;
          if (_bC.r.profit > 0) _bK.wins++; else _bK.loss++;
          _bK._trades.push({ buy_date: _bT[fIdx.buy_date] || "", sell_date: _bT[fIdx.sell_date] || "", amount: _bAmt, profit: _bC.r.profit });
        }
        for (var _by in _ymap) {
          var _bv = _ymap[_by];
          var _bmcc = _kellyMaxConcurrentCapital(_bv._trades);
          _bv.peak_capital = _bmcc;
          _bv.peak_return_pct = _bmcc > 0 ? Math.round(_bv.profit / _bmcc * 100 * 10000) / 10000 : 0;
          // 2026-08-14 按年峰值资金回撤 = 该年最大回撤金额 / 该年峰值同时持仓资金 × 100 (与 hoverpop/AI仓位K评级 max_drawdown/max_concurrent_capital 同口径, 只是按年; §22)
          var _bdd = _kellyMaxDrawdown(_bv._trades).abs;
          _bv.peak_drawdown_pct = _bmcc > 0 ? Math.round(_bdd / _bmcc * 100 * 10000) / 10000 : 0;
          delete _bv._trades;
        }
        return _ymap;
      };
      // 逐模式独立按年聚合(A-G 全模式; 无 signal 的模式(如 H/I 某些档)留空表)
      // #xx: G/H/I 且新键开 → 按年聚合金额用豁免版每日池计数(与该模式桶口径一致 §22)
      var allYearlyByMode = {};
      for (var _amk in sellModes) {
        var _amTrades = toggledByMode[_amk] || [];
        if (!_amTrades.length) continue; // 无 signal 的模式不出表(留空, 前端显示暂无数据)
        var _pdcY = (_bullOn && _isLongMode(_amk) && posDayCountsNB) ? posDayCountsNB : posDayCounts;
        allYearlyByMode[_amk] = _aggYearlyMap(_amTrades, _pdcY);
        await _kellyYield(); // 桶间让步(2026-08-23 性能专项): 全信号按年聚合逐模式分片
      }
      // 总建议语义: 优先 G 模式(当前推荐卖出法; 若卖出模式结构变化, 取 signal:true 的推荐模式), 兼容原 allYearly 展示
      var _yyModeKey = null;
      for (var _ymk0 in sellModes) { if (_ymk0 === "G") { _yyModeKey = _ymk0; break; } }
      if (!_yyModeKey) {
        for (var _ymk1 in sellModes) { if ((sellModes[_ymk1] || {}).signal && String((sellModes[_ymk1] || {}).label || "").indexOf("卖出信号") >= 0) { _yyModeKey = _ymk1; break; } }
      }
      result.allYearlyByMode = allYearlyByMode;
      result.allYearly = (_yyModeKey && allYearlyByMode[_yyModeKey]) ? allYearlyByMode[_yyModeKey] : {};
      result.allYearlyMode = _yyModeKey || "all"; // 记录口径(G模式)
    }
  }
  // #54 2026-08-13: AI仓位建议 K 档评级动态化——positionCap 开启时用当前 filters+费率+最新数据重算 K=1..4(A模式·all伪象限·全周期)写入共享动态源
  // 首页 app.js 与凯利区 lab.js 经 common.js _aiPoscapRatingPopHtml 同读(§22 两处一致); 峰值资金回撤=最大回撤金额÷本金(concCap=峰值同时持仓资金), 与静态快照同口径公式
  try {
    if (filters.positionCap && filters.positionCapK > 0 && quadsAll) {
      var _posModeKey = null;
      for (var _pmk in sellModes) { if (_pmk === "A") { _posModeKey = _pmk; break; } }
      if (!_posModeKey) {
        for (var _pmk2 in sellModes) { if (String((sellModes[_pmk2] || {}).label || "").indexOf("固定10") >= 0) { _posModeKey = _pmk2; break; } }
      }
      if (_posModeKey && quadsAll[_posModeKey]) {
        var _posBase = basePool || (await _kellyCollectBasePool(quads, sellModes, fIdx, passesFade));
        var _posRaw = quadsAll[_posModeKey];
        var _posVals = {};
        for (var _pk = 1; _pk <= 4; _pk++) {
          await _kellyYield(); // K档间让步(2026-08-23 性能专项): 每档全池 kept 重算 ~50-150ms
          var _kept = _kellyPositionCapKeptKeys(_posBase, fIdx, _pk);
          // 每日资金池等分(2026-08-13恢复): 该K档当月的当日保留基笔数, 与卡片/弹窗同口径(§22)
          var _posDayCounts = _kellyKeptDayCounts(_kept);
          var _keptArr = [];
          for (var _ti = 0; _ti < _posRaw.length; _ti++) {
            var _tb = _posRaw[_ti];
            if (!passesFade(_tb)) continue;
            if (!_kept[_kellyBaseKey(_tb, fIdx)]) continue;
            _keptArr.push(_tb);
          }
          var _recomp = _keptArr.map(function (tt) {
            var _amt = _kellyPerTradeAmount(tt, fIdx, buyAmount, _posDayCounts ? _posDayCounts[tt[fIdx.signal_date]] : null);
            var _c = _kellyRecomputeCache.get(tt);
            if (!_c || _c.sig !== feeSig || _c.amt !== _amt) {
              var _r = _kellyRecomputeTrade(tt, fIdx, feeParams, _amt);
              _c = { sig: feeSig, amt: _amt, r: _r };
              _kellyRecomputeCache.set(tt, _c);
            }
            return { profit: _c.r.profit, return_pct: _c.r.return_pct, fee_cost: _c.r.fee_cost,
                     buy_date: tt[fIdx.buy_date] || "", sell_date: tt[fIdx.sell_date] || "",
                     hold_days: tt[fIdx.hold_days] || 0, amount: _amt };
          });
          var _st = _kellyComputeStats(_recomp, "all", buyAmount);
          var _ret = _st.return_pct_max_holding;
          var _dd = _st.max_concurrent_capital > 0 ? Math.round(_st.max_drawdown / _st.max_concurrent_capital * 100 * 10000) / 10000 : 0;
          _posVals[_pk] = {
            name: ({ 1: "最激进", 2: "次稳健", 3: "最稳健", 4: "最保守" })[_pk],
            ret: _ret.toFixed(2) + "%",
            dd: _dd.toFixed(2) + "%",
            ra: _dd > 0 ? (_ret / _dd).toFixed(2) : "-",
            n: _st.n.toLocaleString("en-US"),
            retNum: _ret, ddNum: _dd, nNum: _st.n
          };
        }
        window._AI_POSCAP_RATING_DYNAMIC = { computed: true, date: (data.generated_at || ""), fee: _kellyFeeLabel(), cfg: null, values: _posVals };
      } else {
        window._AI_POSCAP_RATING_DYNAMIC = { computed: false, values: null, date: null, fee: null, cfg: null };
      }
    } else {
      window._AI_POSCAP_RATING_DYNAMIC = { computed: false, values: null, date: null, fee: null, cfg: null };
    }
  } catch (e) {
    console.error("[sigkelly] posRating dynamic compute failed:", e);
    window._AI_POSCAP_RATING_DYNAMIC = { computed: false, values: null, date: null, fee: null, cfg: null };
  }
  // S06 降级警示(codex-task-20260825-001, 可见不静默): 快照失败/覆盖期外笔数 → result._s6warn,
  // 由凯利区模式下拉旁状态 span 展示; 正常态无该字段(span 隐藏)。缓存命中路径随旧 result 一致复用。
  if (_labS06) {
    var _s6WarnParts = [];
    if (typeof window._tdsS06Status === "function") {
      var _st6 = window._tdsS06Status();
      if (!_st6.loaded && _st6.err) _s6WarnParts.push("⚠ S06 快照加载失败了(" + _st6.err + ")，系统还在努力读，你看到的数据暂时是不过滤的完整版本（不是偷偷切到其他模式，只是先把能展示的展示出来）");
    }
    if (_s6OpenSet.size > 0) _s6WarnParts.push("⚠ 有 " + _s6OpenSet.size + " 笔是 2014-2015 年的老历史数据，S06 快照的日期覆盖不到那么早（那时候 A股风格和现在很不一样，系统没把握套用现在的判断规则），所以这 " + _s6OpenSet.size + " 笔就先照常展示了，没有硬套过滤规则——数据给你看，只是标注一下这批和近年的口径不太一样。举例说明：比如 2014 年那波大牛市，按 2026 年的标准会判「进攻王」，但 2014 年实际风格完全不同，用现在的规则去套就容易出错，所以这批老数据干脆不套规则，直接展示原始信号");
    if (_s6WarnParts.length) result._s6warn = _s6WarnParts.join(" ");
  }
  _kellyStatsCacheKey = cacheKey;
  _kellyStatsCacheVal = result;
  return result;
}

// 费率切换处理
async function _kellyOnFeeChange(presetKey) {
  if (!state.labSigKellyFeePreset) state.labSigKellyFeePreset = "etf_main";
  state.labSigKellyFeePreset = presetKey;
  // 更新 feeParams
  if (presetKey === "custom") {
    state.labSigKellyFeeParams = _kellyReadCustomParams();
  } else {
    var preset = KELLY_FEE_PRESETS.find(function (p) { return p.key === presetKey; });
    if (preset) {
      state.labSigKellyFeeParams = {
        commission_rate: preset.commission_rate, min_commission: preset.min_commission,
        slippage: preset.slippage, transfer_fee_rate_sh: preset.transfer_fee_rate_sh,
        stamp_duty_rate: preset.stamp_duty_rate,
      };
    }
  }
  var bar = document.querySelector(".lab-sigkelly-bar");
  var host = document.querySelector(".lab-sigkelly-host");
  if (!bar || !host || !state.labSigKellyData) return;
  // 始终重算(含默认档)以获取费率消耗列; loading先paint再算(方案B⑤), 防重入(方案B⑥)
  _renderSigKellyBar(bar, state.labSigKellyData, state.labSigKellyPeriod);
  await _kellyRunRecompute(host,
    '<div class="lab-custom-loading">⏳ 加载交易数据重算费率…</div>',
    function (stats) {
      if (stats) {
        state.labSigKellyFeeStats = stats;
      } else {
        // 加载失败: 回退原始stats(无费率消耗列) — 2026-08-14 默认档改 ETF主流(etf_main)
        state.labSigKellyFeePreset = "etf_main";
        state.labSigKellyFeeParams = {
          commission_rate: 0.00005, min_commission: 0.1, slippage: 0.001,
          transfer_fee_rate_sh: 0.00001, stamp_duty_rate: 0,
        };
        state.labSigKellyFeeStats = null;
      }
    },
    function (h) {
      // 【P0 防御兜底】h=_kellyRunRecompute 收尾重取的在册 host(失联换新时非闭包值); bar 实时重查防写死节点
      var hb = h || host;
      var bb = document.querySelector(".lab-sigkelly-bar") || bar;
      _renderSigKellyBar(bb, state.labSigKellyData, state.labSigKellyPeriod);
      _updateSigKellyQuadrantsInPlace(hb, state.labSigKellyData, state.labSigKellyPeriod);
    }
  );
}

// 费率输入框 change: 读取表单值重算(不重渲染 bar, 保留输入焦点)
async function _kellyOnFormChange() {
  state.labSigKellyFeePreset = "custom";
  state.labSigKellyFeeParams = _kellyReadCustomParams();
  var bar = document.querySelector(".lab-sigkelly-bar");
  var host = document.querySelector(".lab-sigkelly-host");
  if (!bar || !host || !state.labSigKellyData) return;
  // 更新预设按钮 active 状态(仅切换 class, 不重渲染 bar 保留输入焦点)
  bar.querySelectorAll(".lab-sigkelly-fee-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.fee === "custom");
  });
  // loading先paint再算(方案B⑤), 防重入(方案B⑥)
  await _kellyRunRecompute(host,
    '<div class="lab-custom-loading">⏳ 加载交易数据重算费率…</div>',
    function (stats) {
      if (stats) {
        state.labSigKellyFeeStats = stats;
      } else {
        state.labSigKellyFeeStats = null;
      }
    },
    function (h) { _updateSigKellyQuadrantsInPlace(h || host, state.labSigKellyData, state.labSigKellyPeriod); } // h=收尾兜底重取的在册host
  );
}

// 读取自定义费率输入框值
function _kellyReadCustomParams() {
  var bar = document.querySelector(".lab-sigkelly-bar");
  if (!bar) return { commission_rate: 0.0003, min_commission: 5, slippage: 0.001, transfer_fee_rate_sh: 0.00001, stamp_duty_rate: 0 };
  function val(cls) {
    var el = bar.querySelector(cls);
    return el ? (parseFloat(el.value) || 0) : 0;
  }
  return {
    commission_rate: val(".lab-sigkelly-fee-input-comm") / 10000,
    min_commission: val(".lab-sigkelly-fee-input-min"),
    slippage: val(".lab-sigkelly-fee-input-slip") / 1000,
    transfer_fee_rate_sh: val(".lab-sigkelly-fee-input-transfer") / 10000,
    stamp_duty_rate: val(".lab-sigkelly-fee-input-stamp") / 10000,
  };
}

// 降亏过滤toggle切换处理(仿_kellyOnFeeChange, 但不改费率只过滤交易集)
// toggle改交易集合(filter) vs 费率改profit(recompute), 正交叠加不互斥
// S06(codex-task-20260825-001): 手动勾/取消任一标签 = 退出动态模式进「⚙️自定义组合」(handoff §五.功能3)——
// 默认(无参)清除 s06 态; keepS06=true 仅限「非成员改动」路径(模式下拉选 s06/新键特征就绪补渲)保持动态态。
async function _kellyOnFilterChange(_opts) {
  var host = document.querySelector(".lab-sigkelly-host");
  var bar = document.querySelector(".lab-sigkelly-bar");
  if (!host || !state.labSigKellyData) return;
  if (!(_opts && _opts.keepS06) && state.labSigKellyFadeModeBase === "s06") state.labSigKellyFadeModeBase = null;
  // loading先paint再算(方案B⑤), 防重入(方案B⑥)
  await _kellyRunRecompute(host,
    '<div class="lab-custom-loading">⏳ 过滤交易数据重算…</div>',
    function (stats) {
      if (stats) {
        state.labSigKellyFeeStats = stats;
      } else {
        state.labSigKellyFeeStats = null;
      }
    },
    function (h) {
      // #54 2026-08-13: toggle 变更后重渲染 bar → K 档评级 hoverpop/positionCap label 读共享动态源刷新(与费率切换路径一致; _kellyRunRecompute 内已重算写 _AI_POSCAP_RATING_DYNAMIC)
      // 【P0 防御兜底】h=_kellyRunRecompute 收尾重取的在册 host(优先), 闭包 host 兜底; bar 实时重查防写死节点
      var hb = h || host;
      var bb = document.querySelector(".lab-sigkelly-bar") || bar;
      if (bb) _renderSigKellyBar(bb, state.labSigKellyData, state.labSigKellyPeriod);
      _updateSigKellyQuadrantsInPlace(hb, state.labSigKellyData, state.labSigKellyPeriod);
    }
  );
  // 2026-08-13 降亏状态持久化: 所有 filter toggle 改动都经此函数, 统一写 tds_kelly_filters(AI宏 7成员+组合, 供首页 AI 开关联动; 幂等小JSON)
  _kellyPersistFilters();
}

// 当前费率标签
function _kellyFeeLabel() {
  var preset = KELLY_FEE_PRESETS.find(function (p) { return p.key === state.labSigKellyFeePreset; });
  return preset ? preset.label : "ETF主流";
}
// 轻量 toast(凯利区, #54 2026-08-13 重置按钮反馈)
function _kellyToast(msg) {
  try {
    var el = document.querySelector(".lab-kelly-toast");
    if (!el) {
      el = document.createElement("div");
      el.className = "lab-kelly-toast";
      el.style.cssText = "position:fixed;left:50%;bottom:96px;transform:translateX(-50%);z-index:9999;max-width:88vw;background:var(--bg-card,#fff);color:var(--text-1,#222);border:1px solid var(--primary,#c8a24a);border-radius:8px;box-shadow:0 4px 16px rgba(0,0,0,0.18);padding:10px 14px;font-size:12px;line-height:1.6;display:none;";
      document.body.appendChild(el);
    }
    el.textContent = msg;
    el.style.display = "block";
    if (el._t) clearTimeout(el._t);
    el._t = setTimeout(function () { el.style.display = "none"; }, 3200);
  } catch (e) {}
}

// 费率客调快捷键 0-4+C(输入框聚焦时禁用,modal打开时禁用)
document.addEventListener("keydown", (e) => {
  if (state.labSubMode !== "sigkelly") return;
  var tag = (e.target.tagName || "").toLowerCase();
  if (tag === "input" || tag === "textarea" || tag === "select") return;
  if (e.target.isContentEditable) return;
  // modal 打开时不响应(避免与 modal 内交互冲突)
  var modalEl = document.getElementById("lab-sigkelly-trades-overlay");
  if (modalEl && modalEl.style.display !== "none") return;
  var key = e.key.toUpperCase();
  if (key >= "0" && key <= "4") {
    e.preventDefault();
    _kellyOnFeeChange(KELLY_FEE_PRESETS[+key].key);
  } else if (key === "C") {
    e.preventDefault();
    _kellyOnFeeChange("custom");
  }
});

// === 信号凯利回测(sigkelly):6象限(3评级+3 ETF归类) x 4模式 x 3周期 半凯利仓位回测 ===
// 数据: ./data/signal_kelly_backtest.json (后端 signal_kelly_backtest.py 生成, <100KB 走 CF Workers)
// 布局: 顶部说明 + 周期切换tab(y1/y3/all) + 评级3卡 + ETF3卡(每卡4模式表格) + 底部色标
async function renderSigKellyLab() {
  const wrapper = document.createElement("div");
  wrapper.className = "lab-sigkelly-wrap";

  // 顶部说明 - 可折叠 details (lab.sigkelly 文案长~3000字, 折叠避免占屏; summary首句摘要, body分段完整)
  {
    const _pnText = PURPOSE_NOTES["lab.sigkelly"];
    if (_pnText) {
      const _pnParts = _pnText.split("\n\n");
      const _pnSummary = _pnParts[0] || _pnText;
      const _pnBody = _pnParts.map((p) => "<p>" + p + "</p>").join("");
      const _pnEl = document.createElement("details");
      _pnEl.className = "purpose-note purpose-note-collapse lab-sm";
      _pnEl.innerHTML = '<summary class="purpose-note-summary">' + _pnSummary + '</summary>' +
                        '<div class="purpose-note-body">' + _pnBody + '</div>';
      wrapper.appendChild(_pnEl);
    }
  }

  // 周期切换 + 参数条
  const bar = document.createElement("div");
  bar.className = "lab-sigkelly-bar";
  wrapper.appendChild(bar);

  // AI报告折叠区(静态AI报告, 不依赖周期/费率, 放wrapper层避免随_renderSigKellyQuadrants重渲染重置open状态)
  // 2026-08-12 升级: 3AI新版(默认) / 双AI历史 双模式切换(localStorage 记忆 lab_sigkelly_ai_mode)
  //   3AI模式= 3ai-comparison(3AI结论对比) + comprehensive + deepseek + claude-v4(Claude第三角色)
  //   双AI模式= comparison(双AI对比) + comprehensive + deepseek(历史版, 保留不动)
  //   内容来自 KELLY_REVIEW_NOTES 静态 HTML 字符串, 切换只控制渲染哪些块, 不改内容
  if (typeof KELLY_REVIEW_NOTES !== 'undefined' && KELLY_REVIEW_NOTES) {
    var _aiReviewsDual = [
      { key: 'comparison', title: '双AI对比', hint: 'Claude vs DeepSeek 结论差异对比(核心, 历史版)' },
      { key: 'comprehensive', title: '主控综合结论', hint: 'Claude 4部分:评价/推荐/改造/降亏过滤' },
      { key: 'deepseek', title: 'DeepSeek独立分析', hint: 'DeepSeek 6章节独立分析' },
    ];
    var _aiReviews3ai = [
      { key: '3ai-comparison', title: '3AI 结论对比', hint: '主控综合 vs DeepSeek vs Claude第三角色(含6→9模式数据换代迁移, 新版)' },
      { key: 'comprehensive', title: '主控综合结论', hint: 'Claude 4部分:评价/推荐/改造/降亏过滤' },
      { key: 'deepseek', title: 'DeepSeek独立分析', hint: 'DeepSeek 6章节独立分析' },
      { key: 'claude-v4', title: 'Claude第三角色独立分析', hint: 'Claude(deepseek-v4-flash) 基于新版9模式数据的独立分析' },
    ];
    var _aiMode = '3ai';
    try {
      var _aiModeSaved = localStorage.getItem('lab_sigkelly_ai_mode');
      if (_aiModeSaved === 'dual' || _aiModeSaved === '3ai') _aiMode = _aiModeSaved;
    } catch (e) {}
    var _aiBuildReviews = function(mode) {
      var list = mode === 'dual' ? _aiReviewsDual : _aiReviews3ai;
      // 单一根容器 lab-sigkelly-ai-wrap(2026-08-12 fix): 切换条 + 报告块必须同在一个根下,
      //   初始渲染/切换渲染都取 firstElementChild=wrap, 否则只取到切换条、报告块被丢弃(3AI改造回退 bug)。
      //   切换条(.lab-sigkelly-ai-switch)在上, 报告块(.lab-sigkelly-ai-review)在下。
      // 2026-08-14 用户定: AI报告结论已过时,整区移页面尾部作历史留存,加归档标注(.lab-sigkelly-ai-archive-title)
      var html = '<div class="lab-sigkelly-ai-wrap lab-sigkelly-ai-archive">' +
        '<div class="lab-sigkelly-ai-archive-title">📦 历史 AI 报告存档（结论已过时 · 2026-08-14 起移页尾 · 仅供回溯）</div>' +
        '<div class="lab-sigkelly-ai-switch">' +
        '<span class="lab-sigkelly-ai-switch-label">AI 报告版本:</span>' +
        '<button type="button" class="lab-sigkelly-ai-switch-btn' + (mode === '3ai' ? ' active' : '') + '" data-mode="3ai">3AI 新版</button>' +
        '<button type="button" class="lab-sigkelly-ai-switch-btn' + (mode === 'dual' ? ' active' : '') + '" data-mode="dual">双AI 历史</button>' +
        '</div>' +
        '<div class="lab-sigkelly-ai-review">';
      for (var i = 0; i < list.length; i++) {
        var r = list[i];
        var _aiContent = KELLY_REVIEW_NOTES[r.key] || '';
        if (!_aiContent) continue;
        html += '<details class="lab-sigkelly-review">';
        html += '<summary class="lab-sigkelly-review-summary">' + r.title +
                ' <span class="lab-sigkelly-review-hint">' + r.hint + '</span></summary>';
        html += '<div class="lab-sigkelly-review-body">' + _aiContent + '</div>';
        html += '</details>';
      }
      html += '</div>';
      html += '</div>'; // close lab-sigkelly-ai-wrap
      return html;
    };
    var _aiBindSwitch = function(container) {
      var _aiBtns = container.querySelectorAll('.lab-sigkelly-ai-switch-btn');
      for (var j = 0; j < _aiBtns.length; j++) {
        _aiBtns[j].onclick = function() {
          var m = this.getAttribute('data-mode');
          try { localStorage.setItem('lab_sigkelly_ai_mode', m); } catch (e) {}
          var _aiTmp = document.createElement('div');
          _aiTmp.innerHTML = _aiBuildReviews(m);
          var _aiNewWrap = _aiTmp.firstElementChild;
          container.parentNode.replaceChild(_aiNewWrap, container);
          _aiBindSwitch(_aiNewWrap);
        };
      }
    };
    var _aiDiv = document.createElement('div');
    _aiDiv.innerHTML = _aiBuildReviews(_aiMode);
    var _aiWrap = _aiDiv.firstElementChild;
    // 2026-08-14 用户定: AI报告区从 wrapper 中部移到页面尾部(host 之后)作历史留存,先暂存这里,最后 append
    var _aiWrapPending = _aiWrap || null;
  }

  // 内容 host(2026-08-28 骨架屏: 3 行 + 3 表格行, 复用 .lab-kelly-skeleton CSS)
  const host = document.createElement("div");
  host.className = "lab-sigkelly-host";
  host.innerHTML = '<div class="lab-kelly-skeleton">' +
    '<div class="lab-kelly-skeleton-row"><div class="lab-kelly-skeleton-circle"></div><div class="lab-kelly-skeleton-line lab-kelly-skeleton-text wide"></div></div>' +
    '<div class="lab-kelly-skeleton-row"><div class="lab-kelly-skeleton-circle"></div><div class="lab-kelly-skeleton-line lab-kelly-skeleton-text"></div><div class="lab-kelly-skeleton-line lab-kelly-skeleton-text narrow"></div></div>' +
    '<div class="lab-kelly-skeleton-row"><div class="lab-kelly-skeleton-circle"></div><div class="lab-kelly-skeleton-line lab-kelly-skeleton-text"></div></div>' +
    '<div style="margin-top:18px">' +
      Array.from({length: 5}).map(() => '<div class="lab-kelly-skeleton-table-row">' +
        '<div class="lab-kelly-skeleton-cell" style="width:60px"></div>' +
        '<div class="lab-kelly-skeleton-cell" style="width:90px"></div>' +
        '<div class="lab-kelly-skeleton-cell" style="width:80px"></div>' +
        '<div class="lab-kelly-skeleton-cell" style="width:120px"></div>' +
        '<div class="lab-kelly-skeleton-cell" style="width:70px"></div>' +
        '</div>').join('') +
    '</div>' +
    '</div>';
  wrapper.appendChild(host);
  // 2026-08-14 用户定: AI报告区(历史留存)append 到页面尾部(host 即所有数据表格/图表之后, 页面最底)
  if (_aiWrapPending) {
    wrapper.appendChild(_aiWrapPending);
    _aiBindSwitch(_aiWrapPending);
  }

  content.querySelectorAll(".lab-sigkelly-wrap").forEach((el) => el.remove());
  content.appendChild(wrapper);

  // fetch 数据(缓存到 state, 周期切换不重新 fetch)
  if (!state.labSigKellyData) {
    const v = _labCustomCacheBust();
    const url = `./data/signal_kelly_backtest.json?v=${v}`;
    try {
      state.labSigKellyData = await fetchJSON(url);
    } catch (e) {
      host.innerHTML = `<div class="lab-custom-error"><div class="lab-custom-error-title">⚠️ 数据加载失败</div><div class="lab-custom-error-detail">${e.message || e}</div><div class="lab-custom-error-hint">signal_kelly_backtest.json 不存在或网络异常。后端生成后自动恢复(每日收盘后更新)。</div><button type="button" class="lab-custom-retry">重试</button></div>`;
      host.querySelector(".lab-custom-retry").onclick = () => { state.labSigKellyData = null; renderSigKellyLab(); };
      return;
    }
  }
  // T1(2026-08-23) 并行预取降亏特征 JSON(20 新键谓词查值用); 失败容忍(null→特征键不拦, 与后端同语义), 不阻塞主数据。
  //   晚到补渲染: 首渲时特征未就绪而新键已开启(判定被降级) → 加载完成后补一次渲染对齐 §22 一致性。
  //   【P0 卡死根修 2026-08-23】旧实现补渲 .then 无「进入时是否已就绪」判断——特征 JSON 就绪后
  //   每次 renderSigKellyLab 调用的 _kellyEnsureLossFeatData 都立即 resolve, 只要 filters 含任一新键
  //   (new14/new18/a9/b9/c9 或手动勾新键, 含 tds_kelly_fade_mode 记忆刷新/冷启动特征在途切模式两条路径)
  //   就再调 renderSigKellyLab → 无限自递归(与 sim 弹窗 P0 同款; playwright 实测 R1/R2 探针第 2 点起全 F
  //   彻底冻结, 且每轮全量重建 DOM=用户报的「内存占用异常」同源)。修=①只在首渲发生于就绪前才挂补渲
  //   (就绪后调用零挂载, 环消失) ②就绪跃迁补渲至多一次(state.kellyLossFeatReadyApplied 单向阀)双保险。
  if (state.kellyLossFeatData === undefined) {
    // undefined=尚未完成(进行中/未开始); null=已失败(容忍不补, 降级语义不变); 对象=已就绪
    // 【P0 卡死根修 2026-08-24】补渲动作改调 _kellyOnFilterChange(), 禁止 renderSigKellyLab() 整区重建。
    //   根因链: 首渲(host_A)挂本 then → L8770 _kellyOnFeeChange 启动初始重算(busy=true, await trades.json 慢)
    //   → 特征 JSON 先到触发本回调 → 若整区重建会新建 host_B 替换 host_A; 而 busy/pending 合批只认首次绑定
    //   的 host/onDone(_kellyRunRecompute busy 中再进只置 pending), 初始重算收尾把结果写回闭包捕获的 host_A
    //   (已被替换出 DOM 的死节点) → 页面在册的 host_B 永远停留「⏳ 计算中…」(v1.1.5 NEW14 默认必现)。
    //   _kellyOnFilterChange() 入口实时查当前在册 host + busy 中自动 pending 合批 + 不重建 DOM,
    //   特征就绪后经 _kellyApplyFeeRecompute 最新 filters 快照重算(新键谓词即时生效)→ onDone 就地刷新表格,
    //   与整区重建最终渲染一致但无死节点/无重建开销(features 极快时旧实现阀白烧+补渲丢失问题一并消除)。
    _kellyEnsureLossFeatData().then((d) => {
      if (!d) return;
      if (state.kellyLossFeatReadyApplied) return; // 单向阀: 就绪跃迁补渲至多一次
      state.kellyLossFeatReadyApplied = true;
      if (state.labSigKellyFilters && _KELLY_LOSS_NEW_KEYS.some((p) => state.labSigKellyFilters[p[0]])) {
        _kellyOnFilterChange({ keepS06: true }); // 特征就绪非成员改动: 保持 s06 动态态(codex-task-20260825-001)
      }
    });
  }
  const data = state.labSigKellyData;
  if (!data || !data.quadrants) {
    host.innerHTML = `<div class="lab-custom-error"><div class="lab-custom-error-title">⚠️ 数据为空或结构异常</div><button type="button" class="lab-custom-retry">重试</button></div>`;
    host.querySelector(".lab-custom-retry").onclick = () => { state.labSigKellyData = null; renderSigKellyLab(); };
    return;
  }

  // 默认周期 y1(对比矩阵已移除,卡片视图常驻,主表+进阶表合并为一张宽表)
  if (!state.labSigKellyPeriod) state.labSigKellyPeriod = "y1";
  const period = state.labSigKellyPeriod;
  // 初始化费率客调state(默认ETF主流档=万0.5最低0.1, 2026-08-14 用户改默认: ETF主流; 渲染数据随费率档联动重算 → 按ETF主流口径渲染 §22)
  if (!state.labSigKellyFeePreset) {
    state.labSigKellyFeePreset = "etf_main";
    state.labSigKellyFeeParams = { commission_rate: 0.00005, min_commission: 0.1, slippage: 0.001, transfer_fee_rate_sh: 0.00001, stamp_duty_rate: 0 };
  }
  // 降亏过滤toggle state(AI宏默认已开启: positionCap+追关注×熊市+J1/J2(1月调整)+n2(11月+追关注+行业), 2026-08-12用户拍板"替换默认(AI宏=新默认)", 见 _kellyDefaultFilters)
  // 注意: labSigKellyFilters 仅内存态(每次页面加载都从 _kellyDefaultFilters AI宏 重建, 不读写 localStorage)——
  // 不存在"老用户localStorage旧filters", AI宏默认每次加载即生效。真正与 localStorage 共享的只有 positionCap/K(tds_poscap, 见下, 与 app.js 首页联动)。
  // 2026-08-12 补齐缺失字段: 若 AI宏 默认集后续新增字段, 已存在的 filters 对象缺新字段时用默认值补齐(防御性覆盖结构变更),
  // 而非整体重置——已存在字段保持原值。
  if (!state.labSigKellyFilters) {
    state.labSigKellyFilters = _kellyDefaultFilters();
  } else {
    var _kellyDft = _kellyDefaultFilters();
    for (var _kf in _kellyDft) {
      if (!Object.prototype.hasOwnProperty.call(state.labSigKellyFilters, _kf)) state.labSigKellyFilters[_kf] = _kellyDft[_kf];
    }
  }
  // 2026-08-13 降亏状态持久化(新key tds_kelly_filters): 读取覆盖 AI宏默认档成员键(v1.1.4 及以前=8成员基础5+核心3含K2C5; v1.1.5 起=NEW14 十四键), 其余细标志仍按默认重建
  // 首页 AI 开关与凯利区共享此状态(§22 一致性); 首次访问无该 key → 走默认(AI宏全开)不写
  try {
    var _savedKF = JSON.parse(localStorage.getItem("tds_kelly_filters") || "null");
    if (_savedKF && _savedKF.members) {
      for (var _kmi = 0; _kmi < _kellyPersistMemberKeys.length; _kmi++) {
        var _kmk = _kellyPersistMemberKeys[_kmi];
        if (typeof _savedKF.members[_kmk] === "boolean") state.labSigKellyFilters[_kmk] = _savedKF.members[_kmk];
      }
    }
  } catch (e) {}

  // T3-1(2026-08-23): AI降亏模式持久化(lab 独立 key tds_kelly_fade_mode, TTL 18 小时滑动过期,
  // 常量单源 common.js _TDS_FADE_TTL_MS): 在 tds_kelly_filters
  // 默认档成员键覆盖之后应用(v1.1.5 起=NEW14 十四键), 完整模式组合覆盖成员级状态(模式=57键全集, 成员键只是子集); 无 key/超时/旧格式
  // (用户从未选过或距上次切换>18h)=跳过=回当前默认基座 s06 动态(v1.1.7 起)(2026-08-23 用户拍板: 不做永久记忆, 阉割版只留
  // 18 小时防刷新闪回且覆盖隔夜; 工具函数 _tdsLoadWithTTL 单源在 common.js, T3-2 同款记忆直接复用)
  // (v1.1.5 起默认基座=NEW14 十四键; v1.1.4 及以前=8键 p8 现对照档)。sim 弹窗记忆已独立(tds_sim_fade_mode, 2026-08-23 hotfix,
  // 同走 TTL 工具), 与本 key/首页/AI监控卡互不干预——旧「弹窗每次打开=关+8键」约定已废止。
  try {
    var _savedFM = (typeof _tdsLoadWithTTL === "function")
      ? _tdsLoadWithTTL("tds_kelly_fade_mode", typeof _TDS_FADE_TTL_MS !== "undefined" ? _TDS_FADE_TTL_MS : 18 * 3600 * 1000)
      : JSON.parse(localStorage.getItem("tds_kelly_fade_mode") || "null"); // 兜底: common 未加载时不至于崩(common 先于 lab 载入, 正常不走这)
    // v1.1.5(2026-08-24): 记忆有效=apply 所选模式; 无记忆/超时/旧格式 → apply 默认模式 new14(NEW 14键)。
    //   这一步必须在 tds_kelly_filters 成员覆盖之后——老用户的 tds_kelly_filters.members 是八键(v1.1.4 前),
    //   若不在此处用默认模式覆盖, 老用户冷启动会滞留八键、默认切换不生效(§22 一致性)。
    var _dftModeId = (typeof window._KELLY_FADE_DEFAULT_MODE === "string") ? window._KELLY_FADE_DEFAULT_MODE : "new14";
    // v1.1.8 fix(codex-s06-fademode-001): 老默认 new14 的 localStorage 记忆强制回新默认 S06，
    // 防 v1.1.5~v1.1.6 用户浏览器残留 tds_kelly_fade_mode={mode:'new14'} 覆盖新默认。
    var _applyMid = (_savedFM && _savedFM.mode && typeof _tdsFadeModeById === "function" && _tdsFadeModeById(_savedFM.mode) && _savedFM.mode !== "new14") ? _savedFM.mode : _dftModeId;
    if (typeof _tdsFadeModeById === "function" && _tdsFadeModeById(_applyMid)) {
      // S06(codex-task-20260825-001): dynamic 预设无静态 keys, Apply 返回 false 不改标签区 → 显式恢复
      // 默认档作静态参考底座(判定层 per-date 接管), 与下拉选中 s06 路径同一处理(§22 冷启动/热切换一致)
      if (!_tdsFadeModeApply(_applyMid, state.labSigKellyFilters) && _applyMid !== _dftModeId) {
        _tdsFadeModeApply(_dftModeId, state.labSigKellyFilters);
      }
      state.labSigKellyFadeModeBase = _applyMid;
    }
  } catch (e) {}
  // (2026-08-22 用户拍板) 新降亏键 bullAuxBackupStop: lab 凯利区独立开关, UI 态不落盘(state-only,
  // 与 cyb/specialbearcyb 等默认关实验键同模式), 不写 tds_kelly_filters 固定成员结构; 刷新页面回默认关
  // (2026-08-22 二次变更) 各处独立: 本开关只管 lab 凯利区, 与首页 AI 建议/模拟回测弹窗互不影响
  // 金额口径=每日资金池等分+top-K(2026-08-13 恢复, 每笔=10000/当日保留数, K档最大持仓恒定); positionCap 开关/K 与交易页共享localStorage
  var _sharedPC = _kellySharedPosCap();
  // 2026-08-12 默认开启 positionCap(用户:默认最优组合要开启): 首次访问(无 tds_poscap)写入默认{on:true,k:3}(2026-08-13 K默认3), 与 app.js 首页联动一致(§22)
  if (!localStorage.getItem("tds_poscap")) _kellySetSharedPosCap(true, 1); // 默认 K=1 主推(2026-08-14 #BC)
  state.labSigKellyFilters.positionCap = !!(_sharedPC && _sharedPC.on);
  state.labSigKellyFilters.positionCapK = (_sharedPC && _sharedPC.k) || 3;
  // #49 ai长线模式(G/H/I)仓位管理: 开关写共享键(localStorage tds_gihpos, 默认关; 只影响实验室 G/H/I 卡片, 首页默认关闭不展示 §22)
  state.labSigKellyGihOn = _kellySharedGih().on;

  _renderSigKellyBar(bar, data, period);
  _renderSigKellyQuadrants(host, data, period);
  // 触发初始重算(加载trades.json获取费率消耗列)
  _kellyOnFeeChange(state.labSigKellyFeePreset);
}

// 从 state.labSigKellyData.config.sell_modes 动态获取卖出模式标签(去硬编码 ABCD)
function _sigKellyModeLabels() {
  const sm = (state.labSigKellyData && state.labSigKellyData.config && state.labSigKellyData.config.sell_modes) || {};
  const labels = {};
  Object.keys(sm).forEach((k) => { labels[k] = _sigKellyModeLabelWith(k, sm[k] ? sm[k].label : k); });
  return labels;
}
// 2026-08-14 追加需求(用户拍板, 与 #48 一起): 模式时段标注 A-F=短线 / G/H/I=中长线, 全站模式名展示统一(§22 / §23.3)
// 供 _sigKellyModeLabels / modeStr / 三玩法 modes 数组 / 交易弹窗 modeLabel 共用单一事实来源, 避免各点格式不一
function _sigKellyModeSpanKey(modeKey) {
  if (modeKey === "G" || modeKey === "H" || modeKey === "I") return "中长线";
  return "短线"; // A/B/C/D/E/F/J
}
function _sigKellyModeLabelWith(modeKey, label) {
  const span = _sigKellyModeSpanKey(modeKey);
  // 已有 短/中长/长 线 字样则不重复追加(如 A/F 原 label 含"短线", G 含"长线"——统一归一为 短线/中长线)
  if (/中长线|短线|长线/.test(label || "")) {
    if (span === "中长线" && label.indexOf("长线") >= 0 && label.indexOf("中长线") < 0) {
      return (label || "").replace("长线", "中长线");
    }
    return label || modeKey;
  }
  return (label || modeKey) + "·" + span;
}

// 从 state.labSigKellyData.config.sell_modes 动态获取卖出模式列表(去硬编码 ABCD)
function _sigKellyModeKeys() {
  const sm = (state.labSigKellyData && state.labSigKellyData.config && state.labSigKellyData.config.sell_modes) || {};
  return Object.keys(sm);
}

// 周期切换条 + 回测参数展示 + 费率客调控件(6档预设+自定义5参数+快捷键0-4+C)
// ===== 组合降亏「预设宏」(2026-08-11 用户定: 1+2+3全要,按需选择,组合可叠加=成员并集OR) =====
// 组合=一组成员toggle的命名打包,点击组合→勾选/取消其全部成员toggle;过滤仍走成员toggle各自谓词并集(_kellyPassesFadeFilters零改动)
// 天然幂等(并集OR语义,成员重叠不重复过滤)+单一事实来源(state.labSigKellyFilters只有成员开关,组合勾选态是派生的)→满足§22数据一致性
// 成员/组合指标均为部署9模式数据(round3-verify 2026-08-11; 5月系管理/年初+周中数据不支持未实施)
var _kellyComboPresets = {
  // 年末季节 = n2+n3+v4d (并集standalone 6.50/+29万, 4窗口全>2最稳健, maxSh0.35, wf两段>2)
  yearEnd: {
    label: "年末季节",
    tip: "组合「年末季节」(n2+n3+v4d): 一键勾选这3个成员。经济逻辑=年末止损潮,历史最稳健组合(并集4窗口全>2)。⚠n2 在 v1.1.4 及以前曾是默认键、v1.1.5 起 NEW14 基座已移出(可手动开), 现再勾本组合会新增 n2+n3+v4d 三键过滤(老口径对照: 边际≈0(-0.9万,微负无增益))——非默认推荐,可选分析。1:1例: 单独跑它=并集比值6.50(4窗口 y1 14.33/y3 9.72/y10 7.14/all 6.50 全>2)、+29万,最稳;但叠在新默认 NEW14 上再勾,净利几乎不变→想加稳健可勾、想冲收益可跳过【核实源:kelly-combo-round3-verify.md】。",
    members: [
      { k: "n2NovSpecialIndustry", cls: "lab-sigkelly-toggle-n2" },
      { k: "n3NovSpecialMon", cls: "lab-sigkelly-toggle-n3" },
      { k: "v4d", cls: "lab-sigkelly-toggle-v4d" }
    ]
  },
  // 稳健核心 = 仅r8 (5.95/+30.8万; v4c/v4b部署数据净负已剔除勿含)
  stableCore: {
    label: "稳健核心",
    tip: "组合「稳健核心」(仅r8): 一键勾选纯非五月3稳定组件R8。2021-2026连续6年全正,完全避开5月shift争议,损盈最低之一。注:r8≡n1∪n2∪n3恒等;v4c/v4b部署净负已剔除不在此组合。可选分析非默认推荐。1:1例: 单勾它=年化5.95、净+30.8万,2021-2026每年都正→想要「年年不亏」选它;vs「最大化降亏」(greedy15)是A/F短线收益率唯一大增来源(去之暴跌19-26pt)但G模式建议别勾→先想清楚你在用哪种玩法【核实源:kelly-combo-round3-verify.md】。",
    members: [
      { k: "r8PureNonMay", cls: "lab-sigkelly-toggle-r8" }
    ]
  },
  // 最大化降亏 = greedy15 (2026-08-13 穷举v2 已并入 AI宏 默认3元: A/F 收益率唯一大增来源; standalone 1.90<2标注风险)
  maxLossCut: {
    label: "最大化降亏",
    tip: "组合「最大化降亏」(greedy15): ⚠greedy15 已在 AI降亏过滤 默认内(NEW14 hist6 成员之一, v1.1.5 起), 本组合成员与默认完全重复, 无需再勾——勾 AI降亏过滤 即已含 greedy15(勾选幂等无害)。价值=A/F(短持)收益率唯一大增来源(去之暴跌19-26pt);但用G模式(推荐卖出法)建议去掉。勿单开对照口径(每日池比值1.28<2)。1:1例: 你跑A/F短线,开它收益率能高19-26个百分点(核心价值),默认已含不用手动勾;但你是G长线玩法就别关/别管它,G靠21-100天长持利润引擎、不靠砍量提收益率【核实源:kelly-combo-round3-verify.md】。",
    members: [
      { k: "greedy15", cls: "lab-sigkelly-toggle-greedy15" }
    ]
  },
  // 1月调整 = janMidRating(1月中旬+中评级) + janMidSpecial(1月中旬+追关注) (2026-08-11 元素级重组挖掘)
  // 只做1月中旬(11-20日): 1月上旬=盈利口袋(全负-56万)不可动; 两成员重叠~96%(mid⊂special), 偏好surgical开1月中旬+中评级, 偏好覆盖开1月中旬+追关注
  janAdjust: {
    label: "1月调整",
    tip: "组合「1月调整」(1月中旬+中评级 + 1月中旬+追关注): 一键勾选2个1月保护键。1月上旬=盈利口袋(全负-56万)不可动,只做1月中旬。⚠两键带监控(maxSh0.62/0.79,2026单年主导),每年1月后检查1月中旬子集是否转盈。两键均已并入AI降亏过滤默认,勾选幂等无害。1:1例: 每年1月11-20日这批信号,过去整体是亏损区(1月上旬-56万),勾它=只对1月中旬的中评级/追关注信号做降亏剔除、不动1月上旬盈利段→年初想躲1月坑可勾,但2026单年主导需每年1月后回查【核实源:kelly-combo-element-mining.md】。",
    members: [
      { k: "janMidRating", cls: "lab-sigkelly-toggle-janmidrating" },
      { k: "janMidSpecial", cls: "lab-sigkelly-toggle-janmidspecial" }
    ]
  }
};

// 刷新组合checkbox三态(派生: 全成员勾选=active, 部分=indeterminate半选, 无=空); 成员toggle/组合改动后调用
// 2026-08-13 融合: 组合宏改为顶部快捷按钮(不再 checkbox), 三态改 class 表达(active=全选/semi=半选), 与事件绑定解耦
function _kellyRefreshComboStates(bar) {
  var filters = state.labSigKellyFilters || _kellyDefaultFilters();
  for (var ck in _kellyComboPresets) {
    var cb = bar.querySelector(".lab-sigkelly-toggle-combo-" + ck);
    if (!cb) continue;
    var members = _kellyComboPresets[ck].members;
    var allOn = true, anyOn = false;
    for (var i = 0; i < members.length; i++) {
      if (filters[members[i].k]) anyOn = true; else allOn = false;
    }
    if (cb.classList) {
      cb.classList.toggle("active", allOn);
      cb.classList.toggle("semi", !allOn && anyOn);
    }
  }
}

// v1.1.0(2026-08-15) 曾=AI宏 8 成员(基础5+核心3); v1.1.5(2026-08-24 用户拍板) 默认基座切 NEW14 →
// 联动/三态/持久化成员集同步扩为 NEW14 十四键(hist 键 6 + 规则键 8, 与 common.js new14 预设逐位一致)。
// 总开关语义随默认推荐走: 全勾=NEW14 全开(⭐ 推荐), 部分=偏离新默认(半选), 无=全关。
// tds_kelly_filters.members 结构兼容: 老数据只存 8 键字段, 读取循环按 typeof boolean 判定缺字段自动跳过。
// +1类回测剔除(债类/波段不入宇宙 _bt_in_universe)不变 = 回测层剔除与键组正交。
var _kellyPersistMemberKeys = [
  // hist 键 6
  "r10May6NonMay", "greedy15", "janMidSpecial", "k2c5HkChase", "k3ConceptBuy", "declinePhaseSpecial",
  // 规则键 8(N1/T1/D1/Q1/H1/M1/P1/R2b, 生产键名单源 scripts/loss_rules.py MINING_TO_PROD_KEY)
  "n1NorthOutflow", "t1LowTurnSpecial", "d1LowDivYield", "q1QvixLowPct",
  "h1VolChgHighA", "m1MarginDownBull", "p1LowDivBackup", "r2bSpecialGlobal"
];
var _kellyAiMacroMemberCls = {
  r10May6NonMay: "lab-sigkelly-toggle-r10",
  greedy15: "lab-sigkelly-toggle-greedy15",
  janMidSpecial: "lab-sigkelly-toggle-janmidspecial",
  k2c5HkChase: "lab-sigkelly-toggle-k2c5",
  k3ConceptBuy: "lab-sigkelly-toggle-k3",
  declinePhaseSpecial: "lab-sigkelly-toggle-decline",
  n1NorthOutflow: "lab-sigkelly-toggle-n1out",
  t1LowTurnSpecial: "lab-sigkelly-toggle-t1turn",
  d1LowDivYield: "lab-sigkelly-toggle-d1div",
  q1QvixLowPct: "lab-sigkelly-toggle-q1qvix",
  h1VolChgHighA: "lab-sigkelly-toggle-h1volchg",
  m1MarginDownBull: "lab-sigkelly-toggle-m1margin",
  p1LowDivBackup: "lab-sigkelly-toggle-p1div",
  r2bSpecialGlobal: "lab-sigkelly-toggle-r2bglobal"
};
// AI宏降亏过滤「总开关」三态(#39 三级级联UI; #54 2026-08-13 bug1修复: 联动集合扩到 _kellyAiMacroMembers; v1.1.0(2026-08-15) 扩到 8成员含K2C5; v1.1.5(2026-08-24 用户拍板) 默认基座切 NEW14 → 联动集合=NEW14 十四键(hist6+规则8))
// 全成员勾选=checked, 部分=indeterminate半选, 无=空; 语义=「AI降亏过滤默认推荐(NEW14 十四键)」当前开合
var _kellyAiMacroMembers = _kellyPersistMemberKeys.map(function (k) { return { k: k, cls: _kellyAiMacroMemberCls[k] }; });
// 写降亏状态到 localStorage tds_kelly_filters: { aiMacro(NEW14 十四键全开=勾选态; v1.1.4 及以前为 8键), members(当前默认档成员键), combos(当前全开组合keys, 派生辅助) }
// 只在用户改动 toggle 时经 _kellyOnFilterChange 调用; 读取在 renderSigKellyLab 合并默认后覆盖
function _kellyPersistFilters() {
  try {
    var f = state.labSigKellyFilters;
    if (!f) return;
    var saved = { aiMacro: false, members: {}, combos: [] };
    var allMembers = true;
    for (var i = 0; i < _kellyAiMacroMembers.length; i++) { if (!f[_kellyAiMacroMembers[i].k]) allMembers = false; }
    saved.aiMacro = allMembers;
    for (var j = 0; j < _kellyPersistMemberKeys.length; j++) {
      var pk = _kellyPersistMemberKeys[j];
      saved.members[pk] = !!f[pk];
    }
    for (var ck in _kellyComboPresets) {
      var members = _kellyComboPresets[ck].members;
      var allOn = true;
      for (var m = 0; m < members.length; m++) { if (!f[members[m].k]) { allOn = false; break; } }
      if (allOn) saved.combos.push(ck);
    }
    localStorage.setItem("tds_kelly_filters", JSON.stringify(saved));
  } catch (e) {}
}
function _kellyRefreshAiMacroState(bar) {
  var cb = bar.querySelector(".lab-sigkelly-toggle-aimacro");
  if (!cb) return;
  var filters = state.labSigKellyFilters || _kellyDefaultFilters();
  var allOn = true, anyOn = false;
  for (var i = 0; i < _kellyAiMacroMembers.length; i++) {
    if (filters[_kellyAiMacroMembers[i].k]) anyOn = true; else allOn = false;
  }
  cb.checked = allOn;
  cb.indeterminate = !allOn && anyOn;
}
// #54 2026-08-13 ⭐badge 同步: 默认推荐徽标反映实际勾选态(rec=true 但当前 off → 降级"已关/部分"暗显, 与 checkbox 同步; 语义=默认推荐集成员)
function _kellyRecBadge(on) {
  return on
    ? '<span class="lab-sigkelly-rec-badge">⭐ 推荐</span>'
    : '<span class="lab-sigkelly-rec-badge lab-sigkelly-rec-badge-off">⭐ 推荐·已关</span>';
}
function _kellyRecBadgeState(allOn, anyOn) {
  if (allOn) return '<span class="lab-sigkelly-rec-badge">⭐ 推荐</span>';
  return anyOn
    ? '<span class="lab-sigkelly-rec-badge lab-sigkelly-rec-badge-off">⭐ 推荐·部分</span>'
    : '<span class="lab-sigkelly-rec-badge lab-sigkelly-rec-badge-off">⭐ 推荐·已关</span>';
}
// ===== v1.1.5 枯竭提示 chip(纯展示层, 凯利区信号区): 复用 common.js 单源(_tdsFetchRecentBlock/_tdsComputeDrought/_tdsDroughtChipHtml) =====
// 数据源=overfit_monitor.json recent 块(T3-2 已有产物, 零新增后端任务); 口径=买入类×已入样×未命中当前生效过滤键集;
// N≥20 才显示; 计算失败/数据缺失=静默隐藏(优雅降级); 与首页 AI 建议区 chip 同源同数字(§22 一致性)。
function _kellyMountDroughtChip(bar) {
  if (!bar || typeof window._tdsComputeDrought !== "function") return;
  // modeKeys=当前实际生效的全部过滤键(用户手动改开关后 chip 实时跟随, 与凯利区「最后结果」一致 §22)
  var filters = state.labSigKellyFilters || {};
  // S06(reviewer P2 F1, codex-task-20260825-001): dynamic 预设无静态 keys → 标签区参考底座键集≠实际生效键集,
  // 改 per-date 当日基座键集(与凯利区判定链同源 §22); 快照不可用的日期返回 [](该日视为无键=不拦, fail-open 同语义)。
  // 非 S06 态维持原标签键集派生(默认档行为零变化)。
  var _mp = (typeof _tdsFadeModeById === "function") ? _tdsFadeModeById(state.labSigKellyFadeModeBase) : null;
  var _isS06 = !!(_mp && _mp.dynamic);
  var modeKeys = _isS06
    ? function (d) { if (typeof window._tdsS06KeysForDate !== "function") return []; var ks = window._tdsS06KeysForDate(d); return Array.isArray(ks) ? ks : []; }
    : Object.keys(filters).filter(function (k) { return filters[k] && k !== "positionCap"; });
  window._tdsFetchRecentBlock(typeof fetchJSON === "function" ? fetchJSON : null).then(function (recent) {
    // then 内重查 DOM(bar 可能已被重渲染替换, 不用闭包旧引用防写入丢失)
    var slot = bar.querySelector("#lab-kelly-sig-drought-slot");
    if (!slot) return;
    var info = window._tdsComputeDrought(recent, modeKeys);
    // S06 口径尾注(§21 诚实公示): 默认档不传第二参=用 common.js 内置 NEW14 默认口径(与改前逐字一致);
    // s06 态传动态口径说明(文案单源 common.js _tdsS06CaliberNote, 与首页 chip 同一句 §22)
    var html = window._tdsDroughtChipHtml ? window._tdsDroughtChipHtml(info, (_isS06 && typeof window._tdsS06CaliberNote === "function") ? window._tdsS06CaliberNote() : undefined) : "";
    slot.innerHTML = html;
    slot.style.display = html ? "" : "none";
  });
}

// ===== 降亏过滤 31 toggle 单一事实来源(2026-08-13 融合优化 #39): 渲染/排序/badge/联动全部从本数组派生, 根治"名称/比值/tip 硬编码在 HTML 字符串"痛点 =====
// 字段: k=filter key / cls=checkbox class(事件绑定/组合宏成员复用, 勿改名) / name=白话名 / ratio=降亏比值(组内按此降序) /
//       rec=默认推荐(⭐ badge 由此派生, 根治"标了但实际不默认"复发) / linked=核心3键(受 AI宏 总开关联动) /
//       warn=监控/慎用标注(组内降序下虚高比值会置顶, 靠此防误导) / tip=完整说明(hover)
// 分组口径=2026-08-12 用户定 4 大经济逻辑分类(日历效应·季节调仓/复合并集·广谱管理/信号质量·弱信号/市场防御·大盘择时)
// 组间固定序(按组内默认推荐最高比值降序): 日历效应(6.63)>复合并集(4.18)>信号质量(2.52)>市场防御(2.31)
var _kellyFadeFlagGroups = [
  // ⚠ 2026-08-14 #48 重写: 全站 ratio 由 每笔1万(fixed) 重算为 每日资金池口径(基准=每日池空filter K1)
  //   数据源 docs/kelly/position/kelly-dailypool-exhaustive-rerun.md §7.2/§4 + /tmp/dailypool_rerun_ratio.py
  //   ~声明结构: advice=白话1句+ratio(默认即看, 渲染在label可见文本); tip=完整每日池口径细节(ⓘ hover 弹层)
  //   已剔除「净增收+XX万元」旧挖掘(fixed)主口径数字; rec=默认推荐(绿)/warn=⚠监控(黄)/⚠慎用(红), 联动色块
  //   G模式(K1)正边际参考: excludeSpecialBear(+19,712)>a45(+17,965)>a5(+10,819)>janMidSpecial(+3,602)>n6MidMay(+3,553)
  //   负边际最差(勿单开): greedy15(-169,836)>greedy10(-165,111)>greedy7(-126,328)>r10(-91,267)>excludeAuxCross(-49,796)
  { key: "calendar", title: "日历效应·季节调仓·ratio每日池口径", flags: [
    { k: "v4b", cls: "lab-sigkelly-toggle-v4b", name: "5月+追关注+关联指数", ratio: 999,
      advice: "5月系最稳,减亏又增盈 · 比值999", tip: "❌非默认: 排除A股+5月+追关注+关联指数。每日池比值999=减亏0.23%且盈利反升(损盈-0.02%),组合总亏损反降,效率最高。6年全正,maxSh0.37最低,n=210充足。5月系中最稳。" },
    { k: "n2NovSpecialIndustry", cls: "lab-sigkelly-toggle-n2", name: "11月+追关注+行业", ratio: 30.35, warn: "⭐曾默认·v1.1.5移出",
      advice: "追涨只在牛市做 · 比值30.35 · v1.1.5起非默认", tip: "⭐ 曾是默认推荐(v1.1.4 及以前), v1.1.5 起 NEW14 重构换基座后移出默认(可手动开, §23.7 不删档): 排除11月+追关注+行业指数交易(年底追高在行业轮动中被套)。每日池减亏0.42%/损盈0.01%/比值30.35。7/9年亏,近年(2023/2025)大亏回归。G模式K1正边际键。" },
    { k: "v4m", cls: "lab-sigkelly-toggle-v4m", name: "9月+周三+追关注", ratio: 5.39, warn: "⚠️监控",
      advice: "比例高但只3年数据,谨慎 · 比值5.39", tip: "❌非默认⚠监控: 排除9月+周三+追关注。每日池减亏0.86%/损盈0.16%/比值5.39。⚠只3年数据(2021/2024/2026),数据不足,每年检查9月表现。" },
    { k: "a45NovMidLateSpecial", cls: "lab-sigkelly-toggle-a45", name: "11月中下旬+追关注", ratio: 3.81,
      advice: "G模式补充键,11月追高主流 · 比值3.81", tip: "❌非默认(建议加): 排除11日及以后的11月追关注交易(覆盖11月80%特殊信号)。G模式K1正边际+17,965(+3.35pt),倒数第二强补键。每日池减亏3.89%/损盈1.02%/比值3.81。含11月下旬(2024+零交易,近年贡献来自中旬)。已不在默认组合(与specialBear+J1+J2+n2 75%重叠冗余)。" },
    { k: "janMidSpecial", cls: "lab-sigkelly-toggle-janmidspecial", name: "1月中旬+追关注", ratio: 2.95, rec: true, warn: "⚠️监控",
      advice: "1月保护键,覆盖广 · 比值2.95", tip: "⭐ 默认推荐(默认开启)⚠监控: 排除1月中旬(11-20日)追关注交易。每日池减亏1.23%/损盈0.42%/比值2.95。G模式K1正边际+3,602。⚠maxSh0.79(2026更主导),每年1月后检查1月中子集是否转盈。只做中旬:1月上旬=盈利口袋(全负-56万)不可动。" },
    { k: "a5NovMidSpecial", cls: "lab-sigkelly-toggle-a5", name: "11月中旬+追关注", ratio: 2.58,
      advice: "G模式补充键,11月中追高 · 比值2.58", tip: "❌非默认(建议加): 排除11月中旬(11-20日)追关注。G模式K1正边际+10,819(+2.56pt)。每日池减亏1.77%/损盈0.69%/比值2.58。2016-2025连续有交易最稳。A5为A45的子集,同时开A45时A5不再新增过滤。" },
    { k: "n3NovSpecialMon", cls: "lab-sigkelly-toggle-n3", name: "11月+追关注+周一", ratio: 1.75,
      advice: "不单开,周末消化追高易套 · 比值1.75", tip: "❌非默认: 排除11月+追关注+周一。每日池减亏1.09%/损盈0.62%/比值1.75。8/10年亏,n=474样本充足。周末消息面消化后的追涨易被套。" },
    { k: "v4d", cls: "lab-sigkelly-toggle-v4d", name: "12月+周二+辅+低分", ratio: 1.56,
      advice: "年末止损潮,样本少 · 比值1.56", tip: "❌非默认: 排除12月+周二+辅关注+低分。每日池减亏0.07%/损盈0.04%/比值1.56。5年全正(2020-2024),maxSh0.46。经济逻辑最强(年末止损潮)。n=102,近1年无数据。" },
    { k: "v4j", cls: "lab-sigkelly-toggle-v4j", name: "5月+超低价+追关注", ratio: 1.31,
      advice: "n5细化版,单开意义小 · 比值1.31", tip: "❌非默认: 排除5月+极低价+追关注。每日池减亏0.31%/损盈0.24%/比值1.31。是n5(5月+极低价)细化版,加追关注后maxSh从66%降到40%,过拟合风险显著降低。广谱效应被每日池摊薄。" },
    { k: "n1MarTueHigh", cls: "lab-sigkelly-toggle-n1", name: "3月+周三+高价", ratio: 1.26,
      advice: "全输钱,可作稳健补充 · 比值1.26", tip: "❌非默认: 排除3月+周三+高价ETF。每日池减亏0.18%/损盈0.14%/比值1.26。7/7年全亏(2017-2026),无单年主导,稳定性最强单标志。" },
    { k: "n5MayVlow", cls: "lab-sigkelly-toggle-n5", name: "5月+超低价", ratio: 0.86, warn: "⚠️监控",
      advice: "过拟合风险最高,慎用 · 比值0.86", tip: "❌非默认⚠监控: 排除5月+极低价ETF。每日池减亏0.76%/损盈0.88%/比值0.86。⚠2026年占全历史净影响66%,过拟合风险最高。每年6月监控5月表现,转盈则暂停。" },
    { k: "v4g", cls: "lab-sigkelly-toggle-v4g", name: "全球Q1+辅关注+低评", ratio: 0.78, warn: "⚠️监控",
      advice: "近年才转亏,观察再定 · 比值0.78", tip: "❌非默认⚠监控: 排除全球+Q1+辅关注+低评级。每日池减亏0.47%/损盈0.60%/比值0.78。⚠近年才转亏:2023-2024子集实际盈利,2025-2026才大亏,可能是市场结构变化。观察2年再决定。" },
    { k: "janMidRating", cls: "lab-sigkelly-toggle-janmidrating", name: "1月中旬+中评级", ratio: 0.50, warn: "⭐曾默认·v1.1.5移出",
      advice: "1月保护键,勿单看比值 · 比值0.50 · v1.1.5起非默认", tip: "⭐ 曾是默认推荐(v1.1.4 及以前)⚠监控, v1.1.5 起 NEW14 重构换基座后移出默认(可手动开): 排除1月中旬(11-20日)中评级1月交易。与J2(1月中旬+追关注)同为「1月组合保护键」,曾作默认组合一员协同,勿单看今日池比值0.50(单开无降亏价值)。⚠maxSh0.62略超0.60(2026单年主导),每年1月后检查1月中旬子集是否转盈。只做中旬:1月上旬不可动。" },
    { k: "n4AMay", cls: "lab-sigkelly-toggle-n4", name: "A股+5月", ratio: 0.39,
      advice: "5月系最稳但不亮眼 · 比值0.39", tip: "❌非默认: 排除A股指数+5月。每日池减亏0.35%/损盈0.89%/比值0.39。5月系中最稳(9/15年亏),2023-2026连亏4年。5月A股调整常态化。" },
    { k: "v4cSimple", cls: "lab-sigkelly-toggle-v4csimple", name: "3月+周三+辅关注", ratio: 0.25,
      advice: "稳定但对每日池鸡肋 · 比值0.25", tip: "❌非默认: 排除3月+周三+辅关注,去低分冗余。每日池减亏0.20%/损盈0.79%/比值0.25。4窗口极稳但广谱效应摊薄,效率大降。N1的信号维度变体,可叠加。" },
    { k: "n6MidMay", cls: "lab-sigkelly-toggle-n6", name: "5月+中评级", ratio: 0, warn: "⚠️监控",
      advice: "G模式正边际但值得复查 · 比值≈0", tip: "❌非默认⚠监控: 排除中评级+5月。每日池减亏损盈均微负比值≈0。G模式K1正边际+3,553,但⚠2026年占全历史净影响71%,过拟合风险最高。每年6月监控5月表现,转盈则暂停。" },
    { k: "v4i", cls: "lab-sigkelly-toggle-v4i", name: "5月+追关注+概念+周一", ratio: 0,
      advice: "广谱效应消失,勿单开 · 比值≈0", tip: "❌非默认: 排除追关注+5月+概念+周一。每日池比值≈0(无净减亏效应)。旧每笔1万比值27.04,每日池下广谱效应消失。maxSh0.57接近阈值。" },
    { k: "v4k", cls: "lab-sigkelly-toggle-v4k", name: "1月+主关注+高价", ratio: 0, warn: "⚠️监控",
      advice: "无净效应,稳定性不足 · 比值≈0", tip: "❌非默认⚠监控: 排除1月+主关注+高价。每日池比值≈0(无净效应)。旧每笔1万比值10.11,每日池下广谱效应消失。⚠有子集盈利年(2017/2025),3/5年净正非全正,稳定性不足。" },
    { k: "v4f", cls: "lab-sigkelly-toggle-v4f", name: "6月+周三+主关注+关联", ratio: -5.1, warn: "⚠️监控",
      advice: "转负最末位,样本太小 · 比值-5.1", tip: "❌非默认⚠监控: 排除6月+周三+主关注+关联。每日池比值-5.1(组合总盈亏转坏,最末位)。旧每笔1万比值999(JEP虚高),每日池下转负。⚠n=60太小只3年数据,每年6月检查。" },
    // T1(2026-08-23) 新键·日历族(R2 替补族): 月份主导(仅7-9月生效)归本组; 规格单源=scripts/loss_rules.py
    { k: "r2gLowRatingQ3", cls: "lab-sigkelly-toggle-r2gq3", name: "7-9月+低评+低分", ratio: null, warn: "🆕NEW默认关",
      advice: "🆕三季末砍低评低分 · vs9键+19,442", tip: "🆕NEW(T1 2026-08-23 方法池全量落库, 非默认推荐)默认关: 排除 rating=low 低评级 × 月份∈{07,08,09}(signal_date) × track_score<75 的交易(空分数视为999不拦)。挖掘代号 R2g(R2 三轮替补族之一, 与 R2a≡主关注×概念/R2b 同族)。【白话】三季度末(7-9月)低评级+低分的信号是历史亏损密集区, 开启后整段剔除。【场景】7-9月回撤放大时开启实测减亏效果; 其余月份本键不产生任何过滤。【1:1】vs9键边际 +19,442 元(round3 口径, docs/kelly/analysis round3 mine14_substitute_validate; 与 R2a +9,681 / R2b +8,254 同批验证)。⚠诚实标注: 上数为 vs9 键边际(补位口径 K1, mode A), 非每日池比值——每日池口径比值待补测, 不编数; 门字段数字以 g2 修正重跑后为准。规格与阈值单源=scripts/loss_rules.py, 判定与凯利区/首页同源(§22)。" }
  ]},
  { key: "combo", title: "复合并集·广谱管理·ratio每日池口径", flags: [
    { k: "r8PureNonMay", cls: "lab-sigkelly-toggle-r8", name: "纯非5月三稳", ratio: 2.11,
      advice: "完全避开5月,可独立补 · 比值2.11", tip: "❌非默认: 排除纯非五月3稳定组件(N1+N2+N3并集)。每日池减亏1.65%/损盈0.78%/比值2.11。2021-2026连续6年全正,完全避开5月shift争议。与5月标志零重叠,可作独立补充。" },
    { k: "r7MayReinforced", cls: "lab-sigkelly-toggle-r7", name: "5月强化+3稳定非5月", ratio: 1.70, warn: "⭐曾默认·v1.1.5移出",
      advice: "最外科式降亏 · 比值1.70 · v1.1.5起非默认", tip: "⭐ 曾是默认推荐(v1.1.4 及以前)🔗核心3键成员, v1.1.5 起 NEW14 重构换基座后移出默认(可手动开): 排除5月强化+3稳定非五月并集。最重要的外科式(surgical)降亏键,损盈最低。每日池减亏2.93%/损盈1.73%/比值1.70。原核心3键成员之一(r7+exclAuxCross+greedy15)。⚠G模式建议配合去greedy15/auxCross使用。" },
    { k: "greedy15", cls: "lab-sigkelly-toggle-greedy15", name: "Greedy-15广谱组合", ratio: 1.28, rec: true, linked: true,
      advice: "A/F大增 · 比值1.28", tip: "⭐ NEW14 默认开(v1.1.5 起现役默认成员)🔗: 排除Greedy-15广谱组合。A/F(短持)收益率最大增来源(去之暴跌19-26pt),留默认。⚠但G(长持,推荐卖出法)模式下贪其负边际最大(去之净利+9.8~12.6万,收益+0.4~2.0pt)。NEW14 中与 r10May6NonMay 同族承担广谱位(勿单开老口径对照实验时混淆)。含step11=N2/step13=V4-G/step15=V4-M。" },
    { k: "excludeMonth", cls: "lab-sigkelly-toggle-month", name: "排除3/5月进场", ratio: 1.18,
      advice: "季节性过滤,可能过拟合 · 比值1.18", tip: "❌非默认: 季节性过滤,排除3月和5月进场。每日池减亏17.21%/损盈14.62%/比值1.18。历史6年3/5月亏多盈少可能过拟合。" },
    { k: "greedy7", cls: "lab-sigkelly-toggle-greedy7", name: "Greedy-7广谱组合", ratio: 1.13,
      advice: "负边际差,勿单开 · 比值1.13", tip: "❌非默认(勿单开): 排除Greedy-7广谱组合。G模式K1负边际-126,328(第三差)。每日池减亏11.24%/损盈9.94%/比值1.13。7条独立亏损逻辑线,近年不失效但每日池下双重砍量损净利。" },
    { k: "r10May6NonMay", cls: "lab-sigkelly-toggle-r10", name: "5月+6非5月组合", ratio: 1.10, rec: true, linked: true,
      advice: "NEW14广谱位成员 · 比值1.10", tip: "⭐ NEW14 默认开(v1.1.5 起现役默认 hist 键): 排除5月+6稳定非五月并集。⚠老口径对照数字: G模式K1负边际-91,267/每日池比值1.10——这是「单开」视角, NEW14 里它与其余13键构成完整黑名单基座(mine28/30 记分板第一), 勿用单开负边际直接否定其在组合中的位置。" },
    { k: "greedy10", cls: "lab-sigkelly-toggle-greedy10", name: "Greedy-10广谱组合", ratio: 1.10,
      advice: "负边际次差,勿单开 · 比值1.10", tip: "❌非默认(勿单开): 排除Greedy-10广谱组合。G模式K1负边际-165,111(第二差)。每日池减亏14.15%/损盈12.83%/比值1.10。广谱过滤在每日池下损净利,别单开。" }
  ]},
  { key: "quality", title: "信号质量·弱信号·ratio每日池口径", flags: [
    { k: "excludeRatingLow", cls: "lab-sigkelly-toggle-rating", name: "排除低评级信号", ratio: 0.97, warn: "⚠️慎用(破坏性)",
      advice: "别单开,砍掉盈利群体 · 比值0.97", tip: "❌非默认⚠慎用(破坏性): 排除rating=low低评级信号。每日池减亏64.60%/损盈66.71%/比值0.97(减亏损盈近1:1,无降亏价值)。低评级是周期性盈利群体(2025牛市+901k),砍掉损净利。诚实标注:全模式净负。" },
    { k: "excludeAux", cls: "lab-sigkelly-toggle-aux", name: "排除辅关注信号", ratio: 0.83,
      advice: "损净利,别单开 · 比值0.83", tip: "❌非默认(别单开): 排除buy_aux辅关注信号。每日池减亏18.59%/损盈22.46%/比值0.83,亏得比盈去得多,损净利。唯一净负信号类型(胜率48%),每日池下系统性最强。" },
    { k: "excludeAuxCross", cls: "lab-sigkelly-toggle-auxcross", name: "辅关注×3/5月交叉", ratio: 0.78, warn: "⭐曾默认·v1.1.5移出",
      advice: "协同价值,勿单看比值 · 比值0.78 · v1.1.5起非默认", tip: "⭐ 曾是默认推荐(v1.1.4 及以前)🔗核心3键成员, v1.1.5 起 NEW14 重构换基座后移出默认(可手动开): 排除buy_aux在3/5月的交叉标志。最外科手术式、双条件交集更稳定。原核心3键成员之一。⚠每日池比值0.78<1且G模式负边际-49,796,主要价值在与同族键协同,勿单开。" }
  ]},
  { key: "market", title: "市场防御·大盘择时·ratio每日池口径", flags: [
    { k: "excludeSpecialBear", cls: "lab-sigkelly-toggle-specialbear", name: "追关注×熊市交叉(四档)", ratio: 2.90, warn: "⭐曾默认·v1.1.5移出",
      advice: "🆕追涨只在熊市主跌/下降期做 · 比值2.90 · v1.1.5起非默认", tip: "⭐ 曾是默认推荐(v1.1.2 2026-08-17 用户拍板 四档升级 → v1.1.4 默认), v1.1.5 起 NEW14 重构换基座后移出默认——其「下降期」拦截位由 declinePhaseSpecial(NEW14 hist 键, 全市场口径)替代且不保留熊市主跌段, 本键保留可手动开(§23.7 不删档): 排除buy_special追关注在四档{熊市·主跌,下降期}的A股类交易。四档=hs300 价 vs MA200 + MA20/60/120 排列: 牛市·主升=价>MA200且多头排列 / 上升期=价>MA200非多头 / 下降期=价<MA200非空头 / 熊市·主跌=价<MA200且空头排列。G模式K1正边际+19,712。" },
    { k: "marketTiming", cls: "lab-sigkelly-toggle-mkt", name: "MA60大盘择时", ratio: 1.24, warn: "⚠️慎用(破坏性)",
      advice: "别单开,全模式净负 · 比值1.24", tip: "❌非默认⚠慎用(破坏性): MA60大盘择时(仅A股a/concept/industry,沪深300在60日均线之上才进场)。每日池减亏37.26%/损盈30.14%/比值1.24(降亏强但损盈更多,全模式净负-14.9万)。诚实标注:别单开。" },
    // v1.1.2 三键备选(2026-08-17 用户拍板): 老MA60熊×追买 / 下降期×追关注, 均默认关带🆕NEW标签
    { k: "legacyMa60Special", cls: "lab-sigkelly-toggle-legacyma60", name: "老MA60熊×追买", ratio: 2.31, warn: "🆕NEW默认关",
      advice: "🆕旧MA60判定·默认关 · 比值2.31", tip: "🆕NEW(v1.1.2 2026-08-17 用户拍板)默认关备选: 保留 v1.1.0 excludeSpecialBear 原 MA60 判定——buy_special 追关注 × A股类 × close<MA60(MA60熊)。与主键四档(excludeSpecialBear)的差别: 主键用四档{熊市·主跌,下降期}判坏, 本键用旧 MA60 判熊。默认关, 如需「绝不放急跌段追高」可手动开(≈ R1_lag 收紧变体方向, 未入默认, 回测见 docs/market-state/kelly-4tier-lagexempt-compare.md)。" },
    { k: "declinePhaseSpecial", cls: "lab-sigkelly-toggle-decline", name: "下降期×追关注", ratio: 1.38, rec: true, linked: true,
      advice: "🆕下降期剔追涨·全市场 · 比值1.38 · NEW14默认开", tip: "⭐ NEW14 默认开(v1.1.5 起现役默认 hist 键; 原 v1.1.2 备选键转正): 排除 buy_special 追关注 × 四档=下降期 × 全市场(不限于A股, = B 方案 V4d_all 增量, 回测全周期 Δ+40,409 见 docs/market-state/kelly-4tier-lagexempt-compare.md)。下降期=价<MA200 但均线纠缠(未空头排列)。在 NEW14 中承担「下降期」拦截位(替代 v1.1.2 主键 excludeSpecialBear 的 A股限定版且更广)。" },
    // #69(2026-08-19 用户拍板) cyb 四档版降亏新键: excludeSpecialBearCyb, 默认关非默认推荐(判定源 hs300→cyb 创业板指)
    { k: "excludeSpecialBearCyb", cls: "lab-sigkelly-toggle-specialbearcyb", name: "追关注×熊市交叉(cyb四档)", ratio: null, warn: "🆕NEW默认关(非默认推荐)",
      advice: "🆕cyb四档剔追涨·非默认 · 比值待用户实测", tip: "🆕NEW(#69 2026-08-19 用户拍板)非默认推荐, 默认关: cyb(创业板指)四档版 excludeSpecialBear——判定语义与主键完全一致, 仅判定源 hs300 四档 → cyb(创业板指)四档: buy_special 追关注 × A股类 × cyb四档∈{熊市·主跌,下降期}。四档定义同主键(价 vs MA200 + MA20/60/120 排列)。默认不进默认组合(生产推荐保持稳定 §23.7), 供用户凯利区人工复测看数据变化; 判定源差异: 主键看沪深300大盘四档, 本键看创业板指四档(创业板指代表成长/中小盘风险偏好, 与沪深300大盘四档可能不同步)。人工开启后, 凯利区「最后结果」按本键重算, 可对比 hs300 版 vs cyb 版过滤差异。" },
    // (2026-08-22 用户拍板) 第 5 个降亏键 bullAuxBackupStop: 牛市·主升×(辅买∪备买)全停, 默认关纯新增(§23.7); 仅 A-F 短线适用, G/H/I 长线豁免(桶级选路径)
    { k: "bullAuxBackupStop", cls: "lab-sigkelly-toggle-bullstop", name: "牛市×辅备买全停(A-F)", ratio: null, warn: "🆕NEW默认关(非默认推荐)",
      advice: "🆕牛主升停辅备买·默认关 · 全史+6,573", tip: "🆕NEW(2026-08-22 用户拍板)非默认推荐, 默认关: 牛市·主升(hs300四档) × 信号∈{buy_aux辅买, buy_backup备买} → 该买入信号拦下(时段级全停)。【白话】牛市主升末段(MA排列滞后判定已走一大段后)的低质量买入(辅买/备买)是历史稳定毒药, 开启后全史 +66,530→+73,103(改善+6,573; 理想对照=被拦笔直接消失口径 +9,895)。【场景】5-8月连亏想减亏时开此键实测; 开启后牛主升段不再接辅买/备买。【1:1】2026年 5-8月 mode A K1 基线 50笔 -5,166 → 开启后 41笔 -1,030(⚠弹窗/凯利区实测=补位口径: 被拦天的次优信号自动顶上, 与理想对照略有差异; 理想对照=-256); 2026 全年 +5,626 → +7,490(理想对照 +10,596)。【诚实标注】除注明外均为补位口径=前端真实链路; 近1/2/3/5年 +15,154→+16,653 / +39,682→+43,084 / +41,523→+45,839 / +31,647→+36,503 五窗全改善; 变差年 4 个(理想对照口径)合计 -5,825(2014/-938、2018/-2,109、2020/-2,039、2025/-739, 均牛市年边缘利润); 仅 A-F 短线适用, G/H/I 长线模式自动豁免(选中 G/H/I 时本键不生效); 默认关不入默认组合(§23.7), 未来若并入默认组合走版本升级流程(§5.4⑥)。数据支撑: docs/kelly/analysis/sim-window-loss-mining-20260822.md(§11 为理想对照口径)。" },
    // K2C5/K3 (2026-08-15 #86 新增 纯前端实验键; v1.1.0 2026-08-15 用户拍板: K2C5 默认开, K3 维持默认关)
    { k: "k2c5HkChase", cls: "lab-sigkelly-toggle-k2c5", name: "港股追涨", ratio: 4.55, rec: true, warn: "⭐默认开(v1.1.0)",
      advice: "剔除港股追涨 · 比值4.55 · NEW14默认开", tip: "⭐ NEW14 默认开(v1.1.0 并入旧八键基座 → v1.1.5 起随基座切 NEW14 继续为默认成员, hist6 之一) = 现役 AI宏组成 **NEW14 十四键 + 1类回测剔除(债类/波段不入宇宙 _bt_in_universe)**; K2C5 已穷举验证(16组合全扫、去K2C5损失+41,445第二大贡献、y1样本外正贡献,见 docs/kelly/analysis/kelly-k2c5-exhaust-interaction.md)。剔除 signal∈{buy_special,buy_backup}×港股 的交易(当前数据文件实算:独立信号728个/全9模式占1431条)。每日池减亏2.88%/损盈0.63%/比值4.55(>2高性价比, 与其他键同口径 ALL9-K1; K2档损盈-0.03%不取, 见 docs/kelly/analysis/kelly-k2c5-dailypool-ratio.md)。全信号除 G 外双升(A/F/H 多年稳定,净利 Δ +4,458~+7,840),16象限 92.4% 正,港股卡剔除后 0 负全转正(它就是港股卡亏损主源);除G外唯一负贡献 I 微负 -1,365。诚实标注 G: 因强平兑现口径分裂, b0(保守,强平记0利)=-2,256 / b1(乐观,按持有时间线性兑现)=+11,755,方向依赖口径,真实强平收益在区间[b0,b1],不把 b1 当承诺。" },
    { k: "k3ConceptBuy", cls: "lab-sigkelly-toggle-k3", name: "主关注×概念", ratio: 1.29, rec: true, linked: true, warn: "⚠️NEW14默认开·监控",
      advice: "剔除主关注概念 · 比值1.29 · NEW14默认开", tip: "⭐ NEW14 默认开(v1.1.5 起现役默认 hist 键; 原 #86 报告建议默认关, mine28/30 记分板后用户拍板转正)⚠监控: 剔除 signal=buy×概念 的交易(当前数据文件实算:独立信号3775个/全9模式占6480条)。原报告顾虑=高波动+牺牲 2024/2025 大赚年,故保留 ⚠监控——每年检查概念子集是否重新转盈。每日池减亏2.84%/损盈2.20%/比值1.29(<2性价比一般, ALL9-K1, 见 docs/kelly/analysis/kelly-k2c5-dailypool-ratio.md)。" },
    // ===== T1(2026-08-23) AI降亏方法池57→全量·20条新键(19条市场防御族 + 日历族R2g见上) =====
    //   成员=二轮挖掘新池13+落池7(R2a≡k3ConceptBuy 已有); 规格单源=scripts/loss_rules.py,
    //   阈值=qth快照(mine10_features.json 2026-08-22版全史分位固化, 不滚动重算); 特征数据=data/kelly_loss_features.json。
    //   ratio=null=每日池口径比值无现成数字待补测(诚实不编数 §23.9), tip 内给 vs9键边际(vs9_net, mine20_pool.json 补位口径 K1 mode A; R2 族=round3 9键边际)。门字段以 g2 修正重跑后为准。
    { k: "n1NorthOutflow", cls: "lab-sigkelly-toggle-n1out", name: "北向20日净流出", ratio: null, rec: true, linked: true,
      advice: "🆕北向流出期全停 · vs9键+13,695 · NEW14默认开", tip: "⭐ NEW14 默认开(v1.1.5 起现役默认规则键 N1; 原 T1 2026-08-23 落库): 排除 north_d20(北向资金近20日净流入,亿)<全史30分位(-58.3) 的全部买入交易。【白话】北向连续净流出时外资在撤, 全类型追买历史亏损密集。【场景】外资大幅流出周自动拦截; 流入期本键零过滤。【1:1】vs9键边际 +13,695 元 / 命中1480笔(mode A K1 补位口径, mine20_pool.json), 池内11键中边际第1。⚠每日池比值待补测。" },
    { k: "t1LowTurnSpecial", cls: "lab-sigkelly-toggle-t1turn", name: "换手冰点×追关注", ratio: null, rec: true, linked: true,
      advice: "🆕缩量行情别追高 · vs9键+10,549 · NEW14默认开", tip: "⭐ NEW14 默认开(v1.1.5 起现役默认规则键 T1; 原 T1 2026-08-23 落库): 排除 turn_pct(全市场换手率3年滚动分位)<30 × buy_special 追关注。【白话】全市场换手降到冰点(近3年最冷的30%时段)还去追涨的信号, 胜率差。【场景】地量行情期自动拦截。【1:1】vs9键边际 +10,549 / 命中144笔(mine20_pool.json)。⚠每日池比值待补测。" },
    { k: "d1LowDivYield", cls: "lab-sigkelly-toggle-d1div", name: "股息率低位(估值贵)", ratio: null, rec: true, linked: true,
      advice: "🆕整体估值贵时停手 · vs9键+8,552 · NEW14默认开", tip: "⭐ NEW14 默认开(v1.1.5 起现役默认规则键 D1; 原 T1 2026-08-23 落库): 排除 div_yield(a_div_yield 全市场股息率%)<全史50分位(2.59) 的全部买入。【白话】股息率低=市场整体贵, 贵的时候少进场。【场景】指数高位/股息率压到2.6%下方时自动拦截。【1:1】vs9键边际 +8,552 / 命中621笔(mine20_pool.json)。⚠每日池比值待补测。" },
    { k: "q1QvixLowPct", cls: "lab-sigkelly-toggle-q1qvix", name: "QVIX低分位(自满)", ratio: null, rec: true, linked: true,
      advice: "🆕波动率过低=暴风雨前 · vs9键+4,341 · NEW14默认开", tip: "⭐ NEW14 默认开(v1.1.5 起现役默认规则键 Q1; 原 T1 2026-08-23 落库): 排除 qvix_pct(QVIX 3年滚动分位)<10 的全部买入。【白话】隐含波动率压到历史最低一档, 市场过度自满, 后面容易变盘。【场景】QVIX 分位跌破10时自动拦截。【1:1】vs9键边际 +4,341 / 命中461笔(mine20_pool.json)。⚠每日池比值待补测。" },
    { k: "h1VolChgHighA", cls: "lab-sigkelly-toggle-h1volchg", name: "升波×A股", ratio: null, rec: true, linked: true,
      advice: "🆕波动放大期停A股 · vs9键+6,647 · NEW14默认开", tip: "⭐ NEW14 默认开(v1.1.5 起现役默认规则键 H1; 原 T1 2026-08-23 落库): 排除 h_volchg(hs300 5日std/20日std年化比-1,% )>全史30分位(-23.6) × A股类(mkt=a)。【白话】短端波动比长端明显放大(升波)时,A股信号先撤——升波常伴随急跌启动。【场景】大盘开始放量异动时自动拦截。【1:1】vs9键边际 +6,647 / 命中605笔(mine20_pool.json)。⚠每日池比值待补测。" },
    { k: "m1MarginDownBull", cls: "lab-sigkelly-toggle-m1margin", name: "牛主升×两融降温", ratio: null, rec: true, linked: true,
      advice: "🆕杠杆退潮的牛市别信 · vs9键+3,035 · NEW14默认开", tip: "⭐ NEW14 默认开(v1.1.5 起现役默认规则键 M1; 原 T1 2026-08-23 落库): 排除 margin_chg20(两融余额20日变化率%)<全史70分位(2.08) × hs300四档=牛市·主升(A股类)。【白话】名义上是牛市主升, 但两融(杠杆资金)在退潮, 这种背离段的买入不可信。【场景】牛市段发现两融连续下降时自动拦截。【1:1】vs9键边际 +3,035 / 命中348笔(mine20_pool.json)。⚠每日池比值待补测; 两融序列仅2021-02起(源边界, 更早日期本键不拦)。" },
    { k: "d2LowDivBull", cls: "lab-sigkelly-toggle-d2div", name: "牛主升×股息率低位", ratio: null, warn: "🆕NEW默认关",
      advice: "🆕牛市末段估值贵 · vs9键+5,301", tip: "🆕NEW(T1 2026-08-23, 默认关): 排除 div_yield<全史70分位(2.93) × 牛市·主升(A股类四档)。【白话】牛市主升+市场贵(股息率低)的组合≈牛市后半场追高。【场景】牛主升段里股息率再破2.93时开启。【1:1】vs9键边际 +5,301 / 命中1062笔(mine20_pool.json, 过 g1/g3 门)。⚠每日池比值待补测。" },
    { k: "p1LowDivBackup", cls: "lab-sigkelly-toggle-p1div", name: "备买×股息率分位低", ratio: null, rec: true, linked: true,
      advice: "🆕便宜市也别接备买刀 · vs9键+571 · NEW14默认开", tip: "⭐ NEW14 默认开(v1.1.5 起现役默认规则键 P1; 原 T1 2026-08-23 落库): 排除 div_pct(div_yield 3年滚动分位)<30 × buy_backup 备买。【白话】即便估值分位不高, 备买(兜底型信号)在股息率偏低的时段接飞刀依然亏。【场景】备买信号在低估值分位时段自动拦截。【1:1】vs9键边际 +571 / 命中195笔(mine20_pool.json)。⚠每日池比值待补测。" },
    { k: "v1HighVol20", cls: "lab-sigkelly-toggle-v1vol20", name: "高波动>90分位", ratio: null, warn: "🆕NEW默认关",
      advice: "🆕恐慌顶部全停 · vs9键+3,566", tip: "🆕NEW(T1 2026-08-23, 默认关): 排除 h_vol20(hs300 20日年化已实现波动%)>全史90分位(30.7) 的全部买入。【白话】20日实现波动冲进历史最高一档=市场正在剧烈动荡, 此时任何买入都是赌。【场景】暴跌震荡期开启。【1:1】vs9键边际 +3,566 / 命中189笔(mine20_pool.json)。⚠每日池比值待补测。" },
    { k: "s1SentALow", cls: "lab-sigkelly-toggle-s1senta", name: "A股情绪冰点", ratio: null, warn: "🆕NEW默认关",
      advice: "🆕情绪<20分位全停 · vs9键+982", tip: "🆕NEW(T1 2026-08-23, 默认关): 排除 sent_a(a_sentiment A股情绪分)<全史20分位(33.27) 的全部买入。【白话】情绪分压到历史最低两成时, 反转没来之前继续阴跌。【场景】情绪指标长期低迷段开启。【1:1】vs9键边际 +982 / 命中382笔(mine20_pool.json)。⚠g3 门未过(前瞻弱), 每日池比值待补测。" },
    { k: "r1VolRatioLow", cls: "lab-sigkelly-toggle-r1volratio", name: "量能萎缩<10分位", ratio: null, warn: "🆕NEW默认关",
      advice: "🆕极端地量全停 · vs9键+1,553", tip: "🆕NEW(T1 2026-08-23, 默认关): 排除 vol_ratio_all(a_volume_ratio 全市场量比)<全史10分位(0.876) 的全部买入。【白话】量比缩到历史最低一档=流动性枯竭, 买入滑点与假突破风险都大。【场景】节假日前后/地量段开启。【1:1】vs9键边际 +1,553 / 命中391笔(mine20_pool.json)。⚠g3 未过, 每日池比值待补测。" },
    { k: "r2bSpecialGlobal", cls: "lab-sigkelly-toggle-r2bglobal", name: "追关注×全球类", ratio: null, rec: true, linked: true,
      advice: "🆕全球类追涨剔除 · vs9键+8,254 · NEW14默认开", tip: "⭐ NEW14 默认开(v1.1.5 起现役默认规则键 R2b; 原 T1 2026-08-23 落库): 排除 buy_special 追关注 × mkt=global 全球类的交易。挖掘代号 R2b(R2 三轮替补族)。【白话】全球类(海外指数ETF)的追关注信号历史胜率差, 与 K2C5 港股追涨同思路、不同域类。【场景】NEW14 内与 K2C5 互补(港股+全球类追涨一起收掉)。【1:1】vs9键边际 +8,254 元(round3 口径, 同批 R2a +9,681 / R2g +19,442)。⚠每日池比值待补测。" },
    { k: "n2NorthOutConcept", cls: "lab-sigkelly-toggle-n2nout", name: "北向流出×概念类", ratio: null, warn: "🆕NEW默认关",
      advice: "🆕外资撤+题材炒作双杀 · vs9键+7,054", tip: "🆕NEW(T1 2026-08-23, 默认关): 排除 north_d20<全史30分位(-58.3亿) × mkt=concept 概念类(N1 的子集变体)。【白话】外资在撤的同时还在炒题材概念, 双重风险叠加。【场景】北向流出期只想收概念仓时用(比 N1 精准、砍量更少)。【1:1】vs9键边际 +7,054 / 命中784笔(mine20_pool.json; 开 N1 时本键不再新增过滤, 属其子集)。⚠每日池比值待补测。" },
    { k: "v2Vol20Gt25", cls: "lab-sigkelly-toggle-v2vol25", name: "波动≥25%(固定线)", ratio: null, warn: "🆕NEW默认关",
      advice: "🆕波动破25%全停 · vs9键-8,636", tip: "🆕NEW(T1 2026-08-23, 默认关): 排除 h_vol20≥25%(固定常数, 非分位) 的全部买入。一轮候选3 变体(V1 的放宽版)。【白话】波动一旦越过25%这条固定警戒线就停手。【场景】想用绝对阈值(而非历史分位)控波动暴露时开。【1:1】vs9键边际 -8,635.64 / 命中688笔(mine20_pool.json)。⚠诚实标注: 边际为负(单开损净利), 落池键仅作协同定性参考; 每日池比值待补测。" },
    { k: "s2SentHs300Low", cls: "lab-sigkelly-toggle-s2sent300", name: "HS300情绪冰点", ratio: null, warn: "🆕NEW默认关",
      advice: "🆕300情绪冰点全停 · vs9键-879", tip: "🆕NEW(T1 2026-08-23, 默认关): 排除 sent_hs300(score_daily sentiment_hs300)<全史20分位(35.07) 的全部买入(S1 的 hs300 版)。【白话】沪深300维度情绪同样冰冷时的停手变体。【场景】对比 S1(A股情绪版)哪个更贴身时开。【1:1】vs9键边际 -879.07 / 命中437笔(mine20_pool.json)。⚠诚实标注: 单开边际为负; 每日池比值待补测。" },
    { k: "w1BackupDecline", cls: "lab-sigkelly-toggle-w1backup", name: "备买×下降期", ratio: null, warn: "🆕NEW默认关",
      advice: "🆕下降期别接备买 · vs9键-2,485", tip: "🆕NEW(T1 2026-08-23, 默认关): 排除 buy_backup 备买 × hs300四档=下降期(A股类)。一轮观察型候选(W 族)。【白话】下降趋势里的兜底型买入=接飞刀变体, 但样本小效果不稳。【场景】下降期想单独收紧备买(不动其他信号)时开。【1:1】vs9键边际 -2,484.65 / 命中40笔(mine20_pool.json, 三门全未过)。⚠诚实标注: 单开边际为负+样本小; 每日池比值待补测。" },
    { k: "a1BullAllStop", cls: "lab-sigkelly-toggle-a1bull", name: "牛主升全停(超集)", ratio: null, warn: "🆕NEW默认关",
      advice: "🆕牛主升全类型停 · vs9键-11,884", tip: "🆕NEW(T1 2026-08-23, 默认关): 排除 hs300四档=牛市·主升(A股类)的全部买入——bullAuxBackupStop(只停辅买∪备买)的全类型超集。一轮候选2激进版。【白话】把牛市主升段所有买入全停掉, 比 bullAuxBackupStop 狠得多。【场景】仅在「牛市末段全面避险」实验时开。【1:1】vs9键边际 -11,884.00 / 命中1767笔(mine20_pool.json)。⚠诚实标注: 单开边际大幅为负(误伤牛市盈利主体), 落池键仅作对照; 每日池比值待补测。" },
    { k: "v3Vol20LowPct", cls: "lab-sigkelly-toggle-v3vollow", name: "低波动<10分位", ratio: null, warn: "🆕NEW默认关",
      advice: "🆕极度平静期也危险 · vs9键-2,470", tip: "🆕NEW(T1 2026-08-23, 默认关): 排除 h_vol20<全史10分位(10.73) 的全部买入(V1 的反面: 低波不动段)。【白话】波动压到历史最低一档=多空都没劲, 信号质量普遍差。【场景】窄幅横盘段实验开启。【1:1】vs9键边际 -2,470.24 / 命中1057笔(mine20_pool.json)。⚠诚实标注: 单开边际为负且砍量大(命中1057笔); 每日池比值待补测。" },
    { k: "ad1AdlineHot", cls: "lab-sigkelly-toggle-ad1hot", name: "AD线广度过热", ratio: null, warn: "🆕NEW默认关",
      advice: "🆕普涨过热期停手 · vs9键-236", tip: "🆕NEW(T1 2026-08-23, 默认关): 排除 adline_gap((a_ad_line-a_ad_line_ma20)/|ma20|)>全史70分位(0.060) 的全部买入。【白话】腾落线(AD)远高于其20日线=个股普涨过热, 追买容易买在短期顶部。【场景】普涨大阳线频出时实验开启。【1:1】vs9键边际 -235.61 / 命中845笔(mine20_pool.json)。⚠诚实标注: 单开微负(接近零效应); 每日池比值待补测。" },
    { k: "excludeTierNone", cls: "lab-sigkelly-toggle-xtnone", name: "整剔有跟踪ETF象限", ratio: null, warn: "🆕NEW默认关·NEW14+1成员",
      advice: "🆕回撤改善档 · 数字扩围后待重算", tip: "🆕NEW(X1, mine29c 2026-08-24 用户拍板, 默认关): 排除「有跟踪ETF」整卡信号(track_tier=none/null——匹配不到强关联/相关/近似 ETF: none=30-49 弱跟踪兜底、null=<30 极弱或 N<30 无分; 2026-08-24 用户拍板由仅剔 none 扩为剔 none+null, 与回测卡/首页筛选档4口径完全统一)——NEW14+1·15键可选档(new15)唯一新增键。【白话】连一只像样跟踪标的都配不上的信号=指数代表性最差的一档, 整组不碰。【场景】想要比 NEW14 更浅的回撤时, 切模式下拉「NEW14+1 · 15键」一键带上本键(单独手开亦可)。【1:1·⚠扩围前仅剔none历史口径, 扩围后作废待正式穷举回测重算】NEW14 全史 +122,648/mdd -4,178 → 加本键 +122,705(+56.61, +0.05%)/mdd -3,550(-628, -15%)(etf_def 口径); 页面口径被剔17笔毛+584.62/费359.07/净+225.56, 替补3笔-196.70, Δ=-422。近5年12笔账面 -1,450.66 但补位回收 +1,253.96(mine29c §10.1)。⚠诚实标注: mine29 判决=「噪声级无效改善」, bootstrap 全窗含0 不显著, 回撤改善是唯一真实正效用; 远古5笔(2020-07~2021-08)+1,676.22 掩盖了近端亏损——用户知情后拍板保留为可选档供实测。" }
  ]}
];

// ===== T2(2026-08-23) AI 降亏组成对比展示区(纯展示零交互 §23.7) =====
//   数据权威=docs/kelly/analysis/sim-combo-cheatsheet-20260823.md + mine24_compare.json(anchor 已逐位核对,
//   B_on9 恢复天数速查卡"约200天"系笔误, 以 json=267 天为准; C_on9 json 记 18 天=日历日差19-1 口径);
//   规则中文名单源=_kellyFadeFlagGroups(既有键 label)+ scripts/loss_rules.py RULE_SPECS(T1 新键 desc, 不裸奔英文键名);
//   纯展示层: 不接开关/下拉/谓词(交互归 T3), 默认行为零改动; 数字为静态快照禁止前端自算。
//   chip 类型: base=叠放基座键(金底) / add=本方案叠加键(绿底) / reb=重构口径成员键(蓝底, 无基座概念)。
var _KELLY_MODE_COMPARE_CARDS = [
  { id: "p0", name: "8键", tagline: "v1.1.2 基座·稳定参照", caliber: "✓ v1.1.4 及以前默认(现对照档)", calWarn: false, best: false,
    keys: [
      ["excludeSpecialBear", "追关注×熊市交叉(四档)", "base"],
      ["n2NovSpecialIndustry", "11月+追关注+行业", "base"],
      ["janMidRating", "1月中旬+中评级", "base"],
      ["janMidSpecial", "1月中旬+追关注", "base"],
      ["k2c5HkChase", "港股追涨(K2C5)", "base"],
      ["r7MayReinforced", "5月强化+3稳定非5月", "base"],
      ["excludeAuxCross", "辅关注×3/5月交叉", "base"],
      ["greedy15", "Greedy-15广谱组合", "base"]
    ],
    perf: { net: "+66,530", y1: "+15,714", mdd: "-18,190", rec: "350天", n: "1126笔/胜率52.6%" },
    tip: "【8键 · v1.1.2 基座·稳定参照】✓ v1.1.4 及以前默认(v1.1.5 起为对照档)。【白话】老默认组合(基础5+核心3=8键), 是一切方案对比的原地基参照系。【场景】想回老基座对照时经「模式」下拉选它; 衡量其他方案多赚多少/少回撤多少都拿它当基准。【1:1】全史净利 +66,530 元, 最大回撤 -18,190 元(2023-10-31 见底, 2024-10-16 收复, 恢复 350 天); 近1年 +15,714 / 2026YTD +5,626; 1126 笔胜率 52.6%。诚实标注: 速查卡结论=已被全面超越(NEW14 全史多赚约 5.6 万且回撤浅 77%), 现价值=对照参照系。" },
  { id: "p1", name: "9键", tagline: "8+候选1·牛市辅备买拦截", caliber: "✓ 叠 8 键(+候选1)", calWarn: false, best: false,
    keys: [
      ["excludeSpecialBear", "追关注×熊市交叉(四档)", "base"],
      ["n2NovSpecialIndustry", "11月+追关注+行业", "base"],
      ["janMidRating", "1月中旬+中评级", "base"],
      ["janMidSpecial", "1月中旬+追关注", "base"],
      ["k2c5HkChase", "港股追涨(K2C5)", "base"],
      ["r7MayReinforced", "5月强化+3稳定非5月", "base"],
      ["excludeAuxCross", "辅关注×3/5月交叉", "base"],
      ["greedy15", "Greedy-15广谱组合", "base"],
      ["bullAuxBackupStop", "牛市×辅备买全停(候选1)", "add"]
    ],
    perf: { net: "+73,103", y1: "+17,213", mdd: "-17,650", rec: "349天", n: "1032笔/胜率53.1%" },
    tip: "【9键 · 叠8键+候选1】✓ 叠 8 键再开候选1(bullAuxBackupStop 牛市·主升×辅买∪备买全停)。【白话】比 8键全面小胜 +6,572 元, 但也只是「8键 plus」无质变。【场景】A/B/C 三张卡的叠放基座就是它; v1.1.4 及以前默认口径(v1.1.5 起为对照档, 现役默认=NEW14 十四键)。【1:1】全史净利 +73,103 元, 最大回撤 -17,650 元(恢复 349 天); 近1年 +17,213 / 2026YTD +7,490; 1032 笔胜率 53.1%。" },
  { id: "a9", name: "A on9", tagline: "进攻王·近端牛市吃满", caliber: "⚠ 叠 9 键口径(叠加规则非独立组合)", calWarn: true, best: true,
    keys: [
      ["excludeSpecialBear", "追关注×熊市交叉(四档)", "base"],
      ["n2NovSpecialIndustry", "11月+追关注+行业", "base"],
      ["janMidRating", "1月中旬+中评级", "base"],
      ["janMidSpecial", "1月中旬+追关注", "base"],
      ["k2c5HkChase", "港股追涨(K2C5)", "base"],
      ["r7MayReinforced", "5月强化+3稳定非5月", "base"],
      ["excludeAuxCross", "辅关注×3/5月交叉", "base"],
      ["greedy15", "Greedy-15广谱组合", "base"],
      ["bullAuxBackupStop", "牛市×辅备买全停(候选1)", "base"],
      ["t1LowTurnSpecial", "换手冰点×追关注(T1)", "add"],
      ["q1QvixLowPct", "QVIX低分位(Q1)", "add"],
      ["m1MarginDownBull", "牛主升×两融降温(M1)", "add"],
      ["v1HighVol20", "高波动&gt;90分位(V1)", "add"],
      ["r1VolRatioLow", "量能萎缩&lt;10分位(R1)", "add"],
      ["k3ConceptBuy", "主关注×概念(≡R2a)", "add"],
      ["r2bSpecialGlobal", "追关注×全球类(R2b)", "add"],
      ["r2gLowRatingQ3", "7-9月+低评+低分(R2g)", "add"]
    ],
    perf: { net: "+119,110", y1: "+26,630", mdd: "-6,784", rec: "99天", n: "574笔/胜率63.1%" },
    tip: "【A on9 · 进攻王】⚠ 叠 9 键口径: 在 9 键基座上再叠 8 条规则(T1/Q1/M1/V1/R1/R2a≡主关注×概念/R2b/R2g), 不是独立组合。【白话】赚最多跑最快: 频次砍半、胜率升到 63%, 近端牛市吃满。【场景】要历史利润最大化且回撤可控、能接受偶发砍牛市利润时选它。【1:1】全史净利 +119,110 元(vs 8键 +66,530); 回撤 -6,784 元恢复 99 天(8键 350 天的不到三分之一); 近1年 +26,630 全场第一 / 2026YTD +15,574 第一; 574 笔胜率 63.1%。弱=新方案里回撤最大、2019-20 结构牛会砍利润、G/I 长线不适配。" },
  { id: "b9", name: "B on9", tagline: "均衡卡·K档最钝感", caliber: "⚠ 叠 9 键口径(叠加规则非独立组合)", calWarn: true, best: false,
    keys: [
      ["excludeSpecialBear", "追关注×熊市交叉(四档)", "base"],
      ["n2NovSpecialIndustry", "11月+追关注+行业", "base"],
      ["janMidRating", "1月中旬+中评级", "base"],
      ["janMidSpecial", "1月中旬+追关注", "base"],
      ["k2c5HkChase", "港股追涨(K2C5)", "base"],
      ["r7MayReinforced", "5月强化+3稳定非5月", "base"],
      ["excludeAuxCross", "辅关注×3/5月交叉", "base"],
      ["greedy15", "Greedy-15广谱组合", "base"],
      ["bullAuxBackupStop", "牛市×辅备买全停(候选1)", "base"],
      ["t1LowTurnSpecial", "换手冰点×追关注(T1)", "add"],
      ["q1QvixLowPct", "QVIX低分位(Q1)", "add"],
      ["m1MarginDownBull", "牛主升×两融降温(M1)", "add"],
      ["r1VolRatioLow", "量能萎缩&lt;10分位(R1)", "add"],
      ["r2bSpecialGlobal", "追关注×全球类(R2b)", "add"],
      ["r2gLowRatingQ3", "7-9月+低评+低分(R2g)", "add"]
    ],
    perf: { net: "+109,572", y1: "+22,905", mdd: "-12,408", rec: "267天", n: "628笔/胜率61.5%" },
    tip: "【B on9 · 均衡卡】⚠ 叠 9 键口径: 在 9 键基座上叠 6 条规则(T1/Q1/M1/R1/R2b/R2g)。【白话】每项都不差、无单项冠军也无短板, K 档最不敏感(±710)。【场景】想要 K 档敏感性最小的稳妥叠加、不追求单项极致时选它。【1:1】全史净利 +109,572 元; 回撤 -12,408 元恢复 267 天; 近1年 +22,905 / 2026YTD +11,849; 628 笔胜率 61.5%。弱=回撤明显大于 A/C/NEW。诚实标注: 速查卡曾写恢复「约200天」, mine24_compare.json 原始值=267 天(trough 2022-05-10 → recover 2023-02-02), 以 json 为准。" },
  { id: "c9", name: "C on9", tagline: "保守防守·熊市少亏", caliber: "⚠ 叠 9 键口径(注: 选 C 更优应叠 8 键并下线候选1)", calWarn: true, best: false,
    keys: [
      ["excludeSpecialBear", "追关注×熊市交叉(四档)", "base"],
      ["n2NovSpecialIndustry", "11月+追关注+行业", "base"],
      ["janMidRating", "1月中旬+中评级", "base"],
      ["janMidSpecial", "1月中旬+追关注", "base"],
      ["k2c5HkChase", "港股追涨(K2C5)", "base"],
      ["r7MayReinforced", "5月强化+3稳定非5月", "base"],
      ["excludeAuxCross", "辅关注×3/5月交叉", "base"],
      ["greedy15", "Greedy-15广谱组合", "base"],
      ["bullAuxBackupStop", "牛市×辅备买全停(候选1)", "base"],
      ["n1NorthOutflow", "北向20日净流出(N1)", "add"],
      ["t1LowTurnSpecial", "换手冰点×追关注(T1)", "add"],
      ["d1LowDivYield", "股息率低位(D1)", "add"],
      ["h1VolChgHighA", "升波×A股(H1)", "add"],
      ["m1MarginDownBull", "牛主升×两融降温(M1)", "add"],
      ["p1LowDivBackup", "备买×股息率分位低(P1)", "add"],
      ["r2bSpecialGlobal", "追关注×全球类(R2b)", "add"]
    ],
    perf: { net: "+107,113", y1: "+16,800", mdd: "-4,332", rec: "18天", n: "438笔/胜率64.4%" },
    tip: "【C on9 · 极简防守】⚠ 叠 9 键口径: 在 9 键基座上叠 7 条规则(N1/T1/D1/H1/M1/P1/R2b)。⚠速查卡结论: 若真选 C 应改叠 8 键并下线候选1(on8 +112,141 > on9 +107,113), 本卡数字为 on9 口径仅供横向对比。【白话】笔数最少回撤第二浅的防守卡, 但牛市系统性少赚。【场景】求稳防守时考虑; 注意它近1年几乎白干, 别只盯回撤数字。【1:1】on9 口径全史净利 +107,113 元; 回撤 -4,332 元恢复最快(json 记 18 天, 日历日差 19); 近1年 +16,800 还低于 P1 的 +17,213; 438 笔胜率 64.4%。2014-15/2020-21 两轮牛都被砍。" },
  { id: "new14", name: "NEW 14键", tagline: "新防守王·全史第一+回撤最浅", caliber: "✓ 可回选静态对照档(v1.1.5~v1.1.6 曾为默认·重构换基座, 与 A/B/C 完全不同结构)", calWarn: false, best: true,
    keys: [
      ["r10May6NonMay", "5月+6非5月组合(r10)", "reb"],
      ["greedy15", "Greedy-15广谱组合(greedy15)", "reb"],
      ["janMidSpecial", "1月中旬+追关注(janMidSpecial)", "reb"],
      ["k2c5HkChase", "港股追涨(K2C5)", "reb"],
      ["k3ConceptBuy", "主关注×概念(k3ConceptBuy)", "reb"],
      ["declinePhaseSpecial", "下降期×追关注(declinePhaseSpecial)", "reb"],
      ["n1NorthOutflow", "北向20日净流出(N1)", "reb"],
      ["t1LowTurnSpecial", "换手冰点×追关注(T1)", "reb"],
      ["d1LowDivYield", "股息率低位(D1)", "reb"],
      ["q1QvixLowPct", "QVIX低分位(Q1)", "reb"],
      ["h1VolChgHighA", "升波×A股(H1)", "reb"],
      ["m1MarginDownBull", "牛主升×两融降温(M1)", "reb"],
      ["p1LowDivBackup", "备买×股息率分位低(P1)", "reb"],
      ["r2bSpecialGlobal", "追关注×全球类(R2b)", "reb"]
    ],
    perf: { net: "+122,648", y1: "+18,189", mdd: "-4,178", rec: "26天", n: "429笔/胜率66.9%" },
    tip: "【NEW 14键 · 新防守王·v1.1.7 起非默认(v1.1.5~v1.1.6 曾为默认)】✓ 重构换基座口径: 从全池出发仅这 14 键即完整黑名单(hist 键 6: r10/greedy15/janMidSpecial/k2c5/k3/下降期×追关注 + 规则键 8: N1/T1/D1/Q1/H1/M1/P1/R2b; 不预设 8 默认键在场、弃候选1), 与 A/B/C 的「叠加」完全不同结构, 不能混为一谈。【白话】全史利润第一 + 回撤最浅恢复最快的双冠王, v1.1.5~v1.1.6 曾为全站默认基座, v1.1.7 起默认已切 S06·大盘领先切换(本档降为可回选静态对照档·现非默认)。切换依据=mine28 AUTO 轮动样本外不成立+mine30 记分板 NEW14 第一。【场景】要「睡得着觉」——回撤最浅恢复最快且全史还最高; 接受近端弹性让位 A、以及年均约 2.4 次 ≥20 交易日的信号枯竭期(枯竭提示 chip 已上线, 历史上类似枯竭结束后 3 个月约 72% 为正)。【1:1】全史净利 +122,648 元(全场第一) vs 8键 +66,530; 回撤 -4,178 元恢复 26 天 vs 8键 -18,190 恢复 350 天(浅约 77%、恢复快约 13 倍); 近1年 +18,189(少赚 A 约 8,441)/ 2026YTD +10,016; 429 笔胜率 66.9% 全场最高; 四熊合计第一(2018 唯一转正)、十大亏月减亏第一。诚实标注: 同效果支配解族还有 15/16/17/19/21/24 键共 7 种表达逐笔等价, 落地取最简 14 键即可; 优势集中在 K1(K4 被 A 反超)。" },
  // new18(NEW2·18键)卡已于 2026-08-26 应用户确认移除(原话「18和14键差异太小了 而且有了14+1的这个正向差异化就够了 18不要了」):
  //   NEW 族次优影子对照无独立价值, 模式下拉同项上一批(a428)已删; 原始数字仍存 docs/kelly/analysis mine24_compare.json 可查。
  { id: "new15", name: "NEW14+1 · 15键", tagline: "NEW14+整剔有跟踪ETF象限(none/null)·回撤改善档", caliber: "⚠ 重构换基座(NEW 族扩展·可选档非默认)", calWarn: true, best: false,
    keys: [
      ["r10May6NonMay", "5月+6非5月组合(r10)", "reb"],
      ["greedy15", "Greedy-15广谱组合(greedy15)", "reb"],
      ["janMidSpecial", "1月中旬+追关注(janMidSpecial)", "reb"],
      ["k2c5HkChase", "港股追涨(K2C5)", "reb"],
      ["k3ConceptBuy", "主关注×概念(k3ConceptBuy)", "reb"],
      ["declinePhaseSpecial", "下降期×追关注(declinePhaseSpecial)", "reb"],
      ["n1NorthOutflow", "北向20日净流出(N1)", "reb"],
      ["t1LowTurnSpecial", "换手冰点×追关注(T1)", "reb"],
      ["d1LowDivYield", "股息率低位(D1)", "reb"],
      ["q1QvixLowPct", "QVIX低分位(Q1)", "reb"],
      ["h1VolChgHighA", "升波×A股(H1)", "reb"],
      ["m1MarginDownBull", "牛主升×两融降温(M1)", "reb"],
      ["p1LowDivBackup", "备买×股息率分位低(P1)", "reb"],
      ["r2bSpecialGlobal", "追关注×全球类(R2b)", "reb"],
      ["excludeTierNone", "整剔有跟踪ETF象限(X1)", "reb"]
    ],
    perf: { net: "+122,705", y1: "+18,804", mdd: "-3,550", rec: "26天", n: "415笔/胜率67.7%" },
    tip: "【NEW14+1 · 15键 · 可选档非默认(§23.7 纯新增)】⚠ 重构换基座口径: NEW14 十四键原样保留 + 整剔有跟踪ETF象限(best ETF 无强关联/相关/近似档跟踪标的的信号=track_tier=none/null 整卡, 2026-08-24 扩围含 <30 极弱/无分 null 档)。【白话】连一只像样跟踪标的都配不上的信号=指数代表性最差一档, 整组不碰; 主收益是回撤变浅不是多赚。【场景】想要比 NEW14 更浅回撤时切模式下拉「NEW14+1 · 15键」一键带上(单独手开整剔有跟踪ETF象限 toggle 亦可)。【1:1·⚠扩围前仅剔none历史口径(下述数字扩围后作废待重算)】全史净利 +122,705 元(vs NEW14 +122,648, 仅 +56.61/+0.05%); 回撤 -3,550 元(vs NEW14 -4,178, 浅 628/-15%), 谷日 20240913/恢复 20241009 不变; 近1年 +18,804(vs NEW14 +18,189); 415 笔胜率 67.7%(被剔 17 笔占入选 3.96%)。页面费率口径复核(mine29c §10.4): 被剔17笔毛+584.62/费359.07/净+225.56, 替补3笔-196.70, Δ=-422。⚠诚实标注: mine29 判决=「噪声级无效改善」, bootstrap 全窗含0 不显著, 回撤改善是唯一真实正效用; 用户知情后拍板保留为可选档供实测。" }
];

// T2(2026-08-23): 组成对比折叠区 HTML(纯展示, <details> 默认收起; 展开态持久化 state.labSigKellyModeCompareOpen)
function _kellyModeCompareHTML() {
  var _chipCls = { base: "lab-sigkelly-mode-chip-base", add: "lab-sigkelly-mode-chip-add", reb: "lab-sigkelly-mode-chip-reb" };
  var cardsHTML = _KELLY_MODE_COMPARE_CARDS.map(function (c) {
    var chips = c.keys.map(function (kv) {
      return `<span class="lab-sigkelly-mode-chip ${_chipCls[kv[2]] || ""}" title="${kv[0]}">${kv[1]}</span>`;
    }).join("");
    return `<div class="lab-sigkelly-mode-card${c.best ? " lab-sigkelly-mode-card-best" : ""}" tabindex="0" data-no-pop="" data-tip="${c.tip}">` +
        `<div class="lab-sigkelly-mode-card-head"><span class="lab-sigkelly-mode-card-name">${c.name}</span><span class="lab-sigkelly-mode-tagline">${c.tagline}</span>${c.best ? '<span class="lab-sigkelly-mode-star">★</span>' : ""}</div>` +
        `<div class="lab-sigkelly-mode-caliber${c.calWarn ? " warn" : ""}">${c.caliber}</div>` +
        `<div class="lab-sigkelly-mode-keys">${chips}</div>` +
        `<div class="lab-sigkelly-mode-perf">全史净利 <b>${c.perf.net}</b> 元 · 回撤 <b>${c.perf.mdd}</b>(恢复 ${c.perf.rec}) · 近1年 ${c.perf.y1} · ${c.perf.n}<span class="lab-sigkelly-toggle-tip" title="${c.tip}">ⓘ</span></div>` +
      `</div>`;
  }).join("");
  return `<details class="lab-sigkelly-mode-compare"${state.labSigKellyModeCompareOpen ? " open" : ""}>` +
      `<summary class="lab-sigkelly-mode-compare-summary">🧩 AI 降亏组成对比(${_KELLY_MODE_COMPARE_CARDS.length} 方案各由哪些规则叠加而成 · 点开看构成) <span class="lab-sigkelly-toggle-cat-caret">▼</span></summary>` +
      `<div class="lab-sigkelly-mode-compare-body">` +
        `<div class="lab-sigkelly-mode-compare-note">⚠ 先看清口径: <b>A/B/C</b> 是在 9 键基座上加规则(叠加口径, 金色=基座键/绿色=本方案叠加键); <b>NEW 14键/NEW14+1·15键</b> 是完全不同的组合结构(重构换基座, 蓝色=成员键, 不预设 8 默认在场、弃候选1; NEW14+1 为可选档非默认), 两者不能混为一谈。(NEW2·18键对照卡已于 2026-08-26 移除: 与14键差异太小, 原始数字存 mine24_compare.json)</div>` +
        `<div class="lab-sigkelly-mode-cards">${cardsHTML}</div>` +
        `<div class="lab-sigkelly-mode-compare-foot">📐 数字口径: mode A + K1 + etf_def 费后补位口径(signal_date 切片); 数据版本 signal_kelly_trades generated_at=2026-08-23 05:09, 权威值=mine24_compare.json(经独立审查二次验证, docs/kelly/analysis/sim-combo-cheatsheet-20260823.md)。★=该维度冠军(A=近端收益冠军 / NEW=全史净利+回撤双冠)。本区为纯展示快照, 不随页面开关重算(交互切换归后续版本)。</div>` +
      `</div>` +
    `</details>`;
}

function _renderSigKellyBar(bar, data, period) {
  // B级UI(2026-08-15): 移动端吸顶条默认折叠成1行(周期+「参数」按钮), 全部控制台收进展开区, 点「参数」展开。用户方案A。
  // 展开/收起态持久化 localStorage lab_sigkelly_params_open; 未设置过则按设备宽度默认(≤600px 收起 / >600px 展开=PC现状)。重渲染后保持, 不回落默认。
  // 说明: PC 端保持展开(现状)避免用户觉得功能"藏起来"; 仅移动端默认收起缓解吸顶高度(叠加3层导航后内容被压到屏下)。
  const _sigParamsOpenState = _sigKellyParamsOpen();
  function _sigKellyParamsOpen() {
    let saved = null;
    try { saved = localStorage.getItem('lab_sigkelly_params_open'); } catch (e) { saved = null; }
    if (saved !== null) return saved === '1';
    const isMobile = window.matchMedia && window.matchMedia("(max-width: 600px)").matches;
    return !isMobile; // 移动端默认收起, PC 默认展开
  }
  const cfg = data.config || {};
  const periods = cfg.periods || { y1: "近1年", y3: "近3年", all: "全部" };
  const tabsHTML = Object.keys(periods).map((k) =>
    `<button type="button" class="lab-subnav-tab lab-sigkelly-period-btn${k === period ? " active" : ""}" data-period="${k}">${periods[k]}</button>`
  ).join("");
  const modes = cfg.sell_modes || {};
  const modeStr = Object.keys(modes).map((k) => modes[k] ? `${k}:${_sigKellyModeLabelWith(k, modes[k].label)}` : k).join(" · ");
  // 费率预设按钮
  const curFee = state.labSigKellyFeePreset || "etf_main";
  const feeBtnsHTML = KELLY_FEE_PRESETS.map((p) => {
    const active = p.key === curFee ? " active" : "";
    const title = p.desc || "";
    return `<button type="button" class="lab-sigkelly-fee-btn${active}" data-fee="${p.key}" title="${title}">${p.shortcut}:${p.label}</button>`;
  }).join("");
  // 费率输入区(始终显示: 预设档=快捷填入表单, 自定义档=手输任意值)
  const fp = state.labSigKellyFeeParams || {};
  const commVal = fp.commission_rate != null ? (fp.commission_rate * 10000).toString() : "3";
  const minVal = fp.min_commission != null ? fp.min_commission.toString() : "5";
  const slipVal = fp.slippage != null ? (fp.slippage * 1000).toString() : "1";
  const transferVal = fp.transfer_fee_rate_sh != null ? (fp.transfer_fee_rate_sh * 10000).toString() : "0.1";
  const stampVal = fp.stamp_duty_rate != null ? (fp.stamp_duty_rate * 10000).toString() : "0";
  const customHTML = `<div class="lab-sigkelly-fee-custom">` +
      `<label>佣金:万分之<input type="number" class="lab-input lab-sigkelly-fee-input-comm" value="${commVal}" step="0.01" min="0" style="width:48px"></label>` +
      `<label>最低:<input type="number" class="lab-input lab-sigkelly-fee-input-min" value="${minVal}" step="0.1" min="0" style="width:42px">元</label>` +
      `<label>滑点:千分之<input type="number" class="lab-input lab-sigkelly-fee-input-slip" value="${slipVal}" step="0.1" min="0" style="width:42px"></label>` +
      `<label>过户费:万分之<input type="number" class="lab-input lab-sigkelly-fee-input-transfer" value="${transferVal}" step="0.01" min="0" style="width:42px">(沪)</label>` +
      `<label>印花税:万分之<input type="number" class="lab-input lab-sigkelly-fee-input-stamp" value="${stampVal}" step="0.01" min="0" style="width:42px">(卖)</label>` +
    `</div>`;
  // 降亏过滤toggle(58个独立checkbox可组合(X1 加入后, 2026-08-24; 原"31个"系T1扩池时未跟新的过时计数), 其中7个默认推荐(AI宏)在4大分类组内标⭐, 单一事实来源 _kellyFadeFlagGroups; 开启后过滤交易集重算所有指标, 组内按比值降序)
  const _filters = state.labSigKellyFilters || _kellyDefaultFilters();
  // 组合降亏「预设宏」(4个, 2026-08-11新增): 2026-08-13 融合 #39 改为顶部快捷按钮行, 一键勾选/取消全部成员toggle, 勾选态由成员派生(见 _kellyRefreshComboStates)
  const comboHTML = Object.keys(_kellyComboPresets).map((ck) => {
    const cp = _kellyComboPresets[ck];
    return `<button type="button" class="lab-sigkelly-toggle-combo lab-sigkelly-toggle-combo-${ck}" data-no-pop="" title="${cp.tip}">${cp.label}</button>`;
  }).join("");
  // 4大分类组(2026-08-14 重写; v1.1.5 高亮区改 NEW14 十四键); 渲染结构改为「默认推荐高亮区(rec=true 真实 toggle + 1类回测剔除只读) + 更多开关折叠区」:
  //   - f.advice = 白话1句(可见文本, 默认即看, 含 ratio)
  //   - f.tip    = 完整每日池口径细节(ⓘ data-tip hover 弹层)
  //   - warn 前缀联动色块: 绿=推荐/黄=⚠监控/红=⚠慎用(破坏性)
  // 组内按 ratio 降序; 默认推荐 NEW14 十四键(⭐ rec:true, hist6+规则8, v1.1.5) 独立成块置顶, 非默认(含旧八键移出的5键)收「更多开关」折叠区
  const _kellyAllFlags = [];
  _kellyFadeFlagGroups.forEach((g) => { _kellyAllFlags.push(...g.flags); });
  const _kellyRecFlags = _kellyAllFlags.filter((f) => f.rec);
  const _kellyMoreFlags = _kellyAllFlags.filter((f) => !f.rec);
  // P2-4 fix(2026-08-15): ratio 非数值(如 K2C5/K3 的"待实测"字符串/null)参与减法会产 NaN 使组内排序失效且无限期乱序;
  //  归一为 -1(置底), 数值正常降序, 待实测键固定排组内最后(未验证不冒充高比值), NaN 消除排序确定。
  const _kellyRatioSortVal = (r) => (typeof r === "number" ? r : -1);
  const _fadeWarnCls = (f) => {
    if (f.warn) {
      if (/慎用/.test(f.warn)) return " lab-sigkelly-fade-warn-red";
      return " lab-sigkelly-fade-warn-yellow";
    }
    return f.rec ? " lab-sigkelly-fade-warn-green" : "";
  };
  // v1.1.2 红色 NEW 徽章(2026-08-18 用户定: 🆕 emoji 浏览器兼容差, 改红色 NEW 小徽章; 与「⚠️慎用红」区分=红底白字小徽章, 非整行警示)
  const _kellyNewBadge = '<span class="lab-sigkelly-toggle-new">NEW</span>';
  const _kellyAdviceHtml = (advice) => advice.replace(/^🆕/, _kellyNewBadge + " ");
  const _flagToggleHTML = (f) => {
    return `<label class="lab-sigkelly-toggle${f.rec ? " lab-sigkelly-rec" : ""}${_fadeWarnCls(f)}" tabindex="0" data-no-pop="" data-tip="${f.tip}">` +
      `<input type="checkbox" class="${f.cls}"${_filters[f.k] ? " checked" : ""}>` +
      (f.rec ? _kellyRecBadge(!!_filters[f.k]) : "") +
      (f.linked ? `<span class="lab-sigkelly-toggle-linked">🔗AI宏14键</span>` : "") +
      `<span class="lab-sigkelly-fade-advice">${_kellyAdviceHtml(f.advice)}</span>` +
      `<span class="lab-sigkelly-toggle-tip" title="${f.tip}">ⓘ</span></label>`;
  };
  // 顶部「怎么用」三行汇总(默认即可/进阶调法/别做啥), 用户不必读长 tip
  const fadeHowHTML =
    `<div class="lab-sigkelly-fade-how">` +
      `<span class="lab-sigkelly-fade-how-row lab-sigkelly-fade-how-ok"><b>✅ 默认即可</b> 默认基座已切 S06·大盘领先切换(v1.1.7 起, 动态按日切 A进攻王/NEW14+1 键集+AI仓位K=1主推), 别动下面开关; 信号枯竭≥20交易日会出提示 chip</span>` +
      `<span class="lab-sigkelly-fade-how-row lab-sigkelly-fade-how-mid"><b>🛠 进阶调法</b> 旧默认八键(v1.1.4 及以前: n2/specialBear/janMidRating/r7/auxCross 等)仍在「更多开关」折叠区可手动开对照; 切换依据=mine28 AUTO 轮动样本外不成立+mine30 记分板 NEW14 第一(全史+122,648 vs 八键+66,530)</span>` +
      `<span class="lab-sigkelly-fade-how-row lab-sigkelly-fade-how-no"><b>⚠ 别做啥</b> 别拿单键老口径比值直接否定 NEW14 组合成员(组合与单开口径不同); B模式(3%止盈)裸开全负</span>` +
      `<span class="lab-sigkelly-fade-how-row lab-sigkelly-fade-how-note"><b>📐 口径说明</b> 本面板所有「降亏 toggle」的减亏/损盈/比值数字=未套「AI仓位建议」K档的<b>原始口径</b>(每笔固定1万, 无仓位上限), 故峰持仓会很大(如 G 模式全关 ≈961万=不可操作) — 比值是「砍掉多少笔亏损单」的抽象指标, 不是实盘资金; 要看可操作资金请看下方「ai长线模式(G/H/I)仓位管理」开关(套 P≤3d 档后峰持仓≤20倍本金)</span>` +
    `</div>`;
  const flagCatHTML = (flags) => flags.map((f) => _flagToggleHTML(f)).join("");
  // 默认推荐独立高亮区(v1.1.0 2026-08-15 定名「基础5」: AI宏组成 5+3+1 = 8键+1类; 高亮9键=基础5+核心3(含K2C5港股追涨, 真实渲染) + 1类只读; 其中 8键=高亮区真实 toggle, +1 类=回测剔除只读标识)
  // D需求(2026-08-15): 标题 7键 → 4+3+1 = 7键+1类回测剔除; C需求: 追加第8个灰色只读开关(disabled, 只展示层/不可勾选, 不参与过滤/持久化/组合三态); v1.1.0 补充: K2C5 并回 AI宏组成(第8键→定名并入基础5), P2-2(2026-08-15 用户拍板=真实高亮9键): K2C5 加 rec:true 已从市场组折叠区提进高亮区真实渲染, 市场组自动去重不再出现, 无双重开关; 标题已体现 8键+1类=9规则
  const plus1DisabledHTML =
    `<label class="lab-sigkelly-toggle lab-sigkelly-rec lab-sigkelly-toggle-disabled" tabindex="-1" data-no-pop="" data-tip="+1 回测剔除类别(只读, 恒展示不可关): AI宏组成 **NEW14 = hist6 + 规则8 + **+1** = **14键+1类**(v1.1.5 起; 旧八键=基础5+核心3 为 v1.1.2~v1.1.4 对照基座); 这里的 +1 = 回测/凯利模型层剔除的一整类信号(波动相关信号 + 未入样本信号, 后端已剔除出回测宇宙)——这类信号虽同属全信号之一, 但按宇宙规则被回测剔除(已剔除出回测宇宙), 故 AI建议 一律不推荐, 首页/本区以「未入样本」+灰显+删除线标注。含类别=债类 / 情绪类 / 全球商品利率 / 港股行业 / 无ETF的空类别(权威=官方入样规则, §23.6)。此开关仅为界面上看得到的只读标识, 不参与过滤不写入本地记忆, 恒为展示态。" style="opacity:1">` +
      `<input type="checkbox" class="lab-sigkelly-toggle-plus1" disabled checked>` +
      `<span class="lab-sigkelly-fade-advice">+1 回测剔除类别(不可关)</span>` +
      `<span class="lab-sigkelly-toggle-tip" title="+1 回测剔除类别(只读, 恒展示不可关): AI宏组成 **NEW14 = hist6 + 规则8 + **+1** = **14键+1类**(v1.1.5 起; 旧八键=基础5+核心3 为 v1.1.2~v1.1.4 对照基座); 这里的 +1 = 回测/凯利模型层剔除的一整类信号(波动相关信号 + 未入样本信号, 后端 _bt_in_universe=false)——这类信号虽同属全信号之一, 但按宇宙规则被回测剔除, 故 AI建议 一律不推荐, 首页/本区以「未入样本」+灰显+删除线标注。含类别=债类 / 情绪类 / 全球商品利率 / 港股行业 / 无ETF的空类别(权威=官方入样规则, §23.6)。此开关仅为界面上看得到的只读标识, 不参与过滤不写入本地记忆, 恒为展示态。">ⓘ</span>` +
    `</label>`;
  const recZoneHTML =
    `<div class="lab-sigkelly-toggle-group lab-sigkelly-toggle-group-rec">` +
      `<span class="lab-sigkelly-toggle-tier">✅ 默认推荐(AI降亏过滤, v1.1.5 起 NEW14: hist6+规则8 = 14键 + 1类回测剔除, 全部真实高亮渲染 + 1类只读)</span>` +
      flagCatHTML(_kellyRecFlags.slice().sort((a, b) => _kellyRatioSortVal(b.ratio) - _kellyRatioSortVal(a.ratio))) +
      plus1DisabledHTML +
    `</div>`;
  // E需求(2026-08-15): 组合降亏行(logic前原顶部常驻)收纳进本「更多开关」折叠区 body 顶部, 保留点击一键勾选/取消成员功能(无键盘快捷键); 顶部原插入点移除见下方注释
  const comboFoldHTML =
    `<div class="lab-sigkelly-toggle-group lab-sigkelly-toggle-group-combo"><span class="lab-sigkelly-toggle-tier">组合降亏(可选分析非默认推荐)</span>` + comboHTML + `</div>`;
  // 更多开关折叠区(非默认24键 + 组合行收纳顶部 + 4大分类组标题可收展)
  const moreZoneHTML =
    `<details class="lab-sigkelly-toggle-more"${state.labSigKellyMoreOpen ? " open" : ""}>` +
      `<summary class="lab-sigkelly-toggle-more-summary">🔎 更多开关(非默认, ${_kellyMoreFlags.length} 个独立 toggle · 按4大经济逻辑分类) <span class="lab-sigkelly-toggle-cat-caret">▼</span></summary>` +
      `<div class="lab-sigkelly-toggle-more-body">` +
        comboFoldHTML +
        // 问题2修复(2026-08-15): 更多开关区只渲染非默认(非rec) flags, 与顶部「默认推荐8键」区去重 —— 过滤掉 f.rec 的成员, 组标题 count 用过滤后长度, 过滤后空组跳过; K2C5 标 rec 后自动从市场组移出, 不多线渲染
        _kellyFadeFlagGroups.map((g) => {
          const flagsNoRec = g.flags.filter((f) => !f.rec);
          if (flagsNoRec.length === 0) return "";
          const flagsSorted = flagsNoRec.slice().sort((a, b) => _kellyRatioSortVal(b.ratio) - _kellyRatioSortVal(a.ratio));
          // 举一反三(2026-08-15): 4大分类组 手工收/展态持久化到 state.labSigKellyCatCollapsed(记录收起的组 key 集合), 重渲染后保持用户手工收展, 默认仍全展开不破坏原设计
          const catCollapsed = !!(state.labSigKellyCatCollapsed || {})[g.key];
          const catCaret = catCollapsed ? "▶" : "▼";
          return `<div class="lab-sigkelly-toggle-group lab-sigkelly-toggle-group-cat" data-cat="${g.key}">` +
            `<span class="lab-sigkelly-toggle-tier lab-sigkelly-toggle-tier-cat" data-cat="${g.key}" title="点击收起/展开该组">${g.title}(${flagsNoRec.length}) <span class="lab-sigkelly-toggle-cat-caret">${catCaret}</span></span>` +
            `<div class="lab-sigkelly-toggle-cat-body${catCollapsed ? " collapsed" : ""}" data-cat="${g.key}">${flagCatHTML(flagsSorted)}</div>` +
            `</div>`;
        }).join("") +
      `</div>` +
    `</details>`;
  // positionCap 仓位控制过滤(2026-08-12): 同日只买最优K个(基笔级,10模式共享统一生效), K档位1-4可配置(默认3, 2026-08-13定默认)
  // 2026-08-12 #4 rename+范围扩展: 显示名改"AI仓位建议"(技术别名:仓位控制过滤), pop tooltip 完整展示; 历史回测数据固化展示(下方 poscapHistoryHTML)
  const _pcK = _filters.positionCapK || 1;
  // 2026-08-13: K档位评级标注 + hover 评级理由表格(展示层, 不改算法; 数据=共享单一数据源 common.js window._AI_POSCAP_RATING, §22 与首页 app.js 一致, 勿单改数值)
  // 口径=AI宏默认3元(r7 5月强化+3稳定非5月/exclAuxCross 辅关注×3/5月交叉/greedy15)+A模式(固定10天)+每日资金池等分+top-K +费率etf_main(ETF主流, 2026-08-14 默认改)+全周期, 与 AI宏 hoverpop 口径一致
  // 2026-08-14 #48+#BC: 静态快照由 fixed(比例法) 重算为每日池+费率重算口径(含最低佣金5元, 与动态 _kellyApplyFeeRecompute 一致 §22); §22 与 common.js _AI_POSCAP_RATING/首页 app.js tooltip 三处一致; 主推 K1
  const _pcRating = window._AI_POSCAP_RATING || {
    1: { name: "最激进", ret: "86.60%", dd: "15.99%", ra: "5.42", n: "1,202", reason: "收益率最高+回撤最小+样本最少,主推★" },
    2: { name: "次稳健", ret: "67.61%", dd: "18.64%", ra: "3.63", n: "1,930", reason: "收益率最低+回撤最大" },
    3: { name: "最稳健", ret: "66.24%", dd: "16.19%", ra: "4.09", n: "2,461", reason: "回撤第二大+收益率第三(收益/回撤较优)" },
    4: { name: "最保守", ret: "63.17%", dd: "17.84%", ra: "3.54", n: "2,870", reason: "收益率第二低+回撤第二大+样本最多" }
  };
  // 2026-08-13 调序+OFF: 对齐首页「AI仓位建议 K:」布局 —— 精简标题(技术别名/口径全进 data-tip) + K 按钮组加 OFF(写 tds_poscap {on:false} 退化普通列表, 再点某 K 档恢复, §22 与首页/交易页共享键联动)
  // 2026-08-14 #BC C包: 主推 K1 → K 按钮 1 排首位+高亮
  const _pcKbtns = [1, 3, 4, 2].map((k) => {
    const r = _pcRating[k];
    return `<button type="button" class="lab-sigkelly-kbtn${(_filters.positionCap && k === _pcK) ? " active" : ""}${k === 1 ? " lab-sigkelly-kbtn-main" : ""}" data-k="${k}" data-no-pop=""><span class="lab-sigkelly-kbtn-k">${k}</span><span class="lab-sigkelly-kbtn-r">${r.name}${k === 1 ? "★主推" : ""}</span></button>`;
  }).join("");
  // OFF 按钮(2026-08-13, 复用首页同款交互): data-k="off" 由下方 K 按钮绑定识别为关(写 tds_poscap {on:false}), 关闭后该区退化普通列表, 再点某 K 档恢复
  const _pcOffBtn = `<button type="button" class="lab-sigkelly-kbtn lab-sigkelly-kbtn-off${_filters.positionCap ? "" : " active"}" data-k="off" data-no-pop=""><span class="lab-sigkelly-kbtn-k">关</span><span class="lab-sigkelly-kbtn-r">off</span></button>`;
  const _pcRatingPop = (window._aiPoscapRatingPopHtml ? window._aiPoscapRatingPopHtml() : "");
  // 2026-08-13 合并行: AI宏 总开关(原第二行)合并进 AI仓位建议 行, 跟在「关OFF」按钮后(用户需求: 两行合并一行, 去除重复纯文字标题)
  // 本 label+详情按钮 在 positionCapHTML 内复用, 原 .lab-sigkelly-toggle-group-ai 独立行已移除(仅 CSS 残留无引用)
  // #54 2026-08-13 bug1修复: 总开关联动扩到 _kellyAiMacroMembers; v1.1.0(2026-08-15) 扩到 8成员含K2C5(基础5+核心3), v1.1.5 起联动集合=NEW14 十四键, 三态/badge 由当前默认档键集派生
  const _aiMacroAll = (function () {
    var f = state.labSigKellyFilters || _kellyDefaultFilters();
    var allOn = true, anyOn = false;
    for (var i = 0; i < _kellyAiMacroMembers.length; i++) { if (f[_kellyAiMacroMembers[i].k]) anyOn = true; else allOn = false; }
    return { allOn: allOn, anyOn: anyOn };
  })();
  const aiMacroLabelHTML =
    `<label class="lab-sigkelly-toggle lab-sigkelly-rec" tabindex="0" data-no-pop="" data-tip="⭐ AI降亏过滤(总开关, 默认开启): v1.1.7 起默认基座=S06·大盘领先切换(动态模式, 按大盘风格按日切 A进攻王/NEW14+1); 原 v1.1.5(2026-08-24 用户拍板)~v1.1.6 历史默认=NEW14(NEW 14键, 现为可回选静态对照档)——构成=hist 键 6(5月+6非5月 r10 / Greedy-15 / 1月中旬+追关注 / K2C5 港股追涨 / 主关注×概念 k3 / 下降期×追关注)+规则键 8(N1 北向20日净流出 / T1 换手冰点×追关注 / D1 股息率低位 / Q1 QVIX低分位 / H1 升波×A股 / M1 牛主升×两融降温 / P1 备买×股息率分位低 / R2b 追关注×全球类), 共 14 键; +1=回测/凯利模型层剔除的一整类信号(波动相关信号+未入样本信号, 债类/情绪类/全球商品利率/港股行业/无ETF的空类别, 已剔除出回测宇宙)——这类信号虽同属全信号之一, 但按宇宙规则被回测剔除, 故 AI建议 一律不推荐, 以「未入样本」+灰显+删除线标注。【切换依据】mine28(AUTO 状态轮动样本外全 FAIL, 维持单模式)+mine30 记分板(NEW14 全史第一 +122,648/mdd -4,178 vs 八键 +66,530/-18,190, 费后 K1 V2 回补 cap13 口径); 权威数字见下方「🧩 AI 降亏组成对比」卡。仅买信号判降亏(§23.6 MED3): 删线只针对买入信号, 非买(${_t("sell_short")}/${_t("type_sell_stop_loss")}/${_t("band_hold")}等)不判降亏, ${_t("buy_special")}(被过滤)归入 ${_t("buy_special")} 判。= AI仓位建议(K=1 默认=主推) + 默认组合(当前默认基座=S06 动态, 按快照日套 A进攻王/NEW14+1 键集 + 1类回测剔除)。勾选=联动下方 NEW14 高亮14键子复选框 + 1类只读, 取消=关14键; 旧八键(v1.1.2 基座, 含 n2/janMidRating/r7/exclAuxCross/exclSpecialBear 五个已移出默认的键)经旁侧「模式」下拉选「8键」一键回选, 未删档可随时切回对照。「模式」下拉(T3-1 2026-08-23; v20260826 用户拍板加⭐推荐星标+按星排序: S06 3星/A进攻王·NEW 14键·NEW14+1·15键 2星/9键·B均衡卡 1星, 星多靠前、无星殿后沿用原相对序)=8 种预设一键套用(⭐️⭐️⭐️S06 · 大盘领先切换(动态)/⭐⭐A进攻王/⭐⭐NEW 14键/⭐⭐NEW14+1·15键/⭐9键/⭐B均衡卡/C防守/8键旧默认·对照; NEW2 18键对照档已从下拉与「🧩 AI 降亏组成对比」区移除——用户拍板"不用对照啦 14+1 对照够啦"(2026-08-26 对比区卡亦删, 原始数字存 mine24_compare.json); 其中 NEW14+1·15键=可选档非默认, mine29c 2026-08-24 用户拍板: NEW14 十四键全保留+整剔有跟踪ETF象限(none/null, X1 同日扩围与首页口径统一), 全史净利 +122,705 vs NEW14 +122,648(+57 噪声级·扩围前历史数字待重算), mdd -4,178→-3,550 浅 15%(同扩围前)——回撤改善是唯一真实正效用, bootstrap 全窗含0 不显著), 选中即整套键组合写入下方标签勾选态并重算; 手动勾/取消任一小标签→进入「⚙️自定义组合」态; 再选任意模式回到预设; 模式记忆存 tds_kelly_fade_mode(lab 独立键, 仅保留 18 小时滑动过期——每次切换刷新计时, 超时自动回默认 s06·动态(当前默认基座); 与模拟回测弹窗/首页/监控卡的记忆互不干预)。「重置为AI默认推荐」按钮=一键恢复本默认(当前默认基座=S06 动态模式, 按大盘风格按日切 A进攻王/NEW14+1, 含 1类回测剔除; NEW14 为 v1.1.5~v1.1.6 历史可回选档) + AI仓位建议K=1 并重写本地记忆。枯竭提示(v1.1.5 新增): NEW14 年均约 2.4 次 ≥20 交易日无放行(信号枯竭=其常态运作方式), 凯利区信号区顶部有实时枯竭提示 chip, 历史上类似枯竭结束后 3 个月约 72% 为正(mine30 §五)。"><input type="checkbox" class="lab-sigkelly-toggle-aimacro"${_aiMacroAll.allOn ? " checked" : ""}>${_kellyRecBadgeState(_aiMacroAll.allOn, _aiMacroAll.anyOn)} AI降亏过滤(总开关,默认开启) <span class="lab-sigkelly-toggle-tip">ⓘ</span></label>`;
  // 问题1修复(2026-08-15): AI降亏过滤详情 展开/收起 初始态持久化到 state.labSigKellyAiDetailOpen(参照 labSigKellyMoreOpen 模式), 重渲染后保持展开态
  const _aiDetailText = state.labSigKellyAiDetailOpen ? "AI降亏过滤详情收起 ▲" : "AI降亏过滤详情展开 ▼";
  const aiMacroDetailBtnHTML =
    `<button type="button" class="lab-sigkelly-toggle-detail-btn" id="lab-kelly-ai-macro-btn" style="margin-left:10px;padding:2px 10px;border:1px solid #888;border-radius:4px;background:transparent;cursor:pointer;color:inherit" title="收起/展开下方 组合降亏快捷按钮 + 58个单标志(4大分类组), 默认收起">${_aiDetailText}</button>`;
  // #54 2026-08-13 (用户20:27 必做): 「重置为AI默认推荐」按钮——尝试各种组合后一键恢复 AI默认勾选(_kellyDefaultFilters 默认档全开, v1.1.7 起=当前默认基座 S06 动态模式+AI仓位建议K=1), 重写 tds_kelly_filters 持久化, 刷新三态/hoverpop动态值
  const aiMacroResetBtnHTML =
    `<button type="button" class="lab-sigkelly-toggle-detail-btn" id="lab-kelly-ai-macro-reset" style="margin-left:8px;padding:2px 10px;border:1px solid #888;border-radius:4px;background:transparent;cursor:pointer;color:inherit" title="一键恢复 AI 默认推荐勾选(v1.1.7 起=当前默认基座 S06 动态模式, 按大盘风格按日切 A进攻王/NEW14+1, 含 1类回测剔除, 其中+1类只读不可勾选; + AI仓位建议 K=1), 重写本地记忆并刷新统计">重置为AI默认推荐</button>`;
  // T3-1(2026-08-23): AI降亏模式下拉(7预设一键套用) —— 总开关保留, 原「多选标签直选」升级为「模式预设+细粒度自定义」双层;
  // 选下拉=一键套用该模式完整键组合(标签勾选态由 _kellyOnFilterChange 完成回调重渲染 bar 自动点亮);
  // 手动勾/取消任一标签 -> _tdsFadeModeMatch 反查不匹配任何预设 -> 下拉显示「自定义」占位态(option disabled hidden 仅展示);
  // 再点任意模式 -> 回到预设。持久化=lab 独立 key tds_kelly_fade_mode(a389 三处独立化纪律), 默认模式=v1.1.5 起 new14(旧默认 p8 八键保留为对照档可手选)。
  var _fadeMatchedId = (window._tdsFadeModeMatch ? window._tdsFadeModeMatch(_filters) : null);
  // S06(codex-task-20260825-001, handoff §五.功能3): 动态键集不参与反查(Match 跳过 dynamic 预设)——
  // s06 态且标签区仍停在参考底座(反查=当前默认档, 即未被手动动过)时显示 S06; 手动勾/取消任一标签后
  // 反查≠默认档 → 自然落「⚙️自定义组合」态(判定层同步退出 s06, 见 _kellyOnFilterChange 入口清除)
  // v1.1.8 fix: S06 基座可能是 new14/9键/A进攻王等, 反查结果=基座ID≠"s06"; 只要 state.labSigKellyFadeModeBase
  // 是 s06 且 filters 未被手动改动(反查匹配某个预设, 不是 null=自定义), 就显示 s06 选中态。
  var _isS06Base = (state.labSigKellyFadeModeBase === "s06");
  if (_isS06Base && _fadeMatchedId && _fadeMatchedId !== "custom") {
    _fadeMatchedId = "s06";
  } else if (_fadeMatchedId === (typeof window._KELLY_FADE_DEFAULT_MODE === "string" ? window._KELLY_FADE_DEFAULT_MODE : "new14")
    && _isS06Base) {
    _fadeMatchedId = "s06";
  }
  const _fadeBaseId = state.labSigKellyFadeModeBase || (typeof window._KELLY_FADE_DEFAULT_MODE === "string" ? window._KELLY_FADE_DEFAULT_MODE : "new14");
  const _fadeDisp = (window._tdsFadeModeById ? window._tdsFadeModeById(_fadeMatchedId || _fadeBaseId) : null) || { name: "NEW 14键", caliber: "", calWarn: false };
  const _fadeCaliberHTML = _fadeMatchedId
    ? _fadeDisp.caliber
    : ("⚙️ 自定义组合(基于「" + _fadeDisp.name.replace(/\(默认\)$/, "") + "」手动调整, 口径见各标签 tip)");
  const fadeModeTitle = "AI降亏过滤模式: 一键套用整套键组合(与「AI 降亏组成对比」卡同源口径); ⭐=推荐星标(S06 3星 / A进攻王·NEW14·NEW14+1 2星 / 9键·B均衡卡 1星), 下拉星多靠前、无星殿后沿用原相对序(v20260826 用户拍板); NEW2 18键对照档已从下拉移除(同日拍板\"不用对照啦\", 其组成对比区卡 2026-08-26 亦删——\"18和14键差异太小了\")。手动勾/取消下方任一小标签即进入自定义态, 再选任意模式回到预设。选 S06=按大盘风格按日动态切换 A进攻王/NEW14+1 两套判断规则(v1.1.7 起已为当前默认基座, 判定层自动接管、标签区退为参考底座); 如果 S06 快照读不出来, 这笔信号就照常展示并在旁边标红字提醒, 但不会悄悄换成其他模式——简单说就是\"能正常显示就显示, 读不出来就老实告诉你, 绝不替你做决定偷偷切走\""
    + (typeof window._tdsS06Tooltip === "function" ? ("\n———\n" + window._tdsS06Tooltip()) : "");
  // S06 快照降级警示 span(可见不静默): 文本来自最近一次计算 result._s6warn(_kellyApplyFeeRecompute 写),
  // 无警示恒隐藏; 缓存命中路径随旧 stats 一致复用同文案(§22)
  const _s6StateWarn = (state.labSigKellyFeeStats && state.labSigKellyFeeStats._s6warn) || "";
  // T3-1修复批④(2026-08-23): 类名换公共组件段 .tds-fade-mode-wrap/.tds-fade-mode-sel(style.css 公共段单份,
  // 各页不留私有样式副本); 渲染函数=common.js _tdsFadeModeSelectHTML/_tdsFadeModeSelectMount 四消费点统一组件。
  // T3-1修复批③(2026-08-23): 本下拉落点移至「AI降亏过滤」总开关文字同一行紧跟其后(用户铁律: 一个功能的交互不拆两处),
  // 由下方 positionCapHTML 中 aiMacroLabelHTML + fadeModeHTML 相邻拼接保证。
  const fadeModeHTML =
    `<span class="tds-fade-mode-wrap">` +
      `<span class="lab-sigkelly-fee-label" style="font-weight:600">模式:</span>` +
      (window._tdsFadeModeSelectHTML ? window._tdsFadeModeSelectHTML("lab-kelly-fade-mode-sel", _fadeMatchedId || "custom", true, "tds-fade-mode-sel", fadeModeTitle) : "") +
      `<span id="lab-kelly-fade-mode-caliber" class="lab-sigkelly-fee-label" title="${fadeModeTitle}"${_fadeDisp.calWarn ? ' style="color:#b45309;font-weight:600"' : ""}>${_fadeCaliberHTML}</span>` +
      `<span id="lab-kelly-s06-state" class="lab-sigkelly-fee-label" style="color:#c0392b;font-weight:600;${_s6StateWarn ? "" : "display:none"}">${_s6StateWarn}</span>` +
    `</span>`;
  const positionCapHTML =
    `<div class="lab-sigkelly-toggle-group lab-sigkelly-toggle-group-poscap">` +
    `<label class="lab-sigkelly-toggle lab-sigkelly-rec" tabindex="0" data-no-pop="" data-tip="⭐ 默认推荐(默认开启): AI仓位建议(技术别名:仓位控制过滤)=仅在凯利回测入样宇宙内选择。★结构=v1.1.5 起默认基座 NEW14(十四键, 重构换基座): hist6(r10May6NonMay/greedy15/janMidSpecial/k2c5HkChase/k3ConceptBuy/declinePhaseSpecial)+规则8(N1北向20日净流出/T1换手冰点×追关注/D1股息率低位/Q1 QVIX低分位/H1升波×A股/M1牛主升×两融降温/P1备买×股息率分位低/R2b追关注×全球类)=保留入样、可被AI建议推荐的降亏键; 旧八键(基础5+核心3, v1.1.2~v1.1.4 默认)保留为手动可开对照档; +1=回测/凯利模型层剔除的一整类信号(波动相关信号+未入样本信号, 即下述排除类别)——这类信号虽同属全信号之一, 但按宇宙规则被回测剔除(已剔除出回测宇宙), 故 AI建议 一律不推荐, 首页/本区以「未入样本」+灰显+删除线标注。§23.6 入样宇宙规则, 权威=官方入样规则: 入样白名单只收买入类信号: ${_t("type_buy")}/${_t("buy_aux")}/${_t("buy_special")}/${_t("buy_backup")}; 入样依赖=标的有ETF跟踪且有跟踪分(即回测入样判定); 排除类别=债类/情绪类/全球商品利率/港股行业/无ETF的空类别; 自我ETF唯一例外=10年国债ETF 由 self-ETF 兜底; 首页/本区 1:1 遵从回测入样判定不自行重算), 卖类(${_t("sell_short")}/${_t("type_sell_stop_loss")}/${_t("type_band_sell")}/${_t("band_hold")})不入位——同日只买最优K个买入类信号(基笔级, 按 跟踪分↓→评级high&gt;mid&gt;low→信号类型${_t("buy_backup")}&gt;${_t("type_buy")}&gt;${_t("buy_aux")}&gt;${_t("buy_special")}→买入日↑ 排序保留前K, 9卖出模式共享同一批基笔统一生效)。目标=资金利用率最大化(降低最大持仓), 非质量过滤。**K档评级(2026-08-13 #54 动态化: 随当前降亏勾选/费率档/最新数据实时重算, 与首页/凯利K按钮评级 hoverpop 同源 common.js, §22 一致)**: ${_aiPoscapRatingSummary()}。主推 K1(收益率最高 86.60%); K越大收益率递减(K2=67.61%/K3=66.24%/K4=63.17%, 含最低佣金5元费率重算口径)。每日池口径下 K 越大净利反升(每日资金池恒定, 砍量越少持仓越多)。G模式历史口径(关32.27%/K1 48.58%/K2 40.41%/K3 38.96%等, 每笔固定1万·positionCap单独回测未叠加AI降亏过滤)为已废弃的旧口径(2026-08-13 起默认=每日资金池等分), 以本 K 档评级 hoverpop(每日池+top-K, 实时随勾选动态)与下方「全信号表 · 按年窗口增长」表(每日池实时, 可切 G 并跟 K 档联动)为准, 旧口径数值不再单独公示。OFF按钮(关)=写 tds_poscap {on:false} 关闭AI仓位建议、该区退化普通列表(不再显示「AI建议N」「当日已满」), 再点某 K 档恢复 {on:true,k}(与首页/交易页共享键联动)。与降亏同开仅推荐默认组合(v1.1.5 起 AI降亏过滤默认=NEW14 十四键: hist6=r10May6NonMay/greedy15/janMidSpecial/k2c5HkChase/k3ConceptBuy/declinePhaseSpecial + 规则8=n1NorthOutflow/t1LowTurnSpecial/d1LowDivYield/q1QvixLowPct/h1VolChgHighA/m1MarginDownBull/p1LowDivBackup/r2bSpecialGlobal, 每日池+K=1下边际≈0无害); ⚠绝不同开 live4(双重砍量收益率崩2-5%)/COMBO4全开; 勿再叠加 greedy7/10 等其他广谱(greedy15 已在 NEW14 默认内); B模式(3%止盈)仓位控制下转负建议关。范围扩展: 交易页整个信号列表(近30交易日, 2026-08-24 由15扩30)按同一排序展示 AI建议(AI建议买入/当日已满)。⚠2026-08-14 首页「AI过滤视图」两开关正交不绑定(§21): 开关1「AI降亏」(tds_home_fade)=删除线过滤层——开启时未入样宇宙(债类/情绪类/全球商品利率/港股行业/无ETF的空类别, 已剔除出回测宇宙)信号=删线+灰显+「未入样本」标注; 开关2「AI仓位」(tds_poscap.on)=badge标注层——开启时入宇宙${_t("sell_short")}(${_t("sell_short")}/${_t("type_sell_stop_loss")}/${_t("type_band_sell")})=亮色「AI警示」(${_t("sell_short")}无K约束不判K), 买入进K=「AI建议N」/超K=「当日已满」; 全关=全量视图全亮不标注, band_hold波段持有=中性不标; 迟到入宇宙${_t("sell_short")}(如8/14中证银行${_t("sell_short")})「AI警示」+「盘后补齐」角标共存不冲突。"><input type="checkbox" class="lab-sigkelly-toggle-poscap"${_filters.positionCap ? " checked" : ""}>${_kellyRecBadge(_filters.positionCap)} AI仓位建议 K: <span class="lab-sigkelly-toggle-tip">ⓘ</span></label>` +
    `<span class="lab-sigkelly-kbtns lab-sigkelly-posrate" tabindex="0">${_pcKbtns}${_pcOffBtn}${_pcRatingPop}</span>` +
    // 修复批③: 模式下拉紧跟「AI降亏过滤」总开关文字(同一 flex 行, 不再拆到组尾), 细节见上方 fadeModeHTML 注释
    aiMacroLabelHTML +
    fadeModeHTML +
    aiMacroDetailBtnHTML +
    aiMacroResetBtnHTML +
    // v1.1.5 枯竭提示 chip 占位(纯展示层): 异步拉 overfit_monitor.json recent 块计算「连续 N 交易日无放行」,
    //   N≥20 才显示(common.js 单源 _tdsFetchRecentBlock/_tdsComputeDrought/_tdsDroughtChipHtml, 与首页同源 §22)
    `<span class="sig-drought-slot" id="lab-kelly-sig-drought-slot"></span>` +
    `</div>`;
  // #83(2026-08-15): 移除「AI仓位建议 · 历史回测(G模式口径)」面板——每笔固定1万+裸G口径已废弃(现默认=每日资金池等分), 核心结论已被按年窗口增长表(每日池实时)+K按钮评级(common.js)+全信号建议指南完整继承(详见 docs/kelly/position/kelly-poscap-history-panel-removal-check.md)
  // #49+#xx ai长线模式(G/H/I)仓位管理: 按钮(长线族群总入口, 默认关, v2 三模式独立策略; 架构支持后续按模式独立换策略)
  // 数据定稿: G=P≤3d@13万 定稿单档(kelly-g-mode-recheck.md) / H=满仓不买7万 / I=满仓不买16万(kelly-ghi-continuous-cap-sweep.md)
  // 对比表口径=推荐 K=1 版(报告权威 b0 保守/乐观 b1); tooltip 白话文案按模式分写(架构要求: 说明文案按模式区分)
  const _gihOn = !!state.labSigKellyGihOn;
  const _gihGTierCur = _kellyGihGTier();
  // 对比表数据(报告权威值, §21 公示; 各模式当前所选策略的开关前后对比)
  // G 固定单档 13万(2026-08-29 codex#001 定稿), H/I 为各自满仓不买最优档(手段A 无强平→b0=b1)
  const _gihGTierB = {
    "13万": { b0: ["188.88%", "+24.6万", "13万"], b1: ["188.88%", "+24.6万", "13万"] } // v1.1.7 基准定稿单值, b0=b1 同值
  };
  const _gihRefRows = [
    { m: "G", mName: "G · 卖出信号中长线", strat: "P≤3d " + _gihGTierCur, off: ["47.2%", "+64.2万", "136万"],
      b0: _gihGTierB[_gihGTierCur].b0, b1: _gihGTierB[_gihGTierCur].b1 },
    { m: "H", mName: "H · 卖出+追止损中长线", strat: "满仓不买@7万", off: ["34.3%", "+15.4万", "45万"],
      b0: ["206.76%", "+14.5万", "7万"], b1: ["206.76%", "+14.5万", "7万"] },
    { m: "I", mName: "I · 追关注加追止损中长线", strat: "满仓不买@16万", off: ["39.5%", "+43.9万", "111万"],
      b0: ["127.64%", "+20.4万", "16万"], b1: ["127.64%", "+20.4万", "16万"] }
  ];
  // #88(2026-08-15): G/H/I 对比表改「横向布局」——三模式(G/H/I)作为列横向并排铺满宽度, 行方向=「场景(关/开b0/开b1)×指标(收益率/净利/所需本金)」。
  //   原纵向 rowspan=3 只占屏幕左侧小篇幅→转置为 模式列铺开, 用户诉求(横向+占满宽度)达成。数据源 _gihRefRows 零改动(3模式×关/开b0/开b1×3指标 全保留, §5.3核心保障)。
  //   展示顺序: 关(基线)→开(保守b0)→开(乐观b1) 各三行, 表头首列=场景·指标(行标签), 后3列=G/H/I三模式(列首显 m+strat)。
  const _gihColHead =
    `<colgroup><col class="lab-sigkelly-gihc-row"><col class="lab-sigkelly-gihc-mode"><col class="lab-sigkelly-gihc-mode"><col class="lab-sigkelly-gihc-mode"></colgroup>` +
    `<thead><tr><th class="lab-sigkelly-gihc-corner">模式</th>` +
      _gihRefRows.map(function (r) {
        return `<th class="lab-sigkelly-gihc-mode-th"><b>${r.m}</b><span class="lab-sigkelly-modelbl">${r.mName.replace(/^[A-Z] · /, "")}${r.strat ? " · " + r.strat : ""}</span></th>`;
      }).join("") +
    `</tr></thead>`;
  const _gihScene = [
    { key: "off", label: "关(基线)" },
    { key: "b0", label: "开(保守 b0)" },
    { key: "b1", label: "开(乐观 b1)" }
  ];
  const _gihMetric = [
    { k: 0, label: "收益率", cls: "lab-sigkelly-pos" },
    { k: 1, label: "净利", cls: "lab-sigkelly-pos" },
    { k: 2, label: "所需本金", cls: "" }
  ];
  // 场景行间隔分组: 首列带横向分隔, 区分 关基线/开b0/开b1 三大组; 每组内 3 个指标行连续排列, 一一对应 3 模式同列
  const _gihGroups = _gihScene.map(function (sc, si) {
    const first = si === 0 ? " lab-sigkelly-gihc-scene-first" : "";
    // #88fix(2026-08-15, P1 reviewer): map 返回数组必须先 join 成串, 否则外层 .join("") 在每组 3 行 <tr> 之间插入裸逗号(数组套数组), HTML foster-parenting 把逗号移出表格渲染在表格上方=用户看到 ,,,,,,
    const bodyRows = _gihMetric.map(function (mt) {
      return `<tr class="lab-sigkelly-gihc-tr${first}">` +
        `<td class="lab-sigkelly-gihc-scene-lab">${(mt.k === 0 ? `<b>${sc.label}</b><br>` : "")}<span class="lab-sigkelly-gihc-metric">${mt.label}</span></td>` +
        _gihRefRows.map(function (r) {
          const v = r[sc.key][mt.k];
          return `<td class="${mt.cls} lab-sigkelly-gihc-val">${v}</td>`;
        }).join("") +
      `</tr>`;
    }).join("");
    return bodyRows;
  }).join("");
  const _gihCompareTableHTML =
    `<table class="lab-sigkelly-table lab-sigkelly-advice-table lab-sigkelly-gih-table">` +
      _gihColHead +
      `<tbody>${_gihGroups}</tbody>` +
    `</table>`;
  // tooltip 白话文案(v2.1, 按模式分写——G=P≤3d@13万/H=满仓不买7万/I=满仓不买16万)
  const _gihTipG = "【G】定稿档位=" + _gihGTierCur + " → " + _kellyGihStratShort("G") + "「先卖年轻仓」: 超仓先卖持有≤3天新仓(砍掉刚买没攒利润的), 保21-100天利润引擎, 无年轻仓才卖最老。关 47.2%/+64.2万/136万 → 开(现档" + _gihGTierCur + ")乐观" + _gihGTierB[_gihGTierCur].b1[0] + "/净" + _gihGTierB[_gihGTierCur].b1[1] + "。15起始年全胜旧FIFO、随机30点0/30负, b0/b1区间窄可信。定稿只保留 13万单档(收益率全G档最高, 峰持仓13倍=可操作)。";
  const _gihTip =
    "⭐ ai长线模式(G/H/I)仓位管理(默认开, 2026-08-29 codex#001 定稿): 对 G/H/I 三长线模式各配独立仓位策略(不再统一FIFO)——最终落地为三模式各自最优：\n" +
    _gihTipG + "\n" +
    "【H】满仓不买@7万(手段A): 到7万就停买、不强制平仓, 等自然卖出腾位再买, 中长线选@7万类超低本金可操作。关 34.3%/+15.4万/45万 → 开 206.76%/+14.5万/7万, 7倍本金充分可操作(v1.1.7 基准定稿)。\n" +
    "【I】满仓不买@16万(手段A): 到16万就停买、不强制平仓。关 39.5%/+43.9万/111万 → 开 127.64%/+20.4万/16倍本金。\n" +
    "保守vs乐观: 仅 P 手段(G)有强平日——强平真实盈亏不可知(无中间价格路径), 保守b0=按0利计, 乐观b1=按持有时间线性折算, 真实值在区间, 不把乐观当承诺。H/I 手段A 无强平, b0=b1。\n" +
    "💡 当前页面默认 K=1 主推(2026-08-14 #BC), 对比表亦为推荐 K=1 口径。";
  // G 档位展示(2026-08-29 codex#001 定稿: 只保留 13万单档, 删 15/20 切换按钮; 显示静态标签)
  const aihlineLabelHTML =
    `<label class="lab-sigkelly-toggle lab-sigkelly-rec" tabindex="0" data-no-pop="" data-tip="${_gihTip}">` +
      `<input type="checkbox" class="lab-sigkelly-toggle-gih"${_gihOn ? " checked" : ""}>${_kellyRecBadge(_gihOn)} ai长线模式(G/H/I)仓位管理 <span class="lab-sigkelly-toggle-tip">ⓘ</span> ` +
      `<span class="lab-sigkelly-gih-tier-wrap" title="G 档位定稿 13万(P≤3d 先卖年轻仓, 收益率全 G 档最高 188.88%, 峰持仓 13 倍=可操作, v1.1.7 基准定稿)">` +
        `<span class="lab-sigkelly-gih-tier-lab">G档</span><span class="lab-sigkelly-gih-tier-btn lab-sigkelly-gih-tier-active" data-tier="13万">13万 ✓</span>` +
      `</span>` +
    `</label>` +
    `<button type="button" class="lab-sigkelly-toggle-detail-btn" id="lab-kelly-gih-compare-btn" style="margin-left:8px;padding:2px 10px;border:1px solid #888;border-radius:4px;background:transparent;cursor:pointer;color:inherit" title="收起/展开 G/H/I 仓位管理 开关前后对比表(报告 K=1 参考口径)">G/H/I 对比表 ${_gihCompareOpen ? "▲" : "▼"}</button>`;
  const aihlineCompareHTML =
    `<div id="lab-kelly-gih-compare-body" class="lab-sigkelly-ai-macro-body" style="${_gihCompareOpen ? "" : "display:none"}">` +
      `<div class="lab-sigkelly-toggle-group lab-sigkelly-toggle-group-poscap">` +
        `<div class="lab-sigkelly-advice-li lab-sigkelly-advice-note">G/H/I 仓位管理 · 开关前后对比(推荐 K=1 口径, 前端内核已对齐报告§21)。数据来源 G=「G模式复核」 <button type="button" class="lab-kelly-repo-btn" data-repo-id="kelly-g-mode-recheck">🔍</button> · H/I=「G/H/I连续资金扫描」 <button type="button" class="lab-kelly-repo-btn" data-repo-id="kelly-ghi-continuous-cap-sweep">🔍</button>。G=P≤3d先卖年轻仓@13万(定稿单档, b0/b1区间窄可信), H=满仓不买@7万, I=满仓不买@16万(H/I 手段A 无强平 b0=b1)。收益率=净利÷峰值占用资金; 保守b0=强平按0利计, 乐观b1=按持有时间线性, 真实值在区间。例(G 模式开关前后, K=1 口径)：关(旧FIFO)峰值同时持仓 136 万(136 倍单次本金1万,远超20倍可操作线)→ 即便净利 +64.2万 全模式最高也不可实操;开(现档13万 P≤3d)峰值压到 13 万(13 倍本金,可操作)→ 收益率口径=净利÷峰值占用资金 → 保守 b0 188.88%(净 +24.6万, v1.1.7 基准定稿)【核实源:kelly-g-mode-recheck.md + lab.js _gihRefRows/_gihGTierB】。</div>` +
        `<div class="lab-sigkelly-table-scroll">${_gihCompareTableHTML}</div>` +
        `<div class="lab-sigkelly-advice-li lab-sigkelly-advice-warn">诚实标注: G 的 P≤3d 全面超旧 FIFO(15起始年全胜/随机0/30负/区间窄4-24pp, 强平的为新仓未攒利润); H/I 手段A 无强平完全确定, 但 H 小本金档净利绝对值低(14.5万)可自行放宽; 三模式峰持仓均≤20倍本金=可操作。</div>` +
      `</div>` +
    `</div>`;
  // #78(2026-08-15): 金额口径统一为「每日资金池」(与信息行/建议指南正文一致, 消除旧"每笔固定1万"双口径混乱 §22/§23.3)
  const amountHTML =
    `<span class="lab-sigkelly-fee-label">金额:</span>` +
    `<span class="lab-sigkelly-fee-label" style="font-weight:600">每日资金池 1 万</span>`;
  const toggleHTML = `<div class="lab-sigkelly-toggle-row">` +
      `<span class="lab-sigkelly-toggle-label">过滤:</span>` +
      // 2026-08-13 合并行: AI仓位建议(K档按钮+OFF) 与 AI宏总开关 合并为一行(用户需求: 去重纯文字标题 + 第二行并入第一行「关OFF」按钮后)。
      // 原第二行 .lab-sigkelly-toggle-group-ai 独立行已移除, AI宏 toggle+详情按钮 并入 positionCapHTML 内(见 aiMacroLabelHTML/aiMacroDetailBtnHTML)
      positionCapHTML +
      // #49 ai长线模式(G/H/I)仓位管理行已移出本过滤区 → 2026-08-26 用户拍板移到费率模块后(见下方 bar.innerHTML 的 lab-sigkelly-topgrid/gihcol), 控件与逻辑零变化
      // #39 三级级联UI 第1级: AI宏 详情折叠 body(默认收起, 收起/展开由 #lab-kelly-ai-macro-btn 控制; 展开/收起态持久化到 state.labSigKellyAiDetailOpen, 重渲染后保持; 勾选联动全部8键子级见 _kellyAiMacroMembers, v1.1.0 含K2C5)
      `<div id="lab-kelly-ai-macro-body" class="lab-sigkelly-ai-macro-body" style="${state.labSigKellyAiDetailOpen ? "" : "display:none"}">` +
      // E需求(2026-08-15): 组合降亏行已从顶部移除, 收纳进 moreZoneHTML 更多开关折叠区 body 顶部(见 comboFoldHTML), 不再重复
      // 2026-08-14 重写: 顶部「怎么用」三行 + 默认推荐5+3+1(8键+1类=9规则)高亮区 + 更多开关折叠区(含组合行收纳)
      fadeHowHTML +
      recZoneHTML +
      moreZoneHTML +
      // T2(2026-08-23): AI 降亏组成对比折叠区(纯展示, 8 方案构成+短标语+权威数字; 默认收起, 零交互逻辑 §23.7)
      _kellyModeCompareHTML() +
      `</div>` +
      // D需求(2026-08-15): hint 文案 7 -> 4+3+1; v1.1.0(2026-08-15) 5+3+1 = 8键+1类=9规则
      `<span class="lab-sigkelly-toggle-hint">AI降亏过滤=总开关(联动下方默认推荐 5+3+1: 8键+1类回测剔除, 其中+1类只读不可勾选; 5=基础5含K2C5港股追涨并入);组合预设/单标志独立开启,实时过滤重算</span>` +
    `</div>`;
  // B级UI(2026-08-15): 恒显行(1行=周期+当前状态摘要+「参数」展开按钮) + 展开区(全部控制台)
  // 状态摘要: 费率档 + AI仓位K档/off + G/H/I开关, 让折叠态下用户仍一眼看到当前配置
  const _sumFee = _kellyFeeLabel();
  const _sumPos = _filters.positionCap ? `仓位K${_pcK || 1}` : "仓位off";
  const _sumGih = (_gihOn ? " · GIH开" : "");
  const _paramBtn = `<button type="button" class="lab-sigkelly-params-toggle" id="lab-kelly-params-toggle" data-no-pop="" title="展开/收起 费率·降亏过滤·AI仓位·G/H/I 全部参数控制台">${_sigParamsOpenState ? "参数收起 ▲" : "⚙️ 参数 ▼"}</button>`;
  const _paramsBodyOpen = _sigParamsOpenState ? " lab-sigkelly-params-open" : "";
  // #78(2026-08-15): 信息行 + AI仓位历史回测面板 从参数折叠区移出, 改挂到「全信号操作建议指南」卡片(折叠区外恒显)。
  //   存到全局 state 供 _kellyComboAdviceHtml() 读取渲染; 金额口径=每日资金池(与建议指南正文一致, 消除旧"每笔固定1万"双口径混乱 §22)。
  state.labSigKellyMetaHTML =
    `<div class="lab-sigkelly-gen-row">` +
      `<span>📅 生成: ${data.generated_at || "-"}</span>` +
      `<span> · 金额: 每日资金池 ${cfg.buy_amount || 10000} 元</span>` +
      `<span> · 卖出模式: ${modeStr}</span>` +
    `</div>`;
  bar.innerHTML =
    `<div class="lab-sigkelly-bar-head">` +
      `<span class="lab-sigkelly-periods">${tabsHTML}</span>` +
      `<span class="lab-sigkelly-bar-summary" title="费率: ${_sumFee} · ${_sumPos}${_sumGih} (点「参数」展开完整控制台)">费率:${_sumFee} · ${_sumPos}${_sumGih}</span>` +
      _paramBtn +
    `</div>` +
    `<div class="lab-sigkelly-params-body${_paramsBodyOpen}">` +
      `<div class="lab-sigkelly-params">` +
      // 2026-08-26 排版调整(用户拍板): topgrid 两列 = 左「费率模块(fee-row+自定义输入)」右「ai长线模式(G/H/I)仓位管理块」——
      //   PC 宽屏两列同行, 窄屏 flex-wrap 自然换行=费率一行/长线模式一行(样式见 lab.css .lab-sigkelly-topgrid);
      //   只动 DOM 顺序与排版, 控件功能/事件绑定/记忆 key 零变化(绑定全在本函数尾部按 class/id 重查, 不依赖兄弟顺序)
      `<div class="lab-sigkelly-topgrid">` +
        `<div class="lab-sigkelly-feecol">` +
          `<div class="lab-sigkelly-fee-row">` +
            `<span class="lab-sigkelly-fee-label">费率:</span>` +
            feeBtnsHTML +
            `<span class="lab-sigkelly-fee-hint">快捷键 0-4+C</span>` +
            amountHTML +
          `</div>` +
          customHTML +
        `</div>` +
        `<div class="lab-sigkelly-gihcol">` +
          // #49 ai长线模式(G/H/I)仓位管理: 从降亏过滤区(toggleHTML)后移到费率模块后(2026-08-26 用户拍板 §23.7 已确认)
          `<div class="lab-sigkelly-toggle-group lab-sigkelly-toggle-group-gih">` + aihlineLabelHTML + `</div>` +
        `</div>` +
      `</div>` +
      // G/H/I 对比表 body 紧随长线模式块之后(展开时全宽铺开, 保持 #88 横向满宽设计; 默认 display:none 不占位)
      aihlineCompareHTML +
      toggleHTML +
    `</div>`;
  // B级UI(2026-08-15): 「参数」展开/收起 —— 仅切 class + 按钮文案 + 写 localStorage, 不重渲染 bar(避免折叠↔展开返回到复时态丢失/输入焦点丢失)
  var _paramsToggle = bar.querySelector("#lab-kelly-params-toggle");
  if (_paramsToggle) {
    _paramsToggle.onclick = function () {
      var body = bar.querySelector(".lab-sigkelly-params-body");
      if (!body) return;
      var open = body.classList.contains("lab-sigkelly-params-open");
      if (open) body.classList.remove("lab-sigkelly-params-open");
      else body.classList.add("lab-sigkelly-params-open");
      _paramsToggle.textContent = open ? "⚙️ 参数 ▼" : "参数收起 ▲";
      try { localStorage.setItem('lab_sigkelly_params_open', open ? '0' : '1'); } catch (e) {}
    };
  }
  // 周期切换
  bar.querySelectorAll(".lab-sigkelly-period-btn").forEach((btn) => {
    btn.onclick = () => {
      state.labSigKellyPeriod = btn.dataset.period;
      bar.querySelectorAll(".lab-sigkelly-period-btn").forEach((b) => b.classList.toggle("active", b === btn));
      const hostEl = document.querySelector(".lab-sigkelly-host");
      if (hostEl && state.labSigKellyData) {
        _renderSigKellyQuadrants(hostEl, state.labSigKellyData, btn.dataset.period);
      }
    };
  });
  // 费率预设按钮
  bar.querySelectorAll(".lab-sigkelly-fee-btn").forEach((btn) => {
    btn.onclick = () => { _kellyOnFeeChange(btn.dataset.fee); };
  });
  // 费率输入框 change -> 读取表单值重算(切自定义档, 不重渲染 bar 保留输入焦点)
  bar.querySelectorAll(".lab-sigkelly-fee-custom input").forEach((inp) => {
    inp.onchange = () => { _kellyOnFormChange(); };
  });
  // 降亏过滤toggle: 17个独立checkbox(CSS class选择器,功能与顺序解耦), 切换后过滤交易集重算(按比值倒序)
  // v3新9 toggle(比值>3)
  var n1Cb = bar.querySelector(".lab-sigkelly-toggle-n1");
  if (n1Cb) n1Cb.onchange = function () {
    if (!state.labSigKellyFilters) state.labSigKellyFilters = _kellyDefaultFilters();
    state.labSigKellyFilters.n1MarTueHigh = n1Cb.checked;
    _kellyOnFilterChange();
  };
  var n2Cb = bar.querySelector(".lab-sigkelly-toggle-n2");
  if (n2Cb) n2Cb.onchange = function () {
    if (!state.labSigKellyFilters) state.labSigKellyFilters = _kellyDefaultFilters();
    state.labSigKellyFilters.n2NovSpecialIndustry = n2Cb.checked;
    _kellyOnFilterChange();
  };
  var r8Cb = bar.querySelector(".lab-sigkelly-toggle-r8");
  if (r8Cb) r8Cb.onchange = function () {
    if (!state.labSigKellyFilters) state.labSigKellyFilters = _kellyDefaultFilters();
    state.labSigKellyFilters.r8PureNonMay = r8Cb.checked;
    _kellyOnFilterChange();
  };
  var n3Cb = bar.querySelector(".lab-sigkelly-toggle-n3");
  if (n3Cb) n3Cb.onchange = function () {
    if (!state.labSigKellyFilters) state.labSigKellyFilters = _kellyDefaultFilters();
    state.labSigKellyFilters.n3NovSpecialMon = n3Cb.checked;
    _kellyOnFilterChange();
  };
  var n4Cb = bar.querySelector(".lab-sigkelly-toggle-n4");
  if (n4Cb) n4Cb.onchange = function () {
    if (!state.labSigKellyFilters) state.labSigKellyFilters = _kellyDefaultFilters();
    state.labSigKellyFilters.n4AMay = n4Cb.checked;
    _kellyOnFilterChange();
  };
  var r7Cb = bar.querySelector(".lab-sigkelly-toggle-r7");
  if (r7Cb) r7Cb.onchange = function () {
    if (!state.labSigKellyFilters) state.labSigKellyFilters = _kellyDefaultFilters();
    state.labSigKellyFilters.r7MayReinforced = r7Cb.checked;
    _kellyOnFilterChange();
  };
  var n5Cb = bar.querySelector(".lab-sigkelly-toggle-n5");
  if (n5Cb) n5Cb.onchange = function () {
    if (!state.labSigKellyFilters) state.labSigKellyFilters = _kellyDefaultFilters();
    state.labSigKellyFilters.n5MayVlow = n5Cb.checked;
    _kellyOnFilterChange();
  };
  var n6Cb = bar.querySelector(".lab-sigkelly-toggle-n6");
  if (n6Cb) n6Cb.onchange = function () {
    if (!state.labSigKellyFilters) state.labSigKellyFilters = _kellyDefaultFilters();
    state.labSigKellyFilters.n6MidMay = n6Cb.checked;
    _kellyOnFilterChange();
  };
  var r10Cb = bar.querySelector(".lab-sigkelly-toggle-r10");
  if (r10Cb) r10Cb.onchange = function () {
    if (!state.labSigKellyFilters) state.labSigKellyFilters = _kellyDefaultFilters();
    state.labSigKellyFilters.r10May6NonMay = r10Cb.checked;
    _kellyOnFilterChange();
  };
  // v4新12 toggle(三梯队全量上线)
  // 第一梯队
  var greedy7Cb = bar.querySelector(".lab-sigkelly-toggle-greedy7");
  if (greedy7Cb) greedy7Cb.onchange = function () {
    if (!state.labSigKellyFilters) state.labSigKellyFilters = _kellyDefaultFilters();
    state.labSigKellyFilters.greedy7 = greedy7Cb.checked;
    _kellyOnFilterChange();
  };
  var v4cSimpleCb = bar.querySelector(".lab-sigkelly-toggle-v4csimple");
  if (v4cSimpleCb) v4cSimpleCb.onchange = function () {
    if (!state.labSigKellyFilters) state.labSigKellyFilters = _kellyDefaultFilters();
    state.labSigKellyFilters.v4cSimple = v4cSimpleCb.checked;
    _kellyOnFilterChange();
  };
  var v4bCb = bar.querySelector(".lab-sigkelly-toggle-v4b");
  if (v4bCb) v4bCb.onchange = function () {
    if (!state.labSigKellyFilters) state.labSigKellyFilters = _kellyDefaultFilters();
    state.labSigKellyFilters.v4b = v4bCb.checked;
    _kellyOnFilterChange();
  };
  // 第二梯队
  var greedy10Cb = bar.querySelector(".lab-sigkelly-toggle-greedy10");
  if (greedy10Cb) greedy10Cb.onchange = function () {
    if (!state.labSigKellyFilters) state.labSigKellyFilters = _kellyDefaultFilters();
    state.labSigKellyFilters.greedy10 = greedy10Cb.checked;
    _kellyOnFilterChange();
  };
  var v4dCb = bar.querySelector(".lab-sigkelly-toggle-v4d");
  if (v4dCb) v4dCb.onchange = function () {
    if (!state.labSigKellyFilters) state.labSigKellyFilters = _kellyDefaultFilters();
    state.labSigKellyFilters.v4d = v4dCb.checked;
    _kellyOnFilterChange();
  };
  var v4jCb = bar.querySelector(".lab-sigkelly-toggle-v4j");
  if (v4jCb) v4jCb.onchange = function () {
    if (!state.labSigKellyFilters) state.labSigKellyFilters = _kellyDefaultFilters();
    state.labSigKellyFilters.v4j = v4jCb.checked;
    _kellyOnFilterChange();
  };
  var v4iCb = bar.querySelector(".lab-sigkelly-toggle-v4i");
  if (v4iCb) v4iCb.onchange = function () {
    if (!state.labSigKellyFilters) state.labSigKellyFilters = _kellyDefaultFilters();
    state.labSigKellyFilters.v4i = v4iCb.checked;
    _kellyOnFilterChange();
  };
  // 第三梯队(附监控)
  var greedy15Cb = bar.querySelector(".lab-sigkelly-toggle-greedy15");
  if (greedy15Cb) greedy15Cb.onchange = function () {
    if (!state.labSigKellyFilters) state.labSigKellyFilters = _kellyDefaultFilters();
    state.labSigKellyFilters.greedy15 = greedy15Cb.checked;
    _kellyOnFilterChange();
  };
  var v4fCb = bar.querySelector(".lab-sigkelly-toggle-v4f");
  if (v4fCb) v4fCb.onchange = function () {
    if (!state.labSigKellyFilters) state.labSigKellyFilters = _kellyDefaultFilters();
    state.labSigKellyFilters.v4f = v4fCb.checked;
    _kellyOnFilterChange();
  };
  var v4gCb = bar.querySelector(".lab-sigkelly-toggle-v4g");
  if (v4gCb) v4gCb.onchange = function () {
    if (!state.labSigKellyFilters) state.labSigKellyFilters = _kellyDefaultFilters();
    state.labSigKellyFilters.v4g = v4gCb.checked;
    _kellyOnFilterChange();
  };
  var v4mCb = bar.querySelector(".lab-sigkelly-toggle-v4m");
  if (v4mCb) v4mCb.onchange = function () {
    if (!state.labSigKellyFilters) state.labSigKellyFilters = _kellyDefaultFilters();
    state.labSigKellyFilters.v4m = v4mCb.checked;
    _kellyOnFilterChange();
  };
  var v4kCb = bar.querySelector(".lab-sigkelly-toggle-v4k");
  if (v4kCb) v4kCb.onchange = function () {
    if (!state.labSigKellyFilters) state.labSigKellyFilters = _kellyDefaultFilters();
    state.labSigKellyFilters.v4k = v4kCb.checked;
    _kellyOnFilterChange();
  };
  // K2C5/K3 (2026-08-15 #86 新增实验键; v1.1.0: K2C5 默认开, K3 默认关, 自开关看效果)
  var k2c5Cb = bar.querySelector(".lab-sigkelly-toggle-k2c5");
  if (k2c5Cb) k2c5Cb.onchange = function () {
    if (!state.labSigKellyFilters) state.labSigKellyFilters = _kellyDefaultFilters();
    state.labSigKellyFilters.k2c5HkChase = k2c5Cb.checked;
    _kellyOnFilterChange();
  };
  var k3Cb = bar.querySelector(".lab-sigkelly-toggle-k3");
  if (k3Cb) k3Cb.onchange = function () {
    if (!state.labSigKellyFilters) state.labSigKellyFilters = _kellyDefaultFilters();
    state.labSigKellyFilters.k3ConceptBuy = k3Cb.checked;
    _kellyOnFilterChange();
  };
  // T1(2026-08-23) AI降亏方法池57→全量: 20 条新键开关绑定(全部默认关 §23.7; 规格单源=scripts/loss_rules.py,
  //   键名/cls 与 _kellyFadeFlagGroups 标签一致; 循环绑定替代 20 段复制块)
  _KELLY_LOSS_NEW_KEYS.forEach(function (pair) {
    var key = pair[0];
    var cb = bar.querySelector(".lab-sigkelly-toggle-" + pair[1]);
    if (cb) cb.onchange = function () {
      if (!state.labSigKellyFilters) state.labSigKellyFilters = _kellyDefaultFilters();
      state.labSigKellyFilters[key] = cb.checked;
      _kellyOnFilterChange();
    };
  });
  // 现有6 toggle(比值<3)
  // 辅关注×3/5月交叉(排除buy_aux在3/5月)
  var auxCrossCb = bar.querySelector(".lab-sigkelly-toggle-auxcross");
  if (auxCrossCb) auxCrossCb.onchange = function () {
    if (!state.labSigKellyFilters) state.labSigKellyFilters = _kellyDefaultFilters();
    state.labSigKellyFilters.excludeAuxCross = auxCrossCb.checked;
    _kellyOnFilterChange();
  };
  // 追关注×熊市交叉(排除buy_special在MA60熊市)
  var specialBearCb = bar.querySelector(".lab-sigkelly-toggle-specialbear");
  if (specialBearCb) specialBearCb.onchange = function () {
    if (!state.labSigKellyFilters) state.labSigKellyFilters = _kellyDefaultFilters();
    state.labSigKellyFilters.excludeSpecialBear = specialBearCb.checked;
    _kellyOnFilterChange();
  };
  // 排除3+5月(季节性)
  var monCb = bar.querySelector(".lab-sigkelly-toggle-month");
  if (monCb) monCb.onchange = function () {
    if (!state.labSigKellyFilters) state.labSigKellyFilters = _kellyDefaultFilters();
    state.labSigKellyFilters.excludeMonth = monCb.checked;
    _kellyOnFilterChange();
  };
  var auxCb = bar.querySelector(".lab-sigkelly-toggle-aux");
  if (auxCb) auxCb.onchange = function () {
    if (!state.labSigKellyFilters) state.labSigKellyFilters = _kellyDefaultFilters();
    state.labSigKellyFilters.excludeAux = auxCb.checked;
    _kellyOnFilterChange();
  };
  var mktCb = bar.querySelector(".lab-sigkelly-toggle-mkt");
  if (mktCb) mktCb.onchange = function () {
    if (!state.labSigKellyFilters) state.labSigKellyFilters = _kellyDefaultFilters();
    state.labSigKellyFilters.marketTiming = mktCb.checked;
    _kellyOnFilterChange();
  };
  // 排除低评级(rating=low)
  var ratingCb = bar.querySelector(".lab-sigkelly-toggle-rating");
  if (ratingCb) ratingCb.onchange = function () {
    if (!state.labSigKellyFilters) state.labSigKellyFilters = _kellyDefaultFilters();
    state.labSigKellyFilters.excludeRatingLow = ratingCb.checked;
    _kellyOnFilterChange();
  };
  // round3新候选(11月系): A5 11月中旬+追关注 / A45 11月中下旬+追关注
  var a5Cb = bar.querySelector(".lab-sigkelly-toggle-a5");
  if (a5Cb) a5Cb.onchange = function () {
    if (!state.labSigKellyFilters) state.labSigKellyFilters = _kellyDefaultFilters();
    state.labSigKellyFilters.a5NovMidSpecial = a5Cb.checked;
    _kellyOnFilterChange();
  };
  var a45Cb = bar.querySelector(".lab-sigkelly-toggle-a45");
  if (a45Cb) a45Cb.onchange = function () {
    if (!state.labSigKellyFilters) state.labSigKellyFilters = _kellyDefaultFilters();
    state.labSigKellyFilters.a45NovMidLateSpecial = a45Cb.checked;
    _kellyOnFilterChange();
  };
  // 1月调整新2 toggle(2026-08-11 元素级重组): 1月中旬+中评级 / 1月中旬+追关注
  var janMidRatingCb = bar.querySelector(".lab-sigkelly-toggle-janmidrating");
  if (janMidRatingCb) janMidRatingCb.onchange = function () {
    if (!state.labSigKellyFilters) state.labSigKellyFilters = _kellyDefaultFilters();
    state.labSigKellyFilters.janMidRating = janMidRatingCb.checked;
    _kellyOnFilterChange();
  };
  var janMidSpecialCb = bar.querySelector(".lab-sigkelly-toggle-janmidspecial");
  if (janMidSpecialCb) janMidSpecialCb.onchange = function () {
    if (!state.labSigKellyFilters) state.labSigKellyFilters = _kellyDefaultFilters();
    state.labSigKellyFilters.janMidSpecial = janMidSpecialCb.checked;
    _kellyOnFilterChange();
  };
  // v1.1.2(2026-08-17 用户拍板) 三键之 2 备选键: 老MA60熊×追买 / 下降期×追关注(默认关, 2026-08-18 修漏绑 onchange: 开关不刷新象限表/全信号表)
  // 谓词见 _kellyPassesFadeFilters(legacyMa60Special 用 market_state, declinePhaseSpecial 用 market_tier_all, 无需特征计算)
  var legacyMa60Cb = bar.querySelector(".lab-sigkelly-toggle-legacyma60");
  if (legacyMa60Cb) legacyMa60Cb.onchange = function () {
    if (!state.labSigKellyFilters) state.labSigKellyFilters = _kellyDefaultFilters();
    state.labSigKellyFilters.legacyMa60Special = legacyMa60Cb.checked;
    _kellyOnFilterChange();
  };
  var declinePhaseCb = bar.querySelector(".lab-sigkelly-toggle-decline");
  if (declinePhaseCb) declinePhaseCb.onchange = function () {
    if (!state.labSigKellyFilters) state.labSigKellyFilters = _kellyDefaultFilters();
    state.labSigKellyFilters.declinePhaseSpecial = declinePhaseCb.checked;
    _kellyOnFilterChange();
  };
  // #69(2026-08-19 用户拍板) cyb 四档版降亏新键: excludeSpecialBearCyb(默认关非默认推荐)
  // 谓词见 _kellyPassesFadeFilters(excludeSpecialBearCyb 用 market_tier_cyb 字段, 无需特征计算)
  var specialBearCybCb = bar.querySelector(".lab-sigkelly-toggle-specialbearcyb");
  if (specialBearCybCb) specialBearCybCb.onchange = function () {
    if (!state.labSigKellyFilters) state.labSigKellyFilters = _kellyDefaultFilters();
    state.labSigKellyFilters.excludeSpecialBearCyb = specialBearCybCb.checked;
    _kellyOnFilterChange();
  };
  // (2026-08-22 用户拍板) 第 5 个降亏键: bullAuxBackupStop 牛市·主升×(辅买∪备买)全停(默认关, 仅 A-F 短线; G/H/I 豁免)
  // 谓词见 _kellyPassesFadeFilters(bullAuxBackupStop 用 market_tier 字段, 无需特征计算); lab 独立开关 state-only 不落盘(与 cyb 同模式)
  // (2026-08-22 二次变更) 各处独立: 只管 lab 凯利区, 与首页 AI 建议/模拟回测弹窗开关互不影响
  var bullStopCb = bar.querySelector(".lab-sigkelly-toggle-bullstop");
  if (bullStopCb) bullStopCb.onchange = function () {
    if (!state.labSigKellyFilters) state.labSigKellyFilters = _kellyDefaultFilters();
    state.labSigKellyFilters.bullAuxBackupStop = bullStopCb.checked;
    _kellyOnFilterChange();
  };
  // 组合降亏「预设宏」(2026-08-11用户定: 1+2+3全要,按需选择,组合可叠加=成员并集OR):
  // 2026-08-13 融合 #39: 组合宏改顶部快捷按钮(一键勾选/取消全部成员toggle, 过滤零改动(成员谓词并集), 幂等+§22一致; 组合勾选态由成员派生(不新增第三份过滤状态))
  // 按钮无 change 事件, 需手动刷新 AI宏 三态(最大化降亏组合含核心3键 greedy15)
  for (var comboKey in _kellyComboPresets) {
    (function (ck) {
      var comboCb = bar.querySelector(".lab-sigkelly-toggle-combo-" + ck);
      if (!comboCb) return;
      comboCb.onclick = function () {
        if (!state.labSigKellyFilters) state.labSigKellyFilters = _kellyDefaultFilters();
        var members = _kellyComboPresets[ck].members;
        var allOn = true;
        for (var i = 0; i < members.length; i++) { if (!state.labSigKellyFilters[members[i].k]) { allOn = false; break; } }
        var setOn = !allOn;
        for (var j = 0; j < members.length; j++) {
          state.labSigKellyFilters[members[j].k] = setOn;
          var mb = bar.querySelector("." + members[j].cls);
          if (mb) mb.checked = setOn;
        }
        _kellyRefreshComboStates(bar);
        _kellyRefreshAiMacroState(bar);
        _kellyOnFilterChange();
      };
    })(comboKey);
  }
  // #39 三级级联UI 第1级 AI宏 总开关(2026-08-13): 勾选→联动3元子级(r7+exclAuxCross+greedy15), 取消→取消3元; 三态由3元派生
  var aiMacroCb = bar.querySelector(".lab-sigkelly-toggle-aimacro");
  if (aiMacroCb) aiMacroCb.onchange = function () {
    if (!state.labSigKellyFilters) state.labSigKellyFilters = _kellyDefaultFilters();
    for (var i = 0; i < _kellyAiMacroMembers.length; i++) {
      state.labSigKellyFilters[_kellyAiMacroMembers[i].k] = aiMacroCb.checked;
      var mb = bar.querySelector("." + _kellyAiMacroMembers[i].cls);
      if (mb) mb.checked = aiMacroCb.checked;
    }
    _kellyRefreshAiMacroState(bar);
    _kellyRefreshComboStates(bar);
    _kellyOnFilterChange();
    // v1.1.9 fix: 开启AI降亏时恢复s06动态基座态(关AI时L8703已清null, 需在此恢复)
    if (aiMacroCb.checked) {
      state.labSigKellyFadeModeBase = "s06";
    }
  };
  // positionCap 仓位控制过滤(2026-08-12): 开关 + K档位1-4(共享localStorage供交易页标灰联动)
  // 2026-08-13 调序+OFF: K按钮组加 OFF(写 tds_poscap {on:false} 退化普通列表, 再点某 K 档恢复), 与首页/交易页共享键联动(§22)
  // 同步 K/off 按钮高亮(bar 非整建重渲染, 需手动管理; on=true→K 档高亮, on=false→OFF 高亮)
  function _syncPosCapActive(barEl, on, k) {
    barEl.querySelectorAll(".lab-sigkelly-kbtn").forEach(function (b) {
      if (b.dataset.k === "off") b.classList.toggle("active", !on);
      else b.classList.toggle("active", !!on && parseInt(b.dataset.k, 10) === (k || 3));
    });
  }
  var posCapCb = bar.querySelector(".lab-sigkelly-toggle-poscap");
  if (posCapCb) posCapCb.onchange = function () {
    if (!state.labSigKellyFilters) state.labSigKellyFilters = _kellyDefaultFilters();
    state.labSigKellyFilters.positionCap = posCapCb.checked;
    _kellySetSharedPosCap(posCapCb.checked, state.labSigKellyFilters.positionCapK || 1);
    _syncPosCapActive(bar, posCapCb.checked, state.labSigKellyFilters.positionCapK || 1);
    _kellyOnFilterChange({ keepS06: true }); // posCap是持仓参数非过滤标签, 不改模式基座(S06 keepS06修复)
  };
  bar.querySelectorAll(".lab-sigkelly-kbtn").forEach(function (btn) {
    btn.onclick = function () {
      if (!state.labSigKellyFilters) state.labSigKellyFilters = _kellyDefaultFilters();
      if (btn.dataset.k === "off") {
        // OFF 按钮(2026-08-13, 复用首页同款交互): 写 tds_poscap {on:false}, 关闭 AI仓位建议 → 该区退化普通列表; 再点某 K 档恢复
        state.labSigKellyFilters.positionCap = false;
        _kellySetSharedPosCap(false, 1);
      } else {
        state.labSigKellyFilters.positionCapK = parseInt(btn.dataset.k, 10) || 1;
        state.labSigKellyFilters.positionCap = true;  // 从 OFF 恢复(点 K 档=开启)
        _kellySetSharedPosCap(true, state.labSigKellyFilters.positionCapK);
      }
      var posCapCb2 = bar.querySelector(".lab-sigkelly-toggle-poscap");
      if (posCapCb2) posCapCb2.checked = !!state.labSigKellyFilters.positionCap;
      _syncPosCapActive(bar, state.labSigKellyFilters.positionCap, state.labSigKellyFilters.positionCapK || 1);
      _kellyOnFilterChange({ keepS06: true }); // K档是持仓参数非过滤标签, 不改模式基座(S06 keepS06修复)
    };
  });
  // #49+#xx ai长线模式(G/H/I)仓位管理: 开关(默认关, 只影响 G/H/I) → 写共享键 + 重算(套各模式独立仓位策略) + 刷新对比表; A-F 不受影响
  var gihCb = bar.querySelector(".lab-sigkelly-toggle-gih");
  if (gihCb) gihCb.onchange = function () {
    state.labSigKellyGihOn = !!gihCb.checked;
    _kellySetSharedGih(state.labSigKellyGihOn);
    // 开关后: G/H/I 卡片数据需重新计算(套 FIFO cap), 重渲染 bar 刷新对比表展示态 + 重算象限
    var hostEl = document.querySelector(".lab-sigkelly-host");
    if (hostEl && state.labSigKellyData) {
      // #49 fix(issue49): 对比表展开/收起由按钮点击独立控制(_gihCompareOpen), 开关 change 不强制收展 — 只触发重算刷新内容; _renderSigKellyBar 重渲染时对比表开合保持不变
      _kellyRunRecompute(hostEl,
        '<div class="lab-custom-loading">⏳ 切换 ai长线模式, 重算 G/H/I 仓位管理…</div>',
        function (stats) {
          if (stats) {
            state.labSigKellyFeeStats = stats;
            // 【P0 防御兜底】bar/host 实时重查在册节点, 防 await 让步期间整区重建后写死节点
            var bb2 = document.querySelector(".lab-sigkelly-bar") || bar;
            var hb2 = document.querySelector(".lab-sigkelly-host") || hostEl;
            _renderSigKellyBar(bb2, state.labSigKellyData, state.labSigKellyPeriod);
            _updateSigKellyQuadrantsInPlace(hb2, state.labSigKellyData, state.labSigKellyPeriod);
          }
        },
        function () {}
      );
    }
  };
  // #xx G 档位切换(2026-08-29 codex#001 改定稿单档 13万后兼容保留): 静态 13万 span 的 tier 恒等于 _kellyGihGTier()
//  (均为 "13万"), 本 handler 恒早退无重算副作用——保留以防未来恢复多档自选; 联动逻辑(bar/对比表/卡片/水印/三玩法)未拆
  bar.querySelectorAll(".lab-sigkelly-gih-tier-btn").forEach(function (btn) {
    btn.onclick = function () {
      var tier = btn.dataset.tier;
      if (!tier || tier === _kellyGihGTier()) return;
      _kellySetGihGTier(tier);
      var hostEl = document.querySelector(".lab-sigkelly-host");
      if (hostEl && state.labSigKellyData) {
        _kellyRunRecompute(hostEl,
          '<div class="lab-custom-loading">⏳ 切换 G 档位 ' + tier + ', 重算 ai长线仓位管理…</div>',
          function (stats) {
            if (stats) {
              state.labSigKellyFeeStats = stats;
              // 【P0 防御兜底】bar/host 实时重查在册节点, 防 await 让步期间整区重建后写死节点
              var bb3 = document.querySelector(".lab-sigkelly-bar") || bar;
              var hb3 = document.querySelector(".lab-sigkelly-host") || hostEl;
              _renderSigKellyBar(bb3, state.labSigKellyData, state.labSigKellyPeriod);
              _updateSigKellyQuadrantsInPlace(hb3, state.labSigKellyData, state.labSigKellyPeriod);
            }
          },
          function () {}
        );
      }
    };
  });
  // #49 对比表收起/展开按钮
  var _gihBtn = bar.querySelector("#lab-kelly-gih-compare-btn");
  var _gihWrap = document.getElementById("lab-kelly-gih-compare-body");
  if (_gihBtn && _gihWrap) {
    _gihBtn.addEventListener("click", function () {
      _gihCompareOpen = _gihWrap.style.display === "none";   // 当前收起→展开(state=开), 否则收起
      _gihWrap.style.display = _gihCompareOpen ? "" : "none";
      _gihBtn.textContent = _gihCompareOpen ? "G/H/I 对比表 ▲" : "G/H/I 对比表 ▼";
    });
  }
  // 2026-08-13: K档位评级 hoverpop(评级理由表格, 桌面 hover / 移动端 tap; 共享 common.js _bindAiPoscapRatePop, 与首页同款 §22)
  _bindAiPoscapRatePop(bar);
  // #39 三级级联UI 第1级 AI宏 独立行收起/展开(2026-08-13): 收起/展开 组合降亏 + 单标志降亏 整体详情(默认收起)
  // 问题1修复(2026-08-15): 展开/收起态写 state.labSigKellyAiDetailOpen(参照 labSigKellyMoreOpen 模式), 点小标签/组合按钮重渲染后详情保持展开, 不回落默认收起
  var _aiBtn = bar.querySelector("#lab-kelly-ai-macro-btn");
  var _aiWrap = bar.querySelector("#lab-kelly-ai-macro-body");
  if (_aiBtn && _aiWrap) {
    _aiBtn.addEventListener("click", function () {
      var open = _aiWrap.style.display !== "none";
      _aiWrap.style.display = open ? "none" : "";
      state.labSigKellyAiDetailOpen = !open;
      _aiBtn.textContent = open ? "AI降亏过滤详情展开 ▼" : "AI降亏过滤详情收起 ▲";
    });
  }
  // #54 2026-08-13 (用户20:27 必做): 「重置为AI默认推荐」——恢复 AI默认勾选(_kellyDefaultFilters 默认档全开, v1.1.7 起=当前默认基座 S06 动态模式+AI仓位建议K=1), 重写 tds_kelly_filters 持久化, 重算统计+刷新 hoverpop 动态值
  // 2026-08-14 #BC: 默认 K 3→1 主推

  // T3-1(2026-08-23): AI降亏模式下拉 onchange —— apply 预设到 filters 后只调 _kellyOnFilterChange():
  // 其完成回调会重渲染 bar(标签勾选态/口径标注/AI宏三态/组合三态全部按新 filters 派生刷新), 无需手动同步 57 个 checkbox。
  var _fadeModeSelEl = bar.querySelector("#lab-kelly-fade-mode-sel");
  if (_fadeModeSelEl) _fadeModeSelEl.onchange = function () {
    var mid = _fadeModeSelEl.value;
    if (!mid || mid === "custom") return; // custom 为 disabled 占位项, 正常不可触发(兜底还原)
    if (!state.labSigKellyFilters) state.labSigKellyFilters = _kellyDefaultFilters();
    // S06(codex-task-20260825-001): dynamic 预设不走 Apply(返回 false)——判定层 per-date 接管,
    // 标签区恢复默认档作静态参考底座 + 重写 tds_kelly_filters(防旧自定义 members 冷启动复活造成
    // 「记忆 s06 却显示自定义」不一致, §22); 手动勾任一标签经 _kellyOnFilterChange 入口退出动态态
    var _pSel = (typeof _tdsFadeModeById === "function") ? _tdsFadeModeById(mid) : null;
    if (_pSel && _pSel.dynamic) {
      var _dftIdS6 = (typeof window._KELLY_FADE_DEFAULT_MODE === "string") ? window._KELLY_FADE_DEFAULT_MODE : "new14";
      _tdsFadeModeApply(_dftIdS6, state.labSigKellyFilters);
      state.labSigKellyFadeModeBase = mid;
      if (typeof _tdsStoreWithTTL === "function") _tdsStoreWithTTL("tds_kelly_fade_mode", { mode: mid });
      else try { localStorage.setItem("tds_kelly_fade_mode", JSON.stringify({ mode: mid })); } catch (e) {}
      _kellyPersistFilters();
      _kellyOnFilterChange({ keepS06: true });
      _kellyToast("已切到 S06 · 大盘领先切换(v1.1.7 起默认基座): 按日动态切 A进攻王/NEW14+1 基座, 标签区为参考底座");
      return;
    }
    if (!_tdsFadeModeApply(mid, state.labSigKellyFilters)) return;
    state.labSigKellyFadeModeBase = mid;
    // TTL 记忆(2026-08-23 用户拍板): {mode, ts} 滑动过期——每次切换重写 ts=最后切换时间, 过期回当前默认基座 s06 动态(v1.1.7 起)
    if (typeof _tdsStoreWithTTL === "function") _tdsStoreWithTTL("tds_kelly_fade_mode", { mode: mid });
    else try { localStorage.setItem("tds_kelly_fade_mode", JSON.stringify({ mode: mid })); } catch (e) {}
    _kellyOnFilterChange();
  };
  var _aiResetBtn = bar.querySelector("#lab-kelly-ai-macro-reset");
  if (_aiResetBtn) {
    _aiResetBtn.addEventListener("click", function () {
      var host = document.querySelector(".lab-sigkelly-host");
      if (!host || !state.labSigKellyData) return;
      state.labSigKellyFilters = _kellyDefaultFilters(); // bullAuxBackupStop 为 state-only 不落盘, 重置随默认值回关
      // v1.1.7: 重置同步回落当前默认基座 s06 动态模式(按大盘风格按日切 A进攻王/NEW14+1), 模式记忆一并重写(TTL 工具, ts 刷新=重置也续期)
      var _dftModeId2 = (typeof window._KELLY_FADE_DEFAULT_MODE === "string") ? window._KELLY_FADE_DEFAULT_MODE : "new14";
      state.labSigKellyFadeModeBase = _dftModeId2;
      if (typeof _tdsStoreWithTTL === "function") _tdsStoreWithTTL("tds_kelly_fade_mode", { mode: _dftModeId2 });
      else try { localStorage.setItem("tds_kelly_fade_mode", JSON.stringify({ mode: _dftModeId2 })); } catch (e) {}
      _kellySetSharedPosCap(true, 1);
      _kellyPersistFilters(); // 重写 tds_kelly_filters(当前默认基座 S06 动态 + aiMacro:true), 持久化恢复默认
      _kellyRunRecompute(host,
        '<div class="lab-custom-loading">⏳ 重置为AI默认推荐,重算统计…</div>',
        function (stats) { if (stats) state.labSigKellyFeeStats = stats; else state.labSigKellyFeeStats = null; },
        function (h) {
          // 【P0 防御兜底】h=收尾重取的在册 host(优先), 闭包 host 兜底; bar 实时重查防写死节点
          var hb4 = h || host;
          var bb4 = document.querySelector(".lab-sigkelly-bar") || bar;
          _renderSigKellyBar(bb4, state.labSigKellyData, state.labSigKellyPeriod);
          _updateSigKellyQuadrantsInPlace(hb4, state.labSigKellyData, state.labSigKellyPeriod);
        }
      );
      _kellyToast("已重置为AI默认推荐(v1.1.7: 当前默认基座 S06 动态模式 + 1类回测剔除 + AI仓位建议 K=1主推)");
    });
  }
  // 4大分类组 收起/展开(2026-08-13 融合 #39: 组标题可点击收展该组, 4组默认全展开)
  // 举一反三修复(2026-08-15): 收展态写入 state.labSigKellyCatCollapsed(参照 labSigKellyMoreOpen 模式), 点小标签/组合按钮重渲染后保持用户手工收展, 不再恢复全展开
  bar.querySelectorAll(".lab-sigkelly-toggle-tier-cat").forEach(function (tier) {
    tier.addEventListener("click", function () {
      var cat = tier.getAttribute("data-cat");
      var body = bar.querySelector(".lab-sigkelly-toggle-cat-body[data-cat='" + cat + "']");
      var caret = tier.querySelector(".lab-sigkelly-toggle-cat-caret");
      if (!body) return;
      var isCollapsed = body.classList.contains("collapsed");
      body.classList.toggle("collapsed", !isCollapsed);
      if (caret) caret.textContent = isCollapsed ? "▼" : "▶";
      // 写 state: 收起→记录该组 key, 展开→删除该组 key
      if (!state.labSigKellyCatCollapsed) state.labSigKellyCatCollapsed = {};
      if (isCollapsed) delete state.labSigKellyCatCollapsed[cat];
      else state.labSigKellyCatCollapsed[cat] = true;
    });
  });
  // 2026-08-14 重写:「更多开关」折叠区 open 状态持久化(重渲染后保持), 写入 state 供下次 render 读
  var _moreDtl = bar.querySelector(".lab-sigkelly-toggle-more");
  if (_moreDtl) {
    _moreDtl.addEventListener("toggle", function () {
      state.labSigKellyMoreOpen = _moreDtl.open;
    });
  }
  // T2(2026-08-23): 「AI 降亏组成对比」折叠区 open 态持久化(参照 labSigKellyMoreOpen 模式, 重渲染后保持)
  var _modeCmpDtl = bar.querySelector(".lab-sigkelly-mode-compare");
  if (_modeCmpDtl) {
    _modeCmpDtl.addEventListener("toggle", function () {
      state.labSigKellyModeCompareOpen = _modeCmpDtl.open;
    });
  }
  // 2026-08-14 组合使用建议外层折叠区 open 状态持久化(默认收缩, 展开后重渲染保持), 写入 state 供下次 render 读
  var _adviceDtl = bar.querySelector(".lab-sigkelly-advice-outer");
  if (_adviceDtl) {
    _adviceDtl.addEventListener("toggle", function () {
      state.labSigKellyAdviceOpen = _adviceDtl.open;
    });
  }
  // #83: 移除「AI仓位建议·历史回测数据」面板后, 其展开态持久化绑定(原 _poscapHstDtl / state.labSigKellyPoscapHistoryOpen)一并删除, 无残留引用
  // 成员toggle改动→刷新组合三态+AI宏三态(事件委托, 捕获toggle区内所有checkbox change; 组合自身/AI宏自身change跳过, 各自handler已刷新)
  var _kellyToggleRow = bar.querySelector(".lab-sigkelly-toggle-row");
  if (_kellyToggleRow) {
    _kellyToggleRow.addEventListener("change", function (e) {
      var t = e.target;
      if (t && t.classList) {
        if (!t.classList.contains("lab-sigkelly-toggle-combo")) _kellyRefreshComboStates(bar);
        if (!t.classList.contains("lab-sigkelly-toggle-aimacro")) _kellyRefreshAiMacroState(bar);
      }
    });
  }
  // 首渲染同步组合三态+AI宏三态(部分成员勾选→组合/AI宏半选 indeterminate)
  _kellyRefreshComboStates(bar);
  _kellyRefreshAiMacroState(bar);
  // v1.1.5: 枯竭提示 chip 异步填充(N≥20 才显示, 失败静默隐藏; 用户改开关重渲染时本函数重新调用→chip 实时跟随)
  try { _kellyMountDroughtChip(bar); } catch (e) {}
}

// ================= #79(2026-08-15): 凯利回测报告清单 + 查看弹窗 =================
// 用户原话:「报告git路径地址无法查看, 精简成可点击打开查看点弹窗按钮, 名称缩短为用户看得懂的, 内容里附详细目录结构参考」
// 报告原始 md 在仓库 docs/kelly/ 下, 本清单=可读短名 + 一句话摘要 + 目录结构(toC, 提取自各 md 的 ## / ### 标题)。
// ⚠ 同步维护: 改 docs/kelly/*.md 后若章节/结论变了, 请同步本清单(§22/§23.5 数据来源一致); 弹窗不塞报告全文(体量过大),
//   展示目录结构给用户参考, 完整报告在 git 仓库 docs/kelly/。
var _KELLY_REPORTS = {
  "kelly-position-filter-backtest": {
    name: "仓位过滤回测", path: "docs/kelly/position/kelly-position-filter-backtest.md",
    summary: "单日重复信号=仓位控制过滤 的回测基础: 单日多信号分布、同日内选优能否挖出规则、候选规则(主口径G模式)全维度对比 + 按年分解弱年诚实标注。",
    toc: ["0 摘要(三个核心答案)", "1 单日多信号分布", "1.1 数据基础 / 单日信号数分布 / 信号数vs当日收益", "2 同日信号组内选优 vs 选劣", "3 候选规则回测对比(G模式)", "4 按年分解与弱年诚实标注", "5 推荐规则与理由", "6 实现建议(过滤开关如何定义)"]
  },
  "kelly-position-cap-k-sensitivity": {
    name: "仓位控制K敏感性", path: "docs/kelly/position/kelly-position-cap-k-sensitivity.md",
    summary: "K 值敏感性全谱 + 每日资金池等分口径回测: 修正「多信号=过滤」为「每日资金池等分」, K=1 最优先 K=2 折中, 叠加组合矩阵与按年分解。",
    toc: ["0 摘要(核心答案+前向测试警示)", "1 口径修正: 每日资金池等分", "2 K 值敏感性全谱(K=1-8)", "3 每笔1万口径 K 敏感性(对照)", "4 叠加组合矩阵(COMBO4/live4/27toGG)", "5 top-K + 质量约束", "6 按年分解(每日池 G)", "7 10模式(A-J)敏感性", "8 前向测试(选择器稳定性)"]
  },
  "kelly-dailypool-exhaustive-rerun": {
    name: "每日池穷举重跑", path: "docs/kelly/position/kelly-dailypool-exhaustive-rerun.md",
    summary: "每日资金池口径穷举重跑(2026-08-13): 主基准页面 AI宏7键 A 模式 K1=86.60% 最高, 最优 toggle 组合依卖出模式分裂, K=1 全模式收益率最高。",
    toc: ["0 摘要(三个核心答案)", "0.1 A模式 K1 主基准 86.60%", "0.2 最优 toggle 组合依卖出模式分裂", "0.3 K=1 全模式收益率最高(机制性)", "1 数据版本与口径声明", "2 任务1: AI宏7键 A/F/G × K1-4 每日池 vs 每笔1万", "3 任务2: 27 toggle 边际复核(G)", "4 任务3: 最优组合穷举(G 32配置)", "5 任务4: 口径转换对比", "6 任务5: 按年分解", "7 任务6: ratio 排序对比", "8 诚实标注"]
  },
  "kelly-g-mode-recheck": {
    name: "G模式复核", path: "docs/kelly/position/kelly-g-mode-recheck.md",
    summary: "G 模式专项复检: FIFO 95.66% 是否最优? 连续 cap 扫描 + 强平顺序全矩阵 + 稳健性验证, 结论 P≤3d「先卖年轻仓」全面超旧 FIFO。",
    toc: ["0 摘要(核心答案)", "1 连续 cap 扫描(5-20万 每1万)", "2 强平顺序全矩阵 × 多 cap(10/15/20万)", "3 稳健性验证(多起始时点+随机抽查)", "4 模型敏感性(b0/b1区间宽度)", "5 G vs H/I 差异解释", "6 推荐 + 诚实标注", "7 证据清单(可复核)"]
  },
  "kelly-ghi-continuous-cap-sweep": {
    name: "G/H/I连续资金扫描", path: "docs/kelly/position/kelly-ghi-continuous-cap-sweep.md",
    summary: "G/H/I 连续 cap 档位扫描 + 时间稳健性验证: H 最优=满仓不买@7万, I 最优=满仓不买@16万(用户拍板原15万上调), 分母效应剥离后真最优档。",
    toc: ["0 摘要(核心答案)", "1 连续 cap 扫描(H/I × 5-20万 每1万)", "2 分母效应剥离后的真最优(H=7万 / I=16万, 用户拍板原15万上调)", "3 时间稳健性验证(排除偶然)", "4 结论与用户决策点+诚实标注"]
  },
  "kelly-nextday-batch-limit-sop": {
    name: "次日分批挂单SOP", path: "docs/kelly/position/kelly-nextday-batch-limit-sop.md",
    summary: "次日分批挂单买入SOP(穷举回测): 分N单挂「次日开盘-1%」限价未触达尾盘补满, 比次日开盘直接买多赚约6万, 附主矩阵+9模式全测+敏感性。",
    toc: ["一 一句话结论", "二 摘要(用户想法逐条数据验证)", "三 操作标准SOP(玩法定义/推荐参数/步骤)", "四 主矩阵全表(每日池 N=K vs 次日开盘)", "五 卖出模式9模式全测", "六 关键维度敏感性(资金/挂单深度/成交规则)", "七 诚实标注(挂单模型假设)", "八 脚本与数据落档"]
  },
  "kelly-combo-usage-advice": {
    name: "组合使用建议", path: "docs/kelly/combo/kelly-combo-usage-advice.md",
    summary: "降亏组合使用建议 + 全信号表(真实回测验证): 4个降亏组合全开好不好? 分投资习惯给出建议(追高/保守/短长线) + 总建议(全信号+G卖出模式)。",
    toc: ["0 摘要(两个问题答案)", "1 数据与口径(可复核)", "2 场景对比明细(4组合 vs 去一)", "3 全信号表(按卖出模式)", "4 按年窗口增长", "5 分投资习惯建议", "6 数据不可得/口径说明"]
  },
  "kelly-jan-adjust-combo-verify": {
    name: "1月调整组合验证", path: "docs/kelly/combo/kelly-jan-adjust-combo-verify.md",
    summary: "「1月调整」组合元素级验证: 1月系(日段×评级×信号)全谱, 首推 J1(1月中旬+mid评级)稳健, 备选 J2, 明确不推荐清单 + 实施验收口径。",
    toc: ["0 摘要", "1 数据与口径", "2 1月系全谱", "3 首推 J1(1月中旬+mid评级)稳健性", "4 备选 J2(1月中旬+追关注)", "5 与现有标志的关系(重叠/边际)", "6 明确不推荐", "7 实施落地(lab.js 凯利区)", "8 验收口径", "9 数据不可得/口径说明"]
  },
  "kelly-fee-adjust": {
    name: "费率调整影响", path: "docs/kelly/analysis/kelly-fee-adjust.md",
    summary: "凯利回测费率客调方案调研: 费率计算逻辑读透 + trades.json 字段可重算性验证 + 三方案对比(前端动态重算/后端重跑/后端预计算), 推荐方案A前端动态重算。",
    toc: ["1 费率计算逻辑", "2 trades.json 字段可重算性(已验证)", "3 三方案对比(推荐前端动态重算)", "4 trade_sim 费率客调现状"]
  },
  "kelly-fee-presets": {
    name: "费率预设", path: "docs/kelly/analysis/kelly-fee-presets.md",
    summary: "凯利回测费率客调快捷键预设档: 预设档清单(1-4窗/常用)、快捷键映射、参数映射(后端常量+JSON config 字段)、实施架构注意事项。",
    toc: ["1 背景与现状", "2 预设档清单", "3 快捷键映射建议", "4 参数映射(实施用)", "5 实施注意事项", "6 数据来源与验证状态"]
  }
};

// 报告查看弹窗(复用 lab-signal-modal 容器样式, 参照术语词典 modal)
// #84(2026-08-15): 弹窗显示完整报告正文(非仅摘要+目录)。正文 HTML 由 scripts/kelly_reports_html.py 从
//   docs/kelly/**/*.md 预生成到 static-site/kelly-reports-content.js(全局 KELLY_REPORTS_CONTENT[id]), §23.5 数据来源一致。
//   目录(TOC)可折叠(details), 正文保留 h1-h4 结构 + 表格/代码块, 弹窗放大 + 正文独立滚动(见 lab.css .lab-kelly-repo-*).
function _kellyReportModalHTML(id) {
  const r = _KELLY_REPORTS[id];
  if (!r) return "";
  const tocHTML = r.toc.map((t) => `<div class="lab-kelly-repo-toc-line">${t}</div>`).join("");
  const fullHTML = (window.KELLY_REPORTS_CONTENT && window.KELLY_REPORTS_CONTENT[id]) || "";
  return `<div class="lab-signal-modal lab-kelly-repo-modal">` +
    `<div class="lab-signal-modal-head">` +
    `<span class="lab-signal-modal-title">📄 ${r.name}</span>` +
    `<button type="button" class="lab-rank-modal-close" aria-label="关闭">✕</button>` +
    `</div>` +
    `<div class="lab-signal-modal-body">` +
      `<div class="lab-kelly-repo-meta">${r.summary}</div>` +
      `<div class="lab-kelly-repo-path">源报告: <code>${r.path}</code> (docs/kelly/ 下)</div>` +
      `<details class="lab-kelly-repo-toc-wrap" open>` +
        `<summary class="lab-kelly-repo-toc-title">📑 目录结构（点击折叠/展开）</summary>` +
        `<div class="lab-kelly-repo-toc">${tocHTML}</div>` +
      `</details>` +
      (fullHTML
        ? `<div class="lab-kelly-repo-body">${fullHTML}</div>`
        : `<div class="lab-kelly-repo-body lab-kelly-repo-body-empty">未找到正文（缺 kelly-reports-content 数据源，源见 ${r.path}）。</div>`) +
    `</div></div>`;
}
async function _kellyReportOpenModal(id) {
  let overlay = document.getElementById("labKellyRepoOverlay");
  if (!overlay) {
    overlay = document.createElement("div");
    overlay.id = "labKellyRepoOverlay";
    overlay.className = "lab-signal-overlay";
    document.body.appendChild(overlay);
  }
  // P1-01: 点击报告时动态加载报告正文+审查备注(原 defer 同步加载 379KB)
  await _loadKellyReports();
  await _loadKellyReviewNotes();
  overlay.innerHTML = _kellyReportModalHTML(id);
  overlay.classList.add("show");
  document.body.style.overflow = "hidden";
  overlay.onclick = (e) => { if (e.target === overlay) _kellyReportCloseModal(); };
  const cls = overlay.querySelector(".lab-rank-modal-close");
  if (cls) cls.onclick = _kellyReportCloseModal;
}
function _kellyReportCloseModal() {
  const overlay = document.getElementById("labKellyRepoOverlay");
  if (overlay) { overlay.classList.remove("show"); document.body.style.overflow = ""; }
}
// 全文档级事件委托: 点「🔍查看报告」按钮打开对应报告弹窗(数据来源按钮在建议指南/ai长线对比表等静态区)
document.addEventListener("click", function (e) {
  const btn = e.target && e.target.closest ? e.target.closest(".lab-kelly-repo-btn") : null;
  if (btn && btn.dataset && btn.dataset.repoId) {
    e.preventDefault(); e.stopPropagation();
    _kellyReportOpenModal(btn.dataset.repoId);
  }
});

// 16象限卡片网格(4组: 评级3 + ETF4 + 信号类型4 + 指数大类5)
// ===== 组合使用建议 + 全信号表(最后结果) =====
// 静态建议面板: 数字来自真实回测(复刻 _kellyPassesFadeFilters/_kellyComputeStats 的 Python 管线跑部署数据66,726笔),
// 详见 docs/kelly/combo/kelly-combo-usage-advice.md; 口径=4组合全开(年末季节+稳健核心+最大化降亏+1月调整), 数据更新需同步
function _kellyComboAdviceHtml() {
  return (
    `<div class="lab-sigkelly-advice">` +
      `<div class="lab-sigkelly-advice-title">🎯 全信号操作建议指南（真实回测 · 口径=每日资金池等分+top-K，2026-08-14 #48）</div>` +
      (state.labSigKellyMetaHTML || "") +
      `<div class="lab-sigkelly-advice-li lab-sigkelly-advice-note">默认最优组合已开启（v1.1.5 起 AI降亏过滤=NEW14 十四键=hist6+规则8+1类回测剔除，重构换基座；切换依据 mine28 AUTO 轮动样本外不成立 + mine30 记分板 NEW14 第一(全史净利 +122,648 vs 八键 +66,530、回撤 -4,178 vs -18,190)，数据支撑 <button type="button" class="lab-kelly-repo-btn" data-repo-id="kelly-dailypool-exhaustive-rerun">🔍每日池穷举重跑</button>）：hist6 = r10 5月+6非5月组合 + Greedy-15组合 + J2 1月中旬+追关注 + K2C5 港股追涨剔除(穷举验证 docs/kelly/analysis/kelly-k2c5-exhaust-interaction.md) + K3 主关注×概念 + 下降期×追关注(全市场)；规则8 = N1北向20日净流出 + T1换手冰点×追关注 + D1股息率低位 + Q1 QVIX低分位 + H1升波×A股 + M1牛主升×两融降温 + P1备买×股息率分位低 + R2b追关注×全球类(T1 族规格单源=scripts/loss_rules.py)；旧八键(v1.1.4 及以前默认：基础5+核心3)保留为手动可开对照档(§23.7 不删档)，两者皆保留入样、可被 AI建议推荐；+1=回测/凯利模型层剔除的波动相关/未入样本信号整类（债类cgb_*/情绪s.*/全球商品利率g.*/港股行业hk_*/空数组，_bt_in_universe=false）——虽同属全信号，但被回测剔除，故 AI建议 一律不推荐，以「未入样本」+灰显+删除线表达。信号枯竭提示：NEW14 下历史上年均约 2.4 次 ≥20 个交易日无放行信号的枯竭期，凯利区与首页会出提示 chip(历史上类似枯竭结束后 3 个月约 72% 为正)。另加 AI仓位建议（技术别名：仓位控制过滤，每日只买最优K个，K=1主推，2026-08-14 #BC 默认 K 3→1）。每日池+费率重算口径（2026-08-14 #BC，含最低佣金5元）：A模式 K1(默认主推)=86.60%/K2=67.61%/K3=66.24%/K4=63.17%；F K1=78.71%/G K1=47.22%（#48 每日池口径，⚠以上为 v1.1.4 八键基座数字，NEW14 基座下以本页实时计算为准）。旧 fixed 穷举v2（77.36/66.22/68.40，每笔1万）与 #48 每日池(比例法)均为历史决策基准已过时（#BC 改费率重算口径）。⚠G 模式（推荐卖出法）分裂结论(v1.0.0 八键时代结论，NEW14 基座下需重测)：去掉 greedy15/excludeAuxCross/r7 并加 a45(11月中下旬+追关注)→ K1 收益升到 51.66%（净+82.6万）；A45/A5 不在 NEW14 组合。其余降亏 toggle 默认关（负边际/过拟合）。⚠J2 带监控（maxSh 0.79，2026 单年主导，每年 1 月后检查）。下方「最后结果」全信号表即按当前组合实时计算。</div>` +
      `<details class="lab-sigkelly-advice-details lab-sigkelly-advice-outer"${state.labSigKellyAdviceOpen ? " open" : ""}>` +
        `<summary><span class="lab-sigkelly-advice-summary-short">🎯 全信号操作建议指南（v1.1.7 起默认基座=S06 动态 · G玩法P≤3d可操作）</span><span class="lab-sigkelly-advice-summary-full">🎯 全信号操作建议指南（v1.1.7 起默认基座=S06 动态, 快照日切 A进攻王/NEW14+1 键集；NEW14 为 v1.1.5~v1.1.6 历史可回选档：hist6+规则8 降亏键保留入样 + 1回测剔除波动相关/未入样本信号；G玩法P≤3d「先卖年轻仓」三档可操作）</span></summary>` +
        `<div class="lab-sigkelly-advice-panel">` +
        `<div class="lab-sigkelly-advice-body">` +
          `<div class="lab-sigkelly-advice-section-title">分投资习惯怎么用（A/F/J/G 四玩法实时并列）</div>` +
          `<div class="lab-sigkelly-advice-li"><b>三玩法并列</b>（实时随上方降亏组合勾选 / 费率档联动，全周期 all 口径（与下方总建议一致）；下方「最后结果」卡随周期切换，切到「全部」时同值；金额口径=每日资金池等分+top-K）：A=固定10天短线（快进快出）；F=持有15天短线；J=固定20天短线；G=卖出信号长线（指数卖出信号触发离场、无信号持有至回测结束，最贴近交易页信号驱动跟单，也是总建议主选；G 建议开上方「ai长线模式(G/H/I)仓位管理」套 P≤3d 可操作档）。</div>` +
          _sigKellyAfgRealtimeHtml() +
          `<table class="lab-sigkelly-table lab-sigkelly-advice-table"><thead><tr><th>投资习惯</th><th>建议</th><th>真实回测数据</th></tr></thead><tbody>` +
            `<tr><td>追高/趋势型</td><td>追关注信号只做牛市（MA60 之上），熊市追涨坚决回避</td><td>牛市 n=19,323 净 <b>+490万</b> 胜率60.5% 盈亏比1.94；熊市 n=1,908 净 -16.3万 胜率41.7% 盈亏比0.97（亏损区）</td></tr>` +
            `<tr><td>保守型</td><td>只做高评级信号（rating=high）</td><td>n=531 胜率 <b>70.6%</b> 盈亏比 <b>2.88</b> 年化 <b>2.80%</b>（质量最优但样本少，宜与广谱组合）</td></tr>` +
            `<tr class="lab-sigkelly-advice-hl"><td><b>总建议</b></td><td><b>全信号都看 + 完全遵守交易页面展示的交易方法（卖出信号 G 模式）</b></td><td>AI仓位建议 K=1（主推，每日池+费率重算口径 「每日池穷举重跑」 <button type="button" class="lab-kelly-repo-btn" data-repo-id="kelly-dailypool-exhaustive-rerun">🔍查看报告</button>）下 G 模式收益率 <b>47.22%</b> 净 <b>+642,184</b>（未套仓位管理原始口径，峰持仓 136万=不可操作，须开下方「ai长线模式(G/H/I)仓位管理」套 P≤3d 可操作档，推荐 13万=188.88%/+245,538(v1.1.7 基准定稿)，见下方 G 玩法教学）；按年（G K1 每日池）：2021 <b>-23,500</b>（唯一回撤年）外主要年正，2023 +60,645 不转负，2024 +225,894 / 2025 +151,405（合计占 K1 总净利 58.7%）</td></tr>` +
            `<tr class="lab-sigkelly-advice-cmp"><td><b>真实对照</b></td><td><b>「AI降亏过滤」全开 vs 全关（G 模式真实净利对比，AI仓位 K=2 口径，每日池）</b></td><td>降亏<b>全开</b>（8键=基础5+核心3）= 净 <b>+1,044,948</b>；降亏<b>全关</b> = 净 <b>+1,221,750</b>。差值：全开比全关<b>少赚约 17.7万</b>（-176,802）。说白了＝降亏过滤不是白赚，它会同时砍掉亏损单和一部分盈利单，G 模式净利反而降——这是「降亏」的代价，不是 bug。可对照 K=1 主推档：全开 +642,184 vs 全关 +809,525（少赚约 16.7万）。若要「既降亏又不砍盈利」，参考上方 G 玩法：去 greedy15/excludeAuxCross/r7 + 加 a45（K1 升到 51.66%/净+82.6万）。</td></tr>` +
          `</tbody></table>` +
          `<div class="lab-sigkelly-advice-section-title">总建议（最优秀玩法 + 操作指南）</div>` +
          `<div class="lab-sigkelly-advice-li">总建议配套（页面默认组合 AI降亏过滤，可复现）：仓位=每日资金池等分 + AI仓位建议 K=1（技术别名：仓位控制过滤，同日只买最优1个，主推档，2026-08-14 #BC 默认 K=1；每日总投入恒 1 万均分当日保留数，可切 K=2/3/4）；降亏过滤=追关注×熊市（excludeSpecialBear）+ n2NovSpecialIndustry（11月+追关注+行业）+ janMidRating（1月中旬+中评级）+ janMidSpecial（1月中旬+追关注）+ r7MayReinforced（5月强化+3稳定非5月）+ excludeAuxCross（辅关注×3/5月交叉）+ greedy15（Greedy-15组合），7个默认开启；⚠口径差异说明：本节「投资习惯」静态表格数字=每笔固定 1 万基线（「组合使用建议」 <button type="button" class="lab-kelly-repo-btn" data-repo-id="kelly-combo-usage-advice">🔍查看报告</button>），与下方「最后结果」表（实时=每日资金池等分+top-K）<b>不同口径，不可直接纵向对比</b>，仅供行为/年份参考，核心决策以每日池为准。G 模式（指数卖出信号触发离场）最贴近交易页面的信号驱动跟单，AI仓位建议 K=1 主推口径见上方「总建议」行。⚠J1/J2 带监控（maxSh 0.62/0.79，2026 单年主导），每年 1 月后检查1月中旬子集是否转盈。</div>` +
          `<div class="lab-sigkelly-advice-li lab-sigkelly-advice-verdict lab-sigkelly-gmethod"><b>🎓 G 玩法完整交易方法（2026-08-14，与 A/F 并列，供 G 用户实盘落地）</b>：G=卖出信号长线，默认 AI宏5+3=基础5+核心3（保留入样的8键含K2C5，另 +1=回测剔除波动相关/未入样本信号）之外可再加一层仓位管理。研究找出 G 的最优仓位法＝<b>P≤3d「先卖年轻仓」</b>（数据支撑 「G模式复核」 <button type="button" class="lab-kelly-repo-btn" data-repo-id="kelly-g-mode-recheck">🔍查看报告</button> #49）：<b>持仓超过上限时，先卖掉「刚买进、还没持有满 3 天」的年轻仓（几笔年轻仓里先卖持有最久的那笔）；只有当手上一笔年轻仓都没有时，才轮到卖最老的持仓</b>。白话理解＝<b>保老仓、砍新仓</b>——因为回测里 G 的利润引擎集中在 21-100 天持仓段（净 +24.6万，长持全是盈利单, v1.1.7 基准），新仓才刚买、还没累积利润、砍掉损失最小。举例：你已有 12 万持仓，A 笔已持 10 天赚了 +8%（利润引擎要留），B 笔刚买 2 天刚回本（年轻仓），此时新信号买入会超 13 万上限 → 先卖 B 保 A，让 A 继续滚利润。</div>` +
          `<div class="lab-sigkelly-advice-li lab-sigkelly-gmethod"><b>定稿档位（2026-08-29 用户+数据定稿=只保留 13万单档；收益率数字为 b0 保守口径）</b>：<b>P≤3d@13万</b> = 188.88%（净 +245,538，占用 91.4%=13 倍本金, v1.1.7 基准定稿，≤20 倍=可操作）；对比旧 15万档 147.34%（净 +221,016）、20万档 131.25%（净 +262,509）——13万档收益率全 G 档最高（188.88%, v1.1.7 基准定稿），「13万份本金内先卖年轻仓」既压住可操作性（13 倍）又吃满收益率，数据定稿后 15/20 万选项已删（可配合本面板「ai长线模式(G/H/I)仓位管理」开关联动看效果）。</div>` +
          `<div class="lab-sigkelly-advice-li lab-sigkelly-gmethod"><b>为什么可信（对比证明）</b>：P≤3d 在 5-20 万每个档位收益率都高于旧 FIFO（卖最老＝卖掉了利润引擎本体）；15 个不同起始年 <b>全部</b>胜 FIFO（收益率均值 98.9% vs FIFO 62.0%）、随机 30 个起始点 <b>0/30 负</b>。且 P≤3d 强平的正好是 0-3 天新仓（还没累积利润）→ 保守/乐观两种利润模型区间窄（13万档 24pp）＝<b>数字可信、几乎不依赖模型假设</b>；反观旧 FIFO 强平的是最老仓（平均已持 73 天、自然利润合计 +45 万）→ 区间宽 105pp，真实值高度不确定。<b>结论：G 用户若上仓位管理，用 P≤3d「先卖年轻仓」代替旧 FIFO，收益率与可信度双提升。</b></div>` +
          `<div class="lab-sigkelly-advice-li lab-sigkelly-advice-note lab-sigkelly-gmethod">📌 G 方法三层流程（白话说一遍）：① 选组合=AI宏5+3+1默认=基础5+核心3（5+3 保留入样核心降亏键含K2C5；+1=回测剔除波动相关/未入样本信号，AI建议一律不推荐；A/F 维持现状最稳）；② G 想更极致可去 greedy15/excludeAuxCross/r7 + 加 a45（见上方口径说明分裂结论）；③ 实盘仓位=每日池均分 + P≤3d「先卖年轻仓」@13万定稿单档(2026-08-29 已删 15/20 档自选)。⚠本段为研究结论（详见上方「G模式复核」报告），实际交易以页面「ai长线模式(G/H/I)仓位管理」开关勾选联动为准，仍需你盯盘确认信号。</div>` +
          `<div class="lab-sigkelly-advice-li lab-sigkelly-nextday"><b>🆕 回测买入价口径（v1.1.4 起默认=信号次日开盘）</b>：凯利回测买入价 = <b>信号次日开盘价</b>（信号收盘后固化、次日开盘才能真实成交），按 gap 比例换算到 accum_nav 口径（次日开盘 accum_nav 等价值 = 信号日 accum_nav × (次日原始 open / 信号日原始 close)，正确处理分红/份额折算）；旧基线「信号日收盘等价 accum_nav」因收盘价不可成交已于 v1.1.4 切换（量化见 kelly-nextday-open-backtest.md：净利仅微降 0.01%~0.57%、收益率基本不变）。</div><div class="lab-sigkelly-advice-li lab-sigkelly-nextday"><b>🆕 次日买入玩法（分批挂单，数据更稳，2026-08-15 SOP）</b>：买入执行尽量放<b>次日</b>而非当日收盘——次日开盘直接买比当日收盘买几乎不输（净利仅低 0.01%，胜率反升）；更稳的玩法是<b>分 N 单挂「次日开盘价 -1%」限价单，未触达尾盘按现价补满 1 万预算</b>，回测比次日开盘直接买多赚约 6 万（均价 -0.37%，87.9% 交易日日内最低点低于开盘=免费搭日内下探便车）。数据支撑 「次日分批挂单SOP」 <button type="button" class="lab-kelly-repo-btn" data-repo-id="kelly-nextday-batch-limit-sop">🔍查看报告</button> §3.4，与首页「推荐方法·参考说明」同口径（§22）。</div>` +
          `<div class="lab-sigkelly-advice-li lab-sigkelly-advice-note">⚠ 2026-08-14 #48 口径说明：本节「投资习惯」行为表格/总建议数字为<b>每日资金池等分+top-K（2026-08-13 恢复, 2026-08-14 #BC 对齐重算）口径</b>；页面实时 K 档评级/全信号表同为<b>每日资金池等分+top-K</b>，可对照。核心决策以每日池为准（§0.2 分裂结论）：A/F 短持→维持 AI宏5+3（基础5保留入样8键含K2C5）默认现状；G 长持(推荐卖出法)→建议去 greedy15/excludeAuxCross/r7 + 加 a45。上方 A/F/G 三玩法表为全周期 all 口径(每日池,实时联动)，下方「最后结果」全信号表随周期切换（切到「全部」时两表同值）。</div>` +
        `</div>` +
      `</div>` +
    `</details>` +
    `</div>`
  );
}

// 推荐区 A/F/J/G 四玩法实时并列表(2026-08-12 #18): 全周期 all 口径, 与「最后结果」全信号表同源同口径(feeStats.all.all),
// 实时随上方降亏组合勾选/费率档联动(经 _updateSigKellyQuadrantsInPlace 就地刷新 .lab-sigkelly-afg-realtime)
function _sigKellyAfgRealtimeHtml() {
  const feeStats = state.labSigKellyFeeStats;
  if (!feeStats || !feeStats.all) {
    const _progS = _labKellyProgStr();
    return `<div class="lab-sigkelly-afg-realtime"><div class="lab-custom-loading lab-sigkelly-all-loading">⏳ 计算中…${_progS}</div></div>`;
  }
  const modes = [
    { key: "A", name: "A · 固定10天短线", desc: "买入后固定持有 10 天卖出, 快进快出" },
    { key: "F", name: "F · 持有15天短线", desc: "买入后固定持有 15 天卖出" },
    { key: "J", name: "J · 固定20天短线", desc: "买入后固定持有 20 天卖出" },
    { key: "G", name: "G · 卖出信号中长线", desc: "指数卖出信号触发离场, 无信号持有至回测结束; 最贴近交易页信号驱动跟单, 总建议主选" },
  ];
  let rows = "";
  const _afgPosCapOn = !!((state.labSigKellyFilters || {}).positionCap);
  const _afgGihOn = !!state.labSigKellyGihOn;
  // G 可操作口径参考(报告权威 b0 保守 / b1 乐观, 出处 docs/kelly/position/kelly-g-mode-recheck.md; 与「G/H/I 对比表」/purpose-notes 同值 §21/§22)
  // v2.1(2026-08-29 codex#001) 只保留 13万 定稿单档(15/20档死数据已删, _kellyGihGTier() 恒 "13万")
  const _KELLY_G_TIER_REF = {
    "13万": { b0: ["188.88%", "+245,538", "13万"], b1: ["188.88%", "+245,538", "13万"] } // v1.1.7 基准定稿, b0=b1 同值
  };
  for (const m of modes) {
    // G 行: 始终展示可操作口径(P≤3d 当前档, 峰持仓≤20倍本金=可操作), 不再披露原始 329笔/146万 无操作性数字。
    //   GIH on 用真实仿真 __gihb1(乐观, 与卡片一致, 全列有值); GIH off 用报告参考保守 b0(净利/收益率/本金)。
    if (m.key === "G") {
      const _gTier = _kellyGihGTier();
      const _gRef = _KELLY_G_TIER_REF[_gTier] || _KELLY_G_TIER_REF["13万"];
      const _gOp = (feeStats.all.all || {})["G__gihb1"];
      let _gRow;
      if (_gOp && _gOp.n) {
        _gRow = {
          name: `G · P≤3d ${_gTier}（可操作）`,
          n: _gOp.n,
          prof: (_gOp.total_profit >= 0 ? "+" : "") + Math.round(_gOp.total_profit).toLocaleString("en-US"),
          profCls: _gOp.total_profit >= 0 ? "pos" : "neg",
          win: (_gOp.win_rate * 100).toFixed(1) + "%",
          pl: (_gOp.pl_ratio == null) ? "-" : _gOp.pl_ratio.toFixed(2),
          rmh: _gOp.return_pct_max_holding.toFixed(2) + "%",
          rmhCls: _gOp.return_pct_max_holding >= 0 ? "pos" : "neg",
          mc: _gOp.max_concurrent + "笔 / " + (_gOp.max_concurrent_capital / 10000).toFixed(0) + "万",
          minC: (_gOp.max_concurrent_capital / 20 / 10000).toFixed(1) + "万",
          badge: `AI长线·开 ${_gTier}`,
          tip: `G=P≤3d「先卖年轻仓」${_gTier}（乐观口径，峰持仓≤20倍本金=可操作；与卡片「最后结果」同值）`
        };
      } else {
        _gRow = {
          name: `G · P≤3d ${_gTier}（可操作）`,
          n: "—",
          prof: _gRef.b0[1],
          profCls: "pos",
          win: "—",
          pl: "—",
          rmh: _gRef.b0[0],
          rmhCls: "pos",
          mc: _gRef.b0[2] + "万（≤20倍）",
          minC: "—",
          badge: `P≤3d ${_gTier}·可操作`,
          tip: `G=P≤3d「先卖年轻仓」${_gTier}（保守 b0 口径，峰持仓≤20倍本金=可操作）；样本/胜率/盈亏比见「G/H/I 对比表」`
        };
      }
      rows += `<tr class="lab-sigkelly-trade-row lab-sigkelly-advice-hl" title="${_gRow.tip}"><td><b>${_gRow.name}</b><span class="lab-sigkelly-exec-badge" title="${_gRow.tip}">${_gRow.badge}</span></td><td>${_gRow.n}</td><td class="lab-sigkelly-${_gRow.profCls}">${_gRow.prof}</td><td>${_gRow.win}</td><td>${_gRow.pl}</td><td class="lab-sigkelly-${_gRow.rmhCls}">${_gRow.rmh}</td><td>${_gRow.mc}</td><td>${_gRow.minC}</td></tr>`;
      continue;
    }
    const s = (feeStats.all.all || {})[m.key];
    if (!s || !s.n) { rows += `<tr><td><b>${m.name}</b></td><td colspan="7">暂无数据</td></tr>`; continue; }
    // #25 A包(需求②+需求D举一反三): 三玩法表同样标不可操作淘汰(峰持仓>20倍); A/F 在 K-OFF 下也可能无仓位限制峰持仓超限
    const _afgFlag = _kellyOpElimination(feeStats.all.all, m.key, _afgGihOn, _afgPosCapOn);
    const _afgElim = _afgFlag ? _afgFlag.eliminated : false;
    const _afgReason = _afgFlag && _afgFlag.eliminated ? _afgFlag.reason : "";
    const profStr = (s.total_profit >= 0 ? "+" : "") + Math.round(s.total_profit).toLocaleString("en-US");
    const winStr = (s.win_rate * 100).toFixed(1) + "%";
    const plStr = (s.pl_ratio == null) ? "-" : s.pl_ratio.toFixed(2);
    const rmhStr = s.return_pct_max_holding.toFixed(2) + "%";
    const maxConcStr = s.max_concurrent + "笔 / " + (s.max_concurrent_capital / 10000).toFixed(0) + "万";
    const minCapStr = (s.max_concurrent_capital / 20 / 10000).toFixed(1) + "万";
    const hlAttr = (m.key === "G") ? " lab-sigkelly-advice-hl" : "";
    const afgCls = `class="lab-sigkelly-trade-row${hlAttr}${_afgElim ? " lab-sigkelly-eliminated-row lab-sigkelly-opelim-row" : ""}"`;
    const afgTip = _afgElim ? `淘汰·${_afgReason}: ${(_afgFlag && _afgFlag.tip) || ""}` : m.desc;
    const afgBadge = _afgElim ? `<span class="lab-sigkelly-exec-badge" title="${(_afgFlag && _afgFlag.tip) || _afgReason}">淘汰·${_afgReason}</span>` : "";
    rows += `<tr ${afgCls} title="${afgTip}"><td><b>${m.name}</b>${afgBadge}</td><td>${s.n}</td><td class="${s.total_profit >= 0 ? "lab-sigkelly-pos" : "lab-sigkelly-neg"}">${profStr}</td><td>${winStr}</td><td>${plStr}</td><td class="${s.return_pct_max_holding >= 0 ? "lab-sigkelly-pos" : "lab-sigkelly-neg"}">${rmhStr}</td><td>${maxConcStr}</td><td>${minCapStr}</td></tr>`;
  }
  return (
    `<div class="lab-sigkelly-afg-realtime">` +
      (state.labSigKellyGihOn
        ? `<div class="lab-sigkelly-gih-modal-note" title="#49+#xx ai长线仓位管理口径说明">⚠️ “ai长线模式(G/H/I)仓位管理”已开：本「三玩法各自披露」表 G 行已显示<u>可操作口径</u>（P≤3d「先卖年轻」当前档 ${_kellyGihGTier()}，乐观值，峰持仓≤20倍本金=可操作）；H/I 行仍为未套仓位法的原始口径（H 45万/34.3%／I 111万/39.5%，本金占用大），已套最优仓位法后的收益/净利见「最后结果」卡（H=满仓不买@7万／I=满仓不买@16万，更优且≤20倍可操作）。两者口径不同，请以卡片/对比表为准。</div>`
        : "") +
      `<div class="lab-sigkelly-advice-li"><b>三玩法各自披露</b>「峰值资金收益率＋最大持仓＋所需最小本金」：峰值资金收益率=总盈亏/峰值同时持仓资金×100（与卡面/最后结果表同口径）；最大持仓=峰值同时持仓笔数/资金；所需最小本金≈峰值同时持仓资金÷20（按 20 倍资金约束折算，实际按自身杠杆/资金安排）。<b>举个真实例子（G 模式·可操作口径 P≤3d）</b>：G 行历史峰值同时持仓约 <b>13 万</b>（已套仓位管理后，峰持仓≤20 倍本金=可操作；原始无操作性口径 146 万不披露），所需最小本金 ≈ 130000÷20 = <b>6500 元</b>——意思是「历史最多同时占用过 13 万，按最多动用 20 倍本金的约束，至少准备 6500 元本金就能跑得动这套玩法」；本金越大越稳、回撤越小，按自身资金量选玩法。<i>核实源=lab.js _KELLY_G_TIER_REF「13万」档（P≤3d 可操作口径，§5.4 基准 G=13万 P≤3d；13万÷20=6500 元）</i>。</div>` +
      `<div class="lab-sigkelly-table-scroll"><table class="lab-sigkelly-table lab-sigkelly-afg-table"><thead><tr>` +
        `<th>玩法</th>` +
        `<th title="样本=经当前降亏组合+AI仓位建议(K)过滤后保留的交易笔数">样本</th>` +
        `<th title="净盈亏(元)=全部交易盈亏之和(含费率, 每笔固定1万口径)">净盈亏(元)</th>` +
        `<th title="胜率=盈利笔数/总笔数">胜率</th>` +
        `<th title="盈亏比=平均盈利/平均亏损(绝对值), 反映赚亏幅度之比">盈亏比</th>` +
        `<th title="峰值资金收益率=总盈亏/峰值同时持仓资金×100, 与卡面/最后结果表同口径">峰值资金收益率</th>` +
        `<th title="最大持仓=峰值同时持仓笔数/资金(万), 反映资金占用峰值">最大持仓</th>` +
        `<th title="所需最小本金≈峰值同时持仓资金÷20(20倍资金约束折算)">所需最小本金</th>` +
      `</tr></thead><tbody>${rows}</tbody></table></div>` +
      `<div class="lab-sigkelly-advice-li lab-sigkelly-advice-note">本表实时随上方降亏组合勾选 / 费率档联动（全周期 all 口径，与下方总建议一致；下方「最后结果」卡随周期切换，切到「全部」时同值，金额口径=每日资金池等分+top-K（2026-08-13 恢复，2026-08-14 #48 口径对齐）。G 行为<u>可操作口径</u>（P≤3d「先卖年轻」当前档，峰持仓≤20倍本金，不再披露原始 329笔/146万 无操作性数字）；A/F/J 行勾选越激进（保留交易越多）净利越高但所需本金越大，按自身资金量选玩法；G 为总建议主选（卖出信号长线，与交易页信号驱动跟单一致）。</div>` +
    `</div>`
  );
}

// 全信号表(最后结果): 全信号「all」伪象限卡(实时随toggle/费率/周期) + 按年窗口增长表
// 2026-08-14 需求②: 来源条件归纳提示——动态读当前状态拼出「当前[模式]+[k档]+[降亏N标志]+[费率口径](+[G档])」,
//   不写死, 实时反映本表数据实际使用的条件(卖出模式下拉选中 + AI仓位K档 + 降亏标志集 + 费率档; G 模式额外补 G 定稿档13万)
function _kellyYearlySourceHint(modeKey) {
  var parts = ["[" + (modeKey || "G") + "]"];
  var f = state.labSigKellyFilters || _kellyDefaultFilters();
  parts.push(f.positionCap ? ("[k=" + (f.positionCapK || 1) + "]") : "[k=off]");
  var flagCount = 0;
  for (var kk in f) {
    if (kk === "positionCap" || kk === "positionCapK") continue;
    if (f[kk] === true) flagCount++;
  }
  parts.push("[降亏" + flagCount + "标志]");
  parts.push("[" + _kellyFeeLabel() + "]");
  if (modeKey === "G") parts.push("[G档" + _kellyGihGTier() + "]");
  return "当前" + parts.join("+");
}
function _sigKellyAllSignalGroupHtml(period) {
  const feeStats = state.labSigKellyFeeStats;
  if (!feeStats || !feeStats.all) {
    const _progS = _labKellyProgStr();
    return `<div class="lab-sigkelly-group lab-sigkelly-all-group"><div class="lab-sigkelly-group-title">📌 全信号表（最后结果 · 全量信号融合）<span class="lab-sigkelly-all-badge">最后结果</span></div><div class="lab-custom-loading lab-sigkelly-all-loading">⏳ 计算中…${_progS}</div></div>`;
  }
  const allMeta = { label: "全信号", desc: "评级高低分区并集（互斥全量覆盖），全量信号不拆分，实时反映当前降亏组合勾选 / 费率 / 周期", periods: {} };
  const cardHtml = _renderSigKellyCard("all", allMeta, period, null);
  // 2026-08-14 按年窗口增长 A-G 各模式下拉切换: 每个模式各自独立按年聚合(allYearlyByMode), 默认 G(当前推荐卖出法, 保持现网口径)
  const _ymModes = (state.labSigKellyData && state.labSigKellyData.config && state.labSigKellyData.config.sell_modes) || {};
  const _yearlyByMode = feeStats.allYearlyByMode || {};
  const _selMode = state.labSigKellyYearlyMode || "G";
  // 下拉选项: 用有按年数据的模式(A-G 及全部有 signal 的模式); 保证默认 G 存在
  const _ymOpts = Object.keys(_yearlyByMode).length
    ? Object.keys(_yearlyByMode).sort()
    : (Object.keys(_ymModes).length ? Object.keys(_ymModes).sort() : ["G"]);
  if (_ymOpts.indexOf(_selMode) < 0 && _ymOpts.length) state.labSigKellyYearlyMode = _ymOpts[0];
  const _selModeFinal = state.labSigKellyYearlyMode || "G";
  const _ymOptionsHtml = _ymOpts.map((_mk) => {
    const _ml = (_ymModes[_mk] && _ymModes[_mk].label) ? _ymModes[_mk].label : _mk;
    return `<option value="${_mk}"${_mk === _selModeFinal ? " selected" : ""}>${_mk} · ${_ml}</option>`;
  }).join("");
  const yearly = _yearlyByMode[_selModeFinal] || {};
  const years = Object.keys(yearly).sort();
  let yRows = "";
  let yCum = 0;
  for (const y of years) {
    const v = yearly[y];
    yCum += v.profit;
    const wr = v.n ? (v.wins / v.n * 100).toFixed(1) + "%" : "-";
    const profStr = (v.profit >= 0 ? "+" : "") + v.profit.toFixed(0);
    const cumStr = (yCum >= 0 ? "+" : "") + yCum.toFixed(0);
    const yCls = v.profit >= 0 ? "lab-sigkelly-pos" : "lab-sigkelly-neg";
    const yCumCls = yCum >= 0 ? "lab-sigkelly-pos" : "lab-sigkelly-neg";
    // 按年峰值资金收益率列(2026-08-12): =该年累计净盈亏/该年峰值同时持仓资金×100, 与卡面/建议面板口径一致(§22)
    const yPeakStr = v.peak_return_pct != null ? v.peak_return_pct.toFixed(2) + "%" : "-";
    const yPeakCls = v.peak_return_pct == null ? "" : (v.peak_return_pct >= 0 ? "lab-sigkelly-pos" : "lab-sigkelly-neg");
    // 2026-08-14 按年峰值资金回撤列(第7列): =该年最大回撤金额/该年峰值同时持仓资金×100, 与 hoverpop 同口径(只是按年), 认知差对齐
    const yPeakDdStr = v.peak_drawdown_pct != null ? v.peak_drawdown_pct.toFixed(2) + "%" : "-";
    const yPeakDdCls = v.peak_drawdown_pct == null ? "" : (v.peak_drawdown_pct > 0 ? "lab-sigkelly-neg" : "lab-sigkelly-pos");
    yRows += `<tr><td>${y}</td><td>${v.n}</td><td class="${yCls}">${profStr}元</td><td class="${yCumCls}">${cumStr}元</td><td>${wr}</td><td class="${yPeakCls}" title="=该年累计净盈亏/该年峰值同时持仓资金">${yPeakStr}</td><td class="${yPeakDdCls}" title="=该年过程中最深一次从高点跌下来的幅度(最大回撤金额÷峰值同时持仓资金)">${yPeakDdStr}</td></tr>`;
  }
  const _ymEmptyRows = (!years.length) ? `<tr><td colspan="7" class="lab-sigkelly-all-empty">该模式暂无信号数据</td></tr>` : "";
  return (
    `<div class="lab-sigkelly-group lab-sigkelly-all-group">` +
      `<div class="lab-sigkelly-group-title">📌 全信号表（最后结果 · 全量信号融合）<span class="lab-sigkelly-all-badge">最后结果</span></div>` +
      `<div class="lab-sigkelly-all-desc">总建议口径：全信号都看 + 完全遵守交易页面展示的交易方法（卖出信号 G 模式）。金额口径=每日资金池等分+top-K（2026-08-13 恢复：当日保留前K基笔，每笔=10000/当日保留数，每日总投入恒1万，K档最大持仓恒定）。下表实时随上方降亏组合勾选 / 费率档 / 周期切换联动。年份窗口表为全周期口径（非当前周期窗口），**各模式各自独立按年增长**（2026-08-14 扩展：下方下拉选择 A-G 任一模式查看其各自的按年窗口增长，非混算；G 模式=当前推荐卖出法，与「总建议=遵守G模式卖出」语义对齐）。</div>` +
      `<div class="lab-sigkelly-all-main">` +
        `<div class="lab-sigkelly-all-card">${cardHtml}</div>` +
        `<div class="lab-sigkelly-all-yearly lab-sigkelly-all-yearly-block">` +
          `<div class="lab-sigkelly-all-sub">按年窗口增长</div>` +
          `<div class="lab-sigkelly-yearly-modebar">` +
            `<label class="lab-sigkelly-yearly-mode-label" for="lab-sigkelly-yearly-mode">卖出模式</label>` +
            `<select id="lab-sigkelly-yearly-mode" class="lab-sigkelly-yearly-mode-select" data-yearly-mode="1">${_ymOptionsHtml}</select>` +
            `<span class="lab-sigkelly-yearly-mode-cur" title="本表数据来源条件：卖出模式 + AI仓位K档 + 降亏标志集 + 费率口径，实时随上方勾选/费率档联动">${_kellyYearlySourceHint(_selModeFinal)}</span>` +
          `</div>` +
          `<div class="lab-sigkelly-table-scroll"><table class="lab-sigkelly-table lab-sigkelly-yearly-table">` +
            `<thead><tr><th>年份</th><th>笔数</th><th>净盈亏(元)</th><th>累计净盈亏(元)</th><th>胜率</th><th title="=该年最终的赚钱结果 ÷ 该年手上同时拿着最多的钱 ×100;注意回撤≠收益率:回撤是过程中最深一次从高点跌下来的幅度,收益率是最终净结果,两者是不同尺子">峰值资金<br>收益率</th><th title="=该年过程中最深一次从高点跌下来的幅度(最大回撤金额÷峰值同时持仓资金);与收益率(最终净结果)不同,回撤通常≥亏损,因为过程可能先涨后跌">峰值资金<br>回撤</th></tr></thead>` +
            `<tbody>${yRows}${_ymEmptyRows}</tbody>` +
          `</table></div>` +
          `<div class="lab-sigkelly-all-note">💡 白话解释：收益率=这一年最终赚的钱 ÷ 这一年手里同时拿得最多的那笔钱；回撤=这一年过程中最深一次从高点跌下去的幅度。它俩是两把不同的尺子，回撤一般会比亏损大，因为过程可能先涨后跌——别拿这两列直接比大小。<b>举个真实例子（当前默认 G 模式·AI宏5+3+1·K=1）</b>：2021 年，过程最深回撤 <b>-8.7%</b>（这一年累计盈利先冲高到峰值、再往下最深跌了 8.7%），年末最终净结果却是 <b>-3.8%</b>——一个「先涨上去又跌下来」的年份，所以回撤这一列（8.7%）明显比收益率那列（-3.8%）大，因为回撤量的是「过程里从最高点往下最深的一刀」，收益率量的是「年末最后一笔总账」，是不同时点的两个数，不能直接比大小。<i>核实源=当前数据实时重算(2026-08-16 trades, signal_kelly_trades.json→前端按年聚合 peak_return_pct/peak_drawdown_pct)</i>。全周期回撤见「AI仓位建议」的 K 按钮评级。</div>` +
        `</div>` +
      `</div>` +
    `</div>`
  );
}

function _renderSigKellyQuadrants(host, data, period) {
  const quads = data.quadrants || {};
  const feeStats = state.labSigKellyFeeStats;
  // 卡间比较水印: 全局16张卡互比, 选综合最佳(蓝星)+最稳定(紫菱), 随周期/费率切换实时重算
  const cmp = _sigKellyCardComparison(quads, period, feeStats);
  const groups = [
    { title: "按信号评级分组(10d score 评级)", keys: ["rating_high", "rating_mid", "rating_low"] },
    { title: "按 ETF 跟踪评分分组(track_tier 归类)", keys: ["etf_strong", "etf_related", "etf_approx", "etf_has_track"] },
    { title: _t("lab_group_by_sig_type"), keys: ["sig_main", "sig_aux", "sig_special", "sig_backup"] },
    { title: "按指数大类分组(宽基/港股/全球/行业/概念)", keys: ["mkt_a", "mkt_hk", "mkt_global", "mkt_industry", "mkt_concept"] },
  ];
  // 卡片置顶: 置顶的子域卡集中显示在最前部已置顶区(按置顶顺序), 置顶卡从原分组剔除, 只影响展示顺序
  const pinnedKeys = _sigKellyPinnedKeys();
  const pinnedSet = {};
  for (let i = 0; i < pinnedKeys.length; i++) pinnedSet[pinnedKeys[i]] = true;
  const pinnedSub = pinnedKeys.filter((k) => k !== "all" && quads[k]);
  // 组合使用建议(静态) + 全信号表(最后结果, 实时) 常驻顶部
  let html = _kellyComboAdviceHtml() + _sigKellyAllSignalGroupHtml(period);
  // 已置顶区(置顶子域卡集中显示, 置顶/取消置顶后整组重排)
  if (pinnedSub.length) {
    html += `<div class="lab-sigkelly-group lab-sigkelly-group-pinned">`;
    html += `<div class="lab-sigkelly-group-title">📌 已置顶 <span class="lab-sigkelly-pin-hint">(${pinnedSub.length} 张·点击卡内 📌 取消置顶)</span></div>`;
    html += `<div class="lab-sigkelly-grid">`;
    for (let i = 0; i < pinnedSub.length; i++) {
      const qk = pinnedSub[i];
      html += _renderSigKellyCard(qk, quads[qk], period, cmp.map[qk] || null);
    }
    html += `</div></div>`;
  }
  for (const g of groups) {
    // 跳过已置顶的子域卡(不重复展示)
    const keystoRender = g.keys.filter((k) => !pinnedSet[k] && quads[k]);
    if (!keystoRender.length) continue;
    html += `<div class="lab-sigkelly-group">`;
    html += `<div class="lab-sigkelly-group-title">${g.title}</div>`;
    html += `<div class="lab-sigkelly-grid">`;
    for (const qk of keystoRender) {
      html += _renderSigKellyCard(qk, quads[qk], period, cmp.map[qk] || null);
    }
    html += `</div></div>`;
  }
  html +=
    `<div class="lab-sigkelly-legend">` +
      `<span class="lab-sigkelly-legend-label">半凯利仓位色标:</span>` +
      `<span class="lab-kelly-tier lab-kelly-aggressive">激进 ≥60%</span>` +
      `<span class="lab-kelly-tier lab-kelly-balanced">均衡 30-60%</span>` +
      `<span class="lab-kelly-tier lab-kelly-conservative">保守 <30%</span>` +
      `<span class="lab-sigkelly-note">⚠️ 样本量 n<100 统计意义弱,仅供参考,非投资建议。半凯利=凯利比例/2(更保守)。🎯 1:1 举例（核实源=signal_kelly_backtest.json quadrants.mkt_global.periods.all.G）：全球大类·卖出信号·全部周期 半凯利=<b>41.1%→均衡档（30-60%）</b>——这组 600 个样本胜率 84%、盈亏比 8.88，凯利公式算出全凯利 82.2% 太激进，折半取 41.1% 下注，意思=建议把可投入资金约四成用于下注（保守+平衡的选择）；样本 n<100 的行才挂 ⚠️。</span>` +
    `</div>`;
  host.innerHTML = html;
  _bindSigKellyCardEvents(host);
}

// 绑定卡内事件(行点击弹交易记录modal + 水印hoverpop + 卖出模式说明hoverpop); 整建/就地更新共用
function _bindSigKellyCardEvents(host) {
  // 交易记录行点击 -> 弹窗
  host.querySelectorAll(".lab-sigkelly-trade-row").forEach((row) => {
    row.onclick = () => {
      _openSigKellyTradesModal(row.dataset.quad, row.dataset.mode, row.dataset.period);
    };
  });
  // 卡片置顶按钮: 点击切换置顶(写 localStorage), 整组重排渲染(置顶卡进已置顶区, 排序变更需重建)
  host.querySelectorAll(".lab-sigkelly-pin-btn").forEach((btn) => {
    btn.onclick = (e) => {
      e.stopPropagation();
      const qk = btn.getAttribute("data-pin-quad");
      if (!qk) return;
      _sigKellySetPinned(qk, !_sigKellyIsPinned(qk));
      const bar = document.querySelector(".lab-sigkelly-bar");
      if (bar) _renderSigKellyBar(bar, state.labSigKellyData, state.labSigKellyPeriod);
      _renderSigKellyQuadrants(host, state.labSigKellyData, state.labSigKellyPeriod);
    };
  });
  // 组比较水印 hoverpop: 悬停/点击 badge 弹说明
  _bindSigKellyWmPop(host);
  // 卖出模式说明 hoverpop: 悬停/点击"卖出模式说明❓"入口弹 A-F 说明
  _bindSigKellyGuidePop(host);
  // 按年窗口增长模式下拉: 切换 A-G 任一模式, 就地刷新按年增长表(前端 state 联动, 不刷新整页)
  _bindSigKellyYearlyMode(host);
  // 2026-08-14 问题1: 全信号表按年窗口表格限高——测量「强关联ETF」卡片(etf_strong)高度作为基准, 设置按年表滚动容器 max-height, 超出内部滚动
  _applySigKellyYearlyMaxHeight(host);
}

// 2026-08-14 问题1: 给全信号表「按年窗口增长」表格设置 max-height = 强关联ETF(etf_strong)卡片高度, 超出内部滚动。
// 基准卡片取「按 ETF 跟踪评分分组」的 etf_strong(强关联)卡; 若该卡未渲染(无数据), 回退用同排「全信号」卡高度;
// 再不行则不动(由 CSS 兜底 max-height: 440px 兜住)。每次重渲染/周期/模式切换后调用, 保证基准实时。
function _applySigKellyYearlyMaxHeight(host) {
  var scrollEl = host.querySelector(".lab-sigkelly-all-yearly .lab-sigkelly-table-scroll");
  if (!scrollEl) return;
  var refCard = host.querySelector('.lab-sigkelly-card[data-quad="etf_strong"]');
  if (!refCard) refCard = host.querySelector(".lab-sigkelly-all-card .lab-sigkelly-card");
  if (!refCard) return;
  var refH = refCard.offsetHeight;
  if (refH > 60) scrollEl.style.maxHeight = refH + "px";
}

// 按年窗口增长 A-G 下拉切换绑定(2026-08-14): 选择模式 -> 更新 state.labSigKellyYearlyMode -> 就地替换全信号表组(含卡+按年表)
function _bindSigKellyYearlyMode(host) {
  host.querySelectorAll(".lab-sigkelly-yearly-mode-select[data-yearly-mode='1']").forEach((sel) => {
    sel.onchange = () => {
      state.labSigKellyYearlyMode = sel.value;
      const _g = host.querySelector(".lab-sigkelly-all-group");
      if (_g) _g.outerHTML = _sigKellyAllSignalGroupHtml(state.labSigKellyPeriod);
      _bindSigKellyCardEvents(host);
    };
  });
}

// 卡片级就地更新(2026-08-11 交互优化): 卡片保持挂载, 仅就地替换变化的卡片DOM, 不触碰 group/grid 容器
// 用于 toggle/费率变化后的增量刷新; 首次渲染与周期切换仍走 _renderSigKellyQuadrants(整建)
function _updateSigKellyQuadrantsInPlace(host, data, period) {
  const quads = data.quadrants || {};
  const feeStats = state.labSigKellyFeeStats;
  const cmp = _sigKellyCardComparison(quads, period, feeStats);
  host.querySelectorAll(".lab-sigkelly-card[data-quad]").forEach((oldEl) => {
    const qk = oldEl.getAttribute("data-quad");
    const q = quads[qk];
    if (!q) return;
    oldEl.outerHTML = _renderSigKellyCard(qk, q, period, cmp.map[qk] || null);
  });
  // 全信号表(最后结果)整体就地刷新: "all"伪象限不在 data.quadrants, 单独整组替换(含卡+按年表, 实时联动)
  const _allGroupEl = host.querySelector(".lab-sigkelly-all-group");
  if (_allGroupEl) _allGroupEl.outerHTML = _sigKellyAllSignalGroupHtml(period);
  // 推荐区 A/F/G 三玩法实时表就地刷新(全周期 all 口径, 随降亏组合/费率联动, 与全信号表同源)
  const _afgEl = host.querySelector(".lab-sigkelly-afg-realtime");
  if (_afgEl) _afgEl.outerHTML = _sigKellyAfgRealtimeHtml();
  _bindSigKellyCardEvents(host);
}

// 绑定水印 hoverpop 事件(桌面 hover / 移动端 tap 切换)
function _bindSigKellyWmPop(host) {
  const isTouch = window.matchMedia && window.matchMedia("(hover: none)").matches;
  // 绑定卡内三态水印 + 卡间比较水印(共用同一套 hover/click 逻辑)
  const bindWmEl = (wmEl) => {
    const pop = wmEl.querySelector(".lab-sigkelly-wm-pop-wrap");
    if (!pop) return;
    let openByClick = false;
    const show = () => { pop.style.display = "block"; _positionSigKellyWmPop(wmEl, pop); };
    const hide = () => { pop.style.display = "none"; pop.style.left = ""; };
    wmEl.addEventListener("mouseenter", () => { if (!openByClick) show(); });
    wmEl.addEventListener("mouseleave", () => { if (!openByClick) hide(); });
    wmEl.addEventListener("click", (e) => {
      e.stopPropagation();
      if (isTouch) {
        openByClick = pop.style.display !== "block";
        if (openByClick) show(); else hide();
      }
    });
  };
  host.querySelectorAll('.lab-sigkelly-wm[data-wm="1"]').forEach(bindWmEl);
  host.querySelectorAll('.lab-sigkelly-cwm[data-cwm="1"]').forEach(bindWmEl);
  // 移动端: 点别处/滚动关闭所有水印 pop(全局绑一次)
  if (isTouch && !document._sigKellyWmDocBound) {
    document._sigKellyWmDocBound = true;
    document.addEventListener("click", (e) => {
      if (e.target.closest && (e.target.closest(".lab-sigkelly-wm") || e.target.closest(".lab-sigkelly-cwm"))) return;
      document.querySelectorAll(".lab-sigkelly-wm-pop-wrap").forEach((p) => {
        if (p.style.display === "block") { p.style.display = "none"; p.style.left = ""; }
      });
    }, true);
    window.addEventListener("scroll", () => {
      document.querySelectorAll(".lab-sigkelly-wm-pop-wrap").forEach((p) => {
        if (p.style.display === "block") { p.style.display = "none"; p.style.left = ""; }
      });
    }, { passive: true, capture: true });
  }
}

// 绑定卖出模式说明 hoverpop(桌面 hover / 移动端 tap 切换), 复用水印 pop 的定位+关闭逻辑
function _bindSigKellyGuidePop(host) {
  const isTouch = window.matchMedia && window.matchMedia("(hover: none)").matches;
  host.querySelectorAll('.lab-sigkelly-guide-trigger[data-guide="1"]').forEach((trig) => {
    const pop = trig.querySelector(".lab-sigkelly-guide-pop-wrap");
    if (!pop) return;
    let openByClick = false;
    const show = () => { pop.style.display = "block"; _positionSigKellyWmPop(trig, pop); };
    const hide = () => { pop.style.display = "none"; pop.style.left = ""; };
    trig.addEventListener("mouseenter", () => { if (!openByClick) show(); });
    trig.addEventListener("mouseleave", () => { if (!openByClick) hide(); });
    trig.addEventListener("click", (e) => {
      e.stopPropagation();
      if (isTouch) {
        openByClick = pop.style.display !== "block";
        if (openByClick) show(); else hide();
      }
    });
  });
  // 移动端: 点别处/滚动关闭所有说明 pop(全局绑一次)
  if (isTouch && !document._sigKellyGuideDocBound) {
    document._sigKellyGuideDocBound = true;
    document.addEventListener("click", (e) => {
      if (e.target.closest && e.target.closest(".lab-sigkelly-guide-trigger")) return;
      document.querySelectorAll(".lab-sigkelly-guide-pop-wrap").forEach((p) => {
        if (p.style.display === "block") { p.style.display = "none"; p.style.left = ""; }
      });
    }, true);
    window.addEventListener("scroll", () => {
      document.querySelectorAll(".lab-sigkelly-guide-pop-wrap").forEach((p) => {
        if (p.style.display === "block") { p.style.display = "none"; p.style.left = ""; }
      });
    }, { passive: true, capture: true });
  }
}

// 绑定 AI仓位建议 K档位评级 hoverpop 已迁移至 common.js _bindAiPoscapRatePop(2026-08-13, 共享单一数据源 §22, 与首页 app.js 同款), 本处不再重复定义


// 组内各卖出模式比较水印
// kind: top1(可操作层全>0) / out(全≤0淘汰) / mix(有正有负分化)
// #25 A包(2026-08-14): TOP1 推荐算法修正——先看可操作性层(峰持仓≤20万=≤20倍单次本金), 再按【收益率 return_pct_max_holding】排序, 不再按净盈亏 total_profit
//   用户原话"优秀的数据首先是看可操作性, 其次是看收益率, 净盈亏和最大持仓只是佐证没有比较意义"。GIH on 时 G/H/I 读 __gihb1(cap后乐观b1, 已可操作); 不可操作模式(GIH off 的 G/H/I)不参与 TOP1 推荐
// X=可操作层内收益率最高的方案字母; 辅助(仅top1/mix态): 风险橙(高仓/样本少)+优势绿(高胜率/低回撤/高夏普)
function _sigKellyWatermark(pdata) {
  const _gihOn = !!state.labSigKellyGihOn;
  // #25 A包(需求D): K-OFF(positionCap关, 无仓位限制)时即使 A-F 也可能峰持仓>20倍不可操作, 与需求② GIH off 同用 _kellyOpElimination 统一判据(峰持仓≤20万)
  const _posCapOn = !!((state.labSigKellyFilters || {}).positionCap);
  // 过滤 #49 GIH 伪模式键(mode+"__gihb0/b1/peak"), 只遍历真实模式(A-J), 防伪键污染水印top/均值(§21§22)
  const modes = Object.keys(pdata).filter(m => m.indexOf("__") < 0);
  const items = modes.map(m => {
    const x = _kellyOpElimination(pdata, m, _gihOn, _posCapOn); // GIH on 时 G/H/I 取 __gihb1; K-OFF/A-F 也判峰持仓
    const r = x ? x.r : null;
    if (!r) return null;
    return { m, operable: x.operable, reason: x.reason, tp: r.total_profit || 0, rmh: (r.return_pct_max_holding == null ? 0 : r.return_pct_max_holding),
             hk: (r.half_kelly == null ? 0 : r.half_kelly), n: r.n || 0,
             wr: (r.win_rate == null ? 0 : r.win_rate), md: (r.max_drawdown_pct == null ? 999 : r.max_drawdown_pct), sh: (r.sharpe == null ? 0 : r.sharpe) };
  }).filter(Boolean);
  if (items.length < 2) return null;
  // 可操作层(参与推荐) = operable 为真; 不可操作模式不参与 TOP1 但保留在 compares 展示(逐位对比仍显示其净盈亏)
  // 若全部不可操作(极端), 退回全模式计算(保证 top1/淘汰语义仍可用, 只是标注可操作性缺位)
  const cand = items.filter(x => x.operable).length ? items.filter(x => x.operable) : items;
  const pos = cand.filter(x => x.tp > 0);
  const hasNeg = cand.some(x => x.tp <= 0);
  let kind;
  if (pos.length === 0) kind = "out";
  else if (hasNeg) kind = "mix";
  else kind = "top1";
  // #25 A包 核心: 排序键 = 收益率(rmh), 先可操作层过滤(已在 cand 上); 不再 b.tp-a.tp 净盈亏
  const top = cand.slice().sort((a, b) => b.rmh - a.rmh)[0];
  const auxRisk = [], auxGood = [];
  if (kind !== "out") {
    if (top.hk >= 60) auxRisk.push("高仓");
    if (top.n < 100) auxRisk.push("样本少");
    if (top.wr >= 0.5) auxGood.push("高胜率");
    if (top.md <= 15) auxGood.push("低回撤");
    if (top.sh >= 1.0) auxGood.push("高夏普");
  }
  const kindText = { top1: "TOP1", out: "淘汰", mix: "分化" }[kind];
  const mainText = kind === "out" ? "淘汰" : `${kindText}·${top.m}`;
  let auxHtml = "";
  if (kind !== "out") {
    if (auxRisk.length) auxHtml += `<span class="lab-sigkelly-wm-aux lab-sigkelly-wm-aux-risk">${auxRisk.join("/")}</span>`;
    if (auxGood.length) auxHtml += `<span class="lab-sigkelly-wm-aux lab-sigkelly-wm-aux-good">${auxGood.join("/")}</span>`;
  }
  const text = auxHtml ? `${mainText}${auxHtml}` : mainText;
  const auxAll = [...auxRisk, ...auxGood];
  // #25 A包: title 优先展示收益率(推荐排序键)再展示净盈亏(佐证), 用户语义"先可操作性→再收益率→净盈亏佐证"
  const title = `${kindText}·${top.m} | 收益率${top.rmh.toFixed(2)}%·盈亏${top.tp.toFixed(0)}` + (auxAll.length ? ` | ${auxAll.join("/")}` : "");
  // items 供 hoverpop 渲染各模式盈亏对比; auxRisk/auxGood 供辅助标签说明; top=最高方案
  return { kind, text, title, items, auxRisk, auxGood, top };
}

// 组比较水印 hoverpop: 悬停水印 badge 弹出说明(三态定义+卖出模式含义+盈亏对比+辅助标签)
// wm = _sigKellyWatermark 返回值(含 items/auxRisk/auxGood/top)
function _sigKellyWmPopupHtml(wm) {
  const modeLabels = _sigKellyModeLabels();
  // 本组各模式对比: 每个模式显示【收益率(推荐排序键)+净盈亏佐证】; 不可操作(GIH off 的 G/H/I 原仓位>20倍)标"无操作性"灰化不参与推荐, 正红负绿与表格一致
  const cmpRows = wm.items.map((it) => {
    const tpStr = (it.tp >= 0 ? "+" : "") + it.tp.toFixed(0);
    const rmhStr = (it.rmh != null ? (it.rmh >= 0 ? "+" : "") + it.rmh.toFixed(2) + "%" : "-");
    const cls = it.tp >= 0 ? "lab-sigkelly-pos" : "lab-sigkelly-neg";
    const hi = (wm.top && it.m === wm.top.m) ? " lab-sigkelly-wm-cmp-hi" : "";
    const noOp = it.operable ? "" : " lab-sigkelly-wm-cmp-noop";
    const noOpBadge = it.operable ? "" : ` <span class="lab-sigkelly-wm-cmp-noop-badge" title="峰值同时持仓超20倍单次本金, 不可操作(${it.reason || "无操作性"}), 不参与TOP1推荐; 需求②开ai长线硬控/需求D切K=1-4后可操作">${it.reason || "无操作性"}</span>`;
    return `<div class="lab-sigkelly-wm-cmp-row${hi}${noOp}"><span class="lab-sigkelly-wm-cmp-m">${it.m}</span><span class="lab-sigkelly-wm-cmp-lbl">${modeLabels[it.m] || ""}</span><span class="${cls}">${rmhStr}</span><span class="lab-sigkelly-wm-cmp-tp">盈亏${tpStr}</span>${noOpBadge}</div>`;
  }).join("");
  // 辅助标签说明(仅 top1/mix 显示当前命中标签 + 全量图例)
  let auxHtml = "";
  if (wm.kind !== "out") {
    const hitRisk = wm.auxRisk.length
      ? wm.auxRisk.map((a) => `<span class="lab-sigkelly-wm-aux lab-sigkelly-wm-aux-risk">${a}</span>`).join("")
      : '<span class="lab-sigkelly-wm-aux-none">无</span>';
    const hitGood = wm.auxGood.length
      ? wm.auxGood.map((a) => `<span class="lab-sigkelly-wm-aux lab-sigkelly-wm-aux-good">${a}</span>`).join("")
      : '<span class="lab-sigkelly-wm-aux-none">无</span>';
    auxHtml =
      `<div class="lab-sigkelly-wm-sec">` +
        `<div class="lab-sigkelly-wm-sub">本组最高方案(${wm.top.m})命中标签</div>` +
        `<div class="lab-sigkelly-wm-aux-hit">风险: ${hitRisk} · 优势: ${hitGood}</div>` +
        `<div class="lab-sigkelly-wm-legend">标签含义: 高仓=半凯利仓位≥60% / 样本少=交易笔数&lt;100 / 高胜率=胜率≥50% / 低回撤=最大回撤≤15% / 高夏普=夏普≥1.0</div>` +
      `</div>`;
  }
  // 卖出模式含义(动态从 sell_modes 生成,不止盈模式标注"不止盈")
  const _sm = (state.labSigKellyData && state.labSigKellyData.config && state.labSigKellyData.config.sell_modes) || {};
  const modeDesc = Object.keys(_sm).map((k) => {
    const d = _sm[k];
    if (!d) return k;
    // G/H/I 信号驱动模式有 desc, 用 desc 替代"不止盈"标注(它们非止盈类, 是信号触发)
    return d.desc ? `${k}=${d.label}(${d.desc})` : (d.stop_profit == null ? `${k}=${d.label}(不止盈)` : `${k}=${d.label}`);
  }).join(" · ");
  return (
    `<div class="lab-sigkelly-wm-pop">` +
      `<div class="lab-sigkelly-wm-pop-title">组比较水印说明</div>` +
      `<div class="lab-sigkelly-wm-sec">` +
        `<div class="lab-sigkelly-wm-sub">三态定义</div>` +
        `<div class="lab-sigkelly-wm-li"><b>TOP1·X</b>: 可操作层各方案最终盈亏全为正,X 为推荐方案(收益率最高)</div>` +
        `<div class="lab-sigkelly-wm-li"><b>分化·X</b>: 可操作层有正有负,X 为推荐方案</div>` +
        `<div class="lab-sigkelly-wm-li"><b>淘汰</b>: 可操作层各方案最终盈亏全≤0</div>` +
        `<div class="lab-sigkelly-wm-li lab-sigkelly-wm-li-x">推荐规则: ①先看可操作性(峰值同时持仓≤20万=≤20倍单次本金, 不可操作模式不推荐) ②再看收益率(峰值资金收益率 return_pct_max_holding) ③净盈亏/最大持仓只是佐证, 不比排序。X = 可操作层中收益率最高的方案字母。例(G 模式开关对比, 决策链走①②③)：关(旧FIFO)峰值持仓 136 万=不可操作, 即便净利 +64.2万 全模式最高也先被①淘汰; 开(13万 P≤3d)峰值 13 万=可操作, 再按②收益率排, b0 188.88% 胜出→推荐 G@13万(v1.1.7 基准定稿), 净利/持仓只当佐证不当排序【核实源:kelly-g-mode-recheck.md】</div>` +
        `<div class="lab-sigkelly-wm-li lab-sigkelly-wm-li-noop">删除线/无操作性标灰=峰值同时持仓超20倍单次本金, 不可操作(不参与推荐)。两种触发: 需求②GIH未开(原始 G/H/I 136万/45万/111万)→开「ai长线(G/H/I)仓位管理」套对应模式仓位法(G=P≤3d@13万/H=满仓不买@7万/I=满仓不买@16万, 峰持仓≤20倍可操作); 需求D K档关(无仓位限制每笔1万全买)→切K=1-4(每笔=10000/N有仓位控制)。本卡A-F在该口径下峰持仓≤20倍则可操作仍参与推荐</div>` +
      `</div>` +
      `<div class="lab-sigkelly-wm-sec">` +
        `<div class="lab-sigkelly-wm-sub">卖出模式含义</div>` +
        `<div class="lab-sigkelly-wm-li">${modeDesc}</div>` +
      `</div>` +
      `<div class="lab-sigkelly-wm-sec">` +
        `<div class="lab-sigkelly-wm-sub">本组各模式收益率+净盈亏对比(收益率为主, 净盈亏佐证)</div>` +
        `<div class="lab-sigkelly-wm-cmp">${cmpRows}</div>` +
      `</div>` +
      auxHtml +
    `</div>`
  );
}

// 定位水印 hoverpop: 水印下方右对齐, 仅水平边界检测(top:100% 由 CSS 提供, 与 etf-popup 同模式)
function _positionSigKellyWmPop(wmEl, pop) {
  var pw = pop.offsetWidth;
  var wmRect = wmEl.getBoundingClientRect();
  // left 相对 wm(默认0=对齐wm左缘); 右越界左移(负值), 但不超左边界
  var left = Math.min(0, window.innerWidth - 8 - pw - wmRect.left);
  left = Math.max(left, 8 - wmRect.left);
  pop.style.left = left + "px";
}

// 卡间比较水印(全局16张卡互比): 每周期选1综合最佳(蓝星)+1最稳定(紫菱)
// 用户选选项C(全局+比率折中): 仅用比率指标(胜率/年化/夏普,不受n影响)+排除n<30+全局min-max归一化
// 综合分 = 胜率35% + 年化35% + 夏普30% (排除盈亏比,因受n累积影响)
// 稳定分 = (1-最大回撤)40% + 胜率30% + 夏普30% (无std用sharpe替代)
// 卡级指标 = N模式均值(动态读 config.sell_modes, A-J 10模式), 过滤n<30模式防小样本虚高
function _sigKellyCardComparison(quads, period, feeStats) {
  const allKeys = [
    "rating_high", "rating_mid", "rating_low",
    "etf_strong", "etf_related", "etf_approx", "etf_has_track",
    "sig_main", "sig_aux", "sig_special", "sig_backup",
    "mkt_a", "mkt_hk", "mkt_global", "mkt_industry", "mkt_concept"
  ];
  const cards = [];
  for (const qk of allKeys) {
    const q = quads[qk];
    if (!q) continue;
    const periods = q.periods || {};
    const pdata = (feeStats && feeStats[qk] && feeStats[qk][period]) ? feeStats[qk][period] : (periods[period] || {});
    // 过滤 #49 GIH 伪模式键(mode+"__gihb0/b1/peak"), 防卡级均值/模式数被伪键稀释错乱(§21§22)
    const modes = Object.keys(pdata).filter(m => m.indexOf("__") < 0);
    // 过滤 n<30 的模式
    const validModes = modes.filter((m) => {
      const r = pdata[m];
      return r && r.n != null && r.n >= 30;
    });
    if (validModes.length === 0) { cards.push({ qk, skip: true }); continue; }
    // 卡级指标 = 有效模式均值
    const avg = (field) => {
      let sum = 0, cnt = 0;
      for (const m of validModes) {
        const v = pdata[m][field];
        if (v != null) { sum += v; cnt++; }
      }
      return cnt > 0 ? sum / cnt : null;
    };
    cards.push({
      qk, skip: false,
      winRate: avg("win_rate"), annRet: avg("annualized_return"),
      sharpe: avg("sharpe"), maxDD: avg("max_drawdown_pct"),
      modeCount: validModes.length,   // 有效模式数(过滤 n>=30)
      totalModes: modes.length        // 总模式数(动态, A-J 10模式)
    });
  }
  const validCards = cards.filter((c) => !c.skip);
  if (validCards.length < 2) return { best: null, stable: null, map: {} };
  // 全局 min-max 归一化
  const normField = (arr, field, invert) => {
    const vals = arr.map((c) => c[field]).filter((v) => v != null);
    if (vals.length === 0) return {};
    const mn = Math.min(...vals), mx = Math.max(...vals);
    const res = {};
    for (const c of arr) {
      if (c[field] == null || mx === mn) { res[c.qk] = 0.5; continue; }
      res[c.qk] = invert ? (mx - c[field]) / (mx - mn) : (c[field] - mn) / (mx - mn);
    }
    return res;
  };
  const wrN = normField(validCards, "winRate", false);
  const annN = normField(validCards, "annRet", false);
  const shN = normField(validCards, "sharpe", false);
  const mdN = normField(validCards, "maxDD", true); // 越小越好, 反转
  // 算分
  for (const c of validCards) {
    c.wrN = wrN[c.qk] != null ? wrN[c.qk] : 0.5;
    c.annN = annN[c.qk] != null ? annN[c.qk] : 0.5;
    c.shN = shN[c.qk] != null ? shN[c.qk] : 0.5;
    c.mdN = mdN[c.qk] != null ? mdN[c.qk] : 0.5;
    // 综合分 = 胜率35% + 年化35% + 夏普30%
    c.bestScore = c.wrN * 0.35 + c.annN * 0.35 + c.shN * 0.30;
    // 稳定分 = (1-最大回撤)40% + 胜率30% + 夏普30%
    c.stableScore = c.mdN * 0.40 + c.wrN * 0.30 + c.shN * 0.30;
  }
  const sortedBest = validCards.slice().sort((a, b) => b.bestScore - a.bestScore);
  const sortedStable = validCards.slice().sort((a, b) => b.stableScore - a.stableScore);
  const best = sortedBest[0], stable = sortedStable[0];
  const bestRank = {}, stableRank = {};
  sortedBest.forEach((c, i) => { bestRank[c.qk] = i + 1; });
  sortedStable.forEach((c, i) => { stableRank[c.qk] = i + 1; });
  const map = {};
  for (const c of validCards) {
    map[c.qk] = {
      isBest: c === best,
      isStable: c === stable,
      bestScore: c.bestScore,
      stableScore: c.stableScore,
      bestRank: bestRank[c.qk],
      stableRank: stableRank[c.qk],
      total: validCards.length,
      winRate: c.winRate, annRet: c.annRet, sharpe: c.sharpe, maxDD: c.maxDD,
      modeCount: c.modeCount, totalModes: c.totalModes
    };
  }
  return { best, stable, map };
}

// 卡间比较水印 hoverpop: 评级公式说明(§21公示同步) + 该卡全局排名+得分
function _sigKellyCwmPopupHtml(cmp) {
  const wrStr = cmp.winRate != null ? (cmp.winRate * 100).toFixed(1) + "%" : "-";
  const annStr = cmp.annRet != null ? cmp.annRet.toFixed(2) + "%" : "-";
  const shStr = cmp.sharpe != null ? cmp.sharpe.toFixed(2) : "-";
  const mdStr = cmp.maxDD != null ? cmp.maxDD.toFixed(2) + "%" : "-";
  let cardSec = "";
  if (cmp.isBest || cmp.isStable) {
    const bestTag = cmp.isBest ? ' <span class="lab-sigkelly-wm-aux lab-sigkelly-wm-aux-good">综合最佳</span>' : "";
    const stableTag = cmp.isStable ? ' <span class="lab-sigkelly-wm-aux lab-sigkelly-wm-aux-good">最稳定</span>' : "";
    cardSec =
      `<div class="lab-sigkelly-wm-sec">` +
        `<div class="lab-sigkelly-wm-sub">本卡成绩(全局${cmp.total}张卡互比)</div>` +
        `<div class="lab-sigkelly-wm-li">综合分: <b>${cmp.bestScore.toFixed(3)}</b> · 全局第 <b>${cmp.bestRank}</b>/${cmp.total}${bestTag}</div>` +
        `<div class="lab-sigkelly-wm-li">稳定分: <b>${cmp.stableScore.toFixed(3)}</b> · 全局第 <b>${cmp.stableRank}</b>/${cmp.total}${stableTag}</div>` +
        `<div class="lab-sigkelly-wm-li">胜率 ${wrStr} · 年化 ${annStr} · 夏普 ${shStr} · 最大回撤 ${mdStr} · 有效模式 ${cmp.modeCount}/${cmp.totalModes}</div>` +
      `</div>`;
  }
  return (
    `<div class="lab-sigkelly-wm-pop">` +
      `<div class="lab-sigkelly-wm-pop-title">卡间比较水印说明</div>` +
      `<div class="lab-sigkelly-wm-sec">` +
        `<div class="lab-sigkelly-wm-sub">评级公式</div>` +
        `<div class="lab-sigkelly-wm-li"><b>★综合最佳</b>: 综合分 = 胜率&times;35% + 年化收益&times;35% + 夏普&times;30%</div>` +
        `<div class="lab-sigkelly-wm-li lab-sigkelly-wm-li-x">排除盈亏比(受样本数累积影响), 仅用比率指标</div>` +
        `<div class="lab-sigkelly-wm-li"><b>◆最稳定</b>: 稳定分 = (1-最大回撤)&times;40% + 胜率&times;30% + 夏普&times;30%</div>` +
        `<div class="lab-sigkelly-wm-li lab-sigkelly-wm-li-x">夏普替代收益波动率(无std字段), 夏普高=风险调整收益好=稳定</div>` +
      `</div>` +
      `<div class="lab-sigkelly-wm-sec">` +
        `<div class="lab-sigkelly-wm-sub">计算口径</div>` +
        `<div class="lab-sigkelly-wm-li">卡级指标 = 卡内${cmp.totalModes}模式均值(动态读 sell_modes), 先过滤 n&lt;30 模式防小样本虚高</div>` +
        `<div class="lab-sigkelly-wm-li">年化 = 峰值资金收益率(总盈亏/峰值持仓资金)开方, 非平均化收益率</div>` +
        `<div class="lab-sigkelly-wm-li">全局 min-max 归一化: 16张卡跨组互比, 每指标归一到 0~1</div>` +
        `<div class="lab-sigkelly-wm-li">越小越好指标(最大回撤)反转归一化</div>` +
        `<div class="lab-sigkelly-wm-li">每周期选综合分最高1张 + 稳定分最高1张, 可同一张卡兼得</div>` +
      `</div>` +
      cardSec +
    `</div>`
  );
}

// 卡片置顶: 全信号表卡+16子域卡共用 localStorage(按 data-quad 标识), 置顶卡片集中显示在最前部(已置顶区)
// 2026-08-13 用户需求: "盯住置顶"方便调试降亏排序; 只影响展示顺序, 不动卡片内容/排序算法(§23.3 覆盖全信号+全子域卡)
const _SIGKELLY_PIN_KEY = "tds_lab_sigkelly_pinned";
function _sigKellyPinnedKeys() {
  try { const a = JSON.parse(localStorage.getItem(_SIGKELLY_PIN_KEY) || "[]"); return Array.isArray(a) ? a.filter((k) => typeof k === "string") : []; }
  catch (e) { return []; }
}
function _sigKellyIsPinned(qk) { return _sigKellyPinnedKeys().indexOf(qk) >= 0; }
function _sigKellySetPinned(qk, on) {
  const arr = _sigKellyPinnedKeys();
  const i = arr.indexOf(qk);
  const was = i >= 0;
  if (on && !was) arr.push(qk);   // 保持置顶顺序: 后置顶的补到队尾, 已置顶区按首次置顶序排列
  if (!on && was) arr.splice(i, 1);
  try { localStorage.setItem(_SIGKELLY_PIN_KEY, JSON.stringify(arr)); } catch (e) {}
}

// 单象限卡片: 各卖出模式宽表(动态从 sell_modes 读取) + 跟单指引
// 主表+进阶表合并为一张宽表(14列),details 折叠已移除常显;最大持仓显笔数+资金
function _renderSigKellyCard(qk, q, period, cardCmp) {
  // fix(#1回归): 置顶改动(27047ecf7)误删 periods 声明,补回避免 ReferenceError
  const periods = q.periods || {};
  // 费率客调: 如果有重算stats,用重算值替换原始stats(结构一致)
  const feeStats = state.labSigKellyFeeStats;
  const pdata = (feeStats && feeStats[qk] && feeStats[qk][period]) ? feeStats[qk][period] : (periods[period] || {});
  const modes = _sigKellyModeKeys();
  const modeLabels = _sigKellyModeLabels();
  const guidance = q.guidance || {};
  const hasGuide = modes.some((m) => guidance[m]);
  let rows = "";
  for (const m of modes) {
    // #49+#xx ai长线模式(G/H/I)仓位管理: 开时对 G/H/I 模式卡片行套各模式独立仓位策略后的数值(乐观 b1 口径, b0 区间见对比表; §22 双口径说明在对比表)
    // #25 A包(2026-08-14): GIH off(G/H/I 未套各模式仓位法、原仓位>20倍)时, 该行标"淘汰·无操作性"(删除线+角标+hoverpop理由), 非从列表消失; GIH on(cap后可操作)不标
    const _gihOnThis = !!state.labSigKellyGihOn;
    const _gihRow = _gihOnThis && _kellyIsGih(m) ? (pdata[m + "__gihb1"] || null) : null;
    const r = _gihRow || pdata[m];
    const _gihBadge = _kellyIsGih(m) && _gihOnThis && _gihRow ? `<span class="lab-sigkelly-gih-badge" title="ai长线模式仓位管理已开: 本行套「${_kellyGihStratShort(m) || ""}」仓位法(${_kellyGihStratExplain(m)})后的乐观b1口径, 保守b0见对比表(真实值在区间)">AI长线·开 ${_kellyGihStratShort(m) || ""}</span>` : "";
    // 可操作性淘汰判定(需求②GIH off 无操作性 + 需求D K-OFF 无仓位限制): 卡片行统一走 _kellyOpElimination, 与三玩法/全信号表/水印同判据(§23.3)
    const _opPosCapOn = !!((state.labSigKellyFilters || {}).positionCap);
    const _opFlag = _kellyOpElimination(pdata, m, _gihOnThis, _opPosCapOn);
    const _opElim = _opFlag ? _opFlag.eliminated : false;
    const _opTip = _opFlag ? _opFlag.tip : "";
    const _opReason = _opFlag && _opFlag.eliminated ? _opFlag.reason : "";
    if (!r) {
      rows += `<tr><td><b>${m}</b><span class="lab-sigkelly-modelbl">${modeLabels[m] || ""}</span></td><td colspan="14" class="lab-sigkelly-empty">无数据</td></tr>`;
      continue;
    }
    const hk = (r.half_kelly == null) ? 0 : r.half_kelly;
    const tier = r.kelly_tier || "保守";
    const tierCls = hk >= 60 ? "lab-kelly-aggressive" : hk >= 30 ? "lab-kelly-balanced" : "lab-kelly-conservative";
    const n = r.n || 0;
    const nStr = n < 100 ? `<span class="lab-sigkelly-nwarn" title="样本量少,统计意义弱">⚠️${n}</span>` : `${n}`;
    const pl = r.pl_ratio;
    const plStr = (pl == null || pl <= 0) ? "-" : pl.toFixed(2);
    const wr = (r.win_rate == null) ? "-" : (r.win_rate * 100).toFixed(1) + "%";
    const mr = (r.mean_return == null) ? "-" : r.mean_return.toFixed(2) + "%";
    // 进阶指标(原 details 折叠表,现合并进主表)
    const tp = r.total_profit || 0;
    const tpStr = (tp >= 0 ? "+" : "") + tp.toFixed(0);
    // 费率消耗(总): 该象限x周期x模式下所有笔费率消耗求和,随费率档切换实时更新
    const fc = r.total_fee_cost;
    const fcStr = (fc != null) ? "-" + fc.toFixed(0) : "-";
    // 峰值资金收益率 = 最终盈亏 / 峰值占用资金 (前移到最终盈亏后面, 突出展示)
    const rmhVal = r.return_pct_max_holding;
    const rmh = rmhVal != null ? rmhVal.toFixed(2) + "%" : "-";
    // 最大持仓: 笔数(max_concurrent) + 资金(max_concurrent_capital),笔数加粗显眼
    const mc = r.max_concurrent || 0;
    const mcc = r.max_concurrent_capital || 0;
    const mcStr = mc ? `<b class="lab-sigkelly-mc-n">${mc}</b>笔 / ${(mcc >= 10000 ? (mcc / 10000).toFixed(1) + "万" : Math.round(mcc))}` : "-";
    // 持仓中: 笔数(holding_count) + 占用资金(holding_capital),预估盈亏已计入统计
    const hc = r.holding_count || 0;
    const hcap = r.holding_capital || 0;
    const hcStr = hc ? `<b class="lab-sigkelly-hc-n">${hc}</b>笔 / ${(hcap >= 10000 ? (hcap / 10000).toFixed(1) + "万" : Math.round(hcap))}` : "-";
    const ann = r.annualized_return != null ? r.annualized_return.toFixed(2) + "%" : "-";
    const sh = r.sharpe != null ? r.sharpe.toFixed(2) : "-";
    const md = r.max_drawdown_pct != null ? r.max_drawdown_pct.toFixed(2) + "%" : "-";
    const cm = r.calmar != null ? r.calmar.toFixed(2) : "-";
    // #25 A包(需求②+需求D): 不可操作(峰持仓>20倍)行加删除线灰化 + 淘汰角标 + hoverpop 淘汰理由(无操作性 / 无仓位限制·无法实操)
    const _opRowCls = _opElim ? " lab-sigkelly-eliminated-row lab-sigkelly-opelim-row" : "";
    const _opRowTip = _opElim ? `淘汰·${_opReason}: ${_opTip || ""}` : "点击查看交易记录";
    const _opBadge = _opElim ? `<span class="lab-sigkelly-exec-badge" title="${_opTip || _opReason}">淘汰·${_opReason}</span>` : "";
    rows +=
      `<tr class="lab-sigkelly-trade-row${_opRowCls}" data-quad="${qk}" data-mode="${m}" data-period="${period}" data-opelim="${_opElim ? "1" : "0"}" title="${_opRowTip}">` +
        `<td><b>${m}</b><span class="lab-sigkelly-modelbl">${modeLabels[m] || ""}</span>${_gihBadge}${_opBadge}</td>` +
        `<td class="lab-sigkelly-hk"><span class="lab-kelly-tier ${tierCls}">${hk.toFixed(1)}%</span><span class="lab-sigkelly-tier">${tier}</span></td>` +
        `<td>${wr}</td><td>${plStr}</td><td>${mr}</td><td>${nStr}</td>` +
        `<td class="lab-sigkelly-tp-hl ${tp >= 0 ? "lab-sigkelly-pos" : "lab-sigkelly-neg"}">${tpStr}元</td>` +
        `<td class="lab-sigkelly-rmh ${rmhVal == null ? "" : (rmhVal >= 0 ? "lab-sigkelly-pos" : "lab-sigkelly-neg")}" title="=总盈亏/峰值同时持仓资金,随回测周期增长">${rmh}</td>` +
        `<td class="lab-sigkelly-neg lab-sigkelly-fee">${fcStr}</td>` +
        `<td class="lab-sigkelly-mc">${mcStr}</td><td class="lab-sigkelly-holding">${hcStr}</td><td>${ann}</td>` +
        `<td>${sh}</td><td>${md}</td><td>${cm}</td>` +
      `</tr>`;
  }
  const wm = _sigKellyWatermark(pdata);
  // 卡间比较水印(标题行右侧): 蓝星综合最佳 + 紫菱最稳定, 不撞现有右上角三态水印
  let cwmHtml = "";
  if (cardCmp && (cardCmp.isBest || cardCmp.isStable)) {
    let badges = "";
    if (cardCmp.isBest) badges += `<span class="lab-sigkelly-cwm-badge lab-sigkelly-cwm-best">★综合最佳</span>`;
    if (cardCmp.isStable) badges += `<span class="lab-sigkelly-cwm-badge lab-sigkelly-cwm-stable">◆最稳定</span>`;
    cwmHtml = `<div class="lab-sigkelly-cwm" data-cwm="1">${badges}<div class="lab-sigkelly-wm-pop-wrap lab-sigkelly-cwm-pop-wrap" style="display:none">${_sigKellyCwmPopupHtml(cardCmp)}</div></div>`;
  }
  const _pinned = _sigKellyIsPinned(qk);
  return (
    `<div class="lab-sigkelly-card${_pinned ? " lab-sigkelly-card-pinned" : ""}" data-quad="${qk}">` +
      (wm ? `<div class="lab-sigkelly-wm lab-sigkelly-wm-${wm.kind}" data-wm="1"><span class="lab-sigkelly-wm-badge">${wm.text}</span><div class="lab-sigkelly-wm-pop-wrap" style="display:none">${_sigKellyWmPopupHtml(wm)}</div></div>` : ``) +
      `<div class="lab-sigkelly-card-head">` +
        `<div class="lab-sigkelly-card-name"><span>${q.label || qk}</span>` +
          `<button type="button" class="lab-sigkelly-pin-btn${_pinned ? " active" : ""}" data-pin-quad="${qk}" title="${_pinned ? "点击取消置顶" : "点击置顶此卡片(放最前部盯住)"}" aria-label="置顶/取消置顶">📌</button>` +
        `</div>` +
        `<div class="lab-sigkelly-card-desc">${q.desc || ""}` +
        (hasGuide
          ? ` <span class="lab-sigkelly-guide-trigger" data-guide="1">卖出模式说明❓` +
              `<div class="lab-sigkelly-guide-pop-wrap" style="display:none">` +
                `<div class="lab-sigkelly-wm-pop"><div class="lab-sigkelly-wm-pop-title">卖出模式说明</div>` +
                modes.filter((m) => guidance[m]).map((m) => `<div class="lab-sigkelly-guide-item"><b>${m}:</b> ${guidance[m]}</div>`).join("") +
                `</div>` +
              `</div>` +
            `</span>`
          : ``) +
        `</div>` +
      `</div>` +
      (cwmHtml ? `<div class="lab-sigkelly-cwm-row">` + cwmHtml + `</div>` : ``) +
      `<div class="lab-sigkelly-table-scroll">` +
      `<table class="lab-sigkelly-table lab-sigkelly-wide-table">` +
        `<thead><tr><th>模式</th><th>半凯利仓位</th><th>胜率</th><th>盈亏比</th><th>单笔均收益率</th><th>样本</th><th>最终盈亏<br>(元)</th><th title="=总盈亏/峰值同时持仓资金,随回测周期增长">峰值资金<br>收益率</th><th>费率消耗</th><th>最大持仓</th><th>持仓中</th><th>年化</th><th>夏普</th><th>最大回撤</th><th>卡尔玛</th></tr></thead>` +
        `<tbody>${rows}</tbody>` +
      `</table>` +
      `</div>` +
    `</div>`
  );
}

// 交易记录弹窗(懒加载 trades JSON, 按 quad x mode x period 过滤, 可排序/筛选)
async function _openSigKellyTradesModal(quadKey, modeKey, period) {
  const data = state.labSigKellyData;
  if (!data) return;
  const cfg = data.config || {};
  const cutoffs = cfg.period_cutoffs || {};
  const cutoff = cutoffs[period] || "0";
  const quadLabel = (data.quadrants[quadKey] || {}).label || quadKey;
  const modeLabel = _sigKellyModeLabelWith(modeKey, (cfg.sell_modes || {})[modeKey]?.label || modeKey);

  // 创建 overlay
  let overlay = document.getElementById("lab-sigkelly-trades-overlay");
  if (!overlay) {
    overlay = document.createElement("div");
    overlay.id = "lab-sigkelly-trades-overlay";
    overlay.className = "lab-sigkelly-overlay";
    document.body.appendChild(overlay);
  }
  overlay.innerHTML = `<div class="lab-sigkelly-modal"><div class="lab-sigkelly-modal-loading">⏳ 加载交易记录…</div></div>`;
  overlay.style.display = "flex";

  // 懒加载 trades JSON(分片加载+localStorage缓存, 2026-08-28)
  if (!state.labSigKellyTradesData) {
    const ok = await _labKellyTradesEnsure();
    if (!ok) {
      overlay.innerHTML = `<div class="lab-sigkelly-modal"><div class="lab-custom-error"><div class="lab-custom-error-title">⚠️ 交易记录加载失败</div><div class="lab-custom-error-detail">${_labKellyLoadErr || "unknown"}</div><button type="button" class="lab-custom-retry">重试</button></div></div>`;
      overlay.querySelector(".lab-custom-retry").onclick = () => { state.labSigKellyTradesData = null; state.labSigKellyTradeDims = null; _labKellyFullFallback = false; _openSigKellyTradesModal(quadKey, modeKey, period); };
      return;
    }
  }

  const td = state.labSigKellyTradesData;
  const fields = td.fields || ["signal_date", "buy_date", "sell_date", "etf_code", "etf_name", "buy_price", "sell_price", "shares", "profit", "return_pct", "hold_days", "sell_reason"];
  // 全信号伪象限「all」= rating_high+mid+low 并集(与卡片统计一致, §22数据一致性)
  let rawTrades;
  if (quadKey === "all") {
    rawTrades = [];
    ["rating_high", "rating_mid", "rating_low"].forEach((_rk) => {
      const _qq = (td.quadrants || {})[_rk]?.[modeKey] || [];
      rawTrades = rawTrades.concat(_qq);
    });
  } else {
    rawTrades = (td.quadrants || {})[quadKey]?.[modeKey] || [];
  }
  const _fIdx = {};
  fields.forEach((f, i) => { _fIdx[f] = i; });

  // 按周期 + 降亏toggle过滤(与卡片统计一致, §22数据一致性)
  var _filters = state.labSigKellyFilters || _kellyDefaultFilters();
  // v3标志需维度查找map
  var _tradeDims2 = state.labSigKellyTradeDims;
  if (!_tradeDims2 && td.quadrants) {
    _tradeDims2 = _kellyBuildTradeDims(td, _fIdx);
    state.labSigKellyTradeDims = _tradeDims2;
  }
  // positionCap 仓位控制过滤(2026-08-13): 与卡片统计口径一致(§22数据一致性); 金额口径=每日资金池等分+top-K(每笔=10000/当日保留数, 恢复2026-08-13)
  // 降亏过滤谓词抽成命名函数供基笔池复用(不含period cutoff: cutoff只用于弹窗当前周期显示, 池需全周期一致)
  // 2026-08-12 P2-2修复: 直接调共享谓词 _kellyPassesFadeFilters(消除逐条复制漂移, 补齐 v4 12 toggle 生效, 弹窗与卡片统计一致 §22)
  // #xx(2026-08-22) bullAuxBackupStop G/H/I 豁免: 本弹窗 modeKey∈{G,H,I} 且新键开 → 谓词/基笔池/每日池计数全用
  //   NoBull 变体(bullAuxBackupStop=false 其余同), 与卡片统计桶层豁免同口径(§22); A-F 短线模式不受影响。
  var _pcMonthMask = _kellyActiveMonthMask(_filters);
  var _bullOnM = !!_filters.bullAuxBackupStop && (modeKey === "G" || modeKey === "H" || modeKey === "I");
  var _pcFadeFn;
  if (_bullOnM) {
    var _fNB2 = {};
    for (var _fk2 in _filters) _fNB2[_fk2] = _filters[_fk2];
    _fNB2.bullAuxBackupStop = false;
    _pcFadeFn = (function (_fNB) {
      return function (t) {
        return _kellyPassesFadeFilters(t, _fIdx, _fNB, _kellyTradeFeatureCache, _tradeDims2, _pcMonthMask);
      };
    })(_fNB2);
  } else {
    _pcFadeFn = function (t) {
      return _kellyPassesFadeFilters(t, _fIdx, _filters, _kellyTradeFeatureCache, _tradeDims2, _pcMonthMask);
    };
  }
  // positionCap: 跨全部卖出模式×rating三分区收集基笔池(去重, 10模式共享同一批基笔, 模式之前统一生效)
  var _posCapKept = null;
  var _posDayCounts = null; // 每日资金池等分(2026-08-13恢复): 当日保留基笔数, 与卡片/评级同口径(§22跨展示位一致)
  if (_filters.positionCap && _filters.positionCapK > 0) {
    // 2026-08-23 性能专项: _kellyCollectBasePool 改 async 分片, 本函数本就是 async, await 即可(语义零变化)
    var _basePool = await _kellyCollectBasePool(td.quadrants, cfg.sell_modes || {}, _fIdx, _pcFadeFn);
    _posCapKept = _kellyPositionCapKeptKeys(_basePool, _fIdx, _filters.positionCapK);
    _posDayCounts = _kellyKeptDayCounts(_posCapKept);
  }
  let trades = rawTrades.filter(function (t) {
    if (cutoff && cutoff !== "0" && (t[_fIdx.buy_date] || "") < cutoff) return false;
    if (!_pcFadeFn(t)) return false;
    if (_posCapKept && !_posCapKept[_kellyBaseKey(t, _fIdx)]) return false;
    return true;
  });

  // 2026-08-12 需求B: 被降亏过滤/仓位控制淘汰的交易(显示+删除线灰化, 让用户看到"被淘汰了"而非只消失)
  // 淘汰=未通过 _pcFadeFn(降亏toggle) 或 未被 positionCap 前K保留; 周期cutoff不算淘汰(原语义过滤)
  let eliminated = rawTrades.filter(function (t) {
    if (cutoff && cutoff !== "0" && (t[_fIdx.buy_date] || "") < cutoff) return false;
    return !_pcFadeFn(t) || (_posCapKept && !_posCapKept[_kellyBaseKey(t, _fIdx)]);
  });

  // 始终重算(含默认档)以获取费率消耗: 重算 profit/return_pct/fee_cost
  // 2026-08-12: 每笔金额=固定1万(与卡片统计口径一致 §22)
  var extFields;
  {
    const _buyAmount = td.buy_amount || (cfg.buy_amount) || 10000;
    const feeParams = state.labSigKellyFeeParams || { commission_rate: 0.0003, min_commission: 5, slippage: 0.001, transfer_fee_rate_sh: 0.00001, stamp_duty_rate: 0 };
    const _recompute = (t) => {
      const _amt = _kellyPerTradeAmount(t, _fIdx, _buyAmount, _posDayCounts ? _posDayCounts[t[_fIdx.signal_date]] : null);
      const r = _kellyRecomputeTrade(t, _fIdx, feeParams, _amt);
      const newT = t.slice();
      newT[_fIdx.profit] = r.profit;
      newT[_fIdx.return_pct] = r.return_pct;
      newT.push(r.fee_cost); // fee_cost 作为额外元素追加到数组末尾
      newT.push(_amt); // amount 作为额外元素追加(每笔固定1万)
      return newT;
    };
    trades = trades.map(_recompute);
    eliminated = eliminated.map(_recompute);
    extFields = fields.concat(["fee_cost", "amount"]);
  }

  // 渲染 modal(新开弹窗重置到第 1 页 + 重置筛选/排序状态, 防上个弹窗的 ETF 关键字/盈亏筛选残留到下一个弹窗)
  state._sigKellyTradePage = 1;
  state._sigKellyElimPage = 1;
  state._sigKellyTradeSort = { key: "buy_date", dir: -1 };
  state._sigKellyTradeFilter = { etf: "", profit: "all" };
  _renderSigKellyTradesModal(overlay, trades, extFields, quadLabel, modeLabel, period, quadKey, modeKey, eliminated);
}

function _renderSigKellyTradesModal(overlay, trades, fields, quadLabel, modeLabel, period, quadKey, modeKey, eliminated) {
  const fIdx = {};
  fields.forEach((f, i) => { fIdx[f] = i; });
  // 排序/筛选状态
  if (!state._sigKellyTradeSort) state._sigKellyTradeSort = { key: "buy_date", dir: -1 };
  if (!state._sigKellyTradeFilter) state._sigKellyTradeFilter = { etf: "", profit: "all" };
  if (!state._sigKellyTradePage) state._sigKellyTradePage = 1;
  if (!state._sigKellyElimPage) state._sigKellyElimPage = 1;
  const sort = state._sigKellyTradeSort;
  const filter = state._sigKellyTradeFilter;
  eliminated = eliminated || [];

  const colDefs = [
    { key: "index_id", label: "触发信号", sortable: true },
    { key: "buy_date", label: "买入日", sortable: true },
    { key: "sell_date", label: "卖出日", sortable: true },
    { key: "track_score", label: "ETF关系", sortable: true },
    { key: "etf_code", label: "代码", sortable: true },
    { key: "etf_name", label: "ETF名称", sortable: true },
    { key: "buy_price", label: "买价", sortable: true },
    { key: "sell_price", label: "卖价", sortable: true },
    { key: "shares", label: "份额", sortable: true },
    { key: "amount", label: "每笔金额", sortable: true },
    { key: "profit", label: "盈亏(元)", sortable: true },
    { key: "return_pct", label: "收益率", sortable: true },
    { key: "fee_cost", label: "费率消耗", sortable: true },
    { key: "hold_days", label: "持有天", sortable: true },
    { key: "sell_reason", label: "卖出原因", sortable: true },
  ];

  // 筛选+排序泛化版(2026-08-24 bug修复): 主表/被淘汰区共用同一套 filter.etf/filter.profit 与排序状态,
  // 此前淘汰区渲染完全不经过筛选(筛选时主表变而删除线表一动不动=用户视角"筛选失效"), 且排序也不一致。
  // 纯展示层过滤, 不动任何统计口径/回测数字(顶部 stats 条仍显示全量口径)。
  function _applyFilterTo(list) {
    let result = list;
    if (filter.etf) {
      const kw = filter.etf.toLowerCase();
      result = result.filter((t) => {
        const name = (t[fIdx.etf_name] || "").toLowerCase();
        const code = (t[fIdx.etf_code] || "").toLowerCase();
        return name.includes(kw) || code.includes(kw);
      });
    }
    if (filter.profit === "pos") result = result.filter((t) => t[fIdx.profit] > 0);
    else if (filter.profit === "neg") result = result.filter((t) => t[fIdx.profit] <= 0);
    // 排序(两表共用同一排序状态, 保持一致)
    const sk = fIdx[sort.key];
    if (sk != null) {
      result = result.slice().sort((a, b) => {
        let va = a[sk], vb = b[sk];
        if (typeof va === "string") return sort.dir * va.localeCompare(vb);
        return sort.dir * ((va || 0) - (vb || 0));
      });
    }
    return result;
  }
  function _applyFilter() { return _applyFilterTo(trades); }

  function _render() {
    const filtered = _applyFilter();
    const winCount = trades.filter((t) => t[fIdx.profit] > 0).length;
    const totalProfit = trades.reduce((s, t) => s + (t[fIdx.profit] || 0), 0);
    const totalFeeCost = trades.reduce((s, t) => s + (t[fIdx.fee_cost] || 0), 0);
    const holdingCount = trades.filter((t) => !t[fIdx.sell_date]).length;

    let thHTML = colDefs.map((c) => {
      const isSorted = sort.key === c.key;
      const arrow = isSorted ? (sort.dir > 0 ? " ▲" : " ▼") : "";
      return `<th class="lab-sigkelly-trades-th" data-key="${c.key}">${c.label}${arrow}</th>`;
    }).join("");

    // 分页: 每页 50 行
    const perPage = 50;
    const totalPages = Math.max(1, Math.ceil(filtered.length / perPage));
    if (state._sigKellyTradePage > totalPages) state._sigKellyTradePage = totalPages;
    if (state._sigKellyTradePage < 1) state._sigKellyTradePage = 1;
    const page = state._sigKellyTradePage;
    const pageRows = filtered.slice((page - 1) * perPage, page * perPage);

    // 行渲染(正常/被淘汰共用, 2026-08-12 需求B): 返回 td 拼接, 外层 tr class 由调用方决定
    const _rowHtml = (t) => {
      const pf = t[fIdx.profit] || 0;
      const rp = t[fIdx.return_pct] || 0;
      const pfCls = pf >= 0 ? "lab-sigkelly-pos" : "lab-sigkelly-neg";
      const isHolding = !t[fIdx.sell_date]; // 持仓中trade(sell_date 空, 预估盈亏)
      // 触发信号列: 指数名 + 信号标签
      const iid = t[fIdx.index_id] || "";
      const sig = t[fIdx.signal] || "";
      const sigCell = indexIdToName(iid) + '<br><span class="lab-sigkelly-siglabel">' + signalLabel({ signal: sig }) + '</span>';
      // ETF关系列: 信号灯圆点 + 档位标签 + 跟踪分
      const etfRel = (function () {
        const etf = {
          match_method: t[fIdx.match_method],
          track_tier: t[fIdx.track_tier],
          track_score: t[fIdx.track_score],
          track_low_confidence: t[fIdx.track_low_confidence],
        };
        const light = _etfLightInfo(etf);
        const scoreStr = (typeof etf.track_score === "number") ? Math.round(etf.track_score) : "-";
        return '<span class="etf-light ' + light.cls + '"></span> ' + light.label + ' ' + scoreStr;
      })();
      // 持仓中trade 特殊渲染: 卖出日=持仓中标签 / 卖价=当前价+预估 / 收益率=预估前缀+虚线斜体 / 原因=持有中X天
      const sellDateCell = isHolding
        ? `<td><span class="lab-sigkelly-holding-tag">持仓中</span></td>`
        : `<td>${t[fIdx.sell_date]}</td>`;
      const _cpIdx = fIdx.current_price;
      const sellPriceCell = isHolding
        ? `<td class="lab-sigkelly-est">${(+(_cpIdx != null ? t[_cpIdx] : 0)).toFixed(4)}<span class="lab-sigkelly-est-tag">预估</span></td>`
        : `<td>${(+t[fIdx.sell_price]).toFixed(4)}</td>`;
      const profitCell = isHolding
        ? `<td class="${pfCls} lab-sigkelly-est">${(pf >= 0 ? "+" : "") + pf.toFixed(2)}</td>`
        : `<td class="${pfCls}">${(pf >= 0 ? "+" : "") + pf.toFixed(2)}</td>`;
      const returnCell = isHolding
        ? `<td class="${pfCls} lab-sigkelly-est">预估${(rp >= 0 ? "+" : "") + rp.toFixed(2)}%</td>`
        : `<td class="${pfCls}">${(rp >= 0 ? "+" : "") + rp.toFixed(2)}%</td>`;
      const reasonCell = isHolding
        ? `<td>${t[fIdx.sell_reason] || "持有中"} ${t[fIdx.hold_days]}天</td>`
        : `<td>${t[fIdx.sell_reason]}</td>`;
      return `<td class="lab-sigkelly-trades-sigcell">${sigCell}</td>` +
        `<td>${t[fIdx.buy_date]}</td>${sellDateCell}` +
        `<td class="lab-sigkelly-trades-etfrel">${etfRel}</td>` +
        `<td>${t[fIdx.etf_code]}</td><td class="lab-sigkelly-trades-etfname">${t[fIdx.etf_name]}</td>` +
        `<td>${(+t[fIdx.buy_price]).toFixed(4)}</td>${sellPriceCell}` +
        `<td>${(+t[fIdx.shares]).toFixed(2)}</td>` +
        `<td class="lab-sigkelly-amt">${(t[fIdx.amount] != null ? Math.round(+t[fIdx.amount]).toLocaleString() : "-")}</td>` +
        profitCell + returnCell +
        `<td class="lab-sigkelly-neg lab-sigkelly-fee">${(t[fIdx.fee_cost] != null ? "-" + (+t[fIdx.fee_cost]).toFixed(2) : "-")}</td>` +
        `<td>${t[fIdx.hold_days]}</td>${reasonCell}`;
    };
    let tbodyHTML = "";
    if (pageRows.length === 0) {
      tbodyHTML = `<tr><td colspan="15" class="lab-sigkelly-trades-more">无符合条件的交易记录</td></tr>`;
    } else {
      for (const t of pageRows) {
        const rowCls = (!t[fIdx.sell_date]) ? "lab-sigkelly-holding-row" : "";
        tbodyHTML += `<tr class="${rowCls}">${_rowHtml(t)}</tr>`;
      }
    }
    // 被淘汰交易区块(2026-08-12 需求B): 被降亏过滤/仓位控制淘汰的交易显示+删除线灰化, 独立分页(不计入统计口径)
    // 2026-08-24 bug修复: 同样应用 filter.etf/filter.profit+排序(_applyFilterTo), 分页/计数按筛选后口径
    let elimTbody = "";
    let elimTotalPages = 1;
    let elimFilteredCount = 0;
    if (eliminated.length > 0) {
      const elimFiltered = _applyFilterTo(eliminated);
      elimFilteredCount = elimFiltered.length;
      const elimPerPage = 50;
      elimTotalPages = Math.max(1, Math.ceil(elimFilteredCount / elimPerPage));
      if (state._sigKellyElimPage > elimTotalPages) state._sigKellyElimPage = elimTotalPages;
      if (state._sigKellyElimPage < 1) state._sigKellyElimPage = 1;
      const elimPageRows = elimFiltered.slice((state._sigKellyElimPage - 1) * elimPerPage, state._sigKellyElimPage * elimPerPage);
      if (elimPageRows.length === 0) {
        elimTbody = `<tr><td colspan="15" class="lab-sigkelly-trades-more">无符合条件的被淘汰交易</td></tr>`;
      } else {
        for (const t of elimPageRows) {
          const elimRowCls = ((!t[fIdx.sell_date]) ? "lab-sigkelly-holding-row" : "") + " lab-sigkelly-eliminated-row";
          elimTbody += `<tr class="${elimRowCls}">${_rowHtml(t)}</tr>`;
        }
      }
    }

    const feeLabel = (state.labSigKellyFeePreset && state.labSigKellyFeePreset !== "etf_main") ? ` · 费率:${_kellyFeeLabel()}` : "";
    overlay.innerHTML =
      `<div class="lab-sigkelly-modal">` +
        `<div class="lab-sigkelly-modal-head">` +
          `<div class="lab-sigkelly-modal-title">📋 交易记录 · ${quadLabel} · ${modeLabel} · ${period}${feeLabel}</div>` +
          (state.labSigKellyGihOn && _kellyIsGih(modeKey) ? `<div class="lab-sigkelly-gih-modal-note" title="#49+#xx ai长线仓位管理口径说明">⚠️ 本弹窗为<u>未套 ai长线仓位管理</u>的原始交易；当前卡片 G/H/I 行已套各模式最优仓位法(G=P≤3d@13万/H=满仓不买@7万/I=满仓不买@16万)后的口径(峰持仓≤20倍可操作)，此处净盈亏/峰值与卡片可能不一致。</div>`
           : _kellyOpModalNote(quadKey, modeKey, period)) +
          `<button type="button" class="lab-sigkelly-modal-close" title="关闭">✕</button>` +
        `</div>` +
        `<div class="lab-sigkelly-modal-stats">` +
          `<span>共 ${trades.length} 笔</span>` +
          `<span>盈利 ${winCount} / 亏损 ${trades.length - winCount}</span>` +
          `<span>胜率 ${trades.length ? (winCount / trades.length * 100).toFixed(1) : 0}%</span>` +
          `<span>总盈亏 ${(totalProfit >= 0 ? "+" : "") + totalProfit.toFixed(0)} 元</span>` +
          `<span class="lab-sigkelly-neg">费率消耗 -${totalFeeCost.toFixed(0)} 元</span>` +
          (holdingCount > 0 ? `<span class="lab-sigkelly-holding-stat">含 ${holdingCount} 笔预估</span>` : "") +
          (eliminated.length > 0 ? `<span class="lab-sigkelly-elim-stat">⚠ 被降亏/AI仓位建议淘汰 ${eliminated.length} 笔(删除线,不计入统计)</span>` : "") +
        `</div>` +
        `<div class="lab-sigkelly-modal-filters">` +
          `<input type="text" class="lab-input lab-sigkelly-filter-etf" placeholder="筛选ETF名称/代码…" value="${filter.etf}">` +
          `<select class="lab-input lab-sigkelly-filter-profit">` +
            `<option value="all"${filter.profit === "all" ? " selected" : ""}>全部</option>` +
            `<option value="pos"${filter.profit === "pos" ? " selected" : ""}>仅盈利</option>` +
            `<option value="neg"${filter.profit === "neg" ? " selected" : ""}>仅亏损</option>` +
          `</select>` +
        `</div>` +
        `<div class="lab-sigkelly-modal-tablewrap">` +
          `<table class="lab-sigkelly-trades-table">` +
            `<thead><tr>${thHTML}</tr></thead>` +
            `<tbody>${tbodyHTML}</tbody>` +
          `</table>` +
        `</div>` +
        `<div class="lab-sigkelly-modal-pagination">` +
          `<button type="button" class="lab-sigkelly-page-prev" ${page <= 1 ? "disabled" : ""}>‹ 上一页</button>` +
          `<span class="lab-sigkelly-page-info">第 ${page} / ${totalPages} 页(共 ${filtered.length} 笔)</span>` +
          `<button type="button" class="lab-sigkelly-page-next" ${page >= totalPages ? "disabled" : ""}>下一页 ›</button>` +
        `</div>` +
        (eliminated.length > 0 ? (
          `<div class="lab-sigkelly-modal-elimwrap">` +
            `<div class="lab-sigkelly-modal-elimtitle">⚠ 被降亏/AI仓位建议淘汰的交易 ${eliminated.length} 笔（删除线=不参与统计,已从卡片/按年表剔除;仅在此展示对照哪些被淘汰）· 已筛 ${elimFilteredCount}/${eliminated.length} 笔</div>` +
            `<div class="lab-sigkelly-modal-elimtablewrap">` +
              `<table class="lab-sigkelly-trades-table">` +
                `<thead><tr>${thHTML}</tr></thead>` +
                `<tbody>${elimTbody}</tbody>` +
              `</table>` +
            `</div>` +
            `<div class="lab-sigkelly-modal-pagination">` +
              `<button type="button" class="lab-sigkelly-page-prev-elim" ${state._sigKellyElimPage <= 1 ? "disabled" : ""}>‹ 上一页</button>` +
              `<span class="lab-sigkelly-page-info">第 ${state._sigKellyElimPage} / ${elimTotalPages} 页(共 ${elimFilteredCount} 笔)</span>` +
              `<button type="button" class="lab-sigkelly-page-next-elim" ${state._sigKellyElimPage >= elimTotalPages ? "disabled" : ""}>下一页 ›</button>` +
            `</div>` +
          `</div>`
        ) : "") +
      `</div>`;

    // 关闭
    overlay.querySelector(".lab-sigkelly-modal-close").onclick = () => { overlay.style.display = "none"; };
    overlay.onclick = (e) => { if (e.target === overlay) overlay.style.display = "none"; };
    // 排序
    overlay.querySelectorAll(".lab-sigkelly-trades-th").forEach((th) => {
      th.onclick = () => {
        const key = th.dataset.key;
        if (sort.key === key) sort.dir = -sort.dir;
        else { sort.key = key; sort.dir = -1; }
        state._sigKellyTradePage = 1;
        state._sigKellyElimPage = 1;
        _render();
      };
    });
    // 筛选
    const etfInput = overlay.querySelector(".lab-sigkelly-filter-etf");
    if (etfInput) {
      // 注意:_render() 会重建 overlay.innerHTML,销毁旧 etfInput 节点(分离节点 focus 无效)。
      // 故 _render() 后需重新 querySelector 拿新节点 focus,并尽量保留光标位置(selectionStart)。
      etfInput.oninput = () => {
        filter.etf = etfInput.value;
        const selStart = etfInput.selectionStart;
        state._sigKellyTradePage = 1;
        state._sigKellyElimPage = 1;
        _render();
        const newInput = overlay.querySelector(".lab-sigkelly-filter-etf");
        if (newInput) {
          newInput.focus();
          try { newInput.setSelectionRange(selStart, selStart); } catch (e) { /* ignore */ }
        }
      };
    }
    const profitSel = overlay.querySelector(".lab-sigkelly-filter-profit");
    if (profitSel) {
      profitSel.onchange = () => { filter.profit = profitSel.value; state._sigKellyTradePage = 1; state._sigKellyElimPage = 1; _render(); };
    }
    // 分页
    const prevBtn = overlay.querySelector(".lab-sigkelly-page-prev");
    if (prevBtn) {
      prevBtn.onclick = () => { if (state._sigKellyTradePage > 1) { state._sigKellyTradePage--; _render(); } };
    }
    const nextBtn = overlay.querySelector(".lab-sigkelly-page-next");
    if (nextBtn) {
      nextBtn.onclick = () => { state._sigKellyTradePage++; _render(); };
    }
    // 被淘汰交易分页(2026-08-12 需求B)
    const elimPrevBtn = overlay.querySelector(".lab-sigkelly-page-prev-elim");
    if (elimPrevBtn) {
      elimPrevBtn.onclick = () => { if (state._sigKellyElimPage > 1) { state._sigKellyElimPage--; _render(); } };
    }
    const elimNextBtn = overlay.querySelector(".lab-sigkelly-page-next-elim");
    if (elimNextBtn) {
      elimNextBtn.onclick = () => { state._sigKellyElimPage++; _render(); };
    }
  }

  _render();
}

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
    if (sub && ["single", "fusion", "retest", "ablation", "symmetry", "paramscan", "custom", "aiwarn", "aiscore", "sigkelly"].includes(sub)) {
      // 兼容旧 hash #lab?sub=custom -> 跳转到新 aiwarn 子tab(custom 已拆为父tab)
      state.labSubMode = sub === "custom" ? "aiwarn" : sub;
    }
  }
  // 激活 lab tab 按钮 -> 触发 renderTab -> renderSignalLab/renderLabDetail
  setTimeout(() => {
    const labBtn = document.querySelector('button[data-tab="lab"]');
    if (labBtn) labBtn.click();
  }, 0);
})();
