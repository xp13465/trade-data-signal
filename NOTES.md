# 调研与迭代笔记

> 本文件记录项目演进过程中的调研结论、未解决缺口、关键决策与修复历史，供后续迭代参考。
> 状态/需求见 [REQUIREMENTS.md](REQUIREMENTS.md)，用法见 [HELP.md](HELP.md)。
> 最近更新：2026-07-08（情绪Tab扩充方案 + §9 期货机构净多空持仓方案）

---

## 1. 当前项目状态（2026-07-06）

- 看板运行中：`http://localhost:8000`（绑定 `0.0.0.0`，局域网可访问 `http://192.168.31.207:8000`）
- 指标：33 项 metrics（删 2 个错配的 score 条目）+ 13 指数 + 3 板块；**29 启用 / 6 禁用**
- 数据：§6 跨市场分 **2735 天**、§4 情绪分 7 天（近期）、买卖点 2425 个、派生封板率 16 天
- 全链路通：采集 → 计算（含派生公式）→ API → 前端 5 tab → launchd 定时（待 `launchctl load`）
- 采集层：akshare（sina 源为主）+ direct 直爬（em_get 防封）+ tencent（换手率）

---

## 2. a-stock-data 仓库评估

仓库：`simonlin1212/a-stock-data`（已克隆到 `./a-stock-data/`，是 Claude Code skill 形态，SKILL.md 嵌 40 个 Python 函数，非数据库）。V3.0 不用 akshare，直连 mootdx/腾讯/东财(em_get防封)/同花顺/新浪/巨潮。免费无 key（仅 iwencai NL 搜索需 key）。

### 对 7 个缺口的评估

| # | 缺口 | 能否补 | 说明 |
|---|---|---|---|
| ① | 涨停板池 1 年历史 | ❌ | `em_zt_pool` 与 akshare 同源（push2ex），东财服务端只保留近 2 周 |
| ② | 东财反爬 | ⚠️ 部分 | `em_get()` 1s 限流+重试能缓解速率型封锁；但 push2 clist 单请求就 RemoteDisconnected，更像硬封 |
| ③ | 美股三大指数 | ❌ | 纯 A 股工具包，不覆盖美股 |
| ④ | 板块数据 | ⚠️ 部分 | `industry_comparison()` 给行业涨跌幅+涨跌家数，但走同一个被封的 push2 clist 端点；行业资金流无端点 |
| ⑤ | 北向 2024 后 | ❌ | SKILL 作者承认「2024-08 后净买额 NaN，上游断供」，只能从今天往前自缓存 |
| ⑥ | 涨跌家数历史 | ❌ | 无全市场汇总端点，mootdx 只能按 symbol 枚举 |
| ⑦ | 换手率/乐咕/东财情绪 | ⚠️ 1/3 | **换手率已补**（`tencent_quote` turnover_pct）；乐咕/东财情绪无 |

### 已集成的部分

1. **`em_get()` 防封层**（抄自 SKILL.md 302-334 行）→ `app/collector/base.py`
   - 全局 Session + 1s 串行限流 + 0.1-0.5s 抖动 + HTTPAdapter 指数退避重试（429/5xx）
   - 403 不重试（风控信号）
   - **效果**：`a_fund_main`（主力资金流，push2his 端点）从间歇失败变稳定拿到 120 行历史
2. **`tencent_quote()` 换手率**（抄自 SKILL.md 400-453 行）→ `app/collector/tencent.py`
   - `fetch_index_turnover(code='000001')` 取上证指数换手率
   - 启用 `a_turnover_rate` 指标（之前禁用）
3. `direct.py` 的 `fetch_market_fund_flow` 改用 `em_get`（替代裸 direct_session）

### 集成方式

把 SKILL.md 里的 Python 函数直接复制进 `app/collector/`，不当 skill 调用。函数是无状态纯函数（除 `EM_SESSION`/`_em_last_call` 模块级全局），放进 FastAPI 没问题。注意：em_get 串行锁是进程内的，多 worker 部署会绕过限流（当前单 worker 无影响）。

---

## 3. 未解决缺口与未来路径

| 缺口 | 现状 | 未来路径 |
|---|---|---|
| 涨停板池历史 | 东财 push2ex 只 2 周 | Tushare Pro 付费 / Wind / 接受 §4 从今天积累（4 个月稳定） |
| 美股三大指数 | 禁用 | yfinance（需测 Clash 代理）/ stooq 直爬 / 新浪美股 |
| 北向资金 2024+ | akshare `stock_hsgt_hist_em` 返 2024-08 后行但全 NaN（东财停实时披露） | 已过滤 NaN 冻结在 20240816；雪球有盘后数据但需另写爬虫，未做 |
| 涨跌家数历史 | sina spot 只当日 | 无解；或 mootdx 枚举全 A（慢，需维护代码表） |
| 板块涨跌幅 | 东财反爬 | 抄 `industry_comparison()` 用 em_get 试（未必解硬封） |
| 行业资金流 | 无端点 | Tushare / 东财板块资金流 API 另找 |
| 乐咕活跃度 | legulegu 不稳定 | 放弃，或找替代情绪指数 |
| 东财情绪指数 | 无源 | 放弃 |

---

## 4. 关键决策与修复历史

| 日期 | 决策/修复 | 原因 |
|---|---|---|
| 07-05 | §4 min_periods=10（非20） | 涨停板池只 2 周，放宽让近期 §4 可算，随每日积累稳定 |
| 07-05 | §4 加 ≥3 分项过滤 | 避免仅北向单分项误导（删了 2245 天 north-only 历史假数据） |
| 07-05 | 买卖点改 RSI 主信号 | cross 评分与价格不同步（拉指数不拉个股），原「冰点买」错位在价格高点 |
| 07-05 | gold 方向 → negative | 避险涨=冷，原 neutral 导致 cross 与价格负相关 |
| 07-05 | range 参数修复（rng→range） | FastAPI 按名匹配，前端发 `range` 后端收 `rng` 全用默认 1y |
| 07-05 | uvicorn --host 0.0.0.0 | 局域网访问（原 127.0.0.1 只本机） |
| 07-05 | trust_env=False 全局 | Clash 代理(7890) 拦截东财，绕过直连国内源 |
| 07-05 | sina 源替代东财 clist | 东财 push2 clist 硬反爬（RemoteDisconnected），sina 可用 |
| 07-06 | 集成 em_get 防封层 | 主力资金流间歇失败，em_get 限流+重试后稳定 |
| 07-06 | 集成 tencent 换手率 | sina 无换手率列，腾讯 qt.gtimg.cn 有 turnover_pct |
| 07-06 | collect_series 过滤 NaN | 北向/QVIX 源返 NaN 被当值入库（清掉 3679 null 行），NaN 跳过不入库 |
| 07-06 | 两融加 NEEDS_DATE_RANGE(2000天)+scale 1e-8 | stock_margin_sse 无参只返 2015 老数据；融资余额单位是元，原未缩放飞存 1.5e12 |
| 07-06 | 新建 compute/derived.py | 封板率 type=derived+formula 但无计算模块，补 eval 公式（1 - 炸板率）入 daily_metric |
| 07-06 | 删 a_sentiment_score/cross_market_score 出 metrics | 它们是 score_daily 综合分，错配在 metrics 导致 /api/a-stock 取空、/api/metrics 误列 |
| 07-06 | upsert 加 WHERE source!='manual' | 每日采集用 akshare 无条件覆盖手动补录，manual 补录实际失效（核心 bug） |
| 07-06 | /api/manual 校验 metric_id+date + /api/manual/check | 原无校验，'invalid' 日期/指标写脏数据；补 check 端点供前端覆盖确认 |
| 07-06 | /api/index 未知→404, range 非法→400 | 原都返 200，前端无法区分错误（依赖 range_dep） |
| 07-06 | 前端日期去 .replace + 覆盖确认 + favicon | date input 需 yyyy-MM-dd；m-submit 调 check 确认；favicon 路由 204 |
| 07-06 | **A1: collect_snapshot 拒绝历史日期回填（纯当日快照）** | `stock_zh_a_spot` 等「纯当日快照」无 date 参数，源永远返回今天数据；手动跑 `runner 20260703` 会把今天的盘中值盖章成历史日期 → 覆盖正确历史值（20260703 up 3803→1856 根因）。修复：func 不在 DATE_PARAM_FUNCS/DATE_RANGE_FUNCS 时，若 `date != last_trading_day()` 则跳过（zt_pool 带日期参数近 2 周可回填，不受影响） |
| 07-06 | **A2: collect_series 加 drop_zero 按指标过滤 0.0** | `index_option_1000index_qvix` 源返 34 行 close=0.0（占位/解析缺失，非 NaN），`v!=v` 只判 NaN 漏过 → 入库 0.0。QVIX 真值 15-30 不可能 0，但资金流/IPO 数等可为 0，故用 yaml `drop_zero: true` 按指标开关（仅 QVIX 类），不误伤其他指标 |
| 07-06 | **A3: 北向资金前端标注停更** | `a_fund_north` 已过滤 NaN（数据冻结在 20240816），1 年期窗口内为空 → 前端空白，用户分不清停更还是故障。修复：(1) `config/indicators.yaml` `a_fund_north.name` 加「(2024年8月停更)」——全局生效（看板图例 / 手动补录下拉 / 未来概览 KPI 都带标注）；(2) `web/app.js` `mkCard`/`lineChart` 加可选 `hint` 参数，A股看板「资金面」组渲染时传橙色提示条「数据源自 2024 年 8 月起停更（东财停止实时披露），冻结在 2024-08-16，1 年期窗口内为空属正常」——比图例标注更醒目 |
| 07-06 | **S1: scheduler 跨年刷新 trade_dates**（A1 遗留） | A1 守卫依赖 `last_trading_day()` → `data/trade_dates.txt` 缓存（含 2026 全年），跨年时缓存缺新年日期 → `is_trading_day('20270104')=False` 误跳过采集 + `last_trading_day()` 停在旧年末日致 collect_snapshot 守卫误 skip。修复：(1) `app/scheduler.py` `run()` 开头（is_trading_day 闸门前）调 `refresh_trade_dates()`，try/except 兜底失败沿用旧缓存；(2) `app/calendar.py` `refresh_trade_dates()` 重写为安全刷新——先拉新数据成功才原子覆盖（写 `.tmp` 再 `replace`），失败保留旧缓存（旧实现 `unlink` 删盘后拉取，网络抖动会丢缓存）。跨年模拟验证通过（stale 缓存 max=20261231 → refresh 后 is_trading_day/last_trading_day 正确返 20270104；akshare 抛异常时缓存文件原样保留） |
| 07-09 | **HomeSignalGrid: 首页卡片按日分组，后端取"最近9个日期"(=9行)** | 前端按 date 分组(一天一行)，若 `LIMIT 9` 按记录截断会 9 条挤少数几天(实测 signals 9条/3天)；改子查询 `SELECT DISTINCT date ... LIMIT 9` 再 `WHERE date IN(...)` 取全部记录，保证9天=9行 |
| 07-09 | **HomeSignalGrid: 单日信号超4折叠** | 某日多达16-19个信号 wrap 成多行撑高卡片。每日期最多显示前4个(4列一行 `_SIG_PER_DAY=4`)，多余塞 `.sig-items-extra(hidden)`+"+X"徽章点击展开(`_bindSignalGridMore`)；`.signal-grid max-height:300px` 兜底滚动 |
| 07-09 | **HomeSignalGrid: 周期参数** | freeze 取近120日、signal 取近15交易日(25自然日)范围内的最近9个日期；9行实测不突破卡片 min-height 350px(每行~30px)。今日高亮用 r.date 基准(非 fmtDate 的浏览器今日，避免周末漂移) |

