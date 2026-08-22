# analysis/ 凯利分析类报告索引
| kelly-quadrant-loss-elimination.md | **亏损象限识别与剔除验证:用户假设 y1 成立/全周期不成立,细粒度子群降亏键是正解,候选 K2C5港股追涨/K3主关注×概念**(2026-08-15;数据 `data/kelly-quadrant-mining-data.json`+脚本 `scripts/quadrant_mining/`10个)。**§7 口径补测(2026-08-15)**:初版用裸 G(不可操作)测,用户质疑后按 v1.0.0 基准重测(G 用 13万 P≤3d 可操作口径 + F 等 9 模式全测),结论:降亏键对 A/F 短持正贡献、对可操作 G 转负(路径噪声),依玩法模式分裂,结论以 §7 为准。补测数据 `data/kelly-quadrant-opg-data.json`+脚本 `kelly_opg_engine.py`/`kelly_opg_yearly.py` |

> 认知差/费率/收益线性/时机/卡间水印等分析类报告。**如何新增**:报告放本目录(`kelly-<主题>.md`),脚本放 `scripts/`,并同步更新本索引。

| 文档 | 说明 |
|---|---|
| sim-window-loss-mining-20260822.md | **首页模拟回测弹窗亏损结构挖掘:4月暴赚/5月起连亏根因+时段级空仓候选**——三口径判定"过滤有效但不够"(全信号5月起-93,551 vs K1 -5,166);历史连亏段7次检索(段末转熊主跌后3月4/4恢复;当前下降期无先例);「过滤到0」三层查证全允许空仓;246规则穷举唯一全过主推=「A股牛市·主升×辅买∪备买全停」(mode A K1:5-8月-5,166→-256、4月零误伤、2026全年+10,596追平4月末空仓锚点+10,792、全史+66,530→+76,426、A-F六模式同向、G/I不适配);激进版牛主升全停过拟合标注(2025误砍+13,103);8月下降期亏损-3,427暂无稳健规则(结构性盲区);K2-K4基线5-8月亏-1.4万级(2026-08-22;数据v1.1.4 trades generated_at 08-22 16:58;脚本 `scripts/sim_window_loss_mining_20260822/`+`data/results.json`) |
| kelly-walkforward-validate.md | **凯利组合 Walk-forward 滚动验证(样本外):v1.1.0 推荐最优组合(8键全开)样本外有效,不过拟合**——单次切分(选2011-2020/验2021-2026)验段 A收益率 45.17%→59.52%(唯一不衰减反升)、9模式合计 +431,799 领先选段最优 +109,368/基线 +174,161;扩展窗口滚动 3/3 段 ≥选段最优;「选段最优」反而过拟合(验段仅 +322,431);领先主要来自短持 A-F(+134,767),长持 G/H/I 8键不占优(与E24一致);分年 K2C5 正边际占比最高(76.9%)、g15 最不稳但大年贡献巨大(2026-08-16;数据 `kelly-walkforward-validate/data/kelly-walkforward.json`+脚本 `kelly-walkforward-validate/scripts/kelly_walkforward.py`+引擎副本) |
| kelly-k2c5-return-quadrant-check.md | **K2C5 港股追涨剔除双维度校验:用户认知①(除G外净利+收益率双升)对 A-F/H 成立、I 轻微负(-1,365)、G 口径待定;认知②(象限卡片盈利巨多)成立(基线 127/144=88.2% 正,剔后 133/144),港股卡 6 行负全转正**(2026-08-15,本轮新增;v1.0.0 基准 21:14 批,基线 G b0=+203,594 复现;数据 `kelly-k2c5-return-quadrant-check/data/kelly-k2c5-return-quadrant.json`+脚本 `kelly-k2c5-return-quadrant-check/scripts/kelly_k2c5_return_quadrant.py`) |
| kelly-k2c5-frontend-vs-report-reconcile.md | **K2C5 toggle 前端 vs 报告 §7 口径对账:前端=重跑完整 P3d 仿真(b1 乐观)≠简单剔除;报告 §7=b0 保守,G 双口径分裂(b0 -2,256 / b1 +11,779),真实在区间方向不确定**(2026-08-15;数据 `kelly-k2c5-reconcile/data/k2c5-caliber-compare.json`+脚本 `kelly-k2c5-reconcile/scripts/kelly_k2c5_caliber_compare.py`) |
| kelly-k2c5-mode-yearly-breakdown.md | **K2C5 港股追涨剔除边际 9 模式全按年分解:短持 A-F/H 全正、可操作 G(-2,256)/长持 I(-1,365)负,正负交织路径噪声**(2026-08-15;数据 `data/kelly-k2c5-mode-yearly.json`+脚本 `scripts/quadrant_mining/kelly_opg_yearly_allmodes.py`) |
| kelly-k2c5-dailypool-ratio.md | **K2C5(港股追涨剔除)/K3(主关注×概念)每日池同口径减亏比值补测:K2C5 ALL9-K1 减亏2.88%/损盈0.63%/比值4.55(>2高性价比,取用),K2档损盈-0.03%不取;K3 比值1.29(<2 与其默认关自洽)。lab.js ratio 补值**(2026-08-16;单键 standalone on/off 空filter基准,与其他键同口径可比;脚本 `scripts/dailypool_rerun_ratio.py`(扩展 K2C5/K3 包装判定),输入 `static-site/data/signal_kelly_trades.json` 截止2026-08-13) |
| kelly-v110-k2c5-reviewer-online-audit.md | **v1.1.0 K2C5 上线审查(补齐后在线复审):PASS(有条件)**——上轮缺口全修复(overview 数据补标 17 条/k2c5 联动持久化/common+purpose 文案),8 项审查全过,check_universe_alignment 4 断言 PASS、版本串 a266 一致;4 个 P2:后端 K2C5 over-flag 未入样 hk_industry 12 条(queries.py L640 判两值,回测侧实无 hk_industry trade,建议改单值对齐 lab.js)/高亮区文案"8键"vs实际7键/注释残留/线上待 deploy a266(2026-08-15) |
| kelly-v110-nine-rule-audit.md | **v1.1.0 九规则全站审计(7 vs 9):AI降亏/入样/推荐/过滤模块逐处核对**——代码层(queries.py/app.js/lab.js)已全部对齐 9 规则(8键+1类),唯一核心缺口=overview.json 数据产物未重跑(17 条港股 buy_special/buy_backup 漏标 k2c5HkChase,本地+线上主站同);common.js/purpose-notes.js 文案漏 K2C5(轻);K2C5 未纳入 AI宏总开关联动/持久化(待用户确认);check_universe_alignment.py 4 断言 PASS(1类剔除已对齐)(2026-08-15) |
| kelly-track-score-segment-loss.md | **track_score 分段亏损概率穷举回测:假设不成立,不存在稳定黑洞**(2026-08-15,本轮新增;v1.0.0 基准 G 13万 P≤3d b0 基线 156.03%/+202,836;等宽+分位数5/10段信号层+组合层静态、剔除验证全负/微正、交叉维度、按年稳定性;数据 `data/kelly_ts_segment_loss.json`+脚本 `scripts/kelly_ts_segment_loss.py`;附社区亏损单识别方法调研) |
| kelly-overfit-monitor-design.md | **过拟合监控系统设计方案(B档,2026-08-15 已实施)**:每日多维打点 + 4维过拟合指标(回测-实盘偏离/样本外/参数稳定/象限退化)+ 综合风险分(绿黄红)+ 综合预警邮件。实施 `scripts/overfit_monitor.py`(§7 实施说明,含与方案差异诚实标注) |
| kelly-overfit-monitor-ui-audit-20260815.md | **调教监控卡两个问题查证(UI 审计,纯落档不碰生产)**:①卖/止损卖无「回测预期线+风险分」=设计使然非bug(§23.6 入样宇宙,回测仅买入白名单,证据链三层闭环) ②❓弹窗误用 sigCard 专用 `signalHelpTip`(L1684→`termTip`,确认 bug)。另含:口语化阅读指南 + 监控加AI降亏过滤可行性(前端不可行必须后端重算,K档选择器复用 common.js `_aiPoscapRatingPopHtml`,2项待用户确认)+ K2C5缺口(已并入 v1.1.0 收口,commit fee7a21d0) |
| kelly-ai-suggestion-wrong-entry-quantify.md | **量化「错进 AI 建议」:修复前历史次数 + 修复后干净验证**(2026-08-14,本轮新增;814 债类 self-ETF 错进候选 882 次/748 交易日,空数组/无key 仅全档位错进,修复后目标类别错进=0;脚本 `scripts/replay_candidate.py`+`scripts/full_sweep.py`) |
| kelly-bond-inclusion-probe.md | **债类指数纳入回测穷举对比:纳入债类收益率变差,不建议纳入**(2026-08-14,本轮新增;数据 `data/bond_probe_comparison.json`+脚本 `scripts/signal_kelly_backtest_bond.py`) |
| kelly-yearly-vs-drawdown-cognitive-gap.md | **认知差:按年收益率 vs 峰值资金回撤两把尺子**(2026-08-14,本轮新增) |
| kelly-ai-macro8-special-signal-exclusion.md | **AI宏4+3+1调研:债类/波段特殊信号不入样,不做「+1」,三重验证+#25已覆盖**(2026-08-14,本轮新增) |
| kelly-ai-predict-hit-method.md | **AI 预测命中口径 0.1→0.5 说明**(2026-08-14,本轮新增) |
| kelly-analysis.md | 凯利分析总览 |
| kelly-card-comparison-watermark.md | 卡间比较水印(蓝★紫◆全局互比) |
| kelly-fee-adjust-sim-eval.md | 费率调整模拟评估 |
| kelly-fee-adjust.md | 费率调整 |
| kelly-fee-presets.md | 费率预设 |
| kelly-return-linear-analysis.md | 收益线性分析 |
| kelly-timing-analysis.md | 时机分析 |
