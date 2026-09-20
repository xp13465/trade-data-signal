# 前端直接吃三表改造深度现状调研 + 精确改造方案(L42 步2 Phase 2/3)

日期:2026-09-20 | 角色:researcher(只读) | 状态:调研完成,供主控验收后派 implementer
测试基准:current baseline v1.1.7(权威 memory test-baseline-v112-anchor);改造必须数值口径零改动
前置产物:signal_kelly_trades_unique.json / signal_kelly_trades_sdc_unique.json(步1 已 merge main,开关 KELLY_UNIQUE_EXPORT 默认关)+ 分片 unique_recent.json / unique_t{YYYY}.json(生成端 L2169-2222 已实现,同开关触发,与旧 quadrants 分片并存)

---

## 〇、核心结论一句话

前端两处(app.js sim 弹窗 / lab.js 凯利页)对 trades 档的所有 quadrants 消费,可全部收敛为「1 次三表解析 → 按需还原两种产物」:
- **形态 A(还原 quadrants[qk][mode] 行数组)**:仅 5 个消费点需要(热区扫描/合并/交易日历/nav 目标集/lab 维度表),改动最小、与旧结构逐位对账天然成立;
- **形态 B(直接构建 mode pool 行)**:`_simBuildModePool`/`_kellyCollectBasePool` 两处核心改为从「base+归属+variants[mode]」直接构建,不再遍历 40 倍数组;
- 下游过滤链(13+ 键)/费后重算/K 档/s06 per-date/GIH 管位/posCap 排序**全部零改动**——它们只读 pool 行的 27 列字段(fIdx 索引)与 `_mktD/_etfD/_ratD` 三个聚合维度,而 pool 行正是 27 列数组 + 3 个附加属性的现有形态。

---

## 一、前端现状数据流图(app.js 与 lab.js 全链路)

### 1.1 通用基笔键(两处同源,天然一致)

- `_simBaseKey`(app.js L3573)/`_kellyBaseKey`(lab.js L7847):`signal_date|index_id|signal|buy_date|etf_code`(含 signal)。
- **45 条 signal 差异笔**(data-slim-research L29/L70/L123):同 (signal_date,index_id,buy_date,etf_code) 下 45 条 signal 不同 → key 含 signal 天然拆成不同基笔,与主表保留 signal 逐位一致,零冲突。实证:recent 热区内「同 4 元组不同 signal」269 组(recent 只含最近 120/90/60 天,密度更高),全史 45 组,均按 base_key 拆分。

### 1.2 app.js 首页模拟回测弹窗链路

