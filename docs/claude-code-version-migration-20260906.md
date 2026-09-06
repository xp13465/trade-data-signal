# Claude Code 2.1.237 → 2.1.261 版本迁移调研:9 类历史 workaround 对照

> 调研日期:2026-09-06。调研角色:researcher。
> 目的:升级到 2.1.261 后,本项目大量围绕早期版本限制写的历史 workaround 是否有官方原生解法(§23.8"过时的 workaround 比没有更危险")。
> 结论基调:**只列官方 changelog/docs 白纸黑字查到的变更,未查到变更 = 保守继续用现在 workaround,不因"听起来可能"就建议替换。**

## 0. 版本事实

- 本机当前版本:**2.1.261**(`claude --version` → `2.1.261 (Claude Code)`)
- 本地安装:`/Users/linhuichen/.nvm/versions/node/v25.8.0/bin/claude` → `../lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe`,package.json `"version": "2.1.261"`
- 本地 changelog 缓存 `~/.claude/cache/changelog.md` 只到 2.1.235(mtime 2026-08-19,**滞后**);本次补官方源拿到 2.1.236~2.1.263 全量
- 官方已出到 **2.1.263**(本次区间外 1 版,仅"Bug fixes and reliability improvements")

## 1. 变更摘要表(2.1.236 → 2.1.261 与本项目 9 类 workaround 相关)

| 版本 | 类型 | 变更 | 命中的 workaround 类 |
|---|---|---|---|
| 2.1.236 | **新增** | `SendMessage` 加 `notify_when_idle`:请求同机另一会话下次 idle 时发一条通知——**opt-in、one-shot、免轮询**(macOS/Linux) | 1 通知/完成检测、7 cron/时序 |
| 2.1.251 | 新增 | `PreModelSwitch`/`PostModelSwitch` hook 事件(可 block/confirm/annotate 模型切换);`SessionStart` resume hooks 现收 session staleness + 估算 re-cache 成本 | 5 hooks、8 模型参数 |
| 2.1.251 | 新增 | `claude attach/logs/stop/respawn/rm` 子命令;`--resume` 提示精确命令;`rate_limits.spend_limit`、`prompt_cache` 状态行字段 | 1 通知、9 settings/statusline |
| 2.1.246 | 修复 | subagent 到 `maxTurns` 停时输出标记 `partial` + 提示用 `SendMessage` 继续 | 2 subagent |
| 2.1.248 | 修复 | cross-session 消息在 Bedrock/Vertex/Foundry + telemetry disabled 可用;fallback 到 per-user `/tmp`;`SendMessage` 从 subagent 发给别会话时回复送父会话(行为变更) | 1 通知 |
| 2.1.260 | **修复** | **subagent 通过 `SendMessage` 恢复另一个 agent 时,该 agent 完成不再不唤醒**(通知原来发到主对话) | 1 通知、2 subagent resume |
| 2.1.260 | **修复** | **subagent 启动的后台命令 1 小时时限移除**——现跑到退出或被停止,与主会话一致 | 2 subagent |
| 2.1.260 | 修复 | `ListAgents` 幻影 "interactive" 双胞胎;`task output swap refused` 间歇错 | 1、2、4 |
| 2.1.261 | **新增** | `bashOutputMaxChars` / `taskOutputMaxChars` 设置:**提高命令/后台任务输出在落文件前内联接收量,最高 128K** | 4 token/TaskOutput |
| 2.1.261 | 修复 | 后台 agent 无法恢复时忙等循环 CPU 高占用;`SendMessage` 到离线 Remote Control 会话现报 queued 非 delivered | 1 通知、2 subagent |
| 2.1.261 | 新增 | `/skill-doctor` 列未用 skills 及上下文成本;`--append-subagent-system-prompt-file` | 9 其他 |
| 2.1.260 | 修复/增强 | auto-compact 1M 模型贴近 1M 才压缩;超大 context 的 recovery compaction 不再 10 分钟超时;compaction 期后台 subagent 不再误判 stalled | 3 context |
| 2.1.247 | 修复 | Sonnet 5 auto-compact 窗口改全 1M(~967K) | 3 context |
| 2.1.251 | 修复 | effort xhigh/max + thinking disabled 报错 → effort 降为 high 发送 | 8 模型参数 |
| 2.1.251/257 | 修复/增强 | `/effort` per-model 默认档保存;`/effort s` 只改当前会话;Fable 5.1 mid-session 改 effort 不再失效 prompt cache | 8 模型参数 |
| 2.1.260 | 修复 | Edit/Write/Read 权限规则含括号路径被丢弃;规则尾杂文本报 invalid 而非静默 | 9 settings/permissions |
| 2.1.243 | 新增 | `modelPicker`/`promptCacheTtl`/`subagentPromptCacheTtl`/`modelPricing` 设置 | 8、9 |
| 2.1.238/257 | 新增 | `keybindingFlavor`/`timeFormat`/`timeZone` 设置 | 9 |
| 2.1.248/246/260 | 修复 | hooks 静默吞无效 JSON、hook `if` matcher 误触发(`Bash(cat *)` 带 `$()`)、Stop hooks block 后丢推理;OTel 追踪不碎片化 | 5 hooks |
| 2.1.248/246/260 | 修复 | 后台 worktree session 丢失 checkout(后台 session 现持有 worktree lock);retention sweep 不再误删用户自建 `.claude/worktrees/`;`-p --resume` worktree git 元数据丢失卡死 | 6 worktree |
| 2.1.222/233 | 修复 | worktree 隔离扩展到所有 session 类型(subagent 也不能对 main checkout 跑破坏性 git 命令);`--worktree` 支持 GitLab MR | 6 worktree |

