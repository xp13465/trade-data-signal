# AI 降亏「单开关+模式下拉 7 种」重构前期盘点(T0 调研,2026-08-23)

> 任务:TASKS.md T0(四消费点现状+7套数据来源定案+3+1补漏对账+方法池对账)。只读调研,未改任何生产代码/数据产物。
> 测试基准声明:本报告为前端交互/数据流调研,不涉回测口径;引用回测数字一律标来源文件。权威数字卡=sim-combo-cheatsheet-20260823.md(mine24_compare.json,无门字段,g2 bug 不影响)。
> ⚠️ 进行中事项:g2 门修正+重跑由后台 agent 执行中(g2-gate-audit-20260823.md §④),A/B/C 的门字段数字以重跑后为准;本报告引用的键构成/净利锚点不受影响。

## 结论一句话

四消费点两条数据流(①③后端预计算、②④前端重放)都**沿现状延伸最小改造**;7 套模式中 **5 套(A/B/C/NEW14/NEW18)共 20 条成员规则在生产前后端零实现**(挖掘侧专属),是本次重构唯一硬新增;推荐**混合架构**:Python 侧抽共享规则模块供①③预计算 + JS 移植同一套谓词供②④重放,qth 阈值固化为快照配置单源。

---

## Q1 四消费点现状盘点

| # | 消费点 | 数据流 | 开关持久化 key | 切 7 模式要动哪里 |
|---|---|---|---|---|
| ① | 首页·近期技术分析参考点(`app.js _renderSignalGrid` L3638-3750) | **后端预计算**:overview 每信号注入 `ai_macro:{hit,filters}`(`app/queries.py _ai_macro_hit_filters` L764-851);前端 `_fadeOn`(L2273 `tds_home_fade` 默认开)× 固定 8 键白名单 `_AI_MACRO_FILTER_NAMES`(L2253-2262)求交 → `_isAiFadeHit`;bullAuxBackupStop 前端自判(L2286 `tds_home_bull_aux_backup_stop` 默认关 + L2289 `_ensureSigTierMap` 拉 R2 market_tier_history.json);top-K 补位 `_posCapKeptMap`(L3716-3750,`tds_poscap` 全站共享) | `tds_home_fade` / `tds_home_bull_aux_backup_stop` / `tds_poscap` 三 key 已独立 | queries.py 注入结构扩 per-mode;前端白名单改读所选模式 |
| ② | 首页·模拟回测弹窗(app.js L2513-3395) | **纯前端重放**:`_simDefaultFadeFilters()` L2551 写死 8 键;`_simPassesFade` L2613-2688 = lab 谓词手工复刻;`_simPassesBullStop` L2693 独立谓词;分片加载 recent.json+t{YYYY}.json+全量兜底(`_simTradesUrl`) | **无持久化**,每次打开重置默认(UI 态,a389 独立化产物) | 默认 filters 对象换模式下拉值;谓词需补挖掘规则分支 |
| ③ | 分析参考点·AI 监控卡(`app.js _appendOverfitCard` L1869-2050) | **后端预计算 bank**:overfit_monitor.py 输出 static-site/data/overfit_monitor.json(raw/filtered/by_k/filtered_by_k 四列 bank,L1295);前端 `_ovFade`(`tds_overfit_fade` 默认开)**只切 bank 不重算**(L1932 `_ovBank()`) | `tds_overfit_fade`(K档独立钮组,无单独持久化) | overfit_monitor.py 按 7 模式各出一列 bank;前端 bank 名切换 |
| ④ | 📊信号凯利回测 lab(lab.js) | **纯前端重放**:`_kellyDefaultFilters()` L7267-7313(8 键 true+bullAuxBackupStop:false);主谓词 `_kellyPassesFadeFilters` L7413;37 标签定义 `_kellyFadeFlagGroups` L8873-8966;渲染 L9008-9109(rec 高亮区+折叠区+组合行+K按钮) | **仅内存态** state.labSigKellyFilters(L8666 注释:每次重建不跨会话);真正写 localStorage 只有 `_kellyPersistFilters()`→`tds_kelly_filters`(AI宏成员+组合,L8822,供首页联动)+共享 `tds_poscap` | filters 对象覆写即切模式;新标签走既有四件套路(L8873 定义→渲染循环→onchange 绑定 L9321+→谓词分支 L7413) |

