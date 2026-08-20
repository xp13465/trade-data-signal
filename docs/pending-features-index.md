# 已落档未开发功能索引(pending-features-index)

> **用途**:团队共享"未开发功能地图"。任何开发任务开工前对照本表,确认方案已出的待做项,避免多子 agent 只顾自己的活、漏做已落档方案。
> **生成**:2026-08-12 盘点 agent 产出。来源:docs/ 81 份 md + TASKS.md 待办 + 代码层验证(grep 结论均带证据,非臆断)。
> **路径整理(2026-08-14)**:docs/ 已按主题拆分,凯利文档移入 `docs/kelly/{mining,combo,position,backtest-ai,toggle,analysis}/`、walk-forward/claude-md-reorganize 系列移入 `docs/archive/`。本表内 kelly-* / walk-forward-* 引用路径均已同步为新路径。23:45 cron 定期重建**(`.claude/scheduled_tasks.json` L49 prompt 用 git log 扫新增文件)**会自然用新路径,无需额外改。
> **最近更新**:2026-08-20(pending-features-index 治理批量执行:researcher 逐条核 commit 实锤 + 用户拍板,**37 条真完成移入 done-list**(docs/tasks-done-list.md「2026-08-20 pending-features-index 治理批量移入」,含模块一 #1/2/7、模块三 #16/74、模块四 #24/25、模块六 #35/36、模块八 #39-41/43-50/52-55、模块九 #57、模块十 #58-61、模块十一 #63/64/68、模块十三 #73、模块十五 #76-78,并刷新 #63/64/69/73/74 状态为已合 main)、**3 条关闭移除**(#23 飞书阶段3、#33/#81 管理端看板重复登记,记录在 docs/archive/TASKS-done.md「三、关闭记录」;E 组重复登记交叉引用已标:#15见#91、#90见#34、#92见#80);远期项 #45 留待远期全保留)。2026-08-20(TASKS.md 任务治理落地:43 条完成归档 TASKS-done.md、3 条用户拍板关闭移除、L42(SVG P1)改回 active、远期/搁置 11 条(场外方案C/性能P2/管理端看板/场外阶段)移入**模块十六**、8 项被 #27 归档的活跃需求(留言箱/ETF485扩采/公募筛选器/板块轮动/真pin/PWA/订阅推送/overlap delta)**补登记**模块十六 #82-89;TASKS.md 只留活跃,报告 docs/tasks-active-only-clean-20260820.md;cron 23:45 重建兼容——新增模块十六用既有表格格式,不破坏既有节)。2026-08-20 再收尾(user 拍板「task 剩的待办全判远期移 todolist,不留活跃」):TASKS.md **活跃 checkbox 清零**,原留本站的次日开盘 + SVG 大盘 tab 两条也判远期 → 移本表模块十六 **#91 次日开盘 / #92 SVG 大盘 tab**,模块十六 = #79-92;TASKS.md 只留交接/大纲/指针,报告 docs/tasks-active-only-clean-20260820.md)。2026-08-19(并行工作流降级安全 B 方案用户拍板:多agent并行+worktree 收益vs成本量化 docs/parallel-cost-benefit-2026-08-18.md 净账打平到略亏,用户定「降级到安全点」,新增 #70-72 防再犯 C/D 机制实施待办,详见模块十二;同日防再犯 A/B/E 机制+P1 修复已 merge main 782af79d1)。2026-08-18(researcher 四档升级 v2 穷举落档:excludeSpecialBear 判定源 hs300→cyb 验证报告 docs/market-state/kelly-fourtier-v2-multiindex.md + 稳定性补测 docs/market-state/kelly-fourtier-v2-multiindex-stability.md(cyb 总量赢家非逐年稳定,2023 负),新增 #65 待用户拍板)。2026-08-18(v1.1.2 凯利三键改造+历史四档轨迹图已实施待 merge 验收,新增优化批次 B/C/D/E 待办,更新 #61/#46/#51/#56 状态,详见模块十一)。2026-08-16(#58 K档交互对齐首页 + P2修法①后端排除未入样:监控卡 K档按钮组改为 关+K1/2/3/4 共5钮对齐首页「AI仓位建议 K」(sig-kbtn 样式+K1★主推+sig-kbtn-off,点「关」=_overfitState.k=null 退化 filtered/raw),后端 build_topk_kept_map 跳过 ts=None 未入样信号(与首页 _bt_in_universe 同人口, 20260814 旧逻辑top-1=cgb_idx 未入样已排除, 全史剔 1172 条未入样污染);版本串 a276)。2026-08-16(分析参考点AI监控二次迭代完成 #58/#60:K档启用[by_k/filtered_by_k两开关独立]+窗口语义改「显示范围」固定60+❓hover短click详版+reviewer返修4项+SVG 3色基准;版本串 a275)。2026-08-16(每日 cron 同步:分析参考点AI监控三合一上线[默认开+K档UI预留+轻量SVG] + K2C5补跑同口径比值[进行中] + 窗口语义改数据范围[待办],新增 #58-60,移已排除清单)。2026-08-15(每日 cron 同步:AI过滤视图两开关正交上线 + 公示补「+1」+ §23.6 公示完成 + $压缩冲突P0修复,更新 #31/#33/#36/#49,新增 #51-53,移已排除清单)。2026-08-14(每日 23:45 cron 同步:凯利每日池口径穷举重跑 + 20倍本金硬控调研落档,新增 #48-50,更新 #16/#47)。2026-08-13 用户拍板:#14 更名明确位置→远期待办、#16 排队中(依赖K档口径)、#18 关闭移排除清单、#20→远期待办、#21 并入 #17 v5→远期待办。**此后每日 23:45 cron 定期同步**(2026-08-12 用户定:快照会慢慢过时达不到索引效果,需定期刷新),机制见 docs/main-governance.md §23.4 索引维护。2026-08-20 会话新增:**#95 ETF权重龙头个股回测分支**(模块三,数据验证中→已暂停待续,避 v4/flash 高峰期)+ **#94 CLAUDE.md 瘦身 A1+§5.4独立**(模块八,方案已落档待实施),均待高峰后续。
> **口径**:只列"方案已出/结论已定/计划已写,但尚未开发完成"的功能;已上线/已在跑项见文末【已排除清单】。
> **状态标记**:未派 / 排队中 / 部分完成 / 需确认(不确定是否已开发,待主控核)

---

## 一、AI 预测(daily_brief / edge-tts)

| # | 功能 | 出处 | 方案摘要 | 依赖/前置 | 状态 |
|---|---|---|---|---|---|
| 3 | **daily_brief P1-1 周期定位/钟摆位置模板**(恐贪分位+极端提示) | docs/daily-brief-optimization.md §3 P1-1 | trend 段加周期定位模板:恐贪/情绪/新高新低在历史分位,极端值逆向提示 | 需 30 日内 summary_history 支持 | **未实施**(规则版有冰点反向雏形 L540) |
| 4 | **daily_brief P1-3 公募基金持仓/行业配置注入**(中期风格参考) | docs/daily-brief-optimization.md §3 P1-3 | 注入 public_fund_summary 加仓/减仓行业 top 到【趋势研判/中期】,标注季报滞后 | 数据已有(public_fund_summary) | **未实施** |
| 5 | **daily_brief P1-4 明日关注排序分**(胜率×凯利×一致性×近期确认) | docs/daily-brief-optimization.md §3 P1-4 | 用站点回测数据把 AI 关注列表从"模型猜"变"数据排序" | signal_kelly_backtest + signal_stats 已有 | **部分完成**(win_rate 已注入,L302-310;完整排序分未做) |
| 6 | **daily_brief P1-5 日历效应/节假日/月末季末提示** | docs/daily-brief-optimization.md §3 P1-5 | 注入「明日是否月末/季末/长假前/财报季」,仅提示性段落 | 硬编码节假日表,成本低 | **未实施** |
| 8 | **多角色阶段三:事件/新闻面分析师** | docs/ai-predict-multiagent-plan.md §3.2 阶段三 + 数据源实测[`docs/ai-predict-news-macro-research-sources.md`](docs/ai-predict-news-macro-research-sources.md) | ④事件/新闻面分析师,输入当日快讯摘要 | 需事件面数据采集;注入侧 2026-08-16 已把 news 分布进 risk 域(fetch_news 采集已就绪) | **部分完成**(news 数据+注入已进 risk 域;独立的「事件/新闻面分析角色」未新增,仍分布进既有域) |
| 9 | **daily_brief P1-11 reasoner(R1)深度辩论增强** | docs/daily-brief-optimization.md §3 P1-11 | 研究员角色可切 deepseek-reasoner 深度对抗,成本贵 3-5 倍 | 配置已支持(cfg.researcher_model,gen_daily_brief.py L188),默认 deepseek-chat | **未启用**(可选开关,默认关) |

> 本模块 #1/#2/#7 已完成:移入 docs/tasks-done-list.md「2026-08-20 pending-features-index 治理批量移入」,见文末【已排除清单】对应段口。

## 二、走势图 / 图表

| # | 功能 | 出处 | 方案摘要 | 依赖/前置 | 状态 |
|---|---|---|---|---|---|
| 10 | **ETF 弹窗 30 天外长历史(需求2)** | docs/chart-refactor-config-plan.md 需求2(行29) + docs/chart-p2p3-data-source-research.md P2 | ETF 侧缺:etf_score_list.json 只近 30 日 ohlc,需新数据产物 etf/{code}-all.json(数据源 fund_etf_hist_sina 等)+ 弹窗 period tab | **数据源待调研(阻塞项)**;P1 chartLite 组件 | **未派**(调研已出方案) |
| 11 | **场外基金净值走势 + 弹窗历史 + 指标介绍(需求3)** | docs/chart-refactor-config-plan.md 需求3(行30) + chart-p2p3 P3 | 场外基金 tab 无任何走势图;需 fund_nav/{code}.json 导出(fund_daily_nav 2153 万行已有)+ 行点击详情弹窗 | **依赖 fund_basic 字段补齐**(pf-fund-screener-real-requirements,TASKS L1213-1214) | **未派** |
| 12 | **走势图 canvas 轻量组件统一改造**(统一 20+ 处散落实现) | docs/chart-refactor-config-plan.md §4.2/§6(P0 配置框架+P1 canvas 组件) | 全站走势图 echarts/SVG/canvas 三实现重复,统一 canvas 组件 + site.yaml 配置化双实现切换 | P0 配置框架已部分落地(siteCfg/charts.lightweight);本项是"统一组件化"未做 | **未派**(方案待用户确认) |
| 13 | **SVG 轻量版低优先级 fidelity 差异** | docs/home-svg-lite-fidelity-check.md L130(hideOverlap 未实现) + home-svg-fix-review.md P2-1~P2-4 | hideOverlap / zoom 后 tooltip 残留 / tooltip 底部 clamp / slider preventDefault 等小项 | 无 | **未派**(低优先,不阻塞) |

## 三、凯利回测

| # | 功能 | 出处 | 方案摘要 | 依赖/前置 | 状态 |
|---|---|---|---|---|---|
| 14 | **lab_sim 费率客调(策略实验室配对交易;注意 trade_sim 单信号弹窗已上线)** | docs/kelly/analysis/kelly-fee-adjust-sim-eval.md §10.1 | 凯利费率客调已实现;**trade_sim(单信号回测详情弹窗,app.js _tradeSimOpenModal)已上线**(app.js L21530 _SIM_FEE_PRESETS 6档5参数);**lab_sim(策略实验室配对交易,lab.js 卡片)未做**——lab.js 无费率客调控件,只有静态成本对比块 | 复用凯利费率客调模式 | **远期待办**(2026-08-13 用户定:低优先级) |
| 15 | **凯利回测「次日开盘」口径(前端展示/默认口径)** | docs/kelly/position/kelly-nextday-open-backtest.md + TASKS.md L55 | 建议①后续回测/前端展示默认改「次日开盘」口径(收盘固化、次日开盘买入,数据 100% 覆盖)②操作建议:开盘挂 -1% 限价单 | 无 | **未派→见 #91**(模块十六 #91 为同项完整登记:含「次日分批挂单SOP」按钮lab.js 已做 + 待用户拍板是否切默认,重复登记于此) |
| 17 | **凯利 v5 候选方法 4 项** | docs/kelly/mining/kelly-mining-literature.md 行72-76 | Decision set 互斥规则集 / PSM 倾向得分匹配 / 漂移检测(drift)/ NSGA-II 多目标优化。(2026-08-13 并入原 #21 高胜率子群深化:需先扩 ETF 属性维度/样本) | 无 | **未实施**(v5 可选方向) |
| 19 | **港股/全球加 MA60 择时按需扩展** | docs/kelly/analysis/kelly-timing-analysis.md 尾部(L420) | A股 MA60 择时已上线 toggle;港股/全球用 HSI/SPX MA60,样本量小收益有限,按需扩展 | 无 | **未实施**(建议,可选) |
| 20 | **凯利交叉分组卡片可切换二级筛选** | docs/kelly/analysis/kelly-analysis.md L223 | 信号类型×大类交叉卡片数爆炸,建议做成可切换二级筛选而非平铺。交叉分组样本量易<30,实施前先确认象限样本>100 | 无 | **远期待办**(2026-08-13 用户定:交叉分组样本坍塌+置顶已缓解爆炸,ROI 低暂缓) |
| 21 | **高胜率子群深化研究(并入 #17 v5 方向)** | docs/kelly/backtest-ai/kelly-backtest-deepseek-review.md L89 | 两象限表现优异但样本小,下一步分析行业/市值/技术形态特征,扩充样本或找适用场景 | 依赖新数据(行业/市值/技术形态字段,signal_kelly_trades.json 无),样本小(n=85) | **远期待办**(2026-08-13 用户定:并入 #17 v5,需先接入 ETF 属性维度/扩充样本再做) |
| 22 | **凯利过滤层 walk-forward(调阈值验证持续)** | docs/archive/walk-forward-report.md L183 | 过滤层多轮迭代调参有过拟合风险,建议未来对过滤层做 walk-forward | 无 | **未实施**(研究项) |
| 95 | **ETF→权重龙头个股 回测分支(信号出来后买跟踪分第一/前三ETF持股权重最高个股TOP1)** | 2026-08-20 用户新想法 | 现在信号→对标ETF→操作跟踪分最高ETF;新方向=买「跟踪分第一/前三名ETF」持股权重最高个股TOP1(借ETF管理方筛查,比自找行业龙头靠谱),回测对比①是否提高收益 ②ETF第一名vs前3名综合体的龙头个股哪个更稳定 ③补全各周期(熊市/各时间窗口)。**已定:B1/B2/B3 全跑 + 先数据验证不直接全量回测**。产出报告落档+提交main等用户查阅 | **关键卡点=数据源:需 ETF持仓/权重明细 + 个股历史日线(已验证:东财fundf10持仓可拿2019起,个股日线需补采50-200只)** | **已暂停待续**(2026-08-20 用户叫停避 v4/flash 高峰期;researcher 数据验证已启动后停掉,过高峰再续跑) |

> 本模块 #16(Walk-forward)/#74(ai_macro.hit 白名单过滤 41105d6a8)已完成:移入 docs/tasks-done-list.md「2026-08-20 pending-features-index 治理批量移入」。

## 四、飞书通知

| # | 功能 | 出处 | 方案摘要 | 依赖/前置 | 状态 |
|---|---|---|---|---|---|
| _(本模块已无远期项)_ | — | — | — | — | — |

> 本模块 #24/#25 已完成(移入 done-list);#23(飞书阶段3 优化)用户拍板关闭,记录在 docs/archive/TASKS-done.md「三、pending-features-index 治理关闭记录」。

## 五、R2 / 数据产物 / 运维

| # | 功能 | 出处 | 方案摘要 | 依赖/前置 | 状态 |
|---|---|---|---|---|---|
| 26 | **R2 P1:board_etf_map 与 overview 同步(刷新后自动触发重算)+ track_score 百分位基线固定化** | docs/r2-migration-implementation-report.md §3.2/§6.1 | build_board_etf_map.py 刷新后自动触发 export_overview 重算;百分位基线预计算固定化(工作量大可选) | deploy.sh step 0.8 已刷 map;自动联动未做 | **部分完成/需确认** |
| 27 | **R2 P2:R2 上传失败阻断 push + 版本校验** | docs/r2-migration-implementation-report.md §3.3/§6.1 方案3 | deploy.sh 关键文件 R2 上传失败则阻断 push;dataRewriteHandler 对关键文件加 last-modified 校验 | P0 方案1 已加"upload_r2 空时 notify 告警" | **需确认** |
| 28 | **R2 P2:edge cache purge 兜底(deploy.sh 末尾统一 purge / Worker 定时清理 / HIGH_FREQ TTL=5s)** | docs/r2-migration-implementation-report.md §3.3/§6.1 方案5 | deploy.sh 末尾统一调一次 purge_cache 或 Worker 定时清理 | upload_r2 各命令已 purge;deploy 末尾统一 purge 未加 | **部分完成/需确认** |
| 29 | **R2 审计 P1:159335 track_score 跨文件不一致 + 百分位基线动态变化** | docs/r2-migration-implementation-report.md §3.2/§6.2 | board_etf_map=30.2 / index_detail=30.2 / overview=30.9(match_method 不同);基线随候选集变化 | 非 bug 但需关注一致性 | **待办/需确认** |
| 30 | **R2 审计 P2×4:purge 失败告警 / check_data_integrity 覆盖 / _headers 不生效 / upload_r2 不设 Cache-Control** | docs/r2-migration-implementation-report.md §3.3/§6.2 | 详见报告 | check_data_integrity 已补 etf_since_return + trade_sim_indices 校验(脚本 L48/548),其余未做 | **部分完成**(check 已补,其余待办) |
| 31 | **simulate_trade JSON 模式自动调度(launchd 定时)** | docs/r2-migration-implementation-report.md §3.2 P1-2 | update_lab.sh 只跑 --html 模式,trade_sim JSON 需手动触发,建议加 launchd 定时 | update_lab.sh 已含 --all JSON 生成+ R2 上传(2026-08-09 补) | **部分完成/需确认**(定时调度未确认) |
| 32 | **perf 剩余小优化:etf_nt 缓存 / industry 批查** | docs/perf-p1-plan.md L264 | 共省 ~0.9s,收益小改动风险,建议暂不动;若做优先 etf_nt 缓存 | 无 | **未实施**(低优先,建议暂不动) |

## 六、管理端 / 新功能

| # | 功能 | 出处 | 方案摘要 | 依赖/前置 | 状态 |
|---|---|---|---|---|---|
| 34 | **场外基金阶段3:场内外联动(ETF 联接跟踪误差)** | TASKS.md L65 | 阶段1 评分引擎+阶段2 前端 UI 已实现;阶段3 场内外联动未做 | 阶段1/2 已上线 | **未派** |

> 本模块 #35/#36 已完成(移入 done-list);#33(管理端任务看板)与模块十六 #81 为重复登记,用户拍板关闭,记录在 docs/archive/TASKS-done.md「三、pending-features-index 治理关闭记录」。

## 七、数据采集 / 数据源缺口(已识别非功能方案)

| # | 项 | 出处 | 说明 | 状态 |
|---|---|---|---|---|
| 37 | **美股 VIX 采集** | docs/理财专员使用指南.md §5.6(L458) | 无直接 akshare 函数,未采集 | 数据缺口 |
| 38 | **乐咕活跃度 / 东财情绪源** | docs/理财专员使用指南.md §5.6(L459) | 源不稳定/接口待验证,已禁用 | 数据源状态 |

## 八、会话新待办增补(2026-08-12,来源:TASKS #4/#16/#17 + 当日会话产出;由每日 23:45 cron 自动同步维护)

| # | 功能 | 出处 | 方案摘要 | 依赖/前置 | 状态 |
|---|---|---|---|---|---|
| 42 | **上下文优化 3 项** | docs/context-optimization-research.md(2026-08-12) | ①OPT-2 MEMORY.md 索引瘦身 19.8KB→~8KB ②OPT-1 轮询/编排降本(状态门控+夜间降频)③OPT-3 主会话 /clear 分会话+Compact Instructions(context rot,保质量>省token) | 无 | **未派**(等用户拍板顺序) |
| 51 | **§23.6 入样宇宙规则落地**(显式化+校验) | config/universe_rules.yaml + scripts/check_universe_alignment.py(2026-08-14, f27768c85) | 宇宙规则单一事实源(yaml:白名单/入样依赖/排除类别/自我ETF例外) + 4断言对称校验脚本挂 deploy 链 FAIL 阻断上线 | **已完成**(2026-08-21 同步核对:yaml+check 已上线;首页1:1 遵从/8 步联动走查随批次D b317d85c3/e4fdcead4 收尾闭环) |
| 94 | **CLAUDE.md 瘦身 A1 + §5.4 基准独立** | docs/claude-md-slim-a1-5point4-plan.md(2026-08-20) | §18 删元信息(移动去向/已提炼引用清单,约1K)+ §5.4 状态型基准定义独立(权威已在 memory test-baseline-v112-anchor,删根里更简副本约3.5K,行为纪律②③④⑤⑥留根+③引用改memory锚点);总39K→约34.5K(-12%);含核心保留清单+可逆性 | B级(动核心文件CLAUDE.md+跨memory衔接) | **已完成**★(2026-08-20 implementer 全链路+reviewer返修+存量3处修正,feat/claude-md-slim-94@3d9d9cdab+cd8ea5d8e 已 main-merge 推送 d18b2fcb1→cd8ea5d8e;CLAUDEMd +9/-15;方案文档 docs/claude-md-slim-a1-5point4-plan.md 待补完) |
| 96 | **首页「近90日情绪日历」右上角标「最新冰点日」更新为融合口径** | 2026-08-20 用户「情绪日历融合冰点+情绪信号后,角标规则和描述须更新」 | 情绪日历已融合冰点+情绪双信号,但角标「最新冰点日·08-03」仍是只显示冰点日旧口径+描述文案过时;需同步成融合后的口径+文案(§23.3 情绪日历相关展示点对齐) | researcher 已定位(recent_freeze vs sentiment_calendar 不一致根因+改动点清单,角标tip"恐贪"口径不匹配顺带修) | **已完成**(2026-08-20 上线,commit 768a896cd,角标升级「最新情绪日」融合口径;已验证走 §8 三查: main链含+线上a368三站一致+前端展示「最新情绪日」在) |
| 97 | **README 功能亮点段精炼包装成"门面/目录/大纲"** | 2026-08-20 用户「功能亮点介绍太冗长没高级感,README是门面不是说明书,起目录/总结/大纲作用」 | README 功能亮点段(L71-167约97行)现为 changelog 级长文(技术细节/版本史/A-B回测数/折衷说明混在功能里),需精炼成目录式功能卡片(每功能一行标题+一句"你能获得什么"+跳转细节);被砍的技术细节/版本史**不是删**,下沉到对应 docs/** 留指针(§5.3 核心保障);保留参考与致敬段资产 | 方向待用户确认精炼样式(纯文字精简/带图/表格化) | **已完成**(2026-08-20 上线,commit d92df2b58,功能亮点段精炼成 Slogan+三组卡片,细节下沉 docs 留指针) |

> 本模块 #39/#40/#41/#43/#44/#45/#46/#47/#48/#49/#50/#52/#53/#54/#55 已完成:移入 docs/tasks-done-list.md「2026-08-20 pending-features-index 治理批量移入」(其中 #46 与模块十一 #68 同 commit 63fb27391,在 done-list 只记一次)。

---

## 九、运维/一致性待办增补(2026-08-15 cron 同步)

| # | 项 | 出处 | 说明 | 状态 |
|---|---|---|---|---|
| 56 | **signal_notified.json 双副本清理** | 2026-08-15 部署核验 | trade-data/data(权威,8/14=13条) vs trade/data(旧,8/14=11条) 双份;check_signals 读权威份无重发风险,但"直接 cd trade 跑 python"会误读旧副本重发;处置=同步旧副本或 symlink+断言(REPO 必须落 trade-data) | **已完成**(2026-08-21 同步核对:随批次D e4fdcead4 双副本权威化,REPO 落 trade-data 断言链路已建) |

> 本模块 #57(sw.js 注释过时修正)已完成:移入 docs/tasks-done-list.md「2026-08-20 pending-features-index 治理批量移入」。

## 十、分析参考点AI监控增补(2026-08-16 cron 同步)

| # | 项 | 出处 | 说明 | 状态 |
|---|---|---|---|---|
| 62 | **overview.date 盘中过时不更新(前后端"今日"锚过时的根因)** | 2026-08-17 用户报高亮 bug 根因(reviewer 核实) | overview.json 盘中 `date` 字段停在评分日(如 8/14),但 `signals_today` 已含盘中最新信号日(8/17),导致:①首页信号卡今日高亮锚过时(已前端修:信号卡 todayDate 锚 signals_today 最新日期,max 语义,commit 121e6fb63 + 补丁)②走势图 T 日提示 `_todayDateB2` 漏判"今日该指数有信号"(L6005,已上线功能行为,**待用户确认是否连修**,§23.7)③凯利 KPI 预估经 reviewer 核实**非真同类**(数据源本身就是评分日,自洽)。后端根修(盘中重算 overview 时同步 date 到最新交易日)未实施,待前端补丁稳定后评估 | **已完成+闭环**(2026-08-21 同步核对:后端根治 b59c08838 + 走势图 T 日锚 b0c87c183 均在 main,pending 原标「后端根修未定」已闭环;前端高亮 121e6fb63 亦在) |

> 本模块 #58/#59/#60/#61 已完成:移入 docs/tasks-done-list.md「2026-08-20 pending-features-index 治理批量移入」。

## 十一、v1.1.2 与优化批次增补(2026-08-18 cron 同步)

| # | 项 | 出处 | 说明 | 状态 |
|---|---|---|---|---|
| 65 | **优化批次 B:采集层提速** | docs/ab-refactor-bug-reflection.md + docs/optimization-closeout-list.md §3.1 | ab37 baostock 降并发+熔断(10001011 黑名单 re-login 增强)/ ab38 core 采集提速(删 sw 指数注意波及 board_etf_map/凯利/首页 §22/§23.6) | **已完成**(2026-08-21 同步核对:merge 571c18ef7+7ab3dc3fa 在 main,并入 2026-08-20 会话批次) |
| 66 | **优化批次 C:O2 etf_score 提速** | docs/update-all-20260817-88min-analysis.md | export_etf_score_list.py L580 workers 6→8-10+空返降重试,省 2-3min | **已完成**(2026-08-21 同步核对:同 571c18ef7 合入 main) |
| 67 | **优化批次 D:宇宙规则首页 1:1 走查+双副本清理** | pending #51/#56 | 首页读 _bt_in_universe 无自算+8 步联动走查(#51);signal_notified.json 双副本 symlink+断言 REPO 落 trade-data(#56) | **已完成**(2026-08-21 同步核对:merge b317d85c3+e4fdcead4 在 main,宇宙规则收尾+双副本权威化) |

> 本模块 #63(v1.1.2 凯利三键,tag 已打)/#64(历史四档轨迹图 2d5e1621b)/#68(批次E 63fb27391)已完成:移入 docs/tasks-done-list.md「2026-08-20 pending-features-index 治理批量移入」。

## 十二、防再犯 C/D 机制实施(2026-08-19 用户拍板「并行降级安全 B」,任务 #21)

> 用户 2026-08-18 拍板:**「B 降级安全并行」**——保留研究并行+版本发布速度,从根因堵死 worktree 三个新洞(stale base/同文件并发/版本串撞号),防再犯 A/B/E 机制已上 main(782af79d1)当保险。量化依据:docs/parallel-cost-benefit-2026-08-18.md(净账打平到略亏)+ docs/conflict-overwrite-triggers-2026-08-18.md(诱因链三缺口)。全部依赖:先 merge A/B/E main(已做),避免同文件冲突。

| # | 项 | 出处 | 说明 | 状态 |
|---|---|---|---|---|
| 70 | **三缺口① base 新鲜度事前校验**(开工强制 rebase origin/main + commit 前校验 base 新鲜) | docs/conflict-overwrite-triggers-2026-08-18.md 三缺口 | worktree 开工前强制 `git rebase origin/main` 或校验 base 新鲜度;commit 前校验「工作树内容==提交基点」防 stale base 提交(本次 bf8841966 被 e3fa985c3 覆盖根因) | **已完成**(2026-08-21 同步核对:main-merge.sh 三态 rebase+base 新鲜校验,b74368b5a+2cbec0452 在 main) |
| 71 | **C 同文件并发串行工具化 + worktree agent 不 bump 版本串** | docs/conflict-overwrite-rootcause-2026-08-18.md 建议C | app.js/lab.js/common.js 等大文件同时只允许 1 个 agent 持有改动权(主控派单前核对在跑 agent 文件范围,工具化串行排队);版本串统一由主控 merge 时跑一次 build_min+bump(消 aXXX 撞号 + stale bump),worktree agent 不自行 bump | **已完成**(2026-08-21 同步核对:check_file_owners 串行+bump 统一入口,b74368b5a/2cbec0452/8b63a7b9c 在 main) |
| 72 | **D push main 统一入口 + 三缺口③ bump 模式唯一权威** | docs/conflict-overwrite-rootcause-2026-08-18.md 建议D | agent 只推 feat 分支,merge+push main 由主控统一走(含 §24⑤+bump 校验);agent 完成报告必带「base commit + 版本串前后值」;bump 模式唯一权威入口(消除 §24 撞号二义) | **已完成**(2026-08-21 同步核对:main-merge.sh 统一入口机制C/D,b74368b5a 起各 merge 均走此入口) |

## 十三、多指数四档展示扩展(2026-08-19 用户定,纯展示,等安排再实施)

> 背景:hs300 已有四档色带/轨迹图(历史轨迹图 #64 已完成 2d5e1621b)。用户 2026-08-19 看四档升级 v2 多指数稳定性报告后,想其他宽基也展示各自四档。**本项 #73(8代宽基四档展示)已完成(2026-08-19 commit 7872cccbf 已合 main:后端 index_detail 注入 8 宽基 tiers + 前端色带动态化),本节留背景备查,不再有待办项**。原设计:纯展示(每个指数自己的四档,价 vs 自己 MA200 + MA排列),不影响过滤;core5/core8 融合四档不在本项(研究层)。实施前确认各指数 index_daily 数据起点长度(kc50 起点 2020,历史色带短一截属正常)。

> 本模块 #73(8代宽基四档展示)已完成:移入 docs/tasks-done-list.md「2026-08-20 pending-features-index 治理批量移入」。

## 十四、R2 覆盖防护根治(方案1)(2026-08-19 用户定:等稳定后跟进)

> 背景:2026-08-19 盘中线上 overview.json 被 trade 侧旧库(8-18)覆盖(手动 upload_r2.py 未带 REPO,STATIC_DIR 缺省回退 trade,抓走 trade/static-site 旧库 631607B 覆盖 R2)。已实现 方案2(盘中读 trade 侧 abort 哨兵)+ 方案3(统一入口+skill 条款)+ 方案4(上传前 STATIC_DIR vs REPO 一致性比对),根因报告见 `docs/archive/overview-r2-overwrite-repo-env-20260819.md`(implementer 落档)。**方案1(读路径强校验:REPO 缺省不回退 trade)因涉及 lab/trade_sim 合法 trade 回退产物甄别,误伤面需细判,2026-08-19 用户定「落待办,等 2/3/4 稳定后再跟进」**。

| # | 项 | 出处 | 说明 | 状态 |
|---|---|---|---|---|
| 75 | **方案1:upload_r2.py 读路径强校验(REPO 缺省不回退 trade)** | docs/archive/overview-r2-overwrite-repo-env-20260819.md(researcher 方案1) | STATIC_DIR = `os.environ.get("REPO", str(ROOT))` 缺省回退 trade 是破防线点。根治:REPO 未设置 → 拒绝 upload_intraday 级命令(或改 STATIC_DIR 必须显式指向)。**关键难点**:需甄别 upload_r2.py:255(lab JSON)与 :369(trade_sim HTML)两处「design 上允许回退 trade 侧」的合法产物,一刀切拒 trade 会误伤盘后正常上传 → 逐一 cmd_upload_* 甄别哪些该回退、哪些强制 REPO。⚠️**注意(2026-08-19 reviewer 修正)**:原以为「被方案4(一致性比对)兜底覆盖」,但 reviewer 证实方案4 为结构性死闸(源根由 REPO 一次性派生恒一致,不单独触发),实际拦截由方案2(盘中哨兵)承担 → **方案1 并无方案4 兜底,若要在盘后再用手动不带 REPO 上传 trade 侧,仍需方案1 兜底**。故方案1 建议再上,不只「耐心等稳定」 | **待办**(2026-08-19 用户定:等稳定后跟进;reviewer 修正兜底前提后建议再上) | **未派** |

## 十五、TASKS.md 归档盲区改进(2026-08-19 用户催归档清理时发现)

> 背景:TASKS.md 已 233KB。自动归档脚本 `scripts/tasks_archive.py` dry-run 只归 0 块+压缩 1 行,几乎不瘦身。根因:脚本归档规则 `tasks_archive.py` L256 只认 **level 2(`##`)/level 4(`####`)** 的已完成标题,而 TASKS.md 里 **16 个 `###`(level 3)层级的已完成小块**(`### P2-新-A 采集健康度小灯 ✅` 等,全为 2026-07-20~07-29 老堆积)无法被自动识别归档。用户 2026-08-19 要求「做完的都归档,让文件小点可读性高点」。

| # | 项 | 出处 | 说明 | 状态 |
|---|---|---|---|---|
| _(本模块已完成,无远期项)_ | — | — | — | — |

> 本模块 #76(tasks_archive level3 归档 9359f798f)/#77(compress_status_line 熔行 e54adcb1f)/#78(TASKS 任务治理落地)已完成:移入 docs/tasks-done-list.md「2026-08-20 pending-features-index 治理批量移入」。

## 十六、远期/搁置待办 + 归档活跃需求补登记(2026-08-20 TASKS.md 治理移入/补登记)

> 用途:承接 TASKS.md 任务治理后**移出/补登记**的项。两类:①**远期/搁置待办**(标"待排期/周末或下周/滚动优化"等,从 TASKS.md 移出,用户要远期会明说再从本表捞回);②**8 项此前被 #27 归档但语义活跃/待排期的需求**(出处指向 `docs/archive/TASKS-history-archive-20260820.md` 对应段),本表补登记防丢。格式与全表一致(cron 23:45 重建兼容,不破坏既有表结构)。**状态含义**:待排期 / 部分完成 / 未派 / 进行中。**2026-08-20 再收尾**:range 扩为 **#79-92**(新增 #91 次日开盘 / #92 SVG 大盘 tab,原 TASKS.md 本站最后两条 `[ ]` 也按用户拍板判远期移入)。**2026-08-20 治理批量**:本模块 #81(管理端任务看板)= 与模块六 #33 重复登记,用户拍板关闭(记录在 docs/archive/TASKS-done.md「三、关闭记录」);#90 见 #34(场外阶段3 主登记)、#92 见 #80 P2-11(大盘 tab SVG 同项)已加交叉引用防重复实施;其余远期项保留本条。

| # | 项 | 出处 | 方案摘要 | 依赖/前置 | 状态 |
|---|---|---|---|---|---|
| 79 | **场外基金方案C 全量化(step1-8 主体未实施)** | TASKS.md「📋 2026-08-04 场外基金方案C全量化」整块(tasks-active-clean 治理移出) | C1(CF Workers+D1)方案,**步骤逐条(step0 已完成)**:**step1** export_fund_score.py L62 _query_top_funds 补 fund_basic 扩展字段(fund_company/manager/setup_date/scale/management_fee/custody_fee/purchase_fee/strategy/benchmark,点击弹窗用);**step2** 手动触发 weekly 全量评分 compute_all_scores(top_n=None,resume=True) 从 trade-data 跑,验证 fund_score 表 count≈27418;step0=True 15-30 分钟;**step3** D1 创建(wrangler d1 create trade-fund-score)+wranger.jsonc d1_databases binding(FUND_SCORE_DB)+新建 scripts/sync_fund_score_to_d1.sh+pf_score daily/weekly 末尾加同步;**step4** 新建 worker/fund_score.js 分页/筛选/排序/搜索+鉴权(复用 auth.js session)+worker/headers.js 加分发 /api/fund_score;**step5** 前端 app.js L15014 renderOffshoreFund 改分页 fetch /api/fund_score?page=&size=&type=&sort=&dir=&search=,_fundScoreState 加 total,pager 用 total 算页数(549页);**step6** 点击弹窗 openFundScoreDetailModal 5 区块(决策头/凯利仓位/6维度雷达SVG/5风险+经理6维/基础信息);**step7** build_min+bump_asset_version+bump sw.js CACHE_VERSION+deploy;**step8** 调度确认(手动 launchctl start com.trade.pf-score-weekly 测一次)+线上验证 curl /api/fund_score。**step0(upload_r2 调用 bug 3+1 处修复 d5a8c8f84)已完成**,step1-8 未实施 | 需收盘后休盘跑(7.8h 大工程);首步因 fund_basic 字段待补而阻塞(见 #83);前端 fallback 保留 fund_score_top.json(API 未就绪白屏兜底) | **待排期**(2026-08-04 推周末/休盘启动,现 8-20 仍搁置,步骤逐条完整保留可反查) |
| 80 | **全站性能优化 P2(滚动优化按需)** | TASKS.md「📋 2026-08-04 全站性能优化」P2 段(tasks-active-clean 治理移出,P0/P1 已完成归档) | **P2-10**(app.js 17845 行无 code-splitting,短期 requestIdleCallback 延迟非首屏 init 2-3h 已做/长期按 tab 拆 chunk 8-16h 未做);**P2-11**(大盘 tab renderAStock 30+ echarts 改 SVG 或 IntersectionObserver 懒渲染,3-6h,切 tab -500~1000ms;**= TASKS L42 SVG P1 的未做部分**;**#92 与本子项同项**);**P2-15**(offshore_fund_* 85MB 本地 dead weight 清理,1h,确认场外基金路线图后停跑 export_offshore_fund.py+删本地,或移 R2 upload-offshore-fund;已走 R2 上传,本地/update_all 未删未停) | 无;P2-11 与 #80 大盘 tab SVG 同类展示优化 | **待排期**(按需滚动,非 P0/P1 阻塞,三子项逐条保留) |
| 82 | **留言箱完整方案剩余(管理端审核页/留言墙/防滥用四层/MailChannels)** | docs/archive/TASKS-history-archive-20260820.md L521「📋 2026-08-02 留言箱功能」段 | 用户侧已上线(commit b53a312e7:留言+头像菜单+我的留言列表 GET/POST /api/feedback,复用 SUBSCRIBE_KV);**留档待补全**:管理端审核页 admin/feedback.html + 留言墙上墙公示 + 防滥用四层(频控/honeypot/内容约束/审核闸门)+ MailChannels 邮件通知 + FEEDBACK_ADMIN_PASSWORD secret | 待用户定是否补全(公开留言箱必要) | **待排期**(用户侧已上线,#27 归档只留用户侧,补全项未派) |
| 83 | **公募基金筛选器实战版(大工程)** | docs/archive/TASKS-history-archive-20260820.md L595-596 + memory pf-fund-screener-real-requirements(pending #11/#38 关联) | 基金筛选器要实战级(场外):先补 fund_basic 字段(规模/经理/业绩等,pf-stage0 已有部分)→ 指标体系(夏普/回撤/规模/经理业绩/盈利比例/稳定度)→ 前端复用场内 sparkline/弹窗。指示体系字段缺失是前置阻塞 | **需先补 fund_basic 字段**(memory pf-fund-screener-real-requirements:fund_basic 仅 6 字段,须扩规模/经理/业绩) | **待排期**(大工程,需先补 fund_basic;pending #11/#38 已含场外基金项,本条为筛选器实战需求补登记) |
| 84 | **ETF485 全市场扩采集+OHLC(剩余)** | docs/archive/TASKS-history-archive-20260820.md L357-396 | 部分完成(ETF 专属调权 ✅、前端分页+搜索+持仓输入 ✅ 已实施,62只代表 ETF);**剩余**:全市场 485 个 ETF 扩 etf_daily 采集 + OHLC 采集,~200 行 1-2 天;需 akshare 限流风险控制 | 需 OHLC 采集扩(现 etf_daily 只有 close 且仅 12 国家队全量);akshare 限流风险 | **部分完成**(专属调权/前端交互已上线,485 扩采集+OHLC 未派) |
| 85 | **板块轮动(数据受限,待实施)** | docs/archive/TASKS-history-archive-20260820.md L446/L463 | 6 方向之一 F 板块轮动(105 行),受限于 6-7 个月历史数据;其余方向(盘后日报/E/异常波动/W浏览器通知)已完成。待数据历史积累够再实施 | 受限于 6-7 个月板块历史数据量 | **待排期**(数据受限,历史攒够再做) |
| 86 | **真pin 复盘(**多周期同屏对照**)** | docs/archive/TASKS-history-archive-20260820.md L464 | 大工作量 B-2b「真pin 复盘」(200 行)待实施;同批 H 相似形态/各种通知已上线。具体方案见 archive 上下文(价值排序表主控建议:E>B-2a>A>E>…,真pin 属 B-2b 大工作量) | 无 | **待排期**(大工作量,价值排序中游,未派) |
| 87 | **PWA 体验增强(150 行,未实施)** | docs/archive/TASKS-history-archive-20260820.md L464(价值排序表 A6 PWA 未实施)+ L145(A6 PWA 三件套修正已上线) | 已存在(PWA 三件套 044fd34d 已修正 theme_color+sw.js 重写 App Shell CacheFirst);**剩余 PWA 体验增强**(150 行)未实施(价值排序表中 C PWA 位列靠后) | 无(App Shell 已就绪) | **待排期**(三件套已上线,PWA 增益项未派) |
| 88 | **订阅推送(410 行,待实施)** | docs/archive/TASKS-history-archive-20260820.md L464 | 订阅推送(410 行)为剩余 6 方向大工作量项;第一批已做(留言箱/浏览器通知等),订阅推送未派 | 无 | **待排期**(大工作量,未派) |
| 89 | **overlap delta 可比口径(进行中→派实施)** | docs/archive/TASKS-history-archive-20260820.md L97-114 | overlap delta 中报 vs 年报披露范围差异导致偏大(中报2835只 vs 年报5285只);调研产出 2-4 个可比口径方案+推荐+工时,调研完派实施 agent | 调研报告出后派实施;项目 #44 可用口径待用户选 | **进行中**(调研 2026-08-19 进行中,#28;本表补登记防丢) |
| 90 | **场外基金阶段2 UI / 阶段3 场内外联动(远期子项)** | TASKS.md L45-46(tasks-active-clean 治理移出)+ pending #34(阶段3) | 阶段1 评分引擎+阶段2 UI 已在已排除清单(完成);**阶段3**:场内外联动(ETF 联接跟踪误差)未做;阶段2 UI 属方案C 一部分已在 #79。⚠**重复登记:阶段3 主登记 = 模块六 #34(本行为远期链确认,见 #34)** | 阶段1/2 已上线 | **待排期/见 #34**(阶段3 主登记 #34;本条为场外阶段远期链确认不重复实施) |
| 91 | **次日开盘口径确认(真实可执行口径,待用户拍板是否切默认)** | TASKS.md「次日开盘口径」待办(2026-08-20 治理全判远期移出)+ 模块三 #15 | 信号收盘后固化、次日开盘买入是真实可执行口径,成本极低(每日池净利差 -0.01%、每笔1万 -0.57%,"竞价高开吃掉利润"不成立,跳空均值 +0.031%/中位0/>1%仅6.2%)。**🔶 部分完成**:②已做成「次日分批挂单SOP」按钮 lab.js(2026-08-15 SOP,「次日买入玩法」lab-sigkelly-nextday),①「前端展示/回测默认改次日开盘口径」未改——默认仍当日收盘口径,待用户确认是否切。**建议**:①后续回测/前端展示默认改「次日开盘」口径(数据100%覆盖实现成本低)②操作:开盘不追,挂开盘下方 -1% 限价单(未触达按开盘价兜底)→K=1 +844,931/52.81%(+3.8pt)触达率39.8%,挂-2%更深处不划算。报告 docs/kelly/position/kelly-nextday-open-backtest.md(基线可复现/伪跳空剔除/覆盖率100%/A-F二阶近似诚实标注) | 默认当日收盘口径需用户拍板切换 | **待排期/待用户拍板**(用户"明天起床看"后未定,现挂远期;待用户明说再捞回;模块三 #15 已标见本条) |
| 93 | **首页 AI建议N 无 `tds_poscap` key 时不显示(存量非回归)** | 2026-08-20 tester Playwright 线上核验 #29 时发现(上报 §23.7,未改代码) | 首页 AI建议 在 localStorage 无 `tds_poscap` key 时(首次访问)→ kept map 不 build → **AI建议N badge 不亮(显示 0)**;代码 L2666 注释声称"无 key 保持 K=1 主推高亮"但 L2669 `if(_raw)` 实际需要 key。**不影响回测宇宙/推荐算法核心判定**(判核心全 PASS),独立展示层小茬 | 无 | **待做**(存量行为,非 1.1.3 回归;用户 clear 前已被告知,待用户明说或下轮顺手修) | | TASKS.md「SVG P1」待办未做部分(2026-08-20 治理全判远期移出)+ pending #80 P2-11 | **P1 全站扩展已上线(2026-08-20 home SVG 批 commit 293b1d101 + P0 site-config/ETF评分弹窗/皮肤切换 d9a465dc6)**,剩**大盘 tab renderAStock 30+ echarts 改 SVG 或 IntersectionObserver 懒渲染(P2-11,3-6h,切 tab -500~1000ms)**。用户 2026-08-11 追问状态(此前质疑"首页没效果"即 P0 只接 1 消费点,§23.3 举一反三要求覆盖全站走势图渲染点)。⚠**重复登记:同项 = #80 P2-11(本行为待办移出确认,见 #80)** | 与 #80 P2-11 同项(大盘 tab 展示优化) | **待排期/见 #80**(主登记 #80 P2-11;本条为待办移出确认不重复实施) |

## 【已排除清单】已上线/已在跑(不要重复派)

> **2026-08-20 pending-features-index 治理批量**:37 条真完成已从本索引移除 → 移入 docs/tasks-done-list.md「2026-08-20 pending-features-index 治理批量移入(37 条真完成)」(编号:1,2,7,16,24,25,35,36,39-41,43-50,52-55,57-61,63,64,68,69,73,74,76-78);3 条关闭(#23/#33/#81)→ docs/archive/TASKS-done.md「三、关闭记录」。下述按主题列的已排除项为既有历史记录,与治理批量的 done-list 互为补充。

- **凯利**:默认最优组合(仓位K=2+4降亏)、**金额口径=每日资金池等分+top-K**(2026-08-14 恢复 c951dafa8,修正 K=3 33万虚假杠杆;旧"每笔固定1万"为过时口径)、1月调整 J1/J2 并入、positionCap K档、G公示、**全信号表+组合使用建议**(lab.js L8503,2026-08-12)、MA60择时 toggle⑭、降亏过滤31 toggle、凯利费率客调、fade 交互方案一(lab-custom-host--loading,L7620)、稳健核心组合=仅 r8、次日开盘回测报告本身(仅建议未实施,见 #15)、**K档位评级标注+hover评级理由表格**(2026-08-13 上线 4fe5d45bc,展示层不改算法)、**凯利 top-K+质量约束+选择器前向测试 #18**(已关闭 2026-08-13:质量约束两口径负边际不实施;前向测试简单切分已有结论,滚动版并入 #16)、**K2C5 每日池同口径比值补测 #59**(2026-08-16 上线 f5d218492:K2C5 比值4.55(减亏2.88%/损盈0.63%,>2高性价比)K1档取用/K2档不取,K3 比值1.29 维持默认关,落档 kelly-k2c5-dailypool-ratio.md)
- **daily_brief**:**辩论详情入口+弃用标志+结论展示**(2026-08-12 上线 4bc48da1a)、**edge-tts 语音播报**(2026-08-16 上线 a8a4d632f,版本串 a281:后端 gen_daily_brief.py 服务端 edge-tts 合成 daily_brief_tts_<date>.mp3 上传 R2 metadata audio/mpeg,前端 _dbPlayBtn 🔊 按钮 + <audio> 经 /r2/ 代理播,弹窗+历史收盘分析两处 §22 一致,仅 meta.tts_available=true 渲染,rule/minimal 兜底不播,失败不阻塞)
- **SVG**:轻量走势图 P0+P1 全站扩展(首页 sparkline/KPI/分时,app.js L11059/L11077)、SVG 修正主链 a149、home-svg-fix P1-1/P1-2
- **daily_brief**:后端 P0-1/2/3/4 + P1-2(多空辩论随 P0-4)/P1-7/P1-8/P1-9/P1-10/P1-11(配置)/P2-1(cost_log)/P2-2(已知偏差),前端 AI 预测弹窗+命中率+历史结合展示(2026-08-11,app.js L20066-20377)
- **飞书**:阶段1 发送 + 阶段2 接收(lark-oapi 长连接+落盘+launchd)
- **R2**:迁移 P0 方案1(PURGE_SECRET)/方案2(高频 ttl=0)、前端 ./data fallback、备站主动域名策略(_isBackupSite,app.js L3849)、72h 监控(monitor_72h.sh + com.trade.monitor-72h 已加载)、feed.xml 走 R2、staticdata 同步(daily_brief)、bak-audit 残留(A+B 已合 main、signal_kelly_trades ssd 直链已改主站双兜底)
- **首页/信号**(2026-08-14/15 新增上线):**AI过滤视图两开关正交**(489f0bdb4,AI降亏=删除线层/AI仓位=badge层,review PASS)、**公示补「+1」AI宏4+3+1**(cfd37057e,回测剔除类别公示)、**§23.6 公示三处**(d798854aa,AI建议/AI警示/未入样本 tooltip+凯利区)、**§23.6 yaml+check_universe_alignment.py**(f27768c85,单一事实源+对称校验挂deploy)、**迟到信号增量补通知**(887712c27)、**盘后补齐角标 _bt_late**(89076fd1e+be1c2495b)、**8/14信号三修复**(47c23d42d:空态横条+当日已满判宇宙+定稿文案)、**$压缩冲突根治**(69f505072+根治版,terser reserved/keep-fnames)、**调教监控(过拟合监控)B档**(2026-08-15实施:首页走势图卡双曲线+综合风险分绿黄红+5条预警邮件,后端 `scripts/overfit_monitor.py`,21:40定时,设计见 docs/kelly/analysis/kelly-overfit-monitor-design.md)
- **其他**:intraday 自愈 S1-S5+S9、walk-forward-c P1 选项A(sh 去 D1a,已实施)、全球指数盘中实时 15 指数(含港股系 7 个 + ASX200/SENSEX)、场外基金阶段1 评分引擎(6维+5指标+经理+凯利)+阶段2 UI、alert-design 自定义分析 tab(AI预警/AI评分/历史类比,lab.js custom 父tab)、README 命名统一+og.png 更新、P1-1 走向量化(perf,11.87s->6.10s)、staticdata-daily-brief-sync 全部、tasks-archive-maintain、claude-md 重组/role-based-context、signal-finalize-time 两段式(2026-08-14 上线)、**O1 deploy 4遍→1遍+ab39 增量导出**(2026-08-17 上线 657607b3d,update_all 88min→30-40min 提速根因)
