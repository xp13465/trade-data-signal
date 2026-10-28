# R2 上传锁: 按产物域分锁 + 超时梯度(2026-10-28)

任务书 `/tmp/task-r2lock-20261028.md`。台账依据: §22(多展示位一致)+ L55(超时梯度四副本)+ L52(改
`scripts/` 必跑全量 pytest)。机检入口: `python scripts/r2_lock_gradient_audit.py`。

## 0. 一句话

全局单锁 → **按产物域分锁**(域间 key 不重叠 ⇒ 可并行; 同域串行); 未声明域的调用方
**原样回落全局锁**(漏改 = 继续全局串行, 绝不会变成无锁并发); 每个调用方显式给「锁等待上限」,
并保证 **锁等待 < 内层预算 < 外层 systemd 墙**(L55)。

## 1. 改前基线(云上近 30 天, 只读核查日志)

| 指标 | 数值 | 来源 |
|---|---|---|
| 单条「等待 R2 上传锁」最长 | **3990s** | 云上 `data/logs/*` 心跳行, 近 30 天 |
| S06 等锁被杀 | **870s → rc=124** | 10-27 `s06_snapshot` 实况 |
| 锁等待超时(fail-closed)次数 | 1 次 | 同窗口 |
| 归因范围 | 夜间二十多个任务共用一把锁 | `systemctl list-timers` + R2 日志 |

结论: 排队时长由「所有任务串行」决定, 与单任务自身工作量无关 ⇒ 分域是唯一结构解。

## 2. 域划分与对象 key 不重叠证据

| 域 | 写者(命令) | 对象 key 前缀 | 不重叠依据 |
|---|---|---|---|
| `data` | upload-data-large / upload-all-data / upload-intraday / upload-data-files(大载荷) | `data/<顶层文件>` | **大文件通道**取件集合由 `_is_data_large_file` / `_is_all_data_excluded` / 固定 28 文件表互斥 ⇒ 必须同域;**小载荷通道仍跨锁**(8MB 以下的 data-files 走独立小锁, 与 data 域同写 `data/schedule_stats.json`, 既有例外, 见 §2.1) |
| `etf_score` | upload-etf-score | `data/etf_score_list_*.json` | `_DATA_EXCLUDE_PREFIXES` 含 `etf_score_list`, data-large/all-data 共同排除 |
| `kelly_parts` | upload-kelly-parts | `data/signal_kelly_trades_parts/` | `*.json` glob **非递归**, 顶层 data 写者不覆盖子目录 |
| `kelly_sdc` | upload-kelly-parts-sdc | `data/signal_kelly_trades_sdc_parts/` | 同上 |
| `kelly_snapshots` | upload-kelly-snapshots(含 s06 ④b) | `data/signal_kelly_snapshots/` | 同上 |
| `lab` | upload-lab | `lab/` | 专向前缀 |
| `trade_sim` / `trade_sim_data` | upload-trade-sim / -json | `trade_sim/`, `trade_sim_data/` | 专向前缀 |
| `index` | upload-index | `index/` | 专向前缀 |
| `etf` | upload-etf-hist | `etf/` | 专向前缀 |
| `fund_nav` | upload-fund-nav | `nav_bucket/` | 专向前缀 |
| `accum_nav` | upload-accum-nav | `accum_nav/` | 专向前缀 |
| `industry` | upload-industry | `industry/` | 专向前缀 |
| `public_fund` | upload-public-fund | `public_fund/` | 专向前缀 |
| `offshore_fund` | upload-offshore-fund | `offshore_fund/` | 专向前缀 |
| `fund_score` | upload-fund-score | `fund_score/` | 专向前缀(data-large/all-data 排除 `fund_score*`) |
| `backup_db` / `large_json` / `claude_backup` / `decommissioned` | 私有桶备份命令 | `backup/`, `large-json/`, `claude-backup/`, `decommissioned/` | 私有桶前缀, 与公有桶互不相干 |
| `data`(小载荷例外) | upload-data-files 小锁通道 | 命中 `_is_data_large_file` 一律退回全局锁 | 2026-10-23 A 方案既有例外, 本单不改 |

> **为什么 `data` 不能拆细**: **大文件通道** data-large / all-data / intraday 在顶层 `data/*.json`
> 存在真实同 key 重叠, 拆开 = 两个任务同秒写同一 key(last-writer-wins), 比现状更糟 ⇒ 同域串行。
> **小载荷通道(8MB 以下)是例外**: 它走独立小锁、不吃全局屏障, 与 `data` 域仍是**跨锁**写同一个
> `data/schedule_stats.json`(`push_schedule_stats.sh:73`、`intraday_snapshot.sh:232` 的小锁写者
> vs `intraday_snapshot.sh:170` 的 `data` 域 upload-intraday)——**既有问题, 本单只登记不修**, 见 §2.1。

