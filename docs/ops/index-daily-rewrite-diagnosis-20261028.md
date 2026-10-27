# index_daily「每天约 4.3 万行历史改写」诊断（只读调研）

- 调研日期：2026-10-28
- 数据源：云上权威库 `/home/ubuntu/code/trade-data/data/sentiment.db`（`mode=ro` 只读）、`data/alerts/alert_ledger.jsonl`、`data/notify_dedup.json`、`data/logs/`、`systemctl` 单元
- 本机代码基线：分支 `fix/alert-email-gate-hardening-20261027`（HEAD `f7198e751`）
- 云上零写：未写库、未改文件、未重启服务、未跑生产脚本

---

## 0. 一句话结论

**混合，但主导成分是「缺陷」（置信度：高）。**

「每天 4.3 万行历史改写」里 **99.77% 是审计误报，数据库里的值一个字都没变**：23 个「中证指数公司源」指数（`stock_zh_index_hist_csindex` 家族）的历史行 open/high/low 在库里是 `NULL`，而采集回来的值是 `NaN`；审计比较器把 `NULL → NaN` 判成「实质改写」（`app/history_audit.py:234`），而 SQLite 又把 `NaN` 存回 `NULL`（本地实测已证）——于是**每跑一次就记一次，永远记不完**。

- **缺陷部分**：49,145 行/天（10 个交易日全是这个数），完全零真实变化，是死循环误报。
- **计划内部分**：~80–128 行/天，是「上一交易日的盘中占位行 → 次日真实 OHLC/精度的正常修正」，属于设计内的 T+1 回填。
- **一次性修复部分**：无。没有「只有 10-27 才出现」的特征；同一机制至少从 2026-08-10 起每天在跑（`collect_log` 45 条逐日证据）。

> 一句话给主控：**不是数据坏了，是「审计的比较器坏了」+「每天照计划来回重采两遍」。真数据每天的变动只有 80–128 行。**

---

## 1. 关键数字（先看这张表）

| 指标 | 数值 | 证据 |
|---|---|---|
| `history_overwrite_audit` 中 `index_daily` 总行数 | **491,532** | 10-14T16:37:49 ~ 10-27T21:03:16 |
| 其中「只差 `-`（NULL）↔ `nan`」的行 | **490,384 = 99.77%** | `REPLACE(after_val,'nan','-')=before_val` |
| 其中真实变化行 | **1,148 = 0.23%** | 同上取反 |
| 每个交易日 NaN 误报行 | **49,145（固定值）** | 10 个交易日逐日一致 |
| 每个交易日真实变化行 | **80–128** | 逐日 127/127/92/126/91/125/124/128/122/80 |
| 每批涉及指数数 | 17:5x 批 **85–118** 个；21:0x 批 **23** 个 | 23 个 = csindex 家族 |
| 21:0x 批的真实变化 | **0 行（14 天全部）** | 真实变化只出现在 17/16/02/18 点 |
| 台账 `index_daily 历史行被重写` 条数 | **12 条 / 12 天**，其中 11 条是「1 条」，1 条是「2,062 条」（10-22 02:02） | `alert_ledger.jsonl` |
| 24.6k 大批次是否进过台账 | **0 次** | 同上 |

---

## 2. Q1 这是计划内行为还是异常？

### 结论
**混合**：
1. **写动作本身是计划内**——两批分别由两个每日定时任务发起，且「每天都有」。
2. **4.3 万这个量级是缺陷**——99.77% 是审计比较器把 `NULL` 和 `NaN` 当成两次不同的值，数据实际不变。
3. **不是一次性修复**——没有「只在 10-27 出现」的特征，同一节奏 14 天全在。

### 2.1 谁在写：两条写路径 + 两个定时任务（代码 + 单元 + 日志三方对齐）

**17:52–17:59 批（10-27 共 24,647 行 = 24,573 误报 + 74 真实）**