| # | 函数(行号) | 数据流/消费点 | 消费哪些字段/结构 |
|---|---|---|---|
| 1 | `_simParseTrades`(L3640) | `tr.fields` → fIdx;`quadrants: tr.quadrants` | fields 27 列 → fIdx 下标表 |
| 2 | `_simLoadFull`(L3647) | 兜底全量 `signal_kelly_trades{sdc}.json`(75MB) | 同上 |
| 3 | `_simLoadKellyData`(L3681) | 首开拉 `_parts/recent.json` + `signal_kelly_backtest{sdc}.json`(cfg) | recent 热区扫描 L3704-3716 遍历全部 quadrants 行,读 `fIdx.signal_date` 求 `_simHotMinDate/_simHotMaxDate` |
| 4 | `_simEnsureRange`(L3737) | 提交超热区 → 并行拉 `t{YYYY}.json` 年片 → `_simMergeShards` 按 (qk,mode) concat 合并 | 分片与全量同构 quadrants |
| 5 | `_simBuildModePool`(L4544) **核心** | 遍历全部 16 个 qk,取 `quadrants[qk][mode]` 数组;`_simBaseKey` 去重;`seen[bk]` 首见写入 `orig.slice()` + 初始化 `_mktD/_etfD/_ratD`;后续 qk 用 `_simQkDim(qk)`(L3348,qk 前缀 mkt_/etf_/sig_/rating_)在空槽补维度值(首见写入,`if (!rec._mktD)` 不覆盖) | 行数组(27 列)+ 3 聚合维度属性;跨 qk 去重=本函数核心 |
| 6 | `_simPoolCached`(L4523) | per-mode LRU 缓存(上限 3 模式,数据引用变即失效) | 纯函数(数据引用,mode) |
| 7 | `_simPassesFade`(L3450) 过滤链 | 读 `t[fIdx.signal]`/`market_state`/`buy_date`/`market_tier`/`market_tier_all`/`market_tier_cyb`/`rating`/`buy_price`/`track_score` + **`t._mktD/_etfD/_ratD`** 聚合维度 + `_simLossRuleHit`(T1 20 新键,spec-driven,读 fields 列直读 + `t._mktD`) | pool 行 27 列 + 3 维度 |
| 8 | s06 per-date(L4392-4413) | fadeOn+s06 态:每笔按 signal_date 取 `_tdsS06FiltersForDate` 当日基座键集过滤(fail-open/兜底计数) | `t[fIdx.signal_date]` + 过滤链 |
| 9 | K 档(L4429-4460) | 按 signal_date 分组,sort(track_score DESC→rating→signal→buy_date ASC)取 top-K;`_tdsS06P1StripHigh` 判 K=1 剔 rating_high | `signal_date/track_score/rating/signal/buy_date` |
| 10 | G/H/I 管位(L4461-4493) | `_simGhiHoldCap` 手段 A/P 硬控;`_simCollectNavCodes` 收 etf_code 集 | `etf_code` + 管位需要 buy/sell_date/buy_price |
| 11 | 日期切片+排序(L4495-4505) | kept.filter(按 signal_date 区间)+ sort desc | `signal_date` |
| 12 | `_simRenderTable`(L5181) | 每行 `_simBtCalcRow`(L5924 费后重算:读 buy_price/sell_date/current_price/sell_price/etf_code)+ 累计列 | 27 列 + `_gihForced/_gihNavMissing` 行属性 |
| 13 | `_simBuildTradeCal`(L4612) | 观察期倒计时:遍历全部 quadrants 行,收集 signal_date/buy_date/sell_date 并集作交易日历 | 27 列 3 字段(含 sell_date!见风险点 R4) |

### 1.3 lab.js 凯利页链路

| # | 函数(行号) | 数据流/消费点 | 消费哪些字段/结构 |
|---|---|---|---|
| 1 | `_labKellyParseTrades`(L8699)/`_labKellyLoadFull`(L8723) | 与 app 同构:fields→fIdx + quadrants | fields 27 列 |
| 2 | `_labKellyMergeShards`(L8706) | 分片 (qk,mode) concat | quadrants 同构 |
| 3 | `_kellyBuildTradeDims`(L7472) **核心差异点** | 遍历**全部 16 qk × 10 mode**,key = baseKey + `|sell_date`,value = {rating,etf,sig,mkt} 维度值(从 qk 名拆分 parts[0]/parts.slice(1)) | 维度 map(baseKey+sell_date → 维度值) |
| 4 | `_kellyTradeFeatures`(L7606) | 惰性特征:weekday/quintile + 维度查 `_tradeDims[baseKey+|sell_date]` 取 mkt/rating | dims map + fields 列 |
| 5 | `_kellyPassesFadeFilters`(L7728) | 与 app `_simPassesFade` 等价:读 fields 列 + `feats.mktD/ratD/etfD`(etfD=track_tier 列直读,注意与 app `_etfD` 语义不同!见 R2) | pool 行 + dims map |
| 6 | `_kellyCollectBasePool`(L7893) **核心** | **只遍历 rating_high/mid/low 3 个 qk × sellModes(10 mode)**,`passFn(_t)` 先过滤再 `_kellyBaseKey` 去重;可选 skipRatingKey(s06p1 K=1 剔 rating_high) | 行数组;不附加维度属性(维度走 _tradeDims) |
| 7 | `_kellyApplyFeeRecompute`(L8946) 主入口 | quads=td.quadrants;quadMeta=data.quadrants(**backtest 统计档**的象限名表);per-date s06/passesFade/passesFadeNoBull;`_kellyCollectBasePool` 主池+NoBull 池 → posCapKept;主循环遍历 quadMeta 每 qk × mode 取 `(quads[qk]||{})[modeKey]` 过滤+posCap;period 切片(buy_date>=cutoff);`_kellyRecomputeTrade` 费后重算;`_kellyComputeStats` | 27 列 + posCapKept(由 pool 构建) |
| 8 | `quadsAll`(L8977-8984) | rating 3 qk 拼接 per-mode(全信号表「all」伪象限) | concat 数组 |
| 9 | `_kellyCollectNavCodes`(L8103) | 遍历全部 qk × G/H/I mode 收集 etf_code 并集 | `f[etf_code]` |
| 10 | `_kellyStatsFor`(L10628,演进表格)/卡片渲染 | rawTrades = `(td.quadrants||{})[quadKey][modeKey]`(quadKey 枚举来自 backtest 统计档),与 `_kellyApplyFeeRecompute` 同构重算 | 27 列 |
| 11 | `_kellyPositionCapKeptKeys`(L7851) | pool → byDate 分组 sort 取 K | `signal_date/track_score/rating/signal/buy_date` |

