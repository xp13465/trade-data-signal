# #237 R2 覆盖前备份护栏 —— 根因确认 + 修法设计(2026-10-09)

- 任务:#237【P0 可逆性】R2 覆盖前备份护栏(跨账号 COPY 静默失败)—— 根因确认 + 修法设计
- 关联:module = `scripts/upload_r2.py` `_backup_overwritten_keys`(export-guard L5);上游 #178(备份桶迁独立账号)/ #233(生产观察)/ §25(覆盖前必备份铁律)
- 只读声明:本次全程**零 R2 写**(仅 LIST/HEAD)、零外发、未跑业务脚本、未启停 unit、未 git 操作;云上仅 ssh 只读(读日志 + 只读 LIST)。唯一写入 = 本报告文件 + `/tmp` 进度文件。
- 行号锚点:本报告所有行号 = 当前工作树实读(`scripts/upload_r2.py` md5 `bc0a646905d24c462e473852582d2a09`,4119 行,mtime 2026-10-09 13:29),与前序定因报告(10-09 00:27)引用的 L1174 / L1178-1181 / L1447-1456 / L402-413 逐一对位一致。
- 前序依据:`docs/ops/preupload-copy-rootcause-20261008.md`(10-09 00:27 定因)、`docs/ops/233-r2-bucket-prod-observe-20261008.md`(生产实证)、`docs/ops/export-guard-implementation-20261003.md`(L5 设计)、`docs/ops/r2-export-guard-backup-timeout-rootcause-20261005.md`(并行化背景)。

---

## 0. 一句话结论

**根因判定成立(高置信):Cloudflare R2 的 `CopyObject`(`x-amz-copy-source`)源桶只在"签名凭据所属账号"内解析;源桶在老账号(signal-data)、目标桶在新账号(signal-backup2)时,新账号视角源桶不存在 ⇒ 404 `NoSuchBucket`。** 该护栏自 10-05 切桶起 100% 失败(10-08 起 5363 条,10-09 复市后仍在 100% 失败),且失败只 `print` 不阻断、不告警、无观测 ⇒ §25「备份先于覆盖」实际能力 = 0,切桶以来所有覆盖均不可逆。**本次复核新证据:官方/社区无"跨账号 copy 不支持"的明文声明(存疑);但官方三处间接依据 + 项目生产三重对照 + 工具先例,判定仍成立。修法主推:备份改客户端中转(GET 源→PUT 目标)+ 落地校验(md5/ETag/size)+ fail-fast 阻断(A 先 C 后)。**

一个重要口径修正(诚实标注):**观测到的失败是协议层显式 404,不是"返回 200 假成功"。"静默"发生在处置层**——失败只记日志、不阻断上传、不进告警链、无任何存活观测;同时现状代码对 COPY 200 也不做"备份对象真落地"复核,所以"200-but-not-landed"类平台异常同样会静默。修法的落地校验同时覆盖这两种形态。

---

## 1. 现象与独立复核(2026-10-09 实读,只读)

### 1.1 今日(10-09,交易日)仍在 100% 失败 —— 新实证

云上 `data/logs/intraday_snapshot_20261009_1535.log`(最新一轮,实读):
```
[index] ⚠ 备份 index/hstech-all.json -> signal-backup2/pre-upload/20261009/index/hstech-all.json 失败 status=404
        <Error><Code>NoSuchBucket</Code><Message>The specified bucket does not exist.</Message><BucketName>signal-backup2</BucketName></Error>
[index] ⚠ 备份 index/cgb_idx-all.json -> signal-backup2/pre-upload/20261009/index/cgb_idx-all.json 失败 status=404 ...NoSuchBucket...
```
当日失败行计数(实读,grep -c):`intraday_snapshot_20261009_0925.log`=122、`0935`=77、`0948`=78、`0955`=78、`1008`=78、`1015`=77、`1025`=78、`1035`=78;`etf_national_team_backfill_20261009_0007.log`=108;`gold_night_20261009_0240.log`=4。**curred 全为 pre-upload COPY 失败,无一成功。**

### 1.2 三重对照(唯一变量 = 跨不跨账号)

| 操作 | 源桶(账号) | 目标桶(账号) | 跨账号 | 实测 | 证据 |
|---|---|---|---|---|---|
| 服务端 COPY | signal-data(老) | signal-backup(老) | 否 | **256/256 成功** | `fund_nav_upload_async_20261003_150955.log` L5 原文:`✓ 备份 256 个将被覆盖 key -> signal-backup/pre-upload/20261003/ (export-guard L5)`(本次实读复核) |
| 服务端 COPY | signal-data(老) | signal-backup2(**新**) | **是** | **100% 失败 404 NoSuchBucket** | §1.1 十份日志(10-08 逐条 5363 条全败 + 10-09 仍在持续) |
| plain PUT | — | signal-backup2(新) | 是 | **成功**(连续多日) | `backup_db_20261008_2100.log` 原文:`✓ sentiment.db (130788KB -> 38574KB gzip) -> signal-backup2/backup/sentiment_20261008.db.gz (私有桶)` + `DB 上传 2/2 -> signal-backup2/backup/ (20261008)`(本次实读复核) |

