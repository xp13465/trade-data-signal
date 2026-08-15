# 凯利回测研究落档总索引(docs/kelly/)

> 凯利仓位控制/回测/组合/减亏/AI预测 研究产物的**统一落档目录**。报告(md)放各主题子目录,运行脚本统一放 `scripts/`,研究数据放各子目录或 scripts 旁。
> 落档规范:CLAUDE.md §23.5(研究产物三层落档:报告/脚本/数据 + 建索引,塞入即归类)。

---

## 子目录职责一览

| 子目录 | 职责 | md 数 |
|---|---|---|
| [analysis/](analysis/README.md) | 认知差/费率/收益线性/时机/卡间水印等**分析**类报告 | 11 |
| [backtest-ai/](backtest-ai/README.md) | AI 预测/3AI 对比/回测审查/宏观穷举**回测**类 | 8 |
| [combo/](combo/README.md) | 组合元素挖掘/组合用法/round 验证**组合**类 | 5 |
| [mining/](mining/README.md) | 亏损挖掘/文献/风格/在线调研**挖掘**类 | 12 |
| [position/](position/README.md) | 仓位上限/每日池/策略AB/分仓行为/回撤/次日买入**仓位**类 | 15 |
| [toggle/](toggle/README.md) | 降亏 toggle 方案/计划 | 2 |
| [scripts/](scripts/README.md) | 全部回测/复算**运行脚本**(按 A-F 组) | 36 脚本 |

---

## 如何新增落档(塞入即归类,勿依赖定期整理)

1. **报告** → 按主题放对应子目录(`analysis/` 分析、`position/` 仓位、`combo/` 组合、`mining/` 挖掘、`backtest-ai/` 回测、`toggle/` toggle),命名 `kelly-<主题>.md`。
2. **脚本** → 统一放 `scripts/`,头部加注释块(用途/日期/结论/依赖/复现),互相 import 的不拆散;多个中间演进版标注"以最新版为准"。
3. **数据/结果 json** → 放报告同目录或 scripts 旁,注明生成命令与日期。
4. **每新增一项,同步在本索引 + 对应子目录 README.md 追加一行**,让索引成为入口而非一次性清单。

---

## 本轮落档(2026-08-15)

- 明日(2026-08-15 #83/#84)报告弹窗完整正文生成脚本:脚本 `scripts/kelly_reports_html.py`(前端展示用, 将 10 份 docs/kelly/**/*.md 经 GFM markdown 转 HTML 输出 `static-site/kelly-reports-content.js`, 供 lab.js 报告弹窗显示完整正文, 与 `md_to_html.py`/kelly-review-notes.js 同模式) + 生成数据 `static-site/kelly-reports-content.js/.min.js`
- 移除「AI仓位建议·历史回测(G模式口径)」面板核对说明:报告 `position/kelly-poscap-history-panel-removal-check.md`(#83 移除依据, 核心结论已被 K 按钮评级/按年窗口增长表/建议指南继承)
- 次日分批挂单买入穷举回测:报告 `position/kelly-nextday-batch-limit-sop.md`(结论:兜底 N=K 最优,每日池 G K1 净+861,375/53.17%,比次日开盘+6.1万,2011-2026 全年份正改善,9模式全正)+ 脚本 `scripts/kelly_batch_limit_*.py`(13个,F 组)+ 数据 `position/data/kelly_nextday_batch_limit_data.json`

## 本轮落档(2026-08-14)

- 债类指数纳入回测穷举对比:报告 `analysis/kelly-bond-inclusion-probe.md`(结论:纳入债类变差不建议;`--include-band` 波段 band_hold 纳入更差,过度交易浪费仓位)+ 脚本 `scripts/signal_kelly_backtest_bond.py` + 数据 `analysis/data/bond_probe_comparison.json`
- 策略A/B 穷举对比:报告 `position/kelly-strategyAB-exhaustive.md` + 脚本 `scripts/strategyAB_compare.py`、`strategyAB_robust.py`、`amount_verify.js`、`kelly_verify_amount.py`
- 认知差(按年收益率 vs 峰值回撤):报告 `analysis/kelly-yearly-vs-drawdown-cognitive-gap.md` + 脚本 `scripts/kelly_yearly_*.js`、`dd_2011_*.js`
- AI 预测命中口径:报告 `analysis/kelly-ai-predict-hit-method.md` + 脚本 `scripts/rebackfill_daily_brief.py`
- 每日池穷举重跑全套脚本:`scripts/dailypool_rerun_*.py`(报告见 `position/kelly-dailypool-exhaustive-rerun.md`)
