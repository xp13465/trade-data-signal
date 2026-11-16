# RCA:2026-11-16 晚三起真实失败(只读排查,2026-11-17 01:10 完稿)

> 落地来源: /tmp/rca-backup-nav-20261116.md; 落地时间 2026-11-17

> 无残留后台任务(本次未出现 `moved to the background`)。
> 云上全程只读:未 restart/未改 timer/未写 D1 R2/未跑生产脚本/未手工补数据;token 未 echo。

## 0. 结论速览

| 序 | 事项 | 一句话根因 | 当前状态 | 用户可见? | 严重度 |
|---|---|---|---|---|---|
| 1 | NAV 上传 30 份失败(21:44) | 条件 PUT 设计上**只发一次**(`scripts/upload_r2.py:787-792`),跨境链拥塞时一次 TLS 断连/超时即判死;30 份 = 15 份主对象 `write unconfirmed HTTP 0`(r2_safe_write.py:436-458)+ 15 份备份桶旧版 PUT 未落地导致读回 `backup readback SHA256 mismatch`(r2_safe_write.py:237-248) | 15 unknown 已自愈;8 份被他链补传确认;剩 7 桶仍 preparing(R2 内容滞后 1 天) | 是,7/256 桶净值弹窗滞后 | 中(仍在途残留) |
| 2 | 21:00 成套捕获 inconsistent | 一致性判据是"捕获窗口内**零变更**"(`scripts/backup_state_capture.py:549-557`),重试 2 次且**间隔 0s**(:643-665),而捕获集合本身包含活跃写入的发布状态目录(:106-145, `.r2-protected`/`ops_delivery`/`.r2_*_state.json`);两轮各 ~16s 都在 finalize 判死 → `inconsistent`(:674-680) | 无集合、源数据未动、备用机清单跳过;今晚仍会 21:00 再试(可能复现) | 否(但备份完整性承诺今晚落空) | 中高(功能性失败+复发风险) |
| 3 | overfit-monitor 21:47 exit 1 | 发布层 `overfit_monitor.py` 对主/ext 两个大文件做备份桶读回校验失败(`overfit_monitor_launchd.log:157-158` `backup readback SHA256 mismatch`),`rc≠75` 直接 break 不重试(:2249-2263),主脚本按发布未完成返回 1(`scripts/overfit_monitor.sh:63,123`) | **已自愈**:两份文件 11-17 00:02:21/26 被 r2_upload_async 链补传并 confirmed | 曾滞后 ~2h22m,现已正常 | 低(已恢复) |

严重度排序:**① NAV(仍有用户可见残留)> ② 捕获(无残留但承诺缺口+今晚复现风险)> ③ overfit(已自愈)**。
附带发现(任务书外、但同晚真实发生):`upload-db` 的 **public_fund.db 上 R2 失败**(3 次 SSLEOF 重试耗尽,backup_db_20261116_2100.log:292/320/356/376/383),导致 `verify_backup.sh` 因 `receipt.complete=false` 判 rc=1(:437-450;实际恢复性检查全部 OK,仅上传凭证不完整)。

---

## A. 21:00 成套备份捕获失败

### A1. 证据链
日志:`/home/ubuntu/code/trade-data/data/logs/backup_db_20261116_2100.log`
- 第 1 行 `=== backup_db.sh 开始 2026-11-16 21:00:00 ===`
- 第 9 行 C4 回执 JSON(`evaluated_at=2026-11-16T13:00:05.024653+00:00` = 21:00:05.024 本地,`receipt.status=written`)
- 第 16-18 行:
  - `-> 状态集成套捕获(backup_state_capture.py) ...`
  - `{"status": "inconsistent", "complete": false, "set_dir": null, "duration_seconds": 32.06}`
  - `状态集捕获 rc=1 (0=产出可上传集合, missing 如实记录)`
- 第 386 行:`⚠ 备用机同步清单跳过(缺捕获集合或本轮 receipt; 原备份退出码不变)`
- 第 451 行:`=== backup_db.sh 结束 2026-11-16 22:49:20 退出码=0 ===`

