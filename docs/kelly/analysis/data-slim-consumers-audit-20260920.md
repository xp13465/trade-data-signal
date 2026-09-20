# L42 基笔唯一化方案·消费方补齐审计(两个遗漏维度)

日期:2026-09-20 | 角色:researcher(只读) | 状态:补充 L42 data-slim-research-20260920.md 缺失的 sdc 差异根因 + 消费方穷举
测试基准:current baseline v1.1.7(口径权威见 memory test-baseline-v112-anchor);本审计不重算口径,只做数据形态/消费方分析。

## 一、sdc 档多出基笔的根因(第一步结论)

### 1.1 事实钉死
- 本地 static-site 9-13 05:10 产物:主档 7,608 基笔,sdc 7,612 基笔,**sdc 多 4 条、主档无独有**(主档 ⊂ sdc)。
- 云上(权威)9-20 05:05 产物:主档 7,648 基笔,sdc 7,767 基笔,**sdc 多 119 条、主档仍无独有**。
- 差异随数据版本动态增长(4→119),非静态巧合;按年分布 2018(3)/2021(1)/2022(15)/2023(27)/2024(41)/2025(25)/2026(7),覆盖全史。

### 1.2 根因机制(生成端代码证据)
主档与 sdc 由同一 `scripts/signal_kelly_backtest.py` 生成,仅环境变量不同:
- 主档 `KELLY_BUY_NEXTDAY=1`(默认,next_day_open 买价口径):买价需 `信号日原始 close × 次日原始 open` 换算(signal_kelly_backtest.py L849-857);`sig_close` 或 `nxt_open` 任一缺失/非正即 `return None` **整笔丢弃**(L852-853),伪跳空 |gap|>20% 同样丢弃(L854-856)。
- sdc `KELLY_BUY_NEXTDAY=0`(signal_day_close 当日收盘口径):直接取信号日 accum_nav(L859-860),只用当日 close(缺失回退 open),**无次日价依赖,不受缺价/伪跳空影响**,照常入账。

### 1.3 4 条基笔明细(本地 9-13 版本)
基笔键口径=前端 `_simBaseKey`(signal_date|index_id|signal|buy_date|etf_code,app.js L3573):

| 基笔键 | etf | sdc 侧字段快照 | 主档丢弃原因(数据实证) |
|---|---|---|---|
| 20211111\|thsc_300082\|buy_special\|20211111\|512560 | 军工ETF易方达 | buy_price=1.643141, profit=+64.02, 到期 | 次日 2021-11-12 原始 open=None(该 ETF 2021-11 中旬份额拆分,拆分前后原始价错位,12 日当日原始价缺失) |
| 20240829\|sw_801120\|buy\|20240829\|516900 | 食品饮料ETF华安 | buy_price=0.536636, profit=-471.14, 到期 | 次日 2024-08-30 原始 open=None |
| 20260731\|csi_930851\|buy_aux\|20260731\|159739 | 云计算ETF鹏华 | buy_price=1.577776, profit=+609.21, 到期 | 次日 2026-08-03 open=0.777 vs 信号日 close=1.576,**gap=-50.7% > 20% 伪跳空剔除**(159739 同期份额拆分) |
| 20260911\|hstech\|buy_aux\|20260911\|513260 | 恒生科技ETF汇添富 | buy_price=1.056155, 持有中 | **最新交易日窗口**:9-13(周日)生成时次日 9-14(周一)开盘价尚未产生;9-14 后重跑主档即自动补入(本地 DB 已验证 9-14 open=1.04 已有) |

### 1.4 云上 119 条复核:513030 系统性缺口
- 119 条中 **513030(德国DAX ETF)占 102 条**(其余 17 条散落 530580/512980/513400/530000/513650/512560/510900/159501/513080/512030/560920/159905)。
- 云上 etf_daily 实测:513030 **整段历史 open/close 全 None**(accum_nav 有值,原始价采集缺口,境外 ETF 未采原始价)→ 主档 nextday=1 对 513030 全部基笔 `nxt_open is None` → 全丢;而 sdc 只用 accum_nav 当日值 → 照常入账(real_buy_price 显示 0)。
- 结论:**sdc 多出的基笔 = 主档因缺原始价/伪跳空丢弃的全部基笔;主档基笔集恒为 sdc 的真子集**。

