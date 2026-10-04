# R2 export-guard L5 备份串行 ⇒ upload-etf-hist/upload-accum-nav 确定性 900s 超时死循环(根因落档,2026-10-05)

> **一句话结论**:`_backup_overwritten_keys`(2026-10-03 export-guard L5 新增,commit `4fc1645c0`)对 1718 个 key **串行**逐个 HEAD+COPY 到备份桶(跨境单请求 RTT 实测 0.63~0.7s ⇒ 串行 3436 次 ≈ 2200s),被「总存活时长=900s」看门狗确定性 kill;kill 后 marker 残留 → 下轮强制全量 → 状态文件永不更新 → **死循环**;链路用 verify-r2 补传 + 轻量对账(20/通道抽查 ≈ 1.2%)把「通道从未成功」判成「数据完整」**静音告警**;同一根因让 upload-etf-hist 每轮超长持旧锁 → fetch_news 连续 SKIPPED_LOCKED → schedule_monitor SEVERE。

> **背景(谁发现的、怎么发现的)**:2026-10-05 凌晨,云上 `r2_upload_async.sh` 两轮日志(20261005_021619 / 20261005_051055)暴露 `upload-etf-hist`/`upload-accum-nav` 同一对通道**确定性超时 900s**,同时 schedule_monitor 报出 `fetch_news R2 上传锁连续 3 轮跳过` SEVERE。实施/调研 agent 对云上做**只读调研**(全程无 PUT/COPY,只用 s3_head HEAD 请求),定位到根因=export-guard L5 备份串行 + 看门狗总存活时长判据 + marker 残留死循环 + 轻量对账静音四重叠加。落档依据原报告 `/tmp/r2diag-report.md`(只读调研,2026-10-05),本文为其正式落档副本(§23.5 四件套:本体 + 复现段 + 配套 commit + 索引指针),证据与结论逐字保留不压缩(§5.3 核心保障)。

> **两个决策依据关键事实(漏了=落档失败,原样保留)**:
> ① **失效起点**:`_backup_overwritten_keys` 由 commit **`4fc1645c0`(2026-10-03)** 引入;云端 deploy 日志 **10-03 全天命中 0 次、10-04 02:05 起才出现**「超 900s」⇒ **非 2026-10-05 异步化改动引入**。
> ② **半途备份的陷阱**:`pre-upload/20261005/etf/` = **773 keys**、`accum_nav/` = **763 keys**,约 770 个被 900s kill ⇒ **剩余 ~950 key 无备份、无 checkpoint 幂等**;若只调大看门狗超时而不修备份,这些 key 将被**裸覆盖**(违反 §25)。

---

## 原报告正文(只读调研,2026-10-05,逐字保留)

调研对象:云上 122.51.111.173,两轮 r2_upload_async.sh 日志(20261005_021619 / 20261005_051055)同一对通道确定性超时。
本地镜像与云端 trade-data 代码一致(云端 grep 确认 _backup_overwritten_keys 存在)。

---

## Q1. upload-etf-hist / upload-accum-nav 为什么每轮都超 900s?

### 结论
**900s 是"显式常量"通道超时,且判据是"进程总存活时长"(每5s轮询,进程没退出就累计),不是"停滞/无进展"阈值。**
两通道每轮都进入**全量上传**路径,全量必经 `_backup_overwritten_keys`(2026-10-03 export-guard L5 新增)对 1718 个 key **串行逐个 HEAD+COPY 到备份桶**,跨境单请求 RTT 实测 0.63~0.7s,串行 3436 次请求 ≈ 2165~2405s,**单独这一步就铁定超过 900s**,PUT 甚至还没开始。kill 后**不重试**,只标记 R2_FAIL 继续下一通道。

### 证据

**① 900s 来源 = 显式常量(不是估算函数)**
- `scripts/r2_upload_async.sh:137`: `run_r2_upload "upload-etf-hist" 900 upload-etf-hist`
- `scripts/r2_upload_async.sh:140`: `run_r2_upload "upload-accum-nav" 900 upload-accum-nav`
- `run_r2_upload` 内超时取值逻辑 L89-96:有显式第二参(`^[0-9]+$`)则 `ch_limit=显式值`;估算(`R2_BYTES_TOTAL`/150KB/s×2+240s)仅在无显式时用。两通道均有显式 900,估算不生效。

