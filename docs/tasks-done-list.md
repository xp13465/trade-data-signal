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

- [x] **AI 预测根因调研 + TradingAgents-CN 底层深挖(用户质疑「只肤浅套用多agent辩论?」)** — commit(调研为文档非代码)。结论:TA 底层=langgraph 多智能体辩论编排(setup.py)+各 analyst prompt 内领域软因子+唯一硬权重=舆情三源加权(chinese_finance_utils.py 331行);我们诚实承认只复用了多agent辩论编排,但方向锚信号胜率(转空+均线多头84.2%)为自研8年数据挖掘,超越之;README 措辞已修正(致敬TA保留)。报告 docs/ai-predict/ai-predict-direction-market-winning-signals-20260820.md
- [x] **方向发展锚(第一步)+ 离线回放A/B** — commit 5bbc8fbe1(方向锚语义教学+config默认关+replay脚本)/30ed2c94c(merge main)。A/B结果:8/17修正(down→up)、8/18保持对+L3压制转多设计点通过、8/14未修正(80%+逆势锚被当参考,迭代点晋升"倾向性结论")。迭代跟踪总纲 docs/ai-predict-self-upgrade-roadmap.md
- [x] **反思=因子归因回灌(TA Reflector 内核,提前落地后续轮次3)** — commit 9a47bae97。失败归因到具体误导因子(_attribut_factor,复用方向锚)+「待规避因子」约束段回灌(build_attribut_inject);cfg 默认关reflection_factor_attribution_enabled=false=线上逐字不变。报告 docs/ai-predict/ai-predict-reflection-factor-attribution-20260820.md
- [x] **影子模式 7 真实交易日 A/B 验证(用户拍板数据决定开/不开/改)** — commit 52813c924。方向锚/归因全默认关但旁路算+落盘(brief_shadow.json)+聚算(aggregate_shadow.py);shadow_mode_enabled=true只控旁路不注入线上。契约 docs/ai-predict/ai-predict-shadow-validate-20260820.md + roadmap 第四步实施记录
- [x] **影子模式项目下 md 追踪总表(用户要求项目下 md 文件记录可实时看,非黑盒)** — commit a63a13e87 + 77ffd7041(渲染 try 防阻断)。md=data/brief_shadow.json 唯一事实源全量渲染,幂等双向维护,进 main 可从 commit 检索。追踪表 docs/ai-predict-shadow-track.md(自动生成勿手改)
- [x] **四档色带单色+无hover bug 修复(中证1000/创业板指/科创50)** — commit bb20755be + 836c1f95c(merge main)。根治:per-date匹配tier+silent:false+弹窗补tiers;本地与线上 app.min.js md5 均=d3e0a537

## 2026-08-21 回测结论落档(95)

- [x] **#95 ETF→权重龙头个股回测结论** — 无实际价值,不推荐,维持 v1.1.3。结论:同 ¥10,000/信号基准,A(ETF)全面优于 B1/B2(TOP1个股),B3(TOP1-3并集)与A持平但3倍操作量且半凯利低4pp;ETF免印花税+单标的决策+无停牌退市风险。详见 docs/kelly/backtest-ai/etf-weight-leader/etf-weight-leader-conclusion.md

## 2026-08-22 todolist 治理移入(8 条关闭 + #82 整条关闭,researcher 盘查+用户拍板)

> 来源:docs/todolist-cleanup-20260822.md 全量盘查报告(researcher 三重交叉核实:文档自述+commit 在 main+产物/前端/线上 API 实测),用户 2026-08-22 逐条拍板。§23.12 4 态流转:完成→完成文件;从 pending-features-index.md 移除,每条带 commit 实锤可反查。

