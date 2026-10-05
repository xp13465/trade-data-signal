# #159 public_fund.db.bak 异地备份(R2)+ 删本地 10G(2026-10-05,Batch B)

> 任务:#159 —— 云上 `public_fund.db.bak`(~10G)先补异地备份、实测可恢复后删除(§25 先备份后删,顺序不可反)。
> 依据:`docs/ops/hc-secret-purge-and-db-bak-research-20261003.md` §2.4 判定「不可直接删,先补异地备份」。
> 执行:云上 ssh `ubuntu@122.51.111.173`(`~/tdsignal.pem`)+ 复用仓库 `scripts/upload_r2.py` 的 SigV4 通路。

## 0 结论速览

- **§25 三步走通**:①备份(云上→R2 异地)②实测可恢复(MISSING=0 + 抽样回读逐位 sha256)③**验过即删**云上 ~10G .bak。
- **备份落点** = `signal-backup2/decommissioned/` 2 对象(zstd -12 压缩,各 ~558 MB)。
- **验证 = PASS**(全量 key MISSING=0 + 两文件回读解压 sha256 与源逐位一致)。
- **删除**:云上双仓 4 内容文件 + 4 伴生,共 ~10G 已删;云盘可用 **11G → 20G**(83%→65%,df 实测)。
- **恢复路径**:见 §6(一行命令 + 脚本)。

## 1 定位澄清(重要):.bak 在「云上」,不在本机 mac

- 任务描述「本地 10G」实为**云上生产机** `/home/ubuntu/code/...`;本机 mac `find ~ -name '*.db.bak'` **零命中**。
- 依据:任务引用的调研报告 §2.1 精确路径即云上;本机无同名文件。
- ⇒ 本任务 = **云上 → R2(异地)** 备份 + **删云上**(云上盘 83% 紧张,11G 可用正是痛点)。

## 2 源清单 + 基线(云上实测 2026-10-05)

| 文件(两仓各一份) | size(B) | sha256 |
|---|---|---|
| `trade-data/data/public_fund.db.bak-20261003_104704` | 2,670,219,264 | `dda553c3b918539eacc2078fa06d71763ce2df4c10fdc23720cc88b5567658b9` |
| `trade-data/data/public_fund.db.wal-20261003_104704.bak` | 2,670,219,264 | `8509b421242ec50d082d602e6fa8d3f526473470d29e08c866a884e0b6985025` |
| `trade-data-signal/data/public_fund.db.bak-20261003_104704` | 2,670,219,264 | 同上 `dda553c3…`(**与主仓逐位一致**) |
| `trade-data-signal/data/public_fund.db.wal-20261003_104704.bak` | 2,670,219,264 | 同上 `8509b421…`(**与主仓逐位一致**) |

- 伴生:`-shm` 32768B / `-wal` 0B(读访问残留,非恢复必需;不入备份)。
- 镜像仓 `trade-data-signal` 两文件与主仓 sha256 逐位一致 ⇒ **纯冗余**(内容仅 2 个独立文件;4×2.67G≈10G 中一半是重复)。
- 来源(`docs/ops/accnav-backfill-execution-20261003.md` STEP 2):accnav 场外净值回填(10-03 10:47)的回滚快照;
  回填已完成并经独立复核(`docs/ops/accnav-backfill-exec-review-20261003.md`),回滚窗口已过。

## 3 压缩

- `zstd -12 -T4`:2,670,219,264 → **558,045,538 B(≈532 MiB,21%)** / 2,670,219,264 → **558,045,533 B**。
- 压缩包 sha256:`5c597c06…`(db.bak)/ `2363fcf2…`(wal.bak)。

## 4 上传(流式 multipart → signal-backup2/decommissioned/)

