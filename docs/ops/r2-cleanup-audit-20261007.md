# R2 老账号清理批 · 只读审计报告(2026-10-07,休市日)

> 任务:老账号两桶(`signal-backup` + `signal-data`)A 档 / C 档清理前的**只读审计 + 备份/恢复方案**;裁决 #179 与 #185③ 的口径矛盾;量化 #197 云上灾备仓膨胀。
> **全程只读**:未 PUT / 未 DELETE / 未改云上任何文件 / 未跑 git prune·gc / 无任何外发。本报告所有删除动作均为"建议",待拍板后由独立执行步骤实施(§25:备份做完并实测可恢复之前,一个字节都不许删)。
> 取证方式标注:【云上实测】= 2026-10-07 ssh `ubuntu@122.51.111.173`(`~/tdsignal.pem`)用生产 venv `/home/ubuntu/code/trade-data/.venv/bin/python` 加载 `scripts/upload_r2.py` 的 `s3_request`/`_list_keys` 列桶(探针经 ssh stdin 管道传入,云上未落盘;脚本全文见 §8);【代码】= 本地仓库 `文件:行号`(与云上 `trade-data-signal` @ `2c37425c5` 同版本);【日志】= 云上 `trade-data/data/logs/staticdata_backup_async_2026*.log`。
> 数字口径:GiB=1073741824 B;MB=1048576 B。UTC 的 mtime 原样标注。

---

## 0. 结论总览

| # | 结论 | 判定 |
|---|---|---|
| 1 | **口径矛盾裁决**:合并 #178 后 `_prune_large_json` 目标桶=新桶 `signal-backup2`,老桶 legacy **断链成孤儿,不会被自动清**(#185③ 正确;#179 的"10-06~10-08 清空"预测已失效)。五层证据见 §1 | **确认** |
| 2 | 老桶 legacy 实测 **27,673 对象 / 266.1 MiB 一个没少**(09-29 目录 age=8 天、09-30 age=7 天,均过 7 天宽限) | **需手动清(或不处理则永久滞留)** |
| 3 | A 档实测 **21 个对象 / 163.93 MiB**,与 10-05 评估逐位一致;消费方复核=前端零引用 | **可清**(建议先 GET 归档,见 §3) |
| 4 | C 档 legacy **orphan=0**:27,673 对象的全部 15,805 个 rel 在 flat 均有当前版 ⇒ 删除不丢"路径覆盖",仅丢 9-29/9-30 历史快照(设计既定弃置)。**消费方=restore-large-json.sh `--date`/`--all`**(历史恢复能力,设计上本就 7 天到期) | **可清**(建议先 GET 归档,见 §4) |
| 5 | #197 云上灾备仓:loose 17,245 个 / 1.31 GiB,其中 unreachable **17,077 blob / 解压 5.79 GB**;4 个 tmp_pack 残留 21.5 MiB;gc.log 警告在位;远端 origin 完整同步(0/0) | **可清(备份后)**,见 §5 |
| 6 | 今天两桶合计 **10.676 GiB**(8.43+3.03 GB):lifecycle 已自动回收 313 MB(backup 4 对象 + weekly 2 + claude-backup 2) | 账本更新 |

**建议执行顺序**(均待拍板;每步先备份→验证→删):
1. A 档 21 对象(163.93 MiB;先 GET 归档再逐 key DELETE,§3)
2. C 档 legacy 27,673 对象(266.1 MiB;先 GET 归档再按日期目录逐 key DELETE,§4)
3. #197 仓瘦身(备份→`git prune`/`git gc`;§5)——独立窗口,建议错开每日备份链时点

---

## 1. 🔴 口径矛盾裁决:#178 合并后 `_prune_large_json` 目标桶

**争议**:#179 定案写「legacy 由代码 7 天宽限自动清,10-06~10-08 内清空」;#185③ 写「合并 #178 后 `_prune_large_json` 目标桶已变成新桶 ⇒ 老桶 legacy 断链成孤儿」。**裁决:#185③ 成立。**

### 五层证据链

**① 代码(唯一调用点无 bucket 参数,默认桶=新桶)**:
- `scripts/upload_r2.py:286` `BACKUP2_BUCKET = os.environ.get("R2_BACKUP2_BUCKET", "signal-backup2")`
- `scripts/upload_r2.py:299` `BACKUP_BUCKET = os.environ.get("R2_BACKUP_BUCKET", BACKUP2_BUCKET)` ← 默认=新桶
- `scripts/upload_r2.py:2763` `bkt = bucket or BACKUP_BUCKET`(prune 内部取桶)
- `scripts/upload_r2.py:3231` **全仓唯一调用点** `_prune_large_json()` —— 无参数 ⇒ `bkt = signal-backup2`
- 全仓 grep 无第二调用点;`upload-large-json` CLI(`:3953`)与 async 链路(`scripts/staticdata_backup_async.sh:193`)走的都是同一函数,无 `R2_BACKUP_BUCKET=signal-backup` 显式覆盖(仅注释里作为测试隔离手段提及)。

