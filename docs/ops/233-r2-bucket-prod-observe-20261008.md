# #233 R2 两桶 复市后生产观察报告(2026-10-08)

> **派单**:#233 遗留两个「从未验证过」的风险面 —— ① 跨账号 pre-upload server-side COPY 是否真能跑通(失败只记日志不阻断 ⇒ 可能静默少备份);② 新桶复市后按 ~1.1 GiB/天 外推可能逼近 10 GB 免费线。
> **本次范围**:云上只读(ssh 读日志/读 unit/读 .env 键名)+ R2 只读 LIST。**零写、零外发、零启停、未跑任何业务脚本、未 commit。**
> **采样时刻**:R2 容量 2026-10-08 22:37 CST(14:37Z);日志为 10-08 当晚读。

## 0. 一句话结论

**有异常,且是最严重的那一类**:① **pre-upload 跨账号 COPY 100% 失败(404 NoSuchBucket),且静默** —— 新桶 `signal-backup2/pre-upload/` 自 10-05 切桶以来**对象数 = 0**,"覆盖前先备份"这道数据护栏在生产上**从未生效过一次**;② 新桶容量 4.226 GiB(远低于 10 GB 线),**但这是"链路停摆"造成的,不是安全** —— 复市首日(10-08)deploy 整日卡在 `check_data_integrity` 失败,deploy 的 R2 上传段与 staticdata 备份段**整日未执行**(旁证:10-08 无任何 `r2_upload_async_*.log` / `staticdata_backup_async_*.log`);③ 老桶 7.456 GiB,按 lifecycle 时间线正常推进,10-10~12 前未明显下降(符合预期)。

## 1. 问题①:pre-upload 跨账号 COPY —— 真跑过,真失败,静默(核心发现)

### 1.1 原文行(带时间戳/路径)

**A. fund-nav 通道** `/home/ubuntu/code/trade-data/data/logs/fund_nav_upload_async_20261008_182838.log`(18:28 起跑,19:36 结束):

```
L5:  [fund-nav] ⚠ 备份 nav_bucket/02.json -> signal-backup2/pre-upload/20261008/nav_bucket/02.json 失败 status=404 b'<?xml version="1.0" encoding="UTF-8"?><Error><Code>NoSuchBucket</Code><Message>The specified bucket does not exist.</Message><BucketName>signal-backup2</BucketName></Error>'
L6:  [fund-nav] ⚠ 备份 nav_bucket/07.json -> ... 失败 status=404 ... <Code>NoSuchBucket</Code> ... <BucketName>signal-backup2</BucketName> ...
... (同款 256 行)
```
计数(实测):`失败 status=` **256** 行 / `✓ 备份` **0** 行 / `减量跳过` **0** 行;错误码分布 `NoSuchBucket` **256** + `RequestTimeTooSkewed` 1。文件体量 86,324 B(往常同通道约 9 KB)。

**B. intraday 通道** `/home/ubuntu/code/trade-data/data/logs/intraday_snapshot_20261008_1535.log`:

```
L88: [index] ⚠ 备份 index/hk_hsmogi-all.json -> signal-backup2/pre-upload/20261008/index/hk_hsmogi-all.json 失败 status=404 b'...<Code>NoSuchBucket</Code><Message>The specified bucket does not exist.</Message><BucketName>signal-backup2</BucketName>...'
```
该轮 `失败 status=` **53** 行(标签覆盖 [index] 等多通道)。

**C. 对照:同一段代码在切桶前是成功的**(同通道、同函数、同批 256 个 key)

`/home/ubuntu/code/trade-data/data/logs/fund_nav_upload_async_20261003_150955.log`:
```
L5:  [fund-nav] ✓ 备份 256 个将被覆盖 key -> signal-backup/pre-upload/20261003/ (export-guard L5)
```
(`失败 status=` = 0)⇒ **不是"从来如此",是 10-05 切桶后的回归。**

**D. 新桶侧独立佐证(只读 LIST)**:`signal-backup2` 全桶 `pre-upload/` 前缀 **0 对象**(`pre_upload_days = {}`)——即**切桶以来没有任何一次 COPY 成功过**。对照老桶 `pre-upload/` 仍有 6,585 对象(10-03~10-05 存量)。