- [x] **#15+#91 凯利回测「次日开盘」口径(切默认闭环)** — 371434fdc「回测默认买入口径切次日开盘(v1.1.4)」在 main,git tag v1.1.4 已打;lab.js L9846 前端已公示「v1.1.4 起默认=信号次日开盘」;907b76777 README 已补;「次日分批挂单SOP」按钮②早已上线(lab.js L9736)
- [x] **#29 R2 审计 P1:track_score 跨文件不一致** — 6e0f70eb6「增量门控纳入 board_etf_map + 全量一致性校验(#29)」在 main,check_data_integrity.py L44 全量两两对比挂 deploy 链常态化;基线漂移子问题已随 #26 废弃时定性「漂移极小」
- [x] **#42 上下文优化 3 项(OPT-1/2/3)** — OPT-3 Compact Instructions 已进 CLAUDE.md(grep 命中);OPT-2 MEMORY 瘦身 2026-08-12 已做一轮(§5.3 记录 20.6KB→9.6KB,若要重做另开新项);OPT-1 被 E17 hooks 0 token 抄送(2d1b9206e)+token-cache-stats 每日收尾(92c303963)+§5.5 行为层吸收
- [x] **#75 upload_r2.py REPO 读路径强校验(方案1)** — a956cbe5a「REPO 缺省分级闸 #75,防手动裸跑旧库盖线上」在 main:upload_r2.py L36-54 显式态放行/缺省拦截,reviewer 当年「方案1 无兜底须再上」诉求已实现
- [x] **#79 场外基金方案C 全量化(step1-8)** — 28314d030「feat(#79 方案C) D1 服务端分页+详情弹窗 5 区块」在 main;step1 export_fund_score.py 九字段/step2 weekly top_n=None/step3 wrangler.jsonc FUND_SCORE_DB binding+sync 脚本/step4 worker/fund_score.js/step5 app.js /api/fund_score 分页 fetch/step6 openFundScoreDetailModal/step7 统一 bump(1985b733f)/step8 weekly 挂 sync 全落地;线上 curl /api/fund_score 返回 401 登录特权鉴权正常(生产实证)
- [x] **#80-P2-15 offshore_fund dead weight 停链** — 4289d50a7「chore(P2-15): 停用 offshore_fund JSON 定时生成链(用户已确认)」在 main;P2-10 长期 code-splitting 与 P2-11 保留 pending #80(P2-11 feat/p2-11-dapan-lazy 分支预开,实施中)
- [x] **#82 留言箱完整方案剩余(整条关闭)** — 邮件通知已上线(main 436f6d6bf merge 链,生产端到端验证通过:KV nickname 实锤+站主 QQ 实收);管理端审核页 admin/feedback.html + 防滥用四层(worker/auth.js L731-796 频控/honeypot/内容约束/审核闸门)均在 main(4b384b473/f3f4cd838);留言墙经用户拍板砍除(定位私密信箱不上墙);原行内悬空 hash b53a312e7 随行移除清除(实际承载 eb288f443/4b384b473/f3f4cd838)
- [x] **#83 公募基金筛选器实战版(被 #79 覆盖)** — 前置阻塞解除实锤:export_fund_score.py L8-10 注释「#83 公募筛选器字段前置」,fund_company/manager/scale 等 9 字段已补;指标体系(sharpe/drawdown/stability/manager_score/star_rating)+筛选(type)/排序/搜索+详情弹窗均被 #79 实现;若未来要做「多条件区间组合筛选」增强,重新登记新项
- [x] **#22 凯利过滤层 walk-forward(方法论沉淀)** — #16(commit 299db6167)已建完整 walk-forward 方法论+kelly_walkforward.py(docs/kelly/analysis/kelly-walkforward-validate/),结论「推荐组合样本外有效,选段最优才过拟合」;本条诉求=未来调参用 walk-forward 防过拟合,方法论+脚本沉淀后独立挂待办无增量

## 2026-08-22 会话收尾移入(首页模拟回测弹窗全链 + P2-11 大盘懒渲染)

> 来源:周末清账批次,main-merge 统一入口合并,版本串链 a377→a385 全部 §0 线上验证(curl 主站+备站)。

