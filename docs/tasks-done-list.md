# TASKS 完成文件(done-list)

> 4 态/4 文件流转(2026-08-20 用户定):①活跃→TASKS.md ②待办/远期→docs/pending-features-index.md ③**完成→本文件(done-list)** ④归档→docs/archive/(完成态呆满 7 天自动归档)。本文件 = 完成态落脚点,**呆满 7 天**后自动移入 docs/archive/TASKS-done.md 归档。条目标注完成态 + commit/出处链接,§5.3 核心保留(标题/结论/触发场景不丢)。
> 批次:2026-08-20 任务治理把 TASKS.md 中 43 条真完成移入(下节),关闭 3 条记录在 docs/archive/TASKS-done.md(不属完成待 7 天,直接留关闭记录)。远期/搁置移 docs/pending-features-index.md 模块十六。

## 2026-08-20 任务治理移入(43 条真完成,待 7 天自动归档)

> 治理依据:docs/tasks-governance-scan-20260819.md(researcher 逐条核:代码 grep + 数据产物 + commit 至少两重)+ 报告 docs/tasks-active-only-clean-20260820.md。以下为 TASKS.md 移除的 43 条真完成,原样保留(含案由/commit)。

- [x] (飞书 2026-08-11 18:16) 前面发的两句消息漏收了吗，是否还能读取到
- [x] (飞书 2026-08-11 18:12) 报告群也是一样的，我会对里面的结果对你问做，你正常就是只出处理给答复就好，有改动也要转到开发群
- [x] (飞书 2026-08-11 18:12) 告警群一般我也会回复，虽然不是需求，但是属于对告警内容的问询，比如有没有处理好，是否自愈等，可能上升不到需求大任务，但是如果产出的东西需要大改代码，就需要转回…
- [x] (飞书 2026-08-11 17:55) 需求：一定要靠前缀判断需求吗，这个需求群硬编码不行吗，其他群使用前缀是合理的
- [x] **(用户核心需求·最优先 2026-08-11) 降亏组合使用建议分析 + 全信号表**【已上线 ✓:组合使用建议分析+全信号表(quadMeta.all)落地 docs/kelly/combo/kelly-combo-usage-advice.md + lab.js 凯利区置顶两块,§0 验过 in main】。用户原话"我靠4个组合降亏信号一起使用感觉还不错。你评价一下这样的使用方法是否好。并且你回测一下你推荐怎么用（分用户投资习惯：追高趋势/短线/长线等细分行为建议 + 总建议=全量信号都看完全遵守交易页面展示的交易方法）。可以页面展示建议和理由（必须真实数据跑过回测结果才能提供建议）。其次新增一个表=全信号表（不做信号分拆测试，就全亮信号融合在一起，看全信号都用最新降亏组合的收益预估，这是最后结果，因为正常人也一定是全亮信号都看）"。**现状：代码/前端全未落地**（前端无全信号表/组合建议，grep 无结果）。已误派过 J1/J2 1月调整 toggle（那是降亏增量非核心需求，已上线）。**待办动作**：①用 signal_kelly_trades.json 66,591 笔真实回测 4 组合全开评价 + 分投资习惯细分建议 + 总建议 ②实施前端展示建议和理由 ③新增全信号表（全亮信号+最新降亏组合收益预估，不拆分象限）
- [x] (飞书 2026-08-11 23:01) 怎么没有同步 我在终端里发的 代办给我看看？ 以及你的回复？ 到这个群里？
- [x] **P1（推荐）：加盘中 intraday_snapshot 采全球5指数实时（nikkei225/kospi/ftse100/dax/cac40）**
- [x] **P2（可选）：港股板块8个加盘中实时**
- [x] **前置验证**：akshare 版本是否含 `index_global_spot_em` 函数（`python -c "import akshare as ak; print(hasattr(ak, 'index_global_spot_em'))"`） [待做]
- [x] **前端配套**：全球 Tab 卡片角标更新逻辑（当前 us_ 标 t1，其他 t0，加实时后是否需要新标记）
- [x] accum_nav除权日不跳(159915已验✓,512000回填后复验1.1370->1.1396)
- [x] etf_daily加accum_nav列+1520只回填(覆盖率≥92%)
- [x] 10处计算层改用accum_nav/前复权(grep无遗漏用未复权close算收益)
- [x] 159536 TE用accum_nav不虚高(对比未复权TE 10.6%)
- [x] check_data_integrity + reviewer P0 smoke
- [x] 实时展示close保持未复权(交易视角不变)
- [x] 1140对中≥1051对(92%)track_score非None
- [x] 全量计算<10s(实测6.3s)
- [x] board_etf_map.json<700KB
- [x] 前端_etfMatchTags同时显旧标签(🟢·良好·1.1%)+新评分(跟踪85)
- [x] 排序按track_score降序
- [x] curl overview.json含track_score字段
- [x] sw.js CACHE_VERSION bump
- [x] TE计算用前复权价或NAV(512000除权20250801=1.138->0804=0.572不污染TE,主控已验收跳变✓)
- [x] 滑点固定百分比（默认千1，可配，不用波动率模型）
- [x] 弹窗内嵌"⚙ 费率配置"面板：6 input（买佣金/卖佣金/印花税/过户费/滑点/最低佣金）+ 2 select（过户费模式/滑点模式）+ 说明文案
- [x] fee_config localStorage 持久化（用户配置跨会话保留）
- [x] 底部"费率影响对比"区块：对比表（默认vs当前 收益/年化/回撤/胜率/费率成本/费率占比）+ 成本明细 + 双净值曲线叠加图
- [x] bump sw.js + build_min + bump_asset_version + deploy + 3 域名验证
- [x] upload_r2 上传 trade_sim/ + trade_sim_data/ 前缀
- [x] 双净值曲线叠加渲染
- [x] 3 域名验证（ss.fx8.store / sss.sugas.site / ssd.fx8.store R2）
- [x] 步骤0：修 upload_r2 调用 bug 3+1 处 ✅已完成(commit d5a8c8f84 R2上传恢复；2026-08-08 grep确认 pf_score_daily/weekly.sh:42+update_all.sh:146/158 均用 upload-offshore-fund/upload-fund-score 正确格式)（pf_score_daily.sh:42 / pf_score_weekly.sh:42 / update_all.sh:140(offshore)+152(fund-score) 脚本路径和子命令分开）— **盘中已派 agent aedb9f06 立即做**
- [x] P0-1: renderTab 移除顶层 `await loadEcharts()`，子 render 按需加载（1-2h，首屏 -300~1500ms）。**已上线 commit 89d29b607**（L4467 fire-and-forget + 5处子render await L4484/8142/8768/10434/15582，16处echarts.init调用路径全部确认有保障）
- [x] P0-2: etf_score_list.json 18MB 按 buy/sell/hold 拆分 + 懒加载（2-4h，基金 tab -1~2s，975KB -> <100KB）。证据 `app.js:14649`，export.py 拆 3 JSON，hold 点"持有观察"才加载。**代码已实现(待commit): export_etf_score_list.py 拆3JSON + app.js/lab.js 懒加载 + upload-etf-score 命令, 等23:00+跑export** [✓ commit 3d5013a89]
- [x] P0-3: 11 个 sparkline echarts 改 SVG 复用 ntIndexSparkline L8894（2-3h，首屏 -200~500ms）。**已上线 commit 7506aa0c7**（L8172 调用 ntIndexSparkline，省11个echarts.init，仅留行业热力图L13779用echarts。NOTES §48 小节AG 落档）
- [x] P0-4: R2 大文件 Worker 代理 + Cache API 边缘缓存 ✅上线(2026-08-08)。commit 0d29fd5c3,worker/headers.js r2ProxyHandler /r2/*路由+R2_BUCKET binding+Cache API边缘缓存,前端ssd->ss.fx8.store/r2/ 53处。§0验 cf-cache-status HIT不回源。push feat:main 98c209925 GH Actions wrangler deploy
- [x] P1-6: 首屏 fetch Promise.all 并行（1-2h，首屏 -300~500ms）。证据 `app.js:6998-7034` overview->signal_stats->intraday 3 个 await 串行
- [x] P1-8: 首页 22 JSON 合并 boot.json（2-3h，请求数 22 -> 1）。export 合并首屏 21 个小 JSON ~250KB br
- [x] P2-12: 9 个 sticky + 3 个 IntersectionObserver 加 rootMargin + 卡片加 contain（1-2h，滚动更流畅）
- [x] P2-13: CSS transition all 改指定属性 + will-change + contain（2-4h）
- [x] P2-14: 分时图 11 个 echarts 改 SVG（2-3h，展开分时图 -300~600ms）
- [x] P2-16: update_all core pipeline 20 分钟东财封 IP，启动 industry 换源（2-4h，memory `industry-source-switch-trigger` 解除暂缓，东财 -> 同花顺/新浪）


## 2026-08-20 费率改造已实现(10 条,用户「完成就按完成的走」移入)

> **修正背景(2026-08-20 用户拍板)**:费率可配置(#13/14/18/22)早已上线,原被 TASKS.md 误留为活跃的 10 条费率待办,经逐条代码 grep + 线上 R2 curl 实测均**已实现**,移入完成文件。判据:simulate_trade.py(印花税 :57 / 过户费3模式 :58-59+_transfer_applies / 抽核心 fee_config :45+_normalize_fee_config / 修 bug :40)、app/main.py:586 /api/trade_sim_recalc、static-site/app.js feeCompare+双净值不重算、线上 R2 trade_sim_hs300_stats.json(generated_at 2026-08-19)含 fee_config.stamp_tax/transfer_fee_mode。

- [x] simulate_trade.py 抽核心为可调用函数（传 fee_config 参数）→ simulate_trade.py:45 fee_config 9字段 + L73 _normalize_fee_config + L537/659/789 simulate_fixed_1w/simulate_all_in/simulate_sell_all 均接 fee_config 参数 + L444 _buy_with_fees/L484 _sell_with_fees 均接 fee_config
- [x] 加印花税：卖出收 0.05%（万5，默认值，可配）→ simulate_trade.py:57 stamp_tax:0.0005 + L501 _sell_with_fees stamp_tax=sell_amount*fc['stamp_tax'](+前端 _SIM_FEE_PRESETS stock_def)
- [x] 过户费3模式：沪市/深市/沪深统一（默认沪深统一 0.001% 买卖都收）→ simulate_trade.py:58-59 transfer_fee 0.00001 + transfer_fee_mode:hs_unified(默认) + L427 _transfer_applies 三模式(sh/sz/hs_unified)
- [x] 费率对比函数：默认配置 vs 自定义配置 双回测结果对比 → app.js L23845-25026 feeCompare+feeCompareMode('static'读预生成/localt本地精确重算)+双净值曲线叠加(L24878)
- [x] FastAPI 路由 /api/trade_sim_recalc（POST body index_id+fee_config）→ app/main.py:586 @app.post("/api/trade_sim_recalc") def api_trade_sim_recalc(body:TradeSimRecalcBody)
- [x] "重新回测"按钮调 API → 实现方式演进(2026-08-15):前端去掉「按钮调 API」,改由费率变化驱动——预设档→读预生成静态 fee_compare.json 精确档,custom 手改→前端本地精确重算。目标(费率可配+重算对比)达成(A-L25011 注释「已去按钮」)
- [x] 修正 simulate_trade.py 印花税万5 + 过户费沪深统一 bug → simulate_trade.py:40 注释(2026-08-19 根治:漏印花税+过户费只沪市ETF两 bug)+ L57/58-59(印花税卖出收、transfer_fee_mode 沪深统一)
- [x] 全量重生 103 个 trade_sim_{idx}_stats.json + _full.json（印花税万5+过户费沪深统一）→ 线上 R2 trade_sim_hs300_stats.json generated_at 2026-08-19 19:22 已含 fee_config(含 stamp_tax 0.0005/transfer_fee_mode hs_unified);103 个通配批量于 #18 全量重生
- [x] 验证线上 R2 JSON 含印花税字段 → curl https://ss.fx8.store/r2/trade_sim_data/trade_sim_hs300_stats.json 实测含 fee_config.stamp_tax
- [x] 默认配置 vs 自定义费率对比正确性 → app.js 对比区块(默认 vs 当前,全历史窗口)+ 双净值叠加 + 前端本地精确重算验证(预设/自定义两态都覆盖)


## 2026-08-20 pending-features-index.md 治理批量移入(37 条真完成,待 7 天自动归档)

> 按 researcher 逐条核 commit 实锤(见 pending-features-index.md 各条 commit 证据,均已在 origin/main)。从 todolist 移除真完成项 + 刷新 #63/#64/#69/#73/#74 状态(已合 main)。来源:docs/pending-features-index.md 模块一~十六。以下每条标注「原编号 + 标题 + commit/上线证据」。§23.3 举一反三:done 后全站无同编号残留(见#XX交叉引用已保留原位)。

- [x] **#1 edge-tts 语音播报**(首页 AI 预测上方播放按钮朗读) — 2026-08-16 上线 a8a4d632f,版本串 a281;后端 edge-tts 合成 mp3 传 R2,前端 _dbPlayBtn 🔊 + <audio> 经 /r2/ 代理播
- [x] **#2 AI 预测前端「辩论详情入口」+「弃用标志」+「结论展示」** — 2026-08-12 上线 4bc48da1a(meta.version=ai-multi)
- [x] **#7 daily_brief P1-6 新闻舆情/宏观事件维度** — 2026-08-16 注入侧+前端展示位全落地(244c00cff/a7925c77d/a283/a284 系列 + 33ef7bd33 + 49be3c317 + 70c625386,版本串 a285→a296)
- [x] **#16 凯利组合 Walk-forward 滚动验证(样本外)** — 2026-08-16 commit 299db6167 在 origin/main + 落档 kelly-walkforward-validate.md(v1.1.0 8键全开样本外有效不过拟合)
- [x] **#24 飞书需求群硬编码判断** — scripts/feishu_ws_listener.py L737/781 已实现(白名单需求群免前缀直接落盘)
- [x] **#25 飞书 hook 心跳自检告警** — 2026-08-17 上线 6edca04af(发送侧+listener 接收侧心跳维度,四态自测+33测试全过)
- [x] **#35 理财专员使用指南 about 页上线** — 2026-08-18 上线 scripts/gen_guide_html.py 渲染 → static-site/guide.html;about 目录+互链;README 已补
- [x] **#36 signal-finalize-time 两段式 15:05 A股初版** — 2026-08-14 overview signals_meta 三态 + 2026-08-15 W1 放宽 71d238785 + 三态提示 3311eca8d 已合
- [x] **#39 AI降亏过滤开关(宏 + 三级级联UI)** — 三级级联 UI 已实现(lab.js `#lab-kelly-ai-macro-body` + _kellyAiMacroMembers 联动 8 键),"AI宏=新默认"90f948e3c 上线;穷举见 kelly-k2c5-exhaust-interaction.md
- [x] **#40 凯利降亏折叠区重归类** — 2026-08-12 上线 bacdf8c9b(4 组经济逻辑分类+组内比值降序+⚠️监控置尾)
- [x] **#41 首页 AI 仓位建议 rename + 范围扩展(#4)** — 2026-08-12 上线 760aa9ffb(positionCap 改名 + pop tooltip + 范围扩展)
- [x] **#43 feishu 抄送「整段全抄送」** — 2026-08-12 上线 9694f8fe7
- [x] **#44 分时图 3 条低危改进** — 2026-08-12 上线 537109553(跨空泄漏钳制/legend 超宽/5字行业 legY)
- [x] **#45 凯利「4组合全开」建议文案修正** — 组合降亏行标题改「组合降亏(可选分析非默认推荐)」,随 #39 一起落地
- [x] **#46 降亏面板①口径标注 + 真实对照行** — 2026-08-18,commit 63fb27391(991万→961万/23.9万→17.7万旧口径过时)
- [x] **#47 K档位评级 A 模式数值数据溯源落档 + 每日池重算** — 穷举数据已落档;_pcRating 重算并入 #48 已完成
- [x] **#48 页面 `_kellyFadeFlagGroups` 31键 ratio 每日池口径重算 + _pcRating 重算(§22)** — 2026-08-14 重算落地(lab.js 31键 + _pcRating static 快照 + common.js _AI_POSCAP_RATING + app.js tooltip 三处一致,主推 K1)
- [x] **#49 G/H/I 长持模式持仓≤20倍本金硬控手段** — 2026-08-14 上线(lab.js 凯利回测区「ai长线模式(G/H/I)仓位管理」开关,fifo20w,峰值持仓≤20倍本金;FIFO 内核与报告 §7.2 K1 口径逐位对齐§21;purpose-notes/README 同步)
- [x] **#50 每日池口径默认 K 档/toggle 决策落档** — 决策已定+落档 README L78/L117(默认 AI宏7键 + G 用 13万 P≤3d 可操作口径 155.78%/+202,508);实施并入 #48
- [x] **#52 §23.6 ②公示:入样宇宙规则三处公示文案** — 2026-08-14 上线 d798854aa(AI建议 badge + AI警示 + 未入样本 + 凯利区);AI过滤视图补充公示 489f0bdb4
- [x] **#53 首页「AI过滤视图」两开关正交** — 2026-08-14 上线 489f0bdb4,review PASS(AI降亏=删除线层/AI仓位=badge层)
- [x] **#54 公示补「+1」(AI宏4+3+1)** — 2026-08-14 上线 cfd37057e
- [x] **#55 $压缩冲突 P0 修复** — 08-15 根治上线(build_min.py keep_fnames/保留函数名,terser 不再 mangle 成单字符)
- [x] **#57 sw.js 版本注释过时修正** — 2026-08-17 上线 2d6bc6207(清残留,purge 后三站零残留,纯注释零行为)
- [x] **#58 分析参考点AI监控三合一** — 2026-08-16 二次迭代,版本串 a275→a279,commit ac61248a4/33c722997(K档启用+双图轻量SVG+❓hover+SVG3色基准+by_k排除未入样1172条)
- [x] **#59 K2C5 补跑每日池同口径比值** — 2026-08-16 commit f5d218492 在 origin/main + 落档 kelly-k2c5-dailypool-ratio.md(比值4.55)
- [x] **#60 分析参考点AI监控窗口语义改数据范围** — 2026-08-16 二次迭代,版本串 a275(30/60/90 改「显示范围」)
- [x] **#61 邮件/飞书信号带「回测宇宙+AI过滤+AI警示+AI建议」标记** — 2026-08-17 commit a22aa741a 在 origin/main:check_signals.py L49/L544-790 + README L103
- [x] **#63 v1.1.2 凯利三键改造** — tag v1.1.2 已打;excludeSpecialBear 升四档判定 + 2 默认关备选键;R1_all +65,551 复现(commit 已在 origin/main)
- [x] **#64 历史四档轨迹图** — 2026-08-18 实施,commit 2d5e1621b 在 origin/main(纯展示不影响过滤)
- [x] **#68 优化批次 E:降亏面板口径标注** — 2026-08-18,commit 63fb27391(与 #46 同 commit,待 merge 现已合 main)
- [x] **#69 四档升级 v2:excludeSpecialBearCyb 新键** — 2026-08-19 commit eaff6d781 在 origin/main(后端回测注入 cyb 四档 + queries.py 谓词 + lab.js 新键 + app.js/purpose-notes 公示)
- [x] **#73 8代宽基四档展示(核心已上线)** — 2026-08-19 commit 7872cccbf 已合 main:后端 index_detail 注入 8 宽基 tiers + 前端色带动态化
- [x] **#74 check_signals.py L708 ai_macro.hit 白名单二次过滤** — 2026-08-19 commit 41105d6a8 在 origin/main:与 _calc_signal_markers L748 同口径(§22)
- [x] **#76 tasks_archive.py 支持 level 3 已完成块归档** — main-merge 合 9359f798f:TASKS.md 233258→204213B 瘦身、16块精确归档、待办零丢失
- [x] **#77 tasks_archive.py compress_status_line 缺尾换行致熔行** — commit e54adcb1f push main:补尾换行根治 + 拆 L32/L58 两处熔行
- [x] **#78 TASKS.md 瘦身:任务治理方向已定且已实施** — 2026-08-20 治理落地:43 完成归档 + 3 关闭 + 远期 11 移本表十六节 + TASKS.md 只留活跃(报告 tasks-active-only-clean-20260820.md)

## 2026-08-21 状态同步补登记(做了没标,9 条真完成,待 7 天归档)

> 代理背景:2026-08-21 用户发现 #73/#74 做完未更新状态(pending-index/done-list 未同步),主控核对 git 链发现同类漏网 7 条(#65/66/67/70/71/72/62)。逐条 `git cat-file -e origin/main:<hash>` 实锤均在 main 链。从 pending-index 状态列「待办/未实施」刷新为已完成 + 补登记本文件。§23.12 4 态流转:完成→完成文件。

- [x] **#65 优化批次 B:采集层提速(ab37 baostock 降并发+熔断 / ab38 core 采集提速)** — merge 571c18ef7 + 7ab3dc3fa 在 origin/main(采集提速 ab37 降并发+共享熔断/ab38 core 提速/O2 etf_score)
- [x] **#66 优化批次 C:O2 etf_score 提速** — 同 571c18ef7 合入(export_etf_score_list.py workers 6→8-10+空返降重试,省 2-3min)
- [x] **#67 优化批次 D:宇宙规则首页 1:1 走查 + signal_notified 双副本权威化** — merge b317d85c3 + e4fdcead4 在 origin/main(宇宙规则收尾 8 步联动缺口 + signal_notified 双副本权威化)
- [x] **#70 防再犯 C/D:三缺口① base 新鲜度事前校验** — b74368b5a + 2cbec0452 在 origin/main(main-merge.sh 三态 rebase + base 新鲜校验)
- [x] **#71 防再犯 C/D:同文件并发串行 + worktree agent 不 bump** — 同 b74368b5a(check_file_owners 同文件并发串行 + SKILL.md 不自行 bump+只 push feat)
- [x] **#72 防再犯 C/D:push main 统一入口 + bump 唯一权威** — b74368b5a 在 origin/main(main-merge.sh 统一入口,机制 C/D,后续各 merge 均走此入口)
- [x] **#62 overview.date 盘中过时后端根治** — b59c08838 在 origin/main(后端根治今日锚根因)+ 走势图 T 日锚 b0c87c183(a320,前端 T 日提示用 signals_today 最新日期)——pending 原标「后端根修未定」已闭环
- [x] **#51 §23.6 入样宇宙规则首页 1:1 遵从 + 8 步联动走查** — b317d85c3/e4fdcead4 覆盖(批次D 宇宙规则收尾,原 pending 标「8 步联动走查待全量验证」已闭环)
- [x] **#56 signal_notified.json 双副本权威化** — e4fdcead4 覆盖(批次D 一并处理,REPO 必须落 trade-data 断言链路)

## 2026-08-20 会话收尾移入(AI 预测体系升级 + 四档色带 bug 修复,完成态待 7 天归档)

> 来源:方向锚/反思/影子/影子md/四档色带 5 项,main-merge 统一入口合并(main-merge.sh + worktree 复刻防线),全部 commit 已在 origin/main(git branch --contains 实测)。这批是「听你的」批准的多阶段 AI 预测升级落档闭环,§23.5 四件套(报告本体+脚本+复现段+commit)齐。

- [x] **AI 预测根因调研 + TradingAgents-CN 底层深挖(用户质疑「只肤浅套用多agent辩论?」)** — commit(调研为文档非代码)。结论:TA 底层=langgraph 多智能体辩论编排(setup.py)+各 analyst prompt 内领域软因子+唯一硬权重=舆情三源加权(chinese_finance_utils.py 331行);我们诚实承认只复用了多agent辩论编排,但方向锚信号胜率(转空+均线多头84.2%)为自研8年数据挖掘,超越之;README 措辞已修正(致敬TA保留)。报告 docs/ai-predict-direction-market-winning-signals-20260820.md
- [x] **方向发展锚(第一步)+ 离线回放A/B** — commit 5bbc8fbe1(方向锚语义教学+config默认关+replay脚本)/30ed2c94c(merge main)。A/B结果:8/17修正(down→up)、8/18保持对+L3压制转多设计点通过、8/14未修正(80%+逆势锚被当参考,迭代点晋升"倾向性结论")。迭代跟踪总纲 docs/ai-predict-self-upgrade-roadmap.md
- [x] **反思=因子归因回灌(TA Reflector 内核,提前落地后续轮次3)** — commit 9a47bae97。失败归因到具体误导因子(_attribut_factor,复用方向锚)+「待规避因子」约束段回灌(build_attribut_inject);cfg 默认关reflection_factor_attribution_enabled=false=线上逐字不变。报告 docs/ai-predict-reflection-factor-attribution-20260820.md
- [x] **影子模式 7 真实交易日 A/B 验证(用户拍板数据决定开/不开/改)** — commit 52813c924。方向锚/归因全默认关但旁路算+落盘(brief_shadow.json)+聚算(aggregate_shadow.py);shadow_mode_enabled=true只控旁路不注入线上。契约 docs/ai-predict-shadow-validate-20260820.md + roadmap 第四步实施记录
- [x] **影子模式项目下 md 追踪总表(用户要求项目下 md 文件记录可实时看,非黑盒)** — commit a63a13e87 + 77ffd7041(渲染 try 防阻断)。md=data/brief_shadow.json 唯一事实源全量渲染,幂等双向维护,进 main 可从 commit 检索。追踪表 docs/ai-predict-shadow-track.md(自动生成勿手改)
- [x] **四档色带单色+无hover bug 修复(中证1000/创业板指/科创50)** — commit bb20755be + 836c1f95c(merge main)。根治:per-date匹配tier+silent:false+弹窗补tiers;本地与线上 app.min.js md5 均=d3e0a537

## 2026-08-21 回测结论落档(95)

- [x] **#95 ETF→权重龙头个股回测结论** — 无实际价值,不推荐,维持 v1.1.3。结论:同 ¥10,000/信号基准,A(ETF)全面优于 B1/B2(TOP1个股),B3(TOP1-3并集)与A持平但3倍操作量且半凯利低4pp;ETF免印花税+单标的决策+无停牌退市风险。详见 docs/kelly/backtest-ai/etf-weight-leader/etf-weight-leader-conclusion.md

## 2026-08-29 凯利懒加载修复+性能优化(96-99)

- [x] **#96 凯利trades懒加载缓存短路修复** — 根因:localStorage缓存recent.json(2.9MB/3月)命中后直接返回,跳过年份分片加载,下游5功能全坏;修复=移除缓存短路,始终走年份合并(303,280行)。commit ba6d6f7fe,v20260829-a485
- [x] **#97 t2026年份文件被跳过修复** — `if(y==="2026")continue`致合并后少43,240行(12,880 vs 56,120);yearParts改空数组+删除recent重复计算。commit 39571b3f7,v20260829-a486
- [x] **#98 overfit parity卖类信号过滤移除** — check_overfit_recent_parity.mjs删isSell过滤,实盘统计含全部交易日。commit 0c4bf94ad
- [x] **#99 P1-01 kelly-reports/review 379KB懒加载** — index.html移除defer同步加载,lab.js改动态script标签注入,仅点击报告弹窗时加载(241KB+138KB)。commit ec3e3d58f,v20260829-a487

## 2026-08-30 会话收尾移入(feat/etf-pin-zoom:ETF弹窗缩放+交易记录5项改造)

> 来源:用户连环需求(缩放缺失/预估措辞/pin成对/列合并/红badge移列)+内审2条P1修复,main-merge 204022edb 统一 build_min+bump(版本串 v20260830-a498)上线,全部 commit 在 origin/main。

- [x] **#28-1 ETF走势弹窗缩放+拖拽+重置**(commit 3e160aeb7)— 交易记录点名ETF弹窗原无放大缩小,密集处看不清;新增滚轮/pinch缩放+平移+重置按钮。panZoom内核 `_etfTrendLiteBind` 缺省false=两个复用调用点(首页sparkline/基金净值)走老路径零回归,内部reviewer逐字段核对等价
- [x] **#28-2 持仓「预估」→「至今」**(commit 586afe792)— 预核实为真实点位(accum_nav最新日)不宜展示预估,改「至今」三处(卖价标签/收益率前缀/统计口径),数字零改动
- [x] **#28-3 G/I 红稳定性存疑badge移列**(commit a4c077e24)— 模式列→最终盈亏数字下,不影响行高,纯移列
- [x] **#28-4 交易记录列合并**(commit 831827a69)— 代码+ETF名称/份额+每笔金额各合一列(上下结构),13列
- [x] **#28-5 ETF弹窗买卖pin FIFO配对+连线+聚焦hover+popover**(commit 2255f71cb)— 配对显示+连线+FIFO,popover明细(买卖日期/价格/收益率/费率/持有天/净利)
- [x] **#28-6 内审2条P1修复**(commit b938d21f5)— ①hotzone pointer-events继承吞掉hover(整块交互死码)→补auto;②FIFO下标配对交错交易错配(900组/5136笔张冠李戴)→改按原行引用buy.t===sell.t配对流。reviewer复检PASS
- [x] **codex外审 rev-20260830-001**(参考消化)— BLOCKED但3条issues逐条核实全为误报(P0说复用点破坏零回归=实为刻意零回归;P1未读缩放几何=实现已读svg._etfTrendPan.get();P2列冗余=badge单处+colDefs13单th)。真问题=内审同批P1,已修。留档 /tmp/codex-review-batch-etf-pin-zoom.md

## 2026-08-30 会话收尾追加(feat/etf-pin-zone-toggle:ETF弹窗三需求)

> 来源:用户三需求(正式/淘汰区切换+popover固定顶部不遮pin+触发行配对pin高亮),commit 5a7641692 单 commit,reviewer内审PASS,main-merge 9335d89db(版本串 v20260830-a500)上线,curl三查通过。

- [x] **#A1 ETF弹窗正式区/淘汰区切换按钮** — 默认正式区(已过S06+K1过滤),淘汰区独立整块重渲染(事件源按 src 过滤),空态「该区无此ETF交易」,切区后窗口/日期索引/pins/连线全重建无残留DOM
- [x] **#A2 popover弃用改固定顶部info条** — _positionPop/popEl/_anchorIx 整段删除,详情经 _setInfoDetail(_popContent(p)) 注入 .lab-etf-pin-infobar 固定弹窗顶部,不再盖pin信号;弹窗 max-height 提至94vh(仅本弹窗,交易列表等其他sig-kelly弹窗仍90vh零波及)
- [x] **#A3 触发行配对pin初始高亮** — 正式/淘汰两区 tr 均加 data-ib/data-bd,点击绑定读 srcKey 传第7参,渲染末尾匹配 index_id+buy_date → _focusPair 高亮(单买无sell走持有中分支),hover其他pin正常转移,匹配不到console.warn不抛错
- [x] **reviewer内审**:三需求全PASS+回归零影响(panZoom/连线/hover/返回列表行高亮未动)+node --check过,注2处非阻断小瑕疵(hotzone传多余第3参/死CSS规则.lab-etf-pin-infobar .lab-etf-pin-pop)待后续顺手清

## 2026-08-30 会话追加(feat/sigkelly-all-layout + feat/etf-pin-ui-fix + feat/sigkelly-all-width-unify)

> 来源:用户连环需求(两卡并排 + pin 4项UI修复 + 卖点×N聚合标注 + 全信号卡宽度统一),三批 commit 均已在 origin/main,main-merge 分别统一 build_min+bump(版本串 a501→a502→a503),curl 三查通过。pin 卖口口径调研落档 docs/kelly/analysis/ghi-sell-caliber-2026-08-30.md,UI 根因落档 docs/kelly/analysis/chart-pin-ui-rootcause-2026-08-30.md。

- [x] **#B1 全信号表+按年窗口增长两卡改 grid 并排 2 列**(commit c6a2370ce,版本 a501)— 原 flex+@media1080 断点偏大致中宽屏也变 1 列;改 grid `repeat(auto-fill,minmax(min(100%,600px),1fr))`,PC≥1212px 2 卡并排、窄屏 min(100%) 自动回 1 列;象限 3 列布局(:1548)未动零回归
- [x] **#B2 ETF走势pin弹窗4项UI修复**(commit 687f46a70,版本 a502)— ①dot 居中锚点(dot+txt 整体 translate 致 dot 偏左约27px,改 dot absolute translate(-50%,-50%)、txt 挂旁)②同日多 pin 竖向叠加(dot 共锚点、txt 竖排错开,弃 ei*14 横向错开)③正式/淘汰区切区统一区间基准(并集事件日期,弃每区独立重算窗口)④infobar 详情态去 max-height:64 滚动 + 字体统一;reviewer 内审 PASS
- [x] **#B3 卖点×N聚合标注+同卖日清仓明细**(commit b8b2e5f7a,版本 a502)— GHI 卖出=清仓全部仓位非卖1手(562870=8笔买同日全清 net -262.06,全库617组1卖日命中N买);pin 显示 `×N` + hover 列同卖日被清 buy 行 + 合计清仓本金;口径三源核对一致(仅展示层逐行有误导)
- [x] **#B4 全信号卡默认宽度统一700px+撑不满动态撑满**(commit 358c3dd54,版本 a503)— 全信号卡基准 600px→700px 与象限卡(:1548)对齐;`1fr` 让一行2卡自动撑满;窄屏(<700) min(100%) 回 1 列;同步更新注释口径

## 2026-08-31 会话收尾移入(v1.1.11 tag + P2 清理合并上线)

> 来源:内审 2 条 P2 观察 + codex 外审 rev-20260830-001 双 PASS 后发版 v1.1.11,随后处理 P2 观察并清理归档未跟踪产物;main-merge.sh 统一 build_min+bump(版本串 a517→a518)上线,curl 三查通过。tag v1.1.11 打在 main HEAD 80d1c81de。

- [x] **发版 v1.1.11 git tag**(tag@80d1c81de)— 内审 2 条 P2(非阻断)+ codex 外审 rev-20260830-001 均 PASS,用户「打吧」确认;git tag v1.1.11 打在 main HEAD 80d1c81de(区分 tag-object hash a4b980c4 与 commit hash)
- [x] **P2-1 注释口径修正**(app.js L4665-4667,_simBtCalcRowRealForce,commit 于 feat/p2-cleanup-20260830)— sim 默认档=etf_def(万3/最低5/印花万5)非 etf_main;与 lab 凯利 KELLY_FEE_PRESETS etf_main(免印花)语义不同勿机械同步;记录写回按 FEE_MAIN 不可直接透传。纯注释,min 哈希一致
- [x] **P2-2 幽灵排除项清理**(build_board_etf_map.py L1504,同 commit)— `_HOLDINGS_EXCLUDE` 移除 `bj_399`(幽灵:indicators.yaml/universe_rules.yaml/数据均无),现 {bj50,csi_930820,ftse100,kospi};§23.6 check_universe_alignment.py 无影响
- [x] **2 份调研文档归档(§23.5 四件套)**— docs/kelly/analysis/chart-pin-ui-rootcause-2026-08-30.md(pin UI 根因)+ ghi-sell-caliber-2026-08-30.md(GHI 卖光全仓口径),各含「## 复现」段;3 份 smoke 脚本(pin-zoom/pin-ui-fix-render/pin-xn-aggregate)入 docs/kelly/analysis/scripts/;README.md 索引补齐 2 报告。报告本体+脚本+复现段+commit 四件齐
- [x] **main-merge 合并上线**(feat/p2-cleanup-20260830→main 2bf773a8f)— 统一 build_min+bump 版本串 a517→a518,index.html ?v=20260831-a518 = sw.js CACHE_VERSION v6-20260831-a518;§24 同 commit bump+重建 min+哈希校验;§0 验 main 链含 commit + 线上 ss.fx8.store 服务 app.min.js?v=20260831-a518 HTTP 200 非空

## 2026-08-31 会话追加(CLAUDE.md 瘦身 + 首页 sim 弹窗两处改造)

> 来源:用户两连需求。①CLAUDE.md 超 40k 限制(42.1k)→ 用户拍板「小瘦一轮保核心」;②首页模拟回测·全历史真实历史弹窗:表格列宽/总宽度压缩 + ETF 代码列做和信号凯利卡片一样的点击弹走势交互。两批均 main-merge.sh 统一 build_min+bump(版本串 a518→a519)上线,§0 三查通过。

- [x] **CLAUDE.md 瘦身上线**(feat/claude-md-slim→main 57509a448)— 42,097→39,395 字符(-6.4%,达标 <39500),§5.3 核心保留(§23 十四条/§18 全锚点/§5 六条零丢失,只动行文冗余);纯文档改动跳过 bump,§24⑤ 校验 PASS
- [x] **首页 sim 弹窗表格压缩**(feat/sim-etf-display-fix 216d413a1)— sim-tbl min-width 1470→1270px + nowrap→normal + 逐列收窄(定宽合计 1236→1078px),14 列全保留、数据/逻辑不变(§5.3)
- [x] **sim 弹窗 ETF 代码点击走势交互**(同分支)— ETF 单元格复用凯利卡同款全局组件 _etfTrendLiteHTML/_etfTrendLiteBind/_etfTrendGeom(R2 etf/{code}-all.json→本地 fallback,§22 同源一致),bodyEl 事件委托跨分页生效,z-index 9999 不遮 sim 弹窗
- [x] **reviewer 条件通过 + blocker 修复**(2ed475703)— reviewer CONDITIONAL PASS 揪出 bodyEl.click listener 累积(stale 数据 + 多次弹窗,漏 _simPosHoverBound 式守卫),修复=加 _simEtfPinClickBound 守卫 flag + 每渲染刷新最新 rows/fIdx 到 bodyEl、handler 从 bodyEl 读(根治累积+过期双问题)
- [x] **main-merge 合并上线**(feat/sim-etf-display-fix→main 97b7bc979)— 统一 build_min+bump 版本串 a519,§24⑤ 校验 PASS;§0 验线上 app.min.js?v=20260831-a519 含 sim-etf-code-cell/simEtfPinClickBound + 备站 index 引用 a519 + ETF 数据源 R2 200

## 2026-08-31 会话追加 2(audit2 二审·保守版瘦身上线)

> 来源:audit2 researcher 对 CLAUDE.md「§23 权威原文 vs 指针」分层二次审计,用户拍板保守版(只指针化 §23.2/§23.3/§23.4)。implementer 三轮接力均漏 commit 且自报夸大,主控验 diff+grep 断链后代收尾 commit;reviewer 六项终审 PASS(低分项四连星笔误主控 amend 修正)后 main-merge 上线。

- [x] **audit2 二次审计**(researcher)— §23 十四条+共享核心大段逐条四维结论表(①全角色必读 ②skill 承载 ③历史教训强制 ④规范vs状态),基准核实 39395 字符(wc -m);结论:可指针化=§23.2/23.3/23.4(impl skill 有完整操作版,非事故级),谨慎档 §23.5/23.13/§5.1/§5.5/§23.12;历史教训类(§0.1/§0.2/§18/§5.4/§5.3)不许挪已守约束
- [x] **保守版落地**(feat/claude-md-audit2-slim 92e364b0f)— §23.2/§23.3/§23.4 压成触发词+核心一句话+指向 impl skill §5/§6/§8;impl skill §8 关联规范源去 §23.5 误标;tester skill §23.2② 子条目引用同步为指向 impl §5②(防指针化断链);39395→39030 字符(-365);承载核实=impl §5/§6/§8 完整操作版亲读确认
- [x] **reviewer 终审 PASS(六项)**— 指针化质量(§23.5 起零差异无夹带)/承载复核/断链复核(活跃层子条目引用零命中,worktree 历史快照不算)/§5.3 核心保留+可逆(impl skill 仅 1 行 diff)/历史教训未动/字符数精确命中;「。****(」四连星格式笔误主控 amend 修正(92e364b0f 定稿)
- [x] **main-merge 上线**(→main 92e364b0f)— 纯规范文档未触碰前端 8 源,脚本自动跳过 bump;§24⑤ 机制 A/B PASS(check_version_progress 一条 app.js/style.css 告警经 git diff 779310de7..92e364b0f 证实为基线误报,merge 范围内前端零变化);§0:main 链含 commit ✓,无前端/数据展示项

## 2026-08-31 会话追加 3(sim pin 闭环 + zcode 角色 + codex ref 链审计根治)

> 来源:用户三连拍板。①sim pin 对齐"这个做完吧";②建立 zcode 代班秘书角色;③codex ref 链查证("确认 ref 报告问题是否要修复+为什么我没清理")→ 根因=回传链机制断点非清理疏忽,四项拍板"听你的建议"全做。**A/B 两分支已过审并于 16:1x 先后 merge 上 main**(feat/watcher-inbox-fix→ab6b9ec2a;feat/codex-ref-cleanup→本次 merge,done-list 冲突按两边互补保留解决:全轮概览+A 单详细版并存)。
>
> **外审 rev 文档建议①(闭环对齐)核验(2026-08-31)**:外审报告称「TASKS.md 会话追加3 段落 7 条闭环声明、done-list 仅记 4 条缺配 3 条」系基于旧快照;当前 done-list 本块实含 9 条 `[x]`(L212 sim/L213 zcode/L214 ref审计/L215 A/L216 B/L220 rev-27/L221 rev-30/L222 rev-31/L223 v1.1.12 tag),已全覆盖 TASKS.md 顶部活跃状态段全部闭环声明,**无缺配**。唯一错位=TASKS.md 顶部状态段 L15 ⑤「打 tag 待做」为旧态,已同步为「v1.1.12 完成」(对齐 done-list L223)。纯文档登记对齐,未改任何 commit/功能事实。

- [x] **sim-etf-pin-align 全链闭环上线**(feat/sim-etf-pin-align→main **2e5e32746**,统一 bump a519→a520)— STEP3 收尾 5c400e6d1(_fIdx 缺失崩 pop 修复+×N 聚合/持仓中分支/srcKey 返回高亮)→reviewer CONDITIONAL PASS 抓 P1(区切换 kind 级过滤割裂强平配对)+P2(缺价行 pop 假盈亏 -10000)→fixup 0e96c31b0(行级过滤对齐 lab.js:12219+缺价短路+×N 剔缺价行)→复核 PASS→merge;§0 三域名过(⚠️ 验 min 用根路径 /app.min.js);口径边界(缺价强平行 sim 留正式区 vs lab 进 eliminated)B 落档已知差异 app.js:4501,实测缺价率 0.00%
- [x] **zcode 代班秘书角色建立**(feat/zcode-standin-charter→main **81d4ed411**)— 主控审核 4 缺口(在跑 agent 接管协议/CronDelete 边界/memory 写回收紧/验收入口)→zcode 全补齐+自加四层兜底/派单 checklist;复核通过;**开工门槛=用户确认+派活,当前待派**
- [x] **codex ref 链审计根治**(researcher 实锤+四项执行)— 11 ref 全处置(8 PASS+2 FAIL+1 BLOCKED 全闭环,修复均已在 main);根因=watcher stale 机检 mtime<job_started 时序恒假 100% 误拦+进程 5 天未重启跑 bug 版(8-28 磁盘重写机检丢失,考古 claude-actions 7 回执佐证);协议 :85 清理责任=Claude 主控(7 天保留),非 Claude 疏忽
- [x] **A codex-ref-cleanup**(feat/codex-ref-cleanup→ca745c2ab,验收过,已 merge main 本次)— 协议 :58 补句(req ref status 只读/消费态以 resp ref 为准)+done-list 补 8-27-002 闭环条目+refs 终态 0 req+4 resp consumed+43 个 .failed 镜像落档(claude-actions/FAILED-SIGNALS-ARCHIVE-20260831.md)后删+2.79GB DB 副本释放+8-30-002 收尾(复算报告 docs/kelly/analysis/kelly-card-vs-popup-p12-p13-recompute-2026-08-31.md:P1-2 共享核 48/48 逐位一致;P1-3 剩余差异全为已声明语义差非 bug;P1-1 浏览器实测随 sim 收尾覆盖)
- [x] **B watcher-inbox-fix**(feat/watcher-inbox-fix→05e1f6562+41e4a27eb,reviewer PASS,已 merge main **ab6b9ec2a**)— report_is_fresh 判定修复(mtime≥signaled_at−60s 容差放行)+touch 迁到写信号之后(不变量恒成立)+存量雷最小兼容(8-28 磁盘版硬依赖 tomllib,生产 py3.9.6,重启必崩→`from __future__`+tomllib 可选 import);watcher 重启新 PID 38806 心跳正常,回传闭环恢复;遗留 2 项(prompt 钉定/claude 消费语义)挂起待 rev-20260831-002 实跑表现拍板

以下两条为 A 单(codex-ref-cleanup)落地时补的详细闭环登记,与上面 A 条目概览互补(merge 冲突按两边互补保留解决):

- [x] **codex外审 rev-20260827-002 FAIL 闭环确认** — 两条 P1(F-01 经理名单粘连/F-02 闸门收紧迁移重采)修复 commit 12364dcc2+072ba10d4 均已入 origin/main(git merge-base --is-ancestor 双验 YES);claude-actions 回执当时 blocked(消费 worktree=main 0fe169f5b 不含被审代码 head=87192decf,grep appoint_map 零命中,按协议不静默动手转交主控)后来主仓派 implementer 修复;F-01 经理名分词残差(老页面无链接单元格时仍空格 split,两字姓名误切风险)已在 app/collector/public_fund.py:1944-1953 代码注释标注(F-01 fix 2026-08-28 + fallback 风险说明)
- [x] **codex外审 rev-20260830-002 P1-2/P1-3 数据复算收尾** — P1-3 跑通 verify_card_vs_popup.mjs(harness 补 real 链符号提取+accum_nav_map 注入,对比逻辑零改动)+ 修复后口径回算:非 GIH 42 行 total+holding 全一致、G/I total 647=647 一致,H 的 NEQ 与 G/I holding 差=卡面套 GIH sim 弹窗不套的设计语义(方案 B 已声明)非谓词 bug;P1-2 共享核双份实现(common _gihRealizeRealForce vs lab _kellyAihlineRealizeReal)99 用例逐字段对比,nav 命中主路径 48/48 逐位一致,唯一行为差异=null 防御(lab 抛错 vs common 防御,生产输入域不含 null);报告 docs/kelly/analysis/kelly-card-vs-popup-p12-p13-recompute-2026-08-31.md(含复现段)+README 索引已更新;P1-1 浏览器实测随 sim 分支收尾不在本单
- [x] **外审 rev-20260831-002 发出→回传→消化闭环**(本会话收尾链③④)— 中途 OpenRouter 402 额度 3 连败 gave up(codex 侧用户修正后重发成功);verdict=**PASS 零真问题**,3 issue 逐条核实定性:P2 移动端横滚=有效观察项(差真机实测)/P3 ×N 聚合=复述已落档已知设计差异(app.js:4549)/P3 docstring=可选微优化挂起;resp ref consumed 已建;新 watcher 通路实战成功,prompt 钉定/claude 消费语义两项按用户拍板维持不恢复;巡检 cron 兜底闭环(报告到即抓,CronDelete 收尾)
- [x] **v1.1.12 发版打 tag**(收尾链⑤,用户确认版本号)— README §23.1 随检(c9770354b,模拟回测弹窗段追加 ETF 点击走势描述)→tag **v1.1.12 @ c9770354b** push 远端,版本链 v1.0.0~v1.1.12 十四连齐;不动 AI 推荐/过滤核心,**测试基准仍=v1.1.7**,anchor memory 版本链补登记 v1.1.8~v1.1.12;TASKS 收尾落档 9916a37e1

## 2026-08-31 会话追加 4(tab 懒加载预取上线 + 外审 3 条文档建议 + 429 撞墙经验)

> 来源:性能终审后用户拍板「只做第一件优化(tab 预取)」+ 外审 rev 3 条文档建议用户拍板全做 + 商汤 Sensenova 429 撞墙反复(implementer 两次死限流)。

- [x] **tab 懒加载预取上线**(feat/tab-prefetch→main **a286d669d**,统一 bump a520→a521)— 性能终审(站点加载速度 audit,报告 docs/perf/site-loading-speed-audit-20260831.md)后用户拍板只做第一件:进 ETF 评分 tab(fund 分支)时 fire-and-forget 预取 `_ensureHoldLoaded()`(hold JSON ~783KB br,唯一懒加载点),切"持有"chip 秒显。implementer 两次被 429 死(死在 commit 前),续跑收尾(feat a1f4dbf17 源+5f23fd3a1 min)→reviewer PASS(独立重跑 build_min 与已提交 min 逐字节一致,§24 断链风险解除)→merge;§0:线上 `?v=20260831-a521` 生效,线上 min 确认含 `ensureHoldLoaded(),await renderEtfScore(n)` 预取调用。纯新增不改任何默认行为(§23.7)
- [x] **外审 rev 3 条文档建议①②③上线**(feat/extreview-docs-3items→main **6c9f438c2**,纯文档零代码)— 用户拍板全做:①闭环对齐(核实外审"7vs4"系旧快照,现状 done-list 9 条 [x] 全覆盖无缺配,唯一修 TASKS.md 顶部 L15 ⑤「打 tag 待做」→「v1.1.12 完成」+done-list 补对齐说明);②协议概念分离(codex-collab-protocol.md L58 拆 git 层 ref 不可变 vs 协议层 status 只读两句,语义零漂移);③PASS 来源标注(TASKS.md 顶部 PASS 补 rev-20260831-002)。reviewer PASS(②协议语义逐字确认未改坏+tag 远端实存交叉印证)→merge 跳过 bump(未触前端 8 源)
- [x] **商汤 Sensenova deepseek-v4-flash 429 撞墙经验**(memory `sensenova-rpm-rate-limit` 已建档)— 现象:同一轮 implementer 连续两次 429(「inference tpm exhausted」)死在即将 commit 前,客户端退避间隔写死 4 秒封顶调不了;根因=商汤对 deepseek-v4-flash 按 RPM(每分钟请求数)限流,非 TPM 真满;缓解=`CLAUDE_CODE_MAX_RETRIES`(默认 2-3,用户原设 10,主控误调 6 被用户纠正为 **16**);治本=thinking_proxy.py 加 429 退避(已搁置,待启用 deepseek 官方 API 时做)。教训:改配置前先核对现值,别把用户调过的值当默认覆盖

## 2026-09-01 会话追加 1(ZCode 代班秘书首单:凯利弹窗淘汰原因列)

> 来源:用户点名需求(交易模式弹窗淘汰区缺原因列,无法判淘汰对错/不便溯源)+ ZCode 代班全链执行(Claude 侧并行做其他 review,未参与本单)。

- [x] **交易弹窗淘汰区加「淘汰原因」列 + GIH 满仓不买单静默消失缺口补齐**(feat/kelly-elim-reason→main **67481e89b**,feat **8b741acb5**,统一 bump a521→a522)— 三种原因(AI降亏/AI仓位/AI长线·满仓不买)第14列+tooltip 对齐既有公示(§23.13);动态在场标签;GIH 开启时通过降亏+仓位过滤但未被仿真保留的单原先静默消失(不进主表不进淘汰区)→现入淘汰区对照;排序点击 !data-key 守卫(防 sort.key 置 undefined);CSS 原因列豁免删除线(同 #25「淘汰文字看不清」教训)。过程:ZCode 子agent 通道 6 连死(额度/并发)→调研/实施降级主控亲做,reviewer 死后 **SendMessage resume 带上下文复活**→CONDITIONAL PASS(无阻断 finding;9 验证点+合成4场景测试独立验证 ALL PASS);main-merge 机制 A/B PASS;§0 三查过(线上 lab.min.js?v=20260901-a522 含「淘汰原因」串)。reviewer 2 条低危观察项(G/I 丢弃标签语义简化·判 intended/ETF pin 弹窗新增 elim 事件·意图内)如实告知用户

## 2026-09-01 会话追加 2(凯利交易记录弹窗 UI 四改:列合并+可读性+黄底+淘汰原因筛选)

> 来源:用户点名三处 UI 改动(①买价卖价合并 ②淘汰灰字可读 ③持仓黄底降透明)+ 追加核心需求(④淘汰原因筛选看流失信号盈亏)。

- [x] **凯利交易记录弹窗 UI 四改**(feat/kelly-trade-popup-merge-column→main **055dc4d39**,统一 bump a524→a525)— ①买价+卖价合并一列上下布局(仿份额/每笔金额,priceCell 三态 nav缺价/持仓当前价+至今/正常卖价全保留,13列→12列 colspan 全改);②淘汰灰字:去整行 opacity:0.55 + text-4→text-3 提亮 + 保留删除线(贴合用户"有删除线置灰没那么重要,保持数据/样式可读",叠持仓黄底可读);③持仓黄底 alpha:light 0.10→0.05/hover 0.16→0.08,dark/redgold 0.14→0.05/hover 0.20→0.10;④淘汰原因筛选+该类盈亏统计:筛选区加「淘汰原因」下拉(AI降亏/AI仓位建议/AI长线·满仓不买动态标签+全部默认),淘汰区按 filter.elimReason 过滤,筛选后淘汰区标题渲染「该类信号盈亏:盈利X/亏损Y·胜率Z%·总盈亏W元」(仅选具体原因时显示),下拉 change 绑 events 重置淘汰区页码+重渲染。过程:implementer 首轮漏做④(报告没提,主控代码层核实发现)→续派补④→又 429 半途(统计算出未渲染+下拉未绑事件+未commit)→再续派补完收尾三处→主控逐条核(统计渲染 L12087+下拉绑定 L12141 全到位)→reviewer PASS 六项全过(列合并回归/数据口径零改动/§24② min+bump 完整/④逻辑含 nav_missing 边界/一致性/§21 公示),滤 1 条 p==0 打平归类极微 nitpick(真实成交几乎不精确为 0)→main-merge 机制 A/B PASS→§0 三域名全过(lab.min.js?v=20260901-a525 含「买价」+「该类信号盈亏」+「filter-elimreason」)。纯展示层零口径改动(§23.7 只增不改)

## 2026-09-01 会话追加 3(商汤代理400/429修复 + AI回测5.1+5.2 + B方案A/B harness + Karpathy review规则)

> 来源:今日三条开发线收口(代理稳定性 + AI方向锚回测 + 外部review质量增强)+ 会话落档整理(§23.12 4态流转)。

- [x] **商汤 Sensenova 代理 400/429 修复**(feat/ai-predict-backtest52 相关 commit → main **4e92cb3ef**)— ①修 400:`thinking.type=adaptive` + 嵌套 `thinking.budget_tokens>1024` 会 400(probe 验证 32768→400/1024→200),`_inject_thinking_budget` CLAMP 嵌套 budget 到 1024;②加 429 单 key 分层冷却(level0→30min/level≥1→1h/上限5×1h,quota型 vs tpm/rpm 型区分,4key 独立账户配额)。根因通过 TTP_DETECT_LOG 结构化请求日志定位(thinking_budget 添加契机)。
- [x] **代理日志大小上限守卫**(→main **3dd5b21c1**,feat/proxy-log-cap)— logmsg 超 20MB 留尾截断到 10MB(用户定:诊断env 留观察,文件别太大,最近错误日志够用)。launchctl bootout+bootstrap 误伤过(该服务是 scripts/ plist + load 模式,非 ~/Library/LaunchAgents/bootstrap),用文档的 `launchctl load` 恢复,新 PID 83100 加载新代码。
- [x] **AI 预测方向锚 5.1+5.2 回测**(→main **00fad6654**/**2b26ac690**)— 5.1 全历史 642 样本:lean 方向预测 hit=0.391,押方向 dir_win=0.5103 ≈ 随机;5.2 穷举子群(按T/role/strength/年/分半/阈值0.3-1.0/前向OOD):**全子群无一 |z|>=1.96 显著,阈值不翻天,无过拟合——方向锚自身无显著方向优势**。落档 docs/ai-predict/ai-predict-backtest-feasibility-20260831.md + 脚本 §23.5。**结论触发 B 方案:需严格验证方向锚注入帮不帮 AI**。
- [x] **B方案:方向锚「开锚vs关锚」7日线上A/B harness**(→main **fe9ae452f**,feat/ab-direction-anchor-7d-ab)— 因 5.1/5.2 证明锚自身无方向优势,但 8-28 开启注入依据=3样本离线前测(非严格A/B)。搭双通道:生产照旧(带锚20:40)+ 关锚参考通道(21:15 单prompt,同日期同数据唯一变量=注入),7个真实交易日对比方向命中率定去留。脚本 ab_direction_anchor.py(幂等/7日自动停/交易日判断/只读零侵入,不调 gen main)+ launchd com.trade.ab-direction-anchor 21:15。用户拍板:生产照旧+关锚参考通道(推荐)。报告 §23.5 四件套齐。
- [x] **落档外部系统先查社区教训 L47**(→main **e7f789c2a**)— 用户批评闭门造车(商汤400 闭门11组实验,规范里就有"不要闭门造车"),§5.1 强化触发词+§18①通用共享表加行+archive原文+memory。触发=排查跨厂商/网关/API参数未知行为第一动作上网查社区。
- [x] **Karpathy Skills review 规则(放宽版)采纳**(→main **33c9c90ee**,feat/karpathy-review-rules)— 用户让 codex 评估开源项目 andrej-karpathy-skills;codex 结论不直接用不蒸馏,提 2 条 per-finding 规则(trace/verifier)。主控校验 codex:①"无测试套件"过头(有针对性单测)②落地点偏窄应扩双 reviewer skill(§23.3)。用户拍板采纳**放宽版**(trace.user_request 可 N/A+reviewer_own 不压没主动发现;verifier 对回测/口径类可降级"口径依据")落 5 文件(protocol + .agents codex-reviewer + role-reviewer + 2个同内容副本)。评估落档 docs/codex-reviews/karpathy-skills-evaluation-20260901.md。2周试运行(9-01~9-15)+4指标验证再定正式版。

