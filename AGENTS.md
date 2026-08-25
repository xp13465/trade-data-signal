# Trade 项目 · Codex 工作约定

本文件是 codex 在本仓库的项目级指令(等价 Claude 侧的 CLAUDE.md)。进入会话先读两份:
1. 角色规范:`.agents/codex-reviewer/SKILL.md`(铁律 + 反幻觉规则 + 输出契约)
2. 协作协议:`docs/codex-collab-protocol.md`(ref 通道 + Request/Report JSON schema)

## 外部 review 待办检查(每次会话开始必做)

```bash
git for-each-ref refs/codex/req --format='%(refname:short)'
```

- **无 ref** → 本轮无外部 review 任务,回复「无待处理 request」收工。
- **有 ref** → 逐个处理:`git cat-file blob <ref>` 读 request JSON(status=pending 的才是新活;
  处理中可把 status 自行推进为 processing 并更新 ref)→ 按 request 里 `base..head` 范围 +
  `focus_areas` 执行只读 review → 报告**原子写** `/tmp/codex-reports/<id>.json`
  (先写 `<id>.json.tmp` 再 mv rename,schema 见协议文档)。
- **每份报告完成后必须回传信号**:先校验 JSON 可解析且 `request_id` 一致,再执行
  `python3 scripts/codex_review_complete.py <id> --verdict <PASS|FAIL|BLOCKED>`;
  该脚本会原子写 `/tmp/codex-reports/signals/claude-inbox/<id>.ready`,让主控 watcher 自动接手。

## 收工即走,不等确认

turn 结束**不要 sleep 等主控、不要自设定时器**(子代理定时器不可靠)。你收工的瞬间,
notify 桥接(`~/.codex/config.toml` 的 `notify` → `scripts/codex_notify_bridge.py`)会自动:
①推飞书开发群告知用户 ②落 `/tmp/codex-reports/<thread_id>.done` 信号文件供主控秒级响应。
所以报告写完、最终回复输出完,直接结束即可。
