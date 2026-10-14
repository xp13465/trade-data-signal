# trades 历史行被「重算抹除」根治 A 包(止血 T1/T3/T5 + T2 对比)

- 任务:#252(A 包全量根治)
- 分支:`fix/trades-wipe-rootfix-20261014`(worktree 隔离;只 commit+push 该 feat 分支,不 push main)
- 根因报告(只读调研正文):[`docs/ops/trades-wipe-rootcause-20261014.md`](./trades-wipe-rootcause-20261014.md)
- 时间:2026-10-14 上午
- 口径:**只让历史行改写可见,不禁止重算/改写**(上游源值确实可能有误,必须允许改正)

---

## 0. 一句话结论

根因不是「谁删了行」,而是**两条零保护的整段重写链**:下游 `signal_daily` 每天全表
`DELETE` + 重算全历史(T1),上游 `index_daily` 每次采集整段 `UPSERT` 全字段替换(T3)。
两者都不留痕,所以历史 buy 行**静默消失**(用户侧 = trades 断档)。

A 包做了三件事:①给两条链加**改写审计 + 告警**(T1/T3)②给占位/合成行加 **`source` 标记**(T5)
③把「冻结表孤儿买事件」这条**唯一铁证链**做成可观测 + 可补账候选(T2,默认关闭)。
真跑对比:**新口径(冻结表优先)会让 564/880 格 rmh 变差、最大 -1.86pp** ⇒ **未翻默认,等用户拍板**。

---

## 1. T1 — `signal_daily` 重算抹除历史行 → 可见

| 项 | 内容 |
|---|---|
| 位置 | `app/history_audit.py::snapshot_signal_daily_history / audit_signal_daily_store`;接线在 `app/compute/signals.py::store`(L1444-1469) |
| 判据 | 全表 `DELETE` 前快照 `date < 运行日` 的 `(date,index_id,signal)` 三元组,重算后再快照做 diff |
| **消失** | `before - after` = 历史行被抹除 → **P0,落 `history_overwrite_audit` 表 + 告警**(dedup 1h) |
| **出现** | `after - before` 单条不告警——纯历史回填(迟到信号补采后重算新增历史行)是**合法补账**,否则批量回填会灌爆审计表 + 制造告警风暴;仅当同轮有「消失」(信号类型变更 `buy→buy_aux` 会同时产生一对)时,「出现」作为**类型变更佐证**一并落表/进告警正文 |
| 不阻断 | 快照/diff/落表/告警全部 try/except,失败只打印——审计是增强,绝不阻断 `signals.store` 主流程 |

## 2. T3 — `index_daily` 整段重写历史行 → 可见

| 项 | 内容 |
|---|---|
| 位置 | `app/history_audit.py::audit_index_rows_upsert`(整段)、`::audit_index_row_partial`(单行局部) |
| 判据 | 只审 `date < 运行日`;只为「**库里已存在且值实质变化**」的行记改写(新增行 = 回填不算);浮点容差相对 1e-4 + 绝对 1e-6,源端舍入抖动不算 |
| 落点(§23.2③ 同类写入面**统一入口**,非逐处打补丁) | ① `app/collector/runner.py::upsert_index_rows`(主链整段)② `app/collector/index_backfill.py` 3 处单行兜底(`_audit_hist_row`)③ `app/collector/intraday_snapshot.py` 历史计算法 `UPDATE`(`_audit_hist_partial`) |
| 告警 | 落 `history_overwrite_audit` + 告警(dedup 24h,index_daily 量大噪音面广 → 日报粒度) |

## 3. T5 — 占位/合成行 `source` 标记

- 新列 `index_daily.source`(迁移在 `app/db.py::_migrate`,旧行 NULL = 未标注存量)
- 取值:`collect`(行情源真实价)/ `intraday_snapshot`(盘中快照反哺)/ `calc`(计算法合成,如
  `close = prev_close × (1+pct/100)`)/ `backfill`(兜底补采)
- **覆盖穷举:全仓 `INSERT INTO index_daily` 共 8 处,8/8 带 `source`**(`grep -rn "INTO index_daily" app/ scripts/*.py`),
  另有 1 处历史计算法 `UPDATE` 显式 `SET source='calc'`
- 价值:下游可识别「占位/合成行」,从源头解释「先有信号、后无信号」的假事件
  (实例:10-13 `csi_000673` 现值行 `open=high=low=close=2987.8`、`pct_change=-2.29` 圆整数 = 计算法痕迹)

## 4. T2 — 入账源改「冻结表优先」(**已实现,默认关闭,未拍板**)

