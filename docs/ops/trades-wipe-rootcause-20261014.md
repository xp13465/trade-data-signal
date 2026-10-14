# 交易记录断档·根治型只读调研(谁在重写/删除 signal_daily 的历史行)
- 执行:researcher 子 agent;全程只读(未改云上任何文件/DB,未 source/exec 任何业务脚本主体);数据事实全部取自云上权威库
- 残留后台任务:**无**(所有远端命令均被 `timeout` 包裹;无 `moved to the background`)
- 时间:2026-10-14 上午;超 30 分钟预算(约 47 分钟,多花在两条上游旁证上)

---
## ① 写入方清单(代码行号级)—— signal_daily 只有"全表 DELETE+INSERT 重算",没有"按日期删行"这种东西
| # | 写方 | 证据 |
|---|---|---|
| 1 | **`app/compute/signals.py:1443-1452` `store()`**:`conn.execute("DELETE FROM signal_daily")` 清空全表 → `INSERT OR REPLACE ... VALUES` 重算出的**全历史**行 → commit。全仓 grep 无任何 `DELETE FROM signal_daily WHERE date...` / `UPDATE signal_daily` / 按日补丁式写入 | 唯一命中:`app/compute/signals.py:1444/1449`(`scripts/check_data_gap_alerts.py:1985` 是测试 harness 的内存库,非生产) |
| 2 | 调用链(4 条,每天互相覆盖重算多次):<br>a) **盘中每轮**:`app/collector/intraday_snapshot.py:2050-2085 _recompute_signals()` → `signals.store(sigs)`(`:2066`);timer `trade-intraday-snapshot`(:25/:35/:55 起,含 20:35 一轮)<br>b) **17:50 update_all**:`scripts/pipeline.sh:62` `from app.compute import runner; runner.run()` → `app/compute/runner.py:23-24 sigs=signals.compute(); n_sig=signals.store(sigs)`<br>c) **补采链直接整套重算**:`scripts/lhb_backfill.sh:105`、`scripts/rzhb_backfill.sh:132`(10-14 08:00 那轮 = sentiment.db mtime 10-14_08:00 的最后一写)<br>d) `app/collector/index_backfill.py`(迟到信号补采后重算,见 `:1140` 注释) | 见左列行号 |
| 3 | 项目**自己知道** signal_daily 只存最终态:`app/db.py:162-170` 注释原文「每轮 append 不覆盖(**signal_daily 是 DELETE+INSERT 覆盖只存最终态,本表保留过程历史**)」——为此专门建了 `signal_intraday_log` 过程历史表,但没给 signal_daily 本身任何历史保护 | `app/db.py:165` |

**判定**:10-12 的 buy 行**不是被"删除"**,而是**被"重算掉"**——上游输入一改,全表重建就吐不出它了。所以"谁在重写"要往上游找(见 ③)。

## ② 直接证据:10-12 的 buy 行曾经存在,后来消失(不用推理)
| 证据 | 内容 |
|---|---|
| E1 过程日志(最硬) | `signal_intraday_log`(写方 `app/collector/intraday_snapshot.py:2026-2046 _log_signal_intraday`,每轮把 `signals.compute()` 当日输出 append)**10-12 各轮实测**:09:26 buy×2+buy_aux×13 → 15:36 buy×2(hk_cesg10、sz_div)+ buy_aux×8(csi_000330/000673/000680/000698/399967/399970/970070、sse_000685)→ **18:32 buy×0 + buy_aux×2(csi_000673、gz_399368)** → 20:36 同 18:32 → **现值(10-14 08:00 最后一次重算)buy_aux×0**。逐条 reason 原文如 15:36 `csi_000673 buy_aux 布林下轨回归(下轨3103,收盘价3126), RSI=28` |
| E2 冻结表(固化资产) | `data/signal_kelly_etf_freeze.json` 10-12 有 **7 条**:6 条 `frozen_at=2026-10-12 16:38`(csi_000330/000673/399967/970070→ETF、sse_000685、sz_div(buy))+ 1 条 us_ixic buy_special `frozen_at=2026-10-13 05:03`。**现值 signal_daily 10-12 行里,这 6 条全无**(现 22 行:band_hold×2、buy_special×1(us_ixic)、sell×3、sell_stop_loss×16) |
| E3 系统自己的告警文案 | `update_all_20261012_1750.log:1392/1394`:「🔴 创业板人工智能指数 辅买 … **信号消失，建议人工复核行情**」「🔴 上证科创板芯片指数 辅买 … 信号消失」;`:1373` 18:30:58 收盘邮件「20261012 辅买×2 创业板50、国证军工」 |
| 结论 | **10-12 的 buy/buy_aux 行确实曾经存在(15:36 有 10 条,18:32 前还有),在 10-12 17:50 update_all 一轮里先死 8 条,余 2 条(创业板50、国证军工)再在 10-13~10-14 的重算里死掉。** |