**② 生产等价环境实测(今天)**:云上 `.env` `R2_BACKUP_BUCKET` 计数=0(无覆盖)、`R2_BACKUP2_BUCKET` 计数=1;实测 `BACKUP_BUCKET = signal-backup2`(会 Dump 见 §8①)。

**③ 日志(切桶时点=prune 断链时点,逐轮吻合)**:
- 切桶前最后一轮 `staticdata_backup_async_20261005_122512.log`:prune 输出 `signal-backup large-json/ 无待清理旧日期目录(固定前缀 31673 个唯一副本保留)` ← **打在老桶**
- 切桶后(10-05 16:52 起)所有轮次:`165200 / 180051 / 211626`(10-05)+ 10-06 五轮 + 10-07 两轮(**共 10 轮**)全部 **prune 行数=0**——新桶无 legacy 目录 ⇒ `_prune_large_json` 走 `:2777-2778` 空判 `return 0`,**静默不打印**(故"日志无 prune 行"本身不是异常,而是新桶无 legacy 的证明)
- 全期 grep:老桶 prune 输出 22 次(其中 3 次真删 8 key:10-02 23:44 / 10-04 04:07 / 10-05 00:32);**`signal-backup2` 的 prune 输出 0 次**

**④ 实测(决定性)**:今天 10-07 老桶 legacy 27,673 对象**一个没少**(09-29: 11,875 / 09-30: 15,798)——09-29 目录 age=8 天、09-30 age=7 天,均超 `:2788` 的 7 天宽限;若 prune 仍作用于老桶,10-06/10-07 起就该被删。

**⑤ 佐证**:今天在云上跑 `_prune_large_json(dry_run=True)`(默认桶)→ `return 0`(它在看新桶,新桶无 legacy)。

### 裁决结论
- **老桶 legacy 不会被任何自动通道清**(无 lifecycle 规则 + 代码断链);要清必须**手动**(C 档 §4),不清则永久滞留 266.1 MiB。
- #179 的"10-06~10-08 内清空"预测**已失效**:其模型(老桶 prune 在跑+宽限到期自动删)成立于切桶前;实际 10-05 16:52 切桶打断了该路径(切桶前最后一轮 10-05 12:25 时两目录均在宽限内,此后 prune 转新桶)。

---

## 2. 两桶现状实测(2026-10-07,【云上实测】)——与 10-05 对比

### 2.1 `signal-backup`(私有备份桶):66,000 对象 / 8,434,418,789 B = **7.86 GiB**

| 前缀 | 对象数 | 字节 | GiB | 10-05 对比 | last_mtime(UTC) |
|---|---|---|---|---|---|
| pre-upload/ | 6,585 | 3,453,993,283 | 3.217 | 不变 | 2026-10-05T04:55 |
| mac-backups/ | 1 | 2,278,230,346 | 2.122 | 不变 | 2026-10-04 |
| backup/ | 24 | 1,319,114,393 | 1.228 | **-4 对象 / -218.7 MB**(lifecycle 逐日到龄) | 2026-10-04 |
| large-json/ | 59,346 | 733,530,289 | 0.683 | 不变(flat 31,673 + legacy 27,673) | 2026-10-05T04:31 |
| weekly/ | 6 | 312,556,531 | 0.291 | **-2 对象 / -92.9 MB**(9-07 层 10-05 到龄) | 2026-09-28 |
| monthly/ | 8 | 303,160,886 | 0.282 | 不变 | 2026-10-01 |
| claude-backup/ | 28 | 22,852,892 | 0.021 | **-2 对象 / -1.6 MB**(9-06/07 层到龄) | 2026-10-04 |
| decommissioned/ | 2 | 10,980,169 | 0.010 | 不变 | 2026-09-03 |
| **合计** | **66,000** | **8,434,418,789** | **7.855** | 10-05: 66,008 / 8,747,606,224(8.147 GiB) | — |

⇒ 两天内 lifecycle 已自动回收 **313.2 MB**(backup/weekly/claude-backup),与规则推算一致。
⇒ large-json/ 59,346 全量自 10-05 04:31Z 后**零变化**(老桶无写入)。

### 2.2 `signal-data`(公开主桶):31,484 对象 / 3,029,369,514 B = **2.821 GiB**