## 2026-09-01 会话追加 2(ZCode 代班第二单:淘汰原因 tooltip 中性化)

> 来源:ZCode 首单 reviewer 低危观察项①(G/I 丢弃路径与「满仓不买」tooltip 语义简化)+ 用户拍板做。

- [x] **淘汰原因 tooltip 中性化**(feat/kelly-elim-tooltip-fix→main **9923b1be9**,feat **412886afb**,统一 bump a523→a527)— 「自然卖出腾位后再买」仅准确描述 H(手段A 满仓不买,当日超容整批跳过+自然腾位);G/I(P/FIFO)丢弃路径=强平腾位后仍超容整批跳过(lab.js 8006-8014),同标签 tooltip 语义简化。新文案「当日买入被仓位判定跳过(仓位已满或强平腾位后仍超容)」两路径均准;三分类标签(用户拍板)不动。ZCode 自审 PASS(1 行 diff+两种路径锚点一致+§24 机制C 合规);§0 三查过(线上 lab.min.js?v=20260901-a527 含新文案)。顺带:#25 销账核实=条目早已完成移入 done-list(2026-08-17),main-merge 软提醒为 commit 引用编号误报,无需动作

## 2026-09-01 会话追加 4(两条遗留 TASKS 待办对账销账:UI修复批双merge链 + kelly-lab P1)

