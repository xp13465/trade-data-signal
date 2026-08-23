# 弃用孤儿数据(2026-08-23 审查后归档)

本目录三个文件(mine23_bulls.json / mine23_worstmonths.json / mine23_w10.json)**无任何生成脚本、不可复现**,且数字与权威 compare 链路矛盾(独立重放已仲裁 compare 为准):

- `mine23_bulls.json`:A/B 列为 on8 混口径被标为 on9(A 2014-15 +5,853.92=A_on8,on9 权威 +5,120.18;A 2025长牛 +40,496.94=A_on8,on9 权威 +42,688.04),审计字段见 `../mine24_compare.json` 的 `bulls23_audit`。
- `mine23_worstmonths.json`:recent_months 的 A/B/C 在 2025-09/10/11、2026-01/02/06 与权威 `mine24_compare.json recent_12months` 矛盾(如 A 2026-06 本文件 -1,620.51,权威 -631.33)。
- `mine23_w10.json`:w5check 近5年 A=72,378.08 与权威 74,764.21 矛盾。

权威替代:`../mine23_compare.json`(P0/P1/A/B/C on8+on9 全维)+ `../mine24_compare.json`(含 bulls/worst10/recent_12months/modes_af_audit/bulls23_audit)。

证据全文:../../../../mine23-24-review-20260823.md(docs/kelly/analysis/ 下)。

⚠️ 注意:`../mine24_compare.py` L242 曾硬引用 `data/mine23_bulls.json` 做四牛市窗口端点验证——如需重跑该脚本,先把 `mine23_bulls.json` 临时拷回上级 data/ 目录(P0/P1/C 序列仍逐位可用,A/B 列勿作断言),跑完再移回本目录。
