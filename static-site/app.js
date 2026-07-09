// 静态版前端 —— 从 web/app.js 改造，数据源由 API 改为本地 JSON 文件。
// 改动点：
//   1. fetchJSON URL：/api/xxx → ./data/xxx.json（各 tab 按 range 读对应文件）
//   2. index 详情：读 ./data/index/{id}-all.json 全历史，前端按 ohlc 日期范围过滤 signals
//   3. 其他逻辑（render/ruleBar/signalColor/initBackToTop/initStickyOffset）保持功能一致
//   4. 手动补录入口已移除（与动态版一致）

// BUG-E：交互增强状态——indexFilter（A 股/港股 指数筛选）/ industrySearch（行业搜索）/ heatmapRange（热力图近1日/近5日切换）。
// 筛选只控制前端显示哪些折线/行业，不影响后端数据。
const state = { tab: "overview", range: "1y", indexFilter: "all", industrySearch: "", heatmapRange: "all", subtab: "a-stock" };
const content = document.getElementById("content");
const charts = [];
// 已生成模拟回测页面的品种（📊 模拟回测按钮显示条件）
const SIM_INDICES = new Set([
  'sh', 'sz', 'cyb', 'csi500', 'csi1000', 'kc50', 'hs300',
  'hsi', 'hscei', 'hstech', 'div_lowvol', 'csi_div',
  'us_ixic', 'us_spx', 'us_dji', 'us_ndx',
  'g.gold', 'g.comex_silver', 'g.wti_oil', 'g.us10y', 'g.a_qvix_300', 'g.a_qvix_1000',
  'gold', 'comex_silver', 'wti_oil',
  'sw_801010', 'sw_801030', 'sw_801040', 'sw_801050', 'sw_801080',
  'sw_801110', 'sw_801130', 'sw_801150', 'sw_801160', 'sw_801170',
  'sw_801180', 'sw_801210', 'sw_801230',
  'sw_801710', 'sw_801720', 'sw_801730', 'sw_801740', 'sw_801750',
  'sw_801760', 'sw_801770', 'sw_801780', 'sw_801790',
  'sw_801880', 'sw_801890', 'sw_801950', 'sw_801960', 'sw_801970', 'sw_801980',
  'thsc_300816', 'thsc_309119', 'thsc_308700', 'thsc_309049', 'thsc_301085',
  'thsc_307940', 'thsc_302035', 'thsc_309068', 'thsc_308828', 'thsc_309020',
  'thsc_309060', 'thsc_300008', 'thsc_301079', 'thsc_300733', 'thsc_306380',
  'thsc_308294', 'thsc_309115', 'thsc_308014', 'thsc_300082', 'thsc_300830',
  'thsc_308725', 'thsc_308300', 'thsc_309113', 'thsc_308491', 'thsc_308870',
  'thsc_308752', 'thsc_309128'
]);
// 全球 tab extras 回的 id 无 g. 前缀（如 gold），需映射到实际文件名（如 g.gold）
const SIM_HREF_MAP = { gold: 'g.gold', comex_silver: 'g.comex_silver', wti_oil: 'g.wti_oil' };

window.addEventListener("resize", () => charts.forEach((c) => c && c.resize()));

document.querySelectorAll('.periods button[data-rng]').forEach((b) => {
  b.onclick = () => {
    state.range = b.dataset.rng;
    document.querySelectorAll('.periods button[data-rng]').forEach((x) => x.classList.remove("active"));
    b.classList.add("active");
    renderTab();
  };
});
document.querySelectorAll(".tabs button[data-tab]").forEach((b) => {
  b.onclick = () => {
    state.tab = b.dataset.tab;
    if (state.tab === "market" && !state.subtab) state.subtab = "a-stock";
    document.querySelectorAll(".tabs button[data-tab]").forEach((x) => x.classList.remove("active"));
    b.classList.add("active");
    renderTab();
  };
});

function clearCharts() {
  charts.forEach((c) => c && c.dispose());
  charts.length = 0;
  content.innerHTML = "";
}

// container/chartArr 可选：默认挂 content + push 全局 charts；指数区局部刷新时传入本区容器 + 本区 chart 列表。
function mkCard(title, height = 300, hint = null, container = content, chartArr = charts) {
  const div = document.createElement("div");
  div.className = "chart-card";
  const hintHtml = hint ? `<div class="chart-hint">${hint}</div>` : "";
  div.innerHTML = `<h3>${title}</h3>${hintHtml}<div class="chart" style="height:${height}px"></div>`;
  container.appendChild(div);
  const c = echarts.init(div.querySelector(".chart"));
  chartArr.push(c);
  return c;
}

// 通用折线：series = [{name, data:[{date,value}]}] 或单条 [{date,value}]
function lineChart(title, series, opts = {}, hint = null, container = content) {
  const multi = Array.isArray(series) && series.length && series[0] && series[0].data;
  const arr = multi ? series : [{ name: title, data: series }];
  const dates = [...new Set(arr.flatMap((s) => s.data.map((d) => d.date)))].sort();
  const c = mkCard(title, 300, hint, container);
  c.setOption({
    tooltip: { trigger: "axis" },
    legend: { top: 0, type: "scroll" },
    grid: { left: 55, right: 20, top: 35, bottom: 35 },
    xAxis: { type: "category", data: dates },
    yAxis: { type: "value", scale: true },
    dataZoom: [{ type: "inside" }, { type: "slider", height: 18, bottom: 8 }],
    series: arr.map((s) => ({
      name: s.name,
      type: "line",
      smooth: true,
      symbol: "none",
      connectNulls: true,
      data: dates.map((d) => {
        const p = s.data.find((x) => x.date === d);
        return p ? p.value : null;
      }),
    })),
    ...opts,
  });
  return c;
}

// 卖点 markPoint 配色（方案 B 标注，2026-07-06）：买=红、卖止盈=绿、卖买点失败=灰、卖无前买=橙。
// B1+S1（2026-07-05）：buy_aux 辅买=粉紫 #d63384（与 buy 红 区分）。
// 判断按 reason 子串：含"买点失败"→灰、"止盈"→绿、"无前买点"→橙；买=红；兜底旧卖点无标签按绿。
function signalColor(s) {
  if (s.signal === "buy") return "#e6492e";
  if (s.signal === "buy_aux") return "#d63384";
  const r = s.reason || "";
  if (r.includes("买点失败")) return "#9e9e9e";
  if (r.includes("止盈")) return "#2e8b57";
  if (r.includes("无前买点")) return "#ff9800";
  return "#2e8b57";
}

// markPoint 标签文案：buy→"买"、buy_aux→"辅买"、sell→"卖"。
function signalLabel(s) {
  if (s.signal === "buy") return "买";
  if (s.signal === "buy_aux") return "辅买";
  return "卖";
}

// 情绪分文字标签：散户秒懂，数值旁边加标签
function sentimentTag(value) {
  if (value == null) return "";
  if (value <= 20) return "🔴 冰点";
  if (value <= 40) return "🟠 偏冷";
  if (value <= 60) return "⚪ 中性";
  if (value <= 80) return "🟢 偏热";
  return "🔥 过热";
}

// 恐贪指数标签：0-25 极度恐惧，25-40 恐惧，40-60 中性，60-75 贪婪，75-100 极度贪婪
function fearGreedLabel(value) {
  if (value == null) return "";
  if (value <= 25) return "😱 极度恐惧";
  if (value <= 40) return "😟 恐惧";
  if (value <= 60) return "😐 中性";
  if (value <= 75) return "😤 贪婪";
  return "🤩 极度贪婪";
}

// 恐贪标签颜色：极度恐惧=深红，恐惧=橙，中性=灰，贪婪=浅绿，极度贪婪=深绿
function fearGreedColor(value) {
  if (value == null) return "#86909c";
  if (value <= 25) return "#c62828";
  if (value <= 40) return "#e6a23c";
  if (value <= 60) return "#86909c";
  if (value <= 75) return "#67c23a";
  return "#2e8b57";
}

// index_id → 中文名 转译（散户友好，去除代码前缀，查不到保留原值）
const _INDEX_NAME_MAP = {
  // A股宽基
  sh: '上证指数', sz: '深证成指', cyb: '创业板指', csi500: '中证500', csi1000: '中证1000',
  kc50: '科创50', hs300: '沪深300', sz50: '上证50',
  // 港股
  hsi: '恒生指数', hscei: '国企指数', hstech: '恒生科技',
  // 美股
  us_dji: '道琼斯', us_ixic: '纳斯达克', us_spx: '标普500', us_ndx: '纳斯达克100',
  // 红利/低波
  div_lowvol: '红利低波', csi_div: '中证红利', sz_div: '深证红利',
  // 全球指标
  cn10y: '中国10年国债', us10y: '美国10年国债', wti_oil: 'WTI原油',
  comex_silver: 'COMEX白银', gold: '伦敦金', oil: '原油', usdcnh: '美元/离岸人民币',
  a_qvix_300: '300波动率', a_qvix_1000: '1000波动率', cn_us_spread: '中美利差',
  // 综合情绪
  cross_market: '跨市场综合分', a_sentiment: 'A股综合情绪分',
  sentiment_sz50: '上证50情绪分', sentiment_hs300: '沪深300情绪分',
  sentiment_csi500: '中证500情绪分', sentiment_csi1000: '中证1000情绪分',
  sentiment_cyb: '创业板情绪分', sentiment_kc50: '科创50情绪分',
  fear_greed: '恐贪指数',
  // 申万行业（31个）
  sw_801010: '农林牧渔', sw_801030: '基础化工', sw_801040: '钢铁', sw_801050: '有色金属',
  sw_801080: '电子', sw_801110: '家用电器', sw_801120: '食品饮料', sw_801130: '纺织服饰',
  sw_801140: '轻工制造', sw_801150: '医药生物', sw_801160: '公用事业', sw_801170: '交通运输',
  sw_801180: '房地产', sw_801200: '商贸零售', sw_801210: '社会服务', sw_801230: '综合',
  sw_801710: '建筑材料', sw_801720: '建筑装饰', sw_801730: '电力设备', sw_801740: '国防军工',
  sw_801750: '计算机', sw_801760: '传媒', sw_801770: '通信', sw_801780: '银行',
  sw_801790: '非银金融', sw_801880: '汽车', sw_801890: '机械设备', sw_801950: '煤炭',
  sw_801960: '石油石化', sw_801970: '环保', sw_801980: '美容护理',
  // 概念板块（27个同花顺）
  thsc_300008: '新能源汽车', thsc_300082: '军工', thsc_300733: '锂电池概念',
  thsc_300816: '机器人概念', thsc_300830: '量子科技', thsc_301079: '光伏概念',
  thsc_301085: '芯片概念', thsc_302035: '人工智能', thsc_306380: '储能',
  thsc_307940: '存储芯片', thsc_308014: '创新药', thsc_308294: '固态电池',
  thsc_308300: 'MCU芯片', thsc_308491: '氢能源', thsc_308700: '第三代半导体',
  thsc_308725: '汽车芯片', thsc_308752: '元宇宙', thsc_308828: '东数西算(算力)',
  thsc_308870: '数字经济', thsc_309020: '信创', thsc_309049: '共封装光学(CPO)',
  thsc_309060: '数据要素', thsc_309068: '算力租赁', thsc_309113: '飞行汽车(eVTOL)',
  thsc_309115: '低空经济', thsc_309119: '人形机器人', thsc_309128: '军工信息化',
};

function indexIdToName(indexId) {
  // 去掉 g./s. 前缀后查表
  const key = indexId.replace(/^(g|s)\./, '');
  return _INDEX_NAME_MAP[key] || indexId;
}

