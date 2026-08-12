# 上下文加载/token 浪费优化方向调研(2026-08-12)

> 触发:用户"上下文加载不合理其实也是token浪费的一种 今天做了智能规范和经验过错的调整。你再看看 是否还存在其他可优化的方向 可以往上调研看看别人的方法是否可以得到新的启发?"
> 调研 agent:af905cdf019a9a427(researcher)。**本调研目的不只省 token:上下文过多会稀释真正问题的权重、降低回答质量(context rot),优化是保质量+省钱双目标**(用户 2026-08-12 强调)。
> 数据报告:/tmp/context-optimization-report.json(JSON 已校验)。相关现状:docs/role-based-context-research.md(角色分上下文方案)。

## 〇、关键前置说明(诚实标注)
"按角色分上下文"方案方向正确已落地,但节省幅度没有原报告 §4.4 预估的大。原预估子 agent 降到 ~10.5-11.5K token(省 63-66%),实测每个子 agent 实际启动注入 **~17.7-21.5K token**——漏算两笔:**MEMORY.md 全量索引 19.8KB(≈6.9K token)仍全量注入每个子 agent**(官方机制,子 agent 无法排除)+ **根 CLAUDE.md 是 24.4KB(≈8.5K token)而非预估 ~8K**。拆分前每子 agent ≈37.7K,拆分后 ~18-21K,**实省约 43-53%,不是 63-66%**。

两个最重要的新发现:
1. **MEMORY.md 是每个子 agent 都在买单的低相关全量注入**(每会话前 200 行全载,无排除通道)
2. **主会话编排开销(token 大头)不在子 agent 启动,而在主会话 56% 的轮询+转发 turn**

## 一、本项目现状量化盘点(全部实测)
| 项 | 实测值 | 说明 |
|---|---|---|
| 根 CLAUDE.md | 24,434B / 194 行 | 官方 <200 行红线内;§18 索引表占 9,493B(38.9%)、§23 占 4,783B(19.6%)、§5 占 2,522B(10.3%) |
| docs/main-governance.md | 32,791B / 194 行 | 主控按需读,子 agent 不读(✅ 已到位) |
| 4 个 role skill | implementer 14.7KB / researcher 7KB / reviewer 5.9KB / tester 4.4KB | implementer 最大 |
| **MEMORY.md** | **92 行 / 19,812B(平均 219B/行,最长 403B)** | **官方机制:每会话前 200 行全载;实证:子 agent 收到全量** |
| memory 目录 | 89 个 md / 201KB | 仅 MEMORY.md 索引被注入,主题文件按需读 |
| **主会话 transcript** | **c09b549e 2 天 85.6MB;纯文本 user 消息 1540 条 = cron 轮询 496(32%)+ SendMessage 转发 365(24%)= 56% 编排开销** | 历史最大 34b81f6c 212MB;全部 session jsonl 351.8MB |
| cron 现状 | 5 个常驻;每 agent 派发期瞬态 15min 轮询 | 2 天 496 次轮询 turn |
| hooks | UserPromptSubmit+Stop → feishu_chat_hook.py,真 0 token;补扫已解决中间段漏抄 | 无 PreToolUse/SubagentStop 等 hook |
| 每子 agent 启动注入 | implementer ~21.5K / researcher ~18.7K / reviewer ~18.4K / tester ~17.7K token | 按 0.35 token/KB 折算 |

## 二、优化方向清单(按优先级:现状/做法/预估节省/风险)
### P0
**OPT-1 轮询/编排降本** —— 主会话 56% turn 是编排开销(2 天 496 次轮询),最大单可控项
- 做法:①状态变化才唤醒(cron prompt 门控"进度 mtime 无变化且无 DONE 则零输出直接结束")②夜间/用户离席降频 15min→30-60min ③一次轮询查全部在跑 agent ④演进通知架构(E18 TaskCompleted/SubagentStop hook 待验证)
- 节省:最高(轮询减半≈省主会话输入 token ~16%)风险:中(需保留低频全量兜底)