### 4.1 TASK-A1 根因详述：上涨家数 20260703 回归（3803→1856）

**现象**：`a_width_up_count` 20260703 从 3803（与雪球 3804 一致）变为 1856（-51%），source=akshare。

**根因**（collect_log 铁证）：
- 2026-07-05 19:24（周六）：spot 返回 07-03（周五）收盘数据 → up=3803, down=1628, amount=32046.97 ✅ 正确
- 2026-07-06 13:10（周一盘中，A 股 15:00 收盘）：手动跑 `python -m app.collector.runner 20260703` 回填。runner 把 `date=20260703` 传给 `collect_snapshot`，但 `stock_zh_a_spot` 是纯当日快照（无 date 参数），源仍返回 07-06 盘中数据（up=1856），却盖章成 20260703 → 覆盖正确历史值 ❌
- 同批次 `a_width_down_count`（1628→3524）和 `a_amount`（32046.97→23303.91）也被同一机制污染

**排除的假设**：「1856≈沪市主板量，只回部分市场」❌ —— 实测 `stock_zh_a_spot`(sina) 返回 5526 行=全市场（up+down+flat=5526），count_up transform 逻辑正确。1856 只是 07-06 盘中 up 数。

**修复**：
1. `app/collector/fetchers.py` `collect_snapshot` 加守卫：func 不在 `DATE_PARAM_FUNCS`/`DATE_RANGE_FUNCS`（即纯当日快照）且 `date != last_trading_day()` → 跳过，返回 `skip backfill: ...`。zt_pool 等带日期参数的快照近 2 周仍可回填。
2. SQL 恢复 20260703 三个被污染值（取 07-05 19:24 正确采集值）：up=3803、down=1628、amount=32046.97034002。

**遗留 / 风险**：
- 20260706 的三个 spot 值（up=1788 等）是 13:36 盘中所采，非收盘值。scheduler 15:33 跑时会以 `last_trading_day()=20260706` 重新采集收盘值覆盖（守卫允许，因 date==ltd）。盘中手动采集属使用习惯问题，非脚本 bug。
- 守卫依赖 `last_trading_day()` 准确。trade_dates 缓存（`data/trade_dates.txt`）目前含 2026 全年交易日，年内稳健；**跨年时需刷新**（`refresh_trade_dates()` 当前无自动调用点，scheduler 未调用）。建议后续在 scheduler 或定期任务里加 `refresh_trade_dates()`。
- 正本清源：`stock_zh_a_spot` 无历史，宽度指标长期靠 D1（本地日线）回算更可靠（见 TASK-D2）。

### 4.2 TASK-A2 根因详述：a_qvix_1000 0.0 异常值（28→34 条）

**现象**：`a_qvix_1000` 有 34 条值为 0.0（QVIX 正常 15-30，0.0 不可能）。回归报告（07-06）记 28 条 / 135 总条，是当时中间态；实际清查时为 34 条 / 841 总条（差异是后续又采了若干天）。`a_qvix_300` 无 0.0（1567 条全正常，范围 12.87-45.86）。

**根因**（源数据铁证）：
- akshare `index_option_1000index_qvix()` 返回 2755 行历史，其中 1914 行 close=NaN（早期数据，已被 `collect_series` 的 `if v != v` 过滤），但另有 **34 行 close=0.0（字面 float 0，不是 NaN）**，分布在 20241025 ~ 20260529。
- DB 的 34 个 0.0 日期与源的 34 个 0.0 日期**一一对应、无多余**（DB zeros ⊂ src zeros，且数量相等），证明污染纯来自源，无其他路径。
- 源 0.0 有两种形态，均为源占位/解析缺失：
  1. **整行 NaN + close=0.0**（open/high/low 全 NaN，close 却 0.0）——源对该日无数据但用 0 占位。如 20250224、20250721、20250924/25/26、20260415/21/27/29 等。
  2. **OHLC 有效但 close=0.0**（源数据错误）——如 20241025: open=33.65/high=34.25/low=32.79/close=0.0（close 不可能低于 low）。源端 bug，非脚本问题。
- `collect_series` 的 `if v != v` 只判 NaN，0.0 不是 NaN 所以漏过 → 入库。
- 附带：1000 源自 20260313（值 17.83）后只返 0.0/NaN 占位至 20260626，所以 DB 最新非空值停在 20260313（看板显示「最新 0.0」即此，已随清理一并消除）。300 源仍正常到 20260626。

**为什么不全量 `if v == 0: continue`**：`a_fund_north`（北向净流入）、`a_fund_main`（主力净流入）、`ipo_count`（IPO 数）、`a_width_dt_count`（跌停数）等指标 0 是合法真值，全量过滤会误杀。QVIX 是年化波动率指数，下限约 10-15，真 0 不可能，所以只对 QVIX 类过滤安全。

**修复**：
1. `config/indicators.yaml` 给 `a_qvix_300`、`a_qvix_1000` 加 `drop_zero: true`（300 防御性加上，当前无 0.0 但源可能回归）；yaml 头注释新增 `drop_zero` 字段说明。
2. `app/collector/fetchers.py` `collect_series` 在 NaN 过滤后加 `if drop_zero and v == 0: continue`（`drop_zero = bool(metric.get("drop_zero"))`，按指标开关，不误伤其他指标）。
3. SQL 清已入库：`DELETE FROM daily_metric WHERE metric_id='a_qvix_1000' AND value=0.0` 删 34 行；`a_qvix_300` 0 行（确认无 0.0）。

**验收**：
- DB：`a_qvix_1000` 807 条全非 0（min=11.76, max=43.57），`a_qvix_300` 1567 条全非 0。✅
- 采集过滤：复跑 `collect_series(a_qvix_1000)` 返回 807 行 0 个 0.0（之前 841=807+34）；`a_qvix_300` 1567 行 0 个 0.0。✅
- API：`/api/a-stock?range=all` 两个 QVIX 指标 `data` 数组均无 0.0 点。✅
- 不误伤：`a_fund_north`、`ipo_count` 等无 `drop_zero` 标记，合法 0 不受影响。✅

**遗留 / 风险**：
- `a_qvix_1000` 源自 20260313 后停返有效数据（与回归报告 BUG-010/015「QVIX 源滞后停在 6-26」一致），属源问题非脚本 bug；本次只保证不再入库 0.0 占位。后续若源恢复，`collect_series` 会正常采到新值。
- `drop_zero` 是按指标开关，新增「0 不可能是真值」的指标时记得在 yaml 加 `drop_zero: true`。

### 4.3 TASK-D1 全 A 股日线本地拉取（回溯基础设施）

**目标**：拉全 A 股（~5500 只）10 年日线，作为 D2（历史宽度回填）/ D3（BaoStock 校验）/ F3（行业内宽度）的本地数据底座，替代靠 `stock_zh_a_spot`（无历史）+ `stock_zt_pool_em`（仅近 2 周）的旧口径。

**存储设计**（独立 SQLite 库，非 sentiment.db）：
- 库 `data/stock_daily.db`，表 `stock_daily_raw`，与 `data/sentiment.db`（看板生产库）隔离。
- 理由：(1) ~5500 只 × ~2400 天 ≈ 13M 行，撑大生产库会拖慢看板查询；(2) 仍是 SQLite，D2 可 SQL 跨表算宽度；(3) WAL + synchronous=NORMAL，读写并发安全；(4) 后续可平滑迁 parquet。
- schema：`code/date/open/high/low/close/volume/amount/amplitude/pct_change/pct_amt/turnover`，PK(code,date)。
  - `pct_change`（涨跌幅 %）、`pct_amt`（涨跌额）留作 D2 涨停价/跌停价判定（主板 10% / 创业板科创板 20% / ST 5%——D2 算，D1 只存 close + pct_change）。
  - `adjust=""`（不复权原始价）——保证涨停价判定准确，复权价会破坏 limit 检测。

**接口**（`app/collector/stock_daily.py`）：
- `fetch_stock_codes()` → 5527 只全 A（`stock_info_a_code_name` 走东财 dataapi，非 push2his，未被反爬封；缓存 `data/stock_codes.json`）。
- `fetch_one(code, start, end)` → 单只日线，1s 节流 + jitter，NaN 行过滤，遇 RemoteDisconnected/ConnectionError/429 → 抛 `CooldownError`（不硬刷）。
- `upsert_rows(rows)` → 批量 upsert（PK 冲突幂等更新）。
- `update_one(code, progress)` → **增量接口**：从 `progress[code]` 之后到今天只拉最新日。
- `run_batch(codes, incremental=...)` → **断点续传**：读 `data/stock_daily_progress.json`（{code: last_date}），跳过已采 code，每 5 只落盘一次进度，遇 CooldownError 保存进度 + 写剩余待采报告 `data/stock_daily_cooldown.txt` + 抛出。
- CLI：`python -m app.collector.stock_daily <full|update|one CODE|upone CODE|codes|stats>`。
- **scheduler 集成**：`runner.run()` 末尾 step 5 调 `run_batch(incremental=True)`，封 IP 时记 fail 不阻塞其它采集。

**防封**（复用 base.py 的 `trust_env=False` 全局补丁绕 Clash 代理）：1s 串行 + 0.1-0.5s jitter（与 `em_get` 同档）；遇 `RemoteDisconnected`/`ConnectionError`/`429` → `CooldownError` 停批次（不硬刷，冷却 30min 再重跑）。

**首跑策略**（任务约束）：先 1 只（600519）验证字段 + schema；再小批量（20-50 只）验证流程 + 断点续传 + 增量接口；全量 5500 只留 IP 解封后后台分批跑。

**首跑实际**（2026-07-05）：东财 push2his IP 被 F2 任务硬刷触发临时封锁（`RemoteDisconnected`），D1 启动时仍在封锁中。已验证：
- schema + DB（init_db / upsert / PK 幂等）/ progress JSON 往返 / CooldownError 检测（实拨被封正确抛出）/ code 列表 5527 只 / CLI（codes/stats/one 含 cooldown 优雅退出）/ scheduler 集成 全部就绪。
- 实拨单只 600519 因 IP 封锁未拿到数据（CooldownError 正确抛出）。后台 poller 每 5min 探一次，IP 解封后自动跑 1 + 20 只验证。
- akshare 1.18.64 `stock_zh_a_hist` 列名已从源码确认：日期/开盘/收盘/最高/最低/成交量/成交额/振幅/涨跌幅/涨跌额/换手率/股票代码，字段映射已写入 `fetch_one`。