主要前缀(完整表):data 323 / 623,736,225;nav_bucket 256 / 561,548,829;fund_nav 26,458 / 556,807,260;trade_sim_data 504 / 385,778,698;trade_sim 103 / 204,784,968;offshore_fund 7 / 156,048,848;industry 134 / 128,844,540;etf 1,718 / 117,162,640;lab 65 / 99,056,999;(root) 5 / 80,372,044;index 173 / 68,875,649;accum_nav 1,718 / 26,249,770;test 1 / 10,485,760;public_fund 13 / 7,251,298;fund_score 2 / 2,360,245;probe 3 / 5,723;r2test 1 / 18。
- 活数据在正常滚动:`data/overview.json` 1,830,845 B @ 10-06T21:15Z、`data/intraday_snapshot.json` @ 10-06T18:28Z、`industry/` 134 对象 @ 10-05T10:27Z——**均证实活前缀在变化,A 档对象 mtime 冻结**(见 §3)。
- A 档所在的 `(root)` 5 对象 / 80,372,044 B 与 10-05 逐位一致。

### 2.3 两桶合计:11,463,788,303 B = **10.676 GiB**(10-05: 10.968 GiB)

---

## 3. A 档:逐 key 清单(21 对象 / 171,894,762 B = 163.93 MiB,全部在 `signal-data`)

> 清单 = 逐 key 实测(【云上实测】,含 **体积 + mtime(UTC) + ETag + 所在桶**);ETag 为该对象内容 md5(单段上传,已抽样验证,§3.5)。
> 消费方复核:见 §3.4;**恢复路径/备份方案:见 §3.6/§3.7**。

### 3.1 A1 industry-* 8-29 死快照(10 对象 / 80,963,161 B)

| # | key(桶 signal-data) | 体积 B | mtime(UTC) | ETag(=md5) |
|---|---|---|---|---|
| 1 | data/industry-1y.json | 6,738,441 | 2026-08-29T06:11:29.660Z | 004b4ec7111eef4a8dc503717bfa948b |
| 2 | data/industry-3m.json | 2,492,395 | 2026-08-29T06:11:29.884Z | 6657acb34e2201565a8241cbcece8263 |
| 3 | data/industry-3y-concepts.json | 10,209,777 | 2026-08-29T06:11:31.439Z | d60b4d9c88c60d25b9b0a260212f6ab5 |
| 4 | data/industry-3y-meta.json | 4,860 | 2026-08-29T06:11:30.443Z | b2da2a15d9a2a1880684470026b7bef9 |
| 5 | data/industry-3y.json | 9,601,767 | 2026-08-29T06:11:31.938Z | 812f38218e8eded6c3d73fcc04d3813b |
| 6 | data/industry-5y-concepts.json | 15,664,402 | 2026-08-29T06:11:35.409Z | 11b7a5271bd5d97b50febfeec8de6d9f |
| 7 | data/industry-5y-meta.json | 4,860 | 2026-08-29T06:11:32.527Z | b2da2a15d9a2a1880684470026b7bef9 |
| 8 | data/industry-6m.json | 3,966,034 | 2026-08-29T06:11:32.443Z | b47ec59420fec7dbf32706a282093607 |
| 9 | data/industry-all-concepts.json | 32,275,765 | 2026-08-29T06:11:36.113Z | 429b506dba1ec29806483bde168ca429 |
| 10 | data/industry-all-meta.json | 4,860 | 2026-08-29T06:11:32.456Z | b2da2a15d9a2a1880684470026b7bef9 |

- 10 对象 mtime **全部 2026-08-29T06:11Z,之后 39 天零更新** ⇒ 死快照确认。
- 40 天无写入通道:upload_r2.py:1872 `_DATA_EXCLUDE_PREFIXES = ("industry-", …)`(data-large 通道排除)+ upload-industry 只写 `industry/` 前缀(:1657-1663 注释)⇒ 无任何通道回写 `data/industry-*`。

### 3.2 A2 测速/探测/连接测试残留(8 对象 / 89,134,701 B)

| # | key(桶 signal-data) | 体积 B | mtime(UTC) | ETag |
|---|---|---|---|---|
| 1 | __speedtest_20mb.bin | 20,971,520 | 2026-09-13T04:34:08.863Z | f7353682390b0fcd707730f9bef1d2c5 |
| 2 | __speedtest_50mb.bin | 52,428,800 | 2026-09-13T04:38:12.745Z | 2048d4a10a0619745ecdcd33b68f2d8a |
| 3 | __speedtest_5mb.bin | 5,242,880 | 2026-09-13T04:32:10.642Z | 7d7a6dd7e37454c6a82992eabe7a4613 |
| 4 | test/speedtest-10m.bin | 10,485,760 | 2026-09-13T05:08:53.139Z | f1c9645dbc14efddc7d8a322685f26eb |
| 5 | probe/cf-egress-202610021509514.json | 5,613 | 2026-10-02T15:17:56.276Z | 9acf2244cc966eb6ac8bfc8709189128 |
| 6 | probe/ping-202610021516514.json | 55 | 2026-10-02T15:16:51.619Z | 1c4b38a15fcd8127f7f07b46518fd536 |
| 7 | probe/ping-202610021544518.json | 55 | 2026-10-02T15:44:52.097Z | 3b4b9d6fbda276cf1ca7743ead0e4cc8 |
| 8 | r2test/r2test.txt | 18 | 2026-07-20T10:23:23.715Z | 1af49f952ad5b55c5dd367418ce2680c |

