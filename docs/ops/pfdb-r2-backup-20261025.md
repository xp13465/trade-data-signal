# public_fund.db 补 R2 异地备份(2026-10-25)

> 分支 `feat/pfdb-r2-backup-20261024`(base `origin/main` `8edf7936f`);代码提交 `41df2ff0b`(主体)、`cdc25ee22`(边界用例)、`4f5e3ca1f`(保留期常量崩溃修复)。本文记录首备份实测、从 R2 拉回校验、保留期/容量口径、恢复步骤与「验证了什么/没验证什么」。

## 1. 背景(实测依据)

- 云上 `public_fund.db` = **2,921,410,560 B(2.9G)**;原有三份拷贝(trade-data/data、trade-data-signal/data、trade-data-signal-staticdata/db)**全在同一块 59G 盘**,盘毁即全失。
- `scripts/upload_r2.py` 的 `cmd_upload_db` 原先只备份 `sentiment.db` + `etf_national_team.db`,但 `docs/r2-deployment.md:61` 已写「DB 只靠 R2 signal-backup2 备份」——**文档与代码不符**。
- public_fund 是 WAL 模式库(`-wal`/`-shm` 伴生),不能 `cp` 正在写的库上传,也不能像小库那样整库读进内存(云主机 RAM 3.7G)。

## 2. 改动点(文件:行号)

| 位置 | 改动 |
|---|---|
| `scripts/upload_r2.py:3198` `_backup_public_fund_db` | 大库链路:`未变更跳过(台账 size+mtime_ns)` → `sqlite3.Connection.backup` 在线一致快照(含未 checkpoint 的已提交事务) → 4MiB 分块流式 gzip → 分片流式 multipart 上传 → 周/月副本 → 备份后再 stat 比对(期间被写则不记台账) |
| `scripts/upload_r2.py:3171` `_sqlite_snapshot_to_gz` | 快照 + 流式压缩,峰值内存恒定;临时 gz 成功/失败都清理 |
| `scripts/upload_r2.py:939` `_upload_multipart_file` / `:951` `_upload_file_to_key` | 文件分片流式上传(阈值 100MB、片 64MiB、4 worker),不整文件进内存;原内存版 `_upload_multipart` 行为不变 |
| `scripts/upload_r2.py:3033` / `:3053` | 大库周/月副本:按 ISO 周 / 年月判重后上传本地 gz |
| `scripts/upload_r2.py:3147` | 保留期按对象覆盖:`backup/ 7` + `weekly/ 28` + `monthly/ 180` 天 |
| `scripts/upload_r2.py:3299` `cmd_upload_db` 尾部 | 纳入 public_fund(源库不存在则不计入分母);`DB 上传 N/N` 含大库;失败非零退出 |
| `scripts/tests/test_pfdb_r2_backup_20261025.py` | 10 条打桩用例:清单含 public_fund 且原两项 gzip 内容不变、未变更跳过、缺库不计失败、分片偏移、内存 multipart 回归、WAL 未 checkpoint 事务进快照、per-name 清理、真实入口清理回归、上传 500 不写台账、备份期间源库变化不写台账 |
| `docs/r2-deployment.md:59-63` §1.3 + §4.2 表 | 文档纠偏:写明 public_fund 2.9GB/2,921,410,560 B、独立链路、7/28/180、未变更跳过、WAL 快照 |
| `docs/site-deployment.md:468`、`docs/agent-quickstart.md:77`、`docs/backup-restore.md:20-27` | 配套备份清单/恢复说明同步 |
| `.gitignore:45` | 台账 `data/.r2_db_backup_state.json` 与 `.tmp` 不进 git |

`sentiment.db` / `etf_national_team.db` 的 key 形态、内存 gzip 单 PUT 上传方式、14/28/365 保留期均未改(测试 ① 断言两者 gzip 解压后仍逐字节等于原库)。

## 3. 首次全量备份实测(云上)

- 启动:2026-10-25 **00:26:00**(安全窗内、非交易日;`systemctl list-timers` 无并发 R2 上传;走全局锁,未用 `--skip-if-locked`)。
- 结束:日志最后写入 **01:35:59**(state 台账 `01:35:58`),全链路 **约 70 分钟**;其中三份上传按轮询观测约各 21-25 分钟(轮询粒度 60s,±1 分钟)。
- 产物(三份同一 gz,ETag 相同):

