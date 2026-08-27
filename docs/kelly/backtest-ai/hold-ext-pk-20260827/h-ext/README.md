# hold-ext-pk-20260827/h-ext(H 档带帽回本等待补测)

Task#11 延伸:补 cc 报告 §十.3 留尾的「延长上限 N+到期强制卖」受限版。H 档=亏损单等净回本收盘卖+超帽日无条件卖(与引擎卖法"H(sell+追止损)"完全不同义,防撞名见报告§一)。
- 报告:`h_report.md`(结论+全维度 §5.1⑤+复现节)
- 脚本:`h_ext_backtest.py`(复用 ../cc/ 引擎;`--anchors` 先验基线,`--all` 全矩阵)
- 数据:`h_anchors.json`(锚点+双实现对照)/`h_variants.json`(逐笔明细)/`h_matrix.json`(ledger/replay 四档cap/占用分布/恢复期/按年/分半/熊市窗/checks 机检)
- 状态:已完成(2026-08-27);主推=HT20(总持有20td带帽),进区间 K∈{5,10},避开 K=20~30 中段;机检四道全 PASS