### 3.3 A3~A5 根级孤儿与残留

| # | key(桶 signal-data) | 体积 B | mtime(UTC) | ETag | 性质 |
|---|---|---|---|---|---|
| 1 | overview.json(根级) | 1,585,628 | 2026-08-26T15:32:16.394Z | caac4fa523a170a8beea04cb3ea9685b | 8-26 根级孤儿(GET 抽查头部 `{"date":"20260826",…}`;现行版= data/overview.json 1,830,845 B @ 10-06) |
| 2 | sss.jpg(根级) | 143,216 | 2026-07-20T09:59:30.165Z | 7759f8b69ff108a3cdbafa73c5b4ffee | 7-20 素材;本机 mdfind/find 均无副本 |
| 3 | data/signal_kelly_backtest.json.gz | 68,056 | 2026-08-28T12:35:28.618Z | ea815672e83e5ee5e5606115c2beb243 | 唯一 .gz 残留(前端已统一 .json) |

### 3.4 消费方复核(§25「有无消费方」,今天重核)

| 对象组 | 复核结果 | 证据(命令见 §8④) |
|---|---|---|
| data/industry-* | **前端零 fetch**;worker 仅缓存头规则匹配(`worker/headers.js:107-109` 是 `/data/industry-*-indices/` 缓存规则,非消费);现行加载全走 `/r2/industry/…`(`static-site/app.js:25451-25457`);上传通道已 exclude | grep 仅命中 worker 缓存规则 + upload 脚本注释 |
| __speedtest_*/test/probe/r2test | **全仓零引用**(js/py/sh) | grep 无前端/脚本消费 |
| 根级 overview.json | **零消费方**:前端/worker/脚本全走 `data/overview.json`(worker/dataQuery.js:45,77,363;app.js L2698 `./data/overview.json`;sw.js:157 是 `endsWith('/overview.json')` 通用规则,不构成根级消费) | grep `/overview.json` 无根级构造 |
| sss.jpg | **零引用**(站内 og 图用 `https://ss.fx8.store/og.png`);风险=若曾被站外平台引用,删后该外链 404(不可程序化穷尽,诚实标注) | grep `sss.jpg` 零命中 |
| data/signal_kelly_backtest.json.gz | 前端已统一 `.json`(memory fetchjson-skip-gz);.gz 唯一残留 | 现役 `.json` 源在位(见 §3.6) |

### 3.5 尺子先验 + 抽样 GET 逐位(证明"ETag=md5"可作备份对账尺子)

云上实测(只读 GET):
- `GET r2test/r2test.txt`(18 B)→ 内容 md5 `1af49f952ad5b55c5dd367418ce2680c` **== 其 ListObjects ETag**;注入 1 字节后 md5 `d882e2dc34d90d9d8ce8408dce054031` **≠ ETag(可检出)** ⇒ 尺子有效。
- `GET probe/ping-202610021516514.json`(55 B)→ md5 `1c4b38a15fcd8127f7f07b46518fd536` == ETag ✓
- `GET overview.json`(1,585,628 B)→ md5 `caac4fa523a170a8beea04cb3ea9685b` == ETag ✓
- 本机 `static-site/data/industry-3y.json` md5 `812f38218e8eded6c3d73fcc04d3813b` **== R2 对象 ETag(逐位一致)** ⇒ 该对象本地已有逐位同款副本(§3.6 恢复路径实证)。
- 对 21 个 A 档对象,**全量 ETag 已记录**(§3.1~3.3 表)⇒ 执行阶段备份对账基准就绪。

### 3.6 恢复路径(逐组,§25 门槛)

