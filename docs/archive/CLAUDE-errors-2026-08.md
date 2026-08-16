# CLAUDE.md §18 犯错积累原文快照(2026-08-12 归档)

> 本节为 CLAUDE.md §18 犯错积累与防重犯(2026-08-08 起)原文全量快照,由 CLAUDE.md 整理提炼(去重12+提炼8+归档3大件)归档。
> 原文出处:CLAUDE.md L205-287(归档前版本,commit 见 git log)。CLAUDE.md 现保留索引+防重犯精华,索引能反向追到此原文。
> 反向追踪:文件末尾附「防重犯锚点索引」块(L01-L40 过错锚点 + E01-E30 经验锚点,每行含归档行号),根 CLAUDE.md §18 索引表逐行对锚点 id,`grep -c '^L[0-9]'` == 40 = 零丢失校验锚。
> 归档日期:2026-08-12

---

## 18. 犯错积累与防重犯(2026-08-08 起,每次犯错追加)
用户定:慢慢积累经验迭代完美。每次犯错记录于此 + 防重犯条款,不重犯同类。
- **2026-08-08 犯错 7 条**:
  1. 通知丢失不设 cron 傻等(§11:cron 兜底必设防傻等;2026-08-09 调研穷尽无完美主动通知主控方案,cron 兜底是架构限制下最优残余)
  2. DB 方案理解反复 3 次纠正(防:关键决策前复述理解让用户确认,不臆断不反复)
  3. 架构偏差 exclude 偏离全量本意(防:用户说"全量/全部"不擅自 exclude/清理,先确认)
  4. .gz 断定不严谨凭 memory(防:断定前验证,memory 可能过时,不凭记忆断定)
  5. agent 误报 trade/trade-data 混淆未识破(防:agent 关键结论 §0 验,尤其路径/文件数类)
  6. cherry-pick 撞冲突 + 干扰后台 agent(防:切分支/checkout 前 CronList + 查后台 agent 是否改文件)
  7. hoverpop 方案试错(防:方案先调研充分再实施,不边试边改)
- **通知机制(2026-08-09 调研穷尽修正)**:见 §11。harness 架构硬限制无完美主动通知主控方案(SendMessage~1.9%/task-notification~12% 都走队列不可靠,队列"单消息注入清除其余"+多agent竞争96%丢;SubagentStop hook 注入子agent非主控;无CLI向运行中session注入),cron 兜底是架构限制下最优残余(不阻塞前提下主控自主唯一可靠),notify.py 邮件降级只重要节点。曾误判 notify.py 主方案并实施后推翻
- **2026-08-08 会话级总结追加(ETF信号灯+hoverpop+lowconf+拆档阶段,5条新过错)**:
  8. ETF拆档 null 归属理解错(根因:主控把 null/N<30 极弱归入"概念无ETF"档,但"概念无ETF"=真无任何ETF匹配,null/N<30=有ETF但数据不足算出极弱分,两者语义不同;用户纠正 null 有ETF算得出分应归"有跟踪ETF"档。防:归属/分类前复述口径让用户确认,不靠语义猜测"无数据=无ETF")
  9. hoverpop"无数据"调研误判(根因:调研agent说"signal-tier没铺到hoverpop用老逻辑",实际前端三处都已用_etfLightInfo接track_tier,真因是数据产物不一致(R2 index-all旧'none' vs overview新null)+前端文案L1553 null->"无数据"应"极弱"。防:调研下结论前深入到数据产物层验证(R2旧版vs新版字段值差异),不只看代码逻辑分支;调研结论"没铺到/老逻辑"类要 grep 验证再报)
  10. low_confidence灰蓝虚线过时规则未发现(根因:信号灯统一配色时,_etfLightInfo在track_tier判断之前拦截`if(track_low_confidence) return 灰蓝虚线`,直接覆盖档位灯。统一配色只改了主路径没遍历所有拦截分支。防:改动一个灯/样式体系时遍历所有 return/分支(不只主路径),grep 所有 `return {cls:` 确认无过时拦截)
  11. 需求2理解错加未要求改动(根因:用户需求只说"信号列表中间加信号灯",主控理解成"展示ETF名/代码替代指数名/代码"并实施。加了用户没要求的改动。防:理解需求时不擅自加未要求的改动(只做明确要求的),不确定时复述需求让用户确认"是否还要改X")
  12. 至今盈亏调研方向偏差(根因:用户说"走势卡相关etf后面至今盈亏不见了",调研去查生成逻辑queries.py etf_since_return而非显示层etf-tag-pnl渲染。没对准用户实际看到的问题位置。防:调研先对准用户描述的UI位置(grep 渲染层),确认显示层无问题再查生成层,不直接跳到生成层)
  13. 量子科技调研误判"0量子ETF/不可改善"(根因:调研agent只用了当前算法匹配范围——name+track_index搜"量子"无结果+overlap只看成分股直接重叠,断定"全市场0只量子ETF/不可改善"。但用户用同花顺(第三方平台)搜到多个相关ETF(大数据516000/云计算516510/央企科技562380/科创159335),真因是算法只看成分股直接重叠不看ETF持仓重叠。第二次调研才找到根因+方案(第4层ETF持仓重叠匹配)。防:调研"无/0/不可改善"类结论,不只验证当前算法覆盖范围,要换方法/换数据源(第三方平台如同花顺概念搜索)+考虑不同关联维度(持仓重叠 vs 成分重叠),不轻断"不可改善";调研结论里列"已验证哪些方法/数据源"便于主控判断充分性)
- **token浪费(本阶段)**:①hoverpop信号灯问题重复调研(第一次误判"没铺到老逻辑"第二次才找真因数据产物不一致,应一次调研到位:代码+数据产物同查)②移动端hoverpop修复试错返工(第一次white-space:normal+flex-wrap:wrap效果更差布局错乱,方案应先充分验证移动端窄屏实际效果再实施,不靠推理)③多次429配额耗尽(L6411信号灯分层/L6506 reviewer/L6507 push告警调研,月配额耗尽致全agent终止;§17高峰期多个agent并发消耗大,防:高峰期控制并发agent数,非紧急推迟到18后)④量子科技调研重复(第一次断"0/不可改善"过早,第二次才找到持仓重叠根因+方案,同①模式复发:调研"不可改善"结论过早致二次调研,应一次调研到位:换方法/换数据源+多关联维度同查)
- **每日归纳(2026-08-08 全天 13 条过错,按主题分组,不删减只归类)**:
  - 通知机制(1条):①不设cron傻等(§11:cron兜底必设;2026-08-09穷尽无完美主动通知主控方案,cron为架构限制下最优残余)
  - 理解/口径偏差(3条):②DB方案反复3次⑧ETF拆档null归属⑪需求2加未要求改动(共性:关键决策/归属/需求前复述确认,不臆断不扩展)
  - 调研不充分/误判(4条):④.gz凭memory断定⑨hoverpop调研误判⑫至今盈亏方向偏差⑬量子科技"0/不可改善"误判(共性:下结论前验证数据产物层/换方法换数据源/对准UI位置,不只看当前算法范围)
  - 架构/全量(1条):③exclude偏离全量(防:用户说全量不擅自exclude)
  - agent结论验收(1条):⑤trade/trade-data混淆(防:路径/文件数类§0验)
  - git操作(1条):⑥cherry-pick撞冲突(防:切分支前查后台agent)
  - 实施/试错(2条):⑦hoverpop方案试错⑩lowconf过时规则未发现(共性:方案先充分调研再实施;改体系遍历所有分支)
  - token浪费:重复调研(hoverpop+量子)②试错返工(移动端)③高峰并发429(共性:一次调研到位+先验证再实施+高峰控制并发)
  - 中心思想校准:13条过错核心="调研/理解/实施前充分验证,不臆断不轻断不试错",防重犯条款保持具体可执行
