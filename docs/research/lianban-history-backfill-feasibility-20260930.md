# 调研:最高连板 `a_width_max_lianban` 历史缺口根因 + 一年历史回补可行性

> 调研日期:2026-09-30 | researcher 只读调研(未改业务代码/未写库/未 commit)
> 一句话结论:缺口根因 = ① `width_history.py`(mootdx)回填了涨停/跌停等 7 指标但**漏了最高连板** ② max_lianban 唯一数据源是东财涨停池「连板数」字段,而**东财接口历史只滚动保留近段**(实测今天只能取 20260911 起,一年前已清空) ③ `backfill.py` 以 `a_width_zt_count` 是否已有为 skip 判据,被 mootdx 全段回填后对历史日全部跳过 → 历史段永远没补。**可行回补源 = FAPI 涨停池 limit-up-pool(实测 2021-09 起逐交易日可用,含连板数字段)**,排除 ST 后与线上东财口径 69 天重叠段对账 68/69 一致(98.5%)。

---

## 1. 现状(生产实况)

生产主库 `/home/ubuntu/code/trade-data/data/sentiment.db`(云上,trade-update-all.service WorkingDirectory):
| metric | 日期范围 | 天数 | source 构成 |
|---|---|---|---|
| a_width_max_lianban | 20260612 ~ 20260930 | **77 天** | akshare 25(20260612-20260911)+ intraday 52(20260714-20260930) |
| a_width_zhaban_rate | 20260612 ~ 20260930 | **77 天** | 同构(东财双池) |
| a_width_zt_count | 20160104 ~ 20260930 | 2603+ 天 | width_history.py mootdx 全段回填 |
| a_width_seal_rate / a_width_zb_count | 20160104 起 | 全段 | 同上 |

(本地 mac 开发库停在 20260917,69 天,是过期副本,不作生产实况)

## 2. 根因(为什么历史只有 20260612 起)

### 2.1 两个生产路径都依赖东财涨停池接口
- 盘中:`app/collector/intraday_snapshot.py:1722-1748` `_collect_intraday_width_metrics()` → `ak.stock_zt_pool_em(date=today)` → `lianban = int(df["连板数"].max())` → upsert source='intraday'(2026-07-14 起,commit fb4477d3d)。
- 历史回填:`app/backfill.py:35-82` `backfill_width(days=270)` → 逐日 `ak.stock_zt_pool_em(date=d)` → `lianban = float(zt["连板数"].max())` → upsert source='akshare'。

### 2.2 回填 skip 判据缺陷(决定性)
`app/backfill.py:44`:`if _have("a_width_zt_count", d): skipped += 1; continue`
- `width_history.py` 已把 `a_width_zt_count` 用 mootdx 回填到 **20160104 起全段**(`app/collector/width_history.py:309-344`)。
- 于是 backfill 对几乎所有历史日 skip → `a_width_max_lianban`/`a_width_zhaban_rate`/`a_width_daban_premium` **从未被历史回填**。
- 现存 20260612-20260911 的 akshare 值 = backfill 在 6 月运行当时东财接口还保留的近段历史;更早的被东财清理。

### 2.3 数据源根因:东财涨停池接口历史只滚动保留近段(实测)
`curl push2ex.eastmoney.com/getTopicZTPool?date=<交易日>`(今天 2026-09-30 实测):
| date | tc(涨停数) |
|---|---|
| 20251230 | 0(已清空) |
| 20260611 | 0(已清空) |
| 20260612 ~ 20260901 | 0(全部已清空) |
| 20260911 | 40(保留) |
| 20260916 | 89(保留) |
| 20260928 | 33(保留) |

→ **东财涨停池接口历史仅保留近 ~2-3 周,一年前的历史在东财服务器上已不存在**,akshare 东财源永远补不了一年历史。

### 2.4 width_history.py 为什么没补连板(次要)
`width_history.py` 从 `mootdx_daily_raw` 自算宽度(close>=涨停价×0.999 判涨停),回填 zt/dt/zb/seal_rate/up/down/amount 7 项。**连板需要"连续涨停序列",而 mootdx 历史段(2016-2025)只有 85 只样本股**(见 §3.3),85 只样本推不出全市场最高连板 → 该文件设计上就没做连板。

## 3. 计算口径(平时 max_lianban 从哪来、怎么算)