| 组 | 恢复路径 | 判定 |
|---|---|---|
| A1 industry-*(10) | ① `industry-3y.json`:本机 `static-site/data/industry-3y.json` **逐位同款**(9,601,767 B,md5==ETag,§3.5);②其余 9 个:本机 `static-site/data/` **10 个 industry-*.json 全在位**(2026-10-07 复验;其中 9 个为 9-12/9-13 版),云上 `static-site/data/` **9 个在位、缺 industry-3y.json**(mtime 10-07 05:06,每日更新)——可重传但内容为"新版"(非 8-29 版),职责级可恢复;③无需恢复:现行数据服务走 `industry/` 前缀,前端零引用 | **可恢复(①逐位/②职责级)** |
| A2 测速/探测(8) | 重新生成:`dd if=/dev/zero bs=1M count=N` 重造 speedtest;probe 重跑 `docs/ops/cf-edge-egress-probe-20261002.md` 探测流程;r2test 一行重写 | **可恢复(可再生)** |
| A3 根级 overview.json | 无源重建(8-26 版唯一);现行版是 `data/overview.json`(内容为新版)。建议:删除前 GET 归档(1.5 MiB,零成本) | **可清(建议先 GET 归档)** |
| A4 sss.jpg | 本机无素材(mdfind + find 空);无源重建。**建议:删除前 GET 归档(143 KB)** | **可清(必须先 GET 归档,否则写不出恢复路径)** |
| A5 .gz | 从 `data/signal_kelly_backtest.json` 现行版重生成 gz(源在位:本机 563,967 B @ 9-22 + 云上 563,666 B @ 10-07) | **可恢复(重生成)** |

### 3.7 备份方案(A 档执行阶段)

- **备到哪**:全部 21 对象 GET 打包(163.93 MiB,含 4 个 <1MB 的"无源"对象 + industry 全量),`tar.zst` 归档 → 传 R2 新桶 `signal-backup2/decommissioned/`(语义=退役归档)+ 本机留一份。预估传输:云上跨境 ~150 KB/s ≈ 20 分钟(建议夜间跑,避开备份链时点)。
- **实测可恢复(执行阶段对账口径,尺子已先验 §3.5)**:
  1) 清单全量比对:21/21 key 备份包内存在,MISSING=0(清单=§3.1~3.3);
  2) 逐位对账:`md5(包内文件) == ETag`(21 个 ETag 已备,§3.1~3.3);
  3) 抽样取回:从归档解包 2 个对象 PUT 回原 key 实测(可选;GET 侧内容对账已足够)。
- **风险**:①公开桶属性——`signal-data` 对外可读(worker `/data/*` rewrite + 直链域名),删 A 档对象后,若存在站外历史外链(尤其 `sss.jpg`、根级 `overview.json`)会 404(站内零引用;站外不可穷尽,诚实标注);②非 §23.7 冻结面(均为残留/死快照,无已上线功能依赖)。
- **删除命令形态**(执行阶段,逐 key 精准 DELETE、禁前缀通配):`s3_request('DELETE', <key>, bucket='signal-data')` 逐 keys(21 次),见 §8⑤。

---

## 4. C 档:老桶 `large-json` legacy(27,673 对象 / 279,046,499 B = 266.1 MiB)

### 4.1 对象数 / 前缀形状 / 体积分布(【云上实测】)

| 日期目录 | 对象数 | 字节 | mtime 范围(UTC) | 形状 | 体积分布 |
|---|---|---|---|---|---|
| large-json/2026-09-29/ | 11,875 | 150,262,808 | 09-28T16:09 ~ 09-29T12:56 | 4 子目录(accum_nav/ etf/ fund_nav/ trade_sim/)+ 7 根层文件(accum_nav_map, offshore_fund_{fee_detail,performance,purchase_status,risk_indicator}, signal_kelly_trades, signal_kelly_trades_sdc) | <1KB:552 / 1-10KB:10,122 / 10-100KB:1,160 / 100KB-1MB:35 / 1-5MB:3 / >5MB:3 |
| large-json/2026-09-30/ | 15,798 | 128,783,691 | 09-29T16:51 ~ 09-30T00:49 | 3 子目录(accum_nav/ etf/ fund_nav/)+ 1 根层文件(accum_nav_map.json.gz) | <1KB:549 / 1-10KB:14,052 / 10-100KB:1,163 / 100KB-1MB:33 / 1-5MB:0 / >5MB:1 |
| **合计** | **27,673** | **279,046,499** | — | — | 91.6% 对象 ≤10KB |

- mtime 分布(证明=当日上传的动作产物):09-29 目录 mtime 09-28=5,730 / 09-29=6,145;09-30 目录 mtime 09-29=13,282 / 09-30=2,516。
- 与 10-05 对比:对象数/字节/分布**逐位一致**(完全静止)。
- flat 对照:31,673 / 454,483,790 B,mtime_max=10-05T04:31Z;首段 top:fund_nav 26,458 / nav_bucket 256 / trade_sim 504 / etf 1,718 / signal_kelly_trades_parts 383 / signal_kelly_trades_sdc_parts 391 / index 173 / lab 65 / accum_nav 1,718 + 7 个根层 .gz。

### 4.2 集合关系(关键新证据):orphan = 0