// 买卖点回测 stats tips（折线图上方）：散户化多块文案 + 胜率配色梯度 + 凯利公式折叠详解。
// stats = {buy:{10d:{win_rate,pl,mean,n}}, buy_aux:..., sell:...}
// "10日"= 信号后 10 交易日 forward 收益窗口（非"只回测 10 日数据"）；全历史 signals 回测。
// 凯利公式 f* = max(0, (b·p − (1−p)) / b)，b=盈亏比 pl，p=胜率 win_rate → 数学最优下注比例。
//   买/辅买：f>0 标"凯利建议仓位 X%"；f≤0 标"凯利不建议入场（负期望）"。
//   卖：f>0 标"凯利建议做空 X%"；f≤0 标"凯利不建议做空（负期望，长期会亏）"。
//   样本 n<10 标"样本不足，仅供参考"，不计凯利。
// 卖点语义诚实声明：D1 卖点是"止盈减仓提示"非高胜率反向信号，胜率≈50% 接近随机（见 REQUIREMENTS §7.2）。
// 胜率配色梯度（winRateClass）：≥80 深绿加粗 / 70-79 中绿加粗 / 60-69 浅绿 / 50-59 中性灰 /
//   40-49 浅橙 / 30-39 橙加粗 / <30 红加粗。绿=可信、橙红=不可信，色盲友好（亮度+加粗区分）。
function winRateClass(wr) {
  if (wr >= 80) return "wr-excellent";
  if (wr >= 70) return "wr-good";
  if (wr >= 60) return "wr-fair";
  if (wr >= 50) return "wr-neutral";
  if (wr >= 40) return "wr-weak";
  if (wr >= 30) return "wr-poor";
  return "wr-bad";
}

// YYYYMMDD → "MM-DD" 格式，若是今天则显示"今日"
function fmtDate(dateStr) {
  if (!dateStr || dateStr.length < 8) return dateStr || "";
  const m = dateStr.substring(4, 6), d = dateStr.substring(6, 8);
  const today = new Date();
  const isToday = today.getFullYear() === parseInt(dateStr.substring(0, 4)) &&
                  today.getMonth() + 1 === parseInt(m) &&
                  today.getDate() === parseInt(d);
  return isToday ? "今日" : `${m}-${d}`;
}

// 每个品类的买卖点策略公式标注。后端注入 idx.strategy 字段（{buy,buy_aux,sell}），
// 由 app/compute/signals.py::strategy_desc 读 indicators.yaml 的 buy_aux_filter +
// SKIP_IDS/s.* 前缀逻辑生成。无 strategy 字段时用基线兜底（兼容旧数据/未注入端点）。
// 基线：C1 RSI上穿30 + B1 BB下轨回归 + D1 20日高回落5%+MA60+MACD死叉。
function strategyDesc(strategy) {
  if (strategy) return strategy;
  return {
    buy: "RSI(14)上穿30",
    buy_aux: "BB下轨回归",
    sell: "20日高回落5%+MA60多头+MACD死叉",
  };
}

function statsHint(stats, strategy, indexId) {
  const strat = strategyDesc(strategy);
  const stratHtml = strat ? `<div class="hint-strategy">📋 策略｜买: ${strat.buy} · 辅买: ${strat.buy_aux} · 卖: ${strat.sell}</div>` : "";
  if (!stats) return stratHtml || null;
  const blocks = [];
  const labels = { buy: "买点", buy_aux: "辅买", sell: "卖点" };
  const sigClass = { buy: "buy", buy_aux: "buy-aux", sell: "sell" };
  for (const sig of ["buy", "buy_aux", "sell"]) {
    const s = stats[sig];
    if (!s || !s["10d"]) continue;
    const d = s["10d"];
    const n = d.n || 0;
    const label = labels[sig];
    const cls = sigClass[sig];
    if (n < 10) {
      blocks.push(`<div class="hint-row"><span class="hint-sig ${cls}">${label}</span><span class="hint-warn">样本不足（仅 ${n} 例），仅供参考，不计凯利</span></div>`);
      continue;
    }
    const wr = Math.round((d.win_rate || 0) * 100);
    const pl = d.pl != null ? d.pl.toFixed(2) : "-";
    const wrCls = winRateClass(wr);
    // 凯利仓位：f* = max(0, (b·p − (1−p)) / b)，b=盈亏比，p=胜率。
    const p = d.win_rate || 0;
    const b = d.pl;
    let kellyHtml = "";
    if (b != null && b > 0) {
      const f = Math.max(0, (b * p - (1 - p)) / b);
      const kellyPct = Math.round(f * 100);
      if (sig === "sell") {
        kellyHtml = kellyPct > 0
          ? `<span class="hint-kelly">→ 凯利建议做空 <b>${kellyPct}%</b></span>`
          : `<span class="hint-kelly warn">→ 凯利不建议做空（负期望，长期会亏）</span>`;
      } else {
        kellyHtml = kellyPct > 0
          ? `<span class="hint-kelly">→ 凯利建议仓位 <b>${kellyPct}%</b></span>`
          : `<span class="hint-kelly warn">→ 凯利不建议入场（负期望）</span>`;
      }
    }
    // 卖点诚实声明：止盈减仓提示，非高胜率反向信号（详见凯利说明 + 规则说明条）
    const honestTag = sig === "sell"
      ? `<span class="hint-note">止盈减仓提示，非高胜率反向信号</span>`
      : "";
    // 卖点胜率语义是"走弱概率"（卖后 10 日下跌概率），与买点"胜率"语义对称但口径不同
    const wrLabel = sig === "sell" ? "走弱概率" : "胜率";
    blocks.push(`<div class="hint-row"><span class="hint-sig ${cls}">${label}</span><span class="hint-stat">${wrLabel} <b class="wr ${wrCls}">${wr}%</b></span><span class="hint-stat">盈亏比 ${pl}</span><span class="hint-stat">样本 ${n}</span>${kellyHtml}${honestTag}</div>`);
  }
  if (!blocks.length) return stratHtml || null;
  // 频率统计区块
  let freqHtml = "";
  const freqBlocks = [];
  for (const sig of ["buy", "buy_aux", "sell"]) {
    const s = stats[sig];
    if (!s || !s.frequency) continue;
    const f = s.frequency;
    const label = labels[sig];
    const cls = sigClass[sig];
    const monthsStr = f.months ? Object.entries(f.months).map(([m, c]) => `${m.substring(4,6)}月${c}次`).join(" ") : "";
    freqBlocks.push(`<div class="hint-row"><span class="hint-sig ${cls}">${label}</span><span class="hint-stat">今年 <b>${f.year_count}</b> 次</span><span class="hint-stat">总计 <b>${f.total_count}</b> 次</span><span class="hint-stat">月均 <b>${f.monthly_avg}</b> 次</span>${monthsStr ? `<span class="hint-stat muted">${monthsStr}</span>` : ""}</div>`);
  }
  if (freqBlocks.length) {
    freqHtml = `<div class="hint-header">📅 信号频率</div><div class="hint-blocks">${freqBlocks.join("")}</div>`;
  }
  return stratHtml + `<div class="hint-header">回测口径：全历史信号 · 信号触发后 10 个交易日收益统计${SIM_INDICES.has(indexId) ? ` <a href="./trade_sim_${SIM_HREF_MAP[indexId] || indexId}.html" target="_blank" class="sim-btn" title="查看模拟回测详情">📊 模拟回测</a>` : ''}</div>` +
    `<div class="hint-blocks">${blocks.join("")}</div>` +
    freqHtml +
    `<details class="hint-kelly-explain"><summary>凯利公式是什么？这个数怎么看？</summary>` +
    `<div class="hint-kelly-body">` +
    `<div><b>公式</b>：f* = max(0, (盈亏比 × 胜率 − (1 − 胜率)) ÷ 盈亏比) —— 根据该信号的胜率与盈亏比，算出每次下注的最优资金比例。</div>` +
    `<div><b>"凯利 X%"是什么</b>：理论上每次用总资金的 X% 买入（或做空）在数学上最优——长期复合增长最快、破产风险最低的下注比例。</div>` +
    `<div><b>"凯利不建议做空/入场"</b>：公式算出 ≤0，说明这个信号<b>长期期望为负</b>（亏得多赢得少），按公式不应下注。卖点凯利为 0 通常因胜率接近 50% 且盈亏比&lt;1。</div>` +
    `<div><b>卖点语义</b>：D1 卖点是<b>止盈减仓提示</b>，不是高胜率反向交易指令——卖点后 10 日走弱概率≈50% 接近随机，不可作为独立卖出依据（详见规则说明条）。</div>` +
    `<div><b>重要提醒</b>：凯利公式假设胜率/盈亏比稳定已知，但回测统计本身有波动且含幸存者偏差；<b>请把凯利 X% 当参考上限，实战建议大幅打折</b>（如 1/2 凯利甚至 1/4 凯利）。</div>` +
    `</div></details>` +
    `<div class="hint-disclaimer">⚠ 以上为历史回测统计与数学公式参考仓位，非投资建议；过往表现不代表未来收益。</div>`;
}

// 指数图 + 买卖点标注
function indexChart(title, ohlc, signals, stats, strategy, container = content, chartArr = charts, indexId) {
  const hint = statsHint(stats, strategy, indexId);
  const c = mkCard(title, 360, hint, container, chartArr);
  const close = ohlc.map((d) => [d.date, d.close]);
  const markData = signals.map((s) => {
    const o = ohlc.find((x) => x.date === s.date);
    return {
      coord: [s.date, o ? o.close : null],
      value: signalLabel(s),
      itemStyle: { color: signalColor(s) },
    };
  });
  c.setOption({
    tooltip: { trigger: "axis" },
    grid: { left: 55, right: 20, top: 30, bottom: 50 },
    xAxis: { type: "category", data: ohlc.map((d) => d.date) },
    yAxis: { type: "value", scale: true },
    dataZoom: [{ type: "inside" }, { type: "slider", height: 18, bottom: 8 }],
    series: [
      {
        name: title,
        type: "line",
        smooth: true,
        symbol: "none",
        data: close,
        lineStyle: { width: 1.5 },
        markPoint: {
          symbol: "pin",
          symbolSize: 34,
          label: { fontSize: 11, color: "#fff" },
          data: markData,
        },
      },
    ],
  });
  return c;
}

// 单序列 value 折线 + 买卖点 markPoint（B 扩展：指标/情绪分用，数据是 [{date,value}]）
// 与 indexChart 区别：数据结构是 value 单序列（无 close/high），量级差异大（gold 100-1249 /
// cn10y 1.5-4 / usdcnh 680-722），用通用折线 + markPoint。opts 透传 visualMap 等（cross_market 用）。
function valueChartWithSignals(title, data, signals, opts, stats, strategy, indexId) {
  const sigs = signals || [];
  const hint = statsHint(stats, strategy, indexId);
  const c = mkCard(title, 360, hint);
  const markData = sigs.map((s) => {
    const p = data.find((x) => x.date === s.date);
    return {
      coord: [s.date, p ? p.value : null],
      value: signalLabel(s),
      itemStyle: { color: signalColor(s) },
    };
  });
  c.setOption({
    tooltip: { trigger: "axis" },
    grid: { left: 55, right: 20, top: 30, bottom: 50 },
    xAxis: { type: "category", data: data.map((d) => d.date) },
    yAxis: { type: "value", scale: true },
    dataZoom: [{ type: "inside" }, { type: "slider", height: 18, bottom: 8 }],
    series: [{
      name: title,
      type: "line",
      smooth: true,
      symbol: "none",
      connectNulls: true,
      data: data.map((d) => [d.date, d.value]),
      lineStyle: { width: 1.5 },
      markPoint: {
        symbol: "pin",
        symbolSize: 34,
        label: { fontSize: 11, color: "#fff" },
        data: markData,
      },
    }],
    ...opts,
  });
  return c;
}

// 静态版：读本地 JSON 文件（替代 fetch API）
async function fetchJSON(url) {
  return fetch(url).then((r) => r.json());
}