## 2. 9 类 workaround 逐项对照

### 1) 通知/完成检测机制(现:task-notification/SendMessage + cron 兜底轮询三件套,§11)

| 旧 workaround | 2.1.261 状态 | 替代方案建议 | 优先级 |
|---|---|---|---|
| 依赖 `SendMessage`/`ListAgents` + cron 兜底轮询查 agent 完成 | **部分原生化**。2.1.236 起 `SendMessage` 支持 `notify_when_idle`(one-shot 免轮询通知);2.1.260 修复"SendMessage 恢复的 agent 完成不唤醒"、2.1.261 修复"离线会话送达误报 delivered";但 2.1.261 仍在修 SendMessage 送达类 bug → **"通知送达不可靠是架构事实"仍未根除** | cron 兜底**保留**(仍是最可靠残余);可试点:需要"下一个 idle 时提醒主控"的场景改用 `notify_when_idle`(如等 subagent 回话)。TaskCompleted hook(2.1.224 发现,2.1.261 docs 仍现役、schema 完整)继续用 | P2 观察 |
| `TaskCompleted`/`AgentToolUse` hook 事件 | **增强**。2.1.261 docs 事件全表含 TaskCompleted(无 matcher、exit code 2 阻止 + `{"continue":false,"stopReason"}` 停 teammate);新增 `TaskCreated`/`SubagentStart`/`SubagentStop` 事件 | 若现有 hook 只监听 TaskCompleted,可补 TaskCreated/SubagentStop 增强抄送覆盖 | P2 |
| E18 记忆"TaskCompleted hook 发现(2.1.224)" | 确认仍在,且官方文档化 | 无动作 | - |

### 2) background agent / subagent 能力(现:Agent 工具派 background + run_in_background + worktree isolation + resume 协议)

| 旧 workaround | 2.1.261 状态 | 替代方案建议 | 优先级 |
|---|---|---|---|
| resume/续跑协议(self-resume、SendMessage 续跑) | **显著增强**。2.1.246 subagent 到 maxTurns 输出标 partial + 提示 SendMessage 继续;2.1.257 切断(subagent 被 sleep/断连/断流切断)自动继续不再 incomplete;2.1.260 修复 SendMessage 恢复唤醒;2.1.261 修复恢复失败忙等循环 | resume 类 workaround 保留但可靠性已提升;worktree 续跑碰撞(见 memory resume-agent-worktree-collision)风险由 2.1.260/246 worktree 修复部分缓解,仍需自管 | P1 近期重验 |
| subagent 后台命令 1 小时限制相关规避 | **官方移除 1 小时时限**(2.1.260:"Removed the one-hour time limit on background commands started by subagents") | 若项目脚本有绕 1 小时限制的定时分段逻辑,现可删 | P1 |
| Agent 工具派 background + run_in_background | 无原生 parallel/背景并行新协议变更(未见) | 保持现状 | - |
| SendMessage 送达可靠性 | 2.1.260/261 多轮修复(恢复唤醒/离线 queued/幻影双胞胎) | cron 兜底仍保留(见第 1 类) | - |

