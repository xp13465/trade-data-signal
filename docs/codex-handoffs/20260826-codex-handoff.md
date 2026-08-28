# Codex 产出交接清单 · 2026-08-26

## 执行政策

- **禁止 `git add .` / `git add -A`。** 只能按本清单逐批 stage。
- **默认不直接 commit 到 `main`，不 push。** 先建分支，人工/Claude 复核后再决定合并。
- 每个 commit 必须用本目录对应的 `-F` message 文件，禁止临时改写成无原因标题。
- stage 后必须校验 `git diff --cached --name-only` 与该批次白名单完全一致。
- 本清单只定义本次可安全入库的 Codex 相关产物；未列入的工作区文件**不是删除**，而是留待单独分诊。

建议分支：

```bash
git switch -c codex/agent-inbox-and-architecture-20260826
```

## 批次 A · Agent inbox 自动消费闭环

### 白名单

| 文件 | 状态 | 原因 |
|---|---|---|
| `AGENTS.md` | modified | 增加 Codex 手动兜底前所有权检查，避免与 watcher 抢活。 |
| `docs/codex-collab-protocol.md` | modified | 固化双阶段租约、精确 id 派发、成功后置条件和回执 schema。 |
| `docs/codex-signal-bridge.md` | modified | 更新双向自动消费架构、预算、超时、安全和运维口径。 |
| `launchd/com.trade.agent-inbox-watcher.plist` | modified | 提供 `CLAUDE_BIN`、单次 USD 预算和 job 超时配置。 |
| `scripts/agent_inbox_watcher.py` | modified | 增加双通道单槽、租约续期、超时终止、Claude 回执后置校验。 |
| `scripts/claude-inbox-consumer.sh` | untracked | 新增固定 prompt 的 Claude consumer；隔离 worktree、工具白名单、禁 commit/push/联网。 |
| `scripts/codex_review_claims.py` | untracked | request 租约实现；已被 watcher 导入，漏掉会导致干净检出直接失败。 |
| `scripts/test_agent_inbox_watcher.py` | untracked | 覆盖派单约束、报告 mtime/schema 校验、回执覆盖率和 worktree 归属。 |
| `scripts/codex-review-request.sh` | modified | 活租约下拒绝同 id 重发；重发时清理旧 Claude 信号和 action receipt。 |

### 验证

```bash
shasum -a 256 -c docs/codex-handoffs/20260826-codex-handoff.sha256
python3 -m py_compile scripts/agent_inbox_watcher.py scripts/codex_review_claims.py scripts/test_agent_inbox_watcher.py
bash -n scripts/claude-inbox-consumer.sh scripts/codex-review-request.sh
python3 scripts/test_agent_inbox_watcher.py
plutil -lint launchd/com.trade.agent-inbox-watcher.plist
```

已实测结果：7 个单元测试 PASS；假 Claude CLI 干跑通过；非法/缺失回执会被拒绝；plist lint PASS。

### 提交命令骨架

```bash
git add AGENTS.md \
  docs/codex-collab-protocol.md \
  docs/codex-signal-bridge.md \
  launchd/com.trade.agent-inbox-watcher.plist \
  scripts/agent_inbox_watcher.py \
  scripts/claude-inbox-consumer.sh \
  scripts/codex_review_claims.py \
  scripts/test_agent_inbox_watcher.py \
  scripts/codex-review-request.sh

test "$(git diff --cached --name-only | sort)" = "$(sort <<'EOF'
AGENTS.md
docs/codex-collab-protocol.md
docs/codex-signal-bridge.md
launchd/com.trade.agent-inbox-watcher.plist
scripts/agent_inbox_watcher.py
scripts/claude-inbox-consumer.sh
scripts/codex_review_claims.py
scripts/test_agent_inbox_watcher.py
scripts/codex-review-request.sh
EOF
)"

git commit -F docs/codex-handoffs/20260826-commit-A.txt
```

## 批次 B · 架构评审与性能标准

### 白名单

| 文件 | 状态 | 原因 |
|---|---|---|
| `docs/architecture/tech-stack-review-20260826.md` | untracked | Codex 技术栈架构评审主报告，含语言/存储/Worker/前端决策表与路线图。 |
| `docs/perf/perf-architecture-review-20260826.md` | untracked | 主报告引用的线上性能实测评审证据。 |
| `docs/perf/performance-architecture-standards.md` | untracked | 主报告引用的性能架构规范与预算门禁来源。 |
| `scripts/playwright-accept/perf_arch_probe.mjs` | untracked | 性能基线探针，保证报告中桌面/移动冷热加载指标可复现。 |

### 验证

```bash
shasum -a 256 -c docs/codex-handoffs/20260826-codex-handoff.sha256
node --check scripts/playwright-accept/perf_arch_probe.mjs
```

### 提交命令骨架

```bash
git add docs/architecture/tech-stack-review-20260826.md \
  docs/perf/perf-architecture-review-20260826.md \
  docs/perf/performance-architecture-standards.md \
  scripts/playwright-accept/perf_arch_probe.mjs

test "$(git diff --cached --name-only | sort)" = "$(sort <<'EOF'
docs/architecture/tech-stack-review-20260826.md
docs/perf/perf-architecture-review-20260826.md
docs/perf/performance-architecture-standards.md
scripts/playwright-accept/perf_arch_probe.mjs
EOF
)"

git commit -F docs/codex-handoffs/20260826-commit-B.txt
```

## 批次 C · 交接台账本体

复核并完成 A/B 后，最后提交以下五个控制文件：

- `docs/codex-handoffs/20260826-codex-handoff.md`
- `docs/codex-handoffs/20260826-codex-handoff.sha256`
- `docs/codex-handoffs/20260826-commit-A.txt`
- `docs/codex-handoffs/20260826-commit-B.txt`
- `docs/codex-handoffs/20260826-commit-C.txt`

```bash
git add docs/codex-handoffs/20260826-codex-handoff.md \
  docs/codex-handoffs/20260826-codex-handoff.sha256 \
  docs/codex-handoffs/20260826-commit-A.txt \
  docs/codex-handoffs/20260826-commit-B.txt \
  docs/codex-handoffs/20260826-commit-C.txt

test "$(git diff --cached --name-only | sort)" = "$(sort <<'EOF'
docs/codex-handoffs/20260826-codex-handoff.md
docs/codex-handoffs/20260826-codex-handoff.sha256
docs/codex-handoffs/20260826-commit-A.txt
docs/codex-handoffs/20260826-commit-B.txt
docs/codex-handoffs/20260826-commit-C.txt
EOF
)"

git commit -F docs/codex-handoffs/20260826-commit-C.txt
```

## 明确排除项

以下是当前工作区存在但**不得因本清单顺手入库**的类型；它们应另行分诊，而不是丢弃：

- `.codex/config.toml`：包含 `sandbox_mode = "danger-full-access"`，属于本机风险配置，不能入库。
- `data/**`：数据库、运行状态、缓存、备份和证书类运行时数据。
- `*.bak*`、`*.tmp`、`__pycache__/**`、`.wrangler/**`：本地备份、构建缓存或临时产物。
- 其他与本交接无关的 modified/untracked 文档、脚本、图片：必须由 owner 单独确认后另立 commit。

## 收尾检查

```bash
git status --short
git log --oneline --decorate -5
git diff --check
```

预期：只有本清单外的既有脏改动残留；三个新 commit 都在非 `main` 分支上；未 push。
