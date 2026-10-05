# r2-slim long31「exit 144」归因定论（2026-10-05，只读调研）

> **背景**：分支 `feat/r2-slim-20261003` 报告草稿（`@ac2d7d21a` §⑧-2 / §④ L48）写「`zstd --ultra -22 --long=31` **运行失败（exit 144，211MB 处终止，无报错）**」；main 现行同文件 §⑧-3 写「**按任务书限时窗口停掉**」。两版对同一事件归因不同。本报告只读取证（不改任何现场文件），用实物证据定论。

## 0. 结论

**B = 按限时窗口主动停掉（退出码 144 非 0，但不是「运行失败」）。**

1. long31 压缩进程由 **land 收口 agent**（worktree `agent-a6e41f0e4fff47165`）在 **2026-10-04 00:50:06.060（北京）** 执行 `kill 39145 39142`（SIGTERM，kill 默认信号）主动停掉；停前已按其任务书核实 PPID 属主链。
2. **exit 144 的真实语义** = **Claude Code（macOS + v2.1.274）后台任务在「包装 shell 被 SIGTERM 终止」时的记录码**；它不携带「zstd 自身失败」的信息。本机 4 次复现：对 Claude Code 后台命令（zsh 包装层）发 `kill`（TERM）→ output 与通知**恒记 `[exited with code 144]`**；用纯 `sleep`（不可能「运行失败」的命令）同样得到 144。
3. 「144 = 128+16（SIGSTKFLT/SIGURG）」假说被实验否定：① `kill -16`（SIGURG）对该进程树**无效果**（进程存活、任务不结束）；② 不经 Claude Code 的普通 `/bin/zsh -c` 被 TERM 杀标准 rc=**143**；③ `kill -9` 场景 Claude Code 记录 **1**——144 不是「128+signal」的机械换算。
4. 产物 `211,386,368 B` 结构完好（zstd 帧头合法、可解出正确 tar 头），是「正常压缩流被中途切断」，非压缩逻辑失败。

## 1. 现场第一手证据（六个取证点，全部可复跑）

**取证点 1：启动命令原文**（调研 agent 会话转录，2026-10-03T16:03:06.278Z = 北京 10-04 00:03:06）。
转录：`/Users/linhuichen/.claude/projects/-Users-linhuichen-code-trade/3ba5f717-05ed-4419-abe0-6426872cd686/subagents/agent-ad8cfa7e6d1d82182.jsonl`（下称「调研转录」）L262：

```
{"command": "time zstd --ultra -22 --long=31 -T4 -c /tmp/mac_backups_20261001_raw.tar > /tmp/mac_backups_20261001_long31.tar.zst; ls -la /tmp/mac_backups_20261001_long31.tar.zst", "run_in_background": true}
```

→ 后台任务 ID `bnk2j3j9s`（L263）。

**取证点 2：现场 output 文件（仍在，字节级原样）**：

```
$ stat -f "%N size=%z mtime=%Sm" /private/tmp/claude-501/-Users-linhuichen-code-trade/3ba5f717-05ed-4419-abe0-6426872cd686/tasks/bnk2j3j9s.output
.../bnk2j3j9s.output size=24 mtime=Oct  4 00:50:06 2026
$ xxd .../bnk2j3j9s.output
00000000: 0a5b 6578 6974 6564 2077 6974 6820 636f  .[exited with co
00000010: 6465 2031 3434 5d0a                      de 144].
```

→ 内容仅 `\n[exited with code 144]\n`，**无任何 zstd 错误文本（「无报错」属实）**；mtime = kill 当时（00:50:06）。

**取证点 3：调研 agent 收到的失败通知**（调研转录 L288，16:50:06.577Z）：

> `<status>failed</status><summary>Background command "zstd --ultra -22 --long=31 大窗口压缩后台跑" failed with exit code 144</summary>`

**取证点 4：kill 命令原文**（land 转录 `.../subagents/agent-a6e41f0e4fff47165.jsonl` L113，16:50:06.060Z）：