**② 900s 是"总存活时长"而非"停滞"**
- `scripts/r2_upload_async.sh:97-108`: `while kill -0 $pid; do sleep 5; slept+=5; if slept>=ch_limit; kill -TERM/KILL`。进程只要还活着就累计,不检查字节/请求推进。

**③ 每轮都是全量(状态文件 10-03 后从未更新,marker 死循环)**
- 云端实测:`/home/ubuntu/code/trade-data/data/.r2_etf_hist_state.json` mtime=**Oct 3 21:16**,`.r2_accum_nav_state.json` 同;**marker 残留**:`.r2_etf_hist_uploading.marker`(10-05 05:11)、`.r2_accum_nav_uploading.marker`(10-05 05:31)均存在。
- `upload_r2.py:1049` marker 在每轮上传开始前写(L1198),**只在全部成功时删除**(L1287);被 kill 后残留 → 下轮 `L1102-1105` `marker_stale → 强制全量重传(fail-closed)`。状态文件只在全部成功时原子写(L1285),所以状态永远停在 10-03 → 每轮强制全量 → 每轮备份超时 → 每轮留 marker → 死循环。

**④ 备份阶段串行 + 跨境 RTT ⇒ 数学上必超**
- `upload_r2.py:973-1007 _backup_overwritten_keys`: `for key in r2_keys:` 串行,每 key `s3_head` + `s3_request PUT(x-amz-copy-source)`。
- 云端实测单次 HEAD RTT:**0.63~0.7s**(s3_head keep_alive=False,status=200)。3436 次(HEAD+COPY)×0.65s ≈ **2233s**。
- **备份桶命中证明备份阶段确实在执行**:`s3_head('pre-upload/20261005/etf/158000-all.json', bucket='signal-backup') → status=200`。
- 对照:10-04 deploy 日志 `deploy_20261004_2105.log` 同通道全量模式下 lab 65/65=302s、trade-sim 103/103=580s(均成功),而 etf-hist/accum-nav 超 900s kill —— 差异正在于 etf/accum 的 1718 key 备份串行。

**⑤ 通道串行调用 + kill 不重试**
- `r2_upload_async.sh:127-154` `upload_data_channels()`:16 通道顺序调 `run_r2_upload`,每个 wait 完才下一个(**串行批**)。
- `r2_upload_async.sh:137`: `|| { echo "⚠ ... 失败/超时,继续"; R2_FAIL+="upload-etf-hist"; }` —— **不重试**。
- kill 行:轮1 `⚠ upload-etf-hist 超 900s(估算/显式)未退出,kill pid=358286`;轮2 pid=391379;accum-nav 轮1 pid=362314 / 轮2 395365。

**⑥ 通道体量实测(云端)**
- upload-etf-hist: `static-site/data/etf/*.json` 1718 文件,总 117,232,272 B ≈ 111.8M,平均 65KB,最大 434KB。→ R2 `etf/` 前缀。
- upload-accum-nav: `static-site/data/accum_nav/*.json` 1718 文件,总 26,307,114 B ≈ 25.1M,平均 15KB。→ R2 `accum_nav/` 前缀。
- 均走 `_incremental_upload`(可增量 md5 指纹,但无 checkpoint;全量时不可分片),uploads 阶段 8 线程并发(`_upload_glob` L862)。
- 若跳过备份,纯 PUT 估算:111.8M @ 实测吞吐 326~390KB/s(lab 94.5M/289.7s=326KB/s;trade-sim 195M/498.9s=390KB/s)≈287~343s + 1718/8×0.65s RTT≈140s + purge ≈ **500~550s**,900s 偏紧但勉强;**备份是决定性超时来源**。

