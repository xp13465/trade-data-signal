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
| `data` | upload-data-large / upload-all-data / upload-intraday / upload-data-files(顶层) | `data/<顶层文件>` | 三者取件集合由 `_is_data_large_file` / `_is_all_data_excluded` / 固定 28 文件表互斥; data-files 与 intraday 在 `schedule_stats.json` 等**有重叠** ⇒ 必须同域 |
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

> **为什么 `data` 不能拆细**: data-large / all-data / intraday / data-files 在顶层 `data/*.json`
> 存在真实同 key 重叠(例如 `schedule_stats.json` 同时被 intraday 与 push_schedule_stats 写),
> 拆开 = 两个任务同秒写同一 key(last-writer-wins), 比现状更糟。故同域串行。

## 3. 锁结构(向后兼容模型)

- 声明域: 持 **域锁 EX**(`/tmp/trade_r2_upload_<domain>.lock`)+ **全局锁 SH 屏障**;
- 未声明域: 持 **全局锁 EX**(逐字保持 2026-10-27 行为);
- 全局 EX 与域 SH 互斥 ⇒ 漏改的调用方会挡住全部域写者(安全兜底), 不会与域写者并发;
- 小载荷通道(2026-10-23): 独立小锁, 不吃全局屏障(既有例外; key 由 `_is_data_large_file` 硬闸门
  保证与 data-large 不相交);
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
| E3 | 锁等待 < 内层 < 外层 | `r2_lock_gradient_audit.py` PASS(41 PASS / 1 既有豁免) | 每次改调用方重跑审计 |

## 6. 恢复/回滚

- 单任务回滚: 去掉该调用方的 `R2_UPLOAD_LOCK_DOMAIN` ⇒ 该任务回落全局锁(其他任务不受影响);
- 全局回滚: 所有调用方均不设域 ⇒ 等价 2026-10-27 全局单锁;
- 锁文件残留: 内核自动释放, 无需清理; `/tmp` 重启即清。