# 调教监控卡两个问题查证报告(UI 审计,2026-08-15)

> 对应设计方案:同目录 `kelly-overfit-monitor-design.md`(过拟合监控系统设计 B 档,2026-08-15 已实施)。
> 本期纯审计查证(只落档,不碰生产):回答首页「调教监控」卡(overfit_monitor)两个用户疑问——①卖/止损卖无「回测预期线+过拟合风险分」 ②❓弹窗绑定错。外加主控追加的「监控加 AI降亏过滤」可行性评估 + 顺带发现的 K2C5 缺口(已并入 v1.1.0 收口)。

---

## 1. 问题 1:卖/止损卖无「回测预期线」+「过拟合风险分」= 正常,设计使然,不是 bug

### 1.1 根因:入样宇宙规则(§23.6)

凯利回测只回测**买入白名单 `buy / buy_aux / buy_special / buy_backup`**,卖/止损卖(`SELL_SIGNALS`)从不入回测宇宙 → 无回测成交 → 自然无「回测预期线」、无「过拟合风险分」。这是§23.6 入样宇宙规则的必然结果,不是渲染/数据缺失 bug。

### 1.2 证据链三处闭环

**① 数据层** `static-site/data/overfit_monitor.json`(generated_at=2026-08-15 20:17, version=v1):
- `accuracy.rolling.by_signal.sell.backtest=[]` 空、`sell_stop_loss.backtest=[]` 空;而 `buy/buy_aux/buy_special/buy_backup` 有 365 点满序列
- `overfit.daily_by_dim.sig_type.sell=[]` 空,`buy` 有 357 点
- **actual 侧 sell 有 365 点**(所以能画实盘单曲线)
- 线上 R2 `ssd.fx8.store` 与 `ss.fx8.store` 与本地一致(§22 同步到位)

**② 生成层** `scripts/overfit_monitor.py`:
- L65-66:`BUY_SIGNALS` / `SELL_SIGNALS` 显式分离
- L413-414:`if key in ("sell","sell_stop_loss"): continue` 显式跳过
- L711-757:风险分由「实盘 vs 回测 60 日滚动胜率偏离」派生 → 回测空 ⇒ 序列必空

**③ 渲染层** `static-site/app.js`:
- L1567 / L1588-1592:`btEmpty` / `hasBt` 才 push 回测虚线(空则只画实盘单曲线)
- L1727 副标:「实盘实际(回测仅买入信号)」
- L1630 风险分空态:「无风险分曲线(回测仅买入信号/样本不足)」

### 1.3 用户为什么觉得「其他条件有」

主买 `buy` / 辅买 `buy_aux` / 特买 `buy_special` / 备买 `buy_backup` 恰好是回测白名单的 4 个买入信号;卖 / 止损卖是卖出信号,天然不在白名单。所以表里其他主买系都有回测线,唯独卖系只有实盘红曲线。

---

## 2. 问题 2:❓弹窗绑定错 = 确认 bug

- 调教监控卡的 ❓ **误用了技术信号卡专用的 help 组件 `signalHelpTip()`**
- 证据链:
  - `static-site/app.js` L3146-3148:`signalHelpTip` 自带 `data-signal-help="1"`
  - L3136-3144:全局 click 委托 `[data-signal-help]` **无条件**调 `_openSignalHelpModal()`
  - L3111-3134 / L3105:弹「📊 技术信号 & ETF信号灯参考」modal —— 这个 modal 本是 **sigCard 标题专用**(sigCard 用 L2797 / L10954)
  - 调教监控卡 L1684 误用了它:传入的 hover 文字正确,但点击被全局委托劫持,弹出错误的技术信号 modal

### 2.1 最小改法(非本期落地,仅记录供后续)

```
L1684  signalHelpTip(...)  →  termTip(...)
```
- `termTip` 是纯 hover 组件(L2904,无 `data-signal-help`),点击不再触发错误 modal
- 若想要「点击弹完整说明」,需另行新建调教监控专用 modal(不借用 sigCard 的)

---

## 3. 口语化阅读指南(讲人话,给用户看)

> 摘录 researcher 汇报中「调教监控卡怎么看」整段,收录于此供用户/后续直接取用。

**上曲线(准确率)**:
- 红实线 = 实盘实际;蓝虚线 = 回测预期
- 两条曲线「劈叉」= 过拟合信号(回测告诉你的和实盘差距越来越大)
- 卖/止损卖**只有红线**是正常的(卖出信号不入回测宇宙,见问题 1)

**下曲线(风险分)**:
- 0-100 分,绿 <30、黄 30-60、红 >60
- 4 项加权:回测-实盘偏离 40 / 样本外 25 / 参数稳定 20 / 象限退化 15

**三组按钮**:
- 窗口:30 / 60 / 90 滚动天数
- 评级:高 / 中 / 低
- 类型:买信号 / 卖信号 / ……