### 1.4 消费点穷举汇总(前端 3 文件)

- app.js quadrants 消费:6 处 = parse(L3644)/merge(L3667)/热区(L3706)/pool(L4550)/tradeCal(L4614),其中 pool 消费是唯一「跨 qk 去重」点。
- lab.js quadrants 消费:12 处 = parse/merge/dims(L7474)/collectPool(L7893)/applyFee quads(L8972)/quadsAll(L8977)/navCodes(L8103)/statsFor rawTrades(L13000)/collectPool 二次(L13084)/tradeDims 重建(L8992/L10659/L13016)。
- common.js:仅 `_kellyIntradayRender` 消费 **intraday 档**(L1447,独立 26 列结构,审计 §2.2 建议保持旧结构),**不在本次改造范围**;其 `_simQkDimCompat/_intradayPool`(L1495-1520)是 intraday 专用,与主档 pool 同构但数据源独立。

### 1.5 跨 qk 去重与顺序依赖(核心机制)

- app `_simBuildModePool`:`for (const qk in quadrants)` 遍历顺序 = JSON 键序(文件写入序,实测 recent 为 rating_high,rating_mid,... )。同一基笔跨 qk 的 27 列**逐字段全同**(实测 recent probe 行在 rating_high/etf_strong/sig_special/mkt_concept 4 个 qk 均 `identical: True`),故首见写入哪个 qk 的行无差异。
- 聚合维度:`_mktD/_etfD/_ratD` 值由 qk 名前缀派生,同一基笔恰好 4 个 qk 分属 4 组各一 → 维度值**唯一、顺序无关**(data-slim-research §七.1 已验证)。三表化后直接由「归属枚举码 → qk_groups[组][码] → 前缀值」落 3 个维度,不需要遍历顺序。
- lab 侧维度不走行属性而走 `_tradeDims` map,key 含 sell_date —— 三表化后由「base 行 + 归属枚举」直接构建同一 map,零依赖遍历顺序。

---

## 二、直接吃三表的精确改造方案

### 2.1 统一三表解析器(新函数,两处复用)

新增「三表解析」入口,输出两种形态:

```
parseUnique(uniq):
  fIdx = {}; uniq.fields.forEach((f,i)=>fIdx[f]=i);        // 19 共享字段下标
  vfIdx = {}; uniq.variant_fields.forEach((f,i)=>vfIdx[f]=i); // 8 卖出字段下标
  // 形态 A: 还原 quadrants[qk][mode] 行数组(27 列, 仅给 A1~A5 消费点)
  restoreQuadrants(uniq) -> { qk: { mode: [row27, ...] } }
  // 形态 B: 直接构建 per-mode pool(主表遍历 → 归属 → 变体拼 27 列 + 3 维度)
  buildModePool(uniq, mode, skipRatingKey?) -> [row27+_mktD/_etfD/_ratD, ...]
  // 形态 C: 直接构建 lab 维度表(等价 _kellyBuildTradeDims)
  buildTradeDims(uniq) -> { baseKey+|sell_date: {rating,etf,sig,mkt} }
  // 形态 D: 交易日历/热区/nav 目标集(只需 base 表)
  buildTradeCal(uniq) -> [signal_date/buy_date/sell_date 并集排序]
  scanBase(uniq) -> {min,max}  // 热区上下界: 遍历 base[0](signal_date)
```

