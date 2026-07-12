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
  const indSeries = indicators.map((it) => ({
    name: it.name, type: "line", symbol: "none", data: it.data, smooth: true,
    lineStyle: { width: 1, type: it.dash ? "dashed" : "solid", color: it.color || "#c9cdd4" },
    connectNulls: false,
  }));
  c.setOption({
    tooltip: { trigger: "axis" },
    legend: { top: 0, data: legendData },
    grid: { left: 55, right: 20, top: 35, bottom: 50 },
    xAxis: { type: "category", data: dates },
    yAxis: { type: "value", scale: true },
    dataZoom: [{ type: "inside" }, { type: "slider", height: 18, bottom: 8 }],
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
    { name: "布林上轨", data: bb.bu, color: "#c9cdd4", dash: true },
    { name: "布林下轨", data: bb.bl, color: "#c9cdd4", dash: true },
  ], signals, container, chartArr, "布林上轨回落卖", "#9c27b0");
}

// === 22策略元数据注册表（分区/状态/触发/结论/理论/场景/注意/08报告结论）===
// 文案来源：买卖点策略深度回测.md（重跑于 2026-07-11，244资产全史/近10年/近5年/近3年/近1年 × 5d/10d/20d/60d）
// zone: buy=候选买点 / sell=候选卖点 / excluded=已排除 / prod=生产参考
// status: live=已上线生产 / experimental=实验中 / dev=开发中 / excluded=已排除
const LAB_STRATEGIES = {
  // --- 候选买点区（7个） ---
  BB_lower_revert: {
    name: "布林下轨回归买", side: "buy", zone: "buy", status: "experimental",
    trigger: "前一日 close 跌破 BB 下轨，当日 close 收回下轨之上（超卖反弹）",
    conclusion: "3/4窗口达标并列第1，近3年60d盈亏比1.84最高，与C1语义互补",
    theory: "布林带下轨回归。价格跌破下轨后收回，意味超卖极端已过、反弹拐点出现。与C1同为「超卖反弹」语义，但用价格穿越BB下轨而非RSI阈值，强势市更敏感。",
    scenario: "震荡市/下跌市超卖反弹；强势市中RSI未到30但价格已破下轨时补C1盲区。",
    note: "近1年是唯一达标买点（52.1%/1.23），与C1互补性最强。实验中：已实现图表（收盘价+BB轨+绿色实验买markPoint），未写入signal_daily。",
    report: "08报告：BB_lower_revert 达标数3/4（近10年/近3年/近1年），与C1并列第1。近3年60d盈亏比1.79、均值+4.7%为买点最高。近1年（强势单边市）是唯一达标买点，补强C1在强势市的盲区。语义与C1正交（价格穿越 vs RSI阈值），适合做互补买点。",
  },
  Supertrend_buy: {
    name: "Supertrend翻多买", side: "buy", zone: "buy", status: "experimental",
    trigger: "ATR(10)×3 趋势线从翻空转为翻多（趋势跟踪买点）",
    conclusion: "2/4达标，语义与C1正交（趋势启动 vs 超卖反弹），最佳互补候选",
    theory: "Supertrend 指标基于 ATR 的动态趋势线。翻多意味趋势已确认启动，与C1的「超卖反弹」正交，捕捉的是趋势延续而非拐点。",
    scenario: "趋势启动确认；与C1互补覆盖不同市场状态。",
    note: "近3年全horizon胜率≥48.8%，盈亏比1.40-1.61。信号较C1稀疏。实验中：已实现图表（收盘价+Supertrend趋势线+绿色实验买markPoint），未写入signal_daily。",
    report: "08报告：Supertrend_buy 全史达标（51.4%/1.21），近3年20d/60d胜率≥49.7%盈亏比≥1.45。语义与C1正交（趋势启动 vs 超卖反弹），是最佳互补候选。近3年10d均值+1.0%，60d均值+3.8%。",
  },
  Donchian20_up: {
    name: "唐奇安20日突破买", side: "buy", zone: "buy", status: "dev",
    trigger: "close 突破近20日最高价（通道突破买）",
    conclusion: "2/4达标，近3年胜率<50%，趋势跟踪型信号",
    theory: "唐奇安通道突破。价格创新高意味多头力量突破，经典趋势跟踪系统。",
    scenario: "强趋势市突破入场；震荡市假信号多。",
    note: "近3年10d胜率47.7%低于50%，但近1年51.0%转正。60d盈亏比1.56较高。",
    report: "08报告：Donchian20_up 全史+近1年达标（2/4），近3年胜率47.7%低于50%。全史样本38731最大之一，但胜率平庸。近3年60d盈亏比1.56、均值+2.3%。",
  },
  Donchian55_up: {
    name: "海龟55日突破买", side: "buy", zone: "buy", status: "dev",
    trigger: "close 突破近55日最高价（海龟交易法System 2）",
    conclusion: "2/4达标，胜率<50%，长周期突破信号滞后",
    theory: "海龟交易法 System 2 入场。55日突破捕捉中长期趋势启动，经典趋势跟踪。",
    scenario: "中长期趋势确认入场；短周期信号滞后。",
    note: "近3年胜率47.1%，但近1年51.0%。60d盈亏比1.45。",
    report: "08报告：Donchian55_up 全史+近1年达标（2/4），近3年胜率47.1%低于50%。全史样本20895，60d均值+3.4%。海龟系统长周期突破信号滞后但盈亏比尚可。",
  },
  MA_golden_5_20: {
    name: "MA5/MA20金叉买", side: "buy", zone: "buy", status: "dev",
    trigger: "MA5 上穿 MA20（短期金叉买点）",
    conclusion: "1/4达标，信号密集胜率平庸",
    theory: "双均线金叉。短期均线上穿长期均线意味短期动量转强，经典趋势确认信号。",
    scenario: "趋势确认入场；震荡市频繁假金叉。",
    note: "信号最多（全史30754），但近3年胜率49.8%接近随机。60d盈亏比1.75较高。",
    report: "08报告：MA_golden_5_20 仅全史达标（1/4），近3年10d胜率49.8%接近随机。信号密集（全史30754个），胜率平庸。近3年60d盈亏比1.75、均值+4.9%是唯一亮点。",
  },
  MA_golden_10_60: {
    name: "MA10/MA60金叉买", side: "buy", zone: "buy", status: "dev",
    trigger: "MA10 上穿 MA60（中长期金叉买点）",
    conclusion: "2/4达标，滞后严重",
    theory: "中长期双均线金叉。MA10上穿MA60确认中长期趋势转多，但MA60滞后严重。",
    scenario: "中长期趋势确认；信号滞后，入场点偏晚。",
    note: "近3年胜率47.1%低于50%。全史样本11809较少。",
    report: "08报告：MA_golden_10_60 全史+近1年达标（2/4），近3年胜率47.1%低于50%。MA60滞后严重，信号少且入场偏晚。全史60d均值+2.1%。",
  },
  MACD_golden: {
    name: "MACD金叉买", side: "buy", zone: "buy", status: "dev",
    trigger: "DIF 上穿 DEA（MACD金叉买点）",
    conclusion: "1/4达标，信号最多但平庸",
    theory: "MACD金叉。DIF上穿DEA意味短期动量强于长期，经典趋势确认。MACD(12,26,9)业界标准参数。",
    scenario: "趋势确认入场；震荡市假金叉多。",
    note: "信号全史最多（38930），但近3年胜率49.1%接近随机。",
    report: "08报告：MACD_golden 仅全史达标（1/4），近3年10d胜率49.1%接近随机。信号全史最多（38930个），但胜率平庸。近3年60d盈亏比1.76、均值+4.6%。",
  },
  // --- 候选卖点区（7个） ---
  BB_upper_revert: {
    name: "布林上轨回落卖", side: "sell", zone: "sell", status: "experimental",
    trigger: "前一日 close 突破 BB 上轨，当日 close 回落至上轨下方（短周期止盈）",
    conclusion: "近3年5d/10d胜率第1(57%/54%)，与D1(20d最强)时间维度互补",
    theory: "布林带上轨回归。价格从上轨上方回落至下方，意味超买极端已过、短周期止盈拐点。与D1的「20日高回落5%」时间维度互补。",
    scenario: "短周期止盈/减仓提示；与D1（20d最强）双重确认。",
    note: "实验中，已实现图表（close折线+BB轨+紫色实验卖markPoint）。未写入signal_daily。",
    report: "08报告：BB_upper_revert 近3年5d胜率56.8%/10d胜率54.1%为卖点最高，短周期止盈最强。但样本仅5549（D1一半），20d后衰减。适合做D1的短周期互补（候选C）。全史PL0.87<1（卖点结构性问题），但方向胜率top1。",
  },
  MA_death_5_20: {
    name: "MA5/MA20死叉卖", side: "sell", zone: "sell", status: "experimental",
    trigger: "MA5 下穿 MA20（短期死叉卖点）",
    conclusion: "近3年20d胜率56.3%最高，短周期偏弱但中周期强",
    theory: "双均线死叉。短期均线下穿长期均线意味短期动量转弱，经典趋势转弱确认。",
    scenario: "趋势转弱减仓；震荡市频繁假死叉。",
    note: "近3年20d胜率54.8%较高，但5d/10d偏弱。PL0.90<1。实验中：已实现图表（收盘价+MA5/MA20+紫色实验卖markPoint），未写入signal_daily。",
    report: "08报告：MA_death_5_20 近3年20d胜率54.8%为卖点较高，10d胜率53.2%。均值-0.1%（方向正确）。但5d/10d偏弱，PL0.90<1（卖点结构性问题）。",
  },
  BB_middle_break: {
    name: "跌破布林中轨卖", side: "sell", zone: "sell", status: "dev",
    trigger: "close 跌破布林中轨（MA20），中轨破位卖",
    conclusion: "中规中矩，PL偏低",
    theory: "布林中轨破位。中轨=MA20，跌破意味价格回到均线下方，趋势转弱确认。",
    scenario: "趋势转弱确认减仓；信号密集。",
    note: "近3年10d胜率52.6%，PL0.82偏低。样本最大（10177）。",
    report: "08报告：BB_middle_break 近3年10d胜率52.6%、PL0.82。样本10177最大。中规中矩，无突出优势。",
  },
  Donchian10_down: {
    name: "跌破10日最低卖", side: "sell", zone: "sell", status: "dev",
    trigger: "close 跌破近10日最低价（海龟退出信号）",
    conclusion: "胜率刚过50%",
    theory: "唐奇安通道下破/海龟退出。跌破短期低点意味短期趋势已破，海龟System 2退出信号。",
    scenario: "短期趋势破位退出；信号密集。",
    note: "近3年10d胜率52.4%，PL0.89。样本10731较大。",
    report: "08报告：Donchian10_down 近3年10d胜率52.4%、PL0.89。胜率刚过50%，无突出优势。样本10731较大。",
  },
  Donchian20_down: {
    name: "跌破20日最低卖", side: "sell", zone: "sell", status: "dev",
    trigger: "close 跌破近20日最低价（通道下破卖）",
    conclusion: "PL相对高但平庸",
    theory: "唐奇安通道下破。跌破20日低点意味中期趋势已破，比10日更滞后但更可靠。",
    scenario: "中期趋势破位减仓；信号较稀疏。",
    note: "近3年10d胜率51.8%、PL0.88。全史PL0.94相对高。",
    report: "08报告：Donchian20_down 近3年10d胜率51.8%、PL0.88。全史PL0.94为卖点相对高，但整体平庸。样本7533。",
  },
  MACD_death: {
    name: "MACD死叉卖", side: "sell", zone: "sell", status: "dev",
    trigger: "DIF 下穿 DEA（MACD死叉卖点）",
    conclusion: "PL0.79偏低",
    theory: "MACD死叉。DIF下穿DEA意味短期动量弱于长期，经典趋势转弱确认。MACD(12,26,9)业界标准。",
    scenario: "趋势转弱减仓；震荡市假死叉多。",
    note: "近3年10d胜率51.8%，PL0.83偏低。样本6844较大。",
    report: "08报告：MACD_death 近3年10d胜率51.8%、PL0.83偏低。样本6844。信号密集但PL偏低，卖点结构性问题突出。",
  },
  ATR_trail_stop: {
    name: "ATR追踪止损卖", side: "sell", zone: "sell", status: "dev",
    trigger: "close < 近20日最高close − 3×ATR(14)（追踪止损）",
    conclusion: "胜率刚过50%",
    theory: "ATR追踪止损。基于波动率的动态止损线，价格跌破意味趋势已反转。ATR自适应波动率。",
    scenario: "趋势跟踪止损；波动率大时止损线更宽。",
    note: "近3年10d胜率51.1%，PL0.86。全史PL0.96相对高。",
    report: "08报告：ATR_trail_stop 近3年10d胜率51.1%、PL0.86。全史PL0.96为卖点最高之一。追踪止损型信号，胜率刚过50%。",
  },
  // --- 已排除反面教材区（6个） ---
  BB_upper_break: {
    name: "突破布林上轨买", side: "buy", zone: "excluded", status: "excluded",
    trigger: "close 突破布林上轨（追高买）",
    conclusion: "0/4达标，追高被套，胜率长期<50%",
    theory: "布林上轨突破。价格突破上轨意味强势，但A股追高易被套。",
    scenario: "不推荐使用。",
    note: "已排除。近3年10d胜率45.5%，全史48.8%均<50%。",
    report: "08报告：BB_upper_break 0/4达标，全史+近3年+近1年胜率均<50%（48.8%/45.5%/48.4%）。追高被套，明确排除。",
  },
  KDJ_golden_oversold: {
    name: "KDJ超卖金叉买", side: "buy", zone: "excluded", status: "excluded",
    trigger: "KDJ 金叉且 K<35（超卖金叉买）",
    conclusion: "0/4达标，近3年10d胜率46.1%",
    theory: "KDJ超卖金叉。KDJ在超卖区金叉意味短期反弹，但A股KDJ信号噪声大。",
    scenario: "不推荐使用。",
    note: "已排除。近3年10d胜率45.5%<50%。",
    report: "08报告：KDJ_golden_oversold 0/4达标，近3年10d胜率45.5%<50%。信号密集（6839）但胜率低，明确排除。",
  },
  Vol_breakout: {
    name: "放量突破买", side: "buy", zone: "excluded", status: "excluded",
    trigger: "volume > 2×20日均量 且 当日close涨幅>2%（放量突破）",
    conclusion: "0/4达标，近3年胜率42.6%反向指标",
    theory: "放量突破。量价齐升意味资金入场，但A股个股放量突破后常回调。",
    scenario: "不推荐使用。在A股个股上反而是反向指标。",
    note: "已排除。近3年10d胜率43.0%，全史44.8%均<50%。",
    report: "08报告：Vol_breakout 0/4达标，近3年10d胜率43.0%为所有策略最低。放量突破在A股个股上反而是反向指标（追高被套），明确排除。",
  },
  B0_RSI70: {
    name: "RSI下穿70卖", side: "sell", zone: "excluded", status: "excluded",
    trigger: "RSI(14) 前日≥70 且 当日<70（超买结束卖）",
    conclusion: "PL0.81最差，旧基线已弃",
    theory: "RSI超买结束。RSI从≥70回落意味超买结束，但回测显示方向相反（信号后价格仍涨）。",
    scenario: "不推荐使用。已弃用，改用D1。",
    note: "已排除。全史PL0.84最差，旧基线。已被D1_high20_drop5替代。",
    report: "08报告：B0_RSI70 0/4达标，全史10d胜率48.7%/PL0.84/均值+0.9%（方向相反，信号后价格仍涨）。是所有卖点中最差的，旧基线已弃，改用D1。",
  },
  KDJ_death_overbought: {
    name: "KDJ超买死叉卖", side: "sell", zone: "excluded", status: "excluded",
    trigger: "KDJ 死叉且 K>70（超买死叉卖）",
    conclusion: "近3年10d胜率46.3%失效",
    theory: "KDJ超买死叉。KDJ在超买区死叉意味短期转弱，但近年失效。",
    scenario: "不推荐使用。近年失效。",
    note: "已排除。近3年10d胜率47.8%<50%。",
    report: "08报告：KDJ_death_overbought 0/4达标，近3年10d胜率47.8%<50%。近年失效，明确排除。全史10d胜率45.4%也低。",
  },
  Supertrend_sell: {
    name: "Supertrend翻空卖", side: "sell", zone: "excluded", status: "excluded",
    trigger: "ATR(10)×3 趋势线从翻多转为翻空（趋势跟踪卖）",
    conclusion: "全史唯一PL≥1但近3年48.9%失效",
    theory: "Supertrend翻空。趋势线翻空意味趋势已反转，但近年A股向上漂移致失效。",
    scenario: "不推荐使用。近年失效。",
    note: "已排除。全史PL0.95（接近1），但近3年胜率48.9%<50%失效。",
    report: "08报告：Supertrend_sell 全史唯一PL≥1（0.95接近1，胜率51.9%），但近3年10d胜率48.9%/PL0.85失效。近年A股向上漂移致趋势跟踪卖点失效，明确排除。",
  },
  // --- 生产参考区（2个） ---
  C1_RSI30: {
    name: "RSI上穿30买", side: "buy", zone: "prod", status: "live",
    trigger: "RSI(14) 从 ≤30 升回 >30 那天（超卖结束、价格有望反弹）",
    conclusion: "3/4达标，结构最稳健，当前主买点",
    theory: "RSI经典超卖回归。RSI≤30表示超卖，升回30之上意味空头力量衰竭、反弹拐点出现。事件化（仅穿越当日标）。",
    scenario: "震荡市/下跌市超卖反弹；通用主买点。per-index可收紧阈值至RSI上穿25（kc50/电力设备/传媒已配）。",
    note: "已上线生产。signal='buy'。近3年全horizon胜率>50%，盈亏比随horizon单调上升。",
    report: "08报告：C1_RSI30 达标数3/4（全史/近10年/近3年）并列第1。近3年全horizon胜率>50%（5d54.2%/10d52.6%/20d56.5%/60d55.0%），盈亏比随horizon单调上升（1.38->1.17->1.52->1.68），60d均值+5.3%。结构最稳健，当前主买点，无需改买点。",
  },
  D1_high20_drop5: {
    name: "20日高回落5%卖", side: "sell", zone: "prod", status: "live",
    trigger: "close 从近20日最高 high 回落 5%（前日≥阈 且 当日<阈），且 close>MA60，且 DIF<DEA",
    conclusion: "20d胜率55.7%样本最大，当前主卖点",
    theory: "high-based 回落止盈。从20日最高价回落5%意味趋势转弱，叠加MA60多头过滤+MACD死叉确认。反应型信号（不预测顶部，反应已发生的弱势）。",
    scenario: "趋势转弱/止盈减仓提示；非做空/反向交易指令。胜率≈50%接近随机，不可作独立卖出指令。",
    note: "已上线生产。signal='sell'。卖点本质难预测（PL<1），D1是「最不坏」方案非「好」方案。",
    report: "08报告：D1_high20_drop5 近3年20d胜率55.9%为卖点最高，样本9873最大（统计最稳）。10d均值-0.1%（方向正确）。盈亏比0.86<1（卖点结构性问题：A股向上漂移），但在所有卖点中PL仍属前列。维持现状合理，是「最不坏」方案。",
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
  experimental: { label: "实验中", cls: "lab-tag-exp" },
  dev: { label: "开发中", cls: "lab-tag-dev" },
  excluded: { label: "已排除", cls: "lab-tag-excluded" },
};

// 矩阵窗口/horizon 定义
const LAB_WINDOWS = ["全史", "近10年", "近5年", "近3年", "近1年"];
const LAB_HORIZONS = ["5d", "10d", "20d", "60d"];

// === 5窗口切换（lab_simulate.json 新结构：stats/trades切片/equity切片 均按窗口独立）===
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

// 取某窗口的切片数据：stats(单窗口) + trades(按 tw 切片) + equity_curve(按 ew 切片)
// 新结构 trades/equity_curve 全史共享一份，tw/ew 存各窗口 [start,end] 切片索引
function _labPairWinData(pairData, mode, win) {
  const md = pairData && pairData[mode];
  if (!md) return null;
  const stats = (md.stats && md.stats[win]) || null;
  const tw = md.tw && md.tw[win];
  const ew = md.ew && md.ew[win];
  const trades = (tw && md.trades) ? md.trades.slice(tw[0], tw[1]) : (md.trades || []);
  const equity_curve = (ew && md.equity_curve) ? md.equity_curve.slice(ew[0], ew[1]) : (md.equity_curve || []);
  return { stats, trades, equity_curve };
}

// 窗口切换 tabs HTML（默认近1年：全史太密）
function _labWinTabsHTML() {
  const cur = state.labSimWindow || "y1";
  return '<div class="lab-win-tabs">' + LAB_WIN_DEFS.map((w) =>
    `<button type="button" class="lab-win-tab${w.k === cur ? " active" : ""}" data-win="${w.k}">${w.l}</button>`
  ).join("") + "</div>";
}

// 有图表实现的策略 key（仅这4个有指标+信号图表）
const LAB_CHART_KEYS = { BB_upper_revert: 1, BB_lower_revert: 1, Supertrend_buy: 1, MA_death_5_20: 1 };

// 构建策略图表配置（指标线+信号+标注文案），供 renderLabDetail 和买卖信号弹窗复用
// 返回 { indicators, signals, signalLabel, signalColor, chartTitle, statLabel } 或 null（无图表实现）
function _labBuildChartConfig(key, ohlc, indexName) {
  if (!LAB_CHART_KEYS[key]) return null;
  const meta = LAB_STRATEGIES[key];
  const signalLabel = meta.name; // 信号标注用策略中文名
  const name = indexName || "";
  if (key === "BB_upper_revert") {
    const bb = computeBBLab(ohlc);
    return {
      indicators: [
        { name: "布林上轨", data: bb.bu, color: "#c9cdd4", dash: true },
        { name: "布林下轨", data: bb.bl, color: "#c9cdd4", dash: true },
      ],
      signals: bb.signals, signalLabel, signalColor: "#9c27b0",
      chartTitle: `${name} · 布林上轨回落实验`, statLabel: "实验卖点",
    };
  } else if (key === "BB_lower_revert") {
    const r2 = computeBBLowerRevertLab(ohlc);
    return {
      indicators: [
        { name: "布林上轨", data: r2.bu, color: "#c9cdd4", dash: true },
        { name: "布林下轨", data: r2.bl, color: "#c9cdd4", dash: true },
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
  } else { // MA_death_5_20
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
}

// 获取 lab_backtest.json 数据（缓存到 state.labData）
// web 版走 /static/ 挂载点（main.py 的 StaticFiles(directory=web)），static 版走 ./data/
async function fetchLabData() {
  if (state.labData) return state.labData;
  try {
    state.labData = await fetchJSON("./data/lab/lab_backtest.json");
  } catch (e) {
    state.labData = null;
  }
  return state.labData;
}

// 模拟回测可选指数（每个指数一个 JSON 文件，前端按需加载）
const LAB_SIM_INDEXES = [
  { id: "sh", name: "上证指数" },
  { id: "sz", name: "深证成指" },
  { id: "cyb", name: "创业板指" },
  { id: "kc50", name: "科创50" },
];

// 获取 lab_simulate_{index}.json 数据（per-index 缓存到 state.labSimDataMap）
// web 版走 /static/ 挂载点（main.py 的 StaticFiles(directory=web)），static 版走 ./data/
async function fetchLabSimData(index) {
  index = index || "sh";
  if (!state.labSimDataMap) state.labSimDataMap = {};
  if (state.labSimDataMap[index]) return state.labSimDataMap[index];
  try {
    state.labSimDataMap[index] = await fetchJSON("./data/lab/lab_simulate_" + index + ".json");
  } catch (e) {
    state.labSimDataMap[index] = null;
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
    { l: "起始", v: initCapital, c: "#86909c" },
    { l: "最低", v: minVal, c: "#2e7d32" },
    { l: "峰值", v: peakVal, c: "#c92a2a" },
    { l: "期末", v: finalVal, c: "#3370ff" },
  ].map((it) => `<text x="${ml - 4}" y="${sy(it.v).toFixed(1)}" text-anchor="end" font-size="10" fill="${it.c}" dominant-baseline="middle">${it.l} ${fmtV(it.v)}</text>`).join("");
  const tickCount = Math.min(7, Math.max(3, Math.floor(n / 2)));
  const step = n > 1 ? (n - 1) / (tickCount - 1) : 1;
  const xLabels = [];
  for (let k = 0; k < tickCount; k++) {
    const i = Math.min(Math.round(k * step), n - 1);
    xLabels.push(`<text x="${sx(i).toFixed(1)}" y="${H - 4}" text-anchor="middle" font-size="9" fill="#86909c">${dates[i].substring(0, 7)}</text>`);
  }
  const lineColor = finalVal >= initCapital ? "#c92a2a" : "#2e7d32";
  return `<svg width="100%" height="150" viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" style="display:block;margin-top:8px;border-radius:6px;background:#fafbfc">
    <defs><linearGradient id="${gradId}" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="${lineColor}" stop-opacity="0.12"/><stop offset="100%" stop-color="${lineColor}" stop-opacity="0.01"/></linearGradient></defs>
    <line x1="${ml}" y1="${baselineY.toFixed(1)}" x2="${sx(n - 1).toFixed(1)}" y2="${baselineY.toFixed(1)}" stroke="#c9cdd4" stroke-dasharray="6,4" stroke-width="1"/>
    <polygon points="${areaPts}" fill="url(#${gradId})"/>
    <polyline points="${pts.join(" ")}" fill="none" stroke="${lineColor}" stroke-width="1.5" stroke-linejoin="round"/>
    ${yLabels}
    <circle cx="${sx(peakIdx).toFixed(1)}" cy="${sy(peakVal).toFixed(1)}" r="3" fill="#c92a2a" stroke="#fff" stroke-width="1"/>
    <circle cx="${sx(n - 1).toFixed(1)}" cy="${sy(finalVal).toFixed(1)}" r="3" fill="#3370ff" stroke="#fff" stroke-width="1"/>
    ${xLabels.join("")}
  </svg>`;
}

// 三色分级辅助
function _labLvl(val, thresholds) {
  if (val > thresholds.good) return "good";
  if (val < thresholds.bad) return "bad";
  return "warn";
}

// 最大回撤配色：国人风格 红=好(回撤小)/黄=一般/绿=差(回撤大)，与 .lab-matrix-good/warn/bad 同色值
// 阈值：回撤<20%=good红、20-40%=warn黄、>40%=bad绿
function _labDdColor(dd) {
  if (dd < 20) return "#c92a2a";   // good 红
  if (dd > 40) return "#2e7d32";   // bad 绿
  return "#ad6800";                 // warn 黄
}

// 渲染单个交易模式区块详情（4数字 + 净值曲线 + 折叠交易记录）
// 区块标题由外层 _labSimSectionHTML 的 .lab-sim-strat-head 提供，此处不含 head
// winData = {stats, trades, equity_curve}，已按当前窗口切片（_labPairWinData 产出）
function _labSimModeBlock(mode, winData, initCapital, page, isOpen, signalBtnHTML) {
  const s = winData && winData.stats;
  if (!s) {
    return `<div class="lab-sim-mode-block" data-mode="${mode}">` +
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
    let deltaHTML = '<span style="color:#c9cdd4">-</span>';
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
      `<div class="lab-sim-table-wrap"><table><thead><tr><th>#</th><th>买入日期</th><th>买入价</th><th>卖出日期</th><th>卖出价</th><th>收益率</th><th>持有</th><th>账户总资金</th><th>累计盈亏</th><th>累计收益率</th><th title="本笔累计收益率/累计盈亏相较上一笔的差值，红赚绿亏">较上次</th></tr></thead><tbody>` +
      (tradeRows || '<tr><td colspan="11" style="text-align:center;color:#c9cdd4">无交易记录</td></tr>') +
      `</tbody></table></div>${pagerHTML}</div>`
    : "";

  return `<div class="lab-sim-mode-block" data-mode="${mode}">` +
    `<div class="lab-sim-stats">` +
    `<div class="lab-sim-stat"><span class="k">总收益率</span><span class="v" style="color:${retColor}">${s.total_ret > 0 ? "+" : ""}${s.total_ret}%</span><span class="sub">期末 ${Math.round(s.final_total).toLocaleString()} 元</span></div>` +
    `<div class="lab-sim-stat"><span class="k">年化收益</span><span class="v" style="color:${retColor}">${s.annual_ret > 0 ? "+" : ""}${s.annual_ret}%</span><span class="sub">${s.years} 年</span></div>` +
    `<div class="lab-sim-stat"><span class="k">最大回撤</span><span class="v" style="color:${_labDdColor(s.max_drawdown)}">${s.max_drawdown}%</span><span class="sub">峰值最大跌幅</span></div>` +
    `<div class="lab-sim-stat"><span class="k">胜率</span><span class="v" style="color:${winColor}">${s.win_rate}%</span><span class="sub">${winTrades}胜/${loseTrades}负 · ${s.n_trades}笔</span></div>` +
    `</div>` +
    (signalBtnHTML || "") +
    `<div class="lab-sim-equity"><div class="lab-sim-equity-label">📈 净值曲线（虚线=初始本金）</div>${svgHTML}</div>` +
    `<div class="lab-sim-trades">` +
    `<div class="lab-sim-trades-header" data-mode="${mode}">` +
    `<span class="lab-sim-trades-label">📋 交易记录 共 ${totalReal} 笔${truncNote}</span>` +
    `<span class="lab-sim-trades-toggle">${isOpen ? "收起 ▲" : "展开 ▼"}</span>` +
    `</div>` +
    tradesBody +
    `</div>` +
    `</div>`;
}

// 渲染单个策略区块（标题+描述 -> 配对卡片切换 -> 详情）
// 上下两区各自独立：配对卡片切换、4数字、净值曲线、折叠交易记录都各自一套
// 新结构：pairs 在 simData.pairs 按 "buyKey|sellKey" 去重存储，按 mainKey 的 side 决定 partner 方向
function _labSimSectionHTML(mode, simData, mainKey, side, pairKeys, defaultPair, initCapital, pairSideLabel) {
  const modeName = mode === "full_in" ? "全仓交易策略" : "定额交易策略";
  const modeDesc = mode === "full_in"
    ? "每次全仓买入卖出，本金复利滚动，收益和风险都放大"
    : "每次固定买入1万元分批建仓，卖信号清仓，风险更分散";
  const win = state.labSimWindow || "y1";

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
    const wd = _labPairWinData(pairData, mode, win);
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
      `<span class="pc-name" title="${name}">${name}</span>` +
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
  const winData = _labPairWinData(pairData, mode, win);
  // 区块标题：策略名 + 当前配对名 + 描述（sticky 吸顶时常驻）
  const headHTML = `<div class="lab-sim-strat-head"><span class="lab-sim-strat-name">${modeName}</span><span class="lab-sim-strat-pair">· 配 ${curPairName}</span><span class="lab-sim-strat-desc">${modeDesc}</span></div>`;
  // 买卖信号弹窗入口：买策略+卖策略 key
  const signalBtnHTML = `<div class="lab-sim-signal-btn-wrap"><button type="button" class="lab-sim-signal-btn" data-buy="${buyKey}" data-sell="${sellKey}">📊 查看买卖信号</button></div>`;
  if (!winData || !winData.stats) {
    return `<div class="lab-sim-strat-section" data-mode="${mode}">` +
      headHTML + pairListHTML + '<div class="lab-sim-empty">该模式无交易数据</div>' + signalBtnHTML + '</div>';
  }

  const page = mode === "full_in" ? (state.labSimPageFi || 0) : (state.labSimPageFk || 0);
  const isOpen = mode === "full_in" ? !!state.labSimFiOpen : !!state.labSimFkOpen;
  const detailBlock = _labSimModeBlock(mode, winData, initCapital, page, isOpen, signalBtnHTML);

  return `<div class="lab-sim-strat-section" data-mode="${mode}">` +
    headHTML + pairListHTML + detailBlock + '</div>';
}

// 渲染模拟回测卡片（双策略上下常驻 · 各自独立配对切换 · 5窗口切换）
function _labSimCardHTML(key, simData) {
  if (!simData || !simData.strategies || !simData.strategies[key] || !simData.pairs) {
    const idxName = (simData && simData.index_name) || "该指数";
    return `<h3>💰 模拟回测（${idxName} · 配对交易）</h3><div class="lab-sim-empty">${simData ? "该策略暂无模拟回测数据" : "暂无模拟回测数据"}</div>`;
  }
  const strat = simData.strategies[key];
  const side = strat.side;
  const pairKeys = strat.partners || [];
  if (pairKeys.length === 0) {
    return '<h3>💰 模拟回测（配对交易）</h3><div class="lab-sim-empty">暂无模拟回测数据</div>';
  }

  // 默认配对：买策略配 D1 卖，卖策略配 C1 买
  const defaultPair = side === "buy" ? "D1_high20_drop5" : "C1_RSI30";
  const initCapital = simData.initial_capital || 100000;
  const pairSideLabel = side === "buy" ? "卖点" : "买点";

  // 上区：全仓交易策略 / 下区：定额交易策略（各自独立配对切换+详情）
  const fiSection = _labSimSectionHTML("full_in", simData, key, side, pairKeys, defaultPair, initCapital, pairSideLabel);
  const fkSection = _labSimSectionHTML("fixed_10k", simData, key, side, pairKeys, defaultPair, initCapital, pairSideLabel);

  // 窗口切换 tabs（默认近1年）
  const winLabel = LAB_WIN_DEFS.find((w) => w.k === (state.labSimWindow || "y1"));
  const idxName = simData.index_name || "";
  return `<h3>💰 模拟回测（${idxName} · 配对交易）</h3>` +
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
    const curWin = LAB_WIN_CN[state.labSimWindow || "y1"];
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
  const curWin = LAB_WIN_CN[state.labSimWindow || "y1"];
  document.querySelectorAll(".lab-matrix-table tbody tr").forEach((tr) => {
    const head = tr.querySelector(".lab-matrix-rowhead");
    tr.classList.toggle("lab-matrix-row-active", !!(head && head.textContent === curWin));
  });
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

// 渲染策略详情页
async function renderLabDetail(key) {
  const meta = LAB_STRATEGIES[key];
  if (!meta) { state.labStrategy = null; renderSignalLab(); return; }

  const data = await fetchLabData();
  const stratData = data && data.strategies ? data.strategies[key] : null;
  const tag = LAB_STATUS_TAGS[meta.status] || LAB_STATUS_TAGS.dev;

  content.innerHTML = "";

  // 返回按钮
  const backBtn = document.createElement("button");
  backBtn.className = "lab-back-btn";
  backBtn.innerHTML = "← 返回策略列表";
  backBtn.onclick = () => { state.labStrategy = null; renderSignalLab(); };
  content.appendChild(backBtn);

  // 标题 + 状态标签
  const header = document.createElement("div");
  header.className = "lab-detail-header";
  header.innerHTML = `<h2 class="lab-detail-title">${meta.name} <code class="lab-detail-key">${key}</code></h2>` +
    `<span class="lab-tag ${tag.cls}">${tag.label}</span>` +
    `<span class="lab-tag-side">${meta.side === "buy" ? "买点" : "卖点"}</span>`;
  content.appendChild(header);

  // 实验室自白黄块（所有策略都显示，通用介绍 + 抖音号）
  const warn = document.createElement("div");
  warn.className = "lab-warning lab-warning-essay";
  warn.innerHTML = _labWarningEssayHTML(meta.status);
  content.appendChild(warn);

  // 文案区
  const docCard = document.createElement("div");
  docCard.className = "chart-card lab-doc-card";
  docCard.innerHTML =
    '<h3>📖 策略说明</h3>' +
    '<div class="lab-doc-content">' +
    `<p><b>触发逻辑：</b>${meta.trigger}</p>` +
    `<p><b>理论依据：</b>${meta.theory}</p>` +
    `<p><b>适用场景：</b>${meta.scenario}</p>` +
    `<p><b>注意事项：</b>${meta.note}</p>` +
    `<p><b>08回测结论：</b>${meta.report}</p>` +
    '</div>';
  content.appendChild(docCard);

  // 图表区
  const chartSection = document.createElement("div");
  chartSection.className = "lab-chart-section";
  content.appendChild(chartSection);

  // 图表区：实验中策略显示指标曲线+信号标注，开发中策略显示占位
  if (LAB_CHART_KEYS[key]) {
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
    select.onchange = () => { state.labIndex = select.value; renderLabDetail(key); };
    filterBar.appendChild(select);
    chartSection.appendChild(filterBar);

    const chartDiv = document.createElement("div");
    chartDiv.innerHTML = '<div class="loading">加载中…</div>';
    chartSection.appendChild(chartDiv);

    try {
      const r = await fetchJSON(`./data/index/${state.labIndex}-all.json`);
      const ohlc = r.ohlc;
      if (!ohlc || !ohlc.length) {
        chartDiv.innerHTML = '<div class="empty-note">该指数暂无数据</div>';
      } else {
        const name = _INDEX_NAME_MAP[state.labIndex] || state.labIndex;
        const cfg = _labBuildChartConfig(key, ohlc, name);
        chartDiv.innerHTML = "";
        renderLabChartEx(cfg.chartTitle, ohlc, cfg.indicators, cfg.signals, chartDiv, charts, cfg.signalLabel, cfg.signalColor);
        const statDiv = document.createElement("div");
        statDiv.className = "lab-signal-stat";
        statDiv.innerHTML = `共触发 <b>${cfg.signals.length}</b> 个${cfg.statLabel}（全历史）`;
        chartDiv.appendChild(statDiv);
      }
    } catch (e) {
      chartDiv.innerHTML = `<div class="loading">加载失败：${e}</div>`;
    }
  } else {
    // 其他策略：开发中占位
    chartSection.innerHTML =
      '<div class="lab-placeholder">' +
      '<div class="lab-placeholder-icon">🔧</div>' +
      '<div class="lab-placeholder-text">图表开发中</div>' +
      '<div class="lab-placeholder-sub">该策略的交互式图表尚未实现，暂显示多周期回测矩阵。</div>' +
      '</div>';
  }

  // 回测区：多周期矩阵
  const matrixCard = document.createElement("div");
  matrixCard.className = "chart-card lab-matrix-card";
  const genAt = data ? data.generated_at : "";
  matrixCard.innerHTML =
    '<h3>📊 多周期回测矩阵</h3>' +
    '<div class="lab-matrix-legend"><b>怎么看这张表：</b>' +
    '<span><b>胜率</b>=信号后上涨(买)/下跌(卖)概率</span>' +
    '<span><b>平均收益</b>=每次操作平均赚多少(含亏的)</span>' +
    '<span><b>盈亏比</b>=平均赚÷平均亏，&gt;1才划算</span>' +
    '<span><b>样本</b>=测试了多少次信号</span></div>' +
    '<div class="lab-matrix-tip">⚠ 以上为单次操作平均收益，非连续复利；信号触发不定期，不可直接相乘。</div>' +
    '<div class="lab-matrix-wrap">' + renderLabMatrix(stratData) + '</div>' +
    '<div class="lab-matrix-foot">' +
    '<div class="lab-matrix-source">数据来源：买卖点策略深度回测（基于历史数据验证，重跑于 ' + (genAt || '2026-07-11') + '）</div>' +
    '<div class="lab-matrix-note"><b>这张表怎么测的：</b>信号触发当天按收盘价买入，持有 N 个交易日后按收盘价卖出，统计所有历史信号的平均效果。5d/10d/20d/60d = 持有 5/10/20/60 个交易日。<b>买点胜率</b>=信号后上涨占比；<b>卖点胜率</b>=信号后下跌占比（方向相反）。<b>这是单边统计</b>（每个信号独立看 N 日后涨跌），不是配对交易；真实配对实战收益见下方模拟回测。</div>' +
    '<div class="lab-matrix-legend-color"><span class="lab-matrix-good">红=好</span><span class="lab-matrix-warn">黄=一般</span><span class="lab-matrix-bad">绿=差</span></div>' +
    '</div>';
  content.appendChild(matrixCard);

  // 模拟回测卡片（配对交易 + 净值曲线 + 交易记录 + 买点切换 + 模式切换 + 分页）
  // lab_simulate_{index}.json 按指数拆分，前端按 state.labIndex 按需加载
  // 局部刷新：切指数只重渲染 simCard，不整页 reload（保留 tab/配对/模式/窗口上下文）
  state.labSimPairFi = null;
  state.labSimPairFk = null;
  state.labSimPageFi = 0;
  state.labSimPageFk = 0;
  state.labSimFiOpen = false;
  state.labSimFkOpen = false;
  const simCard = document.createElement("div");
  simCard.className = "chart-card lab-sim-card";
  const simIdxName = _INDEX_NAME_MAP[state.labIndex] || state.labIndex || "上证指数";
  simCard.innerHTML = `<h3>💰 模拟回测（${simIdxName} · 配对交易）</h3><div class="lab-sim-empty">⏳ 加载模拟回测数据中…</div>`;
  content.appendChild(simCard);
  // 检查该指数是否有模拟回测数据（仅4个指数有）
  const simIdx = LAB_SIM_INDEXES.find((x) => x.id === (state.labIndex || "sh"));
  if (!simIdx) {
    simCard.innerHTML = `<h3>💰 模拟回测（${simIdxName} · 配对交易）</h3><div class="lab-sim-empty">该指数暂无模拟回测数据（仅支持上证/深证/创业板/科创50）</div>`;
  } else {
    const simData = await fetchLabSimData(simIdx.id);
    const _rerenderSim = () => {
      if (!simData) {
        simCard.innerHTML = `<h3>💰 模拟回测（${simIdxName} · 配对交易）</h3><div class="lab-sim-empty">模拟回测数据加载失败，请稍后重试</div>`;
        return;
      }
      simCard.innerHTML = _labSimCardHTML(key, simData);
      _labSimAttachHandlers(key, simData, simCard, _rerenderSim);
      // 窗口切换后同步矩阵行高亮（矩阵与 sim 卡片在同一详情页）
      _labUpdateMatrixRowHighlight();
    };
    _rerenderSim();
  }
  // F5 恢复：更新 hash + 恢复滚动位置
  _labSetHash("#lab/" + key);
  _labRestoreScroll();
}

// === 回测推荐榜（列表页底部，128组配对多维度排序 + 点击弹窗细节）===
// 数据源：lab_simulate.json。新结构 pairs 按 "buyKey|sellKey" 去重存储（只存一份），
// 直接遍历 simData.pairs 即得 8买×8卖×2模式=128 组去重配对。窗口切换共用 state.labSimWindow。
const LAB_RANK_TABS = [
  { key: "composite", label: "🏆 综合推荐" },
  { key: "ret", label: "📈 收益率" },
  { key: "win", label: "🎯 胜率" },
  { key: "stable", label: "🛡 稳健(回撤小)" },
  { key: "risk_adj", label: "⚖ 风险调整" },
];

// 聚合128组配对 + 算综合评分与风险调整
// 新结构：simData.pairs 按 "buyKey|sellKey" 去重存储（配对只存一份），直接遍历即得 8买×8卖×2模式=128 组
function _labRankAggregate(simData, win) {
  if (!simData || !simData.pairs) return [];
  const rows = [];
  for (const pairKey in simData.pairs) {
    const parts = pairKey.split("|");
    const bk = parts[0], sk = parts[1];
    const pairData = simData.pairs[pairKey];
    for (const mode of ["full_in", "fixed_10k"]) {
      const wd = _labPairWinData(pairData, mode, win);
      if (!wd || !wd.stats) continue;
      const s = wd.stats;
      rows.push({
        buyKey: bk, sellKey: sk, mode,
        buyName: (LAB_STRATEGIES[bk] || {}).name || bk,
        sellName: (LAB_STRATEGIES[sk] || {}).name || sk,
        modeName: mode === "full_in" ? "全仓" : "定额",
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
  return `<button type="button" class="lab-rank-item" data-buy="${row.buyKey}" data-sell="${row.sellKey}" data-mode="${row.mode}">` +
    `<span class="lab-rank-no">${medal || "#" + rank}</span>` +
    `<span class="lab-rank-name">买${row.buyName} × 卖${row.sellName} · ${row.modeName}</span>` +
    `<span class="lab-rank-stats">` +
      `<span style="color:${retC}">收益${row.total_ret > 0 ? "+" : ""}${row.total_ret}%</span>` +
      `<span style="color:${winC}">胜${row.win_rate}%</span>` +
      `<span style="color:${ddC}">回撤${row.max_drawdown}%</span>` +
      `<span class="lab-rank-n">n=${row.n_trades}</span>` +
    `</span>` + extra + `</button>`;
}

function _labRankHTML(simData) {
  if (!simData) return '<div class="lab-rank-empty">推荐榜数据加载失败，请稍后重试</div>';
  const win = state.labSimWindow || "y1";
  const rows = _labRankAggregate(simData, win);
  if (rows.length === 0) return '<div class="lab-rank-empty">暂无推荐榜数据</div>';
  state.labRankRows = rows;
  const tab = state.labRankTab || "composite";
  const sorted = _labRankSort(rows, tab);
  const showAll = !!state.labRankShowAll;
  const shown = showAll ? sorted : sorted.slice(0, 20);
  const tabsHTML = LAB_RANK_TABS.map((t) =>
    `<button type="button" class="lab-rank-tab${t.key === tab ? " active" : ""}" data-tab="${t.key}">${t.label}</button>`
  ).join("");
  const itemsHTML = shown.map((r, i) => _labRankItemHTML(r, i + 1, tab)).join("");
  const moreBtn = sorted.length > 20
    ? `<button type="button" class="lab-rank-more">${showAll ? "收起 ▲" : `显示全部 ${sorted.length} 组 ▼`}</button>`
    : "";
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
    `<div class="lab-rank-list">${itemsHTML}</div>` + moreBtn;
}

function _labRankAttachHandlers(section, simData) {
  // 窗口切换
  section.querySelectorAll(".lab-win-tab").forEach((btn) => {
    btn.onclick = () => { state.labSimWindow = btn.dataset.win; _labRankRerender(section, simData); };
  });
  section.querySelectorAll(".lab-rank-tab").forEach((btn) => {
    btn.onclick = () => { state.labRankTab = btn.dataset.tab; state.labRankShowAll = false; _labRankRerender(section, simData); };
  });
  section.querySelectorAll(".lab-rank-item").forEach((item) => {
    item.onclick = () => _labRankOpenModal(simData, item.dataset.buy, item.dataset.sell, item.dataset.mode);
  });
  const more = section.querySelector(".lab-rank-more");
  if (more) more.onclick = () => { state.labRankShowAll = !state.labRankShowAll; _labRankRerender(section, simData); };
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
  const win = state.labSimWindow || "y1";
  const pairData = _labGetPair(simData, m.buyKey, m.sellKey);
  const winData = _labPairWinData(pairData, m.mode, win);
  const buyName = (LAB_STRATEGIES[m.buyKey] || {}).name || m.buyKey;
  const sellName = (LAB_STRATEGIES[m.sellKey] || {}).name || m.sellKey;
  const modeName = m.mode === "full_in" ? "全仓" : "定额";
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
  state.labSignalModal = {
    buyKey, sellKey,
    index: state.labIndex || "sh",
    period: "1y",
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

// 买卖信号弹窗周期切换：根据全历史 ohlc 末日回推 N 年，返回 YYYYMMDD 截止日（含）
// period: 1y/3y/5y/all。all 返回 null（不过滤）。ohlc 末日为YYYYMMDD字符串。
function _labSignalCutoffDate(ohlc, period) {
  if (!ohlc || !ohlc.length || period === "all") return null;
  const last = ohlc[ohlc.length - 1].date;
  if (!last || last.length < 8) return null;
  const y = parseInt(last.substring(0, 4), 10);
  const m = parseInt(last.substring(4, 6), 10);
  const d = parseInt(last.substring(6, 8), 10);
  const yrs = period === "1y" ? 1 : period === "3y" ? 3 : period === "5y" ? 5 : 0;
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

  const period = m.period || "1y";
  const periodOpts = [["1y", "1年"], ["3y", "3年"], ["5y", "5年"], ["all", "全历史"]];
  const periodBtnsHTML = periodOpts.map(([p, lbl]) =>
    `<button type="button" class="lab-signal-period-btn${period === p ? " active" : ""}" data-period="${p}">${lbl}</button>`
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
    b.onclick = () => { m.period = b.dataset.period; _labSignalModalRender(overlay); };
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

    // 按周期切片 ohlc + 指标 + 信号（指标在全历史算好后切片，避免窗口边界预热失真）
    const cutoff = _labSignalCutoffDate(ohlcFull, period);
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

    const periodLabel = period === "all" ? "全历史" : period === "1y" ? "近1年" : period === "3y" ? "近3年" : "近5年";
    const title = `${indexName} · 买卖信号（${periodLabel}）`;
    chartArea.innerHTML = "";
    renderLabChartEx(title, ohlc, slicedInd, sigs, chartArea, m.charts, "信号", "#9c27b0");
    const buyCnt = sigs.filter((x) => x.color === BUY_COLOR).length;
    const sellCnt = sigs.filter((x) => x.color === SELL_COLOR).length;
    const statDiv = document.createElement("div");
    statDiv.className = "lab-signal-stat";
    statDiv.innerHTML = `${periodLabel}触发：<b style="color:${BUY_COLOR}">买 ${buyCnt}</b> · <b style="color:${SELL_COLOR}">卖 ${sellCnt}</b>`;
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
  }
});

// 渲染策略实验室主入口（分区tab + 卡片列表 / 详情页）
async function renderSignalLab() {
  // 如果有选中的策略，进详情页
  if (state.labStrategy) {
    await renderLabDetail(state.labStrategy);
    return;
  }

  content.innerHTML = "";

  // 标题
  const h = document.createElement("h2");
  h.className = "lab-title";
  h.textContent = "🧪 策略实验室";
  content.appendChild(h);

  // 实验室自白黄块（列表页也显示，通用介绍 + 抖音号）
  const essayWarn = document.createElement("div");
  essayWarn.className = "lab-warning lab-warning-essay";
  essayWarn.innerHTML = _labWarningEssayHTML();
  content.appendChild(essayWarn);

  // 预加载回测数据（用于卡片摘要）
  const data = await fetchLabData();

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
  content.appendChild(zoneTabs);

  // 分区描述
  const curZone = LAB_ZONES.find((z) => z.key === state.labZone) || LAB_ZONES[1];
  const zoneDesc = document.createElement("div");
  zoneDesc.className = "lab-zone-desc";
  zoneDesc.textContent = curZone.desc;
  content.appendChild(zoneDesc);

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
    card.onclick = () => { state.labStrategy = key; renderSignalLab(); };
    list.appendChild(card);
  });
  content.appendChild(list);

  // 回测推荐榜（列表页底部空白区，按指数加载 lab_simulate_{index}.json，不阻塞上方骨架）
  const rankSection = document.createElement("div");
  rankSection.className = "chart-card lab-rank-card";
  // 指数选择器（持久，不随 rank body 重渲染消失）
  const rankIdxOpts = LAB_SIM_INDEXES.map((x) =>
    `<option value="${x.id}"${x.id === (state.labSimIndex || "sh") ? " selected" : ""}>${x.name}</option>`
  ).join("");
  rankSection.innerHTML = '<h3>🏆 回测推荐榜</h3>' +
    `<div class="lab-win-bar"><span class="lab-win-bar-label">选择指数</span><select class="lab-rank-index">${rankIdxOpts}</select></div>` +
    '<div class="lab-rank-body"><div class="lab-rank-loading">⏳ 加载推荐榜数据中…</div></div>';
  content.appendChild(rankSection);
  const _loadRank = async () => {
    const idx = state.labSimIndex || "sh";
    const simData = await fetchLabSimData(idx);
    _labRankRerender(rankSection, simData);
  };
  _loadRank();
  // 指数切换：重新加载该指数数据并重渲染 rank body
  rankSection.querySelector(".lab-rank-index").onchange = (e) => {
    state.labSimIndex = e.target.value;
    state.labRankShowAll = false;
    const body = rankSection.querySelector(".lab-rank-body");
    if (body) body.innerHTML = '<div class="lab-rank-loading">⏳ 加载中…</div>';
    _loadRank();
  };

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