**遗留**：
- 全量 5500 只 × 10 年采集待 IP 解封后跑（`python -m app.collector.stock_daily full`，可 `--limit N` 分批；预计 ~3-4 小时 @ 1s/只）。
- 若持续封 IP，可考虑 BaoStock（D3 任务）补 + mootdx K 线（TCP 7709 不封 IP）作备用源。
- code 列表含北交所（4x/8x/9x 开头），`stock_zh_a_hist` 是否覆盖北交所需 IP 解封后验证；不覆盖则 D2 时过滤。

### 4.5 TASK-D2 历史宽度指标计算与回填（10 年）

**目标**：从 D1 的 `mootdx_daily_raw`（5203 只 SH/SZ 全历史日线）算 7 项宽度按日聚合，回填 `daily_metric` 2016-2026（2550 交易日），替代旧口径靠 `stock_zh_a_spot`（无历史）+ `stock_zt_pool_em`（仅近 2 周）。

**实现**（`app/collector/width_history.py`，~280 行）：
- pandas 向量化：读 10.18M 行，`prev_close = close/(1+pct_change/100)` 反推（避免 groupby shift），涨跌幅规则按代码前缀（300/301/688/689=20%，其余=10%），涨停价=prev×(1+rule)，close-beyond-limit 检测除权日，groupby date 聚合。
- 7 指标：zt（close>=涨停价×0.999）、dt（close<=跌停价×1.001）、zb（high>=涨停价×0.999 且 close<涨停价×0.999）、seal_rate（zt/(zt+zb)）、up/down（pct_change 符号）、amount（sum/1e8）。
- 写库 17844 行，source='mootdx'。

**除权日检测改进（关键技术决策）**：
- 任务草案建议 `|pct_change| > 规则×1.5`（主板>15%、创业板>30%）作除权日阈值。实测发现该阈值**漏判 10-15%/20-30% 段**：正常交易不可能突破 ±规则，故此段必为除权日，但 1.5x 不跳过 → dt 大量误判（创业板/科创板 -20%~-30% 除权日被计为跌停）。
- 改用 **close-beyond-limit** 检测：`close > 涨停价×1.001 或 close < 跌停价×0.999`（close 超出限价 0.1% 以外必为除权日/数据异常）。修复后 dt 16 日均值误差 82%→33%，主要残差为 ST 误判。
- 保留 pct_change 1.5x 作辅助阈值。deviation from task spec（1.5x → close-beyond-limit）属「技术细节自己定」，已写 REQUIREMENTS.md §8.5。

**review gate（zt 交叉校验）**：
- 本表 zt=**收盘封板**（close 达涨停价）vs stock_zt_pool_em=**盘中触板**（含炸板回封）。16 日均值误差 **3.36% < 5% ✅**（剔除盘中采集的 20260706 后 15 日均值 2.21%、中位 1.49%）。
- 2 日 >5%（20260702 7.5%、20260703 5.6%）为封板 vs 触板口径差异（炸板回封数），非计算错误。
- akshare stock_zt_pool_em 近 3 日可取（东财 push2ex 未封锁）：20260706=64/20260703=108/20260702=93，与本表 70/102/86 趋势一致。

**已知误差**：
1. **ST 5% 不处理**：mootdx 无 ST 标记，ST 股按 10% 规则算致 dt 系统性偏高 ~20-30%（每日 ~4 只 ST 在除权日 -10% 被误判跌停）。需 ST 历史列表才能修（akshare `stock_zh_a_st_em` 东财源待验证）。
2. **北交所/B 股不覆盖**：mootdx 仅 SH/SZ 5203 只，不含北交所 324 只。2021-11 北交所开市后 up/down/amount 漏 ~6%。
3. **dt 口径差异**：本表 dt=收盘封跌停 vs 东财跌停股池，加 ST 误判，均值误差 32.8%（非 gate 项）。

**A1 近端值保护**：up/down/amount 仅回填 20160101-20260702，20260703/20260706（A1 全市场口径 source='akshare'）保留不覆盖。zt/dt 回填全段（覆盖近 2 周 stock_zt_pool_em）。

**遗留**：~~换手率分布（a_turnover_*）mootdx turnover 全 NULL 跳过，等 D3 BaoStock 补~~ → **已补**（2026-07-06，见 §4.4 阶段2 + REQUIREMENTS.md §8.5 换手率分布）。

### 4.4 TASK-D3 BaoStock 全段日线（D1 封锁期替代主力源 + 校验源）

**背景**：D1（akshare `stock_zh_a_hist`，东财 push2his）因东财 IP 临时封锁（F2 触发）尚未采全量。BaoStock 走自己服务（baostock.com，非东财 HTTP），不受东财封锁影响。D3 用 BaoStock 采**全段（1990-2026）全 A 股日线**作封锁期间替代主力数据源。原 D3 范围是「1990-2015 老数据补 D1 早期段 + 校验」，因 D1 akshare 封锁调整为「BaoStock 采全段全 A 股日线，优先近 10 年 2016-2026（D2 急需），再补 1990-2015 老段」。D1 akshare 解封后采 2016-2026 作交叉校验源（阶段2，待 D1 数据采全后做）。

**存储设计**（与 D1 同库不同表）：
- 库 `data/stock_daily.db`，表 `baostock_daily_raw`，与 D1 的 `stock_daily_raw` 分开（校验时 JOIN 对比）。
- schema 与 D1 对齐（共有字段）：`code/date/open/high/low/close/volume/amount/turnover/pct_change/preclose`，PK(code,date) + 双索引(date/code)。
- BaoStock 不返振幅(amplitude)/涨跌额(pct_amt)，故缺这两个字段（D1 有）；校验时只比对共有字段。D2 算涨停价用 pct_change + preclose 已够（涨停价 = preclose × 1.10/1.20/1.05）。
- `adjustflag="3"` 不复权（与 D1 一致，保证涨停价判定准确）。

**接口**（`app/collector/baostock_daily.py`）：
- `fetch_stock_codes()` → 复用 D1 的 `data/stock_codes.json`（5527 只，D1 用 `stock_info_a_code_name` 东财 dataapi 端点，非 push2his 未被封）。
- `to_baostock_code(code)` → 6 位代码转 BaoStock 格式：6xxxxx（含 688 科创板）→ sh.；0xxxxx/2xxxxx/3xxxxx → sz.；920xxx/8xxxxx/4xxxxx（北交所）→ None（BaoStock 不支持，跳过 + 记 `data/baostock_skipped_bj.txt`）。实测 5527 只中 324 只北交所被跳过，5203 只可采。
- `fetch_one(code, start, end)` → 单只日线，BaoStock `query_history_k_data_plus`，0.1s 节流，NaN/空串过滤。
- `upsert_rows(rows)` → 批量 upsert（PK 冲突幂等更新）。
- `run_segment(codes, seg)` → 段批量拉取：seg='r'（recent 2016-2026）/ 'o'（old 1990-2015）。跳过已采 + 北交所，每 10 只落盘进度。
- `run_update(codes)` → 增量更新（recent 段，从 progress[code]['r'] 之后到今天）。
- 进度：`data/baostock_progress.json` = `{code: {"r": yyyymmdd, "o": yyyymmdd}}`，原子写。
- CLI：`python -m app.collector.baostock_daily <recent|old|full|update|one CODE|upone CODE|stats|codes>`。

**并行加速**（`app/collector/baostock_parallel.py` + `app/collector/baostock_worker.py`）：
- BaoStock 单只 10 年日线 ~6.5s（服务端 2.2ms/row），串行 5203 只 × 6.5s ≈ 9.4h。实测 BaoStock 支持同 IP 多连接（多进程独立 login），用 subprocess 起 N 个独立 worker 进程并行采不同 code 段。
- `baostock_parallel.py` 把 code 列表分 N 块，subprocess.Popen 起 N 个 `baostock_worker.py`，各自 `bs.login()` 独立连接，进度共用 `baostock_progress.json`（原子写）。
- 6 workers 实测 ~4000 codes/h（vs 串行 ~550/h），~7x 加速，全段 recent ~1.2-1.5h。
- CLI：`python -m app.collector.baostock_parallel --seg=r --workers=6`。

**BaoStock vs D1 akshare 差异**：
- BaoStock 覆盖 1990-12-19 起（沪市老八股），比 akshare `stock_zh_a_hist`（2016 起，但可拉更早）历史更长。
- BaoStock 不覆盖北交所（920xxx/8xxxxx/4xxxxx），D1 akshare 覆盖范围待 IP 解封后验证。
- BaoStock 字段：date/code/open/high/low/close/volume/amount/turn(换手率%)/pctChg(涨跌幅%)/preclose(昨收)。D1 akshare 字段：日期/开盘/收盘/最高/最低/成交量/成交额/振幅/涨跌幅/涨跌额/换手率/股票代码。
- 两源 adjustflag="3"/adjust="" 均不复权，价格应一致（阶段2 校验内容）。

**scheduler 集成**：`runner.run()` step 6 调 `baostock_daily.run_update(todo)`，仅对已有 progress 的 code 增量（已 backfill recent 段的）；未 backfill 的由 `baostock_daily recent` 手动跑。BaoStock 无 IP 封锁风险，不需 CooldownError 处理。

**阶段2 校验（BaoStock vs mootdx，2026-07-06 完成）**：
- 原计划 BaoStock vs akshare，因 akshare 东财 IP 封锁未采（D1 改 mootdx 主力），改 **BaoStock vs mootdx** 交叉校验。两源 adjustflag="3"/不复权原始价应高度一致。
- 校验脚本 `app/collector/cleanup_d3d2.py validate`，SQL JOIN on (code, date) 聚合 + 抽样 200 只 × 全段 (~493K 行) 算分位差异。报告 `data/cleanup_d3d2_report.json`。
- **重叠行数**：9,847,524（BaoStock 9,987,727 + mootdx 10,179,172 in 2016-2026，重叠 9.85M）。BaoStock-only 140,203（1.4%），mootdx-only 331,648（3.3%，多为 baostock 不覆盖的 code/日期）。
- **共有字段差异率（剔除除权日后）**：
  | 字段 | 均值差异 | 中位 | 90 分位 | 最大 | 结论 |
  |---|---|---|---|---|---|
  | open/high/low/close | 0.0 | 0.0 | 0.0 | 0.0006% | 完全一致（同源原始价） |
  | volume（mootdx×100 归一化到股） | 7e-06 | 2e-06 | 1.6e-05 | 7.53% | 高度一致（极少数源差异） |
  | amount（元） | 0.0 | 0.0 | 0.0 | 0.075% | 完全一致（浮点精度内） |
  | pct_change（百分点） | 0.0002pp | 0.0pp | 0.0pp | 0.49pp | 高度一致 |
