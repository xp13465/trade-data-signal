# 存储治理前复核报告(protected 引用闭包 + 旧库 SHA,按 2026-11-25 云上现状重算)

- 复核时间(云上扫描):2026-11-25 04:25:59–04:26:03 CST(UTC 20:25:59–20:26:03)
- 性质:全程只读。未删/未移/未改码/未跑 GC/未访问 R2/未加锁/未取业务锁。
- 权威源:云上生产 `/home/ubuntu/code/{trade-data-signal,trade-data,trade-data-signal-staticdata}`;本机仅对照。本机 `trade-data` 为 symlink,未作权威。
- 采集器复用 11-24 已审只读脚本 `storage-cleanup-20261124-read-protected.py`(未改逻辑,仅输出到新文件);闭包重算复用 `analyze-protected.py`,另用 `independent-check.py`(BFS 独立实现)复算,两者逐项一致。
- 旧方案快照基准:2026-11-24 14:57:25–14:57:30 CST(`/tmp/codex-reports/storage-cleanup-20261124-*`),固定 main `f4015bb695b98c9defb9e90ff1e435b630b8a02f`。当前云上源码与**本机 main(1128f8073)逐字一致**。

## 0. 六项结论摘要

1. **云上现状**:两卷 88%、可用 7,815,991,296B(7.2792GiB),比快照(约 8.75GiB)少约 1.47GiB;C 根 8261→**9286 文件**/9,496,563,712→**10,683,133,952B**(+1025 文件/+1.1051GiB);D 根 1047 文件不变、1,219,985,408→1,221,545,984B。C 增长=+512 history、+512 payload、+1 pair,顶层 journal 数不变(262)。
2. **protected 引用闭包**:重算候选 **8045 项 / 9,091,342,336B(8.4670GiB)**;旧 7028 项**逐项零漂移**(dev/ino/size/mtime/allocated 全同、仍无引用、0 删除),新增 1017 项(1,167,306,752B)。坏 JSON/缺引用/symlink/非普通文件 **0**。独立 BFS 复算逐项一致。
3. **保守保留集**:55 条 plain preparing 历史**逐字节未变**(同 inode/mtime),payload 99→103(+4,均 nav_bucket 的 old_sha payload,原先靠已终结的 confirmed 行挂着);12 条 unknown+pending_purge 仍由 GC 保留;**无新增 nonconfirmed 状态类**。保留集合计 158 项 / 315,396,096B(0.2937GiB)。
4. **旧库八文件 SHA**:8/8 SHA256 与方案完全相同;5 个独有 SHA 清单仍成立;size/mtime/inode 全未变;8 WAL 全 0B、8 SHM 全 32KiB。唯一变化:C/data/sentiment.db-shm mtime 前移整 24h(11-23 21:15:01→11-24 21:15:01),说明有每日读者打开过 C 旧库(WAL 仍 0=无写)。
5. **deploy 回涨**:机制未修(`deploy.sh:749-754` rsync 仍无 `--exclude=.r2-protected/`、无 `--delete`);今日 03:14:49 又复制了一次(C 的 gc-manifest birth=03:14:49、内容与 D 逐字节同 SHA、mtime=D 的 02:46:22);D 根 1047 文件全部镜像在 C 根(1,222,025,216B 重复);新增 1017 项候选中 766 项在 11-24 旧 D 快照里,504 个新增 payload **全部**是 D 当时的旧 payload → 回涨来源=deploy 把 D 的 protected 抄进 C 且不删。
6. **GC 卡死**:仍卡死。C 根 `len(files)+1=9287>8192`,`sum(size+4096)=10,690,687,112B > 2GiB cap`,`r2_safe_write.py:190/204/211-212` 在 unlink 前抛 `UnsafeWrite`;云上两树 `r2_safe_write.py` SHA=`bdbb8e08…` 与快照一致(未修)。D 根 GC 正常:manifest birth=mtime=11-25 02:46:22(自己写的);C 根从未写过自己的 manifest(现文件是 D 的 rsync 副本,keep=1047=D 的清单)。

**清单判定:旧 7028 项清单不可直接用作执行清单(缺 1017 项新候选),但其 7028 项作为"已核对子集"全部仍有效、可复用;新候选清单 `/tmp/storage-recheck-20261125-candidates.json` 可用(A 阶段)。B/C 旧库清单仍成立,数值不变。**