| key | 大小 | ETag |
|---|---|---|
| `signal-backup2/backup/public_fund_20261025.db.gz` | 790,650,717 B | `"c86a454f1ada3dfedb4ec6ab628da5e5-12"` |
| `signal-backup2/weekly/public_fund_20261025.db.gz` | 790,650,717 B | 同上 |
| `signal-backup2/monthly/public_fund_20261025.db.gz` | 790,650,717 B | 同上 |

- 源库 2,921,410,560 B → gz 790,650,717 B(压缩至 27.1%,约 754MiB/份)。
- 吞吐:三份合计约 2.37GB / 全程约 70 分钟 ⇒ **平均约 0.55-0.59 MB/s**(单份约 0.57MB/s;跨境到 R2,与既有小库上传同量级)。
- 首跑暴露并修复一个 bug:三份上传完成、台账已写后,分层清理步 `_PUBLIC_FUND_RETENTION_DAYS` 结构写错(int vs `{name: days}`)致 `AttributeError`(日志 traceback 在 `/tmp/pfdb-upload-20261025.log` 尾部)。**备份本体未受影响**(三对象齐全、大小一致);修复提交 `4f5e3ca1f`,新增真实入口回归用例 `test_prune_r2_backup_consumes_public_fund_retention`。
- 二次运行(修复后脚本,md5 `ca084e45883b7affbcbeeb570ff47b8b`)验证跳过与清理正常,日志 `/tmp/pfdb-upload-2.log` 01:43:01:

```
public_fund.db 自上次备份(20261025)未变更, 跳过(省 2786MB 上传)
删除旧 signal-backup2/backup/etf_national_team_20261011.db.gz
删除旧 signal-backup2/backup/sentiment_20261011.db.gz
DB 上传 3/3 -> signal-backup2/backup/ (20261025)
```

- 定时化就绪(云上只读核对):`trade-backup-db.timer` 每日 **21:00**(`systemctl list-timers` 显示下次 2026-10-25 21:00),unit `trade-backup-db.service` `ExecStart=backup_db.sh`、`TimeoutStartSec=12600`(3.5h);`update_all.sh` 已不再串接备份(`update_all.sh:450` 写明移除,避免双跑)。首备全程 70 分钟 < 3.5h;此后源库未变则跳过,变了单次约 23-25 分钟,仍在窗口内。
- 相邻任务(2026-10-25 02:39 `systemctl list-timers --all` 实测,不是凭印象):20:40 `trade-daily-brief`、20:45 `trade-brief-push`、**21:00 `trade-backup-db`(本任务)**、21:15 `trade-ab-direction-anchor`、21:50 `trade-freeze-orphan-cleanup`、22:00 `trade-public-fund-full`、22:30 `trade-update-all`、23:20 `trade-r2-consistency`;**没有 21:20 / 21:30 的 timer**。
  - 会与本任务抢 **R2 全局锁 `/tmp/trade_r2_upload.lock`** 的:①**21:10 `trade-turnover-backfill`(`OnCalendar=Mon..Fri *-*-* 21:10:00`,工作日触发;节假日是否空跑由脚本自身判定,未在本次核对范围)**,`turnover_backfill.sh:177,182` 直接跑 `upload-intraday` / `upload-data-large`;本任务常态 21:00-21:25 与之重叠约 15 分钟,靠全局锁串行(谁先拿谁先跑,等锁有超时预算,不会并发上传)。②**22:00 `trade-public-fund-full`** 与 **22:30 `trade-update-all`** 走 `deploy.sh`,而 `deploy.sh` 自己跑 4 条 `upload_r2` 命令,也受同一把锁约束;常态 21:25 前本任务已结束,不重叠(若某天 public_fund 变慢拖到 22:00 后,则由锁串行兜底)。
  - 不碰 R2 上传锁的:20:40/20:45 两个简报任务、21:15 `ab-direction-anchor`、21:50 `freeze-orphan-cleanup`(本地 `sentiment.db`)、23:20 `r2-consistency`(只读核对)。依据:`grep "upload_r2\|upload-\|export.py\|deploy.sh"` 上述脚本无命中;`upload_r2.py` 取锁单点 `_acquire_lock_for_command` 对 `upload-db`/`upload-data-large`/`upload-all-data` 等一律走全局锁(仅 `upload-data-files` 按载荷路由小锁)。

## 4. 从 R2 实际拉回校验(PASS)

方法:HEAD 取大小 → **24 个 32MiB Range GET 全量拉回**(6 线程,峰值内存约 192MiB)→ 记录源库当前 size/mtime 并与备份台账比对(证明源库自上传后未变)→ 用**与上传同一方法**(sqlite3 在线 backup)生成参考快照 → 解压拉回对象 → 整文件 md5 + 头/尾各 50MiB md5 逐位比对 → 两边各跑 `PRAGMA integrity_check`。结果(原文 `/tmp/pfdb-verify/result.json`):