**关键约束**:三表 `fields`=19 列,`fIdx.sell_date` 等 8 个卖出字段下标**不存在** → 任何把三表直接当旧 quadrants 喂给下游的写法都会让 `t[fIdx.sell_date]`=undefined 而崩。**所有下游消费都必须吃「27 列还原行」或「带 3 维度的 pool 行」,不能吃 19 列 base 行**。

### 2.2 app.js 精确改造点

| 函数 | 改造前 | 改造后 |
|---|---|---|
| `_simParseTrades`(L3640) | 只收 quadrants | **收三表**:存 `{fields:27列合成, fIdx(27), ufIdx(19), uvIdx(8), qk_groups, base, variants}`;并**惰性还原形态 A**(quadrants)供 merge/热区;还原 = base 遍历 → 按归属枚举进 4 qk → variants[mode][i] 拼 27 列 → 跳过 null 变体行 |
| `_simMergeShards`(L3663) | quadrants concat | **保持 concat**(形态 A 已还原 27 列,语义不变) |
| 热区扫描(L3704-3716) | 遍历 quadrants 读 signal_date | 改遍历 `base[i][0]`(signal_date,base 按 signal_date 升序 → 直接取首/末即可,不必全遍历) |
| `_simBuildModePool`(L4544) | 遍历 16 qk × mode 数组,baseKey 去重 | **改形态 B**:遍历 base → 归属枚举 → 拼 27 列 + 直接落 `_mktD/_etfD/_ratD`(由归属码查 qk_groups 前缀);base 无重复故无需 seen 去重(保 seen 兜底也行,零成本);**输出行与旧 pool 逐位一致(见 §四 对账)** |
| `_simBuildTradeCal`(L4612) | 遍历 quadrants 收日期并集 | 改形态 D:base 遍历收 signal_date/buy_date + variants 全 mode 收 sell_date(注意:变体表跨 mode 收 sell_date 才等价旧全遍历,见 R4) |
| URL 层(L3580-3610/L3694/L3754) | `signal_kelly_trades{sdc}` / `_parts/t{YYYY}.json` | 全量改 `signal_kelly_trades{sdc}_unique.json`;分片改 `_parts/unique_recent.json` / `_parts/unique_t{YYYY}.json`(生成端已同命名);双套基名逻辑(`_simTradesBaseName`)保留 |
| `_simLoadFull`(L3647) | 拉 75MB | 拉 ~4MB unique 全量(兜底语义保留) |

### 2.3 lab.js 精确改造点

| 函数 | 改造前 | 改造后 |
|---|---|---|
| `_labKellyParseTrades`(L8699) | 同 app | 同 app(收三表 + 惰性还原形态 A + 形态 B/C/D) |
| `_labKellyMergeShards`(L8706) | quadrants concat | 保持 concat(形态 A) |
| `_kellyBuildTradeDims`(L7472) | 遍历 16 qk × 10 mode 建 dims map | **改形态 C**:base 遍历 → 归属 4 枚举 → 每基笔对每个 mode 的变体行建 `baseKey+|sell_date` → dims[key]={rating,etf,sig,mkt}(从 qk_groups 组名/枚举名派生:rating_high→rating 组值 high,etc);**key 含 sell_date 语义保留**(per-mode 变体行 sell_date 各不同 → 条目数 = n_base×10,与旧一致) |
| `_kellyCollectBasePool`(L7893) | 遍历 rating 3 qk × sellModes 数组 | **改形态 B**:主表遍历按归属枚举仅进 rating 3 组过滤(skipRatingKey=rating_high 时跳过)→ variants[mode] 拼 27 列 → passFn 后 baseKey 去重;**注意旧实现 passFn 在去重前逐行调用、pool 行=原始数组引用,新实现也须 passFn 先于 push 且返回行=还原的 27 列数组**(非 19 列 base 行) |
| `_kellyApplyFeeRecompute`(L8946) 的 quads/quadMeta/quadsAll | td.quadrants 读行 | quads=形态 A 还原;quadMeta=backtest 统计档(不动);quadsAll=形态 A 还原后 rating 3 qk concat(语义不变) |
| `_kellyCollectNavCodes`(L8103) | 遍历 quadrants × G/H/I | 改形态 D:base 遍历仅 G/H/I mode 的 variants 行收 etf_code(或直接形态 A 还原后照旧,成本可接受) |
| `_kellyStatsFor`(L10628)/卡片 | rawTrades=quads[quadKey][modeKey] | 形态 A 还原后照旧 |
| URL 层(L8588-8604/L8727/L8798) | 同 app | 同 app(unique 全量 + unique_ 分片) |

