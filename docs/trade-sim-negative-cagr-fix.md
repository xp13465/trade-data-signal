# trade_sim 负值年化 complex 崩溃修复（g.cn_us_spread 首次产出）

## 问题
`scripts/simulate_trade.py _build_result` 年化公式 `((final_total / TOTAL_CAPITAL) ** (1 / years) - 1) * 100`
对 **终值本金倍数 ≤ 0** 的指数（如 `g.cn_us_spread` 中美10年利差，终值可为负）算「负 base 的分数次幂」
返回 Python `complex`。`round(complex)` 抛 `TypeError: type complex doesn't define __round__`
→ 该索引的 trade_sim JSON **永远生成失败**，历史从未产出数据。

已确认：origin/main 旧代码同样崩 = **历史遗留，非 2026-08-19 费率回归**（费率 A merge 后 simulate_trade.py
是干净 base）。

## 修复（负值健壮化，正常正收益指数逐位不变）
1. `_build_result` 年化：`final_total / TOTAL_CAPITAL <= 0` → `annualized = None`（标"不可算"，
   不进 round、不生成 complex）。正常指数（倍数>0，years>0）维持原公式逐位不变；years<=0 仍返回 0。
2. `_build_result` summary `annualized`：`None` 时不 round，输出 `None`（JSON → null）。
3. `_scenario_panel` 年化卡：`None` 时显示 `N/A（终值倍数≤0，无实数复合年化）`。
4. `_render_window_table` 对比表：`b_annual/w_annual` 的 max/min 过滤 None；
   `cmp_cell` 对 None/最优最坏为 None 时输出灰字 `N/A`。
5. `compare_fee_configs` `annualized_diff`：default/custom 年化任一为 None 时输出 None，不崩。

## 受影响文件
- `scripts/simulate_trade.py`（仅后端盈亏年化口径修复；**未碰 app.js/lab.js/前端**）

## 验证
- 单元逻辑：随机正常指数 5 例新旧公式 abs 差 <1e-9，逐位一致；负值→None；years=0→0。
- sh 全量 165 个 summary annualized：修复前(git stash 旧代码) vs 修复后逐位一致（0 差异）。
- `g.cn_us_spread` 重算不再崩，JSON 首次产出（stats+full），annualized 出现 None/正值混合
  （负值窗口标 None，正值窗口正常出数）。
- 线上 R2：`https://ssd.fx8.store/trade_sim_data/trade_sim_g.cn_us_spread_stats.json` HTTP 200。

## 复现
- 依赖：主库 `trade-data/data/sentiment.db`（含 signal_daily g.cn_us_spread 111 行到 2026-08-03）+
  `static-site/data/global-all.json`（cr_us_spread 价格序列）。
- 单跑（修复后）：`.venv/bin/python scripts/simulate_trade.py --index g.cn_us_spread`
- 全量：`bash scripts/update_lab.sh`（含 simulate_trade --all JSON + R2 上传）
- R2 上传：`REPO=<产物所在仓库> .venv/bin/python scripts/upload_r2.py upload-trade-sim-json`
  （上传 static-site/data/trade_sim/*.json 全部 → trade_sim_data/ 前缀 + purge CF edge，内部已分批）
- 数据日期：2026-08-19（g.cn_us_spread signal 到 2026-08-03）
- 关键口径：终值本金倍数 ≤ 0 → 年化 null（不可算）；> 0 维持原复合年化公式。
