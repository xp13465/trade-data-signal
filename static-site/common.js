// === C7 P4 market 融合:公共函数库(common.js) ===
// 从 lab.js 抽出的 10 个 _labCustom* 函数 + 2 个 iid 常量,供 lab tab 自定义分析 + market tab 分数卡共用
// 加载顺序:index.html 中 common.min.js 用 <script defer> 在 app.min.js + lab.min.js 之前加载,执行时 window._labCustom* 已就绪
// 纯函数库,无 IIFE 副作用,无 DOM 依赖
//
// 用法(lab.js / app.js):
//   直接调用 _labCustomScoreCardHTML(...) 等同名函数(本文件末尾挂到 window,且 lab.js 用 var 别名引用)
//   常量 _LAB_CUSTOM_BROAD / _LAB_CUSTOM_SW 同样挂 window

// === 40 个预生成 iid + 中文名(与 app/alert_match.py PREGEN_TARGETS 对齐) ===
var _LAB_CUSTOM_BROAD = [
  { iid: "sh", name: "上证指数" },
  { iid: "sz", name: "深成指" },
  { iid: "sz50", name: "上证50" },
  { iid: "hs300", name: "沪深300" },
  { iid: "csi500", name: "中证500" },
  { iid: "csi1000", name: "中证1000" },
  { iid: "cyb", name: "创业板指" },
  { iid: "kc50", name: "科创50" },
  { iid: "bj50", name: "北证50" },
];
var _LAB_CUSTOM_SW = [
  { iid: "sw_801010", name: "SW 农林牧渔" }, { iid: "sw_801030", name: "SW 基础化工" },
  { iid: "sw_801040", name: "SW 钢铁" }, { iid: "sw_801050", name: "SW 有色金属" },
  { iid: "sw_801080", name: "SW 电子" }, { iid: "sw_801880", name: "SW 汽车" },
  { iid: "sw_801110", name: "SW 家用电器" }, { iid: "sw_801120", name: "SW 食品饮料" },
  { iid: "sw_801130", name: "SW 纺织服饰" }, { iid: "sw_801140", name: "SW 轻工制造" },
  { iid: "sw_801150", name: "SW 医药生物" }, { iid: "sw_801160", name: "SW 公用事业" },
  { iid: "sw_801170", name: "SW 交通运输" }, { iid: "sw_801180", name: "SW 房地产" },
  { iid: "sw_801200", name: "SW 商贸零售" }, { iid: "sw_801210", name: "SW 社会服务" },
  { iid: "sw_801780", name: "SW 银行" }, { iid: "sw_801790", name: "SW 非银金融" },
  { iid: "sw_801230", name: "SW 综合" }, { iid: "sw_801710", name: "SW 建筑材料" },
  { iid: "sw_801720", name: "SW 建筑装饰" }, { iid: "sw_801730", name: "SW 电力设备" },
  { iid: "sw_801890", name: "SW 机械设备" }, { iid: "sw_801740", name: "SW 国防军工" },
  { iid: "sw_801750", name: "SW 计算机" }, { iid: "sw_801760", name: "SW 传媒" },
  { iid: "sw_801770", name: "SW 通信" }, { iid: "sw_801950", name: "SW 煤炭" },
  { iid: "sw_801960", name: "SW 石油石化" }, { iid: "sw_801970", name: "SW 环保" },
  { iid: "sw_801980", name: "SW 美容护理" },
];
// C7 P4 select 扩55:新增红利3+港股3+全球9(与 app/alert_match.py DIV_INDEX_IDS/HK_INDEX_IDS/GLOBAL_INDEX_IDS + app.js _INDEX_NAME_MAP 对齐)
var _LAB_CUSTOM_DIV = [
  { iid: "csi_div", name: "中证红利" },
  { iid: "div_lowvol", name: "红利低波" },
  { iid: "sz_div", name: "深证红利" },
];
var _LAB_CUSTOM_HK = [
  { iid: "hsi", name: "恒生指数" },
  { iid: "hstech", name: "恒生科技" },
  { iid: "hscei", name: "恒生国企" },
];
var _LAB_CUSTOM_GLOBAL = [
  { iid: "us_dji", name: "道琼斯" },
  { iid: "us_ixic", name: "纳斯达克" },
  { iid: "us_spx", name: "标普500" },
  { iid: "us_ndx", name: "纳斯达克100" },
  { iid: "nikkei225", name: "日经225" },
  { iid: "kospi", name: "KOSPI" },
  { iid: "ftse100", name: "富时100" },
  { iid: "dax", name: "德国DAX" },
  { iid: "cac40", name: "法国CAC40" },
];

// 取 lab.min.js 的 ?v= 版本号用于破 alert_analyze_*.json 缓存(与 lab-asset-url meta 同步)
function _labCustomCacheBust() {
  try {
    const meta = document.querySelector('meta[name="lab-asset-url"]');
    if (meta && meta.content) {
      const m = String(meta.content).match(/[?&]v=([0-9a-f]+)/i);
      if (m) return m[1];
    }
  } catch (e) {}
  return Date.now().toString(36);
}

// 等级标签配色(按分值区间)
function _labCustomLevelClass(score, direction) {
  // direction: "high"=高位预警(分越高越危险) / "low"=低位机会(分越高越冷越有机会)
  if (score == null || isNaN(score)) return "lvl-neutral";
  if (direction === "high") {
    return score >= 70 ? "lvl-danger" : score >= 50 ? "lvl-warn" : "lvl-neutral";
  }
  // low: 高分=机会大=绿(好),低分=中性
  return score >= 70 ? "lvl-good" : score >= 50 ? "lvl-warn" : "lvl-neutral";
}

function _labCustomLevelText(level) {
  return level || "中性";
}

// 等级 tooltip(悬浮显示分值区间含义)
function _labCustomLevelTooltip(score, direction) {
  if (score == null || isNaN(score)) return "无数据";
  if (direction === "high") {
    if (score >= 70) return "≥70 过热逢高谨慎";
    if (score >= 50) return "50-70 偏热留意";
    return "<50 暂无过热";
  }
  if (score >= 70) return "≥70 机会显现";
  if (score >= 50) return "50-70 进入低位区";
  return "<50 暂无低位信号";
}

// 默认大白话(human_text 为空时按等级生成)
function _labCustomDefaultHuman(direction, score) {
  if (score == null || isNaN(score)) return "数据不足，无法判断";
  if (direction === "high") {
    if (score >= 70) return "多处指标过热，注意调整风险";
    if (score >= 50) return "部分指标偏热，留意回调风险";
    return "暂无明显过热信号";
  }
  if (score >= 70) return "多处指标低位，机会显现";
  if (score >= 50) return "部分指标进入低位区，关注企稳信号";
  return "暂无低位信号";
}

// 分数卡顶部总判断(基于 high+low 综合给一句话)
function _labCustomScoreSummary(high, low) {
  const hasH = high != null && !isNaN(high);
  const hasL = low != null && !isNaN(low);
  if (!hasH && !hasL) return { text: "➡️ 数据不足，暂无法判断", cls: "sum-neutral" };
  const highHot = hasH && high >= 70;
  const highWarm = hasH && high >= 50 && high < 70;
  const lowOpp = hasL && low >= 70;
  const lowWarm = hasL && low >= 50 && low < 70;
  if (highHot && lowOpp) return { text: "⚠️ 高位过热+低位机会并存，分化严重，谨慎操作", cls: "sum-warn" };
  if (highHot) return { text: "⚠️ 当前偏热，注意调整风险", cls: "sum-danger" };
  if (lowOpp) return { text: "💡 当前偏冷，关注企稳机会", cls: "sum-good" };
  if (highWarm && lowWarm) return { text: "➡️ 当前分化，部分偏热部分偏冷，观望为主", cls: "sum-warn" };
  if (highWarm) return { text: "➡️ 部分指标偏热，留意回调风险", cls: "sum-warn" };
  if (lowWarm) return { text: "➡️ 部分指标进入低位区，关注企稳信号", cls: "sum-good" };
  return { text: "➡️ 当前中性，观望为主", cls: "sum-neutral" };
}

// 分数卡(high 高位预警 + low 低位机会 + adapt 适配信息)
function _labCustomScoreCardHTML(data, alert, humanText) {
  const name = (_INDEX_NAME_MAP[data.target_id] || data.target_name || data.target_id || "");
  const date = alert.date || "";
  const dateStr = date && date.length === 8 ? `${date.slice(0,4)}-${date.slice(4,6)}-${date.slice(6,8)}` : date;
  const high = alert.high, low = alert.low;
  const highLvlCls = _labCustomLevelClass(high, "high");
  const lowLvlCls = _labCustomLevelClass(low, "low");
  const highLvlText = _labCustomLevelText(alert.high_level);
  const lowLvlText = _labCustomLevelText(alert.low_level);
  const highTooltip = _labCustomLevelTooltip(high, "high");
  const lowTooltip = _labCustomLevelTooltip(low, "low");
  const adapt = alert.adapt || {};
  const missing = adapt.missing || [];
  const adaptTxt = `最小维度门槛 ${adapt.min_dims ?? "?"} · 可用 高位${adapt.available_high ?? "?"}/低位${adapt.available_low ?? "?"}` +
    (missing.length ? ` · 缺项 ${missing.length} 个（${missing.join(", ")}）` : " · 无缺项");

  // 大白话前置(优先 human_text，空则按等级生成默认)
  humanText = humanText || {};
  const highHuman = humanText.high || _labCustomDefaultHuman("high", high);
  const lowHuman = humanText.low || _labCustomDefaultHuman("low", low);

  // 顶部总判断(基于 high+low 综合给一句话)
  const summary = _labCustomScoreSummary(high, low);

  // 方案B:仓位分(alert.position = {hands, volatility, label})
  const pos = alert.position || null;
  const posHands = pos ? pos.hands : null;
  const posLabel = pos ? pos.label : "";
  const posVol = pos ? pos.volatility : null;
  const posRow = pos
    ? `<div class="market-position-row">` +
        `<span class="position-badge position-${posHands}">建议仓位 ${posLabel}</span>` +
        `<span class="volatility-text">波动率 ${posVol != null ? posVol.toFixed(2) : "-"}%</span>` +
      `</div>`
    : `<div class="market-position-row"><span class="position-badge position-0">建议仓位 数据不足</span></div>`;

  return `<div class="lab-custom-score-card">` +
    `<div class="lab-custom-score-head">` +
      `<div class="lab-custom-score-title">${name} <span class="lab-custom-score-date">📅 ${dateStr}</span></div>` +
      `<div class="lab-custom-adapt">${adaptTxt}</div>` +
    `</div>` +
    `<div class="lab-custom-score-summary ${summary.cls}">${summary.text}</div>` +
    `<div class="lab-custom-score-grid">` +
      `<div class="lab-custom-score-cell ${highLvlCls}">` +
        `<div class="lab-custom-cell-label">高位预警<span class="lab-custom-cell-sublabel">越高越热，≥70 过热注意调整</span></div>` +
        `<div class="lab-custom-cell-score">${high != null ? high.toFixed(2) : "-"}</div>` +
        `<div class="lab-custom-cell-level" title="${highTooltip}">${highLvlText}</div>` +
        `<div class="lab-custom-cell-desc">分越高越接近过热 · 悬浮看区间含义</div>` +
        `<div class="lab-custom-cell-human">${highHuman}</div>` +
      `</div>` +
      `<div class="lab-custom-score-cell ${lowLvlCls}">` +
        `<div class="lab-custom-cell-label">低位机会<span class="lab-custom-cell-sublabel">越高机会越大，≥70 机会显现</span></div>` +
        `<div class="lab-custom-cell-score">${low != null ? low.toFixed(2) : "-"}</div>` +
        `<div class="lab-custom-cell-level" title="${lowTooltip}">${lowLvlText}</div>` +
        `<div class="lab-custom-cell-desc">分越高越偏冷有机会 · 悬浮看区间含义</div>` +
        `<div class="lab-custom-cell-human">${lowHuman}</div>` +
      `</div>` +
    `</div>` +
    posRow +
  `</div>`;
}

