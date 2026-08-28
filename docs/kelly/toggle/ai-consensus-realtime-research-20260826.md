# 「AI 信号认可度」盘中实时化路径·调研报告

- 日期: 2026-08-26 | 角色: researcher(只读调研,未改任何业务代码)
- 需求锚点(用户批评原文): 「认可度功能本意是避免我多次切换降亏模式来快速标记一个信号的x/y 现在的模式盘中等于是瞎子 我还是要靠手动操作?然后次日看到其实都已经滞后了。信息及时度规范来看 也是实时大于t+0 大于T+1。你现在的功能数据基本就落在了t+1了 虽然固化了 但是不能因为固化需求导致丢弃了实时这么高的质量标准」
- 上游报告: `ai-consensus-score-research-20260826.md`(a436 已上线版设计);本报告回答"盘中实时化怎么走"。
- 落档位置: 同上游报告目录(降亏 toggle 族)。

---

## 结论摘要(TL;DR)

1. **核心反转:「盘中瞎子」的前提与实证不符**——认可度依赖的数据链(overview.json 盘中每 10 分钟重导+ai_macro 注入+R2 ttl=0+前端自动重绘)**整条都是活的、盘中实时的**。用户白天看到"没有认可度"的唯一硬原因:**功能本体今天 21:07 才 merge 上线**(commit c19355f75/52a04b75a,版本串 a436),白天盘中跑的是旧版前端,整个 hoverpop 认可度行都不存在——不是"数据滞后到 T+1",是"UI 今天晚上才出生"。明日盘中起新信号将自动带认可度行上屏。
2. **盘中信号形态实证**:后端 intraday_snapshot 每交易日 28 轮(9:25~15:02,10 分钟节奏),每轮 `_recompute_signals()` 重算 signal_daily(今日 13:35 轮实测 70,977 条)+`_export_affected_json()` 重导 overview.json(ai_macro 注入循环对近 30 日全部信号含今日盘中新信号无条件执行)。**铁证:今日 14:48 staticdata 留档盘中版 overview 里,hstech buy_aux(当日盘中出现)已带 ai_macro.filters=['r2gLowRatingQ3']+track_score=67.9+_bt_in_universe=true。**
3. **Y 票盘中天然可算,零新增采集**:filters 的全部判定输入(mkt/tier/rating/track_score)盘中均已重算(score_daily/signal_stats/index_daily 反哺);前端 _consensusVotesOf 纯函数照算。14:48 盘中版实测 hstech Y=5/8(p8留 p9留 a9拦 b9拦 c9留 new14留 new15留 S06(a9)拦),与收盘定稿口径一致。
4. **S06 第 8 票盘中口径天然防前视自洽,无需改**:快照 date=D 行=D 日生效基座、decision_date=D-1(D-1 收盘决策,D-1 20:35 gen→check→R2 上线)。T 日盘中读 T 行=T-1 收盘产物=合法可得(实证 8-26 行 decision_date=8-25)。fail-open 仅作昨日任务失败兜底。
5. **真实缺口三个(按影响排序)**:①特征类键滞后(通病非盘中特有):kelly_loss_features.json 手动生成停在 8-21/24,8-22 后信号(连盘后定稿版)的 q1/d1/n1/t1/h1/m1 六键不拦,Y 系统性偏松——最大准确性杠杆;②bullAuxBackupStop 前端补判用 market_tier_history(R2,17:50 更新)停 T-1,今日 bull 判保守放行;③X 当日组盘中临时性(新信号可挤掉 top1),建议加「盘中临时·收盘定稿」标注而非隐藏。

---

## 1. 盘中信号形态盘点(调研问题 1)

