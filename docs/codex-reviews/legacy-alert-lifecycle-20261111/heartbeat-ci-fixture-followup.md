# 心跳旧测试契约补齐

2026-11-11。集成候选 `ec6405e19` 的完整 CI 统计为 5307 tests、5 failures、0 errors、7 skipped；失败集中在 `test_alertchain_hardening_20261003.py` 和 `test_alert_w2_tri_state_20261010.py`。本地原样复现 5 failed / 18 passed，原始失败记录随私有总报告保留。

这五项仍伪造旧 stderr 汇总，且要求心跳源码含 `notify_state(out)`、旧 `--severe` 与固定时间窗。现行生产路径已经使用共享事件及 `--result-file`；缺结果必须保守判 unknown。不能为通过旧测试退回字符串判据。

本修订只改测试：保留真实 heartbeat → observe/dispatch，通知子进程替身写结构化结果；事件状态写各测试 tmp_path，避免污染 checkout。缺失/陈旧心跳仍必须首报 critical，事件 refs 必须匹配实际状态中的 event_id，健康心跳仍零通知。nextday 两站的原文本三态测试保持。

新增五个负例覆盖缺结果、坏 JSON、partial、unknown、failed：即使 rc0 且 stderr 为成功文本，心跳也必须返回 2。原 S06/心跳事件重试、恢复再故障、并发覆盖等真实集成用例一起回归。

父侧九文件组合：`173 passed in 5.08s`。这不是完整 CI 通过；最终固定 head、独立复核和新 CI 结论以总交付报告为准。两轮原 CI 失败都保留，不能写成一次全绿。