- legacy 的 distinct rel = **15,805**;其中"rel 不在 flat"的 **orphan 对象数 = 0 / 0 字节**(逐 key 穷举,见 §8②)。
- ⇒ 每个 legacy 对象对应的路径在 flat(31,673)均存在**当前版**;删除 legacy **不丢任何"路径缺备份"**,仅丢"9-29/9-30 历史版本快照"。
- ⇒ `restore-large-json.sh --all`(并集恢复)在删 legacy 后**能力不受实质损失**(所有 rel 都能从 flat 取到;"若有文件只在更老 legacy 会警告"的场景实测不存在)。

### 4.3 消费方与 §25 判定

- **消费方** = `scripts/restore-large-json.sh`:`--date 2026-09-29|09-30`(历史按天快照恢复,L20-21)与 `--all`(固定前缀∪全 legacy 并集,L23-29)。无任何线上服务/前端读取(私有桶,不绑公开域名)。
- **恢复路径**:①逐位重建=无源(过渡期快照,不在 staticdata git;设计语义=7 天宽限后整目录 DELETE,代码注释 upload_r2.py:2748-2749);②历史时点能力=随删除失效(设计既定到期);③**建议执行阶段先 GET 归档(266.1 MiB)**,归档后恢复路径=归档包(完全满足 §25)。
- **§25 判定**:**可清**(推荐"先归档再删";若接受"设计既定作废"语义也可直接删——orphan=0 保证现役数据零影响)。
- **风险**:①非唯一副本问题(orphan=0);②`--date` 历史快照能力丧失(设计内);③§23.7 冻结面=否(私有桶内部备份,非已上线功能数据)。

---

## 5. #197 云上灾备 git 仓膨胀(只读量化)

> 仓:`ssh -i ~/tdsignal.pem ubuntu@122.51.111.173` ⇒ `/home/ubuntu/code/trade-data-signal-staticdata`;**只读**,未跑任何 prune/gc。

### 5.1 `git count-objects -vH`(2026-10-07)

```
count: 17245          # loose 对象数
size: 1.31 GiB        # loose 磁盘占用
in-pack: 182073       # pack 内对象数
packs: 17
size-pack: 1.24 GiB
prune-packable: 0     # 可被 prune 的(已打包且冗余)=0
garbage: 4            # 4 个 tmp_pack_* 残留
size-garbage: 21.50 MiB
```
- `.git` 总 2.6 G(其中 `.git/objects/pack` 1.3 G);工作区(含数据)8.4 G。
- **gc.log 存在**(`.git/gc.log`,mtime 2026-10-07 05:01):`warning: There are too many unreachable loose objects; run 'git prune' to remove them.` ⇒ auto-gc 因不可达 loose 过多**拒绝自动回收**(保护机制),此警告会反复出现(每轮 git 操作)。
- **unreachable 实测**:`git fsck --unreachable` = **blob 17,077**(≈99% 的 loose 是 unreachable;首轮统计另见 1 个 tree,两次统计差 1 个对象,不影响结论,见 §7);`git cat-file --batch-check` 量化:blob 合计 **5,791,906,591 B(解压后 5.79 GB)**,最大单 blob 19,742,998 B(~19.7 MB)。
- **loose 对象的 mtime 日分布(膨胀发生期定位)**:2026-09-29=5,466 / 2026-09-30=5,357 / 2026-10-01=3,506 / 2026-09-28=2,748 / 2026-10-07=175(其余日期合计 ≈0)⇒ **loose 几乎全部产生于 9-28~10-01 四天**——与"#126 large-json 移出 git(`rm --cached`)+ 10-01 gitignore 受管块改造"窗口吻合(reflog 未保留其引用路径,故呈 unreachable;全为 blob、0 个 unreachable commit 佐证"add 后未入库的中间态"机理)。
- **tmp_pack 残留 4 个**(`ls -la .git/objects/pack/`):

| 文件 | 大小 B | mtime |
|---|---|---|
| tmp_pack_nl6mxH | 8,650,752 | 2026-10-03 22:45 |
| tmp_pack_SBiN3T | 8,650,752 | 2026-10-03 23:01 |
| tmp_pack_tmh7Wy | 917,504 | 2026-10-06 01:46 |
| tmp_pack_yQqcrZ | 4,325,376 | 2026-10-06 02:01 |

⇒ 典型"pack 写入中断残留"(git fetch/repack 被超时/中断后未 rename 的中间文件);两次中断时点(10-03 / 10-06)。
### 5.2 远端完整性(可恢复性前提)