// ============ BUG-E：交互增强（指数/行业筛选 + 热力图切换）============
// 纯前端筛选，不影响后端数据。指数筛选条放指数折线区前（紧挨被筛选内容），筛选时局部刷新：
// 只重渲染指数区（filter bar + 指数折线），不调 renderTab、不 refetch（signals 缓存在闭包内）。
// sectionCharts 同步 push 全局 charts（供 window resize），dispose 时从 charts 移除，避免悬空引用。
// fetcher(id, idx) 返回 { signals, stats }；动态版按 range 走 API，静态版读 all.json 前端过滤。
function renderIndicesSection(container, indices, fetcher) {
  const entries = Object.entries(indices || {});
  if (!entries.length) return Promise.resolve();

  const signalsCache = {}; // 闭包级缓存：tab/range 切换时整个 renderAStock/renderHK 重建，缓存自然失效
  const sectionCharts = [];

  function disposeSectionCharts() {
    sectionCharts.forEach((c) => {
      if (!c) return;
      c.dispose();
      const i = charts.indexOf(c);
      if (i >= 0) charts.splice(i, 1);
    });
    sectionCharts.length = 0;
  }

  async function doRender() {
    disposeSectionCharts();
    container.innerHTML = "";
    // 当前 tab 不含已选 id 时回退"全部"（防跨 tab 状态残留导致空渲染）
    const filterId = state.indexFilter !== "all" && entries.some(([id]) => id === state.indexFilter) ? state.indexFilter : "all";
    const bar = document.createElement("div");
    bar.className = "filter-bar";
    bar.innerHTML = `<label>指数筛选：</label>`;
    const sel = document.createElement("select");
    sel.innerHTML = `<option value="all"${filterId === "all" ? " selected" : ""}>全部指数（${entries.length}）</option>` +
      entries.map(([id, idx]) => `<option value="${id}"${filterId === id ? " selected" : ""}>${idx.name}</option>`).join("");
    sel.onchange = async () => {
      state.indexFilter = sel.value;
      await doRender(); // 局部刷新：只重渲染指数区，不调 renderTab、不 refetch
    };
    bar.appendChild(sel);
    container.appendChild(bar);
    for (const [id, idx] of entries) {
      if (filterId !== "all" && id !== filterId) continue; // 未选指数跳过渲染
      if (!signalsCache[id]) signalsCache[id] = await fetcher(id, idx);
      const sig = signalsCache[id];
      if (idx.data && idx.data.length) {
        // chart 入全局 charts（供 resize）+ sectionCharts（供本区 dispose）
        const c = indexChart(idx.name, idx.data, sig.signals, sig.stats, idx.strategy, container, charts, id);
        sectionCharts.push(c);
      }
    }
  }

  return doRender();
}

// 行业搜索条：行业 tab 用，输入关键词实时过滤行业网格（按 name 或 id 模糊匹配）。
function industrySearchBar(containerOverride) {
  const bar = document.createElement("div");
  bar.className = "filter-bar";
  bar.innerHTML = `<label>行业/概念筛选：</label>`;
  const input = document.createElement("input");
  input.type = "search";
  input.placeholder = "搜索行业/概念名称或代码（如：银行、机器人、thsc_）";
  input.value = state.industrySearch;
  let timer;
  input.oninput = () => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      state.industrySearch = input.value.trim();
      renderTab();
    }, 250); // 防抖，避免每键触发 renderTab
  };
  bar.appendChild(input);
  (containerOverride || content).appendChild(bar);
}

function filterIndicesByName(indices, query) {
  if (!query) return indices;
  const q = query.toLowerCase();
  const out = {};
  for (const [id, idx] of Object.entries(indices || {})) {
    const name = (idx.name || "").toLowerCase();
    if (name.includes(q) || id.toLowerCase().includes(q)) out[id] = idx;
  }
  return out;
}

// 静态版：index 详情读 all 全历史 JSON，前端按 ohlc 日期范围过滤 signals。
// ohlc 已由 tab 端点按 range 过滤，取其首尾日期作为 signals 过滤窗口。
function filterSignalsByRange(signals, ohlc) {
  if (!ohlc || !ohlc.length) return [];
  const minDate = ohlc[0].date;
  const maxDate = ohlc[ohlc.length - 1].date;
  return (signals || []).filter((s) => s.date >= minDate && s.date <= maxDate);
}

// 买卖点规则说明条（小字可折叠）。文案与 app/compute/signals.py + REQUIREMENTS.md §7 一致。
// 每个 tab 调用一次；行业 tab（F1）建好后直接调 ruleBar() 即可复用。
// 买卖点规则说明 HTML 内容（供浮动按钮 modal 使用）。复用原 ruleBar 的详细规则。
function ruleContentHtml() {
  return `<div class="rule-detail">

    <div class="rule-section">
      <h4><span class="rule-dot rule-dot-buy"></span>买点信号</h4>

      <div class="rule-card rule-card-buy">
        <div class="rule-card-head"><span class="rule-badge badge-buy">主买</span> 超卖反弹（RSI 指标）</div>
        <p>当市场<b>短期跌过头了</b>，开始反弹时，提示买入机会。</p>
        <table class="rule-table">
          <tr><td class="rule-td-label">含义</td><td>RSI 指标跌到 30 以下（超卖区），然后回升到 30 以上 —— 说明抛压衰竭、买方开始进场</td></tr>
          <tr><td class="rule-td-label">触发</td><td>前一日 RSI ≤ 30，当日回升到 30 以上</td></tr>
          <tr><td class="rule-td-label">颜色</td><td><span class="rule-badge badge-buy">红色</span> 图表上标记为「买」</td></tr>
          <tr><td class="rule-td-label">胜率</td><td>近 3 年 10 日内盈亏比 <b>1.13</b></td></tr>
          <tr><td class="rule-td-label">特殊</td><td><b>科创50、电力设备、传媒</b> 这 3 个品种波动更大，阈值收紧到 25（RSI ≤ 25 才算超卖），更早捕捉反弹</td></tr>
        </table>
      </div>

      <div class="rule-card rule-card-aux">
        <div class="rule-card-head"><span class="rule-badge badge-aux">辅买</span> 超卖反弹（布林带下轨）</div>
        <p>价格<b>跌破布林带下轨后弹回来</b>，也是超卖反弹信号，与主买互补。</p>
        <table class="rule-table">
          <tr><td class="rule-td-label">含义</td><td>布林带下轨 = 近 20 日均价 - 2 倍标准差，跌破后收回 = 极端超卖后的反弹</td></tr>
          <tr><td class="rule-td-label">触发</td><td>前一日收盘价跌破布林下轨，当日回升到下轨之上</td></tr>
          <tr><td class="rule-td-label">颜色</td><td><span class="rule-badge badge-aux">粉紫</span> 图表上标记为「辅买」</td></tr>
          <tr><td class="rule-td-label">胜率</td><td>近 3 年 10 日内盈亏比 <b>1.18</b></td></tr>
          <tr><td class="rule-td-label">去重</td><td>如果同一天主买和辅买同时触发，只保留主买（不重复标记）</td></tr>
        </table>
      </div>
    </div>

    <div class="rule-section">
      <h4><span class="rule-dot rule-dot-sell"></span>卖点信号</h4>

      <div class="rule-card rule-card-sell">
        <div class="rule-card-head"><span class="rule-badge badge-sell">卖点</span> 趋势转弱 · 止盈减仓提示</div>
        <p>价格从<b>近期高点回落</b>，且动量转弱时，提示减仓或止盈。三个条件<b>同时满足</b>才触发：</p>
        <table class="rule-table">
          <tr><td class="rule-td-label">① 价格回落</td><td>从近 20 个交易日的<b>最高价</b>回落超过 <b>5%</b>（用最高价而非收盘价，更能捕捉盘中真实高点）</td></tr>
          <tr><td class="rule-td-label">② 趋势过滤</td><td>收盘价仍在 <b>60 日均线</b> 之上（只在多头趋势中提示卖出，下跌趋势中不制造噪音）</td></tr>
          <tr><td class="rule-td-label">③ 动量确认</td><td><b>MACD 死叉</b> —— 短期动量线（DIF）下穿长期动量线（DEA），确认上涨动能减弱</td></tr>
        </table>
        <p class="rule-note">⚠️ <b>重要</b>：这是止盈减仓提示，<b>不是做空信号</b>。在单边上涨市中可能出现假信号（趋势跟踪类指标的固有代价）。震荡/下跌市中止盈提示更有效。近 3 年 10 日胜率 <b>55%</b>。</p>
      </div>
    </div>

    <div class="rule-section">
      <h4><span class="rule-dot rule-dot-read"></span>如何解读信号</h4>

      <p class="rule-subtitle">盈亏标注（卖点颜色含义）</p>
      <table class="rule-table rule-table-color">
        <tr>
          <td style="width:33%"><span class="rule-dot-sm rule-dot-profit"></span> <b>绿色 = 止盈</b></td>
          <td style="width:33%"><span class="rule-dot-sm rule-dot-loss"></span> <b>灰色 = 买点失败</b></td>
          <td><span class="rule-dot-sm rule-dot-noref"></span> <b>橙色 = 无前买点</b></td>
        </tr>
        <tr>
          <td>卖点价格 &gt; 前一个买点价格<br><span class="muted">→ 获利了结或减仓</span></td>
          <td>卖点价格 &lt; 前一个买点价格<br><span class="muted">→ 已持仓建议止损，未持仓建议观望</span></td>
          <td>附近窗口内没有买点参考<br><span class="muted">→ 单独看趋势判断，不属止盈也不属止损</span></td>
        </tr>
      </table>

      <p class="rule-subtitle">情绪背景标签</p>
      <p class="muted">卖点信号会附带当前市场情绪分，帮你判断「技术拐点 + 情绪背景」的强弱：</p>
      <table class="rule-table rule-table-tags">
        <tr>
          <td><span class="rule-tag tag-freeze">冰点</span> ≤ 20</td>
          <td><span class="rule-tag tag-cool">偏冷</span> 21–40</td>
          <td><span class="rule-tag tag-neutral">中性</span> 41–60</td>
          <td><span class="rule-tag tag-warm">偏热</span> 61–80</td>
          <td><span class="rule-tag tag-hot">过热</span> &gt; 80</td>
        </tr>
      </table>

      <p class="rule-subtitle">买点信号示例</p>
      <div class="rule-example"><span class="muted">主买：</span>RSI上穿30(29→34), 情绪=8[冰点]</div>
      <div class="rule-example"><span class="muted">辅买：</span>布林下轨回归(下轨3852,收盘3870), RSI=41, 情绪=47[偏冷]</div>

      <p class="rule-subtitle">卖点信号示例</p>
      <div class="rule-example"><span class="muted">卖点：</span>20日高回落5%(高4259→阈4046,收盘4028), RSI=40, 情绪=53[中性], MA60=4000[趋势过滤], MACD=死叉确认, 较前买+2.30%[止盈]</div>
    </div>

    <div class="rule-section rule-section-sm">
      <h4><span class="rule-dot rule-dot-stat"></span>当前信号统计</h4>
      <table class="rule-table rule-table-stat">
        <tr><td class="rule-td-label">主买</td><td><b>3,673</b> 个</td><td class="rule-td-label">辅买</td><td><b>3,918</b> 个</td></tr>
        <tr><td class="rule-td-label">卖点</td><td><b>3,185</b> 个</td><td class="rule-td-label">卖买比</td><td><b>0.42</b>（买卖平衡）</td></tr>
      </table>
    </div>

    <p class="rule-disclaimer">以上信号为技术分析参考，不构成交易指令。投资有风险，决策需谨慎。</p>

  </div>`;
}

// 右下角浮动"策略说明"按钮 + modal。点击弹出规则详情，替代原来每个 Tab 顶部的 ruleBar。
function initRuleButton() {
  // 创建浮动按钮
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'rule-float-btn';
  btn.innerHTML = '&#128203;';
  btn.setAttribute('aria-label', '策略说明');
  btn.title = '策略说明';
  document.body.appendChild(btn);

  // 创建 modal
  const modal = document.createElement('div');
  modal.className = 'rule-modal hidden';
  modal.innerHTML = '<div class="rule-modal-overlay"></div><div class="rule-modal-body"><div class="rule-modal-header"><h3>&#128203; 买卖点策略说明</h3><button class="rule-modal-close" aria-label="关闭">&times;</button></div><div class="rule-modal-content">' + ruleContentHtml() + '</div></div>';
  document.body.appendChild(modal);

  const overlay = modal.querySelector('.rule-modal-overlay');
  const closeBtn = modal.querySelector('.rule-modal-close');

  const open = () => { modal.classList.remove('hidden'); document.body.style.overflow = 'hidden'; };
  const close = () => { modal.classList.add('hidden'); document.body.style.overflow = ''; };

  btn.addEventListener('click', open);
  overlay.addEventListener('click', close);
  closeBtn.addEventListener('click', close);
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !modal.classList.contains('hidden')) close(); });

  // 跟随回到顶部按钮的显示/隐藏
  const onScroll = () => {
    if (window.scrollY > 300) { btn.classList.add('visible'); }
    else { btn.classList.remove('visible'); }
  };
  window.addEventListener('scroll', onScroll, { passive: true });
  onScroll();
}



async function renderTab() {
  clearCharts();
  content.innerHTML = '<div class="loading">加载中…</div>';
  try {
    if (state.tab === "overview") await renderOverview();
    else if (state.tab === "market") await renderMarket();
    else if (state.tab === "sentiment") await renderSentiment();
    else if (state.tab === "industry") await renderIndustry();
  } catch (e) {
    content.innerHTML = `<div class="loading">出错了：${e}</div>`;
  }
}