> 来源:主控清理 worktree 时发现两条 TASKS 遗留项可能状态漂移(TASKS 挂着但实物可能已完成),用户拍板「先核对 overfit 再销账」。派 reviewer 用 git 实物证据对账(memory pending-index-drift-verify-before-recommend 教训),主控补核 overfit 数据/上线,确认后销账+清理残留。

- [x] **UI 修复批(P0 卡死)reviewer 终审 + 双 merge 收尾链销账**— reviewer 实物核查结论:代码 100% 完成且双 merge 全落地。P0 卡死根修 `7ea4f8272`(跃迁守卫+单向阀)+批本体 merge `1cd137e70`/`839b5d283` 均在 main;双 merge 链②T3-2 rebase/适配完成(T3-2 merge `673ebe2ef`+适配 `44d383620`/`8811295d6` 在 main);common.js 组件 `_tdsFadeModeSelectHTML`+`_TDS_FADE_TTL_MS` 常量+window 导出全在 main,所谓"~L2111/L2672/style.css ~6993 冲突待处理"不存在,已由 T3-2 收尾覆盖;reviewer 终审已实质完成(44d383620 内附"终审两单点修复")。③overfit.json 正式重跑上线**主控补核 PASS**:`static-site/data/overfit_monitor.json` generated_at 2026-08-31 21:40(末交易日定时跑,晚于 8-23/24 merge),version v2,含 n2NorthOutConcept(708)/janMidRating(128) 新键=证明重跑用了当前 main 代码;线上 ss.fx8.store `/data/overfit_monitor.json` 已到同版数据(§0 任一域名到新版即上线 OK),deploy 链已挂 check_overfit_split_parity.py + check_overfit_recent_parity.mjs 校验。④T4 公示+README+版本号=常规发版收尾(README 侧无独立 T4 标记 commit,归常规发版)。⑤T5 用户手动校验=用户侧动作,非阻塞销账。→ TASKS.md L41/L42 销账
- [x] **kelly-lab P1 首屏懒加载销账**— 分片+骨架屏+localStorage 缓存三件套已实现并合入 main(`543f43bf6`),后续迭代(6cb26ddc6 缓存短路/7d40055b3 2026数据补回/94984d39e 单片失败重试)全上线;TASKS 引用的 `ac359715ca0` 为无效 commit(git cat-file fatal,引用过期/笔误);`feat/lab-lazy-small-mid-step`(dc1168c37)也已并入 main 且无未合 commit。→ TASKS.md L22 该 P1 项销账
- [x] **残留 worktree/分支清理**— 11 个 agent-inbox-rev-* worktree+分支全清(20260827-001~008/20260830-001/002/20260831-001,均干净无脏);`feat/kelly-lab-lazy-load` 分支删除(已并 main 无未合 commit);`lab-lazy-small-mid-step` worktree 待处理(见下)。TASKS.md L20 遗留清单已同步(仅剩 zcode 等用户派活)

