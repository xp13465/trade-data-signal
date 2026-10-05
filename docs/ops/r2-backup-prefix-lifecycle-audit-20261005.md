# R2 备份桶 signal-backup 前缀 × 清理机制 普查报告(2026-10-05,全程只读)

> ⚠️ **主控复核注(2026-10-05 归档时加,务必先读)** —— 本报告 §4.2/§7 那句「新桶 `signal-backup2` ListObjectsV2 → 404,**桶不存在**」**与主控实测矛盾,已判定为探针工件,勿据此认为桶不存在**:主控 2026-10-05 用新账号凭据对该桶做过五动作实测 **PUT 200 / HEAD 200(etag `8da843ff65205a61374b09b81ed0fa35`)/ DELETE 204 / 复查 404 全过**。极可能原因 = 探针复用了 `scripts/upload_r2.py` 的 `_list_keys`,而该脚本 `ENDPOINT`/`AK`/`SK` 是**模块级单套全局变量指向老账号**、`bucket` 仅作路径分量 ⇒ 拿老账号端点找新桶必然 404。**✅ 已复核完毕(2026-10-05,结论=主控判断正确):新桶 `signal-backup2` 存在且为空,404 系探针工件。** 复核证据:云上 monkeypatch 脚本 `/tmp/list_backup2.py` 把 `upload_r2` 模块级 `ENDPOINT`/`HOST`/`AK`/`SK` 换成新账号值后调 `s3_request(GET, query="list-type=2&delimiter=/&max-keys=1000", bucket="signal-backup2")` → **status 200、prefixes=[]、keys_in_page=0**;并印证 `s3_request`(L404-473)确实吃模块级全局 `HOST`/`AK`(L435/463)、`bucket` 只拼进 `path`(L430)。**⇒ 新账号 token 具备 ListObjects 权限**(能 200 列桶),不是权限缺失,**对 #178/#179 实施方式无阻碍**;建议直接在已建好的空桶上配同一套 lifecycle 规则。**除这一处外,本报告其余数字均为云上实测,可作 #178/#179 的实施依据。**