```
{"command": "kill 39145 39142 2>/dev/null; sleep 2; ps -o pid,ppid,command -p 39145,39142 2>/dev/null; echo \"kill-done\"; ls -l /tmp/mac_backups_20261001_long31.tar.zst", "description": "终止 long31 压缩进程并确认"}
```

→ `kill` 无信号参数 = **SIGTERM**；L114 结果：两 PID 已无输出（进程已死），kill-done。

**取证点 5：停前 PPID 属主链核验**（land 转录 L109，16:49:54Z 实测输出）：

```
  PID  PPID STARTED                COMMAND
39145 39142 日 10/4 00:03:06 2026  zstd --ultra -22 --long=31 -T4 -c /tmp/mac_backups_20261001_raw.tar
===
  PID  PPID STARTED                COMMAND
39142 38456 日 10/4 00:03:06 2026  /bin/zsh -c source ...snapshot-zsh-... && ... && eval 'time zstd --ultra -22 --long=31 -T4 -c ... ; ls -la ...' < /dev/null && pwd -P >| /tmp/claude-0ea1-cwd
===
  PID  PPID COMMAND
38456 68271 claude --resume
```

→ 进程树：zstd(39145) → zsh 包装(39142) → claude 会话(38456)。**kill 同时杀 zstd 与 zsh 包装层**（这点在 §2 是决定性细节）。

**取证点 6：两版叙事各自的实时产出**：

- land（执行方）侧：L107（16:49:53Z）「long31 在 00:43→00:49 六分钟只从 189.8MB 长到 210.9MB…**远超 15 分钟窗口。按任务要求停掉**」；L112「PPID 链确认…安全，停掉」；L119/L123 报告改写为「**按任务书限时窗口停掉**（停前核实 PPID 属主链=本调研 claude 会话派生，非生产进程）」。
- 调研（被终止方）侧：调研转录 L289「long31 压缩失败（exit 144）。读输出定位原因。」→ L294「long31 在 211MB 处被终止（exit 144，无报错）。这档不稳定，不再重跑。」（**未做任何 kill 归因调查，直接接受「失败」——分歧即源于此**）。

## 2. exit 144 的真实语义（2026-10-05 同机同版本复现实验）

版本核对：现场转录 `version: 2.1.274`；本机 `claude --version` = 2.1.274（同版本）。复现实验列表（全部在 /tmp，不动现场）：

| # | 实验 | 动作 | output 记录 |
|---|---|---|---|
| E1 | 同构复现：后台 `time sleep 400; ls -la /tmp/r2sl_exit_src.txt` | `kill`(TERM) zsh 包装+子进程 | **`[exited with code 144]`** |
| E2 | 极简：`time sleep 500`（无 `;ls`） | `kill`(TERM) zsh+子进程 | **`[exited with code 144]`** |
| E3 | 同上 | 先 `kill -16`(SIGURG) → **进程存活、任务不结束**；再 `kill`(TERM) | **`[exited with code 144]`** |
| C1 | 对照A | `kill -9` zsh+子进程 | `[exited with code 1]` |
| C2 | 对照B | **只 kill(TERM) 子进程**（zsh 存活） | `[exited with code 0]`（命令正常完成，`;ls` 照跑） |
| C3 | 对照C（不经 Claude Code） | `/bin/zsh -c 'sleep 40; echo done'` 外部 TERM 杀 | 标准 rc=**143** |

语义结论：

- **TERM 杀「zsh 包装层」→ Claude Code 恒记 144（E1/E2/E3 三次一致）**；纯 sleep 也「得到 144」→ **144 不含「程序自身失败」信息，只标志「该后台命令的包装 shell 被 SIGTERM 终止」**。
- **C2 关键推论**：若只杀 zstd（子进程）而 zsh 包装活着，命令记录 0（尾部 `; ls` 与 `&& pwd` 照常成功）——**现场记录 144 反推「zsh 包装层确实被杀」，与 land 的 `kill 39145 39142`（两杀）完全自洽**。
- **144 ≠ 128+16**：`kill -16`(SIGURG) 根本不能终止该进程树（E3 前段）；普通 zsh 标准码是 143（C3）；`kill -9` 记 1（C1）。144 是 Claude Code 平台层记录值，不能按「信号 16/SIGSTKFLT」解读。
- **「timeout 命令/系统看门狗杀」假设不成立**：现场命令原文无 `timeout` 包装（取证点 1）；通知的 `failed` 是 Claude Code 对非零码的统一标签（E1-E3 的 sleep 实验同样被标 failed）；真正终止者是有 PID、有确认输出的人工（agent）`kill` 命令（取证点 4）。