### 2.4 下游过滤/重算/K 档/s06/管位是否零改动

**全部零改动**,依据:
- `_simPassesFade`(L3450)/`_kellyPassesFadeFilters`(L7728):只读 `t[fIdx.xxx]` 列 + `t._mktD/_etfD/_ratD`(app)或 `_tradeDims`(lab)。pool 行=27 列数组+3 维度属性(形态 B),完全满足。
- `_simBtCalcRow`(L5924)/`_kellyRecomputeTrade`(L7241):只读 buy_price/sell_date/current_price/sell_price/etf_code(27 列内)。
- K 档排序(L4440/L7851):signal_date/track_score/rating/signal/buy_date(27 列内)。
- s06 per-date(L4392/L9034):signal_date + 过滤链。
- G/H/I 管位(L4461/L9180):etf_code/buy_date/sell_date/buy_price(27 列内)。
- **唯一需要同步的「行附加属性」**:`_gihForced/_gihNavMissing`(app 渲染时挂)与 `_kellyBaseKey` 一致性 —— 这些属性在 pool 构建后由渲染/管位环节挂,与三表还原无关。

### 2.5 十二项消费方逐一核实与改法(脚本侧)

| # | 消费方 | 现状读法(已核) | 唯一化后改法 | 依赖 |
|---|---|---|---|---|
| 1 | check_universe_alignment.py | L150-165 assertion3 遍历 `trades["quadrants"][qk][mode]`,行内 `r[1]=index_id, r[2]=signal`;L270 打印 quadrants 数 | 改读 unique 主表:遍历 `base` 行,`row[1]=index_id, row[2]=signal`(base 19 列序=share_fields,index_id/signal 在下标 1/2,与旧行 1/2 同位);或读 `fields`/`base_key_fields` 动态定位 | 生成端全量 unique 已存在(开关触发);§23.6 门禁 |
| 2 | check_data_gap_alerts.py | L663-678 `_scan_trades` 遍历 quadrants,`r[0]=signal_date,r[1]=index_id,r[2]=signal`;L632-658 72MB mtime 缓存 | 改读 unique 主表 base 行同列(0/1/2 同位);顺带 72MB→~4MB 提速 | 断档监控,必须同批改 |
| 3 | overfit_monitor.py | L381-396 遍历 quadrants + **硬校验 `len(tr) != len(FIELD)=27` raise ValueError** | 改读 unique:`fields`(19)+`variant_fields`(8)拼接为 27 列还原行后照旧,或直接按 share/variant 两段校验列数;新 schema 重写列校验 | 列数漂移保护重写 |
| 4 | signal_kelly_snapshot.py | L154-165 `scan_trades` 遍历 quadrants,`compact_trade[0]=signal_date` | 改读 unique base 行 `row[0]`;`extract_quadrant_subset` 读统计档不受影响 | — |
| 5 | kelly_posrating.py | L831-838 fields→fIdx + quads 遍历;A 模式 all=rating 3 qk concat;`_trade_dims` 构建 | fields 改 27 列合成(share+variant 并集);A 模式 all 从 base 按归属枚举取 rating 3 组;`_trade_dims` 改形态 C | 评级 K 档卡(共享数据源) |
| 6 | check_fade_predicate_parity.mjs | L170-176 fields→fIdx + 遍历 `td.quadrants[qk].A`(mode A 并集) | 改读 unique base × mode A variants 还原 27 列(谓词不感知 mode,A 并集=全量基笔语义保留) | §5.4⑦ 对账机检 |
| 7 | check_posrating_parity.mjs | L151-159 遍历 `td.quadrants[qk][modeKey]` | 改读 unique 还原 27 列 + `_kellyBuildTradeDims` 形态 C | 同上 |
| 8 | check_loss_rules_vs_mining.py | L95-118 `R.prepare_rows(trades_path)` mode A + 8 键基座复刻前端 | 改读 unique 还原 mode A 行(复刻层同步) | §5.4⑦ 复刻对账 |
| 9 | test_kelly_stats.py | L192 冻结切片 `quadrants.rating_high.A 前 5 行` | 数据切片路径改 unique 还原(或冻结三表切片);断言口径保持 v1.1.7 | — |
| 10 | test_loss_rules_20keys.py | L50-51 FROZEN_TRADES=`rating_high.A 行0-2` | 同上改 unique 还原 | — |
| 11 | playwright-accept 批量(~20 mjs) | curl 线上 trades 验渲染断言 | 发布回归时同步:断言改验 unique 文件 + 页面渲染;分片/全量 URL 断言更新 | 随发布批 |
| 12 | intraday 档全链路 | common.js `_kellyIntradayRender`(L1447)/collector/rerun | **保持旧结构不动**(审计 §2.2) | 不动 |

