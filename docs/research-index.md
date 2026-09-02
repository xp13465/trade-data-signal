# 作战地图总索引(research-index)

> **定位**:全站「作战地图」(含回测数据/挖掘结论/方法论论证的交易研究报告)**唯一入口速查表**。物理上按专题库归档(塞入即归类,§23.5),本索引串全部 6 库+独立报告,一处可查。
> **维护规则(§23.5)**:新增作战地图报告即追加一行到对应段,不攒;报告本体+配套脚本+复现段四件套齐才算入库。
> 盘点基线:2026-08-22(方案全文见 [battle-map-consolidation-plan-20260822.md](battle-map-consolidation-plan-20260822.md))。
> 字段:**主题 | 性质 | 结论一句话 | 日期 | 报告路径 | 脚本路径 | 复现锚点**

---

## 1. 凯利仓位与降亏(docs/kelly/,六子目录)

> 已归位专题库,树内索引齐([docs/kelly/README.md](kelly/README.md)),此处只收**里程碑级**定版报告;版本链对照(v1.0.0→v1.1.2 基准定义)权威=memory `test-baseline-v112-anchor`。

| 主题 | 性质 | 结论一句话 | 日期 | 报告 | 脚本/复现 |
|---|---|---|---|---|---|
| 亏损特征挖掘 | 一轮挖掘 | 系统性亏损特征(降亏过滤 9 键来源) | 2026-08 上旬 | [mining/](kelly/mining/README.md) | [kelly/scripts/](kelly/scripts/README.md) A-F 组 |
| K2C5 每日池+top-K | 口径定版 | 每日资金池等分+top-K 成为默认口径(K 敏感性/象限校验/按年分解全跑) | 2026-08-14 | [analysis/kelly-k2c5-*.md](kelly/analysis/README.md) 系列 | kelly/scripts/ 同前缀 |
| 四档升级 v2 多指数判定源 | 穷举回测 | 15 套判定源全≥基准,最优 cyb 四档排除两档;按年/回撤/大熊市补测齐;研究层待拍板 | 2026-08-18 | [market-state/ 见段 2](market-state/README.md) | market-state/scripts/kelly_fourtier_v2_*.py |
| 牛市×辅备买全停(第 5 键) | 时段级过滤回测 | 补位口径 K1 -5,166→-1,030、全史 +6,573 五窗全改善;默认关供实测 | 2026-08-22 | [analysis/sim-window-loss-mining-20260822.md](kelly/analysis/sim-window-loss-mining-20260822.md) | kelly/analysis/sim_window_loss_mining_20260822/ |
| 过拟合监控 | 风险分设计 | 实盘 vs 回测命中率偏差量化为风险分,B 档上线 | 2026-08-18 | [analysis/kelly-overfit-monitor-design.md](kelly/analysis/kelly-overfit-monitor-design.md) | 前端 lab.js + 后端 queries |
| AI 宏观穷举/3AI 对比/回测审查 | 回测审查 | AI 宏 7 键默认组合来源与各模型回测审查 | 2026-08 | [backtest-ai/](kelly/backtest-ai/README.md) | kelly/scripts/ |
| 组合元素/仓位上限/toggle | 组合与仓位 | greedy15/excludeAuxCross/cap 分档等组合边际与 K 档敏感性 | 2026-08 | [combo/](kelly/combo/README.md) · [position/](kelly/position/README.md) · [toggle/](kelly/toggle/README.md) | kelly/scripts/ |

## 2. 大盘四档研判(docs/market-state/)

> 已归位专题库,完整索引见 [market-state/README.md](market-state/README.md)。

| 主题 | 性质 | 结论一句话 | 日期 | 报告 | 脚本/复现 |
|---|---|---|---|---|---|
| 四档定义与区分度 | 展示层定稿 | 牛市·主升/上升期/下降期/熊市·主跌四档定义+复现段 | 2026-08 | [market-state-analysis.md](market-state/market-state-analysis.md) | market-state/scripts/market_state_analysis*.py |
| 四档接入凯利过滤 | 穷举回测 | R1_all 替换式 +65,551 主推 / V4d_all 加法 +40,409 备选 | 2026-08 | [kelly-market-state-4tier-utility.md](market-state/kelly-market-state-4tier-utility.md) | market-state/scripts/kelly_4tier_*.py(8 个) |
| 极端窗口+9 模式 | 极端专项 | R1_all 救 94 笔 +7,883 未放真熊 | 2026-08 | [kelly-4tier-extreme-windows-9mode.md](market-state/kelly-4tier-extreme-windows-9mode.md) | 同上 |
| 情绪日历+冰点 pin | 数据生效 | 近 90 日情绪日历上线 overview.sentiment_calendar | 2026-08-20 | [sentiment-calendar-data-live.md](market-state/sentiment-calendar-data-live.md) 等 | market-state/scripts/emotion-*-sim.mjs |