// 8+8 维度表(H1-H8 高位预警 + L1-L8 低位机会)
function _labCustomDimsTableHTML(dimHits, dims, adapt) {
  dimHits = dimHits || {};
  dims = dims || {};
  const adaptMissing = (adapt && adapt.missing) || [];
  // 构造 H1-H8 / L1-L8 顺序表，dim_hits 提供名称/权重/贡献/命中；dims 提供原始 score
  const hitsHighMap = {};
  (dimHits.high || []).forEach((h) => { hitsHighMap[h.k] = h; });
  const hitsLowMap = {};
  (dimHits.low || []).forEach((h) => { hitsLowMap[h.k] = h; });

  function rowHTML(k, side) {
    const hit = side === "high" ? hitsHighMap[k] : hitsLowMap[k];
    const score = dims[k];
    const isMissing = adaptMissing.includes(k) || score == null;
    const name = hit ? hit.name : (isMissing ? "（无数据）" : k);
    if (isMissing && !hit) {
      return `<tr class="lab-custom-dim-row dim-na">` +
        `<td class="dim-k">${k}</td>` +
        `<td class="dim-name">${name}</td>` +
        `<td class="dim-score">-</td>` +
        `<td class="dim-weight">-</td>` +
        `<td class="dim-contrib">-</td>` +
        `<td class="dim-hit">无数据</td>` +
      `</tr>`;
    }
    const hitFlag = hit && hit.hit;
    const hitCls = hitFlag ? (side === "high" ? "hit-high" : "hit-low") : "";
    return `<tr class="lab-custom-dim-row ${hitCls}">` +
      `<td class="dim-k">${k}</td>` +
      `<td class="dim-name">${name}</td>` +
      `<td class="dim-score">${score != null ? Number(score).toFixed(2) : "-"}</td>` +
      `<td class="dim-weight">${hit ? (hit.weight * 100).toFixed(0) + "%" : "-"}</td>` +
      `<td class="dim-contrib">${hit ? hit.contribution.toFixed(2) : "-"}</td>` +
      `<td class="dim-hit">${hitFlag ? "✓ 命中" : "未命中"}</td>` +
    `</tr>`;
  }

  let highRows = "";
  for (let i = 1; i <= 8; i++) highRows += rowHTML("H" + i, "high");
  let lowRows = "";
  for (let i = 1; i <= 8; i++) lowRows += rowHTML("L" + i, "low");

  const head = `<tr><th>维度</th><th>名称</th><th>分值</th><th>权重</th><th>贡献</th><th>命中</th></tr>`;
  return `<div class="lab-custom-dims lab-custom-block-gap">` +
    `<div class="lab-custom-section-title">🔬 8+8 维度拆解（高位预警 H1-H8 + 低位机会 L1-L8）</div>` +
    `<div class="lab-custom-dims-grid">` +
      `<div class="lab-custom-dims-col">` +
        `<div class="lab-custom-dims-col-title danger">高位预警维度（分高=危险）</div>` +
        `<table class="lab-custom-dims-table"><thead>${head}</thead><tbody>${highRows}</tbody></table>` +
      `</div>` +
      `<div class="lab-custom-dims-col">` +
        `<div class="lab-custom-dims-col-title good">低位机会维度（分高=机会）</div>` +
        `<table class="lab-custom-dims-table"><thead>${head}</thead><tbody>${lowRows}</tbody></table>` +
      `</div>` +
    `</div>` +
  `</div>`;
}

// 历史类比 Top3 + 统计 + 人话解读
function _labCustomHistoryHTML(historyAnalogy, humanText) {
  historyAnalogy = historyAnalogy || {};
  humanText = humanText || {};

  function sideHTML(side, label) {
    const ha = historyAnalogy[side];
    if (!ha || !ha.matches || !ha.matches.length) {
      return `<div class="lab-custom-hist-col">` +
        `<div class="lab-custom-hist-col-title">${label}</div>` +
        `<div class="lab-custom-hist-empty">无历史相似时段（样本不足）</div>` +
      `</div>`;
    }
    const stats = ha.stats || {};
    const curDate = ha.cur_date || "";
    const curDateStr = curDate && curDate.length === 8 ? `${curDate.slice(0,4)}-${curDate.slice(4,6)}-${curDate.slice(6,8)}` : curDate;
    const winN = stats.n_total_10d != null ? stats.n_total_10d : "";
    const upN = stats.n_up_10d != null ? stats.n_up_10d : "";
    const downN = stats.n_down_10d != null ? stats.n_down_10d : "";
    const ratioTxt = (upN !== "" && winN !== "" && winN > 0) ? `涨${upN}/跌${downN}/共${winN}` : "";

    const rows = ha.matches.map((m) => {
      const md = m.date || "";
      const mdStr = md && md.length === 8 ? `${md.slice(0,4)}-${md.slice(4,6)}-${md.slice(6,8)}` : md;
      const ret5 = m.forward_returns && m.forward_returns.ret_5d != null ? m.forward_returns.ret_5d : null;
      const ret10 = m.forward_returns && m.forward_returns.ret_10d != null ? m.forward_returns.ret_10d : null;
      const ret20 = m.forward_returns && m.forward_returns.ret_20d != null ? m.forward_returns.ret_20d : null;
      const retCls = (r) => r == null ? "ret-na" : (r >= 0 ? "ret-up" : "ret-down");
      const retStr = (r) => r == null ? "-" : (r >= 0 ? "+" : "") + r.toFixed(2) + "%";
      return `<tr>` +
        `<td class="hist-date">${mdStr}</td>` +
        `<td class="hist-sim">${(m.combined != null ? m.combined * 100 : 0).toFixed(1)}%</td>` +
        `<td class="hist-ret ${retCls(ret5)}">${retStr(ret5)}</td>` +
        `<td class="hist-ret ${retCls(ret10)}">${retStr(ret10)}</td>` +
        `<td class="hist-ret ${retCls(ret20)}">${retStr(ret20)}</td>` +
      `</tr>`;
    }).join("");
    const avg5 = stats.avg_ret_5d, avg10 = stats.avg_ret_10d, avg20 = stats.avg_ret_20d;
    const avgCls = (r) => r == null ? "ret-na" : (r >= 0 ? "ret-up" : "ret-down");
    const avgStr = (r) => r == null ? "-" : (r >= 0 ? "+" : "") + r.toFixed(2) + "%";

    const human = humanText[side] || "";

    return `<div class="lab-custom-hist-col">` +
      `<div class="lab-custom-hist-col-title">${label} <span class="lab-custom-hist-cur">基准日 ${curDateStr} · 样本窗 ${ha.window_days || ""} 日</span></div>` +
      `<div class="lab-custom-hist-stats">` +
        `<span class="hist-stat">平均 <b>5日</b> <span class="${avgCls(avg5)}">${avgStr(avg5)}</span></span>` +
        `<span class="hist-stat">平均 <b>10日</b> <span class="${avgCls(avg10)}">${avgStr(avg10)}</span></span>` +
        `<span class="hist-stat">平均 <b>20日</b> <span class="${avgCls(avg20)}">${avgStr(avg20)}</span></span>` +
        (ratioTxt ? `<span class="hist-stat hist-ratio">10日涨跌比 ${ratioTxt}</span>` : "") +
      `</div>` +
      `<table class="lab-custom-hist-table">` +
        `<thead><tr><th>历史日期</th><th>相似度</th><th>5日涨跌</th><th>10日涨跌</th><th>20日涨跌</th></tr></thead>` +
        `<tbody>${rows}</tbody>` +
      `</table>` +
      (human ? `<div class="lab-custom-human-text">${human}</div>` : "") +
    `</div>`;
  }

  return `<div class="lab-custom-hist lab-custom-block-gap">` +
    `<div class="lab-custom-section-title">📜 历史类比 前3（相似特征时段后续涨跌统计）</div>` +
    `<div class="lab-custom-hist-grid">` +
      sideHTML("high", "高位预警视角") +
      sideHTML("low", "低位机会视角") +
    `</div>` +
  `</div>`;
}

// 数据阈值表(默认折叠)
function _labCustomThresholdsHTML(dataThresholds) {
  dataThresholds = dataThresholds || {};
  function sideRows(side) {
    const arr = dataThresholds[side] || [];
    return arr.map((t) => {
      const valStr = t.value != null ? (Number(t.value).toFixed(2) + (t.unit || "")) : "-";
      const thrStr = t.threshold != null ? (Number(t.threshold).toFixed(2) + (t.unit || "")) : "-";
      const hitCls = t.hit ? (side === "high" ? "hit-high" : "hit-low") : (t.status === "无数据" ? "dim-na" : "");
      return `<tr class="lab-custom-thresh-row ${hitCls}">` +
        `<td class="th-k">${t.k}</td>` +
        `<td class="th-name">${t.name}</td>` +
        `<td class="th-val">${valStr}</td>` +
        `<td class="th-thr">${thrStr}</td>` +
        `<td class="th-status">${t.status || ""}</td>` +
        `<td class="th-desc">${t.desc || ""}</td>` +
      `</tr>`;
    }).join("");
  }
  const head = `<tr><th>维度</th><th>名称</th><th>当前值</th><th>阈值</th><th>状态</th><th>说明</th></tr>`;
  return `<div class="lab-custom-thresh lab-custom-block-gap">` +
    `<button type="button" class="lab-custom-thresh-toggle">展开数据阈值表 ▾</button>` +
    `<div class="lab-custom-thresh-body" style="display:none">` +
      `<div class="lab-custom-thresh-grid">` +
        `<div class="lab-custom-thresh-col">` +
          `<div class="lab-custom-thresh-col-title danger">高位预警阈值</div>` +
          `<table class="lab-custom-thresh-table"><thead>${head}</thead><tbody>${sideRows("high")}</tbody></table>` +
        `</div>` +
        `<div class="lab-custom-thresh-col">` +
          `<div class="lab-custom-thresh-col-title good">低位机会阈值</div>` +
          `<table class="lab-custom-thresh-table"><thead>${head}</thead><tbody>${sideRows("low")}</tbody></table>` +
        `</div>` +
      `</div>` +
    `</div>` +
  `</div>`;
}

// 合规底栏
function _labCustomFooterHTML(complianceFooter, noDataHint) {
  const foot = complianceFooter || "⚠️ 本分析基于历史数据统计，仅供学习参考，不构成投资建议或交易指令，市场有风险，决策需谨慎。";
  return `<div class="lab-custom-footer lab-custom-block-gap">` +
    `<div class="lab-custom-footer-text">${foot}</div>` +
    (noDataHint ? `<div class="lab-custom-footer-hint">${noDataHint}</div>` : "") +
  `</div>`;
}