## 2026-09-01 会话追加 5(开源评估跨角色根治 + Karpathy 复核补记)

> 来源:用户批评 ponytail 评估"不值得/只有review"不负责,并怀疑 Karpathy 那次二次评估也错了。核实确认两次评估(ponytail+Karpathy)同犯"只看 review 角色"系统性错误。用户拍板按建议顺序推进:1根治落档 → 2Karpathy复核 → 3ponytail蒸馏。

- [x] **步骤1 根治落档**(→main **37fe7855a**,feat/eval-cross-role-rootfix)— CLAUDE.md §5.1 补强「开源/方法论评估必须跨角色穷举」:评估任何项目必须对 implementer/reviewer/tester/researcher 逐个问可蒸馏增量,穷举完才许下结论,只覆盖一个角色=评估不完整=违规(对应§23.3)。配套 memory open-source-eval-cross-role-sweep(触发词=评估任何开源/方法论)。§24⑤ A/B PASS,纯规范文档零前端
- [x] **步骤2 Karpathy 复核补记**(→main **2905951d2**,feat/karpathy-cross-role-recheck)— 原 Karpathy 评估只落 review 2条(trace/verifier),漏 implementer(Simplicity/Think Before Coding)/tester(Goal-Driven验证闭环)/researcher(量化)。补记澄清:Karpathy 的 Simplicity/Surgical 与 ponytail 7级阶梯重叠可合并,蒸馏以 ponytail 为主,Karpathy 维持原2条 review 规则,评估方法补记防同类窄化
- [x] **步骤3 ponytail 蒸馏落地**(2026-09-01 完成,见下方「会话追加 6」段 feat/ponytail-distill):按 4 角色落地(implementer 优先:7级阶梯+根因修复+少写抽象;reviewer:删除清单+量化;tester:懒但安全;researcher:量化+别过度建模),接现有 trace/verifier 框架,走 §23.8 双向标注+§23.5 落档

