# A 模式信号触发模拟交易账本 — 设计 + 运行手册(第一阶段,2026-11-20)

> 范围:**只做账本 + 触发器 + 回填复盘**,不接交易软件、不发任何通知(只写日志/JSONL)。
> 设计权威:`/tmp/trigger-sim-research-20261120.md`(调研报告,DDL 逐字照建)。
> 代码:`scripts/sim_trade_db.py`(建库/校验)、`scripts/sim_trade_trigger.py`(四阶段触发器)、
> `scripts/sim_trade_backfill.py`(历史回填)、`scripts/sim_trade_review.py`(复盘双口径)、
> `scripts/check_sim_trade_append_only.py`(append-only 机检闸门)。

## 1. 这套东西干什么

用户原话:「对 a 的交易方法做一个独立的信号采集模拟交易表。假定每天对应时间的操作都可以做到,
需要你做一个触发器。触发后往交易表里插入记录(未来就是直接触发后操作交易软件),
我需要你做出触发行为→记录交易记录→模拟交易→后续复盘的仿真测试」。

说人话:

1. 每天收盘后,把「明天要买哪只 ETF、买多少钱」定格进账本(`sim_trade_signal`)。
2. 第二天开盘/尾盘,按当时真实价格记一笔「成交」(`sim_trade_fill`),取不到价格就记失败,绝不编价。
3. D+10 收盘做结算,把卖出成交记进账本。
4. 随时复盘:同一笔交易同时给出「真实可执行」和「回测等价」两套盈亏。

账本走 **append-only(只插不改)**:写错了不能改也不能删,只能追加一条新记录并标记 `supersedes_*`
指向旧记录。这样历史永远不会被悄悄改写。

## 2. 表结构(4 表 + 8 触发器 + 3 视图)

| 表 | 一行是什么 | 关键字段 |
|---|---|---|
| `sim_trade_signal` | 一条买入信号(定格) | signal_id / signal_date / exec_date / sell_due_date / etf_code / s06_effective_mode / plan_hash |
| `sim_trade_order` | 一条下单指令 | order_id / signal_id / side / action / qty_plan / intended_at / trigger_source |
| `sim_trade_fill` | 一条成交 | fill_id / order_id / side / fill_date / price_kind / price_raw / price_equiv / shares_calc / shares_real / net / fee_config / status |
| `sim_trade_event` | 事件流水(失败/自检/运行统计) | event_id / event_type / payload |

- **8 条触发器**:每张表的 `BEFORE UPDATE` 和 `BEFORE DELETE` 各一条,命中就 `RAISE(ABORT,'append-only: ...')`。
- **3 个视图**:`v_sim_fill_effective`(未被 supersede 的成交)、`v_sim_signal_effective`(未被 supersede 的信号)、
  `v_sim_trade_position`(一笔持仓一行,含买/卖有效成交、`profit_calc` / `profit_real` / `profit_mark` / `closed`)。
- **ID 都是确定性 sha1**:同一天同一笔重跑永远算出同一个 ID,配 `INSERT OR IGNORE` 天然幂等。

### ⚠️ 已知限制:必须用 `db.connect()` / `db.init_db()` 打开账本

SQLite 默认 `PRAGMA recursive_triggers=OFF`,`INSERT OR REPLACE` 内部的删除动作**不会触发** `BEFORE DELETE`。
本库在 `scripts/sim_trade_db.py:connect()` 里强制 `PRAGMA recursive_triggers=ON`,所以正常路径能拦住 REPLACE
(实测 9/9 全 ABORT)。但**裸 `sqlite3.connect(账本路径)` 会绕过这一层**,REPLACE 可以覆盖已有行。
因此:所有读写账本的代码必须走 `db.connect()` / `db.init_db()`,不要自己裸连。
闸门 `check_sim_trade_append_only.py` 的动态用例覆盖的是 `db.init_db()` 连接路径。

## 3. 双口径(两套账,不混算)

