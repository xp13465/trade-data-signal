# 2026-11-10 告警接管：第一版事实归档

本版归档审计事实与接管起点。**尚未全部根治**；三个确认 P2、历史缺口与运行验收仍须分别闭环。它不替代父整合的独立审查、测试或部署验收，也不把原审计的 `FAIL` 当成候选代码的发布否决。

## 单次授权与本分支范围

用户原话（私有授权文件第一行原样保存在 [authorization.txt](authorization.txt)）：

> 2026-11-10 用户授权：cc那边token用尽。我授权你现在接替claude 把工作做完。

本次文档派单另明确：“用户明确授权Codex本次接替Claude完成告警收尾。”这只是**本轮实现、独立审查、整合、部署的接管授权**；默认 Codex 只读外审角色不永久改变。本分支仅写 `TASKS.md` 当前会话接管段、`NOTES.md` 本轮事实段、pending-index 相关状态/新 P2 与此目录，不改业务源码或长期角色规范，只 commit，不 push/合 main。

文档基线：`41c567e6aabbfec13af0d310bcc08df59194fdbf`；分支 `codex/alert-takeover-docs-20261110`，worktree `/Users/linhuichen/code/trade/.claude/worktrees/codex-alert-takeover-docs-20261110`。本次按指定基线归档，未自行 rebase 到其它整合状态。

## 时间与版本界限

- 审计窗口：北京时间 **2026-11-04 00:00:00 至 2026-11-10 08:49:35**（含端点）；09:17 的版本快照是额外现状证据，不延长事件窗口。报告生成时间为 09:30:09。
- 审计版本快照：本地 main、origin/main、云 CODE 都是 `41c567e6aabbfec13af0d310bcc08df59194fdbf`，当时不含候选 `4d5c32a7d80c710ef086a1940f7b9beae7f62446`。
- 后续接管快照：父分支 `codex/ops-alert-rootfix-ci-20261109` 已整合至 **`36b8a7e58d93dd9930ff020623d7cd849131df83`**（4d + main 41c）。`docs/ops/machine-check-registry.md` 两行机械冲突均保留，仅去冲突标记；不在文档分支再改该文件。此快照来自给定 controller-state，不冒称持续实时状态。
- 三个 P2 的实施与独立审查在进行；本版没有其合并、发布、云同步或修复后生产验收结果。既有候选 CI `4156 passed / 0 failed / 0 errors / 7 skipped` 只属于 **4d**，不能移贴到 36b 或后来整合 head。
- Nov9 23:18:05 是六组修复到云 CODE 的时点；23:56:06 才到包含冻结持久化修复的 6e；Nov10 05:28:45 到 41c。作者时间、到云时间与 Worker 部署身份不可互相替代。

## 计数口径与保留边界

| 对象 | 归一化结果 | 不能推出的结论 |
|---|---|---|
| 云发送账本 | 224 消息，87 运维、137 其它；87 中有 31 状态通知、6 摘要 | 不是 87 个独立故障 |
| 飞书实际消息 | 两群窗口 216 条已分页读完，运维 87/87 匹配、未匹配 0；4 条正文被发送端截断 | 不代表 QQ 原件已读或正文完整 |
| 摘要/抑制 | 6 摘要的 92 条合并元数据、1361 抑制记录及恢复记录分开核对 | 不将不同单位相加为故障数 |
| 平台邮件 | 8 封完整 MIME，涉及 7 个 UTC 配额窗；2 封重置后才收到；最近一封 Nov9 16:27:35 | 邮件均早于最新优化上线，不能据此认定优化失效 |
| 本机 | 351 开发完成通知；110 云账本副本不重复计数；CODE 30 + worktree 15 假镜像已排除 | 假镜像不是实际渠道送达 |
| 本机读取 | 唯一 inode 路径 3215，完整读到 3208；7 个 worktree 归档在 stat 后读取前消失，共 7593 字节 | 不证明生产删除 |
| 冻结/交易 | 136 历史键 added=0、removed=0；Nov9 九键无 trade，7 无 freeze、2 有 freeze 但缺 Nov9 accum_nav；旧五键仍缺 | 不等于历史恢复；不能“九减五”判四个新 bug |
| 历史改写 | Nov5/6/9 分别 56/58/56 个不同 `(date,index)` 行；每日 15 个此前 OHLC 全同占位形态；Nov9 52 个 OHLC、4 个金额/pct 改动 | 非同一 key 改 56 次；旧 source 身份不足，未证全部正常或本机/异源破坏 |

