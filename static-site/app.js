// 静态版前端 —— 从 web/app.js 改造，数据源由 API 改为本地 JSON 文件。
// 改动点：
//   1. fetchJSON URL：/api/xxx → ./data/xxx.json（各 tab 按 range 读对应文件）
//   2. index 详情：读 https://ssd.fx8.store/index/{id}-all.json 全历史，前端按 ohlc 日期范围过滤 signals
//   3. 其他逻辑（render/ruleBar/signalColor/initBackToTop/initStickyOffset）保持功能一致
//   4. 手动补录入口已移除（与动态版一致）

// BUG-E：交互增强状态--industrySearch（行业搜索）/ heatmapRange（热力图近1日/近5日切换）。
// 注：原 indexFilter（A 股/港股 指数筛选 select）已重构为目录锚点 chip(2026-07-20), 始终全部渲染, 点击 chip 跳转吸顶, 不再需要筛选状态
// 筛选只控制前端显示哪些折线/行业，不影响后端数据。
const state = { tab: "overview", range: "3m", industrySearch: "", heatmapRange: "all", subtab: "a-stock", labIndex: "sh", labZone: "sell", labStrategy: null, labData: null, labSimData: null, labSimPair: null, labSimMode: "full_in", labSimPage: 0, intradaySnapshot: null, labWinSync: false, ntEtf: "510300", ntView: "overview", ntDetailRange: null, signalStats: null, sigGradeFilter: null, sigCorrectFilter: null, sigTypeFilter: null, sigWindowFilter: "0_15" };
const content = document.getElementById("content");
const charts = [];
// 已生成模拟回测页面的品种（📊 模拟回测按钮显示条件）
// 2026-07-20 根治：从 data/trade_sim_indices.json 动态加载（后端 simulate_trade.py 生成），
// 替代硬编码清单——避免新增回测指数后漏更新前端清单导致按钮误灰（cac40 等10指数事故）。
// initSimIndices() 启动时 fetch 填充；renderTab() await _simIndicesPromise 保证首渲前已就绪。
let SIM_INDICES = new Set();
let _simIndicesPromise = null;
function initSimIndices() {
  _simIndicesPromise = fetchJSON('./data/trade_sim_indices.json')
    .then(function (list) {
      SIM_INDICES = new Set(Array.isArray(list) ? list : []);
      // 别名(gold/us10y 等)映射到 g.* 实际文件，需加入 SIM_INDICES 使按钮亮起
      Object.keys(SIM_HREF_MAP).forEach(function (k) { SIM_INDICES.add(k); });
    })
    .catch(function (err) {
      console.error('[SIM_INDICES] trade_sim_indices.json 加载失败，按钮将全部灰色:', err);
      SIM_INDICES = new Set();
    });
  return _simIndicesPromise;
}
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
    // gating：基金评分 tab 为登录特权 fund_score，未登录点击弹提示不切换（双保险：applyAuthState 已隐藏按钮，此处防按钮被显示后绕过）
    if (b.dataset.tab === "fund" && !hasPrivilege('fund_score')) {
      openLoginPromptForFeature('基金评分', '基金评分为登录用户特权，登录后可查看 ETF/场外基金评分排行');
      return;
    }
    state.tab = b.dataset.tab;
    // market/sentiment/fund 共享 state.subtab，切 tab 时校验：非法值回退各自默认
    if (state.tab === "market") state.subtab = _MARKET_SUBTABS.includes(state.subtab) ? state.subtab : "a-stock";
    else if (state.tab === "sentiment") state.subtab = _SENTIMENT_SUBTABS.includes(state.subtab) ? state.subtab : "market-temp";
    else if (state.tab === "fund") state.subtab = _FUND_SUBTABS.includes(state.subtab) ? state.subtab : "etf";
    document.querySelectorAll("button[data-tab]").forEach((x) => x.classList.remove("active"));
    b.classList.add("active");
    updateH5Topbar();
    _setTabHash(state.tab);
    renderTab();
  };
});

function clearCharts() {
  _stopIntradayRefresh();
  // 切 tab 时 disconnect 所有指数目录锚点 scroll spy, 避免 observer 累积泄漏
  disconnectAllIndexNavSpies();
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
      // markPoint/markLine/markArea label 字体色按皮肤适配（canvas 不响应 CSS var，切皮肤需手动重注入）：
      // - markPoint: _autoLabelColor 按数据点 itemStyle.color 返回对比色（2026-07-23 修一刀切改黑色致暗色看不清）
      // - markLine: 分时图"昨收"基准线 label 跟 --text-3
      // - markArea: 分时图"午休"灰条 label 跟 --text-4
      // 2026-07-29 补 markLine/markArea：原仅处理 markPoint，切皮肤后分时图"昨收"/"午休"label
      // 保留旧皮肤色（暗色皮肤灰底灰字看不清），此处补齐重注入。
      if (opt.series && opt.series.length) {
        var mlColor = cssVar("--text-3");
        var maColor = cssVar("--text-4");
        var seriesUpd = opt.series.map(function (s) {
          if (!s) return null;
          var patches = {};
          // markPoint label：按 itemStyle.color 重新评估对比色
          if (s.markPoint && Array.isArray(s.markPoint.data)) {
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
            if (dataChanged) patches.markPoint = { data: newData };
          }
          // markLine label："昨收"基准线 label 跟皮肤（label 在 per-data 项内）
          if (s.markLine && Array.isArray(s.markLine.data)) {
            var mlChanged = false;
            var newMlData = s.markLine.data.map(function (d) {
              if (!d || !d.label) return d;
              if (d.label.color === mlColor) return d;
              mlChanged = true;
              return Object.assign({}, d, { label: Object.assign({}, d.label, { color: mlColor }) });
            });
            if (mlChanged) patches.markLine = { data: newMlData };
          }
          // markArea label："午休"灰条 label 跟皮肤（label 在 markArea 级非 per-data）
          if (s.markArea && s.markArea.label && s.markArea.label.color !== maColor) {
            patches.markArea = { label: Object.assign({}, s.markArea.label, { color: maColor }) };
          }
          return Object.keys(patches).length ? patches : null;
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
// height 可选（第6参数，默认 300），用于单独压缩某张卡片图表高度。
function lineChart(title, series, opts = {}, hint = null, container = content, height = 300) {
  const multi = Array.isArray(series) && series.length && series[0] && series[0].data;
  const arr = multi ? series : [{ name: stripHtml(title), data: series }];
  const dates = [...new Set(arr.flatMap((s) => s.data.map((d) => d.date)))].sort();
  const c = mkCard(title, height, hint, container);
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
  if (s.signal === "estimate") return "#909399";  // 盘中预估点 灰（方案A补T日点，非真实信号，视觉区分）
  const r = s.reason || "";
  // 波段减仓 草绿 #8bc34a（国债波段仓管，减仓非清仓，与卖 #2e8b57 区分体现"没卖重"，2026-07-20）
  // 注意：波段止损仍走默认 #2e8b57（趋势破位清仓，归卖类）；止盈/趋势转弱/前买失效也不受影响
  if (r.includes("波段减仓")) return "#8bc34a";
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
  if (s.signal === "buy_special_filtered") return _t("sl_buy_special_filtered");  // 追买被h5过滤预览（ATR>0.03 OR 量价背离，灰色pin不删除）
  if (s.signal === "buy_backup") return "趋势转向";   // 备买 Supertrend 翻多
  if (s.signal === "sell_stop_loss") {
    const m = (s.reason || "").match(/ATR×([\d.]+)止损/);
    return m ? `ATR×${m[1]}${_t("word_stop_loss")}` : ("ATR" + _t("word_stop_loss"));  // 从 reason 动态提取倍数(csi_div=×4.5,其他=×3.5),数据驱动;底层规则从 Donchian20 下轨改为 ATR×3,2026-07-21 调 ATR×3.5 降频,趋势跟踪风控
  }
  if (s.signal === "band_hold") return _t("band_hold");  // 国债波段仓位管理 持有状态（2026-07-24）
  if (s.signal === "estimate") return "预估";  // 盘中预估点（方案A补T日点，非真实信号）
  const r = s.reason || "";
  // 波段减仓/止损（国债波段仓位管理，2026-07-24）：reason 含"波段减仓X%"/"波段止损X%"
  if (r.includes("波段减仓") || r.includes("波段止损")) {
    const m = r.match(/波段(减仓|止损)(\d+)%/);
    if (m) return "波段" + (m[1] === "减仓" ? _t("word_band_reduce") : _t("word_stop_loss")) + m[2] + "%";
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
      if (s.signal === 'band_hold') {
        // 波段持有 pin(2026-07-31): 默认隐藏 label + 走势线下方(反pin) + 小点半透明
        // 避免密集 band_hold pin 遮蔽走势线; hover 显示 label 文字
        const _c = signalColor(s);
        markData.push({
          coord: [date, y],
          value: signalLabel(s),
          reason: s.reason || "",
          symbol: 'circle',
          symbolSize: 6,
          symbolOffset: [0, 20],
          itemStyle: { color: _c, opacity: 0.5 },
          label: { show: false, color: _autoLabelColor(_c) },
          emphasis: { label: { show: true, color: _autoLabelColor(_c) } },
        });
      } else {
        markData.push({
          coord: [date, y],
          value: signalLabel(s),
          reason: s.reason || "",
          itemStyle: { color: signalColor(s) },
          label: { color: _autoLabelColor(signalColor(s)) },
        });
      }
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
// 2026-07-29 方案D 升级：打分单元从「单窗口 entry」改为「策略(path+scen二元组)」聚合 5 窗口指标后打分。
//   聚合维度：盈利窗口数(profitWins) / 年化中位(medianAnn) / 年化均值(meanAnn,展示用不打分) / 回撤中位(medianDd) / 最大回撤(maxDdAll,5窗口最差) / 样本总数(totalOpsSum)
//   原 steadyScore 单窗口打分(wrNorm*0.4+ddN*0.4+opsNorm*0.2)仅验证 entry 自身窗口，门槛"年化>回撤"不检查同策略其他窗口，
//   致"近1年·全仓·追买+追止损卖"(年化6.9%回撤4.1%)被推为"最稳健"，但同策略近10年-13.1%回撤84%严重不稳健。
//   方案D 多窗口综合分彻底根治：盈利窗口数>=3 门槛 + 5窗口中位归一化打分，防单窗口虚高。
// 三档选择改为全维度归一化综合分（策略级，3路径×11场景=33策略各自聚合5窗口）：
//   年化最高档 = 综合分最高（年化中位40% + 低回撤中位20% + 盈利窗口数20% + 样本20%）过滤 盈利>=3 AND 年化中位>=TH.ann
//   最稳健档  = 综合分最高（年化中位40% + 低回撤中位30% + 盈利窗口数20% + 样本10%）过滤 盈利>=3，门槛 steadyScore>=0.5
//   回撤最小档 = 5窗口最大回撤(maxDdAll)最小 过滤 年化中位>0 AND 样本>=TH.ddMinOps（取最差窗口的回撤，非最好窗口）
// chip val 两行：首行 {scenario}·{path缩写}；次行 "5窗口盈利X/5 · 年化中位+Y% · 均值+Z% · 回撤中位W%"（回撤最小档额外加"最大回撤V%"）
// 2026-07-29 追加年化均值(meanAnn)：与年化中位并列展示，中位防极值偏置/均值反映整体水平，两者并列更直观；meanAnn 只展示不打分
// 去重粒度：scenario+path 二元组（2026-07-29 方案D：打分单元为策略级，去重粒度从三元组降为二元组）
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
// 2026-07-29 方案D 三档打分单元从「单窗口 entry」改为「策略(path+scen二元组)」聚合 5 窗口指标后打分。
//   新增维度：盈利窗口数（5 窗口中年化>0 的数量）、年化中位、回撤中位、最大回撤（5 窗口最差）、样本总数。
//   原 steadyWinRate/steadyMaxDd 单窗口门槛删除（不适用于策略级聚合，由「盈利窗口数>=3」替代防小样本虚高）。
//   年化最高档：年化中位 >= TH.ann AND 盈利窗口数>=3（原年化单窗口门槛升级为多窗口中位+盈利数双门槛）
//   最稳健档：综合分 >=0.5 AND 盈利窗口数>=3（防近1年单窗口虚高被推为"稳健"，
//             2026-07-29 修复: 近1年·全仓·追买+追止损卖 年化6.9%回撤4.1%曾被推为"最稳健"，
//             但同策略近10年-13.1%回撤84%严重不稳健，多窗口综合分彻底根治）
//   回撤最小档：样本总数 >=3 AND 年化中位>0（原门槛升级为策略级，按「5窗口最大回撤」升序排，非单窗口最小回撤）
var _BACKUP_CHIP_THRESHOLDS = {
  ann: 3.0,           // 年化最高档门槛（默认/main）：年化中位 >=3% AND 盈利窗口数>=3
  steadyScore: 0.5,   // 最稳健档综合分 >=0.5（满分1.0）AND 盈利窗口数>=3
  ddMax: 15,          // 回撤最小档回撤（默认/main）：<=15%（5窗口最大回撤，最差窗口）
  ddMinOps: 3,        // 回撤最小档样本总数 >=3
  ddMinAnn: 0.0       // 回撤最小档年化中位 >0（防0%年化策略被推为"回撤最小"）
};
// market 分组门槛覆盖（仅 ann + ddMax，其余继承 _BACKUP_CHIP_THRESHOLDS 基础值）
var _BACKUP_CHIP_MARKET_OVERRIDE = {
  main:      { ann: 3.0, ddMax: 15 },  // 主板（A股宽基+红利）：维持 3%/15%
  gem:       { ann: 3.0, ddMax: 20 },  // 创业板：年化3% + 回撤放宽20%
  star:      { ann: 3.0, ddMax: 20 },  // 科创板：年化3% + 回撤放宽20%
  industry:  { ann: 2.0, ddMax: 15 },  // 行业（申万 sw_* + 同花顺 thsc_*）：年化降到2%
  global:    { ann: 2.0, ddMax: 15 },  // 全球（港股/美股/欧亚股指）：年化降到2%
  commodity: { ann: 3.0, ddMax: 15 }   // 商品/汇率/债（g.*）：维持3%/15%（波动大门槛不降）
};
// market 分类：显式 A股主板/红利 + 创业板/科创 + 前缀匹配 行业/全球/商品，默认 main
function _backupChipMarketOf(id) {
  if (id === 'cyb') return 'gem';
  if (id === 'kc50') return 'star';
  if (['sh','sz','sz50','hs300','csi500','csi1000','bj50','csi_div','div_lowvol','sz_div'].indexOf(id) >= 0) return 'main';
  if (['hsi','hscei','hstech','us_dji','us_ixic','us_ndx','us_spx','ftse100','dax','cac40','kospi','nikkei225'].indexOf(id) >= 0) return 'global';
  if (id.indexOf('hk_') === 0) return 'global';
  if (id.indexOf('g.') === 0) return 'commodity';
  if (id.indexOf('sw_') === 0 || id.indexOf('thsc_') === 0) return 'industry';
  return 'main';
}
// 按 id 取门槛（基础值 + market 覆盖）
function _backupChipThresholdsFor(id) {
  var m = _backupChipMarketOf(id);
  var override = _BACKUP_CHIP_MARKET_OVERRIDE[m] || {};
  return Object.assign({}, _BACKUP_CHIP_THRESHOLDS, override);
}
// 2026-07-25 walk-forward 优化黑名单（docs/walk-forward-action-plan.md 情况B+D）+
// 2026-07-25 方向D 黑名单分级：拆为「WF 确凿失效」(维持屏蔽) + 「小样本」(不屏蔽,加标注走三档)两级。
//
// _OVERFIT_FAILED_IDS（情况B WF 确凿失效，维持屏蔽）：信号经全样本调参后测试段反向退化
// （WF夏普 < 未过滤全样本），不进三档 chip 推荐，仅显示"过拟合/测试段失效"标注 chip。
// 2026-07-26 解禁更新：sz/cyb已解禁（固定0.05 WF有效，原网格过拟合判定不适用生产）；
//              csi500保留（D1卖固定0.05 WF无效wf=-0.949，非调参过拟合）；csi_div移小样本组。
//   csi500    : D1卖固定0.05 WF无效wf=-0.949，信号无效（非调参过拟合，维持屏蔽）
//
// _SMALL_SAMPLE_IDS（情况D 小样本，不屏蔽）：C1主买 测试段 n<30，统计意义弱。
// 2026-07-25 方向D：从原 _OVERFIT_OR_SMALL_SAMPLE_IDS 拆出，恢复三档 chip 显示，仅在 chip-row
// 前加"样本不足"标注 chip 提醒用户，让用户看到三档推荐的同时知道样本量限制。
//   hs300     : C1主买 测试段样本不足
//   kc50      : C1主买 数据短训练2年测1年
//   sw_801110 : C1主买 测试段样本不足
// 上证综指(sh)walk-forward 稳健(WFE 1.138,2026-07-25 P1 去 D1a 后)，不进黑名单，继续参与 chip 推荐。
var _OVERFIT_FAILED_IDS = new Set([
  'csi500'       // D1卖固定0.05 WF无效wf=-0.949，信号无效（非调参过拟合，维持屏蔽）
]);
var _SMALL_SAMPLE_IDS = new Set([
  'hs300',       // 情况D: C1主买 测试段样本不足
  'kc50',        // 情况D: C1主买 数据短训练2年测1年
  'sw_801110',   // 情况D: C1主买 测试段样本不足
  'csi_div'      // D1样本不足n=25，C1买WF强wfe=1.11走三档+标注
]);
// 兼容旧引用（如有外部脚本引用 _OVERFIT_OR_SMALL_SAMPLE_IDS）：合并视图，只读
var _OVERFIT_OR_SMALL_SAMPLE_IDS = new Set(Array.from(_OVERFIT_FAILED_IDS).concat(Array.from(_SMALL_SAMPLE_IDS)));
// 2026-07-27 sharpe>3 可疑过拟合红线(NOTES §48 教训③:Bailey 2014 夏普>3 可疑/>5 必过拟合阈值,
// cgb_idx 3.58 为红线案例)。trade_sim summary.sharpe 为事件稀疏 equity_curve 收益率 sqrt(252) 年化
// 近似值(与 lab_simulate.py L241-261 同口径),值偏高;红线为"可疑"提示非"必过拟合"判定,数据透明让用户判断。
// 遍历全 165 回测(5窗口×3路径×11场景)找 max sharpe;>3 触发红线 chip 前置标注+row 红框修饰。
var _SHARPE_REDLINE_THRESHOLD = 3.0;
// 2026-07-20 chip 警示文案优化(方案C): _sharpeRedlineInfo 增强返回 globalMaxSource(来源 wkey/pkey/skey+中文label)
// 让警示条区分"全局max来自三档推荐"vs"全局max来自非三档推荐策略"两种情况,避免全局 10.59 误导三档推荐判断
function _sharpeRedlineInfo(sd) {
  if (!sd || !sd.data) return { maxSharpe: null, isRedline: false, maxSource: null };
  var maxSharpe = -Infinity;
  var hasSharpe = false;
  var maxWkey = null, maxPkey = null, maxSkey = null;
  for (var wkey in sd.data) {
    var byWin = sd.data[wkey];
    if (!byWin) continue;
    for (var pkey in byWin) {
      var byPath = byWin[pkey];
      if (!byPath) continue;
      for (var skey in byPath) {
        var s = byPath[skey] && byPath[skey].summary;
        if (s && typeof s.sharpe === 'number' && isFinite(s.sharpe)) {
          hasSharpe = true;
          if (s.sharpe > maxSharpe) {
            maxSharpe = s.sharpe;
            maxWkey = wkey; maxPkey = pkey; maxSkey = skey;
          }
        }
      }
    }
  }
  // 来源信息: 窗口/路径中文 label(sd.windows.l 优先, _BACKUP_CHIP_PATH_SHORT 兜底), path|scen 二元组键(供三档推荐匹配用)
  var maxSource = null;
  if (hasSharpe) {
    var winLab = maxWkey;
    if (sd.windows) {
      for (var i = 0; i < sd.windows.length; i++) {
        if (sd.windows[i].k === maxWkey) { winLab = sd.windows[i].l; break; }
      }
    }
    var pathLab = _BACKUP_CHIP_PATH_SHORT[maxPkey] || maxPkey;
    var scenLab = maxSkey.replace(/\+卖$/, '');
    maxSource = {
      wkey: maxWkey, pkey: maxPkey, skey: maxSkey,
      winLabel: winLab, pathShort: pathLab, scenarioLabel: scenLab,
      pathScenKey: maxPkey + '|' + maxSkey  // 与三档 entry 的 scenario|path 键同构,供匹配判断来源是否在三档推荐内
    };
  }
  return {
    maxSharpe: hasSharpe ? maxSharpe : null,
    isRedline: hasSharpe && maxSharpe > _SHARPE_REDLINE_THRESHOLD,
    maxSource: maxSource
  };
}
// chip-row 容器 className 拼装:base + small-sample 修饰 + sharpe-redline 修饰
// sd 可为 null(未缓存),此时只加 small-sample 修饰;sd 加载后异步 patch redline 修饰
function _chipRowClassName(id, sd) {
  var cls = "signal-chip-row";
  if (id && _SMALL_SAMPLE_IDS.has(id)) cls += " chip-row-small-sample";
  if (sd) {
    var si = _sharpeRedlineInfo(sd);
    if (si.isRedline) cls += " chip-row-sharpe-redline";
  }
  return cls;
}
// 在 chart-card 的 h3 之后插入独立 chip-row 容器（标题下换行单独一行展示）。
// SIM_INDICES 之外的指数不显示；已缓存数据同步渲染，未缓存先占位再异步 fetch+patch。
function _appendBackupChipRow(cardEl, id) {
  if (!SIM_INDICES.has(id)) return;
  var cachedSd = _tradeSimStatsCache[id];
  var html = _backupSignalChipRender(cachedSd, id);
  var row = document.createElement("div");
  // 2026-07-20 样本不足品种:row 加 modifier class,配合 CSS 给三档容器加淡蓝背景框+左侧蓝粗边框,
  // 让用户看 3 色 chip 时一眼知道该品种样本不足(WF 测试段 n<30,统计意义弱),区别于过拟合(单橙红 chip 不进三档)与正常三档
  // 2026-07-27 sharpe>3 红线:row 加 chip-row-sharpe-redline 修饰(红框),cachedSd 在手时同步加,否则异步 patch
  row.className = _chipRowClassName(id, cachedSd);
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
    var html = _backupSignalChipRender(sd, id);
    var placeholders = document.querySelectorAll('.signal-chip-row[data-chip-id="' + id + '"]');
    // 2026-07-27 sharpe>3 红线:sd 加载后同步 patch row className(加/去 chip-row-sharpe-redline 修饰)
    var rowCls = _chipRowClassName(id, sd);
    placeholders.forEach(function (el) { el.innerHTML = html; el.className = rowCls; });
  } catch (e) {
    var errEls = document.querySelectorAll('.signal-chip-row[data-chip-id="' + id + '"]');
    errEls.forEach(function (el) { el.innerHTML = '<span class="signal-chip signal-chip-error">⚠ 回测加载失败</span>'; });
  } finally {
    _backupChipLoading[id] = false;
  }
}
// 算三档 chip HTML（A+B 融合方案）：遍历全 165 回测，归一化综合分排名。数据不足返回空串。
function _backupSignalChipRender(sd, id) {
  if (!sd || !sd.data) return '';
  // 2026-07-27 sharpe>3 可疑过拟合红线(NOTES §48 教训③):遍历全 165 回测找 max sharpe,
  // >3 前置红线 chip 提醒(不屏蔽三档,让用户看推荐时知夏普越线需谨慎查详)。
  // trade_sim sharpe 为事件稀疏 equity_curve sqrt(252) 年化近似(与 lab 同口径),值偏高;
  // 标注为"可疑"非"必过拟合"判定,数据透明让用户判断。
  // 2026-07-20 chip 警示文案优化(方案C): 4 处误导点修复
  //   1) "可疑过拟合警示"->"夏普比率红线提示"(去"过拟合"强词,避免和 AZ26-AZ38 参数整治混淆)
  //   2) "部分回测"->"165回测中"(明确范围,用户知是全量回测 max)
  //   3) "夏普10.59"->"夏普比率最高{maxSharpe}来自{来源}"(强调是 max + 明示来源,避免全局 max 误导三档推荐判断)
  //   4) 加"参数侧已 AZ26-AZ38 整治"+"非必过拟合判定"(解释整治后为何还有红线 + 明确性质)
  //   基础版(无三档推荐场景: 黑名单/allEntries<2/三档全null) 用 globalMaxSharpe + globalMaxSource;
  //   完整版(有三档推荐) 在三档推荐算完后重新生成, 加 topTierMaxSharpe + 区分全局max是否来自三档推荐策略
  var sharpeInfo = _sharpeRedlineInfo(sd);
  var sharpeRedlinePrefix = '';
  if (sharpeInfo.isRedline) {
    var shVal = sharpeInfo.maxSharpe.toFixed(2);
    var src = sharpeInfo.maxSource || {};
    var srcStr = src.scenarioLabel ? ('来自' + _t.tsText(src.scenarioLabel) + '·' + _t.tsText(src.pathShort) + '·' + src.winLabel + ', ') : '';
    var tipSrcStr = src.scenarioLabel ? ('来自' + _t.tsText(src.scenarioLabel) + '·' + _t.tsText(src.pathShort) + '·' + src.winLabel + ', ') : '';
    sharpeRedlinePrefix = '<div class="overfit-warn-row overfit-warn-sharpe" data-tip="该品种165回测中夏普比率最高 ' + shVal + ' (' + tipSrcStr + 'Bailey(2014)学术可疑过拟合红线&gt;3)。交易模拟夏普为事件稀疏 净值曲线 收益率 √252 年化近似值(与 lab 同口径),值偏高;高夏普常源于低波动/小样本而非参数过拟合(参数侧已 AZ26-AZ38 整治)。非必过拟合判定,详见完整回测弹窗,历史表现不代表未来">⚠ 夏普比率红线提示: 该品种165回测中夏普比率最高 ' + shVal + ' (' + srcStr + 'Bailey(2014)学术可疑过拟合红线&gt;3); 交易模拟夏普为事件稀疏 √252 年化近似值, 值偏高, 高夏普常源于低波动/小样本而非参数过拟合(参数侧已 AZ26-AZ38 整治); 非必过拟合判定<span class="warn-tip">交易模拟夏普为事件稀疏 净值曲线 √252 年化近似(与 lab 同口径), 值偏高; 高夏普常源于低波动/小样本而非参数过拟合(参数侧已 AZ26-AZ38 整治); 非必过拟合判定, 详见完整回测弹窗</span></div>';
  }
  // 2026-07-25 方向D 黑名单分级：
  //   _OVERFIT_FAILED_IDS（WF 确凿失效）：维持屏蔽，仅显示过拟合标注 chip，不进三档
  //   _SMALL_SAMPLE_IDS（小样本 n<30）：不屏蔽，三档 chip 正常计算 + 前置"样本不足"标注 chip 提醒
  var smallSamplePrefix = '';
  if (id && _OVERFIT_FAILED_IDS.has(id)) {
    return sharpeRedlinePrefix + '<div class="overfit-warn-row overfit-warn-failed">⚠ 过拟合/测试段失效: 信号在滚动测试(walk-forward)段反向退化(滚动测试夏普 &lt; 未过滤全样本), 不进三档推荐<span class="warn-tip">该品种信号在滚动测试段反向退化(滚动测试夏普 &lt; 未过滤全样本), 不进三档推荐; 详见完整回测弹窗, 历史表现不代表未来</span></div>';
  }
  if (id && _SMALL_SAMPLE_IDS.has(id)) {
    smallSamplePrefix = '<div class="overfit-warn-row overfit-warn-sample" data-tip="该品种 C1主买(超卖拐点)信号在滚动测试(walk-forward)段样本量 n&lt;30,统计意义弱,三档推荐仅供谨慎参考;详见完整回测弹窗">📜 样本不足提示: C1主买(超卖拐点)测试段样本量 n&lt;30, 统计意义弱, 三档推荐仅供谨慎参考<span class="warn-tip">滚动测试段 n&lt;30 统计意义弱; 详见完整回测弹窗</span></div>';
  }
  // 窗口 key -> 中文 label 映射（优先用后端 sd.windows.l，缺失兜底硬编码；2026-07-23 chip 英文中文化）
  var winLabel = Object.assign(
    { y1: '近1年', y3: '近3年', y5: '近5年', y10: '近10年', all: '全史' },
    sd.windows ? Object.fromEntries(sd.windows.map(function (w) { return [w.k, w.l]; })) : {}
  );
  // 2026-07-29 方案D：打分单元从「单窗口 entry」改为「策略(path+scen二元组)」聚合 5 窗口指标。
  // 先收集所有 entry（allEntries 备用），同时构建 strategy_map: (path,scen) -> 5 窗口 summary 字典
  var allEntries = [];
  var strategyMap = {};  // key: path|scen -> { path, scenario, label, pathShort, winSummaries: {win: summary} }
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
          total_ops: s.total_ops,
          sharpe: typeof s.sharpe === 'number' ? s.sharpe : null
        });
        var skey = path + '|' + sc;
        if (!strategyMap[skey]) {
          strategyMap[skey] = {
            path: path, scenario: sc, label: sc.replace(/\+卖$/, ''),
            pathShort: _BACKUP_CHIP_PATH_SHORT[path] || path,
            winSummaries: {}
          };
        }
        strategyMap[skey].winSummaries[win] = s;
      }
    }
  }
  if (allEntries.length < 2) return sharpeRedlinePrefix;  // 不足 2 条无法对比,但仍显 sharpe 红线(若有)
  // 策略级聚合：每个策略聚合 5 窗口指标后打分
  // 聚合维度：盈利窗口数(profitWins) / 年化中位(medianAnn) / 回撤中位(medianDd) / 最大回撤(maxDdAll,5窗口最差) / 样本总数(totalOpsSum)
  function medianOf(arr) {
    if (!arr || arr.length === 0) return 0;
    var s = arr.slice().sort(function (a, b) { return a - b; });
    var n = s.length;
    return n % 2 === 1 ? s[(n - 1) / 2] : (s[n / 2 - 1] + s[n / 2]) / 2;
  }
  var strategies = [];
  for (var sk in strategyMap) {
    var strat = strategyMap[sk];
    var ws = strat.winSummaries;
    var anns = [], dds = [], ops = [], profitWins = 0;
    for (var i = 0; i < _BACKUP_CHIP_WINS.length; i++) {
      var w = _BACKUP_CHIP_WINS[i];
      var sm = ws[w];
      if (!sm) continue;
      anns.push(sm.annualized);
      dds.push(sm.max_drawdown);
      ops.push(sm.total_ops);
      if (sm.annualized > 0) profitWins++;
    }
    if (anns.length === 0) continue;
    // 2026-07-29 追加年化均值(meanAnn): 与 medianAnn 并列展示更直观(中位防极值偏置,均值反映整体水平)
    // 阈值过滤(盈利>=3)下均值与中位基于同组窗口算;meanAnn 只展示不打分(打分仍用 medianAnn)
    var meanAnn = anns.reduce(function (a, b) { return a + b; }, 0) / anns.length;
    strategies.push({
      path: strat.path, scenario: strat.scenario, label: strat.label, pathShort: strat.pathShort,
      winSummaries: ws,
      profitWins: profitWins,
      medianAnn: medianOf(anns),
      meanAnn: meanAnn,
      medianDd: medianOf(dds),
      maxDdAll: Math.max.apply(null, dds),  // 5 窗口最差回撤
      totalOpsSum: ops.reduce(function (a, b) { return a + b; }, 0),
      // 兼容旧 tooltip 字段（_backupSignalChipTip 用）
      annualized: medianOf(anns),  // 用年化中位作 tooltip 主年化展示
      max_drawdown: medianOf(dds), // 用回撤中位作 tooltip 主回撤展示
      win_rate: 0,                 // 策略级不再有单一胜率，tooltip 改展示聚合指标
      total_ops: ops.reduce(function (a, b) { return a + b; }, 0),
      sharpe: null,
      win: 'y5'                    // 占位，tooltip 已改为 5 窗口明细展示
    });
  }
  // 三档绝对值门槛过滤（防弱标的年化0.x%也推荐）：先筛达标候选，再归一化打分排序取最高。无达标 -> null
  // 2026-07-25 方向D：门槛按 market 分组差异化（_backupChipThresholdsFor 覆盖 ann/ddMax）
  // 2026-07-29 方案D：打分单元改为策略级，过滤+归一化均在「达标策略子集」内做（每档各自子集归一化）
  var TH = _backupChipThresholdsFor(id);
  function normalizeSubset(values) {
    // 在子集内归一化到 0-1
    if (values.length === 0) return [];
    var mn = Math.min.apply(null, values);
    var mx = Math.max.apply(null, values);
    if (mx > mn) return values.map(function (v) { return (v - mn) / (mx - mn); });
    return values.map(function () { return 0; });
  }
  function lowIsBetterSubset(values) {
    // 越小越好（如回撤）：归一化时取反
    if (values.length === 0) return [];
    var mn = Math.min.apply(null, values);
    var mx = Math.max.apply(null, values);
    if (mx > mn) return values.map(function (v) { return (mx - v) / (mx - mn); });
    return values.map(function () { return 1; });
  }
  // 1. 年化最高 = 策略级综合分最高（过滤: 盈利窗口数>=3 AND 年化中位>=TH.ann）
  //    打分 = 年化中位归一化*0.4 + 低回撤中位归一化*0.2 + 盈利窗口数归一化*0.2 + 样本总数归一化*0.2
  var annCand = strategies.filter(function (s) { return s.profitWins >= 3 && s.medianAnn >= TH.ann; });
  var bestAnn = null;
  if (annCand.length > 0) {
    var aA = annCand.map(function (s) { return s.medianAnn; });
    var aD = annCand.map(function (s) { return s.medianDd; });
    var aP = annCand.map(function (s) { return s.profitWins; });
    var aO = annCand.map(function (s) { return s.totalOpsSum; });
    var nA = normalizeSubset(aA), nD = lowIsBetterSubset(aD), nP = normalizeSubset(aP), nO = normalizeSubset(aO);
    var scoredAnn = annCand.map(function (s, i) {
      var score = nA[i] * 0.4 + nD[i] * 0.2 + nP[i] * 0.2 + nO[i] * 0.2;
      return Object.assign({}, s, { strongScore: score });
    });
    scoredAnn.sort(function (a, b) { return b.strongScore - a.strongScore; });
    bestAnn = scoredAnn[0];
  }
  // 2. 最稳健 = 策略级综合分最高（过滤: 盈利窗口数>=3）
  //    打分 = 年化中位归一化*0.4 + 低回撤中位归一化*0.3 + 盈利窗口数归一化*0.2 + 样本总数归一化*0.1
  //    门槛 steadyScore>=0.5（保留，防弱策略被推）
  var steadyCand = strategies.filter(function (s) { return s.profitWins >= 3; });
  var bestSteady = null;
  if (steadyCand.length > 0) {
    var sA = steadyCand.map(function (s) { return s.medianAnn; });
    var sD = steadyCand.map(function (s) { return s.medianDd; });
    var sP = steadyCand.map(function (s) { return s.profitWins; });
    var sO = steadyCand.map(function (s) { return s.totalOpsSum; });
    var mA = normalizeSubset(sA), mD = lowIsBetterSubset(sD), mP = normalizeSubset(sP), mO = normalizeSubset(sO);
    var scoredSteady = steadyCand.map(function (s, i) {
      var score = mA[i] * 0.4 + mD[i] * 0.3 + mP[i] * 0.2 + mO[i] * 0.1;
      return Object.assign({}, s, { steadyScore: score });
    });
    scoredSteady.sort(function (a, b) { return b.steadyScore - a.steadyScore; });
    for (var i = 0; i < scoredSteady.length; i++) {
      if (scoredSteady[i].steadyScore >= TH.steadyScore) { bestSteady = scoredSteady[i]; break; }
    }
  }
  // 3. 回撤最小 = 5 窗口最大回撤(maxDdAll)最小（过滤: 年化中位>0 AND 样本总数>=TH.ddMinOps）
  //    2026-07-29 方案D：按「5 窗口最大回撤」升序排（取最差窗口的回撤，非最好窗口），选「整体回撤最小」的策略
  var ddCand = strategies.filter(function (s) { return s.medianAnn > TH.ddMinAnn && s.totalOpsSum >= TH.ddMinOps; });
  var bestDd = null;
  if (ddCand.length > 0) {
    var sortedDd = ddCand.slice().sort(function (a, b) { return a.maxDdAll - b.maxDdAll; });
    bestDd = sortedDd[0];
  }
  // 构建 scored 数组供 _backupSignalChipTip Top5 展示（策略级，合并三档分数）
  var scored = strategies.map(function (s) {
    return Object.assign({}, s, {
      strongScore: bestAnn && bestAnn.path === s.path && bestAnn.scenario === s.scenario ? bestAnn.strongScore : 0,
      steadyScore: bestSteady && bestSteady.path === s.path && bestSteady.scenario === s.scenario ? bestSteady.steadyScore : 0
    });
  });
  // 去重：策略级 scenario+path 二元组只显 1 chip（优先级 年化>稳健>回撤）
  // 2026-07-29 方案D：打分单元已是策略级，去重粒度从原三元组(scenario+path+win)降为二元组(scenario+path)
  var used = {};
  var chips = [];
  if (bestAnn) { chips.push({ kind: 'strong', tier: '年化最高', entry: bestAnn }); used[bestAnn.scenario + '|' + bestAnn.path] = 1; }
  if (bestSteady) {
    var kS = bestSteady.scenario + '|' + bestSteady.path;
    if (!used[kS]) { chips.push({ kind: 'steady', tier: '最稳健', entry: bestSteady }); used[kS] = 1; }
  }
  if (bestDd) {
    var kD = bestDd.scenario + '|' + bestDd.path;
    if (!used[kD]) { chips.push({ kind: 'lowdraw', tier: '回撤最小', entry: bestDd }); used[kD] = 1; }
  }
  if (chips.length === 0) {
    // 三档全 null（弱标的整体不达标）：显示兜底文案，区别于三色档中性灰
    // 小样本品种仍前置标注 chip（让用户知道样本量限制，即便三档全不达标）
    // 2026-07-27 sharpe 红线品种仍前置红线 chip（即便三档全不达标，夏普越线信息仍需透明）
    return '<div class="signal-chip chip-weak-placeholder">📉 该标的回测表现均较弱，' + _t("weak_no_buypoint") + '（年化均<' + TH.ann + '%或样本不足）<span class="chip-tip">详见完整回测弹窗，历史表现不代表未来</span></div>' + sharpeRedlinePrefix + smallSamplePrefix;
  }
  // 2026-07-20 chip 警示文案优化(方案C): 三档推荐算完后, 重新生成 sharpeRedlinePrefix 完整版
  //   加 topTierMaxSharpe(三档推荐策略各自 maxSharpe 的最大值) + 区分全局max来源是否在三档推荐内
  //   情况a(全局max来自三档推荐): "来自三档推荐策略 X·Y·Z"
  //   情况b(全局max来自非三档推荐, 如 sw_801230 全局10.59来自追买+追止损卖非三档): "来自非三档推荐策略 X·Y·Z, 三档推荐策略夏普也均>3(最高6.91)"
  //   让用户明确区分"全局最高"vs"三档内最高", 不被全局10.59误导三档推荐判断
  if (sharpeInfo.isRedline) {
    var tierKeys = {};
    if (bestAnn) tierKeys[bestAnn.path + '|' + bestAnn.scenario] = 1;
    if (bestSteady) tierKeys[bestSteady.path + '|' + bestSteady.scenario] = 1;
    if (bestDd) tierKeys[bestDd.path + '|' + bestDd.scenario] = 1;
    var tierList = [bestAnn, bestSteady, bestDd];
    var tierSharps = [];
    for (var ti = 0; ti < tierList.length; ti++) {
      var tstrat = tierList[ti];
      if (!tstrat || !tstrat.winSummaries) continue;
      var tmax = -Infinity, thas = false;
      for (var twk in tstrat.winSummaries) {
        var tsm = tstrat.winSummaries[twk];
        if (tsm && typeof tsm.sharpe === 'number' && isFinite(tsm.sharpe)) {
          thas = true;
          if (tsm.sharpe > tmax) tmax = tsm.sharpe;
        }
      }
      if (thas) tierSharps.push(tmax);
    }
    var topTierMaxSharpe = tierSharps.length > 0 ? Math.max.apply(null, tierSharps) : null;
    var srcInTier = src.pathScenKey && tierKeys[src.pathScenKey];
    var srcTierLabel = srcInTier ? '三档推荐策略' : '非三档推荐策略';
    var srcStrFull = src.scenarioLabel ? ('来自' + srcTierLabel + ' ' + _t.tsText(src.scenarioLabel) + '·' + _t.tsText(src.pathShort) + '·' + src.winLabel + ', ') : '';
    var tierStr = '';
    if (topTierMaxSharpe !== null) {
      var tierMaxStr = topTierMaxSharpe.toFixed(2);
      tierStr = topTierMaxSharpe > _SHARPE_REDLINE_THRESHOLD
        ? '三档推荐策略夏普也均&gt;3(最高 ' + tierMaxStr + ', 详见各档标注), '
        : '三档推荐策略夏普均&lt;=3(最高 ' + tierMaxStr + ', 详见各档标注), ';
    }
    sharpeRedlinePrefix = '<div class="overfit-warn-row overfit-warn-sharpe" data-tip="该品种165回测中夏普比率最高 ' + shVal + ' (' + srcStrFull + 'Bailey(2014)学术可疑过拟合红线&gt;3)。交易模拟夏普为事件稀疏 净值曲线 收益率 √252 年化近似值(与 lab 同口径),值偏高;高夏普常源于低波动/小样本而非参数过拟合(参数侧已 AZ26-AZ38 整治)。' + tierStr + '非必过拟合判定,详见完整回测弹窗,历史表现不代表未来">⚠ 夏普比率红线提示: 该品种165回测中夏普比率最高 ' + shVal + ' (' + srcStrFull + 'Bailey(2014)学术可疑过拟合红线&gt;3); 交易模拟夏普为事件稀疏 √252 年化近似值, 值偏高, 高夏普常源于低波动/小样本而非参数过拟合(参数侧已 AZ26-AZ38 整治); ' + tierStr + '数据透明供判断, 非必过拟合判定<span class="warn-tip">交易模拟夏普为事件稀疏 净值曲线 √252 年化近似(与 lab 同口径), 值偏高; 高夏普常源于低波动/小样本而非参数过拟合(参数侧已 AZ26-AZ38 整治); ' + tierStr + '非必过拟合判定, 详见完整回测弹窗</span></div>';
  }
  // 2026-07-29 方案D：chip val 第二行统一改为策略级聚合指标显示
  //   原 line2 反映单窗口（"回撤-X% 胜率Y%" 或 "y1+X% y3+Y%..."），有误导（近1年虚高也能显示"回撤4%胜率66%"）
  //   新 line2: "5窗口盈利X/5 · 年化中位+Y% · 均值+Z% · 回撤中位W%"（三档统一，反映策略整体 5 窗口表现）
  //   2026-07-29 追加年化均值(meanAnn): 与年化中位并列,中位防极值偏置/均值反映整体水平,两者并列更直观
  //   回撤最小档额外加 "最大回撤V%"（该档核心指标是 5 窗口最大回撤，需明示）
  function formatVal(c) {
    var e = c.entry;
    var line1 = _t.tsText(e.label) + ' · ' + _t.tsText(e.pathShort);
    var annSign = e.medianAnn >= 0 ? '+' : '';
    var meanSign = e.meanAnn >= 0 ? '+' : '';
    // 2026-07-29 line2 追加年化均值(与中位并列): 中位防极值偏置,均值反映整体水平,两者并列更直观
    // 年化最高档用户最关心,三档统一显示保持一致性
    var line2 = '5窗口盈利' + e.profitWins + '/5 · 年化中位' + annSign + e.medianAnn.toFixed(1) + '% · 均值' + meanSign + e.meanAnn.toFixed(1) + '% · 回撤中位' + e.medianDd.toFixed(1) + '%';
    if (c.kind === 'lowdraw') {
      line2 += ' · 最大回撤' + e.maxDdAll.toFixed(1) + '%';  // 回撤最小档明示 5 窗口最大回撤（核心指标）
    }
    // 含费标注：ETF 替代品种显示 "ETF 代码·含费万3"，纯指数显示 "纯指数模拟·无ETF可交易"
    // sd.etf_code 由 simulate_trade.py _generate_json 写入（None=纯指数，agent3 重新生成 JSON 后才有值；
    // 旧 JSON 无此字段时 undefined -> 当作纯指数显示，避免 NaN/undefined 泄漏到 UI）
    // 2026-07-28 统一：board_etf_map 首位（approx 优先 false）。关联不到 ETF（如 nikkei/g.gold）-> 纯指数模拟·无ETF可交易
    var etfCode = sd && sd.etf_code;
    var line3 = etfCode ? ('ETF ' + etfCode + ' 模拟 · 含费万3') : '纯指数模拟 · 无ETF可交易';
    // 2026-07-20 改动2(方案C): line3 追加该档策略 maxSharpe(5窗口 winSummaries.sharpe 的 max), 越线(>3)加⚠
    //   让用户看三档各自策略真实夏普, 不被全局10.59误导(三档实际maxSharpe是6.91/6.91/3.43, 非10.59)
    if (e.winSummaries) {
      var esmx = -Infinity, eshas = false;
      for (var eswk in e.winSummaries) {
        var esm = e.winSummaries[eswk];
        if (esm && typeof esm.sharpe === 'number' && isFinite(esm.sharpe)) {
          eshas = true;
          if (esm.sharpe > esmx) esmx = esm.sharpe;
        }
      }
      if (eshas) {
        line3 += ' · 策略夏普' + esmx.toFixed(2);
        // 2026-07-30 分级符号: >3⚠(红线) / 2-3~(中等警示), 与 modal sim-card 颜色分级协同
        if (esmx > _SHARPE_REDLINE_THRESHOLD) line3 += '⚠';
        else if (esmx >= 2) line3 += '~';
      }
    }
    return { line1: line1, line2: line2, line3: line3 };
  }
  return chips.map(function (c) {
    var emoji = c.kind === 'strong' ? '📈' : c.kind === 'steady' ? '👍' : '🛡';
    var cls = c.kind === 'strong' ? 'signal-chip-strong' : c.kind === 'steady' ? 'signal-chip-steady' : 'signal-chip-lowdraw';
    var tip = _backupSignalChipTip(sd, scored, c);
    var v = formatVal(c);
    return '<span class="signal-chip ' + cls + '" data-tip="' + tip + '">' + emoji + ' ' + c.tier + ' · ' + v.line1 + '&#10;   ' + v.line2 + '&#10;   ' + v.line3 + '</span>';
  }).join('') + sharpeRedlinePrefix + smallSamplePrefix;
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
  // 2026-07-29 方案D：策略级（path+scen 二元组）打分，tooltip 显示 5 窗口聚合指标 + 33 策略 Top5
  var lines = ['【' + chip.tier + '】' + _t.tsText(e.label) + ' · ' + _t.tsText(e.pathShort) + ' · 5窗口综合分胜出'];
  // 顶部显示整体回测区间（all 窗口 s~e，覆盖最长历史；缺失则用 y5 兜底）
  var overallRange = winRange.all || winRange.y5 || '';
  if (overallRange) lines.push('回测区间: ' + overallRange);
  // 策略级聚合指标汇总（chip 上的 line2 完整版）
  lines.push('策略聚合（5 窗口）：盈利' + e.profitWins + '/5 │ 年化中位' + e.medianAnn.toFixed(1) + '% │ 年化均值' + e.meanAnn.toFixed(1) + '% │ 回撤中位' + e.medianDd.toFixed(1) + '% │ 最大回撤' + e.maxDdAll.toFixed(1) + '% │ 样本总数' + e.totalOpsSum);
  lines.push(_t("buypoint_path_label") + '在 5 窗口逐窗口表现（' + _t.tsText(e.scenario) + ' · ' + _t.tsText(e.path) + '）：');
  for (var i = 0; i < _BACKUP_CHIP_WINS.length; i++) {
    var w = _BACKUP_CHIP_WINS[i];
    var s = e.winSummaries && e.winSummaries[w];
    if (s) {
      // 每个窗口行末尾加 [s~e] 起止日期，让用户明确各窗口具体回测时段
      var rng = winRange[w] ? '  [' + winRange[w] + ']' : '';
      // 2026-07-30 夏普分级符号: >3⚠(红线) / 2-3~(中等警示), tooltip 纯文本无法着色, 用符号区分
      var shStr = typeof s.sharpe === 'number' ? s.sharpe.toFixed(2) : '-';
      var shSym = '';
      if (typeof s.sharpe === 'number' && isFinite(s.sharpe)) {
        if (s.sharpe > _SHARPE_REDLINE_THRESHOLD) shSym = '⚠';
        else if (s.sharpe >= 2) shSym = '~';
      }
      lines.push('  ' + winLabel[w] + '  年化' + (s.annualized || 0).toFixed(1) + '% │ 回撤' + (s.max_drawdown || 0).toFixed(1) + '% │ 胜率' + (s.win_rate || 0).toFixed(0) + '% │ 夏普' + shStr + shSym + ' │ 样本' + (s.total_ops || 0) + rng);
    }
  }
  // 全 33 策略该维度 Top5（策略级，非 entry 级 165）
  var top5, label;
  if (chip.kind === 'strong') {
    top5 = scored.slice().sort(function (a, b) { return b.strongScore - a.strongScore; }).slice(0, 5);
    label = '年化综合';
  } else if (chip.kind === 'steady') {
    top5 = scored.slice().sort(function (a, b) { return b.steadyScore - a.steadyScore; }).slice(0, 5);
    label = '稳健综合';
  } else {
    top5 = scored.slice().sort(function (a, b) { return a.maxDdAll - b.maxDdAll; }).slice(0, 5);
    label = '回撤最小（按5窗口最大回撤）';
  }
  lines.push(SEP);
  lines.push('全 33 策略（3路径×11场景）· ' + label + ' Top5：');
  for (var i = 0; i < top5.length; i++) {
    var t = top5[i];
    lines.push('  ' + (i + 1) + '. ' + _t.tsText(t.label) + '·' + _t.tsText(t.pathShort) + '  盈利' + t.profitWins + '/5 │ 年化中位' + t.medianAnn.toFixed(1) + '% │ 年化均值' + t.meanAnn.toFixed(1) + '% │ 回撤中位' + t.medianDd.toFixed(1) + '% │ 最大回撤' + t.maxDdAll.toFixed(1) + '% │ 样本' + t.totalOpsSum);
  }
  lines.push(SEP);
  // 2026-07-28 回测精准模拟说明：手续费万3 + 滑点千1 + 沪市过户费万0.1，ETF 替代指数含跟踪误差
  var etfCodeTip = sd && sd.etf_code;
  var feeLine = etfCodeTip
    ? '回测含费：佣金万3 + 滑点千1 + 沪市过户费万0.1，成交在 ETF ' + etfCodeTip + '（信号在指数生成，含跟踪误差）'
    : '回测含费：佣金万3 + 滑点千1（纯指数模拟，无过户费；ETF 替代品种才收沪市过户费）';
  lines.push(feeLine);
  lines.push('⚠ 研究参考，不构成投资建议 · 历史回测不代表未来');
  lines.push('方案D 多窗口综合分：打分单元为策略（path+场景二元组），聚合 5 窗口指标（盈利窗口数/年化中位/回撤中位/最大回撤/样本总数）后归一化打分，防近1年单窗口虚高被推为"稳健"。');
  // HTML attribute 里换行需转义为 &#10;（textContent 解析时还原为 \n，.term-pop white-space: pre-line 渲染换行）
  return lines.join('&#10;').replace(/"/g, '&quot;');
}

// 6色信号图例（2026-07-23 三档优化版）：4色买点(主买红/辅买玫红/追买金/备买紫) + 卖绿 + 追止损蓝，
// 指数走势图上方统一展示。备买风险提示附末尾（hover pop 显示"备买稳健性弱于追买仅供参考不单独决策"）。
// 同日多买点信号合并拼色 pin（金描边+光晕），图例不单独列拼色（用户从 pin 视觉即可辨识）。
// 三档 chip（年化最高/最稳健/回撤最小）在每个指数卡片内 chip-row 单独一行展示，chip 自带档位标签+买点名+数值，
// 不再在图例条重复展示 mini-legend（消除"分2处"）。图例末尾保留 ❓ termTip 解释 4 买点（重点备买=Supertrend翻多确认的备选买点）。
// _BACKUP_LEGEND_TIP / _BACKUP_BUYPOINT_TIP: 改为函数动态拼 _t()，避免 var 在加载时固化合规词，
// off 模式仍显"主关注"不切"主买"（与 _SIG_TYPE_META 同类 bug）。buy_long=关注点/买点。
function _backupLegendTip() {
  return "4 " + _t("buy_long") + "（" + _t("type_buy") + "/" + _t("buy_aux") + "/" + _t("buy_special") + "/" + _t("buy_backup") + "）历史回测表现差异较大，每个指数标题下方的三档 chip 标注该指数近5年全仓进出回测中表现最优的" + _t("buy_long") + "（年化最高/最稳健/回撤最小）。研究参考，不构成投资建议，历史回测不代表未来。";
}
function _backupBuypointTip() {
  return "4 " + _t("buy_long") + "：" + _t("type_buy") + "=RSI(14)上穿30超卖拐点；" + _t("buy_aux") + "=布林下轨回归左侧布局；" + _t("buy_special") + "=唐奇安20日上轨突破+5日确认；" + _t("buy_backup") + "=超级趋势(Supertrend) ATR×3翻多+3日二次确认的趋势反转备选" + _t("buy_long") + "（稳健性弱于" + _t("buy_special") + "，仅供参考不单独决策）。";
}
function _signalLegendHtml() {
  return '<div class="signal-legend">'
    + '<span class="signal-legend-item"><i style="background:#e6492e"></i>超卖拐点(' + _t("type_buy") + ')</span>'
    + '<span class="signal-legend-item"><i style="background:#d63384"></i>下轨拐点(' + _t("buy_aux") + ')</span>'
    + '<span class="signal-legend-item"><i style="background:#ffd700"></i>上轨突破(' + _t("buy_special") + ')</span>'
    + '<span class="signal-legend-item"><i style="background:#9c27b0"></i>趋势转向(' + _t("buy_backup") + ')</span>'
    + '<span class="signal-legend-item"><i style="background:#ff9800"></i>' + _t("legend_band_hold") + '</span>'
    + '<span class="signal-legend-item"><i style="background:#8bc34a"></i>' + _t("legend_band_reduce") + '</span>'
    + '<span class="signal-legend-item"><i style="background:#2e8b57"></i>' + _t("legend_sell") + '</span>'
    + '<span class="signal-legend-item"><i style="background:#3498db"></i>' + _t("legend_stop_loss") + '</span>'
    + '<span class="term-tip" data-tip="' + _backupBuypointTip().replace(/"/g, '&quot;') + '">❓</span>'
    + '<span class="signal-legend-note" data-tip="' + _backupLegendTip() + '">' + _t("legend_buy_diff") + '</span>'
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
// 设计：减仓=草绿条减少（100%->80%/70%，#8bc34a 与 sell #2e8b57 区分，体现"没卖重"）；接回=粉紫条增加（80%/70%->100%）；止损=蓝色清仓（100%->0%）；持有=橙色满仓维持。
// 国债波段策略是动态仓位管理（非静态 sell）：根据 RSI+乖离+布林三指标超买超卖动态调仓，
// 减仓(触超买)/接回(超卖回归)/止损(趋势破位)/持有(无信号维持)四动作联动，走势图 pin 即历史调仓时点回放。
function _bandPositionBar(reason) {
  if (!reason) return "";
  var r = String(reason);
  var m = r.match(/波段减仓(\d+)%/);
  if (m) {
    var pct = parseInt(m[1], 10);
    return _positionBarHtml(100, 100 - pct, _t("position_reduce_prefix") + pct + "%", "#8bc34a");
  }
  m = r.match(/波段接回(\d+)%/);
  if (m) {
    var pct = parseInt(m[1], 10);
    return _positionBarHtml(100 - pct, 100, "接回" + pct + "%", "#d63384");
  }
  if (r.includes("波段止损")) {
    return _positionBarHtml(100, 0, _t("position_stop_loss_clear"), "#3498db");
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
  hsi: '恒生指数', hscei: '恒生国企', hstech: '恒生科技',
  // 港股板块指数（来自 hk-5y.json，i18n 中文化 2026-07-20）
  hk_cesg10: '中华博彩业', hk_hsmogi: '恒生内地油气', hk_hsmbi: '恒生内地银行',
  hk_hsmpi: '恒生内地地产', hk_cshklre: '中证香港地产', hk_cshklc: '中证香港消费',
  hk_hscci: '恒生中资企业', hk_cshkdiv: '中证香港红利',
  // 美股
  us_dji: '道琼斯', us_ixic: '纳斯达克', us_spx: '标普500', us_ndx: '纳斯达克100',
  // 全球股指（2026-07-16 上线，中文名以后端 index_backfill.py HK_GLOBAL_INDICES 为准，前端简短化）
  // kospi 前端覆盖为"韩国 KOSPI"（JSON 里是英文 'KOSPI'，与"德国DAX/法国CAC40"风格统一：地区+缩写）
  nikkei225: '日经225', kospi: '韩国 KOSPI', ftse100: '富时100', dax: '德国DAX', cac40: '法国CAC40',
  // 红利/低波
  div_lowvol: '红利低波', csi_div: '中证红利', sz_div: '深证红利',
  // 全球指标
  cn10y: '中国10年国债', us10y: '美国10年国债', wti_oil: 'WTI原油', brent: '布伦特原油',
  cgb_idx: '上证国债指数', cgb_10y_etf: '10年国债ETF', cgb_10y_future: '10年国债期货',
  comex_silver: 'COMEX白银', gold: '伦敦金', oil: '原油', usdcnh: '美元/离岸人民币',
  a_qvix_300: '中国波指300', a_qvix_1000: '中国波指(50ETF期权)', cn_us_spread: '中美利差',
  // 综合情绪
  cross_market: '跨市场综合评分', a_sentiment: 'A股综合情绪分',
  sentiment_sz50: '上证50情绪分', sentiment_hs300: '沪深300情绪分',
  sentiment_csi500: '中证500情绪分', sentiment_csi1000: '中证1000情绪分',
  sentiment_cyb: '创业板情绪分', sentiment_kc50: '科创50情绪分',
  fear_greed: '恐贪指数',
  high_alert: '高位预警',
  low_alert: '低位机会',
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

// 按 index_id + signal 关联 state.signalStats 取 10d 窗口 stats（含 score）。
// signal 字段映射：buy_special_filtered -> buy_special（共享同一信号 stats）。
// 返回 {win_rate,pl,mean,n,score} 或 null（无 stats / score None）。
function _getSignalScore(it) {
  if (!state.signalStats) return null;
  const sigKey = it.signal === "buy_special_filtered" ? "buy_special" : it.signal;
  const iidStats = state.signalStats[it.index_id];
  if (!iidStats) return null;
  const sigStats = iidStats[sigKey];
  if (!sigStats || !sigStats["10d"]) return null;
  const d = sigStats["10d"];
  return (d && d.score != null) ? d : null;
}

// 技术分析参考点准确率统计（2026-07-28 B方案）：遍历 items 统计 since_correct
// ☑️(true)/✖️(false)/null(今日/未结算不计分母)，并按 _getSignalScore 的 score 分档
// （高≥0.75/中0.55-0.75/低<0.55）分别统计。返回 {total, grade:{high,mid,low}}。
// pct = t/(t+f)*100，t+f=0 时 pct=null（避免 0/0 误导）。无 score 的 item 计入 total 但不计入分档。
// _SIG_TYPES: byType 分组统计的信号类型清单（不含 buy_special_filtered，该类型不在 signals_today 展示）
// 问题2 fix(2026-07-31): band_hold 从末尾移到买类/卖类之间(中性独立组), 避免紧贴 sell_stop_loss 视觉"归卖"
const _SIG_TYPES = ["buy", "buy_aux", "buy_special", "buy_backup", "band_hold", "band_sell", "sell", "sell_stop_loss"];
// _SIG_TYPE_META: 分类行 chip 渲染元数据（中文标签 + 色点颜色，与 _SIGNAL_HELP_ITEMS 一致）
// 顺序: 买类(buy/buy_aux/buy_special/buy_backup) | 中性(band_hold) | 卖类(sell/sell_stop_loss)
// ⚠️ label 存 i18n key（labelKey）而非 _t() 求值结果：_t() 在 JS 加载时只求值一次，
//    切合规模式后 applyCompliance 调 renderTab 重渲染时拿到的还是加载时固化的值，
//    导致 off 模式仍显示"主关注"。改存 key + 使用时 _t(labelKey) 动态求值，切模式即更新。
const _SIG_TYPE_META = [
  { key: "buy", labelKey: "type_buy", color: "#e6492e" },
  { key: "buy_aux", labelKey: "buy_aux", color: "#d63384" },
  { key: "buy_special", labelKey: "buy_special", color: "#ffd700" },
  { key: "buy_backup", labelKey: "buy_backup", color: "#9c27b0" },
  { key: "band_hold", labelKey: "band_hold", color: "#ff9800" },
  { key: "band_sell", labelKey: "type_band_sell", color: "#8bc34a" },
  { key: "sell", labelKey: "sell_short", color: "#2e8b57" },
  { key: "sell_stop_loss", labelKey: "type_sell_stop_loss", color: "#3498db" },
];
function _calcSignalAccuracy(items) {
  const _newBin = () => ({ t: 0, f: 0, n: 0, pct: null });
  const acc = {
    total: { t: 0, f: 0, n: 0, pct: null },
    grade: {
      high: { t: 0, f: 0, n: 0, pct: null },
      mid: { t: 0, f: 0, n: 0, pct: null },
      low: { t: 0, f: 0, n: 0, pct: null },
    },
    byType: Object.fromEntries(_SIG_TYPES.map((s) => [s, _newBin()])),
  };
  if (!items || !items.length) return acc;
  const _tally = (bin, it) => {
    if (it.since_correct === true) bin.t++;
    else if (it.since_correct === false) bin.f++;
    else bin.n++;
  };
  for (const it of items) {
    // band_hold 非操作项(2026-07-31): 不计入 total(尤其不计入未结算 n, 避免未结算 44 含 35 band_hold 误导);
    //   byType 仍统计 band_hold(chip 显示数量). band_hold since_correct 恒 null, 不影响 total.t/f
    const _isBH = it.signal === "band_hold";
    if (!_isBH) _tally(acc.total, it);
    // 按信号类型分组统计（band_hold 的 since_correct 恒 null，自然只累加 n）
    // 波段减仓(reason)归 band_sell 中性组，不归 sell 卖类（与 ord/_SIG_TYPES 一致）
    const _sigKey = (it.reason||'').includes('波段减仓') ? 'band_sell' : it.signal;
    if (acc.byType[_sigKey]) _tally(acc.byType[_sigKey], it);
    const sc = _getSignalScore(it);
    if (!sc || sc.score == null) continue; // 无 score 不计入分档
    const s = sc.score;
    let bin;
    if (s >= 0.75) bin = acc.grade.high;
    else if (s >= 0.55) bin = acc.grade.mid;
    else bin = acc.grade.low;
    _tally(bin, it);
  }
  const _pct = (bin) => (bin.t + bin.f > 0 ? (bin.t / (bin.t + bin.f)) * 100 : null);
  acc.total.pct = _pct(acc.total);
  acc.grade.high.pct = _pct(acc.grade.high);
  acc.grade.mid.pct = _pct(acc.grade.mid);
  acc.grade.low.pct = _pct(acc.grade.low);
  // byType pct: band_hold 特殊——since_correct 恒 null（只计 n），pct 保持 null 不算
  for (const sig of _SIG_TYPES) {
    if (sig === "band_hold") continue;
    acc.byType[sig].pct = _pct(acc.byType[sig]);
  }
  return acc;
}

// 首页冰点日/买卖点卡片：按日期分组渲染，同日4个/行，今日(date===todayDate)高亮且排首。
// items: freeze={date,score_id,value} | signal={date,index_id,signal,reason}
// kind: "freeze" | "signal"；todayDate: 数据"今日"基准(r.date)
// 每日期全部显示（不做折叠），卡片 .signal-grid 有 max-height+overflow 滚动兜底。
// isClosed: 数据是否已收盘(默认true)。今日+盘中(!isClosed)的pin是盘中预估信号，
// 收盘后(17:50)update_all重算定版可能消失/变动(intraday_snapshot._recompute_signals
// DELETE+INSERT幂等覆盖)，挂⚠角标强提醒。freeze(冰点日)为历史定版不提醒。
// 评分尾缀（2026-07-27）：技术参考点综合把握度 score（10d 窗口），角标[高/中/低]+hover tooltip
//   详情。score≥0.75 高(绿)/≥0.55 中(橙)/<0.55 低(灰)；≥0.75 pin 加 .sig-item-high 描边高亮。
//   组内排序：保留大类优先(买>辅买>卖)，同大类内按 score 降序（高分靠前）。
// E 方案(2026-07-31): 时间窗口筛选标题后缀 - 窗口非 0_15 时追加"·显示X~15日"指示
// y_15 特殊: 今日不在窗口内, "今日高亮"提示改为"今日已排除"
function _sigWindowSuffix() {
  const wf = state.sigWindowFilter;
  if (!wf || wf === "0_15") return "";
  const map = { "10_15": "显示10~15日", "7_15": "显示7~15日", "3_15": "显示3~15日", "y_15": "昨日~15日" };
  return " · " + (map[wf] || "");
}
function _sigTodayHint() {
  return state.sigWindowFilter === "y_15" ? "今日已排除" : "今日高亮";
}
function _renderSignalGrid(items, todayDate, title, kind, emptyText, isClosed = true) {
  if (!items || !items.length) return `<h3>${title}</h3><div class="empty-note">${emptyText}</div>`;
  // A/B 方案(2026-07-29): 评级/对错筛选 - 汇总条数字仍用全量 items(_calcSignalAccuracy),
  // 列表渲染用 filtered(只显示符合筛选的参考点)。null=不筛; "high"/"mid"/"low"=评级;
  // "true"/"false"/"null"=对/错/未结算。点击汇总条 button toggle 筛选, 再点同档恢复。
  // E 方案(2026-07-31): 时间窗口筛选 - 按日期窗口切片 items, 影响汇总条+列表+总数
  // sigWindowFilter: "0_15"=全部(默认), "10_15"=第10-15日, "7_15"=第7-15日,
  // "3_15"=第3-15日, "y_15"=排除今日(昨日~15日)
  // 窗口筛选特殊: 影响汇总条(基于窗口内 items 算准确率); grade/correct/type 筛选不影响汇总条
  let windowedItems = items;
  if (kind === "signal" && state.sigWindowFilter && state.sigWindowFilter !== "0_15") {
    // 按 date 降序得到 dates 序列, 今日排首(与下方 groups 逻辑一致), 保证 y_15 排除今日
    const _allDates = [...new Set(items.map((it) => it.date))].sort((a, b) => (a < b ? 1 : -1));
    let _sortedDates = _allDates;
    if (todayDate && _allDates.includes(todayDate)) {
      _sortedDates = [todayDate, ..._allDates.filter((d) => d !== todayDate)];
    }
    let _lo = 0;
    const wf = state.sigWindowFilter;
    if (wf === "10_15") _lo = 9;       // 第10-15日 = index 9..end
    else if (wf === "7_15") _lo = 6;   // 第7-15日 = index 6..end
    else if (wf === "3_15") _lo = 2;   // 第3-15日 = index 2..end
    else if (wf === "y_15") _lo = 1;   // 排除今日 = index 1..end
    const _windowDates = new Set(_sortedDates.slice(_lo));
    windowedItems = items.filter((it) => _windowDates.has(it.date));
  }
  let filtered = windowedItems;
  if (kind === "signal") {
    filtered = windowedItems.filter((it) => {
      if (state.sigGradeFilter) {
        const sc = _getSignalScore(it);
        if (!sc || sc.score == null) return false;
        const s = sc.score;
        if (state.sigGradeFilter === "high" && !(s >= 0.75)) return false;
        if (state.sigGradeFilter === "mid" && !(s >= 0.55 && s < 0.75)) return false;
        if (state.sigGradeFilter === "low" && !(s < 0.55)) return false;
      }
      if (state.sigCorrectFilter) {
        const v = it.since_correct;
        const k = v === true ? "true" : v === false ? "false" : "null";
        if (k !== state.sigCorrectFilter) return false;
      }
      // 问题fix(2026-07-31): 波段减仓 signal='sell' 但 reason='波段减仓' 应归 band_sell 不进卖列表
      //   与 _sigKey(L1291)/ord(L1401)/chip CSS(L1447) 一致用 reason 判断
      const _sigKey = (it.reason||'').includes('波段减仓') ? 'band_sell' : it.signal;
      // 默认过滤 band_hold(波段持有非操作项, 首页表格不显示); 点 band_hold chip 后 sigTypeFilter='band_hold' 才显示
      if (state.sigTypeFilter !== "band_hold" && _sigKey === "band_hold") return false;
      if (state.sigTypeFilter && _sigKey !== state.sigTypeFilter) return false;
      return true;
    });
  }
  // 按 date 分组（降序），今日组单独提到最前
  const groups = {};
  for (const it of filtered) {
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
      // 问题4 fix(2026-07-31): ord 补全 7 类排序(原只 3 类, band_hold ?? 9 排末尾和 sell_stop_loss 混卖区)
      // 问题2 fix(2026-07-31): band_hold 从 3 改 1.9(买类 1.8 和卖类 2 之间), 与汇总条 chip 顺序一致,
      //   避免紧贴 sell_stop_loss(2.5) 视觉"归卖"; 三档有序: 买类(0~1.8) -> 中性 band_hold(1.9) -> 卖类(2~2.5)
      const ord = { buy: 0, buy_aux: 1, buy_special: 1.5, buy_backup: 1.8, band_hold: 1.9, band_sell: 1.95, sell: 2, sell_stop_loss: 2.5 };
      dayItems.sort((a, b) => {
        const oa = ord[(a.reason||'').includes('波段减仓')?'band_sell':a.signal] ?? 9;
        const ob = ord[(b.reason||'').includes('波段减仓')?'band_sell':b.signal] ?? 9;
        if (oa !== ob) return oa - ob;
        // 同大类内按 score 降序（高分靠前，无 score 视为 -1 排末）
        const sa = _getSignalScore(a)?.score ?? -1;
        const sb = _getSignalScore(b)?.score ?? -1;
        return sb - sa;
      });
    } else {
      dayItems.sort((a, b) => (a.value ?? 99) - (b.value ?? 99));
    }
    const cellHtml = (it) => {
      if (kind === "signal") {
        // 今日+盘中=盘中预估信号，收盘后(17:50)重算定版可能消失/变动，挂⚠角标强提醒
        const showIntradayWarn = isToday && !isClosed;
        const warnBadge = showIntradayWarn
          ? '<sup class="sig-intraday-warn" data-tip="盘中预估·收盘后(17:50)重算定版，此信号可能消失或变动">⚠</sup>'
          : '';
        const cls = showIntradayWarn ? "sig-item sig-clickable sig-intraday" : "sig-item sig-clickable";
        // 评分尾缀：技术参考点综合把握度（10d 窗口 score）
        const sc = _getSignalScore(it);
        let scoreBadge = "";
        let scoreCls = "";
        if (sc && sc.score != null) {
          const s = sc.score;
          let lvl, lvlCls;
          if (s >= 0.75) { lvl = "高"; lvlCls = "sig-score sig-score-high"; }
          else if (s >= 0.55) { lvl = "中"; lvlCls = "sig-score sig-score-mid"; }
          else { lvl = "低"; lvlCls = "sig-score sig-score-low"; }
          const tip = `把握度 ${s.toFixed(2)}·准确率${(sc.win_rate * 100).toFixed(0)}%·盈亏比${sc.pl != null ? sc.pl.toFixed(2) : "-"}·样本${sc.n}`;
          scoreBadge = `<sup class="${lvlCls}" data-tip="${tip}">${lvl}</sup>`;
          if (s >= 0.75) scoreCls = " sig-item-high";
        }
        // 信号至今对错角标：至今走势符合预测☑️ / 不符✖️（since_correct=null 今日信号/band_hold中性不显示）
        let correctBadge = "";
        if (it.since_correct === true || it.since_correct === false) {
          const _mark = it.since_correct ? "☑️" : "✖️";
          const _retS = it.since_return != null ? (it.since_return > 0 ? "+" : "") + it.since_return.toFixed(2) + "%" : "";
          const _dir = it.since_correct ? "符合预测" : "不符预测";
          correctBadge = `<sup class="sig-correct" data-tip="至今${_retS}·${_dir}">${_mark}</sup>`;
        }
        // DOM 顺序(2026-07-28 调整): [信号标签b][⚠][评级高/中/低][☑️/✖️][指数名]
        // 原顺序 [信号标签b][指数名][⚠][评级][对错] 在窄屏下指数名过长把评级+对错挤到右侧被 ellipsis 截掉看不见。
        // 现把评级+对错移到指数名前(紧跟信号标签),指数名放最右,溢出时 ellipsis 只截指数名,评级+对错始终可见。
        // hoverpop title: 分类·signalLabel·指数名·reason·至今对错(可选)·点击查看
        // 2026-07-20 修复: 原只 reason, 补全 _SIG_TYPE_META 分类(主买/辅买/追买/备买/波段持有/波段减仓/卖/追止损)
        // + signalLabel(超卖拐点/下轨拐点/上轨突破/趋势转向/ATR止损等) + 指数名, 配合 CSS nowrap+ellipsis 4列整洁
        const _typeKey = (it.reason||'').includes('波段减仓') ? 'band_sell' : it.signal;
        const _meta = _SIG_TYPE_META.find(m => m.key === _typeKey);
        const _typeLabel = _meta ? _t(_meta.labelKey) : it.signal;
        const _titleParts = [_typeLabel, signalLabel(it), indexIdToName(it.index_id)];
        if (it.reason) _titleParts.push(it.reason);
        if (it.since_correct === true || it.since_correct === false) {
          const _retS2 = it.since_return != null ? (it.since_return > 0 ? "+" : "") + it.since_return.toFixed(2) + "%" : "";
          _titleParts.push(`至今${_retS2}·${it.since_correct ? "符合预测" : "不符预测"}`);
        }
        _titleParts.push("点击查看走势图");
        const _hoverTitle = _titleParts.join(" · ");
        return `<span class="${cls}${scoreCls}" data-idx="${it.index_id}" data-sig="${it.signal}" data-sig-type="${_typeKey}" data-date="${it.date}" title="${_hoverTitle}"><b class="${it.signal}${(it.reason||'').includes('波段减仓')?' band_sell':''}">${signalLabel(it)}</b>${warnBadge}${scoreBadge}${correctBadge} <span class="sig-idx-name">${indexIdToName(it.index_id)}</span></span>`;
      }
      return `<span class="sig-item sig-clickable" data-idx="s.${it.score_id}" data-sig="freeze" data-date="${it.date}" data-val="${it.value != null ? it.value.toFixed(1) : ""}" title="点击查看走势图"><span class="sig-freeze-name">${indexIdToName(it.score_id)}</span>=<b class="freeze-val">${it.value != null ? it.value.toFixed(1) : "-"}</b></span>`;
    };
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
  // B方案(2026-07-28): 技术分析参考点准确率汇总条（仅 signal 类；freeze 无 since_correct/score 不显示）
  // 格式：总准确率 X% (T对/F错·N未结算) | 高 X% (t/f) · 中 X% (t/f) · 低 X% (t/f)
  // 高/中/低前带色点(高绿#15803d/中橙#e6a23c/低灰)；高档0样本(t+f=0) pct=null 显示"-"避免0/0误导
  // A/B 方案(2026-07-29): 高/中/低 + 对/错/未结算 均改为 button 可点击筛选(toggle), 选中态加
  //   sig-acc-filter-active; 末尾追加"恢复全部"按钮(仅筛选激活时显示)。汇总条数字始终用全量 items。
  // C 方案(2026-07-29): 未结算 button 带 data-tip 补说明(信号已发出未验证对错, 收盘后转对/错)。
  let _accHtml = "";
  let _windowBtnsHtml = "";  // E 方案 UI: 窗口按钮组(仅 signal), 移到标题行❓后, 不再独立成行
  if (kind === "signal") {
    // E 方案: 汇总条基于窗口内 items 算准确率(非全量), 窗口筛选影响总数+总准确率
    const _acc = _calcSignalAccuracy(windowedItems);
    const _fmt = (pct) => (pct == null ? "-" : pct.toFixed(0) + "%");
    const _gActive = (g) => (state.sigGradeFilter === g ? " sig-acc-filter-active" : "");
    const _cActive = (k) => (state.sigCorrectFilter === k ? " sig-acc-filter-active" : "");
    const _tActive = (t) => (state.sigTypeFilter === t ? " sig-acc-filter-active" : "");
    const _seg = (label, bin, dotCls, grade) =>
      `<button class="sig-acc-seg sig-acc-filter${_gActive(grade)}" data-grade-filter="${grade}" data-tip="${_escAttr("点击只看评级" + label + "的参考点")}"><span class="sig-acc-dot ${dotCls}">●</span>${label} ${_fmt(bin.pct)} (${bin.t}/${bin.f})</button>`;
    const _unsettledTip = '未结算=信号已发出但尚未验证对错。含：①今日新信号(无至今走势数据);②等待收盘价回填。收盘后update_all重算since_correct后转为"对"或"错"。点击只看未结算项(波段持有非操作项,不计入未结算)';
    const _reset = (state.sigGradeFilter || state.sigCorrectFilter || state.sigTypeFilter)
      ? ` <button class="sig-acc-reset" data-grade-filter-reset="1">恢复全部</button>`
      : "";
    // 按信号分类行（2026-07-30）：只显示 signals_today 实际出现的类型（byType t+f+n>0），不显示空分类
    // band_hold 特殊：since_correct 恒 null（只计 n），chip 只显示"波段持有 N个"不算 pct
    // 色点用 inline color 着色 ● 字符，与评级行 .sig-acc-dot 风格一致
    // 问题2 fix(2026-07-31): chip 分三组用 | 分隔(买类 | 中性 band_hold | 卖类), 避免 band_hold 紧贴
    //   sell_stop_loss 视觉"归卖"; 分隔符在 chip 出现时才加(前有 chip 才插 |)
    const _typeChips = _SIG_TYPE_META
      .filter((m) => {
        const b = _acc.byType[m.key];
        return b && (b.t + b.f + b.n) > 0;
      })
      .reduce((acc, m) => {
        const b = _acc.byType[m.key];
        const tip = _escAttr("点击只看" + _t(m.labelKey) + "信号");
        // band_hold chip 特殊(2026-07-31): 默认灰(未选中, 表格默认不含 band_hold);
        //   选中(sigTypeFilter==='band_hold')才亮橙(#ff9800)+active 描边. 其他 chip 不变(默认亮色)
        const _isBH = m.key === "band_hold";
        const _bhOn = state.sigTypeFilter === "band_hold";
        const _chipColor = _isBH ? (_bhOn ? "#ff9800" : "var(--text-3, #999)") : m.color;
        const _bhCls = _isBH ? (_bhOn ? " sig-acc-filter-bh-on" : " sig-acc-filter-bh-off") : "";
        const dot = `<span class="sig-acc-dot" style="color:${_chipColor}">●</span>`;
        const _lbl = _t(m.labelKey);
        const body = m.key === "band_hold" ? `${_lbl} ${b.n}个` : `${_lbl} ${_fmt(b.pct)} (${b.t}/${b.f})`;
        const chip = `<button class="sig-acc-seg sig-acc-filter${_tActive(m.key)}${_bhCls}" data-type-filter="${m.key}" data-tip="${tip}">${dot}${body}</button>`;
        // 分组分隔: band_hold/sell 前插 | (买类 | 中性 | 卖类), 仅前面已有 chip 才插
        const sep = (m.key === "band_hold" || m.key === "sell") && acc ? ' <span class="sig-acc-sep">|</span> ' : (acc ? " · " : "");
        return acc + sep + chip;
      }, "");
    const _byTypeRow = _typeChips ? `<div class="sig-acc-by-type">${_typeChips}</div>` : "";
    // E 方案(2026-07-31): 时间窗口筛选按钮组 - 4 窗口按钮 + 恢复全部(窗口激活时显示)
    // 再点同窗口按钮 = 恢复 "0_15"(toggle), 与 grade/correct/type 筛选互不影响(正交)
    // UI(2026-07-31): 按钮组改为 span(inline-flex), 移到标题行❓后(h3.sig-title-row flex 布局),
    //   宽度不够自动换行紧跟标题; 不再作为独立 div 放汇总条下方。字体继承页面红金默认(12px/400)
    const _wfActive = (wf) => (state.sigWindowFilter === wf ? " sig-acc-filter-active" : "");
    const _wfBtn = (label, wf, tip) =>
      `<button class="sig-acc-seg sig-acc-filter${_wfActive(wf)}" data-window-filter="${wf}" data-tip="${_escAttr(tip)}">${label}</button>`;
    const _wfReset = (state.sigWindowFilter && state.sigWindowFilter !== "0_15")
      ? ` <button class="sig-acc-reset" data-window-filter-reset="1">恢复全部</button>`
      : "";
    _windowBtnsHtml = `<span class="sig-acc-window sig-title-window">切换: ${_wfBtn("10日~15日", "10_15", "只看第10-15交易日(排除近9日)")} · ${_wfBtn("7日~15日", "7_15", "只看第7-15交易日(排除近6日)")} · ${_wfBtn("3日~15日", "3_15", "只看第3-15交易日(排除近2日)")} · ${_wfBtn("昨日~15日", "y_15", "排除今日,只看昨日及更早14日")}${_wfReset}</span>`;
    // 问题3 fix(2026-07-31): _accHtml 用 .sig-acc-wrap 包裹(summary+byType), _rerenderSigCardContent
    //   整体替换 .sig-acc-wrap, 否则切窗口时 byType 各类型数量/准确率不更新(只 summary 更新)
    _accHtml = `<div class="sig-acc-wrap"><div class="signal-accuracy-summary">总准确率 ${_fmt(_acc.total.pct)} (<button class="sig-acc-seg sig-acc-filter${_cActive("true")}" data-correct-filter="true">${_acc.total.t}对</button>/<button class="sig-acc-seg sig-acc-filter${_cActive("false")}" data-correct-filter="false">${_acc.total.f}错</button>·<button class="sig-acc-seg sig-acc-filter${_cActive("null")}" data-correct-filter="null" data-tip="${_escAttr(_unsettledTip)}">${_acc.total.n}未结算</button>) | ${_seg("高", _acc.grade.high, "sig-acc-dot-high", "high")} · ${_seg("中", _acc.grade.mid, "sig-acc-dot-mid", "mid")} · ${_seg("低", _acc.grade.low, "sig-acc-dot-low", "low")}${_reset}</div>${_byTypeRow}</div>`;
  }
  // 筛选后无匹配: 汇总条仍显示(窗口内统计), 列表区给提示
  if (kind === "signal" && !rows) {
    if (!windowedItems.length) {
      rows = `<div class="empty-note" style="margin:8px 0">当前时间窗口内无参考点，点击上方窗口按钮切换查看</div>`;
    } else if (state.sigGradeFilter || state.sigCorrectFilter || state.sigTypeFilter) {
      rows = `<div class="empty-note" style="margin:8px 0">当前筛选无匹配参考点，点击"恢复全部"查看全部</div>`;
    }
  }
  // UI(2026-07-31): signal 类把窗口按钮组(_windowBtnsHtml)放进 h3 标题行❓后(flex 布局),
  //   宽度足够时与标题同一行, 不够时自动换行紧跟标题; freeze 类无窗口按钮保持原样
  const _h3Html = _windowBtnsHtml
    ? `<h3 class="sig-title-row"><span class="sig-title-text">${title}</span>${_windowBtnsHtml}</h3>`
    : `<h3>${title}</h3>`;
  return `${_h3Html}${_accHtml}<div class="signal-grid">${rows}</div>`;
}

// D 方案(2026-07-29): sigCard 自动更新 - ts:overview-refreshed hook 增量重绘。
// 盘中后端 intraday_snapshot 每 30min 重算 overview.json 并 push main, 前端轮询拉到新
// collected_at 时自动重绘 sigCard, 用户不刷新也能看到最新信号。重绘保留筛选 state(内部读 state)。
let _sigCardRenderedAt = null;  // 上次渲染 sigCard 的 overview collected_at(防重复重绘)

// 增量重绘 sigCard 内容: 替换 h3(含窗口按钮) + .sig-acc-wrap(汇总条+分类行) + .signal-grid,
// 保留 .card-time-badge 角标 + .sig-intraday-hint 盘中提示(不整卡 innerHTML 替换)。
// 筛选 state(sigGradeFilter/sigCorrectFilter) 由 _renderSignalGrid 内部读取, 重绘自动保留。
// 问题3 fix: 替换 .sig-acc-wrap(非仅 .signal-accuracy-summary), 确保 byType 各类型数量/准确率随窗口联动
function _rerenderSigCardContent(r, snap) {
  if (!r) return;
  const sigCard = document.querySelector(".sig-card");
  if (!sigCard) return;
  const isClosed = snap ? snap.is_closed : true;
  const title = "近期技术分析参考点（近 15 交易日 · " + _sigTodayHint() + _sigWindowSuffix() + "）" + signalHelpTip("6色技术信号参考（点击❓查看6色信号详细解释）");
  const newHtml = _renderSignalGrid(r.signals_today || [], r.date, title, "signal", "近期无技术分析参考点", isClosed);
  const tmp = document.createElement("div");
  tmp.innerHTML = newHtml;
  const newH3 = tmp.querySelector("h3");
  const newAccWrap = tmp.querySelector(".sig-acc-wrap");
  const newGrid = tmp.querySelector(".signal-grid");
  const oldH3 = sigCard.querySelector("h3");
  const oldAccWrap = sigCard.querySelector(".sig-acc-wrap");
  const oldGrid = sigCard.querySelector(".signal-grid");
  if (newH3 && newAccWrap && newGrid && oldH3 && oldAccWrap && oldGrid) {
    // UI(2026-07-31): h3 也增量替换(含窗口按钮 active 态 + 标题后缀, 随筛选切换更新)
    // 问题3 fix: .sig-acc-wrap 整体替换(summary+byType), 切窗口时 byType 各类型数量/准确率联动更新
    oldH3.replaceWith(newH3);
    oldAccWrap.replaceWith(newAccWrap);
    oldGrid.replaceWith(newGrid);
  } else {
    // 兜底: 数据从有变空/空变有 - 保留 badge + hint, 替换其余
    const badge = sigCard.querySelector(".card-time-badge");
    const hint = sigCard.querySelector(".sig-intraday-hint");
    sigCard.innerHTML = newHtml;
    if (badge) sigCard.appendChild(badge);
    if (hint) sigCard.appendChild(hint);
  }
}

// ts:overview-refreshed hook: collected_at 变化时增量重绘 sigCard(非概览 tab / 无数据 / 同 collected_at 跳过)
function _maybeRerenderSigCard(r, snap) {
  if (state.tab !== "overview") return;
  if (!r || !r.signals_today) return;
  if (r.collected_at === _sigCardRenderedAt) return;
  _sigCardRenderedAt = r.collected_at;
  _rerenderSigCardContent(r, snap);
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
  { sig: "buy", color: "#e6492e", nameKey: "detail_buy_name", desc: "RSI(14) 上穿 30。情绪极度超卖后拐头，均值回归思路。常对应阶段性反弹起点。", warn: "均值回归思路，适合震荡市；趋势市信号少。配套：与辅买共振时较强。" },
  { sig: "buy_aux", color: "#d63384", nameKey: "detail_buy_aux_name", desc: "布林带下轨回归。价格跌穿布林带(BB)下轨后回归，偏左侧布局。", warn: "左侧布局偏激进。配套：配合主买共振时较强；单独出现风险高。" },
  { sig: "buy_special", color: "#ffd700", nameKey: "detail_buy_special_name", desc: "唐奇安 20 日上轨突破 + 5 日确认。趋势跟随思路，突破后惯性上行。信号在突破后第 5 日确认站稳时触发，确认日当天涨跌不代表信号方向（非突破日）。", backtest: "🔬 回测持有期建议（全史统计）：5d 胜率59.65%/均值+0.87%/回撤2.65%；10d 60.24%/+1.66%/4.26%（风险调整最优）；30d 59.06%/+3.44%（分水岭，风险/收益拐点）；90d 60.83%/+9.42%/回撤16.53%（纯收益最优，但回撤大）。", warn: "趋势跟随追高信号。配套：需配合量能确认，假突破风险；必须配追止损卖(ATR×3.5止损)控制风险，0套牢。" },
  { sig: "buy_backup", color: "#9c27b0", nameKey: "detail_buy_backup_name", desc: "超级趋势(Supertrend) ATR×3 翻多 + 3 日二次确认。趋势反转确认。", warn: "稳健性弱于追买。配套：仅供参考不单独决策，需结合主买/辅买/追买；诱多风险已用3日二次确认过滤。" },
  { sig: "sell", color: "#2e8b57", nameKey: "detail_sell_name", desc: "MA60 多头 + MACD 死叉 + 20 日高回落 5%。止盈调整提示。", note: "📌 图钉标签「盈亏X%」来源：sell 信号 reason 中「vs前买+X%」的单次配对实现涨幅（该卖点 vs 前一个买点的实际涨跌），非统计期望值；悬停提示的「盈亏比Y」才是历史统计值，二者勿混。" , warn: "止盈调整非反向信号。配套：走弱概率≈50%接近随机；与追止损卖共振时调整信号更强。" },
  { sig: "sell_stop_loss", color: "#3498db", nameKey: "detail_sell_stop_loss_name", desc: "ATR×3.5 止损（底层规则从唐奇安20日下轨改为 ATR×3，2026-07-21 调 ATR×3.5 降频，趋势跟踪止损）。趋势反转下行最后防线。", backtest: "🔬 回测对比（全史）：现 ATR×3 胜率46.91%/均值+1.76%/盈亏比1.82，全维度略优原唐奇安20日(胜率44.33%/均值+1.56%，2008股灾-10.5%最差)。ATR×3=趋势跟踪策略（低胜率靠大盈拉均值），区别于固定持有的均值回归（高胜率小赚）。⚠️ 2026-07-21 调 ATR×3.5 降频后（hs300 触发 -18%/5日胜率 49.58%->50.23%），回测旧 ATR×3 数据保留作历史对比，新参数统计值见下方前瞻字段。", warn: "最后防线跌破即清仓卖出。配套：趋势跟踪止损（低胜率大盈）；与卖共振时调整信号更强；蓝色与卖绿色区分。" },
  { sig: "band_hold", color: "#ff9800", nameKey: "detail_band_hold_name", desc: "国债三品种波段仓位管理策略波段持有状态（2026-07-24）。RSI+乖离+布林三指标无超买超卖信号，维持当前仓位。替代原 D1卖点(趋势转弱风险)对国债完全失效（sell=0 无理由）的问题。", backtest: "🔬 回测依据 /tmp/backtest_cgb_band.py + /tmp/cgb_band_results.json：cgb_idx 降风险(回撤-10.4%->-4.8%,夏普2.80->3.58)；cgb_10y_etf 放宽双赢(夏普1.31->1.52)；cgb_10y_future 双赢(年化1.30%->1.63%,夏普0.42->1.58)。", warn: "国债专属动态仓位管理（非静态 sell，非清仓卖出卖点）。四动作联动：减仓(草绿#8bc34a仓位条+图钉头,触超买减20-30%)/接回(buy_aux粉紫,超卖回归接回)/止损(sell_stop_loss蓝,趋势破位清仓卖出)/波段持有(band_hold橙,无超买超卖维持仓位)。走势图图钉 = 历史调仓时点回放，悬停信号日看仓位变化进度条，可缩放查看过去减仓/接回/止损时点。研究参考，不构成投资建议。" },
  { sig: "band_sell", color: "#8bc34a", nameKey: "detail_band_sell_name", desc: "国债波段仓位管理策略减仓动作。触发超买条件(bias20>0.3% AND RSI>rsi_high OR close≥布林上轨)时减仓 20-30% 锁利润。与 sell 区分：减仓非清仓卖出，体现'没卖重'，草绿 #8bc34a 与 sell 绿 #2e8b57 区分。", warn: "国债专属减仓动作(草绿#8bc34a仓位条减少 100%->80%/70%)。触超买减仓 20-30%，非清仓卖出退出。与止损(sell_stop_loss蓝,趋势破位清仓卖出)区分：减仓是主动锁利润，止损是被动防范。研究参考，不构成投资建议。" },
];

// 聚合 signal_stats.json（per-index）-> per-sig 概况（5d/10d/20d 三窗口，按样本数 n 加权平均）
// signal_stats.json 结构: {_updated_at, bj50:{buy:{10d:{win_rate,pl,mean,n},5d,20d,frequency},...}, sz:{...}}
// 无 max_drawdown 字段（signal_stats.py 仅算 win_rate/pl/mean/n/frequency，未算最大回撤）
// 返回 {sig: {5d:{win_rate,pl,mean,n}, 10d:{...}, 20d:{...}}} 或 null
function _aggregateSignalStats(raw) {
  if (!raw || typeof raw !== "object") return null;
  const SIGS = ["buy", "buy_aux", "buy_special", "buy_special_filtered", "buy_backup", "band_hold", "sell", "sell_stop_loss"];
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

// 信号 -> badge/rule-card class 映射（_signalHelpModalHTML / _strategyModalHTML 共用）
// badge-* / rule-card-* 实色与统计基准对齐，见 style.css .badge-* / .rule-card-* 注释
const _SIG_CLASS_MAP = {
  buy: { card: "rule-card-buy", badge: "badge-buy" },
  buy_aux: { card: "rule-card-aux", badge: "badge-aux" },
  buy_special: { card: "rule-card-special", badge: "badge-special" },
  buy_backup: { card: "rule-card-backup", badge: "badge-backup" },
  sell: { card: "rule-card-sell", badge: "badge-sell" },
  sell_stop_loss: { card: "rule-card-stop-loss", badge: "badge-stop-loss" },
  band_hold: { card: "rule-card-band-hold", badge: "badge-band-hold" },
  band_sell: { card: "rule-card-band-sell", badge: "badge-band-sell" },
};

// 渲染技术信号 modal（每信号：标题 badge + 描述 + 回测 + 分析概况[动态] + 补充 + 警示）
// aggStats: _aggregateSignalStats 返回值；null/某信号无数据 -> "数据待补"
// 复用 rule-card / rule-badge / badge-* / rule-stat-box 等 class，与 ruleContentHtml 风格统一
function _signalHelpModalHTML(aggStats) {
  const items = _SIGNAL_HELP_ITEMS.map((it) => {
    const cls = _SIG_CLASS_MAP[it.sig] || { card: "", badge: "" };
    const s = aggStats && aggStats[it.sig];
    let statHtml;
    if (s) {
      // 三窗口对比行（5d/10d/20d），按样本数 n 加权聚合；某窗口无数据显示 "-"
      const hasWin = !!(s["5d"] || s["10d"] || s["20d"]);
      const freqTotal = s.frequency_total || 0;
      // .rule-stat-row flex 布局：.rule-stat-label flex:0 0 3.5em 固定宽度 + white-space:nowrap 防标签内换行,
      // 内容 flex 自适应, align-items:baseline 基线对齐。修原 width:3em inline-block "10日："约3em填满溢出致行间错位。
      const winRows = [["5日", s["5d"]], ["10日", s["10d"]], ["20日", s["20d"]]].map(([label, w]) => {
        const lbl = '<span class="rule-stat-label">' + label + '：</span>';
        if (!w) return '<div class="rule-stat-row">' + lbl + '<span class="rule-stat-empty">- 累积中</span></div>';
        return '<div class="rule-stat-row">' + lbl + '<span>胜率 <b>' + (w.win_rate * 100).toFixed(0) + '%</b> · 盈亏比 <b>' + w.pl.toFixed(2) + '</b> · 均收益 <b>' + w.mean.toFixed(2) + '%</b> · 样本 <b>' + w.n + '</b></span></div>';
      }).join("");
      // 无窗口数据但有 frequency(刚上线窗口未到) -> "已生成N例,窗口统计累积中"; 有窗口数据 -> 附"累计N例"
      const freqNote = (!hasWin && freqTotal > 0)
        ? '<div class="rule-freq-pending">⏳ 已生成 <b>' + freqTotal + '</b> 例，窗口统计(5d/10d/20d)待未来交易日到位后累积</div>'
        : (freqTotal > 0 ? '<div class="rule-freq-note">累计已生成 ' + freqTotal + ' 例</div>' : '');
      statHtml = '<div class="rule-stat-box">📈 <b>分析概况</b>（全品种加权·按样本数加权）：<div style="margin-top:2px">' + winRows + '</div>' + freqNote + '</div>';
    } else {
      statHtml = '<div class="rule-stat-box" style="color:#ff9800">📈 分析概况：数据待补（signal_stats 未含此信号统计）</div>';
    }
    // 回测结论（backtest）：全史统计的持有期建议/止损方案对比，淡金色框区分于动态分析概况
    const backtestHtml = it.backtest
      ? '<div class="rule-backtest-box">' + _t.tsText(it.backtest) + '</div>'
      : '';
    // 补充说明（note）：pin 标签来源/术语澄清等，淡灰框
    const noteHtml = it.note
      ? '<div class="rule-note-box">' + _t.tsText(it.note) + '</div>'
      : '';
    return '<div class="rule-card ' + cls.card + '">' +
      '<div class="rule-card-head"><span class="rule-badge ' + cls.badge + '">' + _t(it.nameKey) + '</span></div>' +
      '<p>' + _t.tsText(it.desc) + '</p>' +
      backtestHtml +
      statHtml +
      noteHtml +
      '<p class="rule-note">⚠ ' + _t.tsText(it.warn) + '</p>' +
      '</div>';
  }).join("");
  return '<div class="rule-modal-overlay"></div><div class="rule-modal-body"><div class="rule-modal-header"><h3>📊 技术信号参考</h3><button class="rule-modal-close" aria-label="关闭">&times;</button></div><div class="rule-modal-content">' + items + '<div class="rule-modal-footer">⚠ 以上为研究标注非交易指令，详见右下角浮动 📋 策略说明。过往表现不代表未来收益。</div></div></div>';
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
  style.textContent += ".chart-hint .hint-sig.band-sell { background: #8bc34a; color: #fff; }";  // 波段减仓 草绿（国债波段仓管，2026-07-20 任务6+7）
  document.head.appendChild(style);
})();

// 涨跌家数数据口径（akshare 新浪(sina)源全市场快照，与东财等 APP 覆盖范围略有差异，非数据错误）
const _WIDTH_CALIBER_TIP = "涨跌家数口径：akshare 新浪(sina)源全市场快照，涨跌幅为负计为跌、平盘不计入。不同数据源覆盖范围略有差异（如东财多1只），非数据错误。";

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
  // forClick=true（click 路径）：只认已迁移的 [data-tip]，不 fallback [title]，
  // 避免移动端点带 title 的别处误开新 pop 而非关闭当前 pop（A2 修复）。
  function findTipEl(target, forClick) {
    if (!target || !target.closest) return null;
    var el = target.closest("[data-tip]");
    if (el) return el;
    if (forClick) return null;  // click 路径不 fallback [title]
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
    // 清上次的 modifier class（--up 由 below/above 逻辑重新加，--sig-*/--ndx 这里清防残留）
    pop.className = "term-pop";
    // 信号 pop 配色强化(2026-08-04)：触发元素带 data-sig-type(信号网格 pin)。
    // 浮层文字跟着信号配色（主关注红/趋势反转紫/风险绿/止损蓝…），首段(信号标签)加粗着色；
    // 纳斯达克100(us_ndx)特殊强化：指数名段加粗强化色 + pop 加背景高亮 + 描边强化。
    var sigType = el.getAttribute("data-sig-type");
    var idx = el.getAttribute("data-idx");
    var isNdx = idx === "us_ndx";
    if (sigType) {
      pop.classList.add("term-pop--sig", "term-pop--sig-" + sigType);
      if (isNdx) pop.classList.add("term-pop--ndx");
      // 文本结构: [信号标签(_typeLabel), signalLabel(子描述), 指数名, reason..., 点击查看走势图] join(" · ")
      // 信号标签 + 子描述(超卖拐点/下轨拐点/上轨突破/趋势转向/ATR止损 等)同属"信号描述区",
      // 都用 term-pop-sig-label 着色加粗跟信号配色, 视觉连贯; 指数名段单独 chip 强化; 非信号段(日期/数值)默认色
      var _esc = function (s) { return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"); };
      var parts = String(text == null ? "" : text).split(" · ");
      var idxName = idx && typeof indexIdToName === "function" ? indexIdToName(idx) : "";
      var html = parts.map(function (p, i) {
        if (i === 0 || i === 1) return '<b class="term-pop-sig-label">' + _esc(p) + '</b>';
        if (idxName && (p === idxName || p === idx)) return '<b class="term-pop-idx' + (isNdx ? ' term-pop-idx-ndx' : '') + '">' + _esc(p) + '</b>';
        return _esc(p);
      }).join(" · ");
      // 定位路径：告知用户完整数据在哪个 tab，点击切 tab + 滚动高亮卡片
      // s.* -> "📍 完整数据：盘面温测"；其他 -> "📍 完整数据：指数表现 > 港股 > 恒生国企"（一级tab > 二级sub-tab > 指数名）
      if (idx && typeof indexToMarketSubtab === "function") {
        var loc = indexToMarketSubtab(idx);
        if (loc && loc.tab && loc.tabName) {
          var locTxt = loc.tab === "sentiment"
            ? "📍 完整数据：" + loc.tabName
            : "📍 完整数据：" + loc.tabName + " > " + (loc.name || "") + " > " + (loc.idxName || "");
          html += '<span class="term-pop-locate" data-locate-idx="' + _esc(idx) + '">' + _esc(locTxt) + '</span>';
        }
      }
      pop.innerHTML = html;
    } else {
      pop.textContent = text;
    }
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
      var el = findTipEl(e.target, true);  // forClick=true：click 路径不 fallback [title]（A2）
      if (el) {
        if (popByClick && popEl === el) { hideNow(); return; }  // 同元素再点 -> 关
        show(el, el.getAttribute("data-tip"));
        popByClick = true;  // 标记后 mouseout 不立即关，直到下次 click 别处
        return;
      }
      if (e.target.closest && e.target.closest(".term-pop")) return;  // 点 pop 内容不关
      if (popByClick) hideNow();  // 点别处 -> 关
    }, true);  // A1：capture 阶段，先于 row 的 stopPropagation 执行，确保点 stopPropagation 元素也能关 term-pop
  }
  // 定位路径点击委托（PC + 移动端通用）：切 tab + 滚动到对应卡片 + 高亮 2s
  // 优先于 isTouch click 委托在 capture 阶段处理 .term-pop-locate，stopPropagation 防误关
  document.addEventListener("click", function (e) {
    var locEl = e.target.closest && e.target.closest(".term-pop-locate");
    if (!locEl) return;
    e.preventDefault();
    e.stopPropagation();
    var locateIdx = locEl.getAttribute("data-locate-idx");
    if (!locateIdx) return;
    var loc = (typeof indexToMarketSubtab === "function") ? indexToMarketSubtab(locateIdx) : null;
    if (!loc || !loc.tab) return;
    hideNow();
    state.tab = loc.tab;
    if (loc.tab === "market") {
      state.subtab = loc.subtab || "a-stock";
    } else if (loc.tab === "sentiment") {
      state.subtab = loc.subtab || "market-temp";
    }
    if (typeof _setTabHash === "function") _setTabHash(loc.tab);
    // 顶部 tab 按钮高亮同步（renderTab 内部也会同步，这里先视觉更新避免闪烁）
    document.querySelectorAll("button[data-tab]").forEach(function (x) { x.classList.remove("active"); });
    var tabBtn = document.querySelector('button[data-tab="' + loc.tab + '"]');
    if (tabBtn) tabBtn.classList.add("active");
    if (typeof updateH5Topbar === "function") updateH5Topbar();
    // renderTab 异步完成后滚动 + 高亮卡片
    if (typeof renderTab === "function") {
      renderTab().then(function () {
        setTimeout(function () {
          // 优先找 idx-card-{id}（A股/港股/全球/全球extras），其次 industry-cell-{id}（行业）
          var bareId = locateIdx.replace(/^(g|s)\./, "");
          var cardEl = document.getElementById("idx-card-" + bareId) ||
                       document.getElementById("industry-cell-" + bareId);
          if (cardEl && cardEl.scrollIntoView) {
            cardEl.scrollIntoView({ behavior: "smooth", block: "center" });
            cardEl.classList.add("idx-card-locate-flash");
            setTimeout(function () { cardEl.classList.remove("idx-card-locate-flash"); }, 2000);
          }
        }, 200);
      }).catch(function () {});
    }
  }, true);
  pop.addEventListener("mouseenter", function () { if (hideTimer) { clearTimeout(hideTimer); hideTimer = null; } });
  pop.addEventListener("mouseleave", hide);
  // C：移动端滚动时关闭 term-pop（CSS position:fixed 不跟随滚动，capture 捕获所有滚动容器）
  if (isTouch) window.addEventListener("scroll", hideNow, { passive: true, capture: true });
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

// 判断指标是否停更：数据日期距最新交易日超过 days 天视为停更（用于任何源端停更的指标,如原北向净买额 2024-08 停更;现北向已切 HKEX 成交总额源每日更新,不再触发）。
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
    buy_aux: "布林带(BB)下轨回归",
    sell: "20日高回落5%+MA60多头+MACD死叉",
  };
}

// === 标题❓策略弹窗（方案 B1 紧凑版，2026-07-20）===
// 信号顺序 + 颜色 badge + 名称（与 _SIGNAL_HELP_ITEMS 一致，便于用户对齐信号图例）
// 8 类信号：buy/buy_aux/buy_special/buy_backup/sell/sell_stop_loss/band_hold/band_sell
var _STRATEGY_DETAIL_KEYS = [
  { key: "buy", color: "#e6492e", nameKey: "detail_buy_name" },
  { key: "buy_aux", color: "#d63384", nameKey: "detail_buy_aux_name" },
  { key: "buy_special", color: "#ffd700", nameKey: "detail_buy_special_name" },
  { key: "buy_backup", color: "#9c27b0", nameKey: "detail_buy_backup_name" },
  { key: "sell", color: "#2e8b57", nameKey: "detail_sell_name" },
  { key: "sell_stop_loss", color: "#3498db", nameKey: "sig_meta_stop_loss_name" },
  { key: "band_hold", color: "#ff9800", nameKey: "detail_band_hold_name" },
  { key: "band_sell", color: "#8bc34a", nameKey: "detail_band_sell_name" },
];
// 渲染策略 modal：每信号 rule-card（badge + 描述 + 参数 + 过滤 + skip 警示），末尾合规声明。
// strategy._detail 字段，每字段 {desc, params, filter, enabled}。
// 复用 rule-card / rule-badge / badge-* / rule-stat-box 等 class，与 ruleContentHtml / _signalHelpModalHTML 风格统一。
function _strategyModalHTML(strategy, indexId) {
  var detail = strategy && strategy._detail;
  var rows = [];
  for (var i = 0; i < _STRATEGY_DETAIL_KEYS.length; i++) {
    var k = _STRATEGY_DETAIL_KEYS[i];
    var d = detail && detail[k.key];
    if (!d) continue;
    var enabled = d.enabled !== false;
    var cls = _SIG_CLASS_MAP[k.key] || { card: "", badge: "" };
    var paramHtml = (d.params && d.params !== "-")
      ? '<div class="rule-stat-box">⚙ 参数：<b>' + d.params + '</b></div>'
      : "";
    var filterHtml = (d.filter && d.filter !== "-")
      ? '<div class="rule-stat-box">🔍 过滤：<b>' + d.filter + '</b></div>'
      : "";
    rows.push(
      '<div class="rule-card ' + cls.card + (enabled ? '' : ' rule-card-disabled') + '">' +
      '<div class="rule-card-head"><span class="rule-badge ' + cls.badge + '">' + _t(k.nameKey) + '</span></div>' +
      '<p>' + d.desc + '</p>' +
      paramHtml +
      filterHtml +
      (enabled ? '' : '<p class="rule-note">⚠ 此信号在该指数已 skip（不触发）</p>') +
      '</div>'
    );
  }
  var rowsHtml = rows.join("") || '<div class="rule-stat-box">该指数暂无策略详情数据。</div>';
  return '<div class="rule-modal-overlay"></div>' +
    '<div class="rule-modal-body"><div class="rule-modal-header">' +
    '<h3>📋 本指数策略详情' + (indexId ? ' · ' + indexId : '') + '</h3>' +
    '<button class="rule-modal-close" aria-label="关闭">&times;</button></div>' +
    '<div class="rule-modal-content">' + rowsHtml +
    '<div class="rule-modal-footer">⚠ 以上为研究标注非交易指令，过往表现不代表未来收益。详见右下角浮动 📋 策略说明与 📊 技术信号参考 ❓。</div>' +
    '</div></div></div>';
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
    var name = _t(k.nameKey).split(" · ")[0];
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
    // gating：未登录 compare 特权 -> 弹登录提示，不切换 pin 状态（钉住=对比复盘）
    if (!hasPrivilege('compare')) {
      openLoginPromptForFeature('钉住', '钉住指数复盘为登录用户特权，登录后可钉住多个指数在顶部对比复盘');
      return;
    }
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
  { key: "buy", labelKey: "type_buy", color: "#e6492e" },
  { key: "buy_aux", labelKey: "buy_aux", color: "#d63384" },
  { key: "buy_special", labelKey: "buy_special", color: "#ffd700" },
  { key: "buy_backup", labelKey: "buy_backup", color: "#9c27b0" },
  { key: "sell", labelKey: "sell_short", color: "#2e8b57" },
  { key: "sell_stop_loss", labelKey: "sig_meta_stop_loss_label", color: "#3498db" },
];

function _loadSubUserInfo() {
  try { return JSON.parse(localStorage.getItem(_SUB_USER_INFO_LS_KEY) || "{}"); } catch (e) { return {}; }
}
function _saveSubUserInfo(info) {
  try { localStorage.setItem(_SUB_USER_INFO_LS_KEY, JSON.stringify(info || {})); } catch (e) {}
}

// C 方案（2026-07-24）：CF Workers 订阅接口单用户密码认证。
// 密码存 localStorage key sub_pwd（用户在订阅弹窗输入），每次请求带 X-Sub-Pwd header。
// 生产环境 /api/subscribe 走 CF Workers + KV；本地开发走 uvicorn main.py（无密码，_subFetch 仍兼容）。
var _SUB_PWD_LS_KEY = "sub_pwd";
function _getSubPwd() {
  try { return localStorage.getItem(_SUB_PWD_LS_KEY) || ""; } catch (e) { return ""; }
}
function _setSubPwd(pwd) {
  try { localStorage.setItem(_SUB_PWD_LS_KEY, pwd || ""); } catch (e) {}
}
// 统一 fetch 包装：自动加 X-Sub-Pwd header + r.ok 容错（旧代码直接 .json() 不判状态码）。
// 返回 Promise<json>（已解析），HTTP 错误时 reject（catch 显示友好提示）。
function _subFetch(url, opts) {
  opts = opts || {};
  var headers = Object.assign({}, opts.headers || {});
  var pwd = _getSubPwd();
  if (pwd) headers["X-Sub-Pwd"] = pwd;
  opts.headers = headers;
  return fetch(url, opts).then(function (r) {
    if (!r.ok) {
      var msg = "订阅接口未启用(HTTP " + r.status + ")";
      if (r.status === 401) msg = "密码错误，请在弹窗中重新输入订阅密码";
      if (r.status === 503) msg = "订阅接口未配置密码（联系管理员设置 SUBSCRIBE_PASSWORD）";
      throw new Error(msg);
    }
    return r.json();
  });
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
  btn.setAttribute("title", _t("subscribe_title"));
  btn.textContent = "🔔";
  btn.addEventListener("click", function (e) {
    e.preventDefault();
    e.stopPropagation();
    // gating：未登录 subscribe 特权 -> 弹登录提示，不打开订阅弹窗
    if (!hasPrivilege('subscribe')) {
      openLoginPromptForFeature('订阅', '信号订阅推送为登录用户特权，登录后可订阅关注的标的');
      return;
    }
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
  var defaultSubPwd = _getSubPwd() || "kant2218";  // C 方案：订阅密码预填（存 localStorage，内测期默认填 kant2218）
  if (!_getSubPwd()) _setSubPwd(defaultSubPwd);  // 首次访问预填后立即写入 localStorage，确保 X-Sub-Pwd header 自动带上（用户无需手输也无需点提交）
  // 信号类型 checkbox（默认全选）
  var sigCheckboxes = _SUB_SIGNAL_LABELS.map(function (s) {
    return '<label class="sub-sig-check"><input type="checkbox" value="' + s.key + '" checked>'
      + '<span class="hint-sig" style="background:' + s.color + '">' + _t(s.labelKey) + '</span></label>';
  }).join("");
  modal.innerHTML =
    '<div class="rule-modal-overlay"></div>' +
    '<div class="rule-modal-body subscribe-modal-body">' +
      '<div class="rule-modal-header"><h3>🔔 信号订阅' + (indexName ? ' · ' + indexName : '') + '</h3>' +
        '<button class="rule-modal-close" aria-label="关闭">&times;</button></div>' +
      '<div class="rule-modal-content">' +
        '<div class="sub-form-section">' +
          '<div class="sub-form-row"><label>订阅密码</label><input id="sub-pwd" type="password" placeholder="访问订阅功能所需密码" value="' + defaultSubPwd + '" autocomplete="off"></div>' +
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
  var subPwd = (document.getElementById("sub-pwd").value || "").trim();
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
  if (!subPwd) { _setSubMsg("请填写订阅密码", true); return; }
  if (!targets.length) { _setSubMsg("请填写订阅标的", true); return; }
  if (!email && !chatId) { _setSubMsg("邮箱和 Telegram chat_id 至少填一个", true); return; }
  // 存 localStorage 免重复输入（密码+邮箱+chat_id）
  _setSubPwd(subPwd);
  _saveSubUserInfo({ email: email, telegram_chat_id: chatId });
  var payload = { id: "", name: name, email: email, telegram_chat_id: chatId, targets: targets, signals: signals, enabled: true };
  _setSubMsg("保存中...", false);
  _subFetch("/api/subscribe", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  }).then(function (data) {
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
  _subFetch("/api/subscribe").then(function (data) {
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
            return '<span class="hint-sig" style="background:' + (found ? found.color : '#86909c') + '">' + (found ? _t(found.labelKey) : sig) + '</span>';
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
  _subFetch("/api/subscribe/" + encodeURIComponent(subId), { method: "DELETE" })
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
  var labels = { buy: _t("buy_short"), buy_aux: _t("buy_aux"), buy_special: _t("buy_special"), buy_special_filtered: _t("buy_special_filtered_short"), buy_backup: _t("buy_backup"), sell: _t("sell_short"), sell_stop_loss: _t("sell_stop_loss") , band_hold: _t("band_hold") };
  var sigClass = { buy: "buy", buy_aux: "buy-aux", buy_special: "buy-special", buy_special_filtered: "buy-special-filtered", buy_backup: "buy-backup", sell: "sell", sell_stop_loss: "sell-stop-loss" , band_hold: "band-hold" };
  var rows = [];
  var order = ["buy", "buy_aux", "buy_special", "buy_backup", "band_hold", "sell", "sell_stop_loss"];
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
    var name = _t(k.nameKey).split(" · ")[0];
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
  var name = (_INDEX_NAME_MAP[id] || (idx && idx.name) || id);
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
// 2026-07-20 灰色兜底：SIM_INDICES 之外的指数也生成按钮（灰色 disabled + hover 提示"暂未接入"），
// 不再返回空串（用户要求：按钮必须显示，不可用时灰色而非缺失，避免用户以为坏了）。
function _simBtnHtml(indexId) {
  if (!indexId || !SIM_INDICES.has(indexId)) {
    var _label = (indexId && (indexId.startsWith('sw_') || indexId.startsWith('thsc_'))) ? '该行业' : '该指数';
    return `<a class="sim-btn sim-btn-disabled" data-index="${indexId || ''}" title="${_label}暂未接入模拟回测">📊 模拟回测</a>`;
  }
  // gating：未登录 trade_sim 特权 -> 灰色 disabled + data-need-login（_prependSimBtn 注入后绑 click 弹登录提示）
  if (!hasPrivilege('trade_sim')) {
    return `<a class="sim-btn sim-btn-disabled" data-index="${indexId}" data-need-login="trade_sim" title="🔒 模拟回测为登录用户特权，点击登录">📊 模拟回测</a>`;
  }
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
  // gating：未登录 trade_sim 时 _simBtnHtml 返回 data-need-login 灰色版本，此处绑 click 拦截弹登录提示
  var needLoginBtn = wrap.querySelector('[data-need-login="trade_sim"]');
  if (needLoginBtn) {
    needLoginBtn.addEventListener('click', function (e) {
      e.preventDefault();
      e.stopPropagation();
      openLoginPromptForFeature('模拟回测', '模拟回测为登录用户特权，登录后可查看完整回测详情');
    });
  }
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
  // 任务6+7(2026-07-20): 指数类别加强展示 + 国债冲突提示 + 信号概念说明(不替用户下结论,让用户自己判断)
  const _idxName = indexId ? indexIdToName(indexId) : "";
  const _idxCatHtml = _idxName ? `<div class="hint-index-cat">📊 ${_idxName} · 信号统计</div>` : "";
  const _isCgb = !!(indexId && indexId.startsWith("cgb_"));
  // 信号概念说明(一句话含义,不替用户下结论)
  const _sigConcept = {
    buy: "RSI上穿30·超卖拐头(均值回归)",
    buy_aux: "布林下轨回归(左侧布局)",
    buy_special: "唐奇安上轨突破(趋势跟随)",
    buy_special_filtered: "追关注(h5过滤预览)",
    buy_backup: "Supertrend翻多(趋势反转)",
    sell: "MA60多头+MACD死叉(止盈调整)",
    sell_stop_loss: "ATR×3.5止损(趋势破位)",
    band_hold: "国债波段仓管·持有(无超买超卖)",
    band_sell: "国债波段仓管·减仓(触超买锁利润)",
  };
  // 国债品种信号排序: band 体系主信号(band_hold/band_sell/buy_aux/sell_stop_loss)排前, buy_special 排后标"次要·参考"
  const _sigOrder = _isCgb
    ? ["band_hold", "band_sell", "buy_aux", "sell_stop_loss", "buy", "buy_backup", "sell", "buy_special"]
    : ["buy", "buy_aux", "buy_special", "buy_special_filtered", "buy_backup", "band_hold", "sell", "sell_stop_loss"];
  // 国债冲突提示: buy_special(追关注·通用趋势信号) 与 band 体系(波段仓管) 方向相反, 国债上参考意义有限
  const _hasCgbConflict = _isCgb && stats.buy_special && stats.buy_special["10d"] && stats.band_hold && stats.band_hold["10d"];
  const blocks = [];
  const labels = { buy: _t("buy_long"), buy_aux: _t("buy_aux"), buy_special: _t("buy_special"), buy_special_filtered: _t("buy_special_filtered_long"), buy_backup: _t("buy_backup"), sell: _t("sell_long"), sell_stop_loss: _t("sell_stop_loss") , band_hold: _t("band_hold"), band_sell: _t("type_band_sell") };
  const sigClass = { buy: "buy", buy_aux: "buy-aux", buy_special: "buy-special", buy_special_filtered: "buy-special-filtered", buy_backup: "buy-backup", sell: "sell", sell_stop_loss: "sell-stop-loss" , band_hold: "band-hold", band_sell: "band-sell" };
  for (const sig of _sigOrder) {
    const s = stats[sig];
    if (!s || !s["10d"]) continue;
    const d = s["10d"];
    const n = d.n || 0;
    let label = labels[sig];
    const cls = sigClass[sig];
    // 国债上 buy_special 标"次要·参考"(通用趋势信号,国债上参考意义有限)
    const _isMinor = _isCgb && sig === "buy_special";
    if (_isMinor) label = label + `<span class="hint-minor-tag">${_t("treasury_buy_special_minor")}</span>`;
    const _concept = _sigConcept[sig] ? `<span class="hint-concept">${_sigConcept[sig]}</span>` : "";
    if (n < 10) {
      blocks.push(`<div class="hint-row"><span class="hint-sig ${cls}">${label}</span>${_concept}<span class="hint-warn">样本不足（仅 ${n} 例），仅供参考，不计凯利</span></div>`);
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
      ? `<span class="hint-note">收益兑现调整提示，非高胜率反向信号</span>`
      : "";
    // 卖点胜率语义是"走弱概率"（卖后 10 日下跌概率），与买点"胜率"语义对称但口径不同
    const wrLabel = (sig === "sell" || sig === "sell_stop_loss") ? "走弱概率" : "胜率";
    blocks.push(`<div class="hint-row"><span class="hint-sig ${cls}">${label}</span>${_concept}<span class="hint-stat">${wrLabel} <b class="wr ${wrCls}">${wr}%</b></span><span class="hint-stat">盈亏比 ${pl}</span><span class="hint-stat">样本 ${n}</span>${kellyHtml}${honestTag}</div>`);
  }
  if (!blocks.length) return _idxCatHtml + stratHtml || null;
  // 频率统计区块
  let freqHtml = "";
  const freqBlocks = [];
  for (const sig of _sigOrder) {
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
  // 国债冲突提示行(buy_special 追关注 vs band 体系 波段仓管, 方向相反)
  const _conflictHtml = _hasCgbConflict ? `<div class="hint-conflict">⚠ ${_t("treasury_conflict_hint")}</div>` : "";
  // 模拟回测按钮已从 statsHint 移出（2026-07-23 改动3）：原塞在 hint 最前属"策略区块内"，
  // 现由调用方（indexChart / valueChartWithSignals / KPI详情 / 网格）通过 _prependSimBtn
  // 注入 h3 末尾排在❓后（改动4），语义上"真正挪出策略区块"且与❓行内排列。
  return _idxCatHtml + stratHtml + `<div class="hint-header">统计基准：全历史信号 · 信号触发后 10 个交易日收益统计</div>` +
    `<div class="hint-blocks">${blocks.join("")}</div>` +
    freqHtml +
    _conflictHtml +
    `<details class="hint-kelly-explain"><summary>凯利公式是什么？这个数怎么看？</summary>` +
    `<div class="hint-kelly-body">` +
    `<div><b>公式</b>：f* = max(0, (盈亏比 × 胜率 − (1 − 胜率)) ÷ 盈亏比) —— 根据该信号的胜率与盈亏比，算出每次下注的最优资金比例。</div>` +
    `<div><b>"凯利 X%"是什么</b>：理论上每次用总资金的 X% 关注低位机会（或留意高位预警）是数学上的理论参考比例——长期复合增长较快、破产风险较低的资金配置模型。</div>` +
    `<div><b>"凯利公式≤0"是什么意思</b>：公式算出 ≤0，说明这个信号<b>长期期望为负</b>（亏得多赢得少），按公式不应下注。风险点凯利为 0 通常因胜率接近 50% 且盈亏比&lt;1。</div>` +
    `<div><b>风险点语义</b>：D1 风险点是<b>收益兑现调整提示</b>，不是高胜率反向交易指令——风险点后 10 日走弱概率≈50% 接近随机，不可作为独立风险依据（详见规则说明条）。</div>` +
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
  const _closeSuffix = _last && _last.close != null ? `<span class="chart-latest"> · ${fmtDate(_last.date)} ${_last.close.toFixed(2)}<small style="color:var(--text-3)"> 收</small></span>` : "";
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
const _NO_CACHE_URLS = /(?:^|\/)(?:overview|intraday_snapshot|metrics|notifications|public_fund_\w+|summary(?:_history|\/history)?|index\/[^/]+-all)(?:\.json)?(?:$|[?])/;
const _CACHE_TTL = 5 * 60 * 1000; // 历史类数据缓存 5 分钟
// R2 大range 路由（2026-07-24）：all/5y/3y 从 R2 读（减 git 仓库 ~60M），小 range（3m/6m/1y）留本地减延迟。
// fetchJSON 统一走 .json + CF br 压缩（2026-08-01 全部跳 .gz，根治 CF .gz 4h edge 缓存滞后）。
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
  // cache-busting(2026-07-27): 时效敏感URL(_NO_CACHE_URLS匹配)加 ?_=Date.now() 绕过浏览器HTTP缓存;
  //   CF Workers Static Assets 忽略 query string 仍HIT同path, 但 raw .json 走 worker max-age=60规则,
  //   60s后CF边缘缓存过期向R2拉新; .gz走worker兜底无max-age(TTL不可控), 时效敏感URL跳过.gz优先。
  //   cache模式: 时效敏感用no-store(浏览器不读HTTP缓存每次发GET), 其他用no-cache(条件请求省带宽)
  const _isFresh = _NO_CACHE_URLS.test(url);
  const _qIdx = url.indexOf("?");
  const _base = _qIdx >= 0 ? url.slice(0, _qIdx) : url;
  const _origQuery = _qIdx >= 0 ? url.slice(_qIdx) : "";
  // cache-busting query: 时效敏感URL追加 _=Date.now() (CF忽略但浏览器URL不同不读HTTP缓存)
  const _bustQuery = _isFresh
    ? (_origQuery ? _origQuery + "&_=" + Date.now() : "?_=" + Date.now())
    : _origQuery;
  // 2026-08-01 全部跳过 .gz，统一走 .json + CF br 压缩（用户定方案）。
  //   根因: .gz 走 CF edge cache(max-age=14400 4h), 数据更新后 CF 边缘仍可能 serve 旧 .gz 致"暂无数据"线上故障
  //   (2026-07-31 public_fund holdings top50->top100 修复被 CF 缓存旧 .gz 抵消, commit 97c76143 先单独跳 public_fund)。
  //   .json cf-cache-status=DYNAMIC 每次回源拿最新; CF 对 .json 自动 br 压缩(transfer ~15KB 接近 .gz 8KB),
  //   牺牲少许带宽换数据新鲜度 + 消除 .gz 解压失败/CF 缓存滞后风险 + 简化架构(单一 fetch 路径)。
  //   本地/R2 仍保留 .gz 文件(export.py/upload_r2 不改), 只是前端不再 fetch .gz。
  //   .gz fallback 逻辑保留(防御性, 万一未来重新启用 .gz), 但 tryGz=false 时 gzUrl=null 不触发。
  const tryGz = false;
  const gzUrl = tryGz ? _base + ".gz" + _bustQuery : null;
  // 实际请求URL(带cache-busting): 时效敏感用_bustQuery, 其他用原query
  const _fetchUrl = _base + _bustQuery;
  const controller = new AbortController();
  const slowTimer = setTimeout(() => controller.abort(), 15000);
  // cache: 'no-cache' 走条件请求(带 If-None-Match/If-Modified-Since), 绕过 R2 .gz 的 cache-control: max-age=14400 强制缓存
  // 否则 stats 等数据更新后浏览器仍读 4h 旧缓存 (2026-07-22 csi_div tooltip 显示旧版 sell_stop_loss n 而非新版 86 的根因)
  // 时效敏感URL用no-store(浏览器完全不读HTTP缓存每次发GET, 避免CF HIT旧etag返回304浏览器读旧缓存)
  const _cacheMode = _isFresh ? "no-store" : "no-cache";
  const doFetch = (u) => fetch(u, { signal: controller.signal, cache: _cacheMode })
    .then((r) => { if (!r.ok) throw new Error("HTTP " + r.status + " " + u); return r; });
  const p = (async () => {
    let resp;
    try {
      if (gzUrl) {
        resp = await doFetch(gzUrl);
        // DecompressionStream 96%+ 兼容;不支持时抛错走 catch fallback
        if (typeof DecompressionStream === "undefined") throw new Error("DecompressionStream unsupported");
        // resp.body 可能为 null(某些浏览器/拦截场景), pipeThrough 会抛 TypeError; 显式抛错走 fallback
        if (!resp.body) throw new Error("gz response body is null");
        const ds = new DecompressionStream("gzip");
        const decompressed = resp.body.pipeThrough(ds);
        const txt = await new Response(decompressed).text();
        return JSON.parse(txt);
      }
      resp = await doFetch(_fetchUrl);
      return await resp.json();
    } catch (e) {
      // .gz 失败(404/解压错/不支持/body null) -> fallback 原 .json(只对原本就是 .gz 尝试的 URL)
      // 用 _fetchUrl(带 cache-busting) 而非 url(原始), 保持与主路径一致的 cache-busting 语义
      if (gzUrl && !(e && e.name === "AbortError")) {
        console.warn("[fetchJSON] .gz failed, fallback to .json: " + url, e?.message || e);
        resp = await doFetch(_fetchUrl);
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
      } else {
        // 非 abort 错误(网络/CORS/解析/HTTP)也记 console, 便于排查"暂无数据"类故障
        console.error("fetchJSON failed: " + url, e?.message || e);
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

// ============ BUG-E：交互增强（行业筛选 + 热力图切换 + 指数目录锚点）============
// 纯前端筛选/锚点，不影响后端数据。指数目录锚点条放指数折线区前(吸顶), 点击 chip 平滑滚动到对应卡片:
// 始终全部渲染指数(不再单指数筛选), scroll spy 高亮当前可见卡对应 chip, 切 tab disconnect observer。
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
        <div class="market-cell-label">高位预警</div>
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

function renderIndicesSection(container, indices, fetcher, foldOneRow, extraGroups, anchorBarRef) {
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
    // 指数目录锚点(吸顶 + chip 点击跳转 + scroll spy); 复用 .industry-anchor-bar CSS
    // 默认组"主指数": 本 section 全部 entries; caller 可通过 extraGroups 追加(港股板块8 chip)
    // 切 tab 时 clearCharts -> disconnectAllIndexNavSpies 统一 disconnect
    const anchorGroups = [{
      label: "主指数",
      items: entries.map(([id, idx]) => ({ key: id, name: (_INDEX_NAME_MAP[id] || idx.name), targetId: "idx-card-" + id }))
    }];
    if (extraGroups && extraGroups.length) anchorGroups.push(...extraGroups);
    const anchorBar = buildIndexAnchorBar(anchorGroups, "指数目录");
    if (anchorBarRef) anchorBarRef.bar = anchorBar;  // 暴露给 caller(renderHK observe 板块 cell 用)
    container.appendChild(anchorBar);
    // 6色信号图例（4色买点+卖绿+追止损蓝）+ 备买风险提示（2026-07-21 阶段4）
    container.insertAdjacentHTML("beforeend", _signalLegendHtml());
    // 渲染期间显示 loading 占位；renderOne 首次成功渲染时移除占位；若最终没有任何 chart-card 渲染则替换为"暂无数据"。
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
        const c = indexChart((_INDEX_NAME_MAP[id] || idx.name) + intradayTag, idx.data, sig.signals, sig.stats, idx.strategy, parent, charts, id);
        sectionCharts.push(c);
        const cardEl = c.getDom().parentElement;
        // 目录锚点跳转目标 id + scroll spy observe(卡片渲染完后注册)
        cardEl.id = "idx-card-" + id;
        anchorBar._observeIndexCard(cardEl);
        addCardTimeBadge(cardEl, idx.data.length ? idx.data[idx.data.length - 1].date : "", state.intradaySnapshot, "t0");
        // 标题❓策略弹窗（2026-07-20 方案B1）：h3 末尾追加❓，hover 一句话摘要 + click 弹该指数6类策略详情 modal
        _appendStrategyHint(cardEl, id, idx.strategy);
        // P2-新-G ETF 联动推荐：h3 末尾追加 ETF tag（buy 信号触发时加 .etf-tag-buy-signal 高亮）
        _appendEtfLinkTag(cardEl, id, idx.etfs, sig.signals);
        // 备买 chip 三档（2026-07-23）：标题下换行单独一行展示，h3 之后插入独立 chip-row 容器（异步 fetch+patch）
        _appendBackupChipRow(cardEl, id);
        // C7 P4 market 融合:图表卡下 append 紧凑分数卡(白名单 iid 才显示)
        _attachMarketScoreCard(id, (_INDEX_NAME_MAP[id] || idx.name), cardEl);
        // A5 真 pin 复盘：h3 末尾追加 📌 按钮（钉住该指数，顶部显示专属复盘面板）
        _appendPinBtn(cardEl, id, idx, sig);
        // A12 订阅推送：h3 末尾追加 🔔 按钮（订阅该指数信号，推送邮件+Telegram）
        _appendSubscribeBtn(cardEl, id, (_INDEX_NAME_MAP[id] || idx.name));
      }
    }
    // A股/港股(foldOneRow=true)全部指数直接铺入 .indices-grid 网格(不折叠，无"更多指数"按钮)。
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
      chartLoadingEl.innerHTML = "📊 暂无指数数据";
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
    const name = ((_INDEX_NAME_MAP[id] || idx.name || "")).toLowerCase();
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
        <div class="rule-card-head"><span class="rule-badge badge-buy">主关注</span> 超卖反弹（RSI 指标）</div>
        <p>当市场<b>短期跌过头了</b>，开始反弹时，作为技术信号参考（超卖反弹）。</p>
        <table class="rule-table">
          <tr><td class="rule-td-label">含义</td><td>RSI 指标跌到 30 以下（超卖区），然后回升到 30 以上 —— 说明抛压衰竭、买方开始进场</td></tr>
          <tr><td class="rule-td-label">触发</td><td>前一日 RSI ≤ 30，当日回升到 30 以上</td></tr>
          <tr><td class="rule-td-label">颜色</td><td><span class="rule-badge badge-buy">红色</span> 图表上标记为「关注」</td></tr>
          <tr><td class="rule-td-label">胜率</td><td>近 3 年 10 日内盈亏比 <b>1.13</b></td></tr>
          <tr><td class="rule-td-label">特殊</td><td><b>科创50、电力设备、传媒</b> 这 3 个品种波动更大，阈值收紧到 25（RSI ≤ 25 才算超卖），更早捕捉反弹</td></tr>
        </table>
      </div>

      <div class="rule-card rule-card-aux">
        <div class="rule-card-head"><span class="rule-badge badge-aux">辅关注</span> 超卖反弹（布林带下轨）</div>
        <p>价格<b>跌破布林带下轨后弹回来</b>，也是超卖反弹信号，与主关注互补。</p>
        <table class="rule-table">
          <tr><td class="rule-td-label">含义</td><td>布林带下轨 = 近 20 日均价 - 2 倍标准差，跌破后收回 = 极端超卖后的反弹</td></tr>
          <tr><td class="rule-td-label">触发</td><td>前一日收盘价跌破布林下轨，当日回升到下轨之上</td></tr>
          <tr><td class="rule-td-label">颜色</td><td><span class="rule-badge badge-aux">粉紫</span> 图表上标记为「辅关注」</td></tr>
          <tr><td class="rule-td-label">胜率</td><td>近 3 年 10 日内盈亏比 <b>1.18</b></td></tr>
          <tr><td class="rule-td-label">去重</td><td>如果同一天主关注和辅关注同时触发，只保留主关注（不重复标记）</td></tr>
        </table>
      </div>
    </div>

    <div class="rule-section">
      <h4><span class="rule-dot rule-dot-sell"></span>趋势转弱参考点</h4>

      <div class="rule-card rule-card-sell">
        <div class="rule-card-head"><span class="rule-badge badge-sell">风险提醒</span> 趋势转弱参考 · 收益兑现调整提示（非风险指令）</div>
        <p>价格从<b>近期高点回落</b>，且动量转弱时，作为技术信号参考（趋势转弱）。三个条件<b>同时满足</b>才触发：</p>
        <table class="rule-table">
          <tr><td class="rule-td-label">① 价格回落</td><td>从近 20 个交易日的<b>最高价</b>回落超过 <b>5%</b>（用最高价而非收盘价，更能捕捉盘中真实高点）</td></tr>
          <tr><td class="rule-td-label">② 趋势过滤</td><td>收盘价仍在 <b>60 日均线</b> 之上（只在多头趋势中提示风险，下跌趋势中不制造噪音）</td></tr>
          <tr><td class="rule-td-label">③ 动量确认</td><td><b>MACD 死叉</b> —— 短期动量线（DIF）下穿长期动量线（DEA），确认上涨动能减弱</td></tr>
          <tr><td class="rule-td-label">颜色</td><td><span class="rule-badge badge-sell">绿色</span> 图表上标记为「风险提醒」</td></tr>
          <tr><td class="rule-td-label">胜率</td><td>近 3 年 10 日走弱概率 <b>55%</b>（接近随机，非高胜率反向信号）</td></tr>
        </table>
        <p class="rule-note">⚠️ <b>重要</b>：这是收益兑现调整提示，<b>不是风险信号</b>。在单边上涨市中可能出现假信号（趋势跟踪类指标的固有代价）。震荡/下跌市中收益兑现提示更有效。</p>
      </div>
    </div>

    <div class="rule-section">
      <h4><span class="rule-dot rule-dot-special"></span>追关注与风控参考点</h4>

      <div class="rule-card rule-card-special">
        <div class="rule-card-head"><span class="rule-badge badge-special">追关注</span> 上轨突破（唐奇安 20 日）</div>
        <p>唐奇安 20 日上轨突破 + 5 日确认。<b>趋势跟随</b>思路，突破后惯性上行。</p>
        <table class="rule-table">
          <tr><td class="rule-td-label">含义</td><td>收盘价突破近 20 日最高价（不含当日），5 日内确认有效</td></tr>
          <tr><td class="rule-td-label">颜色</td><td><span class="rule-badge badge-special">金色</span> 图表上标记为「追关注」</td></tr>
          <tr><td class="rule-td-label">回测持有期建议</td><td>5d 胜率59.65%/均值+0.87%/回撤2.65%；10d 60.24%/+1.66%/4.26%（<b>风险调整最优</b>）；30d 59.06%/+3.44%（<b>分水岭</b>，风险/收益拐点）；90d 60.83%/+9.42%/回撤16.53%（<b>纯收益最优</b>，但回撤大）</td></tr>
        </table>
        <p class="rule-note">⚠️ <b>趋势跟踪策略</b>：低胜率靠大盈拉均值，区别于主关注/辅关注的均值回归（高胜率小赚）。必须配「追风控|警示」控制风险，0 套牢。</p>
      </div>

      <div class="rule-card rule-card-stop-loss">
        <div class="rule-card-head"><span class="rule-badge badge-stop-loss">追风控|警示</span> ATR×3.5 风控</div>
        <p>价格跌破 <b>ATR×3.5 动态风控线</b>（底层规则从唐奇安20日下轨改为 ATR×3，2026-07-21 调 ATR×3.5 降频）。趋势反转下行最后防线。</p>
        <table class="rule-table">
          <tr><td class="rule-td-label">含义</td><td>ATR（平均真实波幅）×3.5 作为风控距离，波动大时风控宽、波动小时风控窄，自适应市场节奏</td></tr>
          <tr><td class="rule-td-label">颜色</td><td><span class="rule-badge badge-stop-loss">蓝色</span> 图表上标记为「追风控|警示」</td></tr>
          <tr><td class="rule-td-label">回测对比</td><td>现 ATR×3 胜率46.91%/均值+1.76%/盈亏比1.82，全维度略优原唐奇安20日（胜率44.33%/均值+1.56%，2008股灾-10.5%最差）。2026-07-21 调 ATR×3.5 降频后 hs300 触发 -18%/5日胜率 49.58%->50.23%</td></tr>
        </table>
        <p class="rule-note">⚠️ <b>最后防线</b>：跌破即防范风险，趋势反转下行。与「风险」共振时调整信号更强。蓝色与风险绿色区分。</p>
      </div>

      <div class="rule-card rule-card-backup">
        <div class="rule-card-head"><span class="rule-badge badge-backup">备关注</span> 超级趋势翻多（ATR×3 + 3 日确认）</div>
        <p>超级趋势(Supertrend) ATR×3 翻多 + 3 日二次确认，<b>趋势反转确认</b>。与追关注（唐奇安突破）互补，作为趋势类信号的备选参考。</p>
        <table class="rule-table">
          <tr><td class="rule-td-label">含义</td><td>Supertrend 指标翻多（ATR×3 乘数），3 日内二次确认有效，过滤诱多</td></tr>
          <tr><td class="rule-td-label">颜色</td><td><span class="rule-badge badge-backup">紫色</span> 图表上标记为「备关注」</td></tr>
          <tr><td class="rule-td-label">稳健性</td><td>弱于追关注（唐奇安突破），仅供参考不单独决策</td></tr>
        </table>
        <p class="rule-note">⚠️ <b>稳健性弱于追关注</b>。配套：仅供参考不单独决策，需结合主关注/辅关注/追关注；诱多风险已用 3 日二次确认过滤。</p>
      </div>
    </div>

    <div class="rule-section">
      <h4><span class="rule-dot rule-dot-band-hold"></span>国债波段仓位管理参考点</h4>

      <div class="rule-card rule-card-band-hold">
        <div class="rule-card-head"><span class="rule-badge badge-band-hold">波段持有</span> 国债仓位维持（无超买超卖）</div>
        <p>国债三品种波段仓位管理策略·<b>波段持有状态</b>。RSI+乖离+布林三指标无超买超卖信号，维持当前仓位。替代原 D1卖点(趋势转弱风险)对国债完全失效（sell=0 无理由）的问题。</p>
        <table class="rule-table">
          <tr><td class="rule-td-label">含义</td><td>国债专属动态仓位管理·维持仓位动作（非清仓卖出卖点，非静态 sell）</td></tr>
          <tr><td class="rule-td-label">颜色</td><td><span class="rule-badge badge-band-hold">橙色</span> 仓位条维持 + 图钉</td></tr>
          <tr><td class="rule-td-label">回测依据</td><td>cgb_idx 降风险(回撤-10.4%-&gt;-4.8%,夏普2.80-&gt;3.58)；cgb_10y_etf 放宽双赢(夏普1.31-&gt;1.52)；cgb_10y_future 双赢(年化1.30%-&gt;1.63%,夏普0.42-&gt;1.58)</td></tr>
        </table>
        <p class="rule-note">⚠️ <b>国债专属动态仓位管理</b>（非静态 sell，非清仓卖出卖点）。四动作联动：减仓(草绿#8bc34a仓位条+图钉头,触超买减20-30%)/接回(buy_aux粉紫,超卖回归接回)/止损(sell_stop_loss蓝,趋势破位清仓卖出)/波段持有(band_hold橙,无超买超卖维持仓位)。研究参考，不构成投资建议。</p>
      </div>

      <div class="rule-card rule-card-band-sell">
        <div class="rule-card-head"><span class="rule-badge badge-band-sell">波段调整</span> 国债减仓（触超买锁利润）</div>
        <p>国债波段仓位管理策略·<b>减仓动作</b>。触发超买条件(bias20&gt;0.3% AND RSI&gt;rsi_high OR close≥布林上轨)时减仓 20-30% 锁利润。与风险提醒区分：减仓非清仓卖出，体现"没卖重"。</p>
        <table class="rule-table">
          <tr><td class="rule-td-label">含义</td><td>国债专属减仓动作（减仓 20-30%，非清仓卖出退出）</td></tr>
          <tr><td class="rule-td-label">颜色</td><td><span class="rule-badge badge-band-sell">草绿色</span> 仓位条减少 100%-&gt;80%/70% + 图钉头（与风险提醒绿 #2e8b57 区分）</td></tr>
          <tr><td class="rule-td-label">触发</td><td>bias20&gt;0.3% AND RSI&gt;rsi_high OR close≥布林上轨，减仓 20-30%</td></tr>
        </table>
        <p class="rule-note">⚠️ <b>国债专属减仓动作</b>(草绿#8bc34a仓位条减少 100%-&gt;80%/70%)。触超买减仓 20-30%，非清仓卖出退出。与止损(sell_stop_loss蓝,趋势破位清仓卖出)区分：减仓是主动锁利润，止损是被动防范。研究参考，不构成投资建议。</p>
      </div>
    </div>

    <div class="rule-section">
      <h4><span class="rule-dot rule-dot-read"></span>如何解读信号</h4>

      <p class="rule-subtitle">盈亏标注（风险提醒颜色含义）</p>
      <table class="rule-table rule-table-color">
        <tr>
          <td><span class="rule-dot-sm rule-dot-profit"></span> <b>绿色 = 收益兑现</b></td>
          <td><span class="rule-dot-sm rule-dot-profit"></span> <b>绿色 = 趋势转弱</b></td>
        </tr>
        <tr>
          <td>风险提醒价格 &gt; 前一个关注点价格<br><span class="muted">→ 历史多为收益兑现/调整情形</span></td>
          <td>风险提醒价格 &le; 前一个关注点价格 / 附近无前关注参考<br><span class="muted">-> 含前关注失效/无前关注点，统一落趋势转弱（非操作建议）</span></td>
        </tr>
      </table>

      <p class="rule-subtitle">pin「盈亏X%」标签来源</p>
      <p class="muted">风险提醒图钉上的「盈亏X%」标签 = sell 信号 reason 中「vs前买+X%」的<b>单次配对实现涨幅</b>（该风险提醒 vs 前一个关注点的实际涨跌），<b>非统计期望值</b>。悬停提示的「盈亏比Y」才是历史统计值。二者勿混。</p>

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
      <div class="rule-example"><span class="muted">主关注：</span>RSI上穿30(29→34), 情绪=8[冰点]</div>
      <div class="rule-example"><span class="muted">辅关注：</span>布林下轨回归(下轨3852,收盘3870), RSI=41, 情绪=47[偏冷]</div>

      <p class="rule-subtitle">趋势转弱参考点示例</p>
      <div class="rule-example"><span class="muted">风险提醒：</span>20日高回落5%(高4259→阈4046,收盘4028), RSI=40, 情绪=53[中性], MA60=4000[趋势过滤], MACD=死叉确认, 较前关注+2.30%[收益兑现]</div>
    </div>

    <div class="rule-section rule-section-sm">
      <h4><span class="rule-dot rule-dot-stat"></span>当前信号统计</h4>
      <table class="rule-table rule-table-stat">
        <tr><td class="rule-td-label">主关注</td><td><b>3,673</b> 个</td><td class="rule-td-label">辅关注</td><td><b>3,918</b> 个</td></tr>
        <tr><td class="rule-td-label">风险提醒</td><td><b>3,185</b> 个</td><td class="rule-td-label">风险/关注比</td><td><b>0.42</b>（风险/关注平衡）</td></tr>
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
  modal.innerHTML = '<div class="rule-modal-overlay"></div><div class="rule-modal-body"><div class="rule-modal-header"><h3>&#128203; ' + _t("rule_modal_title") + '</h3><button class="rule-modal-close" aria-label="关闭">&times;</button></div><div class="rule-modal-content">' + ruleContentHtml() + '</div></div>';
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
          const labels = { buy: _t("buy_long"), buy_aux: _t("buy_aux"), buy_special: _t("buy_special"), buy_special_filtered: _t("buy_special_filtered_long"), buy_backup: _t("buy_backup"), sell: _t("sell_long"), sell_stop_loss: _t("sell_stop_loss") , band_hold: _t("band_hold") };
          const cls = { buy: "buy", buy_aux: "buy-aux", buy_special: "buy-special", buy_special_filtered: "buy-special-filtered", buy_backup: "buy-backup", sell: "sell", sell_stop_loss: "sell-stop-loss" , band_hold: "band-hold" };
          let html = '<div class="hint-header">📅 全品种信号频率汇总</div><div class="hint-blocks">';
          for (const sig of ["buy", "buy_aux", "buy_special", "buy_special_filtered", "buy_backup", "band_hold", "sell", "sell_stop_loss"]) {
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
  modal.innerHTML = '<div class="rule-modal-overlay"></div><div class="rule-modal-body signal-chart-modal-body"><div class="rule-modal-header"><h3 class="signal-chart-title">走势图</h3><div class="signal-chart-periods"><button class="lab-signal-period-btn active" data-period="3m">3月</button><button class="lab-signal-period-btn" data-period="6m">6月</button><button class="lab-signal-period-btn" data-period="1y">1年</button><button class="lab-signal-period-btn" data-period="3y">3年</button><button class="lab-signal-period-btn" data-period="5y">5年</button><button class="lab-signal-period-btn" data-period="all">全部</button></div><button class="rule-modal-close" aria-label="关闭">&times;</button></div><div class="rule-modal-content signal-chart-content"></div></div>';
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

async function openSignalChartModal(indexId, signal, date, freezeVal, period = "3m") {
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
    // 信号弹窗定位路径(2026-08-04)：复用 hoverpop 同款 .term-pop-locate + document 级 click 委托
    // 告知用户指数完整数据在哪个 tab，点击切 tab + 滚动高亮卡片（hoverpop 里那份保留不动）
    if (indexId && typeof indexToMarketSubtab === "function") {
      var _modalLoc = indexToMarketSubtab(indexId);
      if (_modalLoc && _modalLoc.tab && _modalLoc.tabName) {
        var _modalLocTxt = _modalLoc.tab === "sentiment"
          ? "📍 完整数据：" + _modalLoc.tabName
          : "📍 完整数据：" + _modalLoc.tabName + " > " + (_modalLoc.name || "") + " > " + (_modalLoc.idxName || "");
        var _modalLocEl = document.createElement("span");
        _modalLocEl.className = "term-pop-locate term-pop-locate--modal";
        _modalLocEl.setAttribute("data-locate-idx", indexId);
        _modalLocEl.textContent = _modalLocTxt;
        body.appendChild(_modalLocEl);
      }
    }
    // B2 方案B(2026-07-27): 走势图数据未同步到 T 日时提示 - 盘中 sw_/thsc_/cgb_ 等行业概念指数
    // 的 -all.json 不更新(末日停 T-1),用户点首页 T 日 pin 弹窗看不到 T 日 K 线/pin。
    // 触发: chartData 末日 < overview.date(T 日) = 数据未同步; 末日==T 日(已同步)不显示。
    // 收盘后 update_all(17:50) 全量 export,所有指数 -all.json 同步到 T 日,提示自动消失。
    // 方案0(2026-07-28): _lagHint 仅对今日有信号的指数提示，无信号指数不误报"待17:50同步"。
    // _sigsSR 提前到此（原在 L3249 之后），供 _lagHint 条件 + 下方信号至今盈亏行共用。
    const _ovSR = _getCachedOverview();
    const _sigsSR = _ovSR && _ovSR.signals_today ? _ovSR.signals_today : [];
    const _todayDateB2 = _ovSR && _ovSR.date ? _ovSR.date : "";
    const _lastDateB2 = chartData && chartData.length ? chartData[chartData.length - 1].date : "";
    // 今日该指数有信号才提示（.some 过滤 signals_today 中 index_id 匹配且 date===T日）
    const _hasTodaySigB2 = _sigsSR.some(it => it.index_id === indexId && it.date === _todayDateB2);
    if (_todayDateB2 && _lastDateB2 && _lastDateB2 < _todayDateB2 && _hasTodaySigB2) {
      const _lagHint = document.createElement("div");
      _lagHint.className = "sig-chart-lag-hint";
      _lagHint.setAttribute("style", "margin-bottom:8px;padding:6px 10px;font-size:12px;color:#e6a23c;background:rgba(230,162,60,0.1);border:1px solid rgba(230,162,60,0.3);border-radius:4px;line-height:1.5;");
      _lagHint.innerHTML = "⚠ 走势图数据截止 " + fmtDate(_lastDateB2) + "，T日(" + fmtDate(_todayDateB2) + ")有信号·盘中实时预估中，收盘后(17:50)同步最终pin";
      body.appendChild(_lagHint);
    }
    // 方案A(2026-07-28): chartData 末日<T日时，从 intraday_snapshot.json 读实时价补 T 日预估点（兜底）。
    // 覆盖 B 未覆盖的指数/未到 15min 增量窗口的时差：只要该指数在 intraday_snapshot.indices 有实时 close 即补。
    if (_todayDateB2 && _lastDateB2 && _lastDateB2 < _todayDateB2) {
      const _estPt = await _appendIntradayEstimate(chartData, sigs, indexId, _todayDateB2, isValue);
      if (_estPt) {
        // 补点后 chartData 末日==T日，无需再显示 _lagHint 误报（但上方 _lagHint 已基于 _hasTodaySigB2 渲染，保留语义提示）
        // 补的预估点用 "estimate" 信号 pin 标注，视觉区分（灰色虚线 pin）
      }
    }
    // 信号至今盈亏行（方案B后端算）：文案=成功/失败·至今盈亏 ±X%（since_correct=null 今日/band_hold 仅显示盈亏不带成功失败）；颜色=A股红涨绿跌按since_return正负（>0红/<0绿/==0灰）
    const _matchSR = _sigsSR.find((it) => it.index_id === indexId && it.signal === signal && it.date === date);
    if (_matchSR && _matchSR.since_return != null) {
      const _srLine = document.createElement("div");
      _srLine.setAttribute("style", "margin-bottom:8px;padding:6px 10px;font-size:12px;border-radius:4px;line-height:1.5;");
      const _ret = _matchSR.since_return;
      const _correct = _matchSR.since_correct;
      const _retStr = (_ret > 0 ? "+" : "") + _ret.toFixed(2) + "%";
      let _txt, _color;
      // 文案按 since_correct 对错（成功/失败/中性）；颜色按 since_return 盈亏正负（A股红涨绿跌：>0红/<0绿/==0灰）
      if (_correct === true) { _txt = `成功 · 至今盈亏 ${_retStr}`; }
      else if (_correct === false) { _txt = `失败 · 至今盈亏 ${_retStr}`; }
      else { _txt = `至今盈亏 ${_retStr}`; }
      if (_ret > 0) { _color = "#dc2626"; }
      else if (_ret < 0) { _color = "#16a34a"; }
      else { _color = "#6b7280"; }
      _srLine.style.color = _color;
      _srLine.style.background = `${_color}1a`;
      _srLine.style.border = `1px solid ${_color}55`;
      _srLine.textContent = _txt;
      body.appendChild(_srLine);
    }
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
  modal.innerHTML = '<div class="rule-modal-overlay"></div><div class="rule-modal-body kpi-detail-modal-body"><div class="rule-modal-header"><h3 class="kpi-detail-title">关键指标(KPI)走势</h3><div class="signal-chart-periods"><button class="lab-signal-period-btn active" data-period="3m">3月</button><button class="lab-signal-period-btn" data-period="6m">6月</button><button class="lab-signal-period-btn" data-period="1y">1年</button><button class="lab-signal-period-btn" data-period="3y">3年</button><button class="lab-signal-period-btn" data-period="5y">5年</button><button class="lab-signal-period-btn" data-period="all">全部</button></div><button class="rule-modal-close" aria-label="关闭">&times;</button></div><div class="rule-modal-content kpi-detail-content"></div></div>';
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
    // intraday 半日值(source='intraday')视觉区分：拆 series，intraday 段虚线 + 半透明 + tooltip 标"盘中半日值"
    // 避免 2026-08-04 半日值混入日频序列尾部下掉 37% 误导
    if (kpiId === "a_amount") {
      const rawAmount = (metrics["a_amount"] && metrics["a_amount"].data) || [];
      const closedData = rawAmount.filter(d => d.source !== "intraday").map(d => ({ date: d.date, value: d.value }));
      const intradayData = rawAmount.filter(d => d.source === "intraday").map(d => ({ date: d.date, value: d.value }));
      const series = [{ name: "成交额", data: closedData }];
      // intraday 段：单点 symbol + markLine 虚线半透明连接最后收盘点（visual 区分盘中半日值）
      if (intradayData.length && closedData.length) {
        const lastClose = closedData[closedData.length - 1];
        const firstIntra = intradayData[0];
        series.push({
          name: "成交额(盘中)",
          data: intradayData,
          color: "#e6492e",
          lineStyle: { type: "dashed", opacity: 0.5 },
          itemStyle: { opacity: 0.5 },
          symbol: "circle",
          symbolSize: 6,
          markLine: {
            silent: true,
            symbol: "none",
            lineStyle: { type: "dashed", color: "#e6492e", opacity: 0.5 },
            data: [[{ coord: [lastClose.date, lastClose.value] }, { coord: [firstIntra.date, firstIntra.value] }]],
          },
        });
      } else if (intradayData.length) {
        series.push({
          name: "成交额(盘中)",
          data: intradayData,
          color: "#e6492e",
          lineStyle: { type: "dashed", opacity: 0.5 },
          itemStyle: { opacity: 0.5 },
          symbol: "circle",
          symbolSize: 6,
        });
      }
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
        hint: "沪深京A股成交额。放量=交投活跃，缩量=清淡。MA5/MA20为均量线。虚线半透明段=盘中半日值，收盘后覆盖为全天值。",
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
    // P0-1(2026-07-28): 补 T 日预估点（KPI 场景，数据源=overview.today 非 intraday_snapshot）。
    // chartData 末日<T日时，从 overview.today 查 KPI 当日值补灰色"预估"点（T+1 源无 T 日值不补）。
    // 必须在算 dates/seriesOpt 之前补，这样 T 日点纳入 xAxis 范围 + seriesOpt.data。
    const _ovK = _getCachedOverview();
    const _todayDateK = _ovK && _ovK.date ? _ovK.date : "";
    const _estimates = _todayDateK ? await _appendKpiEstimate(result, kpiId, _todayDateK) : [];
    const _hasEst = _estimates.length > 0;
    const last = mainSeries.data[mainSeries.data.length - 1];
    const suffix = last ? ` <span class="chart-latest">· ${fmtDate(last.date)}${_hasEst ? " (预估)" : ""}</span>` : "";
    const noteHtml = result.note ? ` <span class="chart-latest" style="color:var(--text-3)">（${result.note}）</span>` : "";
    const chartCard = document.createElement("div");
    chartCard.className = "chart-card";
    const hintHtml = result.hint ? `<div class="chart-hint">${result.hint}</div>` : "";
    chartCard.innerHTML = `<h3>${cardTitle}走势${suffix}${noteHtml}</h3>${hintHtml}<div class="chart" style="height:380px"></div>`;
    body.appendChild(chartCard);
    const chart = echarts.init(chartCard.querySelector(".chart"));
    _kpiDetailCharts.push(chart);

    const dates = [...new Set(result.series.flatMap(s => (s.data || []).map(d => d.date)))].sort();
    const seriesOpt = result.series.map((s, idx) => {
      // P0-1: 补了预估点的 series 加灰色"预估"markPoint（与信号弹窗 estimate pin 风格一致）
      const est = _estimates.find(e => e.seriesIdx === idx);
      const markPoint = est ? {
        symbol: "circle",
        symbolSize: 8,
        label: { show: true, formatter: "预估", color: "#909399", position: "top", fontSize: 10 },
        itemStyle: { color: "#909399" },
        data: [{ coord: [est.date, est.value], value: "预估" }],
      } : undefined;
      // 合并 lineStyle：s.color 提供默认色，s.lineStyle（如 intraday 虚线/半透明）可覆盖/扩展
      const _lineStyle = { ...(s.color ? { color: s.color } : {}), ...(s.lineStyle || {}) };
      return {
        name: s.name,
        type: "line",
        smooth: true,
        symbol: s.symbol != null ? s.symbol : "none",
        ...(s.symbolSize != null ? { symbolSize: s.symbolSize } : {}),
        connectNulls: true,
        data: dates.map(d => { const p = (s.data || []).find(x => x.date === d); return p ? p.value : null; }),
        ...(s.color ? { color: s.color } : {}),
        ...(Object.keys(_lineStyle).length ? { lineStyle: _lineStyle } : {}),
        ...(s.itemStyle ? { itemStyle: s.itemStyle } : {}),
        ...(s.areaStyle ? { areaStyle: s.areaStyle } : {}),
        ...(s.markLine ? { markLine: s.markLine } : {}),
        ...(markPoint ? { markPoint } : {}),
      };
    });
    // tooltip formatter：从 yLabel "{value}亿" 提取单位后缀；series 名含"盘中"标注"盘中半日值"
    const _unit = result.yLabel ? (String(result.yLabel).match(/\{value\}([\s\S]*)/) || [])[1] || "" : "";
    chart.setOption(withTheme({
      tooltip: {
        trigger: "axis",
        formatter: (params) => {
          if (!Array.isArray(params) || !params.length) return "";
          const lines = [fmtDate(params[0].axisValueLabel || params[0].name)];
          for (const p of params) {
            if (p.value == null) continue;
            const isHalfDay = p.seriesName && p.seriesName.indexOf("盘中") >= 0;
            const val = typeof p.value === "number" ? p.value.toFixed(2) : p.value;
            lines.push(`${p.marker}${p.seriesName}: ${val}${_unit}${isHalfDay ? " (盘中半日值)" : ""}`);
          }
          return lines.join("<br/>");
        },
      },
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
  loadEcharts();   // P0-1: 启动 echarts 加载（不 await 阻塞，子 render 按需 await loadEcharts；loadEcharts 内部缓存 Promise 不重复加载）
  // 确保 SIM_INDICES 动态清单已加载（initSimIndices 启动时发 fetch），避免首渲按钮全灰
  if (_simIndicesPromise) { try { await _simIndicesPromise; } catch (e) { /* catch 内已处理 */ } }
  clearCharts();
  // 概览 tab 图表固定近60日、策略实验 tab 全历史，周期切换均无意义，隐藏 .periods 和 .h5-period-bar；切走恢复
  const _hidePeriods = (state.tab === "lab" || state.tab === "overview" || state.tab === "fund");
  document.querySelectorAll(".periods, .h5-period-bar").forEach((el) => {
    el.style.display = _hidePeriods ? "none" : "";
  });
  renderLoadingState(content);
  try {
    if (state.tab === "overview") await renderOverview();
    else if (state.tab === "market") await renderMarket();
    else if (state.tab === "sentiment") await renderSentiment();
    else if (state.tab === "fund") await renderFund();
    else if (state.tab === "lab") {
      await loadLabScript();   // B5: 懒加载 lab.js
      await loadEcharts();   // P0-1: lab.js 图表依赖 echarts（renderTab 顶层已 fire-and-forget 启动，此处 await 确保 lab 渲染前就绪）
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
// 采集时间统一口径（阶段2）：盘中"HH:MM · 动态(1min)"（腾讯最近拉取时间），收盘"HH:MM · 收盘快照"。
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
  const suffix = intraday ? " · 动态(1min)" : " · 收盘快照";
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
// AZ54 P1-6: 盘中状态全局标识横幅(所有 tab 可见).
//   snap.is_closed===false -> 显示(顶部 risk-banner 下方全局条, 切 tab 不消失)
//   snap.is_closed===true  -> 隐藏(收盘后自动收起)
//   午休时段(snap.label 含"午休") -> 换文案"午休时段 · 13:00复牌后恢复实时"
//   手动关闭 -> 本次 session 隐藏(_marketBannerDismissed=true, 收盘后再开盘会重置)
// 调用点: fetchIntradaySnapshot 回调内(snap 就绪即更新, 覆盖首屏/轮询/开盘检测/收盘切换全部场景)
let _marketBannerDismissed = false;
let _marketBannerBound = false;
function updateMarketStatusBanner(snap) {
  const el = document.getElementById("market-status-banner");
  if (!el) return;
  if (!_marketBannerBound) {
    _marketBannerBound = true;
    el.querySelector(".msb-close")?.addEventListener("click", () => {
      _marketBannerDismissed = true;
      el.style.display = "none";
    });
  }
  const intraday = !!(snap && snap.is_closed === false);
  // P2-C: 盘前集合竞价申报段(9:15-9:25)前端独立时间判断
  // 后端 is_closed 在 9:15-9:25 仍返 true(收盘快照), 9:25 才切 false(竞价完成)
  // 此处前端基于北京时间判断, 不依赖后端 label, 避免盘前显示"收盘"误导用户以为没开盘
  // 节假日前端难判, 盘前提示横幅节假日误显无害(9:25 后无新数据自然恢复收盘态)
  const _bjMin = _bjTimeMin();
  const _bjDow = _bjDayOfWeek();
  const _isWeekday = _bjDow >= 1 && _bjDow <= 5; // 周一-周五兜底(节假日误显无害)
  const _isAuctionCall = !intraday && _isWeekday && _bjMin >= 9 * 60 + 15 && _bjMin < 9 * 60 + 25;
  if (_marketBannerDismissed) {
    el.style.display = "none";
    return;
  }
  if (!intraday && !_isAuctionCall) {
    el.style.display = "none";
    return;
  }
  el.style.display = "";
  // 5态区分: P2-C盘前竞价申报段(前端时间判断) + 4态(对齐后端 is_market_closed label): 集合竞价/竞价完成/午休/盘中实时小结
  const _label = (snap && snap.label) || "";
  const txt = el.querySelector(".msb-text");
  if (txt) {
    let _t;
    if (_isAuctionCall) {
      // 9:15-9:25 申报段: 后端仍 is_closed=true, 前端独立显示竞价申报中
      _t = "📊 集合竞价申报中 · 9:25定开盘价·9:30开盘 · 开盘价未定暂显昨收";
    } else if (/集合竞价/.test(_label)) {
      _t = "📊 集合竞价中 · 9:25竞价完成·9:30开盘 · 开盘价待定";
    } else if (/竞价完成/.test(_label)) {
      _t = "📊 竞价完成 · 待9:30开盘 · 开盘价已定";
    } else if (_bjMin >= 11*60+30 && _bjMin < 13*60) {
      // [改] 午休判断改用前端_bjMin(11:30-13:00),不读 snap.label(10min粒度滞后)
      //   根治13:00复牌后横幅仍显"午休时段":snap.label 13:05才切,但实际13:00已复牌
      _t = "📊 午休时段 · 13:00复牌后恢复实时 · 收盘后17:50同步最终";
    } else {
      _t = "📊 盘中预估中 · 数据实时更新 · 收盘后17:50同步最终";
    }
    txt.textContent = _t;
  }
}

function fetchIntradaySnapshot() {
  if (_intradaySnapPromise) return _intradaySnapPromise;
  _intradaySnapPromise = (async () => {
    try {
      const snap = await fetchJSON("./data/intraday_snapshot.json");
      if (snap && snap.indices) {
        state.intradaySnapshot = snap;
        // AZ54 P1-6: snap 就绪即更新全局盘中状态横幅(显/隐/午休文案)
        updateMarketStatusBanner(snap);
        // snap 就绪回调启动 overview 自适应轮询(根治 2s 超时竞态, 2026-07-27):
        // 旧版 _initAutoRefresh 用 Promise.race 2s 超时, 弱网/强刷首屏 snap 未就绪 -> 永不启动.
        // 现在 snap 何时就绪何时启动, 无超时卡死.
        // 盘中(is_closed===false)或盘后(is_closed===true)均启动:
        // _overviewRefreshDelay 内 is_closed===true 分支自动切5min低频拉盘后overview更新.
        // _startOverviewRefresh 内部先 _stopOverviewRefresh 再置 active=true, 幂等可重复调.
        if (!_overviewRefreshActive) {
          _startOverviewRefresh();
        }
      }
    } catch (e) { /* 兜底不崩，保持空 */ }
  })();
  return _intradaySnapPromise;
}

// 三色语义角标：绿=最新(数据日期>=基准) / 黄=滞后可接受(未到最晚可得时刻) / 红=异常(过时刻仍未采到) / 灰=停更(>30天)
// srcClass: "t0"(T+0实时源,基准=snapDate,盘中当日/收盘当日=绿) / "t1"(T+1源,基准=ptd,复用_t1Relax放宽)
// srcKey: T+1源的标识(查T1_COLLECT_DEADLINE得最晚可得时刻),T+0源传空
// isIndexSpark: 是否为分时图指数sparkline卡片(.spark-cell内).true时盘中用腾讯1min时间(_intradayDynamicTime),
//   false时(KPI/ETF/板块/指数图表卡等)用后端快照时间 snap.datetime(10min粒度),不跟1min动态(2026-07-30修复)
// 判定规则:
//   - 数据日期 >= 基准 -> 绿(盘中实时⏰/收盘定格📍/T+1已采到最新📅)
//   - 数据日期 < 基准 且 当前时间 < 该源最晚可得时刻 -> 黄(⚠滞后,采集中/源端尚未发布)
//   - 数据日期 < 基准 且 当前时间 >= 最晚可得时刻 -> 红(🚨异常,过点未采到)
// T+0源最晚时刻=收盘后update_all(18:00);T+1源=各源T1_COLLECT_DEADLINE表;周末无update_all,滞后即红
function getCardTimeBadge(dataDate, snap, srcClass, srcKey, isIndexSpark) {
  if (srcClass === undefined) srcClass = "t0";
  if (srcKey === undefined) srcKey = "";
  if (isIndexSpark === undefined) isIndexSpark = false;
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
      // 分时图指数sparkline卡片(isIndexSpark=true)用腾讯实时1min时间(_intradayDynamicTime "HH:MM"),无则回退 snap.datetime;
      // 其他卡片(isIndexSpark=false: KPI/ETF/板块/指数图表卡等)用后端快照时间 snap.datetime(10min粒度),不跟1min动态
      const _useDyn = isIndexSpark && _intradayDynamicTime;
      const _hh = _useDyn ? _intradayDynamicTime.slice(0, 2) : shIdx.datetime.slice(8, 10);
      const _mm = _useDyn ? _intradayDynamicTime.slice(3, 5) : shIdx.datetime.slice(10, 12);
      // [新增] 分时图角标(isIndexSpark)优先用自己1min数据时间判断状态,不读 snap.label(10min粒度滞后)
      //   根治13:00午休结束角标滞后:snap.label 13:05才从"午休"切"盘中",但分时图13:04已拉到午后点
      //   对称根治9:30开盘边界:snap.label 9:35才从"竞价完成"切"盘中",但分时图9:30已拉到开盘点
      if (isIndexSpark && _useDyn) {
        const _dynMin = parseInt(_intradayDynamicTime.slice(0,2))*60 + parseInt(_intradayDynamicTime.slice(3,5));
        if ((_dynMin >= 9*60+30 && _dynMin <= 11*60+30) || (_dynMin >= 13*60 && _dynMin < 15*60)) {
          return `<span class="card-time-badge intraday" data-tip="盘中实时刷新(T+0),约30秒一次">⏰ 盘中·${_hh}:${_mm}</span>`;
        }
      }
      if (snap.label && /午休/.test(snap.label)) {
        return `<span class="card-time-badge lunch" data-tip="午休时段(11:30-13:00),13:00复牌后恢复T+0实时">⏰ 午休·${_hh}:${_mm}</span>`;
      }
      if (snap.label && /集合竞价/.test(snap.label)) {
        return `<span class="card-time-badge intraday" data-tip="集合竞价(9:15-9:25),9:25确定开盘价">⏰ 竞价·${_hh}:${_mm}</span>`;
      }
      if (snap.label && /竞价完成/.test(snap.label)) {
        return `<span class="card-time-badge intraday" data-tip="竞价完成(9:25-9:30),开盘价已定,9:30连续竞价开盘">⏰ 竞价完成·${_hh}:${_mm}</span>`;
      }
      return `<span class="card-time-badge intraday" data-tip="盘中实时刷新(T+0),约30秒一次">⏰ 盘中·${_hh}:${_mm}</span>`;
    }
    if (srcClass === "t1") {
      // T+1数据已追平今日(snapDate)=今天最新,显绿(与T+0收盘同色,数据确为今日已采到);
      // 仍停在前一交易日(ptd,等盘后补全)=灰(T+1待更新),与T+0今天区分(0541e21初衷仅适用"到昨日等明日")
      if (snapDate && dataDate === snapDate) {
        return `<span class="card-time-badge t1-latest" data-tip="T+1数据源已采到今日(${mmdd}),属今天最新(已追平收盘日,非待更新)">📅 T+1·${mmdd}</span>`;
      }
      return `<span class="card-time-badge t1" data-tip="T+1数据源已采到最新可得日期(${mmdd}),属正常(数据最新可得${mmdd},T+1源下一交易日盘后补全,逢周末/节假日顺延)">📅 T+1·${mmdd}</span>`;
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
    // T+1源未到采集时刻显前一交易日属正常设计(非异常/非滞后)，消除"已滞后约X天"误导口径
    // AZ54 P1-3: 角标 text 直接带具体更新时点(醒目,无需hover tooltip才知何时更新)
    //   next_day -> "次日盘后"(两融/QVIX类,源端次日才发当日值)
    //   HH:MM    -> 具体时点(ETF 21:30 / 龙虎榜 19:30 / 期货 21:00 等)
    //   未配置    -> "盘后"(兜底)
    const _dl = T1_COLLECT_DEADLINE[srcKey];
    const _dlShort = _dl === "next_day" ? "次日盘后" : (_dl || "盘后");
    const _dlStr = _dl === "next_day" ? "次日盘后" : (_dl ? `当日${_dl}后` : "盘后");
    const ttl = `T+1数据源${_dlStr}才发布当日值，未到采集时刻显示前一交易日(${mmdd})属正常设计(非异常)，预计${_dlStr}更新`;
    return `<span class="card-time-badge t1-pending" data-tip="${ttl}">⏳ 待${_dlShort}更新·${mmdd}</span>`;
  }
  // t0源 dataDate<baseline(=snapDate今日) 的兜底分支: 按场景拆分消除"等盘中刷新或update_all尚未运行"误导
  if (intraday) {
    // 盘中: t0源应实时(snapDate=今日), dataDate<今日=该数据停更早
    if (ptd && dataDate === ptd) {
      // 9:15-9:30 竞价空窗期(炸板率/封板率等盘中实时指标此时东财池为空,date 停昨日):
      //   非T+1,9:30 开盘后 intraday-snapshot 10min 周期即补当日值,不等盘后17:50
      //   与 L4285-4290 竞价 badge 口径对齐(复用 snap.label)
      if (snap && snap.label && /竞价完成|集合竞价/.test(snap.label)) {
        const ttl = `竞价完成时段数据停昨日(${mmdd}),9:30 开盘后 intraday-snapshot 10min 周期采集更新(非等盘后17:50)`;
        return `<span class="card-time-badge intraday" data-tip="${ttl}">⏰ 待开盘·${mmdd}</span>`;
      }
      // 9:30 后罕见 dataDate 仍 ptd(如采集失败): 保留原 T+1 待盘后更新口径
      const ttl = `T+1性质数据盘中显示前一交易日(${mmdd})属正常，盘后17:50 update_all采集后补全`;
      return `<span class="card-time-badge t1-pending" data-tip="${ttl}">⏳ 待盘后更新·${mmdd}</span>`;
    }
    // dataDate<ptd=真异常(实时源已到今日但该数据停更早)
    const ttl = `数据异常(末日${mmdd})，盘中实时源应已更新到今日，可能采集任务漏跑或数据源停更，请反馈`;
    return `<span class="card-time-badge t1-stale" data-tip="${ttl}">⚠ 滞后·${mmdd}</span>`;
  }
  // 非盘中(盘后): dataDate<baseline=真滞后
  const ttl = `数据滞后(末日 ${mmdd})，盘后update_all(17:50)采集后补全；过18:00仍未到=异常`;
  return `<span class="card-time-badge t1-stale" data-tip="${ttl}">⚠ 滞后·${mmdd}</span>`;
}
// 给卡片右上角追加盘中标注角标（absolute 不占位，pointer-events:none 不挡点击）
// 同时加 has-time-badge 类，CSS 据此给标题预留 padding-right 防角标压文字
// 2026-07-27: badge 元素打 data-badge-date/src/srckey 属性, 供 refreshCardTimeBadges 重绘.
// 2026-07-30: 新增 isIndexSpark 参数(分时图指数sparkline卡片=true),打 data-badge-isdyn="1" 标识,
//   refreshCardTimeBadges 据此判断是否用 _intradayDynamicTime(1min动态) vs snap.datetime(10min粒度).
function addCardTimeBadge(cardEl, dataDate, snap, srcClass, srcKey, isIndexSpark, useOverviewDate) {
  if (!cardEl) return;
  const html = getCardTimeBadge(dataDate, snap, srcClass, srcKey, isIndexSpark);
  if (html) {
    // 用临时 wrapper 解析出 badge 元素, 打上 data-* 参数后 append(避免 insertAdjacentHTML 无法加属性)
    const tmp = document.createElement("div");
    tmp.innerHTML = html;
    const badge = tmp.firstElementChild;
    if (!badge) return;
    badge.setAttribute("data-badge-date", dataDate || "");
    badge.setAttribute("data-badge-src", srcClass || "t0");
    if (srcKey) badge.setAttribute("data-badge-srckey", srcKey);
    if (isIndexSpark) badge.setAttribute("data-badge-isdyn", "1");
    // 2026-07-20 任务1: freezeCard/sigCard 用首屏 r.date 固化, 轮询后需用最新 overview.date 覆盖.
    // 打 data-badge-ovdate="1" 标识, refreshCardTimeBadges 据此用 _ov.date 覆盖 dataDate(不误伤 kpiId/序列卡).
    if (useOverviewDate) badge.setAttribute("data-badge-ovdate", "1");
    cardEl.appendChild(badge);
    cardEl.classList.add("has-time-badge");
  }
}

// AZ89 P1+P2 全球指数实时报价角标(2026-07-31)：读 intraday_snapshot.global_realtime.<indexId>
// 显示 price + chg_pct% + 时间, 涨红/跌绿/平橙(A股配色)。
// 数据缺失(global_realtime 无该 indexId 或 snap 未就绪)不渲染, 不阻塞卡片。
// 仅全球 tab 渲染时调用(renderGlobal), 角标定位右上角第二行(top:30px right:8px)避开 .card-time-badge(右上 top:6px)。
// 欧洲指数(ftse100/dax/cac40) A股盘中可能未开盘, 数据为盘前/昨收, 不做特殊过滤(角标 time 字段可让用户自行判断)。
function _fmtGlobalPrice(p) {
  if (p == null || isNaN(p)) return "--";
  // 大指数(如 nikkei 4万点/SENSEX 8万点)保留整数, 小指数(如 asx200 ~8000)保留2位
  return Math.abs(p) >= 1000 ? Math.round(p).toLocaleString("en-US") : p.toFixed(2);
}
function _fmtGlobalChgPct(cp) {
  if (cp == null || isNaN(cp)) return "--";
  const sign = cp > 0 ? "+" : (cp < 0 ? "" : "");  // 涨加+，跌自带-，平不加
  return `${sign}${cp.toFixed(2)}%`;
}
function addGlobalRealtimeBadge(cardEl, indexId, snap) {
  if (!cardEl || !indexId) return;
  const gr = snap && snap.global_realtime ? snap.global_realtime[indexId] : null;
  if (!gr) return;  // 数据缺失不渲染
  const price = Number(gr.price);
  const cp = Number(gr.chg_pct);
  const tm = gr.time || "";
  const hhmm = tm.length >= 5 ? tm.slice(0, 5) : tm;
  const cls = isNaN(cp) ? "flat" : (cp > 0 ? "up" : (cp < 0 ? "down" : "flat"));
  // data-tip 悬停显示完整信息(name/datetime/pre_close/OHLC)
  // 2026-07-20 修复2: 首行加"盘中实时价(标题为最近收盘价)"说明标题收盘价 T+1 与角标实时价 T+0 不同源
  const tipParts = ["盘中实时价(标题为最近收盘价)"];
  if (gr.name) tipParts.push(gr.name);
  if (gr.date) tipParts.push(gr.date + (tm ? " " + tm : ""));
  if (gr.pre_close != null) tipParts.push("昨收 " + gr.pre_close);
  if (gr.open != null) tipParts.push("今开 " + gr.open);
  if (gr.high != null) tipParts.push("高 " + gr.high);
  if (gr.low != null) tipParts.push("低 " + gr.low);
  const tip = tipParts.join(" · ");
  const tmp = document.createElement("div");
  // 2026-07-20 修复2: 角标内容前加"实"前缀, 与标题收盘价后"收"小标签成对呼应
  tmp.innerHTML = `<span class="card-realtime-badge ${cls}" data-tip="${tip.replace(/"/g, "&quot;")}">实 ${_fmtGlobalPrice(price)} <b>${_fmtGlobalChgPct(cp)}</b>${hhmm ? " · " + hhmm : ""}</span>`;
  const badge = tmp.firstElementChild;
  if (!badge) return;
  badge.setAttribute("data-badge-gid", indexId);
  cardEl.appendChild(badge);
  cardEl.classList.add("has-realtime-badge");
}

// overview 轮询拉到新 snap 后, 重绘 addGlobalRealtimeBadge 添加的角标(同 refreshCardTimeBadges 模式)。
// 遍历 .card-realtime-badge[data-badge-gid], 用存的 indexId + 新 snap 重算 HTML 并替换。
function refreshGlobalRealtimeBadges(snap) {
  const _snap = snap || state.intradaySnapshot;
  if (!_snap || !_snap.global_realtime) return;
  document.querySelectorAll(".card-realtime-badge[data-badge-gid]").forEach((badge) => {
    const gid = badge.getAttribute("data-badge-gid");
    if (!gid) return;
    const cardEl = badge.parentElement;
    if (!cardEl) return;
    const gr = _snap.global_realtime[gid];
    if (!gr) {
      // snap 轮询后该指数采集失败, 隐藏角标(不删 DOM 避免后续 snap 恢复时无法重绘)
      badge.style.display = "none";
      return;
    }
    badge.style.display = "";
    const price = Number(gr.price);
    const cp = Number(gr.chg_pct);
    const tm = gr.time || "";
    const hhmm = tm.length >= 5 ? tm.slice(0, 5) : tm;
    const cls = isNaN(cp) ? "flat" : (cp > 0 ? "up" : (cp < 0 ? "down" : "flat"));
    const tipParts = ["盘中实时价(标题为最近收盘价)"];
    if (gr.name) tipParts.push(gr.name);
    if (gr.date) tipParts.push(gr.date + (tm ? " " + tm : ""));
    if (gr.pre_close != null) tipParts.push("昨收 " + gr.pre_close);
    if (gr.open != null) tipParts.push("今开 " + gr.open);
    if (gr.high != null) tipParts.push("高 " + gr.high);
    if (gr.low != null) tipParts.push("低 " + gr.low);
    const tip = tipParts.join(" · ").replace(/"/g, "&quot;");
    badge.setAttribute("class", `card-realtime-badge ${cls}`);
    badge.setAttribute("data-tip", tip);
    badge.innerHTML = `实 ${_fmtGlobalPrice(price)} <b>${_fmtGlobalChgPct(cp)}</b>${hhmm ? " · " + hhmm : ""}`;
  });
}

// overview 轮询拉到新 snap 后, 重绘所有 addCardTimeBadge 添加的角标(根治 Bug2: 轮询不重绘卡片角标).
// 遍历 .card-time-badge[data-badge-date], 用存的 (dataDate, srcClass, srcKey, isIndexSpark) + 新 snap 重算 HTML 并替换.
// 安全性: T+1 角标走 getCardTimeBadge t1 分支, 永远返回 📅/⏳/🚨 + 自身 dataDate 的 mmdd(非 snap 实时时间),
// 不会被误刷成实时时间; 只有 t0+intraday 角标会显 ⏰ 盘中·HH:MM(随 snap.datetime 变化, 正是要更新的).
// 2026-07-30: 仅 data-badge-isdyn="1" 的角标(分时图指数sparkline卡片)用 _intradayDynamicTime(1min动态),
//   其他角标(KPI/ETF/板块/指数图表卡等)用 snap.datetime(10min粒度),不跟1min动态.
// 非 addCardTimeBadge 添加的 badge(如 L5184 🚨异常/L6734 半年报/L7113 期货报价时间)无 data-badge-date, 不被动.
function refreshCardTimeBadges(snap) {
  const _snap = snap || state.intradaySnapshot;
  // 2026-07-31 修复: 从最新 overview.today.metrics 建 id->date 映射,
  // 让 KPI 卡角标(炸板率/封板率等)用最新 date 重算, 而非读旧 data-badge-date.
  // _doOverviewRefresh L5492 已 _setCachedOverview(r) 更新缓存, 此处 _getCachedOverview() 拿到最新.
  // 根治 9:35 后 overview 拉到新 date=7-31 但角标仍用旧 date=7-30 走 L4339 显"待盘后更新·07-30"的 bug.
  const _ov = _getCachedOverview();
  const _metricDateMap = {};
  if (_ov && _ov.today && Array.isArray(_ov.today.metrics)) {
    for (const m of _ov.today.metrics) {
      if (m && m.id && m.date) _metricDateMap[m.id] = m.date;
    }
  }
  document.querySelectorAll(".card-time-badge[data-badge-date]").forEach((badge) => {
    let dataDate = badge.getAttribute("data-badge-date") || "";
    const srcClass = badge.getAttribute("data-badge-src") || "t0";
    const srcKey = badge.getAttribute("data-badge-srckey") || "";
    const isIndexSpark = badge.getAttribute("data-badge-isdyn") === "1";
    const kpiId = badge.getAttribute("data-badge-kpiid") || "";
    // 2026-07-20 任务1: freezeCard/sigCard 角标用首屏 r.date 固化, 轮询拉到新 overview 后需覆盖.
    // 打了 data-badge-ovdate="1" 的角标, 用最新 overview.date 覆盖 dataDate(不误伤 kpiId 卡/6月序列卡).
    const ovdate = badge.getAttribute("data-badge-ovdate") === "1";
    // KPI 卡: 用最新 overview 的 metric date 覆盖旧 dataDate (若 overview 已采到新 date)
    if (kpiId && _metricDateMap[kpiId]) {
      dataDate = _metricDateMap[kpiId];
    }
    // overview date 覆盖(freezeCard/sigCard: 首屏 r.date -> 最新 overview.date, 9:35 后角标不再卡"待盘后更新·旧日期")
    if (ovdate && _ov && _ov.date) {
      dataDate = _ov.date;
    }
    const newHTML = getCardTimeBadge(dataDate, _snap, srcClass, srcKey, isIndexSpark);
    if (!newHTML) return;
    const tmp = document.createElement("div");
    tmp.innerHTML = newHTML;
    const newBadge = tmp.firstElementChild;
    if (!newBadge) return;
    // 保留 data-* 供下一轮重绘
    newBadge.setAttribute("data-badge-date", dataDate);
    newBadge.setAttribute("data-badge-src", srcClass);
    if (srcKey) newBadge.setAttribute("data-badge-srckey", srcKey);
    if (isIndexSpark) newBadge.setAttribute("data-badge-isdyn", "1");
    if (kpiId) newBadge.setAttribute("data-badge-kpiid", kpiId);
    if (ovdate) newBadge.setAttribute("data-badge-ovdate", "1");
    badge.replaceWith(newBadge);
  });
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
  etf_date:      "21:30",   // ETF汪汪队份额: 交易所盘后发布,etf-national-team 20:07+21:30(兜底)采集
  // 2026-07-29 T+1治理: gold(沪金AU0)采集侧改新浪/腾讯实时源变T+0,不再列入T+1截止时点表(原 gold: "18:00" 已移除)
  // cn10y 保持T+1(中债估值源端T+1,采集侧67acb836确认),恢复 cn10y: "18:00" 项; us10y/cn_us_spread derived 跟随,共用cn10y srcKey
  cn10y:         "18:00",   // 国债收益率: 中债估值盘后T+1发布,update_all 17:50采集
  a_qvix_300:    "next_day", // QVIX期权波动率: 源端optbbs T+1日02:00-16:30才发当日值,17:50 update_all常采不到 -> next_day盘中恒放宽,消除18:00后误报红
  industry:      "18:00",   // 申万行业指数: baostock/申万收盘后发布,update_all 17:50采集
  hk_south:      "18:00",   // 港股通净买入: 盘后发布,update_all 17:50采集
  a_fund_main:       "18:00", // 主力净流入: 东财盘后发布,update_all 17:50采集(2026-07-23补配,原漏配走t0误判滞后)
  // 换手率5项: BaoStock stock_daily T+1,update_all 17:50采集,18:00后应已到
  a_turnover_mean:    "18:00",
  a_turnover_median:  "18:00",
  a_turnover_p90:     "18:00",
  a_turnover_p10:     "18:00",
  a_turnover_gt5_pct: "18:00",
  // 2026-07-31 德法角标修复: 欧洲指数(dax/cac40/ftse100)本质 T+1(欧洲盘收盘北京23:30, OHLC次日采)
  // 走 t1 分类, srcKey=eu_global, 最晚可得时刻=02:00(次日 index_backfill 02:00 回填兜底采前日欧洲收盘)
  // 过 02:00 仍未采到 ptd 数据 -> 红(真异常); 未到 02:00 -> 黄(T+1待更新,等backfill)
  eu_global:     "02:00",   // 欧洲指数(DAX/CAC40/FTSE100): 欧洲盘23:30收盘,次日02:00 backfill采集
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
// srcKey: T+1源标识(查T1_COLLECT_DEADLINE得最晚可得时刻)；T+0源传空""走滞后口径。
// 与 getCardTimeBadge 三档分级同口径：
//   - T+1源 dateStr<baseline: 过最晚可得时刻=_pastCollectDeadline(srcKey)?t1-severe(🚨异常):t1-pending(⏳T+1待更新,非滞后)
//   - T+0源 dateStr<baseline: >15天=t1-severe(🚨异常) 否则=t1-stale(⚠滞后)
// 消除"T+1源过采集时刻仍显⚠滞后"误导(用户原话:如果不是异常哪就不应该提示滞后)
function _dataFreshness(dateStr, ptd, relax, snapDate, srcKey) {
  if (!dateStr) return { cls: "", text: "无数据" };
  const mmdd = dateStr.length === 8 ? `${dateStr.slice(4, 6)}-${dateStr.slice(6, 8)}` : dateStr;
  // 盘中未到采集时点：基准放宽到 ptd-1 交易日(显示前一交易日算正常等待)
  const baseline = (relax && ptd) ? _prevTradingDay(ptd) : ptd;
  if (!baseline || dateStr >= baseline) {
    // T+1已追平今日(snapDate)=今天最新显绿;否则(停在前一交易日)显灰待更新(与 getCardTimeBadge 同口径)
    const cls = (snapDate && dateStr === snapDate) ? "t1-latest" : "t1";
    return { cls, text: `📅 T+1·${mmdd}` };
  }
  // dateStr < baseline：T+1源走 pastDeadline 三档(T+1源盘中/未到时刻显 t1-pending 是正常设计非滞后)
  if (srcKey) {
    if (_pastCollectDeadline(srcKey)) {
      return { cls: "t1-severe", text: `🚨 异常·${mmdd}` };
    }
    return { cls: "t1-pending", text: `⏳ T+1待更新·${mmdd}` };
  }
  // T+0源：dateStr<baseline 即真滞后(⚠)；>15天升级异常(🚨)，保留原口径
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
    const f = _dataFreshness(margin.date, ptd, _t1Relax("a_fund_margin", intraday), shDate, "a_fund_margin");
    sources.push({ name: "两融", cls: f.cls, text: f.text, hint: "两融余额(沪市融资)T+1,上交所盘后发布较晚(实测22:10仍未出当日),当晚23:00单采+凌晨backfill兜底补齐(逢周末顺延到下一交易日)" });
  }
  // 北向资金现用 HKEX 成交总额源每日更新(原净买额 2024-08 停更)。此块为源端停更兜底提示,停≤30天提示用户，>30天长期停更不再提醒。
  // 通用规则：任何源端停更的数据源均按此30天口径（与 isStaleMetric 同源日期差逻辑）。
  const north = findM("a_fund_north");
  if (north && north.date && ptd && north.date.length === 8 && ptd.length === 8) {
    const dN = new Date(+north.date.slice(0, 4), +north.date.slice(4, 6) - 1, +north.date.slice(6, 8));
    const dL = new Date(+ptd.slice(0, 4), +ptd.slice(4, 6) - 1, +ptd.slice(6, 8));
    const stoppedDays = Math.round((dL - dN) / 86400000);
    if (stoppedDays > 0 && stoppedDays <= 30) {
      sources.push({ name: "北向", cls: "t1-stale", text: `⚠ 停更·${mmdd(north.date)}`, hint: "北向资金成交总额(港交所(HKEX)官方源)每日收盘后更新" });
    }
  }
  // 成交额/涨停数（intraday 源 metrics，盘中实时）
  const amt = findM("a_amount");
  if (amt && amt.date) {
    if (intraday) sources.push({ name: "成交/涨停", cls: "intraday", text: "✓ 实时", hint: "成交额/涨停数盘中实时(东财板池),收盘后定格" });
    else { const f = _dataFreshness(amt.date, ptd, undefined, shDate, ""); sources.push({ name: "成交/涨停", cls: f.cls, text: f.text, hint: "成交额/涨停数,收盘后定格" }); }
  }
  // 综合情绪分
  const scores = (r && r.today && r.today.scores) || {};
  const aSent = scores.a_sentiment;
  if (aSent && aSent.date) {
    const f = _dataFreshness(aSent.date, ptd, undefined, shDate, "");
    sources.push({ name: "情绪分", cls: f.cls, text: f.text, hint: "综合情绪分基于各指标计算,随依赖指标更新而更新" });
  }
  // === T+1 补充源：多为盘后次日发布。优先从 today.metrics / indices_sparkline 取最新日期分级；
  //   overview 未暴露的取不到 date 时显示该源预估时点（像追剧有预期），不跳过。
  const spark = (r && r.indices_sparkline) || {};
  const EXTRA = [
    { name: "商品", mid: "gold", hint: "黄金/原油等商品期货T+1,源端(新浪期货)次日盘后发布,15:30收盘后显示昨日属正常,次日盘后更新当日(逢周末顺延到下一交易日)", def: "📅 次日盘后" },
    { name: "国债", mid: "cn10y", hint: "国债收益率T+1,中债/美债盘后次日发布,美债更滞后(常停T-3)(逢周末顺延到下一交易日)", def: "📅 次日盘后" },
    { name: "龙虎榜", mid: "lhb_count", hint: "龙虎榜T+1,东财盘后次日发布,当日18点后更新当日(逢周末顺延到下一交易日)", def: "📅 当日18点后" },
    { name: "期货持仓", mid: null, dateKey: "futures_date", hint: "中金所(CFFEX)期货机构持仓T+1,次日盘后发布,次日20:00后更新当日(逢周末顺延到下一交易日)", def: "📅 次日20点后" },
    { name: "ETF汪汪队", mid: null, dateKey: "etf_date", hint: "ETF份额T+1,上交所/深交所盘后次日发布,实测源端常晚于22:00,当日20:07采集通常只到T-1,次日20:07后补全当日(逢周末顺延到下一交易日)", def: "📅 次日22点+" },
    { name: "中国波指", mid: "a_qvix_300", hint: "中国波指(期权隐含波动率)T+1,源端盘后次日发布(逢周末顺延到下一交易日)", def: "📅 次日盘后" },
    { name: "红利指数", iid: "csi_div", dateKey: "csi_div_date", hint: "红利指数T+1,中证指数公司盘后次日发布(逢周末顺延到下一交易日)", def: "📅 次日盘后" },
    { name: "美股", iid: "us_dji", dateKey: "us_dji_date", hint: "美股指数时区滞后,美东21:30开盘(北京),次日晨才出当日收盘,当前显示T-1属正常(周末顺延到下一交易日)", def: "📅 次日晨(T-1)" },
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
    if (dateStr) { const f = _dataFreshness(dateStr, ptd, relax, shDate, cfg.mid || cfg.dateKey || ""); cls = f.cls; text = f.text; }
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

// ============ 当日分时图（腾讯分时API直拉 + 1分钟动态刷新）============
// CORS 已确认：腾讯分时API access-control-allow-origin:*，前端可直拉。
// 盘中每1分钟刷新分时走势；收盘后默认收起，点按钮按需展开。
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

// 分时图展示的指数（12个：9 A股 + 3 港股，与 spark-grid 一一对应）
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
  { id: "hscei", name: "恒生国企" },
];

const INTRADAY_REFRESH_MS = 1 * 60 * 1000; // 1分钟(匹配腾讯分钟线更新节奏)
const INTRADAY_MAX_FAILS = 6; // 连续失败6次暂停(渐进退避: 1min->2min->4min->8min上限)
const INTRADAY_BACKOFF_CAP_MS = 8 * 60 * 1000; // 退避上限8min

// 分时fetch in-flight去重（同URL并发只发一次，复用Promise）
const _inflightMinute = new Map();
let _intradayFailCount = 0;
let _intradayRefreshTimer = null;
let _intradayLastFetch = 0;
let _intradayActive = false;
let _intradayRenderCtx = null; // { sparkGrid, snap }
let _intradayVisBound = false;

// ============ 盘中动态值统一（阶段2）：腾讯分时数据驱动卡片badge/横幅chips/采集时间 ============
// 盘中所有"实时数值类"展示（分时图/卡片涨跌幅badge/横幅chips）同源，均由腾讯分时数据驱动（1分钟）。
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
      // cache-busting: 腾讯分时API加 _=Date.now() + cache:no-store，绕过浏览器/CDN HTTP缓存拿1min最新
      const _url = url + (url.indexOf('?') >= 0 ? '&' : '?') + '_=' + Date.now();
      const resp = await fetch(_url, { cache: 'no-store' });
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

// 更新 spark-foot 底部（最新价 + 相对昨收涨跌点数），与右上角 pct 同维度
// results[id] 含 preClose（fetchTencentMinute 完整返回）；回退 _intradayDynamicPct[id] 只存 pct+price 无 preClose -> skip 静默保持原值
function _applyDynamicToSparkFoot(results) {
  document.querySelectorAll(".spark-cell").forEach((cell) => {
    const badge = cell.querySelector(".pct-badge[data-spark-id]");
    if (!badge) return;
    const id = badge.getAttribute("data-spark-id");
    const r = (results && results[id]) || _intradayDynamicPct[id];
    if (!r || r.price == null || r.preClose == null) return; // 静默回退：保持原值
    const foot = cell.querySelector(".spark-foot");
    if (!foot) return;
    const chg = r.price - r.preClose;
    const chgUp = chg >= 0;
    const chgColor = chgUp ? "#e6492e" : "#2e8b57";
    const chgText = (chgUp ? "+" : "") + chg.toFixed(2);
    foot.innerHTML = `${r.price.toFixed(2)} <span style="color:${chgColor}">${chgText}</span>`;
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

// 分时图主入口：分时图嵌入 spark-cell 内，三态分段控件(仅日图/仅分时/全展开)控制显隐
// 三态：collapsed(仅日图,只日K) / intraday-only(仅分时,隐藏日K) / expanded(全展开,日K+分时)
function renderIntradaySection(sparkGrid, snap) {
  const isClosed = !snap || snap.is_closed !== false;
  // 默认：盘中=expanded 盘后=collapsed；localStorage intraday-chart-mode 记忆覆盖
  // 兼容旧键 intraday-chart-expanded: "1"->expanded "0"->collapsed
  let mode = null;
  try {
    mode = localStorage.getItem("intraday-chart-mode");
    if (mode === null) {
      const old = localStorage.getItem("intraday-chart-expanded");
      if (old !== null) mode = old === "1" ? "expanded" : "collapsed";
    }
  } catch (e) {}
  if (mode !== "collapsed" && mode !== "intraday-only" && mode !== "expanded") {
    mode = isClosed ? "collapsed" : "expanded";
  }

  // 全局三态分段控件（控制所有 .spark-intraday 显隐 + .spark-cell.hide-daily）
  const seg = document.createElement("div");
  seg.className = "intraday-seg-group";
  const pulseHtml = isClosed ? "" : '<span class="dyn-pulse"><span class="dyn-pulse-dot"></span>1min</span>';
  const segDefs = [
    { key: "collapsed",     label: "仅日图" },
    { key: "intraday-only", label: "仅分时" },
    { key: "expanded",      label: "全展开" + pulseHtml },
  ];
  seg.innerHTML = segDefs.map((s) =>
    `<button type="button" class="intraday-seg${s.key === mode ? " active" : ""}" data-mode="${s.key}">${s.label}</button>`
  ).join("");
  sparkGrid.parentElement.insertBefore(seg, sparkGrid);

  function applyMode(newMode) {
    mode = newMode;
    seg.querySelectorAll(".intraday-seg").forEach((b) => {
      b.classList.toggle("active", b.getAttribute("data-mode") === newMode);
    });
    const showIntraday = newMode !== "collapsed";     // 仅分时/全展开 显示分时
    const showDaily    = newMode !== "intraday-only"; // 仅日图/全展开 显示日K
    sparkGrid.querySelectorAll(".spark-intraday[data-intraday-code]").forEach((el) => {
      el.classList.toggle("collapsed", !showIntraday);
      // 显示分时且容器为空才渲染（避免重复渲染）
      if (showIntraday && !el.querySelector("div")) {
        const code = el.getAttribute("data-intraday-code");
        if (code && _INDEX_TO_TENCENT_MINUTE[code]) {
          const preClose = _snapPreClose(snap, code);
          const snapTime = _snapTimeStr(snap);
          _renderIntradayChart(el, code, preClose, snapTime);
        }
      }
    });
    sparkGrid.querySelectorAll(".spark-cell").forEach((cell) => {
      cell.classList.toggle("hide-daily", !showDaily);
    });
    try { localStorage.setItem("intraday-chart-mode", newMode); } catch (e) {}
  }

  seg.querySelectorAll(".intraday-seg").forEach((b) => {
    b.onclick = () => applyMode(b.getAttribute("data-mode"));
  });

  // 初始状态应用（applyMode 内处理分时渲染与 collapsed/hide-daily 类）
  applyMode(mode);

  // 盘中启动1分钟动态刷新（无论何种状态，badge/chips 都需刷新）
  if (!isClosed) {
    _startIntradayRefresh();
    _intradayRenderCtx = { sparkGrid, snap };
    // 立即跑一次：刷新后用腾讯实时价立即更新曲线+底部spark-foot+角标时间，
    // 不等 _scheduleNextRefresh 的1min首次延迟（否则底部+角标卡 renderOverview 旧snap 1min）。
    // _doIntradayRefresh 末尾会 _scheduleNextRefresh 清掉 _startIntradayRefresh 设的1min timer 并重设，不重复调度；
    // _refreshDynamicAll 与 renderOverview L6477 调用共用 fetchTencentMinute in-flight 去重，重复fetch可控。
    _doIntradayRefresh();
  }

  // 连续失败暂停提示（隐藏，3次失败时显示）
  const notice = document.createElement("div");
  notice.className = "intraday-notice";
  notice.textContent = "⚠ 实时拉取连续失败，已暂停刷新。可刷新页面重试。";
  notice.style.display = "none";
  sparkGrid.parentElement.insertBefore(notice, sparkGrid.nextSibling);
}

// 启动1分钟动态刷新（setTimeout递归，避免tab隐藏时堆积）
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
// 渐进退避: 失败时间隔翻倍(1min->2min->4min->8min上限), 成功重置为1min
function _scheduleNextRefresh() {
  if (!_intradayActive) return;
  if (_intradayFailCount >= INTRADAY_MAX_FAILS) return;
  if (_intradayRefreshTimer) clearTimeout(_intradayRefreshTimer);
  // 退避: failCount=0正常1min, 1->2min, 2->4min, 3+->8min上限
  const _delay = Math.min(INTRADAY_REFRESH_MS * Math.pow(2, _intradayFailCount), INTRADAY_BACKOFF_CAP_MS);
  _intradayRefreshTimer = setTimeout(() => {
    _intradayRefreshTimer = null;
    if (!_intradayActive) return;
    if (document.hidden) { _scheduleNextRefresh(); return; } // 页面不可见时跳过
    _doIntradayRefresh();
  }, _delay);
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
    _stopIntradayRefresh(); // 分时图盘后无新数据, 停 intraday
    // 盘后不再 _stopOverviewRefresh: 17:50 update_all + 21:00/02:00 backfill 仍更新 overview.json,
    // 需5min轮询拉最新. _overviewRefreshDelay 内 is_closed===true 自动切5min低频,
    // _startMarketOpenCheck 仍3min/15s检测开盘, 开盘后 snap.is_closed=false 自动切3min盘中逻辑.
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
  _applyDynamicToSparkFoot(dynResult && dynResult.results); // 补更新底部 spark-foot(用腾讯实时价+昨收，与右上角pct同维度，不再卡 renderOverview 旧值)
  if (curSnap) refreshCardTimeBadges(curSnap); // 补更新角标(1min刷新也带动角标，不再卡 snap.datetime 10min粒度)
  if (curSnap) refreshGlobalRealtimeBadges(curSnap); // AZ89 全球指数实时报价角标随 snap 更新
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

// visibilitychange：切回tab立即刷新（方案B: 用户切回说明在看，不论距上次多久）
function _onIntradayVisChange() {
  if (document.hidden || !_intradayActive) return;
  _doIntradayRefresh();
}

// ============ 盘中 overview 自适应轮询(预测后端推完时刻 + 3min兜底) ============
// 独立于1min分时轮询(_startIntradayRefresh): 分时轮询拉腾讯API更新badge/chips/分时图,
// overview轮询拉overview.json更新顶部采集时间badge(_renderCollectTime)+_overviewCache.
// 盘中(is_closed===false)才启动, 收盘自停. visibilitychange切回tab高频窗口内或距上次>3min立即刷新.
// cache-busting: fetchJSON对时效敏感URL(overview匹配_NO_CACHE_URLS)已加?_=Date.now()+cache:no-store,
//   绕过浏览器HTTP缓存 + CF 60s边缘缓存过期后向R2拉新, 无需手动Cmd+Shift+R强刷.
//
// 两态状态机(2026-07-27): 低频兜底层(3min) + 自适应高频层(预测窗口内15s). 追后端推完那一刻而非固定周期,
// 盘中数据滞后从最坏5min降到<15s. 后端周期15min但每轮采集耗时1.5-2min波动, 5min固定轮询追"周期"非"推完",
// 最坏滞后近5min. 自适应层用历史collected_at序列中位数预测下一次推完时刻, 提前30s切高频狂拉, 拉到新即转低频.
// 兜底保证: 任何情况两次轮询间隔<=3min, 自适应层失效(预测偏差/后端延迟/周期异常)不卡死.
const OVERVIEW_REFRESH_MS = 3 * 60 * 1000;        // 低频兜底3min(原5min,缩短保证最坏滞后3min)
const AFTER_HOURS_REFRESH_MS = 5 * 60 * 1000;     // 盘后/收盘(is_closed===true)5min低频轮询: 拉17:50 update_all + 21:00/02:00 backfill 等overview更新
const OVERVIEW_HIGH_FREQ_MS = 15 * 1000;           // 高频15s: 预测窗口内追后端推完
const OVERVIEW_PREDICT_LEAD_MS = 30 * 1000;        // 高频窗口提前量: 预测推完前30s开始
const OVERVIEW_PREDICT_TAIL_MS = 3 * 60 * 1000;    // 高频窗口尾部: 预测推完后3min(覆盖后端耗时波动/延迟)
const OVERVIEW_HISTORY_MAX = 8;                     // 历史collected_at保留个数(中位数预测用)
const OVERVIEW_PERIOD_MIN_MS = 5 * 60 * 1000;       // 周期异常下限(防数据污染): <5min不预测
const OVERVIEW_PERIOD_MAX_MS = 30 * 60 * 1000;      // 周期异常上限: >30min视为跨天/中断,清空历史重攒
// 关键时点1m刷新: intraday_snapshot launchd时点(9:25-15:35每10min共27个)±2min窗口内,
// overview低频兜底从3min缩短到1min, 让盘中关键时点(每次快照推完)后<1min即拉到新数据.
// 非关键时点保持3min低频(兜底铁律: delay<=3min, 关键时点更短).
const _INTRADAY_SNAPSHOT_TIMES = [
  9*60+15,
  9*60+25, 9*60+35, 9*60+45, 9*60+55,
  10*60+5, 10*60+15, 10*60+25, 10*60+35, 10*60+45, 10*60+55,
  11*60+5, 11*60+15, 11*60+25,
  13*60+5, 13*60+15, 13*60+25, 13*60+35, 13*60+45, 13*60+55,
  14*60+5, 14*60+15, 14*60+25, 14*60+35, 14*60+45, 14*60+55,
  15*60+5, 15*60+35
];
// 当前北京时间是否在 intraday_snapshot 时点 ±2min 窗口内(关键刷新时刻)
// 2026-07-20: 开盘关键期 9:15-9:35 全程 60s(独立判断,不依赖±2min窗口),
//   解决 9:25 intraday首采后 9:27 窗口就关, 9:28-9:34 走 3min 低频错过 9:25 数据要等 3min 的问题.
function _isKeyRefreshMoment() {
  const bjMin = _bjTimeMin();
  // 9:15-9:35 开盘关键期全程 60s(竞价+首采+连续竞价开盘,数据切换密集)
  if (bjMin >= 9*60+15 && bjMin <= 9*60+35) return true;
  for (const t of _INTRADAY_SNAPSHOT_TIMES) {
    if (Math.abs(bjMin - t) <= 2) return true;
  }
  return false;
}
// overview低频兜底delay: 盘后5min / 关键时点1min / 非关键3min(<=3min兜底铁律, 盘后5min例外因数据更新慢)
function _overviewRefreshDelay() {
  // 盘后/收盘(is_closed===true): 5min低频, 拉17:50 update_all + 21:00/02:00 backfill 等overview更新
  const snap = state.intradaySnapshot;
  if (snap && snap.is_closed === true) return AFTER_HOURS_REFRESH_MS;
  return _isKeyRefreshMoment() ? 60 * 1000 : OVERVIEW_REFRESH_MS;
}
let _overviewRefreshTimer = null;
let _overviewLastFetch = 0;
let _overviewRefreshActive = false;
let _overviewVisBound = false;
let _overviewCollectHistory = [];   // collected_at 时间戳序列(单调递增去重, 保留最近8个)
let _overviewHighFreqStart = 0;     // 预测高频窗口起点(ms), 0=无预测走低频
let _overviewHighFreqEnd = 0;       // 预测高频窗口终点(ms)
let _overviewNextFireAt = 0;        // 下次轮询触发时间戳(ms), debug倒计时用
let _lastVisibleAt = Date.now();    // 上次页面可见时间戳, visibilitychange gap计算用
let _inOverviewRefresh = false;     // _doOverviewRefresh 幂等锁, 防visibilitychange+定时器并发重复触发
let _refreshDebugEl = null;         // debug状态条DOM引用
let _refreshDebugTimer = null;      // debug状态条1秒更新定时器
let _marketOpenCheckTimer = null;   // 收盘态周期检测开盘定时器(盘前/收盘后自动启动轮询用)
let _marketOpenCheckActive = false; // _startMarketOpenCheck 是否已启动(页面全程true, 供visibilitychange监听判活)
let _marketOpenCheckNextFireAt = 0; // 下次开盘检测timer fire的预估时刻(ms), 用于debug bar盘前显示倒计时
let _checkMarketOpenNow = null;     // 暴露_startMarketOpenCheck内tick, 供_onOverviewVisChange切回前台立即补偿调用
let _preOpenPrecisionTimer925 = null; // 9:25竞价完成精确触发定时器(到点立即tick, 消除15s tick周期延迟)
let _preOpenPrecisionTimer930 = null; // 9:30开盘精确触发定时器(到点立即tick, 消除15s tick周期延迟)
let _preOpenPrecisionNextAt = 0;      // 下次精确触发预估时刻(ms), debug bar盘前显示精确触发时点/倒计时

// 解析 overview.json 的 collected_at("20260727 13:05:05") 为 ms 时间戳; 兜底尝试 ISO 等标准格式
function _parseCollectAt(s) {
  if (!s) return NaN;
  const m = /^(\d{4})(\d{2})(\d{2})\s+(\d{2}):(\d{2}):(\d{2})/.exec(String(s));
  if (m) return new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6]).getTime();
  const t = Date.parse(s);
  return isNaN(t) ? NaN : t;
}

// 用历史collected_at序列预测下一次推完时刻, 设置高频窗口[start,end].
// 中位数周期 P, 预测推完 = 最近collected_at + P, 窗口 = [推完-30s, 推完+3min].
// 周期异常(<5min或>30min)/窗口已过(后端延迟很久) -> 清空高频窗口走低频兜底.
function _recomputeOverviewPrediction() {
  const h = _overviewCollectHistory;
  if (h.length < 2) { _overviewHighFreqStart = 0; _overviewHighFreqEnd = 0; return; }
  const gaps = [];
  for (let i = 1; i < h.length; i++) gaps.push(h[i] - h[i - 1]);
  gaps.sort((a, b) => a - b);
  const med = gaps.length % 2
    ? gaps[(gaps.length - 1) >> 1]
    : (gaps[gaps.length / 2 - 1] + gaps[gaps.length / 2]) / 2;
  if (med < OVERVIEW_PERIOD_MIN_MS || med > OVERVIEW_PERIOD_MAX_MS) {
    _overviewHighFreqStart = 0; _overviewHighFreqEnd = 0; return;
  }
  const predicted = h[h.length - 1] + med; // 预测下一次推完时刻(collected_at+周期)
  _overviewHighFreqStart = predicted - OVERVIEW_PREDICT_LEAD_MS;
  _overviewHighFreqEnd = predicted + OVERVIEW_PREDICT_TAIL_MS;
  if (_overviewHighFreqEnd < Date.now()) { // 整个窗口已过(预测太早/后端延迟很久) -> 走低频
    _overviewHighFreqStart = 0; _overviewHighFreqEnd = 0;
  }
}

function _startOverviewRefresh() {
  _stopOverviewRefresh();
  _overviewRefreshActive = true;
  _overviewLastFetch = Date.now();
  _recomputeOverviewPrediction(); // 历史已有(同日重启)则恢复预测, 否则走3min低频攒数据
  _scheduleNextOverviewRefresh();
  _initRefreshDebugBar(); // debug状态条随轮询启动(收盘态不启动也不显示)
  if (!_overviewVisBound) {
    _overviewVisBound = true;
    document.addEventListener("visibilitychange", _onOverviewVisChange);
  }
}

function _stopOverviewRefresh() {
  _overviewRefreshActive = false;
  if (_overviewRefreshTimer) { clearTimeout(_overviewRefreshTimer); _overviewRefreshTimer = null; }
  _overviewNextFireAt = 0;
  _updateRefreshDebug(); // 更新debug状态条为"已停止"
}

// 调度下次轮询: 高频窗口内15s / 窗口起点在3min内等到起点 / 否则3min低频兜底.
// 兜底铁律: delay 最大 = OVERVIEW_REFRESH_MS(3min), 任何情况两次轮询间隔<=3min.
function _scheduleNextOverviewRefresh() {
  if (!_overviewRefreshActive) return;
  if (_overviewRefreshTimer) clearTimeout(_overviewRefreshTimer);
  const now = Date.now();
  let delay;
  if (_overviewHighFreqStart && now >= _overviewHighFreqStart && now < _overviewHighFreqEnd) {
    delay = OVERVIEW_HIGH_FREQ_MS; // 高频窗口内: 15s追后端推完
  } else if (_overviewHighFreqStart && now < _overviewHighFreqStart
             && (_overviewHighFreqStart - now) <= OVERVIEW_REFRESH_MS) {
    delay = _overviewHighFreqStart - now; // 窗口起点在3min内: 精确等到起点切高频
  } else {
    delay = _overviewRefreshDelay(); // 低频兜底: 关键时点1min/非关键3min
  }
  _overviewNextFireAt = now + Math.max(1000, delay); // debug倒计时用
  _overviewRefreshTimer = setTimeout(() => {
    _overviewRefreshTimer = null;
    _overviewNextFireAt = 0;
    if (!_overviewRefreshActive) return;
    if (document.hidden) { _scheduleNextOverviewRefresh(); return; } // 页面不可见时跳过
    _doOverviewRefresh();
  }, Math.max(1000, delay));
}

// 执行一轮overview刷新: fetch overview.json + 更新采集时间badge + 重绘卡片角标 + 检查收盘 + 更新预测.
// 拉到新collected_at(>已知最新) = 命中高频, push历史后重算预测自动转低频(下一轮窗口在15min后).
// 高频窗口超时未命中 -> _recomputeOverviewPrediction 发现窗口已过清空 -> 走低频兜底.
async function _doOverviewRefresh() {
  if (_inOverviewRefresh) return; // 幂等锁: visibilitychange+定时器并发时不重复触发
  _inOverviewRefresh = true;
  try {
  _overviewLastFetch = Date.now();
  try {
    const r = await fetchJSON("./data/overview.json");
    if (r) {
      _setCachedOverview(r); // 更新5min TTL缓存(分享图/renderOverview复用)
      applyCollectTime(r.collected_at, r.collect_health); // 更新顶部时效badge
      // 记录 collected_at 历史(单调递增去重), 用于预测下一次推完时刻
      const t = _parseCollectAt(r.collected_at);
      if (!isNaN(t)) {
        const last = _overviewCollectHistory.length
          ? _overviewCollectHistory[_overviewCollectHistory.length - 1] : NaN;
        if (isNaN(last) || t > last) {
          // 跨天/长中断(gap>30min)清空历史重攒, 防混合跨天数据污染中位数预测
          if (!isNaN(last) && (t - last) > OVERVIEW_PERIOD_MAX_MS) _overviewCollectHistory = [];
          _overviewCollectHistory.push(t);
          if (_overviewCollectHistory.length > OVERVIEW_HISTORY_MAX) _overviewCollectHistory.shift();
        }
      }
    }
    // 检查snap是否收盘(复用fetchIntradaySnapshot单例, 2s超时避免阻塞)
    _intradaySnapPromise = null;
    try { await Promise.race([fetchIntradaySnapshot(), new Promise((r) => setTimeout(r, 2000))]); } catch (e) {}
    const snap = state.intradaySnapshot;
    // 重绘卡片角标(snap 更新后, T+0 盘中 HH:MM 变化 / T+1 分级可能变化). 收盘态也会先重绘(盘中->收盘切换).
    if (snap) refreshCardTimeBadges(snap);
    if (snap) refreshGlobalRealtimeBadges(snap); // AZ89 全球指数实时报价角标随 snap 更新
    // P2-新-W: 通知检测钩子（overview 刷新成功后触发自定义事件，通知模块监听）
    try { window.dispatchEvent(new CustomEvent('ts:overview-refreshed', { detail: { snap } })); } catch(_e) {}
    if (snap && snap.is_closed === true) {
      // 盘后/收盘不自停: overview.json 仍有17:50 update_all + 21:00/02:00 backfill 等更新,
      // 走5min低频续拉(延迟由 _overviewRefreshDelay is_closed 分支决定).
      // _startMarketOpenCheck 仍3min/15s检测重新开盘, snap.is_closed=false 自动切3min盘中逻辑.
      _recomputeOverviewPrediction();
      _scheduleNextOverviewRefresh();
      return;
    }
  } catch (e) { /* 静默重试, 不弹错 */ }
  // 命中(新历史)或超时(窗口已过)都重算预测: 命中->用新历史预测下一轮; 超时->清空走低频兜底
  _recomputeOverviewPrediction();
  _scheduleNextOverviewRefresh();
  } finally {
    _inOverviewRefresh = false;
    _updateRefreshDebug();
  }
}

// visibilitychange: 后台标签页setTimeout被浏览器throttle/pause(节能策略),
// _scheduleNextOverviewRefresh的定时器在后台不准时. 回前台3动作补偿:
// ①立即触发_doOverviewRefresh(不等定时器, 补偿后台错过时间拉最新overview)
// ②历史gap>5min清空_overviewCollectHistory(后台太久历史过期预测会偏, 重攒)
// ③_recomputeOverviewPrediction重算预测+_scheduleNextOverviewRefresh重排定时器(废弃后台卡住的timer)
// 幂等: _doOverviewRefresh内_inOverviewRefresh锁防与定时器并发重复触发; 收盘后_overviewRefreshActive=false不触发.
function _onOverviewVisChange() {
  if (document.visibilityState === 'hidden') {
    _lastVisibleAt = Date.now(); // 记录离开时刻, 回来算gap
    return;
  }
  // visible: 回到前台
  if (!_overviewRefreshActive) {
    // 盘前/收盘态未启动自适应轮询: 仍补偿一次开盘检测,
    // 让用户切回前台能立即看到 9:25 竞价完成切换(不等 _startMarketOpenCheck 的 setTimeout 15s/3min)
    _checkMarketOpenNow && _checkMarketOpenNow();
    return;
  }
  const now = Date.now();
  const gap = now - _lastVisibleAt;
  // 后台太久(gap>5min)历史collected_at过期, 中位数预测会偏, 清空重攒
  if (gap > 5 * 60 * 1000) {
    _overviewCollectHistory = [];
    _overviewHighFreqStart = 0;
    _overviewHighFreqEnd = 0;
  }
  _lastVisibleAt = now;
  // 重算预测(后台可能错过窗口, 重算后窗口已过则走低频, 在未来则等)
  _recomputeOverviewPrediction();
  // 立即触发一次(幂等锁防重复, 补偿后台错过时间拉最新overview)
  _doOverviewRefresh();
  // 重排定时器(废弃后台卡住的timer, 按当前时间+预测重新调度)
  _scheduleNextOverviewRefresh();
  _updateRefreshDebug();
}

// ============ debug: 自适应轮询状态条(PC嵌入tab栏右端吸顶, 移动端右下角fixed) ============
// PC端作为 .tabs flex 子元素(margin-left:auto)随 sticky tab 栏吸顶; 移动端 fixed 右下角(保持原逻辑).
// 小字灰色半透明, z-index低不抢主界面. 显示: 倒计时/状态/后端时间/样本数/预测.
// 倒计时基于 _overviewNextFireAt(下次触发时间戳) 每秒算剩余秒数, 独立1s setInterval更新.
// 状态判断: !_overviewRefreshActive=已停止(收盘); 高频窗口内=高频追新; 窗口在未来=等预测窗口; 否则=低频兜底.
function _initRefreshDebugBar() {
  if (_refreshDebugEl) return; // 幂等防重复插入
  const el = document.createElement('div');
  el.id = 'refresh-debug';
  // 定位/皮肤样式由 style.css #refresh-debug 控制(皮肤变量 var(--text-3)+color-mix 跟随15皮肤, 7b179644适配)
  // PC端嵌入 .tabs 栏右端随吸顶; 移动端 append 到 body 由 @media fixed 右下角(保持原逻辑)
  const _dbgContainer = window.matchMedia('(max-width: 768px)').matches
    ? document.body
    : document.querySelector('.tabs');
  _dbgContainer.appendChild(el);
  _refreshDebugEl = el;
  _updateRefreshDebug();
  // 倒计时每秒更新(基于 _overviewNextFireAt 算剩余秒数, 不依赖轮询本身触发)
  if (_refreshDebugTimer) clearInterval(_refreshDebugTimer);
  _refreshDebugTimer = setInterval(_updateRefreshDebug, 1000);
}

// ms时间戳 -> "HH:MM"(本地时区), 用于后端collected_at和预测下推时刻格式化
function _fmtHM(ms) {
  if (!ms || isNaN(ms)) return '--:--';
  const d = new Date(ms);
  return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
}

// 渲染debug状态条内容. 每秒由_refreshDebugTimer调, 也在_start/_stop/_doRefresh/_onVisChange后调.
function _updateRefreshDebug() {
  if (!_refreshDebugEl) return;
  const now = Date.now();
  // 状态判断
  let status;
  if (!_overviewRefreshActive) {
    // 未启动自适应轮询: 区分盘前(9:10-9:35, _startMarketOpenCheck在15s快检测)+真收盘
    const m = _bjTimeMin();
    if (m >= 9*60+10 && m <= 9*60+35) {
      status = '⏱ 开盘检测中'; // 盘前竞价时段, 15s快检测等9:25竞价完成切换
    } else {
      status = '已停止(收盘)';
    }
  } else if (state.intradaySnapshot && state.intradaySnapshot.is_closed === true) {
    status = '盘后5min轮询'; // 收盘态仍轮询: 拉17:50 update_all + 21:00/02:00 backfill 等 overview 更新
  } else if (_overviewHighFreqStart && now >= _overviewHighFreqStart && now < _overviewHighFreqEnd) {
    status = '高频追新';
  } else if (_overviewHighFreqStart && now < _overviewHighFreqStart) {
    status = '等预测窗口';
  } else {
    status = _isKeyRefreshMoment() ? '低频兜底(关键1m)' : '低频兜底';
  }
  // 倒计时(基于 _overviewNextFireAt 算剩余秒数)
  let countdown;
  if (_overviewNextFireAt > now) {
    countdown = Math.ceil((_overviewNextFireAt - now) / 1000) + 's';
  } else if (_overviewRefreshActive) {
    countdown = '0s';
  } else if (_marketOpenCheckNextFireAt > now) {
    // 盘前/收盘态未启动轮询: 显示距下次开盘检测的倒计时(15s快检测或3min)
    countdown = Math.ceil((_marketOpenCheckNextFireAt - now) / 1000) + 's';
  } else {
    countdown = '--';
  }
  // 后端时间: 优先用 overview collected_at 历史末尾;
  // 盘后轮询刚启动 _overviewCollectHistory 还空时, 用 intraday_snapshot.collected_at 兜底
  // (intraday_snapshot 在 _doOverviewRefresh 已 fetch, 盘后 first overview 拉到前用它显示真实后端时间, 不再 --:--)
  let lastCA = _overviewCollectHistory.length
    ? _overviewCollectHistory[_overviewCollectHistory.length - 1] : NaN;
  if (isNaN(lastCA) && state.intradaySnapshot && state.intradaySnapshot.collected_at) {
    lastCA = _parseCollectAt(state.intradaySnapshot.collected_at);
  }
  const backend = isNaN(lastCA) ? '--:--' : _fmtHM(lastCA);
  // 历史样本数
  const samples = _overviewCollectHistory.length + '/' + OVERVIEW_HISTORY_MAX;
  // 预测下推时刻(高频窗口起点+提前量=预测推完时刻)
  let predict = '';
  if (_overviewHighFreqStart) {
    predict = ' 预测:' + _fmtHM(_overviewHighFreqStart + OVERVIEW_PREDICT_LEAD_MS);
  }
  // 精确触发时点(9:25首采/9:30开盘, 盘前显示, 让用户看到精确触发倒计时)
  // 2026-07-20: 改显示 9:25首采/9:30开盘(原取较晚9:30显示, 9:25首采被隐藏误导用户)
  let precision = '';
  if (_preOpenPrecisionNextAt > now) {
    const _bjMin = _bjTimeMin();
    const _before925 = _bjMin < 9*60+25;
    const _before930 = _bjMin < 9*60+30;
    if (_before925 && _before930) {
      precision = ' ⏰精确9:25首采/9:30开盘';
    } else if (_before930) {
      precision = ' ⏰精确9:30开盘';
    } else {
      precision = ' ⏰精确:' + _fmtHM(_preOpenPrecisionNextAt);
    }
  }
  // 常驻只显示倒计时+后端时间(精简); status/samples/predict/precision 移到 hover title 显示
  _refreshDebugEl.textContent = '下次:' + countdown + ' | 后端:' + backend;
  _refreshDebugEl.title = status + ' | 样本:' + samples + predict + precision;
}

const MARKET_OPEN_CHECK_MS = 3 * 60 * 1000;          // 收盘态每3min检测一次市场是否开盘
const MARKET_OPEN_CHECK_PREOPEN_MS = 15 * 1000;       // 盘前竞价时段(9:10-9:35)15s检测(2026-07-20改: 原60s延迟追不上9:25竞价完成/9:30开盘切换, 切回前台visibilitychange补偿+15s快检测双保险)

// 收盘态周期检测市场是否开盘: 重新fetch intraday_snapshot, 若is_closed===false则
// fetchIntradaySnapshot内回调自动触发_startOverviewRefresh(启动轮询+debug状态条).
// 解决: 盘前打开页面(is_closed=true) -> 轮询不启动 -> debug状态条不出现 -> 开盘后无机制自动启动.
// 递归setTimeout(非setInterval): 9:10-9:35盘前竞价时段15s检测, 其他时段3min.
// 幂等: 已有timer则跳过; 盘中_overviewRefreshActive=true时跳过请求但仍重排下次(保留检测收盘后重新开盘能力).
// visibilitychange: 切回前台立即补一次tick(补偿后台setTimeout被throttle, 不等15s/3min).
// 清理: 无_stopMarketOpenCheck(timer生命周期=页面全程); 若需停 clearTimeout(_marketOpenCheckTimer).
function _startMarketOpenCheck() {
  if (_marketOpenCheckTimer) return; // 幂等防重复
  const _preOpenDelay = () => {
    const m = _bjTimeMin();
    return ((m >= 9*60+10 && m <= 9*60+35) || (m >= 13*60 && m <= 13*60+10)) ? MARKET_OPEN_CHECK_PREOPEN_MS : MARKET_OPEN_CHECK_MS;
  };
  const tick = async () => {
    _marketOpenCheckTimer = null; // 当前timer已触发, 清标记允许重排
    // 检测市场是否开盘(切换 is_closed 状态): fetch看是否开盘
    // 盘前(无snap或snap.is_closed===true): 15s/3min快检测, 等9:25竞价完成/9:30开盘切换
    // 盘后(active && is_closed===true): 仍3min检测开盘, 开盘后 snap.is_closed=false 自动切盘中逻辑
    // 盘中(active && !is_closed): 跳过(_doOverviewRefresh 内部已 fetch snap, 不重复)
    const curSnap = state.intradaySnapshot;
    const needCheck = !_overviewRefreshActive || !curSnap || curSnap.is_closed === true;
    if (needCheck) {
      _intradaySnapPromise = null; // 清单例强制重新fetch
      try { await fetchIntradaySnapshot(); } catch (e) {}
      // fetchIntradaySnapshot 回调内: if(!_overviewRefreshActive) _startOverviewRefresh()
      // 盘前/盘后首次启动轮询自动触发, 盘中已active不重启
      _updateRefreshDebug(); // 刷新debug状态条(显示最新状态)
    }
    // 递归调度下一次(盘中也重排: 保留检测收盘后重新开盘的能力)
    const delay = _preOpenDelay();
    _marketOpenCheckNextFireAt = Date.now() + delay; // 记录下次fire预估时刻, debug bar盘前显示倒计时
    _marketOpenCheckTimer = setTimeout(tick, delay);
  };
  _checkMarketOpenNow = tick; // 暴露给 _onOverviewVisChange 切回前台立即补偿调用
  _marketOpenCheckActive = true;
  // 切回前台立即触发一次开盘检测(不等 setTimeout, 补偿后台标签页被throttle/pause).
  // 幂等: tick内先清_marketOpenCheckTimer防与已排timer并发; fetchIntradaySnapshot单例锁防双fetch.
  document.addEventListener('visibilitychange', function() {
    if (!document.hidden && _marketOpenCheckActive) {
      tick(); // 立即检测一次
    }
  });
  const initDelay = _preOpenDelay();
  _marketOpenCheckNextFireAt = Date.now() + initDelay;
  _marketOpenCheckTimer = setTimeout(tick, initDelay);
  _schedulePreOpenPrecisionTriggers(); // 9:25/9:30精确触发(零延迟, 消除15s tick周期间隙)
}

// 9:25竞价完成/9:30开盘精确触发: 到点立即tick检测, 消除15s tick周期延迟.
// 解决: 9:25竞价完成/9:30开盘时点若恰在两个15s tick之间, 最坏需等15s才检测到切换.
// 时区: 与_bjTimeMin同口径 UTC+8; 算今日北京时间9:25/9:30对应的UTC ms(Date.UTC北京日+1:25/1:30).
// 幂等: 先clear旧timer再设新timer; 若当前已过9:30(盘后启动)则不设(判断now<时点).
// 清理: timer生命周期=页面全程(同_marketOpenCheckTimer, 无_stopMarketOpenCheck); 本函数内先clear防重排泄漏.
// 复用_checkMarketOpenNow(=_startMarketOpenCheck内tick): 到点tick立即fetchIntradaySnapshot检测, tick内自动重排下次15s tick.
function _schedulePreOpenPrecisionTriggers() {
  if (_preOpenPrecisionTimer925) { clearTimeout(_preOpenPrecisionTimer925); _preOpenPrecisionTimer925 = null; }
  if (_preOpenPrecisionTimer930) { clearTimeout(_preOpenPrecisionTimer930); _preOpenPrecisionTimer930 = null; }
  _preOpenPrecisionNextAt = 0;
  const now = Date.now();
  // 北京时间Date对象(shift +8h, 取UTC年月日=北京日), 与_bjDayOfWeek同口径
  const d = new Date(now + 8 * 3600000);
  const y = d.getUTCFullYear(), mo = d.getUTCMonth(), da = d.getUTCDate();
  // 北京9:25/9:30 = UTC 1:25/1:30(同日, 北京UTC+8)
  const t925UtcMs = Date.UTC(y, mo, da, 1, 25, 0);
  const t930UtcMs = Date.UTC(y, mo, da, 1, 30, 0);
  let nextAt = 0;
  if (now < t925UtcMs) {
    _preOpenPrecisionTimer925 = setTimeout(() => {
      _preOpenPrecisionTimer925 = null;
      if (typeof _checkMarketOpenNow === 'function') _checkMarketOpenNow();
    }, t925UtcMs - now);
    nextAt = t925UtcMs;  // 9:25 较早, 优先作为"下次精确触发"时点(倒计时显示)
  }
  if (now < t930UtcMs) {
    _preOpenPrecisionTimer930 = setTimeout(() => {
      _preOpenPrecisionTimer930 = null;
      if (typeof _checkMarketOpenNow === 'function') _checkMarketOpenNow();
    }, t930UtcMs - now);
    if (!nextAt) nextAt = t930UtcMs;  // 9:25 已过才用 9:30 作下次时点(取最早 upcoming)
  }
  _preOpenPrecisionNextAt = nextAt;
}

// 页面加载后初始化自动刷新: 等snap就绪判断盘中后启动overview轮询
// 2026-07-27: snap 就绪回调已在 fetchIntradaySnapshot 内启动轮询(根治 2s 超时竞态),
// 此处 await 不带超时(回调保证 snap 就绪即启动), 末尾兜底检查防回调漏触发.
// 2026-07-28: 始终创建debug状态条(收盘态显示"已停止")+启动开盘检测(盘前打开页面开盘后自动启动轮询).
async function _initAutoRefresh() {
  try { await fetchIntradaySnapshot(); } catch (e) {}
  const snap = state.intradaySnapshot;
  if (!_overviewRefreshActive) {
    // 盘中或盘后均启动轮询(内含_initRefreshDebugBar):
    // 盘中(is_closed===false): _overviewRefreshDelay 返回1min(关键时点)/3min(低频)
    // 盘后(is_closed===true): _overviewRefreshDelay 返回5min, 拉17:50 update_all + 21:00/02:00 backfill 等更新
    _startOverviewRefresh();
  }
  // 始终启动开盘检测(幂等): 盘后3min/盘前15s检测开盘, 开盘后 snap.is_closed=false 自动切盘中逻辑
  _startMarketOpenCheck();
}

// ============ 🔔 浏览器通知（P2-新-W 方案A：页面 Notification API）============
// PC 模式下盘中异动/新信号/预警弹 Windows 通知中心（OS 原生渲染）。Web Notifications API
// 全球 94.38% 支持（Chrome22+/Edge14+/Firefox22+），HTTPS 必需（ss.fx8.store 满足）。
// requestPermission 须用户手势触发（首次点 🔔 按钮），granted 后 localStorage 持久化偏好。
// 移动端 UA 跳过（new Notification 报 TypeError）。
// 三层去重：Notification tag（同 tag 只显最新）+ localStorage notified_keys（同事件当日只弹一次）
//           + 时间窗（同类别 60s 内不连弹）。后端 signal_notified/anomaly_notified 已做邮件去重。
const NOTIFY_STORAGE_KEY = 'ts_notify_enabled';      // '1'/'0' 用户偏好
const NOTIFY_DEDUP_KEY = 'ts_notify_dedup';          // {key: ts} 当日已弹+时间窗记录
const NOTIFY_TIME_WINDOW_MS = 60 * 1000;             // 同类别 60s 内不连弹
const NOTIFY_FETCH_INTERVAL_MS = 30 * 1000;          // 通知 JSON 拉取节流（最小 30s 间隔）

// 移动端 UA 检测（移动端 new Notification 报 TypeError，需跳过）
function _isMobileUA() {
  return /Android|iPhone|iPad|iPod|Mobile|Windows Phone/i.test(navigator.userAgent || '');
}

// Safari 检测（桌面 Safari 6+ 支持 Notification，但有 permission 不同步 bug + SW message event showNotification 限制）
function _isSafari() {
  const ua = navigator.userAgent || '';
  return /Safari/i.test(ua) && !/Chrome|Chromium|CriOS|Edge|Edg|FxiOS/i.test(ua);
}

// 用户偏好读写（localStorage 持久化跨会话）
function _loadNotifyPref() {
  try { return localStorage.getItem(NOTIFY_STORAGE_KEY) === '1'; } catch (e) { return false; }
}
function _saveNotifyPref(on) {
  try { localStorage.setItem(NOTIFY_STORAGE_KEY, on ? '1' : '0'); } catch (e) {}
}

// 当前通知权限状态
function _notifyPerm() {
  if (!('Notification' in window)) return 'denied';
  // Safari 已知 bug: Notification.permission 静态属性可能滞后/不同步（站点设置允许但 API 返回 denied）
  // 优先读 sessionStorage 缓存的最近一次 requestPermission Promise 返回值
  if (_isSafari()) {
    try {
      const cached = sessionStorage.getItem('ts_notify_perm_cache');
      if (cached === 'granted' || cached === 'denied') return cached;
    } catch (e) {}
  }
  return Notification.permission;
}

// 请求通知权限（须用户手势触发，首次点 🔔 按钮时调用）
async function requestNotifyPermission() {
  if (!('Notification' in window)) return 'denied';
  if (_isMobileUA()) return 'denied'; // 移动端跳过
  try {
    const p = await Notification.requestPermission();
    // Safari: 缓存 Promise 返回值（静态属性可能不同步）
    if (_isSafari()) {
      try { sessionStorage.setItem('ts_notify_perm_cache', p); } catch (e) {}
    }
    return p;
  } catch (e) { return 'denied'; }
}

// 去重存储读写：{key: timestamp}，key 格式 "YYYY-MM-DD:event_id" 或 "__tw:category"
function _loadNotifyDedup() {
  try {
    const s = localStorage.getItem(NOTIFY_DEDUP_KEY);
    return s ? JSON.parse(s) : {};
  } catch (e) { return {}; }
}
function _saveNotifyDedup(d) {
  try { localStorage.setItem(NOTIFY_DEDUP_KEY, JSON.stringify(d)); } catch (e) {}
}

// 同事件当日是否已弹过（第三层去重：localStorage 已读标记）
function _isNotifyNotified(eventKey) {
  const d = _loadNotifyDedup();
  const today = new Date().toISOString().slice(0, 10);
  return !!d[`${today}:${eventKey}`];
}

// 标记事件已弹 + 清理 7 天前旧记录（避免 localStorage 膨胀）
function _markNotified(eventKey) {
  const d = _loadNotifyDedup();
  const today = new Date().toISOString().slice(0, 10);
  d[`${today}:${eventKey}`] = Date.now();
  const cutoff = Date.now() - 7 * 24 * 60 * 60 * 1000;
  for (const k in d) {
    if (typeof d[k] === 'number' && d[k] < cutoff) delete d[k];
  }
  _saveNotifyDedup(d);
}

// 同类别时间窗检查（第三层去重：60s 内不连弹同类通知）
function _isInNotifyTimeWindow(category) {
  const d = _loadNotifyDedup();
  const last = d[`__tw:${category}`] || 0;
  return (Date.now() - last) < NOTIFY_TIME_WINDOW_MS;
}
function _markNotifyTimeWindow(category) {
  const d = _loadNotifyDedup();
  d[`__tw:${category}`] = Date.now();
  _saveNotifyDedup(d);
}

// 弹通知（优先走 SW showNotification: Mac Chrome 下点击比页面 new Notification 可靠）
// clickAction: { msgType, hash?, payload? } 携带点击后期号 UI 反馈动作
// controller null 时（硬刷后 SW 刚 register 时序问题）等 navigator.serviceWorker.ready 再 postMessage
function showNotification(title, body, tag, clickAction) {
  if (!_loadNotifyPref()) { console.warn('[notify] pref未开启，跳过'); return false; }
  if (_notifyPerm() !== 'granted') { console.warn('[notify] permission非granted，跳过'); return false; }
  if (_isMobileUA()) return false;
  const notifData = clickAction || {};
  // Safari: 不走 SW message event -> showNotification（Apple 限制仅 push event 支持）
  // 桌面 Safari 6+ 支持页面级 new Notification()，直接走此路径
  if (_isSafari()) {
    console.log('[notify] Safari 走页面 new Notification（绕开 SW message event 限制）');
    _fallbackNewNotification(title, body, tag, notifData);
    return true;
  }
  try {
    if (navigator.serviceWorker) {
      // controller 存在: 直接 postMessage
      if (navigator.serviceWorker.controller) {
        navigator.serviceWorker.controller.postMessage({
          type: 'SHOW_NOTIFICATION',
          payload: { title, body, tag, data: notifData }
        });
        console.log('[notify] 走SW postMessage (controller存在)');
        return true;
      }
      // controller null: 等 SW ready 再 postMessage（硬刷后 SW 刚 register 时序问题）
      navigator.serviceWorker.ready.then(reg => {
        // controller null 时用 reg.active.postMessage（active SW 即可收 message，不依赖 controller 接管页面）
        const sw = navigator.serviceWorker.controller || reg.active;
        if (sw) {
          sw.postMessage({
            type: 'SHOW_NOTIFICATION',
            payload: { title, body, tag, data: notifData }
          });
          const via = navigator.serviceWorker.controller ? 'controller' : 'reg.active';
          console.log('[notify] 走SW postMessage (' + via + ')');
        } else {
          // reg.active 也 null（极端情况）: 降级 new Notification
          console.warn('[notify] 无active SW，降级new Notification');
          _fallbackNewNotification(title, body, tag, notifData);
        }
      });
      return true;
    }
    // 无 SW: 降级 new Notification
    console.warn('[notify] 无SW支持，降级new Notification');
    _fallbackNewNotification(title, body, tag, notifData);
    return true;
  } catch (e) {
    console.warn('[notify] showNotification failed:', e);
    return false;
  }
}

// 降级: 页面 new Notification（Win 可用, Mac 点击不可靠但兜底至少通知能弹）
function _fallbackNewNotification(title, body, tag, notifData) {
  const n = new Notification(title, {
    body: body, tag: tag,
    icon: '/favicon.svg', badge: '/favicon.svg',
    requireInteraction: false, data: notifData,
  });
  n.onclick = (e) => {
    try { e.preventDefault(); } catch (_) {}
    window.focus();
    _handleNotifyClick(notifData);
    n.close();
  };
  setTimeout(() => { try { n.close(); } catch (e) {} }, 10000);
}

// 抽取弹测试通知逻辑（试看按钮点击调用，clickAction 用 OPEN_SIGNAL_DETAIL 让用户看到点击滚动效果）
function _doTestNotify() {
  const ok = showNotification('测试通知 🔔',
    '点击此通知测试跳转功能（应聚焦窗口+滚动到信号卡） ' + new Date().toLocaleTimeString(),
    'test-preview-' + Date.now(), { msgType: 'OPEN_SIGNAL_DETAIL' });
  if (!ok) {
    console.warn('[notify] showNotification 返回 false，通知未弹（检查 pref/permission/controller）');
  }
}

// 通知点击 UI 反馈: 聚焦后滚动到目标板块 + 高亮闪烁
function _handleNotifyClick(action) {
  if (!action || !action.msgType) return;
  const scrollOpts = { behavior: 'smooth', block: 'center' };
  const flash = (el) => {
    if (!el) return;
    el.scrollIntoView(scrollOpts);
    el.classList.add('notify-flash');
    setTimeout(() => el.classList.remove('notify-flash'), 2200);
  };
  switch (action.msgType) {
    case 'OPEN_SIGNAL_DETAIL':
      flash(document.querySelector('.sig-card'));
      break;
    case 'OPEN_ANOMALY':
      flash(document.querySelector('.sig-card'));
      break;
    case 'OPEN_ALERT':
    case 'OPEN_FG':
      flash(document.querySelector('.fg-dim-card') || document.querySelector('.sig-card'));
      break;
    case 'OPEN_ZT':
      flash(document.querySelector('.sig-card'));
      break;
    case 'OPEN_POST_CLOSE':
      // 收盘速递通知的 11 个信号是 A股/指数买卖点，应跳信号卡片区让用户看完整列表
      // （而非 openNtDayModal 弹汪汪队 ETF 信号明细 modal，那是 OPEN_ETF_DETAIL 的语义）
      // 与 OPEN_SIGNAL_DETAIL 一致：flash(.sig-card) 滚动+高亮信号卡
      flash(document.querySelector('.sig-card'));
      break;
    case 'OPEN_ETF_DETAIL':
      // ETF 汪汪队信号通知点击：弹当日汪汪队信号明细 modal（依赖首页 _ntRecentDaily 缓存）
      // _ntRecentDaily 未加载（非首页/未渲染）时 fallback flash 汪汪队卡片墙
      if (typeof openNtDayModal === 'function' && typeof _ntRecentDaily !== 'undefined' && _ntRecentDaily) {
        const today = new Date().toISOString().slice(0, 10).replace(/-/g, '');
        openNtDayModal(today);
      } else {
        flash(document.querySelector('.nt-card-wall') || document.querySelector('.sig-card'));
      }
      break;
    case 'TEST':
    default:
      break;
  }
}

// 通知检测：fetch notifications.json + 对比 localStorage 去重 + 弹通知
// 节流 30s（避免 overview 高频轮询 15s 时连查），in-flight 去重防并发
let _lastNotifyFetch = 0;
let _notifyFetchInFlight = false;
async function _checkNotifications() {
  if (!_loadNotifyPref()) return;
  if (_notifyPerm() !== 'granted') return;
  if (_notifyFetchInFlight) return;
  const now = Date.now();
  if (now - _lastNotifyFetch < NOTIFY_FETCH_INTERVAL_MS) return;
  _notifyFetchInFlight = true;
  _lastNotifyFetch = now;
  try {
    const data = await fetchJSON("./data/notifications.json");
    if (!data || !data.date) return;
    _processNotifications(data);
  } catch (e) { /* 静默失败（404/解析错不发通知） */ }
  finally { _notifyFetchInFlight = false; }
}

// 独立轮询定时器（根因③修复：原仅靠 ts:overview-refreshed 事件触发，
// document.hidden 时 overview 轮询被跳过(L5372)致 _checkNotifications 不触发，
// 后台标签页收不到通知。独立 setInterval 不受 document.hidden 影响，后台也能弹通知。
// _checkNotifications 内部有 pref/permission/30s 节流三层短路，关闭时 return 不发请求。）
let _notifyCheckTimer = null;
function _startNotifyPolling() {
  if (_notifyCheckTimer) return;  // 防重复启动（initNotifyButton 可能多次调用）
  _notifyCheckTimer = setInterval(_checkNotifications, NOTIFY_FETCH_INTERVAL_MS);
  console.log('[notify] 独立轮询已启动 (每' + NOTIFY_FETCH_INTERVAL_MS / 1000 + 's)');
}
function _stopNotifyPolling() {
  if (_notifyCheckTimer) {
    clearInterval(_notifyCheckTimer);
    _notifyCheckTimer = null;
    console.log('[notify] 独立轮询已停止');
  }
}

// 处理 notifications.json：6 类触发场景 + 三层去重
function _processNotifications(data) {
  const today = data.date;

  // 1+2. 新买入/卖出信号（后端已用 signal_notified.json 去重，前端再做当日去重）
  if (data.signals && data.signals.length) {
    const newBuys = data.signals.filter(s =>
      ['buy', 'buy_aux', 'buy_special', 'buy_backup'].includes(s.signal));
    if (newBuys.length && !_isNotifyNotified(`signal_buy_${today}`)
        && !_isInNotifyTimeWindow('signal_buy')) {
      const names = newBuys.slice(0, 3).map(s => s.name || s.index_id).join('、');
      const more = newBuys.length > 3 ? `等${newBuys.length}个` : '';
      if (showNotification('🔴 ' + _t("notify_buy_title"), `${names}${more} ` + _t("notify_buy_body"), `signal_buy_${today}`, { msgType: 'OPEN_SIGNAL_DETAIL' })) {
        _markNotified(`signal_buy_${today}`);
        _markNotifyTimeWindow('signal_buy');
      }
    }
    const newSells = data.signals.filter(s =>
      ['sell', 'sell_stop_loss'].includes(s.signal));
    if (newSells.length && !_isNotifyNotified(`signal_sell_${today}`)
        && !_isInNotifyTimeWindow('signal_sell')) {
      const names = newSells.slice(0, 3).map(s => s.name || s.index_id).join('、');
      const more = newSells.length > 3 ? `等${newSells.length}个` : '';
      if (showNotification('🟢 ' + _t("notify_sell_title"), `${names}${more} ` + _t("notify_sell_body"), `signal_sell_${today}`, { msgType: 'OPEN_SIGNAL_DETAIL' })) {
        _markNotified(`signal_sell_${today}`);
        _markNotifyTimeWindow('signal_sell');
      }
    }
  }

  // 2b. ETF 汪汪队信号（source='etf'，与 A股 buy/sell 分开弹通知）
  // share_surge->etf_buy 进场 / share_outflow->etf_sell 离场 / volume_surge->etf_volume 放量
  // 注意：同一只 ETF 常同时触发 share_surge+volume_surge，volume 去重排除已有 buy/sell 的 etf_code 避免重复
  if (data.signals && data.signals.length) {
    const etfBuys = data.signals.filter(s => s.source === 'etf' && s.signal === 'etf_buy');
    if (etfBuys.length && !_isNotifyNotified(`etf_buy_${today}`)
        && !_isInNotifyTimeWindow('etf_buy')) {
      const names = etfBuys.slice(0, 3).map(s => s.name || s.index_id).join('、');
      const more = etfBuys.length > 3 ? `等${etfBuys.length}个` : '';
      if (showNotification('🐾 ETF进场信号', `${names}${more} 份额激增疑似进场`, `etf_buy_${today}`, { msgType: 'OPEN_ETF_DETAIL' })) {
        _markNotified(`etf_buy_${today}`);
        _markNotifyTimeWindow('etf_buy');
      }
    }
    const etfSells = data.signals.filter(s => s.source === 'etf' && s.signal === 'etf_sell');
    if (etfSells.length && !_isNotifyNotified(`etf_sell_${today}`)
        && !_isInNotifyTimeWindow('etf_sell')) {
      const names = etfSells.slice(0, 3).map(s => s.name || s.index_id).join('、');
      const more = etfSells.length > 3 ? `等${etfSells.length}个` : '';
      if (showNotification('🐾 ETF离场信号', `${names}${more} 份额缩减疑似离场`, `etf_sell_${today}`, { msgType: 'OPEN_ETF_DETAIL' })) {
        _markNotified(`etf_sell_${today}`);
        _markNotifyTimeWindow('etf_sell');
      }
    }
    // 放量信号去重：排除已触发进场/离场的 etf_code（同一只 ETF 同时 share_surge+volume_surge 只弹进场）
    const etfBuySellCodes = new Set([...etfBuys.map(s => s.etf_code), ...etfSells.map(s => s.etf_code)]);
    const etfVolumes = data.signals.filter(s =>
      s.source === 'etf' && s.signal === 'etf_volume' && !etfBuySellCodes.has(s.etf_code));
    if (etfVolumes.length && !_isNotifyNotified(`etf_volume_${today}`)
        && !_isInNotifyTimeWindow('etf_volume')) {
      const names = etfVolumes.slice(0, 3).map(s => s.name || s.index_id).join('、');
      const more = etfVolumes.length > 3 ? `等${etfVolumes.length}个` : '';
      if (showNotification('🐾 ETF放量信号', `${names}${more} 成交额放量`, `etf_volume_${today}`, { msgType: 'OPEN_ETF_DETAIL' })) {
        _markNotified(`etf_volume_${today}`);
        _markNotifyTimeWindow('etf_volume');
      }
    }
  }

  // 3. 盘中异常（只弹 severe 级：rapid_move/breakout_down）
  if (data.anomalies && data.anomalies.length) {
    const severe = data.anomalies.filter(a => a.tier === 'severe');
    if (severe.length && !_isNotifyNotified(`anomaly_${today}`)
        && !_isInNotifyTimeWindow('anomaly')) {
      const desc = severe.slice(0, 2).map(a => a.desc || a.name).join('；');
      const more = severe.length > 2 ? `等${severe.length}项` : '';
      if (showNotification('⚠️ 盘中异动', `${desc}${more}`, `anomaly_${today}`, { msgType: 'OPEN_ANOMALY' })) {
        _markNotified(`anomaly_${today}`);
        _markNotifyTimeWindow('anomaly');
      }
    }
  }

  // 4. 综合预警（high_alert>=72 / low_alert>=85）
  if (data.alerts) {
    if (data.alerts.high && data.alerts.high.triggered
        && !_isNotifyNotified(`alert_high_${today}`)) {
      if (showNotification('🔴 高位预警',
        `${data.alerts.high.level}（分数 ${data.alerts.high.score}）`, `alert_high_${today}`, { msgType: 'OPEN_ALERT' })) {
        _markNotified(`alert_high_${today}`);
      }
    }
    if (data.alerts.low && data.alerts.low.triggered
        && !_isNotifyNotified(`alert_low_${today}`)) {
      if (showNotification('🔵 低位机会',
        `${data.alerts.low.level}（分数 ${data.alerts.low.score}）`, `alert_low_${today}`, { msgType: 'OPEN_ALERT' })) {
        _markNotified(`alert_low_${today}`);
      }
    }
  }

  // 5. 恐贪极值（<20 极度恐惧 / >80 极度贪婪）
  if (data.fear_greed && data.fear_greed.extreme
      && !_isNotifyNotified(`fg_${data.fear_greed.extreme}_${today}`)) {
    const isFear = data.fear_greed.extreme === 'fear';
    if (showNotification(
      isFear ? '😨 恐贪极值：极度恐惧' : '🤑 恐贪极值：极度贪婪',
      `恐贪指数 ${data.fear_greed.value}（${isFear ? '<20' : '>80'}）`,
      `fg_${data.fear_greed.extreme}_${today}`,
      { msgType: 'OPEN_FG' }
    )) {
      _markNotified(`fg_${data.fear_greed.extreme}_${today}`);
    }
  }

  // 6. 涨停潮（a_width_zt_count > 5日均×1.8 且 >=50）
  if (data.limit_up && data.limit_up.spike
      && !_isNotifyNotified(`zt_${today}`) && !_isInNotifyTimeWindow('zt')) {
    if (showNotification('🔥 涨停潮',
      `今日涨停 ${data.limit_up.count} 只（5日均 ${data.limit_up.avg}）`, `zt_${today}`, { msgType: 'OPEN_ZT' })) {
      _markNotified(`zt_${today}`);
      _markNotifyTimeWindow('zt');
    }
  }

  // 7. 盘后速递（post_close=True 且有信号时弹一次）
  if (data.post_close && data.signals && data.signals.length
      && !_isNotifyNotified(`post_close_${today}`)) {
    if (showNotification('📊 收盘速递',
      `今日 ${data.signals.length} 个信号，点击查看详情`, `post_close_${today}`, { msgType: 'OPEN_POST_CLOSE' })) {
      _markNotified(`post_close_${today}`);
    }
  }
}

// 初始化 🔔 通知按钮（PC 显示，移动端隐藏）+ 监听 overview 刷新事件触发通知检测
function initNotifyButton() {
  // 创建按钮并插入到 theme-btn 前
  const btn = document.createElement('button');
  btn.className = 'notify-btn pc-notify-btn';
  btn.type = 'button';
  btn.setAttribute('aria-label', '浏览器通知');
  btn.textContent = '🔔';
  const themeBtn = document.querySelector('.pc-theme-btn');
  if (themeBtn && themeBtn.parentNode) {
    themeBtn.parentNode.insertBefore(btn, themeBtn);
  } else {
    document.querySelector('header')?.appendChild(btn);
  }

  // 方案B: 试看按钮（仅开启+granted 状态显示，点击弹测试通知重测功能）
  // 继承 pc-notify-btn 样式(含 @media 移动端隐藏)，inline 覆盖差异(更小字号+更紧间距)
  const testBtn = document.createElement('button');
  testBtn.className = 'notify-btn pc-notify-btn pc-notify-test-btn';
  testBtn.type = 'button';
  testBtn.setAttribute('aria-label', '试看测试通知');
  testBtn.textContent = '试看';
  testBtn.title = '点击弹一条测试通知，验证浏览器通知功能正常工作';
  testBtn.style.cssText = 'margin-left:4px;padding:5px 10px;font-size:12px;display:none;';
  btn.parentNode?.insertBefore(testBtn, btn.nextSibling);

  // 状态更新（根据偏好+权限切换图标/样式）
  function updateBtnState() {
    const enabled = _loadNotifyPref();
    const perm = _notifyPerm();
    if (perm === 'denied') {
      btn.classList.add('off');
      btn.classList.remove('on');
      btn.title = _isSafari()
        ? 'Safari 通知权限不同步（已知 bug）。请到 Safari > 设置 > 网站 > 通知 移除本站后，完全退出 Safari (Cmd+Q) 重开，再点铃铛授权'
        : '通知被浏览器屏蔽，去浏览器设置恢复权限后重试';
      btn.textContent = '🔕';
    } else if (enabled && perm === 'granted') {
      btn.classList.add('on');
      btn.classList.remove('off');
      btn.title = '浏览器通知已开启（点击关闭，右侧"试看"可重测通知）';
      btn.textContent = '🔔';
    } else {
      btn.classList.remove('on', 'off');
      btn.title = '点击开启浏览器通知（盘中异动/新信号弹 Windows 通知中心）';
      btn.textContent = '🔔';
    }
    // 方案B: 试看按钮只在已开启+granted 状态显示（display:'' 回退 CSS, 移动端 @media 仍隐藏）
    testBtn.style.display = (enabled && perm === 'granted') ? '' : 'none';
  }
  updateBtnState();

  // 点击处理：开启需用户手势触发 requestPermission
  btn.addEventListener('click', async () => {
    const enabled = _loadNotifyPref();
    if (enabled) {
      _saveNotifyPref(false);
      updateBtnState();
      _stopNotifyPolling();  // 关闭时停独立轮询
      return;
    }
    const perm = _notifyPerm();
    if (perm === 'denied') {
      if (_isSafari()) {
        alert('Safari 通知权限被拒或权限状态不同步。\n\n' +
              'Safari 已知 bug：即使站点设置允许，Notification.permission 可能仍为 denied。\n\n' +
              '恢复方法：\n' +
              '1. Safari > 设置 > 网站 > 通知，找到本站点击"移除"\n' +
              '2. 完全退出 Safari（Cmd+Q）后重新打开\n' +
              '3. 重新点击铃铛授权\n\n' +
              '或建议使用 Chrome 获得更稳定的通知体验。');
      } else {
        alert('浏览器通知已被屏蔽，请在浏览器设置（隐私和安全 -> 通知）中恢复权限后重试。');
      }
      return;
    }
    // 方案A: 记录开启前权限状态，仅 default->granted 首次开启才弹欢迎测试通知（避免每次开关都骚扰）
    const wasGranted = (perm === 'granted');
    if (perm !== 'granted') {
      const p = await requestNotifyPermission();
      if (p !== 'granted') { updateBtnState(); return; }
    }
    _saveNotifyPref(true);
    updateBtnState();
    _startNotifyPolling();  // 开启时启独立轮询（后台标签页也能弹通知，根因③修复）
    // 方案A: 首次开启（权限 default->granted）自动弹欢迎测试通知，让用户立即看到效果验证功能正常
    if (!wasGranted) {
      showNotification('通知已开启 ✅',
        '您将收到盘中信号/异常提醒。本条为测试通知，确认通知功能正常工作', 'test-welcome', { msgType: 'TEST' });
    }
    // 立即检测一次（不等下次 overview 刷新）
    _checkNotifications();
  });

  // 方案B: 试看按钮点击 -> 确保pref开启+permission granted -> 弹测试通知（一键开启+测试，不静默return）
  testBtn.addEventListener('click', () => {
    // 自动开启通知偏好（如果未开启）
    if (!_loadNotifyPref()) {
      _saveNotifyPref(true);
      console.log('[notify] 试看自动开启通知偏好');
      updateBtnState();
    }
    // 确保 permission
    if (_notifyPerm() !== 'granted') {
      requestNotifyPermission().then(p => {
        if (p === 'granted') {
          updateBtnState();
          _doTestNotify();
        } else {
          console.warn('[notify] 通知权限被拒绝，请在 Chrome 站点设置授权');
        }
      });
    } else {
      _doTestNotify();
    }
  });

  // 跨标签页同步（storage 事件：另一 tab 开关通知，本 tab 按钮状态同步）
  window.addEventListener('storage', (e) => {
    if (e.key === NOTIFY_STORAGE_KEY) updateBtnState();
  });

  // 监听 overview 刷新事件 -> 触发通知检测（hook _doOverviewRefresh 自定义事件）
  // D 方案(2026-07-29): 同时增量重绘 sigCard(collected_at 变化时), 盘中自动看到最新信号
  window.addEventListener('ts:overview-refreshed', (e) => {
    _checkNotifications();
    _maybeRerenderSigCard(_getCachedOverview(), e && e.detail && e.detail.snap);
  });

  // 根因③修复：启动独立 setInterval 轮询（不依赖 overview 事件，后台标签页也能弹通知）
  // pref 已开启 + permission granted 时启动；否则等用户点击开启时启动
  if (_loadNotifyPref() && _notifyPerm() === 'granted') {
    _startNotifyPolling();
  }

  // 监听 SW notificationclick 转发的 postMessage -> 触发 UI 反馈
  // 防重复注册(initNotifyButton 可能被多次调用): 标志位短路
  if (window._notifySwMsgBound) return;
  window._notifySwMsgBound = true;
  if (navigator.serviceWorker) {
    navigator.serviceWorker.addEventListener('message', (event) => {
      if (!event.data) return;
      const d = event.data;
      if (d.type === 'NOTIFY_CLICK' || d.type === 'OPEN_SIGNAL_DETAIL' ||
          d.type === 'OPEN_ANOMALY' || d.type === 'OPEN_ALERT' ||
          d.type === 'OPEN_FG' || d.type === 'OPEN_ZT' || d.type === 'OPEN_POST_CLOSE') {
        _handleNotifyClick({ msgType: d.type, hash: d.hash, payload: d.payload });
      }
    });
    // controller 接管后提示（硬刷后 SW activate+claim，controller 从 null 变非 null）
    if (!navigator.serviceWorker.controller) {
      navigator.serviceWorker.addEventListener('controllerchange', () => {
        console.log('[notify] SW controller 已接管，通知点击将走 SW notificationclick（Mac 稳定）');
      });
    }
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
// 在首页 purpose-note 之前插入预警条(等级+原因+命中维度TopN),可折叠/关闭,移动端适配。
async function renderAlertBar(host) {
  let a;
  try { a = await fetchJSON("./data/alert.json"); } catch { return; }
  if (!a || !a.date) return;
  const showHigh = a.high && a.high.triggered;
  const showLow = a.low && a.low.triggered;
  if (!showHigh && !showLow) return; // 市场中性时不打扰
  const note = host.querySelector(".purpose-note");
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
  // 预 fetch signal_stats.json 缓存到 state.signalStats（_renderSignalGrid 评分尾缀用）
  // 2026-07-20 修复(a28 bug):改 await + Promise.race 超时,确保首屏 sigCard 渲染前 signalStats 就绪,
  // 否则 _getSignalScore L1004 `if(!state.signalStats) return null` 致首屏无评分(切tab再切回才有)
  if (!state.signalStats) {
    try {
      await Promise.race([
        fetchJSON("./data/signal_stats.json").then((raw) => { state.signalStats = raw; }),
        new Promise((res) => setTimeout(res, 1500))
      ]);
    } catch {}
  }
  // 分享按钮旁显示数据采集时间（来自 collect_log 最新 run_at）+ A4 健康灯（collect_health）
  applyCollectTime(r.collected_at, r.collect_health);
  // 盘中标注：等快照就绪（最多 1.5s），让每张卡片角标判断 714 实时 vs 713 待收盘
  try { await Promise.race([fetchIntradaySnapshot(), new Promise((res) => setTimeout(res, 1500))]); } catch {}
  const snap = state.intradaySnapshot;
  _renderCollectTime(); // snap 就绪后更新采集时间后缀（动态/收盘）
  // 兜底启动 overview 自适应轮询(覆盖切 tab/重渲染场景, 2026-07-27):
  // 首屏 _initAutoRefresh 已由 fetchIntradaySnapshot 内回调启动(盘中+盘后均启动);
  // 此处 !_overviewRefreshActive 防重复启动, 仅在异常漏启动时兜底. 盘后也会走5min低频分支.
  if (!_overviewRefreshActive) {
    _startOverviewRefresh();
  }
  content.innerHTML = "";
  renderPurposeNote(content, PURPOSE_NOTES["overview"]);
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
        const _pulse = '<span class="dyn-pulse" id="banner-pulse"><span class="dyn-pulse-dot"></span>1min</span>';
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
        const _pulse2 = _intraday2 ? '<span class="dyn-pulse" id="banner-pulse"><span class="dyn-pulse-dot"></span>1min</span>' : "";
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
        banner.innerHTML = `<div class="summary-top"><span class="summary-title"><span class="summary-title-text">${titleText}</span></span>${titleTags ? `<span class="summary-title-tags">${titleTags}</span>` : ""}<span class="summary-meta">${snapBadge}<span class="summary-time-label" id="banner-time-label">${_tLabel2}</span>${_pulse2}<button class="summary-history-btn" title="查看历史收盘分析">📜 更多</button></span></div><div id="banner-chips-host">${renderSummaryChips(s, snap)}</div>`;
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
  // 2026-07-29 T+1治理 实施3: C组8项(确实只能T+1,且非首屏必看)挪出首屏KPI小卡区。
  // 这8项已在"A股指标走势图"折叠区(资金面/换手率分布分位数/换手率>5%占比 分组)展示,
  // 数据仍可访问(展开折叠区即可见),不是删除。挪出原因:首屏KPI小卡是散户最先看的速览,
  // T+1性质的次要资金面/换手率分位指标不应占首屏位置,与T+0/today核心宽度+情绪分卡区分。
  // 包含: a_fund_margin(两融) / a_fund_main(主力净流入) / a_fund_north(北向,现HKEX成交总额源每日更新,原净买额2024-08停更)
  //       / a_turnover_mean/median/p90/p10/gt5_pct(换手率5项)
  const _KPI_T1_MOVED = new Set([
    "a_fund_margin", "a_fund_main", "a_fund_north",
    "a_turnover_mean", "a_turnover_median", "a_turnover_p90", "a_turnover_p10", "a_turnover_gt5_pct",
  ]);
  for (const m of r.today.metrics || []) {
    if (_KPI_T1_MOVED.has(m.id)) continue; // C组8项挪出首屏KPI小卡,见上方说明(折叠区/A股走势图区仍可见)
    // 北向资金等源端长期停更兜底逻辑(如原净买额 2024-08 停更;现北向已切 HKEX 成交总额源每日更新,本分支不再触发)：不再隐藏,恢复显示末日值并叠加"数据停更"水印(见 KPI 卡渲染),
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
    if (_KPI_T1_MOVED.has(it.metric_id)) continue; // C组8项已挪出首屏KPI小卡,异常也不在此显示
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
  // B(核心情绪前置): a_sentiment/cross_market/fear_greed 三张情绪分图表排最前
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
    if (k.tag === "冰点" || k.tag === "过热") return true;          // 情绪分极值
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
      || k.id === "cn10y" || k.id === "a_fund_main"
      || k.id === "lhb_count"; // 2026-07-23 修复:这4项实为T+1性质源(盘后次日发布),漏配误走t0分支baseline=今日致盘后误判"滞后",与"数据更新规则"弹窗标T+1不一致
      // 2026-07-24 补配 lhb_count: 龙虎榜T+1(东财18:00发当日,lhb-backfill 18:30+19:30采集),T1_COLLECT_DEADLINE已配19:30但漏配本列表,
      // 致卡片走t0分支判"数据日期<今日=滞后",盘后/盘中误显⚠滞后7-24,与弹窗L3874"📅当日18点后"不一致
      // 2026-07-29 T+1治理: gold(沪金AU0)采集侧改新浪/腾讯实时源变T+0,从_kpiT1移除(走t0分支,无T1角标)
      // 2026-07-29 T+1治理修正: cn10y保持T+1(中债估值源端T+1,采集侧67acb836确认),恢复_kpiT1标记; us10y/cn_us_spread derived跟随T+1
      // 注: a_fund_margin/a_fund_north/a_fund_main/a_turnover_* 即便挪出首屏KPI小卡(C组实施3),仍保留T1标记兜底(灰态卡/未来回KPI用)
    let _badge = k.disabled
      ? `<span class="card-time-badge t1-severe" data-tip="该指标采集异常/数据源中断,恢复后自动显示">🚨 异常</span>`
      : getCardTimeBadge(k.date, snap, _kpiT1 ? "t1" : "t0", _kpiT1 ? k.id : "");
    // 打 data-badge-* 属性, 让 refreshCardTimeBadges 的 .card-time-badge[data-badge-date] 选择器能选到KPI小卡角标并重绘
    // (异常badge🚨不打属性, 避免被重绘成正常badge; 异常状态由后端恢复后重新渲染整卡)
    if (_badge && !k.disabled) {
      const _tmpWrap = document.createElement("div");
      _tmpWrap.innerHTML = _badge;
      const _badgeEl = _tmpWrap.firstElementChild;
      if (_badgeEl) {
        const _badgeSrc = _kpiT1 ? "t1" : "t0";
        _badgeEl.setAttribute("data-badge-date", k.date || "");
        _badgeEl.setAttribute("data-badge-src", _badgeSrc);
        if (_kpiT1 && k.id) _badgeEl.setAttribute("data-badge-srckey", k.id);
        // 2026-07-31 修复: 所有 KPI 卡(含 T+0 炸板率/封板率)打 data-badge-kpiid,
        // 供 refreshCardTimeBadges 从最新 overview.today.metrics 查新 date 更新角标,
        // 根治 9:35 后 overview 拉到新 date 但角标仍读旧 data-badge-date 显"待盘后"的 bug.
        if (k.id) _badgeEl.setAttribute("data-badge-kpiid", k.id);
        _badge = _badgeEl.outerHTML;
      }
    }
    const _kpiTips = {
      a_fund_north: "北向资金=借沪深股通买A股的外资。现展示成交总额(买+卖合计,港交所(HKEX)官方源),反映外资交投活跃度;原净买额2024-08港交所新规后停更。",
      a_fund_margin: "沪市融资余额=借钱买A股的杠杆资金。增加=杠杆做多情绪升。T+1。",
      a_fund_main: "主力净流入=大单资金净买入。正值=主力流入做多。",
      a_amount: "沪深京A股成交额。放量=交投活跃,缩量=清淡。",
      a_volume_ratio: "当日成交额/前5日均量。>1.5倍放量,<0.7倍缩量。",
      fear_greed: "综合5类市场情绪等权算的0-100温度计。≤25极度恐惧、≥75极度贪婪。作逆向参考。",
      a_sentiment: "6项A股指标加权算的0-100情绪分。≤20冰点、≥80过热。",
      cross_market: "A股+港股+全球等多维度等权均值0-100。看跨市场整体冷热。",
      sentiment_sz50: "该指数RSI+涨跌幅等权算的0-100情绪分(等权,非加权)。≤20冰点≥80过热。比A股综合情绪分更聚焦单只指数。",
      sentiment_hs300: "该指数RSI+涨跌幅等权算的0-100情绪分(等权,非加权)。≤20冰点≥80过热。比A股综合情绪分更聚焦单只指数。",
      sentiment_csi500: "该指数RSI+涨跌幅等权算的0-100情绪分(等权,非加权)。≤20冰点≥80过热。比A股综合情绪分更聚焦单只指数。",
      sentiment_csi1000: "该指数RSI+涨跌幅等权算的0-100情绪分(等权,非加权)。≤20冰点≥80过热。比A股综合情绪分更聚焦单只指数。",
      sentiment_cyb: "该指数RSI+涨跌幅等权算的0-100情绪分(等权,非加权)。≤20冰点≥80过热。比A股综合情绪分更聚焦单只指数。",
      sentiment_kc50: "该指数RSI+涨跌幅等权算的0-100情绪分(等权,非加权)。≤20冰点≥80过热。比A股综合情绪分更聚焦单只指数。",
      a_width_zt_count: "收盘仍封死涨停的股票数,多=追涨情绪强。",
      a_width_dt_count: "收盘仍封死跌停的股票数,多=恐慌抛售强。",
      a_width_zhaban_rate: "当日曾涨停但收盘未封住的比例,高=封板资金不稳。",
      gold: "沪金主力合约(AU0)实时价,避险资产,恐慌时常涨。",
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
      high_alert: "A股大盘高位预警(0-100,越高越危险)。8维加权:情绪过热(max恐贪/A股情绪/跨市场)26%+位置偏高(8宽基1年分位均值)20%+风险点密集13%+汪汪队离场(ETF份额缩减)10%+量价背离/动量衰退/均线转弱/全球走弱各7-8%。≥72触发高位红条预警(回测N10下跌占比56.4%),>75警示、>88高危。综合大盘非单一指数,历史统计参考非操作建议。",
      low_alert: "A股大盘低位机会(0-100,越高越接近底)。8维加权:情绪冰点(100-min三情绪)20%+关注点密集18%+位置偏低(100-8宽基分位)15%+汪汪队入场(ETF份额激增)15%+量能异动10%+新低极端/波指飙升/价值显现各7-8%。≥85触发低位蓝条预警(回测N10上涨占比65.7%),>75机会、>88机遇。综合大盘非单一指数,历史统计参考非操作建议。",
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
  await loadEcharts();   // P0-3: sparkline 已改 SVG 不依赖 echarts；此处 await 为后续 lineChart(恐贪/A股情绪分)+盘中分时图(renderIntradaySection)就绪
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
        <span class="spark-name">${_INDEX_NAME_MAP[sparkId] || idx.name}</span>
        <span class="pct-badge" data-spark-id="${sparkId}" style="color:${color}">${sign}${(idx.pct_change || 0).toFixed(2)}%</span>
      </div>
      <div class="spark-chart"></div>
      ${_INDEX_TO_TENCENT_MINUTE[sparkId] ? '<div class="spark-intraday" data-intraday-code="' + sparkId + '"></div>' : ''}
      <div class="spark-foot">${_lastClose.toFixed(2)} <span style="color:${_chgColor}">${_chgText}</span></div>`;
    grid.appendChild(cell);
    const chartDom = cell.querySelector(".spark-chart");
    chartDom.innerHTML = ntIndexSparkline(idx.closes, idx.dates, color, 300, 72);
    addCardTimeBadge(cell, idx.last_date, snap, "t0", "", true); // isIndexSpark=true: 分时图指数sparkline卡片用腾讯1min时间
  }
  _dynamicBadgeIds = _sparkDynIds;

  // ---- 1b. 当日分时图（嵌入 spark-cell，腾讯分时API直拉，盘中1分钟动态刷新）----
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
      // 冰点(≤25)/过热(≥75)阈值虚线（与盘面温测 tab 恐贪图一致）
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
    const asChart = lineChart("A股综合情绪分（近 6 月）" + termTip("综合多项指标算的0-100情绪分，≤20冰点≥80过热") + latestSuffix(as6), as6, {
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
      // 冰点(≤20)/过热(≥80)阈值虚线（情绪分口径，与盘面温测 tab 一致）
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
  addCardTimeBadge(freezeCard, r.date, snap, "t0", "", false, true);  // 任务1: useOverviewDate=true, 轮询后用最新 overview.date 覆盖
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
  sigCard.className = "chart-card sig-card";
  sigCard.innerHTML = _renderSignalGrid(r.signals_today, r.date, "近期技术分析参考点（近 15 交易日 · " + _sigTodayHint() + _sigWindowSuffix() + "）" + signalHelpTip("6色技术信号参考（点击❓查看6色信号详细解释）"), "signal", "近期无技术分析参考点", snap ? snap.is_closed : true);
  addCardTimeBadge(sigCard, r.date, snap, "t0", "", false, true);  // 任务1: useOverviewDate=true, 轮询后用最新 overview.date 覆盖
  _sigCardRenderedAt = r.collected_at;  // D: 记录渲染时 collected_at, 供 _maybeRerenderSigCard 判断是否需重绘
  // B1 方案B(2026-07-27): 盘中提示 - sw_/thsc_/cgb_ 等行业概念指数不在 intraday 反哺列表
  // (_SNAPSHOT_TO_INDEX_ID 只12个),盘中它们的 -all.json 不更新,首页看到的当日 buy/sell pin
  // 点弹窗看不到 T 日 pin(K线末日还是 T-1)。加提示让用户知道收盘后 17:50 全对齐,非 bug。
  // 触发: snap.is_closed===false(盘中) 且 有信号(r.signals_today 非空),收盘后/无信号不显示。
  // 强提醒已挂到具体今日pin上(⚠角标sig-intraday)，底部提示作总览解释⚠含义+兜底。
  if (snap && snap.is_closed === false && Array.isArray(r.signals_today) && r.signals_today.length) {
    const _sigIntradayHint = document.createElement("div");
    _sigIntradayHint.className = "sig-intraday-hint";
    _sigIntradayHint.setAttribute("style", "margin-top:8px;padding:6px 10px;font-size:11px;color:var(--text-3);background:rgba(230,162,60,0.08);border-left:3px solid #e6a23c;border-radius:3px;line-height:1.5;");
    _sigIntradayHint.innerHTML = "⚠ 今日带⚠角标的pin为盘中预估信号，收盘后(17:50)重算定版可能消失或变动；9大指数+3港股已实时更新";
    sigCard.appendChild(_sigIntradayHint);
  }
  // 点击买卖点卡片弹窗：展示对应指数/品类走势图+买卖信号标注
  // A/B 方案(2026-07-29): 汇总条 button click 委托 toggle 评级/对错筛选, 优先于 .sig-clickable 弹窗。
  // E 方案(2026-07-31): 加时间窗口筛选 toggle, 与 grade/correct/type 正交(互不影响)。
  sigCard.addEventListener("click", (e) => {
    const filterBtn = e.target.closest("[data-grade-filter], [data-correct-filter], [data-type-filter], [data-grade-filter-reset], [data-window-filter], [data-window-filter-reset]");
    if (filterBtn) {
      e.preventDefault();
      e.stopPropagation();
      if (filterBtn.hasAttribute("data-grade-filter-reset")) {
        state.sigGradeFilter = null;
        state.sigCorrectFilter = null;
        state.sigTypeFilter = null;
      } else if (filterBtn.hasAttribute("data-window-filter-reset")) {
        state.sigWindowFilter = "0_15";  // 窗口恢复全部(不影响 grade/correct/type)
      } else if (filterBtn.dataset.gradeFilter != null) {
        const g = filterBtn.dataset.gradeFilter;
        state.sigGradeFilter = (state.sigGradeFilter === g) ? null : g;  // toggle: 再点同档恢复
      } else if (filterBtn.dataset.correctFilter != null) {
        const k = filterBtn.dataset.correctFilter;
        state.sigCorrectFilter = (state.sigCorrectFilter === k) ? null : k;  // toggle
      } else if (filterBtn.dataset.typeFilter != null) {
        const t = filterBtn.dataset.typeFilter;
        state.sigTypeFilter = (state.sigTypeFilter === t) ? null : t;  // toggle: 再点同分类恢复
      } else if (filterBtn.dataset.windowFilter != null) {
        const w = filterBtn.dataset.windowFilter;
        state.sigWindowFilter = (state.sigWindowFilter === w) ? "0_15" : w;  // toggle: 再点同窗口恢复
      }
      // 用最新 overview + snap 重绘(不依赖闭包 r/snap, 盘中自动更新后筛选也生效)
      _rerenderSigCardContent(_getCachedOverview(), state.intradaySnapshot);
      return;
    }
    const item = e.target.closest(".sig-clickable");
    if (!item) return;
    e.preventDefault();
    openSignalChartModal(item.dataset.idx, item.dataset.sig, item.dataset.date);
  });
  colA2.appendChild(sigCard);

  // 右列：🐶 汪汪队信号卡片（ETF汪汪队资金动向，近期信号列表+hover pop+点击弹modal，不跳专区）
  const nt = r.nt_signals_today;
  const ntCard = document.createElement("div");
  ntCard.className = "chart-card nt-home-card";
  if (nt && nt.date) {
    // 共振标记：进/出≥2只、量≥3只宽基同日同步异动=汪汪队共振
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
      '<h3>🐶 汪汪队信号 <span class="nt-date-tag">数据 ' + fmtDate(r.etf_date) + ' · 最近信号 ' + fmtDate(nt.date) + '</span>' + resBadge +
      termTip("宽基ETF份额变动跟踪;观察份额增减与成交放量。进=份额增+z>2+放量(红)/出=份额减+z<-2+放量(绿)/量=成交额>5日均2倍(橙)。共振=进/出≥2只、量≥3只宽基同日同步异动。ETF份额T+1发布，数据日期可能为T-1。点击下方信号chip查看当日明细。") + "</h3>" +
      summaryHtml +
      '<div class="signal-grid nt-signal-grid">' + _renderNtSignalList(rc && rc.daily ? rc.daily : [], nt.date) + '</div>';
    addCardTimeBadge(ntCard, r.etf_date, snap, "t1", "etf_date");
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
    if (r && r.etf_date) addCardTimeBadge(ntCard, r.etf_date, snap, "t1", "etf_date");
  }
  colA2.appendChild(ntCard);

  // 公募基金信号卡调用已移至下方合并 ov2ColB 左列 colB1 (5:4 布局 ui120, 2026-07-20 用户方案)

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
    const wc = mkCard("市场宽度（涨跌家数，近 1 月）" + termTip("上涨家数占比反映市场广度，普涨时宽度大") + wSuffix + termTip(_WIDTH_CALIBER_TIP), 182, null, colB1);
    wc.getDom().closest(".chart-card").classList.add("chart-card--no-stretch"); // 图表缩30%后容器配套缩小(ui119)
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
    }, null, colB1, 210);
    if (cmChart) {
      cmChart.getDom().closest(".chart-card").classList.add("chart-card--no-stretch"); // 图表缩30%后容器配套缩小(ui119)
      // 冰点(≤20)/过热(≥80)阈值虚线（情绪分口径，与盘面温测 tab 一致）
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
      colB1.appendChild(posCard);
      addCardTimeBadge(posCard, posDates.length ? posDates[posDates.length - 1] : "", snap, "t0");
    }
  }).catch((e) => { renderFailCard(colB1, "&#x1F4CD; 大盘位置感", e); });

  // ---- 4. AD Line 腾落线 + 成交量对比（合并到 ov2ColB, 5:4 布局 ui120, 2026-07-20 用户方案）----
  // 第2+3个 ov-2col 合并为1个(左5右4), ov2ColC 不再新建, 复用 ov2ColB/colB1/colB2
  const ov2ColC = ov2ColB;  // 合并容器(复用 ov2ColB)
  const colC1 = colB1;      // 复用左列(基金仓位卡稍后 append 为第5位)
  const colC2 = colB2;      // 复用右列

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
      const adc = mkCard("📊 腾落线（AD Line）" + termTip("腾落线=累积每日上涨家数-下跌家数。持续上升=广度健康(多数股票涨),与指数背离常预示拐点。累计值绝对值无意义,看趋势。") + latestSuffixMulti(adSeries), 210, null, colC1);
      adc.getDom().closest(".chart-card").classList.add("chart-card--no-stretch"); // 图表缩30%后容器配套缩小(ui119)
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
      const nhlCard = mkCard("🔬 新高新低家数（52 周）" + termTip("近52周创新高/新低的股票家数，新高多=强势新低多=弱势") + latestSuffixMulti(nhlSeries), 196, null, colC1);
      nhlCard.getDom().closest(".chart-card").classList.add("chart-card--no-stretch"); // 图表缩30%后容器配套缩小(ui119)
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

  // 阶段 J+K: 公募基金信号卡(基金仓位角标 + 4 信号灯 + 4 维资金面共振)
  // 异步渲染, 不阻塞首页主结构(失败降级隐藏, 不影响其他卡; 与 renderPublicFund 不同, 此处只读 summary 一份)
  // 2026-07-20 ui120 用户方案: 从原 colA1(第1个ov-2col左列)移到合并后 ov2ColB 左列 colB1 作第5卡
  // 放在 Promise.allSettled(ADLine/新高新低)之后调用, 确保占位卡 append 为 colB1 第5位(市场宽度->跨市场->ADLine->新高新低->基金仓位)
  // ui121(2026-07-20): 与大盘位置感互换, 基金仓位移到右列 colB2(均线排列->基金仓位->成交额->新高新低明细), 大盘位置感移到左列 colB1
  // 移动端单列顺序: 综合情绪分(第1ov-2col) -> 冰点/买卖点/汪汪队 -> 市场宽度/跨市场/均线/基金仓位/ADLine/成交额/新高新低/明细/位置感
  _renderPublicFundHomeCard(colB2, r, snap);

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
  renderPurposeNote(content, PURPOSE_NOTES["market"]);
  content.insertAdjacentHTML("beforeend", '<div class="tab-crosslink-note">ℹ️ 本页看指数<b>价格走势</b>+' + _t("crosslink_signal") + ';想看市场<b>盘面温测</b>(恐贪指数/冰点过热热力图)-> 去<a data-goto="sentiment" role="button" tabindex="0">【盘面温测】</a></div>');
  _bindTabCrosslink(content, "sentiment");
  // 二级 tab 栏
  const subtabBar = document.createElement("div");
  subtabBar.className = "subtab-bar";
  const subtabs = [
    ["a-stock", "A股"],
    ["industry", "板块分化"],
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
      _setTabHash(state.tab); // 写 #market/{subtab}，F5 刷新恢复二级 tab
      renderMarket(); // 重新渲染大盘 tab
    };
    subtabBar.appendChild(btn);
  });
  content.appendChild(subtabBar);
  // 量大盘二级 tab 栏(A股/港股/全球)实际高度写入 --subtab-h，供指数目录 anchorBar sticky top 叠加用(吸顶在 subtab-bar 下方而非被遮挡)
  document.documentElement.style.setProperty('--subtab-h', (subtabBar.offsetHeight || 46) + 'px');

  // 子内容容器
  const subContent = document.createElement("div");
  subContent.className = "market-sub-content";
  content.appendChild(subContent);
  renderLoadingState(subContent);

  // 根据 subtab 渲染对应内容
  await loadEcharts();   // P0-1: 子 render（renderAStock/renderIndustry 等）用 mkCard+echarts，按需 await（subtab bar+loading 已先行显示）
  if (state.subtab === "a-stock") await renderAStock(subContent);
  else if (state.subtab === "industry") await renderIndustry(subContent);
  else if (state.subtab === "hk") await renderHK(subContent);
  else if (state.subtab === "global") await renderGlobal(subContent);
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
  // 同向准确度趋势（follow_ratio 可跌破50%，反映"同向失效=风格转逆向"）；失败不阻塞期货主渲染
  let accTrend = null;
  try { accTrend = await fetchJSON("./data/futures_acc_trend.json"); } catch {}
  // 规律结论（4条规律+当前触发状态，每日刷新）；失败不阻塞
  let accConclusion = null;
  try { accConclusion = await fetchJSON("./data/futures_acc_conclusion.json"); } catch {}
  try { await Promise.race([fetchIntradaySnapshot(), new Promise((r) => setTimeout(r, 1500))]); } catch {}
  const snap = state.intradaySnapshot;
  container.innerHTML = "";
  renderPurposeNote(container, PURPOSE_NOTES["market.futures"]);
  if (futures && futures.positions && futures.positions.length) {
    renderFuturesSection(futures, snap, container, accTrend, accConclusion);
  } else {
    container.insertAdjacentHTML("beforeend", '<div class="empty-note">暂无期货持仓数据</div>');
  }
}

// ============ 🐶 汪汪队：汪汪队宽基 ETF 资金动向 ============
// 口径：代理推断，非真实汪汪队席位数据。基于 ETF 每日份额变动+成交额放量，结合季度机构持仓占比校准，
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

  // 拉取盘中快照，供汪汪队3图角标判断盘中/收盘状态（1.5s 超时兜底，不阻塞渲染）
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
    `<h3>🐶 汪汪队 - 宽基 ETF 资金动向 <span class="term-tip" data-tip="宽基ETF份额变动跟踪;观察份额增减与成交放量。追踪12只宽基ETF(上证50/沪深300/中证500/1000/创业板/科创50)的份额变动+成交额放量。份额异动标准分(z-score)>2且放量1.5倍以上=份额扩张(红)，反之为份额收缩(绿)。注意：这是份额变动统计，无法确认具体资金来源，份额变动可能来自任何机构/大户申赎。">❓</span></h3>` +
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

// 首页指数 sparkline（近N日收盘价迷你折线）：纯 SVG 不走 ECharts，省 11 个 echarts.init 开销（P0-3）。
// 等价 echarts line+areaStyle+tooltip：polygon 面积填充 + polyline 折线 + 末点 circle + 每点 <title> 原生 hover tooltip。
// preserveAspectRatio="none" + vector-effect="non-scaling-stroke"：横向拉伸填满容器宽度，stroke 保持 1.5px 不变粗。
function ntIndexSparkline(closes, dates, color, w, h) {
  if (!closes || closes.length < 2) return "";
  w = w || 300; h = h || 72;
  var vals = closes.map(function (v) { return Number(v); }).filter(function (v) { return !isNaN(v); });
  if (vals.length < 2) return "";
  var min = Math.min.apply(null, vals), max = Math.max.apply(null, vals);
  var range = max - min || 1;
  var n = closes.length;
  var pad = 2;
  var pts = closes.map(function (v, i) {
    var x = (i / (n - 1)) * w;
    var y = h - pad - ((Number(v) - min) / range) * (h - pad * 2);
    if (isNaN(y)) y = h - pad;
    return [x, y];
  });
  var polyStr = pts.map(function (p) { return p[0].toFixed(1) + "," + p[1].toFixed(1); }).join(" ");
  var lastY = pts[n - 1][1];
  // 面积 polygon：折线点闭合到底部两端
  var areaPts = "0," + h + " " + polyStr + " " + w.toFixed(1) + "," + h;
  // 每点 hover circle（透明，仅触发原生 <title> tooltip）
  var hoverCircles = pts.map(function (p, i) {
    var d = (dates && dates[i]) ? dates[i] : "";
    var raw = closes[i];
    var val = (raw != null && !isNaN(Number(raw))) ? Number(raw).toFixed(2) : "-";
    return '<circle cx="' + p[0].toFixed(1) + '" cy="' + p[1].toFixed(1) + '" r="4" fill="transparent"><title>' + d + " " + val + '</title></circle>';
  }).join("");
  return '<svg class="idx-spark" width="100%" height="' + h + '" viewBox="0 0 ' + w + ' ' + h + '" preserveAspectRatio="none">' +
    '<polygon points="' + areaPts + '" fill="' + color + '" fill-opacity="0.12" stroke="none"/>' +
    '<polyline points="' + polyStr + '" fill="none" stroke="' + color + '" stroke-width="1.5" vector-effect="non-scaling-stroke"/>' +
    '<circle cx="' + w.toFixed(1) + '" cy="' + lastY.toFixed(1) + '" r="2.2" fill="' + color + '"/>' +
    hoverCircles +
    '</svg>';
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

// ── 总盘汇总层：12只ETF合计持仓市值+净增持额+份额趋势（看"汪汪队整体持仓"而非单只）──
function renderNationalTeamTotalPanel(container, data, snap) {
  // 合计层共振信号阈值：≥N只宽基ETF同日同步异动=汪汪队共振
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

  // ▼ T+1 提示行：让用户知道汪汪队份额为何停 T-1 ▼
  var t1Hint = document.createElement("div");
  t1Hint.className = "nt-t1-hint";
  t1Hint.textContent = "⏳ ETF份额数据为T+1：上交所/深交所盘后次日发布,实测源端常晚于22:00,当日20:07采集通常只到T-1,次日20:07后补全当日(逢周末顺延到下一交易日)";
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

  // ▼ 第0层 KPI 大字：汪汪队总市值 + 今日净增持 + 近20日累计净增持 ▼
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
    '<div class="nt-tk-item"><div class="nt-tk-label">汪汪队合计持仓市值' + termTip("12只宽基ETF当日份额×收盘价合计(亿元)。份额是交易所公布的硬数据，市值随价波动。") + '<span class="chart-latest"> · 截至 ' + fmtDate(last.date) + '</span></div>' + mktCapValHtml + '</div>' +
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

  // 合计层信号 markPoint(方案B:所有信号日都显示pin,不按共振阈值过滤)
  // 共振(n≥THR 多只ETF同日同步异动=汪汪队集体行动)=大pin金边特殊样式;
  // 单只(n<THR 单只ETF异动)=小pin单色普通样式。用户看样式+标签判断共振
  // value 含信号只数,不依赖 hover 即可读出强度
  // 同日多类信号合并成1个拼色pin(分段渐变),不再重叠遮挡
  var mktMarks = [], shareMarks = [];
  var NT_SIG_COLORS = { "进": "#e6492e", "出": "#2e8b57", "量": "#ff9800" };
  series.forEach(function (d) {
    var mktY = +d.mktCap.toFixed(2);
    var shareY = +d.share.toFixed(2);
    // 按固定顺序收集当日所有信号:进->出->量(n≥1即收,不按THR过滤)
    var daySigs = [];
    if (d.nSurge >= 1) daySigs.push({ label: "进" + d.nSurge, color: NT_SIG_COLORS["进"], n: d.nSurge, thr: THR.surge });
    if (d.nOutflow >= 1) daySigs.push({ label: "出" + d.nOutflow, color: NT_SIG_COLORS["出"], n: d.nOutflow, thr: THR.outflow });
    if (d.nVolume >= 1) daySigs.push({ label: "量" + d.nVolume, color: NT_SIG_COLORS["量"], n: d.nVolume, thr: THR.volume });
    if (!daySigs.length) return;
    // 共振判断:任一类信号 n≥THR 即共振(多只ETF同日同步异动)
    var isResonance = daySigs.some(function (s) { return s.n >= s.thr; });
    if (isResonance && daySigs.length === 1) {
      // 单类共振:大pin金边单色(size40,金边强调共振特殊样式)
      var sig = daySigs[0];
      var resStyle = { color: sig.color, borderColor: "#ffd700", borderWidth: 2, shadowBlur: 6, shadowColor: "rgba(255,215,0,0.5)" };
      mktMarks.push({ coord: [d.date, mktY], value: sig.label, symbolSize: 40, itemStyle: resStyle, label: { color: _autoLabelColor(sig.color) } });
      shareMarks.push({ coord: [d.date, shareY], value: sig.label, symbolSize: 40, itemStyle: resStyle, label: { color: _autoLabelColor(sig.color) } });
    } else if (isResonance) {
      // 多类共振:拼色金边大pin(size64,原多信号样式)
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
    } else if (daySigs.length === 1) {
      // 单只单类:小pin单色(size28,无金边,弱信号普通样式)
      var sig = daySigs[0];
      mktMarks.push({ coord: [d.date, mktY], value: sig.label, symbolSize: 28, itemStyle: { color: sig.color }, label: { color: _autoLabelColor(sig.color), fontSize: 10 } });
      shareMarks.push({ coord: [d.date, shareY], value: sig.label, symbolSize: 28, itemStyle: { color: sig.color }, label: { color: _autoLabelColor(sig.color), fontSize: 10 } });
    } else {
      // 单只多类:拼色小pin(size36,无金边,弱信号普通样式)
      var valStr = daySigs.map(function (s) { return s.label; }).join("+");
      var segColors = daySigs.map(function (s) { return s.color; });
      var multiStyle = { color: _ntMultiColor(segColors), borderColor: "#666", borderWidth: 1 };
      var lblFmt = valStr.replace(/\+/g, "\n");
      var multiLabel = { fontSize: 10, color: "#fff", formatter: lblFmt, lineHeight: 12 };
      mktMarks.push({ coord: [d.date, mktY], value: valStr, symbolSize: 36, label: multiLabel, itemStyle: multiStyle });
      shareMarks.push({ coord: [d.date, shareY], value: valStr, symbolSize: 36, label: multiLabel, itemStyle: multiStyle });
    }
  });

  // 3图动态1行折叠布局：PC/4K屏1:1:1全展，窄屏(<768px)折叠竖排(复用 .astock-top-grid 响应式CSS)
  var ntGrid = document.createElement("div");
  ntGrid.className = "astock-top-grid";
  container.appendChild(ntGrid);

  // 图1：合计持仓市值趋势（份额×价合计）+ 共振信号 pin 标注
  var c1 = mkCard("📊 汪汪队合计持仓市值趋势" + termTip("Σ(各ETF当日份额×收盘价)。看总额变化趋势，份额增+价涨=市值双击。pin=所有信号日都标注：共振(进/出≥" + THR.surge + "只、量≥" + THR.volume + "只宽基同步异动=汪汪队集体行动)用大金边pin，单只ETF异动用小单色pin。进=红/出=绿/量=橙。") + latestSuffix(mktData) + missingSuffix, 320, null, ntGrid);
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
  var c2 = mkCard("📈 份额合计趋势" + termTip("Σ各ETF当日份额(亿份)。份额持续增=真增持(非价格涨跌)，这是汪汪队操作的硬信号。pin=所有信号日都标注：共振(进/出≥" + THR.surge + "只、量≥" + THR.volume + "只宽基同步异动=汪汪队集体行动)用大金边pin，单只ETF异动用小单色pin。进=红/出=绿/量=橙。") + latestSuffix(shareData) + missingSuffix, 320, null, ntGrid);
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

// 聚合汪汪队全量数据为按日期信号列表（复用 _renderNtSignalList 入参格式），供专区"近期信号按日期"模块。
// 从 rawData（未切片全量）遍历 etfs[].daily[].signals，按日期合并多ETF多信号，
// 每日组装 {date, signals:[{code,name,type,label,share_change_yi,amount_ratio,intensity,note}], n_surge, n_outflow, n_volume, total, is_resonance}。
// is_resonance 口径同首页后端 _NT_THR：进/出≥2只 或 量≥3只宽基同日同步异动。
// maxDays 限制返回最近N个有信号日（默认14），避免专区页面过长。
// signals[] 在 etf_national_team-*.json 中缺 code/name/label，从 etf 层级补；share_change_yi 在 daily 层级有则补到 signal。
function _ntAggregateRecentSignals(rawData, maxDays) {
  if (!rawData || !rawData.etfs || !rawData.etfs.length) return [];
  var dayMap = {};
  rawData.etfs.forEach(function (e) {
    (e.daily || []).forEach(function (d) {
      if (!d.signals || !d.signals.length) return;
      if (!dayMap[d.date]) dayMap[d.date] = { date: d.date, signals: [], n_surge: 0, n_outflow: 0, n_volume: 0 };
      d.signals.forEach(function (sig) {
        var s = Object.assign({}, sig);
        s.code = e.code;
        s.name = e.name || d.etf_name || e.code;
        s.label = NT_LABEL[sig.type] || sig.type;
        if (s.share_change_yi == null && d.share_change_yi != null) s.share_change_yi = d.share_change_yi;
        dayMap[d.date].signals.push(s);
        if (sig.type === "share_surge") dayMap[d.date].n_surge++;
        else if (sig.type === "share_outflow") dayMap[d.date].n_outflow++;
        else if (sig.type === "volume_surge") dayMap[d.date].n_volume++;
      });
    });
  });
  var dates = Object.keys(dayMap).sort();
  if (maxDays && dates.length > maxDays) dates = dates.slice(-maxDays);
  return dates.map(function (dt) {
    var item = dayMap[dt];
    item.total = item.n_surge + item.n_outflow + item.n_volume;
    item.is_resonance = item.n_surge >= 2 || item.n_outflow >= 2 || item.n_volume >= 3;
    return item;
  });
}

// ── 4层概览首屏：总览摘要条+矩阵热力图+卡片墙+叠加对比折线 ──
function renderNationalTeamOverview(container, data, qData, hData, rawData, snap) {
  var summary = ntBuildSummary(data, qData);

  // ▼ 第0层：汪汪队总盘（合计持仓市值+净增持+份额趋势，最顶部在摘要条之上）▼
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

  // ▼ 第1.5层：近期汪汪队信号（按日期）-- 复用首页 _renderNtSignalList，修专区无730等按日期信号pin ▼
  // 从 rawData（未切片全量）聚合，避免被 state.range 切片切掉历史信号（如1m切掉30天前的730信号）
  // 缓存到 _ntRecentDaily 供 openNtDayModal 弹当日明细（切回首页时 renderOverview L7119 会刷新_ntRecentDaily为首页rc.daily，不串扰）
  var recentDaily = _ntAggregateRecentSignals(rawData, 14);
  if (recentDaily.length) {
    _ntRecentDaily = recentDaily;
    var rcTodayDate = recentDaily[recentDaily.length - 1].date;
    var rcTotal = recentDaily.reduce(function (s, d) { return s + d.total; }, 0);
    var rcSurge = recentDaily.reduce(function (s, d) { return s + d.n_surge; }, 0);
    var rcOutflow = recentDaily.reduce(function (s, d) { return s + d.n_outflow; }, 0);
    var rcVolume = recentDaily.reduce(function (s, d) { return s + d.n_volume; }, 0);
    var rcResonanceDays = recentDaily.filter(function (d) { return d.is_resonance; }).length;
    var recentSec = document.createElement("section");
    recentSec.className = "chart-card nt-recent-signals-card";
    recentSec.innerHTML =
      '<h3>📅 近期汪汪队信号（按日期） <span class="term-tip" data-tip="近' + recentDaily.length + '个有信号日的汪汪队信号，按日期降序（今日置顶高亮）。每行=日期+共振🐾+标签（进/出/量 各一个标签，显示当日该类型只数+净流入/净流出/放量倍数）。悬停标签看当日该类型ETF明细，点击弹当日全部信号弹窗。共振=进/出≥2只或量≥3只宽基同日同步异动。">❓</span></h3>' +
      '<div class="nt-recent-summary"><div class="nt-recent-stats">近' + recentDaily.length + '日 共<b>' + rcTotal + '</b>信号 · ' +
        '<span class="nt-c-surge">进<b>' + rcSurge + '</b></span> ' +
        '<span class="nt-c-outflow">出<b>' + rcOutflow + '</b></span> ' +
        '<span class="nt-c-volume">量<b>' + rcVolume + '</b></span> · 共振<b>' + rcResonanceDays + '</b>日</div></div>' +
      '<div class="signal-grid nt-signal-grid">' + _renderNtSignalList(recentDaily, rcTodayDate) + '</div>';
    // chip 点击：弹当日明细 modal（事件委托，复用 openNtDayModal，_ntRecentDaily 已设为聚合后的 recentDaily）
    recentSec.addEventListener("click", function (e) {
      var chip = e.target.closest("[data-nt-date]");
      if (!chip) return;
      e.stopPropagation();
      openNtDayModal(chip.dataset.ntDate);
    });
    container.appendChild(recentSec);
  }

  // ▼ 第2层：矩阵热力图 ▼
  // 12行×指标列，色阶着色：份额变动红流入/绿流出，机构占比高深色，放量倍数>1.5橙色
  // 标注就地 hover pop（data-tip 复用 .term-pop 事件委托）+ 点行弹 iframe 式满屏弹窗（不切页，保留滚动）
  var heatSec = document.createElement("div");
  heatSec.className = "chart-card nt-heatmap-card";
  heatSec.innerHTML = '<h3>12 只 ETF 资金矩阵 <span class="term-tip" data-tip="一屏看全12只：份额变动%(红=流入/绿=流出，色越深变动越大)、最新信号、机构占比%(深色=汪汪队主导>85%)、放量倍数(橙=成交活跃>1.5倍)。点行进单只详情。">❓</span></h3>';
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
      '<td class="nt-cell-num" style="background:' + instColor + '"><span data-tip="当季机构持有占比，>85%为汪汪队主导品种。点击查看详情">' + (inst != null ? inst.toFixed(1) + "%" : "-") + '</span></td>' +
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
    const intTitle = `${cur.code} ${cur.name} 信号强度分布（标准分(z-score)）` +
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
    `<b>季度校准</b>：当季机构占比&gt;85% 置信×1.5（汪汪队主导品种）；&lt;60% 置信×0.7（散户主导噪声大）。持有人数据半年报+年报，滞后2-3月。` +
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
    var v2Html = '<h3>📊 汇金/证金具名持有人 <span class="term-tip" data-tip="数据来自巨潮资讯网(cninfo)年报/半年报PDF的§9.2期末上市基金前十名持有人表格,用pdfplumber(PDF解析库)解析。持有人类型按名称关键词识别:含中央汇金=汇金,含中国证券金融=证金,含全国社保基金=社保。仅深市5只ETF有cninfo机构ID(orgId),沪市7只待补。">❓</span></h3>';
    v2Html += '<div class="nt-banner-body">';
    if (curEtf && curEtf.has_data && curEtf.reports && curEtf.reports.length) {
      var latestRep = curEtf.reports[0];
      var ntSum = latestRep.national_team_summary || {};
      var ntKeys = Object.keys(ntSum);
      v2Html += '<b>最新一期（报告期 ' + latestRep.report_date + '）汪汪队持股</b>：';
      if (ntKeys.length) {
        for (var k = 0; k < ntKeys.length; k++) {
          var s = ntSum[ntKeys[k]];
          v2Html += '<span style="color:var(--primary)">' + ntKeys[k] + '</span> ' + s.count + '席/合计<b>' + s.total_share_yi + '亿份</b>(' + s.total_pct + '%)、';
        }
        v2Html = v2Html.replace(/、$/, '');
      } else {
        v2Html += '<span style="opacity:0.7">前十大持有人中无汪汪队席位</span>';
      }
      v2Html += '<br/>';
      var ntHistoryCount = 0;
      curEtf.reports.forEach(function (rep) {
        rep.holders.forEach(function (h) { if (h.type !== '其他机构') ntHistoryCount++; });
      });
      if (ntHistoryCount > 0) {
        v2Html += '<details><summary>📜 ' + curEtf.name + ' 汪汪队持股历史轨迹（' + curEtf.reports.length + '期，' + ntHistoryCount + '条汪汪队记录）</summary>';
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
      v2Html += '<b>' + (curEtf ? curEtf.name : state.ntEtf) + ' 暂无具名数据</b>：' + (curEtf ? curEtf.note || 'cninfo未收录该ETF的机构ID(orgId)' : '未找到') + '。<br/>';
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
  renderPurposeNote(container, PURPOSE_NOTES["market.a-stock"]);
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
    "资金面": "注：北向资金原「净买额」自 2024-08 港交所新规后停更，现改用 港交所(HKEX) 官方「成交总额」（沪股通+深股通买+卖合计）替代，反映外资交投活跃度而非净流入方向。每日收盘后更新。",
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
  renderPurposeNote(container, PURPOSE_NOTES["market.hk"]);
  if (r.hk_south && r.hk_south.length) {
    const hks = r.hk_south.map((d) => ({ date: d.date, value: d.value }));
    const chart = lineChart("港股通净买入（亿元）" + termTip("港股通南向资金净买入。内地投资者借港股通通道买港股,净流入为正=内地资金净买入港股(看好)。T+1数据。") + latestSuffixPct(hks), hks, {}, null, container);
    if (chart) addCardTimeBadge(chart.getDom().parentElement, hks.length ? hks[hks.length - 1].date : "", snap, "t1", "hk_south");
  }
  const indices = _injectHkSnapshot(r.indices, snap);
  // 指数折线区：目录锚点(主指数3 + 板块8 分两组, 共 11 项 chip)
  const indicesSection = document.createElement("div");
  indicesSection.className = "indices-section";
  container.appendChild(indicesSection);
  // 板块8 chip 跳转 industry-cell-<iid>(renderIndustryGrid 内 cell.id = 'industry-cell-'+id)
  const hkIndEntries = Object.entries(r.hk_industries || {});
  const extraGroups = hkIndEntries.length ? [{
    label: "板块",
    items: hkIndEntries.map(([id, idx]) => ({ key: id, name: idx.name, targetId: "industry-cell-" + id }))
  }] : [];
  const anchorBarRef = {};
  await renderIndicesSection(indicesSection, indices, async (id, idx) => {
    const raw = await fetchJSON(`https://ssd.fx8.store/index/${id}-all.json`);
    return { signals: filterSignalsByRange(raw.signals, idx.data), stats: raw.stats };
  }, true, extraGroups, anchorBarRef);
  // 港股板块指数（复用 renderIndustryGrid，与 A 股行业网格一致）
  if (hkIndEntries.length) {
    const hkIndWrap = document.createElement("div");
    hkIndWrap.className = "sw-grid-wrap";
    // 港股板块8卡挂进 indicesSection(非 container): anchorBar 在 indicesSection 内,
    // sticky 只在 indicesSection 滚动范围生效; 挂 container 会两区分离, 滚进板块区 sticky 失效
    indicesSection.appendChild(hkIndWrap);
    const hdr = document.createElement("h3");
    hdr.className = "section-title";
    hdr.textContent = "港股板块指数";
    hkIndWrap.appendChild(hdr);
    renderIndustryGrid(r.hk_industries, hkIndWrap);
    // 板块8 cell 渲染完后, 注册到 anchorBar scroll spy(chip 高亮当前可见板块 cell)
    if (anchorBarRef.bar) {
      hkIndEntries.forEach(([id]) => {
        const cell = document.getElementById("industry-cell-" + id);
        if (cell) anchorBarRef.bar._observeIndexCard(cell);
      });
    }
  }
}

// 外盘指数期货预期提示条：亚盘实时期货价 + 涨跌幅 + 预估对应指数开盘方向。
// 读 intraday_snapshot.us_futures（盘中快照采集时注入）。无数据不渲染。
// 配置源在 app/collector/us_futures.py 的 US_FUTURES_META，前端动态渲染任意条数。
// 期货↔指数相关性≈0.95；阈值±0.3%判预涨/预跌/持平。
function _renderUSFuturesExpect(snap, container) {
  const usf = snap && snap.us_futures;
  if (!usf || !Object.keys(usf).length) return;
  const items = [];
  let time = "";
  for (const code of Object.keys(usf)) {
    const d = usf[code];
    if (!d || d.price == null) continue;
    const chg = d.chg_pct;
    const chgCls = chg > 0 ? "up" : chg < 0 ? "down" : "flat";
    const chgTxt = (chg != null ? ((chg >= 0 ? "+" : "") + chg.toFixed(2) + "%") : "-");
    const expect = d.expect || "持平";
    const expectCls = expect === "预涨" ? "up" : expect === "预跌" ? "down" : "flat";
    if (d.time && !time) time = d.time;  // 取第一个有效时间作角标
    items.push(
      `<div class="usf-item">
        <span class="usf-name">${d.display_name || d.name}</span>
        <span class="usf-fname">${d.name || ""}</span>
        <span class="usf-price">${d.price.toFixed(2)}</span>
        <span class="usf-chg ${chgCls}">${chgTxt}</span>
        <span class="usf-arrow">-></span>
        <span class="usf-expect ${expectCls}">${expect}</span>
      </div>`);
  }
  if (!items.length) return;
  const div = document.createElement("div");
  div.className = "us-futures-expect";
  div.innerHTML =
    `<div class="usf-head">
      <span class="usf-title">🌍 外盘指数预期</span>
      <span class="usf-sub">期货亚盘实时 · 预估对应指数开盘方向（期货↔指数相关性≈0.95）</span>
    </div>
    <div class="usf-items">${items.join("")}</div>`;
  container.appendChild(div);
  // 时间角标：期货报价时间（亚盘实时），参考 addCardTimeBadge 机制用 card-time-badge 角标
  if (time) {
    div.insertAdjacentHTML("beforeend", `<span class="card-time-badge intraday" data-tip="外盘期货亚盘实时报价时间">⏰ ${time}</span>`);
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
  renderPurposeNote(container, PURPOSE_NOTES["market.global"]);
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
  // extras 指标定义(11 项, 提前到锚点条之前以便构造 chip 列表)
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
  // 指数目录锚点(全球): 指数12 + 指标11 共 23 项分两组, 吸顶 + chip 跳转 + scroll spy
  // 切 tab 时 clearCharts -> disconnectAllIndexNavSpies 统一 disconnect
  const _GLOBAL_EXTRAS_CHIP_NAME = {
    gold: "黄金", oil: "原油", wti_oil: "WTI", comex_silver: "白银",
    usdcnh: "离岸人民币", a_qvix_300: "波指300", a_qvix_1000: "波指50ETF",
    cn10y: "中10年国债", us10y: "美10年国债", cn_us_spread: "中美利差", brent: "布油",
  };
  const _globalAnchorGroups = [];
  if (idxEntries.length) {
    _globalAnchorGroups.push({
      label: "指数",
      items: idxEntries.map(([id, idx]) => ({
        key: id,
        name: (_INDEX_NAME_MAP && _INDEX_NAME_MAP[id]) ? _INDEX_NAME_MAP[id] : idx.name,
        targetId: "idx-card-" + id,
      })),
    });
  }
  // 指标 11 项(全列, 无 data 的 chip 点击静默失败)
  _globalAnchorGroups.push({
    label: "指标",
    items: Object.keys(extras).map(id => ({ key: id, name: _GLOBAL_EXTRAS_CHIP_NAME[id] || extras[id], targetId: "idx-card-" + id })),
  });
  const globalAnchorBar = buildIndexAnchorBar(_globalAnchorGroups, "指数目录");
  container.appendChild(globalAnchorBar);
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
        // 优先用前端 _INDEX_NAME_MAP 中文化（防 JSON name 英文化，如 kospi=KOSPI → 韩国KOSPI）
        const idxName = (_INDEX_NAME_MAP && _INDEX_NAME_MAP[id]) ? _INDEX_NAME_MAP[id] : idx.name;
        const chart = indexChart(idxName, idx.data, sigs, sig.stats, idx.strategy, cardGrid, charts, id);
        if (chart) {
          const cardEl = chart.getDom().parentElement;
          // 目录锚点跳转目标 id + scroll spy observe(卡片渲染完后注册)
          cardEl.id = "idx-card-" + id;
          globalAnchorBar._observeIndexCard(cardEl);
          // 全球指数 T+1/T+0 分类(2026-07-31 修正德法角标红色异常,三重根因根治):
          //   欧洲(dax/cac40/ftse100): T+1, 欧洲盘收盘北京23:30 OHLC次日采, 走 t1 + eu_global(02:00 backfill)
          //   亚洲(nikkei225/kospi/asx200/sensex): T+0, 与A股同时区盘中实时, 走 t0
          //   美洲(us_*): T+1, 美股收盘北京次日04:00, 走 t1 + us_dji_date(16:35 backfill)
          // 原 logic: us_->t1, 其余->t0 致德法(本质T+1)走t0, 盘后7-30<今日7-31触发红色"⚠滞后"误报
          const _EU_GLOBAL_IDS = new Set(["dax", "cac40", "ftse100"]);
          let _gSrcClass, _gSrcKey;
          if (id && id.startsWith("us_")) { _gSrcClass = "t1"; _gSrcKey = "us_dji_date"; }
          else if (_EU_GLOBAL_IDS.has(id)) { _gSrcClass = "t1"; _gSrcKey = "eu_global"; }
          else { _gSrcClass = "t0"; _gSrcKey = ""; }
          addCardTimeBadge(cardEl, idx.data.length ? idx.data[idx.data.length - 1].date : "", snap, _gSrcClass, _gSrcKey);
          // AZ89 P1+P2 全球指数实时报价角标(读 intraday_snapshot.global_realtime.<id>)
          addGlobalRealtimeBadge(cardEl, id, snap);
          // 标题❓策略弹窗（2026-07-20 方案B1）：h3 末尾追加❓，hover 一句话摘要 + click 弹该指数6类策略详情 modal
          _appendStrategyHint(cardEl, id, idx.strategy);
          // C7 P4 market 融合:全球指数卡下 append 紧凑分数卡
          _attachMarketScoreCard(id, idxName, cardEl);
        }
      }
    });
  }
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
        const cardEl = chart.getDom().parentElement;
        // 目录锚点跳转目标 id + scroll spy observe
        cardEl.id = "idx-card-" + id;
        globalAnchorBar._observeIndexCard(cardEl);
        const lastDate = data.length ? data[data.length - 1].date : "";
        if (dataStaleDays(lastDate) > STALE_DAYS) addStaleMark(cardEl, lastDate);
        else {
          // usdcnh=离岸人民币实时(T+0);
          // 2026-07-29 T+1治理: A组6商品(gold/oil/wti_oil/comex_silver/brent)采集侧改新浪/腾讯实时源变T+0,走t0分支(无T1角标)
          // 国债保持T+1(采集侧67acb836确认): cn10y=中债估值源端T+1; us10y=美债bond_zh_us_rate T+1(hf_TNX新浪源全空);
          // cn_us_spread=cn10y-us10y derived 跟随T+1; 走t1分支+srcKey映射到cn10y(共用T1_COLLECT_DEADLINE放宽口径)
          // 注: 采集侧新增cn10y_etf=sh511260十年国债ETF价格(T+0)作辅助参考,前端暂不加卡(后续再议是否展示ETF价格)
          // 剩余T+1 extras: a_qvix_1000 -> a_qvix_300 (qvix期权波动率optbbs次日发)
          const _T0_EXTRAS = new Set(["usdcnh", "gold", "oil", "wti_oil", "comex_silver", "brent"]);
          const _t0Extra = _T0_EXTRAS.has(id);
          const _srcKey = _t0Extra ? "" : ({ us10y: "cn10y", cn_us_spread: "cn10y", a_qvix_1000: "a_qvix_300" }[id] || id);
          addCardTimeBadge(cardEl, lastDate, snap, _t0Extra ? "t0" : "t1", _srcKey);
        }
        // 标题❓策略弹窗（2026-07-20 方案B1）：global 指标卡 h3 末尾追加❓（如 usdcnh skip买/cn_us_spread skip卖/usdcnh 2σ 去趋势 等 per-index 差异化策略）
        _appendStrategyHint(cardEl, id, extrasStrategy[id]);
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
    ? '<div class="comp-weight-note">权重为名义值；当日缺项时按可用分项重归一化。北向资金现用成交总额(港交所(HKEX)官方源)每日更新,原净买额2024-08停更保留历史权重。</div>'
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
  content.innerHTML = "";
  // 二级 tab 栏（市场温度/期货风向/汪汪队）—— 共通区只保留 tab 栏 + 容器 + 分发
  // purpose note / crosslink 已下沉到 renderSentimentMarketTemp（只市场温度 tab 显示，避免期货/汪汪队上方出现"温度计"提示）
  const subtabBar = document.createElement("div");
  subtabBar.className = "subtab-bar";
  const subtabs = [
    ["market-temp", "市场温度"],
    ["futures", "期货风向"],
    ["national-team", "汪汪队"],
    ["public-fund", "公募基金"],
  ];
  subtabs.forEach(([key, label]) => {
    const btn = document.createElement("button");
    btn.textContent = label;
    btn.dataset.subtab = key;
    if (state.subtab === key) btn.classList.add("active");
    btn.onclick = () => {
      state.subtab = key;
      _setTabHash(state.tab); // 写 #sentiment/{subtab}，F5 刷新恢复二级 tab
      renderSentiment(); // 重新渲染情绪 tab
    };
    subtabBar.appendChild(btn);
  });
  content.appendChild(subtabBar);

  // 子内容容器
  const subContent = document.createElement("div");
  subContent.className = "sentiment-sub-content";
  content.appendChild(subContent);
  renderLoadingState(subContent);

  // 根据 subtab 渲染对应内容
  await loadEcharts();   // P0-1: 子 render（renderFutures/renderPublicFund/renderSentimentHeatmap 等）用 mkCard+echarts，按需 await
  if (state.subtab === "futures") await renderFutures(subContent);
  else if (state.subtab === "national-team") await renderNationalTeam(subContent);
  else if (state.subtab === "public-fund") await renderPublicFund(subContent);
  else await renderSentimentMarketTemp(subContent); // 默认 market-temp
}

// 公募基金持仓二级 subtab：4 信号灯 + 仓位vs沪深300主图 + Top30 重仓 + 行业配置 + Top20 调仓
// 数据源：static-site/data/public_fund_*.json (5 个) + index/hs300-all.json (沪深300, 双轴右轴; close 字段=hs300 非上证)
// 口径：lg=股票型+混合型仓位(88魔咒专用, 范围 90%+); cninfo=全市场资产配置(含债基/货基, 范围 20%+)

// 行业配置"点击展开某行业基金列表"按需 fetch 缓存(模块级, 跨 re-render 复用, 避免重复拉 2MB)
// 数据源: https://ssd.fx8.store/public_fund/public_fund_industry_fund_map.json (方案D, 独立 JSON)
let _industryFundMapCache = null;
let _industryFundMapLoading = null;  // Promise 防并发重复 fetch
async function _loadIndustryFundMap() {
  if (_industryFundMapCache) return _industryFundMapCache;
  if (_industryFundMapLoading) return _industryFundMapLoading;
  _industryFundMapLoading = fetchJSON("https://ssd.fx8.store/public_fund/public_fund_industry_fund_map.json")
    .catch((e) => { console.warn("[pf-fund-map] fetch failed", e?.message || e); return null; })
    .finally(() => { _industryFundMapLoading = null; });
  _industryFundMapCache = await _industryFundMapLoading;
  return _industryFundMapCache;
}

// 制造业子行业->基金详情列表 按需 fetch 缓存(模块级, 跨 re-render 复用)
// 数据源: https://ssd.fx8.store/public_fund/public_fund_manuf_subind_fund_map.json (方案C Step5, 独立 JSON)
// 重仓股拆分口径: 每只制造业基金的重仓股按申万一级子行业聚合 weight_pct/hold_value 和
let _manufSubindFundMapCache = null;
let _manufSubindFundMapLoading = null;  // Promise 防并发重复 fetch
async function _loadManufSubindFundMap() {
  if (_manufSubindFundMapCache) return _manufSubindFundMapCache;
  if (_manufSubindFundMapLoading) return _manufSubindFundMapLoading;
  _manufSubindFundMapLoading = fetchJSON("https://ssd.fx8.store/public_fund/public_fund_manuf_subind_fund_map.json")
    .catch((e) => { console.warn("[pf-subind-map] fetch failed", e?.message || e); return null; })
    .finally(() => { _manufSubindFundMapLoading = null; });
  _manufSubindFundMapCache = await _manufSubindFundMapLoading;
  return _manufSubindFundMapCache;
}

async function renderPublicFund(container) {
  _disposeContainerCharts(container);
  renderLoadingState(container);
  let summary, holdings, industry, shIndex, backtest, estimate;
  try {
    [summary, holdings, industry, shIndex, backtest, estimate] = await Promise.all([
      fetchJSON("https://ssd.fx8.store/public_fund/public_fund_summary.json").catch(() => null),
      fetchJSON("https://ssd.fx8.store/public_fund/public_fund_holdings.json").catch(() => null),
      fetchJSON("https://ssd.fx8.store/public_fund/public_fund_industry.json").catch(() => null),
      fetchJSON("https://ssd.fx8.store/index/hs300-all.json").catch(() => null),
      // G功能: 88魔咒历史回测+极值标注(独立 JSON, 独立计算非 7 元组)
      fetchJSON("https://ssd.fx8.store/public_fund/public_fund_position_backtest.json").catch(() => null),
      // 今日预估仓位(日频 OLS 预估, 补 lg 周频滞后): 主图加第3条 series + 末端 markPoint 标 current
      fetchJSON("https://ssd.fx8.store/public_fund/public_fund_position_estimate.json").catch(() => null),
    ]);
  } catch (e) {
    renderErrorState(container, e, () => renderPublicFund(container));
    return;
  }
  if (!summary || !summary.metrics) {
    container.innerHTML = '<div class="loading">暂无数据</div>';
    return;
  }
  container.innerHTML = "";

  // ── 注入 pf- 样式(自包含, 只注入一次) ──
  if (!document.getElementById("pf-style")) {
    const st = document.createElement("style");
    st.id = "pf-style";
    st.textContent = `
.pf-banner{background:linear-gradient(90deg,rgba(255,152,0,0.12),rgba(230,73,46,0.08));border:1px solid #ff9800;border-left:4px solid #ff9800;border-radius:8px;padding:10px 14px;margin:8px 0 12px;font-size:13px;color:var(--text-2);line-height:1.6;}
.pf-banner b{color:#ff9800;}
.pf-caliber-note{font-size:12px;color:var(--text-3);background:var(--bg-hover);border-radius:6px;padding:6px 12px;margin:4px 0 12px;border-left:3px solid var(--border-strong);}
.pf-sig-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px;margin-bottom:12px;}
.pf-sig-card{border:1px solid;border-radius:10px;padding:12px 14px;background:var(--bg-card, var(--bg-1));display:flex;flex-direction:column;gap:4px;}
.pf-sig-name{font-size:12px;color:var(--text-3);}
.pf-sig-value{font-size:26px;font-weight:700;line-height:1.1;}
.pf-sig-status{font-size:11px;color:var(--text-3);}
.pf-delta{font-size:12px;font-weight:600;}
.pf-delta-na{color:var(--text-3);font-weight:400;}
.pf-two-col{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:12px;margin-bottom:12px;align-items:stretch;}
@media(max-width:900px){.pf-two-col{grid-template-columns:1fr;}}
.pf-main-chart-card{margin-bottom:12px;}
.pf-table-wrap{max-height:420px;overflow:auto;}
/* 左侧 Top30 card 跟右侧柱状图+treemap 撑到同高: grid stretch 让 card 撑满 cell, flex column + flex:1 让表格区域吃掉剩余高度, 消除下方空白 */
.pf-top30-card{display:flex;flex-direction:column;overflow:hidden;}
.pf-top30-card .pf-table-wrap{flex:1 1 0;max-height:none;min-height:0;overflow:auto;}
.pf-table{width:100%;border-collapse:collapse;font-size:12px;}
.pf-table th,.pf-table td{padding:5px 8px;border-bottom:1px solid var(--border-light, var(--border));text-align:left;white-space:nowrap;}
.pf-table th{position:sticky;top:0;background:var(--bg-hover);color:var(--text-2);font-weight:600;z-index:1;box-shadow:inset 0 -1px 0 0 var(--border-light, var(--border));}
.pf-table tr:hover td{background:var(--bg-hover);}
.pf-num{text-align:right;font-variant-numeric:tabular-nums;}
.pf-code{font-family:ui-monospace,monospace;color:var(--text-3);font-size:11px;}
/* 申万一级行业小标签: 红色系(和 .pf-sort-btn.active 同色 #e6492e), 轻底色, 不抢主信息 */
.pf-ind-tag{display:inline-block;padding:1px 6px;border-radius:3px;font-size:11px;color:#e6492e;background:rgba(230,73,46,0.08);white-space:nowrap;}
.pf-help{margin:8px 0 12px;font-size:13px;}
.pf-help>summary{cursor:pointer;user-select:none;color:var(--primary);font-size:13px;font-weight:600;display:inline-block;padding:4px 0;}
.pf-help>summary:hover{color:var(--primary-hover);}
.pf-help-body{margin-top:6px;padding:10px 14px;background:var(--bg-card,var(--bg-1));border:1px solid var(--border-light,var(--border));border-left:4px solid var(--primary);border-radius:6px;font-size:12.5px;color:var(--text-2);line-height:1.7;}
.pf-help-body>div{margin:5px 0;}
.pf-help-body b{color:var(--text-1);font-weight:600;}
.pf-help-body ul{margin:4px 0 4px 18px;padding:0;}
.pf-help-body li{margin:3px 0;}
.pf-help-warn{margin-top:8px;padding:6px 10px;background:rgba(255,152,0,0.08);border-left:3px solid #ff9800;border-radius:4px;color:var(--text-2);font-size:12px;}
/* TreeMap 容器: 显式 width:100% + height:200px 确保 echarts.init 拿到非 0 尺寸(配合完整版 echarts 含 treemap 组件) */
.pf-ind-treemap{width:100%;height:140px;}
/* Top100 调仓表: table-layout fixed + width:100% 撑满容器, 百分比列宽分配(名称列 20% 不再独占剩余致中间空白); td overflow:hidden 防长名称溢出 */
.pf-table-top100{table-layout:fixed;width:100%;}
.pf-table-top100 td{overflow:hidden;text-overflow:ellipsis;}
/* 三态排序按钮: 固定 18x18 不随箭头内容变化跳动; active 态红色高亮 */
.pf-sort-btn{display:inline-flex;align-items:center;justify-content:center;width:18px;height:18px;margin-left:3px;padding:0;border:1px solid var(--border-light,var(--border));border-radius:4px;background:var(--bg-hover);color:var(--text-3);font-size:11px;line-height:1;cursor:pointer;vertical-align:middle;transition:color .1s,border-color .1s,background .1s;}
.pf-sort-btn:hover{border-color:var(--primary);color:var(--primary);}
.pf-sort-btn.active{border-color:#e6492e;color:#e6492e;background:rgba(230,73,46,0.10);font-weight:700;}
.pf-sort-arrow{display:inline-block;width:12px;text-align:center;color:#999;}
.pf-sort-btn.active .pf-sort-arrow{color:#e6492e;}
/* 行业配置排序切换按钮: 文字胶囊, 3 选 1 互斥, active 红底白字(区别于 .pf-sort-btn 的小方框箭头) */
.pf-ind-sort-btn{display:inline-block;margin-left:6px;padding:2px 9px;border:1px solid var(--border-light,var(--border));border-radius:11px;background:var(--bg-hover);color:var(--text-3);font-size:11px;line-height:1.4;cursor:pointer;vertical-align:middle;transition:color .1s,border-color .1s,background .1s;}
.pf-ind-sort-btn:hover{border-color:var(--primary);color:var(--primary);}
.pf-ind-sort-btn.active{border-color:#e6492e;color:#fff;background:#e6492e;font-weight:600;}
/* 行业基金列表 modal: 复用 .rule-modal 骨架, 覆盖宽度 600px + 红色主题(标题/× 关闭按钮 #e6492e) */
.pf-ind-fund-modal .rule-modal-body{width:min(92vw,600px);min-height:300px;}
.pf-ind-fund-modal .rule-modal-header h3{color:#e6492e;}
.pf-ind-fund-modal .rule-modal-close:hover{color:#e6492e;}
.pf-ind-fund-modal .pf-table-wrap{max-height:60vh;overflow:auto;border:1px solid var(--border-light,var(--border));border-radius:6px;}
.pf-ind-fund-modal .pf-modal-tip{font-size:11px;color:var(--text-3);margin-top:8px;line-height:1.5;}
/* 翻页器: 复用 .etf-page-btn 风格, active 态改 #e6492e 红色主题(A股配色) */
.pf-ind-fund-pager{display:flex;align-items:center;gap:6px;flex-wrap:wrap;justify-content:center;padding:10px 8px 4px;}
.pf-ind-fund-pager .pf-page-btn{min-width:32px;height:30px;padding:0 10px;border:1px solid var(--border-strong,var(--border));background:var(--bg-card,var(--bg-1));color:var(--text-2);border-radius:6px;cursor:pointer;font-size:13px;}
.pf-ind-fund-pager .pf-page-btn:hover:not(:disabled):not(.active){border-color:#e6492e;color:#e6492e;}
.pf-ind-fund-pager .pf-page-btn.active{background:#e6492e;color:#fff;border-color:#e6492e;font-weight:600;}
.pf-ind-fund-pager .pf-page-btn:disabled{opacity:0.4;cursor:not-allowed;}
.pf-ind-fund-pager .pf-page-ellipsis{color:var(--text-4);padding:0 4px;}
.pf-ind-fund-pager .pf-page-info{font-size:12px;color:var(--text-3);margin-left:8px;}
/* 制造业 2-tab 弹窗( TreeMap 点击制造业 ): Tab1 子行业列表(可点击下钻) + Tab2 制造业全部基金 */
.pf-tab-header{display:flex;gap:0;border-bottom:2px solid var(--border-light,var(--border));margin-bottom:0;}
.pf-tab-btn{flex:1;padding:10px 16px;border:none;background:var(--bg-hover);color:var(--text-3);font-size:13px;font-weight:600;cursor:pointer;border-bottom:2px solid transparent;margin-bottom:-2px;transition:color .1s,background .1s,border-color .1s;}
.pf-tab-btn:hover{color:var(--primary);}
.pf-tab-btn.active{color:#e6492e;background:var(--bg-card,var(--bg-1));border-bottom-color:#e6492e;}
.pf-tab-body{display:none;padding:12px 0 0;}
.pf-tab-body.active{display:block;}
/* Tab1 子行业表格行可点击下钻: cursor pointer + hover 高亮 */
.pf-subind-table{width:100%;border-collapse:collapse;font-size:12.5px;}
.pf-subind-table th,.pf-subind-table td{padding:6px 10px;border-bottom:1px solid var(--border-light,var(--border));text-align:left;white-space:nowrap;}
.pf-subind-table th{background:var(--bg-hover);color:var(--text-2);font-weight:600;position:sticky;top:0;}
.pf-subind-row{cursor:pointer;transition:background .1s;}
.pf-subind-row:hover td{background:rgba(230,73,46,0.08);}
.pf-subind-row:hover .pf-subind-name{color:#e6492e;}
.pf-subind-name{font-weight:600;cursor:pointer;}
.pf-subind-arrow{color:#e6492e;font-size:11px;margin-left:4px;}
.pf-tab-tip{font-size:11px;color:var(--text-3);margin:6px 0 10px;line-height:1.5;}
/* G功能: 88魔咒历史回测统计面板 */
.pf-backtest-card{margin-bottom:12px;}
.pf-backtest-card .pf-bt-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-top:8px;}
@media(max-width:900px){.pf-backtest-card .pf-bt-grid{grid-template-columns:1fr;}}
.pf-bt-section{border:1px solid var(--border-light,var(--border));border-radius:8px;padding:10px 14px;background:var(--bg-card,var(--bg-1));}
.pf-bt-spell88{border-left:4px solid #e6492e;}
.pf-bt-dip80{border-left:4px solid #2e8b57;}
.pf-bt-current{border-left:4px solid #ff9800;}
.pf-bt-head{font-size:13px;font-weight:700;margin-bottom:8px;padding-bottom:6px;border-bottom:1px solid var(--border-light,var(--border));}
.pf-bt-row{display:flex;justify-content:space-between;align-items:center;font-size:12px;color:var(--text-3);padding:3px 0;}
.pf-bt-row b{color:var(--text-1);font-weight:600;font-variant-numeric:tabular-nums;}
.pf-bt-time{color:var(--text-3);font-size:11px;font-weight:400;margin-left:6px;white-space:nowrap;}
.pf-bt-note{margin-top:8px;padding:6px 10px;background:var(--bg-hover);border-radius:4px;font-size:11px;color:var(--text-3);line-height:1.5;}
/* N功能: 多信号共振仪表盘 */
.pf-nf-card{margin-bottom:12px;}
.pf-nf-res-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px;margin-top:10px;}
@media(max-width:900px){.pf-nf-res-grid{grid-template-columns:1fr;}}
/* F功能: 行业轮动时序堆叠面积图 */
.pf-rot-card{margin-bottom:12px;}
.pf-rot-range{display:inline-flex;gap:2px;margin-left:8px;}
.pf-rot-range-btn{font-size:11px;padding:2px 8px;border:1px solid var(--border);border-radius:10px;background:transparent;color:var(--text-3);cursor:pointer;line-height:1.4;}
.pf-rot-range-btn.active{background:#e6492e;color:#fff;border-color:#e6492e;}
.pf-rot-range-btn:hover:not(.active){color:var(--text-1);border-color:var(--text-3);}
`;
    document.head.appendChild(st);
  }

  const _pfFmtDate = (s) => s && String(s).length === 8 ? `${s.slice(0,4)}-${s.slice(4,6)}-${s.slice(6,8)}` : (s || "");

  // ── 滞后性提示 banner ──
  const reportDate = summary.report_date || "";
  const banner = document.createElement("div");
  banner.className = "pf-banner";
  banner.innerHTML = `⚠️ 本数据截止 <b>${_pfFmtDate(reportDate)}</b>（季报披露滞后约 15 天），仅作辅助参考，不作主信号`;
  container.appendChild(banner);

  // ── 板块帮助说明（可折叠，复用 details+summary 模式，参考 hint-kelly-explain）──
  const helpBox = document.createElement("details");
  helpBox.className = "pf-help";
  helpBox.innerHTML = `<summary>📖 这个板块有什么用？（点击展开说明）</summary>
    <div class="pf-help-body">
      <div><b>板块作用</b>：公募基金持仓作为<b>第 4 维资金面</b>，补充现有「北向 / 两融 / 产业资本」三维，提供<b>机构资金视角</b>。参考性等级<b>中等</b>，作辅助维度有价值，<b>不作主信号</b>（因季报披露滞后 15 个工作日，披露时点持仓 ≠ 当前持仓）。</div>
      <div><b>核心指标（4 信号灯卡片 + 4 衍生）</b>：</div>
      <ul>
        <li><b>平均股票仓位</b>：基金加权平均股票占净比（净资产规模加权，乐咕乐股口径=股票型+混合型）。<b>&gt;88%=88 魔咒见顶警示</b>（加仓空间有限）；<b>&lt;80%=抄底机会</b>（仓位低有加仓空间）；80-88%=中位。</li>
        <li><b>抱团度 HHI（赫芬达尔指数）</b>：重仓股集中度指数。<b>&gt;0.10=高度抱团</b>（瓦解风险积累）；0.05-0.10=中度抱团；<b>&lt;0.05=分散健康</b>。急升=风险积累，急降=瓦解信号。</li>
        <li><b>重叠度（Top30 均覆盖）</b>：Top30 重仓股平均被多少家基金持有（家数）。<b>&gt;1500=高度重叠</b>；800-1500=中度重叠；<b>&lt;800=重叠度低</b>。重叠度高=机构共识强但也意味瓦解时共振下跌。</li>
        <li><b>净申赎率</b>：基金份额变化 / 总规模（%）。<b>&gt;0.5%=净申购（散户乐观，反向看空）</b>；<b>&lt;-0.5%=净赎回（散户悲观，反向看多）</b>；-0.5%~0.5%=申赎平衡。</li>
        <li><b>行业集中度</b>（衍生）：Top3 行业占比之和，&gt;60%=高度集中。</li>
        <li><b>加仓/减仓比 / 头部调仓 / Top30 集中度</b>（3 项衍生辅助）：情绪面方向、顶流整体方向、核心资产集中度。</li>
      </ul>
      <div><b>88 魔咒 / 80 抄底</b>：基金平均仓位 <b>&gt;88%</b> 时加仓空间有限，历史多对应阶段性顶部（应验 <b>2009/7、2015/5、2021/1</b> 等）；<b>&lt;80%</b> 时仓位低有加仓空间，多对应阶段性底部。<b>反向指标，非精确触发</b>--2020 年仓位持续 90%+ 大盘仍涨，仅作风险提示。</div>
      <div><b>4 维资金面共振</b>：北向（外资 / 日更）+ 两融（杠杆 / 日更）+ 产业资本（内部人 / 月更）+ 基金持仓（机构 / 季更），<b>4 维同向信号最强</b>。如「北向流出 + 两融下降 + 产业资本减持 + 基金减仓」= 4 维共振看空。</div>
      <div><b>滞后性与披露规则</b>：季报季末 +15 工作日披露（Q1≈4/22、Q2≈7/22、Q3≈10/22、年报≈3/31 前），季报只披露<b>前十大重仓 + 资产配置 + 行业配置</b>，全部持仓要等中报（60 日内）/年报（90 日内）。</div>
      <div><b>数据源</b>：东方财富基金详情页（持仓/重仓/行业/资产/经理/净值/分红等子页）+ akshare 9 个接口（基金持仓/基金估值等），免费无需密钥。</div>
      <div><b>学术背景</b>：①中国公募基金存在显著羊群效应（许年行等 2013《经济研究》），加剧「抱团-瓦解」循环 ②基金平均仓位与未来大盘收益负相关（88 魔咒统计显著）③2021/1 白酒新能源抱团瓦解领先沪深 300 见顶（2021/2/18 5930 点）约 1 个月 ④基金净申赎与未来 1-3 个月大盘收益负相关（散户情绪反向）。</div>
      <div class="pf-help-warn">⚠ 本板块为辅助参考维度，滞后性强不作主信号；88 魔咒为历史规律未必未来应验。研究参考，不构成投资建议，历史回测不代表未来收益。</div>
    </div>`;
  container.appendChild(helpBox);

  // 任务10 改动2(2026-07-20): 4维资金面共振区块(复用首页 _renderPublicFundHomeCard 的4维逻辑, 自包含样式)
  // 数据来源同首页: overview.json r.today.metrics 3维 + a-stock-3m.json 末两点算环比 + summary.position_history 基金维
  try {
    if (!document.getElementById("pf-resonance-style")) {
      const _rs = document.createElement("style");
      _rs.id = "pf-resonance-style";
      _rs.textContent = ".pf-resonance-card{margin-bottom:12px;}.pf-resonance-card .pf-resonance{margin-top:4px;padding:8px 10px;border-radius:6px;font-size:12.5px;line-height:1.6;background:var(--bg-hover);border-left:3px solid var(--border-strong);}.pf-resonance-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));gap:6px;margin-top:6px;}.pf-resonance-cell{padding:5px 8px;border-radius:4px;background:var(--bg-card,var(--bg-1));font-size:11.5px;border:1px solid var(--border-light,var(--border));}.pf-resonance-cell .pf-rc-name{color:var(--text-3);font-size:10.5px;}.pf-resonance-cell .pf-rc-dir{font-weight:600;margin-top:2px;}.pf-rc-up{color:#e6492e;}.pf-rc-down{color:#2e8b57;}.pf-rc-flat{color:var(--text-3);}.pf-rc-unknown{color:var(--text-3);font-style:italic;}.pf-resonance-badge{display:inline-block;padding:3px 10px;border-radius:4px;font-weight:700;font-size:13px;margin-left:6px;}.pf-resonance-bull{background:rgba(230,73,46,0.15);color:#e6492e;border:1px solid #e6492e;}.pf-resonance-bear{background:rgba(46,139,87,0.15);color:#2e8b57;border:1px solid #2e8b57;}.pf-resonance-none{background:var(--bg-hover);color:var(--text-3);border:1px solid var(--border-light,var(--border));font-weight:400;}";
      document.head.appendChild(_rs);
    }
    let _pfR = _getCachedOverview();
    if (!_pfR) { _pfR = await fetchJSON("./data/overview.json").catch(() => null); }
    if (_pfR && _pfR.today && _pfR.today.metrics) {
      const _pfMetrics = _pfR.today.metrics || [];
      const _pfFindM = (id) => _pfMetrics.find((m) => m.id === id);
      const _pfNorth = _pfFindM("a_fund_north");
      const _pfMargin = _pfFindM("a_fund_margin");
      const _pfMain = _pfFindM("a_fund_main");
      let _pfAvgPosDelta = null;
      if (summary.position_history && summary.position_history.length >= 2) {
        const lgHist = summary.position_history.filter((h) => h.source === "lg").sort((a, b) => a.report_date.localeCompare(b.report_date));
        if (lgHist.length >= 2) { const n = lgHist.length; _pfAvgPosDelta = +(lgHist[n-1].position_pct - lgHist[n-2].position_pct).toFixed(2); }
      }
      const _pfDir = {
        fund: _pfAvgPosDelta != null ? (_pfAvgPosDelta > 0 ? "多" : _pfAvgPosDelta < 0 ? "空" : "平") : "unknown",
        main: _pfMain && _pfMain.value != null ? (_pfMain.value > 0 ? "多" : _pfMain.value < 0 ? "空" : "平") : "unknown",
        margin: "unknown",
        north: "unknown",
      };
      try {
        const _pfHist = await fetchJSON("./data/a-stock-3m.json").catch(() => null);
        if (_pfHist && _pfHist.metrics) {
          const _pfLast2 = (id) => { const m = _pfHist.metrics[id]; if (!m || !m.data || m.data.length < 2) return [null, null]; const n = m.data.length; return [m.data[n-2].value, m.data[n-1].value]; };
          const [mp, mc] = _pfLast2("a_fund_margin"); if (mp != null && mc != null) _pfDir.margin = mc > mp ? "多" : mc < mp ? "空" : "平";
          const [np, nc] = _pfLast2("a_fund_north"); if (np != null && nc != null) _pfDir.north = nc > np ? "多" : nc < np ? "空" : "平";
        }
      } catch {}
      const _pfDirs = [_pfDir.fund, _pfDir.main, _pfDir.margin, _pfDir.north];
      const _pfAllKnown = _pfDirs.every((d) => d === "多" || d === "空");
      const _pfAllSame = _pfAllKnown && _pfDirs.every((d) => d === _pfDirs[0]);
      const _pfRes = _pfAllSame ? (_pfDirs[0] === "多" ? "看多" : "看空") : null;
      const _pfResBadge = _pfRes === "看多" ? '<span class="pf-resonance-badge pf-resonance-bull">4 维共振看多</span>'
        : _pfRes === "看空" ? '<span class="pf-resonance-badge pf-resonance-bear">4 维共振看空</span>'
        : '<span class="pf-resonance-badge pf-resonance-none">4 维方向不一 · 暂无共振</span>';
      const _pfDirCell = (name, d) => {
        const cls = d === "多" ? "pf-rc-up" : d === "空" ? "pf-rc-down" : d === "平" ? "pf-rc-flat" : "pf-rc-unknown";
        const label = d === "unknown" ? "暂无" : d;
        return '<div class="pf-resonance-cell"><div class="pf-rc-name">' + name + '</div><div class="pf-rc-dir ' + cls + '">' + label + '</div></div>';
      };
      const _pfResBlock = document.createElement("div");
      _pfResBlock.className = "chart-card pf-resonance-card";
      _pfResBlock.innerHTML = '<h3>🔀 4 维资金面共振 ' + _pfResBadge + '</h3>' +
        '<div class="pf-resonance"><div style="font-size:12px;color:var(--text-3);margin:4px 0 8px">4维同向(皆多/皆空)才标共振;任一方向不明或不一致则不共振。北向=外资/两融=杠杆/主力=产业资本/基金=机构。</div>' +
        '<div class="pf-resonance-grid">' +
          _pfDirCell("北向(成交额环比)", _pfDir.north) +
          _pfDirCell("两融(余额环比)", _pfDir.margin) +
          _pfDirCell("主力(净流入正负)", _pfDir.main) +
          _pfDirCell("基金(仓位环比)", _pfDir.fund) +
        '</div>' +
        '<div style="margin-top:6px;font-size:11px;color:var(--text-3);line-height:1.5">注:北向原净买额 2024-08 停更,现用成交总额环比;主力=大单净流入;基金=季报仓位环比。4维频率不同(日/日/日/季),基金维更新慢。</div></div>';
      container.appendChild(_pfResBlock);
    }
  } catch (e) { /* 4维共振区块失败不影响其他渲染 */ }

  // ── 提取 4 信号灯指标 ──
  const metricsMap = {};
  (summary.metrics || []).forEach((m) => { metricsMap[m.metric_id] = m; });
  const avgPos = metricsMap["avg_position"];           // 平均仓位 96.01 (lg 口径)
  const conc = metricsMap["concentration_herfindahl"]; // 抱团度 HHI
  const overlap = metricsMap["overlap_ratio"];         // 重叠度 (Top30 平均覆盖基金家数)
  const netRedeem = metricsMap["net_redeem_ratio"];    // 净申赎率 %

  // 计算变化(avg_position 从 position_history 最近两期 lg 差; net_redeem 从 scale_change_history 推)
  const _pfCalcChange = () => {
    let avgPosDelta = null, netRedeemDelta = null;
    if (summary.position_history && summary.position_history.length >= 2) {
      const lgHist = summary.position_history.filter((h) => h.source === "lg").sort((a, b) => a.report_date.localeCompare(b.report_date));
      if (lgHist.length >= 2) {
        const n = lgHist.length;
        avgPosDelta = +(lgHist[n-1].position_pct - lgHist[n-2].position_pct).toFixed(2);
      }
    }
    if (summary.scale_change_history && summary.scale_change_history.length >= 2) {
      const sch = summary.scale_change_history;
      const n = sch.length;
      const cur = sch[n-1], prev = sch[n-2];
      if (cur.end_total_share && prev.end_total_share) {
        const curRate = cur.net_purchase_share / cur.end_total_share * 100;
        const prevRate = prev.net_purchase_share / prev.end_total_share * 100;
        netRedeemDelta = +(curRate - prevRate).toFixed(3);
      }
    }
    return { avgPosDelta, netRedeemDelta };
  };
  const { avgPosDelta, netRedeemDelta } = _pfCalcChange();

  // 颜色规则辅助
  const _pfColorFor = (metricId, value) => {
    if (value == null) return { color: "var(--text-3)", status: "暂无数据" };
    if (metricId === "avg_position") {
      if (value > 88) return { color: "#e6492e", status: "88 魔咒警示（高位）" };
      if (value >= 80) return { color: "#ff9800", status: "中位" };
      return { color: "#2e8b57", status: "抄底机会（低位）" };
    }
    if (metricId === "concentration_herfindahl") {
      if (value > 0.1) return { color: "#e6492e", status: "高度抱团" };
      if (value >= 0.05) return { color: "#ff9800", status: "中度抱团" };
      return { color: "#2e8b57", status: "分散健康" };
    }
    if (metricId === "overlap_ratio") {
      if (value > 1500) return { color: "#e6492e", status: "高度重叠" };
      if (value >= 800) return { color: "#ff9800", status: "中度重叠" };
      return { color: "#2e8b57", status: "重叠度低" };
    }
    if (metricId === "net_redeem_ratio") {
      if (value > 0.5) return { color: "#e6492e", status: "净申购（多头）" };
      if (value > -0.5) return { color: "#ff9800", status: "申赎平衡" };
      return { color: "#2e8b57", status: "净赎回（空头）" };
    }
    return { color: "var(--text-3)", status: "" };
  };

  // 变化箭头 HTML（仓位↑红/↓绿；净申赎↑红/↓绿）
  // status: "incomplete"=当期采集未完成 / "cross_type"=跨披露类型不可比 / null=正常显示 delta
  const _pfDeltaHtml = (delta, status) => {
    if (status === "incomplete") return '<span class="pf-delta pf-delta-na">较上季 数据采集中</span>';
    if (status === "cross_type") return '<span class="pf-delta pf-delta-na">较上季 跨期不可比</span>';
    if (delta == null) return '<span class="pf-delta pf-delta-na">较上季 -</span>';    const arrow = delta > 0 ? "↑" : delta < 0 ? "↓" : "→";
    const color = delta === 0 ? "var(--text-3)" : (delta > 0 ? "#e6492e" : "#2e8b57");
    const sign = delta > 0 ? "+" : "";
    return `<span class="pf-delta" style="color:${color}">较上季 ${arrow} ${sign}${delta.toFixed(2)}</span>`;
  };

  const _pfCard = (metricId, name, value, delta, unit, fmt, clickable, deltaStatus) => {
    const fv = fmt ? fmt(value) : (value != null ? value.toFixed(2) : "—");
    const { color, status } = _pfColorFor(metricId, value);
    return `<div class="pf-sig-card" data-metric-id="${metricId}" style="border-color:${color}${clickable ? ";cursor:pointer" : ""}">
      <div class="pf-sig-name">${name}${clickable ? ' <span style="font-size:10px;color:var(--text-3)">📋</span>' : ""}</div>
      <div class="pf-sig-value" style="color:${color}">${fv}${value != null ? unit : ""}</div>
      <div class="pf-sig-status">${status}</div>
      ${_pfDeltaHtml(delta, deltaStatus)}
    </div>`;
  };

  // 从 detail 提取 delta 状态: incomplete(采集未完成) / cross_type(跨披露类型) / null
  const _pfDeltaStatus = (d) => {
    if (!d) return null;
    if (d.incomplete) return "incomplete";
    if (d.cross_type) return "cross_type";
    return null;
  };

  const sigGrid = document.createElement("div");
  sigGrid.className = "pf-sig-grid";
  container.appendChild(sigGrid);
  sigGrid.innerHTML =
    _pfCard("avg_position", "平均股票仓位", avgPos ? avgPos.metric_value : null, avgPosDelta, "%") +
    _pfCard("concentration_herfindahl", "抱团度 HHI", conc ? conc.metric_value : null, conc && conc.detail && conc.detail.delta_vs_last != null ? conc.detail.delta_vs_last : null, "", null, true, _pfDeltaStatus(conc && conc.detail)) +
    _pfCard("overlap_ratio", "重叠度(Top30 均覆盖)", overlap ? overlap.metric_value : null, overlap && overlap.detail && overlap.detail.delta_vs_last != null ? overlap.detail.delta_vs_last : null, " 家", (v) => v.toFixed(0), true, _pfDeltaStatus(overlap && overlap.detail)) +
    _pfCard("net_redeem_ratio", "净申赎率", netRedeem ? netRedeem.metric_value : null, netRedeemDelta, "%");

  // 4卡片弹窗(抱团度Top10 + 重叠度Top30 重仓股明细, 复用 .rule-modal 样式)
  // 任务4(2026-08-02): grayFirstN 参数区分两弹窗。重叠度 Top30 前10与抱团度 Top10 相同,
  // 标灰(避免用户误解"两弹窗内容一样"), 11-30 高亮(重叠度独有, mark-new 角标)
  const _pfDetailModal = (title, stocks, subtitle, grayFirstN) => {
    const existing = document.getElementById("pf-detail-modal");
    if (existing) existing.remove();
    const grayN = grayFirstN || 0;
    const rows = (stocks || []).map((s, i) => {
      const isDup = i < grayN;  // 前 N 条与抱团度重复
      const rowStyle = isDup
        ? "border-bottom:1px solid var(--border);opacity:0.5;background:var(--bg-2,rgba(128,128,128,0.05))"
        : "border-bottom:1px solid var(--border)";
      const rankCell = isDup
        ? `<td style="text-align:center;color:var(--text-3);padding:3px 4px">${i + 1}<span style="display:block;font-size:9px;color:var(--text-3)">同抱团</span></td>`
        : `<td style="text-align:center;color:var(--text-3);padding:3px 4px">${i + 1}<span style="display:block;font-size:9px;color:#ff9800;font-weight:600">新增</span></td>`;
      const nameStyle = isDup ? "padding:3px 4px;color:var(--text-3)" : "padding:3px 4px";
      return `<tr style="${rowStyle}">
      ${rankCell}
      <td style="${nameStyle}"><b>${s.name || "-"}</b> <span style="color:var(--text-3);font-size:10px">${s.code || ""}</span></td>
      <td style="text-align:right;padding:3px 8px">${s.fund_count != null ? s.fund_count + " 家" : "-"}</td>
      <td style="text-align:right;padding:3px 8px">${s.value != null ? (s.value / 1e8).toFixed(2) + " 亿" : "-"}</td>
    </tr>`;
    }).join("");
    const modal = document.createElement("div");
    modal.id = "pf-detail-modal";
    modal.className = "rule-modal";
    modal.innerHTML = `<div class="rule-modal-overlay"></div>
      <div class="rule-modal-body" style="max-width:560px">
        <div class="rule-modal-header"><h3>${title}</h3>
          <button class="rule-modal-close" aria-label="关闭">&times;</button></div>
        <div class="rule-modal-content">
          ${subtitle ? `<div style="font-size:11px;color:var(--text-3);margin-bottom:8px;line-height:1.5">${subtitle}</div>` : ""}
          <table style="width:100%;border-collapse:collapse;font-size:12px">
            <thead><tr style="border-bottom:2px solid var(--border)">
              <th style="padding:4px;text-align:center">#</th>
              <th style="padding:4px;text-align:left">股票</th>
              <th style="padding:4px;text-align:right">持有基金数</th>
              <th style="padding:4px;text-align:right">持仓市值</th>
            </tr></thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
      </div>`;
    document.body.appendChild(modal);
    modal.classList.remove("hidden");
    const _close = () => modal.remove();
    modal.querySelector(".rule-modal-overlay").addEventListener("click", _close);
    modal.querySelector(".rule-modal-close").addEventListener("click", _close);
  };

  sigGrid.addEventListener("click", (e) => {
    const card = e.target.closest(".pf-sig-card[data-metric-id]");
    if (!card) return;
    const mid = card.dataset.metricId;
    if (mid === "concentration_herfindahl" && conc && conc.detail && conc.detail.top10_stocks) {
      const d = conc.detail;
      const _dltTxt = d.delta_vs_last != null ? (d.delta_vs_last > 0 ? "+" : "") + d.delta_vs_last.toFixed(6)
        : (d.incomplete ? "数据采集中" : (d.cross_type ? "跨期不可比" : "-"));
      const _statNote = d.incomplete ? " · 当期采集未完成(中报披露期8/31截止, stocks数偏低), delta暂不显示"
        : (d.cross_type ? " · 当期与上期披露类型不同(全披露vs前十大), 跨期不可比" : "");
      _pfDetailModal("📊 抱团度 HHI · Top10 重仓股", d.top10_stocks,
        `HHI=${conc.metric_value}（0-1, 值越大抱团越集中）· 较上季 ${_dltTxt} · 上期 ${d.prev_report_date || "-"}${_statNote}`);
    } else if (mid === "overlap_ratio" && overlap && overlap.detail && overlap.detail.top30_stocks) {
      const d = overlap.detail;
      const _dltTxt = d.delta_vs_last != null ? (d.delta_vs_last > 0 ? "+" : "") + d.delta_vs_last.toFixed(2) + " 家"
        : (d.incomplete ? "数据采集中" : (d.cross_type ? "跨期不可比" : "-"));
      const _statNote = d.incomplete ? " · 当期采集未完成(中报披露期8/31截止, stocks数偏低), delta暂不显示"
        : (d.cross_type ? " · 当期与上期披露类型不同(全披露vs前十大), 跨期不可比" : "");
      // 任务4(2026-08-02): 重叠度 Top30 弹窗前10条标灰(与抱团度 Top10 相同), 11-30 高亮(重叠度独有新增)
      // subtitle 明确"前10与抱团度相同, 11-30为新增", 避免用户误解两弹窗内容一样
      _pfDetailModal("🎯 重叠度 · Top30 重仓股持有基金数", d.top30_stocks,
        `平均每只被 ${overlap.metric_value} 家基金持有 · 较上季 ${_dltTxt} · 上期 ${d.prev_report_date || "-"}${_statNote}<br>` +
        `<b style="color:#ff9800">注: 前 10 条(灰色)与抱团度 Top10 相同, 第 11-30 条(橙色"新增"标)为重叠度独有</b>`,
        10);
    }
  });

  // 口径说明
  if (avgPos && avgPos.detail && avgPos.detail.note) {
    const noteDiv = document.createElement("div");
    noteDiv.className = "pf-caliber-note";
    noteDiv.innerHTML = `📊 口径: ${avgPos.detail.note}（当前乐咕乐股源=${avgPos.detail.lg_position}%，巨潮资讯源=${avgPos.detail.cninfo_position}%）`;
    container.appendChild(noteDiv);
  }

  // ── 区域 2: 主图 仓位 vs 沪深300 双轴折线 + 88/80 markLine ──
  const chartCard = document.createElement("div");
  chartCard.className = "chart-card pf-main-chart-card";
  const _estCur = estimate && estimate.current ? estimate.current : null;
  const _confZh = (c) => ({ high: "高", medium: "中", low: "低" })[c] || (c || "-");
  const _estTitleSuffix = _estCur
    ? `<span style="font-size:12px;color:#ff9800;margin-left:8px;font-weight:600">今日预估 ${_estCur.position_estimate}%（日频线性回归，较乐咕乐股源 ${_estCur.lg_latest_position}% 偏差${_estCur.deviation_from_lg > 0 ? "+" : ""}${_estCur.deviation_from_lg}%）</span>`
    : "";
  chartCard.innerHTML = `<div class="chart-title">📈 平均股票仓位与沪深300（乐咕乐股源=股票型+混合型，88 魔咒专用口径）${_estTitleSuffix}</div><div class="chart" style="height:380px"></div>`;
  container.appendChild(chartCard);

  const posHist = (summary.position_history || []).filter((h) => h.source === "lg").sort((a, b) => a.report_date.localeCompare(b.report_date));
  let posPoints = posHist.map((h) => [h.report_date, h.position_pct]);

  // 仓位主图响应全局 state.range(3m/6m/1y/3y/5y/all): 基于仓位数据末日回推 cutoff，
  // 复用 _signalModalCutoff 逻辑(与首页周期按钮/信号弹窗一致)；null=all/空=不过滤
  const _pfCutoff = _signalModalCutoff(posPoints.map((p) => ({ date: p[0], value: p[1] })), state.range || "all");
  if (_pfCutoff) posPoints = posPoints.filter((p) => p[0] >= _pfCutoff);

  let shPoints = [];
  if (shIndex && shIndex.ohlc && shIndex.ohlc.length) {
    if (posPoints.length) {
      const minDate = posPoints[0][0], maxDate = posPoints[posPoints.length - 1][0];
      shPoints = shIndex.ohlc.filter((d) => d.date >= minDate && d.date <= maxDate).map((d) => [d.date, d.close]);
    } else {
      shPoints = shIndex.ohlc.slice(-100).map((d) => [d.date, d.close]);
    }
  }

  const mainChart = echarts.init(chartCard.querySelector(".chart"));
  charts.push(mainChart);
  const shVals = shPoints.map((p) => p[1]);
  const shMin = shVals.length ? Math.min(...shVals) : 3500;
  const shMax = shVals.length ? Math.max(...shVals) : 5000;
  // 今日预估仓位 series(日频 OLS 预估, 补 lg 周频滞后): history 147期时序 + 末端 markPoint 标 current
  // 预估 history date="2025-12-22" 需转 "20251222" 匹配 xAxis category(和 _btDateToCoord 同逻辑, 此处提前用)
  // 预估线只画有数据的部分(2025-12-22 起), 和 lg 线(2007 起)在 2025-12-22~2026-07-24 重叠期可视觉对比日频vs周频
  // 任务1(2026-08-02): estHistory 也按 _pfCutoff 过滤, 否则 3m/6m 窗口 allDates 起点被拉到 20251222,
  // 而红线 posMap 只含 cutoff 后 lg 点, [20251222~cutoff后首lg点] 整段全 null 致视觉断线(connectNulls 救不了全段null)
  const _estHistRaw = (estimate && Array.isArray(estimate.history)) ? estimate.history : [];
  const _estHist = _estHistRaw.filter((h) => {
    const d = (h.date || "").replace(/-/g, "");
    return !_pfCutoff || d >= _pfCutoff;
  });
  const estPoints = _estHist.map((h) => [(h.date || "").replace(/-/g, ""), h.position]);
  const estMap = new Map(estPoints);
  const _estCurDate = _estCur ? (_estCur.date || "").replace(/-/g, "") : "";  // 末端点日期 YYYYMMDD, tooltip 追加偏差
  const allDates = [...new Set([...posPoints.map((p) => p[0]), ...shPoints.map((p) => p[0]), ...estPoints.map((p) => p[0])])].sort();
  const posMap = new Map(posPoints), shMap = new Map(shPoints);

  // G功能: markPoint 标历史极值(88魔咒高点 Top5 + 80抄底低点 Top5)
  // backtest.extremes.highs/lows 日期格式 "2025-08-15", 需转 "20250815" 匹配 xAxis category
  // 融合方案A: pin label 只显示精简标识, 完整说明由 axis tooltip formatter 统一展开(查 _pinDateMap), 一套浮窗
  const _btDateToCoord = (d) => (d || "").replace(/-/g, "");
  // 融合方案A: pin label 只显示精简标识(日期+高96%), 完整说明(类型+仓位+沪深300+后30/60/90天)
  // 统一由 axis tooltip formatter 展开(查 _pinDateMap), 一套浮窗一套样式, 不再用 emphasis label 黑底浮窗
  const _btMarkData = (arr, color, labelPrefix) => {
    if (!arr || !arr.length) return [];
    return arr.map((e) => ({
      coord: [_btDateToCoord(e.date), e.position],
      value: `${labelPrefix}${e.position.toFixed(2)}%`,
      itemStyle: { color },
      label: {
        show: true, color: "#fff", fontSize: 10,
        formatter: `{b|${e.date}}\n{a|${labelPrefix}${e.position}%}`,
        rich: { b: { fontSize: 9, color: "#fff", lineHeight: 12 }, a: { fontSize: 11, color: "#fff", fontWeight: 700 } },
      },
    }));
  };
  const _highsMark = backtest && backtest.extremes && backtest.extremes.highs
    ? _btMarkData(backtest.extremes.highs, "#e6492e", "88高") : [];
  const _lowsMark = backtest && backtest.extremes && backtest.extremes.lows
    ? _btMarkData(backtest.extremes.lows, "#2e8b57", "80低") : [];

  // 融合方案A: 建 pin 日期 Map(YYYYMMDD -> pin 完整信息), axis tooltip formatter 查 Map
  // 命中则追加完整 pin 说明(类型+仓位+沪深300+后30/60/90天), 未命中只显示该日仓位+沪深300
  const _retStr = (v) => (v == null ? "-" : (v > 0 ? "+" : "") + v.toFixed(2) + "%");
  const _pinDateMap = new Map();
  if (backtest && backtest.extremes) {
    const _fillPin = (arr, desc, color) => {
      if (!arr) return;
      arr.forEach((e) => _pinDateMap.set(_btDateToCoord(e.date), { desc, color, date: e.date, position: e.position, close: e.close, after_30d: e.after_30d, after_60d: e.after_60d, after_90d: e.after_90d }));
    };
    _fillPin(backtest.extremes.highs, "⚠ 88魔咒历史高点 Top5(红色标记)", "#e6492e");
    _fillPin(backtest.extremes.lows, "✓ 80抄底低点 Top5(绿色标记)", "#2e8b57");
  }

  mainChart.setOption({
    tooltip: {
      trigger: "axis", axisPointer: { type: "cross" },
      formatter: (params) => {
        if (!params || !params.length) return "";
        const dt = params[0].axisValue; // YYYYMMDD
        let html = `<div style="font-weight:600;margin-bottom:4px">${_pfFmtDate(dt)}</div>`;
        params.forEach((p) => {
          if (p.value == null || isNaN(Number(p.value))) return;
          const unit = (p.seriesName === "平均仓位%" || p.seriesName === "今日预估仓位%") ? "%" : "";
          html += `<div style="display:flex;align-items:center;gap:6px"><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${p.color}"></span><span style="flex:1">${p.seriesName}</span><b style="font-variant-numeric:tabular-nums">${Number(p.value).toFixed(2)}${unit}</b></div>`;
        });
        // 末端预估点: 追加偏差说明(vs lg + confidence), 和 pin 共用同一浮窗
        if (_estCur && dt === _estCurDate) {
          html += `<div style="margin-top:6px;padding-top:6px;border-top:1px solid rgba(255,255,255,0.2);color:#ff9800;font-weight:600;font-size:11px">📌 今日预估 ${_estCur.position_estimate}%（日频线性回归，可信度：${_confZh(_estCur.confidence)}）</div>`;
          html += `<div style="font-size:11px;color:#bbb;margin-top:2px">较乐咕乐股周频 ${_estCur.lg_latest_position}%（${_estCur.lg_latest_date}）· 偏差 ${_estCur.deviation_from_lg > 0 ? "+" : ""}${_estCur.deviation_from_lg}%</div>`;
        }
        // 命中 pin 日期: 追加完整说明(类型+仓位+沪深300+后30/60/90天涨跌), 和普通点共用同一浮窗
        const pin = _pinDateMap.get(dt);
        if (pin) {
          const _retColor = (v) => (v == null ? "#aaa" : v > 0 ? "#e6492e" : v < 0 ? "#2e8b57" : "#aaa");
          html += `<div style="margin-top:6px;padding-top:6px;border-top:1px solid rgba(255,255,255,0.2);color:${pin.color};font-weight:600;font-size:11px">${pin.desc}</div>`;
          html += `<div style="font-size:11px;color:#bbb;margin-top:2px">仓位 ${pin.position}%  沪深300 ${pin.close}</div>`;
          html += `<div style="font-size:11px;color:#bbb;margin-top:2px">后30天 <b style="color:${_retColor(pin.after_30d)}">${_retStr(pin.after_30d)}</b>  后60天 <b style="color:${_retColor(pin.after_60d)}">${_retStr(pin.after_60d)}</b>  后90天 <b style="color:${_retColor(pin.after_90d)}">${_retStr(pin.after_90d)}</b></div>`;
        }
        return html;
      },
    },
    legend: { data: ["平均仓位%", "今日预估仓位%", "沪深300"], top: 5, textStyle: { color: "var(--text-2)" } },
    grid: { left: 60, right: 60, top: 40, bottom: 30 },
    xAxis: { type: "category", data: allDates, axisLabel: { formatter: (v) => _pfFmtDate(v).slice(5), fontSize: 10 } },
    yAxis: [
      { type: "value", name: "仓位%", min: 80, max: 100, position: "left", axisLabel: { formatter: "{value}%" } },
      { type: "value", name: "沪深300", min: Math.floor(shMin * 0.95), max: Math.ceil(shMax * 1.05), position: "right", scale: true, axisLabel: { formatter: "{value}" } },
    ],
    series: [
      {
        name: "平均仓位%", type: "line", data: allDates.map((d) => posMap.has(d) ? posMap.get(d) : null), yAxisIndex: 0,
        symbol: "circle", symbolSize: 5, connectNulls: true,
        lineStyle: { color: "#e6492e", width: 2 }, itemStyle: { color: "#e6492e" },
        markLine: {
          silent: true, symbol: "none", lineStyle: { type: "dashed", width: 1.5 },
          data: [
            { yAxis: 88, lineStyle: { color: "#e6492e" }, label: { formatter: "88 魔咒", color: "#e6492e", position: "insideStartTop", fontSize: 10 } },
            { yAxis: 80, lineStyle: { color: "#2e8b57" }, label: { formatter: "80 抄底", color: "#2e8b57", position: "insideStartBottom", fontSize: 10 } },
          ],
        },
        // G功能: markPoint 标历史极值(红=88魔咒高点Top5, 绿=80抄底低点Top5)
        markPoint: {
          symbol: "pin", symbolSize: 48,
          data: [..._highsMark, ..._lowsMark],
        },
      },
      // 今日预估仓位%(日频 OLS 预估, 补 lg 周频滞后): history 147期时序虚线 + 末端 markPoint 标 current
      // 橙色虚线区别于 lg 红实线; 末端 markPoint 醒目标"今日预估 95.01%" + 副标注"vs lg 96.01% 偏差-1.0%"
      {
        name: "今日预估仓位%", type: "line",
        data: allDates.map((d) => estMap.has(d) ? estMap.get(d) : null), yAxisIndex: 0,
        symbol: "none", connectNulls: true,
        lineStyle: { color: "#ff9800", width: 2, type: "dashed" }, itemStyle: { color: "#ff9800" },
        markPoint: _estCur ? {
          symbol: "pin", symbolSize: 48,
          data: [{
            coord: [_estCurDate, _estCur.position_estimate],
            itemStyle: { color: "#ff9800" },
            label: {
              color: "#fff", fontSize: 11,
              formatter: `{a|今日预估 ${_estCur.position_estimate}%}\n{b|较乐咕乐股源 ${_estCur.lg_latest_position}% 偏差${_estCur.deviation_from_lg > 0 ? "+" : ""}${_estCur.deviation_from_lg}%}`,
              rich: {
                a: { fontSize: 11, color: "#fff", fontWeight: 700, lineHeight: 14 },
                b: { fontSize: 9, color: "#fff", lineHeight: 12 },
              },
            },
          }],
        } : undefined,
      },
      {
        name: "沪深300", type: "line", data: allDates.map((d) => shMap.has(d) ? shMap.get(d) : null), yAxisIndex: 1,
        symbol: "none", connectNulls: true, lineStyle: { color: "#888", width: 1.5 }, itemStyle: { color: "#888" },
      },
    ],
  });

  // ── G功能: 88魔咒历史回测统计面板 ──
  // backtest.stats: spell_88(>88%触发次数+胜率+30/60/90d平均涨跌) + dip_80(<80%触发次数+...)
  // backtest.current: 当前仓位+区间+历史分位
  if (backtest && backtest.stats) {
    const _s88 = backtest.stats.spell_88 || {};
    const _s80 = backtest.stats.dip_80 || {};
    const _cur = backtest.current || {};
    const _pctFmt = (v) => (v == null ? "-" : `${(v * 100).toFixed(1)}%`);
    const _retFmt = (v) => (v == null ? "-" : `${v > 0 ? "+" : ""}${v.toFixed(2)}%`);
    const _retColor = (v) => (v == null ? "var(--text-3)" : v > 0 ? "#e6492e" : v < 0 ? "#2e8b57" : "var(--text-3)");
    const _zoneColor = _cur.zone === "88魔咒" ? "#e6492e" : _cur.zone === "80抄底" ? "#2e8b57" : "#ff9800";
    // 时效标注: 把 "2026-07-24" 格式化成 "07/24" 供每行小字标注数据时点(当前仓位/历史分位/沪深300收盘用 _cur.date lg周频; 今日预估用 _estCur.date 当日实时)
    const _fmtMd = (s) => { if (!s) return ""; const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s); return m ? `${m[2]}/${m[3]}` : s; };
    const btCard = document.createElement("div");
    btCard.className = "chart-card pf-backtest-card";
    btCard.innerHTML = `
      <div class="chart-title">🎯 88 魔咒历史回测（${_s88.sample_30d || 0}/${_s88.count || 0} 期有效样本 · 2007-2026 乐咕乐股源 ${posHist.length} 期周频）</div>
      <div class="pf-bt-grid">
        <div class="pf-bt-section pf-bt-spell88">
          <div class="pf-bt-head" style="color:#e6492e">⚠ 88 魔咒（仓位 &gt; 88%）</div>
          <div class="pf-bt-row"><span>触发次数</span><b>${_s88.count || 0} 期</b></div>
          <div class="pf-bt-row"><span>30 天下跌胜率</span><b style="color:#e6492e">${_pctFmt(_s88.win_rate)}</b></div>
          <div class="pf-bt-row"><span>后 30 天平均</span><b style="color:${_retColor(_s88.avg_30d)}">${_retFmt(_s88.avg_30d)}</b></div>
          <div class="pf-bt-row"><span>后 60 天平均</span><b style="color:${_retColor(_s88.avg_60d)}">${_retFmt(_s88.avg_60d)}</b></div>
          <div class="pf-bt-row"><span>后 90 天平均</span><b style="color:${_retColor(_s88.avg_90d)}">${_retFmt(_s88.avg_90d)}</b></div>
        </div>
        <div class="pf-bt-section pf-bt-dip80">
          <div class="pf-bt-head" style="color:#2e8b57">✓ 80 抄底（仓位 &lt; 80%）</div>
          <div class="pf-bt-row"><span>触发次数</span><b>${_s80.count || 0} 期</b></div>
          <div class="pf-bt-row"><span>30 天上涨胜率</span><b style="color:#2e8b57">${_pctFmt(_s80.win_rate)}</b></div>
          <div class="pf-bt-row"><span>后 30 天平均</span><b style="color:${_retColor(_s80.avg_30d)}">${_retFmt(_s80.avg_30d)}</b></div>
          <div class="pf-bt-row"><span>后 60 天平均</span><b style="color:${_retColor(_s80.avg_60d)}">${_retFmt(_s80.avg_60d)}</b></div>
          <div class="pf-bt-row"><span>后 90 天平均</span><b style="color:${_retColor(_s80.avg_90d)}">${_retFmt(_s80.avg_90d)}</b></div>
        </div>
        <div class="pf-bt-section pf-bt-current">
          <div class="pf-bt-head" style="color:${_zoneColor}">📍 当前状态（${_cur.date || "-"}）</div>
          <div class="pf-bt-row"><span>当前仓位</span><b style="color:${_zoneColor}">${_cur.position != null ? _cur.position.toFixed(2) + "%" : "-"}<small class="pf-bt-time">·lg周频 ${_fmtMd(_cur.date)}</small></b></div>
          <div class="pf-bt-row"><span>今日预估</span><b style="color:#ff9800">${_estCur && _estCur.position_estimate != null ? _estCur.position_estimate.toFixed(2) + `%<small class="pf-bt-time">·今日实时${_estCur.date ? " " + _fmtMd(_estCur.date) : ""}</small>` : "-"}</b></div>
          <div class="pf-bt-row"><span>所处区间</span><b style="color:${_zoneColor}">${_cur.zone || "-"}<small class="pf-bt-time">·同仓位 ${_fmtMd(_cur.date)}</small></b></div>
          <div class="pf-bt-row"><span>历史分位</span><b>${_pctFmt(_cur.percentile)}<small class="pf-bt-time">·截至 ${_fmtMd(_cur.date)}</small></b></div>
          <div class="pf-bt-row"><span>沪深300收盘</span><b>${_cur.close != null ? _cur.close.toFixed(2) : "-"}<small class="pf-bt-time">·${_fmtMd(_cur.date)}收盘</small></b></div>
        </div>
      </div>
      <div class="pf-bt-note"><span style="color:#e6492e;font-size:14px;vertical-align:middle">●</span> 红色水滴标记 = 历史仓位 Top5 高点(88 魔咒触发点) · <span style="color:#2e8b57;font-size:14px;vertical-align:middle">●</span> 绿色水滴标记 = Top5 低点(80 抄底信号点) · 胜率=触发后 30 天沪深300下跌(88)/上涨(80)占比</div>
      <div class="pf-bt-note pf-bt-howto">💡 <b>怎么看</b>：<b style="color:#e6492e">88魔咒区(>88%)</b>传统看跌但胜率仅${_pctFmt(_s88.win_rate)}接近随机<b style="color:#e6492e">不可靠</b>；<b style="color:#2e8b57">抄底区(<80%)</b>看涨胜率${_pctFmt(_s80.win_rate)}+90天平均${_retFmt(_s80.avg_90d)}<b style="color:#2e8b57">更可靠</b>；中性区(80-88%)无明确信号。当前${_cur.position != null ? _cur.position.toFixed(2) + "%" : "-"}=${_cur.zone || "-"}·历史分位${_pctFmt(_cur.percentile)}</div>
    `;
    container.appendChild(btCard);
  }

  // ── N功能: 多信号共振仪表盘（4信号季频叠加 + 共振标注 + 后续市场表现统计）──
  // 信号: 88魔咒(avg_position 周频→季频对齐) + 净申赎(net_purchase_share 季频) + 抱团度(herfindahl 季频) + 规模(end_net_asset 季频)
  // 对齐基准: 抱团度日期(10期 2023Q4-2026Q2); 88魔咒取季末最近一期 lg 源值
  // 共振: 看顶=88魔咒>88+净申购(散户乐观反向看空)+抱团>中位数+规模高位; 看底=88魔咒<80+净赎回(散户悲观反向看多)+抱团<中位数
  // 后续表现: 复用 shIndex.ohlc close 时序算 after_30/60/90d 涨跌
  let _nfScaleTs = null, _nfConcTs = null;
  try {
    [_nfScaleTs, _nfConcTs] = await Promise.all([
      fetchJSON("https://ssd.fx8.store/public_fund/public_fund_scale_change_ts.json").catch(() => null),
      fetchJSON("https://ssd.fx8.store/public_fund/public_fund_holding_concentration_ts.json").catch(() => null),
    ]);
  } catch (e) { /* N功能面板不渲染, 不阻塞后续 Top30/行业 */ }

  if (_nfScaleTs && _nfScaleTs.series && _nfConcTs && _nfConcTs.series && _nfConcTs.series.length && posHist.length) {
    // 1. 季度对齐: 抱团度日期(季频)为基准, 88魔咒取季末最近一期, 净申赎/规模直接用 date
    const _scMap = new Map((_nfScaleTs.series || []).map((s) => [s.date, s]));
    const _quarters = (_nfConcTs.series || []).map((s) => s.date).sort(); // 10期季频
    const _pfQuarterAlign = (qEndDate) => {
      let best = null;
      for (const h of posHist) { if (h.report_date <= qEndDate) best = h; else break; }
      return best;
    };
    const _alignData = _quarters.map((q) => {
      const sc = _scMap.get(q);
      const conc = _nfConcTs.series.find((s) => s.date === q);
      const pf = _pfQuarterAlign(q);
      if (!sc || !conc || !pf) return null;
      return {
        date: q,
        avgPosition: pf.position_pct,
        netPurchase: sc.net_purchase_share,
        endNetAsset: sc.end_net_asset,
        herfindahl: conc.herfindahl,
      };
    }).filter(Boolean);

    if (_alignData.length >= 2) {
      // 3. 共振时点后续市场表现(复用 shIndex.ohlc close 日频时序) - 窗口无关, 计算一次
      const _shClose = (shIndex && shIndex.ohlc) ? shIndex.ohlc.map((d) => ({ date: d.date, close: d.close })).filter((d) => d.close != null) : [];
      const _afterReturn = (startDate, days) => {
        if (!_shClose.length) return null;
        const _start = _shClose.find((d) => d.date >= startDate);
        if (!_start) return null;
        const _sd = new Date(startDate.slice(0, 4) + "-" + startDate.slice(4, 6) + "-" + startDate.slice(6, 8));
        _sd.setDate(_sd.getDate() + days);
        const _target = _sd.getFullYear() + String(_sd.getMonth() + 1).padStart(2, "0") + String(_sd.getDate()).padStart(2, "0");
        const _end = _shClose.find((d) => d.date >= _target);
        if (!_end) return null;
        return (_end.close - _start.close) / _start.close * 100;
      };

      // 4. 渲染面板容器(含时间窗口切换器 - 追加2; 副标题精简不截断 - 追加1)
      const _nfCard = document.createElement("div");
      _nfCard.className = "chart-card pf-nf-card";
      _nfCard.innerHTML = '<div class="chart-title">🎯 多信号共振仪表盘（4信号季频对齐 · <span class="pf-nf-period">' + _alignData.length + ' 期</span>）'
        + '<span class="pf-nf-range"><button class="pf-rot-range-btn" data-nf-rng="3m" type="button">3月</button>'
        + '<button class="pf-rot-range-btn" data-nf-rng="6m" type="button">6月</button>'
        + '<button class="pf-rot-range-btn" data-nf-rng="1y" type="button">1年</button>'
        + '<button class="pf-rot-range-btn active" data-nf-rng="all" type="button">全部</button></span></div>'
        + '<div class="chart-subtitle" style="font-size:11px;color:var(--text-3);margin:0 0 6px 0;line-height:1.6;word-break:break-word;overflow:visible">'
        + '📊 4信号: <span style="color:#e6492e">88魔咒(仓位%)</span> · <span style="color:#ff9800">净申赎(亿份)</span> · <span style="color:#9c27b0">抱团度HHI(赫芬达尔)×1k</span> · <span style="color:#2196f3">规模(亿)</span><br>'
        + '共振 🔴看顶(仓位>88+净申购+高抱团+规模高位) 🟢看底(仓位<80+净赎回+低抱团) · 88魔咒周频对齐季频(取季末最近期值)</div>'
        + '<div class="chart" style="height:420px"></div>'
        + '<div class="pf-nf-resonance"></div>';
      container.appendChild(_nfCard);

      // 5. echarts 4 y 轴时序叠加
      const _nfChart = echarts.init(_nfCard.querySelector(".chart"));
      charts.push(_nfChart);
      const _periodEl = _nfCard.querySelector(".pf-nf-period");
      const _resDiv = _nfCard.querySelector(".pf-nf-resonance");
      const _retFmt = (v) => (v == null ? "-" : (v > 0 ? "+" : "") + v.toFixed(2) + "%");
      const _retColor = (v) => (v == null ? "var(--text-3)" : v > 0 ? "#e6492e" : v < 0 ? "#2e8b57" : "var(--text-3)");

      // 追加2: 时间窗口切换 - 按 cutoff 过滤 _alignData 重算共振+重渲染(季频3m≈2期/6m≈3期/1y≈5期/all=全量)
      function _nfRender(range) {
        const _cutoff = _signalModalCutoff(_alignData.map((d) => ({ date: d.date, value: d.avgPosition })), range);
        const _win = _cutoff ? _alignData.filter((d) => d.date >= _cutoff) : _alignData.slice();
        // 2. 共振判断(基于窗口数据重算中位数+共振)
        const _herfVals = _win.map((d) => d.herfindahl).filter((v) => v != null).sort((a, b) => a - b);
        const _herfMedian = _herfVals.length ? _herfVals[Math.floor(_herfVals.length / 2)] : 0.015;
        let _maxAsset = 0;
        const _resonancePoints = [];
        for (const d of _win) {
          if (d.endNetAsset != null && d.endNetAsset > _maxAsset) _maxAsset = d.endNetAsset;
          // 看顶: 88魔咒>88 + 净申购(散户乐观>0 反向看空) + 抱团>中位数 + 规模接近最高(>95%)
          const _isTop = d.avgPosition > 88 && d.netPurchase != null && d.netPurchase > 0
            && d.herfindahl != null && d.herfindahl > _herfMedian
            && d.endNetAsset != null && _maxAsset > 0 && d.endNetAsset >= _maxAsset * 0.95;
          // 看底: 88魔咒<80 + 净赎回(散户悲观<0 反向看多) + 抱团<中位数
          const _isBottom = d.avgPosition < 80 && d.netPurchase != null && d.netPurchase < 0
            && d.herfindahl != null && d.herfindahl < _herfMedian;
          if (_isTop || _isBottom) _resonancePoints.push({ ...d, type: _isTop ? "top" : "bottom" });
        }
        for (const rp of _resonancePoints) {
          rp.after_30d = _afterReturn(rp.date, 30);
          rp.after_60d = _afterReturn(rp.date, 60);
          rp.after_90d = _afterReturn(rp.date, 90);
        }
        // 更新标题期数+区间
        const _d0 = _pfFmtDate(_win[0].date).slice(0, 7);
        const _dN = _pfFmtDate(_win[_win.length - 1].date).slice(0, 7);
        _periodEl.textContent = _win.length + ' 期 · ' + _d0 + ' ~ ' + _dN;
        // echarts setOption(notMerge=true 全量替换, 切窗口清旧 series/markPoint)
        const _dates = _win.map((d) => d.date);
        const _posData = _win.map((d) => d.avgPosition);
        const _netData = _win.map((d) => d.netPurchase);
        const _herfData = _win.map((d) => d.herfindahl != null ? +(d.herfindahl * 1000).toFixed(2) : null);
        const _assetData = _win.map((d) => d.endNetAsset);
        const _resMark = _resonancePoints.map((rp) => ({
          coord: [rp.date, rp.avgPosition],
          value: rp.type === "top" ? "看顶" : "看底",
          itemStyle: { color: rp.type === "top" ? "#e6492e" : "#2e8b57" },
          label: { color: "#fff", fontSize: 10, formatter: "{b|" + (rp.type === "top" ? "顶" : "底") + "}",
            rich: { b: { fontSize: 11, color: "#fff", fontWeight: 700 } } },
        }));
        _nfChart.setOption({
          tooltip: { trigger: "axis", axisPointer: { type: "cross" } },
          legend: { data: ["88魔咒仓位%", "净申赎(亿份)", "抱团度HHI×1k", "规模(亿)"], top: 5, textStyle: { color: "var(--text-2)" } },
          grid: { left: 60, right: 90, top: 50, bottom: 30 },
          xAxis: { type: "category", data: _dates, axisLabel: { formatter: (v) => _pfFmtDate(v).slice(2, 7), fontSize: 10 } },
          yAxis: [
            { type: "value", name: "仓位%", min: 75, max: 100, position: "left", axisLabel: { formatter: "{value}%" } },
            { type: "value", name: "净申赎", position: "right", axisLabel: { formatter: "{value}" } },
            { type: "value", name: "HHI×1k", position: "right", offset: 45, axisLabel: { formatter: "{value}" } },
            { type: "value", name: "规模亿", position: "right", offset: 90, axisLabel: { formatter: "{value}" } },
          ],
          series: [
            { name: "88魔咒仓位%", type: "line", data: _posData, yAxisIndex: 0,
              symbol: "circle", symbolSize: 6, connectNulls: true,
              lineStyle: { color: "#e6492e", width: 2.5 }, itemStyle: { color: "#e6492e" },
              markLine: { silent: true, symbol: "none", lineStyle: { type: "dashed", width: 1.5 }, data: [
                { yAxis: 88, lineStyle: { color: "#e6492e" }, label: { formatter: "88", color: "#e6492e", fontSize: 10 } },
                { yAxis: 80, lineStyle: { color: "#2e8b57" }, label: { formatter: "80", color: "#2e8b57", fontSize: 10 } },
              ]},
              markPoint: { symbol: "pin", symbolSize: 42, data: _resMark },
            },
            { name: "净申赎(亿份)", type: "line", data: _netData, yAxisIndex: 1,
              symbol: "diamond", symbolSize: 5, connectNulls: true,
              lineStyle: { color: "#ff9800", width: 1.5 }, itemStyle: { color: "#ff9800" } },
            { name: "抱团度HHI×1k", type: "line", data: _herfData, yAxisIndex: 2,
              symbol: "triangle", symbolSize: 5, connectNulls: true,
              lineStyle: { color: "#9c27b0", width: 1.5 }, itemStyle: { color: "#9c27b0" } },
            { name: "规模(亿)", type: "line", data: _assetData, yAxisIndex: 3,
              symbol: "none", connectNulls: true,
              lineStyle: { color: "#2196f3", width: 1.5 }, itemStyle: { color: "#2196f3" } },
          ],
        }, true);
        // 6. 共振统计面板
        let _resHtml = "";
        if (_resonancePoints.length) {
          _resHtml = '<div class="pf-nf-res-grid">';
          for (const rp of _resonancePoints) {
            const _color = rp.type === "top" ? "#e6492e" : "#2e8b57";
            const _label = rp.type === "top" ? "🔴 看顶共振" : "🟢 看底共振";
            _resHtml += '<div class="pf-bt-section" style="border-left:4px solid ' + _color + '">'
              + '<div class="pf-bt-head" style="color:' + _color + '">' + _label + ' · ' + _pfFmtDate(rp.date).slice(0, 7) + '</div>'
              + '<div class="pf-bt-row"><span>88魔咒仓位</span><b style="color:' + _color + '">' + rp.avgPosition.toFixed(2) + '%</b></div>'
              + '<div class="pf-bt-row"><span>净申赎</span><b>' + (rp.netPurchase != null ? rp.netPurchase.toFixed(2) + " 亿份" : "-") + '</b></div>'
              + '<div class="pf-bt-row"><span>抱团度HHI</span><b>' + (rp.herfindahl != null ? rp.herfindahl.toFixed(4) : "-") + '</b></div>'
              + '<div class="pf-bt-row"><span>规模</span><b>' + (rp.endNetAsset != null ? rp.endNetAsset.toFixed(0) + " 亿" : "-") + '</b></div>'
              + '<div class="pf-bt-row"><span>后30天沪深300</span><b style="color:' + _retColor(rp.after_30d) + '">' + _retFmt(rp.after_30d) + '</b></div>'
              + '<div class="pf-bt-row"><span>后60天沪深300</span><b style="color:' + _retColor(rp.after_60d) + '">' + _retFmt(rp.after_60d) + '</b></div>'
              + '<div class="pf-bt-row"><span>后90天沪深300</span><b style="color:' + _retColor(rp.after_90d) + '">' + _retFmt(rp.after_90d) + '</b></div>'
              + '</div>';
          }
          _resHtml += '</div>';
          _resHtml += '<div class="pf-bt-note">📌 看顶=88魔咒>88%+净申购(散户乐观反向看空)+抱团>中位数('+ _herfMedian.toFixed(4) +')+规模接近最高; 看底=88魔咒<80%+净赎回(散户悲观反向看多)+抱团<中位数 · 后续表现从沪深300日频收盘价计算(30/60/90天最近收盘价涨跌%)</div>';
        } else {
          _resHtml = '<div class="pf-bt-note">📌 当前' + _win.length + '期数据无共振时点(4信号未同时触发看顶/看底条件) · 抱团度HHI中位数=' + _herfMedian.toFixed(4) + ' · 88魔咒平均=' + (_win.reduce((s, d) => s + d.avgPosition, 0) / _win.length).toFixed(2) + '%</div>';
        }
        if (_win.length < 3) {
          _resHtml += '<div class="pf-bt-note" style="color:#ff9800">⚠️ 季频数据窗口内仅 ' + _win.length + ' 期, 信号参考性有限, 建议用更长窗口</div>';
        }
        _resDiv.innerHTML = _resHtml;
      }
      _nfRender("all");
      // 窗口按钮点击(追加2)
      _nfCard.querySelectorAll('button[data-nf-rng]').forEach((b) => {
        b.addEventListener("click", () => {
          _nfCard.querySelectorAll('button[data-nf-rng]').forEach((x) => x.classList.remove("active"));
          b.classList.add("active");
          _nfRender(b.dataset.nfRng);
        });
      });
    }
  }

  // ── 区域 3: Top30 重仓表(左) + 行业柱状图(右) 两栏 ──
  const twoCol = document.createElement("div");
  twoCol.className = "pf-two-col";
  container.appendChild(twoCol);

  // 左: Top30 重仓表(按持仓市值排序前30, 原维度保留; 含调仓: 当期 vs 上期, Q2)
  const top30Card = document.createElement("div");
  top30Card.className = "chart-card pf-top30-card";
  const top30 = (holdings && holdings.top100 ? holdings.top100 : []).slice(0, 30);
  const holdingsPrevDate = holdings && holdings.prev_report_date ? _pfFmtDate(holdings.prev_report_date) : "";
  let top30Rows = "";
  top30.forEach((s, i) => {
    const chgColor = s.change_pct > 0 ? "#e6492e" : s.change_pct < 0 ? "#2e8b57" : "var(--text-3)";
    const chgArrow = s.change_pct > 0 ? "↑" : s.change_pct < 0 ? "↓" : "->";
    const chgTxt = s.change_pct == null ? "-" : `${chgArrow} ${Math.abs(s.change_pct).toFixed(2)}%`;
    const tip = s.prev_value == null ? "无上期数据" : `当期 ${(s.hold_value_total / 1e4).toFixed(2)} 万 / 上期 ${(s.prev_value / 1e4).toFixed(2)} 万`;
    const indTxt = s.stock_industry ? `<span class="pf-ind-tag">${s.stock_industry}</span>` : '<span style="color:var(--text-3)">-</span>';
    top30Rows += `<tr>
      <td>${i + 1}</td>
      <td class="pf-code">${s.stock_code}</td>
      <td>${s.stock_name}</td>
      <td>${indTxt}</td>
      <td class="pf-num">${s.fund_count}</td>
      <td class="pf-num">${(s.hold_value_total / 1e4).toFixed(2)}</td>
      <td class="pf-num" style="color:${chgColor};font-weight:600" title="${tip}">${chgTxt}</td>
    </tr>`;
  });
  top30Card.innerHTML = `<div class="chart-title">🏆 重仓股 Top30（持有基金数 / 持仓市值万元 / 调仓${holdingsPrevDate ? " 较 " + holdingsPrevDate : ""}）</div>
    <div class="pf-table-wrap"><table class="pf-table">
      <thead><tr><th>#</th><th>代码</th><th>名称</th><th>行业</th><th>基金数</th><th>市值(万)</th><th>调仓</th></tr></thead>
      <tbody>${top30Rows || '<tr><td colspan="7">暂无数据</td></tr>'}</tbody>
    </table></div>`;
  twoCol.appendChild(top30Card);

  // 右: 行业配置柱状图(Top15+其他聚合) + TreeMap 全景(合并重复分类后全行业)
  // 合并映射表: 67 行业 = 申万中文大类 + GICS中文短名 + GICS带编号 + GICS中英文 多套分类混合, 归并为标准名
  // 合并时 weight/value/fundCount 累加(同基金多分类会重复计 fundCount, 仅作展示用)
  const IND_MERGE_MAP = {
    '信息传输、软件和信息技术服务业': '信息技术', '信息技术': '信息技术', '信息科技': '信息技术',
    '45信息技术': '信息技术', '信息技术InformationTechnology': '信息技术', '科技': '信息技术',
    '金融业': '金融业', '金融': '金融业', '40金融': '金融业', 'E金融': '金融业', '金融Financials': '金融业',
    '房地产业': '房地产业', '房地产': '房地产业', '房地产RealEstate': '房地产业', '60房地产': '房地产业', '地产业': '房地产业',
    '材料': '材料', '原材料': '材料', '15原材料': '材料', '材料Materials': '材料', '基础材料': '材料',
    '工业': '工业', '20工业': '工业', 'G工业': '工业', '工业Industrials': '工业',
    '能源': '能源', 'D能源': '能源',
    '公用事业': '公用事业', 'J公用事业': '公用事业',
    '医疗保健': '医疗保健', '医疗': '医疗保健', '35医疗保健': '医疗保健', '保健HealthCare': '医疗保健',
    '非日常生活消费品': '非必需消费品', '非必需消费品': '非必需消费品', '25可选消费': '非必需消费品',
    '非必需消费品ConsumerDiscretionary': '非必需消费品', '消费者非必需品': '非必需消费品', '非周期性消费品': '非必需消费品',
    '必需消费品': '必需消费品', '日常消费品': '必需消费品', '30日常消费': '必需消费品',
    '必需消费品ConsumerStaples': '必需消费品', '消费者常用品': '必需消费品',
    '通讯': '通信服务', '通讯业务': '通信服务', '通信服务': '通信服务',
    '50电信服务': '通信服务', '电信服务': '通信服务', '电信业务': '通信服务', '通信服务CommunicationServices': '通信服务',
  };
  // 口径分类映射(合并后标准名 -> 'csrc'|'gics'|'both'): 用于"证监会/GICS双口径切换"
  // 背景: fund_industry_alloc.industry_name 是多套分类混合--A股基金按证监会门类披露,
  // QDII/港股基金按GICS披露。合并后标准名按主要来源打口径标签:
  //   csrc = 证监会门类(制造业/采矿业/批发零售等19大门类, A股基金披露口径)
  //   gics = GICS 11大类(能源/材料/工业等, QDII基金披露口径)
  //   both = 合并后标准名同时含CSRC和GICS来源(信息技术/金融业/房地产业; 切换任一视图都显示)
  // 制造业=纯csrc(证监会门类最粗,涵盖电子/通信/汽车等所有制造类); 通信服务=纯gics(GICS独立大类)
  // ⚠️ "通信"(制造业子行业,通信设备制造) ≠ "通信服务"(GICS独立大类,通信运营服务), 二者口径不同
  const IND_CLASSIFICATION = {
    // CSRC 证监会门类(A股基金披露口径, 19大门类)
    '制造业': 'csrc', '采矿业': 'csrc', '批发和零售业': 'csrc', '交通运输、仓储和邮政业': 'csrc',
    '科学研究和技术服务业': 'csrc', '电力、热力、燃气及水生产和供应业': 'csrc',
    '水利、环境和公共设施管理业': 'csrc', '建筑业': 'csrc', '租赁和商务服务业': 'csrc',
    '文化、体育和娱乐业': 'csrc', '卫生和社会工作': 'csrc', '农、林、牧、渔业': 'csrc',
    '住宿和餐饮业': 'csrc', '教育': 'csrc', '综合': 'csrc',
    '居民服务、修理和其他服务业': 'csrc',
    // GICS 11大类(QDII/港股基金披露口径)
    '能源': 'gics', '材料': 'gics', '工业': 'gics', '医疗保健': 'gics',
    '非必需消费品': 'gics', '必需消费品': 'gics', '通信服务': 'gics', '公用事业': 'gics',
    // both: 合并后标准名同时含CSRC和GICS来源(切换任一视图都显示, tooltip 标注双口径)
    '信息技术': 'both',   // CSRC"信息传输、软件和信息技术服务业" + GICS"45信息技术"等
    '金融业': 'both',     // CSRC"金融业" + GICS"40金融"等
    '房地产业': 'both',   // CSRC"房地产业" + GICS"60房地产"等
  };
  // 兜底: 不在表里的标准名(如动态聚合的"其他")默认 both(切换任一视图都显示, 避免长尾丢失)
  const _classifyInd = (name) => IND_CLASSIFICATION[name] || 'both';
  const _rawInd = (industry && industry.industries ? industry.industries : []);
  const _mergedMap = new Map();
  for (const d of _rawInd) {
    const name = IND_MERGE_MAP[d.industry_name] || d.industry_name;
    if (!_mergedMap.has(name)) _mergedMap.set(name, { name, weight: 0, value: 0, fundCount: 0, industryCount: 0, breakdown: null });
    const m = _mergedMap.get(name);
    m.weight += d.total_weight || 0;
    m.value += d.total_value || 0;
    m.fundCount += d.fund_count || 0;
    m.industryCount += 1;
    // 制造业子行业 breakdown 传递(方案C Step4: 仅制造业有 breakdown 来自重仓股拆分, 其他行业 null)
    if (d.breakdown && d.breakdown.length) m.breakdown = d.breakdown;
  }
  const indDataAll = Array.from(_mergedMap.values()).sort((a, b) => b.weight - a.weight);
  let indData = indDataAll;  // 当前显示的行业(口径切换时过滤: all=全部 / csrc=证监会 / gics=GICS)
  let indClass = 'all';  // 口径切换状态: all/csrc/gics
  // indTotalWeight 用全集(切换口径不重算, 保持"占全行业%"稳定, 避免 both 双计)
  // 'sw' 申万一级档换数据源, 切换时重算 indTotalWeight(sw 数据总和)
  let indTotalWeight = indDataAll.reduce((s, d) => s + d.weight, 0) || 1;
  // 申万一级反查口径数据(惰性加载, 切换到 'sw' 档时 fetch public_fund_sw_industry_alloc.json)
  let swDataLoaded = null;  // {data:[{name,weight,value,fundCount,industryCount,breakdown:null,avgWeight}], coverage_pct, coverage_note}
  const _loadSwIndData = async () => {
    if (swDataLoaded) return swDataLoaded;
    const data = await fetchJSON("https://ssd.fx8.store/public_fund/public_fund_sw_industry_alloc.json").catch(() => null);
    if (!data || !data.industries) return null;
    swDataLoaded = {
      data: data.industries.map((d) => ({
        name: d.industry_name,
        weight: d.total_weight || 0,
        value: d.total_value || 0,
        fundCount: d.fund_count || 0,
        industryCount: 1,
        breakdown: null,  // 申万一级已是细分口径, 无下钻
        avgWeight: d.avg_weight,
      })).sort((a, b) => b.weight - a.weight),
      coverage_pct: data.coverage_pct,
      coverage_note: data.coverage_note,
    };
    return swDataLoaded;
  };

  const indCard = document.createElement("div");
  indCard.className = "chart-card";
  indCard.innerHTML = '<div class="chart-title" style="display:flex;align-items:center;flex-wrap:wrap;gap:4px">'
    + '<span>🏭 行业配置（已合并重复分类，点按钮切换排序维度）</span>'
    + '<button class="pf-ind-sort-btn" data-ind-sort="weight" type="button">权重和</button>'
    + '<button class="pf-ind-sort-btn active" data-ind-sort="avg" type="button">平均权重</button>'
    + '<button class="pf-ind-sort-btn" data-ind-sort="value" type="button">持仓市值</button>'
    + '<span style="flex:1;min-width:8px"></span>'
    + '<span style="font-size:11px;color:var(--text-3)">口径:</span>'
    + '<button class="pf-ind-sort-btn active" data-ind-class="all" type="button" title="显示全部行业(证监会+GICS混合)">全部</button>'
    + '<button class="pf-ind-sort-btn" data-ind-class="csrc" type="button" title="只看证监会门类口径(A股基金披露)">证监会</button>'
    + '<button class="pf-ind-sort-btn" data-ind-class="gics" type="button" title="只看GICS口径(QDII/港股基金披露)">GICS</button>'
    + '<button class="pf-ind-sort-btn" data-ind-class="sw" type="button" title="申万一级反查口径(基于重仓股反查, 揭示真实风格暴露, 覆盖约42%仓位仅最新一期)">申万一级</button>'
    + '<span id="pfIndHelpBtn" style="margin-left:6px;cursor:help;color:var(--text-3);font-size:14px;line-height:1;user-select:none" title="行业配置口径说明">❓</span>'
    + '</div>'
    + '<div class="chart-subtitle" style="font-size:11px;color:var(--text-3);margin:0 0 4px 0;line-height:1.5">Top15 + 其他聚合(柱状图)；下方矩形树图看全景集中度(点按钮切换面积维度)；柱状图/矩形树图切换独立, 标签跟随各自选中维度: 权重和数值 / 平均权重% / 持仓市值亿</div>'
    + '<div class="chart-subtitle pf-ind-sub-default" style="font-size:11px;color:var(--text-3);margin:0 0 4px 0;line-height:1.5">🔬 点击<b>制造业</b>柱展开申万一级子行业(电子/通信/电力设备…, 基于重仓股拆分非直接披露)；矩形树图点制造业矩形弹子行业列表</div>'
    + '<div class="chart-subtitle pf-ind-sub-sw" style="font-size:11px;color:var(--text-3);margin:0 0 4px 0;line-height:1.5;display:none">🔬 <b>申万一级反查口径</b>: 基于基金前10大重仓股反查申万一级(非基金直接披露), 揭示真实风格暴露较官方证监会粗门类; <b>覆盖约42%仓位</b>(重仓股部分), 仅最新一期无历史时序; 31个细分行业(电子/通信/医药生物…), 申万一级已是细分口径无下钻</div>'
    + '<div class="chart pf-ind-bar" style="height:360px"></div>'
    + '<div class="chart-title" style="display:flex;align-items:center;flex-wrap:wrap;gap:4px;margin-top:8px">'
    + '<span>🎯 抱团集中度全景（矩形面积随选中维度变化）</span>'
    + '<button class="pf-ind-sort-btn" data-treemap-sort="weight" type="button">权重和</button>'
    + '<button class="pf-ind-sort-btn active" data-treemap-sort="avg" type="button">平均权重</button>'
    + '<button class="pf-ind-sort-btn" data-treemap-sort="value" type="button">持仓市值</button>'
    + '</div>'
    + '<div class="chart pf-ind-treemap" style="height:140px"></div>'
    + '<div class="chart-subtitle" style="font-size:11px;color:var(--text-3);margin:4px 0 0 0;line-height:1.5">💡 点击柱状图任一行业条 / 矩形树图任一矩形，弹窗显示该行业全部基金列表（按该行业配置权重降序，每页50只翻页，首次加载约 2MB）</div>';
  twoCol.appendChild(indCard);

  // 柱状图: Top15 + 其他聚合(长尾合并为单根"其他"柱), 支持 3 维度排序切换
  // indSort = 'weight'(权重和=total_weight) | 'avg'(平均权重=weight/fundCount) | 'value'(持仓市值=total_value)
  // indData 保持 weight 降序不变(TreeMap 用); 柱状图按 indSort 重排, label 跟随, tooltip 不变(显示全部3值)
  const TOP_N = 15;
  // 排序 key: weight=全市场权重%求和; avg=平均每只基金该行业仓位%; value=持仓总市值(万元)
  const _indSortKey = (d, mode) => {
    if (mode === 'avg') return d.fundCount > 0 ? d.weight / d.fundCount : 0;
    if (mode === 'value') return d.value;  // m.value = total_value (持仓市值, 万元)
    return d.weight;  // m.weight = total_weight (权重和)
  };
  let indSort = 'avg';  // 默认平均权重(用户要求 2026-08-01)
  let _manufExpanded = false;  // 制造业子行业展开状态(方案C Step4)
  // 按选中维度排序 indData -> Top15 + 其他聚合, 返回 barData
  // 制造业展开时: 在制造业柱后插入 breakdown 子行业柱(缩进+浅色, isBreakdown 标记)
  const _buildBarData = (mode) => {
    const sorted = indData.slice().sort((a, b) => _indSortKey(b, mode) - _indSortKey(a, mode));
    const _top = sorted.slice(0, TOP_N);
    const _rest = sorted.slice(TOP_N);
    const bar = [];
    for (const d of _top) {
      bar.push(d);
      // 制造业展开: 在制造业柱后插入 breakdown 子行业柱(基于重仓股拆分, 非直接披露)
      if (_manufExpanded && d.name === '制造业' && d.breakdown && d.breakdown.length) {
        for (const sub of d.breakdown) {
          bar.push({
            name: '  └ ' + sub.sub_industry,
            weight: sub.weight,
            value: sub.value,
            fundCount: sub.fund_count,
            industryCount: 0,
            isBreakdown: true,
            subIndustry: sub.sub_industry,
          });
        }
      }
    }
    if (_rest.length > 0) {
      const _restAgg = _rest.reduce((acc, d) => {
        acc.weight += d.weight; acc.value += d.value; acc.fundCount += d.fundCount; acc.industryCount += d.industryCount;
        return acc;
      }, { name: '其他', weight: 0, value: 0, fundCount: 0, industryCount: 0 });
      bar.push(_restAgg);
    }
    return bar;
  };
  // label formatter 跟随选中维度: weight->权重和数值; avg->平均权重%; value->持仓市值亿
  // 用 d.totalWeight(恒定权重和) 算平均权重, 不用 d.value(随 mode 变管柱子长度, 方案C bug 修复)
  const _indLabelFormatter = (p) => {
    const d = p.data;
    if (indSort === 'avg') return (d.fundCount > 0 ? (d.totalWeight / d.fundCount).toFixed(1) : '0') + '%';
    if (indSort === 'value') return (d.totalValue / 1e4).toFixed(2) + '亿';
    return d.totalWeight.toFixed(1);
  };
  const indChart = echarts.init(indCard.querySelector(".pf-ind-bar"));
  charts.push(indChart);
  // 渲染柱状图(初次渲染 + 切换重排共用): tooltip 恒显示3值(p[0].data 模式不回退), yAxis/series/label 随 mode 变
  const _renderIndBar = (mode) => {
    const bar = _buildBarData(mode);
    indChart.setOption({
      // 移动端超屏修复(2026-08-02): 本图直接 setOption 没走 withTheme(),全局 chartThemeOpts() L155-156 的
      // confine:true + extraCssText max-width 没合并进来,致移动端窄屏(375px)点击柱状条 tooltip 超屏看不全。
      // 手动补 confine:true(限制 tooltip 在 .pf-ind-bar 容器 343px x 360px 内不超屏)
      // + extraCssText max-width(300px 封顶小于容器 343px 留余量, 82vw 窄屏兜底, 强制换行防长中文撑宽)。
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, confine: true, extraCssText: "max-width: min(300px, 82vw); white-space: normal; overflow-wrap: anywhere; word-break: break-word;", formatter: (p) => {
        const d = p[0].data;  // series data object, 跟随 .reverse() 后显示顺序, 避免 indData[dataIndex] 用原始降序错位
        // 方案C bug 修复: d.value 随 mode 变(柱子长度), tooltip 用 d.totalWeight(恒定权重和) 算占比/平均权重
        // 制造业子行业(breakdown) tooltip 特殊: 显示"基于重仓股拆分"说明
        if (d.isBreakdown) {
          const pctOfTotal = (d.totalWeight / indTotalWeight * 100).toFixed(2);
          return `${d.subIndustry}（制造业子行业）<br/><br/>` +
            `📌 权重和: <b>${d.totalWeight.toFixed(1)}</b><span style="color:var(--text-3)"> (占全行业 ${pctOfTotal}%)</span><br/>` +
            `💰 持仓市值: <b>${(d.totalValue / 1e4).toFixed(2)} 亿</b><br/>` +
            `🏦 基金数: <b>${d.fundCount}</b> 只基金重仓该子行业<br/>` +
            `<span style="color:var(--text-3)">🔬 基于重仓股拆分（非基金直接披露）</span>`;
        }
        // d.totalWeight = SUM(weight_pct) 全市场基金该行业权重%求和(非 0-1 归一化), 用于柱状图排序(抱团集中度)
        // 平均权重 = d.totalWeight / d.fundCount, 即平均每只基金该行业仓位%, 直观百分比(制造业≈57.9%)
        // d.totalValue = SUM(hold_value) 单位万元, /1e4 转亿
        // d.industryCount = 合并前原始分类数(>1 说明合并过, tooltip 显示合并说明)
        const avgPct = (d.fundCount > 0 ? (d.totalWeight / d.fundCount).toFixed(1) : '0');
        const pctOfTotal = (d.totalWeight / indTotalWeight * 100).toFixed(2);
        const mergeInfo = d.industryCount > 1
          ? (d.name === '其他'
            ? `<br/>📦 其他 = ${d.industryCount} 个长尾行业合计(权重和占全行业 ${pctOfTotal}%)<br/>`
            : `<br/>🔀 已合并 ${d.industryCount} 个原始分类(申万/GICS/带编号)<br/>`)
          : '';
        const manufHint = (d.name === '制造业' && d.breakdown)
          ? `<br/><span style="color:var(--text-3)">🔬 点击此柱展开 ${d.breakdown.length} 个申万一级子行业(基于重仓股拆分)</span>`
          : '';
        return `${d.name}<br/><br/><b style="font-size:13px">📊 平均权重: ${avgPct}%</b><br/>` +
          `<span style="color:var(--text-3)">= 平均每只基金把 ${avgPct}% 仓位配在该行业</span><br/>` +
          `<span style="color:var(--text-3)">(全市场 ${d.fundCount} 只基金该行业权重%的平均值)</span><br/>` +
          `<br/>💰 持仓市值: <b>${(d.totalValue / 1e4).toFixed(2)} 亿</b><span style="color:var(--text-3)"> (全市场基金该行业持仓总市值)</span><br/>` +
          `🏦 基金数: <b>${d.fundCount}</b><span style="color:var(--text-3)"> 只基金持有该行业</span><br/>` +
          `<br/>📌 权重和: <b>${d.totalWeight.toFixed(1)}</b><span style="color:var(--text-3)"> (占全行业 ${pctOfTotal}%)</span><br/>` +
          `<span style="color:var(--text-3)">权重和越大 = 越多基金重配 = 抱团越集中</span>` +
          mergeInfo + manufHint;
      }},
      grid: { left: 10, right: 30, top: 10, bottom: 10, containLabel: true },
      xAxis: { type: "value", axisLabel: { fontSize: 12 } },
      yAxis: { type: "category", data: bar.map((d) => d.name).reverse(), axisLabel: {
        fontSize: 12, width: 120, overflow: "break", lineHeight: 13,
        // 制造业加 ▶/▼ 展开标志(方案C Step4)
        formatter: (val) => (val === '制造业' ? val + (_manufExpanded ? ' ▼' : ' ▶') : val),
      } },
      series: [{
        // 方案C bug 修复: value 随 mode 变(柱子长度跟着切换维度变), totalWeight 恒定(tooltip/label 算平均权重用)
        // isBreakdown 子行业用浅色区分; breakdown 传递供点击展开判断
        type: "bar", data: bar.map((d) => ({
          value: _indSortKey(d, mode),
          totalWeight: d.weight,
          fundCount: d.fundCount,
          name: d.name,
          totalValue: d.value,
          industryCount: d.industryCount,
          breakdown: d.breakdown || null,
          isBreakdown: !!d.isBreakdown,
          subIndustry: d.subIndustry || null,
          itemStyle: d.isBreakdown ? { color: "#f5b8a8" } : { color: "#e6492e" },
        })).reverse(),
        label: { show: true, position: "right", formatter: _indLabelFormatter, fontSize: 11 },
      }],
    });
  };
  _renderIndBar(indSort);
  // 排序切换按钮: 3 选 1 互斥, 点击重排柱状图 + 更新 active 态 + label 跟随
  // 用 [data-ind-sort] 只选柱状图3按钮(非 .pf-ind-sort-btn 会误含 TreeMap 按钮致联动 active 消失)
  indCard.querySelectorAll("[data-ind-sort]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const mode = btn.getAttribute("data-ind-sort");
      if (mode === indSort) return;
      indSort = mode;
      indCard.querySelectorAll("[data-ind-sort]").forEach((b) => b.classList.toggle("active", b === btn));
      _renderIndBar(mode);
    });
  });

  // 口径切换按钮: 全部/证监会/GICS/申万一级 四档
  //   all/csrc/gics: 按标准名口径过滤 indDataAll (both 两视图都显示)
  //   sw: 换数据源, fetch public_fund_sw_industry_alloc.json(申万一级反查口径, 独立计算)
  // 切换后柱状图+TreeMap 同步重渲染; 制造业展开状态重置(切换GICS制造业被过滤, 残留展开无意义)
  // 'sw' 档: 申万一级已是细分口径, 制造业 breakdown 无意义(禁用); indTotalWeight 重算为 sw 数据总和
  const _filterByClass = (cls) => {
    if (cls === 'all') return indDataAll;
    return indDataAll.filter((d) => {
      const c = _classifyInd(d.name);
      return c === cls || c === 'both';
    });
  };
  const _toggleSwSubtitle = (isSw) => {
    const subDefault = indCard.querySelector(".pf-ind-sub-default");
    const subSw = indCard.querySelector(".pf-ind-sub-sw");
    if (subDefault) subDefault.style.display = isSw ? "none" : "";
    if (subSw) subSw.style.display = isSw ? "" : "none";
  };
  indCard.querySelectorAll("[data-ind-class]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const cls = btn.getAttribute("data-ind-class");
      if (cls === indClass) return;
      indClass = cls;
      _manufExpanded = false;  // 重置制造业展开(避免切换到无制造业的口径后残留展开态)
      indCard.querySelectorAll("[data-ind-class]").forEach((b) => b.classList.toggle("active", b === btn));
      if (cls === 'sw') {
        // 申万一级反查口径: fetch 新 JSON 换数据源
        const sw = await _loadSwIndData();
        if (sw && sw.data && sw.data.length) {
          indData = sw.data;
          indTotalWeight = sw.data.reduce((s, d) => s + d.weight, 0) || 1;
          _toggleSwSubtitle(true);
          _renderIndBar(indSort);
          _renderTreemap(treemapSort);
        } else {
          // fetch 失败回退到 all
          indClass = 'all';
          indData = indDataAll;
          indTotalWeight = indDataAll.reduce((s, d) => s + d.weight, 0) || 1;
          _toggleSwSubtitle(false);
          indCard.querySelectorAll("[data-ind-class]").forEach((b) => b.classList.toggle("active", b.getAttribute("data-ind-class") === 'all'));
          _renderIndBar(indSort);
          _renderTreemap(treemapSort);
        }
      } else {
        indData = _filterByClass(cls);
        indTotalWeight = indDataAll.reduce((s, d) => s + d.weight, 0) || 1;
        _toggleSwSubtitle(false);
        _renderIndBar(indSort);
        _renderTreemap(treemapSort);
      }
    });
  });

  // ❓ 行业配置口径说明弹窗(复用 .rule-modal 骨架, 内容: 双口径来源+切换说明+制造业占比+通信区别)
  const _showIndHelpModal = () => {
    let modal = document.getElementById("pfIndHelpModal");
    if (!modal) {
      modal = document.createElement("div");
      modal.id = "pfIndHelpModal";
      modal.className = "rule-modal hidden pf-ind-fund-modal";
      document.body.appendChild(modal);
    }
    const helpContent = ''
      + '<div style="margin-bottom:14px"><b style="font-size:14px;color:#e6492e">📚 三套口径来源</b></div>'
      + '<div style="margin-bottom:12px">公募基金行业配置数据由<b>三套口径</b>构成：</div>'
      + '<div style="margin-bottom:6px;padding-left:12px">• <b>证监会门类(CSRC)</b>：A股基金直接披露，19大门类（制造业/金融业/信息传输软件和信息技术服务业/建筑业等），基金季报直接披露</div>'
      + '<div style="margin-bottom:6px;padding-left:12px">• <b>全球行业分类标准(GICS)</b>：合格境内机构投资者(QDII)/港股基金直接披露，11大类（能源/材料/工业/医疗保健/通信服务等），基金季报直接披露</div>'
      + '<div style="margin-bottom:12px;padding-left:12px">• <b>申万一级</b>：基于基金前10大重仓股<b>反查</b>申万一级行业（<b>非基金直接披露</b>），揭示真实风格暴露，独立数据源，覆盖率约42%仓位，仅最新一期无时序——详见下文「🧬 申万一级反查口径」章节</div>'
      + '<div style="margin-bottom:14px;color:var(--text-3)">前两套(CSRC/GICS)为基金直接披露、合并展示，你会同时看到"制造业"(CSRC)和"通信服务"(GICS)；第三套申万一级为反查独立口径，切换"申万一级"按钮重渲染。</div>'
      + '<div style="margin-bottom:10px"><b style="font-size:14px;color:#e6492e">🔁 切换功能（标题旁"口径"按钮组）</b></div>'
      + '<div style="margin-bottom:6px;padding-left:12px">• <b>全部</b>：显示所有行业（默认，混合口径）</div>'
      + '<div style="margin-bottom:6px;padding-left:12px">• <b>证监会</b>：只看 CSRC 门类（A股基金口径：制造业/金融业/建筑业…）</div>'
      + '<div style="margin-bottom:6px;padding-left:12px">• <b>GICS</b>：只看 GICS 大类（QDII基金口径：能源/材料/工业/通信服务…）</div>'
      + '<div style="margin-bottom:6px;padding-left:12px">• <b>申万一级</b>：基于基金前10大重仓股<b>反查</b>申万一级（非基金直接披露，揭示真实风格暴露，详见下文）</div>'
      + '<div style="margin-bottom:14px;color:var(--text-3)">注：信息技术/金融业/房地产业三行业在两套口径都有（合并自 CSRC+GICS 原始名），切换任一视图都显示。申万一级为独立数据源，切换时重渲染。</div>'
      + '<div style="margin-bottom:10px"><b style="font-size:14px;color:#e6492e">🏭 制造业占比大不是缺陷</b></div>'
      + '<div style="margin-bottom:14px">制造业平均权重≈58%，因为<b>证监会"制造业"门类极粗</b>，涵盖电子/通信/汽车/电力设备/医药生物/食品饮料等所有制造类子行业。GICS 把这些拆成了信息技术/工业/医疗保健/消费品等多个独立大类，所以 GICS 视图下没有"制造业"这一超大类。</div>'
      + '<div style="margin-bottom:10px"><b style="font-size:14px;color:#e6492e">⚠️ "通信" ≠ "通信服务"</b></div>'
      + '<div style="margin-bottom:6px;padding-left:12px">• <b>通信</b>：制造业的<b>子行业</b>（通信<b>设备</b>制造，如中兴/烽火），点击制造业柱展开可见</div>'
      + '<div style="margin-bottom:14px;padding-left:12px">• <b>通信服务</b>：GICS 独立大类（通信<b>运营</b>服务，如中国移动/中国电信），QDII 基金披露</div>'
      + '<div style="margin-bottom:14px;color:var(--text-3)">二者口径完全不同，勿混淆。</div>'
      + '<div style="margin-bottom:10px"><b style="font-size:14px;color:#e6492e">🔬 制造业子行业展开</b></div>'
      + '<div style="margin-bottom:14px">点击柱状图 <b>制造业</b> 条（▶）展开 18 个申万一级子行业（电子/通信/电力设备…），基于重仓股拆分（非基金直接披露）；非制造业口径下此功能不可用。</div>'
      + '<div style="margin-bottom:10px"><b style="font-size:14px;color:#e6492e">🧬 申万一级反查口径（第四档"申万一级"按钮）</b></div>'
      + '<div style="margin-bottom:6px"><b>数据来源</b>：基于基金前10大重仓股（fund_portfolio_hold）反查申万一级行业（sw_components.json 5210 成分股），<b>非基金直接披露</b>。</div>'
      + '<div style="margin-bottom:6px"><b>价值</b>：揭示基金<b>真实风格暴露</b>（较证监会口径的粗门类"制造业"涵盖18个子行业）。证监会口径下制造业≈58%是大类堆叠；申万一级拆出电子/通信/电力设备/医药生物等31个细分行业，能看到基金真正重仓哪个细分赛道，是<b>反查口径有信息差价值</b>。</div>'
      + '<div style="margin-bottom:6px"><b>和制造业拆分的区别</b>：拆分只展开证监会"制造业"门类下18个子项（仍属证监会口径视图）；申万一级是<b>全市场31行业视角</b>（含银行/房地产/非银金融等非制造业），独立数据源。</div>'
      + '<div style="margin-bottom:6px"><b>3个硬限制（诚实标注）</b>：</div>'
      + '<div style="margin-bottom:4px;padding-left:12px">① <b>时序不可用</b>：fund_portfolio_hold 仅1期（最新季报），无历史对比，不能看轮动</div>'
      + '<div style="margin-bottom:4px;padding-left:12px">② <b>覆盖率约42%</b>：前10大重仓股平均占净值42%，仅反映重仓股部分行业暴露，非完整行业配置（较证监会口径含全仓位）</div>'
      + '<div style="margin-bottom:14px;padding-left:12px">③ <b>反查口径</b>：基于重仓股反查（非基金直接披露），未映射股票（港股等）归"未分类"</div>'
      + '<div style="margin-bottom:10px"><b style="font-size:14px;color:#e6492e">📊 数值口径</b></div>'
      + '<div style="margin-bottom:6px;padding-left:12px">• <b>权重和</b> = 全市场基金该行业权重%求和（抱团集中度）</div>'
      + '<div style="margin-bottom:6px;padding-left:12px">• <b>平均权重</b> = 权重和 ÷ 基金数（平均每只基金该行业仓位%，制造业≈58%）</div>'
      + '<div style="margin-bottom:6px;padding-left:12px">• <b>持仓市值</b> = 全市场基金该行业持仓总市值（亿）</div>'
      + '<div style="color:var(--text-3)">切换口径时数值不变（只过滤显示行业），"占全行业%"相对全集稳定。</div>';
    modal.innerHTML = '<div class="rule-modal-overlay"></div>'
      + '<div class="rule-modal-body">'
      + '<div class="rule-modal-header"><h3>🏭 行业配置口径说明</h3>'
      + '<button class="rule-modal-close" aria-label="关闭" type="button">&times;</button></div>'
      + '<div class="rule-modal-content" style="padding:16px 20px;font-size:13px;line-height:1.7;color:var(--text-2);max-height:70vh;overflow:auto">' + helpContent + '</div>'
      + '</div>';
    modal.classList.remove("hidden");
    document.body.style.overflow = "hidden";
    const _close = () => { modal.classList.add("hidden"); document.body.style.overflow = ""; };
    modal.querySelector(".rule-modal-overlay").addEventListener("click", _close);
    modal.querySelector(".rule-modal-close").addEventListener("click", _close);
  };
  const _helpBtn = indCard.querySelector("#pfIndHelpBtn");
  if (_helpBtn) _helpBtn.addEventListener("click", _showIndHelpModal);

  // TreeMap 全景(合并后全行业不截断, 矩形面积=选中维度值, 颜色深浅=value 大小)
  // treemapSort 独立于柱状图 indSort: weight=权重和(total_weight) | avg=平均权重(weight/fundCount) | value=持仓市值(total_value)
  // data 用 object 形式带全字段(totalWeight/fundCount/totalValue/industryCount)避免 tooltip 错位;
  // value(矩形面积)随 treemapSort 切换, tooltip 恒显示3值(从 totalWeight 算, 不依赖 value)
  let treemapSort = 'avg';  // 默认平均权重(用户要求 2026-08-01)
  const treemapChart = echarts.init(indCard.querySelector(".pf-ind-treemap"));
  charts.push(treemapChart);
  // 渲染 TreeMap(初次渲染 + 切换重排共用): tooltip 恒显示3值(p.data 模式不回退), label 跟随 treemapSort, value(面积)随 treemapSort
  const _renderTreemap = (mode) => {
    treemapChart.setOption({
      tooltip: { formatter: (p) => {
        // treemap tooltip 从 p.data 取(同柱状图口径, 不依赖外部 indData 数组避免错位)
        // d.value = 矩形面积值(随 mode 变); tooltip 用 d.totalWeight 算占比/平均权重(恒定不随 mode 变)
        const d = p.data;
        const avgPct = (d.fundCount > 0 ? (d.totalWeight / d.fundCount).toFixed(1) : '0');
        const pctOfTotal = (d.totalWeight / indTotalWeight * 100).toFixed(2);
        const mergeInfo = d.industryCount > 1 ? `<br/>🔀 已合并 ${d.industryCount} 个原始分类` : '';
        const manufHint = (d.name === '制造业' && d.breakdown)
          ? `<br/><span style="color:var(--text-3)">🔬 点击查看 ${d.breakdown.length} 个申万一级子行业(基于重仓股拆分)</span>`
          : '';
        return `${d.name}<br/><br/>📦 权重和: <b>${d.totalWeight.toFixed(1)}</b> (占 ${pctOfTotal}%)<br/>` +
          `📊 平均权重: <b>${avgPct}%</b><br/>` +
          `💰 持仓市值: <b>${(d.totalValue / 1e4).toFixed(2)} 亿</b><br/>` +
          `🏦 基金数: <b>${d.fundCount}</b>${mergeInfo}${manufHint}`;
      }},
      series: [{
        type: "treemap",
        width: '100%', height: '100%',
        roam: false, nodeClick: false,
        breadcrumb: { show: false },
        upperLabel: { show: false },
        // colorMappingBy: 'value' 按兄弟节点 value 排序映射 color 数组, max 大柱深红, 长尾浅色
        colorMappingBy: 'value',
        color: ['#fde4d4', '#fac5a5', '#f88b6a', '#f5704d', '#e6492e', '#9a2a18'],
        label: {
          show: true,
          // label 跟随 treemapSort: weight->权重和占比%; avg->平均权重%; value->持仓市值亿
          formatter: (p) => {
            const d = p.data;
            if (mode === 'avg') return `${d.name} ${(d.totalWeight / d.fundCount).toFixed(1)}%`;
            if (mode === 'value') return `${d.name} ${(d.totalValue / 1e4).toFixed(1)}亿`;
            const pct = (d.totalWeight / indTotalWeight * 100).toFixed(1);
            return `${d.name} ${pct}%`;
          },
          fontSize: 10,
        },
        itemStyle: { borderColor: '#fff', borderWidth: 1, gapWidth: 1 },
        emphasis: { label: { fontSize: 12 } },
        // data 用 object 形式带全字段; value(矩形面积)随 mode 切换:
        //   weight=totalWeight(权重和) | avg=totalWeight/fundCount(平均权重) | value=totalValue(持仓市值)
        //   totalWeight/fundCount/totalValue/industryCount 原值保留, tooltip 恒显示3值不随 mode 变
        data: indData.map((d) => {
          const totalWeight = d.weight;
          const totalValue = d.value;
          const fundCount = d.fundCount;
          let sortVal;
          if (mode === 'avg') sortVal = fundCount > 0 ? totalWeight / fundCount : 0;
          else if (mode === 'value') sortVal = totalValue;
          else sortVal = totalWeight;
          return {
            name: d.name, value: sortVal,
            totalWeight, fundCount, totalValue, industryCount: d.industryCount,
            breakdown: d.breakdown || null,  // 制造业子行业(方案C Step4, 点击弹 breakdown 列表)
          };
        }),
      }],
    });
  };
  _renderTreemap(treemapSort);
  // TreeMap 排序切换按钮: 3 选 1 互斥(独立于柱状图), 点击重排矩形面积 + 更新 active 态 + label 跟随
  indCard.querySelectorAll("[data-treemap-sort]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const mode = btn.getAttribute("data-treemap-sort");
      if (mode === treemapSort) return;
      treemapSort = mode;
      indCard.querySelectorAll("[data-treemap-sort]").forEach((b) => b.classList.toggle("active", b === btn));
      _renderTreemap(mode);
    });
  });

  // ── 点击行业弹窗显示基金列表(方案D: 按需 fetch public_fund_industry_fund_map.json, 模块级缓存) ──
  // 复用 .rule-modal 骨架(遮罩+居中+× 关闭+ESC), .pf-ind-fund-modal 覆盖宽度 600px + 红色主题
  // 翻页(非追加): 每页 50 只, 底部上一页/页码/下一页 + 页码信息(参考 _renderEtfPager 风格)
  const _PF_FUND_PAGE_SIZE = 50;
  let _pfFundCurName = null;       // 当前弹窗的行业名(防异步过期)
  let _pfFundCurList = null;       // 当前行业的基金列表(翻页切片用, 避免闭包传参)
  let _pfFundCurPage = 1;          // 当前页码(1-based, 兼容保留; 新渲染器用本地闭包)
  let _pfFundCurTip = null;        // 当前弹窗的 tip 文本(行业/子行业不同口径)
  let _pfFundEscBound = false;     // ESC 监听只绑一次

  // 渲染翻页器 HTML(参考 _renderEtfPager: 上一页/页码(带省略号)/下一页 + 页码信息)
  const _renderFundPager = (page, pages, total) => {
    if (pages <= 1) return '';  // 单页不显示翻页器
    let html = '<div class="pf-ind-fund-pager">';
    html += '<button class="pf-page-btn" data-page="' + (page > 1 ? page - 1 : 1) + '"' + (page <= 1 ? ' disabled' : '') + '>上一页</button>';
    const pageBtns = [];
    const addPage = (p) => { if (pageBtns.indexOf(p) < 0) pageBtns.push(p); };
    addPage(1); addPage(pages);
    for (let p = page - 2; p <= page + 2; p++) {
      if (p > 1 && p < pages) addPage(p);
    }
    pageBtns.sort((a, b) => a - b);
    let prev = 0;
    pageBtns.forEach((p) => {
      if (p - prev > 1) html += '<span class="pf-page-ellipsis">…</span>';
      html += '<button class="pf-page-btn' + (p === page ? " active" : "") + '" data-page="' + p + '">' + p + '</button>';
      prev = p;
    });
    html += '<button class="pf-page-btn" data-page="' + (page < pages ? page + 1 : pages) + '"' + (page >= pages ? ' disabled' : '') + '>下一页</button>';
    html += '<span class="pf-page-info">' + page + ' / ' + pages + ' 页（' + total + ' 只）</span>';
    html += '</div>';
    return html;
  };

  // 自包含基金列表渲染器: 本地 page 闭包, 不依赖共享状态(避免 2-tab Tab2 与 fund list 弹窗冲突)
  // 渲染表格 + 翻页器到任意 container, 翻页时只重渲染 container 内部(不重 fetch)
  const _renderFundListInto = (container, list, opts) => {
    const pageSize = _PF_FUND_PAGE_SIZE;
    const tip = opts?.tip || '💡 按该行业配置权重降序；权重% = 该基金对此行业的仓位占比，持仓市值单位万元';
    const emptyName = opts?.emptyName || '';
    let page = opts?.page || 1;
    const render = () => {
      const l = list || [];
      if (l.length === 0) {
        container.innerHTML = `<div style="padding:20px;text-align:center;color:var(--text-3)">📦 ${emptyName}：暂无基金数据</div>`;
        return;
      }
      const total = l.length;
      const pages = Math.max(1, Math.ceil(total / pageSize));
      page = Math.min(page, pages);
      const start = (page - 1) * pageSize;
      const pageList = l.slice(start, start + pageSize);
      const rows = pageList.map((f, i) => {
        const wp = f.weight_pct != null ? f.weight_pct.toFixed(2) + '%' : '-';
        const hv = f.hold_value != null ? (f.hold_value).toFixed(2) : '-';
        return `<tr><td>${start + i + 1}</td><td class="pf-code">${f.fund_code || '-'}</td><td>${f.fund_name || '-'}</td><td class="pf-num">${wp}</td><td class="pf-num">${hv}</td></tr>`;
      }).join("");
      container.innerHTML = '<div class="pf-table-wrap"><table class="pf-table">'
        + '<thead><tr><th>#</th><th>代码</th><th>名称</th><th>该行业权重%</th><th>持仓市值(万)</th></tr></thead>'
        + `<tbody>${rows}</tbody></table></div>`
        + _renderFundPager(page, pages, total)
        + `<div class="pf-modal-tip">${tip}</div>`;
      container.querySelectorAll(".pf-page-btn").forEach((btn) => {
        btn.addEventListener("click", () => {
          if (btn.disabled) return;
          const p = parseInt(btn.getAttribute("data-page"), 10);
          if (isNaN(p) || p === page) return;
          page = p;
          render();
        });
      });
    };
    render();
  };

  // 渲染 #pfIndFundModal 内容(单例 modal, 用共享状态 _pfFundCurList/_pfFundCurName/_pfFundCurTip)
  const _renderFundModalPage = (modal) => {
    _renderFundListInto(modal.querySelector(".rule-modal-content"), _pfFundCurList, {
      emptyName: _pfFundCurName,
      tip: _pfFundCurTip,
    });
  };

  // 关闭 modal(加 hidden + 恢复 body 滚动 + 清当前行业)
  const _closeFundModal = (modal) => {
    modal.classList.add("hidden");
    document.body.style.overflow = "";
    _pfFundCurName = null;
    _pfFundCurList = null;
    _pfFundCurPage = 1;
    _pfFundCurTip = null;
  };

  // 点击行业名 -> 创建/复用 modal -> loading -> 异步拉 fund_map -> 渲染表格(翻页, 默认第 1 页)
  const _showIndustryFunds = async (indName) => {
    if (!indName || indName === '其他') return;  // 长尾聚合不弹窗
    _pfFundCurName = indName;
    _pfFundCurList = null;
    _pfFundCurPage = 1;  // 重新打开重置到第 1 页
    _pfFundCurTip = null;  // 用默认 tip(行业配置权重口径)
    // 创建或复用 modal(单例, 避免重复创建堆积 DOM)
    let modal = document.getElementById("pfIndFundModal");
    if (!modal) {
      modal = document.createElement("div");
      modal.id = "pfIndFundModal";
      modal.className = "rule-modal hidden pf-ind-fund-modal";
      document.body.appendChild(modal);
    }
    // 渲染骨架(标题 + loading 态), 复用 .rule-modal-overlay/.rule-modal-body/.rule-modal-header/.rule-modal-close
    modal.innerHTML = '<div class="rule-modal-overlay"></div>'
      + '<div class="rule-modal-body">'
      + '<div class="rule-modal-header"><h3>📦 ' + indName + ' 行业基金列表</h3>'
      + '<button class="rule-modal-close" aria-label="关闭" type="button">&times;</button></div>'
      + '<div class="rule-modal-content"><div style="padding:20px;text-align:center;color:var(--text-3)">⏳ 加载中...</div></div>'
      + '</div>';
    const _close = () => _closeFundModal(modal);
    modal.querySelector(".rule-modal-overlay").addEventListener("click", _close);
    modal.querySelector(".rule-modal-close").addEventListener("click", _close);
    // ESC 关闭(全局 keydown 只绑一次, 关闭当前可见的 modal)
    if (!_pfFundEscBound) {
      document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") {
          const m = document.getElementById("pfIndFundModal");
          if (m && !m.classList.contains("hidden")) _closeFundModal(m);
          const tm = document.getElementById("pfManufTabModal");
          if (tm && !tm.classList.contains("hidden")) { tm.classList.add("hidden"); document.body.style.overflow = ""; }
        }
      });
      _pfFundEscBound = true;
    }
    modal.classList.remove("hidden");
    document.body.style.overflow = "hidden";  // 防背景滚动
    // 异步拉取 fund_map(模块级缓存, 首次约 2MB)
    const fmap = await _loadIndustryFundMap();
    if (_pfFundCurName !== indName) return;  // 异步期间用户关了/换了, 丢弃过期结果
    if (!fmap || !fmap.industry_funds) {
      modal.querySelector(".rule-modal-content").innerHTML = `<div style="padding:20px;text-align:center;color:var(--text-3)">📦 ${indName}：基金列表加载失败</div>`;
      return;
    }
    const list = fmap.industry_funds[indName] || [];
    // 标题更新为"X 的 N 只基金"(行业名 + 基金数)
    modal.querySelector(".rule-modal-header h3").textContent = `📦 ${indName} 的 ${list.length} 只基金`;
    _pfFundCurList = list;  // 缓存列表供翻页切片(不重 fetch)
    _renderFundModalPage(modal);
  };

  // 子行业基金弹窗(方案C Step5): 柱状图子行业柱点击 + TreeMap Tab1 子行业项点击 都调此
  // 复用 #pfIndFundModal 骨架 + _renderFundModalPage 翻页; 数据源 _loadManufSubindFundMap(重仓股拆分口径)
  const _showManufSubindFunds = async (subIndName) => {
    if (!subIndName) return;
    _pfFundCurName = subIndName;
    _pfFundCurList = null;
    _pfFundCurPage = 1;
    _pfFundCurTip = '🔬 重仓股拆分口径：该基金重仓股中属于「' + subIndName + '」子行业的股票汇总（权重%/持仓市值为该子行业重仓股之和，单位万元）';
    let modal = document.getElementById("pfIndFundModal");
    if (!modal) {
      modal = document.createElement("div");
      modal.id = "pfIndFundModal";
      modal.className = "rule-modal hidden pf-ind-fund-modal";
      document.body.appendChild(modal);
    }
    modal.innerHTML = '<div class="rule-modal-overlay"></div>'
      + '<div class="rule-modal-body">'
      + '<div class="rule-modal-header"><h3>📦 ' + subIndName + ' 子行业基金列表（制造业拆分）</h3>'
      + '<button class="rule-modal-close" aria-label="关闭" type="button">&times;</button></div>'
      + '<div class="rule-modal-content"><div style="padding:20px;text-align:center;color:var(--text-3)">⏳ 加载中...</div></div>'
      + '</div>';
    const _close = () => _closeFundModal(modal);
    modal.querySelector(".rule-modal-overlay").addEventListener("click", _close);
    modal.querySelector(".rule-modal-close").addEventListener("click", _close);
    if (!_pfFundEscBound) {
      document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") {
          const m = document.getElementById("pfIndFundModal");
          if (m && !m.classList.contains("hidden")) _closeFundModal(m);
          const tm = document.getElementById("pfManufTabModal");
          if (tm && !tm.classList.contains("hidden")) { tm.classList.add("hidden"); document.body.style.overflow = ""; }
        }
      });
      _pfFundEscBound = true;
    }
    modal.classList.remove("hidden");
    document.body.style.overflow = "hidden";
    const smap = await _loadManufSubindFundMap();
    if (_pfFundCurName !== subIndName) return;  // 异步期间用户关了/换了
    if (!smap || !smap.subind_funds) {
      modal.querySelector(".rule-modal-content").innerHTML = `<div style="padding:20px;text-align:center;color:var(--text-3)">📦 ${subIndName}：基金列表加载失败</div>`;
      return;
    }
    const list = smap.subind_funds[subIndName] || [];
    modal.querySelector(".rule-modal-header h3").textContent = `📦 ${subIndName} 的 ${list.length} 只基金（制造业拆分）`;
    _pfFundCurList = list;
    _renderFundModalPage(modal);
  };
  // 制造业 2-tab 弹窗(方案C Step5, TreeMap 点击制造业用):
  //   Tab1 子行业: breakdown 表格(每行子行业名可点击 -> _showManufSubindFunds 新弹窗下钻)
  //   Tab2 制造业基金: 制造业全部基金列表(复用 _loadIndustryFundMap + _renderFundListInto, 不重复 fetch)
  // 用独立 modal #pfManufTabModal(和 #pfIndFundModal 单例并存, Tab1 下钻时 #pfIndFundModal 在上层)
  const _showManufBreakdown = (breakdown) => {
    if (!breakdown || !breakdown.length) return;
    let modal = document.getElementById("pfManufTabModal");
    if (!modal) {
      modal = document.createElement("div");
      modal.id = "pfManufTabModal";
      modal.className = "rule-modal hidden pf-ind-fund-modal";
      document.body.appendChild(modal);
    }
    const totalW = breakdown.reduce((s, b) => s + (b.weight || 0), 0) || 1;
    // Tab1 子行业表格行: 每行可点击下钻到子行业基金弹窗
    const rows = breakdown.map((b, i) => {
      const pct = ((b.weight || 0) / totalW * 100).toFixed(2);
      return `<tr class="pf-subind-row" data-subind="${b.sub_industry}">`
        + `<td>${i + 1}</td>`
        + `<td><span class="pf-subind-name">${b.sub_industry}</span><span class="pf-subind-arrow">查看基金 →</span></td>`
        + `<td class="pf-num">${(b.weight || 0).toFixed(2)}</td>`
        + `<td class="pf-num">${pct}%</td>`
        + `<td class="pf-num">${((b.value || 0) / 1e4).toFixed(2)}</td>`
        + `<td class="pf-num">${b.fund_count || 0}</td>`
        + `</tr>`;
    }).join("");
    modal.innerHTML = '<div class="rule-modal-overlay"></div>'
      + '<div class="rule-modal-body">'
      + '<div class="rule-modal-header"><h3>🏭 制造业子行业拆分（共 ' + breakdown.length + ' 个子行业）</h3>'
      + '<button class="rule-modal-close" aria-label="关闭" type="button">&times;</button></div>'
      + '<div class="rule-modal-content">'
      + '<div class="pf-tab-header">'
      + '<button class="pf-tab-btn active" data-pf-tab="1">📊 子行业（点击查看基金）</button>'
      + '<button class="pf-tab-btn" data-pf-tab="2">📦 制造业全部基金</button>'
      + '</div>'
      + '<div class="pf-tab-body active" data-pf-tab-body="1">'
      + '<div class="pf-tab-tip">💡 点击子行业名称查看该子行业的基金列表（重仓股拆分口径）</div>'
      + '<div class="pf-table-wrap"><table class="pf-subind-table">'
      + '<thead><tr><th>#</th><th>申万一级子行业</th><th>权重和</th><th>占制造业%</th><th>持仓市值(亿)</th><th>基金数</th></tr></thead>'
      + `<tbody>${rows}</tbody></table></div>`
      + '</div>'  // Tab1 body end
      + '<div class="pf-tab-body" data-pf-tab-body="2">'
      + '<div style="padding:20px;text-align:center;color:var(--text-3)">⏳ 点击此 Tab 加载制造业全部基金...</div>'
      + '</div>'  // Tab2 body end (lazy load on tab switch)
      + '</div>'  // content end
      + '</div>';
    const _close = () => { modal.classList.add("hidden"); document.body.style.overflow = ""; };
    modal.querySelector(".rule-modal-overlay").addEventListener("click", _close);
    modal.querySelector(".rule-modal-close").addEventListener("click", _close);
    // ESC 关闭(守护 _pfFundEscBound, 和 _showIndustryFunds/_showManufSubindFunds 共用)
    if (!_pfFundEscBound) {
      document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") {
          const m = document.getElementById("pfIndFundModal");
          if (m && !m.classList.contains("hidden")) _closeFundModal(m);
          const tm = document.getElementById("pfManufTabModal");
          if (tm && !tm.classList.contains("hidden")) { tm.classList.add("hidden"); document.body.style.overflow = ""; }
        }
      });
      _pfFundEscBound = true;
    }
    // Tab1 子行业行点击 -> 新弹窗显示子行业基金(不覆盖 2-tab modal)
    modal.querySelectorAll(".pf-subind-row").forEach((tr) => {
      tr.addEventListener("click", () => {
        const sub = tr.getAttribute("data-subind");
        if (sub) _showManufSubindFunds(sub);
      });
    });
    // Tab 切换: 点 tab 头 -> 切 active + 懒加载 Tab2 内容
    let tab2Loaded = false;
    modal.querySelectorAll(".pf-tab-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const tab = btn.getAttribute("data-pf-tab");
        modal.querySelectorAll(".pf-tab-btn").forEach((b) => b.classList.toggle("active", b === btn));
        modal.querySelectorAll(".pf-tab-body").forEach((body) => {
          body.classList.toggle("active", body.getAttribute("data-pf-tab-body") === tab);
        });
        // Tab2 懒加载: 首次切换时拉制造业全部基金, 复用 _loadIndustryFundMap(模块级缓存)
        if (tab === "2" && !tab2Loaded) {
          tab2Loaded = true;
          const tab2Body = modal.querySelector('[data-pf-tab-body="2"]');
          tab2Body.innerHTML = '<div style="padding:20px;text-align:center;color:var(--text-3)">⏳ 加载中...</div>';
          const fmap = await _loadIndustryFundMap();
          if (!fmap || !fmap.industry_funds || !fmap.industry_funds['制造业']) {
            tab2Body.innerHTML = '<div style="padding:20px;text-align:center;color:var(--text-3)">📦 制造业基金列表加载失败</div>';
            return;
          }
          const list = fmap.industry_funds['制造业'] || [];
          // 用 _renderFundListInto 自包含渲染(本地 page 闭包, 不依赖共享状态, 不和 #pfIndFundModal 冲突)
          _renderFundListInto(tab2Body, list, {
            emptyName: '制造业',
            tip: '💡 制造业全部基金（按行业配置权重降序）；权重% = 该基金对制造业的仓位占比，持仓市值单位万元',
          });
        }
      });
    });
    modal.classList.remove("hidden");
    document.body.style.overflow = "hidden";
  };
  // 柱状图点击: 制造业切换子行业展开, 子行业柱弹子行业基金弹窗(方案C Step5), 其他行业弹基金列表
  // 'sw' 申万一级档: 数据源不同(重仓股反查非 fund_industry_alloc), 不支持基金列表下钻, 跳过
  indChart.on('click', (params) => {
    if (!params || !params.data || !params.data.name) return;
    if (indClass === 'sw') return;  // 申万一级反查口径无下钻(副标题已说明)
    const d = params.data;
    if (d.isBreakdown) { _showManufSubindFunds(d.subIndustry); return; }  // 子行业柱 -> 子行业基金弹窗
    if (d.name === '制造业' && d.breakdown) {
      _manufExpanded = !_manufExpanded;
      _renderIndBar(indSort);
      return;
    }
    _showIndustryFunds(d.name);
  });
  // TreeMap 点击: 制造业弹子行业 breakdown 列表, 其他行业弹基金列表
  // 'sw' 申万一级档: 同柱状图, 不支持下钻
  treemapChart.on('click', (params) => {
    if (!params || !params.data || !params.data.name) return;
    if (indClass === 'sw') return;
    const d = params.data;
    if (d.name === '制造业' && d.breakdown) {
      _showManufBreakdown(d.breakdown);
      return;
    }
    _showIndustryFunds(d.name);
  });

  // ── F功能: 行业轮动时序堆叠面积图(34期季报 2017Q1-2026Q2, 13行业平均权重变迁) ──
  // 数据源: public_fund_industry_rotation_ts.json (R2 直链, 13 canonical 行业, 134原始名合并)
  // 口径: AVG(weight_pct) 跨基金平均(非SUM), 反映"典型基金"行业配置占比; 过滤 fund_count<50 脏数据期
  // 本地 range 切换(3y/5y/all): 按日期过滤 series, 不依赖全局 state.range(季频 vs 日频)
  let _rotTs = null;
  try {
    _rotTs = await fetchJSON("https://ssd.fx8.store/public_fund/public_fund_industry_rotation_ts.json").catch(() => null);
  } catch (e) { /* F面板不渲染, 不阻塞后续 Top100 */ }

  if (_rotTs && _rotTs.series && _rotTs.series.length && _rotTs.industries_order && _rotTs.industries_order.length) {
    const _rotCard = document.createElement("div");
    _rotCard.className = "chart-card pf-rot-card";
    const _rotD0 = _pfFmtDate(_rotTs.series[0].date).slice(0, 7);
    const _rotDN = _pfFmtDate(_rotTs.series[_rotTs.series.length - 1].date).slice(0, 7);
    _rotCard.innerHTML = '<div class="chart-title" style="display:flex;align-items:center;flex-wrap:wrap;gap:4px">'
      + '<span>🏭 行业轮动时序（' + _rotTs.period_count + '期季度 · ' + _rotTs.industries_count + '行业 · '
      + _rotD0 + ' ~ ' + _rotDN + '）</span>'
      + '<div class="pf-rot-range">'
      + '<button class="pf-rot-range-btn" data-rot-rng="3y" type="button">3年</button>'
      + '<button class="pf-rot-range-btn" data-rot-rng="5y" type="button">5年</button>'
      + '<button class="pf-rot-range-btn active" data-rot-rng="all" type="button">全部</button>'
      + '</div>'
      + '</div>'
      + '<div class="chart-subtitle" style="font-size:11px;color:var(--text-3);margin:0 0 4px 0;line-height:1.5">'
      + '堆叠面积图: 13行业平均权重% 跨基金(非求和), 反映典型基金行业配置占比变迁; 制造业(证监会超大类)占主导 ~58%, 金融/信息技术/通信服务/能源/材料为次主力'
      + '</div>'
      + '<div class="chart-subtitle" style="font-size:11px;color:var(--text-3);margin:0 0 4px 0;line-height:1.5">'
      + '📊 口径: 季报披露(基金行业配置), 134原始行业名合并为13标准名(GICS+证监会映射); 已过滤基金数&lt;50的脏数据期; 点击图例切换显示'
      + '</div>'
      + '<div class="chart pf-rot-chart" style="height:420px"></div>';
    container.appendChild(_rotCard);

    // 13行业色板(红金主题适配, 制造业主导用深红, 金融用金, 其余分类着色)
    const _ROT_COLORS = ['#c0392b', '#e67e22', '#f1c40f', '#3498db', '#2ecc71', '#9b59b6',
                         '#1abc9c', '#e74c3c', '#34495e', '#d35400', '#7f8c8d', '#27ae60', '#8e44ad'];
    const _rotChart = echarts.init(_rotCard.querySelector(".pf-rot-chart"));
    charts.push(_rotChart);

    // range 过滤: 按末日回推年数(3y=3年前, 5y=5年前, all=不过滤)
    const _rotFilter = (rng) => {
      if (rng === "all" || !_rotTs.series.length) return _rotTs.series;
      const last = _rotTs.series[_rotTs.series.length - 1].date;
      const lastY = parseInt(last.slice(0, 4), 10);
      const years = rng === "3y" ? 3 : 5;
      const cutoff = String(lastY - years) + last.slice(4);  // 同月同日, 年减
      return _rotTs.series.filter((s) => s.date >= cutoff);
    };

    const _renderRot = (rng) => {
      const filtered = _rotFilter(rng);
      const dates = filtered.map((s) => _pfFmtDate(s.date).slice(0, 7));
      // 按 industries_order 顺序构建 series(主导行业在下层, 堆叠从底到顶)
      const eSeries = _rotTs.industries_order.map((ind, i) => ({
        name: ind,
        type: "line",
        stack: "rot",
        areaStyle: { opacity: 0.65 },
        emphasis: { focus: "series" },
        lineStyle: { width: 1 },
        symbol: "circle",
        symbolSize: 5,
        showSymbol: false,
        itemStyle: { color: _ROT_COLORS[i % _ROT_COLORS.length] },
        data: filtered.map((s) => (s.industries[ind] != null ? s.industries[ind] : 0)),
      }));
      _rotChart.setOption({
        tooltip: { trigger: "axis", axisPointer: { type: "cross" },
          formatter: (params) => {
            if (!params || !params.length) return "";
            let html = '<div style="font-weight:600;margin-bottom:4px">' + params[0].axisValue + '</div>'
              + '<div style="font-size:11px;color:#888;margin-bottom:4px">基金覆盖: '
              + (filtered[params[0].dataIndex] ? filtered[params[0].dataIndex].fund_count : '-') + ' 只</div>';
            // 按值降序排
            const sorted = params.slice().sort((a, b) => b.value - a.value);
            for (const p of sorted) {
              if (p.value == null || p.value === 0) continue;
              html += '<div style="display:flex;align-items:center;gap:6px">'
                + '<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:' + p.color + '"></span>'
                + '<span style="flex:1">' + p.seriesName + '</span>'
                + '<b style="font-variant-numeric:tabular-nums">' + p.value.toFixed(2) + '%</b>'
                + '</div>';
            }
            return html;
          },
        },
        legend: { type: "scroll", bottom: 0, left: "center", textStyle: { fontSize: 11, color: "var(--text-2)" },
          itemWidth: 12, itemHeight: 8, pageIconColor: "#aaa", pageTextStyle: { color: "#888" } },
        grid: { left: 50, right: 20, top: 20, bottom: 50 },
        xAxis: { type: "category", boundaryGap: false, data: dates,
          axisLabel: { fontSize: 10, color: "var(--text-3)", rotate: dates.length > 20 ? 35 : 0 },
          axisLine: { lineStyle: { color: "var(--border)" } } },
        yAxis: { type: "value", name: "平均权重%", nameTextStyle: { fontSize: 10, color: "var(--text-3)" },
          axisLabel: { fontSize: 10, color: "var(--text-3)", formatter: "{value}%" },
          splitLine: { lineStyle: { color: "var(--border-light,var(--border))", type: "dashed" } } },
        series: eSeries,
      }, true);
    };

    _renderRot("all");
    // range 切换按钮
    _rotCard.querySelectorAll("[data-rot-rng]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const rng = btn.dataset.rotRng;
        _rotCard.querySelectorAll("[data-rot-rng]").forEach((b) => b.classList.toggle("active", b === btn));
        _renderRot(rng);
      });
    });
  }

  // ── 区域 4: 头部重仓股调仓 Top100 表(读 holdings.top100 取前100; 排序切换: 按变化率/按金额差; 指标 top20_adjustment 仍按 Top20 口径不变) ──
  const top100AdjCard = document.createElement("div");
  top100AdjCard.className = "chart-card";
  const top100AdjRaw = (holdings && holdings.top100 ? holdings.top100 : []).slice(0, 100);
  // 排序 comparator: 三态 sortState = { col: null|'amt'|'pct', dir: null|'asc'|'desc' }
  //   col=null 或 dir=null: 原报告顺序(top100AdjRaw 原序, 即按持仓市值降序)
  //   col='amt' dir='asc'/'desc': 按金额差(当期-上期, 带符号)升序/降序(asc 减仓最多在前; desc 加仓最多在前)
  //   col='pct' dir='asc'/'desc': 按变化率(带符号)升序/降序
  //   prev_value=null / change_pct=null 的行始终 append 在后(无数据不参与排序)
  const _amtSigned = (s) => s.prev_value != null ? (s.hold_value_total || 0) - (s.prev_value || 0) : null;
  // 四态分类: new=新进(prev_value=null 上期无当期有) / up=加仓(change_pct>0) / down=减仓(change_pct<0) / flat=持平(=0)
  const _top100State = (s) => {
    if (s.prev_value == null) return 'new';
    if (s.change_pct == null) return 'unknown';
    if (s.change_pct > 0) return 'up';
    if (s.change_pct < 0) return 'down';
    return 'flat';
  };
  // 四态标记 badge: A股配色(加仓红 #e6492e / 减仓绿 #2e8b57 / 新进橙 #ff9800 / 持平灰)
  const _top100StateBadge = (s) => {
    const st = _top100State(s);
    const map = {
      new: { icon: '🆕', label: '新进', color: '#ff9800' },
      up: { icon: '↑', label: '加仓', color: '#e6492e' },
      down: { icon: '↓', label: '减仓', color: '#2e8b57' },
      flat: { icon: '→', label: '持平', color: 'var(--text-3)' },
      unknown: { icon: '?', label: '未知', color: 'var(--text-3)' },
    };
    const m = map[st] || map.unknown;
    return `<span style="color:${m.color};font-weight:600;white-space:nowrap">${m.icon} ${m.label}</span>`;
  };
  // 排序 comparator: 三态 sortState = { col: null|'amt'|'pct', dir: null|'asc'|'desc' }
  //   col=null 或 dir=null: 原报告顺序(top100AdjRaw 原序, 即按持仓市值降序)
  //   col='amt' dir='asc'/'desc': 按金额差(当期-上期, 带符号)升序/降序(asc 减仓最多在前; desc 加仓最多在前)
  //   col='pct' dir='asc'/'desc': 按变化率(带符号)升序/降序
  //   prev_value=null / change_pct=null 的行始终 append 在后(无数据不参与排序)
  // filter: 'all'|'new'|'up'|'down' (四态筛选, 'all'=全部); 筛选后排序仅在筛选子集内做
  const _sortTop100Adj = (sortState, filter) => {
    const { col, dir } = sortState || {};
    const f = filter || 'all';
    const base = f === 'all' ? top100AdjRaw.slice() : top100AdjRaw.filter((s) => _top100State(s) === f);
    const withChg = base.filter((s) => s.change_pct != null).slice();
    const withoutChg = base.filter((s) => s.change_pct == null);
    if (col && dir) {
      withChg.sort((a, b) => {
        let va, vb;
        if (col === 'amt') {
          va = _amtSigned(a); vb = _amtSigned(b);
          if (va == null) va = -Infinity;
          if (vb == null) vb = -Infinity;
        } else {
          va = a.change_pct; vb = b.change_pct;
        }
        return dir === 'asc' ? va - vb : vb - va;
      });
    }
    return withChg.concat(withoutChg);
  };
  // 渲染 tbody HTML(给定已排序列表); 含"状态"列(四态标记 badge) + "金额差(万)"列 = |当期-上期|, 方向色(加仓红/减仓绿)
  const _renderTop100AdjRows = (list) => {
    if (!list.length) return '<tr><td colspan="10">暂无数据</td></tr>';
    let rows = "";
    list.forEach((s, i) => {
      const chgColor = s.change_pct > 0 ? "#e6492e" : s.change_pct < 0 ? "#2e8b57" : "var(--text-3)";
      const chgArrow = s.change_pct > 0 ? "↑" : s.change_pct < 0 ? "↓" : "->";
      const chgCell = s.change_pct == null
        ? '<span style="color:var(--text-3)">-</span>'
        : `${chgArrow} ${Math.abs(s.change_pct).toFixed(2)}%`;
      // 金额差 = 当期 - 上期(带符号判方向); 显示绝对值(万元); prev_value=null 显示"-"
      const amtSigned = _amtSigned(s);
      const amtColor = amtSigned != null ? (amtSigned > 0 ? "#e6492e" : amtSigned < 0 ? "#2e8b57" : "var(--text-3)") : "var(--text-3)";
      const amtCell = amtSigned != null
        ? `<span style="color:${amtColor};font-weight:600">${(Math.abs(amtSigned) / 1e4).toFixed(2)}</span>`
        : '<span style="color:var(--text-3)">-</span>';
      const indCell = s.stock_industry ? `<span class="pf-ind-tag">${s.stock_industry}</span>` : '<span style="color:var(--text-3)">-</span>';
      rows += `<tr>
        <td>${i + 1}</td>
        <td class="pf-top100-state">${_top100StateBadge(s)}</td>
        <td class="pf-code">${s.stock_code}</td>
        <td>${s.stock_name}</td>
        <td>${indCell}</td>
        <td class="pf-num">${s.fund_count}</td>
        <td class="pf-num">${(s.hold_value_total / 1e4).toFixed(2)}</td>
        <td class="pf-num">${s.prev_value != null ? (s.prev_value / 1e4).toFixed(2) : "-"}</td>
        <td class="pf-num">${amtCell}</td>
        <td class="pf-num" style="color:${chgColor};font-weight:600">${chgCell}</td>
      </tr>`;
    });
    return rows;
  };
  const adjPrevDate = holdings && holdings.prev_report_date ? _pfFmtDate(holdings.prev_report_date) : "";
  // 三态排序状态: { col: null|'amt'|'pct', dir: null|'asc'|'desc' }; null=null = 默认原报告顺序(两列显示 ⇅ 浅灰提示可排序)
  let top100AdjSort = { col: null, dir: null };
  // 四态筛选: 'all'|'new'|'up'|'down'; 'all'=全部(默认); 和排序正交(先筛后排)
  let top100AdjFilter = 'all';
  let top100AdjList = _sortTop100Adj(top100AdjSort, top100AdjFilter);
  // 四态计数(筛选用, 显示各态多少只): all=总数, new/up/down/flat=各态数
  const _top100Counts = () => {
    const c = { all: top100AdjRaw.length, new: 0, up: 0, down: 0, flat: 0 };
    top100AdjRaw.forEach((s) => { const st = _top100State(s); if (c[st] != null) c[st]++; });
    return c;
  };
  const _tc = _top100Counts();
  top100AdjCard.innerHTML = `<div class="chart-title" style="display:flex;align-items:center;flex-wrap:wrap;gap:8px">
      <span>🔄 头部重仓股调仓 Top100（当期 ${_pfFmtDate(reportDate)} 较 上期 ${adjPrevDate}；注: 调仓指标仍按前20大重仓股口径计算；点「金额差/变化」旁按钮三态切换: 默认->正序↑->倒序↓->默认）</span>
      <span style="display:inline-flex;gap:4px;flex-wrap:wrap;margin-left:auto">
        <button class="pf-ind-sort-btn pf-top100-filter active" data-filter="all" type="button">全部 ${_tc.all}</button>
        <button class="pf-ind-sort-btn pf-top100-filter" data-filter="new" type="button">🆕新进 ${_tc.new}</button>
        <button class="pf-ind-sort-btn pf-top100-filter" data-filter="up" type="button">↑加仓 ${_tc.up}</button>
        <button class="pf-ind-sort-btn pf-top100-filter" data-filter="down" type="button">↓减仓 ${_tc.down}</button>
      </span>
    </div>
    <div class="pf-table-wrap"><table class="pf-table pf-table-top100">
      <thead><tr>
        <th style="width:4%">#</th><th style="width:8%">状态</th><th style="width:7%">代码</th><th style="width:15%">名称</th><th style="width:9%">行业</th><th style="width:6%">基金数</th><th style="width:10%">当期(万)</th><th style="width:10%">上期(万)</th>
        <th style="width:16%;white-space:nowrap">金额差(万)<button class="pf-sort-btn" data-sort="amt" type="button" aria-label="按金额差排序"><span class="pf-sort-arrow"></span></button></th>
        <th style="width:15%;white-space:nowrap">变化<button class="pf-sort-btn" data-sort="pct" type="button" aria-label="按变化排序"><span class="pf-sort-arrow"></span></button></th>
      </tr></thead>
      <tbody id="pf-top100adj-body">${_renderTop100AdjRows(top100AdjList)}</tbody>
    </table></div>`;
  container.appendChild(top100AdjCard);
  // 三态排序: 重排 tbody + 更新按钮箭头(只动 tbody rows, 不动 thead/容器/列宽, 防布局跳动)
  // 注: 排序在当前 filter 子集内做(filter 变更由 _applyTop100AdjFilter 处理, 排序只重排已筛列表)
  const _applyTop100AdjSort = (sortState) => {
    top100AdjList = _sortTop100Adj(sortState, top100AdjFilter);
    const body = top100AdjCard.querySelector("#pf-top100adj-body");
    if (body) body.innerHTML = _renderTop100AdjRows(top100AdjList);
    // 更新两列按钮箭头 + active 态: 选中列有方向显示 ↑/↓ + active 红色, 未选中/默认显示 ⇅ 浅灰(提示可排序)
    top100AdjCard.querySelectorAll(".pf-sort-btn").forEach((btn) => {
      const col = btn.getAttribute("data-sort");
      const arrow = btn.querySelector(".pf-sort-arrow");
      if (sortState.col === col && sortState.dir) {
        arrow.textContent = sortState.dir === 'asc' ? '↑' : '↓';
        btn.classList.add('active');
      } else {
        arrow.textContent = '⇅';
        btn.classList.remove('active');
      }
    });
  };
  // 四态筛选: 重排 tbody(在筛选子集内保留当前排序) + 更新筛选按钮 active 态
  const _applyTop100AdjFilter = (filter) => {
    top100AdjFilter = filter;
    top100AdjList = _sortTop100Adj(top100AdjSort, top100AdjFilter);
    const body = top100AdjCard.querySelector("#pf-top100adj-body");
    if (body) body.innerHTML = _renderTop100AdjRows(top100AdjList);
    top100AdjCard.querySelectorAll(".pf-top100-filter").forEach((btn) => {
      if (btn.getAttribute("data-filter") === filter) btn.classList.add('active');
      else btn.classList.remove('active');
    });
  };
  // 点击按钮三态循环:
  //   点击同列(当前 col === 点击列): asc -> desc -> null(回默认原序)
  //   点击另一列(当前 col !== 点击列, 含 null): 切到该列, dir='asc'(正序)
  //   两列互斥: 点金额差时变化列重置(其按钮回默认 ⇅), 反之亦然(由 _applyTop100AdjSort 统一刷新两列按钮)
  top100AdjCard.querySelectorAll(".pf-sort-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const col = btn.getAttribute("data-sort");
      let newSort;
      if (top100AdjSort.col === col) {
        // 同列循环: asc -> desc -> null
        if (top100AdjSort.dir === 'asc') newSort = { col, dir: 'desc' };
        else if (top100AdjSort.dir === 'desc') newSort = { col: null, dir: null };
        else newSort = { col, dir: 'asc' }; // dir=null 兜底(切到新列时已是 asc, 此分支理论上不触发)
      } else {
        // 切到新列: dir='asc'
        newSort = { col, dir: 'asc' };
      }
      top100AdjSort = newSort;
      _applyTop100AdjSort(top100AdjSort);
    });
  });
  // 四态筛选按钮点击: 切 filter + 重绘 tbody(保留当前排序)
  top100AdjCard.querySelectorAll(".pf-top100-filter").forEach((btn) => {
    btn.addEventListener("click", () => {
      _applyTop100AdjFilter(btn.getAttribute("data-filter"));
    });
  });
  // 初始化按钮箭头(默认原序显示 ⇅ 浅灰; top100AdjList 已在 innerHTML 渲染, 重绘幂等)
  _applyTop100AdjSort(top100AdjSort);

  // 响应式 resize: mainChart/indChart/treemapChart 都要 resize(首次加载 grid 容器宽度可能延迟算完, init 拿到 0 宽度时靠这里恢复)
  // 注: treemap 曾不渲染的真根因是 vendor/echarts.min.js 用了 common 精简版(629KB 不含 treemap 组件), setOption 静默失败;
  //     已换完整版 echarts@5.6.0(1MB 含 treemap 组件), 此处 resize 仅兜底首帧 0 宽场景
  // top30 卡高度同步: 显式 height=top30=indCard 高度, 让 top30 自然高度=indCard 不撑高 grid cell(grid stretch 取 max, top30 表格 30 行会撑高 cell 致 indCard 底部留白); 表格 flex:1+overflow:auto 在卡内滚动
  const _syncTop30H = () => {
    if (top30Card && indCard) {
      const h = indCard.offsetHeight;
      if (h > 0) top30Card.style.height = h + "px";
    }
  };
  setTimeout(() => { mainChart.resize(); indChart.resize(); treemapChart.resize(); _syncTop30H(); }, 0);
  requestAnimationFrame(() => { treemapChart.resize(); _syncTop30H(); });
  window.addEventListener("resize", _pfResizeHandler);
}

// ════════════════════════════════════════════════════════════════════
// 阶段 J + K: 首页公募基金信号卡
// ════════════════════════════════════════════════════════════════════
// 位置: 首页右列(冰点日/买卖点/汪汪队之后), 作为「机构资金视角」补充
// 内容:
//   J  角标行: 基金仓位 avg_position% + 较上季变化↑↓ + 88魔咒颜色(>88红/80-88黄/<80绿) + ⚠️警示
//   K1 信号灯: 4 条规则(88魔咒见顶 / 80抄底 / 抱团瓦解 / 净申赎反向), 触发时显示对应红/绿/橙徽标
//   K2 4 维共振: 北向 + 两融 + 主力(产业资本代理) + 基金持仓(第4维), 4 维同向看多/看空才标共振
// 滞后性: 基金数据季报披露滞后15天, 文案带「数据滞后」提示
// 点击角标/标题跳转 sentiment/public-fund 二级 tab
async function _renderPublicFundHomeCard(host, r, snap) {
  const card = document.createElement("div");
  card.className = "chart-card pf-home-card";
  card.innerHTML = '<h3>🏦 基金仓位信号 <span class="pf-home-loading">加载中…</span></h3>';
  host.appendChild(card);

  let summary;
  try {
    summary = await fetchJSON("https://ssd.fx8.store/public_fund/public_fund_summary.json").catch(() => null);
    if (!summary || !summary.metrics) {
      card.innerHTML = '<h3>🏦 基金仓位信号</h3><div class="empty-note">暂无公募基金数据</div>';
      return;
    }
  } catch (e) {
    card.innerHTML = '<h3>🏦 基金仓位信号</h3><div class="empty-note">加载失败</div>';
    return;
  }
  // 渲染期间用户切了 tab, 回调不再渲染(防串扰)
  if (state.tab !== "overview") return;

  const metricsMap = {};
  (summary.metrics || []).forEach((m) => { metricsMap[m.metric_id] = m; });
  const avgPos = metricsMap["avg_position"];            // 平均股票仓位%(lg 口径)
  const conc = metricsMap["concentration_herfindahl"];  // 抱团度 HHI
  const netRedeem = metricsMap["net_redeem_ratio"];     // 净申赎率%
  const indConc = metricsMap["industry_concentration"]; // 行业集中度(辅助)
  const _pfFmtDate = (s) => s && String(s).length === 8 ? `${s.slice(0,4)}-${s.slice(4,6)}-${s.slice(6,8)}` : (s || "");

  // ── 计算仓位较上季变化(lg 口径 position_history 末两点) ──
  let avgPosDelta = null;
  if (summary.position_history && summary.position_history.length >= 2) {
    const lgHist = summary.position_history.filter((h) => h.source === "lg").sort((a, b) => a.report_date.localeCompare(b.report_date));
    if (lgHist.length >= 2) {
      const n = lgHist.length;
      avgPosDelta = +(lgHist[n-1].position_pct - lgHist[n-2].position_pct).toFixed(2);
    }
  }
  // 抱团度变化(无 history 字段, 用 detail.top10_stocks 估算? 不准 -> 仅用 concentration_herfindahl 当前值判定, 变化方向置 null)
  // 注:summary 无 conc_history,「抱团瓦解」信号改用 top20_adjustment 环比 + 当前 HHI 综合判定(下文 _pfSignals)
  const top20Adj = metricsMap["top20_adjustment"];       // Top20 调仓环比%

  const avgPosVal = avgPos ? avgPos.metric_value : null;
  const concVal = conc ? conc.metric_value : null;
  const netRedeemVal = netRedeem ? netRedeem.metric_value : null;
  const reportDate = summary.report_date || "";

  // ── 阶段 J: 角标颜色(88 魔咒) ──
  const _pfPosColor = (v) => {
    if (v == null) return "var(--text-3)";
    if (v > 88) return "#e6492e";  // 红 高位警示
    if (v >= 80) return "#ff9800"; // 黄 中位
    return "#2e8b57";              // 绿 低位机会
  };
  const posColor = _pfPosColor(avgPosVal);
  const is88Mazhu = avgPosVal != null && avgPosVal > 88;
  const is80Chao = avgPosVal != null && avgPosVal < 80;
  // 变化箭头(仓位↑红 / ↓绿, 与A股配色一致)
  const _deltaHtml = (delta, unit) => {
    if (delta == null) return '<span style="color:var(--text-3)">较上季 -</span>';
    const arrow = delta > 0 ? "↑" : delta < 0 ? "↓" : "→";
    const color = delta === 0 ? "var(--text-3)" : (delta > 0 ? "#e6492e" : "#2e8b57");
    const sign = delta > 0 ? "+" : "";
    return `<span style="color:${color};font-weight:600">较上季 ${arrow} ${sign}${delta.toFixed(2)}${unit || ""}</span>`;
  };

  // ── 阶段 K1: 4 条信号灯规则 ──
  // ① 88魔咒见顶: avg_position >88% -> 红
  // ② 80抄底: avg_position <80% -> 绿
  // ③ 抱团瓦解: top20_adjustment 显著负(<-5%) OR concentration_herfindahl 较上季显著下降 -> 红(瓦解风险)
  //   注: summary 无 conc 历史, 用 top20_adjustment 环比(头部重仓调仓) 作瓦解代理: 大幅减持=瓦解信号
  // ④ 净申赎反向: net_redeem_ratio 显著负(<-0.5%, 净赎回) + 仓位高位(>88%) -> 橙(散户离场, 反向看多)
  const _pfSignals = [];
  if (is88Mazhu) {
    _pfSignals.push({
      cls: "pf-sig-red",
      icon: "⚠️",
      title: "88 魔咒见顶",
      desc: `基金仓位 ${avgPosVal.toFixed(2)}% > 88%，加仓空间有限，历史多对应阶段性顶部（2009/7、2015/5、2021/1 等）。数据滞后，仅作风险提示。`,
    });
  }
  if (is80Chao) {
    _pfSignals.push({
      cls: "pf-sig-green",
      icon: "✅",
      title: "80 抄底机会",
      desc: `基金仓位 ${avgPosVal.toFixed(2)}% < 80%，仓位低有加仓空间，历史多对应阶段性底部。数据滞后，仅作辅助参考。`,
    });
  }
  if (top20Adj && top20Adj.metric_value != null && top20Adj.metric_value < -5) {
    _pfSignals.push({
      cls: "pf-sig-red",
      icon: "💥",
      title: "抱团瓦解信号",
      desc: `头部重仓 Top20 调仓环比 ${top20Adj.metric_value.toFixed(2)}%（显著减持），机构集中减仓龙头，抱团瓦解风险。数据滞后，仅作风险提示。`,
    });
  }
  if (netRedeemVal != null && netRedeemVal < -0.5 && avgPosVal != null && avgPosVal > 88) {
    _pfSignals.push({
      cls: "pf-sig-orange",
      icon: "🔄",
      title: "净赎回反向（散户离场）",
      desc: `净申赎率 ${netRedeemVal.toFixed(3)}%（净赎回，散户悲观离场）+ 仓位高位 ${avgPosVal.toFixed(2)}%。散户反向指标，净赎回常对应阶段底部附近。数据滞后。`,
    });
  }

  // ── 阶段 K2: 4 维资金面共振 ──
  // 4 维: 北向(a_fund_north) + 两融(a_fund_margin) + 主力/产业资本(a_fund_main) + 基金持仓(avg_position 环比)
  // 数据源: overview.json r.today.metrics 的 3 维 + summary.position_history 的基金维度
  // 方向判定: 北向=成交总额无方向(停更前用净买额, 现仅活跃度) -> 不参与方向共振, 改用主力作产业资本代理
  // 实际4维(适配数据可得性): 两融余额环比 / 主力净流入正负 / 北向成交额环比 / 基金仓位环比
  // 说明: 北向原净买额 2024-08 停更, 现成交总额只反映活跃度不反映方向, 此维用「成交额环比」作活跃度方向
  //      (放量=活跃度升=偏多情绪, 缩量=活跃度降=偏空情绪), 与原净买额方向语义不完全等价, 注释说明
  const metrics = (r && r.today && r.today.metrics) || [];
  const _findM = (id) => metrics.find((m) => m.id === id);
  const north = _findM("a_fund_north");   // 北向成交总额(亿)
  const margin = _findM("a_fund_margin"); // 两融余额(亿)
  const main = _findM("a_fund_main");     // 主力净流入(亿)

  // 各维方向需要历史末两点对比 -> 取 a-stock-3m.json(EXPORT_RANGES 含 3m, 有 62 点可算环比; 1m 不在 EXPORT_RANGES 会 404)
  // 但首页已加载 overview, 无历史时序 -> 用 main.value 正负(主力净流入正=做多, 负=做空)作方向
  // 两融/北向无方向值, 只能取环比 -> 暂用单点值 + 涨跌标签(若 metrics 有 signal 字段则用, 否则置 unknown)
  // 为避免误导, 4 维共振用「明确同向」判定: 4 维都明确看多/看空才共振; 任一 unknown 或方向不一致 -> 不标共振
  const _dir = {
    fund: avgPosDelta != null ? (avgPosDelta > 0 ? "多" : avgPosDelta < 0 ? "空" : "平") : "unknown", // 基金加仓=多, 减仓=空
    main: main && main.value != null ? (main.value > 0 ? "多" : main.value < 0 ? "空" : "平") : "unknown", // 主力净流入正=多, 负=空
    // 两融/北向单点值无方向, 需历史对比 -> fetch a-stock-3m.json 末两点(下文异步)
    margin: "unknown",
    north: "unknown",
  };
  // 异步补全两融/北向方向(末两点对比)
  try {
    const hist = await fetchJSON("./data/a-stock-3m.json").catch(() => null);
    if (hist && hist.metrics) {
      const _last2 = (id) => {
        const m = hist.metrics[id];
        if (!m || !m.data || m.data.length < 2) return [null, null];
        const n = m.data.length;
        return [m.data[n-2].value, m.data[n-1].value];
      };
      const [marginPrev, marginCur] = _last2("a_fund_margin");
      if (marginPrev != null && marginCur != null) {
        _dir.margin = marginCur > marginPrev ? "多" : marginCur < marginPrev ? "空" : "平"; // 两融余额增=杠杆做多升=多
      }
      const [northPrev, northCur] = _last2("a_fund_north");
      if (northPrev != null && northCur != null) {
        _dir.north = northCur > northPrev ? "多" : northCur < northPrev ? "空" : "平"; // 北向成交额放量=活跃度升=偏多(语义弱, 注释)
      }
    }
  } catch {}

  // 共振判定: 4 维都明确(非 unknown 非 平) 且同向
  const _dirs = [_dir.fund, _dir.main, _dir.margin, _dir.north];
  const _allKnown = _dirs.every((d) => d === "多" || d === "空");
  const _allSame = _allKnown && _dirs.every((d) => d === _dirs[0]);
  const _resonance = _allSame ? (_dirs[0] === "多" ? "看多" : "看空") : null;

  // ── 渲染 ──
  // 自包含样式(只注入一次)
  if (!document.getElementById("pf-home-style")) {
    const st = document.createElement("style");
    st.id = "pf-home-style";
    st.textContent = `
.pf-home-card{cursor:pointer;}
.pf-home-card h3{display:flex;align-items:center;flex-wrap:wrap;gap:6px;}
.pf-home-loading{font-size:12px;color:var(--text-3);font-weight:400;}
.pf-home-badge{display:inline-flex;align-items:center;gap:4px;padding:3px 10px;border-radius:14px;font-size:13px;font-weight:600;border:1.5px solid;}
.pf-home-badge .pf-home-val{font-size:15px;}
.pf-home-badge .pf-home-delta{font-size:11px;opacity:0.85;}
.pf-home-stale{font-size:11px;color:var(--text-3);margin-left:6px;}
.pf-sig-list{display:flex;flex-direction:column;gap:6px;margin:8px 0;}
.pf-sig-item{display:flex;gap:8px;padding:7px 10px;border-radius:6px;font-size:12.5px;line-height:1.5;border-left:3px solid;}
.pf-sig-item .pf-sig-icon{font-size:15px;flex-shrink:0;}
.pf-sig-item .pf-sig-text b{font-weight:600;}
.pf-sig-item .pf-sig-desc{color:var(--text-3);font-size:11.5px;margin-top:2px;}
.pf-sig-red{background:rgba(230,73,46,0.08);border-color:#e6492e;color:#e6492e;}
.pf-sig-green{background:rgba(46,139,87,0.08);border-color:#2e8b57;color:#2e8b57;}
.pf-sig-orange{background:rgba(255,152,0,0.08);border-color:#ff9800;color:#ff9800;}
.pf-resonance{margin-top:8px;padding:8px 10px;border-radius:6px;font-size:12.5px;line-height:1.6;background:var(--bg-hover);border-left:3px solid var(--border-strong);}
.pf-resonance-title{font-weight:600;color:var(--text-1);margin-bottom:4px;}
.pf-resonance-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));gap:6px;margin-top:6px;}
.pf-resonance-cell{padding:5px 8px;border-radius:4px;background:var(--bg-card,var(--bg-1));font-size:11.5px;border:1px solid var(--border-light,var(--border));}
.pf-resonance-cell .pf-rc-name{color:var(--text-3);font-size:10.5px;}
.pf-resonance-cell .pf-rc-dir{font-weight:600;margin-top:2px;}
.pf-rc-up{color:#e6492e;}
.pf-rc-down{color:#2e8b57;}
.pf-rc-flat{color:var(--text-3);}
.pf-rc-unknown{color:var(--text-3);font-style:italic;}
.pf-resonance-badge{display:inline-block;padding:3px 10px;border-radius:4px;font-weight:700;font-size:13px;margin-left:6px;}
.pf-resonance-bull{background:rgba(230,73,46,0.15);color:#e6492e;border:1px solid #e6492e;}
.pf-resonance-bear{background:rgba(46,139,87,0.15);color:#2e8b57;border:1px solid #2e8b57;}
.pf-resonance-none{background:var(--bg-hover);color:var(--text-3);border:1px solid var(--border-light,var(--border));font-weight:400;}
.pf-home-hint{margin-top:6px;font-size:11px;color:var(--text-3);line-height:1.5;}
`;
    document.head.appendChild(st);
  }

  // 角标 HTML
  const _warnIcon = is88Mazhu ? " ⚠️" : "";
  const badgeHtml = avgPosVal != null
    ? `<span class="pf-home-badge" style="color:${posColor};border-color:${posColor};background:${posColor}15">
         <span>基金仓位</span>
         <span class="pf-home-val">${avgPosVal.toFixed(2)}%</span>
         <span class="pf-home-delta">${_deltaHtml(avgPosDelta, "pct")}</span>
         ${_warnIcon}
       </span>`
    : '<span class="pf-home-badge" style="color:var(--text-3);border-color:var(--border)">基金仓位 -</span>';

  // 4 维方向单元格
  const _dirCell = (name, d) => {
    const cls = d === "多" ? "pf-rc-up" : d === "空" ? "pf-rc-down" : d === "平" ? "pf-rc-flat" : "pf-rc-unknown";
    const label = d === "unknown" ? "暂无" : d;
    return `<div class="pf-resonance-cell"><div class="pf-rc-name">${name}</div><div class="pf-rc-dir ${cls}">${label}</div></div>`;
  };
  // 共振徽标
  const _resBadge = _resonance === "看多"
    ? '<span class="pf-resonance-badge pf-resonance-bull">4 维共振看多</span>'
    : _resonance === "看空"
    ? '<span class="pf-resonance-badge pf-resonance-bear">4 维共振看空</span>'
    : '<span class="pf-resonance-badge pf-resonance-none">4 维方向不一 · 暂无共振</span>';

  // 信号灯列表 HTML(无触发时显示「中性」提示)
  const _sigListHtml = _pfSignals.length
    ? _pfSignals.map((s) => `<div class="pf-sig-item ${s.cls}">
        <span class="pf-sig-icon">${s.icon}</span>
        <div class="pf-sig-text"><b>${s.title}</b><div class="pf-sig-desc">${s.desc}</div></div>
      </div>`).join("")
    : '<div class="pf-sig-item" style="background:var(--bg-hover);border-left:3px solid var(--border-strong);color:var(--text-3);"><span class="pf-sig-icon">•</span><div class="pf-sig-text">当前无基金信号触发（仓位处于 80-88% 中性区间）</div></div>';

  card.innerHTML =
    '<h3>🏦 基金仓位信号' +
      termTip("公募基金持仓作第4维资金面(补充北向/两融/产业资本)。88魔咒=平均仓位>88%见顶警示;80抄底=<80%抄底机会;抱团瓦解=Top20显著减持;净赎回反向=净赎回+高位(散户离场反向看多)。季报披露滞后15天,仅作辅助参考。点击进入公募基金 tab 查看完整持仓。") +
    '</h3>' +
    `<div style="display:flex;align-items:center;flex-wrap:wrap;gap:8px;margin:6px 0 8px">
       ${badgeHtml}
       <span class="pf-home-stale">📊 数据截止 ${_pfFmtDate(reportDate)}（季报滞后约 15 天）</span>
     </div>` +
    `<div class="pf-sig-list">${_sigListHtml}</div>` +
    `<div class="pf-resonance">
       <div class="pf-resonance-title">🔀 4 维资金面共振 ${_resBadge}</div>
       <div style="font-size:11.5px;color:var(--text-3);margin-top:4px">4 维同向(皆多/皆空)才标共振;任一方向不明或不一致则不共振,避免误导。</div>
       <div class="pf-resonance-grid">
         ${_dirCell("北向(成交额环比)", _dir.north)}
         ${_dirCell("两融(余额环比)", _dir.margin)}
         ${_dirCell("主力(净流入正负)", _dir.main)}
         ${_dirCell("基金(仓位环比)", _dir.fund)}
       </div>
       <div class="pf-home-hint">注:北向原净买额 2024-08 停更,现用成交总额环比作活跃度方向(语义弱于净买额);主力=产业资本代理(大单净流入);基金=季报仓位环比。4 维频率不同(日/日/日/季),基金维更新慢。</div>
     </div>`;

  // 任务10(2026-07-20): 4维共振区块 + 信号灯 click -> 弹窗(不跳转), stopPropagation 防触发整卡跳转
  const _resonanceEl = card.querySelector(".pf-resonance");
  if (_resonanceEl) {
    _resonanceEl.style.cursor = "pointer";
    _resonanceEl.addEventListener("click", (e) => {
      e.stopPropagation();
      _openPfHomeModal("🔀 4 维资金面共振", _pfResonanceModalHtml(_dir, _resonance, _resBadge, { north, margin, main, avgPosVal, avgPosDelta }));
    });
  }
  // 信号灯(88魔咒/80抄底/抱团瓦解/净赎回反向) click -> 弹窗(不跳转)
  const _sigItems = card.querySelectorAll(".pf-sig-item");
  _sigItems.forEach((el, i) => {
    const _sig = _pfSignals[i];
    if (!_sig) return;  // 中性提示项(无数据)不绑
    el.style.cursor = "pointer";
    el.addEventListener("click", (e) => {
      e.stopPropagation();
      _openPfHomeModal(`${_sig.icon} ${_sig.title}`, _pfSignalModalHtml(_sig, { avgPosVal, reportDate }));
    });
  });

  // 点击整卡跳转 sentiment/public-fund 二级 tab(4维共振/信号灯已 stopPropagation 不触发此 handler)
  card.addEventListener("click", (e) => {
    // 点击 termTip ❓ / 4维共振 / 信号灯 不跳转(已 stopPropagation 兜底)
    if (e.target.closest(".term-tip")) return;
    state.tab = "sentiment";
    state.subtab = "public-fund";
    document.querySelectorAll("button[data-tab]").forEach((x) => x.classList.remove("active"));
    const btn = document.querySelector('button[data-tab="sentiment"]');
    if (btn) btn.classList.add("active");
    updateH5Topbar();
    _setTabHash(state.tab);
    renderTab();
  });
}

// 任务10(2026-07-20): 首页基金卡弹窗(4维共振/信号灯详情, 不跳转公募基金页, 复用 rule-modal 框架)
function _openPfHomeModal(title, contentHtml) {
  let modal = document.getElementById("pfHomeModal");
  const isFirst = !modal;
  if (isFirst) {
    modal = document.createElement("div");
    modal.id = "pfHomeModal";
    modal.className = "rule-modal hidden";
    document.body.appendChild(modal);
  }
  modal.innerHTML = '<div class="rule-modal-overlay"></div><div class="rule-modal-body"><div class="rule-modal-header"><h3>' + title + '</h3><button class="rule-modal-close" aria-label="关闭">&times;</button></div><div class="rule-modal-content">' + contentHtml + '</div></div>';
  const _close = () => { modal.classList.add("hidden"); document.body.style.overflow = ""; };
  modal.querySelector(".rule-modal-overlay").addEventListener("click", _close);
  modal.querySelector(".rule-modal-close").addEventListener("click", _close);
  if (isFirst) {
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !modal.classList.contains("hidden")) _close(); });
  }
  modal.classList.remove("hidden");
  document.body.style.overflow = "hidden";
}

// 4维共振弹窗内容(方向详情 + 共振徽标 + 概念说明)
function _pfResonanceModalHtml(_dir, _resonance, _resBadge, data) {
  const _dirDetail = (name, d, val, source) => {
    const cls = d === "多" ? "pf-rc-up" : d === "空" ? "pf-rc-down" : d === "平" ? "pf-rc-flat" : "pf-rc-unknown";
    const label = d === "unknown" ? "暂无" : d;
    return '<div class="pf-resonance-cell" style="text-align:left">' +
      '<div class="pf-rc-name">' + name + '</div>' +
      '<div class="pf-rc-dir ' + cls + '" style="font-size:14px">' + label + '</div>' +
      '<div style="font-size:10.5px;color:var(--text-3);margin-top:2px">当前值: ' + (val || "-") + ' · ' + source + '</div>' +
    '</div>';
  };
  const _northVal = data.north && data.north.value != null ? data.north.value.toFixed(2) + "亿" : "-";
  const _marginVal = data.margin && data.margin.value != null ? data.margin.value.toFixed(2) + "亿" : "-";
  const _mainVal = data.main && data.main.value != null ? data.main.value.toFixed(2) + "亿" : "-";
  const _fundVal = data.avgPosVal != null ? data.avgPosVal.toFixed(2) + "%" : "-";
  return '<div style="margin-bottom:12px">' + _resBadge + '</div>' +
    '<div class="pf-resonance-grid" style="margin-bottom:12px">' +
      _dirDetail("北向(成交额环比)", _dir.north, _northVal, "HKEX T+1") +
      _dirDetail("两融(余额环比)", _dir.margin, _marginVal, "上交所 T+1") +
      _dirDetail("主力(净流入正负)", _dir.main, _mainVal, "akshare 盘中实时") +
      _dirDetail("基金(仓位环比)", _dir.fund, _fundVal, "lg 季报滞后15天") +
    '</div>' +
    '<div class="pf-help-body" style="margin-bottom:12px">' +
      '<div><b>概念说明</b>：4维资金面共振 = 北向(外资) + 两融(杠杆) + 主力(产业资本代理) + 基金(机构) 4维同向才共振。</div>' +
      '<ul>' +
        '<li><b>北向</b>：沪深股通成交总额(原净买额2024-08停更,现用成交额环比作活跃度方向)。T+1披露,放量=活跃度升=偏多。</li>' +
        '<li><b>两融</b>：融资余额(杠杆资金)。T+1披露,余额增=杠杆做多升=多。</li>' +
        '<li><b>主力</b>：大单净流入(产业资本代理)。盘中实时,正=多负=空。</li>' +
        '<li><b>基金</b>：平均股票仓位环比(机构)。季频,季报滞后15天,加仓=多减仓=空。</li>' +
      '</ul>' +
      '<div>4维同向(皆多/皆空)才标共振;任一方向不明或不一致则不共振,避免误导。4维频率不同(日/日/日/季),基金维更新慢。</div>' +
    '</div>' +
    '<div class="pf-modal-tip">💡 点击卡片标题/仓位角标可跳转公募基金页查看完整持仓。</div>';
}

// 信号灯弹窗内容(88魔咒/80抄底/抱团瓦解/净赎回反向 详情 + 概念说明)
function _pfSignalModalHtml(sig, data) {
  return '<div class="pf-sig-item ' + sig.cls + '" style="margin-bottom:12px">' +
      '<span class="pf-sig-icon">' + sig.icon + '</span>' +
      '<div class="pf-sig-text"><b>' + sig.title + '</b><div class="pf-sig-desc">' + sig.desc + '</div></div>' +
    '</div>' +
    '<div class="pf-help-body" style="margin-bottom:12px">' +
      '<div><b>当前仓位</b>：' + (data.avgPosVal != null ? data.avgPosVal.toFixed(2) + '%' : '-') + '（数据截止 ' + (data.reportDate || '-') + '，季报滞后约15天）</div>' +
      '<div class="pf-help-warn">⚠ 本信号为辅助参考维度，滞后性强不作主信号；88魔咒为历史规律未必未来应验。研究参考，不构成投资建议。</div>' +
    '</div>' +
    '<div class="pf-modal-tip">💡 点击卡片标题/仓位角标可跳转公募基金页查看完整持仓。</div>';
}

let _pfResizeTimer = null;
function _pfResizeHandler() {
  if (_pfResizeTimer) clearTimeout(_pfResizeTimer);
  _pfResizeTimer = setTimeout(() => {
    // 只 resize 仍挂载的 pf 图表（dispose 的会被 _disposeContainerCharts 清理）
    document.querySelectorAll(".pf-main-chart-card .chart, .pf-ind-chart-card .chart, .pf-two-col .chart").forEach((dom) => {
      const inst = echarts.getInstanceByDom(dom);
      if (inst) inst.resize();
    });
    // top30 卡高度同步 = 行业配置卡高度(echarts resize 后 indCard 高度可能变, rAF 等 resize 完成再测)
    document.querySelectorAll(".pf-two-col").forEach((row) => {
      const top30 = row.querySelector(".pf-top30-card");
      const ind = row.querySelector(".chart-card:not(.pf-top30-card)");
      if (top30 && ind && ind.offsetHeight > 0) {
        requestAnimationFrame(() => { top30.style.height = ind.offsetHeight + "px"; });
      }
    });
  }, 150);
}

// 市场温度二级 subtab：冰点/过热热力图 + 恐贪/A股情绪分/6宽基/跨市场（原 renderSentiment 主体，期货已归 futures subtab）
async function renderSentimentMarketTemp(container) {
  let r;
  try {
    r = await fetchJSON(dataUrl(`sentiment-${state.range}.json`));
  } catch (e) {
    renderErrorState(container, e, () => renderSentimentMarketTemp(container));
    return;
  }
  // 拉取盘中快照，供情绪大卡右上角角标判断盘中/收盘状态（1.5s 超时兜底，不阻塞渲染）
  try { await Promise.race([fetchIntradaySnapshot(), new Promise((r) => setTimeout(r, 1500))]); } catch {}
  const snap = state.intradaySnapshot;
  container.innerHTML = "";  // 清 loading 开始渲染（loading 由 renderSentiment 分发器 L9362 塞入，对齐 renderGlobal L9119 模式）
  // purpose note + crosslink 只在此 tab 显示（共通区已下沉，避免期货/汪汪队上方出现"温度计"提示）
  renderPurposeNote(container, PURPOSE_NOTES["sentiment"]);
  container.insertAdjacentHTML("beforeend", '<div class="tab-crosslink-note">ℹ️ 本页看<b>市场温度</b>+冰点/过热热力图;想看指数<b>价格走势</b>-> 去<a data-goto="market" role="button" tabindex="0">【指数表现】</a></div>');
  _bindTabCrosslink(container, "market");
  const sig = r.signals || {};
  const stats = r.stats || {};
  const strat = r.strategy || {};

  // 冰点/过热热力图（一眼全局，放最前面）
  renderSentimentHeatmap(r, snap, container);

  // 情绪图表区套 .indices-grid 3列网格(与A股/港股/全球同布局)，每张图+组成因子配对一个 grid cell
  const cardGrid = document.createElement("div");
  cardGrid.className = "indices-grid";
  container.appendChild(cardGrid);

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
    }, undefined, undefined, "fear_greed", cell);
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
    }, stats.a_sentiment, strat.a_sentiment, "a_sentiment", cell);
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
      const title = `${baseTitle}（0-100）` + termTip("该指数RSI+涨跌幅等权算的0-100情绪分(等权,非加权)。≤20冰点≥80过热。比A股综合情绪分更聚焦单只指数。") + (latest != null ? " · " + sentimentTag(latest) + latestSuffixPct(data) : "");
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
        }, stats[key], strat[key], key, cell);
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
    }, stats.cross_market, strat.cross_market, "cross_market", cell);
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
  // 期货已归入 sentiment 二级 futures subtab（renderFutures），此处不再渲染
}

// 情绪冰点/过热热力图：X 轴=日期，Y 轴=指数名，色块=蓝(冰点≤20)/红(过热>80)/灰(中性)
function renderSentimentHeatmap(r, snap, container) {
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
  container.appendChild(div);
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
function renderFuturesSection(data, snap, container, accTrend, accConclusion) {
  if (!data || !data.positions || !data.positions.length) return;
  // P0-5: container 可选，默认 content（兼容情绪 tab 内嵌调用）；期货独立 subtab 传入 subContent
  const _fgHost = container || content;

  const roles = ["机构(前20)", "中信期货", "国泰君安"];
  const products = ["沪深300期货", "中证500期货", "上证50期货", "中证1000期货", "综合"];

  // follow_ratio 列 join 用的辅助映射：role_key -> {date -> follow_ratio}
  // accTrend.series 结构 {中信期货:[{date,follow_ratio,...}], 机构前20:[...], 国泰君安:[...]}
  // 表①②③按 date join 展示当日15日follow_ratio%，极端值(<=30%/>=80%)高亮预警
  const _accFrMap = {};
  if (accTrend && accTrend.series) {
    for (const [roleKey, pts] of Object.entries(accTrend.series)) {
      const m = {};
      if (Array.isArray(pts)) pts.forEach(p => { if (p && p.date != null) m[p.date] = p; });
      _accFrMap[roleKey] = m;
    }
  }
  // 表①② titlePrefix -> accTrend role key 映射
  const _prefixToRoleKey = { "中信": "中信期货", "机构": "机构前20", "国君": "国泰君安" };
  // 格式化 follow_ratio 单元格：所有非空单元格都有 hover 明细（同向准确度/主导方向/历史准确率/样本区间），
  // 极端值(<=30%/>=80%)追加抄底/顶部预警历史统计 + 着色 acc-cell-low/high + <small> 标签
  const _fmtFrCell = (pt) => {
    if (!pt || pt.follow_ratio == null) return { text: "-", cls: "", title: "" };
    const fr = pt.follow_ratio;
    let cls = "", suffix = "";
    const dir = pt.dominant_dir || "-";
    const same = pt.same_count != null ? pt.same_count : "-";
    const contra = pt.contrarian_count != null ? pt.contrarian_count : "-";
    const tot = pt.total != null ? pt.total : "-";
    const acc = pt.accuracy != null ? pt.accuracy.toFixed(1) : "-";
    const ss = pt.sample_start || "-";
    const se = pt.sample_end || "-";
    let title = `同向准确度 ${fr.toFixed(1)}%(${same}同向/${contra}逆向,共${tot}日)\n主导方向：${dir}\n历史准确率：${acc}%\n样本区间：${ss}-${se}`;
    if (fr <= 30) {
      cls = "acc-cell-low";
      suffix = "<br><small>抄底信号</small>";
      title += "\n⚠ 抄底信号：历史34次中33次(97%)后20日正收益";
    } else if (fr >= 80) {
      cls = "acc-cell-high";
      suffix = "<br><small>顶部预警</small>";
      title += "\n⚠ 顶部预警：历史22次中15次(68%)后20日负收益";
    }
    return { text: fr.toFixed(1) + "%" + suffix, cls, title };
  };

  // 期货区统一套 .indices-grid 3列网格(最小宽度700)：表格卡+折线图+说明卡同网格，视觉统一
  const fgGrid = document.createElement("div");
  fgGrid.className = "indices-grid";
  _fgHost.appendChild(fgGrid);

  // 2.5 中信/机构 4品种合计净加仓 15天明细表（拆成两类：准确率合并表×1 + 净加多空表×2）
  // 需求2合并: 中信+机构 多空单同向准确率合并表（7列：日期|中信方向|中信次日涨跌|中信对错|机构方向|机构次日涨跌|机构对错）
  const _renderMergedAccuracyCard = (citicCd, instCd, host, sharedDates) => {
    if (!citicCd && !instCd) return;
    const div = document.createElement("div");
    div.className = "chart-card futures-table-card";
    // 日期集：优先用传入 sharedDates（3表对齐），否则自算并集
    const allDates = sharedDates && sharedDates.length
      ? [...sharedDates].sort()
      : [...new Set([...((citicCd && citicCd.details) ? citicCd.details.map(d => d.date).filter(Boolean) : []), ...((instCd && instCd.details) ? instCd.details.map(d => d.date).filter(Boolean) : [])])].sort();
    const latestDetailDate = allDates.length ? allDates[allDates.length - 1] : "";
    const detailSuffix = latestDetailDate ? `<span class="chart-latest"> · ${fmtDate(latestDetailDate)}</span>` : "";
    // 标题：显示两角色各自主导方向
    const citicDir = citicCd ? citicCd.dominant_dir : "-";
    const instDir = instCd ? instCd.dominant_dir : "-";
    let html = `<h3>中信/机构 多空单同向准确率（中信${citicDir}/机构${instDir}）${detailSuffix}</h3>`;
    html += `<div class="futures-note">最近15个交易日中信期货 vs 机构(前20会员) 4品种合计净加仓方向 vs 上证指数次日涨跌。主导方向按同向/逆向天数判定，每日对错按各自主导方向判断。首行为当天（次日涨跌待收盘）。</div>`;
    // 合并统计副标题：中信 同向X%(Y对Z错) | 机构 同向X%(Y对Z错) — X%按准确率着色(>55%绿/#16a34a, <=55%红/#dc2626, 同 acc-good/acc-bad)
    const fmtStat = (cd) => {
      if (!cd) return "-";
      const accColor = cd.accuracy > 55 ? "#16a34a" : "#dc2626";
      return `同向<span style="color:${accColor}">${cd.accuracy}%</span>(${cd.correct_count}对${cd.wrong_count}错)`;
    };
    html += `<div class="term-plain futures-stat-sub" style="margin:6px 0;font-size:13px;">中信 <strong style="color:var(--text-1)">${fmtStat(citicCd)}</strong> · 机构 <strong style="color:var(--text-1)">${fmtStat(instCd)}</strong></div>`;
    // 合并表7列，用 .accuracy-table-scroll 滚动容器
    html += '<div class="accuracy-table-scroll"><table class="accuracy-table"><thead><tr><th>日期</th><th>中信方向</th><th>中信同向%</th><th>中信次日涨跌</th><th>中信对错</th><th>机构方向</th><th>机构同向%</th><th>机构次日涨跌</th><th>机构对错</th></tr></thead><tbody>';
    // 按 date join 两份 details（并集，缺则该角色留空"-"）
    const citicMap = {};
    if (citicCd && citicCd.details) citicCd.details.forEach(d => { citicMap[d.date] = d; });
    const instMap = {};
    if (instCd && instCd.details) instCd.details.forEach(d => { instMap[d.date] = d; });
    // 倒序渲染（727当天置顶），当天行(任一 next_return==null)高亮淡黄+加粗
    const sortedDates = [...allDates].sort((a, b) => String(b).localeCompare(String(a)));
    const fmtDir = (item) => {
      if (!item) return { text: "-", color: "var(--text-3)" };
      const t = item.citic_dir === "多" ? "多" : item.citic_dir === "空" ? "空" : "-";
      const c = item.citic_dir === "多" ? "#e6492e" : item.citic_dir === "空" ? "#2e8b57" : "var(--text-3)";
      return { text: t, color: c };
    };
    const fmtRet = (item) => {
      if (!item) return { str: "-", color: "var(--text-3)" };
      const ret = item.next_return;
      if (ret == null) return { str: "待收盘", color: "var(--text-3)" };
      return { str: (ret >= 0 ? "涨" : "跌") + Math.abs(ret).toFixed(2) + "%", color: ret >= 0 ? "#e6492e" : "#2e8b57" };
    };
    const fmtJudge = (item) => {
      if (!item) return { text: "-", color: "var(--text-3)" };
      const j = item.correct === true ? "✓" : item.correct === false ? "✗" : "待";
      const c = item.correct === true ? "#e6492e" : item.correct === false ? "#2e8b57" : "var(--text-3)";
      return { text: j, color: c };
    };
    for (const date of sortedDates) {
      const citicItem = citicMap[date];
      const instItem = instMap[date];
      const isToday = (citicItem && citicItem.next_return == null) || (instItem && instItem.next_return == null);
      const rowStyle = isToday ? ' style="background-color:rgba(255,235,59,0.22);font-weight:bold"' : '';
      const cD = fmtDir(citicItem), cR = fmtRet(citicItem), cJ = fmtJudge(citicItem);
      const iD = fmtDir(instItem), iR = fmtRet(instItem), iJ = fmtJudge(instItem);
      // follow_ratio 列：按 date join accTrend，中信+机构各1列（极端值预警着色）
      const _cFr = _accFrMap["中信期货"] ? _accFrMap["中信期货"][date] : null;
      const _iFr = _accFrMap["机构前20"] ? _accFrMap["机构前20"][date] : null;
      const _cFrCell = _fmtFrCell(_cFr);
      const _iFrCell = _fmtFrCell(_iFr);
      const _cFrTd = `<td class="${_cFrCell.cls}" title="${_cFrCell.title}">${_cFrCell.text}</td>`;
      const _iFrTd = `<td class="${_iFrCell.cls}" title="${_iFrCell.title}">${_iFrCell.text}</td>`;
      html += `<tr${rowStyle}><td class="sym-name">${fmtDate(date)}</td><td style="color:${cD.color};font-weight:bold">${cD.text}</td>${_cFrTd}<td style="color:${cR.color}">${cR.str}</td><td style="color:${cJ.color};font-weight:bold">${cJ.text}</td><td style="color:${iD.color};font-weight:bold">${iD.text}</td>${_iFrTd}<td style="color:${iR.color}">${iR.str}</td><td style="color:${iJ.color};font-weight:bold">${iJ.text}</td></tr>`;
    }
    html += '</tbody></table></div>';
    html += '<div class="term-plain">多+涨/空+跌=同向(✓)；多+跌/空+涨=逆向(✗)。按各自主导方向统计历史准确率，不构成未来预测。</div>';
    div.innerHTML = html;
    (host || fgGrid).appendChild(div);
    addCardTimeBadge(div, latestDetailDate, snap, "t1", "futures_date");
  };
  // 需求3: 净加多空表（日期|上证50净加|沪深300净加|中证500净加|中证1000净加|合计净加|方向），过去15天，去掉次日涨跌+对错
  const _renderRoleNetChgCard = (cd, titlePrefix, noteText, host, sharedDates) => {
    if (!cd) return;
    const div = document.createElement("div");
    div.className = "chart-card futures-table-card";
    const latestDetailDate = sharedDates && sharedDates.length ? sharedDates[sharedDates.length - 1] : (cd.details && cd.details.length ? cd.details[cd.details.length - 1].date : "");
    const detailSuffix = latestDetailDate ? `<span class="chart-latest"> · ${fmtDate(latestDetailDate)}</span>` : "";
    let html = `<h3>${titlePrefix}净加多空（过去15天）${detailSuffix}</h3>`;
    html += `<div class="futures-note">${noteText}</div>`;
    // 统计副标题（与准确率合并表结构对齐，保证3表表格起始位置一致）— X%按准确率着色(>55%绿/#16a34a, <=55%红/#dc2626)
    const accColor = cd.accuracy > 55 ? "#16a34a" : "#dc2626";
    html += `<div class="term-plain futures-stat-sub" style="margin:6px 0;font-size:13px;"><strong style="color:var(--text-1)">同向<span style="color:${accColor}">${cd.accuracy}%</span>(${cd.correct_count}对${cd.wrong_count}错)</strong></div>`;
    html += '<div class="accuracy-table-scroll"><table class="accuracy-table"><thead><tr><th>日期</th><th>上证50净加</th><th>沪深300净加</th><th>中证500净加</th><th>中证1000净加</th><th>合计净加</th><th>方向</th><th>15日同向%</th></tr></thead><tbody>';
    // 净加手数：正红负绿（正=净加多=红，负=净加空=绿，A股红涨绿跌惯例）
    const chgColor = (v) => v != null ? (v >= 0 ? "#e6492e" : "#2e8b57") : "var(--text-3)";
    const chgStr = (v) => v != null ? (v >= 0 ? "+" : "") + Math.round(v) : "-";
    // 倒序渲染（最新727当天在上，最旧在下），当日行（next_return=null）高亮淡黄+加粗
    // 3表对齐：优先用传入 sharedDates，缺则用 cd 自身 dates；缺失日期渲染空行保持行对齐
    const detailMap = {};
    if (cd.details) cd.details.forEach(d => { detailMap[d.date] = d; });
    const sortedDates = sharedDates && sharedDates.length
      ? [...sharedDates].sort((a, b) => String(b).localeCompare(String(a)))
      : [...cd.details].sort((a, b) => String(b.date).localeCompare(String(a.date))).map(d => d.date);
    for (const date of sortedDates) {
      const item = detailMap[date];
      // follow_ratio 列：按 date join accTrend，titlePrefix 映射到 role key（中信->中信期货/机构->机构前20）
      const _roleKey = _prefixToRoleKey[titlePrefix];
      const _fr = (_roleKey && _accFrMap[_roleKey]) ? _accFrMap[_roleKey][date] : null;
      const _frCell = _fmtFrCell(_fr);
      const _frTd = `<td class="${_frCell.cls}" title="${_frCell.title}">${_frCell.text}</td>`;
      if (!item) {
        // 该日期在本角色缺失，渲染空行保持3表行对齐
        html += `<tr><td class="sym-name">${fmtDate(date)}</td><td style="text-align:right;color:var(--text-3)">-</td><td style="text-align:right;color:var(--text-3)">-</td><td style="text-align:right;color:var(--text-3)">-</td><td style="text-align:right;color:var(--text-3)">-</td><td style="text-align:right;color:var(--text-3)">-</td><td style="color:var(--text-3)">-</td>${_frTd}</tr>`;
        continue;
      }
      const isToday = item.next_return == null;
      const rowStyle = isToday ? ' style="background-color:rgba(255,235,59,0.22);font-weight:bold"' : '';
      const ihC = chgColor(item.ih_chg), ifC = chgColor(item.if_chg), icC = chgColor(item.ic_chg), imC = chgColor(item.im_chg), totC = chgColor(item.total_chg);
      const dirText = item.citic_dir === "多" ? "多" : item.citic_dir === "空" ? "空" : "-";
      const dirColor = item.citic_dir === "多" ? "#e6492e" : item.citic_dir === "空" ? "#2e8b57" : "var(--text-3)";
      html += `<tr${rowStyle}><td class="sym-name">${fmtDate(item.date)}</td><td style="color:${ihC};text-align:right">${chgStr(item.ih_chg)}</td><td style="color:${ifC};text-align:right">${chgStr(item.if_chg)}</td><td style="color:${icC};text-align:right">${chgStr(item.ic_chg)}</td><td style="color:${imC};text-align:right">${chgStr(item.im_chg)}</td><td style="color:${totC};text-align:right;font-weight:bold">${chgStr(item.total_chg)}</td><td style="color:${dirColor};font-weight:bold">${dirText}</td>${_frTd}</tr>`;
    }
    html += '</tbody></table></div>';
    html += '<div class="term-plain">净加=多头增减-空头增减(手)。合计=上证50+沪深300+中证500+中证1000。多(红)/空(绿)按当日合计净加方向。次日涨跌待收盘后回填统计准确率。</div>';
    div.innerHTML = html;
    (host || fgGrid).appendChild(div);
    addCardTimeBadge(div, latestDetailDate, snap, "t1", "futures_date");
  };
  // 需求3布局: 2行2列 grid（表③准确率合并表 + 规律结论卡 + 中信净加表 + 机构净加表），共享 sharedDates 保证行对齐
  // grid auto-flow 行优先：appendChild 顺序 = 第1行左(表③) -> 第1行右(规律结论卡) -> 第2行左(中信净加) -> 第2行右(机构净加)
  const _citicCd = data.citic_ih_detail;
  const _instCd = data.inst_ih_detail;
  const _citicDates = (_citicCd && _citicCd.details) ? _citicCd.details.map(d => d.date).filter(Boolean) : [];
  const _instDates = (_instCd && _instCd.details) ? _instCd.details.map(d => d.date).filter(Boolean) : [];
  const sharedDates = [...new Set([..._citicDates, ..._instDates])].sort();
  // 2x2 grid 容器（align-items:start 避免规律结论卡撑高表③留白）
  const wrapper2x2 = document.createElement("div");
  wrapper2x2.className = "futures-2x2-grid";
  fgGrid.appendChild(wrapper2x2);
  // 第1行左：表③ 中信/机构多空单同向准确率合并表
  _renderMergedAccuracyCard(_citicCd, _instCd, wrapper2x2, sharedDates);
  // 第1行右：_mergedCard 整块（规律结论+趋势图，下文 appendChild 到 wrapper2x2）
  // 第2行左/右：中信/机构净加多空表（下文 _mergedCard 块后调用，保证 grid 顺序）


  // === 合并卡：规律结论 + 同向准确度趋势（近125日）二区块合一 ===
  // 原本分散在 3 个独立 chart-card（结论卡/徽章卡/趋势图卡），2026-07-20 起删除徽章表区，现合并为同一外层 card 内 2 个子区块
  // 子区块顺序：结论区 -> 趋势图区，子区块间用 border-top 分隔
  const _hasAccTrend = accTrend && accTrend.latest && accTrend.latest.roles;
  const _hasConc = accConclusion && accConclusion.conclusions && accConclusion.conclusions.length;
  if (_hasAccTrend || _hasConc) {
    const _mergedCard = document.createElement("div");
    _mergedCard.className = "chart-card futures-acc-merged-card";
    wrapper2x2.appendChild(_mergedCard);

    // --- 子区块1: 同向准确度趋势图区（上） ---
    // 修复1: 趋势图置上、规律结论置下（原 conc 在上 chart 在下，2026-08-03 对调）
    // 修复4: 按 state.range 切片（3月=90/6月=180/1年=365/3年=1095/5年=1825/全部=全量），原硬编码 slice(-125) 致 3月/6月 切换无效
    if (_hasAccTrend) {
      const _frDate = accTrend.latest.date || "";

      if (accTrend.dates && accTrend.dates.length && accTrend.series) {
        const _chartSub = document.createElement("div");
        _chartSub.className = "futures-acc-sub futures-acc-sub-chart";
        _mergedCard.appendChild(_chartSub);
        const _frDates = accTrend.dates;
        const _frSeriesConfig = [["中信期货", "中信"], ["机构前20", "机构"], ["国泰君安", "国君"]];
        // 修复4: 按 state.range 决定显示天数（与持仓走势图一致），all/未知回退全量
        const _accRangeDays = { "3m": 90, "6m": 180, "1y": 365, "3y": 1095, "5y": 1825 };
        const _accDays = _accRangeDays[state.range] || _frDates.length;
        // 连续3日<50%标记
        const _warnMarks = [];
        for (const [roleKey, roleLabel] of _frSeriesConfig) {
          const pts = accTrend.series[roleKey] || [];
          let streak = 0;
          for (const p of pts) {
            if (p.follow_ratio != null && p.follow_ratio < 50) {
              streak++;
              if (streak >= 3) _warnMarks.push({ date: p.date, role: roleLabel });
            } else {
              streak = 0;
            }
          }
        }
        const _hasWarn = _warnMarks.length > 0;
        const _frChartTitle = "同向准确度趋势（近" + Math.min(_frDates.length, _accDays) + "日）" +
          termTip("同向准确度=同向天数/15日总天数。跌破50%(红区)=同向失效，机构风格转逆向。连续3日<50%标记⚠。50%虚线=随机基准，55%虚线=同向有效线。") +
          (_hasWarn ? ' <span style="color:#e6492e;font-size:13px">⚠ 存在连续3日<50%</span>' : "");
        // 修复4: 按 state.range 切片显示（原 slice(-125) 硬编码致切换无效）
        const _showDates = _frDates.slice(-_accDays);
        // 手动创建 chart 容器（避免 mkCard 产生嵌套 chart-card）
        const _chartTitleEl = document.createElement("h3");
        _chartTitleEl.innerHTML = _frChartTitle;
        _chartSub.appendChild(_chartTitleEl);
        const _chartDiv = document.createElement("div");
        _chartDiv.className = "chart";
        _chartDiv.style.height = "180px";
        _chartSub.appendChild(_chartDiv);
        const _frChart = echarts.init(_chartDiv);
        charts.push(_frChart);
        const _frChartSeries = _frSeriesConfig.map(([roleKey, roleLabel]) => {
          const pts = accTrend.series[roleKey] || [];
          const ptMap = {};
          pts.forEach(p => { ptMap[p.date] = p.follow_ratio; });
          return {
            name: roleLabel,
            type: "line",
            smooth: true,
            symbol: "none",
            connectNulls: true,
            data: _showDates.map(d => ptMap[d] != null ? ptMap[d] : null),
          };
        });
        // <50% 标红 markArea：找每条线<50%的日期区间（合并为整体区间，按角色分别标）
        const _markAreas = [];
        for (const [roleKey, roleLabel] of _frSeriesConfig) {
          const pts = accTrend.series[roleKey] || [];
          const ptMap = {};
          pts.forEach(p => { ptMap[p.date] = p.follow_ratio; });
          let inZone = false;
          let zoneStart = null;
          for (const d of _showDates) {
            const v = ptMap[d];
            if (v != null && v < 50) {
              if (!inZone) { zoneStart = d; inZone = true; }
            } else {
              if (inZone && zoneStart) { _markAreas.push([{ xAxis: zoneStart }, { xAxis: d }]); inZone = false; }
            }
          }
          if (inZone && zoneStart) _markAreas.push([{ xAxis: zoneStart }, { xAxis: _showDates[_showDates.length - 1] }]);
        }
        _frChart.setOption(withTheme({
          tooltip: {
            trigger: "axis",
            formatter: function (params) {
              if (!params || !params.length) return "";
              let html = '<strong>' + params[0].axisValue + '</strong><br/>';
              params.forEach(p => {
                const v = p.data;
                const frStr = v != null ? v.toFixed(1) + "%" : "-";
                const cls = v != null && v < 50 ? 'color:#e6492e' : v != null && v < 55 ? 'color:#f59e0b' : 'color:#16a34a';
                html += p.marker + ' ' + p.seriesName + ': <span style="' + cls + ';font-weight:bold">' + frStr + '</span><br/>';
              });
              return html;
            },
          },
          legend: { top: 0, type: "scroll" },
          grid: { left: 50, right: 20, top: 35, bottom: 35 },
          xAxis: { type: "category", data: _showDates },
          yAxis: {
            type: "value", min: 0, max: 100,
            axisLabel: { color: cssVar("--text-1"), formatter: "{value}%" },
            nameTextStyle: { color: cssVar("--text-1") },
          },
          dataZoom: dzOpts(),
          series: _frChartSeries.map((s, idx) => ({
            ...s,
            markLine: idx === 0 ? {
              silent: true, symbol: "none",
              data: [
                { yAxis: 50, lineStyle: { color: "#999", type: "dashed", width: 1 }, label: { formatter: "50%随机", fontSize: 10, color: "#999" } },
                { yAxis: 55, lineStyle: { color: "#e6492e", type: "dashed", width: 1 }, label: { formatter: "55%有效", fontSize: 10, color: "#e6492e" } },
              ],
            } : undefined,
            markArea: idx === 0 && _markAreas.length ? {
              silent: true,
              itemStyle: { color: "rgba(230,73,46,0.08)" },
              data: _markAreas,
            } : undefined,
          })),
        }));
        addCardTimeBadge(_chartSub, _frDate, snap, "t1", "futures_date");
      }
    }

    // --- 子区块2: 规律结论区（下） ---
    // 修复1: 规律结论置下（原在上，2026-08-03 对调）
    // 修复2: "已触发" badge 加强高亮（红底白字 pill + 阴影，原仅小红字）
    // 修复3: 英文名词中文化（futures_ih_detail_acc -> 期货同向准确度明细表）
    if (_hasConc) {
      const _concSub = document.createElement("div");
      _concSub.className = "futures-acc-sub futures-acc-sub-conc";
      _mergedCard.appendChild(_concSub);
      const _concDate = accConclusion.as_of_date || "";
      const _concDateSuffix = _concDate ? `<span class="chart-latest"> · ${fmtDate(_concDate)}</span>` : "";
      let _concHtml = `<h3>期货同向准确度规律结论${_concDateSuffix}</h3>`;
      _concHtml += `<div class="futures-note">基于历史${accConclusion.streak_history ? Object.keys(accConclusion.streak_history).length : 0}角色时序总结的4条规律，每日自动刷新。当前触发的结论高亮置顶。同向准确度=15日同向天数占比，极端值触发抄底/顶部预警。</div>`;
      // 当前状态摘要：3角色 同向准确度 + 连续段天数（给结论提供上下文）
      if (accConclusion.current_state) {
        const _csRoles = [["中信期货", "中信"], ["机构前20", "机构"], ["国泰君安", "国君"]];
        _concHtml += '<div style="display:flex;gap:8px;flex-wrap:wrap;margin:4px 0 6px">';
        for (const [roleKey, roleLabel] of _csRoles) {
          const cs = accConclusion.current_state[roleKey];
          if (!cs) continue;
          const _fr = cs.follow_ratio;
          const _frColor = _fr != null ? (_fr <= 30 ? "#16a34a" : _fr >= 80 ? "#dc2626" : "var(--text-1)") : "var(--text-3)";
          const _dirText = cs.dominant_dir === "同向" ? "同向" : cs.dominant_dir === "逆向" ? "逆向" : "-";
          const _dirColor = cs.dominant_dir === "同向" ? "#e6492e" : cs.dominant_dir === "逆向" ? "#2e8b57" : "var(--text-3)";
          _concHtml += `<div style="flex:1;min-width:100px;text-align:center;padding:4px 6px;border:1px solid var(--border);border-radius:4px;background:var(--bg-2);font-size:11px">`;
          _concHtml += `<div style="color:var(--text-3)">${roleLabel} · <span style="color:${_dirColor};font-weight:600">${_dirText}${cs.streak_days}日</span></div>`;
          _concHtml += `<div style="font-size:16px;font-weight:bold;color:${_frColor}">${_fr != null ? _fr.toFixed(1) + "%" : "-"}</div>`;
          _concHtml += `</div>`;
        }
        _concHtml += '</div>';
      }
      // 4条结论卡片：触发置顶 + 按级别排序
      const _levelOrder = { "最强": 0, "次强": 1, "中等": 2, "辅助": 3 };
      const _sortedConcs = [...accConclusion.conclusions].sort((a, b) => {
        if (a.triggered !== b.triggered) return a.triggered ? -1 : 1;
        return (_levelOrder[a.level] ?? 9) - (_levelOrder[b.level] ?? 9);
      });
      _concHtml += '<div class="futures-conclusion-grid">';
      for (const c of _sortedConcs) {
        const _levelColor = c.level === "最强" ? "#dc2626" : c.level === "次强" ? "#e67e22" : c.level === "中等" ? "#2563eb" : "#6b7280";
        const _triggeredCls = c.triggered ? " futures-conclusion-triggered" : "";
        _concHtml += `<div class="futures-conclusion-item${_triggeredCls}" style="border-left:3px solid ${_levelColor}">`;
        _concHtml += `<div style="display:flex;align-items:center;gap:6px;margin-bottom:4px;flex-wrap:wrap">`;
        _concHtml += `<span style="background:${_levelColor};color:#fff;font-size:11px;padding:1px 6px;border-radius:3px;font-weight:600">${c.level}</span>`;
        _concHtml += `<strong style="color:var(--text-1)">${c.signal}</strong>`;
        // 修复2: "已触发" badge 加强 - 红底白字 pill + 白点 + 阴影，一眼可见（原仅 color:#dc2626 小红字）
        if (c.triggered) _concHtml += `<span style="background:#dc2626;color:#fff;font-size:11px;font-weight:700;padding:2px 8px;border-radius:10px;box-shadow:0 1px 4px rgba(220,38,38,0.5);letter-spacing:0.5px;display:inline-flex;align-items:center;gap:3px"><span style="display:inline-block;width:5px;height:5px;border-radius:50%;background:#fff"></span>已触发</span>`;
        _concHtml += `</div>`;
        _concHtml += `<div style="font-size:12px;color:var(--text-2);margin:2px 0">触发: ${c.trigger}</div>`;
        _concHtml += `<div style="font-size:12px;color:var(--text-1);margin:2px 0">当前: ${c.current_status}</div>`;
        _concHtml += `<div style="font-size:11px;color:var(--text-3);margin:2px 0">统计: ${c.stats}</div>`;
        _concHtml += `<div style="font-size:12px;font-weight:600;color:${_levelColor};margin-top:4px">建议: ${c.action}</div>`;
        _concHtml += `</div>`;
      }
      _concHtml += '</div>';
      // 修复3: futures_ih_detail_acc -> 期货同向准确度明细表（英文名词中文化）
      _concHtml += '<div class="term-plain">规律基于期货同向准确度明细表历史统计，仅作参考不构成投资建议。同向准确度<=30%为抄底信号(淡绿)，>=80%为顶部预警(淡红)。</div>';
      _concSub.innerHTML = _concHtml;
      addCardTimeBadge(_concSub, _concDate, snap, "t1", "futures_date");
    }
  }

  // 第2行左/右：中信/机构净加多空表（过去15天），appendChild 到 wrapper2x2 保证 grid auto-flow 行优先落第2行
  _renderRoleNetChgCard(_citicCd, "中信", "最近15个交易日中信期货4品种(上证50/沪深300/中证500/中证1000)净加仓(多头增减-空头增减)手数及方向。首行为当天置顶高亮。", wrapper2x2, sharedDates);
  _renderRoleNetChgCard(_instCd, "机构", "最近15个交易日机构(前20会员)4品种(上证50/沪深300/中证500/中证1000)净加仓(多头增减-空头增减)手数及方向。首行为当天置顶高亮。", wrapper2x2, sharedDates);

  // 第456卡片(昨日净多空/历史准确率/当日净加对照)3列并排，和前3一样复用 futures-triple-grid 3列布局
  const tripleGrid2 = document.createElement("div");
  tripleGrid2.className = "futures-triple-grid";
  fgGrid.appendChild(tripleGrid2);

  // 1. 昨日净多空概览卡片（始终创建卡片结构，无数据显示空状态，保证 min-height 生效不塌陷、tripleGrid2 三列布局不缺格）
  {
    const div = document.createElement("div");
    div.className = "chart-card futures-table-card";
    if (data.summary && data.summary.roles) {
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
      html += '<div class="term-plain">净多空=多头持仓-空头持仓(手)，反映机构当前持仓偏向的静态水平：正数=净多(看多占优,红)，负数=净空(看空占优,绿)。区别于"净加"(净多空的日变化量,见当日净加对照)。数据来源：中金所前20会员持仓。</div>';
      html += '<div class="futures-reverse-note">⚠ 机构持仓极端值常为<strong>反向参考</strong>（机构极度看多时可能见顶、极度看空时可能见底），需结合历史准确率与市场位置判断，不可单看净持仓方向顺势操作。</div>';
      div.innerHTML = html;
      tripleGrid2.appendChild(div);
      addCardTimeBadge(div, dateStr, snap, "t1", "futures_date");
    } else {
      // 无数据空状态：保证卡片结构完整(h3+empty-note)，min-height 生效不塌陷
      div.innerHTML = '<h3>昨日净多空（万手）</h3><div class="empty-note">暂无数据</div>';
      tripleGrid2.appendChild(div);
    }
  }

  // 2. 历史准确率表格（移到综合图前面）
  if (data.accuracy) {
    const div = document.createElement("div");
    div.className = "chart-card futures-table-card";
    const windows = ["7d", "15d", "30d", "60d", "120d"];
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
    html += `<tr><td class="sym-name"><span class="term-tip" data-tip="机构最新持仓方向(多/空)及对应指数实际涨跌幅。多+涨/空+跌=赌对方向，反之赌错。实际涨跌幅(actual_return)待收盘次日更新">当期方向❓</span></td>`;
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
    tripleGrid2.appendChild(div);
    addCardTimeBadge(div, accDates.length ? accDates[accDates.length - 1] : "", snap, "t1", "futures_date");
  }

  // 2.5.0 当日净加对照表（中信 vs 机构 vs 国泰君安 4品种净加并排对照，最新交易日727置顶最显眼位置）
  const _renderDailyNetCompareCard = (citicD, instD, guotaiD) => {
    if (!citicD || !instD || !citicD.details || !citicD.details.length || !instD.details || !instD.details.length) return;
    const citicLatest = citicD.details[citicD.details.length - 1];
    const instLatest = instD.details[instD.details.length - 1];
    const guotaiLatest = (guotaiD && guotaiD.details && guotaiD.details.length) ? guotaiD.details[guotaiD.details.length - 1] : null;
    const latestDate = citicLatest.date || instLatest.date;
    const div = document.createElement("div");
    div.className = "chart-card futures-table-card";
    let html = `<h3>当日净加对照（${fmtDate(latestDate)}）</h3>`;
    html += `<div class="futures-note">中信期货 vs 机构前20 vs 国泰君安 在 ${fmtDate(latestDate)} 当日 上证50/沪深300/中证500/中证1000 4品种净加仓并排对照，一眼看三套数据方向。次日涨跌待收盘后回填统计准确率。</div>`;
    html += '<table class="accuracy-table"><thead><tr><th>角色</th><th>上证50净加</th><th>沪深300净加</th><th>中证500净加</th><th>中证1000净加</th><th>合计净加</th><th>方向</th></tr></thead><tbody>';
    const cmpChgColor = (v) => v != null ? (v >= 0 ? "#e6492e" : "#2e8b57") : "var(--text-3)"; // 正红负绿(当日净加对照,与chgColor一致,A股红涨绿跌)
    const cmpChgStr = (v) => v != null ? (v >= 0 ? "+" : "") + Math.round(v) : "-";
    const renderRow = (roleName, item) => {
      const ihC = cmpChgColor(item.ih_chg), ifC = cmpChgColor(item.if_chg), icC = cmpChgColor(item.ic_chg), imC = cmpChgColor(item.im_chg), totC = cmpChgColor(item.total_chg);
      const dirText = item.citic_dir === "多" ? "多" : item.citic_dir === "空" ? "空" : "-";
      const dirColor = item.citic_dir === "多" ? "#e6492e" : item.citic_dir === "空" ? "#2e8b57" : "var(--text-3)";
      html += `<tr><td class="sym-name" style="font-weight:bold">${roleName}</td><td style="color:${ihC};text-align:right">${cmpChgStr(item.ih_chg)}</td><td style="color:${ifC};text-align:right">${cmpChgStr(item.if_chg)}</td><td style="color:${icC};text-align:right">${cmpChgStr(item.ic_chg)}</td><td style="color:${imC};text-align:right">${cmpChgStr(item.im_chg)}</td><td style="color:${totC};text-align:right;font-weight:bold">${cmpChgStr(item.total_chg)}</td><td style="color:${dirColor};font-weight:bold">${dirText}</td></tr>`;
    };
    renderRow("中信期货", citicLatest);
    renderRow("机构前20", instLatest);
    if (guotaiLatest) renderRow("国泰君安", guotaiLatest);
    html += '</tbody></table>';
    html += '<div class="term-plain">净加=多头当日增减-空头当日增减(手)，即净多空的日变化量：正数=净加多(多头加仓>空头,净多增加)，负数=净加空(空头加仓>多头,净多减少)。与"昨日净多空"互补——净多空看持仓偏向(静态)，净加看加仓方向(动态)。合计=上证50+沪深300+中证500+中证1000。多(红)/空(绿)按当日4品种合计净加方向。三套数据方向一致=共振信号，不一致=分歧。</div>';
    div.innerHTML = html;
    tripleGrid2.appendChild(div);
    addCardTimeBadge(div, latestDate, snap, "t1", "futures_date");
  };
  _renderDailyNetCompareCard(data.citic_ih_detail, data.inst_ih_detail, data.guotai_ih_detail);

  // 3. 四张折线图：net_position 手数趋势
  // 修复4: 按 state.range 切片 positions（3月=90/6月=180/1年=365/3年=1095/5年=1825/全部=全量）
  // 原用全量 data.positions 致 3月/6月 切换按钮无效果（图表重画但数据时间范围不变）
  const _posRangeDays = { "3m": 90, "6m": 180, "1y": 365, "3y": 1095, "5y": 1825 };
  const _posDays = _posRangeDays[state.range];
  const _slicedPositions = (_posDays && data.positions.length > _posDays) ? data.positions.slice(-_posDays) : data.positions;

// 图1：综合净多空手数 — 3 条线（机构/中信/国君的综合品种）
  const chart1Series = roles.map((role) => ({
    name: role,
    data: _slicedPositions.map((d) => {
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
                for (const w of ["7d", "15d", "30d", "60d", "120d"]) {
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
      data: _slicedPositions.map((d) => {
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
    div.innerHTML = '<h3>说明</h3><div class="term-plain">机构=中金所前20会员汇总。中信/国君为单独席位。折线图为净多空手数（正=净多，负=净空），悬停可查看比例。历史准确率基于次工作日涨跌方向统计，不构成未来预测。</div>';
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
  const labels = { buy: _t("buy_long"), buy_aux: _t("buy_aux"), buy_special: _t("buy_special"), buy_special_filtered: _t("buy_special_filtered_long"), buy_backup: _t("buy_backup"), sell: _t("sell_long"), sell_stop_loss: _t("sell_stop_loss") , band_hold: _t("band_hold") };
  const cls = { buy: "buy", buy_aux: "buy-aux", buy_special: "buy-special", buy_special_filtered: "buy-special-filtered", buy_backup: "buy-backup", sell: "sell", sell_stop_loss: "sell-stop-loss" , band_hold: "band-hold" };
  let parts = [];
  for (const sig of ["buy", "buy_aux", "buy_special", "buy_special_filtered", "buy_backup", "band_hold", "sell", "sell_stop_loss"]) {
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
    // C：移动端滚动时关闭所有 freq-popup（CSS position:absolute 不跟随滚动，capture 捕获所有滚动容器）
    window.addEventListener("scroll", () => {
      document.querySelectorAll(".freq-popup").forEach((p) => { if (p.style.display === "block") p.style.display = "none"; });
    }, { passive: true, capture: true });
  }
}

// P2-新-G ETF 联动推荐：指数信号卡 h3 末尾追加 ETF tag（复用行业卡片的 _renderEtfTag/_bindEtfPopup）。
// 最新信号为 buy 类（buy/buy_aux/buy_special/buy_special_filtered/buy_backup）时加 .etf-tag-buy-signal 高亮。
// 仿 _appendStrategyHint 通过 cardEl.querySelector("h3") 注入子元素（不碰 markPoint/chip 区域）。
// etfs 为空（sh/sz 综合指数无跟踪ETF）不渲染 tag，避免硬塞"代理"ETF 误导用户。
// 注：ETF 滞后指数，tag 仅作"信号参考"展示（ETF 已反映部分预期），非交易指令。
function _appendEtfLinkTag(cardEl, indexId, etfs, signals) {
  if (!cardEl) return;
  var h3 = cardEl.querySelector("h3");
  // 2026-07-20 板分化适配：行业网格卡无 h3，走 spark-name 路径（仿 _appendStrategyHint L1689）
  var sparkName = !h3 ? cardEl.querySelector(".spark-name") : null;
  var target = h3 || sparkName;
  if (!target) return;
  if (target.querySelector(".etf-tag")) return;  // 避免重复注入
  // 2026-07-20 灰色兜底：无 ETF 时生成灰色占位符（用户要求：不能空白，否则用户以为坏了）
  // data-no-pop 排除 _initTermPop 捕获 title（L1475），保留原生 hover tooltip "该标的暂无相关ETF"
  if (!etfs || !etfs.length) {
    target.insertAdjacentHTML("beforeend", '<span class="etf-tag etf-tag-empty" data-no-pop="" title="该标的暂无相关ETF">无ETF</span>');
    return;
  }
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
  var latestDate = latest ? latest.date : "";  // task2：popup 标题行显"最近一条信号(日期)"，避免"当前"误导
  // 注入 tag HTML（top1 代码 + "+N" 候选）
  target.insertAdjacentHTML("beforeend", _renderEtfTag(etfs));
  var tag = target.querySelector(".etf-tag");
  if (!tag) return;
  if (isBuy) tag.classList.add("etf-tag-buy-signal");
  // 2026-07-28 近似标注：首位 ETF approx=true 时加"⚠近似"标注（如 sh 用上证50近似上证指数，非精准跟踪）
  // 首位 = etfs[0]（board_etf_map 候选，与回测chip首位一致；approx 优先 false 排序由后端 _pick_first_etf 保证）
  var top0 = etfs[0];
  if (top0 && top0.approx) {
    tag.classList.add("etf-tag-approx");
    tag.insertAdjacentHTML("beforeend", '<span class="etf-approx-mark">⚠近似</span>');
    // task1 C根治：删 title（原"近似替代...颜色判定"措辞），避免 _initTermPop 捕获 [title] 弹 .term-pop 盖住 .etf-popup
    // 近似说明已在 tag 内显"⚠近似"标记，红黄判定+日期移到 .etf-popup 标题行（_bindEtfPopup）
  }
  // 绑定 popup：top1 点击复制 + 悬浮弹全部候选（按成交额降序，每行可复制）
  // task2：传 isBuy + latestDate，popup 标题行显示红黄判定 + 最近信号日期
  _bindEtfPopup(target, etfs, isBuy, latestDate);
}

// 行业/概念卡片：ETF 多候选展示（对齐用户诉求 -- 不替用户硬选1个）。
// top1 代码标签（可点复制）+ "+N" 提示更多；悬浮弹出全部候选（按成交额降序，每行可点复制）。
// 匹配不到（etfs 为空）则不渲染，避免硬塞"代理"ETF 误导用户。
function _renderEtfTag(etfs) {
  if (!etfs || !etfs.length) return "";
  const top = etfs[0];
  const more = etfs.length > 1 ? `<span class="etf-more">+${etfs.length - 1}</span>` : "";
  // task1 C根治：无 title -- 避免 _initTermPop 全局 mouseover 捕获 [title] 弹 .term-pop(z:9999 fixed) 盖住 .etf-popup(z:100 absolute)
  // task1 D止血：data-no-pop 双保险，即使后续误加 title 也被 _initTermPop L1475 显式排除
  // task2：红黄判定措辞移到 .etf-popup 标题行（_bindEtfPopup 传 isBuy+latestDate），tag 本身只显代码+"+N"
  return `<span class="etf-tag" data-no-pop="">${top.code}${more}</span>`;
}

function _copyEtfCode(el, code) {
  const txt = navigator.clipboard ? navigator.clipboard.writeText(code) : Promise.resolve();
  txt.then(() => {
    // task1 C根治：不依赖 title 做"已复制"反馈（title 已删，避免 _initTermPop 捕获）
    // 改用 .copied class（CSS L1020/1033 已有绿底视觉反馈）+ data-copied 属性（a11y/selector 备用）
    el.classList.add("copied");
    el.setAttribute("data-copied", code);
    setTimeout(() => { el.classList.remove("copied"); el.removeAttribute("data-copied"); }, 900);
  });
}

function _bindEtfPopup(cell, etfs, isBuy, latestDate) {
  if (!etfs || !etfs.length) return;
  const tag = cell.querySelector(".etf-tag");
  if (!tag) return;
  const popup = document.createElement("div");
  popup.className = "etf-popup";
  // task2：标题行下加红黄判定 + 最近信号日期，措辞明确"最近一条信号"非"当前"
  // 原 tag title 措辞"当前有买点信号"误导（实际=最新一条不限时间）；buy 类含 buy/buy_aux/buy_special/buy_special_filtered/buy_backup
  var sigLine = "";
  if (latestDate) {
    sigLine = isBuy
      ? `<div class="etf-pop-sig etf-pop-sig-buy">🔴 最近买类信号(${latestDate})</div>`
      : `<div class="etf-pop-sig etf-pop-sig-no">` + _t("etf_no_buy") + `(${latestDate})</div>`;
  }
  popup.innerHTML = `<div class="etf-pop-title">相关ETF · 按成交额排序 · 点击复制</div>` + sigLine +
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
    // C：移动端滚动时关闭所有 etf-popup（CSS position:absolute 不跟随滚动，capture 捕获所有滚动容器）
    window.addEventListener("scroll", () => {
      document.querySelectorAll(".etf-popup").forEach((p) => { if (p.style.display === "block") p.style.display = "none"; });
    }, { passive: true, capture: true });
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
    cell.id = "industry-cell-" + id; // 指数目录锚点跳转目标(港股板块 chip / 行业 chip 跳转用)
    const sign = up ? "+" : "";
    const hint = statsHint(idx.stats, idx.strategy, id);
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
        <span class="spark-name">${_INDEX_NAME_MAP[id] || idx.name}${closeSuffix}${pctSuffix}${rotTag}</span>
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
    // task3：改用 _appendEtfLinkTag（与指数表现一致：ETF tag 在 sim-btn 后 + 红黄判定），signals 在 L8950 已定义
    _appendEtfLinkTag(cell, id, idx.etfs, signals);
    // 2026-07-20 板分化三按钮补齐：📌 钉住 + 🔔 订阅（与指数表现 L2967-2969 一致顺序：[etf-tag][📌][🔔]）
    // sig 构造 {signals, stats} 对齐指数表现 sig = signalsCache[id] 结构
    _appendPinBtn(cell, id, idx, { signals: signals, stats: idx.stats });
    _appendSubscribeBtn(cell, id, (_INDEX_NAME_MAP[id] || idx.name));
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
    _attachMarketScoreCard(id, (_INDEX_NAME_MAP[id] || idx.name), cell);
    // 行业绿色(最新)档专属 tip（补充申万/baostock 源说明）；滞后/异常档保留通用 tip
    const _indBdg = cell.querySelector(".card-time-badge.intraday");
    if (_indBdg) _indBdg.setAttribute("data-tip", "行业指数T+1(申万/baostock收盘后次日补全,逢周末顺延到下一交易日),已更新到最新交易日");
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
        <span class="ind-metric-val" title="行业内成分股涨跌家数">涨${lastW.up_count == null ? "-" : lastW.up_count} 跌${lastW.down_count == null ? "-" : lastW.down_count}</span>`;
      metricsBox.appendChild(row);
      const wc = echarts.init(row.querySelector(".ind-metric-chart"));
      wc.setOption(withTheme({
        grid: { left: 1, right: 1, top: 1, bottom: 1 },
        legend: { show: false },
        xAxis: { type: "category", show: false, data: widthData.map((d) => d.date) },
        yAxis: { type: "value", show: false },
        tooltip: { trigger: "axis", formatter: (p) => {
          const d = widthData[p[0].dataIndex];
          if (!d) return `${p[0].axisValue}<br/>-`;
          const wd = _indWidthExtra(id, idx, p[0].dataIndex);
          return `${p[0].axisValue}<br/>涨${d.up_count}家(成分股上涨) 跌${d.down_count}家(成分股下跌) | 涨停${wd.zt_count != null ? wd.zt_count : "-"} 跌停${wd.dt_count != null ? wd.dt_count : "-"} 炸板${wd.zb_count != null ? wd.zb_count : "-"}<br/>封板率${wd.seal_rate != null ? (wd.seal_rate * 100).toFixed(0) + "%" : "-"} | 成交额${wd.amount != null ? wd.amount.toFixed(0) + "亿" : "-"}`;
        } },
        series: [
          { name: "上涨", type: "line", stack: "wd", symbol: "none", smooth: true, color: "#e6492e",
            data: widthData.map((d) => [d.date, d.up_count || 0]),
            lineStyle: { color: "#e6492e", width: 0.8 }, areaStyle: { color: "#e6492e", opacity: 0.35 } },
          { name: "下跌", type: "line", stack: "wd", symbol: "none", smooth: true, color: "#2e8b57",
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
    .map(([id, idx]) => ({ id, name: (_INDEX_NAME_MAP[id] || idx.name), freq: _calcRotationFreq(idx.fund_flow) }))
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
// 指数目录锚点(A股/港股/全球) scroll spy 列表: 切 tab 时统一 disconnect, 避免泄漏
// 每项是一个 IntersectionObserver 实例, buildIndexAnchorBar 内 push, clearCharts 内统一 disconnect
let _indexNavSpies = [];
// 点击 chip 跳转后抑制 scroll spy 抢 .active 的截止时刻(毫秒时间戳)。
// 根因: PC 2列 grid, click scrollIntoView(block:'start') 把同行两张卡同时推进可见带,
// observer 回调 forEach 对每个 intersecting entry 都执行"全部 chip toggle .active=(匹配当前 entry)",
// entries 顺序非确定 -> last entry 覆盖 click 设的 .active, 致 chip 高亮错乱(点科创50高亮创业板指)。
// 修法: click 后 800ms(smooth 动画完成)内 observer 回调直接 return, 保留 click 设的 .active; 冷却期后恢复滚动联动。
let _indexNavClickSuppressUntil = 0;

// 指数目录锚点跳转高亮计时器+当前高亮卡(模块级, 跨多次 chip 点击共享)
// 连点 n 个 chip 时, 前 n-1 个 setTimeout 被第 n 个 clearTimeout 覆盖, 旧卡 class 没被移除 -> 残留高亮
// 修复: 单高亮切换, 新点击立即清旧卡 class + 清旧 timer, 切换高亮到新卡(任意时刻只 1 个卡高亮)
let _indexNavFlashTimer = null;
let _indexNavFlashCard = null;
// 给目标卡片加 .index-nav-highlight 闪烁 2s 提示用户跳到哪了(2026-08-01)
// 多次点击同一/不同 chip: 先 remove 旧卡 class + 清旧 timer, 再 add 新卡 class 重启动画
function _flashIndexNavCard(el) {
  // 清前一个高亮(连点相邻 chip 时, 旧卡的 setTimeout 会被覆盖致 class 残留, 这里主动清)
  if (_indexNavFlashTimer) { clearTimeout(_indexNavFlashTimer); _indexNavFlashTimer = null; }
  if (_indexNavFlashCard) { _indexNavFlashCard.classList.remove("index-nav-highlight"); _indexNavFlashCard = null; }
  if (!el) return;
  el.classList.remove("index-nav-highlight");
  void el.offsetWidth;  // 强制 reflow, 重启 CSS animation
  el.classList.add("index-nav-highlight");
  _indexNavFlashCard = el;
  _indexNavFlashTimer = setTimeout(() => {
    el.classList.remove("index-nav-highlight");
    _indexNavFlashCard = null;
    _indexNavFlashTimer = null;
  }, 2000);
}

// 构建指数目录锚点条(吸顶 + chip 点击跳转 + scroll spy 高亮当前可见卡)
// groups: [{ label, items: [{key, name, targetId}] }]
//   targetId: 卡片 element 的 id 字符串(如 'idx-card-sh' / 'industry-cell-hk_cesg10')
//   caller 负责给卡片加对应 id, 并在卡片渲染完后调用 anchorBar._observeIndexCard(el) 注册 spy
// barLabel: 可选, 锚点条开头小标签(如"指数目录："), 不传则无
// 复用 .industry-anchor-bar CSS(sticky 吸顶 + 按钮样式), 加 .anchor-sep 分组分隔
function buildIndexAnchorBar(groups, barLabel) {
  const anchorBar = document.createElement("div");
  anchorBar.className = "industry-anchor-bar";
  const parts = [];
  if (barLabel) parts.push(`<span class="anchor-label">${barLabel}：</span>`);
  groups.forEach((g, gi) => {
    if (gi > 0) parts.push('<span class="anchor-sep" aria-hidden="true"></span>');
    parts.push('<div class="anchor-btn-group">');
    g.items.forEach(it => {
      parts.push(`<button type="button" data-idx-target="${it.targetId}" title="${it.name}">${it.name}</button>`);
    });
    parts.push('</div>');
  });
  anchorBar.innerHTML = parts.join("");
  // chip 点击: 平滑滚动到目标卡片
  anchorBar.querySelectorAll("button[data-idx-target]").forEach(btn => {
    btn.onclick = () => {
      const targetId = btn.dataset.idxTarget;
      const tryScroll = () => {
        const el = document.getElementById(targetId);
        if (el) {
          el.scrollIntoView({ behavior: "smooth", block: "start" });
          // 跳转后高亮目标卡片(闪烁 2s 边框+光晕), 让用户看到跳到哪了(2026-08-01)
          _flashIndexNavCard(el);
          return true;
        }
        return false;
      };
      // 卡片可能尚未渲染完(fetch 异步), 下一帧重试一次
      if (!tryScroll()) requestAnimationFrame(tryScroll);
      anchorBar.querySelectorAll("button[data-idx-target]").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      // 抑制 scroll spy 800ms(等 smooth 动画完成): 防止 PC 2列 grid 下同行另一卡
      // 同时进可见带致 observer last entry 覆盖 click 设的 .active(chip 高亮错乱)
      _indexNavClickSuppressUntil = Date.now() + 800;
    };
  });
  // scroll spy: 当前可见卡片对应 chip 高亮(rootMargin 让"距视口顶部 15%~30%"区段算可见)
  const spy = new IntersectionObserver((entries) => {
    // 点击 chip 后冷却期内直接 return, 保留 click 设的 .active 不被 scroll spy 覆盖
    if (Date.now() < _indexNavClickSuppressUntil) return;
    // 冷却期外: 选可见度最高(intersectionRatio 最大)的 intersecting entry,
    // 只对该 entry toggle .active; 避免 forEach 全部 entry 都 toggle 致 last entry 覆盖(spec 未规定 entries 顺序)
    let best = null;
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      if (!best || entry.intersectionRatio > best.intersectionRatio) best = entry;
    }
    if (best) {
      const tid = best.target.id;
      anchorBar.querySelectorAll("button[data-idx-target]").forEach(b => {
        b.classList.toggle("active", b.dataset.idxTarget === tid);
      });
    }
  }, { rootMargin: "-15% 0px -70% 0px", threshold: 0 });
  // 暴露 observe 方法给 caller, 卡片渲染完后调用
  anchorBar._observeIndexCard = (el) => { if (el) spy.observe(el); };
  _indexNavSpies.push(spy);
  return anchorBar;
}
// 切 tab 时统一 disconnect 所有指数目录锚点 scroll spy(renderTab->clearCharts 调用)
function disconnectAllIndexNavSpies() {
  _indexNavSpies.forEach(s => { try { s.disconnect(); } catch (e) {} });
  _indexNavSpies = [];
}

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

async function renderIndustry(container = content) {
  renderLoadingState(container, "加载行业数据…");
  // I1：命中缓存则不 refetch
  let r;
  if (_industryCache.range === state.range && _industryCache.r) {
    r = _industryCache.r;
  } else {
    r = await _loadIndustryData(state.range);
    _industryCache = { range: state.range, r };
  }
  container.innerHTML = "";
  renderPurposeNote(container, PURPOSE_NOTES["industry"]);
  const snap = state.intradaySnapshot;

  // 板块轮动速度卡片 + 申万行业热力图：1:2 grid 合并一行（左轮动卡 / 右热力图）
  const rotHmGrid = document.createElement("div");
  rotHmGrid.className = "rotation-heatmap-grid";
  container.appendChild(rotHmGrid);
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
  container.appendChild(anchorBar);
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
  container.appendChild(swGridWrap);

  // I2：概念板块也加搜索筛选 -- 共用 state.industrySearch，一个搜索条同时过滤两区
  let conceptGridWrap = null;
  let conceptTitle = null; // 提到 if 块外，供 _applyIndustryFilter 更新 shown/total 标题
  if (conceptCount > 0) {
    const thscSection = document.createElement("div");
    thscSection.id = "thsc-concepts";
    container.appendChild(thscSection);

    conceptTitle = document.createElement("div");
    conceptTitle.className = "section-title";
    conceptTitle.textContent = `概念板块指数折线（${conceptCount}/${conceptCount} 个，` + _t("concept_title_signal") + ` + 回测统计）`;
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
    title.textContent = `申万行业指数折线（${shown}/${total} 个，` + _t("concept_title_signal") + ` + 资金流/成交额/换手率 + 行业内宽度）`;
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
        conceptTitle.textContent = `概念板块指数折线（${conceptShown}/${conceptTotal} 个，` + _t("concept_title_signal") + ` + 回测统计）`;
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
  const _rotFreqExisting = container.querySelector(".rotation-freq-card");
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
    container.insertBefore(rotFreqCard, anchorBar);
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

// ============ B4: ETF评分列表（分页+搜索） ============
// 数据源: static-site/data/etf_score_list.json (三分类, 2026-07-25 C2)
//   buy_list: C2 买入机会(high<60 AND hands>=2 AND amt_pct>60, ~194只), 字段含 hands/amt_pct
//   sell_list: 过热卖出信号(high>=60, ~96只), 字段含 sell_signal
//   hold_list: 持有观察(不够格buy但不过热 high<60 AND not C2, ~919只), 字段含 hold_reason
//   ohlc: 近30交易日 [[date,o,h,l,c],...] 升序, 前端 _etfSparkline 用 close 画迷你折线
// 合并成统一列表 + side(buy/sell/hold) 字段, 分区渲染(持仓置顶 -> 卖出/持有观察 -> 买入折叠)
// 三分类互斥(每只ETF出现一次), 数据不足(high_alert=None)不进任何list
// 4项 UX(2026-07-25): ①卖出/持有置顶区 ②买入默认折叠Top20 ③持仓永远置顶高亮 ④5档分档色块
const ETF_SCORE_PAGE_SIZE = 50;       // 买入区展开后页大小
const ETF_SELLHOLD_PAGE_SIZE = 100;   // 卖出/持有观察区页大小(145只大页少翻页)
const ETF_BUY_COLLAPSE_TOP = 20;      // 买入区折叠态显 Top N(按score降序)
const ETF_TIER_LABEL = {
  "strong-sell": _t("etf_strong_sell"), "sell": _t("etf_sell"), "hold": _t("etf_hold"),
  "buy": _t("etf_buy"), "strong-buy": _t("etf_strong_buy")
};
// sideFilter: "all"/"buy"/"sell"/"hold" 快速过滤(默认 all, 买入区在前首屏可见)
// sortKey/sortDir: 排序键("score"/"hands"/"amt_pct"/"high_alert")与方向("desc"/"asc"), 默认 score 降序
const _etfScoreState = { all: [], filtered: [], page: 1, pageSellHold: 1, search: "", meta: null, holdingOnly: false, buyExpanded: false, sideFilter: "all", sortKey: "score", sortDir: "desc", dedup: false };

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

// ETF评分行迷你折线(sparkline): 用近30日 close 画 SVG 线, 末点高亮。
// ohlc 格式 [[date,o,h,l,c],...] 升序; 取 close(idx=4) 画线。数据<2点返空串。
// 涨跌色: 末值>=首值用红(up), 反之绿(down), 跟主题涨跌色一致(A股红涨绿跌)。
function _etfSparkline(ohlc, w, h) {
  if (!ohlc || ohlc.length < 2) return "";
  var vals = ohlc.map(function (d) { return d[4]; }).filter(function (v) { return v != null; });
  if (vals.length < 2) return "";
  var min = Math.min.apply(null, vals), max = Math.max.apply(null, vals);
  var range = max - min || 1;
  var n = vals.length;
  var pts = vals.map(function (v, i) {
    var x = (i / (n - 1)) * w;
    var y = h - 2 - ((v - min) / range) * (h - 4);
    return x.toFixed(1) + "," + y.toFixed(1);
  }).join(" ");
  var lastY = h - 2 - ((vals[n - 1] - min) / range) * (h - 4);
  var isUp = vals[n - 1] >= vals[0];
  var stroke = isUp ? "#e6492e" : "#2e8b57";
  return '<svg class="etf-spark" width="' + w + '" height="' + h + '" viewBox="0 0 ' + w + ' ' + h + '">'
    + '<polyline points="' + pts + '" fill="none" stroke="' + stroke + '" stroke-width="1.5"/>'
    + '<circle cx="' + w.toFixed(1) + '" cy="' + lastY.toFixed(1) + '" r="2.2" fill="' + stroke + '"/>'
    + '</svg>';
}

// 5档分档(2026-07-25 C2三分类): 强卖出/卖出/持有观察/买入/强买入
// 阈值基于 score 分布:
//   sell side(过热~96只): score>=75=强卖出, <75=卖出
//   hold side(持有观察~919只): 全归"持有观察"档
//   buy(C2~194只): score>=76=强买入, <76=买入
// 配色延续 177e1e0a 淡雅低饱和(非纯绿纯红), dark/redgold 由 CSS class 变体处理
function _etfScoreTier(e) {
  const score = e.score == null ? -1 : e.score;
  if (e.side === "sell") return score >= 75 ? "strong-sell" : "sell";
  if (e.side === "hold") return "hold";
  return score >= 76 ? "strong-buy" : "buy";
}
function _etfScoreColor(score, side) {
  // 兼容旧调用(score, side) -> 返回主色(light主题); dark/redgold 由 CSS class 控制
  // 新代码应优先用 _etfScoreTier(e) + .etf-tier-${tier} class
  const tier = _etfScoreTier({ score: score, side: side });
  const map = {
    "strong-sell": "#3d5a6a", "sell": "#5a7a8a", "hold": "#b8860b",
    "buy": "#c08080", "strong-buy": "#7a3030"
  };
  return map[tier] || "var(--text-3,#86909c)";
}

function _etfScorePages() {
  return Math.max(1, Math.ceil(_etfScoreState.filtered.length / ETF_SCORE_PAGE_SIZE));
}

// 排序标签(中文, 用于 section-head 副标题)
function _etfSortLabel() {
  const map = {
    score: "评分", hands: _t("etf_score_hands"), amt_pct: "成交额分位",
    high_alert: "高位预警", low_alert: "低位机会"
  };
  return map[_etfScoreState.sortKey] || "评分";
}

// ============ ETF 买入机会同类去重: 同行业/同指数只保留评分最高一只 ============
// 优先级表(从前到后匹配, 复合关键词最优先 -> 单一行业/主题 -> 宽基指数 -> 全名自身成组)
// name.indexOf(k)>=0 即归到该关键词组; 例如"建材ETF"和"中证建材ETF"都含"建材"归同组
const ETF_DEDUP_KEYWORDS = [
  // 复合关键词(先匹配, 避免被单一关键词抢先)
  "央企红利", "红利低波", "港股通汽车", "港股通红利", "港股通创新药", "港股通医药", "医疗器械",
  // 单一行业/主题关键词
  "人工智能", "云计算", "大数据", "物联网", "5G", "创新药", "碳中和", "电池", "储能", "机器人",
  "智能车", "新能源车", "新能源", "光伏", "半导体", "芯片", "军工", "国防", "医药", "医疗",
  "银行", "券商", "非银", "消费", "食品", "酒", "煤炭", "有色", "房地产", "电力", "钢铁",
  "农业", "家电", "物流", "旅游", "通信", "化工", "基建", "传媒", "计算机", "建材", "矿业",
  "影视", "央企", "红利", "黄金", "白银", "原油", "豆粕", "稀土", "港股通", "中概", "互联",
  // 宽基指数关键词
  "中证1000", "中证2000", "中证500", "中证A500", "中证A50", "中证A100",
  "沪深300", "上证50", "上证指数", "创业板", "科创50", "A500", "A50", "A100"
];
// 计算 ETF 去重分组 key: 按优先级表顺序匹配 name, 命中即返回该关键词; 都不匹配返回 name 自身(独占一组)
function _etfDedupKey(name) {
  if (!name) return "";
  const n = String(name);
  for (let i = 0; i < ETF_DEDUP_KEYWORDS.length; i++) {
    if (n.indexOf(ETF_DEDUP_KEYWORDS[i]) >= 0) return ETF_DEDUP_KEYWORDS[i];
  }
  return n; // 都不匹配, 用全名自身成组(不与其他合并)
}

function _applyEtfScoreFilter() {
  const s = _etfScoreState.search.trim().toLowerCase();
  let filtered = s
    ? _etfScoreState.all.filter((e) =>
        String(e.etf_code).toLowerCase().includes(s) || String(e.name).toLowerCase().includes(s))
    : _etfScoreState.all.slice();
  // side 筛选: all=全部, buy/sell/hold=只看该 side
  if (_etfScoreState.sideFilter !== "all") {
    filtered = filtered.filter((e) => e.side === _etfScoreState.sideFilter);
  }
  // 持仓筛选: 只看持仓的 ETF
  if (_etfScoreState.holdingOnly) {
    const hset = _getEtfHoldingsSet();
    filtered = filtered.filter((e) => hset[e.etf_code]);
  }
  _etfScoreState.filtered = filtered;
  const pages = _etfScorePages();
  if (_etfScoreState.page > pages) _etfScoreState.page = pages;
  if (_etfScoreState.page < 1) _etfScoreState.page = 1;
  const shPages = Math.max(1, Math.ceil(_etfScoreState.filtered.filter((e) => e.side === "sell" || e.side === "hold").length / ETF_SELLHOLD_PAGE_SIZE));
  if (_etfScoreState.pageSellHold > shPages) _etfScoreState.pageSellHold = shPages;
  if (_etfScoreState.pageSellHold < 1) _etfScoreState.pageSellHold = 1;
  _renderEtfScoreBody();
}

// 排序工具: 按 sortKey/sortDir 排序数组(返回新数组, 不改原数组)
// null/undefined 值排到末尾(无论升降序, 避免无手数/无amt_pct的ETF挤到前面)
// keepSideGroup=true 时保留 sell 先 hold 后的分组(sellHold 区用, 卖出比持有观察更紧急)
function _sortEtfList(arr, keepSideGroup) {
  const key = _etfScoreState.sortKey;
  const dir = _etfScoreState.sortDir === "asc" ? 1 : -1;
  return arr.slice().sort((a, b) => {
    if (keepSideGroup && a.side !== b.side && (a.side === "sell" || a.side === "hold") && (b.side === "sell" || b.side === "hold")) {
      return a.side === "sell" ? -1 : 1;
    }
    const va = a[key], vb = b[key];
    if (va == null && vb == null) return 0;
    if (va == null) return 1;   // a 无值排后
    if (vb == null) return -1;  // b 无值排后
    return (va - vb) * dir;
  });
}

// 分页器HTML生成(scope: "buy"/"sh" 标识区, 用于绑定区分)
function _renderEtfPager(scope, page, pages, total) {
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

// 任务2(2026-08-02): ETF 评分明细弹窗 - 5区块决策依据(档位/手数or卖出/8维度/置信度/历史类比)
// 复用 openIndexAnalyzeModal 模式(rule-modal 骨架 + _labCustom* HTML 函数)
// 数据来自 etf_score_list.json list item 的 dims/adapt/dim_hits/data_thresholds/history_analogy/confidence/sell_action
// 不再额外 fetch alert_analyze_*.json(后端已把结构化明细内联进 list item, 单次加载即可弹窗)
function openEtfScoreDetailModal(code) {
  // 从 _etfScoreState.all 查 item(已合并 buy/sell/hold, 含新字段)
  const e = (_etfScoreState.all || []).find((x) => x.etf_code === code);
  if (!e) return;
  let modal = document.getElementById("etfScoreDetailModal");
  if (!modal) {
    modal = document.createElement("div");
    modal.id = "etfScoreDetailModal";
    modal.className = "rule-modal hidden";
    modal.innerHTML = `<div class="rule-modal-overlay"></div>
      <div class="rule-modal-body signal-chart-modal-body">
        <div class="rule-modal-header">
          <h3 class="etf-detail-title">🔬 ETF 决策依据</h3>
          <button class="rule-modal-close" aria-label="关闭">&times;</button>
        </div>
        <div class="rule-modal-content etf-detail-content"></div>
      </div>`;
    document.body.appendChild(modal);
    modal.querySelector(".rule-modal-overlay").onclick = closeEtfScoreDetailModal;
    modal.querySelector(".rule-modal-close").onclick = closeEtfScoreDetailModal;
    document.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape" && !modal.classList.contains("hidden")) closeEtfScoreDetailModal();
    });
  }
  modal.querySelector(".etf-detail-title").textContent = "🔬 " + (e.name || code) + " 决策依据";
  const body = modal.querySelector(".etf-detail-content");
  body.innerHTML = '<div class="lab-custom-loading">⏳ 加载中…</div>';
  modal.classList.remove("hidden");
  document.body.style.overflow = "hidden";

  // === 5区块渲染 ===
  const tier = _etfScoreTier(e);
  const tierLabel = ETF_TIER_LABEL[tier] || "";
  const sideLabel = e.side === "buy" ? _t("etf_side_buy") : e.side === "hold" ? _t("etf_side_hold") : _t("etf_side_sell");
  const sideCls = e.side === "buy" ? "etf-side-buy" : e.side === "hold" ? "etf-side-hold" : "etf-side-sell";
  const col = _etfScoreColor(e.score, e.side);

  // 区块1: 决策结论头(档位chip + side tag + 评分 + 数据时点)
  // 复用 ETF 评分行的 chip/side 样式, 加 score + high/low alert + 数据日期
  const headHTML = `<div class="lab-custom-score-card lab-custom-block-gap">
    <div class="lab-custom-score-head">
      <div class="lab-custom-score-title">${_esc(e.name || "")} <span class="lab-custom-score-date">📅 ${_esc(e.etf_code || "")}</span></div>
      <div class="lab-custom-adapt">
        <span class="etf-tier-chip etf-tier-chip-${tier}">${tierLabel}</span>
        <span class="etf-side-tag ${sideCls}" style="margin-left:6px">${sideLabel}</span>
      </div>
    </div>
    <div class="lab-custom-score-grid">
      <div class="lab-custom-score-cell">
        <div class="lab-custom-cell-label">评分<span class="lab-custom-cell-sublabel">${sideLabel}主分</span></div>
        <div class="lab-custom-cell-score" style="color:${col}">${e.score != null ? e.score.toFixed(2) : "-"}</div>
      </div>
      <div class="lab-custom-score-cell">
        <div class="lab-custom-cell-label">高位预警<span class="lab-custom-cell-sublabel">≥70 过热</span></div>
        <div class="lab-custom-cell-score">${e.high_alert != null ? e.high_alert.toFixed(2) : "-"}</div>
      </div>
      <div class="lab-custom-score-cell">
        <div class="lab-custom-cell-label">低位机会<span class="lab-custom-cell-sublabel">≥70 机会</span></div>
        <div class="lab-custom-cell-score">${e.low_alert != null ? e.low_alert.toFixed(2) : "-"}</div>
      </div>
    </div>
  </div>`;

  // 区块2: 手数/卖出动作(buy 显示买点手数 + 卖出动作; sell 显示 sell_action.label + pct 进度条)
  let actionHTML = "";
  if (e.side === "buy") {
    // buy: 买点 X 手 + 6维分(如果有). ETF list item 无 position.detail 6维分, 显示手数+波动率+amt_pct
    const handsTxt = e.hands != null ? e.hands + " 手" : "-";
    const volTxt = e.volatility != null ? e.volatility.toFixed(2) + "%" : "-";
    const amtTxt = e.amt_pct != null ? e.amt_pct.toFixed(0) : "-";
    actionHTML = `<div class="lab-custom-score-card lab-custom-block-gap">
      <div class="lab-custom-section-title">` + _t("etf_buy_section") + `</div>
      <div class="lab-custom-score-grid">
        <div class="lab-custom-score-cell"><div class="lab-custom-cell-label">建议档数</div><div class="lab-custom-cell-score">${handsTxt}</div></div>
        <div class="lab-custom-score-cell"><div class="lab-custom-cell-label">波动率</div><div class="lab-custom-cell-score">${volTxt}</div></div>
        <div class="lab-custom-score-cell"><div class="lab-custom-cell-label">流动性分位</div><div class="lab-custom-cell-score">${amtTxt}</div></div>
      </div>
    </div>`;
  } else if (e.side === "sell" && e.sell_action) {
    // sell: sell_action.label + pct 进度条(明确减仓比例)
    const sa = e.sell_action;
    const pct = sa.pct || 0;
    const barColor = pct >= 75 ? "#e6492e" : pct >= 50 ? "#ff9800" : pct > 0 ? "#ffc107" : "#2e8b57";
    actionHTML = `<div class="lab-custom-score-card lab-custom-block-gap">
      <div class="lab-custom-section-title">` + _t("etf_sell_section") + `</div>
      <div class="lab-custom-score-summary" style="margin:4px 0;font-size:15px">建议 <b>${_esc(sa.label || "")}</b></div>
      <div style="background:var(--bg-2,rgba(128,128,128,0.1));border-radius:6px;height:24px;overflow:hidden;margin:4px 0;position:relative">
        <div style="width:${pct}%;height:100%;background:${barColor};transition:width .3s"></div>
        <span style="position:absolute;right:8px;top:3px;font-size:12px;font-weight:600;color:var(--text-1)">` + _t("position_reduce_prefix") + ` ${pct}%</span>
      </div>
      <div style="font-size:11px;color:var(--text-3);line-height:1.5">基于高位预警分 ${e.high_alert != null ? e.high_alert.toFixed(2) : "-"}（` + _t("etf_high_alert_rule") + `）</div>
    </div>`;
  } else {
    // hold: 持有观察说明
    actionHTML = `<div class="lab-custom-score-card lab-custom-block-gap">
      <div class="lab-custom-section-title">⏸ 持有观察</div>
      <div class="lab-custom-score-summary">${_esc(e.sell_signal || "持有观察")}</div>
      <div style="font-size:11px;color:var(--text-3);margin-top:6px">` + _t("etf_not_qualified") + `</div>
    </div>`;
  }

  // 区块4: 置信度(数据完整度60% + 信号一致性40%, 对齐 88魔咒 _confZh 高/中/低)
  let confHTML = "";
  if (e.confidence) {
    const c = e.confidence;
    const confZh = ({ high: "高", medium: "中", low: "低" })[c.level] || "-";
    const confColor = c.level === "high" ? "#2e8b57" : c.level === "medium" ? "#ff9800" : "#e6492e";
    const missingTxt = (c.missing || []).length ? (c.missing || []).join(", ") : "无";
    const completePct = ((c.avail_h + c.avail_l) / 16 * 100).toFixed(0);
    const consistencyPct = ((c.hit_count || 0) / 16 * 100).toFixed(0);
    confHTML = `<div class="lab-custom-score-card lab-custom-block-gap">
      <div class="lab-custom-section-title">🎯 置信度</div>
      <div class="lab-custom-score-grid">
        <div class="lab-custom-score-cell">
          <div class="lab-custom-cell-label">置信等级</div>
          <div class="lab-custom-cell-score" style="color:${confColor}">${confZh}</div>
          <div class="lab-custom-cell-desc">综合分 ${c.score != null ? c.score.toFixed(1) : "-"}/100</div>
        </div>
        <div class="lab-custom-score-cell">
          <div class="lab-custom-cell-label">数据完整度<span class="lab-custom-cell-sublabel">权重 60%</span></div>
          <div class="lab-custom-cell-score">${completePct}%</div>
          <div class="lab-custom-cell-desc">高位 ${c.avail_h}/8 + 低位 ${c.avail_l}/8 = ${c.avail_h + c.avail_l}/16 维度</div>
        </div>
        <div class="lab-custom-score-cell">
          <div class="lab-custom-cell-label">信号一致性<span class="lab-custom-cell-sublabel">权重 40%</span></div>
          <div class="lab-custom-cell-score">${consistencyPct}%</div>
          <div class="lab-custom-cell-desc">命中(≥60) ${c.hit_count || 0}/16 维度</div>
        </div>
      </div>
      <div style="font-size:11px;color:var(--text-3);margin-top:6px" title="缺失维度: ${_esc(missingTxt)}">缺失维度: ${_esc(missingTxt)}</div>
    </div>`;
  }

  // 区块3: 8维度明细(复用 _labCustomDimsTableHTML: H1-H8/L1-L8 分值+权重+贡献+命中)
  const dimsHTML = (typeof _labCustomDimsTableHTML === "function")
    ? _labCustomDimsTableHTML(e.dim_hits, e.dims, e.adapt) : "";

  // 区块5: 历史类比(复用 _labCustomHistoryHTML: Top3相似日 + 后续涨跌统计)
  const histHTML = (typeof _labCustomHistoryHTML === "function")
    ? _labCustomHistoryHTML(e.history_analogy, {}) : "";

  // 附加: 数据阈值表(折叠, 复用 _labCustomThresholdsHTML: 当前值+阈值+命中状态+desc)
  const threshHTML = (typeof _labCustomThresholdsHTML === "function")
    ? _labCustomThresholdsHTML(e.data_thresholds) : "";

  // 合规底栏
  const footerHTML = (typeof _labCustomFooterHTML === "function")
    ? _labCustomFooterHTML(null, null) : "";

  body.innerHTML = headHTML + actionHTML + confHTML + dimsHTML + histHTML + threshHTML + footerHTML;

  // 折叠阈值表交互(同 openIndexAnalyzeModal)
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

function closeEtfScoreDetailModal() {
  const modal = document.getElementById("etfScoreDetailModal");
  if (modal) modal.classList.add("hidden");
  document.body.style.overflow = "";
}

function _renderEtfScoreBody() {
  const body = document.getElementById("etf-score-body");
  if (!body) return;
  const st = _etfScoreState;
  const hset = _getEtfHoldingsSet();
  const filtered = st.filtered;

  // 拆3组: 持仓置顶 / 买入 / 卖出+持有观察
  // 渲染顺序(2026-07-25 优化): 持仓 -> 买入机会(首屏可见) -> 卖出/持有观察
  //   原顺序 持仓->卖出/持有观察->买入 导致买入被埋在1000+只sell/hold后面, 用户要滚很久
  // 持仓行从原 side 区上移到顶部持仓区, 原 side 区去重(避免重复显示)
  let holdings = filtered.filter((e) => hset[e.etf_code]);
  let sellHold = filtered.filter((e) => (e.side === "sell" || e.side === "hold") && !hset[e.etf_code]);
  let buys = filtered.filter((e) => e.side === "buy" && !hset[e.etf_code]);
  // 排序: 用 _sortEtfList 按 sortKey/sortDir 排序; sellHold 保留 sell 先 hold 后的分组(keepSideGroup)
  holdings = _sortEtfList(holdings);
  sellHold = _sortEtfList(sellHold, true);
  buys = _sortEtfList(buys);
  // 同类去重: 同行业/同指数买入ETF只保留评分最高一只(buys已按score降序, filter保留每组首个即最优)
  if (st.dedup && buys.length > 0) {
    const seen = {};
    buys = buys.filter((e) => {
      const k = _etfDedupKey(e.name);
      if (seen[k]) return false;
      seen[k] = true;
      return true;
    });
  }

  // 统计条
  const buyN = st.all.filter((e) => e.side === "buy").length;
  const sellN = st.all.filter((e) => e.side === "sell").length;
  const holdN = st.all.filter((e) => e.side === "hold").length;
  const holdingInList = holdings.length;
  let html = '<div class="etf-score-stat">共 ' + st.all.length + ' 只'
    + (st.meta && st.meta.full_market ? '（全市场）' : '（代表性清单）')
    + ' · ' + _t("etf_side_buy") + ' ' + buyN + ' · ' + _t("etf_side_hold") + ' ' + holdN + ' · ' + _t("etf_side_sell") + ' ' + sellN
    + (holdingInList > 0 ? ' · <b class="etf-stat-hold">我的持仓 ' + holdingInList + '</b>' : '')
    + (st.search ? ' · 搜索命中 ' + filtered.length : '')
    + (st.holdingOnly ? ' · 只看持仓' : '') + '</div>';

  if (filtered.length === 0) {
    html += '<div class="etf-score-empty">未命中任何 ETF，换个代码或名称试试</div>';
    body.innerHTML = html;
    return;
  }

  // 渲染单行(3区共用): 加 etf-tier-${tier} class + 档位chip
  const renderRow = (e, rank) => {
    const tier = _etfScoreTier(e);
    const col = _etfScoreColor(e.score, e.side);
    const sideTag = e.side === "buy"
      ? '<span class="etf-side-tag etf-side-buy">' + _t("etf_side_buy") + '</span>'
      : e.side === "hold"
      ? '<span class="etf-side-tag etf-side-hold">' + _t("etf_side_hold") + '</span>'
      : '<span class="etf-side-tag etf-side-sell">' + _t("etf_side_sell") + '</span>';
    const tierChip = '<span class="etf-tier-chip etf-tier-chip-' + tier + '">' + (ETF_TIER_LABEL[tier] || '') + '</span>';
    const ntTag = e.is_national_team ? '<span class="etf-nt-tag" title="汪汪队宽基ETF">汪汪队</span>' : '';
    const signalTxt = e.side === "buy"
      ? (e.hands != null ? _t("etf_buypoint_prefix") + ' ' + e.hands + ' ' + _t("etf_hands_unit") : '')
      : e.side === "hold"
      // hold 侧保留 hold_reason(sell_signal 字段)显示, 信息更具体(含"未达买入阈值")
      ? (e.sell_signal ? _esc(e.sell_signal) : '继续持有')
      // 任务3(2026-08-02): sell 行优先显示 sell_action.label(含减仓比例语义)替代旧 sell_signal 文案
      : (e.sell_action && e.sell_action.label ? _esc(e.sell_action.label) : (e.sell_signal ? _esc(e.sell_signal) : ''));
    const isHolding = !!hset[e.etf_code];
    const holdTag = isHolding ? '<span class="etf-hold-tag" title="我的持仓">⭐ 持仓</span>' : '';
    const spark = _etfSparkline(e.ohlc, 60, 20);
    const sparkTag = spark ? '<span class="etf-spark-wrap" title="近30日走势">' + spark + '</span>' : '';
    // 任务2(2026-08-02): 行可点击打开 ETF 评分明细弹窗(data-etf-code + clickable cursor)
    // 仅当有 dims/confidence 等结构化明细时才可点(后端已全量补, 旧数据兜底不可点)
    const hasDetail = !!(e.dims || e.confidence || e.dim_hits);
    const clickAttr = hasDetail ? ' data-etf-code="' + _esc(e.etf_code) + '"' : '';
    const clickCls = hasDetail ? ' etf-score-row-clickable' : '';
    return '<div class="etf-score-row etf-side-' + e.side + ' etf-tier-' + tier + (isHolding ? ' is-holding' : '') + clickCls + '"' + clickAttr + '>'
      + '<div class="etf-row-main">'
      + '<span class="etf-rank">#' + rank + '</span>'
      + '<span class="etf-code">' + _esc(e.etf_code) + '</span>'
      + '<span class="etf-name">' + _esc(e.name) + ntTag + holdTag + '</span>'
      + sparkTag
      + '<span class="etf-score etf-tier-score-' + tier + '" style="color:' + col + '">' + (e.score != null ? e.score.toFixed(2) : '-') + '</span>'
      + '</div>'
      + '<div class="etf-row-sub">'
      + tierChip
      + sideTag
      + (signalTxt ? '<span class="etf-signal">' + signalTxt + '</span>' : '')
      + '<span class="etf-alert" title="高位预警/低位机会区间">预警 ' + (e.high_alert != null ? e.high_alert.toFixed(2) : '-') + ' / ' + (e.low_alert != null ? e.low_alert.toFixed(2) : '-') + '</span>'
      + '</div>'
      + (e.reason_summary ? '<div class="etf-reason">' + _esc(e.reason_summary) + '</div>' : '')
      + (hasDetail ? '<div class="etf-detail-hint" style="font-size:10px;color:var(--text-3);margin-top:2px">💡 点击查看决策依据明细</div>' : '')
      + '</div>';
  };

  // 区A: 我的持仓(置顶, 不分页, 无持仓不显示) —— 持仓永远在顶部可见, 不用翻页找
  if (holdings.length > 0) {
    html += '<div class="etf-section etf-section-holdings">';
    html += '<div class="etf-section-head"><span class="etf-section-icon">⭐</span> 我的持仓 <span class="etf-section-count">' + holdings.length + '</span>'
      + '<span class="etf-section-sub">按' + _etfSortLabel() + '排序</span></div>';
    html += '<div class="etf-score-list">';
    holdings.forEach((e, i) => { html += renderRow(e, i + 1); });
    html += '</div></div>';
  }

  // holdingOnly 模式只显持仓区
  if (!st.holdingOnly) {
    if (st.sideFilter !== "all") {
      // 单区模式: 只显示筛选的 side, 统一 50/页分页(取消折叠/分区差异, 简化浏览)
      // 持仓区已在上方显示(不受 sideFilter 影响, 用户持仓永远可见)
      const sideList = st.sideFilter === "buy" ? buys
        : st.sideFilter === "sell" ? sellHold.filter((e) => e.side === "sell")
        : sellHold.filter((e) => e.side === "hold");
      const sideLabel = st.sideFilter === "buy" ? _t("etf_side_buy")
        : st.sideFilter === "sell" ? _t("etf_side_sell")
        : _t("etf_side_hold");
      const sideIcon = st.sideFilter === "buy" ? "🔺" : st.sideFilter === "sell" ? "🔻" : "⏸";
      const secClass = st.sideFilter === "buy" ? "etf-section-buy"
        : st.sideFilter === "sell" ? "etf-section-sellhold"
        : "etf-section-sellhold";
      if (sideList.length > 0) {
        const pages = Math.max(1, Math.ceil(sideList.length / ETF_SCORE_PAGE_SIZE));
        if (st.page > pages) st.page = pages;
        const start = (st.page - 1) * ETF_SCORE_PAGE_SIZE;
        const slice = sideList.slice(start, start + ETF_SCORE_PAGE_SIZE);
        html += '<div class="etf-section ' + secClass + '">';
        html += '<div class="etf-section-head"><span class="etf-section-icon">' + sideIcon + '</span> ' + sideLabel + ' <span class="etf-section-count">' + sideList.length + '</span>'
          + '<span class="etf-section-sub">按' + _etfSortLabel() + '排序</span></div>';
        html += '<div class="etf-score-list">';
        slice.forEach((e, i) => { html += renderRow(e, start + i + 1); });
        html += '</div>';
        if (pages > 1) html += _renderEtfPager("buy", st.page, pages, sideList.length);
        html += '</div>';
      } else {
        html += '<div class="etf-score-empty">当前筛选下无 ' + sideLabel + ' ETF</div>';
      }
    } else {
      // 全部模式: 三区显示, 顺序 买入(首屏可见) -> 卖出/持有观察
      //   原顺序 卖出/持有观察->买入 导致买入被埋在1000+只sell/hold后面, 2026-07-25 调整
      // 区B: 买入(默认折叠Top20, 展开后50/页) -- 折叠态首屏可见 Top20 买入机会
      if (buys.length > 0) {
        const strongBuyN = buys.filter((e) => _etfScoreTier(e) === "strong-buy").length;
        const buyN2 = buys.length - strongBuyN;
        html += '<div class="etf-section etf-section-buy">';
        html += '<div class="etf-section-head"><span class="etf-section-icon">🔺</span> ' + _t("etf_side_buy") + ' <span class="etf-section-count">' + buys.length + '</span>'
          + '<span class="etf-section-sub">' + _t("etf_strong_buy") + ' ' + strongBuyN + ' · ' + _t("etf_buy") + ' ' + buyN2 + ' · 按' + _etfSortLabel() + '排序' + (st.dedup ? ' · 同类去重后 ' + buys.length + ' 只' : '') + '</span></div>';
        if (st.buyExpanded) {
          // 展开态: 50/页分页
          const bPages = Math.max(1, Math.ceil(buys.length / ETF_SCORE_PAGE_SIZE));
          if (st.page > bPages) st.page = bPages;
          const bStart = (st.page - 1) * ETF_SCORE_PAGE_SIZE;
          const bSlice = buys.slice(bStart, bStart + ETF_SCORE_PAGE_SIZE);
          html += '<div class="etf-score-list">';
          bSlice.forEach((e, i) => { html += renderRow(e, bStart + i + 1); });
          html += '</div>';
          if (bPages > 1) html += _renderEtfPager("buy", st.page, bPages, buys.length);
          html += '<div class="etf-section-collapse-wrap"><button class="etf-section-collapse" data-action="collapse-buy">收起（仅显示 Top ' + ETF_BUY_COLLAPSE_TOP + '）</button></div>';
        } else {
          // 折叠态: Top20 + 展开按钮
          const top = buys.slice(0, ETF_BUY_COLLAPSE_TOP);
          html += '<div class="etf-score-list">';
          top.forEach((e, i) => { html += renderRow(e, i + 1); });
          html += '</div>';
          if (buys.length > ETF_BUY_COLLAPSE_TOP) {
            html += '<div class="etf-section-collapse-wrap"><button class="etf-section-collapse" data-action="expand-buy">展开全部 ' + buys.length + ' 只（共 ' + Math.ceil(buys.length / ETF_SCORE_PAGE_SIZE) + ' 页）</button></div>';
          }
        }
        html += '</div>';
      }
      // 区C: 卖出/持有观察(100/页大页少翻页)
      if (sellHold.length > 0) {
        const shPages = Math.max(1, Math.ceil(sellHold.length / ETF_SELLHOLD_PAGE_SIZE));
        if (st.pageSellHold > shPages) st.pageSellHold = shPages;
        const shStart = (st.pageSellHold - 1) * ETF_SELLHOLD_PAGE_SIZE;
        const shSlice = sellHold.slice(shStart, shStart + ETF_SELLHOLD_PAGE_SIZE);
        const sellN2 = sellHold.filter((e) => e.side === "sell").length;
        const holdN2 = sellHold.filter((e) => e.side === "hold").length;
        html += '<div class="etf-section etf-section-sellhold">';
        html += '<div class="etf-section-head"><span class="etf-section-icon">🔻</span> ' + _t("etf_sellhold_section") + ' <span class="etf-section-count">' + sellHold.length + '</span>'
          + '<span class="etf-section-sub">' + _t("etf_side_sell") + ' ' + sellN2 + ' · ' + _t("etf_side_hold") + ' ' + holdN2 + ' · 按' + _etfSortLabel() + '排序</span></div>';
        html += '<div class="etf-score-list">';
        shSlice.forEach((e, i) => { html += renderRow(e, shStart + i + 1); });
        html += '</div>';
        if (shPages > 1) html += _renderEtfPager("sh", st.pageSellHold, shPages, sellHold.length);
        html += '</div>';
      }
    }
  }

  body.innerHTML = html;
  // 绑定分页按钮(scope 区分 buy/sh)
  body.querySelectorAll(".etf-page-btn[data-page]").forEach((b) => {
    b.onclick = () => {
      if (b.disabled) return;
      const p = parseInt(b.dataset.page, 10) || 1;
      const scope = b.dataset.scope || "buy";
      if (scope === "sh") _etfScoreState.pageSellHold = p;
      else _etfScoreState.page = p;
      _renderEtfScoreBody();
      const top = body.getBoundingClientRect().top + window.scrollY - 80;
      window.scrollTo({ top: Math.max(0, top), behavior: "smooth" });
    };
  });
  // 绑定展开/收起按钮(localStorage 记忆 buyExpanded)
  body.querySelectorAll(".etf-section-collapse[data-action]").forEach((b) => {
    b.onclick = () => {
      const act = b.dataset.action;
      if (act === "expand-buy") {
        _etfScoreState.buyExpanded = true;
        try { localStorage.setItem("etf_buy_expanded", "1"); } catch (e) {}
        _etfScoreState.page = 1;
      } else if (act === "collapse-buy") {
        _etfScoreState.buyExpanded = false;
        try { localStorage.setItem("etf_buy_expanded", "0"); } catch (e) {}
      }
      _renderEtfScoreBody();
    };
  });
  // 任务2(2026-08-02): 行 click 委托打开 ETF 评分明细弹窗(5区块决策依据)
  // 覆盖式绑定(body 不变, 每次渲染覆盖 onclick 无重复绑定问题)
  body.querySelectorAll(".etf-score-row-clickable[data-etf-code]").forEach((row) => {
    row.style.cursor = "pointer";
    row.onclick = () => openEtfScoreDetailModal(row.dataset.etfCode);
  });
}

async function renderEtfScore(container) {
  // container 可选：由 renderFund 二级 tab 分发器传入 subContent；直接调用时 fallback 到全局 content
  const _c = container || content;
  // R2 合规修复（2026-07-20）：4.3MB 走 R2 避免双源冗余（upload-data-large 上传 data/ 前缀）
  const r = await fetchJSON("https://ssd.fx8.store/data/etf_score_list.json");
  _etfScoreState.meta = {
    date: r.date, updated_at: r.updated_at, source: r.source,
    universe_count: r.universe_count, full_market: r.full_market,
    buy_top: r.buy_top, sell_top: r.sell_top, fetch_count: r.fetch_count, skip_count: r.skip_count,
  };
  // 合并 buy_list + sell_list + hold_list 成统一列表(三分类, 2026-07-25 C2)
  // buy=C2买入机会 / sell=过热卖出信号 / hold=不够格buy但不过热持有观察
  const all = [];
  (r.buy_list || []).forEach((e) => all.push({
    etf_code: e.etf_code, name: e.name, score: e.score, side: "buy",
    hands: e.hands, amt_pct: e.amt_pct,
    high_alert: e.high_alert, low_alert: e.low_alert,
    is_national_team: e.is_national_team, reason_summary: e.reason_summary,
    sell_signal: null, ohlc: e.ohlc || [],
    // 任务2/3(2026-08-02): 决策依据明细 + 置信度 + 卖出动作(弹窗5区块用)
    dims: e.dims, adapt: e.adapt, dim_hits: e.dim_hits,
    data_thresholds: e.data_thresholds, history_analogy: e.history_analogy,
    confidence: e.confidence, sell_action: e.sell_action,
  }));
  (r.sell_list || []).forEach((e) => {
    // sell_list 只含过热(high_alert>=60), 统一 side="sell"(不再按 sell_signal 拆 hold)
    all.push({
      etf_code: e.etf_code, name: e.name, score: e.score, side: "sell",
      hands: null, amt_pct: null,
      high_alert: e.high_alert, low_alert: e.low_alert,
      is_national_team: e.is_national_team, reason_summary: e.reason_summary,
      sell_signal: e.sell_signal, ohlc: e.ohlc || [],
      // 任务2/3: 决策依据明细 + 置信度 + 卖出动作
      dims: e.dims, adapt: e.adapt, dim_hits: e.dim_hits,
      data_thresholds: e.data_thresholds, history_analogy: e.history_analogy,
      confidence: e.confidence, sell_action: e.sell_action,
    });
  });
  (r.hold_list || []).forEach((e) => {
    // hold_list: 不够格buy但不过热, side="hold"(新数据源, 原从 sell_list 拆)
    // sell_signal 字段复用存 hold_reason 文本(前端 renderRow hold side 读 sell_signal 显示)
    all.push({
      etf_code: e.etf_code, name: e.name, score: e.score, side: "hold",
      hands: null, amt_pct: null,
      high_alert: e.high_alert, low_alert: e.low_alert,
      is_national_team: e.is_national_team, reason_summary: e.reason_summary,
      sell_signal: e.hold_reason || "持有观察", ohlc: e.ohlc || [],
      // 任务2/3: 决策依据明细 + 置信度 + 卖出动作(hold 也带, 弹窗统一渲染)
      dims: e.dims, adapt: e.adapt, dim_hits: e.dim_hits,
      data_thresholds: e.data_thresholds, history_analogy: e.history_analogy,
      confidence: e.confidence, sell_action: e.sell_action,
    });
  });
  _etfScoreState.all = all;
  _etfScoreState.filtered = all.slice();
  _etfScoreState.page = 1;
  _etfScoreState.pageSellHold = 1;
  _etfScoreState.search = "";
  _etfScoreState.holdingOnly = false; // 进入 tab 重置持仓筛选
  // 买入区展开状态从 localStorage 恢复(记忆用户偏好)
  _etfScoreState.buyExpanded = false;
  try { if (localStorage.getItem("etf_buy_expanded") === "1") _etfScoreState.buyExpanded = true; } catch (e) {}
  // 同类去重状态从 localStorage 恢复(记忆用户偏好, 默认关闭)
  _etfScoreState.dedup = false;
  try { if (localStorage.getItem("etf_dedup") === "1") _etfScoreState.dedup = true; } catch (e) {}
  // side 筛选从 localStorage 恢复(记忆用户偏好, 默认 all); 排序恢复(默认 score desc)
  _etfScoreState.sideFilter = "all";
  try {
    const savedSide = localStorage.getItem("etf_side_filter");
    if (savedSide && ["all", "buy", "sell", "hold"].indexOf(savedSide) >= 0) _etfScoreState.sideFilter = savedSide;
  } catch (e) {}
  _etfScoreState.sortKey = "score";
  _etfScoreState.sortDir = "desc";
  try {
    const savedSort = localStorage.getItem("etf_sort");
    if (savedSort) {
      const parts = savedSort.split("-");
      if (parts.length === 2 && ["score", "hands", "amt_pct", "high_alert", "low_alert"].indexOf(parts[0]) >= 0
          && (parts[1] === "asc" || parts[1] === "desc")) {
        _etfScoreState.sortKey = parts[0];
        _etfScoreState.sortDir = parts[1];
      }
    }
  } catch (e) {}

  _c.innerHTML = "";
  const m = _etfScoreState.meta;
  renderPurposeNote(_c, PURPOSE_NOTES["etf"]);
  // 持仓面板（可折叠输入区 + 持仓 chips 显示评分排名）
  const holdWrap = document.createElement("div");
  holdWrap.id = "etf-holdings-panel";
  _c.appendChild(holdWrap);
  _renderEtfHoldingsPanel();
  // 搜索栏 + side 筛选 chip + 排序下拉
  const bar = document.createElement("div");
  bar.className = "etf-score-bar";
  const holdN = _getEtfHoldings().length;
  // 统计各 side 数量(用于 chip 标签显示)
  const allN = _etfScoreState.all.length;
  const buyNChip = _etfScoreState.all.filter((e) => e.side === "buy").length;
  const sellNChip = _etfScoreState.all.filter((e) => e.side === "sell").length;
  const holdNChip = _etfScoreState.all.filter((e) => e.side === "hold").length;
  const sf = _etfScoreState.sideFilter;
  const sortVal = _etfScoreState.sortKey + "-" + _etfScoreState.sortDir;
  bar.innerHTML =
    '<input id="etf-score-search" type="search" placeholder="搜 ETF 代码或名称（如 515030 / 新能源车）" autocomplete="off" value="' + _esc(_etfScoreState.search) + '">'
    + '<div class="etf-side-chips" role="tablist" aria-label="ETF 分类筛选">'
    + '<button type="button" class="etf-side-chip' + (sf === "all" ? " active" : "") + '" data-side="all">全部 ' + allN + '</button>'
    + '<button type="button" class="etf-side-chip etf-chip-buy' + (sf === "buy" ? " active" : "") + '" data-side="buy">' + _t("etf_chip_buy") + ' ' + buyNChip + '</button>'
    + '<button type="button" class="etf-side-chip etf-chip-sell' + (sf === "sell" ? " active" : "") + '" data-side="sell">' + _t("etf_chip_sell") + ' ' + sellNChip + '</button>'
    + '<button type="button" class="etf-side-chip etf-chip-hold' + (sf === "hold" ? " active" : "") + '" data-side="hold">持有 ' + holdNChip + '</button>'
    + '</div>'
    + '<button id="etf-hold-filter" class="etf-hold-filter' + (_etfScoreState.holdingOnly ? ' active' : '') + '"' + (holdN === 0 ? ' disabled' : '') + '>只看持仓' + (holdN > 0 ? ' (' + holdN + ')' : '') + '</button>'
    + '<button id="etf-dedup-filter" class="etf-hold-filter' + (_etfScoreState.dedup ? ' active' : '') + '" title="同类' + _t("etf_chip_buy") + 'ETF（同行业/同指数）只保留评分最高的一只">同类去重</button>'
    + '<select id="etf-score-sort" class="etf-score-sort" title="排序方式" aria-label="排序方式">'
    + '<option value="score-desc"' + (sortVal === "score-desc" ? " selected" : "") + '>评分 高→低</option>'
    + '<option value="score-asc"' + (sortVal === "score-asc" ? " selected" : "") + '>评分 低→高</option>'
    + '<option value="hands-desc"' + (sortVal === "hands-desc" ? " selected" : "") + '>" + _t("etf_sort_hands") + "</option>'
    + '<option value="amt_pct-desc"' + (sortVal === "amt_pct-desc" ? " selected" : "") + '>成交额分位 高→低</option>'
    + '<option value="high_alert-desc"' + (sortVal === "high_alert-desc" ? " selected" : "") + '>高位预警 高→低</option>'
    + '<option value="low_alert-desc"' + (sortVal === "low_alert-desc" ? " selected" : "") + '>低位机会 高→低</option>'
    + '</select>'
    + '<span class="etf-score-updated">更新 ' + (m && m.updated_at ? _esc(m.updated_at.slice(0, 16)) : '-') + (m && m.full_market ? ' · 全市场' : ' · 代表性') + '</span>';
  _c.appendChild(bar);
  const input = bar.querySelector("#etf-score-search");
  let _searchTimer = null;
  input.oninput = () => {
    if (_searchTimer) clearTimeout(_searchTimer);
    _searchTimer = setTimeout(() => {
      _etfScoreState.search = input.value;
      _etfScoreState.page = 1;
      _etfScoreState.pageSellHold = 1;
      _applyEtfScoreFilter();
    }, 180); // 防抖
  };
  // side chip 切换
  bar.querySelectorAll(".etf-side-chip[data-side]").forEach((chip) => {
    chip.onclick = () => {
      const side = chip.dataset.side;
      if (!side || side === _etfScoreState.sideFilter) return;
      _etfScoreState.sideFilter = side;
      try { localStorage.setItem("etf_side_filter", side); } catch (e) {}
      bar.querySelectorAll(".etf-side-chip[data-side]").forEach((c) => {
        c.classList.toggle("active", c.dataset.side === side);
      });
      _etfScoreState.page = 1;
      _etfScoreState.pageSellHold = 1;
      _applyEtfScoreFilter();
    };
  });
  // 排序下拉
  const sortSel = bar.querySelector("#etf-score-sort");
  sortSel.onchange = () => {
    const v = sortSel.value || "score-desc";
    const parts = v.split("-");
    _etfScoreState.sortKey = parts[0] || "score";
    _etfScoreState.sortDir = parts[1] === "asc" ? "asc" : "desc";
    try { localStorage.setItem("etf_sort", _etfScoreState.sortKey + "-" + _etfScoreState.sortDir); } catch (e) {}
    _applyEtfScoreFilter();
  };
  // 只看持仓 切换
  const holdFilterBtn = bar.querySelector("#etf-hold-filter");
  holdFilterBtn.onclick = () => {
    if (holdFilterBtn.disabled) return;
    _etfScoreState.holdingOnly = !_etfScoreState.holdingOnly;
    holdFilterBtn.classList.toggle("active", _etfScoreState.holdingOnly);
    _etfScoreState.page = 1;
    _etfScoreState.pageSellHold = 1;
    _applyEtfScoreFilter();
  };
  // 同类去重 切换: 同行业/同指数买入ETF只保留评分最高一只
  const dedupBtn = bar.querySelector("#etf-dedup-filter");
  dedupBtn.onclick = () => {
    _etfScoreState.dedup = !_etfScoreState.dedup;
    dedupBtn.classList.toggle("active", _etfScoreState.dedup);
    try { localStorage.setItem("etf_dedup", _etfScoreState.dedup ? "1" : "0"); } catch (e) {}
    _etfScoreState.page = 1;
    _applyEtfScoreFilter();
  };
  // 列表容器
  const body = document.createElement("div");
  body.id = "etf-score-body";
  _c.appendChild(body);
  _renderEtfScoreBody();
}

// ============ 基金评分 1级 tab 二级分发器（场内ETF / 场外基金） ============
// ETF 是基金子类，"基金评分"作上位概念收纳：场内ETF（交易所交易）+ 场外基金（申赎型）。
// 复用 sentiment 二级 subtab 模式（_SENTIMENT_SUBTABS / _setTabHash / _initMainTabHashRestore）。
// 场内ETF=现有 renderEtfScore 内容整体收纳；场外基金=评分排行列表（Phase A Top100 + 排序/搜索/筛选）。
async function renderFund() {
  // gating 兜底：未登录 fund_score 特权 -> 回退 overview + 弹登录提示（防 F5 hash #fund/#fund/etf 绕过 tab 按钮拦截和 applyAuthState 隐藏）
  if (!hasPrivilege('fund_score')) {
    state.tab = "overview";
    document.querySelectorAll("button[data-tab]").forEach(function (x) { x.classList.remove("active"); });
    var ovBtn = document.querySelector('button[data-tab="overview"]');
    if (ovBtn) ovBtn.classList.add("active");
    openLoginPromptForFeature('基金评分', '基金评分为登录用户特权，登录后可查看 ETF/场外基金评分排行');
    renderTab();
    return;
  }
  content.innerHTML = "";
  // 二级 tab 栏（场内ETF/场外基金）
  const subtabBar = document.createElement("div");
  subtabBar.className = "subtab-bar";
  const subtabs = [
    ["etf", "场内ETF"],
    ["offshore", "场外基金"],
  ];
  subtabs.forEach(([key, label]) => {
    const btn = document.createElement("button");
    btn.textContent = label;
    btn.dataset.subtab = key;
    if (state.subtab === key) btn.classList.add("active");
    btn.onclick = () => {
      state.subtab = key;
      _setTabHash(state.tab); // 写 #fund/{subtab}，F5 刷新恢复二级 tab
      renderFund(); // 重新渲染基金评分 tab
    };
    subtabBar.appendChild(btn);
  });
  content.appendChild(subtabBar);

  // 子内容容器
  const subContent = document.createElement("div");
  subContent.className = "fund-sub-content";
  content.appendChild(subContent);
  renderLoadingState(subContent);

  // 根据 subtab 渲染对应内容
  await loadEcharts();   // P0-1: 子 render（renderEtfScore/renderOffshoreFund）用 mkCard+echarts，按需 await
  if (state.subtab === "offshore") await renderOffshoreFund(subContent);
  else await renderEtfScore(subContent); // 默认 场内ETF
}

// ============ 场外基金评分排行（Phase A：Top100 列表 + 排序/搜索/筛选） ============
// 数据源: R2 直链 https://ssd.fx8.store/fund_score/fund_score_top.json（83KB, Top100）
// CF fallback: ./data/fund_score_top.json（按 §8.1 优先 R2，CF 也 200 作兜底）
// 34 字段: fund_code/name/type/composite_score/star_rating + 6维度 + 5风险 + 经理6维 + 凯利 + 市场乘数 + final_suggestion
// 复用 ETF 评分成熟模式: _etfScoreState / _renderEtfScoreBody / _etfScoreTier / _etfScoreColor
// Phase A: 列表 + 排序/搜索/筛选; Phase B: 详情弹窗 5 区块; Phase C: 雷达图 + 实战筛选器
const FUND_SCORE_TOP_URL_R2 = "https://ssd.fx8.store/fund_score/fund_score_top.json";
const FUND_SCORE_TOP_URL_CF = "./data/fund_score_top.json";
const FUND_SCORE_PAGE_SIZE = 50;  // Top100 分 2 页（移动端单列浏览友好）

// tier: 基于 composite_score 分 5 档（参考 ETF 5 档但阈值不同; 基金评分分布偏中高, 阈值更严）
//   >=85 strong-buy(重点留意) / 75-85 buy(关注机会) / 65-75 hold(持有观察) / 50-65 sell(风险提示) / <50 strong-sell(重点规避)
const FUND_SCORE_TIER_LABEL = {
  "strong-sell": _t("etf_strong_sell"), "sell": _t("etf_sell"), "hold": _t("etf_hold"),
  "buy": _t("etf_buy"), "strong-buy": _t("etf_strong_buy")
};
// fundTypeFilter: "all" 或具体 fund_type 字符串（如下拉选择 "债券型-混合二级"）
// sortKey/sortDir: 排序键与方向，默认 composite_score 降序
const _fundScoreState = {
  all: [], filtered: [], page: 1, search: "",
  meta: null, fundTypeFilter: "all",
  sortKey: "composite_score", sortDir: "desc",
  loaded: false, loading: false, error: null
};

// 5档分档（基于 composite_score; 与 ETF _etfScoreTier 同模式但按基金评分分布调阈值）
function _fundScoreTier(e) {
  const s = e.composite_score == null ? -1 : e.composite_score;
  if (s >= 85) return "strong-buy";
  if (s >= 75) return "buy";
  if (s >= 65) return "hold";
  if (s >= 50) return "sell";
  return "strong-sell";
}
// 评分主色（与 ETF _etfScoreColor 同色板, light 主题; dark/redgold 由 CSS class 控制）
function _fundScoreColor(score) {
  const tier = _fundScoreTier({ composite_score: score });
  const map = {
    "strong-sell": "#3d5a6a", "sell": "#5a7a8a", "hold": "#b8860b",
    "buy": "#c08080", "strong-buy": "#7a3030"
  };
  return map[tier] || "var(--text-3,#86909c)";
}

function _fundScorePages() {
  return Math.max(1, Math.ceil(_fundScoreState.filtered.length / FUND_SCORE_PAGE_SIZE));
}

// 排序标签（中文，用于统计条副标题）
function _fundScoreSortLabel() {
  const map = {
    composite_score: _t("fund_score_composite_score"),
    half_kelly_position: _t("fund_score_half_kelly"),
    final_suggestion: _t("fund_score_final_suggestion"),
    sharpe: _t("fund_score_sharpe"),
    manager_score: _t("fund_score_manager_score"),
    star_rating: _t("fund_score_star"),
    score_drawdown: _t("fund_score_d3_drawdown"),
    score_stability: _t("fund_score_d4_stability")
  };
  return map[_fundScoreState.sortKey] || _t("fund_score_composite_score");
}

// 排序工具: 按 sortKey/sortDir 排序（返回新数组; null 值排末尾）
function _sortFundScoreList(arr) {
  const key = _fundScoreState.sortKey;
  const dir = _fundScoreState.sortDir === "asc" ? 1 : -1;
  return arr.slice().sort((a, b) => {
    const va = a[key], vb = b[key];
    if (va == null && vb == null) return 0;
    if (va == null) return 1;
    if (vb == null) return -1;
    return (va - vb) * dir;
  });
}

function _applyFundScoreFilter() {
  const s = _fundScoreState.search.trim().toLowerCase();
  let filtered = _fundScoreState.all.slice();
  if (s) {
    filtered = filtered.filter((e) =>
      String(e.fund_code).toLowerCase().includes(s) ||
      String(e.fund_name).toLowerCase().includes(s));
  }
  if (_fundScoreState.fundTypeFilter !== "all") {
    filtered = filtered.filter((e) => e.fund_type === _fundScoreState.fundTypeFilter);
  }
  filtered = _sortFundScoreList(filtered);
  _fundScoreState.filtered = filtered;
  const pages = _fundScorePages();
  if (_fundScoreState.page > pages) _fundScoreState.page = pages;
  if (_fundScoreState.page < 1) _fundScoreState.page = 1;
  _renderFundScoreBody();
}

// 渲染单行（rank/code/name/star/score + tierChip + typeTag + kellyTier + halfKelly + finalSuggestion + sharpe + manager）
function _renderFundScoreRow(e, rank) {
  const tier = _fundScoreTier(e);
  const col = _fundScoreColor(e.composite_score);
  const tierChip = '<span class="fund-tier-chip fund-tier-chip-' + tier + '">' + (FUND_SCORE_TIER_LABEL[tier] || '') + '</span>';
  // 星级（0-5）: JSON 中 star_rating 已是 1-5 整数, 兜底 round + clamp
  const star = e.star_rating == null ? 0 : Math.max(0, Math.min(5, Math.round(e.star_rating)));
  const stars = '★★★★★'.slice(0, star) + '☆☆☆☆☆'.slice(0, 5 - star);
  const starTag = star > 0 ? '<span class="fund-star" title="' + _t("fund_score_star") + '">' + stars + '</span>' : '';
  const typeTag = e.fund_type ? '<span class="fund-type-tag" title="' + _t("fund_score_fund_type") + '">' + _esc(e.fund_type) + '</span>' : '';
  const halfKelly = e.half_kelly_position != null
    ? '<span class="fund-kelly" title="' + _t("fund_score_half_kelly") + '">½凯利 ' + e.half_kelly_position.toFixed(1) + '%</span>' : '';
  const finalSug = e.final_suggestion != null
    ? '<span class="fund-final" title="' + _t("fund_score_final_suggestion") + '（含市场乘数 ' + (e.market_adjustment != null ? e.market_adjustment.toFixed(2) : '-') + '）">' + _t("fund_score_final_suggestion") + ' ' + e.final_suggestion.toFixed(1) + '%</span>' : '';
  const kellyTier = e.kelly_tier ? '<span class="fund-kelly-tier" title="凯利档位">' + _esc(e.kelly_tier) + '</span>' : '';
  const sharpeTag = e.sharpe != null
    ? '<span class="fund-sharpe" title="' + _t("fund_score_sharpe") + '">' + _t("fund_score_sharpe") + ' ' + e.sharpe.toFixed(2) + '</span>' : '';
  const mgrTag = e.manager_score != null
    ? '<span class="fund-mgr" title="' + _t("fund_score_manager_score") + '">' + _t("fund_score_manager_score") + ' ' + e.manager_score.toFixed(0) + '</span>' : '';
  return '<div class="fund-score-row fund-tier-' + tier + '">'
    + '<div class="fund-row-main">'
    + '<span class="fund-rank">#' + rank + '</span>'
    + '<span class="fund-code">' + _esc(e.fund_code) + '</span>'
    + '<span class="fund-name">' + _esc(e.fund_name) + starTag + '</span>'
    + '<span class="fund-score fund-tier-score-' + tier + '" style="color:' + col + '">' + (e.composite_score != null ? e.composite_score.toFixed(2) : '-') + '</span>'
    + '</div>'
    + '<div class="fund-row-sub">'
    + tierChip
    + typeTag
    + kellyTier
    + halfKelly
    + finalSug
    + sharpeTag
    + mgrTag
    + '</div>'
    + '</div>';
}

// 分页器 HTML（与 ETF _renderEtfPager 同模式，class 前缀改 fund-）
function _renderFundScorePager(page, pages, total) {
  let html = '<div class="fund-score-pager">';
  html += '<button class="fund-page-btn" data-page="' + (page > 1 ? page - 1 : 1) + '"' + (page <= 1 ? ' disabled' : '') + '>上一页</button>';
  const pageBtns = [];
  const addPage = (p) => { if (pageBtns.indexOf(p) < 0) pageBtns.push(p); };
  addPage(1); addPage(pages);
  for (let p = page - 2; p <= page + 2; p++) {
    if (p > 1 && p < pages) addPage(p);
  }
  pageBtns.sort((a, b) => a - b);
  let prev = 0;
  pageBtns.forEach((p) => {
    if (p - prev > 1) html += '<span class="fund-page-ellipsis">…</span>';
    html += '<button class="fund-page-btn' + (p === page ? " active" : "") + '" data-page="' + p + '">' + p + '</button>';
    prev = p;
  });
  html += '<button class="fund-page-btn" data-page="' + (page < pages ? page + 1 : pages) + '"' + (page >= pages ? ' disabled' : '') + '>下一页</button>';
  html += '<span class="fund-page-info">' + total + ' ' + _t("fund_score_count_unit") + '</span>';
  html += '</div>';
  return html;
}

function _renderFundScoreBody() {
  const body = document.getElementById("fund-score-body");
  if (!body) return;
  const st = _fundScoreState;
  const filtered = st.filtered;

  // 统计条
  let html = '<div class="fund-score-stat">共 ' + st.all.length + ' ' + _t("fund_score_count_unit")
    + (st.meta && st.meta.count ? '（Top ' + st.meta.count + '）' : '')
    + (st.search || st.fundTypeFilter !== "all" ? ' · 筛选命中 ' + filtered.length : '')
    + ' · 按' + _fundScoreSortLabel() + _t("fund_score_sort_dir_suffix")
    + (st.meta && st.meta.date ? ' · ' + _t("fund_score_data_label") + ' ' + _esc(st.meta.date) : '')
    + '</div>';

  if (filtered.length === 0) {
    html += '<div class="fund-score-empty">' + _t("fund_score_empty") + '</div>';
    body.innerHTML = html;
    return;
  }

  // 单区列表（Top100, 50/页分页）
  const pages = _fundScorePages();
  if (st.page > pages) st.page = pages;
  const start = (st.page - 1) * FUND_SCORE_PAGE_SIZE;
  const slice = filtered.slice(start, start + FUND_SCORE_PAGE_SIZE);
  html += '<div class="fund-score-list">';
  slice.forEach((e, i) => { html += _renderFundScoreRow(e, start + i + 1); });
  html += '</div>';
  if (pages > 1) html += _renderFundScorePager(st.page, pages, filtered.length);
  body.innerHTML = html;

  // 绑定分页按钮
  body.querySelectorAll(".fund-page-btn[data-page]").forEach((b) => {
    b.onclick = () => {
      if (b.disabled) return;
      _fundScoreState.page = parseInt(b.dataset.page, 10) || 1;
      _renderFundScoreBody();
      const top = body.getBoundingClientRect().top + window.scrollY - 80;
      window.scrollTo({ top: Math.max(0, top), behavior: "smooth" });
    };
  });
}

// 场外基金评分排行（Phase A：Top100 列表 + 排序/搜索/筛选）
// 数据源: R2 直链 https://ssd.fx8.store/fund_score/fund_score_top.json (Top100, 83KB)
// 失败 fallback: ./data/fund_score_top.json (CF Static Assets)
// 复用 ETF 评分成熟模式（_etfScoreState / _renderEtfScoreBody），平行实现 _fundScoreState
async function renderOffshoreFund(container) {
  const _c = container || content;
  _c.innerHTML = "";
  renderPurposeNote(_c, PURPOSE_NOTES["offshore"]);

  // 加载状态
  const loadingEl = document.createElement("div");
  loadingEl.className = "loading loading--active";
  loadingEl.innerHTML = '<span class="loading__spinner"></span><span class="loading__text">' + _t("fund_score_loading") + '</span>';
  _c.appendChild(loadingEl);

  // fetchJSON R2 直链，失败 fallback CF（§8.1 优先 R2；CF 实测 200 作兜底）
  let r = null;
  let err = null;
  try {
    r = await fetchJSON(FUND_SCORE_TOP_URL_R2);
  } catch (e1) {
    try {
      r = await fetchJSON(FUND_SCORE_TOP_URL_CF);
    } catch (e2) {
      err = (e2 && e2.message) ? e2.message : String(e2);
    }
  }
  if (loadingEl.parentNode) loadingEl.parentNode.removeChild(loadingEl);

  if (!r || !r.data) {
    const fail = document.createElement("div");
    fail.className = "fund-score-empty";
    fail.textContent = _t("fund_score_load_failed") + (err ? '：' + err : '');
    _c.appendChild(fail);
    return;
  }

  // 数据填充到 state
  const all = (r.data || []).slice();
  _fundScoreState.all = all;
  _fundScoreState.filtered = all.slice();
  _fundScoreState.meta = {
    date: r.date,
    count: r.count,
    method: r.method,
    update_date: all[0] && all[0].update_date
  };
  _fundScoreState.page = 1;
  _fundScoreState.search = "";
  _fundScoreState.fundTypeFilter = "all";
  _fundScoreState.sortKey = "composite_score";
  _fundScoreState.sortDir = "desc";
  _fundScoreState.loaded = true;
  _fundScoreState.loading = false;
  _fundScoreState.error = null;

  // 从 localStorage 恢复排序偏好
  try {
    const savedSort = localStorage.getItem("fund_score_sort");
    if (savedSort) {
      const parts = savedSort.split("-");
      const validKeys = ["composite_score", "half_kelly_position", "final_suggestion", "sharpe", "manager_score", "star_rating", "score_drawdown", "score_stability"];
      if (parts.length === 2 && validKeys.indexOf(parts[0]) >= 0 && (parts[1] === "asc" || parts[1] === "desc")) {
        _fundScoreState.sortKey = parts[0];
        _fundScoreState.sortDir = parts[1];
      }
    }
  } catch (e) {}

  // 工具栏：搜索 + 类型筛选 + 排序
  const bar = document.createElement("div");
  bar.className = "fund-score-bar";
  // 构造 fund_type 下拉选项（按出现次数降序，动态生成以兼容新类型）
  const typeCounts = Object.create(null);
  all.forEach((e) => {
    const t = e.fund_type || "";
    if (!t) return;
    typeCounts[t] = (typeCounts[t] || 0) + 1;
  });
  const types = Object.keys(typeCounts).sort((a, b) => typeCounts[b] - typeCounts[a]);
  const sortVal = _fundScoreState.sortKey + "-" + _fundScoreState.sortDir;
  bar.innerHTML =
    '<input id="fund-score-search" type="search" placeholder="' + _esc(_t("fund_score_search_placeholder")) + '" autocomplete="off" value="' + _esc(_fundScoreState.search) + '">'
    + '<select id="fund-score-type" class="fund-score-select" title="' + _esc(_t("fund_score_fund_type")) + '" aria-label="' + _esc(_t("fund_score_fund_type")) + '">'
    + '<option value="all">' + _t("fund_score_all_types") + ' ' + all.length + '</option>'
    + types.map((t) => '<option value="' + _esc(t) + '"' + (_fundScoreState.fundTypeFilter === t ? " selected" : "") + '>' + _esc(t) + ' (' + typeCounts[t] + ')</option>').join("")
    + '</select>'
    + '<select id="fund-score-sort" class="fund-score-select" title="' + _esc(_t("fund_score_sort_label_title")) + '" aria-label="' + _esc(_t("fund_score_sort_label_title")) + '">'
    + '<option value="composite_score-desc"' + (sortVal === "composite_score-desc" ? " selected" : "") + '>' + _t("fund_score_sort_composite") + '</option>'
    + '<option value="composite_score-asc"' + (sortVal === "composite_score-asc" ? " selected" : "") + '>' + _t("fund_score_sort_composite_asc") + '</option>'
    + '<option value="half_kelly_position-desc"' + (sortVal === "half_kelly_position-desc" ? " selected" : "") + '>' + _t("fund_score_sort_half_kelly") + '</option>'
    + '<option value="final_suggestion-desc"' + (sortVal === "final_suggestion-desc" ? " selected" : "") + '>' + _t("fund_score_sort_final_suggestion") + '</option>'
    + '<option value="sharpe-desc"' + (sortVal === "sharpe-desc" ? " selected" : "") + '>' + _t("fund_score_sort_sharpe") + '</option>'
    + '<option value="manager_score-desc"' + (sortVal === "manager_score-desc" ? " selected" : "") + '>' + _t("fund_score_sort_manager_score") + '</option>'
    + '<option value="star_rating-desc"' + (sortVal === "star_rating-desc" ? " selected" : "") + '>' + _t("fund_score_sort_star") + '</option>'
    + '<option value="score_drawdown-desc"' + (sortVal === "score_drawdown-desc" ? " selected" : "") + '>' + _t("fund_score_sort_drawdown") + '</option>'
    + '<option value="score_stability-desc"' + (sortVal === "score_stability-desc" ? " selected" : "") + '>' + _t("fund_score_sort_stability") + '</option>'
    + '</select>'
    + '<span class="fund-score-updated">' + _t("fund_score_data_label") + ' ' + _esc(r.date || '-') + (r.method ? ' · ' + _esc(r.method) : '') + '</span>';
  _c.appendChild(bar);

  // 搜索（防抖）
  const input = bar.querySelector("#fund-score-search");
  let _searchTimer = null;
  input.oninput = () => {
    if (_searchTimer) clearTimeout(_searchTimer);
    _searchTimer = setTimeout(() => {
      _fundScoreState.search = input.value;
      _fundScoreState.page = 1;
      _applyFundScoreFilter();
    }, 180);
  };
  // 类型筛选
  const typeSel = bar.querySelector("#fund-score-type");
  typeSel.onchange = () => {
    _fundScoreState.fundTypeFilter = typeSel.value || "all";
    _fundScoreState.page = 1;
    _applyFundScoreFilter();
  };
  // 排序
  const sortSel = bar.querySelector("#fund-score-sort");
  sortSel.onchange = () => {
    const v = sortSel.value || "composite_score-desc";
    const parts = v.split("-");
    _fundScoreState.sortKey = parts[0] || "composite_score";
    _fundScoreState.sortDir = parts[1] === "asc" ? "asc" : "desc";
    try { localStorage.setItem("fund_score_sort", _fundScoreState.sortKey + "-" + _fundScoreState.sortDir); } catch (e) {}
    _fundScoreState.page = 1;
    _applyFundScoreFilter();
  };

  // 列表容器
  const body = document.createElement("div");
  body.id = "fund-score-body";
  _c.appendChild(body);
  _applyFundScoreFilter();
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
      _etfScoreState.pageSellHold = 1;
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
      _etfScoreState.pageSellHold = 1;
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
      _etfScoreState.pageSellHold = 1;
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
// 测量顶部 tab 栏实际高度写入 CSS 变量 --tab-h（兜底 41px）;同时量二级 subtab-bar 高度写 --subtab-h（兜底 46px，供大盘 tab 指数目录 anchorBar sticky top 叠加用）。
function initStickyOffset() {
  const tabs = document.querySelector('.tabs');
  if (!tabs) return;
  const set = () => {
    document.documentElement.style.setProperty('--tab-h', tabs.offsetHeight + 'px');
    const subtabBar = document.querySelector('.subtab-bar');
    if (subtabBar) document.documentElement.style.setProperty('--subtab-h', subtabBar.offsetHeight + 'px');
  };
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
const _H5_TAB_NAMES = { overview: "📊 市场全景", market: "📈 指数表现", sentiment: "😊 盘面温测", fund: "💹 基金评分", lab: "🧪 策略实验" };

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
// trade_sim etf_code -> ETF 名称映射（fallback 兜底表；2026-07-28 统一后 sd.etf_name 优先，旧 JSON 无 etf_name 时用此表）
// 用于回测详情 modal infoBar 显示"回测标的: ETF 代码（名称）"; 覆盖宽基/港股首位 ETF 代码。
// 注：sh 510050=上证50ETF 近似替代上证指数(approx=true)；sz 159943=深证成指ETF 精准跟踪深成指(approx=false)。
// 行业 sw_xxx 等首位 ETF 由 sd.etf_name 提供（board_etf_map 候选 name），不在此硬编码。
var _TRADE_SIM_ETF_NAMES = {
  '510050': '上证50ETF', '510300': '沪深300ETF', '510500': '中证500ETF', '512100': '中证1000ETF',
  '159915': '创业板ETF', '159943': '深证成指ETF', '588000': '科创50ETF',
  '513900': 'H股ETF', '513600': '恒生ETF', '513130': '恒生科技ETF'
};

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

// 2026-07-30 过拟合度分级颜色: sharpe>3 红(可疑过拟合红线) / 2-3 橙(中等警示) / 1-2 默认(正常) / <1 灰(弱)
// 与 _tradeSimColorPct 同风格: 数据语义色硬编码(红橙警示色不随皮肤变), 正常/弱用 var(--text-1/3) 随皮肤协调
// 红线阈值与 _SHARPE_REDLINE_THRESHOLD(3.0) 一致; 橙色 #d97706 介于红 #c0392b 与 WF失效 #ad6800 之间, 警示层级清晰
// Bailey 2014: 夏普>3 可疑过拟合 / >5 必过拟合; trade_sim 夏普为事件稀疏 sqrt(252) 年化近似值偏高, 分级为提示非判定
function _tradeSimSharpeColor(sharpe) {
  if (typeof sharpe !== 'number' || !isFinite(sharpe)) return 'var(--text-3)';  // 无数据/非数: 灰
  if (sharpe > _SHARPE_REDLINE_THRESHOLD) return '#c0392b';   // 红: 可疑过拟合(>3)
  if (sharpe >= 2) return '#d97706';                           // 橙: 中等警示(2-3)
  if (sharpe >= 1) return 'var(--text-1)';                     // 默认: 正常(1-2)
  return 'var(--text-3)';                                      // 灰: 弱(<1或负)
}

// 2026-07-30 夏普分级后缀符号: >3 ⚠>3(红线警示) / 2-3 ~2-3(中等提示) / 其他空
// 与 _tradeSimSharpeColor 配合, modal sim-card 夏普比率卡显示数值+后缀, 一眼区分过拟合度级别
function _tradeSimSharpeSuffix(sharpe) {
  if (typeof sharpe !== 'number' || !isFinite(sharpe)) return '';
  if (sharpe > _SHARPE_REDLINE_THRESHOLD) return ' ⚠>3';
  if (sharpe >= 2) return ' ~2-3';
  return '';
}

function _tradeSimFmtNum(n) {
  if (n === null || n === undefined || n === Infinity) return "-";
  return Number(n).toLocaleString('zh-CN', { maximumFractionDigits: 2 });
}

async function _tradeSimFetchStats(indexId) {
  // R2 托管：trade_sim_data/ 前缀避开 trade_sim/ HTML；fetchJSON 统一走 .json + CF br 压缩（2026-08-01 全跳 .gz）
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
      if (idx) result = { name: (_INDEX_NAME_MAP[indexId] || idx.name), data: (idx.data || []).map(function (d) { return { date: d.date, close: d.close }; }) };
    } else if (_SHAPE_HK.has(indexId)) {
      _hkAllCache = _hkAllCache || await fetchJSON(dataUrl("hk-all.json"));
      var hidx = _hkAllCache.indices && _hkAllCache.indices[indexId];
      if (hidx) result = { name: (_INDEX_NAME_MAP[indexId] || hidx.name), data: (hidx.data || []).map(function (d) { return { date: d.date, close: d.close }; }) };
    } else if (_SHAPE_US_EU.has(indexId)) {
      _globalAllCache = _globalAllCache || await fetchJSON(dataUrl("global-all.json"));
      var gidx = _globalAllCache.indices && _globalAllCache.indices[indexId];
      if (gidx) result = { name: (_INDEX_NAME_MAP[indexId] || gidx.name), data: (gidx.data || []).map(function (d) { return { date: d.date, close: d.close }; }) };
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
  var idxName = (_INDEX_NAME_MAP[indexId] || series.name || indexId);
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
function _tradeSimCardsHTML(s, initCap, etfCode) {
  var ddStr = s.max_drawdown.toFixed(1) + '%';
  var ddDate = s.max_drawdown_date || 'N/A';
  var totalOps = s.buy_count + s.sell_count;
  var skippedTotal = s.skipped_full + s.skipped_no_cash + s.skipped_no_position;
  var signalTotal = totalOps + skippedTotal;
  // 2026-07-20 总资产卡片副标题加 ETF 代码标注（ETF 替代 vs 纯指数模拟）
  var _assetSub = etfCode ? ' · ETF ' + etfCode : ' · 纯指数模拟';
  return '<div class="sim-flow">' + _t.tsText(s.flow_desc) + '</div>' +
    '<div class="sim-cards">' +
    '<div class="sim-card"><span class="k">总资产变化</span><span class="v">' + _tradeSimFmtNum(s.total_capital) + ' -> ' + _tradeSimFmtNum(s.final_total) + ' 元<div class="sub" style="font-size:11px;color:var(--text-3);">期末持仓 ' + _tradeSimFmtNum(s.final_holdings) + ' 元' + _assetSub + '</div></span></div>' +
    '<div class="sim-card"><span class="k">最大持仓</span><span class="v">' + _tradeSimFmtNum(s.max_holding) + ' 元（' + s.max_holding_pct + '%）<div class="sub">' + s.max_holding_date + '</div></span></div>' +
    '<div class="sim-card"><span class="k">总收益</span><span class="v" style="color:' + _tradeSimColorPct(s.total_return) + '">' + _tradeSimFmtNum(s.total_return) + ' 元（' + (s.total_return_pct >= 0 ? '+' : '') + s.total_return_pct.toFixed(2) + '%）</span></div>' +
    '<div class="sim-card"><span class="k" title="' + _t('trade_sim_cagr_title') + '">年化收益率</span><span class="v" style="color:' + _tradeSimColorPct(s.annualized) + '">' + (s.annualized >= 0 ? '+' : '') + s.annualized.toFixed(1) + '%<div class="sub">' + _t('trade_sim_first_buy') + ' ' + s.years + ' ' + _t('trade_sim_years_unit') + '</div></span></div>' +
    '<div class="sim-card"><span class="k" title="年化夏普(无风险0)=净值曲线相邻点收益率 mean/std × √252。事件稀疏序列近似年化值(与 lab 同口径),值偏高。>3 可疑过拟合(Bailey(2014)学术红线)。颜色分级: >3红(可疑过拟合)/2-3橙(中等警示)/1-2默认(正常)/<1灰(弱)">夏普比率</span><span class="v" style="color:' + _tradeSimSharpeColor(s.sharpe) + '">' + (typeof s.sharpe === 'number' ? s.sharpe.toFixed(2) : '-') + _tradeSimSharpeSuffix(s.sharpe) + '<div class="sub">事件稀疏 √252 年化 · 分级&gt;3红/2-3橙/&lt;1灰</div></span></div>' +
    '<div class="sim-card"><span class="k">总资产峰值</span><span class="v">' + _tradeSimFmtNum(s.total_assets_peak) + ' 元<div class="sub">' + s.total_assets_peak_date + '</div></span></div>' +
    '<div class="sim-card"><span class="k" title="历史从最高点到最低点的最大跌幅。衡量最坏情况下的亏损幅度。">最大回撤</span><span class="v" style="color:' + _tradeSimColorPct(-s.max_drawdown) + '">' + ddStr + '<div class="sub">' + ddDate + '</div></span></div>' +
    '<div class="sim-card"><span class="k">回撤中位数 / 回撤去极均值</span><span class="v" style="color:' + _tradeSimColorPct(-s.median_drawdown) + '">' + s.median_drawdown.toFixed(1) + '% / ' + s.trimmed_mean_drawdown.toFixed(1) + '%</span></div>' +
    '<div class="sim-card"><span class="k">总操作</span><span class="v">' + s.buy_count + _t('trade_sim_ops_buy') + '/' + s.sell_count + _t('trade_sim_ops_sell') + '（' + totalOps + '次）<div class="sub">共 ' + signalTotal + ' 次信号 · <span title="' + _t('trade_sim_skip_tooltip') + '">跳过 ' + skippedTotal + ' 次</span> · <span title="同时持有的最大未平仓笔数">峰值并发 ' + s.max_positions_ever + ' 笔</span></div></span></div>' +
    '<div class="sim-card"><span class="k" title="盈利交易笔数÷总交易笔数。越高=胜出的交易占比越大。">胜率</span><span class="v">' + s.win_rate + '%（' + s.win_count + '胜/' + s.lose_count + '负）</span></div>' +
    '<div class="sim-card"><span class="k">最长连胜/连败</span><span class="v">' + s.max_win_streak + ' 轮 / ' + s.max_lose_streak + ' 轮</span></div>' +
    '<div class="sim-card"><span class="k" title="平均每笔盈利÷平均每笔亏损。>1=赚的时候比亏的时候赚得多。">平均盈亏比</span><span class="v">' + _tradeSimFmtNum(s.avg_pl_ratio) + '（均盈' + _tradeSimFmtNum(s.avg_win_pct) + '% / 均亏' + _tradeSimFmtNum(s.avg_loss_pct) + '%）</span></div>' +
    '<div class="sim-card"><span class="k">配对情况</span><span class="v">' + s.total_rounds + '笔成对 · ' + s.open_count + '笔未平仓</span></div>' +
    '</div>';
}

// 交易记录清单表（11列，照搬 _scenario_panel 的 ledger 表）
function _tradeSimLedgerHTML(ledger, indexName, etfCode) {
  if (!ledger || !ledger.length) return '<div style="padding:12px;color:var(--text-3)">无交易记录</div>';
  // 2026-07-20 加 ETF 代码标注：ETF 替代品种表头/提示用 "ETF 代码", 纯指数保留 indexName
  var _priceColName = etfCode ? ('ETF ' + etfCode) : indexName;
  var rows = ledger.map(function (entry, j) {
    var opClass = entry.op.indexOf('止损') >= 0 ? 'sell_stop_loss'
      : entry.op.indexOf('卖') >= 0 ? 'sell'
      : entry.op.indexOf('追买') >= 0 ? 'buy_special'
      : entry.op.indexOf('备买') >= 0 ? 'buy_backup'
      : entry.op.indexOf('辅买') >= 0 ? 'buy_aux' : 'buy';
    var opBadge = '<span class="ledger-op ' + opClass + '">' + _t.tsText(entry.op) + '</span>';
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
  return '<h3 style="margin:20px 0 2px;font-size:15px;">📒 交易记录清单' + (etfCode ? ' · ETF ' + etfCode : '') + '（' + ledger.length + ' 笔，按时间轴）</h3>' +
    '<p style="margin:0 0 8px;font-size:11px;color:var(--text-3)">' + _t('trade_sim_buy_hint_prefix') + _priceColName + _t('trade_sim_buy_hint_suffix') + '</p>' +
    '<div class="sim-table-wrap"><table><thead><tr>' +
    '<th>#</th><th>日期</th><th>' + _priceColName + '收盘</th><th>较上条涨跌</th><th>操作</th><th>交易金额</th><th>份额变动</th><th>持仓份额</th><th>持仓市值</th><th>当前总资产</th><th>累计收益率</th>' +
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
    '<div class="sim-table-wrap"><table><thead><tr><th>#</th><th>' + _t('trade_sim_buy_date') + '</th><th>' + _t('trade_sim_buy_price') + '</th><th>份额</th><th>浮动盈亏%</th><th>当前市值</th><th>浮动盈亏</th></tr></thead><tbody>' + rows + '</tbody></table></div>';
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
    '<th>#</th><th>' + _t('trade_sim_buy_date') + '</th><th>' + _t('trade_sim_buy_price') + '</th><th>' + _t('trade_sim_sell_date') + '</th><th>' + _t('trade_sim_sell_price') + '</th><th>持有时长</th><th>盈亏%</th><th>投入</th><th>回收</th><th>净利润</th>' +
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
  { key: 'annualized', label: '年化', type: 'num', defaultDir: 'desc', title: _t('trade_sim_cagr_title') },
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
      '<td>' + _t.tsText(r.path) + '</td>' +
      '<td>' + _t.tsText(r.sig) + '</td>' +
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
function _tradeSimPanelHTML(winData, fullNode, indexName, initCap, gradId, etfCode) {
  var s = winData.summary;
  var cards = _tradeSimCardsHTML(s, initCap, etfCode);
  var equitySvg = '<h3 style="margin:20px 0 2px;font-size:15px;">📈 资产变化曲线</h3>' +
    '<p style="margin:0 0 4px;font-size:11px;color:var(--text-3)">虚线 = 初始资金 ' + _tradeSimFmtNum(initCap) + ' 元 · 蓝色 = 期末 · 红色 = 峰值 · 绿色 = 最低</p>' +
    _tradeSimEquitySVG(winData.equity_curve, initCap, gradId);
  // 交易记录/回合表/未平仓 从 full.json 懒加载
  var detailHTML;
  if (fullNode) {
    detailHTML = _tradeSimLedgerHTML(fullNode.ledger, indexName, etfCode) +
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
  // 2026-07-20 infoBar: 回测标的 + 费率明细（modal 详情明确标注 ETF 代码/名称 + 完整费率, 区分 ETF 替代 vs 纯指数）
  // 2026-07-28 统一：sd.etf_name/etf_approx 由 simulate_trade.py 从 board_etf_map 首位写入；
  // _etfName 优先 sd.etf_name，fallback _TRADE_SIM_ETF_NAMES 硬编码（旧 JSON 无 etf_name 时兜底）；
  // _isApprox 用 sd.etf_approx（不再硬编码 index_id==='sh'，任何首位 approx=true 都标注"近似替代"）
  var etfCode = sd.etf_code;
  var _etfName = etfCode ? (sd.etf_name || _TRADE_SIM_ETF_NAMES[etfCode]) : null;
  var _isApprox = !!(etfCode && sd.etf_approx);
  var _commRate = sd.commission_rate != null ? ('佣金万' + (sd.commission_rate * 10000).toFixed(1).replace(/\.0$/, '')) : '佣金万3';
  var _slipRate = sd.slippage != null ? ('滑点千' + (sd.slippage * 1000).toFixed(1).replace(/\.0$/, '')) : '滑点千1';
  var _transferFee = sd.transfer_fee_rate_sh != null ? ('沪市过户费万' + (sd.transfer_fee_rate_sh * 10000).toFixed(1).replace(/\.0$/, '')) : '沪市过户费万0.1';
  var _minComm = sd.min_commission != null ? ('最低' + sd.min_commission + '元/笔') : '最低5元/笔';
  var _targetText = etfCode
    ? '回测标的: ETF ' + etfCode + '（' + (_etfName || 'ETF') + (_isApprox ? ', 近似替代' + indexName : '') + '）· 信号在指数生成, 成交在 ETF'
    : '回测标的: ' + indexName + '（纯指数模拟, 无 ETF 替代）';
  var _feeText = etfCode
    ? '费率: ' + _commRate + ' + ' + _slipRate + ' + ' + _transferFee + '（' + _minComm + '）'
    : '费率: ' + _commRate + ' + ' + _slipRate + '（纯指数模拟, 无过户费）';
  var infoBar = '<div class="sim-info-bar">' + _targetText + ' ｜ ' + _feeText + '</div>';
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
    return '<button class="sim-main-tab' + (i === pathIdx ? ' active' : '') + '" data-path="' + i + '">' + _t.tsText(p) + '</button>';
  }).join('') + '</div>';
  var subTabs = '<div class="sim-sub-tabs">' + sd.scenarios.map(function (s, i) {
    return '<button class="sim-sub-tab' + (i === scenIdx ? ' active' : '') + '" data-sig="' + i + '">' + _t.tsText(s) + '</button>';
  }).join('') + '</div>';
  var gradId = 'tradeSimGrad_' + win + '_' + pathIdx + '_' + scenIdx;
  var panel = _tradeSimPanelHTML(winData, fullNode, indexName, initCap, gradId, etfCode);
  body.innerHTML = viewTabs + infoBar + winBar + cmpTable + mainTabs + '<div class="sim-path-group active">' + subTabs + panel + '</div>';
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
    // 防御加固：灰色 disabled 按钮不响应点击（即使动态清单漏了某指数，灰按钮也不会误弹窗）
    if (a.classList.contains('sim-btn-disabled')) return;
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

// 方案A(2026-07-28): intraday_snapshot.json 缓存（2 分钟 TTL），避免每次点弹窗都请求。
// 盘中实时价用于补 T 日预估点（chartData 末日<T日 时兜底）。
const _SNAP_TTL = 2 * 60 * 1000;
let _snapCache = { data: null, ts: 0 };
async function _getCachedSnapshot() {
  const now = Date.now();
  if (_snapCache.data && (now - _snapCache.ts) < _SNAP_TTL) return _snapCache.data;
  try {
    const r = await fetchJSON("./data/intraday_snapshot.json");
    _snapCache = { data: r, ts: now };
    return r;
  } catch (e) { return null; }
}
// indexId(短式如 sh/sz/hs300) -> intraday_snapshot.indices[].code(腾讯全码如 sh000001) 反查表。
// 与 intraday_snapshot.py 的 _SNAPSHOT_TO_INDEX_ID 同步（17 基础指数）。
const _SNAPSHOT_IID_TO_CODE = {
  sh: "sh000001", sz: "sz399001", hs300: "sh000300", sz50: "sh000016",
  csi500: "sh000905", csi1000: "sh000852", cyb: "sz399006", kc50: "sh000688",
  bj50: "bj899050", hsi: "hkHSI", hstech: "hkHSTECH", hscei: "hkHSCEI",
  cgb_idx: "sh000012", cgb_10y_etf: "sh511260", hk_hsmbi: "hkHSMBI",
  hk_hsmogi: "hkHSMOGI", hk_cshkdiv: "hkCSHKDIV",
};
// 方案A: chartData 末日<T日时，从 intraday_snapshot.json 读实时价补 T 日预估点。
// 补点格式：index 图补 {date,open,high,low,close,pct_change,amount}；value 图补 {date,value}。
// 同时追加 signal="estimate" 的 pin 标注（灰色"预估"pin，视觉区分非真实信号）。
// 返回 true=已补点，false=无法补（indexId 不在快照/无实时价/快照拉取失败）。
// P0-1(2026-07-28): 新增可选第6参 todayValueOverride——KPI 弹窗场景由调用方
// （_appendKpiEstimate 适配层）从 overview.today 查到 T 日值后直接传入，跳过 snapshot
// 反查（KPI 用 score_id/kpiId 非 index_id，不在 _SNAPSHOT_IID_TO_CODE 17 基础指数内）。
// 不传或传 null/undefined 时走原 snapshot 路径（信号弹窗向后兼容）。
async function _appendIntradayEstimate(chartData, sigs, indexId, todayDate, isValue, todayValueOverride) {
  if (!chartData || !chartData.length || !todayDate) return false;
  if (chartData[chartData.length - 1].date >= todayDate) return false; // 末日已==T日，无需补
  let idx;
  if (todayValueOverride != null) {
    // KPI 场景：调用方已查好 T 日值（overview.today），无需 snapshot 反查
    idx = { price: todayValueOverride };
  } else {
    // 信号弹窗场景：从 intraday_snapshot 反查腾讯全码
    const code = _SNAPSHOT_IID_TO_CODE[indexId];
    if (!code) return false; // 不在 17 基础指数，无实时价来源
    const snap = await _getCachedSnapshot();
    if (!snap || !snap.indices) return false;
    idx = snap.indices.find(it => it.code === code);
    if (!idx || idx.price == null) return false;
  }
  // 补 T 日点到 chartData 末尾
  if (isValue) {
    chartData.push({ date: todayDate, value: idx.price });
  } else {
    // ohlc 格式：open/high/low 用盘中实际值，close 用最新价
    chartData.push({
      date: todayDate,
      open: idx.open != null ? idx.open : idx.price,
      high: idx.high != null ? idx.high : idx.price,
      low: idx.low != null ? idx.low : idx.price,
      close: idx.price,
      pct_change: idx.pct_change != null ? idx.pct_change : 0,
      amount: idx.amount != null ? idx.amount : null,
    });
  }
  // 追加"预估"pin 标注（signalLabel/signalColor 已加 estimate 分支：灰色"预估"）
  // KPI 场景 sigs 传 null 时跳过（KPI 走势图不用信号 pin，由 openKpiDetailModal 加 markPoint）
  if (sigs) {
    sigs.push({ date: todayDate, index_id: indexId, signal: "estimate", reason: "盘中预估(" + idx.price + ")" });
  }
  return true;
}

// P0-1(2026-07-28): KPI 走势弹窗专用预估点适配层。
// KPI 数据源=overview.today（9 sentiment scores + 20 astock/global/volume_ratio metrics），
// 非 intraday_snapshot.indices（仅 17 基础指数，KPI 用 kpiId/score_id 无法反查腾讯码）。
// 仅对 overview.today 中 date===T日 的 KPI 补点（T+1 源 gold/cn10y/a_qvix_300/
// a_fund_margin/lhb_count/a_turnover_*/a_width_fengban_rate 等无 T 日值，不硬凑）。
// 多 series KPI（涨跌家数/涨跌停数）通过 _KPI_COMPANION 映射 companion kpiId 同步补。
// 百分比 KPI（seal_rate/fengban_rate）chartData 存 *100 值，overview 存 0-1 小数，需 *100 对齐。
// 返回 estimates 数组（{seriesIdx,date,value}），供 openKpiDetailModal 渲染灰色"预估"markPoint。
const _KPI_COMPANION = {
  a_width_up_count: "a_width_down_count", a_width_down_count: "a_width_up_count",
  a_width_zt_count: "a_width_dt_count",   a_width_dt_count: "a_width_zt_count",
};
const _KPI_RATE_X100 = { a_width_seal_rate: true, a_width_fengban_rate: true };
async function _appendKpiEstimate(result, kpiId, todayDate) {
  if (!result || !result.series || !result.series.length || !todayDate) return [];
  // a_amount 已有 intraday 段(source='intraday' 盘中半日值)覆盖 T日，跳过预估避免与盘中点重叠
  if (kpiId === "a_amount") return [];
  const mainSeries = result.series[0];
  if (!mainSeries || !mainSeries.data || !mainSeries.data.length) return [];
  if (mainSeries.data[mainSeries.data.length - 1].date >= todayDate) return []; // 末日已==T日
  // overview 缓存（5min TTL）+ fallback fetch
  let ov = _getCachedOverview();
  if (!ov) {
    try { ov = await fetchJSON("./data/overview.json"); if (ov) _setCachedOverview(ov); } catch (e) { return []; }
  }
  if (!ov || !ov.today) return [];
  // 构建 {kpiId -> {value,date}} 查找表（scores 9 + metrics 20）
  const todayMap = {};
  const scores = ov.today.scores || {};
  for (const k in scores) {
    const sc = scores[k];
    if (sc && sc.value != null && sc.date) todayMap[k] = { value: sc.value, date: sc.date };
  }
  const metrics = ov.today.metrics || [];
  for (const m of metrics) {
    if (m && m.id && m.value != null && m.date) todayMap[m.id] = { value: m.value, date: m.date };
  }
  const estimates = [];
  const _tryPush = async (seriesIdx, kid) => {
    const info = todayMap[kid];
    if (!info || info.date !== todayDate) return; // T+1 源无 T 日值，不硬凑
    const s = result.series[seriesIdx];
    if (!s || !s.data || !s.data.length) return;
    if (s.data[s.data.length - 1].date >= todayDate) return; // 该 series 末日已==T日
    const val = _KPI_RATE_X100[kid] ? info.value * 100 : info.value;
    const pushed = await _appendIntradayEstimate(s.data, null, kid, todayDate, true, val);
    if (pushed) estimates.push({ seriesIdx, date: todayDate, value: val });
  };
  // series[0] = 主 kpiId
  await _tryPush(0, kpiId);
  // 多 series：companion kpiId -> series[1]（涨跌家数/涨跌停数）
  if (_KPI_COMPANION[kpiId] && result.series[1]) await _tryPush(1, _KPI_COMPANION[kpiId]);
  return estimates;
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
      '<div class="theme-divider"></div>' +
      '<h4 class="theme-section-title">🛡️ 显示模式</h4>' +
      '<div class="compliance-options">' +
        '<button class="theme-option compliance-option" data-compliance-mode="on">' +
          '<span class="compliance-icon">🛡️</span>' +
          '<span class="theme-info"><span class="theme-name">精简版（默认）</span>' +
          '<span class="theme-desc">简化信号表述</span></span>' +
          '<span class="theme-check">✓</span>' +
        '</button>' +
        '<button class="theme-option compliance-option" data-compliance-mode="off">' +
          '<span class="compliance-icon">📊</span>' +
          '<span class="theme-info"><span class="theme-name">完整版</span>' +
          '<span class="theme-desc">显示完整信号详情</span></span>' +
          '<span class="theme-check">✓</span>' +
        '</button>' +
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
      if (!opt.classList.contains("compliance-option")) {
        opt.classList.toggle("active", opt.dataset.theme === cur);
      }
    });
  }
  function renderComplianceActive() {
    var cur = _t.getMode() === "off" ? "off" : "on";
    modal.querySelectorAll(".compliance-option").forEach(function (opt) {
      opt.classList.toggle("active", opt.dataset.complianceMode === cur);
    });
  }
  document.querySelectorAll(".theme-btn").forEach(function (b) {
    b.addEventListener("click", function () {
      renderActive();
      renderComplianceActive();
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
      if (opt.classList.contains("compliance-option")) {
        // 合规开关：即时生效（切字典重渲染），不自动关弹窗，用户可继续切皮肤或手动关闭
        // gating：完整版（off）为登录特权 hasPrivilege("detailed_view")，未登录弹提示+登录入口不切换
        var _mode = opt.dataset.complianceMode;
        if (_mode === "off" && !hasPrivilege("detailed_view")) {
          modal.classList.add("hidden");
          openLoginPromptForDetailed();
          return;
        }
        applyCompliance(_mode);
        renderComplianceActive();
      } else {
        applyTheme(opt.dataset.theme);
        renderActive();
        setTimeout(function () { modal.classList.add("hidden"); }, 180);
      }
    }
  });
}

// === OAuth 登录态管理（2026-08-04 前端接入，后端 worker/auth.js）===
// 全局状态：window.__authState = { logged_in, user:{name,avatar,provider}|null, privileges:[] }
// 工具函数：isLoggedIn() / hasPrivilege(name)（供完整版 gating 等场景调用）
// 完整版（compliance_mode=off）为登录特权 hasPrivilege("detailed_view")，未登录点击弹提示+登录入口
// 其他特权（模拟回测/订阅/对比）MVP 不 gating，预留 hasPrivilege 接口供后续扩展
//
// 多站点方案E+G（2026-08-04）：备站(sss.sugas.site/s.sugas.site/localhost)无 Worker，
// /api/auth/* 走主站 ss.fx8.store 跨域 fetch（Bearer token 认证，token 存 localStorage）。
// 登录流程：备站点登录按钮 -> 跳主站 /api/auth/login/{provider}?redirect=<备站URL>
//   -> OAuth callback -> 生成 Bearer token -> 307 跳 ${备站}#auth_token=<token>
//   -> 备站 app.js 启动检测 #auth_token= -> 存 localStorage -> 清 hash -> fetchAuthState 带 Bearer
window.__authState = { logged_in: false, user: null, privileges: [] };
function isLoggedIn() {
  return !!(window.__authState && window.__authState.logged_in);
}
function hasPrivilege(name) {
  var p = window.__authState && window.__authState.privileges;
  return Array.isArray(p) && p.indexOf(name) !== -1;
}
// 多站点：主站 ss.fx8.store 走相对路径 + cookie；备站走主站域名 + Bearer token
function _isMainSite() {
  return location.hostname === 'ss.fx8.store';
}
function _authApiBase() {
  return _isMainSite() ? '' : 'https://ss.fx8.store';
}
function _getAuthToken() {
  try { return localStorage.getItem('auth_token') || ''; } catch (e) { return ''; }
}
function _setAuthToken(t) {
  try {
    if (t) localStorage.setItem('auth_token', t);
    else localStorage.removeItem('auth_token');
  } catch (e) {}
}
// 接收主站 OAuth 回跳的 #auth_token=<token>：存 localStorage 后清 hash（保留其他 hash 片段如 #market/xxx）
function _receiveAuthToken() {
  var h = location.hash || '';
  var m = h.match(/auth_token=([^&]+)/);
  if (!m) return false;
  _setAuthToken(decodeURIComponent(m[1]));
  // 清掉 auth_token 片段，保留其他 hash
  var newHash = h;
  // 先去掉 #auth_token=xxx 或 &auth_token=xxx
  newHash = newHash.replace(/[#&]auth_token=[^&]*/, '');
  // 修正开头：若开头是空（原 # 已被删）则无 hash；若开头是 & 补回 #
  if (newHash.charAt(0) === '&') newHash = '#' + newHash.slice(1);
  if (newHash === '#') newHash = '';
  try {
    history.replaceState(null, '', location.pathname + location.search + newHash);
  } catch (e) {}
  return true;
}
// 拉取登录态：/api/auth/me 返回 {logged_in, user, privileges}
// 未登录且 localStorage compliance_mode=off -> 强制回 on（防 localStorage 残留绕过完整版 gating）
// 主站：cookie 认证（credentials:include）；备站：Bearer token 认证（credentials:omit + Authorization header）
function fetchAuthState() {
  var base = _authApiBase();
  var token = _getAuthToken();
  var headers = token ? { 'Authorization': 'Bearer ' + token } : {};
  var credentials = _isMainSite() ? 'include' : 'omit';
  return fetch(base + '/api/auth/me', { credentials: credentials, headers: headers })
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (d) {
      if (d && d.logged_in) {
        window.__authState = { logged_in: true, user: d.user || null, privileges: Array.isArray(d.privileges) ? d.privileges : [] };
      } else {
        window.__authState = { logged_in: false, user: null, privileges: [] };
        // 备站 Bearer 失效（过期/被撤销）-> 清 localStorage 防止下次请求仍带过期 token
        if (!_isMainSite() && token) _setAuthToken(null);
        try {
          if (localStorage.getItem('compliance_mode') === 'off') {
            if (typeof _t !== 'undefined' && _t.setMode) _t.setMode('on');
            localStorage.setItem('compliance_mode', 'on');
            document.documentElement.setAttribute('data-compliance', 'on');
          }
        } catch (e) {}
      }
      applyAuthState();
    })
    .catch(function () { applyAuthState(); });
}
// 渲染登录按钮：未登录「👤 登录」，已登录头像+名字+退出
function applyAuthState() {
  var st = window.__authState || { logged_in: false, user: null, privileges: [] };
  var pcBtn = document.querySelector('.pc-auth-btn');
  var h5Btn = document.querySelector('.h5-auth-btn');
  if (st.logged_in && st.user) {
    var u = st.user;
    var name = (u.name || '已登录');
    var avatar = u.avatar || '';
    var avatarStyle = avatar ? ' style="background-image:url(\'' + avatar.replace(/'/g, '%27') + '\');background-size:cover;background-position:center;"' : '';
    // 头像 hover/click 弹下拉菜单含"退出登录"项（替代不明显的 ⎋ 按钮）
    var dropdownHtml = '<div class="auth-dropdown" role="menu">' +
                       '<div class="auth-dropdown-item" data-action="logout" role="menuitem" tabindex="0">退出登录</div>' +
                     '</div>';
    var pcHtml = '<span class="auth-user-wrap">' +
                   '<span class="auth-avatar"' + avatarStyle + '></span>' +
                   '<span class="auth-name">' + _escAttr(name) + '</span>' +
                   dropdownHtml +
                 '</span>';
    var h5Html = '<span class="auth-user-wrap">' +
                   '<span class="auth-avatar"' + avatarStyle + '></span>' +
                   dropdownHtml +
                 '</span>';
    // title 改 aria-label：避免 _initTermPop 把 [title] 迁移到 data-tip 后 show .term-pop 浮层
    // (z-index 9999 > .auth-dropdown z-index 60) 盖住下拉菜单致点不到「退出登录」(2026-08-10 修复)
    // 2026-07-20 根治：index.html 硬编码 title 已改 aria-label + 此处 removeAttribute('title') 双保险
    // 清掉任何残留 title（HTML 初始/别处动态加的），只留 aria-label（_initTermPop 不识别 aria-label）
    if (pcBtn) { pcBtn.removeAttribute('title'); pcBtn.innerHTML = pcHtml; pcBtn.classList.add('logged-in'); pcBtn.setAttribute('aria-label', (u.name || '账户') + '（悬停查看菜单）'); pcBtn.setAttribute('aria-haspopup', 'true'); pcBtn.setAttribute('aria-expanded', 'false'); }
    if (h5Btn) { h5Btn.removeAttribute('title'); h5Btn.innerHTML = h5Html; h5Btn.classList.add('logged-in'); h5Btn.setAttribute('aria-label', (u.name || '账户') + '（点击查看菜单）'); h5Btn.setAttribute('aria-haspopup', 'true'); h5Btn.setAttribute('aria-expanded', 'false'); }
  } else {
    if (pcBtn) { pcBtn.removeAttribute('title'); pcBtn.innerHTML = '👤 登录'; pcBtn.classList.remove('logged-in'); pcBtn.setAttribute('aria-label', '登录 / 账户'); }
    if (h5Btn) { h5Btn.removeAttribute('title'); h5Btn.innerHTML = '👤'; h5Btn.classList.remove('logged-in'); h5Btn.setAttribute('aria-label', '登录 / 账户'); }
  }
  // gating：基金评分 tab 为登录特权 fund_score，未登录隐藏 PC+H5 两个 fund tab 按钮（applyAuthState 每次 fetchAuthState 后调用，reload 后自动重判）
  var _fundVisible = st.logged_in && hasPrivilege('fund_score');
  document.querySelectorAll('button[data-tab="fund"]').forEach(function (b) {
    b.style.display = _fundVisible ? '' : 'none';
  });
}
// 登录方式选择弹窗：Gitee + GitHub 两按钮（不渲染 Google 占位）
function _authLoginModalHtml(title, tip) {
  return '<div class="modal-body">' +
    '<button class="theme-modal-close" title="关闭" aria-label="关闭">×</button>' +
    '<h3>' + _escAttr(title) + '</h3>' +
    (tip ? '<p class="auth-login-tip">' + _escAttr(tip) + '</p>' : '') +
    '<div class="auth-login-options">' +
      '<button class="auth-login-btn auth-login-gitee" data-provider="gitee">' +
        '<span class="auth-login-icon">🐱</span>' +
        '<span class="auth-login-text">Gitee 登录</span>' +
      '</button>' +
      '<button class="auth-login-btn auth-login-github" data-provider="github">' +
        '<span class="auth-login-icon">🐙</span>' +
        '<span class="auth-login-text">GitHub 登录</span>' +
      '</button>' +
    '</div>' +
    '<p class="auth-login-note">登录即同意本站仅用于学习研究，不构成投资建议</p>' +
  '</div>';
}
function _bindAuthLoginModal(modal) {
  modal.addEventListener('click', function (e) {
    if (e.target === modal || e.target.classList.contains('theme-modal-close')) {
      modal.classList.add('hidden');
      setTimeout(function () { if (modal.parentNode) modal.parentNode.removeChild(modal); }, 200);
      return;
    }
    var btn = e.target.closest('.auth-login-btn');
    if (btn) {
      var provider = btn.dataset.provider;
      var base = _authApiBase();
      // 主站：直接跳 /api/auth/login/{provider}（callback 设 cookie 跳 /）
      // 备站：跳主站 /api/auth/login/{provider}?redirect=<备站URL>（callback 生成 Bearer token 跳回备站 #auth_token=）
      if (_isMainSite()) {
        window.location.href = base + '/api/auth/login/' + provider;
      } else {
        var redirect = location.origin + location.pathname;
        window.location.href = base + '/api/auth/login/' + provider + '?redirect=' + encodeURIComponent(redirect);
      }
    }
  });
  modal.classList.remove('hidden');
}
function openLoginModal() {
  var modal = document.createElement('div');
  modal.className = 'modal auth-login-modal hidden';
  modal.innerHTML = _authLoginModalHtml('登录', '登录后可使用「完整版」等特权功能');
  document.body.appendChild(modal);
  _bindAuthLoginModal(modal);
}
// 未登录点完整版：弹提示+登录入口（不切换模式）
function openLoginPromptForDetailed() {
  var modal = document.createElement('div');
  modal.className = 'modal auth-login-modal hidden';
  modal.innerHTML = _authLoginModalHtml('🔒 完整版需登录', '完整版为登录用户特权，登录后可显示完整信号详情');
  document.body.appendChild(modal);
  _bindAuthLoginModal(modal);
}
// 通用 gating 入口：未登录点击受特权保护的功能按钮时弹提示+登录入口
// featureName: 功能中文名（如"模拟回测"/"订阅"/"钉住"/"基金评分"），用于拼 title
// tip: 自定义提示文案（不传用默认"X为登录用户特权，登录后可使用"）
function openLoginPromptForFeature(featureName, tip) {
  var modal = document.createElement('div');
  modal.className = 'modal auth-login-modal hidden';
  modal.innerHTML = _authLoginModalHtml('🔒 ' + featureName + '需登录', tip || (featureName + '为登录用户特权，登录后可使用'));
  document.body.appendChild(modal);
  _bindAuthLoginModal(modal);
}
function logout() {
  var base = _authApiBase();
  var token = _getAuthToken();
  var headers = token ? { 'Authorization': 'Bearer ' + token } : {};
  var credentials = _isMainSite() ? 'include' : 'omit';
  fetch(base + '/api/auth/logout', { method: 'POST', credentials: credentials, headers: headers })
    .then(function () { _setAuthToken(null); window.location.reload(); })
    .catch(function () { _setAuthToken(null); window.location.reload(); });
}
// 退出确认弹窗：点退出按钮先弹确认，用户点「确认退出」才真正调 logout，点「取消」关闭不退出
function openConfirmLogout() {
  // 避免重复弹出
  var existing = document.querySelector('.auth-logout-modal');
  if (existing) { existing.classList.remove('hidden'); return; }
  var modal = document.createElement('div');
  modal.className = 'modal auth-login-modal auth-logout-modal hidden';
  modal.innerHTML = '<div class="modal-body">' +
    '<button class="theme-modal-close" title="关闭" aria-label="关闭">×</button>' +
    '<h3>确认退出登录？</h3>' +
    '<p class="auth-login-tip">退出后将无法使用「完整版」等登录特权功能，需重新登录后才能恢复。</p>' +
    '<div class="auth-login-options">' +
      '<button class="auth-login-btn auth-cancel-btn" data-action="cancel">' +
        '<span class="auth-login-text">取消</span>' +
      '</button>' +
      '<button class="auth-login-btn auth-confirm-logout-btn" data-action="confirm">' +
        '<span class="auth-login-text">确认退出</span>' +
      '</button>' +
    '</div>' +
  '</div>';
  document.body.appendChild(modal);
  function closeModal() {
    modal.classList.add('hidden');
    setTimeout(function () { if (modal.parentNode) modal.parentNode.removeChild(modal); }, 200);
  }
  modal.addEventListener('click', function (e) {
    if (e.target === modal || e.target.classList.contains('theme-modal-close')) {
      closeModal();
      return;
    }
    var btn = e.target.closest('.auth-login-btn');
    if (btn) {
      if (btn.dataset.action === 'confirm') {
        closeModal();
        logout();
      } else {
        closeModal();
      }
    }
  });
  modal.classList.remove('hidden');
}
// 绑定登录按钮点击：未登录弹登录框，已登录 hover/click 弹下拉菜单，"退出登录"项调确认弹窗
function initAuthButton() {
  // 多站点方案G：启动时接收主站 OAuth 回跳的 #auth_token=<token>，存 localStorage 后清 hash
  _receiveAuthToken();
  document.querySelectorAll('.pc-auth-btn, .h5-auth-btn').forEach(function (btn) {
    btn.addEventListener('click', function (e) {
      // 下拉菜单"退出登录"项点击 -> 退出确认弹窗（复用 openConfirmLogout，不直接退出）
      var item = e.target.closest('.auth-dropdown-item');
      if (item && item.dataset.action === 'logout') {
        e.stopPropagation();
        e.preventDefault();
        var dd = btn.querySelector('.auth-dropdown');
        if (dd) dd.classList.remove('open');
        btn.setAttribute('aria-expanded', 'false');
        openConfirmLogout();
        return;
      }
      if (window.__authState && window.__authState.logged_in) {
        // 已登录：PC 用 CSS :hover 显示下拉，JS 不干预；H5 无 hover，click toggle 下拉
        if (btn.classList.contains('h5-auth-btn')) {
          var dd2 = btn.querySelector('.auth-dropdown');
          if (dd2) {
            var willOpen = !dd2.classList.contains('open');
            dd2.classList.toggle('open');
            btn.setAttribute('aria-expanded', willOpen ? 'true' : 'false');
          }
        }
        return;
      }
      openLoginModal();
    });
  });
  // H5：点击下拉外部关闭（移动端无 hover，需主动关闭）
  document.addEventListener('click', function (e) {
    document.querySelectorAll('.h5-auth-btn .auth-dropdown.open').forEach(function (dd) {
      var wrap = dd.closest('.h5-auth-btn');
      if (wrap && !wrap.contains(e.target)) {
        dd.classList.remove('open');
        wrap.setAttribute('aria-expanded', 'false');
      }
    });
  });
  fetchAuthState();
}

// === 合规/完整视图切换（皮肤弹窗内开关，复用 applyTheme 模式）===
// mode="on"(精简版,默认,简化表述) / "off"(完整版,显示完整信号详情,用户在皮肤弹窗内切回)
// i18n.js 的 _t() 根据 mode 返回精简/完整版文案；切 mode 后重渲染当前 tab
function applyCompliance(mode) {
  _t.setMode(mode);
  try { localStorage.setItem("compliance_mode", mode === "off" ? "off" : "on"); } catch (e) {}
  document.documentElement.setAttribute("data-compliance", mode === "off" ? "off" : "on");
  // 更新皮肤弹窗内合规开关高亮状态（on 精简版高亮 / off 完整版高亮）
  var normMode = mode === "off" ? "off" : "on";
  document.querySelectorAll(".compliance-option").forEach(function (b) {
    b.classList.toggle("active", b.dataset.complianceMode === normMode);
  });
  // 重渲染当前 tab：用新字典重新渲染所有 DOM 文本 + 图表 pin（renderTab 内部按 state.tab 调对应 render 函数）
  requestAnimationFrame(function () {
    if (typeof renderTab === "function") renderTab();
    // 2026-07-20 修复：切换合规/完整模式时重渲染已打开的 trade_sim modal（modal 是独立 overlay 不在 tab 内，renderTab 不触及）
    if (typeof _tradeSimOverlay !== 'undefined' && _tradeSimOverlay && _tradeSimOverlay.classList.contains('show') && typeof _tradeSimModalRender === 'function') {
      try { _tradeSimModalRender(_tradeSimOverlay); } catch (e) {}
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
      '<p class="ur-note">绿=实时/收盘最新，灰=T+1正常待更新，黄=滞后，红=异常(>15天)。悬停单项查看源说明。</p>' +
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
        '<tr><td>20:05 + 21:00(兜底)</td><td>期货机构持仓单采</td><td>中金所(CFFEX)股指期货前20名会员持仓~20:00出后单采；21:00二次槽应对异常重采</td></tr>' +
        '<tr><td>20:07 + 21:30(兜底)</td><td>ETF汪汪队份额单采</td><td>SSE/SZSE ETF份额T+1发布单采；21:30二次槽当日兜底重采</td></tr>' +
        '<tr><td>23:00</td><td>两融单采</td><td>沪市融资余额源盘后发布较晚(实测22:10仍未出),当晚23:00单采当日(采到则当日上线),配合凌晨兜底补齐</td></tr>' +
        '<tr><td>02:00</td><td>凌晨兜底</td><td>补采遗漏确保次日数据齐全</td></tr>' +
      '</tbody></table>' +
    '</div>' +
    '<div class="rule-section">' +
      '<h4>⏱️ 各数据时效</h4>' +
      '<ul class="ur-list">' +
        '<li>📈 <b>A股指数涨跌幅/热点板块/一句话总结</b>：盘中前端动态拉取腾讯分时数据（约1分钟刷新）；30分钟服务器快照仅用于收盘归档与情绪分计算</li>' +
        '<li>🇭🇰 <b>港股指数（恒生/恒生科技/国企）</b>：盘中实时快照（9:30-16:00），16:35 补完整收盘 OHLC(开高低收)</li>' +
        '<li>🇭🇰 <b>港股板块指数</b>：腾讯备源兜底（cesg10/hsmogi/hsmbi/hsmpi/hscci 5个有腾讯兜底）；cshklre/cshklc/cshkdiv 3个仅新浪无备源</li>' +
        '<li>🇺🇸 <b>美股指数</b>：北京时差晚 21:30 开盘，A 股交易日看美股最新是 T-1 或 T-2（跨周末），属正常</li>' +
        '<li>🇺🇸 <b>美股期货 ES/NQ（新浪 hf_ES/hf_NQ）</b>：盘中亚盘时段实时，预估美股当晚开盘方向（ES↔标普500 / NQ↔纳指100），不替代美股收盘价</li>' +
        '<li>📊 <b>指数历史走势 OHLC(开高低收)</b>：T+1（申万/baostock 收盘后次日补全）</li>' +
        '<li>😐 <b>恐贪指数 / per-index 情绪分</b>：快照反哺后当日可用，否则停 T-1</li>' +
        '<li>📋 <b>A股综合情绪分</b>：当日（mootdx 实时算）</li>' +
      '</ul>' +
    '</div>' +
    '<div class="rule-section">' +
      '<h4>🏷️ 卡片角标时效分级</h4>' +
      '<ul class="ur-list">' +
        '<li>📅 <b>T+1·MM-DD（灰）</b>：正常。数据源盘后T+1公布，公开平台（行情软件）也才到这个日期，下一交易日才更新（逢周末/节假日顺延）</li>' +
        '<li>⏰ <b>盘中·HH:MM（绿）/ 午休（黄）</b>：实时。A股/港股指数盘中动态拉取，约1分钟刷新</li>' +
        '<li>📍 <b>收盘·MM-DD（主题色）</b>：收盘后归档，数据正常时显示；若滞后则切换为⚠/🚨</li>' +
        '<li>⚠ <b>滞后·MM-DD（黄）</b>：异常。该数据应T+1更新但已滞后（悬停可见天数），公开平台已有更新但我们没采到</li>' +
        '<li>🚨 <b>异常·MM-DD（红）</b>：严重滞后（>15天），请反馈</li>' +
        '<li>本弹窗顶部"📊 各数据源实时时效"区块汇总各数据源最新状态，可一眼区分正常T+1 vs 异常滞后</li>' +
      '</ul>' +
    '</div>' +
    '<div class="rule-section">' +
      '<h4>🔄 盘中动态值说明</h4>' +
      '<ul class="ur-list">' +
        '<li>盘中：卡片涨跌幅、横幅指标 chips、分时图均为前端动态拉取腾讯分时数据，约1分钟刷新，三处数值同源一致</li>' +
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
        '<li>港股 16:00 收盘（比 A 股晚 1 小时），盘中快照采实时价，16:35 后补完整收盘 OHLC(开高低收)</li>' +
        '<li>美股北京时差晚 21:30 才开盘，A 股交易日看美股最新通常是 T-1 或 T-2（跨周末更久），属正常</li>' +
        '<li>收盘后约 2 小时（17:50 update_all）T+1 源出数据后会补全</li>' +
        '<li>晚 20:00 再兜底补一次，凌晨 02:00 也会兜底一次</li>' +
      '</ul>' +
    '</div>' +
    '<div class="rule-section">' +
      '<h4>📈 公募基金底座采集（stage0）</h4>' +
      '<table class="ur-table"><thead><tr><th>任务</th><th>调度时点</th><th>内容</th><th>频率</th></tr></thead><tbody>' +
        '<tr><td>overview</td><td>周日 02:17</td><td>补 fund_basic 15 列（规模/经理/成立日等）</td><td>每周</td></tr>' +
        '<tr><td>nav</td><td>周五 01:43</td><td>5 年净值断点续采</td><td>每周</td></tr>' +
        '<tr><td>risk</td><td>每月 15 日 02:33</td><td>风险指标 + 费率</td><td>季报月（1/4/7/10）才真跑，增量</td></tr>' +
        '<tr><td>manager</td><td>每月 1 日 02:47</td><td>任职历史</td><td>每月</td></tr>' +
      '</tbody></table>' +
      '<p class="ur-note">公募基金底座数据（fund_basic/净值/风险/经理）独立采集，为场外基金评分排行（Phase A）提供数据基础。</p>' +
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
  let staleCount = 0, severeCount = 0;
  sources.forEach((s) => {
    if (s.cls === "t1-stale") staleCount++;
    if (s.cls === "t1-severe") severeCount++;
  });
  const summary = severeCount > 0 ? `🚨 ${severeCount}项异常` : staleCount > 0 ? `⚠ ${staleCount}项滞后` : "✓ 全部正常";
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

// P2-1: 次日访问才弹 onboarding 3 步引导
// 触发规则(2026-07-31 改):首次 ever 访问不弹(等次日),当日重复访问不弹,
// 次日(及跨多天)首次访问且当日未弹过才弹;每天最多弹 1 次。
// 通过 last_visit_date(上次访问日期 YYYYMMDD)+ welcome_shown_date(当日已弹日期)双标记控制。
function initOnboarding() {
  const d = new Date();
  const todayStr = d.getFullYear() +
    String(d.getMonth() + 1).padStart(2, '0') +
    String(d.getDate()).padStart(2, '0');
  let lastVisit = null, welcomeShown = null;
  try {
    lastVisit = localStorage.getItem('last_visit_date');
    welcomeShown = localStorage.getItem('welcome_shown_date');
  } catch (e) { return; }

  const setLastVisitToday = function () {
    try { localStorage.setItem('last_visit_date', todayStr); } catch (e) {}
  };

  // 当日已弹过:不弹(只刷新 last_visit_date)
  if (welcomeShown === todayStr) { setLastVisitToday(); return; }
  // 首次 ever 访问(无 last_visit_date)或当日重复访问:不弹,等次日
  if (!lastVisit || lastVisit === todayStr) { setLastVisitToday(); return; }

  // 次日访问(last_visit_date < 今天,YYYYMMDD 字典序=时间序):弹 + 标记当日已弹
  // 先清 onboarding_done,否则 showIntroOnce 内部首行检查会 return 不弹
  try { localStorage.removeItem('onboarding_done'); } catch (e) {}
  setLastVisitToday();
  try { localStorage.setItem('welcome_shown_date', todayStr); } catch (e) {}

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
        body: '想深入?策略实验室提供 <b>82 品种关注点/风险点回测</b>、信号消融分析、蒙特卡洛模拟,帮你理解每个信号的历史表现与稳健性。'
      }
    ]
  });
}

initNavStickyToggle();
initStickyOffset();
initBackToTop();
initRuleButton();
initH5();
initSimIndices();   // 动态加载 SIM_INDICES 清单（fetch trade_sim_indices.json），renderTab 会 await
initSimOverlay();
initShareButton();
initThemeSwitcher();
initAuthButton();
initNotifyButton();
initOnboarding();
initUpdateRules();

// === 主 tab hash 记忆 + 滚动位置恢复 ===
// 切 tab 写 hash（replaceState 不入历史、不触发 hashchange），F5 读 hash 恢复 tab + 滚动位置。
// #lab 开头归 lab.js 的 lab 恢复逻辑（含 #lab/策略key），此模块只管 4 个非 lab 主 tab。
// 大盘 tab 的二级 tab 也写进 hash：#market/{subtab}（如 #market/national-team=汪汪队），
// F5 刷新解析恢复二级 tab，避免刷新回退到默认 a 股。
const _MAIN_TABS = ["overview", "market", "sentiment", "fund"];
const _MARKET_SUBTABS = ["a-stock", "industry", "hk", "global"];
const _SENTIMENT_SUBTABS = ["market-temp", "futures", "national-team", "public-fund"];
// 信号弹窗定位路径：指数 id -> 所属 tab + subtab + 中文名（告知用户完整数据去哪个 tab）
// 返回 {tab:"market"|"sentiment", subtab:"hk"|...|null, tabName:"指数表现"|..., name:"港股"|...|null, idxName:"恒生国企"|""}
// tabName=一级 tab 中文名（指数表现/盘面温测），name=二级 sub-tab 中文名（港股/A股/...）
// s.* 情绪分 -> 盘面温测 tab（sentiment/market-temp，subtab=null 让默认逻辑接手）
const _MARKET_SUBTAB_CN = { "a-stock": "A股", industry: "行业", hk: "港股", global: "全球" };
// 一级 tab 中文名（无 emoji，定位路径用；_H5_TAB_NAMES 带 emoji 给顶部条用，语义不同）
const _MAIN_TAB_CN = { market: "指数表现", sentiment: "盘面温测" };
const _A_STOCK_INDEX_IDS = new Set(["sh","sz","hs300","sz50","csi500","csi1000","cyb","kc50","bj50","csi_div","div_lowvol","sz_div"]);
const _HK_INDEX_IDS = new Set(["hsi","hstech","hscei","hk_cesg10","hk_cshkdiv","hk_cshklc","hk_cshklre","hk_hscci","hk_hsmbi","hk_hsmogi","hk_hsmpi"]);
const _GLOBAL_INDEX_IDS = new Set(["us_dji","us_ixic","us_spx","us_ndx","nikkei225","kospi","ftse100","dax","cac40","cgb_idx","cgb_10y_etf","cgb_10y_future"]);
function indexToMarketSubtab(indexId) {
  if (!indexId) return { tab: null, subtab: null, tabName: null, name: null, idxName: "" };
  // s.* 情绪分 -> 盘面温测 tab
  if (indexId.startsWith("s.")) {
    return { tab: "sentiment", subtab: null, tabName: _MAIN_TAB_CN["sentiment"], name: _MAIN_TAB_CN["sentiment"], idxName: "" };
  }
  // 去前缀（g.=全球指标 wti_oil/gold 等）
  const bare = indexId.startsWith("g.") ? indexId.slice(2) : indexId;
  const idxName = (typeof indexIdToName === "function") ? indexIdToName(bare) : bare;
  if (_A_STOCK_INDEX_IDS.has(bare)) return { tab: "market", subtab: "a-stock", tabName: _MAIN_TAB_CN["market"], name: _MARKET_SUBTAB_CN["a-stock"], idxName: idxName };
  if (_HK_INDEX_IDS.has(bare)) return { tab: "market", subtab: "hk", tabName: _MAIN_TAB_CN["market"], name: _MARKET_SUBTAB_CN["hk"], idxName: idxName };
  if (_GLOBAL_INDEX_IDS.has(bare)) return { tab: "market", subtab: "global", tabName: _MAIN_TAB_CN["market"], name: _MARKET_SUBTAB_CN["global"], idxName: idxName };
  // g.* 全球指标兜底（cn10y/us10y/wti_oil/gold/comex_silver/usdcnh/a_qvix_*/brent/cn_us_spread 等）
  if (indexId.startsWith("g.")) return { tab: "market", subtab: "global", tabName: _MAIN_TAB_CN["market"], name: _MARKET_SUBTAB_CN["global"], idxName: idxName };
  // 申万(sw_*)/同花顺(thsc_*)行业 -> industry
  if (bare.startsWith("sw_") || bare.startsWith("thsc_")) return { tab: "market", subtab: "industry", tabName: _MAIN_TAB_CN["market"], name: _MARKET_SUBTAB_CN["industry"], idxName: idxName };
  return { tab: null, subtab: null, tabName: null, name: null, idxName: "" };
}
const _FUND_SUBTABS = ["etf", "offshore"]; // 场内ETF / 场外基金
function _setTabHash(tab) {
  let h = "#" + tab;
  if (tab === "market" && state.subtab) h = "#market/" + state.subtab;
  if (tab === "sentiment" && state.subtab) h = "#sentiment/" + state.subtab;
  if (tab === "fund" && state.subtab) h = "#fund/" + state.subtab;
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
  let h = location.hash;
  if (!h || h.startsWith("#lab")) return;
  // 旧 #etf 路由兼容：ETF评分已重构为「基金评分」下的「场内ETF」二级 tab，重定向到 #fund/etf
  if (h === "#etf") {
    h = "#fund/etf";
    try { history.replaceState(null, "", location.pathname + location.search + h); } catch (e) {}
  }
  // 旧 #industry 路由兼容：板块分化已移到「指数表现」下的二级 tab，重定向到 #market/industry
  if (h === "#industry") {
    h = "#market/industry";
    try { history.replaceState(null, "", location.pathname + location.search + h); } catch (e) {}
  }
  const parts = h.slice(1).split("/"); // "market/national-team" -> ["market", "national-team"]
  const tab = parts[0];
  if (!_MAIN_TABS.includes(tab)) return;
  state.tab = tab;
  if (tab === "market") {
    // 解析二级 tab，非法/缺失回退 a 股
    const sub = parts[1];
    state.subtab = _MARKET_SUBTABS.includes(sub) ? sub : "a-stock";
  } else if (tab === "sentiment") {
    // 解析二级 tab，非法/缺失回退市场温度
    const sub = parts[1];
    state.subtab = _SENTIMENT_SUBTABS.includes(sub) ? sub : "market-temp";
  } else if (tab === "fund") {
    // 解析二级 tab，非法/缺失回退场内ETF
    const sub = parts[1];
    state.subtab = _FUND_SUBTABS.includes(sub) ? sub : "etf";
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
// 盘中自动轮询 overview.json(5min) 更新采集时间badge, 收盘自停, visibilitychange切回tab立即刷新
_initAutoRefresh();
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
