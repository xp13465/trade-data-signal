# 「AI 信号认可度」(多模式共识分 X/Y)hoverpop 展示·调研报告

- 日期: 2026-08-26 | 角色: researcher(只读调研,未改任何业务代码)
- 需求: 信号 hoverpop 最后加一行「AI 降亏多模式认可度」,双段格式 **X/Y**——Y=8 降亏模式计票(0~8,固化不受界面开关影响);X=AI 仓位终审位(固化按 positionCap 开启+K1 主推档视角判 kept,0/1 二值)。未来升级为列表级显眼展示。
- 落档位置理由: 本功能本质=8 降亏模式预设的共识统计,主题归属降亏 toggle 族,与 `ai-mode-dropdown-research-20260823.md` 同目录同类;本目录有 README 索引(已同步追加)。

---

## 结论摘要(TL;DR)

1. **Y 票不需要跑谓词**:overview 每条信号已带后端预注入的 `ai_macro.filters`(该信号命中的全部降亏键数组,无条件全量注入不做模式裁剪),Y 计票=对 8 个预设 keys 做**集合求交**(交集空=kept=1 票)。零特征 JSON 依赖、单信号 <0.01ms、全列表 476 信号×8 模式毫秒级。
2. **真实数据试算通过**:近 30 日 200 个买入入样信号 Y 分布 {8:6, 5:33, 4:1, 3:20, 2:111, 1:7, 0:22},0 分与 8 分样例齐全(见 §9 复现段),口径可落地。
3. **重大发现(上报级)**:后端 `_ai_macro_hit_filters` **不判 `r10May6NonMay` 与 `k3ConceptBuy` 两键**,而 new14/new15/a9 预设都含这两键——首页现有删除线判定(new14 视角)实际只覆盖 12/14 键。属历史遗留缺口(§23.7⑤ 上报待用户拍板,不默认修),认可度若基于 ai_macro.filters 会继承此近似。
4. **X(K1 固化)推荐前端方案 A**:渲染时用全量 items 按「当日组→买入类→入样→未命中 new14 键集→排序取 top1」预算固化 kept 表,与首页现有 AI建议编号链同源同精度;后端预注入(方案 B)可作 v2 演进但同样只能用信号级近似谓词,首期收益不成比例。
5. **X 天然参数稳定**:kept 判定只依赖 {NEW14 键集, K=1, 入样宇宙, 排序键 track_score→rating→signal类型→buy_date},与费率档/G 档位/卖出模式 A-I/buyAmount **全部无关**(它们只影响资金分配不影响谁被留下)。唯一漂移点=今日信号 21:00 补采定稿前当日组可能变。

---

## 1. 现状结构:hoverpop 渲染链与消费场景

### 1.1 渲染函数(落点)

- 全局唯一 hoverpop 引擎 = app.js `_initTermPop`(IIFE,@/Users/linhuichen/code/trade/static-site/app.js:5699),document 级 mouseover/click 委托 `[data-tip]`(回退 `[title]` 首次迁移,L5709-5729),核心渲染 `show(el, text)` @app.js:5731。
- 信号 cell 分支(sigType 存在)拼装顺序 @app.js:5830-5853:
  `text parts(信号标签/子描述/指数名/reason)` → 删除线原因行 `term-pop-aihit`(L5843-5851,data-ai-hit="1" 时) → `locateHtml + idxLineHtml + etfMetaHtml + etfHtml`(L5852) → `pop.innerHTML`(L5853)。
- **「最后追加一行」落点 = app.js:5852 之后、5853 innerHTML 赋值之前**,读 cell 的 `data-consensus` 属性拼 `<div class="term-pop-consensus">…`。样式仿既有 `term-pop-aihit`(style.css 同族加一条)。
- 数据来源:cell 渲染时算好写入属性。cell 拼 DOM 唯一点 = `_renderSignalGrid` 内 cellHtml 返回串 @app.js:4988(`data-idx/data-sig/data-sig-type/data-date/…/data-ai-hit` 全在此拼),在此追加 `data-consensus="y|x"`(+可选 `data-consensus-dim="1"` 表 0 分灰显)。

