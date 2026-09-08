# 交易记录数据断档监控根治方案（2026-09-08 设计文档）

> 设计目标：补上「自动测出交易记录断档/停更」的监控链路。用户原话定调：「我的问题就是。监控有缺口。真正的数据缺失并没有监控到。是我反馈问题你才排查到的。这个问题需要根治」「脚本只是辅助监控。核心是监控数据断档」。
> 测试基准：current baseline（v1.1.7，memory `test-baseline-v112-anchor`）。本任务纯监控设计，不涉及回测口径变更。
> 状态：**设计稿**。只读调研产出，未实施未挂载。

## 0. 事故背景（2026-09-07）

用户发现首页模拟回测弹窗 + lab 凯利回测交易记录只到 9/3，实际 9/4 有买入信号（应买 159023 养殖ETF万家 / 159173 农牧ETF南方 等）。
任务描述引用的根因链文档 `kelly-trades-stall-20260907.md` **在仓库中不存在（未落盘）**，本报告根因链 R1-R5 全部用现网代码+数据重新验证，证据可复核。

## 1. 根因链（全部代码+数据证据）

### R1：9/4 有 4 个买入信号，其中 3 个需要次日（9/7）价格定买入价

signal_daily（`data/sentiment.db`）9/4 买入信号：

```
20260904|csi_931946|buy_special
20260904|hk_cshklc|buy_aux          ← 前缀 hk_ 命中 universe_rules 排除类别（合法排除，见 §3.1）
20260904|sw_801010|buy_special
20260904|sw_801210|buy_special
```

`_resolve_etf` 映射（已修复产物 signal_kelly_trades.json 中 9/4 实际入账记录，当前基线数据）：

```
('20260904','csi_931946') → 159023 养殖ETF万家（buy_special）
('20260904','sw_801010')  → 159173 农牧ETF南方（buy_special）
('20260904','sw_801210')  → 562510 旅游ETF华夏（buy_special）
```

### R2：KELLY_BUY_NEXTDAY=1（v1.1.4 起默认）：买入价 = 信号日 accum_nav × 次日 open / 信号日 close

`scripts/signal_kelly_backtest.py` L561-569：

```python
if KELLY_BUY_NEXTDAY:
    sig_close = close_map.get(etf_code, {}).get(signal_date) if close_map else None
    nxt_open = open_map.get(etf_code, {}).get(_next_trading_day(signal_date, sorted_dates_list)) if open_map else None
    if sig_close is None or sig_close <= 0 or nxt_open is None or nxt_open <= 0:
        return None  # 缺原始价, 无法按次日开盘重定价
```

即：9/4 信号的入账，硬依赖 **159023/159173 的 9/7（下一交易日）accum_nav 与 open**。

### R3：9/7 盘后 backtest 重跑时，159023/159173 的 9/7 accum_nav 缺失

- 触发链：update_all.sh（launchd `com.trade.update-all` 17:50）→ `deploy.sh all` → `static-site/export.py` 7.9.2 步 **subprocess 调 signal_kelly_backtest.py** 生成 `signal_kelly_trades.json`（export.py L1204-1207；脚本默认输出 `static-site/data/`）。
- 9/7 晚间该两只 ETF 的 9/7 accum_nav 尚未入库（当前数据已补齐：`159023|20260907|1.1267`、`159173|20260907|0.9588`，故本次无法直接截获断档时刻快照，断档由 R4 的机制推论+产物证据钉死）。

### R4：`_batch_load_etf_prices` 按「有 accum_nav 的日期」建交易日序列 → `_next_trading_day` 返回 None → return None 静默丢弃

- L482-486：`SELECT etf_code, date, accum_nav, open, close FROM etf_daily WHERE etf_code IN (...) AND accum_nav IS NOT NULL`——**只有有 accum_nav 的日子才进序列**。
- L498-499：`sorted_dates[code] = sorted(nav_map[code].keys())`——159023 缺 9/7 时，其日期序列最后一天 = 9/4。
- L506-511：