```
trade-update-all.timer  OnCalendar=Mon..Sat 17:50:00
  └─ trade-update-all.service → /home/ubuntu/code/trade-data/scripts/update_all.sh
      └─ app/collector/runner.py::run(steps=indices)          # 第 2 步「指数（拉近 400 天，等于自动回填）」
          ├─ 窗口：runner.py:292  start = date - 400 天
          ├─ 采集：fetchers.py:774 collect_index()
          │        └─ fetchers.py:792-795  csindex 源强制 start_date="20100101"（无视 400 天窗口）
          └─ 落库：runner.py:130 upsert_index_rows()
                   └─ runner.py:142 history_audit.audit_index_rows_upsert()
```

**21:02–21:03 批（10-27 共 24,572 行 = 100% 误报）**

```
trade-backfill-evening.timer  OnCalendar=16:35 / 21:00 / 02:00
  └─ trade-backfill-evening.service → scripts/backfill_metrics.sh:29
      └─ python -c "from app.collector.index_backfill import main; main()"
          └─ index_backfill.py::backfill_history_gaps()          # 第 2.5 步「历史缺口检测+补采」
              ├─ 判据：latest < target 即缺口（index_backfill.py:912-925）
              ├─ 采集：index_backfill.py:934  collect_index(idx, "20100101", date)   # 全历史
              └─ 落库：index_backfill.py:943  upsert_index_rows() → 审计
```

**为什么 21:00 每天都判定「缺口」**：中证指数公司源在 17:50 那一刻**还没发布当日数据**（latest=T-1），到 21:00 才发布 → 每天都触发「缺口补采」，且补采函数是**拉全历史**（`20100101` 起），于是每天把 23 个指数的全部历史重新 UPSERT 一遍。

日志与 `collect_log` 逐条对上（10-27）：
```
[backfill] -> 历史缺口检测+补采 ...
  [gap] ✓ div_lowvol latest 20261026->20261027 (+1行)
  [gap] ✓ csi_931151 latest 20261026->20261027 (+1行)
  ...（23 个全同）
  [缺口检测] 检查完成,补采到新数据 23 个品种
```
`collect_log` 实测：`csi_931151 | 20261027 | 缺口补采 20261026->20261027 | 2026-10-27T21:02:54.381130`，与审计 `detected_at=2026-10-27T21:02:54` 同秒。

### 2.2 是不是每天都发生：是，14 天逐日稳定

`history_overwrite_audit` 按日聚合（`WHERE src_table='index_daily'`）：

| 日期 | 首个批次时间 | 首批行数 | 批次数 | NaN 误报 | 真实变化 |
|---|---|---|---|---|---|
| 10-14 | 16:37:49 | 1 | 114 | 49,145 | 127 |
| 10-15 | 16:37:41 | 1 | 109 | 49,145 | 127 |
| 10-16 | 16:37:34 | 1 | 75 | 49,145 | 92 |
| 10-17(六) | 02:05:45 | 1 | 2 | 0 | 3 |
| 10-19 | 16:37:26 | 1 | 109 | 48,079 | 126 |
| 10-20 | 02:02:14 | 1 | 104 | 49,145 | 91 |
| 10-21 | 16:37:27 | 1 | 105 | 47,083 | 125 |
| 10-22 | 02:02:11 | **2,062** | 108 | 51,207 | 124 |
| 10-23 | 16:37:59 | 1 | 111 | 49,145 | 128 |
| 10-24(六) | 02:02:18 | 1 | 3 | 0 | 3 |
| 10-26 | 16:37:42 | 1 | 110 | 49,145 | 122 |
| 10-27 | 02:02:31 | 1 | 84 | 49,145 | 80 |

- 每个交易日固定 **49,145** 行误报（10-19/10-21 少 1,066/2,062，是当天少补了 1 个指数；10-22 多 2,062，见 §2.4）。
- 真实变化恒定在 **80–128 行/天**，量级差 400 倍。
- **不是 10-27 独有**：审计表 10-14 建表第一天就是这个量级；`collect_log` 里 csindex 的「缺口补采」最早可追到 **2026-08-10**（45 条逐日），说明这套机制早在审计表上线前就每天在跑。

### 2.3 为什么 24,572 行「没变也被记成变了」——死循环的机制（本任务的核心根因）

三件事叠在一起：