async function renderOverview() {
  const r = await fetchJSON("./data/overview.json");
  content.innerHTML = "";

  // ---- 0. 一句话总结横幅 ----
  fetchJSON("./data/summary.json").then((s) => {
    if (s && s.summary) {
      const banner = document.createElement("div");
      banner.className = "summary-banner";
      const freezeBadge = s.is_freeze ? `<span class="summary-freeze">❄️ 冰点</span>` : "";
      const fgBadge = s.fear_greed_label ? `<span class="summary-fg-tag">😐 ${s.fear_greed_label} ${s.fear_greed_value?.toFixed(0) || ""}</span>` : "";
      banner.innerHTML = `<div class="summary-top"><span class="summary-icon">&#x1F4CA;</span><span class="summary-text">${s.summary}</span></div><div class="summary-meta">${s.sentiment_label || ""}${fgBadge}${freezeBadge}<span class="summary-date">${fmtDate(s.date)}数据 · ${s.generated_at || ""}</span></div>`;
      content.insertBefore(banner, content.firstChild);
    }
  }).catch(() => {});

  const sectionTitle = (text) => {
    const h = document.createElement("div");
    h.className = "section-title";
    h.textContent = text;
    content.appendChild(h);
  };

  // KPI 指标值格式化
  const fmtMetric = (m) => {
    if (m.value == null) return "-";
    const v = m.value;
    switch (m.id) {
      case "a_width_zhaban_rate": return (v * 100).toFixed(1) + "%"; // 存储为 0-1 小数
      case "a_width_zt_count":
      case "a_width_dt_count": return v.toFixed(0);
      case "a_amount":
      case "a_fund_margin": return v.toFixed(0);
      case "a_fund_north": return (v >= 0 ? "+" : "") + v.toFixed(1);
      case "a_volume_ratio": return v.toFixed(2) + "x";
      default: return v.toFixed(2);
    }
  };

  // ---- 1. 首屏两列：左=恐贪指数+情绪分，右=冰点日+买卖点 ----
  // 用户优先级：独家数据（恐贪/情绪/冰点日/买卖点/位置感）> 基础数据（KPI/sparkline）
  const ov2ColA = document.createElement("div");
  ov2ColA.className = "ov-2col";
  const colA1 = document.createElement("div");
  const colA2 = document.createElement("div");
  ov2ColA.appendChild(colA1);
  ov2ColA.appendChild(colA2);
  content.appendChild(ov2ColA);

  // 左列：恐贪指数折线（近 6 月，visualMap 分段着色）
  if (r.fear_greed_6m && r.fear_greed_6m.length) {
    lineChart("😐 恐贪指数（近 6 月）", r.fear_greed_6m.map((d) => ({ date: d.date, value: d.value })), {
      visualMap: {
        show: false,
        pieces: [
          { lte: 25, color: "#c62828" },
          { gt: 25, lte: 40, color: "#e6a23c" },
          { gt: 40, lte: 60, color: "#86909c" },
          { gt: 60, lte: 75, color: "#67c23a" },
          { gt: 75, color: "#2e8b57" },
        ],
        dimension: 1,
      },
    }, null, colA1);
  }

  // 左列：A股综合情绪分折线（近 6 月）
  if (r.a_sentiment_6m && r.a_sentiment_6m.length) {
    lineChart("A股综合情绪分（近 6 月）", r.a_sentiment_6m.map((d) => ({ date: d.date, value: d.value })), {}, null, colA1);
  }

  // 右列：冰点日卡片
  const freezeHtml = (r.recent_freeze && r.recent_freeze.length)
    ? `<h3>近期冰点日</h3><ul class="sig-list">${r.recent_freeze
        .map((s) => `<li>${s.date} <span class="muted">${indexIdToName(s.score_id)}=${s.value != null ? s.value.toFixed(1) : "-"}</span></li>`)
        .join("")}</ul>`
    : `<h3>近期冰点日</h3><div class="empty-note">无近期冰点日</div>`;
  const freezeCard = document.createElement("div");
  freezeCard.className = "chart-card";
  freezeCard.innerHTML = freezeHtml;
  colA2.appendChild(freezeCard);

  // 右列：今日买卖点
  const sigHtml = (r.signals_today && r.signals_today.length)
    ? `<h3>${fmtDate(r.date)}买卖点</h3><ul class="sig-list">${r.signals_today
        .map((s) => `<li><b class="${s.signal}">${signalLabel(s)}</b> ${indexIdToName(s.index_id)} <span class="muted">${s.reason || ""}</span></li>`)
        .join("")}</ul>`
    : `<h3>${fmtDate(r.date)}买卖点</h3><div class="empty-note">${fmtDate(r.date)}无买卖点信号</div>`;
  const sigCard = document.createElement("div");
  sigCard.className = "chart-card";
  sigCard.innerHTML = sigHtml;
  colA2.appendChild(sigCard);

  // ---- 2. 信号强度两列：左=市场宽度+跨市场，右=均线排列+位置感 ----
  const ov2ColB = document.createElement("div");
  ov2ColB.className = "ov-2col";
  const colB1 = document.createElement("div");
  const colB2 = document.createElement("div");
  ov2ColB.appendChild(colB1);
  ov2ColB.appendChild(colB2);
  content.appendChild(ov2ColB);

  // 左列：市场宽度图（上涨/下跌家数堆叠面积，近 1 月）
  const w = r.width_1m || { up: [], down: [] };
  const wDates = [...new Set([...w.up.map((d) => d.date), ...w.down.map((d) => d.date)])].sort();
  if (wDates.length) {
    const wc = mkCard("市场宽度（涨跌家数，近 1 月）", 260, null, colB1);
    wc.setOption({
      tooltip: { trigger: "axis" },
      legend: { top: 0, data: ["上涨家数", "下跌家数"] },
      grid: { left: 55, right: 20, top: 35, bottom: 35 },
      xAxis: { type: "category", data: wDates },
      yAxis: { type: "value" },
      series: [
        { name: "上涨家数", type: "line", stack: "width", symbol: "none", areaStyle: {}, color: "#e6492e",
          data: wDates.map((d) => { const p = w.up.find((x) => x.date === d); return p ? p.value : null; }) },
        { name: "下跌家数", type: "line", stack: "width", symbol: "none", areaStyle: {}, color: "#2e8b57",
          data: wDates.map((d) => { const p = w.down.find((x) => x.date === d); return p ? p.value : null; }) },
      ],
    });
  }

  // 左列：跨市场综合评分折线（近 6 月）
  if (r.cross_market_6m && r.cross_market_6m.length) {
    lineChart("跨市场综合评分（近 6 月）", r.cross_market_6m.map((d) => ({ date: d.date, value: d.value })), {
      visualMap: {
        show: false,
        pieces: [{ lte: 20, color: "#e6492e" }, { gt: 20, lte: 80, color: "#5b8ff9" }, { gt: 80, color: "#2e8b57" }],
        dimension: 1,
      },
    }, null, colB1);
  }

  // 右列：均线排列卡片
  fetchJSON("./data/ma_alignment.json").then((maData) => {
    const d = (maData.data || []).slice(-1)[0];
    if (d) {
      const maCard = document.createElement("div");
      maCard.className = "chart-card ma-card";
      let maHtml = `<h3>&#x1F4C8; 均线排列</h3>`;
      const bullish = d.bullish || 0;
      const bearish = d.bearish || 0;
      const cross = d.cross || 0;
      maHtml += `<div class="ma-summary">`;
      maHtml += `<span class="ma-count bullish">${bullish} 个多头</span> `;
      maHtml += `<span class="ma-count bearish">${bearish} 个空头</span> `;
      maHtml += `<span class="ma-count cross">${cross} 个震荡</span>`;
      maHtml += `</div>`;
      if (d.details && d.details.length) {
        maHtml += `<table class="ma-table"><thead><tr><th>指数</th><th>MA5</th><th>MA10</th><th>MA20</th><th>MA60</th><th>状态</th></tr></thead><tbody>`;
        for (const det of d.details) {
          const alignLabel = { bullish: "多头", bearish: "空头", cross: "震荡" }[det.alignment] || det.alignment;
          const alignCls = det.alignment;
          maHtml += `<tr><td>${det.name}</td><td>${det.ma5}</td><td>${det.ma10}</td><td>${det.ma20}</td><td>${det.ma60}</td><td class="${alignCls}">${alignLabel}</td></tr>`;
        }
        maHtml += `</tbody></table>`;
      }
      maCard.innerHTML = maHtml;
      colB2.appendChild(maCard);
    }
    // 位置感卡片（从首屏右列移过来，与均线排列配对）
    fetchJSON("./data/position.json").then((posData) => {
      if (posData && posData.positions && posData.positions.length) {
        const posCard = document.createElement("div");
        posCard.className = "chart-card position-card";
        let posHtml = `<h3>&#x1F4CD; 大盘位置感</h3><div class="position-list">`;
        for (const p of posData.positions) {
          const pct = p.percentile_1y != null ? p.percentile_1y : 50;
          const barColor = pct <= 40 ? "#2e8b57" : pct <= 60 ? "#86909c" : pct <= 80 ? "#e6a23c" : "#e6492e";
          posHtml += `<div class="position-row">
            <span class="pos-name">${p.name}</span>
            <span class="pos-price">${p.current.toLocaleString()}</span>
            <div class="pos-bar-bg"><div class="pos-bar-fill" style="width:${pct}%;background:${barColor}"></div></div>
            <span class="pos-pct">${pct.toFixed(0)}%</span>
            <span class="pos-label" style="color:${barColor}">${p.label}</span>
          </div>`;
        }
        posHtml += `</div>`;
        posCard.innerHTML = posHtml;
        colB2.appendChild(posCard);
      }
    }).catch(() => {});
  }).catch(function() {});

  // ---- 3. 基础数据区：KPI 卡片行 ----
  sectionTitle("基础数据");
  const scoreNames = { a_sentiment: "A股综合情绪分", cross_market: "跨市场综合评分", fear_greed: "恐贪指数" };
  const kpiCards = [];
  for (const [id, s] of Object.entries(r.today.scores || {})) {
    kpiCards.push({
      id: id,
      title: scoreNames[id] || id,
      value: s.value != null ? s.value.toFixed(1) : "-",
      valueNum: s.value,
      sub: "0-100",
      date: s.date || r.date,
      tag: s.is_freeze ? "冰点" : s.is_overheat ? "过热" : "",
    });
  }
  for (const m of r.today.metrics || []) {
    kpiCards.push({
      id: m.id,
      title: m.name,
      value: fmtMetric(m),
      valueNum: m.value,
      sub: m.unit || "",
      date: m.date,
      tag: m.id === "a_fund_north" ? "停更" : "",
      signal: m.signal || "",
      amount: m.amount,
    });
  }
  const kpiOrder = {
    a_width_zt_count: 1, a_width_dt_count: 2, a_width_zhaban_rate: 3,
    a_amount: 4, a_volume_ratio: 5, a_sentiment: 6, cross_market: 7, fear_greed: 8, a_fund_margin: 9, a_fund_north: 10,
  };
  kpiCards.sort((a, b) => (kpiOrder[a.id] || 99) - (kpiOrder[b.id] || 99));
  const cards = document.createElement("div");
  cards.className = "cards kpi-row";
  for (const k of kpiCards) {
    const tagCls = k.tag === "冰点" ? "freeze" : k.tag === "过热" ? "overheat" : "stale";
    const tagHtml = k.tag ? ` <span class="tag ${tagCls}">${k.tag}</span>` : "";
    const sentTag = k.id === "a_sentiment" || k.id === "cross_market" ? ` <span class="sentiment-label">${sentimentTag(k.valueNum)}</span>` : "";
    const fgTag = k.id === "fear_greed" ? ` <span class="sentiment-label" style="color:${fearGreedColor(k.valueNum)}">${fearGreedLabel(k.valueNum)}</span>` : "";
    let sub = k.sub ? `${k.sub} · ${k.date}` : (k.date || "");
    let valueHtml = k.value;
    if (k.id === "a_volume_ratio") {
      const sig = k.signal || "";
      const isFangliang = sig.startsWith("放量");
      const isSuoliang = sig.startsWith("缩量");
      let sigCls = "";
      if (isFangliang) sigCls = "fangliang";
      else if (isSuoliang) sigCls = "suoliang";
      const sigHtml = sig ? ` <span class="tag ${sigCls}">${sig}</span>` : "";
      valueHtml = k.value + sigHtml;
      sub = sig + " · " + (k.date || "");
    }
    cards.innerHTML += `<div class="card kpi"><div class="card-title">${k.title}${tagHtml}</div><div class="card-value">${valueHtml}${sentTag}${fgTag}</div><div class="card-sub">${sub}</div></div>`;
  }
  content.appendChild(cards);

  // ---- 4. 主要指数 sparkline 网格 ----
  const grid = document.createElement("div");
  grid.className = "spark-grid";
  content.appendChild(grid);
  for (const [, idx] of Object.entries(r.indices_sparkline || {})) {
    if (!idx.closes || !idx.closes.length) continue;
    const up = (idx.pct_change || 0) >= 0;
    const color = up ? "#e6492e" : "#2e8b57";
    const cell = document.createElement("div");
    cell.className = "spark-cell";
    const sign = up ? "+" : "";
    cell.innerHTML = `
      <div class="spark-head">
        <span class="spark-name">${idx.name}</span>
        <span class="pct-badge" style="color:${color}">${sign}${(idx.pct_change || 0).toFixed(2)}%</span>
      </div>
      <div class="spark-chart"></div>
      <div class="spark-date">${idx.last_date || ""}</div>`;
    grid.appendChild(cell);
    const chartDom = cell.querySelector(".spark-chart");
    const exist = echarts.getInstanceByDom(chartDom);
    if (exist) exist.dispose();
    const sc = echarts.init(chartDom);
    sc.setOption({
      grid: { left: 2, right: 2, top: 4, bottom: 4 },
      xAxis: { type: "category", show: false, data: idx.dates },
      yAxis: { type: "value", show: false, scale: true },
      tooltip: { trigger: "axis", formatter: (p) => `${p[0].axisValue}<br/>${(p[0].value == null || isNaN(Number(p[0].value))) ? "-" : Number(p[0].value).toFixed(2)}` },
      series: [{
        type: "line", smooth: true, symbol: "none", data: idx.closes,
        lineStyle: { color, width: 1.5 }, areaStyle: { color, opacity: 0.12 },
      }],
    });
    charts.push(sc);
  }

  // ---- 5. AD Line 腾落线 + 成交量对比（全宽，横跨两列）----
  const ov2ColC = document.createElement("div");
  ov2ColC.className = "ov-2col";
  const colC1 = document.createElement("div");
  const colC2 = document.createElement("div");
  ov2ColC.appendChild(colC1);
  ov2ColC.appendChild(colC2);
  content.appendChild(ov2ColC);

  // 左：AD Line 腾落线
  try {
    const adRes = await fetchJSON("./data/ad_line.json");
    const adData = (adRes.data || []).slice(-120);
    if (adData.length) {
      const adDates = adData.map(d => d.date);
      const ratioData = adData.map(d => d.ratio);
      const adLineData = adData.map(d => d.ad_line);
      const adMA20 = adData.map(d => d.ad_line_ma20);
      const ratioColors = adData.map(d => (d.up_count >= d.down_count) ? "#e6492e" : "#2e8b57");

      const adc = mkCard("📊 腾落线（AD Line）", 300, null, colC1);
      adc.setOption({
        tooltip: { trigger: "axis" },
        legend: { top: 0, data: ["涨跌家数比", "AD Line", "AD Line MA20"] },
        grid: { left: 55, right: 55, top: 35, bottom: 35 },
        xAxis: { type: "category", data: adDates },
        yAxis: [
          { type: "value", name: "涨跌比", axisLabel: { formatter: v => v.toFixed(2) }, splitLine: { show: false } },
          { type: "value", name: "AD Line" },
        ],
        dataZoom: [{ type: "inside" }, { type: "slider", height: 18, bottom: 8 }],
        series: [
          { name: "涨跌家数比", type: "bar", yAxisIndex: 0, data: ratioData.map((v, i) => ({ value: v, itemStyle: { color: ratioColors[i] } })), barWidth: "60%" },
          { name: "AD Line", type: "line", yAxisIndex: 1, symbol: "none", smooth: true, data: adLineData, lineStyle: { color: "#5b8ff9", width: 1.5 } },
          { name: "AD Line MA20", type: "line", yAxisIndex: 1, symbol: "none", smooth: true, data: adMA20, lineStyle: { color: "#f6bd16", width: 1.5, type: "dashed" } },
        ],
      });
    }
  } catch (e) { /* 无声降级 */ }

  // 右：成交量对比
  try {
    const vrRes = await fetchJSON("./data/volume_ratio.json");
    const vrData = (vrRes.data || []).slice(-120);
    if (vrData.length) {
      const vrDates = vrData.map(d => d.date);
      const vrAmount = vrData.map(d => d.amount);
      const vrMA5 = vrData.map(d => d.ma5);
      const vrMA20 = vrData.map(d => d.ma20);
      const vrColors = vrData.map(d => (d.pct_change >= 0) ? "#e6492e" : "#2e8b57");

      const vrc = mkCard("📈 成交额与量比（近 120 日）", 300, null, colC2);
      vrc.setOption({
        tooltip: { trigger: "axis", formatter: function(params) {
          const d = vrData[params[0].dataIndex];
          return `<b>${d.date}</b><br/>成交额: ${(d.amount || 0).toFixed(0)} 亿<br/>MA5: ${(d.ma5 || 0).toFixed(0)} 亿<br/>MA20: ${(d.ma20 || 0).toFixed(0)} 亿<br/>量比: ${(d.ratio || 0).toFixed(2)}x<br/>信号: ${d.signal || "正常"}`;
        }},
        legend: { top: 0, data: ["成交额", "MA5", "MA20"] },
        grid: { left: 55, right: 20, top: 35, bottom: 35 },
        xAxis: { type: "category", data: vrDates },
        yAxis: { type: "value", name: "亿元", axisLabel: { formatter: v => (v / 10000).toFixed(1) + "万" } },
        dataZoom: [{ type: "inside" }, { type: "slider", height: 18, bottom: 8 }],
        series: [
          { name: "成交额", type: "bar", data: vrAmount.map((v, i) => ({ value: v, itemStyle: { color: vrColors[i] } })), barWidth: "60%" },
          { name: "MA5", type: "line", symbol: "none", smooth: true, data: vrMA5, lineStyle: { color: "#f6bd16", width: 1.5 } },
          { name: "MA20", type: "line", symbol: "none", smooth: true, data: vrMA20, lineStyle: { color: "#5b8ff9", width: 1.5, type: "dashed" } },
        ],
      });
    }
  } catch (e) { /* 无声降级 */ }

  // ---- 6. 申万行业涨跌幅热力图 ----
  if (r.industry_heatmap && r.industry_heatmap.length) {
    renderIndustryHeatmap(r.industry_heatmap, "申万一级行业涨跌幅热力图（近 1 日 / 近 5 日）");
  } else {
    const ph = document.createElement("div");
    ph.className = "chart-card placeholder";
    ph.innerHTML = `<h3>申万行业涨跌幅热力图</h3><div class="placeholder-body">暂无行业数据</div>`;
    content.appendChild(ph);
  }
}