- **除权日检测**：两源 pct_change 差异 > 0.5%（绝对值）视为除权日/源差异，共 25,404 行 = 0.26% of overlap。除权日 baostock pct_change 用 adjusted preclose 算（含除权调整），mootdx 用 raw prev close 自算（跳水），故差异大；其余字段（OHLC/amount）除权日仍一致（同日真实价）。剔除后 pct_change 均值差异从 0.0195pp 降到 0.0002pp。
- **结论**：所有共有字段差异 <1% ✅（实为 <0.01% 量级，除除权日外完全一致）。两源数据质量互证，D2 用 mootdx 算宽度、本任务用 BaoStock 算换手率分布，口径可信。
- **volume 单位差异（关键发现）**：mootdx volume 单位=手（1 手=100 股），BaoStock volume 单位=股。校验时需 `mootdx.volume × 100` 归一化后对比。D2 width_history.py 用 amount 不用 volume，不受影响；其他模块若用 volume 需注意单位。
- **pct_change 计算口径差异**：BaoStock pctChg 由源提供（基于 adjusted preclose），mootdx pct_change 自算 `(close/prev_close-1)*100` 基于 raw prev close。除权日两值差异大（BaoStock 反映真实涨跌、mootdx 失真），非除权日完全一致。D2 算涨停价用 mootdx pct_change 反推 prev_close，除权日会误判（已用 close-beyond-limit 检测跳过）。

---

## 5. 环境约束（持久）

- **pypi.org / github.com DNS 不通** → 依赖经清华镜像 `pip install -i https://pypi.tuna.tsinghua.edu.cn/simple`
- **Clash 系统代理 127.0.0.1:7890** → 拦截东财流量走境外被东财封 IP；代码全局 `requests.Session.trust_env=False` 绕过
- **东财 push2/82.push2/80.push2 clist 端点硬反爬** → 单请求 RemoteDisconnected；用 sina 源（stock_zh_index_daily / stock_zh_a_spot）替代
- **东财 push2ex 涨停板池只保留近 2 周** → §4 宽度分项无法回填历史
- **akshare 1.18.64** 函数名变化：北向=`stock_hsgt_hist_em`、VIX→QVIX(`index_option_300etf_qvix`)、离岸人民币=`currency_boc_sina`、解禁=`stock_restricted_release_summary_em`

---

## 6. 下一步可迭代

1. **板块**：抄 `industry_comparison()`（SKILL.md 1250 行）用 em_get 试，看能否解硬封；不行则放弃
2. **美股指数**：测 yfinance 能否经代理装上/连上；或直爬新浪美股
3. **§4 积累**：每日 launchd 跑，约 11 月后 120 日窗口稳定
4. **信号调参**：RSI 阈值（现 30/70）可调，跨市场分过滤阈值（现 <80/>20）可调
5. **历史回填**：评估 Tushare Pro（付费）能否补涨停/北向/涨跌家数历史
6. **mootdx 备用源**：若 sina 再失效，可用 mootdx K 线（不封 IP，TCP 7709），需处理 BESTIP

---

## 7. 文件速查

- `REQUIREMENTS.md` — 需求 + 实现状态（§10）+ 数据字典（§8）
- `HELP.md` — 使用方法 + 注意事项 + 故障排查
- `PLAN.md` — 实现方案
- `config/indicators.yaml` — 指标注册表（增删改这里）
- `app/collector/base.py` — em_get 防封层 + 限频 + trust_env 补丁
- `app/collector/tencent.py` — 腾讯行情（换手率）
- `app/collector/direct.py` — 直爬东财（主力资金流）
- `app/compute/signals.py` — RSI 买卖点
- `app/compute/sentiment.py` — §4 A股情绪分（6项加权）
- `app/compute/cross.py` — §6 跨市场分（去极值均值）
- `app/compute/derived.py` — 派生公式指标（封板率 = 1 - 炸板率）
- `app/collector/stock_daily.py` — D1 全 A 股日线（akshare 东财源）
- `app/collector/baostock_daily.py` — D3 全 A 股日线（BaoStock 源，封锁期替代主力）
- `app/collector/baostock_parallel.py` + `baostock_worker.py` — D3 并行采数
- `app/main.py` — FastAPI 端点 + range_dep 校验 + /api/manual/check + manual 值保护
- `a-stock-data/SKILL.md` — 数据工具包源（可继续抄函数）

---

## 8. 情绪Tab扩充方案（2026-07-08）

### 8.1 现状

当前情绪tab只有2个图表，都在 `score_daily` 表：
- 跨市场综合评分（0-100）— `cross_market` score（4647天）
- A股综合情绪分（0-100）— `a_sentiment` score（2542天），全市场6指标加权：涨跌比25% + 涨停数20% + 炸板率15% + 连板15% + 成交额10% + 北向资金15%

### 8.2 用户需求

1. 中证500情绪
2. 中证1000情绪
3. 上证50情绪
4. 沪深300情绪
5. 冰点概念（各指数进入冰点区域时的检测与展示）

### 8.3 可行性结论：全部可实现

现有数据支撑：
- 沪深300：5942天日线数据 + QVIX波动率（1568天）
- 中证500：5221天日线数据
- 中证1000：2848天日线数据 + QVIX波动率（807天）
- 上证50：需要新增采集（akshare `sh000016`），零成本

### 8.4 方案设计

#### 一、数据采集新增

| 项目 | 说明 |
|------|------|
| 上证50指数 | 添加 `sz50` 到 `indicators.yaml`，symbol=`sh000016`，同现有 akshare 采集链路 |
| 各指数成分宽度 | 上证50/沪深300/中证500/中证1000 各自的涨跌家数、涨停跌停数（需确认数据源） |

#### 二、情绪分计算

为每个指数独立计算 0-100 情绪分，写入 `score_daily` 表：

| score_id | 名称 | 计算方式 |
|----------|------|---------|
| `sentiment_sz50` | 上证50情绪 | 价格RSI + 波动率 + 成交额偏离度，3指标归一化加权 |
| `sentiment_hs300` | 沪深300情绪 | 同上 + QVIX波动率（已有数据） |
| `sentiment_csi500` | 中证500情绪 | 同上 |
| `sentiment_csi1000` | 中证1000情绪 | 同上 + QVIX波动率（已有数据） |

计算逻辑：
- 每个指数取：RSI(14)归一化、成交额MA20偏离度、QVIX（如有）、涨跌幅滚动百分位
- 加权综合为 0-100 分，<20=冰点(is_freeze)，>80=过热(is_overheat)
- 统一走 `app/compute/sentiment.py` 框架，扩展为 per-index 配置

#### 三、冰点概念

在现有 `is_freeze` 字段基础上增强：
1. **冰点热力图**：4个指数 × 时间轴，红色=冰点区域，类似行业涨跌幅热力图
2. **冰点统计卡片**：各指数当前是否冰点、冰点持续天数、历史冰点频率
3. **冰点恢复信号**：冰点后首次回升到30以上标记"冰点解冻"，与现有买点信号叠加展示

#### 四、前端布局

情绪tab从2个图表扩展为：

```
┌─────────────────────────────────────────────┐
│  📊 指数情绪仪表盘（冰点/过热）              │
│  ┌──────────┬──────────┬──────────┬────────┐ │
│  │ 上证50   │ 沪深300  │ 中证500  │ 中证1000│ │
│  │ 情绪: 45 │ 情绪: 38 │ 情绪: 22 │ 情绪: 18│ │
│  │ 中性     │ 偏冷     │ ⚠冰点3天 │ ⚠冰点5天│ │
│  └──────────┴──────────┴──────────┴────────┘ │
├─────────────────────────────────────────────┤
│  📈 上证50情绪分（0-100）含买卖点            │
│  📈 沪深300情绪分（0-100）含买卖点           │
│  📈 中证500情绪分（0-100）含买卖点           │
│  📈 中证1000情绪分（0-100）含买卖点          │
├─────────────────────────────────────────────┤
│  🔥 冰点热力图（4指数 × 时间）               │
├─────────────────────────────────────────────┤
│  🌐 跨市场综合评分（0-100）[现有保留]        │
│  📊 A股综合情绪分（0-100）[现有保留]         │
└─────────────────────────────────────────────┘
```

#### 五、还可进一步扩充

| 方向 | 说明 |
|------|------|
| 创业板/科创50情绪 | 扩展 `cyb`、`kc50` 情绪分，覆盖全部6个核心宽基 |
| 港股情绪 | 恒生指数/恒生科技 情绪分，复用同样框架 |
| 情绪与买卖点联动 | 冰点区域的买点信号高亮标注，情绪分叠加在买卖点折线图上 |
| 情绪分与行业联动 | 行业涨跌幅 × 全市场情绪分交叉分析 |
| 情绪预警推送 | 进入冰点/过热时前端醒目提示（顶部 banner） |

#### 六、实施步骤

| 步骤 | 内容 | 预计 |
|------|------|------|
| 1 | 添加上证50到 indicators.yaml，采集历史数据 | 子agent |
| 2 | 扩展 `app/compute/sentiment.py` 支持 per-index 情绪分计算 | 子agent |
| 3 | 更新 `app/compute/runner.py` 跑通全流程 | 子agent |
| 4 | 更新 `/api/sentiment` 返回 per-index 情绪数据 | 子agent |
| 5 | 更新前端 `renderSentiment()` 展示4个指数情绪 | 子agent |
| 6 | 导出静态站数据 | 子agent |
| 7 | 如有余力，做冰点热力图和创业板/科创50 | 子agent |

---

## 9. 期货机构净多空持仓指标方案（2026-07-08 调研，待实施）

### 需求理解

在情绪Tab中添加**期货机构净多空持仓**指标，包括：
1. **机构净多空情况**：中金所（CFFEX）股指期货（IF/IC/IH/IM）前20名会员的多空持仓汇总，计算净头寸
2. **同向准确率**：跟随机构方向（净多→做多，净空→做空）的胜率
3. **逆向准确率**：与机构反向（净多→做空，净空→做多）的胜率，即对冲思维

### 数据源调研

**`akshare.get_cffex_rank_table()`** — 中金所持仓排名数据：

```python
import akshare as ak
result = ak.get_cffex_rank_table(date='20250708', vars_list=['IF', 'IC', 'IH', 'IM'])
```

- **入参**：`date`（YYYYMMDD，支持回溯到至少 2024-01）、`vars_list`（品种列表）
- **返回**：`dict[str, DataFrame]`，key 为合约代码（如 `IF2507`、`IC2509`）
- **每合约 21 行**（前20名会员 + 1行汇总 rank=999），列：
  - `long_open_interest` — 多头持仓
  - `long_open_interest_chg` — 多头持仓变化
  - `short_open_interest` — 空头持仓
  - `short_open_interest_chg` — 空头持仓变化
  - `long_party_name` / `short_party_name` — 多/空排名会员名称
  - `vol_party_name` — 成交量排名会员名称
  - `variety` — 品种（IF/IC/IH/IM）
  - `rank` — 排名（1-20 为会员，999 为合计）