| 口径 | 买入价 | 份额 | 费率 | 存哪 |
|---|---|---|---|---|
| `calc`(回测等价) | 信号日 `accum_nav × 次日open/信号日close`,含千 1 滑点 | 分数份额(`shares_calc`) | `backtest` 档:万 3 / 最低 5 元 | 表内 `net/gross/commission/...` 列 + `fee_config.calc` |
| `real`(真实可执行) | 真实开盘价(或 14:55 实时价) | 100 股整手(`shares_real`) | `etf_main` 档:万 0.5 / 最低 0.1 元 | `fee_config.real` 段(完整费率明细) |

- **卖出双记**:结算写 `price_kind='close'`(D+10 收盘);14:55 实时单写 `price_kind='intraday'`(provisional,
  当天 22:45 结算时被 confirmed 的 `close` 成交 supersede,不是 UPDATE)。
- **未平仓**:真实账本不计已实现盈亏;`--mark-open` 只给回填的页面卡对账用,写 `price_kind='mark'` 的
  provisional 估值行,视图里 `closed=0`、`profit_calc/profit_real=NULL`,估值利润单独放 `profit_mark`。
- **真实口径卖出份额必须用整手 `shares_real`**:回测产物里的 `trades.shares` 是分数份额(高价 ETF 可差十几倍),
  直接乘真实价会让真实盈亏虚高(云上实测 159943 单笔虚高到 17.4 万 → 修后约 1435 元)。

## 4. 四阶段运行手册

所有命令统一入口(生产把 `--db` 指到 `~/code/trade-data/data/sim_trade.db`,开发用本地路径):

```bash
PY=python3
DB=data/sim_trade.db
DATA=~/code/trade-data/static-site/data
ETF=~/code/trade-data/data/etf_national_team.db
DATES=~/code/trade-data/data/trade_dates.txt
```

### 阶段 1:signal(信号日 22:45) — 定格明天要买什么

```bash
$PY scripts/sim_trade_trigger.py --stage signal --date 20261120 \
  --db $DB --data-dir $DATA --etf-db $ETF --trade-dates $DATES --log-dir data/logs
```

- 读 `nextday_plan.json`;`--date` 必须等于文件里的 `date`,不一致直接拒绝(防错日定格)。
- 写入 `sim_trade_signal`,记录 S06 当日生效模式、状态文件 sha256、fade 键集哈希、计划哈希。
- 重跑幂等:第二次 `inserted=0 ignored=N`,行数不变。
- **fail-closed**:交易日历算不出 D+10 卖出日、或 `exec_date <= signal_date` 都直接报错退出。

### 阶段 2:buy_fill(执行日 09:50) — 记真实买入

```bash
$PY scripts/sim_trade_trigger.py --stage buy_fill --date 20261121 \
  --db $DB --data-dir $DATA --etf-db $ETF --trade-dates $DATES --log-dir data/logs
```

- 实时价复用 `signal_kelly_backtest._fetch_intraday_open_prices`,**expect_date 必须等于执行日**,取不到就不写假价:
  写 `sim_trade_event(type='fill_failed')`,等 22:45 用 etf_daily 复核。
- 首次写 `status='provisional'`(price_kind=`realtime`);22:45 settle 用官方开盘价复核后追加 `confirmed` 行并 supersede 旧的。
- 调试可加 `--prices-json '{"510300":4.02}'` 覆盖价格(不联网)。

### 阶段 3:sell_order(卖出日 14:55) — 记尾盘实时卖出

```bash
$PY scripts/sim_trade_trigger.py --stage sell_order --date 20261204 \
  --db $DB --data-dir $DATA --etf-db $ETF --trade-dates $DATES --log-dir data/logs
```

- 扫 `sell_due_date = 今天` 且未平仓的持仓,按 14:55 最新价写 `price_kind='intraday'` 的 provisional 成交。
- 取不到价记 `price_unavailable` 事件,不写假价。

### 阶段 4:settle(D+10 22:45) — 复核买入 + 收盘结算

```bash
$PY scripts/sim_trade_trigger.py --stage settle --date 20261204 \
  --db $DB --data-dir $DATA --etf-db $ETF --trade-dates $DATES --log-dir data/logs
```

- ①当天有买入的执行日:用 etf_daily 官方开盘价追加 confirmed 买入成交;
- ②当天是 D+10:用收盘价追加 confirmed 卖出成交,`net = 10000 + 该口径利润`。
- 幂等:同一天重跑 `buy_confirmed=0 sell_settled=0`。

