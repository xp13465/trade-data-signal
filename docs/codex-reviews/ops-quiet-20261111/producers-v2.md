# R2 skip 交接事实修复 · v2 · 2026-11-11

在已验收 `afca1d0c1aca311e867184692686747632cefbc1` 上追加独立提交；原 `producers.md` 与 `/tmp/.../producers/report.json` 不改。本轮写集仅 `scripts/r2_upload_skip_notify.sh`、`scripts/tests/test_ops_quiet_r2_skip_20261111.py`、本文。核对 48 worktree，三个路径无其他未提交修改。

## 已证反例与实现

旧钩子 enqueue 失败仍向 deploy 日志、skip 流水及 report 通知声称“已保存 proof / 已有实例负责完成”；retire-source 失败被 `|| true` 吞掉。enqueue 返回 0 也可能只是 legacy 唤醒标记，或已完成/被更新版本替代的记录，不能等同新 pending。修前完整 shell 测试原始末行：`6 failed, 2 passed in 3.67s`。

新钩子读取 helper **已有 JSON 返回值**，校验 run/root/哈希格式再分类；不新增或修改队列格式、消费/上传算法。表中状态同步写 deploy 日志、skip 流水与通知正文：

| handoff 状态 | 如实说明 | 源 metadata 与通知 |
|---|---|---|
| queued | 本请求 proof 已保全待接手；未确认接手/远端交付 | 调原 retire-source 自校验；正常 report，不声称源一定删除 |
| recorded_terminal | 同 run 已有 done/superseded 记录，本次没有重建 pending；本地终态不单独证明远端交付 | 保留原 helper 自校验清理；普通 report |
| legacy | 只保留唤醒标记，未登记逐请求 proof | 不 retire，不声称保全；普通 report |
| enqueue_failed | 入队失败，无法确认 proof 保全 | 不 retire、不追加删除；保留源 metadata 供检查与显式 retry，severe + alert |
| invalid_result | 返回内容无法解析、run/root 不符或证明字段无效 | 不 retire；按未知交接处理并给显式 retry 提示，severe + alert |
| retire_failed | 保留已登记事实，但源清理未确认 | 不追加删除；保留现有队列记录及可用副本，核对源状态后按需 retry retire-source，severe + alert |

正常通知沿用 `r2_upload_async_skip:$LOCKPATH`；失败使用 `r2_upload_async_skip:<状态>:$LOCKPATH`，6 小时去重，不含时间戳，普通 skip 的去重窗不能吞新失败。路由用显式参数数组传给原 notify；不把失败送 normal report，不改 notify 本身的全局规则。所有分支都明确：仅凭锁路径不能确认合法持锁者、接手状态或交付时间。

不改 with_lock/callback 的 best-effort 返回契约，通知失败仍不会改变锁返回；不写任何上传或 pending 消费逻辑。**三类 skip 按 deadline 静默仍未实现**，本补丁没有把任何 skip 统一改 info。

## 离线证据与兼容边界

专属用例完整执行隔离副本中的 shell 与真实 `r2_pending_context`（含磁盘 proof 复制、哈希读取、源退休）和真实 notify CLI/dedup；只有故障注入和三渠道 transport 是替身。沿用 v1 的导入前网络/进程/根外写入阻断，全部 REPO/GIT_REPO/MAIN_REPO/config/队列/源 metadata 临时隔离，shell 15 秒进程组上限，超时杀组并收集。无生产调用、真实通知或全局锁操作。

13 项 v2 用例覆盖：enqueue 磁盘失败、retire 失败、成功、retire 返回 False 不删源、legacy、无法解析的零退出、错 run/root、done/superseded 终态、重复失败真实去重、普通 report 去重不吞新失败。加 v1 30 项组合验证，最终原始末行 `43 passed in 18.63s`；原始日志见 `/tmp/codex-reports/ops-quiet-20261111/producers/final-tests-v2.log`。`bash -n` 与 `git diff --check` 通过。

**共享测试兼容尚需父处理，不能宣称整合套件全绿。** 未授权修改共享测试，已在 progress 报告以下三项；原始结果 `3 failed, 6 passed in 25.80s`，日志 `compatibility-v2.log`：

1. `test_business_channel_declaration_20261017.py:75` 固定检查原 inline 参数排版。应保留“显式渠道”要求，检查 `_NOTIFY_FLAGS` 正常 report / 故障 alert 两支及最终 `"${_NOTIFY_FLAGS[@]}"` 透传，不能只删守卫。
2. `test_254_alert_egress_layering_20261028.py:305` 断言全脚本没有 `--feishu-group alert`，与本轮失败必须告警的授权冲突。应按状态区分正常 report 与失败 alert；本组完整流正负控可作为证据，不能用生产写法规避旧字符串检查。
3. `test_codex_r2_pending_handoff_20261106.py` 的 `ADAPTER` 把新增 `python -c` 当未知业务命令空返回，因此脚本正确进入 invalid_result 并保留 source，旧测试要求 source 已退休而失败。父应在该隔离 adapter 中允许真实执行本地 stdlib JSON 校验并继续阻断外发，保留原 source 退休/队列保全断言。

第 3 项已独立诊断：`/tmp/codex-reports/ops-quiet-20261111/producers/verify-handoff-adapter-v2.py` 仅在 pytest 内存中补 adapter 的 `-c` 支持，不改仓库文件、不改断言；原始结果 `7 passed in 27.76s`，日志 `adapter-diagnosis-v2.log`。这不是未修改共享夹具时的通过结果。

父负责上述共享夹具调整、全量套件和整合后通知/调度合同复核。本组只提交授权写集，不合 main、不部署、不宣称已解决交付期限监控。