### 4.1 实现

| 项 | 内容 |
|---|---|
| 位置 | `scripts/signal_kelly_backtest.py` T2 块(L397-480) |
| 孤儿检出 | `_detect_freeze_orphan_buy_events(freeze, present_di)`:冻结表有买类键,但现值 `signal_daily` 该 `(date,index_id)` **整行缺失**(刻意用整行缺失而非精确三元组,信号类型漂移不是孤儿) |
| 入账开关 | `SIGNAL_KELLY_FREEZE_UNION=1` 时 `_union_freeze_buy_rows` 把冻结表买类事件并入买信号集合;默认 `0` |
| 告警开关 | `SIGNAL_KELLY_FREEZE_ORPHAN_ALERT=1` 才告警(dedup 24h);默认只打印 stderr,避免首跑告警风暴 |
| **铁律** | §23.7 冻结契约 + §5.4⑥:动已上线入账口径 ⇒ **未经用户拍板不得翻默认、不得改基准定义** |

### 4.2 实测数据(云上权威库快照 + 同一引擎)

孤儿规模:冻结表买类键中,**36 条**的 `(date,index_id)` 已从现值 `signal_daily` 整行消失
(另有 5 条为信号类型漂移,`(date,index)` 行仍在,由既有 `_freeze_fallback` 接住)。
按日分布:`20260710×1 0715×1 0721×3 0723×3 0727×1 0817×1 0820×1 0903×2 0904×1 0908×1 0910×1 0915×2 0916×3 0917×1 0918×2 0923×1 0930×3 1008×2 1012×6`;
按信号类型:`buy×13 / buy_aux×18 / buy_special×5`。**10-12 的 6 条** = csi_000330(深证100ETF富国 159211)、
csi_000673(创业板50ETF华安 159949)、csi_399967(军工ETF国泰 512660)、csi_970070(创业板人工智能ETF国泰 159388)、
sse_000685(科创芯片ETF易方达 589130)、sz_div(红利ETF工银 159905),`frozen_at=2026-10-12 16:38`。

A/B 对比(基线 = 默认口径 vs 新口径 `SIGNAL_KELLY_FREEZE_UNION=1`,同库同引擎):

| 指标 | 基线 | 新口径 |
|---|---|---|
| 买信号条数 | 42,221 | 42,262(**+41**) |
| trades 行数 | 339,548 | 341,352(**+1,804**) |
| 16 象限 × 11 模式 × 5 周期 = 880 格 | — | **变好 151 / 变差 564 / 不变 165**,最大 \|Δrmh\| = **1.86pp** |

`period=all` + `A`(固定 10 天)逐象限(最接近页面 A 档口径的视图):

| 象限 | n 基线→新 | rmh 基线→新 | Δ |
|---|---|---|---|
| sig_main | 1435→1450 | 14.07→12.78 | **-1.29** |
| etf_strong | 1558→1569 | 10.20→9.82 | -0.38 |
| sig_aux | 2244→2265 | -3.92→-4.12 | -0.21 |
| mkt_a | 1178→1182 | 14.57→14.42 | -0.16 |
| rating_low | 6109→6148 | 6.86→6.73 | -0.13 |
| mkt_concept | 3940→3955 | 13.79→13.71 | -0.08 |
| mkt_global | 616→617 | 2.47→2.40 | -0.08 |
| rating_mid | 1522→1524 | 17.14→17.12 | -0.01 |
| etf_has_track | 1964→1968 | 12.69→12.68 | -0.01 |
| etf_related | 3064→3082 | 11.82→11.87 | +0.05 |
| mkt_industry | 1649→1670 | 6.56→6.60 | +0.04 |
| etf_approx | 1131→1139 | 13.43→13.44 | +0.01 |
| rating_high / sig_backup / mkt_hk | 不变 | 不变 | 0.00 |

**诚实解读**:补进来的多是「当时被重算抹掉」的事件,峰值资金口径下它们会与既有持仓**并发**,
分母(峰值占用资金)变大 ⇒ 多数格 rmh 略降;`tp`(总盈亏)多数格反而略升(如 sig_main tp +157)。
**方向上没有一处灾难性恶化(最大 -1.86pp),但也没有普适改善** —— 这正是必须由用户拍板、
不能由实施方自行翻默认的原因。

### 4.3 复现闸(本节的 A/B 数字可信度依据)

实施方按 §5.4⑦(复现脚本同构对账)做了**比锚点更强**的对账:

1. **基线跑 = 线上生产产物逐位一致**。用云上权威库快照 + 同一引擎跑默认口径,
   与线上 `https://ss.fx8.store/data/signal_kelly_backtest.json`(generated_at `2026-10-14 05:15`)
   做结构对账:**排除 `generated_at` 后 880/880 格逐字段完全相同(差异格 0)**;
   文件字节数同为 564,104B,gzip 同为 80,110B。⇒ 本次 A/B 与我方基线**即生产口径**,零漂移。
2. **锚点 161.63% / 155.42% 的口径说明(必须诚实标注)**:
   memory `kelly-backtest-caliber-authority` 的锚点是**页面「全信号表」实测值**,页面默认**含 S06 动态降亏过滤**
   ——S06 是**前端客户端开关**(`_kellyPassesFadeFilters`),`signal_kelly_backtest.py` **刻意不含**(引擎只出未过滤的
   象限统计)。这一点在上一份同族报告里已明确记录:`docs/auto-trade/k-day-vs-a-20260922.md:156`
   「复刻链不含 S06 过滤;若要严格复刻页面,需复刻全部键谓词…属第二份实现有漂移风险,本次未做」,
   当时的含 S06 复刻链是 `/tmp/kelly_hold_sweep.py`(**临时文件,已不存在**)。
   ⇒ 用本仓脚本复现 161.63% 需**新建第二份前端实现**(正是 §5.4⑦ 要根治的漂移源),故本节改用
   「**与线上产物逐位对账**」作为等价(更强)的过闸证据:证明本次 A/B 落在**生产基线口径**上。

---

## 5. 止血 — 冻结表孤儿买事件候选清单(只读,**未执行**)

- 脚本:`scripts/trades_orphan_backfill.py`(只读候选生成器)
- 输入:冻结表 JSON + `signal_daily`(只读 `mode=ro`)+ `etf_daily`(只读)
- 输出:候选 JSON(每条:`date / index_id / signal / etf_code / etf_name / buy_date / buy_price / frozen_at`)
- **防前视(§5.1⑥)**:买价恒取「信号日之后第一个有行情日的 `open`」——信号日 t 收盘出信号,t+1 开盘成交
- **硬约束:绝不往 `signal_daily` 插行**(下次全表重算会再次抹掉 ⇒ 治标不治本且制造假账);
  补账去向 = T2「冻结表优先」入账源(待拍板)
- 真数据实测(云上库快照,本地 `/tmp` 副本):**36 条孤儿事件全部解析出次日 open(no_price=0)**

**真实执行前置(本脚本自己不会去执行,须主控批准窗口)**:
① §25 备份并实测可恢复 ② §14 时点窗口——盘中 09:30-15:30 / 盘后 15:35·16:00·17:50·20:35·22:00
不写生产 DB(**应急同样不豁免**)③ 主控批准窗口后再跑。当前状态:**未执行,等待主控给窗口**。

---

## 6. §23.2 同类错误面清单(逐项判定,不逐文件打补丁)

| # | 写入点 | 模式 | 判定 |
|---|---|---|---|
| 1 | `app/compute/signals.py::store`(signal_daily) | 全表 DELETE + 重算 INSERT | **已覆盖(T1)** |
| 2 | `app/collector/runner.py::upsert_index_rows` | 整段 UPSERT 全字段替换 | **已覆盖(T3)** + source(T5) |
| 3 | `app/collector/index_backfill.py` ×3 单行兜底 | 单行 UPSERT 覆盖历史行 | **已覆盖(T3,本轮补)** + `source='backfill'` |
| 4 | `app/collector/intraday_snapshot.py:1300` 历史计算法 | 单行 `UPDATE close` | **已覆盖(局部字段审计,本轮补)** + `source='calc'` |
| 5 | `app/collector/intraday_snapshot.py` 反哺/补采(1166/1350/1498) | 单行写入 | **当日行(date==运行日),审计范围外**;已加 `source='intraday_snapshot'` |
| 6 | `app/collector/runner.py::upsert_metric(s_many)`(daily_metric) | 整段 UPSERT | **已有保护**:`WHERE daily_metric.source != 'manual'`(既有「防覆盖手动补录」模式) |
| 7 | `app/collector/width_history.py` / `bj_width.py` / `cleanup_d3d2.py` / `backfill_lianban.py` | 整段 UPSERT | **已有保护**:同款 `WHERE source != 'manual'` |
| 8 | `app/collector/stock_daily.py` / `baostock_daily.py` / `mootdx_daily.py` / `hkex_ccass_quarterly.py` | 按 (code,date) UPSERT | 个股/ETF 行情原子行,**不产出信号**,且逐行幂等;非本根因面(低风险,标注) |
| 9 | `app/collector/public_fund.py` ×4 | UPSERT | 公募基金库,独立域;非本根因面(低风险,标注) |
| 10 | `signal_intraday_log` | **append-only** 过程历史 | 无「抹除」语义,反而是本次断案的关键证据链(E1) |
| 11 | `signal_kelly_etf_freeze.json` | 只增不改 | 有固化保护,是本次唯一铁证源 |
| 12 | `signal_stats.json` / `board_etf_map.json` | 每日整体重生 | 无「历史行」概念(单日快照),不存在抹除问题 |

