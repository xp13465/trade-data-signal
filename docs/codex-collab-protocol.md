# Codex 外部 Review 协议

> 2026-08-24 定。Codex 作为外部只读 tester/reviewer，不 commit、不 push、不改源码。

## 角色

| 角色 | 职责 | 权限 |
|---|---|---|
| Claude 主控 | 调度 implementer/reviewer/tester；生成 request；读取 report | 完整读写 |
| Codex | 只读审查：影响面 grep、smoke 验证、交叉验证 | `.git/` 只读 + `/tmp/` 写 |

## 流程

```
Claude implementer 完成 → 内部 reviewer PASS
→ Claude 主控调 scripts/codex-review-request.sh 生成 request ref + codex-inbox signal
→ agent_inbox_watcher 唤醒 Codex（无信号时零 token 空闲）
→ Codex 读 refs/codex/req/<id> → 执行 review → 原子写 /tmp/codex-reports/<id>.json
→ Codex 调 scripts/codex_review_complete.py 写 claude-inbox signal
→ watcher 只做报告 schema 机检 + 飞书提醒（不后台调用 Claude）
→ Claude 下次开工消费 validated signal → 处置 findings
→ 双方都 PASS → 主控走 scripts/main-merge.sh 合并
```

## Ref 命名

```text
refs/codex/req/<request_id>    # Claude → Codex 请求
refs/codex/resp/<request_id>   # 可选：Codex 报告的 SHA 指针（由 Claude 代写）
/tmp/codex-reports/signals/codex-inbox/<request_id>.ready   # Claude → Codex 唤醒信号
/tmp/codex-reports/signals/claude-inbox/<request_id>.ready  # Codex → Claude 回传信号
```

- `<request_id>` 格式：`rev-YYYYMMDD-NNN` 或 `test-NNN`。
- 处理完成后可保留用于审计，也可 `git update-ref -d` 清理。

## Request JSON Schema

```json
{
  "request_id": "rev-20260824-001",
  "timestamp": "2026-08-24T20:00:00+08:00",
  "status": "pending",
  "repo": "/Users/linhuichen/code/trade",
  "base": "main",
  "head": "worktree-agent-xxx",
  "task_type": "review",
  "change_class": "B",
  "requirement": "用户要求修复XXX",
  "focus_areas": ["数据一致性", "公示同步", "P0 smoke"],
  "internal_reviewer_verdict": "PASS",
  "notes": ""
}
```

必填字段：`request_id`, `repo`, `base`, `head`, `task_type`, `requirement`, `status`。

`status` 取值：`pending`（待处理）/ `processing`（Codex 已开工，可自行推进）/ `completed`（已出报告）。**git 层机制**：git ref 本身无时间戳、无状态标记、内容不可变，请求生命周期只能靠 `status` 字段表达。**协议层约定**：req ref 的 `status` 字段只读不更新，消费态一律以 resp ref（refs/codex/resp/<id>）为准。

## Report JSON Schema

```json
{
  "request_id": "rev-20260824-001",
  "verdict": "PASS",
  "summary": "改动影响面已覆盖",
  "issues": [
    {
      "severity": "P1",
      "title": "标题",
      "path": "path/to/file.py:123",
      "impact": "影响",
      "why": "根因",
      "fix": "修复建议",
      "trace": {
        "diff_range": "哪个 commit/行/文件（必填）",
        "linkage": "与本次需求如何关联：满足/不满足/uncertain（必填）",
        "user_request": "user 原话引用，或 N/A + origin=reviewer_own（见下）",
        "origin": "in-diff | pre-existing | uncertain | reviewer_own"
      },
      "verifier": {
        "command": "可复现命令或可观察现象（必填）",
        "expected": "通过时应该看到什么（必填）",
        "observed": "实际看到什么（必填）"
      }
    }
  ],
  "impact_surface": ["P0-01 KPI角标"],
  "smoke_results": {"P0-01": "OK"},
  "recommendation": "可合入 main"
}
```

必填字段：`request_id`, `verdict`, `summary`, `issues`, `impact_surface`, `smoke_results`, `recommendation`。

`verdict` 取值：`PASS` / `FAIL` / `BLOCKED`。

## 逐条 finding 质量标准：trace + verifier 字段（2026-09-01 采纳 Karpathy Skills 放宽版）

> 采纳来源：`docs/codex-reviews/karpathy-skills-evaluation-20260901.md`（用户 2026-09-01 拍板采纳放宽版）。目的：把 review 报告水分砍掉一大截——从「标来源」升级为「可追溯 + 可验证复现」。**不动 ref/信号/生命周期/原子写通道机制，只加 per-finding 字段定义。**

