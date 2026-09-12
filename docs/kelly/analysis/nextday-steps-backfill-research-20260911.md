# 实操步骤表回填「历史持仓」数据链设计调研(#106, 2026-09-11)

> 用户拍板方案=回填历史持仓(非仅未来计划)。本报告回答数据源/字段/去重/口径/前端/拆分/风险 7 问, 全部结论带证据。
> 背景: 实操步骤表(auto_trade_steps.json, PRD §6)当前只装「次日买入计划」(生成器只对当日信号生成 1 个日期的 seq 链),
> 历史已买入不在表里 → 前端 _atFindSellDue(today>=sell_date)无数据可判, 用户 9/11 问「10 个工作日前的买入怎么没卖出提醒」。

## ① 数据源结论: 生成器历史重演(选项2)为主, 回测 trades(选项1)出局

**选型结论: 用生成器自身的历史重演(--date 逐日回放), 不用 signal_kelly_trades.json。**

- **选项1(回测 trades) 决定性证伪**: `signal_kelly_trades.json` 生成于 **2026-08-09 19:21**(旧产物),
  `sig_main/A` 最新 signal_date = **20260731**, 回填窗口(20260902~20260910)内笔数 = **0**(复现脚本 ⑥)。
  想做 9 月的历史持仓, trades 里根本没有 9 月的记录; 需等重跑回测才可能有, 且重跑后的「实操口径」仍需重做 top1 选取。
  证据: `data/signal_kelly_trades.json` generated_at=2026-08-09; quadrants.sig_main.A max(signal_date)=20260731。
- **选项2 可行性已实测**: 生成器自带 `--date` 参数, 对历史 T 重跑即得「如果当天跑了会选什么」——与未来计划**同一条链**(signal_daily 历史 + 冻结表历史 + S06 历史 + K=1 排序 + 双校验, 代码路径零分叉)。
  实测 10 个交易日(20260826~20260910)全部跑通, 5 天空计划(8/26,27,28,31,9/1), 5 天有买入(9/2,3,4,7,8,9 信号日)。
- **与未来计划口径天然统一(§22)**: 回填行与未来计划用同一 `_build_steps_for_plan` 生成, 同一字段模板, 前端零适配。
- 选项3(现状表无历史根) 自动排除。

**回填窗口重演结果(信号日 → top1 → 买入日 → 卖出日)**: 见复现脚本 ④ 输出:
| 信号日 | index|signal | top1 ETF | 买入日 | 卖出日(D+10) | 到期(9/11)? |
|---|---|---|---|---|---|
| 20260902 | us_dji buy_aux | 513400 | 20260903 | 20260916 | 否 |
| 20260903 | csi_931151 buy_aux | 560230 | 20260904 | 20260917 | 否 |
| 20260904 | sw_801010 buy_special | 159173 | 20260907 | 20260918 | 否 |
| 20260907 | csi_930997 buy_aux | 516390 | 20260908 | 20260921 | 否 |
| 20260908 | csi_399986 buy_special | 512820 | 20260909 | 20260922 | 否 |
| 20260909 | sz_div buy_aux | 159905 | 20260910 | 20260923 | 否 |
| 20260910 | cac40 buy | 513080 | 20260911 | 20260924 | 否(今日计划, 已在表) |

## ② 回填字段设计(完整 dict 样例)

回填行 = `_build_steps_for_plan(plan_entry, now, sell_date)` 输出, 与未来计划**同一模板**, 只是计划条目来自历史 T 重演而非当日生成。完整样例(seq1, seq5 省略中间):

