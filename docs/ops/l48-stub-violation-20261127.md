# L48 新实例:设计阶段验证守卫未打桩,真发一次 critical 告警(2026-11-27)

> 一句话:2026-11-27 14:05:43,设计 agent 在验证 #384 读侧守卫时未打桩 `_alert_guard_blocked`,经 `scripts/notify.py --severe` 真发出一条 critical 告警(email + 飞书,台账 key `e1cb0973ca84`)。

## 事实

- 时间:2026-11-27 14:05:43。
- 动作:为验证「读侧守卫可复用」,直接调用 `pick_repo.guard_deploy_source_tree()`(misconfig 场景)。
- 后果:该函数内部经 `_alert_guard_blocked()` 调 `scripts/notify.py --severe`,真实外发一次 critical 告警,渠道 email=true / feishu=true。
- 台账证据(保留不删):`data/alerts/alert_ledger.jsonl` 记录 `key=e1cb0973ca84, tier=critical`,subject「[防再犯E守卫] 写部署源树目标错误(SystemExit 阻断)」;`data/alerts/latest.md` 有对应 `[severe]` 段。

## 定性

告警内容对应的是一个手工构造的错配 env,不是生产故障;但按规范真实外发记录不删除、如实留档。

## 关联规范

- CLAUDE.md §18 L48:具备真实发送链路的脚本(告警/邮件/飞书)自测前必须先打桩,并先证沙箱判定生效;派单验收点 = 「本次自测未产生真实外发」证据。
- memory `notify-script-selftest-must-stub`。

## 修法已落地(本次事故的直接产物)

1. **#384 批 1 任务书硬约束**:任何触发守卫的用例必须先 `monkeypatch.setattr(pick_repo, "_alert_guard_blocked", lambda m: None)` 打桩;派单硬约束再列「零外发:守卫/告警/通知路径一律先打桩再触发」。
2. **设计报告 §6**(`docs/ops/repo-unify-design-20261127.md`):如实记录本次事故 + 证据 + 后续验证纪律。
3. **实施/审查复核**:批 1 实施报告与独立审查报告均设「L48 打桩核查」项,3 个触达守卫的用例全部打桩,断言桩被调用/不被调用,全程零真实外发。

## 恢复/追溯

- 原始依据:`docs/ops/repo-unify-design-20261127.md` §6;`docs/ops/repo-b1-impl-report-20261127.md`、`docs/ops/repo-b1-review-report-20261127.md` 的 L48 核查段。
- 台账记录不删,可用 `grep e1cb0973ca84 data/alerts/alert_ledger.jsonl` 反查原文。