```python
def _next_trading_day(signal_date, sorted_dates_list):
    """返回 signal_date 之后第一个交易日(次日开盘定价用)。无则返回 None。"""
    idx = bisect.bisect_right(sorted_dates_list, signal_date)
    if idx < len(sorted_dates_list):
        return sorted_dates_list[idx]
    return None
```

- 9/4 信号 → `bisect_right` 越界 → **返回 None** → L563 `.get(None)` = None → L564 `return None`。
- 主循环 L1202-1203：`if result is None: continue`——**静默跳过，无任何按信号粒度的落地记录**。
- 旁证：L1222/L1225 的 `skipped_no_price` 只 print 聚合总数（与「无ETF映射/无评级/未来不足」混在一起），不写文件、不产生监控事件、不区分「缺当日价」vs「缺次日 open」。

### R5：产物「时间戳新、内容停更」→ deploy 全链路绿灯

- 9/7 有 6 次 deploy：18:30 rc=0 ✓、19:30 rc=1（§23.12-1 任务状态机检 FAIL 阻断，与数据断档无关）、20:03 rc=0 ✓、20:39 rc=1（同上）、21:00/21:46 等。
- 9/7 22:35 check-data-gap（`data/logs/check_data_gap_launchd.log`）：

```
[check_data_gap] 检测完成: 1 条发现 (severe=0, warn=0, info=1)
[check_data_gap][info] ETF 累计净值缺价清单快照建档: 671 条缺价(最新库日 20260907)
```

exit=0。671 条为历史存量缺价（方案 D 存量不动），无当日新缺（22:35 时 9/7 nav 已补齐，断档窗口已过）。
- 9/7 update_all 内 check_data_integrity 全绿（update_all_20260907_1750.log L1590：`✓ signal_kelly_backtest: 16象限×5周期×10模式=800组合完整, all/A 总样本=1096440`）。
- 用户看到的：`signal_kelly_trades.json` 最新 signal_date=20260903，9/4 的 3 笔应入账交易缺失，无任何告警。

## 2. 现有监控为什么漏（逐项盘点）

| 现有检查 | 位置/挂载 | 检查内容 | 为什么漏 9/7 断档 |
|---|---|---|---|
| 数据缺口检测 22:35 | `scripts/check_data_gap_alerts.py`（launchd `com.trade.check-data-gap`，工作日 22:35） | 5 个 checker：北向断档/停更、accum_nav 窗口外 NULL 存量基线、accum_nav 当日新增缺价 diff、宽度族停更、涨停源对照 | **全部只查「采集层数据」，零个检查「回测产物/交易记录」**。9/7 跑时 9/7 nav 已补齐 → 无当日新缺 → 0 warn |
| check_signal_accum_nav_lag | `scripts/check_data_integrity.py` L892（deploy 链） | 只验 `MAX(date) WHERE accum_nav IS NOT NULL` vs `MAX(buy信号日)` 滞后 >1 交易日 | **MAX 口径对「个别 ETF 缺价」无感**：9/7 其他 ETF 有 nav → MAX=9/7，days=0 → OK。它就是 2026-09-04 P0（accum_nav 全 NULL）事故补的盲，没覆盖「个股级缺失」 |
| check_signal_kelly_backtest | `scripts/check_data_integrity.py` L546（deploy 链） | 象限×5周期×N模式组合完整 + 总样本非零 | 109 万+样本里少 3 笔不可见。9/4 停更三天但结构全完整 → OK |
| check_universe_alignment | `scripts/check_universe_alignment.py`（§23.6，deploy 同链） | 断言1-4：overview `_bt_in_universe` 对称/候选⊆白名单/trades 不含排除类别/排除类别体现 | **全是「反向一致性」（不该有的没有）+「结构完整性」，没有「正向覆盖」（该有的都有）**。9/4 信号被静默丢弃 = trades 少了 → 断言全绿 |
| backtest 内部 skipped 计数 | `scripts/signal_kelly_backtest.py` L1222/L1225 | `skipped_no_price` 聚合 print | 只 print 不落盘、不告警、无 ETF/日期粒度、不区分缺当日价 vs 缺次日 open |