**⑦ 死循环起点 = 10-04(周日)同步 deploy 时代,非 async 引入**
- 10-04 六趟 deploy(`deploy_20261004_{0205,0500,1640,1750,2105,2230}.log`)**全部含** `upload-etf-hist 超 900s` 与 `upload-accum-nav 超 900s`(grep 命中 6 个文件;2105 行原文: `⚠ upload-etf-hist 超 900s ... kill pid=268555 释放 deploy.lock`)。10-04 周日 force_full 全量 + export-guard L5 备份串行 = 首超。

---

## Q2. 这两轮到底传完了没有?数据真的完整吗?

### 结论
**上传通道本身从未"传完"——每轮全量重传都死在备份阶段,PUT 从未执行;R2 上 etf/accum_nav 是 10-03 21:16(最后一次成功)的旧数据,与本地(export 自 9-30 未重跑)恰好一致,所以抽查判"完整"。** verify-r2 补传 35/34 个 key 把抽查覆盖范围内不一致项补齐,但"轻量对账"只抽每通道 20 个 key(≈1.2%),判据是"存在+ETag==本地md5"(内容级,比纯存在性硬),**它兜"整通道缺失"绰绰有余,兜不住"少量 key 缺口/部分不一致"**。

### 证据
- 轮1 日志 L21 `[verify-r2] ✓ 对账完成, 自动补传 35 个`;轮2 34 个。verify-r2(`upload_r2.py:2929-3066`)平日模式 = 每通道查状态文件 `changed` 字段(10-03 的)+ 全池均匀抽样 100 个(L2987-2993),8 线程 HEAD,不一致 → `_upload_glob` 自动补传(L3030-3035)。具体 key 清单未取到(tmp_log 超时分支已 rm,诚实标注)。
- "轻量对账" = `cmd_verify_channels`(`upload_r2.py:3119-3162`)→ `_light_check_channel`(`upload_r2.py:3089-3116`):每失败通道全池**均匀抽 `_LIGHT_CHECK_SAMPLE=20`**(L3069),逐个 `s3_head` 判 `status==200 && etag.strip('"')==本地md5`(L3084-3086,内容级)。
- 20/1718 ≈ **1.2%** 覆盖率。
- 关键缺陷:**它把"通道从未成功"静音成"数据完整"**。因为 R2 恰好有 10-03 完整旧数据、本地 export 自 9-30 未重跑(云端实测 etf 目录 mtime=Sep 30 22:27),抽查 20 个全中。**一旦下一交易日 export_etf_hist 重跑出新内容,本地变 R2 不变,死循环仍保持 → R2 永不更新 → 前端 ETF 弹窗/凯利净值永远旧数据;抽查 20 个可能命中(大面积不一致→告警)也可能漏(少量差异落在抽样盲区)。**

---

## Q3. fetch_news 争的是哪把锁?

### 结论
**fetch_news 撞的是 upload_r2.py 入口的旧锁 `/tmp/trade_r2_upload.lock`,不是 async 外层的新锁 `/tmp/trade_r2_upload_async.lock`。async 改动既没"引入"也没"消除"fetch_news 的跳过——fetch_news 撞锁的机制(入口旧锁 + --skip-if-locked)自 2026-09-23 起就存在,async 只是把 R2 上传时段挪到凌晨,03:30 那条 SEVERE 恰落在 async 轮1 窗口内,由 async 子进程持旧锁促成。真正的"引入点"是 10-03 export-guard L5 备份串行让 upload-etf-hist 每轮超时 900s+ 超长持锁。**

