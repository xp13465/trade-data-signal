# #238 `trade-fapi-daily` OOM 代码侧治本(实施报告)

- 日期:2026-10-09
- 分支:`feat/238-fapi-oom-20261009`
- 输入(只读):`docs/ops/fapi-daily-oom-rootcause-20261008.md`(238 行,定因已闭合,未重查)
- 边界:只改 python/脚本/测试。**未碰**云上 systemd unit、swap、主机配置(另一 agent 的活)
- 目标:2026-10-09 18:10 该 unit 下一次触发前落地,否则 3.6GB 小机再冻 ~47 分钟

---

## 1. 三件改动(① 护栏 / ⑤ 口径 / ④ 流式)

### ① 阈值护栏(已先行单独 commit `aeadb9047` 并 push)

| 项 | 值 |
|---|---|
| 文件 | `app/collector/fapi_daily.py` |
| 旧 | `STALE_DAYS = 8`(纯自然日) |
| 中间态(①) | `STALE_DAYS = 21` + env `FAPI_STALE_DAYS` |
| 终态(⑤ 取代) | `STALE_TRADING_DAYS = 10`(交易日)+ env `FAPI_STALE_TRADING_DAYS`(见 §1.2) |

① 的验收口径 = **10-09 的 gap=9(自然日)不再走全量**。已满足:交易日后 gap=2 ⇒ 增量。
`run()` 的 dump 选择在 L431-436:`full or _stale(db_latest_date())`。

### ⑤ 缺口判据改「交易日」口径

| 项 | 内容 |
|---|---|
| 常量 | `fapi_daily.py:75` `STALE_TRADING_DAYS = 10` / `:76` env 名 |
| 读 env | `:391` `_stale_trading_days()`(非法值回退默认) |
| 判据 | `:399` `_stale(latest, *, today=None, trading_days_fn=None)` |
| 复用机制 | `app/calendar.trading_days_between(start, end)`(既有交易历,**未另造**) |
| 收敛条件 | 缺口 > 10 交易日才切 full(旧口径「>8 自然日」) |

理由:`daily-k-10d` dump 本就覆盖最近 **10 个交易日**,自然日口径既过度保守(平常也可能误切全量),
又被长假精确击穿(国庆 8 天休市 ⇒ 节后首跑 gap=8/9 ≥ 8)。交易日口径与 dump 的实际覆盖能力对齐。

### ④ full 路径改流式分块

| 项 | 旧(物化) | 新(流式) |
|---|---|---|
| 读 | `read_table()` → `to_pandas()`(1032万×11 列 Arrow 0.8~1GB + pandas 再复制一份) | `ParquetFile.iter_batches(columns=8列, use_threads=False)` |
| 转 | pandas DataFrame | 逐列 `to_numpy()`(不经 pandas) |
| 分组 | 全局 `sort_values` + `groupby` | 连续段检测(批内)+ 跨批未闭合组缓冲 |
| 映射 | 1032 万 tuple 一次性 list | 逐组映射,逐批回调 |
| 落库 | 一次性 `executemany` | 逐批 `executemany` + `commit` |
| 代码 | — | `:279` `_iter_groups` / `:342` `process_parquet` / `:217` `_map_group` |

关键设计(见 §4 正确性):
- **`pct_change` 是「同组内前一行」依赖**(组内时序前收),不跨组 ⇒ 只要保证**组原子**,即可流式,
  无需全局排序。`_iter_groups` 只放行**已闭合的完整组**,批尾未闭合组缓冲到下一批。
- **守卫(不静默)**:某 thscode 被放行后再次出现 ⇒ dump 未按 thscode 连续分组 ⇒ 抛
  `RuntimeError` 中止,绝不把 `pct_change` 静默算错(`:290-299`)。
- 只读映射实际用到的 8 列(`_COLS`,`:84`),裁掉 currency/interval/adjusted。
- `map_frame()` 保留为 **reference oracle**(`:262`),与流式路径共用同一 `_map_group`(单一语义源,§5.4⑦)。