**核心定论：现有全部机检 = 「反向一致性 + 结构完整性」两类；缺「正向覆盖（信号→交易 1:1 闭环）」与「产物停更新鲜度」。** 反例：9/7 断档时 backtest rc=0、deploy rc=0、22:35 数据缺口 0 warn、deploy 链检查全绿，但交易记录停更三天。

## 3. 监控方案设计（三检查器，组合根治）

### 3.1 检查器 A：覆盖检查（正向闭环）——「信号有但交易无」

**检查内容**：`signal_daily` 里最近 N 个交易日的每个入样买入信号（`BUY_SIGNALS`），在 `signal_kelly_trades.json` 中必须有对应 `signal_date` 的 trade；「信号有但交易无」→ 告警，名单逐条列出（index_id/date/对应ETF/预计丢弃原因）。

**必须排除的合法缺失（否则误报刷屏）**，判定复用两处现成逻辑，不新造：

1. **宇宙外信号**：命中 `config/universe_rules.yaml` `excluded_categories`（债类 `cgb_`、情绪 `s.`、全球商品利率 `g.`、港股行业 `hk_` 前缀）+ board_etf_map 无 key/空数组 → 跳过。**等价复用 `_resolve_etf` 的 `_iid_in_excluded_category` 剪枝（signal_kelly_backtest.py L293-297）+ overview.json 已注入的 `_bt_in_universe` 字段**（queries.py 同源，实际样例：`{'20260907 csi_399976 buy_aux, _bt_in_universe: True}`；`hk_cshklc` 9/4 buy_aux 不在 board_etf_map → False，属合法排除）。
2. **未来不足入账的信号**（今日信号需要明日 open，见 §3.2 容差逻辑）：`signal_date ≥ 最近完整交易日` 的信号天然要等次日，不列为缺失（容差窗口处理，见下）。
3. **信号评级缺失（`skipped_no_score`）**：`signal_stats` 无 10d score 的信号本来就不入账——但**这类要单独归一类 WARN 输出**（它代表上游评级数据缺失，值得人看一眼，只是不等同于 R1-R4 的数据断档）。

**当前基线上该检查能抓到的实测案例**（用修复后的数据验证判定逻辑成立）：若在断档时刻（9/7 22:35 前）运行，9/4 的 `csi_931946/sw_801010/sw_801210` 三信号 ∈ 宇宙、signal_date ≤ 容差日、但 trades 无对应记录 → 必命中 3 条 SEVERE。

**阈值初值（可配置，见 §4 规格）**：回溯窗口 N=5 个交易日；`signal_date ≤ 最近完整交易日 - 2`（即落后 ≥2 交易日仍无 trade）→ SEVERE；`= 最近完整交易日 - 1`（1 日落后，次日数据刚齐窗口）→ WARN。

### 3.2 检查器 B：新鲜度检查——「产物停更」

**检查内容**：`signal_kelly_trades.json`（及 `signal_kelly_backtest.json`）的**内容新鲜度**（`generated_at` + 最新 `signal_date`），对「产物更新了但内容是旧的」这个 9/7 断档核心形态做双保险：

- **B1 最新 signal_date 下限**：`trades.json` 最新 `signal_date` 应 ≥ 最近完整交易日 T 的前一个交易日（T-1）。理由（KELLY_BUY_NEXTDAY 次日开盘口径）：T 日信号入账需要 T+1 日 open，T 日盘后不可能入账；**T-1 日信号在 T 日盘后已应有次日（T 日）open 可定价，必须入账**。9/7 断档时刻：最近完整交易日=9/7（周一），T-1=9/4（周五），产物最新 signal_date=9/3 → **落后 2 个交易日 → SEVERE**。9/7 晚正常产物最新应=9/4（9/7 信号待 9/8 定价），落后 0 → OK（不误报）。
- **B2 generated_at / 文件 mtime 下限**：产物应 ≤ 2 个自然日内生成（防 backtest 完全没跑/跑挂但仍保留旧产物——「时间戳新内容旧」由 B1 抓，「时间戳也旧」由 B2 抓）。
- **B3 覆盖源新鲜度的前置**（可选增强）：`etf_daily.accum_nav` 最新日 vs 产物最新 signal_date 的差（若 nav 已到 9/7 但 trades 只到 9/3 → 直接指向 R4 类断档；若 nav 本身落后 → 与 check_signal_accum_nav_lag 互补，但后者只查 MAX 不查覆盖率，此处补「覆盖率缺口前 3 名 ETF 清单」）。