- 通道:自写流式 multipart(64MiB × 9 片 × 4 并发,每片从磁盘 seek 读)——规避 ①云上仅 3.6G 内存禁整文件读入 ②仓库 `_upload_multipart` 内部 `s3_request` 未传 bucket 会落公开主桶的结构陷阱。
- 目标桶**为何选新桶 `signal-backup2`**:老账号已 **>10 GiB**(超免费额度,目标瘦身到 ~6G,见 `docs/ops/r2-old-account-cleanup-assessment-20261005.md`),再塞 1.06G 会加重;新桶为 #178 迁移后的正式家,其 `decommissioned/` 不在 5 条 lifecycle 规则内。
- ⚠️ **中途事件(诚实标注,§23.11 不静默)**:云上 `upload_r2.py` 于 **14:10(+0800)被并发 #178 agent 部署改动**(`BACKUP_BUCKET` 默认 `signal-backup`→`signal-backup2`,mtime 实证)。file1 进程 14:03 起(缓存旧码)→ 落**老桶**;file2 进程 14:35 起(新码)→ 落**新桶** ⇒ 初版两文件被**拆到不同桶**。
  处置:file1 重传新桶(signal-backup2)+ `DELETE` 老桶 stray(status 204,仅删本人产物,未动老桶既有 2 归档:`decommissioned-small-baks-20260903.tar.gz` / `etf_national_team.db.bak-backfill-20260728-232308.gz`)。终态两文件同居新桶。

## 5 验证(MISSING=0 + 抽样回读逐位)

- **全量 key 比对**:`signal-backup2/decommissioned/` 列 2 keys,**MISSING/BAD = 0**;两对象 HEAD `Content-Length` 与本地 .zst 逐位相符(558045538 / 558045533)。
- **抽样回读(逐位)**:GET 下载 → sha256 == 上传前本地 .zst sha256 → `zstd -d` → 解压后 sha256 == **源 .bak sha256**:

| key | 回读 size | zst sha256(前16) | 解压 size | 解压 sha256(前16) | 判定 |
|---|---|---|---|---|---|
| `…public_fund.db.bak-20261003_104704.zst` | 558045538 | `5c597c069425e60c` | 2670219264 | `dda553c3b918539e` | **PASS** |
| `…public_fund.db.wal-20261003_104704.bak.zst` | 558045533 | `2363fcf25ffae1e4` | 2670219264 | `8509b421242ec50d` | **PASS** |

- ⇒ **「异地可恢复」达成**(不只是上传成功,是回读-解压-逐位对账整链路 PASS)。

## 6 恢复路径(§25④:从哪取回 + 具体命令)

- **从哪取回**:R2 私有备份桶 `signal-backup2`,`decommissioned/` 前缀下 2 对象。
- **具体命令**(仓库脚本,复用既有 SigV4 通路):
  ```bash
  # 下载 + 解压为 .bak(校验 sha256 通过才落盘)
  python3 docs/scripts/restore_pfdb_bak_r2.py restore \
    decommissioned/public_fund.db.bak-20261003_104704.zst /tmp/pfdb_restore
  # 覆盖现行库(先停写 public_fund 的写入端)
  cp /tmp/pfdb_restore/public_fund.db.bak-20261003_104704 \
     /home/ubuntu/code/trade-data/data/public_fund.db
  # 快照比现行库旧 29,758 行 fund_score(= 现行 384,687 − 快照 354,929;构成:20261004 的 27,758 + 20261003 的 2,000),恢复后需重跑当日基金评分 + deploy 同步三库
  ```
- **依赖**:恢复脚本走新桶需 **#178(备份桶路由)已合并**(decommissioned/ 存取经新账号凭据)。

## 7 §23.3 举一反三:有无脚本/流程/文档引用该 .bak

- 全仓 grep(`public_fund.db.bak` / `bak-20261003` / `wal-20261003`,排除 worktree):
  - **无脚本 / 无定时任务 / 无代码引用**;
  - 仅文档引用:`TASKS.md`、`docs/pending-features-index.md`、`docs/ops/accnav-backfill-execution-20261003.md`(STEP2 备份 + 回滚命令)、`docs/ops/accnav-backfill-exec-review-20261003.md`(复核)、本调研报告。
- 唯一"消费者"= accnav 回填的**回滚路径**,该回填已完成 + 独立复核 PASS,回滚窗口已过(10-03)。
- **结论:可删**(先备份后删已完成)。

