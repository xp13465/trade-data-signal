# #238 `trade-fapi-daily` OOM 代码侧治本(实施报告)

- 日期:2026-10-09
- 分支:`feat/238-fapi-oom-20261009`
- 输入(只读):`docs/ops/fapi-daily-oom-rootcause-20261008.md`(238 行,定因已闭合,未重查)
- 边界:只改 python/脚本/测试。**未碰**云上 systemd unit、swap、主机配置(另一 agent 的活)
- 目标:2026-10-09 18:10 该 unit 下一次触发前落地,否则 3.6GB 小机再冻 ~47 分钟
- **续跑轮(2026-10-09)**:处置独立审 `docs/ops/fapi-daily-oom-fix-review-20261009.md` 的
  **Finding 1(守卫时序:写后检 → 已修为两遍扫描「写前检」)** + 建议 2/3/4(删死代码 /
  黄金 fixture 对账 / 历史文档口径注记)。详见 **§1(①)/§2/§4/§10**。

---

## 1. 改动(① 护栏 / ⑤ 口径 / ④ 流式 / ① 守卫时序[续跑轮])

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

### ① 守卫时序修复 —— 两遍扫描(续跑轮,reviewer Finding 1)

问题(独立审 Finding 1):流式版把 `dup` / `amt_ok` 校验挪到**逐批 commit 之后**(`:342-367` 尾部),
校验不过时**前面几批已落库**——语义比 #238 前(写前检 ⇒ 零写入)变坏。

修法(采纳审查建议 a:**两遍扫描**,`process_parquet`):

| pass | 函数 | 动作 | 写库 |
|---|---|---|---|
| pass1 | `scan_parquet(path, *, batch_size)` | 流式**只统计** dup / amt_ok / rows(**不映射**) | **否** |
| pass2 | `process_parquet` 内联循环 | 流式逐组 `_map_group` → 回调 `on_rows` | 逐批 upsert |

- 校验不过 ⇒ pass1 直接 `raise` ⇒ pass2 从不执行 ⇒ **回调零触发、库零行**(恢复写前检语义)。
- `run()` 的写连接 `_flush` **首写才 `get_conn()`**(`conn=None` 起)⇒ 过检前连 WAL pragma 都不发生。
- **内存不退化**:pass1 **列裁剪**为 `_GUARD_COLS`(4 列,不需 OHLC),解码缓冲 ≈ 单遍的一半,
  故「pass1+pass2」合计峰值不高于单遍流式(实测见 §2 尾)。
- 代价:full 路径多读一遍 parquet(≈ +20s),memory 不变。

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

**续跑轮(两遍扫描)复测**——确认「过检才写」不把峰值抬回去:

| 模式 | 峰值 RSS | 备注 |
|---|---|---|
| 单遍 pass1(只 `scan_parquet`,4 列裁剪) | **210 MB** | 列裁剪后所需地板 |
| 单遍 pass2(只映射+回调) | **287 MB** | 与旧单遍流式同 |
| **两遍(定稿 `process_parquet`)** | **298 / 299 / 300 MB**(3 次) | 与单遍 290MB 同级(±8MB) |
| 未裁剪 pass1 的两遍(对照,已弃) | 310 MB | 未裁 4 列 ⇒ pass1 地板 286 ⇒ 合计偏高 |

**结论**:峰值 **~298MB < 300MB 目标达成**(容差 320);相对旧路径 **≈ 9.4x 降幅**。
两遍扫描因 pass1 列裁剪,合计峰值与单遍流式同级(290→298MB,~+3%),未退回物化量级。

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
- **黄金 fixture 对账(续跑轮,reviewer 建议 3)**:`fixtures/238/expected_rows.json` 冻结
  **pre-#238 旧实现**(`map_frame`)在真实切片上的输出,新流式逐位 == 它 —— 该锚**独立于当前
  生产 `_map_group`**(旧实现 vs 新实现不共享代码),`_map_group` 若漂移立即红。生成器
  `scripts/tests/gen_fapi_golden_238.py`(`--check` 可复算来源,md5 闸门锁版本)。
- 样本来自**真实产物**:`scripts/tests/fixtures/238/sample.parquet`(真实 FAPI dump 切片,
  120 行 / 4 个 thscode / 11 列;`turnover>volume` 占比 100% ⇒ 顺势验证「成交额↔换手率」命名坑守卫)。