| # | 形态 | 数据源 | 更新节奏 | 特征字段可得性 |
|---|---|---|---|---|
| ① | **买卖点信号(signal_daily)盘中重算** | `app/collector/intraday_snapshot.py` `_recompute_signals()` L1845-1881(collect_and_save L2326 每轮调用):signals.compute() 反哺当日实时 close → signals.store() 全量重建 signal_daily + signal_stats.compute() 重算评级 | 每交易日 28 轮(9:25/9:35…11:32/13:01…15:02+15:35/20:35 收尾,plist 注释全表) | 今日信号盘中即入表;今日 13:35 轮 log 实测「signals 重算: 70977 条」 |
| ② | **overview.json 盘中重导(含 ai_macro 注入)** | 同文件 `_export_affected_json()` L1909/L2331 → export.py export_overview;注入循环 queries.py L1382-1403 对 sigs(signal_daily 近 30 日,L1065-1080)无条件注入 ai_macro.filters | 每 10 分钟随轮重导;upload_r2 upload-intraday 传 R2(intraday_snapshot.sh §2.52 清单明列 overview.json) | **盘中新信号带完整 filters**(§2 实证);判定输入源 score_daily(_recompute_scores L2325)/signal_stats(L2326 后段)/index_daily 当日 close 反哺(L1101)同轮已更新 |
| ③ | **首页技术分析参考点卡** = ②同一数据(app.signals_today) | 前端 D 方案自动重绘链(§3) | 前端盘中自适应轮询 3min/15s(app.js L12136-12142) | 同② |
| ④ | 盘中信号邮件 | check_signals.sh --intraday(intraday_snapshot.sh §1.8,每轮查当日新信号发邮件,signal_notified.json 去重) | 每轮 | — |
| ⑤ | ⚠ 盘中预估角标 | app.js L4927 sig-intraday-warn「盘中预估·收盘后(17:50)重算定版」 | 随 cell 渲染 | — |
| ⑥ | ETF 汪汪队盘中预估 / 分时图 / intraday_snapshot 小结 | etf_national_team intraday-realtime / 前端分时轮询 | 10min/1min | 与认可度无关(无降亏语义) |

## 2. 核心反转的证据链(「T+1 滞后」证伪)

时序实测(2026-08-26 当日):

- 14:48 盘中 staticdata 留档(commit c47d487db,data/overview.json):今日(20260826)买入信号 1 条=hstech buy_aux,**ai_macro.filters=['r2gLowRatingQ3']**、_bt_in_universe=True、top1 track_score=67.9 —— 盘中注入实际生效。
- 同版精算 Y:hstech **Y=5/8**(p8留 p9留 a9拦 b9拦 c9留 new14留 new15留 S06(a9基座)拦);X=1(当日唯一入样买入)。与收盘定稿口径一致(定稿后 g.cn10y buy 未入样不进 X 人口,今日组不变)。
- R2 缓存策略:overview.json 在 upload_r2.py `_data_cache_ttl` L1305-1311 第一档 **ttl=0(no-store,edge 不查不写直回源)**——盘中更新即时可见,无 edge 滞留。
- 前端自动重绘链(D 方案,2026-07-29 起,两个月在役):
  - `_doOverviewRefresh` @app.js:11945 盘中自适应轮询拉 overview → L11979 dispatch `ts:overview-refreshed`;
  - listener @app.js:13019 → `_maybeRerenderSigCard` @app.js:5485(collected_at 变化即触发,state.tab==="overview")→ `_rerenderSigCardContent` @app.js:5434 增量替换 h3+汇总条+.signal-grid;
  - 认可度属性写入点=cellHtml @app.js:5091-5099(`_consensusMap.get(it)` 对所有 items 含今日盘中信号写 data-consensus)、hoverpop 拼行 @app.js:5978-5991——渲染层无任何 intraday 特殊分支跳过。
- 功能上线时点:`git log` 6de5b87f8(20:49 feat)→ c19355f75(21:07 merge)→ 52a04b75a(21:07 bump a436)。**白天盘中用户端无此功能属正常(未上线),非数据滞后。**

## 3. Y 票盘中可算性(调研问题 2)

- **结论:不需要给 ai_macro.filters 找"前端独立谓词替代"——filters 本身盘中就是新鲜的**,纯字段键(greedy15/janMid/k3/k2c5/excludeSpecialBear 四档/r7/r10 可判子集等)判定输入全部盘中就绪。
- bullAuxBackupStop(后端不判,前端补判)例外:_isBullStopHit 依赖 _ensureSigTierMap 拉 market_tier_history.json(R2 静态,export 链 17:50 更新)→ **T 日盘中 tier map 停 T-1** → 今日信号 bull 判 miss → 保守放行(少拦方向偏松,当前下降期零影响,牛市期有影响)。
  - 改进项(Phase A):queries.py L1398-1403 已注入 cyb_tier,同款加注 hs300 tier(~5 行;_ai_macro_build_market_state L554 直接查 index_daily 全量 close,盘中反哺后含当日=实时准确);前端 _isBullStopHit 优先读 it.ai_macro.tier、fallback R2 map(~10 行)。
