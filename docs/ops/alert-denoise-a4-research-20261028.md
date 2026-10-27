# ★4（history_overwrite / kelly 常态事件降级）数据前提复核 + 修订方案

- 调查时间：2026-10-28 01:30–01:52（本机 + 云上 122.51.111.173 只读）
- 数据源：云上 `/home/ubuntu/code/trade-data/data/sentiment.db`（`sqlite3` 缺失，用 `python3 sqlite3` + `mode=ro` URI 只读打开）
- 比较器：直接 `import app.history_audit._values_changed`（main = 修好的版本，commit `8c846e1a9`），未自写第二份实现
- 回放原料：把 `history_overwrite_audit` 的 `before_val/after_val`（`_fmt_vals` 格式化串，`-`=None / `nan`=NaN / `|` 分隔，6 字段固定顺序）解析回元组后喂给真比较器
- 复现锚点：回放结果 **760 行真实变化 / 491,532 行**，与修复 commit 自述「旧 491,532 → 新 760（-99.85%）」**逐位一致** ⇒ 回放口径可信
- 落档：2026-10-28（本文件即 ★4 的实施依据；§6 = 落地方案，§8 = 未验证项，§9 = 复现命令清单）
  - 数据源口径：云上只读（`sqlite3` 以 `mode=ro` URI 打开），本机库仅镜像、不作断言依据
  - 实施回放：`/tmp/a4_replay_20261028.py`（用真函数 `plan_index_daily_alerts` / `plan_signal_daily_alert` 复跑 25 个 index_daily 批 + 21 个 signal_daily 批 = PASS：真实变化 760 / 假 490,772 / critical 0 / old_overwrite 0）

---

## 1. 结论摘要：★4 四条前提逐条判定

| 项 | 规格原前提 | 判定 | 关键数字 |
|---|---|---|---|
| **★4(a)** signal_daily 宽限复核（pending+2h）→ 日级 pure_lost=0 | 成立 | **不成立** | 日级 pure_lost 实测 0/2/2/2/1/6/4/2/1/0（非全 0）；算法回放 14 天产生 **726 条 critical 判定**，其中 10-26 17:59 **一次 562 条**假警 |
| **★4(b) 分桶阈值** small<50 / mid 50-999 / large≥1000 | 可用 | **数字全错，必须改** | 常态真实变化 **85/天（最大 87/天、单批最大 82）** ⇒ `small<50` 把常态判进 mid、`large≥1000` **永不触发** |
| **★4(b) 反例** 「10-22 02:02 的 2062 条必须保住」 | 真异常反例 | **假反例** | 该批 **2062 条 = 100% NULL↔NaN，0 条真实变化**，且只涉及 1 个指数 `csi_H30199`，不可作 E4-3 证据 |
| **★4(c)** kelly 缺失 18 天分布 `3,5,6×5,7,8×7,11,12,14` + 阈值 10 | 成立 | **成立（原样成立）** | 台账 18 条逐条复核 **完全一致**：15 条 <10（notice）、3 条 ≥10（11/12/14，critical） |
| **★4(d)** 孤儿买累计 2→11→16→21→21→21→24 | 成立 | **成立** | 台账 7 条逐条一致；但「delta>0 才发」在该窗口只 **7→5 条**，达不到规格说的 2-3 条 |
| **★4 附加发现** 「02:02 小改写占 24h 窗压掉 17:59/21:03 大批」 | 成立 | **成立，但数量级全变** | 占窗事实成立（dedup 证据见 Q4）；但 21:03 批 **0 条真实变化**（无需可见性），17:59 批是 **35–82 条**不是 4.3 万 |
| **★4(c)** 「缺失 key 集合 md5 去重能覆盖常态」 | 成立 | **未验证** | 台账只存 subject 不存 key 集合，云上无对应日志；间接证据仅「计数 8 连续 7 天、6 连续 5 天」 |

**一句话**：★4 的 (a) 是拿「批量 flip 的中间态」当假丢失，规格给的两条人工验证（10-23、10-27 未配对 0）只覆盖了 442/557 的批量流、没覆盖 1–6/天的尾巴；★4(b) 的数字全建立在假改写上，`large≥1000` 在真实数据里**一次都不会触发**，`small<50` 会让**每个交易日都报 critical**。

---