// 批次2b:仓位计算依据(6维度综合分 v5 透明化)
// pos = alert.position = {hands, volatility, label, detail}
// detail 含 opp/trend/mom/vol/liq/draw(分值0-100) + score(综合分) + 原始值(ma60_ratio/macd_hist/volatility/amt_pct/drawdown)
function _labCustomPositionDetailHTML(pos) {
  if (!pos || !pos.detail) {
    return `<div class="lab-custom-position">` +
      `<div class="lab-custom-section-title">📐 仓位计算依据</div>` +
      `<div class="lab-custom-position-empty">仓位数据不足(后端 position 未生成)</div>` +
    `</div>`;
  }
  const d = pos.detail;
  const f2 = (v) => (v != null ? Number(v).toFixed(2) : "-");
  // 6维度:[key, 名称, 原始值文案, 权重]
  const dims = [
    ["opp", "机会分", `low_alert = ${f2(d.opp)}`, 0.35],
    ["trend", "趋势分", `MA60比 = ${f2(d.ma60_ratio)}`, 0.20],
    ["mom", "动量分", `MACD hist = ${f2(d.macd_hist)}`, 0.15],
    ["vol", "波动分", `ATR/close = ${f2(d.volatility)}%`, 0.15],
    ["liq", "流动性", `成交额分位 = ${f2(d.amt_pct)}%`, 0.05],
    ["draw", "回撤分", `252日回撤 = ${f2(d.drawdown)}%`, 0.10],
  ];
  const rows = dims.map(([k, name, rawText, w]) => {
    const score = d[k] != null ? Number(d[k]) : null;
    const contrib = score != null ? score * w : null;
    return `<tr class="lab-custom-dim-row">` +
      `<td class="dim-name">${name}</td>` +
      `<td class="dim-raw">${rawText}</td>` +
      `<td class="dim-score">${score != null ? f2(score) : "-"}</td>` +
      `<td class="dim-weight">${(w * 100).toFixed(0)}%</td>` +
      `<td class="dim-contrib">${contrib != null ? contrib.toFixed(2) : "-"}</td>` +
    `</tr>`;
  }).join("");
  const score = d.score != null ? Number(d.score) : null;
  const head = `<tr><th>维度</th><th>原始值</th><th>分值</th><th>权重</th><th>贡献</th></tr>`;
  const totalRow = `<tr class="lab-custom-position-total">` +
    `<td class="dim-name">综合分</td><td class="dim-raw">-</td>` +
    `<td class="dim-score"><b>${score != null ? score.toFixed(2) : "-"}</b></td>` +
    `<td class="dim-weight">100%</td>` +
    `<td class="dim-contrib"><b>${score != null ? score.toFixed(2) : "-"}</b></td>` +
  `</tr>`;
  // 档位映射
  const tier = pos.hands != null ? pos.hands : null;
  const tierText = tier === 3 ? "3手(重仓)" : tier === 2 ? "2手(半仓)" : tier === 1 ? "1手(轻仓)" : "0手(观望)";
  return `<div class="lab-custom-position">` +
    `<div class="lab-custom-section-title">📐 仓位计算依据(6维度综合分 v5)</div>` +
    `<div class="lab-custom-position-score-row">` +
      `<span class="lab-custom-position-score-label">综合分</span>` +
      `<span class="lab-custom-position-score-val">${score != null ? score.toFixed(2) : "-"}</span>` +
      `<span class="lab-custom-position-tier">当前档位:${tierText}</span>` +
    `</div>` +
    `<div class="lab-custom-position-formula">` +
      `公式:0.35×机会 + 0.20×趋势 + 0.15×动量 + 0.15×波动 + 0.05×流动性 + 0.10×回撤 = ` +
      `<b>${score != null ? score.toFixed(2) : "-"}</b>` +
    `</div>` +
    `<table class="lab-custom-dims-table lab-custom-position-table">` +
      `<thead>${head}</thead><tbody>${rows}${totalRow}</tbody>` +
    `</table>` +
    `<div class="lab-custom-position-rules">` +
      `<div class="lab-custom-position-sub-title">档位映射规则</div>` +
      `<ul>` +
        `<li>低机会(<b>low_alert &lt; 35</b>):直接 0手(观望,如国债/海外指数无 A股低位机会)</li>` +
        `<li>综合分 ≥ <b>60</b>:3手(重仓)</li>` +
        `<li>综合分 ≥ <b>50</b>:2手(半仓)</li>` +
        `<li>综合分 ≥ <b>40</b>:1手(轻仓)</li>` +
        `<li>其他:0手(观望)</li>` +
      `</ul>` +
    `</div>` +
    `<div class="lab-custom-position-notes">` +
      `<div class="lab-custom-position-sub-title">各维度算法</div>` +
      `<ul>` +
        `<li><b>机会分</b>(权重35%):low_alert 低位机会,L1-L8 多维加权(0-100),主导仓位</li>` +
        `<li><b>趋势分</b>(20%):close/MA60 偏离度。&gt;1.10→100,&gt;1.05→85,&gt;1.00→70,&gt;0.95→40,&gt;0.90→20,else→0</li>` +
        `<li><b>动量分</b>(15%):MACD hist(DIF-DEA)×2。正且上升→100,正→70,负但上升→40,负→10</li>` +
        `<li><b>波动分</b>(15%):ATR(20)/close×100。≤1.5%→100,≤2.5%→85,≤3.5%→70,≤4.5%→50,≤5.5%→30,&gt;5.5%→10(低波动高分)</li>` +
        `<li><b>流动性</b>(5%):近60日成交额分位。&gt;80%→100,&gt;50%→80,&gt;20%→60,else→40</li>` +
        `<li><b>回撤分</b>(10%):相对252日最高价回撤。&gt;40%→100,&gt;25%→85,&gt;15%→70,&gt;5%→50,else→20(深回撤=低位机会)</li>` +
      `</ul>` +
    `</div>` +
    `<div class="lab-custom-position-backtest">` +
      `<b>回测验证</b>(2026-07-24,v5公式):50 ETF + 120日截尾均值,5/10/20日 hands=3 &gt; hands=1。` +
      `历史回测用 position 分位+RSI 代理 low_alert(真实历史未存),实际效果应优于回测。` +
      `核心价值:区分度(buy_list 3手 80%→15%,有加有砍),非预测未来收益。` +
    `</div>` +
    `<div class="lab-custom-position-disclaimer">` +
      `⚠️ 免责声明:本仓位建议为研究参考,非投资建议。市场有风险,投资需谨慎。` +
    `</div>` +
  `</div>`;
}

// === 场景B重构(B1): purpose-note 通用渲染函数 ===
// 统一 home(app.js 原 insertAdjacentHTML '<div class="home-purpose-note">') + lab(lab.js 原 createElement+className="lab-purpose-note") 两套写法
// variant:
//   "home" / undefined -> 基础类 "purpose-note"(home 尺寸:padding 12px16px/font 13.5px/line-height 1.7,3皮肤用主色变量自动适配)
//   "lab-sm"           -> "purpose-note lab-sm"(lab 小字号修饰:padding 10px14px/font 12.5px/line-height 1.6)
// 文案由 PURPOSE_NOTES(purpose-notes.js)集中配置,调用方传 PURPOSE_NOTES[key]
// 返回创建的 div 元素;text 为空/undefined 则不渲染返回 null(防 key 拼错出空框)
function renderPurposeNote(container, text, {variant}={}) {
  if (!text) return null;
  const el = document.createElement("div");
  el.className = variant === "lab-sm" ? "purpose-note lab-sm" : "purpose-note";
  el.innerHTML = text;
  if (container) container.appendChild(el);
  return el;
}

// === AI仓位建议 K 档评级(2026-08-13 共享单一数据源, §22 一致性: app.js 首页 + lab.js 凯利区两处共用同一份数据/HTML/绑定) ===
// 2026-08-14 #48+#BC: 静态快照由 fixed(每笔1万)/比例法 重算为每日池口径 + 费率重算口径(含最低佣金5元), 与动态重算 _kellyApplyFeeRecompute 数值一致(§22 消除 12.7pt 佣金低估差)
// 口径=AI降亏过滤默认=AI宏5+3+1(5=基础5: n2NovSpecialIndustry/excludeSpecialBear四档/janMidRating/janMidSpecial + K2C5 港股追涨剔除(v1.1.2 2026-08-17 excludeSpecialBear MA60→四档升级, 老MA60熊/下降期两备选默认关带🆕NEW); 3=核心3保留入样: r7 5月强化+3稳定非5月 / exclAuxCross 辅关注×3/5月交叉 / greedy15 Greedy-15组合等; +1=回测剔除波动相关/未入样本信号)+A模式(固定10天)+每日资金池等分+top-K+费率etf_def(含min_commission=5元)+全周期+费率重算
// 数值来源: Node 复算前端 _kellyApplyFeeRecompute 动态链路(lab.js 实际函数, 逐位一致), 数据 generated_at 2026-08-14 02:22; 主推 K1(收益率最高 86.60%)
var _AI_POSCAP_RATING = {
  1: { name: "最激进", ret: "86.60%", dd: "15.99%", ra: "5.42", n: "1,202", reason: "收益率最高+回撤最小+样本最少,主推★" },
  2: { name: "次稳健", ret: "67.61%", dd: "18.64%", ra: "3.63", n: "1,930", reason: "收益率最低+回撤最大" },
  3: { name: "最稳健", ret: "66.24%", dd: "16.19%", ra: "4.09", n: "2,461", reason: "回撤第二大+收益率第三(收益/回撤较优)" },
  4: { name: "最保守", ret: "63.17%", dd: "17.84%", ra: "3.54", n: "2,870", reason: "收益率第二低+回撤第二大+样本最多" }
};
// #54 2026-08-13 动态化: 共享动态源(由 lab.js _kellyApplyFeeRecompute 在 AI仓位建议开启时用当前 filters+费率+最新数据重算写入)
// 结构: { computed:bool, date:数据日期, fee:费率档标签, cfg:降亏勾选摘要, values:{1..4:{name,ret,dd,ra,n,reason?,retNum,ddNum,nNum}} }
// 首页 app.js 与凯利区 lab.js 均经 _aiPoscapRatingSrc() 取源(§22 两处一致); 无动态值(未开启 positionCap/未计算)→回退静态快照 _AI_POSCAP_RATING
var _AI_POSCAP_RATING_DYNAMIC = null;
window._AI_POSCAP_RATING_DYNAMIC = _AI_POSCAP_RATING_DYNAMIC;

