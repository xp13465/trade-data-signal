# 已落档未开发功能索引(pending-features-index)

> **用途**:团队共享"未开发功能地图"。任何开发任务开工前对照本表,确认方案已出的待做项,避免多子 agent 只顾自己的活、漏做已落档方案。
> **生成**:2026-08-12 盘点 agent 产出。来源:docs/ 81 份 md + TASKS.md 待办 + 代码层验证(grep 结论均带证据,非臆断)。
> **最近更新**:2026-08-14(每日 23:45 cron 同步:凯利每日池口径穷举重跑 + 20倍本金硬控调研落档,新增 #48-50,更新 #16/#47)。2026-08-13 用户拍板:#14 更名明确位置→远期待办、#16 排队中(依赖K档口径)、#18 关闭移排除清单、#20→远期待办、#21 并入 #17 v5→远期待办。**此后每日 23:45 cron 定期同步**(2026-08-12 用户定:快照会慢慢过时达不到索引效果,需定期刷新),机制见 docs/main-governance.md §23.4 索引维护。
> **口径**:只列"方案已出/结论已定/计划已写,但尚未开发完成"的功能;已上线/已在跑项见文末【已排除清单】。
> **状态标记**:未派 / 排队中 / 部分完成 / 需确认(不确定是否已开发,待主控核)

---

## 一、AI 预测(daily_brief / edge-tts)

| # | 功能 | 出处 | 方案摘要 | 依赖/前置 | 状态 |
|---|---|---|---|---|---|
| 1 | **edge-tts 语音播报**(首页 AI 预测上方播放按钮朗读) | docs/ai-predict-tts-plan.md §三(主方案:后端生成 mp3→R2→前端播放按钮) | 用户 00:53 需求;B 级,落地步骤/验收/风险已齐;edge-tts 未安装于两 .venv | 等 AI 回填修复完成避免撞车;pip install edge-tts 到 trade-data/.venv | **排队中**(参考确认:已派调研,待实施) |
| 2 | **AI 预测前端「辩论详情入口」+「弃用标志」+「结论展示」** | TASKS.md L25/26(待派) | 多角色后端已实施(gen_daily_brief.py L1333 run_multi_agent,meta 含 roles/debate,线上 meta.version=ai-multi),前端完整辩论详情展示入口未做 | 无(后端数据已就绪) | **已完成**(2026-08-12 上线 4bc48da1a) |
| 3 | **daily_brief P1-1 周期定位/钟摆位置模板**(恐贪分位+极端提示) | docs/daily-brief-optimization.md §3 P1-1 | trend 段加周期定位模板:恐贪/情绪/新高新低在历史分位,极端值逆向提示 | 需 30 日内 summary_history 支持 | **未实施**(规则版有冰点反向雏形 L540) |
| 4 | **daily_brief P1-3 公募基金持仓/行业配置注入**(中期风格参考) | docs/daily-brief-optimization.md §3 P1-3 | 注入 public_fund_summary 加仓/减仓行业 top 到【趋势研判/中期】,标注季报滞后 | 数据已有(public_fund_summary) | **未实施** |
| 5 | **daily_brief P1-4 明日关注排序分**(胜率×凯利×一致性×近期确认) | docs/daily-brief-optimization.md §3 P1-4 | 用站点回测数据把 AI 关注列表从"模型猜"变"数据排序" | signal_kelly_backtest + signal_stats 已有 | **部分完成**(win_rate 已注入,L302-310;完整排序分未做) |
| 6 | **daily_brief P1-5 日历效应/节假日/月末季末提示** | docs/daily-brief-optimization.md §3 P1-5 | 注入「明日是否月末/季末/长假前/财报季」,仅提示性段落 | 硬编码节假日表,成本低 | **未实施** |
| 7 | **daily_brief P1-6 新闻舆情/宏观事件维度** | docs/daily-brief-optimization.md §3 P1-6 | 盘后拉东财/财联社当日快讯 top 摘要注入【事件面】;或显式声明不含新闻维度 | **需新增采集**(非本次范围) | **未实施**(依赖采集) |
| 8 | **多角色阶段三:事件/新闻面分析师** | docs/ai-predict-multiagent-plan.md §3.2 阶段三 | ④事件/新闻面分析师,输入当日快讯摘要 | 需事件面数据采集(同 #7) | **未实施**(依赖采集) |
| 9 | **daily_brief P1-11 reasoner(R1)深度辩论增强** | docs/daily-brief-optimization.md §3 P1-11 | 研究员角色可切 deepseek-reasoner 深度对抗,成本贵 3-5 倍 | 配置已支持(cfg.researcher_model,gen_daily_brief.py L188),默认 deepseek-chat | **未启用**(可选开关,默认关) |

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
| 14 | **lab_sim 费率客调(策略实验室配对交易;注意 trade_sim 单信号弹窗已上线)** | docs/kelly-fee-adjust-sim-eval.md §10.1 | 凯利费率客调已实现;**trade_sim(单信号回测详情弹窗,app.js _tradeSimOpenModal)已上线**(app.js L21530 _SIM_FEE_PRESETS 6档5参数);**lab_sim(策略实验室配对交易,lab.js 卡片)未做**——lab.js 无费率客调控件,只有静态成本对比块 | 复用凯利费率客调模式 | **远期待办**(2026-08-13 用户定:低优先级) |
| 15 | **凯利回测「次日开盘」口径(前端展示/默认口径)** | docs/kelly-nextday-open-backtest.md + TASKS.md L55 | 建议①后续回测/前端展示默认改「次日开盘」口径(收盘固化、次日开盘买入,数据 100% 覆盖)②操作建议:开盘挂 -1% 限价单 | 无 | **未派**(lab.js 无次日开盘口径,仍收盘口径) |
| 16 | **凯利组合 Walk-forward 滚动验证(样本外)** | docs/kelly-mining-literature.md(未落地) + kelly-combo-signal-research.md §4 + kelly-loss-mining-v4.md §8 #2 + kelly-backtest-comprehensive-review L525 | 用 t-1 年选 toggle、t 年验证,模拟真实前向;建议作为组合上线前必选验证(2011-2020 选、2021-2026 验) | **K 档金额口径已确认(2026-08-14 每日池 top-K 已恢复 c951dafa8,穷举重跑已出 docs/kelly-dailypool-exhaustive-rerun.md,新 toggle 边际已有效)** | **排队中**(2026-08-13 用户定实施;口径已确认,可派) |
| 17 | **凯利 v5 候选方法 4 项** | docs/kelly-mining-literature.md 行72-76 | Decision set 互斥规则集 / PSM 倾向得分匹配 / 漂移检测(drift)/ NSGA-II 多目标优化。(2026-08-13 并入原 #21 高胜率子群深化:需先扩 ETF 属性维度/样本) | 无 | **未实施**(v5 可选方向) |
| 19 | **港股/全球加 MA60 择时按需扩展** | docs/kelly-timing-analysis.md 尾部(L420) | A股 MA60 择时已上线 toggle;港股/全球用 HSI/SPX MA60,样本量小收益有限,按需扩展 | 无 | **未实施**(建议,可选) |
| 20 | **凯利交叉分组卡片可切换二级筛选** | docs/kelly-analysis.md L223 | 信号类型×大类交叉卡片数爆炸,建议做成可切换二级筛选而非平铺。交叉分组样本量易<30,实施前先确认象限样本>100 | 无 | **远期待办**(2026-08-13 用户定:交叉分组样本坍塌+置顶已缓解爆炸,ROI 低暂缓) |
| 21 | **高胜率子群深化研究(并入 #17 v5 方向)** | docs/kelly-backtest-deepseek-review.md L89 | 两象限表现优异但样本小,下一步分析行业/市值/技术形态特征,扩充样本或找适用场景 | 依赖新数据(行业/市值/技术形态字段,signal_kelly_trades.json 无),样本小(n=85) | **远期待办**(2026-08-13 用户定:并入 #17 v5,需先接入 ETF 属性维度/扩充样本再做) |
| 22 | **凯利过滤层 walk-forward(调阈值验证持续)** | docs/walk-forward-report.md L183 | 过滤层多轮迭代调参有过拟合风险,建议未来对过滤层做 walk-forward | 无 | **未实施**(研究项) |

## 四、飞书通知

| # | 功能 | 出处 | 方案摘要 | 依赖/前置 | 状态 |
|---|---|---|---|---|---|
| 23 | **飞书阶段3 优化** | docs/feishu-bot-integration-plan.md 阶段3(行261) | 发送统一到应用 API(弃 webhook)、@成员/@all 关键字、入向消息转告警群 | 阶段1/2 已实施;富文本 post 已做(notify.py) | **部分完成**(@/入向转告警未确认) |
| 24 | **飞书需求群硬编码判断(前缀判定是否必需)** | TASKS.md L59(+L56-58/L62 群处理规则) | 用户 17:55 需求"需求群硬编码不行吗,其他群用前缀合理";另有报告群/告警群处理规则待对齐 | 无 | **未处理**(需求理解类,待主控确认) |
| 25 | **飞书 hook 心跳自检告警** | docs/feishu-hook-stall-diagnosis.md L84 | 指纹文件 mtime 超阈值告警,防静默停摆再次发生 | 诊断标"可选增强" | **未实施**(需主控确认) |

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
| 33 | **管理端任务看板(kanban)** | TASKS.md L66 + memory kanban-board-design | 4列(新需求/待办/进行中/归档按功能聚合)+ Card/Feature 数据模型 + worker /api/kanban + KV + admin/kanban.html | 无(已设计完整) | **未派**(排期:周末或下周) |
| 34 | **场外基金阶段3:场内外联动(ETF 联接跟踪误差)** | TASKS.md L65 | 阶段1 评分引擎+阶段2 前端 UI 已实现;阶段3 场内外联动未做 | 阶段1/2 已上线 | **未派** |
| 35 | **理财专员使用指南 about 页上线** | TASKS.md L121 + docs/理财专员使用指南.md | 613 行指南已验收;等用户定"上线 about 页/就放 docs" | 无 | **未派**(待用户决策) |
| 36 | **signal-finalize-time 两段式 15:05 A股初版** | docs/signal-finalize-time.md §5.3 | 15:05 A股收盘价初版(标注"仅A股")+ 晚间定稿版;机制已天然支持 | 无 | **未实施**(建议形态) |

## 七、数据采集 / 数据源缺口(已识别非功能方案)

| # | 项 | 出处 | 说明 | 状态 |
|---|---|---|---|---|
| 37 | **美股 VIX 采集** | docs/理财专员使用指南.md §5.6(L458) | 无直接 akshare 函数,未采集 | 数据缺口 |
| 38 | **乐咕活跃度 / 东财情绪源** | docs/理财专员使用指南.md §5.6(L459) | 源不稳定/接口待验证,已禁用 | 数据源状态 |

## 八、会话新待办增补(2026-08-12,来源:TASKS #4/#16/#17 + 当日会话产出;由每日 23:45 cron 自动同步维护)

| # | 功能 | 出处 | 方案摘要 | 依赖/前置 | 状态 |
|---|---|---|---|---|---|
| 39 | **AI降亏过滤开关(宏 + 三级级联UI)** | TASKS #17 + 2026-08-12 用户:"默认推荐应为数据回测最优解,4组合全开+A45 11月中下旬+追关注(5.75)可更好" | 穷举搜索全部降亏 toggle 找最优宏(anchor=4组合+A45);三级级联UI:AI降亏过滤→组合降亏→单标志降亏,父级勾选/取消联动子级;同步修正"4组合全开"误导文案(并入 #45)。**2026-08-13 用户补充真实需求**:①AI宏3级联动**未做** ②AI宏独立一行+收起/展开**未做** ③AI宏对应默认推荐打勾**未做** ④AI宏必含4个组合降亏排序打勾(已知,其余待穷举结果) | 无 | **未完成**(2026-08-13 用户确认三件套 UI 均未做;仅"AI宏=新默认"90f948e3c 已上线,穷举数据未落档) |
| 40 | **凯利降亏折叠区重归类** | TASKS #16 + 2026-08-12 用户:"重新整理标记分类,必要时查文献,最差按比值排序也有据可循" | 4 组经济逻辑分类:日历效应·季节调仓(15)/信号质量·弱信号(3)/复合并集·广谱管理(7)/市场防御·大盘择时(1),组内比值降序,⚠️监控置尾,excludeRatingLow/marketTiming 标慎用 | 无 | **已完成**(2026-08-12 上线 bacdf8c9b) |
| 41 | **首页 AI 仓位建议 rename + 范围扩展(#4)** | TASKS #4 + 2026-08-12 用户:"仓位建议方法已固化,可并行启动" | positionCap 改名"AI仓位建议" + pop tooltip 完整展示(技术别名仓位控制过滤) + 范围扩展整个信号列表 + 历史固化 | 无 | **已完成**(2026-08-12 上线 760aa9ffb) |
| 42 | **上下文优化 3 项** | docs/context-optimization-research.md(2026-08-12) | ①OPT-2 MEMORY.md 索引瘦身 19.8KB→~8KB ②OPT-1 轮询/编排降本(状态门控+夜间降频)③OPT-3 主会话 /clear 分会话+Compact Instructions(context rot,保质量>省token) | 无 | **未派**(等用户拍板顺序) |
| 43 | **feishu 抄送「整段全抄送」** | 2026-08-12 会话 | hooks Stop 钩子只抄最后一段,改整段回复全文抄送 | 无 | **已完成**(2026-08-12 上线 9694f8fe7) |
| 44 | **分时图 3 条低危改进** | 2026-08-12 分时乱序修复遗留 | ①段尾 p3 跨空泄漏钳制 ②legend 超宽单行 ③5 字行业名 legY 兜底 | 无 | **已完成**(2026-08-12 上线 537109553) |
| 45 | **凯利「4组合全开」建议文案修正** | 2026-08-12 用户质疑默认勾选不一致 | 组合使用建议标题易误解为默认推荐,加"可选分析非默认推荐"说明 | 并入 #39(AI宏实施时一起改) | **未完成**(lab.js:8633 标题仍"4组合全开",无"可选分析非默认推荐"字样;随 #39 一起做) |
| 46 | **降亏面板①口径标注 + 真实对照行** | 2026-08-13 用户提出(任务列表 #28-50 重复记录) | 降亏面板补「不含仓位控制/峰值持仓991万」口径说明 + 真实对照行(默认 posK2 上全开=G降23.9万),另补 1 处「降亏全开对比行」 | 数据/逻辑需求 | **待处理**(优先级中,等 P0 bug 修复后派) |
| 47 | **K档位评级 A 模式数值数据溯源落档 + 每日池重算** | reviewer MINOR-2(2026-08-13) + docs/kelly-dailypool-exhaustive-rerun.md | A 模式评级数值(71.03/61.16/64.00/61.73)仅硬编码于 lab.js _pcRating,仓库内无回测产物支撑;每日池穷举重跑已产出新 A 模式数(K1=86.60% 等),旧 _pcRating 是 fixed 口径需重算 | 每日池报告已落档 | **部分完成**(穷举数据已落档;页面 _pcRating 重算并入 #48) |
| 48 | **页面 `_kellyFadeFlagGroups` 31键 ratio 每日池口径重算 + _pcRating 重算**(§22 一致性) | docs/kelly-dailypool-exhaustive-rerun.md §0.7/§7.2(2026-08-14) | 页面 31 个 toggle 展示 ratio(每笔1万口径)在每日池下排序剧烈变化(v4b 3→1、n2 10→2、specBear 27→6、v4f 1→31 等);lab.js _kellyFadeFlagGroups 旧 ratio 过时,需按每日池口径(基准=每日池空filter K1,减亏%/损盈%)重算并更新排序;tip 注明口径切换;同步 _pcRating 评级数值重算 + 首页 _AI_POSCAP_RATING | 每日池报告已落档 | **未派**(需 implementer,§22 一致性) |
| 49 | **G/H/I 长持模式持仓≤20倍本金(20万)硬控手段** | docs/kelly-position-cap-20x-limit.md(2026-08-14) | 用户 2026-08-14 新需求:G/H/I 峰值持仓 45-148 倍单次本金不可操作。最优=手段B(FIFO 强制平仓,cap20万):G 收益率反升到 95.7%(b0)~200%(b1)、I 74.5%~153%、H 应放弃;手段A(砍当日)诚实备选、手段D(截断)全负失败 | 真实平仓盈亏需中间价格路径(待验证);前端 positionCap 改造面需 implementer 评估(lab.js _kellyPositionCapKeptKeys) | **未派**(调研已完成,待用户拍板实施) |
| 50 | **每日池口径默认 K 档/toggle 决策落档** | docs/kelly-dailypool-exhaustive-rerun.md §0.2-0.3(2026-08-14) | 默认 toggle 用户定维持 AI宏7键;最优 K=K1 数据最优/K2 推荐默认;G 模式(长持)可去 greedy15/excludeAuxCross/r7 加 a45(51.66%>47.22%),A/F 模式维持现状 | 决策已定(用户 2026-08-14) | **已定**(待落档 README/前端 tooltip;实施并入 #48) |

---

## 【已排除清单】已上线/已在跑(不要重复派)

- **凯利**:默认最优组合(仓位K=2+4降亏)、**金额口径=每日资金池等分+top-K**(2026-08-14 恢复 c951dafa8,修正 K=3 33万虚假杠杆;旧"每笔固定1万"为过时口径)、1月调整 J1/J2 并入、positionCap K档、G公示、**全信号表+组合使用建议**(lab.js L8503,2026-08-12)、MA60择时 toggle⑭、降亏过滤31 toggle、凯利费率客调、fade 交互方案一(lab-custom-host--loading,L7620)、稳健核心组合=仅 r8、次日开盘回测报告本身(仅建议未实施,见 #15)、**K档位评级标注+hover评级理由表格**(2026-08-13 上线 4fe5d45bc,展示层不改算法)、**凯利 top-K+质量约束+选择器前向测试 #18**(已关闭 2026-08-13:质量约束两口径负边际不实施;前向测试简单切分已有结论,滚动版并入 #16)
- **daily_brief**:**辩论详情入口+弃用标志+结论展示**(2026-08-12 上线 4bc48da1a)
- **SVG**:轻量走势图 P0+P1 全站扩展(首页 sparkline/KPI/分时,app.js L11059/L11077)、SVG 修正主链 a149、home-svg-fix P1-1/P1-2
- **daily_brief**:后端 P0-1/2/3/4 + P1-2(多空辩论随 P0-4)/P1-7/P1-8/P1-9/P1-10/P1-11(配置)/P2-1(cost_log)/P2-2(已知偏差),前端 AI 预测弹窗+命中率+历史结合展示(2026-08-11,app.js L20066-20377)
- **飞书**:阶段1 发送 + 阶段2 接收(lark-oapi 长连接+落盘+launchd)
- **R2**:迁移 P0 方案1(PURGE_SECRET)/方案2(高频 ttl=0)、前端 ./data fallback、备站主动域名策略(_isBackupSite,app.js L3849)、72h 监控(monitor_72h.sh + com.trade.monitor-72h 已加载)、feed.xml 走 R2、staticdata 同步(daily_brief)、bak-audit 残留(A+B 已合 main、signal_kelly_trades ssd 直链已改主站双兜底)
- **其他**:intraday 自愈 S1-S5+S9、walk-forward-c P1 选项A(sh 去 D1a,已实施)、全球指数盘中实时 15 指数(含港股系 7 个 + ASX200/SENSEX)、场外基金阶段1 评分引擎(6维+5指标+经理+凯利)+阶段2 UI、alert-design 自定义分析 tab(AI预警/AI评分/历史类比,lab.js custom 父tab)、README 命名统一+og.png 更新、P1-1 走向量化(perf,11.87s->6.10s)、staticdata-daily-brief-sync 全部、tasks-archive-maintain、claude-md 重组/role-based-context
