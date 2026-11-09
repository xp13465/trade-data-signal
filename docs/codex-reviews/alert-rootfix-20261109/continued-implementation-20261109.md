# 2026-11-09 授权接续实施记录

用户在明确“Codex 独立分支实现、测试、commit/push 与 CI，Claude 最终复核、合并和生产部署”的范围后回复“继续”。本次特批不改变日常只读外审角色。主工作树、main、Claude 工作树和生产数据均不由本次接续修改；共享 pending-index 仍为状态权威，本文件只记录本次证据。

## 接续已有成果

Claude 的冻结持久化修复及 F1/F2 收尾固定在 `06cde8d7371ae352bfde8a915b19b4cf3cb97750`。其工作树已有 `worker/ops_baseline.js` 的未提交生成结果，SHA-256 为 `5ebab425c7cccc4cd2ae36c44f3dad0bd5bb819084c0fbc5b27a61667dcb76db`。Codex 在自己的 `codex/ops-alert-rootfix-ci-20261109` 工作树使用同一既有生成器复现出完全相同的文件，保留 Claude 协作归因，没有另写生成逻辑或覆盖对方工作区。

旧 CI 分支通过正常 merge 纳入 `06c`；整合点 `84ad0f0d0534500688b9fa58751b2229459ce23a` 的 tree 与 `06c` 相同。派生模块修正为单文件提交 `76195fc24b41b8b02c2a606aa670834eef96f165`。六组原提交和冻结并发修复均保留在提交图中。

## 已证明的 CI 失败原因

Linux 运行 `42610034266` 的 systemd 249 兼容检查、运维定向测试和 Worker 测试通过，但 `python3 ops/monitoring/build_baseline.py --check` 以 2 退出，后续完整脚本与运维组合回归未执行。

F2 更新了 `docs/ops/architecture/inventory/data_assets.json`，并同步了 catalog 和 dashboard，却遗漏了另一个同源派生产物 `worker/ops_baseline.js`。只读固定 blob 对照证明：

- `8840` 的原始检查 exit 0；`06c` 的同一检查 exit 2，提示 server baseline differs。
- 生成器、configure 和其余八份输入未变；已提交模块仍对应旧输入。
- 差异只有 11 个叶字段：冻结表三处 evidence 的 location/code_ref/observed_at、write_contract，以及 data_assets 输入哈希。373 条源记录、370 个唯一记录保持不变。

这不是冻结并发逻辑再次失效，也没有证据表明是 Ubuntu 平台差异。修正复用既有生成入口，不手改派生 JSON，不降低检查标准。

## 生成和检查

```sh
python3 ops/monitoring/build_baseline.py --write-module
python3 ops/monitoring/build_baseline.py --check
```

改动 architecture inventory 时，除 `build_catalog.py --write` 外，也必须同步上述服务端模块。两套 `--check` 分别检查各自下游，不能互相替代。

本次本地生成后的 SHA-256 与 Claude 既有结果相同，11 个叶字段逐项、逐值吻合；baseline 检查 exit 0，11 个 Worker 模块语法检查通过，标准 pre-commit 实际执行且 exit 0。没有新增业务逻辑，因此未增加复述生成器行为的测试。

## Linux 与生产验收边界

最终固定 head 的真实 Linux 运行由 `codex/ops-*` 分支推送触发现有工作流，不修改 workflow、依赖或生产部署配置。须记录 `local-only`、`unit-compat` 两个 job 的实际结论，以及完整组合回归的原始末行。本文件不提前声明该运行通过，最终结果与 head/SHA 在本轮不可变 master report 中固定后显式 publish。

原冻结并发 P1 在 `06c` 的独立复验为 34 项定向测试通过、四个真实双进程场景通过。历史 136 条缺冻、5 个交易缺口和 #373 两日缺备份没有因此恢复。NAV、指数稳定性和过拟合/指标跳变另做真实数据核查，不以任务 exit 0 或降低风险阈值销账。

生产自然轮次必须核实际运行版本。2026-11-09 22:18 的只读快照仍为旧版 `adfd77e7a`；21:00 备份和21:10 换手率服务的原生退出码均为 0，但这不代表本次尚未部署的六组代码生效，也不单凭退出码宣称全部产物交付通过。后续仍按 [验收清单](acceptance.md) 逐项留证，由 Claude 负责最终审合部署。

本轮私有证据根：`/tmp/codex-reports/alert-continue-authorized-20261109/`。原始失败、独立复验、前次交接和历史缺口边界均保留；不修改已经 publish 的报告文件。