## 3. AI 预测体系(docs/ai-predict/,新库)

> 2026-08-22 归库新建,14 报告+11 挖掘脚本,明细索引见 [ai-predict/README.md](ai-predict/README.md)。

| 主题 | 性质 | 结论一句话 | 日期 | 报告 | 脚本/复现 |
|---|---|---|---|---|---|
| 方向胜率信号挖掘 | 8 年数据挖掘 | 方向锚信号胜率(转空+均线多头 84.2% 等)为自研挖掘成果,AI 预测方向锚来源 | 2026-08-20 | [ai-predict-direction-market-winning-signals-20260820.md](ai-predict/ai-predict-direction-market-winning-signals-20260820.md) | [ai-predict/direction-market-winning-scripts/](ai-predict/direction-market-winning-scripts/)(11 脚本+out/ 产物) |
| 越错越离谱根因 | 根因调研 | AI 预测体系转折点证据(非纯线上 bug) | 2026-08-20 | [ai-predict-offtrack-rootcause-20260820.md](ai-predict/ai-predict-offtrack-rootcause-20260820.md) | 报告内复现段 |
| 离线 A/B 前验证 | 可行性调研 | 方向锚改造零侵入回放验证方案(方案 A) | 2026-08-20 | [ai-predict-offline-ab-frontvalidate-20260820.md](ai-predict/ai-predict-offline-ab-frontvalidate-20260820.md) | scripts/replay_direction_anchor.py |
| 影子模式验证契约 | 验证契约 | 线上零改动旁路落盘,7 真实交易日聚算拍板开/不开/改 | 2026-08-20 | [ai-predict-shadow-validate-20260820.md](ai-predict/ai-predict-shadow-validate-20260820.md) | scripts/aggregate_shadow.py + shadow_track_md.py |
| 反思=因子归因回灌 | 实现说明 | 失败归因到具体误导因子+待规避约束段回灌,默认关 | 2026-08-20 | [ai-predict-reflection-factor-attribution-20260820.md](ai-predict/ai-predict-reflection-factor-attribution-20260820.md) | scripts/gen_daily_brief.py build_attribut_inject |
| 注入面实测 | 调研 | 已有数据逐项实测+注入设计(top5/bottom5 压缩) | 2026-08-16 | [ai-predict-inject-research.md](ai-predict/ai-predict-inject-research.md) | 报告内 §4 |
| 新闻/宏观面方法论+数据源 | 方法论+源实测 | 新闻面/宏观事件日历全景调研与数据源可行性 | 2026-08 | [ai-predict-news-macro-research-methodology.md](ai-predict/ai-predict-news-macro-research-methodology.md) + [sources](ai-predict/ai-predict-news-macro-research-sources.md) | 报告内复现段 |
| 自成长体系 | 方案 | 反思总结闭环(Step 1 已实施) | 2026-08-17 | [ai-predict-self-growth.md](ai-predict/ai-predict-self-growth.md) | scripts/gen_daily_brief.py L2135 段 |
| 多角色辩论改造 | 方案 | 6 角色子 prompt 独立分析互相校验,主编合成(TradingAgents 启发) | 2026-08-11 | [ai-predict-multiagent-plan.md](ai-predict/ai-predict-multiagent-plan.md) | scripts/gen_daily_brief.py L1810 段 |
| TTS 语音播报 | 落地调研 | edge-tts 免费在线合成,失败降级不阻塞 | 2026-08-16 | [ai-predict-tts-plan.md](ai-predict/ai-predict-tts-plan.md) | scripts/gen_daily_brief.py L2743 段 |
| daily_brief 起点调研+完善点 | 最初调研 | 每日专业金融预测总结立项与完善点分析 | 2026-08 上旬 | [daily-brief-research.md](ai-predict/daily-brief-research.md) + [daily-brief-optimization.md](ai-predict/daily-brief-optimization.md) | scripts/gen_daily_brief.py |
| 业界方法论 | 方法论调研 | 投顾式多因子方向研判业界做法 | 2026-08-20 | [ai-predict-director-industry-method-20260820.md](ai-predict/ai-predict-director-industry-method-20260820.md) | — |

## 4. 模拟回测与波动率(docs/trade-sim/ + docs/qvix-rv/)

> 均已归位专题库。

