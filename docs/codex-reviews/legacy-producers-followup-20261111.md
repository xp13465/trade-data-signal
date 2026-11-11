# OTHER-PRODUCERS：事件接线交付与未覆盖边界（2026-11-11）

本次是用户授权的独立实现，不是已部署或独立复审 PASS。基线固定为
`20f669d25fc44056f207b15b606e2da7f7a70770`，分支
`codex/legacy-producers-followup-20261111`；由父任务集成、独立复验并运行最终 CI。
未改 main、生产、NAV async、fund 模块、notify.py 或 pending-index；无真实通知、上传、公共 GET。

## 已实现

- nextday 生成/校验、update_all 聚合失败、日报 main 包装失败接入原生 alert_state / notify refs / ACK / 分渠道回执。
- 原生状态锁下创建执行令牌、完成前鲜读比较；迟到旧完成不能覆盖新结果。Python 与包装层共享令牌，保留子进程原明细，只补尚未成功渠道。
- 缺失/损坏状态不相信旧 ACK；保留坏文件，失败走明确 unknown 的可见兜底。无新队列或通知状态机。
- 已验证恢复后的新故障创建新 ID，不继承旧 ACK；新增故障类别也重新发首报。update_all 按稳定故障组合区分，日期和错误正文不进入身份。
- 真实 `--date` 补跑、retry 参数、recheck/backfill 的失败仍告警。dry-run/test-open/no-r2/no-notify 不触发运维告警或恢复；历史日期、局部补跑不关闭当前故障。argparse 的显式参数契约有表格测试，真实 shell 的日期补跑亦实测。
- 真实异常保留异常类型、bounded traceback 尾段、日志路径。正常业务订阅和原业务退出码保留。
- gap 部分缺价、清理旧标记后的同步失败接入实际失败证据；即使原业务 rc=0 也不吞告警。
- update_all fund-nav transient service 仅增加父任务要求的两个 opt-in 环境变量（默认 0），未改 readback 预算或 async 上传逻辑。

## 恢复证明：明确未闭合的范围

| producer | 本次可证明 | 不能自动宣布 |
|---|---|---|
| nextday_plan | 执行失败、渠道回执、原生事件身份 | rc0 不等于本轮全部产物已公开发布；成功完成保留 unknown |
| nextday_gap | 真实失败、当前目标价格校验观察 | 缺原故障执行日＋目标集合绑定；今天目标正常不能关闭昨天缺价/旧产物/冻结成交。全部完成仍保留 unknown |
| update_all | 现有监督判据失败及稳定类别 | 本地时效/rc0 未覆盖异步任务、完整发布及公网字节；正常完成仍保留 unknown |
| daily_summary main | 实际 send_report_to_feishu 接收当前报告，正常模式下可恢复“报告投递操作” | 不证明历史漏报已补齐、阅读完成或所有业务数据正确；无数据/历史日期/dry-run 不恢复 |

nextday_gap 先前候选的 `targets_verified_no_write` 被范围负控证伪：昨天 ETF_A
缺价尚未修，今天 ETF_B 通过曾错误返回 verified。`scope-red.log` 保留该真实失败，
本次已收紧为 unknown；没有为了全绿新增日期/资产状态架构。

同一尚未证明恢复的故障类别持续归同一事件，不能从普通 rc0 猜出“已经恢复又复发”。
这意味着 plan/gap/update_all 的完整自动生命周期仍缺上表证据，不能称为业务根治。
update_all 故障组合减少亦可能产生保守的新事件；不把部分好转认作整体恢复。

历史无 refs 队列没有可靠事件身份：不按标题删除、不补造 refs，不声称已安全迁移。
仅文案或成功日志也不是可用的 ACK/资产恢复证据。原生新 refs 仍由既有 notify 在发送前重验。

## 验证与原始证据

全部日志位于 `/tmp/codex-reports/ops-final-gaps-20261111/legacy-producers/`，旧记录未覆盖。

- `base20f-scripts/` 是 git show 固定20f提取；`base20f-negative-v2.log`：
  `2 failed, 9 deselected in 1.65s`。真实旧 py+sh+notify 在 email 成功、另两渠道失败时，
  只调用3次而非应有5次；旧时间窗误吞失败渠道补发。
- 原相关回归 `related-v2.log`：88 failed / 464 passed。77为同一 AST 夹具漏载真实装饰器，
  7为旧窗口/文本契约，3为派发器不认识新 helper，1为日报调用形状。
  实际导入装饰器/notify，而非 lambda 禁用逻辑；历史 generic dedup/parser 断言保留。
- 新全 shell 用例发现 Bash 3 + set-u 空数组展开回归，`shell-v2.log` 原始失败保留；已修为固定标量开关。
- 父侧指出的“任意 argv 静音”和“异常正文丢明细”已修，真实日期补跑、dry/local/skip、异常字段均有入口测试。
- 新异常测试最初 `41 passed, 1 error` 是采集模块 import-time SWS DNS 被离线 trap 阻断。
  `exception-trap-v2.log` 定位到 app/collector/base.py 的 DNS 叶节点，替换为确定离线地址，未改生产实现或放开网络。
- 范围收紧前关联集 `final-local.log`：
  `797 passed, 3 skipped, 11 subtests passed in 89.85s (0:01:29)`。
  3 skip 是既有 fixed49 历史快照缺失测试，不是本轮新增 skip。
- 最后范围收紧后的必要集与固定提交 SHA 由同目录 `report.md` 记录；父任务仍需最终整合 CI。

离线覆盖包括：真实完整 shell+Python main、真实 notify CLI、分渠道失败补发、包装兜底、
线程迟到完成、ACK/新事件、rc0无结果文件、坏状态/缺盘、无refs不删、日期补跑、
无数据/干跑/本地模式不恢复。所有外部网络/通知/进程叶节点均受替身或审计护栏限制。

## 3182ea 独立复审两 P2 追加修复（不改旧提交）

- 包装层删除第二份 flags case；`begin --producer-args ...` 原样接收 argv，
  复用 `operation_mode`（含 argparse 唯一缩写）。明确打印 `disabled:diagnostic` 才是
  诊断关闭；损坏状态等 begin 失败输出空令牌、返回非零，真实失败仍走可见兜底。
  未识别/无效的真实 shell 参数也按失败可见处理，不能伪装为已识别的安全诊断模式。
- 日报 `_run_main` 发送后，只有实际请求日期等于当前日期且报告日期匹配时才记录
  `report_accepted`。覆盖 `main(argv=[...])` 和直接位置/关键字调用；历史业务报告照发，
  不恢复当前 active。dry/supplement 保持不恢复，当前真实报告仍可恢复。
- 新真实入口回归在 `test_legacy_operation_mode_followup_20261111.py`。
  首轮日报 fixture 缺 `fx_contract` 被既有门禁拒绝，保留原失败日志，补合法数据而未修改门禁。
  使用固定3182源码和合法 fixture 的历史日期反例为 `6 failed in 0.33s`；
  修正后必要关联集与追加 SHA 见 `/tmp/codex-reports/ops-final-gaps-20261111/legacy-producers/followup-3182/`。