### 1.2 消费场景清单(§23.3 举一反三)

| 场景 | 入口 | 是否带认可度 | 说明 |
|---|---|---|---|
| 首页信号卡(今日+近30日列表) | app.js:5327 / 14556 `_renderSignalGrid(...,"signal")` | **是(主场景)** | 用户需求点名处 |
| 近期技术分析参考点区块 | app.js:14556(同一 cellHtml 链) | **是(自动获得)** | 与主场景共用 cellHtml,零额外改动 |
| 汪汪队 chip / 冰点日格(kind≠signal) | app.js:4990 freeze 分支、nt chip | 否 | 无降亏语义(s.* 情绪/国家大队不在判定人口),自然不带 |
| 情绪日历信号格 renderSentimentSignalList | app.js:5255 注释所述 s.* 格 | 否 | 情绪分非可交易信号 |
| lab 凯利区 | lab.js 无信号级 hoverpop(仅评级表/水印/说明 pop,L8621/10730 等) | 否 | 凯利区数据源=回测产物天然对齐,无此需求 |
| 模拟回测弹窗(app.js L3163 起) | 行点击弹交易 modal,非 hoverpop | 否(本期) | 未来列表级化时可一并考虑 |

结论:改 cellHtml 一处 + show() 一处,两个 signal 场景同时生效,无漏网消费点。

## 2. 谓词可用性:不求交谓词,直接用 ai_macro.filters

### 2.1 后端已全量注入命中键数组

- queries.py 模块头注 @/Users/linhuichen/code/trade/app/queries.py:495-512:「给 overview.json 每条信号注入 ai_macro:{hit, filters}(filters=该信号命中的全部降亏条件键, **无条件注入、不做默认档裁剪**——前端/check_signals 各自按所选模式键集二次过滤)」。
- 注入循环 @queries.py:1376-1383,遍历 overview 全部信号行(sigs 来源 @queries.py:1049-1055 = signal_daily 全量×30 日窗口,本地实测 overview.json signals_today=476 条/30 日)。
- 仅买信号守卫(MED3):@queries.py:866 非买(band_hold/sell/sell_stop_loss)filters=[]。
- 前端现成消费先例 = `_isAiFadeHit(it)` @app.js:4675-4694:`it.ai_macro.filters.some(fk => _members[fk])`——**首页现有删除线就是这个求交**,Y 票判定与之完全同构,只是把「单一当前模式」扩成「8 个预设各求交一次」。

### 2.2 各票判定公式(建议实现)

```
对预设 p(静态 7 票): hit(p) = ai_macro.filters ∩ p.keys ≠ ∅  或  (p 含 bullAuxBackupStop 且 _isBullStopHit(it))
Y = Σ (7 票 !hit) + S06 票
S06 票: base=_tdsS06BaseForDate(it.date)(common.js:957);ok → 按 a9/new15 键集同式判;!ok → fail-open 计 1 票
```

- bullAuxBackupStop 不在 ai_macro.filters(后端不判,grep queries.py 零命中),须前端补:`_isBullStopHit(it)` @app.js:2827(sig∈{buy_aux,buy_backup} × tier=="牛市·主升",tier 来自 `_ensureSigTierMap()` @app.js:2811 拉 R2 market_tier_history.json——本地实测覆盖 2002-11-08~2026-08-25 全历史,盘中新日缺失=保守放行,与现状同语义)。
- 依赖就绪性:common.js 为三页共加载基座(`_KELLY_FADE_MODE_PRESETS` @common.js:749、`_tdsFadeModeById` @792、`_tdsS06BaseForDate` @957 全部挂 window @885-1011),hoverpop 场景必然就绪;`_KELLY_FADE_LEGACY_SPECS`/特征 JSON(kelly_loss_features.json)**都不需要**——那是跑完整谓词(lab.js `_kellyPassesFadeFilters` @lab.js:7523 三段结构:FRONT spec/gate 特征块/T1 规则块)才要的,Y 票路径完全绕开。
- S06 快照懒加载:首页仅当选了 s06 模式才 `_tdsS06StateEnsure()`(@app.js:5242-5246 幂等单例)。认可度是固化统计,**无论用户当前模式都要 S06 票 → 实施时需在渲染链幂等发起一次 ensure**(单例 promise,已加载直接复用,零重复请求)。

