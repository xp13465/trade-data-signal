# R2 备份桶容量核查 + 免费额度判定 + 瘦身方案(2026-10-02)

> 用户报告:「R2 备份桶的使用容量好像超过免费额度了」→ 实测判定:**已超限 71%**。
> 本报告所有数字可复现(§复现命令);只读统计,未执行任何删除。

## ① 成本警告与本次 List 调用次数(诚实成本标注)

- ListObjectsV2 属 R2 Class A 操作($4.50/百万次,免费 100 万次/月;官方文档明确列 ListObjects 进 Class A)。
- 本次共发出 **154 次 ListObjectsV2** 调用(主桶 32 + 备份桶 60 + large-json 60 + backup/ 1 + claude-backup/ 1),成本 ≈ **$0.0007**。在当月 Class A 免费额度(100 万次)内,零账单影响。
- 两桶对象数最大 5.9 万,远低于 100 万上限,分页统计完整无截断。

## ② 两桶实测对象数 / 字节数 / GB(2026-10-02 实时 List 全量)

| 桶 | 对象数 | 字节 | GiB | 折合 GB(SI) |
|---|---|---|---|---|
| **主站桶 signal-data** | 31,470 | 3,025,006,609 | **2.817 GiB** | 3.025 GB |
| **备份桶 signal-backup** | 59,586 | 15,352,394,722 | **14.298 GiB** | 15.352 GB |
| 合计 | 91,056 | 18,377,401,331 | **17.115 GiB** | 18.377 GB |

### 备份桶构成(按前缀,字节降序)

| 前缀 | 对象数 | GiB | 占比 | 保留机制(代码证据) |
|---|---|---|---|---|
| mac-backups/2026-10-01 | 86 | **10.171** | 71.1% | 一次性家清归档,**无 prune 只增不减**(见⑤) |
| backup/ 日 DB 备份 | 54 | 2.596 | 18.2% | 30 天滚动裁剪 `_prune_r2_backup`(upload_r2.py:1938-2000;2026-10-03 改 14,见 ⑩) |
| large-json/ | 59,370 | 0.820 | 5.7% | legacy 按天目录 7 天宽限自动清 + 固定前缀唯一副本不删(见⑤) |
| weekly/ + monthly/ + decommissioned/ | 18 | ≈0.670 | 4.7% | weekly 28 天 / monthly 365 天裁剪;decommissioned 无清理 |
| claude-backup/ | 58 | 0.041 | 0.3% | 用户拍板"先不删"(upload_r2.py:2044) |

### 主站桶构成(对象数降序,不动它,仅供总量口径)
fund_nav 26,458 + accum_nav 1,718 + etf 1,718 + trade_sim_data 504 + data 312 + nav_bucket 256 + index 173 + industry 134 + trade_sim 103 + lab 65 + public_fund 13 + offshore_fund 7 + root 5 + fund_score 2 + r2test 1 + test 1 = 31,470 对象。

### large-json 内部构成(59,370 对象 = 0.820 GiB)
- **legacy 按天目录 6 天**:2026-09-25~09-30,共 ≈27,705 对象 ≈ **0.44 GiB**。其中 09-29 全量 11,875 (0.140 GiB)、09-30 15,798 (0.120 GiB)、09-28/27/26 各 8 对象 (~0.046 GiB×3)。
- **固定前缀(唯一副本)≈31,665 对象 ≈0.38 GiB**:fund_nav 26,458 (0.103) + nav_bucket 256 (0.101) + trade_sim 504 (0.047) + etf 1,718 (0.041) + kelly parts 774 (0.054) + index 173 (0.016) + 大 JSON 单文件 ~0.05 + accum_nav 1,718 (0.006) + lab 65 + 其它。

## ③ 免费额度口径判定:账号级合计(非每桶)

- **免费 Storage = 10 GB-month / 月,账号级合计**:官方定价页 Free tier 单列 10 GB-month(developers.cloudflare.com/r2/pricing/,2026-10-01 版);官方 billing examples 把账号全部 R2 存储(如 1,000 GB-months)作为单一项抵扣 10 GB-months(单次抵扣,无按桶拆分);用户 CF 账单也是单行 "R2 Data Storage 2.27 GB-months, free 10 GB-Month included" —— 三者一致:**10 GB 免费是账号所有桶合计**,两桶共 17.115 GiB 一起算。
- **免费额度只适用 Standard 存储**(官方 Caution:不适用 Infrequent Access)。本项目两桶均为 Standard,无 IA 对象。

## ④ GB-Month 滞后窗口分析:账单「2.27」≠ 当前「17.1」

