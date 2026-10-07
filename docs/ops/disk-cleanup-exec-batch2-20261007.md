# 磁盘清理「批 2」执行报告 —— 甲1 `~/mac-backups`(2026-10-07,role-implementer)

> 范围:**甲1** `trade-data/data/mac-backups-20261001/`(86 文件 / 10.171 GiB)。
> 权威输入:`docs/ops/disk-cleanup-verify-20261007.md`(只读核实,§二表 甲1 行)+ `docs/ops/r2-archive-upload-20261004.md`(10-04 归档上传+回读)。先例:`docs/ops/disk-cleanup-exec-batch1-20261007.md`。
> 进度文件:`/tmp/agent-progress-disk-clean-batch2.md`。
> **全程遵守 §25**:先备份 → **实测可恢复**(回读逐位对账)→ 验过才删。**零外发**(仅 R2 读 + R2 备份桶写入归档对象;未发任何邮件/飞书/告警)。删除为**逐路径显式**(86 个硬编码文件名 + 集合相等前置校验),**无通配 `rm -rf`**。**未删任何 R2 既存对象**。
> 未改任何 tracked 文件;未 commit/push main(报告本体落本 worktree,待主控统一收口)。

---

## 零、结论速览

| 项 | 结果 |
|---|---|
| 判定 | **可删 → 已删** |
| 闸门 | 老桶副本:回读 sha256 + 86/86 逐文件 md5+size 对账 **PASS**;新桶副本:复合 ETag 本地复算 **逐位一致 PASS** |
| 净释放(本机) | **10,920,869,888 B ≈ 10.17 GiB**(du 10G);df avail **+10Gi** |
| 恢复路径 | ✅ 已写好且**本任务实测走通**(见 §三) |
| 诚实缺口 | 口径分叉处理 + 网络降级 + 新桶副本验证手段(见 §五) |

---

## 一、逐项闸门证据(§25:先备份 → 实测可恢复)

### 1.1 现状确认(只读列举)

| 桶 | key | 对象数 | 字节 | ETag | LastModified |
|---|---|---|---|---|---|
| `signal-backup`(**老桶**,现存) | `mac-backups/archive/mac-backups-2026-10-01.tar.zst` | 1 | 2,278,230,346 | `97188df079ef2600dde851072077b9f2` | 2026-10-04T00:44:04.891Z |
| `signal-backup2`(**现行默认桶**,原为空) | `mac-backups/archive/mac-backups-2026-10-01.tar.zst` | 1 | 2,278,230,346 | `79c8e119a3aac66627882cad33bee7f1-34` | 2026-10-07(本次上传) |

- 本机原件:`~/code/trade-data/data/mac-backups-20261001/` = **86 文件 / 10,920,869,888 B = 10.171 GiB**(与 10-04 报告逐位一致)。

### 1.2 回读对账(老桶 `signal-backup` 副本,即 10-04 那份)—— **PASS**

流程:GET 回读整包 → `zstd -d` 解包 → 与本机原件(删前仍在=天然锚点)逐文件 md5+size 对账。

| 证据 | 值 | 判定 |
|---|---|---|
| R2 回读包 size | 2,278,230,346 B | == 报告值 ✓ |
| R2 回读包 **sha256** | `f36dd009e27f255c37510b268b06a99fe928503d7a9384c74ffd5e449266d043` | == 10-04 报告包 sha256 ✓ |
| R2 对象 ETag | `97188df079ef2600dde851072077b9f2` | == 本地包 md5 ✓ |
| 解包成员 | tar 含 `mac-backups-20261001/`(86 文件)+ `mac-backups-manifest.txt` | ✓ |
| **逐文件对账(解包 86 vs 本机原件 86)** | **PASS 86/86  MISSING(归档缺) 0  EXTRA(归档多) 0  MISMATCH 0** | ✓ |
| 包内 manifest 交叉核对(86 行 `name\|size\|md5`) | **86/86 一致** | ✓ |

> md5 为逐文件全量计算(非抽样);此处做的是**全量回读**,强于派单要求的「抽样取回」。