---

## 1. 云上现状盘点(df / 两卷 / 两 protected 根)

| 指标 | 11-24 14:57 快照 | 11-25 04:26 现状 | 差额 |
|---|---:|---:|---:|
| 根卷 size | — | 63,290,032,128B | — |
| used / avail | avail ≈8.75GiB | used 52,773,294,080B / **avail 7,815,991,296B(7.2792GiB,88%)** | ≈-1.47GiB |
| C 根文件数 | 8261 | **9286** | +1025 |
| C 根 allocated | 9,496,563,712 | **10,683,133,952** | +1,186,570,240(+1.1051GiB) |
| D 根文件数 | 1047 | 1047 | 0 |
| D 根 allocated | 1,219,985,408 | 1,221,545,984 | +1,560,576 |
| 两根合计 | 10,716,549,120(9.9806GiB) | 11,904,679,936(11.0871GiB) | +1,188,130,816 |

C 根增长构成(allocated):`history/` +512 文件/+2,097,152B;`payloads/` +512 文件/+1,184,468,992B;`pairs/` +1/+4,096B;顶层 journal 262 不变;`.gc.lock` 1。三项合计 +1,186,570,240B,与总差额逐字节相等(算术闭合)。

增长来源(证据):新增候选 history 顶层键绝大多数是 `nav_bucket/*.json`(每键 2 条被取代的 confirmed);新增文件 mtime 分布 11-23 488 个、11-24 529 个。新增 504 个 payload **全部**能在 11-24 旧 D 快照的 payload 集里找到(见第 5 节),即 C 根这轮增长主要是 deploy 从 D 抄进来的旧版本,不是 C 自己新写。

D 根:文件数不变但**内容整体轮转**——261 条 history 全换新 write_id、522 个 payload 中 512 个换 digest、262 个顶层 journal 全重写、pair 换 1 个;仅 10 个 payload 因内容相同保留。mtime 分布 11-24 389 个、11-25 657 个。这说明 D 根 GC 在正常工作(每天把被取代的删掉、保持 1047),而 C 根只进不出。

## 2. protected 引用闭包重算(按方案 §4.2 口径,云上 C/D 双根)

口径(与方案一致,未放宽):
- 保留:顶层全部 journal、`unknown`/`pending_purge`/非 confirmed 的 pair history、每 key 最新 confirmed(HISTORY_KEEP=1,按文件 mtime_ns)、pair 图递归、`sha256`+`old_sha256` payload、**跨根 payload 并集**(一个 digest 在任一极被引用则两处都不算候选)、`.gc.lock`/`gc-manifest.json`。
- 候选项:策略无引用、普通文件、nlink=1;pair 候选另核其 2 条 history 终态。

| 类别 | 11-24 快照 | 11-25 现状(C 根) | 差额 |
|---|---:|---:|---:|
| GC 引用闭包保留 | 1079 路径 / 1,266,282,496B | **1083 / 1,276,395,520** | +4 / +10,113,024 |
| 额外保守扣留 | 154 / 306,245,632 | **158 / 315,396,096** | +4 / +9,150,464 |
| 策略无引用候选 | 7028 / 7,924,035,584 | **8045 / 9,091,342,336** | +1017 / +1,167,306,752 |
| 坏 JSON / 缺引用 / 异常类型 | 0 | **0** | 0 |
| D 根 | 1047 全保留、0 候选 | **1047 全保留、0 候选** | 0 |

C 根 9286 = 1083 + 158 + 8045,算术闭合。所有 9308→(现 10333)文件 `(dev,ino)` 唯一、nlink=1、无硬链接、无 symlink、无外部链接;闭包缺失路径=0;顶层 journal 文件名与 `sha256(bucket+"/"+key).json` 身份校验 0 违例;采样前后 stat 无变化(`reference_restat_changes=[]`);采集器 `complete=true`、`errors=[]`。

候选构成:4064 条 confirmed history(全部 `pending_purge=false`)、3972 个 payload、9 个 pair。9 个 pair 的 18 条嵌入 history 全部 `confirmed`、`pending_purge=false`、`pair_id`/`sha256`/`old_sha256` 与 pair 清单逐项一致(逐对已打印核验,含新增的 `pairs/8b30ab21…`)。

