# Codex 外审 Runbook —— 12 步 checklist

> 用途：每次 Codex 作为执行角色接手外部 review / 专项任务时，按此 checklist 推进。
> 生效位置：作为 `.agents/codex-reviewer/SKILL.md` 的子规范引用（P1 落仓后生效）。
> 状态：草案，跑 2 周后定稿。

## 前置条件（开始干活前必须满足）

1. **确认信号源**：`git for-each-ref refs/codex/req --format='%(refname:short)'`，无 ref 则收工。
2. **校验请求合法**：`git cat-file blob <ref>` 读 request JSON，确认 `status=pending`、`base`、`head`、`focus_areas` 齐全。
3. **锁定基线**：`git merge-base base head` 算出真实对比基线，禁止把"工作区差异"误当成待审范围。
4. **模型确认**：默认 `openrouter/free`，禁止显式指向付费模型（zai/zai-small-32k 等）。429 时靠 watcher 重试，不手动改模型。
5. **进度文件**：建 `/tmp/codex-reports/<id>-progress.md`，每完成一步就打勾。

## 执行阶段（12 步）

| # | 步骤 | 关键动作 | 完成标志 |
|---|---|---|---|
| 1 | 需求对齐 | 逐条读 `focus_areas`，列出本次 review 的覆盖清单 | 清单写入 progress.md |
| 2 | 差异获取 | `git diff base..head`（按文件/按关键字分块） | diff 落盘 |
| 3 | 独立采样 | 随机取 3~5 个命中点，独立复现 | 采样结果落盘 |
| 4 | 数据产物验证 | 跑 check_*.py / 查 JSON / curl 数据层 | 全部 PASS 或写明"未执行" |
| 5 | 浏览器实测 | Playwright 打开首页 + 关键 tab + 移动端 | 截图 + JS error 日志 |
| 6 | 前后端重算对齐 | 取样 signal JSON，逐字段对比前端 replay vs 后端输出 | 差异清单 |
| 7 | 发现分级 | P0/P1/P2/P3 打标，标注 `origin=in-diff|pre-existing|uncertain|reviewer_own` | 分级表 |
| 8 | per-finding 格式化 | 每条 finding 含 `diff_range`、`linkage`、`user_request`、`command`、`expected`、`observed` | 格式校验 |
| 9 | 反幻觉过滤 | 确认每条 finding 有 `path:line` 可复现；机器检查只是线索 | 滤掉 1~2 个疑似误报 |
| 10 | 报告原子写 | 先写 `.tmp` → `mv` 到 `/tmp/codex-reports/<id>.json` | JSON 可解析 |
| 11 | 报告校验 | `python3 -c "import json; json.load(open(...))"` + `request_id` 一致 | 校验通过 |
| 12 | 回传信号 | `python3 scripts/codex_review_complete.py <id> --verdict <PASS|FAIL|BLOCKED>` | `claude-inbox/<id>.ready` 出现 |

## 失败路径

- **429 / 额度耗尽**：不改模型，等 watcher 60s × 10 次自动重试。10 次仍败 → `*.failed`，人工接手。
- **报告 schema 不通过**：检查 `request_id` 一致 + atomic write。重写到 `.tmp` 再 mv。
- **守护进程失效**：`launchctl list | grep agent-inbox-watcher`；检查 `agent_inbox.lock` 与 `*.processing` 残留。
- **重复接单**：检查 lock + processing 残留，清掉再重试。
- **主会话动不了**：仅做只读 review；改源 / 提 PR 抛回主控，不自推动。

## 收工即走

- 报告写完、最终回复输出完，直接结束。
- 不 sleep 等主控、不自设定时器。
- `~/.codex/config.toml` 的 `notify` → `scripts/codex_notify_bridge.py` 会自动推飞书 + 落 done 信号。