---

## 2. 内存实测(④ 的验收证据)

**口径说明(重要)**:
- 度量 = `resource.getrusage(RUSAGE_SELF).ru_maxrss`(进程峰值 RSS);macOS 单位=字节、Linux=KB,探针已分别换算。
- 输入 = **真实 10 年全量 dump** `/Users/linhuichen/code/trade/data/daily-k.parquet`
  (10,316,588 行 / 181MB / 2 个 row group:7,650,100 + 2,666,488)。
- **全部在本机跑,未在云上跑 full 路径**(按派单约束)。
- 每模式独立子进程(ru_maxrss 是进程级峰值,不能同进程先后测两种)。

| 模式 | 峰值 RSS | 备注 |
|---|---|---|
| **旧全量物化(legacy)** | **2786 MB** | 复现 #238 前路径(`read_table → to_pandas → map_frame`) |
| **流式 bs=10000(定稿)** | **290 / 242 / 290 MB**(3 次) | 中位 **290MB** |
| 流式 bs=5000 | 289 MB | |
| 流式 bs=2000 | 287 MB | |
| 流式 bs=20000 | 292 MB | |
| 流式 bs=50000 | 307 MB | 上一版默认 |
| **纯读地板(只 `_iter_groups` 不映射)** | **284 MB**(bs=5000) | 见下 |
| row group 0 的 8 列**未压缩**体积 | 183 MB | pyarrow 解码对象 |

**结论**:峰值 **290MB < 300MB 目标达成**;相对旧路径 **≈ 9.6x 降幅**。

**诚实标注(地板从哪来)**:峰值**主要不由 `BATCH_SIZE` 决定**,而由 **pyarrow 解码的最大 row group**
决定 —— 纯读不映射也有 284MB 地板;映射只额外加 ~6MB。也就是说:
- 本文件 8 列未压缩 183MB(rg0 占 765 万行)是**硬地板**,来自 pyarrow 的 row-group 级解码缓冲,不是我们的代码;
- **上游若改用更大的 row group,地板会随之上移**(风险量化:若 10.3M 行挤进单个 row group,地板约 1.35x ⇒ ~380MB,
  仍在定因报告 §6.4 的「<500MB」验收内,但会突破 300MB 目标);
- 我们无法控制上游 dump 的 row group 划分,故以「实测 290MB + 打印 row 数/批大小」交底。

**全量映射耗时与批大小无关**:1032 万行 ~29s(bs=5000/20000/50000 各 29.2/28.5/29.3s)⇒ 取小批不牺牲时间。

**复现命令**:
```
# 流式(bs 省略则 100000)
/Users/linhuichen/code/trade/.venv/bin/python3 scripts/tests/fapi_oom_mem_probe.py stream <daily-k.parquet> 10000
# 旧路径对照
/Users/linhuichen/code/trade/.venv/bin/python3 scripts/tests/fapi_oom_mem_probe.py legacy <daily-k.parquet>
# 输出:PEAK_RSS_MB=<n> BASELINE_MB=<b> ROWS=<r>
```

---

## 3. 防前视声明(§5.1⑥,三条机检)

| 机检 | 本次结论 | 证据 |
|---|---|---|
| ① 分位数阈值禁用全期分位 | **N/A** —— 本改动无分位数阈值;阈值 = 交易日**计数**(常数 10 + env 覆盖) | `fapi_daily.py:391,399` |
| ② 复用既有特征库先核查固化口径 | **PASS** —— 复用 `app/calendar.trading_days_between`(项目既有交易历,固化口径),未另造;其口径 = akshare `tool_trade_date_hist_sina` 落 `data/trade_dates.txt`,**闭区间 [start,end]** | `app/calendar.py:90-100` |
| ③ 时点穿越测试 | **PASS** —— `_stale` 显式闸门 `latest < d <= today_s`,**只统计 (latest, today] 区间**;即便注入含未来日期的完整日历,判定不变 | 测试 `test_stale_lookahead_gate_ignores_future_days`(带**反证**:无闸门会数出 11 > 10 ⇒ 误判 full,即该用例能真正区分「有/无闸门」);另 `test_stale_lower_bound_excludes_latest_day` 验下界 |

