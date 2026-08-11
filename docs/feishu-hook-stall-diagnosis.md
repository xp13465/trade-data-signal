# 飞书 hooks 抄送停止诊断报告（2026-08-12）

## 结论（一句话根因）

**根因 = commit `e79c23d69`（"子agent会话不抄送"修复）判定条件错误**：
该修复用 `CLAUDE_CODE_CHILD_SESSION == "1"` 判断"子 agent 会话"，但**实测 Claude Code 2.1.224 给主控会话的 hook 子进程也注入 `CLAUDE_CODE_CHILD_SESSION=1`**（`AI_AGENT=claude-code_2-1-224_harness`）。因此修复上线后**主控会话的 hook 也被误判为"子 agent"而直接跳过**，主控话 + 主控回复全部不再抄送飞书。

- 正确区分标志是 **`AI_AGENT`**：主控 hook 子进程=`claude-code_2-1-224_harness`（不跳过），子 agent hook 子进程=`claude-code_2-1-224_agent`（跳过）。
- 修复 agent（a16a949d）当时只查了**主控 claude 进程 env**（无此标志）和自己的 `env -u CLAUDE_CODE_CHILD_SESSION` 手动测试（通过），**没查主控会话 hook 子进程的真实 env**——hook 子进程是被 harness 注入该变量的，与主进程 env 无关。

## 时间线证据

| 时间(+08) | 事件 | 证据 |
|---|---|---|
| 2026-08-11 23:48 | settings.json 写入 hooks（UserPromptSubmit/Stop） | `.claude/settings.json` mtime，2d1b9206e |
| 23:52 ~ 08-12 00:15 | 主控抄送正常，指纹文件持续增长 | `/tmp/feishu_hook_sent.txt` 条目匹配主会话 c09b549e（用户话+assistant 回复均命中） |
| 00:05:51 | **用户报告 bug**："好像现在将子agent的输入也当成我的输入抄送到飞书群了" | 主会话 transcript 该条被抄送（指纹在文件） |
| 00:12~00:15 | 派 hook 修复 agent（首个 a6d2cefe 超时终止，重派 a16a949d） | transcript |
| 00:15:03/00:15:27 | 主会话 compact（compact_boundary x2） | transcript system 记录 |
| 00:15:39 | **主控最后一次真实抄送**（A\|3ae0ef43 = "复核 agent（aabf4c6c）已派…"） | 指纹文件匹配主会话 |
| 00:16:12 / 00:18:03 / 00:18:13 | 修复 agent 依次 Edit：加 instrumentation → 加子agent跳过判定 → 最终版 | agent-a16a949d transcript 的 Edit 时间线 |
| 00:18:57 | 修复 agent **手动自测**写 4 条指纹（U\|56ccc527 / U\|ac627a4d / A\|5bc1940e / U\|e7b5cf68，session=s_main_test2/假transcript，均不匹配主会话）——**这 4 条是自测不是真实抄送** | 指纹文件末尾 4 条 + 修复agent命令 |
| 00:19:28 | commit `e79c23d69` 上线 main | git log |
| 00:19:07 起 | 主控 Stop hook 持续触发（stop_hook_summary 无报错 hookErrors=[]，duration ~1.1s=读77MB transcript），但**不再写任何指纹** | 主会话 transcript system 记录 |
| 00:17:06~00:54 | 主控大量真实用户消息（"待办清单看一下"/"归一化…"/"不应该日均偏离更重要么"/"我的需求和你都沟通讨论完了…"等）**全部未抄送** | 指纹匹配全 MISS |
| 01:10:47 | **诊断 agent 临时加 capture，实测主控 hook 子进程 env**：`child_session=1, ai_agent=claude-code_2-1-224_harness`（User/Stop 两模式均如此） | `/tmp/feishu_hook_capture.log`（本次诊断临时instrumentation，已移除） |
| 01:15 之后 | 指纹文件仍停在 00:18:57（783B，29条），无新写入 | stat |

> 注：00:15:53 一条 assistant（"两个后台事件已处理"）在修复生效前即未抄送，疑为 compact 重写 transcript 期间的偶发读取竞态；但**永久性停摆的确切起点是修复上线后首个 hook（00:19:07）**，且 01:10 实测证明主控 hook env 带 child_session=1，故修复为根因。

## 漏抄消息清单 + 兜底情况

- **漏抄**：主控会话 00:15:53 之后所有用户话 + assistant 回复（保守估计 20+ 条用户消息，含 00:17 待办清单 / 00:35 归一化讨论 / 00:42-00:48 权重/日均偏离 / 00:46"怎么现在的主动通知不工作了" / 00:53 播放按钮需求等）。指纹文件 00:18:57 后零写入。
- **兜底情况**：`feishu_missed_fetch.py` 是**从飞书往本地拉**（listener 漏收补拉），**不反向补抄**——它兜不住"主控→飞书"方向的漏抄。listener（PID 85381）本身 WS 正常，00:06 重启后补拉过一次（无新漏收），后续无漏收。**飞书方向漏抄无兜底，需修复后自然恢复（后续新消息正常抄送，历史漏抄不回补）。**

## 修复方案（具体可执行）