## 2. Q1：index_daily 真实变化量级分布 + 阈值

### Q1.1 数据规模与真实变化重算
审计表 `index_daily` 共 **491,532 行**（2026-10-14T16:37 → 2026-10-27T21:03），`kind` 全为 `changed`，`before_val` 100% 是 6 字段。

回放新比较器（`_values_changed(b, a, fields=_IDX_VALUE_COLS)`）：

```
index_daily total rows 491532 ; real changes 760 ; fake 490772
```

**真实变化 = 760 行 = 0.155%**（与修复 commit 自述一致）。

### Q1.2 逐日 × 逐批次真实变化

| run_date | 17:xx 批（update_all） | 21:xx 批（backfill-evening） | 16:37 批 | 02:xx 批 | 18:xx 批 | **当日合计真实** |
|---|---|---|---|---|---|---|
| 10-14 | 24,695→**82** | 24,572→**0** | 5→**5** | – | – | **87** |
| 10-15 | 24,695→**82** | 24,572→**0** | 5→**5** | – | – | **87** |
| 10-16 | 24,660→**50** | 24,572→**0** | 5→**5** | – | – | **55** |
| 10-17(六) | – | – | – | 3→**3** | – | **3** |
| 10-19 | 24,686→**77** | 23,506→**0** | 13→**9** | – | – | **86** |
| 10-20 | 24,661→**52** | 24,572→**0** | – | 3→**3** | – | **55** |
| 10-21 | 24,693→**81** | 22,510→**0** | 5→**5** | – | – | **86** |
| 10-22 | 24,691→**79** | 24,572→**0** | 5→**5** | **2,062→0** | 1→**1** | **85** |
| 10-23 | 24,696→**82** | 24,572→**0** | 5→**5** | – | – | **87** |
| 10-24(六) | – | – | 1→**1** | 2→**2** | – | **3** |
| 10-26 | 24,691→**81** | 24,572→**0** | 4→**4** | – | – | **85** |
| 10-27 | 24,647→**35** | 24,572→**0** | 3→**3** | 2→**2** | 1→**1** | **41**（当日未跑满） |

**分布**：交易日（剔除未跑满的 10-27 的 41）min **55** / p50 **86** / max **87**；非交易日（周六）2–3。
**单批分布**：`[1,1,1,2,2,3,3,3,4,5,5,5,5,5,5,9,35,50,52,77,79,81,81,82,82,82]`，**单批最大 82**。

### Q1.3 10-22 02:02 那 2062 条

```
rows in 10-22T02 batch: 2062
real changes in batch: 0   distinct index_id: 1 (csi_H30199)   distinct dates: 2062
shape 频次: 2062 × ('-','-','-','.','.','.')     # open/high/low 两端都缺失；close/pct/amount 完全相等
样例: 20130701 csi_H30199  -|-|-|1595.41|0.97|22.11  ->  nan|nan|nan|1595.41|0.97|22.11
```

**逐条分类：真实变化 0 / NULL↔NaN 2062（100%）/ 其它 0。**
⇒ 规格 ★4「10-22 02:02 的 2062 条 = 真异常反例，降级后仍必须能发现」**是假反例**，E4-3 必须换合成构造。

### Q1.4 分桶阈值结论

| 规格阈值 | 真实数据下的行为 | 结论 |
|---|---|---|
| `small < 50` | 常态日 85 行 / 单批 82 → **常态落在 mid** | 若 runner+mid → critical，则**每个交易日都发 critical**（比现状 1 条/天更糟） |
| `mid 50–999` | 常态全在这里 | 同上 |
| `large ≥ 1000` | 14 天真实单批 **最大 82**，连 1/10 都不到 | **永不触发** = 造出一个死闸门 |

**建议阈值（用真实数据推）**：`small < 200 / mid 200–999 / large ≥ 1000`
- 200 = 常态单批最大 82 的 **2.4 倍**、常态单日最大 87 的 2.3 倍 ⇒ 常态不再触发 critical；
- 1000 保留作「整段重写」安全网（14 天 0 次，属**合法的永不触发**——但必须用合成反例证明它会响，不能拿 2062 当证据）。
- ⚠️ 仅靠数量阈值仍有缺口：**500 行旧历史被改成别的值**会落在 mid、**80 行旧历史被抹**会落在 small。所以必须加第二维度（见 §3 方案 b-3）：
  **行龄 × 变化类型**——实测 14 天 760 行里，「value→value（真覆盖）」**只出现在行龄 ≤7 天的行上**；行龄 >30 天只有 `fill`（12 行）和 `wipe`（271 行），**`correct` = 0**：

