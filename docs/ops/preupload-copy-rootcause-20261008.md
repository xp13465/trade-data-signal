# pre-upload 覆盖前备份护栏跨账号 COPY 100% 失败 —— 根因定因与修法(#237)

- 报告日期:2026-10-09(事故日 2026-10-08)
- 关联:任务 #237【P0 可逆性】;module=scripts/upload_r2.py `_backup_overwritten_keys`(export-guard L5);上游 #178(备份桶迁独立账号)
- **只读声明**:本次调研全程零写——仅 LIST/HEAD 只读 R2 操作,**未 PUT/COPY/DELETE/建桶,未写任何测试对象**;未启停任何 unit;未跑业务脚本;未产生任何真实外发(邮件/飞书/告警);探针 static-only。唯一写入=本报告文件 + /tmp 下探针脚本/进度文件。
- 一句话结论:**判定乙成立(高置信)——Cloudflare R2 的服务端 CopyObject 的 `x-amz-copy-source` 源桶只能在签名凭据所属账号内解析;源桶在老账号(signal-data)、目标桶在新账号(signal-backup2)时,新账号视角下源桶"不存在"→ 404 NoSuchBucket。甲(打到老端点)、丙(配置写错)均排除。** 该护栏自 10-05 迁移后首个触发日(10-08,国庆后首个交易日)起 100% 失败(5363 条 COPY,0 成功),且失败只记日志、不阻断上传、不告警。

---

## 1. 判定表

| 假设 | 判定 | 排除/成立的核心理由(证据见 §3) |
|---|---|---|
| 甲:COPY 打到老账号端点 | **排除** | ① 环境链静态全链验证:REPO/GIT_REPO 必进 python env → load_env 加载 `/home/ubuntu/code/trade-data/.env`(含 R2_BACKUP2_* 非空)→ `_route_bucket`(L411)必命中新端点;大头渠道进程另有 systemd `EnvironmentFiles=.env` 直注(铁证)② 凭据/端点错配的实测形态=**403**,而现场=404 NoSuchBucket(认证通过、语义失败)③ 同路由 plain PUT 跨账号写新桶连续 4 天成功(见对照表) |
| **乙:R2 不支持跨账号 copy-source** | **成立(高置信)** | 三重对照唯一变量=cross-account copy-source:跨账号 COPY 5363/5363 全败 vs 同账号 COPY 256/256 成功 vs 跨账号 plain PUT 连续成功;官方 changelog 明确"从不存在桶 COPY → NoSuchBucket"(新账号视角源桶=不存在,实测跨账号桶对新账号端点返回 404,与真缺失不可区分) |
| 丙:桶名/区域/凭据路由写错 | **排除** | 两处 .env 键齐值非空(云 trade-data/.env + mac trade/.env);新端点 HEAD signal-backup2=200(桶确实在);日志桶名与配置一致;若凭据写错应 403 而非 404 |

---

## 2. 现象与范围(日志证据)

### 2.1 fund-nav 10-08(最先发现)
`data/logs/fund_nav_upload_async_20261008_182838.log`(云上):
```
L1  === fund_nav_upload_async 开始 2026-10-08 18:28:38 ===
L2  REPO=/home/ubuntu/code/trade-data GIT_REPO=/home/ubuntu/code/trade-data-signal
L3  [fund-nav] 模式=增量 本次待传 256/256(其余 0 个内容未变化跳过)
L4  [fund-nav] R2_BYTES_TOTAL=562077654
L5  [fund-nav] ⚠ 备份 nav_bucket/02.json -> signal-backup2/pre-upload/20261008/nav_bucket/02.json 失败 status=404
    b'<?xml version="1.0" encoding="UTF-8"?><Error><Code>NoSuchBucket</Code><Message>The specified bucket
    does not exist.</Message><BucketName>signal-backup2</BucketName></Error>'
    ……(256 条同款,L5-L260)
    备份进度行:L69-L264 "备份 xx/256 已备份 0 跳过 0"(4 条,已备份恒 0)
L330 [58/256] ✗ 2c.json status=403 RequestTimeTooSkewed(独立小问题,见 §5)
L538-539 共上传 255/256 -> https://ssd.fx8.store/nav_bucket/ ;✓ 上传完成 255/256, 耗时 4089.8s
L541 ✗ upload-fund-nav 异步上传失败 rc=1 (不静默, 走 notify 告警) → 19:36 邮件真实发出(历史事件)
```