**日历依赖**：`app.calendar.trading_days_between`（app/calendar.py L87）取最近交易日序列，周末/节假日不误报。

### 3.3 检查器 C：产物生成检查——「backtest 是否成功跑」

**检查内容**：deploy/backtest 链路的运行证据，防「任务没跑 or 跑挂了但旧产物还在」：

- **C1 日志证据**：最近一次 `export.py`/`signal_kelly_backtest.py` 运行日志存在且含成功标记（`✓ 输出: ... signal_kelly_trades.json`，signal_kelly_backtest.py L1614-1615），或 `trades.json` mtime 在最近 deploy 之后（等效证据，无需解析日志，推荐 mtime 方案为首选实现——见 §4 规格）。
- **C2 deploy 阻断面**：deploy.sh 退出码 rc≠0（如 9/7 19:30/20:39 的 §23.12-1 阻断）→ 产物可能没更新 → 告警。**现状：update_all 侧已有「耗时超 1h」severe 告警（9/7 20:41 实测发过），但那是「update_all 整体失败」的宽告警，没有定位到「kelly 产物可能停更」**——检查器 C 把它变成精确告警，两处并存不冲突。
- **C3 backtest 自身统计**（低成本增强，推荐）：在 `signal_kelly_backtest.py` L1225 的 print 前，把 `skipped_no_price` 明细按「缺当日价 / 缺次日 open / 未来不足 hold_days」细分并落一个 JSON（如 `data/signal_kelly_skip_stats.json`），检查器 A/B 直接消费。**可选**：若不想动回测脚本（§23.7 冻结契约要用户确认），A 检查器在外部独立等价复算也可以，见 §4 对比。

### 3.4 挂载点建议

| 选项 | 位置 | 理由 | 推荐度 |
|---|---|---|---|
| **主挂载** | **并入现有 `check_data_gap_alerts.py`**（22:35 定时，launchd `com.trade.check-data-gap`） | ①已有的告警出口（severe→邮件+latest.md，dedup state 机制照用）②22:35 时序天然正确：当晚所有采集+backtest 已完成，是「日终完整性」的最后一班岗 ③不加新定时器（§14 盘后时段已排满，新增槽位有撞车风险） | **推荐** |
| deploy 硬闸 | `check_data_integrity.py` 新增鲜度/覆盖机检（deploy 链 FAIL 阻断） | 防劣质产物上线（§22 一致性精神），但 deploy 前 trades.json 可能因次日 open 未生成而「合法停更」，需小心设计容差避免误拦（DANGER：deploy 阻断面误伤上线） | 部分——**检查器 B/C 可挂，覆盖检查 A 不挂**（A 在 deploy 时点可能因「当日信号未入账」天然不全，见容差） |
| 独立定时 | 新增 launchd 22:40 | 22:35 已有任务、pmset 唤醒时段依赖同一批，新增独立槽可避免争用，但要新增 plist+巡检注册（L45 教训：定时挂载缺一不算 done） | 备选（若要 A 级隔离再启用） |

**结论：检查器 A/B/C 全部放进 `check_data_gap_alerts.py` 作为第 6/7/8 个 checker，22:35 跑、同 dedup/告警出口；deploy 链挂 B2/B3 与 C2 的轻量版（部署前产物新鲜度硬闸，容差按「当日盘中 deploy 允许 T-1 新鲜度」设计）。**

### 3.5 告警出口