- **守卫时序(续跑轮修正,原审查 Finding 1)**:`dup` / `amt_ok` 断言口径与旧全量**等价**
  (主键重复判据由「组内 `date_ms` 去重」承载 —— 重复项必共享 thscode ⇒ 必同组;
  `|turnover|>|volume|` 占比 <0.9 即拒绝映射),**且校验时机已恢复「写前检」**:由 `scan_parquet`
  (pass1)先行判定,**不过 ⇒ 零映射零写库**(见 §1「① 守卫时序修复」)。旧流式版「逐批写完后尾部判」的写后检语义已消除。
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
| 修复版(第 1 轮) | **16 passed**(`scripts/tests/test_fapi_oom_fix_20261009.py`) |
| **全量 pytest** | `python3 -m pytest -q scripts/tests/` → **400 passed / 2 skipped / 90.19s**;collect 402。**基线(去本任务新增 16)= 384 passed / 2 skipped** |
| **零外发**(§18 L48) | 测试只调纯函数 + 本地 parquet;不 import notify/不触网络。内存实测走的独立子进程只读本地文件。**未跑任何通知/告警脚本,未产生真实外发** |
| 样本真实性(§18 L49) | fixture = 真实 dump 切片;内存实测 = 真实 1032 万行全量 dump |
| 备注 | 本机 macOS + Python 3.11 + pyarrow 25.0.1 + numpy 2.4.6;**本地绿 ≠ CI(Ubuntu)绿**;CI 无真实 dump/交易历缓存 ⇒ 两条重量级用例自动 skip |

### 续跑轮(两遍扫描 + 黄金 fixture)自测

| 项 | 结果 |
|---|---|
| 新增用例 | **11**(守卫时序 4 + pass1 统计 1 + 黄金 fixture 6[bs×5 + map_frame 1] —— 含 skipif 的那条本机跑实) |
| `test_fapi_oom_fix_20261009.py` | **27 passed**(16 + 11) |
| **全量 pytest** | `python3 -m pytest -q scripts/tests/` → **411 passed / 2 skipped / 87.58s**(基线 400 + 11) |
| **内存不退化** | 探针 `stream` bs=10000 × 3:**298 / 299 / 300 MB**(第 1 轮 290MB 级);pass1 列裁剪后 p1=210/p2=287,合计与单遍同级(§2 表) |
| **red-first(区分度实测)** | ①**未修复流式版**(tip `21d0cc9b9`)喂坏 dump:回调**先触发 121 行**后才 raise ⇒ 守卫断言 `seen==[]` 必红;②改 `_map_group`(pct 四舍五入到 2 位)⇒ 流式与 `map_frame` **均 != 黄金** ⇒ 黄金测试红;③**pre-#238 版**无 `process_parquet`/`scan_parquet` ⇒ 两测试 AttributeError 必红 |
| 零外发(续跑) | 新增 `test_run_writes_zero_rows_on_bad_dump` 把 `DB_PATH`/`_DATA_DIR`/下载全 monkeypatch 到 tmp,**不碰生产库、不触网络** |

---

## 8. 诚实标注 / 需主控-用户拍板的分叉

1. **与「契约原文推荐口径」的偏离(需知会)**:`docs/fapi/fapi-integration-plan-20260901.md:110` 记
   「10 日增量落后 **>7 自然日** → 切全量(契约原文推荐口径)」—— 即旧的 8 自然日源自上游契约文本。
   本任务按派单把口径改为**交易日 >10**。**方向已由派单给定**,此处仅标注「与上游契约文本不一致」这一事实,
   供用户决定是否需要在与厂商的对接文档里同步说明。该日期化 plan 文档**原文保留**,已追加一行口径注记(见 §10.4)。
2. **300MB 目标的边界**:实测 ~298MB(两遍扫描),**非「任意 dump 都 <300MB」的保证** —— 地板随上游 row group 大小浮动(§2);
   若上游改成单一大 row group,预计 ~380MB。定因报告 §6.4 的择优验收(「<500MB」)仍有余量。
3. **`_stale` 的语义变化**:库内日期不可解析仍保守走 full(自愈),不变;空库走增量,不变。
   变的是「缺口多少才走 full」——**动到了已发布行为**(§23.7),按派单执行。
4. **未做**:云上 unit 的 `MemoryHigh/MemoryMax`、swap 扩容 —— 明确属另一 agent 的边界,本 agent 未触碰。
5. **env 命名**:`FAPI_STALE_TRADING_DAYS`(旧 `FAPI_STALE_DAYS` 随 ① 中间态弃用;因 ① 与 ⑤ 同分支同日,
   不保留旧名兼容层;`fapi_daily_syn.sh` 不带 env,无迁移负担)。

---

## 9. 复现段(报告四件套)