**关键发现**：
- 多空排名是分开的（long_party_name ≠ short_party_name 同 rank 不一定同机构）
- 汇总行（rank=999）给出全合约总多空持仓，可直接用
- 每个品种有多个合约（当月、下月、季月），需跨合约汇总
- 历史数据至少可回溯到 2024-01-02

### 指标计算方案

#### 一、日度净持仓计算

对每个品种（IF/IC/IH/IM），汇总该品种所有合约的 rank=999 行：

```
variety_total_long = Σ long_open_interest (rank=999, 该品种所有合约)
variety_total_short = Σ short_open_interest (rank=999, 该品种所有合约)
variety_net = variety_total_long - variety_total_short
variety_net_ratio = variety_net / (variety_total_long + variety_total_short)  # 归一化到 [-1, 1]
```

**综合净持仓指标**（4个品种加权汇总）：

```
total_long = Σ variety_total_long  (IF+IC+IH+IM)
total_short = Σ variety_total_short
net_position = total_long - total_short
net_ratio = net_position / (total_long + total_short)  # [-1, 1]
```

**解读**：
- `net_ratio > 0`：机构整体净多头（看涨）
- `net_ratio < 0`：机构整体净空头（看跌）
- `net_ratio` 的绝对值越大，方向越明确
- 跟踪 `net_ratio` 的**变化趋势**（持仓变化方向）比绝对值更重要

#### 二、同向/逆向准确率计算

**核心逻辑**：用机构净持仓方向预测次日指数涨跌，统计准确率。

**输入**：
- 每日机构净持仓方向：`sign = sign(net_position)` → +1（净多）或 -1（净空）
- 每日指数次日涨跌：`next_day_return = (close_next - close) / close` → +1（涨）或 -1（跌）

**同向准确率**（Follow Institutions）：
```
同向正确 = (sign == sign(next_day_return))  # 机构方向与次日涨跌一致
同向准确率 = 同向正确次数 / 总次数
```
含义：如果机构净多→次日涨了，或机构净空→次日跌了，就算"跟对了"

**逆向准确率**（Contrarian）：
```
逆向正确 = (sign != sign(next_day_return))  # 机构方向与次日涨跌相反
逆向准确率 = 逆向正确次数 / 总次数
```
含义：如果机构净多→次日跌了，或机构净空→次日涨了，就算"反着做对了"

**多时间窗口**：
| 窗口 | 含义 |
|------|------|
| 1日 | 次日涨跌 vs 今日净持仓方向 |
| 5日 | 未来5日累计涨跌 vs 今日净持仓方向 |
| 10日 | 未来10日累计涨跌 vs 今日净持仓方向 |
| 20日 | 未来20日累计涨跌 vs 今日净持仓方向 |

**对标指数**：沪深300（IF 对应）、中证500（IC 对应）、上证50（IH 对应）、中证1000（IM 对应）

#### 三、数据存储

**新表 `futures_position`**（日度）：
```sql
CREATE TABLE IF NOT EXISTS futures_position (
    date TEXT NOT NULL,
    variety TEXT NOT NULL,        -- 'IF'/'IC'/'IH'/'IM'/'综合'
    total_long REAL,              -- 总多头持仓
    total_short REAL,             -- 总空头持仓
    net_position REAL,            -- 净持仓 = long - short
    net_ratio REAL,               -- 净持仓比例 = net / (long+short)
    long_chg REAL,                -- 多头持仓变化（当日-前日）
    short_chg REAL,               -- 空头持仓变化
    contract_count INTEGER,       -- 合约数量
    source TEXT DEFAULT 'akshare',
    created_at TEXT DEFAULT (datetime('now','localtime')),
    PRIMARY KEY (date, variety)
);
```

**新表 `futures_accuracy`**（准确率跟踪，按窗口）：
```sql
CREATE TABLE IF NOT EXISTS futures_accuracy (
    date TEXT NOT NULL,
    variety TEXT NOT NULL,        -- 'IF'/'IC'/'IH'/'IM'/'综合'
    index_id TEXT NOT NULL,       -- 对标指数 hs300/csi500/sz50/csi1000
    window INTEGER NOT NULL,      -- 1/5/10/20 日
    follow_accuracy REAL,         -- 同向准确率（滚动窗口）
    contrarian_accuracy REAL,     -- 逆向准确率
    follow_n INTEGER,             -- 同向样本数
    contrarian_n INTEGER,         -- 逆向样本数
    net_direction TEXT,           -- 当日净方向 'long'/'short'
    actual_return REAL,           -- 实际N日涨跌
    PRIMARY KEY (date, variety, index_id, window)
);
```

### 前端展示方案

在情绪Tab中新增一节「🏦 期货机构持仓」：

```
┌─────────────────────────────────────────────────┐
│  🏦 期货机构净多空持仓（中金所 IF+IC+IH+IM）      │
│  ┌─────────────────────────────────────────────┐ │
│  │  [净持仓面积图] 多头 vs 空头 堆叠面积        │ │
│  │  下方 net_ratio 折线（红正蓝负）             │ │
│  └─────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────┤
│  📊 各品种净持仓比例（IF/IC/IH/IM 四合一折线）   │
├─────────────────────────────────────────────────┤
│  🎯 机构方向准确率仪表盘                          │
│  ┌──────────┬──────────┬──────────┬────────────┐ │
│  │ 同向 1日 │ 同向 5日 │ 同向 10日│ 同向 20日   │ │
│  │  52.3%   │  55.1%   │  58.2%   │  61.5%      │ │
│  │ 逆向 1日 │ 逆向 5日 │ 逆向 10日│ 逆向 20日   │ │
│  │  47.7%   │  44.9%   │  41.8%   │  38.5%      │ │
│  └──────────┴──────────┴──────────┴────────────┘ │
│  说明：同向=跟随机构方向做多/做空；逆向=反向操作  │
│  窗口越长准确率越高 → 机构中期方向比短期更可靠    │
└─────────────────────────────────────────────────┘
```

### 实施步骤

| 步骤 | 内容 | 预计 |
|------|------|------|
| 1 | 新建 `app/collector/fetchers.py` 添加 `fetch_futures_position()` 采集函数 | 子agent |
| 2 | 新建 `app/collector/futures_position.py` 采集器（含历史回填） | 子agent |
| 3 | 新建 `app/compute/futures_position.py` 计算模块（净持仓 + 准确率） | 子agent |
| 4 | 更新 `app/compute/runner.py` step 10 加入期货持仓计算 | 子agent |
| 5 | 更新 `app/db/__init__.py` 建表（futures_position + futures_accuracy） | 子agent |
| 6 | 更新 `/api/sentiment` 返回期货持仓数据 | 子agent |
| 7 | 更新前端 `renderSentiment()` 展示期货持仓图表 | 子agent |
| 8 | 更新 `static-site/export.py` 导出静态数据 | 子agent |

### 注意事项

1. **数据时间范围**：CFFEX 数据从 2024-01 起可用，旧数据不存在需标注
2. **合约换月**：每月第三个周五交割，新合约上市后需平滑过渡
3. **节假日**：非交易日无数据，前端需留空或线性插值
4. **准确性声明**：准确率是历史统计，不代表未来预测能力
5. **免责**：机构持仓数据仅供研究参考，不构成投资建议

### 可扩展方向

| 方向 | 说明 |
|------|------|
| 单品种深度 | IF/IC/IH/IM 各自独立图表，看不同品种机构行为差异 |
| 前5/前10集中度 | 头部机构持仓占比，判断方向是否被少数机构主导 |
| 持仓变化信号 | 净持仓大幅变化日（>1 std）标记为"机构异动" |
| 与情绪分联动 | 机构净多 + 情绪冰点 → 双重买入信号叠加 |
| 席位分析 | 特定机构（中信/国君/华泰）的持仓方向跟踪 |

## 10. 采集并发提速可行性分析（2026-07-09 调研，暂不实施）

### 背景

`update_all.sh` 提速做完 P0+P1+P2 后（collect 3h->30-40min），遗留疑问：baostock（5072 codes 串行）和 mootdx（5203 codes 逐个 TCP）为什么是串行/逐个？能否"一次请求拉多只"省网络往返进一步提速？本节为调研留档，**结论：两条协议都不支持批量多只，并发可行但收益场景窄，暂不实施**。

### 核心结论

两个源都**没有"一次请求拉多只历史 K 线"的接口**--协议/API 层硬限制，非代码偷懒。能提速的是**并发**（多连接同时拉不同 code），不是"一次拉多个"。且两源并发可行性差别大：mootdx 可并发，baostock 受库设计限制难并发。

### mootdx（通达信协议，5203 逐个 TCP）

- **为何单只**：`client.bars(symbol=code, frequency=9, offset=800, start=N)` 是通达信"K 线数据"请求，协议本身单只请求-响应，按 `start` 偏移分页（每页 800 行）拼全历史。实测 0.03s/页，单只 4 页 ~0.12s，5203 只串行 ~10min。
- **能否一次拉多只**：不能。通达信有批量"实时行情"接口（多只现价快照），但那是当日快照非历史日 K；协议无"一次请求多只历史日 K"指令。
- **能否并发**：**能，不难**。mootdx 可创建多 client 实例（每个一条独立 TCP），可连 `_TDX_SERVERS` 里不同 server（备 10 个）。不同 client 独立 socket+状态，N client 配 N 线程各拉各的 code，互不串台，线程安全。
- **风险**：通达信公共服务器对单 IP 并发连接数有限制，实测 5-10 路还行，再多被踢/断连，需控并发+失败重建重试。
- **收益**：全量 5203 只 ~10min -> 5 路并发 ~2min。

### baostock（5072 串行）

- **为何单只**：`bs.query_history_k_data_plus(code, start, end, fields)` 一次一只，baostock 服务端 API 无批量多只历史 K 线接口。单只 10 年日线实测 ~6.5s（服务端 2.2ms/row），0.1s 全局节流。
- **能否一次拉多只**：不能，API 无此能力。
- **能否并发**：**难**。baostock Python 库是**模块级全局单 session**：`bs.login()` 全局一次，所有 `query_*` 共享一连接，结果集 `rs.next()` 有状态。多线程并发会**串台**（A 线程 query，B 线程 rs 读走结果）。要并发只能：
  - **多进程**（每进程独立 `bs.login()` + 独立 session），进程间不共享，安全但重（进程启停+login 开销+进度分片汇总）；
  - 或 patch baostock 库支持多 session（侵入式，升级冲掉）。
  - baostock 服务端本身支持多 session 并发，但客户端库没暴露多 session 接口--库的缺陷，非服务端限制。
- **收益点最大但实现最重**：手动 `recent` 首次全量 5072 只 × 6.5s ≈ **~9h**；多进程 4-8 路可降到 ~1-2h。

### 当前瓶颈判断（为何暂不实施）

P1/P2 已解决**日常增量**：baostock 日常增量被默认跳过（P1），mootdx 当日已采 code 本地跳过不发 TCP（P2）。日常 `update_all` 里两源已非瓶颈。**并发的价值只剩"全量回填/补缺口"低频场景**：