**逐项对比旧 7028 项**(path + dev/ino/size/mtime/allocated/nlink):
- 仍存在且元信息**逐位相同**:7028 / 7028;
- 元信息变化:**0**;已消失:**0**;类别变化(如候选→保留):**0**;
- 新增候选:1017 项 / 1,167,306,752B(history 512 / payload 504 / pair 1)。

**独立复核**:用另一份实现(`independent-check.py`,BFS + 并列保留 + 跨根并集)对同一原始数据重算,结果 `code=8045/9,091,342,336`、`runtime=0`,与主算 `exact_match_with_first_audit=true`。

结论:候选集合**扩大** 1017 项(+1.0871GiB),没有缩小、没有身份漂移。旧 7028 项依然全部可删(按本地契约),但清单不完整。

## 3. 保守保留集核验

| 项 | 11-24 快照 | 11-25 现状 | 说明 |
|---|---:|---:|---|
| plain preparing 历史 | 55 | **55** | 路径集合完全相同,且文件 inode/size/mtime **全部未变**(逐字节同一份) |
| 相关 payload | 99 | **103** | +4,无移除;新增 4 个均只被 `nav_bucket/88,89,8a,8b` 的 preparing 行以 `old_sha256` 挂着 |
| unknown + pending_purge 历史(GC 自身保留) | 12 | **12** | 未变 |
| 保留集合计 | 154 / 306,245,632B | **158 / 315,396,096B(0.2937GiB)** | +4 payload / +9,150,464B |

没有新增 nonconfirmed 状态类:全量 history 状态分布仍是 `confirmed 4325 / preparing 55 / unknown(pending_purge) 12`(快照同款)。

**动态性提醒(必须写进执行前置)**:这 4 个新增 payload 在 11-24 快照时是被某条 confirmed 行引用的(GC 保留),该 confirmed 行被更新后,现在只剩 preparing 行的 `old_sha256` 引用它——而现 GC **不保留 preparing 行**,所以这 4 个在"现 GC 语义"下已可被删。也就是说:保守保留集是**会变**的,执行时必须在锁域内重新快照 hold 清单,不能照抄本文件里的 158 项。

## 4. 旧库八文件 SHA 复测(云上 C/S 两树)

| 文件 | 当前 SHA256 | 与快照 | size | mtime/inode | allocated |
|---|---|---|---|---|---|
| C `data/sentiment.db` | `861d4ca2…890622` | 同 | 232,124,416 | 未变 / 未变 | 232,128,512 |
| S `db/sentiment.db` | `861d4ca2…890622` | 同 | 232,124,416 | 未变 / 未变 | 232,128,512 |
| C `data/etf_national_team.db` | `62a47ffc…3f547f` | 同 | 258,400,256 | 未变 / 未变 | 258,404,352 |
| S `db/etf_national_team.db` | `62a47ffc…3f547f` | 同 | 258,400,256 | 未变 / 未变 | 258,404,352 |
| C `data/stock_daily.db` | `fb948a75…49239b` | 同 | 185,065,472 | 未变 / 未变 | 185,069,568 |
| S `db/stock_daily.db` | `36546e24…1c5812` | 同 | 185,065,472 | 未变 / 未变 | 185,069,568 |
| C `data/public_fund.db` | `b5095b10…73f95` | 同 | 2,965,819,392 | 未变 / 未变 | 2,965,831,680 |
| S `db/public_fund.db` | `b5095b10…73f95` | 同 | 2,965,819,392 | 未变 / 未变 | 2,965,827,584 |