1. **数据源给 `NaN`**：`stock_zh_index_hist_csindex` 返回的 DataFrame 里，历史行的 open/high/low 是 pandas 的 `NaN`（不是空串），`fetchers.py:823 g()` 里 `float(NaN)` 原样返回 `nan`。
2. **比较器把 `None` 和 `nan` 判成不同**：`app/history_audit.py:229-235`
   ```python
   if a is None and b is None: continue
   if a is None or b is None:   return True      # <- a=None, b=nan 命中这里
   ```
3. **SQLite 把 NaN 存成 NULL**：本地实测
   ```
   >>> c.execute('insert into t values (?)',(float('nan'),)); c.execute('select x,typeof(x) from t').fetchall()
   [(None, 'null')]
   ```
   库里实测：`SELECT open,typeof(open) FROM index_daily WHERE index_id='csi_932365' AND date='20200102'` → `(None,'null')`。

于是形成闭环：**库里 NULL → 采集回 NaN → 审计判"变了"，落 1 行 → UPSERT 把 NaN 写回，SQLite 存成 NULL → 下一轮再来一遍**。同一条 `csi_932365/20200102` 在 14 天里被记了 **20 次**，每次都是同一个 before/after：

```
before: -|-|-|2354.37|1.4|251.25      after: nan|nan|nan|2354.37|1.4|251.25
（- 表示 NULL；close/pct/amount 三位在 20 次里一字未变）
```

**这是审计比较器的缺陷，不是采集缺陷、更不是数据损坏。**

### 2.4 10-22 02:02 那 2,062 行是什么

同样是 NaN 误报，只是对象换成了 `csi_H30199` 一个指数的全部历史（2013-06-28 起 2,062 行）：`-|-|-|0|0|22.15 → nan|nan|nan|0|0|22.15`。原因是当天 02:00 槽触发了一次单指数「缺口补采」（拉全历史），把该指数整段历史一次性"记"了一遍。它不是真异常，而是同一缺陷的一次性放大版——**这一点对 ★4 的验收用例很关键（spec 把 2,062 当"真异常样本"，实际上它也是误报）**。

### 2.5 重复跑是否幂等

- **数据层：幂等**。同样的输入跑 N 次，库里的值不变（NULL 还是 NULL）。
- **审计层：不幂等**。每跑一次就多记 24,572 行，"改写"计数只增不减。这正是「每天两次、每次 2.4 万」的来源。

### 2.6 「禁止在诊断前降级掩盖」复核

`docs/ops/alert-denoise-spec-20261027.md:465` 已写明「在诊断完成前**不要**直接把大批次降级掩盖」。**复核通过：现有代码未做任何降级**——`index_daily` 走 `pure_lost=None` 分支恒 critical（`history_audit.py:322-323`），只是被 dedup 吞了，不是被降级了。本条无需改动。

---

## 3. Q2 改写内容的性质分布

### 3.1 聚合口径

- `kind`：**491,532 行全部是 `changed`**（index_daily 的审计只记"已存在且值变"的行，不记新增/消失）。
- `signal`：**全部 NULL**（0 行非空）——index_daily 行没有 signal 概念。
- `index_id`：近 14 天共 **124 个**不同指数，但 99.5% 的行集中在 **23 个 csindex 家族指数**（`csi_benefited_932365` 一个就 54,800 行）。

### 3.2 按性质分类（14 天全部 1,148 条真实变化）

| 性质 | 行数 | 占比 | 说明 |
|---|---|---|---|
| 同日 OHLC 完全没变、只有 pct/amount 精度变化 | 450 | 39.2% | 快照写 2 位小数（如 -0.71），历史源写全精度（-0.708668），相对容差 1e-4 对 pct 太紧 |
| OHLC 变了但 close 变化 <0.5% | 476 | 41.5% | 占位（OHLC 全等于 close）→ 真实 OHLC 的正常修正 |
| close 变化 0.5%–2% | 170 | 14.8% | 同上 |
| close 变化 2%–10% | 42 | 3.7% | 同上（当日振幅大） |
| **close 变化 ≥10%** | **10** | **0.9%** | **全部是同一个指数 `csi_000102`，见 §3.3** |
| 合计 | 1,148 | 100% | 平均 **82 行/天** |