### 2.2 全站范围(滚动日志/多渠道)
- 12 通道共用 `_incremental_upload`(L1204)→ 均调 `_backup_overwritten_keys`;10-08 失败行分布:[index]×2303、[etf-hist]×2234、[trade-sim-json]×502、[fund-nav]×256、[lab]×65、[etf-score]×3 = **5363 行,全部为 pre-upload COPY 失败**(grep -v pre-upload 为空),**无一成功**。
- 大渠道样本(etf-hist):`data/logs/etf_national_team_backfill_20261008_2007.log`:
  `[etf-hist] ⚠ 备份 etf/158042-all.json -> signal-backup2/pre-upload/20261008/etf/158042-all.json 失败 status=404 <Code>NoSuchBucket</Code>…`
- 首个失败时点:滚动日志 `intraday_snapshot_launchd.log`(自 2026-09-13 起 118975 行)首个 NoSuchBucket 在 **L108003**,其前一行 L107799 = `=== intraday_snapshot.sh 开始 2026-10-08 09:25:01 ===` → **全系统首次触发=10-08 早盘首跑即 100% 失败**;该文件全篇 `✓ 备份` 计数=0。10-05~07 为国庆休市(零触发),非"尝试后成功"。
- 历史成功对照(迁移前):`fund_nav_upload_async_20261003_150955.log`:
  `[fund-nav] ✓ 备份 256 个将被覆盖 key -> signal-backup/pre-upload/20261003/ (export-guard L5)`(256/256 成功,当时 BACKUP_BUCKET=signal-backup,同账号)

---

## 3. 根因判定过程(证据链逐环)

### 3.1 三重对照实验表

| 操作 | 源桶(账号) | 目标桶(账号) | 是否跨账号 | 实测结果 | 证据 |
|---|---|---|---|---|---|
| 服务端 COPY | signal-data(老) | signal-backup(老) | 否 | **256/256 成功** | 10-03 日志 "✓ 备份 256 个…"(见 §2.2) |
| 服务端 COPY | signal-data(老) | signal-backup2(**新**) | **是** | **5363/5363 失败 NoSuchBucket** | §2.1/2.2 全部失败行 |
| plain PUT | — | signal-backup2(**新**) | 是 | **连续 4 天成功**(10-05~08) | 新端点 LIST:`backup/sentiment_20261005..20261008.db.gz`、`backup/etf_national_team_20261005..20261008.db.gz`(8 对象,38-70MB 级);`claude-backup/claude-self-20261006..20261008.tar.gz`(3 对象) |
| plain PUT(同晚对照) | — | signal-backup2(新) | 是 | 10-08 21:00 成功 2/2 | `data/logs/backup_db_20261008_2100.log`:`✓ sentiment.db (130788KB -> 38574KB gzip) -> signal-backup2/backup/sentiment_20261008.db.gz (私有桶)` + 同款 etf_national_team 行 |

唯一变量 = copy-source 是否跨账号。plain PUT 跨账号连大对象(70MB)都成功,单独 COPY 全败。

### 3.2 环境链静态全链验证(排除甲)

触发链(云上文件原文):
- `scripts/update_all.sh:130-135`:
  ```
  sudo -n systemd-run --collect --unit="fund-nav-upload-$(date +%H%M%S)" \
    --uid="$(id -u)" --gid="$(id -g)" \
    --setenv=REPO="$REPO" --setenv=GIT_REPO="$GIT_REPO" \
    bash "$REPO/scripts/fund_nav_upload_async.sh"
  ```
  ⇒ transient 服务环境含 REPO/GIT_REPO(全部子进程继承)。
- 大头渠道(index/etf-hist/lab 等)在 update_all 主链跑;`systemctl show` 原文:
  `trade-update-all.service` / `trade-backup-db.service` / `trade-backfill-evening.service` / `trade-etf-national-team.service` / `trade-intraday-snapshot.service` 全部:
  `Environment=GIT_REPO=/home/ubuntu/code/trade-data-signal REPO=/home/ubuntu/code/trade-data MAIN_REPO=… `
  `EnvironmentFiles=/home/ubuntu/code/trade-data/.env (ignore_errors=no)`
  ⇒ R2_BACKUP2_* 由 systemd 直接注入,**这些进程 env 里 R2_BACKUP2_* 结构上不可能缺失**。
