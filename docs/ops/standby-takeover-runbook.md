# 备用机接管 / 云回滚 / 回切手册(骨架)

> 版本:2026-11-15 · 状态:**骨架 + 当前能力实测** · 本手册只写步骤与验证点;本文写作过程对云上**只读**(未做任何写操作)。
> 关联:`docs/backup-restore.md`(DB 灾备权威)、`scripts/standby_sync.py`(备用机同步工具)、`scripts/backup_state_capture.py`(状态集捕获)。

---

## 0. 先看这一条:现在能不能接管

**不能。** 2026-11-15 实测结论(证据见 §9):

| 环节 | 实测状态 |
| --- | --- |
| 云上状态集捕获 | **未启用**(云上无 `data/backups/state-capture-sets/`,备份 unit 的 `Environment` 无 `STATE_CAPTURE_ENABLED=1`,备份日志里也搜不到捕获字样) |
| R2 同步源 `standby/manifest_latest.json` | **不存在**(只读 GET 得 `NoSuchKey`) |
| R2 状态集归档 `backup/state_*` | **0 个对象** |
| 生成同步清单的代码 | **仓库内没有**(全仓 grep `manifest_latest` 只命中 `standby_sync.py` 自己的默认值两处) |
| 备用机同步工具的 R2 下载 | **两个缺陷未修**(TLS 无 CA / SigV4 签名首步反序,详见 §9) |
| 本机 launchd 定时 | **未安装**(在 D6 批,需与用户约定后另行执行) |

所以:**第 4~6 章是骨架 + 前置条件清单**。前置条件没齐之前,拿本手册当"可执行"用会踩空。
今天真正可恢复的只有:R2 `backup/` 日备里的几个 DB、`large-json/` 大 JSON、staticdata 备份仓(git)。
**冻结表、采集游标、发布状态、通知状态这些"接管必需状态"目前零归档。**

---

## 1. 名词(说人话)

| 名词 | 意思 | 在哪儿看 |
| --- | --- | --- |
| 云端主生产 | 唯一生产节点(云上 systemd timer 跑采集/发布) | `ssh` 云上 `systemctl list-timers` |
| 本机备用 | 这台 Mac,平时只做同步与演练,不写生产 | 本仓 + `~/trade-standby/` |
| 恢复集合 | 一次捕获产出的"成套状态"(清单 + 文件) | 云上 `data/backups/state-capture-sets/`(尚未产出) |
| `latest_verified` | 本机"最近一次验证通过"的版本指针 | `~/trade-standby/archive/latest_verified` → `versions/<vid>` |
| `versions/<vid>` | 固化的版本目录,内含 `verify_record.json` | 同上 |
| `db_cutoff` | 三个库 `MAX(date)` 取最小 = **所有库共同覆盖到哪天**;**接管/缺口一律以它为准** | 集合 `manifest.json` |
| `common_business_cutoff` | 集合内"最新触点"(文件业务日期优先、mtime 兜底) | 同上;**含 mtime 触点,不能当数据截止日** |

---

## 2. 第 0 步:先判断"能不能接管"(本机,只读)

```bash
cd /Users/linhuichen/code/trade
python3 scripts/standby_sync.py status
```

判定表(任一条命中 = 不能宣称"可接管"):

| 看到什么 | 结论 | 处置 |
| --- | --- | --- |
| `latest_verified: "(none)"` | 本机没有已验证版本 | 先补同步链路(§9),别谈接管 |
| `latest_recovery_point_age_days` > 2 | 恢复点过期(工具默认 `--stale-days 2`) | 先核对云端备份是否还在产,再决定是否用旧点 |
| 集合 `complete=false` | 集合有缺项 | 按 manifest `missing` 逐项补齐,**不许缩表凑成功** |
| `all_databases_covered=false` 或库 `max_date` 为空 | 无法对应业务截止日 | 不得宣称完整可接管 |

