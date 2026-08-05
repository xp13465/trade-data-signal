# TASKS.md - 情绪看板迭代任务清单（监管 + loop 工作模式）

> 这是「监管 + loop」工作模式的唯一共享任务文件。子进程开工前**必读本文件** + `REQUIREMENTS.md`（需求真实来源）+ `NOTES.md`（调研笔记）。监管（主进程）不直接干活，派子进程领任务循环。

> **历史已完成项（2026-07-06 ~ 2026-07-20 晚续3 的交接状态、22 任务全 done 的任务清单/进度看板、综合AI风险预警 P1/P2/P4 全闭环）已归档到 [docs/archive/TASKS-done.md](docs/archive/TASKS-done.md)。本文件只保留头部 + 晚续4 + 工作约定 + R2待办 + 全站性能待办。**

## 📍 当前会话状态（compact 恢复用,每次状态变化后 Edit 更新）

> compact 后第一动作:读本小节恢复 transient 状态(活跃 agent/cron/commit 链/正在等什么)。详见 memory `compact-recovery-checklist`。

**最后更新**:2026-08-04(stage0全量采集跑完✅4表灌满rc=0 + OAuth state改造+登录退出UI+4功能gating+fetch错误修复,详见NOTES§48小节AA):前次2026-08-02(本次会话compact后续8项全闭环上线✅ ui87-ui94连升+落档NOTES §48 AZ113-AZ120,详见下方2026-08-02小节:①ui87补修2处英文残留+help数据源中文化 commit 1066489c ②ui88行业配置❓弹窗数据口径补申万一级三套口径 commit 84d3a153 ③ui89 88魔咒图lg/cninfo缩写中文化(乐咕乐股/巨潮资讯) commit c072f933 ④ui90全站英文残留38条全面中文化(信号/lab/数据源/技术指标统一) commit 35a94d1e ⑤ui91公募基金5项修复(88魔咒补今日预估字段+抱团重叠度delta_vs_last+副标题截断+note中文化+4卡片弹窗) commit baaac2e2 ⑥ui92 ETF评分重构为基金评分(场内ETF/场外基金二级tab) commit a1c8315f ⑦ui93 88魔咒图红绿标记说明优化(去📌emoji+色块示意+pin加88高/80低label标注) commit 7f32faf7 ⑧ui94 overlap/HHI delta可比口径优化(采集完成度闸门+同披露类型对比,根因20260630中报采集未完成非披露范围差异) commit 13705c70;1待验证:8/3周一收盘后预估仓位每日自动更新闭环首次自动跑;1待排期:公募基金筛选器大工程[需先补fund_basic字段规模/经理/业绩]):前次2026-08-03(本次会话10项全闭环✅+8/3收盘后验证预估仓位首次自动跑待验证,详见下方2026-08-03小节:①ui81行业配置口径切换+❓介绍已上线 commit 1d11bf14 ②ui82 88魔咒pin/tooltip融合已上线 commit 1f769deb ③预估仓位方案A push feat未merge main commit ddf613ea初版+d4c08e93修复 ④申万一级口径调研验收完成+实施已上线 ⑤ui84 88魔咒图加今日预估点位已上线 commit bd19a81b ⑥预估仓位每日自动更新闭环 push feat commit 96807ff1待8/3收盘后验证 ⑦ui85 行业配置柱状图tooltip移动端超屏修复已上线 commit 1d91a9e7;1待验证:8/3收盘后16:30 daily.sh pipeline_daily采8/3净值+三指数+export重算position_estimate current.date 7/31->8/3即闭环):前次2026-08-03(公募基金4块工作落档NOTES/TASKS,详见下方2026-08-03小节:①ui81行业配置口径切换+❓介绍已上线 commit 1d11bf14 ②ui82 88魔咒pin/tooltip融合已上线 commit 1f769deb ③预估仓位方案A push feat未merge main commit ddf613ea初版+d4c08e93修复 ④申万一级口径调研验收完成+实施中 agent ab7b0002af598d5c7;3待办:申万一级实施验收+预估点位前端接入88魔咒图[等申万完成避撞app.js]+预估仓位每日自动更新闭环pipeline_daily[等申万完成避撞public_fund.py]):前次2026-07-31 21:30(compact 后续7项闭环✅+分支清理✅+stash待处理):④purpose note下沉`f30e7dd7` sw ui14->ui15[renderSentimentMarketTemp内嵌purpose note/crosslink,修3二级tab显示不匹配]⑤loading bug修复`62ba76d9` ui15->ui16[renderSentimentMarketTemp漏container.innerHTML=''清loading,对齐renderGlobal L9119+try/catch+renderErrorState]⑥high_alert中文化`4c324eeb` ui16->ui17[_INDEX_NAME_MAP补high_alert:'高位预警']⑦采集异常手动修复+自动修复机制`e35b7e06`+`47f1ec91`[7/31跌停池空=大盘反弹日真0,DB a_width_dt_count=0+collect_log ok;collect_snapshot交叉验证+retry_failed_metrics.py+self_heal.sh L29-31集成retry]⑧弹窗次日才弹`49dc0a75` ui17->ui18[initOnboarding改last_visit_date+welcome_shown_date双标记,首次ever不弹/当日重复不弹/次日才弹]⑨通知click跳转修复`158d5c12` ui18->ui19[OPEN_POST_CLOSE错调openNtDayModal改flash(.sig-card)与OPEN_SIGNAL_DETAIL一致,修source/min不一致]3域名ui15-ui19上线;分支清理✅19本地+17远程已删[保留当前feat/iframe-theme-follow/未发布feat-p1-us-futures+feat-p2-hk-board/worktree feat/atrx4-backtest/main+4未发布远程];stash待处理:stash@{0}data-before-rebase2(通知click agent rebase前stash的static-site/data/*.json数据,大概率过时可drop)+stash@{1}wip-other-agent-staged-changes(high_alert agent stash的pre-existing:08买卖点策略回测.md 340行+notifications.json,待确认apply/drop);前次2026-07-31晚3项前端UI闭环✅+明日公募基金实施计划:①P1+P2全球指数前端角标配套`1e9d5d43`+后端`bccef338` sw ui11->ui12[addGlobalRealtimeBadge读intraday_snapshot.global_realtime展示price/chg_pct/time+A股红涨绿跌配色+数据缺失兜底+欧洲时点不过滤]②IA重构`8f7d124d` sw ui12->ui13[market瘦身移除futures/national-team只留a-stock/hk/global+sentiment加二级subtab机制_MARKET_SUBTABS/_SENTIMENT_SUBTABS+renderSentiment改分发器默认market-temp=原sentiment移除末尾期货section+renderFutures/renderNationalTeam移sentiment二级+hash路由sentiment/{subtab}+overview汪汪队右列卡片保留]③grid min-width 600->650`dce3eae8` sw ui13->ui14[.indices-grid/.industry-grid minmax(650px,1fr),astock 700不动,顺带修industry注释]3域名ui12/ui13/ui14上线;明日2026-08-01白天公募基金实施[周末不开盘,主链路5汇总接口+头部1000只明细,补充链路9000只凌晨解耦跑,sentiment二级tab加「公募基金持仓」,工时~4天,详见下方明日计划];前次2026-07-31 05:00:deploy=128事故修复闭环✅:deploy.sh A+B双保险`3c740dde`+git main恢复`d6c54ffd`+atr pin根治`a761278e`05:00验证生效[signals=49905 RECOMPUTE_RC=0]+stash清理2条drop,详见2026-07-31 05:00行;前次2026-07-29 晚续4:续23修复renderIntradaySection顺序bug致intraday1min刷新失效✅[历史遗留_intradayRenderCtx被_stop清空,交换L5049-5050顺序先start后设ctx,sw a65]全闭环上线,见续23行;续22:分时图1min刷新同步底部涨跌幅+角标✅[spark-foot/preClose同维度+角标用腾讯1min时间+cache-busting sw a64]全闭环上线,见续22行;续21:T+1治理全套✅[采集侧盘中直采7品种+前端_T0_EXTRAS/_KPI_T1_MOVED+颜色bug]+intraday 11:32/15:02收尾时点✅+Win通知试看逻辑✅[方案A开启弹欢迎+方案B试看按钮 sw a63]+3域名部署验证✅全闭环上线,见续21行;续20:usdcnh 7-27验证✅+bump_asset_version日期根治✅+update_lab.sh加simulate_trade --html✅+监控异常深查3类根因✅+P2-新-W PC浏览器通知方案A✅全闭环上线,见续20行;续19:app.js 3处修复[t0兜底拆分+关键时点1m+小卡角标重绘]+回退1b✓上线;续18:全站时序优化6项上线+QVIX时点精确化+告警根因修复✓上线;续17:本轮4项修复chip方案D+ETF hover+板块分化按钮+过拟合警示文案✓上线;续16:ETF补采治本+回测切窗口bug修复+trade_sim HTML5窗口+撤销方案F✓上线;续15:回测精准模拟+滞后提示修复+ETF同类去重3项✓上线;续14 4项:P0-1 KPI预估点+debug CSS皮肤+封板率derived根因+分时图1min);前次2026-08-04晚(留言箱+通知试看+历史收盘):①留言箱用户侧 commit b53a312e7 sw v2-20260804-feedback-box(登录后留言+头像菜单💬入口+我的留言列表,GET/POST /api/feedback session认证 KV feedback:<provider>:<uid>:<ts> 复用SUBSCRIBE_KV) ②留言箱管理端+防滥用 commit 4b384b473 sw v2-20260804-feedback-admin(admin/feedback.html审核页+频控10min≤1+honeypot website+50-2000字+审核闸门pending+FEEDBACK_ADMIN_PASSWORD secret X-Admin-Pwd认证,临时密码feedback_admin_2026用户后续改) ③通知试看移铃铛hover popup commit 79bd77dd8 sw v2-20260804-notify-hover-pop(删testBtn独立按钮+.notify-pop popup+mouseenter/mouseleave+_doTestNotify触发原逻辑,省header空间,移动端@media隐藏) ④历史收盘分析下一页没数据bug修复 commit d2b77308b 增量追加模式(agent a7e5064e3dc823f76):根因total=2562(DB全量)但items只90条(queries.summary_history回算每天~12SQL<1s全量2562天3-6min太慢),修total=items.length+增量追加(读已有JSON+重算最近7天+历史保留累计增长,export 0.6s,365天起点first=20260804 last=20250206,明天起每天+1不丢历史,不回填2562天) cron 4af752c2 23:33 deploy(避开22:57资金面8fc98382+23:40验证68c51a59+导航吸顶agent,上线后删cron);⑤导航吸顶移头像菜单 commit fa7bdfa9d sw v2-20260804-nav-sticky-avatar(删header L99独立按钮+头像菜单加📌导航吸顶(开/关)项 L17361+复用nav-no-sticky toggle L17667+applyNavStickyState文案同步 L15511,登录用户可见,移动端也能切,未登录默认吸顶开);⑥留言箱TASKS L1124状态已更新(用户侧+管理端+防滥用已上线,AZ122完整方案剩余管理端已补);每日AI预测调研完成 agent aed69ea414f3c6578(1036行报告 docs/daily-brief-research.md):Claude API生成专业分析(券商晨报语气有观点+预判+风险点)+段落级gating(对外合规版【今日复盘】+【趋势研判】客观/登录detailed_view完整版【明日关注】+【风险点】+【AI预测】具体标的+方向判断,复用compliance_mode+hasPrivilege同fund_score/trade_sim模式)+daily JSON归档(public/private字段历史回看)+盘后update_all跑+首页收盘小结卡片展示;方案B前端gating(推荐第一阶段)+方案A后端gating(+2h);工作量23-30h;用户选Claude API(需ANTHROPIC_API_KEY secret)+周末集中做,待周末实施(需用户设secret);今晚cron 22:57资金面修复8fc98382+23:40验证68c51a59+明晚23:03跌停池根治f9131056

**2026-08-02 续9(阶段0场外基金后端补全✅commit 08c514f1 + 4件实施ui96✅commit 1c0a5502 + 88时效ui95✅commit 229686b3)**:本次落档NOTES §48 AZ121。阶段0后端:fund_basic 6->21列(扩15列)+6新表(manager/performance/risk_indicator/rating/purchase_status/fee_detail)+7fetcher+CLI 6命令(stage0-daily 22s/overview 6.2h/risk 4.5h/manager 3h/nav 5年/sample)+小样本3只验证通过+调度接入update_all.sh L129-141(失败不阻塞)+export_offshore_fund.py导出7 JSON+upload_r2.py加upload-offshore-fund命令(§8.1新类别按前缀)+exclude防双副本+全量27409只挂凌晨launchd。4件实施ui96(前序commit 1c0a5502):仓位红线3m/6m断线修复(app.js L9905-9908 estHistory按_pfCutoff过滤)+ETF评分弹窗5区块(后端补导出7字段+前端openEtfScoreDetailModal L13574)+卖出明确化(_sell_action_for_high L207减仓比例%)+抱团/重叠度弹窗区分(_pfDetailModal grayFirstN L9784)+history_analogy bug修复(alert_reason.py L213 3值解包)。88时效ui95(前序commit 229686b3):app.js L10049-10053 5行时效标注。

#### 阶段0场外基金数据采集补全 - 已完成 (2026-08-02, commit 08c514f1)
- schema: fund_basic 21列(扩15列)+6新表(manager/performance/risk_indicator/rating/purchase_status/fee_detail)
- 7fetcher + CLI 6命令(stage0-daily/overview/risk/manager/nav/sample)
- 小样本3只验证通过 + 调度接入update_all.sh L129-141(失败不阻塞)
- R2: upload-offshore-fund命令 + exclude防双副本
- 全量采集(27409只)挂凌晨launchd自动跑

#### 4件前端+后端实施 - 已完成 上线ui96 (commit 1c0a5502)
- 仓位红线3m/6m断线修复 / ETF评分弹窗5区块 / 卖出明确化(减仓比例%) / 抱团-重叠度弹窗区分
- history_analogy bug修复(alert_reason.py L213 3值解包)

#### 88魔咒每行时效标注 - 已完成 上线ui95 (commit 229686b3)
- app.js L10049-10053 5行时效标注

#### 待办
- 阶段1评分引擎：C调研综合分公式(6维度加权)+风险调整5指标+经理稳健度6维+半凯利仓位
- 阶段2前端UI：场外基金tab
- 阶段3场内外联动：ETF联接跟踪误差
- 🆕 **管理端任务看板**(2026-07-20用户设想,待实施大功能):4列(🆕新需求用户输入/📋待办我整理/🔄进行中/✅归档按功能聚合)。数据模型 Card(id/title/desc/status new|todo|doing|archive/type/priority/feature_id/session_ids[]/commits[])+Feature(id/name/card_ids[]/session_ids[]/commits[]归档功能聚合)。流程:用户管理端输入新需求->我每次会话开工扫描new整理todo->开发doing记录session+commit->完成创建Feature关联cards归档。归档列展示Feature(非单卡)点击展开历史需求+会话+commit。技术:worker /api/kanban/cards+/api/kanban/features CRUD + KV kanban:card:<id>/kanban:feature:<id>/kanban:index(复用SUBSCRIBE_KV) + admin/kanban.html(4列+卡片弹窗编辑+Feature展开)。权限is_admin。详见 memory `kanban-board-design`。排期:周末或下周(关联每日AI预测周末实施一起排期)
- ✅ 全量采集挂凌晨launchd自动跑(2026-08-02 完成,27409只 4任务)
  - **2026-08-04 凌晨实际全量跑完✅rc=0**:risk P 27418只 ok=19783 fail=7224 rows=152720 elapsed 9.7h 00:17:52 rc=0;manager M2 27116只 ok=27116 fail=0 total=27116 elapsed 5h 05:16:18 rc=0;4表最终 basic 27418/nav 21410936/risk 61458/manager 35438。AZ121 真正闭环(不只挂调度,实际全量跑完4表灌满)。详见 NOTES §48 小节AA。
  - pf-stage0-overview: 周日02:17 stage0-overview(~6.2h补fund_basic 15新列) scripts/stage0_overview.sh
  - pf-stage0-nav: 周五01:43 stage0-nav --days 1825(5年净值断点续采) scripts/stage0_nav.sh
  - pf-stage0-risk: 每月15日02:33 stage0-risk(~4.5h,脚本判断1/4/7/10月才跑) scripts/stage0_risk.sh
  - pf-stage0-manager: 每月1日02:47 stage0-manager(~3h补经理任职历史) scripts/stage0_manager.sh
  - 4脚本fcntl互斥锁+caffeinate防休眠+双层锁(shell fcntl+python _acquire_lock),4 plist已launchctl load

**2026-08-03 公募基金7块工作(ui81-ui85已上线+预估仓位每日闭环待8/3收盘后验证)**:本次会话7块工作落档 NOTES §48 AZ106-AZ112(前4块 AZ106-AZ109 上一段落档,本次补 AZ110-AZ112 最后3块):
1. **ui81 行业配置口径切换+❓介绍**(`1d11bf14` 已上线):用户疑问"制造业占比57%为什么这么大/制造业算行业吗/制造业里有通信外面也有通信服务"。解惑:fund_industry_alloc.industry_name 是多套口径混合(证监会CSRC门类+GICS大类)非股票申万一级;制造业是证监会门类(19大门类之一)非行业占比大是口径粗;"通信"(制造业子项通信设备制造)vs"通信服务"(GICS独立大类通信运营)不同东西。实施纯前端app.js:IND_CLASSIFICATION映射(16 CSRC+8 GICS+3 both)+三档切换(全部/证监会/GICS)+❓弹窗(pfIndHelpBtn双口径来源+制造业占比大原因+通信vs通信服务区别)。terser mangle常量名,线上验证用字符串字面量pfIndHelpBtn/data-ind-class非源码名。详见NOTES §48 AZ106。
2. **ui82 88魔咒图pin+tooltip融合**(`1f769deb` 已上线):问题pin用emphasis label黑底浮窗,图表用tooltip axis cross白底,两套割裂。融合方案A:tooltip trigger:axis formatter统一处理,建_pinDateMap(YYYYMMDD->pin信息),formatter查命中追加pin完整说明(类型desc+仓位+沪深300+后30/60/90天涨跌带涨红跌绿),未命中显示普通点(日期+仓位+沪深300);pin label简化为精简标识(日期+高96%/低82%)去emphasis黑底浮窗;保留十字线axisPointer type:cross;一个统一浮窗一套样式不再割裂。详见NOTES §48 AZ107。
3. **预估仓位方案A**(`ddf613ea`初版+`d4c08e93`修复,已push feat未merge main):88魔咒图加"今日预估仓位"点不用等lg周频更新。数据源fund_value_estimation_em(盘中实时估算)+fund_open_fund_info_em回填200只偏股基金400日历史净值+baostock sh.000300沪深300日频(东财被封弃用)。反推算法R_nav=w_stock×R_stock+w_bond×R_bond+R_cash忽略债券现金,OLS回归R_nav_median~R_index斜率=w_stock×beta,lg校准消beta系统性偏差。初版bug1:vs_lg 17期estimate全93.29重复[根因L2015 abs(int(d)-int(lg_date))<=700用YYYYMMDD整数差注释说7天但跨月达3月,slopes只21期早期lg全匹配7/3的101.04];bug2:current.position_estimate=100% clamp自100.35%[根因nav只90日overlap只4期校准4期均值offset=7.75不稳]。修复d4c08e93:nav回填90->400日(slopes 21->147期overlap 4->31期)+matching用datetime真实日历日差<=7+校准用全overlap中位数+窗口60->120日+固定200只面板(subquery非JOIN全市场consistent universe)。算法演进教训:多因子sum(slopes)不可用[三指数高度相关多重共线性Σβ无约束82-100跳变];综合基准(hs300+csi500+gem)/3差[csi500/gem波动大β_composite不稳78-92];hs300单因子最稳[β_hs300 106-115 7%波幅lg校准效果最好]。额外修export_json_files latent bug(conn在finally关闭后_compute_position_estimate用closed conn移入try块)。结果current 95.01(dev=-1.0 vs lg 96.01),vs_lg 17/20 within±5%,3 outliers(6/26-7/10 diff -6.3~-6.6)是7月市场波动β压缩效应2周自愈(7/17:-2.95,7/24:-3.25,7/31:-1.0)时变β固有限制非校准问题。架构独立计算模式(不走export_data() 7元组遵循commit 190c8f7e教训),queries.py薄包装public_fund_position_estimate()调_compute_position_estimate(conn),JSON产物public_fund_position_estimate.json(current+history 147期+vs_lg 20期)。详见NOTES §48 AZ108。
4. **申万一级口径调研(验收完成)+实施(已上线)**:用户认知"反查很麻烦但非公开信息更有价值"(公开数据+重构口径/反向推算=非公开洞察,信息差是alpha来源)。调研验收数据:fund_portfolio_hold 1期(20260630)/937基金/9337行/每基金~10条重仓股/平均集中度42.37%(范围0.19-93.64%);sw_components.json 31个申万一级行业/5210成分股/重仓股反查命中率94.6%(未命中69只港股代码)。3个硬限制:①时序不可用[fund_portfolio_hold只1期做不了历史对比]②采集偏制造业[collect_portfolio_hold L1220硬编码WHERE industry_name='制造业',937只里935只制造业基金非制造业主题基金重仓股没采]③仓位覆盖率42%[top10重仓股平均占净值42.37%只反映42%仓位行业暴露]。实施(已上线):去制造业硬编码采全市场+_compute_sw_industry_alloc()全市场重仓股反查31行业+第四档sw切换(fetch新JSON换数据源)+诚实标注3硬限制(副标题+❓弹窗强调反查价值:揭示真实风格暴露vs官方口径)+制造业breakdown在sw档禁用+bump sw ui83。详见NOTES §48 AZ109。
5. **ui84 88魔咒图加今日预估点位**(`bd19a81b` 已上线,承接 AZ108 预估仓位方案A 接入前端):方案C预估线+末端markPoint双重标注。renderPublicFund fetch加第6个public_fund_position_estimate.json(L9518 Promise.all解构estimate)+主图标题加副标注"今日预估95.01%(日频OLS,vs lg 96.01%偏差-1.0%)"橙色span(L9780)+estPoints/estMap/_estCurDate+allDates并入预估日期延伸到20260731(L9812-9817)+tooltip formatter扩展预估series加%单位+末端点追加"📌今日预估X%(日频OLS confidence=high)+vs lg周频96.01%(20260724)·偏差-1.0%"(L9866-9872)+legend加"今日预估仓位%"(L9885)+series加第3条橙#ff9800虚线width2 symbol none+末端markPoint(pin48 label+副标注)(L9909-9933)。视觉区分:lg线红#e6492e实线symbol circle(不变)vs预估线橙#ff9800虚线symbol none,重叠期可视觉对比日频细密vs周频稀疏,预估延伸到7/31体现时效差。关键发现:任务约束"push feat触发CF deploy"是误判,实际.github/workflows/deploy-cf.yml触发条件branches:[main]feat不触发,按§8补git push origin feat:main fast-forward触发CF deploy。详见NOTES §48 AZ110。
6. **预估仓位每日自动更新闭环**(`96807ff1` 已push feat,待8/3收盘后验证):根因(agent调研)4条:①pipeline_daily不调fetch_index_daily是核心根因(docstring写"较重"过时实际baostock三指数~5s不重,收盘后fund_index_daily停旧日期_compute_position_estimate缺当日r_hs300跳过JSON停旧交易日)②没有盘中launchd采fund_value_estimation_em(fetch_estimation docstring设计了10:00/11:00/13:30/14:30四档但从未实现launchd,fund_estimation_nav表0行)③8/1非交易日是sina源正确返回(trade_dates.txt含8/3不含8/1)非bug,7/31是最后交易日JSON停7/31正确④双路径同步已OK(deploy.sh L184-186 rsync trade-data->trade内置,position_estimate在git add列表L296)。改动:app/collector/public_fund.py pipeline_daily()加fetch_index_daily(三指数hs300/csi500/gem)L1693-1696+main()加fetch-estimation CLI命令L3108(盘中实时估算不持锁轻量~5s)+scripts/public_fund_daily.sh注释更新(~8s->~15s)+scripts/public_fund_estimation.sh(新盘中采集脚本只调fetch-estimation不跑export/deploy避撞intraday-snapshot)+~/Library/LaunchAgents/com.trade.public-fund-estimation.plist(新不进git10:00/11:00/13:30/14:30四档已launchctl load成功plutil -lint OK)。8/3周一收盘后预期闭环:16:30 daily.sh pipeline_daily采8/3净值+fetch_index_daily采8/3三指数+export重算position_estimate(current.date=2026-08-03)+deploy.sh rsync+git push上线;10:00/11:00/13:30/14:30 estimation.sh盘中采fund_value_estimation_em入fund_estimation_nav表。验收:pipeline_daily调用链完整(fetch_daily_nav+fetch_estimation+fetch_index_daily三指数+position_change_estimate)+export_json_files调_compute_position_estimate(L2883)+main()fetch-estimation命令分支(L3108)+fetch-estimation实测(周日force)akshare返回空正常处理exit=0+launchd plist加载+语法OK。详见NOTES §48 AZ111。
7. **ui85 行业配置柱状图tooltip移动端超屏修复**(`1d91a9e7` 已上线):用户反馈"行业配置里移动端点击横向柱状条后这个提示超出屏幕导致看不全了"。根因3条全部坐实:indChart.setOption(L10359)直接setOption没走withTheme()包裹,全局chartThemeOpts() L155-156的confine:true+extraCssText max-width没合并进来[①缺confine:true tooltip不限制在图表容器内移动端窄屏375px右侧空间不够超屏②缺extraCssText max-width formatter多行长中文(行业名+平均权重%+说明+持仓市值+基金数+权重和+合并说明)撑宽超屏③缺position回调默认鼠标右侧定位移动端右侧不够超屏];用户说的"提示"是tooltip(不是modal基金列表弹窗)。修复复用全局proven模板L155-156:L10360 tooltip配置加confine:true(限制在.pf-ind-bar容器343px x 360px内不超屏)+extraCssText "max-width: min(300px, 82vw); white-space: normal; overflow-wrap: anywhere; word-break: break-word;"(300px封顶小于容器343px留余量82vw窄屏兜底强制换行防长中文撑宽),不加position回调(confine+max-width已够避免桌面端副作用)。sw.js bump ui84->ui85(预估点位agent已bump ui84串行ui85)。commit 1d91a9e7只stage 4文件(app.js/app.min.js/index.html/sw.js)不含daily-update agent的public_fund.py(AZ111独立commit)。线上验证ss.fx8.store sw=ui85,app.min.js含confine:!0。详见NOTES §48 AZ112。

**1待验证(写在此处防compact丢)**:
- 预估仓位每日自动更新闭环首次自动跑:8/3周一收盘后16:30 daily.sh pipeline_daily采8/3净值+fetch_index_daily采8/3三指数+export重算position_estimate(current.date 7/31->8/3)+deploy.sh rsync+git push上线;10:00/11:00/13:30/14:30 estimation.sh盘中采fund_value_estimation_em入fund_estimation_nav表。验收口径:JSON current.date=2026-08-03即闭环(当前7/31);fund_estimation_nav表有8/3盘中4档数据

今日3项 UI 全闭环上线(AZ88 deploy=128事故修复 + AZ89/AZ90 纯调研落档 + AZ91 本节3项 UI 实施):①P1+P2全球指数前端角标配套(commit `1e9d5d43`+后端`bccef338` sw ui11->ui12):后端`bccef338` intraday_snapshot.py加`_fetch_global_realtime_sina()`+`_GLOBAL_SPOT_CODES`15指数清单(nikkei225/kospi/ftse100/dax/cac40/asx200/sensex/cesg10/hsmogi/hsmbi/hsmpi/hscci/cshklre/cshklc/cshkdiv),新浪hq.sinajs.cn b_/rt_前缀批量采(akshare index_global_spot_em走东财push2本机连接被拒RemoteDisconnected与CLAUDE.md东财2源被封弃用一致),写入snap['global_realtime']失败不阻断快照核心;前端`1e9d5d43`新增addGlobalRealtimeBadge(cardEl,indexId,snap)读global_realtime.<id>展示price+chg_pct%+time+refreshGlobalRealtimeBadges(snap)overview轮询后重绘角标同refreshCardTimeBadges模式+renderGlobal@L9159调用+两处refreshCardTimeBadges调用点(L5532/L5724)后追加;样式.card-realtime-badge@style.css L388-420右上top:30px right:8px避开.card-time-badge(top:6px)+涨红#e6492e/跌绿#2e8b57/平橙#ff9800 A股配色+移动端top:26px right:6px font-size:10px;数据缺失兜底global_realtime无该indexId或snap未就绪不渲染角标卡片照常显示;欧洲指数ftse100/dax/cac40 A股盘中可能未开盘不做特殊过滤角标time字段让用户自行判断。②IA重构(commit `8f7d124d` sw ui12->ui13):market瘦身`_MARKET_SUBTABS=["a-stock","hk","global"]`移除futures/national-team;sentiment加二级subtab机制`_SENTIMENT_SUBTABS=["market-temp","futures","national-team"]`仿market subtab-bar渲染模式;renderSentiment改分发器原主体抽取为renderSentimentMarketTemp(container)默认market-temp=原sentiment内容移除末尾期货section;renderFutures/renderNationalTeam移sentiment二级futures归sentiment/futures national-team归sentiment/national-team;hash路由加sentiment/{subtab}分支F5恢复二级tab;tab切换校验state.subtab合法性market/sentiment共享subtab状态;overview汪汪队右列卡片保留不动。③grid min-width 600->650(commit `dce3eae8` sw ui13->ui14):.indices-grid/.industry-grid minmax(600px,1fr)->minmax(650px,1fr)只改这2处,.astock-top-grid 700px保持不变,顺带修industry注释minmax700px->650px(indices上方注释700指astock保留),bump style.min.css?v=(index/about/privacy html)+bump sw.js CACHE_VERSION ui13->ui14。3域名ui12/ui13/ui14上线(ss.fx8.store CF主站/sss.sugas.site GH Pages/s.sugas.site MaoziYun)。约束遵循:3项均只改static-site/不碰根data/,均19:00后收盘后实施避开09:30-15:30盘中窗口,改app.js必bump sw遵循memory bump-sw-version-with-appjs,角标配色A股红涨绿跌遵循memory default-theme-redgold。sw.js CACHE_VERSION连升ui11->ui12->ui13->ui14用户需清SW拿最新ui14。详见 NOTES §48 AZ91。

**明日(2026-08-01 白天)公募基金持仓实施计划**:周末不开盘无冲突,盘中禁全量export+deploy约束不触发(本任务不跑export+deploy)。主链路(白天):5汇总接口+头部1000只明细采集实施(akshare fund_portfolio_hold_em十大重仓+fundf10子页爬虫兜底行业/资产/变动+fund_value_estimation_em日更估算+fund_open_fund_daily_em全部基金日净值+fund_purchase_em申赎状态),5核心指标计算(平均仓位/抱团度Herfindahl/重仓股重叠度/行业集中度/净申赎率)+3衍生(加仓减仓比/头部调仓/Top30集中度),前端sentiment二级tab加「公募基金持仓」(遵循AZ90设计方案:4信号灯卡片+仓位vs上证双轴主图+88%魔咒警戒线/80%抄底线+Top30排行+行业热力图+头部调仓Top20+滞后性提示),首页角标接入(平均仓位+颜色>88%红/80-88%黄/<80%绿),信号灯规则(88魔咒/80抄底/抱团瓦解/净申赎反向),4维资金面共振联动(北向/两融/产业资本/基金持仓)。补充链路(凌晨解耦跑):9000只全量采集(全量反爬风险缓解:延时+retry+断点续采`/tmp/fund-collect-progress.json`重跑跳过已采,最坏降级头部1000只覆盖95%+规模)。工时~4天(后端采集+指标2天/前端tab+角标1.7天/信号灯接入0.3天),较原~3.5天+0.5天(全量采集脚本+断点续采复杂度)。排期:08-01白天(周末不开盘)。完整调研报告404行存`/tmp/public-fund-research.md`,反爬可行性调研存`/tmp/agent-progress-fund-research.md`。详见 NOTES §48 AZ90 + TASKS.md「2026-07-31 公募基金持仓佐证大盘」待办条目。

**2026-07-31 05:00(deploy=128事故修复闭环✅+atr pin根治验证生效)**:今日1项闭环上线:①deploy=128事故修复(commit `3c740dde` push feat+main fast-forward):05:00 us_stock_morning.sh跑deploy.sh git commit撞unmerged exit 128(外层exit=0吞失败=监控盲区§0①),根因deploy.sh `pop_rebase_stash`函数(L287-293)rebase后stash pop遇schedule_stats.json/.gz冲突只echo不解决留unmerged污染下次deploy,02:10 backfill deploy rebase留unmerged->05:00 us_stock_morning撞128->730信号R2已上线但git main没推(CF Workers/GH Pages渠道断);修复双保险A方案根治pop_rebase_stash(L315-330,pop冲突自动解决static-site/data/*数据文件冲突取theirs+add+drop,非数据文件保留stash待手动)+B方案起始unmerged清理兜底(L61-83,fetch后检测unmerged数据文件强制reset+checkout origin/main,非数据文件exit 1报警),bash -n通过;git main恢复730数据commit `d6c54ffd`(push b1906150..d6c54ffd)+修复`3c740dde` merge main(ff d6c54ffd..3c740dde),线上CF主站overview date=20260730恢复,R2 ssd.fx8.store/index/us_ixic-all.json 775信号含730;atr pin根治验证生效commit `a761278e`(us_stock_morning.sh deploy前重算signals+signal_stats写signal_daily表)05:00执行成功(signals=49905条 RECOMPUTE_RC=0,730信号us_ixic buy_aux正确生成,signal_daily表最新20260730);stash清理drop 2条纯数据残留(021011+schedule_stats residual),保留stash@{0}(212759含08-买卖点策略深度回测.md 396行文档改动非纯数据待用户决定恢复)+4条用户wip,最终stash 5条;未尽事项notifications.json.gz未推git(intraday-snapshot定时任务独立push待盘中推送)+schedule_stats.json用05:04版(push_schedule_stats.sh已独立推);教训固化监控①exit=0不可信(子bash-c失败外层exit0)须结合deploy退出码/线上时效确认,deploy.sh rebase stash pop冲突必须自动解决数据文件不能只echo留unmerged。详见 NOTES §48 AZ88

**分支**:origin/main = `194c097f`(批次1 提速 `172fe2b6`+docs `194c097f` 已上线)
- 批次1 commit:`0e916672` feat: B4 C方案(E2去双throttle+并发采集+--full-market) + `172fe2b6` data: etf_score_list 1371只修复(手动rsync trade-data->trade)
  - B4 base.py:throttle()加threading.Lock + safe_call加skip_throttle参数
  - B4 etf_national_team.py:L384去显式throttle(双->单) + akshare sina skip_throttle=True可并发 + mootdx fallback _MOOTDX_LOCK串行 + pipeline_daily/pipeline_backfill改ThreadPoolExecutor(max_workers=10)
  - B4 update_all.sh:L117加--full-market(62只代表性->全市场1371只ETF评分)
  - B4 小测:20只ETF串行5.73s->并发1.04s,提速5.52x,结果一致(True)
  - Top2 backfill-evening plist:删20:00槽(晚间冗余兜底),保留16:35+02:00(unload/load生效)
  - Top2 etf-national-team plist:删21:30槽(20:07已采兜底冗余),保留20:07(unload/load生效)
  - Top2 省时:旧代码~91min/天(20:00 backfill 56min+21:30 etf 35min),B4后~20.9min/天
- 批次2b commit:`dac046ee` feat: 批次2b 仓位展示丰富化(6维度透明化,方案1+2)(已上线)
- 版本号:app=9601bca3 common=256e3709 style=35ed6ea5(B4未改前端,版本号不变)

**活跃 cron**:
- `75079ec9`(8/3 17:03 one-shot,session-only):验证预估仓位每日自动更新闭环首次跑(8/3周一收盘后16:30 daily.sh应已跑)
- `5eed36c3`(每小时监控回归7-30全天,:07,session-only,④含告警邮件扫描 grep notify.py/[intraday告警]/upload-index R2失败/数据源未推)
- overlap delta调研agent(aac067bbc6e29125c)无独立cron,主控手动轮询进度文件mtime

**活跃 agent**:
- overlap delta可比口径调研 aac067bbc6e29125c 进行中(只读,报告/tmp/agent-progress-overlap-delta.md;调研overlap delta=-752.9偏大根因[中报2835只vs年报5285只披露范围差异]+2-4个可比口径方案+推荐+工时;调研完派实施agent)
- 2026-08-02会话已完成7项(全闭环上线):①补修2处英文残留 a3e2360459df96278✓(ui87 1066489c)②❓弹窗申万一级 a8ed0f2866a9947f8✓(ui88 84d3a153)③lg/cninfo中文化 a63934ddb7e66dcf1✓(ui89 c072f933)④全站38条中文化 a6708457a2dc0fe3a✓(ui90 35a94d1e,中途429配额12:13恢复后SendMessage resume原会话§11优先resume不重派)⑤公募5项修复 a28ef5ba27e3bba77✓(ui91 baaac2e2)⑥导航重构基金评分 a679dfef60111a9bd✓(ui92 a1c8315f)⑦88魔咒图钉说明优化 ae4ca753557ad7040✓(ui93 7f32faf7);另有2调研agent已闭环:P1-1+rzhb调研 a6ff95e2394b3f0db✓(两方向都已实施过:P1-1走向量化AZ12/AZ31已达11.87s->6.10s省49%剩余signals递归无法消除建议不动;rzhb 23:00->08:00主采+19:15兜底AZ59 29939ade已根治SSE两融T+1早晨发布是硬约束无法再提前);全站英文扫描 a33671985f9cf5c88✓(38条清单报告/tmp/agent-progress-i18n-scan.md);公募4问题调研 a9139fd049095d631✓(报告/tmp/agent-progress-pf-4issues.md 848家真相=Top30重仓股平均每只被848家基金持有)
- summary布局fix2 a91c8807 ✓完成验收(commit feat 2b3860c7/main 791eb4ec, style.css L2617-2618 加 order:1[.summary-meta]/order:2[.summary-title-tags] 视觉顺序title->meta->titleTags 行1title+meta同行行2titleTags独占, sw a81->a82, 线上ss.fx8.store+sss.sugas.site order:2✓; 根因确认:titleTags DOM顺序在title/meta之间flex:0 0 100%把meta挤行3,a80只改CSS没改DOM,order修正视觉顺序;用户需清SW拿a82)
- intraday角标调研 abff38b0 ✓完成验收(根因:getCardTimeBadge L4225-4240 分时图角标isIndexSpark时间用_intradayDynamicTime(1min 13:04更新)但状态读snap.label(10min 13:05才更新)错配,13:00-13:05窗口显示"午休·13:04"黄色状态滞后;其他角标isIndexSpark=false只读snap.datetime同源无歧义;方案:加isIndexSpark&&_useDyn用_dynMin判断9:30-11:30/13:00-15:00盘中覆盖)
- intraday角标实施 a679960d ✓完成验收(commit 89cb29fa, app.js L4236-4241 加isIndexSpark&&_useDyn用_dynMin判9:30-11:30/13:00-15:00盘中覆盖[分时图角标基于自己1min数据时间切盘中不读snap.label]+L4149横幅午休判断改_bjMin[11:30-13:00前端时间], sw a82->a83, 线上sss.sugas.site a83✓; push feat force-with-lease[rebase改hash必需]+push main fast-forward无force main合规; 用户需清SW拿a83)
- 今日已完成:summary布局 a9969c07✓(sw a80 7bd60ad3)/debug浮窗 ae33f73f✓(sw a81 09ef2664)/summary L6432复查 a8ac5586✓(无需改纯SW缓存)/summary布局fix2 a91c8807✓(sw a82 791eb4ec order修复)/intraday角标 a679960d✓(sw a83 89cb29fa getCardTimeBadge _dynMin盘中覆盖+横幅_bjMin)/atr pin实施 aa7558cdee✓(a761278e us_stock_morning重算signals 明天05:00根治 当前17:50 update_all修复)/R2告警根治 ab2f3ede✓(commit 2f0159c2 upload_r2.py s3_request 5xx重试[1s/2s与网络异常对称]+_upload_glob返回failed_rels+cmd_upload_index打印FAILED_FILES+notify.py加--dedup-key/--dedup-window[data/notify_dedup.json 30min不重发]+intraday_snapshot.sh告警body引用FAILED_FILES+共上传汇总+.gitignore加notify_dedup.json;治本5xx自愈+失败清单+去重文案三管齐下;15:05 intraday验证;用户反馈邮件告警接入监控④b)/intraday回归修复 a4abe805✓(commit 35d7eef3 L242 sed单引号改双引号破坏bash -c块致commit+push失败[2f0159c2回归14:55/15:05两次失败线上滞留14:45]+bash -n通过+补跑force恢复collected_at 15:19:43;教训:验收ab2f3ede时没跑bash -n漏语法检查致回归)/监控漏洞补 cron 5eed36c3✓(①exit=0不可信+②盘中15min阈值查intraday时效+④a加语法错误扫描unexpected EOF+⑥主动派agent不等反馈;memory monitor-blindspot-exit0-syntax-error落档;2026-07-30 intraday回归延迟16min用户先发现教训)/favicon替换 a6a1127b3✓(magick PNG->ico 16/32/48/64+index.html L18 svg->ico ?v=beddb3f1+sw.js PRECACHE_URLS加favicon.ico)/favicon白边修复 ab89805d0✓(PNG color-type 2 无alpha白底是自带非透明,-background none/-trim无效,改 -fuzz 5% -transparent white 白底变透明 PaletteAlpha 8-bit 32038B md5 1dbb579c+index.html L18 ?v=1dbb579c;教训PNG无alpha白边用-transparent white)/期货净加多空配色 a475b97c7✓(merge 14fa2b2f,app.js L9322 chgColor 正数多#e6492e红负数空#2e8b57绿 A股红涨绿跌,原美股风格正绿负红反)/全站A股配色统一 a1aa69a44✓(merge cb8b0515,3处反配色:app.js L9489 cmpChgColor当日净加对照+style.css L4451 .etf-hold-chip-buy border-color var(--up,#e6492e)原#16a34a绿->红+L4452 .etf-hold-chip-sell var(--down,#2e8b57)原#e6492e红->绿;build_min 6文件+bump_asset_version about/index/privacy.html+sw.js CACHE_VERSION v2-20260730-color2;教训--up/--down变量未定义走fallback故改fallback生效)/verify_backup R2重试加固 ace471e13✓(merge 1e640a41,告警7-30 18:20 verify_backup R2下载失败 ssl.SSLEOFError TLS抖动同一时点backup_db PUT也失败证R2整体不可达非逻辑错/凭证/桶错;修复1 upload_r2.py L113 range(3)->range(5)+L163/L172 attempt<2->attempt<4+退避1s/2s->1s/2s/4s/8s指数退避总~15s覆盖所有R2操作;修复2 verify_backup.sh L47 封装download_backups()函数+L68-69 第1次失败sleep 60s重试1次才告警双保险;py_compile+bash -n PASS;alerts/latest.md清空;教训R2 S3 API偶发SSLEOFError需指数退避+延迟重试双保险,监控④b grep *_launchd.log漏扫verify_backup_*.log/backup_db_*.log盲区待补)/准确率分类筛选 27b365be✓(feat,app.js _calcSignalAccuracy L1244加byType分组统计7类信号[_SIG_TYPES L1233不含buy_special_filtered]+state加sigTypeFilter L10+筛选逻辑L1303/L1318加signal类型分支+汇总条新增分类行.sig-acc-by-type[L1433 _byTypeRow动态生成chip只显示当天实际出现类型]+chip格式●标签X%(t/f)band_hold特殊只显示数量since_correct恒null+pct跳过L1280-1282+click handler L7093 type-filter toggle复用sig-acc-filter-active选中态+CSS L784 flex-wrap;方向决策A同行追加保留评级行+加分类行正交维度不互斥/band_hold只显示数量/只显示有数据分类;sw.js CACHE_VERSION v2-20260730-sigtype+build_min+bump?v=;详见NOTES §48 AZ87)/sigtype样式修复 012d3a16✓(fix,用户报"字很大";根因_byTypeRow L1433渲染在.signal-accuracy-summary的</div>之外L1434 ${_byTypeRow}在</div>后不继承font-size:12px+.sig-acc-by-type L784只设margin/flex/gap未设font-size继承父级更大字体容器默认14px+;修复.sig-acc-by-type加font-size:12px line-height:1.6与评级行一致;教训新增独立于父容器的div若父容器靠font-size控制子元素字体新div需显式设font-size不靠继承;sw.js CACHE_VERSION v2-20260730-sigtype2+build_min+bump?v=;详见NOTES §48 AZ87)
- 批次1 提速 a99f4fbaa ✓完成上线验收通过(commit 0e916672+172fe2b6+194c097f,sss.sugas.site 1371只✓,ss.fx8.store 62只CF deploy延迟跟进,Top2 plist去重✓;待20:07 etf pipeline_daily跑并发新代码验证全量提速35min->?min)
- 修sticky a19b42a5 ✓完成验收(commit 47c66add rebase后push main,sss.sugas.site style.min.css?v=0a15c967含position:sticky✓;ss.fx8.store批次1数据1371只✓+sticky前端CF deploy延迟~20min中,非失效是CF Git integration延迟特性,远期可加GH Actions wrangler deploy加速)
- 国债修复 a67c9f22 ✓全部完成上线(commit 7a389561 data update全历史band JSON push main,三站验证sss band_hold 5d_n=4045/1805/1564全历史✓非旧版0;方案A改进worktree+双DB symlink跑deploy.sh不动主工作区§10/§12;遗留R2 lab/trade_sim旧版非阻塞远期trade-data跑R2)
- 国债范围核实 a50e5409 ✓完成(验收:db1dbf32是LIMIT 120近60天滚动窗口非全量,60=MA60 warmup,DB band_hold 46条仅20260427..20260723近60天,index_daily全历史2161天,band与其他信号范围不一致)
- 理财专员使用指南 a0ce362e ✓完成验收(docs/理财专员使用指南.md 613行7章+附录;合规口径1手2手3手非1档2档3档+免责声明3处§〇/§6.7/文末;回测数字真实标注来源signals.py/trade_sim/signal_stats;卖点定位胜率≈50%非独立指令;无回测品种诚实说明§5.6;等用户定上线about页/就放docs)
- 文档merge main a94cd396 ✓完成验收(cherry-pick 7ff066d7 push main fast-forward,origin/main含文档613行,worktree清理,主工作区未动)
- R2 lab/trade_sim上传 ab17abaf ✓完成验收(upload_r2.py lab 65/65+trade_sim html 100/100+json 400/400,线上ssd.fx8.store content-length一致,补a67c9f22 worktree缺失;关键教训:trade_sim只在trade/不在trade-data/,R2 upload不设REPO从trade/跑,§9 cwd=trade-data规范是uvicorn读DB不适用R2上传)
- B4实测查 a325e4ada08ccae9b ✓完成验收(20:07 etf跑B4并发新代码,日志line1728-1912:max_workers=10启用1374只sh737sz637+FATAL address_pool_manager 6次V8多线程重复初始化+退出码133 SIGTRAP崩溃+0只成功;7/23旧串行1371只有OHLC进度日志正常未崩;根因mini_racer V8 isolate非线程安全ThreadPoolExecutor并发不兼容;提速35min->?min不成立根本没采到)
- **B4修复 a22d34eb297df2786 ✓完成验收上线**(ProcessPoolExecutor max_workers=8,模块级_fetch_one_ohlc_worker/_fetch_one_backfill_worker pickle-able+_get_worker_tdx进程局部懒创建tdx_client;每进程独立V8 isolate进程隔离不撞address_pool_manager;保留B4其他改动throttle加锁/skip_throttle/--full-market/_MOOTDX_LOCK;重采1376只完成入库7555行daily全流程158.0s并发采集142.6s无崩溃FATAL=0;DB etf_daily MAX(date)=20260724采734只ETF;提速35min->158s=13.3x达预期;push c1921857+merge 55e7c163 push feat+main无force;deploy 37b6571d从trade-data跑读最新DB+1m补推31f3be74;三站验证:sss.sugas.site/s.sugas.site updated_at=20:40:32含7/24末日510050 close=3.05✓,ss.fx8.store仍17:15[wrangler未装CF Workers待手动deploy,任一OK即算上线§8];附带修deploy.sh L194 etf_nt _rng补1m[原3m/6m/1y漏1m致deploy git add不commit 1m数据,1m由pipeline_daily export_json_files生成非export.py];进度文件/tmp/agent-progress-b4-fix.md)
- **backfill_evening 20:00 漏跑告警排查 af3e3c90e8fa2d042 ✓完成验收**（2026-07-24 20:15:06 告警;结论=**误告警**:plist 已由 Top2 去重删 20:00 槽[16:35+02:00 两槽],但 `scripts/schedule_monitor.sh` L51 schedules 仍含 20:00 => 监控配置滞后误判;处理:schedule_monitor.sh L51 删 20:00 同步 + 清空 data/alerts/latest.md[本地 untracked,gitignore L24];下次 schedule_monitor 21:00跑后无新告警;commit 9d612ec5 push main ✓[a22 merge 55e7c163带入schedule_monitor改动,af3 9d612ec5只补TASKS fast-forward无冲突]）

**正在等**:①overlap delta可比口径调研agent(aac067bbc6e29125c)完成报告->派实施agent(overlap delta=-752.9偏大优化,中报/年报披露范围差异);②8/3周一收盘后预估仓位每日自动更新闭环首次自动跑验证(16:30 daily.sh pipeline_daily采8/3净值+fetch_index_daily采8/3三指数+export重算position_estimate current.date 7/31->8/3+deploy.sh rsync+git push上线;10:00/11:00/13:30/14:30 estimation.sh盘中采fund_value_estimation_em入fund_estimation_nav表;验收口径:JSON current.date=2026-08-03即闭环);待排期:公募基金筛选器大工程[需先补fund_basic字段规模/经理/业绩,memory pf-fund-screener-real-requirements明确实战级];远期ss.fx8.store CF deploy优化(GH Actions wrangler);前次历史待办:a9bfb02d 8任务采集时点调研报告(关键发现rzhb 23:00滞后4-5h应提前到19:00-19:30违反第一时间发布)+下一轮优化候选(a37 P1-1 compute/runner.py 14步串行->ThreadPool并行B并发省30-50%[7独立步骤+6指数循环]/P1-2 export.py 30次重复查DB->内存切片A脚本合理性/rzhb 23:00->19:00-19:30第一时间发布)已全部闭环(P1-1走向量化已达标/rzhb已08:00根治详见AZ59)

**三站验证结果**(批次1 提速,任一新版即算上线):
- sss.sugas.site(GitHub Pages):etf_score_list.json universe=1371 full_market=True ✓(批次1上线OK)
- ss.fx8.store(CF 主站):etf_score_list 仍62只 full_market=False(CF Workers deploy延迟,sticky push main触发新deploy时跟进;不卡单域名§8)

**收盘后分批实施**:
- 批次1 提速:Top2集群(B1+F2+L3+L-1+R1 零代码省100min/天)+ B4 C方案(E2去双throttle+并发采集+--full-market,35min->3.5min)
- 批次2 合规+展示:合规改名(8+19处 1档->1手 + 建议类导向词)+ 仓位展示丰富化(方案1主展示chip 30min + 方案2弹窗加仓位依据分区 1.5h 推荐 + 方案3全套透明化 3-4h;后端6维度全分已算前端只露波动率)+ 重生JSON deploy
- 批次3 远期:Top3 U1+U2(baostock多进程+合并deploy)+ A6 PWA(3方向分叉待定)+ C1 TASKS移除已闭环标记

**保活**:caffeinate PID 11109 至 2026-07-26 08:44(elapsed 04:27h 至 05:13)

**2026-07-25 05:13 续(48h 监控 cron 触发发现未闭环)**:etf_national_team "退出失败 last_exit=143" 假告警**未真正闭环**。05:00 schedule_monitor 又发 SEVERE 邮件。根因主控已单点确认:schedule_stats.json mtime 7/25 02:09(早于 6824a43c commit 03:54)= 旧版 gen_stats 生成仍 143;schedule_monitor.sh 只读不重跑 gen_stats;7/24 20:07 那次 collector 成功(DONE 2032s)+ deploy 真失败(rc=1 撞 unstaged industry-3y,bba5ecaa 7/25 已修),6824a43c fallback DONE 行只覆盖 collector 失败没覆盖"collector 成功+deploy 失败"。派 background agent `a14029986d4847e97` 彻底修(backfill.sh DONE 行带真实综合 exit / gen_stats / schedule_monitor 跑前重跑 gen_stats / 重生成 schedule_stats.json)。进度文件 /tmp/agent-progress-etf143.md

**✓05:23 完成验收上线**(agent a14029986d came to rest,commit `afd9b5a8` push feat+main fast-forward)。主控逐字验收 6 项全 ✓:①commit origin/feat+main 都含 ②本地 schedule_stats.json etf `last_exit=null`(非143非0) ③backfill.sh L99/101/112 DONE 行带 `exit=$FINAL_RC`(补全 6824a43c 只覆盖 collector 失败的缺陷:collector 成功+deploy 失败 -> FINAL_RC=1 -> `完成 Ns exit=1`) ④schedule_monitor.sh L135 跑前调 gen_stats 重生成 ⑤curl ss.fx8.store 线上 etf=null 已同步 ⑥矛盾澄清:7/24 collector V8 FATAL crash 没 DONE + backfill.sh 继续 deploy 失败 rc=1,None 合理(历史无法还原真实 exit 但避免假143;未来 crash/deploy失败有 fallback DONE 带真实 133/1)。详见 NOTES §48 AZ17。止损:schedule_monitor 05:30 跑后不再发假 143 SEVERE

**2026-07-25 07:48 续2(用户问角标+规划周末)**:用户问"右上角小红点怎样变绿/异常信息自动清理还是怎样消失"+"接下来做什么/你规划"。派 2 个 background 调研 agent 并行(只读不改):①`a06473c4da5e1a4ce` 角标红点机制(组件位置/数据源/红变绿条件/异常信息清理机制)进度 /tmp/agent-progress-badge.md ②`a83e66c8145e9027a` #19+#21 作用说明扩所有 tab(现有 lab-purpose-note 机制/所有 tab 清单/首页三模块位置/完整实施方案)进度 /tmp/agent-progress-purpose-note.md。周末规划:角标调研回->验收回答+若自动清理机制不合理派实施 / #19+#21 调研回->给方案确认后实施 / #20 皮肤适配待 #19+#21 完成 / 7/27 周一验证 rzhb 19:15+etf 20:07&21:30 新时点 / 07-26 08:44 48h 监控汇总+CronDelete

**2026-07-25 08:00 续3(角标调研回+用户定A+B)**:角标调研 a06473c4 ✓完成验收(4项全✓:app.js L3415 _renderCollectHealthDot 绿/黄/红 + L3437 读 overview.json collect_health + queries.py L456-471 过滤 status!=ok + 线上 level=error items=1 a_fund_main)。机制:红点=采集健康灯(collect_health),自动覆盖式重算(盘中每15-30min intraday 重生成 overview.json)+跨日清零+核心指数陈旧误报复核,不需手动清 alerts/latest.md(那套前端不读)。当前红点原因:a_fund_main direct:market_fund_flow 两源皆败持续多日。用户定 A+B 都做,派 2 agent 并行:①A `ab487f689dcbf3330` 查修 a_fund_main 采集源(两源失败根因+换源/修解析,不跑 export 避免撞B)进度 /tmp/agent-progress-a-fund-main.md ②B `a003f50fef73730dc` 持续故障降级机制(连续N天同error降warn+标"持续X天已知故障",改 queries.py+app.js+跑 export_overview+deploy)进度 /tmp/agent-progress-health-degrade.md。A改 collector/direct.py 不跑 export,B改 queries.py+app.js 跑 export,不同文件不冲突

**2026-07-25 08:10 续4(#19+#21调研回:已上线闭环)**:agent a83e66c8 ✓完成验收。重大发现:**#19/#20/#21 均已上线**(commit `c75c9c57` 7/17 #21 首页大盘信号/情绪温度/板块轮动3板块白话说明卡片 + `a428b44c` 7/17 #19 lab全tab作用说明白话区块+#20 参数扫描判定栏背景色适配皮肤)。验收:git log 两 commit 存在 + origin/main 含 + app.js home-purpose-note 11处 + lab.js lab-purpose-note 8处 = 19处文案 + CSS style.css L2967 .home-purpose-note / lab.css L989 .lab-purpose-note 双类定义。功能闭环,TaskUpdate #19/#20/#21 -> completed。场景B重构(统一类名+集中文案到 purpose-notes.js,2.2h,消除类名分裂/写法分裂/文案散布三大技术债)列为低优先级可选待办,非用户可见,当前优先 A+B(a_fund_main 红点修复+持续故障降级,用户可见改进)

**2026-07-25 08:15 续5(B持续故障降级✓上线)**:agent a003f50f ✓完成验收(commit `f1187fed` push feat+main 08:01:13)。N=3 阈值(同 metric_id+message 连续3采集日 DISTINCT run_date error 降 warn,考虑周末不采集非自然日)。改 queries.py L490-525 降级逻辑(L494 `_N_DEGRADE=3` / L510 `_cnt>=_N_DEGRADE and status==error` / L513-514 `status=warn`+message 加`[持续{cnt}天 已知故障]`前缀 / L522 level 按降级后 items 聚合 error/warn)。未改 app.js(_renderCollectHealthDot warn/error 都显示 pop,后端前缀足够,无需 build_min/bump)。验收3项全✓:grep 降级逻辑落地 + 线上 ss.fx8.store `level=warn a_fund_main|warn|[持续3天 已知故障]两源皆败`(红点变黄点) + origin/main 含 f1187fed。新 error(<3天)仍红(L510 条件)。A 根治 a_fund_main 后变 ok 绿点,B 降级兜底(A 没修好时黄点不困扰)

**2026-07-25 08:20 续6(A a_fund_main 修复✓上线,待自然验证)**:agent ab487f68 ✓完成验收(commit `8ad1ac6a` push feat+main 08:13:24)。根因:东财端点级反爬封锁(push2his.eastmoney.com 整域名被封 curl 52 Empty reply + push2 clist 被封,akshare 底层全走东财同步死,同花顺 chameleon 401/新浪 MoneyFlow 下线/mootdx 无资金流)。修复:direct.py L86 新增第三源 push2/api/qt/stock/fflow/kline/get(dapan.js 实时K线端点未反爬,klt=101 日K f52 主力净流入,原 clist 60页降第四源避免加剧反爬),四源兜底。验收2项✓:commit origin/main 含 + grep direct.py L31-34 注释+L86 实现。第一次测试成功 7/24 -774.61 亿(agent 报)。**collect_log ok 待自然验证**:反复测试触发东财 IP 级封锁(升级 push2 整域名封),collect_log 最新仍 error(08:04:07 A 测试产生),等 launchd 17:50 或反爬间歇期(7-23 17:02 曾成功模式)自然出现 ok,7/27 周一开盘日验证。B 降级(f1187fed)已把红点降黄点不困扰,A 修好后变绿。**A+B 闭环:角标红点困扰已解决(黄点兜底+根治代码上线待自然验证)**。#19/#20/#21 验收已上线(7/17 c75c9c57+a428b44c)标 done。剩场景B重构(purpose-note 统一类名+文案,低优先级可选)+ 7/27 周一新时点验证(rzhb 19:15/etf 20:07&21:30)+ a_fund_main ok 验证 + 07-26 08:44 48h 监控汇总

**2026-07-25 08:30 续7(场景B重构实施中)**:用户选推荐做场景B重构。派 agent `aca89f88e15e4693a` 实施(a83e66c8 调研方案 B1+B2):①CSS 合并 .home-purpose-note+.lab-purpose-note -> .purpose-note(+.lab-sm 修饰)②common.js 新建 renderPurposeNote(container,text,{variant}) 通用函数③新建 purpose-notes.js 集中19段文案(PURPOSE_NOTES 对象)+ index.html 引入④app.js 11处+lab.js 8处替换为 renderPurposeNote 调用⑤nt-banner 不碰(口径声明语义重)⑥build_min+bump_asset_version⑦三站验证19处文案显示⑧commit push feat+main。文案原样搬运不改。进度 /tmp/agent-progress-purpose-refactor.md。估时~2.2h

**2026-07-25 08:40 续8(场景B重构✓上线)**:agent aca89f88 ✓完成验收(commit `9afccee0` push feat+main 08:38:01,18files +100/-70)。7项全✓:①common.js L466 renderPurposeNote(container,text,{variant}) 函数 ②purpose-notes.js 17key(9home+8lab 带引号格式,文案原样搬运) ③app.js 残留 insertAdjacentHTML home-purpose-note=0/renderPurposeNote 9处 ④lab.js 残留 className lab-purpose-note=0/renderPurposeNote 8处 ⑤CSS .purpose-note(style.css L2969)+.purpose-note.lab-sm(lab.css L991)旧类删 ⑥build_min+bump 跑过(6文件built,版本号 purpose-notes.min.js?v=666be462 等) ⑦线上 ss.fx8.store purpose-notes.min.js HTTP200 + index.html 引用。**三大技术债消除**:类名分裂(两套CSS->一套)+写法分裂(insertAdjacentHTML/createElement->统一函数)+文案散布(19处硬编码->集中配置17key)。nt-banner 不碰。未来加新tab作用说明只需加一行 PURPOSE_NOTES[key]+调函数。**周末开发任务全部闭环**,剩等时点待办(7/27新时点/a_fund_main ok/07-26 08:44汇总)

**2026-07-25 09:05 续9(B4 OHLC + a_fund_main第五源 + A6 PWA 三项✓上线)**:用户定1+2+3全做,派3 background agent并行(文件不冲突:①export_etf_score_list.py+app.js+style.css ②direct.py ③index.html+manifest+sw.js)。①B4 OHLC(a7aa,`ca1e2eb9`+`313d2235`):**重大发现全市场扩采集1371只7-24已完成**(`172fe2b6`/`0e916672`/`0ffed42d`),本次只加OHLC导出(30日K线+buy/sell互斥+全量1376只+`_etfSparkline`前端SVG),验收universe=1376/buy=1064/sell=145/三站点ohlc_days=30✓。②a_fund_main第五源(af19,`1b6b04c1`):东财全家桶(push2his+push2+datacenter)联动封四源全死,调研9类候选源只同花顺行业资金流(`data.10jqka.com.cn`/`ak.stock_fund_flow_industry`)可用,direct.py+41第五源sum 90行业净额,**口径差异25%**(全部资金vs主力)方向一致兜底可接受,collect_log 20260725 ok+线上collect_health level=ok红点变绿✓。③A6 PWA(a399,`a41fb2df`):**发现PWA三件套`044fd34d`已存在**本次修正(theme_color#1a1d29->#d4af37 redgold + sw.js重写App Shell CacheFirst+数据SWR 3min+intraday NetworkFirst+CACHE_VERSION v2+sw-update-toast提示刷新),icon 192/512已有,三站点manifest/sw.js HTTP200✓。详见NOTES §48 AZ20。**①②③全闭环**,剩等时点(7/27新时点/a_fund_main ok自然验证/07-26 08:44 48h汇总)

**2026-07-25 10:16 续10(ETF评分三分类重构✓上线)**:用户反馈买入太多(1064/1376=77%)淹没卖出持有。四步:①调研ETF vs AI同源(a4ce12,lab.js L6273 slice(0,12)截断非独立逻辑,根本buy门槛宽松high<60&hands>0)②方向A UI 4项(d271a,`d271e0ed`,卖出置顶+买入折叠+持仓置顶+5档分档,app.js+294/style.css+83,app.min.js?v=7b210158/style.min.css?v=e8e9b3fb)③方向B回测(a33c9,C2=hands>=2&amt_pct>60最彻底,209只/5d+0.21/10d+0.37/20d+0.29 regime-agnostic;S2/S3 score阈值2026熊市误杀否决;B2/B3成交额分位regime-agnostic但C2双重过滤更彻底)④C2三分类实施(a8cc46,`1bd75d66` push feat+main fast-forward):**主控识别三分类设计**(防被过滤870只全进sell_list暴增1000+)-> buy=188(C2条件high<60&hands>=2&amt_pct>60)/sell=96(过热high>=60)/hold=925(不够格buy但不过热high<60&not C2)/数据不足167=1376闭环互斥(buy∩sell∩hold=0)。后端export_etf_score_list.py+71(L390-396 in_buy=C2/in_sell=high>=60/in_hold=新增+L535 buy_list加amt_pct+L557-567 hold_list收集),前端app.js+48(三路合并,sell全归side=sell不拆hold,hold_list->side=hold)。验收:commit 1bd75d66 origin/main顶部6文件 + L390-392 in_buy条件 + L395/396 in_sell/in_hold + 线上ss.fx8.store buy=188/sell=96/hold=925 date=20260724 + buy[0] amt_pct=83.3 high=18.32符合C2 + sell[0] high=80.68 + hold[0] high=17.67 hold_reason + 三站点✓。**工作区残留**(deploy.sh跑export副作用272JSON,R2超时被杀git add没执行)按§8教训git restore static-site/data/清100+残留M+rm baostock lock,工作区干净。详见NOTES §48 AZ21。**P1-新-C 阶段2 ETF评分列表功能完整**(分页/搜索/持仓输入/OHLC K线/三分类)

**2026-07-25 11:25 续11(ETF联动tag数据缺修复+bj50映射错误+漏上线误判纠正✓上线)**:①**漏上线误判纠正**:06055972/02eae130 已cherry-pick上线(efac8b7b/61be8e72),原hash悬空正常非漏上线(add2b0c5盘点+主控验收compute_band_signal signals.py L126+_appendEtfLinkTag app.js L7809+线上cgb_idx 3134条band_hold)。教训:`git branch --contains`空≠漏上线,查cherry-pick新hash。②**ETF联动tag数据缺修复**(aafeea92,`bdad37f6`):build_board_etf_map.py不在update_all未跑最新版,board_etf_map.json缺宽基/红利,deploy.sh加step 0.8每次deploy刷map根因修复(akshare~15s失败不阻塞),部分刷新10 index/*-all.json+R2上传186文件,线上hs300 etfs=3✓。**关键**:index/是R2托管+gitignore L85,部署走upload_r2 upload-index非git add,前端从ssd.fx8.store CSP connect-src读R2。③**bj50映射错误修正**(a397c50c,`38eb8741`):159509纳指科技ETF代码复用绕过EXCLUDE(L163-178代码精确匹配段未检查name),无活跃BJ50 ETF(akshare 1555条无北证),移除bj50映射+EXCLUDE补"纳指"简称+L173代码精确匹配段加name跨境检查双重防御,线上bj50 etfs=[]✓。详见NOTES §48 AZ22。**P2-新-G ETF联动tag功能完整工作**
**2026-07-27 续13(期货3表布局/颜色+信号评定+评分尾缀+intraday修复确认✓上线)**:今日4项上线+1评定+1确认:①a26 `d422a7c6` 前3表标题描述等高(min-height 44/42/84px)727对齐+第456恢复3列并排(删a25副作用grid-column:1/-1+新建tripleGrid2复用futures-triple-grid)②a27 `137a1d72` 前3副标题同向X%准确率着色(>55%绿#16a34a/<=55%红#dc2626,阈值同历史准确率卡片app.js L8091,fmtStat从未带颜色本次新增非回归)③a28 `e128cc42` 技术参考点评分尾缀(signal_stats.py加_compute_score四维加权+方向惩罚+n<30降级,每组合加score字段0-1;app.js预fetch+_getSignalScore按index_id+signal关联10d score+_renderSignalGrid加[高/中/低]角标高≥0.75深绿/中≥0.55橙/低<0.55灰+tooltip把握度/准确率/盈亏比/样本+组内按score降序+score≥0.75 sig-item-high绿描边高亮;sh buy_special 10d score=0.751高验证)④intraday修复确认(`37ae4500` AZ41已落档,329c1ce8改名ALL_RANGES->EXPORT_RANGES漏改intraday_snapshot.py 6处引用,盘中export AttributeError被try/except吞exit=0,AZ47第4盲区scan_log_anomaly抓到,git show --stat验收1file/6+/6-与6处一致;今晚确认3天盘中export失败已修etf_date=20260727正确,异常2误报为任务背景过时20260724周五值)。另完成信号评定清单(signal_stats.json 114品种×6信号×3窗口5d/10d/20d=1836组合,三维评定准确率35%+收益30%+盈亏比15%+样本20%+方向惩罚+n<30降级,Top15标杆上证追买10d n=612胜率72.2%/盈亏比2.37/+4.02%为全站标杆;结论趋势突破追买唐奇安20日A股指数/概念/行业最有把握,均值回归仅银行/美股蓝筹有效,卖点对指数基本失效仅情绪分见顶可作降温确认)。sw.js CACHE_VERSION连升a25->a26->a27->a28。详见NOTES §48 AZ50。✅监控9任务巡检报告已闭环(AZ51 C节确认7-27 9任务全exit=0:ETF国家队20:07+21:30首触/rzhb 19:15/lhb 18:30+19:30/期货20:05+21:00/收盘全量17:50/策略实验室19:00,无SIGTRAP/libmini_racer crash)

**2026-07-28 续14(P0-1 KPI预估点+debug CSS皮肤+封板率derived根因+分时图1min✓上线)**:今日4项全闭环上线:①P0-1 KPI走势弹窗补T日预估点(`7d06f9b6` sw a39,复用方案A `_appendIntradayEstimate`+新增`_appendKpiEstimate`适配层 todayValueOverride 向后兼容,`openKpiDetailModal` L3522 画完走势图补T日灰色预估点,数据源 overview.today 非 intraday_snapshot)②debug条 CSS 皮肤适配(`7b179644` sw a40,根因硬编码 color:rgba(125,125,125,0.62)+background:rgba(255,255,255,0.35) redgold 暗色皮肤低对比看不清,改用 CSS 变量 color:var(--text-3)+background:color-mix(in srgb,var(--bg-card) 45%,transparent) 跟随15皮肤)③封板率盘中滞后根因修复(`e51df0fa` sw a41,根因 intraday_snapshot.py 采完 zhaban 没调 derived.store_derived 重算 fengban(=1-zhaban) 致停 7-27,dc551dbd(7-23)误标 T+1 掩盖 bug;三处联动修复:intraday_snapshot.py L920 加 derived.store_derived(compute_derived_formulas())+app.js:3907 移除 T1_COLLECT_DEADLINE fengban+app.js:5553 移除 _kpiT1 fengban;验证 11:15 定时跑后 fengban=0.7941=1-zhaban(0.2059) source=derived date=7-28)④分时图刷新 3min->1min(`9dcbb080` sw a42,前端直拉腾讯分时 API web.ifzq.gtimg.cn CORS *,1min 匹配分钟线更新节奏;INTRADAY_REFRESH_MS 3min->1min+_onIntradayVisChange 切回 tab 立即刷新+渐进退避 MAX_FAILS=6/BACKOFF_CAP=8min/失败1次间隔翻倍+角标 3min->1min 4处 dyn-pulse)。sw.js CACHE_VERSION 连升 a39->a40->a41->a42。**4项均无独立 TASKS TODO 条目**(P0-1 源自 AZ54 调研报告 P0-1,其余3项 in-session 发现),本条会话状态即为落档。NOTES §48 AZ55 已落档+4条教训(debug CSS 应用 CSS 变量/derived 采完源数据需重算派生指标/T+1 标注掩盖 bug 非根治/分时图瓶颈在前端刷新频率非后端 intraday_snapshot)

**2026-07-28 续15(回测精准模拟+滞后提示+ETF去重✓上线)**:今日3项全闭环上线+1监控自愈:①回测精准模拟(`05490a0f`+`71d3adcd`,simulate_trade.py加手续费万3/千1双边+最低5元+沪市过户费万0.1[COMMISSION_RATE=0.0003/SLIPPAGE=0.001/MIN_COMMISSION=5.0/TRANSFER_FEE_RATE_SH=0.00001]+ETF替代指数含跟踪误差[data/index_etf_map.json 11品种映射:宽基7 sh/hs300/sz50/csi500/csi1000/cyb/kc50 + 港股3 hsi/hstech/hscei + 中概1 g.cn_us互联网,信号在指数生成成交在ETF]+纯指数也加费统一横向对比+港股ETF补采4只入etf_daily+前端chip"ETF 510300·含费万3"或"指数模拟·含费万3"(app.js L781)+修2 bug[simulate_trade.py L52 __file__未解析symlink改os.path.realpath/upload_r2.py REPO绝对路径]+206JSON+206.gz推R2线上hs300 etf_code=510300✓;3 agent协作:补采港股ETF/代码改/重生JSON+R2)②滞后提示修复(`28cf19a6` sw a44,用户"非异常不应提示滞后";根因弹窗_dataFreshness app.js:3975与卡片角标getCardTimeBadge:3820口径不一致T+1源过时刻仍显示⚠滞后;修复加srcKey+pastDeadline对齐三档[T+1过时刻=🚨异常/未到=⏳T+1待更新/T+0=⚠滞后兜底]+summary severeCount/staleCount分离+t1-pending tip改"前一交易日属正常设计(非异常)";T+1源6类配置T1_COLLECT_DEADLINE 3897-3908+_kpiT1 5551双列表覆盖北向/沪金/国债/QVIX/龙虎榜/换手率)③ETF评分买入机会同类去重(`f52a4a36` sw a45,用户"同类去重按钮开启后同类买入ETF只保留最好的,同类=同行业或同指数";app.js L9417 ETF_DEDUP_KEYWORDS优先级表[复合关键词最优先->行业/主题->宽基指数->全名成组]+L9431 _etfDedupKey+L9814"只看持仓"后加"同类去重"toggle默认关localStorage etf_dedup持久化+L9525 buys排序后filter保留每组score最高一只+区B副标题"同类去重后N只"+只影响buys holdings/sellHold不受影响;效果227只->104只减123只31组合并 中证500 21->1/沪深300 14->1/A500 13->1)④监控3异常自愈(ETF国家队7-24 collector撞libmini_racer SIGTRAP 7-27自愈/指数补采兜底deploy push失败non-ff 7-28 02:00自愈/期货机构持仓周日非交易日正常跳过;4修复建议待定见下方🆕2026-07-28待办)。sw.js CACHE_VERSION连升a42->a44。详见NOTES §48 AZ56

**2026-07-28 续16(ETF补采治本+回测切窗口bug修复+HTML5窗口+撤销方案F✓上线)**:今日4项全闭环上线,承接 ETF统一+自动采集待办(L688-700全✅):①ETF统一+自动采集续接(`de4be178` sh改8精准ETF[510210首位 510210/510760/510980/530060/510910/510140/562810/563930,6纯被动+2增强不含510050]+`6482d461` 方案D第二阶段自动采集[build_board_etf_map.py读etf_index_map.json建反向映射{track_index_code:[etf_code]}按amount降序,修3硬编码bug hscei 513900->510900/hsi 513600->159920/sz 159943->159903]+etf_index_map.json建表[1555只/ok=1192/上证综指8个全到位,dataPro MCP单查ETF返回track_index_code]+豆包3方案调研[AkShare不成立/Tushare需8000积分/当前D已等效,用户定继续D])②回测切窗口数据不变bug修复(用户报"进模拟回测弹窗 切换时间窗口 数据不变";根因simulate_trade.py _pick_first_etf运行时过滤<252天ETF[方案D]+phase2重跑后首位ETF上市太晚[sh 510210仅170天]+get_signals L248-249按etf_close_map过滤丢上市前signals致5窗口全退化全史跑同一批,48/103品种受影响;修复=方案D保留运行时过滤min_data_days=252+ETF历史K线补采治本;前端双入口确认app.js L10297 modal[左键sim-btn读trade_sim_data/*.json主入口]+L2146 sim-btn跳HTML[中键/ctrl兜底],用户报"弹窗"=modal;评级✅❌移指数名前`a426c38d` DOM顺序[信号标签b][⚠][评级][☑️/✖️][指数名] bump sw a49->a50)③ETF历史K线补采治本(`78eae801` 新增scripts/backfill_etf_daily.py用akshare fund_etf_hist_sina[新浪源,东财fund_etf_hist_em被封]拉全史,补采1228只ok ETF全成功入库988688行,>=252天ETF 17->885只[总表889只],关键ETF全史510050 50ETF 5208天/510300 300ETF 3443天/159915创业板 3551天/512660军工 2420天,etf_daily表252516->1034267行[增781751]1371->1478只,build_board_etf_map重跑59空->16空行业ETF全恢复[证券512880/银行512800/通信515880/军工512660等],simulate_trade --all重跑103成功行业ETF etf_code全恢复[补采前=None]5窗口.s各行业不同防退化成功)④trade_sim HTML升级5窗口+撤销方案F(`63a0daee` 根因simulate_trade.py --all默认只生JSON不生HTML[需--html flag]+trade-data的HTML是悬空symlink[94/100指向不存在的trade/static-site/];旧版HTML单窗口不含5窗口,升级build_html新增windows_stats/windows_meta参数+_render_window_table()+5窗口tab切换[all/y10/y5/y3/y1]+subtitle内嵌5窗口起止日期+CSS/JS,无windows_stats时退化单窗口兜底;_generate_one读trade_sim_{id}_stats.json提取windows_meta+5窗口summary传build_html[不重复计算与modal同源];跑--all --html生成103个HTML[2.5MB/个]上传R2 trade_sim/[103个]+trade_sim_data/[412个stats];撤销方案F=build_board_etf_map.py移除MIN_ETF_DATA_DAYS=252常量+_count_etf_days_multi辅助函数+源头过滤逻辑[-73行],方案F是设计错误[展示源不应过滤]保留方案D[simulate_trade.py运行时过滤],backfill后全>=252天撤销后board_etf_map内容不变)。commit链de4be178/6482d461/a426c38d/78eae801/63a0daee/ba0c4dae(data update [all] 2026-07-29_00:15)。线上验证3+1域名:R2 ssd.fx8.store/trade_sim/trade_sim_sh.html last-modified=2026-07-28 16:12:55 GMT 2.5MB内嵌5窗口2011/2016/2021/2023/2025✓,R2 ssd.fx8.store/trade_sim_data/trade_sim_sh_stats.json generated_at=2026-07-28 23:35 etf_code=510210 5窗口防退化✓,ss.fx8.store board_etf_map sh=8个+行业非空✓。详见NOTES §48 AZ57

**2026-07-29 续17(本轮4项修复chip方案D+ETF hover+板块分化按钮+过拟合警示文案✓上线)**:今日4项全闭环上线:①chip三档方案D多窗口综合分(`e2b097c7` sw a51,用户报"最稳健"选出近10年-13.31%回撤84%不稳健;根因steadyScore单窗口打分[wrNorm*0.4+ddN*0.4+opsNorm*0.2]门槛"年化>回撤"只验证entry自身窗口;修复打分单元从单窗口entry改成策略[path+scen二元组]聚合5窗口指标[profitWins/medianAnn/medianDd/maxDdAll/totalOpsSum]+三档门槛[年化最高=年化中位>=TH.ann AND 盈利>=3/最稳健=综合分>=0.5 AND 盈利>=3/回撤最小=5窗口最大回撤最小 AND 年化中位>0 AND 样本>=3],核心盈利窗口数>=3防单窗口虚高)②ETF tag三项修复(`b082462a` sw a52,hover重叠=.etf-tag删title+data-no-pop避_initTermPop捕获弹.term-pop盖住.etf-popup+_copyEtfCode改.copied class不依赖title/红黄措辞=_bindEtfPopup加"🔴最近买类信号(日期)/🟡最近信号非买点(日期)"消除"当前"误导[实际=最新一条信号不限时间]/板块分化位置统一方案A=_appendEtfLinkTag支持spark-name回退[h3->target]+板块分化改调_appendEtfLinkTag位置[ETF tag在sim-btn后]+红黄判定都统一)③板块分化按钮灰色兜底(`5be5a2d3` sw a53,根因SIM_INDICES缺sw_801120食品饮料/sw_801140轻工/sw_801200商贸零售3行业+renderIndustryGrid未调_appendPinBtn/_appendSubscribeBtn;修复_simBtnHtml始终生成[不在SIM_INDICES时灰色disabled+hover"暂未接入"]+补3sw进SIM_INDICES[stats.json存在变可用]+L9017/9018加pin/subscribe调用+_appendEtfLinkTag etfs为空时生成"无ETF"灰色占位符+hover提示;用户要求sim-btn必须保持有不可用灰色+hover提示原因,无ETF行业固定占位符不空白)④chip过拟合警示文案优化方案C(`62e7d19e` sw a54,调研结论警示不是旧逻辑残留整治[AZ26-AZ38]管参数侧[signals.py per-index调参]警示[AZ39]管结果侧[trade_sim夏普>3]两者不同维度互补;4误导点修复[①10.59被误读年化实际夏普②"部分"指代不明③全局maxSharpe 10.59来自非三档推荐策略和"三档推荐需谨慎"组合误导三档实际6.91/6.91/3.43④没区分参数过拟合vs小样本高夏普];修复警示条改"夏普比率红线提示"+明确"165回测中最高"+来源+AZ26-AZ38整治说明+"非必过拟合判定"+三档chip各自标注策略夏普[6.91⚠等]+_sharpeRedlineInfo增强返回maxSource+topTierMaxSharpe区分全局max vs三档max)。sw.js CACHE_VERSION连升a50->a51->a52->a53->a54。**附带发现独立问题未修**:所有28个申万行业trade_sim HTML线上404(HTML未上传R2,sim-btn左键跳modal读stats.json不受影响online 200,中键/ctrl跳HTML才404)。详见NOTES §48 AZ58。**rzhb/etf 7-27新时点验证✅已闭环**(AZ49 B节确认etf 20:07 exit=0+1376只ETF+libmini_racer未复现)+**监控9任务巡检报告✅已闭环**(AZ51 C节确认7-27 9任务全exit=0:ETF国家队20:07+21:30首触/rzhb 19:15/lhb 18:30+19:30/期货20:05+21:00/收盘全量17:50/策略实验室19:00,无SIGTRAP/libmini_racer crash)

**2026-07-29 续18(全站时序优化6项+QVIX精确化+告警根因✓上线)**:今日6项时序优化全闭环上线+QVIX时点精确化调研+告警根因4修复:①P0美股早采(`de4934da` us_stock_morning.py 05:00[美股04:00收盘后1h余量],新浪实时gb_$主源4只全OHLC[东财100.NDX mislabeled返IXIC弃用],queries.py us_dji_date改读DB[原读global-all.json滞后1天因export生成顺序],线上us_dji_date=20260728)②us10y消除滞后2天(`5c447d62` us_stock_morning加collect_us10y[bond_zh_us_rate美债10年]与美股同时区04:00收盘05:00顺带采,DB us10y date=20260728 value=4.61,R2 extras.us10y=20260728✓)③QVIX300/50换分钟csv(`b952343f` daily k.csv T+1+才出T日且偶尔卡更[7-29仍停7-27],同源分钟csv vix300.csv/vix50.csv T盘后15:00:32-45即出T日全天intraday,fetchers.py L97-211 _qvix_today_from_min[dropna iloc[-1]取14:56:30值],16:35 backfill即可采到比daily T+1 16:35提前25.5h,线上a_qvix_300=20260728/22.7 a_qvix_1000=20260728/19.7✓)④两融rzhb改08:00+csi_div加21:00(`29939ade` 调研铁证SSE两融T+1早晨发布[非memory误判18-19点,7-27/7-28 19:15连续采不到T日,7-29 07:59才有7-28],rzhb plist 19:15->08:00;csi_div T日晚16:35-02:00间发backfill_evening加21:00槽提前5h;修正index_backfill.py L676 docstring错误注释+backfill_metrics.sh时点注释)⑤schedule_monitor同步plist(`4425366c` 加us_stock_morning 05:00监控+intraday_snapshot schedules同步plist 28时点[26时点10m 9:25-15:05+15:35+20:35,原仅旧15m 18时点]消监控盲区)⑥libmini_racer方案A+C3(`3e0676aa` etf_national_team.py pipeline_intraday_close走ProcessPool[原12只串行]+_run_with_processpool辅助函数[L116-165,BrokenProcessPool重启pool 1次继续剩余仍失败才fallback串行替代faba0f08直接fallback],三处统一调用消除重复,防V8单进程理论SIGTRAP)。**QVIX时点精确化**(agent a4fd5da):澄清a_qvix_1000实际采50ETF波指非真1000波指[真1000 daily源k.csv 2026-03-13后停更4个多月,分钟源vixindex1000.csv全#NAME?];问题1源坏前T+1 16:35稳定采到T日[日志铁证4样本3个T+1 16:35出1个T日20:00出,T+1 02:00全采不到];问题2换分钟csv后T日盘后15:01采到当日[curl -I铁证vix300.csv Last-Modified北京7-28 15:00:45/vix50.csv 15:00:32]。**告警根因修复**(`e6422edf` 用户7-29 08:00/08:15收2封漏跑告警,根因4:①rzhb 08:00漏跑[plist 08:08才改晚于时点一次性明天正常]②us_stock_morning 05:00漏跑[plist 07:52创建晚于05:00一次性明天正常]③futures_backfill log_anomaly[7-28 21:00 deploy.sh rebase撞static-site/data/*.gz二进制冲突abort致push永久失败,已修deploy.sh L290-360 rebase数据冲突自动--theirs=本地最新export+非数据冲突保守abort]④schedule_stats.json没us_stock_morning[gen_schedule_stats.py TASKS漏同步commit 4425366c只改schedule_monitor.sh漏改gen,已补L48-51+L84 LABEL_MAP];2个一次性漏跑明天自愈,2个明确bug已修上线)。**附带memory新记**:cf-workers-large-json-404-r2-fallback(ss.fx8.store对5MB+大JSON返回404,前端dataUrl L2566走R2直链ssd.fx8.store,验证大文件上线curl ssd.fx8.store非ss.fx8.store)。详见NOTES §48 AZ59

**2026-07-29 续19(app.js 3处修复[t0兜底拆分+关键时点1m+小卡角标重绘]+回退1b✓上线)**:今日3项修复全闭环上线+1回退:①修复1a t0兜底拆分(app.js L4124-4137,`getCardTimeBadge` t0兜底分支按场景拆分:盘中dataDate===ptd[T+1性质数据正常]=⏳待盘后更新[t1-pending]/盘中dataDate<ptd[真异常]=⚠滞后[t1-stale]/盘后dataDate<baseline=⚠滞后,删"等盘中刷新或update_all尚未运行"误导文案;ptd在L4060算出t0分支复用;解决ma_alignment/ad_line/volume_ratio/new_high_low/position 5卡片baostock stock_daily盘后才出盘中停T-1被误判⚠滞后)②修复1b回退(`5473bf32`,原实施把5卡片srcClass t0->t1,用户"保证逻辑不变不要只修bug而修bug",回退5卡片保持t0 L6411/6442/6481/6522/6558,走修复1a t0兜底拆分显⏳待盘后更新;t0->t1会改baseline[snapDate->ptd-1]+显示[⏳待盘后更新->📅T+1]+需配T1_COLLECT_DEADLINE违反"逻辑不变")③修复2关键时点1m刷新(`a0b78a18` sw a58,L5118-5136/5217/5346,新增`_INTRADAY_SNAPSHOT_TIMES`[27盘中时点9:25-15:35每10min plist确认]+`_isKeyRefreshMoment`[±2min窗口]+`_overviewRefreshDelay`[关键60s/非关键3min];`_scheduleNextOverviewRefresh`低频兜底delay替换为`_overviewRefreshDelay()`动态返回,debug显示"低频兜底(关键1m)",保留自适应15s高频层,兜底铁律delay最大仍<=3min;解决用户反馈兜底3m太慢别的电脑9:45自己9:35)④修复3小卡角标重绘(L5912-5927,KPI小卡`_badge` const改let+拼装后用临时wrapper解析span打data-badge-date/src/srckey属性[与`addCardTimeBadge` L4139-4141同款命名]+`refreshCardTimeBadges`的.card-time-badge[data-badge-date]选择器能选到KPI小卡重绘+异常badge🚨不打属性避免被重绘成正常badge;根治AZ54 P1-3[commit 4004f231]遗留bug:当时`refreshCardTimeBadges`只覆盖`addCardTimeBadge`大卡路径漏KPI小卡L5878 innerHTML拼接路径[L4147注释自己说"非addCardTimeBadge的badge无data-badge-date不被动"但没意识到KPI小卡就是])。**构建+版本**:`build_min.py`+`bump_asset_version.py`(?v=25ee0e75)+sw.js `CACHE_VERSION` a56->a57->a58(§9铁律1改app.js必bump sw)。**commits**:`a0b78a18`(3修复t0兜底拆分+T+1归位+关键时点1m+小卡角标重绘)+`5473bf32`(回退1b 5卡片保持t0),push feat+main,线上ss.fx8.store+sss.sugas.site验证通过(sw a58+app.min.js?v=25ee0e75)。**主控验收**:grep确认5卡片回t0(L6411/6442/6481/6522/6558全"t0")+修复1a/2/3保留(L4124/L5118/L5912)+sw a58本地线上一致。详见NOTES §48 AZ60

**2026-07-29 续20(usdcnh 7-27验证+bump根治+lab HTML+监控深查3根因+Win通知P2-新-W✅5项全闭环上线)**:今日5项全闭环上线:①usdcnh 7-27验证通过(本地global-all.json extras.usdcnh末值{date:20260727,value:679.11}+线上ssd.fx8.store三源一致,currency_boc_sina主源稳定无需backfill,防复发闭环,TASKS待办标✅)②bump_asset_version.py日期逻辑根治(`7de49686`,关键纠正:a54是sw.js CACHE_VERSION后缀非git commit,20260720是手工误写非脚本bug[原bump只用md5内容哈希无日期逻辑];新增today_version()用ZoneInfo("Asia/Shanghai")显式时区+bump_sw_version()正则同步sw.js日期部分[保留vN/aM幂等]+main()末尾自动调用;单元测试today_version()=20260729;另确认context currentDate 2026/07/20过时真实7-29 CST)③update_lab.sh加第12步simulate_trade --html(`632feb4a`,--output static-site/trade_sim.html指定git tracked路径[默认trade_sim_{index_id}.html被.gitignore走R2],失败不阻塞[echo⚠不exit1],步骤编号[1/11]->[1/12],lab-auto 19:00自动重生;关键决策--output git tracked vs R2:单文件非批量选git tracked部署简单+CF直接服务,批量大文件走R2)④监控异常深查3类根因(①futures_backfill deploy push失败持续1天+:根因旧版deploy.sh rebase撞20+static-site/data/*.json.gz二进制冲突abort+exit1,修复e6422edf已到origin/main+trade-data deploy.sh L306含checkout --theirs[数据冲突取本地最新export]+rebase --continue+重试push,今晚20:05 futures_backfill定时任务自然验证;②美股早采last_run=None:plist 7-29 07:52创建错过StartCalendarInterval Hour=5首触,7-30 05:00自动恢复;③ANOMALY标记:策略实验室已自动消除[eb897914 PUSH_FAIL+PUSH_SUCCESS抑制补丁+intraday重生成]+期货机构持仓随异常①修复消除)⑤P2-新-W PC浏览器通知方案A实施(`4c4be0a8`+merge main `601a9da7`,scripts/export_notifications.py 333行[6类触发:新信号/异常/综合预警/恐贪极值/涨停潮/盘后速递,复用signal_notified/anomaly_notified去重]+app.js~230行[🔔开关initNotifyButton PC显示移动隐藏+requestPermission用户手势合规+localStorage持久化+工具函数showNotification+检测_checkNotifications fetch notifications.json+30s节流+in-flight去重+三层去重:localStorage已读标记+时间窗+Notification tag]+ts:overview-refreshed事件hook _doOverviewRefresh L5262加1行dispatch不改状态机+_NO_CACHE_URLS加notifications绕5min缓存+sw.js a58->a59[铁律1]+index.html ?v=43df0499+线上notifications.json 200;区域限定遵守未碰getCardTimeBadge/兜底刷新两态状态机/小卡角标/addCardTimeBadge)。详见NOTES §48 AZ61

## 总体大纲

A 股 / 港股 / 全球盘后复盘看板。Python 3.11 + FastAPI + SQLite + ECharts，Mac 本地。当前 27 个指标、13 指数、运行在 http://localhost:8000（`--reload`，改文件自动生效，**不要杀进程**）。本轮迭代目标：修回归问题 + 补国债 / 原油白银 / 红利 / A 股十年回溯 / 买卖点优化 / 行业看板 / 概览美化。

相关文件：`REQUIREMENTS.md`（需求 + 实现状态 + §9 变更史）、`NOTES.md`（调研 + 修复史）、`05-回归测试报告.md`（本轮回归）、`01-问题清单.md`（上轮 bug）、`config/indicators.yaml`（指标注册表）、`app/`（采集 + 计算 + API）、`web/`（前端）。

> ⚠ 开工先看 `data/alerts/latest.md` 是否有未处理严重告警，有则优先排查。

## 交接状态（2026-07-21 晚续4，deadcode 清理 + 端到端验锁闭环）

> 收口小节H.3 两条遗留：① L3189/L3192 dead code 清理（远期->已完成）；② update_all 进程互斥锁端到端验证（此前只组件级，本次真跑闭环）。详见 `NOTES.md §48 小节I`。

### ✅ 已完成（2 项闭环，commits 11c9e9e1 + 8839300 端到端验证）
1. **#1 deadcode 清理**（commit `11c9e9e1` + deploy `d8c015ce`）：`app.js` `_KPI_BASE_ORDER` 删两条 dead key：
   - L3189 `a_width_zhaban_rate: 5`（被 L3191 的 13 last-wins 覆盖，5cf9316b 占位 5 + 73848eed 切 13 留下的重复键）。
   - L3191 `a_width_seal_rate: 14`（旧字段，卡片已切 `a_width_fengban_rate: 14`）。
   - 保留活键 `a_width_zhaban_rate: 13` + `a_width_fengban_rate: 14`（第 13/14 位卡片正常显示）。
   - build_min + bump 版本号 `be90399c -> b2a277c7`，deploy.sh 推 `static-site/data/` + `app.min.js`，feat+main 双同步到 `11c9e9e1`。
   - 线上验证：`app.min.js?v=b2a277c7` 生效，grep `zhaban_rate:5`=0 / `seal_rate:14`=0 / `zhaban_rate:13`=1 / `fengban_rate:14`=1 ✅。
2. **#2 端到端验锁闭环**（commit `8839300`，2026-07-20 23:54 真跑通过）：`with_lock.py --nb` fcntl 互斥锁此前只组件级验证，本次真跑 4 场景全通过：
   - 第 1 次占锁（sleep 10）✅ / 第 2 次（`--nb`，锁被占）跳过 exit=0 ✅ / 第 2.5 次（`--nb --on-skip`）跳过+触发回调（打印锁路径）exit=0 ✅ / 第 3 次（锁释放后）成功执行 exit=0 ✅。
   - 生产锁路径 `/tmp/trade_update_all.lock`（`update_all.sh` L39），锁路径是位置参数非 `--lockfile` 选项。
   - `on_skip` 回调 `scripts/on_skip_notify.sh`（发 `notify.py` 邮件 + 写 `alerts/latest.md`，重复跑可见）。
   - 结论：重复跑 update_all 会跳过+通知，无需担心并发撞 `progress.json` 或限流空转。

### 🔄 进行中 / 待验证（承接晚续3）
- ~~**ETF 份额方案 A 零改动 6 天回填**~~：✅ **2026-07-21 验收通过**（commit `d37c2c71`，详见 NOTES §48 小节J）。etf_daily MAX=20260720 / 近 5 日 7-15/16/17/20 各 12 行 / 线上 `overview.json` etf_date="20260720" / 根 `data/` 未 add。
- ~~**ETF ohlc 隐患**（待 7-21 20:07 槽补齐后复查）：凌晨触发 pipeline 时 mootdx OHLC 未采到，7-20 close/amount 为 NULL（ohlc=0）。7-17 数据完整证明正常时点能采到。需 20:07 槽（`scripts/etf_national_team_backfill.sh`）或 17:50 `update_all.sh` 补 OHLC。待办：7-21 20:07 槽跑完后复查 7-20 close/amount 是否补齐。~~ ✅ **2026-07-22 验收通过**（commit `65610d6b` 换 akshare sina 主源 + 7-21 20:07 槽 ohlc=60 补齐；DB 7-17/7-20/7-21 各 12 ETF bad_close=0/bad_amount=0；线上 `overview.json` etf_date=20260721，ss.fx8.store + sss.sugas.site 双站确认；详见 NOTES §48 小节AJ）。
- ✅ **usdcnh 7-27 周一 curl 验证**（2026-07-29 验收通过，详见 NOTES §48 AZ61）：`currency_boc_sina` 主源稳定，本地 `global-all.json` extras.usdcnh 末值 `{date:20260727, value:679.11}`，线上 ssd.fx8.store 三源一致，无需手动 backfill，防复发闭环。

### 🔴 近期
- ~~**ETF 方案 A 验证**~~：✅ 2026-07-21 验收通过（commit `d37c2c71`，详见 NOTES §48 小节J）。
- ~~**ETF ohlc 隐患复查**：7-21 20:07 槽跑完后复查 7-20 close/amount 是否补齐。~~ ✅ **2026-07-22 验收通过**（DB 7-17/7-20/7-21 bad_close=0/bad_amount=0，7-21 20:07 槽 ohlc=60，详见 NOTES §48 小节AJ）。
- ✅ **usdcnh 7-27 周一 curl 验证**（2026-07-29 验收通过）：防复发，确认 `currency_boc_sina` 主源稳定。详见 NOTES §48 AZ61。
- ~~**生产买入信号优化（特买+备买新增）**~~：✅ **2026-07-22 全量上线 + Supertrend 回测审查验收通过**。方案 2026-07-21 定，代码 signals.py L648/654/880 + 生产统计 signal_stats.json + 前端 app.js chip/图例/合规名 + 第一个止损卖过滤（commit 4e515ebe）全上线，等于灰度运行。Supertrend 审查（agent a5207bb15eb95a5c6）：Don20 参数稳健性 7/7 全盈利碾压现有信号 / 生产实绩 sh buy_special win=70.2% pl=2.14 n=506 mean=+6.48% / buy_backup win=68.3% pl=2.31 n=41 mean=+7.20%。agent 建议观察 1-2 个月确认稳定性，详见 NOTES 小节AS。
  - **保留**：主买 C1_RSI30（红色，"红色的超卖拐点"，RSI 上穿30）/ 辅买 B1_BB_lower_revert（玫红色，"玫红色的下轨拐点"，BB 下轨回升）/ 卖 D1_high20_drop5（绿色，20日高回落）。多轮验证低回撤，不推翻。
  - **新增**：特买 Donchian20_up（金色 `#ffd700`，"金色的上轨突破"，唐奇安20日上轨突破，激进战法高回撤高收益）/ 备买 Supertrend_buy（紫色 `#9c27b0`，"紫色的趋势转向"，Supertrend ATR 趋势翻转）
  - **合规命名**：回测口径（指数表现页）保留原名"买点/卖点/辅买"；首页+走势图用合规中文名"[颜色]的[4字技术描述]"（不带"买"字）。前两拐点=均值回归类，后两突破/转向=趋势跟踪类，语义对称。
  - **信号冲突展示**：叠加多色标记（不覆盖，类似汪汪队进出量多色 pin），叠加的特殊 pin 更有价值，覆盖无法体现。
  - **依据**：Donchian20_up 实验室 param_scan robust_profitable 验证过；Supertrend_buy grep 确认在 lab_backtest_*.json 跑过（多指数），robust 性/回撤/收益待审查 agent 报告。
  - **chip 位置**：指数走势图标题旁（最醒目）。重点指数金 chip "备买优势区" / 弱提示指数灰 chip "备买弱势区"。
  - **重点/弱提示清单**：全部展示（4 重点 北证50/中证1000/科创50/中证500 + 5 弱 上证50/沪深300/上证综指/深证成指/创业板），合规性提示（透明告知备买在不同指数表现差异，不藏弱只标强）。
  - **模拟回测弹窗组合**（指数表现 #market tab，`simulate_trade.py` L1286 SIG_LABELS/SIG_TYPES）：单买 4（主买+卖/辅买+卖/特买+卖/备买+卖）+ 双买 6（主买+辅买+卖[现有]/主买+特买+卖/主买+备买+卖/辅买+特买+卖/辅买+备买+卖/特买+备买+卖）= 10 信号组合 × 3 策略 = 30 场景。单买为主、双买辅助；三买/四买远期规划不做。
  - **固定1w(10%) 命题改进**（本次做非远期）：`simulate_trade.py` 策略路径名"买固定1万+卖清仓"->"买固定1万(10%)+卖清仓"，"固定1万进出（FIFO）"->"固定1万(10%)进出（FIFO）"，明确 10 万本金 10%（否则固定1w进出和全仓进出在不知本金时易混）；全仓进出不变。
  - ✅ **实施已完成上线**（commits `2c9b6caa` 阶段1-3 signals.py 加 Donchian20_up+Supertrend_buy + `7d2f5d70` 阶段4 前端五色展示/chip/legend/叠加标记 + `89f8e3c7` simulate_trade 保留 Donchian 止损场景 + `ca4215f7`/`3853a8b9` docs 落档，详见 L123 父条目 2026-07-22 全量上线验收）：signals.py L1012-1096 Donchian20_up(close>max(high[-20:-1]))+Supertrend_buy(ATR10×3 翻多)计算 + L754-755 buy_special/buy_backup detail + L1204-1211 游标扩展 + simulate_trade.py 6 新组合 + 策略路径名改(10%) + 收盘跑 simulate_trade.py --all 重生成 HTML。
  - **阶段计划**（2026-07-21 定，a7e0b2 报告后补充细化行号）：
    - 阶段1 后端 `signals.py`：加 Donchian20_up（close>max(high[-20:-1])）+ Supertrend_buy（ATR(10)×3 翻多）计算，L279 return 扩展输出 buy_special/buy_backup，落 signal_daily（signal 字段字符串不加字段）
    - 阶段2 `signal_stats.py` + `check_signals.py`：加 buy_special/buy_backup 统计+去重+邮件通知
    - 阶段3 `intraday_snapshot.py` L895：_recompute_signals 调 signals.compute() 自动覆盖，不需改
    - 阶段4 前端 `app.js` L267-292 + `index.html` + `style.css`：signalColor/signalLabel 加 buy_special 金#ffd700"上轨突破"/buy_backup 紫#9c27b0"趋势转向" + 4色买点pin叠加（参照汪汪队进出量）+ 走势图标题旁chip（9指数硬编码，4重点金/5弱灰）+ 图例说明+备买tooltip风险提示
    - 阶段5 `simulate_trade.py` L1286：SIG_LABELS/SIG_TYPES 加6新组合（10组合×3=30场景）+ 策略路径名改(10%) + 收盘后跑--all重生成94HTML
    - 阶段6 `lab.js` 命名统一（独立先做）：6必改（name×5+tooltip×5+shortName+PARAMSCAN_RULE）+3trigger可选+3prod归类（BB_lower_revert zone/status+LAB_ZONES count 2->3，特买备买上线后3->5）
    - 阶段7 数据上线+验证：跑历史信号回填+deploy.sh推数据+收盘跑simulate_trade.py --all+线上验证
    - **并行规划**：阶段6（lab命名）独立先做和阶段1-3（后端）并行；阶段4+5依赖阶段1；阶段7依赖1-6

### ✅ 2026-07-20 买点信号净化调研（R1/R2 已实施上线 2026-07-21/22；R3 保持现状 / R4/R5 远期研究保留）

> 详见 `NOTES.md §48 小节AB`。回测脚本 `/tmp/buy_purify_backtest.py`，结果 `/tmp/buy_purify_results.json`。基于 2016-2026（10.5 年）90 指数 13900 条买点信号回测。**核心结论**：净化能小幅拉高综合收益率（+14% 均值）但非稳态；趋势类高位过滤方向对但被 buy_special regime 依赖性拖累；均值回归类 pct 高位反而是最佳信号不应过滤。

- ✅ **R1（已实施上线 2026-07-21，升级为更强 B4_hold5d 方案，非原 buy_backup MA60 过滤）**：原 R1 计划对 **buy_backup** 加 `close/MA60 >= 1.15` 过滤（年度稳定 5.7% 滤率 10d +4%）；**实际升级为对 buy_special 加 B4_hold5d 过滤**（stateless 延后触发，覆盖更全面）。实施点：`app/compute/signals.py` L692/L712 `buy_special_filt = donchian20_up_shift5 & b4_hold5d_confirm`。原 buy_backup MA60 过滤未单独采用
- ✅ **R2（已实施上线 2026-07-22，多层叠加真过滤，绕过 regime 难题）**：原 R2 担心 2025 regime 依赖性（净化后 -1.11%）需先建 regime 识别；**实际通过多层叠加绕过 regime 难题**，3 层已上线：① h5 平衡档真过滤（R2 = C + C12 + E2 + 量价背离收紧，commit `02b477d6` + `531ff532`，signals.py L729/L779 `((dev_ma60 > 1.20) & (atr_pct > 0.03))` C 现状）② buy_special 降回撤过滤方案 B + sh 豁免（`atr_pct>=2.5% OR dist_from_low60>30%`，commit `bf373f5e`）③ 第三层 peak_dd_filter_mask 叠加（signals.py L838-843 `buy_special_set` 排除命中日）。详见 NOTES §48 小节 AT/AU/AV
- **R3（不推荐，保持现状）**：对 **buy/buy_aux** 加 pct_rank 过滤。buy 的 pct high 桶 +2.31%/pf 3.47 是最佳（pullback in uptrend），过滤会误杀最佳信号使收益反向
- **R4（远期研究）**：调查 2025 buy_special 高位反超根因 + regime 识别指标（趋势市/震荡市判断），赋能 R2 自适应过滤
- **R5（远期研究）**：当前过滤误杀率 53%（删除组超半数是赢家），本质"非选择性删除"。研究更选择性指标（量价配合/cross 软分级/行业景气）替代简单位置过滤
- **验收数据**（主控逐字复算口径）：
  - 4 类买点 2016+ 总数：buy=2474 / buy_aux=3314 / buy_special=7095 / buy_backup=1017，合计 13900
  - buy_special 占比 51.0%（最频繁，确认用户假设），年均 675 次
  - 10d 基线：buy +1.11%/pf 1.57 / buy_aux +0.37%/1.18 / buy_special +0.61%/1.36 / buy_backup +1.60%/2.26
  - MA60 high 桶 vs mid 桶 10d 均值：buy_special +0.23% vs +0.71%（high 差 68%）/ buy_backup +0.85% vs +1.53%（high 差 44%）
  - buy pct high 桶 vs low 桶 10d 均值：+2.31% vs +0.94%（high 反而好 2.5x，pct 过滤反向）
  - 趋势类 conservative 净化（仅 TF 过滤，MR 不动）：10d +0.72%->+0.82%（+14%），pf 1.40->1.45，filter 36.1%
  - buy_special pct_only_bal 2025：基线 +1.73% -> 净化后 +0.62%（**-1.11%，最大样本年反向**）

### 🆕 2026-07-21 盘中事故后续根治（intraday 覆盖 + 国家队 mootdx 失效）
> 今日盘中修复 3 事故（均已临时修复上线），根治待办防复发。详见 NOTES §48 小节X+Y（已落档，9 根治项 8 闭环 1 遗留 A1）。
- **intraday 事故根治**（commit 94c79041 方案Y deploy 12:29 午休违规，deploy.sh 通配带入工作区 17:55 旧版覆盖 main 的 11:30 实时版；已 commit 64d43f8d/a6d86178 恢复 7-21 实时）：
  1. ~~trade/data/sentiment.db 改 symlink 指向 trade-data DB~~ ✅ 2026-07-22 实施（symlink -> trade-data/data/sentiment.db，collected_at=11:30:06 对齐 trade-data，WAL/SHM 不存在，备份 sentiment.db.bak.20260722，intraday 13:00 写 trade-data 不受影响，详见 NOTES §48 小节AK）
  2. ✅ **deploy.sh 跑前恢复 intraday_snapshot.json/.gz 到 origin/main 版**（已闭环 2026-07-21，commit `c5e2b7ae` L47-52：`git checkout origin/main -- intraday_snapshot.json/.gz` + `reset HEAD` unstage，清工作区残留防通配带入，§8 警告根治）
  3. ✅ **deploy.sh 加时段闸门**（已闭环 2026-07-21，commit `c5e2b7ae` L32-42：交易日盘中 09:30-15:30 拒跑全量 export+deploy，`IS_TRADING` + `CURRENT_HM` 检查，force 参数绕过，类似 intraday_snapshot.sh IS_TRADING 闸门）
  4. ✅ **intraday_snapshot.sh git add 补加 .gz**（已闭环 2026-07-21，commit `3796ecf3` L133-136：原只 add .json 不 add .gz 致 .gz 仍旧版，补 `intraday_snapshot.json.gz` + `schedule_stats.json.gz` + period 通配 `.gz`，参照 59cffecb 7-22 通配补 period .gz）
  5. ✅ **rsync -a -> --checksum 根治 schedule_stats.json quick check 跳过**（2026-07-22，commit 7d9c3c99，详见 NOTES §48 小节AN）：intraday_snapshot.sh L116 + deploy.sh L100 改 `rsync -a` -> `rsync -a --checksum`，强制 MD5 比对根治 quick check 误判（schedule_stats.json last_run "11:30"->"13:05" size 不变+mtime同秒，quick check 跳过拷贝致 worktree 旧版 commit 不含线上执行统计停滞）。trade+trade-data 两版本同改（launchd 跑 trade-data 版本）。deploy.sh L114 DB 同步(--exclude=logs/)不动（sentiment.db 80MB --checksum 开销大+size 每次变）。
- ✅ **mootdx 失效影响范围评估**（已闭环 2026-07-22，4 文件全处理）：① `runner.py` 加 `signal.alarm(1800)` 30min 超时保护防 SIGTERM 阻塞复发（commit `ff250d87`，NOTES §48 小节AL）；② `mootdx_daily.py` 内置 `consecutive_fail_limit=50` 触发后自动切 baostock fallback（commit 历史已具备）；③ `industry_width.py` 用 `mootdx_daily_raw` 表，间接受 baostock fallback 保护；④ `width_history.py` 加 `MIN_CODES_PER_DAY=1000` 保护防残缺样本覆盖正确值（commit `f8897621`，NOTES §48 小节AQ）。原 ETF 国家队已换 akshare fund_etf_hist_sina（commit `65610d6b`）。A 股 tab 有 baostock 兜底正常
- **换源后须同步 `gzip -kf` 补 .gz**（教训：fetchJSON .gz 优先 + DecompressionStream，只生成 .json 不更新 .gz 致线上读旧 .gz 仍显 0）
- **static-site/data/a-stock-*.json 残留 M 确认**：下次 deploy 前确认工作区无旧版残留（94c79041 事故根因再现）
- ✅ **memory MEMORY.md 清理过时条目**（已完成 2026-07-22，commit `84815d3d`，19->18 条：删 trade-sim-time-window 指向不存在文件 + 更新 trade-sim-chip-three-tier hook）：原 ~40 条索引（实测 ~19 条），有些已完成（如"已100%上线"指针）可删，减少每次注入 context token

### 🟢 远期 / 搁置
- ~~**L3189 `zhaban_rate:5` dead code 清理**~~：✅ 已清理（commit `11c9e9e1`，2026-07-21，详见 NOTES §48 小节I.1）。L3192 `a_width_seal_rate:14` 同类一并清理。
- ~~**端到端互斥验证**~~：✅ 已验证（2026-07-20 23:54，`8839300` 真跑 4 场景全通过，详见 NOTES §48 小节I.2）。
- ~~**C7 P4 交互式自定义分析**~~：✅ 已完成（2026-07-21，commit a241d1f1 后端 + 9a0648cb 前端，8+8 维度+历史类比 Top3+55 静态 json，线上 #lab?sub=custom，详见 NOTES §48 小节L）。
  - ~~**market 融合全 55**~~：✅ 已完成（2026-07-21，commit 75a67d03，`_labCustom*` 10 函数+2 常量抽到 common.js 348 行，app.js `_MARKET_ANALYZE_IIDS` 55 白名单+分数卡+3 调用点，alert_match.py PREGEN_TARGETS 40->55+15 新 JSON，详见 NOTES §48 小节M）。
  - ~~**select 检索**~~：✅ 已完成（2026-07-21，commit 644009b7，lab.js selector 加检索 input+oninput 筛选代码/名称+optgroup 无可见子隐藏+无匹配提示，isSwitch/onchange 清空恢复，style.css `.lab-custom-search` 3 皮肤，不破闪烁修复，详见 NOTES §48 小节N）。
  - ~~**select 扩 55**~~：✅ 已完成（2026-07-21，commit 6106d556，common.js 新增 `_LAB_CUSTOM_DIV`(3 红利)+`_LAB_CUSTOM_HK`(3 港股)+`_LAB_CUSTOM_GLOBAL`(9 全球) 3 常量+挂 window，lab.js select 加 3 新 optgroup(红利/港股/全球指数)+3 处 hint 计数扩 5 常量求和，15 新 iid 名称对齐 app.js `_INDEX_NAME_MAP`+global-all.json，不破闪烁修复/检索/不动 `_labCustom*` 函数，跳过 deploy.sh 自行 commit+push feat+main，详见 NOTES §48 小节N 补充）。
  - ~~**human_text 中性档拼接命中维度**~~：✅ 已完成（2026-07-21，commit b28aa6ac + be3bd749，`build_human_text` 中性档（总分<=60）若 dim_hits 有单维度命中（>=60）拼接 `H1 情绪过热/H4 位置偏高 有命中,整体加权后未达关注线`，避免用户困惑"显示中性但维度表有命中"。55 JSON 重生成（HIGH 中性+命中43/LOW 中性+命中27），关注/过热档不变，线上 hsi 验证通过，详见 NOTES §48 小节Q）。
  - ~~**阈值统一方案A**~~：✅ 已完成（2026-07-21，commit fc155ff1 + a8d42e30，`DIM_THRESHOLDS` H1/H4/L1/L3 threshold 80->60 全表 16 维统一 60，消除主表 dim_hits（HIT_THRESHOLD=60）与折叠表 data_thresholds（H1/H4/L1/L3=80）展示冲突（H1=71.79 主表✓命中 vs 折叠表✗未命中）。纯展示层不碰算法（high_alert 走 _weighted_score 不引用 DIM_THRESHOLDS）。55 JSON 重生成，6 个 H1/H4/L1/L3 value in [60,80) hit=True 验证生效（旧 80 下 False），线上 hsi H1 threshold=60 hit=True / cyb H4 value=73.81 threshold=60 hit=True 验证通过，详见 NOTES §48 小节R）。
- **P2-5 app.js/lab.js 拆 chunk**：远期性能，现 CF br 压缩+defer 后可接受。
- **百度推送效果验证**：搁置（用户 2026-07-14 定），后续有需要再启。**2026-07-22 删 HTTP 百度推送（push.zhanzhang.baidu.com）修 mixed content，保留 HTTPS zz.bdstatic.com，见 NOTES §48 小节AE**。
- **trade_sim 迁 R2**：✅ 2026-07-20 评估=不迁（小节G），**2026-07-22 反转=已迁 R2**（s.sugas.site 瘦身需要，97 文件 200M，见小节AK）。**2026-07-22 upload_r2.py Content-Type 根治（octet-stream -> 按扩展名推断），trade_sim/index/industry 重传 R2，curl 验证 text/html，见小节AP**。
- **data JSON 迁 R2**：✅ 阶段1+2+3 全完成（2026-07-22，index/industry/trade_sim 迁 R2，remote 523M->158M 解 s.sugas.site 超限恢复部署；剩裸 JSON .gz 后续按需，详见 NOTES §48 小节AK）。

### 下轮起点
- ~~7-21 收盘后验证 ETF 方案 A 6 天回填是否自动补 7-20 数据。~~ ✅ 2026-07-21 验收通过（commit `d37c2c71`，etf_daily MAX=20260720，详见 NOTES §48 小节J）。
- ~~ETF ohlc 隐患复查：7-21 20:07 槽跑完后复查 7-20 close/amount 是否补齐（凌晨 mootdx OHLC=0，需 20:07 槽或 update_all 补）。~~ ✅ **2026-07-22 验收通过，待办关闭**（commit `65610d6b` 换源 + 7-21 20:07 槽 ohlc=60 + 7-22 02:00 backfill 同 ohlc=60 稳定；DB 7-17/7-20/7-21 各 12 ETF close/amount 全非 NULL 非 0；线上 etf_date=20260721，详见 NOTES §48 小节AJ）。
- ✅ usdcnh 7-27 周一 curl 验证防复发（2026-07-29 验收通过，详见 NOTES §48 AZ61）。
- R2 P0/P1 已全闭环，P2 data JSON 迁 R2 阶段1+2+3 全完成（2026-07-22，remote 523M->158M，s.sugas.site 恢复部署，详见小节AK）。
- C6 预警条已上线，下步观察线上预警准确性。P4 交互式分析已上线（#lab?sub=custom，详见 NOTES §48 小节L）。
- deadcode + 验锁两条小节H.3 遗留已闭环（晚续4），无遗留。

---

## 工作约定（子进程必读）

1. **领任务**：读本文件，找第一个 `状态: pending` 且 `依赖` 已满足的任务，把状态改 `in_progress`、填 `负责人`（你的标识）。
2. **干活**：按 `描述` 做，达到 `验收标准`。改动前先读相关源码。技术细节自己定；**碰到方向性分叉不要猜——停下、在 `结果备注` 写明、汇报给监管**。
3. **写结果**：做完（或失败）后在 `结果备注` 写：改了哪些文件、做了什么、成功 / 失败、遗留问题。状态改 `done` / `failed` / `blocked`。
4. **汇报**：你的最终消息就是汇报。说清：做了什么、改了哪些文件、验收标准是否达成、有无遗留、下一步建议。
5. **环境约束**（踩过的坑）：
   - pypi / github 用清华镜像；Clash 代理 `127.0.0.1:7890` 拦截东财 → 全局 `trust_env=False`。
   - 东财 push2 / clist / 板块端点反爬封 → 用 sina 源或直爬 + `em_get` 防封（1s 节流 + 0.1-0.5s jitter + HTTPAdapter Retry 429/5xx）。
   - 手动值保护：upsert 的 `ON CONFLICT DO UPDATE` 末尾必须 `WHERE daily_metric.source != 'manual'`（防日采集覆盖手动补录）。
   - NaN 过滤：`collect_series` 里 `if v != v: continue`（`float(NaN)` 不抛异常，必须显式判）。
   - 不要 `cd` 进 compound 命令（用绝对路径）；不要 commit / push（用户没让）。
6. **验收（2026-07-06 调整）**：监管**不自己跑命令验收**（curl/grep/DB 在监管上下文费 token）。改派**验收子进程**（fresh context）跑抽查（DB/curl/复跑/语法），结论写进任务条目「验收备注」+ 向监管汇报。监管读干活汇报 + 验收汇报决定放行。review gate 任务必派验收子进程；非 review gate 可省（信任干活子进程自验）。不暂停等用户，全部完成或卡住才通知。最终用户 + 外部测试整体验收。详见记忆 `supervisor-loop-mode`。
7. **测试**：API 改动用 `curl localhost:8000/...` 验；采集改动跑 `python -m app.collector.runner`；计算改动跑 `python -m app.compute.runner`；前端改动浏览器看。


---

> 22 任务清单（A1/A2/A3/G1/E1/E2/E3/B1/C1/B2/F1/F2/F3/D1/D2/D3/S1/SignalStats/B1S1/HomeSignalGrid 等）+ 进度看板 + 2026-07-13/14/19/20 各轮交接状态已归档到 [docs/archive/TASKS-done.md](docs/archive/TASKS-done.md)。

---


## R2优化+备份方案待办（P0+P1 已全闭环 2026-07-20；P2 data JSON 迁 R2 阶段1+2+3 全闭环 2026-07-22，详见 NOTES §48 小节A+AK）

> 2026-07-15 晚调研，2026-07-20 实施 P0×3 + P1×3 全闭环。.git gc 后 136M（原 1.1G）。DB 压缩实测最优 .dump+gzip 13.8MB(17%)，线上用 .db.gz 24MB(29%)。

### P0（✅ 全 3 条已完成 2026-07-20）
1. ✅ **DB备份压缩改传 .db.gz**（1a573c00）：87MB->24MB 省72%（backup_db.sh 产 .db.gz + upload_r2.py 上传压缩二进制）
2. ✅ **R2 清理改脚本侧分层替代 Dashboard lifecycle**：未配 Dashboard 规则，改 upload_r2.py `_prune_r2_backup` 三层清理 backup/30+weekly/28+monthly/365（更可控，不依赖手配）
3. ✅ **backup 失败邮件告警**（1a573c00）：复用 notify.py（backup_db.sh 失败发邮件，原仅日志无告警风险消除）

### P1（✅ 全 3 条已完成 2026-07-20）
4. ✅ **恢复演练 verify_backup.sh**（500b7338）：R2 拉备份解压 integrity 校验+行数对比，只读不改生产 DB
5. ✅ **R2 多版本保留分层**（0c22524f）：日30天+周4周+月12月（_maybe_upload_weekly/monthly 复用日 payload，ISO week/year+month，节假日顺延）
6. ✅ **git gc**：.git 1.1G->136M（松散925MB 未 gc 积压清理）

### P2（按需）
7. ✅ **trade_sim HTML 52MB 迁 R2**：2026-07-20 评估=**不迁**（小节G），**2026-07-22 反转=已迁 R2**（s.sugas.site 瘦身 523M->158M 需要，97 文件 200M git rm --cached 保本地 untracked，commit b4b75671，见小节AK）。
8. ✅ **data JSON 迁 R2（阶段1+2+3）**：2026-07-22 全完成。阶段1 R2 上传(trade_sim 97+index 180+industry 268，CORS *)+阶段2 前端改读 R2(app.js 4处+lab.js 3处，commit f145a409，app.min.js?v=b4eaf1ec)+阶段3 线上瘦身(commit b4b75671 git rm --cached index/trade_sim 保本地 untracked+.gitignore L63-65+intraday L131 改 no-op，remote 523M->158M < 300M，s.sugas.site 恢复部署 v=b4eaf1ec tooltip 颜色根治)。STATIC_DIR fix a0ba8431。剩裸 JSON .gz 后续按需。详见 NOTES §48 小节AK

### skip（调研后排除）
- 增量备份：压缩后全量仅24MB，收益锐减
- WAL 改造：已在线热备（backup_db.sh `.backup`），最佳方案无需改
- R2 扩容：700MB 远在 10GB 免费额内

## 全站性能优化待办（2026-07-21 扫描，详见 NOTES §48 小节O）

> 10 维度扫描 s.sugas.site（MaoziYun/3.17.0 静态托管，非 CF，_headers 不生效）。最大痛点 = MaoziYun 零压缩 + 不读 _headers，全站 JS/CSS/JSON 全裸传。完整报告留底 `/tmp/perf-report-full.md`，扫描原始数据 `/tmp/agent-progress-perf-scan.md`。本次只扫描+落档不改码。

### P0（最影响首屏）
1. **零压缩 - 全站无 Content-Encoding**：MaoziYun/3.17.0 不做 gzip/br，JS/CSS/JSON 全裸传。首屏 ~466KB gzip 可降到 ~140KB（省 70%+），echarts 629KB 可降到 ~180KB。
   - ~~根治方案：迁 CF Workers（wrangler.jsonc 已存在）自动 br 压缩，工作量 M（迁移+测试+域名切流）。~~ ✅ **2026-07-22 闭环**：ss.fx8.store `server: cloudflare` 上线，push main 触发 CF 构建环境自动 wrangler deploy（无需本地 wrangler），`content-encoding: br` 生效。验收证据 + 完整闭环见 NOTES §48 小节AR。
2. **大 JSON 无压缩传输** ✅ 已完成（commit eea226f3 + 0b3082f1，2026-07-21，方案B：MaoziYun 不支持 Content-Encoding，前端 DecompressionStream 显式解压，244MB->32MB 省 86.9%）：data/ 244MB / 396 文件全裸传。industry-3y.json 9.6MB / etf_national_team-all.json 8MB / a-stock-all.json 6.9MB，切 tab 等待 1s+。
   - 实施方案：export.py `write_json` 加 .json.gz 输出（>100KB）+ scripts/export_alert_analyze.py 全量 .json.gz + 前端 fetchJSON/fetchJSONProgress 优先 .json.gz + DecompressionStream 解压 + 失败 fallback .json + 3 处直连 fetch alert_analyze 改用 fetchJSON。详见 NOTES §48 小节S。
   - 原"缓解方案：export.py 产 .json 同时产 .json.gz + deploy.sh 上传双份按 Accept-Encoding 选"调整：MaoziYun 不按 Accept-Encoding 选（不支持 Content-Encoding），故走前端显式解压方案B 而非服务器自动选 .gz。

### P1
3. **style.css/lab.css 未 minify** ✅ 已完成（commit ada602e0，2026-07-21，rcssmin 1.2.2，style.css 133KB->97KB 省25.5% / lab.css 57KB->44KB 省23.1%，index/about/privacy 引 .min.css?v=新，线上 s.sugas.site 验证 HTTP 200 + content-length 一致）：原 `scripts/build_min.py` 只处理 JS 不处理 CSS，index.html 直接引非 min 版。
   - 扩 build_min.py 加 CSS minify（rcssmin 1.2.2 纯 Python），产 style.min.css/lab.min.css，index.html 改引用 + bump 版本号，工作量 S（立即可做无需迁站，优先推荐）。**实测压缩率 23-26%（非预估 70-80%：CSS 注释+空白仅占 20% 无 data:URI，rcssmin 不改规则保视觉一致，70%+ 是 JS mangle 水平不适用 CSS；更高压缩需迁 CF br 压缩 P0 项）**。详见 NOTES §48 小节P。
~~4. **缓存策略弱**：所有资源统一 max-age=1200，版本化资源（app.min.js?v=）应 max-age=31536000 immutable。迁 CF 后 _headers 加 `/*.min.js`/`/*.min.css` -> immutable，工作量 S（MaoziYun 不读 _headers 暂无效，迁 CF 后落地）。~~ ✅ **2026-07-22 闭环**：CF Workers 主站上线后 _headers 全生效，curl 验证 `app.min.js` 返回 `cache-control: public, max-age=31536000, immutable`（`/style.css` /`/app.min.js` /`/lab.min.js` /`/lab.css` /`/qr.js` /`/vendor/*` 均配 immutable，见 `static-site/_headers`）。详见 NOTES §48 小节AR。
~~5. **缺 ETag**：仅 Last-Modified 无 ETag 精细化缓存验证（迁 CF 后自动补）。~~ ✅ **2026-07-22 闭环**：迁 CF Workers 后 static assets 由 CF 托管，curl 验证 `app.min.js` 返回 `etag: W/"728ad74e7c4605dd879c90ee36f2c796"`（CF 标准行为自动生成）。详见 NOTES §48 小节AR。
6. **echarts 629KB vendor**：虽已动态加载（P2-5 闭环见 NOTES §48 小节K），单文件仍大。换 echarts core + 按图表类型 import（line/bar/pie/scatter/candlestick 等）可降到 ~200KB，工作量 M（需测图表类型覆盖有回归风险）。

### P2
7. ✅ **lab.css 首页强加载**（已完成 2026-07-22，commit `ff1bfe04`，改 preload 异步加载 + noscript 兜底，省 44KB 首屏阻塞）：原 57KB render-blocking，仅 lab tab 用。原计划改 preload 或按 tab 切换加载，工作量 S 收益小（CSS 已 max-age=1200 缓存）。
8. ✅ **HTML 内联 script 较多**（已完成 2026-07-23，commit `41c0f8a7`，4->1 只剩 theme 防闪烁保守保留）：原 index.html 有 3 个内联 `<script>` 块（hm.baidu/navSticky/zz.bdstatic），已外部化到 `inline-init.js`（defer 统一引用）。theme 防闪烁 script 保留为内联（避免 FOUC 闪烁，保守不外部化）。
~~9. **无 CSP/X-Frame-Options/Permissions-Policy**：_headers 不生效，迁 CF Workers 后落地（CLAUDE.md §8 已记）。~~ ✅ **2026-07-22 闭环**：CF Workers 主站上线后 _headers 全生效，curl 验证 `content-security-policy-report-only`（CSP）/ `strict-transport-security: max-age=63072000; includeSubDomains; preload`（HSTS preload）/ `x-frame-options: SAMEORIGIN` / `permissions-policy: camera=(), microphone=(), geolocation=(), payment=(), usb=(), accelerometer=(), gyroscope=()` 全部返回。详见 NOTES §48 小节AR。

### 优先级建议
P1/S CSS minify ✅ 已完成（小节P）-> P0/M data JSON 预压缩 ✅ 已完成（小节S，方案B 前端 DecompressionStream 显式解压）-> ~~P0/M 迁 CF Workers（根治零压缩+解锁 _headers 全部能力：immutable 长缓存+CSP+ETag+X-Frame）~~ ✅ **2026-07-22 闭环**（ss.fx8.store `server: cloudflare` + `content-encoding: br` + `cache-control: immutable` + `etag` + CSP/HSTS preload/X-Frame/Permissions-Policy 全 curl 验证返回，详见 NOTES §48 小节AR）。

### skip（扫描后排除）
- HTTP/2：已启用 ✓
- HSTS：已启用 ✓（max-age=63072000）
- TTFB：<300ms 可接受（日本节点 cf-ray NRT）
- og.png：60KB 已优化（2026-07-16 67->36KB 256色压缩）
- fetch 冗余：仅 6 次无严重冗余（app.js 4 + lab.js 2 + common.js 0）

---

## 🆕 2026-07-21 全站深度审计（3 agent 报告综合，等用户看后安排修）

> 用户要求"对全站功能全面深度重新检查，看异常/待验证/未发现/误报，改软链后计划任务是否正常"。派 3 background agent：性能+部署（ac225cfc5a50ad58c）/ 计划任务（a6e223adab14a5170）/ 功能（a93a577a3e79a695f）。3 报告全收齐，主控逐字验收关键结论（.gz 滞后 curl 属实）。**不擅自动修，等用户看后安排**。

### P0（线上正在发生/高影响）
1. ✅ **.gz 滞后致前端读旧数据**（已闭环 2026-07-21，commit `d3e6bf8f` P0-1 + `59cffecb` 7-22 通配补 period .gz）：原 overview/summary/schedule_stats/hk-1y/sentiment-all 线上 .gz 滞后 1-12h 到 4 天，前端 fetchJSON .gz 优先（app.js L841-849 DecompressionStream 显式解压）读旧数据。
   - 验收：线上 overview.json.gz collected_at **02:05:50** vs overview.json **14:35:06**（滞后 12.5h）；summary.json.gz **7/20** vs .json **7/21**；schedule_stats.json.gz **7/16** vs .json **7/20 17:50**（est 15分钟旧文案）
   - 根因：intraday-snapshot 定时任务（trade-data 跑）更新 .json 不生成/推送 .gz；全量 deploy（02:06 export.py GZ_THRESHOLD=0）才生成 .gz。盘中 .json 更新到 14:35，.gz 停 02:05
   - 修复：intraday-snapshot.sh 补生成 overview/summary/hk-1y/sentiment-all/schedule_stats 的 .gz 并 push（参照 3796ecf3 修 intraday_snapshot.json.gz 做法）。**盘中改定时任务脚本撞正在跑实例有风险，等收盘后修**（已修，d3e6bf8f 收盘后落地）
2. ✅ **lab/ 65 JSON 缺 .gz**（已闭环 2026-07-21，commit `d3e6bf8f` P0-2 `export.py` 批量 gzip glob->rglob 递归扫 lab/ 生成 65 个 `lab/*.json.gz`，94MB 未压缩->全量 .gz 上线）

### P1
3. ✅ **全球指数滞后 4 天**（已闭环 2026-07-21，commit `50663a42` P1-3 + `76f71935` rebase 7/20 数据回填）：`app/collector/index_backfill.py` 加 5 全球指数（nikkei225/kospi/ftse100/dax/cac40）到 `HK_GLOBAL_INDICES` backfill 列表，`require_today=False` 用 >3 天阈值覆盖源延迟（sina T+1）+ 跨周末，避免误报 fail。实测 `global-1y.json` gold/oil/wti_oil date=20260722 已更新到 7-22，详见 NOTES §48 小节Z
4. ✅ **两融滞后**（原"已闭环 2026-07-22"结论作废，2026-07-29 真正根治）：原 memory 判"SSE 两融 18-19 点发布"是误判，调研铁证 SSE 两融 T+1 **早晨发布**（7-27/7-28 19:15 连续采不到 T 日数据，7-29 07:59 才有 7-28 数据）。2026-07-29 rzhb plist 19:15->08:00 真正根治（commit `29939ade`）。详见 NOTES §48 小节AD（旧闭环）+ AZ59（真正根治）
5. ✅ **mootdx_daily.db 加 .gitignore**（已闭环 2026-07-21，commit `d3e6bf8f` P1-5）：`.gitignore` 已加 `data/mootdx_daily.db` + `-wal` + `-shm`，`git ls-files` 确认未追踪，类比 sentiment.db / etf_national_team.db（§10），防切分支污染已根治
6. ✅ **trade vs trade-data 不同步**（已闭环 2026-07-22，commit `ff1bfe04`，根因 = `export_alert.py` L27 + `export_alert_analyze.py` L31 的 `.resolve()` bug 解析 symlink 跳回 trade，改 `.absolute()` 根治；线上不缺：git add 通配仍 commit，alert.json + alert_analyze_hs300.json curl 200）：原观察 trade-data 缺 alert*.json / alert_analyze*.json ~80 个（trade 上 lhb_backfill 等生成未 rsync 回）。deploy.sh rsync 不带 --delete，trade 数据不丢，但 trade-data 采集端不完整
7. ✅ **lab 数据滞后 11 天**（已闭环 2026-07-22，commit `94b6cdde` P1-7b update_lab.sh 补 5 步 + `c49bb6d8` lab.js line2649 去掉 '2026-07-11' 硬编码兜底改动态显示）：根因 = `update_lab.sh` 漏跑 `lab_retest_honors.py` + 4 个顶层脚本（lab_ablation/cost_compare/param_scan/short_symmetry），致 lab_retest_honors.json 停 7/17 + 顶层 4 文件停 7/17。已补 5 步后每日自动刷新，实测 `lab_backtest_*.json` generated_at/data_cutoff=2026-07-22 已是最新。仍待用户决策更新策略（每日/按周/按需，离线回测性质非每日必须，但当前每日跑）

### P2
8. ✅ **deploy.sh L186 文案修正**（已修 commit 0304e4ef）：改"MaoziYun 自动拉取 git main 部署，有拉取延迟 + max-age=1200 缓存；wrangler 未安装，worker/headers.js 待迁 CF Workers 后手动 wrangler deploy" ~~（"wrangler 未安装待手动 deploy" 已过时）~~ ✅ **2026-07-22 更正**：push main 触发 CF 构建环境自动 `wrangler deploy`（内置 esbuild bundle `worker/headers.js`），**无需本地安装 wrangler**；headers.js 通过 `_headers` 已生效，curl 验证 CSP/HSTS preload/X-Frame/Permissions-Policy 全返回。详见 NOTES §48 小节AR。
9. **app.js/lab.js 拆 chunk**（P2-5 待办，已评估不实施）：app.min.js 252KB / lab.min.js 206KB 单文件。评估结论：拆 chunk ROI 低（4-5 工作日+高回归风险），已有 lab.js 懒加载+echarts 懒加载+defer 足够；~~真正瓶颈是 MaoziYun 不压缩 JS（实测 252KB raw 传输，本地 gzip 仅 77KB），应优先迁 CF Workers（wrangler.jsonc 已存在）一举解决压缩+_headers+CSP。~~ ✅ **2026-07-22 迁 CF Workers 已闭环**（ss.fx8.store `server: cloudflare` + `content-encoding: br` 生效，"MaoziYun 不压缩 JS" 前提已消除；拆 chunk 仍不实施，ROI 低）。保留远期待办，详见 /tmp/agent-progress-p2.md

### 误报/澄清（不需修）
- **summary zt_count 0 非误报**：intraday_snapshot 无 zt 字段，summary zt_count=0 是盘中快照未填。实际涨停在 a-stock metrics a_width_zt_count=85（7/21）/跌停 19
- **龙虎榜/两融无独立 tab**：项目无此功能（grep + ls 均无 lhb/rzhb/margin 文件），两融仅在 a-stock metrics a_fund_margin 内
- **ETF 扩展到 12 个**：prompt 假设 9，实际 12（新增 510310/159919 等），非异常是扩展
- **backfill-evening exit 1**：7-18 历史残留，8b76b6b4 已修 backfill_metrics.sh SyntaxError
- **工作区 223 个 M 文件**：7-21 最新数据（HEAD 是 7-20 旧版），非旧版残留，**不需清理**（清理反丢 7-21 数据）
- **性能审计"CF 缓存 20 分钟"误判**：s.sugas.site 走 MaoziYun 非 CF（CLAUDE.md §8），intraday 盘中被缓存 20 分钟是 MaoziYun max-age=1200 已知现状，非 CF
- ~~**worker/headers.js 未部署 = 安全头缺失**：已知现状（CLAUDE.md §8 已接受，MaoziYun 自带 HSTS + meta referrer 兜底，迁 CF Workers 后落地）~~ ✅ **2026-07-22 闭环**：`worker/headers.js` 经 CF 构建环境自动 `wrangler deploy` 上线（push main 触发，无需本地 wrangler），`_headers` 全安全头生效，curl 验证 CSP/HSTS preload/X-Frame/Permissions-Policy 全返回。详见 NOTES §48 小节AR。
- **futures actual_return 3 角色全 null**（P2-10 已澄清）：`accuracy.<role>.actual_return` 是最新日期(20260720)次日涨跌，次日收盘未就绪必为 null（futures_position.py L119 已注释设计意图）；后端另有 `latest_bet.<role>.actual_return` 查 actual_return IS NOT NULL 的最新完成日(20260717, 1.528451)，app.js L5946-5953 已有回退逻辑（ret==null 时取 latest_bet 并显示日期）。前端不报错，字段保留 latest_bet 用，无需修复

### 计划任务审计 ✅ 无异常
- 8 任务全正常运行（launchctl list 7 exit 0 + backfill-evening exit 1 历史残留已修）
- 软链修复生效（gen_schedule_stats.py L27 去 resolve，schedule_stats.json intraday last_run 7-21 14:05）
- 今日 7-21 日志正常（intraday 9 个 0935-1405 + backfill 0200 + deploy 0206）
- 各 launchd 日志尾部正常（update_all 7-20 17:56 退出码 0，intraday 7-21 14:06 commit 6f700734）

### 修复建议
不擅自动修，等用户看后安排。**P0 .gz 滞后建议收盘后优先修**（盘中改 intraday-snapshot.sh 撞正在跑实例有风险），修复简单（补 .gz 生成+push，参照 3796ecf3）。

## 🆕 2026-07-22 待办（用户睡前列，醒来处理）

### P0（阻塞上线）✅ 2 项全闭环（2026-07-22 验收）
1. ~~**MaoziYun 拉取卡住**：21:35（821265ef）后 MaoziYun 未拉取 main（2.5h+），**ATR×3 改造 + signal_stats.json + 前端展示都没上线**~~ ✅ **2026-07-22 验收通过**（R2 全迁阶段3 瘦身 remote 523M->158M<300M 解超限恢复部署；curl 三站：ss.fx8.store + s.sugas.site 均上线 `app.min.js?v=b4eaf1ec` + `signal_stats.json` 双 200。详见 NOTES §48 小节AK）
2. ~~**schedule_stats 过期版**：0d85d2f0 从 trade 跑 deploy.sh 读旧日志生成过期 schedule_stats（last_run 卡 7-16/7-17 vs 线上 7-21）~~ ✅ **2026-07-22 验收通过**（方案③ symlink：`trade/data/logs` -> `trade-data/data/logs`（8:42 建）+ gen_schedule_stats.py `90eede7f` 支持进行中任务根治时序竞态 + `0b491fc2` 推数据；curl 线上 `schedule_stats.json` last_run：intraday=2026-07-22 11:30 / backfill_evening=2026-07-22 02:00 / 其他 task 7-21（今日未到点正常）；intraday-snapshot 10:06/10:48/11:06/11:31 各推一次刷新。详见 NOTES §48 小节AF+AK）

### P1（方向决策，待用户定）
3. ✅ **ATR×3 口径错位**（已闭环 2026-07-22）：用户"信号重复"核心诉求已闭环。前端 `app.js signalLabel sell_stop_loss` 从 reason 动态提取 ATR 倍数（commit `dd463d93`，不再硬编码 ×3.5）+ 后端首次跌破触发去重 + 方案A定倍（commit `a45819e8`：csi_div 4.5 / div_lowvol 3.5 / sz_div 3.5）。原 A/B/C/D 决策不再需要（信号重复根因是 dtype bug 致 6-7x 误增，修复后已根治）。详见 NOTES §48 小节 AC/AO
4. ~~**尖尖信号过滤**（已上线预览，待观察切真过滤）：h5 预览模式（灰 pin 不删除 buy_special）已上线 **R2 = C + C12 + E2 + 量价背离收紧**。C=偏离 ma60>20% AND ATR>3%；C12=均线附近假突破(dev∈(1.0,1.1] AND drawdown_hh20<-0.02)；**E2=布林上轨外 AND ATR>3%**（新增）；**量价背离收紧=price_vol_div==1 AND ATR>2.5%**（新增，ATR 从 0.03 收紧到 0.025）。pkl 实测 R2+C12 滤率 14.24%/滤中套牢 23.31%/滤后套牢 11.09%(基线 12.83%)/滤后 10d +1.731%(基线 +1.656%)。compute() 实跑 buy_special_filtered 2454/12892=19.03%（含 90 年代高波动期数据偏多）。预览模式安全，待观察后切真过滤（drop buy_special_filtered）。详见 NOTES §48 小节AM~~ ✅ **2026-07-22 尖尖逃顶过滤上线**（close 站稳+2%容差 + R2 真过滤 OR 组合）。B4_hold5d 升级 low->close+2%容差（降假确认）+ h5 预览标灰改真过滤 drop（降套牢优先）。回测：滤率 10.66%/trap-1.43pp(12.83%->11.40%)/win+0.6pp/pf+0.04/误杀 55.82% 最低/mean 持平。compute() 验证 buy_special_filtered=0。buy_special_filtered 类型废弃（前端灰 pin 渲染保留无数据不影响）。详见 NOTES §48 小节AT
5. ✅ **买点净化**（R1/R2 已实施上线 2026-07-21/22；R3 不推荐保持现状；R4/R5 远期研究保留，与 L62-79 项一致）：R1 升级为 B4_hold5d 过滤 buy_special（非原 buy_backup MA60 过滤）；R2 多层叠加真过滤绕过 regime 难题（h5 平衡档 + buy_special 降回撤方案B + peak_dd_filter 第三层）；R3 buy/buy_aux pct 过滤不推荐（误杀 pullback-in-uptrend 最佳信号）；R4 调查 2025 buy_special 高位反超根因 + regime 识别指标；R5 研究更选择性指标替代简单位置过滤（当前过滤误杀率 53%）。详见 NOTES §48 小节AB/AT/AU/AV

### 🆕 P1-新（2026-07-22 闭环）
9. ✅ **sell_stop_loss 首次跌破 dtype bug 修复 + 方案A定倍**（2026-07-22，commit a45819e8）：`sell_stop_cond.shift(1).fillna(False)` 返回 object dtype，`~object` 是位运算非布尔取反，致 first_break==below 完全不去重（6-7x 误增）。修复 `.astype(bool)`。raw 去重：csi_div 580->117 (5x)、hs300 1765->231 (7.6x)、us_spx 856->193 (4.4x)。方案A定倍 csi_div 3.5->4.5（raw 151->115 再降24%）。同日叠加过滤逻辑仍成立（副作用：最终窗口化信号数略升 csi_div 64->86，因 BUG 版过度过滤被修正，每个保留信号都是真首次跌破）。详见 NOTES §48 小节AO
10. ✅ **buy_special 降回撤过滤方案B + sh 豁免上线**（2026-07-22）：尖尖逃顶（小节AT）trap-1.43pp 但 mdd 未改善（基线 mdd_20d -4.52%/尖尖率 11.34%）。agent 调研方案 A/B/C，用户确认采纳 **方案 B = `(atr_pct>=2.5%) OR (dist_from_low60>0.30)` + sh 豁免**。效果：保留 12085/15809(76.5%) / mdd -4.52%->-4.01%(-0.51pp) / 尖尖率 11.34%->8.50%(-2.84pp，过滤率25%) / ret20 +2.47%->+1.62%(-0.85pp 可接受)。sh 豁免：sh 实测 mdd 微退化(-3.72->-3.91) + ret20 损大(+5.27->+1.90) 故不应用，其他9指数均改善。第三层叠加（不替换 B4 close 站稳 + h5 R2 真过滤），buy_special_set 排除 peak_dd_filter 命中日不发不更新游标。signals.py 改 4 处（L666 占位 + L785-800 计算+sh豁免 + L820-823 set排除）。compute()+store() 验证：buy_special 15809->12369(含美股)，sh 742 不变，国内 sz/hs300/csi500/csi_div 与调研完全一致。详见 NOTES §48 小节AU
11. ✅ **sh 专属 C1|D1a 叠加降尖尖上线**（2026-07-22，替代小节AU sh 豁免，升级自单 C1）：sh 豁免致 sh 尖尖率 10.38%（10 指数最高）。agent 调研方案 B 对 sh 误滤根因（dist_from_low60>30% 对 sh 趋势中继误滤）+ C1 洞察（dist_from_high>=15% 精准滤低位假突破，尖尖组 11.13% vs 非尖尖 5.59% ratio 1.99，>=15% 档尖尖率 23.91% baseline 2.3 倍）。先上线单 C1（commit 0da514e0 + 5dce98f7，sh buy_special 612），再升级为 **C1|D1a 叠加**（用户 2026-07-22 确认）。叠加公式 `((atr_pct>=0.025)|(dist_from_high>=0.15)) OR ((atr_pct∈[0.018,0.025))&(dist_from_low60>0.15)&(dev_ma60>1.05))`，D1a 补 C1 未覆盖的"中波动+涨多+均线之上"共振区。叠加效果（vs 单 C1）：612->502(保留 82.2%) / peak(<-10%) 7.35%->5.58%(-1.78pp/降 24%) / mdd -3.72%->-2.65%(改善 1.07pp) / ret20 +6.29%->+4.31%(损 1.96pp 可接受) / bot_acc 69.12%->68.33%(-0.79pp) / Jaccard 重叠率 30.8%（C1 与 D1a 互补性强）。其他 9 指数继续方案 B 不变。signals.py 改 sh 分支 L809-821 为叠加 mask + 注释。compute()+store() 验证：sh 612->502，20d mean +4.31%/win_rate 68.33%（signal_stats.json 完全吻合）。详见 NOTES §48 小节AV

### P2
6. ~~**width pipeline 7-21 18:03 被 Terminated:15**：查 width 数据完整性，必要时重跑 backfill_evening 补 width~~ ✅ **2026-07-22 P0-b 闭环**（runner.py mootdx step 加 30min `signal.alarm` 超时保护防 SIGTERM 阻塞复发，详见 NOTES §48 小节AL；**错误值修复 P0-a**（7-17~7-20 用 84 只残缺样本算错误宽度 a_width_zt_count=1）✅ 2026-07-22 闭环（7/20 baostock 数据补 mootdx + 7/1-7/19 从备份恢复 17932 行 + width_history.py 加 MIN_CODES_PER_DAY=1000 保护防复发，详见 NOTES §48 小节AQ）
7. ✅ **collect_health level=error 但 message=ok**（已验证 2026-07-22，`8420871a` fetchers.py L201-202 在位，矛盾消失：线上 overview.json level=error + message="direct:market_fund_flow 两源皆败无数据"，status 与 message 一致。注：level=error 本身是真实采集失败（a_fund_main 两源没采到）非误报，属另一采集问题，见下条补注）：8420871a 已修 fetchers.py（空列表返"两源皆败无数据"）但 overview.json 仍矛盾，从 trade-data 重跑 export 验证修复是否生效
   - ✅ **主力净流入第三源 IP 风控联动监测**（已实施 2026-07-22，commit `30be6f45`，`direct.py::fetch_market_fund_flow` 加第三源 `push2/api/qt/clist/get`）：722 主力净流入 4 次 backfill 全 fail，根因调研发现"双源"实为伪双源（akshare 备源底层与主源同 URL push2his）。新增第三源用不同 API 路径（clist/get 个股排名 vs fflow/daykline 资金流 K 线）+ 不同接口语义兜底。NOTES §48 小节AW 落档 IP 风控联动行为：push2his + push2 同属 eastmoney.com，触发阈值后联动封，第三源不在反爬名单仍可用。验证：主源 -195.55 亿 vs 第三源 -195.36 亿（5206 只汇总），差异 0.1% 口径对齐。限制：① 联动风控可能同步封 ② 只能拿当日不能补历史
8. ✅ **两融 T+1 显示**（2026-07-29 已根治）：原"可接受现状"作废。调研铁证 SSE 两融 T+1 早晨发布（非 memory 误判 18-19 点，7-27/7-28 19:15 连续采不到 T 日，7-29 07:59 才有 7-28），rzhb plist 19:15->08:00 根治（commit `29939ade`）。详见 NOTES §48 AZ59
9. ✅ **trade_sim JSON 持有时长旧 bug 值清理**（已实施，2026-07-20 标闭环）：100 品种 JSON 重生（sh 9253->1079 / hk_hscci 6982->760 / sw_801040 4460->533），后端修复 commit `a1f2b281`（`simulate_trade.py` L509 改最早买入->卖出方案A）。原 2026-07-23 核实"真未完成"状态已闭环：3 个 JSON 文件（`trade_sim_sh_full.json` / `trade_sim_hk_hscci_full.json` / `trade_sim_sw_801040_full.json`）原含多笔分批建仓子回合 hold_days 累加的旧 bug 值（实测 sh_full 最大 9253 天、hk_hscci 最大 6982 天），重生后已清理。**前端已兼容**：`app.js _tradeSimHoldDays` L7531 重算旧 JSON（UI 零影响）。详见 NOTES §48 小节AX

---

## 🆕 2026-07-23 待办（用户列，已验收方案待实施）

### ✅ P1-新-A 盘中信号收盘消失高亮提醒（已实施 commit 4c8b7838，2026-07-20 标闭环）

**背景**：盘中每30min（9:35~15:05）intraday_snapshot 重算 signal_daily 覆盖+推邮件（信号进 `signal_notified.json` 去重）；17:50 收盘 update_all 用收盘价再覆盖 signal_daily。现无任何"盘中 vs 收盘"对比机制。用户诉求：盘中推了某 buy* 信号后若收盘消失，应高亮提醒已执行买入用户隔日止盈/止损避免伤害。

**关键发现（调研已验收）**：
- `data/signal_notified.json`（格式 `{date_str: [[index_id, signal], ...]}`，7天清理）天然就是"盘中已推送信号快照"，收盘 signal_daily 全量覆盖后对比即可，**无需新建表/改表结构/额外采集**
- 信号消失敏感性：buy_backup（Supertrend对当日close极敏感）> buy_special（Donchian+5日站稳确认）> buy/buy_aux/sell/sell_stop_loss（中等）
- `check_signals.py` L40/L42/L120 已有 load_signal_notified，现只做去重不做 fade 检测
- 插入点：update_all.sh L91 收盘 check_signals.sh 之后（此时 signal_daily 已是收盘最终版）

**方案（推荐，~100行单文件为主）**：收盘 check_signals 加 `--fade-detect` 模式，对比 `signal_notified[date]` vs 收盘 `signal_daily[date]`：
- 严格消失（红警）：盘中推 (X, buy*) 收盘无 X 任何信号 = 买入理由失效
- 类型变化（橙警）：盘中 buy_backup -> 收盘 sell* = 反转
- 降级保留（黄警）：盘中 buy -> 收盘 buy_backup = 弱化
- 邮件并入收盘信号邮件一栏：主题加 ⚠️ 前缀 + 正文顶部红色横幅 + 消失信号表格（品种/盘中信号/收盘状态/建议操作），不增邮件总数

**改动点**：`scripts/check_signals.py` +80~120行（detect_fade 函数 + build_email 加 fade_alerts 参数渲染红横幅+表格，收盘模式默认开 fade-detect）/ `scripts/check_signals.sh` +2行 / `scripts/update_all.sh` 0~2行。约半天。

**产品分叉（已定推荐，等用户拍板）**：
1. 消失定义：**C 分等级**（红/橙/黄三档最完整）
2. buy 类型分级：**A 统一警示**（简单，用户自看品种）
3. sell 消失：**A 不提示**（对已卖出用户利好不提醒）
4. 盘中标签：**A 不显式打标签**（已有黄色横幅"待确认"语义够）
5. 邮件形态：**A 并入收盘邮件一栏**（不增邮件总数，⚠️前缀+红横幅够显眼）

**风险**：① 盘中信号误判频繁消失/重现 -> signal_notified.json 去重天然缓解（同日同信号只记一次，收盘只对比一次）② 无法知用户是否真买了，假设"盘中推了 buy* 就当可能买了"是合理假设 ③ update_all 失败致 signal_daily 是盘中版 -> update_all.sh L92 已有 SIGNAL_RC 检查+告警兜底

### ✅ P1-新-B pin 图表标题策略问号弹窗（已实施 commit 1e5d68b6，2026-07-20 标闭环）

**背景**：右下角 📋 买卖策略弹窗是全局通用描述（所有指数共用一份静态文本）。但每个指数有 per-index 定制或多策略混搭过滤，用户诉求：每个标了 pin 信号的图表标题后加 ❓，点开显示该品类指数实际执行的所有交易策略（足够细致完整，含参数/组合/过滤条件）。

**关键发现（调研已验收）**：
- `signals.py` L346-399 `strategy_desc(index_id, cfg)` 函数**已存在但只返回 {buy, buy_aux, sell} 3 字段**，扩展到 6 字段是增量改动
- per-index 定制真实存在（坐实问号有价值）：
  - `buy_filter`（4品类 RSI 阈值收紧）：kc50/sw_801730/sw_801760 = rsi_cross_25（基线30->25）
  - `buy_aux_filter`（19品类辅买增强）：csi1000/cyb 等 = rsi_cross_40；sw_801010 等 = close_above_bl_2pct
  - `sell_no_trend_filter`（1品类）：usdcnh = true（干预市单边上行 MA60 砍光卖点）
  - skip 机制：usdcnh skip_buy / cn_us_spread skip_sell / s.a_sentiment skip_buy（RSI结构性≥40）
- export.py L491/500/507/517/527/594/611/627 + main.py 已自动透传 strategy 字段到多个 JSON，**后端扩展后前端读 JSON 自动同步**
- 前端已有成熟机制可复用：`signalHelpTip`（L816 hover+click）/ `termTip`（L702 hover）/ `rule-modal` 样式 / `_initTermPop` 事件委托（L831-903）/ `_SIGNAL_HELP_ITEMS`（L709 6类信号描述）
- 现有 hint 蓝色行（L973-975 statsHint）"📋 策略｜买:.. 辅买:.. 卖:.."只 3 字段摘要，缺 buy_special/buy_backup/sell_stop_loss + per-index 参数细节

**方案 B（推荐）**：后端扩展 strategy_desc 从 3->6 字段，每字段含 `{desc, params, filter, enabled}`（enabled="skip" 标灰删除线），export 自动写 JSON，前端标题加 ❓：
- hover pop = 一句话摘要（如"本指数：主买 RSI上穿25[收紧] + 辅买 BB下轨+RSI上穿40 + 卖 20日高回落5%+MA60+MACD + 追买/备买/止损 全启用"）
- click modal = 展开该指数 6 类策略+per-index 参数+skip 标灰+引用 📋 全局警示

**方案选型**：A 前端硬编码（维护成本高✗）/ **B 后端扩展 strategy_desc（一处改自动同步✓）**/ C 过滤现有全局（只显示触发了哪些类型不显示参数，不满足诉求✗）

**子方案**：**B1 紧凑版（推荐）** modal 只显示 6 类信号+该指数 per-index 定制参数差异（如 kc50 显示"主买 RSI上穿25[本指数收紧，基线30]"），通用过滤层（h5/R2/B4_hold5d/3日确认）引用 📋 全局弹窗不重复展开 ~30行 / B2 完整版展开所有过滤层 ~60行信息密度高

**改动点**：`app/compute/signals.py` +60行（strategy_desc 重写 L346-399 扩展6字段）/ `static-site/app.js` ~80行（statsHint 注入 ❓ + 新增 _strategyModalHTML + _openStrategyModal + click 委托 [data-strategy-help]）/ `static-site/style.css` ~10行（复用 .term-tip/.rule-modal 微调策略行）。1 个 agent 1-2 小时。

**风险**：① strategy_desc 描述须与 compute() 主循环（L582-1057）实际触发逻辑保持一致 -> 缓解：strategy_desc 内部直接读 buy_filters/buy_aux_filters dict（已实现），buy_special/buy_backup/sell_stop_loss 全局参数写常量加注释"改 compute L683/L711/L727 同步改这里"，可考虑提到模块级常量双方共用 ② 多策略混搭过滤表达 -> skip 机制 modal 显式标灰删除线 ③ 与 hint 蓝色行重复 -> 保留蓝色行作摘要条，❓ modal 作完整版，两者互补 ④ 与 pin-label-fix agent 并行不冲突（改 L973-1047 statsHint + 新增函数，不看 markPoint label L355/1093 等）

### P1-新-C ETF买卖清单 AI评分 tab（方案已验收+用户决策已定，待实施）

**背景**：用户诉求自定义分析 tab 拆"AI预警"（现有功能原样）+"AI评分"（新 ETF 买卖清单）。清单格式：序号/ETF名/买几手（1层仓=1手）/评分/选定理由（点击弹窗看详情）。分买卖两列表按评分排序。解决场景：①开仓买什么性价比高不被套 ②手里有ETF不知该不该卖。评分综合自定义分析+近期买卖点+情绪分。手数逻辑：3手是市场均衡基准+上限，AI价值=向下减档到2/1/0手（0手不开仓也是有效输出）。

**关键发现（调研已验收）**：
- tab 拆分有先例：lab.js L3588 `_LAB_SUB_TABS` 数组，custom 改名"🤖 AI预警"+新增"📈 AI评分"子 tab，renderSignalLab 加分支 + hash 白名单加 aiscore
- **核心评分能力现成可复用**：`app/alert_score.py` L527 `compute_alert_for_target(target_id, target_type="etf")` 已支持 ETF，8+8 维度加权评分（H1情绪过热/L1情绪冰点/H7汪汪队离场/L4入场等）；L496 有 ETF 专属逻辑（H1/L1用RSI 120日滚动百分位，H7/L4汪汪队share_outflow/share_surge）
- **理由弹窗现成可复用**：`app/alert_reason.py` L363 `build_reason()` 返回完整 reason（dim_hits/data_thresholds/history_analogy/human_text/compliance_footer），前端 `_labCustomDimsTableHTML/_labCustomHistoryHTML/_labCustomThresholdsHTML/_labCustomFooterHTML` 4 函数已抽 common.js 0改动可复用
- ETF 数据缺口：etf_daily 表只有 close 无 open/high/low，**ETF 不走 signals.compute() 主循环无6色买卖点信号**，H3/L2维度缺省
- 全市场 ETF 映射：`data/board_etf_map.json` 59 key->485 ETF code（按成交额降序）

**用户决策（已定）**：
1. **ETF范围 = 全市场485个**（C代表ETF或12国家队相关做标注提示区分）。需扩展 etf_daily 采集覆盖485个（现仅12个国家队）
2. **卖清单 = 用户输入持仓**（C）：增加交互让用户输入持有的ETF，系统对其评分给卖出建议。违背"开tab就看"轻量诉求但用户明确要
3. **手数 = 评分分档3/2/1/0**（A）：极佳3手/较好2手/一般1手/差0手不入清单（3手基准向下减档）
4. **权重 = ETF专属调权**（B）：提高 H7/L4 汪汪队权重（ETF国家队动作重要）+ 降低 H3/L2（ETF无6色信号），需调参测试

**方案设计**：
- 后端：① 扩展 etf_daily 采集到全市场485个（需 OHLC，现只有close，扩采集工作量M）② `scripts/export_alert_analyze.py` 加 ETF 配置生成 `alert_analyze_etf_{code}.json` ③ 新增 `scripts/export_etf_score_list.py` 聚合485 ETF评分排序输出 `etf_score_list.json`（buy_list/sell_list两数组，每项含etf_code/name/score/hands/reason_summary/is_national_team标注） ④ alert_match.py PREGEN_TARGETS 加485 ETF元组
- 前端：lab.js 加 aiscore 子 tab + `renderAIScoreListLab()`（~250行）：买清单（low_alert降序+high_alert<60过滤+手数映射）/ 卖清单（用户输入持仓->对该持仓ETF算high_alert排序）/ 理由弹窗（复用_labCustom*HTML）/ 国家队或代表ETF标注
- 评分调权：alert_score.py ETF分支提高 H7/L4 权重降低 H3/L2，需回测验证
- 数据流：后端 export 生成 JSON 静态化（update_all 收盘后跑），前端 fetch 渲染

**改动点**：
| 文件 | 改动 | 行数 |
|---|---|---|
| app/collector/（新增扩ETF采集） | etf_daily 扩到485个+加OHLC采集 | ~200 |
| app/alert_score.py | ETF专属调权 H7/L4↑ H3/L2↓ | ~30 |
| app/alert_match.py | PREGEN_TARGETS 加485 ETF | ~10 |
| scripts/export_alert_analyze.py | 配置485 ETF导出 | ~30 |
| scripts/export_etf_score_list.py | 新增聚合评分生成清单JSON | ~150 |
| scripts/update_all.sh | 加调用 | ~3 |
| static-site/lab.js | aiscore子tab+renderAIScoreListLab+卖清单持仓输入交互 | ~350 |
| static-site/style.css | 清单表格+手数badge+持仓输入样式 | ~100 |
| **合计** | | **~870行** |

**工作量**：2-3天（含扩采集+调权测试+前端持仓交互）。比 MVP（国家队12个+现成权重+卖点列表）大很多，因用户选全市场485+用户输入持仓+ETF专属调权。

**风险**：
1. 全市场485 ETF 采集扩容工作量大（需 OHLC，现 etf_daily 只有 close）+ akshare 限流风险
2. ETF 专属调权需回测验证（不能拍脑袋定权重，要跑历史数据看评分有效性）
3. 用户输入持仓交互复杂（输入ETF代码/名称->匹配->评分->卖出建议），违背静态化架构（但卖清单必须基于用户持仓）
4. 同指数多 ETF 同质化（510300/510310/159919都是hs300）-> 全市场更严重，需去重或按成交额差异化
5. ETF 无6色买卖点信号，评分维度比指数少2个（H3/L2缺省），调权后可能仍不如指数版精确
6. 数据时效 T+1（ETF数据收盘后才更新），盘中不能用

**实施顺序建议**：分两阶段
- 阶段1 MVP：✅ **2026-07-23 已上线**（commit b8fbed75 后端 + d0d19830 前端 + 200bd4cc merge main，国家队12个+现成权重+卖清单卖点信号列表，三站点验证全绿，详见 NOTES §48 小节AZ4）
- 阶段2 扩展：🔄 部分完成（**ETF专属调权 ✅ 2026-07-23 已实施 commit `ad840d16`**，H7/L4↑ H3/L2↓ + 开关默认 off 待回测验证，详见 NOTES §48 小节AZ6；**前端分页+搜索+持仓输入 ✅ 2026-07-24 已实施 commit `743c3ef2`+`02730655`**，62只代表性ETF分页+搜索+持仓高亮+排名+只看持仓筛选，详见 NOTES §48 小节AZ7；剩余待实施：全市场485扩采集+OHLC，~200行，1-2天）

**与 P1-新-A/B 关系**：同属"AI 评分/预警"主题，P1-新-A（盘中信号消失）+P1-新-B（pin策略问号）+P1-新-C（ETF清单）三个可串行实施，互不冲突（A改check_signals后端/B改signals.py+app.js/C改lab.js+新增脚本，不同文件）

### 🆕 2026-07-23 晚续3 新增待办（DB同步/baostock/R2监控）

> 详见 NOTES §48 小节AZ4。

- ✅ **DB 同步根因修复（方案B）**（已实施 commit `f0f6df78`，2026-07-20 标闭环）：根因 = uvicorn cwd=trade/ 读滞后镜像，launchd 写 trade-data/data/ 最新主库，两 DB（trade/data/sentiment.db vs trade-data/data/sentiment.db）inode 不同=独立 copy 非 hardlink，仅 deploy.sh rsync 时同步；BaoStock 补采 / intraday 单独跑不触发 deploy -> 线上 export 漏数据。方案B：uvicorn + 手动补采统一从 trade-data/ cwd 跑，`app/db.py` 的 `.absolute()` 自动指向最新主库（零代码改启动配置）。已修 bug：`app/alert_match.py:21` + `app/alert_score.py:24` `.resolve()` -> `.absolute()`（resolve 解析 symlink 跳回 trade/，absolute 保留 symlink 路径，commit `f0f6df78`）；`scripts/backtest_buy_aux.py:53` 硬编码 trade/data/（只读回测不影响线上，优先级低）
- ✅ **baostock 断线重连**（已实施 commit `185a16ea`，2026-07-20 标闭环）：`_ensure_login` 加 `force_reconnect` + `_reconnect_with_retry` 重连逻辑，避免单次断线致后续采集全 fail
- ✅ **R2 上传超时监控（A3 已实施 2026-07-20）**：`deploy.sh` L136-159 加 `run_r2_upload` 函数（bash 原生 background+sleep+kill，macOS 无 timeout/gtimeout 命令），5 个 upload_r2 调用（upload-lab/trade-sim/trade-sim-json/index/industry）包装为后台跑 + 每 5s 探活 + 超 `R2_UPLOAD_TIMEOUT`（默认 300s=5min）即 kill 释放 deploy.lock。原背景：deploy.sh R2 上传层 hang 不影响 git 上线（CF Workers 从 git deploy 不依赖 R2），但 `deploy.lock` 持有不释放会阻塞后续 update_all（2026-07-23 实测 upload_r2 卡 TCP SYN_SENT 8分20秒，主控 kill 36605+35416 释放锁）

---

## 🆕 2026-07-23 待办外5方向（用户感兴趣，已调研落档待排期，详见 NOTES §48 小节AZ）

> 用户问"待办外建议"，提了5方向都感兴趣，派2个调研 agent（前端3+后端2）只读摸现状给方案。**结论：5方向中 DB灾备已大部分实现，其余4方向待实施。** 收盘 deploy 完再开（盘中不改 app.js/build）。

### P2-新-A 数据可信度透明化 · 采集健康度小灯（前端方向1，~80行）✅ **2026-07-23 已实施**（commit `dd504c21`，详见 NOTES §48 小节AZ6）
- **现状**：后端 `collect_health`（level=ok/warn/error + items）已导出 overview.json（export.py L361），但前端**采集时间旁没暴露小灯**（app.js L2465-2466 注释明说"留给后端日志不展示"）。KPI 灰态卡片只覆盖 9 个白名单指标（L3891-3895），其他 metric_id 的 error 不显示
- **方案**：采集时间旁（`_renderCollectTime` L2485）加🟢🟡🔴小灯，hover 弹失败源 metric_id+message。`fetchCollectTime` 传 `r.collect_health`，复用现有 data-tip hover 机制
- **风险**：① collect_health error 可能误报（export.py L382-394 已过滤陈旧误报但非100%）② 与"数据更新规则 modal"时效展示语义不同需文案区分（小灯=采集动作成败 / modal=数据到没到最新）
- **决策点**：① 小灯位置（采集时间旁 推荐）② warn 是否显示（推荐显示但弱化文案）③ 是否同步补全灰态卡片白名单

### P2-新-B 信号历史复盘展示（前端方向2，分2档）
- **现状**：`signal_stats.json` 已导出 static-site/data/（230KB，110品种×6信号×3窗口），但 app.js L745 `_aggregateSignalStats` **硬编码只取 `s["10d"]`**，5d/20d 数据浪费；L792 注释过期说"未导出"实际已导出
- **方案2a（简单，~30行，先做）** ✅ **2026-07-23 已实施**（commit `02eae130`，app.js L732-808 `WINDOWS=["5d","10d","20d"]` 三窗口聚合，待 merge main 上线，详见 NOTES 小节AZ3）：信号 modal 分析概况从"10日单一窗口"扩"5d/10d/20d 三窗口对比"，让用户看短/中/长期表现。零风险（数据已有+渲染逻辑已有）
- **方案2b（复杂，~200行，后做）** ✅ **2026-07-24 已实施**（commit `8091db40`，从零实现真 pin 复盘专属面板，详见 NOTES §48 小节AZ7）：具体 pin 旁标"X天前buy_aux至今+3.2%"真复盘。查 `indices_sparkline[index_id]` close 序列算涨跌。难点：sparkline 只含宽基，行业/全球指数 close 序列需另查 industry.json/global-all.json。**实际实施**：localStorage[`pinned_indices`] + 📌按钮（`_appendPinBtn`）+ pin 复盘卡片（`_pinReviewCardHtml`/`_renderPinReview`）四段（📈走势摘要 5/20/60日涨跌+波动率+高低点 / 🎯最近信号 / 📊10d 6类信号胜率盈亏比 / 📋专属规则 6类策略desc+per-index filter）+ 跨tab状态隔离 + self-cleanup + 数据缓存双轨
- **风险**：① 2b 数据覆盖度（sparkline 只宽基）② 2b 真实性 vs signal_stats 聚合语义不同（用户预期真复盘，signal_stats 是统计聚合）③ 样本数 n<5 误导需标注
- **决策点**：① 2a vs 2b vs 都做（推荐先2a后2b）② 2b 展示位置（pin旁徽章 推荐 vs modal内）

### P2-新-C 移动端 PWA（前端方向3，~150行+2 icon）✅ **2026-07-25 已实施**（commit `a41fb2df`，详见 NOTES §48 小节AZ20）
- **现状**：完全空白。index.html 无 manifest/SW/theme-color（grep 计数0），无 icon-192/512.png，无 sw.js。有利条件：纯静态站 SW 友好 + 已有4套皮肤 + favicon.svg 矢量可生成 icon + _headers 已配 CSP 无冲突
- **方案三件套**：
  1. `manifest.json`（name/short_name/theme_color=#d4af37 redgold/icons/start_url）
  2. `sw.js` 缓存分层：App Shell `CacheFirst` + 数据JSON `stale-while-revalidate`（盘中3分钟刷，SWR最优）+ intraday_snapshot `NetworkFirst` + 第三方不缓存。版本管理 `CACHE_VERSION` bump 清旧
  3. index.html 加 `<link rel="manifest">` + meta + SW 注册脚本
- **风险**：① SW 缓存策略误伤盘中数据（必须 SWR 不能 CacheFirst）② SW 更新滞后需 skipWaiting+clients.claim 但有 mid-session 切版本风险（推荐显式提示刷新）③ icon 生成（favicon.svg 35字节极简，转512可能模糊，需重做或用 og.png 裁剪）④ iOS standalone 不支持 push（本方案没用到无影响）
- **决策点**：① 缓存策略（推荐 App Shell CacheFirst + 数据 SWR + intraday NetworkFirst）② icon 来源（复用favicon vs 重做高清 vs og.png裁剪）③ theme_color（固定redgold 推荐 vs 跟随皮肤动态切换复杂）④ 是否做完整 offline（推荐不做，只缓存 App Shell+上次快照）

### P2-新-D DB 灾备补强（后端方向3，~70行但大部分已实现）
- **意外发现**：任务描述说"缺DB备份"**实际已完整实现**：
  - `backup_db.sh` L48 `src.backup(dst)` sqlite3 在线热备（WAL一致快照不锁库）+ 14天本地滚动 + 失败 notify 告警
  - `upload_r2.py upload-db` 三层备份（`backup/` 日30天 + `weekly/` 周28天 + `monthly/` 月365天）+ 私有桶 `signal-backup` + gzip（102MB→30MB）
  - `verify_backup.sh` 每日恢复演练（下载+integrity_check+COUNT对比）
  - `update_all.sh` L202 串接，日志确认最近3天都在跑
- **只剩补强**：① 恢复操作文档（脚本支持 `download-db` 但无流程文档）② 可选独立 plist 18:30 双保险（主控判断：plist 双保险价值不大，update_all 串接已够稳+有告警，**只做恢复文档即可**）
- **决策点**：① DB备份触发方式（A现状update_all串接 / B独立plist / C双保险推荐但主控倾向只A+文档）② 异地备份层无需再上云盘（R2三层+verify已够）

### P2-新-E 告警渠道扩展 Telegram bot（后端方向4，~70行）✅ **2026-07-23 已实施**（commit `fc27f631`，notify.py send_telegram + send 多渠道分发 + check_signals 删重复 send_email 改 notify.send，详见 NOTES §48 小节AZ6）
- **现状**：纯邮件。notify.py `send()` 单一 SMTP，无即时渠道。check_signals.py L574-598 **重复实现 `send_email()`** 25行（与 notify.py 几乎一样，不走 notify.py）。fade-detect 红警纯邮件触达
- **方案**：
  1. `config/telegram.json`（gitignore，bot_token/chat_id/api_base，模板 telegram.json.example）
  2. notify.py 加 `send_telegram(text)`（POST api.telegram.org/bot{token}/sendMessage）+ `send()` 改多渠道分发（邮件+Telegram并行，任一成功即OK，8处调用方零改动自动获益）
  3. 顺带删 check_signals.py 重复 `send_email()` 改调 notify.send（fade-detect 红警自动走多渠道）
  4. CF Workers 反代解决国内可达（复用 ss.fx8.store 基础设施）
- **风险**：① Telegram 国内可达需 CF Workers 反代 ② bot token 隐私 gitignore ③ 消息频率限制（intraday 30分钟一次远低于限制OK）④ check_signals 重构动 fade-detect 邮件链路需 --dry-run 测试
- **决策点**：① 渠道选型（A只Telegram推荐 / B只企业微信webhook国内直连但内容简化4096字节限 / C都加）② notify.py 多渠道架构（改A `send()` 内部分发推荐 调用方零改动 / 改B独立函数调用方改8处）

### 5方向排期建议
- **改动量**：A(80行) / B-2a(30行)+2b(200行) / C(150行) / D(只文档) / E(70行)
- **价值排序（主控推荐）**：D(只补文档,0成本闭环) > B-2a(30行快见效) > A(数据诚信) > E(即时告警) > C(PWA体验) > B-2b(真复盘,大工作量)
- **并行性**：A/B/C改 app.js（需build,串行）+ D/E改 scripts（不碰build,可任何时候并行）。D/E 可先做不撞 deploy
- **等用户拍板排期后实施**

---

## 🆕 2026-07-23 待办外6方向（第二批，用户感兴趣，已调研落档待排期，详见 NOTES §48 小节AZ2）

> 用户对第二批6方向也感兴趣，派2个调研 agent（数据展示3+推送告警3）只读摸现状给方案。**结论：6方向中盘后日报已完整实现，板块轮动受限于6-7个月历史，其余待实施。** 收盘 deploy 完再开。

### P2-新-F 板块轮动信号（数据展示方向1，~105行，数据受限）✅ **2026-07-24 已实施**（commit `b4285988`，形态频次非回测，详见 NOTES §48 小节AZ7）
- **现状**：`daily_metric` 表 `ind_flow_<sw_id>` 31个行业资金净流入（同花顺源直接亿元），export.py L580 已导 fund_flow 字段，app.js L7040 已渲染资金流 mini sparkline。但**热力图 _industry_heatmap 只算涨跌幅无资金流维度**
- **方案**：3档轮动信号（连流入3日/流入加速/资金占比Top3）+ 行业卡 chip「🔥连流入3日」「🚀流入加速」+ 热力图双维度着色。export.py 新增 `_rotation_signal()` 注入行业 JSON
- **实际实施**：受 ind_flow 仅 6-7 月历史硬约束，**只做形态频次不做回测**。指标=最近20交易日 `fund_flow.value` 方向反转次数（正->负或负->正=1次）。分级：≥8高频🔥🔥/6-7中频🔥/≤5低频，样本<10不评级。31板块平均6.4次。展示：板块卡 spark-name 旁 rotTag + 热力图下 Top10 rotation-freq-card（可点击滚动定位）。新函数 `_calcRotationFreq`/`_rotationTag`/`_buildRotationFreqList`
- **风险**：**致命硬约束**--ind_flow 仅 6-7个月历史（2026-01-05起，130交易日），回测"后续收益分布"样本不足。对策：缩小到3个月只做"形态触发频次统计"不做回测，文案明确"近3个月统计"
- **决策点**：回测窗口（A推荐3个月只做形态统计 / B等补历史源当前无可用）-- 采纳 A

### P2-新-G ETF联动推荐（数据展示方向2，~85行，推荐先做）✅ **2026-07-23 已实施**（commit `02eae130`，待 merge main 上线，详见 NOTES 小节AZ3）
- **现状**：`board_etf_map.json`（65KB）已含58板块->ETF候选，但**keys只有 sw_*/thsc_*，9个宽基指数 ID 不在 map**。汪汪队 `etf_national_team.py` L56 `ETF_LIST` 12只含 (code,易记名,跟踪指数,市场) **现成映射数据源**（覆盖7宽基）。前端 `_renderEtfTag`/`_bindEtfPopup` 已是通用函数，但指数信号卡 `renderOne` L1666 没调用
- **方案**：新加 `INDEX_ETF_MAP` 常量反查汪汪队 ETF_LIST（精准）+ 关键词补 bj50/红利没汪汪队覆盖的；export_index 宽基 JSON 注入 `etfs` 字段；`renderOne` 调 `_renderEtfTag(idx.etfs)` + buy信号时高亮。**几乎是拼装不是开发**
- **风险**：① 宽基映射不全（sh上证/sz深成无跟踪ETF需文案说明，bj50/红利手动补）② 多ETF候选按成交额排序用户自选不硬选（对齐 list-candidates-not-hardcode）③ ETF滞后指数需文案"信号参考ETF已反映部分预期"
- **决策点**：① 映射表维护（A扩build_board_etf_map关键词 / B推荐新INDEX_ETF_MAP反查汪汪队精准 / 可B为主A补缺）② 展示深度（必做信号卡tag + 可选走势图markPoint + 可选modal走势对比，推荐先做必做+可选1）
- **和P1-新-C关系**：互补不重复。P1-新-C是"ETF视角清单"，方向2是"指数视角带ETF推荐"

### P2-新-H 历史相似形态匹配（数据展示方向3，~240行，独特价值最高）✅ **2026-07-23 已实施第一批**（commits `dd504c21`+`838dbafb`+`0ff4cbc1`+`2129a83b`+`935f69da`，皮尔逊相关系数+滑窗 top5 匹配 + sw_ 取数 + hover 高亮 + TOP_PLOT 3->5 + 走势叠加图例，详见 NOTES §48 小节AZ6）
- **现状**：`index_daily` 表历史充足（sh 8688行1990起35年/hs300 5955/kc50 1588/bj50 1025，31行业每6417行）。trade_sim 是参数化回测，**无相似形态匹配**，功能互补
- **方案**：皮尔逊相关系数+滑窗算法（O(n)前端实时算<100ms，numpy可向量化）。取当前近20日close归一化为日收益率，历史滑窗算相关系数取top5最相似时段，每个给"之后5/10/20日累计涨跌幅"。展示：trade_sim modal 新增「相似形态」tab + 走势图叠加top1延伸虚线
- **风险**：① 过拟合/巧合相似（对策：展示top5+相似度分布，文案"历史相似≠未来重演"）② 市场结构变化（对策：默认扫描近10年可切换）③ 归一化敏感（默认日收益率scale-invariant）
- **决策点**：① 算法（A DTW精准慢需后端预计算 / B推荐皮尔逊快前端实时足够 / C皮尔逊初筛+DTW精排）② 展示位置（1推荐modal新tab主入口 + 2推荐走势图叠加延伸虚线 + 3独立tab重）③ 历史扫描范围（默认近10年可切换全历史/近5年）

### P2-新-I 盘后日报（推送方向4，已实现95%）
- **意外发现**：`daily_summary_email.py`（D10收盘速递邮件）**已完整实现并接入 update_all.sh L187-195**，7/20创建跑了一周稳定。含 build_subject/build_text/build_html 模板，读 summary_history.json 聚合恐贪/情绪分/上证/涨跌家数/涨停跌停/成交额/买卖点/新高新低/均线多空/领涨领跌/冰点/摘要。复用 config/email.json SMTP 失败不阻塞
- **只剩可选补强**：用户需求"操作建议"字段当前没显式输出（只有自然语言 summary_short）。可选补结构化操作建议（读 alert.json + signal_stats.json 聚合"建议关注/谨慎"，~30-50行）
- **决策点**：是否补操作建议字段（A推荐保持现状自然语言摘要避免过度设计 / B补结构化建议）
- **和check_signals邮件关系**：独立合理（买卖点是技术指标层，日报是市场情绪层，受众不同信息密度过高不合并）

### P2-新-J 异常波动盘中告警（推送方向5，~250行新文件，框架有检测缺）✅ **2026-07-23 已实施**（commit `97134640`，detect_intraday_anomaly.py + 接入 intraday_snapshot.sh L194；`5924114a` 补 .gitignore anomaly_notified.json，详见 NOTES §48 小节AZ6）
- **现状**：intraday_snapshot.sh 30分钟一次(9:35-15:35共11次/天)+邮件链路+去重机制(signal_notified.json 7天清理)全有，L188已接 check_signals --intraday。但推的是预定义买卖点信号(RSI/布林/唐奇安等)，**缺异常波动检测算法**（5分钟涨2%/急涨急跌/放量/突破）
- **方案**：新增 `scripts/detect_intraday_anomaly.py`（~250行），借鉴 alert_score.py L5量能异动模式。检测急涨急跌(pct_change≥±3%/±5%/±7%三档)+放量(net_inflow≥近5日均×2)+突破(近20日高低点)。去重 data/anomaly_notified.json(同signal_notified模式)。复用 intraday 30分钟节奏不新增定时，L188前插入
- **风险**：① 噪音（30分钟一次漏分钟级，阈值保守±3%起+同日去重）② 数据频率（intraday_snapshot 30分钟非tick，"5分钟涨2%"实际"30分钟内涨2%"语义需对齐）③ 历史对比缺（intraday_snapshot表单行覆盖无分钟级历史，严格5分钟对比需新intraday_history表DB迁移）④ 误报（开盘9:35首次无上一份，用prev_trading_day收盘作基线）
- **决策点**：检测版本（A简单版日涨跌幅阈值 / B完整版加DB表存历史 / C推荐混合版日级+30分钟对比不加DB）

### P2-新-K 订阅个性化推送（推送方向6，~410行，完全空白分阶段）✅ **2026-07-24 已实施**（前端 commit `c703a584` + 后端 commit `3d29c05c`，详见 NOTES §48 小节AZ8）
- **现状**：完全空白。scripts/ 和 app.js grep subscribe/订阅/favorite/收藏/watch_list 全空（仅gen_rss RSS阅读器非订阅）。check_signals 当前全量推送，用户收到一堆不关注的
- **方案**：3层新建。① 存储config/subscribe.json（email+indices+signal_types，gitignore同email.json）② check_signals 加订阅过滤分支（默认去重模式按email分组，去重key改email+index_id+signal）③ 前端订阅UI（指数页加订阅按钮+管理页，app.js+250行+后端/app/main.py /api/subscribe +80行）
- **风险**：① 隐私（subscribe.json含email需gitignore）② 单文件扩展性差未来转DB需迁移 ③ 去重+订阅交互（全局去重改按email分组）④ 前端改动量大（app.js已8971行）
- **决策点**：① 存储（A推荐config/subscribe.json单用户够用 / B DB表多用户扩展）② 是否先做后端过滤再做前端UI（A推荐分阶段先JSON+过滤验证，UI后做）③ 订阅粒度（A推荐按指数订阅 / B按指数+信号类型避免过度复杂）
- **订阅对象清单**：indicators.yaml 含 9 A股+3 港股+31 行业+27 概念+8 综合分=78个可选
- **实际实施**：`config/subscriptions.json`（gitignore）+ `.example` 模板；前端指数卡片 h3 末尾 🔔 按钮 + 订阅管理 modal（邮箱/chat_id+标的+6类信号+已订阅列表脱敏+localStorage `sub_user_info` 免重复输入）；后端 `app/main.py` /api/subscribe（GET 脱敏列表/POST 创建更新/DELETE）+ `scripts/check_signals.py` `push_subscriptions`/`load_subscriptions`/`save_subs_notified`（独立去重 `subs_notified.json` 7天清理）+ `scripts/notify.py` `send_to`（email+chat_id）
- ⚠️**线上限制**：ss.fx8.store 纯静态站（CF Workers 托管 static-site/）无 FastAPI 后端，线上 `/api/*` 全 404（含 /api/subscribe）。订阅管理 UI modal 线上弹得出但保存/列表/删除 API 调用失败。**订阅推送本身可用**（launchd 跑 check_signals 读本地 `config/subscriptions.json` 推送，不依赖线上 API）。线上管理订阅需手动编辑 `config/subscriptions.json`（从 `.example` 复制）

### P2-新-W PC浏览器通知（推送方向7，方案A页面Notification，~230行）✅ **2026-07-29 已实施**（commit `4c4be0a8` + merge main `601a9da7`，详见 NOTES §48 AZ61）
- **场景**：PC模式下用户开着看板，新信号/盘中异常/收盘速递时弹Windows通知（进Windows操作中心）。Web Notifications API全球94.38%支持，Windows Chrome22+/Edge14+/Firefox22+全支持，HTTPS必需(ss.fx8.store满足)，requestPermission须用户手势触发，通知进Windows通知中心（OS原生渲染）
- **现状**：前端无任何浏览器通知逻辑（grep notif/push/通知 全为array.push）；sw.js已注册(仅缓存无push/showNotification，v2-20260729-a56)；manifest.json已存在(A6 PWA已闭环AZ20 commit a41fb2df)；后端邮件+TG完善(notify.py send/send_to + check_signals + schedule_monitor)无浏览器通知端点；前端轮询intraday 1分钟(L4636)+overview自适应(L4032)可复用挂通知检测
- **方案A（页面Notification，推荐）**：前端加"🔔浏览器通知"开关+通知工具函数(requestNotifyPermission/showNotification ~80行)，复用intraday 1分钟轮询挂通知检测(~50行)；后端新增export_notifications.py导出notifications.json(复用signal_notified/anomaly_notified去重~100行)。sw.js不改(方案A不依赖SW)。零新依赖
- **备选**：方案B(Service Worker Web Push ~400行，VAPID+pywebpush+subscription存储，关闭页面也收但重，CF Workers不跑推送只能本地launchd触发) / 方案C(PWA showNotification ~260行，复用sw.js比A多持久特性，用户切tab通知仍存活)。渐进升级路径：A上线后若要关闭页面也收再升级B/C
- **触发场景6类**：新买入信号(buy/buy_aux/buy_special/buy_backup)/新卖出信号(sell/sell_stop_loss)/盘中异常(volume_surge/breakout/rapid_move)/数据滞后告警/收盘速递(D10)/fade-detect消失
- **去重三层**：后端复用signal_notified/anomaly_notified(每事件每日只导出一次)+前端localStorage notified_keys(防同事件多次轮询重复弹)+Notification tag(同tag只显示最新)。和邮件/TG共享后端diff不新增去重文件
- **用户可控**：前端"🔔浏览器通知"开关按钮，首次点击触发requestPermission(用户手势合规)，granted后localStorage notify_enabled=true开始轮询，denied置灰提示去浏览器设置恢复，关闭开关停止轮询。PC/移动端UA检测(移动端new Notification报TypeError需跳过或用showNotification)
- **改动**：app.js ~130行(开关+工具函数+轮询检测) + export_notifications.py ~100行 + notifications.json导出 + bump_asset_version + bump sw CACHE_VERSION(若用方案C)
- **风险**：页面关闭不收(PC场景可接受)；移动端new Notification报错需UA检测跳过；denied后需引导用户去浏览器设置恢复(无法代码重置)；fade_notified.json不存在fade-detect去重机制待确认(可能复用signal_notified)
- **不合并A6 PWA**：A6已闭环(AZ20)，方案A不依赖SW独立做
- **验收**：开关点击授权->弹测试通知->进Windows通知中心；新信号触发->弹通知；重复事件不重复弹；关闭开关停止轮询
- **调研落档**：2026-07-29 agent a43eec2cc7d7ac8fb调研完成(完整报告见task-notification)。✅ **2026-07-29 晚续20 已实施上线**（commit `4c4be0a8`+merge main `601a9da7`，export_notifications.py 333行6类触发+app.js 230行🔔开关+三层去重+ts:overview-refreshed事件hook不改状态机，sw.js a58->a59，详见 NOTES §48 AZ61）

### 6方向排期建议
- **改动量**：F(105行,数据受限) / G(85行,拼装) / H(240行,独特) / I(已实现,可选~40行) / J(250行新文件) / K(410行,空白)
- **价值排序（主控推荐）**：I(已实现0成本) > G(85行拼装快见效) > H(独特价值最高) > F(数据受限先做信号提示不做回测) > J(盘中告警即时价值) > K(大工作量分阶段)
- **并行性**：F/G/H改 app.js+export.py（需build,串行）+ I/J/K改 scripts（不碰build,可并行）。I/J/K 可先做不撞 deploy
- **等用户拍板排期后实施**

### 11方向总览（5+6批，待统一排期）
- **已实现/0成本**：D DB灾备(只文档) ✅ / I 盘后日报(已实现95%)
- **快见效小工作量**：B-2a 信号三窗口(30行) ✅已实施(commit `02eae130`) / A 采集健康度小灯(80行) ✅已实施(commit `dd504c21`) / G ETF联动(85行拼装) ✅已实施(commit `02eae130`)
- **即时价值**：E Telegram(70行) ✅已实施(commit `fc27f631`) / J 异常波动(250行) ✅已实施(commit `97134640`) / F 板块轮动(105行,数据受限) 待实施 / W PC浏览器通知(230行) ✅已实施(commit `4c4be0a8`)
- **大工作量**：B-2b 真pin复盘(200行) 待实施 / C PWA(150行) 待实施 / H 相似形态(240行) ✅已实施第一批(commit `dd504c21`+`935f69da`) / K 订阅推送(410行) 待实施
- **已实现方向**（DB灾备D/盘后日报I/健康灯A/Telegram E/异常波动J/相似形态H第一批/PC浏览器通知W）防以后重复调研

---

## ✅ 2026-07-23 晚 补5项修复上线闭环

> P1-新-C 阶段1 上线后收尾 5 项修复，主控 curl 三站点验证全绿。详见 `NOTES.md §48 小节AZ5`。

- commits：`04f69fb7`（fix）+ `01ddf8af`（build min 破缓存），已 push main（639dbf0e..01ddf8af fast-forward）。数据 `f93a2066` data update [backfill] 2026-07-23_21:07，`etf_score_list.json` 含 H3/L2。版本号 `8428a4d1`。
1. ✅ **alert_score.py H3/L2 ETF 专属信号**：L435 `_compute_etf_buy_sell_signals` 复用 signals.py `_rsi/_bollinger/_macd` 现算，L564 `compute_target_dims` ETF 分支调用。解决 P1-新-C 风险点 5「ETF 无 6 色信号 H3/L2 缺省」
2. ✅ **chip flex:1 三等分撑满**（style.css L375）：`.signal-chip-row .signal-chip { flex: 1 1 0; ... }` 3 等分，移动端 L378-379 恢复横滚
3. ✅ **模拟回测按钮挪 chip 后独立 DOM**（app.js L1296-1316）：新增 `_simBtnHtml` + `_prependSimBtn`，CSS 改 `.sim-btn`，放 chip-row 后
4. ✅ **指数筛选 loading 提示**（app.js L1892-1931）：加载中显 spinner + "加载指数数据中…"，无数据显"📊 该筛选暂无数据"
5. ✅ **注释修正**（app.js L437-438）：三元组去重说明 scenario+path+win（原二元组致 18/19 缺"回撤最小"）

---

## ✅ 2026-07-23 晚续4 闭环（A8 Telegram / CF缓存根治 / intraday修复 / 第一批前端4项 + A4/A10/A11/A13）

> 当晚最后一批上线工作 + 今日早些时候已上线未单独落档项。详见 `NOTES.md §48 小节AZ6`。

**当晚 4 项（主控 highlight）**：
1. ✅ **A8 Telegram bot 多渠道通知**（commit `fc27f631`）：notify.py `send_telegram` + `send` 多渠道分发返回 dict + check_signals 删重复 send_email 改 notify.send + check_nt_signals 同步 + telegram.json.example 模板 + .gitignore。对应 P2-新-E ✅
2. ✅ **CF 缓存根治**（commit `d1d137dc` + `3acb2c72`）：wrangler.jsonc `run_worker_first:true` 致 _headers 不生效，真正生效是 worker/headers.js；HTML 规则 private->no_store。**重要发现**：CF Workers Static Assets 无视 Cache-Control（no-store/private/no-cache 均无视仍 HIT），靠部署自动 purge；no-store 仅浏览器层生效
3. ✅ **intraday 修复**（commit `74b0ec39`）：剥离 intraday_snapshot.sh 的 upload-industry（268文件~15-16min 超 ExitTimeOut=1800 被杀）-> industry 走 deploy.sh L166 收盘后全量管；gen_schedule_stats.py 配对逻辑修（break->continue + 孤儿检测 + 被杀标 exit=143 前端显⚠️）
4. ✅ **第一批前端 4 项**（commit `935f69da`）：板分化按钮挪 spark-name 后 + 相似形态 sw_ 取数（_shapeLoadSeries 加 sw_* 分支走 ssd.fx8.store/index/${id}-all.json）+ top5 hover 高亮（data-shape-rank 事件委托）+ TOP_PLOT 3->5

**今日其他完成项（早些时候 commit，补记）**：
- ✅ **A4 采集健康度小灯 + A10 相似形态前端**（commit `dd504c21`）：采集时间旁🟢🟡🔴小灯 + 皮尔逊相关系数滑窗 top5 匹配。对应 P2-新-A / P2-新-H ✅
- ✅ **A11 异常波动盘中告警**（commit `97134640` + `5924114a`）：detect_intraday_anomaly.py ~250行 + 接入 intraday_snapshot.sh + anomaly_notified.json 去重 + .gitignore。对应 P2-新-J ✅
- ✅ **A13 P1-新-C 阶段2 ETF专属调权**（commit `ad840d16`）：H7/L4↑ H3/L2↓ + 开关默认 off 待回测。对应 P1-新-C 阶段2 调权部分 ✅
- ✅ **A3 R2上传超时监控 + A7 DB灾备恢复文档**（commit `c43f3d6d`）：R2 跑超5min kill 释放锁 + docs/backup-restore.md + docs/restore-db.md。对应 P2-新-D ✅

**§8 教训补充（2026-07-23）**：
- commit 时间戳≠触发时点（6867daa0 21:30 是 deploy 打标签非任务触发；看 launchd log 文件存在性非 commit 时间戳）
- CF Workers Static Assets 无视 Cache-Control（header 层最激进只能 no-store 浏览器层生效，CF 边缘靠部署自动 purge）

---

## ✅ 2026-07-23 深夜续 / 7-24 凌晨续闭环（rzhb 误报根治 + B4 ETF 评分列表 + A9 板块轮动 + A5 真 pin 复盘）

> 7/23 23:30 ~ 7/24 00:50 深夜续最后一批上线工作。详见 `NOTES.md §48 小节AZ7`。

1. ✅ **rzhb 误报根治**（commit `9116e97f`）：schedule_monitor 与任务整点竞态（23:00:05 读 log 时 rzhb 还没写"开始"行）+ rzhb 退出不刷 stats。修复=schedule_monitor.sh 漏跑检查下界 +60s buffer（sch+60s <= NOW）+ rzhb_backfill.sh 加 `trap refresh_stats EXIT` 退出调 gen_schedule_stats.py。同日 21:00 futures / 21:30 etf 同竞态误报一并根治。验证：intraday 7/23 15:35 exit=0 dur=1144s 不再超时 + rzhb 7/23 23:00 stats 正确显示（trap 生效）
2. ✅ **B4 完整 ETF 评分列表 - 分页+搜索**（commit `743c3ef2`）：新增 etf tab，`renderEtfScore`/`_etfScorePages`/`_applyEtfScoreFilter`/`_renderEtfScoreBody`，62只代表性 buy20+sell30 分页+搜索框
3. ✅ **B4 完整 ETF 评分列表 - 持仓输入**（commit `02730655`）：localStorage[`etf_holdings`] 6位代码数组 + `_getEtfHoldings`/`_setEtfHoldings`/`_renderEtfHoldingsPanel` + 持仓行 `.is-holding` 金色高亮 + ⭐持仓 badge + "只看持仓(N)"筛选 chip + chips 显示"代码 名称 #排名"
4. ✅ **A9 板块轮动信号**（commit `b4285988`）：**只做形态频次不做回测**（ind_flow 仅6-7月历史）。指标=最近20交易日 fund_flow.value 方向反转次数。分级：≥8🔥🔥/6-7🔥/≤5低频，样本<10不评级。31板块平均6.4次。展示：板块卡 spark-name 旁 rotTag + 热力图下 Top10 rotation-freq-card。新函数 `_calcRotationFreq`/`_rotationTag`/`_buildRotationFreqList`。对应 P2-新-F ✅
5. ✅ **A5 真 pin 复盘**（commit `8091db40`）：现有"pin"是 echarts markPoint symbol 非用户钉住，从零实现。localStorage[`pinned_indices`] + 📌按钮（`_appendPinBtn`）+ pin 复盘卡片（`_pinReviewCardHtml`/`_renderPinReview`）四段（📈走势摘要 5/20/60日涨跌+60日波动率+高低点 / 🎯最近信号 / 📊10d 6类信号胜率盈亏比 / 📋专属规则 6类策略desc+per-index filter sh/非sh）+ 跨tab状态隔离 + self-cleanup（`_onPinChanged` 检查 isConnected）+ 数据缓存双轨（signalsCache + _pinDataCache）。对应 P2-新-B 2b ✅

**未完成项保留**：~~B4 全市场485扩采集+OHLC（P1-新-C 阶段2 剩余，前端分页/搜索/持仓输入已完成）~~ ✅已完成(2026-07-25 AZ20) / ~~A6 PWA(P2-新-C)~~ ✅已完成(AZ20) / A14 echarts拆core / A15 拆chunk / C1 industry瘦身（~~C2 64M迁R2~~ 2026-07-24 取消，`ls -lhS static-site/data/` 确认无 64M 文件，最大 industry-3y.json 9.2M，C2 基于错误前提）

## ✅ 2026-07-24 工作闭环（futuresbackfill 漏跑排查 + A12 订阅推送 + etf 评分优化/配色 + ai 评分布局 + migration 实施 + C2 取消）

> 7/24 全天 7 项闭环。详见 `NOTES.md §48 小节AZ8`。

1. ✅ **futuresbackfill 漏跑排查**（commit `9116e97f`，承接 AZ7 rzhb 误报根治同一改动）：**无真漏跑**。futuresbackfill 7/23 20:05/21:00 两次 `exit=0 duration=24min/52min` 正常完成。schedule_monitor 报漏跑 = 整点竞态误报（21:00 futures/21:30 etf/23:00 rzhb 同因，监控和任务同整点 launchd 触发，读 log 时"开始"行未刷入）。修复已在 AZ7 落档（`schedule_monitor.sh` L109 `+60s buffer` + `rzhb_backfill.sh` trap refresh_stats EXIT）。**决策**：futures_backfill 不需加 trap（走 deploy.sh 间接刷 stats，与 rzhb 独立直跑不同）。7/24 00:00 后 alerts=0 无告警。**2026-07-29 补注**：push 失败根因已修（commit `e6422edf`，7-28 21:00 deploy.sh rebase 撞 static-site/data/*.gz 二进制冲突 abort 致 push 永久失败触发 log_anomaly，deploy.sh L290-360 rebase 数据冲突自动 --theirs=本地最新 export + 非数据冲突保守 abort），详见 NOTES §48 AZ59
2. ✅ **C2 64M 迁 R2 取消**（无 commit）：`ls -lhS static-site/data/` 确认无 64M 文件，最大是 `industry-3y.json` 9.2M。C2"64M 迁 R2"基于错误前提（主控推荐时记错），取消。C2 agent session 被 A12 cron prompt 覆盖（报 A12 结果），但本就无需做
3. ✅ **A12 订阅推送 - 前端**（commit `c703a584`）：指数卡片 h3 末尾 🔔 按钮 + 订阅管理 modal（填邮箱/chat_id + 选标的 + 选信号 6 类 + 已订阅列表脱敏），localStorage `sub_user_info` 免重复输入
4. ✅ **A12 订阅推送 - 后端**（commit `3d29c05c`）：`config/subscriptions.json`（gitignore）+ `.example` 模板 + `app/main.py` /api/subscribe（GET 脱敏列表/POST 创建更新/DELETE）+ `scripts/check_signals.py` `push_subscriptions`/`load_subscriptions`/`save_subs_notified`（独立去重 `subs_notified.json` 7天清理）+ `scripts/notify.py` `send_to`（email+chat_id）。⚠️**线上限制**：ss.fx8.store 纯静态站无 FastAPI 后端，线上 `/api/*` 全 404。订阅推送本身可用（launchd 跑 check_signals 读本地 config 推送）。线上管理订阅需手动编辑 `config/subscriptions.json`。对应 P2-新-K ✅
5. ✅ **etf 评分多列网格布局 + 配色**（commit `14ce6355`）：多列网格 `grid-template-columns: repeat(auto-fill, minmax(280px, 1fr))`（移动端降 1 列）+ 配色 buy 暖红粉橙 `#fdecec`/`#c0392b` / sell 青蓝 `#e7f0f7`/`#2c6e8f` 避免纯绿纯红
6. ✅ **etf 配色淡雅低饱和**（commit `177e1b0a`，覆盖 14ce6355 第一版配色）：AskUserQuestion 用户选"淡雅低饱和"。buy `#faf0f0`/`#a05050` / sell `#eef3f6`/`#5a7a8a`，`_etfScoreColor` 同步（buy 80+`#a05050`/60+`#c08080`，sell 80+`#5a7a8a`/60+`#8aaab8`），dark/redgold 主题变体同步。比 14ce6355 更柔和（粉橙->淡粉，青蓝->灰蓝）
7. ✅ **ai 评分布局**（commit `0ef19bdc`）：`lab.js renderAIScoreListLab` 持仓自查前置 1 列 + 买清单/卖清单左右并排（`.lab-aiscore-grid` grid 1fr 1fr，`@media max-width:900px` 降 1 列）。lab URL：https://ss.fx8.store/#lab -> 策略实验 -> AI 评分
8. ✅ **migration 实施**（commit `1f95ba2e`）：用户决策"etf 评分暂不迁移（首页保留），custom 下 2 个 3 级 tab [AI预警][AI评分]"。`lab.js` custom 2 级 tab 下加 3 级 tab，仿 `_SCAN_CHILDREN` 机制定义 `_CUSTOM_CHILDREN=["aiwarn","aiscore"]` + `_CUSTOM_CHILD_LABELS`。AI预警(aiwarn)= `renderCustomAnalyzeLab` 原 custom 内容打包；AI评分(aiscore)= `renderAIScoreListLab`（原 2 级 tab 降为 3 级子 tab，渲染函数零改动，`0ef19bdc` 布局保留）。`_LAB_SUB_TABS` 5->4 项（去 aiscore）。旧 `#lab?sub=custom` 兼容跳 aiwarn。etf 评分不迁移（首页底部导航 ETF评分 tab 保留）

**未完成项保留**：~~B4 全市场485扩采集+OHLC（P1-新-C 阶段2 剩余）~~ ✅已完成(2026-07-25 AZ20) / ~~A6 PWA(P2-新-C)~~ ✅已完成(AZ20) / A14 echarts拆core / A15 拆chunk / C1 industry瘦身（~~C2 64M迁R2~~ 取消）

## ✅ 2026-07-24 晚续闭环（国债波段策略 + hands终极 + intraday修复 + schedule_monitor午休 + 08报告归档）

> 7/24 午后~晚间国债卖点三轮迭代 + 买点 hands 终极 + intraday 推 main 修复 + schedule_monitor 午休告警修复。详见 `NOTES.md §48 小节AZ9`。本节 5 commit 待 15:35 收盘后主控 merge feat/b4 -> main + deploy（盘中不 deploy）。

1. ✅ **国债 A1 回退**（无 commit，checkout + DB 重算）：A1 std2σ 方案致三国债 sell 82/64/69 kelly 全负，回退原版 hh20*0.95（sell=0 恢复，sell_stop_loss 47/61/61 保留）。否决原因：kelly 全仓评估长期上行资产方法错
2. ✅ **国债 B 方案否决**（无 commit，4+2 回测全不达标）：B1/B2/B3/B4 + B1 严格版 + B1 分时段无一达标（kelly>=0.3 且 win_rate>0.5）。2015 年后国债长期上行 kelly 全负（-0.16~-2.86），结构性问题非参数可调，国债不适合标准卖点
3. ✅ **国债波段策略实施**（commit `06055972`，feat/b4，待 deploy）：`signals.py` `compute_band_signal`（RSI14+乖离+布林，减仓/接回/止损）+ 三品种 sell 调用 + 前端 `band_hold` 橙展示。回测 future 1296 严格双赢/etf 290 放宽双赢/idx 降风险（夏普 2.80->3.58）。**待 15:35 deploy 上线**
4. ✅ **买点 hands 终极方案 v5**（commit `13cbdf6b`，已 push main + 3 域名验证）：多维度综合（机会35+趋势20+动量15+波动15+流动性5+回撤10，阈值60/50/40，有加有砍）+ 极端 0 手（low<35）。buy_list 3 手 80%->15%，两处逻辑统一为 alert_score.py 一份（消除重复）
5. ✅ **schedule_monitor overview 滞后告警修复**（commit `497e7a5a`，已 push main）：时点 0930->0950（避开开盘空窗）+ 多域名容错（3 域名任一不 lag 即 OK）
6. ✅ **intraday 推 main 修复**（commit `b2eb9fa9`）：stash 工作区残留 -> force push main fast-forward -> stash pop 恢复。3 域名验证 collected_at=10:49:28
7. ✅ **intraday_snapshot.sh 根治 rebase 阻塞 + alert_analyze position**（commit `2bbf7bae`）：L178 `git checkout -- .` 兜底清 unstaged 残留根治 rebase 阻塞 + 70 个 alert_analyze position 字段重生成（修复指数弹窗"数据不足"）
8. ✅ **schedule_monitor 午休告警修复**（本节 commit）：L147 加 `not ("1130" <= now_hm < "1315")` 排除午休窗口（A股 11:30-13:00 无交易，overview 停在 11:30 快照直到 13:05 更新，12:15 起 lag>30min 误报 SEVERE）。非交易日已由 is_trading_day() 排除
9. ✅ **08 买卖点回测报告根副本清理**（无 commit，已归档 `62ba37c4`）：`docs/archive/08-买卖点策略深度回测.md` 早已归档（244 序列=13指数+3红利+31行业+200个股，12策略×4周期×4 horizon）。根目录残留 untracked 同名副本元数据矛盾（标的 129 序列 vs 脚注 244 资产，cutoff 07-23 vs 脚注 07-06），是不一致部分重生成版。保留归档可靠版（244 序列一致），删除根目录矛盾副本，08 无需新 commit

**用户准则 2 条（已落 CLAUDE.md §5 / memory）**：①方案选择默认准则 3 条（完整正确+不以工作量偷懒+一步到位终极方案不妥协）②卖为降风险非趋势放弃（长期上行≠只买不卖，波段仓位管理评估用波段收益非 kelly 全仓）

**教训 4 条**：①A1 kelly 全仓评估长期上行资产方法错 ②intraday_snapshot.sh git add 通配隐患（git checkout -- . 兜底清残留）③§11 轮询用 stat -L 查 .jsonl 实际 mtime（非 .output 符号链接）④午休告警误报（1130-1315 排除）

**48h 监控运行中**：caffeinate 48h（07-23 ~08:45 启动，PID 98731，-t 172800 自动退出）运行至 07-25 ~08:44，监控 launchd 计划任务 + schedule_monitor heartbeat。期间 schedule_monitor 每 15min 跑一次，heartbeat 写 /tmp/schedule-monitor-heartbeat.txt

**未完成项保留**：~~B4 全市场485扩采集+OHLC（P1-新-C 阶段2 剩余）~~ ✅已完成(2026-07-25 AZ20) / ~~A6 PWA(P2-新-C)~~ ✅已完成(AZ20) / A14 echarts拆core / A15 拆chunk / C1 industry瘦身 / ~~国债波段策略待 15:35 deploy 上线验证~~ ✅已deploy上线(commit `efac8b7b` cherry-pick of `06055972` 在 origin/main，续16 L83 三站验证通过，`ed447c2c` docs 确认 deploy 上线完成)

**教训**：glm-5.2 安全分类器时好时坏（A12 派发两次失败，cron 5 分钟后重试成功）；migration 调研 agent 卡死（jsonl mtime 27 分钟没动），基于进度文件方案 A + 用户确认直接派实施不重派调研；A12 cron 07:14 触发和 etf 优化 agent 撞 app.js（14ce6355 etf 优化 -> c703a584 A12 前端基于 etf 版叠加，两者共存）

## ✅ 2026-07-25 续12 闭环（csi_div ETF映射修正 + rzhb/etf新时点排查 + 信号拟合度调研）

> 7-25 三项工作落档。详见 `NOTES.md §48 小节AZ23`。项1 已上线,项2 plist 今晚首次触发待验证,项3 调研结论待用户决策是否改进。

1. ✅ **csi_div ETF 映射修正**（commit `c4613e21`，origin/main fast-forward f6432266..c4613e21 非force push）：`scripts/build_board_etf_map.py` L114 `"csi_div": ["515080","515100","515090"]` -> `["515080"]`。原因:515100 红利低波100ETF景顺跟踪中证红利低波动100(非中证红利跨基映射错);515090 可持续发展ETF博时+成交额93万死流动性。顺带复核 div_lowvol/sz_div/515450/481012 均正确不动。线上 ssd.fx8.store/index/csi_div-all.json etfs 只剩 515080(R2 186/186)。引入时点 `61be8e72`(07-23)加 INDEX_ETF_MAP,bj50 修复 `38eb8741` 未顺带复核其他红利指数本次补。deploy.sh 自动 data update commit `f6432266` 含新 L114 重新生成的 index/*-all.json
2. ⏳ **rzhb/etf 新时点排查**（plist已生效,今晚首次触发,周六交易日闸门跳过,周一07-27真采验证）：rzhb-backfill plist `{19:15}`(改自23:00,07-24 23:12改 launchctl loaded确认);etf-national-team plist array `{20:7}`主槽+`{21:30}`兜底槽(07-24 22:56重载 commit `56770911` runs=0);launchctl list rzhb/etf 均 loaded LastExitStatus=0。etf exit=None 根因:07-24 20:07 collector 并发采1374只ETF撞 libmini_racer FATAL(address_pool_manager.cc(67) Check failed) python被SIGTRAP(signal 5)杀退出码133,旧版 backfill.sh collector crash 不写 fallback DONE 行 -> gen_schedule_stats parse_etf_nt pending_start -> exit=None,连锁 deploy.sh 也失败(non-fast-forward+rebase撞 unstaged changes)。已修复 commit `afd9b5a8`(07-25 05:23)加 FINAL_RC 综合退出码+fallback DONE 行,今晚若再crash记真实 exit=133 不再 None
3. ✅ **信号拟合度调研结论**（纯调研无 commit,中偏高/过拟合嫌疑中高,待用户决策是否改进）：
   - **拟合度中偏高**:核心信号 C1/B1/D1/Supertrend/Donchian/MACD/Bollinger 用业界标准参数稳健低嫌疑,叠加 per-index 调参+多轮迭代+小样本拉高
   - **过拟合嫌疑中高分级**:高嫌疑(sh C1|D1a 上证专属5阈值 / h5 R2四条件 / 国债波段 cgb_idx 夏普3.58>3进可疑区 / hands v5 六维4档 / sw_801110 per-index);中嫌疑(alert_score H/L 权重基于2021/2024顶部拟合 120日滚动百分位有缓冲);低嫌疑(C1/B1/D1/标准指标业界标准参数);小样本(kc50 22笔 / us_spx 13笔 / hstech 20笔 / div_lowvol 30笔 <30无统计意义)
   - **最大过拟合源**:生产 signals.py 全样本调参无 train/test split/walk-forward(grep 0 命中坐实),只有 lab 候选信号做样本外(70/30)
   - **是否公布**:lab 已公布样本外 tab/过拟合度公式 overfit=|train_ret-test_ret|(lab.js L3932)/OOS综合分/参数敏感扫描(7策略)/5窗口交叉验证/免责声明;**未公布**生产 signals.py per-index 调参细节 / alert_score 权重拟合依据 / 国债夏普3.58 / hands v5 回测 / 整体拟合度综合评分(无) / trade_sim 无 sharpe 字段
   - **参考标准**:夏普>1可用/>2优秀/>3可疑过拟合/>5必过拟合(cgb_idx 3.58触发);参数数<样本量1/10(Bailey 2014);样本<30笔无统计意义;胜率>80%+盈亏比>3几乎必过拟合(div_lowvol PL5.35/sz PL5.98需警惕);PBO≥50%严重过拟合/PSR≥95%夏普可信(López de Prado)
   - **建议(若改进)**:生产 signals.py 引入 walk-forward / per-index 调参收敛为通用规则+1-2个 regime 参数 / trade_sim 加 sharpe 字段>3标红 / 小样本<30笔前端标注仅供参考不进三档 chip / 过拟合度分级<5%绿 5-15%黄 >15%红

**未完成项保留**：~~rzhb/etf 新时点今晚19:15/20:07/21:30 首次触发待验证(周六交易日闸门跳过周一07-27真采)~~ ✅已闭环(AZ49 B节确认etf 20:07 exit=0+1376只ETF+libmini_racer未复现) / ~~信号拟合度改进建议待用户决策是否实施~~ 部分已实施（walk-forward优化 `b24b13e6` csi_div 4.5->3.5通用化去per-index过拟合 + `3255e30f` sh D1a去除 WF夏普0.773->1.602 / 小样本前端标注 _OVERFIT_OR_SMALL_SAMPLE_IDS 7品种 / sharpe>3红线标注 `62e7d19e` 续17 + 过拟合度分级颜色 `408a4c51` AZ81 四档红橙默认灰+符号 全闭环）/ ~~B4 全市场485扩采集+OHLC~~ 已完成(2026-07-25 AZ20)/ ~~A6 PWA~~ 已完成(AZ20)/ A14 echarts拆core / A15 拆chunk / C1 industry瘦身

**教训**：①ETF 映射加 INDEX_ETF_MAP 后需全指数复核(bj50 修复未顺带复核 csi_div/div_lowvol 红利指数跨基映射易错,本次补复核 csi_div 修正)②launchd 新时点首次触发前 crash 不写 fallback DONE 行致 exit=None 假象,FINAL_RC 综合退出码+fallback 行根治(afd9b5a8)③生产 signals.py 无 walk-forward 是最大过拟合源(grep 0 命中坐实),小样本<30笔无统计意义需前端标注,夏普>3 触发可疑过拟合红线(cgb_idx 3.58)

---

## 🆕 2026-07-28 待办（监控4修复建议，2026-07-28 监控3异常自愈排查得出）

> 详见 NOTES §48 AZ56。3 异常已自愈非活跃问题（ETF国家队/指数补采兜底/期货机构持仓），4 条修复建议待定优先级。

1. ✅ **ETF libmini_racer 根治**（2026-07-29 方案 A+C3 已实施 commit `3e0676aa`）：7-24 collector 撞 libmini_racer SIGTRAP(133) 致 ETF 国家队 schedule_stats 滞后至 7-27 才自愈。V8 isolate 非线程安全，B4 已用 ProcessPoolExecutor 进程隔离采集（AZ20），但 collector 单进程内仍可能撞 SIGTRAP。**2026-07-29 根治**：etf_national_team.py pipeline_intraday_close 走 ProcessPool（原 12 只串行）+ _run_with_processpool 辅助函数（L116-165，BrokenProcessPool 重启 pool 1 次继续剩余仍失败才 fallback 串行，替代 faba0f08 直接 fallback），三处统一调用消除重复，防 V8 单进程理论 SIGTRAP。详见 NOTES §48 AZ59
2. ✅ **gen_schedule_stats pending_start 读真实退出码**（已实施 commit `3a1ba16e`）：原 exit=None 掩盖 crash（7-24 ETF collector SIGTRAP 退出码 133 被 None 掩盖，致 schedule_stats 滞后才暴露）。gen_schedule_stats.py 已加 `launchctl_last_exit`（AZ42），本次补 pending_start 也调 `launchctl_last_exit` 读真实退出码。验收：gen_schedule_stats.py L385-411 "P1 稳定性(2026-07-29): 所有模式(含 etf_nt)pending_start 都读 launchctl_last_exit" + L391 `real_exit = launchctl_last_exit(LABEL_MAP.get(t["task"]))` + pending_crash_retry 标 anomaly
3. ✅ **deploy.sh rebase 失败 git stash**（已实施 commit `56770911`）：原 7-27 16:35 指数补采兜底 deploy push 失败（non-ff + rebase 失败 abort 退出），7-28 02:00 自愈。deploy.sh L141-160 rebase 段原 abort 退出等人工处理（§8 规定 agent 不得擅自 force）。本次加 rebase 失败前 `git stash` 自动暂存 unstaged，rebase 成功后 `git stash pop`。验收：deploy.sh L261-286 stash 逻辑完整（L265 `git stash push -m "deploy.sh-rebase-..."` + L274-278 `pop_rebase_stash()` helper + L286 push 后调 pop_rebase_stash）+ L290-360 rebase 数据冲突自动 --theirs=本地最新 export（commit `e6422edf` 补）
4. **futures 非交易日 dur=0s 不改**（确认非 bug，保持现状）：7-26 21:00 期货机构持仓 dur=0s（周日非交易日正常跳过）。非 bug 不需修复

---

## ✅ 2026-07-28 ETF统一+自动采集待办（全闭环，详见 NOTES §48 AZ57）

> 用户质疑 sh 用510050近似错（实际8个精准ETF跟踪上证综合指数000001），且不能每个指数/行业都硬编码。3套ETF系统（前端标签 board_etf_map.json / 回测chip index_etf_map.json / app.js硬编码 _TRADE_SIM_ETF_NAMES）需统一为1套+自动采集。**2026-07-28 晚续全闭环**：ETF补采治本+回测切窗口bug修复+HTML5窗口+撤销方案F。

1. ✅ **自动采集方案深调研完成**（方案D选定，用户定"先d 不行再e"）：dataPro全量查1555只ETF建 etf_index_map.json(etf_code->跟踪指数)，配额不够降级方案E混合fundf10爬虫。覆盖所有指数，新ETF上市不漏
2. ✅ **统一实施已上线+sh改8精准ETF完成**（commit `de4be178`）：board_etf_map.json唯一源+simulate_trade首位+app.js标签+回测chip 已上线；sh改8精准ETF（510210成交额14.13亿首位，6纯被动 approx=false+2增强 approx=true，不含510050）；sz(159903精准)+港股 hsi 159920/hstech/hscei 510900 已修
3. ✅ **方案D第一阶段建表完成**：dataPro查1555只ETF建 data/etf_index_map.json（1555只/ok=1192/上证综指8个全到位），dataPro MCP 单查ETF返回 track_index_code
4. ✅ **方案D第二阶段完成**（commit `6482d461`）：改 build_board_etf_map.py 用 etf_index_map.json 自动采集替代硬编码INDEX_ETF_MAP，建反向映射 {track_index_code:[etf_code]} 按 amount 降序取 ETF，重新生成 board_etf_map.json。修3硬编码bug：hscei 513900->510900 / hsi 513600->159920 / sz 159943->159903
5. ✅ **统一检查所有指数+行业板块相关ETF完成**：build_board_etf_map 重跑 59空->16空，行业ETF全恢复（证券512880/银行512800/通信515880/军工512660等），sh=8个精准ETF全到位
6. ✅ **模拟回测重跑完成**（commit `78eae801`+`63a0daee`）：simulate_trade.py --all --html 重跑103成功，行业ETF etf_code全恢复（补采前=None），5窗口.s各行业不同（防退化成功）；ETF历史K线补采1228只ok ETF入etf_daily表（252516->1034267行，>=252天ETF 17->885只）治本回测切窗口数据不变bug
7. ✅ **hscei精准ETF确认完成**：513900港股通100不精准已改 510900（commit `6482d461` 修硬编码bug），510900 跟踪恒生中国企业指数HSCEI（approx=false）

**教训**：①3套ETF系统不同步致 sh/sz 回测chip有ETF标签无的视觉割裂（board_etf_map.json vs index_etf_map.json vs _TRADE_SIM_ETF_NAMES）②build_board_etf_map.py L103注释"sh无精准跟踪ETF"是错误判断，实际8个精准ETF（用户质疑纠正）③akshare fund_etf_hist_sina（新浪源）可拉全史，东财 fund_etf_hist_em 被封需换源④首位=关联性最大(纯被动精准优先)+体量最大(成交额降序)，510210非510980(跟踪误差低但成交额小)非510050(跟踪上证50≠上证指数)⑤回测切窗口退化根因=ETF上市晚+get_signals按etf_close_map过滤丢上市前signals致5窗口全退化全史跑同一批，治本=补采ETF全史非调过滤逻辑⑥展示源不应过滤（方案F设计错误），board_etf_map.json是展示源过滤<252天ETF是simulate_trade运行时过滤职责，撤销方案F保留方案D是正确分层

---

## ✅ 2026-07-29 app.js 3处修复+回退1b（全闭环，详见 NOTES §48 AZ60）

> 用户反馈首页盘中大量⚠滞后提示（"等盘中刷新或update_all尚未运行"对盘后 update_all 盘中提示无意义）+兜底刷新3m太慢（别的电脑9:45自己9:35）+小卡角标兜底后不更新（大卡9:45小卡还9:35）。a0e2498+a8b57a38 调研，a7773bc 实施。**3项均无独立 TASKS TODO 条目**（修复3根治 AZ54 P1-3[commit 4004f231]遗留 bug，其余2项 in-session 发现），本条会话状态即为落档。

1. ✅ **修复1a t0兜底拆分**（app.js L4124-4137）：`getCardTimeBadge` t0 兜底分支按场景拆分（盘中 dataDate===ptd=T+1性质正常等待⏳待盘后更新[t1-pending] / 盘中 dataDate<ptd=真异常⚠滞后[t1-stale] / 盘后 dataDate<baseline⚠滞后），删"等盘中刷新或update_all尚未运行"误导文案，ptd 在 L4060 算出 t0 分支复用。解决 ma_alignment/ad_line/volume_ratio/new_high_low/position 5 卡片（baostock stock_daily 盘后才出）盘中停 T-1 被误判⚠滞后
2. ✅ **修复1b回退**（commit `5473bf32`）：原实施把 5 卡片 srcClass t0->t1，用户"保证逻辑不变不要只修bug而修bug"，回退 5 卡片保持 t0（L6411/6442/6481/6522/6558），走修复1a t0 兜底拆分显⏳待盘后更新。t0->t1 会改 baseline（snapDate->ptd-1）+显示（⏳待盘后更新->📅T+1）+需配 `T1_COLLECT_DEADLINE` 违反"逻辑不变"
3. ✅ **修复2 关键时点1m刷新**（commit `a0b78a18` sw a58，L5118-5136/5217/5346）：新增 `_INTRADAY_SNAPSHOT_TIMES`（27 盘中时点 9:25-15:35 每 10min，plist 确认）+`_isKeyRefreshMoment`（±2min 窗口）+`_overviewRefreshDelay`（关键 60s/非关键 3min）。`_scheduleNextOverviewRefresh` 低频兜底 delay 替换为 `_overviewRefreshDelay()` 动态返回，debug 显示"低频兜底(关键1m)"，保留自适应 15s 高频层，兜底铁律 delay 最大仍 <=3min
4. ✅ **修复3 小卡角标重绘**（L5912-5927）：KPI 小卡 `_badge` const 改 let + 拼装后用临时 wrapper 解析 span 打 `data-badge-date`/`src`/`srckey` 属性（与 `addCardTimeBadge` L4139-4141 同款命名），`refreshCardTimeBadges` 的 `.card-time-badge[data-badge-date]` 选择器能选到 KPI 小卡重绘，异常 badge🚨不打属性避免被重绘成正常 badge。**根治 AZ54 P1-3**（commit `4004f231`）遗留 bug：当时 `refreshCardTimeBadges` 只覆盖 `addCardTimeBadge` 大卡路径，漏 KPI 小卡 L5878 innerHTML 拼接路径

**构建+版本**：`build_min.py` + `bump_asset_version.py`（?v=25ee0e75）+ sw.js `CACHE_VERSION` a56->a57->a58（§9 铁律1改 app.js 必 bump sw）

**commits**：`a0b78a18`（3修复 t0 兜底拆分+T+1归位+关键时点1m+小卡角标重绘） + `5473bf32`（回退1b 5卡片保持 t0）。push feat+main。线上 ss.fx8.store+sss.sugas.site 验证通过（sw a58+app.min.js?v=25ee0e75）

**主控验收**：grep 确认 5 卡片回 t0（L6411/6442/6481/6522/6558 全"t0"）+修复1a/2/3保留（L4124/L5118/L5912）+sw a58 本地线上一致

**教训**：①AZ54 P1-3 加 `refreshCardTimeBadges` 时漏了 KPI 小卡 innerHTML 路径（L4147 注释自己列举 L5184/L6734/L7113 漏了 L5878 KPI 小卡），badge 渲染有两套路径（大卡走 `addCardTimeBadge` 打 data-badge-date，KPI 小卡走 L5878 innerHTML 拼接无 data-badge-date），下次加被动重绘前要先 grep 出所有 badge 拼接路径逐路径确认是否打 data 属性 ②修 bug 勿改逻辑：t0 兜底拆分能在 t0 分支内解决盘中 T+1 误判，不需 t0->t1 改 srcClass（用户"保证逻辑不变"原则），t0->t1 是"修 bug 而修 bug"改变 baseline/显示/配置 ③a0e2498 调研误报 `signals_today` 末位 BUG（称 L6178 取末位作 dataDate=0717 触发⚠滞后），主控 grep 验收发现实际 L6178 用 `r.date` 不取末位，排除该修复（§0 验收铁律价值） ④实施 agent 第一次没回退修复1b（已 commit+push），主控 SendMessage 二次明确要求才回退（commit `5473bf32`）：派 agent 实施后若用户提出新约束，主控必须显式 SendMessage 传达+要求回退已 commit 部分，不能假设 agent 会自己意识到新约束

---

## ✅ 2026-07-29 晚续20 5项闭环上线（usdcnh验证 + bump根治 + lab HTML + 监控深查3根因 + Win通知P2-新-W）

> 本轮 5 项全闭环上线，主控逐字验收通过。详见 `NOTES.md §48 小节AZ61`。commit 链：`7de49686` / `632feb4a` / `e6422edf`（AZ59已落档）/ `4c4be0a8` + merge main `601a9da7`。sw.js a58->a59。

1. ✅ **usdcnh 7-27 验证通过**（承接 H.3 遗留防复发）：本地 `global-all.json` extras.usdcnh 末值 `{date:20260727, value:679.11}`，线上 ssd.fx8.store 三源（ss.fx8.store / sss.sugas.site / sss.sugas.site 三域名）一致。`currency_boc_sina` 主源稳定，无需手动 backfill。原 TASKS 待办（L119/L124/L194 三处）已标 ✅。

2. ✅ **bump_asset_version.py 日期逻辑根治**（commit `7de49686`）：**关键纠正**——a54 是 sw.js `CACHE_VERSION` 后缀（`v2-20260720-a54` 格式）非 git commit；`20260720` 是手工误写非脚本 bug（原 bump 脚本只用 md5 内容哈希无日期逻辑）。新增 `today_version()` 用 `ZoneInfo("Asia/Shanghai")` 显式时区 + `bump_sw_version()` 正则同步 sw.js 日期部分（保留 `vN/aM`，幂等），main() 末尾自动调用。单元测试 `today_version()=20260729` 通过。另确认 context 注入的 `currentDate 2026/07/20` 过时，真实北京时间 7-29 CST，脚本以 `ZoneInfo` 实时取为准。

3. ✅ **update_lab.sh 加第 12 步 simulate_trade --html**（commit `632feb4a`）：`--output static-site/trade_sim.html` 指定 git tracked 路径（默认 `trade_sim_{index_id}.html` 被 `.gitignore` 走 R2，不带 `--output` 的批量 HTML 仍走 R2 不变）；失败不阻塞（`echo ⚠ 不 exit 1`，lab 流水线幂等）；步骤编号 `[1/11]` -> `[1/12]`，lab-auto 19:00 定时任务自动重生 trade_sim.html。**关键决策**：单文件非批量选 git tracked 路径（部署简单+CF 直接服务），批量大文件走 R2（s.sugas.site 300MB 限制）。

4. ✅ **监控异常深查 3 类根因**：
   - ① **futures_backfill deploy push 失败持续 1 天+**：根因旧版 deploy.sh rebase 撞 20+ `static-site/data/*.json.gz` 二进制冲突直接 `abort + exit 1`。修复 `e6422edf`（已到 origin/main + trade-data deploy.sh L306）：`git checkout --theirs`（数据文件冲突取本地最新 export）+ `git rebase --continue` + 重试 push。今晚 20:05 futures_backfill 定时任务自然验证。
   - ② **美股早采 last_run=None**：plist 7-29 07:52 创建错过 `StartCalendarInterval Hour=5` 首触，7-30 05:00 自动恢复（launchd 错过时点不立即触发，等下一个时点）。
   - ③ **ANOMALY 标记**：策略实验室已自动消除（`eb897914` PUSH_FAIL+PUSH_SUCCESS 抑制补丁 + intraday 重生成覆盖旧 stats）；期货机构持仓随异常 ① 修复消除（deploy push 成功后不再 log_anomaly）。

5. ✅ **P2-新-W PC浏览器通知方案 A 实施**（commit `4c4be0a8` + merge main `601a9da7`）：
   - **后端 `scripts/export_notifications.py` 333 行**：6 类触发（新信号/异常/综合预警/恐贪极值/涨停潮/盘后速递），复用 `signal_notified`/`anomaly_notified` 去重（与邮件/TG 共享后端 diff，不新增去重文件），输出 `static-site/data/notifications.json`。
   - **前端 `static-site/app.js` ~230 行**：🔔 开关 `initNotifyButton`（PC 显示移动隐藏 + `requestPermission` 用户手势合规 + `localStorage` 持久化）+ 工具函数 `showNotification` + 检测 `_checkNotifications`（fetch `notifications.json` + 30s 节流 + in-flight 去重）+ **三层去重**（后端 signal_notified/anomaly_notified + 前端 localStorage notified_keys + Notification tag）。
   - **关键决策：事件 hook 不改状态机**：`_doOverviewRefresh`（L5262）加 1 行 `document.dispatchEvent(new CustomEvent('ts:overview-refreshed'))`，`_checkNotifications` 监听该事件触发检测，不侵入 overview 刷新流程，原状态机/baseline/兜底两态逻辑保持不变。
   - **配置 + 上线**：`_NO_CACHE_URLS` 加 `notifications` 绕 5min SWR 缓存 + sw.js `a58 -> a59`（铁律1）+ index.html `?v=43df0499` + 线上 `notifications.json` 200。
   - **区域限定遵守**：未碰 `getCardTimeBadge` / 兜底刷新两态状态机 / 小卡角标 / `addCardTimeBadge`（AZ60 修复区域保持不变）。

**构建+版本**：`build_min.py` + `bump_asset_version.py`（?v=43df0499）+ sw.js `CACHE_VERSION` a58->a59（§9 铁律1改 app.js 必 bump sw）

**commits**：`7de49686`（bump 日期根治）+ `632feb4a`（lab HTML 第12步）+ `4c4be0a8`（Win 通知方案A）+ `601a9da7`（merge main）。push feat+main。线上 notifications.json 200。

**主控验收**：grep 确认 NOTES AZ61 小节存在 + TASKS 5项 ✅ 标记（usdcnh验证 L119/L124/L194 + P2-新-W L564）+ commit 链 + push feat + merge main + push main 全成功。

---

## ✅ 2026-07-29 晚续2 4项闭环上线（T+1治理全套 + intraday 11:32/15:02收尾 + Win通知试看逻辑 + 部署验证）

> 本轮 4 项全闭环上线，主控逐字验收通过。详见 `NOTES.md §48 小节AZ62`。commit 链：`67acb836` / `15cbd203` / `ab294860` / `c02078f3` / `dfcedc31`。sw.js a62->a63。

1. ✅ **T+1 治理全套**（采集侧 + 前端 + 颜色 bug，3 层闭环）：
   - **采集侧 commit `67acb836`**：`intraday_snapshot.py` 新增 `COMMODITY_CODES`（`nf_AU0` 金/`nf_SC0` 原油大写/`hf_CL` WTI/`hf_SI` 白银/`hf_OIL` 布伦特）+ `fx_susdcny` 离岸人民币 + `cn10y_etf`（sh511260 十年国债 ETF）盘中直采写 `daily_metric` 表 `source='intraday'`。**关键发现**：`AU0` 无 `nf_` 前缀返 2024 旧数据废弃用 `nf_AU0`；`sc0` 小写空 `nf_SC0` 大写有效；`hf_TNX` 美债源全空 `us10y` 保持 T+1。`config/indicators.yaml`：`gold` func=`futures_main_sina`（AU0 沪金主连人民币计价）；`usdcnh` 盘中由 intraday `fx_susdcny` 覆盖（历史仍 `currency_boc_sina` T+1）；`cn10y_etf` 新增指标注册。
   - **前端 commit `15cbd203`**：`_T0_EXTRAS` 7 项（`usdcnh`/`gold`/`oil`/`wti_oil`/`comex_silver`/`brent`）；`_KPI_T1_MOVED` C 组 8 项挪出首屏（资金面/换手率分布分位数/换手率>5% 占比分组）到 A 股指标走势图折叠区 L7959-7963；`T1_COLLECT_DEADLINE` 移除 `gold`。
   - **前端 commit `ab294860`**：回退 `cn10y`/`us10y`/`cn_us_spread` 到 T+1（采集侧确认国债仍 T+1，前端误改 T+0 修正），`_srcKey` 恢复映射。
   - **颜色 bug commit `c02078f3`**：`style.css` `.spark-foot` color `var(--text-3)`->`var(--text-1)`（4 皮肤色相明显）；`app.js` `rethemeCharts` 补 `markLine`/`markArea` label 切皮肤重注入。

2. ✅ **intraday 11:32/15:02 收尾时点**（plist 改动）：上午 13 次->14 次加 `11:32`（11:30 收盘后 2min 拿上午最终收盘价，保留 11:25）；下午 `15:05`->`15:02`（15:00 收盘后 2min）；共 27 次。修复用户报"角标卡 11:25 一个多小时看不到上午收盘信息"（原上午最后 11:25 午休前 5min 拿不到收盘价）。今天手动跑更新线上 `collected_at=12:02`（上午收盘价）；明天起 11:32/15:02 自动收尾。

3. ✅ **Win 通知试看逻辑**（commit `dfcedc31`，sw a62->a63）：方案 A 首次开启通知权限（`Notification.requestPermission` granted）后自动 `showNotification('通知已开启✅', '...', 'test-welcome')`；方案 B 已开启状态加试看按钮（`pc-notify-test-btn`）点击 `showNotification('测试通知🔔', '...', 'test-preview-' + 时间戳)`；移除旧 `test_enable`。承接 AZ61 P2-新-W Win 通知方案 A 上线，补"试看"闭环让用户首次开启后立即验证通知生效。

4. ✅ **部署验证**：3 域名（`ss.fx8.store`/`sss.sugas.site`/`s.sugas.site`）验证 sw.js `a63` + `app.min.js?v=608d7237` 含 `test-welcome`/`test-preview`（memory `deploy-verify-3-sites`：3 域名任一验证到新版即算上线 OK）。

**构建+版本**：`build_min.py` + `bump_asset_version.py`（`?v=608d7237`）+ sw.js `CACHE_VERSION` a62->a63（§9 铁律1 改 app.js 必 bump sw）

**commits**：`67acb836`（采集侧 COMMODITY_CODES 盘中直采）+ `15cbd203`（前端 _T0_EXTRAS/_KPI_T1_MOVED）+ `ab294860`（回退国债 T+1）+ `c02078f3`（颜色 bug）+ `dfcedc31`（Win 通知试看 a63）。push feat+main。3 域名验证 a63+?v=608d7237 含 test-welcome/test-preview。

**主控验收**：grep 确认 NOTES AZ62 小节存在 + TASKS 续21 4项 ✅ 标记 + commit 链 + push feat + merge main + push main 全成功。

**教训**：①bump 脚本时区必须显式 `ZoneInfo("Asia/Shanghai")`，mac 本地时区受系统设置影响，context 注入的 `currentDate` 是 session 开始时点跨日过时，脚本以实时 `ZoneInfo` 为准 ②`--output` 指定 git tracked 路径 vs 走 R2 选择准则：单文件非批量选 git tracked（部署简单+CF 直接服务），批量大文件走 R2（git 不适合大量大文件+s.sugas.site 300MB 限制）③事件 hook 不改状态机原则：在 `_doOverviewRefresh` 加 1 行 `dispatchEvent` 而非侵入 overview 刷新流程，监听方通过事件解耦，原状态机/baseline/兜底两态逻辑保持不变，区域限定遵守（不碰 AZ60 修复区域）④launchd `StartCalendarInterval` 错过时点不立即触发，属一次性漏跑非 bug，改 plist 时点后须等下一个时点自然触发，不手动 launchctl kickstart（除非紧急）⑤deploy.sh rebase 二进制冲突不能保守 abort（AZ59 教训本轮验证）：`static-site/data/*.json.gz` 是 export 最新产物，rebase 撞 .gz 冲突应自动 `--theirs=本地最新 export`，未来 .gz 冲突不再阻塞 deploy

---

## ✅ 2026-07-29 晚续3 1项闭环上线（分时图1min刷新同步底部涨跌幅+角标）

> 本轮 1 项闭环上线，主控逐字验收通过。详见 `NOTES.md §48 小节AZ63`。commit 链：`e9af8c85`。sw.js a63->a64。

1. ✅ **分时图1min刷新同步更新底部涨跌幅+角标**（commit `e9af8c85`，sw a63->a64）：用户反馈盘中分时图曲线走到 13:10、右上角 pct +0.31% 更新了，但底部涨跌幅 -9.90 卡住、角标卡 13:05。根因 3 条：①底部 spark-foot 仅 renderOverview 渲染一次（L6428）intraday/overview refresh 都不更新 ②底部数值语义错（`_chgText=closes[last]-closes[last-2]` 今日两点价差，与右上角 pct 相对昨收不同维度矛盾）③角标读 snap.datetime（10min 粒度）非腾讯 1min。**4 处改动 app.js**：L4816 新增 `_applyDynamicToSparkFoot(results)`（腾讯 price+preClose 更新底部，语义改相对昨收与 pct 同维度）+ L5127 `_doIntradayRefresh` 补调用（1min 刷新带动底部）+ L5128 补 `refreshCardTimeBadges(curSnap)`（1min 刷新带动角标）+ L4113-4114 `getCardTimeBadge` 盘中优先读 `_intradayDynamicTime`（腾讯 1min 替代 snap.datetime 10min，无则回退兜底）+ L4716 `fetchTencentMinute` 加 `cache:'no-store' + ?_=Date.now()`（防御性 cache-busting）。

**构建+版本**：`build_min.py` + `bump_asset_version.py` + sw.js `CACHE_VERSION` a63->a64（§9 铁律1 改 app.js 必 bump sw）

**commits**：`e9af8c85`（分时图1min刷新同步底部涨跌幅+角标 a64）。FF push main（`c280b02d..e9af8c85`），feat rebase 后 force-with-lease（feat 独用非 main）。3 域名验证 a64。

**主控验收**：grep 确认 NOTES AZ63 小节存在 + TASKS 续22 1项 ✅ 标记 + commit 链 + push feat + merge main + push main 全成功。

**教训**：①卡片多元素刷新路径必须全覆盖（4 套元素曲线/右上角 pct/底部 spark-foot/角标各路径独立，任一漏更新就视觉矛盾，同 AZ62 echarts markLine 切皮肤教训、AZ54 badge 两套路径教训）②同卡片多数值语义必须同维度（底部原"今日两点价差"与右上角"相对昨收"矛盾，应统一基准相对昨收，同 AZ62 前端 T+0/T1 对齐采集侧时点教训）③角标时间源必须与卡片主数据源同粒度（原 snap.datetime 10min 滞后腾讯 1min，角标应跟随主数据源，同 AZ62 11:32/15:02 收尾时点紧贴收盘 +2min 教训）④fetch 加 cache-busting 防御性兜底（`cache:'no-store' + ?_=Date.now()`，即使 CF Workers 无视 Cache-Control 浏览器层 no-store 仍生效作兜底）

---

## ✅ 2026-07-29 晚续4 1项闭环上线（修复 renderIntradaySection 顺序bug致 intraday 1min刷新失效）

> 本轮 1 项闭环上线，主控逐字验收通过。详见 `NOTES.md §48 小节AZ64`。commit 链：`0bf65496` + merge `a25ebb80`。sw.js a64->a65。

1. ✅ **修复 renderIntradaySection 顺序 bug 致 intraday 1min 刷新失效**（commit `0bf65496`，sw a64->a65）：AZ63（commit `e9af8c85`）加了 4 处改动想让分时图 1min 刷新同步更新底部 + 角标，但用户无痕模式验证仍不生效。Console 诊断 `_intradayRenderCtx=false` 定位根因。**根因（历史遗留 bug，非 AZ63 引入）**：`renderIntradaySection` L5048-5051 顺序错误——先设 `_intradayRenderCtx={sparkGrid, snap}` 后调 `_startIntradayRefresh()`，而 `_startIntradayRefresh` L5063 第一行调 `_stopIntradayRefresh()`，后者 L5077 `_intradayRenderCtx=null` 把刚设的 ctx 清空 -> `_doIntradayRefresh` L5100 早返回守卫命中 -> L5127-5128（`_applyDynamicToSparkFoot` + `refreshCardTimeBadges`）永不执行 -> 底部 spark-foot + 角标不更新 + 分时图曲线也不 1min 自动更新（用户之前看到的曲线更新是 overview refresh 3min 跑 `renderOverview` 顺带渲染，非 1min 定时器）。**修复**：交换 L5049-5050 两行顺序（只改顺序，2 行）——先 `_startIntradayRefresh()`（内部 `_stop` 清旧 ctx + 旧定时器再调度）后设新 `_intradayRenderCtx={sparkGrid, snap}`（不被 `_stop` 清空）。修复后 `_doIntradayRefresh` 恢复 1min 工作，AZ63 的 4 处改动才真正生效：曲线 + 右上角 pct + 底部 spark-foot + 角标时间全部 1min 同步更新。

**构建+版本**：`build_min.py` + `bump_asset_version.py`（`?v=5199516b`）+ sw.js `CACHE_VERSION` a64->a65（§9 铁律1 改 app.js 必 bump sw）

**commits**：`0bf65496`（修复 renderIntradaySection 顺序 bug a65）+ merge `a25ebb80`。FF push main。3 域名验证 a65（`ss.fx8.store` + `sss.sugas.site`）。

**主控验收**：grep 确认 NOTES AZ64 小节存在 + TASKS 续23 1项 ✅ 标记 + commit 链 + push feat + merge main + push main 全成功。

**教训**：①设状态 + 调启动函数的顺序必须"先启动后设状态"（启动函数内部会先调 stop 清理旧状态含清空 ctx，必须先 start 再设新 ctx，否则 stop 把刚设的新 ctx 一起清空，定时器回调命中早返回守卫永不执行，同 AZ63 教训①"刷新路径全覆盖"延伸：除覆盖所有 refresh 路径还要确认启动链路本身能跑到回调）②新功能验证"无痕模式仍不生效"先查 Console 状态变量（`_intradayRenderCtx` 等）确认回调链路是否走到，再排查改动本身，避免误判"自己改动错"反复改正确代码（同 AZ59 教训：表象与根因常错位，先诊断再动手）③历史遗留 bug 的潜伏条件 = 新功能依赖才暴露（原 `_doIntradayRefresh` 回调只有曲线/pct 更新，overview refresh 3min 顺带渲染掩盖了 1min 定时器失效，AZ63 把底部 + 角标塞进 `_doIntradayRefresh` 才让失效暴露；下次给历史函数加新逻辑前先 grep + Console 验证该函数调用链路是否真能跑到，避免新逻辑加在死代码上）④AZ63 + AZ64 两 commit 配合才完整修复（AZ63 加 4 处改动语义正确但跑不到 + AZ64 修顺序 bug 让 AZ63 跑到，缺一不可；单看任一 commit diff 看不出完整问题，验收"功能不生效"类 bug 修复要确认修复 commit 让原不生效改动真正跑到）

---

## ✅ 2026-07-29 晚续5-6 2项闭环上线（刷新后立即更新分时图+角标1min动态范围限制）

> 本轮 2 项闭环上线，主控逐字验收通过。详见 `NOTES.md §48 小节AZ65 + AZ66`。commit 链：`a6907d1d` + `221c4624`。sw.js a65->a66->a67。

1. ✅ **刷新后立即更新分时图底部+角标（不等1min首次 _doIntradayRefresh）**（commit `a6907d1d`，sw a65->a66）：AZ64 修复顺序 bug 后 `_doIntradayRefresh` 恢复 1min 工作，但用户反馈刷新页面后角标 + 底部先维持在 13:55，要等 1min+ 才开始动态更新。**根因**：`_startIntradayRefresh` L5067 调 `_scheduleNextRefresh`，首次 `failCount=0` -> `_delay=INTRADAY_REFRESH_MS=1min` -> `setTimeout(_doIntradayRefresh, 60000)`，刷新后要等 1min 才首次更新。**修复**：`renderIntradaySection` L5048-5056 设 ctx 后立即调 `_doIntradayRefresh()`，用腾讯实时价立即更新曲线 + 底部 spark-foot + 角标时间，不等 1min。`_doIntradayRefresh` 末尾 `_scheduleNextRefresh` 清掉 `_startIntradayRefresh` 设的 1min timer 并重设，不重复调度；`_refreshDynamicAll` 与 `renderOverview` L6477 调用共用 `fetchTencentMinute` in-flight 去重，重复 fetch 可控。修复后刷新页面瞬间即用腾讯实时价更新，无需等 1min。

2. ✅ **角标1min动态只限分时图指数卡片，其他卡片用后端快照时间**（commit `221c4624`，sw a66->a67）：AZ65 上线后用户反馈"其他卡片角标也跟着分时图 1min 动态更新了"，应该只分时图指数卡片用腾讯 1min 时间，其他卡片用后端快照时间。**根因**：`getCardTimeBadge`（L4077）方案B `_intradayDynamicTime`（L4113）在 `intraday && snapDate && dataDate===snapDate` 分支对所有 t0 盘中卡片生效 + `refreshCardTimeBadges`（L5128 在 `_doIntradayRefresh` 内）更新所有 `.card-time-badge` -> KPI 小卡 / ETF / 板块等所有盘中卡片角标变 1min 动态。**修复**：`getCardTimeBadge` 加 `isIndexSpark` 参数（默认 false），方案B分支改为 `_useDyn = isIndexSpark && _intradayDynamicTime`（只 `isIndexSpark=true` 用 1min，否则用 `snap.datetime` 10min 原逻辑）。`addCardTimeBadge` 加 `isIndexSpark` 参数 + 仅 true 时打 `data-badge-isdyn="1"` 属性。`refreshCardTimeBadges` 从 `data-badge-isdyn` 取 `isIndexSpark` 传给 `getCardTimeBadge` + 重绘保留属性。`spark-cell`（L6486）调 `addCardTimeBadge(...,true)` `isIndexSpark=true`；KPI 小卡 / 指数图表卡 / 行业 `spark-cell`（t1）不传（默认 false）走原逻辑。修复后只有分时图指数 spark-cell 卡片角标 1min 动态（与曲线同源），其他卡片角标用后端快照时间（与各自主数据同源）。

**构建+版本**：`build_min.py` + `bump_asset_version.py` + sw.js `CACHE_VERSION` a65->a66->a67（§9 铁律1 改 app.js 必 bump sw）

**commits**：`a6907d1d`（刷新后立即更新分时图 a66）+ `221c4624`（角标1min动态范围限制 a67）。FF push main。3 域名验证 a66 + a67。

**主控验收**：grep 确认 NOTES AZ65 + AZ66 小节存在 + TASKS 续24 2项 ✅ 标记 + commit 链 + push feat + merge main + push main 全成功。

**教训**：①首次更新延迟应零等待（定时器首次 setTimeout 有 delay，渲染入口应立即调一次消除首帧静态，定时器只管周期；同 AZ63 教训①"刷新路径全覆盖"延伸：覆盖所有 refresh 路径 + 渲染入口立即调一次）②同 fetch 多路径调用走 in-flight 去重（`_doIntradayRefresh` 1min + `_refreshDynamicAll` + `renderOverview` 3min 都可能调 `fetchTencentMinute`，in-flight 去重防多路径竞争）③定时器调度清旧重设防重复（"立即调 + 周期调度"组合时立即调的函数末尾清旧 timer 重设，保证任一时刻只有一个 timer）④角标时间源必须与卡片主数据源同粒度且按卡片类型区分（AZ63 教训③已提但实施时一刀切，应按卡片类型区分：分时图 spark-cell 主数据腾讯 1min -> 角标 1min，其他卡片主数据后端 10min -> 角标 10min，不能一刀切）⑤副作用隔离用显式参数标记（`isIndexSpark` 参数 + `data-badge-isdyn` 属性显式标记动态时间卡片，比隐式按类型判断更可控，refresh 时从属性取值不丢失）⑥AZ63-AZ64-AZ65-AZ66 四 commit 配合才完整修复（AZ63 加 4 处改动语义正确但跑不到 + AZ64 修顺序 bug 让 AZ63 跑到 + AZ65 刷新后立即更新消除 1min 首次延迟 + AZ66 角标范围限制隔离 1min 动态只到分时图指数卡片；四 commit 缺一不可，任一缺失都有视觉割裂）

---

## ✅ 2026-07-29 晚续7 1项闭环上线（技术参考点列表加评级/对错筛选+未结算hover+自动更新）

> 本轮 1 项闭环上线，主控逐字验收通过。详见 `NOTES.md §48 小节AZ67`。commit 链：`8f1002cb` + merge `194d55a2`。sw.js a67->a68。

1. ✅ **技术参考点列表加评级/对错筛选+未结算hover+自动更新**（commit `8f1002cb`，merge `194d55a2`，sw a67->a68）：用户提 4 点需求（①评级高/中/低点击过滤再点恢复+恢复全部按钮 ②"X对/X错/X未结算"也是筛选按钮 ③未结算 hover 说明 ④不刷新页面自动更新看到最新信号）。**调研**（agent a79561e8a + a3b8c7844）：代码位置 `_renderSignalGrid` L1267 / `_calcSignalAccuracy` L1223 / `_accHtml` L1354 / sigCard 调用 L6620；数据源 overview.json `signals_today`（`since_correct: true` 对 / `false` 错 / `null` 未结算），后端 queries.py L357 实时查 `signal_daily` 表无缓存；评级分档 score≥0.75 高 / 0.55-0.75 中 / <0.55 低；无现成筛选机制；自动更新现状缺陷 `_doOverviewRefresh`（3min/1min）只更新角标+通知+缓存不重绘 sigCard -> 角标更新但列表不更新（用户质疑"只是更新角标内容实际没自动更新"确认）；后端 `signals_today` 每轮 intraday_snapshot 10min 重算+push（agent a79561e8a 说"30min"是误读 intraday_snapshot.sh L2 过时注释，实际 plist 10min 调度 2026-07-28 从 15m 升 10m，a3b8c7844 纠正 queries.py L357 实时查 DB 无 30min 节流），无需改后端。**修复 4 部分**：①C 未结算 hover（L1385 N 未结算包 button + data-tip 说明"未结算=信号已发出未验证对错,含今日新信号/波段中性/等待收盘回填,收盘后转对或错",全局 _initTermPop 自动生效）②A 评级筛选（state.sigGradeFilter L10 null/high/mid/low + _renderSignalGrid filter L1273 kind==="signal" 按 score 分档 + 高/中/低改 button data-grade-filter L1380 选中态 sig-acc-filter-active + 末尾恢复全部按钮 L1383 仅 filter 激活时显示 + click 委托 toggle L6720 再点同档恢复 null；_calcSignalAccuracy 仍传原始 items 汇总条数字显示全量）③B 对错筛选（state.sigCorrectFilter + 对/错/未结算包 button data-correct-filter L1385 + filter 逻辑 L1283 since_correct true/false/null 映射 + click 委托 toggle L6729）④D 自动更新（_sigCardRenderedAt 模块变量 L1397 记录上次 collected_at + _rerenderSigCardContent L1402 增量替换 .signal-accuracy-summary+.signal-grid 保留 .card-time-badge 角标+.sig-intraday-hint + _maybeRerenderSigCard L1429 非概览 tab/无数据/同 collected_at 跳过 + sigCard 加 sig-card class L6697 + ts:overview-refreshed 监听器 L5863 加 _maybeRerenderSigCard 调用；筛选 state 由 _renderSignalGrid 内部读重绘自动保留）；CSS style.css L767-773 .sig-acc-filter/.sig-acc-filter-active/.sig-acc-reset。修复后评级/对错筛选 toggle+恢复全部按钮（汇总条数字始终全量）+未结算 hover 说明+盘中 sigCard 跟着 overview-refreshed 增量重绘后端每 10min 更新前端最迟 13min 可见。

**构建+版本**：`build_min.py` + `bump_asset_version.py` + sw.js `CACHE_VERSION` a67->a68（§9 铁律1 改 app.js 必 bump sw）

**commits**：`8f1002cb`（技术参考点列表筛选+未结算hover+自动更新 a68）+ merge `194d55a2`。FF push main。3 域名验证 a68。

**主控验收**：grep 确认 NOTES AZ67 小节存在 + TASKS 续25 1项 ✅ 标记 + commit 链 + push feat + merge main + push main 全成功。

**教训**：①overview refresh 路径要覆盖所有"用户期望自动更新"的卡片（`_doOverviewRefresh` 只更新角标+通知+缓存不重绘 sigCard，用户看到角标变列表不变质疑"只是更新角标内容实际没自动更新"；下次"页面不刷新也要自动更新"类需求逐个排查 overview refresh 路径覆盖了哪些卡片，未覆盖的 hook `ts:overview-refreshed` 事件增量重绘更解耦避免 refresh 函数膨胀）②增量重绘保留兄弟元素而非整卡重建（`_rerenderSigCardContent` 只替换 .signal-accuracy-summary+.signal-grid 两子节点保留 .card-time-badge 角标+.sig-intraday-hint 已由 refresh 路径独立更新，整卡重建会丢失角标刚更新状态+视觉闪烁；下次"某子区域需要重绘"时定位最小替换单元子节点 selector 保留同卡其他已更新兄弟）③筛选 state 放模块级由 render 内部读重绘自动保留（sigGradeFilter/sigCorrectFilter 放 state 模块变量 _renderSignalGrid 内部读并应用 filter 重绘时自动按当前 state 过滤无需额外"恢复筛选态"；下次"列表+筛选+自动重绘"组合时筛选 state 放模块级+render 内部读比放 DOM data 属性重绘后再读回更可靠）④agent 调研"X 分钟更新"结论先核对实际调度 plist 而非脚本文件头注释（a79561e8a 报"30min"误读 intraday_snapshot.sh L2 过时注释写 30min 但 plist 实际 10min 调度 2026-07-28 从 15m 升 10m 没改注释 a3b8c7844 纠正；下次调研"某任务多久跑一次"查 launchd plist StartCalendarInterval/StartInterval 而非脚本文件头注释注释易过时 plist 是实际调度源）

---

## ✅ 2026-07-29 晚续8 5项闭环上线（Mac Chrome 通知点击无响应/不弹修复）

> 本轮 5 项闭环上线，主控逐字验收通过。详见 `NOTES.md §48 小节AZ68-AZ72`。commit 链：`193beb21` + `30685ddf` + `4fd71a74` + `3c788360`。sw.js a68->a72。

1. ✅ **AZ68 SW showNotification+notificationclick 迁移**（commit `193beb21`，sw a68->a69）：Mac Chrome 通知点击无响应根因=page `new Notification()` + `onclick`，Mac Chrome 代理通知到 macOS 通知中心后页面失焦时 onclick 回传链路丢失（Win Chrome 走 Action Center 集成度高 onclick 稳定）；sw.js 无 notificationclick（架构缺口）。修复=sw.js 加 SHOW_NOTIFICATION message 代理（page postMessage 让 SW 弹通知）+ notificationclick 聚焦 tab + postMessage 触发页面 UI 反馈；app.js showNotification 改走 SW 代理 + clickAction 参数 + _handleNotifyClick（滚动到对应板块+高亮闪烁）；_processNotifications 10 处补 clickAction（信号/异动/预警/恐贪/涨停/收盘速递）；CSS .notify-flash 高亮。
2. ✅ **AZ69 pref null + controller null 修复-试看一键开启+SW ready 等 controller**（commit `30685ddf`，sw a69->a70）：AZ68 迁移后通知仍不弹根因=pref null（localStorage key=`ts_notify_enabled` 非 notifyPref 未开启，showNotification 第一行 `if (!_loadNotifyPref()) return false` 直接返回）+ controller null（SW activated 但硬刷时序未接管页面 controller.postMessage 报 null）。修复=试看按钮改一键开启（点击自动 _saveNotifyPref(true) + 请求 permission + 弹测试通知不再静默 return）+ showNotification controller null 时等 navigator.serviceWorker.ready 再 postMessage + ready 后 controller 仍 null 走降级 new Notification 带 onclick _handleNotifyClick + controllerchange 监听 + 诊断 console.log。
3. ✅ **AZ70 controller null 用 reg.active.postMessage 走 SW 路径**（commit `4fd71a74`，sw a70->a71）：AZ69 降级 new Notification Mac onclick 丢失（AZ68 教训①复现）。修复=controller null 时用 `reg.active.postMessage`（ready resolve 时 reg.active 是 active SW，postMessage 给 active SW 即可不依赖 controller 接管页面）-> SW 收 SHOW_NOTIFICATION 调 self.registration.showNotification + notificationclick（Mac 稳定）。`const sw = navigator.serviceWorker.controller || reg.active`，仅 reg.active 也 null 才降级。
4. ✅ **AZ71/AZ72 SW 诊断日志定位通知没弹**（commit `3c788360`，sw a71->a72）：AZ68-AZ70 修复后通知仍不弹，前三轮逻辑都对但用户硬刷拿不到新版 SW。加 SW 诊断日志定位：sw.js message SHOW_NOTIFICATION 分支加 console.log（收到/成功/失败）+ notificationclick 加 matchAll/focus/postMessage 各步日志。定位最终根因=SW 卡旧版 a69 不 update 到 a72（硬刷 Cmd+Shift+R 不触发 SW update check），用户手动 `navigator.serviceWorker.getRegistrations().then(rs=>Promise.all(rs.map(r=>r.unregister()))).then(()=>location.reload())` 注销旧 SW + 刷新强制重新注册新版后正常。
5. ✅ **最终根因 5 层**：①Mac 双重通知权限（浏览器级 + macOS 系统级，Win 只有浏览器级故 Win 正常 Mac 不弹）②page new Notification Mac 失焦 onclick 丢失③pref null（localStorage key=`ts_notify_enabled` 未开启）④controller null（硬刷后 SW 更新时序未接管 page）⑤SW 卡旧版不 update（硬刷不触发 SW update check SW 卡 a69 不更新到 a72，前三轮修复用户拿不到）。**用户验证：通知弹出+点击跳转正常 ✅**

**构建+版本**：`build_min.py` + `bump_asset_version.py` + sw.js `CACHE_VERSION` a68->a69->a70->a71->a72（§9 铁律1 改 app.js 必 bump sw）

**commits**：`193beb21`（SW showNotification+notificationclick 迁移 a69）+ `30685ddf`（pref null+controller null 修复 a70）+ `4fd71a74`（controller null 用 reg.active.postMessage a71）+ `3c788360`（SW 诊断日志 a72）。FF push main。3 域名验证 a72。

**主控验收**：grep 确认 NOTES AZ68-AZ72 小节存在 + TASKS 续26 5项 ✅ 标记 + commit 链 + push feat + merge main + push main 全成功。

**教训**：①Mac Chrome 通知双重权限（浏览器级 Notification.permission=granted 只是第一层，macOS 系统级通知设置系统设置>通知>Google Chrome>允许通知+样式横幅/提醒非无是第二层，Win 只有浏览器级故 Win 正常 Mac 不弹；排查 Mac 通知问题必查系统级设置）②page new Notification Mac 失焦 onclick 丢失 -> 迁移 SW registration.showNotification + notificationclick（Mac 稳定标准做法，SW 常驻不依赖 page focus；下次"通知点击"功能优先走 SW 路径）③controller null（硬刷后 SW 更新时序 clients.claim 未及时接管当前页面）-> 用 reg.active.postMessage 绕过 controller 依赖（reg.active 是 active SW postMessage 不依赖 controller 接管页面；下次"controller null"场景优先 reg.active.postMessage 而非降级 page 路径）④SW 更新卡旧版（硬刷 Cmd+Shift+R 不触发 SW update check SW 卡 a69 不更新到 a72）-> navigator.serviceWorker.getRegistrations().then(rs=>Promise.all(rs.map(r=>r.unregister()))).then(()=>location.reload()) 注销旧 SW+刷新强制重新注册新版，bump CACHE_VERSION 只让新 SW 破缓存不强制旧 SW update，用户硬刷拿新版需此手动注销或浏览器自动 update check 可能 24h（下次"SW 改了但用户硬刷拿不到新版"先让用户注销旧 SW 重注册不死磕代码）⑤pref localStorage key 是 ts_notify_enabled 非 notifyPref（NOTIFY_STORAGE_KEY 常量 L5566，排查"通知偏好没生效"先 localStorage.getItem('ts_notify_enabled') 确认值）⑥SW Console 看 SW 日志 chrome://inspect/#service-workers > 找 sw.js > inspect（不是 DevTools Console 下拉"top"下拉可能无 sw.js 选项；SW 内部变量如 CACHE_VERSION 只能在 SW Console 跑 page Console 报 not defined）⑦试看/测试按钮应一键开启全链路（用户点"试看"期望立即看到通知，若按钮只弹通知但 pref 未开启/权限未请求 showNotification 第一行 if (!_loadNotifyPref()) return false 静默返回用户以为按钮坏了；试看按钮应 _saveNotifyPref(true)+requestPermission()+弹通知三步合一用户一点即通）

---

## ⏸ 2026-07-29 晚续9 Safari通知兼容修复（用户验证搁置）

> AZ73: Safari 走 new Notification + permission 缓存绕静态属性 bug，Chrome SW 路径不变。详见 `NOTES.md §48 小节AZ73`。commit `f02245b5`，sw a72->a73。

1. ⏸ **AZ73 Safari兼容(Safari走new Notification+permission缓存绕静态属性bug+Chrome SW路径不变)**（commit `f02245b5`，sw a72->a73）：
   - **根因三重**：①Safari `Notification.permission` 静态属性不同步 bug（站点设置允许但 API 返回 denied，需完全重启 Safari 或清站点数据才同步）-- 用户"被屏蔽"直接原因 ②sw.js message event 调 `showNotification` Safari 不支持（Apple 限制仅 push event 支持，Chrome 允许 message event）③降级 `new Notification` 桌面 Safari 6+ 可用但被根因①挡住走不到。
   - **方案X**：`_isSafari()` 检测（UA 含 Safari 不含 Chrome/Chromium/Edge/FxiIOS）+ `_notifyPerm()` Safari 优先读 sessionStorage 缓存 `ts_notify_perm_cache`（requestPermission Promise 返回值，绕静态属性不同步 bug）+ `requestNotifyPermission()` async 函数 Safari 缓存 Promise 返回值到 sessionStorage + `showNotification()` Safari 短路走 `_fallbackNewNotification`（页面 new Notification 绕开 SW message event 限制，Chrome 走原 SW 路径不变）+ `updateBtnState`/点击处理 denied 分支加 Safari 专属提示（移除站点+Cmd+Q 重启恢复指引）+ 试看按钮用 `requestNotifyPermission` 复用缓存 + sw a72->a73。
   - **方案B（Web Push+APNs）列未来增强待办**（工作量大破坏架构）：VAPID+推送服务器+破坏现有前端轮询架构，本步用方案X 兼容。
   - **用户验证搁置**：Safari denied 需手动恢复（移除站点+Cmd+Q 重启），a73 代码已上线保留，未来用 Safari 时按恢复指引操作即可走 new Notification 路径。

**构建+版本**：`build_min.py` + `bump_asset_version.py` + sw.js `CACHE_VERSION` a72->a73（§9 铁律1 改 app.js 必 bump sw）。

**commits**：`f02245b5`（Safari 兼容修复 a73）。

**主控验收**：grep 确认 NOTES AZ73 + TASKS 续27 + commit 链 + push feat + merge main 全成功。

## ✅ 2026-07-29 晚续10 通知系统三修复（AZ74）
- 修复1: 6项通知修复(a74, 16110044) - 真实信号浏览器通知不弹根治(export_notifications加调度+删邮件排除+独立轮询+SW破缓存+看返回值+bump)
- 修复2: a74回归修复(fd8fe3a3) - deploy.sh L52-59加notifications.json/.gz恢复(根治untracked rebase冲突,futures+etf+backfill_evening连续2天deploy失败)
- 修复3: A1 check_nt_signals跨日去重(6dd3faea) - 加nt_signal_notified.json(根治每晚重复发7-20旧etf邮件)
- 验收: 8处_markNotified if包裹 + sw a74线上 + deploy.sh L52-59恢复 + check_nt_signals去重逻辑 + 3 commit在origin/main

**待办**:
- B2: intraday_snapshot.sh export_notifications移到push前(notifications滞后10min优化,非紧急)
- 明天验证: 浏览器通知a74 + deploy.sh修复 + A1去重(首次发一次7-20后跳过)
- rzhb schedule T+1 08:00确认(今晚没跑,是改时点还是漏跑)
- 未来增强: export_notifications加读etf_signal(浏览器通知也弹etf,当前notifications.json signals无etf)
- ✅ 完成 commit 90b8e1ce + 057fa74f（export_notifications 读 etf + app.js etf_buy/sell/volume + OPEN_ETF_DETAIL + sw.js a75 主站上线）

**主控验收**: grep确认NOTES AZ74+TASKS续28+3 commit链+push全成功

## 明天 7-30 验证清单
- [ ] 浏览器通知 a75：开盘后 intraday_snapshot 09:35 生成 notifications.json（B2 修复 export_notifications 在 push 前）+ 即时 push，前端 30s 轮询拉取 + showNotification
- [ ] deploy.sh a74 回归修复：02:00 backfill_evening + 20:05 futures/20:07 etf 首触 deploy 不再冲突
- [ ] A1 check_nt_signals 跨日去重：nt_signal_notified.json 明天首次发一次 7-20（设计，后天起跳过）
- [ ] B2 intraday notifications 即时 push：notifications 滞后 10min 根治
- [ ] 未来增强 etf 通知：7-30 有 etf 信号时浏览器弹 🐾 ETF进场/离场/放量，点通知弹汪汪队信号明细 modal
- [ ] rzhb 08:00 主采 + 19:15 兜底：7-30 两次执行（08:00 主采 SSE T+1 + 19:15 兜底防漏），查 rzhb_backfill_launchd.log
- [x] 告警轰炸根治（AZ77，commit `51d404f3`）：schedule_monitor exit!=0 路径加 alert_state suppress + 预填 etf active 止血。07:00 实证 `[suppress] etf_national_team 退出失败(exit=1) 持续中, 不重发` + 0 告警 + last_alerted 不更新 ✅ 已验证
- [ ] 今晚 21:30 etf 兜底成功 exit=0 后：schedule_monitor 检测恢复 -> alert_state etf 转 recovered + 发 1 封 recovery 邮件（不再轰炸 50 次）
- [x] us_stock 延迟根因修复（AZ78，commit `28d5c9eb`）：us_stock_morning.sh 加 gen_schedule_stats trap + 结束行退出码（根治 schedule_stats us_stock exit=null）。验收 6 点 grep 全过 ✅
- [x] schedule_stats 时序矛盾根治（AZ79，commit `346f53a4`）：push_schedule_stats.sh 独立 push 绕过 deploy.sh 时序 + 7任务+intraday选项2。验收6点+线上rzhb=07-30 08:00实时显示 ✅
- [ ] 7-31 05:00 us_stock 跑后 push_schedule_stats.sh 独立 push 线上立即显示 exit=0（时序根治后不再等17:50 update_all deploy）
- [x] 取消主控每小时监控 cron 483ce68c（schedule_monitor 15min 覆盖3/4项，省 token）+ schedule_monitor 加 launchctl 加载检查补缺口（AZ80，commit `d2207fe7`，5项全覆盖：漏跑/exit/log_anomaly/ETF耗时/线上时效+launchctl加载）
- [x] 前端盘中切换 bug 修复（AZ82，commit `80cdcc2e`）：SW fetch 加 no-store 5处 + overview 改 NetworkFirst + bump a77 + 9:15 关键时点 + banner/badge 4态。验收7点全过+线上 a77+160e60d5 ✅
- [ ] AZ82 激活验证：用户刷新页面激活新 SW a77 后，盘中自动轮询拉 7-30 新数据不再卡 7-29（SW skipWaiting 自动接管但旧页面需刷新换新）
- [x] P2 后端提前到 9:15 决策（用户选 A+C，commit `ce55b2c1` AZ83）：A 维持后端 is_closed 现状（9:25 切竞价完成不动）+ C 前端盘前 9:15-9:25 集合竞价提示横幅（_isAuctionCall 前端时间判断，零后端风险）。B 9:20 降级不推荐（腾讯源 9:25 才返开盘价铁证 cc991142）。验收5点全过+线上 a78（sss.sugas.site）✅
- [x] 北向资金提示文案修正（AZ84，commit `4887b0ec`）：7处P0文案+3处P1注释改"已切HKEX成交总额源每日更新，原净买额2024-08停更"，原"冻结2024-08-16"事实错误（DB实际连续到7-29）。验收4点全过+线上a79 ✅

## 🆕 2026-07-31 全球指数时效优化（纯调研落档，待排期，详见 NOTES §48 AZ89）

**优先级**：P1（推荐实施）+ P2（可选增强）

**调研结论摘要**：首页"全球"Tab 9 指数（美股4 + 亚洲2 + 欧洲3）当前全部走新浪日K历史接口（`index_global_hist_sina` / `index_us_stock_sina`），仅 backfill-evening 16:35/21:00/02:00 采集，盘中无实时更新。韩 KOSPI/日经与 A 股同时区（09:00-15:30 KST/JST vs 09:30-15:30 CST），盘中看不到实时涨跌，价值打折。akshare `index_global_spot_em`（东方财富实时）免费覆盖全部5个目标指数，项目已用 akshare，实施成本极低。

**待办动作清单**：

- [ ] **P1（推荐）：加盘中 intraday_snapshot 采全球5指数实时（nikkei225/kospi/ftse100/dax/cac40）**
  - 源：akshare `index_global_spot_em`（单次返全部，无需逐个代码，免费无需 key）
  - 时点：复用现有 9:25-15:02 每10min（亚洲时段覆盖韩日开盘）+ 15:35/20:35（覆盖欧洲开盘，欧洲 15:00-23:00 北京时间）
  - 反哺 `index_daily` 当日 close，盘中 signals.compute() 扩展 buy_special/sell 触发池
  - 收盘 pipeline 仍用 `index_global_hist_sina` 补完整 OHLC（实时源只覆盖当日 latest，无历史序列）
  - 注意：欧洲指数（ftse100/dax/cac40）A 股盘中（09:30-15:00）未开盘，采到昨收；15:35/20:35 才采到欧洲实时

- [ ] **P2（可选）：港股板块8个加盘中实时**
  - 当前仅收盘后 16:35 采，盘中无实时
  - 港股板块腾讯已支持 r_hkCESG10 等（`_HK_CODE_MAP`），加盘中时点即可
  - 优先级低（细分行业用户关注度低于宽基）

- [ ] **P2（不建议）：美股4个加盘中实时**
  - 美股 21:30 开盘（北京），A 股盘中美股未开盘，无实时可采
  - 已有美股期货 ES/NQ 实时预估当晚方向（`us_futures.py`），够用

- [x] **✅ 外盘期货扩充源实施已完成（2026-08-01，commit `fe7525f0`，sw ui44，详见 NOTES §48 AZ94）**
  - 现状：美股预期板块已配置化扩充到 13 只 = 4 hf_(ES/NQ/YM/HSI) + 9 b_ 新增(DAX/CAC/UKX/SX5E/SENSEX/KOSPI/AS51/NKY/RTY)，单一配置源 `US_FUTURES_META` 驱动
  - 新解析器 `_parse_sina_b`（b_ 字段格式与 hf_ 不同，复用 `index_backfill._sina_global_realtime_fallback` 模式）；Yahoo 备用源（META 每条加 `yahoo_symbol`，主源空则 Yahoo 逐个补采，sleep 0.6s 防限流）
  - 弃用：腾讯/东财(封IP)/akshare futures_foreign_hist/雪球(需token)/英为财情(403)/CME(404)；A50 放弃（无源支持）
  - 前端 `_renderUSFuturesExpect` 动态遍历 `Object.keys(usf)` + CSS flex-wrap 自适应 13 卡片，无需改 app.js/style.css
  - Yahoo Russell 2000 用 `^RUT` 非 `^RTY`（实测 ^RTY 无数据）

- [ ] **P2（可选）：亚洲其他同时区指数（澳股 ASX200/印度 NIFTY50）**
  - `index_global_spot_em` 同样覆盖，可一并加
  - 优先级低，用户未提需求

- [ ] **前置验证**：akshare 版本是否含 `index_global_spot_em` 函数（`python -c "import akshare as ak; print(hasattr(ak, 'index_global_spot_em'))"`）
- [ ] **前端配套**：全球 Tab 卡片角标更新逻辑（当前 us_ 标 t1，其他 t0，加实时后是否需要新标记）

**状态**：✅ 用户确认 P1+P2 一起实施（2026-07-31 用户定）。排期 **2026-07-31 收盘后(15:35 后)或 2026-08-01 周末开发**（盘中不开发避免影响生产，用户明确要求等收盘后/周末）。NOTES §48 AZ89 有完整调研报告（指数清单/数据源/时点/韩日时效分析/实时源优劣对比/优先级建议）。实施时派 agent：①前置验证 akshare index_global_spot_em 可用 ②P1 加 intraday_snapshot 采全球5指数实时 ③P2 港股8个+亚洲其他(澳股ASX200/印度NIFTY50) ④前端配套角标 ⑤收盘 pipeline 保留 index_global_hist_sina 补 OHLC。

---

## 🆕 2026-07-31 公募基金持仓佐证大盘（纯调研落档，待排期，P1，详见 NOTES §48 AZ90）

**优先级**：P1（中等优先级，作为现有"北向/外资/两融"3 维资金面的补充维度）

**调研结论摘要**：公募基金持仓数据（十大重仓/股票仓位/行业配置/净申赎）对 A 股大盘走向有**中等参考性**，作辅助维度有价值，不能作主信号。核心限制是季报披露滞后 15 个工作日（披露时点持仓 ≠ 当前持仓）。最有价值信号：①基金平均股票仓位（"88 魔咒" >88% 见顶 / "80 抄底" <80% 见底，反向指标）②重仓股抱团度（Herfindahl 集中度急升=风险积累，瓦解=见顶信号）③净申赎（净申购=散户乐观反向看空，净赎回=散户悲观反向看多）。数据可得性高：东方财富 fundf10 子页（ccmx/jjcc/hytz/zcpz/jbl/cyem/jjjz/fhsp）全部可爬，akshare 已封装 9 个接口（`fund_portfolio_hold_em` / `fund_value_estimation_em` / `fund_open_fund_daily_em` 等）免费无需 key，项目已用 akshare 实施成本极低。实证案例：易方达蓝筹精选 005827（张坤）2026Q2 股票仓位 76.43% 较 Q1 的 93.81% **减仓 17.38 个百分点**，净资产 204.16 亿较上期缩水 23.80%，是 2026 年最显著的"头部基金减仓+规模缩水"信号。

**待办动作清单**：

- [x] **✅ 采集：季度全量采集脚本已完成**（akshare `fund_portfolio_hold_em` + fundf10 子页爬虫兜底，commit `10454371` 后端核心 + `920f57ed` 闸门 + 本轮 quarterly 全量手动跑完成）
  - 范围：**全量**（全市场偏股混合+灵活配置+股票型约 4000-5000 只，2026-07-31 用户定改全量非前500只。理由：①季度才跑一次 30-50 分钟可接受非瓶颈 ②抱团度/重叠度是计数集中度指标前500只漏小基金重仓股会算偏 ③净资产规模加权小基金不污染平均仓位但完整反映全市场抱团结构）
  - 字段：fund_code/fund_name/report_date + top10_holdings + industry_allocation + asset_allocation(stock_ratio/bond_ratio/cash_ratio/net_asset) + holding_changes
  - 时点：每年 1/22（Q1）、4/22（Q2）、7/22（Q3）、10/22（Q3）、3/31（年报）后次日 03:00 一次性采集
  - ✅ **数据新鲜度闸门已实施**（2026-08-01，commit `920f57ed`，详见 NOTES §48 AZ93 + memory `public-fund-fresh-gate`）：quarterly.sh/full.sh 跑前调 `check-fresh` 查源(cninfo B2)最新 report_date vs DB MAX(report_date) + 覆盖率(holding<4500 OR asset<top_n*0.95 触发补采)，无新数据跳过避免重复跑，有失败补采。非死板季报日历：披露窗口每天有新基金披露就跑采全后跳过，非披露窗口直接跳过。daily.sh 不加闸门（日更每天变必须跑）。关键：lg 源是周频不能用，只 cninfo B2 是季报频。
  - ✅ **本轮 quarterly 全量手动跑完成**（2026-08-01，PID 25741，耗时 1666.8s≈28分钟）：5 汇总表全完成（fund_basic 27409/fund_position_history 521/fund_holding_stock 2835/fund_hold_structure 45/fund_scale_change 113）；1000 只逐只跑 asset_ok 955(fail 27)/industry_ok 947(fail 35)；8 指标 fund_metrics 全算（avg_position 96.01/concentration_herfindahl 0.0215/overlap_ratio 848.27/industry_concentration 0.5818/net_redeem_ratio -0.1741/position_change_ratio 0.82/top20_adjustment None/top30_concentration 48.20）；position_history 521 期=cninfo 季报 76 期(20070930~20260630)+lg 周频 445 期(20171204~20260724)
  - 耗时：全量 4000-5000 只 × 7 子页 × 延时，实测推算 30-50 分钟（详见 `/tmp/agent-progress-fund-research.md` 反爬调研）
  - 反爬策略：延时 + retry + 断点续采（记录已采 fund_code 到 `/tmp/fund-collect-progress.json` 重跑跳过已采），最坏降级头部 1000 只（按净资产排序覆盖 95%+ 规模）

- [x] **✅ 采集：日更轻量采集已完成**（盘中估算仓位，commit `ea3ff93b` 阶段L 定时任务 3 脚本含 daily，2026-07-31 用户定一步到位非 P1.5 后续）
  - 源：akshare `fund_value_estimation_em()`（一次返回全市场基金估算净值）
  - 字段：fund_code/fund_name/date + estimated_nav/estimated_change_pct + actual_nav(T+1 确认)
  - 时点：每交易日 16:30
  - 用途：估算净值涨跌 vs 实际涨跌反推仓位变化（粗略，误差 ±5%）
  - 与季度硬数据互补不互斥：季度给绝对值（88 魔咒/抱团度/净申赎精准阈值），日更填补 15 天披露滞后窗口的仓位趋势（88-80 阈值仅趋势参考非精确触发，季报披露后校正）

- [x] **✅ 指标：5 核心指标计算已完成**（commit `10454371` 后端核心 8 指标，本轮 quarterly 全量跑算出 fund_metrics 全 8 项）
  - 基金平均股票仓位：加权平均 `Σ(stock_ratio×net_asset)/Σ(net_asset)`，>88%=见顶/<80%=见底
  - 重仓股抱团度（Herfindahl）：`Σ(weight²)` 加总全市场基金前十大集中度，急升=风险积累
  - 重仓股重叠度：头部 100 只基金前十大重仓股去重数/1000，<300=高度抱团/>500=分散
  - 行业配置集中度：Top3 行业占比之和，>60%=高度集中
  - 基金净申赎率：`Σ(份额变化×净值)/Σ(总规模)`，净申购激增=见顶/净赎回激增=见底
  - 外加 3 衍生指标：加仓减仓比 / 头部 Top20 调仓方向 / 重仓股 Top30 集中度
  - 本轮实测值：avg_position 96.01 / concentration_herfindahl 0.0215 / overlap_ratio 848.27 / industry_concentration 0.5818 / net_redeem_ratio -0.1741 / position_change_ratio 0.82 / top20_adjustment None / top30_concentration 48.20

- [x] **✅ 前端：新独立 tab「基金持仓」已完成**（commit `d8ca2855` ui36 新建 tab + `4238f40e` ui41 4项优化 + `4544ffc4` ui42 range切换修复，遵循 memory `new-feature-isolated-tab-first`）
  - 顶部 4 卡片信号灯（平均仓位/抱团度/重叠度/净申赎，颜色 >88% 红 / 80-88% 黄 / <80% 绿）
  - 主图：基金平均仓位 vs 上证指数双轴折线 + 88% 魔咒警戒线 / 80% 抄底线水平虚线
  - 重仓股 Top30 排行（左）+ 行业配置热力图（右）
  - 头部基金调仓 Top20（基金/规模/仓位变化/重仓股变化）
  - 页面醒目滞后性提示：「本数据截止 YYYY-MM-DD，已滞后 N 天」

- [x] **✅ 前端：首页角标接入已完成**（commit `d4e2c7fd` 阶段J+K ui40，轻量接入现有"资金面"卡片组）
  - 显示当前平均仓位（如 `89.2%⚠️`）+ 较上季变化（如 `↑1.2pct`）
  - 颜色 >88% 红（风险）/ 80-88% 黄（中性）/ <80% 绿（机会）
  - 点击跳转「基金持仓」tab 详情

- [x] **✅ 信号灯：规则接入已完成**（commit `d4e2c7fd` 阶段J+K ui40，首页"信号"模块 4 信号灯）
  - 仓位 >88% -> "基金仓位高位 ⚠️ 88 魔咒见顶信号"
  - 仓位 <80% -> "基金仓位低位 ✅ 80 抄底见底信号"
  - 抱团度 >0.20 且重叠度 <320 -> "重仓股高度抱团 ⚠️ 抱团瓦解风险"
  - 净申赎 >500 亿 -> "基金净申购激增 ⚠️ 散户乐观反向看空"
  - 净申赎 <-500 亿 -> "基金净赎回激增 ✅ 散户悲观反向看多"

- [x] **✅ 4 维资金面共振联动已完成**（commit `d4e2c7fd` 阶段J+K ui40，北向/两融/产业资本/基金持仓 4 维共振）
  - 加入现有"资金面"模块（北向日更/两融日更/产业资本月更/基金季更）
  - 4 维共振信号最强：例如"北向流出+两融下降+产业资本减持+基金减仓"=4 维共振看空

**风险提示**：
- ⚠️ **滞后性误导**：季报披露滞后 15 工作日，披露的持仓已是过去时，基金可能已调仓，不能直接当现在持仓用。缓解：页面醒目提示"数据截止日期+已滞后天数"，不作主信号
- ⚠️ **抱团误导**：抱团股未必瓦解（如茅台抱团 5 年才瓦解），仅作辅助信号，需结合估值（PE 历史分位）确认
- ⚠️ **披露规则限制**：季报只披露前十大，全持仓要等中报（60 日内）/年报（90 日内）。用十大重仓+行业配置+资产配置三维度交叉验证
- ⚠️ **样本偏差**：只看头部 500 只基金忽略小基金。用净资产规模加权，大基金权重大
- ⚠️ **88 魔咒失效**：历史规律未必未来应验（2020 仓位持续 90%+ 大盘仍涨）。仅作"风险提示"非"卖出信号"，结合其他维度共振
- ⚠️ **估算仓位误差**：日更估算仓位（净值反推）误差大（±5%）。估算仅作趋势参考，季报披露后校正

**状态**：✅ **全部 7 项待办已完成**（2026-08-01 实施闭环）。后端 commit `10454371`(9表+8fetcher+3pipeline+8指标+5类export) + `920f57ed`(数据新鲜度闸门) + `ea3ff93b`(定时任务3脚本)；前端 commit `d8ca2855`(tab ui36) + `4238f40e`(4项优化 ui41) + `d4e2c7fd`(首页角标+4信号灯+4维共振 ui40) + `4544ffc4`(range切换修复 ui42) + `4a0bf58a`(export LIMIT40修复)；本轮 quarterly 全量手动跑完成(5汇总表+8指标+521期 position_history)。NOTES §48 AZ94 有本轮 4 项工作闭环记录。**方案修正（2026-07-31 用户定）：采集量改全量（非前500只）+ 日更估算改一步到位（非 P1.5 后续）**，理由：①季度才跑一次 30-50 分钟可接受非瓶颈 ②抱团度/重叠度是计数集中度指标前500只漏小基金重仓股会算偏 ③净资产规模加权小基金不污染平均仓位但完整反映全市场抱团结构 ④日更估算与季度硬数据互补不互斥（季度给绝对值88魔咒/抱团度/净申赎，日更填补15天滞后窗口仓位趋势），一步到位完整不留尾巴。完整调研报告 404 行存 `/tmp/public-fund-research.md`。


## ✅ 2026-07-31 a_width_dt_count 跌停池空修复 + 单项指标失败自动重采机制（全闭环，详见 NOTES §48 AZ92）

**背景**：7/31 17:50 update_all 采 `stock_zt_pool_dtgc_em` 跌停池空，collect_log error 致 collect_health level=error 线上小红点。7/31 大盘强势反弹（涨4690/跌728），跌停0合理（7/30 跌停74反弹日），9:25 竞价跌停6只开盘后都打开。

**手动修复**（commit `e35b7e06` push main）：
- DB: `daily_metric a_width_dt_count 20260731` 6.0(intraday 9:25竞价) -> 0.0(akshare); `collect_log` 新增 ok 记录(20:43)
- overview.json 重生成 + push main（不带 feat 分支 4c324eeb，单独在 main 加 e35b7e06）
- 上线验证：sss.sugas.site + s.sugas.site collect_health=ok collected_at=20:43:34 ✓（CF 主站部署延迟不卡，3域名任一OK即上线）

**自动修复机制实施**（feat 分支 commit 待 push main）：
1. ✅ **fetchers.py collect_snapshot 交叉验证**（`app/collector/fetchers.py` L252-273）：zt_pool 系列空时调另一个 zt_pool 函数交叉验证，涨停池有数据 -> 跌停池空=真0（仅 count_rows transform 写0+ok），都空=源失败保留 empty。根治首次采集误报 error
2. ✅ **新增 scripts/retry_failed_metrics.py**：读 collect_log 当日 error 项，调 collect_snapshot/collect_direct 重采，成功 upsert+清旧error+写ok；失败保留error下次再试。非交易日跳过。sys.path 用 `.absolute()` 不用 `.resolve()`（确保读主库非滞后镜像，§9）
3. ✅ **self_heal.sh 集成 retry**（`scripts/self_heal.sh` L18-30）：在任务级 force-heal 之前先跑 retry 轻量重采，复用每15分钟时点（Minute=7/22/37/52），不加新 launchd 时点。不受每日3次上限限制

**本地验证**：模拟未修复（删 collect_log ok 保留 error）-> 跑 retry -> 发现 a_width_dt_count error -> 交叉验证涨停池99只 -> 写0+ok -> collect_log 20:52 ok + daily_metric 0.0。自动修复流程闭环。

**自动修复时点**：17:50 update_all 跑后，18:07 self_heal 调 retry 重采当日 error 项；18:07 仍失败 18:22/18:37.../20:52 每15分钟重试；当日内任一时点源恢复即修复；当日全天源失败保留 error 等明日 update_all 兜底。

**约束遵循**：不改根目录 data/（手动修复直接改 DB 非 git add）+ 盘中不跑全量 export+deploy（20:43 收盘后）+ push main 避开 intraday 时点 + non-ff 优先 rebase + 不 force push main + commit msg Co-Authored-By + DB 主库 trade-data/data/sentiment.db。

**状态**：✅ 手动修复已上线（e35b7e06 push main，3域名验证 ok）。✅ 自动修复机制本地验证通过，feat 分支 commit 待 merge main push main（launchd 下次跑 self_heal 用新版，下次 update_all/intraday_snapshot 用 collect_snapshot 交叉验证新版）。

---

## 📋 2026-08-02 留言箱功能（待实施，完整方案见 NOTES §48 AZ122）

**目标**：收集用户需求/建议/bug/数据纠错，作为后续完善方向输入；建议上墙增加参与感。

**架构**（复用订阅C方案，零新架构）：
- CF Workers Function（worker/headers.js 已有 Worker）+ KV `FEEDBACK_KV`（仿 SUBSCRIBE_KV）+ secret `FEEDBACK_ADMIN_PASSWORD`（仿 SUBSCRIBE_PASSWORD）+ MailChannels API（CF Workers 免费发邮件）
- 关键：线上 ss.fx8.store 已是 Workers Static Assets + Worker Function，POST 可直接 Worker 接收写 KV，无需后端 app/main.py 无需外链第三方

**模块**：
1. worker/headers.js 加 `/api/feedback*` 路由（POST 提交 / GET list 上墙 / GET+POST admin 审核 / DELETE）
2. 前端右下角浮动按钮📬 + 留言弹窗（昵称/联系/分类/内容/URL自动）+ 留言墙（不占1级tab，6个已满）
3. static-site/admin/feedback.html 管理员审核页（密码登录 + pending列表 + approve/reject）
4. 防滥用四层：频控（同IP 10min≤1条）+ honeypot + 内容约束（50-2000字+IP hash）+ 审核闸门（pending不上墙）
5. MailChannels 邮件通知管理员新留言

**工作量**：~550行，~1.5天

**上线**：`wrangler kv namespace create FEEDBACK_KV` + `wrangler secret put FEEDBACK_ADMIN_PASSWORD` + worker 路由 + 前端 + admin 页 + build_min + bump_asset_version + bump sw CACHE_VERSION + deploy + 3域名验证提交审核上墙闭环

**状态**：🔄 用户侧已上线(commit `b53a312e7`, sw `v2-20260804-feedback-box`, 2026-08-04 19:27 push main)：登录后留言+头像下拉菜单"💬 留言箱"入口+我的留言列表(GET/POST `/api/feedback`, session cookie 认证, KV `feedback:<provider>:<uid>:<ts>`, 复用 SUBSCRIBE_KV 未建 FEEDBACK_KV)。**AZ122 完整方案剩余未做**:管理端审核页(admin/feedback.html)+留言墙(上墙公示)+防滥用四层(频控/honeypot/内容约束/审核闸门)+MailChannels 邮件通知+FEEDBACK_ADMIN_PASSWORD secret。待用户定是否补全(运营者看留言+防滥用是公开留言箱必要)

---

## ✅ 2026-08-02 板块分化移到指数表现二级 tab（已上线，commit 99bfea223）

> commit 99bfea223 feat: 板块分化移到指数表现二级tab(A股港股中间)。app.js L8130 `["industry","板块分化"]` 已是 subtab 放 A股/港股间，index.html 删 1级 industry 按钮，旧 `#industry` 直链 redirect 兼容。

**用户判断**：板块分化1级tab本质是指数表现的一种（板块的），移到指数表现下做二级tab放A股港股中间。

**9处改动**：
1. `_MARKET_SUBTABS` L16400 加 `industry` 放 a-stock/hk 间
2. renderMarket L7826 subtabs 数组加 `["industry","板块分化"]`
3. L7854 加 `else if industry 调 renderIndustry(subContent)`
4. renderIndustry L13208 加 container 参数（仿 renderAStock），函数体10+处 content 改 container
5. index.html L102 删 PC industry 按钮
6. L143 删 H5 industry 按钮
7. `_H5_TAB_NAMES` L14504 删 industry
8. renderTab 主路由 L4189 删 industry 分支（或保留兼容旧hash redirect）
9. state.tab 校验 L103 删 industry 分支

**命名**：主控推荐保留"板块分化"（用户已叫熟+"分化"点出核心价值），tab key `industry` 保留

**副作用**：旧 `#industry` 直链失效（redirect 兼容）+ 搜索框切 subtab 消失（可接受）+ 1级tab 6->5

**状态**：⏳ 等用户拍板（移位 + 命名），定后派实施 agent

---

## ✅ 2026-08-02 全站敏感合规词替换 + 🛡️ 按钮切换（已上线，commit 链 99bfea22+0549ae74+339d0f01+aba5d3cd，后续 a3aa25d14 改名精简版/完整版）

> 4阶段实施完成：①i18n.js 骨架+开关 UI+集中点 _t()（99bfea22）②app.js 分散点+lab.js+about.html（0549ae74）③trade_sim modal+simulate_trade.py+7HTML+邮件（339d0f01）④build+deploy+grep 兜底修复2处真漏改+R2 trade_sim 上传+3域名验证（aba5d3cd）。后续收尾：🛡️开关移入皮肤弹窗（c6cbebd3）+ trade_sim 弹窗合规切换修复（359a568b）+ 版本切换改名精简版/完整版+提示文字合规中性化（a3aa25d14）。详见正文实施进度段。

**需求**：全站"买点/卖点/强买入/强卖出/减仓/清仓/抄底/逃顶/止损/止盈"等敏感合规词，默认显示合规版（游客/巡查机器人看合规词），信任用户可点 🛡️ 按钮切回原版（买卖点壮观易懂）。开关放皮肤切换旁。

**方案**：方案B JS文案替换+localStorage（源码默认合规词，爬虫看合规版）
- 复用 app/alert_reason.py:77-82 已验证的禁用词映射表（买入->关注低位机会 等 8词）
- 新建 static-site/i18n.js：`_t(key)` 函数 + 双字典（compliance/original）+ `_t.setMode(mode)`
- app.js 146行 + lab.js 83行字符串改 `_t()` 调用（6处labels对象 L2470/2641/3610/12489/1265/13395 + signalLabel L380 + _SIG_DETAIL L1678 是集中的）
- about.html 60处手改合规词（静态默认合规，off不切回；保留"不荐股"声明白名单 index.html L130/L150 + about.html L7/L62/L73/L102/L569）
- trade_sim.html×7（~3800处）：改 scripts/simulate_trade.py:31 生成合规词，重生7个HTML
- 后端 reason 字段保留原词（signals.py L225/232，爬虫不直接看JSON），前端解析正则不变，显示时套 `_t()`
- 后端 JSON 字段名 buy_list/sell_list/sell_signal/hands 保留（前后端契约，改名牵连太大）
- 开关 UI：复用 applyTheme 模式（app.js L16024），index.html L87/L94 皮肤按钮旁加🛡️，L40-52 旁加防闪烁读 compliance_mode，默认 on
- 邮件/通知文案复用 alert_reason.py `_filter_forbidden`（export_notifications.py / daily_summary_email.py）

**合规词映射**（复用 alert_reason.py L77-82）：
- 买点->关注点 | 买入->关注低位机会 | 强买入->重点留意 | 买入机会->关注机会
- 卖点->风险提示点 | 卖出->留意高位预警 | 强卖出->重点规避 | 卖出信号->风险提示信号
- 减仓->逢高谨慎 | 清仓->防范风险 | 加仓->逢低关注 | 抄底->关注超跌反弹 | 止损->风险控制 | 止盈->收益兑现
- 推荐->优选 | 88魔咒->保留（专有名词+已配免责） | 图表pin: {buy:"关注", sell:"风险", sell_stop_loss:"风控"}
- 声明白名单："不荐股"声明不可替换

**工作量**：约 7-8 天（含测试）
**风险**：①漏改致合规版漏词=合规失败，改完必 grep 兜底扫0 ②trade_sim 7个HTML漏重生 ③reason字段正则不可断（后端保留原词）④SW缓存必bump ⑤图表pin canvas重注入
**硬约束**：改 app.js/lab.js 后必跑 build_min.py + bump_asset_version.py + bump sw.js CACHE_VERSION
**待用户拍板5点**（2026-08-02 已拍板）：①about.html 始终合规off不切回 ②trade_sim.html×7 off切回（用户明确要，方案先调研弹窗机制）③88魔咒保留 ④图表pin文字版"关注/风险/风控" ⑤"推荐"只改标题级"三档优选"+描述级"关注点"
**调研报告**：/tmp/agent-progress-compliance-research.md（6维度完整，主控§0验收alert_reason.py L77-82禁用词映射表真实存在）

**状态**：✅ **2026-08-02 全部4阶段实施完成上线**（commit 链 99bfea22+0549ae74+339d0f01+aba5d3cd，详见 NOTES AZ124）
- 第1阶段：i18n.js 骨架 + 开关 UI + 集中点 _t()（commit 99bfea22）
- 第2阶段：app.js 分散点 + lab.js + about.html + common/purpose-notes（commit 0549ae74）
- 第3阶段：trade_sim modal + simulate_trade.py + 7HTML + 邮件（commit 339d0f01）
- 第4阶段：build + deploy + grep 兜底修复2处真漏改（app.js L7130/7131 卖点密集/买点密集->风险点密集/关注点密集；L15005 entry.op 显示加 _t.tsText() 合规转换）+ R2 trade_sim 上传 + 3域名curl验证全通过（commit aba5d3cd）
- sw.js CACHE_VERSION: ui97 -> ui98；仅前端commit+push（不跑export.py避免干扰stage0+intraday_snapshot.json带入）；3域名(ss.fx8.store/sss.sugas.site/ssd.fx8.store)验证合规词全通过

**后续收尾**（AZ125，2026-08-02）：
- ✅ 合规🛡️开关移入皮肤弹窗：皮肤弹窗(🎨)内"显示模式"区块两选项（合规版/详细版），删独立🛡️按钮，保留防闪烁+applyCompliance（commit c6cbebd3，ui99）
- ✅ trade_sim 弹窗合规切换修复：applyCompliance rAF 回调加 modal 重渲染（_tradeSimOverlay.classList 含 show 时调 _tradeSimModalRender 复用缓存），修 modal 是独立 overlay 不在 tab 内 renderTab 不触及的 bug（commit 359a568b，ui100）
- ⏳ 遗留：i18n.js position_stop_loss_clear compliance="风控清仓"含"清仓"敏感词，建议改"风控退出"彻底无敏感词，待用户定夺

## ✅ 2026-08-03 站点 OAuth 登录（已上线，commit 链 4d6f7dcd+604928d6+46b742fd5+97b2a0157+9f2ddcc8d）

> 5 commit 闭环：①后端 FastAPI 框架 app/auth.py（4d6f7dcd，生产不走 FastAPI 留作开发参考）②Workers 实现 worker/auth.js 6路由+Web Crypto HMAC session+KV（604928d6）③GitHub 完整接入 login+callback 7路由（46b742fd5）④前端登录按钮 Gitee+GitHub+登录态+详细版 gating+Google 占位隐藏（97b2a0157）⑤OAuth state 改无状态 HMAC 签名校验根治 KV 最终一致性问题（9f2ddcc8d）。worker/auth.js 756 行，app.js L17287+ 登录按钮+gating 完整。

**需求**：站点加 OAuth 登录，支持 Gitee+GitHub 一键登录；模拟回测/订阅/对比/详细版切换作为登录用户特权，登录后才显示。**Google 登录暂时取消，留作远期待办，前端占位按钮隐藏**（2026-08-04 用户定）。

**方案：A CF Workers 自自建 OAuth（用户定 2026-08-04）**
- 生产 ss.fx8.store/api/* 全走 CF Workers 不回源 FastAPI，故 OAuth 必须 Workers 实现（非 FastAPI）
- 复用现有 KV namespace + /api/* 路由分发，零新增基础设施
- worker/auth.js 新建：Web Crypto HMAC 签名 cookie + KV 存 users/oauth_state + Gitee+GitHub 完整接入 + Google 占位 501（远期复用，前端按钮隐藏）

**4 特权功能入口已定位（app.js）**：
| 功能 | 入口 | gating 点 |
|---|---|---|
| 模拟回测 | L2626 sim-btn + L15287 _tradeSimOverlay | 按钮渲染+弹窗打开 |
| 订阅 | L2244 _appendSubscribeBtn + L2276 _openSubscribeModal | _openSubscribeModal 调用时 |
| 对比 | L15850 全局对比表（在 trade_sim 弹窗内） | 跟随 trade_sim |
| 详细版 | L16778 compliance-option + L16851 applyCompliance | applyCompliance('off') 前 |

**方案对比**：
- ✅ A CF Workers 自建 OAuth：复用 KV+/api/*，零成本，特权细粒度可控
- ❌ B CF Access：免费50用户上限 + 登录页跳 cloudflareaccess.com UX割裂 + 全站 gating 不匹配
- ❌ C 第三方 Auth（Auth0/Clerc/Supabase）：过度设计，SDK 依赖+bundle 加大+用户数据外流
- ❌ D FastAPI 自建：需后端上线（CF Workers 跑不了 Python），架构倒退

**CF 免费版限制**（已查官方文档）：Workers 10ms CPU/请求（OAuth callback 网络IO不计CPU）、100k 请求/天；KV 1000 writes/天（500用户登录/天够用，超量$5/月升级）

**工作量**：MVP（Gitee+GitHub 登录 + 详细版 gating）1-2 天；完整版（+订阅/对比/模拟回测 gating）3-5 天

**实施进度（2026-08-04）**：
- ✅ 后端 FastAPI 框架（app/auth.py，commit 4d6f7dcd，本地可跑，生产不走 FastAPI 留作开发参考）
- ✅ Workers 实现（worker/auth.js，commit 604928d6，Gitee完整+me+logout+GitHub/Google占位）
- 🔄 GitHub 完整接入（agent a40a10ac 跑中，补 login+callback 完整流程）
- ⏳ wrangler secrets 配置（待：GITEE_CLIENT_ID/SECRET/REDIRECT_URI + GITHUB_CLIENT_ID/SECRET/REDIRECT_URI + SESSION_SECRET，凭证已收）
- ⏳ 前端（登录按钮 Gitee+GitHub / 登录态 / 详细版 gating / Google 占位按钮隐藏）
- ⏳ 上线 + 端到端测试

**待定**：①未登录用户看特权入口（隐藏 vs 显示锁图标点击提示登录）②付费用户角色预留

**Google 登录远期待办**：worker/auth.js 的 /api/auth/login/google 占位 501 路由保留（远期复用），前端登录按钮先只放 Gitee+GitHub，Google 占位按钮隐藏。Google OAuth 需创建 GCP 项目 + OAuth consent screen，流程繁琐，Gitee+GitHub 跑通后再排。

## ✅ 2026-08-04 多站点 OAuth 登录（已上线，commit 272115382，方案E+G 备站跳主站+Bearer token+CORS）

> commit 272115382 feat: 多站点OAuth方案E+G(备站跳主站登录+token回备站localStorage+Bearer认证+CORS)。worker/auth.js signBearer/isAllowedRedirect（L210/L266）+ login_token 一次性交换 session_token + Allow-Origin 动态白名单；app.js _isMainSite（L17186）+ 主站 cookie 模式/备站 Bearer token 模式（L17221-17235）+ #auth_token= hash 处理。详见正文方案E+G 实施清单。

**需求**：项目 1 主站 + 多备站（ss.fx8.store 主 CF Workers / sss.sugas.site GitHub Pages 备 / s.sugas.site MaoziYun 备），OAuth redirect_uri 只配主站，用户在备站点登录异常（备站纯静态无 Worker，/api/auth/* 全 404）。

**根因**：前端 app.js 全用相对路径 fetch /api/auth/* 无域名区分；备站纯静态无 Worker /api/auth/* 全 404；OAuth redirect_uri 只配主站；跨域 3 重障碍（CORS Allow-Origin:* 和 credentials 不兼容 + Cookie SameSite=Lax 跨站 fetch 不带 + 第三方 cookie 限制）。

**推荐分阶段实施 E -> G**（6 方案完整评估见 NOTES §48 小节AB，报告 /tmp/agent-multisite-oauth-research.md）：

### 短期方案E（止血，立即可做，~15 行前端，不改后端不改 OAuth）
- [ ] app.js 新增 `isMainSite()` 函数：`location.hostname === 'ss.fx8.store'`
- [ ] `openLoginModal` / `openLoginPromptForFeature` / `openLoginPromptForDetailed` 三入口：非主站弹提示"请在主站登录后使用此功能"+ 按钮 `location.href = 'https://ss.fx8.store/'`
- [ ] `fetchAuthState`：非主站跳过 fetch（避免 404 噪音），直接 applyAuthState 渲染未登录态
- [ ] bump sw.js CACHE_VERSION + build_min.py + bump_asset_version.py
- [ ] deploy + 3 域名验证

### 长期方案G（完整登录态，不依赖第三方 cookie，不依赖 iframe）
- [ ] worker/auth.js `loginGitee`/`loginGithub`：读 `?redirect=` 参数，白名单校验（sss.sugas.site/s.sugas.site），存 KV `oauth_redirect:<state>` -> redirect URL
- [ ] worker/auth.js `callbackGitee`/`callbackGithub`：读 KV redirect，签发 session cookie + 生成一次性 login_token（存 KV `login_token:<token>` -> {user_id, exp}，TTL 60s），`redirect307(redirect + '?token=login_token')`
- [ ] worker/auth.js 新增 `POST /api/auth/exchange`：body {login_token} -> 换长期 session_token（存 KV `session_token:<token>` -> {user_id, exp}，TTL 30天）-> 返回 {session_token, user, privileges}
- [ ] worker/auth.js `me`：支持 `Authorization: Bearer session_token`（token 模式）+ cookie（主站模式）双路径
- [ ] worker/auth.js `logout`：支持 token 模式（delete KV session_token）
- [ ] worker/auth.js CORS：Allow-Origin 动态匹配请求 Origin（白名单内才允许）+ Allow-Credentials: true
- [ ] 前端 app.js：检测域名，主站 cookie 模式（现状不变），备站 token 模式（localStorage 存 session_token + fetch 带 Authorization + URL ?token= 处理 exchange）
- [ ] 安全：redirect 白名单（只允许 sss/s.sugas）、login_token 一次性（exchange 后 delete）、state 防 CSRF 保留
- [ ] 测试：主站 cookie 流程不回归 + 备站 token 流程完整 + token 过期/撤销
- [ ] bump sw + build_min + deploy + 3 域名验证

**不推荐方案**：
- ❌ 方案F（跨域 fetch + CORS + 第三方 cookie）：第三方 cookie 限制是趋势性硬约束（Chrome 2024+ 逐步禁、Safari ITP/Firefox ETP），SameSite=None 长期失效，投入后未来要重做
- ❌ 方案C（OAuth redirect_uri 配多域名）：GitHub OAuth 主机名完全匹配是平台硬约束（ss.fx8.store callback 无法 redirect 到 sss.sugas.site 主机名不同），Gitee 按惯例单个，不可行
- ⚠️ 方案A/B 单独不完整：需配合 token 回传（即方案G）才解决备站登录态

**待用户确认 4 决策点**：
1. 备站定位：灾备/镜像（主站可用时备站只读可接受 -> 只做 E）还是平等入口（备站也需完整登录态 -> E 短期 + G 长期）
2. 是否接受备站登录跳主站再回跳（方案G 用户体验：点登录 -> 跳主站 OAuth -> 自动回备站）？还是要求备站全程不离开备站（只能方案F 第三方 cookie 长期不可持续）
3. token 存储位置：localStorage（方案G 默认）vs sessionStorage（关闭标签即失效更安全但体验差）
4. 备站 s.sugas.site 当前已超 300MB 限制自 2026-07-22 停止拉取，方案G 是否仍需覆盖该站？还是只覆盖 sss.sugas.site

## 📋 2026-08-04 模拟回测费率可配置（待实施，用户3决策已定，完整方案见 NOTES §48 小节AC）

**需求**：模拟回测弹窗费率写死不可配，且调研发现回测引擎漏算印花税（应0.05%卖出收，当前0）+ 过户费旧规则（应沪深统一0.001%买卖都收，当前仅沪市ETF）两处 bug。用户要求费率可配 + bug 根治。

**用户决策（已定，无需再问）**：
1. 印花税默认万5（0.05% 卖出收，2023.8.28 现行标准）
2. 滑点固定百分比（简单透明可观测，不用波动率模型）
3. 全量重生 R2 trade_sim JSON 修正印花税+过户费 bug（bug 非 feature 需根治，不是可选项）

**实施清单**：

### 后端 API（4-6h）
- [ ] simulate_trade.py 抽核心为可调用函数（传 fee_config 参数，去掉模块级常量依赖）
- [ ] 加印花税：卖出收 0.05%（万5，默认值，可配）
- [ ] 过户费3模式：沪市/深市/沪深统一（默认沪深统一 0.001% 买卖都收，2024 现行标准）
- [ ] 滑点固定百分比（默认千1，可配，不用波动率模型）
- [ ] 费率对比函数：默认配置 vs 自定义配置 双回测结果对比
- [ ] FastAPI 路由 `/api/trade_sim_recalc`（POST，body 含 index_id + fee_config，缓存5分钟+限流10次/分）

### 前端配置面板（5-7h）
- [ ] 弹窗内嵌"⚙ 费率配置"面板：6 input（买佣金/卖佣金/印花税/过户费/滑点/最低佣金）+ 2 select（过户费模式/滑点模式）+ 说明文案
- [ ] fee_config localStorage 持久化（用户配置跨会话保留）
- [ ] "重新回测"按钮调 `/api/trade_sim_recalc` API
- [ ] 底部"费率影响对比"区块：对比表（默认vs当前 收益/年化/回撤/胜率/费率成本/费率占比）+ 成本明细 + 双净值曲线叠加图
- [ ] bump sw.js + build_min + bump_asset_version + deploy + 3 域名验证

### 全量重生 R2 trade_sim JSON（bug 根治，必做）
- [ ] 修正 simulate_trade.py 印花税万5 + 过户费沪深统一 bug
- [ ] 全量重生 103 个 trade_sim_{idx}_stats.json + _full.json（印花税万5+过户费沪深统一）
- [ ] upload_r2 上传 trade_sim/ + trade_sim_data/ 前缀
- [ ] 验证线上 R2 JSON 含印花税字段

### 测试联调（2-3h）
- [ ] 默认配置 vs 自定义费率对比正确性
- [ ] 双净值曲线叠加渲染
- [ ] 3 域名验证（ss.fx8.store / sss.sugas.site / ssd.fx8.store R2）

**数据结构**：9字段 fee_config JSON（buy_commission / sell_commission / stamp_tax / transfer_fee / transfer_fee_mode / slippage / slippage_mode / slippage_sigma / min_commission）

**工时**：总 11-16h（2-3天）：后端 4-6h + 前端 5-7h + 测试联调 2-3h

**关键文件**：
- 回测引擎 `scripts/simulate_trade.py`（L44-47 费率常量 / L374 `_buy_with_fees` / L409 `_sell_with_fees` / L1812-1815 JSON 费率字段）
- 前端弹窗 `static-site/app.js`（L15465 `_tradeSimOpenModal` / L16184 `_tradeSimModalRender` / L16202-16205 费率只读展示）
- R2 数据 trade_sim_{idx}_stats.json + _full.json（ssd.fx8.store/trade_sim_data/）

**完整调研报告**：`/tmp/agent-fee-config-research.md`（费率含义表+bug详情+终极方案+工时）

## 📋 2026-08-04 场外基金方案C全量化（⏰已推周末 8/9-10 休盘启动，原盘后23:03 cron c1d4d899 已删，避免和资金面修复/P0-1撞23:00窗口+7.8h大工程休盘跑更稳，完整蓝图见 NOTES §48 小节AD）

**需求**：场外基金只显示 100 只（fund_score_top.json Top100），DB 采了 27418 只但评分引擎只跑 2000 只且前端只读 Top100。用户选方案 C 终极：评分引擎扩全量 27418 + 服务端分页 API + 前端改 fetch。

**推荐 C1（CF Workers + D1）**，工时 7.8h 一晚够。评分引擎无需改代码（compute_all_scores(top_n=None) 已支持全量）。

**8 步实施清单**：
- [ ] 步骤0：修 upload_r2 调用 bug 3+1 处（pf_score_daily.sh:42 / pf_score_weekly.sh:42 / update_all.sh:140(offshore)+152(fund-score) 脚本路径和子命令分开）— **盘中已派 agent aedb9f06 立即做**
- [ ] 步骤1：export_fund_score.py L62 _query_top_funds 补 fund_basic 扩展字段（fund_company/fund_manager/setup_date/scale/management_fee/custody_fee/purchase_fee/strategy/benchmark，点击弹窗用）
- [ ] 步骤2：手动触发 weekly 全量评分（收盘后）compute_all_scores(top_n=None, resume=True) 从 trade-data 跑，验证 fund_score 表 count ≈ 27418，预计 15-30 分钟
- [ ] 步骤3：D1 创建（wrangler d1 create trade-fund-score）+ wrangler.jsonc 加 d1_databases binding(FUND_SCORE_DB) + 新建 scripts/sync_fund_score_to_d1.sh + pf_score daily/weekly 末尾加同步调用
- [ ] 步骤4：新建 worker/fund_score.js 分页/筛选/排序/搜索 + 鉴权(复用 auth.js session) + worker/headers.js 加分发 /api/fund_score
- [ ] 步骤5：前端 app.js L15014 renderOffshoreFund 改分页 fetch /api/fund_score?page=&size=&type=&sort=&dir=&search=，_fundScoreState 加 total，pager 用 total 算页数(549页)
- [ ] 步骤6：点击弹窗 openFundScoreDetailModal 5 区块（参考 openEtfScoreDetailModal L14180）：决策头/凯利仓位推导/6维度雷达SVG/5风险指标+经理6维/基础信息
- [ ] 步骤7：build_min + bump_asset_version + bump sw.js CACHE_VERSION（铁律1）+ deploy
- [ ] 步骤8：调度确认（手动 launchctl start com.trade.pf-score-weekly 测一次）+ 线上验证 curl /api/fund_score

**关键约束**：
- 评分引擎无需改代码（compute_all_scores top_n=None 已支持）
- weekly plist 8/2 才创建下次 8/9 周日 03:17 首次跑，步骤2 手动触发验证全量能跑通
- D1 表 fund_score_full 只同步评分+基础关键字段（不同步 2GB 全库），27418只×1KB=27MB 免费额度够
- 前端 fallback 保留 fund_score_top.json（API 未就绪白屏兜底）
- 盘后 15:35+ 启动（盘中不跑全量评分避免撞 intraday-snapshot 定时任务）

## 📋 2026-08-04 全站性能优化（调研落档，见 NOTES §48 小节AE）

> 用户反馈站点功能多了后流畅度变差，派前端+后端两 agent 并行调研，综合 19 个瓶颈（前端 11 + 后端 8，去重后约 16 个）。CF Workers 主站已上线（br + immutable + CSP/HSTS 全生效），本次聚焦 CF 上线后剩余瓶颈（echarts 实例数、大 JSON 体积、R2 缓存、请求数）。两份报告原文：`/tmp/perf-research-frontend.md` + `/tmp/perf-research-backend.md`。

**核心结论（后端非瓶颈确认）**：生产无 FastAPI（Worker 只分发 auth/subscribe，83 处 fetchJSON 全读静态 JSON）+ DB 索引完善（全走索引）。真正瓶颈 = 静态 JSON 体积 + R2 缓存 + 请求数 + echarts 实例数。

### P0（首屏体感最大，5-8h 提速 60-80%）
- [x] P0-1: renderTab 移除顶层 `await loadEcharts()`，子 render 按需加载（1-2h，首屏 -300~1500ms）。**已上线 commit 89d29b607**（L4467 fire-and-forget + 5处子render await L4484/8142/8768/10434/15582，16处echarts.init调用路径全部确认有保障）
- [ ] P0-2: etf_score_list.json 18MB 按 buy/sell/hold 拆分 + 懒加载（2-4h，基金 tab -1~2s，975KB -> <100KB）。证据 `app.js:14649`，export.py 拆 3 JSON，hold 点"持有观察"才加载。**代码已实现(待commit): export_etf_score_list.py 拆3JSON + app.js/lab.js 懒加载 + upload-etf-score 命令, 等23:00+跑export**
- [x] P0-3: 11 个 sparkline echarts 改 SVG 复用 ntIndexSparkline L8894（2-3h，首屏 -200~500ms）。**已上线 commit 7506aa0c7**（L8172 调用 ntIndexSparkline，省11个echarts.init，仅留行业热力图L13779用echarts。NOTES §48 小节AG 落档）
- [ ] P0-4: R2 大文件 Worker 代理 + Cache API 边缘缓存（2-4h，大文件 1-2s -> <50ms）。新建 `worker/r2-proxy.js`，路由 `/r2/*` -> R2 get + Cache API，前端改 `ssd.fx8.store/data/` -> `ss.fx8.store/r2/data/`。**等23:00+ wrangler deploy**

### P1（首屏次要 + 后台优化，2-3h 请求数减 95%）
- [ ] P1-5: _checkNotifications 后台 visibilitychange 暂停（1h）。证据 `app.js:6496` 30s 独立 setInterval，后台标签页持续 fetch
- [ ] P1-6: 首屏 fetch Promise.all 并行（1-2h，首屏 -300~500ms）。证据 `app.js:6998-7034` overview->signal_stats->intraday 3 个 await 串行
- [ ] P1-7: index.html 加 preconnect ssd.fx8.store/腾讯分时（<0.5h，首次请求 -100~300ms）
- [ ] P1-8: 首页 22 JSON 合并 boot.json（2-3h，请求数 22 -> 1）。export 合并首屏 21 个小 JSON ~250KB br
- [ ] P1-9: CF Workers SIN 节点维持现状（零工作量，国内 CDN 需备案付费 ROI 低，靠减请求降影响）

### P2（按需，滚动优化）
- [ ] P2-10: app.js 17845 行无 code-splitting（短期 requestIdleCallback 延迟非首屏 init 2-3h / 长期按 tab 拆 chunk 8-16h）
- [ ] P2-11: 大盘 tab renderAStock 30+ echarts 改 SVG 或 IntersectionObserver 懒渲染（3-6h，切 tab -500~1000ms）
- [ ] P2-12: 9 个 sticky + 3 个 IntersectionObserver 加 rootMargin + 卡片加 contain（1-2h，滚动更流畅）
- [ ] P2-13: CSS transition all 改指定属性 + will-change + contain（2-4h）
- [ ] P2-14: 分时图 11 个 echarts 改 SVG（2-3h，展开分时图 -300~600ms）
- [ ] P2-15: offshore_fund_* 85MB 本地 dead weight 清理（1h，确认场外基金路线图后停跑 export_offshore_fund.py + 删本地，或移 R2 upload-offshore-fund）
- [ ] P2-16: update_all core pipeline 20 分钟东财封 IP，启动 industry 换源（2-4h，memory `industry-source-switch-trigger` 解除暂缓，东财 -> 同花顺/新浪）

### 实施顺序建议
1. 第一批 P0（瓶颈 1/2/3/4，5-8h，首屏提速 60-80%）
2. 第二批 P1（瓶颈 5/6/7/8，2-3h，请求数减 95%）
3. 第三批 P2（按需滚动）

### 验收数据基线（实施前可复测对比）
| 指标 | 当前值 | 目标值 |
|------|--------|--------|
| 首屏请求数 | 22 | 1-3 |
| 首屏传输量 | 1.26MB | <300KB |
| etf_score_list 传输 | 975KB（br） | <100KB |
| R2 大文件 cf-cache-status | DYNAMIC（每次回源） | HIT（边缘缓存） |
| R2 大文件二次请求耗时 | 1.2-1.6s | <50ms |
| 首屏 echarts.init 实例数 | 12 | 1（仅行业热力图） |
| 首屏 DOM 出现时间 | 300-1500ms（白屏） | <100ms |
| update_all 耗时 | 20min（core pipeline） | 15min（换源后） |

**关键约束**：
- §14 生产稳定性 P0：实施 P0-2（改 export）/ P0-4（新建 worker）/ P1-8（改 export）需避开盘后定时任务时点（15:35/16:00/17:50/20:35 push main），放 23:00+ 安全窗口
- 改 app.js/style.css 后必跑 `scripts/build_min.py` + `scripts/bump_asset_version.py` + bump sw.js CACHE_VERSION（铁律1）
- P0-1 改 renderTab 是高风险点（17 处 echarts.init 路径需逐一确认），建议派独立 agent 实施 + 单测覆盖

## 📋 2026-08-04 跌停池采集失败根治 + 角标文案修正（明晚8-5 23:00+ 实施，排查见 /tmp/agent-stale-badge-debug.md）

**根因**：a_width_dt_count（跌停数）8-4 采集失败，intraday_snapshot.py L1305-1318 跌停池 stock_zt_pool_dtgc_em 失败分支只 print 不写 collect_log，无交叉验证（update_all 路径 fetchers.py:321-337 有，intraday 路径没复用），监控漏报 level=ok retry 永不触发。角标 getCardTimeBadge L4739 t0 源盘中 dataDate=ptd 兜底显示"⏳ 待盘后更新·08-03"误导（实际采集失败非待更新）。

**修复方案**（用户3决策已定：A根治+改文案+明晚实施）：
1. **采集侧根治** intraday_snapshot.py L1305-1318：
   - 跌停池失败时复用 fetchers.py:321-337 交叉验证（涨停池有数据+跌停池空=真0跌停写0，source="intraday_cross"）
   - 降级源：从 stock_zh_a_spot（已采 L1266）算跌停数（涨跌幅≤-9.8% 近似）
   - 失败写 collect_log error（log_collect），让 retry_failed_metrics + collect_health 可见
2. **角标文案** app.js L4739 t0 源盘中 dataDate=ptd 分支改"⚠ 采集异常·{mmdd}"，区分 T+1 正常等待 vs t0 采集失败（注意 L4733 竞价时段 9:25-9:30 t0 停昨日正常不动）
3. **监控** intraday_snapshot 跌停池失败写 collect_health，让监控可见（现 level=ok 漏报）

**实施时点**：明晚 8-5 23:00+ 安全窗口（盘中改采集脚本有风险，等收盘后改+明早 09:25 intraday 验证）

**关键约束**：
- 改 intraday_snapshot.py 采集脚本，盘中 intraday-snapshot 每10分钟调它，必须 23:00+ 改 + 明早验证
- 改 app.js 角标后 bump sw.js CACHE_VERSION（铁律1）+ build_min + bump_asset_version
- §14 生产稳定性 P0：push main 避开 intraday-snapshot 盘后 20:35/22:00 时点
- 补采 8-4 跌停数（DB 无 8-4 行）：修复后明早 09:25 intraday 自动采 8-5，8-4 历史数据可手动 backfill 或留空

**状态**：✅ 已实施 commit 17966eb7e（feat，待23:00+推main）。实际实施：fetchers.py提取cross_check_zt_pool公共函数（L286定义+L353调用）+ intraday三池log_collect（13处）+ 交叉验证（涨停/跌停用cross_check区分真0vs源失败，炸板只error）+ app.js L8071 _errItem显"🚨 采集失败"（比原方案改L4739更准确，直接读collect_health error状态）。未做降级源stock_zh_a_spot（交叉验证已足够）。明天盘中intraday-snapshot跑新代码验证collect_health显示error状态。详见 NOTES §48 小节AJ

## 📋 2026-08-05 通知根因根治（commit 9e7c0f616，待23:00+推main）

**根因**（用户反馈"13点多收到盘中异动邮件但浏览器没通知"）：
1. 前端anomaly去重粒度太粗：app.js L7057去重key=`anomaly_${today}`（全天1次），上午9:26第一批异动弹过后13:16/13:26新异动全被去重跳过；后端邮件去重key=`type|kind|name`（标的级）新标的去重通过发邮件 = 邮件发了浏览器没通知
2. showNotification异步标记死锁：return true在postMessage后（异步），_markNotified立即执行不管SW是否真弹出 = SW没弹也标记后续全跳过

**实施**（commit 9e7c0f616，4文件+49/-13，已验收✓）：
- P0主修复：app.js L7075去重key改`anomaly_${type}_${kind}_${name}_${today}`对齐后端_alert_key；多条新异动合并1条通知弹但每条单独_markNotified；60s时间窗保留
- P1辅助1 SW回调防死锁（通知即时性优先）：showNotification加failClearKeys参数+postMessage后立即return true保留即时性；sw.js SHOW_NOTIFICATION失败catch回NOTIFY_FAILED+failClearKeys到所有client；app.js收NOTIFY_FAILED清_clearNotified+时间窗下次轮询重试；新增_clearNotified/_clearNotifyTimeWindow（L6810/L6817）
- sw.js CACHE_VERSION bump v2-20260805-notify-fix

**明天验证**：盘中异动验证浏览器弹通知（去重粒度对齐后新标的能弹）。详见 NOTES §48 小节AJ

## 📋 2026-08-05 预估成交额实施（A+C共存，已验收✓ commit be49e0064 + f81a31bda，待23:00+推main）

**方案**（用户确认显示：预估全天成交额跟着成交额卡片后面对照看）：
- A线性外推带时间加权（立即生效）：A股分时成交节奏经验占比（9:30=2%->15:00=100%），预估=当前累计/经验累计占比
- C历史分时占比（积累5-10交易日后校准）：新表intraday_amount_history每10分钟存一行，积累后查历史同时段占比平均值校准
- C数据足够（>=5天）自动切换，否则fallback A

**实施**（commit `be49e0064` + `f81a31bda`，已验收✓）：
- `be49e0064`（后端+前端基础版，5文件+124/-3）：
  - 后端 `intraday_snapshot.py`（+108行）：新表 `intraday_amount_history` 正确 schema（date/time_hhmm/cum_amount/source/run_at），DROP 旧错 schema 表（ts_code/trade_date 旧 agent 遗留）；新增 `_forecast_amount` 方案A经验加权（`_EXP_RATIOS`+`_exp_cum_ratio`）+方案C历史占比校准（>=5天切换）；在 `_collect_intraday_width_metrics` 的 a_amount upsert 后加预估计算，独立 try-except 隔离失败只 `log_collect error`；width 采集后重新 dump `intraday_snapshot.json` 含 `amount_forecast` 字段
  - 前端 `app.js`：metricId 配置添加 `a_amount_forecast`，成交额 KPI 卡片盘中显示预估全天角标（forecast-tag），收盘后（15:00 后）隐藏
  - 主库：DROP 旧错 schema 表 + 建正确 schema 表
- `f81a31bda`（UI优化，4文件+14/-5）：`be49e0064` 前端旧版只显示灰色"预估全天 X亿"后缀不符合"对照看"需求，本次改 `app.js` L8083-8104：
  - 主值 `valueHtml`：预估全天（>=1万亿用"X.XX万亿"，否则"X亿"）+ 橙色"预估"tag（background:#ff9800;color:#fff;font-size:10px;padding:1px 4px）
  - 副值 `sub`：`当前 {k.value}{k.sub}` 对照看当前累计成交额
  - 时间门控 `hm<1500` 才显示；`build_min` app.min.js 重生成（-46.7%）；`bump_asset_version` app.min.js?v=f4aa6347->7ed6f578；`sw.js` CACHE_VERSION v2-20260805-amount-forecast -> v2-20260805-amount-forecast-ui

**语义错位bug修复**：旧 agent（9a904f948）用 `indices` 单指数预估数值差4倍（语义错位，把指数当全市场成交额算），主控验收发现后改用全市场 `a_amount` 重新实施 `be49e0064`。

**约束遵循**：3保证不影响采集（try-except隔离+改intraday_snapshot.py避开:25/:35/:45/:55/:05/:15时点+ast语法检查）✓ / commit feat不推main ✓ / 改app.js后bump sw.js ✓

**明天验证**：盘中验证 intraday_snapshot.json 含 amount_forecast 字段，KPI 卡片显橙色预估 tag + 主值万亿/亿切换。详见 NOTES §48 小节AK

## 📋 2026-08-05 8/5 R2无数据根治（commit faf109e57，待23:00+推main）

**根因**：`intraday_snapshot.py` 盘中每 10 分钟生成 `sentiment-{rng}.json` 到主库但不上传 R2，前端 `app.js` dataUrl 对 `-all.json` 走 R2（ssd.fx8.store/data/），R2 只在 `export.py`（17:50）上传，盘中 R2 停在昨日致前端读旧数据（8/5 无数据事故）。**非 trade 镜像滞后**（曾误判，实际是 R2 上传滞后--盘中根本不上传 R2）。

**实施**（commit `faf109e57`，1文件+36行）：
- `intraday_snapshot.py` L1655-1667：在 sentiment 5 ranges 生成循环后（L1648），`subprocess` 调用 `upload_r2.py upload` 上传 5 个 `sentiment-{rng}.json` 到 R2（`data/sentiment-{rng}.json`）
- 独立 try-except 失败不阻断采集，`log_collect error` `func_name=sentiment_r2_upload` 让监控发现（L1676/1681）
- 复用 `upload_r2.py`（只依赖 stdlib，自己加载 `.env` 获取 R2 凭证）
- 即时修复：已手动上传 `sentiment-all.json` 到 R2（主库 trade-data，有 8/5）

**验收**：curl R2 `a_sentiment` 最后 20260805 73.78 ✓ / upload_r2 调用 L1655-1667 ✓ / log_collect error L1676/1681 ✓

**明天验证**：盘中验证 R2 `sentiment-all.json` 含 8/6 最新日期。详见 NOTES §48 小节AK

## 📋 2026-08-05 信号设计方案B（commit 9df46887f，待23:00+推main）

**背景**：`sentiment_cyb` 在 `SCORE_IDS` 被当 close 算买卖点，但情绪分是 0-100 衍生指标非可交易标的，混入首页买卖点列表易误导且无 ETF 参考（`trade_sim`/`board_etf_map` 无 `s.` 前缀映射）。

**方案B**（commit `9df46887f`，1文件，已验收✓）：
- `app/queries.py` L370：只在 `overview()` 的 `signals_today` 生成 SQL 加 `AND index_id NOT LIKE 's.%%'` 过滤
- `signal_daily` 表保留 `s.*` 记录（情绪分 KPI 卡片/弹窗仍经 `signals()` 函数按 index_id 查 `s.*` 画走势+pin，L761-769 9 个情绪分 KPI 不受影响）
- 不改 app.js（避免和前端 agent 撞 app.js）

**验收**：grep L370 `NOT LIKE 's.%%'` ✓ / `signals_today` 201 条 `s.*` 0 条（过滤生效）✓ / `signal_daily` 保留 1 条 `s.sentiment_cyb sell`（表未过滤）✓ / ast 语法 queries.py/signals.py OK ✓

**明天验证**：signals_today s.* 0 条（已验收，明天数据复现）。详见 NOTES §48 小节AK

## 📋 2026-08-05 KPI小卡新颖设计全套（P0+P1+P2，待实施）

**背景**：用户反馈首页KPI小卡颜色单调。调研agent（aadbc93ed20adc5ec）验收5根因坐实：
1. 数字无状态色（.card-value L977无显式color，所有数字#f0e6c4暖米同色）
2. 卡片无border（.card L833-840只background+box-shadow）
3. 背景统一无层次（全var(--bg-card) #252836）
4. 金色仅hover（--primary #f0b90b默认不出现，[data-theme=redgold] .card.kpi无覆盖）
5. 状态色只在tag/角标（主区域无编码）

**方案**（用户选全部P0+P1+P2，5-7h）：
- **P0核心3项**：①数字状态着色（.cv-val按涨跌/情绪分色阶class，涨停红#e6492e/跌停绿#2e8b57/成交额放量红缩量绿/情绪分色阶）②左侧3px状态色条（.card.kpi border-left:3px solid+data-state属性）③默认金色顶条（.card.kpi::before渐变金条linear-gradient(90deg,transparent,var(--primary),transparent)）
- **P1增强3项**：④KPI卡内嵌迷你sparkline（复用P0-1基础设施，.kpi-spark 30px高）⑤状态背景渐变（强势半透明金var(--bg-best)/异常淡红/冰点淡蓝/过热淡红）⑥hover动效扩展所有KPI（不只kpi-clickable，.card.kpi:hover背景变深+上浮+阴影）
- **P2高级2项**：⑦3情绪分专属大卡（a_sentiment/cross_market/fear_greed更大尺寸+渐变背景+恐贪指数0-100进度条蓝->红渐变标当前位置）⑧玻璃拟态（.card.kpi半透明rgba(37,40,54,0.85)+backdrop-filter:blur(8px)+多层阴影）

**已有可复用**：sparkline基础设施（P0-1在独立.spark-grid L1033，可嵌入KPI卡）/红金主题色变量（--primary #f0b90b金/--bg-best半透明金/--bg-active暖棕/--primary-bg深棕金）/角标10状态色/hover动效（.kpi-clickable L1737-1742）/情绪分emoji标签（🔵冰点/🟦偏冷/⚪中性/🟠偏热/🔴过热 app.js L1176-1183）

**实施约束**：
- 预估成交额已验收✓（commit be49e0064+f81a31bda），app.js KPI渲染段不再冲突，可直接派实施agent（改 app.js KPI渲染段 L7935-8172+sw.js）
- 改app.js KPI渲染（L7935-8172）+ style.css（L832-1031 KPI样式）+ critical-css（index.html L70可能加变量）+ sw.js CACHE_VERSION bump=v2-20260805-kpi-design
- 23:00+推main（和跌停池根治+通知修复+性能优化+预估成交额+信号方案B+8/5 R2根治一起）
- 改app.js后build_min+bump_asset_version+bump sw.js（铁律1）

**状态**：⏳ 待派实施agent（预估成交额已完成无冲突，推main后可派）