**数据时点**:盘后 21:40 打点

**诚实标注**:G(长持)模式口径峰值持仓 136 万,**不可当作实际可成交收益**(可操作性上限 ≤20 倍本金,见 memory `kelly-operability-20x-principal`),看它别当成「能落袋的收益」。

---

## 4. 监控加 AI降亏过滤 可行性评估(主控追加需求)

### 4.1 改名「分析参考点 AI监控」涉及文件全量清点

用户可见标题唯一:**app.js L1683**。其余为注释/文档,不改不影响用户可见:
- app.js L1509 / L1519 / L1678 / L11020(注释)
- style.css L6663(注释)
- README L75(文档,§23.1 必同步)
- docs/pending-features-index.md L123 历史记录**不应改**
- kelly-overfit-monitor-design.md L215(可选)

改名纯文案,但需同步 README(§23.1)+ bump 版本串(§24)。

### 4.2 可行性结论:前端不可行,必须后端重算

`overfit_monitor.json` 是**聚合时序**(`by_signal` 只有滚动序列,365 天),**无每信号明细 → 前端无法过滤后重算**。干净路径 = 后端 `scripts/overfit_monitor.py` 打点时按降亏谓词过滤:

- **回测侧**:`signal_kelly_trades.json` 每笔交易字段全(market_state / rating / signal_date / return_pct),可移植 lab.js 降亏谓词 `passesFade`(L7382 / L7521,含 k2c5)
- **实盘侧**:`signal_daily` 表缺降亏特征 + track_score,但 `queries.py` 已实现信号级可判定子集 `_ai_macro_hit_filters`(L599-657),可复用;需新增 track_score 依赖(读 board_etf_map)

### 4.3 K 档选择器(现成共享组件,可直接复用)

- common.js L533 `_aiPoscapRatingPopHtml()`,首页 + 凯利区共用,无需新建
- UI 顺序 [1,3,4,2] 与用户描述一致:K=1 最激进★主推 / 3 最稳健 / 4 最保守 / 2 次稳健
- 共享状态:`localStorage tds_poscap`

### 4.4 两个待用户确认项

1. **全信号视图保留吗**:建议保留 + 加「AI降亏过滤」开关做对比,便于看过滤前后差异
2. **K 档过滤意义**:监控口径是**信号方向命中**;K 档影响当日进 top-K,**删线层才是主过滤** → 建议优先做删线层过滤,K 档后置

---

## 5. 术语小坑提醒

代码里叫「调教监控」;类型按钮把 `buy_special` 标「特买」;首页信号叫「**追买**」——同一信号两种叫法,后续文案/交互须统一口径,避免用户混淆。

---

## 6. ⚠️ 顺带发现(已并入 v1.1.0 收口,不开放)

首页 AI降亏命中判定**缺 K2C5 键**:
- `queries.py _ai_macro_hit_filters` L599:7 键无 k2c5
- 前端 `app.js _AI_MACRO_FILTER_NAMES` L1968:7 键无 k2c5
- `lab.js _kellyDefaultFilters` L7282:**已含** k2c5HkChase true(实验室侧已对齐,首页侧漏)

> **状态标注**:该缺口**已由 v1.1.0 收口任务修复**(commit `fee7a21d0` + 后续收口),此处仅备案上下文,**不再作为开放问题**。三处键位一致性后续仍以 §23.6 对称校验把关。

---

## 复现

**问题 1(数据侧空序列)**:
```bash
cd /Users/linhuichen/code/trade && python - <<'PY'
import json
d = json.load(open("static-site/data/overfit_monitor.json"))
bs = d["accuracy"]["rolling"]["by_signal"]
print("generated_at:", d.get("generated_at"), "version:", d.get("version"))
for k, v in bs.items():
    print(f"{k}: backtest len = {len(v.get('backtest', []))}, actual len = {len(v.get('actual', []))}")
PY
```
- 输入依赖:`static-site/data/overfit_monitor.json`(数据截止 2026-08-15 20:17)
- 预期:sell / sell_stop_loss 的 backtest len = 0,buy 系 len = 365

**问题 2(❓弹窗绑定,手动复现)**:
1. 打开首页
2. 进入「🎛️ 调教监控」卡
3. 点卡片上的「❓」
4. 观察到弹出「📊 技术信号 & ETF信号灯参考」modal(应为调教监控说明,却弹技术信号 modal=确认 bug)

**生成脚本重跑**:
```bash
cd /Users/linhuichen/code/trade-data && .venv/bin/python scripts/overfit_monitor.py --dry-run
```
- 关键口径一句话:风险分 = 实盘 vs 回测 60 日滚动胜率偏离派生;回测仅买入白名单 buy/buy_aux/buy_special/buy_backup,卖/止损卖不入宇宙(§23.6)