- `origin` = `git@github.com:xp13465/trade-data-signal-staticdata.git`
- 本地 `HEAD` == `origin/main` == `c4a5f298bcec2c4a868335c3699271613d73c440`(**0 领先 / 0 落后**);工作区 `git status --porcelain` 干净;refs=3(main + origin/main + 1)
- `git ls-remote origin` 远端可达,可见 `HEAD` / `refs/heads/main` / `refs/tags/db-archive-2026-08-10`
- ⇒ **可达内容(全部每日提交)远端完整同步**;unreachable 对象(17,077 blob)按定义不在任何 ref 上 ⇒ 远端同样没有它们。
### 5.3 分析与建议方案(执行阶段,独立拍板)

**性质判断**:17k unreachable blob + 1 tree = 仓历轮"add 后未入库/被移出跟踪"的中间态内容(该仓每日 `git add -A`;大 JSON 曾受管后 `rm --cached` 移出等);它们**不在任何 ref**、远端也没有;`prune-packable=0` 说明无"已打包待清";gc.log 警告证明 auto-gc 保护触发,不手动清理会持续膨胀(pack 侧 1.24 GiB 是可达历史,loose 侧 1.31 GiB 中 ≈99% 是 unreachable)。

**清理方案(§25:先备份→验可恢复→再删)**:
1. **备份**:①仓的可达内容=远端 origin 即完整副本(已核 0/0);②unreachable 侧(17,077 blob/解压 5.79 GB)打包 = `git fsck --unreachable | awk '{print $3}' | git pack-objects` 或简单 `tar` 归档 `.git/objects/??/` 全部 loose(压缩后 ~1 GiB)→ 传 R2 新桶(新账号,不占老账号额度)+ 本机留档;
2. **验证**:归档解包抽样逐位(md5/sha1 对 `git cat-file` 输出),``MISSING=0``(清单=fsck 全量输出);
3. **删除**(执行阶段,明令禁止在本审计窗口做):`git prune --expire=now`(清 unreachable loose)+ 移除 4 个 `tmp_pack_*`(garbage,21.5 MiB)+ 之后 `git gc`(打包收敛);**不**用 `--aggressive` 日常。
4. **恢复路径**:从归档/R2 备份取回对象 → `git unpack-objects` 或 PUT 回 `.git/objects/`;仓本体可从远端 clone 恢复。
5. **风险**:①若 17k blob 里有"意外唯一内容"(如某次误删文件的最新版),删后只能从备份找回——**建议执行前抽样 5~10 个 blob 人工过目确认内容性质**(本次已抽样 3 个,见 §5.4);②操作窗口需避开每日备份链时点(该仓每日 00:50 前后、17:50、21:16 有 async 轮次操作 git)。
### 5.4 抽样(内容性质佐证)

两次独立抽样(2026-10-07),内容性质一致 = **数据 JSON 的历史版本**:
- ① `git fsck --unreachable` 头部抽 3 个 blob(全量扫):`0e00a0d8…` 181,896 B `{"date":"20260924","exported_at":"20260928",…}`(某导出 JSON 9-24 版)/ `1b004898…` 162,644 B `{"ohlc":[{"date":"20220919","open":1002.472,…`(OHLC 全历史类)/ `3b009804…` 22,193 B `{"20210817":0.975,…}`(日期→值 dict 类)
- ② `.git/objects` 随机抽 6 个 loose 对象(全读):全部为 `{"date":…,"exported_at":…}` 数据 JSON / 日期 dict,文件时间 9-28~10-01
- 佐证关系:这些 blob 的时间窗(9-28~10-01)与 R2 老桶 legacy 快照日期(09-29/09-30)同源重叠 ⇒ unreachable blob 本质=「large-json 移出 git 前最后几天的数据文件版本」的未压缩中间态;与 §4 C 档 legacy 快照互为"同内容不同形态"的副本。
- **仍需执行前人工过目**(§5.3 建议保留):抽样仅覆盖 9/17,079;若发现任一 blob 为"意外唯一内容",停止并上报。

---

## 6. §25 总表 + 执行顺序建议

| 块 | 对象数/体量 | 唯一副本? | 消费方 | 冻结面 | §25 判定 | 建议 |
|---|---|---|---|---|---|---|
| A 档 21 对象 | 163.93 MiB | 部分(A3/A4 无源) | 无 | 否 | **可清**(A3/A4 须先 GET 归档) | ①GET 全量归档 →②对账(MISSING=0+ETag 逐位)→③逐 key DELETE |
| C 档 legacy 27,673 | 266.1 MiB | orphan=0 | restore 脚本(设计到期) | 否 | **可清**(推荐先归档) | ①GET 归档 →②对账 →③按目录逐 key DELETE(27,673 个;`s3_request('DELETE', key, bucket='signal-backup')`,禁前缀通配;R2 支持批量 `POST ?delete`(1000/批)=执行可选项) |
| #197 仓 | loose 1.31 GiB(≈99% unreachable)+ garbage 21.5 MiB | 可达=远端有;unreachable=无 | 每日备份链 | 灾备资产(谨慎窗口) | **可清(备份后)** | ①归档 unreachable →②抽样人工过目 →③prune/清 tmp_pack/gc |