### 2.3 S06 快照失败口径(调研问题 2 附)

推荐 **fail-open 计 1 票**,不推荐弃权标"—":
- 与首页判定链降级契约完全同语义(common.js:902-903「快照缺失→fail-open 该笔不拦」、app.js:4683 fail-open=保留);
- "固化不受界面操作影响"的直觉下,Y 值不应随网络状态抖动;
- 可见性沿用现有 S06 警示通道(_homeS06WarnCount 计数警示条 @app.js:4584/4697,S06 slot 四态),不在每行 hoverpop 加噪音。
- purpose-notes 公示写一句:「S06 快照不可用时该票按保留计(fail-open)」。

### 2.4 非买入类显示口径(主控默认口径未覆盖,上报拍板)

后端仅买守卫导致卖类 filters=[],不特判会显 8/8 造成误导。建议:**卖类/band_hold 的 Y 显「—」**(tooltip 注明"仅买入信号参与降亏过滤判定");X 对 卖类/band_hold/未入样本(_bt_in_universe===false)也显「—」(它们不在 K1 kept 人口)。

## 3. 性能与缓存(调研问题 3)

- 单信号 8 票 = 8 次∩,实测 ai_macro.filters 最长 10 键(分布 {0:176,1:7,…,10:2}),预设最长 17 键 → 单信号 ≈280 次字符串比较(<0.01ms);全列表 476×8≈13 万次比较,合计毫秒级。**无需 featCache 类机制**(那套 `_kellyTradeFeatureCache` @lab.js:7366 是跑完整谓词时缓存 weekday/quintile/维度聚合用的,Y 路径用不上)。
- 未来列表级批量(几千信号×8):仍便宜,但建议结构上一步到位:
  - 渲染前一次性预算两张表:`_consensusMap`(it 引用→{y,x})模块级缓存,**失效键 = overview data.generated_at + 预设集 hash(preset ids+keys join 的 md5 前 8)+ NEW14 键集版本**;overview 重拉 generated_at 变即自动失效,预设表是代码常量随发版走。
  - cell 只查表写 data 属性;未来列表 badge 直接读同一张表,零重算(§22 一张表喂 N 展示位)。
- X 固化表同理:per-date 组内排序,30 日×日均 <17 笔买入入样信号,一次 O(n log n) 微不足道。

## 4. 口径细节:预设家族包含关系与 bull 键分布(调研问题 4)

### 4.1 bullAuxBackupStop(候选1)分布

含此键的票 = **p9/a9/b9/c9 共 4 张静态票 + S06 的 a9 基座日**(common.js:753/755/757/759;p8 L751、new14 L761、new15 L770 均不含;a9 含、new15 不含——即"候选1 在哪些票里生效"的精确答案)。c9 有速查卡注「真选 C 应叠 8 键下线候选1」(L758 calWarn),计票按键集字面判,tooltip 不展开、报告如实标注。

### 4.2 p8 家族包含关系(诚实陈述相关性,不改口径)

- 键集包含链:**p8 ⊂ p9 ⊂ a9**(p9=p8+bullAuxBackupStop,a9=p9+T1 八键);b9(15 键)/c9(16 键)也 ⊇p9。
- new14/new15 换基座,与 p8 族仅 3 键交集(greedy15/janMidSpecial/k2c5HkChase);new15=new14+excludeTierNone(new14⊂new15)。
- **后果:8 票高度非独立**——p8 被拦则 p9/a9/b9/c9 五票齐拦(Y 至少 -5)。真实分布实证:Y=2 有 111 个(p8 族拦+new 族留 2~3 票)、Y=5 有 33 个(p8 族全留),中间档稀疏。独立信息≈3 簇:{p8 族 5 票} {new14/new15} {S06 动态}。
- 建议 tooltip 加一句「票间有家族重叠,非独立评审」即可,不改计票口径(主控指示如实陈述)。