### 证据
- fetch_news 上传调用:`scripts/fetch_news.py:713-721` `upload_r2.py --skip-if-locked upload-data-files ...`;L723-729 遇 `SKIPPED_LOCKED` 打印跳过标记。
- 旧锁定义:`upload_r2.py:3209` `lock_path = Path(os.environ.get("R2_UPLOAD_LOCK", "/tmp/trade_r2_upload.lock"))`;入口 L3265-3268 所有 `upload_*/verify_*/purge_*` 命令统一先 `_acquire_r2_upload_lock`(默认排队 7300s;`--skip-if-locked` 立即 SKIPPED_LOCKED + exit 0)。
- async 外层新锁:`r2_upload_async.sh:42-48` `with_lock.py /tmp/trade_r2_upload_async.lock`,只门控 async 自身多实例互斥;async 内**每通道子进程仍抢旧锁**(upload_r2.py 入口 L3265)。
- fetch_news 全天调度:云端 `systemctl cat trade-fetch-news.timer` → `OnCalendar=*-*-* *:01,45:00`(**全天每 30 分钟**,非注释中"7:30-21:00");上次运行 06:01、下次 06:45。
- schedule_monitor SEVERE 时间戳:`[2026-10-05 03:30:01] 检测到 1 个告警: SEVERE: fetch_news R2 上传锁连续 3 轮跳过` —— 正落在 async 轮1(02:16-03:52)窗口内;fetch_news 03:01/03:45 轮次撞旧锁。
- fetch_news 日志 15+ 条连续 `SKIPPED_LOCKED`(fetch_news_launchd.log L2543-2603)。
- **改前对照**:10-04(同步 deploy 时代)deploy 日志同样 `upload-etf-hist 超 900s ... kill`,同步 R2 段同样持旧锁;10-04 21:30~00:30 的 skip 主要由 deploy R2 段 + `etf_national_team_backfill.sh:112`(直调 upload-etf-hist)超长持锁导致。机制未变。

---

## 根因一句话
**upload-etf-hist/accum-nav 每轮全量上传必经 `_backup_overwritten_keys`(export-guard L5,2026-10-03)串行 3436 次跨境 HEAD+COPY(实测 RTT 0.65s ⇒ ~2200s),被"总存活时长=900s"的看门狗确定性处死;kill 后 marker 残留 → 下轮强制全量 → 状态文件永不更新 → 死循环;链路用 verify-r2 补传 35/34 + 轻量对账(20/通道抽查)把"通道从未成功"判成"数据完整"静音告警;同一根因让 upload-etf-hist 每轮超长持旧锁 → fetch_news 连续 SKIPPED_LOCKED → schedule_monitor SEVERE。**

---

## ③ 900s 判据该换成什么(建议方向,不写代码)
1. **停滞判据替代总耗时判据**:看门狗只判"无进展"(字节量/已传文件数在 N 分钟内无增长)才 kill,进程有进展就放行(业界 rclone/rsync/curl/systemd 全部按 IO 空闲判死,见 memory `batch-upload-arch-industry-refs`)。这是根治"全量备份慢但健康被误杀"的关键。
2. **备份阶段并行化或减量**:1718 key 串行 HEAD+COPY 改为 8 线程并发(与 PUT 同模式),或按"状态文件里 R2 已有且指纹未变"跳过(备份只覆盖"将要变"的 key)。不解决这里,任何判据都白搭。
3. **通道超时值按"实际工作内容"动态**:全量(备份+PUT)时给足(如 30min+);增量时给小值。与现状"显式 900"相反。

## ④ "失败通道被轻量对账静音"风险评估
**中偏高,需修复。** 内容级判据(ETag==md5)比纯存在性好,但:①覆盖仅 1.2%(20/1718);②静音了"通道从未成功 + 死循环 + R2 停止更新"这一事实——本轮恰好靠"R2 旧数据与本地一致"蒙混,下一交易日 export 重跑后 R2 将永久陈旧;③若只有少量 key 落在抽样盲区,前端将静默展示旧数据且无任何告警。**建议:轻量对账通过时,若该通道本轮是"全量+超时 kill",至少单独告警"上传未完成",不能与"数据完整"混为一谈。**

## ⑤ 建议回退还是有保留地继续用?
**有保留地继续用 async 架构,不回退。** 理由:回退到 deploy 同步跑 R2 同样死(10-04 六趟同步 deploy 已证明 upload-etf-hist/accum-nav 同样 900s 超时),async 拆出主链的方向本身正确。保留 async + 必须修三件事:①`_backup_overwritten_keys` 并行/减量(根因);②看门狗改停滞判据(防健康全量被误杀);③轻量对账对"全量+超时 kill"通道保留告警(防静音)。修完这三项,死循环自然断、fetch_news 撞锁 SEVERE 也消失。

---

