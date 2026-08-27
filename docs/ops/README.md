# docs/ops 目录索引

运维告警体系评估与监控机制相关产物。

## 文档
- [alert-system-evaluation.md](./alert-system-evaluation.md) - 运维告警体系全面评估(2026-08-02~08-15):全量告警清单/分类统计/「调机制vs根治」逐类判定/建议清单/发现的bug(待用户确认)。结论:49条SEVERE中~21条机制误报噪音,~12条真实已根治,剩余需动作为5类(P0修pending误报机制+intraday盘后阈值/P1 R2降噪/push跨槽恢复判定/验证已修项)
- [v4-pro-leak-rootcause-20260815.md](./v4-pro-leak-rootcause-20260815.md) - v4-pro 用量异常根因(2026-08-15):Explore subagent 请求 model=claude-opus-5 不在代理 INJECT/ALIAS 白名单 → 透传官方端点按 v4-pro 计费。修复建议 A/B/C 待用户确认。复现命令见报告「## 复现」。

- [data-source-outage-diagnosis-20260827.md](./data-source-outage-diagnosis-20260827.md) - 8-27数据源三线故障全链路诊断(baostock封禁10001011熔断+mootdx停服45天+东财封IP):错误码/熔断机制解剖、zb-seal_rate停更37天定性(已弃指标非活性故障,真病灶=mootdx_progress宇宙缩水85只致mootdx_daily_raw断供)、损失面量化、E28韧性盘点(个股日线/换手率/宽度三链无异源兜底+akshare备源空置)、修复任务拆单T1-T7。复现命令见报告「## 复现」。
- [ds-resilience-selftest-evidence-20260827.md](./ds-resilience-selftest-evidence-20260827.md) - Task#10数据源韧性修复批·证伪式自测证据(2026-08-27,T1降并发限速/T2 progress缩水根治/L46④severe镜像latest.md):修复前FAIL病灶点名→修复后18/18 PASS两段输出全留。复现:`.venv/bin/python scripts/check_ds_resilience.py`(不读写生产DB,通知渠道stub)。

## 脚本
- [scripts/parse_monitor_alerts.py](./scripts/parse_monitor_alerts.py) - 从 schedule_monitor_launchd.log 提取全量告警检测块并分类统计。复现:`python3 docs/ops/scripts/parse_monitor_alerts.py --since 2026-08-02`。输入依赖 `trade-data/data/logs/schedule_monitor_launchd.log`(主监控日志,15min轮询,含全量检测块)

## 数据
- (本次无独立数据文件,统计全部由脚本从主监控日志实时解析)