## 2026-09-01 会话追加 6(ponytail 蒸馏落地完成)

- [x] **步骤3 ponytail 蒸馏落地(2026-09-01 完成,feat/ponytail-distill)** — 用户拍板蒸馏 ponytail(~118k star)而非装 plugin,按 4 角色纯新增落地(§23.7 只增不改):
  - ① **implementer** `.claude/skills/role-implementer/SKILL.md` 新增 §6.5「写码前 7 级阶梯+根因修复+少写抽象」(接 §6 后 §7 前):7 级阶梯(需要吗/已有复用/stdlib/原生/已装依赖/一行/才写最小)+根因修复(共享函数一个守卫<每个 caller 一个守卫,接 §23.2)+少写抽象(删除优先于添加,接 L11)
  - ② **reviewer** `.claude/skills/role-reviewer/SKILL.md` 新增 §10.6「代码类 finding 附删除清单+量化」:每代码类 finding 加 over_engineering_findings(action=delete|simplify + saves_lines + rationale 指向阶梯层),只对代码类强制(口径类走 §23.13);`.agents/codex-reviewer/SKILL.md` 加同内容(§22 三处一致)
  - ③ **tester** `.claude/skills/role-tester/SKILL.md` 新增 §5.4「懒但安全+最小充分测试边界」:安全底线(输入/安全/数据丢失兜底,接 E16+§22)不省,避免冗余/过度测试;最小充分测试=主路径+关键边界,不每行全覆盖
  - ④ **researcher** `.claude/skills/role-researcher/SKILL.md` 新增 §3.2「量化影响+别过度建模」:与 §5.1 穷举互补(该穷举的穷举/无谓维度不堆),建模前四问+结论可量化验证
  - **落档**:docs/codex-reviews/ponytail-distill-20260901.md + codex-reviews README 索引已更新;每个 skill 改动处标注 §23.8 关联规范源;不改 CLAUDE.md 正文