// 取当前评级数据源: 动态优先(已计算且 positionCap 当前开启), 否则回退静态快照(标注"快照 08-13")
function _aiPoscapRatingSrc() {
  var d = window._AI_POSCAP_RATING_DYNAMIC;
  var pcOn = true;
  try {
    var _raw = localStorage.getItem("tds_poscap");
    if (_raw) { var _p = JSON.parse(_raw); pcOn = !!_p.on; }
  } catch (e) {}
  if (d && d.computed && d.values && pcOn) return { dynamic: true, src: d };
  return { dynamic: false, src: _AI_POSCAP_RATING };
}
// 动态评级理由派生(收益率最高/回撤最小/样本最少/主推; 静态快照自带 reason 不走此函数); 主推 K1(收益率最高)
function _aiPoscapRatingReasonFor(k, vals) {
  var retMaxK = 1, ddMinK = 1, nMinK = 1, i;
  for (i = 1; i <= 4; i++) {
    if (!vals[i]) continue;
    if (vals[i].retNum > vals[retMaxK].retNum) retMaxK = i;
    if (vals[i].ddNum < vals[ddMinK].ddNum) ddMinK = i;
    if (vals[i].nNum < vals[nMinK].nNum) nMinK = i;
  }
  var parts = [];
  if (k === retMaxK) parts.push("收益率最高");
  if (k === ddMinK) parts.push("回撤最小");
  if (k === nMinK) parts.push("样本最少");
  if (k === 1) parts.push("主推★(收益率最高)");
  if (!parts.length) parts.push("收益回撤居中");
  return parts.join("+");
}
// 生成 K 档评级一行摘要(凯利区 positionCap label data-tip 复用; 与 hoverpop 表同源 §22)
function _aiPoscapRatingSummary() {
  var s = _aiPoscapRatingSrc();
  var vals = s.src.values || _AI_POSCAP_RATING;
  var parts = [1, 2, 3, 4].map(function (k) {
    var r = vals[k];
    if (!r) return "";
    return 'K=' + k + ' ' + r.name + ' 收益率' + r.ret + '/峰值资金回撤' + r.dd + '/样本' + r.n;
  }).filter(Boolean);
  return parts.join('; ') + (s.dynamic
    ? ('（实时·当前配置/费率/数据' + (s.src.date ? ' ' + s.src.date : '') + '）')
    : '（快照 08-14·每日池+费率重算口径(含最低佣金5元): AI降亏过滤默认 AI宏5+3+1(5基础+3核心保留入样 + 1回测剔除波动相关/未入样本信号)+每日资金池等分+top-K, 主推K1; 当前未开启AI仓位建议或未重算）');
}
// K 档评级 hoverpop 表格 HTML(1 排首位, K=1 高亮主推; app.js/lab.js 两处共用同一份, 数据源=动态优先/静态快照回退, 勿单改数值)
function _aiPoscapRatingPopHtml() {
  var s = _aiPoscapRatingSrc();
  var vals = s.src.values || _AI_POSCAP_RATING;
  var rows = [1, 3, 4, 2].map(function (k) {
    var r = vals[k];
    if (!r) return "";
    var reason = r.reason || _aiPoscapRatingReasonFor(k, vals);
    return '<tr' + (k === 1 ? ' class="lab-sigkelly-posrate-hl"' : '') + '><td><b>K=' + k + '</b> ' + r.name + (k === 1 ? ' ★主推' : '') + '</td><td>' + r.ret + '</td><td>' + r.dd + '</td><td>' + r.ra + '</td><td>' + r.n + '</td><td>' + reason + '</td></tr>';
  }).join("");
  var srcLabel = s.dynamic
    ? '📌 实时·当前配置/费率/数据(' + (s.src.date || '-') + (s.src.fee ? ' · 费率' + s.src.fee : '') + ')：随上方降亏勾选 / 费率档 / 最新数据联动重算(展示层动态化, 未改算法)'
    : '📌 快照 08-14：每日池+费率重算口径(2026-08-14 #48+#BC) = AI降亏过滤默认 AI宏5+3+1(基础5+核心3保留入样 + 1回测剔除波动相关/未入样本信号) + A模式(固定10天) + 每日资金池等分+top-K + 费率etf_def(含最低佣金5元) + 全周期。当前未开启 AI仓位建议 或尚未重算, 显示静态快照';
  return '<span class="lab-sigkelly-posrate-pop-wrap">' +
    '<div class="lab-sigkelly-posrate-pop">' +
      '<div class="lab-sigkelly-posrate-pop-title">AI仓位建议 · K 档位评级（评级依据=下方回撤矩阵）</div>' +
      '<table class="lab-sigkelly-posrate-table"><thead><tr><th>档位</th><th>收益率</th><th>峰值资金回撤</th><th>风险调整<br>(收益/回撤)</th><th>样本</th><th>评级理由</th></tr></thead><tbody>' + rows + '</tbody></table>' +
      '<div class="lab-sigkelly-posrate-pop-note">⚠ 口径：动态=当前降亏勾选(AI降亏过滤 8 键或用户自定义) + A模式(固定10天) + 每日资金池等分+top-K + 当前费率档(默认etf_def含最低佣金5元) + 最新数据全周期；静态快照=同上默认配置+费率重算口径(2026-08-14 #48+#BC, 含最低佣金5元, 与动态一致§22)。与「历史回测数据」G模式口径不同，勿混用数值。峰值资金回撤=最大回撤金额÷本金(concCap, 峰值同时持仓资金；与回测报告 ddPct=最大回撤÷资金池 口径不同, 数值勿直接对照)</div>' +
      '<div class="lab-sigkelly-posrate-pop-note"><b>K 档到底在选什么（举个 1:1 例子）</b>：每日资金池=每天总共投入 1 万，均分给当日保留的前 K 个信号。选 <b>K1</b>=当天只买最优的那 1 个信号，单笔就是 1 万（全押 1 个，持仓最集中）→ 收益率最高 <b>86.6%</b>；选 <b>K3</b>=当天买最优的 3 个信号，每个 10000÷3≈<b>3333 元</b>（鸡蛋分 3 篮子，持仓更分散）→ 收益率降到 <b>66.2%</b>。价格：K 越大越分散、单日冲高收益越低，但波动和风险也摊薄——想要集中吃大肉就 K1（主推★），想要分散稳健就调大 K。<i>核实源=common.js _AI_POSCAP_RATING 快照(K1 86.60% / K3 66.24%, 2026-08-14 每日池+费率重算口径)</i></div>' +
      '<div class="lab-sigkelly-posrate-pop-note">' + srcLabel + '</div>' +
    '</div>' +
  '</span>';
}
// 绑定 AI仓位建议 K 档评级 hoverpop(桌面 hover / 移动端 tap 切换; 自包含定位, 不依赖 lab.js; 与凯利区原 _bindSigKellyPosRatePop 同款逻辑)
// container: 包含 .lab-sigkelly-posrate(trigger) 的容器(首页 sigCard / 凯利区 bar), 全站两处共用
function _bindAiPoscapRatePop(container) {
  if (!container) return;
  var isTouch = window.matchMedia && window.matchMedia("(hover: none)").matches;
  container.querySelectorAll(".lab-sigkelly-posrate").forEach(function (trig) {
    var pop = trig.querySelector(".lab-sigkelly-posrate-pop-wrap");
    if (!pop) return;
    var openByClick = false;
    var show = function () {
      pop.style.display = "block";
      // 定位(同 lab.js _positionSigKellyWmPop): left 相对 trig, 右越界左移但不超左边界
      var pw = pop.offsetWidth;
      var tr = trig.getBoundingClientRect();
      var left = Math.min(0, window.innerWidth - 8 - pw - tr.left);
      left = Math.max(left, 8 - tr.left);
      pop.style.left = left + "px";
    };
    var hide = function () { pop.style.display = "none"; pop.style.left = ""; };
    trig.addEventListener("mouseenter", function () { if (!openByClick) show(); });
    trig.addEventListener("mouseleave", function () { if (!openByClick) hide(); });
    trig.addEventListener("click", function (e) {
      // 2026-08-13 fix(reviewer C1): K/off 按钮点击不再被无条件 stopPropagation 拦截——
      // 首页 .sig-kbtn 是 trigger(.lab-sigkelly-posrate) 的子元素, 事件需冒泡到 sigCard 级委托(_bindSigSwitchRow)才生效;
      // 凯利区 .lab-sigkelly-kbtn 用直接 btn.onclick(target 先执行), 但为一致与稳妥一并放过。
      var t = e.target;
      if (t && t.closest && (t.closest(".sig-kbtn") || t.closest(".lab-sigkelly-kbtn"))) return;
      e.stopPropagation();
      if (isTouch) {
        openByClick = pop.style.display !== "block";
        if (openByClick) show(); else hide();
      }
    });
  });
  // 移动端: 点别处/滚动关闭所有评级 pop(全局绑一次)
  if (isTouch && !document._aiPoscapRateDocBound) {
    document._aiPoscapRateDocBound = true;
    document.addEventListener("click", function (e) {
      if (e.target.closest && e.target.closest(".lab-sigkelly-posrate")) return;
      document.querySelectorAll(".lab-sigkelly-posrate-pop-wrap").forEach(function (p) {
        if (p.style.display === "block") { p.style.display = "none"; p.style.left = ""; }
      });
    }, true);
    window.addEventListener("scroll", function () {
      document.querySelectorAll(".lab-sigkelly-posrate-pop-wrap").forEach(function (p) {
        if (p.style.display === "block") { p.style.display = "none"; p.style.left = ""; }
      });
    }, { passive: true, capture: true });
  }
}

// === 挂到 window,供 lab.js / app.js 跨文件引用 ===
window._AI_POSCAP_RATING = _AI_POSCAP_RATING;
window._AI_POSCAP_RATING_DYNAMIC = _AI_POSCAP_RATING_DYNAMIC;
window._aiPoscapRatingPopHtml = _aiPoscapRatingPopHtml;
window._aiPoscapRatingSummary = _aiPoscapRatingSummary;
window._aiPoscapRatingSrc = _aiPoscapRatingSrc;
window._bindAiPoscapRatePop = _bindAiPoscapRatePop;
window._LAB_CUSTOM_BROAD = _LAB_CUSTOM_BROAD;
window._LAB_CUSTOM_SW = _LAB_CUSTOM_SW;
window._LAB_CUSTOM_DIV = _LAB_CUSTOM_DIV;
window._LAB_CUSTOM_HK = _LAB_CUSTOM_HK;
window._LAB_CUSTOM_GLOBAL = _LAB_CUSTOM_GLOBAL;
window._labCustomCacheBust = _labCustomCacheBust;
window._labCustomLevelClass = _labCustomLevelClass;
window._labCustomLevelText = _labCustomLevelText;
window._labCustomLevelTooltip = _labCustomLevelTooltip;
window._labCustomDefaultHuman = _labCustomDefaultHuman;
window._labCustomScoreSummary = _labCustomScoreSummary;
window._labCustomScoreCardHTML = _labCustomScoreCardHTML;
window._labCustomDimsTableHTML = _labCustomDimsTableHTML;
window._labCustomHistoryHTML = _labCustomHistoryHTML;
window._labCustomThresholdsHTML = _labCustomThresholdsHTML;
window._labCustomFooterHTML = _labCustomFooterHTML;
window._labCustomPositionDetailHTML = _labCustomPositionDetailHTML;
window.renderPurposeNote = renderPurposeNote;

