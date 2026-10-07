# 子 agent「收工自清后台任务」规则可行性验证(只读取证)

- 日期:2026-10-07 | 执行:researcher agent(只读,零外发,**未 commit**)| 前提报告:`docs/ops/agent-zombie-pattern-20261007.md`
- 收工自查:本 agent 转录**真实后台化事件 = 0**(判据:工具结果起始签名 `Command did not complete within its` 计数 0;裸 grep `moved to the background (ID:` 命中的 4 个 ID 全是本报告分析期间打印的他人样本,非本 agent 事件)。无残留后台任务(本 agent 无 TaskStop 工具,若有只能声明)
- **一句话结论:原规则不能按原文直接写进 4 个 role skill——四个 role agent(implementer/researcher/reviewer/tester)的运行时工具清单都没有 `TaskStop`(声明逐字 + 114 份子转录运行时核对,双证),写了=死规则。但「先给 role agent frontmatter 挂 TaskStop、再做 1 次冒烟、然后写 skill」经二进制级取证**可行且安全**;报告所称唯一「成功实证」`aefbc4d3e7ced1236` 是 **general-purpose**(内置全能 agent,非 role agent),不能代表 role agent。—— 与 memory `agent-zombie-parked-background-child` 中「可行性验证中,勿先写死」的状态一致,本报告给出验证结论。**

## 0. 结论表(TL;DR)

| # | 问题 | 结论 | 关键证据 |
|---|---|---|---|
| 1 | 4 个 role agent 有没有 TaskStop | **4/4 都没有**(声明与运行时均无) | §1:`*.md:4` 逐字 + 114 份子转录 `prompt_snapshot.tools` 全量分组 |
| 2 | 唯一成功自清的 agent 是什么类型 | **general-purpose**(非 role agent)⇒「role agent 能自清」不成立 | §2:launch 参数 `subagent_type='general-purpose'` + 全会话 112 例 role agent 0 次 TaskStop |
| 3 | 子 agent 能否拿到自己的转录 | **能**(2 条通路,本机以「我是子 agent」实测) | §3:session-id 通配 + 唯一 token 自证 |
| 4 | 给 role agent 挂 TaskStop 是否可行/安全 | **可行且安全**:只能停自己名下任务,停不了主控/他人/自己 | §4:harness 二进制反混淆源码 `xce`/`yNn` + 两 bundle 双处取证 |
| 5 | 该条能否落 role skill | **不能直接落;先挂 TaskStop(8 处小改)+ 1 次冒烟,再落**;并保留主控兜底 + 源头减量 | §5 方案 1-4 排序 |

## 1. Q1 工具可得性(逐字引用 + 运行时双证)

### 1.1 `.claude/agents/*.md` 的 `tools` 字段(逐字)

| 文件:行 | 逐字内容 | TaskStop |
|---|---|---|
| `.claude/agents/implementer.md:4` | `tools: Read, Edit, Write, Bash, WebFetch, WebSearch, NotebookEdit` | 无 |
| `.claude/agents/researcher.md:4` | `tools: Read, Bash, WebFetch, WebSearch` | 无 |
| `.claude/agents/reviewer.md:4` | `tools: Read, Bash, WebFetch, WebSearch` | 无 |
| `.claude/agents/tester.md:4` | `tools: Read, Bash, WebFetch, WebSearch` | 无 |

### 1.2 运行时工具集核对(不是只看定义):114 份子转录 `prompt_snapshot.attachment.tools` 全量分组

会话 `d08c47ab-19eb-44fb-85c4-4b62d4809072` 内全部 114 个 agent 的转录目录 `~/.claude/projects/-Users-linhuichen-code-trade/d08c47ab-…/subagents/`,逐份取首段 `prompt_snapshot` 的工具清单:

| agentType | 例数 | 运行时工具清单(逐字) | 有 TaskStop? |
|---|---|---|---|
| implementer | 42+2+1(见注) | `[Read, Edit, Write, Bash, WebFetch, WebSearch, NotebookEdit]`(2 例尾部多 1 个 harness 内部工具 `SubagentHandback`;1 例启动即止无快照) | **否** |
| researcher | 18+1+1 | `[Read, Bash, WebFetch, WebSearch]`(+`SubagentHandback` 1 例;启动即止 1 例) | **否** |
| reviewer | 34+3 | `[Read, Bash, WebFetch, WebSearch]`(+`SubagentHandback` 3 例) | **否** |
| tester | 10 | `[Read, Bash, WebFetch, WebSearch]` | **否** |
| **general-purpose** | 2 | `[Agent, Bash, Edit, EnterWorktree, ExitWorktree, NotebookEdit, Read, SendMessage, Skill, **TaskStop**, WebFetch, WebSearch, Write]` | **是** |

结论:运行时工具集 = `.md` 声明逐项映射;role agent 共 112 例的清单里 **TaskStop 出现 0 次**;含 TaskStop 的只有 2 例 general-purpose。`SubagentHandback` 是 harness 内部附加(近段派发的部分 agent 才有,来源未深究,不影响结论)。

### 1.3 运行时确实按清单裁剪(反证,防「声明了没用」疑云)

- reviewer `aa1efa05fb78e5b8b` 转录第 274 行:调 Write 工具得 `<tool_use_error>Error: No such tool available: Write. Write is disabled for this session, in subagents as well as here.</tool_use_error>`;同会话 implementer 侧 Write 成功结果 194 条(例:`agent-a009e6519afe86978.jsonl` 第 78 行 `File created successfully at: …`)。
- ⇒ 缺工具会以 `No such tool available` 硬失败:若把现行规则原文写进 skill,role agent 执行 `TaskStop(...)` 必得同款报错,规则作废(可能还带坏「照做即成功」的信任)。

## 2. Q2 那 1 例成功实证的 agent 类型 = general-purpose(关键判定)

- 报告 `docs/ops/agent-zombie-pattern-20261007.md:165`(§9.2)称 `aefbc4d3e7ced1236` 成功执行 `TaskStop`。
- 主转录 launch 记录(`d08c47ab-…jsonl:1129`)逐字:Agent 工具 input = `{description:"Git 分支大扫除", subagent_type:"general-purpose", run_in_background:true}`;紧随 `:1130` toolUseResult.agentId = `aefbc4d3e7ced1236`。
- 其转录 `subagents/agent-aefbc4d3e7ced1236.jsonl` 逐行:`:232` thinking / `:233` tool_use `TaskStop {"task_id":"bzzkavjzj"}`(2026-10-05T06:23:24.666Z)/ `:234` tool_result `{"message":"Successfully stopped task: bzzkavjzj (git fetch --prune origin 2>&1 | tail -20)","task_type":"local_bash",…}`。
  - 诚实标注:其 `:232` thinking 原文是「Let me stop my background fetch and test connectivity.」(fetch 挂住→停掉重试),**是"能力实证"不是"收工自清"的行为先例**。
- 全会话普查(114 例):role agent 112 例 **实际 TaskStop 执行 0 次**;general-purpose 2 例中 1 例调用(上述 aefbc)、另 1 例(`a8d2b033252c42a52`,清理陈旧 worktree)有工具但 0 次调用。
- 端到端正面证据(自清有效):aefbc 自清后,其完成通知走**正常文案**(主转录 `:1477`,2026-10-05T06:40:00Z,note=「A task-notification fires each time this agent stops with no live background children of its own.」)= 未进停放、未被标僵尸。
- ⇒ **判定:原报告把 general-purpose 的实证泛化为「子 agent 能自清」;对 4 个 role agent 不成立**。24 例僵尸中 role agent 0 例自清(原报告一致),现状是「role agent 无工具 × 认知缺口」双重原因,不是单纯认知缺口。

## 3. Q3 转录可达性 = 能(两条通路,本机以「我是子 agent」实测)

### 3.1 环境与约定路径

- 环境变量(本次调研 agent 自身 env 实测):`CLAUDE_CODE_SESSION_ID=d08c47ab-19eb-44fb-85c4-4b62d4809072`(与父会话同值);无 `CLAUDE_AGENT_ID` 类变量。
- worktree 型 agent 与主树 agent **共用同一 sessionId**(逐份核对 48 个 worktree agent 转录 top-level `sessionId` 字段,全部同值),且其转录**也落在主仓 slug 目录**(`worktree cwd ≠ 转录位置`,所以**不能拿 cwd 推 slug**——那 48 例 cwd 都在 `.claude/worktrees/agent-<id>`,转录却在 `-Users-linhuichen-code-trade/…/subagents/`)。
- 约定路径:`~/.claude/projects/<proj-slug>/<session-id>/subagents/agent-<agentId>.jsonl`(本会话在册 114 份,另有同名 `.meta.json` 含 agentType/description)。