- **2026-08-08 追加过错(量子科技第4层需求丢失)**:
  - 过错:①第二次调研找到第4层ETF持仓重叠方案后没落档TASKS待办,只存memory教训,致需求丢失(§7:memory非持久化写保障,落档NOTES/TASKS才是写保障) ②批量归档28条标done时把e4007405d标done+虚构完成依据(TASKS-done L1448说"做了第4层+匹配516000等ETF"),但 `git show e4007405d` commit message自述"量子科技thsc_300830确认不可改善(0量子ETF)",直接矛盾,凭commit标题臆断未核对实际内容
  - 防重犯:①调研找到方案后必须立即落档TASKS待办(不只存memory,memory非持久化) ②归档done前必须 `git show <commit>` 核对commit message实际内容,不凭commit标题/摘要臆断完成内容(commit标题可能只说大方向,body才说具体做了什么/没做什么)
- **2026-08-08 追加(方案A board_etf_map数据产物遗漏+reviewer误报,印证回归检查不完整)**:
  - 过错:①方案A agent 改 build_board_etf_map.py 代码(TRACK_WEIGHTS_INDIRECT)也重跑了生成新 board_etf_map.json(源文件trade-data/data/已是159586),但**build_board_etf_map.py写ROOT/data/(用.absolute()非.resolve()),export.py不复制board_etf_map到static-site/data/,data/->static-site/data/复制步骤遗漏**,两处static-site旧版516630+R2旧版 ②reviewer验"local board_etf_map=159586"误报,实际local static-site=516630(reviewer没真读上线文件,信agent自验或验了源文件trade-data/data/而非static-site上线文件) ③主控§0 curl board_etf_map才发现(overview 159586但board_etf_map 516630不一致),非等用户发现
  - 防重犯:①算法改动重跑数据产物时,列所有依赖该算法的数据产物清单(board_etf_map/overview/index detail/trade_sim)逐个确认**重跑+同步到static-site/data/+上传R2**三步完整,不只重跑 ②build_board_etf_map.py写ROOT/data/需手动cp到static-site/data/(export.py不复制它,data/->static-site/data/是独立步骤,memory export-output-path-sync衍生陷阱) ③reviewer验数据产物必须真读上线文件(static-site/data/或R2/CF)非源文件或agent自验,reviewer prompt明确"curl local static-site+R2+CF三处验具体字段值" ④主控§0不只验主路径(overview),验所有相关数据产物三版本一致(overview vs board_etf_map vs index detail) ⑤agent自验+reviewer+主控§0三层都需真验文件内容,任一层信结论不验文件=漏洞
- **2026-08-09 追加(量子科技3展示位数据不一致)**:
  - 过错:层B concepts.json R2未更新(方案A重跑board_etf_map时 concepts 的 upload-industry 遗漏),本地新版(159586)没上传R2,线上R2旧版(516630);层A stable_top1滞回 count=2 未切换(设计行为明天自动),term-pop 优先滞回标记(516630)非分数第一(159586)。3展示位(概念列表top1/相关ETF hoverpop/首页信号hoverpop)看到不一致数据
  - 防重犯:①更新必N处同步(数据一致性铁律§22)②算法改动重跑时列所有依赖数据产物(含concepts.json)逐个确认重跑+同步static-site+R2三步(§18已有教训重申)③滞回切换时确认3展示位(overview stable_top1+board_etf_map hysteresis+concepts)同步切换
- **2026-08-09 追加(凯利回测系列4条过错+§0证伪查错文件)**:
  14. D修正 annualized 口径判断偏差(根因:主控 prompt 指定用 total_return 总盈亏/单笔本金 开方,y1=258.78% 年化 258% 明显不合理--固定金额非复利,总盈亏/单笔本金=平均×笔数非真实收益率。用户定改 return_pct_max_holding 峰值资金收益率开方 y1≈3.04% y10≈1.37% 合理。commits 2686adf80 错->4c6d50917 修。防:指定计算口径前先验算典型值合理性,年化>100% 或负值应警觉查口径定义,不直接实施不合理口径;同§18教训⑦模式"方案先充分调研再实施"的口径版--口径也要验算非只方案)
  15. 前端改 agent 漏做2个追加 A级小改(根因:SendMessage 追加费率格式+卡间水印布局2任务给运行中 agent,送达率低~1.9%(§11)agent commit 前没处理,需另开 commit b4ac948ab 补做。防:追加任务给运行中 agent 不只靠 SendMessage,主控在 agent commit 前主动确认追加任务是否处理;或追加任务等当前 commit 后派新 agent 不追加到运行中 agent;同§11 SendMessage 不可靠的延伸--追加任务=改规格,应走"停旧派新"或"commit后新派"非SendMessage)
  16. 数据没上线 R2(根因:backfill 0d6fe0edd 没 upload signal_kelly(backtest/trades.json),CF 404 用户访问看不到。backfill 不跑 signal_kelly_backtest.py(独立脚本无 launchd)+export.py upload_r2 没传 signal_kelly。防:新数据类别上线后确认上传链路完整三步:①export.py upload_r2 清单含该类别②launchd 定时覆盖或 deploy.sh 含③backfill 补跑上传;独立脚本(无 launchd)的 backfill 手动补跑上传 R2;同§18"算法改动重跑数据产物列清单逐个确认重跑+同步static-site+R2三步"的上线链路版)
  17. §0 证伪查错文件(根因:前次 agent 说"CF edge 缓存 industry-all-concepts.json",主控 §0 跟着查错文件,实际走势图读 thsc_300830-all.json。§0 验收信 agent 说的文件名没 grep 前端渲染逻辑确认实际读哪个。防:§0 证伪前先 grep 前端渲染逻辑(fetch/dataUrl/fetchJSON)确认实际读哪个文件,不跟 agent 说的文件名查;§0 验收文件类结论时独立确认文件路径非信 agent 报告;同§18教训⑤"agent关键结论§0验"的延伸--文件名/路径类结论也要独立验非信agent)