对照(正常态):`data/backups/state-capture-sets/20261115_2100-6bf1b0e9/manifest.json` = `complete:true / retries:0 / duration 16.95s / files 1491`(11-15 22:29 静默窗口人工试跑)。
本次目录列表只有 11-15 一份集合(`data/backups/state-capture-sets/` 下无 11-16 目录)。
**32.06s ≈ 2 × 16.0s**:两轮都完整扫完 1491 个文件、在收尾复查阶段判死,符合代码"2 次尝试、无 sleep"。

### A2. 根因
触发判据在 `scripts/backup_state_capture.py`:
- `_capture_attempt` 收尾复查:549-557 行逐文件 `stat_identity(src) != rec["source_stat"] or sha256_file(src) != rec["sha256"]` → `raise SourceChanged(rec["rel"])`;554-555 行把"读后文件消失(FileNotFoundError)"也按"被修改"处理。
- `capture()`:643-680 行 `for attempt in range(2)` **无退避/无 sleep**;两次都不一致 → 674-680 行返回 `{"uploadable": False, "set_dir": None}`、`reason=sidecar_changed_across_capture_after_one_retry`。
- 捕获集合面:106-145 行 `DECLARED_INVENTORY` 含 `(".r2_*_state.json")`、`ops_delivery`(dir)、`.r2-protected`(dir)、`alerts`(dir)、`logs/r2-db-source-*.json`;`expand_inventory` 383-415 行 `root.rglob("*")`,**未排除临时文件/隐藏临时名**。
- 失败输出**只打状态不打文件名**:926-928 行只输出 `{"status","complete","set_dir","duration_seconds"}`——这是本次无法逐位定位"哪个文件变了"的直接原因(观测缺陷)。

"哪个文件在采样时变化"——实测取证:
- 窗口 = 21:00:05→21:00:37(两轮各约 16s)。
- 在 `ops_delivery / alerts / .r2-protected` 三处按 mtime 找 21:00:00–21:00:40 的改动,**唯一命中** = C4 回执 `ops_delivery/receipts/unknown/backup_isolated_restore/fb5ef1f8….json`,mtime `21:00:05.027660980`(1192B)。它是 C4 阶段(21:00:05.024)刚写完、捕获随后才开始,读时已静止,理论上不构成变更。
- `.r2-protected` 在窗口内 **0 个文件被创建/修改**(`find . -newermt ...` COUNT=0),排除"上传 journal 在窗口内落盘"。
- `.r2_*_state.json`(20 个)在窗口内是否被写:**无法回溯**——这些文件之后被 23:xx/00:xx 的运行覆盖 mtime;而 C4 回执之外没有留存痕迹。
- 结论(如实标注):**本轮无法逐位证明是哪个 rel**。两种符合"两轮都失败"的机制:①某上传通道恰在 21:00–21:00:37 内收尾写 `.r2_*_state.json`(被后续运行覆盖 mtime,取证丢失);②每轮扫描时存在的临时文件(`.receipt-*` 等)在 finalize 时已消失 → 554-555 行判"被修改"。C4 自身确实在捕获目录里制造临时文件:`scripts/delivery_evidence.py:242` `mkstemp(prefix=".receipt-")` → `:249 os.link` → `:268 temp.unlink(missing_ok=True)`,且 `rglob("*")` 不排除它。
- 结构层面确凿:捕获集合**包含高频写入面**,且判据要求"整个 16s 窗口零字节变化",重试间隔 0s;本次首次进入 21:00 正式槽位,同槽位有 20:21 起的长链上传在跑(`r2_upload_async_20261116_202111.log`,backup_db 域锁被 `upload-db` 持有 5892s 直至 22:38)。11-15 成功那一份是 22:29 静默窗口跑的,恰好没有并发写。

### A3. 一致性捕获设计(为什么没等到一致窗口)
- 参与文件:38 项恢复清单经 `DECLARED_INVENTORY` 展开(含 glob/dir),声明排除 `payloads/`(1.21GB)等;`read_stable` 对每个文件做"读前 stat → read_bytes → 读后 stat",变化即 `SourceChanged`(:296-308);收尾再做全局 stat+sha256 复查(:549-557)。
- "集合一致"定义 = 从第一次 stat 到 finalize 复查之间,**无任何成员内容/身份变化**。
- 没等到窗口的原因:不是"超时不够",而是 ①重试只有 2 次且**零等待**,两次落在同一繁忙区间;②判据粒度是"零变更",对任何一次后台状态落盘都不可容忍;③捕获面包含活跃目录,与"备份链自己在 21:00 起大规模上传"天然冲突。

