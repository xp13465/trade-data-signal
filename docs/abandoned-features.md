# 废弃需求清单(abandoned-features)

> **用途**:已废弃/基本不会再拾回的需求归档。除非用户主动强调或同类问题再次出现,不重新启用。
> **来源**:2026-08-21 从 pending-features-index 移入,用户拍板全部废弃。
> **恢复条件**:用户主动说"把这个捞回来"或同类问题实际出现。

---

## 废弃项

| # | 功能 | 废弃原因 | 废弃日期 | 原出处 |
|---|---|---|---|---|
| 30 | **R2审计P2×4: purge失败告警 / _headers不生效 / upload_r2不设Cache-Control** | 小运维项,长期不动;check_data_integrity已补2项,剩余3项收益极低风险小,投入产出不划算 | 2026-08-21 | docs/r2-migration-implementation-report.md §3.3/§6.2 |
| 32 | **perf小优化: etf_nt缓存 / industry批查** | 共省~0.9s,收益小改动风险大,原建议"暂不动" | 2026-08-21 | docs/perf-p1-plan.md L264 |
| 37 | **美股VIX采集** | 数据缺口,无直接akshare函数,获取成本高收益低 | 2026-08-21 | docs/理财专员使用指南.md §5.6(L458) |
| 38 | **乐咕活跃度 / 东财情绪源** | 源不稳定/接口已禁用,可靠性无法保障 | 2026-08-21 | docs/理财专员使用指南.md §5.6(L459) |
| 89 | **overlap delta可比口径** | 中报vs年报披露范围差异调研无产出,context丢失;问题本身偏学术,实操价值有限 | 2026-08-21 | docs/archive/TASKS-history-archive-20260820.md L97-114 |
| 26 | **R2 board_etf_map与overview自动联动+百分位基线固定化** | P0已解决核心(部署流程已自动联动,百分位漂移极小),再做是画蛇添足——稳定系统不做没验证的加固 | 2026-08-21 | docs/r2-migration-implementation-report.md §3.2/§6.1 |
| 27 | **R2上传失败阻断push+版本校验** | P0告警已加(上传失败notify),阻断是锦上添花;稳定系统不做,怕坏了没验证到 | 2026-08-21 | docs/r2-migration-implementation-report.md §3.3/§6.1 方案3 |
| 28 | **R2 edge cache purge兜底** | P0高频文件ttl=0已根治核心问题,统一purge是仪式感;稳定系统不做多余加固 | 2026-08-21 | docs/r2-migration-implementation-report.md §3.3/§6.1 方案5 |
| 34 | **场外基金阶段3 场内外联动(ETF联接跟踪误差)** | 用户不关注该功能模块,对用户无关 | 2026-08-21 | TASKS.md L65 |
