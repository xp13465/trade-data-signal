# 实现方案（已批准 2026-07-05）

> 需求见 [REQUIREMENTS.md](REQUIREMENTS.md)。

## 架构
```
akshare(东财/新浪) ──采集──► SQLite ──计算──► 综合分/买卖点 ──► FastAPI ──► ECharts 看板
launchd 每日15:30 触发 ──────┘                手动补录 ─► POST /api/manual (覆盖同日自动值)
```

## 目录
```
config/{indicators,scores,signals}.yaml   # 配置驱动（可插拔）
app/{main,db,calendar,backfill,scheduler}.py
app/collector/{base,fetchers,runner}.py
app/compute/{normalize,sentiment,cross,signals}.py
app/routes/{overview,a_stock,hk,global_,sentiment,manual}.py
web/{index.html,app.js,style.css,vendor/echarts.min.js}
launchd/com.trade.sentiment.plist
```

## SQLite 库表
- `daily_metric(date, metric_id, value, source, updated_at)` — 单值日指标（长表，可插拔核心）
- `index_daily(date, index_id, open/high/low/close, pct_change, amount)` — 指数 OHLCV
- `board_daily(date, board_type, board_name, pct_change, net_inflow)` — 板块 Top 榜
- `score_daily(date, score_id, value, is_freeze, is_overheat, components)` — 两个综合分（components=JSON 分项贡献）
- `signal_daily(date, index_id, signal, reason)` — 买点/卖点
- `manual_entry` / `collect_log` / `alert_log`

## 计算
- 归一化：120 日滚动百分位 → 0–100；反向指标取反
- §4 A股综合情绪分：6 分项加权（涨跌家数比25/涨停20/炸板15/连板15/成交额10/北向15），<20冰点 >80过热
- §6 跨市场综合评分：全指标归一化后去 max+min，其余均值
- §7 买卖点：情绪(§6<20或>80) + 技术面(MA5×MA20金叉死叉 / 不创新低3日 / 放量滞涨) 双确认

## 阶段
P1 地基 → P2 采集 → P3 计算 → P4 回填 → P5 定时 → P6 API → P7 前端 → P8 验收