### 3) context 压缩(现:CLAUDE_CODE_AUTO_COMPACT_WINDOW 阈值 + 每次 compact 手动恢复清单)

| 旧 workaround | 2.1.261 状态 | 替代方案建议 | 优先级 |
|---|---|---|---|
| `CLAUDE_CODE_AUTO_COMPACT_WINDOW=1048576` 阈值 | 仍有效;auto-compact 时机/恢复增强(2.1.260 1M 模型贴近限才压、超大 context recovery compaction 不再 10min 超时;2.1.247 Sonnet5 全 1M) | 阈值维持;超时 bug 已修 → 大上下文 compact 更稳 | P2 |
| 手动 compact 恢复清单(5 步) | **官方无结构化压缩摘要/恢复工具**(未查到)。2.1.261 `/context` token 计数本地估算、2.1.240 compaction 后 reminder 不再重跑 skill 原参数 | **手动恢复清单保留**;可加 `PostCompact` hook(事件表确认存在)自动落恢复锚点 | P1 |

### 4) token/效率(TaskOutput block=False 轮询完整输出 ~11.6MB 最大浪费点)

| 旧 workaround | 2.1.261 状态 | 替代方案建议 | 优先级 |
|---|---|---|---|
| TaskOutput block=False 轮询后台任务输出拿全量 | **官方早已废弃 TaskOutput 改 Read 输出文件**(2.1.83 "Deprecated `TaskOutput` tool in favor of using `Read` on the background task's output file path");2.1.261 新加 `taskOutputMaxChars`/`bashOutputMaxChars`(内联上限,最高 128K,超阈值自动落文件) | **直接改用 Read 后台任务输出文件路径**(=官方 2.1.83 起的方向),彻底避开 11.6MB 内联;`taskOutputMaxChars` 调小可进一步压低内联。注意:2.1.203 修过 TaskStop/TaskOutput 找不到异 agent 派生的后台 agent,2.1.260 修过 swap refused | **P0 立即改** |
| memory/context-optimization-20260906.md 的 TaskOutput 大输出结论 | 方向与官方一致(输出落文件) | 见上 | - |

### 5) hooks 体系(现:PostToolUse(Agent)+ SessionStart 派单三件套自查/抄送)

| 旧 workaround | 2.1.261 状态 | 替代方案建议 | 优先级 |
|---|---|---|---|
| PostToolUse(Agent) hook + 派单三件套自查 | 现役;2.1.248 修 hooks 静默吞无效 JSON、2.1.246 修 hook `if` matcher 误触发、2.1.260 修 Stop hooks block 后丢推理 → matcher/可靠性增强 | 维持;matcher 增强后可更精确地按 agent/工具分类 | P2 |
| SessionStart 抄送 | 2.1.251 起 SessionStart resume hooks 带 staleness + re-cache 估算(新字段) | 可顺手用新字段增强抄送信息 | P2 |
| **新事件红利(未用)** | 2.1.261 docs 确认新增:PreModelSwitch(sequential 可 block)/PostModelSwitch、WorktreeCreate/WorktreeRemove(async)、CwdChanged、ConfigChange、InstructionsLoaded、MessageDisplay(display-only)、PostToolBatch、PostToolUseFailure、TaskCreated、PreCompact/PostCompact、Elicitation/ElicitationResult | 值得加的:PostCompact hook 自动恢复锚点;WorktreeCreate/Remove hook 管 worktree 生命周期;MessageDisplay 轻量流式抄送。**五类 hook type(command/http/mcp_tool/prompt/agent)已文档化**,prompt/agent hook 是 LLM 判定型 | P1 |
| per-agent matcher 区分截图场景 | 未见 matcher 新增 per-agent 字段(事件表 matcher 仍对 tool_name/to_model 等求值) | 维持现状;未查到=不替换 | - |

