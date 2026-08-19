# 已落档未开发功能索引(pending-features-index)

> **用途**:团队共享"未开发功能地图"。任何开发任务开工前对照本表,确认方案已出的待做项,避免多子 agent 只顾自己的活、漏做已落档方案。
> **生成**:2026-08-12 盘点 agent 产出。来源:docs/ 81 份 md + TASKS.md 待办 + 代码层验证(grep 结论均带证据,非臆断)。
> **路径整理(2026-08-14)**:docs/ 已按主题拆分,凯利文档移入 `docs/kelly/{mining,combo,position,backtest-ai,toggle,analysis}/`、walk-forward/claude-md-reorganize 系列移入 `docs/archive/`。本表内 kelly-* / walk-forward-* 引用路径均已同步为新路径。23:45 cron 定期重建**(`.claude/scheduled_tasks.json` L49 prompt 用 git log 扫新增文件)**会自然用新路径,无需额外改。
> **最近更新**:2026-08-19(并行工作流降级安全 B 方案用户拍板:多agent并行+worktree 收益vs成本量化 docs/parallel-cost-benefit-2026-08-18.md 净账打平到略亏,用户定「降级到安全点」,新增 #70-72 防再犯 C/D 机制实施待办,详见模块十二;同日防再犯 A/B/E 机制+P1 修复已 merge main 782af79d1)。2026-08-18(researcher 四档升级 v2 穷举落档:excludeSpecialBear 判定源 hs300→cyb 验证报告 docs/market-state/kelly-fourtier-v2-multiindex.md + 稳定性补测 docs/market-state/kelly-fourtier-v2-multiindex-stability.md(cyb 总量赢家非逐年稳定,2023 负),新增 #65 待用户拍板)。2026-08-18(v1.1.2 凯利三键改造+历史四档轨迹图已实施待 merge 验收,新增优化批次 B/C/D/E 待办,更新 #61/#46/#51/#56 状态,详见模块十一)。2026-08-16(#58 K档交互对齐首页 + P2修法①后端排除未入样:监控卡 K档按钮组改为 关+K1/2/3/4 共5钮对齐首页「AI仓位建议 K」(sig-kbtn 样式+K1★主推+sig-kbtn-off,点「关」=_overfitState.k=null 退化 filtered/raw),后端 build_topk_kept_map 跳过 ts=None 未入样信号(与首页 _bt_in_universe 同人口, 20260814 旧逻辑top-1=cgb_idx 未入样已排除, 全史剔 1172 条未入样污染);版本串 a276)。2026-08-16(分析参考点AI监控二次迭代完成 #58/#60:K档启用[by_k/filtered_by_k两开关独立]+窗口语义改「显示范围」固定60+❓hover短click详版+reviewer返修4项+SVG 3色基准;版本串 a275)。2026-08-16(每日 cron 同步:分析参考点AI监控三合一上线[默认开+K档UI预留+轻量SVG] + K2C5补跑同口径比值[进行中] + 窗口语义改数据范围[待办],新增 #58-60,移已排除清单)。2026-08-15(每日 cron 同步:AI过滤视图两开关正交上线 + 公示补「+1」+ §23.6 公示完成 + $压缩冲突P0修复,更新 #31/#33/#36/#49,新增 #51-53,移已排除清单)。2026-08-14(每日 23:45 cron 同步:凯利每日池口径穷举重跑 + 20倍本金硬控调研落档,新增 #48-50,更新 #16/#47)。2026-08-13 用户拍板:#14 更名明确位置→远期待办、#16 排队中(依赖K档口径)、#18 关闭移排除清单、#20→远期待办、#21 并入 #17 v5→远期待办。**此后每日 23:45 cron 定期同步**(2026-08-12 用户定:快照会慢慢过时达不到索引效果,需定期刷新),机制见 docs/main-governance.md §23.4 索引维护。
> **口径**:只列"方案已出/结论已定/计划已写,但尚未开发完成"的功能;已上线/已在跑项见文末【已排除清单】。
> **状态标记**:未派 / 排队中 / 部分完成 / 需确认(不确定是否已开发,待主控核)

---

## 一、AI 预测(daily_brief / edge-tts)

| # | 功能 | 出处 | 方案摘要 | 依赖/前置 | 状态 |
|---|---|---|---|---|---|
| 1 | **edge-tts 语音播报**(首页 AI 预测上方播放按钮朗读) | docs/ai-predict-tts-plan.md §三(主方案:后端生成 mp3→R2→前端播放按钮) | 用户 00:53 需求;B 级,落地步骤/验收/风险已齐;edge-tts 未安装于两 .venv | 等 AI 回填修复完成避免撞车;pip install edge-tts 到 trade-data/.venv | **已完成**(2026-08-16 上线 a8a4d632f,版本串 a281;见文末【已排除清单】) |
| 2 | **AI 预测前端「辩论详情入口」+「弃用标志」+「结论展示」** | TASKS.md L25/26(待派) | 多角色后端已实施(gen_daily_brief.py L1333 run_multi_agent,meta 含 roles/debate,线上 meta.version=ai-multi),前端完整辩论详情展示入口未做 | 无(后端数据已就绪) | **已完成**(2026-08-12 上线 4bc48da1a) |
| 3 | **daily_brief P1-1 周期定位/钟摆位置模板**(恐贪分位+极端提示) | docs/daily-brief-optimization.md §3 P1-1 | trend 段加周期定位模板:恐贪/情绪/新高新低在历史分位,极端值逆向提示 | 需 30 日内 summary_history 支持 | **未实施**(规则版有冰点反向雏形 L540) |
| 4 | **daily_brief P1-3 公募基金持仓/行业配置注入**(中期风格参考) | docs/daily-brief-optimization.md §3 P1-3 | 注入 public_fund_summary 加仓/减仓行业 top 到【趋势研判/中期】,标注季报滞后 | 数据已有(public_fund_summary) | **未实施** |
| 5 | **daily_brief P1-4 明日关注排序分**(胜率×凯利×一致性×近期确认) | docs/daily-brief-optimization.md §3 P1-4 | 用站点回测数据把 AI 关注列表从"模型猜"变"数据排序" | signal_kelly_backtest + signal_stats 已有 | **部分完成**(win_rate 已注入,L302-310;完整排序分未做) |
| 6 | **daily_brief P1-5 日历效应/节假日/月末季末提示** | docs/daily-brief-optimization.md §3 P1-5 | 注入「明日是否月末/季末/长假前/财报季」,仅提示性段落 | 硬编码节假日表,成本低 | **未实施** |
| 7 | **daily_brief P1-6 新闻舆情/宏观事件维度** | docs/daily-brief-optimization.md §3 P1-6 + 调研双报告:数据源实测 [`docs/ai-predict-news-macro-research-sources.md`](docs/ai-predict-news-macro-research-sources.md)(东财7x24/财联社电报/金十flash 三源免签可达,仅缺「未来事件日历」现成接口)、方法论 [`docs/ai-predict-news-macro-research-methodology.md`](docs/ai-predict-news-macro-research-methodology.md)(字段期望/页面展示 §7) | 盘后拉东财/财联社当日快讯 top 摘要注入【事件面】;或显式声明不含新闻维度 | fetch_news.py(launchd 16:45)已产 `data/news_digest.json`(三源:东财/财联社/金十,含 news+upcoming);注入侧 2026-08-16 已进 gen_daily_brief.load_data(新增 9 聚合 key + news 段 + upcoming 明日事件,guard 停更/缺失跳过,见 ai-predict-inject-research.md) | **已完成**(2026-08-16:注入侧+前端展示位全落地——首页「📣今日要闻」外露速览行+「📅明日关键事件」日期标注(244c00cff/a7925c77d/a283/a284 系列)+ 外露行可点&历史兜底入口(33ef7bd33)+ 新闻按日期归档累积(49be3c317)+ 弹窗空态修复(70c625386),commit 均在 origin/main,版本串 a285→a296) |
| 8 | **多角色阶段三:事件/新闻面分析师** | docs/ai-predict-multiagent-plan.md §3.2 阶段三 + 数据源实测[`docs/ai-predict-news-macro-research-sources.md`](docs/ai-predict-news-macro-research-sources.md) | ④事件/新闻面分析师,输入当日快讯摘要 | 需事件面数据采集;注入侧 2026-08-16 已把 news 分布进 risk 域(fetch_news 采集已就绪) | **部分完成**(news 数据+注入已进 risk 域;独立的「事件/新闻面分析角色」未新增,仍分布进既有域) |
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
| 14 | **lab_sim 费率客调(策略实验室配对交易;注意 trade_sim 单信号弹窗已上线)** | docs/kelly/analysis/kelly-fee-adjust-sim-eval.md §10.1 | 凯利费率客调已实现;**trade_sim(单信号回测详情弹窗,app.js _tradeSimOpenModal)已上线**(app.js L21530 _SIM_FEE_PRESETS 6档5参数);**lab_sim(策略实验室配对交易,lab.js 卡片)未做**——lab.js 无费率客调控件,只有静态成本对比块 | 复用凯利费率客调模式 | **远期待办**(2026-08-13 用户定:低优先级) |
| 15 | **凯利回测「次日开盘」口径(前端展示/默认口径)** | docs/kelly/position/kelly-nextday-open-backtest.md + TASKS.md L55 | 建议①后续回测/前端展示默认改「次日开盘」口径(收盘固化、次日开盘买入,数据 100% 覆盖)②操作建议:开盘挂 -1% 限价单 | 无 | **未派**(lab.js 无次日开盘口径,仍收盘口径) |
| 16 | **凯利组合 Walk-forward 滚动验证(样本外)** | docs/kelly/mining/kelly-mining-literature.md(未落地) + kelly-combo-signal-research.md §4 + kelly-loss-mining-v4.md §8 #2 + kelly-backtest-comprehensive-review L525 | 用 t-1 年选 toggle、t 年验证,模拟真实前向;建议作为组合上线前必选验证(2011-2020 选、2021-2026 验) | **K 档金额口径已确认(2026-08-14 每日池 top-K 已恢复 c951dafa8,穷举重跑已出 docs/kelly/position/kelly-dailypool-exhaustive-rerun.md,新 toggle 边际已有效)** | **已完成**(2026-08-16 commit 299db6167 已在 origin/main + 落档 docs/kelly/analysis/kelly-walkforward-validate.md:v1.1.0 推荐最优组合 8键全开 样本外有效不过拟合,选段最优反而过拟合) |
| 17 | **凯利 v5 候选方法 4 项** | docs/kelly/mining/kelly-mining-literature.md 行72-76 | Decision set 互斥规则集 / PSM 倾向得分匹配 / 漂移检测(drift)/ NSGA-II 多目标优化。(2026-08-13 并入原 #21 高胜率子群深化:需先扩 ETF 属性维度/样本) | 无 | **未实施**(v5 可选方向) |
| 19 | **港股/全球加 MA60 择时按需扩展** | docs/kelly/analysis/kelly-timing-analysis.md 尾部(L420) | A股 MA60 择时已上线 toggle;港股/全球用 HSI/SPX MA60,样本量小收益有限,按需扩展 | 无 | **未实施**(建议,可选) |
| 20 | **凯利交叉分组卡片可切换二级筛选** | docs/kelly/analysis/kelly-analysis.md L223 | 信号类型×大类交叉卡片数爆炸,建议做成可切换二级筛选而非平铺。交叉分组样本量易<30,实施前先确认象限样本>100 | 无 | **远期待办**(2026-08-13 用户定:交叉分组样本坍塌+置顶已缓解爆炸,ROI 低暂缓) |
| 21 | **高胜率子群深化研究(并入 #17 v5 方向)** | docs/kelly/backtest-ai/kelly-backtest-deepseek-review.md L89 | 两象限表现优异但样本小,下一步分析行业/市值/技术形态特征,扩充样本或找适用场景 | 依赖新数据(行业/市值/技术形态字段,signal_kelly_trades.json 无),样本小(n=85) | **远期待办**(2026-08-13 用户定:并入 #17 v5,需先接入 ETF 属性维度/扩充样本再做) |
| 22 | **凯利过滤层 walk-forward(调阈值验证持续)** | docs/archive/walk-forward-report.md L183 | 过滤层多轮迭代调参有过拟合风险,建议未来对过滤层做 walk-forward | 无 | **未实施**(研究项) |
| 74 | **check_signals.py L708 ai_macro.hit 未做 AI_MACRO_KEYS 白名单二次过滤** | #69 reviewer 非阻断发现(2026-08-19) | 邮件广播候选判定 `if m.get("ai_macro", {}).get("hit"): continue` 只查 hit 原始值,默认关非推荐键(如刚上线的 excludeSpecialBearCyb)产生的 hit 也会把信号从广播候选剔除;对普通用户(默认关)本不该生效,建议二次过滤 AI_MACRO_KEYS 白名单(只承认默认组合内键的 hit) | 等 #69 上线后安排;改动小(A 级) | **待办**(非阻断,2026-08-19 建) |

## 四、飞书通知

| # | 功能 | 出处 | 方案摘要 | 依赖/前置 | 状态 |
|---|---|---|---|---|---|
| 23 | **飞书阶段3 优化** | docs/feishu-bot-integration-plan.md 阶段3(行261) | 发送统一到应用 API(弃 webhook)、@成员/@all 关键字、入向消息转告警群 | 阶段1/2 已实施;富文本 post 已做(notify.py) | **部分完成**(@/入向转告警未确认) |
| 24 | **飞书需求群硬编码判断(前缀判定是否必需)** | TASKS.md L59(+L56-58/L62 群处理规则) | 用户 17:55 需求"需求群硬编码不行吗,其他群用前缀合理";另有报告群/告警群处理规则待对齐 | 无 | **已完成**(scripts/feishu_ws_listener.py L737/781 已实现:白名单需求群免前缀直接落盘,非白名单群保留前缀过滤,全角/半角冒号都认) |
| 25 | **飞书 hook 心跳自检告警** | docs/feishu-hook-stall-diagnosis.md L84 | 指纹文件 mtime 超阈值告警,防静默停摆再次发生 | 诊断标"可选增强" | **已完成**(2026-08-17 上线 6edca04af:发送侧 hook 心跳维度⑧ + 接收侧 listener 心跳维度⑨,listener 事件成功落盘 touch `/tmp/feishu_ws_last_event`,schedule_monitor.sh 维度⑨ 24h 阈值+进程>30min 防误报+alert_state 去重,四态自测+33测试全过) |

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
| 35 | **理财专员使用指南 about 页上线** | TASKS.md L121 + docs/理财专员使用指南.md | 613 行指南已验收;等用户定"上线 about 页/就放 docs" | 无 | **已完成**(2026-08-18 上线:scripts/gen_guide_html.py 用 Python-Markdown 渲染 docs/理财专员使用指南.md → static-site/guide.html,纯静态零 JS;about.html 目录+header+footer 与 index.html footer 加互链入口;README 功能亮点+参考与致敬已补) |
| 36 | **signal-finalize-time 两段式 15:05 A股初版** | docs/signal-finalize-time.md §5.3 | 15:05 A股收盘价初版(标注"仅A股")+ 晚间定稿版;机制已天然支持 | 无 | **已实施**(2026-08-14: overview signals_meta 三态 + close/etf_close + 前端提示条/AI建议标签/参考说明, 见 docs/signal-finalize-time.md §6 已实施注记; 2026-08-15 后续 W1 文案放宽 71d238785 + 三态提示 3311eca8d 已合) |

## 七、数据采集 / 数据源缺口(已识别非功能方案)

| # | 项 | 出处 | 说明 | 状态 |
|---|---|---|---|---|
| 37 | **美股 VIX 采集** | docs/理财专员使用指南.md §5.6(L458) | 无直接 akshare 函数,未采集 | 数据缺口 |
| 38 | **乐咕活跃度 / 东财情绪源** | docs/理财专员使用指南.md §5.6(L459) | 源不稳定/接口待验证,已禁用 | 数据源状态 |

## 八、会话新待办增补(2026-08-12,来源:TASKS #4/#16/#17 + 当日会话产出;由每日 23:45 cron 自动同步维护)

| # | 功能 | 出处 | 方案摘要 | 依赖/前置 | 状态 |
|---|---|---|---|---|---|
| 39 | **AI降亏过滤开关(宏 + 三级级联UI)** | TASKS #17 + 2026-08-12 用户:"默认推荐应为数据回测最优解,4组合全开+A45 11月中下旬+追关注(5.75)可更好" | 穷举搜索全部降亏 toggle 找最优宏(anchor=4组合+A45);三级级联UI:AI降亏过滤→组合降亏→单标志降亏,父级勾选/取消联动子级;同步修正"4组合全开"误导文案(并入 #45)。**2026-08-13 用户补充真实需求**:①AI宏3级联动**未做** ②AI宏独立一行+收起/展开**未做** ③AI宏对应默认推荐打勾**未做** ④AI宏必含4个组合降亏排序打勾(已知,其余待穷举结果) | 无 | **已完成**(三级级联UI已实现:lab.js `#lab-kelly-ai-macro-body` 详情折叠+AI宏勾选联动全部8键子级 `_kellyAiMacroMembers`(含K2C5),"AI宏=新默认"90f948e3c 已上线;穷举数据见 docs/kelly/analysis/kelly-k2c5-exhaust-interaction.md) |
| 40 | **凯利降亏折叠区重归类** | TASKS #16 + 2026-08-12 用户:"重新整理标记分类,必要时查文献,最差按比值排序也有据可循" | 4 组经济逻辑分类:日历效应·季节调仓(15)/信号质量·弱信号(3)/复合并集·广谱管理(7)/市场防御·大盘择时(1),组内比值降序,⚠️监控置尾,excludeRatingLow/marketTiming 标慎用 | 无 | **已完成**(2026-08-12 上线 bacdf8c9b) |
| 41 | **首页 AI 仓位建议 rename + 范围扩展(#4)** | TASKS #4 + 2026-08-12 用户:"仓位建议方法已固化,可并行启动" | positionCap 改名"AI仓位建议" + pop tooltip 完整展示(技术别名仓位控制过滤) + 范围扩展整个信号列表 + 历史固化 | 无 | **已完成**(2026-08-12 上线 760aa9ffb) |
| 42 | **上下文优化 3 项** | docs/context-optimization-research.md(2026-08-12) | ①OPT-2 MEMORY.md 索引瘦身 19.8KB→~8KB ②OPT-1 轮询/编排降本(状态门控+夜间降频)③OPT-3 主会话 /clear 分会话+Compact Instructions(context rot,保质量>省token) | 无 | **未派**(等用户拍板顺序) |
| 43 | **feishu 抄送「整段全抄送」** | 2026-08-12 会话 | hooks Stop 钩子只抄最后一段,改整段回复全文抄送 | 无 | **已完成**(2026-08-12 上线 9694f8fe7) |
| 44 | **分时图 3 条低危改进** | 2026-08-12 分时乱序修复遗留 | ①段尾 p3 跨空泄漏钳制 ②legend 超宽单行 ③5 字行业名 legY 兜底 | 无 | **已完成**(2026-08-12 上线 537109553) |
| 45 | **凯利「4组合全开」建议文案修正** | 2026-08-12 用户质疑默认勾选不一致 | 组合使用建议标题易误解为默认推荐,加"可选分析非默认推荐"说明 | 并入 #39(AI宏实施时一起改) | **已完成**(lab.js 组合降亏行标题已改「组合降亏(可选分析非默认推荐)」,原"4组合全开"误导文案已修正,不会误当默认推荐;随 #39 一起落地) |
| 46 | **降亏面板①口径标注 + 真实对照行** | 2026-08-13 用户提出(任务列表 #28-50 重复记录) | 降亏面板补「不含仓位控制/峰值持仓961万」口径说明 + 真实对照行(AI仓位 K=2 全开=G少赚约17.7万, K=1 少赚约16.7万),另补 1 处「降亏全开对比行」 | 数据/逻辑需求 | **已完成**(2026-08-18,commit 63fb27391,分支 worktree-agent-a28682160e85b9dd4;数字现网复算,991万→961万/23.9万→17.7万旧口径过时) |
| 47 | **K档位评级 A 模式数值数据溯源落档 + 每日池重算** | reviewer MINOR-2(2026-08-13) + docs/kelly/position/kelly-dailypool-exhaustive-rerun.md | A 模式评级数值(71.03/61.16/64.00/61.73)仅硬编码于 lab.js _pcRating,仓库内无回测产物支撑;每日池穷举重跑已产出新 A 模式数(K1=86.60% 等),旧 _pcRating 是 fixed 口径需重算 | 每日池报告已落档 | **部分完成**(穷举数据已落档;页面 _pcRating 重算并入 #48) |
| 48 | **页面 `_kellyFadeFlagGroups` 31键 ratio 每日池口径重算 + _pcRating 重算**(§22 一致性) | docs/kelly/position/kelly-dailypool-exhaustive-rerun.md §0.7/§7.2(2026-08-14) | 页面 31 个 toggle 展示 ratio(每笔1万口径)在每日池下排序剧烈变化(v4b 3→1、n2 10→2、specBear 27→6、v4f 1→31 等);lab.js _kellyFadeFlagGroups 旧 ratio 过时,需按每日池口径(基准=每日池空filter K1,减亏%/损盈%)重算并更新排序;tip 注明口径切换;同步 _pcRating 评级数值重算 + 首页 _AI_POSCAP_RATING | 每日池报告已落档 | **已完成**(2026-08-14 #48+#BC 重算落地:lab.js _kellyFadeFlagGroups 31键 ratio 按每日池口径重算更新排序 + _pcRating 静态快照由 fixed 重算为每日池+费率口径,§22 与 common.js _AI_POSCAP_RATING/首页 app.js tooltip 三处一致,主推 K1) |
| 49 | **G/H/I 长持模式持仓≤20倍本金(20万)硬控手段** | docs/kelly/position/kelly-position-cap-20x-limit.md(2026-08-14) | 用户 2026-08-14 新需求:G/H/I 峰值持仓 45-148 倍单次本金不可操作。最优=手段B(FIFO 强制平仓,cap20万):G 收益率反升到 95.7%(b0)~200%(b1)、I 74.5%~153%、H 应放弃;手段A(砍当日)诚实备选、手段D(截断)全负失败 | 真实平仓盈亏需中间价格路径(待验证);H 后期研究为什么差(本次按用户定性标注慎用,未做 H 优化) | **已实施**(2026-08-14 上线:lab.js 凯利回测区新增「ai长线模式(G/H/I)仓位管理」开关=长线族群总入口+模式→策略映射(fifo20w),默认关,ON 套持仓≤20万+FIFO硬控,G/H/I 卡片套乐观b1+AI长线·开角标,新增G/H/I对比表(关/开b0/开b1,报告§7.2 K1口径),前端FIFO内核与报告逐位对齐§21;purpose-notes/README同步;sw.js a197) |
| 50 | **每日池口径默认 K 档/toggle 决策落档** | docs/kelly/position/kelly-dailypool-exhaustive-rerun.md §0.2-0.3(2026-08-14) | 默认 toggle 用户定维持 AI宏7键;最优 K=K1 数据最优/K2 推荐默认;G 模式(长持)可去 greedy15/excludeAuxCross/r7 加 a45(51.66%>47.22%),A/F 模式维持现状 | 决策已定(用户 2026-08-14) | **已定**(待落档 README/前端 tooltip;实施并入 #48) |
| 51 | **§23.6 入样宇宙规则落地**(显式化+校验) | config/universe_rules.yaml + scripts/check_universe_alignment.py(2026-08-14, f27768c85) | 宇宙规则单一事实源(yaml:白名单/入样依赖/排除类别/自我ETF例外) + 4断言对称校验脚本挂 deploy 链 FAIL 阻断上线 | 已落 yaml+校验脚本(17:42) | **部分完成**(yaml+check 已上线;首页1:1遵从/变更联动 8 步走查待全量验证) |
| 52 | **§23.6 ②公示:入样宇宙规则三处公示文案** | app.js L2208/L2224/L2229 + purpose-notes.js lab.sigkelly + lab.js(2026-08-14, d798854aa) | 入样白名单/依赖/排除类别/自我ETF例外/1:1遵从 全公示到 AI建议 badge tooltip + AI警示 + 未入样本 + 凯利区 | 已上线 d798854aa | **已完成**(2026-08-14 上线;AI过滤视图补充公示 489f0bdb4) |
| 53 | **首页「AI过滤视图」两开关正交** | 2026-08-14 用户多轮澄清 | AI降亏(删除线层)与 AI仓位(badge层)两开关独立不绑定:降亏=熊市追信号删线+未入样本删线;仓位=AI建议N/当日已满/AI警示 | 无 | **已完成**(2026-08-14 上线 489f0bdb4,review PASS) |
| 54 | **公示补「+1」(AI宏4+3+1)** | 2026-08-14 用户:"信号凯利回测是全信号,回测剔除的波动相关/未入样本必须公示,最简单=补一个1" | AI宏结构公示升级为 4+3+1:+1=回测剔除的信号类别(波动相关/未入样本),虽属全信号但 AI建议不推荐 | 无 | **已完成**(2026-08-14 上线 cfd37057e) |
| 55 | **$压缩冲突 P0 修复(防重犯)** | 2026-08-14 "$ is not a function" / 08-15 "c is not a function" | terser mangle 把新增函数重命名为单字符($→C)与既有变量冲突,报 is not a function | build_min.py 加 --mangle reserved=['$'] 只是打地鼠(69f505072) | **已完成**(08-15 根治已上线:build_min.py keep_fnames/保留函数名,terser 不再把新增函数 mangle 成单字符与既有变量冲突;详见【已排除清单】「$压缩冲突根治」) |

---

## 九、运维/一致性待办增补(2026-08-15 cron 同步)

| # | 项 | 出处 | 说明 | 状态 |
|---|---|---|---|---|
| 56 | **signal_notified.json 双副本清理** | 2026-08-15 部署核验 | trade-data/data(权威,8/14=13条) vs trade/data(旧,8/14=11条) 双份;check_signals 读权威份无重发风险,但"直接 cd trade 跑 python"会误读旧副本重发;处置=同步旧副本或 symlink+断言(REPO 必须落 trade-data) | **待办**(低优先,已同步 md5 一致) |
| 57 | **sw.js 版本注释过时修正** | reviewer S1(2026-08-14) | sw.js 注释堆里 `_sigFilterViewOn` 旧变量名残留 1 处(在 CACHE_VERSION 版本变更注释里,该变量已不存在);新注释「两开关正交」已随后续 bump 写入 | **已完成**(2026-08-17 上线:commit 2d6bc6207 清残留+push,CF 主站 purge /sw.js 后三站+本地 curl 全 0 残留,不 bump CACHE_VERSION=纯注释零行为零产物变化) |

## 十、分析参考点AI监控增补(2026-08-16 cron 同步)

| # | 项 | 出处 | 说明 | 状态 |
|---|---|---|---|---|
| 58 | **分析参考点AI监控三合一** | 2026-08-16 用户拍板 | AI降亏过滤默认开(首次无 localStorage 默认 true,手动关记住) + **K档启用**(by_k/filtered_by_k,与首页AI仓位建议top-K同口径,降亏开关×K档两开关独立)+ 双图轻量SVG(_lwSetup,绿黄红分段+30/60参考线) + ❓hover短+click详版弹窗 + reviewer返修(P1 localStorage try/catch/P2-1空态删_lwRenderers/P2-2 pb44/P2-3 y轴0-100) + SVG 3色为基准(echarts fallback 去固定色) + **P2修法①K档by_k排除未入样**(build_topk_kept_map 跳 ts=None 未入样,与首页同人口,全史剔1172条,commit ac61248a4+merge 33c722997) | **已完成**(2026-08-16 二次迭代,版本串 a275→a279,commit ac61248a4/33c722997) |
| 59 | **K2C5 补跑每日池同口径比值** | 2026-08-16 用户拍板 | 凯利区降亏开关 K2C5 ratio"待实测"→补跑每日池减亏%/损盈%/比值(researcher 预跑:减亏2.88%/损盈0.63%/比值4.55) + 凯利区 advice 文案精简 | **已完成**(2026-08-16 commit f5d218492 已在 origin/main + 落档 docs/kelly/analysis/kelly-k2c5-dailypool-ratio.md + 主站 ss.fx8.store lab.js 线上含「比值4.55」;备站 sss.sugas.site 前端同步滞后未命中,主站已上线即算上线) |
| 60 | **分析参考点AI监控窗口语义改数据范围** | 2026-08-16 用户观察"窗口切换没实质影响" | 窗口按钮(30/60/90)从"滚动计算宽度"改为"整个曲线图数据范围"(更名「显示范围」):点N日=两图显示最近N天曲线段(前端截取,统计口径固定60日滚动,后端 rolling 只留60一套降体积);卡 tooltip+help 弹窗补说明 | **已完成**(2026-08-16 二次迭代,版本串 a275) |
| 61 | **邮件/飞书信号带「回测宇宙+AI过滤+AI警示+AI建议」标记(提高可信度)** | 2026-08-17 用户定(用户原话:"邮件抄送信号时也要参考首页的回测宇宙 有一个标记。不在回测宇宙和ai建议ai仓位的都要明确标注。反过来在的就要强化展示...提高可信度 加强对就和首页一样 ai警示 ai建议123" + 两轮澄清:①"被ai过滤的当日已满和降亏过滤 改为ai过滤吧" ②"ai过滤时包括了降亏过滤和ai仓位建议的过滤") | 发盘中信号邮件/飞书时,每个信号带首页同款标记(口径以用户两轮澄清为准):①**回测宇宙**:不在 `_bt_in_universe` → 标「未入回测宇宙」(历史表现不背书)②**AI 过滤(统称)**:被 AI 处理掉的信号统一标「AI 过滤」,涵盖两类(AI降亏层 + AI仓位层,两开关正交):降亏过滤(命中降亏键→建议回避;未入样本→未入样本标注)+ AI 仓位建议过滤(当日已满=超出 top-K)。⚠**注意**:AI 过滤 ≠ AI 警示(用户 2026-08-17 明确纠正:首页「AI警示」和「AI降亏过滤」不是一回事)③**AI 警示(独立类别)**:入宇宙卖出信号(sell/sell_stop_loss/波段减仓)→ 亮橙警示(离场保护,与 AI 过滤正交)④**AI 建议 top-K**:在 AI 建议/AI 仓位(top-K)→ **强化展示**(类比首页「AI建议 1/2/3」badge)。数据源=打通 overview.json 的 `_bt_in_universe`/`ai_macro`/AI仓位判定(queries.py 从回测侧注入)到 check_signals.py 邮件/飞书。目的:明确告诉用户"这个信号回测认不认、AI 认不认",提高信号可信度 | **已完成**(2026-08-17 commit a22aa741a 已在 origin/main:check_signals.py L49/L544-790 全实现+README L103 已记录,见 docs/optimization-closeout-list.md §3.4) |
| 62 | **overview.date 盘中过时不更新(前后端"今日"锚过时的根因)** | 2026-08-17 用户报高亮 bug 根因(reviewer 核实) | overview.json 盘中 `date` 字段停在评分日(如 8/14),但 `signals_today` 已含盘中最新信号日(8/17),导致:①首页信号卡今日高亮锚过时(已前端修:信号卡 todayDate 锚 signals_today 最新日期,max 语义,commit 121e6fb63 + 补丁)②走势图 T 日提示 `_todayDateB2` 漏判"今日该指数有信号"(L6005,已上线功能行为,**待用户确认是否连修**,§23.7)③凯利 KPI 预估经 reviewer 核实**非真同类**(数据源本身就是评分日,自洽)。后端根修(盘中重算 overview 时同步 date 到最新交易日)未实施,待前端补丁稳定后评估 | **待办**(前端已修高亮;走势图 T 日待用户确认;后端根修未定) |

## 十一、v1.1.2 与优化批次增补(2026-08-18 cron 同步)

| # | 项 | 出处 | 说明 | 状态 |
|---|---|---|---|---|
| 63 | **v1.1.2 凯利三键改造** | 2026-08-17 用户拍板三开关设计 + §5.4⑥ 版本升级原则 | excludeSpecialBear 从 MA60 熊 升级四档判定(默认开主键)+ 2 默认关备选键(legacyMa60Special 老MA60熊×追买 / declinePhaseSpecial 下降期×buy_special)+ NEW 徽标;tag v1.1.2,§5.4 基准升级(四档升级仍 8 键+2 备选默认关不计数);R1_all +65,551 复现 | **已实施待 merge 验收**(2026-08-18 implementer 完成,feat/v112-kelly-3keys-plus-track,reviewer 验收中) |
| 64 | **历史四档轨迹图** | 2026-08-17 用户拍板形态 | hs300 走势图底部四档色带(涨红跌绿)+独立时间线面板(近1年/近5年/全史2002切换)+tooltip 显示大盘四档;market_tier_history.json 5773条(2002-11-08起);纯展示不影响过滤(§23.7) | **已实施待 merge 验收**(2026-08-18,同 v1.1.2 分支;数据产物 gitignored 待 R2/deploy 上线) |
| 69 | **四档升级 v2:excludeSpecialBear 判定源换单指数 cyb(创业板)** | docs/market-state/kelly-fourtier-v2-multiindex.md(2026-08-18 researcher 穷举) | v1.1.2 已上线主键 excludeSpecialBear 现判定源硬编码 hs300,回测实测 G 模式负边际(-8,053 vs 无键);15 套判定源穷举全 ≥ 基准,最优=单指数 cyb 四档排除{熊市·主跌,下降期}(G +16,720/+12.86pp,9 模式 8 正,cap/分半全优,按年总量正分布不均 2023 -10,237;**稳定性补测(kelly-fourtier-v2-multiindex-stability.md):cyb 是总量赢家非逐年稳定赢家,按年 Δ=-9,703 有负年,需用户知悉此权衡再拍板**);次优=投票 core8 最差(G +15,504 但 A-F 短持模式负);另议首页「多指数档位展示」副 chip(研究层,纯展示)。**2026-08-19 用户拍板:不动 v1.1.2 默认主键(保留 hs300),改为新增非默认推荐的降亏新键 excludeSpecialBearCyb(cyb 四档版,默认关+🆕NEW,凯利区加独立开关供人工复测)** | **已实施待 merge 验收**(2026-08-19 implementer 实施:后端回测注入 market_tier_cyb + queries.py cyb 四档谓词(默认不进组合) + lab.js 新键 toggle + app.js/purpose-notes 公示;signal_kelly_trades.json 已重跑并上传 R2) | **implementer 完成待 merge** |
| 65 | **优化批次 B:采集层提速** | docs/ab-refactor-bug-reflection.md + docs/optimization-closeout-list.md §3.1 | ab37 baostock 降并发+熔断(10001011 黑名单 re-login 增强)/ ab38 core 采集提速(删 sw 指数注意波及 board_etf_map/凯利/首页 §22/§23.6) | **待办**(2026-08-18 建,任务 #21) |
| 66 | **优化批次 C:O2 etf_score 提速** | docs/update-all-20260817-88min-analysis.md | export_etf_score_list.py L580 workers 6→8-10+空返降重试,省 2-3min | **待办**(2026-08-18 建,任务 #21) |
| 67 | **优化批次 D:宇宙规则首页 1:1 走查+双副本清理** | pending #51/#56 | 首页读 _bt_in_universe 无自算+8 步联动走查(#51);signal_notified.json 双副本 symlink+断言 REPO 落 trade-data(#56) | **待办**(2026-08-18 建,任务 #22,等 v1.1.2 合完避同文件冲突) |
| 68 | **优化批次 E:降亏面板口径标注** | pending #46 | 补「不含仓位控制/峰值持仓961万」口径说明+真实对照行(AI仓位 K=2 全开=G少赚约17.7万),纯展示文案 §21 公示同步 | **已完成**(2026-08-18,commit 63fb27391,分支 worktree-agent-a28682160e85b9dd4 待 merge) |

## 十二、防再犯 C/D 机制实施(2026-08-19 用户拍板「并行降级安全 B」,任务 #21)

> 用户 2026-08-18 拍板:**「B 降级安全并行」**——保留研究并行+版本发布速度,从根因堵死 worktree 三个新洞(stale base/同文件并发/版本串撞号),防再犯 A/B/E 机制已上 main(782af79d1)当保险。量化依据:docs/parallel-cost-benefit-2026-08-18.md(净账打平到略亏)+ docs/conflict-overwrite-triggers-2026-08-18.md(诱因链三缺口)。全部依赖:先 merge A/B/E main(已做),避免同文件冲突。

| # | 项 | 出处 | 说明 | 状态 |
|---|---|---|---|---|
| 70 | **三缺口① base 新鲜度事前校验**(开工强制 rebase origin/main + commit 前校验 base 新鲜) | docs/conflict-overwrite-triggers-2026-08-18.md 三缺口 | worktree 开工前强制 `git rebase origin/main` 或校验 base 新鲜度;commit 前校验「工作树内容==提交基点」防 stale base 提交(本次 bf8841966 被 e3fa985c3 覆盖根因) | **待办**(2026-08-19 建,任务 #21) |
| 71 | **C 同文件并发串行工具化 + worktree agent 不 bump 版本串** | docs/conflict-overwrite-rootcause-2026-08-18.md 建议C | app.js/lab.js/common.js 等大文件同时只允许 1 个 agent 持有改动权(主控派单前核对在跑 agent 文件范围,工具化串行排队);版本串统一由主控 merge 时跑一次 build_min+bump(消 aXXX 撞号 + stale bump),worktree agent 不自行 bump | **待办**(2026-08-19 建,任务 #21) |
| 72 | **D push main 统一入口 + 三缺口③ bump 模式唯一权威** | docs/conflict-overwrite-rootcause-2026-08-18.md 建议D | agent 只推 feat 分支,merge+push main 由主控统一走(含 §24⑤+bump 校验);agent 完成报告必带「base commit + 版本串前后值」;bump 模式唯一权威入口(消除 §24 撞号二义) | **待办**(2026-08-19 建,任务 #21) |

## 十三、多指数四档展示扩展(2026-08-19 用户定,纯展示,等安排再实施)

> 背景:hs300 已有四档色带/轨迹图(历史轨迹图 #64 已实施待 merge)。用户 2026-08-19 看四档升级 v2 多指数稳定性报告后,想其他宽基也展示各自四档。**已明确:纯展示(每个指数自己的四档,价 vs 自己 MA200 + MA排列),不影响过滤;不需要回测报告(展示自己状态无选优问题,与 hs300 现有色带同构)**。用户问过 sh 用 core5/core8 还是独立 → 拍板独立做(core5/core8 融合四档是判定源/全局市场状态概念,不进单指数卡片,语义会乱)。实施前确认各指数 index_daily 数据起点长度(kc50 起点 2020,历史色带短一截属正常)。

| # | 项 | 出处 | 说明 | 状态 |
|---|---|---|---|---|
| 73 | **8代宽基四档展示(core8 全家):sh/sz/hs300/csi500/cyb/sz50/csi1000/kc50 各自走势图四档色带/轨迹图** | docs/market-state/kelly-fourtier-v2-multiindex-stability.md + 用户 2026-08-19 拍板 | **hs300 已完成(历史轨迹图 #64)**;其余 7 个(sh/sz/csi500/cyb/sz50/csi1000/kc50)待做。后端 per-index 注入 tiers(现仅 hs300:app/queries.py index_detail L1683 写死 `index_id=='hs300'`),四档算法按各指数自己的价 vs MA200 + MA20/60/120 排列(index_daily 已含 8 宽基数据);前端色带/轨迹图放开给 7 指数;纯展示不影响过滤(§23.7 只增不改);走 §24 版本串+§22 三步同步;core5/core8 融合四档不在本项(研究层,仅当未来做判定源才需报告) | **待办**(2026-08-19 用户定,等安排再实施) | **未派** |

## 十四、R2 覆盖防护根治(方案1)(2026-08-19 用户定:等稳定后跟进)

> 背景:2026-08-19 盘中线上 overview.json 被 trade 侧旧库(8-18)覆盖(手动 upload_r2.py 未带 REPO,STATIC_DIR 缺省回退 trade,抓走 trade/static-site 旧库 631607B 覆盖 R2)。已实现 方案2(盘中读 trade 侧 abort 哨兵)+ 方案3(统一入口+skill 条款)+ 方案4(上传前 STATIC_DIR vs REPO 一致性比对),根因报告见 `docs/archive/overview-r2-overwrite-repo-env-20260819.md`(implementer 落档)。**方案1(读路径强校验:REPO 缺省不回退 trade)因涉及 lab/trade_sim 合法 trade 回退产物甄别,误伤面需细判,2026-08-19 用户定「落待办,等 2/3/4 稳定后再跟进」**。

| # | 项 | 出处 | 说明 | 状态 |
|---|---|---|---|---|
| 75 | **方案1:upload_r2.py 读路径强校验(REPO 缺省不回退 trade)** | docs/archive/overview-r2-overwrite-repo-env-20260819.md(researcher 方案1) | STATIC_DIR = `os.environ.get("REPO", str(ROOT))` 缺省回退 trade 是破防线点。根治:REPO 未设置 → 拒绝 upload_intraday 级命令(或改 STATIC_DIR 必须显式指向)。**关键难点**:需甄别 upload_r2.py:255(lab JSON)与 :369(trade_sim HTML)两处「design 上允许回退 trade 侧」的合法产物,一刀切拒 trade 会误伤盘后正常上传 → 逐一 cmd_upload_* 甄别哪些该回退、哪些强制 REPO。⚠️**注意(2026-08-19 reviewer 修正)**:原以为「被方案4(一致性比对)兜底覆盖」,但 reviewer 证实方案4 为结构性死闸(源根由 REPO 一次性派生恒一致,不单独触发),实际拦截由方案2(盘中哨兵)承担 → **方案1 并无方案4 兜底,若要在盘后再用手动不带 REPO 上传 trade 侧,仍需方案1 兜底**。故方案1 建议再上,不只「耐心等稳定」 | **待办**(2026-08-19 用户定:等稳定后跟进;reviewer 修正兜底前提后建议再上) | **未派** |

## 十五、TASKS.md 归档盲区改进(2026-08-19 用户催归档清理时发现)

> 背景:TASKS.md 已 233KB。自动归档脚本 `scripts/tasks_archive.py` dry-run 只归 0 块+压缩 1 行,几乎不瘦身。根因:脚本归档规则 `tasks_archive.py` L256 只认 **level 2(`##`)/level 4(`####`)** 的已完成标题,而 TASKS.md 里 **16 个 `###`(level 3)层级的已完成小块**(`### P2-新-A 采集健康度小灯 ✅` 等,全为 2026-07-20~07-29 老堆积)无法被自动识别归档。用户 2026-08-19 要求「做完的都归档,让文件小点可读性高点」。

| # | 项 | 出处 | 说明 | 状态 |
|---|---|---|---|---|
| 76 | **改进 tasks_archive.py 支持 level 3 已完成块归档(治本:让 TASKS.md 真瘦身)** | docs/tasks-archive-maintain.md + 2026-08-19 用户催清理时实测(dry-run 归0) | 脚本 L256 只归档 level 2/4 已完成标题,漏掉 level 3(`###`);TASKS.md 16 个 `### P2-新-X ✅`(7-20~7-29)老已完成块堆积不归。需扩为「level 3 且标题含 ✅/已完成/已上线」也算已完成节并入归档。**难点**:必保待办保护(归档前提取 `- [ ]` 活跃待办+`### 保留*` 子节并入 `#### 待办`,不误删;§5.3 核心保障),且 level3 非全归——只归标题明确已完成(`✅`/`已完成`/`已上线`),「### 🔴 近期/进行中/保留」等不归。B 级,涉脚本+待办保护逻辑,派 implementer 改 + 幂等重跑验 | **已完成**(2026-08-19 implementer 改 L257 level(2,4)→(2,3,4) 且 is_done_title 把关+reviewer PASS 条件性+main-merge 合 9359f798f:TASKS.md 233258→204213B 瘦身、16块归档精确、待办64→64零丢失、幂等过) | — |
| 77 | **tasks_archive.py compress_status_line 缺尾换行致熔行(压缩行熔掉下一行)** | #76 main-merge 后 reviewer 发现(find #1,2026-08-19) | `compress_status_line`(tasks_archive.py L98-116) 返回缺尾 `\n`(根因),归档时把被压缩的超长状态行与下一行内容熔成同一物理行。**实测熔 2 处历史行**:L32(`- **#16 重归类**`) + L58(`**AI 预测缺口核实**`),纯格式零数据丢失,与 level3 归档无关,是既有 bug。修复:`compress_status_line` 返回 `head + marker + "\n"` 补尾换行根治(已含排查同类,§23.2 抓出 L58 第二处)+ 手动拆 TASKS.md L32/L58 两处熔行 + 幂等重跑验(dry-run 压缩 0 行不再产生)。**关联**:第 3 处「AI 预测缺口核实」L58 也是同类,一并拆。A 级 | **已完成**(2026-08-19 用户确认「做掉吧」修 + commit e54adcb1f push main:补尾换行根治 + 拆 L32/L58 两处熔行 + 自测 py_compile/dry-run 幂等/§48】 复查清零) | — |

## 【已排除清单】已上线/已在跑(不要重复派)

- **凯利**:默认最优组合(仓位K=2+4降亏)、**金额口径=每日资金池等分+top-K**(2026-08-14 恢复 c951dafa8,修正 K=3 33万虚假杠杆;旧"每笔固定1万"为过时口径)、1月调整 J1/J2 并入、positionCap K档、G公示、**全信号表+组合使用建议**(lab.js L8503,2026-08-12)、MA60择时 toggle⑭、降亏过滤31 toggle、凯利费率客调、fade 交互方案一(lab-custom-host--loading,L7620)、稳健核心组合=仅 r8、次日开盘回测报告本身(仅建议未实施,见 #15)、**K档位评级标注+hover评级理由表格**(2026-08-13 上线 4fe5d45bc,展示层不改算法)、**凯利 top-K+质量约束+选择器前向测试 #18**(已关闭 2026-08-13:质量约束两口径负边际不实施;前向测试简单切分已有结论,滚动版并入 #16)、**K2C5 每日池同口径比值补测 #59**(2026-08-16 上线 f5d218492:K2C5 比值4.55(减亏2.88%/损盈0.63%,>2高性价比)K1档取用/K2档不取,K3 比值1.29 维持默认关,落档 kelly-k2c5-dailypool-ratio.md)
- **daily_brief**:**辩论详情入口+弃用标志+结论展示**(2026-08-12 上线 4bc48da1a)、**edge-tts 语音播报**(2026-08-16 上线 a8a4d632f,版本串 a281:后端 gen_daily_brief.py 服务端 edge-tts 合成 daily_brief_tts_<date>.mp3 上传 R2 metadata audio/mpeg,前端 _dbPlayBtn 🔊 按钮 + <audio> 经 /r2/ 代理播,弹窗+历史收盘分析两处 §22 一致,仅 meta.tts_available=true 渲染,rule/minimal 兜底不播,失败不阻塞)
- **SVG**:轻量走势图 P0+P1 全站扩展(首页 sparkline/KPI/分时,app.js L11059/L11077)、SVG 修正主链 a149、home-svg-fix P1-1/P1-2
- **daily_brief**:后端 P0-1/2/3/4 + P1-2(多空辩论随 P0-4)/P1-7/P1-8/P1-9/P1-10/P1-11(配置)/P2-1(cost_log)/P2-2(已知偏差),前端 AI 预测弹窗+命中率+历史结合展示(2026-08-11,app.js L20066-20377)
- **飞书**:阶段1 发送 + 阶段2 接收(lark-oapi 长连接+落盘+launchd)
- **R2**:迁移 P0 方案1(PURGE_SECRET)/方案2(高频 ttl=0)、前端 ./data fallback、备站主动域名策略(_isBackupSite,app.js L3849)、72h 监控(monitor_72h.sh + com.trade.monitor-72h 已加载)、feed.xml 走 R2、staticdata 同步(daily_brief)、bak-audit 残留(A+B 已合 main、signal_kelly_trades ssd 直链已改主站双兜底)
- **首页/信号**(2026-08-14/15 新增上线):**AI过滤视图两开关正交**(489f0bdb4,AI降亏=删除线层/AI仓位=badge层,review PASS)、**公示补「+1」AI宏4+3+1**(cfd37057e,回测剔除类别公示)、**§23.6 公示三处**(d798854aa,AI建议/AI警示/未入样本 tooltip+凯利区)、**§23.6 yaml+check_universe_alignment.py**(f27768c85,单一事实源+对称校验挂deploy)、**迟到信号增量补通知**(887712c27)、**盘后补齐角标 _bt_late**(89076fd1e+be1c2495b)、**8/14信号三修复**(47c23d42d:空态横条+当日已满判宇宙+定稿文案)、**$压缩冲突根治**(69f505072+根治版,terser reserved/keep-fnames)、**调教监控(过拟合监控)B档**(2026-08-15实施:首页走势图卡双曲线+综合风险分绿黄红+5条预警邮件,后端 `scripts/overfit_monitor.py`,21:40定时,设计见 docs/kelly/analysis/kelly-overfit-monitor-design.md)
- **其他**:intraday 自愈 S1-S5+S9、walk-forward-c P1 选项A(sh 去 D1a,已实施)、全球指数盘中实时 15 指数(含港股系 7 个 + ASX200/SENSEX)、场外基金阶段1 评分引擎(6维+5指标+经理+凯利)+阶段2 UI、alert-design 自定义分析 tab(AI预警/AI评分/历史类比,lab.js custom 父tab)、README 命名统一+og.png 更新、P1-1 走向量化(perf,11.87s->6.10s)、staticdata-daily-brief-sync 全部、tasks-archive-maintain、claude-md 重组/role-based-context、signal-finalize-time 两段式(2026-08-14 上线)、**O1 deploy 4遍→1遍+ab39 增量导出**(2026-08-17 上线 657607b3d,update_all 88min→30-40min 提速根因)