> 2026-11-15 实测:该命令输出 `latest_verified: "(none)"`、`versions: []`(退出码 0)。

---

## 3. 停同步(本机侧)

**当前状态**:本机**没有**装备用机同步的 launchd 任务(实测 `launchctl list | grep -c standby` = `0`),所以现在"停同步"无事可做。

装好之后(D6 批)按下面停,标签名以 D6 定案为准:

```bash
# 查有没有在跑(把 <标签> 换成 D6 安装时的真实标签)
launchctl print gui/$UID/<标签>

# 停掉调度
launchctl bootout gui/$UID/<标签>
```

验证点:
- `launchctl print gui/$UID/<标签>` 报 `Could not find service` ⇒ 已卸下。
- 正在跑的实例**不要强杀**:脚本内有 `flock` 单实例锁,同机再起会以退出码 3 退出;等当前实例自己结束即可,看 `~/trade-standby/logs/standby_sync_YYYYMMDD.log` 最后一行。
- 停完再跑一次 `python3 scripts/standby_sync.py status`,确认 `last_success_ts` 不再前进。

**需不需要用户拍板**:不需要(纯本机、只读/停调度,不碰云端)。

---

## 4. 云端回滚(把 DB 恢复回云上生产路径)

> **整个第 4 章必须用户拍板后执行**(写生产库、停生产任务)。

第 1 步:登录云上(进入交互 shell):

```bash
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173
```

第 2 步:停写(防恢复过程中定时任务又写库)。四个写库任务 + 备份任务:

```bash
sudo systemctl stop trade-update-all.timer trade-intraday-snapshot.timer \
     trade-etf-national-team.timer trade-lab-auto.timer trade-backup-db.timer
```

验证点:逐个查 `systemctl is-active trade-update-all.timer trade-intraday-snapshot.timer trade-etf-national-team.timer trade-lab-auto.timer trade-backup-db.timer` ⇒ 五行都应是 `inactive`。注意:只停 timer 只挡"以后不再触发",正在跑的 service 不会被中断;要连当前这轮也停,再 `sudo systemctl stop <对应>.service`(会截断当前任务,需用户点头)。

第 3 步:把当前库改名留一份(出事能回滚):

```bash
cd /home/ubuntu/code/trade-data/data
mv sentiment.db sentiment.db.broken.$(date +%Y%m%d_%H%M)
```

验证点:`ls -l sentiment.db.broken.*` 能看到刚改名的那份,大小与原库一致。

第 4 步:取备份并落位。小库用 `download-db`,大库(public_fund)用流式脚本(整对象 GET 会 OOM):

```bash
# 小库(在云上仓库根跑;输出解压后的 .db 绝对路径)
.venv/bin/python scripts/upload_r2.py download-db sentiment /home/ubuntu/restore
.venv/bin/python scripts/upload_r2.py download-db etf_national_team /home/ubuntu/restore
.venv/bin/python scripts/upload_r2.py download-db stock_daily /home/ubuntu/restore

# 大库 public_fund(先确认输出盘余量 ≥ gz + 解压后约 2.9GB)
python3 docs/scripts/restore_r2_db_backup.py --name public_fund --out-dir /home/ubuntu/restore

# 落位
cp /home/ubuntu/restore/sentiment_YYYYMMDD.db /home/ubuntu/code/trade-data/data/sentiment.db
chmod 644 /home/ubuntu/code/trade-data/data/sentiment.db
```

验证点:每一步都看**实际文件路径 + 字节数**,不要只看"退出码 0"。

第 5 步:删旧 WAL/SHM(旧 WAL 会和新库打架):

```bash
rm -f /home/ubuntu/code/trade-data/data/sentiment.db-wal \
      /home/ubuntu/code/trade-data/data/sentiment.db-shm
```

第 6 步:恢复后自检(有一条不过就别起 timer):

