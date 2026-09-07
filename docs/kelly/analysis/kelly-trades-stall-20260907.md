# 信号凯利回测 + 首页模拟回测弹窗 交易记录停更根因排查(2026-09-07)

> 用户反馈:两处交易记录"只到 9/3",今天(2026-09-07 周一)理应看到 9/4(周五)甚至 9/7 的交易。
> 排查 agent:role-researcher | 测试基准:current baseline(v1.1.7,非回测口径变更,纯数据供给链路排查)
> 日期:2026-09-07 22:47

## 一、结论摘要(根因五条链)

| # | 结论 | 证据 | 类型 |
|---|---|---|---|
| R1 | 9/7 信号今天不成交是**设计预期**,非故障 | signal_kelly_backtest.py L555-569 KELLY_BUY_NEXTDAY=1:买入价=信号日 accum_nav × (次日 open/信号日 close),9/7 信号的次日=9/8(未发生)→ `_next_trading_day` L506-511 返回 None → return None(L564-565) | 设计 |
| R2 | **9/4 信号不成笔 = 根因**:159023/159173 两只 ETF 的 9/7 accum_nav 缺失(9/7 OHLC 采集返空 + accum-nav 补拉失败),回测交易日序列基于「有 accum_nav 的日期」(L499),9/4 信号定位不到 9/7 次日 → `nxt_open=None` → 9/4 信号被丢弃 | 生产 DB 159023/159173 9/7 accum_nav 均为 NULL;当前全量回测 9/4 仅 562510 成笔 | 数据缺口 |
| R3 | 21:30 第二次 backfill 补齐后,deploy 被 **check_task_state.py 僵尸巡检 cron FAIL 阻断**(§23.12-1 FAIL 阻断上线)→ 新 trades 未上线,线上仍是 20:12 旧版 | backfill 日志 20260907_2130:zombie_crons FAIL(3 处)→ "✗ deploy 失败 (rc=1)" | 部署阻断 |
| R4 | 前端默认模式 A 在 20:12 数据下 max sell_date=20260903,用户看到"9/3"=数据真实状态 + 默认视图 | 20:12 trades 各模式 max sell:A/B/C/D/F=20260903,E/H/J=20260904 | 展示 |
| R5 | 机检盲区:check_signal_accum_nav_lag 只验「最新 accum_nav 日期」不验「覆盖率/单只缺口」→ 9/7 总量有(1197 只)lag=0 PASS,159023/159173 个体缺口漏检 | check_data_integrity.py L892-942 + update_all 日志 L162 "滞后 0 交易日" | 机检盲区 |

## 二、根因链完整时序(2026-09-07)

| 时刻 | 事件 | 状态 |
|---|---|---|
| 17:50 | update_all 启动(launchd),4 pipeline 并发 | - |
| 20:07 | etf backfill 启动(launchd),OHLC 采集 1501 只 ETF,146.4s | 正常 |
| 20:09:33 | OHLC 入库 7433 行;**159023/159173 等深市 ETF 主源 sina+fallback mootdx 返空**(WARNING),9/7 open/close/accum_nav 缺失 | 部分失败 |
| 20:09:50-20:10:27 | accum-nav 阶段:缺失 50 行补 35 行(只补历史缺口,未覆盖 159023/159173 的 9/7) | 补集不足 |
| 20:12 | update_all O1 deploy export 生成 signal_kelly_trades.json(generated_at=2026-09-07 20:12):9/4 信号三只 ETF 9/7 accum_nav 均缺 → 9/4 信号不成笔 → **max signal_date=20260903** | 产物生成 |
| 20:12:59 | overview.json generated_at | 正常 |
| 20:41 | update_all 结束(171min),发「耗时超1h」严重告警 | 超时告警 |
| 20:50 | backfill 第一次 deploy:**check_task_state 僵尸 cron FAIL → deploy rc=1** | 阻断 |
| 21:30 | backfill 第二次:accum-nav 缺失 296 行补 1 行(562510 补上,159023/159173 仍缺) | 部分补齐 |
| 21:46 | backfill 第二次 deploy:3 个僵尸 cron FAIL → **deploy rc=1,新 trades 未上线** | 阻断 |
| 上线态 | 线上 signal_kelly_trades.json = 20:12 版(quadrants 最高卖出日 20260904 仅 E/H/J 模式,A 模式 20260903) | 停更可见 |