项目 QQ 主收件箱未通过 IMAP 独立读取；Resend 读取接口 401/send-only 不构成收件回执。无时间戳 SMTP 失败不归为窗口新故障。“119 个历史事件”是一条通知，不是 119 条消息，来源主机未证。原始邮件/飞书正文、私密群 ID、凭证全部留在私有证据目录，本仓仅留必要归一化数据、源锚点与证据 hash。

## 三个确认 P2 与两族编号

三项均为固定 41c 中**预先存在**的缺陷；没有证实本次修复新增 P0/P1 或实际不可恢复数据损坏。复现输入均是合成文本，不复制真实消息正文。

| 索引 | 发现 | 固定源锚点（完整 head 为上文 41c） | 原观察 → 修复后应见 |
|---|---|---|---|
| #379 preupload 统计 | `PREUPLOAD-DATE-01` | `scripts/check_preupload_backup.py:73–115,135–156`；`scan_today_logs` / `parse_log_lines` / `judge` | Nov1 失败+Nov9 成功、mtime Nov9，得到 runs=2/copied=12/failed=1/FAIL → Nov9 新失败 0，旧失败单独保留 |
| #379 preupload 统计 | `PREUPLOAD-SENTINEL-02` | 同文件 `:78–90,145–157`；`scripts/upload_r2.py:2071–2076` 异常写 failed=-1 | failed=1 与 -1，landed=318，汇总 failed=0/OK → 异常与非负计数分开，FAIL/unknown，不能抵消为 OK |
| #380 测试隔离 | `TEST-MIRROR-03` | `scripts/tests/test_f03r1_digest_atomic_write.py:38–65`；`scripts/notify.py:103,1937–1979`；`sandbox` / `_replace_latest` | 只换 ALERTS_DIR、不换导入时固定 ALERTS_FILE，合成“外部目标”被替换、sandbox latest 不存在 → 所有派生路径留沙箱，外部目标字节不变 |

索引基线最大 #377；写入前核对 **36 个本地分支、6 种索引 blob 和现存 worktree**，发现 **#378 已被 `feat/fix/merge-fastcheck-gate-20261110` 的 main-merge 快检闸门占用**，已上报并避开；本版不复制该行、不抢号。#379 合两项统计问题，#380 单列测试隔离，三项发现本身不合并抹平。远端未 fetch 分支与未来并发登记仍由父合并前再核号。

同模块对账：#237 原 relay/检查器上线事实不回写，PhaseA fail-fast 未开启与旧失败继续主 PUT 的回滚风险仍需独立决策；#367 原摘要并发修复完成事实不回写，新测试隔离由 #380 承接。#257/#333 候选的指数/NAV 恢复、#353/#354 同域排队、#372 候选发布门禁、#373 原备份/Nov3 权威归因、#374 D1、#375 双自动发布链均沿用原号，不重复立项。#311 已销账的 backup_db↔data 跨域互锁不重开为本次同域锁事件。

## 21 类状态与证据

[audit-normalized.json](audit-normalized.json) 的 `repair_matrix` **逐条保留全部 21 类** id、原状态、根因摘要、修复候选/部署界限和结论；`confirmed_p2` 保留三条 trace/verifier。它是上述固定审计快照，不把“原审计未修”自动变成当前部署判断。

