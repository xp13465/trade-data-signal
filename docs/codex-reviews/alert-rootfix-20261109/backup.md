# 备份恢复跨时点比较根因修复（供 Claude 独立审合）

本次由用户明确授权 Codex 业务实现，Claude 审核、合并、部署。仅在隔离 worktree
`/Users/linhuichen/code/trade/.claude/worktrees/codex-alert-backup-20261109`、分支
`codex/alert-backup-20261109` 工作；base `adfd77e7ad3a25033bf7ca02df85e0f459446e71`。
不 push，不部署，不运行生产 backup/restore/R2 写入，不修改 notify/pending-index/main。

用户原话：“为了确认可以修好。修之前分析一下真正原因和找出可以修好的依据。再开始修。我去睡了。醒来看你修好了多少个”。

## 实施前三验

1. 问题真实：读取 `/tmp/codex-reports/alert-rootfix-20261109/ancillary-root-cause-v2.json`
   及 `ancillary-evidence/historical-verify-logs.json` 中 Nov3/4/5 完整晚间日志。
   integrity 均 ok，signal_daily 分别 72108/71992、72139/72032、72171/72058，
   唯一这项 `backup > live` 导致 rc1；非周日 public_fund SKIP 不是失败根因。
   使用真实临时 SQLite 独立执行 base checker，三组全部重现 `VERIFY_OK=0`。
2. 根因锚点：`verify_backup.sh` 把备份与后来已变化的 live 比较，直接解释为丢数据；
   `app/compute/signals.py` store() 全量 DELETE+INSERT，历史审计记录 Nov3 净减少 116。
   Nov4/5 历史净变化与总差有余量，未逐键复原，不能认定所有减少都合法。
   e6f1c421c 仅补失败邮件明细，未修判据。
3. 机制可达：真实上传链并不消费 `data/backups/*2100.db`。三个小库原为 live
   `read_bytes()` 再 gzip，甚至没有 WAL-safe capture；public_fund 才使用在线 backup。
   旧 `.r2_db_backup_state.json` 只有 stat/key/date/gz_size，不是同源证明。
   现有 SQLite backup、流式 gzip、Range GET 及签名 extra_headers 可复用。
   改动前确认旧返回合同：snapshot 返回 int、PF 返回 True/False/None、upload-db CLI RC 不变。

## 新合同与信任边界

`backup_db.sh` 每轮生成 UUID 和独立日志目录 receipt 路径，通过
`R2_DB_BACKUP_RUN_ID` / `R2_DB_BACKUP_PROOF` 传给原来的 upload-db 调用。
上传进程持有自己生成的独立 SQLite 快照时采集 raw SHA256/size、现有关键表计数；
压缩关闭后采集 gzip SHA256/size。来源 entry 包含 run/name/bucket/精确 key。
PUT 或 multipart initiate 将 entry 的规范化 SHA256 与 run 写入两个 S3 metadata 字段。
本地 receipt 原子写，只有命令完成且所有必需上传成功才标 complete=true。

verify 显式消费 `VERIFY_BACKUP_RUN_ID` / `VERIFY_BACKUP_SOURCE_PROOF`，锁定该 entry 的
精确对象，不 LIST 后选择另一轮。HEAD 必须匹配远端 run/entry digest/长度；随后复用既有
6 线程 Range downloader，验证整个 gzip 哈希、限长解压、raw 哈希、integrity 与来源表计数；
结束再次 HEAD，身份/ETag 变化失败。恢复成功标记只落本次临时目录。
本地 receipt 仅用于选择；其字段被改会与远端 metadata digest 不符，不能靠本地台账假绿。
ETag 只用于观察变化，不当作 multipart 内容 MD5。

`verify_backup.sh` 自身保持验证器，完全没有上传/刷新动作。是否要求 public_fund fresh
same-run 上传只由 `backup_db.sh` 沿用现有 `VERIFY_BACKUP_SKIP` 与 `VERIFY_PUBLIC_FUND`
日/周门控决定，传入 `R2_DB_BACKUP_REQUIRE_PUBLIC_FUND=1`。普通非演练日保留旧 PF stat+HEAD
skip；周日/显式演练即使 stat 未变，也重新采集并上传原有 daily key，不增加任务或新 R2 key。
跳过上传而没有 PF entry 的 receipt 不可用来声称 PF 同源恢复成功。