- **数据源**:东财 `push2ex.eastmoney.com/getTopicZTPool`(akshare 封装 `stock_zt_pool_em`),东财封板池直接给「连板数」字段(lbc)。
- **判定**:`max(涨停池.连板数)` —— 不是自己算涨跌幅规则,连板数是源端统计的"连续涨停天数"。
- 涨停判定规则(主板 10% / 创业板科创板 20% / 北交所 30% / ST 5%):**由东财封板池口径直接给**,不涉及自己判定;实测东财涨停池**不含 ST**(20260928 池内 0 只 ST)。
- 代码锚点:`app/collector/intraday_snapshot.py:1722-1748`(盘中)、`app/backfill.py:48-71`(回填)、`app/compute/sentiment.py:15,32,47-64`(a_sentiment 分项使用)。

## 4. 回补可行性(各源实测边界)

| 源 | 历史可获取性(实测) | 连板数字段 | 结论 |
|---|---|---|---|
| **FAPI limit-up-pool(同花顺官方 API fuyao.aicubes.cn)** | **20210901 起逐交易日可用**(实测 20210901 66 只/连板max7、20220901 41只、20231201 47只、20240115 34只、20250901 116只、20260612 98只、20260928 35只) | `continue_day_cnt` → 映射东财兼容「连板数」(`fapi_fallback.py:61-74`) | ✅ **主回补源** |
| 东财 akshare `stock_zt_pool_em(date=历史)` | 今天实测 20260901 及更早已空,仅近 ~2-3 周 | lbc | ❌ 不能补历史 |
| mootdx 自算(mootdx_daily_raw) | 本地+生产(云上 3 个库一致)历史段 2016-2025 仅 **85 只/天**,2026-07-20 起才全量 5199 只 | 无,需自算连板序列 | ❌ 85 只样本算不出全市场最高连板 |

补充实测:
- FAPI 涨停池**不含北交所**(20260520/20220901 代码前缀 00/30/60/68 无 8x/43/920)。
- FAPI 涨停池**含 ST**(20260701 top=ST中装 7 连板),东财涨停池不含 ST → **回补必须排除 ST**。
- FAPI 炸板池 limit-break-pool 历史:20250915 起有(20250915 27只/20251201 27只/20260612 61只),20250908 及更早 unavailable → zhaban_rate 历史只能补到 ~2025-09 中旬(部分覆盖,备选 mootdx seal_rate 口径)。

## 5. 口径陷阱清单(自算历史连板最易错点 + 本方案怎么防)

| # | 陷阱 | 说明 | 本方案防法 |
|---|---|---|---|
| 1 | **ST 股(致命)** | FAPI 涨停池含 ST(5% 涨停连续天数计入连板),东财不含。20260701 FAPI=7(ST中装)vs 东财当时=3 | **回补前排除名称含 ST 的股票再取 max**。实测排除后 69 天对账从 11 DIFF → 1 DIFF |
| 2 | 东财 vs FAPI 涨停池宇宙差异 | 涨停数有口径差(20260928 FAPI 35 vs 东财 33;20260901 FAPI 80 vs 东财 83),但同日**连板 max 一致**(20260928 都是 5,新华传媒) | 对账以「连板 max」为准,不以涨停数为准 |
| 3 | 一字板/开板 | 连板数由源端统计(一字板封死计入,炸板后回落),不自判 | 直接用源端 `连板数` 字段,不自算 |
| 4 | 除权/复权 | 自算涨跌幅跨除权日失真(width_history 用 pct_change 反推 prev_close 有该问题) | 源端连板数已含复权/除权处理,回补直接用源端值,规避 |
| 5 | 新股首日 | 首日无涨跌幅限制不计涨停 | 源端涨停池不含首日股,天然规避 |
| 6 | 北交所 | FAPI 涨停池实测不含北交所;东财 20260928 也不含 | 口径一致;标注未来若源端混入需复核 |
| 7 | 盘中 vs 收盘 | 现有 77 天含 intraday(盘中快照)值,尾盘炸板可能降连板 | 回补统一用 FAPI 收盘值覆盖重叠段,口径统一;对账时分 source 统计(见 §6) |

## 6. 【天然校验集】对账方案(回补必须过这关)

