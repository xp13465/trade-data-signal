# #19 情绪日历后端数据生效记录(2026-08-20 00:31)

#19「首页近期冰点日」改造成近90日情绪日历:前端已上线(走降级原冰点展示),后端 queries.py 注入 `sentiment_calendar` 已 merge main,本记录 = 重生成数据产物让 overview.json 真正带 `sentiment_calendar`,情绪日历正式生效。

## 变更内容

纯数据层 deploy(前端代码已在 main,后端注入逻辑已 merge),未改任何源码。

- **后端注入**(已完成,非本次):`app/queries.py` overview 构建近90日 `sentiment_calendar`(date-join freeze+signals,按 date 降序,signals 组内 buy>buy_aux>sell)。源头见 `docs/market-state/sentiment-signal-freeze-merge-research.md`。
- **前端消费**(已完成,非本次):`static-site/app.js` `_renderSentimentCalendar`(8abefd7c2,merge 于 cfe8e76e1 之前的 feat 分支),主分支已含(20260820-a365)。
- **本次**:跑 `bash scripts/deploy.sh` 完整管线(深夜安全窗口),export.py 重算 overview.json 注入 `sentiment_calendar`。

## 数据字段结构(前端 _renderSentimentCalendar 读取,必须逐项对齐)

```json
sentiment_calendar: [
  {
    "date": "20260818",            // 日期(YYYYMMDD),整体按 date 降序
    "freeze":  [{"score_id":"s.fear_greed","value":16.13}],  // 冰点日(score_daily is_freeze=1, 已过滤 low_alert)
    "signals": [{"index_id":"s.*","signal":"buy|buy_aux|sell","reason":"..."}]  // 情绪分买卖点信号
  }
]
```

- freeze: `score_daily WHERE is_freeze=1 AND score_id!='low_alert'`(过滤低质 low_alert,非<20冰点混标)
- signals: `signal_daily WHERE index_id LIKE 's.%'`(只情绪分,无未入样污染)
- 同日 freeze+signals 并存(如 20260708/20260623);日期降序;无日期缺失条目

## 数据生效验证(§22 一致性 + 数据校验)

| 项 | 结果 |
|---|---|
| deploy.sh 退出码 | 0(deploy 结束 2026-08-20 00:31:21) |
| 线上 overview.json 带 sentiment_calendar | ✅ 存在,27 长度,0 malformed,日期降序正确 |
| freeze 有真实内容 | ✅ 17 日,fav 如 20260730 四指数冰点(cyb 18.75/kc50 14.2/csi500 18.03/csi1000 18.77) |
| freeze 无 low_alert 污染 | ✅ score_id 集合 = {sentiment_*},无 low_alert |
| signals 无未入样污染 | ✅ index_id 全是 `s.*`(情绪分买卖点,9 个指数) |
| 同日双列 | ✅ 20260708/20260623 两日(stable 样例) |
| 旧字段 recent_freeze | ✅ 仍保留(旁路字段不动既存,§5.3 核心保障) |
| 前端展示层上线 | ✅ 线上 app.min.js 含 `_renderSentimentCalendar`/`sentiment_calendar`/`近 90 日情绪日历`,不再走降级 |
| 版本串一致(§24⑤) | ✅ 线上 index `?v=20260820-a365` == 本地,本地 app.min.js hash == 线上 hash(5ea096c0...) |
| git main | ✅ deploy 后 main 无脏数据变更(前端 min 内容与 HEAD 一致,gzip "Everything up-to-date") |

## 复现

- **脚本**:`bash scripts/deploy.sh`(完整管线)
- **输入依赖**:`trade-data/data/sentiment.db`(score_daily/signal_daily)+ `static-site/export.py`
- **重跑命令**:
  ```bash
  cd /Users/linhuichen/code/trade
  REPO=/Users/linhuichen/code/trade-data bash scripts/deploy.sh
  ```
- **验证命令**:
  ```bash
  curl -s https://ss.fx8.store/data/overview.json | python3 -c "import json,sys;d=json.load(sys.stdin);sc=d.get('sentiment_calendar');print('have' if sc else 'missing', len(sc))"
  curl -s https://ss.fx8.store/ | grep -oE 'app\.min\.js\?v=[0-9]+-[a-z0-9]+'
  curl -s https://ss.fx8.store/app.min.js | md5  # 与实际文件 md5 比对
  ```
- **数据截止**:score_daily/signal_daily 主库至 2026-08-18(sentiment_calendar 首条 date=20260818),deploy 时间 2026-08-20 00:31

## 关键口径一句话

近90日情绪日历 = score_daily is_freeze=1(过滤 low_alert)的冰点日与 signal_daily s.% 情绪分买卖点信号按 date 合并,每日一张行,同日双列,日期降序。
