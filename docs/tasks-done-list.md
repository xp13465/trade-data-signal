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