// ===== T3-1(2026-08-23) AI降亏·老37键规格单源 + 7模式预设(common.js 两页常载单源) =====
// 【为什么放 common.js】lab.min.js 由 app 动态注入(lab tab), 首页模拟回测弹窗场景 lab.js 不在场;
//   index.html 常载 common.min.js → 规格层/评估器/模式预设只有这里能让 lab 与弹窗两消费点同源(§22)。
// 【为什么内嵌常量而非走 meta.rules(kelly_loss_features.json)】现状老37键=硬编码谓词零异步依赖;
//   若改读远程 JSON, R2/CF 拉取失败=AI降亏整体失效, 引入新生产故障面违反 §23.7。T1 20新键通道
//   (meta.rules)保持不动; 本表与 meta.rules 同为 spec-driven 风格, 未来后端 per-mode(T3-2)可对齐。
// 【迁移一致性】本表由 lab.js/app.js 旧硬编码谓词逐条转录(scripts/check_fade_predicate_parity.mjs
//   断言迁移前后全量行×57键命中集合逐位一致); 月门 mask 表(_kellyMonthMask/_simMonthMask)保留原值
//   不从规格派生(greedy7 的 q2 组件隐含季度展开成手工 mask, 派生会变宽改变行为)。
// ctx 字段约定: sig/mm/wd/bpb/q/ts/mktD/ratD/etfD = lab _kellyTradeFeatures feats 同名;
//   dd=日; tier/tierAll/tierCyb/rating/mstate = trades 原始字段(market_tier/market_tier_all/
//   market_tier_cyb/rating/market_state)。组件内各条件 AND, any 数组内组件 OR。
var _KELLY_FADE_LEGACY_SPECS = {
  // ---- 前置简单键(gate=0, 判定不进月门块, 输入=trades 原始字段组装的 ctx) ----
  excludeAux:            { gate: 0, any: [{ sig: "buy_aux" }] },
  marketTiming:          { gate: 0, any: [{ mstateNotTrue: 1 }] },
  excludeMonth:          { gate: 0, any: [{ mmIn: ["03", "05"] }] },
  excludeRatingLow:      { gate: 0, any: [{ ratingIsLow: 1 }] },
  excludeAuxCross:       { gate: 0, any: [{ sig: "buy_aux", mmIn: ["03", "05"] }] },
  excludeSpecialBear:    { gate: 0, any: [{ sig: "buy_special", tierIn: ["熊市·主跌", "下降期"] }] },
  legacyMa60Special:     { gate: 0, any: [{ sig: "buy_special", mstateFalse: 1 }] },
  declinePhaseSpecial:   { gate: 0, any: [{ sig: "buy_special", tierAll: "下降期" }] },
  excludeSpecialBearCyb: { gate: 0, any: [{ sig: "buy_special", tierCybIn: ["熊市·主跌", "下降期"] }] },
  bullAuxBackupStop:     { gate: 0, any: [{ sigIn: ["buy_aux", "buy_backup"], tier: "牛市·主升" }] },
  // ---- 门控块键(gate=1, v3/v4/r3/jan/k2 五组共享月门短路, 输入=feats 缓存对象) ----
  n1MarTueHigh:          { gate: 1, any: [{ mm: "03", wd: 2, bpb: "high" }] },
  n2NovSpecialIndustry:  { gate: 1, any: [{ sig: "buy_special", mm: "11", mkt: "industry" }] },
  r8PureNonMay:          { gate: 1, any: [{ mm: "03", wd: 2, bpb: "high" }, { sig: "buy_special", mm: "11", mkt: "industry" }, { sig: "buy_special", mm: "11", wd: 0 }] },
  n3NovSpecialMon:       { gate: 1, any: [{ sig: "buy_special", mm: "11", wd: 0 }] },
  n4AMay:                { gate: 1, any: [{ mkt: "a", mm: "05" }] },
  r7MayReinforced:       { gate: 1, any: [{ mkt: "a", mm: "05" }, { rat: "mid", mm: "05" }, { mm: "05", bpb: "vlow" }, { mm: "03", wd: 2, bpb: "high" }, { sig: "buy_special", mm: "11", mkt: "industry" }, { sig: "buy_special", mm: "11", wd: 0 }] },
  n5MayVlow:             { gate: 1, any: [{ mm: "05", bpb: "vlow" }] },
  n6MidMay:              { gate: 1, any: [{ rat: "mid", mm: "05" }] },
  r10May6NonMay:         { gate: 1, any: [{ mm: "05" }, { mm: "03", wd: 2, bpb: "high" }, { sig: "buy_special", mm: "11", mkt: "industry" }, { sig: "buy_special", mm: "11", wd: 0 }, { sig: "buy_special", mm: "11", bpb: "low" }, { sig: "buy_special", mm: "03", mkt: "industry" }, { mm: "03", wd: 2, sig: "buy_aux" }] },
  v4cSimple:             { gate: 1, any: [{ mm: "03", wd: 2, sig: "buy_aux" }] },
  v4b:                   { gate: 1, any: [{ mkt: "a", mm: "05", sig: "buy_special", etf: "related" }] },
  greedy7:               { gate: 1, any: [{ sig: "buy_special", mm: "05" }, { sig: "buy_special", mm: "11", mkt: "concept" }, { sig: "buy_special", mm: "03" }, { sig: "buy_aux", mm: "01" }, { q: 2, bpb: "vlow", sig: "buy_aux", mkt: "concept" }, { sig: "buy", mm: "01" }, { mm: "03", wd: 2, mkt: "concept", rat: "low" }] },
  v4d:                   { gate: 1, any: [{ mm: "12", wd: 1, sig: "buy_aux", tsMax: 50 }] },
  v4j:                   { gate: 1, any: [{ mm: "05", bpb: "vlow", sig: "buy_special" }] },
  v4i:                   { gate: 1, any: [{ sig: "buy_special", mm: "05", mkt: "concept", wd: 0 }] },
  greedy10:              { gate: 1, any: [{ sig: "buy_special", mm: "05" }, { sig: "buy_special", mm: "11", mkt: "concept" }, { sig: "buy_special", mm: "03" }, { sig: "buy_aux", mm: "01" }, { q: 2, bpb: "vlow", sig: "buy_aux", mkt: "concept" }, { sig: "buy", mm: "01" }, { mm: "03", wd: 2, mkt: "concept", rat: "low" }, { sig: "buy_aux", mm: "12", tsMax: 50 }, { mm: "06", bpb: "vlow", rat: "low" }, { sig: "buy_aux", mm: "05" }] },
  v4f:                   { gate: 1, any: [{ sig: "buy", mm: "06", wd: 2, etf: "related" }] },
  v4g:                   { gate: 1, any: [{ mkt: "global", q: 1, sig: "buy_aux", rat: "low" }] },
  v4m:                   { gate: 1, any: [{ sig: "buy_special", mm: "09", wd: 2 }] },
  v4k:                   { gate: 1, any: [{ sig: "buy", mm: "01", bpb: "high" }] },
  greedy15:              { gate: 1, any: [{ sig: "buy_special", mm: "05" }, { sig: "buy_special", mm: "11", mkt: "concept" }, { sig: "buy_special", mm: "03" }, { sig: "buy_aux", mm: "01" }, { q: 2, bpb: "vlow", sig: "buy_aux", mkt: "concept" }, { sig: "buy", mm: "01" }, { mm: "03", wd: 2, mkt: "concept", rat: "low" }, { sig: "buy_aux", mm: "12", tsMax: 50 }, { mm: "06", bpb: "vlow", rat: "low" }, { sig: "buy_aux", mm: "05" }, { sig: "buy_special", mm: "11", mkt: "industry" }, { mm: "04", wd: 1, mkt: "concept", tsMax: 50 }, { mkt: "global", q: 1, sig: "buy_aux", rat: "low" }, { mm: "01", bpb: "low", sig: "buy_special", mkt: "concept" }, { sig: "buy_special", mm: "09", wd: 2 }] },
  a5NovMidSpecial:       { gate: 1, any: [{ sig: "buy_special", mm: "11", ddMin: 11, ddMax: 20 }] },
  a45NovMidLateSpecial:  { gate: 1, any: [{ sig: "buy_special", mm: "11", ddMin: 11 }] },
  janMidRating:          { gate: 1, any: [{ mm: "01", ddMin: 11, ddMax: 20, rat: "mid" }] },
  janMidSpecial:         { gate: 1, any: [{ sig: "buy_special", mm: "01", ddMin: 11, ddMax: 20 }] },
  k2c5HkChase:           { gate: 1, any: [{ sigIn: ["buy_special", "buy_backup"], mkt: "hk" }] },
  k3ConceptBuy:          { gate: 1, any: [{ sig: "buy", mkt: "concept" }] }
};
var _KELLY_FADE_FRONT_KEY_ORDER = [
  "excludeAux", "marketTiming", "excludeMonth", "excludeRatingLow", "excludeAuxCross",
  "excludeSpecialBear", "legacyMa60Special", "declinePhaseSpecial", "excludeSpecialBearCyb",
  "bullAuxBackupStop"
];
var _KELLY_FADE_GATE_KEY_ORDER = [
  "n1MarTueHigh", "n2NovSpecialIndustry", "r8PureNonMay", "n3NovSpecialMon", "n4AMay",
  "r7MayReinforced", "n5MayVlow", "n6MidMay", "r10May6NonMay",
  "v4cSimple", "v4b", "greedy7", "v4d", "v4j", "v4i", "greedy10", "v4f", "v4g", "v4m", "v4k", "greedy15",
  "a5NovMidSpecial", "a45NovMidLateSpecial", "janMidRating", "janMidSpecial",
  "k2c5HkChase", "k3ConceptBuy"
];
function _tdsFadeSpecHit(key, c) {
  var sp = _KELLY_FADE_LEGACY_SPECS[key];
  if (!sp) return false;
  var arr = sp.any;
  for (var i = 0; i < arr.length; i++) {
    var p = arr[i];
    if (p.sig != null && c.sig !== p.sig) continue;
    if (p.sigIn != null && p.sigIn.indexOf(c.sig) < 0) continue;
    if (p.mm != null && c.mm !== p.mm) continue;
    if (p.mmIn != null && p.mmIn.indexOf(c.mm) < 0) continue;
    if (p.ddMin != null && !(c.dd >= p.ddMin)) continue;
    if (p.ddMax != null && !(c.dd <= p.ddMax)) continue;
    if (p.wd != null && c.wd !== p.wd) continue;
    if (p.bpb != null && c.bpb !== p.bpb) continue;
    if (p.q != null && c.q !== p.q) continue;
    if (p.tsMax != null && !(Number(c.ts) < p.tsMax)) continue;
    if (p.mkt != null && c.mktD !== p.mkt) continue;
    if (p.etf != null && c.etfD !== p.etf) continue;
    if (p.rat != null && c.ratD !== p.rat) continue;
    if (p.tier != null && c.tier !== p.tier) continue;
    if (p.tierIn != null && p.tierIn.indexOf(c.tier) < 0) continue;
    if (p.tierAll != null && c.tierAll !== p.tierAll) continue;
    if (p.tierCybIn != null && p.tierCybIn.indexOf(c.tierCyb) < 0) continue;
    if (p.ratingIsLow != null && c.rating !== "low") continue;
    if (p.mstateNotTrue != null && c.mstate === true) continue;
    if (p.mstateFalse != null && c.mstate !== false) continue;
    return true;
  }
  return false;
}