**OPT-2 MEMORY.md 索引瘦身(最大新发现)** —— 92 行/19.8KB 每会话全载、子 agent 无排除通道
- 做法:按官方模式"索引只留一行一条",描述压到 ~80B/行(删 why 留 how+适用),详情已在 89 个主题文件;目标 19.8KB→~8KB;周 memory review 一并做
- 节省:每子 agent 省 ~4K token,6 子 agent/天+主会话 2 次≈32K token/天,覆盖所有会话无死角;风险:低

### P1
**OPT-3 主会话 /clear 分会话 + Compact Instructions(用户强调核心)** —— 上下文过多会稀释问题权重、降低回答质量(context rot)
- 现状:c09b549e 2 天 85.6MB,抽样已见多次 "ran out of context" compact;社区证据:长会话超 ~100-150K token 推理质量下降,compaction 在最差时点总结最易忘约束
- 做法:主控每完成一个工作流 `/clear`+`/rename` 分会话(官方 best practice);根 CLAUDE.md 或 governance 加 `# Compact instructions` 节(明确 compact 保留什么:修改文件清单/测试命令/在跑 agent 状态);监控主会话大小超 ~40MB 提醒分会话
- 节省:中-高(消掉已压缩旧内容再被读、提 adherence 防重犯;质量收益 > token 收益)

**OPT-6 日总结 agent 读当天 jsonl 限制** —— 改为只读 system-reminder/compact 摘要/进度文件 DONE 结论,或先 grep 提取关键行,不读 85MB jsonl 分片

### P2
- **OPT-4 根 CLAUDE.md §18 索引表压缩**:9.5KB(38.9%)→4-5KB(表格紧凑单行,经验索引移 governance),每会话省 ~1.8K token
- **OPT-5 PreToolUse hook 过滤大工具输出**(Governor 技术,官方 costs 页推荐):对已知噪音命令截断去重,重型 grep 可省 10-30% turn token;风险中(截断丢数据→阈值保守)
- **OPT-7 文档过度 Read**:quickstart 33KB+smoke-checklist 39KB 按需 Read,派活引用具体小节
- **OPT-8 子 agent 模型分档**:简单只读任务可指定 haiku(官方建议),复杂实施留 inherit

## 三、明确推荐"先做这 3 项"
1. **OPT-2 MEMORY.md 索引瘦身**(P0)——零风险、全覆盖、每子 agent+每主会话都立刻省 ~4-6K token;唯一"全量注入但高比例低相关"的机制级残留,与角色拆分目标同源
2. **OPT-1 轮询/编排降本**(P0)——数据证明主会话 56% turn 是编排开销,这是 token 大头;状态变化门控+夜间降频成本低
3. **OPT-3 主会话 /clear 分会话 + Compact Instructions**(P1)——2 天 85MB transcript 已有 context-rot 风险,官方+社区双重背书;**同时把"compact 保留什么"固化成规范,防重犯体系受益;用户强调的核心目的=保回答质量(问题权重不被大量上下文稀释),非仅省钱**

## 四、调研来源
- 官方文档(镜像 ddobon/mirror-claude-code-docs):memory.md(前 200 行全载/claudeMdExcludes/@import)、costs.md(Reduce token usage 专节/PreToolUse hook 过滤)、how-claude-code-works.md(auto-compact//context/子 agent 隔离)、best-practices.md(bloated CLAUDE.md 降低遵循度//clear 频繁用/kitchen-sink 反模式)、sub-agents.md(skills 全文注入)、features-overview.md(hooks=Zero)
- 社区:Governor(工具输出过滤/记忆压缩)、Unclog(JSONL 审计每 agent/skill/MCP token 成本)、PrismoDev(找 token 浪费)、HN 48275853(compaction amnesia and context rot)、agents.md(AGENTS.md 嵌套就近)、bito.ai blog(精简 codebase 上下文降 token 47%)
