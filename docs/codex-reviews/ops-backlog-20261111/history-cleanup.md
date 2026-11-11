# HC16 / HC19 / HC20 Evidence 执行记录

用户本轮全部待办实施授权及定向接管适用于本任务。工作树 `codex-ops-history-cleanup-20261111`，分支 `codex/ops-history-cleanup-20261111`，base `2346b6d621b254cdabc18225a3f98372a41980fd`。Fund `f26fa19b1d291b3e4048985db2f216821ee1e2e6` 冻结未改。

结果：HC19 已精确隔离三个测试块；HC20 已实际删除三个符合条件的旧 Codex 树；HC16 完成新增有界追溯，七个 T0 原件仍缺证据，未补造数据。

机器结果见 [history-cleanup-result.json](history-cleanup-result.json)，逐树保留/删除理由见 [history-cleanup-inventory.json](history-cleanup-inventory.json)。本任务仅新增 `history-cleanup*` 文档/工具/测试；不改主控协调文档、pending-index 或业务源码。

## HC16：原件仍缺，不能按补采完成结案

精确缺键：

```text
20261104|csi_000102|buy
20261104|csi_000330|buy
20261104|csi_000673|buy
20261104|gz_399395|buy
20261104|thsc_307940|buy
20261104|thsc_309049|buy
20261105|dax|buy_special
```

继承 `/tmp/codex-reports/ops-closeout-20261111/history_inventory.{py,json}` 和父任务 `history/local-originals.json`，新增两类只读追溯：

| 范围 | 本轮读取 | 结果与边界 |
|---|---:|---|
| 本机 audit/private archives 与冻结相关候选 | 180,123,348 bytes | 296 候选中按上限处理前 200；含 fixture/诊断，不能作为原件 |
| 云端 data/code/staticdata/backups 路径 | 18,766,978 bytes | 207 候选中前 200；当前及 pre-deploy freeze 哈希与前证据一致 |
| 本机日期索引、两份完整 manifest、manifest 指向的候选 | 13 文件，1,086,620 bytes | 无精确键记录；归档索引中的 orphan_state / exact-matches 文件不是 T0 原件 |
| 云端日期索引 | 12 文件，1,186,583 bytes | 无精确键记录；未下载大归档 |

每个新采样文件记录 SHA-256、文件 mtime、采样时间；JSON 内嵌源时间单独记录。无内嵌时间时明确为空，不能把 mtime、归档创建时间或本次采样时间当 T0。tar 记录 archive hash 和 member 原始 mtime，只读列表/选定成员，不解压到来源目录。

归档读取上限为单 archive 160 MiB、单成员 16 MiB、成员遍历 3,000 个/64 MiB logical；`alert-recheck-evidence.tar.gz`、`fastcheck-evidence.tar.gz` 因 logical cap 未完整遍历。额外完整读取两份 manifest，按 freeze/frozen/日期筛查成员，但不声称 tar 与 manifest 已全量重新对账。`runtime-core.tar` 列表完成，无相关原件。

日期遍历限深度 4、30,000 路径、80 候选、32 MiB。定向 Git 历史查 11 月 3–7 日最多 40 个相关提交，本机代码库和云 staticdata 无结果；云 `trade-data` 并非 Git 仓库，原始 exit 128 已保存。staticdata 浅历史和未覆盖候选意味着本结果不能证明所有历史原件都不存在。

没有使用当前评级替代 T0，没有重造历史、修改生产或把缺键诊断的文本命中当完整记录。后续只有拿到可核验的原始快照/旧归档才可解除这七个缺口。

## HC19：实际隔离，原 ledger 保留

目标 `agent-ae637b217439bb921`，固定 HEAD `61a56ce7fc037e0a9f8ce8aad018ee1c173edd95`。前后检查 tracked 状态干净；无 worktree lock、cwd 或打开句柄。初查、dry-run、备份后及写前分别校验，源 hash 稳定。

`latest.md` 三块身份由完整文件固定 hash 加 `2026-11-10 09:18:09` / `h_existing` / `h_new` 来源确认；来源是 `scripts/tests/test_f03r1_digest_atomic_write.py`。未按一般关键词删除告警。

- before：`c18fc064357244910150efb080304fb08f32117d48b00d7a4c0356403f6b3683`
- after：`333b7dc63ba9109e60d718b575f31ea4a1af8b1e007ec95e12331f8651c7ccd8`
- 原文 1,878 bytes → 保留前言 312 bytes；权限仍为 `0644`。该固定原文没有真实 severe 块；追加 severe 的负控会拒绝整个操作，保持原文。
- 原 `suppression_ledger.jsonl`（5,250 bytes）hash 保持 `4559e6a15da8a34327243940193a4fa1306d6ae7434066a7b0f38ce307d4ee44`，另两份原 lock/prune 文件保持。
- 目标树原本没有 `alert_ledger.jsonl`，没有伪造或初始化它。
- 与镜像写者共用 `.latest.lock`，本次创建了这一空协调锁文件；未调用 notify。锁内再次 CAS，再原子替换 `latest.md`。