## ③ 范围穷举 + 上游真凶(为什么重算会把历史行算没)
### 3.1 上游被"整段重写"的证据
| 证据 | 内容 |
|---|---|
| U1 同一行数字跨轮变化 | 10-12 同一天同一 id 的 reason:sw_801230 `收盘价4012`(18:32)→`3995`(现);sw_801970 `1831`→`1825`;csi_000673 布林下轨 `3103`(15:36)→`3108`(18:32)而 close 仍 3126;**现值 csi_000673 10-12 close=3057.907**(pct=-2.87% 与 3057.907/10-09的3148.252 自洽、low=3057.216 自洽;而 3126≈当日 open 3125.973 = 盘中占位值) |
| U2 写方 + 全史覆盖 | `app/collector/runner.py:281`「指数(**拉近 400 天,等于自动回填**)」+ `_collect_one_index`(`runner.py:224-231`)→ `upsert_index_rows`(`runner.py:139-148`,`INSERT INTO index_daily ... ON CONFLICT DO UPDATE SET open/high/low/close/pct_change/amount=excluded.*` **全字段替换、零保护**);实测日志 `update_all_20261013_1750.log:913-914` `[  ok] csi_000330 5029 rows / csi_000673 2993 rows`,与库内总行数一致(csi_000673=2994 行 20140618 起、csi_000330=5030 行 20060124 起)⇒ **名义 400 天,实际每次整段全历史重采+覆盖** |
| U3 计算法占位行也写历史 | `app/collector/intraday_snapshot.py:1188/1229-1300`「close = prev_close × (1+pct/100)」→ `UPDATE index_daily SET close=? WHERE index_id=? AND date=?`;**10-13 的 csi_000673 现值行 open=high=low=close=2987.8、pct_change=-2.29(圆整数)= 计算法痕迹** ⇒ 今天(10-13)那一行也还是占位值,晚上重算同样会变 |
| 定性 vs #251 | **是同族**:「每日重写缺保护 / UPSERT 全量替换把历史行清掉」的镜像(东财 showday 翻滚 + UPSERT/COALESCE 病)。本例**未见到** #251 的"日期错位/抢跑窗"证据(10-12 行的 date 没错位),是两个新落点:**① index_daily 全史 UPSERT 覆盖(上游)② signal_daily 全表 DELETE+INSERT 无历史保护(下游)** |

### 3.2 日期 × 条数全列(机检:每日最后一轮 signal_intraday_log 快照 vs 现值 signal_daily,09-01~10-13 共 32 个交易日)
- 消失的 buy/buy_aux 共 **16 条**:09-10 cac40(buy);09-15 gz_399395/gz_399440/sw_801050;09-16 sw_801120/sw_801880;09-17 sz_div;09-18 hk_cesg10(buy)+sz_div(buy);09-23 g.a_qvix_300(buy);09-30 csi_000330(buy)+csi_000673;**10-08 csi_000330+csi_000673**;10-12 csi_000673+gz_399368(以 15:36 快照比 = **10 条**:上述 2 + csi_000680/csi_000698/csi_399970/hk_cesg10/sz_div/csi_000330/csi_399967/csi_000970070/sse_000685 中相应项)。
- 其它日期 sell 系也有消失(09-15 一次 5 条 sell_stop_loss)⇒ 是同机制的全类型改写,只是 buy 的后果最重(丢成交)。
- **同族其它表/产物**:`index_daily`(上游本体,每天全史重写)、`signal_stats.json`(由 signal_daily 派生,`intraday_snapshot.py:2083`)、`signal_kelly_trades.json`(由现值 signal_daily 派生)、全部 index/sentiment/overview 导出(由被改写序列派生)。**唯一有固化(防前视)保护的 = signal_kelly_etf_freeze.json**,所以它成了唯一"事件曾经存在"的铁证。
- 已上线可见影响确认:主档 `max signal_date=20261009`;10-12 事件 16:38 已冻结 ETF、10-13 开盘价也齐,但行在可定价前已消失 ⇒ 既不成账也不报孤儿。

## ④ A / B 双因判定
- **A(主档入账单依赖 signal_daily 现值行,10-12 的 buy 行被事后重写)**:成立,**高置信**。机制已从"重写"升级为坐实:见 ①②③(U1 证明上游值被换、U2 定位写方与全史覆盖、E1 证明行曾经存在)。
- **B(盘中档→主档未收敛)**:不足以独立坐实,**中置信**。`signal_kelly_trades_intraday.json`(rerun_date=20261012、含 csi_000673 buy_aux)与主档无对应行,但**无法区分**"从未收敛"与"收敛后又被同一重算抹掉";且它不是主因——主因是 A(10-12 事件在可定价时点已不在现值表)。
- 附带修正前人一处措辞:不是"谁 DELETE 了历史行",而是"signal_daily 无历史行概念,一切重算;上游 10-12 行被改 ⇒ 重算吐不出该行"。