| 行龄 | 仅 correct | correct+fill | 仅 fill | 仅 wipe |
|---|---|---|---|---|
| 0–7 天 | 172 | 268 | 37 | 0 |
| 31–365 天 | **0** | **0** | 12 | 10 |
| >365 天 | **0** | **0** | 0 | 261 |

### Q1.5 计划内回填（index_backfill）vs runner

审计表**无 source 列**（schema 只有 `detected_at/run_date/src_table/kind/date/index_id/signal/before_val/after_val`），无法程序化归因；按「时间戳 ↔ systemd timer」对照：

| 批次时点 | 对应单元（实测） | 记录行/真实行 |
|---|---|---|
| 17:59:43–17:59:50 | `trade-update-all` 17:50:01 启动 → `update_all.sh` → `runner.upsert_index_rows` | 24,647 / **35–82** |
| 21:02:53–21:03:16 | `trade-backfill-evening` 21:00:01 启动 → `backfill_metrics.sh:29` → `index_backfill.main` | 24,572 / **0（12 天全 0）** |
| 02:xx / 05:xx / 16:37 | 海外指数夜间链路（ftse100/cac40/dax/nikkei 的 pct/amount **值→缺失**） | 1–5 / 1–9 |

**结论：计划内回填（index_backfill）对「真实变化」贡献 0 条**——它那 2.4 万行全是 NULL↔NaN 表示差异；真正产生变化的只有 17:50 的 update_all（T+1 源值修正 + OHLC 补全）。
**未验证**：02:xx/05:xx/16:37 小批的具体写入脚本（只确认不是 update-all、也不是 backfill-evening）。

---

## 3. Q2：signal_daily「两阶段重算造成假 pure_lost」

### Q2.1 批次结构（实测）
审计表 `signal_daily` **18,020 行**，`kind` 只有 disappeared / appeared（无 changed）。每日 2 批：

- 第 1 批 **16:44**、第 2 批 **17:58–18:00** ⇒ **间隔 73/73/73/75/73/74/76/75/76 分钟（9 天实测，全部 < 2h）**
- 10-20 有第 3 批 **21:28**（距第 2 批 208 分钟）、10-23 有第 3 批 **21:31**（距第 2 批 210 分钟）
- 10-26 **只有 1 批**（17:59），当天的 16:44 批**根本没跑**

### Q2.2 批量 flip 的真相（规格这条是对的）
- 16:44 批：消失 440–444 / 出现 557 → **被后续批 100% 还原**（restored_by_later = 440/442/444，never_back = 0–2）
- 17:58 批：消失 557–563 / 出现 440–447 → 当日不再还原，**次日 16:44 批还原 557**（10-14→10-15、10-15→10-16… 连续 6 次 557/557）
- 即 signal_daily 在 **两个状态 A/B 之间来回翻**，每次翻动涉及 ~1,000 行（表总 71,836 行）

### Q2.3 日级 pure_lost ≠ 0
按 `(date,index_id)` 口径、按 run_date 取当日全部批次并集：

```
run_date   消失  出现  pure_lost
20261014   983   987      0
20261015   985   984      2
20261016   985   983      2
20261019   990   990      2
20261020   986   988      1
20261021   991   985      6
20261022   989   985      4
20261023   987   988      2
20261026     2     9      1
20261027   985   986      0
```

**规格「日级 pure_lost = 0」只在 10-14 和 10-27 成立**，其余 8 天 1–6 条。

### Q2.4 宽限复核算法回放（按规格 (a) 伪代码实跑）

伪代码落成 30 行 Python（pending dict，key=(date,index_id,signal)，先「回表→移除」再「仍缺且 age≥2h→critical」再「本批候选入 pending」），在 21 个真实批次上顺序回放：

```
detected_at           dis  app  back  CRIT newpend  pend
2026-10-14T16:44:24   440  557     0     0     426   426
2026-10-14T17:58:17   557  444   426     0     543   543
2026-10-15T16:44:56   440  557   543     0     426   426
...
2026-10-23T21:31:21   557  442   428    19     543   562
2026-10-26T17:59:24     2    9     0   562       1   563   ← 假警 562 条
2026-10-27T16:44:43   442  557   543    20     428   448
TOTAL critical keys across 14 days: 726
```