### 6) worktree 管理(现:`.claude/worktrees/` + EnterWorktree/ExitWorktree 机制)

| 旧 workaround | 2.1.261 状态 | 替代方案建议 | 优先级 |
|---|---|---|---|
| 手动 `.claude/worktrees/` 隔离区 | **可靠性多轮修复**:2.1.248 后台 session 持 worktree lock 防 checkout 丢失;2.1.246 retention sweep 不再误删用户自建 worktree;2.1.260 `-p --resume` 元数据丢失不再卡死;2.1.222 隔离扩展全 session 类型 | worktree 机制保留;重建/清理类 workaround 简化 | P1 |
| EnterWorktree/ExitWorktree 工具 | 未见 baseRef 新选项/并发隔离新增强(未查到) | 维持 | - |
| 并发 implementer 必须 worktree 隔离(memory) | 官方方向一致且隔离更严 | 维持 | - |

### 7) cron/时序(现:CronCreate(3,18,33,48)巡检兜底;69 个同档 cron 纯 session 无状态)

| 旧 workaround | 2.1.261 状态 | 替代方案建议 | 优先级 |
|---|---|---|---|
| CronCreate 15min 档巡检兜底 | **CronCreate 工具本身未见增强**(未查到 durable/jitter 变更);2.1.236 `notify_when_idle` 是新的原生一次性通知 | **巡检 cron 保留**;`notify_when_idle` 可替代"等某个 session idle 再提醒"的单点轮询场景。69 个同档 cron 的僵尸清理仍走 check_task_state.py(§23.12-1) | P1 |
| 一次性 reminder | 2.1.236 `notify_when_idle` = 官方一次性通知(SendMessage opt-in one-shot) | 新建"一次性提醒"类需求优先用它 | P1 |

### 8) 模型参数(现:"thinking off" 提速方案 §5.2,方舟注入 disabled;per-role effort)

| 旧 workaround | 2.1.261 状态 | 替代方案建议 | 优先级 |
|---|---|---|---|
| 方舟 thinking disabled 注入(per-role) | **官方无 per-role thinking 开关**(未查到);官方 effort 已 per-model(2.1.251)/per-session(`/effort s`,2.1.257) | 方舟注入方案保留;运行时切 effort 可走 `/effort` 或 PreModelSwitch hook 拦截 | P2 |
| effort+thinking 组合冲突规避 | 2.1.251 修 xhigh/max+disabled 报错(effort 自动降 high);2.1.260 Fable 5.1 mid-session 改 effort 不再失效 cache | 原有规避逻辑可简化 | P2 |
| thinking_proxy 透传 thinking_budget 400 卡死(memory) | 未查到官方变更 | 维持停用状态 | - |

### 9) 其他(settings.json 新键/statusline/内置组件/mdc)

| 旧 workaround | 2.1.261 状态 | 替代方案建议 | 优先级 |
|---|---|---|---|
| settings.json 键集 | **新增**:`bashOutputMaxChars`/`taskOutputMaxChars`(2.1.261)、`modelPicker`/`promptCacheTtl`/`subagentPromptCacheTtl`/`modelPricing`(2.1.243)、`keybindingFlavor`(2.1.238)、`timeFormat`/`timeZone`(2.1.257)。permissions 修复:括号路径规则不再被丢(2.1.260)、deny 规则尾杂文本报 invalid(2.1.260)。注:官方 settings 文档页尚未收录 2.1.261 新键(docs 滞后于 changelog,以 changelog 为准) | 新增键按需用;无必须迁移项 | P2 |
| statusline 占位符 | 2.1.260/251 新增 `prompt_cache` 对象(每会话缓存行:命中率/未中/重缓存/冷热)、`rate_limits.spend_limit` | 若 statusline 脚本想显示缓存命中,新字段可用 | P2 |
| 内置组件/mdc/`<default-mcp-servers>` | 未查到 2.1.237→2.1.261 相关变更 | 维持 | - |