// 大盘Tab：二级Tab切换（A股/港股/全球），渲染 subtab 栏 + 对应子内容
async function renderMarket() {
  content.innerHTML = "";
  // 二级 tab 栏
  const subtabBar = document.createElement("div");
  subtabBar.className = "subtab-bar";
  const subtabs = [
    ["a-stock", "A股"],
    ["hk", "港股"],
    ["global", "全球"],
  ];
  subtabs.forEach(([key, label]) => {
    const btn = document.createElement("button");
    btn.textContent = label;
    btn.dataset.subtab = key;
    if (state.subtab === key) btn.classList.add("active");
    btn.onclick = () => {
      state.subtab = key;
      renderMarket(); // 重新渲染大盘 tab
    };
    subtabBar.appendChild(btn);
  });
  content.appendChild(subtabBar);

  // 子内容容器
  const subContent = document.createElement("div");
  subContent.className = "market-sub-content";
  content.appendChild(subContent);

  // 根据 subtab 渲染对应内容
  if (state.subtab === "a-stock") await renderAStock(subContent);
  else if (state.subtab === "hk") await renderHK(subContent);
  else if (state.subtab === "global") await renderGlobal(subContent);
}

async function renderAStock(container = content) {
  const r = await fetchJSON(`./data/a-stock-${state.range}.json`);
  container.innerHTML = "";
  const groups = {
    "市场宽度（涨跌家数）": ["a_width_up_count", "a_width_down_count"],
    "涨停/跌停/连板": ["a_width_zt_count", "a_width_dt_count", "a_width_max_lianban"],
    "炸板率/封板率/打板溢价": ["a_width_zhaban_rate", "a_width_fengban_rate", "a_width_daban_premium"],
    "资金面": ["a_fund_north", "a_fund_margin", "a_fund_main", "a_amount"],
    "情绪指数（QVIX/换手率）": ["a_qvix_300", "a_qvix_1000", "a_turnover_rate"],
    "换手率分布分位数（%，BaoStock 全市场）": ["a_turnover_mean", "a_turnover_median", "a_turnover_p90", "a_turnover_p10"],
    "换手率>5%家数占比（0-1，活跃度分化）": ["a_turnover_gt5_pct"],
    "股息率": ["a_div_yield"],
    "龙虎榜": ["lhb_count", "lhb_inst_net"],
    "解禁/IPO/可转债": ["unlock_amount", "ipo_count", "cov_count", "cov_premium_median"],
  };
  const groupHints = {
    "资金面": "注：北向资金数据源自 2024 年 8 月起停更（东财停止实时披露），该序列冻结在 2024-08-16，1 年期窗口内为空属正常。",
  };
  const entries = Object.entries(groups);
  const mainEntries = entries.slice(0, 8);
  const extraEntries = entries.slice(8);
  // 前8张卡片：4行2列网格
  const grid2col = document.createElement("div");
  grid2col.className = "ov-2col";
  container.appendChild(grid2col);
  for (const [g, ids] of mainEntries) {
    const series = ids.map((id) => r.metrics[id]).filter(Boolean).map((m) => ({ name: m.name, data: m.data }));
    if (series.length && series.some((s) => s.data.length)) lineChart(g, series, {}, groupHints[g] || null, grid2col);
  }
  // 龙虎榜 + 解禁/IPO/可转债：默认隐藏，点击「更多」展开
  const extraWrap = document.createElement("div");
  extraWrap.style.marginBottom = "16px";
  container.appendChild(extraWrap);
  const moreBtn = document.createElement("button");
  moreBtn.textContent = "更多 ▼";
  moreBtn.className = "more-toggle";
  moreBtn.style.cssText = "display:block;width:100%;padding:8px;border:1px dashed #d9d9d9;border-radius:6px;background:#fafafa;color:#86909c;cursor:pointer;font-size:13px;";
  extraWrap.appendChild(moreBtn);
  const extraGrid = document.createElement("div");
  extraGrid.className = "ov-2col";
  extraGrid.style.display = "none";
  extraWrap.appendChild(extraGrid);
  moreBtn.onclick = () => {
    if (extraGrid.style.display === "none") {
      extraGrid.style.display = "grid";
      moreBtn.textContent = "收起 ▲";
      if (!extraGrid.dataset.rendered) {
        for (const [g, ids] of extraEntries) {
          const series = ids.map((id) => r.metrics[id]).filter(Boolean).map((m) => ({ name: m.name, data: m.data }));
          if (series.length && series.some((s) => s.data.length)) lineChart(g, series, {}, groupHints[g] || null, extraGrid);
        }
        extraGrid.dataset.rendered = "1";
      }
    } else {
      extraGrid.style.display = "none";
      moreBtn.textContent = "更多 ▼";
    }
  };
  // 指数折线区：筛选条移到本区前（紧挨指数折线），筛选时局部刷新（不 refetch、不动上方 KPI/宽度/资金面）
  const indicesSection = document.createElement("div");
  indicesSection.className = "indices-section";
  container.appendChild(indicesSection);
  // 静态版 fetcher：读 index/{id}-all.json 全历史，前端按 ohlc 日期范围过滤 signals
  await renderIndicesSection(indicesSection, r.indices, async (id, idx) => {
    const raw = await fetchJSON(`./data/index/${id}-all.json`);
    return { signals: filterSignalsByRange(raw.signals, idx.data), stats: raw.stats };
  });
}