勾选联动机制(lab):标签 onchange → 写 `state.labSigKellyFilters.<key>` → `_kellyOnFilterChange()`(L8461)→ `_kellyRunRecompute` 重算费后统计+K档评级 → 重渲染 bar+象限图 → `_kellyPersistFilters()` 同步 tds_kelly_filters。新标签照抄此链路即可。

已知同源性缺口(顺手补漏候选,见 Q3):
- 谓词三份拷贝:lab.js `_kellyPassesFadeFilters` / app.js `_simPassesFade`(注释自认"完整复刻")/ sim_core.py `passes_fade`(挖掘权威版)。
- 后端两份硬编码:queries.py `_ai_macro_hit_filters` 与 overfit_monitor.py `ai_macro_hit_keys`(L128-156)各自维护 8 键列表。
- 首页白名单不含后端备选键:`_AI_MACRO_FILTER_NAMES` 无 legacyMa60Special 等 3 备选(L3645 注释明示),后端 filters 数组含备选键命中时前端 some() 判 false 静默不认(tooltip 名字却能经 `_AI_MACRO_BACKUP_NAMES` L3910 显示,行为不一致)。

## Q2 七套组合数据来源定案

### 推荐:混合架构(甲乙按消费点现有数据流各取所长),非二选一

**这不是妥协而是约束下的唯一解**:②④的交互本质=K档×时间范围×费率×自由勾选的任意组合实时重算,预计算无法覆盖组合空间(且 T1 明确要求 lab 补 20 新标签自由勾选);①是逐信号渲染性能敏感、③的 bank 本来就是离线 Python 产物,前端重算要拉全量 trades+特征不可接受。

| 层 | 做法 |
|---|---|
| 规则单源 | 抽 Python 共享模块(如 scripts/loss_rules.py):把 mine21 `build_rules`(L23-62)/mine22 `build_r2`(L24-34)的 20 条谓词从挖掘脚本提为生产级;qth 分位数阈值**固化为快照** config/loss_rule_thresholds.json(生成日全史分位写死,诚实标注"新数据不自动漂移,重算快照需发版") |
| ①③ 后端预计算 | queries.py ai_macro 扩 per-mode 输出;overfit_monitor.py 用共享模块算 7 列 bank(filtered_by_mode) |
| ②④ 前端重放 | JS 移植同一套谓词进 lab.js/app.js;特征数据下发裁剪版 JSON(12 特征×全史日频,约 1.2MB/gzip~300KB,放 static-site/data/+R2,②④懒加载);阈值快照同一份 |
| 一致性 | §22 三步同步特征 JSON+bank;对称校验(check_universe_alignment 同款思路):后端 mode 命中笔数 vs JS 重放抽样对比,FAIL 阻断 |
| 模式语义实现 | 8/9/A/B/C = on8/on9 基座(默认 8 键+cand1 强制开)+叠加子集 OR;NEW14/NEW2 = 整体替换 filters 对象("换基座",忽略用户当前勾选状态);用户再手动勾选=脱离模式,UI 提示「自定义」 |

### 七套键清单(权威=sim-combo-cheatsheet-20260823.md+mine24_compare.json+源码)

