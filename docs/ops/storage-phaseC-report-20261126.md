# 存储治理 C 阶段 实施报告(旧库归档退役)

- 执行时间:云上 2026-11-26 09:00–14:40 CST(实际墙钟);本报告定稿 14:45 CST
- 任务书:`/tmp/task-storage-phaseC-20261126.md`;方案 C 段:`/tmp/codex-reports/claude-storage-cleanup-20261124-execution-plan.md`
- 昨夜复核:`/tmp/storage-recheck-20261125.md`;B 阶段工具链参考:`/tmp/storage-phaseB-report-20261125.md`
- 权威源:云上 `/home/ubuntu/code/{trade-data-signal,trade-data,trade-data-signal-staticdata}`
- 云上工作目录(全部中间产物可复核):`/home/ubuntu/storage-governance/phaseC-20261126/`

## 0. 三行结论

1. **依赖清查**:可动 2(etf_national_team、public_fund,C 根副本)/ **停 1**(C 根 sentiment.db-shm,有每日生产读者)/ 保留 2(两个 stock_daily,任务书点名、SHA 不同)。
2. **释放量**:退役释放 **3,224,285,184B(3.0027GiB 文件字节;allocated/df 实增 3,221,463,040B = 3.0004GiB)**,df 可用 16,337,039,360 → 19,558,502,400B(根卷 74% → 68%)。
3. **三态**:归档=R2 复用核验 PASS(未重传)/ 隔离=已执行(13:06:59)/ 退役=**已完成**(14:11:38 etf、14:13:33 public_fund),C 根 6 个目标路径现全部不存在且未重建。

## 1. 第 0 步 依赖清查(闸门)逐文件证据

判定口径:任何读者/写者/定时任务仍引用该文件 ⇒ 该项停。检查面 = ①两树源码 grep ②deploy/启动脚本 ③systemd unit + timer 快照 ④`/proc/*/fd` 瞬时打开者 ⑤atime/shm mtime 侧证。

| 文件 | 判定 | 证据 |
|---|---|---|
| C `data/etf_national_team.db`(+wal/shm) | 可动 | 云上 unit `WorkingDirectory=/home/ubuntu/code/trade-data`、`REPO=/home/ubuntu/code/trade-data`;采集入口 `etf_national_team_backfill.sh` 用 `python -m app.collector.etf_national_team` 在 cwd=D 下导入,`__file__` 为 D 路径 ⇒ 模块内 `_DATA_DIR = Path(__file__).parent.parent.parent/"data"` 解析到 **D/data**(非 C);`app/queries.py`/`alert_score.py` 的 `_REPO` 同理随启动路径落 D;隔离前 `/proc/*/fd` 命中 0。实证:D/data/etf_national_team.db 11-26 13:57、14:27 仍在被写(现役库正常),C 副本 10-28 后未变。 |
| C `data/public_fund.db`(+wal/shm) | 可动 | 同上;`trade-public-fund-daily.service` 与 `trade-public-fund-full/quarterly/estimation` 全部 `WorkingDirectory=D`、`REPO=D`、入口 `public_fund_daily.sh` 用 `python -m app.collector.public_fund`,模块内 `DB_PATH=_DATA_DIR/"public_fund.db"` ⇒ **D/data**;`export_fund_score.py` 用 `SCRIPT_DIR.parent`(从 D 调用 ⇒ D);隔离前 FD 命中 0。实证:D/data/public_fund.db 存在(3,323,805,696B)且今日 07:06 有写。 |
| C `data/sentiment.db` + `-shm` | **停(整项冻结)** | `gen_daily_brief.pick_db` / `brief_ledger._pick_db` / `aggregate_shadow._pick_db` 会遍历候选仓(env REPO→GIT_REPO→MAIN_REPO→默认),对每个仓的 `data/sentiment.db` 真开 sqlite 只读取 `MAX(date)` ⇒ 每日会打开 C 旧库;C/sentiment.db-shm mtime 每日 21:15 前进(11-25 21:15 实测),为生产读者铁证。 |
| C `data/stock_daily.db`、S `db/stock_daily.db` | **保留**(未动) | 任务书点名两个 SHA 不同(`fb948a75…` / `36546e24…`),分别保留;本轮未做任何 stat 之外的操作。 |

