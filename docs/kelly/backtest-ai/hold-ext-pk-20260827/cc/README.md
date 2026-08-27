# hold-ext-pk-20260827/cc(Task#11 cc侧,Claude Code 执行方)

亏单延长持有双卖法可行性穷举回测(vs codex 双跑):三降亏模式 S06/A(on9)/NEW14+1 × 卖法{基线10td, V1回本即卖, V2等卖出信号(+G/T+1敏感)} 全矩阵。
- 报告:`cc_report.md`(结论+全维度+复现节)
- 脚本:`cc_hold_ext_backtest.py`(复现命令在报告##复现节)
- 数据:`cc_anchors.json`(锚点对照)/`cc_selection.json`/`cc_variants.json`(逐笔明细)/`cc_matrix.json`(聚合矩阵)
- 状态:已完成+口径已拍板(2026-08-27);V2 主口径=仅纯 sell(G语义,用户拍板),H 档=对照列「用户未选,仅对照」
- 2026-08-27 晚用户拍板:V2 主口径=仅纯 sell(G语义),H 档降级对照列;报告 §一/四/六/七/九/十 已切换重写并机检(BAD=0)。
