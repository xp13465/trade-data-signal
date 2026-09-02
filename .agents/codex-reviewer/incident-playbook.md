# Codex Incident Playbook —— 故障剧本

> 用途：新会话开局贴墙上，if X then Y。
> 生效位置：作为 `.agents/codex-reviewer/SKILL.md` 的子规范引用。
> 状态：草案，跑 2 周后定稿。

## P0 级故障（立即阻断干活）

### P0-1：429 / 额度耗尽
- **判断**：codex exec 报错 429 或"quota exceeded"
- **动作**：不改模型。watcher 已有 60s x 10 次自动重试，等 watcher 接手。
- **禁止**：手动改模型指向 zai/zai-small-32k 等付费模型
- **后续**：等 openrouter/free 每日重置（通常 UTC 0 点），或等用户充值

### P0-2：主会话完全不可用（网络/权限/崩溃）
- **判断**：当前会话 hang 住、无法响应
- **动作**：不重复发同一请求。新建会话，引用本 playbook 继续。
- **后续**：人工检查 launchd 服务状态

## P1 级故障（影响效率但不阻断）

### P1-1：守护进程失效
- **判断**：`launchctl list com.trade.agent-inbox-watcher` 无输出或报错
- **动作**：
  1. `cd /Users/linhuichen/code/trade && python3 scripts/agent_inbox_watcher.py &`
  2. 临时前台启动确认能跑
  3. 重新加载 launchd plist
- **检查项**：`tail -20 .../logs/agent_inbox_watcher_launchd.log` 看最后一行

### P1-2：重复接单（同一 request 触发多次）
- **判断**：codex-inbox 里出现两个 `*.ready` 或 `*.processing`
- **动作**：
  1. `ls /tmp/codex-reports/signals/codex-inbox/*.processing` 找残留
  2. 杀掉当前 running job 的 proc（`kill <pid>`）
  3. 清掉 processing 文件：`mv *.processing *.invalid`
  4. 重试

### P1-3：报告 schema 不通过
- **判断**：`python3 -c "import json; json.load(open(...))"` 报错
- **动作**：
  1. 检查 `request_id` 是否一致
  2. 重写 `.tmp` 再 `mv`
  3. 再跑一次 `codex_review_complete.py`

## P2 级故障（低频异常）

### P2-1：base/head 误判（改动了不该审的范围）
- **判断**：git diff base..head 包含无关文件
- **动作**：
  1. 必跑 `git merge-base base head`
  2. 确认基线后重跑 `git diff`
  3. 在 report 里明确注明实际审了哪些文件

### P2-2：trace/verifier 缺字段（finding 不合格）
- **判断**：finding 没有 `diff_range` + `linkage` 或没有 `command` + `expected`
- **动作**：退回补全。格式见 review-rubric.md 规则 1/2。
- **放宽点**（2026-09-01）：回测/口径判断类 finding 允许降级描述，不强制现场重跑几小时。

### P2-3：openrouter/free 路由到付费模型
- **判断**：日志出现 zai/zai-small-32k 或 glm-5.3-flash 等付费路径
- **动作**：固化 `openrouter/free`，不加任何模型 override
- **后续**：等用户充值后解封调整

## 日常自检清单（每次新会话开始）

```
1. git for-each-ref refs/codex/req -> 有无 pending request
2. launchctl list com.trade.agent-inbox-watcher -> 守护进程活着?
3. tail -5 .../logs/agent_inbox_watcher_launchd.log -> 最后一行时间戳
4. ls /tmp/codex-reports/signals/codex-inbox/*.processing -> 有无残留
5. model 检查：当前会话是否用 openrouter/free
```