### A4. 影响面
- 今晚没有可上传集合:无 `backup/state_*.tar.gz` 归档、无备用机 manifest 更新(backup_db.sh:189-198 因 `CAPTURE_SET_DIR` 空而跳过),但**源数据全部在,零丢失**;本地三库热备成功(local_rc=0)。
- 会不会自己恢复:明天 21:00 定时会再跑一次;若并发写入面不变,**可能再次复现**(同判据、同槽位、同零退避)。恢复承诺需要等一次成功集合。
- 附带:`upload-db` 的 public_fund.db 今晚未进 R2(:376/383),R2 少一档 11-16 的 public_fund 恢复点(14 天保留期内其余 13 天仍可回退)。

### A5. 修复方向(各带可观测预期 / 证据用例 / 风险)
**方案 A1(推荐,结构性):排除临时面 + 双扫描稳定窗口 + offender 可见**
- 改哪个环节:`backup_state_capture.py` 的 `expand_inventory`(排除 `.receipt-*`/`*.tmp`/`*.lock`/`gc-manifest.json`,并写进 `declared_excludes`)、`_capture_attempt`(一致性判定改为"两次全量扫描 rel+stat 身份一致,间隔≥2s",失败时把差异 rel 列表记入 `result.reason.changed_rel`)、`capture`(重试间隔 5s/15s,总预算 ≤90s)、`main`(926-928 行输出 offender)。
- 可观测预期:同样有并发写入时,①要么 `status=consistent`(第二次扫描窗口内无变化);②要么 stdout 出现 `changed_rel:["…"]` 具体文件名,**不再出现无 detail 的 inconsistent**;静默窗口回放 `retries=0`。
- 证据用例:①fixture 在捕获期每 2s `touch data/.r2_fake_state.json` → 断言输出含该 rel;停写后重跑 → consistent;②生产回放:同一 inventory 在 23:30 静默窗口跑,`files≈1491`、`retries=0`、耗时 ≤30s;③明天 21:00 真实槽位若再失败,日志必须点名文件(可复核)。
- 风险:排除清单若误伤真正要恢复的状态文件 → 需在 manifest 声明排除里逐项写明,并由 reviewer 对照 docs/backup-restore.md;耗时从 ~17s 变 ~35-40s(预算 12600s 内无压力)。

**方案 A2(互补,与写入者错峰):捕获前拿 R2 全局锁 EX / 改时点**
- 改哪个环节:`backup_db.sh` 状态捕获段(131-159)先经 `with_lock` 取全局 `trade_r2_upload.lock` EX(与所有上传通道互斥),拿不到则本轮 `status=deferred`(不算失败)并跳过;或把捕获挪到 23:15 低峰。
- 可观测预期:捕获期间不可能有上传写状态文件 → 0 次 `SourceChanged`;日志出现 `deferred`(而非 inconsistent)。
- 证据用例:①人为在 21:00 起 `upload-fund-nav` 同时触发捕获 → 断言 `deferred`;②空闲窗口触发 → consistent 且 ≤25s。
- 风险:捕获占全局锁 20-60s 会推迟上传链(可能撞看门狗);与备份链自身 21:00 的大库上传冲突,需实测窗口。若只改时点(23:15),需核对 23:00 后安全窗口规范(§14)与次日 00:xx 的 update_all 时段。

---

## B. 21:44 NAV 上传 30 份失败

### B1. 30 份失败逐份清单与现状
运行:`fund_nav_upload_async_20261116_214427.log`;`[fund-nav] ✓ 上传完成 150/180, 耗时 3638.0s (较全量少传 76 个)`;`FAILED_FILES`(第 4021 行)共 30 个。