- SEVERE → 现有 `[severe-mirror] 邮件 + latest.md` 链路（notify.py 同款，与 9/7 20:41「update_all 严重告警」同一通道）。
- WARN → 普通告警邮件。
- 信息格式必须含定位信息：日期清单 + index_id + 信号类型 + 对应 ETF 代码/名称 + 预计丢弃原因（「缺次日 accum_nav: 159023」这类人话），方便用户一眼定位（§23.9 三档互证精神，不断档时零打扰）。

### 3.6 防误报与自愈设计

- **同 key 每自然日去重**：复用 `data/alerts/data_gap_alert_state.json`（原子写 tmp+replace，与现 5 个 checker 一致）。
- **恢复通知**：问题消失（如 9/8 05:10 重跑后 9/4 三笔入账，A 检查恢复）→ 发恢复邮件（沿用 now-absent 判定，参照 `data_gap:width_gap` 恢复先例）。
- **QDII 跨境 T+1 净值时滞豁免**：159xxx A 股 ETF 不豁免；QDII（如 513xxx）缺 T 日 nav 降 info 不告警（与 checker5 现有豁免同款逻辑）。
- **非交易日**：脚本内交易日闸门跳过（与现有 check_data_gap_alerts.sh 一致）；周末 B1 使用「最近完整交易日」由交易日历算，天然不误报。

## 4. 实现规格（给 implementer 的可执行规格）

### 4.1 检查器 A（新 checker：`data_gap:kelly_coverage`）

- **代码位置**：`scripts/check_data_gap_alerts.py` 新增函数 `check_kelly_coverage(repo)`，并入 `run_all` checker 列表（该文件 L60-70 checkers 表处）。
- **输入依赖**：
  - `{repo}/data/sentiment.db`：`signal_daily`（date/index_id/signal），取最近 N 交易日 buy 系信号：`SELECT date,index_id,signal FROM signal_daily WHERE date >= ? AND signal IN ('buy','buy_aux','buy_special','buy_backup')`（N 由 `trade_days_back` 配置，初值 5，用 `app.calendar.trading_days_between` 往前推）。
  - `{repo}/data/board_etf_map.json`：宇宙判定（key 存在 + 非空 + 有 track_score；排除类别由 universe_rules.yaml 载入，复用 `_iid_in_excluded_category` 同款 match 逻辑——**建议直接从 universe_rules.yaml 读以免双份维护**）。
  - `{repo}/static-site/data/signal_kelly_trades.json`：trades 全集（72MB，读取用已有 `--trades` 路径解析先例，check_universe_alignment.py L237-241 同款；若嫌大可用 `signal_kelly_trades_parts/` 或只解析 quadrants 扫描 signal_date 集合）。
  - 可选 `{repo}/static-site/data/overview.json`：`_bt_in_universe`（若实现走「读标记」而非复算宇宙，则与 §23.6 ③ 1:1 遵从同精神）。
- **判定**：对每个候选信号 `(date,iid,sig)`：宇宙外 → 跳过；`signal_date > T-1`（T=最近完整交易日）→ 容差跳过；否则在 trades 最新 signal_date 集合中查 → 无 → finding。
- **级别**：落后 ≥2 交易日 SEVERE；=1 交易日 WARN（注意：若本期所有缺失都集中在「=T-1 且缺次日价」——9/8 上午首次运行场景——降 WARN 防首日吓人，连续 2 日未恢复升级）。**配置项**：`kelly_coverage: {trade_days_back: 5, severe_back_days: 2, warn_back_days: 1}`。
- **复现命令**（开发验证）：`.venv/bin/python scripts/check_data_gap_alerts.py --repo /Users/linhuichen/code/trade-data --dry-run`（dry-run 零副作用，先例同文件 --self-test）。

### 4.2 检查器 B（新 checker：`data_gap:kelly_stale`）