### 4.3 发现上报:后端两键缺口(§23.7⑤ 完整证明链路)

- **现象**:new14/new15/a9 预设含 `r10May6NonMay` 与 `k3ConceptBuy`(common.js:761/770/755),但后端 `_ai_macro_hit_filters`(queries.py:845-940)与 `_ai_macro_hit_new_keys`(queries.py:819-841,只遍历 loss_rules.NEW_KEYS_PROD=T1 20 键)**均无这两个键的判定**(grep 全文件仅注释引用 L499/L847)。
- **影响**:①首页 new14 视角删除线少拦 r10(5月+6非5月组合,spec 见 common.js:665,其中 5 个子条件信号级可判)与 k3(主关注×概念,common.js:683,`{sig:"buy",mkt:"concept"}` **完全信号级可判**)命中的信号;②邮件链路(check_signals.py 从 overview 读 ai_macro,L62-64/L776)同样继承;③本认可度 Y/X 若基于 ai_macro.filters,new14/new15/a9 票偏松。
- **根因推测**:两键属 hist/v3-v4 老 37 键族,后端信号级层(v1.1.3 建)按当时默认八键+T1 批次实现,v1.1.5 切 NEW14 基座时审计(v115-new14-baseline-alignment-audit.md)查了六处登记点键集中文名,未覆盖「后端谓词实现完整性」。机检 check_fade_keys_alignment.py 六项断言也不含「预设键 ⊆ 后端可判键集」方向。
- **处置建议**:按 §23.7⑤ 报用户拍板——修法轻(queries.py 补两个纯字段谓词分支:k3 一行;r10 五个信号级子条件一行,price_bin 两子条件继续降级不判),修完 check_fade_keys_alignment 加第⑦项断言「默认档键集的信号级可判子集必须被 _ai_macro_hit_filters 覆盖」。**本认可度功能不阻塞**:先按现状口径上线并诚实标注,new14 票注明「基于信号级可判定子集」。

## 5. 与既有标记的关系(调研问题 5)

- `_bt_in_universe`:queries.py:1134 注入(any etfs track_score non-null),前端未入样走「未入样本」删线链@app.js:4882。关系:X 人口排除它;Y 不管它(债类等未入样信号的 ai_macro.filters 仍可能命中键,如港股行业?——实测 hk_industry 无 track_score 但 k2c5 只判 mkt_hk 单值(L899),不会误标;Y 对未入样买入类照常计算,tooltip 不必特殊处理)。
- track_score/rating:cell 已有评分尾缀(scoreBadge L4906-4918,sig_stats 10d score 阈值 0.75/0.55 分高/中/低);X 排序 rating 口径与此同源(_ratingOf @app.js:4721 同阈值,后端 _ai_macro_rating_of @queries.py:729 同款),一致。
- hoverpop 内层级:末行共识 div 排在 ETF 至今行(etfHtml)之后,视觉上是"总结行";0 分灰显用独立 class(主控口径③),不动既有配色体系。
- AI仓位层标记(posCapBadge「AI建议N/当日已满」L4859-4877)是**动态视角**(跟随 tds_poscap 开关/K 档),共识行是**固化视角**,两者并存不冲突,tooltip 明确"与左侧 AI建议标注可能不同,因那边跟随你的开关"。

## 6. X(K1 固化)可行路径两案对比(升级重点①)

### 现成缓存核实(为什么不能直接复用)

- 首页 `_posCapKeptMap` @app.js:4702-4759:**函数局部变量**(作用域=`_renderSignalGrid` @4485),且人口=popItems(**受用户 ETF 档位筛选影响**)+排除 band_hold/未入样+先滤当前模式降亏,K 跟随 tds_poscap——四点全部违背"固化"要求,不能复用。
- `_AI_POSCAP_RATING_DYNAMIC` @common.js:488/lab.js:8485:只有各 K 档统计值(收益率等 `_posVals`),**无 per-signal kept 明细**,不能复用。