| # | key | 报错类型 | 当轮 retry | 现 journal 状态 | 补传证据 |
|---|---|---|---|---|---|
| 1-15(write unconfirmed) | 16,32,34,38,3a,4c,57,5b,6b,6f,72,7f,81,a3,e2 | `write unconfirmed HTTP 0; no fallback` | 0 | 全部 confirmed(retry_count=1) | 23:09-23:11 自愈 `recover-protected`(日志 4067-4078 / 4079 `{"confirmed":253,"preparing":8}`) |
| 16-30(readback mismatch) | 03,10,18,30,3c,4b,5d,5e | `backup readback SHA256 mismatch` | 0 | confirmed | 他链 run_id=5b736a4d 于 23:09:01-23:11:08 补传确认(journal mtime 逐条可查) |
| 同上 | 6d,71,84,89,8f,90,cf | `backup readback SHA256 mismatch` | 0 | **仍 preparing** | 无(等下一轮同通道上传) |

当前 journal 汇总:`{"confirmed":253, "preparing":8}`(8 = 上述 7 个 nav 桶 + `data/signal_kelly_day_snapshot.json`;另 1 个 state=None 的历史行)。

### B2. 根因(两个报错同一根因)
代码路径:
- `scripts/r2_safe_write.py:428-458` `commit()`:先落 `unknown`(:436-437)再发**条件 PUT**;网络异常(`OSError`/`HTTPException`,含 SSLEOFError/超时)统一 `st=0`(:447-448);随后 `confirm()` 只做 2 次 GET(:250-264),需 sha256 + `x-amz-meta-write-id` 全匹配,否则 :457-458 `write unconfirmed HTTP {st}; no fallback`。
- `scripts/r2_safe_write.py:237-248` `immutable()`(备份旧版):条件 PUT 异常同样吞成 `st=0`(:242-243);然后 GET 备份对象,`404→None`(:221-226)→ :246-248 `backup readback SHA256 mismatch`。**备份键是内容寻址路径** `protected-versions/v1/<bucket>/<key>/<sha(old)>`,因此该报错的真实语义 = **"备份桶 PUT 没落地/读不到(404),读回为空"**,不是"读到一个内容不同的有效旧版"。
- `scripts/upload_r2.py:787-792`:凡带 `if-match/if-none-match` 的条件提交 `attempts = 1`(注释:交 write-id 确认层处理)——**TLS 断一次即失败,不重发**。
- 超时:云上 `.env` `R2_UPLOAD_HTTP_TIMEOUT=600`(已核对),单次 socket 可挂 600s。

实测量化(同日志 `R2_PHASE`):
- 主对象 `upload`(n=165):p50 **49.4s**、max **600.1s**(e2.json 正好打满 600s 超时)、合计 9754s。
- 备份旧版 `backup_write`(n=180):p50 **50.9s**、max **225.5s**、合计 10847s;`backup_readback` p50 6.7s;`old_read` p50 6.7s。
- 1-7 小时前基线(18:24 同通道)upload p50 ~16s ⇒ 今晚约 **3 倍劣化**。
- 拥塞来源:同晚并跑 backup_db 大库上传(public_fund 64MB 分片,`backup_db_20261116_2100.log:292/320/356` 连续 3 次 SSLEOF)、20:21 起的 `r2_upload_async` 长链(backup_db 域锁被 upload-db 占 5892s;verify-r2 等锁 ~96min 后失败)、21:40 overfit 发布(同款 backup readback 失败)。

时间/桶分布:30 份 `first_unresolved_at` 落在 21:41–22:34(UTC 13:41–14:34),散在全桶(03…e2),不集中单桶或单分钟 ⇒ **是链上随机抖动 + 拥塞放大,不是某桶代码缺陷**;但"条件提交只发一次"把随机抖动放大成确定性失败。

### B3. 自愈/残留
- 15 unknown:自愈链 `nav_journal_selfheal.py`(门控 :268-276)调用一次 `recover-protected`(auto),同 write-id 重放 + confirm 成功,retry_count=1,全部 confirmed(日志 4070-4078)。
- 8 个 readback 失败:被并发链(20:21 起的 r2_upload_async,run_id 5b736a4d)在 23:09-23:11 以相同内容重传确认——不是人工补,属"另一条上传链兜住"。
- 7 个 nav 桶 + 1 个 kelly 快照:auto 模式**设计上不碰 preparing**(`upload_r2.py:1389-1393`、selfheal 文档 :12/:38),留给下一轮同通道正常上传重建 journal 自愈;在此之前 R2 这 7 桶仍是前一交易日内容。