- 5 个独有 SHA 清单**仍成立**(sentiment 1、ETF 1、公募 1、stock_daily 2),不能把两个 stock 合并丢弃。
- 8 个 WAL 全部 **0B**、8 个 SHM 全部 **32KiB**、无 `-journal`;与快照一致。
- 唯一 sidecar 变化:C `data/sentiment.db-shm` mtime 11-23 21:15:01 → **11-24 21:15:01**(整 +24h,WAL 仍 0)。含义:C 旧 `sentiment.db` **有一个每日 21:15 左右的打开者**(只读打开也会更新 WAL 模式 SHM),与方案"不能凭 DB 停在 10/28 就说没有消费者"的警告一致。B/C 隔离观察必须覆盖这个时点。
- 瞬时 `/proc/*/fd` 扫描:命中 8 个旧库及其 sidecar 的打开 FD = **0**(仅代表 04:26 这一刻,不替代调度窗口检查)。
- 空间口径未变:B(三份同 SHA 的静态副本)= **3,456,360,448B(3.2190GiB)**(S 侧 public 的 allocated 2,965,827,584 计入);C 八主文件 = **7,282,864,128B(6.7827GiB)**。逐文件与快照完全一致。

## 5. deploy 回涨核查(机制修复前的现状)

机制未修证据:
- 云上 `scripts/deploy.sh` 与**本机 main 1128f8073 逐字同 SHA**(`fe4d7844…6d723d`),第 749–754 行 `rsync -a --exclude=logs/ … --exclude='*.db*' "$REPO/data/" "$GIT_REPO/data/"` **没有** `--exclude=.r2-protected/`,也**没有** `--delete`;`r2_safe_write.py` 云上/本机同为 `bdbb8e08…`(方案钉的旧版,GC 修复未落地)。

回涨实证(今天刚发生):
- C 根 `gc-manifest.json` 的 **birth=2026-11-25 03:14:49**,mtime=**02:46:22**;D 根同文件 birth=mtime=**02:46:22**;两者 **SHA 逐字节相同**(`8dd2333d…6f20f`)、大小 72,159B、keep 都是 1047 项。→ C 的这份是 rsync 从 D 抄来的(mtime 保留=源端 02:46:22= D 自己 GC 写清单的时刻;C 侧文件 03:14:49 才出现),不是 C 根自己 GC 写的。
- D 根 1047 个文件在 C 根**全部存在**,size 与 mtime 逐项相同(mtime 相同的 1047/1047)。C 根里这批镜像的 allocated 合计 **1,222,025,216B(1.1381GiB)**,且因 C 根把镜像来的 journal 当"当前 journal"解析,这批文件全部落在"GC 引用保留"类——**本地 GC 永远不会回收它们**,只能等跨树复制被阻断后按单根治理。
- 新增 1017 项候选里:766 项在 11-24 旧 D 快照中存在;504 个新增 payload **全部**是 11-24 旧 D 的 payload(现已被 D 轮转删除、C 里留下);512 条新增 history 中 261 条来自旧 D 快照、251 条是快照之后 D 新写又被轮转掉的。→ 回涨链路=**D 写入→deploy rsync 抄进 C→D 轮转删除→C 留下孤儿**。
- 本次扫描(04:26)之后,05:00 又起了一轮 deploy(`deploy_20261125_0500.log`,05:08 仍在跑),即回涨仍在继续,执行前后候选数会再变。

结论:方案 §3.1 的"先修再清"门槛**仍未满足**;当前每天净增约 1.1GiB 且可用空间只剩 7.28GiB,不回修机制,清完也会在 7 天内涨回。

## 6. GC 卡死现状

- 代码路径(云上 `r2_safe_write.py`,SHA `bdbb8e08…`):`gc()` 第 108 行 → 第 190 行 `self.check_capacity(files, {gc-manifest})` → `check_capacity` 第 204 行 → 第 211–212 行 `if used + extra > cap or len(files) + len(writes) > 8192: raise UnsafeWrite(...)`;**check 在 `durable(gc-manifest)`(191)和 `path.unlink()`(193)之前**。
- 当前值:C 根 `files=9286`,`len(files)+1=9287 > 8192`;`used=10,690,687,112B > 2,147,483,648B`(默认 cap 2GiB,约 4.98 倍);`free=7.81GB > 128MiB reserve`(free 不是本轮阻塞项)。
- 环境覆盖:两树 `.env`/`.env.production` 的 3 个配额变量均无覆盖(`trade-data/.env` 存在但未选到这三键);扫描时 1 个 uploader 进程环境无覆盖。与快照一致。
- 是否"真的卡死"(不只靠日志沉默,按代码路径+环境反证):①代码路径确定:给定 9286 文件和 2GiB cap,`gc()` 必在 unlink 前 raise,零删除;②环境反证:C 根 manifest 是 D 的副本(不是 C 自己写的),且 C 根仍留着 8045 个无引用文件——若 C 根 GC 曾成功过一次,这些早该被删。两条一致。
- 上次 GC 成功时间:**D 根 = 2026-11-25 02:46:22**(manifest birth=mtime,retired_count=0,即 D 根全保留无需删);**C 根无成功记录**(现有 manifest 是 03:14:49 的 rsync 副本)。近 9 小时 journal 无 `capacity budget exhausted` / `R2_PROTECTED_GC` 行——但按 E31 此条只作旁证,不作结论依据。