```bash
sqlite3 /home/ubuntu/code/trade-data/data/sentiment.db "PRAGMA integrity_check;"   # 期望 ok
sqlite3 /home/ubuntu/code/trade-data/data/sentiment.db "SELECT COUNT(*) FROM score_daily; SELECT COUNT(*) FROM signal_daily;"
```

验证点:`integrity_check` = `ok`;关键表行数与昨日同量级(数量级不对 = 恢复错版本,停下查 `download-db` 取的是哪天的 key)。

第 7 步:恢复调度:

```bash
sudo systemctl start trade-update-all.timer trade-intraday-snapshot.timer \
     trade-etf-national-team.timer trade-lab-auto.timer trade-backup-db.timer
```

验证点:`systemctl list-timers --all | grep trade` 里 `NEXT` 列有值(`trade-update-all` 次日 22:30 等)。

> 更细的 DB 恢复背景(保留层级、周/月归档、public_fund 特殊口径)见 `docs/backup-restore.md` 第三、五、六章;本章只列接管时要照着敲的那几条。

---

## 5. 人工接管(本机顶到生产角色)——骨架

**前置条件(缺一不可,缺了就停):**

1. 有**已验证**的恢复集合:`python3 scripts/standby_sync.py status` 的 `latest_verified` 不是 `(none)`,且 `~/trade-standby/archive/versions/<vid>/verify_record.json` 存在。
2. 集合 `manifest.json` 里 `complete=true`、`all_databases_covered=true`、`db_cutoff` 有值。
3. 云端已冻结(第 4 章第 2 步),且**明确记录冻结时点**。
4. 凭据走受控渠道人工配置;**集合归档里不含 `.env`/密钥**(捕获脚本有拒绝面,接管时也不要往里塞)。
5. 用户明确拍板"从 X 时点起由本机接管"。

**步骤骨架(前置条件齐了才展开):**

1. 记录冻结时点与 `db_cutoff` → 缺口区间 = `db_cutoff + 1 天` 到冻结时点(见 §7)。
2. 从 `latest_verified` 取集合,恢复到**隔离目录**先验(不直接覆盖任何生产路径);验完再落位。
3. 按依赖顺序起本机链路(采集游标 / 发布状态 / 通知状态都在集合里,原样带回;**通知状态不许清空或清成全绿**,否则已通知事件会重发)。
4. 每起一段就验一段:数据层(DB `integrity_check` + 关键表行数)→ 发布层(静态产物)→ 展示层(线上页面)。

**明令禁止:**自动接管、双写(云与本机同时写同一份数据)、为了让数字好看而重写时间戳、跳过 §7 的缺口登记。

**必须用户拍板**:整章全部。

---

## 6. 回切(本机 → 云端)——骨架

1. 云端故障确认解除;**先别急着让云端恢复写**,先做数据对账:本机在接管期间产生的增量 vs 云端最后一笔,区间 = 云端 `db_cutoff` 之后到本机停写时点。
2. 停本机发布链(第 3 章同款停法),记录本机停写时点。
3. 把本机增量按既有采集/发布链路补进云端(不手工拼 SQL 猜口径);大 JSON 用 `bash scripts/restore-large-json.sh <文件>` 这类既有入口。
4. 云端自检:`integrity_check` + 关键表行数 + 最新业务日期已前进到回切日。
5. 起云端 timer(第 4 章第 7 步),观察一轮完整跑批。
6. 缺口如实写进交接记录(`db_cutoff` → 回切日),**不许重写时间戳伪装连续**。

验证点:云端最新业务日期回切日之后仍连续推进 ≥ 1 个交易日;线上三查(主链 commit / 数据层字段 / 前端展示)齐。
**必须用户拍板**:第 1、2、3、6 步。

---

## 7. 数据缺口口径(统一说法,别各说各的)