### B4. 修复方向
**方案 B1(推荐,语义保持的有界重放):区分"网络级未决"与"业务拒绝",同 write-id 有界重试**
- 改哪个环节:`r2_safe_write.py` `commit()` 在 `st=0` 且 `confirm()` 未过时,用**同一 write_id + 同一条件头**(若对象存在则 if-match 原 ETag)最多重放 2 次(2s/4s 退避,每次前先 confirm);`immutable()` 备份 PUT 同样重放(备份键内容寻址 + `if-none-match:*`,重发幂等;412 视为已存在再 GET 校验 sha)。这不改变"条件提交"语义(同 write-id 幂等),只把一次网络抖动从"判死"变为"确认后重放"。
- 可观测预期:同拥塞条件下 30 → 0-2 失败;journal 出现 `retry_count≥1` 的 confirmed,不再新增 failed;单通道总耗时 ≤4200s(3638s+重试余量)。
- 证据用例:①单测 monkeypatch `_put_bytes` 首调抛 `SSLEOFError`、次调成功 → 断言 row=confirmed 且 put 调用 2 次、write-id 相同;②连续两次抛错 → 断言 `UnsafeWrite` 且 journal 保留 preparing/unknown(可自愈);③受控窗口重跑 180 桶 → `FAILED_FILES` 为空、upload max <90s。
- 风险:重试会把拥塞放大(总字节翻倍);必须同时核"同 write-id 重放不产生第二份许可";若 R2 真故障,重试只是延后失败(需上限 2 次,禁止无限重试)。

**方案 B2(互补,治拥塞与超时放大):并发/超时/时点治理**
- 改哪个环节:`upload_r2.py` 引擎 8 worker(`:1653`)对备份桶 PUT 降到 4 或按字节自适应;`R2_UPLOAD_HTTP_TIMEOUT` 600→90-120s(失败快退,交给 B1 重放);把 fund-nav 上传与 21:00 backup_db 大库上传错峰(或让 fund-nav 在 upload-db 之后启动)。
- 可观测预期:nav 上传 p50 49.4s→≤20s、600s 级挂起消失;180 桶 0 失败;总时长不劣化(拥塞下降抵消并发下降)。
- 证据用例:在同一 21:00 大库上传并发窗口重跑 180 桶,统计 `R2_PHASE` p50/max 与 `FAILED_FILES`;对比本次基线数字(49.4s/600.1s/30)。
- 风险:降并发会拉长总时长(需估算窗口);缩短超时可能误杀大对象(>64MB 走 multipart 另算,需按体积区分)。

---

## C. overfit-monitor 21:47:09 exit 1

### C1. 日志原文与判据
`data/logs/overfit_monitor_launchd.log`(21:40 起):
- 第 106 行:`overfit 发布尝试 1/8，剩余总预算 960.0s`
- 第 140-142 行:备份旧版 `backup_write 43.92s` + `backup_readback 21.66s`(overfit_monitor.json 5.73MB)
- 第 152-156 行:ext(17.92MB)备份 `backup_write 236.74s` + `backup_readback 1.28s`
- 第 157-158 行:
  - `[1/2] ✗ overfit_monitor_ext.json 异常(UnsafeWrite: backup readback SHA256 mismatch)`
  - `[2/2] ✗ overfit_monitor.json 异常(UnsafeWrite: backup readback SHA256 mismatch)`
- 第 163 行:`✗ R2_UPLOAD_INCOMPLETE: stage=upload 1；产物保留，可 --publish-only 补传`
- 第 166-167 行:`✗ overfit 计算产物保留，发布未完成(rc=1)；用 --publish-only 补传` / `=== overfit_monitor.sh 结束 2026-11-16 21:47:09 退出码=1 ===`

判据行:`scripts/overfit_monitor.sh:63 RC=$?` → `:123 exit $RC`;发布层 `scripts/overfit_monitor.py:2249-2263` 只在 `rc==75`(锁占用)时重试,发布错误(rc=1) **直接 break**(`if rc != 75 or attempt == 8: break`),所以"1/8"只跑了 1 轮。