已发生的改善：监控部署后 23:30–08:45 **38/38** 原生轮次 delivery_ok/HTTP200，抽样 ID 真实落库；业务样本仍有 41/42 unknown。Nov10 08:27 **90 unit 逐字段、45 service 登记 PASS**，仅覆盖登记/顶层配置。换手率最新自然链 **6/6+3/3 上传与 purge 成功**，不归功于未部署的 4d；九文件业务逐值复核是父前轮事实，本轮不冒称重做。

仍独立保留：R2 intraday 等锁 600s 拒传、purge 等 570s 后失败，后续总链 rc0 不关闭失败清单，日志仅证明持锁进程候选；D1 blocked 邮件与重置前 OPS 成功落库并存，需完整自然周期/配额口径；原 pre-upload GET503/TLS EOF 真错误与回滚风险不能因统计误计而静音；#373 Nov1/2 原备份及 Nov3 指标权威身份不足，不能拿今天重造；overfit **74/red** 是真实业务风险，保持告警。overfit 主/ext 四地址 HTTP200+hash 等于云 DATA 只证明当前对象追平，不证明交付机制根治。备份/nextday 新逻辑没有在截止前拿到对应新自然轮验收。

## 可复现方法

无需安装依赖。报告本体 + 生成脚本 + 复现段（本 README）为三件套，另附独立三个 P2 的安全反例脚本。每条命令的外层 timeout 显式有界；`git show` 子调用另限 10s：

```bash
# 在本仓任一保留41c对象的worktree执行；以下cwd为指定文档worktree。
python3 -c 'import subprocess; subprocess.run(["python3","-B","docs/codex-reviews/alert-takeover-20261110/reproduce_p2.py"], timeout=30, check=True)'
python3 -c 'import subprocess; subprocess.run(["python3","-B","docs/codex-reviews/alert-takeover-20261110/generate_archive.py","--check"], timeout=30, check=True)'
python3 -c 'import subprocess; subprocess.run(["python3","scripts/check_task_state.py","--skip-zombie-crons"], timeout=30, check=True)'
```

`reproduce_p2.py` 只经 `git show 41c:<path>` 读固定源码，AST 抽取白名单函数/常量；不导入业务模块、不执行 fixture/完整套件、不访问网络/数据库/真实通知器。写入的 simulated-live 与 sandbox 都在 `/tmp`；退出 0 表示**三个旧源码缺陷复现成功**，不是修复通过。真实 latest 文件不改、不清理，不运行已知可污染它的原测试。

`generate_archive.py --check` 先校验四个固定输入及 31 份证据 SHA-256，再按显式允许字段生成并逐字节对账。父 controller-state 在归档期间已推进，固定 hash 校验如期拦截新版；本版把先前完整读取的旧内容保存为私有 `/tmp/codex-reports/alert-takeover-20261110/docs-source-snapshot/controller-state.json`，恢复后实核 **1558 字节及原 SHA 完全一致**，同目录保留授权输入。生成脚本默认从这份私有快照读授权/状态，原父状态文件未改；可用 `--takeover-dir` 指定另存的同 hash 原件。证据来源路径在清单保持原身份，不随重放位置变化。原件不在本机时只能阅读已入库快照，不能声称重跑原件校验；新事实应追加新版本，不覆盖本版。

原审计 SHA-256：`c3e77494cb30a8aff69d6ed3759a1ec0e5cceae4bb7eeeefcdb604f737f1fa05`。四输入与全部 31 份证据的文件名/字节数/hash 见 [evidence-manifest.json](evidence-manifest.json)，正文不入库。

## 父整合后续追加项

父提供真实结果后再追加收口段：三个 P2 各自完整 commit 与独立审查结论、最终整合 head 的完整测试末行和 CI run/head、main 包含关系、云 CODE 文件 hash/同步与必要重启、Worker 版本及发布来源、受控恢复前备份与精确 key/日期差异；NAV/指数恢复不得用 rc0 替代逐键证明。#374 16:00 稳态写量及完整 UTC 周期、R2 失败清单与持锁时间、#373 历史原件、冻结 T0/交易缺口和 overfit 风险按各自证据关闭。**本版不等待未来自然轮，也不提前称已合并或部署。**