## 7. §23.3 举一反三(同模式/同数据源/同组件还被谁用)

| 同族 | 结论 |
|---|---|
| `index_daily` | ✓ 本轮全覆盖(#2/#3/#4,8/8 写入点带 source) |
| `signal_daily` | ✓ T1 覆盖唯一写方(全仓 grep 无其它写方) |
| `signal_stats.json` | 单日快照,无历史行;不适用 |
| `signal_kelly_trades.json` | 由冻结表保护 + 每日整体重生;孤儿(=冻结表有、现值无)本轮已做成可观测(T2) |
| 上游采集链(baostock/腾讯/新浪/ths 兜底) | 全部经 #3/#4/#5 的 `index_daily` 入口落库 ⇒ source + 审计全覆盖 |
| export / R2 上传链 | 只读产物、不写 DB ⇒ 无「重写历史行」面 |
| 前端展示位(全信号表 / lab 凯利区 / trades 卡) | 读同一批 JSON;数据层修复后无需前端改动(本包未触前端 ⇒ 不涉 §21 公示/§24 版本串) |

---

## 8. 自测证据(§18 L48:通知类自测必须先打桩 + 先证打桩生效)

- 测试文件:`scripts/tests/test_252_trades_wipe_rootfix_20261014.py`(**18 用例**)
- 覆盖:T1 消失/出现/纯回填不告警/快照只取历史行;T3 实质改写/舍入噪声不误报/新增行不报/当日行不审/
  局部字段审计(含白名单外列名忽略)/index_backfill 兜底行过审计;T5 `source` 随整段 UPSERT 刷新;
  止血脚本 next_open 严格取次日/只读(md5 前后逐位不变)/无价跳过/`mode=ro` 拒缺失文件/`--out` 只写输出文件
- **零外发**:全 `send_alert` 出口 monkeypatch 成记录器;并用 `ZeroOutboundTrap` 包裹,
  **先打正控**(直接 `urlopen` ⇒ 断言必炸 + 命中计数 1,证明陷阱生效),再断言本次自测 `trap.hits == []`
  ⇒ **本次自测零真实外发**
- 全量回归:`python -m pytest -q scripts/tests/` → **899 passed, 2 skipped**(CI Job1 同集)
- 回测对账:见 §4.3(与线上产物 880/880 格逐位一致)

## 9. 复现命令

```bash
# 全量回归(含本包 18 用例)
.venv/bin/python -m pytest -q scripts/tests/

# 单跑本包
.venv/bin/python -m pytest -q scripts/tests/test_252_trades_wipe_rootfix_20261014.py

# 止血候选清单(只读;本包实测命令)
python3 scripts/trades_orphan_backfill.py \
  --freeze data/signal_kelly_etf_freeze.json \
  --db data/sentiment.db --etf-db data/etf_national_team.db \
  --out /tmp/orphan_candidates.json

# T2 对比回测(同库同引擎;基线首跑应与线上 signal_kelly_backtest.json 逐位一致)
python3 scripts/signal_kelly_backtest.py --output /tmp/t2run/out/base_backtest.json --skip-parts
SIGNAL_KELLY_FREEZE_UNION=1 python3 scripts/signal_kelly_backtest.py \
  --output /tmp/t2run/out/union_backtest.json --skip-parts
```

## 10. 配套 commit

- 代码:`app/history_audit.py`、`app/notify_hook.py`、`app/db.py`、`app/compute/signals.py`、
  `app/collector/runner.py`、`app/collector/index_backfill.py`、`app/collector/intraday_snapshot.py`、
  `scripts/signal_kelly_backtest.py`、`scripts/trades_orphan_backfill.py`、`scripts/tests/test_252_trades_wipe_rootfix_20261014.py`
- 文档:本文件 + `docs/ops/trades-wipe-rootcause-20261014.md`(根因报告归档)
- 分支 `fix/trades-wipe-rootfix-20261014` 上的本 commit