### 1.3 新桶 `signal-backup2` 副本(本次新建)—— **PASS(字节级)**

按派单硬约束 #1/#2「归档上传 R2 备份桶 / 走 signal-backup2」,把已验包 PUT 到 `signal-backup2`(multipart,34×64MiB,8 并发;老桶副本**原样保留未动**)。

| 证据 | 值 | 判定 |
|---|---|---|
| R2 对象存在 + size | 2,278,230,346 B | == 本地包 size ✓ |
| R2 对象 **multipart ETag** | `79c8e119a3aac66627882cad33bee7f1-34` | — |
| 本地复算复合 ETag | `md5(concat(md5(每片)))` + `-34` = `79c8e119a3aac66627882cad33bee7f1-34` | **逐位一致 ✓** |

> 新桶副本是 multipart 上传,**ETag=分片复合**(非内容 md5),故改用「本地复算复合 ETag == R2 ETag」做**全量字节级验证(免二次下载)**;公式为 S3/R2 标准 multipart ETag。复合一致 ⇒ 34 片每一片的 md5 均一致 ⇒ 整对象每个字节与本地包相同。
> 本地包本身已由 §1.2 证明「== 10-04 包(sha256)」且「解包内容 == 本机原件(86/86)」⇒ 新桶副本 = 本机原件内容,链条闭合。

### 1.4 删除(逐路径显式)

- 硬编码 86 文件名清单 → 与目录实际内容做**集合相等前置校验**(多/少任一即 abort,不删)→ 逐个 `os.remove` → `rmdir`。
- 结果:删 86/86 文件,`rmdir OK, 目录存在? False`。
- 删后复测:目录不存在;老/新桶各 `KeyCount=1` 且 size 逐位一致。

---

## 二、净释放实测

| 口径 | 值 |
|---|---|
| du 删前 | `10G`(目录,10,920,869,888 B) |
| du 删后 | 目录不存在 |
| **本机净释放** | **10,920,869,888 B ≈ 10.17 GiB** |
| df `/System/Volumes/Data` used | 301Gi → 291Gi(-10Gi) |
| df avail | 132Gi → 142Gi(**+10Gi**) |

> 注:本任务自建的 `/tmp` 临时副本(`mb_extract` 10G + 包 2.12G,与数据**同卷**)已一并清理归零,否则净释放会被抵消;复测确认 `/tmp/mb_extract`、`/tmp/mac-backups-2026-10-01.tar.zst` 均不存在。

---

## 三、恢复路径(本任务**实测走通**,非纸面)

```bash
# 从 R2 取回归档(现行桶 signal-backup2;老桶 signal-backup 同样有一份,可替换 bucket 名)
python3 -c "import sys;sys.path.insert(0,'/Users/linhuichen/code/trade/scripts');import upload_r2 as u;open('/tmp/mb.tar.zst','wb').write(u.s3_request('GET','mac-backups/archive/mac-backups-2026-10-01.tar.zst',bucket='signal-backup2')[1])" \
  && zstd -d /tmp/mb.tar.zst -o /tmp/mb.tar \
  && tar -xf /tmp/mb.tar -C /Users/linhuichen/code/trade-data/data/
# → /Users/linhuichen/code/trade-data/data/mac-backups-20261001/(86 文件) + mac-backups-manifest.txt
# 完整性校验: python3 -c "import hashlib;print(hashlib.sha256(open('/tmp/mb.tar.zst','rb').read()).hexdigest())"
#            期望 = f36dd009e27f255c37510b268b06a99fe928503d7a9384c74ffd5e449266d043
```

- **一行版(流式、免整包进内存)**:`/tmp/disk_clean_batch2.py get <bucket> <key> <dest>`(本任务用其 GET 回读并逐位对账;脚本为临时件,可复制自 `upload_r2.s3_request` 范式重建)。
- ⚠️ **勿用 `docs/scripts/restore_mac_backups_r2.py`**:该脚本针对 `mac-backups/2026-10-01/` **86 个散对象前缀**(已于 10-02 从 R2 删净),现前缀已不存在,不适用于本归档。
- ⚠️ `wrangler` 本机**未安装** ⇒ 10-04 报告 §⑦ 的 wrangler 命令不可直接跑,故以 python `s3_request` 路径为准(已实测)。

