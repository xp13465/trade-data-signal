# 每日专业金融预测总结 - 调研报告

> 调研时间:2026-08-04 19:34 - 20:00
> 调研 agent(只读),不修改任何文件
> 用户需求:平台有很多数据,每天做一个"专业金融大佬的预测总结"(内容不要太长),放在"首盘小结"里,每天记录形成历史数据

---

## 0. 一句话结论(先给)

**平台已有完整的"收盘速递"管线(`market_summary.py` 规则生成 -> `summary.json` / `summary_history.json` 90天历史 -> 邮件+RSS+首页横幅+历史弹窗),但内容是"今日复盘",不是"预测"。**

用户要的"专业金融大佬的预测总结"是在现有总结基础上**叠加预测维度**(明日关注+风险点+趋势研判),并升级口吻。推荐**方案B(规则增强版)**作为主方案、**方案A(AI 生成)作为可选增强**(因为平台零 AI 集成,从零接入成本+依赖+不准风险都高,但可作"锦上添花"层)。两套方案详见 §5、§6。

---

## 1. 现有基础(可复用,务必读完再设计)

### 1.1 收盘速递邮件 `scripts/daily_summary_email.py` (562 行)

- **数据源**:`static-site/data/summary_history.json`(单文件多日 items 列表,90 天历史)
- **生成逻辑**:从 summary_history.json 取指定日期 item -> 拼 text/html 正文 -> SMTP SSL 发邮件(163 邮箱)
- **正文格式**(L154-241 `build_text`):
  - 标题:A股收盘情绪速递 · 日期 周X
  - 恐贪指数+情绪分(双指标)
  - 上证指数涨跌幅+收盘点
  - 涨跌家数+涨停跌停
  - 成交额+量能标签
  - 关注/风险点(买/卖信号数)
  - 新高新低+均线多空
  - 冰点提示(若有)
  - 领涨/领跌板块(top3)
  - 摘要(优先 summary_short)
  - 订阅列表段(读 config/subscriptions.json)
- **字段映射**:`date / fear_greed_value / fear_greed_label / sentiment_score / sentiment_label / sh_pct / sh_close / up_count / down_count / zt_count / dt_count / volume_amount / volume_label / buy_count / sell_count / nh_count / nl_count / ma_bullish / ma_bearish / is_freeze / freeze_info / top_industries[] / bottom_industries[] / summary_short / summary`
- **调度**:`update_all.sh` L233 末尾跑,失败不阻塞主流程(L234-241,失败调 notify.py 告警)
- **容错**:非交易日/无数据/SMTP 配置缺失 -> 优雅跳过不发,退出码 0
- **关键**:这是**邮件层**,不生成数据,只读 summary_history.json 渲染

### 1.2 `scripts/update_all.sh` L233 时点

```bash
# D10 每日收盘情绪速递邮件(summary_history.json 已由 pipeline deploy 生成就绪)。
# 失败不阻塞主流程:调 notify.py 告警,退出码仍以 RC_CORE 为准。
echo "-> daily_summary_email 收盘速递邮件 ..." | tee -a "$LOG"
if "$PY" "$REPO/scripts/daily_summary_email.py" >> "$LOG" 2>&1; then
  echo "  ✓ 收盘速递邮件已处理" | tee -a "$LOG"
else
  _DSE_RC=$?
  echo "⚠ daily_summary_email 失败(不阻塞主流程) rc=$_DSE_RC" | tee -a "$LOG"
  "$PY" "$REPO/scripts/notify.py" "[告警] 收盘速递邮件失败 ${MM_DD_HM}" ...
fi
```

update_all.sh 整体时点(launchd 17:50 触发):
- L70-87 并发 5 pipeline(core/width/futures/turnover/stock_daily)
- L91 check_signals.sh
- L99 intraday_snapshot 采集
- L105 export_alert.py(C6 预警分)
- L111 export_alert_analyze.py(40 宽基+行业预警分析)
- L118 export_etf_score_list.py(全市场1385只ETF评分)
- L125 export_notifications.py(浏览器通知源)
- L132-141 public_fund stage0-daily + export + R2
- L147 compute_all_scores + export_fund_score
- L155 结束
- L233 daily_summary_email(在此,数据已全部就绪)
- L245 backup_db.sh

### 1.3 `scripts/gen_rss.py` (158 行)

- **数据源**:`summary_history.json` 取最近 30 条
- **生成**:`static-site/data/feed.xml`(RSS 2.0)
- **调度**:`deploy.sh` L163-169 每次 deploy 跑(每次部署刷新)
- **RSS item 结构**:title(`YYYY-MM-DD 收盘 | 恐贪指数 XX.X | 情绪标签`)+ description(涨跌/量能/买卖点/板块/冰点纯文本)+ pubDate + guid
- **复用价值**:RSS 已是"每日总结历史"的对外渠道,任何 summary 字段扩展自动进 RSS

### 1.4 关键发现:已有"每日总结"生成逻辑 `app/compute/market_summary.py` (416 行)

**这是现有规则总结的核心,不是只读 DB 拼数据,而是有完整规则引擎**:

- `generate_summary(date)` (L71-395):从 DB 拼 summary 文字
- 数据源(全部从 sentiment.db):
  - `score_daily` 表:a_sentiment / fear_greed / 11 个情绪分 / is_freeze
  - `index_daily` 表:sh(上证) pct_change/close + sw_*(申万行业)涨跌幅+net_inflow
  - `daily_metric` 表:a_width_up_count / a_width_down_count / a_zt_count / a_dt_count / a_amount / a_nh_52w / a_nl_52w / a_nhnl_52w / a_ma_bullish / a_ma_bearish
  - `signal_daily` 表:buy / buy_aux / sell 信号计数
- 规则化描述函数:
  - `_sentiment_desc(score)`:7 档(极度悲观->情绪亢奋)
  - `_volume_desc(amount, avg5)`:5 档量能(显著放量/温和放量/量能平稳/温和缩量/显著缩量)
  - 涨跌家数比 -> 5 档(普涨/多数上涨/涨跌互现/多数下跌/普跌)
  - 新高新低 -> 4 档描述
  - 均线多空 -> 5 档描述
- **输出字段**(L367-395,26 个字段):
  ```
  date, generated_at, summary(段落长版), summary_short(一句话),
  sentiment_label, sentiment_score,
  fear_greed_value, fear_greed_label, is_freeze, freeze_info,
  volume_label, volume_amount, sh_pct, sh_close,
  up_count, down_count, zt_count, dt_count, buy_count, sell_count,
  nh_count, nl_count, ma_bullish, ma_bearish,
  top_industries[], bottom_industries[]
  ```
- **summary 段落长版示例**(20260325):
  > 3月25日A股乐观积极(恐贪指数66,贪婪)。上证指数涨1.30%至3932点,普涨(4610家上涨、515家下跌),涨停0家、跌停0家。成交额21792亿,量能平稳。共11个买点、1个卖点。无指数创年度新高/新低。0个多头、4个空头,偏空震荡。领涨板块:综合、通信、有色金属。

### 1.5 数据导出 `static-site/export.py` L406-411, L667-671

```python
def export_summary_history(days: int = 90):
    """静态站无后端,预生成 summary_history.json 供前端"更多"弹窗本地分页。"""
    return queries.summary_history(get_conn(), 0, days)

# L667-671
counts["summary.json"] = write_json(DATA_DIR / "summary.json", export_summary())
counts["summary_history.json"] = write_json(DATA_DIR / "summary_history.json", export_summary_history())
```

- `summary.json`:当日单条(含 summary + summary_short + 全字段)
- `summary_history.json`:{items:[90条], total, offset, limit} 倒序
- 导出由 export.py 在 pipeline 内跑,deploy.sh 推 git 上线