### 1.2 性质与影响

- 失败语义 = 「记日志不阻断」(`scripts/upload_r2.py:1178-1181`):上传照常进行,只把警告写 stderr ⇒ **静默少备份**。这正是 #233 报告 §5 点名的最严重风险面。
- 影响面 = §25 数据护栏:**每次覆盖前应留一份"覆盖前现场",实际一份都没留**。当前没有真实数据损失(没有出现"覆盖后才发现要回滚"的场景),但**回滚能力实际为 0**。
- 触发条件 = 「待上传 key 在 R2 已存在」。10-05~10-07 假期无数据变更 ⇒ 零次触发 ⇒ 缺陷潜伏;10-08 复市首日一触发即 100% 失败。

### 1.3 机制未定论(诚实标注:两种假设,本次只读证据无法区分)

已排除的因素(逐项实测):
- 云端 `/home/ubuntu/code/trade-data/.env` **四键齐全**:`R2_BACKUP2_ENDPOINT / R2_BACKUP2_BUCKET(=signal-backup2) / R2_BACKUP2_ACCESS_KEY_ID(len=32) / R2_BACKUP2_SECRET_ACCESS_KEY(len=64)`;`R2_BACKUP2_ENDPOINT` 与**本机 .env 逐位同值**(md5 前 12 位 `cff0ede5b2c9`,len 65,带 scheme),且与老账号端点**不同**(新 `2455352499…` / 老 `9be954e87f…`)。
- 云端**实际运行副本** `/home/ubuntu/code/trade-data/scripts/upload_r2.py`(mtime Oct 7 17:17)含 `_route_bucket` 5 处 / `BACKUP2_HOST` 5 处 ⇒ 路由代码在位。
- `trade-intraday-snapshot.service` 有 `EnvironmentFile=/home/ubuntu/code/trade-data/.env` + `REPO/GIT_REPO` ⇒ 该进程环境理论上带 BACKUP2 键。
- 同进程族对**新桶的普通 PUT 是成功的**(见 §4:`-> signal-backup2/backup/…` 2/2)⇒ 凭据/端点本身可用。

剩余两种候选机制(需写操作或跑探针才能定论,**本次未做**):
- **(甲) 路由落老账号**:COPY 的 PUT 被发到老账号端点(该进程 `BACKUP2_HOST` 为假)⇒ 老账号没有该桶 ⇒ 服务端回 `NoSuchBucket(signal-backup2)`。**零风险验证法**:在该 unit 环境里只打印 `_route_bucket("signal-backup2")` 的结果(不触发任何 PUT),即可证真/证伪。
- **(乙) R2 不支持跨账号 copy-source**:路由正确(到新账号),但 `x-amz-copy-source: /signal-data/…` 的源桶在新账号不可见 ⇒ R2 以 `NoSuchBucket` 形式拒绝(错误 XML 里回显请求路径桶)。**验证法**:一个受控 COPY 实验 / 官方文档;本次按 §5.1(L47 外部系统先查社区)做过检索,**未取得权威结论**。
- **两机制下都成立的修法** = 跨账号时退化为**客户端拷贝**(源账号 GET → 目标账号 PUT)或把 pre-upload 备份目标改回同账号桶。

## 2. 问题②:新桶容量 / pre-upload 增量 vs 外推