| 检查项 | 结果 |
|---|---|
| HEAD | 200,Content-Length 790,650,717 == 台账 `gz_size` |
| 全量拉回 | 790,650,717 B / 24 分片,与 Content-Length 一致 |
| .gz md5 | `a646700817576b12afac807560f16440` |
| 源库自备份后未变 | true(size 2,921,410,560 与 mtime_ns 均同台账,无 `-wal`) |
| 解压后整库 md5 | 拉回 `17a55d86f2ea9234044be150c36df87d` == 参考快照 `17a55d86f2ea9234044be150c36df87d`,2,921,410,560 B |
| 头 50MiB md5 | `155fcfbde2ccf1adc48754e1b8c4fca5`(两边一致) |
| 尾 50MiB md5 | `0ef1bd8a78cb7647dd576d4d1da80838`(两边一致) |
| integrity_check | 拉回 `ok` / 参考 `ok`;page_count 713,235、page_size 4096、19 张表(两边一致) |
| 耗时 | 01:47:5x 启动 → 01:56:24 出结果(约 8.5 分钟;下载约 2 分钟,6 线程约 6MB/s) |

小结:**R2 上的对象能完整拉回,内容与上传时刻的一致快照逐位相同,库结构完整可打开。**

### 验证了什么 / 没验证什么

- 已验证:对象存在与大小、全量拉回字节数、整库与参考快照逐位一致、头尾 50MiB 抽样一致、`integrity_check=ok`、页数/页大小/表数与参考一致、三份副本(日/周/月)同一 ETag。
- 已验证(间接):恢复出的库能被 sqlite3 正常打开并跑完整性检查;`--verify-against-src` 模式下脚本会拒绝「源库已变」时对账(本地打桩用例覆盖)。
- **未验证**:①整机磁盘全毁后在新机器「装环境→恢复库→跑采集/导出/前端」的端到端演练(本次只到文件级恢复 + 完整性检查);②2.9GB 从 R2 恢复的实际耗时(下载约 2 分钟为实测,解压/落盘未单独计时);③7/28/180 天滚动清理的跨天/跨月实跑(仅单测覆盖);④R2 账号实际出账金额(下节为估算);⑤WAL 场景下「恢复后继续被采集进程写入」的并发行为(恢复文件本身无 `-wal`,已含上传时刻全部已提交事务)。

## 5. 保留期、容量与成本(估算)

- 保留期:日 7 份 + 周 28 天(约 4 份)+ 月 180 天(约 6 份)= **17 份 × 0.79GB ≈ 12.8GB**(稳态);小库按 14/28/365 不变(约 2-4GB)。
- R2 免费额度按**账号合计** 10GB(非单桶)。该独立账号原存量约 2.0GiB,加 public_fund 稳态后总量约 **15-17GB**,超出部分约 5-7GB,按 $0.015/GB-month 估算 **每月约 $0.08-0.11**(不到 $0.15)。实际以账单为准。
- 不沿用 14/28/365 的原因:最高会到约 25GB,且每日全传 0.79GB 无额外恢复价值。

## 6. 恢复步骤(流式,别用 download-db 拉大库)

`scripts/upload_r2.py download-db` 是「整对象 GET 进内存 + `gzip.decompress`」,public_fund 会同时驻留 0.79GB + 2.9GB,云主机 3.7GB RAM 有 OOM 风险,**不适用于大库**。用 `docs/scripts/restore_r2_db_backup.py`:

```bash
# 恢复最新一份(输出 <out-dir>/public_fund_YYYYMMDD.db + 同名 .gz + result.json)
# 先确认磁盘余量 ≥ gz(0.79GB) + 解压后(2.9GB)
python3 docs/scripts/restore_r2_db_backup.py --name public_fund --out-dir /home/ubuntu/restore

# 带对账:与源库当前状态生成的参考快照逐位比对(额外再占 2.9GB)
python3 docs/scripts/restore_r2_db_backup.py --name public_fund --out-dir /tmp/verify \
    --verify-against-src /home/ubuntu/code/trade-data/data/public_fund.db
```

脚本做的事:Range 分片流式下载(默认 32MiB/片、6 线程)→ 大小校验 → 流式解压 → `integrity_check`;`--verify-against-src` 时再生成参考快照做整库 + 头尾 50MiB md5 对账。**恢复文件写在 out-dir,不要直接覆盖生产库**;确认 integrity 后再停采集/写库进程替换,旧库先留一份。