### 新旧调用和 standalone 行为

- 原 `upload-db` 无两个新 env：CLI/返回码和 key/分层/锁保持兼容，小库也改用 WAL-safe
  SQLite 快照；不生成来源证明、不声称可用于同源 PASS。一个 env 缺另一个直接失败。
- `backup_db.sh` 正常调用：上传和校验使用同一显式 run/receipt；local_rc、upload_rc、verify_rc
  分开记录；parent RC 仍只由本地备份决定，上传/verify 失败沿原独立告警路径。
- standalone verify 无 receipt/run：保留旧只读下载、完整性/行数/新鲜度诊断，最终
  **unknown/not_verified + rc1**。有本地台账或 integrity=ok 也不能 PASS，不自动发现“最新”receipt。
- 有显式来源但缺文件、错 run、不完整上传、对象覆盖、metadata/任一哈希不符：失败/unknown + rc1，
  不回落到旧下载或另一轮。历史 Nov3/4/5 没有来源证明，仍不能在新规则下追认 PASS。
- 使用既有成功 receipt 手动验证时，必须显式给出 run 与路径；PF receipt 缺该库则 PF 不能 PASS。
  本次不运行真实手动验证；默认 `bash verify_backup.sh` 的保守失败是刻意改变的契约。

同源恢复成立后，只有 sentiment.signal_daily 的非空 live 行数变化作为
`VERIFY_LIVE_DRIFT_JSON` / `live_drift` 单列，指向 `history_overwrite_audit`，不会直接称为恢复失败
或丢数据，也不认证其业务合法性。已有历史审计/孤儿链没有修改。live 缺表、空表、读取损坏
仍失败；其它库表原来的计数下限、备份大于 live、PF 0.95、新鲜度检查保留。
所有参与同源验证的库都检查日期为今天或昨天；未来日期拒绝。

## 初始 28 处回归失败分类（不以实现反推预期）

基线断言来自 `test_pfdb_r2_backup_20261025.py`、`test_255_backup_drill_20261028.py`、
`test_345_backup_followups_20261029.py`、`test_codex_alert_context_20261106.py`。
初跑原始输出 `/tmp/alert-backup-initial-targeted.log`：`28 failed, 83 passed in 26.46s`。

| 类别 | 数量 | 依据及处理 |
|---|---:|---|
| 无上传来源证明却期待 PASS/不告警 | 20 | 用户明确要求缺证明不能假绿。旧 Drill 只替身下载，没有任何来源绑定。保留各 gate/ratio/freshness/ledger 诊断断言；最终改验 rc1+unknown。包括 stock SKIP/date、PF 空间/门限/日周/关闭、ratio 内及边界、ledger 匹配/异日、结论/freshness、sandbox、C1 五种门限、skip-only。有效来源下的 PASS/健康周频 SKIP 由新完整链路验证。 |
| SQLite 页字节与 live 主文件相等 | 1 | 原 PF 测试中的小库比较 raw==live 文件字节；SQLite backup 可改变页/头布局。改成恢复后 schema+全部行 iterdump 相等；新增真实 WAL 提交+上传时 live 变化测试，验证内容，另用来源 raw SHA256 验精确上传字节。 |
| 旧错误措辞“本地丢数据” | 4 | 一个 stock count 用例和三种 corrupt-side 诊断仍验 rc1/实际库表/异常路径；只改为“跨时点行数减少，待审计核对”。用户明确禁止由跨时点计数直接断言丢数据。 |
| 源码形状守卫 | 2 | stock 原字面 download-db 已封装为 download_one，改守卫到真实 wrapper；另一条禁止无条件 sys.path.insert 的原断言保留，通过限定 importlib 加载新 helper 修实现，没有删除守卫。 |
| stock 日期闸变异的最终 rc 判别 | 1 | 全局缺来源本来就失败，删除日期闸不再能用总 rc 区分。改为断言变异明确产生 stock SKIP 且缺少 stock 专属 FAIL；倒置闸、删除存在性闸也逐项验证具体诊断。负例没有删除，不让无关 unknown 掩盖变异判别力。 |