- `scripts/upload_r2.py`:L46 `ROOT=Path(__file__).resolve().parent.parent`;/home/ubuntu/code/trade-data-signal/.env 不存在 → 回退 GIT_REPO/.env(同路径不存在)→ **REPO/.env=/home/ubuntu/code/trade-data/.env(存在,含全部 R2_* 非空值)**;`load_env()` L248-266 以 setdefault 注入(L263),`R2_BUCKET` L270 取用——若 .env 全候选落空脚本会 `sys.exit("无 .env")` 直接崩,而 10-08 运行正常 ⇒ .env 必已加载 ⇒ R2_BACKUP2_* 必已在 os.environ。
- `_route_bucket` L402-413:`if BACKUP2_HOST and bkt == BACKUP2_BUCKET: return BACKUP2_HOST, BACKUP2_AK, BACKUP2_SK`;BUCKET=signal-data、`BACKUP_BUCKET = os.environ.get("R2_BACKUP_BUCKET", BACKUP2_BUCKET)`(L299)→ signal-backup2 → **必路由新端点+新凭据**。`s3_request` L530-531 `bkt=bucket or BUCKET; host,ak,sk=_route_bucket(bkt)` 同源。
- 云上 `.env`(2234B,mtime Oct 5 11:18,自迁移后未变):键名 R2_BACKUP2_BUCKET/ENDPOINT/ACCESS_KEY_ID/SECRET_ACCESS_KEY + R2_BUCKET/R2_S3_* 全在;端点脱敏值 R2_S3_ENDPOINT=https://9be954e8****.r2.cloudflarestorage.com(老)、R2_BACKUP2_ENDPOINT=https://24553524****.r2.cloudflarestorage.com(新);桶名 signal-data / signal-backup2。

### 3.3 平台只读探针(跨凭据矩阵 + 桶/前缀实测)

自研 stdlib SigV4 只读探针(云上无 boto3/aws cli),输出原文:

```
矩阵: HEAD /signal-backup2 —— (凭据集 × 端点)
  OLD键 -> OLD端点(9be954e8****…) : 404
  OLD键 -> NEW端点(24553524****…) : 403
  NEW键 -> OLD端点(9be954e8****…) : 403
  NEW键 -> NEW端点(24553524****…) : 200
```
⇒ 若请求发生"端点/凭据错配",形态是 **403 认证失败**;现场失败是 404 语义失败 ⇒ 认证通道是通的(排除甲的另一独立佐证)。

桶级与前缀级(只读 LIST):
```
prefix='pre-upload/'    KeyCount=0          ← 护栏自迁移后零成功、零存量
prefix='backup/'        KeyCount=8          (10-05~08 sentiment/etf_national_team db.gz)
prefix='claude-backup/' KeyCount=3          (10-06~08 tar.gz)
```
新端点 HEAD:signal-data=404(跨账号桶对新账号不可见,与"不存在"同形态)、signal-backup=404、signal-backup2=**200**;老端点:signal-data=200、signal-backup=200、signal-backup2=404。

### 3.4 错误体桶名对位说明(诚实标注)

错误体 `<BucketName>signal-backup2</BucketName>` 报的是**目标桶**(该桶在新账号实测存在,HEAD 200/LIST 正常),与语义推断的"源桶解析失败"在字面上不完全对位。最自洽读法:该请求必然到达新端点(§3.2 环境链),目标桶必然存在,而操作中唯一"对新账号不存在"的桶=源桶 signal-data(§3.3 实测跨账号桶对新账号=404),R2 CopyObject 错误模板以请求路径桶填充 BucketName。**此细节无法用官方文档 100% 钉死,但对修法无影响**(A/B 两方案均不依赖该细节)。若需 100% 法定论:提 CF Support ticket,或另开受控窗口做一次 COPY 实验(新账号 copy-source 指老账号桶;需写操作,本次只读禁令内未做)。

---

## 4. 官方/社区依据(URL + 原文)

**官方(间接依据,未找到"跨账号 copy 不支持"的明文声明——诚实标注)**:
- S3 兼容矩阵页 https://developers.cloudflare.com/r2/api/s3/api/ :`CopyObject ✅`、`x-amz-copy-source ✅`、`UploadPartCopy ✅`,**无任何跨账号注记**。
- R2 官方全文(changelog)https://developers.cloudflare.com/r2/llms-full.txt 原文三句:
  - "The S3 API `CopyObject` source parameter now requires a leading slash."(代码已符合:copy-source 带前导 `/`,L1174)
  - "The S3 API `CopyObject` operation now returns a `NoSuchBucket` error when copying to a non-existent bucket instead of an internal error."
  - "Copying from a non-existent key (or from a non-existent bucket) to another bucket now returns the proper `NoSuchKey` / `NoSuchBucket` response."