**两条致命问题**：
1. **10-26 17:59 一次判 562 条 critical**：10-23 21:31 入 pending 的 557 个 key，因 10-26 **没跑 16:44 批**（当日只有 17:59 一批、只还原 0 个）而一直「仍缺失」，到 10-26 17:59 已 age=92h ⇒ 全量判 critical。**2h 时间窗 + 「下一次运行一定还原」的假设，在真实运行里不成立。**
2. **常驻滴水 2–6 条/天**：14 天有 **24 个 key 永不再现**（如 `20261015|csi_000102|buy`、`20261016|gz_399417|buy_aux`），每个 age 越过 2h 就 critical 一次。其中 `csi_000102` 正是 2026-10-28 映射纠错（sh000102→sz399102）涉及的对象 ⇒ 属**重算的确定性结果**，不是数据丢失。

**结论：★4(a) 按原样实施会从「每天 2 条假 critical」变成「每天 1–6 条假 critical + 偶发 562 条雪崩」，判别力没提升。**

### Q2.5 10-26 单批 11 条：真丢还是补回？
11 行 = 2 disappeared + 9 appeared：
- disappeared：`20261023|gz_399417|buy_aux`、`20261023|hk_hscci|buy`
- 这 2 个 key 在 10-27 及以后**都没有再出现** ⇒ **不是「第二阶段补回」，是当日重算的确定性结果**（同批新增 9 个其它 key，属重算换了一批）
- 量级：2 / 71,836 行 = 0.003%，判「重算噪声」，非真丢失。

---

## 4. Q3：kelly 两条

### Q3.1 signal_kelly_frozen_missing_small（台账 `data/alerts/alert_ledger.jsonl`，18 条）

```
2026-10-10 21:12:14  8    2026-10-19 05:07:18  6
2026-10-11 21:12:32  8    2026-10-20 07:09:48  7
2026-10-13 02:13:06  3    2026-10-21 07:10:08  8
2026-10-14 02:24:53  5    2026-10-21 16:35:40 14   ← severe
2026-10-15 02:32:17  6    2026-10-22 07:12:39  8
2026-10-16 03:09:46  6    2026-10-23 07:13:07  8
2026-10-17 05:03:50  6    2026-10-24 16:51:01  8
2026-10-18 05:06:48  6    2026-10-25 21:13:01  8
2026-10-26 16:30:01 11   ← severe
2026-10-27 02:13:55 12   ← severe
```

分布 = `3,5,6×5,7,8×7,11,12,14`，**与规格逐项一致**；<10 共 **15 条**、≥10 共 **3 条**。阈值 10 保留成立（正常最大 8，+25% 余量）。

**md5 key-set 去重可行性 = 未验证**：台账只存 `subject`（不含 body/key 集合），云上 `data/logs/` 无 `冻结缺失` 字样日志（grep 0 命中）。间接证据：8 连续 7 天、6 连续 5 天 ⇒ 集合**可能**稳定，但「同计数 ≠ 同集合」。
**验证方法（需 3–5 天）**：在 `_alert_frozen_missing` 加一行 `print(sorted(new_events))` 落日志，或直接把 md5 写进 dedup key 并观察是否真降。
**兜底方案（不依赖验证）**：small 档改为「只写日志 + 进 23:25 摘要」，不发邮件 —— 15 条/18 天直接归零，且真异常（≥10）仍 critical。

### Q3.2 kelly 孤儿买（7 条，累计口径）

```
2026-10-20 18:19:08   2      2026-10-25 05:07:07  21
2026-10-22 00:25:56  11      2026-10-26 07:12:42  21
2026-10-23 02:16:38  16      2026-10-27 07:13:08  24
2026-10-24 05:06:40  21
```

累计 **2→11→16→21→21→21→24**，与规格一致（单调不减，**14 天里没有出现「新增又消失」造成回退**）。
delta = **2, 9, 5, 5, 0, 0, 3** ⇒ 「delta>0 才发」在该窗口 **7 → 5 条**，**达不到规格写的 2–3 条**。
若再收紧为「delta ≥ 5 才发」⇒ 命中 9/5/5 共 **3 条**（delta 序列 2,9,5,5,0,0,3）。**这是数据支撑的推荐档位。**