// ---- AI降亏 8 模式预设(权威=T2 卡 _KELLY_MODE_COMPARE_CARDS+mine24_compare.json; 文案从卡转录) ----
// keys 全部 ⊆ 58 键(FRONT 10 + GATE 27 + T1 20 + X1); caliber 口径标注随选项展示(A/B/C=叠9键 / NEW 族=换基座)。
// ⭐ v20260826(用户拍板, §23.7 已确认可改历史功能): ①预设新增 stars 字段(纯展示层=S06 3星/a9·new14·new15 2星/
//   p9·b9 1星/p8·c9 无星), 仅用于下拉「星多靠前、无星殿后(保持原相对序)」排序与前缀展示, 键集/判定/默认值零变化;
//   ②NEW2 18键(new18) 对照档从下拉移除(用户:"不用对照啦 14+1 对照够啦"): 仅删本表条目, 后端 RECENT_KEYS 打标集不动(自定义手勾键仍需打标);
//   【更新 2026-08-26】「🧩 AI 降亏组成对比」区 18键方案卡亦已移除(用户:"18和14键差异太小了...18不要了"), lab.js _KELLY_MODE_COMPARE_CARDS 同步删条目;
//   已存 new18 模式记忆的浏览器在四个消费点读取处经 _tdsFadeModeById 校验失败自动回默认(_KELLY_FADE_DEFAULT_MODE),
//   不空白不报错。下拉渲染顺序由 _tdsFadeModeDisplayList 统一给出(stars 稳定降序+原相对序兜底), 其余按 id 消费方不受影响。
// ⚠ v1.1.5(2026-08-24 用户拍板): 默认基座从 p8(8键, v1.1.2) 切换为 new14(NEW 14键)——依据 mine28(AUTO 轮动
//   样本外全 FAIL+天花板作弊仍输单持)+mine30 记分板(NEW14 全史第一 +122,648/mdd -4,178 vs 八键 +66,530/-18,190,
//   费后 K1 V2 回补 cap13 口径)。p8 保留为可手动选的对照档位不删(§23.7 只增不改精神: 老口径可回选)。
//   所有「null/缺失回退默认」消费点统一引用 _KELLY_FADE_DEFAULT_MODE 单源, 禁止各自硬编码 "p8"/"new14" 字面量。
var _KELLY_FADE_T1_KEYS = [
  "r2gLowRatingQ3", "n1NorthOutflow", "t1LowTurnSpecial", "d1LowDivYield", "q1QvixLowPct",
  "h1VolChgHighA", "m1MarginDownBull", "d2LowDivBull", "p1LowDivBackup", "v1HighVol20",
  "s1SentALow", "r1VolRatioLow", "r2bSpecialGlobal", "n2NorthOutConcept", "v2Vol20Gt25",
  "s2SentHs300Low", "w1BackupDecline", "a1BullAllStop", "v3Vol20LowPct", "ad1AdlineHot",
  // X1(mine29c 2026-08-24, NEW14+1·15键可选档成员; 非挖掘产出故排末位; 与 loss_rules.NEW_KEYS_PROD 同步)
  "excludeTierNone"
];
var _KELLY_FADE_ALL_KEYS = _KELLY_FADE_FRONT_KEY_ORDER.concat(_KELLY_FADE_GATE_KEY_ORDER, _KELLY_FADE_T1_KEYS);
var _KELLY_FADE_MODE_PRESETS = [
  { id: "p8", name: "8键(旧默认·对照)", tagline: "v1.1.2 基座·稳定参照", caliber: "✓ v1.1.4 及以前默认(现对照档)", calWarn: false,
    keys: ["excludeSpecialBear", "n2NovSpecialIndustry", "janMidRating", "janMidSpecial", "k2c5HkChase", "r7MayReinforced", "excludeAuxCross", "greedy15"] },
  { id: "p9", name: "⭐ 9键", tagline: "8键+候选1·牛市辅备买拦截", caliber: "✓ 叠 8 键(+候选1)", calWarn: false, stars: 1,
    keys: ["excludeSpecialBear", "n2NovSpecialIndustry", "janMidRating", "janMidSpecial", "k2c5HkChase", "r7MayReinforced", "excludeAuxCross", "greedy15", "bullAuxBackupStop"] },
  { id: "a9", name: "⭐⭐ A 进攻王", tagline: "近端牛市吃满·回撤恢复99天", caliber: "⚠ 叠 9 键口径(叠加规则非独立组合)", calWarn: true, stars: 2,
    keys: ["excludeSpecialBear", "n2NovSpecialIndustry", "janMidRating", "janMidSpecial", "k2c5HkChase", "r7MayReinforced", "excludeAuxCross", "greedy15", "bullAuxBackupStop", "t1LowTurnSpecial", "q1QvixLowPct", "m1MarginDownBull", "v1HighVol20", "r1VolRatioLow", "k3ConceptBuy", "r2bSpecialGlobal", "r2gLowRatingQ3"] },
  { id: "b9", name: "⭐ B 均衡卡", tagline: "每项不差无短板·K档最钝感", caliber: "⚠ 叠 9 键口径(叠加规则非独立组合)", calWarn: true, stars: 1,
    keys: ["excludeSpecialBear", "n2NovSpecialIndustry", "janMidRating", "janMidSpecial", "k2c5HkChase", "r7MayReinforced", "excludeAuxCross", "greedy15", "bullAuxBackupStop", "t1LowTurnSpecial", "q1QvixLowPct", "m1MarginDownBull", "r1VolRatioLow", "r2bSpecialGlobal", "r2gLowRatingQ3"] },
  { id: "c9", name: "C 防守", tagline: "笔数最少·熊市少亏", caliber: "⚠ 叠 9 键口径(速查卡注: 真选 C 应叠 8 键下线候选1)", calWarn: true,
    keys: ["excludeSpecialBear", "n2NovSpecialIndustry", "janMidRating", "janMidSpecial", "k2c5HkChase", "r7MayReinforced", "excludeAuxCross", "greedy15", "bullAuxBackupStop", "n1NorthOutflow", "t1LowTurnSpecial", "d1LowDivYield", "h1VolChgHighA", "m1MarginDownBull", "p1LowDivBackup", "r2bSpecialGlobal"] },
  { id: "new14", name: "⭐⭐ NEW 14键", tagline: "新防守王·全史第一+回撤最浅", caliber: "✓ v1.1.5~v1.1.6 默认·现对照档", calWarn: false, stars: 2,
    keys: ["r10May6NonMay", "greedy15", "janMidSpecial", "k2c5HkChase", "k3ConceptBuy", "declinePhaseSpecial", "n1NorthOutflow", "t1LowTurnSpecial", "d1LowDivYield", "q1QvixLowPct", "h1VolChgHighA", "m1MarginDownBull", "p1LowDivBackup", "r2bSpecialGlobal"] },
  // new18(NEW2 18键) 已从下拉移除(v20260826 用户拍板"不用对照啦 14+1 对照够啦"): 条目删除,
  // 后端 RECENT_KEYS 打标集保留; 老记忆经消费点校验自动回默认。
  // 【更新 2026-08-26】组成对比区方案卡(lab.js _KELLY_MODE_COMPARE_CARDS)亦已移除(同日用户拍板"18和14键差异太小了")。
  { id: "new15", name: "⭐⭐ NEW14+1 · 15键", tagline: "NEW14+整剔有跟踪ETF象限(none/null)·回撤改善档", caliber: "⚠ 重构换基座(NEW 族扩展·可选档非默认)", calWarn: true, stars: 2,
    // X1=整剔 track_tier=none/null 象限(mine29c 2026-08-24 用户拍板保留为可选档; 同日用户拍板 X1 扩围
    // 「一起扩」剔 null, 与回测 etf_has_track 卡/首页筛选档4口径完全统一)。⚠诚实标注: 下述数字均为扩围前
    // 仅剔 none 口径(mine29c), 扩围后作废待正式穷举回测重算: 全史仅剔 17 笔毛 +584.62(费 359.07 净 +225.56),
    // 近 5 年 12 笔净 -1,450.66 但补位回收 +1,253.96(页面口径); mdd -4,178→-3,550。默认仍=new14(§23.7)。
    keys: ["r10May6NonMay", "greedy15", "janMidSpecial", "k2c5HkChase", "k3ConceptBuy", "declinePhaseSpecial", "n1NorthOutflow", "t1LowTurnSpecial", "d1LowDivYield", "q1QvixLowPct", "h1VolChgHighA", "m1MarginDownBull", "p1LowDivBackup", "r2bSpecialGlobal", "excludeTierNone"] },
  // S06(codex-task-20260825-001, B级用户拍板): 大盘领先动态切换·v1.1.7 起为默认档(综合auto王者, 用户拍板观察期)。
  // ⚠dynamic:true = 非静态键组合, 本条目禁止携带 keys; 四消费点遇 s06 必须按「信号日期」读快照
  //   effective_mode(a9/new15)再套对应基座键集, 禁止展开成静态 keys(handoff §四)。
  // 阈值/状态机唯一事实源 = scripts/gen_kelly_mode_s06_state.py → static-site/data/kelly_mode_s06_state.json,
  //   本文件零硬编码阈值(§22 登记点纪律); 下方 tooltip 文案数值仅为 §21 公示, 与生成器逐位一致由
  //   scripts/check_s06_state.py 机检把关。回测对照锚点(codex008 F2 held 新语义引擎重跑 2026-08-26):
  //   验段净利 +100,572.43 / mdd -3,811.27 / 强平 +82,761.50 vs 静态 NEW14+1 +83,718.16。
  { id: "s06", name: "⭐️⭐️⭐️ S06 · 大盘领先切换(默认)", tagline: "小盘弱→A进攻王·否则NEW14+1(动态)", caliber: "✓ v1.1.7 起默认·动态切换", calWarn: false, dynamic: true, stars: 3 }
];
var _KELLY_FADE_DEFAULT_MODE = "s06"; // v1.1.7(2026-08-26) 默认切 S06·大盘领先动态切换(综合auto王者, 用户拍板观察期); v1.1.5~v1.1.6=new14
// 下拉展示顺序(v20260826 用户拍板): 有星在前星多靠前, 无星跟在 1 星组后沿用原相对序——稳定排序(同星数不改变
// 原相对顺序), 默认选中值(p8/new14)与键集判定不受影响; 仅 _tdsFadeModeSelectHTML 渲染消费。
function _tdsFadeModeDisplayList() {
  return _KELLY_FADE_MODE_PRESETS
    .map(function (p, i) { return { p: p, i: i }; })
    .sort(function (a, b) {
      var sa = a.p.stars || 0, sb = b.p.stars || 0;
      if (sa !== sb) return sb - sa;   // 星多靠前(降序); 无星=0 殿后
      return a.i - b.i;                // 同星级沿用原相对序(Array.prototype.sort 现代引擎为稳定排序, 双保险仍显式比原索引)
    })
    .map(function (x) { return x.p; });
}
function _tdsFadeModeById(id) {
  for (var i = 0; i < _KELLY_FADE_MODE_PRESETS.length; i++) {
    if (_KELLY_FADE_MODE_PRESETS[i].id === id) return _KELLY_FADE_MODE_PRESETS[i];
  }
  return null;
}
// 把模式键组合写进 filters 对象: 58 个 fade 键先全部置 false 再按预设点亮(non-fade 键如 positionCap/K 不动)
// s06(dynamic)无静态 keys → 返回 false(调用方须改走 _tdsS06FiltersForDate 按日期取基座 filters)
function _tdsFadeModeApply(modeId, filters) {
  var p = _tdsFadeModeById(modeId);
  if (!p || !filters) return false;
  if (p.dynamic || !Array.isArray(p.keys)) return false;
  for (var i = 0; i < _KELLY_FADE_ALL_KEYS.length; i++) filters[_KELLY_FADE_ALL_KEYS[i]] = false;
  for (var j = 0; j < p.keys.length; j++) filters[p.keys[j]] = true;
  return true;
}
// 由 filters 反查当前匹配的模式 id(全等匹配; 不匹配任何预设=null=自定义态; dynamic 预设无静态形态必跳过)
function _tdsFadeModeMatch(filters) {
  if (!filters) return null;
  for (var i = 0; i < _KELLY_FADE_MODE_PRESETS.length; i++) {
    var p = _KELLY_FADE_MODE_PRESETS[i];
    if (p.dynamic || !Array.isArray(p.keys)) continue;
    var ok = true;
    for (var j = 0; j < _KELLY_FADE_ALL_KEYS.length; j++) {
      var k = _KELLY_FADE_ALL_KEYS[j];
      if (!!filters[k] !== (p.keys.indexOf(k) >= 0)) { ok = false; break; }
    }
    if (ok) return p.id;
  }
  return null;
}
// 模式下拉 HTML(withCustom=true 时附加「自定义」占位项, lab 标签区用; 弹窗无标签区不需要)
// ── 四消费点统一下拉组件(T3-1修复批 2026-08-23, §23.3 举一反三)──
//   HTML 层=_tdsFadeModeSelectHTML(id, 当前值, 是否含自定义项, 类名, tooltip);
//   挂载层=_tdsFadeModeSelectMount(挂载点, {id/value/withCustom/cls/title/onchange});
//   样式=.tds-fade-mode-wrap/.tds-fade-mode-sel(style.css 公共段单份, 各页不留私有副本)。
//   已接入: lab 凯利区(lab.js _renderSigKellyBar)、模拟回测弹窗(app.js _openSimBacktestModal);
//   待接(T3-2): 首页 AI 建议卡、AI 监控卡——直接复用本组件, 不再各写一份 select。
function _tdsFadeModeSelectHTML(id, selectedId, withCustom, cls, title) {
  var h = '<select id="' + id + '" class="' + (cls || "tds-fade-mode-sel") + '"' + (title ? ' title="' + title + '"' : "") + '>';
  // v20260826: 渲染顺序走 _tdsFadeModeDisplayList(星多靠前/无星殿后沿用原相对序), name 已含星前缀
  var _list = (typeof _tdsFadeModeDisplayList === "function") ? _tdsFadeModeDisplayList() : _KELLY_FADE_MODE_PRESETS;
  for (var i = 0; i < _list.length; i++) {
    var p = _list[i];
    h += '<option value="' + p.id + '"' + (p.id === selectedId ? " selected" : "") + ">" + p.name + " · " + p.tagline + (p.calWarn ? " ⚠" : "") + "</option>";
  }
  if (withCustom) {
    h += '<option value="custom"' + ("custom" === selectedId ? " selected" : "") + ' disabled hidden>⚙️ 自定义(手动勾选生成)</option>';
  }
  h += "</select>";
  return h;
}
// 挂载层: 往挂载点(元素或 id)渲染下拉并绑 onchange(value)=>; 返回 select 元素(失败返回 null)。
// 注: 若宿主已有委托/change 统一绑定(如 sim 弹窗 .sim-fade-mode-sel 选择器循环), cfg.onchange 留空避免双触发。
function _tdsFadeModeSelectMount(mount, cfg) {
  cfg = cfg || {};
  var el = typeof mount === "string" ? document.getElementById(mount) : mount;
  if (!el) return null;
  var selId = cfg.id || ("tds-fade-mode-sel-" + Date.now() + "-" + Math.floor(Math.random() * 1e4));
  el.innerHTML = _tdsFadeModeSelectHTML(selId, cfg.value || _KELLY_FADE_DEFAULT_MODE, !!cfg.withCustom, "tds-fade-mode-sel" + (cfg.cls ? " " + cfg.cls : ""), cfg.title || "");
  var sel = el.firstElementChild;
  if (sel && typeof cfg.onchange === "function") {
    sel.addEventListener("change", function () { cfg.onchange(sel.value, sel); });
  }
  return sel;
}
// ── localStorage 带 TTL 的读写工具(2026-08-23 用户拍板: 模式记忆不做永久保留; 同日二次拍板 TTL=18 小时,
//    覆盖隔夜——今天收盘后切的模式, 明天开盘仍在, 但不会永久滞留)──
//   存格式 = JSON.stringify({ v: <任意可序列化值>, ts: Date.now() }); 取时超时/无 ts(旧格式兼容)/解析失败 → 返回 null 并顺手清键。
//   设计为通用工具(T3-2 首页 tds_home_fade_mode / 监控卡 tds_overfit_fade_mode 直接复用), 不绑定具体 key。
//   ⚠️ 模式记忆 TTL 单一常量源 = _TDS_FADE_TTL_MS(所有调用方引用它, 不各自写 3600*1000, 防再调时长漏改)。
var _TDS_FADE_TTL_MS = 18 * 3600 * 1000;
function _tdsStoreWithTTL(key, val) {
  try { localStorage.setItem(key, JSON.stringify({ v: val, ts: Date.now() })); } catch (e) {}
}
function _tdsLoadWithTTL(key, ttlMs) {
  try {
    var raw = localStorage.getItem(key);
    if (!raw) return null;
    var o = JSON.parse(raw);
    if (!o || typeof o !== "object" || o.ts === undefined || o.ts === null) {
      // 旧格式(无 ts 字段)= 视为过期记忆, 清掉回默认(2026-08-23 用户拍板: 不做永久记忆)
      localStorage.removeItem(key);
      return null;
    }
    if (Date.now() - o.ts > ttlMs) { localStorage.removeItem(key); return null; }
    return o.v;
  } catch (e) { try { localStorage.removeItem(key); } catch (e2) {} return null; }
}
window._KELLY_FADE_LEGACY_SPECS = _KELLY_FADE_LEGACY_SPECS;
window._KELLY_FADE_FRONT_KEY_ORDER = _KELLY_FADE_FRONT_KEY_ORDER;
window._KELLY_FADE_GATE_KEY_ORDER = _KELLY_FADE_GATE_KEY_ORDER;
window._tdsFadeSpecHit = _tdsFadeSpecHit;
window._KELLY_FADE_MODE_PRESETS = _KELLY_FADE_MODE_PRESETS;
window._KELLY_FADE_ALL_KEYS = _KELLY_FADE_ALL_KEYS;
window._KELLY_FADE_DEFAULT_MODE = _KELLY_FADE_DEFAULT_MODE;
window._tdsFadeModeById = _tdsFadeModeById;
window._tdsFadeModeDisplayList = _tdsFadeModeDisplayList;
window._tdsFadeModeApply = _tdsFadeModeApply;
window._tdsFadeModeMatch = _tdsFadeModeMatch;
window._tdsFadeModeSelectHTML = _tdsFadeModeSelectHTML;
window._tdsFadeModeSelectMount = _tdsFadeModeSelectMount;
window._tdsStoreWithTTL = _tdsStoreWithTTL;
window._tdsLoadWithTTL = _tdsLoadWithTTL;
window._TDS_FADE_TTL_MS = _TDS_FADE_TTL_MS;

