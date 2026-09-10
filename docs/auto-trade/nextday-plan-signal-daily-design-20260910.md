# nextday_plan 生成器方案A根治: 改走首页 AI建议同一条选取链

> 实施: implementer agent · 日期: 2026-09-10 · 分支: feat/nextday-plan-signal-daily
> 依据: PRD 阶段一 docs/auto-trade/next-day-buy-prd-20260910.md §3/§6 + 用户拍板方案A
> 测试基准: current baseline(memory test-baseline-v112-anchor, v1.1.7); 本任务不涉回测口径, 生成逻辑与首页 overview 逐位同构防前视

## 一、设计缺口(背景)

**原实现**(de0932f8d): 生成器从 `static-site/data/signal_kelly_trades.json` 选 `signal_date == T` 的候选,
再走 `kelly_posrating.make_passes_fade` 降亏链路取 K=1 每日 top1。

**缺口根因**: 主回测 `KELLY_BUY_NEXTDAY=1` 口径下, 买价 = 信号次日开盘价, 即**今日信号永远不在 trades 里**
(信号次日才入账进 trades)。因此每晚 20:55 定时跑 `signal_date == 今天` 的查询必为空 → **定时跑必出空计划误导用户**。
2026-09-10 晚 21:32 launchd 实测: 旧版产出空计划 `{date, empty:true}` 并通知「明日买入计划 20260910(空)」,
而首页 AI建议当日明明有 top1 = 513080 法国ETF华安。

## 二、方案A核心口径(用户拍板)

生成器改走**首页 AI建议 1:1 同一条选取链**, 不再是「从 trades 找当日信号」:

1. **信号源** = `sentiment.db` signal_daily 当日(T)全部信号, 排除 `s.*` 情绪分前缀(与首页查询
   `app/queries.py` L1123-1128 逐字一致), 再只取买信号 `BUY_SIGNALS={buy, buy_aux, buy_special, buy_backup}`
   (buy_special_filtered 归一为 buy_special, 与 `queries._AI_MACRO_BUY_SIGNALS` 同源)。
2. **top1 ETF 判定** = 冻结表 `data/signal_kelly_etf_freeze.json`(key=`date|index_id|signal`)命中
   → 该信号 top1 = 冻结 code(标 `_bk_top` 权威, 与回测标的逐位一致); 未命中 → 前端 `_topEtfByScore`
   同构(纯 max(track_score), 平手回退 similarity)。track_score 取 `board_etf_map` 注入值(与首页 overview 一致)。
3. **降亏过滤** = 首页同款 `queries._ai_macro_hit_filters`(ctx 与 overview 完全同构: rating/market/track_score/
   tier/ma60/cyb) ∩ **S06 动态基座成员集**(`s06.filters_for_date(T)` True 键; 快照缺行 fail-open 放行)。
   a9 基座补 `bullAuxBackupStop` 前端分支(buy_aux/buy_backup × hs300 四档=牛市·主升, 用 kelly_posrating
   `_tds_fade_spec_hit` 同源判定, 不内联复制)。
4. **K=1 保留** = 排序准则(track_score DESC → rating high>mid>low → signal buy_backup>buy>buy_aux>buy_special
   → buy_date ASC), 与首页 AI建议 top1 逐位一致。
5. **buy_date** = T 的下一个交易日(权威交易日历 `data/trade_dates.txt`, §11.4 长假处理; etf_daily 兜底)。
6. **prev_close** = 该 etf T 日收盘(etf_daily, 挂单价上限; 与首页 etf_close 同源同口径)。
7. **amount** = 每日资金池 1 万等分(K=1 即 1 万)。
8. **双校验**(原逻辑保留): ① prev_close>0 非停牌 ② prev_close vs 信号日收盘 ±20% 内(伪跳空剔除同款)。

## 三、数据就绪 gate(§23.15 不上残缺版)

- **原则**: 不产出「误导性空计划」。旧版定时跑**永不空计划才是对的**, 一旦空计划 = 数据没就绪。
- **实现**: `etf_daily` 最新日期 < T → 打印告警退出码 **2**(明确告警"backfill-evening 未完成, 不产出误导性计划"),
  不落盘不 R2 不通知; `NEXTDAY_PLAN_FORCE=1` 可跳过(仅人工核查用, 不推荐)。