### 1.5 对唯一化方案的对齐影响(关键)
1. **双套基笔集天然不同(主档 ⊂ sdc),且随数据版本动态变化** → 唯一化**必须双套各自独立生成主表+变体+qk 归属**,禁止共用一份唯一化主表;方案风险点 3「双套同构覆盖」精确化为:结构(schema)同构、基笔集不强求一致。
2. **sdc 档内唯一化规律成立**:云上 sdc 全局 7,767 基笔 × 每基笔恰好 40 次(4 qk × 10 mode)全覆盖零例外 → sdc 唯一化主表行数 = 7,767(≠ 主档 7,648),差异笔零特殊处理。
3. **跨档一致性断言不能用「基笔数相等」**:唯一化后若有机检/对账想校验双套,应改用「主档基笔集 ⊆ sdc 基笔集」或各自独立口径,不许等数。
4. 4 条差异笔(本地)/119 条(云上)在各自档内均为正常基笔,前端 `_simBuildModePool` 双套独立解析,现状即如此,唯一化不引入新冲突。

## 二、signal_kelly_trades 结构消费方全清单(第二步结论)

判定方法:grep `signal_kelly_trades|quadrants|fields` 于本地 trade 主树 scripts/worker/app/static-site + 云上 trade-data(scripts 目录 symlink 直指主树同一 inode,代码同源;数据产物云上为权威,9-20 版本已核)。

### 2.1 唯一化后【必须同步改】的消费方(解析 quadrants[qk][mode] 行数组 / fields 列式)

