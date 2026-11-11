# HC21 发布最终 push 路径修复 · 2026-11-11

本子任务已实施并完成隔离自验，交父任务整合及 Claude 复核；不表示已合 main、已部署或完整 CI 通过。按本次用户明确授权开发，不修改默认角色规范。

## 改动与合并证据

- 工作分支：`codex/ops-release-gate-20261111`；独立 worktree：`/Users/linhuichen/code/trade/.claude/worktrees/codex-ops-release-gate-20261111`。
- 指定 base：`0ad543ef41758be9d7102b42471489b24d0cb989`。
- 固定合入：`61a56ce7fc037e0a9f8ce8aad018ee1c173edd95`，连同其父 `c720d8733ff95200cbefb2c62532ba99651c9ebd` 的既有三快检实现；没有重写另一套快检。
- 合并提交：`e8943f0634524a51453aae346f2ef52119a25c47`，两个父依次为上述 base、固定合入提交。其后的修复提交包含本报告，完整最终 HEAD 与图保存在交付回执 `delivery.json` / `merge-graph.txt`（下述私有证据目录），并随最终回复交父任务。
- `NOTES.md`、`docs/pending-features-index.md` 各一处真实冲突，仅局部拼接两侧记录。原 base 的所有行按原顺序保留，两侧冲突臂逐字保留；pending 只新增原分支 #378，不改其他 HC 状态。源脚本与固定合入提交逐字一致后才另做修复；registry 正常自动合并。

最终 push 首次失败即 `exit 5`，明确提示主控核对远端、处理失败原因并更新基线，随后重走完整 `main-merge.sh` 入口。不再自动 fetch/rebase/第二次 push，不复制或移动 7.10。连接中断等失败同样停止；不能由失败返回推断远端一定没有接受提交。

逐字保留证明：相对固定 `61a56ce7…`，`set -euo pipefail` 至最终 push 块之前的运行代码、7.10 块、push 后第 10/11 步均完全相同。因此原安全窗口、入口错误退出、自更新、防循环、bump、源码/产物干净检查、既有显式 skip 均保留。仅流程头注释、最终 push 失败分支、registry 的对应自检说明改变。`deploy.sh` 字节未改，前端版本串未改。

## 先复现再修复

依据：[前轮独立审计](../ops-followup-20261111/fastcheck/report.md)。先复制原 harness 到本次证据目录，再重放，原证据和交接 packet 未改。

1. 原 24 项断言：24 符合预期。真实隔离 Git 的两侧文档各自三检通过；旧 push 失败后 fetch/rebase，再执行第二次模拟 push；事后重复 #499 被任务检查拒绝。这是缺陷成功复现，不是发布链通过。
2. 新增常驻 14 项用例在修前：`3 failed, 11 passed in 5.11s`。真实本地 bare 远端非快进拒推及强制返回 1/128 都抓到旧自动重试。
3. 修后同反例：首次拒推 `exit 5`，调用轨迹仅 `git push origin main`，零 fetch/rebase/第二 push/ssh/CI；本地 HEAD 和本地远端 HEAD 保持不变。随后仅在测试临时仓手动 rebase 作负控，三检确实报重复编号并 exit 11。
4. 正常本地 push 成功仍进入云同步桩，再进入 CI 桩；同步失败 exit 6、CI FAIL exit 9、CI 无结论返回警告但 exit 0，顺序和语义保留。

## 自验与原始末行

私有证据根：`/tmp/codex-reports/ops-backlog-20261111/release/`。新增常驻用例子进程限 25 秒，继承 harness 子进程限 30 秒；成组运行外层 120/150 秒强制终止进程组，内部另设 110/140 秒预算；耗时调用通过 session 收集至完成，无遗留进程。没有执行完整生产入口，也没有执行完整 `--dry-run`。

定向命令（设置 REPO/GIT_REPO 为临时根，禁 bytecode 和 pytest cache）：

```sh
python3 -m pytest -q -p no:cacheprovider   scripts/tests/test_hc21_main_merge_push_gate.py   scripts/tests/test_gate_registry_pytest.py   scripts/tests/test_277_version_check_toctou_20261022.py   scripts/tests/test_309_unit_registry_drift_20261031.py   scripts/tests/test_r2_lock_gradient_audit_normalize_20261031.py
```

实际加独立 `--basetemp`，完整日志 `targeted.log`，原样末行：

```text
35 passed in 7.90s
```

