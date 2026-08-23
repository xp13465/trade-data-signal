# deprecated_g2bug_20260823(g2 门 bug 修正前的旧 json 存档)

- 归档原因:`r2_common.py` L113 `ma_impr = base−new` 反号(应为 new−base),导致 2026-08-22~23 生成的
  本目录所列 json 中所有 `gates.g2`/`gates_pass`/`d_mayaug`/`d_apr`(取负版)字段带系统性符号失真。
  根因审计与影响面全表见 `../../../../../g2-gate-audit-20260823.md`(即 docs/kelly/analysis/g2-gate-audit-20260823.md)。
- 归档日期:2026-08-23;修正后重跑产物直接覆盖 data/ 下同名文件,本目录仅作 §5.3 可逆性回退用,勿删勿改。
- 文件清单(13):mine11_univariate / mine12_equity / mine13_calendar / mine14_subgroup /
  mine16_candidates / mine18_windows / mine18_combos / mine19_pareto / mine20_pool / mine21_tour /
  mine22_joint / mine24_global_search / mine24_compare(均为修正前最后版本,mtime 见文件)。
- 回退方式:如需恢复旧口径数据,把对应文件 cp 回上级 data/ 即可(但 g2 失真仍在,不建议用于结论)。