| 场景 | 串行耗时 | 并发后 | 值不值得 |
|------|----------|--------|----------|
| mootdx 全量回填（首次建库/重建） | ~10min | ~2min（5 路） | 收益小，本就不长，且有公共 server 限流风险 |
| baostock 全量 recent（首次/大补） | ~9h | ~1-2h（4-8 进程） | 收益大，但多进程实现重 |

### 何时做 + 怎么做（留档方案）

- **baostock 9h 是唯一值得啃的**：`multiprocessing.Pool`，每 worker 独立 `bs.login()`，按 code 分片，progress 分片写后合并。4-8 进程可降到 1-2h。落地前先小并发（2 进程）测服务端承载力，别一上来 8 进程被封。
- **mootdx 并发不值得做**：10min 本就不长，公共 server 限流风险大于收益。真要做就 5 路 client+不同 server+重试，优先级低。

### 决策

**暂不实施**。触发条件：手动跑 `baostock_daily recent` 全量觉得 9h 不能忍时，再上多进程方案。mootdx 9-10min 量级可接受，不动。

---

## 11. H5 移动端打磨 + 获客基础设施（2026-07-10）

### 背景

公网地址 http://tdsignal-ujpzw01zm.maozi.io/ 已上线（Cloudflare Pages 静态版）。本轮目标：①移动端体验打磨（用户实机反馈）②让公网可被搜索到、可分享传播、技术圈可发现。共 8 个 commit（3e4a7b0..539f5b0）。

### H5 移动端打磨（4 项）

| # | commit | 问题 | 方案 |
|---|---|---|---|
| 1 | 3e4a7b0 | 模拟回测浮层 iframe 加载白屏（sim html 最大 991KB） | sim-window 加 .sim-loading 转圈层，打开时 show、frame.onload 后 hide，z-index:loading=1<close=2 |
| 2 | 13e63c2 | H5 网格列数不固定，「1列/2列」按钮在行业 tab 点无反应 | sparkline 默认 2 列、行业卡片强制 1 列、KPI 2 列；移除按钮 |
| 3 | 3fff0c7 | KPI 小卡片 flex+calc 因 subpixel rounding 换行成 1 列 | `.cards.kpi-row` 改 `display:grid;grid-template-columns:1fr 1fr` 硬约束 |
| 4 | a17f508 | 北向资金停更还显示「停更」卡片占位 | `isStaleMetric(m.date,r.date,30)` 日期差动态判断，恢复自动显示 |

**关键教训（H5 网格）**：移动端等宽多列布局用 CSS Grid 比 Flex 稳。`flex:1 1 calc(50%-5px)+flex-wrap:wrap` 中 flex-basis 是建议值，浏览器 subpixel rounding 会让第二项差几像素放不下而换行；`grid-template-columns:1fr 1fr` 列宽是硬约束不受影响。同模式已用于 spark-grid / industry-grid / KPI。

### 交互防刷新（1 项，624e8de）

**问题**：热力图「近1日/近5日/全部」按钮和周期「1月/3月/6月」按钮点击后调 `renderTab()` 整页重渲染，滚动位置丢失。

**方案**：
- **热力图**：抽出 `_heatmapSetOption(c, heatmap, toggleBtnsEl)` 纯函数，`renderIndustryHeatmap` 只建一次 DOM+init 一个 echarts 实例，按钮点击复用同实例 `setOption` 重画+同步 active 态。不调 renderTab、不重建 DOM、不丢滚动。
- **周期按钮**：切换前记 `savedScroll=scrollY` + 锁 `content.style.minHeight=当前高度`（防 `content.innerHTML='加载中'` 清空时高度塌陷致浏览器跳顶）+ `renderTab().then(()=>{释放minHeight; rAF恢复scrollY})`。避免「跳顶再跳回」闪烁。

### 获客基础设施（3 项）

#### 11.1 SEO（7fc98fa）

SPA 动态渲染爬虫抓不到内容，补静态 SEO：
- **head**：title/description/keywords（含 trade-data-signal/tdsignal/tdsignal-ujpzw01zm 三组关键字）/canonical/robots index,follow/OG 全套(type/site_name/title/desc/url/image/locale)/Twitter Card summary_large_image/JSON-LD WebApplication 结构化数据(name/alternateName=trade-data-signal/applicationCategory=FinanceApplication/offers 免费)。
- **body noscript 静态文案区**：爬虫可读的项目介绍+8 项核心功能列表+关键字+域名（JS 禁用时也可见，搜索引擎索引主体内容）。
- **og.png**：`scripts/gen_og_image.py` 用 Pillow 生成 1200×630 深色品牌卡片（品牌标题+3 数据卡+域名），放 web/ 和 static-site/ 根目录。字体用 macOS `/System/Library/Fonts/PingFang.ttc`（index 4=Medium/5=Semibold）。`app/main.py` 加 `/og.png` 路由（动态版与静态版路径一致）。
- **Pillow 安装**：`pip install -i https://pypi.tuna.tsinghua.edu.cn/simple Pillow`（项目原本无，akshare 不带）。

#### 11.2 分享图功能（76f7558）

**方案选型**：自绘分享卡片（非 html2canvas 截图）。理由：无第三方库依赖、体积小、样式完全可控、自带品牌引流水印。用户在 AskUserQuestion 选定。

**实现**：`drawShareCard(r)` 用 canvas API 自绘 1080×1350 竖版卡片：
- 顶部品牌条（蓝色圆角 `📊 tdsignal` + `trade-data-signal`）
- 主标题「A股情绪看板」+ 日期
- 6 个数据卡（2 行 ×3）：情绪分（综合/跨市场/恐贪，带 sentimentTag/fearGreedLabel 标签）+ 宽度（涨停/跌停/成交额，红绿蓝配色）
- 上证指数迷你走势（从 `r.indices_sparkline` 取 sh000001，画 area+line，带涨跌幅标注）
- 底部域名 `tdsignal-ujpzw01zm.maozi.io` + slogan

`openShareModal()` 复用 `rule-modal` 弹窗，`canvas.toDataURL` 生成预览 + `<a download>` 下载按钮。数据从 overview 端点取（web `/api/overview` / static `./data/overview.json`）。

**按钮**：PC header 右上角「📤 分享」+ H5 顶部条📤图标按钮，`.pc-share-btn`/`.h5-share-btn` 用 @media 互斥显示。

#### 11.3 README + LICENSE + HelloGitHub（539f5b0）

- **README 重写**：从纯开发者安装步骤 → 对外吸引版。前置在线 demo+og 图+关键字，6 大核心功能（情绪温度计/买卖点信号/市场宽度/行业轮动/期货持仓/大盘位置感），技术栈表，快速开始，项目结构，声明，MIT。原安装步骤保留后置。
- **LICENSE**：MIT（开源传播必需，HelloGitHub 入选前提）。
- **HELLOGITHUB.md**：提交文案（推荐理由/亮点/地址/demo/类别/语言/license）+ 提交说明（审核周期~1 月/提升入选率建议：截图+topics+攒 star）。

### 验证模式（本轮统一）

每个改动跑同一套验证：
1. `node --check web/app.js` + `node --check static-site/app.js` 语法
2. 两版对应函数 `diff` 一致性（除数据源 URL 外必须一致）
3. `py_compile` 后端改动
4. `.venv/bin/python scripts/bump_asset_version.py` 破缓存
5. commit + push origin main

### 遗留

见 TASKS.md 交接状态节「遗留 / 待用户手动做」（GitHub topics / README 截图 / HelloGitHub 提交 / og.png 预览验证 / g.cn10y buy_aux 回测）。

## §12 update_all 拆并行流水线（2026-07-10，c6407aa）

### 痛点
原 `update_all.sh` 串行 collect(11 步)->deploy->check，mootdx 5072 只 ~10min 等慢任务拖累整体，核心数据（指数/指标/情绪分）已采却要等慢任务跑完才推送上线（实测日志 ok=109 fail=5217，慢任务大量失败仍阻塞核心上线）。

### 依赖分析结论（拆分依据）
- 慢任务（mootdx/stock_daily/baostock）写到独立库 `stock_daily.db`，**不写 sentiment.db**；export 只读 sentiment.db。慢任务通过 step8/step9 算宽度写回 sentiment.db 才影响上线。
- **核心看板**（指数/scores/signals/sentiment tabs/overview 大部分/position/summary/new_high_low/ma_alignment/rotation）只依赖快采集 step1+2+4。
- step3(boards 全 disabled)、step5(stock_daily_raw 无消费方)、step6(baostock 默认跳过) 是**死端**，不影响任何上线 JSON。
- compute 里 sentiment/ad_line/volume_ratio 依赖 width，需 width 完成后重算。

### 4 条 pipeline
| pipeline | step | compute | export | 上线 |
|---|---|---|---|---|
| core | metrics,indices,industry_extras | 全量(用现有width) | 全量 | 最先(分钟级) |
| width | mootdx,industry_width,width_history | 全量(重算新width) | 全量覆盖 | 慢(~10min)后补 |
| futures | futures | step内accuracy | 全量 | 独立快 |
| stock_daily | stock_daily | 无 | 无(不push) | 后台死端不阻塞 |

core 先上线时情绪分用昨日 width（宽度日变化小，偏差可接受），width 完成后覆盖。

### 关键文件
- `scripts/update_all.sh`：并发启动 4 pipeline + 统一交易日闸门 + wait core/width/futures
- `scripts/pipeline.sh`(新)：通用流水线 采集(子集)+compute+export+持锁 commit+push
- `scripts/with_lock.py`(新)：fcntl.flock 持锁串行化 git（**macOS 无 flock 命令**，用 Python fcntl）
- `app/collector/runner.py`：`run(steps=None)` 加 steps 参数，`_want` 守卫，向后兼容
- `scripts/deploy.sh`：加可选 `$1` pipeline 名参数（commit msg 标注 `[core]`/`[width]`/...）
- `scripts/update_all_serial.sh`：旧串行版备份回退

### 并发安全（3 处）
1. **SQLite 并发写**：`db.py` get_conn 加 `busy_timeout=30000`；stock_daily/baostock 加 `busy_timeout=10000`。WAL + busy_timeout 多进程写串行化自动重试，避免 `database is locked`。
2. **git 并发 commit+push**：`with_lock.py` 持 fcntl.flock 独占锁调 deploy.sh 串行化（避免 index.lock 冲突 + 避免 git add 把别 pipeline 正在写的半截 JSON stage 进来）。
3. **signal_stats.json 并发写**：`signal_stats.store` 改原子写（.tmp + os.replace），避免 core/width 并发 compute 撕裂 JSON。

### 验证状态
组件级全通过：bash -n 语法 / runner steps=[] 守卫 / with_lock 串行(2s) / busy_timeout=30000ms 生效 / signal_stats 原子写(无 .tmp 残留)。**完整端到端待手动跑** `bash scripts/update_all.sh`（会真采集+部署公网，mootdx ~10min）。