- 本体:`docs/ops/fapi-daily-oom-fix-20261009.md`(本文)
- 代码:`app/collector/fapi_daily.py`
- 测试:`scripts/tests/test_fapi_oom_fix_20261009.py`(27 例)/ `fapi_oom_mem_probe.py`
- 黄金 fixture:`scripts/tests/fixtures/238/expected_rows.json`(pre-#238 旧实现冻结输出)
  - 生成/复算:`python3 scripts/tests/gen_fapi_golden_238.py [ref] [--check]`(md5 闸门锁版本)
- 输入样本:`scripts/tests/fixtures/238/sample.parquet`(真实 dump 切片)
- 复现命令:见 §2 与 §7(探针 + pytest + `gen … --check`)
- 配套 commit(本分支,未碰 main):见 §10 尾「commit 链」

---

## 10. 审查 Findings 处置清单(续跑轮,对照 `fapi-daily-oom-fix-review-20261009.md`)

| # | 审查项 | 处置 | 证据 |
|---|---|---|---|
| **Finding 1** | 守卫由「写前检」变「写后检」(异常时已落库) | **已修**:两遍扫描(`scan_parquet` pass1 只统计 → 通过后 `process_parquet` pass2 才映射/写),不过 ⇒ 零映射零写库;`run()` 写连接首写才开 | §1「① 守卫时序修复」/ 测试 `test_process_parquet_guard_blocks_all_rows_on_*` / `test_run_writes_zero_rows_on_bad_dump`;red-first:「未修复流式版回调先触发 121 行」 |
| 建议 2 | 删死代码 `upsert_rows()` | **已删**(全仓 `git grep upsert_rows` 确认 fapi 版零调用方;其余同名均在各自模块内) | `app/collector/fapi_daily.py`(该函数已移除) |
| 建议 3 | 黄金 fixture 固化(防 `_map_group` 漂移) | **已固化**:`fixtures/238/expected_rows.json` + 生成器 `gen_fapi_golden_238.py`(`--check` 复算);测试 `test_streaming_equals_golden_fixture`(bs×5)+ `test_map_frame_equals_golden_fixture` + 来源可复算断言 | 见 §4 / §7 |
| 建议 4 | 20260901/20260902 两份历史文档加口径注记 | **已加**(各一行,原文保留):`docs/fapi/fapi-integration-plan-20260901.md:111` / `docs/fapi/fapi-p0-implementation-20260902.md:39` | grep `自然日` in `docs/fapi/` = 仅此两处(§23.3 全覆盖) |
| 建议 5 | Python 层 nan vs None(DB 等价) | **no-op**(审查已证落库无差,不处理) | 审查报告 §② |

**commit 链(本分支 `feat/238-fapi-oom-20261009`,未碰 main)**:第 1 轮 `21d0cc9b9`(⑤ 交易日口径 + ④ 流式分块)
→ 续跑轮(本轮):① 两遍扫描 + ② 删死代码 + ③ 黄金 fixture + ④ 文档注记 + 本报告更新。

---

## 11. 续跑轮 §23.2 同类错误面 / §23.3 举一反三

**§23.2 同类错误面(「写后检」家族)**:本模块唯一的**数据行写入口**= `_flush`(`:474-475`
`executemany`+`commit`),现仅由 pass2 触发 ⇒ pass1 过检前不存在任何数据写入。
`app/collector/fapi_daily.py` 内 `grep "executemany\|conn.commit()"` 仅此一处(另 `init_db` 的
commit 是 DDL,非数据行,与 #238 前一致)。**无第二处需同款补丁**。

**§23.3 举一反三(同模式/同数据源/同组件/展示位)**:

| 类别 | 对象 | 核对结果 | 处置 |
|---|---|---|---|
| **同组件**(两遍扫描复用者) | `_iter_groups` 现接受 `columns` 参数(默认 8 列) | pass1 用 `_GUARD_COLS`(4 列)裁剪;pass2/`map_frame`/探针默认 8 列不变 | 兼容(默认值=旧行为) |
| **同链测试** | `fapi_oom_mem_probe.py` 的 `stream` 模式 | 走 `process_parquet`(现两遍),仍只读、量级不变(§2 表) | 不改 |
| **同数据源下游** | `bj_width` / 宽度 / 双源互证读 `fapi_daily_raw` | 行内容逐位不变(黄金 fixture 4 路径全等),零影响 | 不改 |
| **同口径文档** | `docs/fapi/` 全目录 `grep 自然日` | 命中恰 2 处(20260901 + 20260902),均已加注记;其余(定因报告/审查报告)是**历史记录**,保留 | 已覆盖 |
| **同常量登记点** | `FAPI_STALE_*` / `STALE_*` 全仓 | 见第 1 轮 §6(生产代码仅本文件;前端同名不同物) | 无新增 |

**§23.4**:`docs/pending-features-index.md` #238 条目为本模块唯一在办项(无同模块并行任务冲突);
状态列仍「待拍板…均未实施」已过时,merge 收尾按 §23.12-1 刷新(主控流程,非本 agent 边界)。