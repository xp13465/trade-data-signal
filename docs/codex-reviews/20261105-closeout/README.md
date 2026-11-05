# 2026-11-05 协作收尾：补测、台账、Git 清理与回执

本目录记录用户明确“做”授权的四项工作。固定基线为 `6c1493aea9febd6318eafa8a5cf51d0d774aa155`；本轮业务源码不改，合并与业务 findings 处置仍交 Claude 独立复核。前端版本保持 `20261105-a657` → `20261105-a657`。

| 授权事项 | 实际结果 | 接力边界 |
|---|---|---|
| 回归补测 | `codex/notify-regressions-20261105`，`0d1bc0fdcdb849a371c4804adf7fae97aba16d19` 已推送且远端 SHA 一致；49 项定向为20 failed /29 passed；全量为20 failed /2358 passed /3 skipped | 20红全部为现有权限异常路径；没有xfail/skip遮红。本分支是 DRAFT，不可单独合并。Claude复核并配套业务修复后再验。fixture内存模拟49绿不代表业务已修 |
| 台账与落档 | 只修改 pending-index #366–#370 状态单元格；24份原证据保持原字节 | 本分支待Claude审合；#333剩余事项及#371/#372已定政策未改 |
| 本地清理 | 本地分支39→6，删除33条已合分支；worktree13→4，备份后移除9个；4份stash保留 | 远端、main、Codex分支与占用/未合保护项保留；未force/prune/gc。不是Git历史瘦身，bundle保留旧历史 |
| 通知回执工具 | 自研CLI、两项hook及测试位于 `codex/collab-closeout-20261105`；53项定向通过；修复坏队首P1后独立18组PASS；全量2382 passed /3 skipped /1 warning | 仅分支准备接入；未安装live hook，未声称Claude已读/认领/完成。真实加载后由下一个正常事件提示，不能唤醒idle会话 |

以上两分支均需Claude独立review；本地green不代替远端CI或真实Claude加载。工具作者冻结清单作为历史材料保留，主会话随后只收紧了deadline下的文档上界，三份源码/配置冻结未变。

机器可读最终结果见 [closeout-status.json](closeout-status.json)。本分支仍需 Claude 审核合并，未执行 main commit/push 或部署。

## 清理备份与恢复

永久私有备份：`/Users/linhuichen/code/trade-backups/20261105-codex-closeout-20261105T175548-390bd6`（0700）。standalone bundle 为1,371,615,270字节，SHA256 `1637809ea636e718eff850bf79838eade4bb4c117f4ad363fd302868bd9745ed`。在新的空bare仓实际fetch，refs精确一致、无alternates，完整严格fsck通过，候选及stash对象读取校验通过。9份工作区归档含ignored/untracked文件，逐文件hash及覆盖核验通过；私有内容未入Git。

[清理manifest](evidence/closeout/cleanup-manifest.json)含删除记录、保护项与完整性证明；[摘要](evidence/closeout/cleanup-summary.md)、[恢复步骤](evidence/closeout/cleanup-recovery.md)。未合 `feat/fix-258-s06-budget` 与仍被进程cwd占用的 `worktree-agent-a33753a60314dae35` 保留；不kill进程。4份stash原顺序和原始reflog字节哈希未变，已备份并核验无独有补丁，按本次约定继续保留。目录清理不会缩短历史或改善远端首次clone大小。

完整清理报告保留在私有备份 `cleanup-final-report.json`，SHA见manifest；仓内只存元数据，不存bundle/tar/私有配置。恢复验证用的是新空仓，没有向生产工作区覆盖文件。

## 本轮补测与交接工具验证

[补测摘要](evidence/closeout/regression-summary.json)、[全量结果](evidence/closeout/regression-full-result.json)与[已推送身份](evidence/closeout/regression-delivery.json)保留原始数字。20个红例为5条writer × stat/chmod故障 × 0600/0640；29绿包含正常保权、新建默认mode、严格fchmod、真实多进程两序payload/缓冲守恒以及删payload仍返回成功的负控。全量源码hash前后不变，没有其它模块失败。完整日志/JUnit路径属于本机原始取证定位；长期摘要在仓，测试入口在固定分支。

工具首轮独立自检曾为FAIL：失效队首未消耗总hash预算，实测每事件约4秒读取6.27GB并挡住有效尾；该报告保留，不能用首轮48绿替代独立结论。修复后定向为53 passed（26.28s）；每事件最多32个packet、4次hash、33,554,436报告字节，失败也计额；同锁原子游标使近容量fixture的有效尾在256次事件内可达；这是每次完成预算循环的边界，读取逐次超时则可能需1023次，游标写入前中断不计进度。预算与游标不缓存完整性/ACK结论，status/ack仍实时验hash。修复后[独立R2](evidence/closeout/handoff-selfcheck-r2.json)为PASS（18组），原样CLI近满队列768个事件均exit0，实际timer中断后下一事件继续，未误ACK；[全量](evidence/closeout/handoff-full-result.json)为2382 passed /3 skipped /1 warning（314.18s），源码/测试/settings前后SHA一致。演示packet已归档退役，未伪造ack；最终master须在两个分支提交推送后固定报告再publish。