```json
{
  "schema_version": "v1",
  "steps": [
    {
      "date": "20260903",          // = buy_date(执行日), 与现有表 date 语义一致
      "seq": 1, "time_slot": "09:15", "action": "buy",
      "etf_code": "513400", "etf_name": "美国50ETF",
      "order_price": 1.764,        // prev_close = 信号日 etf_daily 收盘(挂单价上限, 双校验后)
      "amount": 10000, "shares_planned": 5000,
      "status": "pending", "status_text": "待执行",
      "signal": "buy_aux", "track_score": 66.8,
      "trigger_note": "...", "expected_range": "...", "decision": "...",
      "updated_at": "2026-09-11 20:55:00"
    },
    { "seq": 2, "time_slot": "09:25", "action": "buy", "...": "同模板" },
    { "seq": 3, "time_slot": "14:55", "action": "buy", "...": "同模板" },
    {
      "seq": 5, "time_slot": "D+10 14:55", "action": "sell",
      "date": "20260903", "sell_date": "20260916",   // 结构化键, 前端 _atFindSellDue 按 today>=sell_date 判到期
      "order_price": null, "amount": 10000, "shares_planned": 5000,
      "status": "pending", "status_text": "待执行",
      "trigger_note": "A 模式固定 10 个交易日到期: 卖出日 20260916, 收盘市价卖出 5000 份; Phase1 提醒手动 / Phase2 自动",
      "updated_at": "2026-09-11 20:55:00"
    }
  ]
}
```

- **金额/份额口径(D 问)**: amount=10000(BUY_AMOUNT 常量), shares=_shares_planned(10000÷order_price 向下取整到 100 份整数倍),
  与前端 `_atSharesPlanned` 同构(lab.js L13998)。**不用**回测 trades 的 shares(复权份数, 如 4448.416259, 非交易手数)。
- **不含盈亏字段**: 实操表是计划+步骤状态展示(PRD §6.2), 不展示买卖盈亏; sell_price/profit 无必要。
- **history 标记建议**: 回填组加 `"backfilled": true`(或 trigger_note 前缀「历史回填」), 便于前端/排查区分, 纯展示字段不影响逻辑。

## ③ 去重/幂等/窗口方案(F 问)

- **幂等键**: 现有逻辑已按 `date(=buy_date) + seq=1` 存在即跳过(L582-583); 回填并入同一判定, 天然幂等。
  实测现有表只有 20260911 组, 回填 6 组(20260903~20260910)**零冲突**, 9/10(from 已有)自动幂等跳过。
- **回填窗口上限 = 最近 10 交易日**(常量 BACKFILL_WINDOW=10): 窗口起点随每日前移, 已过期组随窗口滑出(不删只不再补);
  空计划日不生成组 → 本次实际补充 6 组。未来每天最多新增 1 组(有买入日), 年增长 ≈ 244 组, 表体积可控(每组 4 行 JSON ~2KB)。
- **增量**: 每次生成器运行先跑回填(补窗口内缺失组), 再追加当日计划, 已存在组跳过。
- **到期组处理(B 问)**: 回填只补「未到期」组(sell_date >= today 或空)。窗口内全部未到期(最早 9/16)。
  - 已到期(sell_date < today)的旧持仓: **不生成卖出提醒行**(防过期骚扰); 若表里已有(未来某日跨期), 由前端
    `_atFindSellDue` + 用户「✓ 我已操作」标记机制自然收敛(标记后不再提醒, localStorage 持久化)——「已卖出不再提醒」无需新逻辑。
  - 跨日边界: 昨天持有中今天到期 → 前端 today>=sell_date 字符串比较自动切换, 无需后端特判。

## ④ 卖出口径统一说明(C 问)

**三源完全一致, 无矛盾, 无需改文档**:
| 源 | 口径 | 证据 |
|---|---|---|
| 回测 _backtest_one | sell_date = 信号日后第 hold_days(10)交易日(`dates[idx:idx+10]` 取末位, L715/774) | 8 样本与生成器公式逐位一致(复现脚本 ③) |
| 生成器新行 | `_nth_trading_day_after(signal_date, 10)` = 信号日后第 10 交易日(L588) | 同上 |
| 生成器迁移段(老行) | 无 signal_date 用 `_nth_trading_day_after(buy_date, 9)`(L289) | buy_date=信号日+1交易日 ⇒ 等价信号日后第10交易日 |
| PRD 示例 | 9/7 买入 → 「预计 D+10(2026-09-21)」(L427) | 9/21 = 信号日(9/4)后第 10 交易日 ✓ |
| trades 记录 | rating_high/A 20210607 → sell_date 20210622 | = 信号日后第 10 交易日 ✓(F 模式 20210629 = 第 15 交易日, per-mode 不同) |

