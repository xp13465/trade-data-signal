// 静态版前端 —— 从 web/app.js 改造，数据源由 API 改为本地 JSON 文件。
// 改动点：
//   1. fetchJSON URL：/api/xxx → ./data/xxx.json（各 tab 按 range 读对应文件）
//   2. index 详情：读 https://ssd.fx8.store/index/{id}-all.json 全历史，前端按 ohlc 日期范围过滤 signals
//   3. 其他逻辑（render/ruleBar/signalColor/initBackToTop/initStickyOffset）保持功能一致
//   4. 手动补录入口已移除（与动态版一致）

// BUG-E：交互增强状态——indexFilter（A 股/港股 指数筛选）/ industrySearch（行业搜索）/ heatmapRange（热力图近1日/近5日切换）。
// 筛选只控制前端显示哪些折线/行业，不影响后端数据。
const state = { tab: "overview", range: "3m", indexFilter: "all", industrySearch: "", heatmapRange: "all", subtab: "a-stock", labIndex: "sh", labZone: "sell", labStrategy: null, labData: null, labSimData: null, labSimPair: null, labSimMode: "full_in", labSimPage: 0, intradaySnapshot: null, labWinSync: false, ntEtf: "510300", ntView: "overview", ntDetailRange: null };
const content = document.getElementById("content");
const charts = [];
// 已生成模拟回测页面的品种（📊 模拟回测按钮显示条件）
const SIM_INDICES = new Set([
  'sh', 'sz', 'cyb', 'csi500', 'csi1000', 'kc50', 'hs300', 'sz50',
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

// P2-5: echarts.min.js 按 tab 懒加载（首屏不下载 615KB echarts，省 76% 首屏 JS）
// index.html 不再预加载 echarts.min.js，renderTab 触发时才 dynamic 注入。
// 版本号 URL 由 <meta name="echarts-asset-url"> 持有（bump 同 script 标签机制注入 ?v= 破缓存）。
let _echartsScriptPromise = null;
function loadEcharts() {
  if (_echartsScriptPromise) return _echartsScriptPromise;
  _echartsScriptPromise = new Promise((resolve, reject) => {
    if (typeof echarts !== "undefined") { resolve(); return; }  // 已加载
    const meta = document.querySelector('meta[name="echarts-asset-url"]');
    const src = meta ? meta.content : "./vendor/echarts.min.js";
    const s = document.createElement("script");
    s.src = src;
    s.onload = () => resolve();
    s.onerror = () => { _echartsScriptPromise = null; reject(new Error("echarts load failed")); };
    document.head.appendChild(s);
  });
  return _echartsScriptPromise;
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
      extraCssText: "max-width: min(340px, 80vw); white-space: normal; overflow-wrap: anywhere; word-break: break-word;",  // 防多信号长文案撑宽:宽屏封顶340px强制换行,窄屏80vw;overflow-wrap拆长串(如括号内无空格逗号段)
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
  if (typeof echarts === "undefined") return;  // P2-5: echarts 未加载时跳过（懒加载尚未触发）
  try {
    var dzColor = cssVar("--text-1");
    var vmColor = cssVar("--text-1");
    function retheme(c) {
      if (!c || c.isDisposed()) return;
      var opt = c.getOption();
      var t = chartThemeOpts();
      // 多轴图表：把单对象 yAxis/xAxis 转成与现有等长数组，确保 yAxis[1+] 也更新（Bug1 兜底）
      if (Array.isArray(opt.yAxis) && opt.yAxis.length > 1) {
        t.yAxis = Array.from({length: opt.yAxis.length}, function(){ return t.yAxis; });
      }
      if (Array.isArray(opt.xAxis) && opt.xAxis.length > 1) {
        t.xAxis = Array.from({length: opt.xAxis.length}, function(){ return t.xAxis; });
      }
      c.setOption(t);
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
      // markPoint label 字体色按皮肤适配（2026-07-23 修一刀切改黑色致暗色皮肤看不清）：
      // _autoLabelColor 按皮肤返回不同色，此处对已渲染图表的 markPoint 数据项重新评估注入。
      // 仅处理有 hex itemStyle.color 且已设 label.color 的数据项：
      //   - app.js _autoLabelColor 调用点（7 处）label.color 已设 -> 重新评估
      //   - lab.js 彩色 pin label 继承系列级 #fff 不设 label.color -> 跳过避免误改
      //   - 拼色 pin（itemStyle.color 是渐变对象非 string）-> 跳过保留硬编码 #fff
      if (opt.series && opt.series.length) {
        var seriesUpd = opt.series.map(function (s) {
          if (!s || !s.markPoint || !Array.isArray(s.markPoint.data)) return null;
          var dataChanged = false;
          var newData = s.markPoint.data.map(function (d) {
            if (!d || !d.label || d.label.color == null) return d;
            if (!d.itemStyle || typeof d.itemStyle.color !== "string") return d;
            if (!/^#[0-9a-fA-F]{6}$/.test(d.itemStyle.color)) return d;
            var newColor = _autoLabelColor(d.itemStyle.color);
            if (d.label.color === newColor) return d;
            dataChanged = true;
            return Object.assign({}, d, { label: Object.assign({}, d.label, { color: newColor }) });
          });
          return dataChanged ? { markPoint: { data: newData } } : null;
        }).filter(Boolean);
        if (seriesUpd.length) c.setOption({ series: seriesUpd });
      }
    }
    charts.forEach(retheme);
    _signalModalCharts.forEach(retheme);
    if (typeof _kpiDetailCharts !== "undefined") _kpiDetailCharts.forEach(retheme);
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

// 卖点 markPoint 配色（方案 B 标注，2026-07-06）：买=红、卖点统一绿（止盈/趋势转弱/前买失效均绿）。
// B1+S1（2026-07-05）：buy_aux 辅买=粉紫 #d63384（与 buy 红 区分）。
// 2026-07-20: 取消灰色（买点失败）和橙色（无前买点），卖点统一落 #2e8b57 绿；sell_stop_loss 蓝独立；buy_special_filtered 灰是买类预览，保留。
function signalColor(s) {
  if (s.signal === "buy") return "#e6492e";
  if (s.signal === "buy_aux") return "#d63384";
  if (s.signal === "buy_special") return "#ffd700";  // 追买 金（唐奇安20日上轨突破）
  if (s.signal === "buy_special_filtered") return "#9e9e9e";  // 追买被h5过滤预览 灰（ATR>0.03 OR 量价背离，预览模式不删除）
  if (s.signal === "buy_backup") return "#9c27b0";   // 备买 紫（Supertrend 趋势转向）
  if (s.signal === "sell_stop_loss") return "#3498db";  // 追止损卖 蓝（ATR×3.5 止损，底层规则从 Donchian20 下轨改为 ATR×3，2026-07-21 调 ATR×3.5 降频）
  if (s.signal === "band_hold") return "#ff9800";  // 波段持有 橙（国债波段仓位管理，中性状态，2026-07-24）
  const r = s.reason || "";
  if (r.includes("止盈")) return "#2e8b57";
  return "#2e8b57";  // 2026-07-20: 卖点统一绿（前买失效/无前买点/趋势转弱均落绿，取消灰橙）
}

// markPoint label 文字色：按皮肤适配（非一刀切）。
// 暗色皮肤(dark/redgold)：用 --text-1 浅色字，根治黑字溢出 pin 形到暗卡片背景看不清
//   （label.position 默认 inside，但文字宽于 pin 头时溢出到卡片背景，黑字在暗卡看不清）。
// 浅色皮肤(default/morandi)：保留底色 luminance 逻辑（lum>0.18 用黑字否则白字），
//   适用于 label 在 pin 形内（黑字 on 金/红/绿 pin 可读）。
// 2026-07-20: 原 #ffd700 追买金白字看不清（contrast 1.40 几乎隐形）改黑字达标，
// 2026-07-23: 但暗色皮肤下黑字溢出看不清，改为按皮肤适配。
function _autoLabelColor(bg) {
  var theme = (document.documentElement.getAttribute("data-theme") || "").toLowerCase();
  if (theme === "dark" || theme === "redgold") {
    // 暗色皮肤：统一用浅色字（--text-1），确保溢出 pin 形到暗卡片背景可读
    return cssVar("--text-1") || "#e6edf3";
  }
  // 浅色皮肤：按底色 luminance 选黑白
  // 阈值 0.18 覆盖：#ffd700(0.70)/#9e9e9e(0.34)/#3498db(0.28)/#409eff(0.33)/#e6492e(0.22)/#2e8b57(0.20)/#d63384(0.18临界)/#ff9800(0.49) -> 黑字
  // 仅 #9c27b0(0.12) 等深色保留白字（contrast 6.30 达标）
  var c = (bg || "").replace("#", "");
  if (c.length < 6) return "#fff";
  var toLin = function (v) { v = v / 255; return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
  var r = toLin(parseInt(c.slice(0, 2), 16)),
      g = toLin(parseInt(c.slice(2, 4), 16)),
      b = toLin(parseInt(c.slice(4, 6), 16));
  var lum = 0.2126 * r + 0.7152 * g + 0.0722 * b;
  return lum > 0.18 ? "#000" : "#fff";
}

// markPoint 标签文案（P0-4 去指令化 + P0-3 主标签精简）：
// buy/sell/止盈 -> 中性研究标注描述（非交易指令）；完整 reason 收进 hover tooltip。
// buy→超卖拐点、buy_aux→下轨拐点；
// sell 按 reason 子串细分：
//   止盈(卖点价>前买价，正收益) -> 盈亏+X%（提取 vs前买 正比例）
//   买点失败(卖点价<前买价，负收益) -> 盈亏-X%（与止盈对称，提取 vs前买 负比例，如 -4.61）
//   无前买点(无前买参考无法算盈亏) -> 趋势转弱
function signalLabel(s) {
  if (s.signal === "buy") return "超卖拐点";
  if (s.signal === "buy_aux") {
    // 波段接回（国债波段仓位管理，2026-07-24）：reason 含"波段接回X%"
    const m = (s.reason || "").match(/波段接回(\d+)%/);
    if (m) return "波段接回" + m[1] + "%";
    return "下轨拐点";
  }
  if (s.signal === "buy_special") return "上轨突破";  // 追买 唐奇安20日上轨突破
  if (s.signal === "buy_special_filtered") return "特买(过滤预览)";  // 追买被h5过滤预览（ATR>0.03 OR 量价背离，灰色pin不删除）
  if (s.signal === "buy_backup") return "趋势转向";   // 备买 Supertrend 翻多
  if (s.signal === "sell_stop_loss") {
    const m = (s.reason || "").match(/ATR×([\d.]+)止损/);
    return m ? `ATR×${m[1]}止损` : "ATR止损";  // 从 reason 动态提取倍数(csi_div=×4.5,其他=×3.5),数据驱动;底层规则从 Donchian20 下轨改为 ATR×3,2026-07-21 调 ATR×3.5 降频,趋势跟踪风控
  }
  if (s.signal === "band_hold") return "波段持有";  // 国债波段仓位管理 持有状态（2026-07-24）
  const r = s.reason || "";
  // 波段减仓/止损（国债波段仓位管理，2026-07-24）：reason 含"波段减仓X%"/"波段止损X%"
  if (r.includes("波段减仓") || r.includes("波段止损")) {
    const m = r.match(/波段(减仓|止损)(\d+)%/);
    if (m) return "波段" + m[1] + m[2] + "%";
    return "波段动作";
  }
  if (r.includes("止盈")) {
    // 2026-07-22: vs前买 后可能带 [买点类型] 前缀（主买/辅买/追买/备买），正则用可选组兼容新旧格式
    const m = r.match(/vs前买(?:\[[^\]]+\])?\s*([+-]?\d+(?:\.\d+)?)\s*%/);
    if (m) return "盈亏" + m[1] + "%";
    return "盈亏拐点";
  }
  // 买点失败（卖点价<前买价，负收益）-> 盈亏-X%（与止盈对称，reason 里如 vs前买[追买]-4.61%，正则提取负号）
  if (r.includes("买点失败")) {
    const m = r.match(/vs前买(?:\[[^\]]+\])?\s*([+-]?\d+(?:\.\d+)?)\s*%/);
    if (m) return "盈亏" + m[1] + "%";  // m[1] 已含负号如 -4.61
    return "亏损拐点";
  }
  // 无前买点（无前买参考无法算盈亏）-> 趋势转弱
  return "趋势转弱";  // 2026-07-20: 无前买点统一落趋势转弱（卖点统一绿）
}

// 多色拼色 pin（2026-07-22 方案A 重构）：同日全部信号（买/卖/止损，不分买卖语义）
// 整体合并为 1 个 pin。单信号保持单色 pin（原行为）；多信号拼色 pin
// （_ntMultiColor 分段渐变 + 金描边 + 光晕，参照汪汪队共振信号 L4486-4521）。
// 修复"多 pin 同 coord 后画盖先画"问题：同日 N 信号只画 1 个拼色 pin，不互相盖住。
// getValueFn(date) 返回该日 y 值（close 或 value），用于 pin coord 定位。
function _buildSignalMarkData(signals, getValueFn) {
  const byDate = {};
  for (const s of signals) {
    if (!byDate[s.date]) byDate[s.date] = [];
    byDate[s.date].push(s);
  }
  const markData = [];
  for (const date of Object.keys(byDate).sort()) {
    const daySigs = byDate[date];
    const y = getValueFn(date);
    if (daySigs.length === 1) {
      // 单信号：保持单色 pin（原行为）
      const s = daySigs[0];
      markData.push({
        coord: [date, y],
        value: signalLabel(s),
        reason: s.reason || "",
        itemStyle: { color: signalColor(s) },
        label: { color: _autoLabelColor(signalColor(s)) },
      });
    } else {
      // 多信号同日：拼色 pin（金描边+光晕，买+卖/多买/多卖合一展示叠加价值）
      const labels = daySigs.map(signalLabel);
      const segColors = daySigs.map(signalColor);
      markData.push({
        coord: [date, y],
        value: labels.join("+"),
        reason: daySigs.map((s) => s.reason || "").filter(Boolean).join("<br/>---<br/>"),
        symbolSize: 52,
        label: { fontSize: 11, color: "#fff", formatter: labels.join("\n"), lineHeight: 13 },
        itemStyle: {
          color: _ntMultiColor(segColors),
          borderColor: "#ffd700",
          borderWidth: 3,
          shadowBlur: 8,
          shadowColor: "rgba(255,215,0,0.6)",
        },
        tipColors: segColors,   // 拼色各段颜色，供 tooltip 渲染多色●（方案3 修拼色 tooltip bug）
        tipLabels: labels,      // 拼色各段标签，供 tooltip 渲染多色●
      });
    }
  }
  return markData;
}

// 备买信号 chip 三档优化（2026-07-23）：删除旧版硬编码 9 指数二分（_BACKUP_SIGNAL_CHIP），
// 改读 trade_sim JSON 实时算 4 单买点场景（主买+卖/辅买+卖/追买+卖/备买+卖）对比取最强，
// 全仓进出路径（最能体现买点本身表现），近5年窗口（_TRADE_SIM_DEFAULT_WIN）。
// 三档 chip（标题下换行单独一行展示，3 chip 横排）：
//   📈 年化最高（金）   - 4 买点里年化最高那个
//   👍 最稳健（蓝）     - 多维综合分最高（胜率40%+低回撤40%+样本20%），显回撤+胜率
//   🛡 回撤最小（绿）   - 最大回撤最小那个
// 同一买点只显1 chip（避免重复），优先级 年化>稳健>回撤；分散时最多3并排。
// tooltip 补完整 4 买点对比 + 合规文案"研究参考，不构成投资建议，历史回测不代表未来"。
// 合规文案：年化最高/回撤最小是回测术语，非"最赚钱"导向词。
var _backupChipLoading = {};  // 防并发重复 fetch 同一 index
// A+B 融合方案（2026-07-23）：跨 5窗口×3路径×11场景=165 回测综合排名，原仅 y5 单窗口 4 单买 2.4% 切片面片。
// 三档选择改为全维度归一化综合分（防 y1 小样本虚高）：
//   年化最高档 = 综合分最高（年化50% + 胜率25% + 低回撤15% + 样本10%）
//   最稳健档  = 综合分最高（胜率40% + 低回撤40% + 样本20%）
//   回撤最小档 = max_drawdown 最小（跨全 165）
// chip val 两行：首行 {scenario}·{path缩写}；次行 5 窗口年化对比 / 稳健指标 / 回撤指标
// 去重粒度：scenario+path+win 三元组（2026-07-23 弱化,解决18/19缺档）
var _BACKUP_CHIP_WINS = ["y1", "y3", "y5", "y10", "all"];
var _BACKUP_CHIP_PATHS = ["买固定1w(10%)+卖清仓", "全仓进出", "固定1w(10%)进出（FIFO）"];
var _BACKUP_CHIP_SCENARIOS_ALL = [
  "主买+卖", "辅买+卖", "追买+卖", "备买+卖",
  "主买+辅买+卖", "主买+追买+卖", "主买+备买+卖",
  "辅买+追买+卖", "辅买+备买+卖", "追买+备买+卖",
  "追买+追止损卖"
];
var _BACKUP_CHIP_PATH_SHORT = {
  "买固定1w(10%)+卖清仓": "1w清仓",
  "全仓进出": "全仓",
  "固定1w(10%)进出（FIFO）": "1w先进先出"
};
// 三档绝对值门槛（2026-07-23 防"弱标的年化0.x%也推荐"bug）：不达标不进档，全 null 显示兜底文案。
//   年化最高档：年化必须 >=3%（低于3%无推荐价值，不如存银行）
//   最稳健档：综合分 >=0.5（满分1.0）AND 胜率 >=60% AND 回撤 <=20% AND 年化>回撤（收益必须覆盖回撤，
//             防 0% 年化 + 1~3% 回撤的"稳健"策略实际亏本却推荐，2026-07-24 上证50 case 修复）
//   回撤最小档：回撤 <=15%（>15%谈不上"最小"优势）AND 样本 >=3（样本太少不算）AND 年化>0
//             （回撤低但年化为0/负的策略无推荐价值，2026-07-24 加门槛）
//   门槛集中在此常量，方便后续调整（用户决策：加绝对值门槛 + 隐藏弱标的）。
var _BACKUP_CHIP_THRESHOLDS = {
  ann: 3.0,           // 年化最高档门槛：年化 >=3%
  steadyScore: 0.5,   // 最稳健档综合分 >=0.5（满分1.0）
  steadyWinRate: 60,  // 最稳健档胜率 >=60%
  steadyMaxDd: 20,    // 最稳健档回撤 <=20%
  ddMax: 15,          // 回撤最小档回撤 <=15%
  ddMinOps: 3,        // 回撤最小档样本 >=3
  ddMinAnn: 0.0       // 回撤最小档年化 >0（防0%年化策略被推为"回撤最小"）
};
// 在 chart-card 的 h3 之后插入独立 chip-row 容器（标题下换行单独一行展示）。
// SIM_INDICES 之外的指数不显示；已缓存数据同步渲染，未缓存先占位再异步 fetch+patch。
function _appendBackupChipRow(cardEl, id) {
  if (!SIM_INDICES.has(id)) return;
  var html = _backupSignalChipRender(_tradeSimStatsCache[id]);
  var row = document.createElement("div");
  row.className = "signal-chip-row";
  row.setAttribute("data-chip-id", id);
  // 占位: 未缓存时先放 loading 提示，异步 fetch 完成后整体替换 innerHTML
  row.innerHTML = html || '<span class="signal-chip signal-chip-loading">⏳ 加载回测…</span>';
  // 2026-07-20 板分化适配：行业 spark-cell 无 h3，加 .spark-head 兜底插入点，保证 [标题][chip-row][sim-btn] 顺序
  var h3 = cardEl.querySelector("h3");
  if (h3) h3.after(row);
  else {
    var head = cardEl.querySelector(".spark-head");
    if (head) head.after(row);
    else cardEl.appendChild(row);
  }
  // 未缓存：触发异步加载
  if (!_tradeSimStatsCache[id]) _backupSignalChipLoad(id);
}
async function _backupSignalChipLoad(id) {
  if (_backupChipLoading[id]) return;
  _backupChipLoading[id] = true;
  try {
    var sd = _tradeSimStatsCache[id] || await _tradeSimFetchStats(id);
    _tradeSimStatsCache[id] = sd;
    var html = _backupSignalChipRender(sd);
    var placeholders = document.querySelectorAll('.signal-chip-row[data-chip-id="' + id + '"]');
    placeholders.forEach(function (el) { el.innerHTML = html; });
  } catch (e) {
    var errEls = document.querySelectorAll('.signal-chip-row[data-chip-id="' + id + '"]');
    errEls.forEach(function (el) { el.innerHTML = '<span class="signal-chip signal-chip-error">⚠ 回测加载失败</span>'; });
  } finally {
    _backupChipLoading[id] = false;
  }
}
// 算三档 chip HTML（A+B 融合方案）：遍历全 165 回测，归一化综合分排名。数据不足返回空串。
function _backupSignalChipRender(sd) {
  if (!sd || !sd.data) return '';
  // 窗口 key -> 中文 label 映射（优先用后端 sd.windows.l，缺失兜底硬编码；2026-07-23 chip 英文中文化）
  var winLabel = Object.assign(
    { y1: '近1年', y3: '近3年', y5: '近5年', y10: '近10年', all: '全史' },
    sd.windows ? Object.fromEntries(sd.windows.map(function (w) { return [w.k, w.l]; })) : {}
  );
  // 遍历 5 窗口 × 3 路径 × 11 场景 = 165 回测
  var allEntries = [];
  for (var wi = 0; wi < _BACKUP_CHIP_WINS.length; wi++) {
    var win = _BACKUP_CHIP_WINS[wi];
    var byWin = sd.data[win];
    if (!byWin) continue;
    for (var pi = 0; pi < _BACKUP_CHIP_PATHS.length; pi++) {
      var path = _BACKUP_CHIP_PATHS[pi];
      var byPath = byWin[path];
      if (!byPath) continue;
      for (var si = 0; si < _BACKUP_CHIP_SCENARIOS_ALL.length; si++) {
        var sc = _BACKUP_CHIP_SCENARIOS_ALL[si];
        var blk = byPath[sc];
        var s = blk && blk.summary;
        if (!s) continue;
        if (typeof s.annualized !== 'number' || typeof s.max_drawdown !== 'number' ||
            typeof s.win_rate !== 'number' || typeof s.total_ops !== 'number') continue;
        allEntries.push({
          scenario: sc,
          label: sc.replace(/\+卖$/, ''),
          path: path,
          pathShort: _BACKUP_CHIP_PATH_SHORT[path] || path,
          win: win,
          annualized: s.annualized,
          max_drawdown: s.max_drawdown,
          win_rate: s.win_rate,
          total_ops: s.total_ops
        });
      }
    }
  }
  if (allEntries.length < 2) return '';  // 不足 2 条无法对比
  // 跨全 165 归一化（0-1）
  var maxAnn = Math.max.apply(null, allEntries.map(function (e) { return e.annualized; }));
  var minAnn = Math.min.apply(null, allEntries.map(function (e) { return e.annualized; }));
  var maxDd = Math.max.apply(null, allEntries.map(function (e) { return e.max_drawdown; }));
  var minDd = Math.min.apply(null, allEntries.map(function (e) { return e.max_drawdown; }));
  var maxWr = Math.max.apply(null, allEntries.map(function (e) { return e.win_rate; }));
  var minWr = Math.min.apply(null, allEntries.map(function (e) { return e.win_rate; }));
  var maxOps = Math.max.apply(null, allEntries.map(function (e) { return e.total_ops; }));
  var minOps = Math.min.apply(null, allEntries.map(function (e) { return e.total_ops; }));
  function norm(v, mn, mx) { return mx > mn ? (v - mn) / (mx - mn) : 0; }
  function ddNorm(dd) { return (maxDd > minDd) ? (maxDd - dd) / (maxDd - minDd) : 1; }  // 回撤越小越好故取反
  var scored = allEntries.map(function (e) {
    var annNorm = norm(e.annualized, minAnn, maxAnn);
    var wrNorm = norm(e.win_rate, minWr, maxWr);
    var ddN = ddNorm(e.max_drawdown);
    var opsNorm = norm(e.total_ops, minOps, maxOps);
    return Object.assign({}, e, {
      // 年化最高档综合分：年化50% + 胜率25% + 低回撤15% + 样本10%
      strongScore: annNorm * 0.5 + wrNorm * 0.25 + ddN * 0.15 + opsNorm * 0.10,
      // 最稳健档综合分：胜率40% + 低回撤40% + 样本20%
      steadyScore: wrNorm * 0.4 + ddN * 0.4 + opsNorm * 0.2
    });
  });
  // 三档绝对值门槛过滤（防弱标的年化0.x%也推荐）：先筛达标候选，再按维度排序取最高。无达标 -> null
  var TH = _BACKUP_CHIP_THRESHOLDS;
  // 1. 年化最高 = strongScore 最高（年化必须 >= TH.ann）
  var annCandidates = scored.filter(function (e) { return e.annualized >= TH.ann; });
  var bestAnn = annCandidates.length > 0
    ? annCandidates.slice().sort(function (a, b) { return b.strongScore - a.strongScore; })[0]
    : null;
  // 2. 最稳健 = steadyScore 最高（综合分>=0.5 AND 胜率>=60 AND 回撤<=20 AND 年化>回撤）
  // 2026-07-24 加年化>回撤门槛：防"0%年化+1~3%回撤"的伪稳健策略被推（收益不覆盖回撤=实际亏）
  var steadyCandidates = scored.filter(function (e) {
    return e.steadyScore >= TH.steadyScore && e.win_rate >= TH.steadyWinRate
      && e.max_drawdown <= TH.steadyMaxDd && e.annualized > e.max_drawdown;
  });
  var bestSteady = steadyCandidates.length > 0
    ? steadyCandidates.slice().sort(function (a, b) { return b.steadyScore - a.steadyScore; })[0]
    : null;
  // 3. 回撤最小 = max_drawdown 最小（回撤<=15% AND 样本>=3 AND 年化>0）
  // 2026-07-24 加年化>0门槛：防0%年化策略被推为"回撤最小"（无收益的极低回撤无推荐价值）
  var ddCandidates = scored.filter(function (e) { return e.max_drawdown <= TH.ddMax && e.total_ops >= TH.ddMinOps && e.annualized > TH.ddMinAnn; });
  var bestDd = ddCandidates.length > 0
    ? ddCandidates.slice().sort(function (a, b) { return a.max_drawdown - b.max_drawdown; })[0]
    : null;
  // 去重：scenario+path+win 三元组只显 1 chip（优先级 年化>稳健>回撤）
  // 2026-07-23 弱化去重（原 scenario+path 二元组致 18/19 缺档：best_dd 与 best_steady 撞同一 entry 被吞）
  // 副作用：同 scenario+path 不同 win 可能显 2 档（信息完整优先，可视觉冗余接受）
  var used = {};
  var chips = [];
  if (bestAnn) { chips.push({ kind: 'strong', tier: '年化最高', entry: bestAnn }); used[bestAnn.scenario + '|' + bestAnn.path + '|' + bestAnn.win] = 1; }
  if (bestSteady) {
    var kS = bestSteady.scenario + '|' + bestSteady.path + '|' + bestSteady.win;
    if (!used[kS]) { chips.push({ kind: 'steady', tier: '最稳健', entry: bestSteady }); used[kS] = 1; }
  }
  if (bestDd) {
    var kD = bestDd.scenario + '|' + bestDd.path + '|' + bestDd.win;
    if (!used[kD]) { chips.push({ kind: 'lowdraw', tier: '回撤最小', entry: bestDd }); used[kD] = 1; }
  }
  if (chips.length === 0) {
    // 三档全 null（弱标的整体不达标）：显示兜底文案，区别于三色档中性灰
    return '<div class="signal-chip chip-weak-placeholder">📉 该标的回测表现均较弱，暂无优质买点推荐（年化均<' + TH.ann + '%或样本不足）<span class="chip-tip">详见完整回测 modal，历史表现不代表未来</span></div>';
  }
  // chip val 第二行：该 scenario+path 在 5 窗口的年化对比
  function win5Ann(e) {
    var parts = [];
    for (var i = 0; i < _BACKUP_CHIP_WINS.length; i++) {
      var w = _BACKUP_CHIP_WINS[i];
      var s = sd.data && sd.data[w] && sd.data[w][e.path] && sd.data[w][e.path][e.scenario] && sd.data[w][e.path][e.scenario].summary;
      if (s && typeof s.annualized === 'number') {
        parts.push(winLabel[w] + (s.annualized >= 0 ? '+' : '') + s.annualized.toFixed(1) + '%');
      }
    }
    return parts.join(' ');
  }
  // chip val 两行格式
  function formatVal(c) {
    var e = c.entry;
    var line1 = e.label + ' · ' + e.pathShort;
    var line2;
    if (c.kind === 'strong') {
      line2 = win5Ann(e);  // y1+X% y3+Y% y5+Z% y10+W% all+V%
    } else if (c.kind === 'steady') {
      line2 = '回撤-' + e.max_drawdown.toFixed(1) + '% 胜率' + e.win_rate.toFixed(0) + '% (5窗口均稳)';
    } else {
      line2 = winLabel[e.win] + '回撤-' + e.max_drawdown.toFixed(1) + '% (全维度最小)';
    }
    return { line1: line1, line2: line2 };
  }
  return chips.map(function (c) {
    var emoji = c.kind === 'strong' ? '📈' : c.kind === 'steady' ? '👍' : '🛡';
    var cls = c.kind === 'strong' ? 'signal-chip-strong' : c.kind === 'steady' ? 'signal-chip-steady' : 'signal-chip-lowdraw';
    var tip = _backupSignalChipTip(sd, scored, c);
    var v = formatVal(c);
    return '<span class="signal-chip ' + cls + '" data-tip="' + tip + '">' + emoji + ' ' + c.tier + ' · ' + v.line1 + '&#10;   ' + v.line2 + '</span>';
  }).join('');
}
// chip tooltip：该档 scenario+path 5 窗口 summary + 全 165 该维度 Top5 + 合规文案
// 2026-07-23 格式美化：区块分隔线 + │ 列分隔 + ⚠ 合规前缀；winLabel 本函数内自建(隔离 _backupSignalChipRender 局部作用域)
function _backupSignalChipTip(sd, scored, chip) {
  var e = chip.entry;
  // 窗口 key -> 中文 label 映射（优先 sd.windows.l，兜底硬编码；同 _backupSignalChipRender）
  var winLabel = Object.assign(
    { y1: '近1年', y3: '近3年', y5: '近5年', y10: '近10年', all: '全史' },
    sd.windows ? Object.fromEntries(sd.windows.map(function (w) { return [w.k, w.l]; })) : {}
  );
  // 窗口 key -> 起止日期 "s~e" 映射（2026-07-24 时间窗口强化：显示回测区间起止日期）
  // sd.windows[].s/e 为后端返回的窗口起止日期（如 y5: 2021-07-22~2026-07-22）
  var winRange = {};
  if (sd.windows) {
    sd.windows.forEach(function (w) {
      if (w.s && w.e) winRange[w.k] = w.s + '~' + w.e;
    });
  }
  var SEP = '────────────────────';
  var lines = ['【' + chip.tier + '】' + e.label + ' · ' + e.pathShort + ' · ' + winLabel[e.win] + ' 综合分胜出'];
  // 顶部显示整体回测区间（all 窗口 s~e，覆盖最长历史；缺失则用 y5 兜底）
  var overallRange = winRange.all || winRange.y5 || '';
  if (overallRange) lines.push('回测区间: ' + overallRange);
  lines.push('该买点+路径在 5 窗口表现（' + e.scenario + ' · ' + e.path + '）：');
  for (var i = 0; i < _BACKUP_CHIP_WINS.length; i++) {
    var w = _BACKUP_CHIP_WINS[i];
    var s = sd.data && sd.data[w] && sd.data[w][e.path] && sd.data[w][e.path][e.scenario] && sd.data[w][e.path][e.scenario].summary;
    if (s) {
      // 每个窗口行末尾加 [s~e] 起止日期，让用户明确各窗口具体回测时段
      var rng = winRange[w] ? '  [' + winRange[w] + ']' : '';
      lines.push('  ' + winLabel[w] + '  年化' + (s.annualized || 0).toFixed(1) + '% │ 回撤' + (s.max_drawdown || 0).toFixed(1) + '% │ 胜率' + (s.win_rate || 0).toFixed(0) + '% │ 样本' + (s.total_ops || 0) + rng);
    }
  }
  // 全 165 该维度 Top5
  var top5, label;
  if (chip.kind === 'strong') {
    top5 = scored.slice().sort(function (a, b) { return b.strongScore - a.strongScore; }).slice(0, 5);
    label = '年化综合';
  } else if (chip.kind === 'steady') {
    top5 = scored.slice().sort(function (a, b) { return b.steadyScore - a.steadyScore; }).slice(0, 5);
    label = '稳健综合';
  } else {
    top5 = scored.slice().sort(function (a, b) { return a.max_drawdown - b.max_drawdown; }).slice(0, 5);
    label = '回撤最小';
  }
  lines.push(SEP);
  lines.push('全 165 回测 · ' + label + ' Top5：');
  for (var i = 0; i < top5.length; i++) {
    var t = top5[i];
    lines.push('  ' + (i + 1) + '. ' + t.label + '·' + t.pathShort + '·' + winLabel[t.win] + '  年化' + t.annualized.toFixed(1) + '% │ 回撤' + t.max_drawdown.toFixed(1) + '% │ 胜率' + t.win_rate.toFixed(0) + '% │ 样本' + t.total_ops);
  }
  lines.push(SEP);
  lines.push('⚠ 研究参考，不构成投资建议 · 历史回测不代表未来');
  lines.push('综合排名覆盖全维度（5窗口×3路径×11场景=165回测），年化最高/回撤最小为综合分排名结果（非纯极值，防小样本虚高）。');
  // HTML attribute 里换行需转义为 &#10;（textContent 解析时还原为 \n，.term-pop white-space: pre-line 渲染换行）
  return lines.join('&#10;').replace(/"/g, '&quot;');
}

// 6色信号图例（2026-07-23 三档优化版）：4色买点(主买红/辅买玫红/追买金/备买紫) + 卖绿 + 追止损蓝，
// 指数走势图上方统一展示。备买风险提示附末尾（hover pop 显示"备买稳健性弱于追买仅供参考不单独决策"）。
// 同日多买点信号合并拼色 pin（金描边+光晕），图例不单独列拼色（用户从 pin 视觉即可辨识）。
// 三档 chip（年化最高/最稳健/回撤最小）在每个指数卡片内 chip-row 单独一行展示，chip 自带档位标签+买点名+数值，
// 不再在图例条重复展示 mini-legend（消除"分2处"）。图例末尾保留 ❓ termTip 解释 4 买点（重点备买=Supertrend翻多确认的备选买点）。
var _BACKUP_LEGEND_TIP = "4 买点（主买/辅买/追买/备买）历史回测表现差异较大，每个指数标题下方的三档 chip 标注该指数近5年全仓进出回测中表现最优的买点（年化最高/最稳健/回撤最小）。研究参考，不构成投资建议，历史回测不代表未来。";
var _BACKUP_BUYPOINT_TIP = "4 买点：主买=RSI(14)上穿30超卖拐点；辅买=布林下轨回归左侧布局；追买=Donchian20日上轨突破+5日确认；备买=Supertrend ATR×3翻多+3日二次确认的趋势反转备选买点（稳健性弱于追买，仅供参考不单独决策）。";
function _signalLegendHtml() {
  return '<div class="signal-legend">'
    + '<span class="signal-legend-item"><i style="background:#e6492e"></i>超卖拐点(主买)</span>'
    + '<span class="signal-legend-item"><i style="background:#d63384"></i>下轨拐点(辅买)</span>'
    + '<span class="signal-legend-item"><i style="background:#ffd700"></i>上轨突破(追买)</span>'
    + '<span class="signal-legend-item"><i style="background:#9c27b0"></i>趋势转向(备买)</span>'
    + '<span class="signal-legend-item"><i style="background:#2e8b57"></i>趋势转弱(卖)</span>'
    + '<span class="signal-legend-item"><i style="background:#3498db"></i>ATR×3.5止损(追止损|卖)</span>'
    + '<span class="term-tip" data-tip="' + _BACKUP_BUYPOINT_TIP.replace(/"/g, '&quot;') + '">❓</span>'
    + '<span class="signal-legend-note" data-tip="' + _BACKUP_LEGEND_TIP + '">⚠ 买点回测差异提示</span>'
    + '</div>';
}

// markPoint reason 换行格式化：reason 是后端 ", ".join(parts) 拼的逗号分隔串
// （如 "20日高回落5%(高78.74->阈74.8,close70.16), RSI=53, MA60=51.13[趋势过滤], vs前买+7.44%[止盈]"）。
// 按 ", "（逗号+空格）断成多行——段内括号里的逗号无空格不会被拆，防 tooltip 单行过长超宽。
function _fmtReason(r) {
  return r ? String(r).replace(/, /g, "<br/>") : "";
}

// 波段仓位比例可视化（国债波段仓位管理，2026-07-24）：解析 reason 中"波段减仓X%"/"波段接回X%"/"波段止损"/"波段持有"，
// 返回 HTML 仓位变化进度条（不只文字 reason，直观展示仓位动态调整）。非波段信号返回 ""。
// 设计：减仓=绿色条减少（100%->80%/70%）；接回=粉紫条增加（80%/70%->100%）；止损=蓝色清仓（100%->0%）；持有=橙色满仓维持。
// 国债波段策略是动态仓位管理（非静态 sell）：根据 RSI+乖离+布林三指标超买超卖动态调仓，
// 减仓(触超买)/接回(超卖回归)/止损(趋势破位)/持有(无信号维持)四动作联动，走势图 pin 即历史调仓时点回放。
function _bandPositionBar(reason) {
  if (!reason) return "";
  var r = String(reason);
  var m = r.match(/波段减仓(\d+)%/);
  if (m) {
    var pct = parseInt(m[1], 10);
    return _positionBarHtml(100, 100 - pct, "减仓" + pct + "%", "#2e8b57");
  }
  m = r.match(/波段接回(\d+)%/);
  if (m) {
    var pct = parseInt(m[1], 10);
    return _positionBarHtml(100 - pct, 100, "接回" + pct + "%", "#d63384");
  }
  if (r.includes("波段止损")) {
    return _positionBarHtml(100, 0, "止损清仓", "#3498db");
  }
  if (r.includes("波段持有")) {
    return _positionBarHtml(100, 100, "持有·仓位不变", "#ff9800");
  }
  return "";
}
// 仓位条 HTML：before% -> after%，label + 颜色，inline-block 适配 echarts tooltip。
// 满仓部分用 color，空仓部分用半透明灰（深浅皮肤均可见），箭头 -> 表示变化方向。
function _positionBarHtml(before, after, label, color) {
  function bar(pct, col) {
    return '<span style="display:inline-block;width:44px;height:8px;background:linear-gradient(to right,' + col + ' ' + pct + '%,rgba(127,127,127,0.3) ' + pct + '%);border-radius:2px;vertical-align:middle"></span>';
  }
  return '<div style="margin-top:3px;font-size:11px;line-height:1.5;white-space:nowrap">'
    + '<span style="color:#aaa">' + label + ':</span> '
    + bar(before, "rgba(127,127,127,0.5)") + '<span style="color:#aaa;padding:0 1px">' + before + '%</span>'
    + '<span style="color:#666;padding:0 2px">-></span>'
    + bar(after, color) + '<span style="color:' + color + ';font-weight:600;padding:0 1px">' + after + '%</span>'
    + '</div>';
}
// _fmtReason + 波段仓位条（tooltip 统一调用：reason 文字 + 仓位可视化，非波段信号仅返回 reason 文字）
function _fmtReasonWithBand(reason) {
  var base = _fmtReason(reason);
  var bar = _bandPositionBar(reason);
  return base + (bar ? '<br/>' + bar : '');
}

// 情绪分文字标签：散户秒懂，数值旁边加标签
function sentimentTag(value) {
  if (value == null) return "";
  if (value <= 20) return "🔵 冰点";
  if (value <= 40) return "🟦 偏冷";
  if (value <= 60) return "⚪ 中性";
  if (value <= 80) return "🟠 偏热";
  return "🔴 过热";
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

// 恐贪标签颜色：冰点=蓝，偏冷=浅蓝，中性=灰，偏热=橙，过热=红（与热力图一致：冰=冷色，过热=热色）
function fearGreedColor(value) {
  if (value == null) return "#86909c";
  if (value <= 25) return "#42a5f5";
  if (value <= 40) return "#4fc3f7";
  if (value <= 60) return "#86909c";
  if (value <= 75) return "#e6a23c";
  return "#e6492e";
}

// index_id → 中文名 转译（散户友好，去除代码前缀，查不到保留原值）
const _INDEX_NAME_MAP = {
  // A股宽基
  sh: '上证指数', sz: '深证成指', cyb: '创业板指', csi500: '中证500', csi1000: '中证1000',
  kc50: '科创50', bj50: '北证50', hs300: '沪深300', sz50: '上证50',
  // 港股
  hsi: '恒生指数', hscei: '国企指数', hstech: '恒生科技',
  // 港股板块指数（来自 hk-5y.json，i18n 中文化 2026-07-20）
  hk_cesg10: '中华博彩业', hk_hsmogi: '恒生内地油气', hk_hsmbi: '恒生内地银行',
  hk_hsmpi: '恒生内地地产', hk_cshklre: '中证香港地产', hk_cshklc: '中证香港消费',
  hk_hscci: '恒生中资企业', hk_cshkdiv: '中证香港红利',
  // 美股
  us_dji: '道琼斯', us_ixic: '纳斯达克', us_spx: '标普500', us_ndx: '纳斯达克100',
  // 全球股指（2026-07-16 上线，中文名以后端 index_backfill.py HK_GLOBAL_INDICES 为准，前端简短化）
  nikkei225: '日经225', kospi: '首尔综合', ftse100: '富时100', dax: '德国DAX', cac40: '法国CAC40',
  // 红利/低波
  div_lowvol: '红利低波', csi_div: '中证红利', sz_div: '深证红利',
  // 全球指标
  cn10y: '中国10年国债', us10y: '美国10年国债', wti_oil: 'WTI原油', brent: '布伦特原油',
  cgb_idx: '中证国债', cgb_10y_etf: '10年国债ETF', cgb_10y_future: '10年国债期货',
  comex_silver: 'COMEX白银', gold: '伦敦金', oil: '原油', usdcnh: '美元/离岸人民币',
  a_qvix_300: '中国波指300', a_qvix_1000: '中国波指(50ETF期权)', cn_us_spread: '中美利差',
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
      ? `<span class="sig-item sig-clickable" data-idx="${it.index_id}" data-sig="${it.signal}" data-date="${it.date}" title="${it.reason ? it.reason + ' · ' : ''}点击查看走势图"><b class="${it.signal}">${signalLabel(it)}</b> ${indexIdToName(it.index_id)}</span>`
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
// stats = {buy:{10d:{win_rate,pl,mean,n}}, buy_aux:..., buy_special:..., buy_backup:..., sell:...}
// buy=主买(超卖拐点) / buy_aux=辅买(下轨拐点) / buy_special=追买(上轨突破) / buy_backup=备买(趋势转向) / sell=卖点(趋势转弱)。
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
// fix: KPI弹窗标题>转义异常(a_turnover_gt5_pct 显示为 &gt;)。
// innerHTML 序列化文本节点时按 HTML spec 把 > 转 &gt;,stripHtml 若不反转义,textContent 设置后显示字面量 &gt;。
// 末尾反转义 HTML 实体,顺序:实体字符先转,&amp; 必须最后(否则会把 &gt; 里的 & 转成 & 再二次转义出错)。
function stripHtml(s) { return String(s == null ? "" : s).replace(/<span class="term-tip"[^>]*>[\s\S]*?<\/span>/g, "").replace(/<[^>]+>/g, "").replace(/&gt;/g, ">").replace(/&lt;/g, "<").replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&nbsp;/g, " ").replace(/&amp;/g, "&").replace(/\s+/g, " ").trim(); }

// A：标题旁 ❓ 小问号 hover 提示（专业术语白话，原生 title 属性，无需 JS tooltip）
function termTip(text) {
  return ` <span class="term-tip" data-tip="${text}">❓</span>`;
}

// 6色技术信号解释 modal（首页"近期技术分析参考点"卡片标题 ❓ 点击弹窗，方案6）
// hover pop 简短提示 + click 弹窗6色信号详细解释（主买/辅买/追买/备买/卖/追止损卖）
// 复用 .rule-modal 样式 + 内联 style（不改 CSS），与 📋 策略说明 modal 风格一致。
const _SIGNAL_HELP_ITEMS = [
  { sig: "buy", color: "#e6492e", name: "主买 · 超卖拐点", desc: "RSI(14) 上穿 30。情绪极度超卖后拐头，均值回归思路。常对应阶段性反弹起点。", warn: "均值回归思路，适合震荡市；趋势市信号少。配套：与辅买共振时较强。" },
  { sig: "buy_aux", color: "#d63384", name: "辅买 · 下轨拐点", desc: "布林带下轨回归。价格跌穿 BB 下轨后回归，偏左侧布局。", warn: "左侧布局偏激进。配套：配合主买共振时较强；单独出现风险高。" },
  { sig: "buy_special", color: "#ffd700", name: "追买 · 上轨突破", desc: "唐奇安 20 日上轨突破 + 5 日确认。趋势跟随思路，突破后惯性上行。", backtest: "🔬 回测持有期建议（全史统计）：5d 胜率59.65%/均值+0.87%/回撤2.65%；10d 60.24%/+1.66%/4.26%（风险调整最优）；30d 59.06%/+3.44%（分水岭，风险/收益拐点）；90d 60.83%/+9.42%/回撤16.53%（纯收益最优，但回撤大）。", warn: "趋势跟随追高信号。配套：需配合量能确认，假突破风险；必须配追止损|卖(ATR×3.5止损)控制风险，0套牢。" },
  { sig: "buy_special_filtered", color: "#9e9e9e", name: "追买(过滤预览) · h5灰pin", desc: "命中 h5 平衡档过滤条件（ATR(14)/close>0.03 OR 量价背离）的追买信号，灰色 pin 标记展示不删除。预览模式：用户看后决定是否真过滤，未来直接 drop 即可。", backtest: "🔬 h5 过滤回测（/tmp/peak_filter_combos.py）：过滤率 ~29%，过滤后 10d 均 +1.66->+1.84、套牢 12.83->11.77；核心反直觉：套牢来自高波动假突破而非顶部追买，传统顶部过滤（偏离/RSI/距前高）误杀 49-81%。", warn: "灰色 pin = 会被过滤的追买信号（预览模式，暂不删除）。用户观察后决定是否真过滤。" },
  { sig: "buy_backup", color: "#9c27b0", name: "备买 · 趋势转向", desc: "Supertrend ATR×3 翻多 + 3 日二次确认。趋势反转确认。", warn: "稳健性弱于追买。配套：仅供参考不单独决策，需结合主买/辅买/追买；诱多风险已用3日二次确认过滤。" },
  { sig: "sell", color: "#2e8b57", name: "卖 · 趋势转弱", desc: "MA60 多头 + MACD 死叉 + 20 日高回落 5%。止盈减仓提示。", note: "📌 pin 标签「盈亏X%」来源：sell 信号 reason 中「vs前买+X%」的单次配对实现涨幅（该卖点 vs 前一个买点的实际涨跌），非统计期望值；hover tooltip 的「盈亏比Y」才是历史统计值，二者勿混。" , warn: "止盈减仓非反向信号。配套：走弱概率≈50%接近随机；与追止损|卖共振时减仓信号更强。" },
  { sig: "sell_stop_loss", color: "#3498db", name: "追止损|卖 · ATR×3.5止损", desc: "ATR×3.5 止损（底层规则从 Donchian20 下轨改为 ATR×3，2026-07-21 调 ATR×3.5 降频，趋势跟踪风控）。趋势反转下行最后防线。", backtest: "🔬 回测对比（全史）：现 ATR×3 胜率46.91%/均值+1.76%/盈亏比1.82，全维度略优原 Don20(胜率44.33%/均值+1.56%，2008股灾-10.5%最差)。ATR×3=趋势跟踪策略（低胜率靠大盈拉均值），区别于固定持有的均值回归（高胜率小赚）。⚠️ 2026-07-21 调 ATR×3.5 降频后（hs300 触发 -18%/5d win 49.58%->50.23%），backtest 旧 ATR×3 数据保留作历史对比，新参数 stats 见下方 forward 字段。", warn: "最后防线跌破即止损。配套：趋势跟踪风控（低胜率大盈）；与卖共振减仓信号更强；蓝色与卖绿色区分。" },
  { sig: "band_hold", color: "#ff9800", name: "波段持有 · 国债波段仓管", desc: "国债三品种波段仓位管理策略持有状态（2026-07-24）。RSI+乖离+布林三指标无超买超卖信号，维持当前仓位。替代原 D1 卖点对国债完全失效（sell=0 无理由）的问题。", backtest: "🔬 回测依据 /tmp/backtest_cgb_band.py + /tmp/cgb_band_results.json：cgb_idx 降风险(回撤-10.4%->-4.8%,夏普2.80->3.58)；cgb_10y_etf 放宽双赢(夏普1.31->1.52)；cgb_10y_future 双赢(年化1.30%->1.63%,夏普0.42->1.58)。", warn: "国债专属动态仓位管理（非静态 sell，非清仓卖点）。四动作联动：减仓(sell绿,触超买减20-30%)/接回(buy_aux粉紫,超卖回归接回)/止损(sell_stop_loss蓝,趋势破位清仓)/持有(band_hold橙,无超买超卖维持仓位)。走势图 pin = 历史调仓时点回放，hover 信号日看仓位变化进度条，可缩放查看过去减仓/接回/止损时点。研究参考，不构成投资建议。" },
];

// 聚合 signal_stats.json（per-index）-> per-sig 概况（5d/10d/20d 三窗口，按样本数 n 加权平均）
// signal_stats.json 结构: {_updated_at, bj50:{buy:{10d:{win_rate,pl,mean,n},5d,20d,frequency},...}, sz:{...}}
// 无 max_drawdown 字段（signal_stats.py 仅算 win_rate/pl/mean/n/frequency，未算最大回撤）
// 返回 {sig: {5d:{win_rate,pl,mean,n}, 10d:{...}, 20d:{...}}} 或 null
function _aggregateSignalStats(raw) {
  if (!raw || typeof raw !== "object") return null;
  const SIGS = ["buy", "buy_aux", "buy_special", "buy_special_filtered", "buy_backup", "sell", "sell_stop_loss", "band_hold"];
  const WINDOWS = ["5d", "10d", "20d"];
  const agg = {};
  for (const sig of SIGS) {
    const sigAgg = {};
    let freqTotal = 0;  // 全品种 frequency.total_count 求和（已生成总例数，窗口未到也计数）
    for (const win of WINDOWS) {
      let totN = 0, sumWr = 0, sumPl = 0, sumMean = 0;
      for (const [idx, sigs] of Object.entries(raw)) {
        if (idx.startsWith("_")) continue;  // 跳过 _updated_at 等元字段
        const s = sigs && sigs[sig];
        if (!s) continue;
        // 聚合 frequency.total_count（每品种每信号只计一次，用 5d 轮次做去重开关）
        if (win === "5d" && s.frequency && s.frequency.total_count) {
          freqTotal += s.frequency.total_count;
        }
        if (!s[win]) continue;
        const d = s[win];
        const n = d.n || 0;
        if (n > 0) {
          totN += n;
          sumWr += (d.win_rate || 0) * n;
          sumPl += (d.pl || 0) * n;
          sumMean += (d.mean || 0) * n;
        }
      }
      sigAgg[win] = totN > 0
        ? { win_rate: sumWr / totN, pl: sumPl / totN, mean: sumMean / totN, n: totN }
        : null;
    }
    sigAgg.frequency_total = freqTotal;
    // 至少有一个窗口有数据，或有 frequency_total（已生成N例但窗口未到）才保留；否则 null
    agg[sig] = (sigAgg["5d"] || sigAgg["10d"] || sigAgg["20d"] || freqTotal > 0) ? sigAgg : null;
  }
  return agg;
}

// 渲染6色信号 modal（每信号三段：逻辑描述 + 分析概况[动态] + 配套警示）
// aggStats: _aggregateSignalStats 返回值；null/某信号无数据 -> "数据待补"
function _signalHelpModalHTML(aggStats) {
  const items = _SIGNAL_HELP_ITEMS.map((it) => {
    const s = aggStats && aggStats[it.sig];
    let statHtml;
    if (s) {
      // 三窗口对比行（5d/10d/20d），按样本数 n 加权聚合；某窗口无数据显示 "—"
      const hasWin = !!(s["5d"] || s["10d"] || s["20d"]);
      const freqTotal = s.frequency_total || 0;
      const winRows = [["5日", s["5d"]], ["10日", s["10d"]], ["20日", s["20d"]]].map(([label, w]) => {
        if (!w) return '<div style="margin-left:8px"><span style="display:inline-block;width:3em">' + label + '：</span><span style="opacity:0.5">— 累积中</span></div>';
        return '<div style="margin-left:8px"><span style="display:inline-block;width:3em">' + label + '：</span>胜率 <b>' + (w.win_rate * 100).toFixed(0) + '%</b> · 盈亏比 <b>' + w.pl.toFixed(2) + '</b> · 均收益 <b>' + w.mean.toFixed(2) + '%</b> · 样本 <b>' + w.n + '</b></div>';
      }).join("");
      // 无窗口数据但有 frequency(刚上线窗口未到) -> "已生成N例,窗口统计累积中"; 有窗口数据 -> 附"累计N例"
      const freqNote = (!hasWin && freqTotal > 0)
        ? '<div style="margin-top:3px;color:#ff9800">⏳ 已生成 <b>' + freqTotal + '</b> 例，窗口统计(5d/10d/20d)待未来交易日到位后累积</div>'
        : (freqTotal > 0 ? '<div style="margin-top:2px;opacity:0.6;font-size:11px">累计已生成 ' + freqTotal + ' 例</div>' : '');
      statHtml = '<div style="font-size:12px;line-height:1.6;margin:4px 0;padding:4px 8px;background:rgba(127,127,127,0.1);border-radius:4px">📈 <b>分析概况</b>（全品种加权·按样本数加权）：<div style="margin-top:2px">' + winRows + '</div>' + freqNote + '</div>';
    } else {
      statHtml = '<div style="font-size:12px;line-height:1.5;margin:4px 0;padding:4px 8px;background:rgba(127,127,127,0.1);border-radius:4px;color:#ff9800">📈 分析概况：数据待补（signal_stats 未含此信号统计）</div>';
    }
    // 回测结论（backtest）：全史统计的持有期建议/止损方案对比，淡金色框区分于动态分析概况
    const backtestHtml = it.backtest
      ? '<div style="font-size:12px;line-height:1.55;margin:4px 0;padding:5px 8px;background:rgba(255,215,0,0.12);border-left:3px solid #ffd700;border-radius:4px">' + it.backtest + '</div>'
      : '';
    // 补充说明（note）：pin 标签来源/术语澄清等，淡灰框
    const noteHtml = it.note
      ? '<div style="font-size:12px;line-height:1.55;margin:4px 0;padding:5px 8px;background:rgba(127,127,127,0.08);border-left:3px solid #888;border-radius:4px">' + it.note + '</div>'
      : '';
    return '<div style="display:flex;gap:10px;padding:10px 0;border-bottom:1px solid rgba(127,127,127,0.18)">' +
      '<span style="flex:0 0 14px;width:14px;height:14px;border-radius:50%;margin-top:4px;background:' + it.color + '"></span>' +
      '<div style="flex:1;min-width:0">' +
      '<div style="font-weight:600;margin-bottom:2px">' + it.name + '</div>' +
      '<div style="font-size:13px;line-height:1.55;opacity:0.85">' + it.desc + '</div>' +
      backtestHtml +
      statHtml +
      noteHtml +
      '<div style="font-size:12px;line-height:1.55;opacity:0.7;margin-top:3px">⚠ ' + it.warn + '</div>' +
      '</div></div>';
  }).join("");
  return '<div class="rule-modal-overlay"></div><div class="rule-modal-body"><div class="rule-modal-header"><h3>📊 6色技术信号参考</h3><button class="rule-modal-close" aria-label="关闭">&times;</button></div><div class="rule-modal-content"><div style="padding:0 4px">' + items + '</div><div style="margin-top:12px;padding:8px 12px;font-size:12px;opacity:0.7;background:rgba(127,127,127,0.1);border-radius:6px">⚠ 以上为研究标注非交易指令，详见右下角浮动 📋 策略说明。过往表现不代表未来收益。</div></div></div>';
}

// 打开6色信号 modal：异步 fetch signal_stats.json 聚合后渲染（每次打开重新渲染含最新统计）
// signal_stats.json 已导出到 static-site/data/（export.py 生成，110品种×6信号×5d/10d/20d 三窗口）
// fetchJSON 缓存5分钟；若 fetch 失败(404/解析错误) -> aggStats=null -> 降级"数据待补"
async function _openSignalHelpModal() {
  let aggStats = null;
  try {
    const raw = await fetchJSON("./data/signal_stats.json");
    aggStats = _aggregateSignalStats(raw);
  } catch (e) { /* signal_stats.json 未导出(404)/解析失败 -> aggStats=null -> 显示"数据待补" */ }
  let modal = document.getElementById("signalHelpModal");
  const isFirst = !modal;
  if (isFirst) {
    modal = document.createElement("div");
    modal.id = "signalHelpModal";
    modal.className = "rule-modal hidden";
    document.body.appendChild(modal);
  }
  modal.innerHTML = _signalHelpModalHTML(aggStats);  // 每次重新渲染（含最新统计数据）
  const _close = () => { modal.classList.add("hidden"); document.body.style.overflow = ""; };
  modal.querySelector(".rule-modal-overlay").addEventListener("click", _close);
  modal.querySelector(".rule-modal-close").addEventListener("click", _close);
  if (isFirst) {
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !modal.classList.contains("hidden")) _close(); });
  }
  modal.classList.remove("hidden");
  document.body.style.overflow = "hidden";
}
// click 委托：[data-signal-help] 弹窗（capture 先于 termTip 移动端 pop click，stopPropagation 防双弹）
(function _initSignalHelpDelegation() {
  document.addEventListener("click", (e) => {
    const el = e.target.closest("[data-signal-help]");
    if (!el) return;
    e.preventDefault();
    e.stopPropagation();
    _openSignalHelpModal();
  }, true);
})();
// 标题旁 ❓ hover pop + click 弹窗（技术分析参考点卡片标题用，与 termTip 区别：多了 click 弹窗）
function signalHelpTip(tipText) {
  return ` <span class="term-tip" data-tip="${tipText}" data-signal-help="1">❓</span>`;
}

// sell_stop_loss 统计行蓝色样式（内联注入，不改 CSS 文件；与 .hint-sig.sell 绿色区分）
// 选择器限定 .chart-hint 与现有 .hint-sig.sell 同层级（freq-popup 在 .chart-hint 内也命中）
(function _injectSellStopLossStyle() {
  const style = document.createElement("style");
  style.textContent = ".chart-hint .hint-sig.sell-stop-loss { background: #3498db; color: #fff; }";
  style.textContent += ".chart-hint .hint-sig.band-hold { background: #ff9800; color: #fff; }";  // 波段持有 橙（国债波段仓管，2026-07-24）
  document.head.appendChild(style);
})();

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

// 每个品类的买卖点策略公式标注。后端注入 idx.strategy 字段（{buy,buy_aux,sell,_detail}），
// 由 app/compute/signals.py::strategy_desc 读 indicators.yaml 的 buy_filter/buy_aux_filter/
// sell_no_trend_filter + SKIP_IDS/s.* 前缀逻辑生成。无 strategy 字段时用基线兜底（兼容旧数据/未注入端点）。
// 顶层 buy/buy_aux/sell 字符串向后兼容（export.py/main.py/app.js 现有调用读字符串不破坏）。
// _detail 子对象含 6 类信号完整描述（buy/buy_aux/buy_special/buy_backup/sell/sell_stop_loss），
// 每字段 {desc, params, filter, enabled}，供标题❓ click 弹 modal 展开该指数策略组合。
// 基线：C1 RSI上穿30 + B1 BB下轨回归 + D1 20日高回落5%+MA60+MACD死叉。
function strategyDesc(strategy) {
  if (strategy) return strategy;
  return {
    buy: "RSI(14)上穿30",
    buy_aux: "BB下轨回归",
    sell: "20日高回落5%+MA60多头+MACD死叉",
  };
}

// === 标题❓策略弹窗（方案 B1 紧凑版，2026-07-20）===
// 6 类信号顺序 + 颜色圆点 + 名称（与 _SIGNAL_HELP_ITEMS 一致，便于用户对齐 6 色信号图例）
var _STRATEGY_DETAIL_KEYS = [
  { key: "buy", color: "#e6492e", name: "主买 · 超卖拐点" },
  { key: "buy_aux", color: "#d63384", name: "辅买 · 下轨拐点" },
  { key: "buy_special", color: "#ffd700", name: "追买 · 上轨突破" },
  { key: "buy_backup", color: "#9c27b0", name: "备买 · 趋势转向" },
  { key: "sell", color: "#2e8b57", name: "卖 · 趋势转弱" },
  { key: "sell_stop_loss", color: "#3498db", name: "追止损|卖 · ATR止损" },
  { key: "band_hold", color: "#ff9800", name: "波段持有 · 国债波段仓管" },
];
// 渲染策略 modal：6 行（颜色圆点+信号名+该指数策略描述+参数+过滤），skip 标灰删除线，末尾合规声明。
// strategy._detail 6 字段，每字段 {desc, params, filter, enabled}。
function _strategyModalHTML(strategy, indexId) {
  var detail = strategy && strategy._detail;
  var rows = [];
  for (var i = 0; i < _STRATEGY_DETAIL_KEYS.length; i++) {
    var k = _STRATEGY_DETAIL_KEYS[i];
    var d = detail && detail[k.key];
    if (!d) continue;
    var enabled = d.enabled !== false;
    var rowStyle = enabled
      ? ""
      : "opacity:0.5;text-decoration:line-through;";
    var paramHtml = (d.params && d.params !== "-")
      ? '<div style="font-size:12px;line-height:1.55;margin:3px 0;padding:4px 8px;background:rgba(127,127,127,0.08);border-radius:4px">⚙ 参数：<b>' + d.params + '</b></div>'
      : "";
    var filterHtml = (d.filter && d.filter !== "-")
      ? '<div style="font-size:12px;line-height:1.55;margin:3px 0;padding:4px 8px;background:rgba(127,127,127,0.08);border-radius:4px">🔍 过滤：<b>' + d.filter + '</b></div>'
      : "";
    rows.push(
      '<div style="display:flex;gap:10px;padding:10px 0;border-bottom:1px solid rgba(127,127,127,0.18);' + rowStyle + '">' +
      '<span style="flex:0 0 14px;width:14px;height:14px;border-radius:50%;margin-top:4px;background:' + k.color + '"></span>' +
      '<div style="flex:1;min-width:0">' +
      '<div style="font-weight:600;margin-bottom:2px">' + k.name + '</div>' +
      '<div style="font-size:13px;line-height:1.55;opacity:0.85">' + d.desc + '</div>' +
      paramHtml +
      filterHtml +
      (enabled ? '' : '<div style="font-size:12px;color:#ff9800;margin-top:3px">⚠ 此信号在该指数已 skip（不触发）</div>') +
      '</div></div>'
    );
  }
  var rowsHtml = rows.join("") || '<div style="padding:16px 0;opacity:0.6">该指数暂无策略详情数据。</div>';
  return '<div class="rule-modal-overlay"></div>' +
    '<div class="rule-modal-body"><div class="rule-modal-header">' +
    '<h3>📋 本指数策略详情' + (indexId ? ' · ' + indexId : '') + '</h3>' +
    '<button class="rule-modal-close" aria-label="关闭">&times;</button></div>' +
    '<div class="rule-modal-content"><div style="padding:0 4px">' + rowsHtml +
    '<div style="margin-top:12px;padding:8px 12px;font-size:12px;opacity:0.7;background:rgba(127,127,127,0.1);border-radius:6px">⚠ 以上为研究标注非交易指令，过往表现不代表未来收益。详见右下角浮动 📋 策略说明与 6 色信号参考 ❓。</div>' +
    '</div></div></div></div>';
}
// 打开策略 modal：从 statsHint 闭包/全局 strategyDesc 兜底取 strat，渲染 modal 并绑定关闭事件。
function _openStrategyModal(indexId, strategy) {
  var strat = strategyDesc(strategy);
  var modal = document.getElementById("strategyHelpModal");
  var isFirst = !modal;
  if (isFirst) {
    modal = document.createElement("div");
    modal.id = "strategyHelpModal";
    modal.className = "rule-modal hidden";
    document.body.appendChild(modal);
  }
  modal.innerHTML = _strategyModalHTML(strat, indexId);
  var _close = function () { modal.classList.add("hidden"); document.body.style.overflow = ""; };
  modal.querySelector(".rule-modal-overlay").addEventListener("click", _close);
  modal.querySelector(".rule-modal-close").addEventListener("click", _close);
  if (isFirst) {
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && !modal.classList.contains("hidden")) _close();
    });
  }
  modal.classList.remove("hidden");
  document.body.style.overflow = "hidden";
}
// click 委托 [data-strategy-help] -> 弹该指数策略 modal（capture 先于 termTip 移动端 pop，stopPropagation 防双弹）
(function _initStrategyHelpDelegation() {
  document.addEventListener("click", function (e) {
    var el = e.target.closest("[data-strategy-help]");
    if (!el) return;
    e.preventDefault();
    e.stopPropagation();
    var idx = el.getAttribute("data-index-id") || "";
    var strat = el.__strategy || null;
    _openStrategyModal(idx, strat);
  }, true);
})();
// 在卡片 h3 末尾追加❓（hover pop 一句话摘要 + click 弹该指数策略 modal）。
// cardEl: chart-card DOM；indexId: 该指数 id；strategy: 后端注入的 idx.strategy dict。
// 仿 _appendBackupChipRow 通过 cardEl.querySelector("h3") 注入子元素的先例（不碰 markPoint/chip 区域）。
function _appendStrategyHint(cardEl, indexId, strategy) {
  if (!cardEl) return;
  var h3 = cardEl.querySelector("h3");
  // 2026-07-20 板分化适配：行业网格卡无 h3，走 spark-name 路径（❓+按钮入 spark-name 内，与指数表现 h3 一行布局一致）
  var sparkName = !h3 ? cardEl.querySelector(".spark-name") : null;
  var target = h3 || sparkName;
  if (!target) return;
  // 避免重复注入
  if (target.querySelector("[data-strategy-help]")) return;
  var strat = strategyDesc(strategy);
  // hover pop 一句话摘要：本指数6类策略组合（buy/buy_aux/buy_special/buy_backup/sell/sell_stop_loss）
  var tipLines = ["本指数策略组合："];
  var detail = strat && strat._detail;
  for (var i = 0; i < _STRATEGY_DETAIL_KEYS.length; i++) {
    var k = _STRATEGY_DETAIL_KEYS[i];
    var d = detail && detail[k.key];
    if (!d) continue;
    var name = k.name.split(" · ")[0];
    var en = d.enabled !== false;
    // 2026-07-24 hoverpop 专属规则修复：hover 摘要原本只读 d.desc，sh/sz 一样；
    // 追加 d.filter 末段 per-index 部分（sh 专属 / 非 sh 方案B），让 hover 显差异（click modal 仍读完整 d.filter）。
    // 正则 /专属|非 sh/ 排除 buy/buy_aux 基线备注"无 per-index 配置"（含字面 per-index 字串会误匹配）。
    var filt = d.filter || "";
    var seg = filt.split("；").filter(function (s) { return /专属|非 sh/.test(s); }).slice(-1)[0] || "";
    tipLines.push(name + "：" + (en ? d.desc : "skip") + (seg ? "【" + seg + "】" : ""));
  }
  tipLines.push("点击展开完整参数与过滤条件。");
  var tipText = tipLines.join("\n").replace(/"/g, "&quot;");
  var span = document.createElement("span");
  span.className = "term-tip";
  span.setAttribute("data-tip", tipText);
  span.setAttribute("data-strategy-help", "1");
  span.setAttribute("data-index-id", indexId || "");
  span.setAttribute("aria-label", "本指数策略详情");
  span.textContent = "❓";
  span.style.cursor = "help";
  span.__strategy = strat;  // click 委托时取回
  // 若 target 已有 sim-btn-wrap（_prependSimBtn 先于本函数调用），把❓插到 sim-btn 前，保证 [❓][模拟回测] 顺序
  var simWrap = target.querySelector(".sim-btn-wrap");
  if (simWrap) target.insertBefore(span, simWrap);
  else target.appendChild(span);
}

// === A5 真 pin 复盘（2026-07-24）===
// pin = 用户钉住某指数，钉住后在指数区顶部显示该指数专属详细复盘面板。
// 持久化：localStorage["pinned_indices"] = JSON.stringify(["sh","sz300",...])，跨刷新保留。
// 事件：togglePin 后 dispatch "pin-changed" CustomEvent，renderIndicesSection 监听后刷新复盘面板。
// 复盘面板内容：历史走势摘要(近5/20/60日涨跌+波动)/信号状态(最近信号)/关键统计(6类信号10d胜率盈亏比)/专属规则(per-index)。
var _PIN_INDICES_LS_KEY = "pinned_indices";
function _getPinnedIds() {
  try { return JSON.parse(localStorage.getItem(_PIN_INDICES_LS_KEY) || "[]"); } catch (e) { return []; }
}
function _setPinnedIds(arr) {
  try { localStorage.setItem(_PIN_INDICES_LS_KEY, JSON.stringify(arr || [])); } catch (e) {}
  document.dispatchEvent(new CustomEvent("pin-changed", { detail: { ids: arr || [] } }));
}
function _isPinned(id) { return _getPinnedIds().indexOf(id) >= 0; }
function _togglePin(id) {
  var ids = _getPinnedIds();
  var i = ids.indexOf(id);
  if (i >= 0) ids.splice(i, 1); else ids.push(id);
  _setPinnedIds(ids);
  return i < 0;  // 返回新状态（true=已 pin）
}
// 全局缓存：renderOne 时写入 {id: {idx, sig}}，pin 按钮点击时立即从缓存渲染复盘卡片（避免异步等待）
var _pinDataCache = {};

// 在 chart-card h3 末尾追加 📌 按钮（pin 切换）；h3 不存在时退到 spark-name。
// 与❓/sim-btn 同行排列，放最末尾（[标题][❓][模拟回测][📌]）。
function _appendPinBtn(cardEl, indexId, idx, sig) {
  if (!cardEl || !indexId) return;
  var h3 = cardEl.querySelector("h3");
  var sparkName = !h3 ? cardEl.querySelector(".spark-name") : null;
  var target = h3 || sparkName;
  if (!target) return;
  if (target.querySelector(".pin-btn")) return;  // 避免重复注入
  // 缓存数据供复盘面板用
  if (idx) _pinDataCache[indexId] = { idx: idx, sig: sig || _pinDataCache[indexId] && _pinDataCache[indexId].sig || null };
  else if (_pinDataCache[indexId] && _pinDataCache[indexId].sig && sig) _pinDataCache[indexId].sig = sig;
  var btn = document.createElement("span");
  btn.className = "pin-btn" + (_isPinned(indexId) ? " active" : "");
  btn.setAttribute("data-pin-id", indexId);
  btn.setAttribute("role", "button");
  btn.setAttribute("aria-label", _isPinned(indexId) ? "取消钉住" : "钉住指数");
  btn.setAttribute("title", _isPinned(indexId) ? "已钉住，点击取消" : "钉住该指数，顶部显示专属复盘");
  btn.textContent = "📌";
  btn.addEventListener("click", function (e) {
    e.preventDefault();
    e.stopPropagation();
    var newPinned = _togglePin(indexId);
    btn.classList.toggle("active", newPinned);
    btn.setAttribute("aria-label", newPinned ? "取消钉住" : "钉住指数");
    btn.setAttribute("title", newPinned ? "已钉住，点击取消" : "钉住该指数，顶部显示专属复盘");
  });
  target.appendChild(btn);
}

// ============ A12 订阅推送（2026-07-24 P2-新-K）============
// 用户订阅关注的标的（指数/ETF），有信号时推送邮件+Telegram。
// 后端：config/subscriptions.json 存订阅（已 gitignore），scripts/check_signals.py 检测信号后匹配推送。
// 前端：指数卡片 h3 末尾 🔔 按钮，点击弹订阅管理 modal（填邮箱/chat_id + 选标的 + 选信号 + 已订阅列表）。
// localStorage：存用户邮箱/chat_id 免重复输入（key: sub_user_info）。
var _SUB_USER_INFO_LS_KEY = "sub_user_info";
var _SUB_SIGNAL_LABELS = [
  { key: "buy", label: "主买", color: "#e6492e" },
  { key: "buy_aux", label: "辅买", color: "#d63384" },
  { key: "buy_special", label: "追买", color: "#ffd700" },
  { key: "buy_backup", label: "备买", color: "#9c27b0" },
  { key: "sell", label: "卖", color: "#2e8b57" },
  { key: "sell_stop_loss", label: "追止损卖", color: "#3498db" },
];

function _loadSubUserInfo() {
  try { return JSON.parse(localStorage.getItem(_SUB_USER_INFO_LS_KEY) || "{}"); } catch (e) { return {}; }
}
function _saveSubUserInfo(info) {
  try { localStorage.setItem(_SUB_USER_INFO_LS_KEY, JSON.stringify(info || {})); } catch (e) {}
}

function _appendSubscribeBtn(cardEl, indexId, indexName) {
  if (!cardEl || !indexId) return;
  var h3 = cardEl.querySelector("h3");
  var sparkName = !h3 ? cardEl.querySelector(".spark-name") : null;
  var target = h3 || sparkName;
  if (!target) return;
  if (target.querySelector(".subscribe-btn")) return;  // 避免重复注入
  var btn = document.createElement("span");
  btn.className = "subscribe-btn";
  btn.setAttribute("role", "button");
  btn.setAttribute("aria-label", "订阅该指数信号");
  btn.setAttribute("title", "订阅该指数信号（有买卖点时推送邮件/Telegram）");
  btn.textContent = "🔔";
  btn.addEventListener("click", function (e) {
    e.preventDefault();
    e.stopPropagation();
    _openSubscribeModal(indexId, indexName);
  });
  target.appendChild(btn);
}

function _subscribeModalEl() {
  var modal = document.getElementById("subscribe-modal");
  if (!modal) {
    modal = document.createElement("div");
    modal.id = "subscribe-modal";
    modal.className = "rule-modal subscribe-modal hidden";
    document.body.appendChild(modal);
  }
  return modal;
}

function _openSubscribeModal(indexId, indexName) {
  var modal = _subscribeModalEl();
  var userInfo = _loadSubUserInfo();
  var defaultEmail = userInfo.email || "";
  var defaultChatId = userInfo.telegram_chat_id || "";
  // 信号类型 checkbox（默认全选）
  var sigCheckboxes = _SUB_SIGNAL_LABELS.map(function (s) {
    return '<label class="sub-sig-check"><input type="checkbox" value="' + s.key + '" checked>'
      + '<span class="hint-sig" style="background:' + s.color + '">' + s.label + '</span></label>';
  }).join("");
  modal.innerHTML =
    '<div class="rule-modal-overlay"></div>' +
    '<div class="rule-modal-body subscribe-modal-body">' +
      '<div class="rule-modal-header"><h3>🔔 信号订阅' + (indexName ? ' · ' + indexName : '') + '</h3>' +
        '<button class="rule-modal-close" aria-label="关闭">&times;</button></div>' +
      '<div class="rule-modal-content">' +
        '<div class="sub-form-section">' +
          '<div class="sub-form-row"><label>订阅名称（可选）</label><input id="sub-name" type="text" placeholder="如：我的宽基订阅" maxlength="40"></div>' +
          '<div class="sub-form-row"><label>邮箱（可选）</label><input id="sub-email" type="email" placeholder="your@example.com" value="' + defaultEmail + '"></div>' +
          '<div class="sub-form-row"><label>Telegram chat_id（可选）</label><input id="sub-chatid" type="text" placeholder="数字 id 或 @channelname" value="' + defaultChatId + '"></div>' +
          '<div class="sub-form-row sub-form-row-top"><label>订阅标的（index_id，逗号分隔）</label>' +
            '<input id="sub-targets" type="text" placeholder="如：sh,sz300,cyb" value="' + (indexId || "") + '"></div>' +
          '<div class="sub-form-row sub-form-row-top"><label>订阅信号类型（不选=全部）</label>' +
            '<div class="sub-sig-checkboxes">' + sigCheckboxes + '</div></div>' +
          '<div class="sub-form-actions">' +
            '<button id="sub-save-btn" class="sub-save-btn">保存订阅</button>' +
            '<span id="sub-msg" class="sub-msg"></span>' +
          '</div>' +
        '</div>' +
        '<div class="sub-list-section">' +
          '<div class="sub-list-title">📋 已订阅列表</div>' +
          '<div id="sub-list" class="sub-list"><div class="sub-list-loading">加载中...</div></div>' +
        '</div>' +
        '<div class="sub-disclaimer">⚠ 订阅后，check_signals 检测到匹配信号时会推送邮件/Telegram。每订阅每日每信号只推一次（去重）。历史回测信号仅供研究参考，非投资建议。</div>' +
      '</div>' +
    '</div>';
  modal.classList.remove("hidden");
  document.body.style.overflow = "hidden";
  // 关闭事件
  var _close = function () { modal.classList.add("hidden"); document.body.style.overflow = ""; };
  modal.querySelector(".rule-modal-overlay").addEventListener("click", _close);
  modal.querySelector(".rule-modal-close").addEventListener("click", _close);
  // 保存按钮
  modal.querySelector("#sub-save-btn").addEventListener("click", function () {
    _saveSubscriptionFromModal(indexId);
  });
  // 加载已订阅列表
  _renderSubscriptionsList();
}

function _saveSubscriptionFromModal(currentIndexId) {
  var name = (document.getElementById("sub-name").value || "").trim();
  var email = (document.getElementById("sub-email").value || "").trim();
  var chatId = (document.getElementById("sub-chatid").value || "").trim();
  var targetsRaw = (document.getElementById("sub-targets").value || "").trim();
  var msgEl = document.getElementById("sub-msg");
  // 解析 targets（逗号分隔，去空格去重）
  var targets = targetsRaw.split(",").map(function (s) { return s.trim(); }).filter(function (s) { return s; });
  targets = Array.from(new Set(targets));
  // 解析选中的信号类型
  var signals = [];
  var checkboxes = document.querySelectorAll("#subscribe-modal .sub-sig-check input:checked");
  checkboxes.forEach(function (cb) { signals.push(cb.value); });
  // 校验
  if (!targets.length) { _setSubMsg("请填写订阅标的", true); return; }
  if (!email && !chatId) { _setSubMsg("邮箱和 Telegram chat_id 至少填一个", true); return; }
  // 存 localStorage 免重复输入
  _saveSubUserInfo({ email: email, telegram_chat_id: chatId });
  var payload = { id: "", name: name, email: email, telegram_chat_id: chatId, targets: targets, signals: signals, enabled: true };
  _setSubMsg("保存中...", false);
  fetch("/api/subscribe", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  }).then(function (r) { return r.json(); }).then(function (data) {
    if (data.ok) {
      _setSubMsg("✓ 订阅已保存（" + (data.action === "created" ? "新建" : "更新") + "）", false);
      _renderSubscriptionsList();  // 刷新列表
    } else {
      _setSubMsg("✗ 保存失败：" + (data.detail || "未知错误"), true);
    }
  }).catch(function (err) {
    _setSubMsg("✗ 网络错误：" + err.message, true);
  });
}

function _setSubMsg(msg, isError) {
  var el = document.getElementById("sub-msg");
  if (!el) return;
  el.textContent = msg;
  el.className = "sub-msg" + (isError ? " error" : " success");
}

function _renderSubscriptionsList() {
  var listEl = document.getElementById("sub-list");
  if (!listEl) return;
  listEl.innerHTML = '<div class="sub-list-loading">加载中...</div>';
  fetch("/api/subscribe").then(function (r) { return r.json(); }).then(function (data) {
    var subs = data.subscriptions || [];
    if (!subs.length) {
      listEl.innerHTML = '<div class="sub-list-empty">暂无订阅。在上方填写信息后点"保存订阅"创建。</div>';
      return;
    }
    listEl.innerHTML = subs.map(function (s) {
      var channels = [];
      if (s.has_email) channels.push('📧 ' + (s.email_masked || '邮箱'));
      if (s.has_telegram) channels.push('💬 ' + (s.telegram_chat_id_masked || 'TG'));
      var sigsText = s.signals && s.signals.length
        ? s.signals.map(function (sig) {
            var found = _SUB_SIGNAL_LABELS.filter(function (x) { return x.key === sig; })[0];
            return '<span class="hint-sig" style="background:' + (found ? found.color : '#86909c') + '">' + (found ? found.label : sig) + '</span>';
          }).join("")
        : '<span class="sub-sig-all">全部</span>';
      var targetsText = (s.targets || []).join(", ");
      var enabledBadge = s.enabled ? '' : '<span class="sub-disabled-badge">已暂停</span>';
      return '<div class="sub-list-item" data-sub-id="' + s.id + '">' +
        '<div class="sub-item-head">' +
          '<span class="sub-item-name">' + (s.name || s.id) + '</span>' + enabledBadge +
          '<button class="sub-delete-btn" data-sub-id="' + s.id + '" title="删除订阅">✕</button>' +
        '</div>' +
        '<div class="sub-item-row"><span class="sub-item-label">标的：</span>' + targetsText + '</div>' +
        '<div class="sub-item-row"><span class="sub-item-label">信号：</span>' + sigsText + '</div>' +
        '<div class="sub-item-row"><span class="sub-item-label">渠道：</span>' + (channels.join(" · ") || '未配置') + '</div>' +
      '</div>';
    }).join("");
    // 绑定删除按钮
    listEl.querySelectorAll(".sub-delete-btn").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var subId = btn.getAttribute("data-sub-id");
        if (!subId) return;
        if (!confirm("确认删除此订阅？")) return;
        _deleteSubscription(subId);
      });
    });
  }).catch(function (err) {
    listEl.innerHTML = '<div class="sub-list-error">加载失败：' + err.message + '</div>';
  });
}

function _deleteSubscription(subId) {
  fetch("/api/subscribe/" + encodeURIComponent(subId), { method: "DELETE" })
    .then(function (r) { return r.json(); })
    .then(function (data) {
      if (data.ok) {
        _setSubMsg("✓ 订阅已删除", false);
        _renderSubscriptionsList();
      } else {
        _setSubMsg("✗ 删除失败：" + (data.detail || "未知错误"), true);
      }
    }).catch(function (err) {
      _setSubMsg("✗ 网络错误：" + err.message, true);
    });
}

// 计算近 N 日涨跌幅（基于 ohlc close 末值 vs N 日前 close）
function _pctChangeOver(ohlc, n) {
  if (!ohlc || ohlc.length < 2) return null;
  var len = ohlc.length;
  var last = ohlc[len - 1];
  var base = ohlc[len - 1 - n];
  if (!last || !base || last.close == null || base.close == null) return null;
  return (last.close / base.close - 1) * 100;
}
// 计算近 N 日波动率（日收益标准差×sqrt(N)，年化近似）
function _volatilityOver(ohlc, n) {
  if (!ohlc || ohlc.length < n + 1) return null;
  var slice = ohlc.slice(-n - 1);
  var rets = [];
  for (var i = 1; i < slice.length; i++) {
    if (slice[i].close != null && slice[i - 1].close != null && slice[i - 1].close > 0) {
      rets.push(Math.log(slice[i].close / slice[i - 1].close));
    }
  }
  if (rets.length < 2) return null;
  var mean = rets.reduce(function (a, b) { return a + b; }, 0) / rets.length;
  var variance = rets.reduce(function (a, b) { return a + (b - mean) * (b - mean); }, 0) / rets.length;
  return Math.sqrt(variance) * Math.sqrt(n) * 100;  // N 日波动率（%）
}
// 取近 N 日高低点
function _highLowOver(ohlc, n) {
  if (!ohlc || !ohlc.length) return null;
  var slice = ohlc.slice(-Math.min(n, ohlc.length));
  var hi = -Infinity, lo = Infinity;
  for (var i = 0; i < slice.length; i++) {
    if (slice[i].high != null && slice[i].high > hi) hi = slice[i].high;
    if (slice[i].low != null && slice[i].low < lo) lo = slice[i].low;
  }
  if (hi === -Infinity || lo === Infinity) {
    // 退到 close 兜底（valueChart 数据只有 value 无 high/low）
    hi = -Infinity; lo = Infinity;
    for (var j = 0; j < slice.length; j++) {
      var v = slice[j].close != null ? slice[j].close : slice[j].value;
      if (v == null) continue;
      if (v > hi) hi = v;
      if (v < lo) lo = v;
    }
  }
  if (hi === -Infinity || lo === Infinity) return null;
  return { high: hi, low: lo };
}
// 取最近一个信号（按 date 降序找最后一个）
function _latestSignal(signals) {
  if (!signals || !signals.length) return null;
  var latest = null;
  for (var i = 0; i < signals.length; i++) {
    var s = signals[i];
    if (!s || !s.date) continue;
    if (!latest || s.date > latest.date) latest = s;
  }
  return latest;
}
// 6 类信号 stats 简表 HTML（胜率/盈亏比/样本，沿用 statsHint 配色但精简）
function _pinStatsBriefHtml(stats) {
  if (!stats) return '<div class="pin-empty">无统计数据</div>';
  var labels = { buy: "买", buy_aux: "辅买", buy_special: "追买", buy_special_filtered: "追买(过滤)", buy_backup: "备买", sell: "卖", sell_stop_loss: "追止损|卖" , band_hold: "波段持有" };
  var sigClass = { buy: "buy", buy_aux: "buy-aux", buy_special: "buy-special", buy_special_filtered: "buy-special-filtered", buy_backup: "buy-backup", sell: "sell", sell_stop_loss: "sell-stop-loss" , band_hold: "band-hold" };
  var rows = [];
  var order = ["buy", "buy_aux", "buy_special", "buy_backup", "sell", "sell_stop_loss", "band_hold"];
  for (var i = 0; i < order.length; i++) {
    var sig = order[i];
    var s = stats[sig];
    if (!s || !s["10d"]) continue;
    var d = s["10d"];
    var n = d.n || 0;
    if (n < 10) continue;  // 样本不足不显示
    var wr = Math.round((d.win_rate || 0) * 100);
    var pl = d.pl != null ? d.pl.toFixed(2) : "-";
    var wrCls = winRateClass(wr);
    var wrLabel = (sig === "sell" || sig === "sell_stop_loss") ? "走弱" : "胜率";
    rows.push('<span class="pin-stat-item"><span class="hint-sig ' + sigClass[sig] + '">' + labels[sig] + '</span>' +
      '<span class="pin-stat-val">' + wrLabel + ' <b class="wr ' + wrCls + '">' + wr + '%</b></span>' +
      '<span class="pin-stat-val">盈亏比 <b>' + pl + '</b></span>' +
      '<span class="pin-stat-val muted">n=' + n + '</span></span>');
  }
  if (!rows.length) return '<div class="pin-empty">无充足样本统计（所有信号 n&lt;10）</div>';
  return '<div class="pin-stat-grid">' + rows.join("") + '</div>';
}
// 专属规则 HTML：6 类策略 desc + per-index filter（sh 专属 / 非 sh 方案B）
function _pinStrategyHtml(strategy, indexId) {
  var strat = strategyDesc(strategy);
  var detail = strat && strat._detail;
  if (!detail) {
    return '<div class="pin-strat-line">📋 买: ' + (strat.buy || '-') + ' · 辅买: ' + (strat.buy_aux || '-') + ' · 卖: ' + (strat.sell || '-') + '</div>';
  }
  var lines = [];
  for (var i = 0; i < _STRATEGY_DETAIL_KEYS.length; i++) {
    var k = _STRATEGY_DETAIL_KEYS[i];
    var d = detail[k.key];
    if (!d) continue;
    var name = k.name.split(" · ")[0];
    var en = d.enabled !== false;
    if (!en) { lines.push('<div class="pin-strat-line skip"><span class="pin-strat-dot" style="background:' + k.color + '"></span>' + name + '：skip（本指数不启用）</div>'); continue; }
    var filt = d.filter || "";
    var seg = filt.split("；").filter(function (s) { return /专属|非 sh/.test(s); }).slice(-1)[0] || "";
    lines.push('<div class="pin-strat-line"><span class="pin-strat-dot" style="background:' + k.color + '"></span>' + name + '：' + (d.desc || "") + (seg ? '<span class="pin-strat-seg">【' + seg + '】</span>' : '') + '</div>');
  }
  return '<div class="pin-strat-block">' + lines.join("") + '</div>';
}
// 单个 pin 复盘卡片 HTML
function _pinReviewCardHtml(id, idx, sig) {
  var name = idx && idx.name ? idx.name : id;
  var ohlc = (idx && idx.data) || [];
  var last = ohlc.length ? ohlc[ohlc.length - 1] : null;
  var lastClose = last && last.close != null ? last.close : null;
  var lastPct = last && last.pct_change != null ? last.pct_change : null;
  var lastDate = last && last.date ? last.date : "";
  var up = (lastPct || 0) >= 0;
  var pctColor = up ? "#e6492e" : "#2e8b57";
  // 走势摘要
  var pct5 = _pctChangeOver(ohlc, 5);
  var pct20 = _pctChangeOver(ohlc, 20);
  var pct60 = _pctChangeOver(ohlc, 60);
  var vol60 = _volatilityOver(ohlc, 60);
  var hl60 = _highLowOver(ohlc, 60);
  // 信号状态
  var signals = sig && sig.signals ? sig.signals : [];
  var latestSig = _latestSignal(signals);
  var stats = sig && sig.stats ? sig.stats : null;
  var strategy = idx && idx.strategy ? idx.strategy : null;
  // 头部
  var closeHtml = lastClose != null ? '<span class="pin-close">' + (typeof lastClose === "number" ? lastClose.toFixed(2) : lastClose) + '</span>' : "";
  var pctHtml = lastPct != null ? '<span class="pin-pct" style="color:' + pctColor + '">' + (up ? "+" : "") + lastPct.toFixed(2) + '%</span>' : "";
  var dateHtml = lastDate ? '<span class="pin-date">· ' + fmtDate(lastDate) + '</span>' : "";
  // 走势摘要行
  function pctSpan(v, label) {
    if (v == null) return "";
    var cu = v >= 0;
    return '<span class="pin-trend-item">' + label + ' <b style="color:' + (cu ? "#e6492e" : "#2e8b57") + '">' + (cu ? "+" : "") + v.toFixed(2) + '%</b></span>';
  }
  var trendHtml = pctSpan(pct5, "近5日") + pctSpan(pct20, "近20日") + pctSpan(pct60, "近60日");
  if (vol60 != null) trendHtml += '<span class="pin-trend-item">60日波动 <b>' + vol60.toFixed(1) + '%</b></span>';
  if (hl60) {
    var hiStr = typeof hl60.high === "number" ? hl60.high.toFixed(2) : hl60.high;
    var loStr = typeof hl60.low === "number" ? hl60.low.toFixed(2) : hl60.low;
    trendHtml += '<span class="pin-trend-item">60日高 <b>' + hiStr + '</b> / 低 <b>' + loStr + '</b></span>';
  }
  if (!trendHtml) trendHtml = '<div class="pin-empty">无充足走势数据</div>';
  // 信号状态
  var sigHtml = "";
  if (latestSig) {
    var sigColor = signalColor(latestSig);
    var sigLabel = signalLabel(latestSig);
    sigHtml = '<div class="pin-sig-latest"><span class="hint-sig" style="background:' + sigColor + '">' + sigLabel + '</span>' +
      '<span class="pin-sig-date">' + fmtDate(latestSig.date) + '</span>' +
      '<span class="pin-sig-reason">' + (latestSig.reason || "").slice(0, 80) + (latestSig.reason && latestSig.reason.length > 80 ? "…" : "") + '</span></div>';
  } else {
    sigHtml = '<div class="pin-empty">近段无信号触发</div>';
  }
  // 组装
  return '<div class="pin-review-card" data-pin-id="' + id + '">' +
    '<div class="pin-review-head">' +
      '<div class="pin-review-title">' +
        '<span class="pin-review-name">' + name + '</span>' +
        closeHtml + pctHtml + dateHtml +
      '</div>' +
      '<button class="pin-unpin-btn" data-unpin-id="' + id + '" title="取消钉住">✕</button>' +
    '</div>' +
    '<div class="pin-review-section-block">' +
      '<div class="pin-block-label">📈 走势摘要</div>' +
      '<div class="pin-trend-row">' + trendHtml + '</div>' +
    '</div>' +
    '<div class="pin-review-section-block">' +
      '<div class="pin-block-label">🎯 信号状态</div>' +
      sigHtml +
    '</div>' +
    '<div class="pin-review-section-block">' +
      '<div class="pin-block-label">📊 关键统计（10d）</div>' +
      _pinStatsBriefHtml(stats) +
    '</div>' +
    '<div class="pin-review-section-block">' +
      '<div class="pin-block-label">📋 专属规则</div>' +
      _pinStrategyHtml(strategy, id) +
    '</div>' +
    '<div class="pin-disclaimer">⚠ 历史回测统计与数学公式参考，非投资建议；过往表现不代表未来收益。</div>' +
  '</div>';
}

// 模拟回测按钮 HTML（2026-07-23 改动3）：从 statsHint 抽出，由调用方注入为独立 DOM。
// SIM_INDICES 之外的指数返回空串（不渲染按钮）。
function _simBtnHtml(indexId) {
  if (!SIM_INDICES.has(indexId)) return "";
  return `<a href="https://ssd.fx8.store/trade_sim/trade_sim_${SIM_HREF_MAP[indexId] || indexId}.html" class="sim-btn" data-index="${indexId}" title="查看模拟回测详情">📊 模拟回测</a>`;
}
// 把 sim-btn 注入 h3 末尾（标题行内排列，排在❓之后）；h3 不存在时退到 chart-hint 前独立兄弟 DOM。
// 注：_prependSimBtn 通常先于 _appendStrategyHint 调用（indexChart 内），此时 h3 内尚无❓，sim-btn 先追加末尾，
// _appendStrategyHint 后续会把❓ insertBefore 到 sim-btn 前，保证最终顺序 [标题][❓][模拟回测]。
function _prependSimBtn(cardEl, indexId) {
  var html = _simBtnHtml(indexId);
  if (!html) return;
  var wrap = document.createElement("span");
  wrap.className = "sim-btn-wrap";
  wrap.innerHTML = html;
  var h3 = cardEl.querySelector("h3");
  if (h3) {
    // 若❓已存在(data-strategy-help)，插在❓之后；否则追加末尾（❓后续由 _appendStrategyHint 插到 sim-btn 前）
    var tip = h3.querySelector("[data-strategy-help]");
    if (tip) {
      if (tip.nextSibling) h3.insertBefore(wrap, tip.nextSibling);
      else h3.appendChild(wrap);
    } else {
      h3.appendChild(wrap);
    }
  } else {
    // 2026-07-20 板分化适配：网格 spark-head 无 h3，走 spark-name 路径（按钮入 spark-name 内末尾，与指数表现 h3 一行布局一致）
    var sparkName = cardEl.querySelector(".spark-name");
    if (sparkName) {
      sparkName.appendChild(wrap);
    } else {
      // 兜底：spark-name 也不存在时退到 chart-hint 前独立兄弟 DOM
      var hintEl = cardEl.querySelector(".chart-hint");
      if (hintEl) hintEl.before(wrap);
      else cardEl.appendChild(wrap);
    }
  }
}

function statsHint(stats, strategy, indexId) {
  const strat = strategyDesc(strategy);
  const stratHtml = strat ? `<div class="hint-strategy">📋 策略｜买: ${strat.buy} · 辅买: ${strat.buy_aux} · 卖: ${strat.sell}</div>` : "";
  if (!stats) return stratHtml || null;
  const blocks = [];
  const labels = { buy: "买点", buy_aux: "辅买", buy_special: "追买", buy_special_filtered: "追买(过滤预览)", buy_backup: "备买", sell: "卖点", sell_stop_loss: "追止损|卖" , band_hold: "波段持有" };
  const sigClass = { buy: "buy", buy_aux: "buy-aux", buy_special: "buy-special", buy_special_filtered: "buy-special-filtered", buy_backup: "buy-backup", sell: "sell", sell_stop_loss: "sell-stop-loss" , band_hold: "band-hold" };
  for (const sig of ["buy", "buy_aux", "buy_special", "buy_special_filtered", "buy_backup", "sell", "sell_stop_loss", "band_hold"]) {
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
      if (sig === "sell" || sig === "sell_stop_loss") {
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
    const honestTag = (sig === "sell" || sig === "sell_stop_loss")
      ? `<span class="hint-note">止盈减仓提示，非高胜率反向信号</span>`
      : "";
    // 卖点胜率语义是"走弱概率"（卖后 10 日下跌概率），与买点"胜率"语义对称但口径不同
    const wrLabel = (sig === "sell" || sig === "sell_stop_loss") ? "走弱概率" : "胜率";
    blocks.push(`<div class="hint-row"><span class="hint-sig ${cls}">${label}</span><span class="hint-stat">${wrLabel} <b class="wr ${wrCls}">${wr}%</b></span><span class="hint-stat">盈亏比 ${pl}</span><span class="hint-stat">样本 ${n}</span>${kellyHtml}${honestTag}</div>`);
  }
  if (!blocks.length) return stratHtml || null;
  // 频率统计区块
  let freqHtml = "";
  const freqBlocks = [];
  for (const sig of ["buy", "buy_aux", "buy_special", "buy_special_filtered", "buy_backup", "sell", "sell_stop_loss", "band_hold"]) {
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
  // 模拟回测按钮已从 statsHint 移出（2026-07-23 改动3）：原塞在 hint 最前属"策略区块内"，
  // 现由调用方（indexChart / valueChartWithSignals / KPI详情 / 网格）通过 _prependSimBtn
  // 注入 h3 末尾排在❓后（改动4），语义上"真正挪出策略区块"且与❓行内排列。
  return stratHtml + `<div class="hint-header">统计基准：全历史信号 · 信号触发后 10 个交易日收益统计</div>` +
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
  const c = mkCard(title + _suffix, 300, hint, container, chartArr);
  // 模拟回测按钮：注入 h3 末尾排在❓后（标题行内排列，挪出策略区块）
  _prependSimBtn(c.getDom().parentElement, indexId);
  // 信号频率改 hover pop（与行业卡片一致，悬浮成功率行弹频率）
  _bindFreqPopupToHintRows(c.getDom().parentElement, stats);
  const close = ohlc.map((d) => [d.date, d.close]);
  // 4色买点拼色 pin（同日多买点合并1个拼色 pin，参照汪汪队），卖绿独立 pin
  const _ohlcMap = {}; for (const o of ohlc) _ohlcMap[o.date] = o;
  const markData = _buildSignalMarkData(signals, (date) => {
    const o = _ohlcMap[date]; return o ? o.close : null;
  });
  c.setOption(withTheme({
    tooltip: {
      trigger: "axis",
      // P0-3: hover 信号日时追加完整 reason（主标签已在 pin 上，技术细节进 tooltip）
      formatter: function (params) {
        const d = params[0], dt = d.axisValue;
        const o = ohlc.find((x) => x.date === dt);
        let tip = fmtDate(dt);
        if (o && o.close != null) {
          tip += "<br/>收盘 " + o.close.toFixed(2);
          if (o.pct_change != null) tip += ' <span style="color:' + (o.pct_change >= 0 ? "#e6492e" : "#2e8b57") + '">' + (o.pct_change >= 0 ? "+" : "") + o.pct_change.toFixed(2) + "%</span>";
        }
        const marks = markData.filter((m) => m.coord[0] === dt && m.reason);
        for (const m of marks) {
          if (Array.isArray(m.tipColors) && Array.isArray(m.tipLabels)) {
            // 拼色 pin：渲染多色●（如 ●趋势转向+●上轨突破 紫●+金●，方案3 修拼色 tooltip bug）
            const dots = m.tipColors.map((c, i) => '<b style="color:' + c + '">●</b>' + (m.tipLabels[i] || "")).join("+");
            tip += '<br/>' + dots + " " + _fmtReasonWithBand(m.reason);
          } else {
            const mc = typeof m.itemStyle.color === "string" ? m.itemStyle.color : "#ffd700";
            tip += '<br/><b style="color:' + mc + '">● ' + m.value + "</b> " + _fmtReasonWithBand(m.reason);
          }
        }
        return tip;
      }
    },
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
          label: { fontSize: 11, color: cssVar("--text-1") },
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
  const c = mkCard(title, 300, hint, container, chartArr);
  // 模拟回测按钮：注入 h3 末尾排在❓后（与 indexChart 一致，挪出策略区块）
  _prependSimBtn(c.getDom().parentElement, indexId);
  // 信号频率改 hover pop（与行业卡片一致，悬浮成功率行弹频率）
  _bindFreqPopupToHintRows(c.getDom().parentElement, stats);
  // 4色买点拼色 pin（同日多买点合并1个拼色 pin，参照汪汪队），卖绿独立 pin
  const _dataMap = {}; for (const p of data) _dataMap[p.date] = p;
  const markData = _buildSignalMarkData(sigs, (date) => {
    const p = _dataMap[date]; return p ? p.value : null;
  });
  c.setOption(withTheme({
    tooltip: {
      trigger: "axis",
      // P0-3: hover 信号日时追加完整 reason
      formatter: function (params) {
        const d = params[0], dt = d.axisValue;
        const p = data.find((x) => x.date === dt);
        let tip = fmtDate(dt);
        if (p && p.value != null) tip += "<br/>" + Number(p.value).toFixed(2);
        const marks = markData.filter((m) => m.coord[0] === dt && m.reason);
        for (const m of marks) {
          if (Array.isArray(m.tipColors) && Array.isArray(m.tipLabels)) {
            // 拼色 pin：渲染多色●（如 ●趋势转向+●上轨突破 紫●+金●，方案3 修拼色 tooltip bug）
            const dots = m.tipColors.map((c, i) => '<b style="color:' + c + '">●</b>' + (m.tipLabels[i] || "")).join("+");
            tip += '<br/>' + dots + " " + _fmtReasonWithBand(m.reason);
          } else {
            const mc = typeof m.itemStyle.color === "string" ? m.itemStyle.color : "#ffd700";
            tip += '<br/><b style="color:' + mc + '">● ' + m.value + "</b> " + _fmtReasonWithBand(m.reason);
          }
        }
        return tip;
      }
    },
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
        label: { fontSize: 11, color: cssVar("--text-1"), hideOverlap: true },
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
// 2026-07-20: 加 index\/[^/]+-all 排除 kc50-all.json 等 index/{iid}-all.json（走势图源），
// 让走势图与 overview 同级实时（跳过 5min 缓存），避免"卡片有信号但走势图无 pin"的窗口期不一致。
// 只排除 *-all.json（走势图源），不排除 industry-*-indices/* 等静态少变文件（保留缓存）。
const _NO_CACHE_URLS = /(?:^|\/)(?:overview|intraday_snapshot|metrics|summary(?:_history|\/history)?|index\/[^/]+-all)(?:\.json)?(?:$|[?])/;
const _CACHE_TTL = 5 * 60 * 1000; // 历史类数据缓存 5 分钟
// R2 大range 路由（2026-07-24）：all/5y/3y 从 R2 读（减 git 仓库 ~60M），小 range（3m/6m/1y）留本地减延迟。
// fetchJSON 自动 .gz 优先 + DecompressionStream 解压，./data/ 与 https://ssd.fx8.store/ 均生效。
// 匹配 -(all|5y|3y).json 结尾 -> R2；其余 -> 本地 ./data/。
const _R2_DATA_BASE = "https://ssd.fx8.store/data/";
const _R2_LARGE_RANGE_RE = /-(?:all|5y|3y)\.json$/;
function dataUrl(filename) {
  return _R2_LARGE_RANGE_RE.test(filename) ? _R2_DATA_BASE + filename : "./data/" + filename;
}
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
  // JSON gz 方案B/Y: 优先 .json.gz + DecompressionStream 解压(MaoziYun 不支持 Content-Encoding,前端显式解压)
  // 失败(404/解压错/不支持)fallback 原 .json。仅对 ./data/*.json 静态资源启用(跳过 /api/* 和外链 https://)
  // 支持 url 带 query string(如 ?v=xxx): .gz 插在 .json 后 query 前
  // 方案Y: export.py GZ_THRESHOLD=0 全量生成 .gz(含小文件),.gz 优先不再 404
  const _qIdx = url.indexOf("?");
  const _base = _qIdx >= 0 ? url.slice(0, _qIdx) : url;
  const _query = _qIdx >= 0 ? url.slice(_qIdx) : "";
  // R2 全迁后 ./data/ 与 https://ssd.fx8.store/ 均走 .gz 优先(DecompressionStream 解压)
  const tryGz = (_base.startsWith("./data/") || _base.startsWith("https://ssd.fx8.store/")) && _base.endsWith(".json");
  const gzUrl = tryGz ? _base + ".gz" + _query : null;
  const controller = new AbortController();
  const slowTimer = setTimeout(() => controller.abort(), 15000);
  // cache: 'no-cache' 走条件请求(带 If-None-Match/If-Modified-Since), 绕过 R2 .gz 的 cache-control: max-age=14400 强制缓存
  // 否则 stats 等数据更新后浏览器仍读 4h 旧缓存 (2026-07-22 csi_div tooltip 显示旧版 sell_stop_loss n 而非新版 86 的根因)
  const doFetch = (u) => fetch(u, { signal: controller.signal, cache: "no-cache" })
    .then((r) => { if (!r.ok) throw new Error("HTTP " + r.status + " " + u); return r; });
  const p = (async () => {
    let resp;
    try {
      if (gzUrl) {
        resp = await doFetch(gzUrl);
        // DecompressionStream 96%+ 兼容;不支持时抛错走 catch fallback
        if (typeof DecompressionStream === "undefined") throw new Error("DecompressionStream unsupported");
        const ds = new DecompressionStream("gzip");
        const decompressed = resp.body.pipeThrough(ds);
        const txt = await new Response(decompressed).text();
        return JSON.parse(txt);
      }
      resp = await doFetch(url);
      return await resp.json();
    } catch (e) {
      // .gz 失败(404/解压错/不支持) -> fallback 原 .json(只对原本就是 .gz 尝试的 URL)
      if (gzUrl && !(e && e.name === "AbortError")) {
        resp = await doFetch(url);
        return await resp.json();
      }
      throw e;
    }
  })()
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
// === C7 P4 market 融合:market tab 指数卡接入分数卡 + 深度拆解 modal ===
// 58 个 iid 白名单(9宽基+3红利+3港股+9全球+31申万+3国债),与 static-site/data/alert_analyze_*.json 一一对应
// 复用 common.js 的 _labCustom* 函数(window._labCustom*),lab-custom-* 样式已移到 style.css 全 tab 共享
const _MARKET_ANALYZE_IIDS = new Set([
  // 9 宽基
  "sh","sz","sz50","hs300","csi500","csi1000","cyb","kc50","bj50",
  // 3 红利
  "csi_div","div_lowvol","sz_div",
  // 3 港股
  "hsi","hstech","hscei",
  // 9 全球
  "us_dji","us_ixic","us_spx","us_ndx","nikkei225","kospi","ftse100","dax","cac40",
  // 31 申万一级行业
  "sw_801010","sw_801030","sw_801040","sw_801050","sw_801080","sw_801880",
  "sw_801110","sw_801120","sw_801130","sw_801140","sw_801150","sw_801160",
  "sw_801170","sw_801180","sw_801200","sw_801210","sw_801780","sw_801790",
  "sw_801230","sw_801710","sw_801720","sw_801730","sw_801890","sw_801740",
  "sw_801750","sw_801760","sw_801770","sw_801950","sw_801960","sw_801970","sw_801980",
  // 3 国债波段(方案B:仓位分 alert.position 数据已就绪,接入分数卡)
  "cgb_idx","cgb_10y_etf","cgb_10y_future",
]);

// 紧凑版分数卡 HTML(图表下方用,深度内容进 modal 看)
// 复用 common.js 的 _labCustomLevelClass/_labCustomLevelText/_labCustomLevelTooltip/_labCustomScoreSummary
function _marketScoreCardHTML(data, alert, humanText) {
  const high = alert.high, low = alert.low;
  const highLvlCls = _labCustomLevelClass(high, "high");
  const lowLvlCls = _labCustomLevelClass(low, "low");
  const highLvlText = _labCustomLevelText(alert.high_level);
  const lowLvlText = _labCustomLevelText(alert.low_level);
  const highTooltip = _labCustomLevelTooltip(high, "high");
  const lowTooltip = _labCustomLevelTooltip(low, "low");
  const summary = _labCustomScoreSummary(high, low);
  // 方案B:仓位分(alert.position = {hands, volatility, label, detail})
  // 批次2b:6维度透明化,主chip露综合分+关键维度摘要,tooltip 看全6维度
  const pos = alert.position || null;
  const posHands = pos ? pos.hands : null;
  const posLabel = pos ? pos.label : "";
  const posVol = pos ? pos.volatility : null;
  const posDetail = (pos && pos.detail) ? pos.detail : null;
  const posScore = posDetail && posDetail.score != null ? Number(posDetail.score) : null;
  const _d = posDetail || {};
  const _f0 = (v) => (v != null ? Number(v).toFixed(0) : "-");
  const posDimTitle = posDetail
    ? `机会${_f0(_d.opp)} / 趋势${_f0(_d.trend)} / 动量${_f0(_d.mom)} / 波动${_f0(_d.vol)} / 流动性${_f0(_d.liq)} / 回撤${_f0(_d.draw)}`
    : "";
  const posScoreHTML = posScore != null
    ? `<span class="position-score" title="综合分=${posScore.toFixed(1)}(6维度加权,点击深度拆解看明细)">综合 ${posScore.toFixed(1)}</span>`
    : "";
  const posDimHTML = posDetail
    ? `<span class="position-dim-summary" title="${posDimTitle}">机会${_f0(_d.opp)} 趋势${_f0(_d.trend)}</span>`
    : "";
  const posBadge = pos
    ? `<span class="position-badge position-${posHands}">建议仓位 ${posLabel}</span>` +
      posScoreHTML + posDimHTML +
      `<span class="volatility-text">波动率 ${posVol != null ? posVol.toFixed(2) : "-"}%</span>`
    : `<span class="position-badge position-0">建议仓位 数据不足</span>`;
  return `<div class="market-score-card" data-iid="${data.target_id || ""}">
    <div class="market-score-summary ${summary.cls}">${summary.text}</div>
    <div class="market-score-grid">
      <div class="market-score-cell ${highLvlCls}">
        <div class="market-cell-label">高位风险</div>
        <div class="market-cell-score">${high != null ? high.toFixed(2) : "-"}</div>
        <div class="market-cell-level" title="${highTooltip}">${highLvlText}</div>
      </div>
      <div class="market-score-cell ${lowLvlCls}">
        <div class="market-cell-label">低位机会</div>
        <div class="market-cell-score">${low != null ? low.toFixed(2) : "-"}</div>
        <div class="market-cell-level" title="${lowTooltip}">${lowLvlText}</div>
      </div>
    </div>
    <div class="market-position-row">${posBadge}</div>
    <div class="market-score-cta">🔬 点击查看深度拆解</div>
  </div>`;
}

// 异步 fetch alert_analyze + append 紧凑分数卡到 containerEl + 绑 onclick 弹 modal
// try/catch 静默失败,不影响图表渲染
async function _attachMarketScoreCard(iid, name, containerEl) {
  if (!containerEl || !_MARKET_ANALYZE_IIDS.has(iid)) return;
  try {
    const v = _labCustomCacheBust();
    const data = await fetchJSON(`./data/alert_analyze_${iid}.json?v=${v}`);
    if (!data || data.error) return;
    const alert = data.alert || {};
    const humanText = (data.reason || {}).human_text;
    containerEl.insertAdjacentHTML("beforeend", _marketScoreCardHTML(data, alert, humanText));
    const card = containerEl.querySelector(".market-score-card:last-child");
    if (card) card.onclick = () => openIndexAnalyzeModal(iid, name);
  } catch (e) { /* 静默失败 */ }
}

// 深度拆解 modal(复用 .rule-modal 骨架,5 分区用 common.js 的 _labCustom* 拼 HTML)
function openIndexAnalyzeModal(iid, name) {
  let modal = document.getElementById("indexAnalyzeModal");
  if (!modal) {
    modal = document.createElement("div");
    modal.id = "indexAnalyzeModal";
    modal.className = "rule-modal hidden";
    modal.innerHTML = `<div class="rule-modal-overlay"></div>
      <div class="rule-modal-body signal-chart-modal-body">
        <div class="rule-modal-header">
          <h3 class="index-analyze-title">🔬 深度拆解</h3>
          <button class="rule-modal-close" aria-label="关闭">&times;</button>
        </div>
        <div class="rule-modal-content index-analyze-content"></div>
      </div>`;
    document.body.appendChild(modal);
    modal.querySelector(".rule-modal-overlay").onclick = closeIndexAnalyzeModal;
    modal.querySelector(".rule-modal-close").onclick = closeIndexAnalyzeModal;
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && !modal.classList.contains("hidden")) closeIndexAnalyzeModal();
    });
  }
  modal.querySelector(".index-analyze-title").textContent = `🔬 深度拆解 - ${name}`;
  const body = modal.querySelector(".index-analyze-content");
  body.innerHTML = '<div class="lab-custom-loading">⏳ 加载中…</div>';
  modal.classList.remove("hidden");
  document.body.style.overflow = "hidden";

  (async () => {
    try {
      const v = _labCustomCacheBust();
      const data = await fetchJSON(`./data/alert_analyze_${iid}.json?v=${v}`);
      if (!data || data.error) {
        body.innerHTML = `<div class="lab-custom-error">` +
          `<div class="lab-custom-error-title">⚠️ 数据不足，暂无法分析此标的</div>` +
          `<div class="lab-custom-error-detail">${(data && data.error) || "未知"}</div>` +
          `<div class="lab-custom-error-hint">该标的后端计算异常（如指数数据缺失/dtype 异常），待后端修复后自动恢复。</div>` +
          `</div>`;
        return;
      }
      const alert = data.alert || {};
      const reason = data.reason || {};
      body.innerHTML = "";
      body.insertAdjacentHTML("beforeend", _labCustomScoreCardHTML(data, alert, reason.human_text));
      body.insertAdjacentHTML("beforeend", _labCustomPositionDetailHTML(alert.position));
      body.insertAdjacentHTML("beforeend", _labCustomDimsTableHTML(reason.dim_hits, alert.dims, alert.adapt));
      body.insertAdjacentHTML("beforeend", _labCustomHistoryHTML(reason.history_analogy, reason.human_text));
      body.insertAdjacentHTML("beforeend", _labCustomThresholdsHTML(reason.data_thresholds));
      body.insertAdjacentHTML("beforeend", _labCustomFooterHTML(reason.compliance_footer, reason.no_data_hint));
      // 折叠阈值表交互(同 lab.js renderCustomAnalyzeLab)
      const toggle = body.querySelector(".lab-custom-thresh-toggle");
      if (toggle) {
        toggle.onclick = () => {
          const tBody = body.querySelector(".lab-custom-thresh-body");
          const open = tBody && tBody.style.display !== "none";
          if (tBody) tBody.style.display = open ? "none" : "block";
          toggle.textContent = open ? "展开数据阈值表 ▾" : "收起数据阈值表 ▴";
        };
      }
    } catch (e) {
      body.innerHTML = `<div class="lab-custom-error">⚠️ 加载失败：${e.message || e}</div>`;
    }
  })();
}

function closeIndexAnalyzeModal() {
  const modal = document.getElementById("indexAnalyzeModal");
  if (modal) modal.classList.add("hidden");
  document.body.style.overflow = "";
}

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

  // === A5 pin 复盘面板：本 section 的容器引用 + 数据源（供 pin-changed 事件刷新用）===
  let pinReviewContainer = null;
  // 异步渲染复盘面板：pinned 指数列表 -> 每个渲染一张复盘卡片（数据从 _pinDataCache 拿，cache miss 则 await fetcher）
  async function _renderPinReview() {
    if (!pinReviewContainer || !pinReviewContainer.isConnected) return;
    var pinnedIds = _getPinnedIds();
    // 仅保留本 section 实际拥有的指数（跨 tab pin 状态隔离：A 股 tab 只显示 A 股 pinned）
    var validIds = pinnedIds.filter(function (id) { return entries.some(function (e) { return e[0] === id; }); });
    if (!validIds.length) {
      pinReviewContainer.innerHTML = "";
      pinReviewContainer.style.display = "none";
      return;
    }
    pinReviewContainer.style.display = "";
    pinReviewContainer.innerHTML = '<div class="pin-review-loading"><span class="loading__spinner"></span><span class="loading__text">加载钉住指数复盘…</span></div>';
    var htmlParts = [];
    for (var i = 0; i < validIds.length; i++) {
      var id = validIds[i];
      var entry = entries.find(function (e) { return e[0] === id; });
      if (!entry) continue;
      var idx = entry[1];
      var sig = signalsCache[id] || (_pinDataCache[id] && _pinDataCache[id].sig) || null;
      if (!sig) {
        // cache miss: 异步补 fetcher（不阻塞其他卡片渲染）
        try {
          sig = await fetcher(id, idx);
          signalsCache[id] = sig;
        } catch (e) { sig = null; }
      }
      // 同步 _pinDataCache（_appendPinBtn 也会写，这里兜底）
      _pinDataCache[id] = { idx: idx, sig: sig };
      htmlParts.push(_pinReviewCardHtml(id, idx, sig));
    }
    if (!pinReviewContainer.isConnected) return;  // 异步期间可能被切走
    pinReviewContainer.innerHTML = '<div class="pin-review-header">📌 钉住指数复盘（' + validIds.length + '）<span class="pin-review-hint">点击指数卡片标题 📌 钉住/取消</span></div>' +
      '<div class="pin-review-list">' + htmlParts.join("") + '</div>';
    // 绑定取消 pin 按钮
    var unpinBtns = pinReviewContainer.querySelectorAll("[data-unpin-id]");
    unpinBtns.forEach(function (btn) {
      btn.addEventListener("click", function () {
        var uid = btn.getAttribute("data-unpin-id");
        if (uid) _togglePin(uid);
      });
    });
  }
  // pin-changed 事件：刷新本 section 复盘面板 + 同步各卡片 📌 按钮状态
  // self-cleanup：切 tab 后 container 被 renderTab 清空，pinReviewContainer 不再 connected，
  // 下次 pin-changed 触发时检测到 not connected 即 removeEventListener 自身，避免监听器累积。
  function _onPinChanged() {
    if (!pinReviewContainer || !pinReviewContainer.isConnected) {
      document.removeEventListener("pin-changed", _onPinChanged);
      return;
    }
    _renderPinReview();
    // 同步本 section 内所有 pin-btn 的 active 状态
    var btns = container.querySelectorAll(".pin-btn[data-pin-id]");
    btns.forEach(function (b) {
      var bid = b.getAttribute("data-pin-id");
      var act = _isPinned(bid);
      b.classList.toggle("active", act);
      b.setAttribute("aria-label", act ? "取消钉住" : "钉住指数");
      b.setAttribute("title", act ? "已钉住，点击取消" : "钉住该指数，顶部显示专属复盘");
    });
  }
  document.addEventListener("pin-changed", _onPinChanged);

  async function _doRender() {
    disposeSectionCharts();
    container.innerHTML = "";
    // === A5 pin 复盘面板容器（放最顶部，filter-bar 之前）===
    pinReviewContainer = document.createElement("div");
    pinReviewContainer.className = "pin-review-section";
    pinReviewContainer.style.display = "none";  // 无 pinned 时隐藏
    container.appendChild(pinReviewContainer);
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
    // 6色信号图例（4色买点+卖绿+追止损蓝）+ 备买风险提示（2026-07-21 阶段4）
    container.insertAdjacentHTML("beforeend", _signalLegendHtml());
    // 改动4（2026-07-23）：筛选切换时先显示 loading 占位，避免数据加载期间空白；
    // renderOne 首次成功渲染时移除占位；若最终没有任何 chart-card 渲染出来则替换为"该筛选暂无数据"。
    const chartLoadingEl = document.createElement("div");
    chartLoadingEl.className = "loading loading--active index-filter-loading";
    chartLoadingEl.innerHTML = `<span class="loading__spinner"></span><span class="loading__text">加载指数数据中…</span>`;
    container.appendChild(chartLoadingEl);
    // 渲染单个指数到 parent（chart 入全局 charts 供 resize + sectionCharts 供本区 dispose）
    async function renderOne(id, idx, parent) {
      if (!signalsCache[id]) signalsCache[id] = await fetcher(id, idx);
      const sig = signalsCache[id];
      // 首次成功进入渲染流程即移除 loading 占位（chart-card 即将 append）
      if (chartLoadingEl.parentNode) chartLoadingEl.parentNode.removeChild(chartLoadingEl);
      if (idx.data && idx.data.length) {
        // 港股盘中实时标注（快照注入 _snap_intraday=true 时显示）
        const intradayTag = idx._snap_intraday ? ' <span class="snap-intraday-tag">⏰ 盘中实时</span>' : "";
        const c = indexChart(idx.name + intradayTag, idx.data, sig.signals, sig.stats, idx.strategy, parent, charts, id);
        sectionCharts.push(c);
        addCardTimeBadge(c.getDom().parentElement, idx.data.length ? idx.data[idx.data.length - 1].date : "", state.intradaySnapshot, "t0");
        // 标题❓策略弹窗（2026-07-20 方案B1）：h3 末尾追加❓，hover 一句话摘要 + click 弹该指数6类策略详情 modal
        _appendStrategyHint(c.getDom().parentElement, id, idx.strategy);
        // P2-新-G ETF 联动推荐：h3 末尾追加 ETF tag（buy 信号触发时加 .etf-tag-buy-signal 高亮）
        _appendEtfLinkTag(c.getDom().parentElement, id, idx.etfs, sig.signals);
        // 备买 chip 三档（2026-07-23）：标题下换行单独一行展示，h3 之后插入独立 chip-row 容器（异步 fetch+patch）
        _appendBackupChipRow(c.getDom().parentElement, id);
        // C7 P4 market 融合:图表卡下 append 紧凑分数卡(白名单 iid 才显示)
        _attachMarketScoreCard(id, idx.name, c.getDom().parentElement);
        // A5 真 pin 复盘：h3 末尾追加 📌 按钮（钉住该指数，顶部显示专属复盘面板）
        _appendPinBtn(c.getDom().parentElement, id, idx, sig);
        // A12 订阅推送：h3 末尾追加 🔔 按钮（订阅该指数信号，推送邮件+Telegram）
        _appendSubscribeBtn(c.getDom().parentElement, id, idx.name);
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
      // 改动4：若 loading 占位仍在说明没有任何 chart-card 渲染（如 idx.data 空），替换为 empty state
      if (chartLoadingEl.parentNode) {
        chartLoadingEl.className = "trade-sim-empty";
        chartLoadingEl.innerHTML = "📊 该筛选暂无数据";
      }
      // A5: 渲染 pin 复盘面板（signalsCache 已填充，异步补 cache miss）
      _renderPinReview();
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
    // 改动4：若 loading 占位仍在（如所有 idx.data 空），替换为 empty state
    if (chartLoadingEl.parentNode) {
      chartLoadingEl.className = "trade-sim-empty";
      chartLoadingEl.innerHTML = "📊 该筛选暂无数据";
    }
    // A5: 渲染 pin 复盘面板（signalsCache 已填充，异步补 cache miss）
    _renderPinReview();
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
      <h4><span class="rule-dot rule-dot-buy"></span>超卖反弹参考点</h4>

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
      <h4><span class="rule-dot rule-dot-sell"></span>趋势转弱参考点</h4>

      <div class="rule-card rule-card-sell">
        <div class="rule-card-head"><span class="rule-badge badge-sell">卖点</span> 趋势转弱参考 · 止盈减仓提示（非卖出指令）</div>
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
      <h4><span class="rule-dot" style="background:#ffd700"></span>追买与止损参考点</h4>

      <div class="rule-card" style="border-left:3px solid #ffd700">
        <div class="rule-card-head"><span class="rule-badge" style="background:#fff3cc;color:#8a6d00">追买</span> 上轨突破（唐奇安 20 日）</div>
        <p>唐奇安 20 日上轨突破 + 5 日确认。<b>趋势跟随</b>思路，突破后惯性上行。</p>
        <table class="rule-table">
          <tr><td class="rule-td-label">含义</td><td>收盘价突破近 20 日最高价（不含当日），5 日内确认有效</td></tr>
          <tr><td class="rule-td-label">颜色</td><td><span class="rule-badge" style="background:#ffd700;color:#000">金色</span> 图表上标记为「追买」</td></tr>
          <tr><td class="rule-td-label">回测持有期建议</td><td>5d 胜率59.65%/均值+0.87%/回撤2.65%；10d 60.24%/+1.66%/4.26%（<b>风险调整最优</b>）；30d 59.06%/+3.44%（<b>分水岭</b>，风险/收益拐点）；90d 60.83%/+9.42%/回撤16.53%（<b>纯收益最优</b>，但回撤大）</td></tr>
        </table>
        <p class="rule-note">⚠️ <b>趋势跟踪策略</b>：低胜率靠大盈拉均值，区别于主买/辅买的均值回归（高胜率小赚）。必须配「追止损|卖」控制风险，0 套牢。</p>
      </div>

      <div class="rule-card" style="border-left:3px solid #3498db">
        <div class="rule-card-head"><span class="rule-badge" style="background:#e8f4fd;color:#1c6dbf">追止损|卖</span> ATR×3.5 止损</div>
        <p>价格跌破 <b>ATR×3.5 动态止损线</b>（底层规则从 Donchian20 下轨改为 ATR×3，2026-07-21 调 ATR×3.5 降频）。趋势反转下行最后防线。</p>
        <table class="rule-table">
          <tr><td class="rule-td-label">含义</td><td>ATR（平均真实波幅）×3.5 作为止损距离，波动大时止损宽、波动小时止损窄，自适应市场节奏</td></tr>
          <tr><td class="rule-td-label">颜色</td><td><span class="rule-badge" style="background:#3498db;color:#fff">蓝色</span> 图表上标记为「追止损|卖」</td></tr>
          <tr><td class="rule-td-label">回测对比</td><td>现 ATR×3 胜率46.91%/均值+1.76%/盈亏比1.82，全维度略优原 Don20（胜率44.33%/均值+1.56%，2008股灾-10.5%最差）。2026-07-21 调 ATR×3.5 降频后 hs300 触发 -18%/5d win 49.58%->50.23%</td></tr>
        </table>
        <p class="rule-note">⚠️ <b>最后防线</b>：跌破即止损，趋势反转下行。与「卖」共振时减仓信号更强。蓝色与卖绿色区分。</p>
      </div>
    </div>

    <div class="rule-section">
      <h4><span class="rule-dot rule-dot-read"></span>如何解读信号</h4>

      <p class="rule-subtitle">盈亏标注（卖点颜色含义）</p>
      <table class="rule-table rule-table-color">
        <tr>
          <td style="width:50%"><span class="rule-dot-sm rule-dot-profit"></span> <b>绿色 = 止盈</b></td>
          <td><span class="rule-dot-sm rule-dot-profit"></span> <b>绿色 = 趋势转弱</b></td>
        </tr>
        <tr>
          <td>卖点价格 &gt; 前一个买点价格<br><span class="muted">→ 历史多为止盈/减仓情形</span></td>
          <td>卖点价格 &le; 前一个买点价格 / 附近无前买参考<br><span class="muted">-> 含前买失效/无前买点，统一落趋势转弱（非操作建议）</span></td>
        </tr>
      </table>

      <p class="rule-subtitle">pin「盈亏X%」标签来源</p>
      <p class="muted">卖点 pin 上的「盈亏X%」标签 = sell 信号 reason 中「vs前买+X%」的<b>单次配对实现涨幅</b>（该卖点 vs 前一个买点的实际涨跌），<b>非统计期望值</b>。hover tooltip 的「盈亏比Y」才是历史统计值。二者勿混。</p>

      <p class="rule-subtitle">情绪背景标签</p>
      <p class="muted">趋势转弱参考点会附带当前市场情绪分，帮你判断「技术拐点 + 情绪背景」的强弱：</p>
      <table class="rule-table rule-table-tags">
        <tr>
          <td><span class="rule-tag tag-freeze">冰点</span> ≤ 20</td>
          <td><span class="rule-tag tag-cool">偏冷</span> 21–40</td>
          <td><span class="rule-tag tag-neutral">中性</span> 41–60</td>
          <td><span class="rule-tag tag-warm">偏热</span> 61–80</td>
          <td><span class="rule-tag tag-hot">过热</span> &gt; 80</td>
        </tr>
      </table>

      <p class="rule-subtitle">超卖反弹参考点示例</p>
      <div class="rule-example"><span class="muted">主买：</span>RSI上穿30(29→34), 情绪=8[冰点]</div>
      <div class="rule-example"><span class="muted">辅买：</span>布林下轨回归(下轨3852,收盘3870), RSI=41, 情绪=47[偏冷]</div>

      <p class="rule-subtitle">趋势转弱参考点示例</p>
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
          const labels = { buy: "买点", buy_aux: "辅买", buy_special: "追买", buy_special_filtered: "追买(过滤预览)", buy_backup: "备买", sell: "卖点", sell_stop_loss: "追止损|卖" , band_hold: "波段持有" };
          const cls = { buy: "buy", buy_aux: "buy-aux", buy_special: "buy-special", buy_special_filtered: "buy-special-filtered", buy_backup: "buy-backup", sell: "sell", sell_stop_loss: "sell-stop-loss" , band_hold: "band-hold" };
          let html = '<div class="hint-header">📅 全品种信号频率汇总</div><div class="hint-blocks">';
          for (const sig of ["buy", "buy_aux", "buy_special", "buy_special_filtered", "buy_backup", "sell", "sell_stop_loss", "band_hold"]) {
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
  // 2026-07-20: 删除硬编码三元链，复用 signalLabel（L310-335 已覆盖 7 种信号 + 默认 fallback "趋势转弱"）。
  // 修复 sell_stop_loss / buy_special_filtered 等漏分支落英文原值的 bug（原末尾 `: signal` 返回英文）。
  // reason 传空串：sell_stop_loss fallback 返回 "ATR止损"（L318），buy_special_filtered 返回 "特买(过滤预览)"。
  const sigLabel = isFreeze ? `冰点${freezeVal ? "(" + freezeVal + ")" : ""}` : signalLabel({signal: signal, reason: ""});
  titleEl.textContent = `${name} · ${sigLabel} · ${fmtDate(date)}`;
  modal.classList.remove("hidden");
  document.body.style.overflow = "hidden";
  modal._ctx = { indexId, signal, date, freezeVal };
  try {
    let chartData, sigs, stats, strategy, isValue = false;

    if (indexId.startsWith("g.")) {
      const key = indexId.slice(2);
      const r = await fetchJSON(dataUrl("global-extras-all.json"));
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
      const r = await fetchJSON(dataUrl("sentiment-all.json"));
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
      const r = await fetchJSON(`https://ssd.fx8.store/index/${indexId}-all.json`);
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
  a_width_zb_count:    { src: "astock" },
  a_width_seal_rate:   { src: "astock" },
  a_width_fengban_rate: { src: "astock" },
  a_fund_main:         { src: "astock" },
  a_turnover_mean:     { src: "astock" },
  a_turnover_median:   { src: "astock" },
  a_turnover_p90:      { src: "astock" },
  a_turnover_p10:      { src: "astock" },
  a_turnover_gt5_pct:  { src: "astock" },
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

  // 情绪分 9 张：visualMap 5 段着色（冰点蓝/偏冷浅蓝/中性灰/偏热橙/过热红，与热力图+恐贪一致：冰=冷色，过热=热色）
  if (cfg.src === "sentiment") {
    const r = await fetchJSON(dataUrl(`sentiment-${period}.json`));
    const list = r[kpiId] || [];
    return {
      series: [{ name, data: list.map(d => ({ date: d.date, value: d.value })) }],
      visualMap: {
        show: false,
        pieces: [
          { lte: 20, color: "#42a5f5" },
          { gt: 20, lte: 40, color: "#4fc3f7" },
          { gt: 40, lte: 60, color: "#86909c" },
          { gt: 60, lte: 80, color: "#e6a23c" },
          { gt: 80, color: "#e6492e" },
        ],
        dimension: 1,
      },
      hint: "≤20冰点(蓝) · 20-40偏冷(浅蓝) · 40-60中性(灰) · 60-80偏热(橙) · >80过热(红)",
    };
  }

  // a-stock 指标
  if (cfg.src === "astock") {
    const r = await fetchJSON(dataUrl(`a-stock-${period}.json`));
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
    // 封板率（百分比，存 0-1 小数需 *100 显示；fengban_rate=1-炸板率 新源，seal_rate 旧源保留兼容）
    if (kpiId === "a_width_seal_rate" || kpiId === "a_width_fengban_rate") {
      const raw = (metrics[kpiId] && metrics[kpiId].data) || [];
      const data = raw.map(d => ({ date: d.date, value: d.value * 100 }));
      return {
        series: [{ name: "封板率", data }],
        yLabel: "{value}%",
        hint: "封板率=1-炸板率（涨停封住/(涨停+炸板)）。高=打板成功率高、封板资金强。",
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
    const r = await fetchJSON(dataUrl("global-extras-all.json"));
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
  const _titleEl = card ? card.querySelector(".card-title") : null;
  const cardTitle = _titleEl ? (stripHtml(_titleEl.innerHTML) || indexIdToName(kpiId)) : indexIdToName(kpiId);
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
  await loadEcharts();   // P2-5: 懒加载 echarts（所有 tab 图表 + lab.js 都依赖）
  clearCharts();
  // 概览 tab 图表固定近60日、策略实验 tab 全历史，周期切换均无意义，隐藏 .periods 和 .h5-period-bar；切走恢复
  const _hidePeriods = (state.tab === "lab" || state.tab === "overview" || state.tab === "etf");
  document.querySelectorAll(".periods, .h5-period-bar").forEach((el) => {
    el.style.display = _hidePeriods ? "none" : "";
  });
  renderLoadingState(content);
  try {
    if (state.tab === "overview") await renderOverview();
    else if (state.tab === "market") await renderMarket();
    else if (state.tab === "sentiment") await renderSentiment();
    else if (state.tab === "industry") await renderIndustry();
    else if (state.tab === "etf") await renderEtfScore();
    else if (state.tab === "lab") {
      await loadLabScript();   // B5: 懒加载 lab.js
      await renderSignalLab();
    }
  } catch (e) {
    renderErrorState(content, e, () => renderTab());
  }
}

// tab 互链引导:点击链接复用顶部 tab 按钮的 onclick 切换
// (state/active class/hash/renderTab 全走原按钮路径,零重复逻辑;market/sentiment 不受 lab 跳过分支影响)
function _bindTabCrosslink(scope, gotoTab) {
  const a = scope.querySelector && scope.querySelector(`a[data-goto="${gotoTab}"]`);
  if (!a) return;
  const go = (e) => { if (e) e.preventDefault(); const b = document.querySelector(`button[data-tab="${gotoTab}"]`); if (b) b.click(); };
  a.onclick = go;
  a.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } };
}

// 采集时间独立化：任何 tab 刷新都能显示，不依赖 renderOverview 是否执行
// 末尾追加 ℹ️ 图标，点击弹"数据更新规则"modal（事件委托在 initUpdateRules 绑定 document，重渲染不失效）。
const _UPDATE_RULES_ICON = '<span class="update-rules-btn" title="数据更新规则" role="button" tabindex="0" aria-label="数据更新规则">ℹ️</span>';
// A4 采集健康度小灯：采集时间旁圆点 🟢(ok)/🟡(warn)/🔴(error)，hover 弹失败源 metric_id+message 列表。
// 复用 overview.collect_health（export.py 导出，最新一次 run 的非 ok 项）；level=ok 时绿点无 pop。
function applyCollectTime(ct, health) {
  _collectTimeBase = { ct: ct || "", health: health || null };
  _renderCollectTime();
}
// 采集时间统一口径（阶段2）：盘中"HH:MM · 动态(3min)"（腾讯最近拉取时间），收盘"HH:MM · 收盘快照"。
// 盘中优先显腾讯动态时间，无则回退 snap 采集时间；后缀让用户一眼区分动态 vs 收盘。
function _renderCollectTime() {
  const { ct, health } = _collectTimeBase;
  const _icon = _UPDATE_RULES_ICON;
  if (!ct) {
    document.querySelectorAll(".pc-collect-time,.h5-collect-time").forEach((el) => { el.innerHTML = ""; });
    return;
  }
  const snap = state.intradaySnapshot;
  const intraday = snap && snap.is_closed === false;
  const timeStr = (intraday && _intradayDynamicTime) ? _intradayDynamicTime : ct;
  const suffix = intraday ? " · 动态(3min)" : " · 收盘快照";
  const _healthHTML = _renderCollectHealthDot(health);
  document.querySelectorAll(".pc-collect-time").forEach((el) => {
    el.innerHTML = `数据采集时间：${timeStr}${suffix}${_healthHTML}${_icon}`;
  });
  document.querySelectorAll(".h5-collect-time").forEach((el) => {
    el.innerHTML = `${timeStr}${suffix}${_healthHTML}${_icon}`;
  });
}
// A4 健康灯 HTML：ok 绿点（无 pop）；warn/error 黄/红点 + hover pop 显示失败源列表。
function _renderCollectHealthDot(health) {
  if (!health) return "";
  const level = health.level || "ok";
  const items = Array.isArray(health.items) ? health.items.filter((it) => it && it.status && it.status !== "ok") : [];
  if (level === "ok" && !items.length) {
    return `<span class="collect-health" data-level="ok" title="采集正常"><span class="collect-health-dot"></span></span>`;
  }
  const _tagText = (s) => (s === "error" ? "错误" : s === "disabled" ? "中断" : "警告");
  const listHTML = items.map((it) =>
    `<div class="collect-health-item"><span class="collect-health-tag collect-health-tag--${it.status}">${_tagText(it.status)}</span><span class="collect-health-mid">${it.metric_id || ""}</span><span class="collect-health-msg">${(it.message || "").replace(/</g, "&lt;")}</span></div>`
  ).join("");
  const title = `采集${level === "error" ? "异常" : "告警"} ${items.length} 项`;
  return `<span class="collect-health" data-level="${level}" tabindex="0" role="button" aria-label="${title}">
    <span class="collect-health-dot"></span>
    <span class="collect-health-pop">
      <div class="collect-health-pop-title">采集${level === "error" ? "异常" : "告警"} · ${items.length} 项</div>
      ${listHTML || '<div class="collect-health-empty">无详情</div>'}
    </span>
  </span>`;
}
async function fetchCollectTime() {
  try {
    const r = await fetchJSON("./data/overview.json");
    applyCollectTime(r.collected_at, r.collect_health);
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
    let relax = _t1Relax(srcKey, intraday);
    // 美股跨市场时区滞后：美东21:30开盘(北京次日04:00收盘)，backfill 16:35才采。
    // A股收盘(15:00)到美股采集(16:35)有间隙，且美股比A股晚约1天。未过16:35采集点
    // -> baseline 放宽到 _prevTradingDay(ptd)(美股上一可得日)，避免A股已到新交易日
    // (ptd)但美股数据尚未采集时误报滞后(周一美股晚开盘，ptd=周一时尤甚)。
    if (srcKey === "us_dji_date") relax = !_pastCollectDeadline("us_dji_date");
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
  if (srcClass === "t1") {
    const ttl = `T+1数据源盘后公布，当前未到最晚可得时刻，末日 ${mmdd}，已滞后约${lagDays}天，预计稍后更新`;
    return `<span class="card-time-badge t1-pending" data-tip="${ttl}">⏳ T+1待更新·${mmdd}</span>`;
  }
  const ttl = `数据滞后(末日 ${mmdd})，盘中等待刷新或update_all尚未运行`;
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
  a_fund_margin: "next_day", // 两融(沪市融资余额): 源端T+1日才发当日值(上交所次日盘后),23:00 rzhb单采永远采不到当日 -> next_day盘中恒放宽,消除T日23:00后误报红
  us_dji_date:   "16:35",   // 美股道指: 美股收盘=北京次日04:00,backfill-evening 16:35采集
  lhb_count:     "19:30",   // 龙虎榜: 东财18:00发当日,lhb-backfill 18:30+19:30(兜底)采集
  futures_date:  "21:00",   // 期货机构持仓: CFFEX 20:00发当日,futures-backfill 20:05+21:00(兜底)采集
  csi_div_date:  "18:00",   // 中证红利: 中证指数公司盘后发布,update_all 17:50采集,18:00后应已到
  etf_date:      "21:30",   // ETF国家队份额: 交易所盘后发布,etf-national-team 20:07+21:30(兜底)采集
  gold:          "18:00",   // 商品期货(黄金/原油): 新浪期货盘后发布,update_all 17:50采集
  cn10y:         "18:00",   // 国债收益率: 中债盘后发布,update_all 17:50采集
  a_qvix_300:    "next_day", // QVIX期权波动率: 源端optbbs T+1日02:00-16:30才发当日值,17:50 update_all常采不到 -> next_day盘中恒放宽,消除18:00后误报红
  industry:      "18:00",   // 申万行业指数: baostock/申万收盘后发布,update_all 17:50采集
  hk_south:      "18:00",   // 港股通净买入: 盘后发布,update_all 17:50采集
  a_fund_main:       "18:00", // 主力净流入: 东财盘后发布,update_all 17:50采集(2026-07-23补配,原漏配走t0误判滞后)
  a_width_fengban_rate: "18:00", // 封板率: derived,update_all 17:50才算(2026-07-23补配,原漏配走t0误判滞后)
  // 换手率5项: BaoStock stock_daily T+1,update_all 17:50采集,18:00后应已到
  a_turnover_mean:    "18:00",
  a_turnover_median:  "18:00",
  a_turnover_p90:     "18:00",
  a_turnover_p10:     "18:00",
  a_turnover_gt5_pct: "18:00",
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
    let relax = _t1Relax(cfg.mid || cfg.dateKey, intraday);
    // 美股跨市场时区滞后：未过16:35采集点放宽基准(同 getCardTimeBadge 美股特殊处理)
    if ((cfg.mid || cfg.dateKey) === "us_dji_date") relax = !_pastCollectDeadline("us_dji_date");
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

// C6 综合风险预警条:读 data/alert.json,high_alert>=72(高位红)/low_alert>=85(低位蓝)时
// 在首页 home-purpose-note 之前插入预警条(等级+原因+命中维度TopN),可折叠/关闭,移动端适配。
async function renderAlertBar(host) {
  let a;
  try { a = await fetchJSON("./data/alert.json"); } catch { return; }
  if (!a || !a.date) return;
  const showHigh = a.high && a.high.triggered;
  const showLow = a.low && a.low.triggered;
  if (!showHigh && !showLow) return; // 市场中性时不打扰
  const note = host.querySelector(".home-purpose-note");
  const items = [];
  if (showHigh) items.push({ type: "high", d: a.high });
  if (showLow) items.push({ type: "low", d: a.low });
  for (const it of items) {
    const key = `alertbar_${a.date}_${it.type}`;
    if (localStorage.getItem(key) === "1") continue; // 当日同等级已关闭
    const bar = document.createElement("div");
    bar.className = `alert-bar ${it.type}`;
    const icon = it.type === "high" ? "🔴" : "🔵";
    const dims = (it.d.dims || []).filter((x) => x.hit).slice(0, 4);
    const dimsHTML = dims.length
      ? `<div class="alert-bar-detail" style="display:none">
           <div class="ab-dim-title">命中维度(强度≥60,≥75为强命中)</div>
           ${dims.map((x) => `<div class="ab-dim"><span class="ab-dim-name">${x.name}</span>
             <span class="ab-dim-bar"><i style="width:${Math.min(100, x.score)}%"></i></span>
             <span class="ab-dim-val">${x.score.toFixed(0)}</span>
             <span class="ab-dim-hit">${x.score >= 75 ? "强" : "✓"}</span></div>`).join("")}
         </div>` : "";
    bar.innerHTML = `<span class="ab-icon">${icon}</span>
      <div class="ab-main"><span class="ab-level">${it.d.level}预警</span>
        <span class="ab-score">分数 ${it.d.score != null ? it.d.score.toFixed(1) : "-"}</span>
        <span class="ab-reason">${it.d.reason || ""}</span></div>
      <div class="ab-actions">
        ${dims.length ? `<button class="ab-btn ab-toggle" title="展开/收起命中维度">▾</button>` : ""}
        <button class="ab-btn ab-close" title="关闭当日此预警">✕</button>
      </div>${dimsHTML}`;
    host.insertBefore(bar, note || host.firstChild);
    const detail = bar.querySelector(".alert-bar-detail");
    bar.querySelector(".ab-toggle")?.addEventListener("click", () => {
      if (!detail) return;
      const open = detail.style.display !== "none";
      detail.style.display = open ? "none" : "flex";
      bar.querySelector(".ab-toggle").textContent = open ? "▾" : "▴";
    });
    bar.querySelector(".ab-close")?.addEventListener("click", () => {
      localStorage.setItem(key, "1");
      bar.remove();
    });
  }
}

async function renderOverview() {
  // O3：复用 overview 缓存，避免概览/采集时间/分享图重复请求
  const r = _getCachedOverview() || await fetchJSON("./data/overview.json");
  _setCachedOverview(r);
  // 分享按钮旁显示数据采集时间（来自 collect_log 最新 run_at）+ A4 健康灯（collect_health）
  applyCollectTime(r.collected_at, r.collect_health);
  // 盘中标注：等快照就绪（最多 1.5s），让每张卡片角标判断 714 实时 vs 713 待收盘
  try { await Promise.race([fetchIntradaySnapshot(), new Promise((res) => setTimeout(res, 1500))]); } catch {}
  const snap = state.intradaySnapshot;
  _renderCollectTime(); // snap 就绪后更新采集时间后缀（动态/收盘）
  content.innerHTML = "";
  content.insertAdjacentHTML("beforeend", '<div class="home-purpose-note">💡 <b>今天 A 股多冷多热?一眼看全</b>:情绪分(0-100,越低越恐慌)+涨跌家数+历史位置+拐点提示,综合判断当前偏冷还是偏热。</div>');
  // C6 综合风险预警条:high_alert>=72(高位红)/low_alert>=85(低位蓝)时顶部提示(异步,不阻塞渲染)
  renderAlertBar(content);
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
      // P0-2 多指数共振冰点：≥3 个宽基情绪分同时冰点(<20)时，横幅转红 + 共振聚合提示
      // 数据来自 overview today.scores（6 宽基：上证50/沪深300/中证500/中证1000/创业板/科创50情绪分）
      const _BROAD_SENT_IDS = ["sentiment_sz50", "sentiment_hs300", "sentiment_csi500", "sentiment_csi1000", "sentiment_cyb", "sentiment_kc50"];
      const _ovScores = (r.today && r.today.scores) || {};
      const _frozenList = [];
      for (const sid of _BROAD_SENT_IDS) {
        const sc = _ovScores[sid];
        if (sc && (sc.is_freeze || (sc.value != null && sc.value < 20))) {
          _frozenList.push({ id: sid, name: indexIdToName(sid), value: sc.value, date: sc.date });
        }
      }
      if (_frozenList.length >= 3) {
        let _firstSince = "";
        try {
          const sall = await fetchJSON(dataUrl("sentiment-all.json"));
          if (state.tab !== 'overview') return;
          // 扫描历史，找上一个 ≥3 宽基同日冰点的日期，算"近X月首次"
          const _dfc = {};
          for (const sid of _BROAD_SENT_IDS) {
            for (const d of (sall[sid] || [])) {
              if (d.is_freeze || (d.value != null && d.value < 20)) _dfc[d.date] = (_dfc[d.date] || 0) + 1;
            }
          }
          const _curDate = _frozenList[0].date || r.date;
          const _prevDates = Object.keys(_dfc).filter(d => d !== _curDate && _dfc[d] >= 3).sort();
          if (_prevDates.length) {
            const _prev = _prevDates[_prevDates.length - 1];
            const _mo = (+_curDate.slice(0, 4) - +_prev.slice(0, 4)) * 12 + (+_curDate.slice(4, 6) - +_prev.slice(4, 6));
            // 诚信口径：距上次≥3冰点间隔≥1月才称"近X月首次"；<1月=近期持续冰点(不夸大稀缺性)
            _firstSince = _mo >= 12 ? `近${Math.floor(_mo / 12)}年首次` : _mo >= 1 ? `近${_mo}月首次` : "近期持续冰点";
          } else {
            _firstSince = "数据期内首次";
          }
        } catch (e) { /* best-effort，无历史数据则不显示"首次" */ }
        const _names = _frozenList.map(f => `${f.name}=${f.value != null ? f.value.toFixed(1) : "-"}`).join("、");
        const resBanner = document.createElement("div");
        resBanner.className = "freeze-resonance-banner";
        resBanner.innerHTML = `<span class="fr-icon">⚠️</span><span class="fr-text"><b>${_frozenList.length}/6 宽基情绪分进入冰点区</b>${_firstSince ? ` · ${_firstSince}` : ""}</span><span class="fr-detail">${_names}</span>`;
        content.insertBefore(resBanner, banner);
      }
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
      case "a_width_zhaban_rate":
      case "a_width_seal_rate":
      case "a_width_fengban_rate": return (v * 100).toFixed(1) + "%"; // 存储为 0-1 小数
      case "a_width_zt_count":
      case "a_width_dt_count":
      case "a_width_up_count":
      case "a_width_down_count":
      case "a_width_zb_count": return v.toFixed(0);
      case "a_amount":
      case "a_fund_margin": return v.toFixed(0);
      case "a_fund_north":
      case "a_fund_main": return (v >= 0 ? "+" : "") + v.toFixed(1);
      case "a_volume_ratio": return v.toFixed(2) + "x";
      case "a_turnover_mean":
      case "a_turnover_median":
      case "a_turnover_p90":
      case "a_turnover_p10": return v.toFixed(2) + "%";
      case "a_turnover_gt5_pct": return (v * 100).toFixed(1) + "%"; // 存储为 0-1 小数
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
    // 北向资金等源端长期停更(2024-08 起)：不再隐藏,恢复显示末日值并叠加"数据停更"水印(见 KPI 卡渲染),
    // 恢复更新后 isStaleMetric 自动转 false,水印消失。
    const _stale = isStaleMetric(m.date, r.date);
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
      stale: _stale,
    });
  }
  // P0-1 数据诚信披露：collect_health 标记 error/disabled 但未在 KPI 展示的指标，显示灰态卡片而非静默隐藏。
  // 研究工具立身之本——用户必须知道哪些指标当前采集异常（数据源中断），诚信 > 美观。
  const _DISABLED_METRIC_NAMES = {
    a_fund_main: "主力净流入", a_width_zhaban_rate: "炸板率", a_width_zb_count: "炸板数", a_width_seal_rate: "封板率", a_width_fengban_rate: "封板率",
    a_turnover_mean: "换手率均值", a_turnover_median: "换手率中位数", a_turnover_p90: "换手率90分位",
    a_turnover_p10: "换手率10分位", a_turnover_gt5_pct: "换手率>5%占比",
  };
  const _existingKpiIds = new Set(kpiCards.map(k => k.id));
  const _chItems = (r.collect_health && r.collect_health.items) || [];
  for (const it of _chItems) {
    if (it.status !== "error" && it.status !== "disabled") continue;
    if (_existingKpiIds.has(it.metric_id)) continue;  // 已正常展示的指标不重复加灰态卡
    kpiCards.push({
      id: it.metric_id,
      title: _DISABLED_METRIC_NAMES[it.metric_id] || it.metric_id,
      value: "采集异常",
      valueNum: null,
      sub: "数据源中断",
      date: r.date,
      tag: "异常",
      disabled: true,
    });
  }
  // ---- A+B 组合默认排序 + 用户拖拽自定义 ----
  // B(核心情绪前置): a_sentiment/cross_market/fear_greed 三张情绪温度计排最前
  // A(异常度优先): 组内带异常 tag(冰点/过热) 或 signal(放量/缩量) 的卡排前
  // 兜底: 原 kpiOrder 顺序
  const _KPI_CORE_SENTIMENT = ["a_sentiment", "cross_market", "fear_greed"];
  const _KPI_BASE_ORDER = {
    a_width_up_count: 1, a_width_down_count: 2, a_width_zt_count: 3, a_width_dt_count: 4,
    a_amount: 6, a_volume_ratio: 7, a_sentiment: 8, cross_market: 9, fear_greed: 10, a_fund_margin: 11, a_fund_north: 12,
    a_width_zhaban_rate: 13, a_width_fengban_rate: 14, a_fund_main: 15, a_turnover_mean: 16, a_turnover_median: 17,
    a_turnover_p90: 18, a_turnover_p10: 19, a_turnover_gt5_pct: 20,
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
    const tagCls = k.tag === "冰点" ? "freeze" : k.tag === "过热" ? "overheat" : k.disabled ? "disabled" : "stale";
    const tagHtml = k.tag ? ` <span class="tag ${tagCls}">${k.tag}</span>` : "";
    const sentTag = (k.id === "a_sentiment" || k.id === "cross_market") && !k.tag ? ` <span class="sentiment-label">${sentimentTag(k.valueNum)}</span>` : "";
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
    const _kpiT1 = k.id === "a_fund_margin" || k.id === "a_fund_north" || k.id === "a_qvix_300" || k.id.startsWith("a_turnover_")
      || k.id === "gold" || k.id === "cn10y" || k.id === "a_fund_main" || k.id === "a_width_fengban_rate"; // 2026-07-23 修复:这4项实为T+1性质源(盘后次日发布),漏配误走t0分支baseline=今日致盘后误判"滞后",与"数据更新规则"弹窗标T+1不一致
    const _badge = k.disabled
      ? `<span class="card-time-badge t1-severe" data-tip="该指标采集异常/数据源中断,恢复后自动显示">🚨 异常</span>`
      : getCardTimeBadge(k.date, snap, _kpiT1 ? "t1" : "t0", _kpiT1 ? k.id : "");
    const _kpiTips = {
      a_fund_north: "北向资金=借沪深股通买A股的外资。净流入=外资净买入。2024-08起停更,保留历史。",
      a_fund_margin: "沪市融资余额=借钱买A股的杠杆资金。增加=杠杆做多情绪升。T+1。",
      a_fund_main: "主力净流入=大单资金净买入。正值=主力流入做多。",
      a_amount: "沪深京A股成交额。放量=交投活跃,缩量=清淡。",
      a_volume_ratio: "当日成交额/前5日均量。>1.5倍放量,<0.7倍缩量。",
      fear_greed: "综合5类市场情绪等权算的0-100温度计。≤25极度恐惧、≥75极度贪婪。作逆向参考。",
      a_sentiment: "6项A股指标加权算的0-100情绪分。≤20冰点、≥80过热。",
      cross_market: "A股+港股+全球等多维度等权均值0-100。看跨市场整体冷热。",
      sentiment_sz50: "该指数RSI+涨跌幅等权算的0-100情绪温度计(等权,非加权)。≤20冰点≥80过热。比A股综合情绪分更聚焦单只指数。",
      sentiment_hs300: "该指数RSI+涨跌幅等权算的0-100情绪温度计(等权,非加权)。≤20冰点≥80过热。比A股综合情绪分更聚焦单只指数。",
      sentiment_csi500: "该指数RSI+涨跌幅等权算的0-100情绪温度计(等权,非加权)。≤20冰点≥80过热。比A股综合情绪分更聚焦单只指数。",
      sentiment_csi1000: "该指数RSI+涨跌幅等权算的0-100情绪温度计(等权,非加权)。≤20冰点≥80过热。比A股综合情绪分更聚焦单只指数。",
      sentiment_cyb: "该指数RSI+涨跌幅等权算的0-100情绪温度计(等权,非加权)。≤20冰点≥80过热。比A股综合情绪分更聚焦单只指数。",
      sentiment_kc50: "该指数RSI+涨跌幅等权算的0-100情绪温度计(等权,非加权)。≤20冰点≥80过热。比A股综合情绪分更聚焦单只指数。",
      a_width_zt_count: "收盘仍封死涨停的股票数,多=追涨情绪强。",
      a_width_dt_count: "收盘仍封死跌停的股票数,多=恐慌抛售强。",
      a_width_zhaban_rate: "当日曾涨停但收盘未封住的比例,高=封板资金不稳。",
      gold: "沪金现货价,避险资产,恐慌时常涨。",
      cn10y: "10年期国债收益率=无风险利率基准,上行=资金偏紧。",
      a_qvix_300: "沪深300期权隐含波动率,类似美国VIX,高=预期大波动。",
      lhb_count: "当日上龙虎榜的个股数,多=游资活跃。",
      a_width_zb_count: "炸板数=收盘未封住的涨停数。高=打板情绪转弱。",
      a_width_seal_rate: "封板率=涨停/(涨停+炸板)。高=打板成功率高。",
      a_width_fengban_rate: "封板率=1-炸板率。高=打板成功率高、封板资金强。",
      a_turnover_mean: "全市场换手率均值。高=交投活跃。",
      a_turnover_median: "换手率中位数。比均值抗极端值,反映典型活跃度。",
      a_turnover_p90: "换手率90分位。最活跃的10%个股换手水平。",
      a_turnover_p10: "换手率10分位。最不活跃的10%个股换手水平。",
      a_turnover_gt5_pct: "换手率>5%家数占比。高=市场活跃面广。",
    };
    const _widthTip = _kpiTips[k.id] ? termTip(_kpiTips[k.id]) : (k.id === "a_width_up_count" || k.id === "a_width_down_count") ? termTip(_WIDTH_CALIBER_TIP) : "";
    const _hasHist = !!KPI_HISTORY_SOURCE[k.id];
    const _disabledTip = k.disabled ? termTip("该指标当前采集异常（数据源中断），暂无数据。恢复后自动显示。") : "";
    // 源端停更水印：半透明"数据停更"叠在卡片中部,不遮蔽数值(pointer-events:none 点击穿透到卡片)
    const _staleWm = k.stale ? '<span class="stale-watermark">数据停更</span>' : "";
    cards.innerHTML += `<div class="card kpi${_badge ? " has-time-badge" : ""}${_hasHist ? " kpi-clickable" : ""}${k.disabled ? " kpi-disabled" : ""}${k.stale ? " kpi-stale" : ""}" data-kpi-key="${k.id}"${_hasHist ? ` data-kpi-id="${k.id}"` : ""}>${_badge}${_staleWm}<div class="card-title" title="${k.title}">${k.title}${_widthTip}${_disabledTip}</div><div class="card-value"><span class="cv-val">${valueHtml}</span><span class="cv-tags">${tagHtml}${sentTag}${fgTag}</span></div><div class="card-sub" title="${sub}">${sub}</div></div>`;
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
    cards.querySelectorAll(".card.kpi:not(.kpi-disabled)").forEach(c => { c.draggable = true; });
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
          { lte: 25, color: "#42a5f5" },        // 冰点 蓝(冰色,与热力图一致)
          { gt: 25, lte: 40, color: "#4fc3f7" }, // 偏冷 浅蓝
          { gt: 40, lte: 60, color: "#86909c" }, // 中性 灰
          { gt: 60, lte: 75, color: "#e6a23c" }, // 偏热 橙
          { gt: 75, color: "#e6492e" },          // 过热 红(热色,与热力图一致)
        ],
        dimension: 1,
      },
    }, null, colA1);
    if (fgChart) {
      // 冰点(≤25)/过热(≥75)阈值虚线（与情绪温度tab恐贪图一致）
      fgChart.setOption({ series: [{ markLine: {
        silent: true, symbol: "none", lineStyle: { type: "dashed", width: 1.5 },
        data: [
          { yAxis: 25, lineStyle: { color: "#42a5f5" }, label: { formatter: "冰点", color: "#42a5f5", position: "insideStartTop", fontSize: 10 } },
          { yAxis: 75, lineStyle: { color: "#e6492e" }, label: { formatter: "过热", color: "#e6492e", position: "insideStartTop", fontSize: 10 } },
        ],
      } }] });
      addCardTimeBadge(fgChart.getDom().parentElement, fg6.length ? fg6[fg6.length - 1].date : "", snap, "t0");
    }
  }

  // 左列：恐贪分项条（8 项情绪分等权 = 恐贪指数；分项解释总分构成，紧贴恐贪折线）
  {
    const _FG_DIM_IDS = [
      "a_sentiment", "cross_market",
      "sentiment_sz50", "sentiment_hs300", "sentiment_csi500",
      "sentiment_csi1000", "sentiment_cyb", "sentiment_kc50",
    ];
    const _sc = (r.today && r.today.scores) || {};
    const _fgTotal = _sc.fear_greed && _sc.fear_greed.value != null ? _sc.fear_greed.value : null;
    const _rows = _FG_DIM_IDS.map((id) => {
      const s = _sc[id];
      if (!s || s.value == null) return null;
      return { id, name: indexIdToName(id), value: s.value, freeze: !!(s.is_freeze || s.value < 20), overheat: !!(s.is_overheat || s.value > 80) };
    }).filter(Boolean).sort((a, b) => a.value - b.value); // 升序：最恐惧(低分)在上
    if (_rows.length) {
      const fgDimCard = document.createElement("div");
      fgDimCard.className = "chart-card fg-dim-card";
      fgDimCard.id = "fg-dim-ov";
      const totalTxt = _fgTotal != null ? ` · 总分 ${_fgTotal.toFixed(1)}` : "";
      let html = '<h3>🌡️ 恐贪分项' + termTip("恐贪指数由以下8项情绪分等权平均合成(2项综合+6项宽基)。分项条解释总分为何是当前值--哪几项拖累(冰点)/哪几项偏高。❄️=冰点(≤20)，🔥=过热(≥80)。") + '<span class="fg-dim-total">8 项等权' + totalTxt + '</span></h3>';
      html += '<div class="fg-dim-rows">';
      for (const row of _rows) {
        const col = fearGreedColor(row.value);
        const icon = row.freeze ? ' ❄️' : row.overheat ? ' 🔥' : '';
        html += '<div class="fg-dim-row">' +
          '<span class="fg-dim-name">' + row.name + icon + '</span>' +
          '<span class="fg-dim-track"><span class="fg-dim-fill" style="width:' + row.value.toFixed(1) + '%;background:' + col + '"></span></span>' +
          '<span class="fg-dim-val" style="color:' + col + '">' + row.value.toFixed(1) + '</span>' +
          '</div>';
      }
      html += '</div>';
      fgDimCard.innerHTML = html;
      colA1.appendChild(fgDimCard);
    }
  }

  // 左列：A股综合情绪分折线（近 6 月）
  if (r.a_sentiment_6m && r.a_sentiment_6m.length) {
    const as6 = r.a_sentiment_6m.map((d) => ({ date: d.date, value: d.value }));
    const asChart = lineChart("A股综合情绪分（近 6 月）" + termTip("综合多项指标算的情绪温度计0-100，≤20冰点≥80过热") + latestSuffix(as6), as6, {
      visualMap: {
        show: false,
        pieces: [
          { lte: 20, color: "#42a5f5" },
          { gt: 20, lte: 40, color: "#4fc3f7" },
          { gt: 40, lte: 60, color: "#86909c" },
          { gt: 60, lte: 80, color: "#e6a23c" },
          { gt: 80, color: "#e6492e" },
        ],
        dimension: 1,
      },
    }, null, colA1);
    if (asChart) {
      // 冰点(≤20)/过热(≥80)阈值虚线（情绪分口径，与情绪温度tab一致）
      asChart.setOption({ series: [{ markLine: {
        silent: true, symbol: "none", lineStyle: { type: "dashed", width: 1.5 },
        data: [
          { yAxis: 20, lineStyle: { color: "#42a5f5" }, label: { formatter: "20", color: "#42a5f5", position: "insideStartTop", fontSize: 10 } },
          { yAxis: 80, lineStyle: { color: "#e6492e" }, label: { formatter: "80", color: "#e6492e", position: "insideStartTop", fontSize: 10 } },
        ],
      } }] });
      addCardTimeBadge(asChart.getDom().parentElement, as6.length ? as6[as6.length - 1].date : "", snap, "t0");
      // 图表高度减一点(300->250)，给下方历史位置3行腾空间
      const _ovChartDiv = asChart.getDom();
      if (_ovChartDiv) { _ovChartDiv.style.height = '250px'; asChart.resize(); }
      // 历史位置3行(候选2/3/4)合并进本卡图表下方：overview.json 无1年时序，独立 fetch 近1年+6月
      appendHistoryPos(asChart.getDom().parentElement);
    }
  }

  // 右列：冰点日卡片（近120日，按日分组4个/行）
  const freezeCard = document.createElement("div");
  freezeCard.className = "chart-card";
  freezeCard.innerHTML = _renderSignalGrid(r.recent_freeze, r.date, "近期冰点日（近 120 日）" + termTip("近120日情绪冰点日(恐贪指数<20)，常对应阶段性底部"), "freeze", "无近期冰点日");
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
  sigCard.innerHTML = _renderSignalGrid(r.signals_today, r.date, "近期技术分析参考点（近 15 交易日 · 今日高亮）" + signalHelpTip("6色技术信号参考（点击❓查看6色信号详细解释）"), "signal", "近期无技术分析参考点");
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
      termTip("宽基ETF份额变动跟踪;观察份额增减与成交放量。进=份额增+z>2+放量(红)/出=份额减+z<-2+放量(绿)/量=成交额>5日均2倍(橙)。共振=进/出≥2只、量≥3只宽基同日同步异动。ETF份额T+1发布，数据日期可能为T-1。点击下方信号chip查看当日明细。") + "</h3>" +
      summaryHtml +
      '<div class="signal-grid nt-signal-grid">' + _renderNtSignalList(rc && rc.daily ? rc.daily : [], nt.date) + '</div>';
    addCardTimeBadge(ntCard, nt.date, snap, "t1", "etf_date");
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
      termTip("宽基ETF份额变动跟踪;观察份额增减与成交放量。ETF份额T+1发布。") + "</h3>" +
      '<div class="empty-note">近期无汪汪队信号</div>';
    if (nt && nt.date) addCardTimeBadge(ntCard, nt.date, snap, "t1", "etf_date");
  }
  colA2.appendChild(ntCard);

  // 汪汪队首次解释：复用 showIntroOnce 弹窗,localStorage[nt_intro_done] 标记后不再弹。
  // 加 _ntIntroScheduled 守卫,确保整页生命周期只调度一次(避免 tab 反复切换重复 setTimeout)。
  if (!window._ntIntroScheduled) {
    window._ntIntroScheduled = true;
    showIntroOnce({
      key: 'nt_intro_done',
      title: '🐶 汪汪队是什么',
      delay: 2000,
      steps: [
        {
          icon: '🐶', title: '汪汪队是什么',
          body: '<b>汪汪队</b>=宽基 ETF 份额变动跟踪,观察份额增减与成交放量。追踪 12 只宽基 ETF(上证50/沪深300/中证500/1000/创业板/科创50)的份额变动 + 成交额放量。<b>ETF 份额 T+1 发布</b>,数据日期可能为 T-1。'
        },
        {
          icon: '🎨', title: '信号怎么看',
          body: '<b>进</b>=份额增+z>2+放量(<span style="color:#e6492e">红</span>) / <b>出</b>=份额减+z<-2+放量(<span style="color:#2e8b57">绿</span>) / <b>量</b>=成交额>5日均2倍(<span style="color:#ff9800">橙</span>)。<b>共振</b>=进/出≥2只、量≥3只宽基同日同步异动。点击下方信号 chip 查看当日明细。'
        }
      ]
    });
  }


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
        pieces: [
          { lte: 20, color: "#42a5f5" },
          { gt: 20, lte: 40, color: "#4fc3f7" },
          { gt: 40, lte: 60, color: "#86909c" },
          { gt: 60, lte: 80, color: "#e6a23c" },
          { gt: 80, color: "#e6492e" },
        ],
        dimension: 1,
      },
    }, null, colB1);
    if (cmChart) {
      // 冰点(≤20)/过热(≥80)阈值虚线（情绪分口径，与情绪温度tab一致）
      cmChart.setOption({ series: [{ markLine: {
        silent: true, symbol: "none", lineStyle: { type: "dashed", width: 1.5 },
        data: [
          { yAxis: 20, lineStyle: { color: "#42a5f5" }, label: { formatter: "20", color: "#42a5f5", position: "insideStartTop", fontSize: 10 } },
          { yAxis: 80, lineStyle: { color: "#e6492e" }, label: { formatter: "80", color: "#e6492e", position: "insideStartTop", fontSize: 10 } },
        ],
      } }] });
      addCardTimeBadge(cmChart.getDom().parentElement, cm6.length ? cm6[cm6.length - 1].date : "", snap, "t0");
    }
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
        { name: "腾落线", data: adData.map(d => ({ date: d.date, value: d.ad_line })), label: "腾落线" },
        { name: "腾落线MA20", data: adData.map(d => ({ date: d.date, value: d.ad_line_ma20 })), label: "MA20" },
      ];
      const adc = mkCard("📊 腾落线（AD Line）" + termTip("腾落线=累积每日上涨家数-下跌家数。持续上升=广度健康(多数股票涨),与指数背离常预示拐点。累计值绝对值无意义,看趋势。") + latestSuffixMulti(adSeries), 300, null, colC1);
      appendPlainTip(adc, "AD线持续上行=多数股票在涨，大盘涨势健康");
      addCardTimeBadge(adc.getDom().parentElement, adDates.length ? adDates[adDates.length - 1] : "", snap, "t0");
      adc.setOption(withTheme({
        tooltip: { trigger: "axis" },
        legend: { top: 0, data: ["涨跌家数比", "腾落线", "腾落线MA20"] },
        grid: { left: 55, right: 55, top: 35, bottom: 35 },
        xAxis: { type: "category", data: adDates },
        yAxis: [
          { type: "value", name: "涨跌比", axisLabel: { formatter: v => v.toFixed(2) }, splitLine: { show: false } },
          { type: "value", name: "腾落线" },
        ],
        dataZoom: dzOpts(),
        series: [
          { name: "涨跌家数比", type: "bar", yAxisIndex: 0, data: ratioData.map((v, i) => ({ value: v, itemStyle: { color: ratioColors[i] } })), barWidth: "60%" },
          { name: "腾落线", type: "line", yAxisIndex: 1, symbol: "none", smooth: true, data: adLineData, lineStyle: { color: "#5b8ff9", width: 1.5 } },
          { name: "腾落线MA20", type: "line", yAxisIndex: 1, symbol: "none", smooth: true, data: adMA20, lineStyle: { color: "#f6bd16", width: 1.5, type: "dashed" } },
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
        { name: "净新高", data: nhlData.map(d => ({ date: d.date, value: d.nhnl_52w })), label: "净新高" },
      ];
      const nhlCard = mkCard("🔬 新高新低家数（52 周）" + termTip("近52周创新高/新低的股票家数，新高多=强势新低多=弱势") + latestSuffixMulti(nhlSeries), 280, null, colC1);
      appendPlainTip(nhlCard, "新高多于新低=市场偏强；新低多于新高=市场偏弱");
      addCardTimeBadge(nhlCard.getDom().parentElement, nhlDates.length ? nhlDates[nhlDates.length - 1] : "", snap, "t0");
      nhlCard.setOption(withTheme({
        tooltip: { trigger: "axis" },
        legend: { top: 0, data: ["52周新高", "52周新低", "净新高"] },
        grid: { left: 55, right: 55, top: 35, bottom: 35 },
        xAxis: { type: "category", data: nhlDates },
        yAxis: [
          { type: "value", name: "家数", splitLine: { show: false } },
          { type: "value", name: "净新高" },
        ],
        dataZoom: dzOpts(),
        series: [
          { name: "52周新高", type: "bar", yAxisIndex: 0, data: nhlData.map(d => d.nh_52w), itemStyle: { color: "#e6492e" }, barWidth: "40%" },
          { name: "52周新低", type: "bar", yAxisIndex: 0, data: nhlData.map(d => d.nl_52w), itemStyle: { color: "#2e8b57" }, barWidth: "40%" },
          { name: "净新高", type: "line", yAxisIndex: 1, symbol: "none", smooth: true, data: nhlData.map(d => d.nhnl_52w), lineStyle: { color: "#5b8ff9", width: 1.5 } },
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
  content.insertAdjacentHTML("beforeend", '<div class="home-purpose-note">💡 <b>这板块有什么用</b>:看A股、港股、全球指数走势,叠加技术分析参考点,综合判断大盘情绪偏冷还是偏热;另追踪🐶汪汪队宽基ETF份额变动(观察份额增减与成交放量)。<b>怎么解读</b>:信号偏多通常反映情绪回暖,偏空反映转弱(历史统计参考,非操作建议);汪汪队大额净流入历史上常伴随市场低位区域,流出对应份额收缩。</div>');
  content.insertAdjacentHTML("beforeend", '<div class="tab-crosslink-note">ℹ️ 本页看指数<b>价格走势</b>+买卖点信号;想看市场<b>情绪温度</b>(恐贪指数/冰点过热热力图)-> 去<a data-goto="sentiment" role="button" tabindex="0">【情绪温度】</a></div>');
  _bindTabCrosslink(content, "sentiment");
  // 二级 tab 栏
  const subtabBar = document.createElement("div");
  subtabBar.className = "subtab-bar";
  const subtabs = [
    ["a-stock", "A股"],
    ["hk", "港股"],
    ["global", "全球"],
    ["futures", "期货"],
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
  else if (state.subtab === "futures") await renderFutures(subContent);
  else if (state.subtab === "national-team") await renderNationalTeam(subContent);
}

// ============ 期货机构净多空持仓（P0-5 独立入口，原仅嵌在情绪 tab） ============
// 渲染到传入容器（大盘 tab 的 subContent）；复用 renderFuturesSection 的全部图表/表格逻辑。
async function renderFutures(container) {
  _disposeContainerCharts(container);
  renderLoadingState(container);
  let futures;
  try {
    futures = await fetchJSON("./data/futures.json");
  } catch (e) {
    renderErrorState(container, e, () => renderFutures(container));
    return;
  }
  try { await Promise.race([fetchIntradaySnapshot(), new Promise((r) => setTimeout(r, 1500))]); } catch {}
  const snap = state.intradaySnapshot;
  container.innerHTML = "";
  container.insertAdjacentHTML("beforeend", '<div class="home-purpose-note">💡 <b>这板块有什么用</b>:看中金所股指期货机构(前20会员/中信/国君)净多空持仓变化,作市场情绪参考。<b>怎么解读</b>:机构净多空为正=偏看多、为负=偏看空;但极端值常为<strong>反向参考</strong>(极度看多可能见顶)。历史同向/逆向准确率辅助判断,均不构成未来预测。</div>');
  if (futures && futures.positions && futures.positions.length) {
    renderFuturesSection(futures, snap, container);
  } else {
    container.insertAdjacentHTML("beforeend", '<div class="empty-note">暂无期货持仓数据</div>');
  }
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
    data = await fetchJSON(dataUrl(`etf_national_team-${state.range}.json`));
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
    `<h3>🐶 汪汪队 - 宽基 ETF 资金动向 <span class="term-tip" data-tip="宽基ETF份额变动跟踪;观察份额增减与成交放量。追踪12只宽基ETF(上证50/沪深300/中证500/1000/创业板/科创50)的份额变动+成交额放量。份额异动z-score>2且放量1.5倍以上=份额扩张(红)，反之为份额收缩(绿)。注意：这是份额变动统计，无法确认具体资金来源，份额变动可能来自任何机构/大户申赎。">❓</span></h3>` +
    `<div class="nt-banner-body">追踪 12 只宽基 ETF 的<span style="color:var(--primary)">份额变动+成交额放量</span>，观察份额增减与成交放量。<b>口径声明</b>：本指标为份额变动代理统计，非真实资金席位数据，无法精确区分汇金/证金/社保/险资/公募等来源。份额变动可能来自任何机构/大户申赎，不等于特定机构操作。当季机构占比&gt;85% 时置信度×1.5（机构主导品种）。</div>`;
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
      if (!dateMap[dt]) dateMap[dt] = { date: dt, mktCap: 0, share: 0, netAdd: 0, nSurge: 0, nOutflow: 0, nVolume: 0, shareNull: false, chgNull: false, closeNull: false };
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
      if (d.close == null) dateMap[dt].closeNull = true;  // 末日close=null(T+1源行情缺)时mktCap/netAdd按0计会显"0亿元"误导,需KPI容错
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
  // 末日收盘价缺失(行情源延迟,close=null兜底0致mktCap/netAdd=0显"0亿元"误导)：KPI改显"行情待更新"
  var lastCloseMissing = last.closeNull;
  if (lastShareMissing && prev) {
    last.share = prev.share;   // 份额T+1未发布,沿用上日份额(市值已在聚合时用prevShare×当日close预估,不再整体复制prev.mktCap)
  }
  // 方案A(2026-07-22): 末日份额未发(fund_share NULL -> share_change NULL)时,
  // 用持仓市值差分预估净增持 = 当日mktCap - 前日mktCap(复用已估mktCap,无需份额),
  // 加 netAddEstimated 标记,前端显"预估"标注区分真实净增持(份额已发时用真实值)。
  // 语义差异:真实netAdd=Σ(份额变动×价),预估netAdd=市值差分=份额变动×价+份额不变×价变动(含价格波动)。
  if (lastChgMissing) {
    if (prev && last.mktCap != null && prev.mktCap != null) {
      last.netAdd = last.mktCap - prev.mktCap;
      last.netAddEstimated = true;  // 预估标记,KPI/图3显"预估"标注
    } else {
      last.netAdd = null;  // 无前日数据或close缺失,无法预估,显"份额待公布"
    }
  }
  if (lastCloseMissing) {
    last.mktCap = null;   // 末日close=null时不显"0亿元",KPI改显"行情待更新"
    if (last.netAdd != null) {  // close=null时预估也不准(市值差分依赖close),同样标null
      last.netAdd = null;
      last.netAddEstimated = false;
    }
  }
  // cum20 求和用 (d.netAdd || 0),末日 close=null 时 last.netAdd 已置 null 不会误计0
  var cum20 = series.slice(-20).reduce(function (s, d) { return s + (d.netAdd || 0); }, 0);

  // ▼ T+1 提示行：让用户知道国家队份额为何停 T-1 ▼
  var t1Hint = document.createElement("div");
  t1Hint.className = "nt-t1-hint";
  t1Hint.textContent = "⏳ ETF份额数据为T+1：上交所/深交所盘后次日发布,实测源端常晚于22:00,当日20:07采集通常只到T-1,次日20:07后补全当日";
  if (lastShareMissing) {
    var netEstTxt = (last.netAddEstimated)
      ? "净增持额按持仓市值差分预估(含价格波动,待份额公布后更新真实值)"
      : "净增持额待公布";
    t1Hint.textContent += "。⚠ 当日(" + fmtDate(last.date) + ")份额尚未发布,市值按上日份额×当日收盘价预估,份额沿用上日," + netEstTxt;
  }
  if (lastCloseMissing) {
    t1Hint.textContent += "。⚠ 当日(" + fmtDate(last.date) + ")收盘价缺失(行情源延迟),合计市值/净增持额暂显\"行情待更新\",下一采集时点补全";
  }
  container.appendChild(t1Hint);

  // ▼ 第0层 KPI 大字：国家队总市值 + 今日净增持 + 近20日累计净增持 ▼
  var kpi = document.createElement("div");
  kpi.className = "nt-total-kpi";
  // close=null 时 netAdd 已置 null,优先显"行情待更新"(行情源延迟),其次 lastChgMissing 显"份额待公布"(T+1份额延迟)
  var netCls = (last.netAdd == null) ? "" : (last.netAdd >= 0 ? "nt-up" : "nt-down");
  var netSign = (last.netAdd == null) ? "" : (last.netAdd >= 0 ? "+" : "");
  var netValHtml;
  if (lastCloseMissing) {
    netValHtml = '<div class="nt-tk-val" style="color:var(--text-3)">行情待更新</div>';
  } else if (last.netAdd == null) {
    netValHtml = '<div class="nt-tk-val" style="color:var(--text-3)">份额待公布·' + _ntShareReplenishTxt(last.date) + '补全</div>';
  } else if (last.netAddEstimated) {
    // 方案A: 份额未发,按市值差分预估,显"预估"标注(橙色⚠,区分真实净增持)
    netValHtml = '<div class="nt-tk-val ' + netCls + '">' + netSign + last.netAdd.toFixed(2) + ' <span class="nt-tk-unit">亿元</span> <span style="font-size:12px;color:#ff9800">⚠预估(' + _ntShareReplenishTxt(last.date) + '补全)</span></div>';
  } else {
    netValHtml = '<div class="nt-tk-val ' + netCls + '">' + netSign + last.netAdd.toFixed(2) + ' <span class="nt-tk-unit">亿元</span></div>';
  }
  var cumCls = cum20 >= 0 ? "nt-up" : "nt-down";
  var cumSign = cum20 >= 0 ? "+" : "";
  // 合计市值 KPI：close=null 时 last.mktCap 已置 null,显"行情待更新"避免"0亿元"误导
  var mktCapValHtml;
  if (lastCloseMissing) {
    mktCapValHtml = '<div class="nt-tk-val" style="color:var(--text-3)">行情待更新</div>';
  } else {
    mktCapValHtml = '<div class="nt-tk-val">' + last.mktCap.toFixed(0) + ' <span class="nt-tk-unit">亿元</span>' + (lastShareMissing ? ' <span style="font-size:12px;color:#ff9800">份额待公布·按上日份额预估(' + _ntShareReplenishTxt(last.date) + '补全)</span>' : '') + '</div>';
  }
  kpi.innerHTML =
    '<div class="nt-tk-item"><div class="nt-tk-label">国家队合计持仓市值' + termTip("12只宽基ETF当日份额×收盘价合计(亿元)。份额是交易所公布的硬数据，市值随价波动。") + '<span class="chart-latest"> · 截至 ' + fmtDate(last.date) + '</span></div>' + mktCapValHtml + '</div>' +
    '<div class="nt-tk-item"><div class="nt-tk-label">净增持额' + (last.netAddEstimated ? '（预估）' : '') + termTip("Σ(各ETF今日份额变动×今日价)。正值=今日净流入，负值=净流出。份额变动是硬数据不受价格波动干扰。" + (last.netAddEstimated ? "当日份额未公布,暂用持仓市值差分预估(含价格波动),待份额公布后更新真实值。" : "")) + '<span class="chart-latest"> · ' + fmtDate(last.date) + '</span></div>' + netValHtml + '</div>' +
    '<div class="nt-tk-item"><div class="nt-tk-label">近20日累计净增持' + termTip("Σ(近20日各ETF每日份额变动×当日价)。看近一个月份额持续扩张还是收缩。") + '<span class="chart-latest"> · 截至 ' + fmtDate(last.date) + '</span></div><div class="nt-tk-val ' + cumCls + '">' + cumSign + cum20.toFixed(2) + ' <span class="nt-tk-unit">亿元</span>' + (lastShareMissing ? ' <span style="font-size:12px;color:#ff9800">份额待公布·按上日份额预估(' + _ntShareReplenishTxt(last.date) + '补全)</span>' : '') + '</div></div>';
  container.appendChild(kpi);

  var mktData = series.map(function (d) { return { date: d.date, value: d.mktCap == null ? null : +d.mktCap.toFixed(2) }; });
  var shareData = series.map(function (d) { return { date: d.date, value: +d.share.toFixed(2) }; });
  var netData = series.map(function (d) { return { date: d.date, value: d.netAdd == null ? null : +d.netAdd.toFixed(2) }; });
  // 末日份额待公布标记(图1/图2标题追加,提示末日值为上一日估算)；lastDate 3图共享(8位YYYYMMDD)
  var missingSuffix = lastShareMissing ? '<span class="chart-latest" style="color:#ff9800">· 末日份额待公布(市值按上日份额预估,' + _ntShareReplenishTxt(last.date) + '补)</span>' : '';
  if (lastCloseMissing) missingSuffix += '<span class="chart-latest" style="color:#ff9800">· 末日收盘价待更新(行情源延迟)</span>';
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
      mktMarks.push({ coord: [d.date, mktY], value: sig.label, itemStyle: { color: sig.color }, label: { color: _autoLabelColor(sig.color) } });
      shareMarks.push({ coord: [d.date, shareY], value: sig.label, itemStyle: { color: sig.color }, label: { color: _autoLabelColor(sig.color) } });
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
      markPoint: { symbol: "pin", symbolSize: 40, label: { fontSize: 11, color: cssVar("--text-1") }, data: mktMarks },
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
      markPoint: { symbol: "pin", symbolSize: 40, label: { fontSize: 11, color: cssVar("--text-1") }, data: shareMarks },
    }],
  }));

  // 图3：每日净增持额柱状（红流入绿流出，末日份额待公布则末日柱不画）
  // 方案A: 末日份额未发时,预估柱画出(橙色),title 标"末日预估(份额待公布)";无法预估时标"末日待公布"
  var c3EstSuffix = lastChgMissing
    ? (last.netAddEstimated
      ? '<span class="chart-latest" style="color:#ff9800">· 末日预估(份额待公布)</span>'
      : '<span class="chart-latest" style="color:#ff9800">· 末日待公布</span>')
    : '';
  var c3 = mkCard("📉 每日净增持额（近" + dates.length + "日）" + termTip("每日Σ(份额变动×当日价)柱状。红柱=当日净流入(份额扩张)，绿柱=净流出(份额收缩)。末日份额未公布时按持仓市值差分预估(橙色柱)。") + c3EstSuffix, 300, null, ntGrid);
  addCardTimeBadge(c3.getDom().parentElement, lastDate, snap, "t1", "etf_date");
  c3.setOption(withTheme({
    tooltip: { trigger: "axis", formatter: function (p) { var v = p[0]; var dt = v.axisValue; if (v.value == null) return fmtDate(dt) + "<br/>份额待公布"; var est = (dt === last.date && last.netAddEstimated); return fmtDate(dt) + "<br/>" + (v.value >= 0 ? "+" : "") + (+v.value).toFixed(2) + " 亿元" + (est ? "<br/>⚠预估(份额未公布,按市值差分)" : ""); } },
    grid: { left: 55, right: 20, top: 30, bottom: 50 },
    xAxis: { type: "category", data: dates },
    yAxis: { type: "value", name: "亿元" },
    dataZoom: dzOpts(),
    series: [{
      name: "净增持额", type: "bar", data: netData.map(function (d) { return d.value; }),
      itemStyle: { color: function (p) { var dt = dates[p.dataIndex]; var isEst = (dt === last.date && last.netAddEstimated); if (p.value == null) return "#999"; if (isEst) return "rgba(255,152,0,0.75)"; return p.value >= 0 ? "#e6492e" : "#2e8b57"; } },
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
      shareMarks.push({ coord: [d.date, d.fund_share_yi], value: "进", itemStyle: { color: "#e6492e" }, label: { color: _autoLabelColor("#e6492e") } });
    if (d.signals.find((s) => s.type === "share_outflow"))
      shareMarks.push({ coord: [d.date, d.fund_share_yi], value: "出", itemStyle: { color: "#2e8b57" }, label: { color: _autoLabelColor("#2e8b57") } });
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
      markPoint: { symbol: "pin", symbolSize: 36, label: { fontSize: 11, color: cssVar("--text-1") }, data: shareMarks },
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
      volMarks.push({ coord: [d.date, d.close], value: "量", itemStyle: { color: "#ff9800" }, label: { color: _autoLabelColor("#ff9800") } });
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
        markPoint: { symbol: "pin", symbolSize: 34, label: { fontSize: 11, color: cssVar("--text-1") }, data: volMarks } },
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
    r = await fetchJSON(dataUrl(`a-stock-${state.range}.json`));
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
    "涨停/跌停/连板/炸板率": ["a_width_zt_count", "a_width_dt_count", "a_width_max_lianban", "a_width_zhaban_rate"],
    "市场宽度（涨跌家数）": ["a_width_up_count", "a_width_down_count"],
    "资金面": ["a_fund_north", "a_fund_margin", "a_fund_main", "a_amount"],
    "情绪指数（波指/换手率）": ["a_qvix_300", "a_qvix_1000", "a_turnover_rate"],
    "炸板率/封板率/打板溢价": ["a_width_seal_rate", "a_width_fengban_rate", "a_width_daban_premium"],
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
    "涨停/跌停/连板/炸板率": { a_width_zt_count: "涨停", a_width_dt_count: "跌停", a_width_max_lianban: "连板", a_width_zhaban_rate: "炸板率" },
    "市场宽度（涨跌家数）": { a_width_up_count: "涨", a_width_down_count: "跌" },
    "资金面": { a_fund_north: "北向", a_fund_margin: "融资", a_fund_main: "主力", a_amount: "成交" },
    "炸板率/封板率/打板溢价": { a_width_seal_rate: "封板率", a_width_fengban_rate: "封板", a_width_daban_premium: "打板" },
    "情绪指数（波指/换手率）": { a_qvix_300: "波指300", a_qvix_1000: "波指50ETF", a_turnover_rate: "换手" },
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
    const raw = await fetchJSON(`https://ssd.fx8.store/index/${id}-all.json`);
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
    r = await fetchJSON(dataUrl(`hk-${state.range}.json`));
  } catch (e) {
    renderErrorState(container, e, () => renderHK(container));
    return;
  }
  container.innerHTML = "";
  // 等快照就绪，注入港股实时数据 + 供走势卡角标判断盘中/收盘状态
  try { await Promise.race([fetchIntradaySnapshot(), new Promise((r) => setTimeout(r, 1500))]); } catch {}
  const snap = state.intradaySnapshot;
  container.insertAdjacentHTML("beforeend", '<div class="home-purpose-note">💡 <b>这板块有什么用</b>:看港股(恒生/恒生科技/国企)走势+技术分析参考点,叠加港股通南向资金(内地资金买港股的通道,净流入=看好港股)。另含港股板块指数。</div>');
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
    const raw = await fetchJSON(`https://ssd.fx8.store/index/${id}-all.json`);
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
  // 显式设 loading：fetch + 盘中快照等待期间保持 loading，避免点击后空白无反馈（对齐 renderFutures 模式）
  renderLoadingState(container, "加载全球数据…");
  let r;
  try {
    r = await fetchJSON(dataUrl(`global-${state.range}.json`));
  } catch (e) {
    renderErrorState(container, e, () => renderGlobal(container));
    return;
  }
  // 拉取盘中快照，供走势卡角标判断盘中/收盘状态（1.5s 超时兜底，不阻塞渲染）
  try { await Promise.race([fetchIntradaySnapshot(), new Promise((r) => setTimeout(r, 1500))]); } catch {}
  const snap = state.intradaySnapshot;
  container.innerHTML = "";  // 清 loading 开始渲染
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
    // 9 个全球指数 sig 并发 fetch 期间显示内部 loading（避免 indices-grid 空白，grid-column:1/-1 占满整行）
    const gridLoading = document.createElement("div");
    gridLoading.className = "loading loading--active";
    gridLoading.style.gridColumn = "1 / -1";
    gridLoading.innerHTML = '<span class="loading__spinner"></span><span class="loading__text">加载指数图表…</span>';
    cardGrid.appendChild(gridLoading);
    const sigResults = await Promise.all(
      idxEntries.map(([id]) => fetchJSON(`https://ssd.fx8.store/index/${id}-all.json`).catch(() => null))
    );
    gridLoading.remove();
    idxEntries.forEach(([id, idx], i) => {
      const sig = sigResults[i] || { signals: [], stats: {} };
      const sigs = filterSignalsByRange(sig.signals, idx.data);
      if (idx.data && idx.data.length) {
        const chart = indexChart(idx.name, idx.data, sigs, sig.stats, idx.strategy, cardGrid, charts, id);
        if (chart) {
          addCardTimeBadge(chart.getDom().parentElement, idx.data.length ? idx.data[idx.data.length - 1].date : "", snap, id && id.startsWith("us_") ? "t1" : "t0", id && id.startsWith("us_") ? "us_dji_date" : "");
          // 标题❓策略弹窗（2026-07-20 方案B1）：h3 末尾追加❓，hover 一句话摘要 + click 弹该指数6类策略详情 modal
          _appendStrategyHint(chart.getDom().parentElement, id, idx.strategy);
          // C7 P4 market 融合:全球指数卡下 append 紧凑分数卡
          _attachMarketScoreCard(id, idx.name, chart.getDom().parentElement);
        }
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
    a_qvix_1000: "中国波指(50ETF期权)",
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
    a_qvix_300: "中国波指(300ETF期权隐含波动率),类似美股VIX恐慌指数。飙升=市场恐慌预期升,低位=情绪平稳。T+1。",
    a_qvix_1000: "中国波指(50ETF期权隐含波动率),类似美股VIX恐慌指数。飙升=市场恐慌预期升,低位=情绪平稳。T+1。",
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
        // 标题❓策略弹窗（2026-07-20 方案B1）：global 指标卡 h3 末尾追加❓（如 usdcnh skip买/cn_us_spread skip卖/usdcnh 2σ 去趋势 等 per-index 差异化策略）
        _appendStrategyHint(chart.getDom().parentElement, id, extrasStrategy[id]);
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
  north: "北向资金",
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

// 历史位置3行(候选2/3/4)：独立 fetch 近1年+6月，append 到 container 图表下方，不受 state.range 切换影响
// indexId 指定取哪个序列(默认 a_sentiment)；细分指数(csi1000/cyb/...)也复用，使其与 a股情绪分卡片等高对齐。
// 用 fetchJSON(in-flight 去重+5min 缓存)：多卡同时调用只发 2 个实际请求。
function appendHistoryPos(container, indexId = "a_sentiment") {
  const box = document.createElement("div");
  box.className = "hist-pos-merged";
  box.innerHTML = '<div class="hist-pos-loading">📊 历史位置加载中…</div>';
  container.appendChild(box);
  (async () => {
    try {
      const [r1, r6] = await Promise.all([
        fetchJSON('./data/sentiment-1y.json'),
        fetchJSON('./data/sentiment-6m.json'),
      ]);
      const a1 = (r1[indexId] || []).filter(x => x.value != null);
      const a6 = (r6[indexId] || []).filter(x => x.value != null);
      if (!a1.length) { box.innerHTML = '<div class="hist-pos-loading">暂无数据</div>'; return; }
      const cur = a1[a1.length - 1].value;
      // 候选2: 近1年分位 = (小于当前值的条数/总数)*100%
      const less = a1.filter(x => x.value < cur).length;
      const pct = less / a1.length * 100;
      const tag = pct < 33.34 ? '偏冷' : pct > 66.66 ? '偏热' : '中性';
      const tagColor = pct < 33.34 ? 'var(--freeze,#2e8b57)' : pct > 66.66 ? 'var(--overheat,#e6492e)' : 'var(--text-2)';
      const ptrPos = Math.max(0, Math.min(100, cur)); // 当前值在0-100条上的位置
      // 候选3: 近6月极值
      const mn = a6.length ? a6.reduce((m, x) => x.value < m.value ? x : m, a6[0]) : null;
      const mx = a6.length ? a6.reduce((m, x) => x.value > m.value ? x : m, a6[0]) : null;
      const distFreeze = Math.max(0, cur - 20);   // 当前值向下到冰点20的距离(已在冰点区则为0)
      const distHeat = Math.max(0, 80 - cur);      // 当前值向上到过热80的距离(已在过热区则为0)
      // 候选4: 近1年极端触发统计
      const freezes = a1.filter(x => x.is_freeze === 1);
      const heats = a1.filter(x => x.is_overheat === 1);
      const fmtD = s => s && s.length === 8 ? s.slice(4, 6) + '-' + s.slice(6, 8) : (s || '');
      const fLast = freezes.length ? freezes[freezes.length - 1].date : '';
      const hLast = heats.length ? heats[heats.length - 1].date : '';
      box.innerHTML =
        '<div class="hist-pos-headline">当前 <b>' + cur.toFixed(1) + '</b> · 近1年 <b style="color:' + tagColor + '">' + pct.toFixed(1) + '%分位(' + tag + ')</b></div>' +
        '<div class="hist-pos-body">' +
          '<div class="hist-pos-row hist-pos-row-bar">' +
            '<div class="hist-row-label">历史位置(近1年' + a1.length + '日)</div>' +
            '<div class="hist-pos-bar-wrap">' +
              '<div class="hist-pos-track">' +
                '<span class="hist-zone hist-zone-freeze" style="width:20%"></span>' +
                '<span class="hist-zone hist-zone-heat" style="left:80%;width:20%"></span>' +
                '<span class="hist-pos-fill" style="width:' + pct.toFixed(1) + '%"></span>' +
                '<span class="hist-pos-pointer" style="left:' + ptrPos.toFixed(1) + '%">▼</span>' +
              '</div>' +
              '<div class="hist-pos-scale">' +
                '<span>0</span><span class="hist-tick hist-tick-freeze">冰点20</span><span>40</span><span class="hist-tick hist-tick-heat">过热80</span><span>100</span>' +
              '</div>' +
            '</div>' +
          '</div>' +
          '<div class="hist-pos-row hist-extremes">' +
            '<span class="hist-row-label">近6月极值</span>' +
            '<span class="hist-ext-item">最低 <b>' + (mn ? mn.value.toFixed(1) : '-') + '</b><span class="hist-ext-date">(' + (mn ? fmtD(mn.date) : '') + ')</span></span>' +
            '<span class="hist-ext-item">最高 <b>' + (mx ? mx.value.toFixed(1) : '-') + '</b><span class="hist-ext-date">(' + (mx ? fmtD(mx.date) : '') + ')</span></span>' +
            '<span class="hist-ext-item">距冰点 <b>' + distFreeze.toFixed(1) + '</b></span>' +
            '<span class="hist-ext-item">距过热 <b>' + distHeat.toFixed(1) + '</b></span>' +
          '</div>' +
          '<div class="hist-pos-row hist-triggers">' +
            '<span class="hist-row-label">极端触发(近1年)</span>' +
            '<span class="hist-trig hist-trig-freeze">❄️冰点(≤20) <b>' + freezes.length + '</b>次 最近 <b>' + (fLast ? fmtD(fLast) : '-') + '</b></span>' +
            '<span class="hist-trig hist-trig-heat">🔥过热(≥80) <b>' + heats.length + '</b>次 最近 <b>' + (hLast ? fmtD(hLast) : '-') + '</b></span>' +
          '</div>' +
        '</div>';
    } catch (e) {
      box.innerHTML = '<div class="hist-pos-loading">数据加载失败</div>';
    }
  })();
}

async function renderSentiment() {
  // 期货数据与情绪数据无依赖，用 Promise.all 并发请求；futures 失败不影响情绪图（独立 .catch）
  const [r, futures] = await Promise.all([
    fetchJSON(dataUrl(`sentiment-${state.range}.json`)),
    fetchJSON("./data/futures.json").catch(() => null),
  ]);
  content.innerHTML = "";
  content.insertAdjacentHTML("beforeend", '<div class="home-purpose-note">💡 <b>这板块有什么用</b>:把多项情绪指标合成0-100的温度计,量化市场冷热(≤20冰点、≥80过热),作逆向参考。<b>怎么解读</b>:≤20冰点(人人恐慌)=情绪极端偏冷区域(历史常对应阶段性低位),≥80过热(人人贪婪)=情绪极端偏热区域(历史常对应阶段性高位);中间区域为中性(历史统计参考,非操作建议)。</div>');
  content.insertAdjacentHTML("beforeend", '<div class="tab-crosslink-note">ℹ️ 本页看<b>情绪温度计</b>+冰点/过热热力图;想看指数<b>价格走势</b>-> 去<a data-goto="market" role="button" tabindex="0">【指数表现】</a></div>');
  _bindTabCrosslink(content, "market");
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
    const chart = valueChartWithSignals(title, data, sig.fear_greed || [], {
      visualMap: {
        show: false,
        pieces: [
          { lte: 25, color: "#42a5f5" },        // 冰点 蓝(冰色,与热力图一致)
          { gt: 25, lte: 40, color: "#4fc3f7" }, // 偏冷 浅蓝
          { gt: 40, lte: 60, color: "#86909c" }, // 中性 灰
          { gt: 60, lte: 75, color: "#e6a23c" }, // 偏热 橙
          { gt: 75, color: "#e6492e" },          // 过热 红(热色,与热力图一致)
        ],
        dimension: 1,
      },
    }, undefined, undefined, undefined, cell);
    // 冰点(≤25)/过热(≥75)阈值线 + 最新值标记（保留信号 pin）
    {
      const _fgOpt = chart.getOption();
      const _fgMp = (_fgOpt.series && _fgOpt.series[0] && _fgOpt.series[0].markPoint && _fgOpt.series[0].markPoint.data) ? [..._fgOpt.series[0].markPoint.data] : [];
      if (data.length && data[data.length - 1].value != null) {
        const _l = data[data.length - 1];
        _fgMp.push({ coord: [_l.date, _l.value], value: _l.value.toFixed(1), itemStyle: { color: "#409eff" }, symbol: "circle", symbolSize: 12, label: { fontSize: 11, color: _autoLabelColor("#409eff") } });
      }
      chart.setOption({ series: [{ markPoint: { data: _fgMp }, markLine: {
        silent: true, symbol: "none", lineStyle: { type: "dashed", width: 1.5 },
        data: [
          { yAxis: 25, lineStyle: { color: "#42a5f5" }, label: { formatter: "冰点", color: "#42a5f5", position: "insideStartTop", fontSize: 10 } },
          { yAxis: 75, lineStyle: { color: "#e6492e" }, label: { formatter: "过热", color: "#e6492e", position: "insideStartTop", fontSize: 10 } },
        ],
      } }] });
    }
    // 缩减恐贪图表高度(360->240),与A股综合/中证1000三卡图表统一高度,给8维度分项腾空间
    chart.getDom().style.height = '240px';
    chart.resize();
    addCardTimeBadge(chart.getDom().parentElement, data.length ? data[data.length - 1].date : "", snap, "t0");
    appendComponentsBlock(data, undefined, cell);
    // 恐贪分项条（8 项情绪分等权 = 恐贪指数；合并进本卡片图表下方，不再独立成卡）
    {
      const _FG_DIM_IDS = [
        "a_sentiment", "cross_market",
        "sentiment_sz50", "sentiment_hs300", "sentiment_csi500",
        "sentiment_csi1000", "sentiment_cyb", "sentiment_kc50",
      ];
      const _lastVal = (arr) => (arr && arr.length && arr[arr.length - 1].value != null) ? arr[arr.length - 1].value : null;
      const _rows = _FG_DIM_IDS.map((id) => {
        const v = _lastVal(r[id]);
        if (v == null) return null;
        return { id, name: indexIdToName(id), value: v, freeze: v < 20, overheat: v > 80 };
      }).filter(Boolean).sort((a, b) => a.value - b.value); // 升序：最恐惧(低分)在上
      if (_rows.length) {
        const fgCard = chart.getDom().parentElement; // 恐贪指数 .chart-card，分项并入同一张卡片
        const _fgTotal = _lastVal(r.fear_greed);
        const totalTxt = _fgTotal != null ? ` · 总分 ${_fgTotal.toFixed(1)}` : "";
        let html = '<div class="fg-dim-merged"><div class="fg-dim-subhead">🌡️ 恐贪分项' + termTip("恐贪指数由以下8项情绪分等权平均合成(2项综合+6项宽基)。分项条解释总分为何是当前值--哪几项拖累(冰点)/哪几项偏高。❄️=冰点(≤20)，🔥=过热(≥80)。") + '<span class="fg-dim-total">8 项等权' + totalTxt + '</span></div>';
        html += '<div class="fg-dim-rows">';
        for (const row of _rows) {
          const col = fearGreedColor(row.value);
          const icon = row.freeze ? ' ❄️' : row.overheat ? ' 🔥' : '';
          html += '<div class="fg-dim-row">' +
            '<span class="fg-dim-name">' + row.name + icon + '</span>' +
            '<span class="fg-dim-track"><span class="fg-dim-fill" style="width:' + row.value.toFixed(1) + '%;background:' + col + '"></span></span>' +
            '<span class="fg-dim-val" style="color:' + col + '">' + row.value.toFixed(1) + '</span>' +
            '</div>';
        }
        html += '</div></div>';
        fgCard.insertAdjacentHTML("beforeend", html);
      }
    }
  }

  if (r.a_sentiment && r.a_sentiment.length) {
    const data = r.a_sentiment.map((d) => ({ date: d.date, value: d.value, components: d.components }));
    const latest = data[data.length - 1] && data[data.length - 1].value;
    const title = `A股综合情绪分（0-100）` + termTip("6项A股指标加权(涨跌比25%+涨停热度20%+炸板率15%+连板15%+成交10%+北向15%,缺项按可用重归一化)算的0-100。≤20冰点(恐慌极值)、≥80过热(亢奋极值)。点'组成因子'看各分项。") + (latest != null ? " · " + sentimentTag(latest) + latestSuffixPct(data) : "");
    const cell = document.createElement("div");
    cardGrid.appendChild(cell);
    const chart = valueChartWithSignals(title, data, sig.a_sentiment || [], {
      visualMap: {
        show: false,
        pieces: [
          { lte: 20, color: "#42a5f5" },
          { gt: 20, lte: 40, color: "#4fc3f7" },
          { gt: 40, lte: 60, color: "#86909c" },
          { gt: 60, lte: 80, color: "#e6a23c" },
          { gt: 80, color: "#e6492e" },
        ],
        dimension: 1,
      },
    }, stats.a_sentiment, strat.a_sentiment, undefined, cell);
    chart.setOption({ series: [{ markLine: {
      silent: true, symbol: "none", lineStyle: { type: "dashed", width: 1.5 },
      data: [
        { yAxis: 20, lineStyle: { color: "#42a5f5" }, label: { formatter: "20", color: "#42a5f5", position: "insideStartTop", fontSize: 10 } },
        { yAxis: 80, lineStyle: { color: "#e6492e" }, label: { formatter: "80", color: "#e6492e", position: "insideStartTop", fontSize: 10 } },
      ],
    } }] });
    addCardTimeBadge(chart.getDom().parentElement, data.length ? data[data.length - 1].date : "", snap, "t0");
    // 标题❓策略弹窗（2026-07-20 方案B1）：a_sentiment 卡 h3 末尾追加❓（s.* 情绪分 skip买 + 豁免MACD 差异化策略）
    _appendStrategyHint(chart.getDom().parentElement, "s.a_sentiment", strat.a_sentiment);
    appendComponentsBlock(data, undefined, cell);
    // 图表高度统一240(与恐贪/中证1000三卡一致)，给下方历史位置3行腾空间
    const _asChartDiv = cell.querySelector('.chart');
    if (_asChartDiv) { _asChartDiv.style.height = '240px'; chart.resize(); }
    // 历史位置3行(候选2/3/4)合并进本卡图表下方：注入 .chart-card(图表父容器)，使3行落在卡片边框内
    appendHistoryPos(chart.getDom().parentElement);
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
            pieces: [
              { lte: 20, color: "#42a5f5" },
              { gt: 20, lte: 40, color: "#4fc3f7" },
              { gt: 40, lte: 60, color: "#86909c" },
              { gt: 60, lte: 80, color: "#e6a23c" },
              { gt: 80, color: "#e6492e" },
            ],
            dimension: 1,
          },
        }, stats[key], strat[key], undefined, cell);
      // 冰点(≤20)/过热(≥80)阈值线（情绪分口径，与恐贪25/75区分）
      chart.setOption({ series: [{ markLine: {
        silent: true, symbol: "none", lineStyle: { type: "dashed", width: 1.5 },
        data: [
          { yAxis: 20, lineStyle: { color: "#42a5f5" }, label: { formatter: "20", color: "#42a5f5", position: "insideStartTop", fontSize: 10 } },
          { yAxis: 80, lineStyle: { color: "#e6492e" }, label: { formatter: "80", color: "#e6492e", position: "insideStartTop", fontSize: 10 } },
        ],
      } }] });
      // 图表高度统一240(与恐贪/A股综合三卡一致)
      chart.getDom().style.height = '240px';
      chart.resize();
      addCardTimeBadge(chart.getDom().parentElement, data.length ? data[data.length - 1].date : "", snap, "t0");
      // 标题❓策略弹窗（2026-07-20 方案B1）：sentiment_* 卡 h3 末尾追加❓（s.* 情绪分 skip买 + 豁免MACD 差异化策略）
      _appendStrategyHint(chart.getDom().parentElement, "s." + key, strat[key]);
      appendComponentsBlock(data, undefined, cell);
      // 历史位置块(与 a股情绪分一致)：补齐卡片高度与恐贪/a股行对齐，同时给出该指数历史分位/近6月极值/极端触发
      appendHistoryPos(chart.getDom().parentElement, key);
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
        pieces: [
          { lte: 20, color: "#42a5f5" },
          { gt: 20, lte: 40, color: "#4fc3f7" },
          { gt: 40, lte: 60, color: "#86909c" },
          { gt: 60, lte: 80, color: "#e6a23c" },
          { gt: 80, color: "#e6492e" },
        ],
        dimension: 1,
      },
    }, stats.cross_market, strat.cross_market, undefined, cell);
    // 冰点(≤20)/过热(≥80)阈值线（情绪分口径，与恐贪25/75区分）
    chart.setOption({ series: [{ markLine: {
      silent: true, symbol: "none", lineStyle: { type: "dashed", width: 1.5 },
      data: [
        { yAxis: 20, lineStyle: { color: "#42a5f5" }, label: { formatter: "20", color: "#42a5f5", position: "insideStartTop", fontSize: 10 } },
        { yAxis: 80, lineStyle: { color: "#e6492e" }, label: { formatter: "80", color: "#e6492e", position: "insideStartTop", fontSize: 10 } },
      ],
    } }] });
    addCardTimeBadge(chart.getDom().parentElement, data.length ? data[data.length - 1].date : "", snap, "t0");
    // 标题❓策略弹窗（2026-07-20 方案B1）：cross_market 卡 h3 末尾追加❓（s.* 情绪分 skip买 + 豁免MACD 差异化策略）
    _appendStrategyHint(chart.getDom().parentElement, "s.cross_market", strat.cross_market);
    appendComponentsBlock(data, undefined, cell);
    // 历史位置块：与细分指数/a股一致，补齐卡片高度对齐
    appendHistoryPos(chart.getDom().parentElement, "cross_market");
  }
  // 期货机构持仓（已在上方与 sentiment 并发拉取，渲染在情绪图之后保持顺序）
  if (futures && futures.positions && futures.positions.length) renderFuturesSection(futures, snap);
}

// 情绪冰点/过热热力图：X 轴=日期，Y 轴=指数名，色块=蓝(冰点≤20)/红(过热>80)/灰(中性)
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

  div.innerHTML = `<h3>🔥 指数情绪冰点/过热热力图${hmSuffix}${termTip("6大宽基指数情绪分的冰点(≤20蓝)/过热(>80红)日历。蓝色密集=多指数同时恐慌(常近底);红色密集=同时亢奋(常近顶)。作逆向参考。")}</h3><div class="chart" style="height:220px"></div>`;
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
        { lte: 20, color: "#42a5f5", label: "冰点(≤20)" },
        { gt: 20, lte: 80, color: "#d9d9d9", label: "中性(20-80)" },
        { gt: 80, color: "#e6492e", label: "过热(>80)" },
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
function renderFuturesSection(data, snap, container) {
  if (!data || !data.positions || !data.positions.length) return;
  // P0-5: container 可选，默认 content（兼容情绪 tab 内嵌调用）；期货独立 subtab 传入 subContent
  const _fgHost = container || content;

  const roles = ["机构(前20)", "中信期货", "国泰君安"];
  const products = ["沪深300期货", "中证500期货", "上证50期货", "中证1000期货", "综合"];

  // 期货区统一套 .indices-grid 3列网格(最小宽度700)：表格卡+折线图+说明卡同网格，视觉统一
  const fgGrid = document.createElement("div");
  fgGrid.className = "indices-grid";
  _fgHost.appendChild(fgGrid);

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
  const labels = { buy: "买点", buy_aux: "辅买", buy_special: "追买", buy_special_filtered: "追买(过滤预览)", buy_backup: "备买", sell: "卖点", sell_stop_loss: "追止损|卖" , band_hold: "波段持有" };
  const cls = { buy: "buy", buy_aux: "buy-aux", buy_special: "buy-special", buy_special_filtered: "buy-special-filtered", buy_backup: "buy-backup", sell: "sell", sell_stop_loss: "sell-stop-loss" , band_hold: "band-hold" };
  let parts = [];
  for (const sig of ["buy", "buy_aux", "buy_special", "buy_special_filtered", "buy_backup", "sell", "sell_stop_loss", "band_hold"]) {
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
  const clsToSig = { buy: "buy", "buy-aux": "buy_aux", "buy-special": "buy_special", "buy-backup": "buy_backup", sell: "sell", "sell-stop-loss": "sell_stop_loss" , "band-hold": "band_hold" };
  const freqBySig = {};
  for (const node of freqNodes) {
    node.querySelectorAll(".hint-row").forEach((row) => {
      const sigSpan = row.querySelector(".hint-sig");
      if (!sigSpan) return;
      let cls = null;
      for (const c of ["buy", "buy-aux", "buy-special", "buy-backup", "sell", "sell-stop-loss"]) {
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
  const sigMap = { buy: "buy", buy_aux: "buy-aux", buy_special: "buy-special", buy_backup: "buy-backup", sell: "sell", sell_stop_loss: "sell-stop-loss" };
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

// P2-新-G ETF 联动推荐：指数信号卡 h3 末尾追加 ETF tag（复用行业卡片的 _renderEtfTag/_bindEtfPopup）。
// 最新信号为 buy 类（buy/buy_aux/buy_special/buy_special_filtered/buy_backup）时加 .etf-tag-buy-signal 高亮。
// 仿 _appendStrategyHint 通过 cardEl.querySelector("h3") 注入子元素（不碰 markPoint/chip 区域）。
// etfs 为空（sh/sz 综合指数无跟踪ETF）不渲染 tag，避免硬塞"代理"ETF 误导用户。
// 注：ETF 滞后指数，tag 仅作"信号参考"展示（ETF 已反映部分预期），非交易指令。
function _appendEtfLinkTag(cardEl, indexId, etfs, signals) {
  if (!cardEl) return;
  if (!etfs || !etfs.length) return;  // sh/sz 综合指数无跟踪ETF -> 不渲染
  var h3 = cardEl.querySelector("h3");
  if (!h3) return;
  if (h3.querySelector(".etf-tag")) return;  // 避免重复注入
  // 检测最新信号（按 date 降序取最新一条），buy 类则高亮 tag
  var BUY_TYPES = { buy: 1, buy_aux: 1, buy_special: 1, buy_special_filtered: 1, buy_backup: 1 };
  var latest = null;
  if (signals && signals.length) {
    for (var i = 0; i < signals.length; i++) {
      var s = signals[i];
      if (!s.date) continue;
      if (!latest || s.date > latest.date) latest = s;
    }
  }
  var isBuy = !!(latest && BUY_TYPES[latest.signal || latest.type]);
  // 注入 tag HTML（top1 代码 + "+N" 候选）
  h3.insertAdjacentHTML("beforeend", _renderEtfTag(etfs));
  var tag = h3.querySelector(".etf-tag");
  if (!tag) return;
  if (isBuy) tag.classList.add("etf-tag-buy-signal");
  // 绑定 popup：top1 点击复制 + 悬浮弹全部候选（按成交额降序，每行可复制）
  _bindEtfPopup(h3, etfs);
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
    const det = await fetchJSON("https://ssd.fx8.store/industry/industry-all-indices/" + id + "-detail.json");
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
    cell.dataset.iid = id; // A9: 供轮动频次 Top N chip 点击滚动定位
    const sign = up ? "+" : "";
    const hint = statsHint(idx.stats, idx.strategy, id);
    const etfTag = _renderEtfTag(idx.etfs);
    // A9: 板块轮动频次标记（fund_flow 方向反转次数，高频🔥🔥/中频🔥）
    const rotFreq = _calcRotationFreq(idx.fund_flow);
    const rotTag = _rotationTag(rotFreq);
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
        <span class="spark-name">${idx.name}${etfTag}${closeSuffix}${pctSuffix}${rotTag}</span>
      </div>
      ${hint ? `<div class="chart-hint">${hint}</div>` : ""}
      <div class="spark-chart"></div>
      <div class="ind-metrics"></div>`;
    // 模拟回测按钮：网格 spark-head 无 h3，走 spark-name 路径（与指数表现 h3 一行布局一致）
    _prependSimBtn(cell, id);
    // 2026-07-20 板分化适配：行业卡加❓策略详情入口（走 spark-name 路径，_prependSimBtn 后调保证 [❓][按钮] 顺序）
    _appendStrategyHint(cell, id, idx.strategy);
    // 信号频率改为 hover pop：绑在对应信号的成功率行(hint-row)上，悬浮显示频率
    _bindFreqPopupToHintRows(cell, idx.stats);
    // ETF：top1 标签可点复制，悬浮弹全部候选（按成交额降序，每行可复制）
    _bindEtfPopup(cell, idx.etfs);
    // B2：视口懒加载行业 detail（tooltip 专属字段），进视口即预取
    // 2026-07-20 板分化 chip：同步懒加载 _appendBackupChipRow，避免循环里同步调触发 58 并发 stats.json fetch
    const _io = new IntersectionObserver((entries) => {
      for (const e of entries) {
        if (e.isIntersecting) {
          _preloadIndDetail(id, idx);
          _appendBackupChipRow(cell, id);
          _io.unobserve(e.target);
        }
      }
    }, { rootMargin: "300px" });
    _io.observe(cell);
    grid.appendChild(cell);
    // 行业角标：dataDate 用 idx.data 末条 date(=07-14 T+1源已到日期)，
    // 非 last_valid_close(=07-13)，避免盘中误判滞后(预期显 📅 T+1·07-14 绿色最新)
    addCardTimeBadge(cell, last.date, state.intradaySnapshot, "t1", "industry");
    // C7 P4 market 融合:行业 spark 卡 append 紧凑分数卡(白名单 iid 才显示)
    _attachMarketScoreCard(id, idx.name, cell);
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
        reason: s.reason || "",  // P0-3: 完整 reason 收进 hover tooltip
        itemStyle: { color: signalColor(s) },
        label: { color: _autoLabelColor(signalColor(s)) },
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
        // P0-3: 信号日追加完整 reason
        const marks = markData.filter((m) => m.coord[0] === p[0].axisValue && m.reason);
        for (const m of marks) lines.push(`<b style="color:${m.itemStyle.color}">● ${m.value}</b> ${_fmtReasonWithBand(m.reason)}`);
        return lines.join("<br/>");
      } },
      series: [{
        type: "line", smooth: true, symbol: "none",
        data: ohlc.map((d) => [d.date, d.close]),
        lineStyle: { color, width: 1.5 }, areaStyle: { color, opacity: 0.12 },
        markPoint: { symbol: "pin", symbolSize: 26, label: { fontSize: 9, color: cssVar("--text-1") }, data: markData },
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

// ============ A9: 板块轮动频次（形态频次，非回测） ============
// 数据源: r.indices[iid].fund_flow = [{date, value}, ...]（value=资金净流入，正=流入/负=流出）
// 指标: 最近 N 日（默认20）资金流向反转次数（正->负 或 负->正 = 1次轮动）
//   反转多 = 资金频繁进出 = 轮动频繁；反转少 = 资金方向稳定（持续流入或流出）
// 注: fund_flow 仅 6-7 月历史（128天），只做形态频次展示，不做回测
const ROTATION_WINDOW = 20;  // 最近 20 交易日窗口
const ROTATION_HIGH = 8;     // >=8 次: 高频轮动 🔥🔥（超均值 1.25 倍）
const ROTATION_MID = 6;      // 6-7 次: 中频轮动 🔥
const ROTATION_MIN_SAMPLE = 10; // 样本 < 10 日不评级（数据不足）

function _calcRotationFreq(fundFlow, window = ROTATION_WINDOW) {
  if (!Array.isArray(fundFlow) || fundFlow.length < 2) return { reversals: 0, sample: 0, level: "na" };
  const recent = fundFlow.slice(-window);
  let reversals = 0;
  let lastDir = 0; // 0=未定，1=流入，-1=流出
  for (const p of recent) {
    const v = (p && typeof p.value === "number") ? p.value : 0;
    const dir = v > 0 ? 1 : (v < 0 ? -1 : 0);
    if (dir === 0) continue; // 0 值不计入反转（资金持平）
    if (lastDir !== 0 && dir !== lastDir) reversals++;
    lastDir = dir;
  }
  const sample = recent.length;
  let level = "low";
  if (sample >= ROTATION_MIN_SAMPLE) {
    if (reversals >= ROTATION_HIGH) level = "high";
    else if (reversals >= ROTATION_MID) level = "mid";
  } else {
    level = "na"; // 样本不足，不评级
  }
  return { reversals, sample, level };
}

function _rotationTag(freq) {
  if (!freq || freq.level === "low" || freq.level === "na") return "";
  const icon = freq.level === "high" ? "🔥🔥" : "🔥";
  return `<span class="rot-tag rot-${freq.level}" title="近期轮动频次: ${freq.reversals}次资金方向反转（近${freq.sample}日，频次高=资金切换频繁）">${icon}${freq.reversals}</span>`;
}

// A9 Top N 轮动频次板块列表（用于板块分化区独立卡片）
function _buildRotationFreqList(indices) {
  return Object.entries(indices || {})
    .map(([id, idx]) => ({ id, name: idx.name, freq: _calcRotationFreq(idx.fund_flow) }))
    .filter((x) => x.freq.sample >= ROTATION_MIN_SAMPLE) // 样本不足不参与排名
    .sort((a, b) => b.freq.reversals - a.freq.reversals);
}

async function _loadIndustryData(range) {
  // all/5y/3y 走拆分：31 行业小文件按需并发 fetch，避免 industry-all 29MB / industry-5y 14MB / industry-3y 9.2MB 大单文件拖慢首屏
  if (range !== "all" && range !== "5y" && range !== "3y") return await fetchJSON(`https://ssd.fx8.store/industry/industry-${range}.json`);
  const meta = await fetchJSON(`https://ssd.fx8.store/industry/industry-${range}-meta.json`);
  const ids = meta.index_ids || [];
  const entries = await Promise.all(
    ids.map(async (iid) => [iid, await fetchJSON(`https://ssd.fx8.store/industry/industry-${range}-indices/${iid}.json`)])
  );
  const conceptsRes = await fetchJSON(`https://ssd.fx8.store/industry/industry-${range}-concepts.json`);
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

  // A9: 板块轮动频次 Top N 卡片（基于 fund_flow 方向反转次数，单板块维度，与全局轮动速度互补）
  // 插在 anchorBar 之前（热力图下方概览区），chip 点击清搜索+滚动定位对应板块卡
  const _rotFreqExisting = content.querySelector(".rotation-freq-card");
  if (_rotFreqExisting) _rotFreqExisting.remove();
  const rotFreqList = _buildRotationFreqList(r.indices);
  const rotTopN = rotFreqList.slice(0, 10);
  if (rotTopN.length) {
    const rotFreqCard = document.createElement("div");
    rotFreqCard.className = "rotation-freq-card";
    const highCnt = rotTopN.filter((x) => x.freq.level === "high").length;
    rotFreqCard.innerHTML = `
      <div class="rotation-freq-header">🔀 板块轮动频次 Top ${rotTopN.length}<span class="chart-latest"> · 近${ROTATION_WINDOW}日资金流向反转次数</span></div>
      <div class="rotation-freq-body">
        ${rotTopN.map((x, i) => `<button type="button" class="rot-freq-chip rot-${x.freq.level}" data-iid="${x.id}" title="${x.name}：近${x.freq.sample}日资金方向反转${x.freq.reversals}次（频次高=资金切换频繁）">${i + 1}. ${x.name} <b>${x.freq.reversals}次</b></button>`).join("")}
      </div>
      <div class="rotation-freq-hint">💡 资金流向频繁反转=板块轮动信号强（如 ${highCnt} 个高频板块🔥🔥）；频次低=资金方向稳定。点击 chip 跳转对应板块卡。<details class="rotation-explain"><summary>指标怎么算</summary><div class="rotation-explain-body"><div>取每个板块最近 ${ROTATION_WINDOW} 个交易日的 <b>资金净流入</b>（fund_flow），看资金方向（正=流入/负=流出）反转了几次：正->负或负->正算 1 次轮动。</div><div>分级：≥${ROTATION_HIGH}次 高频🔥🔥 / ${ROTATION_MID}-${ROTATION_HIGH - 1}次 中频🔥 / ≤${ROTATION_MID - 1}次 低频。样本＜${ROTATION_MIN_SAMPLE}日不评级。</div><div>注：fund_flow 仅 6-7 月历史，只做形态频次展示，非回测。</div></div></details></div>`;
    content.insertBefore(rotFreqCard, anchorBar);
    rotFreqCard.querySelectorAll(".rot-freq-chip").forEach((chip) => {
      chip.onclick = () => {
        // 清搜索以确保目标板块卡可见（搜索筛选会隐藏）
        if (state.industrySearch) {
          state.industrySearch = "";
          const si = anchorBar.querySelector(".anchor-search");
          if (si) si.value = "";
          _applyIndustryFilter();
        }
        // 延迟一帧等重渲染完成再滚动定位
        requestAnimationFrame(() => {
          const target = swGridWrap.querySelector(`.industry-cell[data-iid="${CSS.escape(chip.dataset.iid)}"]`);
          if (target) target.scrollIntoView({ behavior: "smooth", block: "center" });
        });
      };
    });
  }

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

// ============ B4: ETF 评分列表（分页+搜索） ============
// 数据源: static-site/data/etf_score_list.json
//   buy_list: 买入机会（score 高=机会显著）, 字段 etf_code/name/score/hands/high_alert/low_alert/is_national_team/reason_summary
//   sell_list: 卖出信号（score 高=过热）, 字段 etf_code/name/score/sell_signal/high_alert/low_alert/is_national_team/reason_summary
// 合并成统一列表 + side(buy/sell) 字段, 分页(每页50) + 搜索(代码/名称过滤)
// 注: 当前为代表性 62 只(buy20+sell30=50); 后端 --full-market 可扩至 ~1371 只, 分页自动生效
const ETF_SCORE_PAGE_SIZE = 50;
const _etfScoreState = { all: [], filtered: [], page: 1, search: "", meta: null, holdingOnly: false };

// ============ B4 持仓: localStorage 读写（纯前端本地存，不传后端） ============
// 存储格式: localStorage["etf_holdings"] = JSON.stringify(["510300","159915",...]) 6位ETF代码数组
function _getEtfHoldings() {
  try {
    const raw = localStorage.getItem("etf_holdings");
    if (!raw) return [];
    const arr = JSON.parse(raw);
    return Array.isArray(arr) ? arr.map((x) => String(x).trim()).filter(Boolean) : [];
  } catch (e) { return []; }
}
function _setEtfHoldings(arr) {
  try { localStorage.setItem("etf_holdings", JSON.stringify(arr)); } catch (e) {}
}
// 解析用户输入: 容忍 逗号(半/全角)/换行/空格/分号 分隔, 只保留 6 位数字代码, 去重保序
function _parseEtfHoldingsInput(text) {
  if (!text) return [];
  const tokens = String(text).split(/[,，;；\n\r\s]+/).map((s) => s.trim()).filter(Boolean);
  const out = [];
  const seen = Object.create(null);
  tokens.forEach((t) => {
    const m = t.match(/(\d{6})/);
    if (m && !seen[m[1]]) { seen[m[1]] = 1; out.push(m[1]); }
  });
  return out;
}
// 持仓代码集合（用于 O(1) 判断行是否持仓）
function _getEtfHoldingsSet() {
  const set = Object.create(null);
  _getEtfHoldings().forEach((c) => { set[c] = 1; });
  return set;
}

function _esc(s) {
  // 简易 XSS 防护: 转义 HTML 特殊字符（reason_summary/name 等后端文本）
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function _etfScoreColor(score, side) {
  // 配色与卡片一致(2026-07-24 v2 淡雅低饱和):buy 淡粉暗红(多),sell 灰蓝(空,冷色非绿),hold 暗黄(持有观察)
  if (side === "buy") {
    if (score >= 80) return "#a05050";
    if (score >= 60) return "#c08080";
    return "var(--text-3,#86909c)";
  }
  if (side === "hold") {
    const theme = document.documentElement.getAttribute("data-theme");
    const isDark = theme === "dark" || theme === "redgold";
    if (score >= 80) return isDark ? "#e8b870" : "#b8860b";
    if (score >= 60) return isDark ? "#f0c890" : "#d4a017";
    return "var(--text-3,#86909c)";
  }
  if (score >= 80) return "#5a7a8a";
  if (score >= 60) return "#8aaab8";
  return "var(--text-3,#86909c)";
}

function _etfScorePages() {
  return Math.max(1, Math.ceil(_etfScoreState.filtered.length / ETF_SCORE_PAGE_SIZE));
}

function _applyEtfScoreFilter() {
  const s = _etfScoreState.search.trim().toLowerCase();
  let filtered = s
    ? _etfScoreState.all.filter((e) =>
        String(e.etf_code).toLowerCase().includes(s) || String(e.name).toLowerCase().includes(s))
    : _etfScoreState.all.slice();
  // 持仓筛选: 只看持仓的 ETF
  if (_etfScoreState.holdingOnly) {
    const hset = _getEtfHoldingsSet();
    filtered = filtered.filter((e) => hset[e.etf_code]);
  }
  _etfScoreState.filtered = filtered;
  const pages = _etfScorePages();
  if (_etfScoreState.page > pages) _etfScoreState.page = pages;
  if (_etfScoreState.page < 1) _etfScoreState.page = 1;
  _renderEtfScoreBody();
}

function _renderEtfScoreBody() {
  const body = document.getElementById("etf-score-body");
  if (!body) return;
  const st = _etfScoreState;
  const total = st.filtered.length;
  const pages = _etfScorePages();
  const start = (st.page - 1) * ETF_SCORE_PAGE_SIZE;
  const slice = st.filtered.slice(start, start + ETF_SCORE_PAGE_SIZE);
  let html = "";
  // 统计条
  const buyN = st.all.filter((e) => e.side === "buy").length;
  const sellN = st.all.filter((e) => e.side === "sell").length;
  const holdN = st.all.filter((e) => e.side === "hold").length;
  const hset = _getEtfHoldingsSet();
  const holdingInList = st.all.filter((e) => hset[e.etf_code]).length;
  html += '<div class="etf-score-stat">共 ' + st.all.length + ' 只'
    + (st.meta && st.meta.full_market ? '（全市场）' : '（代表性清单）')
    + ' · 买入机会 ' + buyN + ' · 持有观察 ' + holdN + ' · 卖出信号 ' + sellN
    + (holdingInList > 0 ? ' · <b class="etf-stat-hold">我的持仓 ' + holdingInList + '</b>' : '')
    + (st.search ? ' · 搜索命中 ' + total : '')
    + (st.holdingOnly ? ' · 只看持仓' : '') + '</div>';
  if (total === 0) {
    html += '<div class="etf-score-empty">未命中任何 ETF，换个代码或名称试试</div>';
  } else {
    html += '<div class="etf-score-list">';
    slice.forEach((e, i) => {
      const col = _etfScoreColor(e.score, e.side);
      const sideTag = e.side === "buy"
        ? '<span class="etf-side-tag etf-side-buy">买入机会</span>'
        : e.side === "hold"
        ? '<span class="etf-side-tag etf-side-hold">持有观察</span>'
        : '<span class="etf-side-tag etf-side-sell">卖出信号</span>';
      const ntTag = e.is_national_team ? '<span class="etf-nt-tag" title="国家队宽基ETF">国家队</span>' : '';
      const signalTxt = e.side === "buy"
        ? (e.hands != null ? '买点 ' + e.hands + ' 手' : '')
        : e.side === "hold"
        ? (e.sell_signal ? _esc(e.sell_signal) : '继续持有')
        : (e.sell_signal ? _esc(e.sell_signal) : '');
      const rank = start + i + 1;
      const isHolding = !!hset[e.etf_code];
      const holdTag = isHolding ? '<span class="etf-hold-tag" title="我的持仓">⭐ 持仓</span>' : '';
      html += '<div class="etf-score-row etf-side-' + e.side + (isHolding ? ' is-holding' : '') + '">'
        + '<div class="etf-row-main">'
        + '<span class="etf-rank">#' + rank + '</span>'
        + '<span class="etf-code">' + _esc(e.etf_code) + '</span>'
        + '<span class="etf-name">' + _esc(e.name) + ntTag + holdTag + '</span>'
        + '<span class="etf-score" style="color:' + col + '">' + (e.score != null ? e.score.toFixed(2) : '-') + '</span>'
        + '</div>'
        + '<div class="etf-row-sub">'
        + sideTag
        + (signalTxt ? '<span class="etf-signal">' + signalTxt + '</span>' : '')
        + '<span class="etf-alert" title="高位/低位预警区间">预警 ' + (e.high_alert != null ? e.high_alert.toFixed(2) : '-') + ' / ' + (e.low_alert != null ? e.low_alert.toFixed(2) : '-') + '</span>'
        + '</div>'
        + (e.reason_summary ? '<div class="etf-reason">' + _esc(e.reason_summary) + '</div>' : '')
        + '</div>';
    });
    html += '</div>';
    // 分页器
    if (pages > 1) {
      html += '<div class="etf-score-pager">';
      html += '<button class="etf-page-btn" data-page="' + (st.page > 1 ? st.page - 1 : 1) + '"' + (st.page <= 1 ? ' disabled' : '') + '>上一页</button>';
      // 页码：最多显示 9 个，首尾+当前附近
      const pageBtns = [];
      const addPage = (p) => { if (pageBtns.indexOf(p) < 0) pageBtns.push(p); };
      addPage(1); addPage(pages);
      for (let p = st.page - 2; p <= st.page + 2; p++) {
        if (p > 1 && p < pages) addPage(p);
      }
      pageBtns.sort((a, b) => a - b);
      let prev = 0;
      pageBtns.forEach((p) => {
        if (p - prev > 1) html += '<span class="etf-page-ellipsis">…</span>';
        html += '<button class="etf-page-btn' + (p === st.page ? " active" : "") + '" data-page="' + p + '">' + p + '</button>';
        prev = p;
      });
      html += '<button class="etf-page-btn" data-page="' + (st.page < pages ? st.page + 1 : pages) + '"' + (st.page >= pages ? ' disabled' : '') + '>下一页</button>';
      html += '<span class="etf-page-info">' + st.page + ' / ' + pages + ' 页（' + total + ' 只）</span>';
      html += '</div>';
    }
  }
  body.innerHTML = html;
  // 绑定分页按钮
  body.querySelectorAll(".etf-page-btn[data-page]").forEach((b) => {
    b.onclick = () => {
      if (b.disabled) return;
      _etfScoreState.page = parseInt(b.dataset.page, 10) || 1;
      _renderEtfScoreBody();
      // 翻页后滚到列表顶部
      const top = body.getBoundingClientRect().top + window.scrollY - 80;
      window.scrollTo({ top: Math.max(0, top), behavior: "smooth" });
    };
  });
}

async function renderEtfScore() {
  const r = await fetchJSON("./data/etf_score_list.json");
  _etfScoreState.meta = {
    date: r.date, updated_at: r.updated_at, source: r.source,
    universe_count: r.universe_count, full_market: r.full_market,
    buy_top: r.buy_top, sell_top: r.sell_top, fetch_count: r.fetch_count, skip_count: r.skip_count,
  };
  // 合并 buy_list + sell_list 成统一列表
  const all = [];
  (r.buy_list || []).forEach((e) => all.push({
    etf_code: e.etf_code, name: e.name, score: e.score, side: "buy",
    hands: e.hands, high_alert: e.high_alert, low_alert: e.low_alert,
    is_national_team: e.is_national_team, reason_summary: e.reason_summary,
    sell_signal: null,
  }));
  (r.sell_list || []).forEach((e) => {
    // sell_list 按 sell_signal 拆 side:含"减仓信号/减仓/清仓"->sell,含"观察/持有"->hold
    const sig = e.sell_signal || "";
    const side = /建议卖出|减仓|清仓/.test(sig) ? "sell" : "hold";
    all.push({
      etf_code: e.etf_code, name: e.name, score: e.score, side: side,
      hands: null, high_alert: e.high_alert, low_alert: e.low_alert,
      is_national_team: e.is_national_team, reason_summary: e.reason_summary,
      sell_signal: e.sell_signal,
    });
  });
  _etfScoreState.all = all;
  _etfScoreState.filtered = all.slice();
  _etfScoreState.page = 1;
  _etfScoreState.search = "";
  _etfScoreState.holdingOnly = false; // 进入 tab 重置持仓筛选

  content.innerHTML = "";
  const m = _etfScoreState.meta;
  content.insertAdjacentHTML("beforeend",
    '<div class="home-purpose-note">💡 <b>这板块有什么用</b>:从代表性 ETF 清单里按多维度评分筛出当前<b>买入机会</b>（冰点共振/超跌反弹）与<b>卖出信号</b>（过热/位置偏高）。<b>怎么解读</b>:买入评分高=机会显著（历史常对应低位区域），卖出评分高=情绪过热（历史常对应高位区域）。<b>口径</b>:历史统计与技术分析参考，非投资建议。</div>');
  // 持仓面板（可折叠输入区 + 持仓 chips 显示评分排名）
  const holdWrap = document.createElement("div");
  holdWrap.id = "etf-holdings-panel";
  content.appendChild(holdWrap);
  _renderEtfHoldingsPanel();
  // 搜索栏
  const bar = document.createElement("div");
  bar.className = "etf-score-bar";
  const holdN = _getEtfHoldings().length;
  bar.innerHTML =
    '<input id="etf-score-search" type="search" placeholder="搜 ETF 代码或名称（如 515030 / 新能源车）" autocomplete="off" value="' + _esc(_etfScoreState.search) + '">'
    + '<button id="etf-hold-filter" class="etf-hold-filter' + (_etfScoreState.holdingOnly ? ' active' : '') + '"' + (holdN === 0 ? ' disabled' : '') + '>只看持仓' + (holdN > 0 ? ' (' + holdN + ')' : '') + '</button>'
    + '<span class="etf-score-updated">更新 ' + (m && m.updated_at ? _esc(m.updated_at.slice(0, 16)) : '-') + (m && m.full_market ? ' · 全市场' : ' · 代表性') + '</span>';
  content.appendChild(bar);
  const input = bar.querySelector("#etf-score-search");
  let _searchTimer = null;
  input.oninput = () => {
    if (_searchTimer) clearTimeout(_searchTimer);
    _searchTimer = setTimeout(() => {
      _etfScoreState.search = input.value;
      _etfScoreState.page = 1;
      _applyEtfScoreFilter();
    }, 180); // 防抖
  };
  // 只看持仓 切换
  const holdFilterBtn = bar.querySelector("#etf-hold-filter");
  holdFilterBtn.onclick = () => {
    if (holdFilterBtn.disabled) return;
    _etfScoreState.holdingOnly = !_etfScoreState.holdingOnly;
    holdFilterBtn.classList.toggle("active", _etfScoreState.holdingOnly);
    _etfScoreState.page = 1;
    _applyEtfScoreFilter();
  };
  // 列表容器
  const body = document.createElement("div");
  body.id = "etf-score-body";
  content.appendChild(body);
  _renderEtfScoreBody();
}

// ============ B4 持仓面板: 输入/保存/清空 + chips 显示评分排名 ============
// 折叠态记忆: localStorage["etf_holdings_expanded"] ("1"/"0"), 默认展开(引导输入)
function _renderEtfHoldingsPanel() {
  const wrap = document.getElementById("etf-holdings-panel");
  if (!wrap) return;
  const holdings = _getEtfHoldings();
  let expanded = true;
  try { const v = localStorage.getItem("etf_holdings_expanded"); if (v === "0") expanded = false; } catch (e) {}
  // 计算每个持仓在评分榜中的排名（按 all 列表顺序，即评分排序）
  const all = _etfScoreState.all;
  const rankMap = Object.create(null);
  all.forEach((e, i) => { if (rankMap[e.etf_code] == null) rankMap[e.etf_code] = i + 1; });
  // chips: 持仓代码 + 名称(若在榜) + 榜内排名
  const chipsHtml = holdings.map((code) => {
    const item = all.find((e) => e.etf_code === code);
    const rank = rankMap[code];
    const onList = !!item;
    const nameTxt = onList ? _esc(item.name) : '未在榜单';
    const sideCls = onList ? (' etf-hold-chip-' + item.side) : ' etf-hold-chip-off';
    const rankTxt = onList ? ' <b class="etf-hold-rank">#' + rank + '</b>' : '';
    return '<span class="etf-hold-chip' + sideCls + '" data-code="' + _esc(code) + '">'
      + '<span class="etf-hold-chip-code">' + _esc(code) + '</span>'
      + '<span class="etf-hold-chip-name">' + nameTxt + rankTxt + '</span>'
      + '<button class="etf-hold-chip-x" title="移除" data-code="' + _esc(code) + '">×</button>'
      + '</span>';
  }).join("");
  const emptyTip = holdings.length === 0
    ? '<div class="etf-hold-empty">尚未录入持仓。输入 ETF 代码后保存，榜单中持仓行会高亮并显示评分排名。</div>' : '';
  wrap.innerHTML =
    '<div class="etf-hold-head">'
    + '<button class="etf-hold-toggle' + (expanded ? ' expanded' : '') + '">'
    + '<span class="etf-hold-star">⭐</span> 我的持仓' + (holdings.length > 0 ? ' (' + holdings.length + ')' : '') + '</button>'
    + (holdings.length > 0
      ? '<span class="etf-hold-hint">榜单中持仓行高亮显示，并标注评分排名</span>' : '')
    + '</div>'
    + (expanded
      ? '<div class="etf-hold-body">'
        + '<div class="etf-hold-input-row">'
        + '<textarea id="etf-hold-input" rows="2" placeholder="输入持仓 ETF 代码，逗号或换行分隔（如 510300, 159915）">' + _esc(holdings.join(", ")) + '</textarea>'
        + '<div class="etf-hold-actions">'
        + '<button id="etf-hold-save" class="etf-hold-btn-primary">保存</button>'
        + '<button id="etf-hold-clear"' + (holdings.length === 0 ? ' disabled' : '') + '>清空</button>'
        + '</div>'
        + '</div>'
        + '<div class="etf-hold-chips">' + chipsHtml + emptyTip + '</div>'
        + '</div>'
      : '');
  // 折叠/展开
  const toggleBtn = wrap.querySelector(".etf-hold-toggle");
  toggleBtn.onclick = () => {
    const next = !toggleBtn.classList.contains("expanded");
    try { localStorage.setItem("etf_holdings_expanded", next ? "1" : "0"); } catch (e) {}
    _renderEtfHoldingsPanel();
  };
  // 保存
  const saveBtn = wrap.querySelector("#etf-hold-save");
  if (saveBtn) {
    saveBtn.onclick = () => {
      const ta = wrap.querySelector("#etf-hold-input");
      const arr = _parseEtfHoldingsInput(ta.value);
      _setEtfHoldings(arr);
      _renderEtfHoldingsPanel();
      _refreshEtfHoldFilterBtn();
      _etfScoreState.page = 1;
      _applyEtfScoreFilter();
    };
  }
  // 清空
  const clearBtn = wrap.querySelector("#etf-hold-clear");
  if (clearBtn) {
    clearBtn.onclick = () => {
      if (clearBtn.disabled) return;
      _setEtfHoldings([]);
      _renderEtfHoldingsPanel();
      _refreshEtfHoldFilterBtn();
      _etfScoreState.holdingOnly = false;
      _etfScoreState.page = 1;
      _applyEtfScoreFilter();
    };
  }
  // chip 移除
  wrap.querySelectorAll(".etf-hold-chip-x").forEach((x) => {
    x.onclick = () => {
      const code = x.dataset.code;
      const arr = _getEtfHoldings().filter((c) => c !== code);
      _setEtfHoldings(arr);
      _renderEtfHoldingsPanel();
      _refreshEtfHoldFilterBtn();
      _etfScoreState.page = 1;
      _applyEtfScoreFilter();
    };
  });
}
// 同步搜索栏"只看持仓"按钮的数字/状态
function _refreshEtfHoldFilterBtn() {
  const btn = document.getElementById("etf-hold-filter");
  if (!btn) return;
  const n = _getEtfHoldings().length;
  btn.textContent = '只看持仓' + (n > 0 ? ' (' + n + ')' : '');
  btn.disabled = (n === 0);
  if (n === 0) {
    _etfScoreState.holdingOnly = false;
    btn.classList.remove("active");
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
const _H5_TAB_NAMES = { overview: "📊 市场全景", market: "📈 指数表现", sentiment: "😊 情绪温度", industry: "🏭 板块分化", etf: "💹 ETF评分", lab: "🧪 策略实验" };

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

// === 模拟回测 modal（替代 iframe，5窗口切换，每窗口独立 10w 起算）===
// 主题继承父页（不再 iframe postMessage）；复用 lab.min.css 的 .lab-win-tabs/.lab-win-tab/.lab-win-bar
var _tradeSimOverlay = null;
var _tradeSimState = null;
var _tradeSimStatsCache = {};
var _tradeSimFullCache = {};
var _TRADE_SIM_WIN_DEFS = [
  { k: "all", l: "全历史" },
  { k: "y10", l: "近10年" },
  { k: "y5",  l: "近5年" },
  { k: "y3",  l: "近3年" },
  { k: "y1",  l: "近1年" },
];
var _TRADE_SIM_DEFAULT_WIN = "y5";

function _tradeSimOverlayEl() {
  if (_tradeSimOverlay) return _tradeSimOverlay;
  var ov = document.createElement('div');
  ov.className = 'trade-sim-overlay';
  ov.innerHTML = '<div class="trade-sim-modal">' +
    '<div class="trade-sim-modal-head">' +
      '<span class="trade-sim-modal-title"></span>' +
      '<button type="button" class="trade-sim-modal-close" aria-label="关闭" title="关闭">✕</button>' +
    '</div>' +
    '<div class="trade-sim-modal-body"></div>' +
    '</div>';
  document.body.appendChild(ov);
  _tradeSimOverlay = ov;
  ov.querySelector('.trade-sim-modal-close').onclick = _tradeSimCloseModal;
  ov.onclick = function (e) { if (e.target === ov) _tradeSimCloseModal(); };
  return ov;
}

function _tradeSimCloseModal() {
  if (_tradeSimOverlay) _tradeSimOverlay.classList.remove('show');
  document.body.style.overflow = '';
}

function _tradeSimColorPct(pct) {
  if (pct > 0) return "#e6492e";
  if (pct < 0) return "#2e8b57";
  return "#9e9e9e";
}

function _tradeSimFmtNum(n) {
  if (n === null || n === undefined || n === Infinity) return "-";
  return Number(n).toLocaleString('zh-CN', { maximumFractionDigits: 2 });
}

async function _tradeSimFetchStats(indexId) {
  // R2 托管：trade_sim_data/ 前缀避开 trade_sim/ HTML；fetchJSON 自动 .gz 优先 + DecompressionStream 解压（与 lab/index 一致）
  return await fetchJSON('https://ssd.fx8.store/trade_sim_data/trade_sim_' + encodeURIComponent(indexId) + '_stats.json');
}

async function _tradeSimFetchFull(indexId) {
  return await fetchJSON('https://ssd.fx8.store/trade_sim_data/trade_sim_' + encodeURIComponent(indexId) + '_full.json');
}

// === A10 历史相似形态匹配（皮尔逊相关 + 滑窗，O(n) 前端实时算）===
// 取近 N 日归一化日收益率作为"当前形态"，历史滑窗算 top5 最相似时段，top1 延伸虚线为后续走势参考。
// 数据源路由：A股宽基/红利->a-stock-all.json，港股->hk-all.json，美股/欧洲->global-all.json(indices)，商品->global-all.json(extras)，申万行业->index/${id}-all.json。
var _tradeSimShapeCache = {};      // indexId -> {name, data:[{date,close,...}]} 或 null
var _astockAllCache = null, _hkAllCache = null, _globalAllCache = null;
var _SHAPE_A_STOCK = new Set(['sh','sz','cyb','csi500','csi1000','kc50','hs300','sz50','bj50','div_lowvol','csi_div','sz_div']);
var _SHAPE_HK = new Set(['hsi','hscei','hstech']);
var _SHAPE_US_EU = new Set(['us_dji','us_ixic','us_spx','us_ndx','ftse100','dax','nikkei225','kospi']);
var _SHAPE_COMMODITY = {
  'g.gold':'gold', 'gold':'gold', 'g.comex_silver':'comex_silver', 'comex_silver':'comex_silver',
  'g.wti_oil':'wti_oil', 'wti_oil':'wti_oil', 'g.brent':'brent', 'brent':'brent',
  'g.us10y':'us10y', 'us10y':'us10y', 'g.a_qvix_300':'a_qvix_300', 'a_qvix_300':'a_qvix_300',
  'g.a_qvix_1000':'a_qvix_1000', 'a_qvix_1000':'a_qvix_1000',
};
var _SHAPE_COMMODITY_NAME = {
  'gold':'伦敦金', 'comex_silver':'COMEX白银', 'wti_oil':'WTI原油', 'brent':'布伦特原油',
  'us10y':'美10Y收益率', 'a_qvix_300':'A股300波动率', 'a_qvix_1000':'A股1000波动率',
};
// 路由取数：返回 {name, data:[{date,close}]} 或 null（数据源未覆盖或加载失败）
async function _shapeLoadSeries(indexId) {
  if (_tradeSimShapeCache.hasOwnProperty(indexId)) return _tradeSimShapeCache[indexId];
  var result = null;
  try {
    if (_SHAPE_A_STOCK.has(indexId)) {
      _astockAllCache = _astockAllCache || await fetchJSON(dataUrl("a-stock-all.json"));
      var idx = _astockAllCache.indices && _astockAllCache.indices[indexId];
      if (idx) result = { name: idx.name, data: (idx.data || []).map(function (d) { return { date: d.date, close: d.close }; }) };
    } else if (_SHAPE_HK.has(indexId)) {
      _hkAllCache = _hkAllCache || await fetchJSON(dataUrl("hk-all.json"));
      var hidx = _hkAllCache.indices && _hkAllCache.indices[indexId];
      if (hidx) result = { name: hidx.name, data: (hidx.data || []).map(function (d) { return { date: d.date, close: d.close }; }) };
    } else if (_SHAPE_US_EU.has(indexId)) {
      _globalAllCache = _globalAllCache || await fetchJSON(dataUrl("global-all.json"));
      var gidx = _globalAllCache.indices && _globalAllCache.indices[indexId];
      if (gidx) result = { name: gidx.name, data: (gidx.data || []).map(function (d) { return { date: d.date, close: d.close }; }) };
    } else if (_SHAPE_COMMODITY[indexId]) {
      _globalAllCache = _globalAllCache || await fetchJSON(dataUrl("global-all.json"));
      var exKey = _SHAPE_COMMODITY[indexId];
      var ex = _globalAllCache.extras && _globalAllCache.extras[exKey];
      if (ex && ex.length) result = { name: _SHAPE_COMMODITY_NAME[exKey] || exKey, data: ex.map(function (d) { return { date: d.date, close: d.value }; }) };
    } else if (indexId && indexId.indexOf('sw_') === 0) {
      // 2026-07-20 板分化适配：申万行业指数走 index/${id}-all.json（与 _preloadIndDetail 同路径），取 ohlc[].close
      var swJson = await fetchJSON('https://ssd.fx8.store/index/' + encodeURIComponent(indexId) + '-all.json');
      if (swJson && swJson.ohlc && swJson.ohlc.length) {
        var swName = (_INDEX_NAME_MAP && _INDEX_NAME_MAP[indexId]) ? _INDEX_NAME_MAP[indexId] : indexId;
        result = { name: swName, data: swJson.ohlc.map(function (d) { return { date: String(d.date), close: d.close }; }) };
      }
    }
  } catch (e) { result = null; }
  _tradeSimShapeCache[indexId] = result;
  return result;
}
// 归一化（零均值、单位方差，用总体标准差；null=方差过小）
function _shapeNormalize(arr) {
  var n = arr.length;
  if (n < 2) return null;
  var mean = 0;
  for (var i = 0; i < n; i++) mean += arr[i];
  mean /= n;
  var v = 0;
  for (var j = 0; j < n; j++) v += (arr[j] - mean) * (arr[j] - mean);
  var std = Math.sqrt(v / n);
  if (std < 1e-10) return null;
  var out = new Array(n);
  for (var k = 0; k < n; k++) out[k] = (arr[k] - mean) / std;
  return out;
}
// 皮尔逊相关（入参已归一化，= dot/n）
function _shapePearson(a, b) {
  if (a.length !== b.length) return null;
  var dot = 0;
  for (var i = 0; i < a.length; i++) dot += a[i] * b[i];
  return dot / a.length;
}
// 核心匹配：closes/dates 完整序列，curLen=当前形态长度，forecastLen=延伸长度，topN=返回数
// 返回 {current:{startDate,endDate,cum:[{date,cum}]}, matches:[{startDate,endDate,corr,forecast:[{date,cum}]}]}
function _shapeMatch(closes, dates, curLen, forecastLen, topN) {
  var n = closes.length;
  if (n < curLen + forecastLen + 5) return null;
  var rets = new Array(n - 1);
  for (var i = 1; i < n; i++) rets[i - 1] = (closes[i] - closes[i - 1]) / closes[i - 1];
  // rets[t] 对应 closes[t+1] 的涨幅；当前末 curLen 日 = rets 末 curLen 个
  var curStart = rets.length - curLen;
  var curNorm = _shapeNormalize(rets.slice(curStart));
  if (!curNorm) return null;
  var matches = [];
  // 历史窗末 index 必须 < curStart（不与当前重叠），且窗末后要有 forecastLen 日延伸
  var lastAllowed = curStart - 1;
  for (var i = 0; i + curLen - 1 <= lastAllowed; i++) {
    var winEnd = i + curLen - 1;
    if (winEnd + forecastLen >= rets.length) continue;
    var winNorm = _shapeNormalize(rets.slice(i, i + curLen));
    if (!winNorm) continue;
    var corr = _shapePearson(curNorm, winNorm);
    if (corr === null || isNaN(corr)) continue;
    // 延伸：窗末 close=closes[i+curLen]，后续 forecastLen 日累计收益（归一化到窗末=1）
    var base = closes[i + curLen];
    var forecast = [];
    for (var k = 1; k <= forecastLen; k++) {
      var ci = i + curLen + k;
      if (ci >= n) break;
      forecast.push({ date: dates[ci], cum: closes[ci] / base });
    }
    matches.push({ startDate: dates[i + 1], endDate: dates[i + curLen], corr: corr, forecast: forecast, idx: i });
  }
  matches.sort(function (a, b) { return b.corr - a.corr; });
  // 去重：相邻窗间隔 < curLen 视为重叠，只保留 corr 最高的
  var picked = [];
  for (var m = 0; m < matches.length; m++) {
    var overlap = false;
    for (var p = 0; p < picked.length; p++) {
      if (Math.abs(matches[m].idx - picked[p].idx) < curLen) { overlap = true; break; }
    }
    if (!overlap) picked.push(matches[m]);
    if (picked.length >= topN) break;
  }
  // 当前形态累计收益（末日=1，向前累乘）
  var curBase = closes[n - 1];
  var curCum = [];
  for (var c = n - curLen; c < n; c++) curCum.push({ date: dates[c], cum: closes[c] / curBase });
  return { current: { startDate: dates[n - curLen], endDate: dates[n - 1], cum: curCum }, matches: picked };
}
// 相似形态虚线样式：rank 1=top1(最亮最粗)，2-5 递减区分层次（TOP_PLOT=5 用）
function _shapeLineStyle(rank) {
  var W = [0, 1.8, 1.3, 1.1, 0.9, 0.8];
  var O = [0, 0.9, 0.55, 0.45, 0.35, 0.28];
  return { width: W[rank] || 0.8, opacity: O[rank] || 0.28 };
}
// 相似形态走势 SVG：当前末段实线 + top1..topN 延伸虚线（各延伸起点对齐到当前末点）
function _shapeMatchSVG(result, topPlot) {
  if (!result || !result.matches.length) return '<div style="padding:16px;color:var(--text-3);text-align:center">无相似时段</div>';
  var cur = result.current.cum;
  var topList = result.matches.slice(0, topPlot);
  // 拼接序列：当前段（curLen 点）+ 延伸段（forecastLen 点）。当前段实线，延伸段虚线（top1 主色，top2+ 灰阶）
  var curLen = cur.length;
  var fcLen = topList[0].forecast.length;
  var totalLen = curLen + fcLen;
  var allVals = [];
  for (var i = 0; i < curLen; i++) allVals.push(cur[i].cum);
  // 当前延伸（预测=保持，cum=1 在末点）
  allVals.push(1);
  var series = [{ name: '当前', data: cur.concat([{ date: '延伸', cum: 1 }]), color: '#3370ff', dashed: false }];
  for (var t = 0; t < topList.length; t++) {
    var fc = topList[t].forecast;
    var fcData = [];
    // 延伸起点对齐当前末点（cum=1）：用 top 时段的累计收益作为后续相对走势
    fcData.push({ date: cur[curLen - 1].date, cum: 1 });
    for (var k = 0; k < fc.length; k++) fcData.push({ date: fc[k].date, cum: fc[k].cum });
    series.push({ name: topList[t].startDate + '~' + topList[t].endDate, data: fcData, color: t === 0 ? '#e6a23c' : '#9e9e9e', dashed: true, corr: topList[t].corr });
    for (var v = 0; v < fc.length; v++) allVals.push(fc[v].cum);
  }
  var yMin = Math.min.apply(null, allVals) * 0.97;
  var yMax = Math.max.apply(null, allVals) * 1.03;
  if (yMax <= yMin) yMax = yMin + 1;
  // 2026-07-20 走势叠加图放大：去掉固定 height=200(配合 preserveAspectRatio=meet 在宽容器下左右大量留白),
  // 改 width:100% + height:auto 让 SVG 按 viewBox 比例撑满容器宽度;H 220->260 适度加高纵向空间。
  var W = 820, H = 260, ml = 56, mr = 12, mt = 8, mb = 28;
  var pw = W - ml - mr, ph = H - mt - mb;
  var sx = function (i) { return ml + (totalLen > 1 ? (i / (totalLen - 1)) * pw : 0); };
  var sy = function (v) { return mt + ph - ((v - yMin) / (yMax - yMin)) * ph; };
  var baselineY = sy(1);
  var xTicks = Math.min(7, totalLen);
  var xLabels = '';
  for (var xt = 0; xt < xTicks; xt++) {
    var xi = Math.min(Math.round(xt * (totalLen - 1) / (xTicks - 1)), totalLen - 1);
    var xLabel = xi < curLen ? cur[xi].date : (xi === curLen ? '今' : '+D' + (xi - curLen));
    xLabels += '<text x="' + sx(xi).toFixed(1) + '" y="' + (H - 6) + '" text-anchor="middle" font-size="9" fill="var(--text-3)">' + xLabel + '</text>';
  }
  var yLabels = '';
  var yTicks = [yMin, (yMin + yMax) / 2, 1, yMax];
  for (var yi = 0; yi < yTicks.length; yi++) {
    var yv = yTicks[yi];
    if (yv < yMin || yv > yMax) continue;
    yLabels += '<text x="' + (ml - 4) + '" y="' + sy(yv).toFixed(1) + '" text-anchor="end" font-size="9" fill="var(--text-3)" dominant-baseline="middle">' + ((yv - 1) * 100).toFixed(1) + '%</text>';
  }
  var paths = '';
  // 当前实线（只画 curLen 段，不含延伸点）rank=0 基准
  var curPts = cur.map(function (d, i) { return sx(i).toFixed(1) + ',' + sy(d.cum).toFixed(1); }).join(' ');
  paths += '<polyline class="shape-line" data-shape-rank="0" points="' + curPts + '" fill="none" stroke="' + series[0].color + '" stroke-width="2" stroke-linejoin="round"/>';
  // 各延伸虚线：从当前末点 (sx(curLen-1), sy(1)) 连到延伸各点（x 偏移到延伸区）
  for (var s = 1; s < series.length; s++) {
    var fcData = series[s].data;
    var pts = (sx(curLen - 1).toFixed(1) + ',' + sy(1).toFixed(1));
    for (var f = 1; f < fcData.length; f++) {
      pts += ' ' + sx(curLen - 1 + f).toFixed(1) + ',' + sy(fcData[f].cum).toFixed(1);
    }
    var ls = _shapeLineStyle(s);
    paths += '<polyline class="shape-line" data-shape-rank="' + s + '" points="' + pts + '" fill="none" stroke="' + series[s].color + '" stroke-width="' + ls.width + '" stroke-dasharray="5,3" stroke-linejoin="round" opacity="' + ls.opacity + '"/>';
  }
  // 末点圆点 + 分隔线（当前 vs 延伸）
  var sepX = sx(curLen - 1);
  // 大白话图例：实线=当前真实走势；虚线=历史上与当前最像的几个时段、它们随后的实际走势（仅供形态参考，非预测）
  // 2026-07-20 改：原 "top1/top2 + r=0.xx" 技术术语改为口语化（最像/第N像 + 相似度），并加一行总述 hint
  var legendItems = ['<span style="color:' + series[0].color + '">━ 当前近 ' + curLen + ' 日真实走势</span>'];
  for (var lg = 1; lg < series.length; lg++) {
    var rankWord = lg === 1 ? '最像' : '第 ' + lg + ' 像';
    legendItems.push('<span style="color:' + series[lg].color + '">┄ ' + rankWord + '的历史时段,随后 ' + fcLen + ' 日实际走势(相似度 ' + (series[lg].corr || 0).toFixed(2) + ')</span>');
  }
  legend = '<div style="font-size:12px;color:var(--text-2);margin:6px 0 2px;line-height:1.5">📊 <b>实线</b> = 当前真实走势;<b>虚线</b> = 历史上与当前最像的几个时段、它们随后的实际走势(仅供形态参考,不构成预测)</div>' +
    '<div style="display:flex;flex-wrap:wrap;gap:6px 14px;font-size:12px;margin:0">' + legendItems.join('') + '</div>';
  return '<div style="margin-top:6px">' +
    '<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="xMidYMid meet" style="display:block;width:100%;height:auto;border-radius:6px;background:var(--bg-hover)">' +
    '<line x1="' + ml + '" y1="' + baselineY.toFixed(1) + '" x2="' + (W - mr) + '" y2="' + baselineY.toFixed(1) + '" stroke="var(--border)" stroke-dasharray="3,3" stroke-width="1"/>' +
    '<line x1="' + sepX.toFixed(1) + '" y1="' + mt + '" x2="' + sepX.toFixed(1) + '" y2="' + (H - mb) + '" stroke="var(--border-strong)" stroke-width="1" stroke-dasharray="4,4"/>' +
    '<text x="' + (sepX + 3).toFixed(1) + '" y="' + (mt + 10) + '" font-size="9" fill="var(--text-3)">→ 延伸预测</text>' +
    yLabels + xLabels + paths +
    '<circle cx="' + sx(curLen - 1).toFixed(1) + '" cy="' + sy(1).toFixed(1) + '" r="3" fill="' + series[0].color + '" stroke="#fff" stroke-width="1"/>' +
    '</svg>' + legend + '</div>';
}
// 相似形态视图 HTML
async function _tradeSimShapeViewHTML(indexId) {
  var series = await _shapeLoadSeries(indexId);
  if (!series || !series.data || series.data.length < 30) {
    return '<div class="trade-sim-shape-empty">该指数暂不支持相似形态分析（数据源未覆盖或数据不足）。<br>当前支持：A 股宽基/红利、港股、美股/欧洲、主要商品、申万行业。</div>';
  }
  var closes = series.data.map(function (d) { return d.close; });
  var dates = series.data.map(function (d) { return d.date; });
  var CUR_LEN = 20, FORECAST_LEN = 20, TOP_N = 5, TOP_PLOT = 5;
  var result = _shapeMatch(closes, dates, CUR_LEN, FORECAST_LEN, TOP_N);
  if (!result) {
    return '<div class="trade-sim-shape-empty">数据不足：需要至少 ' + (CUR_LEN + FORECAST_LEN + 5) + ' 个交易日，当前 ' + closes.length + ' 个。</div>';
  }
  var idxName = series.name || indexId;
  var svg = _shapeMatchSVG(result, TOP_PLOT);
  // top5 列表
  var listRows = result.matches.map(function (m, i) {
    var corrPct = (m.corr * 100).toFixed(1) + '%';
    var corrColor = m.corr >= 0.7 ? '#e6492e' : m.corr >= 0.5 ? '#e6a23c' : 'var(--text-3)';
    // 延伸20日累计涨跌
    var endCum = m.forecast.length ? m.forecast[m.forecast.length - 1].cum : 1;
    var chgPct = ((endCum - 1) * 100).toFixed(2) + '%';
    var chgColor = endCum >= 1 ? '#e6492e' : '#2e8b57';
    return '<tr data-shape-rank="' + (i + 1) + '">' +
      '<td>top' + (i + 1) + '</td>' +
      '<td>' + m.startDate + ' ~ ' + m.endDate + '</td>' +
      '<td style="color:' + corrColor + ';font-weight:600">' + corrPct + '</td>' +
      '<td style="color:' + chgColor + '">' + (chgPct >= 0 ? '+' : '') + chgPct + '</td>' +
      '</tr>';
  }).join('');
  var listTable = '<table class="shape-match-table"><thead><tr><th>排名</th><th>历史时段</th><th>相关系数</th><th>后续' + FORECAST_LEN + '日涨跌</th></tr></thead><tbody>' + listRows + '</tbody></table>';
  return '<div class="trade-sim-shape-view">' +
    '<div class="trade-sim-shape-hint">🔮 取近 ' + CUR_LEN + ' 日<b>归一化日收益率</b>为当前形态，在 ' + idxName + ' 全历史（' + closes.length + ' 个交易日）中滑窗匹配皮尔逊相关最高的 ' + TOP_N + ' 个时段。<b>虚线为相似时段后续 ' + FORECAST_LEN + ' 日走势</b>（起点对齐当前末点），仅作形态参考非预测。</div>' +
    '<div class="trade-sim-shape-section"><div class="trade-sim-shape-section-title">走势叠加图(实线=当前,虚线=历史相似时段后续走势)</div>' + svg + '</div>' +
    '<div class="trade-sim-shape-section"><div class="trade-sim-shape-section-title">最相似 Top' + TOP_N + ' 时段</div>' + listTable + '</div>' +
    '</div>';
}

async function _tradeSimOpenModal(indexId, openView) {
  var ov = _tradeSimOverlayEl();
  _tradeSimState = {
    indexId: indexId,
    win: _TRADE_SIM_DEFAULT_WIN,
    path: 0,
    scenario: 0,
    view: openView === 'shape' ? 'shape' : 'backtest',   // A10 视图切换：backtest=回测详情 / shape=相似形态（lab.js 可直传 'shape'）
    statsData: null,
    fullData: null,
    fullLoaded: false,
    loadingFull: false,
    cmpSortCol: -1,    // 对比表当前排序列索引（-1=未排序，保持原始顺序）
    cmpSortDir: 'desc', // 当前排序方向 'asc'|'desc'
  };
  var body = ov.querySelector('.trade-sim-modal-body');
  body.innerHTML = '<div class="trade-sim-loading"><span class="sim-spinner"></span>加载回测中…</div>';
  ov.classList.add('show');
  document.body.style.overflow = 'hidden';
  try {
    _tradeSimState.statsData = _tradeSimStatsCache[indexId] || await _tradeSimFetchStats(indexId);
    _tradeSimStatsCache[indexId] = _tradeSimState.statsData;
  } catch (e) {
    body.innerHTML = '<div class="trade-sim-empty">⚠ 加载失败：' + (e.message || e) + '<br><br>可访问旧版：<a href="https://ssd.fx8.store/trade_sim/trade_sim_' + encodeURIComponent(indexId) + '.html" target="_blank">静态回测页</a></div>';
    return;
  }
  _tradeSimModalRender(ov);
}

// 渲染净值曲线 SVG（照搬 simulate_trade._equity_svg，主题色用 CSS 变量）
function _tradeSimEquitySVG(curve, initCap, gradId) {
  if (!curve || curve.length < 2) return '<div style="padding:20px;color:var(--text-3);text-align:center">净值数据不足</div>';
  var vals = curve.map(function (e) { return e.value; });
  var dates = curve.map(function (e) { return e.date; });
  var yMin = Math.min.apply(null, vals.concat([initCap])) * 0.95;
  var yMax = Math.max.apply(null, vals.concat([initCap])) * 1.05;
  if (yMax <= yMin) yMax = yMin + 1;
  var W = 800, H = 160, ml = 80, mr = 10, mt = 5, mb = 24;
  var pw = W - ml - mr, ph = H - mt - mb;
  var n = vals.length;
  var sy = function (v) { return mt + ph - ((v - yMin) / (yMax - yMin)) * ph; };
  var sx = function (i) { return ml + (n > 1 ? (i / (n - 1)) * pw : 0); };
  var baselineY = sy(initCap);
  var finalVal = vals[n - 1];
  var peakVal = Math.max.apply(null, vals);
  var peakIdx = vals.indexOf(peakVal);
  var minVal = Math.min.apply(null, vals);
  var pts = vals.map(function (v, i) { return sx(i).toFixed(1) + ',' + sy(v).toFixed(1); });
  var areaPts = pts.join(' ') + ' ' + sx(n - 1).toFixed(1) + ',' + (mt + ph).toFixed(1) + ' ' + sx(0).toFixed(1) + ',' + (mt + ph).toFixed(1);
  var fmtV = function (v) { return v >= 10000 ? (v / 10000).toFixed(1) + '万' : v.toFixed(0); };
  var yLabels = [
    { l: '起始', v: initCap, c: 'var(--text-3)' },
    { l: '最低', v: minVal, c: '#2e8b57' },
    { l: '峰值', v: peakVal, c: '#e6492e' },
    { l: '期末', v: finalVal, c: '#3370ff' },
  ].map(function (it) {
    return '<text x="' + (ml - 4) + '" y="' + sy(it.v).toFixed(1) + '" text-anchor="end" font-size="10" fill="' + it.c + '" dominant-baseline="middle">' + it.l + ' ' + fmtV(it.v) + '</text>';
  }).join('');
  var tickCount = Math.min(7, Math.max(3, Math.floor(n / 2)));
  var step = n > 1 ? (n - 1) / (tickCount - 1) : 1;
  var xLabels = [];
  for (var k = 0; k < tickCount; k++) {
    var i = Math.min(Math.round(k * step), n - 1);
    xLabels.push('<text x="' + sx(i).toFixed(1) + '" y="' + (H - 4) + '" text-anchor="middle" font-size="9" fill="var(--text-3)">' + dates[i].substring(0, 7) + '</text>');
  }
  var lineColor = finalVal >= initCap ? '#3370ff' : '#9e9e9e';
  return '<svg width="100%" height="150" viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="xMidYMid meet" style="display:block;margin-top:8px;border-radius:6px;background:var(--bg-hover)">' +
    '<defs><linearGradient id="' + gradId + '" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="' + lineColor + '" stop-opacity="0.12"/><stop offset="100%" stop-color="' + lineColor + '" stop-opacity="0.01"/></linearGradient></defs>' +
    '<line x1="' + ml + '" y1="' + baselineY.toFixed(1) + '" x2="' + sx(n - 1).toFixed(1) + '" y2="' + baselineY.toFixed(1) + '" stroke="var(--border)" stroke-dasharray="6,4" stroke-width="1"/>' +
    '<polygon points="' + areaPts + '" fill="url(#' + gradId + ')"/>' +
    '<polyline points="' + pts.join(' ') + '" fill="none" stroke="' + lineColor + '" stroke-width="1.5" stroke-linejoin="round"/>' +
    yLabels +
    '<circle cx="' + sx(peakIdx).toFixed(1) + '" cy="' + sy(peakVal).toFixed(1) + '" r="3" fill="#e6492e" stroke="#fff" stroke-width="1"/>' +
    '<circle cx="' + sx(n - 1).toFixed(1) + '" cy="' + sy(finalVal).toFixed(1) + '" r="3" fill="#3370ff" stroke="#fff" stroke-width="1"/>' +
    xLabels.join('') +
    '</svg>';
}

// 12卡（照搬 _scenario_panel 的 .sim-cards 12个卡片，字段不删不减）
function _tradeSimCardsHTML(s, initCap) {
  var ddStr = s.max_drawdown.toFixed(1) + '%';
  var ddDate = s.max_drawdown_date || 'N/A';
  var totalOps = s.buy_count + s.sell_count;
  var skippedTotal = s.skipped_full + s.skipped_no_cash + s.skipped_no_position;
  var signalTotal = totalOps + skippedTotal;
  return '<div class="sim-flow">' + s.flow_desc + '</div>' +
    '<div class="sim-cards">' +
    '<div class="sim-card"><span class="k">总资产变化</span><span class="v">' + _tradeSimFmtNum(s.total_capital) + ' -> ' + _tradeSimFmtNum(s.final_total) + ' 元<div class="sub" style="font-size:11px;color:var(--text-3);">期末持仓 ' + _tradeSimFmtNum(s.final_holdings) + ' 元</div></span></div>' +
    '<div class="sim-card"><span class="k">最大持仓</span><span class="v">' + _tradeSimFmtNum(s.max_holding) + ' 元（' + s.max_holding_pct + '%）<div class="sub">' + s.max_holding_date + '</div></span></div>' +
    '<div class="sim-card"><span class="k">总收益</span><span class="v" style="color:' + _tradeSimColorPct(s.total_return) + '">' + _tradeSimFmtNum(s.total_return) + ' 元（' + (s.total_return_pct >= 0 ? '+' : '') + s.total_return_pct.toFixed(2) + '%）</span></div>' +
    '<div class="sim-card"><span class="k" title="首笔买入至今的复合年化收益。正值=平均每年赚这么多,可与银行理财/通胀对比。">年化收益率</span><span class="v" style="color:' + _tradeSimColorPct(s.annualized) + '">' + (s.annualized >= 0 ? '+' : '') + s.annualized.toFixed(1) + '%<div class="sub">首笔买入至今 ' + s.years + ' 年</div></span></div>' +
    '<div class="sim-card"><span class="k">总资产峰值</span><span class="v">' + _tradeSimFmtNum(s.total_assets_peak) + ' 元<div class="sub">' + s.total_assets_peak_date + '</div></span></div>' +
    '<div class="sim-card"><span class="k" title="历史从最高点到最低点的最大跌幅。衡量最坏情况下的亏损幅度。">最大回撤</span><span class="v" style="color:' + _tradeSimColorPct(-s.max_drawdown) + '">' + ddStr + '<div class="sub">' + ddDate + '</div></span></div>' +
    '<div class="sim-card"><span class="k">回撤中位数 / 回撤去极均值</span><span class="v" style="color:' + _tradeSimColorPct(-s.median_drawdown) + '">' + s.median_drawdown.toFixed(1) + '% / ' + s.trimmed_mean_drawdown.toFixed(1) + '%</span></div>' +
    '<div class="sim-card"><span class="k">总操作</span><span class="v">' + s.buy_count + '买/' + s.sell_count + '卖（' + totalOps + '次）<div class="sub">共 ' + signalTotal + ' 次信号 · <span title="仓位已满/现金不足/无持仓可卖时跳过不执行">跳过 ' + skippedTotal + ' 次</span> · <span title="同时持有的最大未平仓笔数">峰值并发 ' + s.max_positions_ever + ' 笔</span></div></span></div>' +
    '<div class="sim-card"><span class="k" title="盈利交易笔数÷总交易笔数。越高=胜出的交易占比越大。">胜率</span><span class="v">' + s.win_rate + '%（' + s.win_count + '胜/' + s.lose_count + '负）</span></div>' +
    '<div class="sim-card"><span class="k">最长连胜/连败</span><span class="v">' + s.max_win_streak + ' 轮 / ' + s.max_lose_streak + ' 轮</span></div>' +
    '<div class="sim-card"><span class="k" title="平均每笔盈利÷平均每笔亏损。>1=赚的时候比亏的时候赚得多。">平均盈亏比</span><span class="v">' + _tradeSimFmtNum(s.avg_pl_ratio) + '（均盈' + _tradeSimFmtNum(s.avg_win_pct) + '% / 均亏' + _tradeSimFmtNum(s.avg_loss_pct) + '%）</span></div>' +
    '<div class="sim-card"><span class="k">配对情况</span><span class="v">' + s.total_rounds + '笔成对 · ' + s.open_count + '笔未平仓</span></div>' +
    '</div>';
}

// 交易记录清单表（11列，照搬 _scenario_panel 的 ledger 表）
function _tradeSimLedgerHTML(ledger, indexName) {
  if (!ledger || !ledger.length) return '<div style="padding:12px;color:var(--text-3)">无交易记录</div>';
  var rows = ledger.map(function (entry, j) {
    var opClass = entry.op.indexOf('止损') >= 0 ? 'sell_stop_loss'
      : entry.op.indexOf('卖') >= 0 ? 'sell'
      : entry.op.indexOf('追买') >= 0 ? 'buy_special'
      : entry.op.indexOf('备买') >= 0 ? 'buy_backup'
      : entry.op.indexOf('辅买') >= 0 ? 'buy_aux' : 'buy';
    var opBadge = '<span class="ledger-op ' + opClass + '">' + entry.op + '</span>';
    var pctStr = (entry.return_pct >= 0 ? '+' : '') + entry.return_pct.toFixed(2) + '%';
    var pctColor = _tradeSimColorPct(entry.return_pct);
    var closeStr = entry.close.toFixed(2);
    var idxChg = entry.index_chg_pct;
    var idxChgStr;
    if (idxChg !== null && idxChg !== undefined) {
      idxChgStr = '<span style="color:' + _tradeSimColorPct(idxChg) + ';font-weight:600">' + (idxChg >= 0 ? '+' : '') + idxChg.toFixed(2) + '%</span>';
    } else {
      idxChgStr = '<span style="color:var(--text-3)">-</span>';
    }
    var sharesTrd = entry.shares_traded || 0;
    var sharesStr;
    if (sharesTrd > 0) sharesStr = '<span style="color:#e6492e;font-weight:600">+' + sharesTrd.toFixed(2) + '</span>';
    else if (sharesTrd < 0) sharesStr = '<span style="color:#2e8b57;font-weight:600">' + sharesTrd.toFixed(2) + '</span>';
    else sharesStr = '<span style="color:var(--text-3)">-</span>';
    var totalSh = entry.total_shares || 0;
    var totalShStr = totalSh > 0 ? totalSh.toFixed(2) : '<span style="color:var(--text-3)">0</span>';
    var hv = entry.holdings_value || 0;
    var hvStr = hv > 0 ? _tradeSimFmtNum(hv) : '<span style="color:var(--text-3)">0</span>';
    var amt = entry.amount;
    var amtStr;
    if (sharesTrd > 0) amtStr = _tradeSimFmtNum(amt) + ' <span style="font-size:10px;color:var(--text-3)">(←' + sharesTrd.toFixed(2) + '股)</span>';
    else if (sharesTrd < 0) amtStr = _tradeSimFmtNum(amt) + ' <span style="font-size:10px;color:var(--text-3)">(' + Math.abs(sharesTrd).toFixed(2) + '股->)</span>';
    else amtStr = _tradeSimFmtNum(amt);
    return '<tr>' +
      '<td>' + (j + 1) + '</td>' +
      '<td>' + entry.date + '</td>' +
      '<td style="white-space:nowrap">' + closeStr + '</td>' +
      '<td>' + idxChgStr + '</td>' +
      '<td>' + opBadge + '</td>' +
      '<td>' + amtStr + '</td>' +
      '<td>' + sharesStr + '</td>' +
      '<td>' + totalShStr + '</td>' +
      '<td>' + hvStr + '</td>' +
      '<td>' + _tradeSimFmtNum(entry.total_assets) + '</td>' +
      '<td style="color:' + pctColor + ';font-weight:600">' + pctStr + '</td>' +
      '</tr>';
  }).join('');
  return '<h3 style="margin:20px 0 2px;font-size:15px;">📒 交易记录清单（' + ledger.length + ' 笔，按时间轴）</h3>' +
    '<p style="margin:0 0 8px;font-size:11px;color:var(--text-3)">💡 买入：固定金额 -> 得份额；卖出：卖份额 -> 得市值（金额 ≠ 买入成本）。份额变动 +红/-绿，持仓市值 = 份额 × ' + indexName + '收盘价。</p>' +
    '<div class="sim-table-wrap"><table><thead><tr>' +
    '<th>#</th><th>日期</th><th>' + indexName + '收盘</th><th>较上条涨跌</th><th>操作</th><th>交易金额</th><th>份额变动</th><th>持仓份额</th><th>持仓市值</th><th>当前总资产</th><th>累计收益率</th>' +
    '</tr></thead><tbody>' + rows + '</tbody></table></div>';
}

// 未平仓持仓表（7列）
function _tradeSimOpenPositionsHTML(openPositions, s) {
  if (!openPositions || !openPositions.length) return '';
  var rows = openPositions.map(function (op, j) {
    return '<tr>' +
      '<td>' + (j + 1) + '</td>' +
      '<td>' + op.buy_date + '</td>' +
      '<td>' + op.buy_close + '</td>' +
      '<td>' + op.shares + '</td>' +
      '<td style="color:' + _tradeSimColorPct(op.pct) + ';font-weight:600">' + (op.pct >= 0 ? '+' : '') + op.pct.toFixed(2) + '%</td>' +
      '<td>' + _tradeSimFmtNum(op.current_value) + '</td>' +
      '<td style="color:' + _tradeSimColorPct(op.profit) + ';font-weight:600">' + (op.profit >= 0 ? '+' : '') + op.profit.toFixed(2) + '</td>' +
      '</tr>';
  }).join('');
  return '<h3 style="margin:20px 0 10px;font-size:15px;">📌 未平仓持仓（' + s.open_count + ' 笔，按最后交易日收盘价估值）</h3>' +
    '<div class="sim-table-wrap"><table><thead><tr><th>#</th><th>买入日期</th><th>买入价</th><th>份额</th><th>浮动盈亏%</th><th>当前市值</th><th>浮动盈亏</th></tr></thead><tbody>' + rows + '</tbody></table></div>';
}

// 已完成回合表（10列，含子回合展开）
// 持有时长按方案A计算：最早买入日 -> 卖出日(与左侧 buy_date 区间起点对齐)
// 兼容旧 JSON：后端曾把多笔分批建仓的子回合 hold_days 累加(原 bug 致 2037 天)，
// 前端按 buy_date 区间起点 + sell_date 重算覆盖后端值，避免重生 100 品种 JSON
function _tradeSimHoldDays(buyDateStr, sellDateStr) {
  // buyDateStr 可能是 "2023-08-22"(单笔) 或 "2023-08-22~2024-09-19"(区间)
  // 取区间最早日期(分隔符 ~ 前的部分)，计算到 sellDateStr 的天数
  var earliest = String(buyDateStr || '').split('~')[0].trim();
  var b = new Date(earliest);
  var s = new Date(sellDateStr);
  if (isNaN(b.getTime()) || isNaN(s.getTime())) return 0;
  return Math.max(0, Math.round((s - b) / 86400000));
}
function _tradeSimRoundsHTML(rounds) {
  if (!rounds || !rounds.length) return '';
  var rows = rounds.map(function (r, j) {
    var subRows = '';
    if (r._sub_rounds && r._sub_rounds.length > 1) {
      subRows = r._sub_rounds.map(function (sr) {
        return '<tr style="background:var(--bg-hover);font-size:11px;color:var(--text-2)">' +
          '<td colspan="2" style="padding-left:20px;border-left:3px solid var(--border-strong)">└ ' + sr.buy_date + '</td>' +
          '<td>' + sr.buy_close + '</td>' +
          '<td colspan="2"></td>' +
          '<td>' + sr.hold_days + ' 天</td>' +
          '<td style="color:' + _tradeSimColorPct(sr.pct) + ';font-weight:600">' + (sr.pct >= 0 ? '+' : '') + sr.pct.toFixed(2) + '%</td>' +
          '<td>' + _tradeSimFmtNum(sr.amount_in) + '</td>' +
          '<td>' + _tradeSimFmtNum(sr.amount_out) + '</td>' +
          '<td style="color:' + _tradeSimColorPct(sr.profit) + ';font-weight:600">' + (sr.profit >= 0 ? '+' : '') + sr.profit.toFixed(2) + '</td>' +
          '</tr>';
      }).join('');
    }
    return '<tr>' +
      '<td>' + (j + 1) + '</td>' +
      '<td>' + r.buy_date + '</td>' +
      '<td>' + r.buy_close + '</td>' +
      '<td>' + r.sell_date + '</td>' +
      '<td>' + r.sell_close + '</td>' +
      '<td>' + _tradeSimHoldDays(r.buy_date, r.sell_date) + ' 天</td>' +
      '<td style="color:' + _tradeSimColorPct(r.pct) + ';font-weight:600">' + (r.pct >= 0 ? '+' : '') + r.pct.toFixed(2) + '%</td>' +
      '<td>' + _tradeSimFmtNum(r.amount_in) + '</td>' +
      '<td>' + _tradeSimFmtNum(r.amount_out) + '</td>' +
      '<td style="color:' + _tradeSimColorPct(r.profit) + ';font-weight:600">' + (r.profit >= 0 ? '+' : '') + r.profit.toFixed(2) + '</td>' +
      '</tr>' + subRows;
  }).join('');
  return '<h3 style="margin:20px 0 10px;font-size:15px;">📋 已完成回合（' + rounds.length + ' 轮）</h3>' +
    '<div class="sim-table-wrap"><table><thead><tr>' +
    '<th>#</th><th>买入日期</th><th>买入价</th><th>卖出日期</th><th>卖出价</th><th>持有时长</th><th>盈亏%</th><th>投入</th><th>回收</th><th>净利润</th>' +
    '</tr></thead><tbody>' + rows + '</tbody></table></div>';
}

// 全局对比表（33行：3路径×11场景，每列最优/最差高亮，照搬 build_html 的对比表逻辑）
// 列定义：key=数据字段名,type='str'|'num',defaultDir=首次点击默认方向
//   - 数值指标越大越好的列默认 desc（高到低）
//   - 回撤类指标越小越好默认 asc（小到大）
//   - 字符串列默认 asc
var _TRADE_SIM_CMP_COLS = [
  { key: 'path', label: '策略', type: 'str', defaultDir: 'asc', title: '' },
  { key: 'sig', label: '信号', type: 'str', defaultDir: 'asc', title: '' },
  { key: 'final_total', label: '最终资产', type: 'num', defaultDir: 'desc', title: '' },
  { key: 'total_return_pct', label: '总收益率', type: 'num', defaultDir: 'desc', title: '' },
  { key: 'annualized', label: '年化', type: 'num', defaultDir: 'desc', title: '首笔买入至今的复合年化收益。正值=平均每年赚这么多,可与银行理财/通胀对比。' },
  { key: 'max_drawdown', label: '最大回撤', type: 'num', defaultDir: 'asc', title: '历史从最高点到最低点的最大跌幅。衡量最坏情况下的亏损幅度。' },
  { key: 'median_drawdown', label: '回撤中位数', type: 'num', defaultDir: 'asc', title: '' },
  { key: 'trimmed_mean_drawdown', label: '回撤去极均值', type: 'num', defaultDir: 'asc', title: '' },
  { key: 'win_rate', label: '胜率', type: 'num', defaultDir: 'desc', title: '盈利交易笔数÷总交易笔数。越高=胜出的交易占比越大。' },
  { key: 'total_ops', label: '交易笔数', type: 'num', defaultDir: 'desc', title: '' }
];

// 按 colIdx/dir 对 rows 排序。null/NaN/非数值 视为"无数据"恒排末尾，不受 dir 影响。
function _tradeSimCmpSortRows(rows, colIdx, dir) {
  if (colIdx < 0 || colIdx >= _TRADE_SIM_CMP_COLS.length) return rows;
  var col = _TRADE_SIM_CMP_COLS[colIdx];
  var factor = (dir === 'asc') ? 1 : -1;
  return rows.slice().sort(function (a, b) {
    var av = a[col.key], bv = b[col.key];
    if (col.type === 'str') {
      var as = (av == null) ? '' : String(av);
      var bs = (bv == null) ? '' : String(bv);
      if (as === '' && bs === '') return 0;
      if (as === '') return 1;   // 空值末尾
      if (bs === '') return -1;
      return as.localeCompare(bs, 'zh') * factor;
    }
    // num: null/NaN/Infinity 一律视为 null（无数据），恒排末尾
    var an = (typeof av === 'number' && isFinite(av)) ? av : null;
    var bn = (typeof bv === 'number' && isFinite(bv)) ? bv : null;
    if (an === null && bn === null) return 0;
    if (an === null) return 1;   // null 末尾，不随 dir 翻转
    if (bn === null) return -1;
    if (an === bn) return 0;
    return (an < bn ? -1 : 1) * factor;
  });
}

function _tradeSimComparisonTableHTML(sd, win) {
  var rows = [];
  var paths = sd.paths, scenarios = sd.scenarios;
  for (var pi = 0; pi < paths.length; pi++) {
    for (var si = 0; si < scenarios.length; si++) {
      var s = sd.data[win][paths[pi]][scenarios[si]].summary;
      rows.push({
        path: paths[pi], sig: scenarios[si],
        final_total: s.final_total,
        total_return_pct: s.total_return_pct,
        annualized: s.annualized,
        max_drawdown: s.max_drawdown,
        median_drawdown: s.median_drawdown,
        trimmed_mean_drawdown: s.trimmed_mean_drawdown,
        win_rate: s.win_rate,
        total_ops: s.buy_count + s.sell_count,
      });
    }
  }
  // 应用当前排序状态（-1=未排序保持原序）
  var sortCol = (_tradeSimState && _tradeSimState.cmpSortCol != null) ? _tradeSimState.cmpSortCol : -1;
  var sortDir = (_tradeSimState && _tradeSimState.cmpSortDir) || 'desc';
  if (sortCol >= 0) {
    rows = _tradeSimCmpSortRows(rows, sortCol, sortDir);
  }
  var bestFinal = Math.max.apply(null, rows.map(function (r) { return r.final_total; }));
  var bestReturn = Math.max.apply(null, rows.map(function (r) { return r.total_return_pct; }));
  var bestAnnual = Math.max.apply(null, rows.map(function (r) { return r.annualized; }));
  var bestDd = Math.min.apply(null, rows.map(function (r) { return r.max_drawdown; }));
  var bestMedianDd = Math.min.apply(null, rows.map(function (r) { return r.median_drawdown; }));
  var bestTrimmedDd = Math.min.apply(null, rows.map(function (r) { return r.trimmed_mean_drawdown; }));
  var bestWin = Math.max.apply(null, rows.map(function (r) { return r.win_rate; }));
  var bestOps = Math.max.apply(null, rows.map(function (r) { return r.total_ops; }));
  var worstFinal = Math.min.apply(null, rows.map(function (r) { return r.final_total; }));
  var worstReturn = Math.min.apply(null, rows.map(function (r) { return r.total_return_pct; }));
  var worstAnnual = Math.min.apply(null, rows.map(function (r) { return r.annualized; }));
  var worstDd = Math.max.apply(null, rows.map(function (r) { return r.max_drawdown; }));
  var worstMedianDd = Math.max.apply(null, rows.map(function (r) { return r.median_drawdown; }));
  var worstTrimmedDd = Math.max.apply(null, rows.map(function (r) { return r.trimmed_mean_drawdown; }));
  var worstWin = Math.min.apply(null, rows.map(function (r) { return r.win_rate; }));
  var worstOps = Math.min.apply(null, rows.map(function (r) { return r.total_ops; }));
  function cmpCell(val, best, worst, isPct, signed) {
    var isBest = Math.abs(val - best) < 0.001;
    var isWorst = Math.abs(val - worst) < 0.001;
    var styles = [];
    if (isBest) styles.push('background:var(--bg-best);font-weight:700');
    else if (isWorst) styles.push('background:var(--bg-worst);font-weight:700');
    if (signed) {
      if (val > 0) styles.push('color:#e6492e');
      else if (val < 0) styles.push('color:#2e8b57');
      else styles.push('color:#9e9e9e');
    }
    var styleAttr = styles.length ? ' style="' + styles.join(';') + '"' : '';
    var numStr;
    if (isPct) numStr = (val >= 0 ? '+' : '') + val.toFixed(2) + '%';
    else numStr = _tradeSimFmtNum(val);
    return '<span' + styleAttr + '>' + numStr + '</span>';
  }
  var body = rows.map(function (r) {
    return '<tr>' +
      '<td>' + r.path + '</td>' +
      '<td>' + r.sig + '</td>' +
      '<td>' + cmpCell(r.final_total, bestFinal, worstFinal, false, false) + ' 元</td>' +
      '<td>' + cmpCell(r.total_return_pct, bestReturn, worstReturn, true, true) + '</td>' +
      '<td>' + cmpCell(r.annualized, bestAnnual, worstAnnual, true, true) + '</td>' +
      '<td>' + cmpCell(r.max_drawdown, bestDd, worstDd, true, false) + '</td>' +
      '<td>' + cmpCell(r.median_drawdown, bestMedianDd, worstMedianDd, true, false) + '</td>' +
      '<td>' + cmpCell(r.trimmed_mean_drawdown, bestTrimmedDd, worstTrimmedDd, true, false) + '</td>' +
      '<td>' + cmpCell(r.win_rate, bestWin, worstWin, true, false) + '</td>' +
      '<td>' + cmpCell(r.total_ops, bestOps, worstOps, false, false) + ' 次</td>' +
      '</tr>';
  }).join('');
  // 表头：th 可点击切换排序，当前列显示 ▲(升序)/▼(降序)，其他列显示 ⇅(可排序提示)
  var headHTML = _TRADE_SIM_CMP_COLS.map(function (col, i) {
    var isActive = (i === sortCol);
    var arrow = isActive ? (sortDir === 'asc' ? '▲' : '▼') : '⇅';
    var cls = 'sim-cmp-sortable' + (isActive ? ' sim-cmp-active' : '');
    var titleAttr = col.title ? ' title="' + col.title + '"' : '';
    return '<th class="' + cls + '" data-cmp-col="' + i + '"' + titleAttr + '>' +
      '<span class="sim-cmp-th-label">' + col.label + '</span>' +
      '<span class="sim-cmp-arrow' + (isActive ? ' active' : '') + '">' + arrow + '</span>' +
      '</th>';
  }).join('');
  return '<div class="sim-cmp-table"><table><thead><tr>' +
    headHTML +
    '</tr></thead><tbody>' + body + '</tbody></table></div>';
}

// 场景面板：12卡 + 曲线 + 交易记录(懒加载) + 未平仓 + 回合表
function _tradeSimPanelHTML(winData, fullNode, indexName, initCap, gradId) {
  var s = winData.summary;
  var cards = _tradeSimCardsHTML(s, initCap);
  var equitySvg = '<h3 style="margin:20px 0 2px;font-size:15px;">📈 资产变化曲线</h3>' +
    '<p style="margin:0 0 4px;font-size:11px;color:var(--text-3)">虚线 = 初始资金 ' + _tradeSimFmtNum(initCap) + ' 元 · 蓝色 = 期末 · 红色 = 峰值 · 绿色 = 最低</p>' +
    _tradeSimEquitySVG(winData.equity_curve, initCap, gradId);
  // 交易记录/回合表/未平仓 从 full.json 懒加载
  var detailHTML;
  if (fullNode) {
    detailHTML = _tradeSimLedgerHTML(fullNode.ledger, indexName) +
      _tradeSimOpenPositionsHTML(fullNode.open_positions, s) +
      _tradeSimRoundsHTML(fullNode.rounds);
  } else {
    detailHTML = '<div style="padding:16px;text-align:center">' +
      '<button type="button" class="trade-sim-load-full" style="padding:8px 24px;border:1px solid var(--primary);border-radius:6px;background:var(--primary-bg);color:var(--primary);font-size:13px;cursor:pointer">📥 展开交易记录 / 回合明细 / 未平仓</button>' +
      '<div style="margin-top:6px;font-size:11px;color:var(--text-3)">点击懒加载完整数据（约 1-3MB）</div>' +
      '</div>';
  }
  return cards + equitySvg + detailHTML;
}

function _tradeSimModalRender(ov) {
  var m = _tradeSimState;
  if (!m || !m.statsData) return;
  var sd = m.statsData;
  var win = m.win;
  var pathIdx = m.path;
  var scenIdx = m.scenario;
  var pathLabel = sd.paths[pathIdx];
  var scenLabel = sd.scenarios[scenIdx];
  var indexName = sd.index_name;
  var initCap = sd.initial_capital || 100000;
  var winData = sd.data[win][pathLabel][scenLabel];
  var fullNode = (m.fullLoaded && m.fullData && m.fullData.data[win] && m.fullData.data[win][pathLabel] && m.fullData.data[win][pathLabel][scenLabel]) || null;
  var winLabel = '';
  for (var i = 0; i < _TRADE_SIM_WIN_DEFS.length; i++) {
    if (_TRADE_SIM_WIN_DEFS[i].k === win) { winLabel = _TRADE_SIM_WIN_DEFS[i].l; break; }
  }
  var viewTabs = '<div class="sim-view-tabs">' +
    '<button type="button" class="sim-view-tab' + (m.view === 'backtest' ? ' active' : '') + '" data-view="backtest">📊 回测详情</button>' +
    '<button type="button" class="sim-view-tab' + (m.view === 'shape' ? ' active' : '') + '" data-view="shape">🔮 相似形态</button>' +
    '</div>';
  ov.querySelector('.trade-sim-modal-title').textContent = indexName + (m.view === 'shape' ? ' · 历史相似形态匹配' : ' · 技术信号模拟回测（' + winLabel + '）');
  var body = ov.querySelector('.trade-sim-modal-body');
  // A10 相似形态视图：异步加载，加载完填入；用户切走则不覆盖
  if (m.view === 'shape') {
    body.innerHTML = viewTabs + '<div class="trade-sim-loading"><span class="sim-spinner"></span>加载相似形态分析…</div>';
    body.querySelectorAll('.sim-view-tab[data-view]').forEach(function (btn) {
      btn.onclick = function () { m.view = btn.dataset.view; _tradeSimModalRender(ov); };
    });
    (async function () {
      try {
        var html = await _tradeSimShapeViewHTML(m.indexId);
        if (_tradeSimState !== m || m.view !== 'shape') return;
        body.innerHTML = viewTabs + html;
        body.querySelectorAll('.sim-view-tab[data-view]').forEach(function (btn) {
          btn.onclick = function () { m.view = btn.dataset.view; _tradeSimModalRender(ov); };
        });
        // top5 列表 hover 高亮：tr hover 时对应 rank polyline 加粗高亮，其他虚线降透明（rank 0=当前实线基准不参与）
        body.querySelectorAll('.shape-match-table tbody tr[data-shape-rank]').forEach(function (tr) {
          var rank = tr.getAttribute('data-shape-rank');
          tr.addEventListener('mouseenter', function () {
            body.querySelectorAll('polyline.shape-line').forEach(function (pl) {
              var pr = pl.getAttribute('data-shape-rank');
              if (pr === '0') return;
              if (pr === rank) {
                pl.setAttribute('stroke-width', '3.5');
                pl.setAttribute('opacity', '1');
              } else {
                pl.setAttribute('opacity', '0.12');
              }
            });
          });
          tr.addEventListener('mouseleave', function () {
            body.querySelectorAll('polyline.shape-line').forEach(function (pl) {
              var pr = pl.getAttribute('data-shape-rank');
              if (pr === '0') return;
              var ls = _shapeLineStyle(parseInt(pr, 10));
              pl.setAttribute('stroke-width', ls.width);
              pl.setAttribute('opacity', ls.opacity);
            });
          });
        });
      } catch (e) {
        if (_tradeSimState !== m || m.view !== 'shape') return;
        body.innerHTML = viewTabs + '<div class="trade-sim-empty">⚠ 相似形态加载失败：' + (e.message || e) + '</div>';
        body.querySelectorAll('.sim-view-tab[data-view]').forEach(function (btn) {
          btn.onclick = function () { m.view = btn.dataset.view; _tradeSimModalRender(ov); };
        });
      }
    })();
    return;
  }
  // 吸顶窗口切换条
  var winBar = '<div class="lab-win-bar trade-sim-win-bar">' +
    '<span class="lab-win-bar-label">时间窗口</span>' +
    '<div class="lab-win-tabs">' + _TRADE_SIM_WIN_DEFS.map(function (w) {
      return '<button type="button" class="lab-win-tab' + (w.k === win ? ' active' : '') + '" data-win="' + w.k + '">' + w.l + '</button>';
    }).join('') + '</div>' +
    '<span class="lab-win-bar-cur">' + winLabel + '</span>' +
    '</div>';
  var cmpTable = _tradeSimComparisonTableHTML(sd, win);
  var mainTabs = '<div class="sim-main-tabs">' + sd.paths.map(function (p, i) {
    return '<button class="sim-main-tab' + (i === pathIdx ? ' active' : '') + '" data-path="' + i + '">' + p + '</button>';
  }).join('') + '</div>';
  var subTabs = '<div class="sim-sub-tabs">' + sd.scenarios.map(function (s, i) {
    return '<button class="sim-sub-tab' + (i === scenIdx ? ' active' : '') + '" data-sig="' + i + '">' + s + '</button>';
  }).join('') + '</div>';
  var gradId = 'tradeSimGrad_' + win + '_' + pathIdx + '_' + scenIdx;
  var panel = _tradeSimPanelHTML(winData, fullNode, indexName, initCap, gradId);
  body.innerHTML = viewTabs + winBar + cmpTable + mainTabs + '<div class="sim-path-group active">' + subTabs + panel + '</div>';
  // 绑定视图切换（A10）+ 窗口切换
  body.querySelectorAll('.sim-view-tab[data-view]').forEach(function (btn) {
    btn.onclick = function () { m.view = btn.dataset.view; _tradeSimModalRender(ov); };
  });
  body.querySelectorAll('.lab-win-tab[data-win]').forEach(function (btn) {
    btn.onclick = function () { m.win = btn.dataset.win; _tradeSimModalRender(ov); };
  });
  body.querySelectorAll('.sim-main-tab').forEach(function (btn) {
    btn.onclick = function () { m.path = parseInt(btn.dataset.path); _tradeSimModalRender(ov); };
  });
  body.querySelectorAll('.sim-sub-tab').forEach(function (btn) {
    btn.onclick = function () { m.scenario = parseInt(btn.dataset.sig); _tradeSimModalRender(ov); };
  });
  // 对比表列标题点击排序：同列=切方向，不同列=换列+用该列默认方向
  body.querySelectorAll('.sim-cmp-table th[data-cmp-col]').forEach(function (th) {
    th.onclick = function () {
      var colIdx = parseInt(th.dataset.cmpCol);
      if (isNaN(colIdx)) return;
      if (m.cmpSortCol === colIdx) {
        // 同列：翻转方向
        m.cmpSortDir = (m.cmpSortDir === 'asc') ? 'desc' : 'asc';
      } else {
        // 不同列：切到该列，用其默认方向
        m.cmpSortCol = colIdx;
        m.cmpSortDir = _TRADE_SIM_CMP_COLS[colIdx].defaultDir;
      }
      _tradeSimModalRender(ov);
    };
  });
  var loadFullBtn = body.querySelector('.trade-sim-load-full');
  if (loadFullBtn) {
    loadFullBtn.onclick = async function () {
      if (m.loadingFull) return;
      m.loadingFull = true;
      loadFullBtn.textContent = '加载中…';
      loadFullBtn.disabled = true;
      try {
        if (!m.fullLoaded) {
          m.fullData = _tradeSimFullCache[m.indexId] || await _tradeSimFetchFull(m.indexId);
          _tradeSimFullCache[m.indexId] = m.fullData;
          m.fullLoaded = true;
        }
        _tradeSimModalRender(ov);
      } catch (e) {
        loadFullBtn.textContent = '⚠ 加载失败，点击重试';
        loadFullBtn.disabled = false;
      } finally {
        m.loadingFull = false;
      }
    };
  }
}

function initSimOverlay() {
  // sim-btn 左键打开 modal（不再 iframe）；中键仍可新标签打开旧 HTML 兜底
  document.addEventListener('click', function (e) {
    var a = e.target.closest('.sim-btn');
    if (!a) return;
    // 仅左键拦截；中键/ctrl+点击放行新标签
    if (e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey) return;
    e.preventDefault();
    var indexId = a.dataset.index || 'sh';
    _tradeSimOpenModal(indexId);
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && _tradeSimOverlay && _tradeSimOverlay.classList.contains('show')) _tradeSimCloseModal();
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

function drawShareCard(r, futures) {
  const W = 1080, H = 1500;
  const canvas = document.createElement("canvas");
  canvas.width = W; canvas.height = H;
  const ctx = canvas.getContext("2d");
  // === 主题色读取层:canvas 不读 CSS var,运行时 getComputedStyle 取当前皮肤配色 ===
  // 涨红跌绿(#e6492e/#2e8b57)为数据语义色,二维码白底深码为扫码对比,均保持硬编码不随皮肤变
  const C = {
    bg: cssVar("--bg-card"),
    text1: cssVar("--text-1"),
    text2: cssVar("--text-2"),
    primary: cssVar("--primary"),
    border: cssVar("--border"),
  };
  const hexToRgb = (hex) => {
    const h = (hex || "").replace("#", "").trim();
    if (h.length === 6) { const n = parseInt(h, 16); return [(n >> 16) & 255, (n >> 8) & 255, n & 255]; }
    if (h.length === 3) { return [parseInt(h[0] + h[0], 16), parseInt(h[1] + h[1], 16), parseInt(h[2] + h[2], 16)]; }
    return [255, 255, 255];
  };
  const t1rgb = hexToRgb(C.text1), t2rgb = hexToRgb(C.text2), prgb = hexToRgb(C.primary);
  const rgba = (rgb, a) => `rgba(${rgb[0]},${rgb[1]},${rgb[2]},${a})`;
  const UP = "#e6492e", DOWN = "#2e8b57"; // 涨红跌绿(数据语义色,4 套皮肤均不变)
  const STRIP_EM = /[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}\u{2190}-\u{21FF}\u{2B00}-\u{2BFF}\u{FE00}-\u{FE0F}]/gu;

  // 背景渐变(跟随皮肤)
  const g = ctx.createLinearGradient(0, 0, 0, H);
  g.addColorStop(0, C.bg); g.addColorStop(1, C.bg);
  ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
  ctx.textBaseline = "alphabetic";

  // 顶部品牌条
  ctx.fillStyle = C.primary;
  _roundRect(ctx, 60, 60, 240, 64, 18); ctx.fill();
  ctx.fillStyle = C.text1; ctx.font = "bold 30px 'PingFang SC',sans-serif"; ctx.textBaseline = "middle";
  ctx.fillText("📊 tdsignal", 84, 93);
  ctx.fillStyle = C.text2; ctx.font = "26px 'PingFang SC',sans-serif";
  ctx.fillText("trade-data-signal", 320, 93);

  // 主标题
  ctx.textBaseline = "alphabetic";
  ctx.fillStyle = C.text1; ctx.font = "bold 76px 'PingFang SC',sans-serif";
  ctx.fillText("信号实验室", 60, 220);
  ctx.fillStyle = C.text2; ctx.font = "32px 'PingFang SC',sans-serif";
  ctx.fillText(`${fmtDate(r.date)} 收盘复盘`, 60, 272);

  // 分隔线
  ctx.strokeStyle = rgba(t1rgb, 0.15); ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(60, 296); ctx.lineTo(1020, 296); ctx.stroke();

  // === ★ 一句话结论(情绪分 + 信号 + 涨停) ===
  const drawConclusion = (y) => {
    const sc = (r.today && r.today.scores) || {};
    const sent = sc.a_sentiment ? sc.a_sentiment.value : null;
    let sentTag = sent != null ? sentimentTag(sent) : "";
    sentTag = sentTag.replace(STRIP_EM, "").trim();
    const sigs = r.signals_today || [];
    const buyN = sigs.filter((s) => /^buy/.test(s.signal)).length;
    const sellN = sigs.filter((s) => /^sell/.test(s.signal)).length;
    const mt = (r.today && r.today.metrics) || [];
    const zt = _metricVal(mt, "a_width_zt_count");
    const parts = [];
    if (sent != null) parts.push(`情绪${sent.toFixed(0)}${sentTag ? "[" + sentTag + "]" : ""}`);
    parts.push(`${sigs.length}信号(买${buyN}/卖${sellN})`);
    if (zt != null) parts.push(`涨停${zt.toFixed(0)}`);
    const text = "💡 " + parts.join(" · ");
    const boxH = 52;
    ctx.fillStyle = rgba(t1rgb, 0.05);
    _roundRect(ctx, 60, y, W - 120, boxH, 12); ctx.fill();
    ctx.strokeStyle = rgba(prgb, 0.4); ctx.lineWidth = 1.5;
    _roundRect(ctx, 60, y, W - 120, boxH, 12); ctx.stroke();
    ctx.fillStyle = C.primary;
    _roundRect(ctx, 60, y, 6, boxH, 3); ctx.fill();
    ctx.fillStyle = C.text1; ctx.font = "bold 28px 'PingFang SC',sans-serif"; ctx.textBaseline = "middle";
    ctx.fillText(text, 84, y + boxH / 2 + 1);
    ctx.textBaseline = "alphabetic";
    return y + boxH + 16;
  };

  // === 数据卡(情绪分 + 涨跌停/成交额) ===
  const scores = (r.today && r.today.scores) || {};
  const sentVal = scores.a_sentiment ? scores.a_sentiment.value : null;
  const crossVal = scores.cross_market ? scores.cross_market.value : null;
  const fgVal = scores.fear_greed ? scores.fear_greed.value : null;
  const sentCards = [
    { label: "A股情绪分", val: sentVal, tag: sentVal != null ? sentimentTag(sentVal) : "" },
    { label: "跨市场评分", val: crossVal, tag: crossVal != null ? sentimentTag(crossVal) : "" },
    { label: "恐贪指数", val: fgVal, tag: fgVal != null ? fearGreedLabel(fgVal) : "" },
  ];
  const metrics = (r.today && r.today.metrics) || [];
  const zt = _metricVal(metrics, "a_width_zt_count");
  const dt = _metricVal(metrics, "a_width_dt_count");
  const amt = _metricVal(metrics, "a_amount");
  const widthCards = [
    { label: "涨停", val: zt, color: UP },
    { label: "跌停", val: dt, color: DOWN },
    { label: "成交额(亿)", val: amt, color: C.primary },
  ];
  const cardW = 290, cardH = 124, gap = 18;
  const drawDataCard = (c, x, y) => {
    ctx.fillStyle = rgba(t1rgb, 0.06);
    _roundRect(ctx, x, y, cardW, cardH, 14); ctx.fill();
    ctx.strokeStyle = rgba(t1rgb, 0.12); ctx.lineWidth = 1;
    _roundRect(ctx, x, y, cardW, cardH, 14); ctx.stroke();
    ctx.fillStyle = C.text2; ctx.font = "26px 'PingFang SC',sans-serif";
    ctx.fillText(c.label, x + 22, y + 40);
    const v = c.val;
    ctx.fillStyle = c.color || C.text1; ctx.font = "bold 50px 'PingFang SC',sans-serif";
    const vText = v == null ? "-" : (typeof v === "number" && Math.abs(v) >= 1000 ? v.toFixed(0) : (typeof v === "number" ? v.toFixed(1) : v));
    ctx.fillText(vText, x + 22, y + 98);
    if (c.tag) {
      // 用数值字体(50px)测量宽度--切 tag 字体前测,否则 tag 叠到数值上
      const tw = ctx.measureText(vText).width;
      const tagText = "[" + c.tag.replace(STRIP_EM, "").trim() + "]";
      ctx.fillStyle = c.color || C.text2; ctx.font = "22px 'PingFang SC',sans-serif";
      ctx.fillText(tagText, x + 38 + tw, y + 98);
    }
  };

  // === ★ 8 指数迷你走势 2×4 网格 ===
  const drawIndicesSpark8 = (y) => {
    const sps = r.indices_sparkline || {};
    const keys = ["sh", "sz", "hs300", "sz50", "cyb", "kc50", "bj50", "csi500"];
    ctx.fillStyle = C.text2; ctx.font = "26px 'PingFang SC',sans-serif";
    ctx.fillText("8 指数近30日走势", 60, y);
    y += 20;
    const cols = 4, rows = 2, gap2 = 14;
    const cellW = (W - 120 - (cols - 1) * gap2) / cols;
    const cellH = 110;
    keys.forEach((k, idx) => {
      const col = idx % cols, row = Math.floor(idx / cols);
      const x = 60 + col * (cellW + gap2);
      const cy = y + row * (cellH + gap2);
      ctx.fillStyle = rgba(t1rgb, 0.04);
      _roundRect(ctx, x, cy, cellW, cellH, 10); ctx.fill();
      const it = sps[k];
      const nm = (it && it.name) || k;
      const pct = it && it.pct_change != null ? it.pct_change : null;
      const up = pct != null && pct >= 0;
      const col0 = up ? UP : DOWN;
      ctx.fillStyle = C.text1; ctx.font = "bold 23px 'PingFang SC',sans-serif";
      ctx.fillText(nm, x + 12, cy + 26);
      if (pct != null) {
        const sign = pct >= 0 ? "+" : "";
        const pctTxt = `${sign}${pct.toFixed(2)}%`;
        ctx.fillStyle = col0; ctx.font = "bold 22px 'PingFang SC',sans-serif";
        const tw = ctx.measureText(pctTxt).width;
        ctx.fillText(pctTxt, x + cellW - 12 - tw, cy + 26);
      }
      if (it && it.closes && it.closes.length > 1) {
        const sx = x + 12, sy = cy + 38, sw = cellW - 24, sh = cellH - 48;
        const closes = it.closes;
        const mn = Math.min(...closes), mx = Math.max(...closes);
        const range = mx - mn || 1;
        ctx.beginPath();
        closes.forEach((v, i) => {
          const px = sx + (i / (closes.length - 1)) * sw;
          const py = sy + sh - ((v - mn) / range) * sh;
          i === 0 ? ctx.moveTo(px, py) : ctx.lineTo(px, py);
        });
        ctx.strokeStyle = col0; ctx.lineWidth = 2.5; ctx.stroke();
      }
    });
    return y + rows * cellH + (rows - 1) * gap2 + 16;
  };

  // === ★ 期货机构净持仓迷你表(3 角色 × 5 列) ===
  const drawFuturesMini = (y, fut) => {
    ctx.fillStyle = C.text2; ctx.font = "26px 'PingFang SC',sans-serif";
    const fdate = fut && fut.summary && fut.summary.date ? fut.summary.date : (r.futures_date || "");
    ctx.fillText("期货机构净持仓" + (fdate ? `(${fdate})` : ""), 60, y);
    y += 20;
    const roles = (fut && fut.summary && fut.summary.roles) || {};
    const roleNames = [["机构(前20)", "机构前20"], ["中信期货", "中信"], ["国泰君安", "国君"]];
    const cols = [["沪深300期货", "沪深300"], ["中证500期货", "中证500"], ["上证50期货", "上证50"], ["中证1000期货", "中证1000"], ["综合", "综合"]];
    const x0 = 60, tableW = W - 120;
    const colW = tableW / (cols.length + 1);
    const headerH = 32, rowH = 38;
    const tableH = headerH + rowH * roleNames.length + 10;
    ctx.fillStyle = rgba(t1rgb, 0.05);
    _roundRect(ctx, x0, y, tableW, tableH, 10); ctx.fill();
    ctx.textBaseline = "middle";
    ctx.fillStyle = C.text2; ctx.font = "21px 'PingFang SC',sans-serif";
    ctx.fillText("角色", x0 + 12, y + headerH / 2 + 5);
    cols.forEach((c, i) => {
      ctx.fillText(c[1], x0 + colW * (i + 1) + 12, y + headerH / 2 + 5);
    });
    ctx.strokeStyle = rgba(t1rgb, 0.1); ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(x0 + 10, y + headerH + 4); ctx.lineTo(x0 + tableW - 10, y + headerH + 4); ctx.stroke();
    let ry = y + headerH + 8;
    roleNames.forEach((rn) => {
      const rd = roles[rn[0]] || {};
      ctx.fillStyle = C.text1; ctx.font = "bold 21px 'PingFang SC',sans-serif";
      ctx.fillText(rn[1], x0 + 12, ry + rowH / 2);
      cols.forEach((c, i) => {
        const v = rd[c[0]];
        ctx.fillStyle = v == null ? C.text2 : (v >= 0 ? UP : DOWN);
        ctx.font = "21px 'PingFang SC',sans-serif";
        const txt = v == null ? "-" : (v >= 0 ? "+" : "") + v.toFixed(0);
        ctx.fillText(txt, x0 + colW * (i + 1) + 12, ry + rowH / 2);
      });
      ry += rowH;
    });
    ctx.textBaseline = "alphabetic";
    return ry + 12;
  };

  // === ★ 行业涨跌 Top5(领涨/领跌双列横条) ===
  const drawIndustryBar = (y) => {
    y += 6; // 上填充:与上方期货表"国君"行拉开间距(原仅约5px,显挤)
    ctx.fillStyle = C.text2; ctx.font = "26px 'PingFang SC',sans-serif";
    ctx.fillText("行业涨跌 Top5", 60, y);
    y += 30; // 下填充:与子标题"领涨/领跌 Top5"拉开,消除文字重叠(原20致标题底与子标题顶重叠约3px)
    const heat = (r.industry_heatmap || []).slice().sort((a, b) => (b.pct_1d || 0) - (a.pct_1d || 0));
    const top5 = heat.slice(0, 5);
    const bot5 = heat.slice(-5).reverse();
    const colW = (W - 120 - 30) / 2;
    const itemH = 30;
    const drawCol = (items, cx, label, color) => {
      ctx.fillStyle = color; ctx.font = "bold 22px 'PingFang SC',sans-serif";
      ctx.fillText(label, cx, y);
      let iy = y + 24;
      const maxAbs = Math.max(...items.map((it) => Math.abs(it.pct_1d || 0)), 1);
      const rgbC = hexToRgb(color);
      items.forEach((it) => {
        const nm = (it.name || "").replace(/^SW\s*/, "");
        const pct = it.pct_1d || 0;
        ctx.fillStyle = C.text1; ctx.font = "21px 'PingFang SC',sans-serif";
        let nmDraw = nm;
        while (ctx.measureText(nmDraw).width > 150 && nmDraw.length > 1) nmDraw = nmDraw.slice(0, -1);
        if (nmDraw !== nm) nmDraw = nmDraw.slice(0, -1) + "…";
        ctx.fillText(nmDraw, cx, iy);
        const pctTxt = (pct >= 0 ? "+" : "") + pct.toFixed(2) + "%";
        ctx.fillStyle = color; ctx.font = "bold 20px 'PingFang SC',sans-serif";
        const tw = ctx.measureText(pctTxt).width;
        ctx.fillText(pctTxt, cx + colW - tw, iy);
        const barX0 = cx + 158, barX1 = cx + colW - tw - 10;
        const bw = (Math.abs(pct) / maxAbs) * (barX1 - barX0);
        ctx.fillStyle = rgba(rgbC, 0.85);
        _roundRect(ctx, barX0, iy - 7, Math.max(bw, 2), 7, 3.5); ctx.fill();
        iy += itemH;
      });
    };
    drawCol(top5, 60, "领涨 Top5", UP);
    drawCol(bot5, 60 + colW + 30, "领跌 Top5", DOWN);
    return y + 24 + 5 * itemH + 12;
  };

  // === 排版链(各区块返回下一区块 y) ===
  let y = drawConclusion(321);
  const cardStartY = y;
  sentCards.forEach((c, i) => drawDataCard(c, 60 + i * (cardW + gap), cardStartY));
  widthCards.forEach((c, i) => drawDataCard(c, 60 + i * (cardW + gap), cardStartY + cardH + gap));
  y = cardStartY + cardH * 2 + gap + 22;
  y = drawIndicesSpark8(y);
  y = drawFuturesMini(y, futures);
  y = drawIndustryBar(y);

  // 底部分隔 + 域名(分隔线让出右侧二维码区)
  ctx.strokeStyle = rgba(t1rgb, 0.15); ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(60, H - 150); ctx.lineTo(870, H - 150); ctx.stroke();
  ctx.fillStyle = C.primary; ctx.font = "bold 34px 'PingFang SC',sans-serif";
  ctx.fillText("ss.fx8.store", 60, H - 95);
  ctx.fillStyle = C.text2; ctx.font = "24px 'PingFang SC',sans-serif";
  ctx.fillText("盘后复盘·多市场情绪·技术分析参考点", 60, H - 55);
  // 底部免责水印(合规:教育研究定位,非投资建议)
  ctx.fillStyle = rgba(t2rgb, 0.7); ctx.font = "20px 'PingFang SC',sans-serif";
  ctx.fillText("本图仅供学习研究，不构成投资建议 · tdsignal", 60, H - 22);
  // 右下角二维码(白底深码,扫码对比不随皮肤变;矩阵来自 qr.js,fillRect 同步绘制,无图片加载竞态)
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
  // 期货机构净持仓(独立文件,失败不阻塞分享图,区块画占位)
  const futures = await fetchJSON("./data/futures.json").catch(() => null);
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
    const canvas = drawShareCard(r, futures);
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


// 通用"首次解释"弹窗：复用 onboarding 的 rule-modal 多步引导,localStorage 标记后不再弹。
// 参数：key(localStorage 键)/title(标题)/steps([{icon,title,body}])/delay(毫秒,首屏稳定后再弹)。
// 已有引导弹窗打开时自动延后,避免与 onboarding 等重叠；关闭时清理 DOM 与键盘监听。
function showIntroOnce(opts) {
  try { if (localStorage.getItem(opts.key)) return; } catch (e) { return; }
  const steps = opts.steps || [];
  if (!steps.length) return;

  const fire = () => {
    try { if (localStorage.getItem(opts.key)) return; } catch (e) { return; }
    // 已有引导弹窗打开则延后再试,避免重叠
    if (document.querySelector('.onboarding-modal:not(.hidden)')) { setTimeout(fire, 800); return; }

    let cur = 0;
    const modal = document.createElement('div');
    modal.className = 'rule-modal hidden onboarding-modal';
    modal.innerHTML =
      '<div class="rule-modal-overlay"></div>' +
      '<div class="rule-modal-body onboarding-body">' +
        '<div class="rule-modal-header"><h3>' + opts.title + '</h3></div>' +
        '<div class="onboarding-content"></div>' +
        '<div class="onboarding-footer">' +
          '<a class="onboarding-skip" href="javascript:void(0)">跳过,下次不再显示</a>' +
          '<div class="onboarding-nav">' +
            '<button class="onboarding-prev">上一步</button>' +
            '<span class="onboarding-dots"></span>' +
            '<button class="onboarding-next">下一步</button>' +
          '</div>' +
        '</div>' +
      '</div>';
    document.body.appendChild(modal);

    const contentEl = modal.querySelector('.onboarding-content');
    const dotsEl = modal.querySelector('.onboarding-dots');
    const prevBtn = modal.querySelector('.onboarding-prev');
    const nextBtn = modal.querySelector('.onboarding-next');
    const skipLink = modal.querySelector('.onboarding-skip');
    const overlay = modal.querySelector('.rule-modal-overlay');

    function renderDots() {
      dotsEl.innerHTML = steps.map(function (_, i) {
        return '<span class="onboarding-dot' + (i === cur ? ' active' : '') + '"></span>';
      }).join('');
    }
    function render() {
      const s = steps[cur];
      contentEl.innerHTML =
        '<div class="onboarding-step">' +
          '<div class="onboarding-icon">' + s.icon + '</div>' +
          '<div class="onboarding-step-title">' + s.title + '</div>' +
          '<div class="onboarding-step-body">' + s.body + '</div>' +
        '</div>';
      prevBtn.style.visibility = cur === 0 ? 'hidden' : 'visible';
      nextBtn.textContent = cur === steps.length - 1 ? '完成' : '下一步';
      renderDots();
    }
    function done() {
      try { localStorage.setItem(opts.key, '1'); } catch (e) {}
      modal.classList.add('hidden');
      document.body.style.overflow = '';
      document.removeEventListener('keydown', onKey);
      modal.remove();
    }
    function onKey(e) {
      if (e.key === 'Escape' && !modal.classList.contains('hidden')) done();
    }

    prevBtn.addEventListener('click', function () { if (cur > 0) { cur--; render(); } });
    nextBtn.addEventListener('click', function () {
      if (cur < steps.length - 1) { cur++; render(); } else { done(); }
    });
    skipLink.addEventListener('click', done);
    overlay.addEventListener('click', done);
    document.addEventListener('keydown', onKey);

    render();
    modal.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
  };

  setTimeout(fire, opts.delay || 900);
}

// P2-1: 首次访问 onboarding 3 步引导（localStorage 标记后不再弹）
function initOnboarding() {
  showIntroOnce({
    key: 'onboarding_done',
    title: '👋 新朋友,3 步看懂本站',
    delay: 900,
    steps: [
      {
        icon: '🌡️', title: '看情绪分',
        body: '综合情绪分 <b>0-100</b>,越低越恐慌。<b>≤20 是冰点</b>(人人恐慌,往往是历史低位),<b>≥80 是过热</b>(人人贪婪,常见于高位)。中间区域观望为主。'
      },
      {
        icon: '❄️', title: '看冰点共振',
        body: '多个宽基指数(上证50 / 沪深300 / 中证500 等)同时跌入冰点,称为<b>"冰点共振"</b>。历史上常对应市场低位区域,是逆向布局的参考信号(对应首页"共振冰点"卡片)。'
      },
      {
        icon: '🧪', title: '看策略实验室(进阶)',
        body: '想深入?策略实验室提供 <b>82 品种买卖点回测</b>、信号消融分析、蒙特卡洛模拟,帮你理解每个信号的历史表现与稳健性。'
      }
    ]
  });
}

initNavStickyToggle();
initStickyOffset();
initBackToTop();
initRuleButton();
initH5();
initSimOverlay();
initShareButton();
initThemeSwitcher();
initOnboarding();
initUpdateRules();

// === 主 tab hash 记忆 + 滚动位置恢复 ===
// 切 tab 写 hash（replaceState 不入历史、不触发 hashchange），F5 读 hash 恢复 tab + 滚动位置。
// #lab 开头归 lab.js 的 lab 恢复逻辑（含 #lab/策略key），此模块只管 4 个非 lab 主 tab。
// 大盘 tab 的二级 tab 也写进 hash：#market/{subtab}（如 #market/national-team=汪汪队），
// F5 刷新解析恢复二级 tab，避免刷新回退到默认 a 股。
const _MAIN_TABS = ["overview", "market", "sentiment", "industry", "etf"];
const _MARKET_SUBTABS = ["a-stock", "hk", "global", "futures", "national-team"];
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