- **token浪费(8/9凯利阶段)**:①D修正返工(第一次 total_return 错->第二次 return_pct_max_holding 修,应指定口径前验算数值合理性一次到位,同§18教训⑦模式)②SendMessage 追加任务漏做致另开 commit 补做(应追加任务不靠 SendMessage 或 commit 前确认,同§11)③数据没上线 R2 致紧急派 agent 修(应上线链路确认完整,同§18"重跑数据产物列清单")④8/9 全天100+ subagent(虽多数 justified 并行不冲突,token 消耗大,非紧急可适当控制并发数)
- **经验(非过错,8/9凯利回测+R2阶段,记录防绕路)**:
  ① R2 purge_cache 分批避 CF Worker 超时 500(commit ea64df512):一次性发400+ keys 致 Worker CPU/wall time 超限->500,改分批每批30 keys(PURGE_BATCH_SIZE,20-50安全区间)+批间 sleep 0.5s 避 CF 限流,400+ keys->14批每批30 keys 远在 Worker 时限内。适用:所有 R2 purge cache 场景(数据更新后清 CF edge 缓存),不能一次性全量 purge
  ② 持仓 hold_days 改交易日口径修复虚高(commit 9cba7ca42):hold_days 用自然日含周末致虚高,改交易日口径+跟踪 price_date。适用:所有"持有天数"类计算(回测/统计),用交易日非自然日
  ③ check_data_integrity 加3校验 + 新建 check_r2_consistency.py(commit 1d5fe3ccc):数据完整性校验扩展(3新规则)+ R2 审计脚本(本地 vs R2 一致性)。适用:数据产物改动后跑 check_data_integrity(deploy 前置)+ 定期跑 check_r2_consistency 审计 R2
  ④ 凯利回测卡间比较水印设计(蓝★综合最佳+紫◆最稳定,全局16卡互比,commit ff56d9b71):跨卡片全局互比而非单卡内比较,用颜色+符号双标识。适用:UI 多卡比较场景,全局互比+双标识设计
- **2026-08-10 追加(降亏4toggle+模拟回测费率客调阶段,2条新过错+经验)**:
  18. §21算法公示gap复发(根因:模拟回测费率5参数实施agent 963ba3881 没更新 purpose-notes.js 的算法公示文案,reviewer FAIL catch(problem 4)。同会话降亏4toggle agent c818fddd3 正确更新了 purpose-notes.js(§21同步),但费率agent没--同会话两agent一做一不做,说明 fresh context agent 不主动读§21全文,主控 prompt 未对费率agent显式要求 grep 公示点。防重犯:算法/逻辑改动 agent prompt 必含显式动作"§21:grep purpose-notes.js + app.js/lab.js 所有算法说明文案,同步更新新规则,漏=验收不过";不只引用"见§21",要列出具体 grep 动作+文件名(purpose-notes.js);fresh context agent 不读 CLAUDE.md 全文,§21规范需在 prompt 转成具体可执行动作)
  19. 前端重算与后端算法对齐不完整(根因:费率5参数实施agent移植凯利费率模型框架到 trade_sim 前端 replay 重算,但3处没逐字段对齐后端算法:①open_positions.buy_close 存 br.buyPrice(含滑点买价)非原始close,后端 buy_price=close*(1+slippage) ②equity_curve 起点应用窗口起点(w_start)非 ledger[0].date,末点应加{date:signal_last_date,value:finalTotal} ③rounds.buy_close 应用 sold 的 buy_close 平均值非首个 sub_round 值。reviewer FAIL catch 3 bug,fix 0e024896f。防重犯:前端重算类实施(replay/recompute/前端复算后端逻辑),自验须逐字段对比后端 JSON 输出--取一个 signal 的 trade_sim/sigkelly JSON,前端 replay 后逐字段对比 open_positions/rounds/equity_curve/summary 各字段值,不只对比 summary 总计;prompt 要求"自验:取一个 signal JSON,前端 replay 后逐字段对比后端输出,列对比表,不一致项列差值")
  - 经验(非过错,记录防绕路):①GitHub Actions deploy 需约90s,curl 验上线 sleep 90 非15(首次 sleep 15 curl 到旧版 SW a91 非 a92)②Edit 工具匹配含 em dash(U+2014)或特殊字符的行会失败(3次匹配失败),改用 `sed -i '' 'Nc\替换内容'` 行号替换(memory appjs-em-dash-edit 已有 em dash 记录,补充 sed fallback)③reviewer FAIL 后§0验2点(positions.push+purpose-notes)合规(§0允许 FAIL 时亲自确认再回滚/修),非违规--主控本会话较守规:全程派 background agent + §0验1-2点 + cron 兜底,未亲干调研/实施 ④intraday 走 R2 不推 main 后,盘中 push 代码 main 不用避 intraday 时点(commit 4fb1a88e9,已落§14/§16):R2 迁移后 intraday_snapshot 走 R2 不推 main,盘中 push 代码 main 改不同文件 rebase 能合不撞车。适用:盘中需 push 前端代码 main 时避 update_all(17:50)即可,不用避 intraday 每10分钟时点 ⑤分时图 1min 轮询自愈机制(S1-S5+S9,commit d2a97108b):5阶段自愈--S1 fetch 加 AbortController 8s 超时防卡死 / S2 inflight 去重 Map+15s 兜底清理防毒化 / S3 6次失败不永久停改降频5min兜底重试(7x24自愈) / S4 overview 3min 轮询心跳唤起 intraday(定时器丢失/刷新超5min则重启) / S5 visibilitychange 切回前台清 in-flight。适用:所有定时轮询类前端机制,fetch 必加超时+inflight去重+失败降频不永久停+心跳唤起+切前台清inflight ⑥决策树/子群发现数据挖掘方法论(commit 7ada31c57):手写CART决策树+beam search子群+关联规则+多维交叉,超越人工2特征穷举(最高2.52)找到78个比值>3标志(单标志最高10.06,3月+周二+高价ETF 7/7年全亏)。适用:多特征组合优化场景(降亏标志/参数寻优),用决策树找高纯度叶节点=高比值标志,非人工穷举
  - token浪费:reviewer FAIL 5问题致 fix+复审 extra round。但这是 reviewer 系统设计正常工作(catch bugs before 上线,§15),非浪费。可优化:实施agent自验更充分(逐字段对比后端)可减少 reviewer catch 的问题数,但 reviewer 存在的意义就是 catch agent 自验漏的,不需追求 agent 自验100%
