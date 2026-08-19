# TASKS.md - 情绪看板迭代任务清单（监管 + loop 工作模式）

> 这是「监管 + loop」工作模式的唯一共享任务文件。子进程开工前**必读本文件** + `REQUIREMENTS.md`（需求真实来源）+ `NOTES.md`（调研笔记）。监管（主进程）不直接干活，派子进程领任务循环。

> **历史已完成项/旧叙述已归档两处：①2026-07-06 ~ 07-20 晚续3 交接状态、22 任务全 done、综合AI风险预警 P1/P2/P4 全闭环 → [docs/archive/TASKS-done.md](docs/archive/TASKS-done.md)；②07-21 ~ 08-16 旧交接轮次/旧需求章节（绝大多数已完成/过期/搁置）+ 📍当前会话状态旧滚动交接轮次 → [docs/archive/TASKS-history-archive-20260820.md](docs/archive/TASKS-history-archive-20260820.md)。本文件只保留最新交接（1-2 轮）+ 大纲 + 工作约定 + 活跃待办（含 08-04 三章）+ 保留待办块。归档对照表见 docs/tasks-narrative-slim-20260820.md。**

## 📍 当前会话状态（compact 恢复用,每次状态变化后 Edit 更新）

> compact 后第一动作:读本小节恢复 transient 状态(活跃 agent/cron/commit 链/正在等什么)。详见 memory `compact-recovery-checklist`。