### 生产开关

默认**不写库**:必须 `SIM_TRADE_ENABLED=1`(timer 里设置)或手动加 `--force`。这是防误触发的保险。

### 日志

每天一个 `data/logs/sim_trade_run_YYYYMMDD.jsonl`,逐阶段追加运行统计。**本阶段不接 notify/邮件/飞书**。

## 5. 历史回填与复盘

```bash
# 回测口径(K=1, PRD 545 笔那组):信号日 <= 20260910
$PY scripts/sim_trade_backfill.py --db /tmp/sim_bt.db --data-dir $DATA --etf-db $ETF \
  --trade-dates $DATES --fee backtest --asof 20260910

# 页面卡口径(K=1, etf_main 费率, 含未平仓估值标记)
$PY scripts/sim_trade_backfill.py --db /tmp/sim_page.db --data-dir $DATA --etf-db $ETF \
  --trade-dates $DATES --fee etf_main --mark-open

# 复盘(两种口径; 默认只算已平仓, --include-marks 与页面卡同 n)
$PY scripts/sim_trade_review.py --db /tmp/sim_page.db --caliber calc --include-marks
$PY scripts/sim_trade_review.py --db /tmp/sim_page.db --caliber real --include-marks
```

- **一份账本只能装一种回填口径**(`signal_id` 不含费率档,混跑会被幂等吞掉一半行):脚本检测到其他口径的
  回填行会直接拒绝,要求换独立 `--db`。
- 2026-11-20 云上实测对账(云上数据 11-20 23:11 那批):
  - 页面卡口径:`n=586 / ret 144.7282% / dd 20.9296%`,与云上 `latest_posrating.json` K1 卡
    (144.7282 / 20.9296 / 586)**逐位一致**;
  - 回测口径(信号日 <= 20260910):`n=549 / +156,592.9988 / rmh 156.593%`;
    与 PRD 2026-09-10 的 545 笔 / +158,397 / 158.40% 差 4 笔(产物 11-20 已重算,属历史数据漂移,不是脚本错)。
  - 锚点旧值 585 / 146.43% / 19.23% 是 11-20 07:09 的产物,当天 23:11 更新后页面本身已变成 586 / 144.73% / 20.93%。

## 6. systemd 单元样本(只放文档,本阶段不安装)

放 `docs/ops/systemd/` 下的 5 个文件:`trade-sim-trade@.service` + 4 个 `.timer`。
安装前必须先核当天定时任务清单(§14),并确认账本路径、`SIM_TRADE_ENABLED=1`、日志目录权限。
安装示例(明确要用户拍板后才做):

```bash
sudo cp docs/ops/systemd/trade-sim-trade*.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now trade-sim-trade-signal.timer trade-sim-trade-buy-fill.timer \
  trade-sim-trade-sell-order.timer trade-sim-trade-settle.timer
systemctl list-timers 'trade-sim-trade-*'
```

时点与现有任务的关系(2026-11-20 现状):signal 22:45 与 settle 22:50 在盘后任务(15:35/16:00/17:50/20:35/22:00)
之后、23:00 安全窗口之前;buy_fill 09:50、sell_order 14:55 在盘中,只写独立账本库,不碰采集/评分库。

## 7. 机检闸门

```bash
$PY scripts/check_sim_trade_append_only.py --scripts-dir .
```

三层检查:①静态扫 `scripts/**/*.py` 里的 `UPDATE sim_trade_*` / `DELETE FROM sim_trade_*` /
`INSERT OR REPLACE ... sim_trade_*`(跳过触发器 DDL 和文档字符串);②结构检查(8 触发器 + `PRAGMA integrity_check`);
③临时库动态实测(4 表 × UPDATE/DELETE + REPLACE 必须全部 ABORT,行数不变)。任一不过 `pass=false` 非零退出。

## 8. 回滚

本阶段没有安装任何定时任务、没有改生产数据、没有接通知,回滚 = 不合并分支即可。
账本库是独立文件(`data/sim_trade.db`),删掉重建不影响任何既有数据(删除前按 §25 先备份)。