> 补充核实(审计 §2.3 已列):backtest 统计档消费方(check_data_integrity/monitor_72h/gen_daily_brief/nextday_plan)均不读 trades 档,不受影响;upload_r2/worker headers.js 若新增 unique 文件名需补上传清单与 regex。

---

## 三、风险点清单

| # | 风险点 | 详情 | 防错手段 |
|---|---|---|---|
| R1 | 三表 fields 19 列 vs 旧 27 列,`fIdx.sell_date` 等缺失 | 三表 `fields`=share_fields(19),直接喂下游 `t[fIdx.sell_date]`=undefined 静默崩 | 解析器必须输出 27 列还原行或 pool 行;对账机检断言「还原行 len==27 且 fIdx 全键存在」 |
| R2 | lab `feats.etfD` 语义 ≠ app `_etfD` | lab `_kellyTradeFeatures`(L7620)`etfD = track_tier 列直读`(strong/related/approx/none/null);app `_etfD` = qk 前缀 etf_ 后缀(strong/related/approx/has_track)。**两者不是同一个字段**,改造必须各自保留消费方式 | 还原 27 列时 track_tier 列原样保留(base 19 含 track_tier),lab 维度表只供 mkt/rating;`etfD` 继续列直读,不引入 qk 维度 |
| R3 | 45 条 signal 差异笔 | 同 4 元组 signal 不同 → base 拆不同行;归属枚举对拆分后的行仍恰好 4 qk(schema §1.4 零例外) | base_key 含 signal 原样保留;对账用「键集相等」而非「行数/四元组数相等」 |
| R4 | `_simBuildTradeCal` 需跨 mode 收 sell_date | 旧实现遍历全部 quadrants 行(含各 mode 卖出日期),交易日历含全部 mode 的卖出日;若只从 base 收 signal/buy_date 会丢卖出日 → 观察期倒计时计算错 | 形态 D:base 收 signal_date/buy_date + **variants 全 mode 收 sell_date 并集**,或直接形态 A 还原后照旧(还原成本可接受) |
| R5 | s06 per-date 过滤 | 依赖 `t[fIdx.signal_date]`(27 列内,base 保留)与 `_tdsS06FiltersForDate`(读 kelly_mode_s06_state.json 快照,不读 trades) | 保留 signal_date 列;s06 快照链不受影响(已核实) |
| R6 | 双套切换 | 主档/sdc 基笔集不同(主档 ⊂ sdc,本地 7608⊂7612,云上 7648⊂7767),唯一化双套独立生成 | 前端双套 URL/基名逻辑保留;跨档对账用「主档基笔集 ⊆ sdc」非等数(审计 §1.5) |
| R7 | 分片合并与基笔互斥 | 分片按 signal_date 切,基笔完整落在单一片,不跨片;但**每片三表独立排序/n_base** → 旧 `_simMergeShards` concat 直接拼 quadrants 数组仍可用(形态 A 已还原);若直接拼 base 表会错(重复 base_key 语义丢失) | 合并必须发生在「形态 A 还原之后」;对账断言各片还原行==旧分片行 |
| R8 | variants[mode][i] 可能为 null(哨兵) | 生成端对某 mode 无有效回测的基笔写 null(L1639 注释) | 还原/建池时 `if (v==null) continue` 跳过该 (mode,基笔) 行;对账断言键集相等即覆盖 |
| R9 | 热区扫描顺序 | 三表 base 按 signal_date 升序排序 → 热区直接取 base[0][0] / base[-1][0],不需全遍历;但**若未来 base 排序变化**,取首末会错 | 机检断言「base[0] 的 signal_date == min(base 全表 signal_date)」;或保留一次全遍历(5.6MB 很小,成本可忽略) |
| R10 | `_simPoolCached` LRU 缓存键 | 缓存键=数据引用+mode;三表化后同一数据引用内 pool 构建变快,无正确性问题 | 保持引用比较;数据替换(分片合并/切档)即失效重建 |
| R11 | intraday 档共享 `_build_outputs` 改造点 | 若实施把 `_build_outputs` 改成三表结构,intraday 档会跟着变 → common.js `_kellyIntradayRender` 断粮 | intraday 路径必须保持旧结构(步1 已用 KELLY_UNIQUE_EXPORT 开关隔离,实施别动 intraday 分支) |
| R12 | 12 项消费方+playwright 批量漏改 | 改结构后旧断言漂移静默 FAIL | 同批改 + §5.4⑦ 对账机检 + playwright 回归断言改验 unique 文件 |