**时点建议**:全部执行动作避开每日备份链时点(00:00-00:30 / 05:00 / 17:50 / 21:00 前后),建议窗口=夜间 22:30 后或休市日;云上跨境传输大文件(归档上传)预计 20~40 分钟,夜间跑。

---

## 7. 诚实标注(局限 / 未验项)

1. 本报告**全程只读**:未执行任何删除/上传/prune/gc;所有清理动作均为建议,待拍板+独立执行。
2. ETag=md5 结论已抽样验证(3 个对象 GET 逐位 + tamper 尺子);12 个从未 GET 过的 A 档对象仅依赖此举一反三(单段上传语义),执行阶段对账时全量核。
3. sss.jpg / 根级 overview.json 的"站外引用"不可程序化穷尽(同 10-05 评估口径);按"站内零引用"判定+建议先归档。
4. C 档 09-29/09-30 目录内容"价值"按设计语义(7 天宽限后弃置)判定;`restore-large-json.sh --date` 能力随删失效(设计内)——如用户要保留历史时点恢复能力,请走"先归档"路径。
5. #197 抽样 blob 内容性质(§5.4)仅凭少量抽样+机理推断;"17k blob 全部无价值"不是本报告的既证结论,执行前需按 §5.3 建议做人工过目。
6. 云上 ss 探测期间使用生产 venv 3.11.15(与 #185 口径一致);所有探针经 ssh stdin 管道执行,云上未落任何文件。
7. 本报告不 commit(留工作区,由主控处理)。

---

## 8. 复现命令段(逐条可复核)

```bash
# ① 环境与裁决证据(生产等价)
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 \
  'cd /home/ubuntu/code/trade-data && grep -c R2_BACKUP_BUCKET .env; grep -c R2_BACKUP2_BUCKET .env; \
   REPO=/home/ubuntu/code/trade-data .venv/bin/python -c "import sys; sys.path.insert(0,\"scripts\"); import upload_r2 as u; print(u.BACKUP_BUCKET)"'
# ② 两桶全量 + legacy 细节 + orphan(探针经 stdin,不打云上文件)
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'REPO=/home/ubuntu/code/trade-data /home/ubuntu/code/trade-data/.venv/bin/python - full' < /tmp/r2_probe_20261007.py
# ③ A 档 ETag + 尺子先验 + 抽样 GET
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'REPO=/home/ubuntu/code/trade-data /home/ubuntu/code/trade-data/.venv/bin/python - etag' < /tmp/r2_probe_20261007.py
# ④ 消费方复核(本机)
grep -rn "data/industry-" static-site/*.js scripts/*.py worker/*.js | grep -v .min.
grep -rn "sss\.jpg" static-site/ scripts/ worker/ | grep -v .min.
grep -rn '"/overview\.json"\|/r2/overview' static-site/*.js worker/*.js | grep -v .min.
# ⑤ prune 断链四层证据(代码/环境/日志/实测)
grep -n "_prune_large_json()\|bkt = bucket or BACKUP_BUCKET" scripts/upload_r2.py         # L3231 / L2763
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'cd /home/ubuntu/code/trade-data/data/logs && \
  grep -l "旧日期目录" staticdata_backup_async_2026*.log | tail -3; \
  grep -c "旧日期目录" staticdata_backup_async_20261005_165200.log; \
  grep -c "旧日期目录" staticdata_backup_async_20261007_051111.log'
# ⑥ #197 只读量化
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'cd /home/ubuntu/code/trade-data-signal-staticdata && \
  git count-objects -vH; cat .git/gc.log; ls -la .git/objects/pack/ | grep tmp_pack; \
  git fsck --unreachable --no-progress 2>/dev/null | awk "{print \$2}" | sort | uniq -c; \
  git fsck --unreachable --no-progress 2>/dev/null | awk "{print \$3}" | \
    git cat-file --batch-check="%(objecttype) %(objectsize)" | awk "{n[\$1]++; s[\$1]+=\$2} END {for(k in n) print k, n[k], s[k]}"'
# ⑦ 本机 industry 源文件逐位对账
md5 -q static-site/data/industry-3y.json   # 812f38218e8eded6c3d73fcc04d3813b == R2 ETag
```

**探针脚本全文**(`/tmp/r2_probe_20261007.py`,可重建):mode = full / etag / spot 三段,仅用 `upload_r2.s3_request`/`_list_keys` 只读函数(LIST/GET 类),无任何 PUT/DELETE 调用。
