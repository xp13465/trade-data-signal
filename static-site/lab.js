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

function renderLabChart(title, ohlc, bb, signals, container, chartArr) {
  const c = mkCard(title, 400, null, container, chartArr);
  const dates = ohlc.map((d) => d.date);
  const markData = signals.map((s) => ({
    coord: [s.date, s.close],
    value: "实验卖",
    itemStyle: { color: "#9c27b0" },
  }));
  c.setOption({
    tooltip: { trigger: "axis" },
    legend: { top: 0, data: ["收盘价", "布林上轨", "布林下轨"] },
    grid: { left: 55, right: 20, top: 35, bottom: 50 },
    xAxis: { type: "category", data: dates },
    yAxis: { type: "value", scale: true },
    dataZoom: [{ type: "inside" }, { type: "slider", height: 18, bottom: 8 }],
    series: [
      {
        name: "收盘价", type: "line", smooth: true, symbol: "none",
        data: ohlc.map((d) => d.close), lineStyle: { width: 1.5 },
        markPoint: {
          symbol: "pin", symbolSize: 34,
          label: { fontSize: 10, color: "#fff" },
          data: markData,
        },
      },
      {
        name: "布林上轨", type: "line", symbol: "none", data: bb.bu, smooth: true,
        lineStyle: { width: 1, type: "dashed", color: "#c9cdd4" },
      },
      {
        name: "布林下轨", type: "line", symbol: "none", data: bb.bl, smooth: true,
        lineStyle: { width: 1, type: "dashed", color: "#c9cdd4" },
      },
    ],
  });
  return c;
}