- **任务书提到「PRD 示例 9/21 vs 9/24 差 1 交易日」不成立**: 全仓 grep `docs/auto-trade/*.md` 只有 9/21 一处(PRD L427);
  **9/24 不存在于任何文档**。9/24 = 20260910 信号那笔的 D+10(生成器推算), 与 PRD 的 9/21 是两笔不同交易的卖出日, 非同一笔差日。
- **文档微差(§23.13 上报, 不自行改)**: PRD seq5 示例行(L431-435)缺结构化 `sell_date` 字段(仅 time_slot "D+10 14:55");
  实现已加 sell_date(前端判定依赖)。建议 PRD 示例补该字段, 需用户确认。

## ⑤ 前端是否要改(E 问)

**主逻辑不需要改; 可选一个小增强。**

- 现状已支持: ① `_atFindSellDue`(L14073-14095)按 today>=sell_date 找最早到期未标记卖出行 → bar「现在该干嘛」提示 + 主表 nowActDate 高亮;
  ② `_atDaySummary`(L14230)纯 sell 组摘要防整表变卖出(reviewer P1 已修)已兼容「只有 seq5 的行」组; ③ 主表 `_atBuildDays`(L14329)**无近 N 天截断**(全部天渲染, date DESC), 回填 6 行=表多 6 行, 不会「表头被占」; ④ `_atCollectCodes`(L14188)盘中现价批量已限 20 只。
- **回填后用户预期自动满足**: 9/16 起(第一笔到期)打开实操步骤页, bar 顶部显示「D+10 14:55 卖出: 513400 美国50ETF…」, 主表该行高亮。
- **可选增强(待用户拍板)**: 主表排序 date DESC, 到期笔(如 9/16)排在当日计划(9/11)下方, 用户需滚动才见。若要「到期笔置顶」:
  `_atBuildDays` 返回的 days 排序前, 把含「到期未标记 sell 步骤」的组插到最前(或渲染时该行加固定置顶 class)。纯前端小改, 不动数据。
  建议: bar 已在页面顶部 = 最优位置已满足, 主表保持 date DESC 一致性更好; 是否加置顶由用户定。

## ⑥ 实施拆分建议

**生成器改动(implementer, scripts/nextday_plan_generator.py)**:
1. 新增 `BACKFILL_WINDOW_DAYS = 10` 常量 + `--no-backfill` 开关(自测/临时关)。
2. 主链入口新增回填段: 对窗口内每个历史交易日 T(从 trade_dates 取窗口), 复用 `_signal_candidates` → 买信号/宇宙/降亏/K=1 → plan 构建(与当日共用函数, 已有 _signal_candidates 接受任意 T)。
3. 每组生成完整链 `_build_steps_for_plan`(seq1-5), 幂等(date+seq1 存在即跳过), 只补 sell_date >= today 的组。
4. 落盘两树 + R2 upload-data-files(现有段; 注意现逻辑 `if plan` 才传 auto_trade_steps.json——回填后 steps 有变更也应传, 改为按 steps_changed)。
5. 通知: 回填为台账补充不单独发邮件; 当日计划通知照旧。
6. 复验: 重跑后 `_backfill_missing_seqs` 迁移段不受影响(已有完整链组跳过)。

**前端改动(implementer, static-site/lab.js)**:
1. 主逻辑零改动(验证见 ⑤)。
2. 可选: 到期卖出组置顶(待用户拍板); 若加, 改动集中在 `_atBuildDays` 排序 + 可能一行 class。
3. 提示文案: 主表 sub 行「次日买入计划·每日1行」可加「含历史持仓回填」字样(纯文案)。

**文档同步**:
- PRD seq5 示例补 sell_date 字段(§23.13 上报等确认)。
- §21 公示: 回填不改算法, 公示文案不变(展示说明可加一句「历史持仓由生成器按同一选取链回填」, 待用户确认)。
- 本报告四件套: 报告 + 复现脚本 `scripts/nextday_backfill_repro.py` + 本复现段 + 配套 commit。

## ⑦ 防前视评估与风险/不确定登记