### 3.2 通路 A:session-id 通配(一次命中全部)

```bash
ls ~/.claude/projects/*/$CLAUDE_CODE_SESSION_ID/subagents/agent-*.jsonl
# 本机实测:命中 114 份(不含 slug 段也可,透过会话 ID 全局唯一)
```

### 3.3 通路 B:唯一 token 自证「哪份是我」(两步,注意 flush 时机)

```bash
# 第 1 步(单独一次工具调用):生成并打印唯一 token
TOKEN="selftok-$RANDOM-$RANDOM-$RANDOM"; echo "$TOKEN"
# 第 2 步(下一次工具调用):grep 该 token,唯一命中即自己的转录
grep -l "selftok-…" ~/.claude/projects/*/$CLAUDE_CODE_SESSION_ID/subagents/*.jsonl
```

- 本机实测:第 2 步唯一命中 `agent-aa78c2f154510d04b.jsonl`(= 本调研 agent 自身),且文件运行期实时写入。
- 注意:token 与 grep **必须分两次工具调用**——同一次命令内 grep 会先于转录落盘执行(实测 exit=1 无命中);跨调用即可命中。
- 之后 `grep -o 'moved to the background (ID: [a-z0-9]*' <自己转录>` 列全部后台任务 ID。

### 3.4 主控把路径注入 prompt 的通路评估

- 主控在 launch **之后**才从 toolUseResult 拿到 agentId(`:1130`),预置 prompt 里写不了确切路径 ⇒ 无需依赖此通路;skill 里给「自证通路 B」即可。(SendMessage 补发在 worktree 隔离下有不可达记录,不作依赖。)

### 3.5 补充:后台 ID 本身就在 agent 自己的上下文里

自动转后台的工具结果原文(转录实测样本):

```
Command did not complete within its 420s timeout and was moved to the background (ID: bgp9t133o). Output is being written to: /private/tmp/claude-501/-Users-linhuichen-code-trade/<session>/tasks/bgp9t133o.output.
```

⇒ 「转录 grep」是**防遗忘/防上下文压缩**的兜底,不是唯一来源(agent 当时就看见了 ID)。token 超时值多样(120/180/420s…),勿写死。

## 4. Q4 给 role agent 挂 TaskStop:可行 + 安全(二进制级权限边界)

### 4.1 可行性

- frontmatter `tools:` → 运行时工具集精确映射(§1.2,114 份实证);`TaskStop` 在子 agent 命名空间可正常注册/执行(aefbc 实证,§2)。
- 冒烟验证法(挂完必做,方法已跑通):派 1 个 agent,读其 `prompt_snapshot.tools` 是否含 `TaskStop`(同 §1.2 的读法)。

### 4.2 权限边界(harness v2.1.274 反混淆源码,两 bundle 同逻辑)

TaskStop 工具 call 传 `callerAgentId:Jne(h)`、`killedBy:"parent"`;核心 kill 例程 `xce` 与所有权谓词:

```js
function yNn(e,t){if(e===void 0)return!0;return e===t}      // e=callerAgentId, t=task 的 owner agentId
// xce 内两道门:
if(J!==void 0&&J===be.agentId) throw …`Observer ${Me} cannot stop itself; use the task UI or a main-session TaskStop.` // 防自杀(local_agent)
if(!yNn(J,be.agentId)) throw …`Task ${Me} is owned by ${…}; agent ${…} cannot stop it.`                              // 防越权
```

| 语义 | 规则 | 备注 |
|---|---|---|
| 主会话(caller 无 agentId) | 可停任意任务 | 谓词 `e===void 0 → true` |
| 子 agent | **只能停 owner == 自己 agentId 的任务**(自己名下 Bash 后台等) | 停父/兄弟/别人的任务 = `not_owner` 硬拒 |
| 子 agent 停「自己那条 agent 记录」 | **被拒**(`cannot stop itself`) | 防误用,子 agent 自毁只能走主控/Task UI |
| 任务已结束/不存在 | 回 `Task X is not running (status: …)`(errorCode 3) | 良性,收工清单里可直接忽略继续 |
| 工具别名 | `KillShell` / `KillBash` | a71ca 案里它说的「KillShell 不在我列表」即此工具 |