### 1.6 前端首页"首盘小结"位置(确认是现有 summary-banner)

**首页已有 summary-banner 横幅,这就是用户说的"首盘小结"**(`static-site/app.js` L7121-7184):

```js
// renderOverview() L7121
fetchJSON("./data/summary.json").then(async (s) => {
  if (s && s.summary) {
    // ... 盘中/收盘判断
    const banner = document.createElement("div");
    banner.className = "summary-banner";
    banner.innerHTML = `<div class="summary-top">
      <span class="summary-title">${titleText}</span>
      <span class="summary-title-tags">${sentimentBadge}${fgBadge}${freezeBadge}</span>
      <span class="summary-meta">
        ${snapBadge}<span class="summary-time-label">${_tLabel2}</span>${_pulse2}
        <button class="summary-history-btn" title="查看历史收盘分析">📜 更多</button>
      </span>
    </div>
    <div id="banner-chips-host">${renderSummaryChips(s, snap)}</div>`;
    content.insertBefore(banner, content.firstChild);  // 顶部第一个
    const histBtn = banner.querySelector(".summary-history-btn");
    if (histBtn) histBtn.addEventListener("click", openSummaryHistoryModal);
  }
});
```

- **位置**:`content.insertBefore(banner, content.firstChild)` - 首页 content 顶部第一个,在预警条 renderAlertBar 之后
- **5 态切换**:📍收盘小结 / ⏰午休小结 / ⏰盘中动态小结 / 盘中横幅(T-1 summary + T 实时 snap) / 收盘后同日横幅
- **chips 行**(`renderSummaryChips` L5190-5219):上证涨跌幅 + 涨跌家数 + 成交额量能 + 涨停跌停 + 买卖点 + 新高新低 + 均线多空
- **历史弹窗**:`openSummaryHistoryModal` (L15610) -> 读 `summary_history.json` 90 条 -> 分页 30/页 -> 每条显示 date + sentiment_label + fear_greed + freeze + chips(已去裸 summary 文字,L15541)

### 1.7 现有架构总结图

```
DB(score_daily/index_daily/daily_metric/signal_daily)
   ↓ app/compute/market_summary.py::generate_summary()  [规则引擎]
summary dict (26 字段,含 summary + summary_short 文字)
   ↓ app/queries.py::summary_history()  [90天分页]
   ↓ static-site/export.py L667-671  [导出]
static-site/data/summary.json (当日) + summary_history.json (90天)
   ↓ deploy.sh 推 git 上线 + gen_rss.py 生成 feed.xml
   ↓
前端 app.js L7121 summary-banner 横幅 + L15610 历史弹窗
   ↓ update_all.sh L233 daily_summary_email.py
邮件 + RSS + 横幅 + 历史弹窗 (4 渠道)
```

**结论:平台已有完整的"每日总结"管线,只是内容是"今日复盘"而非"预测"。用户需求是在此基础上加预测维度+升级口吻。**

---

## 2. 平台数据源盘点(可用于预测总结)

### 2.1 已在 summary 中的数据(现有规则总结已用)

| 数据 | 来源 | 关键字段 | 预测价值 |
|------|------|----------|----------|
| 恐贪指数 | score_daily | fear_greed (0-100) + label | 极端值反转预测 |
| A股情绪分 | score_daily | a_sentiment (0-100) | 情绪周期位置 |
| 6 宽基情绪分 | score_daily | sentiment_sz50/hs300/csi500/csi1000/cyb/kc50 | 分化判断 |
| 跨市场情绪 | score_daily | cross_market | 全球联动 |
| 上证指数 | index_daily | sh pct_change/close | 趋势 |
| 涨跌家数 | daily_metric | a_width_up_count/down_count | 普涨普跌 |
| 涨停跌停 | daily_metric | a_zt_count/dt_count | 风险偏好 |
| 成交额 | daily_metric | a_amount + 5日均值 | 量能 |
| 新高新低 | daily_metric | a_nh_52w/nl_52w/nhnl_52w | 内在强势 |
| 均线多空 | daily_metric | a_ma_bullish/bearish/cross | 趋势排列 |
| 买卖点信号 | signal_daily | buy/buy_aux/sell 计数 | 信号密度 |
| 领涨/领跌板块 | index_daily sw_* | pct_change + net_inflow | 资金方向 |

### 2.2 未在 summary 但可补充的预测数据(关键!)

| 数据 | 来源(JSON/DB) | 关键字段 | 预测价值 |
|------|---------------|----------|----------|
| **高位/低位综合预警** | `alert.json` | high.score/level + 8 维 dims(H1-H7) / low.score/level + 8 维 dims(L1-L8) + history[] | **核心预测**:多维共振预警,如"情绪过热+位置偏高+均线转弱"=减仓信号 |
| **信号历史胜率** | `signal_stats.json` | 各指数 6 类信号(buy/buy_aux/buy_special/buy_backup/sell/sell_stop_loss)的 5d/10d/20d win_rate/pl/mean/n/score + frequency | **明日关注**:胜率>60%的买点信号值得跟 |
| **全市场 ETF 评分清单** | `etf_score_list.json` | buy_list/sell_list/hold_list(全市场 1385 只 ETF 评分排序) | **明日关注**:top ETF 标的 |
| **今日信号明细** | overview.json signals_today | 201 条信号(index_id/signal/reason/since_return/since_correct) | **明日关注**:具体标的+触发原因 |
| **国家团队信号** | overview.json nt_signals_today | 国家队 ETF 信号 | 政策底信号 |
| **主力资金净流入** | daily_metric a_fund_main | 当日值(亿) | 资金方向 |
| **两融余额** | daily_metric a_fund_margin | 当日值(亿) | 杠杆水平 |
| **北向资金** | daily_metric a_fund_north | 当日值(亿) | 外资方向 |
| **波指 QVIX** | daily_metric a_qvix_300/1000 | 300/1000 波动率指数 | 预期波动率 |
| **板块轮动指标** | daily_metric a_rotation_5d/10d/20d + a_rotation_concept_5d/10d/20d | 0-100 轮动速度 | 风格切换 |
| **换手率分位** | daily_metric a_turnover_mean/median/p90/p10/gt5_pct | 分位值 | 活跃度 |
| **封板率/连板/炸板率** | daily_metric a_width_fengban_rate/max_lianban/zhaban_rate/seal_rate | 0-1 比例 + 连板数 | 打板情绪 |
| **认购期权** | daily_metric cov_count/cov_premium_median | 数量+认沽认购比 | 期权市场情绪 |
| **量价关系** | daily_metric a_volume_signal/ratio + a_up_down_ratio | 信号 + 比率 | 量价背离 |
| **行业热度图** | overview.json industry_heatmap | list(行业+涨跌幅+资金) | 板块轮动 |
| **期货机构持仓** | DB futures_position | IH/IF/IC/IM 净多仓位 | 机构态度 |
| **期货机构净多历史** | daily_metric csi500/csi1000_position_1y/3y/5y | 历史序列 | 机构趋势 |
| **跨市场** | daily_metric brent/cn10y/cn_us_spread/gold/oil/usdcnh/comex_silver | 全球资产 | 联动预测 |
| **9 宽基+港股+海外实时** | intraday_snapshot.json indices | price/pct_change/open/high/low | 当日强弱 |
| **概念板块** | intraday_snapshot.json concepts | 实时涨跌 | 热点 |
| **浏览器通知源** | notifications.json | 信号/预警/恐贪/异动事件 | 事件汇总 |
| **冰点历史** | overview.json recent_freeze | 近 120 日冰点日 | 阶段底判断 |

### 2.3 预测维度的数据支撑矩阵