---

## 四、对账锚点(改造后「新三表路径 == 旧 quadrants 路径」逐位一致)

### 4.1 对账层次(由底到顶)

1. **生成端无损还原机检(已存在,步1)**:`scripts/check_kelly_unique_restore.py --unique <unique.json> --trades <trades.json>`,断言 `{(qk,mode,base_key)}` 键集相等 + 304,320 行 27 列逐位一致。实施前先跑通(本地 9-13 主档应有 7,608 基笔)。
2. **分片还原机检(已存在,步2 Phase1)**:`scripts/check_kelly_unique_parts_restore.py`,每片三表还原 == 旧分片 quadrants 逐位。跑通后前端分片路径才有对账基准。
3. **前端解析器对账(新写,改造必备)**:`node` 直接喂同 `unique.json`,分别用「新三表解析器」与「旧 quadrants 直读(临时对比桩,实施期保留)」构建同一 mode pool,断言:
   - pool 键集(base_key 集合)相等、无重复;
   - 每行 27 列逐位相等;
   - `_mktD/_etfD/_ratD` 逐位相等;
   - pool 行顺序(旧实现按 qk 遍历序,新实现按 base 遍历序)——**顺序可能不同**!若下游有依赖 pool 顺序的地方(表格渲染排序在 pool 后统一做 sort,无依赖),断言仅比「集合+逐位值」,不比顺序;若实施希望顺序也一致,新 pool 可按「还原 quadrants → 旧遍历」保序(形态 A+B 混合)。
4. **页面实测锚点(§5.4⑦ 最高层)**:Playwright 无痕浏览器打开首页 sim 弹窗 / lab 凯利页,固定「模式=G、周期=y1/all、K=1、S06 默认、费率默认」,断言页面数字(净盈亏/收益率/胜率/累积列/峰值)与改造前基线一致。**改造前后各录一次基线,diff 必须为空**。

### 4.2 具体断言点(可写脚本)

| 断言 | 位置/口径 | 期望 |
|---|---|---|
| unique 全量还原键集 | check_kelly_unique_restore.py | `{(qk,mode,base_key)}` 零缺零多 |
| unique 全量值逐位 | 同上 | 304,320 行 27 列全 PASS |
| 分片还原 | check_kelly_unique_parts_restore.py | 每片逐位 |
| 前端 pool 键集 | 新对账脚本(三表解析 vs 旧 quadrants 直读) | 相等 |
| 前端 pool 27 列值 | 同上 | 逐位相等(排除顺序) |
| 前端 3 维度 | 同上 | `_mktD/_etfD/_ratD` 逐位相等 |
| 热区上下界 | scanBase vs 旧 quadrants 扫描 | `_simHotMinDate/_simHotMaxDate` 相等 |
| 交易日历 | 形态 D vs 旧 `_simBuildTradeCal` | 并集相等 |
| lab 维度表 | 形态 C vs `_kellyBuildTradeDims` | 键集相等 + 值相等 |
| 页面数字 | Playwright 无痕 × G/y1/all × K1 × S06 × 默认费率 | 改造前后 diff 空 |