## 8 删除(§25③ 验过即删)

- 删前复核:`sha256` 与 §2 基线一致(见 §2)、R2 备份验证 PASS(§5)。
- 删除对象(云上,双仓):`public_fund.db.bak-20261003_104704` + `-shm` + `-wal`,`public_fund.db.wal-20261003_104704.bak` + `-shm` + `-wal` × 主仓/镜像仓 = 12 个文件(~10G)。
- 删后:云盘 `/dev/vda2` 可用 **11G → 20G**(83%→65%)。

## 9 诚实标注

1. **并发改码中途事件**:见 §4(file1 初落老桶 → 已重传新桶并清老桶 stray),**零数据丢失**。
2. **lifecycle 规则来源**:老桶由用户 dashboard 实测 + `docs/ops/r2-backup-prefix-lifecycle-audit-20261005.md` 佐证(仅 `backup/` 14 天);新桶 5 条规则(#179:`pre-upload/backup/weekly/monthly/claude-backup`)**不含 `decommissioned/`**。⚠️ R2 `GetBucketLifecycleConfiguration` 返 403,我方 API 未能实测,以代码/文档为据(与 `r2-archive-upload-20261004.md` §⑧ 同口径残余风险)。
3. **伴生文件(-shm 32KB / -wal 0B)不入备份**:读访问残留,非恢复必需。
4. **删除不可逆但已可逆化**:R2 备份 + 回读验证 PASS 后才删(§25)。

## 复现段(关键命令)

```bash
# 基线 sha256(云上)
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 \
  'sha256sum /home/ubuntu/code/trade-data/data/public_fund.db.bak-20261003_104704'
# 压缩
zstd -12 -T4 -f -o /tmp/public_fund.db.bak-20261003_104704.zst <src>
# 上传(流式 multipart,TARGET_BUCKET=signal-backup2;脚本见 docs/scripts/pfdb_bak_offsite_upload.py)
REPO=/home/ubuntu/code/trade-data TARGET_BUCKET=signal-backup2 \
  python3 docs/scripts/pfdb_bak_offsite_upload.py <local.zst> <key_name>
# 验证(MISSING=0 + 抽样回读逐位;脚本见 docs/scripts/restore_pfdb_bak_r2.py)
python3 docs/scripts/restore_pfdb_bak_r2.py verify
# 验证锚点(实测输出)
#   list decommissioned/ -> 2 keys ; MISSING/BAD=0
#   downloaded size==expect ; decompressed sha256==dda553c3…/8509b421…(源) PASS
# 删除(验过后)
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'rm -f /home/ubuntu/code/trade-data/data/public_fund.db.bak-20261003_104704{,-shm,-wal} \
  /home/ubuntu/code/trade-data/data/public_fund.db.wal-20261003_104704.bak{,-shm,-wal} \
  /home/ubuntu/code/trade-data-signal/data/public_fund.db.bak-20261003_104704{,-shm,-wal} \
  /home/ubuntu/code/trade-data-signal/data/public_fund.db.wal-20261003_104704.bak{,-shm,-wal}; df -h /'
# 恢复(§25④)
python3 docs/scripts/restore_pfdb_bak_r2.py restore decommissioned/public_fund.db.bak-20261003_104704.zst /tmp/pfdb_restore
```

## 参考

- `docs/ops/hc-secret-purge-and-db-bak-research-20261003.md`(§2.4 判定「先补异地备份再删」)
- `docs/ops/accnav-backfill-execution-20261003.md` / `accnav-backfill-exec-review-20261003.md`(.bak 来源=回填回滚快照)
- `docs/ops/r2-backup-prefix-lifecycle-audit-20261005.md`(老桶 decommissioned/ 无 lifecycle)
- `docs/ops/r2-old-account-cleanup-assessment-20261005.md`(老账号 >10GiB 瘦身目标)
- `docs/scripts/pfdb_bak_offsite_upload.py`(流式 multipart 上传脚本,复用 `upload_r2` SigV4 通路)
- `docs/scripts/restore_pfdb_bak_r2.py`(恢复/校验脚本:verify/list/get/restore)