## 7. 边界维度清单(七轴,实施方交审查关的输入端)

> 供 reviewer §10.8「先不看本清单、自己再推一份」独立复核对账。判定口径:测=有自动化用例/实测证据;不测=写明理由。

| 轴 | 涉及点与来源 | 判定 |
|---|---|---|
| ① 输入域 | 源库缺失/为空、WAL 未 checkpoint、台账缺失或损坏(来源:§23.2 同类错误面 + 首备实测) | **测**:缺库不计入分母(用例③)、WAL 未 checkpoint 的已提交事务仍进快照(用例⑥);**不测**:台账文件损坏/不可读 → 代码按「无台账」处理(try/except → 空 dict),理由:失败方向是「重新上传」,只会多传不会漏传,且非本 feat 新增数据结构 |
| ② 状态组合 | 非交易日首备、源库自上次备份变/未变(来源:首备实测 + 定时化) | **测**:首备在非交易日实跑通过;未变跳过(用例②+二次运行日志 `跳过(省 2786MB 上传)`);变则重传(用例⑨) |
| ③ 时序 | 同日重跑、备份期间源库被写、跨日 key、清理发生在上传之后(来源:首跑 prune 崩溃事故) | **测**:同日重跑跳过(用例②/二次运行);备份期间被写不记台账,下一轮重传(用例⑨);清理按前缀+日期在整批上传成功后执行(用例⑦/⑦b 真实入口) |
| ④ 上下游依赖 | R2 PUT 失败、周/月副本判重、`_prune_r2_backup` 消费保留期常量、`backup_db.sh`→`upload-db` 调用链(来源:首跑崩溃 + 定时化核对) | **测**:PUT 500 → 非零退出且不写台账(用例⑧);周/月判重(二次运行实证);保留期结构被真实入口消费(用例⑦b);**不测**:`backup_db.sh` 端到端(改的是 `upload_r2.py`,shell 调用未变,已在云上实跑两轮) |
| ⑤ 极端值 | 2.9GB 源库、0.79GB gz、12 分片、临时目录剩余空间不足(来源:首备实测 + 磁盘预检代码 `upload_r2.py:3219-3222`) | **测**:真实 2.9GB 全链路上传+拉回;分片偏移(用例④);**不测**:磁盘不足预检分支无单测,理由:纯前置判断(打印并 `return False`),不影响数据正确性;**已知真实触发**:2026-10-25 云上拉回校验留了 `/tmp/pfdb-verify` 约 6.2G,根盘余量降到 2.5G < 预检需要约 3.81G ⇒ 当晚 21:00 备份会打印「空间不足放弃」;需清理目录后恢复(非代码缺陷,属运维留痕) |
| ⑥ 回退路径 | 上传失败后的下一轮重传、恢复脚本失败/源库已变拒绝对账、大库误用 `download-db`(来源:§23.2 + 恢复手册) | **测**:失败不写台账(用例⑧);恢复脚本「源库已变则拒绝对账」失败路径本地打桩 PASS;**不测**:整机盘毁端到端演练(见 §4「没验证什么」①) |
| ⑦ 并发与重入 | 与 21:10 `turnover-backfill`、22:00/22:30 deploy 链抢 `/tmp/trade_r2_upload.lock`;同任务重入(来源:list-timers 实测) | **测**:首备与二跑均走全局锁实跑;锁互斥逻辑属既有机制(`_acquire_lock_for_command`),本 feat 未改锁;**不测**:专门造并发上传用例,理由:锁实现未改动,且失败语义是排队等锁而非数据损坏;另见 §3 相邻任务时点表 |

## 8. 复现与测试

- 全量测试:`python3 -m pytest -q scripts/tests/` → **1396 passed, 2 skipped**(245.57s,改动提交后跑)。
- 新增用例:`python3 -m pytest -q scripts/tests/test_pfdb_r2_backup_20261025.py` → 10 passed。
- 本地打桩验证恢复脚本:临时脚本 `/tmp/test_restore_script_20261025.py`(不随仓),覆盖单分片端到端 + 多分片(4 片)偏移拼接 + 「源库已变则拒绝对账」失败路径,均 PASS;脚本全文见 `docs/scripts/restore_r2_db_backup.py`。
- 云上执行日志:`/tmp/pfdb-upload-20261025.log`(首跑)、`/tmp/pfdb-upload-2.log`(二跑跳过验证)、`/tmp/pfdb-verify.log` + `/tmp/pfdb-verify/result.json`(拉回校验)。