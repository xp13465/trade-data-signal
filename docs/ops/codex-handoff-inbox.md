# Codex 交接收件与显式回执

来源：用户 2026-11-05 授权。群消息和 `.done` 没有进入现有 Claude 上下文，实际仍靠用户转达。此工具只补「显式发布结构化交接 → 正常 hook 事件提供元数据 → 显式回执」，不执行交接任务。

## 生效条件

本 feature 的 `.claude/settings.json` 只追加 `UserPromptSubmit` 和 `PreToolUse`，全部既有 hook 保留。命令是兼容本机 Claude Code **2.1.274** 的 shell 字符串：

```json
{"type":"command","command":"python3 \"${CLAUDE_PROJECT_DIR}/scripts/codex_handoff.py\" hook","timeout":5}
```

只使用稳定的 `hookSpecificOutput: {hookEventName, additionalContext}`，无 `args`、权限决定、输入改写或继续执行字段。[官方说明](https://code.claude.com/docs/en/hooks#add-context-for-claude)确认两个事件支持附加上下文；这是外部数据，不是用户指令。

**需 Claude 审核、merge 并实际加载配置后，下一次正常事件才可能注入当前会话。** 本轮不做 live 安装/加载；空闲会话不保证即时唤醒。即使进程输出成功，也只能证明输出过上下文，不能证明模型已读、认领或完成。

`${CLAUDE_PROJECT_DIR}` 保持会话初始项目目录，工具的 `cwd` 则可能切到 worktree 或子目录（见[官方路径说明](https://code.claude.com/docs/en/hooks#reference-scripts-by-path)）。hook 始终以初始项目的 Git common directory 过滤收件，不从工具 cwd 猜分支；同仓库 worktree 共享项目归属。新脚本也必须在初始项目路径可用。

## 发布与核验

**Codex 报告完成后必须显式 `publish`，只写报告或发送群消息不算发布。** hook 只处理新工具发布的结构化 JSON。旧 `codex_notify_bridge.py` 的群消息、`.done`、`last_assistant_message`、现有 watcher/consumer/`.ready` 均不接入、不转换，也不会自动编辑消费者。

发布前确定报告所属的实际工作分支和完整已提交 head，固定最终报告文件。示例中的 head 必须替换成该分支真实完整 SHA：

```sh
python3 /Users/linhuichen/code/trade/scripts/codex_handoff.py publish \
  --id handoff-example-v1 \
  --project /Users/linhuichen/code/trade/.claude/worktrees/codex-collab-closeout-20261105 \
  --branch codex/collab-closeout-20261105 \
  --head <该工作分支的完整commit-SHA> \
  --report /tmp/codex-reports/example-master-report.json
```

- `--head`/`--branch` 是调用者显式声明；工具核对本地 `refs/heads/<branch>` 恰等于完整 head，且 head 确为本地 commit，才写入。`head_verification=local-branch-and-commit-at-publish` 与 `head_verified_at` 说明核验方式和时点。**不证明已 push、合并、包含未提交改动或上线。** 不把 root 的 main HEAD 当作 Codex 工作分支，也不读取报告内声称的 head。
- 工具直接读取报告字节算 SHA-256，不信报告内写的 hash，也不从报告或最后一条回复猜路径、分支、head。报告正文不生成指令或摘要，hook 只输出 id、项目、路径、branch、head、hash。
- 同 id、同全部元数据重试幂等，保留回执与去重状态；head/hash/路径/分支/项目任一不同即拒绝。新版本用新 id，不重置旧回执。
- 主会话最终在两分支 push 后生成并固定不可变 master report，再发布新 id；**publish 后不改报告文件，回执另存 inbox**。本轮工具演示不代替该 master report。

## 状态与显式回执

```sh
python3 /Users/linhuichen/code/trade/scripts/codex_handoff.py status \
  --project /Users/linhuichen/code/trade --id handoff-example-v1
```

| 字段/状态 | 能说明什么 |
|---|---|
| `delivery=queued` | 已发布，尚无 hook 上下文输出记录 |
| `delivery=context-emitted` | hook 输出过元数据；不代表 Claude 已读 |
| `ack=null` | 没有显式已读回执 |
| `ack=received` | 操作者显式声明已读，已核验固定 head/hash |
| `ack=claimed` | 在已读之后显式认领 |
| `ack=completed` | 在认领之后显式声明处置完成；不等同 merge/上线 |
| `integrity=verified` | **本次查询**读取报告，其 SHA 与发布时一致 |
| `integrity=report-changed/report-unavailable` | 报告已改、缺失、越界、变成 symlink 或不可读；`status=invalidated`，旧 `ack` 只保留为历史记录 |

`status` 在完整性通过时取 `ack` 或 `delivery`；完整性失败优先显示 `invalidated`，不能把旧 claimed/completed 当成仍有效。查询不篡改历史回执。hash 相符只说明字节一致，不证明报告结论正确；head 核验字段是发布时的记录。

Claude/操作者读完固定报告后显式发回执，三个状态都必须逐步、手动调用：

```sh
python3 /Users/linhuichen/code/trade/scripts/codex_handoff.py ack \
  --project /Users/linhuichen/code/trade --id handoff-example-v1 \
  --head <发布时的完整commit-SHA> --sha256 <发布时的64位SHA256> --state received
```

认领时把 `--state` 改为 `claimed`；处置完成后再用 `completed`。每次都核对项目/id/head/hash、head 为真实本地 commit、当前报告字节。分支后续移动不改变固定 head。回执保存自己的 id/project/head/hash，旧身份回执不能嫁接。相同状态重试幂等；禁止跳级、降级，terminal（completed）不降级。明确的手动已读不要求事先有 hook 输出。

hook 只面向 Claude 主会话。payload 有 `agent_id` 或 `transcript_path` 含 `/subagents/agent-` 时，在处理 session/inbox 前直接跳过，不读取转录、不产生 emission，也不抢占主会话的去重位置；单独的 `agent_type` 可能来自顶层 `--agent`，不据此拒绝。

hook 自己从不 ack。`PreToolUse` 按固定报告与 session 去重，session 仅存 SHA-256；未显式 ack 的 `UserPromptSubmit` 可以再次提示。已读后的交接不再提示。每个事件最多输出 4 条；按 id 循环扫描并跨事件继续，不再每次回到队首。用户事件不采用工具 session 去重，循环再次到达未确认条目时仍可提示。

每事件最多检查 **32 个 packet**、尝试 **4 次报告 hash**；缺失、越界、不可读及 hash 不符的尝试同样占额。每次尝试预留最大 `8 MiB + 1` 字节（额外一字节检测文件增长），故报告总读取上限 **32 MiB + 4 字节**。预算耗尽的条目留待后续事件，不输出尚未验证的报告。

`.scan` 保存各项目的上次检查 id，最多 32 个项目。它与 packet 使用同一个稳定锁、0600 唯一临时文件和原子替换，在尝试读取前写入；写失败则静默结束，不开始报告 hash、不输出上下文。它只是检查位置，**不代表已读、有效或失效**，不生成 ACK，也不缓存权威完整性结论。格式损坏的游标可从头重建；状态写入失败或正常事件未到达时，不承诺前进。

队列固定、同项目持续收到正常事件且状态写入成功时，循环会越过坏前缀；每次均能完成预算循环时，1023 个 packet 最多 **256 次事件**检查到队尾。进度即使遇到报告读取超时也已保存，不会反复卡住同一份报告；若每次仅检查一份即被 deadline 中断，则可能需要最多1023次，未到达游标写入的事件不计进度。报告恢复原字节后仍会重新检查；`status`/`ack` 保持现场真实 hash 校验，不采用游标或上次 hook 的判断。`queued` 只表示尚未输出上下文，不能单独推断报告有效。

## 存储、安全与限制

- 独立目录 `/tmp/codex-reports/handoffs` 必须属于当前用户、权限 0700；packet、稳定 `.lock` 和 `.scan` 为 0600。单一稳定 `flock` 覆盖读取、校验、状态改写；唯一临时文件、flush/fsync、`os.replace` 原子替换，不替换锁文件。多进程 publish/hook 不得覆盖更新的回执。失败保留旧 packet/游标；重试不降级。
- 仅标准库、本地 Git 只读查询。不调用 LLM/claude，不执行交接任务、不发外部消息或 `.ready`、不改工具权限。也不记录用户 prompt、tool_input、转录全文或报告正文。
- id 仅字母数字开头、字母数字/`_`/`-`，最多 96 字符；head 为完整 40/64 位小写十六进制，branch 最多 200 字符。绝对路径只接受 ASCII 字母数字/`_`/`.`/`/`/`-`、最多 768 字符，不接受空格、中文路径或 `..`。逐层拒绝 symlink；仅兼容系统 `/tmp` 别名。报告限项目 common directory 的父目录或 `/tmp/codex-reports` 内的普通文件，最大 8 MiB。
- hook 输入、packet 和游标各限 128 KiB；超大/损坏输入静默忽略，不抄送其中内容。原有目录容量上限 1024 项（含锁）外，为 `.scan` 单独保留一项，即稳定布局最多 1025 项；容量检查还容许一个严格匹配 `.32位小写十六进制.tmp` 的唯一临时项（总计 1026 项），不占 packet 位置。新 publish 仍保留原容量余量，已有 1023 packets + 锁的 inbox 可直接增加游标并继续扫描；同锁内不会有另一个正常进程竞争临时项。每个报告最多记录 256 个工具 session；达到上限后不再为新工具 session 提示，用户事件仍可提示。无自动清理、重试任务或通用消息框架，容量整理交主会话。
- 空 inbox/项目不匹配/已 ack 时 stdout 零输出。异常 exit 0，不阻塞正常 Claude；hook 内部总预算 4 秒、锁等待 0.5 秒，配置 timeout 5 秒。CLI 错误 exit 1，锁等待最多 3 秒，便于显式操作重试。
- `context-emitted` 只记录 stdout 已输出；进程在输出与落盘之间中断可能重复提示，平台未消费输出也不等于已读。文件系统掉电持久性、同用户恶意篡改状态、模型是否实际理解报告不由工具证明。

## 本轮验收与演示

定向测试：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider scripts/tests/test_codex_handoff.py
```

覆盖真实 CLI JSON/stdout、多进程 publish/ack/hook、原子写失败、旧回执/乱序、修改报告/hash/head/项目错误、symlink/FIFO/尺寸、空收件、提示后未 ack、状态重新验 hash、同 session 子 agent 先触发不影响主会话、顶层 agent_type、既有 hook 保留；另验近容量坏前缀的两事件读取预算/有限次队尾可达、最大尺寸失败 hash 预算、游标写失败与读取中断后的继续扫描。所有模拟 hook 只用测试专用 inbox/session。全量 `scripts/tests/` 由主会话统一跑。

P1 修复后的定向末行为 `53 passed in 26.28s`。两种事件均从 1023 packets + 锁的旧容量开始，持续检查增加游标后的 1025 项布局，在第 256 次事件到达有效队尾；测试也验证增加唯一临时项后仍能枚举全部 1023 个 packet。近容量回归用 64 KiB 报告控制总测试开销，另用真实 8 MiB 报告验证单事件失败 hash 的次数与字节上限。

测试专用 inbox 的本机实测：4 次最大尺寸失败 hash 共读 33,554,432 字节，两个事件分别约 0.033 秒、0.032 秒；不读报告而检查 32 个 packet、逐候选原子写入/fsync 游标，三次约 0.019/0.018/0.018 秒。证据在 `/tmp/codex-reports/closeout-20261105/handoff-p1-budget-probe.json`。这是本机缓存和文件系统下的样本，不保证其他机器同延迟；4 秒内部 deadline 与 5 秒配置超时仍保留。原独立 FAIL 与后续 R2 应一起归档；定向通过不代替独立复验或主会话全量测试。

本轮曾实际发布 `handoff-closeout-tool-demo-20261105-v1`，publish + status 证明为 `queued`，未调用真实 packet 的模拟 hook 或伪造 received。**该 demo 已由主会话退役并移入私有证据 archive**，见 `/tmp/codex-reports/closeout-20261105/demo-retirement.json`；它不是当前活跃交接。演示原报告保持不变，最终真实 inbox 只保留主会话正式 master packet。发布时 id/路径/SHA/状态及修复后的冻结记录见 `/tmp/codex-reports/closeout-20261105/handoff-progress.md`。

本机制补偿平台的上下文交接缺口，复审期限 2027-05-05；平台若提供可靠的原生接收/认领回执，优先评估退役本工具。可机检部分为上述定向用例；真实加载和下一次正常事件到达须由 Claude 侧实测，不能用测试注入代替。

主会话最终验证：全量 `scripts/tests/` 为 **2382 passed / 3 skipped / 1 warning（314.18s）**，源码/测试/settings 前后SHA一致；独立R2 **18组PASS**，原P1解除。报告与原FAIL一起归档于 [协作收尾](../codex-reviews/20261105-closeout/README.md)。这仍不表示Claude最终审合或live加载已完成。