| 主题 | 性质 | 结论一句话 | 日期 | 报告 | 脚本/复现 |
|---|---|---|---|---|---|
| 模拟盘费率方案 | 费用口径 | trade-sim 费率静态方案与配置化(负 CAGR 修复) | 2026-08-19 | [trade-sim/README.md](trade-sim/README.md)(2 报告) | 报告内复现段 |
| QVIX RV 兜底 | 数据源自算 | 期权隐含波指宕机时本地 RV 真异源兜底(口径已公示) | 2026-08-14 | [qvix-rv/qvix-rv-fallback.md](qvix-rv/qvix-rv-fallback.md) + [qvix-data-sources.md](qvix-rv/qvix-data-sources.md)(算法公示) | qvix-rv/scripts/calc_rv.py + data/rv_*.json |

## 5. 历史买卖点回测系列(docs/archive/)

> 已归档,轻量索引见 [archive/README.md](archive/README.md)。01-26 编号买卖点回测系列(01 问题清单→26 行业 buy_aux 全行业扫)+ walk-forward×5 + 08 深度回测三版并存(07-10 / 08-14 / 08-21 数据截止)。

| 主题 | 性质 | 结论一句话 | 日期 | 报告 | 脚本/复现 |
|---|---|---|---|---|---|
| 买卖点策略深度回测(最新刷新版) | 历史回测刷新 | stash 恢复产物,数据截止 2026-08-21(454 行) | 2026-08-21 | [archive/08-买卖点策略深度回测-2026-08-21.md](archive/08-买卖点策略深度回测-2026-08-21.md) | 报告内复现段 |
| 01-26 编号系列 | 历史回测 | 买卖点参数/配对/行业 buy_aux 逐行业回测全记录 | 2026-07~08 | [archive/README.md](archive/README.md) 清单 | a-stock-data/backtest_strategies.py(活脚本) |
| walk-forward×5 | 前向验证 | 买卖点规则 walk-forward 样本外验证系列 | 2026-07~08 | [archive/README.md](archive/README.md) 清单 | 同上 |

## 6. 数据源穷举调研(独立报告)

| 主题 | 性质 | 结论一句话 | 日期 | 报告 | 脚本/复现 |
|---|---|---|---|---|---|
| 全球行情免费源穷举 | 数据源穷举 | 全球指数/期货免费数据源穷举实测(该功能唯一数据层文档,README L80 引用,留原处) | 2026-08 | [docs/global-ticker-free-source-research.md](global-ticker-free-source-research.md) | 报告内复现段 |
| QVIX 免费异源穷举 | 数据源穷举 | optbbs→上交所 IV 自算→本地 RV 三重兜底实测(算法公示位 README L145 引用) | 2026-08-15 | [docs/qvix-rv/qvix-data-sources.md](qvix-rv/qvix-data-sources.md) | qvix-rv/scripts/calc_rv.py |
| 北交所宽度宇宙纳入 | 影响面调研+拍板 | 宽度只算沪深 ~5185 只,北交所 339 不在统计;三方案推荐 C 单独出(不动冻结资产),选 A/C 须先挂 FAPI 定时+验 920 段历史覆盖 | 2026-09-02 | [docs/analysis/beijiao-exchange-width-universe-20260902.md](analysis/beijiao-exchange-width-universe-20260902.md) | 报告内复现段(只读 SQL);索引见 [analysis/README.md](analysis/README.md) |

## 7. 独立活文档(留 docs/ 根,勿搬)

| 文件 | 性质 | 不搬理由 |
|---|---|---|
| [docs/ai-predict-shadow-track.md](ai-predict-shadow-track.md) | 影子追踪总表 | 自动生成活产物:`scripts/shadow_track_md.py` L24 TRACK_MD 硬编码写目标,手改被覆盖 |
| [docs/ai-predict-self-upgrade-roadmap.md](ai-predict-self-upgrade-roadmap.md) | 自升级路线图 | 主控迭代驱动持续更新中的活文档 |
| [docs/daily-brief-range-prediction-spec.md](daily-brief-range-prediction-spec.md) | 区间预测实施规格 | `gen_daily_brief.py` 实施验收依据的活规格 |

---

## 复现

- 盘点与归库方案:[battle-map-consolidation-plan-20260822.md](battle-map-consolidation-plan-20260822.md)(含盘点命令与引用核实命令)
- 归库执行:2026-08-22 implementer,feat 分支 commit(git mv 保历史,`git log --follow` 可溯)
- 关键口径:作战地图=含回测数据/挖掘结论/方法论论证的交易研究报告;工程效能/bug 复盘/操作手册/任务治理不在范围(方案 §五排除项)