- **数据业务截止日只看 `db_cutoff`**(三库 `MAX(date)` 取最小 = 所有库共同覆盖到哪天)。
- 老集合(2026-11-15 前产出、没有 `db_cutoff` 字段)按 `db_leg.databases[].max_date` 取最小值,等价口径。
- `all_databases_covered=false` 或某个库 `date` 读不到 ⇒ **"无法对应"**,不得宣称完整可接管。
- `common_business_cutoff` **只表示"集合里最新触点"**(含文件 mtime,可能是运行日),**不能拿来判数据截止日**。
- 缺口 = `db_cutoff + 1 天` ~ 接管/回切时点;逐日列清单,缺多少天写多少天。
- 通知/告警状态随集合原样带回;**不得**"恢复成全绿"或"清空历史"。

---

## 8. 哪些动作必须先问用户

| 动作 | 为什么必须问 |
| --- | --- |
| 云上停/起任何 timer、`mv`/覆盖生产库 | 写生产,影响线上数据 |
| 决定"从某时点起本机接管" | 生产角色切换,不可自动 |
| 回切时点与增量补齐方式 | 涉及数据缺口口径,错了会丢数据 |
| 任何 `force push` / 改动已推送历史 | 破坏可追溯性(规范禁擅自强推) |
| 删除任何集合/版本/备份 | 删前必须备份并验可恢复 |

---

## 9. 已知缺陷与未完成项(阻断"接管就绪"的名单)

按 2026-11-15 实测,以下每一项都会单独阻断接管,需另行派单修:

| 编号 | 问题 | 实测证据 | 归属 |
| --- | --- | --- | --- |
| G1 | 云上未启用状态集捕获 | 云上无 `data/backups/state-capture-sets/`;`systemctl show trade-backup-db.service -p Environment` 里没有 `STATE_CAPTURE_ENABLED`;备份日志 grep 不到捕获字样 | 部署/启用(需用户拍板) |
| G2 | R2 上没有同步清单 | 只读 GET `standby/manifest_latest.json` → `NoSuchKey`;`list standby/` KeyCount=0 | 缺"提交清单"这一步 |
| G3 | 仓库里没有生成 `standby/manifest_latest.json` 的代码 | 全仓 grep 只命中 `standby_sync.py` 的默认值两处 | 功能缺口 |
| G4 | 捕获产物清单与同步工具契约不一致 | 捕获侧:`schema` / `capture_set_id` / `files[].rel` / `sha256`(未压缩)/ 无顶层 `business_date`;同步侧要求:`schema_version=1` / 顶层 `business_date`(ISO)/ `files[].key` 或 `path` / `size`(压缩字节)/ `sha256_gz` | 需加转换/提交步骤 |
| G5 | 同步工具 R2 下载签名错误 | 现网 key 上 GET 得 `403 SignatureDoesNotMatch`;同一时间戳下独立重算,签名逐位等于"首步 HMAC 用空 key"变体 | `scripts/standby_sync.py` 代码缺陷 |
| G6 | 同步工具 R2 下载 TLS 无 CA | 本机 `/usr/local/bin/python3` 3.11 直接跑 → `CERTIFICATE_VERIFY_FAILED`(同机 `upload_r2.py` 显式挂 certifi CA 才能通) | `scripts/standby_sync.py` 代码缺陷 |
| G7 | 本机未装 launchd 定时 | `launchctl list | grep -c standby` = 0 | D6 批(需用户约定时点) |

> 另:本次按任务边界**没有**做"非 dry-run 真跑"。原因不是不敢跑,而是真跑必失败,而失败会走 `notify.py --severe` 发出**真实**邮件/飞书告警(四事件通道:corrupt_set / window_fail / stale_recovery_point / space_insufficient,7 天去重)。源端都没准备好就真跑 = 制造一次假告警。

---

## 10. 本机身份登记(D4)