- **诚实标注缺口(既有口径非本功能引入,影响所有展示位含盘后定稿版)**:kelly_loss_features.json 手动生成(mtime 8-24 17:07,grep 全 scripts/*.sh 零调用方、无 launchd),特征覆盖 north_d20/turn_pct/div_yield/qvix_pct 停 **20260821**、h_volchg 停 **20260824** → 8-22 之后信号的 q1QvixLowPct/d1LowDivYield/n1NorthOutflow/t1LowTurnSpecial/h1VolChgHighA/m1MarginDownBull 六键 feat_at=None 不拦(loss_rules.load_features 缺失降级契约),new14 默认档 14 键中占 6 键 → **近期信号 Y 系统性偏松**。§23.7⑤ 上报项,修法见 §6 Phase C。

## 4. X 盘中语义(调研问题 3)

- 盘中 X 可算:_fixedKeptSet(app.js:4844-4858)人口=items 中买入∧入样∧未命中 new14,排序键 track_score(盘中已重算)/rating(signal_stats 已重算)/类型——全部就绪。但**临时性真实存在**:今日组后续新信号(更高 track_score)可挤掉 top1 使 X 翻转;21:00 backfill-evening 迟到信号同理(上游报告 §6 已注明"今日以 21:00 定稿为准")。
- **建议口径:盘中保留显示 X + 临时标注**,不建议盘中藏 X:
  - 用户批评的核心诉求恰是盘中决策参考,"K1 主推位判断"是盘中最有价值的信息;藏 X=把最有用的一个数字砍掉;
  - 实现:it.date===todayDate 且 state.intradaySnapshot?.is_closed===false 时,_cxTxt 由 "1·当日主推"/"0·非主推" 变为 "1·当日主推(盘中临时·收盘定稿)"/同前缀(~10 行,hoverpop L5988 一处);
  - 定稿翻转场景公示一句即可(与既有「今日信号以 21:00 定稿为准」框架挂靠)。

## 5. S06 票盘中口径+防前视专节(调研问题 4)

- **结论:现口径天然自洽,不动**。快照语义(gen_kelly_mode_s06_state.py L77/L117-119):date=D 行 effective_mode=D 日生效基座,decision_date=D-1;T 日收盘判定 T+1 生效(§5.1⑥ 合规)。
- T 日盘中时间线:T-1 日 20:35 s06_snapshot(plist 工作日 20:35,gen→check→R2 三段)生成并上传含 date=T 行 → T 日盘中 _tdsS06BaseForDate(T) 正常命中。实证:8-26 行 decision_date=8-25、effective_mode=a9,昨日 20:35 已上线。
- 防前视检查:T 日盘中信号使用 T-1 收盘数据决策的基座=t 时点只用 t 前数据 ✓;不存在"用今晚才生成的快照判今天"的前视路径。fail-open(common.js:902-903 契约)仅当 T-1 任务失败兜底,计保留票=保守方向 ✓。
- 残余小缺口(记录不改):kelly_mode_s06_state.json edge TTL=3600 档(upload_r2 L1312+)靠 deploy purge,20:35 上传后最长 ~1h edge 旧版——只影响当晚,不影响次日盘中;market_tier_history.json 同理(见 §3 Phase A 解法)。

## 6. 实施方案(调研问题 5)

**总判断:不需要新建任何盘中采集/数据通道(现有 intraday 10min 链全覆盖),改动全是小修补。**

| Phase | 内容 | 落点 | 行数级 | 优先级 |
|---|---|---|---|---|
| A | bull 键实时化:ai_macro 加注 hs300 tier 字段 + _isBullStopHit 优先读它(fallback R2 map 不删) | queries.py L1398-1403 / app.js _isBullStopHit(~L2827) | ~15 行 | P2(当前下降期零影响,牛市前落地即可) |
| B | X 盘中临时标注「盘中临时·收盘定稿」 | app.js hoverpop L5988 一处+CONS_TIP 一句 | ~10 行 | P1(用户感知直接) |
| C | 特征库每日化(**先上报拍板再动手**):gen_kelly_loss_features.py 挂 update_all 尾段或独立盘后 launchd;六特征源(north_d20 北向/qvix/div_yield/turn_pct/h_volchg/margin)均为盘后可得键,T 日特征 T 日晚间补齐=T+1 生效,天然防前视 | scripts/update_all.sh 或新 plist | 任务级(半天) | **P0(Y 准确性最大杠杆,但涉数据链变更须用户确认)** |
| D | 公示补充:purpose-notes sig.consensus 段加「盘中信号实时可算;当日组 X 为临时值收盘定稿;特征类键截至 X 日」 | purpose-notes.js | ~3 行 | P1 |

- 明日盘中预期行为(Phase B/C/D 不做也成立):盘中新信号出现 → 10min 内 overview 重导传 R2 → 前端 ≤3min 轮询拉到 → collected_at 变化触发信号卡增量重绘 → 新信号带认可度行(Y/X 实时值)上屏,全程无需手动操作。
- 验收建议:Playwright 冒烟①mock is_closed=false+今日新信号断言 data-consensus 存在;②断言 ts:overview-refreshed 触发后 grid 更新;③Phase C 落地后 check_data_integrity 加「kelly_loss_features.json 覆盖末日≥T-1」断言。

## 7. 已验证方法/数据源清单

- 代码层:intraday_snapshot.py(采集主流程/recompute/export 三函数全文)、queries.py(ai_macro 层+注入循环+sigs 来源+tier 构建源)、loss_rules.py(load_features/make_feat_at/RULE_SPECS R2g/N2 等)、common.js(8 预设键集/S06 块全文/_tdsS06BaseForDate)、app.js(cellHtml/hoverpop/_doOverviewRefresh/_rerenderSigCardContent/_maybeRerenderSigCard/_refreshKpiMainValues/renderTab)、upload_r2.py(_data_cache_ttl)、intraday_snapshot.sh(推送链全文)、s06_snapshot/intraday-snapshot/update-all plist。
- 数据层:staticdata 灾备仓今日盘中逐轮 commit(c47d487db=14:48 版实测解析)、本地 static-site/data(overview/kelly_loss_features/kelly_mode_s06_state/market_tier_history 四件 mtime+内容)、trade-data/data/logs 今日 28 轮 intraday log(13:35 轮 signals 重算 70,977 条)。
- 试算:14:48 盘中版 hstech 全 8 票手算+脚本双验一致(Y=5/8)。

## 8. 维度清单完成度自查

| 维度 | 状态 |
|---|---|
| 盘中信号形态盘点(4 问全列) | ✅ §1 表格六形态 |
| 数据产物层验证(staticdata 盘中版 vs 本地 vs R2 策略) | ✅ §2(L09 教训执行:不凭代码分支下结论) |
| Y/X/S06 三票逐一盘中口径 | ✅ §3/§4/§5 |
| 防前视专节 | ✅ §5(T+1 生效时序核验,无穿越路径) |
| 方案分阶段+工作量+与既有盘中体系衔接 | ✅ §6(零新增采集) |
| 诚实标注(缺口三条+既有通病区分) | ✅ TL;DR⑤/§3 |

## 复现

- 输入依赖:staticdata 灾备仓 `/Users/linhuichen/code/trade-data-signal-staticdata`(盘中版 overview 取 `git show c47d487db:data/overview.json`)、本地 `static-site/data/{kelly_loss_features,kelly_mode_s06_state,market_tier_history}.json`、`trade-data/data/logs/intraday_snapshot_20260826_*.log`。
- 重跑命令(盘中版 Y 票精算,预设键集抄 common.js:749-778 单源勿从本文抄):
  ```
  git -C /Users/linhuichen/code/trade-data-signal-staticdata show c47d487db:data/overview.json | python3 -c "
  import json,sys
  ov=json.load(sys.stdin)
  t=[s for s in ov['signals_today'] if isinstance(s,dict) and s.get('date')=='20260826' and s.get('signal') in ('buy','buy_aux','buy_special','buy_backup')]
  print([(s['index_id'],(s.get('ai_macro') or {}).get('filters'),s.get('_bt_in_universe')) for s in t])"
  # 预期输出: [('hstech', ['r2gLowRatingQ3'], True)] → 对照 a9/new14 键集判 Y=5/8、X=1
  ```
- 关键口径一句话:认可度三票数据链(overview 盘中重导+ai_macro 无条件注入+S06 快照 T-1 决策 T 生效)在盘中均为实时合法态;唯一历史遗留=特征库手动生成滞后(§3 缺口①)。
- 数据截止:2026-08-26(盘中 14:48 staticdata 留档 + 收盘后定稿版对照)。