- **launchd 时点建议**: 维持 20:55 不变(plist 已定 20:55, 20:35 s06-snapshot 定稿后 / 21:00 backfill 前空档)。
  20:55 跑时 etf_daily 应已由 17:50 update_all 更新到 T; 若机器睡眠或更新延迟 → gate 退出码 2 触发
  nextday_plan.sh 的 severe 告警(既有), 不产出误导计划。

## 四、对账验证(逐位)

| 项 | 首页 overview.json(线上) | 生成器产出(20260910 真跑) | 一致 |
|---|---|---|---|
| 信号 index | cac40 | cac40 | ✓ |
| 信号类型 | buy | buy | ✓ |
| top1 ETF | 513080 法国ETF华安(_bk_top=true) | 513080 法国ETF华安 | ✓ |
| track_score | 53.1 | 53.1 | ✓ |
| prev_close / etf_close | 1.762 | 1.762 | ✓ |
| 入样宇宙 | _bt_in_universe=true | 候选通过 | ✓ |
| 降亏过滤 | ai_macro.hit filters=[r2gLowRatingQ3] 但 S06(new14) 不含该键 → 放行 | 放行 | ✓ |

S06 20260910 基座 = new14, members True 键 14 个, `r2gLowRatingQ3` 不在其中 → cac40 通过降亏, 与首页 AI建议一致。

## 五、落盘链路(§22 三步同步)

1. 本地权威: `data/nextday_plan.json`
2. 两树用户可见: `REPO(trade-data)/static-site/data/` + `GIT_REPO(trade)/static-site/data/`
   (nextday_plan.json + auto_trade_steps.json)
3. R2: `upload_r2.py upload-data-files` + purge(退出码 0)
4. 通知: notify.py 邮件+飞书 dedup-key=`nextday_plan_{T}` 24h

## 六、本次改动文件

| 文件 | 改动 |
|---|---|
| `scripts/nextday_plan_generator.py` | 方案A重写: 读 signal_daily + 冻结表 + queries 首页同款链路; 数据就绪 gate |
| `scripts/nextday_plan.sh` | wrapper 空参 bug 修复(launchd 无参调用时 bash 3.2 `"${GEN_ARGS[@]:-}"` 展开为空字符串参数 → argparse unrecognized, 20:55 实测 usage error) |

## 复现

- **脚本**: `scripts/nextday_plan_generator.py`(生产入口) + `scripts/nextday_plan.sh`(launchd 包装)
- **输入依赖**: `data/sentiment.db`(signal_daily) + `static-site/data/signal_kelly_etf_freeze.json`(冻结表)
  + `static-site/data/kelly_mode_s06_state.json`(S06 动态基座) + `static-site/data/kelly_loss_features.json`(降亏特征)
  + `data/board_etf_map.json`(ETF 候选映射) + `data/etf_national_team.db`(etf_daily) + `data/trade_dates.txt`(交易日历)
- **重跑命令**:
  ```
  # 干跑(只计算打印, 不落盘不 R2 不通知)
  REPO=/Users/linhuichen/code/trade-data .venv/bin/python scripts/nextday_plan_generator.py --date 20260910 --dry-run
  # 真跑(落盘两树 + R2 + 通知; launchd 20:55 同款)
  REPO=/Users/linhuichen/code/trade-data .venv/bin/python scripts/nextday_plan_generator.py
  # 数据未就绪 gate 测试
  REPO=/Users/linhuichen/code/trade-data .venv/bin/python scripts/nextday_plan_generator.py --date 20990101 --dry-run   # 期望退出码 2
  ```
- **关键口径**: 信号源=signal_daily 当日(排除 s.*) + 冻结表 top1(_bk_top 权威) + queries._ai_macro_hit_filters
  ∩ S06 基座成员集(fail-open); K=1 每日 top1; buy_date=下个交易日; prev_close=etf T 日收盘;
  伪跳空 ±20%; 数据截止 2026-09-10(etf_daily)。
- **验收证据**(2026-09-10 22:23 真跑): 产出 513080 法国ETF华安 prev_close=1.762 amount=10000 signal=buy
  track_score=53.1 signal_date=20260910 buy_date=20260911; 两树 diff 一致; R2 退出码 0(purge 2 keys);
  notify 退出码 0(dedup-key=nextday_plan_20260910); curl ssd.fx8.store/data/nextday_plan.json 读到同内容。