**现成基准 = 线上 77 天 `a_width_max_lianban`**(本地 69 天同理)。回补脚本对重叠段逐日输出 FAPI 值(排除 ST 后 max 连板),与 daily_metric 现有值比较。

实测结果(本地 69 天全量对账,`fetch_zt_fallback('stock_zt_pool_em', d)` → 排除 ST → max):
| 口径 | DIFF 天数 | 一致率 |
|---|---|---|
| 含 ST 全量 | 11/69 | 84% |
| **排除 ST** | **1/69** | **98.5%** |
| 其中 intraday 段(44 天) | 1/44 | 97.7% |
| 其中 akshare 段(25 天) | 0/25(排除ST后) | 100% |

- 排除 ST 后唯一 DIFF = **20260717**(本地 akshare=5,FAPI=4,FAPI 低 1),根因待查(东财 7/17 数据已清空无法回溯)。
- 双源交叉:东财接口当前还能取的近段(20260911-20260930)可与 FAPI 逐日对照,20260928 已验证 max 完全一致(都=5,新华传媒)。
- **对账跑法**(只读脚本,不写库):遍历重叠段日期 → 逐日 `fetch_zt_fallback('stock_zt_pool_em', d)` → 排除 ST → max(连板数) → 与 `SELECT value FROM daily_metric WHERE metric_id='a_width_max_lianban' AND date=?` 比较 → 输出 DIFF 明细 + 一致率。回补脚本 `--dry-run` 模式即输出此报告。
- 验收线:**排除 ST 口径重叠段一致率 ≥ 98%,唯一允许 DIFF=20260717(需标注)**;若新增 DIFF 天 = 口径错,停下查。

## 7. 产出方案(具体可执行)

### 7.1 数据源与算法
- 源:FAPI `limit-up-pool`(已接好 `app/collector/fapi_fallback.py:92-106` `fetch_zt_fallback('stock_zt_pool_em', date)`,返回东财兼容 df 含「连板数」)。
- 算法:逐交易日 → `fetch_zt_fallback` → `df[~df["名称"].str.contains("ST", na=False)]` → `max(连板数)` → upsert。
- zhaban_rate(附带):逐日 `fetch_zt_fallback('stock_zt_pool_zbgc_em', d)` 得炸板数,FAPI 涨停池行数作涨停数,`zhaban_rate = 炸板/(涨停+炸板)`;**仅 2025-09-15 起可用**(炸板池历史浅),更早部分标注缺口或备选 mootdx `a_width_seal_rate` 换算(口径不同需标注)。

### 7.2 脚本改动建议(实施阶段)
- 新增 `app/backfill_lianban.py`(或扩展 `app/backfill.py`),CLI:
  - `--start=YYYYMMDD --end=YYYYMMDD`(默认 20220101 ~ 今日)
  - `--dry-run`(只算+对账输出,不写库 —— **只读可先验证的中间步骤**)
  - `--skip-existing`(默认 skip 已有非 manual 值)或 `--overwrite`
- 写库:`INSERT INTO daily_metric (date, metric_id, value, source, updated_at) ... ON CONFLICT(date, metric_id) DO UPDATE ... WHERE source != 'manual'`,source=**'fapi'**(新 source 标记,便于追溯与回滚)。
- 重叠段(20260612-今)是否覆盖现有 intraday/akshare 值:建议**覆盖为统一 FAPI 收盘口径**(同口径才能让 a_sentiment 的 lianban 分项全段连续),但覆盖 intraday 盘中值是否允许需用户拍板(§23.7 冻结契约)。

### 7.3 预计耗时与覆盖
- 一年 ≈ 240 交易日,FAPI 串行每日期 ~1-3s → **约 5-10 分钟**;若补 2022-01 起 4 年 ≈ 980 交易日 → 约 30-50 分钟。
- 推荐覆盖:**2022-01-01 起**(FAPI 实测 2021-09 起可用,取 2022 起留足冰点因子 4 年样本),至少满足"一年以上"。

