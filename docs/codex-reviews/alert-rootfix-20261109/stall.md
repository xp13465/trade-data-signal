# 巡检告警的滚动日期与当前对象时长（2026-11-09）

真实用户要求：

> 为了确认可以修好。修之前分析一下真正原因和找出可以修好的依据。再开始修。我去睡了。醒来看你修好了多少个

`delegated_scope`：父任务把 B 的 caller / ADR / 对应测试与本文档交给 Codex，
独立 worktree `codex-alert-stall-20261109`，分支 `codex/alert-stall-20261109`，
基线 `adfd77e7ad3a25033bf7ca02df85e0f459446e71`。A 的不可变备份基线另有 owner。
根因报告原件保留于 `/tmp/codex-reports/alert-rootfix-20261109/ancillary-root-cause.json`；
v2 只改溯源元数据，把真实原话放进 `trace.user_request`，父子分工放进 `delegated_scope`。

## 根因与实证

`check_failed_units.py` 将本轮 failed unit / 巡检者异常汇入同一通道。
`notify.py` 用 `failed_units_patrol_state.json`，经
`consecutive_days_escalate(rolling_window_days=7)`，记录通道的异常日期集合。
这组日期可以来自不同 unit，也允许正常轮次和断日。健康轮清集合签名，保留滚动历史。
漂移通道用另一份 `cloud_unit_patrol_drift_state.json`，并非所有类别共用一个状态。

原 `stall_context` 把通道的 `first_fail_date / consecutive_days` 复制成对象的
`first_seen / consecutive`，随后正文头写“首次发生 / 连续失败”。另一个旧升级前言
把同一通道统计写成“该异常自…未清除 / 人工处置超时”。两层都超出了证据。

11/8 23:00 的正文只列 `trade-ops-monitor.service`，却写自 11/2 起连续 7 天。
现有 journal 记录该轮 22:45:20 HTTP 503 / exit 2，下一轮 23:00:09 HTTP 200 / 自然成功。
这证明“该对象连续停摆 7 天”的解释不成立；本轮采样看到 failed 状态仍有真实依据。
完整历史来源与哈希见上述根因报告，本实现阶段没有再访问生产。

## 最小修复

1. caller 正文明确这是本轮状态观测，不能据此推断当前对象连续停摆时长。
2. ADR 对这两个通道单独展示：统计日期、近 7 个自然日的异常记录天数、窗口内最早记录。
   当前对象首次发生和连续失败时长均标“未知”。当前窗口只读过滤日期，不写状态。
   缺日期、损坏 JSON、非法日历日期或只有旧累计数字时，不反推日期来伪造证据。
3. 最终 `format_stall_body` 只识别这两个 key 下、与当前 `notify.py` 完全匹配的旧升级前言，
   将其改写为“通道异常记录达到既有升级条件”。原始对象、差异和处置明细保留。
   匹配锚定正文开头和整段固定模板，不改写其他来源的相似原文。

第三点是本轮独占 ADR 范围内对旧升级模板的兼容，不需要覆盖 `notify.py` 的未合
strict-chmod 补丁。测试直接从未修改的 `notify.py` AST 取真实升级模板，验证
原始正文 → 升级 → 最终格式化，以及先格式化 → 升级 → 再格式化和重复升级。
如果以后旧模板变更，真实模板回归会失败，要求维护这处边界。

升级 subject 沿用现有类别名及“近 7 天出现 N 天”的括号文案；这次未改标题、
升级阈值、滚动计数、首报/升级 key、去重窗、健康/恢复逻辑、群路由及收件配置。
正文明确这只是通道历史，不把类别名“持续未清”解释为当前对象持续停摆。
本次覆盖实际外发正文边界；`notify.py` 内部日志/模板源码仍是旧文案，未作修改。
其他普通 stall formatter 的输出保持兼容。

## 验证与交接

修复前，跨 unit 和两种通道断日 fixture 共 3 项失败（预期 RED）。修复后定向运行：

```bash
python -m pytest -q -p no:cacheprovider \
  scripts/tests/test_patrol_observation_wording_20261109.py \
  scripts/tests/test_264_upgrade_chain_20261015.py \
  scripts/tests/test_196_patrol_visibility_20261005.py \
  scripts/tests/test_282_alert_denoise3_20261022.py
```

新测试还覆盖：不同通道独立、当前窗口滑动不修改原计数状态、旧态/坏态保守未知、
非目标通道和普通两参调用兼容、相似原文不误改、反复格式化/升级后没有假时长。
真实进程内 `send_tiered → send → ADR → 三渠道替身` 验证最终正文和 alert 群解析，
显式 `window=0` 仍可再次发送；网络 trap 必须零命中。
原 #196 / #264 / #282 回归覆盖既有分级、滚动迁移、72h / 6h 去重、直发/预算豁免和恢复。
所有文件路径和传输替身隔离至测试临时目录，不运行真实通知 wrapper。

定向四文件合跑结果：109 passed。另验 Python 语法、`git diff --check`，
AST 对比确认 ADR 只有 `stall_context / format_stall_body` 两个函数发生变化，
滚动分级函数未改；notify / cloud patrol / 两份备份脚本与基线逐字节一致。

仅交付本分支 commit，供 Claude 审核合并部署；未 push、未改 main / pending-index / 生产。
本修改不提供精确事故起点或连续停摆计时器，也不改变历史告警事实。