---

## 5. Q4：24h dedup 占窗证据

云上 `data/notify_dedup.json`（139 个 key）实测：

```
history_overwrite:index_daily:20261027:critical -> {'last_alerted': '2026-10-27 02:02:35'}
```

当天 17:59 批（24,647 行记录）与 21:03 批（24,572 行记录）**无独立台账条目** ⇒ **占窗成立**（`scripts/notify.py:1829 check_dedup`，key 在 `app/history_audit.py:389-391` 构造为 `history_overwrite:{src_table}:{run_date}:{critical|notice}`）。

**但修复后占窗仍在**：10-27 02:02 那批在新比较器下仍有 **2 条真实变化**（`20221110|ftse100`、`20221125|cac40`，pct/amount 值→缺失），照样写同一个 `...:20261027:critical` key ⇒ 17:59 的 35–82 条仍被压。
⇒ **★4(b) 的分键不可省**；且「真变化降到 85/天」**不会**自动消除占窗（占窗与数量无关，是 key 相同）。

---

## 6. 修订后的 ★4 实施方案草案（可直接落地）

### (a) signal_daily：**放弃 pending+2h，改「单批净变化 + 日期覆盖率」两条无状态判据**

落点：`app/history_audit.py:325 _alert()` 的 `critical = n_pure > 0`（**L357**），以及 `audit_signal_daily_store`（diff 完成后调用处）。

1. 计算两个指标（diff 里已有 `changes`，再加一条 `SELECT date,COUNT(*) FROM signal_daily GROUP BY date`，71,836 行、毫秒级）：
   - `net = len(appeared) - len(disappeared)`
   - 对每个 date：`before = after + dis - app`；`drop = before - after`
2. **critical 判据（两条任一）**：
   - `net <= -200`
   - 任一 date `drop >= 20 且 drop/before >= 0.30`
3. 否则 **notice**（dedup 24h，进摘要）。

**依据（可修正）**：21 个真实批次回放，`net ∈ [-121, +117]`，带绝对下限（≥20 行）的日期跌幅最大 **0** ⇒ 14 天 **0 次误报**。
**实现预期（X→Y）**：signal_daily critical **2 条/天 → 0 条/天**；notice 2 → 1 条/天（24h 窗合并）。
**证据用例**：
- 正控（必须不响）：用本报告回放脚本重跑 14 天 21 个批次，断言 critical 计数 **= 0**。
- 反例 1（必须响）：早快照 500 行、晚快照 0 行 → `net=-500` → critical。
- 反例 2（必须响）：某 date 90 行 → 60 行 → `drop=30 ≥20 且 33% ≥30%` → critical。
- 边界（必须不响）：某 date 3 行 → 2 行 → `drop=1 <20` → notice。
**风险（诚实标注）**：敏感性下限 = 单日 20 行 / 净 200 行；**1–2 行级真丢失不再 critical**。这条能力由「孤儿买检测」（`scripts/signal_kelly_backtest.py:508 _alert_freeze_orphans`）承担，不应指望 history_audit —— 现状它本来就被 442/557 淹没，保不住 1 行级。
**机检**：回放脚本 + 4 条单测（含冻结时间注入，避免 L51 隔天红）。

### (b) index_daily：分键 + 分桶 + **加一条「旧行真覆盖」判据**

落点：
- `app/history_audit.py:148 audit_index_rows_upsert`（加 `caller: str = "runner"`）
- `app/history_audit.py:188 audit_index_row_partial`（同上，`caller="partial"`）
- `app/collector/runner.py:143` 传 `caller="runner"`；`app/collector/index_backfill.py:78` 传 `caller="index_backfill"`（该模块另在 L293/310/346/361/393 经 `runner.upsert_index_rows` 写入，需同步传参）
- dedup key：`app/history_audit.py:389-391` 改 `history_overwrite:index_daily:{run_date}:{caller}:{bucket}`