### 1.3 备份桶实态(本次 R2 只读 LIST 独立复核)

- `signal-backup2` 桶 `pre-upload/` 前缀对象数 = **0**(切桶以来零成功)。
- 老桶 `signal-backup` `pre-upload/` = **6585 对象**(10-03~10-05 存量,同账号时代产物)。
- 结论:护栏"实际能力 = 0"事实成立;现状覆盖不可逆(**10-09 仍在发生**)。

### 1.4 静默性的机制(为什么没人发现)

- `scripts/upload_r2.py:1178-1181`:失败分支只 `print ⚠ ... status=...`(write stderr)。
- `scripts/upload_r2.py:1447-1457`:调用点 `try/except` 包裹,**返回值被丢弃;失败不阻断上传,仅记日志**(注释原文)。
- `scripts/upload_r2.py:1172-1176`:COPY 返回 200 即 `copied += 1`,**无任何目标落地复核**(无 HEAD 对账)。
- 全仓 grep:`pre-upload` 只在 `upload_r2.py` 的写路径与 prune(L1070-1117)出现,**无任何巡检/观测点**(护栏是否在工作 = 不可观测)。
- 规模:10-08 单日 5363 条失败(12 通道),10-09 全天持续(盘中每 10 分钟一轮)⇒ 无一告警。

---

## 2. 根因确认:跨账号 COPY 的官方语义 + 社区先例(本次新查)

### 2.1 官方依据(本次实抓,URL + 原文)

| # | 来源 | 原文关键句 | 说明 |
|---|---|---|---|
| ① | R2 S3 兼容矩阵 https://developers.cloudflare.com/r2/api/s3/api/ (llms-full.txt L4590) | `✅ CopyObject ... ✅ Conditional Operations: ✅ x-amz-copy-source ... ❌ Bucket Owner: ❌ x-amz-expected-bucket-owner ❌ x-amz-source-expected-bucket-owner` | **R2 明确不支持 `x-amz-source-expected-bucket-owner`** —— 该头正是 S3 用来声明"源桶所属账号"的。无此头 = R2 没有"跨账号源桶"这一语义位 |
| ② | R2 错误码参考(同页 llms-full L4378) | `10006 \| NoSuchBucket \| 404 \| The specified bucket does not exist. \| Verify the bucket name is correct and the bucket exists in your account.` | 「**exists in your account**」(你的账号内)—— 桶可见域 = 凭据所属账号;跨账号桶 = "不存在" |
| ③ | R2 changelog(llms-full L8940/8941/8922) | 「The S3 API `CopyObject` source parameter now requires a leading slash.」/「…now returns a `NoSuchBucket` error when copying to a non-existent bucket instead of an internal error.」/「Copying from a non-existent key (or from a non-existent bucket) to another bucket now returns the proper `NoSuchKey` / `NoSuchBucket` response.」 | (a) 代码已带前导 `/`(L1174 合规);(b) R2 对"copy 源不存在"的正式形态 = **NoSuchBucket/NoSuchKey**(与现场 404 逐字吻合) |
| ④ | R2 llms-full L12392 | 「When your Worker and R2 bucket live in the same Cloudflare account, R2 bindings give you zero-latency access... **Use the S3 API when you need cross-account access** or interoperability with S3-compatible tooling.」 | 官方语境:**原生 binding 是账号内的;跨账号访问须走带凭据的 S3 API** —— 与"桶/源解析按凭据账号隔离"的账号隔离架构一致 |
| ⑤ | AWS S3 CopyObject API 对照 https://docs.aws.amazon.com/AmazonS3/latest/API/API_CopyObject.html | `x-amz-source-expected-bucket-owner: The account ID of the expected source bucket owner. If the account ID that you provide does not match the actual owner of the source bucket, the request fails with the HTTP status code 403 Forbidden (access denied).` | S3 语义跨账号源桶是**一等公民**(有专头、失败=**403** 权限类);R2 无该头、失败=**404** 语义类 ⇒ 两平台对"跨账号源"的语义位不同 |

### 2.2 社区/工具先例