- **GB-month = 计费周期(30 天)内每日峰值存储的平均值**(官方原文:"A GB-month is calculated by averaging the peak storage per day over a billing period (30 days)")。
- 时间线(按实测倒推):
  - 9 月(账单 2.27 GB-months,费用 $0):9 月大部分时间总存量 ≤~7 GiB(large-json 固定前缀改造 09-30 落地,9-29/30 才出现全量 legacy 目录);**9 月没超,免费内**。
  - **10-01 mac-backups 上传 86 个文件 10.171 GiB**(假日家清行动,见 docs/ops/holiday-window-housekeeping-execution-20261001.md:104)→ 总存量从 ~6.9 GiB 跳到 **17.115 GiB**。
  - 用户当前看到的账单 2.27 GB-months = 9 月平均值,自然不含 10-01 的大跳变 → **当前已超限但账单还没体现**的窗口存在,且窗口很长:10 月 1 日起存量即 17.1 GiB,10 月末 11 月初的账单就会按 ≈17.1 GB-months 结算。
- 若 10 月存量保持 17.115 GiB → 10 月账单:超额 ≈ 7.1 GB-month × $0.015 = **≈$0.11/月**(现价),不是巨款,但**免费额度从 10 月起破掉,之后每月持续收费**(除非瘦身)。

## ⑤ 备份桶增长机制:DB 层有裁剪,归档层只增不减(代码证据)

- **DB 备份层(backup/weekly/monthly):有滚动裁剪**。upload-db 每日上传后调 `_prune_r2_backup`(upload_r2.py:2000→1938;2026-10-03 起日层改 14 天,见 ⑩):backup/ 30 天→14 天、weekly/ 28 天、monthly/ 365 天(实测 backup/ 恰 54 对象≈27 天×2,与裁剪吻合)。代码注释(upload_r2.py:1945)称 R2 桶 lifecycle 规则配了同等天数作双保险 —— **S3 API GetBucketLifecycleConfiguration 返回 403(S3 凭证无权限),未能直接验证,标注为「代码声明,未实测」**。
- **large-json/:固定前缀唯一副本,不滚动删**(upload_r2.py:2204-2211,`_prune_large_json`):git 已 rm --cached 移出,R2 是唯一副本,删除=丢数据;**对象数恒定 ≈31,665,字节随源数据内容增长(缓慢)**。legacy 按天目录(09-25~09-30)在 7 天宽限期后由同函数自动清理(≈0.44 GiB,10-07 前后自动释放,**无需手动**)。逃生门 R2_LARGE_JSON_DATE_PREFIX=1(未设,固定前缀模式生效中)。
- **mac-backups / decommissioned / claude-backup:无任何 prune,只增不减**。mac-backups 是一次性家清动作(86 文件 10.171 GiB),不会自动涨,但也不会自动清。
- 结论:**不是单调爆炸式增长**——每天新增约 2×~0.1 GiB DB 备份进入 30 天窗口(平衡态 ~2.6 GiB),large-json 内容微涨;14.3 GiB 备份桶的 71% 是一次性归档(mac-backups)。真正的"会持续缓慢增长"是 large-json 固定前缀内容。

## ⑥ 结论:是否超限 + 是否即将超限

- **已超限**:当前两桶合计 **17.115 GiB > 10 GiB 账号级免费额度,超 71%(7.115 GiB)**。
- **超限原因(归因)**:mac-backups 10.171 GiB(71% 增量)。无 mac-backups 时两桶 ~6.98 GiB,在免费额度内。
- **超限开始时间**:2026-10-01(mac 家清上传当天)。10 月首日即超,10 月末账单开始按超出计费(≈$0.11/月,现价),**非紧急大额成本,但已破免费**。
- **即将超限**:无 mac-backups 不超;不清理则会一直超,幅度随 large-json 内容增长缓升。

## ⑦ 瘦身方案(只出方案,未执行任何删除;每个方案含恢复路径)

### 方案 A(首选,立竿见影):mac-backups 本地恢复后删除 R2 侧 → 释放 10.171 GiB(71%)
- 动作:① GET `mac-backups/2026-10-01/<file>` 全部 86 个落回 `data/backups/`(恢复配方在 holiday-window-housekeeping-execution-20261001.md:123,md5 对账日志 /tmp/mac_backups_upload_log_20261001.txt 留存)② 逐文件 md5 与日志对账 86/86 一致 ③ 对账 PASS 后删除 R2 `mac-backups/2026-10-01/` 86 个 key。
- **影响面**:备份桶 14.3→4.1 GiB,两桶合计 17.1→6.98 GiB,回到免费额度内($0/月)。R2 侧风险窗口=本地恢复完成前(即先恢复后删,窗口内 R2 仍是备份)。
- **可逆性**:删除前先在本地重建完整备份并验证 → 可逆(§25 铁律:备份先建成,删除即安全)。预执行前需确认本地磁盘余量 ≥10G(2026-10-02 data/ 现状:备份目录删除后 data/ 剩 4.0G,需挪/扩容后再恢复)。
- **需求前提**:用户拍板(动的是异地唯一副本;但恢复路径已文档化且 reviewer 独立验证过 GET 通道)。