async function renderHK(container = content) {
  const r = await fetchJSON(`./data/hk-${state.range}.json`);
  container.innerHTML = "";
  if (r.hk_south && r.hk_south.length) lineChart("港股通净买入（亿元）", r.hk_south.map((d) => ({ date: d.date, value: d.value })), {}, null, container);
  // 指数折线区：筛选条移到本区前，筛选时局部刷新
  const indicesSection = document.createElement("div");
  indicesSection.className = "indices-section";
  container.appendChild(indicesSection);
  await renderIndicesSection(indicesSection, r.indices, async (id, idx) => {
    const raw = await fetchJSON(`./data/index/${id}-all.json`);
    return { signals: filterSignalsByRange(raw.signals, idx.data), stats: raw.stats };
  });
}

async function renderGlobal(container = content) {
  const r = await fetchJSON(`./data/global-${state.range}.json`);
  container.innerHTML = "";
  for (const [id, idx] of Object.entries(r.indices)) {
    const sig = await fetchJSON(`./data/index/${id}-all.json`);
    const sigs = filterSignalsByRange(sig.signals, idx.data);
    if (idx.data.length) indexChart(idx.name, idx.data, sigs, sig.stats, idx.strategy, container, charts, id);
  }
  const extras = {
    gold: "黄金（元/克）",
    oil: "原油（元/桶）",
    wti_oil: "WTI原油（美元/桶）",
    comex_silver: "COMEX白银（美元/盎司）",
    usdcnh: "离岸人民币",
    a_qvix_300: "QVIX(300ETF)",
    a_qvix_1000: "QVIX(1000ETF)",
    cn10y: "中国10年国债收益率（%）",
    us10y: "美国10年国债收益率（%）",
    cn_us_spread: "中美利差(10Y)（%）",
  };
  const extrasSignals = r.extras_signals || {};
  const extrasStats = r.extras_stats || {};
  const extrasStrategy = r.extras_strategy || {};
  for (const [id, name] of Object.entries(extras)) {
    const data = r.extras[id] || [];
    if (data.length) valueChartWithSignals(name, data, extrasSignals[id] || [], {}, extrasStats[id], extrasStrategy[id], id);
  }
}

async function renderSentiment() {
  const r = await fetchJSON(`./data/sentiment-${state.range}.json`);
  content.innerHTML = "";
  const sig = r.signals || {};
  const stats = r.stats || {};
  const strat = r.strategy || {};

  // 恐贪指数（综合情绪指标，放最前面）
  if (r.fear_greed && r.fear_greed.length) {
    const data = r.fear_greed.map((d) => ({ date: d.date, value: d.value }));
    const latest = data[data.length - 1] && data[data.length - 1].value;
    const title = `😱😐😤 恐贪指数（0-100）${latest != null ? " · " + fearGreedLabel(latest) : ""}`;
    valueChartWithSignals(title, data, [], {
      visualMap: {
        show: false,
        pieces: [
          { lte: 25, color: "#c62828" },
          { gt: 25, lte: 40, color: "#e6a23c" },
          { gt: 40, lte: 60, color: "#86909c" },
          { gt: 60, lte: 75, color: "#67c23a" },
          { gt: 75, color: "#2e8b57" },
        ],
        dimension: 1,
      },
    });
  }

  if (r.a_sentiment.length) {
    const data = r.a_sentiment.map((d) => ({ date: d.date, value: d.value }));
    const latest = data[data.length - 1] && data[data.length - 1].value;
    const title = `A股综合情绪分（0-100）${latest != null ? " · " + sentimentTag(latest) : ""}`;
    valueChartWithSignals(title, data, sig.a_sentiment || [], {}, stats.a_sentiment, strat.a_sentiment);
  }
  const idxNames = {
    sentiment_sz50: '上证50情绪分',
    sentiment_hs300: '沪深300情绪分',
    sentiment_csi500: '中证500情绪分',
    sentiment_csi1000: '中证1000情绪分',
    sentiment_cyb: '创业板情绪分',
    sentiment_kc50: '科创50情绪分',
  };
  for (const [key, baseTitle] of Object.entries(idxNames)) {
    if (r[key] && r[key].length) {
      const data = r[key].map(d => ({date: d.date, value: d.value}));
      const latest = data[data.length - 1] && data[data.length - 1].value;
      const title = `${baseTitle}（0-100）${latest != null ? " · " + sentimentTag(latest) : ""}`;
      valueChartWithSignals(title, data,
        sig[key] || [], {
          visualMap: {
            show: false,
            pieces: [{ lte: 20, color: "#e6492e" }, { gt: 20, lte: 80, color: "#5b8ff9" }, { gt: 80, color: "#2e8b57" }],
            dimension: 1,
          },
        }, stats[key], strat[key]);
    }
  }
  // 冰点/过热热力图
  renderSentimentHeatmap(r);
  if (r.cross_market.length) {
    const data = r.cross_market.map((d) => ({ date: d.date, value: d.value }));
    const latest = data[data.length - 1] && data[data.length - 1].value;
    const title = `跨市场综合评分（0-100）${latest != null ? " · " + sentimentTag(latest) : ""}`;
    valueChartWithSignals(title, data, sig.cross_market || [], {
      visualMap: {
        show: false,
        pieces: [{ lte: 20, color: "#e6492e" }, { gt: 20, lte: 80, color: "#5b8ff9" }, { gt: 80, color: "#2e8b57" }],
        dimension: 1,
      },
    }, stats.cross_market, strat.cross_market);
  }
  // 期货机构持仓
  const futures = await fetchJSON("./data/futures.json");
  if (futures && futures.positions && futures.positions.length) renderFuturesSection(futures);
}

// 情绪冰点/过热热力图：X 轴=日期，Y 轴=指数名，色块=红(冰点≤20)/绿(过热>80)/灰(中性)
function renderSentimentHeatmap(r) {
  const idxNames = [
    { key: 'sentiment_sz50', label: '上证50' },
    { key: 'sentiment_hs300', label: '沪深300' },
    { key: 'sentiment_csi500', label: '中证500' },
    { key: 'sentiment_csi1000', label: '中证1000' },
    { key: 'sentiment_cyb', label: '创业板' },
    { key: 'sentiment_kc50', label: '科创50' },
  ];
  // 收集所有日期（取各指数日期并集）
  const allDates = new Set();
  const idxData = {};
  for (const { key, label } of idxNames) {
    const series = r[key] || [];
    idxData[key] = series;
    series.forEach((d) => allDates.add(d.date));
  }
  if (!allDates.size) return;
  const dates = [...allDates].sort();
  const dateIdx = {};
  dates.forEach((d, i) => { dateIdx[d] = i; });

  // 构建 heatmap 数据：[dateIndex, yIndex, value]
  const data = [];
  idxNames.forEach(({ key }, yi) => {
    (idxData[key] || []).forEach((d) => {
      const xi = dateIdx[d.date];
      if (xi != null) data.push([xi, yi, d.value]);
    });
  });
  if (!data.length) return;

  const div = document.createElement("div");
  div.className = "chart-card";
  div.innerHTML = `<h3>🔥 指数情绪冰点/过热热力图</h3><div class="chart" style="height:220px"></div>`;
  content.appendChild(div);
  const c = echarts.init(div.querySelector(".chart"));
  charts.push(c);

  // 日期标签：只显示约 10 个刻度以免太密
  const labelInterval = Math.max(1, Math.floor(dates.length / 10));
  c.setOption({
    tooltip: {
      trigger: "item",
      formatter: (p) => {
        const d = dates[p.value[0]];
        const lbl = idxNames[p.value[1]].label;
        const v = p.value[2];
        const tag = v <= 20 ? "冰点" : v > 80 ? "过热" : "中性";
        return `${d}<br/>${lbl}: ${v != null ? v.toFixed(1) : "-"} (${tag})`;
      },
    },
    grid: { left: 80, right: 20, top: 20, bottom: 50 },
    xAxis: {
      type: "category", data: dates,
      axisLabel: { rotate: 45, fontSize: 10, interval: labelInterval },
      splitArea: { show: false },
    },
    yAxis: {
      type: "category",
      data: idxNames.map((x) => x.label),
      axisLabel: { fontSize: 12 },
    },
    visualMap: {
      min: 0, max: 100,
      pieces: [
        { lte: 20, color: "#e6492e", label: "冰点(≤20)" },
        { gt: 20, lte: 80, color: "#d9d9d9", label: "中性(20-80)" },
        { gt: 80, color: "#2e8b57", label: "过热(>80)" },
      ],
      orient: "horizontal", left: "center", bottom: 4,
    },
    series: [{
      type: "heatmap", data: data,
      label: { show: false },
      emphasis: { itemStyle: { borderColor: "#1f2329", borderWidth: 1 } },
    }],
  });
}