## 三、前端展示机制解释(为什么看到 9/3 而非 9/4)

1. **lab.js 凯利页交易记录**(static-site/lab.js):
   - 数据源:`_labKellyTradesBaseName()`(L8417)→ `signal_kelly_trades.json`。
   - 默认过滤:`_kellyDefaultFilters()`(L7455,AI 宏默认组合 positionCap K=1)。
   - 模式默认 A:20:12 数据下 **A 模式 max sell_date=20260903**(A/B/C/D/F 均 20260903;E/H/J 才有 20260904)。
   - 用户看到的"只到 9/3" = A 模式真实数据上限,前端忠实展示。
2. **首页模拟回测弹窗**(static-site/app.js):
   - 数据源:`_simTradesBaseName()`(L3541)→ `signal_kelly_trades.json`,分片加载 L4156-4168。
   - 默认模式:`sel.value || "A"`(L4118),同样 A 模式 max sell=9/3。
3. 结论:**前端无 bug**,是 20:12 产物本身缺 9/4 信号(A 模式)。9/4 卖出记录 36 条只存在于 E/H/J 模式(by_mode: J=16/H=16/E=4),用户默认模式 A 看不到。

## 四、8/31 停更是否同源(结论:不同源,但同背景)

- 8/31:update_all 耗时 **226 分钟**(极值,update_all_launchd.err 08-31 21:36 严重告警),trades 19:49 生成、deploy 21:23 **成功**(退出码 0),线上有更新。
- 9/7:update_all 171 分钟超时(连续第 10 天超 1h),但停更的直接原因是「数据未就绪(accum_nav 缺口)+ 二次 backfill deploy 被 check_task_state 阻断」双因素。
- **共同背景**:8/26~9/7 update_all 每天"耗时超1h"严重告警(update_all_launchd.err),指数/ETF 采集系统性变慢,需根治;但 8/31 无数据缺口 + 无 deploy 阻断,与本次机制不同。

## 五、数据供给四件套现状评估

| 环节 | 现状 | 缺口 |
|---|---|---|
| 生成 | etf backfill 20:07+21:30 launchd 正常跑(OHLC 163s),信号检测正常(9/7 出 3 条买入信号) | accum_nav 补齐能力不足:9/7 深市部分 ETF 数据源返空,296 只缺只补 1 只 |
| 定时挂载 | com.trade.etf-national-team 20:07+21:30;com.trade.update-all 17:50 | 无 |
| 机检 | check_signal_accum_nav_lag(最 新日期滞后)9/7 PASS | **不验覆盖率/单只缺口**——总量新鲜但个体缺口漏检 |
| 告警 | update_all 每天超时告警(有),backfill deploy 失败只 exit=1 记 schedule_stats,**无独立告警** | 交易记录停更无专项告警;backfill deploy 阻断无通知 |

## 六、修复建议(按优先级)