- [x] **首页「模拟回测」弹窗上线+三轮迭代** — a377 上线(main 2dd0feaa1):5 操作块+13 列费后盈亏累积表,R2 signal_kelly_trades.json 全历史 27 万笔,过滤口径与首页 AI 建议 1:1;迭代①13 列定宽+hover 当日持仓格→信号关联 ETF 对应高亮(高亮数==持仓数)+四列红正绿负(a383,4602b3232);迭代②累积盈亏口径修正=累计盈亏÷(窗口峰值同时持仓笔数×¥10000),不再按每笔 1 万简单相加(E23 虚假杠杆口径根治),tooltip 三档互证含动态 1:1 公式(a385,0c876ebe5 merge 链);迭代③费率块 6 档快捷+5 参数计费+持仓中笔按最新价预估浮盈(b13d93592)
- [x] **P2-11 大盘 tab 懒渲染(#80/#92 同项)** — e01de0423(+评审加固)经 af0fc35d6 merge 上线,a384:IntersectionObserver 单例+_marketLazyProxy 懒代理(setOption 入队 init 后回放/getOption 回退/dispose 完整),首帧 canvas 23→5、init 长任务 59ms→0、像素 diff≈0 外观零变化(reviewer 8 项 PASS);加固项=getOption 未 init 返回缓存首帧配置(修切皮肤×懒加载交叉丢主题色时序 bug)+_disposeContainerCharts 错位约束注释;遗留:板块分化 subtab renderIndustryGrid spark 格同根因待拍板

## 2026-08-22 晚间收尾移入(#88 销号 + #10 ETF 长历史上线)

> 来源:#88 订阅推送差距调研(researcher,docs/subscribe-push-gap-research-20260822.md)+ #10 实施(reviewer 10 项 PASS)。

- [x] **#88 订阅推送(整条关闭销号)** — 调研定性=「已完成未销号」:原始设想(存储/订阅过滤推送/前端 UI/邮件通道)已于 2026-07-24 由 A12 全量实施上线(commit c703a584f 前端 + 3d29c05c4 后端,NOTES L2290 标✅),8-20 补登记时按旧快照误判"未实施"。现状:链路每天在跑(check_signals 日志「2 个有效订阅」),零发出=订阅标的(sh/sz 指数类)7-21 后无新信号属数据事实;TG 通道代码在但 bot_token 从未配置。零代码增量选项留用户拍板:①订阅加自选高活跃标的②填 token 启用 TG。报告 docs/subscribe-push-gap-research-20260822.md(含宽基零信号定性附录:行情原因+卖点双过滤设计行为,非 bug)
- [x] **#10 ETF 评分弹窗 30 天外长历史** — fa1ca6e3b 经 bc187f5ce merge 上线(a387):数据层 scripts/export_etf_hist.py(etf_daily 表→1532 只 per-ETF 全史前复权日K,87MB 走 R2 etf/ 前缀,4.2s 全量生成)+upload_r2 upload-etf-hist 分批 purge+update_all/deploy 定时链软挂载+check_etf_hist 挂 integrity 校验(C30);前端 openEtfScoreDetailModal period tab(默认 30 日零变化,点 3m~all 懒加载 r2/etf/{code}-all.json,内存缓存+竞态序号+缺数容错),SVG/echarts 双渲染路径兼容;Playwright 24 断言全过,R2 线上抽验 510300=3461 行逐位对 DB;reviewer 上报项 D(smoke-checklist 滞后)本批补 C30

## 2026-08-24 会话收尾移入(12 条,工具台账 completed 清出)

> 来源:has_track 口径事故闭环 + 全站判定窗改造 + 警示模块迭代等批次,版本串链 a409→a414 全部 §0 线上验证。§23.12 四态流转:完成→本文件。

- [x] **#30 首页信号区三件套** — 「仅显示可用信号」开关+近15→近30扩容+枯竭引导空态(893e57a9d)+首渲时序竞态修复(28a9c2eca),feat/home-available-only-toggle 合入上线
- [x] **#31 盘中日图颜色同步** — 单源色判定+盘中重染+收盘恢复,与实时分时红绿一致(8b12588c9)
- [x] **#32 P0:lab凯利区NEW14首载卡「计算中」死host闭包** — feat/fix-kelly-stale-host 合入(b27001e15 bump 链)
- [x] **#33 sim弹窗恢复「AI降亏过滤」独立总开关(否决off档)** — 下拉旁「过滤」checkbox=fadeOn 快速切换层(f601ac73e)
- [x] **#34 NEW14+1·15键可选档(X1 整剔none象限)** — feat/new15-tier-none 合入(a410 下拉批,184698b9e);后续 X1 扩围随 #44 has_track 批再演进
- [x] **#36 AI监控卡走势图渲染慢** — 根因调研+提速方案落地,feat/aimon-chart-speedup 合入(e58e37e9a)
- [x] **#37 全站缓存/体积/拆分类病灶清单扫描** — researcher 报告落档 c26b983c2(docs/kelly/analysis 同目录 perf 扫描报告,6新病灶+4批次修复划分);后续修复=#39/#40 排队
- [x] **#38 v1.1.5 基座对齐残留修复批(R1-R7+机检)** — feat/fade-keys-align-new14 合入(1eb88b5ad+e9c3f1b0b docs);配套 §22 补"代码内常量登记点也是一致性对象"(f4b123a7d)
- [x] **#41 全站「AI降亏模式」下拉统一固定宽200px×5处** — d64c67537,feat/fade-dropdown-width 合入
- [x] **#42 信号类型统计补卖/止损信号的数量对错正确率** — feat/warning-signal-stats 合入(a411,9a1f10d4a)
- [x] **#45 警示模块调整:撤波段持有行+三类chip悬浮说明** — feat/warn-chip-tweak 合入(a412,2fa7d795e)
- [x] **#44 has_track 归类修复+X1 扩围批** — 「有跟踪ETF」卡补装 null 档(卡 1,604→1,982 待盘后回测重跑生效)+X1 扩围剔 none+null(3387cfaad,a413 上线已验);特征快照数组化+R2 同步完成(generated_at 08-24 17:07,md5 双树一致,X1 spec=["none","null"]);数字口径勘误落档(0a85c3963);剩余尾巴(has_track 卡数据扩容)归 #47 盘后闭环