- 错误码参考:`NoSuchBucket` 404 —— "Verify the bucket name is correct and the bucket exists in your account."(R2 视角=「你账号里」的桶;跨账号桶不在"你账号"⇒语义重合)

**社区/工具先例(佐证级,非权威)**:
- GitHub `chenqi92/CloneS3toS3`:专为"跨账号 S3 兼容桶互搬"设计的工具,对 Cloudflare R2 作为源专门做直读模式优化——印证"跨账号搬桶=读+写中转,R2 源有特殊性"。
- rclone 等工具的跨存储搬运一律实现为下载+上传(不做跨账号服务端 copy)。
- Cloudflare Community / GitHub issues 检索**未找到**关于 R2 跨账号 copy 的权威原文(社区搜索接口被 CF challenge 拦;GitHub issues 无直接命中)。

---

## 5. 附带发现(顺带,均如实标注)

1. **护栏静默空转**:备份失败仅 `print ⚠`(L1178-1181),调用点 `try/except` 吞异常不阻断(L1448 注释原文「失败不阻断上传,仅记日志」+ L1455-1456)——5363 条失败**从未触发任何告警**;fund_nav 唯一告警来自 rc=1(1 个上传 403),与备份无关。自迁移(10-05)至 10-08,所有覆盖上传实际处于"零备份"状态(§25「备份先于覆盖」承诺失效),**若期间任一上传内容异常将无法回滚**。
2. **fund_nav rc=1 的直接原因**:L330 `[58/256] ✗ 2c.json status=403 RequestTimeTooSkewed`(时钟/重试瞬时问题,255/256 成功),独立小问题。
3. **手动补跑路径疑似断**(推断,未见日志实证):云上手跑 `bash scripts/fund_nav_upload_async.sh` / `python scripts/upload_r2.py upload-fund-nav` 时,REPO/GIT_REPO 为 shell 局部变量(脚本未 export,见 repo_paths.sh 契约「lib 只 assign,绝不 export」;fund_nav_upload_async.sh 正文无 export 行),python 侧 load_env 候选(ROOT=trade-data-signal 无 .env、GIT_REPO/REPO 无)全落空 → 预期 `sys.exit("无 .env")`。生产 systemd 路径不受影响(--setenv/EnvironmentFiles 已注入);全量日志 grep "无 .env" 零命中(云端手动跑未曾记录)。**建议顺手修复(见修法 D)。**
4. **全仓 copy-source 用法仅一处**(`scripts/upload_r2.py:1174`),修复面=单点;12 通道共用同一预上传函数,天然全通。

---

## 6. 修法(全集)

### 修法 A(主修,推荐):跨账号备份改「客户端中转(GET 流式 → PUT)」

改点:`_backup_one`(L1150-1182)内 COPY 调用(L1171-1174)替换为两跳中转:
1. **GET 源**(老账号,BUCKET=signal-data;`s3_request` 需新增 GET 支持——现无 s3_get,参考 L510 s3_request 的 SigV4 与 L628 s3_head 结构);
2. **PUT 目标**(新账号,`bucket=BACKUP_BUCKET` 经 `_route_bucket` 自动路由;复用 `s3_request` payload 或 `_upload_multipart`(L817));
3. 小对象(≤8MiB,本项目该路径对象普遍 ≤ 数 MB:nav_bucket ~2MB/桶、index-all 小型)内存直转;为通用性建议 Range 分片流式(常量内存,防未来大对象)。
- 幂等/减量:现有 bk_st/st 检查(L1154-1165)与"已备份且指纹一致跳过"(L1166-1169)不变,中转后语义不变。
- 对账:单段 PUT ETag=md5 可比(可在 PUT 后 `s3_head` 目标比对);分片 ETag 形如 `md5-N` 按规则处理或跳过对账。
- 重试:沿用 s3_request 内置 5 次退避。
- 成本:R2 egress 免费;操作数由 1 COPY 变 1 GET+1 PUT(Class A,成本可忽略);跨境带宽实测约 0.3-0.4MB/s/连接(代码注释 L456-458 记载),现 8 线程并行,单日备份量级(例 fund-nav 562MB)预计数分钟,夜间窗口充足。
- 收益:**不依赖 R2 是否支持跨账号 copy**;保留 #178 "备份独立账号(额度解耦+私有桶)"全部属性;覆盖甲/乙/丙任何形态。
- 上线后验证清单:①新桶 `pre-upload/` 出现当日对象(只读 LIST)②8 线程并发正常③减量跳过仍生效④失败注入(指向不存在桶)验阻断路径(配合 C)⑤ETag 对账。
- 回退:不保留旧 COPY 双路径(防腐化);如需回退=revert 该 commit。

