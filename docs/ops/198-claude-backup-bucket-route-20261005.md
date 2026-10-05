# #198 判定:claude-backup / mac-backups / pre-upload 三个前缀该不该在新桶(只读核查,2026-10-05 CST)

> 任务:新桶 `signal-backup2` 里这三个前缀 0 对象 —— 判定「① 该链路本就不走跨账号路由、直写老账号(⇒ #186 需修)」还是「② 已切新桶、只是尚无写入」。
> 环境:本机(mac,纯开发)+ 云上 `ssh -i ~/tdsignal.pem ubuntu@122.51.111.173`(生产)。**全程只读:未 PUT/DELETE 任何 R2 对象、未改云上任何文件、未启停 unit**。
> 全部 R2 操作走 `scripts/upload_r2.py` 的 `s3_request`/`_list_keys`(分页);跨账号路由 `_route_bucket`(bucket==signal-backup2 → 新账号端点)。

## 0. 结论(一句话表)

| 前缀 | 判定 | 一句话依据 |
|---|---|---|
| `claude-backup/` | **② 已切新桶**(代码+env 双就绪;待 10-06 03:17 首跑实证) | 写入唯一走 `upload-claude-backup` → `s3_request(bucket=BACKUP_BUCKET)`;本机解析 `BACKUP_BUCKET=signal-backup2`;老桶最新对象=**切桶前** 10-05 03:17(北京);切桶生效后老桶 0 新增 |
| `mac-backups/` | **③ 不适用「切桶」——一次性归档对象**(拍板容灾保留,非活跃链路) | 全仓唯一写入记录=10-04 手工归档上传(2.122GiB tar.zst,显式 `bucket=BACKUP_BUCKET`,当时=老桶);此后**无任何定时/脚本再写**;对象恰 1 个、零推进 |
| `pre-upload/` | **② 已切新桶**(待首笔「覆盖上传」实证) | 写入点唯 `_backup_overwritten_keys`(export-guard L5,`bucket=BACKUP_BUCKET`);云上**14:10:55 起**代码+env 双就绪;老桶最新=12:55:32(**就绪前**);就绪后无覆盖上传发生 ⇒ 两桶均无新对象 |

**对 #186:claude-backup 与 pre-upload 无需改判定(「在用,切桶后停」成立),mac-backups「不可清」结论保持但依据应补正**(见 §5)。

## 1. 写入脚本与凭据/桶名通路(判据核心问题的直答)

**三前缀全部走 `upload_r2.py` 的跨账号路由,不存在「自己直连老桶端点」的旁路:**

| 前缀 | 写入者 | 调用链 | 桶名来源 |
|---|---|---|---|
| `claude-backup/` | mac 本机 launchd `com.claude.self-backup`(每天 03:17 跑 `scripts/backup_claude_self.sh`) | `backup_claude_self.sh:45` → `upload_r2.py upload-claude-backup` → `cmd_upload_claude_backup`(upload_r2.py:2500)→ `s3_request("PUT", key, bucket=BACKUP_BUCKET)`(L2524) | `BACKUP_BUCKET = os.environ.get("R2_BACKUP_BUCKET", BACKUP2_BUCKET)`(L299)→ 本机无 `R2_BACKUP_BUCKET` 覆盖 ⇒ `=signal-backup2` |
| `mac-backups/` | **无(一次性)**。仅 2026-10-04 手工归档上传(`docs/ops/r2-archive-upload-20261004.md` §④:显式 `bucket=BACKUP_BUCKET`,当时=老桶) | 同上 `s3_request` 通路(服务端 COPY 纠正落点也走同一通路) | 同上;该对象 10-04 落在老桶是当时默认,之后无再次写入 |
| `pre-upload/` | 云上数据上传链(export-guard L5) | `_incremental_upload`(L1436)→ `_backup_overwritten_keys`(L1108)→ COPY `bucket=BACKUP_BUCKET`(L1155) | 同上;云上 `EnvironmentFile=/home/ubuntu/code/trade-data/.env` 注入四键 |

路由实现:`_route_bucket`(upload_r2.py:402):目标桶==`BACKUP2_BUCKET`(L286,默认 `signal-backup2`)且 `BACKUP2_HOST` 已配 → 新账号端点/凭据;否则回退老账号。**本机与云上实测双确认**(见 §2 表)。

## 2. 路由解析实测(本机 + 云上,均为当前代码+当前 .env,纯本地解析不联网)

| 位置 | BACKUP_BUCKET | R2_BACKUP_BUCKET 覆盖 | route(signal-backup2) | route(signal-backup) |
|---|---|---|---|---|
| mac 本机(trade 树,与 03:17 定时同一路径) | `signal-backup2` | 无 | 新账号 host `2455352499...` | 老账号 host `9be954e8...` |
| 云上(trade-data 树) | `signal-backup2` | 无(`grep -c '^R2_BACKUP_BUCKET='`=0) | 新账号 host `2455352499...` | 老账号 host `9be954e8...` |

- 本机 `.env` 键名(只列键):`R2_BACKUP2_ACCESS_KEY_ID / R2_BACKUP2_BUCKET / R2_BACKUP2_ENDPOINT / R2_BACKUP2_SECRET_ACCESS_KEY` 四键全在(`/Users/linhuichen/code/trade/.env`)。
- 云上 `/home/ubuntu/code/trade-data/.env` 四键全在,mtime `2026-10-05 11:18:04 +0800`。

## 3. 两桶枚举实测(LastModified,UTC;本次复核 2026-10-05 23:4x CST)

| 桶::前缀 | 对象数 | 最新对象(LastModified) | 切桶生效后(≥10-05 05:30Z)新增 |
|---|---|---|---|
| `signal-backup::claude-backup/` | 30 | `claude-self-20261005.tar.gz` @ **2026-10-04T19:17:07.326Z**(北京 10-05 03:17) | **0** |
| `signal-backup::mac-backups/` | **1** | `archive/mac-backups-2026-10-01.tar.zst` @ **2026-10-04T00:44:04.891Z**(北京 08:44) | 0(本就没有写入者) |
| `signal-backup::pre-upload/` | 6585 | `pre-upload/20261005/data/signal_kelly_snapshots/latest_posrating.json` @ **2026-10-05T04:55:32.034Z**(北京 12:55:32) | **0** |
| `signal-backup2::claude-backup/` | **0** | — | 0 |
| `signal-backup2::mac-backups/` | **0** | — | 0 |
| `signal-backup2::pre-upload/` | **0** | — | 0 |

- 新桶 0 与 tester 10-05 22:15~22:45 实测一致(`docs/ops/185-backfill-verify-20261005.md` §1)。
- 「切桶生效后」判定线取 **10-05 05:30Z(=北京 13:30)**,理由:云上真正 pull 到切桶代码为 14:10:55(见 §4),05:30Z 早于它、晚于老桶最后写入 12:55 的包含性最保守。

## 4. 关键时间线(北京时区,证据链)

| 时间(10-05) | 事件 | 证据 |
|---|---|---|
| 03:17:07 | 本机 claude-backup 上传成功 → **老桶**(当时跑旧代码) | `claude_self_backup.log` 末行「✓ … -> signal-backup/claude-backup/claude-self-20261005.tar.gz」;对象时间戳 19:17:07.326Z 精确吻合;旧代码定义 `BACKUP_BUCKET=os.environ.get("R2_BACKUP_BUCKET","signal-backup")`(`git show a8086deba^:scripts/upload_r2.py` L268) |
| 11:18:04 | 云上 `.env` mtime(四键在位) | `stat` 输出 |
| 12:25:01~13:03:49 | 云上 r2_upload_async 轮(`r2_upload_async_20261005_122501.log`;etf-hist 停滞被 kill) | 老桶 pre-upload 最后写入 12:55:32 属此轮窗口 |
| **12:47** | #178 路由代码 commit(`a8086deba`) | git log |
| **14:10:55** | **云上 `git pull` 到 merge `5e014d9e3`(切桶代码在云上生效)** | `git reflog --date=iso`:`5e014d9e3 HEAD@{2026-10-05 14:10:55 +0800}: pull origin main` |
| 16:51:49~18:35 | r2_upload_async 轮:多通道「停滞 300s」被 kill、无成功覆盖 PUT | `r2_upload_async_20261005_165149.log`(全通道 kill 清单) |
| 21:16:20~21:35:31 | r2_upload_async 轮:lab/trade-sim「内容未变化,无需上传」 | `r2_upload_async_20261005_211620.log` |
| 22:15~22:45 | tester 只读复核:新桶三前缀 0 | 185 报告 §1 |
| 23:4x | 本次复核:新桶 0;老桶切桶后 0 新增 | 本报告 §3 |

**要点:老桶三个前缀的最后写入(03:17、08:44[10-04]、12:55)全部发生在云上/本机切桶生效之前**;切桶生效后(本机 10-06 03:17 未到、云上 14:10:55 后)两桶均无新对象 —— 因为期间没有发生「会写这三前缀」的活动(本机链路未到点;云上各轮要么「未变化」要么被 kill,没有成功覆盖 PUT)。

## 5. 对 #186(老桶清理评估)的影响

- `claude-backup/`:评估报告写「在用(切桶后停)」——**成立,无需修**。老桶存量 30 对象(9-06~10-05)是切桶前历史,由老桶已配的 30 天 lifecycle 自然回收(≈10-06~11-04 逐日到期,评估报告 §幂等表推算)。
- `pre-upload/`:评估报告写「在用(写入中;切桶后停)」——**成立,无需修**。老桶存量由 7 天 lifecycle 到期回收(≈10-10~10-12);此后新写入落新桶。
- `mac-backups/`:评估报告「不可清」结论**保持**,但依据应补正为「**10-04 用户拍板『传 R2 归档,本机先留』= 异地容灾保留 + 该对象无任何自动写入者**」——原表述「不可清」不应被读成「因老账号不再增长所以留着没关系」;它是一条**一次性归档**,不在「增长链路」范畴,后续即便再传归档也会走新路由落新桶。「与老账号增长预期冲突」的担忧对 mac-backups **不成立**(它没有增长源)。
- 综合:**「老账号(这三前缀)不再增长」的预期成立**,首笔实证时点为 10-06 03:17(本机 claude-backup 首跑新桶)。

## 6. 诚实标注

1. **10-06 03:17 首跑是全报告唯一无法当场验证的环节**(未来事件)。依据=「跑的就是本报告 §2 解析的同一脚本+同一 .env」(launchd plist 直调 `backup_claude_self.sh`,脚本内绝对路径调 `trade/scripts/upload_r2.py` + `trade/.venv/bin/python`,与解析环境一致)。复核命令见「复现段」③。
2. **12:55:32 老桶 pre-upload 最后一笔的进程归属未精确定位**:该时间点无对应文件日志/journal 可见的「将被覆盖」打印行(全云上 logs 中该打印仅 10-03 fund-nav 一条,`-> signal-backup/pre-upload/20261003/`);推断为 12:25 轮某通道 PUT 前备份动作(kelly-snapshots 3 文件对:31.889/31.944/32.034Z)。**不影响判定**:该笔发生在云上切桶生效(14:10:55)之前,属旧代码/旧路由行为。
3. **顺手发现(建议后续小修,本报告未实施)**:`scripts/backup_claude_self.sh:46` 的成功文案写死「signal-backup/claude-backup/…」(不随实际桶名),10-06 起日志会显示老桶名而实际已写新桶(脚本上一行 `upload_r2.py` 自身打印的是**真实**桶名,可交叉核对)。属文案与实际不符,建议改为反映实际桶名或去除桶名。
4. 本报告全程只读;未对任何 R2 桶执行 PUT/DELETE/POST;未改云上文件;枚举脚本 `docs/scripts/198_backup_prefix_probe.py` 只发 GET(ListObjectsV2)。

## 复现段

### ① 本机(任意检出本报告的 trade 分支,只读)

```bash
# 路由解析(纯本地,秒级;期望: BACKUP_BUCKET=signal-backup2 + route2=2455... + route1=9be9...)
/Users/linhuichen/code/trade/.venv/bin/python docs/scripts/198_backup_prefix_probe.py route

# 6 组枚举(跨境 ListObjectsV2,约 1-2 分钟;stdout 摘要 + 全量 JSON 落 /tmp/r2_list_198_out.json)
/Users/linhuichen/code/trade/.venv/bin/python docs/scripts/198_backup_prefix_probe.py
```
2026-10-05 23:4x 实测输出(摘):
```
[signal-backup] claude-backup/: 30 objects; after-cutover=0
   2026-10-04T19:17:07.326Z  claude-backup/claude-self-20261005.tar.gz
[signal-backup] mac-backups/: 1 objects; after-cutover=0
   2026-10-04T00:44:04.891Z  mac-backups/archive/mac-backups-2026-10-01.tar.zst
[signal-backup] pre-upload/: 6585 objects; after-cutover=0
   2026-10-05T04:55:32.034Z  pre-upload/20261005/data/signal_kelly_snapshots/latest_posrating.json
[signal-backup2] claude-backup/: 0 objects
[signal-backup2] mac-backups/: 0 objects
[signal-backup2] pre-upload/: 0 objects
```

### ② 云上(ssh 只读)

```bash
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 "grep -o '^R2_[A-Z0-9_]*' /home/ubuntu/code/trade-data/.env | sort"
# 期望含 R2_BACKUP2_{ACCESS_KEY_ID,BUCKET,ENDPOINT,SECRET_ACCESS_KEY};且无 R2_BACKUP_BUCKET 覆盖

ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'cd /home/ubuntu/code/trade-data-signal && REPO=/home/ubuntu/code/trade-data GIT_REPO=/home/ubuntu/code/trade-data-signal .venv/bin/python -c "import sys; sys.path.insert(0, \"/home/ubuntu/code/trade-data-signal/scripts\"); import upload_r2 as u; u.load_env(); print(u.BACKUP_BUCKET, u._route_bucket(\"signal-backup2\")[0])"'
# 期望: signal-backup2 2455352499fc04ddbd92d33e0a0e8614.r2.cloudflarestorage.com

# 云上切桶代码生效时点(期望含: 5e014d9e3 ... 2026-10-05 14:10:55 +0800)
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 "cd /home/ubuntu/code/trade-data-signal && git reflog --date=iso | grep -m1 5e014d9e3"
```
### ③ 首跑实证(10-06 03:17 之后跑;本报告的最终闭环验证)

```bash
/Users/linhuichen/code/trade/.venv/bin/python docs/scripts/198_backup_prefix_probe.py route   # 先看路由仍=新桶
# 预期: signal-backup2::claude-backup/ count>=1(出现 claude-self-20261006.tar.gz);
#        signal-backup::claude-backup/ 不再新增(数目只随 30 天 lifecycle 减少)
```

### ④ 复核/恢复一行
- **复核**:`python3 docs/scripts/198_backup_prefix_probe.py`(只读,本机/云上通用);
- **恢复**:本报告零删除零改动,无需恢复;若未来要把 `mac-backups` 归档从老桶迁新桶(跨账号无法服务端直拷):源=本机 `~/code/trade-data/data/mac-backups-20261001/`(86 文件 10.171GiB)或老桶 GET 中转,重新打包后经 `upload_r2.py` 通路(`bucket=signal-backup2`)PUT 即可。