其中「占位行（open=high=low=close）→ 真实 OHLC」共 **148 行**（约 11 行/天），是盘中快照 `intraday_snapshot` 写的当日行被次日采集覆盖，**属于设计内的 T+1 修正**（见 `intraday_snapshot.py:1334-1385`）。

### 3.3 那两个抽样：哪边是对的？

**`csi_000330`（深证100）：后值对，前值是盘中占位价**

```
20261026  before: 4886.59|4886.59|4886.59|4886.59|-1|-
          after : 4886.59|4932.384|4841.428|4898.295|-0.767255|-
```
- 前值 OHLC 四列全等于同一个数、amount 为空 = 典型"盘中快照占位行"（`intraday_snapshot` 写 `open=high=low=close=快照价`）。
- 后值 open=4886.59 恰好等于前值的 close，close=4898.295；用后值反算前收：4898.295/(1-0.00767255)=**4936.17**，而库中 10-23 收盘 = **4936.168** —— 内部自洽，**后值正确**。
- 结论：这一条是**占位 → 真实 OHLC 的正常修正**，不是纠错。

**`csi_000102`：后值对，前值是「写错了标的」**

```
20261026  before: 6562.71|6562.71|6562.71|6562.71|-0.88|-
          after : 3367.89|3396.24|3319.9|3354.83|-1.57514|-
```
- `config/indicators.yaml:301` 定义 `csi_000102 = 创业板综 / symbol sz399102`，真实点位量级 ~3350-3450，**后值正确**。
- 前值 6562.71 是谁？查 `app/collector/intraday_snapshot.py:1399`：
  ```python
  "csi_000102": "sh000102",  # 沪投资品
  ```
  **同一个 id 被盘中快照映射到了另一个指数（沪投资品 sh000102）**，而配置里 `csi_000102` 是创业板综。这不是"占位"，是**张冠李戴**。
- 量级佐证：14 天里所有 close 变化 ≥10% 的行 **10 条全是 csi_000102**，且每天稳定 ~48%（6562/3354≈1.96）。这是系统性错值，不可能是巧合。
- 影响面：每个交易日盘中到次日 17:50 之前，`csi_000102` 当日行显示的是**沪投资品的点位和涨跌幅**；若该时段参与任何计算/导出，就是错数（本次未展开查下游影响，列为遗留问题）。

> 注：`docs/ops/alert-denoise-spec-20261027.md:460` 写的抽样 `csi_000102 6562.71→3367.89` 读的是 after 的**开盘价**字段，收盘价是 **3354.83**；同一行 A1 里 `23,931 / 19,476` 两个行数也复现不出来，库内实测是 **24,647 / 24,572**（见 §7 口径修正）。

### 3.4 有没有整表重写

- **审计口径上：是。** 23 个 csindex 指数每次运行都会把 2010-01-01 起的**全历史**逐行"记一遍"（合计 24,572 行），但 close/pct/amount 一位没变，只有 NULL→NaN 的表示变化。
- **真实数据口径上：没有。** 14 天里没有任何一次真实的全表重写。

---

## 4. Q3 dedup 键的设计缺陷有多大

### 4.1 键与去重语义（代码）

- 键：`history_overwrite:{src_table}:{run_date}:{critical|notice}`（`app/history_audit.py:340-341`）
- 窗口：`_INDEX_DEDUP_WINDOW = 86400`（`history_audit.py:43`），critical 用 24h
- 机制：`scripts/notify.py:1792 check_dedup()` 命中同键同窗即 suppress；发送成功才 `update_dedup()`（`:1826`）
- 后果：**同一张表、同一天，全站只有 1 次播报机会**。

### 4.2 近 14 天实测：12/12 天被小批次先占键，大批次全部被吞