> 任务:老桶 signal-backup 全前缀 × (对象数/字节) × 清理机制,产出「代码切走后失控的前缀清单 + 建议 lifecycle」。
> 基准事实(用户 dashboard 实测 2026-10-05):**老桶只有 `backup/` 14 天一条 lifecycle 规则,其余前缀全无**;`weekly/` 28 天 / `monthly/` 365 天是**代码 `_prune_r2_backup` 的保留期、不是桶规则**。
> 取证方式标注:【云上实测】= 2026-10-05 ssh `ubuntu@122.51.111.173`(tdsignal.pem)+ `/home/ubuntu/code/trade-data/.venv/bin/python` 加载 `scripts/upload_r2.py` 用其 `s3_request`/`_list_keys` 列桶(脚本 /tmp/list_r2_counts.py / preupload_days.py);【代码】= 本地 `scripts/upload_r2.py:行号`;【lifecycle】= 用户 CF dashboard 实测;【文档】= docs/ops/*.md。

---

## 1. 前缀全量表(实测,2026-10-05)

| 前缀 | 对象数 | 总字节 | MiB | GiB | 取证 |
|---|---|---|---|---|---|
| backup/ | 28 | 1,537,824,096 | 1466.6 | 1.43 | 【云上实测】明细 20260921~20261004,每 DB 14 天×2 |
| weekly/ | 8 | 405,436,133 | 386.6 | 0.38 | 【云上实测】20260907~20260928×2 |
| monthly/ | 8 | 303,160,886 | 289.1 | 0.28 | 【云上实测】20260721~20261001×2 |
| pre-upload/ | 5,540 | 3,361,005,696 | 3205.3 | 3.13 | 【云上实测】见 §3.2 按日明细 |
| large-json/ | 59,346 | 733,529,084 | 699.6 | 0.68 | 【云上实测】legacy 2 目录 27,673 + 固定前缀 flat 31,673 |
| claude-backup/ | 61 | 46,745,631 | 44.6 | 0.04 | 【云上实测】20260806~20261005 每天 1 个 |
| decommissioned/ | 2 | 10,980,169 | 10.5 | 0.01 | 【云上实测】2 个退役归档 |
| mac-backups/ | 1 | 2,278,230,346 | 2172.7 | 2.12 | 【云上实测】mac-backups/archive/mac-backups-2026-10-01.tar.zst(86 散文件已按文档 10-02 删净,只剩 archive 打包) |
| **合计** | **65,994** | **8,676,912,041** | **8275.0** | **8.08** | 顶层 delimiter=/ 实测无松散 key |

---

## 2. 归属矩阵(谁在清 / lifecycle / 切走后谁清)

| 前缀 | 对象数 | 字节 | 现由代码清?(函数:行号 / 保留期) | 有 lifecycle 吗 | 代码切走后谁清 |
|---|---|---|---|---|---|
| backup/ | 28 | 1.47 GiB | `_prune_r2_backup`→`_prune_layer("backup/",14)` upload_r2.py:2108/2158;触发=backup_db.sh:94(upload-db),云上 trade-backup-db.timer 每日 21:00 | **有,14 天(用户实测)** | **lifecycle 兜底**,14 天内自动清空,不会失控 |
| weekly/ | 8 | 0.38 GiB | `_prune_layer("weekly/",28)` upload_r2.py:2109(同日 21:00 通道) | 无 | **无人清,永久滞留** |
| monthly/ | 8 | 0.28 GiB | `_prune_layer("monthly/",365)` upload_r2.py:2110(同日) | 无 | **无人清,永久滞留** |
| pre-upload/ | 5,540 | 3.13 GiB | `_prune_pre_upload` upload_r2.py:939(7 天,`_PREUPLOAD_RETENTION_DAYS=7` :936),由 `_backup_overwritten_keys` :1006 调,在 `_incremental_upload` :1252 内(12 个增量上传通道共用) | 无 | **无人清,永久滞留 3.13 GiB** |
| large-json/ | 59,346 | 0.68 GiB | `_prune_large_json` :2356 由 cmd_upload_large_json :2830 调,**仅全部上传成功才执行**(:2806 失败即 exit);legacy 按天目录 7 天宽限后清;固定前缀 flat 31,673 唯一副本不滚动删 | 无 | **无人清**:legacy 27,673 滞留;flat 本来就保留 |
| claude-backup/ | 61 | 0.04 GiB | **无 prune**(cmd_upload_claude_backup :2202 明确"R2 端不做滚动清理");写入=本机 launchd com.claude.self-backup(backup_claude_self.sh:45,03:17 每天 1 个) | 无 | **无人清,永久滞留** |
| decommissioned/ | 2 | 0.01 GiB | **无 prune**(cmd_upload_decommissioned :2164 退役归档,长期留存) | 无 | **刻意保留**(手动归档) |
| mac-backups/ | 1 | 2.12 GiB | **无 prune**(一次性家清归档 2026-10-01) | 无 | **刻意保留**(无规则=不受删除风险,#169 用户实测确认) |

---

## 3. 会无限堆积的风险清单 + 堆积速度量化

### 3.1 老桶「代码切走后」逐前缀结论

代码切走 = 老桶不再有新写入、也没有代码 prune 跑。此时:
- **backup/**:不失控。有 lifecycle 14 天兜底,14 天内自动清空。反是当前唯一安全前缀。
- **weekly/ / monthly/ / pre-upload/ / large-json/ legacy / claude-backup/**:**全部变永久滞留**(无 lifecycle,代码不再清)。老桶 8.08 GiB 中非 backup/ 部分 **≈6.61 GiB 永远占容量**。
- **decommissioned/ / mac-backups/archive/**:刻意保留,不算失控,处置意图见 §5。

### 3.2 堆积速度(每前缀单位时间增量,依据写入频率)

| 前缀 | 单位时间增量 | 依据 |
|---|---|---|
| pre-upload/ | **~1,850 对象/天,~1.08 GiB/天** | 【云上实测】10-03:277 个 722.1MB / 10-04:2697 个 1353.5MB / 10-05:2566 个 1129.8MB;机制=每次增量上传前把将被覆盖的 key COPY 到 pre-upload/<YYYYMMDD>/,export-guard L5(上传_r2.py:973) |
| backup/ | 2 对象/天,~0.1 GiB/天 | etf ~0.05-0.066 GiB/份+sentiment ~0.037 GiB/份(【文档】r2-backup-bucket-capacity-20261002.md);14 天窗口平衡态 28 对象 ~1.5 GiB |
| weekly/ | 2 对象/周,~0.39 GiB/4周 | 4 周窗口 8 对象 |
| monthly/ | 2 对象/月,~0.28 GiB/12月 | 12 月窗口 |
| large-json/ | flat 31,673 恒定,内容变才 PUT(量小) | 固定前缀唯一副本不滚动删 |
| claude-backup/ | 1 对象/天,~0.7 MB/天 | 本机 launchd 03:17(backup_claude_self.sh) |
| decommissioned/ / mac-backups/ | ~0(手动/一次性) | — |

### 3.3 多久撑爆免费额度(10 GB-month,账号级)

- **老桶(冷冻)**:无新增,不会爆。但非 backup/ 的 6.61 GiB 永久滞留,老 CF 账号若还有公共桶(主桶 signal-data)一起算,当前老账号合计约 8.08+主桶;主桶约 4-5 GiB(【文档】10-02 两桶共 17.1 GiB,减 mac 10.17 后 ≈6.98,其中备份桶 8.08 已含 mac archive)→ 老账号合计可能已在 10 GiB 边缘。**关键是 pre-upload/ 3.13 GiB 的存量若不清,一直占着。**
- **新桶(signal-backup2,若只配 backup/ 14 天一条 lifecycle、且代码 prune 停跑)**:**pre-upload/ 每天 ~1.08 GiB 增长 → ~9 天撑爆 10 GiB 免费额度**(backup/ 平衡 ~1.5 GiB 有 lifecycle,claude/大 JSON 量小)。**pre-upload/ 是唯一会在「无 lifecycle + 无代码清」下真正无限堆满的前缀。**

---

## 4. 建议的 lifecycle 配置(逐前缀,区分意图)

### 4.1 老桶(冷冻后自然回收)——给「会滞留」的前缀补规则
| 前缀 | 建议天数 | 理由(数字依据) | 备注 |
|---|---|---|---|
| backup/ | **已配 14 天** | 与代码一致;已有,不动 | — |
| pre-upload/ | **补 7 天** | 与代码 `_PREUPLOAD_RETENTION_DAYS=7`(upload_r2.py:936)一致;7 天内清空 3.13 GiB 存量 | **最高优先**,体量+增速最大 |
| weekly/ | **补 28 天** | 与代码 `_prune_layer("weekly/",28)`(:2109)一致;28 天后清 0.38 GiB | — |
| monthly/ | **补 365 天** | 与代码 `_prune_layer("monthly/",365)`(:2110)一致;12 月后清 | — |
| large-json/ | **legacy 补 7 天**(前缀 `large-json/` 按日期目录) | 与代码 `_prune_large_json` legacy 7 天宽限(:2403)一致;legacy 27,673 对象 10-07 前后本来就会被代码清,补规则防代码停跑后滞留 | **固定前缀 flat 31,673 不配删除规则**(唯一副本,删=丢数据) |
| claude-backup/ | **补 30 天** | 本地已 30 天滚动(backup_claude_self.sh:38),R2 侧镜像同一窗口即可;清 0.04 GiB(小) | 若用户想留更长也可,数字可议 |
| decommissioned/ | **不配删除规则** | 手动退役归档,长期留存意图(cmd_upload_decommissioned :2164) | **刻意保留** |
| mac-backups/ | **不配删除规则** | 一次性归档,无规则=不受删除风险(#169 用户实测确认豁免意图) | **刻意保留** |

### 4.2 新桶(signal-backup2,今后新写)——防"代码切走后失控"的根子
新桶当前**存在且为空**(2026-10-05 复核,见顶部主控复核注;早前「404 不存在」系探针工件已更正)。建议**直接在已建好的空桶上照抄上面同一套规则**(backup/ 14 + pre-upload/ 7 + weekly/ 28 + monthly/ 365 + large-json legacy 7 + claude-backup/ 30,固定前缀与 decommissioned/archive 不配),让"自动回收"由 R2 侧独立承担,不依赖代码每天跑。**否则新桶 pre-upload/ 单点 ~9 天爆 10 GiB 免费额度(§3.3)。**

---

## 5. 待用户确认清单
1. **mac-backups/archive/mac-backups-2026-10-01.tar.zst(2.12 GiB)**:刻意保留到何时?(当前无规则=安全;若日后想清,须先取回本机验证)
2. **decommissioned/ 2 个对象(10.5 MB)**:退役归档长期保留,是否接受永久占容量?
3. **claude-backup/ 保留期**:R2 侧当前无清理,建议 30 天镜像本地滚动;用户想留更长可议。
4. **老桶整体处置**:是「等 backup/ 14 天 + 补规则自动清」还是「一次性清空其余前缀释放容量」(后者需先确认各前缀确实无恢复需求;large-json flat 31,673 是唯一副本不可清)。

---

## 6. 用户原话回答:「其余七个前缀一个 lifecycle 都没有,全靠代码清,所以现在容量越来越大是不是也是因为缺少兜底清理规则?」

**答案是「部分是,但更准确地说是『当下靠代码兜底所以没爆,缺 lifecycle 是切走后的爆炸引信,而非当下容量变大的主因』」。**

用数字说话(当下实测 2026-10-05,老桶 8.08 GiB):
- **当下容量大的直接原因有三,缺 lifecycle 不在最前面**:①`mac-backups/archive/` 一次性归档 **2.12 GiB**(占 26%,刻意保留,无代码清,也无 lifecycle 规则,但它是一次性不涨);②`pre-upload/` **3.13 GiB** 且有代码清(7 天,upload_r2.py:939),它日增 **~1.08 GiB/天**,是增速最大项——**但当下它正在被代码清,不是「无人清而堆大」,是「写入频率高导致 7 天滚动稳态本身就大」**;③正常滚动层 backup/ 1.47 + weekly/ 0.38 + monthly/ 0.28 + large-json/ 0.68 ≈ 2.8 GiB,这些当下代码都在清,稳态平衡、不无限涨。
- **真正「无任何清理机制」的当下前缀只有三个,且都不大/不涨**:mac-backups/archive/(2.12,一次性)、claude-backup/(0.04,无 prune 但每天仅 0.7MB)、decommissioned/(0.01,手动)。所以「缺 lifecycle 导致现在越来越大」**不成立**——现在最大的 pre-upload/ 恰恰是有代码清的。
- **缺 lifecycle 的真实后果是未来**:代码 prune 依赖代码每天跑、且只删带日期后缀的 key。**代码一切走(迁移到新桶/停跑),weekly/ monthly/ pre-upload/ large-json legacy/ claude-backup/ 全部变永久滞留 ≈6.61 GiB;新桶若不补 pre-upload/ 的 lifecycle,~9 天就爆 10 GiB 免费额度(§3.3)。**这才是「缺兜底清理规则」真正要防的事。

---

## 7. 取证方式清单(每条数字可复核)
- 【云上实测-前缀全集】ssh + `/home/ubuntu/code/trade-data/.venv/bin/python /tmp/list_r2_prefixes.py`(ListObjectsV2 delimiter=/,signal-backup)→ 8 个前缀,无松散 key。
- 【云上实测-逐前缀计数】`/tmp/list_r2_counts.py`(分页 max-keys=1000 全量 List)→ 各前缀对象数/总字节(合计 8,676,912,041 B)。
- 【云上实测-明细】`/tmp/inspect_r2.py`(backup/weekly/monthly 全 key 名;mac-backups/ 1 个 archive;large-json legacy 2 目录 27,673 vs flat 31,673;claude-backup 61 个;decommissioned 2 个)。
- 【云上实测-pre-upload 按日】`/tmp/preupload_days.py` → 10-03/10-04/10-05 各对象数与字节。
- 【云上实测-新桶·复核后更正】`/tmp/inspect_r2.py` list signal-backup2 → 404(**探针工件**:复用了模块级老账号端点,已作废)。**复核(2026-10-05)**=`/tmp/list_backup2.py` monkeypatch 新账号 ENDPOINT/HOST/AK/SK 后 `s3_request(GET, list-type=2&delimiter=/, bucket=signal-backup2)` → **200 / prefixes=[] / keys_in_page=0** ⇒ **桶存在且为空**。
- 【云上实测-timer/service】`systemctl list-timers` + `cat /etc/systemd/system/trade-backup-db.service|.timer`(21:00,注入 RETAIN_DAYS=7 本地盘)。
- 【代码】`scripts/upload_r2.py`:L2094(_prune_r2_backup)/L2108-2110(_prune_layer 三层)/L2158(cmd_upload_db 内执行)/L939(_prune_pre_upload)/L1006(L982/_backup_overwritten_keys)/L1252(_incremental_upload 内)/L2356(_prune_large_json)/L2830(仅全成功执行)/L2202(claude 不删 R2 旧)/L2164(decommissioned 不 prune);`scripts/backup_db.sh:94`(upload-db);`scripts/backup_claude_self.sh:38,45`(本地 30 天滚动+R2 上传);`scripts/staticdata_backup_async.sh` step3.5b(upload-large-json)。
- 【lifecycle】用户 CF dashboard 实测 2026-10-05:老桶只有 backup/ 14 天一条(主控基准更新转达)。
- 【文档佐证】docs/ops/r2-backup-bucket-capacity-20261002.md(mac-backups 10-02 已删净/免费额度口径/large-json flat 唯一副本);docs/ops/r2-mac-backups-restore-20261002.md(86 散文件取回删除 PASS);docs/ops/r2-retention-effective-20261004.md(14 天生效时点 10-04 21:00 首跑);docs/ops/r2-billing-4usd50-followup-20261002.md(9 月 Class A 超限归因)。