// 期货机构持仓：净持仓比例折线图 + 方向准确率表格
function renderFuturesSection(data) {
  if (!data || !data.positions || !data.positions.length) return;

  const roles = ["机构(前20)", "中信期货", "国泰君安"];
  const products = ["沪深300期货", "中证500期货", "上证50期货", "中证1000期货", "综合"];

  
  // 1. 昨日净多空概览卡片
  if (data.summary && data.summary.roles) {
    const div = document.createElement("div");
    div.className = "chart-card";
    const dateStr = data.summary.date || "";
    let html = `<h3>昨日净多空（手） ${dateStr}</h3>`;
    html += '<div class="futures-note">正数=净多（绿），负数=净空（红）。数据来源：中金所前20会员持仓。</div>';
    html += '<table class="futures-summary-table"><thead><tr><th>品种</th>';
    for (const role of roles) html += `<th>${role}</th>`;
    html += '</tr></thead><tbody>';
    for (const prod of products) {
      html += `<tr><td class="sym-name">${prod}</td>`;
      for (const role of roles) {
        const v = (data.summary.roles[role] || {})[prod];
        const cls = v > 0 ? "futures-long" : v < 0 ? "futures-short" : "";
        const sign = v > 0 ? "+" : "";
        html += `<td class="${cls}">${v != null ? sign + v.toLocaleString() : "-"}</td>`;
      }
      html += '</tr>';
    }
    html += '</tbody></table>';
    div.innerHTML = html;
    content.appendChild(div);
  }

  // 2. 历史准确率表格（移到综合图前面）
  if (data.accuracy) {
    const div = document.createElement("div");
    div.className = "chart-card";
    const windows = ["30d", "60d", "120d"];
    let html = '<h3>历史同向/逆向准确率（次工作日涨跌）</h3>';
    html += '<div class="futures-note">同向=跟随机构方向做多/做空；逆向=反向操作。滚动窗口统计，不构成未来预测。数据来源：中金所前20会员持仓。</div>';
    html += '<table class="accuracy-table"><thead><tr><th>滚动窗口</th>';
    for (const role of roles) html += `<th>${role}</th>`;
    html += '</tr></thead><tbody>';
    for (const win of windows) {
      html += `<tr><td class="sym-name">${win}</td>`;
      for (const role of roles) {
        const acc = (data.accuracy[role] || {})[win];
        if (acc) {
          const f = acc.follow != null ? Math.round(acc.follow * 100) : null;
          const c = acc.contrarian != null ? Math.round(acc.contrarian * 100) : null;
          const fCls = f != null && f > 55 ? "acc-good" : "";
          const cCls = c != null && c > 55 ? "acc-warn" : "";
          html += `<td><span class="${fCls}">同${f != null ? f + "%" : "-"}</span> <span class="${cCls}">逆${c != null ? c + "%" : "-"}</span></td>`;
        } else {
          html += '<td>-</td>';
        }
      }
      html += '</tr>';
    }
    html += '</tbody></table>';
    html += '<div class="futures-note" style="margin-top:10px;">机构=中金所前20会员汇总。中信/国君为单独席位。历史准确率基于次工作日涨跌方向统计，不构成未来预测。</div>';
    div.innerHTML = html;
    content.appendChild(div);
  }

  // 3. 四张折线图：net_position 手数趋势（默认折叠，点击展开）
  const chartsCollapse = document.createElement("div");
  chartsCollapse.className = "futures-collapse";
  const chartsToggle = document.createElement("button");
  chartsToggle.className = "futures-collapse-toggle";
  chartsToggle.textContent = "📈 展开净多空趋势图";
  chartsToggle.onclick = () => {
    const body = chartsCollapse.querySelector(".futures-collapse-body");
    const hidden = body.classList.toggle("hidden");
    chartsToggle.textContent = hidden ? "📈 展开净多空趋势图" : "📈 收起净多空趋势图";
  };
  content.appendChild(chartsToggle);
  const chartsBody = document.createElement("div");
  chartsBody.className = "futures-collapse-body hidden";
  chartsCollapse.appendChild(chartsBody);
  content.appendChild(chartsCollapse);
  // 后续 mkCard 改用 chartsBody 作为容器
  const _origMkCard = mkCard;
  mkCard = function(title, height, hint) {
    return _origMkCard(title, height, hint, chartsBody);
  };

// 图1：综合净多空手数 — 3 条线（机构/中信/国君的综合品种）
  const chart1Series = roles.map((role) => ({
    name: role,
    data: data.positions.map((d) => {
      const r = d[role];
      return r ? { date: d.date, value: r["综合"] } : { date: d.date, value: null };
    }).filter((d) => d.value != null),
  }));
  if (chart1Series.some((s) => s.data.length)) {
    const dates1 = [...new Set(chart1Series.flatMap((s) => s.data.map((d) => d.date)))].sort();
    const c1 = mkCard("综合净多空手数", 300);
    c1.setOption({
      tooltip: {
        trigger: "axis",
        formatter: function (params) {
          if (!params || !params.length) return "";
          let html = '<strong>' + params[0].axisValue + '</strong><br/>';
          const accEntry = data.accuracy_history ? data.accuracy_history.find((a) => a.date === params[0].axisValue) : null;
          params.forEach((p) => {
            const v = p.data;
            const handStr = v != null ? (v > 0 ? "+" : "") + (v / 10000).toFixed(1) + "万手" : "-";
            const dirStr = v > 0 ? "净多" : v < 0 ? "净空" : "";
            html += p.marker + ' ' + p.seriesName + ': ' + handStr + ' ' + dirStr + '<br/>';
            if (accEntry) {
              const roleAcc = accEntry[p.seriesName];
              if (roleAcc) {
                html += '<span style="color:#86909c;font-size:11px;margin-left:16px;">';
                const parts = [];
                for (const w of ["30d", "60d", "120d"]) {
                  const a = roleAcc[w];
                  if (a) {
                    const f = Math.round(a.follow * 100);
                    const c = Math.round(a.contrarian * 100);
                    const fStyle = f > c ? 'color:#16a34a;font-weight:bold' : 'color:#86909c';
                    const cStyle = c > f ? 'color:#16a34a;font-weight:bold' : 'color:#86909c';
                    parts.push(w + ' <span style="' + fStyle + '">同' + f + '%</span> <span style="' + cStyle + '">逆' + c + '%</span>');
                  }
                }
                html += parts.join(' | ') + '</span><br/>';
              }
            }
          });
          return html;
        },
      },
      legend: { top: 0, type: "scroll" },
      grid: { left: 55, right: 20, top: 35, bottom: 35 },
      xAxis: { type: "category", data: dates1 },
      yAxis: { type: "value", scale: true, axisLabel: { formatter: (v) => (v / 10000).toFixed(1) + "万手" } },
      dataZoom: [{ type: "inside" }, { type: "slider", height: 18, bottom: 8 }],
      series: chart1Series.map((s) => ({
        name: s.name, type: "line", smooth: true, symbol: "none", connectNulls: true,
        data: dates1.map((d) => { const p = s.data.find((x) => x.date === d); return p ? p.value : null; }),
        markLine: { silent: true, symbol: "none", lineStyle: { color: "#86909c", type: "dashed", width: 1 }, label: { formatter: "0", fontSize: 10 }, data: [{ yAxis: 0 }] },
      })),
    });
  }

  // 图2-4：每个角色各品种手数
  for (const role of roles) {
    const prodSeries = products.map((prod) => ({
      name: prod,
      data: data.positions.map((d) => {
        const r = d[role];
        return r ? { date: d.date, value: r[prod] } : { date: d.date, value: null };
      }).filter((d) => d.value != null),
    }));
    if (prodSeries.some((s) => s.data.length)) {
      const datesP = [...new Set(prodSeries.flatMap((s) => s.data.map((d) => d.date)))].sort();
      const cP = mkCard(`${role} 各品种净多空手数`, 300);
      cP.setOption({
        tooltip: {
          trigger: "axis",
          formatter: function (params) {
            if (!params || !params.length) return "";
            let html = '<strong>' + params[0].axisValue + '</strong><br/>';
            params.forEach((p) => {
              const v = p.data;
              const handStr = v != null ? (v > 0 ? "+" : "") + (v / 10000).toFixed(1) + "万手" : "-";
              const dirStr = v > 0 ? "净多" : v < 0 ? "净空" : "";
              html += p.marker + ' ' + p.seriesName + ': ' + handStr + ' ' + dirStr + '<br/>';
            });
            return html;
          },
        },
        legend: { top: 0, type: "scroll" },
        grid: { left: 55, right: 20, top: 35, bottom: 35 },
        xAxis: { type: "category", data: datesP },
        yAxis: { type: "value", scale: true, axisLabel: { formatter: (v) => (v / 10000).toFixed(1) + "万手" } },
        dataZoom: [{ type: "inside" }, { type: "slider", height: 18, bottom: 8 }],
        series: prodSeries.map((s) => ({
          name: s.name, type: "line", smooth: true, symbol: "none", connectNulls: true,
          data: datesP.map((d) => { const p = s.data.find((x) => x.date === d); return p ? p.value : null; }),
          markLine: { silent: true, symbol: "none", lineStyle: { color: "#86909c", type: "dashed", width: 1 }, label: { formatter: "0", fontSize: 10 }, data: [{ yAxis: 0 }] },
        })),
      });
    }
  }

  mkCard = _origMkCard;

  // 4. 说明文字
  {
    const div = document.createElement("div");
    div.className = "chart-card";
    div.innerHTML = '<div class="futures-note">机构=中金所前20会员汇总。中信/国君为单独席位。折线图为净多空手数（正=净多，负=净空），hover 可查看比例。历史准确率基于次工作日涨跌方向统计，不构成未来预测。</div>';
    content.appendChild(div);
  }
}

// ============ 行业看板（F1）============
// 申万一级 31 个行业：折线网格（mini 折线 + E1 买卖点 markPoint）+ 涨跌幅热力图（近 1 日/近 5 日）。
// industry.json 一次性返回 indices（ohlc+signals）+ heatmap（pct_1d/pct_5d）。
// BUG-E：热力图加近1日/近5日/全部切换按钮（嵌在卡片标题右侧），数据已有 pct_1d/pct_5d 只加 UI 切换。
function renderIndustryHeatmap(heatmap, title, containerOverride) {
  if (!heatmap || !heatmap.length) return null;
  const rangeMode = state.heatmapRange || "all";
  // 按近 1 日涨跌幅排序（红涨在前，绿跌在后），便于看强弱分布
  const sortBy = rangeMode === "5d" ? "pct_5d" : "pct_1d";
  const sorted = [...heatmap].sort((a, b) => (b[sortBy] ?? -999) - (a[sortBy] ?? -999));
  const names = sorted.map((h) => h.name.replace(/^SW\s/, ""));
  // BUG-E：按 rangeMode 决定 y 轴维度（近1日/近5日/全部两行）
  const yCats = rangeMode === "1d" ? ["近 1 日"] : rangeMode === "5d" ? ["近 5 日"] : ["近 1 日", "近 5 日"];
  const yIdxs = rangeMode === "1d" ? [0] : rangeMode === "5d" ? [1] : [0, 1];
  const data = [];
  sorted.forEach((h, i) => {
    for (let yi = 0; yi < yIdxs.length; yi++) {
      const v = yIdxs[yi] === 0 ? h.pct_1d : h.pct_5d;
      data.push([i, yi, v == null ? null : Number(v.toFixed(2))]);
    }
  });
  // BUG-E：自建卡片（含切换按钮在标题右侧），不复用 mkCard（其标题不支持嵌入控件）
  const ctn = containerOverride || content;
  const div = document.createElement("div");
  div.className = "chart-card";
  const toggleBtns = [["1d", "近1日"], ["5d", "近5日"], ["all", "全部"]]
    .map(([k, label]) => `<button type="button" data-hr="${k}" class="${rangeMode === k ? "active" : ""}">${label}</button>`).join("");
  div.innerHTML = `<h3 class="with-toggle"><span>${title || "申万一级行业涨跌幅热力图"}</span><span class="heatmap-toggle">${toggleBtns}</span></h3><div class="chart" style="height:280px"></div>`;
  ctn.appendChild(div);
  const c = echarts.init(div.querySelector(".chart"));
  charts.push(c);
  // 切换按钮：点击改 state.heatmapRange 后重渲染整个 tab（保持其他筛选状态）
  div.querySelectorAll(".heatmap-toggle button").forEach((b) => {
    b.onclick = () => {
      state.heatmapRange = b.dataset.hr;
      renderTab();
    };
  });
  c.setOption({
    tooltip: {
      trigger: "item",
      formatter: (p) => `${names[p.value[0]]}<br/>${yCats[p.value[1]]}：${p.value[2] == null ? "-" : p.value[2] + "%"}`,
    },
    grid: { left: 56, right: 16, top: 24, bottom: 90 },
    xAxis: { type: "category", data: names, axisLabel: { rotate: 50, fontSize: 10, interval: 0 }, splitArea: { show: false } },
    yAxis: { type: "category", data: yCats, axisLabel: { fontSize: 11 } },
    visualMap: {
      min: -5, max: 5, calculable: true, orient: "horizontal", left: "center", bottom: 4,
      inRange: { color: ["#2e8b57", "#a8d8b9", "#f2f3f5", "#f5b6a8", "#e6492e"] }, // 绿→灰→红（A 股惯例红涨绿跌）
      text: ["+5%", "-5%"],
    },
    series: [{
      type: "heatmap", data: data,
      label: { show: true, fontSize: 9, formatter: (p) => (p.value[2] == null ? "-" : p.value[2].toFixed(1)) },
      emphasis: { itemStyle: { borderColor: "#1f2329", borderWidth: 1 } },
    }],
  });
  return c;
}