| 预测维度 | 可用数据 | 现有数据是否充足 |
|----------|----------|------------------|
| **趋势研判** | 均线多空 + 涨跌家数 + 新高新低 + 跨市场 | ✅ 充足 |
| **量能分析** | 成交额 + 5日均 + 量比 + 换手率分位 + 量价信号 | ✅ 充足 |
| **资金面** | 主力 + 两融 + 北向 + 期货机构持仓 + 行业 net_inflow | ✅ 充足 |
| **情绪周期** | 恐贪 + A股情绪 + 6 宽基情绪 + 波指 + 认购期权 | ✅ 充足 |
| **板块轮动** | 行业涨跌 + rotation_5d/10d/20d + concept rotation + heatmap | ✅ 充足 |
| **风险预警** | high_alert 8 维 + low_alert 8 维 + 封板率/连板/炸板率 | ✅ 充足 |
| **明日关注标的** | 今日 133 个 buy 信号 + signal_stats 胜率 + etf_score_list | ✅ 充足 |
| **历史类比** | summary_history 90 天 + 冰点历史 + alert history | ✅ 充足 |

**结论:平台数据源完全支撑"专业预测总结",数据维度比一般券商晨会还全。**

---

## 3. AI 集成现状(grep 确认)

### 3.1 grep 结果

```
grep -rIn -E 'anthropic|openai|claude|API_KEY|api_key|ANTHROPIC|OPENAI' \
  /Users/linhuichen/code/trade --include='*.py' --include='*.js' --include='*.sh' ...
```

**结果:零 AI/Claude/OpenAI API 集成**。所有匹配均为:
- `Co-Authored-By: Claude <noreply@anthropic.com>`(commit message 尾巴,git 标记)
- `~/.claude/skills/a-stock-data/SKILL.md`(Claude Code skill 库,非项目代码)
- `claude-work-mode/`(工作模式元规范文档)
- `backup_claude_self.sh`(Claude 自备份脚本,非 AI 调用)
- `docs/archive/01-问题清单.md` BUG 修复记录(历史文档)

### 3.2 API key 配置

- 无 `.env` 文件
- 无 `anthropic` / `openai` Python 包(只在 a-stock-data skill 文档里提到 IWENCAI_API_KEY,非项目实际用)
- 无 worker 内 AI 调用(`wrangler.jsonc` 是 CF Workers Static Assets 绑定,非 AI Worker)

### 3.3 结论

**若走 AI 路线,需从零接入**:
1. 申请 Claude API key(用户需有 Anthropic 账号 + 余额)
2. 加 `anthropic` Python 包到 .venv
3. 配 key 到环境变量或 config/secret.json(不入 git)
4. 写调用脚本(prompt 工程 + 调用 + 容错 + 成本控制)
5. 集成到 update_all.sh 或独立 launchd
6. CF Workers 主站(ss.fx8.store)是 Static Assets,不能跑 AI(AI 在本地脚本跑,生成 JSON 上线)

---

## 4. 前端"首盘小结"位置(grep 确认)

### 4.1 grep 结果

```
grep -nE '首盘|首屏|小结|brief|summary|每日预测|每日总结|daily.brief|daily_brief' app.js
```

**结果:无"首盘/首屏/小结/brief/daily_brief"命名的卡片**。命中的都是:
- `summary-banner`(收盘分析横幅,L7121-7184)
- `summary-chips`(横幅 chips 行)
- `summary-history-btn`(📜 更多 按钮)
- `summaryHistoryModal`(历史弹窗,L15610)
- `renderSummaryChips`(chips 渲染函数)
- `summary.json / summary_history.json`(数据文件)

### 4.2 "首盘小结"定位

**用户说的"首盘小结" = 现有 `summary-banner` 横幅**(首页顶部第一个卡片,显示当日总结+chips+历史按钮)。"首盘"是用户口语,指"首页盘面小结"。

### 4.3 首页布局(renderOverview 结构)

```
renderOverview():
├─ renderPurposeNote(content, PURPOSE_NOTES["overview"])  // 顶部说明
├─ renderAlertBar(content)  // C6 综合风险预警条(high_alert>=72红/low_alert>=85蓝)
├─ summary-banner  ← "首盘小结"位置(用户说的这个)
│  ├─ summary-top: 日期标题 + 情绪/恐贪/冰点标签 + 📜更多按钮
│  └─ summary-chips: 上证/涨跌/成交/涨停跌停/买卖点/新高新低/均线
├─ freeze-resonance-banner(条件:≥3宽基冰点时显示)
├─ sectionTitle("① 基础数据区")  // KPI卡片行 + 指数sparkline网格
│  ├─ KPI 卡片(11情绪分 + 核心宽度指标)
│  └─ 10大指数迷你走势 sparkline
├─ sectionTitle("② ...")
├─ ...
```

### 4.4 展示位置选项

| 位置 | 优劣 |
|------|------|
| **A. 扩展现有 summary-banner**(推荐) | 用户认知一致(就是"首盘小结"),无需新卡片,复用历史弹窗 |
| B. 新建"每日预测"卡片(在 banner 下) | 内容分离更清晰,但增加首页卡片数,可能挤占核心 KPI |
| C. 弹窗(横幅加"🔮预测"按钮) | 不占首页空间,但用户需点击才看到,曝光低 |
| D. 二级页(`/daily-brief`) | 历史回看方便,但脱离首页,用户不易发现 |

**推荐 A+C 组合**:横幅扩展显示预测一句话 + "🔮查看详细预测"按钮弹窗(完整预测内容)

---

## 5. 方案 A:AI 生成(Claude API)

### 5.1 生成方式

- **调用**:Python `anthropic` SDK,模型 `claude-sonnet-4-5`(性价比)或 `claude-opus-4`(更专业)
- **位置**:本地脚本 `scripts/gen_daily_brief_ai.py`(CF Workers 主站是 Static Assets,不能跑 AI)
- **集成**:`update_all.sh` 末尾(daily_summary_email 之前,数据全部就绪后)
- **Key 配置**:`config/ai.json`(不入 git,加 .gitignore)或环境变量 `ANTHROPIC_API_KEY`
- **容错**:API 失败/超时/配额耗尽 -> 回退到规则版(方案B)生成,不阻塞主流程
- **成本控制**:
  - prompt 约 2000-3000 token(数据注入)+ 输出 500-800 token
  - claude-sonnet-4-5:$3/M input + $15/M output
  - 单次约 $0.012(0.003+0.012),一年约 $3(250 交易日)
  - 每日 1 次调用,成本极低
- **prompt 工程**:
  - system:"你是专业金融分析师,基于市场数据生成每日预测总结,风格简洁专业,不夸大不模棱两可,给出明确方向判断+风险点+明日关注"
  - user:注入当日全部数据(summary dict + alert dims + signal_stats top + etf_score_list top + signals_today top)
  - 约束:总长 ≤300 字,结构化(今日复盘/明日关注/风险点 3 段),必须引用具体数据(恐贪值/涨跌家数/信号胜率),禁止"可能/或许/也许"模糊表述

### 5.2 数据源

注入 prompt 的数据(全部从现有 JSON/DB 读取,不新增采集):

```python
data_context = {
  "date": "20260804",
  "summary": {...},  # market_summary.generate_summary() 完整输出
  "alert": alert.json,  # high/low 8维 dims + history
  "signals_today_top": overview.signals_today[:20],  # 前20条 buy 信号
  "signal_stats_top": {
    # 各指数 buy 信号 20d 胜率 >60% 的 top 5
    "hscei": {"buy_special": {"20d": {"win_rate": 0.75, "n": 24}}},
    ...
  },
  "etf_score_top": etf_score_list.buy_list[:10],  # 评分 top10 ETF
  "funds": {
    "main": daily_metric.a_fund_main,  # 主力净流入
    "margin": daily_metric.a_fund_margin,  # 两融
    "north": daily_metric.a_fund_north,  # 北向
  },
  "volatility": {
    "qvix_300": ..., "qvix_1000": ...,
    "cov_count": ..., "cov_premium_median": ...,
  },
  "rotation": {"5d": ..., "10d": ..., "20d": ...},
  "broad_indices": intraday_snapshot.indices[:9],  # 9宽基实时
}
```