- **2026-08-10 追加(每日总结,backfill整改闭环+备用站404+开源化+KPI 阶段,4条新过错+经验)**:
  20. §0 验收 grep 字面量误判"整改未落地"(根因:backfill 整改 §0 第一轮 grep 字面量 "3600" 无结果→误判"整改点未落地"(3600 无/BACKFILL_SLOT 无/校验无),实际代码用常量 `_ALARM_RECOMPUTE=3600`(hkex_ccass_quarterly.py L47-48)+`_current_slot()` 读 env 槽通道,第二轮查常量名+赋值行才确认全落地,多耗一轮验证。防重犯:§0 验"值/配置/阈值"类结论时,grep 字面量无结果先怀疑"值被封装成常量/变量/配置/env",改 grep 常量名/变量名+查赋值行确认值,不直接下"未落地/未实现"结论;§0 是确认 agent 已报结论,第一轮无结果应换更精确 grep 方式而非否定)
  21. 备用站 reviewer 卡死 22min+无进度文件(根因:reviewer agent 没按 §16 prompt 要求每步 echo 进度文件,jsonl 停 23:33:48 22min 才被 cron 轮询发现;SendMessage 唤醒无效(33min)→判定死 TaskStop 重派,浪费 22-33min+重派 token。上次卡死根因=不写进度文件。防重犯:派任何 agent(尤其 reviewer)prompt 显式"每步 echo 进度文件,不写=无法监控按卡死重派";主控轮询 jsonl mtime+进度文件双重查,卡死先 SendMessage 唤醒(成本低),>1 轮仍无活动再判定死重派并强化进度文件要求)
  22. curl -sv 泄漏 GitHub token(根因:DB Release 上传 agent 诊断 POST /releases 404 时 curl -sv,把 Authorization header 的 token 值打印进 Bash 输出泄漏到会话,用户被迫撤销重发新 token。防重犯:curl 带认证头诊断禁止 -v/-i(会打印请求头);token 从 .env 读不硬编码不 echo;agent prompt 处理认证/密钥时显式"不 echo token、curl 不带 -v、token 从 .env 读";泄漏后立即建议用户 revoke)
  23. 主控 prompt 期望数值错误(根因:邮件任务 prompt 期望国君 15日同向=66.7,实际 accuracy 字段值 33.3(follow_ratio),代码读对字段输出 33.3 与页面一致,reviewer 判 §22 合规非代码 bug——主控 prompt 期望值写错。防重犯:任务 prompt 里的期望数值先核实来源(字段语义/页面实际),reviewer 按真实数据判合规不盲信任务描述期望值;reviewer 发现期望值与实际不符时先查任务描述是否笔误)
  - 经验(非过错,8/10 backfill整改+备用站404+开源化+邮件阶段,记录防绕路):
    ① 定时任务超时修复的"兜底槽按槽差异化"策略(backfill CCASS e2a41b058→reviewer FAIL P1/P2→整改 9be4e8f30→复验 PASS 全闭环):02:00 兜底槽强制重算+3600s 宽限(一石二鸟:解决 P1 慢网络停更回归+ P2 坏值冻结每日自纠正),16:35/21:00 常规槽闸门跳过+600s;槽通道=BACKFILL_SLOT env 注入(backfill_metrics.sh L23)+py `_current_slot()` 读 env 按槽差异化。适用:同一脚本多 launchd 槽位要差异化行为(兜底槽 vs 常规槽),用 env 通道注入槽标识,避免所有槽一刀切;reviewer FAIL→整改→复验 流程 catch 上线前回归(§15 正常)
    ② 数据挖掘盲区发现方法论(降亏第三轮):对比数据源全部字段 vs 历轮实际挖过的字段,v3/v4 跑 19 字段版无 market_state,部署版已有(N=66,591)从未挖过→market_state×全维度=盲区=优先挖掘目标。适用:任何多轮数据挖掘前先核对字段覆盖,未覆盖字段=最大机会(同 §18 教训 8/9/13 模式"验证数据产物层再下结论")
    ③ 新 toggle/标志评估用"叠加边际"非只 standalone 比值(降亏第三轮回测验证 docs/kelly/mining/kelly-loss-round3-verify.md):A1/A2/A3 standalone 比值 4-10 但叠加现有 4 toggle 边际=0(被完全覆盖不推荐);A45 叠加边际 +107k 才推荐;现有 toggle 已砍 87.9% 亏损,新候选只在残余 12% 里再砍 ~1pp。适用:多 toggle/多标志叠加场景,新候选必须算叠加现有配置的边际贡献,不被 standalone 比值误导
    ④ 邮件期货风向字段语义修正(9ce765bef):accuracy.net_direction(静态净持仓方向)vs inst_ih_detail.details[-1](动态当日净加方向)两字段语义不同致"当日:空"矛盾,15日同向80%一致;改读动态字段+白话预警。适用:页面与邮件同数据源时先确认字段语义(静态 vs 动态/快照 vs 增量),矛盾先查字段选错非数据错
    ⑤ 开源化两仓库分工(用户纠偏定稿 0547f6733):数据开源主体(manifest+fetch_data+DB Release)放静态数据仓库 trade-data-signal-staticdata(CC BY 4.0),开发库 trade-data-signal 只代码 MIT+README「数据开源」章节引导,双向互链;DB 分发走 GitHub Release(GITHUB_TOKEN env 方案,release_db.sh 支持,gh CLI 未装改 token),manifest uploaded=true+URL 替换+下载 206 可达验证。适用:开源项目数据/代码分仓库,数据主体放数据仓库避免开发库肥大+双份
    ⑥ check_data_integrity 加"定时任务该有的数据在不在"类校验(backfill 季度闸门 check_a_fund_north_quarterly 最新季度行存在,缺失/滞后即 FAIL):C级数据任务防静默缺失。适用:任何数据产物改动新增对应完整性校验点防静默
  - token浪费(8/10):①§0 第一轮 grep 字面量误判→第二轮才确认(字面量 vs 常量,多一轮验证,同过错 20)②备用站 reviewer 卡死 22-33min+重派(不写进度文件致卡死难发现,同过错 21)③通知 reviewer API 失败重派(a959b2490de2cceb4 Prompt too long 全文读大文件终止,重派约束 git diff+定点 grep 不全文读大文件)。backfill FAIL→整改→复验 是 reviewer 系统正常 catch 非浪费(§15)
