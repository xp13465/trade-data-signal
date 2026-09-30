# a_fund_main 2026-09-30 缺口核查(tester 只读)

> 结论:**风险窗口已过,数据正常**。a_fund_main(主力净流入)2026-09-30 已落数据,16:35 槽天然兜底生效。

## 背景
今日为国庆假期前最后交易日,`a_fund_main` 六源全败,16:35 / 21:00 两槽为唯一天然兜底。核查两槽是否补上。

## ① 数据层:最新日期 = 20260930 ✓
- 线上 `https://ss.fx8.store/data/overview.json` → `a_fund_main_6m` 尾部:
  - `20260929 65.24353024` → `20260930 -194.73`(**新增**)
- 云上 `sentiment.db` `daily_metric` 表(`metric_id` 窄表):
  - `a_fund_main`: `[('20260930', -194.73), ('20260929', 65.24), ('20260928', -914.00)]`
  - `a_fund_margin`: 最新 `20260929`(融资余额 T+1,源当日无新数据,日志标注"缺口但源无新数据(ok)",非故障)

## ② 日志层:16:35 槽 ok 补采,21:00 槽无重复补采
- `data/logs/backfill_20260930_1635.log`:
  - `[ok] a_fund_main +1 rows`
  - `direct metrics 补采 ok=3 gap=0 fail=0`
  - `backfill_metrics.sh 结束 2026-09-30 16:51:05 退出码=0`
  - `[gap] - a_fund_margin latest=20260929 缺口但源无新数据(ok)`(融资余额源无新数据,正常)
- `data/logs/backfill_20260930_2100.log`:仅 a_fund_margin 源无新数据提示,无 a_fund_main 输出 ⇒ 16:35 已补,21:00 无新数据不再补采

## ③ 告警层:无 a_fund 相关条目 ✓
- `data/alerts/latest.md`、`data/alert_state.json`、`trade-data-signal/data/alerts/latest.md`、`trade-data-signal/data/alert_state.json` grep `a_fund|fund_main|fund_margin` 均无匹配。

## 前端影响
无缺口,前端展示位(首页 KPI/资金面卡、A股走势、市场宽度页)正常显示 20260930 值,无空值/旧值残留。

## 复现段
```bash
# 线上
curl -sA "Mozilla/5.0" "https://ss.fx8.store/data/overview.json" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['a_fund_main_6m'][-2:])"
# 云上(只读)
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'cd /home/ubuntu/code/trade-data/data && python3 -c "import sqlite3; db=sqlite3.connect(\"file:sentiment.db?mode=ro\",uri=True); print(db.execute(\"SELECT date,value FROM daily_metric WHERE metric_id=? ORDER BY date DESC LIMIT 2\",(\"a_fund_main\",)).fetchall())"'
# 日志
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'grep -n -i "a_fund_main" /home/ubuntu/code/trade-data/data/logs/backfill_20260930_1635.log'
```