| 日期 | 占键批次（时间/行数） | 之后的大批次（行数） | 大批次是否进台账 |
|---|---|---|---|
| 10-14 | 16:37:52 / **1** | 24,695 + 24,572 | 否 |
| 10-15 | 16:37:45 / **1** | 24,695 + 24,572 | 否 |
| 10-16 | 16:37:38 / **1** | 24,660 + 24,572 | 否 |
| 10-17 | 02:05:49 / **1** | （仅 2 行） | 否 |
| 10-19 | 16:37:29 / **1** | 24,686 + 23,506 | 否 |
| 10-20 | 02:02:17 / **1** | 24,661 + 24,572 | 否 |
| 10-21 | 16:37:31 / **1** | 24,693 + 22,510 | 否 |
| 10-22 | 02:02:14 / **2,062** | 24,691 + 22,510 | 否（02:02 那条已发） |
| 10-23 | 16:38:02 / **1** | 24,696 + 24,572 | 否 |
| 10-24 | 02:02:21 / **1** | （仅 1 行） | 否 |
| 10-26 | 16:37:45 / **1** | 24,691 + 24,572 | 否 |
| 10-27 | 02:02:35 / **1** | 24,647 + 24,572 | 否 |

- **占比：12/12 天（100%）**；其中 **11 天是被「1 条」占掉的**。
- 台账 12 条 `index_daily` 提醒里，11 条正文都是「重写 **1** 条」，1 条是「重写 **2,062** 条」。
- **24.6k 批次进台账次数 = 0。**

### 4.3 最坏情况：已经发生过吗？

**「真·结构性损坏被吞」没有发生过；但「播报机会被吞」每天在发生。**

- 真实变化量级 80–128 行/天，其中没有一条是损坏（除 `csi_000102` 的错值，而错值本身是**前值**、修正后消失）。
- 因此目前被吞掉的是：①49,145 行噪声 ②~80 行正常修正。**没有真实故障因此漏报**。
- 但机制上**必然**：如果明天 21:03 出现一次真的整表损坏（比如某源返回空/错位），它会被 02:02 的「1 条」按死，**一条都不会发**。
- 反向漏洞也真实存在：**10-22 02:02 的 2,062 条噪声抢到了当天的唯一名额，发了一条 critical 假告警**——即"先占键者得播报"，噪声先到就是真告警，噪声后到就被吞。

### 4.4 ★4「按来源/数量级分键」是否必要

**必要，但 spec 现在的写法会反噬，必须调顺序。**

`alert-denoise-spec-20261027.md:262-266` 提的方案是：
```
key = history_overwrite:index_daily:{run_date}:{source}:{large|mid|small}
分级：index_backfill → notice；runner/partial 且 mid/large → critical；small → notice
```
按现网数据推演，这套规则上线第一天就会发一条 **24,572 行的 critical**（17:5x 批走 `runner` + `large`），因为**它把"数量大"当成"故障"**。而数量大恰恰是 NaN 误报造成的假象。

**建议的正确顺序与键设计**（只给建议，不实施）：

1. **先修比较器**（一行级）：`_values_changed` 里把 `NaN` 与 `None` 视为等价；`pct_change`/`amount` 用"按发布精度"的容差（pct 走绝对 0.005，而不是相对 1e-4）。修完基线立刻从 49,225/天 掉到 ~82/天。
2. **再分键**，且**严重度按"幅度"而不是"数量"**：
   - `critical`：任一批次里出现 `|Δclose|/close ≥ 1%` 的行 ≥5 条，**或**涉及 ≥10 个指数同时变（真损坏通常是面广幅度大）。
   - `notice/摘要`：占位修正、精度修正、计划内回填。
   - 键：`history_overwrite:index_daily:{run_date}:{source}:{critical|notice}:{size_bucket}`，24h 窗保留，不同桶互不占窗。
3. **兜底可见性**：当天无论是否 critical，都把「今日 index_daily 改写 N 行（真实 M 行 / 指数 K 个）」并进 23:25 摘要，保证"零台账"不再等于"零信息"。
4. **补一个盲区**：`index_daily` 审计只记 `changed`，**行消失/整段被删根本不会记录**（`_diff_index_history` 只遍历"采集回来的行"）。若担心上游像 10-14 那样被整段抹掉，需要补一条「行数快照对比」。

---

## 5. Q4 处置建议（只给建议，不实施）

### 5.1 定性结论对应的处置