// ===== S06 · 大盘领先切换: 快照加载/按日期解析/降级状态(codex-task-20260825-001, B级用户拍板) =====
// 【单源】阈值/confirm/minhold/逐日 effective_mode 全部来自 static-site/data/kelly_mode_s06_state.json
//   (生成器 scripts/gen_kelly_mode_s06_state.py); 本文件零硬编码阈值——前端只做「日期→基座(a9/new15)→键集」,
//   禁止自算因子/阈值(§23.6 同精神: 前端不自算宇宙; §22: 多展示位共用本单源)。
// 【降级契约(可见不静默)】快照缺失/字段缺失/日期超出覆盖期 → _tdsS06BaseForDate 返回 ok:false + reason,
//   各消费点必须 fail-open(该笔不拦)+ 在界面给出可见警示(计数说明原因), 绝不静默退回其他模式(handoff §五.功能5)。
// 【事件】加载完成 dispatch "tds-s06-state-ready"(消费点可监听重渲染); 失败 dispatch "tds-s06-state-error"。
var _TDS_S06_MODE_ID = "s06";
var _TDS_S06_STATE_URL = "./data/kelly_mode_s06_state.json";
var _tdsS06State = null;         // 快照本体(null=尚未成功加载)
var _tdsS06LoadErr = null;       // 最近一次加载失败原因(可见降级提示用)
var _tdsS06Promise = null;       // 单例加载 promise(防四消费点并发重复拉)
var _tdsS06ByDate = null;        // date(YYYYMMDD)->daily 行 映射(加载后建)
var _tdsS06FiltersCache = null;  // baseId -> 58 键布尔 filters(惰性构建共享, 只读勿改)
function _tdsS06NormalizeDate(d) {
  if (d === null || d === undefined) return "";
  return String(d).replace(/[^0-9]/g, "");   // 兼容 YYYYMMDD 与 YYYY-MM-DD 两种来源格式
}
function _tdsS06StateEnsure() {
  if (_tdsS06Promise) return _tdsS06Promise;
  var fetchFn = typeof fetchJSON === "function" ? fetchJSON : null;   // fetchJSON 自带备站 fallback(app.js)
  _tdsS06Promise = (fetchFn ? fetchFn(_TDS_S06_STATE_URL) : fetch(_TDS_S06_STATE_URL).then(function (r) {
    if (!r.ok) throw new Error("HTTP " + r.status);
    return r.json();
  })).then(function (d) {
      if (!d || !Array.isArray(d.daily) || !d.daily.length || typeof d.threshold !== "number"
          || !d.on_base || !d.off_base) {
        _tdsS06LoadErr = "快照字段缺失/为空";
        try { window.dispatchEvent(new CustomEvent("tds-s06-state-error", { detail: _tdsS06LoadErr })); } catch (e) {}
        return null;
      }
      _tdsS06State = d;
      _tdsS06ByDate = {};
      for (var i = 0; i < d.daily.length; i++) _tdsS06ByDate[_tdsS06NormalizeDate(d.daily[i].date)] = d.daily[i];
      try { window.dispatchEvent(new CustomEvent("tds-s06-state-ready")); } catch (e) {}
      return d;
    })
    .catch(function (err) {
      _tdsS06LoadErr = (err && err.message) ? ("快照加载失败: " + err.message) : "快照加载失败";
      try { window.dispatchEvent(new CustomEvent("tds-s06-state-error", { detail: _tdsS06LoadErr })); } catch (e) {}
      return null;
    });
  return _tdsS06Promise;
}
// 健康度速查(消费点渲染警示条用): loaded/err/覆盖期/current{date,mode,since}/threshold 等元信息
function _tdsS06Status() {
  return {
    modeId: _TDS_S06_MODE_ID,
    loading: !!_tdsS06Promise && !_tdsS06State && !_tdsS06LoadErr,
    loaded: !!_tdsS06State,
    err: _tdsS06LoadErr,
    coverageStart: _tdsS06State ? _tdsS06State.coverage_start : null,
    coverageEnd: _tdsS06State ? _tdsS06State.coverage_end : null,
    current: _tdsS06State ? _tdsS06State.current : null,
    onBaseName: (_tdsFadeModeById("a9") || {}).name || "a9",
    offBaseName: (_tdsFadeModeById("new15") || {}).name || "new15"
  };
}
// 核心: 日期 → 生效基座。ok:false 时 reason ∈ not_loaded/load_err/no_row/out_of_range(消费点 fail-open + 可见提示)
function _tdsS06BaseForDate(dateStr) {
  var nd = _tdsS06NormalizeDate(dateStr);
  if (!_tdsS06State) return { ok: false, reason: _tdsS06LoadErr ? "load_err" : "not_loaded" };
  var row = _tdsS06ByDate ? _tdsS06ByDate[nd] : null;
  if (!row) {
    var cs = _tdsS06NormalizeDate(_tdsS06State.coverage_start), ce = _tdsS06NormalizeDate(_tdsS06State.coverage_end);
    return { ok: false, reason: (!cs || nd < cs || nd > ce) ? "out_of_range" : "no_row" };
  }
  var base = row.effective_mode;
  if (base !== "a9" && base !== "new15") return { ok: false, reason: "bad_mode" };
  return { ok: true, base: base, decisionDate: row.decision_date, sizeSpread: row.size_spread };
}
// 日期 → 该日生效基座的 58 键布尔 filters(共享只读对象; 不可用返回 null=调用方 fail-open)
function _tdsS06FiltersForDate(dateStr) {
  var r = _tdsS06BaseForDate(dateStr);
  if (!r.ok) return null;
  if (!_tdsS06FiltersCache) _tdsS06FiltersCache = {};
  var f = _tdsS06FiltersCache[r.base];
  if (!f) {
    f = {};
    for (var i = 0; i < _KELLY_FADE_ALL_KEYS.length; i++) f[_KELLY_FADE_ALL_KEYS[i]] = false;
    var p = _tdsFadeModeById(r.base);
    if (p && Array.isArray(p.keys)) for (var j = 0; j < p.keys.length; j++) f[p.keys[j]] = true;
    _tdsS06FiltersCache[r.base] = f;
  }
  return f;
}
// 日期 → 该日生效基座的 keys 数组(memberSet 型消费点用; 不可用返回 null)
function _tdsS06KeysForDate(dateStr) {
  var r = _tdsS06BaseForDate(dateStr);
  if (!r.ok) return null;
  var p = _tdsFadeModeById(r.base);
  return (p && Array.isArray(p.keys)) ? p.keys : null;
}
// §21/§23.9 三档互证公示文案(下拉 title 等; 数值须与 gen_kelly_mode_s06_state.py 逐位一致, 机检把关)
function _tdsS06Tooltip() {
  return [
    "【是什么】S06 不是固定勾键组合, 是按大盘风格自动换基座: 每天收盘算「中证100020日涨幅 − 沪深300 20日涨幅」,",
    "小于 -3.524%(2016-2020 选段 q30 冻结阈值)说明小盘显著跑输 → 次日切 A 进攻王(进攻基座); 否则次日回到 NEW14+1·15键(防守兜底)。",
    "T 日收盘判定 T+1 生效; A 持有天数=生效交易日数(进入当日计 1, 其后每个交易日递增, 无论当日是否继续命中);",
    "从 A 退出需「连续 15 个交易日破坏」且「持满 10 个交易日」同时满足——持续非命中时最多 15 个交易日必切出, 不会锁死。",
    "【什么时候用】想检验「大小盘风格切换能否自动选对基座」时选它; 默认档仍是 NEW 14键不受影响。",
    "【举例】2026-06-08 收盘差值 -4.049% < -3.524% → 6-09 起生效 A 进攻王, 该段持续到 7-06、因 premise 连续 15 日未破于 7-07 切回防守;",
    "2026-07-14 收盘差值 -5.049% 已破位但按 T+1 时序当日仍 NEW14+1, 7-15 起生效 A 进攻王至今; 2026-04-27 差值 +1.687% 未破阈值 → 4-28 生效 NEW14+1(3-24 进入的 A 段结束)。",
    "【对照数据(同引擎验证段 2021 起, 2026-08-26 held 口径修复后重跑)】S06 净利 +100,572 高于静态 NEW14+1 的 +83,718; 但最大回撤 -3,811 略深于其 -3,550,",
    "强平口径 +82,762 亦略逊 — 未过完整风格周期检验, 实验可选档非实盘结论。"
  ].join("\n");
}
window._TDS_S06_MODE_ID = _TDS_S06_MODE_ID;
window._TDS_S06_STATE_URL = _TDS_S06_STATE_URL;
window._tdsS06StateEnsure = _tdsS06StateEnsure;
window._tdsS06Status = _tdsS06Status;
window._tdsS06BaseForDate = _tdsS06BaseForDate;
window._tdsS06FiltersForDate = _tdsS06FiltersForDate;
window._tdsS06KeysForDate = _tdsS06KeysForDate;
window._tdsS06Tooltip = _tdsS06Tooltip;
window._tdsS06NormalizeDate = _tdsS06NormalizeDate;
// 枯竭 chip S06 口径尾注(§22 文案单源, reviewer P2 F1 举一反三下沉): 选 S06(dynamic)时判定按日期在
// A进攻王/NEW14+1 两基座间切换, 与 chip 内置「NEW14 默认过滤」静态口径文案不符 → 消费点(app.js 首页两处 +
// lab 凯利区)统一取本函数覆盖; 非 S06 态消费点不调用, 内置默认口径渲染零变化。
function _tdsS06CaliberNote() {
  return "(口径: S06 动态基座·按日切 A进攻王/NEW14+1 过滤下实时统计; 72% 为 NEW14 全史统计仅作参考)";
}
window._tdsS06CaliberNote = _tdsS06CaliberNote;