## 3. 时间线（北京时间，全部有转录时间戳）

| 时刻 | 事件 | 出处 |
|---|---|---|
| 10-04 00:03:06 | long31 启动（调研 agent 后台任务 bnk2j3j9s；zstd pid 39145 / zsh pid 39142） | 调研转录 L262/L263 |
| 00:34:43 | 主控派 land 收口任务；任务书原文：「还活着 → **最多再等 15 分钟**（每 3 分钟看一次）…15 分钟没完/进程已死 → **停掉残留进程**再定稿。停之前必须先核 PPID 属主链」 | land 转录 L0 |
| 00:35:30 | land 开工确认：进程存活，产物 152MB | `/tmp/agent-progress-r2-slim-land.md` |
| 00:43:41 / 00:46:42 / 00:49:42 | 轮询三拍：189,849,600 → 197,877,760 → 210,857,984 B | land 转录 L104 |
| 00:49:53 | land 判定「远超 15 分钟窗口。按任务要求停掉」 | land 转录 L107 |
| 00:49:54 | 核 PPID 链（zstd→zsh→claude 会话） | land 转录 L109 |
| **00:50:06.060** | **`kill 39145 39142`（SIGTERM）发出** | land 转录 L113 |
| **00:50:06.577** | **调研 agent 收到通知：failed, exit code 144（kill 后 0.5 秒）** | 调研转录 L288 |
| 00:50:08 | land 确认进程已死（产物定格 211,386,368 B） | land 转录 L114 |
| 00:50:14 | 调研 agent 读 output（仅 `[exited with code 144]`）→ 判「失败」 | 调研转录 L289-294 |
| 00:56:32 | land commit `2ce49542a`（→main 口径「按任务书限时窗口停掉」） | `git show 2ce49542a` |
| 00:57:57 | 调研 agent commit `ac2d7d21a`（→分支草稿口径「exit 144 运行失败」） | `git show ac2d7d21a` |

**窗口边界核对**：kill 时刻 00:50:06；距 land 派单（00:34:43）= 15 分 23 秒，距 land 开工确认（00:35:30）= 14 分 36 秒 ⇒ **终止恰好落在「最多再等 15 分钟」限时窗口的边界**。

> 任务书口径说明：调研任务书（调研转录 L0 硬约束原文）**含「不 kill 进程」**（原文：「不删任何 R2 对象、不上传、不改本机 `data/`、不 `secret put`、**不 kill 进程**」），不含任何「限时」；「限时窗口 + 停掉残留进程」的授权只在 **land 收口任务书**（00:34:43）。两 agent 各自尽职，分歧来自视角：land 有权停且执行了停；调研被停且只看到 144 记录。

## 4. 产物完好性（支持「压缩本身没有失败」）

- 文件：`/tmp/mac_backups_20261001_long31.tar.zst`，211,386,368 B，mtime 10-04 00:49（仍现存）。
- 魔数：`28b52ffd`（合法 zstd 帧头）。
- `zstd -t --long=31` → `Read error (39) : premature end`（**流被提早切断的形态**，非结构损坏；帧头可解析出 window size 2147483648 = long=31 配置一致）。
- 解码冒烟：`zstd -d --long=31 -c … | head -c 1024 | xxd` → 解出正确 tar 头 `mac-backups-20261001/`（mode 000755、size 字段…）——**211MB 里是已验证可解的压缩数据**。
- 崩溃报告核查：`/Library/Logs/DiagnosticReports`（含 Retired）与 `~/Library/Logs/DiagnosticReports` **无 zstd 崩溃记录**（10-04 前后）。
- 综合：产物 = 「正常压缩流被中途 SIGTERM 切断的合法前缀」。支持「压缩本身没失败，是运行被主动终止」。

