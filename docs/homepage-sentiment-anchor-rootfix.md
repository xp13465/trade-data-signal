# 首页情绪卡「当前值停旧、文件已有最新」锚定根治(2026-08-18)

## 现象
8/18 首页 9 张情绪卡(a_sentiment/cross_market/fear_greed/sentiment_sz50/hs300/csi500/csi1000/cyb/kc50)
overview.json `today.scores` 全停 date=20260817,但 sentiment-1y.json 数组末尾已有 20260818
(弹窗读到 818、卡片读到 817 → 用户看到不一致)。实证(16:38 export):
- 旧 overview today.scores: 9 卡全 date=20260817(含 sentiment_csi500=817/82.34)
- sentiment-1y 末尾: 8 卡已 20260818(a_sentiment 本身停 817,因为它确实缺当日)

## 根因链(主控已用 researcher 定位,实施据此根治)
1. 【已修复,勿动】8/15 b46584b3f 异源兜底重构误删 `cross_check_zt_pool` 函数定义 →
   intraday width 采集 ImportError → a_sentiment 缺分项算不出当日。已由 a084cd74a 恢复(8/18 15:55,已在 main)。
2. 【本次根治①】app/queries.py overview() today.scores 的 date **单一锚定 a_sentiment 的
   max(date)**:a_sentiment 单指标缺失 → 9 张情绪卡 today.scores 全拖停 8/17。
   而 sentiment-1y/6m 是逐 score_id 各自取 max(date) → 不一致。
3. 【本次根治②】intraday width 采集 `from .fetchers import cross_check_zt_pool` 在函数顶部 import,
   import 失败 = 整个 width 采集崩,一个指标都写不进 → a_sentiment 6 分项全缺 → 出不了当日分。
   sentiment.py 已有 avail_count>=3 重归一化机制,但 width 全缺时无法生效。
4. 【本次根治③,顺带】a_fund_main 跨日标注 bug:8/18 02:36 写入时 A 股未开盘,
   东财/akshare 盘前预生成「今日行」=昨日收盘值(8/18 行=8/17 收盘 800.70),日期标当日 →
   daily_metric 出现「昨日值标当日行」(8/17 与 8/18 行同值 800.70)。

## 改动(4 项,全部本地分支,上线由主控安全窗口安排)

### ① today.scores 锚定加固 — app/queries.py overview()
- scores 构建(L820-832):改为每张卡独立取 `max(date)<=last_trading_day()` 的最新行,
  每行自带 `date`=该卡实际最新日期。单指标缺失(如 a_sentiment 缺当日)不再拖垮其它卡。
- today.scores 组装(L1456):`{**v, "date": v.get("date") or score_date}` 保留每卡独立 date,
  不再强制覆盖为 score_date。
- 效果:与 sentiment-1y/6m(score_series 逐 score_id 取 max)口径完全一致(§22)。
- 说明:overview.date 主字段(L1446)仍用 score_date(a_sentiment 锚定兜底),属页面级评分日
  基准(盘中 date 过时另见 docs/pending-features-index.md #62),本次不动(§23.7 冻结)。

### ② intraday width 容错 — app/collector/intraday_snapshot.py
- `from .fetchers import cross_check_zt_pool` 从函数顶部(一次崩全崩)改为 try/except 容错:
  定义缺失/import 失败 → `cross_check_zt_pool = None`,不阻断整个 width 采集。
- step2/step3 交叉验证调用处对 None 降级:cross 不可用时直接走 fallback spot 兜底或记 error,
  不崩。step1(spot 采 up/down/amount)、step4(炸板率)照常执行 → width 部分指标写入 →
  a_sentiment 有 ≥3 分项(ratio/amount 等)可出当日分(avail_count>=3 重归一化,见 sentiment.py L60-63)。

### ③ 一致性校验 — scripts/check_data_integrity.py
- 新增 `check_sentiment_card_date`:比对 overview.json today.scores 各情绪卡 date 与
  sentiment-1y.json 对应序列末尾 date,任一不一致 = FAIL 阻断上线(§22 扩展,
  防「文件有最新、当前值停旧」再犯)。
- 注册进 run_all_checks(在 check_overview 后),deploy.sh L132 调 `--deploy-mode` 自动带上。

### ④ a_fund_main 跨日标注 — app/collector/direct.py
- 新增 `_drop_preopen_today(rows)` 辅助函数:A 股开盘前(本地 <09:30)过滤「今日行」。
  盘前东财/akshare 预生成的今日行 = 昨日收盘值,日期却标当日,丢弃之(当日真实值盘中/盘后
  采集覆盖,不丢数据)。盘后(≥09:30)不过滤(今日行是真实值)。
- 在 fetch_market_fund_flow 五个数据源 return 点套用(主源/akshare/第三源过滤今日行保留历史,
  第四/五源盘前返回空 → collect_direct 转 fail 记 error,宁可 error 不污染当日)。

## 复现
- 脚本/验证命令:
  - 自测 1(单指标缺失不拖垮):`cd /Users/linhuichen/code/trade-data && .venv/bin/python -c
    "from app import queries; from app.db import get_conn; ov=queries.overview(get_conn(), {'metrics':[]});
    print([(k, v.get('date')) for k,v in ov['today']['scores'].items()])"`
    期望:a_sentiment=20260817(缺当日), 其余 8 卡=20260818。
  - 自测 2(与 sentiment 序列一致):本地 export overview+sentiment-1y 后逐卡比对 date(0 mismatch)。
  - 自测 3(校验 PASS/FAIL):`scripts/check_data_integrity.py --data-dir <dir>` 跑 check_sentiment_card_date;
    正常数据 OK,人为把某卡 date 改旧 → FAIL。
  - 自测 4(盘前过滤):monkeypatch datetime.now 为 08:00 → `_drop_preopen_today` 丢弃今日行;
    16:00 → 保留。
  - 自测 5(width 容错):del fetchers.cross_check_zt_pool 后 mock akshare 池空,
    `_collect_intraday_width_metrics()` 不崩,step1 仍采到 up/down/amount。
- 输入依赖:data/sentiment.db(score_daily / daily_metric)、static-site/data/overview.json、sentiment-1y.json。
- 数据截止:2026-08-18(DB 中 a_sentiment=8/17,其它 8 卡=8/18,天然复现「单指标缺失」)。
- 关键口径一句话:overview today.scores 每张情绪卡独立取自身 score_id 的 max(date)<=最近交易日,
  单指标缺失不拖垮其它卡,与 sentiment 序列逐 score_id 口径一致。

## 自测清单(§23.2 三铁律)
- [x] 修完整:全 9 卡独立(非只中证500),自测 1 验证 9 卡各自 date。
- [x] 自测完成:5 项自测(锚定/一致性/校验/盘前过滤/width容错)全过。
- [x] 排查同类(§23.3):grep queries.py 确认无其它「单指标锚定拖多卡」模式;
      today.metrics(KPI 卡)本就逐指标独立;sentiment 6m/1y 本就逐 score_id;score_date 其余
      用途(窗口起点/overview.date)为页面级基准非「9 卡展示停旧」,不动(§23.7 冻结)。
- [x] §21 公示:本任务不改评分算法/权重/分段,只改数据锚定取法,app.js L15479/L15509/L18087
      「6分项+缺项重归一化」公示无需改(算法没变)。
- [x] §23.4 冲突预防:目标文件无其它 worktree 未 merge 改动,a084cd74a 已在 main。