1. **P0 立即**:删除僵尸巡检 cron(§23.12-1 拍板三连②),让 21:30 版本 deploy 通过 → 线上 trades 补上 562510 的 9/4 交易(至少 sw_801210 入账)。
2. **P1 数据补齐**:排查 159023/159173 等深市 ETF 9/7 accum_nav 缺失(数据源返空)→ 用 baostock/腾讯 alt 源补拉 9/7 累计净值 → 重跑 backtest → deploy。补不上需如实标注该 ETF 9/4 信号不可成笔(数据源缺口)。
3. **P1 机检增强**:check_signal_accum_nav_lag 增加"覆盖率"维度(最新交易日的 accum_nav 非空率阈值,如 <90% 即 FAIL),挂 deploy 链阻断;或对 signal_kelly_trades 加"最近 N 交易日买入信号入账率"校验(9/4 信号 3 条入账 0 条应触发告警)。
4. **P2 告警补盲**:backfill deploy 失败(rc≠0)发 notify 告警(当前只有 schedule_stats exit=1,无通知);update_all 超时告警细化到"哪条 pipeline 慢"。
5. **P2 根治 update_all 慢**:连续 10 天超 1h,需定位慢 pipeline(turnover baostock?width mootdx?)单独优化。

## 复现段

- 脚本:`scripts/signal_kelly_backtest.py`(compute 函数,读 `data/sentiment.db` signal_daily + `trade-data/data/etf_national_team.db` etf_daily + `static-site/data/signal_stats.json` + `data/board_etf_map.json` + `data/signal_kelly_etf_freeze.json`)。
- 重跑命令:`cd /Users/linhuichen/code/trade/scripts && /Users/linhuichen/code/trade-data/.venv/bin/python -c "import signal_kelly_backtest as sk; out,tr=sk.compute()"`(全量约 3-5 分钟)。
- 数据截止:2026-09-07(生产 DB etf_national_team.db 21:35 / sentiment.db 21:45)。
- 关键口径:买入=信号日收盘后次日开盘成交(KELLY_BUY_NEXTDAY=1);9/7 信号需 9/8 价格,当前跑 9/7 信号 0 条成笔为预期。
- 修复说明:本报告 R2 结论由「20:12 产物(线上停更版)vs 当前全量回测(562510 已入账)」对比得出;线上页面实测锚点=20:12 版 trades.json max signal_date=20260903、max sell_date(A 模式)=20260903。

## 本次排查已确认事实清单

1. 线上 signal_kelly_trades.json generated_at=2026-09-07 20:12,quadrants max signal_date=20260903、max buy_date=20260903、max sell_date=20260904(仅 E/H/J 模式,A/B/C/D/F=20260903)。
2. 9/7 信号 3 条(csi_399976 buy_aux / sw_801140 buy_special / sw_801210 buy_special)今日 0 条入账=KELLY_BUY_NEXTDAY 需 9/8 开盘价,设计预期。
3. 9/4 信号 4 条(buy_aux hk_cshklc + buy_special csi_931946/sw_801010/sw_801210),hk_cshklc 被 universe_rules 排除类别剪枝(港股),其余 3 条在 20:12 产物全未入账。
4. 当前全量回测(21:35 生产 DB)9/4 成笔仅 562510(sw_801210)1 只 ETF;159023/159173 因 9/7 accum_nav 缺失仍不成笔。
5. 生产 DB etf_daily 9/7=1491 行(open/close 全非空,accum_nav 1197 非空);本机 trade/data/etf_national_team.db 9/7 仅 12 行(双库不同 inode,回测读生产侧)。
6. 9/7 两次 backfill(20:07/21:30)deploy 均被 check_task_state.py zombie_crons FAIL 阻断(第一次 1 个僵尸 cron,第二次 3 个),deploy rc=1,新 trades 未上线。
7. check_signal_accum_nav_lag(最 新日期)9/7 PASS("滞后 0 交易日"),未覆盖单只 ETF 缺口。
8. index_daily 9/7 缺 42 条 = 27 csi + 8 gz + 4 us + dax/ftse100/div_lowvol(海外指数 9/7 数据未发布,部分合理;csi/gz A 股指数缺口待查采集日志,非本次停更主因)。
9. 9/5/9/6 为周末(9/4 周五),backfill IS_TRADING=0 跳过,正常。
10. update_all 8/26~9/7 连续 10 天"耗时超1h"严重告警(8/31 达 226min),指数/ETF 采集系统性变慢。
