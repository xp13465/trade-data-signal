# position/ 凯利仓位类报告索引

> 仓位上限/每日池/策略AB/分仓行为/回撤等仓位类报告。**如何新增**:报告放本目录,脚本放 `scripts/`,同步更新本索引。

| 文档 | 说明 |
|---|---|
| kelly-ghi-avsp-method-sweep.md | **A法vs P法同池同cap真实价矩阵扫描**(2026-08-30, 同647池 5档cap A法(满仓不买)vs P3d(先卖年轻) 全比: P法净利恒>A法 Δ+12,971~+24,247, 续买增量11,394~55,794覆盖强平成本, P3d价值命题不证伪; 强平年轻仓非全亏(10万420笔196赢/224亏净-31,547)) |
| kelly-ghi-real-price-rebase.md | **🏆GHI 三档真实价格重算唯一权威数字**(2026-08-30, 强平日真实 accum_nav 重算强平盈亏, G=157,743/157.74% I=140,585/156.21% H=115,157/230.31%, 替代 b0/b1 估算, 含按年分解+29笔预估根因证据) |
| trade-methods-principle.md | **🌟交易方法原理拆解**(2026-08-30: 短线A-F满仓不买 / H止损滚A法全场最高 / G·I卖信号少→P<3d吃短线, 数据+口诀+一键复现) |
| kelly-nextday-batch-limit-sop.md | **次日分批挂单买入 SOP 回测**(2026-08-15,兜底 N=K 每日池 G K1 净+861,375/53.17%,比次日开盘+6.1万) |
| kelly-strategyAB-exhaustive.md | **策略A(固定拆K)vs 策略B(每日池等分)穷举对比**(2026-08-14,本轮新增) |
| firstcol-badge-linebreak.md | 信号凯利回测首列 SPAN 独立换行(纯前端 CSS display:block,2026-08-14) |
| kelly-dailypool-exhaustive-rerun.md | 每日池口径穷举重跑(权威基线) |
| kelly-fade-filter-interaction.md | fade 过滤交互 |
| kelly-g-mode-recheck.md | G 模式复核 |
| kelly-ghi-continuous-cap-sweep.md | GHI 连续资金上限扫描 |
| kelly-ghi-method-full-sweep.md | GHI 方法全谱扫描 |
| kelly-ghiposition-manage-matrix.md | GHI 仓位管理矩阵 |
| kelly-ghiposition-method-sweep.md | GHI 仓位方法扫描 |
| kelly-nextday-open-backtest.md | 次日开盘回测 |
| kelly-position-cap-20x-limit.md | 仓位上限 20x 本金限制 |
| kelly-position-cap-k-sensitivity.md | 仓位上限 K 敏感性 |
| kelly-position-filter-backtest.md | 仓位过滤回测 |
| kelly-poscap-history-panel-removal-check.md | **「AI仓位建议·历史回测」面板移除核对**(2026-08-15: 面板=每笔1万·裸G已废弃, 核心结论已被K评级+按年表+建议指南继承, 可放心移除) |
| positioncap-review.md | 仓位上限审查 |