### C2. 一句话根因与分类
根因:跨境 R2 备份桶 PUT 在大文件上失败/读不回,`immutable()` 判 `backup readback SHA256 mismatch`,发布层按"发布未完成"返回 1——**外部依赖(网络/带宽)失败,与 B 同一根因族**,不是数据缺失、不是预算耗尽、不是代码 bug;放大点=失败后按设计不重试。
数据未就绪?否:计算结果完整(产物 5.73MB+17.92MB 已生成、parity 结构校验 PASS 于日志 116-132)。

### C3. 正常重试路径与当前状态
- 人工补传路径(脚本自带):`bash scripts/overfit_monitor.sh publish-only`(`:56-59`,不重算/不重发预警,只补传当前主/ext)。
- 实际结局:无需人工——11-17 00:02:21 / 00:02:26,journal 中 `data/overfit_monitor.json`、`data/overfit_monitor_ext.json` 已被 20:21 起的 r2_upload_async 链补传并 confirmed(内容为 11-16 21:40 生成版)。overfit 页面当晚滞后约 2h22m,现已正常。

---

## D. 严重度排序与动手时点

1. **NAV 上传(中,仍有残留)** — 用户可见:7/256 桶净值数据滞后一个交易日(弹窗走势图那几只基金显示前一日净值)。已在 22:45 真发告警。**时点:明天白天**(11-17 16:10-17:40 窗口,或顺其自然等 17:50/18:24 上传链自动重传;若要立刻清残余,派 implementer/mech-runner 受控单跑 `upload_r2.py upload-fund-nav` 一次,只补 7 桶增量)。修复代码(B1+B2)可排入明天白天。
2. **成套捕获(中高,无残留但承诺缺口+复发风险)** — 今晚无集合、无数据丢失、源数据齐;备用机清单今晚缺席;明天 21:00 可能复现。**时点:明天白天改代码**(先补"打印 changed_rel"再谈验收,否则无法证明修好)。今晚不动。
3. **overfit-monitor(低)** — 已自愈(00:02),页面正常。**时点:可以排期**,与 B 同源修复一起做。
4. **附带:public_fund.db 的 R2 备份缺失(中)** — 明天 21:00 会自动重试;若不接受一天恢复点缺口,明天白天在静默窗口派一次受控 `upload_r2.py upload-db`(注意域锁 9000s 预算与 15:35/16:00/17:50 时点)。

## E. 已验证的现况数据与取证方法(供复核)
- 云上日志:`data/logs/backup_db_20261116_2100.log`、`data/logs/fund_nav_upload_async_20261116_214427.log`、`data/logs/overfit_monitor_launchd.log`、`data/logs/r2_upload_async_20261116_202111.log`。
- journal:`data/.r2-protected/*.json`(sha256(bucket/key) 命名),聚合 `{"confirmed":253,"preparing":8}`;30 个失败 key 的 state/mtime/run_id 已逐条核对(见 B1 表)。
- 一致性取证:`find data/{ops_delivery,alerts,.r2-protected} -newermt "2026-11-16 21:00:00" ! -newermt "2026-11-16 21:00:40"`;`.r2-protected` 窗口 0 命中。
- 代码:`backup_state_capture.py:106-145/296-308/383-415/549-557/643-680/926-928`;`r2_safe_write.py:221-226/237-248/250-264/428-458`;`upload_r2.py:787-792/1389-1393`;`overfit_monitor.py:2249-2271`;`overfit_monitor.sh:56-63/123`;`delivery_evidence.py:242/249/268`;`nav_journal_selfheal.py:12/38/268-276`。
- 云上 md5 核对:`backup_state_capture.py` 云上/本地一致(2a38d3a850a345c011a4746c47858c21,前序已核)。

## F. 诚实标注(未能证明/未覆盖)
- A 的**具体 offender 文件名无法逐位定位**(脚本不记 rel;`.r2_*_state.json` 的窗口内写入已被后续运行覆盖 mtime)。报告给出的是结构根因 + 两种可复现机制的取证组合,不是"猜一个文件名"。
- 8 个 readback 失败的"他链补传"run_id=5b736a4d,归因到 20:21 起的 r2_upload_async 链(其 pending context created_at 与 run_id 一致);该链日志未打印 nav_bucket 明细,故"具体哪条通道补传"只能到链路级,不能到通道级——同样是观测缺口。
- 未做任何云上写操作/未跑生产脚本/未重跑上传,所有结论基于日志与 journal 静态取证。
