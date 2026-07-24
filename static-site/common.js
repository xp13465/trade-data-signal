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
  { iid: "hscei", name: "国企指数" },
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
  // direction: "high"=高位风险(分越高越危险) / "low"=低位机会(分越高越冷越有机会)
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
    if (score >= 70) return "≥70 过热减仓";
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
    if (score >= 70) return "多处指标过热，注意减仓风险";
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
  if (highHot) return { text: "⚠️ 当前偏热，注意减仓风险", cls: "sum-danger" };
  if (lowOpp) return { text: "💡 当前偏冷，关注企稳机会", cls: "sum-good" };
  if (highWarm && lowWarm) return { text: "➡️ 当前分化，部分偏热部分偏冷，观望为主", cls: "sum-warn" };
  if (highWarm) return { text: "➡️ 部分指标偏热，留意回调风险", cls: "sum-warn" };
  if (lowWarm) return { text: "➡️ 部分指标进入低位区，关注企稳信号", cls: "sum-good" };
  return { text: "➡️ 当前中性，观望为主", cls: "sum-neutral" };
}

// 分数卡(high 高位风险分 + low 低位机会分 + adapt 适配信息)
function _labCustomScoreCardHTML(data, alert, humanText) {
  const name = data.target_name || data.target_id || "";
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
        `<span class="position-badge position-${posHands}">建议仓位 ${posHands}手·${posLabel}</span>` +
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
        `<div class="lab-custom-cell-label">高位风险分<span class="lab-custom-cell-sublabel">越高越热，≥70 过热注意减仓</span></div>` +
        `<div class="lab-custom-cell-score">${high != null ? high.toFixed(2) : "-"}</div>` +
        `<div class="lab-custom-cell-level" title="${highTooltip}">${highLvlText}</div>` +
        `<div class="lab-custom-cell-desc">分越高越接近过热 · 悬浮看区间含义</div>` +
        `<div class="lab-custom-cell-human">${highHuman}</div>` +
      `</div>` +
      `<div class="lab-custom-score-cell ${lowLvlCls}">` +
        `<div class="lab-custom-cell-label">低位机会分<span class="lab-custom-cell-sublabel">越高机会越大，≥70 机会显现</span></div>` +
        `<div class="lab-custom-cell-score">${low != null ? low.toFixed(2) : "-"}</div>` +
        `<div class="lab-custom-cell-level" title="${lowTooltip}">${lowLvlText}</div>` +
        `<div class="lab-custom-cell-desc">分越高越偏冷有机会 · 悬浮看区间含义</div>` +
        `<div class="lab-custom-cell-human">${lowHuman}</div>` +
      `</div>` +
    `</div>` +
    posRow +
  `</div>`;
}

// 8+8 维度表(H1-H8 高位风险 + L1-L8 低位机会)
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
  return `<div class="lab-custom-dims">` +
    `<div class="lab-custom-section-title">🔬 8+8 维度拆解（高位风险 H1-H8 + 低位机会 L1-L8）</div>` +
    `<div class="lab-custom-dims-grid">` +
      `<div class="lab-custom-dims-col">` +
        `<div class="lab-custom-dims-col-title danger">高位风险维度（分高=危险）</div>` +
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

  return `<div class="lab-custom-hist">` +
    `<div class="lab-custom-section-title">📜 历史类比 前3（相似特征时段后续涨跌统计）</div>` +
    `<div class="lab-custom-hist-grid">` +
      sideHTML("high", "高位风险视角") +
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
  return `<div class="lab-custom-thresh">` +
    `<button type="button" class="lab-custom-thresh-toggle">展开数据阈值表 ▾</button>` +
    `<div class="lab-custom-thresh-body" style="display:none">` +
      `<div class="lab-custom-thresh-grid">` +
        `<div class="lab-custom-thresh-col">` +
          `<div class="lab-custom-thresh-col-title danger">高位风险阈值</div>` +
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
  return `<div class="lab-custom-footer">` +
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
        `<li><b>机会分</b>(权重35%):low_alert 低位机会分,L1-L8 多维加权(0-100),主导仓位</li>` +
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

// === 挂到 window,供 lab.js / app.js 跨文件引用 ===
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