### 5.3 生成内容结构

```
【今日复盘】(80字)
8月4日A股情绪回暖(恐贪58,贪婪),上证涨0.33%收3822,普涨(4610涨515跌),
成交额1.2万亿(温和放量)。领涨:通信、有色金属、综合。

【明日关注】(100字)
1. 港股突破:恒生企业指数(唐奇安20日突破,前高8418,close8436,20d胜率75%),
   值得关注。
2. 6宽基情绪分化:上证50=37(偏冷)vs 创业板=70(乐观),关注风格切换。
3. 封板率90%(高位),连板7家,打板情绪亢奋,追高需谨慎。

【风险点】(80字)
1. high_alert=49(中性)但 H6均线转弱=85 + H5动量衰退=63,顶背离迹象。
2. 主力净流入517亿但北向-203亿,资金分歧。
3. QVIX_300=22.67(低位),波动率若飙升需减仓。

总长 ≤300 字,3 段结构化。
```

### 5.4 存储历史

- **当日**:`static-site/data/daily_brief.json`(单条,含 date/summary/predict/risk/raw_data_snapshot)
- **历史**:`static-site/data/daily_brief_history.json`({items:[90条], total, offset, limit},与 summary_history.json 同结构)
- **归档**:每日生成时 append 到 history,保留 90 天(滚动)
- **DB 持久化(可选)**:新表 `daily_brief(date TEXT PRIMARY KEY, content TEXT, predict TEXT, risk TEXT, raw_json TEXT, created_at TEXT)`,支持更长历史+后端 API 查询
- **R2 上传**:daily_brief.json 单文件 <5KB,走 CF Workers Static Assets(不进 R2)

### 5.5 前端展示(方案 A+C 组合)

**A. 横幅扩展**(改 renderOverview L7121-7184):

```
┌─────────────────────────────────────────────────────────────┐
│ 📊 8月4日 [乐观积极] [😐贪婪58]    📍收盘小结 18:18  [📜更多]│
├─────────────────────────────────────────────────────────────┤
│ 🔮 AI预测:明日震荡偏强,关注港股突破(胜率75%),警惕均线转弱 │ ← 新增一行
│ [上证+0.33%] [4610涨515跌] [成交1.2万亿] [涨停0/跌停0] ...  │
└─────────────────────────────────────────────────────────────┘
```

**C. 弹窗**(横幅加"🔮AI预测"按钮):

```
┌─ 🔮 8月4日 AI 预测总结 ─────────────────[✕]┐
│                                              │
│ 【今日复盘】                                 │
│ 8月4日A股情绪回暖...                         │
│                                              │
│ 【明日关注】                                 │
│ 1. 港股突破:恒生企业指数...                  │
│ 2. 6宽基情绪分化...                          │
│ 3. 封板率90%...                              │
│                                              │
│ 【风险点】                                   │
│ 1. high_alert=49但H6均线转弱=85...           │
│ 2. 主力+517亿但北向-203亿...                 │
│ 3. QVIX_300=22.67...                         │
│                                              │
│ ── 历史预测 ─────────────────────────────── │
│ 8月3日:震荡偏弱,关注... [命中✓/未命中✗]     │
│ 8月2日:情绪冰点,关注... [命中✓]             │
│  ← 上一页  1/3  下一页 ->                     │
└──────────────────────────────────────────────┘
```

**历史回看**:弹窗内"历史预测"分页 + 命中率统计(可选,需回填实际涨跌)

### 5.6 定时生成

- **时点**:update_all.sh L233 之前(在 daily_summary_email 之前,数据全部就绪后)
- **不新增 launchd**:复用 update_all.sh 的 17:50 调度
- **盘后跑**:只在交易日跑(非交易日 update_all 早期 exit 0,L56-62)
- **失败兜底**:AI 失败 -> 回退规则版(方案B)生成,不阻塞 daily_summary_email
- **盘后时点避开**:15:35/16:00/17:50/20:35 是盘后定时任务时点,但 update_all 自己 17:50 跑,内部串行不冲突(§14 P0 已查)

### 5.7 工作量估时(谨慎估,不偏乐观)

| 任务 | 估时 | 说明 |
|------|------|------|
| 申请 Anthropic API key + 充值 | 0.5h | 用户操作,需信用卡 |
| 加 anthropic 包到 .venv | 0.2h | `uv add anthropic` |
| 配 key(config/ai.json + .gitignore) | 0.3h | |
| 写 `scripts/gen_daily_brief_ai.py` | 4-6h | prompt 工程+数据注入+调用+容错+成本日志 |
| 写 `app/compute/daily_brief.py`(规则兜底版) | 3-4h | 同方案B的核心,作为 fallback |
| 改 update_all.sh L233 之前插入调用 | 0.5h | 失败回退规则版 |
| 改 export.py 导出 daily_brief.json + history | 1h | 复用 summary_history 模式 |
| 改 app.js summary-banner 加"AI预测"行 + 弹窗 | 4-6h | 横幅扩展+新弹窗+历史分页+移动端适配 |
| 改 style.css 加样式 | 1h | |
| bump sw.js + build_min + deploy | 0.5h | |
| 测试(本地+线上)+ prompt 调优 | 4-8h | 多日数据回测 prompt 效果 |
| **合计** | **19-28h** | 约 3-4 个工作日 |

### 5.8 优劣

**优点**:
- 真正"专业金融大佬"口吻,自然语言流畅
- 能综合多维数据给出明确方向判断(规则版难做到)
- 可生成"明日关注"具体标的(规则版只能列信号)
- 历史类比能力强(可引用"类似 2024-08 冰点期")

**缺点**:
- **零 AI 集成,从零接入**(key+SDK+prompt 工程+容错)
- **成本**:虽低($3/年)但需用户有 Anthropic 账号
- **依赖**:API 宕机/限流/配额耗尽时无预测(需规则兜底)
- **预测不准风险**:AI 可能给出错误方向判断,误导用户(需加免责声明)
- **合规风险**:金融预测需谨慎,不能给具体买卖建议(只能"关注"不能"买入")
- **prompt 调优耗时**:需要多日回测才能稳定输出质量
- **不可解释**:用户不知预测依据(规则版可点 chips 看数据)

---

## 6. 方案 B:规则生成(模板拼接,复用 daily_summary_email 数据)

### 6.1 生成方式

- **不调 AI**:纯 Python 规则引擎,模板拼接
- **位置**:`app/compute/daily_brief.py`(新文件,与 market_summary.py 同级)
- **集成**:`static-site/export.py` 调用导出 `daily_brief.json` + `daily_brief_history.json`
- **调度**:复用 export.py 在 pipeline 内跑(无需改 update_all.sh)
- **零成本**:无 API 调用,无 key,无依赖
- **零风险**:规则确定,输出可预测,可解释

### 6.2 数据源

全部从现有 DB(JSON)读取,不新增采集:

```python
def generate_daily_brief(date=None) -> dict:
    conn = get_conn()
    # 1. 复用现有 summary(market_summary.generate_summary)
    from .market_summary import generate_summary
    summary = generate_summary(date)
    
    # 2. 补充预测维度数据(全部从 DB/JSON 读)
    alert = json.load(open("static-site/data/alert.json"))
    signals_today = json.load(open("static-site/data/overview.json"))["signals_today"]
    signal_stats = json.load(open("static-site/data/signal_stats.json"))
    etf_score = json.load(open("static-site/data/etf_score_list.json"))
    intraday = json.load(open("static-site/data/intraday_snapshot.json"))
    
    # 3. 从 daily_metric 取资金面/波动率/轮动
    funds = query_metrics(date, [
        "a_fund_main", "a_fund_margin", "a_fund_north",
        "a_qvix_300", "a_qvix_1000",
        "a_rotation_5d", "a_rotation_10d", "a_rotation_20d",
        "a_width_fengban_rate", "a_width_max_lianban",
        "cov_count", "cov_premium_median",
    ])
    
    # 4. 规则引擎生成预测文字
    return {
        "date": date,
        "review": _gen_review(summary),       # 今日复盘(复用 summary)
        "watch": _gen_watch(signals_today, signal_stats, etf_score),  # 明日关注
        "risk": _gen_risk(alert, funds, summary),  # 风险点
        "trend": _gen_trend(summary, funds, intraday),  # 趋势研判
        "raw": {...},  # 原始数据快照(可解释性)
    }
```

### 6.3 生成内容结构

**规则引擎函数**(每个函数有明确 if-else 规则,可解释):

```python
def _gen_review(summary):
    """今日复盘:复用 summary.summary,精简到 80 字。"""
    return summary["summary_short"]  # 已是一句话

def _gen_watch(signals_today, signal_stats, etf_score):
    """明日关注:取 20d 胜率 >60% 的买点信号 top3 + ETF 评分 top3。"""
    watch = []
    # 1. 高胜率买点信号
    buy_signals = [s for s in signals_today if s["signal"].startswith("buy")]
    for s in buy_signals[:20]:
        stats = signal_stats.get(s["index_id"], {}).get(s["signal"], {})
        win_rate_20d = stats.get("20d", {}).get("win_rate", 0)
        if win_rate_20d >= 0.6:
            watch.append(f"{indexIdToName(s['index_id'])}({s['signal']},20d胜率{win_rate_20d:.0%})")
    # 2. ETF 评分 top3
    for e in etf_score.get("buy_list", [])[:3]:
        watch.append(f"{e['name']}(评分{e['score']:.0f})")
    return "、".join(watch[:5]) or "无明显高胜率信号"

def _gen_risk(alert, funds, summary):
    """风险点:high_alert 命中维度 + 资金分歧 + 量价背离。"""
    risks = []
    # 1. high_alert 命中维度
    for dim in alert["high"]["dims"]:
        if dim["hit"]:
            risks.append(f"{dim['name']}={dim['score']:.0f}")
    # 2. 资金分歧(主力流入 vs 北向流出)
    if funds["a_fund_main"] > 0 and funds["a_fund_north"] < 0:
        risks.append(f"资金分歧(主力+{funds['a_fund_main']:.0f}亿/北向{funds['a_fund_north']:.0f}亿)")
    # 3. 量价背离
    if summary["sh_pct"] > 0 and funds["a_volume_signal"] < 0:
        risks.append("量价背离")
    # 4. 封板率高位
    if funds["a_width_fengban_rate"] > 0.8:
        risks.append(f"封板率{funds['a_width_fengban_rate']:.0%}(高位)")
    return "、".join(risks[:3]) or "无显著风险点"

def _gen_trend(summary, funds, intraday):
    """趋势研判:均线 + 涨跌家数 + 跨市场。"""
    # 规则化判断
    if summary["ma_bullish"] >= 6:
        trend = "多头排列,趋势向好"
    elif summary["ma_bearish"] >= 6:
        trend = "空头排列,趋势偏弱"
    else:
        trend = f"{summary['ma_bullish']}多{summary['ma_bearish']}空,震荡"
    # 加宽基分化
    indices = {i["code"]: i["pct_change"] for i in intraday["indices"]}
    if "sz399006" in indices and "sh000016" in indices:
        spread = indices["sz399006"] - indices["sh000016"]
        if abs(spread) > 3:
            trend += f",风格{'成长' if spread > 0 else '价值'}占优"
    return trend
```

**输出示例**:

```
{
  "date": "20260804",
  "generated_at": "8月4日 收盘预测",
  "review": "8月4日A股情绪回暖,上证涨0.33%,普涨(4610涨515跌),成交额1.2万亿(温和放量)。热点:通信、有色金属",
  "watch": "恒生企业指数(buy_special,20d胜率75%)、恒生指数(buy_special,20d胜率75%)、沪深300ETF(评分85)、中证500ETF(评分82)",
  "risk": "均线转弱=85、动量衰退=63、资金分歧(主力+517亿/北向-203亿)、封板率90%(高位)",
  "trend": "0多4空,震荡,风格成长占优",
  "raw": {...}  # 原始数据快照
}
```

### 6.4 存储历史

- **当日**:`static-site/data/daily_brief.json`(单条)
- **历史**:`static-site/data/daily_brief_history.json`({items:[90条], total, offset, limit})
- **导出**:export.py L667 附近加:
  ```python
  counts["daily_brief.json"] = write_json(DATA_DIR / "daily_brief.json", export_daily_brief())
  counts["daily_brief_history.json"] = write_json(DATA_DIR / "daily_brief_history.json", export_daily_brief_history())
  ```
- **部署**:deploy.sh L308 DATA_FILES 清单加 `daily_brief daily_brief_history`
- **R2**:不进(单文件 <5KB,走 CF Workers)

### 6.5 前端展示(方案 A+C 组合,同方案A)

**横幅扩展**(改 renderOverview L7121-7184):

```
┌─────────────────────────────────────────────────────────────┐
│ 📊 8月4日 [乐观积极] [😐贪婪58]    📍收盘小结 18:18  [📜更多]│
├─────────────────────────────────────────────────────────────┤
│ 🔮 预测:明日震荡,关注恒生企业(胜率75%),警惕均线转弱+资金分歧│ ← 新增
│ [上证+0.33%] [4610涨515跌] [成交1.2万亿] [涨停0/跌停0] ...  │
└─────────────────────────────────────────────────────────────┘
```

**弹窗**(横幅加"🔮预测"按钮):

```
┌─ 🔮 8月4日 每日预测总结 ─────────────────[✕]┐
│                                              │
│ 【今日复盘】                                 │
│ 8月4日A股情绪回暖,上证涨0.33%...             │
│                                              │
│ 【明日关注】                                 │
│ • 恒生企业指数(buy_special,20d胜率75%)       │
│ • 恒生指数(buy_special,20d胜率75%)           │
│ • 沪深300ETF(评分85)                         │
│                                              │
│ 【风险点】                                   │
│ • 均线转弱=85                                │
│ • 资金分歧(主力+517亿/北向-203亿)            │
│ • 封板率90%(高位)                            │
│                                              │
│ 【趋势研判】                                 │
│ 0多4空,震荡,风格成长占优                     │
│                                              │
│ ── 历史预测 ─────────────────────────────── │
│ 8月3日:震荡偏弱,关注...  [实际+0.33%↑]      │
│ 8月2日:情绪冰点,关注...  [实际-0.5%↓]        │
│  ← 上一页  1/3  下一页 ->                     │
└──────────────────────────────────────────────┘
```

### 6.6 定时生成

- **时点**:export.py 在 pipeline 内跑(已有调度,无需改 update_all.sh)
- **位置**:export.py L667 附近,在 summary.json 导出之后
- **依赖**:alert.json / overview.json / signal_stats.json / etf_score_list.json 必须先导出(update_all.sh 顺序:L105 alert -> L111 alert_analyze -> L118 etf_score_list -> L125 notifications -> pipeline 内 export)
- **盘后跑**:复用 update_all.sh 17:50 调度

### 6.7 工作量估时(谨慎估)