口径一句话:t 时点判定**只用 t 之前**(库内 latest)与 **(latest, t]** 的日历,不使用任何 t 之后的数据;
判定在运行当次生效(t = 运行日)。

---

## 4. 正确性:流式 == 旧物化(不是「图省事切片」)

- 差分对账:`process_parquet` 输出 **逐位等于** `map_frame`(reference oracle),批大小
  `[1, 7, 13, 120, 999]` 全覆盖(含**跨批切组**、含**单组跨多批**的累积分支)。
- 样本来自**真实产物**:`scripts/tests/fixtures/238/sample.parquet`(真实 FAPI dump 切片,
  120 行 / 4 个 thscode / 11 列;`turnover>volume` 占比 100% ⇒ 顺势验证「成交额↔换手率」命名坑守卫)。
- 防御断言与旧全量口径**等价**:主键重复判据由「组内 `date_ms` 去重」承载(重复项必共享 thscode ⇒ 必同组);
  `|turnover|>|volume|` 占比 <0.9 即拒绝映射。
- 组内若乱序(异常数据)按 `date_ms` 稳定排序后再算 `pct_change`,不假定 dump 完美排序。

---

## 5. §23.2 同类错误面清单(全仓扫描「大表全量物化」)

扫描口径:全仓 `grep -rn "read_table|read_parquet|ParquetFile|iter_batches|read_row_group|to_pandas"`,
排除 `.git / static-site / node_modules / data`。

| # | 位置 | 现状 | 判定 |
|---|---|---|---|
| 1 | `app/collector/fapi_daily.py` full 路径 | `read_table → to_pandas → sort → 1032 万 tuple` | **已修**(本任务,唯一生产物化点) |
| 2 | `docs/fapi/scripts/probe_fapi.py:83,87` | `read_table + to_pandas` 本地小 dump | **不改**:docs 下只读探针,**无任何 unit/链路调用**;文件量级小;非生产入口 |
| 3 | 其余全仓 | 除上述 **0 命中** | — |
| 4 | 其他大表采集(mootdx/baostock 等) | 走 SQLite 行级写入,**不经过 parquet 全量物化** | 不改 |

**根因修而非逐文件打补丁**:病灶只有一处(单点),修在该点;扫描证实没有第二处需要同款补丁。

---

## 6. §23.3 举一反三(同模式 / 同数据源 / 同组件 / 展示位)

| 类别 | 对象 | 核对结果 | 处置 |
|---|---|---|---|
| **同数据源**(FAPI) | `app/collector/bj_width.py`(`load_bj_daily` 读 `fapi_daily_raw`) | 读 **SQLite 窗口**、非 parquet 物化;其 `days=35` 是 **lookback+buffer**(保证首日 prev_close),**不是 staleness/触发口径**;属 #101 已完成功能(冻结资产 §23.7) | **不改** |
| **同链脚本** | `scripts/fapi_daily_syn.sh`(18:10 链式 wrapper) | 直接 `"$PY" -m app.collector.fapi_daily`,**不带 env** ⇒ 完全依赖**默认阈值**;故默认值必须长假安全(本改动默认 = 交易日 10)✓ | **不改**(已核对无需改) |
| **同模式**(「恒定阈值 + 自然日」家族) | `scripts/check_data_integrity.py:57-58` `STALE_DAYS_WARN/FAIL`(前端产物滞后告警)、`scripts/check_data_gap_alerts.py:130` `NORTH_STALE_DAYS=14`、`static-site/app.js` `const STALE_DAYS=30`(卡片陈旧标记) | 语义**不同**:这些是**告警/展示陈旧标记**,不是「触发某个昂贵动作」的判据(北向那条还显式写了「长假断档 11 天 < 14 不误报」= 已考虑长假) | **不改**(跨语义,非同一 bug;且属已发布行为 §23.7) |
| **同常量登记点** | `STALE_DAYS` 全仓引用 | 生产代码仅 `fapi_daily.py`;前端 `STALE_DAYS` 是**同名不同物**(独立常量),已识别 | 已 grep 确认无遗漏登记点 |
| **展示位/下游** | `fapi_daily_raw` → 前端/邮件/`bj_width`/双源互证 | 本改动**不改表结构、不改行格式、不改字段口径**;只改「何时走 full」与「怎么读」⇒ 数据内容与旧路径逐位一致(§4) | **零影响** |