| 模式 | 键构成 | 口径标注 | 成员实现现状 |
|---|---|---|---|
| 8键(默认) | excludeAuxCross/excludeSpecialBear/n2NovSpecialIndustry/r7MayReinforced/greedy15/janMidRating/janMidSpecial/k2c5HkChase | 现役地基(sim_core.py DEFAULT_FILTERS L73-85 True 8 键) | 前后端全有 ✅ |
| 9键 | 8+bullAuxBackupStop(≡候选1,谓词=buy_aux/buy_backup×牛市·主升) | on8 叠加 | 前端有(a389 三处开关);queries 有;sim_core 无(挖掘侧按公示语义自补,§15.12.1)⚠️ |
| A on9(+46,007 vs 9键) | 9+T1/Q1/M1/V1/R1/R2a/R2b/R2g | **叠9键口径** | R2a≡k3ConceptBuy 有;其余 7 条零实现 ❌ |
| B on9(+36,469) | 9+T1/Q1/M1/R1/R2b/R2g | 叠9键;「双正王」名头因 g2 bug 作废(TASKS L48) | 6 条零实现(R2a/R2b/R2g 中 b/g 零实现)❌ |
| C on9(+34,011) | 9+N1/T1/D1/H1/M1/P1/R2b | 叠9键;cheatsheet 建议 on8 更优(+112,141>on9) | 7 条零实现 ❌ |
| NEW 14键(+122,648.33/mdd−4,178.01) | r10May6NonMay/greedy15/janMidSpecial/k2c5HkChase/k3ConceptBuy/declinePhaseSpecial/N1/T1/D1/Q1/H1/M1/P1/R2b | **重构换基座**(全池出发黑名单,不预设 8 默认在场) | 6 有+8 零实现(N1/T1/D1/Q1/H1/M1/P1/R2b)❌ |
| NEW2 18键(+120,564.54/mdd−4,083.63) | NEW14 去 declinePhaseSpecial + excludeSpecialBear/n2NovSpecialIndustry/greedy7/v4f/N2 | 重构换基座;NEW 族次优(入选差 31 笔) | 同上 ❌ |

挖掘规则两类依赖(Q4 详):
- **纯 trades 字段规则**(移植零障碍,前端字段已有):R2a(buy×concept)/R2b(special×global)/R2g(rating=low×07-09月×track_score<75)/W1(buy_backup×下降期)/A1(tier=牛市·主升)。
- **外部市场特征规则**(12 特征,mine21 build_rules FR 工厂按 buy_date 查值):north_d20/turn_pct/div_yield/qvix_pct/h_volchg/margin_chg20/div_pct/h_vol20/sent_a/vol_ratio_all/sent_hs300/adline_gap;阈值两种形态:qth 数据驱动分位数(生成日固化)与固定常数(V2 的 h_vol20>25.0)。特征源=data/mine10_features.json(25 特征 2.5MB,sentiment.db daily_metric/score_daily+hs300-all.json 衍生,无前视)。

## Q3 「3+1 处补漏」对账(最终所指请主控与用户确认)

全库唯一出处=TASKS.md L47,未展开定义;git log/docs/pending-index/tasks-done-list 均无对应登记(唯一另一处"3+1"="修 upload_r2 bug 3+1 处",无关)。

已排除的候选:v1.1.0 审计 4 个 P2(kelly-v110-k2c5-reviewer-online-audit.md)已在 commit 67173284a 收口(P2-1 queries 只判 mkt_hk 现核实 L818 已修/P2-2 高亮区真实 9 键 lab.js L9055 注释+recZoneHTML 现文案已体现/P2-3 注释修正/P2-4 部署完成);nine-rule-audit 4.1 K2C5 持久化已修(_kellyPersistMemberKeys 8 成员)、4.2 price_bin 降级=已知设计。

最可能指代(证据强度排序):
1. **「三处开关独立化」复用+1**(强):TASKS L12 刚做完 bullAuxBackupStop「开关三处独立化 a389(e471f7fc8):lab=state-only 回默认/sim 弹窗=UI 态每次打开默认关/首页=独立键」,与"顺手做"措辞直接呼应——7 模式下拉沿用同样的三处独立化纪律;"+1"或指第④消费点(AI 监控卡,现状仅 tds_overfit_fade 一个 key,bank 切换无模式态)。
2. **§23.6 三处公示+README**(中):purpose-notes.js+lab tooltip+app.js badge tooltip(3)+README(1)——但 T4 已单列公示任务,重复登记可能性低。
3. **三处谓词同源维护债**(客观存在,Q1 已列):lab/_sim/sim_core 三份拷贝+queries/overfit 两份硬编码——无论"3+1"原意为何,建议纳入本次补漏。

## Q4 方法池 57→最新全量对账

N=57 权威名单(round2 报告 §15.12.1 L588-593):
- 历史 37 = 前端 UI 37 标签(lab.js `_kellyFadeFlagGroups`,sed 统计 37 个字段)。注:报告文本名单(v4a~v4k 11 个/cybXxFilter/janMidLowSpecial)与代码有小出入,**以 sim_core.py DEFAULT_FILTERS 为准=36 键+excludeMonthDummy 占位,+bullAuxBackupStop(挖掘自补)=37,与前端 37 一致**。
- 新池 13:N1/T1/D1/Q1/H1/M1/D2/P1/V1/S1/R1/R2b/R2g(R2a≡k3ConceptBuy 已去重)
- 落池 7:N2/V2/S2/W1/A1/V3/AD1