[台账/版本/旧hooks保留校验](evidence/closeout/precommit-gates.json)通过；版本校验只跑1/2及版本进度，未跑前端build/min校验3，因为本轮无前端写集。没有把本机检查当成远端CI、Claude最终review或上线。

## #366–#370 状态事实

本次按用户已确认的“原修复已审、已合、已上线”纠正台账，并分别列明证据来源和验证范围。原问题描述作为历史触发背景保留，仅修改状态列；[逐行前后对账](ledger-reconciliation.json)保存原行与新行，并校验目标外文本逐字节一致。

| 项目 | 已完成事实及固定提交链 | 证据边界 |
|---|---|---|
| #366 FOF 整批异常 | F01/R1 `1f98f67ba` → `00dabd713`；旧 P2-C 回滚 `af6fddf10` → `d813cc2ad`；同类 ETF 回滚 `5771ef41a` 亦在固定 main | 下午验收用真实 SQLite 验证中途失败零残留、后续基金容错及全批失败 exit 2/合法空 exit 0/信号复位；云上同步事实来自 Claude 回执。仅核销本行，不核销 #333 批2/批3、份额类清理、定开封闭识别、历史回填及原 skip 判据剩余工作 |
| #367 摘要并发 | F03/R1 `197a0beda` → `31c868fa3`；原三项后端 P2 修复批次已审合上线：权限 `15b7ec53c`、假红 `6b91de7e8`、FOF 回滚 `af6fddf10` → `d813cc2ad`；同类正常权限路径 `897b56624` 亦已上线 | 原三 P2 的关闭由下午独立验收支持；正常 mode 矩阵、两序 payload/缓冲守恒通过。新两项 P2 只列待 Claude 复核候选，见下文 |
| #368 R2 屏障锁 | `bf1ed42d4` → 实际 merge `aac5d19bd`；固定 main 的 `upload_r2.py` blob 与其相同：`1e3e92107379ad6604ca625f885ca7690cb1d697` | [既有独立外审](../night-20261105/evidence/f04-main-recheck.json)：16/16 定向测试、15/15 独立场景、exact-SHA CI success。该外审明确不作云上/R2部署声明；本次上线状态依据用户确认，文档归档阶段 只复核提交与 blob，未重做生产故障注入 |
| #369 正文超时 | `92013be60` → merge `37f6641dd`，首次发布 `a655`；经 `c508c0a72` 补齐版本载体后验收为 `20261105-a657` | Claude 回执记录独立审查及发布；下午验收线上 app/lab min 与固定 main blob 字节相等，本机真实 Chromium 生命周期 46/46 通过 |
| #370 boot 超时 | 与 #369 同批审查、合并、部署，当前验收版本 `20261105-a657` | 46 场景含 boot 响应头/正文超时、共享预取与兜底；不写成“仍待审合部署”，也不外推真机、WebKit、真实时长 SLA 或全站视觉通过 |

[固定 main 提交图取证](fixed-main-commits.json)由归档阶段只读 `git show`、`merge-base --is-ancestor`、`diff-tree`、`rev-parse` 生成：28 个相关提交均在固定 main 祖先链中，另复核 F04 blob 一致。提交在 main 只能证明版本归属；线上或云上状态使用上述单独证据来源，不从祖先关系推断。

## 新候选与发布尾项分级

整合结论保留原 [report.json](evidence/recheck/report.json) 的 `PASS_WITH_RESIDUAL_P2`。原始 [backend.json](evidence/recheck/backend.json) 的 `PASS` 绑定“旧三 P2 可关闭”，并没有表示所有边界均无问题。

两项后端候选均**待 Claude 复核**，尚未作为新业务需求拍板：

1. `BACKEND-NEW-P2-01`：同类权限 helper 吞掉异常 `stat/chmod` 后仍 replace，故障注入中可发布不同 mode 的新 inode。原摘要 `_atomic_write_digest` 严格处理 fchmod 失败，该旧修复仍成立；不声称线上发生泄漏或生产事故。
2. `BACKEND-NEW-P2-02`：作者并发测试以 buffer 为空推断交付成功，缺少实际 payload 守恒断言；负控删掉新条目 payload 仍可测试绿。固定 main 的独立两序守恒检查通过，不能把测试缺口写成生产已丢通知。