### 2026-09-01 会话追加 6:分支处置 codex 外审结论(rev-20260901-001/002/003)
- **请求状态**:3 个请求报告均已生成(/tmp/codex-reports/rev-20260901-001/002/003.json),verdict/recommendation/findings 齐全;inbox 标记为 .failed(retry_count=2,watcher 投递信号问题,报告本体完整可用)。
- **001 feat/etf-weight-leader-b123-backtest**:verdict=MERGE_FIRST。4 独有 commit 中 3 个已被 main 吸收,仅 `ff06d1ef4`(首页 AI 降亏过滤 ON 分栏计数+准确率排除降亏命中信号,改 static-site/app.js +21/-18)未在 main。建议:先 cherry-pick ff06d1ef4 验证无冲突→再删分支。风险:与 main 后续降亏 commit 可能冲突。
- **002 codex/ghi-sim-modal-handoff-20260829**:verdict=SAFE_TO_DELETE。交接包 1 commit/12 文件/1670 行已被 main 覆盖(I=15万→16万 定稿在 kelly-ghi-avsp-method-sweep.md),codex-handoff/ 目录无引用,删除无副作用。
- **003 fix/platform-healthcheck-mjs**:verdict=MERGE_FIRST。修复 2 个真实 bug(顶层 await ReferenceError + parity 命令缺 RECENT_JSON 环境变量),main 上同类 bug 仍存在,3 行 diff 无副作用。建议合并进 main 收口。
- **处置状态**:全部为「报告已出待用户拍板」,未自动执行 merge/删除(001 涉前端 app.js §24 需 bump,003 涉 merge main,均待用户确认)。