既有源码形状守卫扫描覆盖 `scripts/tests` 对 `main-merge`/`MAIN_MERGE`/`FASTCHECK` 的引用，未找到依赖旧重试字面量的守卫，无删测试或弱化断言。与本脚本直接相关的原四组回归均包含在上述 35 项内；全量 `scripts/tests/` 按派单由父任务统一执行。

原 harness 更新为当前 push 块后的最终摘要（`after.log`）：

```text
{"shell": "GNU bash, version 3.2.57(1)-release (arm64-apple-darwin23)", "python": "3.11.0 (v3.11.0:deaf509e8f, Oct 24 2022, 14:43:23) [Clang 13.0.0 (clang-1300.0.29.30)]", "total": 24, "assertions_passed": 24, "assertions_failed": 0}
```

这 24 项复用旧固定文档样本，覆盖三检、缺解释器/缺脚本、任意错误码、WARN、跨 cwd、skip=1/true、纯文档与局部 dry-run 等；不冒充整个合并树。首次适配出现 23/24：旧夹具未设生产入口必设的 FEAT，新错误提示触发 nounset。原日志保存在 `after-initial-fixture.log` / `after-initial-retry.log`；仅补齐测试环境 FEAT 后重跑通过，没有修改产品来迎合夹具。

真实解决冲突后的最终文件另外复制到隔离根，实际三检查原始末行（`ledger.log` / `registry.log` / `task_state.log`）：

```text
[ledger] RESULT=PASS(通过 15 项,失败 0 项)
[gate-registry] RESULT=PASS
=== 汇总: 2 ok / 0 warn / 0 fail ===
```

`bash -n scripts/main-merge.sh` exit 0、无输出；`git diff --check` exit 0。`preservation-proof.json` 记录字节保留断言；`conflict-resolution.json` 记录局部合并；`final-fixture-sha256.json` 固定实际检查文件哈希。

## 边界、同类与后续

| 维度 | 本次覆盖 |
|---|---|
| 输入 | 正常 push、非快进拒推、错误码 1/128；三检错误码 1/2/37/127；skip 仅字面 1 生效 |
| 状态组合 | 三检全绿/连续三红、纯文档不触发 pytest 仍触发快检；失败退出不进入后续步骤 |
| 时序 | 两侧分别有效→并发远端前进→拒推；检查过的 HEAD 不改变；成功后先云同步再 CI |
| 上下游 | Git 真实执行但只接本地 bare 远端；GIT_ALLOW_PROTOCOL=file 禁联网；ssh/CI 只记日志的桩 |
| 极端值 | 缺脚本、缺解释器、任意非零检查码；任务编号 WARN 与 FAIL 区分 |
| 回退 | 显式 skip/dry-run 保持现状；仅抽取白名单块，完整 dry-run 有 fetch/rebase 等副作用未执行 |
| 并发重入 | 并发远端提交用真实本地 Git 重现；任意外部进程改工作树、定制 Git hook 未覆盖，不外推 |

实现复用已有三快检、已有完整入口，删除自动重试这一处根因；没有新框架或第二套校验。pending 本模块核到 #378，分工按父协调文档 Release 边界；没有新增接口需要给其他组预留。

同类范围已报告父任务：`deploy.sh` 仍有独立 rebase/retry 流程（静态定位在段 2），本任务未改也未运行，不能把 main-merge 的修复外推为全部发布通道已修。根 CLAUDE/实施规范中的通用 fetch+rebase 重试指导未改；本入口失败后的操作应以“更新基线后重走完整入口”为准。

其他保留限制：7.10 本身仍读工作树，不能保证覆盖未提交文档修复、并发改树、任意 hook；registry 自身 7.10 行被删的既有盲点按原文保留。完整 build/bump、其他发布门禁运行、Linux/CI、main 合并点验证、生产发布和自然轮由父任务/Claude 完成。本任务没有真实邮件/飞书/通知、生产 DB/R2 写、main push、原 packet 修改/ACK、cron 或子 agent；git 提交/推送禁用本地 hooks，手工运行上述相关检查，避免外发副作用。

相对 base 的文件清单仅六件：`scripts/main-merge.sh`、`docs/ops/machine-check-registry.md`、本次局部冲突的 `NOTES.md` 与 `docs/pending-features-index.md`、`scripts/tests/test_hc21_main_merge_push_gate.py`、本报告。协调 README、其他组文件、角色规范均未改。