## ⑤ 修复方向(只建议,未实施)
### 止血(把 10-12 / 10-13 的入账补回来)
1. **正确入口 = 回测侧入账源,不是往 signal_daily 插行**:往 signal_daily 插历史行会被下一轮全表 DELETE+INSERT 再抹掉(重算源不含它)— 踩坑必现。
2. 做法:用冻结表已有事件(`signal_kelly_etf_freeze.json`:10-12 六条+frozen_at 齐全、10-13 一批)+ 10-13 open(已齐)+ 10-14 open(10-13 事件)**重跑一次 backtest 的"孤儿事件补账"**;或按冻结事件手工补一条 trade 记录并标注来源=冻结表(可追溯)。
3. 风险:补账必须沿用防前视口径(成交日冻结 ETF + 成交日价,§5.1⑥);不得用"现在的 best ETF"回填。另:补账后要与前端/缓存同步(§22),否则弹窗/lab 卡又出现三处不一致。
4. 另可顺手拿到:10-12 真实成交若有(如 ETF 实价),核对补账价是否与 10-13 open 一致,避免又产生"价格源残差"争议。
### 治本(写入方加保护,按优先级)
- T1 **signal_daily 重算加"历史行 diff 审计"**:`store()` 重算后对 `date < today` 的行做集合/字段 diff,变化即落审计表 + 告警(而非静默覆盖)。最小侵入、当天可上,且能立刻回答"今天哪些历史信号变了"。
- T2 **入账源改"冻结表优先 + signal_daily 兜底"(即 B 方案)**:已冻结事件即使现值表无行也入账(或至少出"孤儿事件"告警)。这直接消除"事件曾存在但没成交"的账目断档。
- T3 **上游 index_daily 的"全史 UPSERT"加保护**:`runner.py:139-148/281` 对 `date < today` 的行,值发生变化时记修正审计(或只在"缺失/为空"时补,别整行替换)。**风险:上游源值确实有误时必须允许改正**,所以做"审计+告警"而不是"禁止改写"。
- T4 **口径层记录**:T2/T3 动了入账/数据口径 ⇒ 按 §5.4⑥ 发中间版本 + 前端默认/公示/键集登记点同步。
- T5 相关固化:采集侧"计算法占位行"(U3)应在写入时打标记(如 source/占位 flag),让下游能区分"真收盘价"与"占位价",从源头减少"先有信号、后无信号"的假事件。

## ⑥ 13 条 SEVERE 老缺口是否同根:部分同根,需逐条分拣
- **09-30 csi_000903 缺次日价**(etf_daily 无 20261008 记录):`csi_000903` 的 09-30 行**现在还在** signal_daily(实测 `20260930|csi_000903|buy_aux`),故**不是**"行消失"根因;更像 etf_daily 里 164508 缺 10-08 行(独立根,中低置信,需另查 etf_daily 10-08 覆盖)。但**同日**的 csi_000330(buy)、csi_000673(buy_aux)确实属本根因(已消失)。
- **10-02 cac40→513080 / dax→159561「次日价已齐仍缺」**:实测 `signal_daily(20261002)` 现含 `cac40 buy` + `dax buy_aux`,行**还在** ⇒ **不同根**(检查器文案自身给的候选:评级缺失/冻结缺失)。
- 结论:**13 条 SEVERE 里至少混着 2 类根因**(行消失 vs 次日价/评级/冻结),不能一句"同根"了结;建议逐条按"信号行现在在不在"分拣(本次已给出 09-30/10-02 两条的判法)。

## 已验证方法/数据源清单(便于主控判充分性)
- 云上权威库:`/home/ubuntu/code/trade-data/data/sentiment.db`(signal_daily / signal_intraday_log / index_daily)、`data/signal_kelly_etf_freeze.json`、`data/logs/`(update_all/backfill 日志)、`systemctl list-timers`/`systemctl cat`。
- 机检法:①逐日"最后一轮 intraday 快照 vs 现值"集合 diff(32 日)②同 date 同 id 的 reason 字符串跨轮对比 ③fetch 行数 vs 库内总行数对齐(判全史覆盖)④pct_change/OHLC/low 自洽性(判哪个值是真收盘)⑤冻结表 frozen_at 时间戳(判"曾经存在")。
- **未做/未坐实(诚实标注)**:①"谁把 csi_000673 10-12 close 从 3126 改成 3057.907"未逐次运行坐实(高置信=10-13 17:50 update_all 指数全史段,该 log 有 2993 行 fetch 但无逐值日志;10-14 02:00 backfill 亦可能)②3126 vs 3057.907 谁是真收盘:内部自洽支持 3057.907,但未做异源(跟踪 ETF 实价)交叉验证(etf_daily 无 pct_change 列,未取数)③B 因未独立坐实(见④)。
