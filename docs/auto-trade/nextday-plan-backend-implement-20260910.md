# 阶段一后端实施: nextday_plan 计划生成器 + auto_trade_steps 状态机落档

> 实施: implementer agent · 日期: 2026-09-10 · 分支: feat/prd-plan-backend
> 依据: docs/auto-trade/next-day-buy-prd-20260910.md §3(计划生成模块)/§6(实操步骤表格)/§8(干跑)
> 测试基准: current baseline(memory test-baseline-v112-anchor, v1.1.7); 本任务不涉回测, 生成逻辑与回测同构防前视

## 一、交付物清单

| 文件 | 作用 | 落位 |
|---|---|---|
| `scripts/nextday_plan_generator.py` | 次日买入计划生成器(核心) | git tracked |
| `scripts/nextday_plan.sh` | launchd 包装(交易日闸门+日志+失败告警) | git tracked |
| `docs/auto-trade/com.trade.nextday-plan.plist` | launchd plist 档案副本(已安装 ~/Library/LaunchAgents/) | git tracked |
| `docs/auto-trade/README.md` | 索引补指向 | git tracked |
| 本报告 | 实施报告(含复现段) | git tracked |
| `data/nextday_plan.json` | 当日计划本地权威产物(运行时生成, 不 commit) | gitignored |
| `static-site/data/nextday_plan.json` / `auto_trade_steps.json` | 用户可见产物(运行时生成, R2 同步, 不 commit) | gitignored(static-site/data/* catch-all) |

## 二、生成逻辑口径(与回测同构, 防前视)

核心 = 复用 `kelly_posrating.py` 现成模块, **不重写**:

1. `make_passes_fade(fIdx, trade_dims, loss_spec_map, feat_at, s06)` —— S06 per-date 动态基座 + 降亏键过滤
2. `_collect_base_pool(quads, sell_modes, fIdx, pass_fn)` —— 三评级象限 × 全部 sell_modes, baseKey 去重
3. `_position_cap_kept_keys(base_pool, fIdx, K=1)` —— 按 signal_date 分组, 组内排序 track_score DESC→rating→signal→buy_date ASC, 每日 top1

**当日计划 = signal_date == T 且被 K=1 保留的交易**(与回测每日 top1 同口径)。

**buy_date(T+1)**: 权威交易日历 `data/trade_dates.txt`(akshare 缓存, 含未来至当年底)取 `> T` 最小日期,
etf_daily 历史日期集兜底 —— 解决 T=今天时 etf_daily 无下一交易日的问题(§11.4 长假/调休)。

**双校验**(PRD §3):
- `prev_close > 0` 且该 etf 前一日有成交(etf_daily 该 etf `<= T` 最近一条 close, 非停牌)
- 伪跳空剔除同款: `|prev_close / 信号日收盘 - 1| > 20%` 剔除; 信号日收盘 = trades 该笔 current_price(信号日收盘),
  缺失则不拦(诚实降级, 同回测 fail-open 精神)

**amount**: `buy_amount`(trades.buy_amount, 每日资金池 1 万)= 10000(K=1 每日 1 笔, 1 万等分)。
**shares_planned**: `int(10000 / order_price / 100) * 100`(100 份整数倍向下取整, §6.6)。

**auto_trade_steps.json**(§6.2 全表, 追加模式幂等):
- 结构 `{schema_version:"v1", steps:[...]}`
- seq1 行为: date=执行日(buy_date), seq=1, time_slot=09:15, action=buy, order_price=prev_close,
  expected_range=「低开按开盘价成交; 高开等回落至 X 或尾盘兜底」, decision=「9:25 集合竞价: O ≤ X? 是→按O成交; 否→高开等回落触及 X; 14:55 仍未触及→撤单市价兜底」,
  amount=10000, shares_planned=100 份整数倍, status=pending, status_text=待执行,
  signal/track_score/trigger_note/updated_at
- **幂等**: 同执行日(buy_date)seq1 已存在 → 跳过追加不重复写
- 空计划(无信号/T 非交易日): 只写 `{date, empty:true}` 到 nextday_plan.json, 不追加 steps

## 三、上线链路(§22 三步同步)

1. 本地权威: `data/nextday_plan.json`
2. 两树用户可见: `REPO(trade-data)/static-site/data/` + `GIT_REPO(trade)/static-site/data/`
   (nextday_plan.json + auto_trade_steps.json)
3. R2: `upload_r2.py upload-data-files nextday_plan.json [auto_trade_steps.json]` + purge(盘后产物走既有 upload-data-files 段)
4. 通知: `notify.py`(邮件+飞书) subject「明日买入计划 T」body 按 §10 白话样式
   `明日计划: 512480 半导体ETF国联安 | 昨收 1.082 | 买入 1 万元 | 信号: buy_special | 跟踪分 36.2`;
   空计划发「明日无买入计划」; dedup-key=`nextday_plan_{T}` 24h 防同日重复
5. 干跑模式: AUTO_EXEC_ON=false, 本阶段只生成计划+通知书, 不连 easytrader 不真实下单(PRD §8/§9)

## 四、launchd 时点定稿: 20:55

**调研过程**(2026-09-10 `launchctl list` + 逐个 plist `StartCalendarInterval` 实证):

| 时点 | 既有任务 | 结论 |
|---|---|---|
| 20:35 | s06-snapshot(交易日), intraday-snapshot | 数据源定稿, 不撞 |
| 20:40 | daily-brief | 不撞 |
| 20:45 | brief-push | 不撞 |
| **20:55** | **空档** | **本任务落此** |
| 21:00 | backfill-evening, futures-backfill | ❌ 撞, 排除 21:00 |
| 21:10 | turnover-backfill | 不撞但太近 |
| 21:15 | ab-direction-anchor | 不撞 |
| 21:30 | etf-national-team | 不撞 |

任务书初稿提示「21:00 或 20:55」, 实证 21:00 已被 backfill-evening + futures-backfill 占用,
故定 **20:55**(落 20:45~21:00 空档, 晚于全部数据源 20:35 定稿, 秒级任务不抢资源)。
plist Weekday 1-5, RunAtLoad=false, ExitTimeOut=600。日志 `data/logs/nextday_plan_launchd.log`(固定名 append,
标准开始/结束行, schedule-monitor 可直读)。非交易日脚本内闸门跳过(force 可补跑)。

## 五、自测记录(逐项)

| 项 | 命令/场景 | 结果 |
|---|---|---|
| 语法 | `bash -n nextday_plan.sh` / `python3 ast.parse` / `plutil -lint plist` | 全 PASS |
| 有信号日 | `--date 20260908 --dry-run` | T=20260908 → 512820 银行ETF汇添富 prev_close=1.476 buy_date=20260909(trades 最新信号日) |
| 空计划 | `--date 20260910 --dry-run` | T=今天无信号 → `{date, empty:true}`; buy_date=20260911 正常(日历含未来) |
| 幂等 | 真落盘两次同 date | 第二次 `auto_trade_steps 已含执行日 date=20260909, 幂等跳过追加` |
| R2 同步 | 真跑 --no-notify | upload-data-files 退出码 0, purge 成功; curl ssd.fx8.store/data/nextday_plan.json 读到 |
| notify 链路 | notify.py --dry-run | email/feishu 通道 OK(telegram 未配置属现状) |
| launchd | `bash nextday_plan.sh force --date 20260910 --no-notify` | 退出码 0, 日志标准开始/结束行齐全 |
| 前端结构对齐 | auto_trade_steps seq1 字段逐项对照 §6.2 全表 | 14 字段全齐(缺 actual_price/actual_shares/entrust_no/remark 属后续状态流转回填, 生成期不填) |

**注意**: 与前端并行 agent 的依赖 = nextday_plan.json + auto_trade_steps.json 结构, 本实现严格按 PRD §6.2 字段一字不差(前端按 §6.2 渲染)。

## 复现

- **脚本**: `scripts/nextday_plan_generator.py`(生产入口) + `scripts/nextday_plan.sh`(launchd 包装)
- **输入依赖**: `static-site/data/signal_kelly_trades.json` + `signal_kelly_backtest.json` + `kelly_mode_s06_state.json`
  + `kelly_loss_features.json` + `data/etf_national_team.db`(etf_daily) + `data/trade_dates.txt`(交易日历, 含未来)
- **重跑命令**:
  ```
  # 干跑(只计算打印, 不落盘不 R2 不通知)
  REPO=/Users/linhuichen/code/trade-data .venv/bin/python scripts/nextday_plan_generator.py --date 20260908 --dry-run
  # 真跑(落盘两树 + R2 + 通知; launchd 20:55 同款)
  REPO=/Users/linhuichen/code/trade-data .venv/bin/python scripts/nextday_plan_generator.py
  # launchd 全链路(交易日闸门 + 日志)
  bash scripts/nextday_plan.sh force --date 20260908 --no-notify
  ```
- **关键口径**: 宇宙 = S06 动态基座 + 降亏键过滤 + K=1 每日 top1; 每日资金池 1 万等分;
  buy_date = 交易日历中 T 的下一交易日; 挂单价上限 = 该 etf T 日(<=T 最近交易日)收盘 prev_close;
  伪跳空阈值 ±20%; 数据截止 2026-09-10(etf_daily) / trades generated_at 2026-09-10 19:06。
- **上线时点**: 交易日 20:55(20:35 s06-snapshot 定稿后, 21:00 backfill 前空档)