**最后更新**:2026-08-19 14:0x(**TASKS.md 瘦身方向定=任务治理(非文字压缩),晚上开工;等 18:00 后用户安排**)。**此前**:2026-08-19 13:5x(**TASKS 归档清理 #76 + 熔行修复 #77 闭环**)。本轮:
- **📌 #76 TASKS.md 归档清理已完成并合 main(9359f798f)**:`tasks_archive.py` L257 归档规则扩为 level(2,3,4),支持 level3(`###`)已完成块归档。TASKS.md 233258→204213B(瘦身 87.5%),16 个历史 `### P2-新-X ✅`(7-20~7-29)老已完成块精确归档进 docs/archive/TASKS-done.md,64 个活跃待办零丢失,幂等过(dry-run 归档 0 块不再重复)。评审 2026-08-19 reviewer 条件性 PASS。**pending-features-index #76 已标完成**。
- **📌 #77 compress_status_line 熔行已修复并合 main(e54adcb1f)**:根因=`tasks_archive.py L98-116 compress_status_line` 压缩超长状态行返回缺尾 `\n`,归档时把「下一行」熔成同一物理行(既有 bug,与 level3 无关,reviewer find #1)。**排查同类抓出 2 处历史熔行**:TASKS.md L32(`- **#16 重归类**`)+ L58(`**AI 预测缺口核实**`),均拆回独立行。修复=`return head + marker + "\n"` 补尾换行根治 + 拆两处熔行 + 自测(py_compile/dry-run 幂等压缩 0 行/§48】 复查清零)。用户确认「做掉吧」后修(§23.7 既有 bug 需确认)。**pending-features-index #77 已标完成**。
- **⏳ 晚上核心工作(用户 2026-08-19 定方向)**:TASKS.md 真正瘦身 = **任务治理**——逐个任务核实现状态:已完成→关闭/归档、废弃不要→删除、真活跃→保留跟进。非文字压缩。**开工流程(见 pending-index #78)**:派 researcher 全量盘 TASKS.md 待办→逐个核 commit/上线状态→产三分类清单(完成可关/废弃可删/活跃保留,含证据链)→用户过清单拍板→implementer 按清单处理→main-merge 上线。⚠️ **避坑(memory [[archive-dispatch-by-block-type]])**:第一次按行号一刀切误删 28 活待办已回滚;「📍当前会话状态」块 = 历史交接 ~28KB(可压)+ 活跃待办 ~48KB(accum_nav 前复权 16 条/全球指数盘中实时 8 条/飞书群处理 6 条等,代码疑似已实现但状态未核,researcher 逐条核)。**也并入今晚**:#73(8 宽基四档展示)/#74(邮件广播 hit 白名单过滤)。#75(方案1 REPO 强校验)等稳定后跟进。
- **📌 代理切官方+按需thinking 落地(commit 206c6143e,memory kickstart 教训)**:thinking_proxy.py 注入逻辑升级=flash 默认注入 disabled 关思考(执行类省 token),仅请求显式 `thinking.type=enabled` 时放行思考(`explicit=True` 日志),adaptive 仍按默认关;plist 改 TTP_PROVIDER=official(api.deepseek.com/anthropic)+settings sk-key 走代理;三态 curl 200 验证。⚠️ 代理配置下次重启别用 kickstart(不读 plist,本次两次改坏的根因,见 memory [[launchctl-kickstart-does-not-reread-plist]]),改 plist 用 bootout+bootstrap。
- **📌 hooks 飞书抄送已补回**:用户重置配置丢了 hooks,从模板(tpl-proxy-full)补回 hooks.Stop(claude-says 0token 抄送),保留官方 env。**下次重启会话生效**。
- **📌 main-merge.sh commit 分支修好 + token_cache_stats 自动 commit+push 上线(8b63a7b9c)**:①main-merge.sh commit 分支改为只盯 BUMP_PRODUCTS(10 个前端产物)diff,不再用整个工作区 diff(原 bug:工作区有无关 M 如 README→误入 commit 分支→bump 无变更→空提交 exit 1 卡死,本次实测已修好,推送过程正常)②token_cache_stats.py --append-daily 追加 README 命中率走势后自动 add+commit+push main,幂等跳过/遇冲突不静默(方案①,绕开 main-merge 统一入口)。
- **⏳ 待办 main-merge.sh 残余抖动**:本次 merge 最后一步 push 走非 0 分支 exit 1(手动 push 成功、origin/main 已确认 8b63a7b9c),疑似 push 瞬间网络抖动触发重试、重试 rebase 撞工作区 plist M 改动,交付未受影响但脚本有残余抖动待修。
- **📌 #69 已完整上线**:新增**非默认推荐**降亏键 `excludeSpecialBearCyb`(excludeSpecialBear 的创业板 cyb 四档版,默认关+🆕NEW,凯利区独立开关供人工复测;2026-08-19 用户拍板:不动 v1.1.2 默认主键 hs300,8键+1类默认组合零改动)。链路:signal_kelly_backtest.py 注入 market_tier_cyb + queries.py cyb 四档谓词 + lab.js 新键 toggle + app.js/purpose-notes 公示 → reviewer PASS(公示数字修复为「收益待用户实测」)→ main-merge.sh 统一 merge+bump(版本串 **20260819-a353**)+ deploy 上线(§24⑤ 校验 + 版本进度 A/B PASS)+ §0 三查齐(线上 signal_kelly_trades.json 含 market_tier_cyb 153 条 cyb≠hs300 独立计算 / overview 含 cyb_tier / app+lab.min.js 含新键 / index 版本串一致)。commit 链:c8095538c(merge+bump) + 57f6a1c66(子页 about/guide/privacy 版本串同步)。
- **📌 新增待办 #74**(pending-features-index,commit 869af405a):check_signals.py L708 `ai_macro.hit` 未做 AI_MACRO_KEYS 白名单二次过滤(reviewer 非阻断发现——默认关非推荐键的 hit 也会把信号从邮件广播候选剔除,对普通用户本不该生效)。
- **⏳ 待安排/待办**:①#73 8 宽基四档展示(sh/sz/csi500/cyb/sz50/csi1000/kc50 走势图四档色带,hs300 已完成,纯展示,用户 2026-08-19 拍板待安排)②#74 邮件广播 hit 白名单过滤 ③用户实测凯利区 excludeSpecialBearCyb 开关(数据口径/开关/公示已就绪,公示写「收益待用户实测」)。
**前·最后更新**:2026-08-19(**并行降级安全 B 方案落地 + 防再犯五条机制全上线**)。本轮:
- **📌 五条防再犯机制全部上线 main(523af2813)**:A 版本串倒退哨兵+B merge 净回退校验(scripts/check_version_progress.py,挂 deploy 安全网,P1 静默口子已修 fc6248ffc/cad362838)+ C 同文件并发串行(scripts/check_file_owners.py,扫 /tmp 进度文件,mtime>24h 视为历史)+ D push main 统一入口(scripts/main-merge.sh,8 源检测+三态 rebase+±5min 时点缓冲+统一 build_min+bump)+ E 写源树统一 helper(scripts/pick_repo.py,守卫阻断主动告警)。前序 A/B/E merge main 782af79d1(含诱因链报告 docs/conflict-overwrite-triggers-2026-08-18.md + 收益成本报告 docs/parallel-cost-benefit-2026-08-18.md)。
- **📌 用户拍板「B 降级安全并行」(2026-08-19)**:docs/parallel-cost-benefit-2026-08-18.md 净账打平到略亏(收益 3-5 天 vs 成本 4.5-8 天,merge 吞吐 19/天 10x 但代码量没涨)→ 保留研究并行+版本发布速度(6天4 tag),从根因堵 worktree 三洞(stale base/同文件并发/版本串撞号);不做 A 废除(太极端)不做 C 现状(密度会复现)。
- **📌 新工作流规范生效**(已同步 role-implementer SKILL.md §0/§1/§3/§4 + docs/main-governance.md + CLAUDE.md §8/§14):agent 只 push feat 禁直接 push main;worktree 不自行 bump 版本串(主控 merge 走 main-merge.sh 统一 build_min+bump);完成报告必带 base commit+版本串前后值;开工强制 rebase origin/main;主控 merge 冲突即停报(§23.11)。
- **📌 pending-features-index 已同步(7fd035cfb)**:五条机制已完成移已排除清单;#70-72(C/D 实施)已完成。
- **⏳ 待用户拍板**:①~~#69 四档判定源 cyb vs hs300~~(**2026-08-19 已拍板实施上线**:改非默认新键 excludeSpecialBearCyb,见上方本轮块)②优化清单 docs/optimization-decision-checklist.md #1 次日开盘/#4 R2 阻断/#7 百分位/#9/#14/#15。
- **📋 备注**:claude-work-mode/README.md 有预先存在 M 改动(08-18 token 走势表追加,非本会话,未动未 commit)。
**前·最后更新**:2026-08-18(**AI 预测历史反思严格口径+三档联动已实施**——gen_daily_brief.py:①_classify_failure 升级:老条目(无区间)仅方向命中=未中进反思(direction_only 新 type),新格式含区间三层全命中才不算失败;②_history_stats 改严格口径(仅方向命中不计中,计分母);③三档联动 _reflection_tier/<50%加强/50-75正常/75-90轻量/>90参考借鉴+build_reflection_inject/meta 按档位出文案与强度;④8/11-13 三条自动进反思库(direction_only)、8/14 direction_fail 时间隔离 8/18 自动补录;⑤§21 公示同步 app.js L22513 严格口径+三档,前端 _dbReflectionHtml 加 direction_only+档位标题;§24 bump a348→a349+build_min)。

**📌 818-fix(首页明日关键事件 818)已上线 main**(2026-08-18,commit cf85862d6):根因=launchd 给 fetch_news 注入 REPO=trade-data,上传子进程 `env.setdefault("REPO",...)` 不覆盖已有值 → upload_r2/staticdata 按 env.REPO=trade-data 拼源目录=**trade-data/static-site/data(旧8/17 实体目录)**,每次「R2 同步 OK」实际传旧版,线上 news_digest 停 8/17 → 前端「明日=818」。修复:①应急上传本地新版(2026-08-18 13:01,md5 415f3806)到 R2 data/news_digest.json+purge+同步 staticdata 备站,线上已恢复 date=2026-08-18(明日=8月19日)②根修 fetch_news.py sync_news_digest_live 上传子进程改 `env["REPO"]=REPO` 强制覆盖,读写统一走 trade;修正注释(trade-data/static-site 实为**实体目录**非 symlink,由 gen_daily_brief 等采集器写入,不改为 symlink)③前端守卫:_loadNewsDigest 加 stale(date<本地今日),明日关键事件/今日要闻行 stale 时标「(数据待更新)」不把昨日当明日(§23.3 同模式今日要闻行一并覆盖)④移动端布局:style.css @media≤768px db-nextday-row flex-wrap,k/v 各占整行内容铺满不再挤右半块⑤§24 同 commit build_min+bump_asset_version(版本串 a348)+bump sw.js CACHE_VERSION(v6-20260818-a348)⑥备站 sss.sugas.site 缺 news_digest=运行时数据不 commit git 的既有设计,靠 fetchJSON 备站主动域名策略重写 `./data/*`→`https://ss.fx8.store/data/` R2 fallback,线上已读到新版。验收:线上 app.min.js 含「数据待更新」+style.min.css 含 flex-wrap:wrap+sw a348,三查齐。

**📌 四档收窄为仅沪深300 已上线 main**(2026-08-18,commit bf8841966+样式 1ef1fb9e6+bump a351 da6367df8):用户中途改主意「四档先不用扩散到其他指数图,只用沪深300」→ 撤回 a3b2d142f 方案B 的 queries.py 扩散段(`market='a'` 全部A股指数注入 tiers),恢复原版 `if index_id=="hs300"` 只给沪深300注入(queries.py 实际未改,原版即符合);**保留**方案B另两项:①色带高度 1/2→1/4(走势图隐藏色带轴 max:1→max:2,独立时间线面板整条不动)②全站文案「大盘四档/大盘状态」→「沪深300四档」(走势图 tooltip/series/独立面板标题「沪深300四档状态轨迹」/图例/首页chip「沪深300 ·」,均加「沪深300 单一指数口径·非综合多指数」防误解标注)。数据产物不扩散、无需重跑 export(静态产物不变,线上 sh-all 无 tiers、hs300-all 有 tiers 均已核实)。§24 同 commit build_min+bump_asset_version(版本串 a349→a350)+bump sw.js CACHE_VERSION(v6-20260818-a350)。**待跟进上报主控(2026-08-18 已处理)**:每日速递邮件 `daily_summary_email.py`/`gen_daily_brief.py` 正文 summary_short 的「大盘状态:」文案已改「沪深300四档状态」并上线(commit f22000fc0,用户已确认,market_summary.py L533/L564 两处;summary_short 由邮件/前端读字段消费不自拼文案,无需重跑 export)。

#### 待办
- [ ] (次日开盘回测 2026-08-12 用户"弄好后落档报告放待办,我明天起床看") 真实跟信号操作口径确认【🔶 部分完成:②已做成「次日分批挂单SOP」按钮 lab.js(2026-08-15 SOP,「次日买入玩法」lab-sigkelly-nextday),①「前端展示/回测默认改次日开盘口径」未改——默认仍当日收盘口径,待用户确认是否切】:信号收盘后固化、次日开盘买入是真实可执行口径,成本极低(每日池净利差 -0.01%、每笔1万 -0.57%,"竞价高开吃掉利润"不成立,跳空均值 +0.031%/中位0/>1%仅6.2%)。建议①后续回测/前端展示默认改「次日开盘」口径(数据100%覆盖实现成本低)②操作:开盘不追,挂开盘下方 -1% 限价单(未触达按开盘价兜底)→K=1 +844,931/52.81%(+3.8pt)触达率39.8%,挂-2%更深处不划算。报告 docs/kelly/position/kelly-nextday-open-backtest.md(基线可复现/伪跳空剔除/覆盖率100%/A-F二阶近似诚实标注)
- [x] (飞书 2026-08-11 18:16) 前面发的两句消息漏收了吗，是否还能读取到
- [x] (飞书 2026-08-11 18:12) 报告群也是一样的，我会对里面的结果对你问做，你正常就是只出处理给答复就好，有改动也要转到开发群
- [x] (飞书 2026-08-11 18:12) 告警群一般我也会回复，虽然不是需求，但是属于对告警内容的问询，比如有没有处理好，是否自愈等，可能上升不到需求大任务，但是如果产出的东西需要大改代码，就需要转回…
- [x] (飞书 2026-08-11 17:55) 需求：一定要靠前缀判断需求吗，这个需求群硬编码不行吗，其他群使用前缀是合理的
- [x] **(用户核心需求·最优先 2026-08-11) 降亏组合使用建议分析 + 全信号表**【已上线 ✓:组合使用建议分析+全信号表(quadMeta.all)落地 docs/kelly/combo/kelly-combo-usage-advice.md + lab.js 凯利区置顶两块,§0 验过 in main】。用户原话"我靠4个组合降亏信号一起使用感觉还不错。你评价一下这样的使用方法是否好。并且你回测一下你推荐怎么用（分用户投资习惯：追高趋势/短线/长线等细分行为建议 + 总建议=全量信号都看完全遵守交易页面展示的交易方法）。可以页面展示建议和理由（必须真实数据跑过回测结果才能提供建议）。其次新增一个表=全信号表（不做信号分拆测试，就全亮信号融合在一起，看全信号都用最新降亏组合的收益预估，这是最后结果，因为正常人也一定是全亮信号都看）"。**现状：代码/前端全未落地**（前端无全信号表/组合建议，grep 无结果）。已误派过 J1/J2 1月调整 toggle（那是降亏增量非核心需求，已上线）。**待办动作**：①用 signal_kelly_trades.json 66,591 笔真实回测 4 组合全开评价 + 分投资习惯细分建议 + 总建议 ②实施前端展示建议和理由 ③新增全信号表（全亮信号+最新降亏组合收益预估，不拆分象限）
- [x] (SVG P1 2026-08-11) 走势图轻量扩展【已上线 ✓:首页 sparkline 批(commit `293b1d101`)把 ~39 实例 echarts→轻量 SVG(_ntSparkSVG/_reRenderHomeSpark),§0 验在 origin/main】。P0 已上线(`d9a465dc6`,08-11 02:58 main,site-config 框架 config/site.yaml→boot.json→_siteConfig 单例 + 2 消费者 charts.lightweight/intraday.default_mode,ETF 评分弹窗近30日走势轻量 SVG + 皮肤弹窗"⚡走势图渲染"切换)。**P1 待做=把轻量 SVG 走势图扩展到所有消费点**(首页 sparkline/KPI sparkline/分时图等)，P0 commit body 明写"P1 铺路"但从未落档待办从未实施=漏落档缺口。用户 2026-08-11 追问状态(此前质疑"首页没效果"即 P0 只接 1 消费点,举一反三规范要求覆盖全站走势图渲染点)。排期:飞书链路 2 agent(hooks 抄送+P0/P1 修复)落地后
- [x] (飞书 2026-08-11 23:01) 怎么没有同步 我在终端里发的 代办给我看看？ 以及你的回复？ 到这个群里？
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

### 保留待办（tasks_archive.py 自动并入，防归档丢待办）
- [x] **P1（推荐）：加盘中 intraday_snapshot 采全球5指数实时（nikkei225/kospi/ftse100/dax/cac40）**
- [x] **P2（可选）：港股板块8个加盘中实时**
- [x] **P2（可选）：亚洲其他同时区指数（澳股 ASX200/印度 NIFTY50）**
- [x] **前置验证**：akshare 版本是否含 `index_global_spot_em` 函数（`python -c "import akshare as ak; print(hasattr(ak, 'index_global_spot_em'))"`） [待做]
- [x] **前端配套**：全球 Tab 卡片角标更新逻辑（当前 us_ 标 t1，其他 t0，加实时后是否需要新标记）
- [x] accum_nav除权日不跳(159915已验✓,512000回填后复验1.1370->1.1396)
- [x] etf_daily加accum_nav列+1520只回填(覆盖率≥92%)
- [x] 10处计算层改用accum_nav/前复权(grep无遗漏用未复权close算收益)
- [x] 159536 TE用accum_nav不虚高(对比未复权TE 10.6%)
- [x] check_data_integrity + reviewer P0 smoke
- [x] 实时展示close保持未复权(交易视角不变)
- [x] 159536 track_score<70(approx/none)非"良好",验证新算法抓出V型尖刺(原型已验证65.3✓,此为生产确认)
- [x] 1140对中≥1051对(92%)track_score非None
- [x] 全量计算<10s(实测6.3s)
- [x] board_etf_map.json<700KB
- [x] 前端_etfMatchTags同时显旧标签(🟢·良好·1.1%)+新评分(跟踪85)
- [x] 排序按track_score降序
- [x] curl overview.json含track_score字段
- [x] sw.js CACHE_VERSION bump
- [x] TE计算用前复权价或NAV(512000除权20250801=1.138->0804=0.572不污染TE,主控已验收跳变✓)
- [x] 自身跟踪591对用avg_dev≤0.2%分类(非2%TE硬阈值,2%TE全超过严),板块重叠514对用rank排序

## 总体大纲

A 股 / 港股 / 全球盘后复盘看板。Python 3.11 + FastAPI + SQLite + ECharts，Mac 本地。当前 27 个指标、13 指数、运行在 http://localhost:8000（`--reload`，改文件自动生效，**不要杀进程**）。本轮迭代目标：修回归问题 + 补国债 / 原油白银 / 红利 / A 股十年回溯 / 买卖点优化 / 行业看板 / 概览美化。

相关文件：`REQUIREMENTS.md`（需求 + 实现状态 + §9 变更史）、`NOTES.md`（调研 + 修复史）、`05-回归测试报告.md`（本轮回归）、`01-问题清单.md`（上轮 bug）、`config/indicators.yaml`（指标注册表）、`app/`（采集 + 计算 + API）、`web/`（前端）。

> ⚠ 开工先看 `data/alerts/latest.md` 是否有未处理严重告警，有则优先排查。

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
- [x] 滑点固定百分比（默认千1，可配，不用波动率模型）
- [ ] 费率对比函数：默认配置 vs 自定义配置 双回测结果对比
- [ ] FastAPI 路由 `/api/trade_sim_recalc`（POST，body 含 index_id + fee_config，缓存5分钟+限流10次/分）

### 前端配置面板（5-7h）
- [x] 弹窗内嵌"⚙ 费率配置"面板：6 input（买佣金/卖佣金/印花税/过户费/滑点/最低佣金）+ 2 select（过户费模式/滑点模式）+ 说明文案
- [x] fee_config localStorage 持久化（用户配置跨会话保留）
- [ ] "重新回测"按钮调 `/api/trade_sim_recalc` API
- [x] 底部"费率影响对比"区块：对比表（默认vs当前 收益/年化/回撤/胜率/费率成本/费率占比）+ 成本明细 + 双净值曲线叠加图
- [x] bump sw.js + build_min + bump_asset_version + deploy + 3 域名验证

### 全量重生 R2 trade_sim JSON（bug 根治，必做）
- [ ] 修正 simulate_trade.py 印花税万5 + 过户费沪深统一 bug
- [ ] 全量重生 103 个 trade_sim_{idx}_stats.json + _full.json（印花税万5+过户费沪深统一）
- [x] upload_r2 上传 trade_sim/ + trade_sim_data/ 前缀
- [ ] 验证线上 R2 JSON 含印花税字段

### 测试联调（2-3h）
- [ ] 默认配置 vs 自定义费率对比正确性
- [x] 双净值曲线叠加渲染
- [x] 3 域名验证（ss.fx8.store / sss.sugas.site / ssd.fx8.store R2）

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
- [x] 步骤0：修 upload_r2 调用 bug 3+1 处 ✅已完成(commit d5a8c8f84 R2上传恢复；2026-08-08 grep确认 pf_score_daily/weekly.sh:42+update_all.sh:146/158 均用 upload-offshore-fund/upload-fund-score 正确格式)（pf_score_daily.sh:42 / pf_score_weekly.sh:42 / update_all.sh:140(offshore)+152(fund-score) 脚本路径和子命令分开）— **盘中已派 agent aedb9f06 立即做**
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
- [x] P0-2: etf_score_list.json 18MB 按 buy/sell/hold 拆分 + 懒加载（2-4h，基金 tab -1~2s，975KB -> <100KB）。证据 `app.js:14649`，export.py 拆 3 JSON，hold 点"持有观察"才加载。**代码已实现(待commit): export_etf_score_list.py 拆3JSON + app.js/lab.js 懒加载 + upload-etf-score 命令, 等23:00+跑export** [✓ commit 3d5013a89]
- [x] P0-3: 11 个 sparkline echarts 改 SVG 复用 ntIndexSparkline L8894（2-3h，首屏 -200~500ms）。**已上线 commit 7506aa0c7**（L8172 调用 ntIndexSparkline，省11个echarts.init，仅留行业热力图L13779用echarts。NOTES §48 小节AG 落档）
- [x] P0-4: R2 大文件 Worker 代理 + Cache API 边缘缓存 ✅上线(2026-08-08)。commit 0d29fd5c3,worker/headers.js r2ProxyHandler /r2/*路由+R2_BUCKET binding+Cache API边缘缓存,前端ssd->ss.fx8.store/r2/ 53处。§0验 cf-cache-status HIT不回源。push feat:main 98c209925 GH Actions wrangler deploy

### P1（首屏次要 + 后台优化，2-3h 请求数减 95%）
- [x] P1-6: 首屏 fetch Promise.all 并行（1-2h，首屏 -300~500ms）。证据 `app.js:6998-7034` overview->signal_stats->intraday 3 个 await 串行
- [~] P1-7: index.html preconnect — ssd.fx8.store 已有(L18);腾讯分时前端已换东财push2(app.js L5971 注释 WAF拦截501);前端fetch域(push2.eastmoney.com分时等)全覆盖待调研补preconnect,非纯A级降调研项（<0.5h，首次请求 -100~300ms）
- [x] P1-8: 首页 22 JSON 合并 boot.json（2-3h，请求数 22 -> 1）。export 合并首屏 21 个小 JSON ~250KB br

### P2（按需，滚动优化）
- [ ] P2-10: app.js 17845 行无 code-splitting（短期 requestIdleCallback 延迟非首屏 init 2-3h / 长期按 tab 拆 chunk 8-16h）
- [ ] P2-11: 大盘 tab renderAStock 30+ echarts 改 SVG 或 IntersectionObserver 懒渲染（3-6h，切 tab -500~1000ms）
- [x] P2-12: 9 个 sticky + 3 个 IntersectionObserver 加 rootMargin + 卡片加 contain（1-2h，滚动更流畅）
- [x] P2-13: CSS transition all 改指定属性 + will-change + contain（2-4h）
- [x] P2-14: 分时图 11 个 echarts 改 SVG（2-3h，展开分时图 -300~600ms）
- [ ] P2-15: offshore_fund_* 85MB 本地 dead weight 清理（1h，确认场外基金路线图后停跑 export_offshore_fund.py + 删本地，或移 R2 upload-offshore-fund）
- [x] P2-16: update_all core pipeline 20 分钟东财封 IP，启动 industry 换源（2-4h，memory `industry-source-switch-trigger` 解除暂缓，东财 -> 同花顺/新浪）

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