附:与 `scripts/deploy.sh` 原注释「代码仓 data/*.db 云上零读取方」冲突的点仅限 sentiment(pick_db 家族),已写入残余风险 §6;etf/public_fund 的采集都走 D,注释结论对这两个成立。

## 2. 第 1 步 SHA 重核(变了就停该项)

| 文件 | 11-26 复核 SHA256 | vs 昨夜/方案 | size |
|---|---|---|---|
| C `data/etf_national_team.db` | `62a47ffc614934f97111a7685c892c45a9a6d76147d1cade9b9d777d023f547f` | **相同** | 258,400,256 |
| C `data/public_fund.db` | `b5095b10f141632e7b34d4e73e3662f6901954e9c4ced9a0b64b583403973f95` | **相同** | 2,965,819,392 |

未变化 ⇒ 允许继续。原始记录:`sha-recheck.txt`(云上工作目录)。

## 3. 第 2 步 归档(复用 B 阶段对象,不重传)

方案 §5.2 允许「已有完全匹配归档」直接复用。两个文件 SHA 与 B 阶段归档对象逐位相同,故只做**核验**不做重传:

- 脚本:`verify-archive.py`(复用 phaseB-archive.py 的小写 `range` 分片修复)
- 输出 `verify-archive.json`:**ALL_PASS = True**
  - HEAD 200 且 `Content-Length` == 本地 size(两文件)
  - 3 点 × 1MiB 分片按小写 `range` GET,逐字节与本地一致(两文件)
  - 隔离副本 `mode=ro&immutable=1` `PRAGMA quick_check` = ok
- 归档 key:
  - `db-archive/v1/old-db-20261125/62a47ffc…3f547f/etf_national_team.db`
  - `db-archive/v1/old-db-20261125/b5095b10…73f95/public_fund.db`
  - 桶:第二账号 `signal-backup2`

## 4. 第 3 步 同卷隔离(2026-11-26 13:06:59)

- 脚本 `quarantine.py` 前置校验:普通文件 / nlink=1 / 同设备 / 与 manifest SHA 一致 / 无 `/proc/*/fd` 打开者 / WAL=0 / 无 `-journal` / 目标不存在。
- 执行:同卷 `rename(2)` 主库 + sidecar 到 `quarantine/`,重核 (ino,size,mtime_ns) 后写 `quarantine-manifest.json`(tmp+fsync+os.replace+目录 fsync,含 orig/quarantine/dev/ino/size/mtime_ns/sha256/restore_cmd)。
- 入口 `quarantine/` 全部改为存放 6 个文件并随即被第 5 步 unlink;manifest 3763B 保留。
- 快照:C/data 六路径在本步后全部 absent(见第 5 步观察)。

## 5. 第 4 步 自然轮观察(隔离后)

观察脚本 `observe2.py`(只读),PASS 口径:①每个监控 unit `Result=success` 且最后一次主进程 start/exit ≥ 隔离时刻 ②6 个源路径仍 absent ③当前无进程持隔离路径 FD ④journal(自隔离时刻起)无 DB 打开/缺表/I-O 错误行。

`rounds-observed.json`:**PASS = true**(2026-11-26 14:09 采集)

| unit | Result | start | exit | 在隔离后 |
|---|---|---|---|---|
| trade-ops-monitor.service | success | 14:00:06 | 14:00:11 | 是 |
| trade-self-heal.service | success | 14:07:00 | 14:07:01 | 是 |
| trade-schedule-monitor.service | success | 14:00:00 | 14:00:42 | 是 |
| trade-check-monitor-heartbeat.service | success | 13:56:00 | 13:56:00 | 是 |

- `source_paths_absent`:6/6 true,`recreated` 为空
- `fd_holders_now`:{}
- `journal_suspicious_lines`:0

**诚实标注(边界)**:
- 首版 observe.py 用 `systemctl show --value` 取字段,而 systemd 按自身属性顺序输出(不是请求顺序),导致字段错位、误报 PASS=false;已改为 key=value 解析并重跑。首版错报不作为证据。
- 覆盖的是**监控/自愈/心跳**类自然轮(每 5–60 分钟一轮),**未覆盖**当日日更写库任务(16:20/17:00 public-fund-daily、20:07 etf-national-team)。这两个任务经第 0 步核到写目标是 **D/data**(unit WorkingDirectory/REPO 均为 D,`-m` 导入使 `__file__` 落 D),因此不构成 C 根退役的阻塞条件;但**今日尚未观察其跑完**,列入残余风险 §6,不宣称已被自然轮完全证明。

## 6. 第 5 步 退役 + 释放量 + 恢复路径

退役前置(retire.py 内建 gate,任一不成立即 STOP):`rounds-observed.json` 存在且 PASS → 逐主库重算 SHA 且等于 manifest → R2 `HEAD` key 200 且长度 == size → 隔离副本 `immutable` quick_check=ok → 无 FD → 才 unlink 主库+sidecar → 目录 fsync → 追加 `retire-20261126.jsonl`。

| 项 | 退役时刻 | 文件 | 释放字节 | R2 归档 key | quick_check |
|---|---|---|---:|---|---|
| etf_national_team | 14:11:38 | .db 258,400,256 / -wal 0 / -shm 32,768 | 258,433,024 | `db-archive/v1/old-db-20261125/62a47ffc…3f547f/etf_national_team.db` | ok |
| public_fund | 14:13:33 | .db 2,965,819,392 / -wal 0 / -shm 32,768 | 2,965,852,160 | `db-archive/v1/old-db-20261125/b5095b10…73f95/public_fund.db` | ok |
| **合计** | | 6 文件 | **3,224,285,184** | | |

- `df_avail`:before 16,337,039,360B → after 19,558,502,400B,**delta +3,221,463,040B**(与文件字节差 2,822,144B 为目录/元数据/其他并发写入的净影响);根卷使用率 **74% → 68%**。
- `quarantine/` 现存 0 文件;`retire-20261126.jsonl` 已 fsync(2 条 retire 记录 + 1 条 summary)。
- 退役后复核(14:36):C/data 下 6 个路径全部 absent;D/data 现役 `etf_national_team.db`(264,368,128B,14:27 仍在写)、`public_fund.db`(3,323,805,696B)、`sentiment.db`(237,723,648B,14:35 仍在写)**均未被触碰**。

### 恢复路径(§25④,写不出恢复路径=不算可逆)

对每个已退役库:
1. 从第二账号备份桶取回(凭据在云上 `.env`,不进命令行):
   `R2 GET signal-backup2:<r2_key> -> <orig>`(orig 见 `retire-20261126.jsonl` 的 `files[].orig`)
2. 取回后先核 SHA256 == 记录值(etf `62a47ffc…`、public_fund `b5095b10…`),不符即停
3. 再 `chown ubuntu:ubuntu`,确认无 `.db-wal`/`.db-journal` 残留,方可启动读者
4. 替选恢复:隔离副本已 unlink,不再有本地副本,唯一可恢复源 = R2 归档对象(HEAD 长度与抽样已在 3 步核过;B 阶段对同一 SHA 做过全量分片回读 PASS)

## 7. 残余风险与后续

1. **C 根 sentiment 仍冻结**:`pick_db` 家族每日打开 C 旧库(21:15 左右)。建议后续把 pick_db 候选仓收敛到 D(或显式排除 C 根),再评估 sentiment 退役;在那之前不要动 C/sentiment.db 与 -shm。
2. **日更写库任务未当日观察**:16:20/17:00 public-fund-daily、20:07 etf-national-team 写目标是 D 树(已核 unit 与环境变量),但今日未等其跑完;如后续发现 C/data 下同名库被重建 ⇒ 立即按 §23.11 上报,不要静默处理。
3. **deploy 回涨机制仍在**:`deploy.sh` rsync 仍把 D 的 `.r2-protected` 抄进 C 且无 `--delete`(昨夜复核 §5),C 根会继续净增;本 C 阶段释放的 3GiB 不代表趋势反转,机制问题需另批修。
4. **GC 卡死未治**:C 根 `check_capacity` 在 unlink 前按全量 9286 文件/10.7GB 判定 > 8192 文件 / 2GiB cap ⇒ 永远 UnsafeWrite;本轮未动 GC。
5. **S 树同 SHA 副本未动**:S/db 下的 etf/public_fund 与 C 同 SHA,属 B 阶段三份静态副本口径范围之外的 C 阶段清单,本批**未删**,留给后续批次按备份策略决策。

## 8. 举一反三 / 同类面覆盖(§23.3)

| 同模式/同数据源点 | 是否覆盖 | 处置 |
|---|---|---|
| S 树 `db/etf_national_team.db`、`db/public_fund.db`(同 SHA) | 已识别 | 本批不删(任务书 C 段范围=C 根),已在 §7.5 登记 |
| C 根 `data/sentiment.db` + `-shm` | 已识别 | 有读者 ⇒ 冻结,已写入 §7.1 |
| C 根 `data/stock_daily.db`、S 树 `db/stock_daily.db`(SHA 不同) | 已识别 | 保留不删(任务书点名) |
| C 树 `.r2-protected`(部署镜像) | 已识别 | 属 A 阶段范围,本批未动 |
| 代码内其他写 C/data 的路径(collector 模块、queries、alert_score) | 已逐个核 | 运行期均随 cwd/`__file__` 落 D;唯一例外是 pick_db 家族(已冻结 sentiment) |
| 备份工具对已退役文件的引用(`backup_db.sh` 的 etf_national_team) | 已核 | 脚本读 `$DBDIR`(=D/data)备份,不读 C;退役不影响备份链 |

## 9. 边界维度清单(§5.8① 实施关出口,七轴)

| 轴 | 测/不测 | 说明与来源 |
|---|---|---|
| 输入域(文件身份) | 测 | 普通文件/nlink=1/同设备/SHA 匹配/WAL=0/无 journal;quarantine.py 逐项 gate,retire.py 二次重算 SHA |
| 状态组合(隔离/退役/归档) | 测 | 隔离→观察 PASS→退役 三态顺序由 retire.py gate 强制;缺观察文件或 PASS=false 即 STOP(代码内建) |
| 时序(谁在什么时点读/写) | 测(有缺口) | 监控轮 13:56–14:07 全 success;21:15 每日读者只涉 sentiment(已冻结);16:20/20:07 日更写库当日未观察,见 §7.2 |
| 上下游依赖(采集→库→导出) | 测 | 采集入口路径解析逐层核到 D;export_fund_score/backup_db.sh 读 D;退役后 C 路径不存在不影响链路 |
| 极端值(大文件/慢 quick_check) | 测 | 2.9GB public_fund 的 SHA 重算 + quick_check 耗时约 115s,后台化+轮询完成,未触发超时中断 |
| 回退路径 | 测 | R2 HEAD+长度+3 点抽样 + B 阶段同 SHA 全量回读 PASS + 隔离副本 quick_check;恢复命令写进 manifest/JSONL |
| 并发与重入 | 部分测 | retire.py 单次运行、无锁;若并发重跑,首文件 unlink 后 `exists` 检查会 STOP(不会误删第二份);生产侧并发写已由 FD/WAL 前置挡 |

## 10. 产物与复核入口(云上 `/home/ubuntu/storage-governance/phaseC-20261126/`)

| 文件 | 用途 |
|---|---|
| `sha-recheck.txt` | 第 1 步 SHA 复核原始输出 |
| `verify-archive.json` | 归档复用核验(ALL_PASS) |
| `verify-archive.py` | 归档核验脚本(可重跑) |
| `quarantine-manifest.json` | 隔离清单(6 文件 ino/size/mtime_ns/sha256/restore_cmd) |
| `quarantine.out` / `quarantine.log` | 隔离执行日志 |
| `observe2.py` / `observe2.out` / `rounds-observed.json` | 自然轮观察(PASS) |
| `retire.py` / `retire.out` / `retire.log` | 退役执行与门控 |
| `retire-20261126.jsonl` | 退役凭据(逐项 sha/R2 key/释放字节/恢复命令 + summary) |

报告文件:`/tmp/storage-phaseC-report-20261126.md`;进度文件:`/tmp/agent-progress-storage-phaseC.md`。

[DONE] C 阶段收口:可动 2/停 1/保留 2;隔离 13:06:59 + 观察 PASS + 退役 14:11–14:13;释放 3,224,285,184B(3.0027GiB);恢复路径=R2 signal-backup2 归档对象(先核 SHA 再落回原路径)。