**57 − 历史37 = 20 条待补新键**:新池 13 + 落池 7。这 20 条在 sim_core.py DEFAULT_FILTERS(36 键)、queries.py、signal_kelly_backtest.py(grep 无 DEFAULT_FILTERS/无挖掘键,该脚本只产 trades 不过滤)、lab.js/app.js 谓词中**全部零实现**——生产实现只在挖掘脚本内存里(mine21_bigtour.build_rules/mine22_joint.build_r2),数据断档即失传,这正是 T1 要落地的对象。

T1 实施前提核对:
- 20 键中 5 条纯 trades 字段(W1/A1/R2b/R2g/R2a≡已有)可直接落;
- 15 条依赖 12 特征 → 必须先落特征数据通道(裁剪 JSON 上 static-site/data/+R2)+ qth 快照,否则前端标签勾了也算不出;
- 新标签默认关:_kellyDefaultFilters 加 false 即可;勾选联动照抄 onchange→_kellyOnFilterChange 链路;37→57 后 UI 建议沿用三梯队分组(_kellyFadeFlagGroups 已有 calendar/combo/quality/market 分组机制,L8873)。

## 实施落点速查(T1/T3 派单用锚点)

| 动作 | 文件:锚点 |
|---|---|
| 模式下拉+filters 覆写 | lab.js `_kellyDefaultFilters` L7267 / 渲染 L9008;app.js sim 弹窗 `_simDefaultFadeFilters` L2551 / UI L2857-2882 |
| 20 新键谓词(JS) | lab.js `_kellyPassesFadeFilters` L7413 + app.js `_simPassesFade` L2613(两处同步加) |
| 特征查询基建(JS) | 仿 `_kellyTradeFeatureCache`/`_kellyMonthMask` L7376 缓存模式 |
| 后端 per-mode | queries.py `_ai_macro_hit_filters` L764-851;overfit_monitor.py L128-156+输出 L1295 |
| 阈值快照单源 | 新建 config/(Python 生成+JS 读同一份) |
| 公示三处+README | purpose-notes.js lab.sigkelly + lab.js tooltip + app.js badge tooltip(L3910 附近)+ README §23.1 |

## 复现

- 数据流盘点:`grep -n "_AI_MACRO_FILTER_NAMES\|tds_home_fade\|_posCapKeptMap" static-site/app.js | head`;`grep -n "_simDefaultFadeFilters\|_simPassesFade\|_simPassesBullStop" static-site/app.js | head`;`grep -n "_ovFade\|_ovBank" static-site/app.js | head`
- lab 结构:`grep -n "_kellyDefaultFilters\|_kellyPassesFadeFilters\|_kellyFadeFlagGroups\|_kellyOnFilterChange\|_kellyPersistMemberKeys" static-site/lab.js`
- 后端注入:`grep -n "_ai_macro_hit_filters" app/queries.py`;`grep -n "ai_macro_hit_keys\|filtered_by_k" scripts/overfit_monitor.py`
- 7 套键构成:`sed -n '73,105p' docs/kelly/analysis/scripts/sim_window_loss_mining_20260822/sim_core.py`(DEFAULT_FILTERS);`sed -n '23,62p' .../mine21_bigtour.py`(build_rules 20 条谓词工厂);`sed -n '24,34p' .../mine22_joint.py`(build_r2);A/B/C 子集=`grep -n "A_SUB\|B_SUB\|C_SUB" .../mine23_final_compare.py`
- 57 名单:`sed -n '588,593p' docs/kelly/analysis/sim-loss-mining-round2-20260822.md`
- 数字权威:docs/kelly/analysis/sim-combo-cheatsheet-20260823.md(来源 mine24_compare.json projects 字段)
- 数据截止:signal_kelly_trades.json generated_at 2026-08-23 05:09(cheatsheet 头注明)
- 关键口径:A/B/C=叠9键(on9),NEW14/NEW2=重构换基座;补位口径 K1