## 7. 新候选集合(交付物)

文件:`/tmp/storage-recheck-20261125-candidates.json`(3.4MB,含 8045 条逐项 path/realpath/size/allocated/dev/ino/nlink/mtime_ns + 保留集清单 + 旧快照差异明细 + 前置条件)

| 类 | 文件数 | allocated 字节 | GiB |
|---|---:|---:|---:|
| history(confirmed,已被取代) | 4064 | 16,646,144 | 0.0155 |
| payloads(无保留引用) | 3972 | 9,074,659,328 | 8.4514 |
| pairs(已终结,18/18 history confirmed) | 9 | 36,864 | 0.00003 |
| **合计候选** | **8045** | **9,091,342,336** | **8.4670** |
| (对照)GC 引用保留 C 根 | 1083 | 1,276,395,520 | 1.1887 |
| (对照)保守保留 C 根 | 158 | 315,396,096 | 0.2937 |

辅助产物(可复核):
- `/tmp/codex-reports/storage-cleanup-20261125-protected-raw.json`(原始只读采集,sha256 `784d473b…b30151`)
- `/tmp/codex-reports/storage-cleanup-20261125-protected.json`(逐文件分类/理由)
- `/tmp/codex-reports/storage-cleanup-20261125-protected-summary.json`
- `/tmp/codex-reports/storage-cleanup-20261125-independent-check.json`(BFS 独立复算,逐项一致)
- `/tmp/codex-reports/storage-cleanup-20261125-diff.json`(7028 旧项逐项对比 + 1017 新增明细)

## 8. 判定、风险与执行前置

**清单可用性**
- 旧 7028 项清单:**不能直接当执行清单**——它缺 1017 项新候选(1.0871GiB);但它的 7028 项逐位仍然有效,**可作为已核对子集复用**,用于交叉验证新清单。
- 新清单 8045 项:**可用作 A 阶段执行输入**,但按方案 §4.2 它只是"审查输入",执行时必须在同一生产锁域内重跑闭包 + 重核 dev/ino/size/mtime/allocated + 重新冻结 hold 清单;任何一项对不上就整批停。
- B/C 旧库清单:**仍成立**。8 文件 SHA/size/mtime/inode 全未变;5 个独有 SHA;B=3,456,360,448B、C 全量=7,282,864,128B 不变。新增的唯一注意点:C/sentiment.db-shm 有一个每日 21:15 的读者,隔离观察窗口要覆盖它。

**必须在执行前解决/写入前置的三件事(方案门槛)**
1. 阻断 `deploy.sh` 的 `.r2-protected` 跨树复制(否则 A 清完,deploy 又把 D 的旧版本抄回 C;C 还会继续日增)。
2. 保守保留集动态化:执行时锁内重新冻结(本文件 158 项会变;4 个新增 payload 现 GC 语义下可删)。
3. GC 预算拆分(`check_capacity` 在 unlink 前用全量文件判定)未修时,C 根无法自行回收,只能走方案 §4 的本地-only planner/apply。

**诚实标注**
- 本轮未做 R2 HEAD/GET、未重哈希 payload 内容、未取锁,候选"无引用"是**本地契约**判定,不等于远端已验证每份可恢复。
- 扫描是 04:26 的瞬间快照;之后 05:00 又跑了一轮 deploy,执行前必须重算。
- 未验证过 payload 与远端对象的逐字节一致;未验证 D 根镜像在 C 根之外是否还有第三方恢复通道。
- 96 分钟内可完成,本报告全部数据均产自 2026-11-25 04:26–05:38 CST 的只读调用。