## 补充:数据完整性决定性证据(主控推翻"新旧巧合"子结论后重查,2026-10-05)

### 补充结论
**R2 上 etf-hist / accum-nav 两通道当前 = 大概率完整(抽样+最新档全部内容级一致,漂移 0、缺失 0)。本地内容自 10-03 21:16(R2 上次成功上传)后 C 档/A 档指纹均未变 ⇒ R2 旧数据与本地一致是"必然",非"巧合漏检"。系统当前"只慢不坏",但死循环让状态文件永不更新 ⇒ 下一交易日 export 出新内容时上传通道每轮死在备份段、PUT 不执行,R2 将永不更新,届时"只慢"升级为"坏"。**

### 决定性证据(云端只读 HEAD,全程无 PUT/COPY)
**① 逐 key HEAD 对账(200+25 样本,内容级 md5 比对)**
- etf-hist:最新50+均匀50(seed42)去重后 100 样本 HEAD → **一致=100 漂移=0 缺失=0**(再补 seed7 均匀 20 → 20/20 一致)。
- accum-nav:同法 97 样本 HEAD → **一致=97 漂移=0 缺失=0**。
- lab 最新5、index 最新5 HEAD → 全一致。
- 覆盖率:etf-hist 120/1718≈7.0%,accum-nav 97/1718≈5.6%。**覆盖内全一致;不能 100% 排除抽样盲区少量缺口,但强证据支持完整。**
- 方法:`s3_head(key, keep_alive=True)` 只发 HEAD(upload_r2.py:508-562,签名确认无 PUT/COPY),etag 去引号比对本地 `_file_md5` 整文件 md5。

**② 本地内容自 10-03 未变(用正确指纹口径,主控推翻的是我原"整文件md5"误用)**
- 状态文件 `.r2_etf_hist_state.json` 存 **C 档指纹**(`_etf_hist_md5`,upload_r2.py:917-932,剔除 exported_at);`.r2_accum_nav_state.json` 存 A 档整文件 md5。
- **etf-hist:C 档复核 30/30 相同**(状态 C 档指纹 == 当前本地 C 档指纹);etf 文件 mtime 全部 2026-09-30_22:27(批量重写后未动)。
- **accum-nav:A 档复核 30/30 相同**;文件 mtime 全部 2026-10-05_05:08(export 重写,mtime 变但内容 append-only 无新净值日 → md5 未变)。
- ⇒ 两通道本地内容在 10-03 21:16(R2 上次成功上传)之后**没有数据变化**,R2 旧数据与本地一致是必然。我原"9-30 export 未重跑"的时间点是错的(accum 05:08 确实重写),但"内容未变导致 R2 一致"的结论在正确口径下成立。

**③ verify-r2 判定口径(不是全量)**
- `cmd_verify_r2`(upload_r2.py:2929-3066)平日模式:**每通道 to_check = 状态文件 `changed` 字段 + 全池均匀抽样 100**(L2987-2993),`_check` 用「本地整文件 md5 vs R2 ETag」(L3004-3016)不符即 `_upload_glob` 补传(L3030-3035)。
- **两通道状态文件 `changed` 均为 0 条** → 平日 to_check = 仅抽样 100。34/35 是**跨全部 _R2_CHANNELS 的累计补传数**(具体分布未取到,tmp_log 超时分支已删,诚实标注)。
- **盲区明确**:当日 export 若真出新内容,不在旧状态 `changed` 里 → verify-r2 只能靠抽样 100(≈5.8%)兜底,非全量;且状态文件因上传死循环永不更新,`changed` 永远指不到新文件 ⇒ 下交易日风险放大。

**④ 备份保护实际状态(§25 状态)**
- `_list_keys`(只读,upload_r2.py:1971)实测:`pre-upload/20261005/etf/` = **773 keys**,`pre-upload/20261005/accum_nav/` = **763 keys**。
- 即每次全量备份到 ~770 个 key 就被 900s kill,**备份本身半途而废**:前 ~770 key 有 `pre-upload/<日期>/` 备份,后 ~950 key 无备份且无 checkpoint/幂等 → **§25「覆盖前备份」当前不完整**;若未来修复看门狗使 PUT 真正执行,后 ~950 key 将裸覆盖无备份。