| 任务 | 估时 | 说明 |
|------|------|------|
| 写 `app/compute/daily_brief.py` 规则引擎 | 6-8h | 4 个 _gen_* 函数 + 数据读取 + 规则调试 |
| 写 `app/queries.py::daily_brief_history` | 1h | 复用 summary_history 模式 |
| 改 export.py 导出 daily_brief.json + history | 1h | 复用 export_summary_history 模式 |
| 改 deploy.sh DATA_FILES 清单 | 0.2h | L308 加 daily_brief daily_brief_history |
| 改 app.js summary-banner 加"预测"行 | 2-3h | 横幅扩展 |
| 改 app.js 加"🔮预测"弹窗 + 历史分页 | 4-6h | 新弹窗+分页+移动端 |
| 改 style.css 加样式 | 1h | |
| bump sw.js + build_min + deploy | 0.5h | |
| 测试(本地+线上)+ 规则调优 | 3-5h | 多日数据回测规则效果 |
| **合计** | **19-26h** | 约 3-4 个工作日 |

### 6.8 优劣

**优点**:
- **零成本零依赖**:不调 AI,无 key,无 SDK
- **稳定可预测**:规则确定,输出一致,不会出"幻觉"
- **可解释**:每条预测可点开看原始数据(chips + raw 快照)
- **复用现有架构**:与 summary_history 同模式,前端弹窗复用
- **无合规风险**:只列信号+数据,不给买卖建议
- **上线快**:不依赖外部 API,本地跑通即可上线

**缺点**:
- **口吻模板化**:不像"专业金融大佬",像"数据汇总"
- **预测维度有限**:只能列信号+数据,不能综合判断"明天大概率怎么走"
- **无历史类比**:不能引用"类似 2024-08 冰点期"等类比
- **无自然语言流畅性**:规则拼接,读起来生硬

---

## 7. 方案对比 + 推荐

### 7.1 对比矩阵

| 维度 | 方案 A(AI) | 方案 B(规则) |
|------|------------|--------------|
| 专业大佬口吻 | ✅ 强 | ❌ 模板化 |
| 预测准确性 | ⚠️ 可能不准 | ✅ 规则确定 |
| 成本 | $3/年(低) | ✅ 0 |
| 依赖 | ❌ Anthropic API | ✅ 无 |
| 上线速度 | 19-28h | 19-26h(相当) |
| 可解释性 | ❌ 黑盒 | ✅ 可点数据 |
| 合规风险 | ⚠️ 需免责声明 | ✅ 只列信号 |
| 历史类比能力 | ✅ 强 | ❌ 无 |
| 自然语言流畅 | ✅ 强 | ❌ 拼接生硬 |
| 稳定性 | ⚠️ API 宕机需兜底 | ✅ 稳定 |
| 复用现有架构 | ✅ 复用存储+展示 | ✅ 复用存储+展示 |

### 7.2 推荐

**主推方案 B(规则增强版)**,理由:

1. **平台零 AI 集成**:从零接入 AI 成本高(key+SDK+prompt 工程+容错),且平台现有数据已足够支撑规则化预测
2. **生产稳定性 P0**(CLAUDE.md §14):AI 调用是外部依赖,API 宕机/限流/配额耗尽时无预测,违反"生产稳定性第一"原则
3. **可解释性是研究工具立身之本**:用户看预测时需知依据,规则版可点 chips 看数据,AI 版黑盒
4. **合规风险低**:金融预测需谨慎,规则版只列"信号+数据"不给买卖建议,AI 版可能给出错误方向判断误导用户
5. **复用现有架构**:summary_history 90 天历史+横幅+弹窗已就绪,规则版直接扩展,工作量与 AI 版相当但风险更低
6. **数据维度已全**:平台数据源比一般券商晨会还全(§2.3),规则引擎能生成有价值的预测

**可选增强:方案 A 作为"锦上添花"层**(未来):

- 先上方案 B,验证规则引擎效果+用户反馈
- 若用户觉得"不够专业/不够大佬",再叠加 AI 层(AI 读规则版输出 + 原始数据,生成自然语言润色版)
- AI 失败时回退规则版,不阻塞
- 这样既享受 AI 的口吻,又有规则版兜底,稳定性+专业性兼顾

### 7.3 实施建议(方案 B)

1. **第一步**:写 `app/compute/daily_brief.py` 规则引擎(4 个 _gen_* 函数)
2. **第二步**:改 export.py 导出 daily_brief.json + history(复用 summary_history 模式)
3. **第三步**:改 app.js summary-banner 加"🔮预测"行(横幅扩展,最小侵入)
4. **第四步**:加"🔮预测"弹窗 + 历史分页(复用 openSummaryHistoryModal 模式)
5. **第五步**:测试+规则调优(多日数据回测)
6. **第六步**:bump sw + build_min + deploy

**关键约束**:
- 不改 daily_summary_email.py(邮件层不动,读 summary_history 不变)
- 不改 gen_rss.py(RSS 层不动,读 summary_history 不变)
- 不改 market_summary.py(现有总结逻辑不动,daily_brief 是新增层)
- daily_brief.json 是新增文件,不影响现有 summary.json / summary_history.json

---

## 8. 关键文件路径(实施时参考)

### 8.1 现有可复用文件(只读参考)

- `/Users/linhuichen/code/trade/app/compute/market_summary.py` - 规则总结引擎(416 行)
- `/Users/linhuichen/code/trade/app/queries.py` L1297 - summary_history 查询
- `/Users/linhuichen/code/trade/static-site/export.py` L406-411, L667-671 - 导出 summary
- `/Users/linhuichen/code/trade/scripts/daily_summary_email.py` - 邮件层(562 行)
- `/Users/linhuichen/code/trade/scripts/gen_rss.py` - RSS 层(158 行)
- `/Users/linhuichen/code/trade/scripts/update_all.sh` L233 - 调度时点
- `/Users/linhuichen/code/trade/scripts/deploy.sh` L163-169, L308 - RSS 生成 + DATA_FILES 清单
- `/Users/linhuichen/code/trade/static-site/app.js` L7121-7184 - summary-banner 横幅
- `/Users/linhuichen/code/trade/static-site/app.js` L15610-15622 - openSummaryHistoryModal 历史弹窗
- `/Users/linhuichen/code/trade/static-site/app.js` L5190-5219 - renderSummaryChips

### 8.2 数据源文件(读取)

- `/Users/linhuichen/code/trade/static-site/data/summary.json` - 当日总结(26 字段)
- `/Users/linhuichen/code/trade/static-site/data/summary_history.json` - 90 天历史(90 items)
- `/Users/linhuichen/code/trade/static-site/data/overview.json` - scores + signals_today + industry_heatmap + nt_signals_today
- `/Users/linhuichen/code/trade/static-site/data/intraday_snapshot.json` - 9 宽基 + 港股 + 海外实时
- `/Users/linhuichen/code/trade/static-site/data/alert.json` - high/low 8 维预警 + history
- `/Users/linhuichen/code/trade/static-site/data/signal_stats.json` - 各指数 6 类信号 5d/10d/20d 胜率
- `/Users/linhuichen/code/trade/static-site/data/etf_score_list.json` - 全市场 1385 只 ETF 评分
- `/Users/linhuichen/code/trade/static-site/data/notifications.json` - 浏览器通知源
- `/Users/linhuichen/code/trade/data/sentiment.db` - 主 DB(daily_metric / score_daily / signal_daily / index_daily / futures_position)

### 8.3 需新增文件(实施时)

- `/Users/linhuichen/code/trade/app/compute/daily_brief.py` - 规则预测引擎(方案B核心)
- `/Users/linhuichen/code/trade/app/queries.py` - 加 daily_brief_history 函数
- `/Users/linhuichen/code/trade/static-site/export.py` - 加 export_daily_brief / export_daily_brief_history
- `/Users/linhuichen/code/trade/static-site/data/daily_brief.json` - 当日预测(生成)
- `/Users/linhuichen/code/trade/static-site/data/daily_brief_history.json` - 90 天历史(生成)
- `/Users/linhuichen/code/trade/scripts/deploy.sh` - DATA_FILES 加 daily_brief daily_brief_history
- `/Users/linhuichen/code/trade/static-site/app.js` - summary-banner 加预测行 + 新弹窗
- `/Users/linhuichen/code/trade/static-site/style.css` - 新样式