function renderIndustryGrid(indices, containerOverride) {
  const entries = Object.entries(indices).filter(([, idx]) => idx.data && idx.data.length);
  const ctn = containerOverride || content;
  if (!entries.length) {
    const note = document.createElement("div");
    note.className = "empty-note";
    note.textContent = "暂无行业指数数据";
    ctn.appendChild(note);
    return;
  }
  const grid = document.createElement("div");
  grid.className = "spark-grid industry-grid";
  ctn.appendChild(grid);
  for (const [id, idx] of entries) {
    const ohlc = idx.data;
    const signals = idx.signals || [];
    const last = ohlc[ohlc.length - 1];
    const pct = last.pct_change;
    const up = (pct || 0) >= 0;
    const color = up ? "#e6492e" : "#2e8b57";
    const cell = document.createElement("div");
    cell.className = "spark-cell industry-cell";
    const sign = up ? "+" : "";
    const hint = statsHint(idx.stats, idx.strategy, id);
    cell.innerHTML = `
      <div class="spark-head">
        <span class="spark-name">${idx.name}</span>
        <span class="pct-badge" style="color:${color}">${pct == null ? "-" : sign + pct.toFixed(2) + "%"}</span>
      </div>
      ${hint ? `<div class="chart-hint">${hint}</div>` : ""}
      <div class="spark-chart"></div>
      <div class="ind-metrics"></div>`;
    grid.appendChild(cell);
    const chartDom = cell.querySelector(".spark-chart");
    const exist = echarts.getInstanceByDom(chartDom);
    if (exist) exist.dispose();
    const sc = echarts.init(chartDom);
    const markData = signals.map((s) => {
      const o = ohlc.find((x) => x.date === s.date);
      return {
        coord: [s.date, o ? o.close : null],
        value: signalLabel(s),
        itemStyle: { color: signalColor(s) },
      };
    });
    sc.setOption({
      grid: { left: 2, right: 2, top: 6, bottom: 18 },
      xAxis: { type: "category", show: true, data: ohlc.map((d) => d.date), axisLabel: { fontSize: 8, color: "#86909c", interval: Math.max(1, Math.floor(ohlc.length / 5)), formatter: (v) => v.slice(0, 4) + "-" + v.slice(4, 6) }, axisTick: { show: false }, axisLine: { show: false }, splitLine: { show: false } },
      yAxis: { type: "value", show: false, scale: true },
      tooltip: { trigger: "axis", formatter: (p) => {
        const d = ohlc[p[0].dataIndex];
        if (!d || d.close == null) return `${p[0].axisValue}<br/>-`;
        const lines = [p[0].axisValue, `收盘 ${d.close.toFixed(2)}`];
        if (d.pct_change != null) lines.push(`涨跌 ${d.pct_change >= 0 ? "+" : ""}${d.pct_change.toFixed(2)}%`);
        if (d.open != null && d.high != null && d.low != null) lines.push(`开 ${d.open.toFixed(2)} 高 ${d.high.toFixed(2)} 低 ${d.low.toFixed(2)}`);
        return lines.join("<br/>");
      } },
      series: [{
        type: "line", smooth: true, symbol: "none",
        data: ohlc.map((d) => [d.date, d.close]),
        lineStyle: { color, width: 1.5 }, areaStyle: { color, opacity: 0.12 },
        markPoint: { symbol: "pin", symbolSize: 26, label: { fontSize: 9, color: "#fff" }, data: markData },
      }],
    });
    charts.push(sc);

    // F2：行业资金流 / 成交额 / 换手率 mini sparklines
    const metricsBox = cell.querySelector(".ind-metrics");
    const fundFlow = idx.fund_flow || [];
    const turnover = idx.turnover || [];
    // 成交额从 index_daily.amount 取
    const amountData = ohlc.filter((d) => d.amount != null).map((d) => ({ date: d.date, value: d.amount }));

    const miniSpecs = [
      { label: "资金流", data: fundFlow, color: "#5b8ff9", fmt: (v) => v.toFixed(1) + "亿" },
      { label: "成交额", data: amountData, color: "#9b6dff", fmt: (v) => v.toFixed(0) + "亿" },
      { label: "换手率", data: turnover, color: "#36cfc9", fmt: (v) => v.toFixed(2) + "%" },
    ];
    let hasAnyMetric = false;
    for (const spec of miniSpecs) {
      const hasData = spec.data && spec.data.length;
      if (!hasData) continue;
      hasAnyMetric = true;
      const lastVal = spec.data[spec.data.length - 1].value;
      const row = document.createElement("div");
      row.className = "ind-metric-row";
      row.innerHTML = `
        <span class="ind-metric-label">${spec.label}</span>
        <div class="ind-metric-chart"></div>
        <span class="ind-metric-val">${lastVal == null ? "-" : spec.fmt(lastVal)}</span>`;
      metricsBox.appendChild(row);
      const mc = echarts.init(row.querySelector(".ind-metric-chart"));
      mc.setOption({
        grid: { left: 1, right: 1, top: 1, bottom: 1 },
        xAxis: { type: "category", show: false, data: spec.data.map((d) => d.date) },
        yAxis: { type: "value", show: false, scale: true },
        tooltip: { trigger: "axis", formatter: (p) => {
          const d = spec.data[p[0].dataIndex];
          if (!d || d.value == null) return `${p[0].axisValue}<br/>${spec.label}: -`;
          return `${p[0].axisValue}<br/>${spec.label}: ${spec.fmt(d.value)}`;
        } },
        series: [{
          type: "line", smooth: true, symbol: "none",
          data: spec.data.map((d) => [d.date, d.value]),
          lineStyle: { color: spec.color, width: 1.2 },
          areaStyle: { color: spec.color, opacity: 0.1 },
        }],
      });
      charts.push(mc);
    }
    if (!hasAnyMetric) {
      const emptyNote = document.createElement("div");
      emptyNote.className = "ind-metric-empty";
      emptyNote.textContent = "暂无资金流/换手率数据";
      metricsBox.appendChild(emptyNote);
    }

    // F3：行业内宽度 mini chart（涨跌家数堆叠：红涨/绿跌）
    const widthData = idx.width || [];
    if (widthData.length) {
      const lastW = widthData[widthData.length - 1];
      const row = document.createElement("div");
      row.className = "ind-metric-row";
      row.innerHTML = `
        <span class="ind-metric-label">宽度</span>
        <div class="ind-metric-chart"></div>
        <span class="ind-metric-val">涨${lastW.up_count == null ? "-" : lastW.up_count} 跌${lastW.down_count == null ? "-" : lastW.down_count}</span>`;
      metricsBox.appendChild(row);
      const wc = echarts.init(row.querySelector(".ind-metric-chart"));
      wc.setOption({
        grid: { left: 1, right: 1, top: 1, bottom: 1 },
        xAxis: { type: "category", show: false, data: widthData.map((d) => d.date) },
        yAxis: { type: "value", show: false },
        tooltip: { trigger: "axis", formatter: (p) => {
          const d = widthData[p[0].dataIndex];
          if (!d) return `${p[0].axisValue}<br/>-`;
          return `${p[0].axisValue}<br/>涨${d.up_count} 跌${d.down_count} | 涨停${d.zt_count} 跌停${d.dt_count} 炸板${d.zb_count}`;
        } },
        series: [
          { name: "上涨", type: "line", stack: "wd", symbol: "none", smooth: true,
            data: widthData.map((d) => [d.date, d.up_count || 0]),
            lineStyle: { color: "#e6492e", width: 0.8 }, areaStyle: { color: "#e6492e", opacity: 0.35 } },
          { name: "下跌", type: "line", stack: "wd", symbol: "none", smooth: true,
            data: widthData.map((d) => [d.date, -(d.down_count || 0)]),
            lineStyle: { color: "#2e8b57", width: 0.8 }, areaStyle: { color: "#2e8b57", opacity: 0.35 } },
        ],
      });
      charts.push(wc);
    }
  }
}

// ============ 板块轮动速度卡片 ============
async function renderRotationCard(container) {
  try {
    const r = await fetchJSON("./data/rotation.json");
    if (!r || !r.latest) return;

    const latest = r.latest;
    const sw = latest.sw || {};
    const concept = latest.concept || {};

    function speedLabel(v) {
      if (v == null) return { text: "N/A", cls: "" };
      if (v >= 60) return { text: "快速轮动", cls: "fast" };
      if (v >= 30) return { text: "中等轮动", cls: "mid" };
      return { text: "轮动缓慢", cls: "slow" };
    }
    function speedHint(v) {
      if (v == null) return "";
      if (v >= 60) return "板块快速轮动，追热点风险大";
      if (v >= 30) return "轮动速度适中，可关注主线";
      return "主线明确，适合趋势跟踪";
    }

    const sw5 = speedLabel(sw.speed_5d);
    const sw10 = speedLabel(sw.speed_10d);
    const sw20 = speedLabel(sw.speed_20d);
    const swHint = speedHint(sw.speed_5d);

    const card = document.createElement("div");
    card.className = "rotation-card";
    card.innerHTML = `
      <div class="rotation-card-header">🌀 板块轮动速度</div>
      <div class="rotation-card-body">
        <div class="rotation-row">
          <span class="rotation-label">申万行业</span>
          <span class="rotation-item ${sw5.cls}">5日: ${sw.speed_5d != null ? sw.speed_5d + "%" : "N/A"} ${sw5.text}</span>
          <span class="rotation-item ${sw10.cls}">10日: ${sw.speed_10d != null ? sw.speed_10d + "%" : "N/A"} ${sw10.text}</span>
          <span class="rotation-item ${sw20.cls}">20日: ${sw.speed_20d != null ? sw.speed_20d + "%" : "N/A"} ${sw20.text}</span>
        </div>
        ${concept.speed_5d != null ? `
        <div class="rotation-row">
          <span class="rotation-label">概念板块</span>
          <span class="rotation-item ${speedLabel(concept.speed_5d).cls}">5日: ${concept.speed_5d}% ${speedLabel(concept.speed_5d).text}</span>
          <span class="rotation-item ${speedLabel(concept.speed_10d).cls}">10日: ${concept.speed_10d}% ${speedLabel(concept.speed_10d).text}</span>
          <span class="rotation-item ${speedLabel(concept.speed_20d).cls}">20日: ${concept.speed_20d}% ${speedLabel(concept.speed_20d).text}</span>
        </div>` : ""}
        <div class="rotation-hint">💡 ${swHint}</div>
      </div>`;
    container.appendChild(card);
  } catch (e) {
    // 静默失败，不影响主流程
    console.warn("轮动速度卡片加载失败:", e);
  }
}

async function renderIndustry() {
  const r = await fetchJSON(`./data/industry-${state.range}.json`);
  content.innerHTML = "";

  // 锚点导航条：sticky 定位，快速跳转申万行业 / 概念板块
  const swCount = Object.keys(r.indices || {}).length;
  const conceptCount = Object.keys(r.concepts || {}).length;
  const anchorBar = document.createElement("div");
  anchorBar.className = "industry-anchor-bar";
  anchorBar.innerHTML = `
    <div class="anchor-btn-group">
      <button type="button" data-anchor="sw-industries" class="active">申万行业（${swCount}）</button>
      <button type="button" data-anchor="thsc-concepts">概念板块（${conceptCount}）</button>
    </div>
    <a class="anchor-back-top" href="#" onclick="window.scrollTo({top:0,behavior:'smooth'});return false">回到顶部</a>`;
  content.appendChild(anchorBar);
  // 按钮点击：平滑滚动到对应区域
  anchorBar.querySelectorAll("button[data-anchor]").forEach((btn) => {
    btn.onclick = () => {
      const el = document.getElementById(btn.dataset.anchor);
      if (el) el.scrollIntoView({ behavior: "smooth" });
      // 更新激活状态
      anchorBar.querySelectorAll("button[data-anchor]").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
    };
  });

  // 板块轮动速度卡片（放在锚点导航下方、热力图上方）
  await renderRotationCard(content);

  // 申万行业区域
  const swSection = document.createElement("div");
  swSection.id = "sw-industries";
  content.appendChild(swSection);

  renderIndustryHeatmap(r.heatmap, "申万一级行业涨跌幅热力图（近 1 日 / 近 5 日）", swSection);
  // BUG-E：行业搜索条（输入名称关键词实时过滤行业网格）
  industrySearchBar(swSection);
  const title = document.createElement("div");
  title.className = "section-title";
  const total = Object.keys(r.indices || {}).length;
  const filtered = filterIndicesByName(r.indices, state.industrySearch);
  const shown = Object.keys(filtered).length;
  title.textContent = `申万行业指数折线（${shown}/${total} 个，含买卖点 + 资金流/成交额/换手率 + 行业内宽度）`;
  swSection.appendChild(title);
  renderIndustryGrid(filtered, swSection);

  // 概念板块区域
  if (conceptCount > 0) {
    const thscSection = document.createElement("div");
    thscSection.id = "thsc-concepts";
    content.appendChild(thscSection);

    const conceptTitle = document.createElement("div");
    conceptTitle.className = "section-title";
    conceptTitle.textContent = `概念板块指数折线（${conceptCount} 个，含买卖点 + 回测统计）`;
    thscSection.appendChild(conceptTitle);
    renderIndustryGrid(r.concepts || {}, thscSection);
  }
}

// ============ 手动补录（前端入口已移除） ============
// 敏感操作不应在主导航暴露。后端 /api/manual 与 /api/manual/check API 保留，
// 需要时直接调 API 或另设权限入口。原 modal/handler 代码已删除。

// === UX 优化：sticky 偏移测量 + 右下角回到顶部浮动按钮 ===
// 测量顶部 tab 栏实际高度写入 CSS 变量 --tab-h（兜底 41px）。
function initStickyOffset() {
  const tabs = document.querySelector('.tabs');
  if (!tabs) return;
  const set = () => document.documentElement.style.setProperty('--tab-h', tabs.offsetHeight + 'px');
  set();
  window.addEventListener('resize', set);
  window.addEventListener('load', set);
}

// 右下角浮动"回到顶部"箭头按钮：滚动 >300px 淡入，点击平滑回顶，顶部淡出。
function initBackToTop() {
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'back-to-top';
  btn.textContent = '↑';
  btn.setAttribute('aria-label', '回到顶部');
  btn.title = '回到顶部';
  btn.addEventListener('click', () => window.scrollTo({ top: 0, behavior: 'smooth' }));
  document.body.appendChild(btn);
  const onScroll = () => {
    if (window.scrollY > 300) btn.classList.add('visible');
    else btn.classList.remove('visible');
  };
  window.addEventListener('scroll', onScroll, { passive: true });
  onScroll();
}

initStickyOffset();
initBackToTop();
initRuleButton();
renderTab();