- **输入依赖**：trades.json 的 `generated_at`（顶层字段）+ quadrants 扫描最新 signal_date；`static-site/data/signal_kelly_backtest.json` 同查；`{repo}/data/etf_national_team.db`（etf_daily MAX 日，用于 B3 覆盖率前 3 名缺 ETF：`SELECT etf_code, MAX(date) FROM etf_daily WHERE date >= ? AND accum_nav IS NOT NULL GROUP BY etf_code ORDER BY MAX(date) ASC LIMIT 3` 与 trades 最新 signal_date 交叉）。
- **判定**：
  - B1：`latest_signal_date < T_prev`（T=最近完整交易日）→ SEVERE（9/7 场景=9/3 < 9/4 → 命中）；`== T_prev` → 当前正常。
  - B2：`generated_at`（或 mtime）早于 `now - 48h` → SEVERE（周末自动放宽：用交易日历取最后一个数据日而非自然日）。
  - B3：nav 最新日 ≥ T 但 trades 最新 signal_date ≤ T-2 → SEVERE + 输出「最新 nav 也缺的 ETF 前 3 名」。
- **复现命令**同上 dry-run。

### 4.3 检查器 C（`data_gap:kelly_backtest_fail`）

- **C1 实现首选（不解析日志）**：比较 trades.json 的 mtime 与最近一次成功 deploy 的`$REPO/static-site/data/.deploy_marker`（若无 marker 文件可新增，或复用 `deploy_YYYYMMDD_HHMM.log` 的 mtime 判断——deploy 链每次结束写一行 `deploy.sh 结束 ... 退出码=0`，取最新一份 mtime 与 rc）。判定：`deploy mtime` 距今 >2 天 OR 最新 deploy rc≠0 且之后无成功 deploy → WARN。
- **C2 简化版**：直接扫最新 `deploy_*.log` 尾部 rc 行（`tail -c 2000`），`退出码=0` 缺失 → WARN（定位语：「最近 deploy 未知/失败，kelly 产物可能未刷新」）。
- **输入依赖**：`{repo}/data/logs/deploy_*.log`、trades.json mtime。无 DB 依赖。
- **复现命令**：dry-run 同前。

### 4.4 回测侧 skip 统计落盘（可选增强，需 §23.7 用户确认后实施）

- `scripts/signal_kelly_backtest.py` L1222-1225：把 `skipped_no_price` 细分（缺当日价/缺次日 open/未来不足 hold 天数/伪跳空剔除）并按 (date|etf_code) 粒度落 `data/signal_kelly_skip_stats.json`（含 `asof`）。
- 检查器 A 直接消费该文件，命中时能给出精确丢弃原因（如 `20260904|159023|needs_nxt_open_missing`）。
- **取舍**：动回测脚本属「已发布功能行为」相邻面（不改语义只加日志，纯增量），但按 §23.7 仍需用户确认；**不动它 A 也能跑**（外部等价判定：nav 有当日价 + 缺次日价 = 判断为缺次日 open），只是原因粒度粗。建议先实施 A/B/C 纯监控层（对生产零副作用），skip 落盘作为 add-on 一并问用户。

### 4.5 与 §23.6/§22/§23.12-1 的关系（合规性）

- 覆盖检查复用 `universe_rules.yaml` 判定 → 宇宙规则变更时本检查自动跟随（§23.6 ⑤ 变更联动链上加一步：改规则 → 重跑 board_etf_map → 重跑回测 → 重跑 export → 对称校验 → **本检查器 dry-run 验证**）。
- 部署链路：新 checker 进 `check_data_gap_alerts.py` 后，更新 README 对应段（§21 公示同精神：算法/监控口径公示）。
- 排查注册：新增检查的告警 key 进 `schedule_monitor` 可观测范围内（漏跑/超时巡检，参照现 5 checker 待遇）。
- 本任务不涉及 TASKS 状态（无新编号任务，或按主控后续派单编号登记）。

## 5. 维度清单完成度