### 8.4 可选(AI 层,方案A)

- `/Users/linhuichen/code/trade/scripts/gen_daily_brief_ai.py` - AI 调用脚本
- `/Users/linhuichen/code/trade/config/ai.json` - API key 配置(不入 git,加 .gitignore)
- `/Users/linhuichen/code/trade/.gitignore` - 加 config/ai.json

---

## 9. 合规 gating 设计(补充:AI 预测 + 预测性段落 gating)

> 主控补充需求:AI 预测只在完整版(compliance_mode=off + hasPrivilege("detailed_view"))显示,合规版(on)不显示。本章节基于代码验证(非转述)设计 gating 方案。

### 9.1 平台合规模式(代码验证确认)

**验证结果**(grep + Read 确认,非转述):

| 机制 | 位置 | 确认内容 |
|------|------|----------|
| `compliance_mode` localStorage | index.html L55-64 | 防闪烁同步 `data-compliance` 属性,默认 'on' |
| `hasPrivilege(name)` 函数 | app.js L17278 | 工具函数,供 gating 调用 |
| 登录用户 privileges | app/auth.py L290 | `"privileges": ["detailed_view"]`(MVP 登录即给) |
| 完整版切换 gating | app.js L17245-17247 | `_mode === "off" && !hasPrivilege("detailed_view")` -> openLoginPromptForDetailed(),不切换 |
| 防绕过 | app.js L17334-17336 | 未登录且 localStorage compliance_mode=off -> 强制回 on |
| 现有 gating 模式 | app.js L102/L2268/L2348/L2719/L14988 | `if (!hasPrivilege('xxx'))` 用于 fund_score/compare/subscribe/trade_sim |
| 切换 UI | app.js L17179-17247 | compliance-option on/off 按钮,即时生效切字典重渲染 |

**合规版语义**:
- `on`(🛡️精简版,默认,对外):简化信号表述,不含具体预测/买卖建议,规避证券合规风险
- `off`(📊完整版,登录特权 `hasPrivilege("detailed_view")`):显示完整信号详情+预测+预判+风险点

### 9.2 gating 粒度设计(段落级,非卡片级)

**关键决策:不是整个 daily_brief 卡片 gating,而是卡片内的"预测性段落"gating**。

理由:
- "今日复盘"是数据汇总(恐贪值/涨跌家数/成交额等),现有 summary-banner 已对外展示,不算预测建议,合规版可见
- "趋势研判"是均线/涨跌家数的客观描述(如"0多4空,震荡"),现有 summary 已含,合规版可见
- "明日关注"列具体标的(高胜率买点信号+ETF 评分 top),属"投资建议"性质,必须 gating
- "风险点"含方向性判断(如"顶背离迹象""资金分歧"),边界模糊,保守 gating
- AI 预测(整段专业分析+预判)全部 gating

**gating 分级**:

| 段落 | 合规版(on,对外) | 完整版(off,登录) | gating 依据 |
|------|------------------|-------------------|-------------|
| 【今日复盘】 | ✅ 显示(数据汇总) | ✅ 显示 | 现有 summary 已对外,非预测 |
| 【趋势研判】 | ✅ 显示(客观描述) | ✅ 显示 | 均线/涨跌家数客观描述,非建议 |
| 【明日关注】 | ❌ 不显示 | ✅ 显示(具体标的+胜率) | 列具体标的属投资建议,合规风险 |
| 【风险点】 | ❌ 不显示 | ✅ 显示(方向性判断) | 含"顶背离/资金分歧"等预判,保守 gating |
| 【AI 预测】(方案A) | ❌ 不显示 | ✅ 显示(专业分析+预判) | 含具体观点/方向判断,合规风险高 |
| 历史预测回看 | ❌ 不显示(预测历史也是预测) | ✅ 显示 | 历史预测含方向判断,同 gating |

**合规版降级展示**(对外可见部分):
```
┌─────────────────────────────────────────────────────────────┐
│ 📊 8月4日 [乐观积极] [😐贪婪58]    📍收盘小结 18:18  [📜更多]│
├─────────────────────────────────────────────────────────────┤
│ 🔮 趋势:0多4空,震荡,风格成长占优                            │ ← 只显示趋势研判
│ [上证+0.33%] [4610涨515跌] [成交1.2万亿] [涨停0/跌停0] ...  │
│                                                              │
│ 📊 完整版含每日预测+明日关注+风险点,登录查看 ->               │ ← 引导登录
└─────────────────────────────────────────────────────────────┘
```

**完整版展示**(登录用户):
```
┌─────────────────────────────────────────────────────────────┐
│ 📊 8月4日 [乐观积极] [😐贪婪58]    📍收盘小结 18:18  [📜更多]│
├─────────────────────────────────────────────────────────────┤
│ 🔮 预测:明日震荡,关注恒生企业(胜率75%),警惕均线转弱+资金分歧│ ← 完整预测
│ [上证+0.33%] [4610涨515跌] [成交1.2万亿] [涨停0/跌停0] ...  │
└─────────────────────────────────────────────────────────────┘
```

### 9.3 前端 gating 实现

**复用现有 `hasPrivilege` + `compliance_mode` 机制**,与 fund_score/trade_sim 同模式:

```js
// app.js summary-banner 渲染处(L7121-7184 修改)

// 1. 判断是否完整版(复用现有判定)
const _isDetailedView = () => {
  try {
    return localStorage.getItem('compliance_mode') === 'off' && hasPrivilege('detailed_view');
  } catch (e) { return false; }
};

// 2. 横幅渲染:gating 预测行
fetchJSON("./data/daily_brief.json").then((brief) => {
  if (!brief) return;
  const showPredict = _isDetailedView();
  let predictRow = "";
  if (showPredict) {
    // 完整版:显示完整预测一句话(明日关注+风险点精简)
    predictRow = `<div class="summary-predict-row">🔮 预测:${brief.private.watch_short} | 警惕:${brief.private.risk_short}</div>`;
  } else {
    // 合规版:只显示趋势研判(客观)+ 引导登录
    predictRow = `<div class="summary-predict-row summary-predict-compliance">🔮 趋势:${brief.public.trend} · <a class="login-link" onclick="openLoginPromptForDetailed()">📊 完整版含每日预测,登录查看 -></a></div>`;
  }
  banner.querySelector(".summary-top").insertAdjacentHTML("afterend", predictRow);
});

// 3. 弹窗渲染:gating 预测性段落
function openDailyBriefModal() {
  if (!_isDetailedView()) {
    // 合规版:不打开预测弹窗(或打开只显示趋势研判的精简版)
    openLoginPromptForDetailed();
    return;
  }
  // 完整版:打开完整预测弹窗(今日复盘+明日关注+风险点+趋势研判+历史)
  ...
}

// 4. 历史预测弹窗:同样 gating
function openDailyBriefHistoryModal() {
  if (!_isDetailedView()) {
    openLoginPromptForDetailed();
    return;
  }
  // 完整版:读 daily_brief_history.json 分页
  ...
}
```

**切换响应**:用户从完整版切回合规版时,已渲染的预测行/弹窗需即时隐藏。复用现有 `applyCompliance` 钩子(app.js L17736):

```js
// app.js applyCompliance 函数内追加
function applyCompliance(mode) {
  // ... 现有逻辑 ...
  // 追加:重渲染 summary-banner 预测行(合规版隐藏预测段落)
  const banner = document.querySelector(".summary-banner");
  if (banner && state.tab === 'overview') {
    renderOverview();  // 重新渲染首页横幅(根据新 compliance_mode 决定显示内容)
  }
}
```

