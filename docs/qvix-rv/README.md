# QVIX RV 近似兜底（真异源互备）

QVIX（中国波指，期权隐含波动率）主源 optbbs 宕机时的真异源兜底方案文档与数据。

## 文档
- [qvix-rv-fallback.md](qvix-rv-fallback.md) — 设计报告（背景/方案/RV 口径/fallback 链路/代码改动/数值验证/复现）

## 脚本
- [scripts/calc_rv.py](scripts/calc_rv.py) — RV 独立复现脚本（拉 510050/510300 日线 → 20 日滚动年化波动率 → 沉淀 JSON）

## 数据（2026-08-14 收盘生成）
- [data/rv_510050.json](data/rv_510050.json) — 50ETF 全历史 RV 序列（5201 行，最新 20260814 = 16.607）
- [data/rv_510300.json](data/rv_510300.json) — 300ETF 全历史 RV 序列（3436 行，最新 20260814 = 19.658）

> 生产调用不读本目录脚本/数据（防双份维护分叉）：RV 计算逻辑在 `app/collector/fetchers.py::_qvix_rv_series`，
> 数据来源在 `app/collector/etf_national_team.py::fetch_etf_ohlc`（sina 主源 + mootdx fallback）。
> 本目录仅作落档复现与溯源依据。