### force 参数（周末补数据/校准，c6d6ee2）
- `bash scripts/update_all.sh force` 绕交易日闸门强制全量采集；无参仍走闸门（非交易日仅 deploy+check_signals）。
- 场景：周一到周五忘跑，周末补漏跑日。回填类 step（`collect_series` / `width_history.run_recent` / mootdx 增量）不依赖"今天交易日"，源周末有历史数据。
- 当日快照 `date=last_trading_day()`=最近交易日，A1 守卫放行采收盘值，幂等不误盖（不会把上周五数据盖成今天）。
- launchd 15:33 无参不变；force 仅手动触发。

### 进程互斥（防并发撞 progress / 限流空转）
- `update_all.sh` 开头 `exec with_lock.py --nb /tmp/trade_update_all.lock` 自包装持锁（`UPDATE_ALL_LOCKED=1` 防递归）；重复跑的第 2 个持不到锁直接 exit 0 跳过。
- 根因：mootdx/stock_daily/baostock 的 `progress.json` 原子写（`os.replace(tmp->真)`）不支持跨进程并发 -> 撞坏 -> fallback 全量 5203 只；且两进程并发连通达信/东财被限流全 `empty` 空转（2026-07-11 两个 force 并发卡 2h+ 即此）。
- `with_lock.py` 加 `--nb` 非阻塞选项；`pipeline.sh` 的 deploy 仍用阻塞模式（排队串行 git），向后兼容。
- 锁会自动跳过第 2 个，但仍应避免同时手动跑两个 update_all。

## §13 多源补采 + launchd 定时 + 前端两项（2026-07-10，f2e710b/442f1e0/26f390b）

### 痛点
- 新浪指数主源 15:30 收盘后当日延迟（要到 16 点后才稳定有今日），导致 15:33 全量采集可能采到昨日。
- 采集一直是**手动跑**，launchd 从未加载过。
- 近期冰点/买卖点"今日"文字替换多余（用户要求只保留行背景色）；分享按钮旁无采集时间，用户无法判断数据新旧。

### 多源补采（index_backfill.py）
- `app/collector/index_backfill.py`：`CORE_A_INDICES` 映射 8 指数 → (baostock_code, tencent_symbol)。kc50 仅腾讯（baostock 缺）。
- `verify_and_backfill_indices(date)`：查每个指数 `index_daily` 最新日期；缺则 baostock（跳 kc50）→ 腾讯兜底；全失败 `log_collect` 告警。返回 (ok, fail, details)。
- **集成点**：`runner.py` step2 指数循环后调一次（主源当日延迟 → 自动兜底）。
- **三源链路**：新浪（主，快）→ baostock（备1，7/8 覆盖）→ 腾讯（备2，全覆盖，慢）。

### launchd 两个时间点（scripts/plists/）
- `com.trade.update-all.plist`：**15:33** 全量采集（update_all.sh），RunAtLoad=false。
- `com.trade.backfill-evening.plist`：**02:00+20:00** 轻量回填兜底（02:00 凌晨兜底+20:00 晚间兜底）（backfill_indices.sh → index_backfill.main()）。
- `main()`：非交易日跳过；调 verify_and_backfill；有新数据则重算情绪分 + 推送公网，无则跳过（15:33 已采全或三源都缺）。
- PATH 显式设 `/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin`（launchd 默认 PATH 极小，python3 在 homebrew）。
- 加载：`launchctl load ~/Library/LaunchAgents/com.trade.{update-all,backfill-evening}.plist`。

### 前端两项（26f390b）
1. **取消今日替换**：`_renderSignalGrid` `dateLabel = fmtDate(dt)`（去掉🔥今日）；`fmtDate` 去今日判断纯格式化 MM-DD。今日行**仅靠 `today-row` 背景色**高亮。
2. **采集时间显示**：分享按钮旁 `<span class="collect-time">`。
   - 数据源 = `collect_log` 表最新 `run_at`（**脚本运行记录**，非 generated_at 收盘分析标签），格式 `YYYYMMDD HH:MM:SS`。
   - `export.py` export_overview + `app/main.py` /api/overview 加 `collected_at` 字段（`run_at[:10].replace("-","") + " " + run_at[11:19]`）。
   - `renderOverview`：PC 填 `数据采集时间：YYYYMMDD HH:MM:SS`，H5 @media 精简只填时间串。
   - **双版同步**：static-site/ + web/ + app/main.py 全改；`bump_asset_version.py` 破缓存。

### 验证
- index_backfill 3 场景（全有/部分缺/全缺）通过。
- launchctl list 确认两 plist 已加载（状态码 0）。
- 前端双版一致性：🔥今日残留 0、collected_at 填 DOM 1、span 2（PC+H5）；`/api/overview` 返回 `collected_at='20260710 16:46:00'`、`date=20260710`；node -c 两 app.js 语法 OK。

---

## §14 国家队宽基 ETF 资金动向追踪（2026-07-13）

### 背景
追踪 12 只宽基 ETF 的份额变动+成交额放量，推断疑似大资金（含国家队）进场/离场。口径声明：代理推断，非真实国家队席位数据（无法区分汇金/证金/社保/险资/公募）。详见 REQUIREMENTS.md §8.6。

### 实施
新建 `app/collector/etf_national_team.py`（4 fetcher + 日级/daily pipeline + 信号算法 + export）。独立库 `data/etf_national_team.db`（3 表：etf_daily/etf_signal/etf_holder_quarterly），与 sentiment.db 隔离（参考 stock_daily.py 理念）。

**4 个 fetcher（全部实测可达）**：
1. **A 沪市份额** `ak.fund_etf_scale_sse(date)`：返回当日全沪市 ETF（~400只），过滤本清单 7 只沪市。周末抛 KeyError（try/except 跳过）。单位：份。510050 ~586 亿份。
2. **B 深市份额** `ak.fund_scale_daily_szse(start,end,"ETF")`：区间批量，一次返回多日全部深市 ETF。过滤本清单 5 只深市。**要求 YYYYMMDD 格式**（曾误传 YYYY-MM-DD 报 ValueError）。
3. **C ETF OHLC** mootdx `client.bars(symbol, frequency=9)`：**替代东财 push2his**（2026-07-13 起 IP 封，`fund_etf_hist_em` 不可用，sina 备选也空）。mootdx 完美支持 ETF（510050/159915 均通），返回 open/close/high/low/amount（元）。复用项目 `mootdx_daily.tdx_client`。按任务 schema 仅存 close+amount（信号算法只需这两个）。
4. **D 持有人结构** 直爬东财 `fundf10.eastmoney.com/FundArchivesDatas.aspx?type=cyrjg&code=XXX`：走 `em_get`（1s 限流+重试防封）。返回 `var apidata={content:"<table>...",summary:"..."}` JS（非 JSON），正则提取 content 后 bs4+lxml 解析 HTML 表。510050 历史轨迹：2023-12-31 机构 68.22% -> 2024-06 80.26% -> 2024-12 84.31% -> 2025-06 88.69% -> 2025-12 91.46%（增持轨迹清晰）。半年报+年报，滞后 2-3 月。

**信号算法**：z-score（过去20日 share_change，shift(1) 不含当日）+ vol_ratio（过去5日 amount，shift(1) 不含当日）。share_surge/outflow/volume_surge 三类。折算日排除（|pct|>30% 且 vol<1.0 标 split_suspect 不触发）。季度校准（机构>85% ×1.5 / <60% ×0.7 写进 note）。强度分级（z≥5 极端 / ≥3 显著 / ≥2 轻度）。

**存储隔离**：独立 db + fcntl.flock 进程互斥（macOS 用 fcntl 非 flock 命令，参考 with_lock.py）。

**export 双版同步**：
- `data/etf_national_team.json`（12 只 ETF 近 60 日份额+成交额+信号）
- `data/etf_national_team_quarterly.json`（机构占比历史）
- web API：`/api/etf-national-team` + `/api/etf-national-team/quarterly`
- `static-site/export.py` 加 `export_etf_national_team()` + `export_etf_national_team_quarterly()`，main() 里 write_json

**CLI**：`backfill --start 20230101` / `daily` / `signals` / `holders` / `export`。

### 关键决策
1. **C fetcher 换源 mootdx**：任务原指定 `fund_etf_hist_em`（push2his），实测当天 IP 封。baostock 不支持 ETF（返 0 行）。mootdx 是唯一可用源（项目已有完整基建）。文档已注明换源。
2. **独立 db**：与 sentiment.db 隔离，采集异常不影响看板（参考 stock_daily.py）。
3. **etf_daily 不存 open/high/low**：任务 schema 只要 close/amount/fund_share/share_change，信号算法也只需这些。mootdx 拉的 open/high/low 在内存中但不入库（_upsert_daily fields 参数控制）。
4. **份额单位统一为份**：SSE/SZSE 返回份（510050 ~5.86e10），持有人表 total_share 用亿份（东财原样）。export JSON 加 fund_share_yi 字段（份转亿份）便于前端展示。
5. **159845 代码核实**：子 agent 探测误报"A50ETF"，实测 fund_scale_daily_szse 返回"中证1000ETF"（任务清单正确）。

### 测试结果
- etf_daily: 10224 行（12只ETF × 852交易日，20230103~20260713）
- etf_signal: 881 条（share_surge 345 / share_outflow 160 / volume_surge 375 / split_suspect 1）
- etf_holder_quarterly: 284 期（510050 43期 ~ 588050 12期，新ETF历史短）
- backfill 耗时 1282s（21min）：OHLC 12min（tdx_client 每只重新选服务器，已优化 client 复用）+ SSE 6min（852交易日×0.6s）+ 其他
- daily 增量 65s（client 复用优化后，12只ETF 一次选服务器）

### 验证：2023 汇金增持期信号
Q4 2023（20231001-20231231）共 59 条信号，准确捕捉 2023-10-23 汇金宣布增持 ETF：
- 510300（沪深300华泰柏瑞）：10/23 份额+9.9亿 倍量2.1 z=4.62 显著异动 机构90%
- 510310（沪深300易方达）：10/23 份额+4.3亿 z=7.47 极端异动；10/24 +13.8亿 z=13.24 极端异动 机构98%
- 159919（沪深300嘉实）：10/24 份额+3.8亿 z=9.00 极端异动 机构97%
- 510050（上证50）：11/17 份额+12.1亿 z=4.19 显著异动 机构91%
510050 机构占比轨迹：2023H1 65.84% -> 2023年报 68.22% -> 2024H1 80.26% -> 2024年报 84.31% -> 2025H1 88.69% -> 2025年报 91.46%（持续增持，总份额 226亿->566亿）。

### daily 增量验证
`python -m app.collector.etf_national_team daily` 65s 完成：ohlc=72 sse=42 szse=25 signals=881。client 复用优化生效（原 backfill 每只ETF 1min选服务器，daily 一次选服务器拉12只）。无报错。

