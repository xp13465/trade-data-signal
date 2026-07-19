// 静态版前端 —— 从 web/app.js 改造，数据源由 API 改为本地 JSON 文件。
// 改动点：
//   1. fetchJSON URL：/api/xxx → ./data/xxx.json（各 tab 按 range 读对应文件）
//   2. index 详情：读 ./data/index/{id}-all.json 全历史，前端按 ohlc 日期范围过滤 signals
//   3. 其他逻辑（render/ruleBar/signalColor/initBackToTop/initStickyOffset）保持功能一致
//   4. 手动补录入口已移除（与动态版一致）

// BUG-E：交互增强状态——indexFilter（A 股/港股 指数筛选）/ industrySearch（行业搜索）/ heatmapRange（热力图近1日/近5日切换）。
// 筛选只控制前端显示哪些折线/行业，不影响后端数据。
const state = { tab: "overview", range: "3m", indexFilter: "all", industrySearch: "", heatmapRange: "all", subtab: "a-stock", labIndex: "sh", labZone: "sell", labStrategy: null, labData: null, labSimData: null, labSimPair: null, labSimMode: "full_in", labSimPage: 0, intradaySnapshot: null, labWinSync: false, ntEtf: "510300", ntView: "overview", ntDetailRange: null };
const content = document.getElementById("content");
const charts = [];
// 已生成模拟回测页面的品种（📊 模拟回测按钮显示条件）
const SIM_INDICES = new Set([
  'sh', 'sz', 'cyb', 'csi500', 'csi1000', 'kc50', 'hs300',
  'hsi', 'hscei', 'hstech', 'div_lowvol', 'csi_div',
  'hk_cesg10', 'hk_hsmogi', 'hk_hsmbi', 'hk_hsmpi', 'hk_cshklre', 'hk_cshklc', 'hk_hscci', 'hk_cshkdiv',
  'us_ixic', 'us_spx', 'us_dji', 'us_ndx',
  'ftse100', 'dax', 'bj50',
  'g.gold', 'g.comex_silver', 'g.wti_oil', 'g.us10y', 'g.a_qvix_300', 'g.a_qvix_1000', 'g.brent',
  'gold', 'comex_silver', 'wti_oil', 'brent', 'us10y', 'a_qvix_300', 'a_qvix_1000',
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
const SIM_HREF_MAP = { gold: 'g.gold', comex_silver: 'g.comex_silver', wti_oil: 'g.wti_oil', brent: 'g.brent', us10y: 'g.us10y', a_qvix_300: 'g.a_qvix_300', a_qvix_1000: 'g.a_qvix_1000' };

let _resizeTimer;
window.addEventListener("resize", () => {
  clearTimeout(_resizeTimer);
  _resizeTimer = setTimeout(() => charts.forEach((c) => c && c.resize()), 150);
});

// B5: lab.js 按 tab 懒加载（不访问 lab 的用户不下载 88KB lab.min.js）
// index.html 不再预加载 lab.min.js，切到 lab tab 或 #lab 直链时才 dynamic 注入。
// 版本号 URL 由 <meta name="lab-asset-url"> 持有（bump / main.py 同 script 标签机制注入 ?v= 破缓存）。
let _labScriptPromise = null;
function loadLabScript() {
  if (_labScriptPromise) return _labScriptPromise;
  _labScriptPromise = new Promise((resolve, reject) => {
    if (typeof renderSignalLab === "function") { resolve(); return; }  // 已加载
    const meta = document.querySelector('meta[name="lab-asset-url"]');
    const src = meta ? meta.content : "./lab.min.js";
    const s = document.createElement("script");
    s.src = src;
    s.onload = () => resolve();
    s.onerror = () => { _labScriptPromise = null; reject(new Error("lab.js load failed")); };
    document.head.appendChild(s);
  });
  return _labScriptPromise;
}

document.querySelectorAll('button[data-rng]').forEach((b) => {
  b.onclick = () => {
    state.range = b.dataset.rng;
    document.querySelectorAll('button[data-rng]').forEach((x) => x.classList.remove("active"));
    b.classList.add("active");
    // P2-3: overview/lab tab 周期无意义（图表固定范围），跳过重建避免图表闪烁重绘
    if (state.tab === "overview" || state.tab === "lab") return;
    // 锁定内容区高度避免清空时塌陷跳顶，渲染后恢复滚动位置（周期切换不丢阅读位置）
    const savedScroll = window.scrollY;
    content.style.minHeight = content.offsetHeight + "px";
    renderTab().then(() => {
      content.style.minHeight = "";
      requestAnimationFrame(() => window.scrollTo(0, savedScroll));
    });
  };
});
document.querySelectorAll("button[data-tab]").forEach((b) => {
  b.onclick = () => {
    // B5: lab.js 动态加载后其末尾 IIFE 会 click labBtn 恢复 #lab 直链；
    // tab 切换到 lab 时按钮已 active，IIFE 的 click 会导致重复渲染竞态，跳过。
    if (b.dataset.tab === "lab" && b.classList.contains("active")) return;
    state.tab = b.dataset.tab;
    if (state.tab === "market" && !state.subtab) state.subtab = "a-stock";
    document.querySelectorAll("button[data-tab]").forEach((x) => x.classList.remove("active"));
    b.classList.add("active");
    updateH5Topbar();
    _setTabHash(state.tab);
    renderTab();
  };
});

function clearCharts() {
  _stopIntradayRefresh();
  charts.forEach((c) => c && c.dispose());
  charts.length = 0;
  content.innerHTML = "";
}

// === ECharts 主题色：canvas 不支持 CSS var()，运行时读 getComputedStyle 取值注入 ===
// 15 个皮肤变量见 style.css :root / [data-theme]。UI 语义中性色（轴线/网格/坐标文字/tooltip/legend）
// 跟随主题；数据语义色（涨红跌绿/冰点过热/恐贪色阶/辅买紫/指标蓝橙黄）保持硬编码不变。
function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}
// ECharts 公共 UI 语义色配置片段。mkCard 初始化后立即 setOption 注入；
// applyTheme 切换主题时对已渲染图表重注入以跟随皮肤（merge 模式，业务 option 保留）。
function chartThemeOpts() {
  const axisLabel = cssVar("--text-1");
  const axisLine = cssVar("--border-strong");
  const splitLine = cssVar("--border");
  const nameText = cssVar("--text-1");
  const axisCommon = {
    axisLine: { lineStyle: { color: axisLine } },
    axisTick: { lineStyle: { color: axisLine } },
    axisLabel: { color: axisLabel },
    splitLine: { lineStyle: { color: splitLine } },
    nameTextStyle: { color: nameText },
  };
  return {
    // 全局默认字色：未显式设色的 canvas 文字（含多轴 yAxis[1+] 的 axisLabel/nameTextStyle
    // 等 merge 不到 axisCommon 的组件）一律回退到 --text-1，避免 ECharts 默认 #333 在深底看不清。
    // 全统一 --text-1（皮肤主字体色），不分层：legend/axisLabel/nameTextStyle/visualMap/markLine label
    // /dataZoom slider/tooltip 等 canvas 内所有文字均用 --text-1；数据语义色（涨跌/色阶/彩色背景上的字）保持硬编码。
    textStyle: { color: nameText },
    xAxis: axisCommon,
    yAxis: axisCommon,
    legend: { textStyle: { color: nameText } },
    tooltip: {
      backgroundColor: cssVar("--bg-card"),
      borderColor: cssVar("--border-strong"),
      textStyle: { color: cssVar("--text-1") },
      confine: true,                                  // tooltip 限制在 chart 容器内,防手机端 markPoint 贴边超屏
      extraCssText: "max-width: 80vw; white-space: normal; word-break: break-word;",  // 防多信号长文案撑宽,窄屏自动换行
    },
  };
}

// 将 chartThemeOpts() 的 UI 语义色深合并进业务 option，供一次性 setOption 首帧即含主题色 + series + visualMap。
// 治本（修刷新闪烁）：原先 mkCard 先 setOption(chartThemeOpts) 作首帧（无 series/visualMap），业务 setOption
// 再 merge 注入 series+visualMap；visualMap 经 merge 注入时首帧未完成着色映射（恐贪分段线呈默认单色），
// 需 rethemeCharts 事后 rAF 重绘修正=闪烁。现在第一次 setOption 即完整含主题色 + series + visualMap，
// ECharts 建立组件时 visualMap 与 series 同步初始化、着色一次完成，首帧正确不闪，不再依赖 retheme 重绘。
// xAxis/yAxis 支持数组（多轴）逐项合并：业务 axisLabel 显式色覆盖主题 axisLabel，业务未设的
// axisLine/splitLine/nameTextStyle 等主题色保留。legend/tooltip 同样浅合并保留双方键。
function withTheme(opt) {
  const t = chartThemeOpts();
  const mergeAxis = (ta, oa) => {
    if (oa === undefined) return ta;
    if (Array.isArray(oa)) return oa.map((o) => Object.assign({}, ta, o));
    return Object.assign({}, ta, oa);
  };
  return Object.assign({}, t, opt, {
    xAxis: mergeAxis(t.xAxis, opt.xAxis),
    yAxis: mergeAxis(t.yAxis, opt.yAxis),
    legend: Object.assign({}, t.legend, opt.legend),
    tooltip: Object.assign({}, t.tooltip, opt.tooltip),
  });
}

// dataZoom 滑块配置（slider 底部日期文字色跟主题；inside 无 UI 无需设色）。
// 抽成函数供所有折线图共用，applyTheme 主题切换时也调它重注入。
function dzOpts() {
  return [
    { type: "inside" },
    { type: "slider", height: 18, bottom: 8, textStyle: { color: cssVar("--text-1") } },
  ];
}

// 重注入主题色到所有已渲染 ECharts 图表（charts 全局 + 信号弹窗 _signalModalCharts）。
// ECharts canvas 不响应 CSS 变量，需手动读 getComputedStyle 重注入 UI 语义色
// （轴线/网格/坐标文字/tooltip/legend/dataZoom slider/visualMap 文字）。
// 调用时机：applyTheme 切皮肤后经 requestAnimationFrame 调用--等 data-theme 改完 CSS 重算再读色重注入。
// 注：刷新/切 tab 首帧不再调用本函数--已通过 withTheme() 让业务 setOption 一次性含主题色 + series +
// visualMap，首帧着色即正确（治本，见 withTheme 注释）。切皮肤是运行时改 CSS 变量，已渲染的 canvas
// 不会自动跟随，故仍需此处重注入。
function rethemeCharts() {
  try {
    var dzColor = cssVar("--text-1");
    var vmColor = cssVar("--text-1");
    function retheme(c) {
      if (!c || c.isDisposed()) return;
      c.setOption(chartThemeOpts());
      var opt = c.getOption();
      if (opt.dataZoom && opt.dataZoom.length) {
        c.setOption({ dataZoom: opt.dataZoom.map(function (d) {
          if (d.type === "slider") return Object.assign({}, d, { textStyle: Object.assign({}, d.textStyle, { color: dzColor }) });
          return d;
        }) });
      }
      if (opt.visualMap && opt.visualMap.length) {
        c.setOption({ visualMap: opt.visualMap.map(function (v) {
          return Object.assign({}, v, { textStyle: Object.assign({}, v.textStyle, { color: vmColor }) });
        }) });
      }
    }
    charts.forEach(retheme);
    _signalModalCharts.forEach(retheme);
  } catch (e) {}
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
  const arr = multi ? series : [{ name: stripHtml(title), data: series }];
  const dates = [...new Set(arr.flatMap((s) => s.data.map((d) => d.date)))].sort();
  const c = mkCard(title, 300, hint, container);
  c.setOption(withTheme({
    tooltip: { trigger: "axis" },
    legend: { top: 0, type: "scroll" },
    grid: { left: 55, right: 20, top: 35, bottom: 35 },
    xAxis: { type: "category", data: dates },
    yAxis: { type: "value", scale: true },
    dataZoom: dzOpts(),
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
  }));
  return c;
}

// 卖点 markPoint 配色（方案 B 标注，2026-07-06）：买=红、卖止盈=绿、卖买点失败=灰、卖无前买=橙。
// B1+S1（2026-07-05）：buy_aux 辅买=粉紫 #d63384（与 buy 红 区分）。
// 判断按 reason 子串：含"买点失败"→灰、"止盈"→绿、"无前买点"→橙；买=红；兜底旧卖点无标签按绿。
function signalColor(s) {
  if (s.signal === "buy") return "#e6492e";
  if (s.signal === "buy_aux") return "#d63384";
  if (s.signal === "freeze") return "#2563eb"; // 冰点标注=蓝色
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
  if (s.signal === "freeze") return "冰点";
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
  kc50: '科创50', bj50: '北证50', hs300: '沪深300', sz50: '上证50',
  // 港股
  hsi: '恒生指数', hscei: '国企指数', hstech: '恒生科技',
  // 美股
  us_dji: '道琼斯', us_ixic: '纳斯达克', us_spx: '标普500', us_ndx: '纳斯达克100',
  // 红利/低波
  div_lowvol: '红利低波', csi_div: '中证红利', sz_div: '深证红利',
  // 全球指标
  cn10y: '中国10年国债', us10y: '美国10年国债', wti_oil: 'WTI原油',
  comex_silver: 'COMEX白银', gold: '伦敦金', oil: '原油', usdcnh: '美元/离岸人民币',
  a_qvix_300: '中国波指300', a_qvix_1000: '中国波指1000', cn_us_spread: '中美利差',
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

// 首页冰点日/买卖点卡片：按日期分组渲染，同日4个/行，今日(date===todayDate)高亮且排首。
// items: freeze={date,score_id,value} | signal={date,index_id,signal,reason}
// kind: "freeze" | "signal"；todayDate: 数据"今日"基准(r.date)
// 每日期全部显示（不做折叠），卡片 .signal-grid 有 max-height+overflow 滚动兜底。
function _renderSignalGrid(items, todayDate, title, kind, emptyText) {
  if (!items || !items.length) return `<h3>${title}</h3><div class="empty-note">${emptyText}</div>`;
  // 按 date 分组（降序），今日组单独提到最前
  const groups = {};
  for (const it of items) {
    (groups[it.date] = groups[it.date] || []).push(it);
  }
  let dates = Object.keys(groups).sort((a, b) => (a < b ? 1 : -1));
  // 今日组排首
  if (todayDate && groups[todayDate]) {
    dates = [todayDate, ...dates.filter((d) => d !== todayDate)];
  }
  let rows = "";
  for (const dt of dates) {
    const isToday = dt === todayDate;
    const dayItems = groups[dt];
    // 今日组内部再按信号优先级排（买>辅买>卖）；冰点按值升序（越冷越前）
    if (kind === "signal") {
      const ord = { buy: 0, buy_aux: 1, sell: 2 };
      dayItems.sort((a, b) => (ord[a.signal] ?? 9) - (ord[b.signal] ?? 9));
    } else {
      dayItems.sort((a, b) => (a.value ?? 99) - (b.value ?? 99));
    }
    const cellHtml = (it) => kind === "signal"
      ? `<span class="sig-item sig-clickable" data-idx="${it.index_id}" data-sig="${it.signal}" data-date="${it.date}" title="点击查看走势图"><b class="${it.signal}">${signalLabel(it)}</b> ${indexIdToName(it.index_id)}</span>`
      : `<span class="sig-item sig-clickable" data-idx="s.${it.score_id}" data-sig="freeze" data-date="${it.date}" data-val="${it.value != null ? it.value.toFixed(1) : ""}" title="点击查看走势图"><span class="sig-freeze-name">${indexIdToName(it.score_id)}</span>=<b class="freeze-val">${it.value != null ? it.value.toFixed(1) : "-"}</b></span>`;
    const dateLabel = fmtDate(dt);
    // 同日数据超过 4 个时按 4 个/行分块换行，每行重复日期（不做合并单元格效果）。
    // COLS 与 CSS .sig-items grid-template-columns:repeat(4,1fr) 一致；
    // 移动端(≤768px) CSS 改 2 列，同日仍按 4 分组，日期会在每 2 个移动行重复一次（分块数不依赖断点，无 resize 回归）。
    const COLS = 4;
    for (let i = 0; i < dayItems.length; i += COLS) {
      const cellsHtml = dayItems.slice(i, i + COLS).map(cellHtml).join("");
      rows += `<div class="sig-day-row${isToday ? " today-row" : ""}"><span class="sig-day-date">${dateLabel}</span><div class="sig-items">${cellsHtml}</div></div>`;
    }
  }
  return `<h3>${title}</h3><div class="signal-grid">${rows}</div>`;
}

// 买卖点回测 stats tips（折线图上方）：散户化多块文案 + 胜率配色梯度 + 凯利公式折叠详解。
// stats = {buy:{10d:{win_rate,pl,mean,n}}, buy_aux:..., sell:...}
// "10日"= 信号后 10 交易日 forward 收益窗口（非"只回测 10 日数据"）；全历史 signals 回测。
// 凯利公式 f* = max(0, (b·p − (1−p)) / b)，b=盈亏比 pl，p=胜率 win_rate → 数学最优下注比例。
//   买/辅买：f>0 标"凯利公式计算仓位 X%（研究参考）"；f≤0 标"凯利公式≤0（负期望，按公式不下注）"。
//   卖：f>0 标"凯利公式计算做空比例 X%（研究参考）"；f≤0 标"凯利公式≤0（负期望，按公式不下注）"。
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

// YYYYMMDD → "MM-DD" 格式(今日不再替换为今日文字,仅靠行背景色 today-row 高亮)
function fmtDate(dateStr) {
  if (!dateStr || dateStr.length < 8) return dateStr || "";
  const m = dateStr.substring(4, 6), d = dateStr.substring(6, 8);
  return `${m}-${d}`;
}

// 图表标题追加"最新日期 数值"，无需 hover 即可见最新值（复用 fmtDate 转 MM-DD）
// 用 <span class="chart-latest"> 包裹高亮，与标题文字区分便于一眼看到最新数据
function latestSuffix(data) {
  if (!data || !data.length) return "";
  const last = data[data.length - 1];
  if (!last || last.value == null) return "";
  return `<span class="chart-latest"> · ${fmtDate(last.date)} ${last.value.toFixed(2)}</span>`;
}

function latestSuffixPct(data) {
  const _last = data[data.length - 1];
  const _prev = data.length > 1 ? data[data.length - 2] : null;
  const _pct = (_last && _last.value != null && _prev && _prev.value) ? (_last.value / _prev.value - 1) * 100 : null;
  const _up = (_pct || 0) >= 0;
  const _pctSuffix = (_pct != null && isFinite(_pct)) ? ` <span class="pct-badge" style="color:${_up ? "#e6492e" : "#2e8b57"}">${_up ? "+" : ""}${_pct.toFixed(2)}%</span>` : "";
  return latestSuffix(data) + _pctSuffix;
}

// series.name 去 HTML：latestSuffix 的 <span> 高亮只供卡片标题（HTML 容器），
// 进 ECharts series.name 会被 tooltip 默认 formatter HTML 转义成字面量 <span>，故 tooltip 用纯文本
// 最后 collapse 连续空格并 trim：termTip 返回的前导空格在剥离 span 后会残留，避免 legend 多空格
function stripHtml(s) { return String(s == null ? "" : s).replace(/<span class="term-tip"[^>]*>[\s\S]*?<\/span>/g, "").replace(/<[^>]+>/g, "").replace(/\s+/g, " ").trim(); }

// A：标题旁 ❓ 小问号 hover 提示（专业术语白话，原生 title 属性，无需 JS tooltip）
function termTip(text) {
  return ` <span class="term-tip" data-tip="${text}">❓</span>`;
}

// 涨跌家数数据口径（akshare sina 源全市场快照，与东财等 APP 覆盖范围略有差异，非数据错误）
const _WIDTH_CALIBER_TIP = "涨跌家数口径：akshare sina 源全市场快照，涨跌幅为负计为跌、平盘不计入。不同数据源覆盖范围略有差异（如东财多1只），非数据错误。";

// ❓ 问号 hover pop 浮层（替代浏览器原生 title，pop 风格：圆角/阴影/主题色/小箭头）
// 事件委托：document mouseover/mouseout 检查 target.closest('[data-tip]')，
// 覆盖 termTip 生成的 .term-tip + lab.js 的 data-tip 元素，一次绑定全局生效。
// 移动端增强：(hover:none) 设备补 click 委托——点 [data-tip] 弹 pop(防合成 mouseover
// 闪现 80ms 后消失)、再点同一元素或点别处关闭、点 pop 内容不关；PC (hover:hover) 仍纯 hover。
(function _initTermPop() {
  var pop = document.createElement("div");
  pop.className = "term-pop";
  pop.setAttribute("role", "tooltip");  // a11y：补偿被迁移走的原生 title
  pop.style.display = "none";
  document.body.appendChild(pop);
  var hideTimer = null;
  var popByClick = false;  // pop 由 click 触发(移动端)，此时 mouseout 不立即关
  var popEl = null;        // 当前触发元素，用于同元素再点 toggle 关
  var isTouch = window.matchMedia && window.matchMedia("(hover: none)").matches;
  // 查找触发 pop 的元素：优先 [data-tip]，回退 [title]（排除 iframe a11y title + [data-no-pop]）。
  // [title] 首次命中时一次性迁移到 data-tip 并移除原生 title，防浏览器原生 tooltip 闪现。
  function findTipEl(target) {
    if (!target || !target.closest) return null;
    var el = target.closest("[data-tip]");
    if (el) return el;
    el = target.closest("[title]");
    if (!el) return null;
    if (el.tagName === "IFRAME") return null;         // iframe title 是 a11y 语义，不加 pop
    if (el.hasAttribute("data-no-pop")) return null;  // 显式排除
    el.setAttribute("data-tip", el.getAttribute("title"));
    el.removeAttribute("title");
    el.dataset.fromTitle = "1";  // 标记：该 data-tip 由 title 迁移而来（便于排查）
    return el;
  }
  function show(el, text) {
    if (hideTimer) { clearTimeout(hideTimer); hideTimer = null; }
    pop.textContent = text;
    pop.style.display = "block";
    popEl = el;
    var r = el.getBoundingClientRect();
    var pw = pop.offsetWidth, ph = pop.offsetHeight;
    var left = r.left + r.width / 2 - pw / 2;
    left = Math.max(8, Math.min(left, window.innerWidth - pw - 8));
    var top = r.bottom + 6;
    var above = false;
    if (top + ph > window.innerHeight - 8) { top = r.top - ph - 6; above = true; }
    pop.style.left = left + "px";
    pop.style.top = top + "px";
    // 方向 class：默认(下方)箭头朝上，翻到上方时箭头朝下，供 CSS ::before 翻转
    if (above) pop.classList.add("term-pop--up"); else pop.classList.remove("term-pop--up");
  }
  function hide() { hideTimer = setTimeout(function () { pop.style.display = "none"; }, 80); }
  function hideNow() { if (hideTimer) { clearTimeout(hideTimer); hideTimer = null; } pop.style.display = "none"; popByClick = false; }
  document.addEventListener("mouseover", function (e) {
    var el = findTipEl(e.target);
    if (el && !popByClick) show(el, el.getAttribute("data-tip"));
  });
  document.addEventListener("mouseout", function (e) {
    var el = findTipEl(e.target);
    if (el && !popByClick) hide();
  });
  if (isTouch) {
    document.addEventListener("click", function (e) {
      var el = findTipEl(e.target);
      if (el) {
        if (popByClick && popEl === el) { hideNow(); return; }  // 同元素再点 -> 关
        show(el, el.getAttribute("data-tip"));
        popByClick = true;  // 标记后 mouseout 不立即关，直到下次 click 别处
        return;
      }
      if (e.target.closest && e.target.closest(".term-pop")) return;  // 点 pop 内容不关
      if (popByClick) hideNow();  // 点别处 -> 关
    });
  }
  pop.addEventListener("mouseenter", function () { if (hideTimer) { clearTimeout(hideTimer); hideTimer = null; } });
  pop.addEventListener("mouseleave", hide);
})();

// B：卡片底部追加一行 muted 白话小字（最晦涩术语常驻解释，放卡片底部）
function appendPlainTip(chartOrEl, text) {
  const dom = chartOrEl && chartOrEl.getDom ? chartOrEl.getDom() : chartOrEl;
  const card = dom && dom.closest ? dom.closest(".chart-card") : null;
  if (!card) return;
  const d = document.createElement("div");
  d.className = "term-plain";
  d.textContent = text;
  card.appendChild(d);
}

// 最新值紧凑格式：万级缩写、整数直出、其余按量级保留1-2位小数（标题后缀用，简洁为主）
function fmtLatestVal(v) {
  if (v == null || isNaN(v)) return "-";
  const a = Math.abs(v);
  if (a >= 10000) return (v / 10000).toFixed(1) + "万";
  if (Number.isInteger(v)) return String(v);
  if (a >= 100) return v.toFixed(0);
  return v.toFixed(2);
}

// 多序列图标题后缀：取所有序列最新日期的最大值 + 各序列最新值（用短标签 label，缺省用 name）
// series = [{name, data:[{date,value}], label?}]，如 ` · MM-DD 涨停92 跌停4 连板2`
function latestSuffixMulti(series) {
  if (!series || !series.length) return "";
  let lastDate = "";
  for (const s of series) {
    if (s && s.data && s.data.length) {
      const d = s.data[s.data.length - 1];
      if (d && d.date && d.date > lastDate) lastDate = d.date;
    }
  }
  if (!lastDate) return "";
  const parts = [];
  for (const s of series) {
    if (!s || !s.data || !s.data.length) continue;
    let v = null;
    for (let j = s.data.length - 1; j >= 0; j--) {
      if (s.data[j].date <= lastDate) { v = s.data[j].value; break; }
    }
    const lbl = s.label || s.name || "";
    parts.push(`${lbl}${fmtLatestVal(v)}`);
  }
  return `<span class="chart-latest"> · ${fmtDate(lastDate)} ${parts.join(" ")}</span>`;
}

// 判断指标是否停更：数据日期距最新交易日超过 days 天视为停更（如北向资金 2024-08 起源端停更）。
// 用于概览 KPI 卡片：停则隐藏，恢复更新后自动显示回来。
function isStaleMetric(metricDate, latestDate, days = 30) {
  if (!metricDate || !latestDate || metricDate.length < 8 || latestDate.length < 8) return false;
  const p = (s) => new Date(+s.substring(0, 4), +s.substring(4, 6) - 1, +s.substring(6, 8));
  const diff = Math.round((p(latestDate) - p(metricDate)) / 86400000);
  return diff > days;
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
          ? `<span class="hint-kelly">→ 凯利公式计算做空比例 <b>${kellyPct}%</b>（研究参考）</span>`
          : `<span class="hint-kelly warn">→ 凯利公式≤0（负期望，按公式不下注）</span>`;
      } else {
        kellyHtml = kellyPct > 0
          ? `<span class="hint-kelly">→ 凯利公式计算仓位 <b>${kellyPct}%</b>（研究参考）</span>`
          : `<span class="hint-kelly warn">→ 凯利公式≤0（负期望，按公式不下注）</span>`;
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
  return stratHtml + `<div class="hint-header">回测口径：全历史信号 · 信号触发后 10 个交易日收益统计${SIM_INDICES.has(indexId) ? ` <a href="./trade_sim_${SIM_HREF_MAP[indexId] || indexId}.html" class="sim-btn" title="查看模拟回测详情">📊 模拟回测</a>` : ''}</div>` +
    `<div class="hint-blocks">${blocks.join("")}</div>` +
    freqHtml +
    `<details class="hint-kelly-explain"><summary>凯利公式是什么？这个数怎么看？</summary>` +
    `<div class="hint-kelly-body">` +
    `<div><b>公式</b>：f* = max(0, (盈亏比 × 胜率 − (1 − 胜率)) ÷ 盈亏比) —— 根据该信号的胜率与盈亏比，算出每次下注的最优资金比例。</div>` +
    `<div><b>"凯利 X%"是什么</b>：理论上每次用总资金的 X% 买入（或做空）是数学上的理论参考比例——长期复合增长较快、破产风险较低的资金配置模型。</div>` +
    `<div><b>"凯利公式≤0"是什么意思</b>：公式算出 ≤0，说明这个信号<b>长期期望为负</b>（亏得多赢得少），按公式不应下注。卖点凯利为 0 通常因胜率接近 50% 且盈亏比&lt;1。</div>` +
    `<div><b>卖点语义</b>：D1 卖点是<b>止盈减仓提示</b>，不是高胜率反向交易指令——卖点后 10 日走弱概率≈50% 接近随机，不可作为独立卖出依据（详见规则说明条）。</div>` +
    `<div><b>重要提醒</b>：凯利公式假设胜率/盈亏比稳定已知，但回测统计本身有波动且含幸存者偏差；<b>请把凯利 X% 当参考上限，实战建议大幅打折</b>（如 1/2 凯利甚至 1/4 凯利）。</div>` +
    `</div></details>` +
    `<div class="hint-disclaimer">⚠ 以上为历史回测统计与数学公式参考仓位，非投资建议；过往表现不代表未来收益。</div>`;
}

// 指数图 + 买卖点标注
function indexChart(title, ohlc, signals, stats, strategy, container = content, chartArr = charts, indexId) {
  const hint = statsHint(stats, strategy, indexId);
  // 标题追加最新日期+收盘价（OHLC 图，取最后一条 close）
  const _last = ohlc && ohlc.length ? ohlc[ohlc.length - 1] : null;
  const _pct = _last && _last.pct_change != null ? _last.pct_change : null;
  const _up = (_pct || 0) >= 0;
  const _closeSuffix = _last && _last.close != null ? `<span class="chart-latest"> · ${fmtDate(_last.date)} ${_last.close.toFixed(2)}</span>` : "";
  const _pctSuffix = (_pct != null) ? ` <span class="pct-badge" style="color:${_up ? "#e6492e" : "#2e8b57"}">${_up ? "+" : ""}${_pct.toFixed(2)}%</span>` : "";
  const _suffix = _closeSuffix + _pctSuffix;
  const c = mkCard(title + _suffix, 360, hint, container, chartArr);
  // 信号频率改 hover pop（与行业卡片一致，悬浮成功率行弹频率）
  _bindFreqPopupToHintRows(c.getDom().parentElement, stats);
  const close = ohlc.map((d) => [d.date, d.close]);
  const markData = signals.map((s) => {
    const o = ohlc.find((x) => x.date === s.date);
    return {
      coord: [s.date, o ? o.close : null],
      value: signalLabel(s),
      itemStyle: { color: signalColor(s) },
    };
  });
  c.setOption(withTheme({
    tooltip: { trigger: "axis" },
    grid: { left: 55, right: 20, top: 30, bottom: 50 },
    xAxis: { type: "category", data: ohlc.map((d) => d.date) },
    yAxis: { type: "value", scale: true },
    dataZoom: dzOpts(),
    series: [
      {
        name: stripHtml(title),
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
  }));
  return c;
}

// 单序列 value 折线 + 买卖点 markPoint（B 扩展：指标/情绪分用，数据是 [{date,value}]）
// 与 indexChart 区别：数据结构是 value 单序列（无 close/high），量级差异大（gold 100-1249 /
// cn10y 1.5-4 / usdcnh 680-722），用通用折线 + markPoint。opts 透传 visualMap 等（cross_market 用）。
function valueChartWithSignals(title, data, signals, opts, stats, strategy, indexId, container = content, chartArr = charts) {
  const sigs = signals || [];
  const hint = statsHint(stats, strategy, indexId);
  const c = mkCard(title, 360, hint, container, chartArr);
  // 信号频率改 hover pop（与行业卡片一致，悬浮成功率行弹频率）
  _bindFreqPopupToHintRows(c.getDom().parentElement, stats);
  const markData = sigs.map((s) => {
    const p = data.find((x) => x.date === s.date);
    return {
      coord: [s.date, p ? p.value : null],
      value: signalLabel(s),
      itemStyle: { color: signalColor(s) },
    };
  });
  c.setOption(withTheme({
    tooltip: { trigger: "axis" },
    grid: { left: 55, right: 20, top: 30, bottom: 50 },
    xAxis: { type: "category", data: data.map((d) => d.date) },
    yAxis: { type: "value", scale: true },
    dataZoom: dzOpts(),
    series: [{
      name: stripHtml(title),
      type: "line",
      smooth: true,
      symbol: "none",
      connectNulls: true,
      data: data.map((d) => [d.date, d.value]),
      lineStyle: { width: 1.5 },
      markPoint: {
        symbol: "pin",
        symbolSize: 34,
        label: { fontSize: 11, color: "#fff", hideOverlap: true },
        data: markData,
      },
    }],
    ...opts,
  }));
  return c;
}

// 静态版：读本地 JSON 文件（替代 fetch API）
// in-flight fetch 去重：同 URL 并发请求只发一次，复用 Promise。
// 解决重复点击二级 tab / 周期切换时启动多个并行 fetch 的重复劳动（首个 fetch 白等、总耗时被拉长）。
// 不同 URL 各自独立缓存；fetch 完成后（resolve/reject）立即清 key，下次调用重新发请求。
// P1-2: 结果缓存（带 TTL）。切 tab 再切回不重拉历史数据；时效敏感数据（overview/intraday_snapshot/metrics/summary/summary_history）跳过缓存。
const _inflightFetch = new Map();
const _resultCache = new Map(); // url -> { data, ts }
// 兼容两种版本URL:静态 ./data/summary.json / summary_history.json；动态 /api/summary / /api/summary/history?...
const _NO_CACHE_URLS = /(?:^|\/)(?:overview|intraday_snapshot|metrics|summary(?:_history|\/history)?)(?:\.json)?(?:$|[?])/;
const _CACHE_TTL = 5 * 60 * 1000; // 历史类数据缓存 5 分钟
async function fetchJSON(url) {
  // 1. 结果缓存命中（时效敏感 URL 跳过，确保盘中快照实时性）
  if (!_NO_CACHE_URLS.test(url)) {
    const rc = _resultCache.get(url);
    if (rc && (Date.now() - rc.ts) < _CACHE_TTL) return rc.data;
  }
  // 2. in-flight 去重（同 URL 并发只发一次）
  const inflight = _inflightFetch.get(url);
  if (inflight) return inflight;
  // A3: AbortController + 15s 超时，避免后端卡死时请求永久挂起；超时由调用方 catch + renderFailCard 兜底
  const controller = new AbortController();
  const slowTimer = setTimeout(() => controller.abort(), 15000);
  const p = fetch(url, { signal: controller.signal })
    .then((r) => { if (!r.ok) throw new Error("HTTP " + r.status + " " + url); return r.json(); })
    .then((data) => {
      // 成功才缓存（时效敏感 URL 跳过）；失败不缓存，下次重试
      if (!_NO_CACHE_URLS.test(url)) _resultCache.set(url, { data, ts: Date.now() });
      return data;
    })
    .catch((e) => {
      // 超时（abort）：renderFailCard 存在则向上抛由调用方兜底渲染，否则 console.error 并返回 null
      if (e && e.name === "AbortError") {
        console.error("fetchJSON timeout (15s): " + url);
        if (typeof renderFailCard !== "function") return null;
      }
      throw e;
    })
    .finally(() => { clearTimeout(slowTimer); _inflightFetch.delete(url); });
  _inflightFetch.set(url, p);
  return p;
}

// 加载失败占位卡片：统一错误兜底（X4）。失败时显示"加载失败"而非空白，与空数据 empty-note 区分。
function renderFailCard(container, title, err) {
  const card = document.createElement("div");
  card.className = "chart-card placeholder";
  card.innerHTML = `<h3>${title || ""}</h3><div class="placeholder-body">加载失败${err ? "：" + err : ""}</div>`;
  (container || content).appendChild(card);
}

// 加载中状态：spinner+文字，3秒后追加"网络较慢"提示。返回 timer 句柄供 clearLoadingTimer 清理。
// 解决手机端点二级tab后页面空白无反馈、用户不知是卡死还是加载中的问题。
function renderLoadingState(container, msg) {
  container.innerHTML = "";
  const el = document.createElement("div");
  el.className = "loading loading--active";
  el.innerHTML = `<span class="loading__spinner"></span><span class="loading__text">${msg || "加载中…"}</span>`;
  container.appendChild(el);
  const timer = setTimeout(() => {
    const hint = document.createElement("div");
    hint.className = "loading__hint";
    hint.textContent = "网络较慢，请稍候…";
    el.appendChild(hint);
  }, 3000);
  return timer;
}
function clearLoadingTimer(timer) { if (timer) clearTimeout(timer); }
// 加载失败状态：错误信息 + 重试按钮，retryFn 为重试回调
function renderErrorState(container, err, retryFn) {
  container.innerHTML = "";
  const el = document.createElement("div");
  el.className = "loading loading--error";
  const msg = document.createElement("span");
  msg.className = "loading__text";
  const errStr = typeof err === "string" ? err : (err && err.message ? err.message : String(err));
  msg.textContent = "加载失败" + (errStr ? "：" + errStr : "");
  el.appendChild(msg);
  const btn = document.createElement("button");
  btn.className = "loading__retry";
  btn.textContent = "重试";
  btn.onclick = () => { if (retryFn) retryFn(); };
  el.appendChild(btn);
  container.appendChild(el);
}

// ============ 动态1行折叠：1行容量按视口宽度自适应，超出1行进折叠，resize 重算 ============
// 读 getComputedStyle(grid).gridTemplateColumns 的实际轨道数(适配 auto-fill / 媒体查询任一布局)，
// 比 Math.floor(width/minW) 更准(与浏览器实际排布一致)。
function gridColsOf(el) {
  if (!el) return 1;
  const tpl = getComputedStyle(el).gridTemplateColumns;
  if (!tpl || tpl === "none") return 1;
  const n = tpl.trim().split(/\s+/).filter(Boolean).length;
  return n > 0 ? n : 1;
}

// display-toggle 版动态1行折叠：所有卡片已渲染入 grid(直接子级)，按 grid 实际列数 cols 仅显示前 cols 个(1行)，
// 其余 display:none；moreBtn 展开/收起全部；ResizeObserver 监听 grid 宽度变化重算 cols 更新显隐。
// 适用于数据本地、可一次性渲染全部卡片的场景(如 A股市场指标走势图，r.metrics 已在内存)。
function setupOneRowToggle(grid, items, moreTextFn, defaultExpanded = false) {
  let expanded = defaultExpanded;
  let curCols = 0;
  let rsizeT = null;
  let roT = null;
  const wrap = document.createElement("div");
  wrap.style.marginBottom = "16px";
  if (grid.parentNode) grid.parentNode.insertBefore(wrap, grid.nextSibling);
  else grid.appendChild(wrap);
  const moreBtn = document.createElement("button");
  moreBtn.className = "more-toggle";
  moreBtn.style.cssText = "display:none;width:100%;padding:8px;border:1px dashed var(--border-strong);border-radius:6px;background:var(--bg-hover);color:var(--text-3);cursor:pointer;font-size:13px;";
  wrap.appendChild(moreBtn);
  function resizeSoon() { clearTimeout(rsizeT); rsizeT = setTimeout(() => charts.forEach((c) => c && c.resize()), 60); }
  function apply() {
    const cols = gridColsOf(grid);
    curCols = cols;
    const showCount = expanded ? items.length : cols;
    let shownNew = false;
    items.forEach((it, i) => {
      const show = i < showCount;
      if (show) {
        if (it.style.display === "none") { it.style.display = ""; shownNew = true; }
      } else {
        it.style.display = "none";
      }
    });
    const hidden = Math.max(0, items.length - showCount);
    moreBtn.style.display = (hidden > 0 || expanded) ? "block" : "none";
    moreBtn.textContent = expanded ? "收起 ▲" : moreTextFn(hidden);
    if (shownNew) resizeSoon();
  }
  moreBtn.onclick = () => { expanded = !expanded; apply(); };
  if (typeof ResizeObserver !== "undefined") {
    const ro = new ResizeObserver(() => {
      clearTimeout(roT);
      roT = setTimeout(() => { if (gridColsOf(grid) !== curCols) apply(); }, 120);
    });
    ro.observe(grid);
  }
  apply();
  return { dispose: () => { clearTimeout(roT); clearTimeout(rsizeT); } };
}

// ============ BUG-E：交互增强（指数/行业筛选 + 热力图切换）============
// 纯前端筛选，不影响后端数据。指数筛选条放指数折线区前（紧挨被筛选内容），筛选时局部刷新：
// 只重渲染指数区（filter bar + 指数折线），不调 renderTab、不 refetch（signals 缓存在闭包内）。
// sectionCharts 同步 push 全局 charts（供 window resize），dispose 时从 charts 移除，避免悬空引用。
// fetcher(id, idx) 返回 { signals, stats }；动态版按 range 走 API，静态版读 all.json 前端过滤。
function renderIndicesSection(container, indices, fetcher, foldOneRow) {
  const entries = Object.entries(indices || {});
  if (!entries.length) return Promise.resolve();

  const signalsCache = {}; // 闭包级缓存：tab/range 切换时整个 renderAStock/renderHK 重建，缓存自然失效
  const sectionCharts = [];
  // rendering+pendingRender 防 onchange 重入(快速切筛选时上一次 await 未完)
  let rendering = false;
  let pendingRender = false;

  function disposeSectionCharts() {
    sectionCharts.forEach((c) => {
      if (!c) return;
      c.dispose();
      const i = charts.indexOf(c);
      if (i >= 0) charts.splice(i, 1);
    });
    sectionCharts.length = 0;
  }

  async function _doRender() {
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
    // 渲染单个指数到 parent（chart 入全局 charts 供 resize + sectionCharts 供本区 dispose）
    async function renderOne(id, idx, parent) {
      if (!signalsCache[id]) signalsCache[id] = await fetcher(id, idx);
      const sig = signalsCache[id];
      if (idx.data && idx.data.length) {
        // 港股盘中实时标注（快照注入 _snap_intraday=true 时显示）
        const intradayTag = idx._snap_intraday ? ' <span class="snap-intraday-tag">⏰ 盘中实时</span>' : "";
        const c = indexChart(idx.name + intradayTag, idx.data, sig.signals, sig.stats, idx.strategy, parent, charts, id);
        sectionCharts.push(c);
        addCardTimeBadge(c.getDom().parentElement, idx.data.length ? idx.data[idx.data.length - 1].date : "", state.intradaySnapshot, "t0");
      }
    }
    // 选了单个指数：只渲染该指数，不折叠
    if (filterId !== "all") {
      // P0-2: 并发预取选中指数填充 signalsCache，再按原顺序渲染（命中 cache 不再发请求）
      await Promise.all(entries.map(([id, idx]) =>
        id !== filterId || signalsCache[id] ? Promise.resolve() : fetcher(id, idx).then((s) => { signalsCache[id] = s; })
      ));
      for (const [id, idx] of entries) {
        if (id !== filterId) continue; // 未选指数跳过渲染
        await renderOne(id, idx, container);
      }
      return;
    }
    // "全部"模式：A股/港股(foldOneRow=true)全部指数直接铺入 .indices-grid 网格(不折叠，无"更多指数"按钮)。
    let parent = container;
    if (foldOneRow) {
      const cardGrid = document.createElement("div");
      cardGrid.className = "indices-grid";
      container.appendChild(cardGrid);
      parent = cardGrid;
    }
    // P0-2: 并发预取所有指数数据填充 signalsCache，再按原顺序渲染（命中 cache 不再发请求，DOM 顺序不变）
    await Promise.all(entries.map(([id, idx]) =>
      signalsCache[id] ? Promise.resolve() : fetcher(id, idx).then((s) => { signalsCache[id] = s; })
    ));
    for (const [id, idx] of entries) {
      await renderOne(id, idx, parent);
    }
  }

  // doRender 包装：防 onchange 重入(快速切筛选时上一次 await 未完即触发下一次)，避免并发渲染撞 charts 数组
  async function doRender() {
    if (rendering) { pendingRender = true; return; }
    rendering = true;
    try { await _doRender(); }
    finally {
      rendering = false;
      if (pendingRender) { pendingRender = false; doRender(); }
    }
  }

  return doRender();
}

// 行业搜索条：行业 tab 用，输入关键词实时过滤行业网格（按 name 或 id 模糊匹配）。
// I1：onSearch 回调只做客户端筛选+局部重渲染（不调 renderTab、不 refetch）。
function industrySearchBar(containerOverride, onSearch) {
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
      if (onSearch) onSearch(); // 局部筛选，不 refetch
    }, 250); // 防抖
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
        <p>当市场<b>短期跌过头了</b>，开始反弹时，作为技术信号参考（超卖反弹）。</p>
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
        <p>价格从<b>近期高点回落</b>，且动量转弱时，作为技术信号参考（趋势转弱）。三个条件<b>同时满足</b>才触发：</p>
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
          <td>卖点价格 &gt; 前一个买点价格<br><span class="muted">→ 历史多为止盈/减仓情形</span></td>
          <td>卖点价格 &lt; 前一个买点价格<br><span class="muted">→ 历史多为止损/观望情形（非操作建议）</span></td>
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

    <div class="rule-freq-stats"></div>

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

  const open = () => {
    modal.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
    const freqDiv = modal.querySelector('.rule-freq-stats');
    if (freqDiv) {
      freqDiv.innerHTML = '<div class="hint-loading">加载中…</div>';
      fetchJSON("./data/signal_freq.json").then((freq) => {
        if (freq) {
          const labels = { buy: "买点", buy_aux: "辅买", sell: "卖点" };
          const cls = { buy: "buy", buy_aux: "buy-aux", sell: "sell" };
          let html = '<div class="hint-header">📅 全品种信号频率汇总</div><div class="hint-blocks">';
          for (const sig of ["buy", "buy_aux", "sell"]) {
            const f = freq[sig];
            if (!f || !f.total_count) continue;
            html += `<div class="hint-row"><span class="hint-sig ${cls[sig]}">${labels[sig]}</span><span class="hint-stat">今年 <b>${f.year_count}</b> 次</span><span class="hint-stat">总计 <b>${f.total_count}</b> 次</span><span class="hint-stat">月均 <b>${f.monthly_avg}</b> 次</span>${f.active_months ? `<span class="hint-stat muted">今年${f.active_months}月均</span>` : ""}</div>`;
          }
          html += '</div>';
          freqDiv.innerHTML = html;
        }
      }).catch(() => {});
    }
  };
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

// ============ 首页买卖点卡片点击弹窗：展示该指数/品类走势图+买卖信号标注 ============
// indexId 可能带前缀：g.=全球指标(wti_oil等，读 global 文件 extras)、s.=情绪分(sentiment_*/cross_market，读 sentiment 文件)、
// 无前缀=常规指数(sh/sz/sw_/thsc_/hsi 等，读 index 文件)。复用 indexChart/valueChartWithSignals + rule-modal 样式。
let _signalModalCharts = [];
function _signalChartModalEl() {
  let modal = document.getElementById("signalChartModal");
  if (modal) return modal;
  modal = document.createElement("div");
  modal.id = "signalChartModal";
  modal.className = "rule-modal hidden";
  modal.innerHTML = '<div class="rule-modal-overlay"></div><div class="rule-modal-body signal-chart-modal-body"><div class="rule-modal-header"><h3 class="signal-chart-title">走势图</h3><div class="signal-chart-periods"><button class="lab-signal-period-btn" data-period="3m">3月</button><button class="lab-signal-period-btn" data-period="6m">6月</button><button class="lab-signal-period-btn active" data-period="1y">1年</button><button class="lab-signal-period-btn" data-period="3y">3年</button><button class="lab-signal-period-btn" data-period="5y">5年</button><button class="lab-signal-period-btn" data-period="all">全部</button></div><button class="rule-modal-close" aria-label="关闭">&times;</button></div><div class="rule-modal-content signal-chart-content"></div></div>';
  // 添加时间段切换按钮事件监听
  modal.querySelectorAll('.lab-signal-period-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      modal.querySelectorAll('.lab-signal-period-btn').forEach(b => b.classList.remove('active'));
      e.target.classList.add('active');
      // 重新加载数据（上下文存于 modal._ctx，由 openSignalChartModal 写入）
      const period = e.target.dataset.period;
      const ctx = modal._ctx || {};
      openSignalChartModal(ctx.indexId, ctx.signal, ctx.date, ctx.freezeVal, period);
    });
  });
  document.body.appendChild(modal);
  const close = () => closeSignalChartModal();
  modal.querySelector(".rule-modal-overlay").addEventListener("click", close);
  modal.querySelector(".rule-modal-close").addEventListener("click", close);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !modal.classList.contains("hidden")) close(); });
  return modal;
}

function closeSignalChartModal() {
  const modal = document.getElementById("signalChartModal");
  if (!modal) return;
  modal.classList.add("hidden");
  document.body.style.overflow = "";
  _signalModalCharts.forEach((c) => c && c.dispose());
  _signalModalCharts = [];
}

// 信号弹窗日期过滤截止日：基于数据末日回推（而非 new Date() 今天），
// 保证静态版窗口与动态版（后端按数据末日算）一致，避免周末数据滞后时窗口多出几天。
// 独立实现（逻辑同 lab.js _labSignalCutoffDate）。chartData 末日格式 YYYYMMDD。
// 支持 3m/6m/1y/3y/5y/all（与首页周期按钮一致）。
function _signalModalCutoff(chartData, period) {
  if (period === "all" || !chartData || !chartData.length) return null;
  const last = chartData[chartData.length - 1].date;
  if (!last || last.length < 8) return null;
  const y = parseInt(last.substring(0, 4), 10);
  const m = parseInt(last.substring(4, 6), 10);
  const d = parseInt(last.substring(6, 8), 10);
  // 按年回推：1y/3y/5y
  const yrs = period === "1y" ? 1 : period === "3y" ? 3 : period === "5y" ? 5 : 0;
  if (yrs) {
    let cy = y - yrs, cm = m, cd = d;
    if (cm === 2 && cd === 29) cd = 28; // 闰日简化
    return `${cy}${String(cm).padStart(2, "0")}${String(cd).padStart(2, "0")}`;
  }
  // 按月回推：3m/6m（近似按日历月减，月末溢出时截到当月最后一天）
  const mos = period === "3m" ? 3 : period === "6m" ? 6 : 0;
  if (mos) {
    let cy = y, cm = m - mos;
    while (cm <= 0) { cm += 12; cy -= 1; }
    let cd = d;
    const _dim = [0, 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
    const _leap = (cy % 4 === 0 && cy % 100 !== 0) || (cy % 400 === 0);
    const _max = cm === 2 && _leap ? 29 : _dim[cm];
    if (cd > _max) cd = _max;
    return `${cy}${String(cm).padStart(2, "0")}${String(cd).padStart(2, "0")}`;
  }
  return null;
}

async function openSignalChartModal(indexId, signal, date, freezeVal, period = "1y") {
  const modal = _signalChartModalEl();
  const body = modal.querySelector(".signal-chart-content");
  const titleEl = modal.querySelector(".signal-chart-title");
  _signalModalCharts.forEach((c) => c && c.dispose());
  _signalModalCharts = [];
  renderLoadingState(body);
  const name = indexIdToName(indexId);
  const isFreeze = signal === "freeze";
  const sigLabel = signal === "buy" ? "买" : signal === "buy_aux" ? "辅买" : signal === "sell" ? "卖" : isFreeze ? `冰点${freezeVal ? "(" + freezeVal + ")" : ""}` : signal;
  titleEl.textContent = `${name} · ${sigLabel} · ${fmtDate(date)}`;
  modal.classList.remove("hidden");
  document.body.style.overflow = "hidden";
  modal._ctx = { indexId, signal, date, freezeVal };
  try {
    let chartData, sigs, stats, strategy, isValue = false;

    if (indexId.startsWith("g.")) {
      const key = indexId.slice(2);
      const r = await fetchJSON("./data/global-extras-all.json");
      const data = (r.extras && r.extras[key]) || [];
      sigs = (r.extras_signals && r.extras_signals[key]) || [];
      stats = (r.extras_stats && r.extras_stats[key]) || {};
      strategy = r.extras_strategy && r.extras_strategy[key];
      chartData = data.map((d) => ({ date: d.date, value: d.value }));
      // 根据period过滤数据（截止日基于数据末日，非今天）
      const filterDate = _signalModalCutoff(chartData, period);
      if (filterDate) {
        chartData = chartData.filter(d => d.date >= filterDate);
      }
      isValue = true;
    } else if (indexId.startsWith("s.")) {
      const key = indexId.slice(2);
      const r = await fetchJSON("./data/sentiment-all.json");
      const data = r[key] || [];
      sigs = (r.signals && r.signals[key]) || [];
      stats = (r.stats && r.stats[key]) || {};
      strategy = r.strategy && r.strategy[key];
      chartData = data.map((d) => ({ date: d.date, value: d.value }));
      // 根据period过滤数据（截止日基于数据末日，非今天）
      const filterDate = _signalModalCutoff(chartData, period);
      if (filterDate) {
        chartData = chartData.filter(d => d.date >= filterDate);
      }
      isValue = true;
    } else {
      const r = await fetchJSON(`./data/index/${indexId}-all.json`);
      chartData = r.ohlc || [];
      sigs = r.signals || [];
      stats = r.stats || {};
      strategy = r.strategy;
      // 根据period过滤数据（截止日基于数据末日，非今天）
      const filterDate = _signalModalCutoff(chartData, period);
      if (filterDate) {
        chartData = chartData.filter(d => d.date >= filterDate);
        sigs = sigs.filter(d => d.date >= filterDate);
      }
    }
    if (!chartData || !chartData.length) {
      body.innerHTML = `<div class="empty-note">暂无「${name}」走势数据</div>`;
      return;
    }
    // 冰点模式：在原买卖点标注基础上追加冰点标注（≤20 蓝色），走势图同时显示买卖点+冰点
    if (isFreeze) {
      const freezePts = chartData.filter((d) => d.value != null && d.value <= 20).map((d) => ({ date: d.date, signal: "freeze" }));
      sigs = [...sigs, ...freezePts];
    }
    body.innerHTML = "";
    const title = name + latestSuffix(chartData);
    if (isValue) valueChartWithSignals(title, chartData, sigs, {}, stats, strategy, indexId, body, _signalModalCharts);
    else indexChart(title, chartData, sigs, stats, strategy, body, _signalModalCharts, indexId);
    requestAnimationFrame(() => _signalModalCharts.forEach((c) => c && c.resize()));
  } catch (e) {
    renderErrorState(body, e, () => openSignalChartModal(indexId, signal, date, freezeVal, period));
  }
}


// ============ KPI 小卡弹窗：点击首页 KPI 卡展示历史走势+细节 ============
// 复用 rule-modal 骨架 + signal-chart-periods period 切换 + echarts 走势图。
// 独立于 signalChartModal（不污染信号语义）。数据按 period 分片拉取，避免拉 6.8MB a-stock-all。
// KPI_HISTORY_SOURCE: 卡 id -> { src } 映射，key 默认=kpiId（sentiment/astock/global 的 JSON key 均与卡 id 同名）
const KPI_HISTORY_SOURCE = {
  // 情绪分 9 张 -> sentiment-{period}.json[kpiId]
  a_sentiment:       { src: "sentiment" },
  cross_market:      { src: "sentiment" },
  fear_greed:        { src: "sentiment" },
  sentiment_sz50:    { src: "sentiment" },
  sentiment_hs300:   { src: "sentiment" },
  sentiment_csi500:  { src: "sentiment" },
  sentiment_csi1000: { src: "sentiment" },
  sentiment_cyb:     { src: "sentiment" },
  sentiment_kc50:    { src: "sentiment" },
  // a-stock 指标 -> a-stock-{period}.json metrics[kpiId].data
  a_width_up_count:    { src: "astock" },
  a_width_down_count:  { src: "astock" },
  a_width_zt_count:    { src: "astock" },
  a_width_dt_count:    { src: "astock" },
  a_width_zhaban_rate: { src: "astock" },
  a_amount:            { src: "astock" },
  a_fund_margin:       { src: "astock" },
  lhb_count:           { src: "astock" },
  // 量比 -> volume_ratio.json（单一文件，客户端按 period 过滤）
  a_volume_ratio: { src: "volume_ratio" },
  // 全球指标 -> global-extras-all.json extras[kpiId]
  gold:       { src: "global" },
  cn10y:      { src: "global" },
  a_qvix_300: { src: "global" },
};
let _kpiDetailCharts = [];

function _kpiDetailModalEl() {
  let modal = document.getElementById("kpiDetailModal");
  if (modal) return modal;
  modal = document.createElement("div");
  modal.id = "kpiDetailModal";
  modal.className = "rule-modal hidden";
  modal.innerHTML = '<div class="rule-modal-overlay"></div><div class="rule-modal-body kpi-detail-modal-body"><div class="rule-modal-header"><h3 class="kpi-detail-title">KPI 走势</h3><div class="signal-chart-periods"><button class="lab-signal-period-btn active" data-period="3m">3月</button><button class="lab-signal-period-btn" data-period="6m">6月</button><button class="lab-signal-period-btn" data-period="1y">1年</button><button class="lab-signal-period-btn" data-period="3y">3年</button><button class="lab-signal-period-btn" data-period="5y">5年</button><button class="lab-signal-period-btn" data-period="all">全部</button></div><button class="rule-modal-close" aria-label="关闭">&times;</button></div><div class="rule-modal-content kpi-detail-content"></div></div>';
  modal.querySelectorAll('.lab-signal-period-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      modal.querySelectorAll('.lab-signal-period-btn').forEach(b => b.classList.remove('active'));
      e.target.classList.add('active');
      const period = e.target.dataset.period;
      const ctx = modal._ctx || {};
      if (ctx.kpiId) openKpiDetailModal(ctx.kpiId, period);
    });
  });
  document.body.appendChild(modal);
  const close = () => closeKpiDetailModal();
  modal.querySelector(".rule-modal-overlay").addEventListener("click", close);
  modal.querySelector(".rule-modal-close").addEventListener("click", close);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !modal.classList.contains("hidden")) close(); });
  return modal;
}

function closeKpiDetailModal() {
  const modal = document.getElementById("kpiDetailModal");
  if (!modal) return;
  modal.classList.add("hidden");
  document.body.style.overflow = "";
  _kpiDetailCharts.forEach((c) => c && c.dispose());
  _kpiDetailCharts = [];
}

// 加载 KPI 历史数据，返回 { series:[{name,data,color?,markLine?,areaStyle?}], visualMap?, yLabel?, hint?, note? }
async function _loadKpiHistory(kpiId, cfg, period) {
  const name = indexIdToName(kpiId);

  // 情绪分 9 张：visualMap 5 段着色（冰点红/偏冷橙/中性灰/偏热绿/过热深绿）
  if (cfg.src === "sentiment") {
    const r = await fetchJSON(`./data/sentiment-${period}.json`);
    const list = r[kpiId] || [];
    return {
      series: [{ name, data: list.map(d => ({ date: d.date, value: d.value })) }],
      visualMap: {
        show: false,
        pieces: [
          { lte: 20, color: "#c62828" },
          { gt: 20, lte: 40, color: "#e6a23c" },
          { gt: 40, lte: 60, color: "#86909c" },
          { gt: 60, lte: 80, color: "#67c23a" },
          { gt: 80, color: "#2e8b57" },
        ],
        dimension: 1,
      },
      hint: "≤20冰点(红) · 20-40偏冷(橙) · 40-60中性(灰) · 60-80偏热(绿) · >80过热(深绿)",
    };
  }

  // a-stock 指标
  if (cfg.src === "astock") {
    const r = await fetchJSON(`./data/a-stock-${period}.json`);
    const metrics = r.metrics || {};
    const _get = (k) => (metrics[k] && metrics[k].data) ? metrics[k].data.map(d => ({ date: d.date, value: d.value })) : [];

    // 涨跌家数：点上涨或下跌都显示双线
    if (kpiId === "a_width_up_count" || kpiId === "a_width_down_count") {
      return {
        series: [
          { name: "上涨家数", data: _get("a_width_up_count"), color: "#e6492e" },
          { name: "下跌家数", data: _get("a_width_down_count"), color: "#2e8b57" },
        ],
        hint: "上涨家数远多于下跌=普涨行情；两者接近=市场分化。",
      };
    }
    // 涨停跌停：点涨停或跌停都显示双线
    if (kpiId === "a_width_zt_count" || kpiId === "a_width_dt_count") {
      return {
        series: [
          { name: "涨停数", data: _get("a_width_zt_count"), color: "#e6492e" },
          { name: "跌停数", data: _get("a_width_dt_count"), color: "#2e8b57" },
        ],
        hint: "涨停数反映做多情绪，跌停数反映恐慌情绪。",
      };
    }
    // 炸板率（百分比，历史短）
    if (kpiId === "a_width_zhaban_rate") {
      const raw = (metrics.a_width_zhaban_rate && metrics.a_width_zhaban_rate.data) || [];
      const data = raw.map(d => ({ date: d.date, value: d.value * 100 }));
      return {
        series: [{ name: "炸板率", data }],
        yLabel: "{value}%",
        note: data.length < 30 ? "历史较短（近期才有），更长周期可能为空" : "",
        hint: "炸板率=当日炸板数/曾涨停数。高=封板资金弱、市场分歧大。",
      };
    }
    // 成交额：主线 + 叠加 MA5/MA20（from volume_ratio.json，仅250条，长周期覆盖尾部）
    if (kpiId === "a_amount") {
      const series = [{ name: "成交额", data: _get("a_amount") }];
      try {
        const vr = await fetchJSON("./data/volume_ratio.json");
        const vrData = vr.data || [];
        const cutoff = _signalModalCutoff(vrData.map(d => ({ date: d.date, value: d.ratio })), period);
        const filtered = cutoff ? vrData.filter(d => d.date >= cutoff) : vrData;
        if (filtered.length) {
          series.push({ name: "MA5", data: filtered.map(d => ({ date: d.date, value: d.ma5 })), color: "#e6a23c" });
          series.push({ name: "MA20", data: filtered.map(d => ({ date: d.date, value: d.ma20 })), color: "#909399" });
        }
      } catch (e) {}
      return {
        series,
        yLabel: "{value}亿",
        hint: "沪深京A股成交额。放量=交投活跃，缩量=清淡。MA5/MA20为均量线。",
      };
    }
    // 两融余额
    if (kpiId === "a_fund_margin") {
      return {
        series: [{ name: "沪市融资余额", data: _get("a_fund_margin") }],
        yLabel: "{value}亿",
        hint: "沪市融资余额=借钱买A股的杠杆资金。增加=杠杆做多情绪升。T+1发布。",
      };
    }
    // 龙虎榜（历史短）
    if (kpiId === "lhb_count") {
      const data = _get("lhb_count");
      return {
        series: [{ name: "龙虎榜上榜家数", data }],
        note: data.length < 30 ? "历史较短（近期才有），更长周期可能为空" : "",
        hint: "龙虎榜=当日涨跌幅前列或有异常波动的个股。上榜多=游资活跃。",
      };
    }
    // 兜底
    return { series: [{ name, data: _get(kpiId) }] };
  }

  // 量比：ratio + MA5 + 1.5/0.7 阈值 markLine
  if (cfg.src === "volume_ratio") {
    const r = await fetchJSON("./data/volume_ratio.json");
    const all = r.data || [];
    const cutoff = _signalModalCutoff(all.map(d => ({ date: d.date, value: d.ratio })), period);
    const data = cutoff ? all.filter(d => d.date >= cutoff) : all;
    return {
      series: [
        {
          name: "量比",
          data: data.map(d => ({ date: d.date, value: d.ratio })),
          markLine: {
            silent: true,
            symbol: "none",
            lineStyle: { type: "dashed" },
            data: [
              { yAxis: 1.5, name: "放量", lineStyle: { color: "#e6492e" }, label: { formatter: "放量1.5x", color: "#e6492e" } },
              { yAxis: 0.7, name: "缩量", lineStyle: { color: "#2e8b57" }, label: { formatter: "缩量0.7x", color: "#2e8b57" } },
            ],
          },
        },
        { name: "MA5", data: data.map(d => ({ date: d.date, value: d.ma5 })), color: "#e6a23c" },
      ],
      yLabel: "{value}x",
      hint: "量比=当日成交额/前5日均量。>1.5倍放量，<0.7倍缩量。",
    };
  }

  // 全球指标：gold/cn10y/a_qvix_300（global-extras-all.json，按 period 客户端过滤）
  if (cfg.src === "global") {
    const r = await fetchJSON("./data/global-extras-all.json");
    const all = (r.extras && r.extras[kpiId]) || [];
    const cutoff = _signalModalCutoff(all, period);
    const data = cutoff ? all.filter(d => d.date >= cutoff) : all;
    const _hints = {
      gold: "沪金主力合约收盘价。避险+抗通胀资产。",
      cn10y: "中国10年期国债收益率。升=资金收紧/经济预期好，降=宽松/避险。",
      a_qvix_300: "中国波指300（期权隐含波动率）。高=市场预期波动大=恐慌。",
    };
    const _yLabels = { gold: "{value}元/克", cn10y: "{value}%", a_qvix_300: "{value}点" };
    return {
      series: [{ name, data: data.map(d => ({ date: d.date, value: d.value })) }],
      yLabel: _yLabels[kpiId],
      hint: _hints[kpiId] || "",
    };
  }

  return { series: [] };
}

async function openKpiDetailModal(kpiId, period = "3m") {
  const cfg = KPI_HISTORY_SOURCE[kpiId];
  if (!cfg) return;
  const modal = _kpiDetailModalEl();
  const body = modal.querySelector(".kpi-detail-content");
  const titleEl = modal.querySelector(".kpi-detail-title");
  _kpiDetailCharts.forEach((c) => c && c.dispose());
  _kpiDetailCharts = [];

  // 从 DOM 卡片读取标题+当前值+标签+sub（避免重新 fetch overview）
  const card = document.querySelector(`.card.kpi[data-kpi-id="${kpiId}"]`);
  const cardTitle = card ? ((card.querySelector(".card-title") || {}).textContent || "").trim() : indexIdToName(kpiId);
  const cardVal = card ? ((card.querySelector(".cv-val") || {}).textContent || "").trim() : "";
  const cardTags = card ? ((card.querySelector(".cv-tags") || {}).textContent || "").trim() : "";
  const cardSub = card ? ((card.querySelector(".card-sub") || {}).textContent || "").trim() : "";

  titleEl.textContent = cardTitle;
  renderLoadingState(body);
  modal.classList.remove("hidden");
  document.body.style.overflow = "hidden";
  modal._ctx = { kpiId };
  modal.querySelectorAll('.lab-signal-period-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.period === period);
  });

  try {
    const result = await _loadKpiHistory(kpiId, cfg, period);
    body.innerHTML = "";
    const hasData = result.series.length && result.series.some(s => s.data && s.data.length);
    if (!hasData) {
      body.innerHTML = `<div class="empty-note">暂无「${cardTitle}」历史走势数据${result.note ? "（" + result.note + "）" : ""}</div>`;
      return;
    }
    // 当前值摘要行
    const valHtml = cardVal ? `<span class="kdv-val">${cardVal}</span>` : "";
    const tagHtml = cardTags ? ` <span class="kdv-tags">${cardTags}</span>` : "";
    const subHtml = cardSub ? ` <span class="kdv-sub">${cardSub}</span>` : "";
    if (valHtml) {
      const cur = document.createElement("div");
      cur.className = "kpi-detail-current";
      cur.innerHTML = valHtml + tagHtml + subHtml;
      body.appendChild(cur);
    }
    // 走势图
    const mainSeries = result.series[0];
    const last = mainSeries.data[mainSeries.data.length - 1];
    const suffix = last ? ` <span class="chart-latest">· ${fmtDate(last.date)}</span>` : "";
    const noteHtml = result.note ? ` <span class="chart-latest" style="color:var(--text-3)">（${result.note}）</span>` : "";
    const chartCard = document.createElement("div");
    chartCard.className = "chart-card";
    const hintHtml = result.hint ? `<div class="chart-hint">${result.hint}</div>` : "";
    chartCard.innerHTML = `<h3>${cardTitle}走势${suffix}${noteHtml}</h3>${hintHtml}<div class="chart" style="height:380px"></div>`;
    body.appendChild(chartCard);
    const chart = echarts.init(chartCard.querySelector(".chart"));
    _kpiDetailCharts.push(chart);

    const dates = [...new Set(result.series.flatMap(s => (s.data || []).map(d => d.date)))].sort();
    const seriesOpt = result.series.map(s => ({
      name: s.name,
      type: "line",
      smooth: true,
      symbol: "none",
      connectNulls: true,
      data: dates.map(d => { const p = (s.data || []).find(x => x.date === d); return p ? p.value : null; }),
      ...(s.color ? { color: s.color, lineStyle: { color: s.color } } : {}),
      ...(s.areaStyle ? { areaStyle: s.areaStyle } : {}),
      ...(s.markLine ? { markLine: s.markLine } : {}),
    }));
    chart.setOption(withTheme({
      tooltip: { trigger: "axis" },
      legend: { top: 0, type: "scroll" },
      grid: { left: 65, right: 25, top: 35, bottom: 45 },
      xAxis: { type: "category", data: dates },
      yAxis: { type: "value", scale: true, axisLabel: result.yLabel ? { formatter: result.yLabel } : undefined },
      dataZoom: dzOpts(),
      series: seriesOpt,
      ...(result.visualMap ? { visualMap: result.visualMap } : {}),
    }));
    requestAnimationFrame(() => chart.resize());
  } catch (e) {
    renderErrorState(body, e, () => openKpiDetailModal(kpiId, period));
  }
}


async function renderTab() {
  clearCharts();
  // 概览 tab 图表固定近60日、策略实验 tab 全历史，周期切换均无意义，隐藏 .periods 和 .h5-period-bar；切走恢复
  const _hidePeriods = (state.tab === "lab" || state.tab === "overview");
  document.querySelectorAll(".periods, .h5-period-bar").forEach((el) => {
    el.style.display = _hidePeriods ? "none" : "";
  });
  renderLoadingState(content);
  try {
    if (state.tab === "overview") await renderOverview();
    else if (state.tab === "market") await renderMarket();
    else if (state.tab === "sentiment") await renderSentiment();
    else if (state.tab === "industry") await renderIndustry();
    else if (state.tab === "lab") {
      await loadLabScript();   // B5: 懒加载 lab.js
      await renderSignalLab();
    }
  } catch (e) {
    renderErrorState(content, e, () => renderTab());
  }
}

// 采集时间独立化：任何 tab 刷新都能显示，不依赖 renderOverview 是否执行
// 末尾追加 ℹ️ 图标，点击弹"数据更新规则"modal（事件委托在 initUpdateRules 绑定 document，重渲染不失效）。
const _UPDATE_RULES_ICON = '<span class="update-rules-btn" title="数据更新规则" role="button" tabindex="0" aria-label="数据更新规则">ℹ️</span>';
// 采集时间不再展示数据健康度圆点：采集层报错(如 HTTPSConnectionPool)用户看不懂且与数据时效功能重叠，
// collect_health 留给后端日志，前端只显示采集时间文本。数据时效以"数据更新规则"弹窗(ℹ️)为准。
function applyCollectTime(ct) {
  _collectTimeBase = { ct: ct || "" };
  _renderCollectTime();
}
// 采集时间统一口径（阶段2）：盘中"HH:MM · 动态(3min)"（腾讯最近拉取时间），收盘"HH:MM · 收盘快照"。
// 盘中优先显腾讯动态时间，无则回退 snap 采集时间；后缀让用户一眼区分动态 vs 收盘。
function _renderCollectTime() {
  const { ct } = _collectTimeBase;
  const _icon = _UPDATE_RULES_ICON;
  if (!ct) {
    document.querySelectorAll(".pc-collect-time,.h5-collect-time").forEach((el) => { el.innerHTML = ""; });
    return;
  }
  const snap = state.intradaySnapshot;
  const intraday = snap && snap.is_closed === false;
  const timeStr = (intraday && _intradayDynamicTime) ? _intradayDynamicTime : ct;
  const suffix = intraday ? " · 动态(3min)" : " · 收盘快照";
  document.querySelectorAll(".pc-collect-time").forEach((el) => {
    el.innerHTML = `数据采集时间：${timeStr}${suffix}${_icon}`;
  });
  document.querySelectorAll(".h5-collect-time").forEach((el) => {
    el.innerHTML = `${timeStr}${suffix}${_icon}`;
  });
}
async function fetchCollectTime() {
  try {
    const r = await fetchJSON("./data/overview.json");
    applyCollectTime(r.collected_at);
  } catch (e) { /* 兜底不崩，保持空 */ }
}

// 盘中实时快照独立获取（不依赖当前 tab），用于一句话总结覆盖 T+1 缺失的指数/行业数据。
// 单例 Promise：多次调用复用同一次请求，避免重复 fetch。
let _intradaySnapPromise = null;
function fetchIntradaySnapshot() {
  if (_intradaySnapPromise) return _intradaySnapPromise;
  _intradaySnapPromise = (async () => {
    try {
      const snap = await fetchJSON("./data/intraday_snapshot.json");
      if (snap && snap.indices) state.intradaySnapshot = snap;
    } catch (e) { /* 兜底不崩，保持空 */ }
  })();
  return _intradaySnapPromise;
}

// 三色语义角标：绿=最新(数据日期>=基准) / 黄=滞后可接受(未到最晚可得时刻) / 红=异常(过时刻仍未采到) / 灰=停更(>30天)
// srcClass: "t0"(T+0实时源,基准=snapDate,盘中当日/收盘当日=绿) / "t1"(T+1源,基准=ptd,复用_t1Relax放宽)
// srcKey: T+1源的标识(查T1_COLLECT_DEADLINE得最晚可得时刻),T+0源传空
// 判定规则:
//   - 数据日期 >= 基准 -> 绿(盘中实时⏰/收盘定格📍/T+1已采到最新📅)
//   - 数据日期 < 基准 且 当前时间 < 该源最晚可得时刻 -> 黄(⚠滞后,采集中/源端尚未发布)
//   - 数据日期 < 基准 且 当前时间 >= 最晚可得时刻 -> 红(🚨异常,过点未采到)
// T+0源最晚时刻=收盘后update_all(18:00);T+1源=各源T1_COLLECT_DEADLINE表;周末无update_all,滞后即红
function getCardTimeBadge(dataDate, snap, srcClass, srcKey) {
  if (srcClass === undefined) srcClass = "t0";
  if (srcKey === undefined) srcKey = "";
  if (!dataDate) return "";
  const mmdd = dataDate.length === 8 ? `${dataDate.slice(4, 6)}-${dataDate.slice(6, 8)}` : dataDate;
  // 源端长期停更(距今>30天)：灰，与 addStaleMark 同口径
  if (dataStaleDays(dataDate) > STALE_DAYS) {
    return `<span class="card-time-badge stale-mark" data-tip="源端长期停更（末日 ${mmdd}，距今>30天），非采集故障">⏸ 停更·${mmdd}</span>`;
  }
  const shIdx = snap && snap.indices ? snap.indices.find((i) => i.code === "sh000001") : null;
  const snapDate = shIdx ? (shIdx.datetime || "").slice(0, 8) : "";
  const ptd = (snap && snap.prev_trading_day) || "";
  const intraday = !!(snap && snap.is_closed === false);
  // 计算基准(理论最新可得交易日)和是否过最晚可得时刻
  let baseline, pastDeadline;
  if (srcClass === "t1") {
    // T+1源：基准=ptd(盘中未到时刻时_t1Relax放宽到ptd-1)；过时刻判定独立于intraday
    const relax = _t1Relax(srcKey, intraday);
    baseline = (relax && ptd) ? _prevTradingDay(ptd) : ptd;
    pastDeadline = _pastCollectDeadline(srcKey);
  } else {
    // T+0源：基准=snapDate(盘中=当日,收盘=当日,周末=ptd);收盘后(非周末)18:00前=黄等待,18:00后/周末=红
    baseline = snapDate || ptd;
    const bjDow = _bjDayOfWeek();
    const isWeekend = bjDow === 0 || bjDow === 6;
    pastDeadline = !intraday && (isWeekend || _bjTimeMin() >= 18 * 60);
  }
  // 绿：数据日期 >= 基准(已采到最新可得)
  if (!baseline || dataDate >= baseline) {
    if (intraday && snapDate && dataDate === snapDate) {
      const hh = shIdx.datetime.slice(8, 10);
      const mm = shIdx.datetime.slice(10, 12);
      if (snap.label && /午休/.test(snap.label)) {
        return `<span class="card-time-badge lunch" data-tip="午休时段(11:30-13:00),13:00复牌后恢复T+0实时">⏰ 午休·${hh}:${mm}</span>`;
      }
      return `<span class="card-time-badge intraday" data-tip="盘中实时刷新(T+0),约30秒一次">⏰ 盘中·${hh}:${mm}</span>`;
    }
    if (srcClass === "t1") {
      // T+1数据已追平今日(snapDate)=今天最新,显绿(与T+0收盘同色,数据确为今日已采到);
      // 仍停在前一交易日(ptd,等盘后补全)=灰(T+1待更新),与T+0今天区分(0541e21初衷仅适用"到昨日等明日")
      if (snapDate && dataDate === snapDate) {
        return `<span class="card-time-badge t1-latest" data-tip="T+1数据源已采到今日(${mmdd}),属今天最新(已追平收盘日,非待更新)">📅 T+1·${mmdd}</span>`;
      }
      return `<span class="card-time-badge t1" data-tip="T+1数据源已采到最新可得日期(${mmdd}),属正常(数据最新可得${mmdd},T+1源次日盘后补全)">📅 T+1·${mmdd}</span>`;
    }
    return `<span class="card-time-badge intraday" data-tip="收盘后定格,显示当日收盘数据(最新)">📍 收盘·${mmdd}</span>`;
  }
  // dataDate < baseline -> 黄(未到时刻,采集中) or 红(过时刻,异常)
  let lagDays = 0;
  if (dataDate.length === 8 && baseline.length === 8) {
    const d1 = new Date(+dataDate.slice(0, 4), +dataDate.slice(4, 6) - 1, +dataDate.slice(6, 8));
    const d2 = new Date(+baseline.slice(0, 4), +baseline.slice(4, 6) - 1, +baseline.slice(6, 8));
    lagDays = Math.floor((d2 - d1) / 86400000);
  }
  if (pastDeadline) {
    const ttl = `超过该源最晚可得时刻仍未采到最新数据，末日 ${mmdd}，已滞后约${lagDays}天，可能采集异常，请反馈`;
    return `<span class="card-time-badge t1-severe" data-tip="${ttl}">🚨 异常·${mmdd}</span>`;
  }
  const ttl = srcClass === "t1"
    ? `T+1数据源盘后公布，当前未到最晚可得时刻，末日 ${mmdd}，已滞后约${lagDays}天，预计稍后更新`
    : `数据滞后(末日 ${mmdd})，盘中等待刷新或update_all尚未运行`;
  return `<span class="card-time-badge t1-stale" data-tip="${ttl}">⚠ 滞后·${mmdd}</span>`;
}
// 给卡片右上角追加盘中标注角标（absolute 不占位，pointer-events:none 不挡点击）
// 同时加 has-time-badge 类，CSS 据此给标题预留 padding-right 防角标压文字
function addCardTimeBadge(cardEl, dataDate, snap, srcClass, srcKey) {
  if (!cardEl) return;
  const html = getCardTimeBadge(dataDate, snap, srcClass, srcKey);
  if (html) {
    cardEl.insertAdjacentHTML("beforeend", html);
    cardEl.classList.add("has-time-badge");
  }
}

// 数据停更标记：指标末日距今>STALE_DAYS 天，判为源端长期停更（非我们采集故障），灰色提示区别于滞后(黄)/异常(红)
// 适用源端停更/计算公式损坏等无法修复的长期停滞（如 QVIX(1000) 源端 optbbs 公式损坏，数据停在历史日期）
const STALE_DAYS = 30;
function dataStaleDays(dataDate) {
  if (!dataDate || dataDate.length !== 8) return Infinity;
  const d = new Date(+dataDate.slice(0, 4), +dataDate.slice(4, 6) - 1, +dataDate.slice(6, 8));
  return Math.floor((Date.now() - d.getTime()) / 86400000);
}
function addStaleMark(cardEl, dataDate) {
  if (!cardEl) return;
  const mmdd = dataDate.length === 8 ? `${dataDate.slice(4, 6)}-${dataDate.slice(6, 8)}` : dataDate;
  cardEl.insertAdjacentHTML("beforeend",
    `<span class="card-time-badge stale-mark" data-tip="源端长期停更（末日 ${mmdd}，距今>30天），非采集故障">⏸ 停更·${mmdd}</span>`);
  cardEl.classList.add("has-time-badge");
}

// === 各数据源时效分级（供"数据更新规则"弹窗"各数据源实时时效"区块 + 卡片角标复用）===
// 汇总各数据源最新日期，让用户一眼区分"正常T+1(数据源盘后公布，公开平台也才到这个日期)" vs
// "异常滞后(公开平台有更新我们没采到)"。从 overview + intraday_snapshot 提取各源最新日期分级显示。
// 原首页"数据时效健康横幅"已移入弹窗（ℹ️ 图标入口），_buildHealthSources 计算结果在弹窗 open 时渲染。
// 复用 getCardTimeBadge 的三档分级口径，保证角标与弹窗时效文案一致。
//
// 逐源采集时点配置(北京时间 HH:MM)：盘中(snap.is_closed===false)且当前时间未到该源采集时点 ->
// 数据源尚未发布/采集调度未跑，显示前一交易日(ptd-1)算正常等待，放宽 stale 基准到 ptd-1 交易日
// (消除盘中误报)。过了该时点该采的还没采到 = 真滞后，恢复原口径(dateStr < ptd 即 stale)。
// "next_day"=源端次日才发当日数据(今天的采集根本采不到 ptd 的当日值)，盘中恒放宽基准-1。
// 收盘后(is_closed===true)一律恢复原口径。商品/国债/QVIX/红利等当天盘后已采到 ptd，无需放宽(默认行为)。
const T1_COLLECT_DEADLINE = {
  // T+1 源最晚可得时刻(北京时间 HH:MM)。当前时间 >= 该时刻仍未采到基准日期数据 -> 红(异常)
  // 盘中(intraday)<该时刻 -> _t1Relax 放宽基准到 ptd-1(数据源尚未发布,显示前日算正常等待)
  a_fund_margin: "23:00",   // 两融(沪市融资余额): rzhb-backfill 23:00当晚单采; 上交所盘后发布较晚
  us_dji_date:   "16:35",   // 美股道指: 美股收盘=北京次日04:00,backfill-evening 16:35采集
  lhb_count:     "19:30",   // 龙虎榜: 东财18:00发当日,lhb-backfill 18:30+19:30(兜底)采集
  futures_date:  "21:00",   // 期货机构持仓: CFFEX 20:00发当日,futures-backfill 20:05+21:00(兜底)采集
  csi_div_date:  "18:00",   // 中证红利: 中证指数公司盘后发布,update_all 17:50采集,18:00后应已到
  etf_date:      "21:30",   // ETF国家队份额: 交易所盘后发布,etf-national-team 20:07+21:30(兜底)采集
  gold:          "18:00",   // 商品期货(黄金/原油): 新浪期货盘后发布,update_all 17:50采集
  cn10y:         "18:00",   // 国债收益率: 中债盘后发布,update_all 17:50采集
  a_qvix_300:    "18:00",   // QVIX期权波动率: 源端盘后发布,update_all 17:50采集
  industry:      "18:00",   // 申万行业指数: baostock/申万收盘后发布,update_all 17:50采集
  hk_south:      "18:00",   // 港股通净买入: 盘后发布,update_all 17:50采集
};
// 是否对该 T+1 源放宽盘中 stale 判定(基准 ptd -> ptd-1 交易日)。intraday=false 一律不放宽。
function _t1Relax(key, intraday) {
  if (!intraday || !key) return false;
  const t = T1_COLLECT_DEADLINE[key];
  if (!t) return false;
  if (t === "next_day") return true; // 盘中恒放宽(今天根本采不到 ptd 当日值)
  // 当前北京时间(UTC+8) vs 采集调度时点
  const now = new Date();
  const bjMin = ((now.getUTCHours() + 8) % 24) * 60 + now.getUTCMinutes();
  const [hh, mm] = t.split(":").map(Number);
  return bjMin < hh * 60 + mm; // 未到采集时点 -> 放宽
}
// 近似上一交易日(仅处理周末，忽略节假日)。后端 prev_trading_day 已用真实日历跳过假期，
// 此处算其前一交易日：遇假期相邻会偏近一天(罕见，且仅影响盘中数小时放宽窗口，过采集时点即恢复严格口径)。
function _prevTradingDay(ptd) {
  if (!ptd || ptd.length !== 8) return "";
  const d = new Date(+ptd.slice(0, 4), +ptd.slice(4, 6) - 1, +ptd.slice(6, 8));
  const w = d.getDay(); // 0=周日 6=周六
  d.setDate(d.getDate() - (w === 1 ? 3 : 1)); // 周一->上周五(+3)，其余->前一日(+1)
  const y = d.getFullYear(), m = d.getMonth() + 1, dd = d.getDate();
  return `${y}${String(m).padStart(2, "0")}${String(dd).padStart(2, "0")}`;
}
// 北京时间(UTC+8)当日分钟数(0-1439)，用于采集时刻判定
function _bjTimeMin() {
  const now = new Date();
  return ((now.getUTCHours() + 8) % 24) * 60 + now.getUTCMinutes();
}
// 北京时间星期几(0=周日 6=周六)，用于周末 T+0 滞后判定(周末无 update_all，滞后即异常)
function _bjDayOfWeek() {
  return new Date(Date.now() + 8 * 3600000).getUTCDay();
}
// 是否已过该 T+1 源的最晚可得时刻(北京时间)。过时刻仍未采到基准日期 -> 红(异常)。
// 仅对 T+1 源(有 T1_COLLECT_DEADLINE 表项)调用；T+0 源走 pastDeadline=!intraday 判定。
// 未配置的 T+1 源默认 18:00(update_all 17:50 采集时刻)。
function _pastCollectDeadline(key) {
  if (!key) return false;
  const t = T1_COLLECT_DEADLINE[key];
  if (t === "next_day") return false; // next_day(保留兼容):盘中恒未过，收盘后靠日历日差
  if (!t) return _bjTimeMin() >= 18 * 60; // 未配置:默认 update_all 18:00
  const [hh, mm] = t.split(":").map(Number);
  return _bjTimeMin() >= hh * 60 + mm;
}
function _dataFreshness(dateStr, ptd, relax, snapDate) {
  if (!dateStr) return { cls: "", text: "无数据" };
  const mmdd = dateStr.length === 8 ? `${dateStr.slice(4, 6)}-${dateStr.slice(6, 8)}` : dateStr;
  // 盘中未到采集时点：基准放宽到 ptd-1 交易日(显示前一交易日算正常等待)
  const baseline = (relax && ptd) ? _prevTradingDay(ptd) : ptd;
  if (!baseline || dateStr >= baseline) {
    // T+1已追平今日(snapDate)=今天最新显绿;否则(停在前一交易日)显灰待更新(与 getCardTimeBadge 同口径)
    const cls = (snapDate && dateStr === snapDate) ? "t1-latest" : "t1";
    return { cls, text: `📅 T+1·${mmdd}` };
  }
  let severe = false;
  if (dateStr.length === 8 && ptd.length === 8) {
    const d1 = new Date(+dateStr.slice(0, 4), +dateStr.slice(4, 6) - 1, +dateStr.slice(6, 8));
    const d2 = new Date(+ptd.slice(0, 4), +ptd.slice(4, 6) - 1, +ptd.slice(6, 8));
    severe = (d2 - d1) / 86400000 > 15;
  }
  return severe
    ? { cls: "t1-severe", text: `🚨 异常·${mmdd}` }
    : { cls: "t1-stale", text: `⚠ 滞后·${mmdd}` };
}
function _buildHealthSources(r, snap) {
  const ptd = (snap && snap.prev_trading_day) || (r && r.date) || "";
  const intraday = !!(snap && snap.is_closed === false);
  const mmdd = (d) => (d && d.length === 8) ? `${d.slice(4, 6)}-${d.slice(6, 8)}` : (d || "");
  const sources = [];
  // A股指数（实时源）
  const shIdx = snap && snap.indices ? snap.indices.find((i) => i.code === "sh000001") : null;
  const shDate = shIdx ? (shIdx.datetime || "").slice(0, 8) : "";
  if (intraday && shDate) {
    sources.push({ name: "A股", cls: "intraday", text: "✓ 实时", hint: "沪深京A股指数实时,盘中每30秒刷新,15:00收盘后定格" });
  } else {
    sources.push({ name: "A股", cls: "closed", text: `📍 收盘·${mmdd(shDate || (r && r.date) || "")}`, hint: "沪深京A股指数,收盘后定格为当日收盘价" });
  }
  // 港股指数（实时源，盘中 hkHSI.is_closed===false）
  const hkIdx = snap && snap.indices ? snap.indices.find((i) => i.code === "hkHSI") : null;
  const hkDate = hkIdx ? (hkIdx.datetime || "").slice(0, 8) : "";
  if (hkIdx && hkIdx.is_closed === false) {
    sources.push({ name: "港股", cls: "intraday", text: "✓ 实时", hint: "恒生指数实时,港股交易时段(9:30-16:00)刷新" });
  } else {
    sources.push({ name: "港股", cls: "closed", text: `📍 收盘·${mmdd(hkDate)}`, hint: "恒生指数,港股收盘后定格" });
  }
  // T+1 指标：从 overview.today.metrics 提取最新日期
  const metrics = (r && r.today && r.today.metrics) || [];
  const findM = (id) => metrics.find((m) => m.id === id);
  const margin = findM("a_fund_margin");
  if (margin && margin.date) {
    const f = _dataFreshness(margin.date, ptd, _t1Relax("a_fund_margin", intraday), shDate);
    sources.push({ name: "两融", cls: f.cls, text: f.text, hint: "两融余额(沪市融资)T+1,上交所盘后发布较晚(实测22:10仍未出当日),当晚23:00单采+凌晨backfill兜底补齐" });
  }
  // 北向资金 2024-08 起源端停更。停≤30天提示用户，>30天长期停更不再提醒（避免长期挂红条烦扰）。
  // 通用规则：任何源端停更的数据源均按此30天口径（与 isStaleMetric 同源日期差逻辑）。
  const north = findM("a_fund_north");
  if (north && north.date && ptd && north.date.length === 8 && ptd.length === 8) {
    const dN = new Date(+north.date.slice(0, 4), +north.date.slice(4, 6) - 1, +north.date.slice(6, 8));
    const dL = new Date(+ptd.slice(0, 4), +ptd.slice(4, 6) - 1, +ptd.slice(6, 8));
    const stoppedDays = Math.round((dL - dN) / 86400000);
    if (stoppedDays > 0 && stoppedDays <= 30) {
      sources.push({ name: "北向", cls: "t1-stale", text: `⚠ 停更·${mmdd(north.date)}`, hint: "北向资金2024-08起源端停更,显示为停更前最后日期" });
    }
  }
  // 成交额/涨停数（intraday 源 metrics，盘中实时）
  const amt = findM("a_amount");
  if (amt && amt.date) {
    if (intraday) sources.push({ name: "成交/涨停", cls: "intraday", text: "✓ 实时", hint: "成交额/涨停数盘中实时(东财板池),收盘后定格" });
    else { const f = _dataFreshness(amt.date, ptd, undefined, shDate); sources.push({ name: "成交/涨停", cls: f.cls, text: f.text, hint: "成交额/涨停数,收盘后定格" }); }
  }
  // 综合情绪分
  const scores = (r && r.today && r.today.scores) || {};
  const aSent = scores.a_sentiment;
  if (aSent && aSent.date) {
    const f = _dataFreshness(aSent.date, ptd, undefined, shDate);
    sources.push({ name: "情绪分", cls: f.cls, text: f.text, hint: "综合情绪分基于各指标计算,随依赖指标更新而更新" });
  }
  // === T+1 补充源：多为盘后次日发布。优先从 today.metrics / indices_sparkline 取最新日期分级；
  //   overview 未暴露的取不到 date 时显示该源预估时点（像追剧有预期），不跳过。
  const spark = (r && r.indices_sparkline) || {};
  const EXTRA = [
    { name: "商品", mid: "gold", hint: "黄金/原油等商品期货T+1,源端(新浪期货)次日盘后发布,15:30收盘后显示昨日属正常,次日盘后更新当日", def: "📅 次日盘后" },
    { name: "国债", mid: "cn10y", hint: "国债收益率T+1,中债/美债盘后次日发布,美债更滞后(常停T-3)", def: "📅 次日盘后" },
    { name: "龙虎榜", mid: "lhb_count", hint: "龙虎榜T+1,东财盘后次日发布,当日18点后更新当日", def: "📅 当日18点后" },
    { name: "期货持仓", mid: null, dateKey: "futures_date", hint: "CFFEX期货机构持仓T+1,次日盘后发布,次日20:00后更新当日", def: "📅 次日20点后" },
    { name: "ETF国家队", mid: null, dateKey: "etf_date", hint: "ETF份额T+1,上交所/深交所盘后次日发布,实测源端常晚于22:00,当日20:07采集通常只到T-1,次日20:07后补全当日", def: "📅 次日22点+" },
    { name: "中国波指", mid: "a_qvix_300", hint: "中国波指(期权隐含波动率)T+1,源端盘后次日发布", def: "📅 次日盘后" },
    { name: "红利指数", iid: "csi_div", dateKey: "csi_div_date", hint: "红利指数T+1,中证指数公司盘后次日发布", def: "📅 次日盘后" },
    { name: "美股", iid: "us_dji", dateKey: "us_dji_date", hint: "美股指数时区滞后,美东21:30开盘(北京),次日晨才出当日收盘,当前显示T-1属正常", def: "📅 次日晨(T-1)" },
  ];
  EXTRA.forEach((cfg) => {
    let dateStr = "";
    if (cfg.mid) { const m = findM(cfg.mid); if (m && m.date) dateStr = m.date; }
    else if (cfg.iid) { const sp = spark[cfg.iid]; if (sp && sp.last_date) dateStr = sp.last_date; }
    // mid/iid 都取不到时，从 overview 顶层 extra_dates(futures_date/etf_date/us_dji_date) 兜底取停留日期
    if (!dateStr && cfg.dateKey) { dateStr = (r && r[cfg.dateKey]) || ""; }
    // T+1 源盘中放宽：用 mid 或 dateKey 作源标识查采集时点(龙虎榜=lhb_count/期货=futures_date/美股=us_dji_date)
    const relax = _t1Relax(cfg.mid || cfg.dateKey, intraday);
    let cls, text;
    if (dateStr) { const f = _dataFreshness(dateStr, ptd, relax, shDate); cls = f.cls; text = f.text; }
    else { cls = "t1"; text = cfg.def; }
    sources.push({ name: cfg.name, cls, text, hint: cfg.hint });
  });
  return sources;
}

// 盘中实时快照覆盖一句话总结文本：T+1 指数源缺当日数据（sh_pct=null / top_industries=空）时，
// 用快照的实时 pct_change 和领涨行业替换，保证收盘后立即看到当日真实涨跌与热点板块。
function injectSnapshotToSummary(text, s, snap) {
  if (!text || !snap || !snap.indices) return text;
  const shIdx = snap.indices.find((i) => i.code === "sh000001");
  if (!shIdx || shIdx.pct_change == null) return text;
  // 快照须与 summary 同日，避免旧快照覆盖新数据
  const snapDate = (shIdx.datetime || "").slice(0, 8);
  if (s.date && snapDate && snapDate !== s.date) return text;

  let out = text;
  // 1. 上证涨跌幅：T+1 指数源缺当日（sh_pct=null）时用快照实时值
  if (s.sh_pct == null) {
    const pct = shIdx.pct_change;
    const dir = pct >= 0 ? "涨" : "跌";
    const val = Math.abs(pct).toFixed(2);
    const ptStr = shIdx.price != null ? `至${Math.round(shIdx.price)}点` : "";
    // 长版"上证指数涨0.00%（至X点）？"
    out = out.replace(/上证指数[涨跌]\d+\.\d+%(?:至\d+点)?/, `上证指数${dir}${val}%${ptStr}`);
    // 短版"上证涨0.00%"
    out = out.replace(/上证[涨跌]\d+\.\d+%/, `上证${dir}${val}%`);
  }
  // 2. 领涨板块：top_industries 为空时用快照 top1
  if ((!s.top_industries || !s.top_industries.length) && snap.industries && snap.industries.length) {
    const top1 = [...snap.industries].sort((a, b) => (b.pct_change ?? -999) - (a.pct_change ?? -999))[0];
    if (top1 && top1.pct_change != null) {
      const name = (top1.sw_name || top1.name || "").replace("SW ", "");
      const lead = top1.lead_stock ? `（${top1.lead_stock}）` : "";
      const sign = top1.pct_change >= 0 ? "+" : "";
      const hot = `${name} ${sign}${top1.pct_change.toFixed(2)}%${lead}`;
      out = out.replace(/领涨板块：无明显热点板块/, `领涨板块：${hot}`);
      out = out.replace(/热点：无明显热点板块/, `热点：${hot}`);
    }
  }
  return out;
}

// 收盘分析横幅/历史弹窗共用的指标 chips 渲染（双版一致）。
// snap 存在且未收盘时优先用快照实时值覆盖上证涨跌幅/点位与领涨板块；s 缺值时兜底用快照。
// 不含恐贪/冰点标签（由调用方自行放置），只返回指标 chips 行 + 领涨板块行。
function renderSummaryChips(s, snap) {
  // 快照同日校验（避免旧快照覆盖新数据）：以 sh000001 的 datetime 判定
  let snapSameDay = false, snapShIdx = null;
  if (snap && snap.indices) {
    snapShIdx = snap.indices.find((i) => i.code === "sh000001");
    if (snapShIdx && snapShIdx.pct_change != null) {
      const snapDate = (snapShIdx.datetime || "").slice(0, 8);
      snapSameDay = !s.date || !snapDate || snapDate === s.date;
    }
  }
  const intraday = snap && snap.is_closed === false;
  // 上证：盘中(snap 未收盘)优先用快照实时值；收盘后用 s 原值；s 缺失时兜底快照
  let shPct = s.sh_pct, shClose = s.sh_close;
  if (snapShIdx && snapSameDay && (intraday || s.sh_pct == null)) {
    shPct = snapShIdx.pct_change;
    if (snapShIdx.price != null) shClose = snapShIdx.price;
  }
  // 盘中优先用腾讯动态值（与分时图/卡片badge同源，消除"分时图2%但卡片1%"矛盾）
  if (intraday && _dynPct("sh") != null) {
    shPct = _dynPct("sh");
    if (_dynPrice("sh") != null) shClose = _dynPrice("sh");
  }
  const chips = [];
  // 上证 chip（涨红跌绿，硬编码语义色）
  if (shPct != null) {
    const shColor = shPct >= 0 ? "#e6492e" : "#2e8b57";
    const shSign = shPct >= 0 ? "+" : "";
    const closeStr = shClose != null ? ` · ${Math.round(shClose)}点` : "";
    chips.push(`<span class="summary-chip" style="color:${shColor}">上证 ${shSign}${shPct.toFixed(2)}%${closeStr}</span>`);
  }
  // 涨跌家数
  if (s.up_count != null || s.down_count != null) {
    chips.push(`<span class="summary-chip">${s.up_count || 0}涨 ${s.down_count || 0}跌${termTip(_WIDTH_CALIBER_TIP)}</span>`);
  }
  // 成交额
  if (s.volume_amount != null) {
    const v = s.volume_amount;
    const amtStr = v >= 10000 ? `${(v / 10000).toFixed(2)}万亿` : `${Math.round(v)}亿`;
    const vLabel = s.volume_label ? ` ${s.volume_label}` : "";
    chips.push(`<span class="summary-chip">成交${amtStr}${vLabel}</span>`);
  }
  // 涨跌停
  if (s.zt_count || s.dt_count) {
    chips.push(`<span class="summary-chip">涨停${s.zt_count || 0} 跌停${s.dt_count || 0}</span>`);
  }
  // 买卖信号
  if (s.buy_count || s.sell_count) {
    chips.push(`<span class="summary-chip">买${s.buy_count || 0} 卖${s.sell_count || 0}</span>`);
  }
  // 新高新低
  if (s.nh_count != null || s.nl_count != null) {
    chips.push(`<span class="summary-chip">新高${s.nh_count || 0} 新低${s.nl_count || 0}</span>`);
  }
  // 均线多空
  if ((s.ma_bullish != null || s.ma_bearish != null) && (s.ma_bullish || s.ma_bearish)) {
    chips.push(`<span class="summary-chip">均线${s.ma_bullish || 0}多${s.ma_bearish || 0}空</span>`);
  }
  const chipsRow = chips.length ? `<div class="summary-chips">${chips.join("")}</div>` : "";

  // 领涨板块行：盘中(snap 未收盘)优先用快照 top3；s 为空时兜底快照
  let topInds = s.top_industries;
  if (snap && snap.industries && snap.industries.length && snapSameDay && (intraday || !topInds || !topInds.length)) {
    topInds = [...snap.industries]
      .sort((a, b) => (b.pct_change ?? -999) - (a.pct_change ?? -999))
      .slice(0, 3)
      .map((d) => ({ name: (d.sw_name || d.name || "").replace("SW ", ""), pct_change: d.pct_change, net_inflow: d.net_inflow }));
  }
  let topRow = "";
  if (topInds && topInds.length) {
    const parts = topInds.slice(0, 3).map((d) => {
      const nm = d.name || "";
      const pc = d.pct_change;
      const color = pc != null ? (pc >= 0 ? "#e6492e" : "#2e8b57") : "var(--text-2)";
      const sign = pc != null && pc >= 0 ? "+" : "";
      const pcStr = pc != null ? `(${sign}${pc.toFixed(2)}%)` : "";
      // 资金净流入：正值=流入(红)，负值=流出(绿)
      let flowStr = "";
      if (d.net_inflow != null) {
        const fColor = d.net_inflow >= 0 ? "#e6492e" : "#2e8b57";
        const fSign = d.net_inflow >= 0 ? "+" : "";
        flowStr = ` <span style="color:${fColor}">💰${fSign}${d.net_inflow.toFixed(1)}亿</span>`;
      }
      return `<span style="color:${color}">${nm}${pcStr}</span>${flowStr}`;
    });
    topRow = `<div class="summary-chips summary-chips-top"><span class="term-tip" data-tip="领涨板块按涨跌幅排序；💰为该行业当日资金净流入(亿元)，正值=资金流入(红)，负值=流出(绿)">🔥领涨❓</span>${parts.join("、")}</div>`;
  }
  // 领跌板块行：盘中(snap 未收盘)优先用快照 bottom3(升序)；s 为空时兜底快照
  let bottomInds = s.bottom_industries;
  if (snap && snap.industries && snap.industries.length && snapSameDay && (intraday || !bottomInds || !bottomInds.length)) {
    bottomInds = [...snap.industries]
      .sort((a, b) => (a.pct_change ?? 999) - (b.pct_change ?? 999))
      .slice(0, 3)
      .map((d) => ({ name: (d.sw_name || d.name || "").replace("SW ", ""), pct_change: d.pct_change, net_inflow: d.net_inflow }));
  }
  let bottomRow = "";
  if (bottomInds && bottomInds.length) {
    const parts = bottomInds.slice(0, 3).map((d) => {
      const nm = d.name || "";
      const pc = d.pct_change;
      const color = pc != null ? (pc >= 0 ? "#e6492e" : "#2e8b57") : "var(--text-2)";
      const sign = pc != null && pc >= 0 ? "+" : "";
      const pcStr = pc != null ? `(${sign}${pc.toFixed(2)}%)` : "";
      // 资金净流入：正值=流入(红)，负值=流出(绿)
      let flowStr = "";
      if (d.net_inflow != null) {
        const fColor = d.net_inflow >= 0 ? "#e6492e" : "#2e8b57";
        const fSign = d.net_inflow >= 0 ? "+" : "";
        flowStr = ` <span style="color:${fColor}">💰${fSign}${d.net_inflow.toFixed(1)}亿</span>`;
      }
      return `<span style="color:${color}">${nm}${pcStr}</span>${flowStr}`;
    });
    bottomRow = `<div class="summary-chips summary-chips-top"><span class="term-tip" data-tip="领跌板块按涨跌幅倒序排序；💰为该行业当日资金净流入(亿元)，正值=资金流入(红)，负值=流出(绿)">❄领跌❓</span>${parts.join("、")}</div>`;
  }
  return chipsRow + topRow + bottomRow;
}

// 盘中横幅专用 chips：summary 是 T-1 收盘、snap 是 T 盘中时，横幅仅用 snap 实时数据。
// 只显示 snap 有的字段（上证/深成/创业板/科创50 等指数实时 + 领涨板块），
// 隐藏 summary 独有指标（恐贪/冰点/涨跌家数/成交额/涨跌停等，盘中不稳定且属 T-1，收盘才有意义）。
function renderIntradayChips(snap) {
  if (!snap || !snap.indices) return "";
  const mainCodes = [
    { code: "sh000001", id: "sh", label: "上证" },
    { code: "sz399001", id: "sz", label: "深成" },
    { code: "sz399006", id: "cyb", label: "创业板" },
    { code: "sh000688", id: "kc50", label: "科创50" },
  ];
  const chips = [];
  for (const { code, id, label } of mainCodes) {
    const idx = snap.indices.find((i) => i.code === code);
    // 盘中优先用腾讯动态值（与分时图/卡片badge同源），无则回退snap
    const pct = _dynPct(id) != null ? _dynPct(id) : (idx ? idx.pct_change : null);
    const price = _dynPrice(id) != null ? _dynPrice(id) : (idx ? idx.price : null);
    if (pct != null) {
      const color = pct >= 0 ? "#e6492e" : "#2e8b57";
      const sign = pct >= 0 ? "+" : "";
      const ptStr = price != null ? ` · ${Math.round(price)}点` : "";
      chips.push(`<span class="summary-chip" style="color:${color}">${label} ${sign}${pct.toFixed(2)}%${ptStr}</span>`);
    }
  }
  const chipsRow = chips.length ? `<div class="summary-chips">${chips.join("")}</div>` : "";
  // 领涨板块 top3（与 renderSummaryChips 同款样式，复用 term-tip 事件委托）
  let topRow = "";
  if (snap.industries && snap.industries.length) {
    const top3 = [...snap.industries].sort((a, b) => (b.pct_change ?? -999) - (a.pct_change ?? -999)).slice(0, 3);
    const parts = top3.map((d) => {
      const nm = (d.sw_name || d.name || "").replace("SW ", "");
      const pc = d.pct_change;
      const color = pc != null ? (pc >= 0 ? "#e6492e" : "#2e8b57") : "var(--text-2)";
      const sign = pc != null && pc >= 0 ? "+" : "";
      const pcStr = pc != null ? `(${sign}${pc.toFixed(2)}%)` : "";
      let flowStr = "";
      if (d.net_inflow != null) {
        const fColor = d.net_inflow >= 0 ? "#e6492e" : "#2e8b57";
        const fSign = d.net_inflow >= 0 ? "+" : "";
        flowStr = ` <span style="color:${fColor}">💰${fSign}${d.net_inflow.toFixed(1)}亿</span>`;
      }
      return `<span style="color:${color}">${nm}${pcStr}</span>${flowStr}`;
    });
    topRow = `<div class="summary-chips summary-chips-top"><span class="term-tip" data-tip="领涨板块按涨跌幅排序；💰为该行业当日资金净流入(亿元)，正值=资金流入(红)，负值=流出(绿)">🔥领涨❓</span>${parts.join("、")}</div>`;
  }
  // 领跌板块 bottom3（升序，与 renderSummaryChips 同款样式，复用 term-tip 事件委托）
  let bottomRow = "";
  if (snap.industries && snap.industries.length) {
    const bottom3 = [...snap.industries].sort((a, b) => (a.pct_change ?? 999) - (b.pct_change ?? 999)).slice(0, 3);
    const parts = bottom3.map((d) => {
      const nm = (d.sw_name || d.name || "").replace("SW ", "");
      const pc = d.pct_change;
      const color = pc != null ? (pc >= 0 ? "#e6492e" : "#2e8b57") : "var(--text-2)";
      const sign = pc != null && pc >= 0 ? "+" : "";
      const pcStr = pc != null ? `(${sign}${pc.toFixed(2)}%)` : "";
      let flowStr = "";
      if (d.net_inflow != null) {
        const fColor = d.net_inflow >= 0 ? "#e6492e" : "#2e8b57";
        const fSign = d.net_inflow >= 0 ? "+" : "";
        flowStr = ` <span style="color:${fColor}">💰${fSign}${d.net_inflow.toFixed(1)}亿</span>`;
      }
      return `<span style="color:${color}">${nm}${pcStr}</span>${flowStr}`;
    });
    bottomRow = `<div class="summary-chips summary-chips-top"><span class="term-tip" data-tip="领跌板块按涨跌幅倒序排序；💰为该行业当日资金净流入(亿元)，正值=资金流入(红)，负值=流出(绿)">❄领跌❓</span>${parts.join("、")}</div>`;
  }
  return chipsRow + topRow + bottomRow;
}

// ============ 当日分时图（腾讯分时API直拉 + 3分钟动态刷新）============
// CORS 已确认：腾讯分时API access-control-allow-origin:*，前端可直拉。
// 盘中每3分钟刷新分时走势；收盘后默认收起，点按钮按需展开。
// 海外指数盘中无分时（时差），维持T+1现状不动态。

// 指数ID -> 腾讯分时API code 映射（复用现有指数ID体系：sh/sz/hs300/cyb 等）
const _INDEX_TO_TENCENT_MINUTE = {
  sh: "sh000001", sz: "sz399001", hs300: "sh000300", sz50: "sh000016",
  cyb: "sz399006", kc50: "sh000688", bj50: "bj899050",
  csi500: "sh000905", csi1000: "sh000852",
  hsi: "hkHSI", hstech: "hkHSTECH", hscei: "hkHSCEI",
};
// 指数ID -> 市场类型（cn=A股 9:30-11:30/13:00-15:00，hk=港股 9:30-12:00/13:00-16:00）
const _INDEX_MARKET = {};
["sh","sz","hs300","sz50","cyb","kc50","bj50","csi500","csi1000"].forEach((k) => _INDEX_MARKET[k] = "cn");
["hsi","hstech","hscei"].forEach((k) => _INDEX_MARKET[k] = "hk");

// 分时图展示的指数（11个：9 A股 + 2 港股，与 spark-grid 一一对应）
const _INTRADAY_INDICES = [
  { id: "sh", name: "上证指数" },
  { id: "sz", name: "深证成指" },
  { id: "hs300", name: "沪深300" },
  { id: "sz50", name: "上证50" },
  { id: "cyb", name: "创业板指" },
  { id: "kc50", name: "科创50" },
  { id: "bj50", name: "北证50" },
  { id: "csi500", name: "中证500" },
  { id: "csi1000", name: "中证1000" },
  { id: "hsi", name: "恒生指数" },
  { id: "hstech", name: "恒生科技" },
];

const INTRADAY_REFRESH_MS = 3 * 60 * 1000; // 3分钟
const INTRADAY_MAX_FAILS = 3; // 连续失败3次暂停刷新

// 分时fetch in-flight去重（同URL并发只发一次，复用Promise）
const _inflightMinute = new Map();
let _intradayFailCount = 0;
let _intradayRefreshTimer = null;
let _intradayLastFetch = 0;
let _intradayActive = false;
let _intradayRenderCtx = null; // { sparkGrid, snap }
let _intradayVisBound = false;

// ============ 盘中动态值统一（阶段2）：腾讯分时数据驱动卡片badge/横幅chips/采集时间 ============
// 盘中所有"实时数值类"展示（分时图/卡片涨跌幅badge/横幅chips）同源，均由腾讯分时数据驱动（3分钟）。
// snap（30分钟）退居后端职责：反哺日K+重算情绪分+收盘归档，不再驱动前端盘中数值展示。
// _intradayDynamicPct: {sh:{pct,price}, sz:{...}} 腾讯最近一次成功拉取的动态值
// _intradayDynamicTime: "HH:MM" 腾讯最近成功拉取时间（取上证最新分时点时间，无则空）
let _intradayDynamicPct = {};
let _intradayDynamicTime = "";
let _dynamicBadgeIds = [];        // spark-grid 中可映射腾讯code的指数id列表（renderOverview 设置）
let _bannerRenderCtx = null;      // {el, s, snap, type:"intraday"|"summary"} 横幅渲染上下文，刷新时复用
let _collectTimeBase = { ct: "", health: null };

// fetch腾讯分时API，解析返回 {name,price,preClose,pct,date,points:[{time,price,volume,amount}]}
// code参数是项目内指数ID（sh/sz/cyb 等），内部映射到腾讯code（sh000001 等）。
// 异常（fetch失败/解析失败/code!=0/空数据）返回null，调用方走降级。
async function fetchTencentMinute(code) {
  const tcCode = _INDEX_TO_TENCENT_MINUTE[code];
  if (!tcCode) return null;
  const url = "https://web.ifzq.gtimg.cn/appstock/app/minute/query?code=" + tcCode;
  const cached = _inflightMinute.get(url);
  if (cached) return cached;
  const p = (async () => {
    try {
      const resp = await fetch(url);
      const json = await resp.json();
      if (!json || json.code !== 0 || !json.data) return null;
      const node = json.data[tcCode];
      if (!node || !node.data || !node.data.data) return null;
      const rawPts = node.data.data;
      const date = node.data.date || "";
      const points = [];
      for (const line of rawPts) {
        const parts = String(line).split(" ");
        if (parts.length < 2) continue;
        const hhmm = parts[0];
        const time = hhmm.length === 4 ? hhmm.slice(0, 2) + ":" + hhmm.slice(2) : hhmm;
        const price = parseFloat(parts[1]);
        if (isNaN(price)) continue;
        const volume = parts[2] ? parseInt(parts[2], 10) || 0 : 0;
        const amount = parts[3] ? parseFloat(parts[3]) || 0 : 0;
        points.push({ time, price, volume, amount });
      }
      if (!points.length) return null;
      // qt: [1]=名称 [3]=当前价 [4]=昨收
      const qt = node.qt && node.qt[tcCode];
      const name = qt && qt[1] ? qt[1] : "";
      const curPrice = qt && qt[3] ? parseFloat(qt[3]) : points[points.length - 1].price;
      const preClose = qt && qt[4] ? parseFloat(qt[4]) : null;
      const pct = preClose && curPrice ? ((curPrice - preClose) / preClose) * 100 : null;
      return { name, price: curPrice, preClose, pct, date, points };
    } catch (e) { return null; }
  })();
  _inflightMinute.set(url, p);
  p.finally(() => _inflightMinute.delete(url));
  return p;
}

// 从snap提取HH:MM时间（取sh000001的datetime末尾4位）
function _snapTimeStr(snap) {
  if (!snap || !snap.indices) return "";
  const sh = snap.indices.find((i) => i.code === "sh000001");
  if (!sh || !sh.datetime) return "";
  return sh.datetime.slice(8, 10) + ":" + sh.datetime.slice(10, 12);
}

// 从snap获取指数preClose（snap.indices的code是sh000001等腾讯code）
function _snapPreClose(snap, code) {
  const tcCode = _INDEX_TO_TENCENT_MINUTE[code] || "";
  const idx = snap && snap.indices ? snap.indices.find((i) => i.code === tcCode) : null;
  return idx ? idx.pre_close : null;
}

// 取某指数的腾讯动态pct（无则null），供 badge/chips 复用
function _dynPct(id) {
  const d = _intradayDynamicPct[id];
  return d && d.pct != null ? d.pct : null;
}
function _dynPrice(id) {
  const d = _intradayDynamicPct[id];
  return d && d.price != null ? d.price : null;
}

// 并行拉取多个指数的腾讯动态值（复用 fetchTencentMinute 的 in-flight 去重，不重复请求）。
// 成功更新 _intradayDynamicPct/_intradayDynamicTime，返回 {results, ok}。
async function _fetchDynamicPcts(ids) {
  const valid = (ids || []).filter((id) => _INDEX_TO_TENCENT_MINUTE[id]);
  if (!valid.length) return { results: {}, ok: false };
  const pairs = await Promise.all(valid.map((id) => fetchTencentMinute(id).then((r) => [id, r])));
  const results = {};
  for (const [id, r] of pairs) {
    if (r && r.pct != null) {
      results[id] = r;
      _intradayDynamicPct[id] = { pct: r.pct, price: r.price };
      if (id === "sh" && r.points && r.points.length) {
        const t = r.points[r.points.length - 1].time;
        if (t) _intradayDynamicTime = t;
      }
    }
  }
  return { results, ok: Object.keys(results).length > 0 };
}

// 更新所有 spark-grid 卡片涨跌幅 badge 为腾讯动态值（无动态值时保持原值不闪烁，静默回退）
function _applyDynamicToBadges(results) {
  document.querySelectorAll(".pct-badge[data-spark-id]").forEach((el) => {
    const id = el.getAttribute("data-spark-id");
    const r = (results && results[id]) || _intradayDynamicPct[id];
    if (!r || r.pct == null) return; // 静默回退：保持原值
    if (!el.hasAttribute("data-snap-txt")) {
      el.setAttribute("data-snap-txt", el.textContent);
      el.setAttribute("data-snap-color", el.style.color || "");
    }
    const pct = r.pct;
    const color = pct >= 0 ? "#e6492e" : "#2e8b57";
    const sign = pct >= 0 ? "+" : "";
    el.style.color = color;
    el.textContent = `${sign}${pct.toFixed(2)}%`;
    el.classList.add("dyn-updated");
  });
}

// 重渲染横幅 chips（盘中用动态值覆盖指数chip）
function _applyDynamicToChips(snap) {
  if (!_bannerRenderCtx || !_bannerRenderCtx.el) return;
  const host = _bannerRenderCtx.el.querySelector("#banner-chips-host");
  if (!host) return;
  const { s, type } = _bannerRenderCtx;
  if (type === "intraday") {
    host.innerHTML = renderIntradayChips(snap); // renderIntradayChips 内部优先读 _intradayDynamicPct
  } else {
    host.innerHTML = renderSummaryChips(s, snap);
  }
}

// 更新横幅时间标签 + 采集时间后缀（盘中用腾讯时间，收盘用snap时间）
function _applyDynamicToBannerTime(snap) {
  if (_bannerRenderCtx && _bannerRenderCtx.el) {
    const tl = _bannerRenderCtx.el.querySelector("#banner-time-label");
    if (tl) {
      const intraday = snap && snap.is_closed === false;
      const _lunch = snap && snap.label && /午休/.test(snap.label);
      const t = _intradayDynamicTime || _snapTimeStr(snap);
      if (intraday && !_lunch) tl.textContent = `更新于 ${t}`;
      else if (intraday && _lunch) tl.textContent = "13:00复牌";
      else tl.textContent = `收盘快照 · ${t}`;
    }
  }
  _renderCollectTime(); // 采集时间后缀随动态时间更新
}

// 一轮动态值刷新：拉取 + 应用到 badge/chips/时间（盘中调用）
async function _refreshDynamicAll(snap) {
  if (!snap || snap.is_closed !== false) return { results: {}, ok: false };
  const ids = _dynamicBadgeIds && _dynamicBadgeIds.length
    ? _dynamicBadgeIds
    : _INTRADAY_INDICES.map((i) => i.id);
  const { results } = await _fetchDynamicPcts(ids);
  _applyDynamicToBadges(results);
  _applyDynamicToChips(snap);
  _applyDynamicToBannerTime(snap);
  return { results, ok: Object.keys(results).length > 0 };
}

// 收盘：清空动态值缓存，badge/chips/采集时间恢复读 overview/snap 收盘值
function _onMarketClosed() {
  _intradayDynamicPct = {};
  _intradayDynamicTime = "";
  // badge 恢复原值（overview 的 pct_change）
  document.querySelectorAll(".pct-badge.dyn-updated").forEach((el) => {
    const txt = el.getAttribute("data-snap-txt");
    const col = el.getAttribute("data-snap-color");
    if (txt != null) el.textContent = txt;
    if (col != null) el.style.color = col;
    el.classList.remove("dyn-updated");
  });
  const snap = state.intradaySnapshot;
  if (_bannerRenderCtx) {
    _applyDynamicToChips(snap);
    _applyDynamicToBannerTime(snap);
    const p = _bannerRenderCtx.el.querySelector("#banner-pulse");
    if (p) p.remove();
  }
  _renderCollectTime();
}

// 分时图拉取失败的降级提示
function _renderIntradayFail(container, snapTime) {
  if (!container || !container.isConnected) return;
  const old = echarts.getInstanceByDom(container);
  if (old) { old.dispose(); const i = charts.indexOf(old); if (i >= 0) charts.splice(i, 1); }
  container.innerHTML = '<div class="intraday-fail">实时拉取失败' + (snapTime ? "·显示快照 " + snapTime : "") + "</div>";
}

// 渲染单个指数分时图。返回 Promise<boolean>（true=成功 false=失败）
function _renderIntradayChart(container, code, preClose, snapTime) {
  if (!container || !container.isConnected) return Promise.resolve(false);
  return fetchTencentMinute(code).then((result) => {
    if (!container.isConnected) return false;
    if (!result || !result.points || !result.points.length) {
      _renderIntradayFail(container, snapTime);
      return false;
    }
    // 复用本次拉取填充动态值缓存（badge/chips/采集时间共用，避免重复请求）
    if (result.pct != null) {
      _intradayDynamicPct[code] = { pct: result.pct, price: result.price };
      if (code === "sh" && result.points && result.points.length) {
        const t = result.points[result.points.length - 1].time;
        if (t) _intradayDynamicTime = t;
      }
    }
    // dispose 旧实例避免内存泄漏
    const old = echarts.getInstanceByDom(container);
    if (old) { old.dispose(); const i = charts.indexOf(old); if (i >= 0) charts.splice(i, 1); }
    container.innerHTML = "";
    const pc = preClose || result.preClose;
    const lastPrice = result.points[result.points.length - 1].price;
    const up = pc != null ? lastPrice >= pc : true;
    const color = up ? "#e6492e" : "#2e8b57"; // 红涨绿跌（中国风）
    const times = result.points.map((p) => p.time);
    const prices = result.points.map((p) => p.price);
    // 午休边界：找最后午前点和首个午后点，markArea标注午休
    let morningLast = null, afternoonFirst = null;
    for (const p of result.points) {
      if (p.time < "13:00") morningLast = p.time;
      else if (!afternoonFirst) { afternoonFirst = p.time; break; }
    }
    const markAreaData = (morningLast && afternoonFirst && morningLast !== afternoonFirst)
      ? [[{ xAxis: morningLast }, { xAxis: afternoonFirst }]] : [];
    const chart = echarts.init(container);
    chart.setOption(withTheme({
      grid: { left: 38, right: 6, top: 8, bottom: 18 },
      xAxis: {
        type: "category", data: times, boundaryGap: false,
        axisLabel: { interval: Math.max(1, Math.floor(times.length / 4)), fontSize: 10 },
      },
      yAxis: {
        type: "value", scale: true, splitNumber: 2,
        axisLabel: { fontSize: 10, formatter: (v) => v.toFixed(0) },
      },
      tooltip: {
        trigger: "axis",
        formatter: (p) => {
          if (!p[0]) return "";
          const price = p[0].value != null ? Number(p[0].value) : NaN;
          let line = p[0].axisValue + "<br/>" + (isNaN(price) ? "-" : price.toFixed(2));
          if (pc != null && !isNaN(price)) {
            const diff = price - pc;
            const pct = (diff / pc) * 100;
            const up = diff >= 0;
            const color = up ? "#e6492e" : "#2e8b57";
            const sign = up ? "+" : "";
            line += `<br/><span style="color:${color}">涨跌 ${sign}${diff.toFixed(2)}</span>`;
            line += `<br/><span style="color:${color}">幅度 ${sign}${pct.toFixed(2)}%</span>`;
          }
          return line;
        },
      },
      series: [{
        type: "line", data: prices, symbol: "none", connectNulls: false,
        lineStyle: { color, width: 1.2 }, areaStyle: { color, opacity: 0.1 },
        // 昨收基准横虚线
        markLine: pc != null ? {
          symbol: "none", silent: true,
          lineStyle: { type: "dashed", color: cssVar("--text-3"), width: 1 },
          data: [{ yAxis: pc, label: { formatter: "昨收", position: "end", fontSize: 9, color: cssVar("--text-3") } }],
        } : undefined,
        // 午休灰色横条标注
        markArea: markAreaData.length ? {
          silent: true, itemStyle: { color: "rgba(128,128,128,0.08)" },
          label: { show: true, position: "insideTop", formatter: "午休", fontSize: 9, color: cssVar("--text-4") },
          data: markAreaData,
        } : undefined,
      }],
    }));
    charts.push(chart);
    return true;
  }).catch(() => { _renderIntradayFail(container, snapTime); return false; });
}

// 渲染分时图到 spark-cell 内的 .spark-intraday 容器（仅渲染可见容器）
function _renderIntradayInSparkCells(sparkGrid, snap) {
  if (!sparkGrid || !sparkGrid.isConnected) return;
  const snapTime = _snapTimeStr(snap);
  const containers = sparkGrid.querySelectorAll(".spark-intraday[data-intraday-code]:not(.collapsed)");
  containers.forEach((el) => {
    const code = el.getAttribute("data-intraday-code");
    if (!_INDEX_TO_TENCENT_MINUTE[code]) return;
    const preClose = _snapPreClose(snap, code);
    _renderIntradayChart(el, code, preClose, snapTime);
  });
}

// 分时图主入口：分时图嵌入 spark-cell 内，全局切换按钮控制显隐
function renderIntradaySection(sparkGrid, snap) {
  const isClosed = !snap || snap.is_closed !== false;
  // 默认展开：盘中=true 盘后=false；localStorage 记忆覆盖
  let lsExpanded = null;
  try { lsExpanded = localStorage.getItem("intraday-chart-expanded"); } catch (e) {}
  const defaultExpanded = isClosed ? false : true;
  const expanded = lsExpanded === null ? defaultExpanded : lsExpanded === "1";

  // 全局切换按钮（控制所有 .spark-intraday 显隐）
  const toggle = document.createElement("button");
  toggle.className = "intraday-toggle" + (expanded ? " expanded" : "");
  const pulseHtml = isClosed ? "" : '<span class="dyn-pulse"><span class="dyn-pulse-dot"></span>3min</span>';
  toggle.innerHTML = (expanded ? "📊 收起分时图" : "📊 显示分时图") + pulseHtml;
  sparkGrid.parentElement.insertBefore(toggle, sparkGrid);

  toggle.onclick = () => {
    const nowExpanded = !toggle.classList.contains("expanded");
    toggle.classList.toggle("expanded", nowExpanded);
    toggle.innerHTML = (nowExpanded ? "📊 收起分时图" : "📊 显示分时图") +
      (isClosed ? "" : '<span class="dyn-pulse"><span class="dyn-pulse-dot"></span>3min</span>');
    sparkGrid.querySelectorAll(".spark-intraday[data-intraday-code]").forEach((el) => {
      el.classList.toggle("collapsed", !nowExpanded);
      // 展开时若容器为空才渲染（避免重复渲染）
      if (nowExpanded && !el.querySelector("div")) {
        const code = el.getAttribute("data-intraday-code");
        if (code && _INDEX_TO_TENCENT_MINUTE[code]) {
          const preClose = _snapPreClose(snap, code);
          const snapTime = _snapTimeStr(snap);
          _renderIntradayChart(el, code, preClose, snapTime);
        }
      }
    });
    try { localStorage.setItem("intraday-chart-expanded", nowExpanded ? "1" : "0"); } catch (e) {}
  };

  // 初始状态：collapsed 类控制显隐
  if (!expanded) {
    sparkGrid.querySelectorAll(".spark-intraday[data-intraday-code]").forEach((el) => el.classList.add("collapsed"));
  } else {
    _renderIntradayInSparkCells(sparkGrid, snap);
  }

  // 盘中启动3分钟动态刷新（无论展开与否，badge/chips 都需刷新）
  if (!isClosed) {
    _intradayRenderCtx = { sparkGrid, snap };
    _startIntradayRefresh();
  }

  // 连续失败暂停提示（隐藏，3次失败时显示）
  const notice = document.createElement("div");
  notice.className = "intraday-notice";
  notice.textContent = "⚠ 实时拉取连续失败，已暂停刷新。可刷新页面重试。";
  notice.style.display = "none";
  sparkGrid.parentElement.insertBefore(notice, sparkGrid.nextSibling);
}

// 启动3分钟动态刷新（setTimeout递归，避免tab隐藏时堆积）
function _startIntradayRefresh() {
  _stopIntradayRefresh();
  _intradayActive = true;
  _intradayFailCount = 0;
  _intradayLastFetch = Date.now();
  _scheduleNextRefresh();
  if (!_intradayVisBound) {
    _intradayVisBound = true;
    document.addEventListener("visibilitychange", _onIntradayVisChange);
  }
}

// 停止刷新（切tab/收盘时调用）
function _stopIntradayRefresh() {
  _intradayActive = false;
  _intradayRenderCtx = null;
  _bannerRenderCtx = null; // 横幅已随 tab 切换移除，置空避免操作已分离 DOM
  if (_intradayRefreshTimer) { clearTimeout(_intradayRefreshTimer); _intradayRefreshTimer = null; }
}

// 调度下次刷新（不可见时跳过但重新调度，不堆积）
function _scheduleNextRefresh() {
  if (!_intradayActive) return;
  if (_intradayFailCount >= INTRADAY_MAX_FAILS) return;
  if (_intradayRefreshTimer) clearTimeout(_intradayRefreshTimer);
  _intradayRefreshTimer = setTimeout(() => {
    _intradayRefreshTimer = null;
    if (!_intradayActive) return;
    if (document.hidden) { _scheduleNextRefresh(); return; } // 页面不可见时跳过
    _doIntradayRefresh();
  }, INTRADAY_REFRESH_MS);
}

// 执行一轮刷新：并行refetch所有图表，跟踪成功/失败
async function _doIntradayRefresh() {
  if (!_intradayRenderCtx || !_intradayRenderCtx.sparkGrid) { _scheduleNextRefresh(); return; }
  const ctx = _intradayRenderCtx;
  _intradayLastFetch = Date.now();
  // 刷新snap检查是否收盘（2s超时避免阻塞）
  _intradaySnapPromise = null;
  try { await Promise.race([fetchIntradaySnapshot(), new Promise((r) => setTimeout(r, 2000))]); } catch (e) {}
  const curSnap = state.intradaySnapshot || ctx.snap;
  if (curSnap && curSnap.is_closed === true) {
    _onMarketClosed(); // 先恢复 badge/chips/时间为收盘态（需 _bannerRenderCtx 未置空）
    _stopIntradayRefresh();
    return;
  }
  ctx.snap = curSnap;
  const snapTime = _snapTimeStr(curSnap);
  // 并发：动态值拉取（badge/chips/时间用）与分时图重绘
  // （共用 fetchTencentMinute in-flight 去重，11 指数只发一次请求，不重复）
  const dynP = _refreshDynamicAll(curSnap);
  const promises = [];
  const chartEls = ctx.sparkGrid.querySelectorAll(".spark-intraday[data-intraday-code]:not(.collapsed)");
  chartEls.forEach((chartEl) => {
    const code = chartEl.getAttribute("data-intraday-code");
    const preClose = _snapPreClose(curSnap, code);
    promises.push(_renderIntradayChart(chartEl, code, preClose, snapTime));
  });
  const results = await Promise.all(promises);
  const dynResult = await dynP; // 确保 badge/chips 已更新
  // 判断成功：有分时图渲染成功 OR 动态值拉取成功（分时图全收起时靠动态值判断）
  const anyOk = results.length > 0 ? results.some((r) => r) : (dynResult && dynResult.ok);
  if (anyOk) {
    _intradayFailCount = 0;
  } else {
    _intradayFailCount++;
    if (_intradayFailCount >= INTRADAY_MAX_FAILS) {
      const notice = ctx.sparkGrid.parentElement.querySelector(".intraday-notice");
      if (notice) notice.style.display = "";
      return; // 暂停刷新，不再调度
    }
  }
  _scheduleNextRefresh();
}

// visibilitychange：切回tab且距上次>3分钟时立即刷新
function _onIntradayVisChange() {
  if (document.hidden || !_intradayActive) return;
  if (Date.now() - _intradayLastFetch >= INTRADAY_REFRESH_MS) {
    _doIntradayRefresh();
  } else if (!_intradayRefreshTimer) {
    _scheduleNextRefresh();
  }
}

// ============ 🐶 汪汪队首页卡片：近期信号列表 + 点击弹 day modal ============
// 复用 _renderSignalGrid 骨架（按日分组·降序·今日高亮）+ 全局 _initTermPop hover pop（加 data-tip 即生效）。
// 整卡不跳转：chip click 弹当日 per-ETF 信号明细 modal（openNtDayModal）。
const NT_SIG_COLOR = { share_surge: "#e6492e", share_outflow: "#2e8b57", volume_surge: "#ff9800" };
const NT_SIG_CLASS = { share_surge: "nt-surge", share_outflow: "nt-outflow", volume_surge: "nt-volume" };
const NT_ORDER = ["share_surge", "share_outflow", "volume_surge"];
const NT_LABEL = { share_surge: "进", share_outflow: "出", volume_surge: "量" };
var _ntRecentDaily = null;  // 缓存首页 nt.recent.daily，供 openNtDayModal 取当日 signals[]

// HTML 属性转义（data-tip 值含中文/括号/逗号，转义 " & < 防属性截断）
function _escAttr(s) {
  return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
}

// 首页🐶卡片近期信号列表：每日一行=日期+共振🐾+chips（进/出/量 各一个 chip，显示当日该类型只数）。
// chip 带 data-tip（当日该类型 ETF 明细，hover pop 全局 _initTermPop 自动生效）+
// data-nt-date/data-nt-type（点击弹 openNtDayModal）。daily 升序传入，内部降序渲染，今日高亮。
function _renderNtSignalList(daily, todayDate) {
  if (!daily || !daily.length) return '<div class="empty-note">近期无汪汪队信号</div>';
  const sorted = daily.slice().sort((a, b) => (a.date < b.date ? 1 : -1));
  if (todayDate) sorted.sort((a, b) => (a.date === todayDate ? -1 : b.date === todayDate ? 1 : 0));
  let rows = "";
  for (const d of sorted) {
    const isToday = d.date === todayDate;
    const resMark = d.is_resonance
      ? '<span class="nt-day-resonance" data-tip="共振日：进/出≥2只或量≥3只宽基同日同步异动">🐾</span>'
      : '';
    const sigs = d.signals || [];
    let chips = "";
    for (const st of NT_ORDER) {
      const cnt = st === "share_surge" ? d.n_surge : st === "share_outflow" ? d.n_outflow : d.n_volume;
      if (!cnt) continue;
      const grp = sigs.filter((s) => s.type === st);
      // data-tip：当日该类型 ETF 明细（简称+份额变动亿+note），截断前3只+"等N只"
      const tipParts = grp.slice(0, 3).map((s) => {
        const sc = s.share_change_yi != null
          ? (s.share_change_yi >= 0 ? "+" : "") + s.share_change_yi + "亿" : "";
        const note = s.note ? "（" + s.note + "）" : "";
        return s.name + sc + note;
      });
      if (grp.length > 3) tipParts.push("等" + grp.length + "只");
      const tip = NT_LABEL[st] + cnt + "只：" + tipParts.join("、");
      // chip 内联加该类聚合指标：进/出→净流入/净流出(亿)，量→放量倍数
      let suffix = "";
      if (grp.length) {
        if (st === "share_surge" || st === "share_outflow") {
          let tot = 0, has = false;
          for (const s of grp) { const v = s.share_change_yi; if (v != null && isFinite(v)) { tot += v; has = true; } }
          if (has) suffix = st === "share_surge" ? " 净流入" + tot.toFixed(1) + "亿" : " 净流出" + Math.abs(tot).toFixed(1) + "亿";
        } else if (st === "volume_surge") {
          let sum = 0, n = 0;
          for (const s of grp) { const v = s.amount_ratio; if (v != null && isFinite(v)) { sum += v; n++; } }
          if (n) suffix = " 放量" + (sum / n).toFixed(1) + "倍";
        }
      }
      chips +=
        '<span class="sig-item sig-clickable" data-nt-date="' + d.date + '" data-nt-type="' + st + '" ' +
        'data-tip="' + _escAttr(tip) + '" title="点击查看当日明细">' +
        '<b class="' + NT_SIG_CLASS[st] + '">' + NT_LABEL[st] + cnt + suffix + '</b></span>';
    }
    if (!chips) chips = '<span class="sig-item nt-day-empty">—</span>';
    rows +=
      '<div class="sig-day-row' + (isToday ? " today-row" : "") + '">' +
        '<span class="sig-day-date">' + fmtDate(d.date) + resMark + '</span>' +
        '<div class="sig-items">' + chips + '</div>' +
      '</div>';
  }
  return rows;
}

// day modal 元素懒创建（复用 rule-modal 骨架，无 period 切换）
var _ntDayModal = null;
function _ntDayModalEl() {
  if (_ntDayModal) return _ntDayModal;
  const modal = document.createElement("div");
  modal.id = "ntDayModal";
  modal.className = "rule-modal hidden";
  modal.innerHTML =
    '<div class="rule-modal-overlay"></div>' +
    '<div class="rule-modal-body nt-day-modal-body">' +
      '<div class="rule-modal-header"><h3 class="nt-day-modal-title">🐶 汪汪队信号明细</h3>' +
      '<button class="rule-modal-close" aria-label="关闭">&times;</button></div>' +
      '<div class="rule-modal-content nt-day-modal-content"></div>' +
    '</div>';
  document.body.appendChild(modal);
  const close = () => closeNtDayModal();
  modal.querySelector(".rule-modal-overlay").addEventListener("click", close);
  modal.querySelector(".rule-modal-close").addEventListener("click", close);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !modal.classList.contains("hidden")) close(); });
  _ntDayModal = modal;
  return modal;
}

function closeNtDayModal() {
  const modal = document.getElementById("ntDayModal");
  if (!modal) return;
  modal.classList.add("hidden");
  document.body.style.overflow = "";
}

// 弹当日 per-ETF 信号明细 modal：从 _ntRecentDaily 取该日 signals[]，分 进/出/量 三组展示。
// 每条 ETF：简称+份额变动亿(着色)+放量倍数+intensity+note。单只ETF点击暂不进 openNtDetailOverlay
// （需额外 fetch 3 个 JSON，复杂；day modal 已展示完整信号明细，满足查看需求）。
function openNtDayModal(date) {
  const modal = _ntDayModalEl();
  const body = modal.querySelector(".nt-day-modal-content");
  const titleEl = modal.querySelector(".nt-day-modal-title");
  const day = _ntRecentDaily ? _ntRecentDaily.find((d) => d.date === date) : null;
  if (!day) {
    titleEl.textContent = "🐶 汪汪队信号明细";
    body.innerHTML = '<div class="empty-note">暂无 ' + fmtDate(date) + ' 的信号明细</div>';
  } else {
    titleEl.innerHTML = '🐶 汪汪队信号明细 · ' + fmtDate(date) +
      (day.is_resonance ? ' <span class="nt-resonance-badge">🐾 共振</span>' : '') +
      ' <span class="nt-day-modal-count">共' + day.total + '信号</span>';
    const sigs = day.signals || [];
    let html = "";
    for (const st of NT_ORDER) {
      const grp = sigs.filter((s) => s.type === st);
      if (!grp.length) continue;
      const color = NT_SIG_COLOR[st];
      html +=
        '<div class="nt-day-group">' +
          '<div class="nt-day-group-hd"><b style="color:' + color + '">' + NT_LABEL[st] + grp.length + '只</b> ' +
          (st === "share_surge" ? "份额增+放量（疑似进场）" : st === "share_outflow" ? "份额减+放量（疑似离场）" : "成交额放量（>5日均2倍）") +
          '</div>';
      for (const s of grp) {
        const sc = s.share_change_yi != null
          ? ' <b style="color:' + color + '">' + (s.share_change_yi >= 0 ? "+" : "") + s.share_change_yi + "亿</b>" : "";
        const ratio = s.amount_ratio != null
          ? ' <span class="nt-day-etf-ratio">放量' + s.amount_ratio.toFixed(2) + "倍</span>" : "";
        const inten = s.intensity != null
          ? ' <span class="nt-day-etf-inten">z=' + s.intensity.toFixed(2) + "</span>" : "";
        const note = s.note ? ' <span class="nt-day-etf-note">' + s.note + "</span>" : "";
        html += '<div class="nt-day-etf"><span class="nt-day-etf-name">' + s.name + "</span>" + sc + ratio + inten + note + "</div>";
      }
      html += "</div>";
    }
    if (!html) html = '<div class="empty-note">该日无信号明细</div>';
    body.innerHTML = html;
  }
  modal.classList.remove("hidden");
  document.body.style.overflow = "hidden";
}

async function renderOverview() {
  // O3：复用 overview 缓存，避免概览/采集时间/分享图重复请求
  const r = _getCachedOverview() || await fetchJSON("./data/overview.json");
  _setCachedOverview(r);
  // 分享按钮旁显示数据采集时间（来自 collect_log 最新 run_at）
  applyCollectTime(r.collected_at);
  // 盘中标注：等快照就绪（最多 1.5s），让每张卡片角标判断 714 实时 vs 713 待收盘
  try { await Promise.race([fetchIntradaySnapshot(), new Promise((res) => setTimeout(res, 1500))]); } catch {}
  const snap = state.intradaySnapshot;
  _renderCollectTime(); // snap 就绪后更新采集时间后缀（动态/收盘）
  content.innerHTML = "";
  content.insertAdjacentHTML("beforeend", '<div class="home-purpose-note">💡 <b>一屏看懂全市场</b>:情绪温度计(冷热)+市场宽度(涨跌家数/新高新低)+估值位置(历史分位)+买卖信号,综合判断当前情绪偏冷(贪婪区)还是偏热(恐惧区)。</div>');
  // 数据时效栏已移入"数据更新规则"弹窗（ℹ️ 图标入口），首页不再展示健康横幅。

  // ---- 0. 一句话总结横幅 ----
  fetchJSON("./data/summary.json").then(async (s) => {
    if (s && s.summary) {
      if (state.tab !== 'overview') return; // A2: await 期间用户切了 tab，回调回来不再渲染 overview 横幅
      // 等快照就绪（已在 bootstrap 发起，最多等 1.5s 避免阻塞渲染），保证 T+1 缺数据时能覆盖
      try { await Promise.race([fetchIntradaySnapshot(), new Promise((r) => setTimeout(r, 1500))]); } catch {}
      const snap = state.intradaySnapshot;
      if (snap && snap.indices) {
        s.summary = injectSnapshotToSummary(s.summary, s, snap);
        s.summary_short = injectSnapshotToSummary(s.summary_short, s, snap);
      }
      // 同日判断：summary 是 T-1 收盘、snap 是 T 盘中时，横幅改用 snap 实时数据，避免标题/数据日期错位
      const snapShIdx = snap && snap.indices ? snap.indices.find((i) => i.code === "sh000001") : null;
      const snapDate = snapShIdx ? (snapShIdx.datetime || "").slice(0, 8) : "";
      const isSameDay = !snapDate || !s.date || snapDate === s.date;
      const intradayMismatched = snap && snap.is_closed === false && !isSameDay;
      const banner = document.createElement("div");
      banner.className = "summary-banner";
      if (intradayMismatched) {
        // 盘中横幅：summary 是 T-1，改用 snap T 日实时数据（标题日期/chips 均来自 snap）
        const datePrefix = snapDate && snapDate.length === 8
          ? `${parseInt(snapDate.substring(4, 6), 10)}月${parseInt(snapDate.substring(6, 8), 10)}日` : "";
        const hhmm = snapShIdx && snapShIdx.datetime ? `${snapShIdx.datetime.slice(8, 10)}:${snapShIdx.datetime.slice(10, 12)}` : "";
        const _lunch = snap && snap.label && /午休/.test(snap.label);
        const titleText = `📊 ${datePrefix} ${_lunch ? "午休" : "盘中动态"} A股`.replace(/\s+/g, " ").trim();
        const snapBadge = `<span class="summary-snap-tag" style="color:#e6a23c">⏰ ${_lunch ? "午休小结" : "盘中动态小结"}</span>`;
        const _tLabel = _lunch ? "13:00复牌" : `更新于 ${_intradayDynamicTime || hhmm}`;
        const _pulse = '<span class="dyn-pulse" id="banner-pulse"><span class="dyn-pulse-dot"></span>3min</span>';
        banner.innerHTML = `<div class="summary-top"><span class="summary-title"><span class="summary-title-text">${titleText}</span></span><span class="summary-meta">${snapBadge}<span class="summary-time-label" id="banner-time-label">${_tLabel}</span>${_pulse}<button class="summary-history-btn" title="查看历史收盘分析">📜 更多</button></span></div><div id="banner-chips-host">${renderIntradayChips(snap)}</div>`;
        _bannerRenderCtx = { el: banner, s: null, snap, type: "intraday" };
      } else {
        // 收盘后/同日：原逻辑（标题用 summary.generated_at，chips 用 summary+snap 同日覆盖）
        const _lunch2 = snap && snap.label && /午休/.test(snap.label);
        const _intraday2 = snap && snap.is_closed === false;
        const _tTime2 = _intradayDynamicTime || _snapTimeStr(snap);
        let snapBadge = "";
        if (snap && snap.indices) {
          if (snap.is_closed) {
            snapBadge = `<span class="summary-snap-tag" style="color:var(--text-3)">📍 收盘小结</span>`;
          } else if (_lunch2) {
            snapBadge = `<span class="summary-snap-tag" style="color:#e6a23c">⏰ 午休小结</span>`;
          } else {
            snapBadge = `<span class="summary-snap-tag" style="color:#e6a23c">⏰ 盘中动态小结</span>`;
          }
        }
        let _tLabel2;
        if (snap && snap.is_closed) _tLabel2 = `收盘快照 · ${_tTime2}`;
        else if (_lunch2) _tLabel2 = "13:00复牌";
        else if (_intraday2) _tLabel2 = `更新于 ${_tTime2}`;
        else _tLabel2 = (s.generated_at || "").replace(/^\d+月\d+日\s*/, "").trim();
        const _pulse2 = _intraday2 ? '<span class="dyn-pulse" id="banner-pulse"><span class="dyn-pulse-dot"></span>3min</span>' : "";
        const freezeBadge = s.is_freeze ? `<span class="summary-freeze">❄️ 冰点</span>` : "";
        const fgBadge = s.fear_greed_label ? `<span class="summary-fg-tag">😐 ${s.fear_greed_label} ${s.fear_greed_value?.toFixed(0) || ""}</span>` : "";
        const genAt = s.generated_at || "";
        const dm = genAt.match(/^(\d+月\d+日)/);
        let datePrefix = dm ? dm[1] : "";
        if (!datePrefix && s.date && s.date.length === 8) {
          datePrefix = `${parseInt(s.date.substring(4, 6), 10)}月${parseInt(s.date.substring(6, 8), 10)}日`;
        }
        const titleText = `📊 ${datePrefix}`.replace(/\s+/g, " ").trim();
        const sentimentBadge = s.sentiment_label ? `<span class="summary-fg-tag">${s.sentiment_label}</span>` : "";
        // 情绪标签+恐贪标签移到第二行(与 summary-meta 同行),行1只留日期标题
        const titleTags = (sentimentBadge || fgBadge || freezeBadge) ? `${sentimentBadge}${fgBadge}${freezeBadge}` : "";
        banner.innerHTML = `<div class="summary-top"><span class="summary-title"><span class="summary-title-text">${titleText}</span>${titleTags ? `<span class="summary-title-tags">${titleTags}</span>` : ""}</span><span class="summary-meta">${snapBadge}<span class="summary-time-label" id="banner-time-label">${_tLabel2}</span>${_pulse2}<button class="summary-history-btn" title="查看历史收盘分析">📜 更多</button></span></div><div id="banner-chips-host">${renderSummaryChips(s, snap)}</div>`;
        _bannerRenderCtx = { el: banner, s, snap, type: "summary" };
      }
      content.insertBefore(banner, content.firstChild);
      const histBtn = banner.querySelector(".summary-history-btn");
      if (histBtn) histBtn.addEventListener("click", openSummaryHistoryModal);
    }
  }).catch(() => {});

  let _secIdx = 0;
  const _SEC_NUMS = ["①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨", "⑩"];
  const sectionTitle = (text) => {
    const h = document.createElement("div");
    h.className = "section-title";
    h.textContent = (_SEC_NUMS[_secIdx] || (_secIdx + 1) + ".") + " " + text;
    _secIdx++;
    content.appendChild(h);
  };

  // KPI 指标值格式化
  const fmtMetric = (m) => {
    if (m.value == null) return "-";
    const v = m.value;
    switch (m.id) {
      case "a_width_zhaban_rate": return (v * 100).toFixed(1) + "%"; // 存储为 0-1 小数
      case "a_width_zt_count":
      case "a_width_dt_count":
      case "a_width_up_count":
      case "a_width_down_count": return v.toFixed(0);
      case "a_amount":
      case "a_fund_margin": return v.toFixed(0);
      case "a_fund_north": return (v >= 0 ? "+" : "") + v.toFixed(1);
      case "a_volume_ratio": return v.toFixed(2) + "x";
      default: return v.toFixed(2);
    }
  };

  // ---- 1. 基础数据区（置顶）：KPI 卡片行 + 指数 sparkline 网格 ----
  // 散户最先看的行情速览：涨停/跌停/成交额/情绪分 等 KPI + 10 大指数迷你走势
  const scoreNames = { a_sentiment: "A股综合情绪分", cross_market: "跨市场综合评分", fear_greed: "恐贪指数" };
  const kpiCards = [];
  for (const [id, s] of Object.entries(r.today.scores || {})) {
    kpiCards.push({
      id: id,
      title: scoreNames[id] || indexIdToName(id),
      value: s.value != null ? s.value.toFixed(1) : "-",
      valueNum: s.value,
      sub: "0-100",
      date: s.date || r.date,
      tag: s.is_freeze ? "冰点" : s.is_overheat ? "过热" : "",
    });
  }
  for (const m of r.today.metrics || []) {
    if (isStaleMetric(m.date, r.date)) continue;  // 停更指标隐藏（如北向资金 2024-08 起停更），恢复更新后自动显示
    kpiCards.push({
      id: m.id,
      title: m.name,
      value: fmtMetric(m),
      valueNum: m.value,
      sub: m.unit || "",
      date: m.date,
      tag: "",
      signal: m.signal || "",
      amount: m.amount,
    });
  }
  // ---- A+B 组合默认排序 + 用户拖拽自定义 ----
  // B(核心情绪前置): a_sentiment/cross_market/fear_greed 三张情绪温度计排最前
  // A(异常度优先): 组内带异常 tag(冰点/过热) 或 signal(放量/缩量) 的卡排前
  // 兜底: 原 kpiOrder 顺序
  const _KPI_CORE_SENTIMENT = ["a_sentiment", "cross_market", "fear_greed"];
  const _KPI_BASE_ORDER = {
    a_width_up_count: 1, a_width_down_count: 2, a_width_zt_count: 3, a_width_dt_count: 4, a_width_zhaban_rate: 5,
    a_amount: 6, a_volume_ratio: 7, a_sentiment: 8, cross_market: 9, fear_greed: 10, a_fund_margin: 11, a_fund_north: 12,
  };
  const _kpiIsAbnormal = (k) => {
    if (k.tag === "冰点" || k.tag === "过热") return true;          // 情绪温度计极值
    const sig = k.signal || "";                                     // 量比 放量/缩量
    return sig.startsWith("放量") || sig.startsWith("缩量");
  };
  // A+B 默认:核心情绪组前置(组内异常优先), 其余卡异常优先 + 原顺序兜底
  const _kpiDefaultOrderIds = () => {
    const sortByAb = (arr) => [...arr].sort((a, b) => {
      const aAb = _kpiIsAbnormal(a) ? 0 : 1, bAb = _kpiIsAbnormal(b) ? 0 : 1;
      if (aAb !== bAb) return aAb - bAb;
      return (_KPI_BASE_ORDER[a.id] || 99) - (_KPI_BASE_ORDER[b.id] || 99);
    });
    const core = kpiCards.filter(k => _KPI_CORE_SENTIMENT.includes(k.id));
    const rest = kpiCards.filter(k => !_KPI_CORE_SENTIMENT.includes(k.id));
    return [...sortByAb(core), ...sortByAb(rest)].map(k => k.id);
  };
  // 渲染排序:localStorage 自定义优先(须覆盖所有当前卡 id), 否则 A+B 默认
  const _kpiSortForRender = () => {
    try {
      const custom = JSON.parse(localStorage.getItem("kpiCustomOrder") || "null");
      if (Array.isArray(custom) && custom.length) {
        const idSet = new Set(kpiCards.map(k => k.id));
        const valid = custom.filter(id => idSet.has(id));
        if (valid.length === kpiCards.length) {
          const orderMap = new Map(custom.map((id, i) => [id, i]));
          return [...kpiCards].sort((a, b) => (orderMap.get(a.id) ?? 999) - (orderMap.get(b.id) ?? 999)).map(k => k.id);
        }
      }
    } catch (e) { /* ignore */ }
    return _kpiDefaultOrderIds();
  };
  const _orderedIds = _kpiSortForRender();
  const _idToCard = new Map(kpiCards.map(k => [k.id, k]));
  const _orderedCards = _orderedIds.map(id => _idToCard.get(id)).filter(Boolean);
  const cards = document.createElement("div");
  cards.className = "cards kpi-row";
  for (const k of _orderedCards) {
    const tagCls = k.tag === "冰点" ? "freeze" : k.tag === "过热" ? "overheat" : "stale";
    const tagHtml = k.tag ? ` <span class="tag ${tagCls}">${k.tag}</span>` : "";
    const sentTag = k.id === "a_sentiment" || k.id === "cross_market" ? ` <span class="sentiment-label">${sentimentTag(k.valueNum)}</span>` : "";
    const fgTag = k.id === "fear_greed" ? ` <span class="sentiment-label" style="color:${fearGreedColor(k.valueNum)}">${fearGreedLabel(k.valueNum)}</span>` : "";
    let sub = k.sub || "";
    let valueHtml = k.value;
    if (k.id === "a_volume_ratio") {
      const sig = k.signal || "";
      const isFangliang = sig.startsWith("放量");
      const isSuoliang = sig.startsWith("缩量");
      let sigCls = "";
      if (isFangliang) sigCls = "fangliang";
      else if (isSuoliang) sigCls = "suoliang";
      const sigHtml = sig ? ` <span class="tag ${sigCls}" title="${sig}">${sig}</span>` : "";
      valueHtml = k.value + sigHtml;
      sub = sig || "";
    }
    const _kpiT1 = k.id === "a_fund_margin" || k.id === "a_fund_north";
    const _badge = getCardTimeBadge(k.date, snap, _kpiT1 ? "t1" : "t0", _kpiT1 ? k.id : "");
    const _kpiTips = {
      a_fund_north: "北向资金=借沪深股通买A股的外资。净流入=外资净买入。2024-08起停更,保留历史。",
      a_fund_margin: "沪市融资余额=借钱买A股的杠杆资金。增加=杠杆做多情绪升。T+1。",
      a_fund_main: "主力净流入=大单买入-卖出。正值=大资金净买入,负值=净卖出。",
      a_amount: "沪深京A股成交额。放量=交投活跃,缩量=清淡。",
      a_volume_ratio: "当日成交额/前5日均量。>1.5倍放量,<0.7倍缩量。",
      fear_greed: "综合5类市场情绪等权算的0-100温度计。≤25极度恐惧、≥75极度贪婪。作逆向参考。",
      a_sentiment: "6项A股指标加权算的0-100情绪分。≤20冰点、≥80过热。",
      cross_market: "A股+港股+全球等多维度等权均值0-100。看跨市场整体冷热。",
    };
    const _widthTip = _kpiTips[k.id] ? termTip(_kpiTips[k.id]) : (k.id === "a_width_up_count" || k.id === "a_width_down_count") ? termTip(_WIDTH_CALIBER_TIP) : "";
    const _hasHist = !!KPI_HISTORY_SOURCE[k.id];
    cards.innerHTML += `<div class="card kpi${_badge ? " has-time-badge" : ""}${_hasHist ? " kpi-clickable" : ""}" data-kpi-key="${k.id}"${_hasHist ? ` data-kpi-id="${k.id}"` : ""}>${_badge}<div class="card-title">${k.title}${_widthTip}</div><div class="card-value"><span class="cv-val">${valueHtml}</span><span class="cv-tags">${tagHtml}${sentTag}${fgTag}</span></div><div class="card-sub" title="${sub}">${sub}</div></div>`;
  }
  // 容器级事件委托：点击有历史走势的 KPI 卡弹窗
  cards.addEventListener("click", (e) => {
    const c = e.target.closest(".card.kpi[data-kpi-id]");
    if (!c) return;
    e.preventDefault();
    openKpiDetailModal(c.dataset.kpiId);
  });

  // ---- 重置排序按钮(仅在有自定义顺序时显示) ----
  const kpiHead = document.createElement("div");
  kpiHead.className = "kpi-section-head";
  const resetBtn = document.createElement("button");
  resetBtn.className = "kpi-reset-btn";
  resetBtn.type = "button";
  resetBtn.title = "恢复默认排序";
  resetBtn.textContent = "↺ 重置排序";
  // 按给定 id 顺序原地重排 DOM(appendChild 移动已有节点)
  const _reorderKpiDom = (idOrder) => {
    const map = new Map(idOrder.map((id, i) => [id, i]));
    Array.from(cards.querySelectorAll(".card.kpi[data-kpi-key]"))
      .sort((a, b) => (map.get(a.dataset.kpiKey) ?? 999) - (map.get(b.dataset.kpiKey) ?? 999))
      .forEach(el => cards.appendChild(el));
  };
  const _syncKpiResetBtn = () => {
    let has = false;
    try { has = !!localStorage.getItem("kpiCustomOrder"); } catch (_) {}
    resetBtn.style.display = has ? "" : "none";
  };
  resetBtn.addEventListener("click", () => {
    try { localStorage.removeItem("kpiCustomOrder"); } catch (_) {}
    _reorderKpiDom(_kpiDefaultOrderIds());
    _syncKpiResetBtn();
  });
  kpiHead.appendChild(resetBtn);
  _syncKpiResetBtn();
  content.appendChild(kpiHead);

  // ---- 拖拽自定义排序(桌面端;移动端触屏禁用保持 A+B 默认) ----
  const _kpiCanDrag = !('ontouchstart' in window || navigator.maxTouchPoints > 0);
  let _draggedKpi = null;
  if (_kpiCanDrag) {
    cards.querySelectorAll(".card.kpi").forEach(c => { c.draggable = true; });
    cards.addEventListener("dragstart", (e) => {
      const c = e.target.closest(".card.kpi");
      if (!c) return;
      _draggedKpi = c;
      c.classList.add("dragging");
      e.dataTransfer.effectAllowed = "move";
      try { e.dataTransfer.setData("text/plain", c.dataset.kpiKey || ""); } catch (_) {}
    });
    cards.addEventListener("dragend", () => {
      if (_draggedKpi) _draggedKpi.classList.remove("dragging");
      cards.querySelectorAll(".card.kpi.drag-over").forEach(x => x.classList.remove("drag-over"));
      _draggedKpi = null;
    });
    cards.addEventListener("dragover", (e) => {
      if (!_draggedKpi) return;
      const c = e.target.closest(".card.kpi");
      if (!c) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      cards.querySelectorAll(".card.kpi.drag-over").forEach(x => x.classList.remove("drag-over"));
      if (c !== _draggedKpi) c.classList.add("drag-over");
    });
    cards.addEventListener("drop", (e) => {
      if (!_draggedKpi) return;
      const c = e.target.closest(".card.kpi");
      if (!c || c === _draggedKpi) return;
      e.preventDefault();
      // 鼠标落在目标卡左半=插前, 右半=插后
      const rect = c.getBoundingClientRect();
      const after = (e.clientX - rect.left) > rect.width / 2;
      cards.insertBefore(_draggedKpi, after ? c.nextSibling : c);
      // 持久化新顺序(含全部卡 key)
      const ids = Array.from(cards.querySelectorAll(".card.kpi[data-kpi-key]")).map(x => x.dataset.kpiKey);
      try { localStorage.setItem("kpiCustomOrder", JSON.stringify(ids)); } catch (_) {}
      _syncKpiResetBtn();
    });
  }

  content.appendChild(cards);

  // 指数 sparkline 网格
  const grid = document.createElement("div");
  grid.className = "spark-grid";
  content.appendChild(grid);
  const _sparkDynIds = [];
  for (const [sparkId, idx] of Object.entries(r.indices_sparkline || {})) {
    if (!idx.closes || !idx.closes.length) continue;
    if (_INDEX_TO_TENCENT_MINUTE[sparkId]) _sparkDynIds.push(sparkId);
    const up = (idx.pct_change || 0) >= 0;
    const color = up ? "#e6492e" : "#2e8b57";
    const cell = document.createElement("div");
    cell.className = "spark-cell";
    const sign = up ? "+" : "";
    // 左下角撑高度：最新点位 + 涨跌点数（closes 末两个差值，避免右下角角标覆盖走势图）
    const _lastClose = Number(idx.closes[idx.closes.length - 1]);
    const _prevClose = idx.closes.length >= 2 ? Number(idx.closes[idx.closes.length - 2]) : null;
    const _chgPts = _prevClose != null ? (_lastClose - _prevClose) : null;
    const _chgUp = _chgPts != null && _chgPts >= 0;
    const _chgColor = _chgPts == null ? "var(--text-3)" : (_chgUp ? "#e6492e" : "#2e8b57");
    const _chgText = _chgPts == null ? "- " : ((_chgUp ? "+" : "") + _chgPts.toFixed(2));
    cell.innerHTML = `
      <div class="spark-head">
        <span class="spark-name">${idx.name}</span>
        <span class="pct-badge" data-spark-id="${sparkId}" style="color:${color}">${sign}${(idx.pct_change || 0).toFixed(2)}%</span>
      </div>
      <div class="spark-chart"></div>
      ${_INDEX_TO_TENCENT_MINUTE[sparkId] ? '<div class="spark-intraday" data-intraday-code="' + sparkId + '"></div>' : ''}
      <div class="spark-foot">${_lastClose.toFixed(2)} <span style="color:${_chgColor}">${_chgText}</span></div>`;
    grid.appendChild(cell);
    const chartDom = cell.querySelector(".spark-chart");
    const exist = echarts.getInstanceByDom(chartDom);
    if (exist) exist.dispose();
    const sc = echarts.init(chartDom);
    sc.setOption(withTheme({
      grid: { left: 2, right: 2, top: 4, bottom: 4 },
      xAxis: { type: "category", show: false, data: idx.dates },
      yAxis: { type: "value", show: false, scale: true },
      tooltip: { trigger: "axis", formatter: (p) => `${p[0].axisValue}<br/>${(p[0].value == null || isNaN(Number(p[0].value))) ? "-" : Number(p[0].value).toFixed(2)}` },
      series: [{
        type: "line", smooth: true, symbol: "none", data: idx.closes,
        lineStyle: { color, width: 1.5 }, areaStyle: { color, opacity: 0.12 },
      }],
    }));
    charts.push(sc);
    addCardTimeBadge(cell, idx.last_date, snap, "t0");
  }
  _dynamicBadgeIds = _sparkDynIds;

  // ---- 1b. 当日分时图（嵌入 spark-cell，腾讯分时API直拉，盘中3分钟动态刷新）----
  renderIntradaySection(grid, snap);
  // 盘中：立即拉取腾讯动态值刷新卡片badge/横幅chips/采集时间
  // （与分时图共用 fetchTencentMinute in-flight 去重，11 指数只发一次请求不重复）
  if (snap && snap.is_closed === false) _refreshDynamicAll(snap);

  // ---- 2. 首屏两列：左=恐贪指数+情绪分，右=冰点日+买卖点 ----
  const ov2ColA = document.createElement("div");
  ov2ColA.className = "ov-2col";
  const colA1 = document.createElement("div");
  const colA2 = document.createElement("div");
  ov2ColA.appendChild(colA1);
  ov2ColA.appendChild(colA2);
  content.appendChild(ov2ColA);

  // 左列：恐贪指数折线（近 6 月，visualMap 分段着色）
  if (r.fear_greed_6m && r.fear_greed_6m.length) {
    const fg6 = r.fear_greed_6m.map((d) => ({ date: d.date, value: d.value }));
    const fgChart = lineChart("😐 恐贪指数（近 6 月）" + termTip("综合5类市场情绪算的0-100温度计，越低越恐惧越高越贪婪") + latestSuffix(fg6), fg6, {
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
    if (fgChart) addCardTimeBadge(fgChart.getDom().parentElement, fg6.length ? fg6[fg6.length - 1].date : "", snap, "t0");
  }

  // 左列：A股综合情绪分折线（近 6 月）
  if (r.a_sentiment_6m && r.a_sentiment_6m.length) {
    const as6 = r.a_sentiment_6m.map((d) => ({ date: d.date, value: d.value }));
    const asChart = lineChart("A股综合情绪分（近 6 月）" + termTip("综合多项指标算的情绪温度计0-100，≤20冰点≥80过热") + latestSuffix(as6), as6, {}, null, colA1);
    if (asChart) addCardTimeBadge(asChart.getDom().parentElement, as6.length ? as6[as6.length - 1].date : "", snap, "t0");
  }

  // 右列：冰点日卡片（近120日，按日分组4个/行）
  const freezeCard = document.createElement("div");
  freezeCard.className = "chart-card";
  freezeCard.innerHTML = _renderSignalGrid(r.recent_freeze, r.date, "近期冰点日（近 120 日）", "freeze", "无近期冰点日");
  addCardTimeBadge(freezeCard, r.date, snap, "t0");
  // 点击冰点日卡片弹窗：展示该情绪分走势图+冰点(≤20)标注
  freezeCard.addEventListener("click", (e) => {
    const item = e.target.closest(".sig-clickable");
    if (!item) return;
    e.preventDefault();
    openSignalChartModal(item.dataset.idx, item.dataset.sig, item.dataset.date, item.dataset.val);
  });
  colA2.appendChild(freezeCard);

  // 右列：近期买卖点（近15交易日，今日高亮排首）
  const sigCard = document.createElement("div");
  sigCard.className = "chart-card";
  sigCard.innerHTML = _renderSignalGrid(r.signals_today, r.date, "近期买卖点（近 15 交易日 · 今日高亮）", "signal", "近期无买卖点信号");
  addCardTimeBadge(sigCard, r.date, snap, "t0");
  // 点击买卖点卡片弹窗：展示对应指数/品类走势图+买卖信号标注
  sigCard.addEventListener("click", (e) => {
    const item = e.target.closest(".sig-clickable");
    if (!item) return;
    e.preventDefault();
    openSignalChartModal(item.dataset.idx, item.dataset.sig, item.dataset.date);
  });
  colA2.appendChild(sigCard);

  // 右列：🐶 汪汪队信号卡片（ETF国家队资金动向，近期信号列表+hover pop+点击弹modal，不跳专区）
  const nt = r.nt_signals_today;
  const ntCard = document.createElement("div");
  ntCard.className = "chart-card nt-home-card";
  if (nt && nt.date) {
    // 共振标记：进/出≥2只、量≥3只宽基同日同步异动=国家队共振
    const resBadge = nt.is_resonance
      ? '<span class="nt-resonance-badge">🐾 共振</span>' : '';
    // 汇总小标题（一行小字，保留）：近N天共X信号·进X出Y量Z·共振M日
    const rc = nt.recent;
    let summaryHtml = "";
    if (rc && rc.daily && rc.daily.length) {
      // 缓存 daily 供 openNtDayModal 取当日 signals[]
      _ntRecentDaily = rc.daily;
      summaryHtml =
        '<div class="nt-recent-summary">' +
          '<div class="nt-recent-stats">近' + rc.days + '天 共<b>' + rc.total + '</b>信号 · ' +
            '<span class="nt-c-surge">进<b>' + rc.surge + '</b></span> ' +
            '<span class="nt-c-outflow">出<b>' + rc.outflow + '</b></span> ' +
            '<span class="nt-c-volume">量<b>' + rc.volume + '</b></span> · 共振<b>' + rc.resonance_days + '</b>日</div>' +
        '</div>';
    } else {
      _ntRecentDaily = null;
    }
    ntCard.innerHTML =
      '<h3>🐶 汪汪队信号 <span class="nt-date-tag">数据 ' + fmtDate(nt.date) + '</span>' + resBadge +
      termTip("汪汪队=国家队。追踪12只宽基ETF份额变动+成交额放量，推断疑似大资金进场/离场。进=份额增+z>2+放量(红)/出=份额减+z<-2+放量(绿)/量=成交额>5日均2倍(橙)。共振=进/出≥2只、量≥3只宽基同日同步异动。ETF份额T+1发布，数据日期可能为T-1。点击下方信号chip查看当日明细。") + "</h3>" +
      summaryHtml +
      '<div class="signal-grid nt-signal-grid">' + _renderNtSignalList(rc && rc.daily ? rc.daily : [], nt.date) + '</div>';
    addCardTimeBadge(ntCard, nt.date, snap, "etf");
    // chip 点击：弹当日明细 modal（事件委托，[data-nt-date] 触发；stopPropagation 防冒泡）
    ntCard.addEventListener("click", (e) => {
      const chip = e.target.closest("[data-nt-date]");
      if (!chip) return;
      e.stopPropagation();
      openNtDayModal(chip.dataset.ntDate);
    });
  } else {
    _ntRecentDaily = null;
    ntCard.innerHTML =
      '<h3>🐶 汪汪队信号' +
      termTip("汪汪队=国家队。追踪12只宽基ETF份额变动+成交额放量，推断疑似大资金进场/离场。ETF份额T+1发布。") + "</h3>" +
      '<div class="empty-note">近期无汪汪队信号</div>';
    if (nt && nt.date) addCardTimeBadge(ntCard, nt.date, snap, "etf");
  }
  colA2.appendChild(ntCard);


  // ---- 3. 信号强度两列：左=市场宽度+跨市场，右=均线排列+位置感 ----
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
    const wLast = wDates[wDates.length - 1];
    const wUpV = (w.up.find((x) => x.date === wLast) || {}).value;
    const wDnV = (w.down.find((x) => x.date === wLast) || {}).value;
    const wSuffix = wLast ? `<span class="chart-latest"> · ${fmtDate(wLast)} 涨${wUpV != null ? wUpV : "-"} 跌${wDnV != null ? wDnV : "-"}</span>` : "";
    const wc = mkCard("市场宽度（涨跌家数，近 1 月）" + termTip("上涨家数占比反映市场广度，普涨时宽度大") + wSuffix + termTip(_WIDTH_CALIBER_TIP), 260, null, colB1);
    appendPlainTip(wc, "上涨家数远多于下跌=普涨行情；两者接近=市场分化");
    addCardTimeBadge(wc.getDom().parentElement, wLast, snap, "t0");
    wc.setOption(withTheme({
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
    }));
  }

  // 左列：跨市场综合评分折线（近 6 月）
  if (r.cross_market_6m && r.cross_market_6m.length) {
    const cm6 = r.cross_market_6m.map((d) => ({ date: d.date, value: d.value }));
    const cmChart = lineChart("跨市场综合评分（近 6 月）" + termTip("综合A股/港股/美股等多市场算的0-100分，≤20偏冷≥80偏热") + latestSuffix(cm6), cm6, {
      visualMap: {
        show: false,
        pieces: [{ lte: 20, color: "#e6492e" }, { gt: 20, lte: 80, color: "#5b8ff9" }, { gt: 80, color: "#2e8b57" }],
        dimension: 1,
      },
    }, null, colB1);
    if (cmChart) addCardTimeBadge(cmChart.getDom().parentElement, cm6.length ? cm6[cm6.length - 1].date : "", snap, "t0");
  }

  // 右列：均线排列卡片（独立 fetch，失败不影响位置感卡片 O1）
  fetchJSON("./data/ma_alignment.json").then((maData) => {
    const d = (maData.data || []).slice(-1)[0];
    if (d) {
      const maCard = document.createElement("div");
      maCard.className = "chart-card ma-card";
      const bullish = d.bullish || 0;
      const bearish = d.bearish || 0;
      const cross = d.cross || 0;
      const maSuffix = d.date ? `<span class="chart-latest"> · ${fmtDate(d.date)} 多头${bullish} 空头${bearish} 震荡${cross}</span>` : "";
      let maHtml = `<h3>&#x1F4C8; 均线排列${termTip("MA=移动平均线,N日收盘价均值。MA5>MA10>MA20>MA60多头排列=短长期均线由高到低,趋势向上;反之为空头排列,趋势向下。")}${maSuffix}</h3>`;
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
      appendPlainTip(maCard, "多头排列=短期均线在长期之上，趋势向上；反之趋势向下");
      addCardTimeBadge(maCard, d.date, snap, "t0");
    }
  }).catch((e) => { renderFailCard(colB2, "&#x1F4C8; 均线排列", e); });

  // 位置感卡片（独立 fetch，与均线排列互不依赖 O1）
  fetchJSON("./data/position.json").then((posData) => {
    if (posData && posData.positions && posData.positions.length) {
      const posCard = document.createElement("div");
      posCard.className = "chart-card position-card";
      const posDates = posData.positions.map((p) => p.current_date).filter(Boolean).sort();
      let posLow = 0, posHigh = 0;
      for (const p of posData.positions) {
        const pct = p.percentile_1y != null ? p.percentile_1y : 50;
        if (pct <= 40) posLow++; else if (pct > 60) posHigh++;
      }
      const posDateSuffix = posDates.length ? `<span class="chart-latest"> · ${fmtDate(posDates[posDates.length - 1])} 低位${posLow} 高位${posHigh}</span>` : "";
      let posHtml = `<h3>&#x1F4CD; 大盘位置感${termTip("当前价在近1年最高最低之间的位置%，越低越便宜越高越贵")}${posDateSuffix}</h3><div class="position-list">`;
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
      addCardTimeBadge(posCard, posDates.length ? posDates[posDates.length - 1] : "", snap, "t0");
    }
  }).catch((e) => { renderFailCard(colB2, "&#x1F4CD; 大盘位置感", e); });

  // ---- 4. AD Line 腾落线 + 成交量对比（全宽，横跨两列）----
  const ov2ColC = document.createElement("div");
  ov2ColC.className = "ov-2col";
  const colC1 = document.createElement("div");
  const colC2 = document.createElement("div");
  ov2ColC.appendChild(colC1);
  ov2ColC.appendChild(colC2);
  content.appendChild(ov2ColC);

  // 并行拉取 AD Line / 成交量对比 / 新高新低（3 个独立 fetch，allSettled 互不影响，失败各自降级）
  const [adLineP, volRatioP, newHighLowP] = await Promise.allSettled([
    fetchJSON("./data/ad_line.json"),
    fetchJSON("./data/volume_ratio.json"),
    fetchJSON("./data/new_high_low.json"),
  ]);

  // 左：AD Line 腾落线
  try {
    if (adLineP.status !== "fulfilled") throw adLineP.reason;
    const adRes = adLineP.value;
    const adData = (adRes.data || []).slice(-120);
    if (adData.length) {
      const adDates = adData.map(d => d.date);
      const ratioData = adData.map(d => d.ratio);
      const adLineData = adData.map(d => d.ad_line);
      const adMA20 = adData.map(d => d.ad_line_ma20);
      const ratioColors = adData.map(d => (d.up_count >= d.down_count) ? "#e6492e" : "#2e8b57");

      const adSeries = [
        { name: "涨跌家数比", data: adData.map(d => ({ date: d.date, value: d.ratio })), label: "涨跌比" },
        { name: "AD Line", data: adData.map(d => ({ date: d.date, value: d.ad_line })), label: "AD" },
        { name: "AD Line MA20", data: adData.map(d => ({ date: d.date, value: d.ad_line_ma20 })), label: "MA20" },
      ];
      const adc = mkCard("📊 腾落线（AD Line）" + termTip("腾落线=累积每日上涨家数-下跌家数。持续上升=广度健康(多数股票涨),与指数背离常预示拐点。累计值绝对值无意义,看趋势。") + latestSuffixMulti(adSeries), 300, null, colC1);
      appendPlainTip(adc, "AD线持续上行=多数股票在涨，大盘涨势健康");
      addCardTimeBadge(adc.getDom().parentElement, adDates.length ? adDates[adDates.length - 1] : "", snap, "t0");
      adc.setOption(withTheme({
        tooltip: { trigger: "axis" },
        legend: { top: 0, data: ["涨跌家数比", "AD Line", "AD Line MA20"] },
        grid: { left: 55, right: 55, top: 35, bottom: 35 },
        xAxis: { type: "category", data: adDates },
        yAxis: [
          { type: "value", name: "涨跌比", axisLabel: { color: cssVar("--text-1"), formatter: v => v.toFixed(2) }, nameTextStyle: { color: cssVar("--text-1") }, splitLine: { show: false } },
          { type: "value", name: "AD Line", axisLabel: { color: cssVar("--text-1") }, nameTextStyle: { color: cssVar("--text-1") } },
        ],
        dataZoom: dzOpts(),
        series: [
          { name: "涨跌家数比", type: "bar", yAxisIndex: 0, data: ratioData.map((v, i) => ({ value: v, itemStyle: { color: ratioColors[i] } })), barWidth: "60%" },
          { name: "AD Line", type: "line", yAxisIndex: 1, symbol: "none", smooth: true, data: adLineData, lineStyle: { color: "#5b8ff9", width: 1.5 } },
          { name: "AD Line MA20", type: "line", yAxisIndex: 1, symbol: "none", smooth: true, data: adMA20, lineStyle: { color: "#f6bd16", width: 1.5, type: "dashed" } },
        ],
      }));
    } else {
      renderFailCard(colC1, "📊 腾落线（AD Line）");
    }
  } catch (e) { renderFailCard(colC1, "📊 腾落线（AD Line）", e); }

  // 右：成交量对比
  try {
    if (volRatioP.status !== "fulfilled") throw volRatioP.reason;
    const vrRes = volRatioP.value;
    const vrData = (vrRes.data || []).slice(-120);
    if (vrData.length) {
      const vrDates = vrData.map(d => d.date);
      const vrAmount = vrData.map(d => d.amount);
      const vrMA5 = vrData.map(d => d.ma5);
      const vrMA20 = vrData.map(d => d.ma20);
      const vrColors = vrData.map(d => (d.pct_change >= 0) ? "#e6492e" : "#2e8b57");

      const vrSeries = [
        { name: "成交额", data: vrData.map(d => ({ date: d.date, value: d.amount })), label: "成交" },
        { name: "MA5", data: vrData.map(d => ({ date: d.date, value: d.ma5 })), label: "MA5" },
        { name: "MA20", data: vrData.map(d => ({ date: d.date, value: d.ma20 })), label: "MA20" },
      ];
      const vrc = mkCard("📈 成交额与量比（近 120 日）" + termTip("量比=当日成交额/前5日均量。>1.5=放量(交投活跃),<0.7=缩量(清淡)。放量伴随涨跌更可信。") + latestSuffixMulti(vrSeries), 300, null, colC2);
      appendPlainTip(vrc, "量比>1.5为明显放量，<0.5为明显缩量");
      addCardTimeBadge(vrc.getDom().parentElement, vrDates.length ? vrDates[vrDates.length - 1] : "", snap, "t0");
      vrc.setOption(withTheme({
        tooltip: { trigger: "axis", formatter: function(params) {
          const d = vrData[params[0].dataIndex];
          return `<b>${d.date}</b><br/>成交额: ${(d.amount || 0).toFixed(0)} 亿<br/>MA5: ${(d.ma5 || 0).toFixed(0)} 亿<br/>MA20: ${(d.ma20 || 0).toFixed(0)} 亿<br/>量比: ${(d.ratio || 0).toFixed(2)}x<br/>信号: ${d.signal || "正常"}`;
        }},
        legend: { top: 0, data: ["成交额", "MA5", "MA20"] },
        grid: { left: 55, right: 20, top: 35, bottom: 35 },
        xAxis: { type: "category", data: vrDates },
        yAxis: { type: "value", name: "亿元", axisLabel: { color: cssVar("--text-1"), formatter: v => (v / 10000).toFixed(1) + "万" }, nameTextStyle: { color: cssVar("--text-1") } },
        dataZoom: dzOpts(),
        series: [
          { name: "成交额", type: "bar", data: vrAmount.map((v, i) => ({ value: v, itemStyle: { color: vrColors[i] } })), barWidth: "60%" },
          { name: "MA5", type: "line", symbol: "none", smooth: true, data: vrMA5, lineStyle: { color: "#f6bd16", width: 1.5 } },
          { name: "MA20", type: "line", symbol: "none", smooth: true, data: vrMA20, lineStyle: { color: "#5b8ff9", width: 1.5, type: "dashed" } },
        ],
      }));
    } else {
      renderFailCard(colC2, "📈 成交额与量比");
    }
  } catch (e) { renderFailCard(colC2, "📈 成交额与量比", e); }

  // ---- 4b. 新高新低家数（NH-NL，52周/20日，X1 死端接入）----
  try {
    if (newHighLowP.status !== "fulfilled") throw newHighLowP.reason;
    const nhlRes = newHighLowP.value;
    const nhlData = (nhlRes.data || []).slice(-120);
    if (nhlData.length) {
      const nhlDates = nhlData.map(d => d.date);
      const nhlSeries = [
        { name: "52周新高", data: nhlData.map(d => ({ date: d.date, value: d.nh_52w })), label: "新高" },
        { name: "52周新低", data: nhlData.map(d => ({ date: d.date, value: d.nl_52w })), label: "新低" },
        { name: "NH-NL", data: nhlData.map(d => ({ date: d.date, value: d.nhnl_52w })), label: "NH-NL" },
      ];
      const nhlCard = mkCard("🔬 新高新低家数（52 周）" + termTip("近52周创新高/新低的股票家数，新高多=强势新低多=弱势") + latestSuffixMulti(nhlSeries), 280, null, colC1);
      appendPlainTip(nhlCard, "新高多于新低=市场偏强；新低多于新高=市场偏弱");
      addCardTimeBadge(nhlCard.getDom().parentElement, nhlDates.length ? nhlDates[nhlDates.length - 1] : "", snap, "t0");
      nhlCard.setOption(withTheme({
        tooltip: { trigger: "axis" },
        legend: { top: 0, data: ["52周新高", "52周新低", "NH-NL"] },
        grid: { left: 55, right: 55, top: 35, bottom: 35 },
        xAxis: { type: "category", data: nhlDates },
        yAxis: [
          { type: "value", name: "家数", axisLabel: { color: cssVar("--text-1") }, nameTextStyle: { color: cssVar("--text-1") }, splitLine: { show: false } },
          { type: "value", name: "NH-NL", axisLabel: { color: cssVar("--text-1") }, nameTextStyle: { color: cssVar("--text-1") } },
        ],
        dataZoom: dzOpts(),
        series: [
          { name: "52周新高", type: "bar", yAxisIndex: 0, data: nhlData.map(d => d.nh_52w), itemStyle: { color: "#e6492e" }, barWidth: "40%" },
          { name: "52周新低", type: "bar", yAxisIndex: 0, data: nhlData.map(d => d.nl_52w), itemStyle: { color: "#2e8b57" }, barWidth: "40%" },
          { name: "NH-NL", type: "line", yAxisIndex: 1, symbol: "none", smooth: true, data: nhlData.map(d => d.nhnl_52w), lineStyle: { color: "#5b8ff9", width: 1.5 } },
        ],
      }));
      // 最新日的指数级详情（8 个指数是否创 52周/20日新高新低）
      const latest = nhlData[nhlData.length - 1];
      if (latest && latest.details && latest.details.length) {
        const detCard = document.createElement("div");
        detCard.className = "chart-card";
        let detHtml = `<h3>&#x1F50D; 指数新高新低明细<span class="chart-latest"> · ${fmtDate(latest.date)}</span></h3>`;
        detHtml += `<table class="ma-table"><thead><tr><th>指数</th><th>收盘</th><th>52周</th><th>20日</th></tr></thead><tbody>`;
        for (const it of latest.details) {
          const tag52 = it.nh_52w ? '<span class="ma-count bullish">新高</span>' : it.nl_52w ? '<span class="ma-count bearish">新低</span>' : '<span style="color:var(--text-3)">-</span>';
          const tag20 = it.nh_20d ? '<span class="ma-count bullish">新高</span>' : it.nl_20d ? '<span class="ma-count bearish">新低</span>' : '<span style="color:var(--text-3)">-</span>';
          detHtml += `<tr><td>${it.name}</td><td>${(it.close || 0).toLocaleString()}</td><td>${tag52}</td><td>${tag20}</td></tr>`;
        }
        detHtml += `</tbody></table>`;
        detCard.innerHTML = detHtml;
        colC2.appendChild(detCard);
        addCardTimeBadge(detCard, latest.date, snap, "t0");
      }
    }
  } catch (e) { /* new_high_low 失败不影响主流程，静默降级 */ }

  // ---- 5. 申万行业涨跌幅热力图 ----
  if (r.industry_heatmap && r.industry_heatmap.length) {
    const hmDates = r.industry_heatmap.map(h => h.last_date).filter(Boolean).sort();
    const hmSuffix = hmDates.length ? `<span class="chart-latest"> · ${fmtDate(hmDates[hmDates.length - 1])}</span>` : "";
    const hmChart = renderIndustryHeatmap(r.industry_heatmap, "申万一级行业涨跌幅热力图（近 1 日 / 近 5 日）" + hmSuffix);
    if (hmChart) addCardTimeBadge(hmChart.getDom().parentElement, hmDates.length ? hmDates[hmDates.length - 1] : "", snap, "t1", "industry");
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
  content.insertAdjacentHTML("beforeend", '<div class="home-purpose-note">💡 <b>这板块有什么用</b>:看A股、港股、全球指数走势,叠加技术面买卖点信号,综合判断大盘情绪偏冷还是偏热;另追踪🐶汪汪队=国家队宽基ETF资金动向。<b>怎么解读</b>:信号偏多通常反映情绪回暖,偏空反映转弱(历史统计参考,非操作建议);汪汪队大额净流入常对应政策底区域,流出对应资金撤离。</div>');
  // 二级 tab 栏
  const subtabBar = document.createElement("div");
  subtabBar.className = "subtab-bar";
  const subtabs = [
    ["a-stock", "A股"],
    ["hk", "港股"],
    ["global", "全球"],
    ["national-team", "🐶 汪汪队"],
  ];
  subtabs.forEach(([key, label]) => {
    const btn = document.createElement("button");
    btn.textContent = label;
    btn.dataset.subtab = key;
    if (state.subtab === key) btn.classList.add("active");
    btn.onclick = () => {
      state.subtab = key;
      _setTabHash(state.tab); // 写 #market/{subtab}，F5 刷新恢复二级 tab
      renderMarket(); // 重新渲染大盘 tab
    };
    subtabBar.appendChild(btn);
  });
  content.appendChild(subtabBar);

  // 子内容容器
  const subContent = document.createElement("div");
  subContent.className = "market-sub-content";
  content.appendChild(subContent);
  renderLoadingState(subContent);

  // 根据 subtab 渲染对应内容
  if (state.subtab === "a-stock") await renderAStock(subContent);
  else if (state.subtab === "hk") await renderHK(subContent);
  else if (state.subtab === "global") await renderGlobal(subContent);
  else if (state.subtab === "national-team") await renderNationalTeam(subContent);
}

// ============ 🐶 汪汪队：国家队宽基 ETF 资金动向 ============
// 口径：代理推断，非真实国家队席位数据。基于 ETF 每日份额变动+成交额放量，结合季度机构持仓占比校准，
// 推断疑似大资金进场/离场。无法精确区分汇金/证金/社保/险资/公募。详见 REQUIREMENTS.md §8.6。
// v2 待办（任务#60）：汇金/证金具名识别展示位置 - 等 v2 后端补具名席位数据后，在下方"关键事件"区前加明细卡片。
// 首屏=4层概览看板（总览摘要条+矩阵热力图+卡片墙+叠加对比折线），点卡片/热力图行/折线进单只详情。
async function renderNationalTeam(container = content) {
  _disposeContainerCharts(container);
  renderLoadingState(container);
  let data, qData, hData;
  try {
    data = await fetchJSON(`./data/etf_national_team-${state.range}.json`);
    qData = await fetchJSON("./data/etf_national_team_quarterly.json");
    try { hData = await fetchJSON("./data/etf_national_team_holders.json"); } catch (e) { hData = null; }
  } catch (e) {
    renderErrorState(container, e, () => renderNationalTeam(container));
    return;
  }
  if (!data || !data.etfs || !data.etfs.length) {
    container.innerHTML = '<div class="loading">暂无数据</div>';
    return;
  }
  container.innerHTML = "";

  // 拉取盘中快照，供国家队3图角标判断盘中/收盘状态（1.5s 超时兜底，不阻塞渲染）
  try { await Promise.race([fetchIntradaySnapshot(), new Promise((r) => setTimeout(r, 1500))]); } catch {}
  const snap = state.intradaySnapshot;

  // 保留原始全量数据引用，供弹窗内独立周期(ntDetailRange)切片，不受外层 state.range 影响
  var rawData = data;
  // 按 state.range 时间窗口切片 daily（数据全量在 JSON，前端切片不 refetch）
  data = ntSliceDataByRange(data);

  // ── 口径声明横幅 ──
  const banner = document.createElement("div");
  banner.className = "nt-banner";
  banner.innerHTML =
    `<h3>🐶 汪汪队 - 国家队宽基 ETF 资金动向 <span class="term-tip" data-tip="汪汪队=国家队。追踪12只宽基ETF(上证50/沪深300/中证500/1000/创业板/科创50)的份额变动+成交额放量，推断疑似大资金进场/离场。份额异动z-score>2且放量1.5倍以上=疑似大资金进场(红)，反之为离场(绿)。注意：这是代理推断，无法100%确认是国家队，份额变动可能来自任何机构/大户申赎。">❓</span></h3>` +
    `<div class="nt-banner-body">追踪 12 只宽基 ETF 的<span style="color:var(--primary)">份额变动+成交额放量</span>，推断疑似大资金（含国家队）进场/离场。<b>口径声明</b>：本指标为代理推断，非真实国家队席位数据，无法精确区分汇金/证金/社保/险资/公募。份额变动可能来自任何机构/大户申赎，不等于国家队操作。当季机构占比&gt;85% 时置信度×1.5（国家队主导品种）。</div>`;
  container.appendChild(banner);

  if (state.ntView === "detail") {
    renderNationalTeamDetail(container, data, qData, hData);
  } else {
    renderNationalTeamOverview(container, data, qData, hData, rawData, snap);
  }
}

// 按 state.range 时间窗口切片 daily（数据全量在 JSON，前端切片不 refetch）
// 按 range 时间窗口切片 daily（数据全量在 JSON，前端切片不 refetch）
// range 缺省时用 state.range（外层概览切片）；弹窗内传 ntDetailRange 独立切片
function ntSliceDataByRange(data, range) {
  var rng = range || state.range;
  var rangeDays = { "1m": 30, "3m": 90, "6m": 180, "1y": 365, "3y": 1095, "5y": 1825 };
  var days = rangeDays[rng];
  if (!days) return data; // all 或未知 -> 全量
  var dd = new Date();
  dd.setDate(dd.getDate() - days);
  var cutoff = "" + dd.getFullYear() + String(dd.getMonth() + 1).padStart(2, "0") + String(dd.getDate()).padStart(2, "0");
  var out = { updated_at: data.updated_at, etfs: [] };
  data.etfs.forEach(function (e) {
    out.etfs.push({
      code: e.code, name: e.name, index: e.index, market: e.market,
      daily: (e.daily || []).filter(function (x) { return x.date >= cutoff; }),
      latest: e.latest, // 保留原始最新行（不随 range 切）
    });
  });
  return out;
}

// 散户白话：汪汪队 ETF 每只份额迷你折线（sparkline），SVG 轻量不走 ECharts，currentColor 跟主题
function ntSparkline(daily, w, h) {
  var vals = (daily || []).map(function (d) { return d.fund_share_yi; }).filter(function (v) { return v != null; });
  if (vals.length < 2) return "";
  var min = Math.min.apply(null, vals), max = Math.max.apply(null, vals);
  var range = max - min || 1;
  var pts = vals.map(function (v, i) {
    var x = (i / (vals.length - 1)) * w;
    var y = h - 2 - ((v - min) / range) * (h - 4);
    return x.toFixed(1) + "," + y.toFixed(1);
  }).join(" ");
  var lastV = vals[vals.length - 1];
  var lastY = h - 2 - ((lastV - min) / range) * (h - 4);
  return '<svg class="nt-spark" width="' + w + '" height="' + h + '" viewBox="0 0 ' + w + ' ' + h + '">' +
    '<polyline points="' + pts + '" fill="none" stroke="currentColor" stroke-width="1.5"/>' +
    '<circle cx="' + w.toFixed(1) + '" cy="' + lastY.toFixed(1) + '" r="2.2" fill="currentColor"/></svg>';
}

// 首页🐶卡片7天总况：堆叠迷你柱状图（红进/绿出/橙量），柱底标MM-DD，金点=共振日
function ntMiniBars(daily) {
  if (!daily || !daily.length) return "";
  var n = daily.length;
  var barW = 14, gap = 6, padX = 4;
  var w = padX * 2 + n * barW + (n - 1) * gap;
  var chartH = 38, labelH = 16;
  var h = chartH + labelH;
  var maxTotal = Math.max.apply(null, daily.map(function (d) { return d.total; })) || 1;
  var scale = (chartH - 4) / maxTotal;
  var parts = ['<svg class="nt-mini-bars" width="100%" height="' + h + '" viewBox="0 0 ' + w + ' ' + h + '" preserveAspectRatio="xMidYMid meet">'];
  daily.forEach(function (d, i) {
    var x = padX + i * (barW + gap);
    var y = chartH;
    // 堆叠：进(红)底 -> 出(绿)中 -> 量(橙)顶
    if (d.n_surge > 0) { var sh = d.n_surge * scale; y -= sh; parts.push('<rect x="' + x + '" y="' + y.toFixed(1) + '" width="' + barW + '" height="' + sh.toFixed(1) + '" fill="#e6492e" rx="1"/>'); }
    if (d.n_outflow > 0) { var oh = d.n_outflow * scale; y -= oh; parts.push('<rect x="' + x + '" y="' + y.toFixed(1) + '" width="' + barW + '" height="' + oh.toFixed(1) + '" fill="#2e8b57" rx="1"/>'); }
    if (d.n_volume > 0) { var vh = d.n_volume * scale; y -= vh; parts.push('<rect x="' + x + '" y="' + y.toFixed(1) + '" width="' + barW + '" height="' + vh.toFixed(1) + '" fill="#ff9800" rx="1"/>'); }
    // 共振日柱底加金色圆点
    if (d.is_resonance) { parts.push('<circle cx="' + (x + barW / 2) + '" cy="' + (chartH + 2.5) + '" r="1.8" fill="#ffd700"/>'); }
    // 日期标签 MM-DD
    var lbl = d.date.length === 8 ? d.date.slice(4, 6) + "-" + d.date.slice(6, 8) : d.date;
    parts.push('<text class="nt-bar-label" x="' + (x + barW / 2) + '" y="' + (h - 3) + '" text-anchor="middle" font-size="8">' + lbl + '</text>');
  });
  parts.push('</svg>');
  return parts.join("");
}

// 计算12只ETF的概览摘要（最新日份额变动/信号/机构占比/放量倍数）
function ntBuildSummary(data, qData) {
  return data.etfs.map(function (e) {
    var daily = e.daily || [];
    var latest = e.latest || daily[daily.length - 1] || {};
    var qEtf = qData.etfs.find(function (q) { return q.code === e.code; });
    var qLatest = qEtf && qEtf.history && qEtf.history.length ? qEtf.history[qEtf.history.length - 1] : null;
    // 放量倍数=当日成交额/前5日均量（不含当日）
    var recent5 = daily.slice(-6, -1);
    var avg5 = recent5.length ? recent5.reduce(function (s, d) { return s + (d.amount || 0); }, 0) / recent5.length : 0;
    var volRatio = avg5 > 0 && latest.amount ? latest.amount / avg5 : 0;
    // 最近一条信号
    var latestSig = null;
    for (var i = daily.length - 1; i >= 0; i--) {
      if (daily[i].signals && daily[i].signals.length) {
        latestSig = Object.assign({}, daily[i].signals[0], { date: daily[i].date });
        break;
      }
    }
    return {
      e: e, code: e.code, name: e.name, index: e.index,
      daily: daily, latest: latest, qLatest: qLatest,
      shareChangeYi: latest.share_change_yi || 0,
      shareChangePct: latest.share_change_pct || 0,
      close: latest.close || 0,
      instPct: qLatest ? qLatest.inst_hold_pct : null,
      volRatio: volRatio,
      latestSig: latestSig,
    };
  });
}

// 多信号拼色 pin 渐变：硬切割线性渐变(进红->出绿->量橙)，同 offset 两 stop 实现段间锐利分界
// 比例：每段均分 (100-20)/N，末段(底部,量橙)再叠加固定 20%(气泡底部尖端窄,均分会被挤没看不见)
//   2段: 40:60   3段: 26.6:26.6:46.6
function _ntMultiColor(segColors) {
  var n = segColors.length, stops = [];
  var base = (1 - 0.2) / n;          // 每段均分基量 80%/N
  var cum = 0;                        // 已累计 offset
  for (var i = 0; i < n; i++) {
    var isLast = i === n - 1;
    var w = isLast ? base + 0.2 : base;  // 末段叠加 20%
    var start = cum, end = cum + w;
    stops.push({ offset: start, color: segColors[i] });
    stops.push({ offset: end, color: segColors[i] });
    cum = end;
  }
  return { type: "linear", x: 0, y: 0, x2: 0, y2: 1, colorStops: stops };
}

// 共振信号 pin 文案：进N/出N/量N -> 通俗描述（hover pin 时 tooltip 显示，解释信号含义）
// 支持多信号组合串 "进8+量5"：按 + 拆分逐段描述，返回多行 HTML
function _ntPinTip(v) {
  var s = String(v), parts = s.split("+");
  if (parts.length === 1) {
    var m = /^([进出量])(\d+)$/.exec(s);
    if (!m) return s;
    var type = m[1], n = m[2];
    if (type === "进") return v + ":当日" + n + "只宽基ETF同步进场信号(份额增+异常度z>2+放量)";
    if (type === "出") return v + ":当日" + n + "只宽基ETF同步离场信号(份额减+异常度z<-2+放量)";
    return v + ":当日" + n + "只宽基ETF同步放量(成交额>近5日均2倍)";
  }
  var descs = [];
  for (var i = 0; i < parts.length; i++) {
    var m = /^([进出量])(\d+)$/.exec(parts[i]);
    if (!m) continue;
    var type = m[1], n = m[2];
    if (type === "进") descs.push("进" + n + ":" + n + "只宽基同步进场(份额增+z>2+放量)");
    else if (type === "出") descs.push("出" + n + ":" + n + "只宽基同步离场(份额减+z<-2+放量)");
    else descs.push("量" + n + ":" + n + "只宽基同步放量(额>近5日均2倍)");
  }
  return s + " 多信号共振<br/>" + descs.join("<br/>");
}

// ETF份额T+1补全时点：交易所次日盘后发布,20:07采集补全。显示明确日期避免"明晚"模糊表述
function _ntShareReplenishTxt(dataDate) {
  if (!dataDate || dataDate.length < 8) return "次日 20:07 后";
  var d = new Date(+dataDate.slice(0, 4), +dataDate.slice(4, 6) - 1, +dataDate.slice(6, 8));
  d.setDate(d.getDate() + 1);
  return (d.getMonth() + 1) + "月" + d.getDate() + "日 20:07 后";
}

// ── 总盘汇总层：12只ETF合计持仓市值+净增持额+份额趋势（看"国家队整体持仓"而非单只）──
function renderNationalTeamTotalPanel(container, data, snap) {
  // 合计层共振信号阈值：≥N只宽基ETF同日同步异动=国家队共振
  // 进/出=份额激增/流出(≥2只)，量=放量(≥3只，放量标准更严因更常见)
  var THR = { surge: 2, outflow: 2, volume: 3 };
  // 聚合12只ETF的daily，按日期合并：合计市值/合计份额/当日净增持 + 信号计数
  // shareNull/chgNull 标记该日是否有ETF的份额/变动为NULL(T+1源末日未发布)，末日NULL不兜底成0误导
  var dateMap = {};
  data.etfs.forEach(function (e) {
    var prevShare = null;  // 跨日维护该ETF上一日份额：末日share null(T+1未发布)时用prevShare×当日close预估市值
    (e.daily || []).forEach(function (d) {
      var dt = d.date;
      if (!dateMap[dt]) dateMap[dt] = { date: dt, mktCap: 0, share: 0, netAdd: 0, nSurge: 0, nOutflow: 0, nVolume: 0, shareNull: false, chgNull: false };
      var rawShare = d.fund_share_yi;          // 原始份额(可能null)
      var share = rawShare || 0;               // 亿份（null兜底0用于份额合计,份额合计末日由下方复制prev.share修正）
      var chg = d.share_change_yi || 0;        // 亿份变动
      var close = d.close || 0;                // 元
      // 末日份额null时用prevShare×当日close预估市值(随价波动),而非share=0致市值突降后整体复制prev.mktCap
      var shareForMkt = (rawShare != null) ? rawShare : (prevShare != null ? prevShare : 0);
      dateMap[dt].mktCap += shareForMkt * close;  // 亿元（亿份×元）
      dateMap[dt].share += share;                  // 亿份
      dateMap[dt].netAdd += chg * close;           // 亿元
      if (rawShare != null) prevShare = rawShare;  // 更新prevShare供下一日预估
      if (d.fund_share_yi == null) dateMap[dt].shareNull = true;
      if (d.share_change_yi == null) dateMap[dt].chgNull = true;
      // 聚合单只信号：当日有多少只ETF出 share_surge/share_outflow/volume_surge
      (d.signals || []).forEach(function (sig) {
        if (sig.type === "share_surge") dateMap[dt].nSurge++;
        else if (sig.type === "share_outflow") dateMap[dt].nOutflow++;
        else if (sig.type === "volume_surge") dateMap[dt].nVolume++;
      });
    });
  });
  var dates = Object.keys(dateMap).sort();
  if (!dates.length) return;
  var series = dates.map(function (dt) { return dateMap[dt]; });
  var last = series[series.length - 1];
  var prev = series.length >= 2 ? series[series.length - 2] : null;
  // 末日份额未发布(T+1时滞,如7/15份额源端未出)：市值/份额用上一日估算保持趋势连续不突降,
  // 净增持标null(图3末日柱不画,KPI显"份额待公布"),避免||0兜底成"净增持0亿"误导
  var lastShareMissing = last.shareNull;
  var lastChgMissing = last.chgNull;
  if (lastShareMissing && prev) {
    last.share = prev.share;   // 份额T+1未发布,沿用上日份额(市值已在聚合时用prevShare×当日close预估,不再整体复制prev.mktCap)
  }
  if (lastChgMissing) {
    last.netAdd = null;
  }
  var cum20 = series.slice(-20).reduce(function (s, d) { return s + (d.netAdd || 0); }, 0);

  // ▼ T+1 提示行：让用户知道国家队份额为何停 T-1 ▼
  var t1Hint = document.createElement("div");
  t1Hint.className = "nt-t1-hint";
  t1Hint.textContent = "⏳ ETF份额数据为T+1：上交所/深交所盘后次日发布,实测源端常晚于22:00,当日20:07采集通常只到T-1,次日20:07后补全当日";
  if (lastShareMissing) {
    t1Hint.textContent += "。⚠ 当日(" + fmtDate(last.date) + ")份额尚未发布,市值按上日份额×当日收盘价预估,份额沿用上日,净增持额待公布";
  }
  container.appendChild(t1Hint);

  // ▼ 第0层 KPI 大字：国家队总市值 + 今日净增持 + 近20日累计净增持 ▼
  var kpi = document.createElement("div");
  kpi.className = "nt-total-kpi";
  var netCls = (last.netAdd == null) ? "" : (last.netAdd >= 0 ? "nt-up" : "nt-down");
  var netSign = (last.netAdd == null) ? "" : (last.netAdd >= 0 ? "+" : "");
  var netValHtml = (last.netAdd == null)
    ? '<div class="nt-tk-val" style="color:var(--text-3)">份额待公布·' + _ntShareReplenishTxt(last.date) + '补全</div>'
    : '<div class="nt-tk-val ' + netCls + '">' + netSign + last.netAdd.toFixed(2) + ' <span class="nt-tk-unit">亿元</span></div>';
  var cumCls = cum20 >= 0 ? "nt-up" : "nt-down";
  var cumSign = cum20 >= 0 ? "+" : "";
  kpi.innerHTML =
    '<div class="nt-tk-item"><div class="nt-tk-label">国家队合计持仓市值' + termTip("12只宽基ETF当日份额×收盘价合计(亿元)。份额是交易所公布的硬数据，市值随价波动。") + '</div><div class="nt-tk-val">' + last.mktCap.toFixed(0) + ' <span class="nt-tk-unit">亿元</span>' + (lastShareMissing ? ' <span style="font-size:12px;color:#ff9800">份额待公布·按上日份额预估(' + _ntShareReplenishTxt(last.date) + '补全)</span>' : '') + '</div></div>' +
    '<div class="nt-tk-item"><div class="nt-tk-label">今日净增持额' + termTip("Σ(各ETF今日份额变动×今日价)。正值=国家队今日净买入，负值=净卖出。份额变动是硬数据不受价格波动干扰。") + '</div>' + netValHtml + '</div>' +
    '<div class="nt-tk-item"><div class="nt-tk-label">近20日累计净增持' + termTip("Σ(近20日各ETF每日份额变动×当日价)。看国家队近一个月持续买入还是卖出。") + '</div><div class="nt-tk-val ' + cumCls + '">' + cumSign + cum20.toFixed(2) + ' <span class="nt-tk-unit">亿元</span></div></div>';
  container.appendChild(kpi);

  var mktData = series.map(function (d) { return { date: d.date, value: +d.mktCap.toFixed(2) }; });
  var shareData = series.map(function (d) { return { date: d.date, value: +d.share.toFixed(2) }; });
  var netData = series.map(function (d) { return { date: d.date, value: d.netAdd == null ? null : +d.netAdd.toFixed(2) }; });
  // 末日份额待公布标记(图1/图2标题追加,提示末日值为上一日估算)；lastDate 3图共享(8位YYYYMMDD)
  var missingSuffix = lastShareMissing ? '<span class="chart-latest" style="color:#ff9800">· 末日份额待公布(市值按上日份额预估,' + _ntShareReplenishTxt(last.date) + '补)</span>' : '';
  var lastDate = last.date;

  // 合计层共振信号 markPoint：≥THR 只宽基同步异动（语义：国家队共振）
  // value 含共振只数，不依赖 hover 即可读出强度
  // 同日多信号(≥2类)合并成1个拼色pin(分段渐变+金描边+光晕)，不再重叠遮挡
  var mktMarks = [], shareMarks = [];
  var NT_SIG_COLORS = { "进": "#e6492e", "出": "#2e8b57", "量": "#ff9800" };
  series.forEach(function (d) {
    var mktY = +d.mktCap.toFixed(2);
    var shareY = +d.share.toFixed(2);
    // 按固定顺序收集当日达标信号：进->出->量
    var daySigs = [];
    if (d.nSurge >= THR.surge) daySigs.push({ label: "进" + d.nSurge, color: NT_SIG_COLORS["进"] });
    if (d.nOutflow >= THR.outflow) daySigs.push({ label: "出" + d.nOutflow, color: NT_SIG_COLORS["出"] });
    if (d.nVolume >= THR.volume) daySigs.push({ label: "量" + d.nVolume, color: NT_SIG_COLORS["量"] });
    if (!daySigs.length) return;
    if (daySigs.length === 1) {
      // 单信号：保持原样(内置pin、单色、size40)
      var sig = daySigs[0];
      mktMarks.push({ coord: [d.date, mktY], value: sig.label, itemStyle: { color: sig.color } });
      shareMarks.push({ coord: [d.date, shareY], value: sig.label, itemStyle: { color: sig.color } });
    } else {
      // 多信号：合并成1个拼色pin(分段渐变+金描边+光晕,size52)
      var valStr = daySigs.map(function (s) { return s.label; }).join("+");
      var segColors = daySigs.map(function (s) { return s.color; });
      var multiStyle = {
        color: _ntMultiColor(segColors),
        borderColor: "#ffd700",
        borderWidth: 3,
        shadowBlur: 8,
        shadowColor: "rgba(255,215,0,0.6)"
      };
      var lblFmt = valStr.replace(/\+/g, "\n");
      var multiLabel = { fontSize: 11, color: "#fff", formatter: lblFmt, lineHeight: 13 };
      mktMarks.push({ coord: [d.date, mktY], value: valStr, symbolSize: 64, label: multiLabel, itemStyle: multiStyle });
      shareMarks.push({ coord: [d.date, shareY], value: valStr, symbolSize: 64, label: multiLabel, itemStyle: multiStyle });
    }
  });

  // 3图动态1行折叠布局：PC/4K屏1:1:1全展，窄屏(<768px)折叠竖排(复用 .astock-top-grid 响应式CSS)
  var ntGrid = document.createElement("div");
  ntGrid.className = "astock-top-grid";
  container.appendChild(ntGrid);

  // 图1：合计持仓市值趋势（份额×价合计）+ 共振信号 pin 标注
  var c1 = mkCard("📊 国家队合计持仓市值趋势" + termTip("Σ(各ETF当日份额×收盘价)。看总额变化趋势，份额增+价涨=市值双击。pin=进/出≥" + THR.surge + "只、量≥" + THR.volume + "只宽基同步异动(国家队共振)：进=红/出=绿/量=橙。") + latestSuffix(mktData) + missingSuffix, 320, null, ntGrid);
  addCardTimeBadge(c1.getDom().parentElement, lastDate, snap, "t1", "etf_date");
  c1.setOption(withTheme({
    tooltip: {
      trigger: "axis",
      formatter: function (params) {
        var d = params[0], dt = d.axisValue;
        var pins = [];
        for (var i = 0; i < mktMarks.length; i++) {
          if (mktMarks[i].coord[0] === dt) pins.push(_ntPinTip(mktMarks[i].value));
        }
        for (var k = 0; k < params.length; k++) {
          if (params[k].componentType === "markPoint") return pins.join("<br/>");
        }
        var tip = fmtDate(dt) + "<br/>" + (d.value == null ? "-" : Number(d.value).toFixed(2)) + " 亿元";
        if (pins.length) tip += "<br/>" + pins.join("<br/>");
        return tip;
      }
    },
    grid: { left: 55, right: 20, top: 30, bottom: 50 },
    xAxis: { type: "category", data: dates },
    yAxis: { type: "value", name: "亿元", scale: true },
    dataZoom: dzOpts(),
    series: [{
      name: "合计市值", type: "line", smooth: true, symbol: "none", connectNulls: true,
      data: mktData.map(function (d) { return d.value; }), lineStyle: { width: 1.8 },
      markPoint: { symbol: "pin", symbolSize: 40, label: { fontSize: 11, color: "#fff" }, data: mktMarks },
    }],
  }));

  // 图2：份额合计趋势（纯份额，不含价格波动，份额持续增=真增持）+ 共振信号 pin 标注
  var c2 = mkCard("📈 份额合计趋势" + termTip("Σ各ETF当日份额(亿份)。份额持续增=真增持(非价格涨跌)，这是国家队操作的硬信号。pin=进/出≥" + THR.surge + "只、量≥" + THR.volume + "只宽基同步异动(国家队共振)：进=红/出=绿/量=橙。") + latestSuffix(shareData) + missingSuffix, 320, null, ntGrid);
  addCardTimeBadge(c2.getDom().parentElement, lastDate, snap, "t1", "etf_date");
  c2.setOption(withTheme({
    tooltip: {
      trigger: "axis",
      formatter: function (params) {
        var d = params[0], dt = d.axisValue;
        var pins = [];
        for (var i = 0; i < shareMarks.length; i++) {
          if (shareMarks[i].coord[0] === dt) pins.push(_ntPinTip(shareMarks[i].value));
        }
        for (var k = 0; k < params.length; k++) {
          if (params[k].componentType === "markPoint") return pins.join("<br/>");
        }
        var tip = fmtDate(dt) + "<br/>" + (d.value == null ? "-" : Number(d.value).toFixed(2)) + " 亿份";
        if (pins.length) tip += "<br/>" + pins.join("<br/>");
        return tip;
      }
    },
    grid: { left: 55, right: 20, top: 30, bottom: 50 },
    xAxis: { type: "category", data: dates },
    yAxis: { type: "value", name: "亿份", scale: true },
    dataZoom: dzOpts(),
    series: [{
      name: "份额合计", type: "line", smooth: true, symbol: "none", connectNulls: true,
      data: shareData.map(function (d) { return d.value; }), lineStyle: { width: 1.8 },
      markPoint: { symbol: "pin", symbolSize: 40, label: { fontSize: 11, color: "#fff" }, data: shareMarks },
    }],
  }));

  // 图3：每日净增持额柱状（红流入绿流出，末日份额待公布则末日柱不画）
  var c3 = mkCard("📉 每日净增持额（近" + dates.length + "日）" + termTip("每日Σ(份额变动×当日价)柱状。红柱=当日净流入(国家队买入)，绿柱=净流出(卖出)。") + (lastChgMissing ? '<span class="chart-latest" style="color:#ff9800">· 末日待公布</span>' : ''), 300, null, ntGrid);
  addCardTimeBadge(c3.getDom().parentElement, lastDate, snap, "t1", "etf_date");
  c3.setOption(withTheme({
    tooltip: { trigger: "axis", formatter: function (p) { var v = p[0]; if (v.value == null) return fmtDate(v.axisValue) + "<br/>份额待公布"; return fmtDate(v.axisValue) + "<br/>" + (v.value >= 0 ? "+" : "") + (+v.value).toFixed(2) + " 亿元"; } },
    grid: { left: 55, right: 20, top: 30, bottom: 50 },
    xAxis: { type: "category", data: dates },
    yAxis: { type: "value", name: "亿元" },
    dataZoom: dzOpts(),
    series: [{
      name: "净增持额", type: "bar", data: netData.map(function (d) { return d.value; }),
      itemStyle: { color: function (p) { return p.value == null ? "#999" : (p.value >= 0 ? "#e6492e" : "#2e8b57"); } },
    }],
  }));

  // 动态1行折叠：1行容量按 grid 实际列数(随视口宽度自适应)，超出进折叠，resize 重算
  setupOneRowToggle(ntGrid, [c1.getDom().parentElement, c2.getDom().parentElement, c3.getDom().parentElement], function (n) { return "更多图表（" + n + "）▼"; });
}

// ── 4层概览首屏：总览摘要条+矩阵热力图+卡片墙+叠加对比折线 ──
function renderNationalTeamOverview(container, data, qData, hData, rawData, snap) {
  var summary = ntBuildSummary(data, qData);

  // ▼ 第0层：国家队总盘（合计持仓市值+净增持+份额趋势，最顶部在摘要条之上）▼
  renderNationalTeamTotalPanel(container, data, snap);

  // ▼ 第1层：总览摘要条 ▼
  // 净流入=各ETF当日份额变动(亿份)×收盘价(元)求和=亿元；红流入绿流出
  var netInflow = summary.reduce(function (s, e) { return s + e.shareChangeYi * e.close; }, 0);
  var inflowCount = summary.filter(function (e) { return e.shareChangeYi > 0; }).length;
  var outflowCount = summary.filter(function (e) { return e.shareChangeYi < 0; }).length;
  var mostActive = summary.reduce(function (m, e) { return Math.abs(e.shareChangeYi) > Math.abs(m.shareChangeYi) ? e : m; }, summary[0]);
  var bar = document.createElement("div");
  bar.className = "nt-summary-bar";
  var netCls = netInflow >= 0 ? "nt-up" : "nt-down";
  var netSign = netInflow >= 0 ? "+" : "";
  bar.innerHTML =
    '<div class="nt-sum-item"><span class="nt-sum-label">净流入</span><span class="nt-sum-val ' + netCls + '">' + netSign + netInflow.toFixed(2) + ' 亿</span></div>' +
    '<div class="nt-sum-item"><span class="nt-sum-label">增持</span><span class="nt-sum-val nt-up">' + inflowCount + ' 只</span></div>' +
    '<div class="nt-sum-item"><span class="nt-sum-label">减持</span><span class="nt-sum-val nt-down">' + outflowCount + ' 只</span></div>' +
    '<div class="nt-sum-item"><span class="nt-sum-label">最活跃</span><span class="nt-sum-val">' + mostActive.code + ' ' + mostActive.name + '</span></div>';
  container.appendChild(bar);

  // ▼ 第2层：矩阵热力图 ▼
  // 12行×指标列，色阶着色：份额变动红流入/绿流出，机构占比高深色，放量倍数>1.5橙色
  // 标注就地 hover pop（data-tip 复用 .term-pop 事件委托）+ 点行弹 iframe 式满屏弹窗（不切页，保留滚动）
  var heatSec = document.createElement("div");
  heatSec.className = "chart-card nt-heatmap-card";
  heatSec.innerHTML = '<h3>12 只 ETF 资金矩阵 <span class="term-tip" data-tip="一屏看全12只：份额变动%(红=流入/绿=流出，色越深变动越大)、最新信号、机构占比%(深色=国家队主导>85%)、放量倍数(橙=成交活跃>1.5倍)。点行进单只详情。">❓</span></h3>';
  var heatWrap = document.createElement("div");
  heatWrap.className = "nt-heatmap-wrap";
  heatWrap.innerHTML = '<table class="nt-heatmap"><thead><tr>' +
    '<th>ETF</th><th>跟踪指数</th><th>份额变动%</th><th>最新信号</th><th>机构占比%</th><th>放量倍数</th>' +
    '</tr></thead><tbody></tbody></table>';
  heatSec.appendChild(heatWrap);
  container.appendChild(heatSec);
  var tbody = heatWrap.querySelector("tbody");
  summary.forEach(function (s) {
    var tr = document.createElement("tr");
    tr.className = "nt-heat-row";
    tr.onclick = function () { openNtDetailOverlay(s.code, rawData, qData, hData); };
    var scp = s.shareChangePct;
    var scpColor = scp > 0 ? "rgba(230,73,46," + Math.min(Math.abs(scp) / 5, 0.45).toFixed(2) + ")"
      : scp < 0 ? "rgba(46,139,87," + Math.min(Math.abs(scp) / 5, 0.45).toFixed(2) + ")" : "transparent";
    var inst = s.instPct;
    var instColor = inst != null ? "rgba(230,73,46," + (inst / 100 * 0.35).toFixed(2) + ")" : "transparent";
    var vr = s.volRatio;
    var vrColor = vr > 1.5 ? "rgba(255,152,0," + Math.min((vr - 1) / 2, 0.4).toFixed(2) + ")" : "transparent";
    // 信号标注就地 hover pop：data-tip 复用 .term-pop 事件委托，简短一句+点击查看详情
    var sigType = s.latestSig ? s.latestSig.type : null;
    var sigTxt;
    if (sigType === "share_surge") {
      sigTxt = '<span class="nt-sig-tip" data-tip="份额激增，疑似大资金进场。点击查看详情">🔴 进</span>';
    } else if (sigType === "share_outflow") {
      sigTxt = '<span class="nt-sig-tip" data-tip="份额流出，疑似大资金离场。点击查看详情">🟢 出</span>';
    } else if (sigType === "volume_surge") {
      sigTxt = '<span class="nt-sig-tip" data-tip="成交放量(份额未大动)，资金活跃。点击查看详情">🟠 量</span>';
    } else {
      sigTxt = '<span class="nt-sig-tip" data-tip="近期无大资金信号。点击查看详情">-</span>';
    }
    var scpSign = scp > 0 ? "+" : "";
    tr.innerHTML =
      '<td class="nt-cell-code">' + s.code + '<br><span class="nt-cell-name">' + s.name + '</span></td>' +
      '<td>' + s.index + '</td>' +
      '<td class="nt-cell-num" style="background:' + scpColor + '"><span data-tip="当日份额变动%，红流入绿流出。点击查看详情">' + scpSign + scp.toFixed(2) + '%</span></td>' +
      '<td>' + sigTxt + '</td>' +
      '<td class="nt-cell-num" style="background:' + instColor + '"><span data-tip="当季机构持有占比，>85%为国家队主导品种。点击查看详情">' + (inst != null ? inst.toFixed(1) + "%" : "-") + '</span></td>' +
      '<td class="nt-cell-num" style="background:' + vrColor + '"><span data-tip="当日成交额/前5日均量，>1.5倍为放量。点击查看详情">' + (vr ? vr.toFixed(2) + "倍" : "-") + '</span></td>';
    tbody.appendChild(tr);
  });

  // ▼ 第3层：卡片墙 ▼
  // 3×4网格(H5 2列)，每张迷你卡含 sparkline+份额变动%+信号标注，点卡片弹详情
  var wallSec = document.createElement("div");
  wallSec.className = "chart-card nt-wall-card";
  wallSec.innerHTML = '<h3>12 只 ETF 走势卡片墙 <span class="term-tip" data-tip="每张迷你卡片含份额折线(sparkline)+当日份额变动%+信号标注。🔴进=疑似大资金进场/🟢出=疑似离场/🟠量=放量。点卡片进单只详情。">❓</span></h3>';
  var wall = document.createElement("div");
  wall.className = "nt-card-wall";
  summary.forEach(function (s) {
    var card = document.createElement("div");
    card.className = "nt-mini-card clickable-card";
    card.onclick = function () { openNtDetailOverlay(s.code, rawData, qData, hData); };
    var spark = ntSparkline(s.daily, 120, 30);
    var scp = s.shareChangePct;
    var scpCls = scp > 0 ? "nt-up" : scp < 0 ? "nt-down" : "";
    var scpSign = scp > 0 ? "+" : "";
    var sigBadge = s.latestSig
      ? (s.latestSig.type === "share_surge" ? '<span class="nt-badge nt-badge-in" data-tip="份额激增，疑似大资金进场。点击查看详情">🔴</span>'
        : s.latestSig.type === "share_outflow" ? '<span class="nt-badge nt-badge-out" data-tip="份额流出，疑似大资金离场。点击查看详情">🟢</span>'
        : '<span class="nt-badge nt-badge-vol" data-tip="成交放量(份额未大动)，资金活跃。点击查看详情">🟠</span>')
      : "";
    card.innerHTML =
      '<div class="nt-mini-head"><span class="nt-mini-code">' + s.code + '</span><span class="nt-mini-name">' + s.name + '</span></div>' +
      '<div class="nt-mini-spark">' + spark + '</div>' +
      '<div class="nt-mini-foot"><span class="nt-mini-chg ' + scpCls + '" data-tip="当日份额变动%，红流入绿流出。点击查看详情">' + scpSign + scp.toFixed(2) + '%</span>' + sigBadge + '</div>';
    wall.appendChild(card);
  });
  wallSec.appendChild(wall);
  container.appendChild(wallSec);

  // ▼ 第4层：叠加对比折线 ▼
  // 12只ETF份额归一化为%(基准=各自最早日100%)，叠加看谁份额增长快/谁流出
  // 信号散点标在图上(🔴进/🟢出)，多只同时触发=汇金增持期共振
  var allDatesSet = {};
  data.etfs.forEach(function (e) { (e.daily || []).forEach(function (d) { allDatesSet[d.date] = 1; }); });
  var allDates = Object.keys(allDatesSet).sort();
  var overlaySeries = [];
  var sigPoints = [];
  var baseInfo = {};  // code -> {name, baseDate} 用于tooltip显示基准日
  data.etfs.forEach(function (e) {
    var daily = e.daily || [];
    if (!daily.length) return;
    var base = daily[0].fund_share_yi;
    if (!base) return;
    baseInfo[e.code] = { name: e.name, baseDate: daily[0].date };
    var lookup = {};
    daily.forEach(function (d) { lookup[d.date] = +(d.fund_share_yi / base * 100).toFixed(2); });
    overlaySeries.push({
      name: e.code, type: "line", smooth: true, symbol: "none", connectNulls: true,
      data: daily.map(function (d) { return [d.date, lookup[d.date]]; }),
      lineStyle: { width: 1.4 },
      emphasis: { focus: "series" },
    });
    daily.forEach(function (d) {
      (d.signals || []).forEach(function (sig) {
        if (sig.type === "share_surge" || sig.type === "share_outflow") {
          sigPoints.push({
            value: [d.date, lookup[d.date], e.code, sig.type === "share_surge" ? "进" : "出"],
            itemStyle: { color: sig.type === "share_surge" ? "#e6492e" : "#2e8b57" },
          });
        }
      });
    });
  });
  overlaySeries.push({ name: "信号", type: "scatter", data: sigPoints, symbolSize: 7, z: 10 });
  // YYYYMMDD -> YYYY-MM-DD（tooltip需带年份，与fmtDate的MM-DD区分）
  function fmtFull(s) { return s && s.length >= 8 ? s.substring(0,4) + "-" + s.substring(4,6) + "-" + s.substring(6,8) : (s || ""); }
  var overlayTitle = '12 只 ETF 份额归一化叠加（基准=最早日 100%）<span class="term-tip" data-tip="所有ETF份额除以各自最早日份额×100，叠加在同一图看谁被持续增持(线上行)/谁流出(线下行)。🔴点=进场信号/🟢点=离场信号，多只同时触发=汇金增持期共振。点图例切换显隐。">❓</span>';
  var c4 = mkCard(overlayTitle, 400, null, container);
  c4.setOption(withTheme({
    tooltip: {
      trigger: "item",
      formatter: function (p) {
        var v = p.value;
        if (!Array.isArray(v)) return p.seriesName;
        var code = p.seriesType === "scatter" ? v[2] : p.seriesName;
        var bi = baseInfo[code] || {};
        var nameStr = bi.name ? bi.name + " " + code : code;
        var baseStr = bi.baseDate ? "（基准 " + fmtFull(bi.baseDate) + "=100%）" : "";
        if (p.seriesType === "scatter") {
          return nameStr + " " + v[3] + "<br/>" + fmtFull(v[0]) + " 份额归一 " + (+v[1]).toFixed(1) + "%" + baseStr;
        }
        return nameStr + "<br/>" + fmtFull(v[0]) + " 份额归一 " + (+v[1]).toFixed(2) + "%" + baseStr;
      },
    },
    legend: { top: 0, type: "scroll" },
    grid: { left: 55, right: 20, top: 40, bottom: 50 },
    xAxis: { type: "category", data: allDates },
    yAxis: { type: "value", name: "归一化%" },
    dataZoom: dzOpts(),
    series: overlaySeries,
  }));
}

// ── 单只详情：保留原 ETF 选择器+5KPI+3图+信号表+汇金验证 ──
// opts.overlay=true 时为弹窗模式：返回按钮=关闭弹窗，选择器=重渲染弹窗内 detail（不切页）
function renderNationalTeamDetail(container, data, qData, hData, opts) {
  opts = opts || {};
  var isOverlay = !!opts.overlay;
  // 盘中快照(已在 renderNationalTeam @2883 / 页面加载 @5762 fetch,此处直接取 state 缓存供3图角标)
  var snap = state.intradaySnapshot;
  // 返回概览按钮（弹窗模式=关闭弹窗，保留滚动位置）
  var backBtn = document.createElement("button");
  backBtn.className = "nt-back-btn";
  backBtn.innerHTML = isOverlay ? "✕ 关闭" : "← 返回概览";
  backBtn.onclick = isOverlay
    ? function () { closeNtDetailOverlay(); }
    : function () { state.ntView = "overview"; renderNationalTeam(container); };
  container.appendChild(backBtn);

  // ── ETF 选择器（12只，按跟踪指数分组）──
  const selWrap = document.createElement("div");
  selWrap.className = "nt-selector";
  const idxOrder = ["上证50", "沪深300", "中证500", "中证1000", "创业板", "科创50"];
  const groups = {};
  data.etfs.forEach((e) => { (groups[e.index] = groups[e.index] || []).push(e); });
  idxOrder.forEach((idx) => {
    const list = groups[idx];
    if (!list) return;
    const grp = document.createElement("span");
    grp.className = "nt-grp-label";
    grp.textContent = idx;
    selWrap.appendChild(grp);
    list.forEach((e) => {
      const btn = document.createElement("button");
      btn.textContent = e.code;
      btn.title = `${e.code} ${e.name}（${e.index}）`;
      btn.dataset.code = e.code;
      if (e.code === state.ntEtf) btn.classList.add("active");
      btn.onclick = () => {
        state.ntEtf = e.code;
        if (isOverlay) {
          // 弹窗内切换ETF：清空旧内容+dispose旧ECharts，重渲染弹窗内 detail
          _disposeContainerCharts(container);
          container.innerHTML = "";
          renderNationalTeamDetail(container, data, qData, hData, opts);
        } else {
          renderNationalTeam(container);
        }
      };
      selWrap.appendChild(btn);
    });
  });
  container.appendChild(selWrap);

  // ── 选中 ETF ──
  const cur = data.etfs.find((e) => e.code === state.ntEtf) || data.etfs[0];
  const curQ = qData.etfs.find((e) => e.code === cur.code);
  const daily = cur.daily || [];

  // ── 顶部摘要 KPI ──
  const latest = cur.latest || daily[daily.length - 1] || {};
  const prev = daily.length >= 2 ? daily[daily.length - 2] : null;
  const qLatest = curQ && curQ.history && curQ.history.length ? curQ.history[curQ.history.length - 1] : null;
  const sigCount = daily.reduce((n, d) => n + (d.signals ? d.signals.length : 0), 0);
  const kpi = document.createElement("div");
  kpi.className = "nt-kpi";
  // 末日份额未发布(T+1时滞,交易所盘后次日才发)：最新份额用上一日估算+橙色标注,当日份额变动显示"待公布",避免"-"像坏了
  const shareMissing = latest.fund_share_yi == null;
  const chgMissing = latest.share_change_yi == null;
  const shareEst = prev && prev.fund_share_yi != null;
  const shareDisp = shareMissing
    ? (shareEst ? prev.fund_share_yi.toFixed(1) + " 亿份" : "份额待公布")
    : latest.fund_share_yi.toFixed(1) + " 亿份";
  const shareHint = shareMissing
    ? ' <span style="font-size:12px;color:#ff9800">份额待次日公布(' + _ntShareReplenishTxt(latest.date) + '补全)' + (shareEst ? "·用上日估算" : "") + "</span>"
    : "";
  const chgDisp = chgMissing
    ? "待公布"
    : (latest.share_change_yi >= 0 ? "+" : "") + latest.share_change_yi.toFixed(2) + " 亿份";
  const chgCls = chgMissing ? "" : (latest.share_change_yi >= 0 ? "nt-up" : "nt-down");
  const chgHint = chgMissing ? ' <span style="font-size:12px;color:#ff9800">份额待次日公布(' + _ntShareReplenishTxt(latest.date) + '补全)</span>' : "";
  const closeDisp = latest.close != null ? latest.close.toFixed(3) + " 元" : "-";
  const qDateTxt = qLatest ? qLatest.report_date.slice(0, 4) + "-" + qLatest.report_date.slice(4, 6) + "-" + qLatest.report_date.slice(6, 8) : "";
  const instDisp = qLatest && qLatest.inst_hold_pct != null ? qLatest.inst_hold_pct.toFixed(1) + "%" : "-";
  kpi.innerHTML =
    `<div class="nt-kpi-item"><div class="nt-kpi-label">最新份额</div><div class="nt-kpi-val">${shareDisp}${shareHint}</div></div>` +
    `<div class="nt-kpi-item"><div class="nt-kpi-label">当日份额变动</div><div class="nt-kpi-val ${chgCls}">${chgDisp}${chgHint}</div></div>` +
    `<div class="nt-kpi-item"><div class="nt-kpi-label">最新收盘价</div><div class="nt-kpi-val">${closeDisp}</div></div>` +
    `<div class="nt-kpi-item"><div class="nt-kpi-label">机构占比${qDateTxt ? "（" + qDateTxt + "）" : ""}</div><div class="nt-kpi-val">${instDisp}</div></div>` +
    `<div class="nt-kpi-item"><div class="nt-kpi-label">区间信号数</div><div class="nt-kpi-val">${sigCount}</div></div>`;
  container.appendChild(kpi);

  // 5图+信号明细表：动态1行折叠(700px最小宽度，视口自适应，resize重算)
  const grid = document.createElement("div");
  grid.className = "astock-top-grid";
  container.appendChild(grid);
  const topCards = [];

  // ── 图1: 份额变化趋势（亿份）+ 信号标注 ──
  // share_surge=红"进"（疑似大资金进场）/ share_outflow=绿"出"（疑似大资金离场）
  const shareData = daily.map((d) => [d.date, d.fund_share_yi]);
  const shareMarks = [];
  daily.forEach((d) => {
    if (!d.signals) return;
    if (d.signals.find((s) => s.type === "share_surge"))
      shareMarks.push({ coord: [d.date, d.fund_share_yi], value: "进", itemStyle: { color: "#e6492e" } });
    if (d.signals.find((s) => s.type === "share_outflow"))
      shareMarks.push({ coord: [d.date, d.fund_share_yi], value: "出", itemStyle: { color: "#2e8b57" } });
  });
  const shareTitle = `${cur.code} ${cur.name} 份额趋势（亿份）${latest.fund_share_yi != null ? `<span class="chart-latest"> · ${fmtDate(latest.date)} ${latest.fund_share_yi.toFixed(1)}亿份</span>` : ""}`;
  const c1 = mkCard(shareTitle, 320, null, grid);
  c1.setOption(withTheme({
    tooltip: { trigger: "axis" },
    grid: { left: 55, right: 20, top: 30, bottom: 50 },
    xAxis: { type: "category", data: daily.map((d) => d.date) },
    yAxis: { type: "value", scale: true, name: "亿份" },
    dataZoom: dzOpts(),
    series: [{
      name: "基金份额", type: "line", smooth: true, symbol: "none", connectNulls: true,
      data: shareData, lineStyle: { width: 1.8 },
      markPoint: { symbol: "pin", symbolSize: 36, label: { fontSize: 11, color: "#fff" }, data: shareMarks },
    }],
  }));
  topCards.push(c1.getDom().parentElement);
  addCardTimeBadge(c1.getDom().parentElement, latest.date, snap, "t1", "etf_date");

  // ── 图2: 收盘价(元) + 成交额(亿元) 双轴，volume_surge 标注 ──
  // volume_surge=橙"量"（成交额/5日均量>2倍，独立放量信号）
  const closeData = daily.map((d) => [d.date, d.close]);
  const amtData = daily.map((d) => [d.date, d.amount != null ? +(d.amount / 1e8).toFixed(2) : null]);
  const volMarks = [];
  daily.forEach((d) => {
    if (!d.signals) return;
    if (d.signals.find((s) => s.type === "volume_surge"))
      volMarks.push({ coord: [d.date, d.close], value: "量", itemStyle: { color: "#ff9800" } });
  });
  const priceTitle = `${cur.code} ${cur.name} 收盘价 / 成交额`;
  const c2 = mkCard(priceTitle, 320, null, grid);
  c2.setOption(withTheme({
    tooltip: { trigger: "axis" },
    legend: { top: 0, data: ["收盘价", "成交额"] },
    grid: { left: 55, right: 60, top: 35, bottom: 50 },
    xAxis: { type: "category", data: daily.map((d) => d.date) },
    yAxis: [
      { type: "value", scale: true, name: "元", position: "left" },
      { type: "value", scale: true, name: "亿元", position: "right" },
    ],
    dataZoom: dzOpts(),
    series: [
      { name: "收盘价", type: "line", smooth: true, symbol: "none", data: closeData, lineStyle: { width: 1.5 },
        markPoint: { symbol: "pin", symbolSize: 34, label: { fontSize: 11, color: "#fff" }, data: volMarks } },
      { name: "成交额", type: "bar", yAxisIndex: 1, data: amtData, itemStyle: { opacity: 0.4 } },
    ],
  }));
  topCards.push(c2.getDom().parentElement);
  addCardTimeBadge(c2.getDom().parentElement, latest.date, snap, "t1", "etf_date");

  // ── 图3: 季度持有人结构变化（机构/个人占比%）──
  if (curQ && curQ.history && curQ.history.length) {
    // 近5年（基于数据末日年份回推）
    const endYr = latest.date ? parseInt(latest.date.slice(0, 4), 10) : new Date().getFullYear();
    const hist = curQ.history.filter((h) => parseInt(h.report_date.slice(0, 4), 10) >= endYr - 5);
    const instData = hist.map((h) => [h.report_date, h.inst_hold_pct]);
    const retailData = hist.filter((h) => h.retail_hold_pct != null).map((h) => [h.report_date, h.retail_hold_pct]);
    // 持有人结构=半年报披露(报告期6/30、12/31)，滞后2-3月发布；不自走T+1滞后判定(>30天会误判⏸停更)
    var qLastRep = hist.length ? hist[hist.length - 1].report_date : "";
    var qLastFmt = qLastRep.length === 8 ? qLastRep.slice(0, 4) + "-" + qLastRep.slice(4, 6) + "-" + qLastRep.slice(6, 8) : qLastRep;
    var qBadgeMmdd = qLastRep.length === 8 ? qLastRep.slice(4, 6) + "-" + qLastRep.slice(6, 8) : qLastRep;
    var qFreqTip = "持有人结构数据每半年披露一次（报告期6/30、12/31），基金年报/半年报发布后2-3月更新。最新至" + qLastFmt;
    const qTitle = `${cur.code} ${cur.name} 持有人结构变化（%）` + termTip(qFreqTip);
    const c3 = mkCard(qTitle, 300, null, grid);
    c3.setOption(withTheme({
      tooltip: { trigger: "axis" },
      legend: { top: 0, data: ["机构占比", "个人占比"] },
      grid: { left: 55, right: 20, top: 35, bottom: 50 },
      xAxis: { type: "category", data: hist.map((h) => h.report_date) },
      yAxis: { type: "value", scale: true, name: "%", max: 100 },
      dataZoom: dzOpts(),
      series: [
        { name: "机构占比", type: "line", smooth: true, symbol: "circle", symbolSize: 5, data: instData, lineStyle: { width: 1.8 } },
        { name: "个人占比", type: "line", smooth: true, symbol: "circle", symbolSize: 5, data: retailData, lineStyle: { width: 1.5 } },
      ],
    }));
    topCards.push(c3.getDom().parentElement);
    // 持有人结构角标: 📅半年报(灰)，tip 注明半年披露频次（不走 addCardTimeBadge 的 T+1 滞后判定）
    var _qCard = c3.getDom().parentElement;
    if (_qCard && qBadgeMmdd) {
      _qCard.insertAdjacentHTML("beforeend",
        '<span class="card-time-badge stale-mark" data-tip="' + qFreqTip + '">📅 半年报·' + qBadgeMmdd + '</span>');
      _qCard.classList.add("has-time-badge");
    }
  }

  // ── 信号趋势：按月信号数堆叠柱状 + 强度散点（散户看大资金活跃度月度变化）──
  // 收集区间内所有信号，按月汇总次数 + 散点展示 z 强度
  const allSigs = [];
  daily.forEach((d) => { (d.signals || []).forEach((s) => allSigs.push({ date: d.date, ...s })); });
  if (allSigs.length) {
    // 按月汇总信号数（YYYYMM -> {进场/离场/放量}）
    const monthMap = {};
    allSigs.forEach((s) => {
      const m = s.date.slice(0, 6);
      monthMap[m] = monthMap[m] || { share_surge: 0, share_outflow: 0, volume_surge: 0 };
      if (monthMap[m][s.type] != null) monthMap[m][s.type]++;
    });
    const months = Object.keys(monthMap).sort();
    const monthLabels = months.map((m) => m.slice(0, 4) + "-" + m.slice(4));
    const sigTrendTitle = `${cur.code} ${cur.name} 信号趋势（按月汇总）` +
      termTip("每月大资金进场(红)/离场(绿)/放量(橙)信号次数堆叠，柱子越高当月越活跃");
    const c4 = mkCard(sigTrendTitle, 280, null, grid);
    c4.setOption(withTheme({
      tooltip: { trigger: "axis" },
      legend: { top: 0, data: ["疑似进场", "疑似离场", "放量"] },
      grid: { left: 45, right: 20, top: 35, bottom: 35 },
      xAxis: { type: "category", data: monthLabels },
      yAxis: { type: "value", name: "次数", minInterval: 1 },
      series: [
        { name: "疑似进场", type: "bar", stack: "sig", data: months.map((m) => monthMap[m].share_surge), itemStyle: { color: "#e6492e" } },
        { name: "疑似离场", type: "bar", stack: "sig", data: months.map((m) => monthMap[m].share_outflow), itemStyle: { color: "#2e8b57" } },
        { name: "放量", type: "bar", stack: "sig", data: months.map((m) => monthMap[m].volume_surge), itemStyle: { color: "#ff9800" } },
      ],
    }));
    topCards.push(c4.getDom().parentElement);
    // 信号强度散点：x=日期, y=z强度, 颜色按类型（z>=5极端/>=3显著/>=2轻度）
    const scatterByType = { share_surge: [], share_outflow: [], volume_surge: [] };
    allSigs.forEach((s) => {
      if (s.intensity != null && scatterByType[s.type]) {
        scatterByType[s.type].push([s.date, +s.intensity.toFixed(2)]);
      }
    });
    const intTitle = `${cur.code} ${cur.name} 信号强度分布（z-score）` +
      termTip("每条信号的z强度散点，z>=5极端>=3显著>=2轻度，越高越异常");
    const c5 = mkCard(intTitle, 260, null, grid);
    c5.setOption(withTheme({
      tooltip: { trigger: "item", formatter: (p) => `${p.data[0]}<br/>z = ${p.data[1]}` },
      legend: { top: 0, data: ["疑似进场", "疑似离场", "放量"] },
      grid: { left: 45, right: 20, top: 35, bottom: 50 },
      xAxis: { type: "category", data: daily.map((d) => d.date), axisLabel: { hideOverlap: true } },
      yAxis: { type: "value", name: "z强度", scale: true },
      dataZoom: dzOpts(),
      series: [
        { name: "疑似进场", type: "scatter", data: scatterByType.share_surge, symbolSize: 8, itemStyle: { color: "#e6492e" } },
        { name: "疑似离场", type: "scatter", data: scatterByType.share_outflow, symbolSize: 8, itemStyle: { color: "#2e8b57" } },
        { name: "放量", type: "scatter", data: scatterByType.volume_surge, symbolSize: 8, itemStyle: { color: "#ff9800" } },
      ],
    }));
    topCards.push(c5.getDom().parentElement);
  }

  // ── 信号明细表（近60日，按日期倒序）──
  const sigRows = [];
  daily.forEach((d) => { (d.signals || []).forEach((s) => sigRows.push({ date: d.date, ...s })); });
  sigRows.sort((a, b) => (a.date < b.date ? 1 : -1));
  const sigTypeText = { share_surge: "🔴 疑似进场", share_outflow: "🟢 疑似离场", volume_surge: "🟠 放量" };
  const sigCard = document.createElement("div");
  sigCard.className = "chart-card";
  let sigHtml = `<h3>${cur.code} ${cur.name} 信号明细（近60日，共 ${sigRows.length} 条）</h3>`;
  if (sigRows.length) {
    sigHtml += `<div class="nt-sig-table-wrap"><table class="nt-sig-table"><thead><tr>` +
      `<th>日期</th><th>类型</th><th>份额变动(亿份)</th><th>放量倍数</th><th>z强度</th><th>备注</th>` +
      `</tr></thead><tbody>`;
    sigRows.forEach((r) => {
      const sc = r.share_change != null ? (r.share_change / 1e8).toFixed(2) : "-";
      const ar = r.amount_ratio != null ? r.amount_ratio.toFixed(2) + "倍" : "-";
      const zi = r.intensity != null ? r.intensity.toFixed(2) : "-";
      sigHtml += `<tr><td>${fmtDate(r.date)}</td><td>${sigTypeText[r.type] || r.type}</td><td>${sc}</td><td>${ar}</td><td>${zi}</td><td><span class="nt-note" title="${(r.note || "").replace(/"/g, "&quot;")}">${r.note || ""}</span></td></tr>`;
    });
    sigHtml += `</tbody></table></div>`;
  } else {
    sigHtml += `<div class="placeholder-body">近60日无信号</div>`;
  }
  sigCard.innerHTML = sigHtml;
  grid.appendChild(sigCard);
  topCards.push(sigCard);
  // 动态1行折叠：1行容量按视口宽度自适应，超出进折叠，resize重算
  setupOneRowToggle(grid, topCards, (n) => `更多（${n}）▼`, true);

  // ── 关键事件与口径说明（含2023汇金增持期历史验证）──
  const evt = document.createElement("div");
  evt.className = "nt-banner";
  evt.innerHTML =
    `<h3>📌 关键事件与口径说明</h3>` +
    `<div class="nt-banner-body">` +
    `<b>2023年10月汇金增持（历史验证）</b>：2023-10-23 汇金宣布增持 ETF，本系统准确捕捉--510300 当日份额+9.9亿（z=4.62 显著异动）、510310 份额+4.3亿（z=7.47 极端异动）、159919 次日份额+3.8亿（z=9.00 极端异动）。510050 机构占比轨迹：2023年报68% -> 2024年报84% -> 2025年报91%（持续增持）。<br/>` +
    `<b>信号含义</b>：🔴疑似进场=份额增加且 z&gt;2 且放量1.5倍；🟢疑似离场=份额减少且 z&lt;-2 且放量1.5倍；🟠放量=成交额/5日均量&gt;2倍（独立信号）。z≥5 极端 / ≥3 显著 / ≥2 轻度。<br/>` +
    `<b>季度校准</b>：当季机构占比&gt;85% 置信×1.5（国家队主导品种）；&lt;60% 置信×0.7（散户主导噪声大）。持有人数据半年报+年报，滞后2-3月。` +
    `</div>`;
  container.appendChild(evt);

  // ── v2: 汇金/证金具名持有人（cninfo PDF 解析）──
  if (hData && hData.etfs) {
    var hCard = document.createElement("div");
    hCard.className = "nt-banner";
    var curEtf = null;
    for (var i = 0; i < hData.etfs.length; i++) {
      if (hData.etfs[i].code === state.ntEtf) { curEtf = hData.etfs[i]; break; }
    }
    var v2Html = '<h3>📊 汇金/证金具名持有人 <span class="term-tip" data-tip="数据来自巨潮资讯网(cninfo)年报/半年报PDF的§9.2期末上市基金前十名持有人表格,用pdfplumber解析。持有人类型按名称关键词识别:含中央汇金=汇金,含中国证券金融=证金,含全国社保基金=社保。仅深市5只ETF有cninfo orgId,沪市7只待补。">❓</span></h3>';
    v2Html += '<div class="nt-banner-body">';
    if (curEtf && curEtf.has_data && curEtf.reports && curEtf.reports.length) {
      var latestRep = curEtf.reports[0];
      var ntSum = latestRep.national_team_summary || {};
      var ntKeys = Object.keys(ntSum);
      v2Html += '<b>最新一期（报告期 ' + latestRep.report_date + '）国家队持股</b>：';
      if (ntKeys.length) {
        for (var k = 0; k < ntKeys.length; k++) {
          var s = ntSum[ntKeys[k]];
          v2Html += '<span style="color:var(--primary)">' + ntKeys[k] + '</span> ' + s.count + '席/合计<b>' + s.total_share_yi + '亿份</b>(' + s.total_pct + '%)、';
        }
        v2Html = v2Html.replace(/、$/, '');
      } else {
        v2Html += '<span style="opacity:0.7">前十大持有人中无国家队席位</span>';
      }
      v2Html += '<br/>';
      var ntHistoryCount = 0;
      curEtf.reports.forEach(function (rep) {
        rep.holders.forEach(function (h) { if (h.type !== '其他机构') ntHistoryCount++; });
      });
      if (ntHistoryCount > 0) {
        v2Html += '<details><summary>📜 ' + curEtf.name + ' 国家队持股历史轨迹（' + curEtf.reports.length + '期，' + ntHistoryCount + '条国家队记录）</summary>';
        v2Html += '<table class="nt-table"><thead><tr><th>报告期</th><th>持有人</th><th>类型</th><th>份额(亿份)</th><th>占比%</th><th>排名</th></tr></thead><tbody>';
        curEtf.reports.forEach(function (rep) {
          rep.holders.forEach(function (h) {
            if (h.type !== '其他机构') {
              v2Html += '<tr><td>' + rep.report_date + '</td><td>' + h.name + '</td><td style="color:var(--primary)">' + h.type + '</td><td>' + (h.hold_share_yi != null ? h.hold_share_yi : '-') + '</td><td>' + (h.hold_pct != null ? h.hold_pct : '-') + '</td><td>' + h.rank + '</td></tr>';
            }
          });
        });
        v2Html += '</tbody></table></details>';
      }
    } else {
      v2Html += '<b>' + (curEtf ? curEtf.name : state.ntEtf) + ' 暂无具名数据</b>：' + (curEtf ? curEtf.note || 'cninfo未收录该ETF的orgId' : '未找到') + '。<br/>';
      var hasData = hData.etfs.filter(function (e) { return e.has_data; });
      if (hasData.length) {
        v2Html += '其他有具名数据的ETF：';
        hasData.forEach(function (e) {
          var nt = e.latest_national_team || {};
          var ntDesc = Object.keys(nt).map(function (k) { return k + nt[k].total_share_yi + '亿份'; }).join('/');
          v2Html += e.name + '(' + ntDesc + ')、';
        });
        v2Html = v2Html.replace(/、$/, '');
      }
    }
    v2Html += '</div>';
    if (hData.events && hData.events.length) {
      v2Html += '<details style="margin-top:8px"><summary>🏛 历史汇金/证金公开增持事件（' + hData.events.length + '件，基于新华社/证监会公告整理）</summary>';
      v2Html += '<div class="nt-banner-body">';
      hData.events.forEach(function (ev) {
        v2Html += '<b>' + ev.date + '</b> <span style="color:var(--primary)">' + ev.actor + '</span> ' + ev.action + '：<span style="opacity:0.85">' + ev.note + '</span> <i style="opacity:0.6">(' + ev.source + ')</i><br/>';
      });
      v2Html += '</div></details>';
    }
    hCard.innerHTML = v2Html;
    container.appendChild(hCard);
  }
}

async function renderAStock(container = content) {
  let r;
  try {
    r = await fetchJSON(`./data/a-stock-${state.range}.json`);
  } catch (e) {
    renderErrorState(container, e, () => renderAStock(container));
    return;
  }
  container.innerHTML = "";
  // 拉取盘中快照，供走势卡角标判断盘中/收盘状态（1.5s 超时兜底，不阻塞渲染）
  try { await Promise.race([fetchIntradaySnapshot(), new Promise((r) => setTimeout(r, 1500))]); } catch {}
  const snap = state.intradaySnapshot;
  container.insertAdjacentHTML("beforeend", '<div class="home-purpose-note">💡 <b>这板块有什么用</b>:A股全景指标:涨停连板(打板情绪)+涨跌家数(市场广度)+资金面(北向/融资/主力)+波动率/换手率(活跃度)。综合判断A股冷热。</div>');
  const groups = {
    "涨停/跌停/连板/炸板数": ["a_width_zt_count", "a_width_dt_count", "a_width_max_lianban", "a_width_zb_count"],
    "市场宽度（涨跌家数）": ["a_width_up_count", "a_width_down_count"],
    "资金面": ["a_fund_north", "a_fund_margin", "a_fund_main", "a_amount"],
    "情绪指数（波指/换手率）": ["a_qvix_300", "a_qvix_1000", "a_turnover_rate"],
    "炸板率/封板率/打板溢价": ["a_width_zhaban_rate", "a_width_fengban_rate", "a_width_daban_premium"],
    "换手率分布分位数（%，BaoStock 全市场）": ["a_turnover_mean", "a_turnover_median", "a_turnover_p90", "a_turnover_p10"],
    "换手率>5%家数占比（0-1，活跃度分化）": ["a_turnover_gt5_pct"],
    "股息率": ["a_div_yield"],
    "龙虎榜": ["lhb_count", "lhb_inst_net"],
    "解禁/IPO/可转债": ["unlock_amount", "unlock_count", "ipo_count", "ipo_amount", "cov_count", "cov_premium_median"],
  };
  const groupHints = {
    "资金面": "注：北向资金数据源自 2024 年 8 月起停更（东财停止实时披露），该序列冻结在 2024-08-16，1 年期窗口内为空属正常。",
    "龙虎榜": "注：龙虎榜为T+1数据，东财盘后18点后更新当日；机构净额=上榜个股机构买入-卖出。",
    "解禁/IPO/可转债": "注：解禁/IPO/可转债为低频事件型数据，按事件日更新，窗口内多数日期无新增。",
  };
  // 各分组序列短标签（标题后缀用，避免长名堆积）：id -> 短标签
  const groupLabels = {
    "涨停/跌停/连板/炸板数": { a_width_zt_count: "涨停", a_width_dt_count: "跌停", a_width_max_lianban: "连板", a_width_zb_count: "炸板" },
    "市场宽度（涨跌家数）": { a_width_up_count: "涨", a_width_down_count: "跌" },
    "资金面": { a_fund_north: "北向", a_fund_margin: "融资", a_fund_main: "主力", a_amount: "成交" },
    "炸板率/封板率/打板溢价": { a_width_zhaban_rate: "炸板", a_width_fengban_rate: "封板", a_width_daban_premium: "打板" },
    "情绪指数（波指/换手率）": { a_qvix_300: "波指300", a_qvix_1000: "波指1000", a_turnover_rate: "换手" },
    "换手率分布分位数（%，BaoStock 全市场）": { a_turnover_mean: "均值", a_turnover_median: "中位", a_turnover_p90: "P90", a_turnover_p10: "P10" },
    "换手率>5%家数占比（0-1，活跃度分化）": { a_turnover_gt5_pct: ">5%占比" },
    "股息率": { a_div_yield: "股息率" },
    "龙虎榜": { lhb_count: "上榜", lhb_inst_net: "机构" },
    "解禁/IPO/可转债": { unlock_amount: "解禁", unlock_count: "解禁家数", ipo_count: "IPO", ipo_amount: "募资额", cov_count: "可转债", cov_premium_median: "溢价率" },
  };
  // 构建带短标签的 series 并追加最新值后缀到标题
  function buildSeries(g, ids) {
    const labels = groupLabels[g] || {};
    return ids.map((id) => {
      const m = (r.metrics && r.metrics[id]) || null;
      return m ? { name: m.name, data: m.data, label: labels[id] } : null;
    }).filter(Boolean);
  }
  const entries = Object.entries(groups);
  // 分组级术语解释（多序列图无法给单个 series 加 termTip，故在分组标题统一解释组内黑话）
  const groupTermTips = {
    "炸板率/封板率/打板溢价": "炸板率=当日炸板数÷曾涨停数(高=封板失败多,打板情绪弱);封板率=涨停封住数÷曾涨停数(高=封板成功多,与炸板率互补);打板溢价=次日开盘相对前日涨停价的溢价(正=打板次日有肉,负=易亏)。",
    "情绪指数（波指/换手率）": "波指=中国波指(期权隐含波动率),即A股'恐慌指数'。飙升=恐慌升,低位=平静。",
    "换手率分布分位数（%，BaoStock 全市场）": "P90/P10=全市场换手率90/10分位数。P90高=90%的股票换手率低于此值,衡量活跃度极端值。",
  };
  // 市场指标走势图：全部渲染入 astock-top-grid，再按视口宽度动态1行折叠(1行容量随宽度自适应，超出进折叠，resize 重算)
  const grid2col = document.createElement("div");
  grid2col.className = "astock-top-grid";
  container.appendChild(grid2col);
  const topCards = [];
  for (const [g, ids] of entries) {
    const series = buildSeries(g, ids);
    if (series.length && series.some((s) => s.data.length)) {
      const chart = lineChart(g + (groupTermTips[g] ? termTip(groupTermTips[g]) : "") + latestSuffixMulti(series), series, {}, groupHints[g] || null, grid2col);
      if (chart) {
        let lastDate = "";
        for (const s of series) { if (s && s.data && s.data.length) { const d = s.data[s.data.length - 1]; if (d && d.date && d.date > lastDate) lastDate = d.date; } }
        addCardTimeBadge(chart.getDom().parentElement, lastDate, snap, "t0");
        topCards.push(chart.getDom().parentElement);
      }
    }
  }
  // 动态1行折叠：1行容量按 grid 实际列数(随视口宽度自适应)，超出进折叠，resize 重算
  setupOneRowToggle(grid2col, topCards, (n) => `更多指标（${n}）▼`);
  // 指数折线区：筛选条移到本区前（紧挨指数折线），筛选时局部刷新（不 refetch、不动上方 KPI/宽度/资金面）
  // 动态1行折叠：1行容量按视口宽度自适应(窄屏1个/宽屏4-6个)，上证指数首个上浮首屏，resize 重算
  const indicesSection = document.createElement("div");
  indicesSection.className = "indices-section";
  container.appendChild(indicesSection);
  // 静态版 fetcher：读 index/{id}-all.json 全历史，前端按 ohlc 日期范围过滤 signals
  await renderIndicesSection(indicesSection, r.indices, async (id, idx) => {
    const raw = await fetchJSON(`./data/index/${id}-all.json`);
    return { signals: filterSignalsByRange(raw.signals, idx.data), stats: raw.stats };
  }, true);
}

// 港股快照 code -> index_id 映射（与 intraday_snapshot.py 的 _SNAPSHOT_TO_INDEX_ID 一致）。
// 腾讯 v_r_hkHSI 经 _parse_tencent 提取后 key="hkHSI"（r_ 前缀被 split("_")[-1] 吃掉）。
const _HK_SNAP_TO_IID = {
  hkHSI: "hsi",
  hkHSTECH: "hstech",
  hkHSCEI: "hscei",
};

// 把盘中快照的港股实时数据注入到 hk-*.json 返回的 indices 中。
// 快照日期 >= indices 最新日期时追加/替换最新点为快照实时值，让港股卡片显示当日实时涨跌。
// 同时标记 _snap_intraday=true（港股未收盘时）供前端显示"盘中实时"标签。
function _injectHkSnapshot(indices, snap) {
  if (!snap || !snap.indices) return indices;
  const snapHkMap = {};
  for (const si of snap.indices) {
    const iid = _HK_SNAP_TO_IID[si.code];
    if (iid && si.pct_change != null) {
      const snapDate = (si.datetime || "").slice(0, 8);
      if (snapDate) snapHkMap[iid] = { si, snapDate };
    }
  }
  const out = {};
  for (const [id, idx] of Object.entries(indices || {})) {
    const entry = snapHkMap[id];
    if (!entry) { out[id] = idx; continue; }
    const { si, snapDate } = entry;
    const newData = [...(idx.data || [])];
    const snapPt = {
      date: snapDate,
      open: si.open, high: si.high, low: si.low,
      close: si.price, pct_change: si.pct_change, amount: null,
    };
    const lastPt = newData.length ? newData[newData.length - 1] : null;
    if (!lastPt || lastPt.date < snapDate) {
      newData.push(snapPt);
    } else if (lastPt.date === snapDate) {
      newData[newData.length - 1] = { ...lastPt, ...snapPt };
    }
    out[id] = { ...idx, data: newData, _snap_intraday: si.is_closed === false };
  }
  return out;
}

async function renderHK(container = content) {
  let r;
  try {
    r = await fetchJSON(`./data/hk-${state.range}.json`);
  } catch (e) {
    renderErrorState(container, e, () => renderHK(container));
    return;
  }
  container.innerHTML = "";
  // 等快照就绪，注入港股实时数据 + 供走势卡角标判断盘中/收盘状态
  try { await Promise.race([fetchIntradaySnapshot(), new Promise((r) => setTimeout(r, 1500))]); } catch {}
  const snap = state.intradaySnapshot;
  container.insertAdjacentHTML("beforeend", '<div class="home-purpose-note">💡 <b>这板块有什么用</b>:看港股(恒生/恒生科技/国企)走势+买卖点,叠加港股通南向资金(内地资金买港股的通道,净流入=看好港股)。另含港股板块指数。</div>');
  if (r.hk_south && r.hk_south.length) {
    const hks = r.hk_south.map((d) => ({ date: d.date, value: d.value }));
    const chart = lineChart("港股通净买入（亿元）" + termTip("港股通南向资金净买入。内地投资者借港股通通道买港股,净流入为正=内地资金净买入港股(看好)。T+1数据。") + latestSuffixPct(hks), hks, {}, null, container);
    if (chart) addCardTimeBadge(chart.getDom().parentElement, hks.length ? hks[hks.length - 1].date : "", snap, "t1", "hk_south");
  }
  const indices = _injectHkSnapshot(r.indices, snap);
  // 指数折线区：筛选条移到本区前，筛选时局部刷新
  const indicesSection = document.createElement("div");
  indicesSection.className = "indices-section";
  container.appendChild(indicesSection);
  await renderIndicesSection(indicesSection, indices, async (id, idx) => {
    const raw = await fetchJSON(`./data/index/${id}-all.json`);
    return { signals: filterSignalsByRange(raw.signals, idx.data), stats: raw.stats };
  }, true);
  // 港股板块指数（复用 renderIndustryGrid，与 A 股行业网格一致）
  if (r.hk_industries && Object.keys(r.hk_industries).length) {
    const hkIndWrap = document.createElement("div");
    hkIndWrap.className = "sw-grid-wrap";
    container.appendChild(hkIndWrap);
    const hdr = document.createElement("h3");
    hdr.className = "section-title";
    hdr.textContent = "港股板块指数";
    hkIndWrap.appendChild(hdr);
    renderIndustryGrid(r.hk_industries, hkIndWrap);
  }
}

// 美股期货 ES/NQ 预期提示条：亚盘实时期货价 + 涨跌幅 + 预估美股当晚方向。
// 读 intraday_snapshot.us_futures（盘中快照采集时注入）。无数据不渲染。
// ES↔标普500 / NQ↔纳指100，相关性≈0.95；阈值±0.3%判预涨/预跌/持平。
function _renderUSFuturesExpect(snap, container) {
  const usf = snap && snap.us_futures;
  if (!usf || !Object.keys(usf).length) return;
  const items = [];
  for (const code of ["hf_ES", "hf_NQ"]) {
    const d = usf[code];
    if (!d || d.price == null) continue;
    const chg = d.chg_pct;
    const chgCls = chg > 0 ? "up" : chg < 0 ? "down" : "flat";
    const chgTxt = (chg != null ? ((chg >= 0 ? "+" : "") + chg.toFixed(2) + "%") : "-");
    const expect = d.expect || "持平";
    const expectCls = expect === "预涨" ? "up" : expect === "预跌" ? "down" : "flat";
    items.push(
      `<div class="usf-item">
        <span class="usf-name">${d.target_name || d.name}</span>
        <span class="usf-fname">${d.name || ""}</span>
        <span class="usf-price">${d.price.toFixed(2)}</span>
        <span class="usf-chg ${chgCls}">${chgTxt}</span>
        <span class="usf-arrow">-></span>
        <span class="usf-expect ${expectCls}">${expect}</span>
      </div>`);
  }
  if (!items.length) return;
  const time = (usf.hf_ES && usf.hf_ES.time) || (usf.hf_NQ && usf.hf_NQ.time) || "";
  const div = document.createElement("div");
  div.className = "us-futures-expect";
  div.innerHTML =
    `<div class="usf-head">
      <span class="usf-title">🇺🇸 美股预期</span>
      <span class="usf-sub">期货亚盘实时 · 预估美股当晚方向（ES↔标普500 / NQ↔纳指100，相关性≈0.95）</span>
    </div>
    <div class="usf-items">${items.join("")}</div>`;
  container.appendChild(div);
  // 时间角标：ES/NQ 期货报价时间（亚盘实时），参考 addCardTimeBadge 机制用 card-time-badge 角标
  if (time) {
    div.insertAdjacentHTML("beforeend", `<span class="card-time-badge intraday" data-tip="美股期货亚盘实时报价时间">⏰ ${time}</span>`);
    div.classList.add("has-time-badge");
  }
}

async function renderGlobal(container = content) {
  let r;
  try {
    r = await fetchJSON(`./data/global-${state.range}.json`);
  } catch (e) {
    renderErrorState(container, e, () => renderGlobal(container));
    return;
  }
  container.innerHTML = "";
  // 拉取盘中快照，供走势卡角标判断盘中/收盘状态（1.5s 超时兜底，不阻塞渲染）
  try { await Promise.race([fetchIntradaySnapshot(), new Promise((r) => setTimeout(r, 1500))]); } catch {}
  const snap = state.intradaySnapshot;
  container.insertAdjacentHTML("beforeend", '<div class="home-purpose-note">💡 <b>这板块有什么用</b>:看全球主要指数+商品/国债/汇率等风险资产。美股期货(ES/NQ)亚盘实时预估美股当晚开盘方向。商品/国债T+1。</div>');
  // M2：r.indices 已有 || {} 兜底；为空时显示空数据提示而非静默空白
  const idxEntries = Object.entries(r.indices || {});
  if (!idxEntries.length) {
    const note = document.createElement("div");
    note.className = "empty-note";
    note.textContent = "暂无全球指数数据";
    container.appendChild(note);
  }
  // 全球指数 + extras(黄金/原油/QVIX/国债等)统一套一个 .indices-grid 3列网格流式排开，
  // 纳斯达克/黄金等同处一个 grid 流，PC 宽屏按 3 列顺序排列(避免指数区与 extras 区分两个 grid 致不在一行)
  // 美股期货预期提示条（亚盘实时，放网格上方，美股指数区旁）
  _renderUSFuturesExpect(snap, container);
  const cardGrid = document.createElement("div");
  cardGrid.className = "indices-grid";
  container.appendChild(cardGrid);
  if (idxEntries.length) {
    const sigResults = await Promise.all(
      idxEntries.map(([id]) => fetchJSON(`./data/index/${id}-all.json`).catch(() => null))
    );
    idxEntries.forEach(([id, idx], i) => {
      const sig = sigResults[i] || { signals: [], stats: {} };
      const sigs = filterSignalsByRange(sig.signals, idx.data);
      if (idx.data && idx.data.length) {
        const chart = indexChart(idx.name, idx.data, sigs, sig.stats, idx.strategy, cardGrid, charts, id);
        if (chart) addCardTimeBadge(chart.getDom().parentElement, idx.data.length ? idx.data[idx.data.length - 1].date : "", snap, id && id.startsWith("us_") ? "t1" : "t0", id && id.startsWith("us_") ? "us_dji_date" : "");
      }
    });
  }
  const extras = {
    gold: "黄金（元/克）",
    oil: "原油（元/桶）",
    wti_oil: "WTI原油（美元/桶）",
    comex_silver: "COMEX白银（美元/盎司）",
    usdcnh: "离岸人民币",
    a_qvix_300: "中国波指300",
    a_qvix_1000: "中国波指1000",
    cn10y: "中国10年国债收益率（%）",
    us10y: "美国10年国债收益率（%）",
    cn_us_spread: "中美利差(10Y)（%）",
    brent: "布伦特原油（美元/桶）",
  };
  const extrasSignals = r.extras_signals || {};
  const extrasStats = r.extras_stats || {};
  const extrasStrategy = r.extras_strategy || {};
  // 全球 extras 黑话解释（QVIX/国债/利差等专业术语）
  const extrasTermTips = {
    a_qvix_300: "中国波指(50ETF期权隐含波动率),类似美股VIX恐慌指数。飙升=市场恐慌预期升,低位=情绪平稳。T+1。",
    a_qvix_1000: "中国波指(300ETF/1000ETF期权隐含波动率),类似美股VIX恐慌指数。飙升=市场恐慌预期升,低位=情绪平稳。T+1。",
    cn_us_spread: "中国10年国债收益率-美国10年国债收益率。为负=美债收益更高,资金倾向流向美国;走扩/收窄影响人民币汇率与跨境资金。",
    us10y: "美国10年国债收益率,全球资产定价锚。上升常压制成长股/黄金,关注其拐点。T+1(常停T-3)。",
  };
  for (const [id, name] of Object.entries(extras)) {
    const data = r.extras[id] || [];
    if (data.length) {
      const chart = valueChartWithSignals(name + (extrasTermTips[id] ? termTip(extrasTermTips[id]) : "") + latestSuffixPct(data), data, extrasSignals[id] || [], {}, extrasStats[id], extrasStrategy[id], id, cardGrid);
      if (chart) {
        const lastDate = data.length ? data[data.length - 1].date : "";
        if (dataStaleDays(lastDate) > STALE_DAYS) addStaleMark(chart.getDom().parentElement, lastDate);
        else {
          // usdcnh=离岸人民币实时(T+0); 其余 extras=商品/国债/QVIX(T+1)
          // T+1 srcKey 映射: oil/wti_oil/silver/brent->gold, qvix_1000->a_qvix_300, us10y/spread->cn10y
          const _t0Extra = id === "usdcnh";
          const _srcKey = _t0Extra ? "" : ({ oil: "gold", wti_oil: "gold", comex_silver: "gold", brent: "gold", a_qvix_1000: "a_qvix_300", us10y: "cn10y", cn_us_spread: "cn10y" }[id] || id);
          addCardTimeBadge(chart.getDom().parentElement, lastDate, snap, _t0Extra ? "t0" : "t1", _srcKey);
        }
      }
    }
  }
}

// 情绪分组成因子展开区：显示最新一天的 components（rsi/涨跌幅/炸板率等子因子），散户白话标签
// per-index 多数只有 rsi/pct_change 两项，信息量有限，展开区简洁展示即可（默认折叠）
const _COMP_NAMES = {
  rsi: "RSI", pct_change: "涨跌幅", qvix: "恐慌波动", volume: "量偏离",
  ratio: "涨跌比", zt: "涨停热度", zhaban: "炸板率", lianban: "连板", amount: "成交活跃",
  label: "恐贪标签", available_scores: "可用分项",
  // 跨市场综合评分组成维度（按指标分组归一化均值 0-100）
  a_width: "A股宽度", a_fund: "资金面", a_sentiment: "A股情绪",
  hk: "港股", global: "全球", lhb: "龙虎榜", unlock: "解禁", ipo: "IPO", cov: "可转债",
};
// 各分项权重（A股综合情绪分 a_sentiment 为固定加权,缺项按可用重归一化;
//  per-index 情绪分/跨市场评分/恐贪指数为等权,未列入的 key 显示"等权"）
const _COMP_WEIGHTS = {
  ratio: "25%", zt: "20%", zhaban: "15%", lianban: "15%", amount: "10%", north: "15%",
};
function _fmtComp(k, v) {
  if (k === "label") return String(v); // 恐贪标签为中文（极度恐惧/恐惧/中性/贪婪/极度贪婪），原样返回不走数字格式
  if (v == null || isNaN(v)) return "-";
  const n = Number(v);
  if (k === "pct_change" || k === "zhaban") return n.toFixed(1) + "%";
  if (k === "available_scores") return n + " 项"; // 恐贪等权 8 分项中当日有值数量
  return n.toFixed(1);
}
function appendComponentsBlock(data, tipText, container = content) {
  const last = data[data.length - 1];
  if (!last || !last.components) return;
  let comp;
  try { comp = typeof last.components === "string" ? JSON.parse(last.components) : last.components; } catch (e) { return; }
  const keys = Object.keys(comp);
  if (!keys.length) return;
  // 判断是否有固定权重(a_sentiment 的6分项),决定是否展示权重说明
  const hasFixedWeights = keys.some((k) => _COMP_WEIGHTS[k]);
  const chips = keys.map((k) => {
    const name = _COMP_NAMES[k] || k;
    const wt = _COMP_WEIGHTS[k] || "等权";
    return `<span class="comp-item"><span class="comp-k">${name}</span><span class="comp-v">${_fmtComp(k, comp[k])}</span><span class="comp-w" data-tip="${wt === "等权" ? "等权平均" : "固定权重(缺项按可用重归一化)"}">${wt}</span></span>`;
  }).join("");
  const weightNote = hasFixedWeights
    ? '<div class="comp-weight-note">权重为名义值；当日缺项时按可用分项重归一化。北向资金自2024-08起停更,保留历史权重。</div>'
    : '<div class="comp-weight-note">各分项等权平均。</div>';
  const div = document.createElement("div");
  div.className = "comp-block";
  div.innerHTML = `<details><summary>组成因子${termTip(tipText || "情绪分由这些因子综合计算")}<span class="comp-date"> · ${fmtDate(last.date)}</span></summary><div class="comp-list">${chips}</div>${weightNote}</details>`;
  container.appendChild(div);
}

async function renderSentiment() {
  // 期货数据与情绪数据无依赖，用 Promise.all 并发请求；futures 失败不影响情绪图（独立 .catch）
  const [r, futures] = await Promise.all([
    fetchJSON(`./data/sentiment-${state.range}.json`),
    fetchJSON("./data/futures.json").catch(() => null),
  ]);
  content.innerHTML = "";
  content.insertAdjacentHTML("beforeend", '<div class="home-purpose-note">💡 <b>这板块有什么用</b>:把多项情绪指标合成0-100的温度计,量化市场冷热(≤20冰点、≥80过热),作逆向参考。<b>怎么解读</b>:≤20冰点(人人恐慌)=逆向贪婪逐步买,≥80过热(人人贪婪)=逆向恐惧准备卖;中间区域观望或顺势。</div>');
  const sig = r.signals || {};
  const stats = r.stats || {};
  const strat = r.strategy || {};
  // 拉取盘中快照，供情绪大卡右上角角标判断盘中/收盘状态（1.5s 超时兜底，不阻塞渲染）
  try { await Promise.race([fetchIntradaySnapshot(), new Promise((r) => setTimeout(r, 1500))]); } catch {}
  const snap = state.intradaySnapshot;

  // 冰点/过热热力图（一眼全局，放最前面）
  renderSentimentHeatmap(r, snap);

  // 情绪图表区套 .indices-grid 3列网格(与A股/港股/全球同布局)，每张图+组成因子配对一个 grid cell
  const cardGrid = document.createElement("div");
  cardGrid.className = "indices-grid";
  content.appendChild(cardGrid);

  // 恐贪指数（市场温度计）
  if (r.fear_greed && r.fear_greed.length) {
    const data = r.fear_greed.map((d) => ({ date: d.date, value: d.value, components: d.components }));
    const latest = data[data.length - 1] && data[data.length - 1].value;
    const title = `😱😐😤 恐贪指数（0-100）` + termTip("综合5类市场情绪(波动率/动量/强度/广度/避险)等权算的0-100温度计。≤25极度恐惧(人人抛售,常近底)、≥75极度贪婪(人人追高,常近顶)。作逆向参考:恐惧时贪婪、贪婪时恐惧。") + (latest != null ? " · " + fearGreedLabel(latest) + latestSuffixPct(data) : "");
    const cell = document.createElement("div");
    cardGrid.appendChild(cell);
    const chart = valueChartWithSignals(title, data, [], {
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
    }, undefined, undefined, undefined, cell);
    addCardTimeBadge(chart.getDom().parentElement, data.length ? data[data.length - 1].date : "", snap, "t0");
    appendComponentsBlock(data, undefined, cell);
  }

  if (r.a_sentiment && r.a_sentiment.length) {
    const data = r.a_sentiment.map((d) => ({ date: d.date, value: d.value, components: d.components }));
    const latest = data[data.length - 1] && data[data.length - 1].value;
    const title = `A股综合情绪分（0-100）` + termTip("6项A股指标加权(涨跌比25%+涨停热度20%+炸板率15%+连板15%+成交10%+北向15%,缺项按可用重归一化)算的0-100。≤20冰点(恐慌极值)、≥80过热(亢奋极值)。点'组成因子'看各分项。") + (latest != null ? " · " + sentimentTag(latest) + latestSuffixPct(data) : "");
    const cell = document.createElement("div");
    cardGrid.appendChild(cell);
    const chart = valueChartWithSignals(title, data, sig.a_sentiment || [], {}, stats.a_sentiment, strat.a_sentiment, undefined, cell);
    addCardTimeBadge(chart.getDom().parentElement, data.length ? data[data.length - 1].date : "", snap, "t0");
    appendComponentsBlock(data, undefined, cell);
  }
  // 细分指数：散户关注度排序（小盘/成长优先）
  const idxNames = {
    sentiment_csi1000: '中证1000情绪分',
    sentiment_cyb: '创业板情绪分',
    sentiment_kc50: '科创50情绪分',
    sentiment_csi500: '中证500情绪分',
    sentiment_hs300: '沪深300情绪分',
    sentiment_sz50: '上证50情绪分',
  };
  for (const [key, baseTitle] of Object.entries(idxNames)) {
    if (r[key] && r[key].length) {
      const data = r[key].map(d => ({date: d.date, value: d.value, components: d.components}));
      const latest = data[data.length - 1] && data[data.length - 1].value;
      const title = `${baseTitle}（0-100）` + termTip("该指数RSI+涨跌幅等权算的0-100情绪温度计(等权,非加权)。≤20冰点≥80过热。比A股综合情绪分更聚焦单只指数。") + (latest != null ? " · " + sentimentTag(latest) + latestSuffixPct(data) : "");
      const cell = document.createElement("div");
      cardGrid.appendChild(cell);
      const chart = valueChartWithSignals(title, data,
        sig[key] || [], {
          visualMap: {
            show: false,
            pieces: [{ lte: 20, color: "#e6492e" }, { gt: 20, lte: 80, color: "#5b8ff9" }, { gt: 80, color: "#2e8b57" }],
            dimension: 1,
          },
        }, stats[key], strat[key], undefined, cell);
      addCardTimeBadge(chart.getDom().parentElement, data.length ? data[data.length - 1].date : "", snap, "t0");
      appendComponentsBlock(data, undefined, cell);
    }
  }
  if (r.cross_market && r.cross_market.length) {
    const data = r.cross_market.map((d) => ({ date: d.date, value: d.value, components: d.components }));
    const latest = data[data.length - 1] && data[data.length - 1].value;
    const title = `跨市场综合评分（0-100）` + termTip("A股+港股+全球+龙虎榜+解禁+IPO+可转债等维度等权均值0-100。范围比A股情绪分更广,看跨市场整体冷热。") + (latest != null ? " · " + sentimentTag(latest) + latestSuffixPct(data) : "");
    const cell = document.createElement("div");
    cardGrid.appendChild(cell);
    const chart = valueChartWithSignals(title, data, sig.cross_market || [], {
      visualMap: {
        show: false,
        pieces: [{ lte: 20, color: "#e6492e" }, { gt: 20, lte: 80, color: "#5b8ff9" }, { gt: 80, color: "#2e8b57" }],
        dimension: 1,
      },
    }, stats.cross_market, strat.cross_market, undefined, cell);
    addCardTimeBadge(chart.getDom().parentElement, data.length ? data[data.length - 1].date : "", snap, "t0");
    appendComponentsBlock(data, undefined, cell);
  }
  // 期货机构持仓（已在上方与 sentiment 并发拉取，渲染在情绪图之后保持顺序）
  if (futures && futures.positions && futures.positions.length) renderFuturesSection(futures, snap);
}

// 情绪冰点/过热热力图：X 轴=日期，Y 轴=指数名，色块=红(冰点≤20)/绿(过热>80)/灰(中性)
function renderSentimentHeatmap(r, snap) {
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

  // 计算最新日期的冰点/过热统计
  let hmSuffix = "";
  if (dates.length) {
    const latestDate = dates[dates.length - 1];
    let coldCount = 0;
    let hotCount = 0;

    // 遍历所有指数，获取最新日期的值
    for (const { key } of idxNames) {
      const series = idxData[key] || [];
      // 从后往前找最新日期的数据
      for (let i = series.length - 1; i >= 0; i--) {
        const d = series[i];
        if (d.date === latestDate) {
          if (d.value <= 20) coldCount++;
          else if (d.value > 80) hotCount++;
          break;
        }
      }
    }

    hmSuffix = `<span class="chart-latest"> · ${fmtDate(latestDate)} 冰点${coldCount} 过热${hotCount}</span>`;
  }

  div.innerHTML = `<h3>🔥 指数情绪冰点/过热热力图${hmSuffix}${termTip("6大宽基指数情绪分的冰点(≤20红)/过热(>80绿)日历。红色密集=多指数同时恐慌(常近底);绿色密集=同时亢奋(常近顶)。作逆向参考。")}</h3><div class="chart" style="height:220px"></div>`;
  content.appendChild(div);
  const c = echarts.init(div.querySelector(".chart"));
  charts.push(c);
  // 热力图为单一大卡容器，右上角加盘中角标（日期取最新一日）
  addCardTimeBadge(div, dates.length ? dates[dates.length - 1] : "", snap, "t0");

  // 日期标签：上限 10 个均匀采样（i % step === 0），避免全历史数百日期在窄屏 45° 旋转重叠
  const labelStep = Math.max(1, Math.ceil(dates.length / 10));
  c.setOption(withTheme({
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
      axisLabel: { color: cssVar("--text-1"), rotate: 0, fontSize: 10, interval: (i) => i % labelStep === 0, formatter: (v) => v.slice(4, 6) + "-" + v.slice(6, 8) },
      splitArea: { show: false },
    },
    yAxis: {
      type: "category",
      data: idxNames.map((x) => x.label),
      axisLabel: { color: cssVar("--text-1"), fontSize: 12 },
    },
    visualMap: {
      min: 0, max: 100,
      pieces: [
        { lte: 20, color: "#e6492e", label: "冰点(≤20)" },
        { gt: 20, lte: 80, color: "#d9d9d9", label: "中性(20-80)" },
        { gt: 80, color: "#2e8b57", label: "过热(>80)" },
      ],
      orient: "horizontal", left: "center", bottom: 4,
      textStyle: { color: cssVar("--text-1") },
    },
    series: [{
      type: "heatmap", data: data,
      label: { show: false },
      emphasis: { itemStyle: { borderColor: cssVar("--text-1"), borderWidth: 1 } },
    }],
  }));
}

// 期货机构持仓：净持仓比例折线图 + 方向准确率表格
function renderFuturesSection(data, snap) {
  if (!data || !data.positions || !data.positions.length) return;

  const roles = ["机构(前20)", "中信期货", "国泰君安"];
  const products = ["沪深300期货", "中证500期货", "上证50期货", "中证1000期货", "综合"];

  // 期货区统一套 .indices-grid 3列网格(最小宽度700)：表格卡+折线图+说明卡同网格，视觉统一
  const fgGrid = document.createElement("div");
  fgGrid.className = "indices-grid";
  content.appendChild(fgGrid);

  // 1. 昨日净多空概览卡片
  if (data.summary && data.summary.roles) {
    const div = document.createElement("div");
    div.className = "chart-card futures-table-card";
    const dateStr = data.summary.date || "";
    const dateSuffix = dateStr ? `<span class="chart-latest"> · ${fmtDate(dateStr)}</span>` : "";
    let html = `<h3>昨日净多空（万手）${dateSuffix}</h3>`;
    html += '<table class="futures-summary-table"><thead><tr><th>品种</th>';
    for (const role of roles) html += `<th>${role}</th>`;
    html += '</tr></thead><tbody>';
    for (const prod of products) {
      html += `<tr><td class="sym-name">${prod}</td>`;
      for (const role of roles) {
        const v = (data.summary.roles[role] || {})[prod];
        const cls = v > 0 ? "futures-long" : v < 0 ? "futures-short" : "";
        const sign = v > 0 ? "+" : "";
        html += `<td class="${cls}">${v != null ? sign + (v / 10000).toFixed(1) + "万手" : "-"}</td>`;
      }
      html += '</tr>';
    }
    html += '</tbody></table>';
    html += '<div class="term-plain">正数=净多（红），负数=净空（绿）。数据来源：中金所前20会员持仓。</div>';
    html += '<div class="futures-reverse-note">⚠ 机构持仓极端值常为<strong>反向参考</strong>（机构极度看多时可能见顶、极度看空时可能见底），需结合历史准确率与市场位置判断，不可单看净持仓方向顺势操作。</div>';
    div.innerHTML = html;
    fgGrid.appendChild(div);
    addCardTimeBadge(div, dateStr, snap, "t1", "futures_date");
  }

  // 2. 历史准确率表格（移到综合图前面）
  if (data.accuracy) {
    const div = document.createElement("div");
    div.className = "chart-card futures-table-card";
    const windows = ["30d", "60d", "120d"];
    const accDates = (data.positions || []).map(p => p.date).filter(Boolean).sort();
    const accDateSuffix = accDates.length ? `<span class="chart-latest"> · ${fmtDate(accDates[accDates.length - 1])}</span>` : "";
    let html = `<h3>历史同向/逆向准确率（次工作日涨跌）${accDateSuffix}</h3>`;
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
    // 当期方向+实际涨跌行：net_direction(红多绿空) + actual_return(涨跌)
    html += `<tr><td class="sym-name"><span class="term-tip" data-tip="机构最新持仓方向(多/空)及对应指数实际涨跌幅。多+涨/空+跌=赌对方向，反之赌错。actual_return待收盘次日更新">当期方向❓</span></td>`;
    for (const role of roles) {
      const acc = data.accuracy[role] || {};
      let dir = acc.net_direction;
      let ret = acc.actual_return;
      // 最新日期 actual_return 常为 null(待收盘)，回退到最近已完成的方向+涨跌
      let betDate = "";
      if (ret == null && data.latest_bet && data.latest_bet[role]) {
        const lb = data.latest_bet[role];
        dir = lb.net_direction;
        ret = lb.actual_return;
        betDate = lb.date ? `(${lb.date.slice(4, 6)}/${lb.date.slice(6, 8)})` : "";
      }
      if (dir != null) {
        const dirText = dir === "long" ? "多" : dir === "short" ? "空" : dir;
        const dirColor = dir === "long" ? "#e6492e" : "#2e8b57";
        let retStr = "待收盘";
        let retColor = "var(--text-3)";
        let judge = "";
        if (ret != null) {
          retStr = (ret >= 0 ? "+" : "") + ret.toFixed(2) + "%";
          retColor = ret >= 0 ? "#e6492e" : "#2e8b57";
          // 赌对方向：多+涨 / 空+跌
          const correct = (dir === "long" && ret >= 0) || (dir === "short" && ret < 0);
          judge = correct ? " ✓" : " ✗";
        }
        html += `<td><span style="color:${dirColor}">${dirText}</span> <span style="color:${retColor}">${retStr}</span>${betDate}<span style="color:${ret != null ? (ret >= 0 ? "#e6492e" : "#2e8b57") : "var(--text-3)"}">${judge}</span></td>`;
      } else {
        html += '<td>-</td>';
      }
    }
    html += '</tr>';
    html += '</tbody></table>';
    html += '<div class="term-plain">机构=中金所前20会员汇总。中信/国君为单独席位。历史准确率基于次工作日涨跌方向统计，不构成未来预测。</div>';
    div.innerHTML = html;
    fgGrid.appendChild(div);
    addCardTimeBadge(div, accDates.length ? accDates[accDates.length - 1] : "", snap, "t1", "futures_date");
  }

  // 3. 四张折线图：net_position 手数趋势

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
    const roleLabels = { "机构(前20)": "机构", "中信期货": "中信", "国泰君安": "国君" };
    const c1Series = chart1Series.map((s) => ({ ...s, label: roleLabels[s.name] || s.name }));
    const c1 = mkCard("综合净多空手数" + termTip("机构多头仓位减空头仓位，正数=机构偏看多") + latestSuffixMulti(c1Series), 300, null, fgGrid);
    appendPlainTip(c1, "净多空为正且持续增加，机构看多情绪增强");
    addCardTimeBadge(c1.getDom().parentElement, dates1.length ? dates1[dates1.length - 1] : "", snap, "t1", "futures_date");
    c1.setOption(withTheme({
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
                html += '<span style="color:var(--text-3);font-size:11px;margin-left:16px;">';
                const parts = [];
                for (const w of ["30d", "60d", "120d"]) {
                  const a = roleAcc[w];
                  if (a) {
                    const f = Math.round(a.follow * 100);
                    const c = Math.round(a.contrarian * 100);
                    const fStyle = f > c ? 'color:#16a34a;font-weight:bold' : 'color:var(--text-3)';
                    const cStyle = c > f ? 'color:#16a34a;font-weight:bold' : 'color:var(--text-3)';
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
      yAxis: { type: "value", scale: true, axisLabel: { color: cssVar("--text-1"), formatter: (v) => (v / 10000).toFixed(1) + "万手" }, nameTextStyle: { color: cssVar("--text-1") } },
      dataZoom: dzOpts(),
      series: chart1Series.map((s) => ({
        name: s.name, type: "line", smooth: true, symbol: "none", connectNulls: true,
        data: dates1.map((d) => { const p = s.data.find((x) => x.date === d); return p ? p.value : null; }),
        markLine: { silent: true, symbol: "none", lineStyle: { color: cssVar("--border-strong"), type: "dashed", width: 1 }, label: { formatter: "0", fontSize: 10, color: cssVar("--text-1") }, data: [{ yAxis: 0 }] },
      })),
    }));
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
      const prodLabels = { "沪深300期货": "300", "中证500期货": "500", "上证50期货": "50", "中证1000期货": "1000", "综合": "综合" };
      const cPSeries = prodSeries.map((s) => ({ ...s, label: prodLabels[s.name] || s.name }));
      const cP = mkCard(`${role} 各品种净多空手数` + termTip("该角色在各期货品种上的净多空手数，正数看多负数看空") + latestSuffixMulti(cPSeries), 300, null, fgGrid);
      addCardTimeBadge(cP.getDom().parentElement, datesP.length ? datesP[datesP.length - 1] : "", snap, "t1", "futures_date");
      cP.setOption(withTheme({
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
        yAxis: { type: "value", scale: true, axisLabel: { color: cssVar("--text-1"), formatter: (v) => (v / 10000).toFixed(1) + "万手" }, nameTextStyle: { color: cssVar("--text-1") } },
        dataZoom: dzOpts(),
        series: prodSeries.map((s) => ({
          name: s.name, type: "line", smooth: true, symbol: "none", connectNulls: true,
          data: datesP.map((d) => { const p = s.data.find((x) => x.date === d); return p ? p.value : null; }),
          markLine: { silent: true, symbol: "none", lineStyle: { color: cssVar("--border-strong"), type: "dashed", width: 1 }, label: { formatter: "0", fontSize: 10, color: cssVar("--text-1") }, data: [{ yAxis: 0 }] },
        })),
      }));
    }
  }

  // 4. 说明文字
  {
    const div = document.createElement("div");
    div.className = "chart-card futures-table-card";
    div.innerHTML = '<h3>说明</h3><div class="term-plain">机构=中金所前20会员汇总。中信/国君为单独席位。折线图为净多空手数（正=净多，负=净空），hover 可查看比例。历史准确率基于次工作日涨跌方向统计，不构成未来预测。</div>';
    fgGrid.appendChild(div);
  }
}

// ============ 行业看板（F1）============
// 申万一级 31 个行业：折线网格（mini 折线 + E1 买卖点 markPoint）+ 涨跌幅热力图（近 1 日/近 5 日）。
// industry.json 一次性返回 indices（ohlc+signals）+ heatmap（pct_1d/pct_5d）。
// BUG-E：热力图加近1日/近5日/全部切换按钮（嵌在卡片标题右侧），数据已有 pct_1d/pct_5d 只加 UI 切换。
function renderIndustryHeatmap(heatmap, title, containerOverride) {
  if (!heatmap || !heatmap.length) return null;
  // BUG-E：自建卡片（含切换按钮在标题右侧），不复用 mkCard（其标题不支持嵌入控件）
  const ctn = containerOverride || content;
  const div = document.createElement("div");
  div.className = "chart-card hm-badge-bottom";
  const toggleBtns = [["1d", "近1日"], ["5d", "近5日"], ["all", "全部"]]
    .map(([k, label]) => `<button type="button" data-hr="${k}">${label}</button>`).join("");
  div.innerHTML = `<h3 class="with-toggle"><span>${title || "申万一级行业涨跌幅热力图"}</span><span class="heatmap-toggle">${toggleBtns}</span></h3><div class="chart" style="height:280px"></div>`;
  ctn.appendChild(div);
  const c = echarts.init(div.querySelector(".chart"));
  charts.push(c);
  const toggleBtnsEl = div.querySelector(".heatmap-toggle");
  // 切换按钮：就地重画该热力图（不调 renderTab，避免整页重渲染丢滚动位置）
  _heatmapSetOption(c, heatmap, toggleBtnsEl);
  div.querySelectorAll(".heatmap-toggle button").forEach((b) => {
    b.onclick = () => { state.heatmapRange = b.dataset.hr; _heatmapSetOption(c, heatmap, toggleBtnsEl); };
  });
  return c;
}

// 热力图按 state.heatmapRange 计算 setOption 数据并应用到实例 c，同步按钮 active 态
function _heatmapSetOption(c, heatmap, toggleBtnsEl) {
  const rangeMode = state.heatmapRange || "all";
  // 排序：单日模式按对应字段，全部模式按两日平均值（红涨在前，绿跌在后）
  const sortBy = rangeMode === "5d" ? "pct_5d" : rangeMode === "1d" ? "pct_1d" : null;
  const sorted = sortBy
    ? [...heatmap].sort((a, b) => (b[sortBy] ?? -999) - (a[sortBy] ?? -999))
    : [...heatmap].sort((a, b) => {
        const avgA = ((a.pct_1d ?? 0) + (a.pct_5d ?? 0)) / 2;
        const avgB = ((b.pct_1d ?? 0) + (b.pct_5d ?? 0)) / 2;
        return avgB - avgA;
      });
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
  if (toggleBtnsEl) toggleBtnsEl.querySelectorAll("button").forEach((b) => {
    b.classList.toggle("active", b.dataset.hr === rangeMode);
  });
  c.setOption(withTheme({
    tooltip: {
      trigger: "item",
      formatter: (p) => {
        const h = sorted[p.value[0]];
        let s = `${names[p.value[0]]}<br/>${yCats[p.value[1]]}：${p.value[2] == null ? "-" : p.value[2] + "%"}`;
        if (h && h.net_inflow != null) {
          const fc = h.net_inflow >= 0 ? "#e6492e" : "#2e8b57";
          const fs = h.net_inflow >= 0 ? "+" : "";
          s += `<br/>净流入：<span style="color:${fc}">${fs}${h.net_inflow.toFixed(1)}亿</span>`;
        }
        if (h && h.lead_stock) s += `<br/>领涨：${h.lead_stock}`;
        return s;
      },
    },
    grid: { left: 56, right: 16, top: 24, bottom: 60 },
    xAxis: { type: "category", data: names, axisLabel: { color: cssVar("--text-1"), rotate: 0, fontSize: 10, interval: 0 }, splitArea: { show: false } },
    yAxis: { type: "category", data: yCats, axisLabel: { color: cssVar("--text-1"), fontSize: 11 } },
    visualMap: {
      min: -5, max: 5, calculable: true, orient: "horizontal", left: "center", bottom: 4,
      inRange: { color: ["#2e8b57", "#a8d8b9", "#f2f3f5", "#f5b6a8", "#e6492e"] }, // 绿→灰→红（A 股惯例红涨绿跌）
      text: ["+5%", "-5%"],
      textStyle: { color: cssVar("--text-1") },
    },
    series: [{
      type: "heatmap", data: data,
      label: { show: true, fontSize: 9, color: "#333", formatter: (p) => (p.value[2] == null ? "-" : p.value[2].toFixed(1)) },
      emphasis: { itemStyle: { borderColor: cssVar("--text-1"), borderWidth: 1 } },
    }],
  }));
}

// 从 stats 中提取频率信息，生成 hover popup HTML
function _freqPopupHtml(stats) {
  if (!stats) return null;
  const labels = { buy: "买点", buy_aux: "辅买", sell: "卖点" };
  const cls = { buy: "buy", buy_aux: "buy-aux", sell: "sell" };
  let parts = [];
  for (const sig of ["buy", "buy_aux", "sell"]) {
    const s = stats[sig];
    if (!s || !s.frequency) continue;
    const f = s.frequency;
    parts.push(`<span class="hint-sig ${cls[sig]}">${labels[sig]}</span> 今年<b>${f.year_count}</b>次 总计<b>${f.total_count}</b>次 月均<b>${f.monthly_avg}</b>次`);
  }
  return parts.length ? parts.join("<br>") : null;
}

// 行业卡片：把 statsHint 直显的"📅 信号频率"区块改为 hover pop，绑到对应信号的成功率行上。
// hint-row 的 .hint-sig class（buy/buy-aux/sell）关联同信号的频率 -> 悬浮成功率行弹频率 pop。
function _bindFreqPopupToHintRows(cell, stats) {
  const hintEl = cell.querySelector(".chart-hint");
  if (!hintEl || !stats) return;
  // 定位并移除直显的频率区块（"📅 信号频率" hint-header 到下一个 hint-header/details 之间）
  const headers = hintEl.querySelectorAll(".hint-header");
  let freqHeader = null;
  for (const h of headers) {
    if (h.textContent.includes("信号频率")) { freqHeader = h; break; }
  }
  if (!freqHeader) return;
  // 收集频率区块的兄弟节点（freqHeader 及其后到下一个 hint-header/details/disclaimer）
  const freqNodes = [freqHeader];
  let nxt = freqHeader.nextElementSibling;
  while (nxt && !nxt.classList.contains("hint-header") && nxt.tagName !== "DETAILS" && !nxt.classList.contains("hint-disclaimer")) {
    freqNodes.push(nxt);
    nxt = nxt.nextElementSibling;
  }
  // 从每个频率行提取该信号的频率文案，按 sig 名存映射
  // 注意：class 名是 buy-aux，sig 名是 buy_aux（买/卖两者相同，辅买不同），需统一存 sig 名
  const clsToSig = { buy: "buy", "buy-aux": "buy_aux", sell: "sell" };
  const freqBySig = {};
  for (const node of freqNodes) {
    node.querySelectorAll(".hint-row").forEach((row) => {
      const sigSpan = row.querySelector(".hint-sig");
      if (!sigSpan) return;
      let cls = null;
      for (const c of ["buy", "buy-aux", "sell"]) {
        if (sigSpan.classList.contains(c)) { cls = c; break; }
      }
      const sig = cls ? clsToSig[cls] : null;
      if (sig) freqBySig[sig] = row.innerHTML;
    });
  }
  // 移除直显的频率区块
  freqNodes.forEach((n) => n.remove());
  // 给每个信号的成功率 hint-row 绑 hover pop（PC hover 显示）/ 点按 pop（移动端 hover:none 设备补 click 切换）
  const isTouch = window.matchMedia && window.matchMedia("(hover: none)").matches;
  const sigMap = { buy: "buy", buy_aux: "buy-aux", sell: "sell" };
  hintEl.querySelectorAll(".hint-row").forEach((row) => {
    const sigSpan = row.querySelector(".hint-sig");
    if (!sigSpan) return;
    let sig = null;
    for (const [k, v] of Object.entries(sigMap)) {
      if (sigSpan.classList.contains(v)) { sig = k; break; }
    }
    const freqHtml = sig ? freqBySig[sig] : null;
    if (!freqHtml) return;
    row.classList.add("freq-hover-row");
    const popup = document.createElement("div");
    popup.className = "freq-popup";
    popup.innerHTML = `<div class="hint-header">📅 信号频率</div><div class="hint-row">${freqHtml}</div>`;
    row.style.position = "relative";
    row.appendChild(popup);
    let openByClick = false;  // 移动端 click 触发时标记，此时 mouseleave 不立即关
    row.addEventListener("mouseenter", () => { if (!openByClick) popup.style.display = "block"; });
    row.addEventListener("mouseleave", () => { if (!openByClick) popup.style.display = "none"; });
    if (isTouch) {
      row.addEventListener("click", (e) => {
        if (e.target.closest && e.target.closest(".freq-popup")) return;  // 点 pop 内容不 toggle
        e.stopPropagation();
        // 关闭其他已打开的 freq-popup
        hintEl.querySelectorAll(".freq-popup").forEach((p) => { if (p !== popup && p.style.display === "block") p.style.display = "none"; });
        openByClick = popup.style.display !== "block";  // 基于 display 同步状态（document 委托关闭后仍正确）
        popup.style.display = openByClick ? "block" : "none";
      });
    }
  });
  // 移动端：点别处（非频率行/非 pop 内容）关闭所有 freq-popup（capture 阶段，先于 row 的 stopPropagation）
  if (isTouch && !document._freqPopDocBound) {
    document._freqPopDocBound = true;
    document.addEventListener("click", (e) => {
      if (e.target.closest && (e.target.closest(".freq-hover-row") || e.target.closest(".freq-popup"))) return;
      document.querySelectorAll(".freq-popup").forEach((p) => { if (p.style.display === "block") p.style.display = "none"; });
    }, true);
  }
}

// 行业/概念卡片：ETF 多候选展示（对齐用户诉求 -- 不替用户硬选1个）。
// top1 代码标签（可点复制）+ "+N" 提示更多；悬浮弹出全部候选（按成交额降序，每行可点复制）。
// 匹配不到（etfs 为空）则不渲染，避免硬塞"代理"ETF 误导用户。
function _renderEtfTag(etfs) {
  if (!etfs || !etfs.length) return "";
  const top = etfs[0];
  const more = etfs.length > 1 ? `<span class="etf-more">+${etfs.length - 1}</span>` : "";
  return `<span class="etf-tag" title="相关ETF · 点击复制代码，悬浮看全部候选">${top.code}${more}</span>`;
}

function _copyEtfCode(el, code) {
  const txt = navigator.clipboard ? navigator.clipboard.writeText(code) : Promise.resolve();
  txt.then(() => {
    const origTitle = el.getAttribute("title") || "";
    el.classList.add("copied");
    el.setAttribute("title", `已复制 ${code}`);
    setTimeout(() => { el.classList.remove("copied"); el.setAttribute("title", origTitle); }, 900);
  });
}

function _bindEtfPopup(cell, etfs) {
  if (!etfs || !etfs.length) return;
  const tag = cell.querySelector(".etf-tag");
  if (!tag) return;
  const popup = document.createElement("div");
  popup.className = "etf-popup";
  popup.innerHTML = `<div class="etf-pop-title">相关ETF · 按成交额排序 · 点击复制</div>` +
    etfs.map((e) => `<div class="etf-pop-row" data-code="${e.code}"><span class="etf-pop-code">${e.code}</span><span class="etf-pop-name">${e.name}</span><span class="etf-pop-amt">${e.amount}亿</span></div>`).join("");
  tag.appendChild(popup);
  const isTouch = window.matchMedia && window.matchMedia("(hover: none)").matches;
  let openByClick = false;  // 移动端 click 打开时标记，防合成 mouseenter 闪现 + mouseleave 立即关
  tag.addEventListener("click", (e) => {
    if (e.target.closest(".etf-pop-row")) return;  // 点候选行复制，不 toggle
    e.stopPropagation();
    if (isTouch) {
      openByClick = popup.style.display !== "block";  // 基于 display 同步状态
      popup.style.display = openByClick ? "block" : "none";
    } else {
      _copyEtfCode(tag, etfs[0].code);  // PC：复制 top1（popup 已 hover 显示）
    }
  });
  popup.querySelectorAll(".etf-pop-row").forEach((row) => {
    row.addEventListener("click", (e) => {
      e.stopPropagation();
      _copyEtfCode(row, row.dataset.code);
      if (isTouch) { popup.style.display = "none"; openByClick = false; }  // 移动端复制后关闭
    });
  });
  tag.addEventListener("mouseenter", () => { if (!openByClick) popup.style.display = "block"; });
  tag.addEventListener("mouseleave", () => { if (!openByClick) popup.style.display = "none"; });
  // 移动端：点别处（非 tag/非 pop 内容）关闭所有 etf-popup
  if (isTouch && !document._etfPopDocBound) {
    document._etfPopDocBound = true;
    document.addEventListener("click", (e) => {
      if (e.target.closest && (e.target.closest(".etf-tag") || e.target.closest(".etf-popup"))) return;
      document.querySelectorAll(".etf-popup").forEach((p) => { if (p.style.display === "block") p.style.display = "none"; });
    }, true);
  }
}

// B2 折中：行业 tooltip detail 按需加载（静态版瘦身主文件，detail 存 tooltip 专属字段）
const _indDetail = new Map();
function _indHasDetail(idx) {
  return idx.width && idx.width.length && idx.width[0] && "zt_count" in idx.width[0];
}
async function _preloadIndDetail(id, idx) {
  if (_indDetail.has(id)) return;
  if (_indHasDetail(idx)) {
    _indDetail.set(id, {
      ohlc: (idx.data || []).map((d) => ({ open: d.open, high: d.high, low: d.low })),
      width: (idx.width || []).map((w) => ({ zt_count: w.zt_count, dt_count: w.dt_count, zb_count: w.zb_count, seal_rate: w.seal_rate, amount: w.amount })),
    });
    return;
  }
  try {
    const det = await fetchJSON("./data/industry-all-indices/" + id + "-detail.json");
    if (det.ohlc && idx.data && det.ohlc.length === idx.data.length && det.width && idx.width && det.width.length === idx.width.length) {
      _indDetail.set(id, det);
    } else {
      console.warn("industry detail " + id + " 长度不匹配，已丢弃");
    }
  } catch (e) { /* 静默失败，tooltip 降级 */ }
}
function _indOHL(id, idx, i) {
  const det = _indDetail.get(id);
  if (det && det.ohlc && det.ohlc[i]) return det.ohlc[i];
  return idx.data[i] || {};
}
function _indWidthExtra(id, idx, i) {
  const det = _indDetail.get(id);
  if (det && det.width && det.width[i]) return det.width[i];
  return (idx.width || [])[i] || {};
}

function renderIndustryGrid(indices, containerOverride, emptyText) {
  const entries = Object.entries(indices).filter(([, idx]) => idx.data && idx.data.length);
  // 按当日涨幅降序排序(最高在前,最低在后);行业 grid 与概念 grid 共用此函数,改一处双生效
  entries.sort(([, a], [, b]) => {
    const pa = a.data && a.data.length ? a.data[a.data.length - 1].pct_change : -Infinity;
    const pb = b.data && b.data.length ? b.data[b.data.length - 1].pct_change : -Infinity;
    return (pb ?? -Infinity) - (pa ?? -Infinity);
  });
  const ctn = containerOverride || content;
  if (!entries.length) {
    const note = document.createElement("div");
    note.className = "empty-note";
    // 概念板块传 emptyText="暂无概念板块数据"，申万/港股行业默认"暂无行业指数数据"
    note.textContent = emptyText || "暂无行业指数数据";
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
    const etfTag = _renderEtfTag(idx.etfs);
    // 行业卡片标题加最新收盘值（与指数表现 latestSuffix 一致：· MM-DD 收盘价 +涨跌幅）
    // closeSuffix 兜底：last.close==null(T+1源当日未发布)时向前找最后 close!=null 的点显收盘价
    let _csDate = last.date, _csClose = last.close;
    if (_csClose == null) {
      for (let k = ohlc.length - 1; k >= 0; k--) {
        if (ohlc[k].close != null) { _csDate = ohlc[k].date; _csClose = ohlc[k].close; break; }
      }
    }
    const closeSuffix = (_csClose != null) ? `<span class="chart-latest"> · ${fmtDate(_csDate)} ${_csClose.toFixed(2)}</span>` : "";
    const pctSuffix = (pct != null) ? ` <span class="pct-badge" style="color:${color}">${sign}${pct.toFixed(2)}%</span>` : "";
    cell.innerHTML = `
      <div class="spark-head">
        <span class="spark-name">${idx.name}${etfTag}${closeSuffix}${pctSuffix}</span>
      </div>
      ${hint ? `<div class="chart-hint">${hint}</div>` : ""}
      <div class="spark-chart"></div>
      <div class="ind-metrics"></div>`;
    // 信号频率改为 hover pop：绑在对应信号的成功率行(hint-row)上，悬浮显示频率
    _bindFreqPopupToHintRows(cell, idx.stats);
    // ETF：top1 标签可点复制，悬浮弹全部候选（按成交额降序，每行可复制）
    _bindEtfPopup(cell, idx.etfs);
    // B2：视口懒加载行业 detail（tooltip 专属字段），进视口即预取
    const _io = new IntersectionObserver((entries) => {
      for (const e of entries) {
        if (e.isIntersecting) { _preloadIndDetail(id, idx); _io.unobserve(e.target); }
      }
    }, { rootMargin: "300px" });
    _io.observe(cell);
    grid.appendChild(cell);
    // 行业角标：dataDate 用 idx.data 末条 date(=07-14 T+1源已到日期)，
    // 非 last_valid_close(=07-13)，避免盘中误判滞后(预期显 📅 T+1·07-14 绿色最新)
    addCardTimeBadge(cell, last.date, state.intradaySnapshot, "t1", "industry");
    // 行业绿色(最新)档专属 tip（补充申万/baostock 源说明）；滞后/异常档保留通用 tip
    const _indBdg = cell.querySelector(".card-time-badge.intraday");
    if (_indBdg) _indBdg.setAttribute("data-tip", "行业指数T+1(申万/baostock收盘后次日补全),已更新到最新交易日");
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
    sc.setOption(withTheme({
      grid: { left: 2, right: 2, top: 6, bottom: 18 },
      xAxis: { type: "category", show: true, data: ohlc.map((d) => d.date), axisLabel: { fontSize: 8, color: cssVar("--text-1"), interval: Math.max(1, Math.floor(ohlc.length / 5)), formatter: (v) => v.slice(0, 4) + "-" + v.slice(4, 6) }, axisTick: { show: false }, axisLine: { show: false }, splitLine: { show: false } },
      yAxis: { type: "value", show: false, scale: true },
      tooltip: { trigger: "axis", formatter: (p) => {
        const d = ohlc[p[0].dataIndex];
        if (!d || d.close == null) return `${p[0].axisValue}<br/>-`;
        const lines = [p[0].axisValue, `收盘 ${d.close.toFixed(2)}`];
        if (d.pct_change != null) lines.push(`涨跌 ${d.pct_change >= 0 ? "+" : ""}${d.pct_change.toFixed(2)}%`);
        const od = _indOHL(id, idx, p[0].dataIndex);
        if (od.open != null && od.high != null && od.low != null) lines.push(`开 ${od.open.toFixed(2)} 高 ${od.high.toFixed(2)} 低 ${od.low.toFixed(2)}`);
        return lines.join("<br/>");
      } },
      series: [{
        type: "line", smooth: true, symbol: "none",
        data: ohlc.map((d) => [d.date, d.close]),
        lineStyle: { color, width: 1.5 }, areaStyle: { color, opacity: 0.12 },
        markPoint: { symbol: "pin", symbolSize: 26, label: { fontSize: 9, color: "#fff" }, data: markData },
      }],
    }));
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
      mc.setOption(withTheme({
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
      }));
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
      wc.setOption(withTheme({
        grid: { left: 1, right: 1, top: 1, bottom: 1 },
        xAxis: { type: "category", show: false, data: widthData.map((d) => d.date) },
        yAxis: { type: "value", show: false },
        tooltip: { trigger: "axis", formatter: (p) => {
          const d = widthData[p[0].dataIndex];
          if (!d) return `${p[0].axisValue}<br/>-`;
          const wd = _indWidthExtra(id, idx, p[0].dataIndex);
          return `${p[0].axisValue}<br/>涨${d.up_count} 跌${d.down_count} | 涨停${wd.zt_count != null ? wd.zt_count : "-"} 跌停${wd.dt_count != null ? wd.dt_count : "-"} 炸板${wd.zb_count != null ? wd.zb_count : "-"}<br/>封板率${wd.seal_rate != null ? (wd.seal_rate * 100).toFixed(0) + "%" : "-"} | 成交额${wd.amount != null ? wd.amount.toFixed(0) + "亿" : "-"}`;
        } },
        series: [
          { name: "上涨", type: "line", stack: "wd", symbol: "none", smooth: true,
            data: widthData.map((d) => [d.date, d.up_count || 0]),
            lineStyle: { color: "#e6492e", width: 0.8 }, areaStyle: { color: "#e6492e", opacity: 0.35 } },
          { name: "下跌", type: "line", stack: "wd", symbol: "none", smooth: true,
            data: widthData.map((d) => [d.date, -(d.down_count || 0)]),
            lineStyle: { color: "#2e8b57", width: 0.8 }, areaStyle: { color: "#2e8b57", opacity: 0.35 } },
        ],
      }));
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
      if (v == null) return { text: "N/A", cls: "", short: "-" };
      if (v >= 60) return { text: "快速轮动", cls: "fast", short: "快" };
      if (v >= 30) return { text: "中等轮动", cls: "mid", short: "中" };
      return { text: "轮动缓慢", cls: "slow", short: "慢" };
    }
    function speedHint(v) {
      if (v == null) return "";
      if (v >= 60) return "板块天天换领涨，没持续主线，追热点易接盘";
      if (v >= 30) return "轮动速度适中，可关注主线";
      return "同一板块连续领涨，主线明确，适合跟主线";
    }

    const sw5 = speedLabel(sw.speed_5d);
    const sw10 = speedLabel(sw.speed_10d);
    const sw20 = speedLabel(sw.speed_20d);
    const swHint = speedHint(sw.speed_5d);
    const c5 = speedLabel(concept.speed_5d);
    const c10 = speedLabel(concept.speed_10d);
    const c20 = speedLabel(concept.speed_20d);

    const card = document.createElement("div");
    card.className = "rotation-card";
    const rotDateSuffix = latest.date ? `<span class="chart-latest"> · ${fmtDate(latest.date)}</span>` : "";
    card.innerHTML = `
      <div class="rotation-card-header">🌀 板块轮动速度${rotDateSuffix}</div>
      <div class="rotation-card-body">
        <div class="rotation-row">
          <span class="rotation-label">申万行业</span>
          <span class="rotation-item ${sw5.cls}">5日: ${sw.speed_5d != null ? sw.speed_5d + "%" : "N/A"} <span class="rit-full">${sw5.text}</span><span class="rit-short">${sw5.short}</span></span>
          <span class="rotation-item ${sw10.cls}">10日: ${sw.speed_10d != null ? sw.speed_10d + "%" : "N/A"} <span class="rit-full">${sw10.text}</span><span class="rit-short">${sw10.short}</span></span>
          <span class="rotation-item ${sw20.cls}">20日: ${sw.speed_20d != null ? sw.speed_20d + "%" : "N/A"} <span class="rit-full">${sw20.text}</span><span class="rit-short">${sw20.short}</span></span>
        </div>
        ${concept.speed_5d != null ? `
        <div class="rotation-row">
          <span class="rotation-label">概念板块</span>
          <span class="rotation-item ${c5.cls}">5日: ${concept.speed_5d}% <span class="rit-full">${c5.text}</span><span class="rit-short">${c5.short}</span></span>
          <span class="rotation-item ${c10.cls}">10日: ${concept.speed_10d}% <span class="rit-full">${c10.text}</span><span class="rit-short">${c10.short}</span></span>
          <span class="rotation-item ${c20.cls}">20日: ${concept.speed_20d}% <span class="rit-full">${c20.text}</span><span class="rit-short">${c20.short}</span></span>
        </div>` : ""}
        <div class="rotation-hint">💡 ${swHint}</div>
        <details class="rotation-explain" open><summary>📊 这个百分比怎么看？</summary><div class="rotation-explain-body">
          <div>每天找出当天<b>涨幅最高</b>的板块（领涨板块），看过去 N 天领涨<b>换了几次</b>：换得越多百分比越高。</div>
          <div>举例（5 日窗口，最多换 4 次）：</div>
          <div class="rotation-explain-example">同一板块连涨 5 天 -> 换 0 次 -> <b>0%</b>（轮动缓慢）<br>5 天换 4 次领涨 -> <b>100%</b>（快速轮动，一天换一个）</div>
          <div>所以：<b>100%</b> = 过去几天每天领涨都不同，板块天天换、没持续主线，追热点容易接盘；<b>越低</b> = 同一板块连续领涨、主线明确，适合跟主线做。</div>
        </div></details>
      </div>`;
    container.appendChild(card);
  } catch (e) {
    // 静默失败，不影响主流程
    console.warn("轮动速度卡片加载失败:", e);
  }
}

async function _loadIndustryData(range) {
  if (range !== "all") return await fetchJSON(`./data/industry-${range}.json`);
  // all range：Cloudflare 25MB 限制，industry-all 拆成 31 行业文件 + concepts + meta，并发加载
  const meta = await fetchJSON("./data/industry-all-meta.json");
  const ids = meta.index_ids || [];
  const entries = await Promise.all(
    ids.map(async (iid) => [iid, await fetchJSON(`./data/industry-all-indices/${iid}.json`)])
  );
  const conceptsRes = await fetchJSON("./data/industry-all-concepts.json");
  return {
    indices: Object.fromEntries(entries),
    heatmap: meta.heatmap,
    concepts: conceptsRes.concepts || {},
  };
}

// I1：行业数据缓存（按 range 缓存，搜索只做客户端筛选不 refetch）
let _industryCache = { range: null, r: null };
// I3：行业锚点 scrollspy observer（切 tab 时 disconnect 旧实例避免泄漏）
let _industryScrollSpy = null;

// 释放指定容器内 ECharts 实例并从全局 charts 移除（搜索重渲染前清理）
function _disposeContainerCharts(container) {
  if (!container) return;
  container.querySelectorAll(".spark-chart, [_echarts_instance_]").forEach((dom) => {
    const inst = echarts.getInstanceByDom(dom);
    if (inst) {
      inst.dispose();
      const i = charts.indexOf(inst);
      if (i >= 0) charts.splice(i, 1);
    }
  });
}

async function renderIndustry() {
  renderLoadingState(content, "加载行业数据…");
  // I1：命中缓存则不 refetch
  let r;
  if (_industryCache.range === state.range && _industryCache.r) {
    r = _industryCache.r;
  } else {
    r = await _loadIndustryData(state.range);
    _industryCache = { range: state.range, r };
  }
  content.innerHTML = "";
  content.insertAdjacentHTML("beforeend", '<div class="home-purpose-note">💡 <b>这板块有什么用</b>:追踪申万一级行业和概念板块的资金流向与轮动速度,辅助判断主线、定位走强板块。<b>怎么解读</b>:持续净流入+加速轮动=主线走强特征;净流出+减速=走弱特征(历史统计,非配置建议);行业/概念技术信号辅助观察。</div>');
  const snap = state.intradaySnapshot;

  // 板块轮动速度卡片 + 申万行业热力图：1:2 grid 合并一行（左轮动卡 / 右热力图）
  const rotHmGrid = document.createElement("div");
  rotHmGrid.className = "rotation-heatmap-grid";
  content.appendChild(rotHmGrid);
  await renderRotationCard(rotHmGrid);
  // 轮动卡 fetch 失败兜底：降级单列，热力图占满
  if (!rotHmGrid.querySelector(".rotation-card")) {
    rotHmGrid.classList.add("single-col");
  }

  const swCount = Object.keys(r.indices || {}).length;
  const conceptCount = Object.keys(r.concepts || {}).length;

  // 申万行业区域（热力图）；tab 按钮 + 搜索框移到热力图下方（anchorBar，sticky 吸顶）
  const swSection = document.createElement("div");
  swSection.id = "sw-industries";
  rotHmGrid.appendChild(swSection);

  const indHmDates = (r.heatmap || []).map(h => h.last_date).filter(Boolean).sort();
  const indHmSuffix = indHmDates.length ? `<span class="chart-latest"> · ${fmtDate(indHmDates[indHmDates.length - 1])}</span>` : "";
  const indHmChart = renderIndustryHeatmap(r.heatmap, "申万一级行业涨跌幅热力图（近 1 日 / 近 5 日）" + indHmSuffix, swSection);
  if (indHmChart) addCardTimeBadge(indHmChart.getDom().parentElement, indHmDates.length ? indHmDates[indHmDates.length - 1] : "", snap, "t1", "industry");

  // 锚点 + 搜索条：热力图下方，sticky 吸顶（申万/概念 tab 按钮 + 搜索框同一行）
  // 吸顶时锚点跳转与搜索筛选均可用；搜索共用 state.industrySearch（I2 概念区同筛）
  const anchorBar = document.createElement("div");
  anchorBar.className = "industry-anchor-bar";
  anchorBar.innerHTML = `
    <div class="anchor-btn-group">
      <button type="button" data-anchor="sw-industries" class="active">申万行业（${swCount}）</button>
      <button type="button" data-anchor="thsc-concepts">概念板块（${conceptCount}）</button>
    </div>
    <input type="search" class="anchor-search" placeholder="搜索行业/概念名称或代码（如：银行、机器人、thsc_）" aria-label="搜索行业/概念" />`;
  content.appendChild(anchorBar);
  // tab 按钮：平滑滚动到对应区域
  anchorBar.querySelectorAll("button[data-anchor]").forEach((btn) => {
    btn.onclick = () => {
      const el = document.getElementById(btn.dataset.anchor);
      if (el) el.scrollIntoView({ behavior: "smooth" });
      anchorBar.querySelectorAll("button[data-anchor]").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
    };
  });

  // I1：搜索只局部重渲染 swGridWrap（title + grid），不 refetch、不重建热力图/轮动卡
  // swGridWrap 作为 content 直接子元素（与 anchorBar 同级），使 anchorBar sticky 跨申万+概念两区生效
  const swGridWrap = document.createElement("div");
  swGridWrap.dataset.spyFor = "sw-industries"; // I3: scrollspy 申万网格映射到 sw-industries
  content.appendChild(swGridWrap);

  // I2：概念板块也加搜索筛选 -- 共用 state.industrySearch，一个搜索条同时过滤两区
  let conceptGridWrap = null;
  let conceptTitle = null; // 提到 if 块外，供 _applyIndustryFilter 更新 shown/total 标题
  if (conceptCount > 0) {
    const thscSection = document.createElement("div");
    thscSection.id = "thsc-concepts";
    content.appendChild(thscSection);

    conceptTitle = document.createElement("div");
    conceptTitle.className = "section-title";
    conceptTitle.textContent = `概念板块指数折线（${conceptCount}/${conceptCount} 个，含买卖点 + 回测统计）`;
    thscSection.appendChild(conceptTitle);

    conceptGridWrap = document.createElement("div");
    thscSection.appendChild(conceptGridWrap);
  }

  function _applyIndustryFilter() {
    // 申万行业
    _disposeContainerCharts(swGridWrap);
    swGridWrap.innerHTML = "";
    const title = document.createElement("div");
    title.className = "section-title";
    const total = Object.keys(r.indices || {}).length;
    const filtered = filterIndicesByName(r.indices, state.industrySearch);
    const shown = Object.keys(filtered).length;
    title.textContent = `申万行业指数折线（${shown}/${total} 个，含买卖点 + 资金流/成交额/换手率 + 行业内宽度）`;
    swGridWrap.appendChild(title);
    renderIndustryGrid(filtered, swGridWrap);
    // I2：概念板块共用搜索条筛选
    if (conceptGridWrap) {
      _disposeContainerCharts(conceptGridWrap);
      conceptGridWrap.innerHTML = "";
      const conceptFiltered = filterIndicesByName(r.concepts, state.industrySearch);
      const conceptShown = Object.keys(conceptFiltered).length;
      const conceptTotal = Object.keys(r.concepts || {}).length;
      if (conceptTitle) {
        conceptTitle.textContent = `概念板块指数折线（${conceptShown}/${conceptTotal} 个，含买卖点 + 回测统计）`;
      }
      renderIndustryGrid(conceptFiltered, conceptGridWrap, "暂无概念板块数据");
    }
  }
  // 搜索框（锚点条内）：防抖 + 局部筛选（I1 不 refetch/不重建热力图轮动卡）
  const searchInput = anchorBar.querySelector(".anchor-search");
  searchInput.value = state.industrySearch || "";
  let _searchTimer;
  searchInput.oninput = () => {
    clearTimeout(_searchTimer);
    _searchTimer = setTimeout(() => {
      state.industrySearch = searchInput.value.trim();
      _applyIndustryFilter();
    }, 250);
  };
  _applyIndustryFilter();

  // I3：scrollspy -- 滚动时自动高亮当前可视区对应锚点按钮
  // 观察热力图区(sw-industries)、申万网格(spyFor=sw-industries)、概念区(thsc-concepts)
  if (_industryScrollSpy) { _industryScrollSpy.disconnect(); }
  _industryScrollSpy = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        const id = entry.target.id || entry.target.dataset.spyFor;
        anchorBar.querySelectorAll("button[data-anchor]").forEach((b) => {
          b.classList.toggle("active", b.dataset.anchor === id);
        });
      }
    });
  }, { rootMargin: "-15% 0px -70% 0px", threshold: 0 });
  anchorBar.querySelectorAll("button[data-anchor]").forEach((btn) => {
    const target = document.getElementById(btn.dataset.anchor);
    if (target && _industryScrollSpy) _industryScrollSpy.observe(target);
  });
  if (_industryScrollSpy) _industryScrollSpy.observe(swGridWrap);
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

// === 导航吸顶开关：PC header 右上角，关闭后导航回归文档流方便截图（24h 过期，多窗 storage 同步）===
function isNavStickyOff() {
  try {
    var ts = parseInt(localStorage.getItem('navStickyOff_ts'), 10);
    return !!(ts && Date.now() - ts < 24*3600*1000);
  } catch(e){ return false; }
}
function applyNavStickyState() {
  var off = isNavStickyOff();
  document.documentElement.classList.toggle('nav-no-sticky', off);
  document.querySelectorAll('.nav-sticky-toggle').forEach(function(b){
    b.classList.toggle('off', off);
    b.textContent = off ? '导航吸顶 关' : '导航吸顶';
  });
}
function initNavStickyToggle() {
  document.querySelectorAll('.nav-sticky-toggle').forEach(function(b){
    b.addEventListener('click', function(){
      if (isNavStickyOff()) {
        try { localStorage.removeItem('navStickyOff_ts'); } catch(e){}
      } else {
        try { localStorage.setItem('navStickyOff_ts', String(Date.now())); } catch(e){}
      }
      applyNavStickyState();
    });
  });
  window.addEventListener('storage', function(e){
    if (e.key === 'navStickyOff_ts') applyNavStickyState();
  });
  applyNavStickyState();
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

// ---- 历史收盘分析弹窗（横幅"更多"按钮触发）----
// limit=30：每页 30 条（约 3 个月每日），90 条数据分 3 页，第 1 页能显示到约 2 个月前
let _summaryHistoryState = { page: 0, limit: 30, total: 0, cache: null };

function _summaryHistoryModalEl() {
  let modal = document.getElementById("summaryHistoryModal");
  if (modal) return modal;
  modal = document.createElement("div");
  modal.id = "summaryHistoryModal";
  modal.className = "rule-modal hidden";
  modal.innerHTML = '<div class="rule-modal-overlay"></div><div class="rule-modal-body summary-history-body"><div class="rule-modal-header"><h3>📜 历史收盘分析</h3><button class="rule-modal-close" aria-label="关闭">&times;</button></div><div class="rule-modal-content"><div class="summary-history-info"></div><div class="summary-history-list"></div><div class="summary-history-pager"><button class="sh-prev">‹ 上一页</button><div class="sh-pages"></div><button class="sh-next">下一页 ›</button></div></div></div>';
  document.body.appendChild(modal);
  modal.querySelector(".rule-modal-overlay").addEventListener("click", closeSummaryHistoryModal);
  modal.querySelector(".rule-modal-close").addEventListener("click", closeSummaryHistoryModal);
  modal.querySelector(".sh-prev").addEventListener("click", () => {
    if (_summaryHistoryState.page > 0) { _summaryHistoryState.page--; _loadSummaryHistoryPage(); }
  });
  modal.querySelector(".sh-next").addEventListener("click", () => {
    const maxPage = Math.max(0, Math.ceil(_summaryHistoryState.total / _summaryHistoryState.limit) - 1);
    if (_summaryHistoryState.page < maxPage) { _summaryHistoryState.page++; _loadSummaryHistoryPage(); }
  });
  return modal;
}

function _summaryHistoryItemHtml(s) {
  const date = s.date ? `${s.date.substring(0,4)}-${s.date.substring(4,6)}-${s.date.substring(6,8)}` : "";
  const fg = s.fear_greed_label ? `<span class="sh-fg">😐 ${s.fear_greed_label} ${s.fear_greed_value != null ? s.fear_greed_value.toFixed(0) : ""}</span>` : "";
  const freeze = s.is_freeze ? `<span class="sh-freeze">❄️冰点</span>` : "";
  // 去掉裸 summary 文字，改用指标 chips（与横幅一致）；历史接口缺的字段做空值兜底跳过
  return `<div class="summary-history-item"><div class="sh-date">${date} <span class="sh-label">${s.sentiment_label || ""}</span>${fg}${freeze}</div>${renderSummaryChips(s, null)}</div>`;
}

async function _loadSummaryHistoryPage() {
  const modal = _summaryHistoryModalEl();
  const list = modal.querySelector(".summary-history-list");
  list.innerHTML = '<div class="summary-history-loading">加载中…</div>';
  const { page, limit } = _summaryHistoryState;
  // 静态站：一次性加载 summary_history.json，本地分页（无后端 API）
  if (!_summaryHistoryState.cache) {
    try {
      const all = await fetchJSON("./data/summary_history.json");
      _summaryHistoryState.cache = all.items || [];
      _summaryHistoryState.total = all.total || _summaryHistoryState.cache.length;
    } catch (e) {
      list.innerHTML = `<div class="summary-history-empty">加载失败：${e}</div>`;
      return;
    }
  }
  const offset = page * limit;
  const items = _summaryHistoryState.cache.slice(offset, offset + limit);
  list.innerHTML = items.map(_summaryHistoryItemHtml).join("") || '<div class="summary-history-empty">暂无历史数据</div>';
  // 翻页后列表回顶（用户想看新页内容，不是底部）
  list.scrollTop = 0;
  _renderSummaryPager(modal);
}

// 渲染分页器：顶部 info 行 + 上一页/下一页按钮（带禁用态）+ 可点击页码按钮（当前页高亮）
function _renderSummaryPager(modal) {
  const { page, limit, total } = _summaryHistoryState;
  const maxPage = Math.max(0, Math.ceil(total / limit) - 1);
  const pageCount = maxPage + 1;
  // 顶部 info：让用户立刻知道有更多页
  const info = modal.querySelector(".summary-history-info");
  info.textContent = total > 0 ? `共 ${total} 条记录 · 第 ${page + 1} / ${pageCount} 页` : "";
  // 上一页 / 下一页 禁用态
  const prev = modal.querySelector(".sh-prev");
  const next = modal.querySelector(".sh-next");
  prev.disabled = page <= 0;
  next.disabled = page >= maxPage;
  // 页码按钮：≤7 全显示，>7 智能 1 … cur-1 cur cur+1 … N
  const pagesEl = modal.querySelector(".sh-pages");
  let btns = [];
  if (pageCount <= 7) {
    for (let i = 0; i < pageCount; i++) btns.push(i);
  } else {
    btns.push(0);
    if (page > 2) btns.push(-1);
    for (let i = Math.max(1, page - 1); i <= Math.min(pageCount - 2, page + 1); i++) btns.push(i);
    if (page < pageCount - 3) btns.push(-2);
    btns.push(pageCount - 1);
  }
  pagesEl.innerHTML = btns.map(i =>
    i < 0
      ? '<span class="sh-ellipsis">…</span>'
      : `<button class="sh-page-btn${i === page ? ' active' : ''}" data-page="${i}">${i + 1}</button>`
  ).join("");
  pagesEl.querySelectorAll(".sh-page-btn").forEach(b => {
    b.addEventListener("click", () => {
      const p = +b.dataset.page;
      if (p !== _summaryHistoryState.page) {
        _summaryHistoryState.page = p;
        _loadSummaryHistoryPage();
      }
    });
  });
}

function openSummaryHistoryModal() {
  _summaryHistoryState.page = 0;
  _summaryHistoryState.total = 0;
  _summaryHistoryModalEl().classList.remove("hidden");
  document.body.style.overflow = "hidden";
  _loadSummaryHistoryPage();
}

function closeSummaryHistoryModal() {
  const modal = document.getElementById("summaryHistoryModal");
  if (modal) modal.classList.add("hidden");
  document.body.style.overflow = "";
}

// === H5 移动端适配（方案B：底部导航 + 顶部精简条 + 1/2列切换）===
// matchMedia 驱动 body.h5，@media(max-width:768px) 自动切换布局，PC(>768) 零影响。
const SUMMARY_URL = "./data/summary.json";
const _H5_TAB_NAMES = { overview: "📊 市场全景", market: "📈 指数表现", sentiment: "😊 情绪温度", industry: "🏭 板块分化", lab: "🧪 策略实验" };

function updateH5Topbar() {
  if (!document.body.classList.contains("h5")) return;
  const el = document.querySelector(".h5-tab-name");
  if (el) el.textContent = _H5_TAB_NAMES[state.tab] || state.tab;
}

function applyH5(on) {
  document.body.classList.toggle("h5", on);
  updateH5Topbar();
  // 切换 PC<->H5 时图表容器宽度变化，resize 所有 ECharts
  setTimeout(() => charts.forEach((c) => c && c.resize()), 60);
}

async function initH5Topbar() {
  // 顶部条精简为「分享/采集时间/皮肤」与 PC 一致；历史收盘分析入口回归横幅（.summary-history-btn）
}

function initH5() {
  const mql = window.matchMedia("(max-width: 768px)");
  applyH5(mql.matches);
  mql.addEventListener("change", (e) => applyH5(e.matches));
  initH5Topbar();
}

// === 模拟回测 iframe 浮层（遮罩+圆角边框+缩放动画；左键点 sim-btn 打开，关闭后停留原位置）===
function initSimOverlay() {
  const overlay = document.createElement('div');
  overlay.className = 'sim-overlay';  // CSS 默认 opacity:0/visibility:hidden 隐藏
  overlay.innerHTML = '<div class="sim-window"><div class="sim-loading"><span class="sim-spinner"></span>加载回测中…</div><button class="sim-close" aria-label="关闭回测" title="关闭">✕</button><iframe class="sim-frame" src="about:blank" title="模拟回测"></iframe></div>';
  document.body.appendChild(overlay);
  const frame = overlay.querySelector('.sim-frame');
  const loading = overlay.querySelector('.sim-loading');
  let closeTimer = null;
  const close = () => {
    overlay.classList.remove('show');
    document.body.style.overflow = '';
    clearTimeout(closeTimer);
    closeTimer = setTimeout(() => { frame.src = 'about:blank'; }, 260);  // 等缩放过渡结束再清 src，避免白闪
  };
  overlay.querySelector('.sim-close').addEventListener('click', close);
  overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });  // 点遮罩区关闭
  // 事件委托：所有 .sim-btn（动态生成于 hint）左键在当前页浮层打开 iframe；中键仍可新标签
  document.addEventListener('click', (e) => {
    const a = e.target.closest('.sim-btn');
    if (!a) return;
    e.preventDefault();
    clearTimeout(closeTimer);
    loading.classList.add('show');            // 显示 loading（iframe 加载期间盖白屏）
    var _th; try { var _v = localStorage.getItem('trade-theme'); _th = (_v === null) ? 'redgold' : _v; } catch (e) { _th = 'redgold'; }
    frame.src = a.href.split('#')[0] + '#' + encodeURIComponent(_th);  // hash 传当前主题给 iframe
    overlay.classList.add('show');
    document.body.style.overflow = 'hidden';
  });
  frame.addEventListener('load', () => { loading.classList.remove('show'); });  // iframe 加载完隐藏 loading
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && overlay.classList.contains('show')) close();
  });
}

// === 汪汪队单只详情 接近全屏弹窗（对齐 sim-window：width/height 100%，overlay padding 留边框；顶部含独立周期切换）===
// 点矩阵行/卡片墙卡片弹出，渲染 renderNationalTeamDetail 内容到弹窗内；关闭不重渲染 overview，保留滚动位置
var _ntDetailOverlay = null;
function _ntDetailOverlayEl() {
  if (_ntDetailOverlay) return _ntDetailOverlay;
  var ov = document.createElement('div');
  ov.className = 'nt-detail-overlay';  // CSS 默认 opacity:0/visibility:hidden 隐藏
  ov.innerHTML = '<div class="nt-detail-window"><button class="nt-detail-close" aria-label="关闭" title="关闭">✕</button><div class="nt-detail-toolbar"></div><div class="nt-detail-body"></div></div>';
  document.body.appendChild(ov);
  _ntDetailOverlay = ov;
  var close = function () {
    ov.classList.remove('show');
    document.body.style.overflow = '';
    // dispose 弹窗内 ECharts + 从全局 charts 数组移除，避免内存泄漏
    var body = ov.querySelector('.nt-detail-body');
    _disposeContainerCharts(body);
    body.innerHTML = '';
  };
  ov.querySelector('.nt-detail-close').addEventListener('click', close);
  ov.addEventListener('click', function (e) { if (e.target === ov) close(); });  // 点遮罩区关闭
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && ov.classList.contains('show')) close();
  });
  ov._close = close;
  return ov;
}

function closeNtDetailOverlay() {
  var ov = _ntDetailOverlayEl();
  if (ov._close) ov._close();
}

function openNtDetailOverlay(code, data, qData, hData) {
  // 弹窗内独立周期：默认继承点击弹窗前外部 state.range（用户在矩阵页设的周期）
  state.ntDetailRange = state.range;
  var ov = _ntDetailOverlayEl();
  var body = ov.querySelector('.nt-detail-body');
  // 清空旧内容（dispose 旧 ECharts）
  _disposeContainerCharts(body);
  body.innerHTML = '';
  state.ntEtf = code;
  // 弹窗内按 ntDetailRange 独立切片（不影响外层 state.range，data 此处为全量 rawData）
  var sliced = ntSliceDataByRange(data, state.ntDetailRange);
  // 渲染单只详情到弹窗 body（opts.overlay 让返回按钮=关闭、选择器=重渲染弹窗）
  renderNationalTeamDetail(body, sliced, qData, hData, { overlay: true });
  // 渲染弹窗顶部周期切换按钮（闭包持有全量 data，切换时只重渲染 detail 不重开弹窗）
  _renderNtDetailToolbar(ov, data, qData, hData);
  ov.classList.add('show');
  document.body.style.overflow = 'hidden';
}

// 弹窗顶部时间周期切换按钮（独立 ntDetailRange，只影响弹窗内数据切片，不影响外层 state.range）
// 切换时复用闭包内的全量 rawData 重新切片，只重渲染弹窗内 detail，不重开弹窗、保留弹窗状态
function _renderNtDetailToolbar(ov, rawData, qData, hData) {
  var tb = ov.querySelector('.nt-detail-toolbar');
  if (!tb) return;
  tb.innerHTML = '';
  var rngWrap = document.createElement('div');
  rngWrap.className = 'nt-detail-rng';
  rngWrap.innerHTML = '<span class="nt-detail-rng-label">周期' + termTip('弹窗内时间窗口切换，只影响本弹窗数据，不影响外层页面。默认继承点击前外部周期。3月=近90日/6月=近180日/1年=近365日/3年=近1095日/5年=近1825日/全部=全历史') + '</span>';
  var ranges = [['3m', '3月'], ['6m', '6月'], ['1y', '1年'], ['3y', '3年'], ['5y', '5年'], ['all', '全部']];
  ranges.forEach(function (r) {
    var btn = document.createElement('button');
    btn.textContent = r[1];
    btn.dataset.ntrng = r[0];
    if (state.ntDetailRange === r[0]) btn.classList.add('active');
    btn.onclick = function () {
      if (state.ntDetailRange === r[0]) return;
      state.ntDetailRange = r[0];
      // 只重渲染弹窗内 detail：按新周期重切全量 rawData，不重开弹窗
      var body = ov.querySelector('.nt-detail-body');
      _disposeContainerCharts(body);
      body.innerHTML = '';
      var sliced = ntSliceDataByRange(rawData, state.ntDetailRange);
      renderNationalTeamDetail(body, sliced, qData, hData, { overlay: true });
      // 更新按钮 active 态
      tb.querySelectorAll('button[data-ntrng]').forEach(function (b) {
        b.classList.toggle('active', b.dataset.ntrng === r[0]);
      });
    };
    rngWrap.appendChild(btn);
  });
  tb.appendChild(rngWrap);
}

// === 分享图：canvas 自绘品牌分享卡片（含当日关键数据 + 上证迷你走势 + 域名）===
function _roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

function _metricVal(metrics, id) {
  const m = (metrics || []).find((x) => x.id === id);
  return m ? m.value : null;
}

function drawShareCard(r) {
  const W = 1080, H = 1350;
  const canvas = document.createElement("canvas");
  canvas.width = W; canvas.height = H;
  const ctx = canvas.getContext("2d");
  // 背景渐变
  const g = ctx.createLinearGradient(0, 0, 0, H);
  g.addColorStop(0, "#1f2329"); g.addColorStop(1, "#2d3239");
  ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
  ctx.textBaseline = "alphabetic";

  // 顶部品牌条
  ctx.fillStyle = "#165dff";
  _roundRect(ctx, 60, 60, 240, 64, 18); ctx.fill();
  ctx.fillStyle = "#fff"; ctx.font = "bold 30px 'PingFang SC',sans-serif"; ctx.textBaseline = "middle";
  ctx.fillText("📊 tdsignal", 84, 93);
  ctx.fillStyle = "#aab2bd"; ctx.font = "26px 'PingFang SC',sans-serif";
  ctx.fillText("trade-data-signal", 320, 93);

  // 主标题
  ctx.textBaseline = "alphabetic";
  ctx.fillStyle = "#fff"; ctx.font = "bold 76px 'PingFang SC',sans-serif";
  ctx.fillText("信号实验室", 60, 220);
  ctx.fillStyle = "#aab2bd"; ctx.font = "32px 'PingFang SC',sans-serif";
  ctx.fillText(`${fmtDate(r.date)} 收盘复盘`, 60, 272);

  // 分隔线
  ctx.strokeStyle = "rgba(255,255,255,0.15)"; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(60, 320); ctx.lineTo(1020, 320); ctx.stroke();

  // 情绪分卡片（3个）
  const scores = r.today && r.today.scores || {};
  const sentVal = scores.a_sentiment ? scores.a_sentiment.value : null;
  const crossVal = scores.cross_market ? scores.cross_market.value : null;
  const fgVal = scores.fear_greed ? scores.fear_greed.value : null;
  const sentCards = [
    { label: "A股情绪分", val: sentVal, tag: sentVal != null ? sentimentTag(sentVal) : "" },
    { label: "跨市场评分", val: crossVal, tag: crossVal != null ? sentimentTag(crossVal) : "" },
    { label: "恐贪指数", val: fgVal, tag: fgVal != null ? fearGreedLabel(fgVal) : "" },
  ];
  const metrics = r.today && r.today.metrics || [];
  const zt = _metricVal(metrics, "a_width_zt_count");
  const dt = _metricVal(metrics, "a_width_dt_count");
  const amt = _metricVal(metrics, "a_amount");
  const widthCards = [
    { label: "涨停", val: zt, color: "#e6492e" },
    { label: "跌停", val: dt, color: "#2e8b57" },
    { label: "成交额(亿)", val: amt, color: "#165dff" },
  ];

  const cardW = 290, cardH = 150, gap = 25, startX = 60, startY = 360;
  const drawDataCard = (c, x, y, idx) => {
    ctx.fillStyle = "rgba(255,255,255,0.06)";
    _roundRect(ctx, x, y, cardW, cardH, 14); ctx.fill();
    ctx.strokeStyle = "rgba(255,255,255,0.12)"; ctx.lineWidth = 1;
    _roundRect(ctx, x, y, cardW, cardH, 14); ctx.stroke();
    ctx.fillStyle = "#aab2bd"; ctx.font = "26px 'PingFang SC',sans-serif";
    ctx.fillText(c.label, x + 22, y + 44);
    const v = c.val;
    ctx.fillStyle = c.color || "#fff"; ctx.font = "bold 56px 'PingFang SC',sans-serif";
    const vText = v == null ? "-" : (typeof v === "number" && Math.abs(v) >= 1000 ? v.toFixed(0) : (typeof v === "number" ? v.toFixed(1) : v));
    ctx.fillText(vText, x + 22, y + 108);
    if (c.tag) {
      // 用数值字体(56px)测量宽度——必须在切到tag字体前测,否则22px测56px的数值tw偏小,tag会叠到数值上
      const tw = ctx.measureText(vText).width;
      // tag去emoji(emoji在canvas宽度不确定+跨平台渲染不一致+分享图更清爽),只留中文文字
      const tagText = "[" + c.tag.replace(/[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}\u{2190}-\u{21FF}\u{2B00}-\u{2BFF}\u{FE00}-\u{FE0F}]/gu, "").trim() + "]";
      ctx.fillStyle = c.color || "#aab2bd"; ctx.font = "22px 'PingFang SC',sans-serif";
      ctx.fillText(tagText, x + 38 + tw, y + 108);
    }
  };
  sentCards.forEach((c, i) => drawDataCard(c, startX + i * (cardW + gap), startY, i));
  widthCards.forEach((c, i) => drawDataCard(c, startX + i * (cardW + gap), startY + cardH + gap, i));

  // 上证迷你走势
  const sparkY = startY + cardH * 2 + gap * 2 + 40;
  const sps = r.indices_sparkline ? Object.values(r.indices_sparkline) : [];
  const sh = sps.find((s) => /sh000001|上证/.test(s.id || s.name)) || sps[0];
  if (sh && sh.closes && sh.closes.length > 1) {
    ctx.fillStyle = "#aab2bd"; ctx.font = "26px 'PingFang SC',sans-serif";
    ctx.fillText(`${sh.name} 近30日走势`, 60, sparkY - 16);
    const up = (sh.pct_change || 0) >= 0;
    const lineColor = up ? "#e6492e" : "#2e8b57";
    const cx0 = 60, cy0 = sparkY, cw = W - 120, ch = 240;
    ctx.strokeStyle = "rgba(255,255,255,0.08)"; ctx.lineWidth = 1;
    _roundRect(ctx, cx0, cy0, cw, ch, 12); ctx.stroke();
    const closes = sh.closes;
    const mn = Math.min(...closes), mx = Math.max(...closes);
    const range = mx - mn || 1;
    const pad = 20;
    ctx.beginPath();
    closes.forEach((v, i) => {
      const x = cx0 + pad + (i / (closes.length - 1)) * (cw - pad * 2);
      const y = cy0 + ch - pad - ((v - mn) / range) * (ch - pad * 2);
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });
    ctx.lineTo(cx0 + cw - pad, cy0 + ch - pad);
    ctx.lineTo(cx0 + pad, cy0 + ch - pad);
    ctx.closePath();
    ctx.fillStyle = lineColor; ctx.globalAlpha = 0.15; ctx.fill(); ctx.globalAlpha = 1;
    ctx.beginPath();
    closes.forEach((v, i) => {
      const x = cx0 + pad + (i / (closes.length - 1)) * (cw - pad * 2);
      const y = cy0 + ch - pad - ((v - mn) / range) * (ch - pad * 2);
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });
    ctx.strokeStyle = lineColor; ctx.lineWidth = 3; ctx.stroke();
    // 涨跌幅标注
    const sign = up ? "+" : "";
    ctx.fillStyle = lineColor; ctx.font = "bold 28px 'PingFang SC',sans-serif";
    ctx.fillText(`${sign}${(sh.pct_change || 0).toFixed(2)}%`, cx0 + cw - 140, cy0 + 36);
  }

  // 底部分隔 + 域名（分隔线让出右侧二维码区）
  ctx.strokeStyle = "rgba(255,255,255,0.15)"; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(60, H - 150); ctx.lineTo(870, H - 150); ctx.stroke();
  ctx.fillStyle = "#165dff"; ctx.font = "bold 34px 'PingFang SC',sans-serif";
  ctx.fillText("s.sugas.site", 60, H - 95);
  ctx.fillStyle = "#aab2bd"; ctx.font = "24px 'PingFang SC',sans-serif";
  ctx.fillText("盘后复盘·多市场情绪·买卖点信号", 60, H - 55);
  // 底部免责水印（合规：教育研究定位，非投资建议）
  ctx.fillStyle = "rgba(170,178,189,0.7)"; ctx.font = "20px 'PingFang SC',sans-serif";
  ctx.fillText("本图仅供学习研究，不构成投资建议 · tdsignal", 60, H - 22);
  // 右下角二维码（扫码访问公网看板；矩阵来自 qr.js，fillRect 同步绘制，无图片加载竞态）
  if (window.QR_MODULES && window.QR_MODULES.length) {
    const mods = window.QR_MODULES, nq = mods.length, quiet = 2;
    const qrSize = 130, cell = qrSize / (nq + quiet * 2);
    const qx = W - 60 - qrSize, qy = H - 12 - qrSize;
    ctx.fillStyle = "#fff";
    _roundRect(ctx, qx - 6, qy - 6, qrSize + 12, qrSize + 12, 8); ctx.fill();
    ctx.fillStyle = "#1f2329";
    const cs = Math.ceil(cell) + 0.5;
    for (let i = 0; i < nq; i++)
      for (let j = 0; j < nq; j++)
        if (mods[i][j]) ctx.fillRect(qx + (j + quiet) * cell, qy + (i + quiet) * cell, cs, cs);
  }
  return canvas;
}

// O3：overview 数据缓存（5 分钟 TTL），避免分享图重复请求已加载的概览数据
const _OVERVIEW_TTL = 5 * 60 * 1000;
let _overviewCache = { data: null, ts: 0 };
function _getCachedOverview() {
  const now = Date.now();
  if (_overviewCache.data && (now - _overviewCache.ts) < _OVERVIEW_TTL) return _overviewCache.data;
  return null;
}
function _setCachedOverview(r) {
  _overviewCache = { data: r, ts: Date.now() };
}

async function openShareModal() {
  // O3：优先复用缓存（概览页已加载过），避免每次点分享都重新请求
  let r = _getCachedOverview();
  if (!r) {
    r = await fetchJSON("./data/overview.json").catch(() => null);
    if (!r) { alert("数据加载失败，无法生成分享图"); return; }
    _setCachedOverview(r);
  }
  let modal = document.getElementById("share-modal");
  if (!modal) {
    modal = document.createElement("div");
    modal.id = "share-modal";
    modal.className = "rule-modal hidden";
    modal.innerHTML = '<div class="rule-modal-overlay"></div><div class="rule-modal-body share-modal-body"><div class="rule-modal-header"><h3>📤 分享图</h3><button class="rule-modal-close" aria-label="关闭">&times;</button></div><div class="rule-modal-content share-content"></div></div>';
    document.body.appendChild(modal);
    modal.querySelector(".rule-modal-close").addEventListener("click", () => modal.classList.add("hidden"));
    modal.querySelector(".rule-modal-overlay").addEventListener("click", () => modal.classList.add("hidden"));
  }
  const content = modal.querySelector(".share-content");
  content.innerHTML = '<div class="summary-history-loading">生成中…</div>';
  modal.classList.remove("hidden");
  document.body.style.overflow = "hidden";
  try {
    const canvas = drawShareCard(r);
    const dataUrl = canvas.toDataURL("image/png");
    content.innerHTML = `<img class="share-img" src="${dataUrl}" alt="信号实验室分享图"><a class="share-download-btn" href="${dataUrl}" download="tdsignal-${r.date}.png">⬇ 下载图片</a>`;
  } catch (e) {
    content.innerHTML = `<div class="summary-history-empty">生成失败：${e}</div>`;
  }
}

function initShareButton() {
  document.querySelectorAll(".share-btn").forEach((b) => {
    b.addEventListener("click", openShareModal);
  });
}

// === 配色皮肤切换 ===
function initThemeSwitcher() {
  var THEMES = [
    { id: "", name: "浅色", desc: "字节蓝", swatch: ["#f5f6f8", "#fff", "#165dff"] },
    { id: "dark", name: "深色专业", desc: "金融终端风", swatch: ["#0d1117", "#161b22", "#58a6ff"] },
    { id: "redgold", name: "红金中国", desc: "琥珀金主色（默认）", swatch: ["#1a1d29", "#252836", "#f0b90b"] },
    { id: "morandi", name: "莫兰迪", desc: "低饱和柔和", swatch: ["#f5f1ec", "#fffaf3", "#6b7c93"] }
  ];
  var modal = document.createElement("div");
  modal.className = "modal theme-modal hidden";
  modal.innerHTML =
    '<div class="modal-body">' +
      '<button class="theme-modal-close" title="关闭">×</button>' +
      '<h3>🎨 切换皮肤</h3>' +
      '<div class="theme-options">' +
        THEMES.map(function (t) {
          return (
            '<button class="theme-option" data-theme="' + t.id + '">' +
              '<span class="theme-swatch">' +
                t.swatch.map(function (c) { return '<span style="background:' + c + '"></span>'; }).join("") +
              '</span>' +
              '<span class="theme-info"><span class="theme-name">' + t.name + '</span>' +
              '<span class="theme-desc">' + t.desc + '</span></span>' +
              '<span class="theme-check">✓</span>' +
            '</button>'
          );
        }).join("") +
      '</div>' +
    '</div>';
  document.body.appendChild(modal);

  var DEFAULT_THEME = "redgold";
  function currentTheme() {
    try {
      var v = localStorage.getItem("trade-theme");
      return v === null ? DEFAULT_THEME : v;
    } catch (e) { return DEFAULT_THEME; }
  }
  function applyTheme(t) {
    // t="" 表示浅色（无 data-theme 即浅色），显式存空串区分"用户选了浅色"与"没选过"
    if (t) document.documentElement.setAttribute("data-theme", t);
    else document.documentElement.removeAttribute("data-theme");
    try { localStorage.setItem("trade-theme", t === "" ? "" : (t || DEFAULT_THEME)); } catch (e) {}
    // 通知模拟回测 iframe 跟随主题切换（URL hash 传初始主题，postMessage 传动态切换）
    document.querySelectorAll('.sim-frame').forEach(function (f) {
      try { if (f.contentWindow) f.contentWindow.postMessage({ type: 'set-theme', theme: t || '' }, window.location.origin); } catch (e) {}
    });
    // ECharts canvas 不响应 CSS 变量，切换主题后下一帧重注入 UI 语义色（等 data-theme 改完 CSS 重算再读色）
    requestAnimationFrame(rethemeCharts);
  }
  function renderActive() {
    var cur = currentTheme();
    modal.querySelectorAll(".theme-option").forEach(function (opt) {
      opt.classList.toggle("active", opt.dataset.theme === cur);
    });
  }
  document.querySelectorAll(".theme-btn").forEach(function (b) {
    b.addEventListener("click", function () {
      renderActive();
      modal.classList.remove("hidden");
    });
  });
  modal.addEventListener("click", function (e) {
    if (e.target === modal || e.target.classList.contains("theme-modal-close")) {
      modal.classList.add("hidden");
      return;
    }
    var opt = e.target.closest(".theme-option");
    if (opt) {
      applyTheme(opt.dataset.theme);
      renderActive();
      setTimeout(function () { modal.classList.add("hidden"); }, 180);
    }
  });
}

// === 数据更新规则 modal（采集时间旁 ℹ️ 图标入口）===
// 复用 rule-modal 结构/样式（CSS 变量自动适配 4 套皮肤）。事件委托绑定 document，
// applyCollectTime 每次 innerHTML 重渲染后 ℹ️ 图标仍可点。
function updateRulesContentHtml() {
  return (
    '<div class="rule-section">' +
      '<h4>📊 各数据源实时时效</h4>' +
      '<div id="ur-freshness" class="ur-freshness"><p class="ur-note">打开弹窗时加载…</p></div>' +
      '<p class="ur-note">绿=实时/收盘最新，灰=T+1正常待更新，黄=滞后，红=异常(>15天)。hover 单项查看源说明。</p>' +
    '</div>' +
    '<div class="rule-section">' +
      '<h4>📅 更新时间表</h4>' +
      '<table class="ur-table"><thead><tr><th>时间</th><th>更新内容</th><th>说明</th></tr></thead><tbody>' +
        '<tr><td>盘中每30分钟</td><td>实时快照</td><td>9:35-15:35，腾讯/同花顺实时数据（含港股盘中实时）</td></tr>' +
        '<tr><td>15:33</td><td>收盘快照</td><td>A股收盘后实时源采当日涨跌幅+热点</td></tr>' +
        '<tr><td>16:35</td><td>港股补采</td><td>港股16:00收盘后补采当日恒生指数</td></tr>' +
        '<tr><td>17:50</td><td>收盘全量</td><td>baostock等T+1源出数据后全量采集</td></tr>' +
        '<tr><td>18:30 + 19:30(兜底)</td><td>龙虎榜单采</td><td>东财18:00发布后单采当日龙虎榜；19:30二次槽应对网络抖动重采</td></tr>' +
        '<tr><td>20:00</td><td>晚间兜底</td><td>补采晚出的申万/港股等数据</td></tr>' +
        '<tr><td>20:05 + 21:00(兜底)</td><td>期货机构持仓单采</td><td>CFFEX股指期货前20名会员持仓~20:00出后单采；21:00二次槽应对异常重采</td></tr>' +
        '<tr><td>20:07 + 21:30(兜底)</td><td>ETF国家队份额单采</td><td>SSE/SZSE ETF份额T+1发布单采；21:30二次槽当日兜底重采</td></tr>' +
        '<tr><td>23:00</td><td>两融单采</td><td>沪市融资余额源盘后发布较晚(实测22:10仍未出),当晚23:00单采当日(采到则当日上线),配合凌晨兜底补齐</td></tr>' +
        '<tr><td>02:00</td><td>凌晨兜底</td><td>补采遗漏确保次日数据齐全</td></tr>' +
      '</tbody></table>' +
    '</div>' +
    '<div class="rule-section">' +
      '<h4>⏱️ 各数据时效</h4>' +
      '<ul class="ur-list">' +
        '<li>📈 <b>A股指数涨跌幅/热点板块/一句话总结</b>：盘中前端动态拉取腾讯分时数据（约3分钟刷新）；30分钟服务器快照仅用于收盘归档与情绪分计算</li>' +
        '<li>🇭🇰 <b>港股指数（恒生/恒生科技/国企）</b>：盘中实时快照（9:30-16:00），16:35 补完整收盘 OHLC</li>' +
        '<li>🇭🇰 <b>港股板块指数</b>：腾讯备源兜底（cesg10/hsmogi/hsmbi/hsmpi/hscci 5个有腾讯兜底）；cshklre/cshklc/cshkdiv 3个仅新浪无备源</li>' +
        '<li>🇺🇸 <b>美股指数</b>：北京时差晚 21:30 开盘，A 股交易日看美股最新是 T-1 或 T-2（跨周末），属正常</li>' +
        '<li>🇺🇸 <b>美股期货 ES/NQ（新浪 hf_ES/hf_NQ）</b>：盘中亚盘时段实时，预估美股当晚开盘方向（ES↔标普500 / NQ↔纳指100），不替代美股收盘价</li>' +
        '<li>📊 <b>指数历史走势 OHLC</b>：T+1（申万/baostock 收盘后次日补全）</li>' +
        '<li>😐 <b>恐贪指数 / per-index 情绪分</b>：快照反哺后当日可用，否则停 T-1</li>' +
        '<li>📋 <b>A股综合情绪分</b>：当日（mootdx 实时算）</li>' +
      '</ul>' +
    '</div>' +
    '<div class="rule-section">' +
      '<h4>🏷️ 卡片角标时效分级</h4>' +
      '<ul class="ur-list">' +
        '<li>📅 <b>T+1·MM-DD（灰）</b>：正常。数据源盘后T+1公布，公开平台（行情软件）也才到这个日期，次日才更新</li>' +
        '<li>⏰ <b>盘中·HH:MM（绿）/ 午休（黄）</b>：实时。A股/港股指数盘中动态拉取，约3分钟刷新</li>' +
        '<li>📍 <b>收盘·MM-DD（主题色）</b>：收盘后归档，数据正常时显示；若滞后则切换为⚠/🚨</li>' +
        '<li>⚠ <b>滞后·MM-DD（黄）</b>：异常。该数据应T+1更新但已滞后（hover 可见天数），公开平台已有更新但我们没采到</li>' +
        '<li>🚨 <b>异常·MM-DD（红）</b>：严重滞后（>15天），请反馈</li>' +
        '<li>本弹窗顶部"📊 各数据源实时时效"区块汇总各数据源最新状态，可一眼区分正常T+1 vs 异常滞后</li>' +
      '</ul>' +
    '</div>' +
    '<div class="rule-section">' +
      '<h4>🔄 盘中动态值说明</h4>' +
      '<ul class="ur-list">' +
        '<li>盘中：卡片涨跌幅、横幅指标 chips、分时图均为前端动态拉取腾讯分时数据，约3分钟刷新，三处数值同源一致</li>' +
        '<li>30分钟服务器快照仅用于收盘归档与情绪分计算，不直接展示盘中数值</li>' +
        '<li>收盘后：切换为服务器收盘快照，停止动态更新</li>' +
      '</ul>' +
    '</div>' +
    '<div class="rule-section">' +
      '<h4>💡 为什么时间更新了但有些数据还是前天的？</h4>' +
      '<p>右上角时间是"脚本跑完时间"。脚本跑了≠每个数据源都采到当日：</p>' +
      '<ul class="ur-list">' +
        '<li>实时快照源（腾讯/同花顺）秒级出当日 -> 这些数据是当天的</li>' +
        '<li>T+1 源（申万/baostock）收盘后次日才发布当日 -> 历史走势/部分情绪分可能停在 T-1</li>' +
        '<li>港股 16:00 收盘（比 A 股晚 1 小时），盘中快照采实时价，16:35 后补完整收盘 OHLC</li>' +
        '<li>美股北京时差晚 21:30 才开盘，A 股交易日看美股最新通常是 T-1 或 T-2（跨周末更久），属正常</li>' +
        '<li>收盘后约 2 小时（17:50 update_all）T+1 源出数据后会补全</li>' +
        '<li>晚 20:00 再兜底补一次，凌晨 02:00 也会兜底一次</li>' +
      '</ul>' +
    '</div>' +
    '<div class="rule-section">' +
      '<h4>📊 近期执行统计</h4>' +
      '<table class="ur-table" id="schedule-stats-table"><thead><tr><th>任务</th><th>调度时点</th><th>预估耗时</th><th>最后执行</th></tr></thead><tbody><tr><td colspan="4">加载中…</td></tr></tbody></table>' +
      '<p class="ur-note">预估耗时＝近10次有效平均；最后执行＝最近一次开始时间，退出码非0标 ⚠️（数据部署时刷新）</p>' +
    '</div>'
  );
}
function _renderScheduleStats(rows) {
  const tb = document.querySelector("#schedule-stats-table tbody");
  if (!tb) return;
  if (!Array.isArray(rows) || !rows.length) {
    tb.innerHTML = '<tr><td colspan="4">暂无统计</td></tr>';
    return;
  }
  tb.innerHTML = rows.map((r) => {
    const warn = (r.last_exit != null && r.last_exit !== 0)
      ? ` <span data-tip="⚠️ 上次执行异常: 退出码=${r.last_exit}（非0=脚本异常退出,可能部分采集失败）。详见日志 data/logs/${r.task || r.name}_launchd.log">⚠️</span>`
      : "";
    return `<tr><td>${r.name || r.task || ""}</td><td>${r.schedule || ""}</td><td>${r.est_text || "-"}</td><td>${r.last_run || "-"}${warn}</td></tr>`;
  }).join("");
}
function _loadScheduleStats() {
  fetchJSON("./data/schedule_stats.json")
    .then(_renderScheduleStats)
    .catch(() => {
      const tb = document.querySelector("#schedule-stats-table tbody");
      if (tb) tb.innerHTML = '<tr><td colspan="4">暂无统计</td></tr>';
    });
}
// 渲染弹窗内"各数据源实时时效"区块（原首页数据时效横幅移入）。
// 复用 _buildHealthSources(overview, snap) 计算各源动态时效，open() 时刷新。
async function _renderFreshnessInModal() {
  const box = document.querySelector("#ur-freshness");
  if (!box) return;
  let r = _getCachedOverview();
  let snap = state.intradaySnapshot;
  // 缓存空（用户未访问首页）时主动 fetch 回填，避免"请先加载首页后重开"影响使用
  if (!r || !snap) {
    box.innerHTML = '<p class="ur-note">加载中…</p>';
    if (!r) {
      r = await fetchJSON("./data/overview.json").catch(() => null);
      if (r) _setCachedOverview(r);
    }
    if (!snap) {
      try { await Promise.race([fetchIntradaySnapshot(), new Promise((res) => setTimeout(res, 1500))]); } catch (e) {}
      snap = state.intradaySnapshot;
    }
  }
  if (!r) { box.innerHTML = '<p class="ur-note">时效数据加载失败，请稍后重试</p>'; return; }
  const sources = _buildHealthSources(r, snap);
  let staleCount = 0, hasSevere = false;
  sources.forEach((s) => {
    if (s.cls === "t1-stale" || s.cls === "t1-severe") staleCount++;
    if (s.cls === "t1-severe") hasSevere = true;
  });
  const summary = hasSevere ? `🚨 ${staleCount}项异常` : staleCount > 0 ? `⚠ ${staleCount}项滞后` : "✓ 全部正常";
  const chips = sources.map((s) =>
    `<span class="ur-fchip ${s.cls}" data-tip="${s.hint || ""}">${s.name}<span class="ur-fval">${s.text}</span></span>`
  ).join("");
  box.innerHTML = `<div class="ur-fsummary">${summary}</div><div class="ur-fchips">${chips}</div>`;
}
function initUpdateRules() {
  const modal = document.createElement("div");
  modal.className = "rule-modal hidden update-rules-modal";
  modal.innerHTML =
    '<div class="rule-modal-overlay"></div>' +
    '<div class="rule-modal-body"><div class="rule-modal-header"><h3>📋 数据更新规则</h3>' +
    '<button class="rule-modal-close" aria-label="关闭">&times;</button></div>' +
    '<div class="rule-modal-content">' + updateRulesContentHtml() + '</div></div>';
  document.body.appendChild(modal);

  const overlay = modal.querySelector(".rule-modal-overlay");
  const closeBtn = modal.querySelector(".rule-modal-close");
  const open = () => { modal.classList.remove("hidden"); document.body.style.overflow = "hidden"; _loadScheduleStats(); _renderFreshnessInModal(); };
  const close = () => { modal.classList.add("hidden"); document.body.style.overflow = ""; };

  // 事件委托：applyCollectTime 每次 innerHTML 重渲染后图标仍可点
  document.addEventListener("click", (e) => {
    if (e.target.closest(".update-rules-btn")) { e.preventDefault(); open(); }
  });
  document.addEventListener("keydown", (e) => {
    if ((e.key === "Enter" || e.key === " ") &&
        document.activeElement && document.activeElement.classList &&
        document.activeElement.classList.contains("update-rules-btn")) {
      e.preventDefault(); open();
    }
    if (e.key === "Escape" && !modal.classList.contains("hidden")) close();
  });
  overlay.addEventListener("click", close);
  closeBtn.addEventListener("click", close);
}


initNavStickyToggle();
initStickyOffset();
initBackToTop();
initRuleButton();
initH5();
initSimOverlay();
initShareButton();
initThemeSwitcher();
initUpdateRules();

// === 主 tab hash 记忆 + 滚动位置恢复 ===
// 切 tab 写 hash（replaceState 不入历史、不触发 hashchange），F5 读 hash 恢复 tab + 滚动位置。
// #lab 开头归 lab.js 的 lab 恢复逻辑（含 #lab/策略key），此模块只管 4 个非 lab 主 tab。
// 大盘 tab 的二级 tab 也写进 hash：#market/{subtab}（如 #market/national-team=汪汪队），
// F5 刷新解析恢复二级 tab，避免刷新回退到默认 a 股。
const _MAIN_TABS = ["overview", "market", "sentiment", "industry"];
const _MARKET_SUBTABS = ["a-stock", "hk", "global", "national-team"];
function _setTabHash(tab) {
  let h = "#" + tab;
  if (tab === "market" && state.subtab) h = "#market/" + state.subtab;
  if (location.hash === h) return;
  try { history.replaceState(null, "", location.pathname + location.search + h); } catch (e) {}
}
let _tabInitialRestore = false;
function _restoreMainTabScroll() {
  try {
    const y = parseInt(sessionStorage.getItem("tabScrollY_" + state.tab) || "0", 10);
    if (y > 0) requestAnimationFrame(() => window.scrollTo(0, y));
  } catch (e) {}
}
// 滚动位置持续保存（per-tab，仅非 lab 主 tab；lab 由 lab.js 的 labScrollY 管理）
let _tabScrollTimer = null;
window.addEventListener("scroll", () => {
  if (!_MAIN_TABS.includes(state.tab)) return;
  if (_tabScrollTimer) clearTimeout(_tabScrollTimer);
  _tabScrollTimer = setTimeout(() => {
    try { sessionStorage.setItem("tabScrollY_" + state.tab, String(window.scrollY)); } catch (e) {}
  }, 200);
}, { passive: true });

// F5 刷新：读 URL hash 恢复主 tab + 大盘二级 tab（#lab 开头归 lab.js 处理）
(function _initMainTabHashRestore() {
  const h = location.hash;
  if (!h || h.startsWith("#lab")) return;
  const parts = h.slice(1).split("/"); // "market/national-team" -> ["market", "national-team"]
  const tab = parts[0];
  if (!_MAIN_TABS.includes(tab)) return;
  state.tab = tab;
  if (tab === "market") {
    // 解析二级 tab，非法/缺失回退 a 股
    const sub = parts[1];
    state.subtab = _MARKET_SUBTABS.includes(sub) ? sub : "a-stock";
  }
  document.querySelectorAll("button[data-tab]").forEach((x) => x.classList.remove("active"));
  const btn = document.querySelector(`button[data-tab="${tab}"]`);
  if (btn) btn.classList.add("active");
  updateH5Topbar();
  _tabInitialRestore = true;
})();
// 采集时间独立获取（不依赖当前 tab），保证切到非概览 tab 刷新后顶部仍显示
fetchCollectTime();
// 盘中实时快照独立获取（不依赖当前 tab），一句话总结覆盖 T+1 缺失数据用
fetchIntradaySnapshot();
// #lab* hash 由 lab.js 接管初始渲染（_labInitHashRestore 的 labBtn.click 触发 renderTab）。
// 此处跳过 bootstrap renderTab，避免与 lab 渲染竞态导致概览内容（含行业热力图）串入实验室页 / 高亮与内容不一致。
if (location.hash.startsWith("#lab")) {
  renderLoadingState(content);
  // B5: 懒加载 lab.js，加载后其末尾 IIFE 读 #lab 自动 click labBtn -> renderTab
  loadLabScript().catch((e) => renderErrorState(content, e, () => location.reload()));
} else {
  renderTab().then(() => {
    if (_tabInitialRestore) { _tabInitialRestore = false; _restoreMainTabScroll(); }
  });
}