// ===== v1.1.5(2026-08-24) 「连续 N 日无放行」枯竭提示(纯展示层, 单源在此; 消费点=首页 AI 建议区 + lab 凯利区信号区) =====
// 【数据源】overfit_monitor.json 的 recent 块(T3-2 已建产物字段, 后端 overfit_monitor.py build_recent_block,
//   近 RECENT_DAYS=340 个交易日逐信号明细: d=signal_date / s=signal / t=track_score(null=未入样) /
//   k=命中键"|"join(v1.1.2 四档口径) / tier)。零新增后端任务, 纯复用现有产物(每晚 21:40 随监控卡打点更新)。
//   老版 json 无 recent 块 → 静默不显示(优雅降级), 不报错不占位。
// 【放行定义】与首页 AI 建议/凯利回测同链口径(§22): 买入类信号(buy/buy_aux/buy_special(+filtered)/buy_backup)
//   × 已入样(t≠null, 等价 _bt_in_universe 回测入样判定, 前端不自算宇宙 §23.6) × 当前默认模式(s06 动态组合/new14 静态键集)键集
//   与该信号命中键集(k)无交集=未被任何降亏键拦下。
// 【防前视声明】本提示为「截至最新交易日的累计状态 + mine30 静态历史统计」纯展示, 零时变判定/零切换规则,
//   不含任何未来信息(§5.1⑥ 自查通过)。
var _TDS_DROUGHT_THRESHOLD = 20;   // N≥20 才显示(≈年均触发 2.4 次, mine30 §五)
var _TDS_DROUGHT_LONG = 40;        // N≥40 追加历史长度对照句(≈一年一遇, mine30 §五)
var _TDS_BUY_SIGNAL_SET = { buy: 1, buy_aux: 1, buy_special: 1, buy_special_filtered: 1, buy_backup: 1 };
var _tdsRecentBlockPromise = null;
// 共享获取器: overfit_monitor.json recent 块(app.js 监控卡/lab 凯利区共用一个 promise 防 27MB 双拉; 失败 resolve null)
function _tdsFetchRecentBlock(fetchFn) {
  if (_tdsRecentBlockPromise) return _tdsRecentBlockPromise;
  var _f = fetchFn || (typeof fetchJSON === "function" ? fetchJSON : null);
  _tdsRecentBlockPromise = (_f ? _f("./data/overfit_monitor.json") : Promise.reject(new Error("no fetch")))
    .then(function (d) { return (d && d.recent && Array.isArray(d.recent.rows)) ? d.recent : null; })
    .catch(function () { return null; });
  return _tdsRecentBlockPromise;
}
// 计算: 截至 latest 的连续无放行买入信号交易日数 N。
// recent={rows:[{d,s,t,k,...}], latest} / modeKeys=当前模式键数组(默认取 s06 动态/new14 预设 keys);
//   S06(2026-08-25 codex-task-001): 也接受「日期→键集」函数(per-date 动态基座口径, 与首页判定链同源 §22),
//   函数对某日期返回 []/null = 该日视为无键不拦(fail-open 同语义)。
// 返回 {n, latest, window} 或 null(rows 缺失/空)。n 封顶=窗口内交易日数(全窗口无放行时)。
function _tdsComputeDrought(recent, modeKeys) {
  try {
    if (!recent || !Array.isArray(recent.rows) || !recent.rows.length) return null;
    var staticKeys = Array.isArray(modeKeys) ? modeKeys : null;
    // 按日期聚合「该日是否有放行买入信号」+ 收集交易日序列
    var dayHasPass = {};
    for (var i = 0; i < recent.rows.length; i++) {
      var r = recent.rows[i];
      if (!r || !r.d || !_TDS_BUY_SIGNAL_SET[r.s]) continue;      // 仅买类参与放行判定
      if (r.t == null) continue;                                   // 未入样(无跟踪分)不算放行
      var keys = staticKeys;
      if (!staticKeys && typeof modeKeys === "function") {         // s06 per-date 键集
        var kd = modeKeys(r.d);
        keys = Array.isArray(kd) ? kd : [];
      }
      var hit = (typeof r.k === "string" && r.k) ? r.k.split("|") : [];
      var blocked = false;
      for (var j = 0; j < hit.length; j++) { if (keys.indexOf(hit[j]) >= 0) { blocked = true; break; } }
      if (!blocked) dayHasPass[r.d] = true;                        // 未命中任一默认键=放行
    }
    var seen = {};
    var allDays = [];
    for (var m = 0; m < recent.rows.length; m++) {
      var dd = recent.rows[m] && recent.rows[m].d;
      if (dd && !seen[dd]) { seen[dd] = 1; allDays.push(dd); }
    }
    if (!allDays.length) return null;
    allDays.sort();
    var latest = (recent.latest && seen[recent.latest]) ? recent.latest : allDays[allDays.length - 1];
    var idxLatest = allDays.indexOf(latest);
    if (idxLatest < 0) return null;
    var n = 0;
    for (var b = idxLatest; b >= 0; b--) {
      if (dayHasPass[allDays[b]]) break;
      n++;
    }
    return { n: n, latest: latest, window: allDays.length };
  } catch (e) { return null; }
}
// 文案生成(N≥阈值才返回 HTML; 数字全部来自 mine30(docs/kelly/analysis/new14-default-challenge-mine30-20260824.md §五), 零编造)
// caliberNote(可选, 2026-08-25): 口径尾注覆盖(如 s06 动态基座时由调用方传入动态口径说明, 防文案与实际判定口径不符 §21)
function _tdsDroughtChipHtml(info, caliberNote) {
  if (!info || !(info.n >= _TDS_DROUGHT_THRESHOLD)) return "";
  var base = "已连续 <b>" + info.n + "</b> 个交易日无放行信号 · 历史上类似枯竭结束后 3 个月约 <b>72%</b> 为正, 常由下跌触发放行";
  var src = caliberNote || "(口径: 默认过滤(s06/v1.1.7 起)下实时统计; 72%=mine30 全史 37 次≥20 交易日枯竭恢复后 26/36 为正)";
  var longNote = info.n >= _TDS_DROUGHT_LONG
    ? " · 本轮已超历史上多数枯竭长度(≥40 交易日共 13 次、≥60 日 10 次、最长 484 日)"
    : "";
  var tip = "信号枯竭提示(v1.1.5 新增, 纯展示层): 当前默认过滤组合下连续无放行买入信号的交易日数。" +
    "【白话】NEW14 是防守反击刀——长时间不开枪、只开高置信度的枪, 枯竭是它的常态运作方式而非异常" +
    "(全史 ≥20 交易日枯竭 37 次≈年均 2.4 次)。【场景】看到本提示不必恐慌: 历史上类似枯竭结束后 3 个月约 72% 为正," +
    "且最肥的反弹全部紧随大跌(报复性信号簇正是 NEW14 高净利的来源形态)。【1:1】2026-07-21 起 NEW14 进入本轮枯竭," +
    "至 08-21 已 23 个交易日(mine30 实测), 与本提示实时数字同源可对照。【数据源】overfit_monitor.json recent 明细块" +
    "(近 340 交易日逐信号打标, 放行=买入类×已入样×未命中当前模式键); 历史统计=mine30 报告 §五。";
  return '<span class="sig-drought-chip tds-drought-chip" data-no-pop="" data-tip="' + tip.replace(/"/g, "&quot;") + '" title="">' +
    '⏳ ' + base + longNote + ' <span style="opacity:.75;font-size:.92em">' + src + '</span>' +
    '</span>';
}
window._TDS_DROUGHT_THRESHOLD = _TDS_DROUGHT_THRESHOLD;
window._tdsFetchRecentBlock = _tdsFetchRecentBlock;
window._tdsComputeDrought = _tdsComputeDrought;
window._tdsDroughtChipHtml = _tdsDroughtChipHtml;
