# 历史优化项全量收尾清单(optimization-closeout-list)

> 盘点日期:2026-08-17 | 盘点人:role-researcher(只读盘点,不改业务代码)
> 目标:把散落的历史优化项并入**单一收尾清单**,每项有明确状态与去处,消灭"没落档/没下文"散落项。
> 来源:docs/pending-features-index.md + ab-refactor-bug-reflection.md + update-all-20260817-88min-analysis.md + r2-migration-implementation-report.md + perf-p1-plan.md + feishu-bot-integration-plan.md + data-sources.md + 代码层验证(git log / grep)。
> **口径**:只列"未实施/部分完成/需确认/远期/待办"项;已完成项进【已关闭/可关闭】。

## 一、全量优化项总表

> 编号约定:pending-XX = docs/pending-features-index.md 编号;ab-XX = docs/ab-refactor-bug-reflection.md 的 a+b 遗留(采集提速 #37/38/39,**与 pending 的 #37/38 数据源缺口是不同内容**);O1-O4 = update-all 88min 分析;R2-§6.3 = R2 报告主动通知散落项。

### 1.1 pending-features-index 未完成项(AI 预测 / 走势图 / 凯利)

| 编号 | 名称 | 来源:行 | 一句话内容 | 涉及文件 | 状态 | 依赖 | 拍板点 | 建议处理 |
|---|---|---|---|---|---|---|---|---|
| pending-#3 | daily_brief P1-1 周期定位/钟摆位置模板 | pending L18 | trend 段加恐贪/情绪/新高新低历史分位+极端逆向提示 | gen_daily_brief.py | 未实施 | 需 30 日 summary_history | 无 | 维持远期(daily_brief 增强,非优化,优先级低) |
| pending-#4 | daily_brief P1-3 公募基金持仓/行业配置注入 | pending L19 | 注入 public_fund_summary 加减仓行业 top 到【趋势研判/中期】 | gen_daily_brief.py | 未实施 | 数据已有 | 无 | 维持远期 |
| pending-#5 | daily_brief P1-4 明日关注排序分 | pending L20 | AI 关注列表从模型猜变数据排序(胜率×凯利×一致性) | gen_daily_brief.py | 部分完成(win_rate 已注入 L302-310,完整排序分未做) | signal_kelly_backtest+signal_stats 已有 | 无 | 维持远期(完整排序分=算法增强,需回测口径支持) |
| pending-#6 | daily_brief P1-5 日历效应/节假日 | pending L21 | 注入明日是否月末/季末/长假前/财报季 | gen_daily_brief.py | 未实施 | 硬编码节假日表,成本低 | 无 | 维持远期 |
| pending-#8 | 多角色阶段三:事件/新闻面分析师 | pending L23 | 独立「事件/新闻面分析角色」 | gen_daily_brief.py | 部分完成(news 数据+注入已进 risk 域;独立角色未新增) | fetch_news 已就绪 | 无 | 维持远期 |
| pending-#9 | daily_brief P1-11 reasoner(R1)深度辩论 | pending L24 | 研究员切 deepseek-reasoner(贵 3-5 倍) | gen_daily_brief.py L188 | 未启用(可选开关默认关) | cfg.researcher_model 已支持 | 是否启用?成本考量 | 维持远期(默认关,需要时用户开) |
| pending-#10 | ETF 弹窗 30 天外长历史(需求2) | pending L30 | etf/{code}-all.json 新产物+弹窗 period tab | export.py + app.js | 未派 | **数据源待调研(阻塞项)** | 无 | 维持远期(阻塞在数据源调研) |
| pending-#11 | 场外基金净值走势+弹窗历史(需求3) | pending L31 | fund_nav/{code}.json 导出+行点击详情弹窗 | export.py + app.js | 未派 | **依赖 fund_basic 字段补齐** | 无 | 维持远期(依赖 PF 阶段数据) |
| pending-#12 | 走势图 canvas 轻量组件统一改造 | pending L32 | 统一 20+ 处散落实现为 canvas 组件 | app.js/lab.js/common.js | 未派 | P0 配置框架已部分落地(siteCfg) | **方案待用户确认** | 需拍板(动全站走势图,§23.7) |
| pending-#13 | SVG 轻量版低优先级 fidelity 差异 | pending L33 | hideOverlap/tooltip 残留/clamp 等小项 | app.js | 未派 | 无 | 无 | 维持远期(低优先,不阻塞) |
| pending-#14 | lab_sim 费率客调 | pending L39 | lab.js 配对交易卡片加费率客调控件 | lab.js | 远期待办 | 复用凯利费率客调模式 | 无(8/13 已定低优先) | **维持远期(8/13 拍板,不翻案)** |
| pending-#15 | 凯利回测「次日开盘」口径(前端展示/默认口径) | pending L40 | lab.js 默认口径从收盘改次日开盘 | lab.js | 未派(lab.js 仍收盘口径) | 无 | **动已发布功能默认行为(§23.7)** | 需拍板:是否改默认口径。注:次日玩法已作为操作建议进首页参考说明弹窗(commit 0eb1ef5ea/2026-08-15),但回测默认口径仍收盘 |
| pending-#17 | 凯利 v5 候选方法 4 项 | pending L42 | Decision set/PSM/漂移检测/NSGA-II | 回测脚本 | 未实施(可选) | 无 | 无 | 维持远期(v5 可选方向) |
| pending-#19 | 港股/全球加 MA60 择时 | pending L43 | HSI/SPX MA60 按需扩展 | 回测脚本+lab.js | 未实施(建议可选) | 无 | 无 | 维持远期 |
| pending-#20 | 凯利交叉分组卡片二级筛选 | pending L44 | 交叉卡片做可切换二级筛选 | lab.js | 远期待办 | 无 | 无(8/13 已定低优先) | **维持远期(8/13 拍板,不翻案)** |
| pending-#21 | 高胜率子群深化研究 | pending L45 | 行业/市值/技术形态特征分析 | 回测脚本 | 远期待办 | 需扩 ETF 属性维度(n=85 样本小) | 无(8/13 已定并入 #17) | **维持远期(8/13 拍板,不翻案)** |
| pending-#22 | 凯利过滤层 walk-forward | pending L46 | 过滤层调阈值持续验证 | 回测脚本 | 未实施(研究项) | 无 | 无 | 维持远期 |

### 1.2 pending-features-index 未完成项(飞书 / R2 / 管理端 / 运维 / AI监控)

| 编号 | 名称 | 来源:行 | 一句话内容 | 涉及文件 | 状态 | 依赖 | 拍板点 | 建议处理 |
|---|---|---|---|---|---|---|---|---|
| pending-#23 | 飞书阶段3 优化 | pending L52 | 发送统一应用 API(弃 webhook)/@成员/@all/入向转告警 | notify.py | 部分完成(@/入向转告警未确认) | 阶段1/2 已实施 | @/入向转告警是否做 | 需拍板 |
| pending-#26 | R2 P1:board_etf_map 与 overview 同步+百分位固定化 | pending L60 / r2 报告 §2.2 方案4 | build 后自动触发 export 重算;百分位基线预计算固定化 | deploy.sh + build_board_etf_map.py | 部分完成/需确认(deploy.sh L118-120 build→export 已顺序执行;自动联动/固定化未做) | 无 | 百分位固定化工作量大,是否做 | 需拍板(§14 动 deploy 主链路,避时点) |
| pending-#27 | R2 P2:上传失败阻断 push+版本校验 | pending L61 / r2 报告 §2.2 方案3 | deploy.sh 关键文件 R2 上传失败阻断 push;dataRewriteHandler last-modified 校验 | deploy.sh + worker/headers.js | 需确认 | P0 已加 upload_r2 空时告警 | **失败阻断是否接受(可能误阻正常 deploy)** | 需拍板(§14 动 deploy 主链路) |
| pending-#28 | R2 P2:edge cache purge 兜底 | pending L62 / r2 报告 §2.2 方案5 | deploy.sh 末尾统一 purge / Worker 定时清理 / HIGH_FREQ TTL=5s | deploy.sh + worker/headers.js | 部分完成/需确认 | upload_r2 各命令已 purge;deploy 末尾统一 purge 未加 | 选哪种方案 | 需拍板(§14) |
| pending-#29 | R2 审计 P1:track_score 跨文件不一致+基线动态 | pending L63 / r2 报告 §3.2 | board_etf_map=30.2/index_detail=30.2/overview=30.9 不同 match_method | check_data_integrity.py | 部分完成(**三版本容差校验已加 L44-50,±1.0 FAIL 阻断上线**=校验兜底已闭环;**基线动态固定化未做**) | 无 | 仅剩「百分位基线固定化」是否做(工作量大可选) | 拆解:校验已闭环(可关闭);固定化需拍板(见 §3.2 第 6 条) |
| pending-#30 | R2 审计 P2×4:purge 告警/check 覆盖/_headers/upload Cache-Control | pending L64 / r2 报告 §3.3 | 4 项审计优化 | deploy.sh/upload_r2.py/worker/check_data_integrity.py | 部分完成(check 已补 etf_since_return+trade_sim_indices L48/548;其余 3 项待办) | 无 | 3 项剩余是否做 | 需拍板(§14) |
| pending-#31 | simulate_trade JSON 模式自动调度 | pending L65 / r2 报告 §3.2 P1-2 | update_lab.sh 加 launchd 定时 | update_lab.sh + launchd | 部分完成/需确认(update_lab.sh 已含 --all JSON 生成 L215-219+R2 上传;lab-auto launchd 已在跑) | 无 | 定时调度是否已满足 | **可关闭**(lab-auto launchd 已含 update_lab,JSON 已自动生成,证据:com.trade.lab-auto.plist 存在+launchctl 计数 1) |
| pending-#32 | perf 剩余小优化:etf_nt 缓存/industry 批查 | pending L66 / perf-p1-plan.md L264 | 共省 ~0.9s,收益小改动风险 | export.py | 未实施(低优先,建议暂不动) | 无 | 无(报告已建议暂不动) | 维持远期(低优先,建议暂不动) |
| pending-#33 | 管理端任务看板(kanban) | pending L72 | 4 列看板 + Card/Feature 模型 + worker API | 新功能 | 未派(排期周末或下周) | 无(已设计完整) | 排期 | 需拍板(排期) |
| pending-#34 | 场外基金阶段3:场内外联动 | pending L73 | ETF 联接跟踪误差 | 新功能 | 未派 | 阶段1/2 已上线 | 排期 | 需拍板(排期) |
| pending-#35 | 理财专员使用指南 about 页上线 | pending L74 | 613 行指南上线 about 页或就放 docs | about 页 | 未派 | 无 | **上线位置:about 页 vs docs** | 需拍板 |
| pending-#42 | 上下文优化 3 项 | pending L91 | OPT-2 索引瘦身/OPT-1 轮询降本/OPT-3 会话瘦身 | memory/规范 | 未派 | 无 | **执行顺序** | 需拍板(已部分落地:P0-1 已落 memory persist-before-clear-compact) |
| pending-#46 | 降亏面板①口径标注+真实对照行 | pending L95 | 补「不含仓位控制/峰值持仓961万」口径说明+真实对照行 | lab.js | 已完成(2026-08-18,commit 63fb27391) | 数据/逻辑已有 | 无 | 已完成:口径行(fadeHow)+真实对照行(总建议)+purpose-notes公示;数字现网复算(991万→961万旧口径过时,17.7万替代23.9万),见分支 worktree-agent-a28682160e85b9dd4 |
| pending-#47 | K 档位评级 A 模式数值溯源落档+每日池重算 | pending L96 | 穷举数据落档;页面 _pcRating 重算 | lab.js/common.js | 部分完成(穷举已落档;页面重算已并入 #48 完成) | 无 | 无 | **可关闭**(#48 已重算落地,§22 三处一致) |
| pending-#51 | §23.6 入样宇宙规则落地(首页 1:1 遵从/变更联动走查) | pending L100 | yaml+check 已上线;首页 1:1 遵从/8 步联动待全量验证 | app.js/export.py/check_universe_alignment.py | **已完成**(2026-08-18 批次D收尾验证:①首页读 `_bt_in_universe` 标记无自算(app.js L2659-2661 过滤 `_bt_in_universe!==false`+排除卖类, 候选⊆BUY_SIGNALS) ②check_universe_alignment.py 四断言全 PASS(198信号对称/84候选⊆白名单/177096笔无排除/排除类别正确) ③三处公示全在(purpose-notes.js+app.js L2273+lab.js L8988/L9787) ④8步联动: deploy.sh 链 build_board_etf_map(L106)→export(L118)→check(L147)→§22三步(rsync+R2+push), **注: step3 重跑 signal_kelly_backtest 非自动, 手改回测标准须先手动重跑再 deploy**(本次收尾未重跑回测) ⑤举一反三: 首页/lab.js AI仓位/check_signals邮件/首页删除线 4 展示位均读标记不自算) | 无 | 无 | **已完成**(2026-08-18 批次D 收尾) |
| pending-#56 | signal_notified.json 双副本清理 | pending L112 | trade-data/data(权威 13 条)vs trade/data(旧 11 条)双份;cd trade 跑 python 会误读旧副本重发 | check_signals.py+data/signal_notified.json | **已完成**(2026-08-18 批次D: check_signals.py 通知去重状态权威化——signal_notified/subscriptions_notified/fade_notified 三去重文件强制读写 trade-data/data 权威份, 非权威仓库运行(如 cd trade)自动重定向+启动告警, 防误读旧镜像重发; 与 app/db.py .absolute() 同口径) | 无 | 无 | **已完成**(2026-08-18 批次D) |
| pending-#61 | 邮件/飞书信号带「回测宇宙+AI过滤+AI警示+AI建议」标记 | pending L122 | 每信号带首页同款标记提高可信度 | check_signals.py | **实际已完成**(commit a22aa741a 2026-08-17 19:14 已在 origin/main;check_signals.py L49/L544-790 全实现+README L103 已记录) | 无 | 无 | **可关闭**(pending 索引 8/17 早间同步,未赶上当晚上线) |
| pending-#62 | overview.date 盘中过时不更新 | pending L123 | 盘中 date 停在评分日,前后端"今日"锚过时 | app.js(前端已修 121e6fb63)+queries.py(后端根修未定) | 待办(前端已修高亮;走势图 T 日待用户确认;后端根修未定) | 无 | **走势图 T 日是否连修(§23.7)** | 需拍板(动已发布功能行为) |

### 1.3 ab-refactor 遗留(a+b 采集提速 #37/38/39)—— 与 pending #37/38 不同内容

| 编号 | 名称 | 来源:行 | 一句话内容 | 涉及文件 | 状态 | 依赖 | 拍板点 | 建议处理 |
|---|---|---|---|---|---|---|---|---|
| ab-#37 | 降并发+A 熔断 | ab-refactor L31 | baostock 并发降低/熔断(10001011 黑名单 re-login 增强) | baostock_worker.py/parallel/runner.py | 未执行(仅 ab-refactor 落档,无独立方案 md) | 无 | 无(收益=采集稳定性/风控) | **本轮做**(采集层提速,与 O1 部署层独立,可同批) |
| ab-#38 | core 采集提速 | ab-refactor L32 | pipeline.sh/indicators.yaml/fetchers 提速 | pipeline.sh/indicators.yaml/fetchers | 未执行 | 无 | 删 sw 指数波及 board_etf_map/凯利/首页(§22/§23.6)需谨慎 | **本轮做**(与 O1 同批,注意删指数波及面) |
| ab-#39 | deploy 增量导出 | ab-refactor L33 | deploy 只导出变化 JSON,避免全量重算 353 JSON | deploy.sh/export.py | 未执行 | 无 | **与 O1 并合决策** | **并合 O1**(见 §2 并合分析,并合后关闭) |

### 1.4 update-all 88min 分析(O1-O4)

| 编号 | 名称 | 来源:行 | 一句话内容 | 涉及文件 | 状态 | 依赖 | 拍板点 | 建议处理 |
|---|---|---|---|---|---|---|---|---|
| O1 | deploy 4 遍→1 遍 | 88min L71-75 | 前 3 条 pipeline 只 collect+轻量 push,最后统一 1 次完整 deploy(export+rsync+R2+备份) | update_all.sh/pipeline.sh/deploy.sh | 未做(最大优化,省 50-58min) | 依赖采集时序;改锁逻辑 | **与"各 pipeline 独立上线"设计初衷冲突(需确认)** | **本轮做**(最高收益;§14 避时点) |
| O2 | etf_score 提速 | 88min L77-79 | workers 6→8-10 + 空返降重试 + mootdx 服务器复用 | scripts/export_etf_score_list.py L580(n_workers=min(6,...)) | 未做(省 2-3min) | 无 | 无 | **本轮做**(独立脚本,低风险) |
| O3 | mootdx 停服 fallback 降延迟 | 88min L81-84 | 降连败阈值/提前并发切 fallback(外部因素) | pipeline.sh | 未做(省 2-4min) | 外部源状态 | 阈值太低误判抖动 | 需拍板(外部因素,优先级低) |
| O4 | check_version_consistency 秒级确认 | 88min L86-87 | 8/17 新增,确认秒级即可忽略 | deploy.sh | 已上线(8/17) | 无 | 无 | **可关闭**(已确认秒级非主因;若未来分钟级再加 stage 计时) |

### 1.5 其他散落项

| 编号 | 名称 | 来源:行 | 一句话内容 | 涉及文件 | 状态 | 依赖 | 拍板点 | 建议处理 |
|---|---|---|---|---|---|---|---|---|
| R2-§6.3 | 主动通知方案(launchd WatchPaths 监听进度文件) | r2 报告 L324-329 | 进度文件变化触发 notify.py 告警;agent prompt 规范更新 | launchd + agent 规范 | 部分完成(notify_agent_done 已实现 notify.py L985;WatchPaths 未落地) | 无 | WatchPaths 增强是否做 | 需拍板(可选增强,优先级低) |
| DS-国际期货 | wti/comex_silver/brent 数据源 | data-sources.md L332 | 新浪 futures_foreign_hist 未实施(列入次优先) | 采集脚本 | 未实施(数据源缺口) | 无 | 无 | 维持远期(次优先数据源缺口) |

## 二、关键并合与互斥分析

### 2.1 #39(deploy 增量导出)与 O1(deploy 4遍→1遍)—— 可并合,并合后 #39 关闭

- **方向不同但互补**:O1 解决"deploy 被调 4 遍"(每次都是完整 export+rsync+R2+备份,77.2min/87.5% 主因);ab-#39 解决"单次 deploy 内 export 全量重算 353 JSON"(4 遍=4 次重复重算,最纯粹的重复劳动)。
- **并合方案**:O1 改造后,最后一次统一完整 deploy 时,export 仍会全量重算 353 JSON → ab-#39 增量导出(只重算变更 JSON)作为 O1 的配套一起做,收益最大化。
- **并合后 #39 可关闭**:不再是独立项,归属 O1 批次实施。
- **风险提醒(ab-refactor §三)**:增量判定"带日期文件跳过"有静默用旧数据风险(8-14 偏样本同类);必须建"必更白名单"(overview/board_etf_map/信号产物等强制全量)+ §22 三查(R2/static-site 同步)。
- **并合交付要求**:改后必须跑**完整 update_all** 验证(不只 deploy),防增量判定误跳;§14 避盘后时点。

### 2.2 ab-#37/#38 与 O1 互相独立,可同批做

- **层不同**:ab-#37/#38 是采集层(baostock_worker/pipeline.sh/indicators.yaml),O1 是部署层(update_all.sh/pipeline.sh/deploy.sh)。pipeline.sh 内部 collect→compute→deploy 是先后阶段,改动点不重叠。
- **同批做可行性**:三者都动 pipeline.sh/update_all.sh 主链路(§14),但改动面不冲突(采集 vs 部署),可同批。**但都需避盘后时点 + 完整 update_all 回归**。
- **注意**:ab-#38 删 sw 指数会波及 board_etf_map/凯利回测/首页(§22/§23.6),删前 grep 全站引用;ab-#37 改共享状态(circuit_open)需 grep 读写双方。

### 2.3 动"宇宙规则/回测口径/已发布功能默认行为"项(§23.6/§23.7 冻结契约)→ 标「需用户确认」

| 项 | 动什么 | 冻结性质 |
|---|---|---|
| pending-#15 | lab.js 回测默认口径收盘→次日开盘 | 动已发布功能默认行为(§23.7) |
| pending-#62 | 走势图 T 日提示连修 + 后端根修 | 动已发布功能行为(§23.7) |
| pending-#12 | 全站走势图统一 canvas 组件 | 动 20+ 处已发布展示(§23.7) |
| pending-#51 | 首页 1:1 遵从宇宙规则(读标记不自算) | §23.6 既定规则落地收尾(已定,不需确认,只收尾验证) |
| pending-#46 | 降亏面板口径标注 | 纯展示文案新增,不破坏默认行为(§21 公示) |

### 2.4 动"盘后部署主链路"项(§14 生产稳定性)→ 标「需避时点/需确认」

| 项 | 动主链路哪段 | 避时点要求 |
|---|---|---|
| O1 | update_all.sh/pipeline.sh/deploy.sh 核心链路 | 必须避开 15:35/16:00/17:50/20:35/22:00;周末可随时 |
| ab-#39(并合 O1) | deploy.sh/export.py | 同上 |
| ab-#37/#38 | pipeline.sh/baostock_worker | 同上 |
| pending-#27 | deploy.sh R2 阻断逻辑 | 同上 |
| pending-#28 | deploy.sh 末尾统一 purge | 同上 |
| O2 | export_etf_score_list.py(update_all 内) | 同上 |

## 三、批次清单

### 3.1 建议本轮做(依赖已满足、无冻结冲突、收益明确)

| 批次 | 项 | 收益 | 涉及文件 | 为什么这批发 |
|---|---|---|---|---|
| **批次 A:update_all 提速(部署层)** | O1 + ab-#39(并合) | 88min→30-40min(省 50-58min),8 月唯一 >70min 离群根因 | update_all.sh/pipeline.sh/deploy.sh/export.py | 最大收益;88min 分析结论优先;§14 避时点+完整 update_all 回归 |
| **批次 B:update_all 提速(采集层)** | ab-#37 + ab-#38 | 采集稳定/提速(宽 224s→更低) | baostock_worker.py/pipeline.sh/indicators.yaml/fetchers | 与 A 独立;删 sw 指数前 grep 全站引用(§22/§23.6) |
| **批次 C:etf_score 提速** | O2 | 省 2-3min | scripts/export_etf_score_list.py L580 | 独立脚本,低风险,workers 6→8-10+空返缓存 |
| **批次 D:宇宙规则收尾 + 一致性** | pending-#51 首页 1:1 遵从走查 + pending-#56 双副本清理 | 规则对齐 + 防误读旧副本重发 | app.js/export.py + check_signals.py/data | 已定项收尾;低风险 |
| **批次 E:降亏面板口径标注** | pending-#46 | 用户可理解口径(不含仓位控制/峰值持仓961万) | lab.js | ✅已完成(2026-08-18,commit 63fb27391,分支 worktree-agent-a28682160e85b9dd4 待 merge):纯展示文案+§21 公示同步;数字现网复算(991万旧口径过时→961万;23.9万→17.7万) |
| **批次 F:首页分时快照兜底渲染昨日曲线(bug修复,2026-08-18)** | 用户报:实时拉取失败 fallback 快照只显示文字,应看快照分时图本身 | 分时图实时失败时仍可看昨日全天曲线(而非一行文字) | app/collector/intraday_snapshot.py + static-site/app.js | 数据层盘后(is_closed)拉东财 trends2 ndays=1 全天分时注入 indices[].minute_series(约240点 9:30-15:00);前端 `_renderIntradayChart` 失败分支优先 `_renderSnapMinuteSeries` 复用 _lwSetup 渲染管线画昨日折线(昨收虚线+午休),无 minute_series 保持文字平滑降级。本地 Playwright 模拟验证:注入331点→block 东财→sh svg path 出现/intraday-fail=0;未注入 sz→文字降级;未 block→实时分支无回归。盘后需主控验证线上全天序列(盘中接口只返到当前分钟)。分支 feat/snapshot-intraday-curve |

### 3.2 需拍板清单(每条写清要用户决定什么)

1. **pending-#15 次日开盘口径**:lab.js 回测默认口径收盘→次日开盘,动已发布默认行为(§23.7)。注:次日玩法已作为操作建议进首页参考说明(0eb1ef5ea),这里只问"回测默认口径是否也改"。
2. **pending-#62 overview.date 后端根修**:走势图 T 日提示是否连修(§23.7);后端根修(queries.py 盘中同步 date)是否实施。
3. **pending-#12 走势图 canvas 统一组件化**:方案是否确认(动 20+ 处已发布展示)。
4. **pending-#27 R2 上传失败阻断 push**:是否接受"关键文件 R2 上传失败即阻断 push"(可能误阻正常 deploy)。
5. **pending-#28 edge cache purge 兜底**:选哪种(deploy 末尾统一 purge / Worker 定时清理 / HIGH_FREQ TTL=5s)。
6. **pending-#26/#29 百分位基线固定化**:工作量大可选,是否做。
7. **pending-#30 R2 审计 P2 剩余 3 项**:purge 失败告警/_headers/upload_r2 Cache-Control 是否做。
8. **pending-#23 飞书阶段3**:@成员/@all/入向转告警是否做。
9. **pending-#35 理财 about 页**:上线位置(about 页 vs 就放 docs)。
10. **pending-#42 上下文优化顺序**:OPT-1/2/3 执行顺序(P0-1 已部分落地)。
11. **pending-#33/#34 排期**:看板/场外联动排期。
12. **O3 mootdx 降延迟**:阈值降低是否接受(外部因素,优先级低)。
13. **R2-§6.3 WatchPaths 主动通知增强**:是否做(可选增强)。

### 3.3 维持远期清单(用户 8/13 已拍板低优先,注明不翻案)

| 项 | 依据 |
|---|---|
| pending-#14 lab_sim 费率客调 | 2026-08-13 用户定低优先级(pending L39) |
| pending-#20 交叉分组二级筛选 | 2026-08-13 用户定:样本坍塌+置顶已缓解,ROI 低暂缓(pending L44) |
| pending-#21 高胜率子群深化 | 2026-08-13 用户定:并入 #17 v5,需先扩 ETF 属性维度(pending L45) |
| pending-#17 v5 候选方法 | v5 可选方向 |
| pending-#19 港股/全球 MA60 | 建议可选 |
| pending-#22 过滤层 walk-forward | 研究项 |
| pending-#13 SVG fidelity 小项 | 低优先不阻塞 |
| pending-#32 perf 剩余小优化 | 报告已建议暂不动(perf-p1-plan L264) |
| pending-#3/#4/#5/#6/#8/#9 daily_brief P1 增强 | daily_brief 增强类,非优化,优先级低 |
| pending-#10/#11 走势图需求 | 阻塞在数据源调研/fund_basic 字段补齐 |
| DS-国际期货 | 次优先数据源缺口 |

### 3.4 已关闭/可关闭清单(已被后续版本覆盖/可并合,注明依据)

| 项 | 依据 |
|---|---|
| pending-#16 凯利 Walk-forward 滚动验证 | 已完成:commit 299db6167 已在 origin/main(2026-08-16)+ 落档 kelly-walkforward-validate.md |
| pending-#61 邮件/飞书信号标记 | **已完成**:commit a22aa741a(2026-08-17 19:14)已在 origin/main;check_signals.py L49/L544-790 全实现+README L103 记录。pending 索引状态过时 |
| pending-#47 K 档位评级数值重算 | 页面 _pcRating 已并入 #48 完成(2026-08-14),§22 三处一致 |
| pending-#31 simulate_trade 定时调度 | update_lab.sh 已含 --all JSON 生成(L215-219)+R2 上传;com.trade.lab-auto launchd 已在跑(launchctl 计数 1) |
| pending-#29 track_score 跨文件不一致(校验部分) | check_data_integrity.py L44-50 已加三版本容差校验(±1.0 FAIL 阻断上线),监控兜底已闭环;仅剩「百分位固定化」需拍板 |
| O4 check_version_consistency | 已上线且确认秒级非主因,可忽略(88min L86-87) |
| ab-#39 deploy 增量导出 | 并合 O1(见 §2.1),不再是独立项 |
| pending-#50 每日池默认 K/toggle 决策 | 用户 2026-08-14 已定,README 已含 6 处每日池/基础5/K2C5 落档 |
| pending-#56 双副本清理 | **已完成(2026-08-18 批次D)**: check_signals.py 通知去重状态权威化(读写强制落 trade-data/data 权威份+非权威重定向告警),「cd trade 跑 python 误读旧副本重发」尾巴根治,详见 §1.2 行 |

## 四、统计

| 类别 | 数量 |
|---|---|
| 全量优化项(总) | 44(表内:1.1×17 + 1.2×18 + ab×3 + O×4 + 散落×2) |
| 建议本轮做(批次 A-E) | 7 项(#46/#51/#56/ab37/ab38/O1/O2) |
| 需拍板 | 15 项 |
| 维持远期 | 17 项 |
| 已关闭/可关闭 | 5 项(表内)+ 表外早已完成 #16/#50(补充说明防重复派单) |
> 口径说明:44 = 7 本轮 + 15 拍板 + 17 远期 + 5 已关闭;表外 #16/#50 早已完成不在待办计数,仅防重复派单列出。

## 复现

- **来源文档**(全部已 tracked):docs/pending-features-index.md / docs/ab-refactor-bug-reflection.md / docs/update-all-20260817-88min-analysis.md / docs/r2-migration-implementation-report.md / docs/perf-p1-plan.md / docs/feishu-bot-integration-plan.md / docs/data-sources.md
- **证据命令**:
  - `git log origin/main --oneline | grep a22aa741a`(pending-#61 已上线,2026-08-17 19:14)
  - `git log origin/main --oneline | grep 299db6167`(pending-#16 walk-forward 已完成)
  - `grep -n "n_workers" scripts/export_etf_score_list.py | head`(O2 现 workers=min(6,...),L580)
  - `grep -n "track_score.*容差\|TRACK_SCORE_TOLERANCE" scripts/check_data_integrity.py`(pending-#29 校验已闭环,L44-50)
  - `launchctl list | grep trade.lab-auto`(pending-#31 launchd 在跑)
  - `grep -n "check_version_consistency" scripts/deploy.sh`(O4 已上线)
- **数据截止**:2026-08-17 20:53(git status 快照);update-all 88min 分析数据截止 2026-08-17 19:18
- **关键口径**:本清单只列"未实施/部分完成/需确认/远期/待办";已完成项一律进【已关闭/可关闭】并注明 commit/行号证据,不保留在"待办"里防重复派单