### 严重性修正
原报告第④条"下一交易日 export 重跑后 R2 永久陈旧、抽查可能漏"的风险判断**上调确认**:不是"可能",而是**必然**——本地内容一变,upload-etf-hist/accum-nav 全量死循环依旧死在备份段,PU 从不执行,R2 永不更新,verify-r2 抽样 100(5.8%)与轻量对账 20(1.2%)都覆盖不到全部 key,存在静默陈旧窗口。当前"只慢不坏"的窗口在下一个 export 新内容时关闭。

---

## 复现段(全部命令只读;本段每条命令已在 2026-10-05 实测,输出与正文一致)

> 云上命令需带 ssh(本地 mac 无云端数据/日志);本地命令在 trade-data 或 trade 仓库根跑。只读,全程无 PUT/COPY。

**① 云端 deploy 日志「超 900s」命中数(证实失效起点 10-04 02:05 起、10-03 全天 0)**
```bash
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'timeout 25 grep -ac "超 900s" /home/ubuntu/code/trade-data/data/logs/deploy_20261004_0205.log'
# 实测输出:2
# 全量对照(10-03 全部 0;10-04 起命中):
#   deploy_20261003_{0205,0228,0500,0522,0916,0940,1534,1558,1640,1712,1750,1813,2105,2129}.log = 0 (14 趟全 0)
#   deploy_20261004_0205=2 / 0500=2 / 1640=5 / 1750=5 / 2105=4 / 2230=5
```
**② 云端 marker 残留(证死循环:写于上传开始、仅全成功才删)**
```bash
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'timeout 25 ls -l /home/ubuntu/code/trade-data/data/.r2_etf_hist_uploading.marker /home/ubuntu/code/trade-data/data/.r2_accum_nav_uploading.marker'
# 实测输出:
#   -rw-r--r-- 1 ubuntu ubuntu 30 Oct  5 05:11 .r2_etf_hist_uploading.marker
#   -rw-r--r-- 1 ubuntu ubuntu 30 Oct  5 05:31 .r2_accum_nav_uploading.marker
```
**③ 本地代码锚点(证实 `_backup_overwritten_keys` L973 定义 / L1252 调用)**
```bash
cd /Users/linhuichen/code/trade-data   # 或 trade 仓库根
grep -n "_backup_overwritten_keys" scripts/upload_r2.py
# 实测输出:
#   973:def _backup_overwritten_keys(r2_keys, label):
#   1252:        _backup_overwritten_keys(
```
**④ 云端备份半途实态(证实 §25 备份不完整:~770 key 被 kill、~950 key 无备份)**
```bash
# 云端,用 upload_r2.py _list_keys(只读 S3 list-type=2 分页枚举,无 PUT/COPY)列备份桶前缀 key 数:
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 "timeout 25 bash -c 'cd /home/ubuntu/code/trade-data && REPO=/home/ubuntu/code/trade-data GIT_REPO=/home/ubuntu/code/trade-data /home/ubuntu/code/trade-data/.venv/bin/python -c \"import sys; sys.path.insert(0, \\\"scripts\\\"); from upload_r2 import _list_keys; print(len(_list_keys(\\\"pre-upload/20261005/etf/\\\", bucket=\\\"signal-backup\\\")))\"'"
# 实测输出:773
# accum_nav 同法,prefix 换 pre-upload/20261005/accum_nav/ → 实测 763
```
> 注:④ 的 773/763 于 2026-10-05 落档日重跑确认(上述命令实测输出 773 / 763,与正文「补充④」一致);仅 HEAD 枚举,无写操作。

**⑤ 云端状态文件 mtime(证状态永远停在 10-03 → 每轮全量)**
```bash
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'timeout 25 ls -l /home/ubuntu/code/trade-data/data/.r2_etf_hist_state.json /home/ubuntu/code/trade-data/data/.r2_accum_nav_state.json'
# 实测输出:两个 state 文件 mtime 均为 Oct 3 21:16
```
