# restore-r2-backup.sh 默认桶失效修复(跨桶候选探测)2026-10-08

> 任务:修 `scripts/restore-r2-backup.sh` 默认桶失效 bug(用户 2026-10-08 已拍板「修」)。
> 分支 `feat/restore-bucket-route-20261008`(base = origin/main)。报告日期 2026-10-08。
> **只读验证**:全流程无 R2 写、无邮件/飞书/告警外发;真实 `data/` 零新增零改动。

---

## 一、缺陷(复现证据)

### 1.1 机制

- `scripts/restore-r2-backup.sh` 恢复时用 `upload_r2.BACKUP_BUCKET` 作为目标桶。
- #178 备份桶迁移(commit `a8086deba`,2026-10-05)后 `BACKUP_BUCKET` 默认 = **`signal-backup2`**(独立新账号)。
- 但 `decommissioned/` 前缀下的**历史归档**(#178 迁移**之前**写入的)仍在**老桶 `signal-backup`**。
- ⇒ 按脚本默认跑 → 目标 key 在新桶 404 → **恢复直接失败,可逆性名存实亡**。

### 1.2 实测(只读探针,探测两桶同 key)

探针 `/tmp/restore_bucket_probe.py`(只发 GET,不改任何 R2 对象):

```
signal-backup2   GET decommissioned/decommissioned-small-baks-20260903.tar.gz  -> status=404 bytes=127
signal-backup    GET decommissioned/decommissioned-small-baks-20260903.tar.gz  -> status=200 bytes=11259 md5=6f905c9b077884d1b17df39228865948

signal-backup2   GET decommissioned/etf_national_team.db.bak-backfill-20260728-232308.gz -> status=404 bytes=127
signal-backup    GET decommissioned/etf_national_team.db.bak-backfill-20260728-232308.gz -> status=200 bytes=10968910 md5=1b82c2dd650b883d0dccd0a8466da569
```

两 md5 与批1 报告 `docs/ops/disk-cleanup-exec-batch1-20261007.md` §闸门① 的 ETag 逐位一致
(`6f905c9b…` / `1b82c2dd…`),坐实对象实体在老桶、新桶 404。

---

## 二、修法(结构解:跨桶候选探测)

改 `scripts/restore-r2-backup.sh`:

1. **默认桶探测(按序回落)**:候选桶顺序 = `BACKUP_BUCKET`(现行默认=新桶)→ 老 legacy 桶
   (env `R2_LEGACY_BACKUP_BUCKET`,默认 `signal-backup`)→ env `R2_RESTORE_BUCKET_FALLBACKS`
   (逗号分隔追加,**将来第三个桶零代码扩展**)。逐桶 GET,命中即用;404 继续下一个。
2. **非 404 硬错误不静默**:403/5xx 等**立即响亮失败**,不回落(§23.11 异常绝不静默),避免把
   权限/凭据问题伪装成「对象不存在」。
3. **`--bucket <名>` 显式钉桶**:已知对象所在桶时跳过探测,只查该桶(不回落)。
4. **`--out-dir <目录>`**:输出目录可指(默认 `data/`)。供演练/自测指临时目录,**避免覆盖本地源**。
5. 全候选 404 → 响亮失败并列出每桶探测结果 + 提示,不静默、不写半成品文件。

说明:**未改** `scripts/upload_r2.py`。候选桶解析当前只有本脚本一个真实使用者(§6.5 少写抽象:
第二个使用者出现才提取),故逻辑内聚在恢复脚本;将来若多脚本共用,再上提公共函数。

---

## 三、同类错误面清单(§23.2① / §23.3,逐个判定)

grep 全部读备份桶的脚本/文档 + `backup/`、`decommissioned/`、`large-json/` 前缀消费方:

| # | 对象 | 读/写 | 判定 | 结论 |
|---|---|---|---|---|
| 1 | `scripts/restore-r2-backup.sh` | 读历史 `decommissioned/` | **同病**(默认绑新桶,历史归档在老桶) | **修**(本次) |
| 2 | `docs/scripts/restore_pfdb_bak_r2.py` | 读 `decommissioned/`(#159 异地归档) | **不同病** | 不修 |
| 3 | `scripts/restore-large-json.sh` | 读 `large-json/`(`upload_r2.BACKUP_BUCKET`) | **不同病** | 不修 |
| 4 | `scripts/verify_backup.sh` | 读**最新** `backup/`(经 `cmd_download_latest_db`) | **不同病** | 不修 |
| 5 | `scripts/staticdata_backup_async.sh` | 写(调 `upload-large-json`) | **不同病** | 不修 |
| 6 | `docs/decommissioned-backups.md` | 文档(恢复指引) | **同病(文档)** | **修**(本次) |
| 7 | `docs/backup-restore.md` / `docs/site-deployment.md` / `docs/ops/r2-archive-upload-20261004.md` | 文档(老桶名文案漂移) | 文案/历史叙述 | 不修(归 #205,见下) |
| 8 | `upload_r2.py`: `cmd_upload_decommissioned` / `cmd_upload_claude_backup` / `cmd_download_latest_db` | 写侧 / 读最新 | 非「读历史归档」问题 | 不修 |

判定依据(逐条):

- **#2 `restore_pfdb_bak_r2.py`**:其 2 个 `.zst` 对象**实际落在新桶**(#159 报告
  `docs/ops/159-pfdb-bak-offsite-20261005.md` §4/§49 实证:`signal-backup2/decommissioned/` 列 2 keys、
  MISSING/BAD=0;上传时 TARGET_BUCKET 显式 `signal-backup2`)⇒ 默认 `BACKUP_BUCKET`(=新桶)**正确命中**。
  其 docstring 第 6 行「如需读老桶设 `R2_BACKUP_BUCKET=signal-backup`」是通用兜底描述,非 bug。
- **#3 `restore-large-json.sh`**:`large-json/` 有**自愈**机制——状态文件 `data/.r2_large_json_state.json`
  的 `bucket` 字段与当前 `BACKUP_BUCKET` 不符 → 视同无状态退化**全量回传**(`upload_r2.py`
  `cmd_upload_large_json` docstring 明载「换桶后首个 large-json 轮自动全量回填,根治『新桶实际不完整』」)
  ⇒ #178 后首轮已把全部 key 回填新桶 ⇒ 默认桶可覆盖全部 key,**不复发**。
- **#4 `verify_backup.sh`**:只用 `cmd_download_latest_db` 读**最新**一份 `backup/<name>_YYYYMMDD.db.gz`;
  新写入都落新桶,老桶 `backup/` 有 14 天 lifecycle 早回收 ⇒ 读「最新」= 读新桶**正确**。脚本内
  `signal-backup` 字样**仅日志文案**(非桶参数),文案漂移归 **#205**。
- **#5 `staticdata_backup_async.sh`**:写侧脚本(调 `upload-large-json` 写 `BACKUP_BUCKET`)+ 文案;
  非「读历史归档」问题,文案漂移归 **#205**。
- **#7 三份文档**:`docs/backup-restore.md`(10 老 / 0 新)、`docs/site-deployment.md`(10/0)、
  `docs/ops/r2-archive-upload-20261004.md`(7/0)——已在 **#205** 在册,且 #205 明确要求「逐处判
  『历史归档叙述 vs 现行指引』,禁止一把梭改」。**本次不改**,避免与在标任务撞车/口径冲突(§23.4)。

**与 #205 的关系**:`docs/pending-features-index.md` #205「切桶后『老桶名』文案漂移残留:4 个 shell
仍写 signal-backup」正是本族问题的在册待办,列了 `verify_backup.sh` / `restore-r2-backup.sh` /
`restore-large-json.sh` / `staticdata_backup_async.sh` 四 shell + 三文档。本次**只落地 `restore-r2-backup.sh`
的读桶实质 bug 修复**(#205 预告的「legacy 恢复语义,写老桶名可能正确」——本次用**候选探测**同时
覆盖新/老桶,不绑死任一桶,正是该风险的根治);其余三 shell 与三文档(non-bug 文案)仍留 #205 处理。

---

## 四、自测证据(§23.2②,全在临时目录,真实 `data/` 零写入)

### 4.1 正向:A 默认探测,小 key(老桶对象)
```
$ bash scripts/restore-r2-backup.sh --out-dir /tmp/restore-selftest-a decommissioned-small-baks-20260903.tar.gz
✓ 命中桶 signal-backup | 还原 11259B(网络) → /tmp/restore-selftest-a/decommissioned-small-baks-20260903.tar (47104B)
exit=0
```
- tar 解出 4 个 .bak,大小与 manifest 逐位一致:2222 / 13331 / 4432 / 22822。
- 网络字节 11259 = 批1 报告列出的对象 `Content-Length`。

### 4.2 正向:B 大 key(37MB 解压)
```
$ bash scripts/restore-r2-backup.sh --out-dir /tmp/restore-selftest-b etf_national_team.db.bak-backfill-20260728-232308.gz
✓ 命中桶 signal-backup | 还原 10968910B(网络) → …/etf_national_team.db.bak-backfill-20260728-232308 (38793216B)
exit=0
$ file …/etf_national_team.db.bak-backfill-20260728-232308
  SQLite 3.x database, … database pages 9471 …
```
- 网络 10,968,910 B / 解压 38,793,216 B 与 manifest 逐位一致;还原物是真 SQLite 库。
- 原始字节 md5 = `1b82c2dd650b883d0dccd0a8466da569` = R2 ETag(逐位一致)。

### 4.3 负控:C 不存在的 key ⇒ 响亮失败(非静默)
```
$ bash scripts/restore-r2-backup.sh --out-dir /tmp/restore-selftest-a does-not-exist-20261008.tar.gz
✗ 目标对象在所有候选桶均不存在(全部 404): decommissioned/does-not-exist-20261008.tar.gz
  探测结果: signal-backup2=404, signal-backup=404
exit=1          # 且未在 out-dir 落任何文件
```

### 4.4 负控/正控:D 显式钉桶
```
$ bash … --bucket signal-backup2 … decommissioned-small-baks-20260903.tar.gz   # 钉错(新)桶
✗ … 探测结果: signal-backup2=404          exit=1   # 钉桶不回落,响亮失败
$ bash … --bucket signal-backup  … decommissioned-small-baks-20260903.tar.gz   # 钉对(老)桶
✓ 命中桶 signal-backup …                  exit=0
```

### 4.5 可扩展性:E 将来第三个桶零代码改动(env 驱动)
```
$ R2_LEGACY_BACKUP_BUCKET=bogus-bucket bash …      # 老桶名改无效
✗ 探测结果: signal-backup2=404, bogus-bucket=404  exit=1   # 证明 env 旋钮生效
$ R2_LEGACY_BACKUP_BUCKET=bogus-bucket R2_RESTORE_BUCKET_FALLBACKS=signal-backup,another-future-bucket bash …
✓ 命中桶 signal-backup …                          exit=0   # 第三/第四桶经 env 追加即被探测
```

### 4.6 真实 `data/` 零污染 + 无外发
```
$ git status --porcelain
 M docs/decommissioned-backups.md
 M scripts/restore-r2-backup.sh
$ ls -l data/    # 仅存 index_etf_map.json/stock_codes.json/trade.db/trade_dates.txt, mtime 07:15(测试前), 无新增/无改动
```
`bash -n scripts/restore-r2-backup.sh` 通过。全程只发 R2 **GET**;无任何 R2 写/删、无邮件/飞书/告警发送。

---

## 五、恢复路径(§25④,一行命令)

```bash
bash scripts/restore-r2-backup.sh <key_name>            # 自动探测候选桶(新桶→老 legacy 桶)
# 或已知桶时显式钉桶 / 演练到临时目录:
bash scripts/restore-r2-backup.sh --bucket signal-backup --out-dir /tmp/restore <key_name>
```

python 侧等价(手动):`python3 scripts/upload_r2.py list decommissioned/ signal-backup`,再
`upload_r2.s3_request("GET", "decommissioned/<key>", bucket="signal-backup")` → gunzip。

---

## 六、诚实缺口

1. **候选桶默认两桶写死**:默认顺序 `BACKUP_BUCKET` + `signal-backup`;今后第三个桶必须靠
   env(`R2_RESTORE_BUCKET_FALLBACKS`/`R2_LEGACY_BACKUP_BUCKET`)或改代码追加,非零配置。
2. **老桶可读性依赖老账号凭据**:老桶 `signal-backup` 走 `R2_S3_*`(老 CF 账号)路由;若将来老账号
   凭据作废,老桶归档将不可读(届时须先迁移对象)。本次未改凭据链路。
3. **候选顺序 new-first**:若某 key 在两桶都存在(当前 `decommissioned/` 无重复),新桶优先命中;
   未做「同 key 双桶一致性比对」。
4. **未落地 #205 其余项**:另 3 个 shell + 3 份文档(老桶名文案)仍留 #205;**本次无 python 逻辑变更**
   (未改 `upload_r2.py`),CI 环境差异面小,但仍以 CI 结论为准。
5. **只读验证边界**:本次仅本机验证(R2 只读 + 临时目录);未在生产侧实跑恢复(恢复动作会写 `data/`,
   按硬约束不在本机对真实 `data/` 执行)。