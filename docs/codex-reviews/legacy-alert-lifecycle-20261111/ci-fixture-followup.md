# 完整 CI 中恢复循环夹具缺依赖：补修

基线 `b1eb3f38596975d8719eb738c591f00c88e45bf8`，原独立 codex 分支。
用户报告 CI run 43007260478：5299 tests / 16 failures / 0 errors / 7 skipped。
父任务集成 head 与本地分支不同；本文不把本地结果冒充该 CI 的重跑结果。

实际依据：读取父任务原日志 ci-failure-local-repro.log，并在本分支用项目 .venv/bin/python
执行相同四模块。结果 `11 failed, 77 passed in 2.73s`，全部堆栈为生产恢复循环调用
`_producer_owned` 的 NameError。四个夹具只剪裁了 for 循环，没有加载新增的函数依赖。
本次未发现需要改产品代码的缺陷；未修改产品文件或生产状态。

## 修改

四个夹具从正在被测试的同一源码 AST 中，先加载真正的 `_producer_owned` 定义，再执行
原恢复循环；支持原有源码覆盖入口，不使用 lambda False，也不复制前缀判定。
未找到真实函数时 next() 直接失败，不能假装测试通过。

新增 test_recovery_fixture_ownership_20261111.py 对每个夹具分别验证 active/pending：
真实 helper 收到两个独立 producer key 时返回 True，收到普通任务 key 时返回 False；
前者状态保持，后者按原循环恢复。包装函数只是记录调用并执行原 helper，不改变结果。
四个原模块 77 个 test_* 定义的 AST（含原断言/装饰器）完全相同，未删测试、未加 skip。

## 有界查漏

范围：scripts/tests/**/*.py、scripts/test*.py、ops/monitoring/tests/**/*.py。
搜索 seen_keys_this_run / _producer_owned / recovery_loop / _key 与 _info 同行锚点；
20 个候选文件保存在 evidence/ci-fixtures/recovery-candidates.txt。
后两个搜索范围未命中。不是全项目任意语言、历史文档或外部临时脚本穷举。

- 本次四个剪裁恢复循环夹具缺函数，已补。
- _monitor_conclusion_309 的 recovery_loop 已提取真实 owner，309 结论测试由其执行。
- ops_quiet_schedule / notify_ops_schedule_integration 加载全部生产定义；legacy_ops_lifecycle
  复用后者命名空间。ops_quiet_unit 的显式函数清单已包含 owner。
- 232 / 181 / alert_denoise_20261001 的恢复模拟不是 exec 当前完整恢复循环，未改模拟逻辑。
- 其余候选执行漏跑、资源、R2、退出/关键词片段等，或只是委托上述入口；没有发现其它
  exec 当前完整恢复循环但缺 owner 的夹具。全部候选一并复跑。

## 结果与边界

四模块 + 新增 8 个正反例：`96 passed in 2.67s`。
20 候选文件一起执行：`459 passed, 4 skipped in 18.64s`，原已有条件 skip 保留。
原始日志在 /tmp/codex-reports/ops-evidence-closeout-20261111/legacy-ci-fixtures/；
仓内文本副本仅去除 pytest 尾随空白，原字节未改。

命令使用 PYTHONPATH=scripts、PYTEST_DISABLE_PLUGIN_AUTOLOAD=1、
PYTHONDONTWRITEBYTECODE=1、项目 .venv/bin/python -m pytest --noconftest -q。
原 CI 的 16 与本地 11 计数差异尚未独立证实原因；不凭猜测归因于 subtests。
父任务需 cherry-pick 补修 commit 后，针对新集成完整 head 重跑完整 CI。
Raman 可复核本次 diff 仅加载缺失依赖、原断言不变和正反例实际调用链。
