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
→ Claude 主控调 scripts/codex-review-request.sh 生成 request ref
→ 通知 Codex（用户转达 / cron 轮询）
→ Codex 读 refs/codex/req/<id> → 执行 review → 写 /tmp/codex-reports/<id>.json
→ Claude 主控调 scripts/codex-review-report.sh 校验并读结果
→ 双方都 PASS → 主控走 scripts/main-merge.sh 合并
```

## Ref 命名

```text
refs/codex/req/<request_id>    # Claude → Codex 请求
refs/codex/resp/<request_id>   # 可选：Codex 报告的 SHA 指针（由 Claude 代写）
```

- `<request_id>` 格式：`rev-YYYYMMDD-NNN` 或 `test-NNN`。
- 处理完成后可保留用于审计，也可 `git update-ref -d` 清理。

## Request JSON Schema

```json
{
  "request_id": "rev-20260824-001",
  "timestamp": "2026-08-24T20:00:00+08:00",
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

必填字段：`request_id`, `repo`, `base`, `head`, `task_type`, `requirement`。

## Report JSON Schema

```json
{
  "request_id": "rev-20260824-001",
  "verdict": "PASS",
  "summary": "改动影响面已覆盖",
  "issues": [],
  "impact_surface": ["P0-01 KPI角标"],
  "smoke_results": {"P0-01": "OK"},
  "recommendation": "可合入 main"
}
```

必填字段：`request_id`, `verdict`, `summary`, `issues`, `impact_surface`, `smoke_results`, `recommendation`。

`verdict` 取值：`PASS` / `FAIL` / `BLOCKED`。

## 约束

- Codex 不写 `.git/`，不 commit，不 push。
- Codex 报告写到 `/tmp/codex-reports/<request_id>.json`。
- Claude 主控负责清理过期 ref 和报告文件（建议保留 7 天）。
- P0 smoke fail = BLOCKED；P1 = FAIL（主控判断是否阻断）；P2/P3 = 记录不阻断。
