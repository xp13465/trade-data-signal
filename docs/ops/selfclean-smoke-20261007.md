# 冒烟实测:role agent 挂 TaskStop 后能否自清后台任务(2026-10-07)

**结论:PASS / FAIL — FAIL(role 子 agent 自清不可行)**

- 一句话:四个 role agent frontmatter 里新挂的 `TaskStop` **没有被投放进子 agent 的可用工具清单**(实测该 tester 子 agent 上下文只有 4 个工具:Read/Bash/WebFetch/WebSearch),调用一律报 `No such tool available: TaskStop. TaskStop is disabled for this session, in subagents as well as here.`;而**同一会话的主线程**今天实测两次 TaskStop 调用**成功**(见 §E3),说明不是"整个会话禁用",是**子 agent 拿不到**。
- **残留后台任务:无**。实测期间产生 2 个被 harness 转后台的任务,最终都以"已完成"收尾:`bbiidip9z`(sleep 200)由 Bash 层 `kill -TERM` 清掉、`bisdpum2a`(只读 grep)自己跑完;无存活进程、无未收尾任务(证据见 §E4)。第 2 步的后台 ID 拿到后 TaskStop 失败 ⇒ 按派单要求首行声明本条。

---

## 五步原始输出(逐字)

### 步骤 1:证明工具可用(调 `TaskStop(task_id="__nonexistent_probe__")`)

调用 1(原文):
```
<tool_use_error>Error: No such tool available: TaskStop. TaskStop is disabled for this session, in subagents as well as here.</tool_use_error>
```
调用 2(复现,原文一致):
```
<tool_use_error>Error: No such tool available: TaskStop. TaskStop is disabled for this session, in subagents as well as here.</tool_use_error>
```
⚠️ 与派单预期不符:预期是「任务不存在/not running」类良性报错,实际是**工具根本不在清单里**。本项目历史里确实存在那种良性报错格式(见 §E3),两者形态不同。

对照探针 `TaskOutput`(原文):
```
<tool_use_error>Error: No such tool available: TaskOutput. TaskOutput is not available inside subagents. Complete the task with the tools provided and return findings to the orchestrator.</tool_use_error>
```
两个报错措辞不同(TaskStop 走的是"会话/上下文没这个工具"的通用文案分支,TaskOutput 走的是"子 agent 侧明确禁用"分支)。

### 步骤 2:制造后台化(`sleep 200`,故意不传 timeout)

命令:
```
echo "$(date '+%F %T') step2 start sleep 200 (no timeout param)" >> /tmp/agent-progress-selfclean-rollout.md; sleep 200; echo "SLEEP-COMPLETED-NORMALLY"
```
harness 返回原文:
```
Command did not complete within its 120s timeout and was moved to the background (ID: bbiidip9z). Output is being written to: /private/tmp/claude-501/-Users-linhuichen-code-trade/d08c47ab-19eb-44fb-85c4-4b62d4809072/tasks/bbiidip9z.output. You will be notified when it completes.
```

### 步骤 3:后台 ID

```
bbiidip9z
```

### 步骤 4:**立刻** TaskStop(ID)

```
<tool_use_error>Error: No such tool available: TaskStop. TaskStop is disabled for this session, in subagents as well as here.</tool_use_error>
```

### 步骤 5:再调一次复验

```
<tool_use_error>Error: No such tool available: TaskStop. TaskStop is disabled for this session, in subagents as well as here.</tool_use_error>
```
(与步骤 4 逐字相同;预期中的 not running 复验无法得到,因为工具不可用。)

---

## 附:实测期间额外跑出来的旁证

### E1 我这个子 agent 的真实工具清单(harness 快照,非推测)

从本人子 agent 转录里的 `prompt_snapshot` attachment 提取(即实际发给模型的工具定义):
```
snapshots with tools in MY transcript: 1
tool count: 4
names: ['Read', 'Bash', 'WebFetch', 'WebSearch']
TaskStop in my tool list: False
```
对照 `.claude/agents/tester.md` 第 4 行(frontmatter,15:09 改过):
```
tools: Read, Bash, WebFetch, WebSearch, TaskStop
```
⇒ **声明了但没投放**。四个工具 = frontmatter 清单**去掉 TaskStop** 后的结果。

### E2 同一会话主线程的工具清单(harness 快照)

同一会话(`d08c47ab-19eb-44fb-85c4-4b62d4809072`)主线程最新 `prompt_snapshot`(2026-10-07T07:11:27Z):
```
tool count: 24
names: ['Agent','AskUserQuestion','Bash','CronCreate','CronDelete','CronList','Edit','EnterPlanMode','EnterWorktree','ExitPlanMode','ExitWorktree','ListAgents','NotebookEdit','Read','ReportFindings','ScheduleWakeup','SendMessage','Skill','TaskOutput','TaskStop','WebFetch','WebSearch','Workflow','Write']
TaskStop -> True
```

### E3 同一会话主线程今天两次 TaskStop 实调成功(证明"不是整个会话禁用")