四份原文件先完整归档，并实际恢复核对内容/hash、权限；成功后才改源。删除的三块原文另存 `removed-blocks.md`。复查时又从同一 tar 独立恢复一份，包括纳秒 mtime 的全 manifest 相等；两份恢复目录均保留。

备份：`/Users/linhuichen/.local/share/trade-audit/20261111/ops-backlog-cleanup/agent-ae637b217439bb921/`。payload SHA-256：`d04bc5f2988865cacf7ca5433ed1bc5163945af402bc2c886a4930bf301e19e2`。

## HC20：实际移除三树，保留 refs

选择依据同时包含 Codex 分支归属、先前完成记录、HEAD 已在 main、clean、无 lock/打开句柄/cwd、无正式交接 packet 引用；不单凭祖先关系删除。完成记录来自 `continued-implementation-20261109.md` 与 `ops-alert-recovery-20261110/verification.json`，其路径/hash 已写入结果。

| 已移除工作树 | 保留的 HEAD | 备份 entries / ignored bytes | 移除逻辑 bytes / allocated bytes |
|---|---|---:|---:|
| codex-fof-nav-completeness-20261109 | b1f20bca27d96db15a07230f7bed0d9e0f7d6f9e | 205 / 6,532,184 | 156,988,306 / 162,897,920 |
| codex-fund-index-reconnect-20261109 | e30d1c90a9482e754b802be202e9cd7d59b9875a | 206 / 6,505,922 | 156,953,534 / 162,865,152 |
| codex-ops-fund-budget-20261110 | 01aa15a9bdfa54d95cccedffe2b9525ba99e02d3 | 195 / 6,322,724 | 157,221,752 / 163,160,064 |

实际工作树数 44 → 41。保留原 `codex/ops-fof-nav-completeness-20261109`、`codex/ops-fund-index-reconnect-20261109`、`codex/ops-fund-budget-20261110` refs，末次校验仍指向上表完整 HEAD。

普通 untracked 为零，否则直接拒绝。ignored 文件、symlink、空目录完整归档并实际恢复，权限、hash、link target 逐项一致后，二次检查所有安全前提和 manifest，再执行不带 `--force` 的 `git worktree remove`。Git 正常删除成功，无须人工 unlink ignored，更没有广义 rm。随后另做全 metadata 恢复校验，纳秒 mtime 也相同。

三树合计逻辑 471,163,592 bytes、按 `st_blocks` 汇总 allocated 488,923,136 bytes（含目录元数据）。这是移除前逐路径统计，不是 APFS 的精确净空间变化；备份、两份恢复副本和审计文件约 59,064,701 regular-file bytes 保留，不把它算作净释放。

所有 Claude 命名树、reviewer、本轮实现/integration/本树、Fund 冻结树、dirty freeze、public final 交接树均保留。其他旧树未完成归属/占用核实，也保留。逐树理由和实际删除标记在 inventory；没有把计划记为完成。主树 main 可由 Claude 发布移动，本任务未写主树或 main。

## 验证与复核入口

默认 dry-run 的执行工具：[history-cleanup.py](history-cleanup.py)。只读追溯：[history-cleanup-scan.py](history-cleanup-scan.py)、[history-cleanup-date-index.py](history-cleanup-date-index.py)。隔离测试：[history-cleanup-test.py](history-cleanup-test.py)，内置 100 秒总时限，各外部命令有单独 timeout。

真实操作之前：`Ran 33 tests in 1.877s` / `OK`。初次 33 项中 4 个错误是临时测试 repo 的 macOS `/var` 与 Git canonical `/private/var` 路径不一致；原始失败日志保留，仅修测试路径并加强特定拒绝原因断言，未放宽生产 guard。

最终原始末行：

```text
Ran 38 tests in 3.028s

OK
```

涵盖真实临时 Git/文件恢复、dry-run 零写、错误 hash/时间/真实严重块拒绝、ledger/CAS 变化、恢复损坏/缺成员/穿越/symlink 父路径、纳秒时间、锁/dirty/untracked/未合并/未知 owner/交接引用拒删、真实打开 writer/cwd 拦截、超时回收进程、重复执行拒绝及 manifest/日期索引负控。全部使用临时根；没有业务 collector、真实 DB、外发或新子 agent。

证据根 `/tmp/codex-reports/ops-backlog-20261111/history-cleanup/`：`tests-initial.log`、`tests-second.log`、`tests-final.log`、四份 dry-run/apply JSON、`full-restore-verification.json`、只读追溯与 inventory；结果中包含证据 hash 清单。

私有 archive 根 `/Users/linhuichen/.local/share/trade-audit/20261111/ops-backlog-cleanup/` 为每目标独立目录。恢复输入为 `payload.tar` + `manifest.json`；`restore_archive()` 只接受空目标目录，拒绝穿越/类型/内容不符。tracked 内容由保留 refs 可恢复。未修改原交接 packet、未 ACK、未通知、未合 main 或部署。父任务负责集成及最终 Claude 复核。