### 方案 B(温和):DB 保留窗口 30 天 → 14 天 → 释放 ~2 GiB
- 动作:改 `_prune_r2_backup(keep_days=30)`(upload_r2.py:2000)→ 14;同步 R2 lifecycle(如已配同类天数)。
- 影响面:DB 日备份可恢复窗口 30→14 天;etf_national_team 日备份 0.05-0.066 GiB/份、sentiment ~0.037 GiB/份,释放 ≈16 天×2×~0.06≈2 GiB。仍在免费额度边缘(6.98-2=4.98+主桶<10,充足)。
- 可逆性:改参数即可加回;已删对象不可恢复(但 DB 备份每天都有新份,本地 backup_db.sh 也有本地保留,损失=更早历史备份)。

### 方案 C(自动,零动作):large-json legacy 按天目录等 7 天宽限自动清理
- 09-25~09-30 legacy 目录 ≈0.44 GiB 由 `_prune_large_json`(upload_r2.py:2245)在 10-07 前后自动删除,无需手动。**不建议手动提前清**(宽限期设计防过渡期读取,过渡期已结束,手动清也可行但收益小)。

### 方案 D(可选项):claude-backup / decommissioned 梳理
- claude-backup 58 个 tar.gz 仅 0.041 GiB,用户此前拍板不删,保持。
- decommissioned 2 对象(≈0.6 GiB,退役归档)可查证内容后决定去留(若无价值可走 upload-decommissioned 同理的恢复→删除流程)。

### 推荐组合
方案 A(用户拍板后执行)+ 方案 C 自动 + (可选 B)。执行后预期稳态:两桶合计 ~7 GiB < 10 GiB,免费额度回血,月成本 $0。

## ⑧ 复现命令