**防前视(§5.1⑥)逐项核查**:
- 冻结表(方案2 主路径): key=date|index_id|signal → value 带 `frozen_at`(如 2026-09-03 05:10), **不可变** = 信号日当晚/次晨固化值 → 历史 T 查冻结即当日权威(复现脚本 ⑤)。✓
- S06 快照: daily 全历史(20100201~20260910, 4034 行), 每行 `decision_date` = 前一交易日(抽样 5/5 一致)→ 用 T-1 收盘判定 T 状态。✓
- tier/ma60/cyb: index_daily 全历史 + bisect 取 <=T 最近日, MA 用截至 i 的数据(L578-601)→ 无前视。✓
- signal_daily: 全历史(19910205~20260910, 71175 行), 任意 T 可查。✓
- 生成器历史重演 dry-run 与现网表对账: 20260910 重演输出(cac40|buy|513080 buy_date=20260911 order_price=1.762 amount=10000 shares=5600)与现网 auto_trade_steps.json 20260911 组**逐位一致**(同构对账机检 PASS)。

**已知缺口(诚实标注, 均为低实害)**:
1. **signal_stats 10d score 无历史(唯一实质缺口)**: `_ai_macro_rating_of` 读当日快照的 10d score → 历史 T 的 rating(high/mid/low)取不到当日值。
   影响面: ① K=1 排序第二键(仅 track_score 相同时才比较)——冻结命中路径不走 rating; ② AI宏 filter 的 rating 子条件(janMidRating 1月/r7MayReinforced 5月/greedy15 部分/…), 回填窗口(8月底9月初)主要相关 9 月子条件。
   实害评估: 本次窗口 5 笔 top1 全部由 track_score 领先或唯一候选决出, rating 缺口未改变任何 top1 归属(重演输出可核)。
   根治选项(不推荐现阶段做): 由 signal_daily 历史信号重算 10d score 入历史库(工作量 1 脚本, 口径需与 signal_stats.py 对齐)。
2. **冻结命中后排序 score 取当前 board_etf_map 注入值**(非冻结值): 如 20260908|csi_399986 冻结 score=80.6 vs 当前注入 57.2(差 23.4)。
   只影响同天多候选排名(不变换冻结 code 权威), 9/3 有 11 候选日理论受影响。可增强: 排序 score 改取冻结值(需 implementer 评估 _align_home_top1_to_backtest 注入覆盖点)。
3. **board_etf_map 当前快照 fallback**: 冻结未命中且入样的信号走 fallback(用当前 track_score), 历史 T 当日值可能不同。窗口内未触发 top1 归属差异。
4. **重演≠真实成交**: 9/10 前生成器未上线, 重演输出=「如果当天跑了会选什么」; 干跑阶段本无真实成交, 语义一致, 无需额外说明位。

**风险登记**:
- 回填组 `track_score` 字段(重演值)与冻结值差异, 若用户核对历史可能会问; 建议回填 trigger_note 注明「历史回填」+ signal_date, 便于追溯。
- 前端标记(localStorage)按 date|etf_code|seq|action 键, 回填组键与未来计划同构, 无冲突。

## 复现

- 脚本: `docs/kelly/analysis/scripts/nextday_backfill_repro.py`(死脚本, 与报告同 commit)
- 输入依赖: `data/trade_dates.txt`(REPO=trade-data) / `data/signal_kelly_etf_freeze.json` / `data/sentiment.db signal_daily` / `data/signal_kelly_trades.json`
- 重跑命令: `REPO=/Users/linhuichen/code/trade-data python3 docs/kelly/analysis/scripts/nextday_backfill_repro.py`
- 数据截止: 2026-09-11(交易日历至年底, signal_daily/etf_daily 至 20260910/20260911)
- 关键口径一句话: 卖出日 = 信号日后第 10 交易日(回测 future_dates 切片与生成器 _nth_trading_day_after(sig_date,10) 同款); 回填组与未来计划同模板(_build_steps_for_plan)
- 生成器历史重演验证命令(逐 T): `REPO=/Users/linhuichen/code/trade-data GIT_REPO=/Users/linhuichen/code/trade PY=.../.venv/bin/python scripts/nextday_plan_generator.py --date <YYYYMMDD> --dry-run`
- 修复链说明: 首版脚本 ③ 的 trades 对照取 sig_main quadrants(sig_main=主信号维度)致样本 20210607 不命中, 已修正说明(per-mode 对照须用 rating_high/A); 结论不受影响(三源一致由公式逐位比对支撑, trades 记录仅旁证)