### 2.1 既有「同 key 但不同锁」例外(只登记, 本单不修)

分域只解决「域间 key 不重叠」这一层; 下面两处是**改前就存在**的跨锁同 key 写者, 分域既没新增
也没消除它们。登记在此供后续立项, 不做"顺手修"(任务书明令: 只登记)。

| # | 谁在跨锁写同一个 key | 触发条件 | 风险 | 建议 |
|---|---|---|---|---|
| E-1 | **小载荷通道**: `upload-data-files` 命中「非大文件判据 + 总量 ≤ 8MB」⇒ 走独立小锁 `/tmp/trade_r2_upload_small.lock`(不吃全局 SH 屏障)。写者: `push_schedule_stats.sh:73`、`intraday_snapshot.sh:232`; 同 key 的域锁写者: `intraday_snapshot.sh:170` 的 `R2_UPLOAD_LOCK_DOMAIN=data upload-intraday`(其文件表含 `schedule_stats.json`) | 小锁与小锁之间互斥, **小锁 vs `data` 域锁不互斥**; 8MB 阈值是静态判据, 不感知对手 | 极端时点两者同秒写 `data/schedule_stats.json` ⇒ last-writer-wins(内容都是同一份统计的不同时刻快照, 不会结构损坏, 但可能读到旧一版) | 立项: 给小载荷通道也加一把**与 data 域共享的 SH/EX 关系**(或把小锁并入 data 域的分段); 在合并前维持现状(改动面大于收益) |
| E-2 | **`upload` 子命令是锁豁免写者**: `upload_r2.py:4990` 的取锁门槛 `cmd not in {..., "upload"}` 把 `upload` 排除在锁外。调用方: `app/collector/intraday_snapshot.py:2185` 用它写 `data/sentiment-{rng}.json`, 与 `data` 域 upload-intraday 的文件表同 key | 盘中采集每轮都会跑到; 完全**无锁**并发 | 与 data 域写者同 key 且零互斥; 单文件 PUT 原子, 最坏是"新老两版互相覆盖"(内容同为 sentiment 序列, 不会损坏, 但可能短暂读到上一轮) | 立项: 把 `upload` 子命令并入 data 域(或至少让它持全局 SH 屏障)。**本单不动**: 它属"锁豁免"既有设计, 改动会影响 `--dry-run`/手动补刷语义, 需单独评估 |

> 两处都不是本次分域引入的**, 故 §5 的 E1/E2 观察口径不受影响; 但排障时若看到 `schedule_stats.json`
> 或 `sentiment-*.json` 出现"旧一版", **先怀疑 E-1/E-2**, 不要误判成域锁失效。

## 3. 锁结构(向后兼容模型)

- 声明域: 持 **域锁 EX**(`/tmp/trade_r2_upload_<domain>.lock`)+ **全局锁 SH 屏障**;
- 未声明域: 持 **全局锁 EX**(逐字保持 2026-10-27 行为);
- 全局 EX 与域 SH 互斥 ⇒ 漏改的调用方会挡住全部域写者(安全兜底), 不会与域写者并发;
- 小载荷通道(2026-10-23): 独立小锁, 不吃全局屏障(既有例外; 硬闸门 `_is_data_large_file` 只保证
  它与 **data-large** 同 key 不相交, 与 `data` 域的 upload-intraday **仍同写 `schedule_stats.json`**
  ⇒ 见 §2.1 E-1);
- 域名白名单(2026-10-28 返工): 合法域名的单一事实源 = `scripts/r2_lock_paths.py::LOCK_DOMAINS`
  (20 个)。`upload_r2.py`、排障探针 `r2_lock_probe.py`、审计脚本三者都 import 它, **不手抄第二份**;
  未登记域名 ⇒ 回落全局锁 + WARN(不是报错): 打错字只会退化成串行, 不会自建一把新锁静默失去互斥;
- fail-open(锁文件打不开)/ 等锁心跳 30s / 超时文案 / `SKIPPED_LOCKED` 哨兵语义 **全部不变**;
- 回滚: 不设 `R2_UPLOAD_LOCK_DOMAIN` 即回到全局单锁(无需回滚代码)。

## 4. 三列梯度表(锁等待 < 内层 < 外层; 由审计脚本机检)