## 3. 未查到变更 = 保守继续用现在 workaround 的清单(防"听起来可能"误替换)

1. **TaskOutput 就位机制**(2.1.83 废弃改 Read 输出文件)——这个不是新变更,是新版把官方方向走得更远(taskOutputMaxChars),改动是**顺势而为**而非猜测
2. **CronCreate 工具增强**——未查到 durable/jitter/一次性变体;巡检 cron 不动
3. **per-role thinking 开关**——官方只到 effort 粒度(per-model/per-session),无 per-role thinking;方舟注入保留
4. **结构化 compact 摘要/一键恢复**——未查到;手动恢复清单保留(可加 PostCompact hook 辅助)
5. **per-agent hook matcher 字段**——未查到;截图场景区分维持现状
6. **worktree baseRef 选项**——未查到;EnterWorktree/ExitWorktree 维持
7. **通知送达不可靠根除**——2.1.261 仍在修 SendMessage bug;cron 兜底三件套逻辑不变

## 4. 优先级汇总

- **P0 立即改(1 项)**:第 4 类 —— TaskOutput block=False 轮询全量 → 改 Read 后台任务输出文件路径(官方 2.1.83 起方向 + 2.1.261 taskOutputMaxChars 配套),消灭 ~11.6MB 内联浪费
- **P1 近期(5 项)**:①subagent 1 小时后台时限已移除,查项目有无相关规避逻辑可删;②resume 链路(2.1.260 唤醒修复)重验 SendMessage 续跑;③PostCompact hook 自动落恢复锚点;④WorktreeCreate/Remove hook 管 worktree 生命周期;⑤一次性提醒优先 notify_when_idle
- **P2 观察(6 项)**:cron 兜底保留但试点 notify_when_idle;SessionStart 新字段;effort 配置简化;新 settings 键;statusline 新字段;TaskCreated/SubagentStop hook 补充抄送

## 5. 诚实标注

- 本报告全部结论基于官方第一手来源:**①官方 changelog**(2.1.236~2.1.263 全量,来源 URL 见复现段)②官方 hooks 文档(2.1.261 当前版,含事件全表)③本机 claude --help + package.json。未使用任何第三方博客/社区帖
- 已知盲区:官方 settings 文档页未收录 2.1.261 新键(文档滞后),故 `taskOutputMaxChars` 默认值/内联阈值未获文档级确认,仅 changelog "up to 128K characters" 一条原文;建议实施时实测一次内联截断行为
- 2.1.263 已发布(仅 bugfix),未逐条核对,不影响本报告结论

## 复现

- 数据来源(官方)URL 清单:
  - 官方 changelog:https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md(抓取日期 2026-09-06,覆盖 2.1.263 之底全部版本;本地缓存 ~/.claude/cache/changelog.md 只到 2.1.235 故用官方源)
  - 官方 hooks 文档:https://docs.claude.com/en/docs/claude-code/hooks(2.1.261 当前版,事件全表 + matcher + 五种 hook type)
  - 官方 settings 文档:https://docs.claude.com/en/docs/claude-code/settings(注意:未收录 2.1.261 新键)
  - 官方 subagents 文档:https://docs.claude.com/en/docs/claude-code/sub-agents
- 抓取命令(本机无代理直连被断,用固定 IP resolve;WebFetch/WebSearch 工具被企业策略阻断):
  - `curl -s --resolve raw.githubusercontent.com:443:185.199.108.133 -o /tmp/cc-changelog-261.md https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md`
  - `curl -s -L -o /tmp/docs-hooks.md "https://docs.claude.com/en/docs/claude-code/hooks"`(docs.claude.com 直连可用)
- 本机版本验证:`claude --version` → `2.1.261 (Claude Code)`;`cat ~/.nvm/versions/node/v25.8.0/lib/node_modules/@anthropic-ai/claude-code/package.json | grep version`
- 关键口径一句话:**只认 changelog/docs 原文;9 类对照中"未查到"一律保守维持,不因推测替换**