| 维度 | 状态 |
|---|---|
| 根因链 R1-R5 证据 | ✅ 代码行号 + 现网数据 + 9/7 日志三重证据 |
| 现有监控逐项盘点 | ✅ 5 项（22:35 缺口检测/lag 检查/结构检查/宇宙对齐/skip 计数）why 漏 逐项钉死 |
| 三检查器设计 | ✅ A 覆盖/B 鲜度/C 生成 + 容差 + 防误报 |
| 挂载点对比 | ✅ 3 方案表 + 推荐（并入 22:35） |
| 告警出口 | ✅ 复用 notify severe 链路 |
| 实现规格 | ✅ 脚本/调用点/输入依赖/阈值初值/复现命令 |
| 防前视 | ✅ 不涉及（监控检查全部用「截至当前」数据，无预测） |
| 诚实标注 | ✅ 159023/159173 断档时刻快照已不可截获（数据已补齐），R3 为机制推论+产物证据钉死 |

## 6. 关键证据索引（供主控/grep 验收）

| 证据点 | 位置 |
|---|---|
| 9/4 信号明细 + 9/7 信号明细 | `data/sentiment.db` signal_daily SQL（见 §1 R1） |
| 9/4 trades 实入账（159023/159173/562510） | `static-site/data/signal_kelly_trades.json` quadrants 扫描（signal_date=20260904） |
| `_batch_load_etf_prices` 过滤 + 日期序列 | scripts/signal_kelly_backtest.py L482-486/L498-499 |
| `_next_trading_day` 返回 None | scripts/signal_kelly_backtest.py L506-511 |
| return None 静默丢弃 | scripts/signal_kelly_backtest.py L563-565 + L1202-1203 |
| skipped 只 print | scripts/signal_kelly_backtest.py L1222/L1225 |
| check_signal_accum_nav_lag MAX 口径 | scripts/check_data_integrity.py L892-946 |
| check_signal_kelly_backtest 结构口径 | scripts/check_data_integrity.py L546-610 |
| check_universe_alignment 反向断言 | scripts/check_universe_alignment.py（assertion1-4） |
| 9/7 22:35 缺口检测 exit=0 | data/logs/check_data_gap_launchd.log（severe=0,warn=0） |
| 9/7 update_all 全绿 | data/logs/update_all_20260907_1750.log L1590-1604 |
| 9/7 deploy rc=1 两次 | data/logs/deploy_20260907_1930/2039.log（§23.12-1 阻断） |
| update_all 超时 severe 告警已发 | data/logs/update_all_launchd.err（9/7 20:41 耗时171分钟） |
| launchd 22:35 挂载 | launchd/com.trade.check-data-gap.plist |
| 产物刷新链 | launchd/com.trade.update-all.plist → update_all.sh → deploy.sh → export.py L1204-1207 → signal_kelly_backtest.py |
| hk_cshklc 合法排除 | config/universe_rules.yaml excluded_categories（hk_ 前缀）+ board_etf_map 无 key |
| `_bt_in_universe` 已注入 | static-site/data/overview.json signals_today 样例（csi_399976=True / cgb_idx=False） |

## 7. 复现与验证（实施后自测）

1. **two-way 自测**（`--self-test` 同款）：临时注入「159023 缺 9/7 nav」场景 → A 检查器必命中 csi_931946/sw_801010 缺失且级别 SEVERE；注入「全部正常」→ 0 finding。
2. **断档回放验证**：在修复前产物快照（9/7 20:43 之前任一 deploy 时刻的 trades.json，可从 git/R2 历史取）上跑 dry-run → 必命中 9/4 三笔缺失。
3. **正常日零误报验证**：9/8（修复后）产物 + 当前 DB 跑 dry-run → 0 finding（9/7 信号因容差不报，hk_cshklc 因宇宙外不报）。
4. **首日 WARN 验证**：模拟 9/8 上午（最新完整交易日=9/7 但 nav 已齐）→ 9/4 缺失应为 SEVERE（落后 2 交易日），9/7 信号不报。
5. **上线三步**（§22）：改 check_data_gap_alerts.py → 与 launchd 不变（脚本路径不变无需重载 plist，但需 `launchctl kickstart -k gui/$UID/com.trade.check-data-gap` 验证新代码生效一次）→ README 数据缺口段同步新 3 item（L445 段）。