⇒ 结论:挂 TaskStop **不会**给 role agent 越权能力(只能停自己名下任务);与「收工自清自己留下的后台任务」用途 1:1 对齐。

### 4.3 残余风险(低)与对策

- (a) 声明名写错/上游改工具名 → 挂后 1 次冒烟(§4.1)。
- (b) agent 提前停掉自己仍需的长任务 → 靠 skill 措辞限定「仅收工阶段执行」。
- (c) 未来 harness 升级改语义 → 按原报告 §6 的「二进制 grep 3 秒判行为是否变化」流程顺带复查(§5.2 精神)。

## 5. Q5 落地方案(按根治程度 + 成本排序)与推荐

| 方案 | 内容 | 成本 | 根治度/备注 |
|---|---|---|---|
| **1(推荐主路径)** | **4 个 role agent 挂 TaskStop(每个 .md 改 1 行)+ 4 个 role skill 落可执行三步收工清单**(见下) | 8 处文本小改 + 1 次冒烟 + 常规 reviewer/§0 | 根治「能力缺口」;需先挂再写,否则死规则 |
| 2(零改动,立即可用) | 主控侧兜底 SOP 固化:带僵尸备注的通知≠完成;在册 completed 且转录 mtime 冻结 ≥20min → 主控主动 TaskStop | 纯 SOP 文本 | 主控有全权 TaskStop 且已有成功先例(主转录 `:11004` 停 a71ca);兜住方案 1 漏网 |
| 3(源头减量,已在做) | 派单纪律:>60s 必带 timeout、云上 nohup 化、禁 `find /`/无白名单 `grep -r`;§0.2 hook 已把「prompt 含 timeout 约束」做成机检项 | 已有 | 唯一「少产生僵尸」的手段;覆盖不了「本以为很快」的命令 |
| 4(不建议主路径) | hook 兜底:harness 有 `SubagentStop` 事件(二进制出现 54 次),hook input schema 含 `agent_id`/`transcript_path`;但 hook 是 shell 进程,**调不了进程内 TaskStop**,只能 ps 匹配杀 OS 进程(脆弱:任务 output 文件无 pid) | 高 | 原报告 §9.4 亦评估「不建议复杂 hook」 |

**推荐的 skill 三步收工清单(方案 1 用,措辞可直接采用)**:

1. **自查**:列出本次出现过 `moved to the background (ID:`(或显式 `run_in_background`)的任务 ID;遗忘/上下文被压缩时,用自证通路(§3.3 两步命令)找到自己转录再 `grep -o 'moved to the background (ID: [a-z0-9]*'`。
2. **自清**:对每个 ID `TaskStop(task_id="…")` 逐个停;返回「not running」= 任务已自己结束,忽略即可。
3. **声明**:确实清不掉的,报告首行写 `残留后台任务: <ID> <命令>`,交主控收尾。

**顺序建议**:先落 1 的挂工具(小改,独立可验)→ 冒烟(§4.1)→ 再写 2 的 skill 文本;2/3 并行照旧。单独任一条都不完整(1 需冒烟;2 依赖主控注意力;3 覆盖不了意外慢命令)。

## 6. 证据索引(可复核锚点)