## 5. 反证检查（主动找反对证据的结果）

| 反证方向 | 查找结果 | 裁决 |
|---|---|---|
| zstd 自身报错 | output 文件 24B 内无任何错误文本；崩溃报告无记录 | 不支持「运行失败」 |
| 「failed/error」字样 | 仅平台通知的 `failed` 标签——E1-E3 的 sleep 实验同样被标 failed | 该标签不含失败信息 |
| 「timeout reached, stopping」字样 | 无；现场无 timeout 命令/看门狗 | 不支持「timeout 机制」 |
| 时序检验 | 终止出现在「15 分钟边界 + kill 命令后 0.5 秒」 | 只有「被 kill」能解释 |
| 「144 是信号 16 所杀」 | kill -16 不能终止进程；普通 zsh TERM=143 | 否定 |

**未发现任何支持「A = zstd 运行失败」的独立证据**；「failed exit 144」全部出处可回溯为「该后台命令被 SIGTERM 终止」的平台记录。

## 6. 两版叙事评价（供主控/用户拍板参考）

- main 现行「按任务书限时窗口停掉」：**事实正确**（land 任务书原文 + kill 命令原文 + 时间窗吻合，三证齐全）。严格说「任务书」指 land 收口任务书。
- 分支草稿「运行失败（exit 144）」：**归因不准确，但现象记录真实**——它作为被终止方只看到自己的后台任务收到 failed/144 通知；且其任务书明令「不 kill 进程」；它当时也未做归因调查。
- 终版措辞（可选，供迁移时用，非本报告强制建议）：「long31 未跑完，按限时窗口主动停掉（执行方记录 exit 144——Claude Code 对被 SIGTERM 终止的后台任务的记录码，非运行失败）」。

## 7. 复现命令（全部可重跑）

```bash
# ① 现场 output（文件若未被 /private/tmp 清理仍在）
stat -f "%N size=%z mtime=%Sm" /private/tmp/claude-501/-Users-linhuichen-code-trade/3ba5f717-05ed-4419-abe0-6426872cd686/tasks/bnk2j3j9s.output
xxd /private/tmp/claude-501/-Users-linhuichen-code-trade/3ba5f717-05ed-4419-abe0-6426872cd686/tasks/bnk2j3j9s.output
# ② 产物完好性
ls -la /tmp/mac_backups_20261001_long31.tar.zst     # 211,386,368 B
zstd -t --long=31 /tmp/mac_backups_20261001_long31.tar.zst   # → premature end（预期）
zstd -d --long=31 -c /tmp/mac_backups_20261001_long31.tar.zst | head -c 1024 | xxd  # → tar 头
# ③ 144 语义复现（任一 Claude Code 会话；后台起 time sleep 500，再在另一 shell：kill <sleep_pid> <zsh包装pid>）
#    读对应 tasks/<id>.output → [exited with code 144]
# ④ 转录证据（只读）
#    调研转录：.../3ba5f717-.../subagents/agent-ad8cfa7e6d1d82182.jsonl（L262 启动 / L288 通知 / L289-294 判读）
#    land 转录：.../3ba5f717-.../subagents/agent-a6e41f0e4fff47165.jsonl（L107-114 kill / L119-123 报告改写）
```

## 8. 诚实标注

1. 本报告只读：未改动任何现场文件（bnk2j3j9s.output / long31 产物 / 任何既有报告）；新增仅本文件与 §2 复现实验在 /tmp 的临时文件（实验后台任务均已终止）。
2. 144 的平台内部机制（为何是 144 而非 143）未深挖——Claude Code 为编译分发、机制层未公开；本报告给的是**行为层可复现事实**（同机同版本 4 次），足以定论归因，但不声称内部换算逻辑。
3. 复现实验在「同机、同 Claude Code 版本 2.1.274、同 shell 快照机制」下完成；未跨 OS/版本交叉验证。
4. 未重跑那次 long31 压缩本身（仅验证产物前缀可解）；结论不依赖压缩能否最终跑完。
5. 时间戳均为北京时间（转录 UTC 已换算）。
