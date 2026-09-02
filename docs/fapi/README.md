# 同花顺 FAPI 接入研究/实施落档(docs/fapi/)

> 同花顺金融开放平台(FAPI)接入的**统一落档目录**。方案报告/实施报告放根目录,探针脚本放 `scripts/`,launchd 模板放 `launchd/`。
> 落档规范:CLAUDE.md §23.5(研究产物三层落档:报告/脚本/数据 + 建索引,塞入即归类)。
> 背景:解决 mootdx 断片 + BaoStock T+1 痛点 + 北交所缺口,引入 T+0 官换届兜底(§15.1 异源互备)。

## 目录职责一览

| 文件/子目录 | 用途 | 状态 |
|---|---|---|
| [fapi-integration-plan-20260901.md](fapi-integration-plan-20260901.md) | 接入方案 + 试点验证(T+0 日线/涨停池/龙虎榜/THS 指数)+ P0-P2 优先级 | 已随上游 commit |
| [fapi-p0-implementation-20260902.md](fapi-p0-implementation-20260902.md) | **P0 日线采集落地实现报告**(脚本/表/launchd 模板/实测对照/复现) | 本次 commit |
| [scripts/probe_fapi.py](scripts/probe_fapi.py) | 一次性探针(dump/涨停/龙虎榜/指数/snapshot,只读) | 已随方案 commit |
| [launchd/fapi-daily.plist](launchd/fapi-daily.plist) | 18:10 日采集模板(已挂载 2026-09-02,观察期双写) | 本次 commit |

## 关键落地资产

- 采集脚本:`app/collector/fapi_daily.py`(dump 下载→pyarrow→UPSERT `fapi_daily_raw`)
- 新表:`data/stock_daily.db:fapi_daily_raw`,主键 `(thscode, date_ms)`,与 mootdx_daily_raw 语义对齐
- 状态:纯新增试点(未 bump/未 deploy),launchd 已挂载 com.trade.fapi-daily(2026-09-02 用户拍板启动观察期),每日 18:10 自动采集双写互证,≥1 周后评估转主(§23.7)
- 风险:key 只存 .env,禁入 git/日志/报告;FAPI 单一外部依赖,只做兜底不替换主链

## 复现/重跑

```bash
cd /Users/linhuichen/code/trade
.venv/bin/python -m app.collector.fapi_daily            # 常规增量 daily-k-10d
.venv/bin/python -m app.collector.fapi_daily --full     # 强制全量 daily-k
```
详细复现见 [fapi-p0-implementation-20260902.md](fapi-p0-implementation-20260902.md) `## 复现` 段。