- **2026-08-11 用户新规范(README 维护:功能完成必补 README,两条)**:①做功能**若参考了文件或用了开源项目**,完成后必须在 README「🎓 参考与致敬」段扩充描述作用 + 附致敬(含跳转链接)。触发:任何实施任务(agent 或主控)引用了外部开源项目/库/文件/平台能力(如 a-stock-data/easytrader/thsautoorder/tradingagents/DeepSeek/pysubgroup/mootdx/baostock/akshare/R2/CF Workers 等)。②站点**有重大功能添加/发布/更新**,完成后必须在 README 主体段(功能亮点/系统架构/技术栈/在线体验)完善补充描述(不只参考段)。动作:功能完成后检查 README 对应段落,缺则补"该功能做了什么/用了什么/参考了什么→作用→来源链接",有则更新对齐实际用法。验收口径:实施 agent 自验含「grep README 确认本功能描述+致敬已补」,reviewer 查 README 同步,漏=验收不过(同 §21 算法公示同步模式)。README 现状:功能亮点(信号灯+降亏toggle/AI速递/自动交易等)+参考与致敬(数据挖掘方法论/多 Agent 协作 traderagent/AI 预测 DeepSeek/自动交易 easytrader→thsautoorder/公开数据源致谢 a-stock-data 等)各段已建,后续新功能按段归属补
- **2026-08-11 用户新规范(修 bug 三铁律:修完整+自测+排查同类,2026-08-11 备站多模块异常触发)**:用户原话"每一个修复bug的核心要修好修完整以及自测完成,不是只为图快和我说啥你修啥,不调研是否还有其他同类错误 。要落档规范不要再犯"。触发场景:备站(sss.sugas.site)多个功能模块同时异常(公募基金 tab 暂无数据/指数表现加载失败刷新无用/凯利回测 signal_kelly_backtest.json Failed to fetch/信号实验配对排行加载失败/诸如此类还有很多),若逐个打地鼠只修用户报的那几个=违反本规范。三铁律:①**修完整**:修一个 bug 前先全面调研同类错误面(用户报 1 个,先 grep 前端全量数据依赖+curl 多处状态码列全同类异常,不只听用户报的),根因修复不只表面症状 ②**自测完成**:修复后必须自己全面测试(用户报的模块+同根因其他模块+跨展示位 §22 一致性),自验列测试清单,不"草率说修好了" ③**排查同类**:修完自查"是否还有其他同类错误"(同文件类型/同 fallback 链路/同上传通道的其他文件,如本次 signal_kelly 未传 R2,要查所有新数据类别是否都传 R2)。验收口径:修 bug agent 自验须含「同类错误面清单(与用户报的同根因的所有模块)+逐项自测结果」,reviewer 查同类覆盖,漏=验收不过。防重犯:①修 bug 前必派调研/先列异常面清单,不直接上手修用户报的那几个 ②修复后自测清单要全覆盖(不只用户报的)③根因层面修(如备站数据通道/R2 上传链路/fallback 逻辑),不逐文件打补丁
- **2026-08-11 用户新规范(需求理解/做方案也要举一反三,修 bug 三铁律的同类延伸)**:用户原话"聪明人或模型都应该会举一反三。就想前面提到bug 让你看一下有没有相似问题 也类似是举一反三。那同样的 题的需求理解做方案时 也要有举一反三的精神"。即:不只是修 bug 要排查同类(三铁律③),**需求理解/设计/实施方案时也要主动举一反三**——用户点名做 A,方案要主动覆盖 A 的相关场景/相关位置/相关展示位(同类功能在哪也用同一模式、同一数据源/同一组件还被谁用、N 个展示位 §22 一致性),不只做用户点名的那一处。示例(2026-08-11):用户问"走势图轻量/完整切换为什么首页没效果",现状=P0 只接了 ETF 评分弹窗 1 个消费者,首页 sparkline/KPI sparkline/分时图都没接入——若做方案时举一反三,切换应覆盖所有走势图消费点;用户问"切换功能在哪",答=皮肤弹窗,但首页才是主力消费点,方案应主动列出全站所有走势图渲染点并逐个评估接入。验收口径:实施方案 agent 自验须含「同模式/同数据源/同组件还被谁用+相关展示位清单+逐项覆盖结果」,不只做用户点名处;reviewer 查举一反三覆盖,漏=验收不过。防重犯:①需求理解/方案阶段先列"同类消费点/相关展示位"清单,不全员覆盖不实施 ②只做用户点名处=违反本规范,先确认是否有同模式其他位置 ③与 §18 修bug三铁律③(排查同类)同源,一为正(修bug排查已坏同类)一为前(做方案覆盖未做同类)
- **2026-08-11 追加(每日总结,飞书机器人链路+0成本hooks+凯利组合阶段,4条新过错+经验)**:
  24. 用户核心需求方向偏差(误派 J1/J2)(根因:用户 2026-08-11 核心需求="降亏组合使用建议分析+全信号表"(评价4降亏组合全开好不好+分投资习惯细分建议+总建议+新增全信号表=全亮信号融合的最终收益预估),主控先派"1月调整组合宏(J1/J2 toggle)"实施——那是降亏增量非核心需求,消耗 1 实施 agent(a48b6bcb8)+1 reviewer(aff36db11)+3 commits(3eb6583bc+beb7ab49b+b41ccc3d6)上线,方向纠正 2 次(①识破误派 ②全信号表范围对齐)后才派 a8a8c4e6 正确方向实施,当晚仍在跑,TASKS L30 明记"已误派过 J1/J2 1月调整 toggle(那是降亏增量非核心需求,已上线)"。防重犯:接"分析/建议+新增视图"类核心需求,先列需求拆解清单(要回答什么问题+要新增什么视图+用哪份数据回测),对清单再派 agent,不把相关增量功能当核心需求实施;实施前复述需求让用户确认"这是核心需求还是相关功能"(同 §18 教训⑪需求理解/复述确认)
  25. J1/J2 §21 公示未同步复发(根因:1月调整 agent 修 tooltip(lab.js L7976-7977)减亏损盈数值为全局基准口径(J1 2.31%/0.49% J2 4.95%/1.10%),但没同步 purpose-notes.js/min.js 的公示点(仍 J1 3.58/0.76 J2 6.83/1.52 旧值),reviewer FAIL catch→b41ccc3d6 修复——同 8-10 教训18 §21算法公示gap复发的同模式复发。防重犯:数值/算法口径改动,agent prompt 必列全部公示点(purpose-notes.js+app.js/lab.js 所有算法说明),修一个数值要 grep 全站同一数值所有出现处同步改(同 §22 数据一致性铁律),不只 tooltip 实施点;§18 教训18 已列防重犯条款仍复发,说明 fresh context agent 仍不主动读,主控 prompt 每次都要显式列 grep 动作+文件名)
  26. hooks 误报"还没生效"实际已生效(根因:feishu_chat_hook.py(2d1b9206e)上线后,主控凭"还差用户确认才生效"推断,未查运行证据就说"当前 hooks 还没确认生效",实际 .claude/settings.json 已配置+去重指纹文件 /tmp/feishu_hook_sent.txt 已有 9 条运行记录,下轮查证才纠正"实际 hooks 已经在跑"。防重犯:判断"功能是否生效/上线"先查运行证据(指纹/日志文件 mtime/实际发送记录/curl 线上),不凭"配置未确认/还没生效"推断;同 §18"下结论前验证"(验证运行证据层))
  27. hooks 项目级配置把子 agent 输入也当用户输入抄送(根因:.claude/settings.json 的 UserPromptSubmit/Stop hooks 是项目级,子 agent 在同一项目目录运行同样加载,子 agent 收到的任务 prompt 被 UserPromptSubmit 当"用户输入"抄送到开发群(用户发现"子agent的输入也当成我的输入抄送"),需给 hook 加"子 agent 会话跳过"判断(主控当场判断根因正确并派修复)。防重犯:任何"处理用户输入"的 hooks/脚本(抄送/记录/转发),实现时须区分主会话 vs 子 agent(如 transcript_path/session 上下文判断),项目级 hook 对 subagent 同样生效是默认行为;上线后主动验证子 agent 场景不误触发)
  - token浪费(8/11):①误派 J1/J2 在非核心需求上(1 实施 agent+1 reviewer+3 commits,用户核心需求拖到深夜才派 a8a8c4e6 正确方向,方向偏差返工,同过错24)②主控 1min 飞书 cron+15min agent polling crons 轮询噪音占主会话上下文(用户抱怨"你倒是说不可以/轮询要等多久",后靠 listener 需求自动处理 02bd47f8f 主控零轮询缓解)③J1/J2 reviewer FAIL→fix+复验 extra round(§21 复发致,reviewer catch 正常但实施 agent 自验可减少)④hooks"还没生效"误报多一轮查证(同过错26)⑤AI 预测前端漏上线(数据层+reviewer 验本地 min PASS 但前端代码未 commit main,线上 app.min.js 0 处,用户看不到,补验+补上线一轮——已落 §8 "功能 done"三查清单,不重复记,此处记 token 面)
  - 经验(非过错,8/11 飞书机器人+0成本hooks+通知架构+凯利组合阶段,记录防绕路):
    ① 0 token 抄送方案(hooks 逐条实时抄送,commit 2d1b9206e):UserPromptSubmit→user/Stop→assistant 两个 hook 挂 .claude/settings.json,纯外部 python 脚本(scripts/feishu_chat_hook.py)读 stdin prompt/transcript_path 最后一条 assistant 文本→notify.send_feishu 发开发群;全程不经过 LLM=0 token 成本;指纹文件+flock 去重防 Stop 多次触发重复抄送;任何异常 exit 0 不阻塞 Claude Code;密钥复用 notify.py 不硬编码。适用:所有"自动记录/转发会话/消息"类需求,hooks 层实现 0 token 实时,不占主会话上下文,比 cron 轮询/子agent 转发省 token 且实时
    ② TaskCompleted hook 发现(本版 claude 2.1.224,2026-08-11 通知架构调研):后台任务完成时确定性触发 hook,可能替代 cron 兜底轮询做确定性通知(待验证实施)。适用:通知架构持续演进方向(§11 cron 兜底之外的新可能)
    ③ 通知架构调研结论(方案A 子agent 中间层不可行):子agent是工具循环,1分钟轮询=每天1440次模型回合(每步 60-400s API 物理跟不上+token爆炸),且通知主控仍走不可靠消息队列/需轮询,轮询没根治;bash 守护版/方案C 是方向,不需要子agent身份。适用:任何"用子agent做中间层轮询/转发"想法先算模型回合数成本再定
    ④ 飞书 listener 需求自动处理(commit 02bd47f8f,主控零轮询):listener 收到需求自动 落盘 data/feishu_requests/ + 进 TASKS 待办 + notify 即时回执给来源群,主控不再 1min 轮询飞书(25/25 单测+真 TASKS 插入验证)。适用:任何"外部消息→主控"链路,尽量在 listener/脚本层自动落盘+回执,主控只消费落盘文件,消除轮询噪音
    ⑤ 用户"全信号表"需求视图方法论(拆分测试 vs 最终结果):用户把降亏回测拆成 4 组合宏+独立 toggle(各象限细节调试用),但最后要"全亮信号融合"的最终结果表(正常人一定全亮信号都看)——多因子/多开关系统,用户需要"拆分调试视图(各象限细节)+结果视图(全融合最终收益)"双视图,别只做其中一种
    ⑥ 并发实验结论已在 §16④ 落档,不重复(并发非瓶颈,文件漂移/工具循环/API慢才是);TASKS 归档+完成度校验已在 §7 落档(commit bdef31aeb,曾 429KB 靠 tasks_archive.py+tasks_verify.py 周度自动校验)——此二条仅记引用不重复展开
- **2026-08-12 追加(每日总结,AI仓位历史固化调研+SVG fix4 阶段,1条新过错+用户定性)**:
  28. 主控 §0 抢跑在 reviewer 前重复验代码(根因:fix4(commit a7dffbe77)完成后,主控在派 reviewer 前亲手 grep 4 处落点+sw a150+index.html 版本号,违反 governance L16「reviewer PASS 后主控不 §0 复验代码+主控§0 与 agent 自验去重(2026-08-07 用户定)」和 L10「验收=点到即止,不亲手 grep 一堆」;fix4 自验 6+26+9 隔离测试已覆盖代码正确性,主控 §0 该只验上线点(push hash in main+curl 功能生效层)。用户问"规范没写全还是执行不到位",主控**未查原文凭印象答"规范没写全"**——实际 governance L16 白纸黑字已写清分工:规范写全了,是执行不到位;凭印象下结论=二次错误(同 L23 期望值先核实来源/下结论先查证据)。防重犯:①派 reviewer 的改动,主控 merge 前不 grep 代码(只确认 commit hash 存在),§0 一律 merge 后验上线点 ②agent 自验已 grep 的代码点,主控 §0 不重复同点 ③下结论前先 grep 规范原文(governance/CLAUDE.md),不凭印象回答"规范缺什么"。用户定性:「重复犯就一定是规范写的不严谨」→已加硬 governance L16 硬门槛+本条锚点,双保险防复发)
  29. 主控亲自 Edit 业务代码干活(根因:2026-08-12 处理首页腾落线 y 轴标注 bug 时,主控亲手 Edit static-site/app.js 的 _lwValueExtent + node --check 自测;违反 governance §2「主控只派发,不亲自干活」+「本质是项目管理,不是实施者…不亲干实施」;根因=2026-08-12 角色分上下文精简后"主控不实施"仅在 governance(按需读),compact 后上下文不注入,主控连续处理 bug 忙起来没先读 governance 就上手 Edit。用户批评:「你是主控 怎么会亲自干活?工作模式规范忘了?」+归因「看来是claude 精简后的缺点」+要求「你看看如何防止再犯」。防重犯:①根 CLAUDE.md 共享核心新增 §0.1「主控角色红线:只调度,不亲自实施」,每会话必注入(不依赖按需读 governance),触发场景=接 bug/功能想"直接 Edit 快"→停,先想"该派谁"②紧急小改也走 agent(§23.2 修bug三铁律要求 agent 修+自测)③主控只做调度+时点管理+§0 验收(验上线点)。用户定性:精简后规范位置降级(必注入→按需读)=约束力断裂,红线类规范必须留共享核心)
  30. K档每日资金池口径理解错误致误删中间档(根因:2026-08-12 用户说"1w还分30个信号买30份没意义,仓位控制1/2/3/4已足以",主控理解成"删掉整个每日资金池等分、改每笔固定1万"(commit 5d047aef2),实际用户反对的是"每日池+买全部"(当天30信号每份只分333元),要求保留"每日池+top-K"中间档(每天1万池、买K个、每笔10000/K);执行时把中间档一起误删。2026-08-13 用户报 K=1 最大持仓 11万 vs K=3 33万异常才暴露,主控承认"这是执行理解错误,责任在我这一侧"。影响面极大:fixed 口径下固化的 v2 穷举报告(406,336 配置)/AI宏默认推荐/_pcRating 硬编码/README 数值全部建立在错误口径上,需影响面审计+穷举重跑重来(commit c951dafa8/263bc9298 恢复每日池+top-K)。防重犯:①用户叫停某功能/改口径时,先复述"要删到什么粒度/保留什么档"让用户确认再实施,不把同链路可保留档一起删(本次"每日池+top-K"就是被误删的中间档)②删除/重构前 git show 原实现,列"删除清单+保留清单"逐项确认③口径类改动后自验关键展示值(K档切换最大持仓应恒定~11万),不等用户报异常)
  31. 派数据重跑/回测任务派单基准过时(根因:2026-08-13 派"每日池口径穷举重跑"researcher(a2a195a62)时,主控沿用旧审计报告"4组合全开×A/F/G×K1-4"作为主基准,未先核对当前页面 lab.js `_kellyDefaultFilters()`/`_kellyComboPresets` 真值;用户直接指出"你基准 4组合全开 × A/F/G × K1-4 这个基准是不是过时了?现在的ai降亏最优好像是4+3",主控核对后确认当前默认已是"AI宏7键 基础4+核心3"(n2NovSpecialIndustry/excludeSpecialBear/janMidRating/janMidSpecial + r7MayReinforced/excludeAuxCross/greedy15),承认"我派单时沿用了审计报告里的旧基准,这确实是我漏核对的"。已 SendMessage 在 STEP 1/6 修正正在跑的 researcher,4组合全开降为对比项。防重犯:①派数据重跑/回测任务前,先 grep 当前页面 `_kellyDefaultFilters()`/`_kellyComboPresets` 真值(默认键集/组合宏定义),不沿用旧报告基准②基准类参数写进任务 prompt 时标注"来源=当前页面 lab.js Lxxxx 核验",便于主控 §0 复核③发现基准过时立即 SendMessage 同步在跑 agent(本次 STEP 1/6 修正,未全量浪费))
  32. "A/F 收益率虚高"标注方向错误(根因:2026-08-13 每日池穷举重跑报告 §0.1 把 A/F 模式 86.6% 收益率标为"机制性虚高"(A/F 卖出快持仓10-15万分母小),主控向用户转述时沿用此标注;用户纠正:"你认为af收益率是虚高。我认为af起码有操作性 g几百倍"——A/F 持仓10-15万=10-15倍单次本金**可操作**,86% 是真实可达到的(10万本金就能跑),非虚高;G/H/I 持仓136万=136倍本金**不可操作**,需要136万本金才跑得动,那笔"净盈亏金额"才是更虚的。主控承认"我之前把'虚高'标反了"。由此引出新需求:GHI 长持模式需"持仓≤20×单次本金(≤20万)"硬性控制手段(researcher a8afcca172e35f6f6 调研回测中)。防重犯:①判断收益率/净盈亏是否有实操意义,先看**峰值持仓/单次本金倍数**(≤20倍可操作),不从模式快慢(A/F短持/G长持)预设"虚高"标签②"虚高"只用于"口径本身放大数值"(如每笔1万=虚假杠杆),不用于"高收益但可操作"③报告/转述中带"虚高/不现实"类结论前,先算峰值持仓×本金倍数)
  - 经验(非过错,8/13 每日池口径穷举重跑+影响面审计阶段,记录防绕路):
    ① K=1 每笔1万 ≡ 每日池(净利逐位相同);K>1 每笔1万 = 虚假杠杆(净利虚高≈K倍、持仓同步放大、收益率不变)——K=1 时每笔固定1万正好等于每日池1万,两种口径净利逐位相同;K>1 时每笔1万本金累计算单只"一次投入满额1万"但净利虚高≈K倍、持仓同步放大、收益率却不变,是口径放大而非真实可操作收益。适用:判断金额口径合理性/回测报告口径必须匹配用户真实交易模式(单笔本金多少=真实可投,每日池等分=分母小),先验 K=1 边界逐位相等再标"口径一致"
    ② 最优 toggle 组合依卖出模式分裂——G 模式(长持)greedy15/excludeAuxCross/r7 负贡献(去后+a45 最优 51.66%),A/F 模式(短持)greedy15 是收益率第一大增来源(去之暴跌 19-26pt)。同批 toggle 在长持/短持卖法下作用方向相反,G 长持去掉 greedy15/excludeAuxCross/r7 反增收益,短持却靠 greedy15 抬大收益。适用:多 toggle 系统最优组合结论须分卖出模式给,不一套配置打天下,报告/默认配置按 G vs A/F 拆分呈现避免误导
    ③ 口径/基准切换先派影响面审计(会反转/数值变化/自愈三类分类),并行修根因再全面修正受影响功能。本次 fixed→每日池审计出 2 项高风险反转(默认推荐/默认K档)——口径切换(如 fixed→每日池)会连带默认推荐/默认 K 档/fixed 期固化的穷举报告全部受影响,分"会反转/数值变化/自愈"三类逐项评估再修根因,不同步会导致多数展示位继续按旧口径出数(同 §22 一致性)。适用:任何资金口径/默认基准切换前,先列受影响功能清单分类审计,并行修根因
    ④ 发现派单基准过时立即 SendMessage 同步在跑 agent(本次 STEP 1/6 修正避免全量重跑)。派数据重跑/回测任务后,若核对当前页面真值发现派单基准已过时,第一时间 SendMessage 同步在跑 agent 修正(STEP 1/6 早段修正未全量浪费),不留到跑完返工。适用:派数据重跑/回测任务后才发现基准或口径过时,立即同步在跑 agent 纠正,越早越好(配合 E31 派单前先核真值,防重于治)

---

## 防重犯锚点索引(2026-08-12 建立,根 CLAUDE.md §18 索引表反向追原文用)

> 用法:命中场景 → 读根 CLAUDE.md §18 索引表 → grep 锚点 id → 读本文件对应行号原文(含根因+场景+防重犯)。
> 零丢失校验锚:`grep -c '^L[0-9]' docs/archive/CLAUDE-errors-2026-08.md` 应 == 根 CLAUDE.md §18 过错索引表行数(39),一致=零丢失。
> 注意:本文件行号会随未来编辑漂移,追到后若行号对不上按锚点 id 关键词 grep 定位。

### 过错锚点(39 条,与根索引表 #1-39 一一对应)

L01 | 通知丢失不设cron傻等 → 防重犯:§11 cron兜底必设 | archive:L13
L02 | DB方案理解反复3次 → 关键决策前复述确认 | archive:L14
L03 | exclude偏离全量本意 → 全量不擅自exclude先确认 | archive:L15
L04 | .gz凭memory断定 → 断定前验证 | archive:L16
L05 | trade/trade-data混淆 → agent关键结论§0验(路径/文件数类) | archive:L17
L06 | cherry-pick撞冲突 → 切分支前CronList+查后台agent | archive:L18
L07 | hoverpop方案试错 → 方案先调研再实施 | archive:L19
L08 | ETF拆档null归属 → 归属/分类前复述口径确认 | archive:L22
L09 | hoverpop"无数据"误判 → 下结论前验数据产物层(R2旧vs新版) | archive:L23
L10 | lowconf灰蓝过时规则 → 改灯体系遍历所有return/分支 | archive:L24
L11 | 需求2加未要求改动 → 不擅自扩展需求(→§23.3) | archive:L25
L12 | 至今盈亏方向偏差 → 调研先对准UI位置(grep渲染层) | archive:L26
L13 | 量子"0/不可改善"误判 → 换方法/数据源+多关联维度 | archive:L27
L14 | annualized口径判断偏差 → 指定口径前验算典型值合理性 | archive:L49
L15 | 追加A级小改漏做 → 追加任务不靠SendMessage(→§11) | archive:L50
L16 | 数据没上线R2 → 新类别上线链路三步(→§22) | archive:L51
L17 | §0证伪查错文件 → §0证伪前grep前端渲染逻辑确认读哪个文件(→§8三查) | archive:L52
L18 | §21算法公示gap复发(已复发2次) → §21强化款:prompt显式列grep动作+文件名 | archive:L60
L19 | 前端重算不对齐后端 → replay逐字段对比后端JSON(→memory frontend-replay-align-backend) | archive:L61
L20 | §0 grep字面量漏常量 → memory verify-grep-constant-not-literal | archive:L65
L21 | reviewer卡死无进度文件 → prompt显式"每步echo进度文件"(→§11) | archive:L66
L22 | curl -sv泄漏token → memory curl-v-leaks-auth-token | archive:L67
L23 | prompt期望数值错误 → 期望值先核实来源 | archive:L68
L24 | 核心需求方向偏差(误派J1/J2) → 需求拆解清单+复述确认(→§23.3) | archive:L81
L25 | J1/J2 §21公示复发(已复发2次) → §21强化款 | archive:L82
L26 | hooks误报"还没生效" → 判断生效先查运行证据 | archive:L83
L27 | hooks子agent输入也抄送 → hooks区分主会话vs子agent | archive:L84
L28 | 主控§0抢跑在reviewer前重复验代码 → 派reviewer的改动merge前不grep代码(只验hash),§0只验上线点,下结论先查规范原文 | archive:L94
L29 | 主控亲自Edit干活违反"只派发" → 主控永不亲自改代码/写代码/跑自测,实施一律派implementer(→根CLAUDE.md §0.1红线) | archive:L95
L30 | 需求叫停时过度删除同链路中间档 → 复述"删到什么粒度/保留什么档"确认再删,不把可保留档一起删 | archive:L96
L31 | 派数据重跑/回测任务基准过时 → 派单前先核对当前页面 `_kellyDefaultFilters()`/`_kellyComboPresets` 真值,不沿用旧报告基准 | archive:L97
L32 | "A/F收益率虚高"标注方向错误 → 判断实操意义先看峰值持仓/单次本金倍数(≤20倍可操作),不从模式快慢预设"虚高"标签 | archive:L98
L33 | 子agent设"等定时器自唤醒"不可靠(会话停REPL没了定时器永不触发) → 带时点动作(merge/上线避盘后)主控侧设一次性CronCreate兜底,或收到"在等定时器"报告立即改为命令立即执行;主控兜底设在自己会话不指望子agent | archive:L103
L34 | 报告索引有但报告本体未提交/配套脚本缺指向(用户:"提交记录里看到了次日的报告索引 怎么没看到报告本体?") → 报告落档必走 §23.5 四件套:报告本体+生成脚本+##复现段+配套commit;commit 前 `git ls-files` 验本体/脚本已 tracked,缺=验收不过 | archive:L104
L35 | Explore agent v4-pro 计费泄漏:派只读/搜索任务误用 Claude Code 内置 Explore subagent(model=claude-opus-5 不在代理白名单,绕过白名单按 v4-pro 计费,12次~45万tokens泄漏) → 只读/搜索/定位任务一律派 researcher(内置 Explore 固定用 claude-opus-5 绕过代理白名单);白名单外 model 一律兜底改写 flash,绝不透传 | archive:L105
L36 | 汇报并行在跑 agent 数错误(把已完成/已收到通知的还当在跑,用户:"顺带提醒 并行在跑的可没4个"+"这种错不要再犯了") → 汇报"在跑N个"前逐 agent 核对是否已收完成通知;收到通知=已完成立即移出在跑 | archive:L106
L37 | 非交易日补发买卖点信号邮件(周日没开盘却收到周五买卖点信号) → 信号邮件/backfill 补发前判断交易日,非交易日不补发 | archive:L107
L38 | daily-brief 周六触发降级(周六20:40收到AI预测且是老版本) → 触发源脚本(run_daily_brief.sh)必带交易日判断,非交易日不触发;降级=模型不守约束加强prompt不放松校验,补原始range日志 | archive:L108
L39 | 挖掘用裸G不可操作口径当基准(2.0挖掘第一轮用裸G测「剔除整象限G -74,954」,用户质疑后核实确是不可操作口径,结论需重测) → 回测/挖掘第一件事=确认基线落在 v1.1.0 基准(§5.4),测非基准口径(裸G/其他K/P档)必须显式声明+说明为何测+标注口径差异,不作主推结论 | archive:L109
L40 | 打 tag 只做点名处没举一反三(用户让打 v1.1.1 tag,我打了 v1.1.1 就报完成,但 v1.1.0 从没打过 git tag——首次 `git tag -l` 已看到只有 v1.0.0,却把"v1.1.0 漏打"当顺手小事默默补打,没暴露给用户;用户追问"怎么会1.1.0都没打"才发现这是历史疏漏) → ①「打 tag/发版本」需求第一件事 `git tag -l` 全量核对版本链(v1.0.0→v1.1.0→v1.1.1 三连齐不齐),缺哪个=先报用户确认再补,不默默自己消化;②发版本验收口径=git tag 必须在(页面版本串 a2xx/memory/README 是辅助标记,不替代 git tag,漏没漏要单独验),git tag 必须 push 远端;③发现历史疏漏=上报用户(§23.7⑤同精神),不自己拍板位置;④「打 vN tag」隐含前提=版本链完整,做 A 要举一反三覆盖版本链全貌(§23.3) | archive:L110

### 经验锚点(30 条,非过错,适用场景;对应根索引表经验 1-30)

E01 | R2 purge_cache分批避超时500(每批30+batch sleep) | archive:L55
E02 | 持仓hold_days改交易日口径 | archive:L56
E03 | check_data_integrity+check_r2_consistency | archive:L57
E04 | 凯利卡间比较水印(蓝★+紫◆全局互比) | archive:L58
E05 | GitHub Actions deploy约90s,curl验上线sleep 90 | archive:L62
E06 | Edit含em dash行失败用sed行号替换 | archive:L62
E07 | reviewer FAIL后§0验2点合规(§0允许FAIL时亲自确认) | archive:L62
E08 | intraday走R2后盘中push代码不避intraday | archive:L62
E09 | 分时1min轮询自愈(S1-S5+S9) | archive:L62
E10 | 决策树/子群数据挖掘方法论 | archive:L62
E11 | 兜底槽按槽差异化(BACKFILL_SLOT env通道) | archive:L70
E12 | 数据挖掘盲区发现方法论(字段覆盖) | archive:L71
E13 | 新toggle评估用"叠加边际" | archive:L72
E14 | 邮件期货风向字段语义修正(静态vs动态) | archive:L73
E15 | 开源化两仓库分工(数据主体放staticdata仓) | archive:L74
E16 | check_data_integrity"该有的数据在不在"校验 | archive:L75
E17 | 0 token抄送方案(hooks,2d1b9206e) | archive:L87
E18 | TaskCompleted hook发现(2.1.224) | archive:L88
E19 | 通知架构方案A子agent中间层不可行 | archive:L89
E20 | 飞书listener需求自动处理(02bd47f8f) | archive:L90
E21 | "全信号表"双视图方法论 | archive:L91
E22 | 并发实验/TASKS归档仅记引用(已落§16④/§7) | archive:L92
E23 | K=1每笔1万≡每日池;K>1每笔1万=虚假杠杆(净利虚高≈K倍,持仓同步放大) | archive:L99
E24 | 最优toggle组合依卖出模式分裂(G去greedy15/excludeAuxCross/r7+a45最优;A/F维持AI宏7) | archive:L100
E25 | 口径/基准切换先派影响面审计(会反转/数值变化/自愈三类),并行修根因再全面修正 | archive:L101
E26 | 发现派单基准过时立即SendMessage同步在跑agent(本次STEP 1/6修正避免全量重跑) | archive:L102
E27 | v1.1.0 版本发布机制:动 AI 推荐/降亏过滤核心功能必须发中间版本(1.0.0→1.1.0),7键→9键全站对齐审计(后端判定/前端默认/lab/公示四处置0过时) | archive:L110
E28 | 免费异源自动切换多重兜底(6组+qvix3重):数据源单源项→寻免费异源组合逐源实测,任一源必须有其他源兜底,fallback不走同源 | archive:L111
E29 | token优化6条0成本行为层(§5.5):输出简洁/命令静默/派单只回结论/@文件直引/小任务不spawn/失败方向用rewind | archive:L112
E30 | 优化/修复落地后定期巡检机制(每天18:05 cron,6项指标+判定标准+严重止损回滚小问题迭代) | archive:L113