新测试用真实 SQLite 与临时目录文件 S3 替身执行真实 upload-db → 新进程 verify shell →
既有 Range downloader；禁用周/月副本与远端 prune，notify 只写临时参数，无真实网络/外发。
覆盖来源完全一致+live -116、WAL、实际另一轮同 key 覆盖（含相同内容）、中途覆盖、
截断、同长位改、有效 SQLite 同长同计数内容改动、错对象/错 run/receipt 改动/缺证明/
上传部分失败、缺表/空表/损坏、live 缺失/空表/其它表减少、周频 SKIP 和 parent RC 三分离。

## 磁盘、流式与 #373 边界

- PF capture 仍只有原先一份临时 raw+gzip，沿用原磁盘预检，不新增一份完整 DB；hash/
  计数只读同一文件。没有自动清理历史台账、日志、备份或数据库；原本的本地保留逻辑未改。
- 新小库 capture 的额外磁盘峰值是一份 raw+gzip。新增预检读取 SQLite page_count*page_size
  （包含已提交 WAL 的页），要求 2.01×raw+64MiB 余量，不足时在上传前保守失败。
  不是对 #373 生产余量做乐观承诺；并发写入/其它进程占盘仍可能失败，原失败告警保留。
- 恢复端按受远端 metadata 绑定的 raw+gzip 大小加 64MiB 预检，之后才预分配 Range 文件；
  限长解压防超出来源尺寸；本次 gzip 验完即删除，避免三个小库 gzip 叠加常驻到脚本退出。
  PF 外层原有空间门仍在。只删除本次生成的临时文件，失败临时目录沿既有 trap 清理。
- hash/gzip copy chunk 为 4MiB，PF/恢复仍复用 Range 默认 32MiB×6 线程，不用整库内存；
  小库 PUT 仍需要压缩 payload 常驻，但已不把 raw 整库同时读入内存。
- 新 receipt 只有库身份/指纹/计数（几 KiB），无 SQL 值/凭证，mode 0600 原子写。
  其本地留存随日志管理，本次不新增定时器或历史清理器。
- 真实随机 BLOB 小样、磁盘不足禁止上传/禁止 Range 分配、历史 sentinel 不变的测试结果见下方。
  这只验证小样与有界 IO 行为，未运行 GB 级容量/耗时测试，不能外推生产可用空间。

## 复用与代码体量

新增一个双端共享 helper 是必要连接点：上传与校验共用表清单、fingerprint、entry digest、
原子 JSON、同源检查；不是远端 manifest 服务，也不新建 R2 manifest 对象。
复用 `_sqlite_snapshot_to_gz`（扩展到小库）、`_upload_file_to_key`/multipart（仅可选 metadata）、
`restore_r2_db_backup.download`（6 线程 Range）、原通知出口、分域锁、日/周/月 key 及保留逻辑。
既有 API 返回形态不变；新增参数均可选，未传时不向旧调用/替身额外传 kwargs。
生产代码净增 300 行：caller +14、upload +47、verify +66、共享 helper +173；
测试净增 431 行（405 行独立离线链路/反例 + 26 行旧合同断言调整）。体量主要用于双端
身份验证、保守失败和离线反例；没有引入第三方依赖或通用状态机。新增 helper 中的
流式哈希/原子写/共享表清单由上传与恢复两端使用，Range 下载器原实现零复制。