从主会话转录提取的 tool_result 原文:
```
2026-10-07T00:15:14.639Z  {"message":"Successfully stopped task: a71ca5848fa5936de (P0 CI修复(守卫真bug)独立审)","task_id":"a71ca5848fa5936de","task_type":"local_agent",...}
2026-10-07T07:07:42.767Z  {"message":"Successfully stopped task: a3b88eb70ca4cfc82 (给四个role agent挂TaskStop)","task_id":"a3b88eb70ca4cfc82","task_type":"local_agent",...}
```
历史全量统计(扫 `~/.claude/projects/*/**/*.jsonl`):
```
total TaskStop tool_use across ALL projects: 67 | from subagent sidechain: 0
```
⇒ 67 次 TaskStop 全部来自主线程(isSidechain=False),**零次来自子 agent**;历史良性报错样例(会话 3ba5f717 内):
```
<tool_use_error>Task a027755ff15464f62 is not running (status: completed)</tool_use_error>
```

### E4 残留与收尾核查

- `bisdpum2a`(步骤外的只读 grep,`timeout=180000` 仍被 `180s` 超时转后台;跑完自行结束):
```
[bisdpum2a.output 末尾] [exited with code 0]
```
- `bbiidip9z`(sleep 200,因 TaskStop 不可用无法用工具停;改用 Bash 层进程终止):
```
$ kill -TERM 15141        # sleep 200 的真实 PID;包装 zsh = 15138
$ pgrep -fl "sleep 200"   # → 无输出
$ cat .../tasks/bbiidip9z.output
SLEEP-COMPLETED-NORMALLY
[exited with code 0]
$ ls -la .../tasks/bbiidip9z.output
-rw-r--r-- 1 linhuichen wheel 47 10 7 15:24 .../tasks/bbiidip9z.output
```
harness 随后推送的完成通知:`<task-id>bbiidip9z</task-id> <status>completed</status>`(注:用的是 kill 而不是 TaskStop;`kill -TERM` 后包装脚本继续执行到结尾 echo,故框架侧记为 exit code 0)。最终 `ps` 扫描无 `sleep 200` 残留进程。

### E5 顺带确认的 harness 行为(供规范参考)

- 「不传 timeout」时默认 120s 转后台;传了 `timeout=180000` 的命令是 **180s 后**转后台(即以"生效超时"为阈值,不是固定 120s)。
- 只读 grep 这种命令也会被转后台并留下 task 记录,子 agent 收工时同样需要清理。

---

## 结论与建议(给主控)

1. **本轮改造目标未达成**:`.claude/agents/*.md` frontmatter 挂 `TaskStop` **不足以**让 role agent 自清后台任务。工具在子 agent 上下文里根本不存在(实测清单只有 4 个),harness 报错把它归到"本会话禁用,子 agent 与主线程皆然"的通用文案分支。
2. **已知确凿的部分**:主线程能用(TaskStop 在 23+1 工具清单里,今天两次成功);子 agent 不能用(本人 + 历史 0/67 佐证)。
3. **尚未能区分(留一个 5 分钟复验点)**:子 agent 拿不到 TaskStop,是 `2.1.274` 的**子 agent 硬性禁用**,还是**本会话 agent 定义缓存未重载**(改文件 15:09、会话更早启动)。两者对本轮改造的结论一样(当前形态无效),但若是后者,**新开会话**再挂一次即可验真:新会话里派一个 tester 子 agent,令其调 `TaskStop(task_id="__nonexistent_probe__")` —— 返回 `Task <id> is not running (status: completed)` 类文案 = frontmatter 生效;返回本次的 `No such tool available` = 硬禁用。
4. **可用的兜底(本次已验证)**:子 agent 用 Bash 层进程终止可以清掉自己名下被转后台的任务(`pgrep -fl "<命令特征>"` 找 PID → `kill -TERM <pid>`),效果等于清理,且 harness 会把该 task 记为 completed。缺点:要按命令特征匹配 PID,不如 TaskStop 精确。
5. **现状风险提示**:子 agent 若在收工前遗留被转后台的长命令,当前**没有任何工具手段**自行停掉(只能等其自然结束或靠 Bash 层 kill);派单规范里"子 agent 收工自清"这条在 TaskStop 不可用的前提下**不能按原样落地**。

## 复现命令(本次实测用到的关键命令)

```bash
# 本子 agent 工具清单(harness 快照)
python3 -c "import json;[print([t.get('name') for t in a['tools']]) for a in [d.get('attachment') or {} for d in map(json.loads, filter(lambda l:'\"prompt_snapshot\"' in l, open('/Users/linhuichen/.claude/projects/-Users-linhuichen-code-trade/d08c47ab-19eb-44fb-85c4-4b62d4809072/subagents/agent-a26be3037dc138150.jsonl')))] if a.get('tools')]"
# 主会话工具清单 + 历史 TaskStop 调用统计(命令全文见本文件 §E2/§E3 对应扫描脚本)
```