改 `scripts/feishu_chat_hook.py` main() 开头的子 agent 判定：

```python
# 子 agent 会话不抄送。⚠️不能用 CLAUDE_CODE_CHILD_SESSION（主控 hook 子进程也被注入=1）。
# 正确区分：AI_AGENT 后缀（主控 hook=claude-code_2-1-224_harness，子agent hook=claude-code_2-1-224_agent）
if os.environ.get("AI_AGENT", "").endswith("_agent"):
    return 0
```

要点：
1. **只用 `AI_AGENT.endswith("_agent")` 判定子 agent**，主控（`_harness`）不跳过。
2. 保留"任何异常 exit 0"原则不变。
3. 改完按 §9/§21 流程：commit（附 `Co-Authored-By: Claude`）+ push feat + merge main + push main（避开盘后 15:35/16:00/17:50/20:35 push main，深夜安全窗口可）。
4. 上线验证口径：
   - 主控会话发一条 → 指纹文件新增 + 飞书开发群收到（U 条目）。
   - 主控回复一条 → 指纹文件新增 A 条目。
   - 子 agent（派一个调研 agent）→ 不新增指纹、不抄送。
   - `grep -c "CLAUDE_CODE_CHILD_SESSION" scripts/feishu_chat_hook.py` = 0（确认旧判定移除）。

## 防复发

1. **hook/子进程类修复，验证口径必须是"真实 hook 子进程 env"，不是主进程 env 或手动 `env -u` 模拟**——本次教训：修复 agent 只查了主进程 env（干净）+ 手动 unset 测试（通过），漏了 harness 对 hook 子进程的 env 注入。
2. 任何用 env 区分会话角色的判定，先实测两类会话的 hook 子进程 env 全量对比（`ps eww` 主进程 ≠ hook 子进程，二者可能不同）。
3. 上线后**主动向飞书开发群发一条测试消息**确认回显（本次靠用户反馈才发现停摆，缺主动自检）。
4. 可考虑给 hook 加"心跳自检"：指纹文件 mtime 超过阈值（如 30min 无新写入且会话活跃）告警，避免静默停摆。（可选增强）

## 关联文件

- `scripts/feishu_chat_hook.py`（判定在 main() 开头，当前为错误判定，待修）
- `.claude/settings.json`（hooks 配置，无需改）
- `scripts/notify.py` / `config/feishu.json`（发送链路，正常，dry-run 通过）
- 证据留存：`/tmp/feishu_hook_capture.log`（本次诊断 capture 原始记录，含主控 hook 子进程 env 实证）、`/tmp/feishu_chat_hook.py.bak-diag`（诊断前备份，与 commit 一致）

---

## 已修复（2026-08-12）

- **修复方式**：`scripts/feishu_chat_hook.py` main() 开头子 agent 判定由 `CLAUDE_CODE_CHILD_SESSION=="1"` 改为 `os.environ.get("AI_AGENT","").endswith("_agent")`。主控 hook 子进程 `AI_AGENT=claude-code_2-1-224_harness`（不跳，继续抄送）；子 agent hook 子进程 `AI_AGENT=claude-code_2-1-224_agent`（return 0 跳过）。注释同步更新（含"不能用 CHILD_SESSION 判定"防复发警示）。
- **全部入口统一**：`.claude/settings.json` 仅 UserPromptSubmit（user）/Stop（assistant）两入口，均指向同一 `scripts/feishu_chat_hook.py` main()，判定在 mode 分发前，单点修复覆盖全部入口（user/assistant 两模式均已测）。
- **验证结果（自测全过）**：
  1. 单测（monkeypatch _send/_mark_sent 不真发）：①子agent `_agent`→rc=0 无 send；②主控 `_harness`→rc=0 SEND；③无 AI_AGENT→rc=0 SEND（向后兼容）；④assistant 模式子agent→rc=0 无 send。
  2. 真实子进程端到端：子agent env→rc=0 指纹 34→34 无发送；主控 env→rc=0 **真发飞书成功**（notify 日志 "Feishu 已发送至 oc_98a49be…：👤 用户"）指纹 34→35。
  3. 真实 env 证据：本实施 agent（子agent）进程实测 `AI_AGENT=claude-code_2-1-224_agent` + `CLAUDE_CODE_CHILD_SESSION=1`（两变量都在，佐证诊断结论）。
  4. `grep -c CLAUDE_CODE_CHILD_SESSION scripts/feishu_chat_hook.py` = 0（旧判定完全移除）。
- **上线 commit**：`6089f7913`（2026-08-12，commit message `fix(feishu-hook): 抄送停摆修复 — 子agent判定改 AI_AGENT.endswith(_agent)`；本报告同 commit 上线）。
- **兜底补抄**：诊断确认 `feishu_missed_fetch.py` 只做飞书→本地方向补拉，不反向补抄主控→飞书方向漏抄；本次停摆期漏抄（00:15:53 后 20+ 条）**不回补**，修复后新消息自然恢复抄送。
- **待办（未实施，诊断标"可选增强"，需主控确认）**：hook 心跳自检——指纹文件 mtime 超过阈值（如 30min 无新写入且会话活跃）告警，防静默停摆再次发生。本次未擅自扩展实施。
