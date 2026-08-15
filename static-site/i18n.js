/*!
 * i18n.js - 全站合规名词替换字典 + _t() 翻译函数
 * 方案B: JS文案替换 + localStorage（默认精简版表述；🛡️按钮切回完整版）
 * 复用 app/alert_reason.py:77-82 禁用词映射 + 5点拍板（88魔咒保留/图表pin文字版"关注/风险/风控"）
 *
 * 默认 mode="on"（精简版）；🛡️按钮切 mode="off"（完整版）
 * localStorage key: "compliance_mode"，值 "on"（默认/精简）/"off"（完整）
 *
 * 第1阶段（本文件）：核心骨架，仅覆盖 app.js 集中点（6处labels + _SIG_TYPE_META + _SIG_DETAIL + signalLabel + ETF5档）
 * 第2-4阶段：app.js分散点 + lab.js + about.html + trade_sim + common.js + purpose-notes.js + 邮件
 */
(function () {
  "use strict";
  var STORAGE_KEY = "compliance_mode";

  // ===== 双字典：compliance（默认精简版）/ original（🛡️ off 完整版）=====
  var DICTS = {
    // 精简版（默认）：简化表述，去交易指令词保留语义
    compliance: {
      // 短标签（走势图pin，app.js L2470 _pinStatsBriefHtml）
      buy_short: "关注",
      sell_short: "风险提醒",
      buy_aux: "辅关注",
      buy_special: "追关注",
      buy_special_filtered_short: "追关注(过滤)",
      buy_special_filtered_long: "追关注(过滤预览)",
      buy_backup: "备关注",
      sell_stop_loss: "追风控|警示",
      band_hold: "波段持有",
      // 长标签（信号卡/频率汇总，app.js L2641 statsHint / L3610 频率modal / L12489 _freqPopupHtml）
      buy_long: "主关注",
      sell_long: "风险提醒",
      // _SIG_TYPE_META 分类chip（app.js L1265-1272）
      type_buy: "主关注",
      type_sell_stop_loss: "追风控|警示",
      type_band_sell: "波段调整",
      // _SIG_DETAIL 弹窗详情 name（app.js L1678-1685 _SIGNAL_HELP_ITEMS）
      detail_buy_name: "主关注 · 超卖拐点",
      detail_buy_aux_name: "辅关注 · 下轨拐点",
      detail_buy_special_name: "追关注 · 上轨突破",
      detail_buy_special_filtered_name: "追关注(过滤预览) · h5灰图钉",
      detail_buy_backup_name: "备关注 · 趋势转向",
      detail_sell_name: "风险提醒 · 趋势转弱",
      detail_sell_stop_loss_name: "追风控|警示 · ATR×3.5风控",
      detail_band_hold_name: "波段持有 · 国债波段仓管",
      detail_band_sell_name: "波段调整 · 国债波段仓管",
      // ETF 5档（app.js L13395 ETF_TIER_LABEL）
      etf_strong_sell: "重点规避",
      etf_sell: "风险提示信号",
      etf_hold: "持有观察",
      etf_buy: "关注机会",
      etf_strong_buy: "重点留意",
      // signalLabel（app.js L380）动态拼接用词
      sl_buy_special_filtered: "追关注(过滤预览)",
      word_stop_loss: "风控",
      word_band_reduce: "调整",
      // 第2阶段分散点：通知/ETF明细/标题等
      notify_buy_title: "新关注信号",
      notify_sell_title: "新风险提示",
      notify_buy_body: "触发关注",
      notify_sell_body: "触发风险提示",
      etf_side_buy: "关注机会",
      etf_side_sell: "风险提示信号",
      etf_side_hold: "持有观察",
      etf_buy_section: "📐 关注建议",
      etf_sell_section: "🔻 风险提示建议",
      etf_sellhold_section: "风险提示 / 持有观察",
      etf_chip_buy: "关注",
      etf_chip_sell: "风险提示",
      etf_sort_hands: "关注点档数 多->少",
      etf_no_buy: "🟡 最近信号非关注点",
      etf_score_hands: "关注点档数",
      etf_buypoint_prefix: "关注点",
      etf_hands_unit: "档",
      // 图例/tooltip 短词
      legend_band_reduce: "波段调整(国债)",
      legend_stop_loss: "ATR×3.5风控(追风控|警示)",
      legend_buy_diff: "⚠ 关注点回测差异提示",
      legend_band_hold: "波段持有(国债)",
      legend_sell: "趋势转弱(风险)",
      // 期货同向准确度趋势（分析术语，无买卖指令词，精简版与完整版一致）
      futures_acc_title: "同向准确度趋势",
      futures_acc_follow_ratio: "同向准确度",
      futures_acc_warn_streak: "连续3日<50%同向失效",
      futures_acc_dominant_same: "同向主导",
      futures_acc_dominant_contrarian: "逆向主导",
      position_reduce_prefix: "调整",
      position_stop_loss_clear: "风控退出",
      sig_meta_stop_loss_name: "追风控|警示 · ATR风控",
      sig_meta_stop_loss_label: "追风控|警示",
      weak_no_buypoint: "暂无优质关注点优选",
      buypoint_path_label: "该关注点+路径",
      subscribe_title: "订阅该指数信号（有关注/风险点时推送邮件/Telegram）",
      crosslink_signal: "关注/风险点信号",
      concept_title_signal: "含关注/风险点",
      etf_not_qualified: "不够格关注(C2)但不过热, 持有观察等待信号",
      etf_high_alert_rule: "≥85防范风险/≥75调3-4/≥70调1-2/≥60调1-4/<60持有观察",
      rule_modal_title: "关注/风险点策略说明",
      // 第3阶段：trade_sim modal 字符串（app.js L14981-15129）
      trade_sim_cagr_title: "首笔关注至今的复合年化收益。正值=平均每年赚这么多,可与银行理财/通胀对比。",
      trade_sim_first_buy: "首笔关注至今",
      trade_sim_years_unit: "年",
      trade_sim_buy_hint_prefix: "💡 关注：固定金额 -> 得份额；风险提示：退份额 -> 得市值（金额 ≠ 关注成本）。份额变动 +红/-绿，持仓市值 = 份额 × ",
      trade_sim_buy_hint_suffix: "收盘价。",
      trade_sim_buy_date: "关注日期",
      trade_sim_buy_price: "关注价",
      trade_sim_sell_date: "风险日期",
      trade_sim_sell_price: "风险价",
      trade_sim_ops_buy: "关注",
      trade_sim_ops_sell: "风险提醒",
      trade_sim_skip_tooltip: "仓位已满/现金不足/无持仓可退时跳过不执行",
      // 第4阶段：场外基金评分排行（Phase A，fund_score_top.json Top100 列表）
      // 指标名非交易指令词，compliance/original 同文案
      fund_score_loading: "加载评分数据…",
      fund_score_load_failed: "加载评分数据失败",
      fund_score_search_placeholder: "搜基金代码或名称（如 013579 / 鹏扬）",
      fund_score_fund_type: "基金类型",
      fund_score_all_types: "全部类型",
      fund_score_sort_label_title: "排序方式",
      fund_score_composite_score: "综合评分",
      fund_score_half_kelly: "半凯利仓位",
      fund_score_final_suggestion: "建议仓位",
      fund_score_manager_score: "经理评分",
      fund_score_sharpe: "夏普",
      fund_score_star: "星级",
      fund_score_d3_drawdown: "回撤评分",
      fund_score_d4_stability: "稳定性评分",
      fund_score_count_unit: "只",
      fund_score_data_label: "数据日期",
      fund_score_sort_dir_suffix: "排序",
      fund_score_empty: "未命中基金，换个代码或名称试试",
      fund_score_sort_composite: "综合评分 高->低",
      fund_score_sort_composite_asc: "综合评分 低->高",
      fund_score_sort_half_kelly: "半凯利仓位 高->低",
      fund_score_sort_final_suggestion: "建议仓位 高->低",
      fund_score_sort_sharpe: "夏普 高->低",
      fund_score_sort_manager_score: "经理评分 高->低",
      fund_score_sort_star: "星级 高->低",
      fund_score_sort_drawdown: "回撤评分 高->低",
      fund_score_sort_stability: "稳定性评分 高->低",
      // 任务6+7(2026-07-20): 国债冲突提示 + 次要参考标注(非交易指令词,两版同文案)
      treasury_conflict_hint: "国债走波段仓位管理，波段调整优先；追关注为通用趋势信号，国债上参考意义有限",
      treasury_buy_special_minor: "次要·参考",
      // lab.js 凯利卡间比较分组标题
      lab_group_by_sig_type: "按信号类型分组(主/辅/追/备关注)"
    },
    // 完整版（🛡️ off）：用户点按钮切回的完整买卖点版本
    original: {
      buy_short: "买",
      sell_short: "卖",
      buy_aux: "辅买",
      buy_special: "追买",
      buy_special_filtered_short: "追买(过滤)",
      buy_special_filtered_long: "追买(过滤预览)",
      buy_backup: "备买",
      sell_stop_loss: "追止损|卖",
      band_hold: "波段持有",
      buy_long: "买点",
      sell_long: "卖点",
      type_buy: "主买",
      type_sell_stop_loss: "追止损|卖",
      type_band_sell: "波段减仓",
      detail_buy_name: "主买 · 超卖拐点",
      detail_buy_aux_name: "辅买 · 下轨拐点",
      detail_buy_special_name: "追买 · 上轨突破",
      detail_buy_special_filtered_name: "追买(过滤预览) · h5灰图钉",
      detail_buy_backup_name: "备买 · 趋势转向",
      detail_sell_name: "卖 · 趋势转弱",
      detail_sell_stop_loss_name: "追止损|卖 · ATR×3.5止损",
      detail_band_hold_name: "波段持有 · 国债波段仓管",
      detail_band_sell_name: "波段减仓 · 国债波段仓管",
      etf_strong_sell: "强卖出",
      etf_sell: "卖出",
      etf_hold: "持有观察",
      etf_buy: "买入",
      etf_strong_buy: "强买入",
      sl_buy_special_filtered: "追买(过滤预览)",
      word_stop_loss: "止损",
      word_band_reduce: "减仓",
      // 第2阶段分散点：通知/ETF明细/标题等
      notify_buy_title: "新买入信号",
      notify_sell_title: "新卖出信号",
      notify_buy_body: "触发买入",
      notify_sell_body: "触发卖出",
      etf_side_buy: "买入机会",
      etf_side_sell: "卖出信号",
      etf_side_hold: "持有观察",
      etf_buy_section: "📐 买点建议",
      etf_sell_section: "🔻 卖出建议",
      etf_sellhold_section: "卖出 / 持有观察",
      etf_chip_buy: "买入",
      etf_chip_sell: "卖出",
      etf_sort_hands: "买点手数 多->少",
      etf_no_buy: "🟡 最近信号非买点",
      etf_score_hands: "买点手数",
      etf_buypoint_prefix: "买点",
      etf_hands_unit: "手",
      // 图例/tooltip 短词
      legend_band_reduce: "波段减仓(国债)",
      legend_stop_loss: "ATR×3.5止损(追止损|卖)",
      legend_buy_diff: "⚠ 买点回测差异提示",
      legend_band_hold: "波段持有(国债)",
      legend_sell: "趋势转弱(卖)",
      // 期货同向准确度趋势（分析术语，无买卖指令词，精简版与完整版一致）
      futures_acc_title: "同向准确度趋势",
      futures_acc_follow_ratio: "同向准确度",
      futures_acc_warn_streak: "连续3日<50%同向失效",
      futures_acc_dominant_same: "同向主导",
      futures_acc_dominant_contrarian: "逆向主导",
      position_reduce_prefix: "减仓",
      position_stop_loss_clear: "止损清仓",
      sig_meta_stop_loss_name: "追止损|卖 · ATR止损",
      sig_meta_stop_loss_label: "追止损|卖",
      weak_no_buypoint: "暂无优质买点推荐",
      buypoint_path_label: "该买点+路径",
      subscribe_title: "订阅该指数信号（有买卖点时推送邮件/Telegram）",
      crosslink_signal: "买卖点信号",
      concept_title_signal: "含买卖点",
      etf_not_qualified: "不够格买入(C2)但不过热, 持有观察等待信号",
      etf_high_alert_rule: "≥85清仓/≥75减3-4/≥70减1-2/≥60减1-4/<60持有观察",
      rule_modal_title: "买卖点策略说明",
      // 第3阶段：trade_sim modal 字符串（app.js L14981-15129）
      trade_sim_cagr_title: "首笔买入至今的复合年化收益。正值=平均每年赚这么多,可与银行理财/通胀对比。",
      trade_sim_first_buy: "首笔买入至今",
      trade_sim_years_unit: "年",
      trade_sim_buy_hint_prefix: "💡 买入：固定金额 -> 得份额；卖出：卖份额 -> 得市值（金额 ≠ 买入成本）。份额变动 +红/-绿，持仓市值 = 份额 × ",
      trade_sim_buy_hint_suffix: "收盘价。",
      trade_sim_buy_date: "买入日期",
      trade_sim_buy_price: "买入价",
      trade_sim_sell_date: "卖出日期",
      trade_sim_sell_price: "卖出价",
      trade_sim_ops_buy: "买",
      trade_sim_ops_sell: "卖",
      trade_sim_skip_tooltip: "仓位已满/现金不足/无持仓可卖时跳过不执行",
      // 场外基金评分排行（Phase A，指标名非交易指令词，两版同文案）
      fund_score_loading: "加载评分数据…",
      fund_score_load_failed: "加载评分数据失败",
      fund_score_search_placeholder: "搜基金代码或名称（如 013579 / 鹏扬）",
      fund_score_fund_type: "基金类型",
      fund_score_all_types: "全部类型",
      fund_score_sort_label_title: "排序方式",
      fund_score_composite_score: "综合评分",
      fund_score_half_kelly: "半凯利仓位",
      fund_score_final_suggestion: "建议仓位",
      fund_score_manager_score: "经理评分",
      fund_score_sharpe: "夏普",
      fund_score_star: "星级",
      fund_score_d3_drawdown: "回撤评分",
      fund_score_d4_stability: "稳定性评分",
      fund_score_count_unit: "只",
      fund_score_data_label: "数据日期",
      fund_score_sort_dir_suffix: "排序",
      fund_score_empty: "未命中基金，换个代码或名称试试",
      fund_score_sort_composite: "综合评分 高->低",
      fund_score_sort_composite_asc: "综合评分 低->高",
      fund_score_sort_half_kelly: "半凯利仓位 高->低",
      fund_score_sort_final_suggestion: "建议仓位 高->低",
      fund_score_sort_sharpe: "夏普 高->低",
      fund_score_sort_manager_score: "经理评分 高->低",
      fund_score_sort_star: "星级 高->低",
      fund_score_sort_drawdown: "回撤评分 高->低",
      fund_score_sort_stability: "稳定性评分 高->低",
      // 任务6+7(2026-07-20): 国债冲突提示 + 次要参考标注(非交易指令词,两版同文案)
      treasury_conflict_hint: "国债走波段仓位管理，波段减仓优先；追买为通用趋势信号，国债上参考意义有限",
      treasury_buy_special_minor: "次要·参考",
      // lab.js 凯利卡间比较分组标题
      lab_group_by_sig_type: "按信号类型分组(主/辅/追/备买)"
    }
  };

  // ===== 当前 mode（同步读 localStorage，避免异步导致首屏用错字典）=====
  var currentMode = "on";
  try {
    var m = localStorage.getItem(STORAGE_KEY);
    if (m === "off") currentMode = "off";
  } catch (e) {}

  function _t(key) {
    var dict = DICTS[currentMode === "off" ? "original" : "compliance"];
    return Object.prototype.hasOwnProperty.call(dict, key) ? dict[key] : key;
  }
  _t.setMode = function (mode) {
    currentMode = (mode === "off") ? "off" : "on";
    try { localStorage.setItem(STORAGE_KEY, currentMode); } catch (e) {}
  };
  _t.getMode = function () { return currentMode; };
  _t.isCompliance = function () { return currentMode !== "off"; };

  // trade_sim entry.op 动态文本合规化（与 simulate_trade.py _ts_text_compliance 对齐）
  // JSON 保留原词（_BUY_LABELS: 主买/辅买/追买/备买/卖/追止损卖/清仓卖出 等），显示侧按 mode 转换
  // off mode 原样返回（切回完整版买卖点）；on mode 按长度降序替换，风控退出复合词用占位符保护
  var _TS_COMPLIANCE_MAP = [
    ["止损清仓卖出", "风控\x01CLEARED\x01"],
    ["止损清仓", "风控\x01CLEARED\x01"],
    ["止损卖出", "风控"],
    ["清仓卖出", "防范风险"],
    ["追止损卖", "追风控|警示"],
    ["主买", "主关注"],
    ["辅买", "辅关注"],
    ["追买", "追关注"],
    ["备买", "备关注"],
    ["买点", "关注点"],
    ["卖出日期", "风险日期"],
    ["卖出价", "风险价"],
    ["卖点", "风险提醒"],
    ["卖出", "风险提示"],
    ["首笔买入", "首笔关注"],
    ["买入日期", "关注日期"],
    ["买入价", "关注价"],
    ["买入成本", "关注成本"],
    ["卖份额", "退份额"],
    ["可卖", "可退"],
    ["买入", "关注"],
    ["止损", "风控"],
    ["风控清仓", "风控\x01CLEARED\x01"],
    ["清仓", "防范"],
    ["止盈", "收益兑现"],
    ["减仓", "调整"],
    ["买", "关注"],
    ["卖", "风险提醒"]
  ];
  _t.tsText = function (text) {
    if (currentMode === "off" || !text) return text;
    var out = text;
    for (var i = 0; i < _TS_COMPLIANCE_MAP.length; i++) {
      out = out.split(_TS_COMPLIANCE_MAP[i][0]).join(_TS_COMPLIANCE_MAP[i][1]);
    }
    // 还原占位符 -> 退出（"风控退出"合规复合词，与 i18n.js position_stop_loss_clear 对齐）
    return out.split("\x01CLEARED\x01").join("退出");
  };

  window._t = _t;
})();