### 规则1 `trace` 字段：每条 finding 必须能追溯
每条 issue 必须带 `trace`，三子字段：
- `diff_range`（**必填**）：定位到哪个 commit / 行 / 文件，让实施方能直接跳到。
- `linkage`（**必填**）：与本次需求如何关联，取值 `满足` / `不满足` / `uncertain`。
- `user_request`：引用 user 原话；**允许填 `N/A` + `"origin": "reviewer_own"`**，用于「reviewer 独立主动挖出的项目深层问题」（这类本就无对应 user 原话，如「queries.py 连接没 finally 关」）。
- **放宽点**：只对「声称与本次需求相关」的 finding 强制追溯 `user_request`；`reviewer_own` 类放行但**必须显式标注**，不许用 `in-diff|pre-existing` 把这类好 finding 压没。

### 规则2 `verifier` 字段：每条 finding 必须可验证
每条 issue 必须带 `verifier`，三子字段：
- `command`（**必填**）：可复现命令或可观察现象。
- `expected`（**必填**）：通过时应该看到什么。
- `observed`（**必填**）：实际看到什么。
- **放宽点**：对「回测/口径判断类」finding，`command` 允许填「重跑 XXX 回测脚本 + 预期口径」，不强制当场真跑几小时回测；或降级为「给口径依据」（`command: "口径依据:..."`）。
- **禁止**：只说「逻辑有问题」不带任何 `command` / 现象——那不算 finding。

## 写入与清理规范（2026-08-24 补，来源：外部 reviewer codex 回馈）

> 背景：报告文件 `/tmp/codex-reports/<id>.json` 有两个误读源——①半成品（Codex 还在写，读方拿到截断 JSON；report.sh 的 json.load 已天然防御）②**同 id 重跑时旧完整报告残留**（ref 已立但报告是上一轮的旧结果，完整可解析，最危险）。

- **① Codex 报告必须原子写**：先写 `<id>.json.tmp`，写完再 `mv <id>.json.tmp <id>.json` rename 过去；杜绝读方读到半成品。
- **② Claude 发 request 前脚本自动清场**：`codex-review-request.sh` 在写 ref 之前先 `rm -f /tmp/codex-reports/<id>.json`——保证「ref 出现」时绝无旧报告残留。
- **③ 可选闭环标记 consumed**：Claude 读到报告并采纳后，`git update-ref refs/codex/resp/<id> $(git hash-object -w --stdin < 报告内容)` 标记已消费，防同一轮被重复读取/重复采纳。
- **④ 过期清理**：ref 与报告文件建议保留 7 天，由 Claude 主控负责清理（`git update-ref -d` + 删文件）。
- **⑤ 信号生命周期**：`.ready` 只表示待消费；watcher 先 rename 成 `.processing`，成功转
  `.done`，失败转 `.failed`。信号名必须是 `[A-Za-z0-9][A-Za-z0-9_.-]{0,127}`，内容只是元数据，
  不承载可执行 prompt。watcher 用固定指令调用 CLI，禁止把信号内容拼进模型指令。
- **⑥ 安全自动桥**：`scripts/agent_inbox_watcher.py` 只在需要协作时由用户手动启动；
  2 秒本地 stat 轮询，空闲不调用 LLM。Codex 侧用 workspace-write + 可写
  `/tmp/codex-reports`，不用免审批模式。Claude 回传侧只做 schema 机检与飞书提醒，
  不允许后台 watcher 直接以高权限唤醒 Claude 处置代码。`com.trade.agent-inbox.plist`
  仅是可选本机模板，默认不入 LaunchAgents。
- **⑦ Reviewer 模型继承（2026-08-27 补）**：watcher 派发 `codex exec` 时必须显式传
  `-m <model>`，避免子进程因运行环境或 CLI 默认值漂移到另一个模型。模型解析顺序：
  ① `CODEX_REVIEWER_MODEL` 显式覆盖；② 近 7 天内当前仓库最新 `thread_source=user`
  的 Codex Desktop session 元数据中 `provenance.model`；③ `~/.codex/config.toml`
  的顶层 `model`；④ 最终硬编码兜底。这套规则让外部 reviewer 跟随“当前主会话”
  模型，而不是每次改脚本固定值。测试入口：
  `python3 -m unittest discover -s scripts -p 'test_model_inherit_dispatch.py'`。

## 约束

- Codex 不写 `.git/`，不 commit，不 push。
- Codex 报告写到 `/tmp/codex-reports/<request_id>.json`。
- Claude 主控负责清理过期 ref 和报告文件（建议保留 7 天）。
- P0 smoke fail = BLOCKED；P1 = FAIL（主控判断是否阻断）；P2/P3 = 记录不阻断。
- 同 id 重跑必须换新 id，或确认旧报告已清（脚本②已自动清场）；禁止依赖残留报告当本次结果。