原始 [release.json](evidence/recheck/release.json) 中三项 P2 标签为子报告的原始记录，按原字节保留；**对外结论沿用主报告已做的假阳性分级，不照抄为三个未修 bug**：

| 原始 ID | 主报告分类 | 具体口径 |
|---|---|---|
| P2-1 | `documented_internal_precondition_not_confirmed_bug` | `MAIN_MERGE_RESUME=1` 是已合并后的内部续跑契约；未合 feature 即使 dry-run 也拒绝，符合当前前提，不能直接叫 bug |
| P2-2 | `recovery_optimization_candidate` | push 全失败后普通重跑可多 bump 一次，但最终产物完整；未找到通用 push-only 幂等恢复承诺，属于恢复语义/优化候选，交 Claude 决定 |
| P2-3 | `documented_guard_coverage_limit` | 残留守卫覆盖常规 bump 内的已跟踪未暂存变化；staged-only/未知文件是已有覆盖边界，不表述成三产物漏提交仍未修 |

发布主机制的既有验收涵盖三产物补齐、17 项写集、自更新重载、防循环和 SHA 失败告警。22 组独立沙箱使用合成本地 Git fixture，压缩器、其它门禁、SSH 和 CI 为显式桩；不等于真实发布或远端 CI 全量复跑。最初文档归档阶段只核对已有证据，未重做这些发布探针；本轮主会话新增执行的补测、工具检查及Git恢复核验单列在本文开头。

## 原始材料与长期追溯

| 材料 | 本目录位置 | 来源 |
|---|---|---|
| 主报告、前端、后端、发布 component JSON | [evidence/recheck/](evidence/recheck/) | `/tmp/codex-reports/recheck-20261105-afternoon/{report,frontend,backend,release}.json` |
| 原始任务对账、清理前盘点 | [task-reconciliation.json](evidence/recheck/task-reconciliation.json)、[cleanup-inventory.json](evidence/recheck/cleanup-inventory.json) | 同上目录；原文的“本轮未修改/未清理”描述属于原验收时点，保留不改 |
| Claude 原始回执 | [claude-receipt.json](evidence/claude/claude-receipt.json) | `/tmp/codex-reports/night-20261105/claude-receipt.json`；与下午 receipt snapshot 字节一致 |
| 固定基线、原提交取证、源码 hash、浏览器独立复核、职责记录 | [evidence/context/](evidence/context/) | 原始 JSON，含 ownership 快照 |
| 权限/回滚/两序守恒/负控结果与少量原始日志 | [evidence/backend/](evidence/backend/) | 原隔离 fixture 的合成测试结果，不含生产数据 |
| HTML 差异过滤结果 | [html-delta-filter.json](evidence/frontend/html-delta-filter.json) | 线上 HTML 仅有边缘脚本插入，移除唯一插入可还原固定 blob；依据路径/头部推断为 CF 注入，未误报版本漂移 |

[archive-manifest.json](archive-manifest.json)逐项记录原路径、归档相对路径、字节数和 SHA256，24 份原始文件均按原 bytes 复制；六份核心验收 JSON 另与原目录 SHA256SUMS 交叉核对。Claude 回执 SHA256 为 `4a51668525f0f999900993057a1fcf3f948a9a2972af397da916c6e2c6c39593`，与原任务对账记载一致。

原 JSON 中的 `/tmp` 路径保留为历史取证定位，通过 manifest 映射到仓内副本；主结论、components、回执和必要结果均在仓内，不依赖 `/tmp` 作为唯一长期依据。大 HTML、截图、min、Git tar、`.env`、生产数据均不复制。源码由固定 Git commit/blob 追溯。

本目录未复制 Python 探针。原报告 verifier 命令中的本机绝对路径指向**原始取证脚本及当时隔离环境**，不是可移植 CI 入口，不能照抄到任意机器运行；这里保存原始报告和必要结果 JSON/日志，复审可据固定版本及独立 tests-only 分支重建隔离验证。

`SHA256SUMS` 覆盖本目录所有文件并**排除自身**。在本目录执行以下命令仅核验归档完整性，不运行产品脚本：

```sh
shasum -a 256 -c SHA256SUMS
```

后续修改状态或证据后，先检查新增文件仍属本目录，再在本目录重算：

```sh
python3 - <<'PY'
from pathlib import Path
import hashlib
root = Path.cwd()
assert root.name == '20261105-closeout'
files = sorted(p for p in root.rglob('*') if p.is_file() and p.name != 'SHA256SUMS')
(root / 'SHA256SUMS').write_text(''.join(
    f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(root).as_posix()}\n'
    for p in files
))
PY
```