### 7.4 写库目标(需用户授权)
- **生产主库 = 云上 `/home/ubuntu/code/trade-data/data/sentiment.db`**(trade-update-all.service 的 MAIN_REPO,实测该库 max_lianban 77 天)。
- 云上写入 = 生产变更,**必须用户拍板后才执行**;本调研只出方案不执行。
- 其余两库(`/home/ubuntu/code/trade-data-signal/data/sentiment.db`、`/home/ubuntu/code/trade-data-signal-staticdata/db/sentiment.db`)为镜像/export 副本,由现有同步链带出,不单独写(需在实施时确认同步机制,§22 数据一致性)。
- **只读可先验证中间步骤**:本地 mac 开发库(stock_daily.db/sentiment.db 过期副本)或临时 sqlite 库先跑 `--dry-run` 全量对账,输出重叠段一致率 + 全段覆盖日期给用户确认,再谈生产写入。

### 7.5 防前视说明
- 本回补是**数据回补**,不生成信号:历史 max_lianban 是 T 日收盘后统计值,冰点因子 F1=楼层≤4 以 T 日值判定、T+1 生效,不存在未来数据。
- F4 地量若用滚动分位,沿用冰点文档 §3.5 的 expanding/rolling 口径(截至 T 日),不用全期分位。

## 8. 诚实标注

- **读代码确认**:width_history.py 回填 7 指标不含连板(文件全文);intraday_snapshot.py:1722-1748 与 backfill.py:44-73 的采集/skip 逻辑;fapi_fallback.py:61-74 的 continue_day_cnt→连板数映射。
- **实测确认**:东财接口历史保留边界(今天实测 20260911 起,之前全空);FAPI 2021-09 起历史可用;FAPI 含 ST/不含北交所;mootdx 历史 85 只样本;排除 ST 后 69 天对账 98.5% 一致。
- **推断(无法完全验证)**:20260612 为 backfill 当时东财保留窗口边界(东财已清空 20260612 之前数据,无法回溯当时接口实际返回)。
- **无法验证**:
  1. 20260717 唯一 DIFF(FAPI 4 vs 本地 5)根因——东财 7/17 数据已清空,无法回头对比;标注"待实施时人工核对该日涨停池"。
  2. FAPI 涨停池 2021-09 之前的历史边界未测(不影响一年需求;若要 2020 及更早需再实测)。
  3. FAPI 炸板池 2025-09-08 之前的历史边界未测全(已知 unavailable,影响 zhaban_rate 回补深度)。
- **对既有冰点文档的修正**:`docs/research/icepoint-shanghai-trader-20260930.md` §3.4 建议"用 mootdx 全 A 日线连板口径"补历史——本调研实测 mootdx 历史段仅 85 只样本股,**该路径不可行**,正确路径是 FAPI(见 §4)。

## 复现段

每条结论的取得命令/文件:
- 生产实况(77 天):`ssh -i ~/tdsignal.pem ubuntu@122.51.111.173` python3 只读 `SELECT MIN(date),MAX(date),COUNT(DISTINCT date) FROM daily_metric WHERE metric_id='a_width_max_lianban'` 于 `/home/ubuntu/code/trade-data/data/sentiment.db`(3 个库同查,主库 77 天)。
- 本地 69 天对账:`app/collector/fapi_fallback.py` `fetch_zt_fallback('stock_zt_pool_em', d)` 遍历本地 `data/sentiment.db` daily_metric 69 天,排除 ST 后 1/69 DIFF。
- 东财接口保留边界:`curl "https://push2ex.eastmoney.com/getTopicZTPool?ut=7eea3edcaed734bea9cbfc24409ed989&dpt=wz.ztzt&Pageindex=0&pagesize=1&sort=fbt:asc&date=<交易日>"` → tc 字段(20260901 及更早 tc=0,20260911 tc=40)。
- FAPI 历史深度:`fetch_zt_fallback('stock_zt_pool_em', d)` for d in [20210901,20220901,20231201,20240115,20250901,20260612,20260928](全部有数据)。
- mootdx 历史覆盖率:云上 3 个 `stock_daily.db` python3 只读 `SELECT substr(date,1,4),COUNT(*),COUNT(DISTINCT code) FROM mootdx_daily_raw GROUP BY 1` → 2016-2025 每年 85 只 code,2026 年 5200 只(全量起点 20260720,本地测)。
- 代码锚点:`app/collector/width_history.py`(全文)、`app/backfill.py:44,48-71`、`app/collector/intraday_snapshot.py:1722-1748,1812-1848`、`app/collector/fapi_fallback.py:61-74,92-106`、`app/compute/sentiment.py:11-18,47-64`、`app/backfill.py` skip 判据。