### 修法 B(备选/快速止血):备份目标桶改回同账号

`R2_BACKUP_BUCKET=signal-backup`(老账号桶)一行 env 即刻恢复——10-03 先例实证同账号 COPY 可用。代价:放弃"备份独立账号/独立额度"(违背 #178 初衷);老桶 lifecycle 回收语义需重评。**仅在 A 排期较长且明确接受降级时用;默认不选。**

### 修法 C(§25 fail-fast):备份失败必须阻断上传 + 预检

- `_backup_overwritten_keys` 统计 `failed`(L1177-1181 两个失败分支)并返回 `(copied, skipped, failed)`(现返回 copied,L1201)。
- 调用点(L1451-1456):去掉吞异常;`failed != 0` → **中止本次上传**(置于 `_upload_glob` L1466 之前,确保"未带备份不覆盖")+ notify severe 一条(失败计数+首因样本+日志路径,走现有告警链)。
- 备份阶段前**预检**:经 `_route_bucket` 探测 `BACKUP_BUCKET` 可达性;不可达 → 立即终止并明确文案(「备份桶不可达,拒绝覆盖上传」),避免 N 条 404 刷屏(本次 5363 条的教训)。
- **顺序约束(重要)**:必须 A(或 B)先上线,C 后开——否则在当前 (100% 失败) 状态下开启 C 会让全站所有上传立即停摆。
- 告警建议:接入现有 dedup-key 机制防风暴。

### 修法 D(加固,防同类复发)

1. `_route_bucket`(L402-413)对 `BACKUP2_BUCKET` 的「env 缺失→静默回退老账号」兼容分支是**炸弹**(该桶仅存在于新账号,回退=必然 404 且不可见):改为 fail-loud(缺失即抛错),或至少在入口 WARN。
2. 异步包裹脚本按 repo_paths 模板补 `export REPO GIT_REPO`(修 §5.3 手动补跑路径)。
3. (可选)每日巡检校验 `signal-backup2 pre-upload/` 有当日对象(只读 LIST),缺失即告警——把"护栏是否在工作"纳入可观测。

### 备选路径全景(乙类问题的其他解,均已评估)

| 方案 | 可行性 | 代价/风险 | 结论 |
|---|---|---|---|
| A 客户端中转 | 已验证基础设施齐(仅缺 GET) | 带宽耗时(分钟级/日) | **推荐主修** |
| B 目标桶改回同账号 | 10-03 实证 | 牺牲独立账号/额度解耦 | 备选止血 |
| 同账号目录前缀备份(备份落源账号内前缀) | 技术可行(同账号 COPY 可用) | signal-data 为公开桶,备份对象将经公开域名暴露(数据泄漏面);与源同故障域,失去灾备意义 | 不推荐 |
| 换备份策略:整站快照(打包→plain PUT 跨账号) | plain PUT 跨账号已实证可行 | 粒度粗(整站回退),无法 1:1 回填单 key;备份动作重 | 不推荐(除非粒度要求放宽) |
| 双写上传(写主桶同时写备份) | 可行 | 上传成本×2、一致性复杂 | 不推荐 |

---

## 7. 附录:本次取证命令与输出摘要

- 云上入口:`ssh -4 -i tdsignal.pem -o ConnectTimeout=10 -o ServerAliveInterval=5 -o ServerAliveCountMax=3 ubuntu@122.51.111.173`,远端命令均 `timeout N` 包裹。
- 代码核读(本地 `scripts/upload_r2.py`,云上 md5=87e307d5e1ccee7c326a29eea61a784c 一致):L46/L51、L228-266、L270、L278-299、L402-413、L510-531、L628、L817、L1146-1201、L1447-1469。
- systemd:见 §3.2(5 个 unit `systemctl show` 原文)。
- R2 只读探针(matrix/LIST/HEAD):见 §3.3 输出原文;`.env` 仅读键名与非空断言,端点脱敏展示,未打印任何 AK/SK 明文。
- 日志:§2 各文件路径与行号。
- 全程未出现后台化任务残留。

## 8. 落档信息

- 本报告=本次调研唯一写入文件;任务链:#237 → 本报告(定因+修法) → 待主控派实施(A+C 同批,按 §5.4⑥ 视改动是否触默认行为/发布版本)→ reviewer → tester。
- 修复后建议回填本报告:最终采用的修法 + 上线日期 + 复验结果(新桶 pre-upload 当日对象在案)。