---

## 7. 自测结果

| 项 | 结果 |
|---|---|
| **Red-first**(把 `main` 版 `fapi_daily.py` 换回工作区,跑**本任务新测试**) | **15 failed / 1 passed**(唯一 pass = `_stale(None)/坏日期` 的兼容性断言) |
| 修复版 | **16 passed**(`scripts/tests/test_fapi_oom_fix_20261009.py`) |
| **全量 pytest** | `python3 -m pytest -q scripts/tests/` → **400 passed / 2 skipped / 90.19s**;collect 402。**基线(去本任务新增 16)= 384 passed / 2 skipped** |
| **零外发**(§18 L48) | 测试只调纯函数 + 本地 parquet;不 import notify/不触网络。内存实测走的独立子进程只读本地文件。**未跑任何通知/告警脚本,未产生真实外发** |
| 样本真实性(§18 L49) | fixture = 真实 dump 切片;内存实测 = 真实 1032 万行全量 dump |
| 备注 | 本机 macOS + Python 3.11 + pyarrow 25.0.1 + numpy 2.4.6;**本地绿 ≠ CI(Ubuntu)绿**;CI 无真实 dump/交易历缓存 ⇒ 两条重量级用例自动 skip |

---

## 8. 诚实标注 / 需主控-用户拍板的分叉

1. **与「契约原文推荐口径」的偏离(需知会)**:`docs/fapi/fapi-integration-plan-20260901.md:110` 记
   「10 日增量落后 **>7 自然日** → 切全量(契约原文推荐口径)」—— 即旧的 8 自然日源自上游契约文本。
   本任务按派单把口径改为**交易日 >10**。**方向已由派单给定**,此处仅标注「与上游契约文本不一致」这一事实,
   供用户决定是否需要在与厂商的对接文档里同步说明。该日期化 plan 文档**未改**(历史记录)。
2. **300MB 目标的边界**:实测 290MB,**非「任意 dump 都 <300MB」的保证** —— 地板随上游 row group 大小浮动(§2);
   若上游改成单一大 row group,预计 ~380MB。定因报告 §6.4 的择优验收(「<500MB」)仍有余量。
3. **`_stale` 的语义变化**:库内日期不可解析仍保守走 full(自愈),不变;空库走增量,不变。
   变的是「缺口多少才走 full」——**动到了已发布行为**(§23.7),按派单执行。
4. **未做**:云上 unit 的 `MemoryHigh/MemoryMax`、swap 扩容 —— 明确属另一 agent 的边界,本 agent 未触碰。
5. **env 命名**:`FAPI_STALE_TRADING_DAYS`(旧 `FAPI_STALE_DAYS` 随 ① 中间态弃用;因 ① 与 ⑤ 同分支同日,
   不保留旧名兼容层;`fapi_daily_syn.sh` 不带 env,无迁移负担)。

---

## 9. 复现段(报告四件套)

- 本体:`docs/ops/fapi-daily-oom-fix-20261009.md`(本文)
- 代码:`app/collector/fapi_daily.py`(+ `scripts/tests/test_fapi_oom_fix_20261009.py` / `fapi_oom_mem_probe.py` / `fixtures/238/sample.parquet`)
- 复现命令:见 §2 与 §7(探针 + pytest)
- 配套 commit:`docs(ops): #238 落档 + 实施(⑤ 交易日口径 + ④ 流式分块)`(本分支 tip,见交接)