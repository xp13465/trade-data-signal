# 已落档未开发功能索引(pending-features-index)

> **用途**:团队共享"未开发功能地图"。任何开发任务开工前对照本表,确认方案已出的待做项,避免多子 agent 只顾自己的活、漏做已落档方案。
> **生成**:2026-08-12 盘点 agent 产出。来源:docs/ 81 份 md + TASKS.md 待办 + 代码层验证(grep 结论均带证据,非臆断)。
> **口径**:只列"方案已出/结论已定/计划已写,但尚未开发完成"的功能;已上线/已在跑项见文末【已排除清单】。
> **状态标记**:未派 / 排队中 / 部分完成 / 需确认(不确定是否已开发,待主控核)

---

## 一、AI 预测(daily_brief / edge-tts)

| # | 功能 | 出处 | 方案摘要 | 依赖/前置 | 状态 |
|---|---|---|---|---|---|
| 1 | **edge-tts 语音播报**(首页 AI 预测上方播放按钮朗读) | docs/ai-predict-tts-plan.md §三(主方案:后端生成 mp3→R2→前端播放按钮) | 用户 00:53 需求;B 级,落地步骤/验收/风险已齐;edge-tts 未安装于两 .venv | 等 AI 回填修复完成避免撞车;pip install edge-tts 到 trade-data/.venv | **排队中**(参考确认:已派调研,待实施) |
| 2 | **AI 预测前端「辩论详情入口」+「弃用标志」+「结论展示」** | TASKS.md L25/26(待派) | 多角色后端已实施(gen_daily_brief.py L1333 run_multi_agent,meta 含 roles/debate,线上 meta.version=ai-multi),前端完整辩论详情展示入口未做 | 无(后端数据已就绪) | **未派**(排队) |
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
| 14 | **模拟回测(lab_sim)费率客调** | docs/kelly-fee-adjust-sim-eval.md §10.1 | 凯利费率客调已实现,**模拟回测费率客调明确"待实施"**(SIM_FEE_PRESETS 4 档2参数 + _simRecomputeTrade 等) | 复用凯利费率客调模式 | **未派**(明确待实施) |
| 15 | **凯利回测「次日开盘」口径(前端展示/默认口径)** | docs/kelly-nextday-open-backtest.md + TASKS.md L55 | 建议①后续回测/前端展示默认改「次日开盘」口径(收盘固化、次日开盘买入,数据 100% 覆盖)②操作建议:开盘挂 -1% 限价单 | 无 | **未派**(lab.js 无次日开盘口径,仍收盘口径) |
| 16 | **凯利组合 Walk-forward 滚动验证(样本外)** | docs/kelly-mining-literature.md(未落地) + kelly-combo-signal-research.md §4 + kelly-loss-mining-v4.md §8 #2 + kelly-backtest-comprehensive-review L525 | 用 t-1 年选 toggle、t 年验证,模拟真实前向;建议作为组合上线前必选验证(2011-2020 选、2021-2026 验) | 无 | **未实施**(研究/回测项,组合已上线但缺样本外) |
| 17 | **凯利 v5 候选方法 4 项** | docs/kelly-mining-literature.md 行72-76 | Decision set 互斥规则集 / PSM 倾向得分匹配 / 漂移检测(drift)/ NSGA-II 多目标优化 | 无 | **未实施**(v5 可选方向) |
| 18 | **凯利 top-K+质量约束 + 选择器前向测试** | docs/kelly-position-cap-k-sensitivity.md §5/§8 待验证②④ | top-K 内再排除 buy_special(质量约束)、前向测试(选择器稳定性) | positionCap K 档已上线,此两项为待验证扩展 | **未派**(待验证研究项) |
| 19 | **港股/全球加 MA60 择时按需扩展** | docs/kelly-timing-analysis.md 尾部(L420) | A股 MA60 择时已上线 toggle;港股/全球用 HSI/SPX MA60,样本量小收益有限,按需扩展 | 无 | **未实施**(建议,可选) |
| 20 | **凯利交叉分组卡片可切换二级筛选** | docs/kelly-analysis.md L223 | 信号类型×大类交叉卡片数爆炸,建议做成可切换二级筛选而非平铺 | 无 | **未实施**(建议) |
| 21 | **高胜率子群深化研究(rating_high/sig_backup)** | docs/kelly-backtest-deepseek-review.md L89 | 两象限表现优异但样本小,下一步分析行业/市值/技术形态特征,扩充样本或找适用场景 | 无 | **未实施**(研究项) |
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

---

## 【已排除清单】已上线/已在跑(不要重复派)

- **凯利**:默认最优组合(仓位K=2+4降亏)、金额口径=每笔固定1万(2026-08-12)、1月调整 J1/J2 并入、positionCap K档、G公示、**全信号表+组合使用建议**(lab.js L8503,2026-08-12)、MA60择时 toggle⑭、降亏过滤31 toggle、凯利费率客调、fade 交互方案一(lab-custom-host--loading,L7620)、稳健核心组合=仅 r8、次日开盘回测报告本身(仅建议未实施,见 #15)
- **SVG**:轻量走势图 P0+P1 全站扩展(首页 sparkline/KPI/分时,app.js L11059/L11077)、SVG 修正主链 a149、home-svg-fix P1-1/P1-2
- **daily_brief**:后端 P0-1/2/3/4 + P1-2(多空辩论随 P0-4)/P1-7/P1-8/P1-9/P1-10/P1-11(配置)/P2-1(cost_log)/P2-2(已知偏差),前端 AI 预测弹窗+命中率+历史结合展示(2026-08-11,app.js L20066-20377)
- **飞书**:阶段1 发送 + 阶段2 接收(lark-oapi 长连接+落盘+launchd)
- **R2**:迁移 P0 方案1(PURGE_SECRET)/方案2(高频 ttl=0)、前端 ./data fallback、备站主动域名策略(_isBackupSite,app.js L3849)、72h 监控(monitor_72h.sh + com.trade.monitor-72h 已加载)、feed.xml 走 R2、staticdata 同步(daily_brief)、bak-audit 残留(A+B 已合 main、signal_kelly_trades ssd 直链已改主站双兜底)
- **其他**:intraday 自愈 S1-S5+S9、walk-forward-c P1 选项A(sh 去 D1a,已实施)、全球指数盘中实时 15 指数(含港股系 7 个 + ASX200/SENSEX)、场外基金阶段1 评分引擎(6维+5指标+经理+凯利)+阶段2 UI、alert-design 自定义分析 tab(AI预警/AI评分/历史类比,lab.js custom 父tab)、README 命名统一+og.png 更新、P1-1 走向量化(perf,11.87s->6.10s)、staticdata-daily-brief-sync 全部、tasks-archive-maintain、claude-md 重组/role-based-context