- **rclone S3 文档**(https://rclone.org/s3/ 「Using server-side copy」段,本次实抓原文):「For rclone to use server-side copy, **you must use the same remote for the source and destination**.」⇒ 业界工具口径:跨端点/跨账号搬运 = 下载再上传,不做服务端 copy。
- **CloneS3toS3**(社区专为"跨账号 S3 兼容桶互搬"的工具,前序报告引用):其存在本身即"跨账号搬桶 = 读+写中转"的先例(本次尝试复核 README 未取到正文,诚实标注为前序转引)。
- **Cloudflare Community**:`community.cloudflare.com/search.json` 被 CF 挑战页拦截(「Just a moment...」),**未取到社区原文**;WebSearch 命中以营销页为主,**无权威命中**(诚实标注)。

### 2.3 判定(诚实标注)

- **官方/社区"跨账号 COPY 不支持"的明文声明:未找到(存疑)**。前序报告(10-09 00:27)已尽力检索,本次新查亦未命中,两侧诚实一致。
- **判定仍成立(高置信)**,依据三条:①官方兼容矩阵"❌ x-amz-source-expected-bucket-owner"+ 错误码「your account」措辞 + 「S3 API = 跨账号通道」语境 = 账号隔离架构的官方间接依据;②项目生产**三重对照**(跨账号 COPY 0/5363 vs 同账号 COPY 256/256 vs 跨账号 plain PUT 成功,唯一变量 = 跨账号)= 直接实证;③rclone 同 remote 注记 = 工具先例。
- **残留未钉死点(不影响修法)**:错误 XML 的 `<BucketName>signal-backup2</BucketName>` 报的是目标桶(字面),与"源桶解析失败"的语义推断不完全对位;100% 法定论需 CF Support 工单或一次受控 COPY 写实验(超本次只读禁令,未做)。A/B 两类修法均不依赖该细节。

---

## 3. 代码点现状定性:COPY 与覆盖写逐点

### 3.1 COPY 使用点(全仓唯一一处)

| 点 | 位置 | 跨账号? | 校验? | 现状风险 |
|---|---|---|---|---|
| 覆盖前备份 COPY | `scripts/upload_r2.py:1172-1175`(`_backup_overwritten_keys._backup_one`,L1172-1175 `s3_request("PUT", backup_key, extra_headers={"x-amz-copy-source": "/{BUCKET}/{key}"})`) | **是**(源 signal-data 老账号 → 目标 BACKUP_BUCKET=signal-backup2 新账号) | 仅判 `bst == 200`;失败只打印(L1178-1181);**无目标 HEAD 落地复核** | **P0:100% 失败且静默**(§1);即便 200 也无落地校验 ⇒ 无回滚能力 |

### 3.2 覆盖写(plain PUT 覆盖既有 key)通道全景

| 类别 | 通道(命令) | 覆盖前备份? | 现状风险 |
|---|---|---|---|
| 走 `_incremental_upload`(L1447-1456 有 L5 护栏) | lab / trade-sim / trade-sim-json / index / etf-hist / fund-nav / accum-nav / industry / public-fund / etf-score / kelly-parts / kelly-parts-sdc / kelly-snapshots / data-large / all-data(**15 条**) | 有护栏,但 COPY 100% 失效 ⇒ **实际零备份** | **P0:与 §3.1 同体** |
| 走 `_upload_glob` 直连(**无 L5 护栏**) | `cmd_upload_offshore_fund`(L1795-1812)/ `cmd_upload_fund_score`(L1816-1834)/ `cmd_upload_intraday`(L2199-2232,盘中每 10 分钟覆盖 `data/*.json`)/ `cmd_upload_data_files`(L2359-2377,11 个调用方) | **无**(从设计起就未覆盖) | **结构性缺口**:这些是用户可见数据(data/ 前缀),被覆盖时无"覆盖前现场";财务口径另有 staticdata git/R2 层二备份兜底,但非 per-key 覆盖前备份 |
| 写私有备份桶自身 | `upload-large-json`(L2987)/ `upload-db`(L2601)/ `upload-claude-backup`(L2681)/ `upload-decommissioned`(L2649) | 不适用 | 低(按日新 key;仅同日重跑覆盖自身)。注:这些通道的跨账号 plain PUT 已实证可用(§1.2) |
| 对账补传 | `cmd_verify_r2` backfill(L3511+) | 不适用 | 低(补的是缺失 key,非覆盖) |

### 3.3 护栏机制现状(设计 vs 失效)

- 设计语义(§25 机制化):`_incremental_upload` **先整批备份**(L1447-1456)后 **整批 PUT**(L1461-1469),减量判据(备份桶已有今天备份 且 R2 内容 == 本地将传指纹 → 跳过,L1166-1169)。
- 失效链:`_route_bucket`(L402-413)按目标桶路由到新账号凭据(正确)→ 服务端 COPY 的 `x-amz-copy-source` 在新账号解析源桶失败 → 404(100%)→ 只打印(L1178-1181)→ 调用点丢弃返回值、不阻断(L1447-1457)→ 无告警、无观测 ⇒ **静默零备份**。
- 附:`_route_bucket` 对新账号 env 缺失时**静默回退老账号**(L402-413 `if BACKUP2_HOST and ...` 否则 `return HOST, AK, SK`)—— 对 signal-backup2 而言回退 = 必然 404 且不可见(炸弹,见修法 D)。


---

## 4. 修法设计(全集 + 选项 + 风险)

### 4.0 备选路径全景(先排除,后主推)

| 方案 | 内容 | 判定 |
|---|---|---|
| **A. 客户端中转备份(主推)** | 备份语义从服务端 COPY 改为:老账号端点 **GET 源对象 body**(L510 `s3_request` 已支持 GET 返回 body)→ 校验 → 新账号端点 **PUT 到 `BACKUP_BUCKET/pre-upload/...`**(≤100MB 单 PUT,>100MB 走 `_upload_multipart`) | **主推**。唯一与"第二套端点+凭据按桶路由"架构(#178)相容的方案;读写通道都已被生产实证(老桶 GET 常年在跑、新桶 plain PUT 已被 db 备份实证) |
| B. 备份目标退回老桶(同账号 COPY 保留) | `BACKUP_BUCKET` 指回 signal-backup(老账号),COPY 恢复可用 | **不推荐**。牺牲 #178 的"备份与主桶跨账号隔离"目标(灾难时同账号一起挂);且老桶 10-10~12 起按 lifecycle 回收,容量与保留策略要重议 |
| C. fail-fast 阻断(与 A 配套) | `_backup_overwritten_keys` 返回 `(copied, skipped, failed)`;调用点 `failed>0` ⇒ **PUT 前中止**(清 marker、不落 ANY 新数据)+ severe 告警 | **A 之后开**(顺序硬约束,见 §4.4);开之前需用户拍板(改生产行为,§23.7) |
| D. 加固(与 A 同批) | ① `_route_bucket`(L402-413)对 `signal-backup2` 类桶 **fail-loud**(env 缺失不静默回退老账号,直接异常);② 提请排查 `fund_nav_upload_async.sh` 为何走 2.5s 超时/需补 env(见 §4.5 遗留);③ pre-upload **当日存活观测**(进监控巡检) | **同批做**,防"静默回退"与"护栏不可观测"复辟 |
| E. 降级 fallback(备选,须拍板) | COPY 失败时自动降级客户端中转(即"A 做成运行时 fallback")| 可作为 A 的实现形态(见 §4.2);若独立成方案,则同 A |
| ✗ 排除:同账号公开前缀 | 备份写到主桶同账号下某前缀 | 排除:与主桶同生命周期/同账号,泄漏面与隔离目标都破坏 |
| ✗ 排除:定时快照式备份 | 每天定时全量快照,不做"覆盖前"逐 key 备份 | 排除:两次快照之间的覆盖 = 旧版永久丢失,**不满足 §25「备份先于删除/覆盖」**语义 |
| ✗ 排除:继续服务端 COPY 等官方支持 | 维持现状等 R2 开放 | 排除:官方矩阵明确"❌ x-amz-source-expected-bucket-owner",无支持时间表,现状 = 护栏能力 0 持续 |

### 4.1 备份时机:覆盖前 vs 定时

- **必须保留"覆盖前"语义**(§25):`_incremental_upload` 已有"先备份整批(L1447-1456)→ 再 PUT 整批(L1461-1469)"的两段结构,时机不动。
- A 的改造是把这两段之间的"备份实现"从 COPY 换成"GET+PUT",**不引入定时任务、不改上传时序**。
- 唯一新增时机约束:备份段的耗时从"服务端秒级"变成"跨境搬运"(GET 老账号 + PUT 新账号 = 2 次跨境),**时长≈旧 COPY 的 2 倍以上**(bit 搬运量 = 被覆盖 key 的总字节,实测单轮 intraday 77~122 个 key 只是 data/*.json 小文件;fund-nav 256 个 key 是大头)。⇒ 见 §4.6 看门狗联动。

### 4.2 跨账号怎么备:客户端中转的实现形态(A 细案)

**(a) 首选形态:直接替换 `_backup_one` 的 COPY 段(L1172-1175),GET+PUT 原地替换**

```
现有(L1172-1175):s3_request("PUT", backup_key, bucket=BACKUP_BUCKET,
                              extra_headers={"x-amz-copy-source": f"/{BUCKET}/{key}"}, keep_alive=True)
替换为:P1 源 HEAD(L628 s3_head(key, bucket=BUCKET, with_len=True))→ (st, etag_s, size_s)
        P2 减量判定(保留现有 L1166-1169 逻辑:备份桶 HEAD 200 且 etag==local_md5 则跳过)之后,
        P3 GET 源体:s3_request("GET", key, bucket=BUCKET) → body(len 应 == size_s)
        P4 落地校验:md5(body) == etag_s(单 PUT 语义,docstring L628 已写明;multipart 对象改比 size)
        P5 PUT 目标:<100MB 单次 s3_request("PUT", backup_key, payload=body, bucket=BACKUP_BUCKET);
                    ≥100MB 走 _upload_multipart(L817)
        P6 目标回读:s3_head(backup_key, bucket=BACKUP_BUCKET, with_len=True) →
            单 PUT:etag_t == md5(body);multipart:Content-Length == len(body)
        ⇒ 全部通过 = copied += 1;任一环失败 = failed += 1(记录 key + 环节 + 实际值)
```

- 校验链设计原则(核心问题:怎么证"备份真落地"——静默失败 ⇒ **必须实测比对**,不能只看 PUT 200):
  - **源侧对照**:P3/P4 用 GET 回来的 body 自校验(既证 GET 完整,又给 P5/P6 提供基准 md5)。
  - **目标侧对照**:P6 HEAD 回读,**单 PUT 比 ETag==本地 md5、multipart 比 Content-Length**(`s3_head` docstring 已注明 multipart ETag ≠ md5,禁用 ETag 判 multipart)。
  - **双形态覆盖**:① 协议失败(PUT 返回非 200 / 网络异常)= 显式;② 平台"200 但没落地"= 由 P6 兜住。两种形态都收敛到 `failed`。
  - **fail-closed 方向**:与上传对账的"宁多传"相反 —— 备份宁可多备(failed 判严),漏备不可接受。
- **(b) 不要用 multipart upload 省内存**:现状 `_upload_glob`(L885-1005)已全量 `read_bytes` 读内存;备份段同风格(get 全量 body + put,单文件最大 84MB 级,内存可控)。>100MB 场景(信号凯利大 JSON)走 `_upload_multipart`,不新造轮子。
- **(c) 复用层级**:`s3_request`(L510)已支持 `bucket=` 参数 + `payload` + GET 返回 body + 5xx 退避 5 次;`s3_head`(L628)已有 `with_len`;**改动集中在 `_backup_one` 一个函数体内**,不新增网络原语。

### 4.3 校验判据表(实施按此写断言)

| 环节 | 判据 | 失败处理 |
|---|---|---|
| P1 源 HEAD | `st==200`;记 `etag_s`、`size_s` | 源对象不存在 ⇒ 视为"无备份必要"(现状逻辑:HEAD 源失败时跳过,保持);其他失败 ⇒ failed |
| P2 减量 | `bk_st==200 且 etag==local_md5`(现状 L1166-1169 保留) | 跳过(不重复备) |
| P3 GET 源体 | `len(body) == size_s` 且 GET 状态 200 | failed(记"GET 短读/失败") |
| P4 源 md5 | 单 PUT 场景:`md5(body) == etag_s`;multipart 源:只比 len | failed(记"源读不一致") |
| P5 PUT 目标 | 状态 200(单 PUT);multipart 分片全 200 | failed(记 HTTP 状态 + 错误体前 200B) |
| P6 目标回读 | 单 PUT:`etag_t == md5(body)`;multipart:`Content-Length == len(body)` | failed(记"落地校验不一致";**这就是静默失败的兜底网**) |
| 汇总 | `failed == 0` ⇒ 返回 `(copied, skipped, 0)`;否则 `(copied, skipped, failed)` + 失败样本前 5 条 | 调用点据此决策(§4.4) |

### 4.4 失败时怎么办:阻断 vs 告警 vs 降级(顺序硬约束)

- **分级策略**:
  - **默认(第一阶段,先上 A 不阻断)**:A 落地后保持"失败不阻断上传,但把 failed 计数 + 样本写**结构化日志**" ⇒ 先观测 1~2 个交易日,拿到"中转备份真实成功率"数据。理由:阻断会改生产行为,且 A 是新代码路径,先证稳定(§23.7:动已上线功能行为需用户确认;先观测再阻断是同一精神)。
  - **第二阶段(用户拍板后开 C)**:`failed > 0` ⇒ `_incremental_upload` **在 PUT 批之前中止**:清 marker(防死循环,参照 10-05 教训 `r2-export-guard-backup-timeout-rootcause-20261005.md`)、不落任何新数据、severe 告警(走既有 notify 链)。语义:宁可不更新,也不"覆盖且无备份"。
  - **降级 fallback(E)**:不建议做成"COPY 失败自动降级中转"的运行时双路径(双路径 = 双份维护面);A 直接替换后**没有 COPY 路径**,降级概念消失。
- **顺序硬约束(A 先 C 后,必须写进实施验收)**:现状 COPY 100% 失败。若先开 C 再修 A,或 A/C 同批上线而 A 有 bug ⇒ **全站上传当场停摆**(fail-fast 会因备份失败中止所有 15 条通道的 PUT)。**A 上线并观测到 failed≈0 之后,才允许开 C。**

### 4.5 与既有链的关系(§22/§14/§25/看门狗)

- **§22 一致性**:pre-upload 备份桶**不是任何展示位**的数据源(纯私有回滚层)⇒ A/C 不产生"多展示位不一致"风险;不需要 N 文件+N 缓存同步动作。
- **§14 时点**:A 是代码级修复,上线走常规 feat→reviewer→`main-merge.sh`(避开 15:35/16:00/17:50/20:35/22:00 盘后时点与 23:00 后安全窗;休市日可随时)。**运行期行为**:备份段耗时增加,需确认不超过既有看门狗/超时(见下)。
- **§25**:A 是 §25 的**修复**(把"声明有备份"变成"实测有备份");文档/公示上无需改 §25 条文,但建议在 `export-guard-implementation-20261003.md`(L5 设计文)追加"A 迁移注记"。
- **看门狗联动(重要)**:`scripts/r2_upload_async.sh` 对 `r2_upload_async` 有 **900s 总时长硬闸**(10-05 事故根因就是串行 3436 次跨境 HEAD+COPY ≈2200s 被 kill ⇒ marker 残留死循环)。A 的备份段(跨境 GET+PUT 双程)比 COPY 更重:
  - 需实测单轮备份段时长(未测,见 §7);若接近 900s,需同步评估:提高看门狗闸、或备份段保留并行(现状 8 线程)、或先备份后跑双段。
  - **必做**:A 上线时**保留 10-05 已加的减量/并行优化**(L1166-1169 减量 + 现并行度),不回归串行。
  - **marker 安全**:C 开之前,失败仍不阻断 ⇒ marker 不因 A 而残留;C 开启时**必须**在"备份失败中止"路径上清 marker,否则复刻 10-05 死循环。

### 4.6 容量联动(拍板项)

- 现状新桶 4.226 GiB(#233 基线)+ pre-upload 0 = 安全;A 修复后 pre-upload 按 ~1.1 GiB/天 × 7 天保留 ≈ 7.7 GiB ⇒ 合计 **~12 GiB 越过 10 GB 免费线**(#233 §2 已外推)。
- **同批评估**:`_PREUPLOAD_RETENTION_DAYS`(L1070)7 → 3~5 天,或 pre-upload 上 lifecycle 规则;两者取其一即可压回免费线(3 天 ≈ 3.3 GiB ⇒ 合计 ~7.5 GiB)。**此项属"动保留策略",需用户拍板**(与 A 同批,不阻塞 A 代码)。


---

## 5. 实施规格(改点清单 + 验收口径)

> 派单锚点 = `scripts/upload_r2.py:行号`(下表行号 = 本报告实读版;实施开工先核对 md5 `bc0a646905d24c462e473852582d2a09` 防漂移)。**实施顺序 = A(+D)先,观测后 C;容量项同批议。**

### 5.1 改点清单

| # | 文件:行 | 改动 | 级别 |
|---|---|---|---|
| 1 | `scripts/upload_r2.py:1120-1201`(`_backup_overwritten_keys` / `_backup_one`) | COPY 段(L1172-1176)替换为 §4.2 的 P1~P6(GET+校验+PUT+回读校验);失败改 `failed += 1` + 记样本;**返回 `(copied, skipped, failed, samples)`**(与现 `return copied` 不兼容,调用点同步改) | A 级主体 |
| 2 | `scripts/upload_r2.py:1447-1457`(L5 调用点) | 接住新返回值:第一阶段只**结构化日志**(`[label] 备份完成 copied=X skipped=Y failed=Z` + 失败样本);保留"不阻断" | A 级配套 |
| 3 | `scripts/upload_r2.py:1447-1457`(同上) | **第二阶段(C)**:`failed>0` ⇒ 清 marker(L1395-1396 写入点对应 unlink)+ `return` 中止于 PUT 批(L1461-1469)之前 + severe 告警 | C 级(拍板后) |
| 4 | `scripts/upload_r2.py:402-413`(`_route_bucket`) | D①:对 `signal-backup2`(或一切 BACKUP2 桶)env 缺失时 **fail-loud**(抛异常/显式报错),不静默回退老账号;对老账号桶保持原回退(默认端点) | D 级 |
| 5 | 观测点(部署侧) | D③:pre-upload 当日对象数/备份成功率进巡检(可挂 `check_s06_freshness` 同族或独立 check);判据:`pre-upload/<今日>/` 对象数 > 0(有覆盖时) | D 级 |
| 6 | `scripts/r2_upload_async.sh`(看门狗 900s 闸) | 根据 §4.5 实测(备份段新时长)决定是否调闸;**未实测前不动** | 待实测 |
| 7 | `_PREUPLOAD_RETENTION_DAYS`(`:1070`)或 pre-upload lifecycle | 7→3~5 天(**拍板项**,不阻塞 1~4) | 拍板后 |

### 5.2 验收口径(实施 agent 自验必含,缺一不过)

1. **同构对账**:改造后,对同一批 key 在"老桶有源对象"场景下,备份桶落地对象**逐个**满足:P6 判据(单 PUT ETag==md5 / multipart size 一致),且对象数 = 期望覆盖数 − 减量跳过数(§5.4 复现脚本同构精神:脚本输出 vs R2 LIST 实测逐位对账)。
2. **对照矩阵**:① 正常 key ⇒ copied;② 已备同内容 key ⇒ skipped(减量仍生效);③ 人为构造源缺失 key ⇒ 按现状语义跳过且不误报 failed;④ 模拟 GET 短读/PUT 非 200(可打桩)⇒ failed 且样本完整。
3. **失败语义**:第一阶段=failed>0 时上传照常 + 日志含 `failed=Z`;第二阶段=failed>0 时**PUT 批未发生**(证据:上传日志无该批 `✓` 行)+ marker 已清(无残留)+ 告警实发(打桩验证,参照 L48 自测禁止真发)。
4. **看门狗**:跑一轮真实规模备份段(≥256 key 场景)记录时长,结论落档;超 900s 须同步调闸才许合并。
5. **§22 无回归**:pre-upload 为私有回滚层,不涉展示位;但确认改造后**不改变**主数据上传路径的键集/内容/顺序(对比改造前后上传日志同批 key 集合一致)。
6. **门控**:改造 A 上线时,若 C 未开,禁止在 fail-fast 代码路径上留半开开关;若 C 已开,C 的强制点必须**在 PUT 批之前**(防"先覆盖后报错")。
7. **数据产物层实测**:验收须含一次真实运行(休市日全量)后的 **R2 只读 LIST 实证**:`signal-backup2/pre-upload/<当日>/` 对象数与上传日志 copied 对账一致(不许只看日志自证)。

---

## 6. 落地窗口建议(2026-10-09 视角)

| 时点 | 属性 | 建议动作 |
|---|---|---|
| 10-09(五)盘中~盘后 | 交易日;intraday 正在持续失败(每 10 分钟一轮) | 窗口不适合上线(A 是新代码路径);可先在 dev 分支完成代码+自测 |
| **10-10(六)** | 休市 | **代码窗口**:A+D 上线(feat→reviewer→main-merge,休市可随时);上线后立即用一轮**手动通道**(如 fund-nav 或 index 全量)验证 copied>0 + 落地实查 |
| **10-11(日)** | 休市 | **全量验证窗口**:deploy 周日 `weekday()==6` ⇒ `force_full` 天然全量(备份段规模最大)⇒ 验证"真实全量备份段时长 + failed=0";这也是看门狗时长实测的最佳场 |
| 10-12(一) | 复市 | 首个真实增量日:**先观测一整天**(A 后不开 C);确认各通道 failed=0 后,提请拍板开 C |
| 后续 | — | C(拍板后)上线窗口同休市;容量项(§4.6)与 C 同批议 |

- 避让纪律:merge/上线避开 15:35 / 16:00 / 17:50 / 20:35 / 22:00 盘后时点与 23:00 后(§14);休市日可随时,但 10-11 21:16 附近有周末 deploy/staticdata 备份链,手动验证错开。
- **兜底**:上线后 10-12 盘中若出现"备份段新问题时",因 A 是"不阻断"阶段,**没有**上传停摆风险;若 C 已开且误报,处置 = 先停 C(回滚点到"A 不阻断"版)再查因。

---

## 7. 风险与诚实标注

### 7.1 主要风险(按严重度)

1. **A 未验证前误开 C ⇒ 全站上传停摆**(所有 15 条 `_incremental_upload` 通道的 PUT 全被阻断)。缓解:顺序硬约束 + §5.2 验收 2/3。
2. **修复激活 pre-upload 增长 ⇒ 逼近/越过 10GB 免费线**(~7.7GiB+4.2GiB ≈ 12GiB)。缓解:同批评估保留期(拍板)。
3. **备份段时长**:跨境 GET+PUT 双程比 COPY 重;若单轮超 900s 看门狗 ⇒ kill ⇒ marker 残留(复刻 10-05)。缓解:§5.2-4 实测 + 调闸。
4. **残留证据不确定点**:错误 XML 桶名回显与"源桶解析失败"推断不完全对位(§2.3);若真实机制另有其因,A 的"客户端中转"路径**仍然正确**(它绕开服务端 COPY 语义,不依赖该细节)——即修法对该不确定性**健壮**。
5. **护栏覆盖缺口**:4 条 `_upload_glob` 直连通道(offshore_fund / fund_score / intraday / data_files)L5 从设计起就缺;**A 不覆盖它们**。建议:本次立项后追加子任务评估(至少 intraday 的 `data/*.json` 是有用户可见性的每日覆盖)。**不在本次修法内**(不同类风险:那些是"没护栏",不是"护栏坏了")。

### 7.2 诚实标注(未测/未取到)

- **官方无明文**:两轮检索均未命中"R2 跨账号 copy 不支持"官方声明(§2.3),判定=高置信推断+生产实证,非官方定论;未开 CF Support 工单,未做受控 COPY 写实验(超只读禁令)。
- **社区搜索被拦**:CF Community search.json 被 challenge(「Just a moment...」);DDG lite `HTTP:000`(重试 1 次仍失败);WebSearch 命中以营销页为主。→ 社区侧证据=缺。
- **备份段新时长未实测**(A 尚未实现,取不到运行时数据;§5.2-4 列为实施时必测)。
- **A 的绝对性能未估**:本次只做了字节量与经验吞吐(跨境 ~0.3-0.4MB/s/连接、RTT 0.65s)的粗外推,不写数(**未测**)。
- **本次零副作用**:全程未写 R2/未外发/未跑业务脚本/未启停 unit/未 git 操作;云上仅读日志+grep+只读 LIST。

---

## 8. 复现命令(本次实测的只读通道)

```bash
# ① 10-09 失败原文 + 计数(云上只读)
ssh -4 -i ~/tdsignal.pem ubuntu@122.51.111.173 \
  "timeout 60 grep -c '失败 status=' /home/ubuntu/code/trade-data/data/logs/intraday_snapshot_20261009_1535.log"
ssh … "timeout 60 grep -o 'NoSuchBucket' /home/ubuntu/code/trade-data/data/logs/intraday_snapshot_20261009_1535.log | wc -l"
# ② 同日多轮日志失败计数(示例;逐个文件,勿整树 grep)
for f in 0925 0935 0948 0955 1008 1015 1025 1035; do ssh … "timeout 60 grep -c '失败 status=' .../intraday_snapshot_20261009_${f}.log"; done
# ③ 对照:10-03 同账号成功(切桶前)
ssh … "timeout 60 grep -n '将被覆盖' /home/ubuntu/code/trade-data/data/logs/fund_nav_upload_async_20261003_150955.log"
# ④ 跨账号 plain PUT 对照(成功)
ssh … "timeout 60 grep -nE 'signal-backup2/backup|DB 上传' /home/ubuntu/code/trade-data/data/logs/backup_db_20261008_2100.log"
# ⑤ pre-upload 对象数(本机 R2 只读 LIST;凭据自 repo/.env,不打印密钥)
/Users/linhuichen/code/trade/.venv/bin/python /tmp/r2cap_measure.py signal-backup2 /tmp/r2cap_out/new2.json   # pre-upload=0
/Users/linhuichen/code/trade/.venv/bin/python /tmp/r2cap_measure.py signal-backup  /tmp/r2cap_out/old2.json   # pre-upload=6585
# ⑥ 官方原文(本机 curl 抓取,llms-full 已缓存 /tmp/r2-llms-full.txt)
curl --max-time 20 -sL https://developers.cloudflare.com/r2/llms-full.txt -o /tmp/r2-llms-full.txt
grep -n "source-expected-bucket-owner" /tmp/r2-llms-full.txt        # L4590 兼容矩阵 ❌
grep -n "exists in your account" /tmp/r2-llms-full.txt              # L4378 NoSuchBucket
grep -n "CopyObject" /tmp/r2-llms-full.txt | head                   # L8922/L8940-8941 changelog
curl --max-time 20 -sL https://docs.aws.amazon.com/AmazonS3/latest/API/API_CopyObject.html -o /tmp/aws-copy.html   # x-amz-source-expected-bucket-owner -> 403
curl --max-time 20 -sL https://rclone.org/s3/ -o /tmp/rclone-s3.html                                # "same remote for the source and destination"
```

## 9. 已验证方法/数据源清单(供后续复用)

- **只读实测**:云上日志逐文件 grep -c(单文件定目标,勿整树);R2 只读 LIST(自研 `r2cap_measure` 走 `s3_request("GET","",query="list-type=2&...")`);`s3_head`(返回 (status, etag[, len]))。
- **官方源**:`developers.cloudflare.com/r2/llms-full.txt`(一次抓取含全站文档,行号引用以该文件为准);AWS CopyObject API 页;rclone s3 文档。
- **对照法**:同操作跨账号 vs 同账号(唯一变量);plain PUT vs COPY(同目标桶、同凭据)。
- **判据锚**:R2 错误码表(NoSuchBucket 404);兼容矩阵 ✅/❌ 表;ETag/md5/size 三元判据(单 PUT vs multipart 区分)。

---

## 附:待主控/用户拍板项(3 条)

1. **C(fail-fast 阻断)开启时机**:建议 A 上线并观测 ≥1 个完整交易日(10-12)failed=0 后开;C 本身改生产行为,需拍板(§23.7)。
2. **retention 7→3~5 天**(或 pre-upload lifecycle):控制 10GB 免费线,建议与 C 同批拍板。
3. **4 条 `_upload_glob` 无护栏通道**(offshore_fund / fund_score / intraday / data_files):是否追加子任务补 L5 覆盖(建议至少评估 intraday 的 `data/*.json`)。

---

## 落档信息

- 报告:本文件;生成方式 = 只读调研(零 R2 写);进度:`/tmp/agent-progress-237.md`
- 前序链:`docs/ops/preupload-copy-rootcause-20261008.md`(#237 定因)→ 本报告(修法设计);关联 #233 / #176 / #178 / 10-05 超时根因文
- 复现段:§8;核心数字锚点:跨账号 COPY 失败 5363+(10-08)与持续(10-09 盘中 77~122/轮)/ 同账号成功 256/256(10-03)/ pre-upload 新桶 0 vs 老桶 6585 / 新桶 4.226 GiB(#233)