```bash
# 统计脚本(可复用,已落档)
/Users/linhuichen/code/trade/.venv/bin/python docs/scripts/r2_bucket_stats.py                       # 两桶全量
/Users/linhuichen/code/trade/.venv/bin/python docs/scripts/r2_bucket_stats.py --bucket signal-backup  # 单桶
/Users/linhuichen/code/trade/.venv/bin/python docs/scripts/r2_bucket_stats.py --bucket signal-backup --prefix large-json/
# 2026-10-02 实测关键值:
#   主站桶 signal-data: 31,470 对象 / 3,025,006,609 B / 2.817 GiB (list_calls=32)
#   备份桶 signal-backup: 59,586 对象 / 15,352,394,722 B / 14.298 GiB (list_calls=60)
#   large-json/: 59,370 对象 / 880,788,582 B / 0.820 GiB (list_calls=60)
#   backup/: 54 对象 / 2,787,091,814 B / 2.596 GiB (list_calls=1)
#   claude-backup/: 58 对象 / 44,067,250 B / 0.041 GiB (list_calls=1)

# 官方定价(2026-10-01 版)
#   curl -A "<浏览器UA>" https://developers.cloudflare.com/r2/pricing/
#   关键句:Free Storage 10 GB-month / month;Storage $0.015/GB-month;
#   "A GB-month is calculated by averaging the peak storage per day over a billing period (30 days)"

## ⑨ 诚实标注(局限与未验证项)

1. **R2 lifecycle 配置未能直接验证**:代码注释(upload_r2.py:1945)声称 R2 桶 lifecycle 规则配了与代码相同的保留天数(双保险),但 S3 API `GetBucketLifecycleConfiguration` 返回 **403 AccessDenied**(当前 S3 凭证无此权限)。若 R2 侧 lifecycle 缺失,DB 层清理只靠代码 `_prune_r2_backup`(每日 upload-db 内执行)单一机制;若 R2 侧存在,则是双保险。需更高权限 token 或 CF 控制台确认。
2. **GB-Month 预测是推算**:10 月账单 ≈17.1 GB-months 基于「存量保持 17.115 GiB 不变」的假设;实际若期间再上传/删除会变。9 月 2.27 GB-months 是 CF 账单实际值。
3. **mac-backups 对象数**:实测 86 对象;家清执行文档称「86 个 .db」,reviewer 复核实际为 85 个真 .db + 1 个 .db-shm(sidecar,无业务数据,SQLite 自动重建),不构成缺陷,如实引用。
4. **decommissioned / weekly / monthly 字节为差值推算**(0.670 GiB = 全桶 14.298 − mac 10.171 − backup 2.596 − large-json 0.820 − claude 0.041),未单独 List。如需精确值可对这三个前缀各跑 1 次 List(成本 ~$0.000005/次)。
5. **类 A 操作免费额度**:本月 List 154 次 + 每日上传 PUT(large-json 增量模式实际 PUT 远小于 3.1 万/日)+ DB 备份 ~2 PUT/日,预估远低于 Class A 免费 100 万次/月;操作费用非本报告重点,未逐项核算。
6. **执行状态**:本报告初版只读(方案 A/B/D 均未执行)。**方案 B 已于 2026-10-03 用户拍板执行**(见 ⑩),方案 A(删 mac-backups 10.171 GiB)/D 仍待用户拍板;方案 C 自动。

## ⑩ 方案 B 执行记录(2026-10-03,用户拍板:DB 日备份保留窗口 30 天 → 14 天)

> 本报告原为只读统计(⑨.6「未执行任何删除」),方案 B 于 2026-10-03 经用户拍板执行,本节为该执行的落档。

- **改动**:`scripts/upload_r2.py` `_prune_r2_backup` 默认 keep_days 30→14,`cmd_upload_db` 内调用同步改 `keep_days=14`;docstring/注释同步;weekly(28 天)/monthly(365 天)两级**不变**。
- **R2 侧 lifecycle 核对结果**:`GetBucketLifecycleConfiguration` 本次重测仍返回 **403 AccessDenied**(S3 凭证无此权限),**未能验证**。若 R2 侧存在与代码同天数 lifecycle 规则则双保险;若缺失则清理以代码 `_prune_r2_backup`(每日 upload-db 内执行)为单一机制。**确认路径**:CF 控制台 R2 → signal-backup → Lifecycle rules 人查,或换更高权限 token 重跑 GET ?lifecycle。**此确认项未关闭**(承接 D6 P2-3)。
- **下次 upload-db 运行时将过期对象(2026-10-03 基准,keep_days=14,cutoff=09-19)**:
  - 过期 26 个对象 = 13 天份(2026-09-04/07/08/09/10/11/13/14/15/16/17/18/19)×2 DB
  - 释放 **1,285,523,660 B ≈ 1.197 GiB**(backup/ 总量 2.629 GiB 的 45.5%);剩余 14 天份 28 对象 ≈ 1.43 GiB
  - 注:若下次 run 日期晚于 10-03,cutoff 顺延,过期对象再多(每多 1 天多 2 对象 ≈ 0.1 GiB)
- **长周期恢复能力未丢(实测在位)**:weekly/ 8 对象(09-07~09-28 四周)×2、monthly/ 8 对象(07-21~10-01 四月)×2,均在保留窗口内。
- **本地保留仍在(R2 非唯一副本)**:`scripts/backup_db.sh` 本地 `data/backups/` 保留(脚本默认 RETAIN_DAYS=7,云上 systemd timer 注入 RETAIN_DAYS=7;docs 中部分「本地 14 天」描述为历史遗留偏差,已按 §23.7 不动本地行为,仅在本节如实标注)。
- **2026-10-04 用户澄清目标 = 降低备份容量而非统一**:上轮将本机脚本默认值 7→14 是为对齐 R2 保留期,**属为一个死值放宽了保留期**,现已回退(`scripts/backup_db.sh` RETAIN_DAYS 默认值 14→7,`b9152d925` 引入的改动撤销)。**现行口径三层表**(以本行为准):
  - **R2 异地(DB 日备份)= 14 天**(原 30 天,2026-10-03 缩短,`743c0043c`)
  - **云上本地 = 7 天**(systemd timer 显式注入 `RETAIN_DAYS=7`,云盘预算,维持不动)
  - **本机脚本默认值 = 7 天**(与云上一致;本机无 crontab/launchd 定时任务,**该值为惰性**,不实际运行)
  - 注:历史迁移文档(docs/deploy/migration-inventory-20260912.md / systemd-units-20260912.md)中「14 天」为 2026-09-12 迁移前的历史值,不作现行口径。
- **可逆性**:改参数即可加回 30 天;已删对象不可恢复,但 DB 每天有新备份,损失=更早历史日备份(超过 14 天的日份仍可由 weekly/monthly 层级覆盖部分)。

## 参考

- CF R2 官方定价(2026-10-01 版):https://developers.cloudflare.com/r2/pricing/(llms 版 /r2/llms-full.txt)
- 家清行动执行/审查:docs/ops/holiday-window-housekeeping-execution-20261001.md · holiday-window-housekeeping-review-20261001.md
- 大 JSON R2 备份设计:docs/ops/large-json-out-of-git-20260925.md · docs/ops/126-*.md
- 上传代码:scripts/upload_r2.py(_prune_r2_backup L1938→现 L2094 / _prune_large_json L2199 / cmd_upload_large_json L2344 / cmd_upload_db L1958→现 L2116)
- 统计脚本:docs/scripts/r2_bucket_stats.py