官方接口依据：[R2 S3 API compatibility](https://developers.cloudflare.com/r2/api/s3/api/)、
[R2 metadata extensions](https://developers.cloudflare.com/r2/api/s3/extensions/)、
[R2 consistency](https://developers.cloudflare.com/r2/reference/consistency/)。S3 metadata 使用
`x-amz-meta-*`，请求经现有 SigV4 签名。未假设 ETag 为 multipart MD5、未假设对象版本功能。

## 验证与交付

定向回归命令（解释器 `/Users/linhuichen/code/trade/.venv/bin/python`）：

```sh
python -m pytest -q scripts/tests/test_backup_source_proof_20261109.py scripts/tests/test_pfdb_r2_backup_20261025.py scripts/tests/test_367_r2chain_upload_robustness_20261101.py scripts/tests/test_255_backup_drill_20261028.py scripts/tests/test_345_backup_followups_20261029.py scripts/tests/test_366_restore_r2_db_backup_units_20261101.py scripts/tests/test_codex_alert_context_20261106.py scripts/tests/test_283_weekly_copy_object_20261027.py scripts/tests/test_253_disk_reclaim_20261028.py scripts/tests/test_importpath_p0_20261029.py
```

原始末行：`183 passed in 41.50s`，rc0；原始完整输出
`/tmp/alert-backup-final-targeted.log`。其后只增强新旧测试的断言（unknown 必须为唯一失败，
receipt <16KiB 且 mode0600），定向重验原始末行 `86 passed in 37.80s`，rc0，
见 `/tmp/alert-backup-contract-final.log`。进一步在 verify 进程的文件 S3 替身禁止所有非 GET/HEAD
请求，确认 verifier 无写入路径；原始末行 `36 passed in 15.58s`，rc0，
见 `/tmp/alert-backup-readonly-final.log`。
真实资源小样原始行：
`RESOURCE_SAMPLE={"gzip": 5259443, "peak_raw_plus_gzip": 10584243, "raw": 5324800}`，
见 `/tmp/alert-backup-new-final.log`（该轮 36 passed in 15.37s）。
`bash -n` 两脚本、`py_compile` 新 helper/upload/新测试、`git diff --check` 均通过。
未执行全量 pytest、任何生产 SSH/backup/restore/R2 写、GB 级压测或真实外发。

交付文件：`scripts/backup_db.sh`、`scripts/verify_backup.sh`、`scripts/upload_r2.py`、
`scripts/backup_source_proof.py`、`scripts/tests/test_backup_source_proof_20261109.py`、
四份相关旧测试（PF/255/345/codex_alert_context），以及本文件。仅这些文件提交到指定分支，
作者 Codex；不 push。提交 head 在最终回传提供（不把尚未存在的 commit 写入自身）。
边界七轴：输入域（缺/坏证明与坏库已测）；状态组合（部分失败/缺 entry 已测）；
时序（WAL/live 改写/跨轮覆盖/中途覆盖已测）；上下游（真实 uploader+shell+Range 已测）；
极端值（空/缺/同长篡改/磁盘不足已测）；回退（无来源拒绝绿、PF SKIP 已测）；
并发与重入（实际同 key 换轮、中途覆盖已测，真实生产并发与 GB 级压测未执行）。
不宣称已上线或历史误报已被追认修正；Claude 仍须独立审查、合并与择窗部署。


## BACKUP-P2-01 作者续修（父决定返修，5123632 外审已封存）

本追加以 `5123632bb743d039837d1af133eb78fadedb839a` 为修复基线，保留其独立报告
`/tmp/codex-reports/alert-rootfix-20261109/backup-independent-review.json` 和全部原日志。
实施前记录报告、manifest 证据、原作者日志 SHA256，见 `/tmp/alert-backup-p2-frozen-hashes.json`。
本节只修单库失败扩散及关联 proof 消费，不扩展容量策略、周期、锁或状态框架。

先运行封存 `corrupt_first_db` 反例及 base 对照，使用新 basetemp 和日志目录：
`/tmp/alert-backup-p2-20261109/red-corrupt-first.log`，原始结尾
`1 failed, 1 passed, 19 deselected in 0.10s`。坏 sentiment 的 DatabaseError 令上传对象为空，
receipt.complete=false；该红例证实 P2，不依赖作者自验结论。

修复点：

- 小库快照/压缩/PUT 的 OSError、ValueError、sqlite3.Error 在本库边界记录失败后继续，
  不发成功 entry、不增加 ok。PF 异常归为该目标 False；仍用原有 ok/total 最终 exit(1)。
  小库 receipt 原子写位于此异常边界之外，存储证明失败不能被伪装成本库成功；
  SystemExit/KeyboardInterrupt 不被局部捕获。
- `receipt.complete` 保持整轮状态：false 时上传总 RC 非零。helper 可选择此 run 的健康 entry，
  但该 entry 仍须通过原来的 run/name/bucket/key、远端 metadata、双层 SHA/size、integrity、
  非空关键表检查。没有 entry 的坏库不能借旧对象恢复；不完整或篡改的 entry 也不能通过。
- shell 绑定模式在单库下载/证明失败后继续其它库与原周期的 PF 演练；记录库名 FAIL 到
  既有 notes，checker 单列验证健康库，再独立用 complete=false 判本轮失败。即使所有
  entry 都健康、只是最终 complete 写入没成功，也不能整体 PASS。无 receipt 旧模式仍早退。
  原下载失败 severe 出口保留，已告警时不再重复发送末尾 severe，失败明细仍落完整报告。
- `backup_db.sh` 本轮零改动；local/upload/verify RC 合同、分域锁、日周门控均不变。
  不新增上传动作到 verify，不清理历史，不改此前容量预检。父保存的
  backup-capacity-readonly.json 是 df/stat 证据，不是 GB 级演练结论。

证明与测试：

- 新增四库分别坏库（含首个 sentiment）的真实 SQLite/文件 S3 测试：另三个健康对象均
  上传、各自恢复 entry 通过；坏库无 entry，本轮上传和 verify 都 rc1、complete=false。
  验证通知替身仅调用一次；gzip/来源完整性/PUT 异常也不得阻断后继目标。
- 新增 incomplete+全部健康 entries 的总失败反例、下一轮坏库不借上一轮同 key 对象、
  裸 upload-db 无 receipt 时仍保留健康库上传；修改两条旧“直接抛 SQLite/OSError”预期为
  CLI 汇总 SystemExit(1)，原坏库/空间不足/无不当上传断言保留。这是指定的逐库继续合同变化。
- 独立原测试有两处测试夹具不能直接接收此 CLI 合同：corrupt_first 只捕获 Exception，
  不含 SystemExit；WAL 空间测试原先要求全局 OSError+所有目标零调用，而新合同要求只阻止
  不足空间的库、允许其它健康库。封存文件零修改；新建
  `/tmp/alert-backup-p2-20261109/test_p2_independent_replay.py` 显式捕获并断言 SystemExit(1)，
  重用原 corrupt_first 的对象断言及独立 fixture，并对健康 PF/逐对象恢复加验；
  WAL 反例仍验原 page_count 空间判断，只将“零全局 PUT”收窄为“零 sentiment PUT”，同时
  要求 ETF/stock/PF 成功 entry。其余 19 项独立测试原样执行。
  原始末行 `21 passed, 2 deselected in 9.09s`，见 `independent-after.log`；这是
  19 个封存原测试+2 个显式适配重放，不冒充“封存 21 项原样全绿”，仍交同 reviewer 复验。
- 首轮扩大定向有 `16 failed, 176 passed in 52.21s`：作者改了一条日志 echo，使旧邮件测试
  的源码抽取锚点失效；恢复原 echo 即修复，未修改这 16 个旧断言。该失败日志
  `targeted.log` 保留，最终重跑结果见完成记录。

所有本轮新日志只写 `/tmp/alert-backup-p2-20261109/`。新 raw 测试末行、标准 precommit、
最终 head/clean 和固定证据哈希复核写入原子结果包
`/tmp/codex-reports/alert-rootfix-20261109/backup-p2-result.json`；不覆盖 512 报告。
本轮不运行生产 SSH/备份/恢复/真实 R2/真实通知，也不单独全量测试；父在独立复验后跑一次全量。

本轮最终定向原始末行：`193 passed in 53.66s`，rc0，见
`/tmp/alert-backup-p2-20261109/targeted-final.log`。仅语法/编译/diff 检查也通过；
`backup_db.sh` 与 5123632 逐字节相同，封存报告及原始证据/日志哈希复核无变化。