| 证据 | 位置 |
|---|---|
| 4 个 role agent 声明无 TaskStop | `.claude/agents/{implementer,researcher,reviewer,tester}.md` 第 4 行 |
| 运行时工具集全量(114 例分组) | `~/.claude/projects/-Users-linhuichen-code-trade/d08c47ab-19eb-44fb-85c4-4b62d4809072/subagents/*.jsonl` 每份首段 `prompt_snapshot.attachment.tools` |
| 缺工具硬失败反证 | `subagents/agent-aa1efa05fb78e5b8b.jsonl:274`(No such tool available: Write) |
| 唯一自清实例 launch 参数 | 主转录 `d08c47ab-…jsonl:1129-1130`(`subagent_type:"general-purpose"`) |
| 唯一自清实例 TaskStop 三行 | `subagents/agent-aefbc4d3e7ced1236.jsonl:232(thinking)/233(tool_use)/234(成功结果)`;md5=a0a2cea9fa77f8714e8ced1fb1a2a272 |
| 自清后端到端正常驱逐 | 主转录 `:1477`(正常文案「no live background children」,06:40:00Z) |
| 主控侧成功 TaskStop 先例 | 主转录 `:11004`(停 a71ca5848fa5936de) |
| TaskStop 权限源码 | claude.exe v2.1.274:工具代码 offset 182098909;kill 例程 `xce` offset 181836032;`yNn` offset 179946139;「cannot stop itself」两 bundle offset 72591946 / 181836558 |
| 原规则原文与实证引述 | `docs/ops/agent-zombie-pattern-20261007.md:162`(派单固化句)/`:165-167`(§9.2) |

## 7. 复现命令(全部只读)

```bash
PROJ=~/.claude/projects/-Users-linhuichen-code-trade; SID=d08c47ab-19eb-44fb-85c4-4b62d4809072

# ① role agent 声明
grep -n '^tools:' /Users/linhuichen/code/trade/.claude/agents/*.md

# ② 运行时工具集分组(逐份取 prompt_snapshot 的 tools 名列表,按 .meta.json 的 agentType 聚合)
python3 - <<'PY'
import json,glob,os
from collections import defaultdict
D=os.path.expanduser('~/.claude/projects/-Users-linhuichen-code-trade/d08c47ab-19eb-44fb-85c4-4b62d4809072/subagents/')
comb=defaultdict(list)
for f in sorted(glob.glob(D+'agent-*.jsonl')):
    aid=os.path.basename(f)[6:-6]; typ=None; tools=None
    mp=D+'agent-'+aid+'.meta.json'
    if os.path.exists(mp): typ=json.load(open(mp)).get('agentType')
    for i,line in enumerate(open(f,errors='replace')):
        if i>300: break
        if 'prompt_snapshot' not in line: continue
        try: d=json.loads(line)
        except: continue
        a=d.get('attachment',{})
        if a.get('type')=='prompt_snapshot' and a.get('tools'):
            tools=tuple(x.get('name') for x in a['tools']); break
    comb[(typ,tools)].append(aid)
for k,v in comb.items(): print(len(v),k)
PY

# ③ 唯一自清实例(三行 + 结果)
F=$PROJ/$SID/subagents/agent-aefbc4d3e7ced1236.jsonl; sed -n '232,234p' "$F" | cut -c1-300

# ④ 权限源码(二进制 grep)
B=/Users/linhuichen/.nvm/versions/node/v25.8.0/lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe
python3 - <<'PY'
import re
d=open('/Users/linhuichen/.nvm/versions/node/v25.8.0/lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe','rb').read().decode('utf-8','replace')
for k in ['function xce(','function yNn(e,t){if(e===void 0)','cannot stop itself']:
    print(k,[m.start() for m in re.finditer(re.escape(k),d)][:4])
PY

# ⑤ 自证转录(通路 B,两步分两次调用)
TOKEN="selftok-$RANDOM-$RANDOM-$RANDOM"; echo "$TOKEN"
# 下一次调用:
grep -l "selftok-…" $PROJ/*/$SID/subagents/*.jsonl
```

## 8. 诚实标注 / 未实测项

1. **「挂 TaskStop 后 role agent 实际调用成功」未实测**——现状没有任何 role agent 有该工具,唯一子 agent 实例是 general-purpose;故方案 1 落地必须带 1 次冒烟(§4.1)。挂工具本身可逆(改 1 行)。
2. worktree agent 的 Bash 环境是否含 `CLAUDE_CODE_SESSION_ID` 未逐例实测(以「同一 harness 进程共享 env + 其 bash 子进程继承」推断);通路 A/B 的 glob 去掉 session 段也可用(`$PROJ/*/*/subagents/…`),防御性更强。
3. 「僵尸率」分母口径等边界沿用原报告 §5/§附 的诚实标注,本报告未扩展样本(只覆盖本项目 d08c47ab 会话 + 该会话 114 例;其他会话/项目未扫)。
4. 本报告为纯取证产物,**不 commit**,交主控决定后续动作。
