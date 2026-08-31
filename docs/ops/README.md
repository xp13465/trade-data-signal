# docs/ops 目录索引

运维告警体系评估与监控机制相关产物。

## 文档
- [alert-system-evaluation.md](./alert-system-evaluation.md) - 运维告警体系全面评估(2026-08-02~08-15):全量告警清单/分类统计/「调机制vs根治」逐类判定/建议清单/发现的bug(待用户确认)。结论:49条SEVERE中~21条机制误报噪音,~12条真实已根治,剩余需动作为5类(P0修pending误报机制+intraday盘后阈值/P1 R2降噪/push跨槽恢复判定/验证已修项)
- [data-gap-alert-batch-20260827.md](./data-gap-alert-batch-20260827.md) - 采集异常告警兜底批(检测器上线报告,#103 方案A+S2 用户拍板):新增 scripts/check_data_gap_alerts.{py,sh} 四检查器(北向深缺口不自愈/北向停更/accum_nav 窗外缺口基线增量口径/宽度族保鲜),launchd com.trade.check-data-gap 交易日 22:35;阈值全部实测来源;发现 a_width_zb/seal_rate 停更37天真先例;two-way 自测+复现段见报告。
- [v4-pro-leak-rootcause-20260815.md](./v4-pro-leak-rootcause-20260815.md) - v4-pro 用量异常根因(2026-08-15):Explore subagent 请求 model=claude-opus-5 不在代理 INJECT/ALIAS 白名单 → 透传官方端点按 v4-pro 计费。修复建议 A/B/C 待用户确认。复现命令见报告「## 复现」。

- [data-source-outage-diagnosis-20260827.md](./data-source-outage-diagnosis-20260827.md) - 8-27数据源三线故障全链路诊断(baostock封禁10001011熔断+mootdx停服45天+东财封IP):错误码/熔断机制解剖、zb-seal_rate停更37天定性(已弃指标非活性故障,真病灶=mootdx_progress宇宙缩水85只致mootdx_daily_raw断供)、损失面量化、E28韧性盘点(个股日线/换手率/宽度三链无异源兜底+akshare备源空置)、修复任务拆单T1-T7。复现命令见报告「## 复现」。
- [ds-resilience-selftest-evidence-20260827.md](./ds-resilience-selftest-evidence-20260827.md) - Task#10数据源韧性修复批·证伪式自测证据(2026-08-27,T1降并发限速/T2 progress缩水根治/L46④severe镜像latest.md):修复前FAIL病灶点名→修复后18/18 PASS两段输出全留。复现:`.venv/bin/python scripts/check_ds_resilience.py`(不读写生产DB,通知渠道stub)。
- [sensenova-rotate-proxy-20260901.md](./sensenova-rotate-proxy-20260901.md) - 商汤Sensenova 3-token轮换本地代理方案(2026-09-01):缓解token.sensenova.cn对deepseek-v4-flash的RPM限流(~1req/min),纯key轮换3把key摊3池≈3req/min吞吐。构成:独立脚本sensenova-rotate-proxy.{py,sh}(纯round-robin+429换key重试,无thinking逻辑)+plist(launchd守护8899)+rollback.sh新增sento一键回退。key存../trade-data/.env(SENSENOVA_KEY1/2/3,仓外禁进git),settings已切127.0.0.1:8899。8899曾孤儿static-site已清理。reviewer PASS 4硬约束+端到端冒烟3层证据。诚实待改进:日志L141不记具体key。回退`bash scripts/thinking-proxy-rollback.sh sento`。复现命令见报告「## 复现」。

## 脚本
- [scripts/parse_monitor_alerts.py](./scripts/parse_monitor_alerts.py) - 从 schedule_monitor_launchd.log 提取全量告警检测块并分类统计。复现:`python3 docs/ops/scripts/parse_monitor_alerts.py --since 2026-08-02`。输入依赖 `trade-data/data/logs/schedule_monitor_launchd.log`(主监控日志,15min轮询,含全量检测块)

## 数据
- (本次无独立数据文件,统计全部由脚本从主监控日志实时解析)