| # | 消费方 | 消费方式(证据行) | 唯一化后要改什么 |
|---|---|---|---|
| 1 | static-site/app.js(首页模拟回测弹窗) | `_simParseTrades`(L3640)/`_simLoadFull`(L3647)/分片 recent+年片加载(L3694-3757,失败回退 `_simLoadFull` L3767)/`_simBuildModePool`(L4544)/`_simBaseKey`(L3573)/`_simIsSdc·_simTradesBaseName`(L3607-3610 双套基名) | 解析器适配三表(主表+变体+qk归属)现组装 `quadrants[qk][mode]`;删除前端跨 qk 去重 40 倍扫描;双套(主/sdc)都要;兜底 URL 不变但数据变小(~4MB) |
| 2 | static-site/lab.js(凯利页) | `_labKellyParseTrades`(L8699)/`_labKellyLoadFull`(L8723)/年片解析(L8798,失败回退 L8771/L8787)/`_kellyCollectBasePool`(L7893)/`_labKellyIsSdc·_labKellyTradesBaseName`(L8600-8603) | 同上等价点;lab 凯利页多消费点(按年表/全信号表/管位)全部走 `_labKellyParseTrades` 与 `_kellyCollectBasePool`,适配新结构 |
| 3 | scripts/check_universe_alignment.py | assertion3 遍历 `trades["quadrants"][qk][mode]`,行内 index 1=index_id、2=signal(L147-153,L257-270)| 改读唯一化主表前 3 列(或保留兼容视图);§23.6 入样宇宙对称校验是强制门禁 |
| 4 | scripts/check_data_gap_alerts.py | `_scan_trades` 遍历 quadrants,行内 index 0/1/2=signal_date/index_id/signal(L663-678);72MB mtime 缓存加载(L632-658) | 改读主表;顺带受益:唯一化后 72MB→~4MB,该脚本 load 不再拖慢 |
| 5 | scripts/overfit_monitor.py | L381-396 遍历 quadrants 且**硬校验每行 len==len(TRADE_FIELDS)=27**(列数漂移 ValueError) | 改读主表;列校验规则随新 schema 重写 |
| 6 | scripts/signal_kelly_snapshot.py | `scan_trades` 遍历 quadrants,compact_trade[0]=signal_date(L154-165) | 改读主表取 max_signal_date + recent10(注意:同文件 `extract_quadrant_subset` 读的是统计档,不受影响) |
| 7 | scripts/kelly_posrating.py | fields→fIdx + quadrants 遍历(L831-838) | 改读主表(fields/fIdx 映射换新 schema) |
| 8 | scripts/check_fade_predicate_parity.mjs | 读 TRADES_JSON,遍历 `td.quadrants[qk].A`(L175-176),fields→fIdx(L170-171) | 改读主表 mode A 并集(唯一化后主表即全量基笔,mode A 并集语义天然保留) |
| 9 | scripts/check_posrating_parity.mjs | 读 TRADES_JSON+BT_JSON,遍历 `td.quadrants[qk][modeKey]`(L151-159) | 改读主表+变体 |
| 10 | scripts/check_loss_rules_vs_mining.py | `R.prepare_rows(trades_path)` mode A + 8键基座复刻前端逻辑(L95-118) | 改读主表(复刻层同步;涉 §5.4⑦ 同构对账铁律) |
| 11 | scripts/tests/test_kelly_stats.py / test_loss_rules_20keys.py | 冻结切片读 `quadrants.rating_high.A` 前 5/3 行 | 数据切片路径改主表;断言口径保持 v1.1.7 |
| 12 | scripts/playwright-accept/*(verify_sigkelly_y1_render 等约 20 个 mjs) | 验收脚本 curl 线上 trades 验渲染 | 发布回归时同步;非常驻消费方,但改结构后旧断言会漂移,须一并过 |

### 2.2 intraday 盘中增量档判定(signal_kelly_trades_intraday.json)

- **结构同构**:顶层 {generated_at, buy_amount, period_cutoffs, fields, quadrants} + 独有 `intraday` 元信息(rerun_date/next_open_date/price_basis=next_day_open_akshare_spot/main_pre_date_hash);quadrants 16 子域同主档;fields **26 列**(比主档 27 列缺 `real_buy_date`,生成端 compute_intraday 路径跳过该字段)。
- **量级**:本地 2.2KB / 云上 48KB,**无 40 倍膨胀问题**(只含 T 日信号,单日几十条)→ 唯一化无必要。
- **生成端耦合**:`compute_intraday`(signal_kelly_backtest.py L1734)与全量共用 `_build_outputs`(L1837-1844 也走 L1493 输出组装)→ **若实施把 `_build_outputs` 直接改成三表新结构,intraday 档会跟着变**;必须给 `_build_outputs` 加唯一化开关或让 intraday 路径保持旧结构。
- **前端消费独立**:渲染单源在 common.js `_kellyIntradayRender`(L1437+,fetch `./data/signal_kelly_trades_intraday.json`,自建 fields→fIdx 独立解析,不经 app.js `_simParseTrades`);anchor 挂在 lab.js L13473/L13524 与 app.js L4069-4082。intraday 档若保持旧结构,**不受主档唯一化改造影响**。
- **后端消费**:app/collector/etf_national_team.py L1357-1481 读 intraday 档 quadrants 刷新持仓 current_price;kelly_intraday_rerun.sh(云上 timer 交易日 9:40)生成 + verify_intraday 对账 + intraday_snapshot.sh 传 R2。
- **建议**:intraday 档**不动**(保持旧结构),前端主档解析器改造不涉及它;但实施时注意 `_build_outputs` 共享改造点(见上)。

### 2.3 唯一化后【不受影响】的消费方

| 消费方 | 原因 |
|---|---|
| check_data_integrity.py `check_signal_kelly_backtest`(L604)/`check_signal_kelly_backtest_sdc`(L671) | 校验的是**统计档** signal_kelly_backtest.json(501KB)的 quadrants[qk].periods 结构,非 trades 档;统计档不动 |
| monitor_72h.sh(L427-428,L710-732) | 读 signal_kelly_backtest.json 统计档(quadrants 非空 + y1/A annualized_return 口径) |
| gen_daily_brief.py(L954-958) | 读 signal_kelly_backtest.json 统计档按信号类型的凯利仓位 |
| upload_r2.py | 按文件名 glob/路径前缀上传(cmd_upload_kelly_parts L1087 / _sdc L1105 / data-large 排除 L1167-1172);文件名字面不变则免改;**若唯一化新增 `*_base.json` 类新文件名需补上传清单** |
| worker/headers.js | 路径 regex 匹配(L185 L199),文件名不变免改;**新增 `*_base.json` 需补 regex** |
| deploy.sh | 仅引用 sdc 注释/上传命令(L543-545),不上传/解析 trades 结构 |
| nextday_plan_generator.py | 已改方案A(读 freeze/stats/s06/board_etf_map,不读 trades;L13-14 注释即说明) |
| gen_kelly_mode_s06_state.py / check_s06_freshness.py / check_consensus_parity.mjs | s06 快照链不读 trades |
| app/queries.py | 仅注释(L954) |
| signal_kelly_backtest_bond.py | 债券对比档自己产 quadrants,不写/不读现网 trades(L22 注释) |
| intraday 档全链路(common.js `_kellyIntradayRender`/collector/rerun) | 若 intraday 档保持旧结构(见 2.2) |

### 2.4 分片/兜底/遗留文件补充

- 分片目录:主档 `signal_kelly_trades_parts/`(17 个:recent+t2011..t2026+**recent2.json** 遗留),sdc `_sdc_parts/`(17 个,无 recent2)。recent2.json **全站无前端引用**,与方案第四节 lab_*_p{N}.json 同属删除候选(补充进第四步,需再验 R2 消费后删)。
- 分片消费路径:app.js recent(L3694-3701)/年片(L3754-3767,失败回退全量 L3767);lab.js 年片(L8798,失败回退 L8771/L8787)。唯一化后分片也切三表结构(年片 shrunk ~4 倍),兜底全量 = 唯一化全量 ~4MB,原 75MB 长拉消除。
- 双套基名切换:app.js `_simTradesBaseName`(L3608)/lab.js `_labKellyTradesBaseName`(L8601),买入口径切换(next_day_open ↔ signal_day_close)依赖两套并存,唯一化双套各自保留。

## 三、给主控的分步实施补充建议

1. **生成端**:`_build_outputs` 加「三表唯一化」开关,仅主档全量 + sdc 全量走新结构;intraday 路径保持旧结构(避免 common.js `_kellyIntradayRender` 断粮)。
2. **双套独立**:主档主表 7,648 行(云上 9-20)/sdc 主表 7,767 行,各自主表+变体+qk 归属,互不共用;跨档断言用「主档⊆sdc」不用等数。
3. **机检联动**(必须改 12 项,见 2.1 表)与**前端**(app.js/lab.js)同批改,不能只改前端——check_universe_alignment(§23.6 门禁)、check_data_gap_alerts(断档监控)是生产监控链路,改了结构不断粮。
4. **lab_*_p{N} 364 files + recent2.json** 确认无消费后删除(第四步扩)。
5. 发布前按 §5.4⑦ 对账:唯一化三表 vs 旧 quadrants 解析结果逐位一致(至少 GIH×y1/all),再切默认。

## 四、已验证方法与数据源清单

- 本地 static-site/data/signal_kelly_trades.json(78MB)+ _sdc.json(78MB),9-13 05:10 产物;python 解析对比基笔键。
- 云上 /home/ubuntu/code/trade-data/static-site/data/(权威,9-20 05:05),ssh -i ~/tdsignal.pem。
- 生成端 signal_kelly_backtest.py L840-863(买价口径)/L849-856(缺价+伪跳空丢弃)/L1962-1969(分片由文件名派生)/L1734 compute_intraday/L1493 _build_outputs。
- 消费方 grep:本地 trade 主树 scripts/worker/app/static-site + 云上对照(scripts symlink 同源)。
- etf_daily DB(trade-data/data/etf_national_team.db)原始 open/close 实证。