// === 22策略元数据注册表（分区/状态/触发/结论/理论/场景/注意/08报告结论）===
// 文案来源：买卖点策略深度回测.md（重跑于 2026-07-11，244资产全史/近10年/近5年/近3年/近1年 × 5d/10d/20d/60d）
// zone: buy=候选买点 / sell=候选卖点 / excluded=已排除 / prod=生产参考
// status: live=已上线生产 / experimental=实验中 / dev=开发中 / excluded=已排除
const LAB_STRATEGIES = {
  // --- 候选买点区（7个） ---
  BB_lower_revert: {
    name: "布林下轨回归买", side: "buy", zone: "buy", status: "dev",
    trigger: "前一日 close 跌破 BB 下轨，当日 close 收回下轨之上（超卖反弹）",
    conclusion: "3/4窗口达标并列第1，近3年60d盈亏比1.84最高，与C1语义互补",
    theory: "布林带下轨回归。价格跌破下轨后收回，意味超卖极端已过、反弹拐点出现。与C1同为「超卖反弹」语义，但用价格穿越BB下轨而非RSI阈值，强势市更敏感。",
    scenario: "震荡市/下跌市超卖反弹；强势市中RSI未到30但价格已破下轨时补C1盲区。",
    note: "近1年是唯一达标买点（52.1%/1.23），与C1互补性最强。信号密集度中等。",
    report: "08报告：BB_lower_revert 达标数3/4（近10年/近3年/近1年），与C1并列第1。近3年60d盈亏比1.79、均值+4.7%为买点最高。近1年（强势单边市）是唯一达标买点，补强C1在强势市的盲区。语义与C1正交（价格穿越 vs RSI阈值），适合做互补买点。",
  },
  Supertrend_buy: {
    name: "Supertrend翻多买", side: "buy", zone: "buy", status: "dev",
    trigger: "ATR(10)×3 趋势线从翻空转为翻多（趋势跟踪买点）",
    conclusion: "2/4达标，语义与C1正交（趋势启动 vs 超卖反弹），最佳互补候选",
    theory: "Supertrend 指标基于 ATR 的动态趋势线。翻多意味趋势已确认启动，与C1的「超卖反弹」正交，捕捉的是趋势延续而非拐点。",
    scenario: "趋势启动确认；与C1互补覆盖不同市场状态。",
    note: "近3年全horizon胜率≥48.8%，盈亏比1.40-1.61。信号较C1稀疏。",
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
    name: "MA5/MA20死叉卖", side: "sell", zone: "sell", status: "dev",
    trigger: "MA5 下穿 MA20（短期死叉卖点）",
    conclusion: "近3年20d胜率56.3%最高，短周期偏弱但中周期强",
    theory: "双均线死叉。短期均线下穿长期均线意味短期动量转弱，经典趋势转弱确认。",
    scenario: "趋势转弱减仓；震荡市频繁假死叉。",
    note: "近3年20d胜率54.8%较高，但5d/10d偏弱。PL0.90<1。",
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
  { key: "buy", label: "🧪 候选买点", count: 7, desc: "候选买点策略（开发中）" },
  { key: "sell", label: "🧪 候选卖点", count: 7, desc: "候选卖点策略（含BB_upper_revert实验中）" },
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

// 获取 lab_simulate.json 数据（缓存到 state.labSimData）
async function fetchLabSimData() {
  if (state.labSimData) return state.labSimData;
  try {
    state.labSimData = await fetchJSON("./data/lab/lab_simulate.json");
  } catch (e) {
    state.labSimData = null;
  }
  return state.labSimData;
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

// 渲染单个交易模式区块（全仓进出 / 1万定额）
function _labSimModeBlock(mode, modeData, initCapital, page, isOpen) {
  const modeName = mode === "full_in" ? "全仓进出" : "1万定额";
  const modeDesc = mode === "full_in"
    ? "本金复利滚动 · 全仓买卖"
    : "每次买1万(最多10笔) · 卖信号清仓";
  const s = modeData && modeData.stats;
  if (!s) {
    return `<div class="lab-sim-mode-block" data-mode="${mode}">` +
      `<div class="lab-sim-mode-head"><span class="lab-sim-mode-name">${modeName}</span><span class="lab-sim-mode-desc">${modeDesc}</span></div>` +
      `<div class="lab-sim-empty">该模式无交易数据</div></div>`;
  }

  const retColor = s.total_ret >= 0 ? "#c92a2a" : "#2e7d32";
  const winColor = s.win_rate >= 50 ? "#c92a2a" : "#2e7d32";
  const winTrades = Math.round((s.win_rate / 100) * s.n_trades);
  const loseTrades = s.n_trades - winTrades;
  const gradId = "labSimGrad_" + mode;
  const svgHTML = _labSimSVG(modeData.equity_curve, initCapital, gradId);
  const trades = modeData.trades || [];

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
    const tc = t.ret > 0 ? "#c92a2a" : (t.ret < 0 ? "#2e7d32" : "#86909c");
    const cr = t.cumulative_return != null ? t.cumulative_return : 0;
    const pc = cr >= 0 ? "#c92a2a" : "#2e7d32";
    const at = t.account_total != null ? Math.round(t.account_total).toLocaleString() : "-";
    const cp = t.cumulative_profit != null ? (t.cumulative_profit >= 0 ? "+" : "") + Math.round(t.cumulative_profit).toLocaleString() : "-";
    const crStr = t.cumulative_return != null ? (cr >= 0 ? "+" : "") + t.cumulative_return + "%" : "-";
    return `<tr><td>${startIdx + i + 1}</td><td>${t.buy_date}</td><td>${t.buy_price}</td><td>${t.sell_date}</td><td>${t.sell_price}</td><td style="color:${tc};font-weight:600">${t.ret > 0 ? "+" : ""}${t.ret}%</td><td>${t.hold_days}天</td><td>${at}</td><td style="color:${pc}">${cp}</td><td style="color:${pc};font-weight:600">${crStr}</td></tr>`;
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
      `<div class="lab-sim-table-wrap"><table><thead><tr><th>#</th><th>买入日期</th><th>买入价</th><th>卖出日期</th><th>卖出价</th><th>收益率</th><th>持有</th><th>账户总资金</th><th>累计盈亏</th><th>累计收益率</th></tr></thead><tbody>` +
      (tradeRows || '<tr><td colspan="10" style="text-align:center;color:#c9cdd4">无交易记录</td></tr>') +
      `</tbody></table></div>${pagerHTML}</div>`
    : "";

  return `<div class="lab-sim-mode-block" data-mode="${mode}">` +
    `<div class="lab-sim-mode-head"><span class="lab-sim-mode-name">${modeName}</span><span class="lab-sim-mode-desc">${modeDesc}</span></div>` +
    `<div class="lab-sim-stats">` +
    `<div class="lab-sim-stat"><span class="k">总收益率</span><span class="v" style="color:${retColor}">${s.total_ret > 0 ? "+" : ""}${s.total_ret}%</span><span class="sub">期末 ${Math.round(s.final_total).toLocaleString()} 元</span></div>` +
    `<div class="lab-sim-stat"><span class="k">年化收益</span><span class="v" style="color:${retColor}">${s.annual_ret > 0 ? "+" : ""}${s.annual_ret}%</span><span class="sub">${s.years} 年</span></div>` +
    `<div class="lab-sim-stat"><span class="k">最大回撤</span><span class="v" style="color:#2e7d32">${s.max_drawdown}%</span><span class="sub">峰值最大跌幅</span></div>` +
    `<div class="lab-sim-stat"><span class="k">胜率</span><span class="v" style="color:${winColor}">${s.win_rate}%</span><span class="sub">${winTrades}胜/${loseTrades}负 · ${s.n_trades}笔</span></div>` +
    `</div>` +
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

// 渲染模拟回测卡片（配对交易 + 双交易策略并列对比 + 折叠交易记录）
function _labSimCardHTML(key, simData) {
  if (!simData || !simData.strategies || !simData.strategies[key] || !simData.strategies[key].pairs) {
    return '<h3>💰 模拟回测（配对交易 · 全仓 vs 定额并列对比）</h3><div class="lab-sim-empty">暂无模拟回测数据</div>';
  }
  const strat = simData.strategies[key];
  const side = strat.side;
  const pairs = strat.pairs;
  const pairKeys = Object.keys(pairs);
  if (pairKeys.length === 0) {
    return '<h3>💰 模拟回测（配对交易 · 全仓 vs 定额并列对比）</h3><div class="lab-sim-empty">暂无模拟回测数据</div>';
  }

  // 默认配对：买策略配 D1 卖，卖策略配 C1 买
  const defaultPair = side === "buy" ? "D1_high20_drop5" : "C1_RSI30";
  let currentPair = state.labSimPair || defaultPair;
  if (!pairs[currentPair]) currentPair = pairKeys[0];
  state.labSimPair = currentPair;

  const pairSideLabel = side === "buy" ? "卖点" : "买点";
  const initCapital = simData.initial_capital || 100000;

  // 配对策略卡片列表（双模式摘要：全仓 ret/胜率 + 定额 ret/胜率）
  const pairCards = pairKeys.map((pk) => {
    const meta = LAB_STRATEGIES[pk];
    const name = meta ? meta.name : pk;
    const pd = pairs[pk];
    const fiSt = pd && pd.full_in && pd.full_in.stats;
    const fkSt = pd && pd.fixed_10k && pd.fixed_10k.stats;
    // 卡片整体分级基于 full_in
    let lvl = "warn";
    if (fiSt) {
      const retLv = _labLvl(fiSt.total_ret, { good: 5, bad: -5 });
      const winLv = _labLvl(fiSt.win_rate, { good: 55, bad: 45 });
      const goods = [retLv, winLv].filter((x) => x === "good").length;
      const bads = [retLv, winLv].filter((x) => x === "bad").length;
      lvl = goods >= 2 ? "good" : bads >= 2 ? "bad" : "warn";
    }
    const activeCls = pk === currentPair ? " active" : "";
    const fiRow = fiSt
      ? `<span class="pc-mode-row"><span class="pc-mode-tag">全仓</span>` +
        `<span class="pc-ret pc-lvl-${_labLvl(fiSt.total_ret, { good: 5, bad: -5 })}">${fiSt.total_ret > 0 ? "+" : ""}${fiSt.total_ret}%</span>` +
        `<span class="pc-win pc-lvl-${_labLvl(fiSt.win_rate, { good: 55, bad: 45 })}">胜${fiSt.win_rate}%</span></span>`
      : "";
    const fkRow = fkSt
      ? `<span class="pc-mode-row"><span class="pc-mode-tag">定额</span>` +
        `<span class="pc-ret-sm pc-lvl-${_labLvl(fkSt.total_ret, { good: 5, bad: -5 })}">${fkSt.total_ret > 0 ? "+" : ""}${fkSt.total_ret}%</span>` +
        `<span class="pc-win-sm pc-lvl-${_labLvl(fkSt.win_rate, { good: 55, bad: 45 })}">胜${fkSt.win_rate}%</span></span>`
      : "";
    const nStr = fiSt ? `<span class="pc-n">样本 n=${fiSt.n_trades}</span>` : "";
    return `<button type="button" class="lab-sim-pair-card lab-matrix-${lvl}${activeCls}" data-pair="${pk}">` +
      `<span class="pc-name" title="${name}">${name}</span>${fiRow}${fkRow}${nStr}</button>`;
  }).join("");

  const pairListHTML =
    `<div class="lab-sim-pair-section"><div class="lab-sim-pair-label">配对${pairSideLabel}（点卡片切换 · 红好/绿差）</div>` +
    `<div class="lab-sim-pair-list">${pairCards}</div></div>`;

  const pairData = pairs[currentPair];
  if (!pairData || !pairData.full_in || !pairData.full_in.stats) {
    return '<h3>💰 模拟回测（配对交易 · 全仓 vs 定额并列对比）</h3>' +
      pairListHTML + '<div class="lab-sim-empty">该配对无交易数据</div>';
  }

  const pageFi = state.labSimPageFi || 0;
  const pageFk = state.labSimPageFk || 0;
  const fiOpen = !!state.labSimFiOpen;
  const fkOpen = !!state.labSimFkOpen;

  const fiBlock = _labSimModeBlock("full_in", pairData.full_in, initCapital, pageFi, fiOpen);
  const fkBlock = _labSimModeBlock("fixed_10k", pairData.fixed_10k, initCapital, pageFk, fkOpen);

  return '<h3>💰 模拟回测（配对交易 · 全仓 vs 定额并列对比）</h3>' +
    pairListHTML +
    `<div class="lab-sim-dual">${fiBlock}${fkBlock}</div>`;
}

// 模拟回测卡片交互绑定（配对切换 / 交易记录折叠 / 分页）
function _labSimAttachHandlers(key, simData, simCard, rerender) {
  // 配对策略卡片切换
  simCard.querySelectorAll(".lab-sim-pair-card").forEach((card) => {
    card.onclick = () => {
      state.labSimPair = card.dataset.pair;
      state.labSimPageFi = 0;
      state.labSimPageFk = 0;
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
    html += `<tr><td class="lab-matrix-rowhead">${w}</td>`;
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

  if (key === "BB_upper_revert") {
    // BB_upper_revert：复用 computeBBLab + renderLabChart + 指数选择器
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
        const bb = computeBBLab(ohlc);
        chartDiv.innerHTML = "";
        const name = _INDEX_NAME_MAP[state.labIndex] || state.labIndex;
        renderLabChart(`${name} · 布林上轨回落实验`, ohlc, bb, bb.signals, chartDiv, charts);
        const statDiv = document.createElement("div");
        statDiv.className = "lab-signal-stat";
        statDiv.innerHTML = `共触发 <b>${bb.signals.length}</b> 个实验卖点（全历史）`;
        chartDiv.appendChild(statDiv);
      }
    } catch (e) {
      chartDiv.innerHTML = `<div class="loading">加载失败：${e}</div>`;
    }
  } else {
    // 其他21个策略：开发中占位
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
  // lab_simulate.json 较大（~3MB），先渲染 loading 占位，异步加载就绪后填充，不阻塞上方骨架
  state.labSimPair = null;
  state.labSimPageFi = 0;
  state.labSimPageFk = 0;
  state.labSimFiOpen = false;
  state.labSimFkOpen = false;
  const simCard = document.createElement("div");
  simCard.className = "chart-card lab-sim-card";
  simCard.innerHTML = '<h3>💰 模拟回测（配对交易）</h3><div class="lab-sim-empty">⏳ 加载模拟回测数据中…（约3MB，请稍候）</div>';
  content.appendChild(simCard);
  const simData = await fetchLabSimData();
  const _rerenderSim = () => {
    if (!simData) {
      simCard.innerHTML = '<h3>💰 模拟回测（配对交易）</h3><div class="lab-sim-empty">模拟回测数据加载失败，请稍后重试</div>';
      return;
    }
    simCard.innerHTML = _labSimCardHTML(key, simData);
    _labSimAttachHandlers(key, simData, simCard, _rerenderSim);
  };
  _rerenderSim();
}

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
}