### 方案 A(推荐):前端渲染时预算固化表

- 落点:`_renderSignalGrid` 作用域内新增 `_fixedConsensus(items)`:
  - per-date 组:人口=items 全量(不受 windowedItems/档位筛选,先例=_dateHasInUniverseBuy 用 items @app.js:4654-4668)中 买入类 ∧ `_bt_in_universe!==false` ∧ 未命中 new14 键集(ai_macro.filters ∩ new14.keys 为空;new14 不含 bull 键,**不需要 tier map**);
  - 组内排序复刻 `_posCapSortedFn` 口径(track_score DESC(top1 etf)→rating high>mid>low→signal 类型 buy_backup>buy>buy_aux>buy_special→buy_date ASC,@app.js:4728-4742),top1 即 X=1;
  - **独立定义排序函数**,不复用 `_posCapSortedFn`(它在 `tds_poscap.on&&k合法` 条件内才赋值 @app.js:4717,off 态为 null,固化视角不能依赖用户状态)。
- 优点:零后端/零 export/deploy 改动(§23.7 生产稳定);与首页现有 AI建议编号**同级别精度**(用户已接受的近似层级);数据实时跟 overview。
- 缺点(诚实标注,全部与凯利区严格口径的既有差距同源):a) 继承 §4.3 两键缺口;b) rating 取自 sig_stats 信号级而非 trades 行;c) 回测基笔池跨全历史去重 vs 首页当日组人口(理论同源 signal_daily,残余差异极小)。

### 方案 B(备选,v2 演进):后端 queries.py 注入 `_k1_kept`

- 类比 `_bt_in_universe` 先例(§23.6「首页 1:1 遵从回测侧」精神),在 ai_macro 注入循环后(@queries.py:1383 同一遍 sigs)按 date 分组算 top1 标 true/false。
- 注意:**Python 后端并没有 positionCap kept 实现**(positionCap 是前端 lab.js 重放引擎 `_kellyPositionCapKeptKeys` @lab.js:7646,signal_kelly_backtest.py grep 零命中)——方案 B 是在 queries.py 新写一份排序逻辑(约 30 行),不是"复用回测产物",精度并不高于方案 A(同样受 §4.3 缺口限制);额外成本=NEW14 键集后端登记点+1(必须进 check_fade_keys_alignment 机检)+export 重跑+§22 三步同步。
- 定位:v2 若做「列表级显眼展示+全历史认可度」再切 B(那时批量固化进 JSON 更划算);本期 A 最小闭环。

### X 参数稳定性(升级重点②)

- kept 判定依赖 = {NEW14 键集(钉死), K=1(钉死), 入样宇宙规则, 排序口径};**费率档/G 档位/buyAmount/卖出模式 A-I 全部无关**——它们只影响每笔金额与盈亏分配,不影响"谁被留下"(lab.js:7638「过滤在模式之前统一生效」「9卖出模式共享同一批基笔」;_kellyPositionCapKeptKeys 输入只有 pool/fIdx/K)。
- 唯一漂移点:**今日信号** 21:00 补采(backfill-evening)迟到信号挂「盘后补齐」角标进当日组,可能挤掉原 top1 → 今日 X 在定稿前可能变;历史日冻结不变。tooltip/公示注明「今日信号以 21:00 定稿为准」即可(与既有信号固化时点公示同框架,purpose-notes lab.sigkelly 已有两段式文案可挂靠)。
- positionCap 关闭的用户:tooltip 写明「X 恒按标准视角(AI 仓位开启+K1★主推档)计算,与你当前的开关/K 档设置无关;你界面上看到的 AI建议标注才是跟随开关的动态结果」。

## 7. 实施方案(调研问题 6:最小实现路径)

**改动文件清单(方案 A,预估 ~85 行)**:

| 文件 | 锚点 | 内容 | 行数 |
|---|---|---|---|
| static-site/app.js | `_renderSignalGrid` 顶部(L4627 附近,_statItems 后) | 新增 `_fixedConsensus` 预算表(固化 new14 键集常量从 common.js preset 单源拉取 `_tdsFadeModeById("new14").keys`,禁硬编码)+ 8 票函数 `_consensusOf(it)`;S06 ensure 幂等发起 | ~45 |
| static-site/app.js | cellHtml L4988 | 拼串追加 `data-consensus="${y}|${x}"`(非买/未入样写 `data-consensus="na"`)| ~8 |
| static-site/app.js | show() L5852 后 | 读属性拼 consensusHtml(格式:`🤝 AI降亏多模式认可度: <b>X/Y</b>`+title tooltip 三档互证文案;na 显「—」)| ~12 |
| static-site/style.css | .term-pop-aihit 附近 | `.term-pop-consensus`(+ `-dim` 0 分灰)| ~10 |
| static-site/purpose-notes.js | 新 key `"sig.consensus"`(或并入 lab.sigkelly 尾段) | 公示:定义/8 预设票/fail-open/家族重叠/今日定稿/X 标准视角 | ~6 |
| docs/kelly/toggle/README.md | 索引 | 追加本报告一行(已完成) | 1 |

**联动点**:
- §21 公示:认可度属展示统计不改算法,purpose-notes 一处足够;hoverpop 行内 title 自解释(三档互证:白话+场景+下方 1:1 例)。
- §24:改 app.js 必同 commit build_min+bump 版本串+sw.js CACHE_VERSION(实施 agent 铁律,不赘述)。
- 机检(建议 P2 可选):`scripts/check_consensus_parity.mjs`——node 读 overview.json+common.js presets 重算 Y/X,与静态检查 data-consensus 拼串逻辑抽查比对;轻量版=parity 断言写进冒烟。
- Playwright 冒烟:①hover 任一买入信号 cell 断言 .term-pop 含「AI降亏多模式认可度」且匹配 /\d\/8|—/;②构造 filters∩new14 非空+全 8 票拦的 mock 数据断言灰显 class;③mock kelly_mode_s06_state.json 404 断言 Y 仍出数(fail-open 计 1)且 S06 警示通道在;④断言 positionCap off(localStorage tds_poscap={on:false})下 X 值不变(固化)。
- codex 外部 review:§23.14,B 级必发。

## 8. 已验证方法/数据源清单

- 代码层:app.js(hoverpop/_renderSignalGrid/_isAiFadeHit/_simPassesFade/_ensureSigTierMap/_isBullStopHit)、common.js(8 预设/S06 块/评级 pop)、lab.js(_kellyPassesFadeFilters/_kellyPositionCapKeptKeys/_AI_POSCAP_RATING_DYNAMIC 写入)、queries.py(ai_macro 层全文+注入循环+sigs 来源)、check_signals.py(邮件链路读法)、loss_rules.py(NEW_KEYS_PROD)、purpose-notes.js(键清单)。
- 数据层(本地 static-site/data 实测):overview.json(476 信号/30 日/filters 分布/tier map 2002-2026)、kelly_mode_s06_state.json(daily effective_mode)、signal_kelly_trades.json(fields 24 列无 kept 字段)。
- 试算:python 全量重放 8 票公式(§9),分布合理、极端样例人工核对通过。

## 9. 复现