### 4.3 对账触发时机

- 每次前端算法改动后重跑 §4.1-3 机检;
- 每次页面发布前跑 §4.1-4 页面实测锚点;
- 对不上 = 停,查根因再继续(§5.4⑦ 铁律)。

---

## 五、分阶段改造顺序建议(依赖关系)

### Phase A:对账基建(先行,串行前提)
1. 生成端跑 `KELLY_UNIQUE_EXPORT=1` 产全量+分片三表(本地 9-13 或最新数据);跑通两个 restore 机检(全量/分片)全 PASS。
2. 写「前端三表解析器对账脚本」(§4.1-3)作为实施期的回归基线;同时用 Playwright 录当前页面基线数字(G/y1/all × K1 × S06)。

### Phase B:前端解析器 + app.js(与 C 并行,互不依赖文件)
3. app.js `_simParseTrades` 收三表 + 惰性还原形态 A + 形态 B/C/D;改 URL 层(unique 全量 + unique_ 分片)。
4. `_simBuildModePool` 改形态 B(核心);`_simBuildTradeCal` 改形态 D;热区扫描改 scanBase。
5. 跑 §4.1-3 对账 + 页面实测(首页 sim 弹窗)。

### Phase C:lab.js 凯利页(与 B 并行)
6. lab.js `_labKellyParseTrades` 收三表 + 形态 A/C/D;`_kellyCollectBasePool` 改形态 B;`_kellyBuildTradeDims` 改形态 C;URL 层同步。
7. 跑 §4.1-3 对账 + 页面实测(凯利页卡片/全信号表/按年表/K 档评级)。

### Phase D:12 项消费方同批(必须与前端同批上线,不能只改前端)
8. 脚本侧 10 项(check_universe_alignment/check_data_gap_alerts/overfit_monitor/snapshot/posrating/2 个 parity mjs/check_loss_rules_vs_mining/2 个 test)改读三表 + 列校验重写;跑各自自测。
9. playwright-accept 批量断言更新(改验 unique 文件 + 页面渲染)。

### Phase E:上线切换 + 兜底/残留清理
10. deploy 后:线上验证 ①main 链含 commit ②数据层 curl `signal_kelly_trades_unique.json` 有值 ③前端展示层 curl 上线 JS 含新解析字符串(§8「功能 done」三查)。
11. 旧 75MB 全量 + .gz 双套保留一段时间观察(兜底),确认无回退后再评估删除;`lab_*_p{N}` 364 files 与 recent2.json 确认无消费方后删除(审计 §2.4)。

### 依赖关系
- A → B、C(解析器依赖生成端产物与对账基准)
- B ∥ C(改不同文件,可并行;但两者都吃形态 A 还原函数,建议先定统一还原语义再分头实现)
- B/C → D(消费方脚本只读 unique 文件,不依赖前端实现;可与 B/C 并行,但上线必须同批)
- 全部 → E

---

## 六、已验证方法/数据源清单

- 本地 static-site/data/signal_kelly_trades{,_sdc}.json(9-13 05:10,78MB)+ parts 分片:python 解析验证 qk 键序/行结构/跨 qk 全同/45 条 signal 差异笔口径/recent 热区 4 元组差异 269 组。
- 生成端 scripts/signal_kelly_backtest.py:L173 TRADE_FIELDS、L1575 `_build_unique_tables`(三表 schema 单一事实源)、L2169-2222 分片三表导出、L2274-2292 全量三表导出。
- 前端消费点穷举:app.js 6 处 / lab.js 12 处 / common.js intraday 1 处(不动),逐函数读了过滤链/费后重算/K 档/s06/管位/统计的字段消费方式。
- 审计文档:data-slim-consumers-audit-20260920.md(12 项消费方 + sdc 差异根因 + intraday 判定)、kelly-unique-schema-20260920.md(三表 schema + 无损还原规则)、data-slim-research-20260920.md(原始瘦身方案 + 45 条 signal 差异笔 + 首见顺序验证)。
- 业界佐证(data-slim-research §八):预聚合+明细分层、HTTP Range、TTL 分层(改造不依赖,但设计原则同源)。