1. bucket 由本批 `len(changes)` 决定：`small < 200`、`mid 200–999`、`large >= 1000`（**原 50/1000 作废**，见 Q1.4）。
2. 分级：`caller=index_backfill` → notice；`caller=runner` 且 mid/large → critical；small → notice。
3. **新增 `old_overwrite` 桶（推荐，治「数量小但性质严重」）**：本批里存在「行龄 ≥30 天 且 至少一个字段 value→value 且超出容差」的行 ⇒ **critical（独立 key）**。
   - 依据：14 天 760 行真实变化中，行龄 >30 天的 `correct` 行 **= 0**（0–7 天 172 纯 correct + 268 correct+fill，31 天以上 0）。
   - 预期：常态 0 次；一旦旧历史被改成别的值（trades-wipe 同型）当天就响，且不会被数量阈值稀释（哪怕只 1 行）。
4. `_INDEX_DEDUP_WINDOW` 保持 86400（同桶一天一条）。

**可见性（E4-4 替代）**：small 桶只落表 + 进 23:25 摘要，不单发 —— 因为 85 条/天的 T+1 修正是常态、单发无信息量。若坚持「每批可见」，则把 notice 的 window 降到 3600（02:xx 与 17:59 相隔 17h，各自可见），代价 ≈ +1 条/天。

**证据用例**：
- E4-3（重写）：合成 2,062 行真实 value→value → `large` → critical；合成 1 行 → small → notice。
- E4-3'（新增，替代假的 2062 现网反例）：把 10-27 的 2 条 `ftse100/cac40` 值→缺失喂进去 → small → notice（正确：这 2 条不是 critical 级）。
- 反例 3：构造 250 行真实改写（caller=runner）→ mid → critical。
- 反例 4：构造 1 行行龄 400 天的 close 6562→3367 → old_overwrite → critical。

### (c) kelly 缺失：阈值 10 保留；notice 两选一
- **推荐（不依赖未验证前提）**：small 档（<10）改为「只写日志 + 进摘要」，不发邮件 ⇒ 预期 **15 条/18 天 → 0**，≥10 的 3 条不变。
- 备选：`dedup_key = signal_kelly_frozen_missing_small:{md5(sorted(keys))[:8]}`，window 86400 —— 但**效果完全取决于 key 集合是否每天不变，本单未验证**，必须先落 3–5 天 key 集合日志再定。
- 依据：台账 18 条分布逐项复核一致（Q3.1）。

### (d) kelly 孤儿买：改「净新增 ≥5 才发」
- 落点：`scripts/signal_kelly_backtest.py:508 _alert_freeze_orphans` 增加 `delta = n - prev_n`（prev_n 需落状态文件，或用 `--dedup-key` 携带）判据。
- 依据：累计 2→11→16→21→21→21→24，delta = 2,9,5,5,0,0,3 ⇒ `delta>0` 出 5 条、`delta≥5` 出 **3 条**。
- 预期 X→Y：7 条/9 天 → **3 条/9 天**；正文写「新增 N 条（累计 M）」。
- 风险：若某日新增 4 条且持续 3 天，会累积到 12 条才报一次 —— 可接受（孤儿买是「历史行被抹」的辅助证据，不是 P0 首报）。

### 6.5 顺带发现（超出 ★4 范围，但修复后会被新审计首次暴露，必须单独立项）

新比较器上线后，每天约 85 条真实变化里有一块**真实的数据退化**，不是噪声：

- **pct_change 值→缺失 共 283 行 / 14 天，32 个指数**，按日 29–34 条（交易日）：`thsc_*` 233/283（82%），其余是 ftse100/dax/cac40/nikkei225/kospi 各约 10 条。
- 库内现状已核实：`(20250909, thsc_300816)` 的 pct_change **当前就是 NULL**；`(20260105, thsc_308700)` 被清空后又被后续批次写回 2.0769 ⇒ 属「反复清空/回填」的抖动。
- 另 `(20221110, ftse100)`、`(20221125, cac40)` 是海外链路把 2022 年老行的 pct 抹成 NULL（就是 10-27 02:02 那条吃掉 dedup 窗的记录）。

⇒ 建议：**不要**把这类「值→缺失」当 critical（否则日报 29 条），但应在摘要里单列「历史行字段被清空 N 条/日」，并给 thsc 与海外两条写入链路各开一个 data-quality 工单（本单不修）。

---

## 7. 冲突面