- **缺陷（主导）→ 必须修比较器**：这是根因，改的是 3 行判断，不是数据。
  - 预期 X→Y：`index_daily` 审计行/天 **49,225 → ~82（−99.8%）**；21:03 批 **24,572 → 0**。
  - 证据用例：用云上 14 天数据回放进修好的比较器，断言 ①`nan↔-` 行 = 0 ②`csi_932365/20200102` 不再出现 ③`csi_000102` 的 ~48% 变化仍然被记录 ④10-22 的 2,062 条归零。
- **计划内回填 → 保持可见但降为提示**：占位→真实 OHLC 是设计行为，按日聚合成 1 条 notice 即可（spec ★4(b) 的 `index_backfill → notice` 方向正确，前提是先修比较器）。
- **不用动**的部分:17:50 拉 400 天 / 21:00 拉全历史的**调度节奏本身不用改**——它每天只多花两次全历史 UPSERT，代价可接受；真正的浪费是"记了 4.9 万行假账"，不是"多采了一遍"。

### 5.2 顺带必须上报的两个问题（不在本任务范围，但不修会继续错）

1. **`csi_000102` 张冠李戴（P1）**：`intraday_snapshot.py:1399` 把 `csi_000102` 映射成 `sh000102`（沪投资品），而配置 `config/indicators.yaml:301` 里它是创业板综 `sz399102`。后果：每交易日盘中该指数当日行是错标的、错点位（差 ~96%，6562 vs 3354）。
   - **根因**：该映射的生成规则写在 `intraday_snapshot.py:1390-1392` 注释里——「`csi_000xxx→sh`、`csi_399xxx→sz`」，例外清单只列了 `csi_000330(深证100)→sz399330`、`csi_000673(创业板50)→sz399673` 等，**`csi_000102`（创业板综，实为 399102）没进例外表**，被机械规则套成 `sh000102`。
   - **全量核对结果（已做，不是"可能还有"）**：`_SIGNAL_UNIVERSE_TENCENT_MAP` 共 **48 条**，逐条与 `indicators.yaml` 的 id→symbol 比对，**真错 1 条（就是本条）**；另 1 条 `csi_div: sh000922` 与 yaml `000922` 只是"腾讯码需市场前缀 / csindex 源用裸码"的口径差异，不算错；3 条港股 id 不在 indicators.yaml（`hk_cesg10/hk_hscci/hk_hsmpi`），另行核对。
   - **修法方向**：把该条改成 `sz399102`；再在生成规则里加一条"以 `indicators.yaml` 的 symbol 为准"的兜底/机检（防下次按规则批量生成再错）。
2. **spec A1 的三个数字需要更正**：行数 23,931/19,476 → 实测 **24,647/24,572**；抽样 `6562.71→3367.89` 的 3367.89 是开盘价，收盘是 **3354.83**；10-22 的 2,062 条被 spec 当作"真异常必须保住"的正样本，实测**也是 NaN 误报**，不能当反例用例。

### 5.3 「诊断前不降级」复核

已核（§2.6）：现状**没有**任何 index_daily 降级，只是被 dedup 吞。建议在修比较器之前**不要**先上 ★4 的分级——否则会拿一个假阈值去切真数据。

---

## 6. 口径与局限（诚实标注）

1. **时间覆盖只有 14 天，不是 30 天**：`history_overwrite_audit` 表 2026-10-14 才建（T1/T3 随 trades 根治上线），最早一行 `2026-10-14T16:37:49`。任务书说的「近 30 天」实际只能看到 14 天（12 天有数据，10 个交易日）。**结论的"稳定每日"是在 14 天窗口内成立的**，10-14 之前的历史无法从该表验证；但 `collect_log` 里 csindex 的「21:02 缺口补采」可追到 **2026-08-10**，佐证机制长期存在。
2. **10-14 之前到底有没有 4.3 万行/天，无法直接证实**（表不存在）。按代码推算应同样存在（比较器与采集路径都没变），但这是推断不是实测。
3. **`csi_000102` 的下游影响未展开**：只证实了盘中占位行是错标的；没有追查「这个错值有没有进入 signal_daily / trades / 前端展示的具体时段」。需要单独立项核实。
4. **没有做外部数据源交叉验证**：`csi_000330`/`csi_000102` 的"哪边对"是靠①配置定义 ②点位量级 ③前后收盘自洽 三条内部证据判定的，未拉第三方行情源比对（云上只读、禁止跑采集脚本）。
5. **`_SIGNAL_UNIVERSE_TENCENT_MAP` 48 条已全量核对**（与 `indicators.yaml` id→symbol 逐条比），真错只有 `csi_000102` 1 条；3 条港股 id 不在 indicators.yaml，未纳入比对。
6. **本报告未提交**（按任务书要求，主控后续派机械 agent 提交）。