| 项 | 10-07 21:12 CST(#233 基线) | **10-08 22:37 CST(本次)** | 增量 |
|---|---|---|---|
| 全桶对象/字节 | 31,692 / 2,148,344,504 B(2.001 GiB) | **31,696 / 4,537,898,470 B(4.226 GiB)** | +4 obj / **+2.225 GiB** |
| `pre-upload/` | 0 obj(空) | **0 obj(空)** | **+0**(外推 28-h 应 ~+1.3 GiB) |
| `backup/` | 6 / 330,618,259 B | 8 / 440,970,692 B | +2 obj / +105.2 MiB(10-08 DB 备份) |
| `mac-backups/` | 无 | 1 / 2,278,230,346 B(2.122 GiB,mtime 10-07T15:18:03Z) | +2.122 GiB(一次性归档,**非日常通道**) |
| `large-json/` | 31,673 / 454,498,988 | 31,673 / 454,498,992 | ~0(10-08 deploy 未跑) |
| `decommissioned/` `weekly/` `monthly/` `claude-backup/` | — | 1,140,898,597 / 110,197,083 / 110,197,083 / 2,862,850 | claude +1 obj(+0.9 MiB),余持平 |

- **对照外推**:`pre-upload/` 增量 **0**,**远低于** ~1.1 GiB/天 —— 但原因是**护栏坏掉(§1)+ deploy 链路停摆(§5)**,不是"量小"。**风险② 是被推迟,不是被消除**:一旦 COPY 修好,按 7 天保留 × ~1.1 GiB/天 ≈ 7.7 GiB,叠加当前 4.226 GiB 底 = **~12 GiB,会越过 10 GB 免费线**。修 COPY 时应同步评估免费额度。
- 全桶 +2.225 GiB 的构成:2.122 GiB 是 10-07 深夜写入的 `mac-backups` 一次性归档(与老桶同名对象等大 2,278,230,346 B),**不属日常备份节奏**,不构成"链路失控"。

## 3. 问题③:老桶 lifecycle 趋势(10-10~12 前不应明显下降)

| 项 | 10-07 基线 | **10-08 22:37 CST** | 变化 |
|---|---|---|---|
| 全桶 | 38,327 / 8,155,372,290 B(7.595 GiB) | **38,323 / 8,005,831,751 B(7.456 GiB)** | -4 obj / **-142.6 MiB(-1.7%)** |
| `pre-upload/` | 6,585 / 3,453,993,283 B | **6,585 / 3,453,993,283 B**(max mtime 10-05T04:55:32Z) | **逐位持平** |
| `backup/` | 24 / 1,319,114,393 B | 21 / 1,170,366,731 B | -3 obj / -141.9 MiB(14 天期回收) |
| `claude-backup/` | 28 / 22,852,892 B | 27 / 22,060,015 B | -1 obj / -0.76 MiB(30 天期回收) |

**结论:符合预期**。无批量下降(未到龄),-142.6 MiB 全部来自 `backup/`+`claude-backup/` 的规则内逐日回收;**首批 pre-upload 存量(3.29 GiB)到龄时钟在 10-10~12**,届时才应出现 -3.2 GiB 的大台阶。

## 4. 问题④:最近成功的备份清单(链路仍活的部分)

1. **DB 备份(10-08 21:00→21:14,退出码 0,含恢复演练)** `/home/ubuntu/code/trade-data/data/logs/backup_db_20261008_2100.log`:
   - `✓ sentiment.db (130788KB -> 38574KB gzip) -> signal-backup2/backup/sentiment_20261008.db.gz (私有桶)`
   - `✓ etf_national_team.db (248364KB -> 69191KB gzip) -> signal-backup2/backup/etf_national_team_20261008.db.gz (私有桶)`
   - `DB 上传 2/2 -> signal-backup2/backup/ (20261008)`;随后 `verify_backup.sh` 只读恢复演练:两库 integrity 全 ok + 12 张关键表行数逐表一致 ⇒ `VERIFY_OK=1`,退出码 0(见 `verify_backup_20261008_2112.log`)。
   - ⇒ **新账号的普通 PUT 通道是活的**(这同时是 §1.3 排除"凭据/端点不可用"的依据)。
2. **staticdata 备份 / R2 上传(最后一次 = 10-07 21:16→21:29,10-08 未跑)**:`staticdata_backup_async_20261007_211644.log` → 27 files / 39,589,329 B 入 staticdata git;`large-json 上传 2/2 -> signal-backup2/large-json/`(signal_kelly_trades_sdc.json 84MB→14MB gz、signal_kelly_trades.json 82MB→13MB gz);`r2_upload_async_20261007_211623.log` 退出码 0(verify-r2 自动补传 2 个)。

## 5. 旁证(直接解释 ①② 为何长这样):10-08 deploy 链整日停摆

- 10-08 全部 **14** 个 deploy 日志均以同一行终止:`✗ 数据产物校验失败(退出码 1)，终止部署（4 类事故拦截）`(fail 数 6 → 3 → 1 逐步收敛,即 `docs/ops/deploy-integrity-selflock-20261008.md` / #235 正在处置的问题)。
- deploy.sh 中 R2 上传触发(:582)与 staticdata 备份触发(:913)都在该闸门**之后** ⇒ 整日未执行。机器枚举佐证:`data/logs` 下 `-mmin -1500` 全量文件清单中,**无任何 `r2_upload_async_2026 1008_*.log`、无 `staticdata_backup_async_20261008_*.log`**(最后一条分别是 10-07 21:29 / 10-07 21:21)。
- ⇒ 「复市首日新桶没按外推涨」有两个叠加原因:护栏坏(§1)+ 批量通道停摆(§5)。**注意区别**:`pre-upload` 的失败是**真实发生的**(§1.1 有两条日志实证),不是"没被触发"。

## 6. 诚实标注

- **实测(可复核)**:三处 R2 LIST 数字与 mtime(§2/§3);两条日志的逐行原文与计数(§1.1);`.env` 四键存在性/端点 hash/AK·SK 长度;运行副本含路由代码;systemd unit 的 EnvironmentFile;deploy 日志终止行与日志目录文件清单;backup_db 通道 2/2 成功 + 恢复演练 PASS。
- **推断(未定论)**:**机制(甲)/(乙)二选一**(§1.3);`mac-backups` 2.122 GiB 判定为一次性归档(依据:对象数与等大对照,未找到对应操作日志)。
- **未测**:① 主桶 `signal-data` 本轮未测(不在派单范围);② (甲)/(乙)未定论 —— 定论需写操作或跑探针,本次禁写未做;③ 老桶 10-10~12 的首批 pre-upload 到龄回收**尚未发生**,无法测;④ `GetBucketLifecycleConfiguration` 仍 403(继承 #233,规则以用户 dashboard 为准);⑤ 未清点全部 10-08 通道日志的失败行总数(仅精确计数了 fund-nav 256 与 intraday 单轮 53)。
- **本次零副作用**:无 PUT/COPY/DELETE、未启停 unit、未跑备份脚本主体、未外发通知、未切分支、未 commit。

## 7. 复现命令

```bash
# ① 容量(只读 LIST;凭据自 repo/.env 读入,不打印密钥)
/Users/linhuichen/code/trade/.venv/bin/python /tmp/r2cap_measure.py signal-backup2 /tmp/r2cap_out/new2.json   # -> 31696 / 4537898470 B (4.226 GiB)
/Users/linhuichen/code/trade/.venv/bin/python /tmp/r2cap_measure.py signal-backup  /tmp/r2cap_out/old2.json   # -> 38323 / 8005831751 B (7.456 GiB)
#   脚本核心:upload_r2.s3_request("GET","",query="list-type=2&max-keys=1000&continuation-token=…",bucket=<桶>)
# ② 失败原文(指定单文件,勿整树 grep)
ssh -4 -i ~/tdsignal.pem ubuntu@122.51.111.173 \
  "timeout 60 grep -n 'NoSuchBucket' /home/ubuntu/code/trade-data/data/logs/fund_nav_upload_async_20261008_182838.log | head -5"
# ③ 计数
ssh … "timeout 60 bash -c 'f=…/fund_nav_upload_async_20261008_182838.log; grep -c \"失败 status=\" \$f; grep -cE \"✓ 备份|减量跳过\" \$f'"
# ④ 对照(切桶前成功)
ssh … "timeout 60 grep -n '将被覆盖' /home/ubuntu/code/trade-data/data/logs/fund_nav_upload_async_20261003_150955.log"
# ⑤ 停摆佐证(限 depth、限目录)
ssh … "timeout 60 find /home/ubuntu/code/trade-data/data/logs -maxdepth 1 -type f -name 'r2_upload_async_20261008*' -o -maxdepth 1 -name 'staticdata_backup_async_20261008*'"
```

## 8. 参考
- `docs/ops/r2-backup-bucket-capacity-20261007.md`(#233 基线)· #178/#179/#185/#186
- `scripts/upload_r2.py`(:286 备份桶常量 / :402-412 `_route_bucket` / :1120-1201 `_backup_overwritten_keys`,失败只记日志在 :1178-1181)
- `scripts/deploy.sh`(:582 R2 上传触发 / :913 staticdata 备份触发,均在数据校验闸门之后)