| 文件 | ★4 是否改 | 批次2 分支（`fix/alert-denoise-batch2-20261028`）是否改 | 处置 |
|---|---|---|---|
| `app/history_audit.py` | **是**（325/357/389-394/148/188） | 否 | 可并行 |
| `app/collector/runner.py` | 是（143 加 caller） | 否 | 可并行 |
| `app/collector/index_backfill.py` | 是（78 加 caller；293/310/346/361/393 传参） | 否 | 可并行 |
| `scripts/signal_kelly_backtest.py` | 是（384-395 / 508-545） | 否 | 可并行 |
| `scripts/notify.py` | **否**（只用 `--dedup-key/--dedup-window`，不改实现） | **是（45 行）** | 无重叠，但**同一 merge 窗口**要串行过 `main-merge.sh` |
| `scripts/alert_denoise_rules.py` | 否 | **是（30 行）** | 同上 |

实测批次2 分支改动范围（`git diff --stat main...fix/alert-denoise-batch2-20261028`）：`alert_denoise_rules.py / check_failed_units.py / notify.py / schedule_monitor.sh` + 4 个测试文件，**与 ★4 零文件重叠 ⇒ 代码可并行**。
唯一串行点：两者都要进 main，`main-merge.sh` 一次一支；且若 ★4 后续想在 `notify.py` 里加「多 dedup key / 摘要汇入」就会与批次2 撞车 —— 本方案刻意不碰 `notify.py` 以保持可并行。

---

## 8. 诚实标注（未验证 / 数据不足）

1. **frozen_missing 的 key 集合稳定性 = 未验证**：台账无 body、云上无日志。影响 ★4(c) 的 md5 方案效果，故推荐改为「small 档只进摘要」。
2. **02:xx / 05:xx / 16:37 小批的写入脚本 = 未定位**：审计表无 source 列，只能排除 update-all 与 backfill-evening。
3. **14 天窗口外的行为未知**：所有阈值来自 2026-10-14~10-27 共 14 天；更长基线（尤其季度末/全量重建）无法取得 —— 审计表本身是 10-14 才建的。
4. **「旧行 value→value = 0」是 14 天样本**，不是物理定律；作为 critical 判据时若真出现（如计划内的一次性历史修正）会报一次，属可接受的真阳性。
5. **本报告回放有 6 位有效数字精度损失**（`_fmt_vals` 用 `%g`）：相对误差 ~5e-7，远小于 1e-4 容差 ⇒ 不影响 760 的结论；但「几乎相等」的边界行可能有个位数差异，未逐行验证。
6. **signal_daily 的 16:44 批由谁触发 = 未定位**：`systemctl list-timers --all` 无 16:4x 项；`systemctl --user list-timers` 0 个；`trade-pf-score-daily`(16:00) 16:02 已结束；`us_stock_morning`(05:00) / `intraday_snapshot`(09:25 起) 均不是。**但「每天两批、间隔 73–76 分钟」是 9 天实测事实**，与触发者无关。

---

## 9. 复现清单

```bash
# 1) 拉审计表到本地（云上无 sqlite3 CLI，用 python3 sqlite3 只读）
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'python3 -' <<'PY' | gzip > /tmp/a4_audit.tsv.gz
import sqlite3, sys
con = sqlite3.connect('file:/home/ubuntu/code/trade-data/data/sentiment.db?mode=ro', uri=True)
for r in con.execute("SELECT detected_at,run_date,src_table,kind,date,index_id,COALESCE(signal,''),COALESCE(before_val,''),COALESCE(after_val,'') FROM history_overwrite_audit ORDER BY id"):
    sys.stdout.write("\t".join(str(x) for x in r) + "\n")
PY

# 2) 回放新比较器（本机，main 分支）
python3 -c "
import gzip,sys; sys.path.insert(0,'/Users/linhuichen/code/trade')
from app.history_audit import _values_changed,_IDX_VALUE_COLS
def parse(s):
    return tuple(None if t in ('-','') else (float('nan') if t.lower()=='nan' else float(t)) for t in s.split('|'))
n=r=0
for line in gzip.open('/tmp/a4_audit.tsv.gz','rt'):
    p=line.rstrip().split('\t')
    if p[2]!='index_daily': continue
    n+=1; r+=_values_changed(parse(p[7]),parse(p[8]),fields=_IDX_VALUE_COLS)
print('index_daily',n,'real',r)"
# 期望：index_daily 491532 real 760
```
