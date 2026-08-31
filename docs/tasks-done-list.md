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