---

## 四、批次定位 / 举一反三

- 本项为**单独串行**大项(甲1);批内其余项(甲2-6 / 乙1-5 / 3 stash)见 `disk-cleanup-exec-batch1-20261007.md` 与核实报告 §二表,不在本次范围。
- **同模式扫查**:本机是否还有其它「已异地归档到 R2 却未删本机」的目录 —— 由核实报告 §二表统一编排(乙1 p0 备份「先归档→可删」、乙3 旧会话「先打包→可删」仍待执行);本任务未越界处理。
- 硬排除项(全程未动):`staticdata-old-*`(8.3G,保留至 2026-10-30)、根 `data/` 下 DB/产物、双树活跃数据、当前会话目录、`~/.claude/projects`、R2 上任何既存对象。

---

## 五、诚实缺口 / 未做

1. **口径分叉(需主控确认)**:派单硬约束 #2「备份归档走 `signal-backup2`(不要用老桶)」 vs 核实报告(「以它为准」)「异地归档**已在位**」且全部既往报告(10-04/10-05/10-07)均把归档记在**老桶 `signal-backup`**、并标注「不可动·唯一副本异地容灾」。二者对「归档落在哪个桶」口径不一致。**本任务按「双保险」同时满足**:①回读验证老桶现存副本 ②在 signal-backup2 新建副本并验证;两桶副本**均保留**、未删任何 R2 既存对象。若主控意图为「只保留新桶」或「只验老桶即可」,请据此裁撤。
2. **网络降级**:本机到 CF/R2 链路本次异常慢且不稳(`cachefly` 仅 0.42 MB/s;`speed.cloudflare.com`/`raw.githubusercontent.com` SSL 直连失败)。单连接 GET/PUT 仅 ~0.5–0.9 MB/s;改 8 并发后 GET ≈ 2.4 MB/s、multipart PUT ≈ 1.6–1.9 MB/s。期间出现 1 次 `SSLEOFError`(自动重试成功)。整包 2.12 GiB 下载 ≈ 14 min、新桶上传 ≈ 23 min。
3. **新桶副本的验证手段**:multipart ETag 非内容 md5,故用「本地复算复合 ETag == R2 ETag」做字节级验证(未二次下载整包回读);老桶副本已做整包 sha256 + 86/86 全量回读,两者互补。
4. **R2 lifecycle 未实测**(403,沿用既往标注):`mac-backups/` 前缀在新老两桶均**无 lifecycle 规则**(刻意保留、不参与自动清理)——归档不会被自动清掉,此点沿用 10-04/10-05/10-07 结论,未在本轮重测。
5. **未改 tracked 文件 / 未 commit**:如需把「新桶副本」或恢复脚本固化为仓库资产(如把流式取回脚本落 `docs/scripts/`),须主控拍板后再改(派单要求「改脚本先上报」)。

## 六、复现命令(关键)

```bash
# 列举两桶(只读)
python3 scripts/upload_r2.py list mac-backups/ signal-backup
python3 scripts/upload_r2.py list mac-backups/ signal-backup2
# HEAD 取 ETag/size
python3 -c "import sys;sys.path.insert(0,'scripts');import upload_r2 as u;print(u.s3_head('mac-backups/archive/mac-backups-2026-10-01.tar.zst',bucket='signal-backup2',with_len=True))"
# 本任务临时件(可清理): /tmp/disk_clean_batch2.py(GET/PUT/head) /tmp/b2_rget.py(并行分片GET) /tmp/b2_mput.py(multipart PUT) /tmp/b2_verify.py /tmp/b2_mcheck.py /tmp/b2_del.py
```

> 报告落档:本文件(worktree `docs/ops/disk-cleanup-exec-batch2-20261007.md`)。**未 commit/push main**。