---

## 7. 复现命令（全部只读）

```bash
# 1) 审计表总量与 NaN 误报占比
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'python3 - <<EOF
import sqlite3
con=sqlite3.connect("file:/home/ubuntu/code/trade-data/data/sentiment.db?mode=ro",uri=True)
print(con.execute("SELECT COUNT(*) FROM history_overwrite_audit WHERE src_table=?",("index_daily",)).fetchone())
print(con.execute("SELECT SUM(CASE WHEN REPLACE(after_val,\"nan\",\"-\")=before_val THEN 1 ELSE 0 END),COUNT(*) FROM history_overwrite_audit WHERE src_table=?",("index_daily",)).fetchone())
EOF'

# 2) 按日按小时聚合
#    SELECT substr(detected_at,1,10) d, substr(detected_at,12,2) h, COUNT(*), COUNT(DISTINCT index_id)
#    FROM history_overwrite_audit WHERE src_table='index_daily' GROUP BY d,h

# 3) 同一条记录被反复记（证明死循环）
#    SELECT detected_at,before_val,after_val FROM history_overwrite_audit
#    WHERE index_id='csi_932365' AND date='20200102' ORDER BY detected_at

# 4) 库里确实是 NULL（SQLite 把 NaN 存成 NULL）
#    SELECT open,typeof(open) FROM index_daily WHERE index_id='csi_932365' AND date='20200102'

# 5) 21:00 缺口补采的时间线
grep -nE "^  \[gap\]" /home/ubuntu/code/trade-data/data/logs/backfill_20261027_2100.log

# 6) 去重键被谁占用
python3 -c "import json;d=json.load(open('/home/ubuntu/code/trade-data/data/notify_dedup.json'));print({k:v for k,v in d.items() if k.startswith('history_overwrite:index_daily')})"
```

---

## 8. 附：代码锚点一览（供主控 §0 单点验收）

| 位置 | 作用 |
|---|---|
| `app/history_audit.py:234` | `if a is None or b is None: return True` —— **缺陷根点**（None vs NaN 判为变化） |
| `app/history_audit.py:43` | `_INDEX_DEDUP_WINDOW = 86400` |
| `app/history_audit.py:340-341` | dedup key `history_overwrite:{table}:{date}:{severity}` |
| `app/collector/runner.py:130` | `upsert_index_rows`（整段 UPSERT，唯一入口） |
| `app/collector/runner.py:142` | 调 `audit_index_rows_upsert` |
| `app/collector/runner.py:292` | indices 步 400 天窗口 |
| `app/collector/fetchers.py:792-795` | csindex 源强制 `start_date="20100101"` |
| `app/collector/index_backfill.py:863` | `backfill_history_gaps`（每日缺口检测） |
| `app/collector/index_backfill.py:934` | 缺口补采拉全历史 `"20100101"` |
| `app/collector/index_backfill.py:943` | 补采后 `upsert_index_rows` |
| `app/collector/intraday_snapshot.py:1399` | `csi_000102 → sh000102(沪投资品)` **错映射** |
| `app/collector/intraday_snapshot.py:1334-1385` | 盘中快照写当日占位行（次日被覆盖） |
| `config/indicators.yaml:301` | `csi_000102 = 创业板综 / sz399102` |
| `config/indicators.yaml:299` | `csi_000330 = 深证100 / sz399330` |
| `/etc/systemd/system/trade-update-all.timer` | `Mon..Sat 17:50` |
| `/etc/systemd/system/trade-backfill-evening.timer` | `16:35 / 21:00 / 02:00` |
| `scripts/backfill_metrics.sh:29` | 21:00 槽调 `index_backfill.main()` |