| 项 | 值 |
| --- | --- |
| 机器 | MacBook Air(MacBookAir10,1 / Apple M1 / 16GB / 8 核) |
| 系统 | macOS 14.4.1(build 23E224) |
| 时区 | `CST +0800`(`/etc/localtime` → `Asia/Shanghai`) |
| 代码仓真实路径 | `/Users/linhuichen/code/trade`(非 symlink) |
| 生产数据仓(本机镜像) | `/Users/linhuichen/code/trade-data`(非 symlink) |
| 备用根目录 | `/Users/linhuichen/trade-standby`(`work/` `data/` `archive/versions/` `state/` `logs/`) |
| 调度器 | macOS launchd(本机;云上是 systemd timer,别混) |
| 磁盘可用 | 49 GiB(`/System/Volumes/Data`,总 460 GiB,已用 89%) |
| 保留策略(工具默认) | 日备 7 份 + 最近 4 个 ISO 周各 1 份 + 至少 2 份已验版本;`latest_verified` 永不删;下载前最低可用空间 5 GiB(`--min-free-gb`) |
| 空间估算(估算,非实测) | 单版集合:状态集约 15.2MB(2026-11-14 云上试跑实测)+ 若清单含 DB 腿再按压缩后约 100–150MB 量级;**≤11 版约 1.6GB 上限**,加解压临时区峰值 < 1GB;对 49GiB 够用 |
| 计划同步时点 | **未定案**(D6 定)。可排程依据:云上 `trade-backup-db.timer` 每日 21:00 起(常态约 23–25 分钟完成上传+演练)、`trade-update-all.timer` 22:30;⇒ 建议落在 **01:00–04:00** 之间任选一档,避开这两段 |

---

## 11. 命令核验表(本手册里每条命令都核过)

| 命令 | 用途 | 核验方式 | 结果 |
| --- | --- | --- | --- |
| `python3 scripts/standby_sync.py status` | 判能不能接管 | 本机实跑 | ✅ 退出码 0,输出 `latest_verified: "(none)"` |
| `python3 scripts/standby_sync.py retention --dry-run` | 看保留计划 | 本机实跑 | ✅ 退出码 0,"无登记版本,无事可做" |
| `python3 scripts/standby_sync.py verify` | 复验版本 | 本机实跑 | ✅ 退出码 0,"无 latest_verified" |
| `python3 scripts/standby_sync.py sync --dry-run` | 演练同步 | 本机实跑 | ✅ 有 `--dry-run`(子命令后置);当前源端缺清单,详见 §9 |
| `launchctl print gui/$UID/<标签>` / `bootout` | 停/查同步任务 | 语法核 + 现状核(本机无该任务) | 📄 待 D6 装标签后实测 |
| `ssh -i ~/tdsignal.pem ubuntu@122.51.111.173` | 上云 | 本次实际使用(只读) | ✅ 连通 |
| `systemctl stop/start trade-*.timer` | 停/起云上写库任务 | 云端只读核对 unit 名(五个都在) | 🔍 名字核对通过,未执行写操作 |
| `scripts/upload_r2.py download-db <name> [outdir]` | 拉小库备份 | 见 `--help`/源码 `cmd_download_latest_db` | 📄 参数核对通过 |
| `docs/scripts/restore_r2_db_backup.py --name public_fund --out-dir <dir>` | 流式拉大库 | 本机 `--help` | ✅ 参数与实际一致 |
| `bash scripts/restore-large-json.sh` | 还原大 JSON | 文件存在 + 文档参数表 | 📄 参数核对通过 |
| `bash scripts/verify_backup.sh` | 每日恢复演练 | 读脚本头注释(用法/环境变量/退出码) | 📄 参数核对通过 |
| `sqlite3 <db> "PRAGMA integrity_check;"` | 库完整性 | 标准命令 | 📄 |

> 核验状态说明:✅ = 本次实跑过;🔍 = 云端只读核对过;📄 = 读源码/`--help` 核对过参数,但依赖尚未就绪、没有可跑对象。