| 调用方 | 域 | 锁等待上限 | 内层预算 | 外层 TimeoutStartSec |
|---|---|---|---|---|
| s06_snapshot.sh | data | 600 | 900(run_to) | 7020 |
| s06_snapshot.sh(④b) | kelly_snapshots | 600 | 900(run_to) | 7020 |
| turnover_backfill.sh | data | 1800 | 2760(run_to) | 0(无界) |
| intraday_snapshot.sh | index / data | 600 | 无界 | 0 |
| update_lab.sh | lab / trade_sim_data / data | 600 | 无界 | 0 |
| gold_night.sh | data | 900 | 无界 | 2700 |
| etf_national_team_backfill.sh | etf | 900 | 无界 | 0 |
| fund_nav_upload_async.sh | fund_nav | 1800 | 无界 | 0 |
| pf_score_daily.sh | fund_score | 400 | 无界 | 600(云上实测 1800, 快照记 600 ⇒ 取保守值) |
| pf_score_weekly.sh | fund_score | 1800 | 无界 | 4140 |
| backup_db.sh | backup_db | 9000 | 无界 | 12600 |
| staticdata_backup_async.sh / migrate_large_json_out_of_git.sh | large_json | 3000 | 无界 | 0 |
| update_all.sh | data / etf_score / fund_score | 300 / 600 / 600 | 无界 | 0 |
| kelly_intraday_rerun.sh | data | 400 | 无界 | 600 |
| push_schedule_stats.sh | data | 120 | 无界 | 0 |
| backup_claude_self.sh | claude_backup | 900 | 无界 | 0(本机 cron) |
| fetch_news.py | data | 120 | 180(subprocess+skip 重试) | 1080 |
| gen_daily_brief.py | data | 80 | 120 | 1740 |
| nextday_plan_generator.py | data | 320 | 480 | 600 |
| nextday_gap_check.py | data | 200 | 300 | 1800 |
| overfit_monitor.py | data | 240 | 960 | 360(**既有倒置 #223④, 已豁免**) |
| fapi_bj_width_export.py | data | 600 | 900 | 1800 |
| r2_upload_async.sh 全部通道 | 各域 | 600(verify 6000) | 7200(停滞/硬兜底) | - (systemd-run 瞬时) |

> 内层「无界」= 该脚本对 upload_r2 子进程不设 timeout, 由外层/停滞判据兜底; 审计脚本对此类
> 只校验「显式声明了锁等待上限」, 不强行编造内层预算。

## 5. 验收锚点(E1/E2/E3)与观察口径

| 编号 | 目标 | 本单能自证到哪一步 | 上线后怎么验 |
|---|---|---|---|
| E1 | 等锁单条时长 P100 < 300s | 机制层: 最长锁等待上限从 7300 降到 ≤1800, s06=600; 域间并行已由单测证明 | 上线后 7 天 `grep '等待 R2 上传锁'` 取最大值 |
| E2 | S06 rc=124 不再由等锁引起 | s06 锁等待 600 < run_to 900; 单测钉死字面量 | 观察 s06 退出码与日志等锁秒数 |
| E3 | 锁等待 < 内层 < 外层 | `r2_lock_gradient_audit.py` PASS(**44 PASS / 1 既有豁免, 共 45 行**) | 每次改调用方重跑审计 |

> **调用点计数口径(2026-10-28 返工校正)**: 审计表 `SITES` = **45 行**, 是"登记行数", 不是"取锁
> 调用次数"。按每次 `upload_r2.py` 实际取锁调用展开 = **46 次**, 差 1 的来源: `intraday_snapshot.sh`
> 的「intraday + schedule_stats」一行里写了两次调用(index 是另一行)。**改前那次审计输出的"42 个
> 调用点"是行数**, 且当时把 `update_all.sh` 的 etf_score/fund_score、`update_lab.sh` 的 lab/
> trade_sim_data/data 各合并成一行 ⇒ 那些调用点当时没被单独核对(本次已拆开, 并加机检
> 「脚本内字面量域必须有对应登记行」)。审查报告里的"约 48"是估算, 实测 46, 差异已在此说明。

## 6. 排障探针(超时后「谁占着锁」)

`scripts/r2_lock_probe.py::lock_paths_from_env(include_domains=True)` 返回 22 把锁(全局 + 小锁 +
20 把域锁), `probe_locks` 逐把 `lsof`;**无占用的域锁折叠成一行**(否则 20 行会把日志/告警正文冲垮),
有占用的逐条列出文件名 + 已运行时长。Python 调用方(`nextday_plan_generator` / `nextday_gap_check` /
`gen_daily_brief` / `fapi_bj_width_export`)调诊断时必须带 `include_domains=True`——只探全局/小锁会在
**域锁被占**时指向错误文件(2026-10-28 审查发现, 本单修)。机检: 审计脚本扫 `scripts/*.py` 的
`lock_paths_from_env(` 调用点, 缺 `include_domains=True` ⇒ FAIL。

## 7. 恢复/回滚

- 单任务回滚: 去掉该调用方的 `R2_UPLOAD_LOCK_DOMAIN` ⇒ 该任务回落全局锁(其他任务不受影响);
- 全局回滚: 所有调用方均不设域 ⇒ 等价 2026-10-27 全局单锁;
- 锁文件残留: 内核自动释放, 无需清理; `/tmp` 重启即清。