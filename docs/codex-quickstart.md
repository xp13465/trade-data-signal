# Codex 快速上手

> 本文档是 Codex 外部 reviewer 在本项目的快速引导。首次接任务先读 `.codex/skills/role-codex-reviewer/SKILL.md`（角色规范）再读本文件。

## 项目架构一句话

FastAPI 后端 + 原生JS前端 + Cloudflare Workers/R2 静态站 + launchd 定时任务 + SQLite 主库。

## 关键文件速查

| 路径 | 作用 |
|---|---|
| `static-site/app.js` | 首页前端源码 (1.8MB) |
| `static-site/lab.js` | 策略实验室前端源码 (748KB) |
| `static-site/common.js` | 共享常量/预设/工具函数 (62KB) |
| `scripts/signal_kelly_backtest.py` | 凯利回测核心脚本 |
| `scripts/loss_rules.py` | AI降亏规则键定义（RULE_SPECS + QTH 阈值） |
| `scripts/check_signals.py` | 信号检查 + 邮件/飞书通知 |
| `scripts/check_data_integrity.py` | 数据完整性校验（deploy 前置） |
| `scripts/check_fade_keys_alignment.py` | AI降亏键集跨端一致性机检 |
| `app/queries.py` | 后端查询层 |
| `config/universe_rules.yaml` | 宇宙规则（入样/排除） |
| `docs/smoke-checklist.md` | P0/P1 smoke 清单 |
| `CLAUDE.md` | Claude 共享规范（含 §22 一致性 / §23 铁律） |

## 常用命令

```bash
# 键集一致性机检（六项断言）
python3 scripts/check_fade_keys_alignment.py

# 谓词全等校验（三层）
python3 scripts/check_loss_rules_vs_mining.py

# 数据完整性（32项检查）
python3 scripts/check_data_integrity.py

# 前端谓词对齐（Node.js）
node scripts/check_fade_predicate_parity.mjs

# 浏览器测试
node /tmp/codex-reports/browser-test.js
```

## 通讯协议

- **请求**: `git cat-file -p refs/codex/req/<request_id>`
- **报告**: `/tmp/codex-reports/<request_id>.json`（原子写 .tmp→rename）
- **协议文档**: `docs/codex-collab-protocol.md`

## 注意事项

- `.git/` 只读，不能 `git hash-object -w` 或 `git update-ref`
- `data/sentiment.db` 可读但部分校验脚本可能因 schema 差异误报
- 线上 curl 在沙箱内可能全部超时（http_code=000），需要 escalated 权限
- Playwright 需要 escalated 权限才能启动 Chromium headless