### 9.4 后端 gating 实现

**方案 B(规则版,静态 JSON)**:
- `daily_brief.json` / `daily_brief_history.json` 是静态文件,部署到 CF Workers Static Assets,无后端 gating
- **gating 完全在前端**:静态 JSON 含全部段落(含预测),但前端根据 compliance_mode + hasPrivilege 决定渲染哪些段落
- **风险**:技术用户可直接 curl `static-site/data/daily_brief.json` 看到预测内容(绕过前端 gating)
- **缓解(可选)**:
  - 选项1:拆分 JSON,`daily_brief_public.json`(复盘+趋势,对外)+ `daily_brief_private.json`(明日关注+风险点+AI预测,登录 API 返回)
  - 选项2:后端 `/api/daily-brief` 接口加 detailed_view gating(未登录只返 public 段落),静态 JSON 只存 public 段落
  - 选项3:接受前端 gating(技术用户绕过是小概率,合规风险可接受,因 JSON 是公开数据汇总非交互式建议)

**推荐选项3(前端 gating)**,理由:
- 平台现有 fund_score/trade_sim 也是前端 gating(静态 JSON 可 curl,但 gating 在渲染层)
- 证券合规的关键是"不对公众展示预测",而非"数据不可访问"(数据本身是市场公开数据汇总)
- 拆分 JSON 增加复杂度,且 public/private 边界模糊(趋势研判算 public 还是 private?)

**方案 A(AI 版,动态生成)**:
- AI 预测内容存 DB 或独立 JSON,后端 `/api/daily-brief-ai` 接口加 detailed_view gating:
  ```python
  # app/main.py
  @app.get("/api/daily-brief-ai")
  def daily_brief_ai(date: str | None = None):
      if not is_logged_in() or 'detailed_view' not in get_privileges():
          raise HTTPException(403, detail="需登录完整版查看 AI 预测")
      return generate_daily_brief_ai(date)
  ```
- AI 预测 JSON 不部署到 static-site/data/(不公开),只通过登录 API 返回
- 规则版的 public 段落(复盘+趋势)仍走静态 JSON

### 9.5 合规版 vs 完整版展示对比

| 元素 | 合规版(on,对外) | 完整版(off,登录) |
|------|------------------|-------------------|
| summary-banner 横幅 | ✅ 显示(现有,复盘+chips) | ✅ 显示(现有+预测行) |
| 预测行(横幅内) | 只显示趋势研判+登录引导 | 显示完整预测(明日关注+风险点) |
| 🔮 预测弹窗 | ❌ 不打开(弹登录提示) | ✅ 打开(4段完整) |
| 📜 历史预测弹窗 | ❌ 不打开(弹登录提示) | ✅ 打开(历史预测分页) |
| AI 预测(方案A) | ❌ 不显示 | ✅ 显示(专业分析) |
| daily_brief.json 静态文件 | 技术上可 curl(前端不渲染预测段) | 前端渲染全部 |
| /api/daily-brief-ai 接口 | 403(未登录) | 返回 AI 预测内容 |

### 9.6 对方案 A/B 的影响调整

**方案 B(规则版)调整**:
- `daily_brief.json` 结构调整为含 `public` + `private` 两组字段:
  ```json
  {
    "date": "20260804",
    "public": {
      "review": "...",      // 今日复盘(合规版可见)
      "trend": "..."        // 趋势研判(合规版可见)
    },
    "private": {
      "watch": "...",       // 明日关注(完整版才显示)
      "risk": "..."         // 风险点(完整版才显示)
    },
    "raw": {...}
  }
  ```
- 前端根据 `_isDetailedView()` 决定是否合并 private 段渲染
- 工作量:+1h(字段拆分+前端 gating 逻辑),总工作量 20-27h

**方案 A(AI 版)调整**:
- AI 预测内容不进 static-site/data/,存 DB 或独立私有 JSON
- 后端 `/api/daily-brief-ai` 接口加 detailed_view gating(复用现有 is_logged_in/get_privileges)
- 前端完整版 fetch `/api/daily-brief-ai`(带 cookie),合规版不 fetch
- 工作量:+2h(后端接口+gating+前端 fetch 调整),总工作量 21-30h

**推荐组合(调整后)**:
1. **第一阶段(方案 B + gating)**:规则版预测,public 段落(复盘+趋势)对外,private 段落(明日关注+风险点)登录可见。前端 gating,静态 JSON 含全部字段但前端控制渲染
2. **第二阶段(方案 A 锦上添花)**:AI 预测走后端 API,detailed_view gating,不进静态 JSON。规则版作为 AI 失败兜底
3. **gating 统一**:两阶段共用 `_isDetailedView()` 判定,UI 一致(合规版看复盘+趋势+登录引导,完整版看全部)

### 9.7 gating 实施清单(方案 B 第一阶段)

| 任务 | 估时 | 说明 |
|------|------|------|
| `daily_brief.json` 字段拆分 public/private | 0.5h | 规则引擎输出分两组 |
| 前端 `_isDetailedView()` 工具函数 | 0.3h | 复用现有 compliance_mode + hasPrivilege |
| 横幅预测行 gating 渲染 | 1h | 完整版显示预测,合规版显示趋势+登录引导 |
| 预测弹窗 gating(openDailyBriefModal) | 0.5h | 合规版弹登录提示 |
| 历史预测弹窗 gating | 0.5h | 同上 |
| applyCompliance 切换响应 | 0.5h | 切回合规版时隐藏预测段 |
| 测试(合规版/完整版切换) | 1h | 验证 gating 不绕过 |
| **合计** | **4.3h** | 加到方案 B 总工作量 |

**方案 B 调整后总工作量**:19-26h + 4.3h = **23-30h**(约 3-4 工作日)

---

## 10. 调研结论

## 10. 调研结论

1. **平台已有完整"每日总结"管线**(market_summary 规则引擎 -> summary.json + 90天历史 -> 邮件+RSS+横幅+弹窗 4 渠道),内容是"今日复盘"
2. **用户要的"预测总结"是在此基础上叠加预测维度**(明日关注+风险点+趋势研判),并升级口吻
3. **"首盘小结"= 现有 summary-banner 横幅**(首页顶部第一个卡片,用户口语指此)
4. **平台数据源完全支撑预测**(§2.2 列了 20+ 项可用数据,涵盖趋势/量能/资金/情绪/板块轮动/风险预警/明日关注标的/历史类比 8 维度)
5. **平台零 AI 集成**(grep 确认无 anthropic/openai/API_KEY),走 AI 路线需从零接入
6. **推荐方案 B(规则增强版)+ 段落级 gating**:零成本零依赖稳定可解释,工作量与 AI 版相当但风险更低
7. **可选方案 A(AI)作为未来"锦上添花"层**:先上规则版验证,再叠加 AI 润色(AI 失败回退规则版)
8. **合规 gating(§9)**:复用现有 compliance_mode + hasPrivilege("detailed_view") 机制,段落级 gating(今日复盘/趋势研判对外可见,明日关注/风险点/AI预测登录可见)。方案 B 前端 gating(静态 JSON 含全部字段,前端控制渲染),方案 A 后端 API gating(AI 预测不进静态 JSON,登录 API 返回)
9. **工作量**:方案 B 约 23-30h(含 gating 4.3h,3-4 工作日),方案 A 约 21-30h(含 gating 2h,3-4 工作日)

---

> 调研完成。本报告只读不改,未修改任何文件。实施时由主控派 implement agent 执行。
gating 章节追加完成 20:17:53 - 报告含 §1-§10,§9 为合规 gating 设计(代码验证+段落级 gating+前端/后端实现+方案调整+实施清单)