- **正式咬合件(2026-08-26 实施期已落)**:`scripts/check_consensus_parity.mjs`(独立第二实现, 与前端 app.js `_consensusVotesOf/_fixedKeptSet` 互证)——重跑命令 `node scripts/check_consensus_parity.mjs`(只读校验; 全量 (date|index|sig)→{y,x} 写 /tmp/consensus-expected.json 供 Playwright 冒烟逐条比对)。最近结果: 入样 196 条 Y={8:6,5:33,4:1,3:20,2:112,1:2,0:22}, 例证①②③全部成立。
- 脚本:本报告 §4.2/§2 数据结论由一次性 python 内联脚本产出(临时试算未另存脚本;正式版即上行 `scripts/check_consensus_parity.mjs`)。
- 输入依赖:`static-site/data/overview.json`、`static-site/data/market_tier_history.json`、`static-site/data/kelly_mode_s06_state.json`;预设键集抄 `static-site/common.js:749-778 _KELLY_FADE_MODE_PRESETS`(单源,勿从本文抄)。
- 重跑命令(试算版):
  ```
  python3 - << 'EOF'
  import json,collections
  ov=json.load(open('static-site/data/overview.json')); s06=json.load(open('static-site/data/kelly_mode_s06_state.json'))
  P={m:set(k) for m,k in [("p8","excludeSpecialBear n2NovSpecialIndustry janMidRating janMidSpecial k2c5HkChase r7MayReinforced excludeAuxCross greedy15".split()),
      ("p9","excludeSpecialBear n2NovSpecialIndustry janMidRating janMidSpecial k2c5HkChase r7MayReinforced excludeAuxCross greedy15 bullAuxBackupStop".split()),
      ("new14","r10May6NonMay greedy15 janMidSpecial k2c5HkChase k3ConceptBuy declinePhaseSpecial n1NorthOutflow t1LowTurnSpecial d1LowDivYield q1QvixLowPct h1VolChgHighA m1MarginDownBull p1LowDivBackup r2bSpecialGlobal".split())]}
  tier={r['date']:r['tier'] for r in json.load(open('static-site/data/market_tier_history.json'))}
  sm={str(r['date']):r['effective_mode'] for r in s06['daily']}; BUY={"buy","buy_aux","buy_special","buy_backup"}; dist=collections.Counter()
  for s in ov['signals_today']:
      if not isinstance(s,dict) or s.get('signal') not in BUY or s.get('_bt_in_universe') is False: continue
      f=set((s.get('ai_macro') or {}).get('filters') or []); y=0
      bull = s['signal'] in ('buy_aux','buy_backup') and tier.get(str(s.get('date') or ''))=='牛市·主升'
      for mid in ["p8","p9","new14"]: y += 0 if (f & P[mid] or ("bullAuxBackupStop" in P[mid] and bull)) else 1
      y += 0 if f & P[sm.get(str(s['date']),'new14')] else 1   # s06 票(其余 4 票 a9/b9/c9/new15 略,完整版见报告)
      dist[y]+=1
  print(dict(sorted(dist.items(),reverse=True)))
  EOF
  ```
  (注:上面精简到 4 票示意;报告 §2 试算为完整 8 票版,两者方向一致。)
- 数据截止:overview.json generated_at=2026-08-25 盘后(30 日窗口 20260715~20260825)。
- 关键口径一句话:Y=8 预设键集与 ai_macro.filters 求交的 kept 数(bull 键前端 tier map 补判,S06 按日期读快照基座,fail-open 计 1);X=new14 过滤后当日入样买入组内 track_score DESC→rating→类型→buy_date 排序 top1=1。

## 1:1 直白举例(§23.9,数字全部来自上述真实数据核验)

- **白话**:Y=8 个降亏模式里有几个愿意留下这个信号;X=按标准 K1 视角,AI 仓位当天会不会真买它。
- **场景**:看到一笔信号想判断"是真金还是纸面繁荣"——Y 高只说明过滤层喜欢它,X=0 提醒你就算全留下,K1 主推档当天也轮不到它。
- **举例**:①2026-07-23 恒指 buy_special:ai_macro.filters 含 k2c5HkChase(港股追涨)+n1NorthOutflow+r1VolRatioLow+r2gLowRatingQ3+v2Vol20Gt25 → 8 票全拦,**Y=0**(灰显);②2026-07-20 中证系列 4 笔 buy_aux 只命中 v2Vol20Gt25(不在任何默认票键集)→ **Y=8**;③2026-08-24 当日 new14 未拦的入样买入只有 2 笔(csi_399975 track_score 78.2 / csi_H30199 71.0)→ 排序后 csi_399975 **X=1**、csi_H30199 **X=0**(Y 可能同为高分但 K1 当天只带第一笔="纸面繁荣警示"的真实形态)。