### 已知小问题
- ResourceWarning：fcntl.flock 锁文件 fd 未显式关闭（进程退出时 GC 释放，不影响功能）；tdxpy socket 未关闭（mootdx 库 bug）。两者均不影响数据正确性。

---

## §15 策略实验室 C1 排查诊断 + BB_upper_revert 不融生产决策（2026-07-14）

### 背景
C1×D1 生产组合在上证指数全仓模式 -31.2%（见 TASKS.md `## 交接状态（2026-07-11 续3/续4）`），需排查是 C1 买点失效还是 D1 卖点问题；同时评估 BB_upper_revert 是否值得融入生产替代/互补 D1 卖点。本轮诊断**无代码改动**，仅落决策进项目文件（避免只存 memory 丢失）。

### C1_RSI30 配对实战排查结论

**C1 买点未失效**（244 资产 = 13 指数 + 31 行业 + 200 抽样个股，近 3 年，60 日 horizon）：
- 盈亏比 PL = 1.68，均值 +5.26%，正期望
- C1 单边统计达标≠配对实战赚钱，但 C1 单边本身没问题

**C1×D1 全仓 -31.2% 根因三要素**：
1. 纯 D1 卖点盈亏比 PL<1（0.69-0.94，赚小亏大）：D1 本就是「最不坏非好方案」，胜率≈50% 接近随机（见 REQUIREMENTS §7.2 / BUG-F 修复）
2. 全仓进出无止损：单次大亏吃掉多次小盈
3. 2005 年后 D1 胜率从 45% 滑到 30%：市场结构变化致 D1 触发点变差

**fixed_10k 模式扭亏为盈**：靠 10% 仓位分批建仓，C1×D1 由 -31.2% 翻为 +1.2%。说明问题在仓位非买点。

**各指数表现分化**（全仓全史）：

| 类型 | 指数 | 全仓收益 |
|------|------|---------|
| 大盘股（亏） | 上证综指 / 沪深300 / 上证50 | 全亏 |
| 中小盘（赚） | 中证500 | +131% |
| 成长（赚） | 创业板 | +74% |
| 小盘（赚） | 北证50 | +167% |

→ 大盘股长牛中 D1 频繁误杀（赚小亏大），中小盘趋势性更强 D1 能锁利。

### BB_upper_revert 决策数据

**回测对比**（作卖点配对，PL = 盈亏比）：

| 卖策略 | PL 范围 | 全仓配对收益 |
|--------|---------|-------------|
| D1_high20_drop5（现生产） | 0.69-0.94 | -31.2% |
| BB_upper_revert（候选） | 0.64-0.90 | -70.5% |

BB_upper_revert 比 D1 更差（PL 更低 + 全仓亏更多 2.3×）。作卖点不融生产。

**决策**：
- 不融入生产 `signals.py`，只留在策略实验室（`lab.js` 前端实时算 BB+信号，紫标 experimental 保留展示）
- 原 08 候选 C 触发条件「D1 实盘连续 2 季度 10 日胜率<45% 则启用 BB_upper_revert 互补」作废（替代品更差，互补无意义）
- BB 作买点（BB_lower_revert / B1）已在生产 `signals.py`（2026-07-05 上线，signal='buy_aux'），不受本次决策影响

### 相关文件
- 生产卖点：`app/compute/signals.py` `D1_high20_drop5`（不动，保留最不坏方案）
- 生产买点：`app/compute/signals.py` `C1_RSI30`（signal='buy'）+ `BB_lower_revert`（signal='buy_aux'，不动）
- 实验室卖点：`web/lab.js` `computeBBLab()` BB_upper_revert（保留，前端实时算不落库）
- 回测数据：`lab_simulate.json`（64 组配对×2 模式）/ `lab_backtest.json`（22 策略×5 窗口×4 horizon）
- 决策记录：TASKS.md `## 交接状态（2026-07-14，策略实验室 C1 排查诊断 + BB_upper_revert 不融生产决策）`

## §16 收盘分析领跌 + 数据时效提示 + collect_health 修复 + 分时图/角标/数据push 一揽子（2026-07-13/14）

### 背景
延续 §14/§15。本轮聚焦分时图实时化、角标体系、数据时效提示、数据 push 链路、收盘分析对称化。**多处改动此前只在对话上下文/memory，未落文件，本次补记**（用户明确要求：重要状态落 NOTES/TASKS commit，不能只存 memory）。

### 已完成（已 commit）
1. **分时图嵌入指数卡内部**（d8afc74）：从"另起一行"改为嵌入 spark-cell 内部，11 只指数 11 个分时图一一对应，手机端上证指数卡和分时卡同屏可对照。盘中默认展开、盘后默认隐藏，切换按钮。前端 3 分钟动态拉取腾讯分时 API（一次返回全天 240 个 1 分钟点），不依赖后端采集。
2. **min.js 重建同步**（a610548）：d8afc74 改 app.js 后 min.js 是旧版（spark-intraday 计数 0）致分时图无数据，重跑 build_min.py 强制同步。**教训**：每次改 app.js 后必须 grep min.js 字面量计数验证同步。
3. **数据 push 固定 main**（92271d7）：intraday_snapshot.sh 的 git push 不指定分支，push 到当前 checkout 的 feat 分支，公网停 13:05。改 worktree 方案：detached HEAD @ origin/main，cp 数据，push HEAD:main，trap cleanup 清理。数据直接推 main 触发 Pages/Workers 部署。
4. **大盘 tab 走势卡加右上角角标**（3d07f9d）：A股/港股/全球走势大卡复用 addCardTimeBadge 标注盘中/收盘状态。
5. **backfill 美股补采阈值 5天->3天**（2d01476）：`(today_d - last_d).days > 5` 把正常 T+1 当不缺跳过，美股停 7-10。改 >3 覆盖跨周末。
6. **分时图腾讯 API 域名修正**（321c467）：fetchTencentMinute 用 `web.ifzq.gtimgs.cn`（带 s 是 NXDOMAIN），fetch DNS 失败触发降级"实时拉取失败·显示快照15:35"。改 `gtimg.cn`（不带 s）。**教训**：agent 报告结论要逐字落实，阶段1实施 agent 仍用错域名。
7. **热力图近5日空修复**（2679328）：3 bug 叠加--close=NULL 致 pct_5d 永远 None + snap 硬编码 None + maybe_override_heatmap REPLACE 清空。修复：close=NULL 时用近5日 pct_change 累乘 fallback + MERGE 保留 DB pct_5d + 修硬编码。
8. **角标体系**（664dfef/4aa317c/399d395/504117a）：4 态（盘中绿.intraday/午休黄.lunch/待收盘灰.pending/收盘主题色.closed）+ 滞后分级（基于 prev_trading_day）+ 大卡右上角小卡右下角（两害取其轻避免盖标题）+ 半透明毛玻璃浮动 + 删 padding-right（曾挤标题错位）。
9. **KPI 卡去第三行日期**（cffcddb）：角标已含日期，第三行日期冗余且被角标压。
10. **收盘分析横幅文案**（76506b4）："盘中实时小结"误导（30分钟采集不算实时），改"盘中动态小结·更新于HH:MM"。
11. **去省略号改截取**：card-value 不要 ellipsis，能显示多少显示多少。
12. **ECharts 线色跟随主题**（2cb2aab）：轴线/网格/tooltip/布林轨道改读 CSS 变量，主题切换重绘。
13. **收盘分析横幅+历史弹窗 chips 流式排版**（ef53e14）/ **H5 顶部与 PC 统一**（d265955）/ **模拟回测 iframe 跟随父页面皮肤**（7485005，URL hash+postMessage 双保险）/ **采集时间ℹ️图标+数据更新规则 modal**（eadcf20）。

### 进行中（已派 agent，后台跑）
- **D 收盘分析加领跌**（agent a79b60f141ff47ea6）：`app/compute/market_summary.py` 加 `bottom_industries`（L279-298 同款 SQL 但 `ORDER BY pct_change ASC LIMIT 3`，L373 纳入 summary，L388 BRIEF_FIELDS 白名单）+ 双版 `app.js` 的 `renderSummaryChips`/`renderIntradayChips` 加 ❄领跌行（对称 🔥领涨，盘中 snap.industries 升序取 bottom3 否则 s.bottom_industries）+ build_min + push feat + merge main。历史弹窗复用 `renderSummaryChips` 自动同步，数据全在 snap.industries 不用额外采集。
- **B collect_health 误报修复**（agent a6f9242b59516e40b）：`app/main.py:313-338` + `static-site/export.py:330-354` 的 collect_health 直接用 backfill 校验日志（`_hrows`）判 level，backfill 在 snap 采集前跑、陈旧，致"指数今日数据缺失：新浪主源未找到，baostock+腾讯补采亦失败"误报（实际 snap.indices 已采到 7-14 15:35 sh000001 pct=1.36）。修复：对指数缺失类 item 复核 snap.indices/index_daily 实际数据，有则移除/降级。纯 .py 不碰 app.js。

### 排队（等 D 完成 app.js 空闲后合并派，避免 build_min/push 撞车）
- **A 数据时效提示 app.js JS**：接着 style.css 半成品（角标三档 `.t1`/`.t1-stale`/`.t1-severe` + 顶部健康横幅 `.data-health-banner` CSS 已就绪但未提交，见 `git diff web/style.css`）。JS 待做：`getCardTimeBadge` 三档分级（📅T+1正常灰/⚠滞后黄/🚨异常红，基于 prev_trading_day 判断滞后天数）+ 顶部全局健康横幅渲染（汇总各数据源最新状态，有滞后整体加黄边严重加红边，可折叠）。数据来源待设计（基于 collect_health + 各卡片 dataDate）。
- **C 卡片文案对齐**：`.card.kpi .card-value` 改 flex 布局，数值左对齐 + tag（偏热/缩量上涨等）固定右侧，避让右下角角标。解决 0.94x 和缩量上涨未对齐、66.1 和偏热未对齐等。

### 关键技术点
- **双版同步铁律**：web/(/api/) + static-site/(./data/) 改动逐字一致除数据源 URL。
- **腾讯分时 API**：域名 `web.ifzq.gtimg.cn`（**不带 s**，带 s 是 NXDOMAIN），CORS `access-control-allow-origin: *`，返回全天 240 个 1 分钟点，格式 `"0930 3909.27 4306268 8109534289.50"`（HHMM 价格 成交量 成交额），qt 数组 [1]=名称 [3]=当前价 [4]=昨收。
- **角标 4 态**：盘中绿.intraday/午休黄.lunch/待收盘灰.pending/收盘主题色.closed。
- **prev_trading_day**：基于 akshare 交易日历，判断数据真滞后（正常 T+1 vs 异常滞后）。
- **数据 push worktree 方案**：detached HEAD @ origin/main，采集在主仓库（DB 持久化），commit+push 在 worktree。
- **build_min 验证**：改 app.js 后必须 `grep -c` min.js 字面量计数确认同步，否则前端不显示。
- **app.js 是热点文件**：多 agent 并行改 app.js 会撞 build_min/push，需串行或合并派。
