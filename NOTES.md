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
- **build_min 验证**：改 app.js 后必须 `grep -c` min.js 字面量计数确认同步，否则前端不显示。**注意 min.js 是单行文件，`grep -c` 按行算永远≤1 误导，改用 `grep -o '关键词' file | wc -l`**。
- **app.js 是热点文件**：多 agent 并行改 app.js 会撞 build_min/push，需串行或合并派。

## §17 工作模式强化 + 本轮（2026-07-14 新会话）状态（2026-07-14）

### 工作模式再强化（用户明确要求，2026-07-14）
- **调研/代码定位/分析问题也派子 agent**，不只派"实施"。主上下文不做 grep/Read/方案分析这些"调研活"——把"调研需求+定位代码+给方案"作为 agent 任务派出去，收结论后再派实施 agent。
- 主控只做三件事：①派发（含目标+约束+验收口径）②收总结 ③验证关键结论（逐字 grep 报告，**不信 agent 报告**，dot is not defined / min.js grep -c 教训）。
- **不问 yes/no**（"要我跑吗""要不要更新文档""要不要验"类自决），自行验收连轴转；只在真·方向分叉给选项。
- **不冲突就并行**派发，不串行等。app.js 改动串行（撞 build_min/push）；.py / 独立 HTML / 只读调研可并行。
- **重要状态/决策/方案落 NOTES.md/TASKS.md commit 进 git，不进 memory**（memory 只暂存会丢）。
- 核对 agent 看完成通知会丢，查 jsonl mtime（`stat -f "%Sm" .../tasks/<id>.output`）确认真实状态。

### §16 状态修正（D/B/A/C/E 实际全完成，§16 进行中/排队段已过时）
- **D 收盘分析加领跌** ✅ commit c28e466（market_summary.py 加 bottom_industries + 双版 app.js renderSummaryChips/renderIntradayChips 加❄领跌）
- **B collect_health 误报** ✅ commit 41c42df（复核 index_daily 当日 close，移除 backfill 陈旧误报，items 19->10）
- **A 数据时效** ✅ commit 1eef457（移除红点 _healthDotHtml + 健康横幅 renderDataHealthBanner 替代 + 北向停更30天规则 + CSS）
- **C 卡片文案对齐** ✅ commit 4c73aca（.card.kpi .card-value flex + cv-val/cv-tags span）
- **E spark 角标** ✅ commit 4c73aca（删 spark-date + addCardTimeBadge 复用 4 态 + .spark-cell position:relative）
- **hotfix dot is not defined** ✅ commit 2fafe2e（A 删 _healthDotHtml 漏删 _renderCollectTime 两处 ${dot}）

### 本轮（2026-07-14 新会话）已完成
| commit | 内容 |
|---|---|
| 81e6997 | 收盘小结+历史弹窗领涨领跌带💰资金净流入+name去SW前缀（B1：index_daily 加 net_inflow 字段 db.py migration ALTER + intraday_snapshot _backfill_industry_daily 反哺 net_inflow + market_summary top/bottom 带 net_inflow + name .replace("SW ","")。当日有💰；B1 前历史 net_inflow NULL 只显示涨跌幅）|
| f22018d | 全站 170 个 HTML 注入百度自动推送 JS（SEO 收录）+ 修 2 bug（split(':')[0] / getElementsByTagName("script")[0]，markdown 吞 [0]）+ simulate_trade.py 生成器模板同步（future 自带）。注意：.io 域名无法工信部备案，百度收录效果存疑，代码无害保留 |
| 9f38fa4 | spark 卡左下角补点位+涨跌点数（spark-foot `${_lastClose.toFixed(2)}` + `${_chgText}` 带色）。接手 spark agent 收尾：补 static-site/style.css 双版同步 + build_min + bump（agent 漏 commit/漏双版 style.css/通知丢了，查 jsonl mtime 发现）|

### 本轮续（2026-07-14）已完成
5 个进行中 agent 全部收口，3 commit + 3 诊断结论。

| commit | 内容 |
|---|---|
| 9346451 | 汪汪队ETF数据自动更新-新增20:07 launchd调度（scripts/plists/com.trade.etf-national-team.plist，复用现有plist模板，StartCalendarInterval 20:07，独立锁 data/etf_national_team.lock 不撞 update_all。SSE/SZSE ETF份额18:00-20:00发布，20:07跑当晚出信号不再滞后。launchctl已加载exit 0。根治 etf_nt 采集不在任何调度致停7-13问题） |
| f316153 | 国家队合计层图1（合计持仓市值趋势）+图2（份额合计趋势）加共振信号 markPoint pin（进N/出N/量N）。方案A聚合单只信号：遍历 data.etfs[].daily[].signals，某日≥N只ETF同出信号即合计层标pin。阈值 THR={surge:2,outflow:2,volume:3}（进/出≥2只，量≥3只放量更常见故更严）。share_surge->"进N"红#e6492e / share_outflow->"出N"绿#2e8b57 / volume_surge->"量N"橙#ff9800。不改 lineChart 签名（10+处调用回归风险），图1/图2改用 mkCard+setOption 直接画+markPoint pin。value含共振只数N不依赖hover。双版 app.js renderNationalTeamTotalPanel 逐字同步。无数据缺口（signals字段链路完整，不改export.py/采集/DB） |
| 2a29984 | sim页（模拟回测 trade_sim_*.html）主题初始化对齐主看板。根因：sim页主题JS只读 location.hash 不读 localStorage，直接访问（非iframe，如行业图表按钮弹窗）时无hash回退 :root 浅色，浅色下 --bg-best=#fff8e1 正好等于旧硬编码值致背景色看不出变化。修复：simulate_trade.py L1183-1194 主题JS改三级优先级（hash优先->localStorage->首次默认redgold），与 web/index.html L42-49 对齐。重生成 83+83=166 个 trade_sim HTML（28个 sw_801* 数据None失败 + 6个 g.* 不在 name_map，用Python原地补丁：56个 sw_801* 替换旧JS块 + 12个 g.* 注入新主题JS块，g.* 原完全无主题支持）。验证：trade-theme 83+83，redgold 83+83，旧块残留0，花括号无残留，push.js仍170。这同时修复了之前 13dee00 的策略表格背景色未生效问题（根因是子页主题不应用，非背景色代码问题） |

#### 诊断结论（无 commit，报告型）
- **汪汪队7-13停更根因**：etf_nt 采集不在任何调度（update_all 4 pipeline / runner.py steps / launchd / crontab 都没有），只能手动CLI跑。已由 9346451 根治（新增20:07 launchd）。
- **两融7-13**：已由之前 0f86acc 加 backfill 20:00 补采步骤（series 补采覆盖两融等晚发布指标，不再漏采）。
- **合计信号调研（a5530b32）**：方案A聚合单只信号推荐，不改 lineChart 改用 mkCard+setOption，无数据缺口。已由 f316153 实施。

#### 进行中 agent 状态收口
| agent | 任务 | 结果 |
|---|---|---|
| afe0e4196 | 数据时效栏手机端默认折叠+修跳动 | ✅ 代码已在 321c467 落地（dhb-collapsed localStorage + matchMedia ≤768px 默认折叠 + .dhb-chips max-height 过渡修跳动） |
| a21b4f8c | 策略表格背景色跟主题 | ✅ 13dee00 初版（cmp_cell 改 var(--bg-best/worst)+4套主题变量）+ 2a29984 根因修复（sim页主题JS三级优先级，子页主题不应用致背景色不生效） |
| a0545d65 | 汪汪队7-13未更新诊断+补采 | ✅ 诊断：etf_nt 不在任何调度 -> 9346451 根治（20:07 launchd） |
| a7fed704 | 两融7-13诊断 | ✅ 诊断：akshare 两融晚发布 -> 0f86acc 已修（backfill 20:00 加 series 补采） |
| a5530b32 | 合计层加进/出/量信号方案调研 | ✅ 方案A推荐 -> f316153 实施（共振信号 markPoint pin） |

### 关键技术点（本轮续补充）
- **sim页主题JS三级优先级**：hash（iframe传入）-> localStorage -> 首次默认 redgold，与主看板 web/index.html L42-49 对齐。原 sim 页只读 hash 不读 localStorage，直接访问（非 iframe）时无 hash 回退浅色。
- **g.* trade_sim 页原完全无主题支持**：本次 2a29984 用 Python 原地补丁注入新主题 JS 块（12个 g.* 文件），sw_801* 系列 56 个文件替换旧 JS 块。
- **合计层共振信号**：方案A聚合单只 signals，THR={surge:2,outflow:2,volume:3}（进/出≥2只，量≥3只放量更常见故更严）。不改 lineChart 签名（10+处调用回归风险），图1/图2改用 mkCard+setOption 直接画+markPoint pin。value 含共振只数N不依赖 hover。
- **etf_nt launchd 20:07**：复用 scripts/plists/ 模板，独立锁 data/etf_national_team.lock 不撞 update_all。SSE/SZSE ETF份额18:00-20:00发布，20:07跑当晚出信号不再滞后。

### 关键约束补充
- **百度推送代码 bug**：官方原版带 `[0]`（`split(':')[0]` + `getElementsByTagName("script")[0]`），markdown 渲染吞 `[0]` 致看起来漏。push.js 源码是 1×1 img 打 sp0.baidu.com 上报 URL。
- **index_daily.net_inflow**：db.py `_migrate` 用 PRAGMA table_info 检查列存在性+ALTER TABLE ADD COLUMN 兼容旧 DB。
- **数据时效栏折叠**：localStorage `dhb-collapsed` 记忆，首次手机端默认折叠 PC 默认展开。

## §18 排队4/5 + 性能优化收口（2026-07-14 续，2 commit）

> 排队-4/5 共 12 项 + 性能优化可独立做项，逐字 grep 验收 + 收尾。2 commit + TASKS.md 回填。已推 feat/iframe-theme-follow。

### 排队-4/5 调研结论（关键发现）
- **12 项中 11 项前序会话已完成**（6 commit：4183fa3/5de17b3/669b003/ad88fb3/af46512/11c526d，2026-07-13 21:54-22:09 闭环）。`EVAL_REPORT_2026-07-13.md` 是修复前基线快照，TASKS.md L40 未回填状态仍标"待办"致重复调研。
- **教训**：开工先 `git log --oneline --since=2026-07-13 -- web/lab.js web/app.js app/compute/signal_stats.py` 看最近 commit，不只读 TASKS.md/EVAL_REPORT。
- **X6 是唯一未收尾项**：前端已 100% 迁移新字段（`f.year_count`/`f.total_count`/`f.monthly_avg`/`f.active_months`），后端 `compute_global_freq` 仍双发 year/total + year_count/total_count。

### 已完成验收（11 项，逐字 grep）
| 项 | 证据 |
|---|---|
| L1 买卖信号弹窗下全历史 | `web/lab.js:2345` apiRange 映射 y1->3y/y3->5y/y5->5y/y10/all->all |
| L2 实验图表窗口联动 | `web/lab.js:1460` state.labWinSync + 🔗同步按钮 |
| L3 规则弹窗频率刷新 | `dataset.loaded` grep=0（注：EVAL_REPORT 称"lab.js:726"是旧行号，实际在 `app.js:907` initRuleButton）|
| L4 推荐榜超时取消+重试 | `web/lab.js:2166` AbortController 15s + lab-full-retry 按钮 |
| O3 分享图overview缓存 | `web/app.js:4986` _OVERVIEW_TTL=5min + _overviewCache |
| M2 renderGlobal null守卫 | `web/app.js:314` empty-note + r.indices\|\|{} 兜底 |
| S2 月均年初虚高 | `signal_stats.py:127` active_months 除数（今年实际有信号月数并集）|
| I2 概念搜索 | `web/app.js:774` industrySearchBar 共用搜索条过滤 indices+concepts |
| I3 锚点scrollspy | `web/app.js:4529` IntersectionObserver rootMargin -15%/-70% |
| X2 _headers qr.js | `static-site/_headers:25` immutable，与 bump_asset_version.py ASSETS 对齐 |
| X3 版本号md5非mtime | `scripts/bump_asset_version.py:31` hashlib.md5 前8位（内容变则版本变）|

### X6 收尾（commit 368cd31）
- `app/compute/signal_stats.py`：init dict year/total -> year_count/total_count；累加 `freq[sig]["year_count"]`/`["total_count"]`；返回 dict 删 year/total 两行；docstring 删兼容期说明。共 5 处 Edit。
- 重生成 `static-site/data/signal_freq.json`：4 字段（monthly_avg/year_count/total_count/active_months），旧字段 grep=0。样例 buy{monthly_avg:23.33,year_count:140,total_count:4184,active_months:6}。
- 双版一致：动态 compute_global_freq() 输出与静态 JSON diff IDENTICAL（main.py/export.py 都委托该函数，改一处双版同步）。
- 前端无需改（已迁移）。

### 性能优化可独立做项（6 项，5 已完成 + P2-3 实施）
| 项 | 状态 | 证据 |
|---|---|---|
| P1-1 echarts defer | ✅ 前序完成 | `index.html:29` 双版均带 defer，app.min.js/lab.min.js 也 defer（顺序 echarts->app->lab 安全）|
| P1-2 resize debounce | ✅ 前序完成 | `app.js:29-32` clearTimeout+setTimeout(150) 遍历 charts.resize() |
| P1-4 app.js/lab.js minify | ✅ 前序完成 | `build_min.py` 用 `npx terser --compress --mangle`（真 minify 非合并）|
| P2-1 renderOverview并行 | ✅ 前序完成 | `app.js:2403` Promise.allSettled([ad_line,volume_ratio,new_high_low]) 失败各自降级 |
| P2-3 FastAPI缓存头 | ✅ 本轮实施 | commit 22da604，中间件版本化资源 immutable 其余 no-cache |
| P2-4 lab输入debounce | ✅ 前序完成 | `lab.js:2097-2102` clearTimeout+setTimeout(100) 只刷结果区不重建面板 |

### P2-3 FastAPI Cache-Control 中间件（commit 22da604）
- `app/main.py:30-50` `@app.middleware("http")`，位置 `app=FastAPI()` 之后、路由之前。
- `_VERSIONED_ASSETS` 6 项（style.css/app.min.js/lab.min.js/lab.css/qr.js/vendor/echarts.min.js）带 `?v=` -> `public,max-age=31536000,immutable`；其余 /static/ -> no-cache；/api/、/、/trade_sim、/og.png -> no-cache。
- 守卫 `if resp.headers.get("cache-control"): return resp` 不覆盖 / 路由自设头（line 1219）。
- 对齐 static-site/_headers（动态站 /api/* 对应静态站 /data/*）。TestClient 冒烟全过。
- 只改 app/main.py（23 insertions），不需 build_min/bump，不碰 static-site（走 _headers）。

### 性能优化剩余（需用户决策，本轮不做）
- **P0-1/P0-2（gzip/缓存头部署层）**：MaoziYun 服务器零压缩，echarts 1MB/行业全部 24MB 全裸传。需确认服务器可改性或接 Cloudflare。**单项最高收益**（弱网提速 3-5 倍）。
- P1-3/P1-5/P2-2/P2-5：靠 P0 或改动大，本轮不做。

### 两融 7-14 滞后补充诊断（前序 agent a7fed704，2026-07-14）
- **根因不是调度**（调度已由 0f86acc 根治，backfill_series_metrics 在 index_backfill.py:363，20:00/02:00 兜底补采 series 指标），而是 **SSE 源一次性异常延迟**：7-14 盘后 5.5 小时（到 20:35）仍未发布，轮询 24 次全返 max=7-13。stock_margin_sse + macro_china_market_margin_sh 双源均无 7-14。
- **实测 DB**（07-14）：a_fund_margin=20260713，但 a_qvix_300/a_div_yield/hk_south 均已补 20260714（同 20:00 backfill 采到，证 backfill_series_metrics 生效，仅 SSE 源没出）。
- **兜底**：02:00 backfill（index_backfill.py:434 main 调用）会重跑，SSE 一旦发布即采到+重算+推送。未来交易日 20:00/02:00 都兜底，不再系统性漏采。
- **区分**：两融是 SERIES_FUNCS（依赖 SSE 盘后发布，17:50 update_all 赶不上）；涨停/成交额是 intraday_snapshot（15:35 收盘后即有）。前者滞后是源发布晚非采集 bug。

### TASKS.md 回填
- L39 排队-4 标 ✅（commit ad88fb3 + apiRange 映射说明）。
- L40 排队-5 标 ✅ 全部完成（11 项 + 6 commit 清单 + 逐项证据，注明 EVAL_REPORT 是修复前基线快照）。

### A3 合计层共振信号阈值密度回算（agent a1906bea1，2026-07-14，只读分析）
- **结论：保持当前 {surge:2, outflow:2, volume:3} 不变**（数据支持，无需调参）。
- **频率**：当前阈值近1年 39 信号天 / 占16% / 周均0.80 / 月均3.37（理想一周1-3次的下沿，不密不疏）。
- **备选对比**（近1年243交易日）：{1,1,2}敏感=77天但单只不算共振语义错❌ / {2,2,2}量降=46天但volume_surge宽松信息量不足❌ / **{2,2,3}当前=39天✅** / {2,2,4}=39天与{2,2,3}无差异(volume≥3时通常已≥4) / {3,3,4}=19天砍一半漏小规模协同 / {4,4,5}=11天太疏。
- **关键发现**：volume 阈值 3→4 无差别（volume_surge 单条件宽松，触发时往往≥4只），量阈值不是瓶颈。surge/outflow 是三重条件(方向+z>2+vol_ratio>1.5)已很严格,2只共振是有效信号。
- **信号扎堆是特性非缺陷**：2026-01 连续8天出信号精确捕捉1月暴跌国家队流出,这是信号价值所在。
- **单只信号触发**：etf_national_team.py:681-768 compute_signals。surge(进)=share_change>0 AND z>2 AND vol_ratio>1.5；outflow(出)=share_change<0 AND z<-2 AND vol_ratio>1.5；volume(量)=vol_ratio>2。折算排除|share_change_pct|>30% AND vol_ratio<1.0。

### A3 衍生文案瑕疵（待修，排队）
- **bug**：web/app.js:2778,2793（图1 c1/图2 c2 termTip）写 `pin=≥" + THR.surge + "只宽基同步异动...进红/出绿/量橙`，用 THR.surge(=2)统一描述三种pin，但量pin实际阈值=THR.volume(=3)。当前阈值下量阈值文案错（说≥2实际≥3）。
- **修法**：termTip 文案改为分别说明 `进/出≥${THR.surge}只、量≥${THR.volume}只`。双版 app.js 同改 + build_min + bump。
- **排队**：A1 已完成(369f036)。串行在 B3/B5 之后（都改 app.js，避免 merge 冲突）。

### B2-B5 独立性调研（agent a4c370e8，2026-07-14，只读分析）
- **B3 全球轻量 JSON**：完全独立可立即做。static-site/data/global-all.json 3.1MB（indices 2.31MB + extras 0.87MB + extras_signals 0.1MB），信号弹窗(static-site/app.js:1072)拉全量只为取 extras/extras_signals/extras_stats。新导出 global-extras-all.json 只含4字段不含 indices(~1.0MB)，省 2.1MB(68%)。web/app.js:1023 已按 range 拉不需改（动态版无此问题）。export.py+5行 + app.js改1URL。**收益/改动比最高**。
- **B5 lab.js 懒加载**：完全独立纯前端。index.html:130 删 `<script defer lab.min.js>`，app.js renderTab(state.tab==="lab") 时 dynamic import loadScriptOnce()。省 88KB 首屏。需测 hash 直链 #lab 恢复（lab.js 末尾 IIFE 读 hash）。改动小2index.html删1行+2app.js加~15行。
- **B2 行业瘦身**：部分独立。industry-all 31文件24MB，每个 data 字段7 OHLC 只用3(close/pct_change/date)，width 8字段只用3。瘦身 24MB->10.4MB(57%)。但 tooltip 信息损失（宽度tooltip不显示涨停/跌停/炸板率/封板率/成交额），**需用户确认接受 UX 代价**。服务端预合并方案不可行（超 Cloudflare 25MB 限制，当初拆分正是为此）。gzip 能降到3.6MB(85%)，B1 搁置则 B2 独立收益57%仍可观但需确认 UX。
- **B4 trade_sim**：强依赖 B1，搁置合理。84文件46MB 已 iframe 按需，HTML 表格高度重复 gzip 压缩率80%(46MB->10MB)。独立方案A(class替inline style)省9.2MB(20%)但 gzip 后差异消失。方案B(JSON+客户端渲染)重构改动大。
- **实施排队**：B3/B5/文案瑕疵都碰 app.js 需串行。B3 先(a26f130aecd4f338c) -> B5 -> 文案瑕疵。B2 待用户确认 UX 代价再派。B4 随 B1 搁置。

### B3/B5/文案瑕疵 已完成（2026-07-14）
- **B3 全球轻量 JSON**（commit c556ae3）：信号弹窗 fetch global-all(3.1MB)改 global-extras-all(0.9MB)，省70%。export.py 复用循环内 data 变量导出4字段(extras/extras_signals/extras_stats/extras_strategy)不含 indices。web 动态版已按 range 拉无需改。
- **B5 lab.js 懒加载**（commit 4642735）：index.html 删 `<script defer lab.min.js>` 改 `<meta name="lab-asset-url" content="...?v=...">`，bump/main.py 既有正则自动注入版本号(零 Python 改)。app.js 加 loadLabScript() Promise 缓存，renderTab lab 分支 await loadLabScript()+renderSignalLab()。hash #lab 直链靠 lab.js 末尾 IIFE + onclick 守卫(lab 已 active 跳过 spurious click)协调。省 88KB 首屏。
- **pin 文案瑕疵**（commit 97c3585）：图1/图2 termTip 改 `进/出≥THR.surge只、量≥THR.volume只`(原用 THR.surge=2 统一描述,量实际≥3文案错)。
- **教训**：pin commit 误混入 static-site/data/etf_national_team*.json + signal_freq.json(export/build 重生成的站点数据)。内容有效(数据更新到7-14+signal_freq 仍4字段),但应单独 commit。**export 重生成的 static-site/data/ JSON 要单独 commit,别和功能改动混**。已 push 不 amend(force push 风险)。

### B2 折中方案调研 + 实施（agent a3091f39 调研 / a8b86fd7 实施，2026-07-14）
- **方案**：主文件瘦身保留 data 的 date/close/pct_change/**amount**(amount是成交额mini chart series数据非tooltip,前序a4c370e8漏这点)+ width 的 date/up_count/down_count。detail.json 只含 tooltip 字段:data 的 open/high/low + width 的 zt_count/dt_count/zb_count/seal_rate/amount。detail 不含 date(靠 index 对齐+length guard,省3MB)。
- **echarts tooltip 同步性约束**：formatter 同步函数不能 await fetch -> 用 IntersectionObserver 视口懒加载(rootMargin:300px 卡片进入视口即预取)。模块级 _indDetail Map 缓存。_indHasDetail(idx) 检测:动态版 idx 已含完整 width[0].zt_count -> 从 idx 填充缓存(无 fetch);静态版 fetch {iid}-detail.json。
- **改动量**：export.py ~15行(循环内同时导出瘦身主+detail) + 双版 app.js ~45行新增(缓存+3helper+IO)+~10行改(2 formatter)。
- **收益**：初始加载 24MB->13.86MB(省43%)，detail 按视口懒加载。tooltip 首次显示可能降级(显示"-")，rootMargin 提前预取缓解，动态版无此问题。
- **不碰**：app/main.py(动态版 /api/industry 单次返回完整无25MB限制)/concepts(无width)/采集。
- 实施 agent a8b86fd747be0089d 跑中。

## §19 两个数据层系统隐患（2026-07-14 发现）

### 隐患1：sentiment.db / etf_national_team.db 进 git 跟踪
- 现状：.gitignore 第10行注释"sentiment.db 45MB 进 git 供动态版运行"，git ls-files 确认 data/sentiment.db + data/etf_national_team.db 被跟踪
- **事故**：2026-07-14 线上采集时间停 13:32:14，根因是 7-13 晚 git checkout/merge 分支时 git 用旧版本 sentiment.db 覆盖了本地 DB，把 7-14 18:04 update_all 跑出的收盘快照（intraday_snapshot 表）丢回 13:05:04 盘中快照
- 危害：45MB 二进制进版本库 = 反模式。每次切分支都可能污染 DB（本次事故根因）；仓库 .git 持续膨胀；merge 易冲突
- 约束：注释说"供动态版运行"——maozi.io 动态版可能依赖从 git 拉 sentiment.db 启动。改前必须先确认动态版部署机制（服务器 DB 来源：git pull？还是服务器本地独立 DB？）
- 待办：调研 maozi.io 部署机制后，方案二选一：(a)DB 不进 git + 服务器本地独立采集维护 DB；(b)保留进 git 但加 pre-commit hook 防误推/checkout 时 git stash 保护 DB
- 临时规避：切分支时若 git 报 "local changes would be overwritten"，用 `git stash push data/sentiment.db` 保护，切完 `git stash pop`，**绝不能 git restore / git checkout -- data/sentiment.db**（会再次污染）

### 隐患2：net_inflow 列缺失致 export.py 中断
- 现象：export.py 在 summary.json 步骤中断，报 `index_daily has no column named net_inflow`
- 根因：commit 81e6997 引入 app/compute/market_summary.py 读取 index_daily.net_inflow 列，但旧 DB 用旧 schema 建表缺该列，且 app/db.py 的 init_db._migrate() 从未被某些采集流程调用（直接 sqlite3.connect 绕过 migrate）
- 影响：export 中断 = static-site/data 下 summary.json / summary_history.json / signal_freq.json / rotation.json / new_high_low.json / ma_alignment.json 等多个 JSON 不生成 = 线上对应模块无数据/旧数据
- 临时修复（2026-07-14 已做）：跑 `.venv/bin/python -c "from app.db import init_db; init_db()"` 执行 ALTER TABLE 加 net_inflow 列，本地 DB schema 修复。修复后 export 198 个 JSON 完整生成（125.5MB）
- **已根治**（commit 782d4d5 + 2026-07-17 清理）：782d4d5 将所有 `sqlite3.connect(SENTIMENT_DB_PATH/DB)` 直连改为 `app.db.get_conn()`（含 _migrate），涉及 7 处：industry_width._get_sentiment_conn、width_history(3处)、cleanup_d3d2(1处)、scripts/check_signals、scripts/simulate_trade、scripts/lab/lab_matrix、scripts/lab/lab_simulate。2026-07-17 复核确认：全项目无剩余 sentiment.db 直连（剩余 sqlite3.connect 均连 stock_daily.db/etf_national_team.db 不同库），并清理 3 文件遗留死代码 SENTIMENT_DB_PATH 变量+加注释防复用。net_inflow 列在 index_daily/board_daily schema 中确认存在
- 关联文件：app/db.py（_migrate 逻辑已有，只需确保被调用）、app/compute/market_summary.py（读 net_inflow）、static-site/export.py（被中断处）

## §20 拼色pin放大 + 收盘分析H5布局重构 + 工作模式教训（2026-07-15）

### 拼色pin气泡放大+比例修正
- 比例：`_ntMultiColor` 末段固定 20%（底部尖端窄，均分会被挤没看不见）。2段 40:60 / 3段 26.6:26.6:46.6。commit bad8b94
- 气泡放大：多信号 markPoint `symbolSize` 52->64、`fontSize` 9->11（和单信号一致）、新增 `lineHeight:13`。提取 `multiLabel` 变量复用。commit 2d4737b

### 收盘分析 H5 布局重构（返工3次，复盘教训）
- 需求：首行「日期+情绪」左、「收盘小结/更多」右；tags 第二行；chips 第三行。PC 保持内联不变。
- b2e9645：`summary-title` 内层拆 `summary-title-text`+`summary-title-tags`，@media 768 块加 `summary-title-tags{flex-basis:100%}`。但 `.summary-title{flex:1 1 auto}` 占满第一行把 meta 挤第三行。
- 95b0c32：@media 内 `.summary-title{display:contents}` 让子元素提升为 summary-top 的 flex item + `space-between`。但 DOM 顺序 text->tags->meta，tags `flex:0 0 100%` 占第二行把 meta 顶到第三行（用户实测「贪婪61一行、收盘小结更多一行」）。
- a4a48cc（最终修复）：加 `order:1/2/3` 把渲染顺序改 text->meta->tags。text+meta 首行左右分布，tags 第二行。
- **教训**：第一次派 agent 前没想透 DOM 顺序与 flex item 提升后的渲染顺序，导致返工 3 次。派 agent 前主控应先在思考块把 CSS 布局原理跑通（display:contents 后谁是 flex item + order 需求），一次给对方案。

### 工作模式教训（已落 CLAUDE.md 第2条 + memory）
- 违规：派子 agent 修 H5 order 时用同步 `Agent` 调用（未加 `run_in_background:true`），主控卡 ing 状态 12分58秒，期间用户多次发消息不响应。
- 根因：CLAUDE.md 第2条本就写「后台 run_in_background」，执行没遵守。
- 修复：CLAUDE.md 第2条强化（commit e28e967）——必须 `run_in_background:true`，派完立即返回监工待命，同步调用=违规。memory 新增 `agent-dispatch-then-standby.md`。

### 融合信号卡片状态修复（方案已定，待实施）
- 现状：策略实验室「候选买点」区 F_B1_RSI40 / F_B1_rebound2pct 标 `status:"live"`（已上线生产），但实际是 per-index 的 buy_aux 辅买点增强（signals.py:449-468，18个指数配置），非全局融合信号生产实现。zone/status 矛盾 + note 过时。
- 方案（用户已确认）：新增 `partial`（部分上线，琥珀色标签）状态，两卡 live->partial；note 更新实际指数名单（rsi_cross_40 10个 / close_above_bl_2pct 8个，从 indicators.yaml grep）；融合卡加 hover 提示「阶段一仅展示，详情页待阶段二」。双版 lab.js + style.css。
- F_D1_MA_death（候选卖点 experimental）标对——后端无 MA5/20 死叉过滤，确实没上线。

## §21 HTTP 压缩调研结论（2026-07-15）

### 背景
「市场温度看板」3 站点压缩现状实测（curl 验证，2026-07-15），推翻 §18 的盲点（原以为 maozi.io 走用户 Cloudflare 账号可后台开 Brotli）。

### 实测三站点压缩现状
| 站点 | 压缩 | 缓存头 | 国内可达 | 备注 |
|---|---|---|---|---|
| maozi.io (tdsignal-ujpzw01zm.maozi.io) | ❌ 零压缩 | 全 max-age=1200 | ✅ | 走 Cloudflare CDN 但回源帽子云(MaoziYun/3.17.0)，_headers 不解析 |
| GitHub Pages (xp13465.github.io/trade-data-signal) | ✅ gzip 全类型(含 JSON，省 67-83%) | 固定 max-age=600 | ✅ | 不支持 br，不支持 _headers |
| Cloudflare Workers (trade-data-signal.sugas13465.workers.dev) | ✅ gzip+br，支持 _headers | 可自定义 | ❌ 国内墙 | workers.dev DNS 污染+IP 墙，不可达 |

### 关键发现（推翻 §18 盲点）
- maozi.io 响应头有 cf-ray/cf-cache-status，看似走 Cloudflare，但实测 DNS：子域 CNAME cname.maozi-dns.com -> 帽子云 IP 82.40.32.125，主域 NS 在华为云(huaweicloud-dns)
- 响应头的 cf-ray 是**帽子云后端自带的 Cloudflare**（帽子云自己用 CF 做 CDN 回源），**不是用户 CF 账号**——用户无权在那个 CF 后台开压缩规则
- 所以「在 Cloudflare 后台给 maozi.io 开 Brotli」不成立
- GitHub Pages 已自动 gzip 现成，但用户主访 maozi.io（零压缩），要享受 Pages 压缩得切流量
- 豆包建议的「方案 A 预压缩 .gz + _headers 配 Content-Encoding」在帽子云不可行（帽子云不解析 _headers，免费版无 gzip_static）

### 待定方案（用户 2026-07-15 决策：暂不动压缩，先上 UI，压缩搁置后续定）
3 条可行路：
1. **切主流量到 GitHub Pages**：零成本立即享受 gzip，但 Pages 域名不如 maozi.io 专业，max-age=600 短
2. **提帽子云工单开 nginx gzip**：免费版可能拒，给话术：申请服务端动态 gzip，html/css/js/json/svg，等级6，>1KB
3. **maozi 子域接入用户自己 CF 账号(sugas13465)开 Brotli**：需 CF 后台加自定义域名+压缩规则，最彻底，国内可达性优于 workers.dev

## §22 换手率分布图表数据停滞修复（2026-07-15）

### 问题
大盘信号→A股「换手率分布分位数」「换手率>5%家数占比」图表角标滞留在 7/6（滞后 9 天）。

### 根因
- `a_turnover_mean/median/p90/p10/gt5_pct`（daily_metric，BaoStock 全市场换手率分布）从未被任何 pipeline 自动调用——`cleanup_d3d2 turnover` 只手动跑过（末次 7/6）。
- `baostock_daily`（填 baostock_daily_raw）runner.py:235 默认跳过（需 `RUN_BAOSTOCK=1`），stock_daily pipeline 只跑东财 stock_daily 不跑 baostock。
- `cleanup_d3d2.py` `END_DATE` 硬编码 `20260706`——即使跑了也不采新数据。
- 采集链：`baostock_daily`（baostock→baostock_daily_raw）→ `cleanup_d3d2 turnover`（算分布→daily_metric）→ `/api/a-stock` & export.py（读 daily_metric→a-stock-*.json）。两步都没每日跑。

### 修复（commit b810861）
- `cleanup_d3d2.py`：`END_DATE` 改动态（今天）；`compute_turnover_dist` 增量模式（从 daily_metric 末尾+1，避免每次重算 1500 万行）；`MIN_STOCKS_PER_DAY=4000` 跳部分采集日（如 7/9 仅 2281 只，分布失真）；`--full` 标志强制全量。
- `runner.py`：+step 12 `turnover`（baostock 增量[仅 `RUN_BAOSTOCK=1`]+cleanup_d3d2）。
- `pipeline.sh`：+`turnover` pipeline（STEPS=turnover, DO_EXPORT=1, DO_PUSH=1, 设 `RUN_BAOSTOCK=1`）。
- `update_all.sh`：+turnover 前台 pipeline（wait，caffeinate 覆盖防休眠，通知含 RC_TURNOVER）。不阻塞 core——core 先抢 deploy 锁上线，turnover 采完排号 deploy。

### 数据修复（commit b27287e）
- 快赢：cleanup 从现有 baostock_daily_raw(7/9) 算 7/7-7/8（7/9 部分采集跳过）。
- backfill：`baostock_daily update` 增量补 7/9-7/15（5071 ok/1 fail，+23071 行，~25min）。
- 再 cleanup：5 天全部入库，a_turnover 5 指标 MAX=20260715。deploy regen a-stock-*.json 上线。

### 注意
- baostock 增量 update 5072 codes × 0.1s throttle ≈ 10-25min（远小于 10 年全量 9h）。`RUN_BAOSTOCK=1` 只 turnover pipeline 设，collect.sh（scheduler 全 steps）跑 turnover 时 baostock 子步仍跳过（cleanup 照跑，快）。
- 部分采集日（< 4000 只）自动跳过，待 baostock 补全后下次重跑补回（增量起点 = daily_metric 末尾，未入库的部分日始终在重算范围内）。

## §23 情绪温度布局统一 + 跨市场综合评分组成因子 + 计划任务加固（2026-07-15）

### 今日上线功能（commit 清单）
| commit | 功能 |
|--------|------|
| 15fe67f | qvix(1000)停采方案C（修日志标签bug+保持采集+前端⏸停更）+中文名中国波指300/1000 |
| 283d2d5/ae8c291 | 策略实验室左右2栏（3:7）+自白移左栏 |
| 705c91f | 图表角标收盘后滞后警示（📍收盘->3档判定⚠/🚨） |
| d1038e7 | 实验室自白黄块移左栏 |
| f358851 | 国家队3图动态1行折叠+角标+末日份额NULL处理 |
| 3684013/ad490eb/9df23c5 | ETF弹窗5图折叠+弹窗KPI末日NULL+默认展开 |
| b4d059b | 份额估算文案加时点"明晚20:07后" |
| a7ac797 | 情绪温度期货4图套indices-grid+角标 |
| 7aea569 | 期货表格卡样式统一（药丸/角标/12px间距font-size） |
| c3e235f+022b317 | **情绪温度布局统一+跨市场综合评分组成因子** |
| 67c94d7 | ETF弹窗3图角标+持有人结构半年报标注 |
| d480f70 | P1/P2/P3计划任务加固 |

### 跨市场综合评分组成因子（重点，commit c3e235f+022b317）
- **根因**：cross.py store() 硬编码 components=None；前端 appendComponentsBlock 检查 `if(!last.components)return` 提前退出，故跨市场综合评分卡不显示组成因子
- **后端**：cross.py compute() 改返回 (score, components_df)，components_df 按指标 config group 分9组（a_width/a_fund/a_sentiment/hk/global/lhb/unlock/ipo/cov）算归一化滚动百分位均值；store() 写每日期 components JSON 到 score_daily.components 列。更新 runner.py:17 + intraday_snapshot.py:779 两处调用方
- **前端**：_COMP_NAMES 加9组中文标签；renderSentiment 的 cardGrid cross_market 卡(@4070)调 appendComponentsBlock 展示"组成因子"chips
- **全自动链路**（已验证）：runner.py:17 `cross.compute()+store(components)` ← 被5路径调用（update_all/intraday/backfill/lhb/rzhb）-> export.py:105 `SELECT components` 导出 sentiment-*.json -> intraday:813 `_export_affected_json()` dump -> deploy.sh/各backfill `git add static-site/data/` push。**下次定时采集后 components 自动更新上线，不依赖手动 deploy**
- **踩坑**：agent 改代码+重算DB+重导本地JSON+commit代码push，但**没跑deploy.sh推数据上线**，线上 sentiment-all.json 仍 `components:None`。逐字验收 curl 线上才发现，补跑 deploy.sh（commit 022b317）才生效。教训见下「踩坑1」

### ETF弹窗3图角标 + 持有人结构半年报标注（commit 67c94d7）
- 份额趋势/收盘价成交额：addCardTimeBadge（daily T+1 规则）
- 持有人结构：自定义📅半年报角标（**不走 getCardTimeBadge**，因>30天会误判⏸停更）+ termTip"每半年披露一次（报告期6/30、12/31），基金年报/半年报发布后2-3月更新。最新至YYYY-MM-DD"
- **根因**：数据源东财 FundArchives（type=cyrjg），半年报+年报披露，滞后2-3月。停 2025-12-31 **正常**（下一期2026半年报6/30，预计8-9月发布），非停更

### 计划任务自动化检查结论（2026-07-15）
7个 launchd 任务（无 crontab），全 LastExitStatus=0，时序错开无硬冲突，互斥完善：

| 任务 | 触发 | 耗时 | 自身锁 | deploy锁 | caffeinate |
|------|------|------|--------|----------|------------|
| intraday-snapshot | 9:35-15:35×11 | ~12s | ✅ | ✅ | ❌->P2修 |
| backfill-evening | 16:35/02:00/20:00 | ~3min | ❌ | ✅ | ✅ |
| update-all | 17:50 | ~16min | ✅ | ✅ | ✅ |
| lhb-backfill | 18:30 | 秒级 | ✅ | ✅ | ✅ |
| futures-backfill | 20:05 | 秒级 | ✅ | ✅ | ✅ |
| etf-national-team | 20:07 | 秒级 | ✅ | ❌->P1修 | ❌->P1修 |
| rzhb-backfill | 22:10 | 秒级 | ✅ | ✅ | ✅ |

- 互斥：update_all 用 `/tmp/trade_update_all.lock`(--nb)；各backfill 自身锁 + 持 deploy.lock(`/tmp/trade_deploy.lock` 阻塞)串行化git；futures等锁有3600s超时兜底
- 时序：16:35backfill(3min)->17:50update_all(16min,18:06完)->18:30lhb；20:00backfill(3min)->20:05futures->20:07etf，间隔充足无硬冲突
- cross_market components 全自动链路已确认（见上），不依赖手动 deploy

### P1/P2/P3 修复（commit d480f70）
- **P1**：etf_national_team daily 不push -> 新建 `scripts/etf_national_team_backfill.sh`（仿futures/lhb：caffeinate+`/tmp/trade_etf_nt.lock`--nb+交易日闸门+持deploy.lock调deploy.sh）。plist改指新shell已reload（LOADED）。**ETF数据当日采集当日上线，不再等次日17:50**
- **P2**：intraday_snapshot.sh 缺caffeinate -> 加 `caffeinate -i -w $$` @23行（与5脚本一致，防盘中Mac休眠漏快照）
- **P3**：无早盘pmset唤醒 -> 根因 AC sleep=1（插电1分钟就睡）太激进。最终方案：`sudo pmset -c sleep 0`（插电永不睡，盘中9:35快照+17:50 update_all 插电时都跑，不需早盘唤醒）+ `sudo pmset repeat wakeorpoweron MTWRF 17:48:00`（17:48兜底防手动合盖/拔电后睡过头）。**两个坑**：①pmset repeat type 名是 `wakeorpoweron`（带"or"），写成 `wakepoweron` 报 "Unspecified scheduled event type"；②pmset repeat 每个唤醒类(wake/wakeorpoweron)只能存一个时间，9:25和17:48二选一不可兼得，故改用插电sleep=0绕开（不需要两个唤醒）。intraday_snapshot.sh 也补了 caffeinate（P2）双保险

### 踩坑教训（4条）
1. **数据结构变更必须重新部署数据上线**：cross.py 加 components 字段，agent 改代码+重导本地JSON+commit代码push，但没跑 deploy.sh，线上 `components:None` 前端不显示。**涉及JSON字段结构变更的后端改动，代码commit后必须跑 deploy.sh（git add static-site/data/ + commit + push）让新数据上线；验收要 curl 线上数据确认字段值，不只看代码**。已记 memory data-schema-change-needs-deploy
2. **pmset repeat 每 type 一个事件**：`sudo pmset repeat wakepoweron MTWRF 9:25:00 17:48:00` 同type两时间，pmset只保留17:48覆盖9:25。多唤醒时间用不同type。已更新 memory mac-sleep-wake-fix
3. **jsonl mtime 误判卡死**：长工具调用不更新jsonl时间戳，判卡死优先看进度文件 mtime+tail（已记 memory check-progress-file-over-jsonl）
4. **agent遗漏多改点**：复杂任务多改点，prompt 要逐项列明+要求逐项确认（ETF弹窗KPI NULL 遗漏，单独派补丁 agent）

## §24 全球数据补全 + 大盘涨跌幅 + 港股行业daily_sina翻盘（2026-07-16）

### 背景
其他工具要做"每日全球数据复盘日报"，检测报告指出现状：✅港股三大/美股四大/黄金/WTI/白银/离岸人民币/美债/跨市场综合评分；❌缺失日经/KOSPI/欧洲三大/布伦特/港股行业；⚠️港股滞后3天（截至7-10）。用户要求补全 + 大盘信号各数值图加涨跌幅 + 盘中可见（概念/行业轮动折线）。

### 上线功能（commit 清单）
- **大盘指数折线图加涨跌幅**（commit 6f583f3）：`indexChart` 的 `_suffix`（web:618/static:625）在 close 后追加 pct_change badge，正红 `#e6492e`+、负绿 `#2e8b57`，`_last.pct_change` 实测存在（07-15 上证 -0.29%）。一次改完12个A股指数全带。双版 IDENTICAL。
- **阶段1 盘中可见**（commit 4fa01f0）：行业+概念轮动/折线盘中可见。intraday_snapshot 加 `fetch_concept_realtime`(27概念) + `_backfill_concept_daily` + `_recompute_rotation`(盘中显式date=today) + `snap["concepts"]`；export.py 抽 `write_industry_all_split` 供main+盘中共用；DB intraday_snapshot 表加 concepts TEXT 列。**关键：盘中导出JSON已含当日行，前端读JSON即盘中可见，无需改前端**。
- **全球tab extras涨跌幅bug修复 + 6新品种**（commit daf06e7代码 + e421c71数据）：
  - **bug根因**：全球tab里"黄金开始"的商品/汇率/国债走 `valueChartWithSignals`（extras metric series），数据 `{date,value}` 无 pct_change，所以没涨跌幅（刚加的 indexChart badge 只覆盖OHLC指数）。修法：新增 `latestSuffixPct(data)` helper（web:408/static:415）从末两条value算 `(last/prev-1)*100`，extras循环 `latestSuffix`→`latestSuffixPct`。**不改 valueChartWithSignals 本体**（被6处复用会波及情绪图）。
  - **6新品种接入**：日经/KOSPI/富时100/DAX/CAC40（`index_global_hist_sina` 新浪，market:global 走 collect_index 通用路径，fetchers.py:341-343 自算pct_change → 自动有涨跌幅badge）+ 布伦特（`futures_foreign_hist` symbol=**OIL不是B**，B报ValueError）。4处硬编码extras列表加brent（main.py:464/export.py:454/双版app.js extras dict）。renderGlobal indices循环动态（`Object.entries(r.indices)`）→ 5新指数零前端改动自动出图。

### 踩坑教训（2条，已落 CLAUDE.md §8 + memory）
1. **static-site/data/ 误判为§8禁推对象**（本轮最关键踩坑）：实施agent把"不 add data/"理解成连 `static-site/data/` 也不推，导致代码上线（daf06e7）但线上数据没更新（线上global-3m.json仍旧4指数无新品种）。实际：§8 禁的是**根目录 data/**（sentiment.db/signal_stats.json 等 DB+本地M），`static-site/data/` 是**正常上线渠道**（deploy.sh 设计就是commit+push它，git历史有 `data update [all]` 为证，`.gitignore` 不ignore它）。后端新增JSON字段/品种后**必须跑 `bash scripts/deploy.sh`**（export重生成JSON→git add static-site/data/→commit→push→wrangler自动部署），deploy.sh 的git add只加static-site/data/+min JS不碰根data/，安全。已落 CLAUDE.md §8 补澄清 + memory data-schema-change-needs-deploy。**派agent时prompt措辞要精确区分根data/ vs static-site/data/，别让agent误判**。
2. **布伦特symbol用OIL不是B**：`futures_foreign_hist(symbol='B')` 报 ValueError，正确是 `symbol='OIL'`（WTI用CL、白银用SI）。已记入indicators.yaml注释。

### 港股行业分类数据源翻盘结论（重要，颠覆前次预期）
- **前次全球调研结论（错）**：akshare 无港股行业 daily_hist 接口，`stock_hk_index_spot_sina` 只给当日spot，做历史趋势需**自建每日落库累积**，从启用日起逐日增长（短期历史是空的）。
- **本次深挖翻盘（对）**：`stock_hk_index_daily_sina(symbol)` 实测支持**全38指数历史daily**（CESG10博彩业实测2523行 2016-04-18~至今，7列 date/open/high/low/close/volume/amount）。**历史可一次性回填，立即有完整趋势，无需逐日累积**！源码注释"大量采集会被封IP"，回填需分批（每只sleep 3s，8只约24s）。
- **限制**：这38只是"港股相关指数大杂烩"非恒生11行业完整分类体系。真正"行业/板块"属性约8-10只：CESG10博彩/HSTECH科技/CSHKLRE地产/HSMPI地产/HSMOGI油气/HSMBI银行/CSCMC消费/HSCCI中资企业/CSHKDIV红利。建议展示命名"港股板块指数"非"港股行业分类"。
- **落库方案**：复用现有 `index_daily` 表（无需新表），config 加 `market: hk_industry`（新market类型，避免混入三大指数大图），index_id 加 `hk_` 前缀；一次性回填脚本 + 每日增量并入17:50 update_all（不需新launchd）；前端复用 `renderIndustryGrid`（A股行业网格，支持涨幅排序/信号/角标），接入 renderHK 末尾（web:3926/static:3995）；CSS复用现有 `.industry-grid` 无需新样式。

### 策略实验室融合信号差距确认（用户记忆正确）
- 当初设计（TASKS.md:141-160 + lab.js:1621"阶段一仅展示...阶段二将开放回测"）：先展示候选融合信号卡片（阶段一），用户指定后抓数据做实验（阶段二）。
- 现状差距：①候选只硬编码6个手工组合，无自动组合机制（7买×7卖=49配对+同向共振42=90+候选，符合"应该有很多"但没做）②用户指定入口完全缺失（card.onclick空函数lab.js:1471）③抓数据回测链路完全缺失（2个experimental卡note"暂无回测数据需阶段二"）。
- **补全方案4步**：P0候选生成器（纯前端，从22单信号LAB_STRATEGIES两两AND组合生成80+ pending候选卡，lab.js:661后新增_generateFusionCandidates）→ P1用户指定入口（pending卡加"🔁回测此组合"按钮+modal+队列JSON fusion_queue.json）→ P2后端lab_simulate.py扩展 `--fusion`/`--queue` 跑任意配对回测 + 结果回填卡status流转 + 点击进详情页复用renderLabDetail。

### 港股滞后3天根因（已恢复当日，坐实到代码行）
- 线上实测 hk-1m.json 的 hsi/hstech/hscei 最新均 20260715（当日），"滞后3天"是历史快照。
- 根因：新浪源收盘后发布时点不稳定 + 腾讯兜底窗口窄（`_tencent_hk_fallback` index_backfill.py:476-542 三限制：盘中<16:00不写/值<35跳过/快照日期≠当日跳过）。17:50新浪还没出当日+腾讯兜底也失败时累积，直到20:00/02:00 backfill补齐。商品/汇率能当日因源在17:50前已发布（期货15:00收盘、央行中间价9:15发布）。

### 待办（已落 TASKS.md A区）
- 🟡 P2 港股行业分类历史趋势：daily_sina翻盘后可一次性回填，待实施（8板块指数复用renderIndustryGrid接入renderHK）。
- 策略实验室融合信号补全：P0候选生成器可立即做（纯前端），P1/P2看节奏。

## §25 港股板块/全球tab pin补全 + 帽子云purge决策维持（2026-07-16 续）

### 三个pin/按钮缺失修复（同型：配置清单遗漏，非字段缺失数据有）
1. **港股板块指数无pin**（commit 7eb64b1）：main.py `hk_industries` + export.py `export_hk` 生成时漏 signals/stats 字段（对比 A股行业 `export_industry` 有完整字段）。数据齐全（signal_daily 8指数各128-175条+signal_stats全命中），补字段即渲染。根因≠§24踩坑（那是static-site/data误判），是路由生成漏字段。
2. **布伦特原油无pin**（commit 8a4bb4a）：`signals.py:292` GLOBAL_METRIC_IDS 漏 brent（10个无brent），信号脚本不给 g.brent 算信号（signal_daily 0条）。daily_metric brent 2585条行情一直在（§24已接入），只是没算买卖点。补 brent+重算 -> g.brent 117条信号+stats。
3. **全球指数无模拟回测按钮**（commit 84c9b30）：app.js `SIM_INDICES` 白名单遗漏 ftse100/dax/bj50 + us10y/a_qvix_300/a_qvix_1000 裸id（只有g.前缀，extras传裸id致`has()`=false）+ trade_sim_ftse100/dax/g.brent.html 未生成。补白名单+生成3页面+SIM_HREF_MAP映射。deploy 9c6b677 推数据上线。

### 帽子云purge调研结论 + 决策：维持现状
- **缓存错位是 transient**：部署非原子（帽子云构建传播窗口）+ 长 TTL（max-age=1200=20分钟）叠加，新URL命中源站旧内容/404时 CF edge 缓存错位响应20分钟，过期自愈。非永久故障。
- **缓存层定位**：`cf-cache-status: HIT`（Cloudflare缓存）+ `my-cache-status: BYPASS`（帽子云只回源不缓存）。缓存层是 Cloudflare 不是帽子云。
- **根治方案（未采纳）**：maozi.io 子域接入用户自己CF账号（sugas13465），deploy.sh加 wrangler deploy + CF purge API，一次解决 purge秒级 + _headers生效 + Brotli压缩。需用户操作DNS子域CNAME。
- **次选（未采纳）**：切主流量GitHub Pages（max-age=600缩短+现成gzip）。
- **用户决策：维持现状**（不迁移CF/GH Pages）。CDN 20分钟缓存延迟靠等自愈。

### 踩坑：线上静态资源在根路径非 /static/
- 线上 static-site 部署：app.min.js/style.css/trade_sim_*.html 在**根路径**（`/app.min.js?v=xxx`、`/trade_sim_ftse100.html`），非 `/static/`。`/static/` 路径全404。
- web/app.js（动态版）按钮 href 用 `/static/trade_sim_*.html`，static-site/app.js（线上）用 `./trade_sim_*.html`（根路径正确）。
- **验证线上静态资源必须用根路径**，curl `/static/` 会误判404。本次逐字验证差点冤枉 agent 报告不准（agent 实际 curl 根路径报200是对的）。

## §26 全站数据时效调研报告（2026-07-16）

### 调研背景
用户需求：全站非实时数据能否做到实时/当天，优先级 实时>当天>隔天，预期全部实时。派 agent 调研 11 类数据源，主控逐字验证 3 关键机制点。

### 三档汇总（3 关键点已主控 grep 验证）
- **🟢 已实时(6类,工作量0)**：A股指数/A股行业/概念/港股/宽度/情绪。intraday 11槽位 9:35-15:35 每30min（grep plist 确认）反哺DB -> 动态版 /api/* 实时读DB + 静态版每30min `git push origin HEAD:main`（intraday_snapshot.sh:120 grep 确认）。30min 粒度准实时。
- **🟡 当天(6类)**：龙虎榜(18:30)/两融(20:00双源，fetchers.py:24 grep 确认 stock_margin_sse/szse)/商品期货(17:50)/汇率国债/亚欧指数/QVIX。盘后发当天可得。
- **🔴 只能隔天(4类,T+1本质不可突破)**：期货机构持仓(CFFEX次日20:00)/ETF份额(交易所T+1)/美股(时差)/ETF持有人结构(半年报)。

### 核心结论
1. "全部实时"不可能：4类交易所T+1/时差本质限制，任何方案突破不了。
2. 当前已是免费源最优解，无需改动。
3. 秒级实时需付费Level2+WebSocket，对30min看板性价比低，不建议。

### 痛点(非时效)
港股收盘后新浪源不稳+腾讯兜底窗口窄，靠backfill补齐。源稳定性问题(非时效)，已在backfill机制消化。

### a4bc 自查修正 2 处原报告错误
1. 两融 SZSE"可加双源"->错，fetchers.py:24 双源早已采。
2. 两融"准T+1"->错，index_backfill.py:557 注释 18-19:00发布+20:00 backfill，当天可得。

### 深究补充：免费版更好方案(2026-07-16,3关键点已主控验证)
派 agent 深究4方向(备选源/模拟预估/提频5min/其他免费源),3关键点主控 curl/grep 验证:
- **P1 美股期货ES/NQ预估**(curl hq.sinajs.cn hf_ES/hf_NQ 实测14:15=7622.217/29729.150可得✓):A股收盘后用新浪 hf_ES/hf_NQ 亚盘价预估美股当晚开盘方向(相关性≈0.95),解决"美股指数停昨日"观感痛点。~3h,免费源已验证。**唯一有价值增量,值得做**。
- **P2 港股板块8个加备源**(grep _HK_CODE_MAP 确认只3宽基无板块✓,index_backfill.py:494):扩展腾讯代码映射逐一验CESG10/HSMOGI等。~2h,收益低-中(非核心展示,仅收盘延迟触发)。
- **P3 mootdx提频5min**:技术可行(quotes实时TCP无限流),但情绪看板非交易系统,30min够,5min对日级情绪分无增益。不建议。
- **P4-P7 不建议**:ETF份额IOPV预估(IOPV是参考净值非份额,精度不足)/CFFEX持仓预估(盘中无源,外推精度极差)/持有人结构外推(半年频低收益)/美股ETF实时(新浪hf_QQQ返空+东财push2被封,用P1期货替代)。
**结论**:免费版基本到顶,唯一增量 P1(美股期货预估)值得做;P2 可选;其余不建议。

---

## §27 导航吸顶开关（2026-07-16 已实施 commit 545618d）

PC端顶部分享按钮**左边**加"导航吸顶"开关，默认吸顶ON，关闭后导航回文档流原位（方便截图）；多窗口同源共享状态，localStorage 存关闭时间戳，24h 过期回默认吸顶。

> ✅ 已实施上线（commit 545618d, 2026-07-16）：web/static-site 双版同步，`app.js` `applyNavStickyState`+`initNavStickyToggle`(web:5255)，`index.html` 按钮 HTML，`style.css` `.pc-nav-sticky-toggle`。下方调研清单保留作实施记录。

### 1. 顶部分享按钮位置（精确插入点）

**文件行号（双版完全一致，除资源URL）**：
- `web/index.html:73-87` `<header>` 块
- `static-site/index.html:73-87` 同上（仅 script/link 的 href 用 `./` 而非 `/static/`）

**header 结构**（web/index.html:73-87）：
```html
<header>
  <h1>📊 市场温度看板</h1>
  <button class="share-btn pc-share-btn" title="生成分享图">📤 分享</button>   <!-- line 75，PC分享按钮 -->
  <span class="collect-time pc-collect-time" title="数据采集时间"></span>      <!-- line 76 -->
  <button class="theme-btn pc-theme-btn" title="切换皮肤">🎨</button>           <!-- line 77 -->
  <div class="h5-topbar">...</div>   <!-- line 79-86，H5顶部条，PC隐藏 -->
</header>
```

**开关插入点**：在 **line 75 的 `<button class="share-btn pc-share-btn">` 之前**插入开关按钮（即 h1 与 pc-share-btn 之间）。header 是 `display:flex; justify-content:space-between`（style.css:103-110），`.pc-share-btn { margin-left:auto }`（style.css:114）把右侧按钮组推到最右；开关加在 share-btn 左边，会落在右侧按钮组最左位（分享按钮之左、采集时间/皮肤更右）。建议开关也用 `pc-` 前缀（如 `class="nav-sticky-toggle pc-nav-sticky-toggle"`），与 share/collect/theme 一组。

**PC/H5 显隐机制**（style.css:112-143）：
- `.pc-share-btn` PC 默认显示；`@media(max-width:768px){ .pc-share-btn{display:none} }`（style.css:135-136）移动端隐藏。
- `.h5-share-btn` 默认 `display:none`（style.css:121），`@media` 内显示（style.css:137-141）。
- 开关同理：`.pc-nav-sticky-toggle` PC 显示 + `@media` 隐藏。**移动端不需要此开关**——移动端 `nav.tabs{display:none}`（style.css:1845），用底部固定导航 `.h5-bottomnav` + 顶部 `.h5-period-bar` sticky，无 PC 式吸顶问题。

### 2. 导航吸顶实现 + 连带元素（关闭吸顶的改动点）

**主吸顶元素**：`web/style.css:179-189`（static-site 同行号）
```css
.tabs {
  display: flex; gap:4px; padding:0 24px;
  background: var(--bg-card); border-bottom:1px solid var(--border);
  position: sticky;   /* UX：tab 栏滚动时悬浮顶部 */
  top: 0; z-index: 50;
  box-shadow: 0 1px 3px var(--shadow);
}
```
**纯 CSS `position:sticky`，非 JS 滚动监听**。关闭 = 改 `position:static`。

**连带吸顶元素（必须一并处理，否则脱节）**：
1. `style.css:843-855` `.rule-bar`（买卖点规则说明条）：`position:sticky; top:var(--tab-h,41px); z-index:40`——top 贴 tab 栏正下方，依赖 tab 栏吸顶。
2. `style.css:1400-1411` `.industry-anchor-bar`（行业锚点条，含申万/概念 tab+搜索框）：`position:sticky; top:var(--tab-h,41px); z-index:39`——同样依赖 tab 栏。
3. 若只把 `.tabs` 改 static，rule-bar / anchor-bar 仍 sticky 在视口顶 41px 处（因 `--tab-h` 仍=41px），会脱离 tab 栏单独悬空吸顶，视觉错乱。

**`--tab-h` 来源**（web/app.js:5212-5219 / static-site/app.js:5297-5304）：
```js
function initStickyOffset() {
  const tabs = document.querySelector('.tabs');
  if (!tabs) return;
  const set = () => document.documentElement.style.setProperty('--tab-h', tabs.offsetHeight + 'px');
  set();
  window.addEventListener('resize', set); window.addEventListener('load', set);
}
```
测 tabs 高度写 `--tab-h`（兜底41px）。**关闭吸顶后此函数仍可运行**（static 元素也有 offsetHeight），无副作用，不需改。

**关闭吸顶的推荐改法**：给 `<html>` 加 class `nav-no-sticky`，CSS 统一覆盖：
```css
.nav-no-sticky .tabs,
.nav-no-sticky .rule-bar,
.nav-no-sticky .industry-anchor-bar { position: static !important; }
```
（用 `!important` 或确保选择器特异性高于原 `.tabs`；原选择器是单 class，`.nav-no-sticky .tabs` 双 class 特异性更高，可不加 !important。）移动端 `.h5-period-bar`（style.css:1847）不在此 class 影响范围内，移动端不受影响。

### 3. 多窗口共享逻辑确认（localStorage + storage 事件 + 24h，可行）

现有 `trade-theme`（app.js:5734/5742）只用 localStorage 读写、**无 storage 事件监听**（主题不实时跨窗口同步，仅新窗口加载时读）。本需求要实时同步，需新增 `storage` 事件监听——标准 Web API，项目无障碍。

**localStorage key**：`navStickyOff_ts`（关闭时存 `Date.now()` 数值串；默认吸顶=不存或已过期）。

**加载时判定（防闪烁，放 head 内联脚本，仿 index.html:40-51 主题防闪烁）**：
```js
// <head> 内联，body 渲染前执行，避免吸顶渲染后再跳变
(function(){
  try {
    var ts = parseInt(localStorage.getItem('navStickyOff_ts'), 10);
    if (ts && Date.now() - ts < 24*3600*1000) {
      document.documentElement.classList.add('nav-no-sticky');  // 24h内=关闭吸顶
    } else {
      if (ts) localStorage.removeItem('navStickyOff_ts');  // 过期清理
      // 不加 class = 默认吸顶
    }
  } catch(e){}
})();
```

**开关 toggle（app.js 新增 initNavStickyToggle）**：
```js
function isNavStickyOff() {
  try { var ts = parseInt(localStorage.getItem('navStickyOff_ts'), 10);
    return !!(ts && Date.now() - ts < 24*3600*1000);
  } catch(e){ return false; }
}
function applyNavStickyState() {
  var off = isNavStickyOff();
  document.documentElement.classList.toggle('nav-no-sticky', off);
  // 更新开关 UI（ON/OFF 两态）
  document.querySelectorAll('.nav-sticky-toggle').forEach(function(b){
    b.classList.toggle('off', off);
    b.textContent = off ? '导航吸顶 ⏻' : '导航吸顶';  // 或用 data 属性切文案
  });
  if (!off) { try { localStorage.removeItem('navStickyOff_ts'); } catch(e){} }
}
function initNavStickyToggle() {
  document.querySelectorAll('.nav-sticky-toggle').forEach(function(b){
    b.addEventListener('click', function(){
      if (isNavStickyOff()) {  // 当前关 -> 开：清 ts
        try { localStorage.removeItem('navStickyOff_ts'); } catch(e){}
      } else {                 // 当前开 -> 关：存 ts
        try { localStorage.setItem('navStickyOff_ts', String(Date.now())); } catch(e){}
      }
      applyNavStickyState();   // 原窗口立即生效
    });
  });
  // 多窗口实时同步：其他窗口改 localStorage 触发 storage 事件
  window.addEventListener('storage', function(e){
    if (e.key === 'navStickyOff_ts') applyNavStickyState();
  });
  applyNavStickyState();  // 初始渲染开关态
}
```
**注意**：`storage` 事件不在原窗口触发（只在同源其他窗口），原窗口 toggle 后直接 `applyNavStickyState()` 即时生效；其他窗口靠 storage 事件实时同步。同浏览器同源多窗口共享，无需后端。

### 4. 双版结构差异

**结论：双版结构一致，仅资源 URL 不同（符合 §9 双版同步铁律）**。
- `index.html`：web 与 static-site 的 header/tabs 结构逐字相同（行73-126），差异仅在 `<link href="/static/...">` vs `./...`、`<script src="/static/...">` vs `./...`、og/canonical URL。分享按钮、nav.tabs、header 布局完全一致。
- `style.css`：双版均 2363 行，行号完全对应。`.tabs`/`.rule-bar`/`.industry-anchor-bar`/`.pc-share-btn`/`@media` 全部一致。
- `app.js`：web 5991 行 / static-site 6057 行（static-site 多 66 行，因数据源 URL 等差异）。关键函数双版齐全：
  | 函数 | web/app.js | static-site/app.js |
  |---|---|---|
  | initStickyOffset | 5212 | 5297 |
  | openShareModal | 5657 | 5748 |
  | initShareButton | 5694 | 5779 |
  | initThemeSwitcher | 5701 | 5786 |
- 末尾顶层初始化调用顺序双版一致：
  - web: 5918-5926 `initStickyOffset();initBackToTop();initRuleButton();initH5();initSimOverlay();initShareButton();initThemeSwitcher();initUpdateRules();initDataHealthBanner();`
  - static-site: 5984-5992 同序。
- 分享按钮双版都有（PC `.pc-share-btn` + H5 `.h5-share-btn`），事件绑定 `document.querySelectorAll(".share-btn").forEach(b=>b.addEventListener("click",openShareModal))`（web:5695 / static-site:5780）。开关用独立 class `.nav-sticky-toggle`，不会误触分享。

### 5. 实施清单（后续 agent 照做）

**A. HTML（双版 index.html，各改2处）**：
1. **line 75 前**插入开关按钮（PC版）：
   ```html
   <button class="nav-sticky-toggle pc-nav-sticky-toggle" title="切换导航吸顶（关闭后方便截图）">导航吸顶</button>
   ```
   （插在 `<h1>` 与 `<button class="share-btn pc-share-btn">` 之间。）
2. **head 内联脚本**（line 40-51 主题防闪烁段之后）加 navStickyOff_ts 判定，documentElement 加 `nav-no-sticky` class（见 §3 加载时判定伪代码）。

**B. CSS（双版 style.css，各改2处）**：
1. **header 区域**（style.css:112-143 附近，`.pc-share-btn` 之后）加开关样式：
   ```css
   .pc-nav-sticky-toggle {
     margin-left: 8px; border:1px solid var(--border-strong); background:var(--bg-card);
     color:var(--text-2); border-radius:16px; padding:5px 12px; font-size:13px;
     cursor:pointer; transition:all .15s; user-select:none;
   }
   .pc-nav-sticky-toggle.off { border-color:var(--text-4); opacity:.6; }   /* OFF 态 */
   .pc-nav-sticky-toggle:hover { background:var(--bg-hover); }
   ```
   并在 `@media(max-width:768px)` 块（style.css:135）内加 `.pc-nav-sticky-toggle{display:none}`（移动端隐藏，移动端无 PC 吸顶）。
2. **吸顶覆盖**（style.css:189 `.tabs` 规则之后或文件末尾）加：
   ```css
   .nav-no-sticky .tabs,
   .nav-no-sticky .rule-bar,
   .nav-no-sticky .industry-anchor-bar { position: static; }
   ```
   （`.nav-no-sticky .tabs` 双 class 特异性 > `.tabs`，无需 !important。）

**C. JS（双版 app.js，各改2处）**：
1. **新增 `initNavStickyToggle()` 函数**（含 isNavStickyOff/applyNavStickyState/toggle/storage 监听，见 §3 伪代码）。建议插在 `initStickyOffset`（web:5212 / static-site:5297）附近。
2. **末尾初始化调用**（web:5918 / static-site:5984 的 `initStickyOffset()` **之前**）加 `initNavStickyToggle();`——确保 nav-no-sticky class 先定，再测 --tab-h（虽 static 也有 offsetHeight，但顺序上先定状态更稳）。

**D. 双版同步 + 上线**：
1. 改完跑 `python3 scripts/build_min.py`（terser minify app.js->app.min.js）+ `python3 scripts/bump_asset_version.py`（md5前8位破缓存，更新 index.html 的 ?v=）。
2. 双版 diff 验证 IDENTICAL（除数据源 URL）：`diff <(sed 's#\./#/#g' static-site/index.html) web/index.html` 等比对应无业务差异。
3. commit + push feat + merge main + push main（§8）。不 add 根目录 data/。

### 验收口径对照
- **分享按钮在 web/index.html:75（static-site:index.html:75），结构是 `<button class="share-btn pc-share-btn">📤 分享</button>`，在 `<header>` 内 h1 之后；开关插在 line 75 之前**。
- **导航吸顶实现是 CSS `position:sticky`（style.css:185 `.tabs`，非 JS scroll）；关闭吸顶改 `position:static`，通过给 `<html>` 加 `nav-no-sticky` class 覆盖 `.tabs`/`.rule-bar`/`.industry-anchor-bar` 三处（后两者 top 依赖 tab 栏，必须一并 static）**。
- **双版结构一致（index.html header/tabs 逐字相同仅资源URL不同；style.css 均2363行行号对应；app.js 关键函数+末尾初始化顺序双版齐全，static-site 比 web 多66行属数据源差异）**。

## §28 策略实验室二次测试（2026-07-16，已实施3种切片+每日自动跑上线）

> 任务来源：用户需求"策略实验室回测排行榜+融合信号测试线跑全+brainstorm二次测试方案"。

> **实施落档（2026-07-16 晚，逐字验收通过）**：
> - **二次测试3种切片已实施上线**：①分年回测(2016-2026逐年) ②样本外(前70%训练后30%holdout) ③极端行情(4 regime: crash2015/bear2018/covid2020/rally2024)。前端 lab.js 加"🔬 二次测试"tab + ⭐️候选规则公示(commit d6b2224)；lab_retest.py pair_meta 补全(strategy/window/score归一化0.4*ret+0.3*win+0.2*(-dd)+0.1*n)(commit 5d68c73)。
> - **每日自动跑+上线**（用户需求"每天自动增量所有回测,不用手动补"）：调研确认 lab 数据源=DB `index_daily`(每日 update_all 17:50 新增当天日线,lab_simulate.py:104-105 读 DB)，产物(`lab_sim_*/lab_retest_*.json`)原手动跑、update_all.sh 不含 lab、不自动更新。方案：`scripts/update_lab.sh` 跑 `lab_simulate`(单信号128组×9指数) + `--fusion`(91候选×9) + `lab_retest`(切片)，跑完 `git add static-site/data/lab/ web/data/lab/` + commit + `push origin HEAD:main` 上线(§8 上线渠道,不碰根 data/)。launchd `com.trade.lab-auto` 每日 **19:00**(update_all 17:50→18:39 完后；脚本内 `pgrep update_all.sh` 等待完成防撞车+防读旧数据缺当天日线，最多等90min) + `caffeinate -i -w $$` 防睡 + 交易日闸门 + `with_lock.py --nb` 进程互斥 + 失败不阻塞。全量仅 ~30s(单信号10.3s+融合15s+retest2.5s,纯 pandas 读 DB)。(commit d9bcd78 feat + 6bad9cd data update [lab])
> - 其余7方向(蒙特卡洛/参数敏感/信号消融/手续费/多空对称/标的泛化/融合P2回测)属优化/归因,靠后待办。

### 1. 回测排行榜（推荐榜）精确定位

**文件**：`web/lab.js`（动态版）+ `static-site/lab.js`（静态版，双版逐字相同**仅数据源URL差异** `/static/data/lab/` vs `./data/lab/`，符合§9）；min版 `web/lab.min.js`/`static-site/lab.min.js` 由 `scripts/build_min.py` 生成。**本调研不碰主页 index.html/style.css/app.js，lab.js 是策略实验室专用文件。**

**渲染函数链**（全在 lab.js）：
- `_labRankHTML`（lab.js:2156）主入口 → 调 `_labRankAggregate` + `_labRankResultsHTML`
- `_labRankAggregate`（lab.js:2079）聚合 `simData.pairs` → `rows[]`，算综合评分 `r.score`
- `_labRankSort`（lab.js:2127）按 tab 排序；5 个 tab（`LAB_RANK_TABS` lab.js:2017）：`composite`🏆综合推荐(默认) / `ret`📈收益率 / `win`🎯胜率 / `stable`🛡稳健(回撤小) / `risk_adj`⚖风险调整
- `_labRankItemHTML`（lab.js:2137）渲染单项 button

**数据来源**：`lab_sim_{iid}_stats.json`（lab.js:1161 fetch），9 A股宽基指数齐全（sh/sz/cyb/kc50/bj50/sz50/hs300/csi500/csi1000）。`generated_at` 停在 **2026-07-10**（文件时间戳7-13），**距今3天非最新**。`lab_backtest_{iid}.json`（22策略×5窗口×4horizon矩阵）同样停在7-13。

**stats.json 结构**（`lab_sim_{iid}_stats.json`）：
```
top keys: generated_at, index_id, index_name, initial_capital, windows, strategies, pairs
pairs["buy_key|sell_key"][mode].stats[win] = {
  total_ret, annual_ret, max_drawdown, win_rate, n_trades, final_total, years
}  # mode=full_in|fixed_10k, win=all|y10|y5|y3|y1
# 64 配对（8买×8卖），strategies 16个（8买+8卖，存 side+partners）
```

**评分字段**：`row.score`（0~1，lab.js:2123）= `0.4*nRet(total_ret) + 0.3*nWin(win_rate) + 0.2*nDd(-max_drawdown) + 0.1*nN(n_trades)`，各项 min-max 归一化到[0,1]加权。展示：lab.js:2142 `tab==="composite"` 时 `<span class="lab-rank-score">评分 ${(row.score*100).toFixed(0)}</span>`。另有 `row.risk_adj = annual_ret/max_drawdown`（类Calmar，lab.js:2117）。

**单项 HTML 结构**（lab.js:2145-2153，`_labRankItemHTML` 返回）：
```html
<button class="lab-rank-item clickable-card" data-buy data-sell data-mode>
  <span class="lab-rank-no">${medal || "#"+rank}</span>   <!-- 🥇🥈🥉 或 #4.. -->
  <span class="lab-rank-name">买${buyName} × 卖${sellName} · ${modeName}</span>
  <span class="lab-rank-stats">
    <span>收益${total_ret}%</span><span>胜${win_rate}%</span>
    <span>回撤${max_drawdown}%</span><span class="lab-rank-n">n=${n_trades}</span>
  </span>
  ${extra}   <!-- composite: 评分span / risk_adj: risk_adj span -->
</button>
```

**⭐️"进入二次测试"精确插入点**：
- **判定逻辑**插在 `_labRankAggregate`（lab.js:2123 附近，`r.score` 赋值后）：加 `r.retest = <二次测试候选条件>;`
- **标注HTML**插在 `_labRankItemHTML`（**lab.js:2143 行尾**，`else if (tab === "risk_adj") extra = ...` 之后、lab.js:2145 `return` 之前）：
  ```js
  if (row.retest) extra += '<span class="lab-rank-retest">⭐️进入二次测试</span>';
  ```
- 配套 style.css 加 `.lab-rank-retest` 样式（金色⭐️徽章）。**注意 style.css 是吸顶 agent 也在改的文件，实施时需串行协调（见§5约束）**。

### 2. "融合信号测试线"真意（坐实）

**结论：融合信号（多信号同日AND共振）作为独立买卖信号的回测链路当前完全未实现/未跑。"跑全"= 实现 P2 + 跑91候选×9指数。这是开发新功能，非现成命令。**

坐实证据：
1. `scripts/lab/lab_simulate.py` 的 `BUY_KEYS`/`SELL_KEYS`（lab_simulate.py:84-93）**全是单信号**（BB_lower_revert/Supertrend_buy/.../D1_high20_drop5），8买×8卖=64配对×2模式×5窗口，**无任何 F_* 融合信号**。
2. grep `--fusion`/`--queue`/`argparse` in lab_simulate.py = **0 命中** → NOTES §1270-1281 记的 **P2（lab_simulate.py 扩展 `--fusion`/`--queue` 跑任意配对回测）未实现**。
3. `a-stock-data/backtest_strategies.py` 的 `gen_buy_signals`（:133）/`gen_sell_signals`（:175）只生成单信号（11买+11卖），**无融合信号生成函数**；`STRATEGY_DESC`（:290）也无 F_* 条目。
4. 前端 `_generateFusionCandidates`（lab.js:667）运行时生成 **91 个 pending 候选**：49买×卖 + 21买×买 + 21卖×卖，`status:"pending"`，note"待回测"。
5. 当前 fusion 模式推荐榜（lab.js:2160 `experimentalOnly: state.labSubMode==="fusion"`）**只是复用单信号配对 stats.json 过滤展示49个单信号买×卖配对**，**非真融合信号（多信号同日AND）回测**。
6. 同向共振42个（买×买21+卖×卖21）标注"回测开发中"（lab.js:2634 phaseNote + lab.js:2791 `🚧 同向共振回测开发中`）。
7. 融合信号列表页 lab.js:2550 注释"阶段一：仅展示元数据，不跑回测"。

**已知风险**：融合信号"同日AND"样本可能极少——lab.js:615 已记"F_D1_S1（s.*情绪分序列）加MACD后样本从106降至7，不足统计"。多条件AND天然降样本，需设最小样本阈值（如 n≥30）否则统计无意义。

### 3. 跑全方式（两种解读，方向性分叉——待用户选）

#### 解读A（重）：真融合信号回测链路（P2 开发 + 跑全）
- **需先开发 3 处**：
  - `a-stock-data/backtest_strategies.py` 加 `gen_fusion_signals(df, fusion_def)`：把 lab.js `LAB_FUSION_STRATEGIES`（lab.js:596-663）+ `_generateFusionCandidates`（lab.js:667）的 conditions 映射到单信号 key，同日 AND 组合生成融合买卖信号 mask。
  - `scripts/lab/lab_simulate.py` 扩展 `--fusion`（跑全部91候选）/`--queue fusion_queue.json`（跑 P1 用户指定队列）参数；复用 `build_pair_result`/`simulate_full_in`/`simulate_fixed_10k`。
  - 输出 `lab_sim_{iid}_fusion_stats.json` / `_full.json`（或合并入现有 stats.json 加 `fusion` 段），前端 `_labRankAggregate` 加融合分支。
- **跑全命令（开发后）**：`python scripts/lab/lab_simulate.py --fusion`
- **产物**：`web/data/lab/` + `static-site/data/lab/` 各 `lab_sim_{iid}_fusion_*.json`，9指数×91候选×2模式×5窗口
- **预估**：开发 0.5-1 天 + 跑全 <30min（单信号64配对×9指数量级相当）
- **风险**：同日AND样本稀少（见§2），部分候选可能 n<30 无统计意义，需阈值过滤

#### 解读B（轻）：刷新现有单信号64配对数据（立即可跑）
- 现有 lab_simulate.py（无 --fusion）跑全9指数刷新 stats/full json（当前停在7-10/7-13）+ lab_matrix.py 刷新22策略矩阵
- **跑全命令**：`python scripts/lab/lab_simulate.py && python scripts/lab/lab_matrix.py`（main 均跑全9指数）
- **产物**：覆盖 `web/data/lab/` + `static-site/data/lab/` 的 `lab_sim_{iid}_stats/full.json` + `lab_backtest_{iid}.json`
- **预估**：<15min
- **局限**：仅刷新已有数据，不产生"融合信号"成绩

#### 推荐
**先做解读B**（立即可跑，刷新数据让排行榜基于最新7-16行情，可立即评测⭐️二次测试候选），**解读A（P2真融合回测）列入二次测试方案待办**（融合信号回测本身验证"多信号共振是否优于单信号"，是二次测试的核心一环）。理由：用户"跑全后评测建议二次测试"——B跑全后单信号排行榜基于最新数据可立即评测；A的融合回测作为二次测试的"信号叠加消融"方向推进，不阻塞⭐️标注。

### 4. 二次测试方案 brainstorm（待用户选，记待办）

基于回测排行榜成绩（`row.score` 综合评分 + total_ret/win_rate/max_drawdown/n_trades/risk_adj 各维度），10 个二次测试方向：

1. **分年回测**：现5窗口（全史/10y/5y/3y/1y）粒度粗，按自然年切分看年度稳定性（防某年暴利拉高整体）
2. **极端行情分段**：牛熊转换段（2015股灾/2018熊/2020疫情/2024反弹）单独回测，看 regime 切换表现
3. **多空对称性**：现仅多头（买→卖），加空头（卖→买开空）测对称性，看卖点反向是否也有效
4. **手续费/滑点敏感**：现回测零成本，加双边手续费0.03%+滑点0.1%重算，看高换手策略（MA金叉/MACD等密集信号）是否被成本吃掉
5. **标的泛化**：现9 A股宽基，扩到31申万行业+海外指数+商品（trade_sim_* 覆盖标的），看泛化性
6. **样本外检验**：前70%数据调参，后30%样本外验证，防过拟合
7. **蒙特卡洛扰动**：信号日±1~2天扰动、价格±0.5%扰动，跑N次看收益分布稳定性（脆弱=轻微扰动即崩）
8. **参数敏感扫描**：核心参数（RSI周期/MA周期/BB带宽/Donchian窗口）网格扫描，看收益对参数敏感度（平坦=鲁棒，尖锐=过拟合）
9. **信号叠加消融**：融合信号91候选逐个消融（去某条件看变化），定位真正贡献来源——**依赖§3解读A的P2先跑出融合回测**
10. **融合信号回测（P2本身）**：§3解读A，把91个pending融合候选真跑出来，比较多信号AND共振 vs 单信号的增益

**⭐️二次测试候选筛选标准（建议，实施时可调）**：
- 主条件：`score≥0.6 && n_trades≥30 && max_drawdown≤50`（综合评分top档+样本充分+回撤可控）
- 或单项突出：`win_rate≥55 || risk_adj≥1.0 || total_ret 为 top10%`
- 在 `_labRankAggregate`（lab.js:2123后）实现为 `r.retest = <上述条件>`

### 5. 实施清单（后续实施 agent 照做，待用户定§3方向后启动）

**前置协调**：当前分支 `feat/iframe-theme-follow` 有吸顶 agent 改主页 index.html/style.css/app.js。lab.js 是策略实验室专用文件**不冲突可并行**；但 **style.css 是同文件**（lab 徽章样式 vs 吸顶样式不同区域但同文件），实施⭐️标注的 style.css 改动需**等吸顶 agent 完成或串行**，避免撞车。

1. **跑全融合信号测试线**（按用户选§3A或§3B）：
   - B（推荐先做）：`python scripts/lab/lab_simulate.py && python scripts/lab/lab_matrix.py` 刷新9指数数据
   - A（二次测试阶段做）：先开发 P2（`backtest_strategies.gen_fusion_signals` + `lab_simulate.py --fusion`），再 `python scripts/lab/lab_simulate.py --fusion`
2. **评测+⭐️标注**：
   - `_labRankAggregate`（web/lab.js:2123 + static-site/lab.js 同处）加 `r.retest = (r.score>=0.6 && r.n_trades>=30 && r.max_drawdown<=50) || r.win_rate>=55 || r.risk_adj>=1.0;`
   - `_labRankItemHTML`（web/lab.js:2143 + static-site/lab.js 同处）`extra` 赋值后加 `if (row.retest) extra += '<span class="lab-rank-retest">⭐️进入二次测试</span>';`
   - style.css 加 `.lab-rank-retest` 样式（金⭐️徽章，两版同改）
3. **双版同步**（§9）：web/lab.js + static-site/lab.js（唯一差异数据源URL）+ web/style.css + static-site/style.css
4. **build_min + 版本号**：`python scripts/build_min.py`（lab.js→lab.min.js）+ `python scripts/bump_asset_version.py`（md5前8位破缓存）
5. **deploy 上线**（§8）：`bash scripts/deploy.sh`（推 static-site/data/lab/ + min JS；deploy.sh 的 git add 只加 static-site/data/ + min JS，不碰根 data/，安全）
6. **验收**：curl 线上 `lab_sim_{iid}_stats.json` 确认 `generated_at` 更新到7-16；前端排行榜⭐️"进入二次测试"标注在候选配对显示；双版 lab.min.js cmp 仅数据源URL差异

### 验收口径对照
- **回测排行榜在 `web/lab.js`（双版 static-site/lab.js），渲染函数 `_labRankItemHTML`（lab.js:2137）；评分字段 `row.score`（0-1，lab.js:2123 算，=0.4收益率+0.3胜率+0.2回撤倒数+0.1样本量，min-max归一化加权）；⭐️插在 lab.js:2143（`_labRankItemHTML` 的 `extra` 赋值后，`return` 之前）+ 判定逻辑插在 lab.js:2123（`_labRankAggregate` 的 `r.score` 赋值后）**。
- **"融合信号测试线"= 融合信号（多信号同日AND）回测链路，当前 P2 未实现（lab_simulate.py 无 --fusion/--queue，BUY_KEYS/SELL_KEYS 全单信号，backtest_strategies.py 无 gen_fusion_signals）；跑全命令解读B=`python scripts/lab/lab_simulate.py && python scripts/lab/lab_matrix.py`（刷新现有数据，<15min），解读A=先开发P2再 `python scripts/lab/lab_simulate.py --fusion`（<30min）；产物=web/data/lab/+static-site/data/lab/ 的 lab_sim_{iid}_stats/full.json[+_fusion_*.json]**。
- **二次测试方案 brainstorm 10 方向已记本节§4（分年/极端行情/多空对称/手续费/标的泛化/样本外/蒙特卡洛/参数敏感/信号消融/融合P2），⭐️筛选标准建议 `score≥0.6&&n≥30&&dd≤50 || win≥55||risk_adj≥1.0`，待用户选方向**。

### 6. 二次测试对齐单一信号实验（2026-07-16，已实施，commits 05a5e6a/bb713d2/cdb5dff）

**目标**：二次测试弹窗/排行榜此前是简化展示，与单一信号实验页（`_labSimModeBlock` 整体回测详情）观感割裂；本次把二次测试弹窗上半整体回测详情**照抄单一信号实验**，下半保留三切片，排行榜加 5 窗口切换器对齐单一信号页交互。双版 lab.js 同步。

**弹窗 `_labRetestPairModalRender`（改 async，lab.js:3278）**：
- 上半 = 整体回测详情，直接复用单一信号实验渲染 `_labSimModeBlock`（lab.js:1348）：
  - 4 数字结论（总收益 / 年化 / 回撤 / 胜率）+ 净值曲线 SVG + 11 列交易记录表 + 分页
  - 买卖模式切换器（全仓 `full_in` / 定额 10% `fixed_10k`）
  - 5 窗口切换（近 1/3/5/10 年/全史，复用 `LAB_WIN_DEFS`，独立于排行榜窗口 `state.labRetestRankWindow`）
  - full 按需加载 `_labRetestEnsureFull`（lab.js:3248，async，切到需 trades/equity_curve 的窗口时懒拉 full JSON 合并）
- 下半 = 二次测试三切片（分年 / 样本外 / 极端行情）保留不变。

**排行榜 `_labRetestRankHTML`（lab.js:3029）**：
- 加 5 窗口切换器，独立 state `labRetestRankWindow`（默认 `y5`，不影响推荐榜 `state.labSimWindow`）。
- 切窗口时从单信号 `simData.stats[winKey]` 重算整体 4 维（ret/win/dd/n），再按综合分（0.4·ret+0.3·win+0.2·(-dd)+0.1·n 归一化）重排。
- 每行标注"全仓"（retest 后端 `full_in` 模式产出，区别于单一信号页可选定额）。

**数据复用（不动后端）**：
- retest 22 pair 全是融合候选，pair key 与单一信号 `simData.pairs` key 对齐，验证 ret `0.1087`（pair_meta 小数）= `10.87`（单信号 stats 百分数）一致（lab.js:2877 注释坐实统一为小数）。
- 复用 `fetchLabSimData`（lab.js:1164，拉 stats）+ `fetchLabSimFullData`（lab.js:1229，拉 full）合并，**不动后端 `scripts/lab/lab_retest.py`，不动 fusion 相关文件**。

**双版同步**：web/lab.js 与 static-site/lab.js IDENTICAL（除 4 处数据源 URL）；`lab.min.js` 已 `scripts/build_min.py` 重建；commit message 末尾 `Co-Authored-By: Claude <noreply@anthropic.com>`。

### 7. 本轮 lab + freshness 改动落档（2026-07-17，6 项已上线）

> 任务来源：retest 区 5 点对齐 + 后端 fixed_10k + 融合弹窗 3 Bug 修复 + 三区弹窗交互一致 + 执行统计 ⚠️ pop + index_backfill 退出码 bug 修复。全部双版 lab.js 同步、`build_min.py` 重建、commit 末尾 `Co-Authored-By`。

**a. retest 区 5 点对齐**（commits 9c84896 / fbbd6c1 / e7b512c / d85b7f1，web/lab.js + static-site/lab.js 双版）：

- **点 1 指数选择器**：retest 排行榜 `_labRetestRankHTML` 顶部加指数选择条；左栏（排行榜）与右栏（详情）共用 `idxBar`，切指数时两栏一起重载。
- **点 2 过滤**：新增 `LAB_RETEST_RANK_FILTERS` 常量 + `_labRetestRankApplyFilter` + `_labRetestRankFilterHTML`；支持收益 / 胜率 / 回撤 三类过滤，过滤值×100 与 stats 小数比较（统一小数口径）。
- **点 3 定额 10% 双行**：`_labRetestRankRows` 每对产出 2 行（`full_in` + `fixed_10k`），综合分各自用对应 mode 的三切片重算；弹窗接 `mode` 参数读 `fixed_10k` 对应切片。
- **点 4 弹窗说明**：modeBar + winBar 旁加 `switchHint`（💡可切换时间窗口和买卖模式），降低用户找不到切换入口的困惑。
- **点 5 三切片注入位置**：`_labSimModeBlock` 加 `midHTML` 参数，三切片注入「净值曲线」与「交易记录」之间；弹窗内顺序固定为 4 数字 → 净值曲线 → 三切片 → 交易记录。

**b. 后端 fixed_10k 模式**（commits cbd2756 / 06f04ed / bd2f58d，scripts/lab/lab_retest.py）：

- 5 个函数加 `sim_func` 参数 + `simulate_fixed_10k`（定额 1 万本金，按信号逐笔投入 / 平仓，不按比例加仓）；9 指数全量重跑约 4s。
- **数据结构（向后兼容）**：每个 pair = `{pair_meta{mode:full_in}, yearly, oos, regimes, fixed_10k{pair_meta{mode:fixed_10k}, yearly, oos, regimes}}`；旧前端读 top-level 字段不受影响，新前端按 mode 读 `fixed_10k.*`。
- 跑完 `scripts/deploy.sh` 推 `static-site/data/lab/` 上线（§8 正常上线渠道，非禁推对象）。

**c. 融合弹窗 3 Bug 修复**（commit e89b8d8，web/lab.js + static-site/lab.js）：

- **Bug-A（6 个硬编码策略缺 `_pairType`）**：`LAB_FUSION_STRATEGIES`（标签 live/partial/experimental）未设 `_pairType`，弹窗按类型分发时走「同向共振开发中」分支且标题 undefined。修：对这类硬编码策略独立渲染，直接显示其 stats，不进 buy_buy/sell_sell 分支。
- **Bug-B（42 个同向共振显示「开发中」）**：buy_buy / sell_sell 共 42 个 pair 有真实 stats（后端已跑），弹窗却判为未实现。修：弹窗三类分支（buy_sell / buy_buy / sell_sell）都支持显示，不再误判。
- **Bug-C（加载错文件）**：弹窗误加载单信号 `stats`（64 pairs），应加载融合 `fusion_stats`（91 pairs）。修：弹窗改加载 `fusion_stats`。
- **结论**：融合实验已 100% 跑完（91 候选 = 49 buy_sell + 21 buy_buy + 21 sell_sell，9 指数齐备）；此前前端显示「回测开发中」是前端 bug，非真没跑。

**d. 三区弹窗交互一致**（commits a953cb7 / af35aea，web/lab.js + static-site/lab.js）：

- **单一信号弹窗 `_labRankModalRender`**：加 modeBar（全仓 / 定额 10%）+ winBar（5 窗口）+ switchHint，与 retest 弹窗对齐。
- **融合弹窗**：从静态 2×5 表改为交互（modeBar / winBar 切换 + 复用 `_labSimModeBlock` + `fusion_full` 按需懒加载）。
- **通用 `_labModalWinTabsHTML`**：三区（retest / 单一 / 融合）弹窗交互完全一致，用户切窗口 / 切 mode 体验统一。

**e. 执行统计 ⚠️ pop**（commit eeafbfe，web/app.js + static-site/app.js）：

- 执行统计行的 ⚠️ 标记加 `data-tip`（tooltip）：退出码非 0 = 脚本异常退出，tooltip 显示具体退出码 + 指明日志路径 `data/logs/${task}_launchd.log`，方便一键定位。

**f. index_backfill 退出码 bug 修复**（commit ac93c50，app/collector/index_backfill.py）：

- **根因**：`verify_and_backfill_indices` 函数内 `upsert_index_rows` 经 3 处 `else` 分支（核心 A 股 / 申万 / 概念「有缺失才补采」段）延迟 `import`；Python 编译期把该 import 标记为函数局部变量。当前三段全齐（无需补采）时 import 语句不执行，到第 448 港股段调用 `upsert_index_rows` -> `UnboundLocalError`。数据其实采到 ✓，但异常致退出码 1 -> ⚠️。
- **修复**：港股段补一处 `import` 保证名字绑定；backfill 退出码 1 -> 0，执行统计 ⚠️ 自动消失。
- **教训**：函数内条件分支里的延迟 import + 同名函数调用 = UnboundLocalError 陷阱；后续补采逻辑改动需保持 import 在每个调用路径前都已执行。

### 8. retest 进入判定收紧（2026-07-17，全仓三窗口 dd≤10%+n≥10+OR，已上线）

**retest 进入判定收紧：全仓三窗口 dd≤10%+n≥10+保留OR收益**（commits d07809b 后端 + 3e5125b 前端 + d11906a deploy）

- **背景**：用户质疑原判定 dd≤50%（腰斩都进）+OR 结构松+后端只看 y5 单窗口。数据验证：全仓 dd≤10% 筛 39% 激进策略（81/210），定额模式 dd 几乎都 ≤10%（206/210 门槛失效），yearly 无 y3/y1 滚动切片需后端改造。
- **用户决策**（AskUserQuestion 全选推荐）：全仓 dd≤10% + 后端加 y3/y1 切片（多窗口最严）+ n≥10 + 保留 OR 收益结构。
- **新判定规则**：`y5_dd≤10% && y3_dd≤10% && y1_dd≤10% && n≥10 && [(score≥0.6&&n≥30) || win≥55 || risk_adj≥1.0]`。近 5/3/1 年三窗口最大回撤均 ≤10%（多窗口最严）+样本量 n≥10+收益 OR 三分支任一。score/win/dd/n/ret 取 y5 全仓 pair_meta。risk_adj=ret/dd。
- **后端 lab_retest.py**（d07809b）：`_compute_y5_stats` -> 通用 `_compute_window_stats(df,...,window_years,sim_func)` 用 w_start=last_date-N 年重跑 simulate（非截取 equity_curve，保证 trades/equity_curve/stats 自洽）；新增 `_fmt_window_stats`；`_is_star_candidate(score,windows)` 改三窗口 dd 判定+n≥10+保留 OR；`run_retest_for_index` 第一趟算 y5/y3/y1 三窗口，pair_meta 新增 `windows:{y5,y3,y1}` 字段（向后兼容，top-level y5 的 score/n/dd/win/ret 保留不变）。
- **重跑结果**：9 指数 41 pairs（原 210，收紧 80.5%），规则违规 0，耗时 2.4s。3 指数 <3：cyb=1/bj50=2/sz50=2（这些指数波动大/历史短，多窗口 ≤10% 极严的自然结果；若上线后觉得 cyb 太少可调「三窗口」放宽为「两窗口」或「最差 ≤15%」）。各指数：sh=4/sz=4/cyb=1/kc50=10/bj50=2/sz50=2/hs300=3/csi500=8/csi1000=7。
- **前端双版 lab.js**（3e5125b）：3 处规则文案更新（title@2234/横幅@2269/_LAB_RETEST_RULE@2277）为三窗口 dd≤10%+n≥10+OR；⭐️徽章判定改方案 A（查 retest JSON 存在性，retestSet.has(buyKey|sellKey)），与后端必然一致，修旧「按选中窗口 state.labSimWindow 动态算」的不一致 bug；`_loadRank`@2894/3921 预加载 retest JSON（单信号+融合）。双版 diff=10（5URL×2）IDENTICAL。
- **上线**：build_min（lab.min.js 130KB -38.5%）+bump_asset_version（版本号 f2cbefda）+deploy.sh（d11906a 推 data+min JS）。

### 8. 二次测试二次推进：10 方向全闭环(2026-07-19)

> 任务来源：§4 brainstorm 的 10 方向中，选 7 方向推进。3 方向（手续费滑点/蒙特卡洛扰动/标的泛化）已由实施 agent 跑出结论，4 方向列待办。引擎零侵入：成本/蒙特卡洛均为外层包装，`lab_simulate.py` 仅加 `commission_rate=0.0, slippage=0.0` 参数（默认 0 向后兼容），不动现有 64 配对/融合回测产物。

#### 8.1 七方向评估表

| 方向 | 状态 | 工作量 | 可行性 | 关键产物 |
|---|---|---|---|---|
| 手续费/滑点敏感 | ✅ 已实施 | 半天 | 高（引擎加参数即可） | `lab_cost_compare.py`/`.json` |
| 蒙特卡洛扰动 | ✅ 已实施 | 半天 | 高（纯外层包装） | `lab_montecarlo.py`/`.json` |
| 标的泛化 | ✅ 已实施 | 半天 | 高（扩标的池重跑） | `lab_generalize.py`/`.json` |
| 参数敏感扫描 | ✅ 已实施 | 半天 | 中（复刻指标参数化网格扫描） | `lab_param_scan.py`/`.json` |
| 信号叠加消融 | ✅ 已实施 | 小时级 | 高（6硬编码融合N-1子集） | `lab_ablation.py`/`.json` |
| 多空对称 | ✅ 已实施 | 半天 | 高（新增镜像 simulate_short） | `lab_short_symmetry.py`/`.json` |
| 融合 P2 回测 | ⏳ 待办 | 全天 | 低（需从 signal_daily/HTML 解耦引擎，工作量最大，放最后） | 待开发 |

#### 8.2 方向1：手续费滑点（已实施）

- **改动**：`lab_simulate.py` 的 `simulate_full_in`(:183)/`simulate_fixed_10k`(:266) 加 `commission_rate=0.0, slippage=0.0`（默认 0 兼容）。买入 `shares=cash/(close*(1+slippage)*(1+commission_rate))`，卖出 `cash=shares*close*(1-slippage)*(1-commission_rate)`。
- **产物**：`lab_cost_compare.py` + `lab_cost_compare.json`(205KB)，对 top10 策略跑 3 成本档（毛/万3+千1/万5+千2）。
- **结论**：90 个盈利配对加成本后 **100% 仍盈利**。交易频率是成本敏感度决定因素：高频（MACD 金叉死叉 313 笔）衰减 **-55%** 收益腰斩；低频（C1_RSI30 仅 12-17 笔）衰减仅 **-5%**；趋势跟踪类（Donchian/Supertrend）衰减 -15~30%。分指数：上证/深证 -33% 最重，北证 -6%/创业板 -13% 最轻。

#### 8.3 方向2：蒙特卡洛扰动（已实施）

- **改动**：新建 `lab_montecarlo.py`（纯外层包装，不改引擎）+ `lab_montecarlo.json`(55KB)。
- **两类扰动**：方式 A 信号翻转（5/10/20% 翻转 buy/sell_mask，M=200 次）；方式 B 价格噪声（close 加高斯噪声 sigma=0.5%/1% 后重算信号，M=100 次）。top8 配对 × 3 指数（sh/cyb/kc50），seed=42。
- **结论**：24 个配对全部 **Moderate**。5% 翻转下全部 ≥95% 正收益（多数 100%），但 mean_ret 降到 baseline 的 **10-65%**，max_dd 从 18-31% 飙升到 **29-48%**。信号翻转影响 **远大于** 价格噪声（0.5% 噪声下收益保持 70-135%）。kc50 最稳定（cv 0.53-0.68），sh 最不稳定（cv 0.84-1.18，因 35 年复利放大）。Donchian20_up 系列信号时点容错性最好。
- **要点**：策略不是靠少数 lucky 信号（翻转 5% 不变亏），但收益幅度对信号时点高度敏感（最优时点贡献大部分超额收益）。

#### 8.4 方向3：标的泛化（已实施）

- **改动**：新建 `lab_generalize.py` + `lab_generalize.json`(10.7KB)。top6 配对在 31 个申万行业指数 + 18 只抽样个股上跑。
- **结论**：申万行业 = **强泛化**（正收益 87-97%，median +267%~+406%）；个股 = **弱泛化**（正收益 28-39%，median 全负，过拟合指数）。`MACD_golden|MACD_death` 是唯一中泛化配对（个股 profit 55.6%，median +22.2%）。`Vol_breakout` 在个股无效（profit 22-33%）。
- **要点**：策略适用于指数/行业级标的，不适用于个股（除 MACD 金叉配死叉勉强可用）。caveat：个股 close 为未复权价，除权日跳水触发假卖出系统性压低个股收益，但 profitable_pct 差距远超除权能解释。

#### 8.5 方向4：信号叠加消融（已实施）

- **改动**：新建 `lab_ablation.py`（不动 backtest_strategies.py，import 公开 helper + fusion_signals 的 `_gen_filter_masks`/`HARDCODED_FUSIONS`）+ `lab_ablation.json`(17KB)。对 6 硬编码融合做 N-1 子集消融（逐一去组件，3 指数 sh/hs300/cyb）。
- **方法**：每个融合 F 组件 [c1..cN]，full=AND全部，ablated_i=AND去ci；contribution_i=stats(full)-stats(ablated_i)，正值=该组件增益。2组件融合去一个=单信号基线，直接对比融合 vs 最佳单信号增益。
- **结论**：`D1_high20_drop5` 是核心驱动组件（avg_contrib +769%，88.9% 正贡献）--它作主信号时融合普遍增益。`MACD_below_signal`/`close_above_bl_2pct`/`MA60_bull` 作过滤条件 100%/67% 正贡献（过滤有效）。`BB_lower_revert`/`C1_RSI30` 作过滤组件时 0% 正贡献（avg_contrib -479/-278，过滤过严漏信号拖累）。`F_D1_MA_death` 在上证 full=+6482%（异常高，24 笔低频复利放大）。
- **要点**：卖侧融合（D1 系）增益明确，买侧融合（BB/C1 系）过滤反而拖累--买信号本就稀少，再 AND 过滤会漏掉关键反弹时点。

#### 8.6 方向5：多空对称（已实施）

- **改动**：`lab_simulate.py` 新增 `simulate_short`（~50 行做空镜像函数）+ 新建 `lab_short_symmetry.py` + `lab_short_symmetry.json`(37KB)。9 指数 × top8 配对，full_in 全历史窗口。
- **simulate_short 会计**：卖信号开空 shares=cash/short_price，cash=0；买信号平仓 cash=shares*(2*short_price-cover_price)，即 cash*(1+ret_short)，与做多 shares*sell_price=cash*(1+ret_long) 对称。持仓空头期末估值=shares*(2*short_price-last_close)（涨市可能转负）。
- **结论**：72 配对 **做多 100% 盈利，做空仅 9.7% 盈利**。65 个"做多盈做空亏"（典型长牛漂移），仅 7 个两端皆盈（趋势型）。平均 symmetry_ratio=-0.19（理想=-1，差距大）。仅北证50 做空 87.5% 盈利（历史短+曾大跌）。上证/深证做空亏损最惨（-2742%/-1461%，35 年长牛复利反噬）。
- **要点**：**卖信号只适合止盈多头，不适合反手做空**。A股长期向上漂移使做空结构性劣势，卖信号的"方向正确性"（forward-return 下跌概率）无法转化为做空盈利--因为做空需承受无限上行风险且长牛漂移吃掉所有做空收益。

#### 8.7 方向6：参数敏感扫描（已实施）

- **改动**：新建 `lab_param_scan.py`（不动 backtest_strategies.py，import 公开指标函数 rsi/ma/macd/bollinger/donchian/supertrend/_cross_up/_cross_down，脚本内参数化复刻信号生成）+ `lab_param_scan.json`(49KB)。7 策略 × 3 指数（sh/hs300/cyb），买侧扫描配固定 D1 卖，卖侧扫描配固定 C1 买。
- **网格**：C1_RSI30(5周期×5阈值=25)、BB_lower_revert(4n×4k=16)、Donchian20_up(7周期)、Supertrend_buy(4周期×5mult=20)、D1_high20_drop5(4周期×4回落=16)、BB_upper_revert(4n×4k=16)、Donchian10_down(4周期)。共 104 组合 × 3 指数 = 312 次回测。
- **稳定性判定**：neighbors=与默认参数某维相差1步的组合；stable_plateau=默认ret>0且neighbor_avg≥0.7×default；sharp_peak=best>1.5×neighbor_avg且best≠default（孤立尖峰=过拟合风险）；robust_profitable=>50%组合盈利。
- **结论**：`Donchian20_up`/`Supertrend_buy` = **robust_profitable**（3 指数全稳定高原，所有组合盈利，默认参数非孤峰，不过拟合）。`C1_RSI30`/`BB_lower_revert`/`BB_upper_revert` = **sharp_peak**（默认参数 ret 低甚至负，最佳参数是远离默认的孤立尖峰，过拟合风险高--生产用的默认参数并非最优，但换成"最优"参数又是过拟合）。`D1_high20_drop5`/`Donchian10_down` = 混合（cyb 稳健，sh/hs300 尖峰）。
- **要点**：趋势跟踪类（Donchian/Supertrend）参数鲁棒（平坦高原），适合生产；均值回归类（RSI/BB）参数敏感（尖峰），默认参数保守但非最优，调参易过拟合，维持默认最安全。

#### 8.8 方向7：融合 P2 回测（已实施，2026-07-19）

- **目标重定义**：原 §28.8.8 旧表述"解耦 simulate_trade.py 3路径引擎对91融合候选跑回测"为过时理解（重复 §31 的 lab_simulate.py --fusion 已做的 mask 级回测，低价值且破坏 trade_sim.html 风险）。P2 真实增量 = **链路一致性验证**：从 signal_daily 表读生产环境实际触发的信号，对比回测引擎独立算的信号，验证生产链路 = 回测链路（回测可信）。
- **认知纠正**：signal_daily 表 signal 字段实测只有 buy/buy_aux/sell 3 值，**不存融合信号**。但生产 sell 本身 = D1_high20_drop5 & MA60_bull & MACD_below_signal = **融合策略 F_D1_S1_MACD**（fusion_signals.py:128）；生产 buy = RSI 上穿30 = C1_RSI30；生产 buy_aux = BB 下轨回归 = BB_lower_revert。故一致性验证可行，映射：buy->C1_RSI30 / buy_aux->BB_lower_revert / sell->F_D1_S1_MACD。
- **指标等价性**：生产 signals.py 与回测 backtest_strategies.py 各有一套 RSI/Bollinger/MACD/MA60，逐个核对数学等价（backtest 注释"复刻 signals._rsi"；MACD ewm(span=N) 与 ewm(alpha=2/(N+1)) 等价；Bollinger 两边 std ddof=0；MA60 两边 min_periods=60）。差异不来自算法实现。
- **实现**：新建 `scripts/lab/lab_fusion_p2.py`（不碰 simulate_trade.py 3路径引擎，不碰 a-stock-data/backtest_strategies.py 公开项目）。对 9 指数从 signal_daily 读 buy/buy_aux/sell 日期集合，用 backtest_strategies+fusion_signals 同款实现算 C1_RSI30/BB_lower_revert/F_D1_S1_MACD mask 日期集合，对比一致率 + 差异归因。输出 `static-site/data/lab_fusion_p2.json`（21KB）。
- **结果（9 指数 × 3 信号一致率）**：

  | 生产信号 | 回测 mask | 一致率 | 生产覆盖 | 说明 |
  |---|---|---|---|---|
  | sell | F_D1_S1_MACD | **100%**（497/497） | 100% | 9 指数全 100%，生产 sell = 融合策略，链路一致性坐实 |
  | buy | C1_RSI30 | **97.1%**（726/741） | 99.0% | 8 指数 100%，仅 kc50 21.4%（per-index rsi_cross_25） |
  | buy_aux | BB_lower_revert | **68.8%**（890/890） | 100% | 生产 100% 覆盖；差异全是回测多算 |

- **核心结论：生产覆盖 100%**。除 kc50 buy（per-index 阈值差异）外，所有生产信号 100% 被回测 mask 覆盖（prod_cover_pct=100%），回测未漏算任何生产信号。差异全部是回测多算（lab_only），来源明确，非算法 bug。**回测可信，生产链路 = 回测链路验证通过**。
- **3 差异来源（已知，非 bug，全部量化）**：
  1. **per-index filter**（indicators.yaml 配置）：kc50 buy=rsi_cross_25（生产上穿25 vs 回测上穿30，7 个穿25未穿30 + 15 个穿30未穿25）；csi1000/cyb buy_aux=rsi_cross_40（生产多一层 RSI 上穿40 过滤，cyb 72 + csi1000 52 = 124 个被过滤）。
  2. **去重**（生产 C1 同日优先）：生产 buy_aux_set = buy_aux - buy_set（同日 C1 触发则不发 buy_aux），回测 BB_lower_revert 不去重 -> 277 个回测多算（sh64/sz56/cyb27/bj50 5/sz50 29/hs300 40/csi500 33/kc50 5/csi1000 20）。
  3. **sell**：无 per-index 无去重，预期完全一致，**已验证 100%**（497/497）。
- **上线**：commit + deploy.sh 推 `static-site/data/lab_fusion_p2.json`。

#### 8.9 关键文件路径

- 引擎：`scripts/lab/lab_simulate.py`（加 commission/slippage 参数 + simulate_short 做空镜像）
- 成本对比：`scripts/lab/lab_cost_compare.py` + `static-site/data/lab_cost_compare.json`
- 蒙特卡洛：`scripts/lab/lab_montecarlo.py` + `static-site/data/lab_montecarlo.json`
- 标的泛化：`scripts/lab/lab_generalize.py` + `static-site/data/lab_generalize.json`
- 信号消融：`scripts/lab/lab_ablation.py` + `static-site/data/lab_ablation.json`
- 多空对称：`scripts/lab/lab_short_symmetry.py` + `static-site/data/lab_short_symmetry.json`
- 参数扫描：`scripts/lab/lab_param_scan.py` + `static-site/data/lab_param_scan.json`

## §29 QVIX 指标名中文化：中国波指300/1000（2026-07-17，commits 43d134a + 40e2da5 deploy）

> 与 §23 的 15fe67f 区别：15fe67f（07-15）只是「qvix(1000)停采方案C + 前端⏸停更」顺便提到中文名，`INDEX_NAMES` 映射早有但多处硬编码英文没走映射。本次 43d134a（07-17）是用户反馈首页「QVIX(300ETF) 21.25 点」仍是英文后，彻底统一去英文后缀的中文化收口。

### 背景
- 用户反馈首页「QVIX(300ETF) 21.25 点」不是中文。
- QVIX = 300ETF 期权隐含波动率指数（对标美国 VIX；中证官方 iVIX 2018 停发后，期权论坛 optbbs 等民间按 VIX 方法论用 300ETF 期权 IV 算的替代），direction: negative（越高越恐慌）。
- `a_qvix_300` = 300ETF 期权；`a_qvix_1000` = 中证1000期权。

### 根因
- `app.js:303` `INDEX_NAMES` 已有「中国波指300」映射，但 4025 等处硬编码英文「QVIX(300ETF)」没用映射。
- `config/indicators.yaml:40-41` 的 `name` 也是英文。

### 改动
- **config/indicators.yaml:40-41 + static-site/data/metrics.json**：`name` `QVIX(300ETF)`->`中国波指300`，`QVIX(1000ETF)`->`中国波指1000`（`export.py` 从 yaml 读 name，deploy 后产物同步）。
- **双版 app.js**（web + static-site 逐字相同，行号因静态版特有函数偏移）：
  - 4025/4098 extras 去英文后缀：「中国波指300 QVIX(300ETF)」->「中国波指300」
  - 1571/1636 数据源栏 `name`「QVIX」->「中国波指」+ hint 改「中国波指（期权隐含波动率）」
  - 3796/3861 分组名「情绪指数(QVIX/换手率)」->「情绪指数(波指/换手率)」
  - 3815/3880 短标签「QVIX300」->「波指300」
  - 303/310 `INDEX_NAMES` 验证已中文，无需改
- **双版 index.html** 版本号刷新（bump_asset_version）

### 验证
- `grep "QVIX(300ETF)"/"QVIX(1000ETF)"/"QVIX300"/name:"QVIX"` 全 0 残留。
- 双版波指相关行内容一致（行号因静态版特有函数偏移）。
- build_min（app.min.js -42%）+ bump_asset_version + deploy 上线。

### 效果
首页「QVIX(300ETF) 21.25 点」->「中国波指300 21.25 点」。


## §30 融合信号实验卡片信息对齐单一信号基标（2026-07-17，已完成）

### 背景
用户反馈：融合信号实验里"部分上线生产/已上线生产/实验中"卡片点击后，信息不如单一信号实验卡片全面，"只有一个策略说明"。定基标：**融合信号实验卡片信息量 ≥ 单一信号，至少持平不得更少**。开发顺序：①单一信号先固化作基准 ②融合后开发补齐 ③二次测试实验再开发。

### 根因（已确认）
融合弹窗 `_labFusionPairModalRender`（web/lab.js@3655 / static-site 同步）有两个分支，两类卡片各有缺失：

1. **6 硬编码融合策略**（`LAB_FUSION_STRATEGIES`@598，无 `_pairType`/`_buyKey`/`_sellKey`）：
   - 覆盖三状态：live（F_D1_S1_MACD、F_D1_S1）、partial（F_B1_RSI40、F_B1_rebound2pct）、experimental（F_C1_MACD_golden、F_D1_MA_death）
   - 走 `if (!meta._pairType)`@3661 -> `_labFusionHardcodedHTML`@3635 -> **只渲染 6 段文案**（组成条件/触发/回测结论/理论/场景/备注）
   - 缺：指标图表、模拟回测（4数字+净值+交易记录）、买卖信号弹窗
   - 代码注释 @3634 自标"Bug-A：6个无 _pairType 的策略，不走配对回测"——遗留缺口
   - 为何没回测：这 6 个是多条件融合（如 D1+MA60+MACD 三条件），非 91 候选的简单买×卖配对，`lab_sim_fusion_stats.json` 无现成 pairKey

2. **91 自动候选**（`_generateFusionCandidates`@669，带 `_pairType`：49 买×卖 + 21 买×买 + 21 卖×卖）：
   - 走配对分支 -> 有回测数据（modeBar+winBar+_labSimModeBlock=4数字+净值+交易记录+指数选择器）
   - 缺：策略说明文案（触发/理论/场景/结论）、指标图表、买卖信号弹窗

### 基标（单一信号 renderLabDetail@1816，5 块全有）
| 信息块 | 单一信号 | 融合-6硬编码 | 融合-91候选 |
|---|---|---|---|
| ①标题+状态标签+买卖侧 | ✅ | ✅(仅标题) | ✅(仅标题) |
| ②自白黄块 | ✅ | ❌ | ❌ |
| ③📖策略说明(触发/理论/场景/注意/结论+指标释义折叠) | ✅ | ✅(缺指标释义) | ❌ |
| ④指标图表(echarts曲线+信号标注+窗口切换+指数选择) | ✅ | ❌ | ❌ |
| ⑤💰模拟回测(4数字+净值+交易记录+全仓/定额+配对切换+买卖信号弹窗) | ✅ | ❌ | ✅(缺买卖信号弹窗) |

### 开发计划（按用户定顺序）
1. **单一信号固化**：确认 5 块无遗漏（renderLabDetail 已含全，作基准标尺）
2. **融合补齐**：
   - 6 硬编码：补 ⑤回测（映射 pairKey 或后端补算）+ ④图表 + ②自白 + 买卖信号弹窗
   - 91 候选：补 ③策略说明文案 + ④图表 + ②自白 + 买卖信号弹窗
3. **二次测试实验**：融合达标后再开发

### 实施记录（2026-07-17 commit 4a3a5c5 已上线）
- **step1 单一信号基准**：确认 `renderLabDetail`@1816 实含 6 块（①标题标签 ②自白 ③📖策略说明+指标释义 ④指标图表echarts ⑤📊多周期回测矩阵 ⑥💰模拟回测配对交易），作基准标尺无遗漏。
- **step2 融合补齐**：
  - 6 硬编码（LAB_FUSION_STRATEGIES@598）加 `_coreKey` 字段映射核心单一策略：F_D1_S1_MACD/F_D1_S1/F_D1_MA_death→D1_high20_drop5，F_B1_RSI40/F_B1_rebound2pct→BB_lower_revert，F_C1_MACD_golden→C1_RSI30。三者均在 sim stats（8 partners）+ LAB_CHART_KEYS（有图表）。
  - `_labFusionPairModalRender`@3667 `!meta._pairType` 分支：有 `_coreKey` 时渲染"融合策略说明文案(_labFusionHardcodedHTML) + 分隔提示 + 核心策略全量详情(renderLabDetail 渲染到 .lab-fusion-core-detail 子容器)"，达单一信号基标（策略说明+图表+矩阵+回测）。
  - 91 候选（_pairType 分支）：回测数据前补策略说明文案（组成条件/触发/结论，复用 .lab-fusion-hardcoded 样式）。
  - `_labFusionPairCloseModal` 增强：关闭时释放 echarts 实例 + 清 state._labSimRerender/_labChartRerender（照搬 _labSignalDetailCloseModal，防内存泄漏）。
  - 新增 .lab-fusion-core-divider/.lab-fusion-core-detail CSS。
- **代理说明**：6 硬编码是多条件融合（如 D1+MA60+MACD 三条件），非 91 候选的简单买×卖配对，lab_sim_fusion_stats.json 无现成 pairKey。用核心单一策略回测作代理（弹窗已标注"核心策略回测供参考"），达信息量基标。真实融合回测需后端为这 6 个多条件融合单独算，属后续增强。
- **剩余增强**：91 候选补指标图表 echarts（融合是双策略，需设计双策略图表展示方案）。
- 双版 lab.js+lab.css 同步，build_min+bump_asset_version，已 push main，GitHub Pages lab.min.js?v=13ec0afd 已上线验证。

## §31 6硬编码融合策略补跑真实回测：去 _coreKey 代理，多条件AND融合（2026-07-17，commits 2ff5082 + 5ccaa00）

> 承接 §30：§30 的 4a3a5c5 用 `_coreKey` 让 6 硬编码融合策略拿核心单一策略回测作代理（弹窗标"核心策略回测供参考"），仅达信息量基标。用户质疑数据准确性——代理数据并非融合策略真实表现。本次补跑真实融合回测，彻底去代理。

### 背景
6 个硬编码融合策略（如 F_D1_MA_death"D1回落5%+MA5/20死叉 融合卖"）弹窗此前用 `_coreKey` 代理，拿核心单一策略（如 D1_high20_drop5）的回测数据冒充融合策略，且带"已上线生产"标签误导用户。本次为这 6 个多条件融合单独算真实回测。

### 改动（不动 backtest_strategies.py）
1. **scripts/lab/fusion_signals.py**（+86 行）：
   - `_gen_filter_masks(df)`@137：4 个过滤 mask，语义照生产 `app/compute/signals.py`：
     - `MA60_bull`（状态 close>MA60，signals.py:367-369）
     - `MACD_below_signal`（状态 DIF<DEA，signals.py:377，非穿越）
     - `RSI_cross_40`（穿越 rp≤40 & r>40，signals.py:345）
     - `close_above_bl_2pct`（状态 close>下轨*1.02，signals.py:349）
   - `HARDCODED_FUSIONS`@127：6 条定义（pair_id/side/fusion_keys/ref_side）：
     - F_D1_S1_MACD(sell): D1_high20_drop5 & MA60_bull & MACD_below_signal | 基线 C1_RSI30
     - F_D1_S1(sell): D1_high20_drop5 & MA60_bull | 基线 C1_RSI30
     - F_B1_RSI40(buy): BB_lower_revert & RSI_cross_40 | 基线 D1_high20_drop5
     - F_B1_rebound2pct(buy): BB_lower_revert & close_above_bl_2pct | 基线 D1_high20_drop5
     - F_C1_MACD_golden(buy): C1_RSI30 & MACD_golden | 基线 D1_high20_drop5
     - F_D1_MA_death(sell): D1_high20_drop5 & MA_death_5_20 | 基线 C1_RSI30
   - `gen_hardcoded_fusion_candidates(df)`@164：主信号 & 过滤条件**同日 AND 取交集**（复用 buy_buy/sell_sell 的 m1&m2 机制扩展到多条件），pair_type=hardcoded_buy/hardcoded_sell。
2. **scripts/lab/lab_simulate.py**：`candidates = gen_fusion_candidates(df) + gen_hardcoded_fusion_candidates(df)`（97 候选同跑：91 自动 + 6 硬编码）。
3. **9 指数重跑**：生成 54 个真实 F_ pair 数据（9 指数 × 6），写入 `lab_sim_*_fusion_stats.json`/`_full.json`。
4. **前端 web/lab.js + static-site/lab.js**：
   - 删 `_coreKey` 代理分支（LAB_FUSION_STRATEGIES 6 条的 `_coreKey` 字段全删）。
   - 卡片 onclick 传 `{...meta, _fusionKey: key}`。
   - `_labFusionPairModalRender` 重构：6 硬编码走真实融合回测数据（复用 91 候选分支 B 渲染：指数选择器/模式切换/窗口切换/交易记录分页），头部保留完整组成条件/触发/回测结论/理论/场景/备注。
   - 双版同步：diff 只剩 5 处 URL（/static/data/ vs ./data/）。

### 数据预警（数据说话，不阻塞）
- F_C1_MACD_golden 样本极小（0-8 笔）：两穿越事件同日罕见，kc50 无交易（n=0），前端显示"无交易数据"。
- F_D1_MA_death 部分小样本（bj50 n=1）。
- 这是多条件 AND 融合的固有特性（条件越严交易越少），非 bug；前端已能正确处理 n=0/小样本。

### 上线
- build_min.py（lab.min.js -38.5%）+ bump_asset_version.py（lab.min.js?v=850935c9）+ deploy.sh 推 main（afdafdf..5ccaa00）。
- commit 2ff5082（代码+数据）+ 5ccaa00（data update [all]），origin/main=5ccaa00 push 成功。

### 验收（主控逐字验证）
- `fusion_signals.py`：HARDCODED_FUSIONS@127 + _gen_filter_masks@137（4 mask 齐）+ gen_hardcoded_fusion_candidates@164 ✓
- 双版 lab.js `_coreKey` 残留 = 0 ✓
- `_labRankAggregate`@2211 retest 行未碰（仍是 `r.buyKey + "|" + r.sellKey` 修复版）✓
- 线上 csi500 fusion_stats：97 pairs（91+6），6 个 F_ pair 全在，generated_at 2026-07-17 ✓

## §32 融合实验策略弹窗 3 缺失块回归修复（2026-07-17，commit 8c49292）

> 承接 §31：§31 的 2ff5082 在重构 `_labFusionPairModalRender` 去 `_coreKey` 代理时，把 6 硬编码分支从 `renderLabDetail(coreKey)` 全量渲染（信号图 / 多周期回测矩阵 / 模拟回测 / 查看买卖信号 4 块）改为只调 `_labSimModeBlock`（5 参），结果丢了 3 块。用户反馈融合弹窗里信号图 / 矩阵 / 买卖信号按钮不见了。8c49292 把这 3 块接回，对齐单一信号弹窗的渲染基准。

### 根因（回归引入点）
`_labFusionPairModalRender` 重构后 6 硬编码分支只保留"模拟回测配对块"（`_labSimModeBlock` 前 5 参），但：
- 信号图（echarts 信号图）整段未渲染；
- 多周期回测矩阵（`renderLabMatrix`）未渲染；
- 查看买卖信号按钮本应由 `_labSimModeBlock` 第 6 参 `signalBtnHTML` 注入，但该参未传（实参只到第 5 参 `isOpen`）。

即弹窗从 4 块退化成 1 块，属功能回归，非数据问题。

### 修复要点（web/lab.js + static-site/lab.js 双版同步）
1. **函数顶部 echarts dispose + generation counter**：re-render 时先 dispose 旧 echarts 实例防内存泄漏；用 generation 计数防止 stale async（旧请求返回晚）覆盖新渲染结果。
2. **chartBaseKey 取值**：6 硬编码用 `FUSION_CHART_BASE[F_key]`，91 候选用 `_buyKey`（与单一信号弹窗基准一致）。
3. **Promise.all 并行加载**：`fetchLabFusionSimData` + 指数 OHLC + `fetchLabMatrixData` 三路并行，避免串行等待。
4. **信号图**：`_labBuildChartConfig` + `_labChartSlice` + `renderLabChartEx` 渲染进占位 div（`chartSectionHTML`）。
5. **多周期矩阵**：`renderLabMatrix` + `_labUpdateMatrixRowHighlight`（`matrixSectionHTML`）。
6. **查看买卖信号**：按 `pair_type` 推导 buy/sell key——
   - `buy_buy` / `sell_sell` 用 `fusion_meta.ref_side` 补反面；
   - `hardcoded_buy` / `hardcoded_sell` 用 `FUSION_CHART_BASE` + `ref_side`；
   - 构建 `signalBtnHTML` 传 `_labSimModeBlock` 第 6 参（此前漏传的第 6 参补回）。
7. **bodyHTML 组装**：`chartSectionHTML` + `matrixSectionHTML` 在 6 硬编码、91 候选两个分支都加进去。
8. **不重新引入 `_coreKey` 代理**：模拟回测仍走真实 `F_pair` 融合回测数据，`FUSION_CHART_BASE` 仅用于图表 / 矩阵 / 按钮的 baseKey 取值。

### 上线
- commit 8c49292（代码改动，双版 lab.js 同步），origin/main = 8c49292 push 成功。

### 验收（主控逐字验证）
- origin/main = 8c49292 push ✓
- `_labFusionPairModalRender` 函数体内 3 块接回：信号图（`chartSectionHTML`）+ 矩阵（`matrixSectionHTML` + `renderLabMatrix`）+ `signalBtnHTML` 传 `_labSimModeBlock` 第 6 参 ✓
- `_coreKey` 未重新引入（全仓仅 665 行注释一句"非 `_coreKey` 代理"提及，无实参 / 字段）✓
- `_labRankAggregate` 未碰（仍 `r.buyKey + "|" + r.sellKey`）✓
- 双版 lab.js diff 只剩 5 处 URL（`/static/data/lab/` vs `./data/lab/`：lab_backtest / lab_backtest_idx / lab_sim_idx_stats / lab_sim_idx_fusion_stats / lab_retest_idx）✓

## §33 融合弹窗对齐单一信号弹窗（2026-07-17，commit 854e6cc + deploy 6efd745）

> 承接 §32：§32 的 8c49292 只接回 3 块，但矩阵用 `chartBaseKey` 基础策略代理 + 缺配对买点 / 卡片切换，没完全对齐单一弹窗。用户预期：融合实验 = 单一实验进阶版，单一弹窗有的融合都要有，仅策略信号从单一变融合信号。

### 实施要点
1. **信号图方向 B**（用户选）：前端 `_labBuildFusionChartConfig` 实现融合 AND 信号计算画融合信号点，非基础策略代理（LAB_CHART_KEYS 只含 22 单一策略无融合 AND，故需前端实现；失败回退 `chartBaseKey` 代理）。
2. **后端** `lab_matrix.py` 新增 `run_fusion_matrix()` 生成 `lab_backtest_fusion_{idx}.json`（97 候选 ×5 窗口 ×4 horizon，F_ 策略有数据）；`lab_simulate.py` 补 6 硬编码 `F_xxx` ×8 反向 partner（48 组，fusion_stats pairs 总数 145 = 97+48）。
3. **前端双版 lab.js 6 处改造**：矩阵 `fusionMatrixData.strategies[pairId]` 非代理 @4040 + 信号图 `_labBuildFusionChartConfig` 融合 AND 方向 B @4016 + 6 硬编码配对卡片 `m.pair` 局部管理（防与单一弹窗全局 state 冲突）+ 自白黄块 `_labWarningEssayHTML` + 91 候选补成分策略 theory/scenario/note/report（details 折叠）。
4. **上线**：build_min + bump（版本 ecdd1c6f）+ 双版 diff 只剩 URL + commit 854e6cc + ff main + deploy 6efd745 + 线上 s.aisusu.cn 验证 200。

### 验收（6 项全通过）
- 融合矩阵双版 97 策略 6 F_ ✓；前端矩阵 `strategies[pairId]` 非代理 ✓；信号图 `_labBuildFusionChartConfig` ✓；双版 diff 只剩 URL ✓；git push 854e6cc + 6efd745 ✓；线上 200 ✓。
- 原 agent ad09ea81 卡死（没 echo 致 10 分钟盲区），重派 aea32ba4 读遗留接手完成（后端原 agent 已做完，前端 6 处改造 + 上线重派完成）。

## §34 retest 维度榜荣誉共享标注（2026-07-17，commit a27ebba）

> 用户需求：二次测试维度榜排行榜每行标注策略在其他（指数 × 窗口）下的排名荣誉（近 10 年第 1 / 近 5 年第 2 / 科创 50 第 1 等），多层次定位好排名策略（一次好不代表什么，多层次好才更好）。

### 实施要点
1. **后端** `scripts/lab/lab_retest_honors.py` 精确复刻 `_labRetestRankRows` 排名逻辑（双模式 + min-max 同群），9 指数 ×5 窗口（all/y10/y5/y3/y1）Top3，`pairKey -> [{idx,win,rank}]`，输出 `lab_retest_honors.json`（18 pairs / 115 荣誉，双版一致 4698 字节）。
2. **前端** `_labRetestHonorsHTML` 徽章（🥇🥈🥉 + 标签，排除当前 idx/win，最多 4 枚）+ `_labRetestHonorJump` 点击跳转（同 idx 切窗口 / 跨 idx reload）+ `lab.css` 金银铜配色 + `stopPropagation` 防触发行弹窗。
3. **窗口用全 5 窗口**（`LAB_WIN_DEFS`，与榜单一致），非 retest pair_meta.windows（y5/y3/y1 候选门槛子集）。
4. **上线**：双版同步 + commit a27ebba + ff main + 线上 s.aisusu.cn 200。

### 验收（5 项通过）
- 荣誉表双版生成 + push a27ebba ✓；双版 diff 只剩 URL ✓；徽章函数双版 ✓；未碰 `_labRankAggregate` ✓。

## §35 buy_aux（BB 下轨回归辅买点）回测覆盖（2026-07-17）

> 背景：signal_stats.json 已含 g.cn10y buy_aux 前向统计（app/compute/signal_stats.py 基于生产 signal_daily 信号算，前端 tips 显示）。但 a-stock-data/backtest_metrics.py（公开项目 simonlin1212/a-stock-data，不可改）只覆盖 C1 主买（RSI 上穿）+ 卖点参数网格，未覆盖 buy_aux（BB 下轨回归辅买点）。本节补齐 buy_aux 回测。

### 实施
1. **新写 `scripts/backtest_buy_aux.py`**（不动 a-stock-data/、不改 backtest_strategies.py）：自复刻 signals.py 的 RSI(14) + Bollinger(ddof=0) + buy_aux 生成（BB 下轨回归：前一日 value<下轨 且当日 value>下轨）+ C1 去重（与 C1 同日保留 C1 主买，与生产一致）+ per-index filter（rsi_cross_40 / close_above_bl_2pct）。
2. **参数网格**：n_std ∈ {1.5, 2.0, 2.5} × filter ∈ {none, rsi_cross_40, close_above_bl_2pct} × horizon ∈ {5, 10, 20}，覆盖 11 个 global 指标 + 2 个情绪分。
3. **收益双口径**：百分比（(shift(-h)/s-1)×100，与 signal_stats 一致）+ 绝对值（shift(-h)-s，与 backtest_metrics 一致）。

### 关键验证：cn10y buy_aux 完美复现生产统计
本脚本自生成 buy_aux 信号（σ2.0+none 基线）与生产 signal_stats.json **完全一致**：
- buy_aux 10d：n=67，胜率=0.5373，盈亏比=0.8083（生产同值）
- buy_aux 5d：n=67，胜率=0.4925，盈亏比=0.6561（生产同值）
- buy_aux 20d：n=67，胜率=0.4179，盈亏比=0.7316（生产同值）
- C1 主买 10d：n=56，胜率=0.4821，盈亏比=0.7392（生产 buy 同值）

证明 buy_aux 复刻逻辑（BB 下轨回归 + C1 去重）与生产 signals.py 完全对齐，回测可信。

### cn10y 结论：buy_aux 10d 优于 C1 主买
| 信号 | n | 10d胜率 | 10d盈亏比 | 10d均值% |
|---|---|---|---|---|
| C1 主买(RSI上穿30) | 56 | 48.21% | 0.74 | -0.3547 |
| buy_aux 基线(σ2.0) | 67 | 53.73% | 0.81 | -0.0559 |
| buy_aux σ1.5 | 93 | 39.78% | 1.02 | - |
| buy_aux σ2.5 | 34 | 50.00% | 0.93 | - |

- buy_aux 基线 10d 胜率(53.73%)/盈亏比(0.81)双优于 C1(48.21%/0.74)，均值亏损更小(-0.056 vs -0.355)。
- 基线 σ2.0+none 已是最佳：rsi_cross_40 样本不足(n=11)，close_above_bl_2pct 在 cn10y 无信号(反弹2%门槛对收益率序列太严)。
- 20d 维度 buy_aux 胜率(41.79%)优于 C1(35.71%)，但盈亏比(0.73)略低于 C1(0.86)。

### 其他序列亮点（样本>=10 且胜率>60% 或盈亏比>2）
- g.us10y σ2.0+close_above_bl_2pct：n=16，10d 胜率 75%，盈亏比 4.52（强）
- g.comex_silver σ1.5+close_above_bl_2pct：n=12，10d 胜率 83.3%，盈亏比 2.99（样本少）
- g.a_qvix_1000 σ2.0+close_above_bl_2pct：n=14，10d 胜率 71.4%
- s.cross_market σ2.5+rsi_cross_40：n=10，10d 胜率 80%（样本少）

### 落档
- 脚本：`scripts/backtest_buy_aux.py`
- JSON：`static-site/data/buy_aux_backtest.json`（可推上线，含每序列 buy_aux 最佳参数 + C1 对比 + 全网格）
- 本节 NOTES §35

## §36 交易记录不从 10w 起步修复（2026-07-17，commit f0e5182）

> 背景：用户报推荐榜排名详情「总收益率/交易纪律末条、期末金额/末笔记录」对不上，交易记录不从 10w 起。根因：commit 7b68bf0 修了 `_labPairWinData`（web lab.js:815 `const wtd = md.win_trades && md.win_trades[win]`）优先读 win_trades（每窗口独立 sim 的 trades，at/cp 从 INITIAL_CAPITAL=10w 起算，与该窗口 final_total/total_ret 同源同口径），后端 full JSON 也已含 win_trades/win_base_cp（已验收 sh full 128/64 pairs 全有、fusion full 290/145 全有）。但 **4 处 fetch 合并块漏搬 win_trades/win_base_cp**，导致 `_labPairWinData` 读不到回退旧 trades（全史切片 + win_base_cp 调分母，at 不调、分母错），三处全对不上。

### 漏搬点（双版各 2 处，共 4 处）
- `fetchLabFusionSimFullData`：web lab.js:1415 / static-site lab.js:1415
- `fetchLabSimFullData`：web lab.js:1523 / static-site lab.js:1523
- 4 处合并块原只搬 `equity_curve/trades/tw`，各补加 `sp[mode].win_trades = fp[mode].win_trades;` + `sp[mode].win_base_cp = fp[mode].win_base_cp;`（共 8 行，双版同步）

### 受影响 5 入口（共用 `_labPairWinData`，无一在运行时用上 win_trades）
1. 模拟回测左侧卡片交易记录（`_labSimModeBlock`）
2. 推荐榜弹窗排名详情
3. 二次测试弹窗
4. 融合排行榜弹窗
5. 91 候选弹窗

### 教训
- **改数据读取层要同步改所有合并/搬运点**：7b68bf0 改了 `_labPairWinData`（读取层）读 win_trades，但没同步改 fetch 合并块（搬运层）搬 win_trades，致读取层改了数据层没跟上。以后改读取字段，要 grep 所有 fetch/合并/EnsureFull 路径确认字段贯通后端→搬运→读取三段。
- 纯前端修复（8 行），无需重跑后端/JSON（full JSON 已含 win_trades）。改完 `build_min.py` + `bump_asset_version.py` + 双版 diff 归一化（=0）+ `deploy.sh` 上线。
- 验收：线上 `lab.min.js?v=9f0c7a67` 含 win_trades 搬运代码；根 `data/signal_stats.json` 保持 M 未推（§8）。
- 本节 NOTES §36

---

## §37 网安合规审计与修复（2026-07-18）

### 审计背景
用户要求网安合规审计视角检查站点，完成 P0-P3 分级风险修复 + 品牌更名 + 域名变更。本节落档全量修复项、品牌更名、域名变更及 MaoziYun 托管 limitation。

### P0-P3 修复落地
- **P0-1 ICP 备案**：s.sugas.site（.site 国际域名）走 MaoziYun 境外托管不需 ICP；footer ICP 占位隐藏（HTML 注释保留待国内备案启用）；原 s.aisusu.cn（.cn 未备案）风险随弃用消除
- **P0-2 证券投资咨询资质**：强化教育/研究工具定位，弱化推荐语义 12 项--凯利"建议仓位"->"公式计算（研究参考）"；推荐榜->配对对比榜/综合评分；绝对化"并列第1/最高/最强/最佳互补"->"并列靠前/较高"；首页 risk-banner 非持牌声明；实验室自白置顶；分享图 canvas 水印免责；trade_sim 批量页 title 买卖点->技术信号+免责常驻
- **P1-1 百度统计**：保留 + 新建隐私政策页 privacy.html（站点性质/采集/Cookie/第三方服务/未成年保护/免责）
- **P1-4 manual API**：本地调试不公网，暂缓（未来公网加 token）
- **P2-1 CSP**：_headers 加 CSP-Report-Only（MaoziYun 不处理 _headers，未来迁移 CF 生效）
- **P2-2 .map 下线**：build_min.py 移除 source-map + git rm app/lab.min.js.map + .gitignore 加 *.map
- **P2-3 postMessage**：'*' -> window.location.origin（同源 iframe，dev/prod 通用）
- **P2-4 SRI**：跳过（同源自托管无安全增益 + hm.js/push.js 动态注入 hash 不稳定）
- **P2-5 数据来源**：footer 加「东方财富/腾讯财经/baostock/同花顺等公开来源」
- **P2-6 og域名**：canonical/og:url/og:image 改 s.sugas.site
- **P3-1 HSTS**：_headers 加 preload（MaoziYun 不生效，自带 max-age=63072000）
- **P3-2 安全头**：_headers 加 nosniff/X-Frame-Options/Referrer-Policy/Permissions-Policy（MaoziYun 不生效，Referrer-Policy 经 meta referrer 兜底）
- **P3-3 绝对化用语**：改（含 P0-2）
- **P3-4 腾讯API**：privacy.html 第三方服务节声明（线上无后端不代理，前端直拉保留+声明）

### 品牌更名
市场温度看板 -> 信号实验室（中文展示位），tdsignal/trade-data-signal 保留作英文副标识（中英并行）；策略实验室 tab -> 策略实验（避免与品牌名重叠）；域名 s.aisusu.cn -> sugas.site -> s.sugas.site（加 s 子域），s.aisusu.cn 弃用（DNS 未撤仍可达）；关于页 about.html 定位展示（策略实验核心+其他佐证+非咨询+数据来源+免责）

### limitation（重要）
s.sugas.site/s.aisusu.cn/maozi.io 同走 MaoziYun/3.17.0（非 Cloudflare），`_headers` 不生效（CSP/HSTS preload/nosniff/X-Frame/Permissions-Policy 无法落地），MaoziYun 自带 HSTS max-age=63072000 + meta referrer 兜底；wrangler.jsonc 已存在，未来迁移 CF Workers Static Assets 即生效；用户 2026-07-18 决策接受现状

### commits
9ea8532（footer ICP+隐私）/1006b15（弱化12项）/310c587（信号实验室）/1d0fa8e（sugas.site）/2768678（P2/P3 8项）/02e702c（meta referrer兜底）/2017906（s.sugas.site+策略实验+关于页）

- 本节 NOTES §37

## §38 策略实验室 91候选融合弹窗补双策略指标图（2026-07-18，commit 4be9c84）

承接 §30 剩余增强。91候选融合配对弹窗 `_labFusionPairModalRender`@4167 此前缺"指标图表 echarts"块（单一信号基标 5 块之④），§31 只做了 6 硬编码去代理真实回测（不同的事）。

**改动**（static-site/lab.js，web/ 已删不双写）：
- 91候选分支加双图：上下排列 `lab-fusion-chart-ph-a`（策略A）+ `lab-fusion-chart-ph-b`（策略B），各自独立 echarts 实例 `renderLabChartEx`
- 双 key 取法：`_buyKey`（策略A）+ `_sellKey`（策略B），三类 _pairType 通用（buy_sell=买+卖 / buy_buy=买1+买2 / sell_sell=卖1+卖2）
- 配色：买红 #c92a2a 卖绿 #2e7d32，对齐融合合并图 BUY_C/SELL_C（A股习惯）；signalColor 按 side 覆盖
- rerender：指数/窗口/模式切换调 `_labFusionPairModalRender(overlay)` 整函数重跑（generation counter 防 stale），echarts 实例 push 全局 charts 数组，re-render 时自动释放（双图实例自动含在内，无需额外 dispose）
- 6硬编码分支保持单图（`_labFusionHardcodedHTML`@4147 未碰）

**上线**：build_min.py（lab.js 297KB->lab.min.js 179KB）+ bump_asset_version.py（index.html 版本号）+ commit 4be9c84 push main。

**验收**（主控逐字）：
- `_labFusionPairModalRender` 内 12 处图表调用（renderLabChartEx 双图各调 + 占位 ph-a/ph-b + 6硬编码单图分支）
- 6硬编码 `_labFusionHardcodedHTML`@4147 完整（注释确认走真实 F_pair 融合回测非 _coreKey 代理）
- node --check PASS
- 线上 lab.min.js?v=6d41583b 含双图代码（lab-fusion-chart-ph-a + renderLabChartEx + 成分策略分图）

策略实验室待办全闭环（4分区22策略+5窗口回测+9指数+128组配对+推荐榜+L1-L4 polish+§30信息对齐+§31去代理+§38双图）。

- 本节 NOTES §38

## §39 首页汪汪队卡片 + lab 3级tab + KPI 排序 UI 优化 7 项（2026-07-19）

7 项 UI 需求链全闭环上线 s.sugas.site。逐条记录改动点/关键文件函数/commit。

### 7 项改动

1. **汪汪队 7 天总况**（commit 5540625）：首页汪汪队卡片加近 7 天汇总（汇总数字 + 堆叠迷你柱 + 明细折叠）。后端 `recent_signals_overview(days: int = 7)`@`app/collector/etf_national_team.py:1263`（默认 7 天，返回 `{summary, daily:[{date, signals[], ...}]}`）。

2. **首页 tab 更名**（commit 38a4c4e）：`_H5_TAB_NAMES`@`static-site/app.js:6199`，大盘信号 -> `📈 指数表现`、板块轮动 -> `🏭 板块分化`（弱化"信号"推荐语义，对齐 §37 P0-2 合规定位）。

3. **lab 3 级 tab 重构**（commit 98779a9）：单一/融合信号实验降级为 3 级 tab，打包进「信号实验」父 tab。复用 scan 已有 3 级机制：`_SCAN_CHILDREN`@`static-site/lab.js:3481` = `["ablation","symmetry","paramscan"]` + `isScanActive`@`lab.js:3485`；hash 向后兼容（旧 hash 仍可直达）。

4. **汪汪队明细默认展开**（commit 74efdd1）：卡片汇总明细 `<details open>`，进站即见不折叠。

5. **KPI 卡片排序**（commit 283bc6b）：A+B 组合默认 + 用户拖拽自定义，存 `localStorage.kpiCustomOrder`@`app.js:3007/3133`；加重置按钮（`removeItem`@3087 清回默认）。

6. **汪汪队卡片重构**（commit fb02246）：重构为「近期信号列表」（按日分组 + 今日高亮）+ hover pop 细节 + 点击 chip 弹当日 per-ETF 明细 modal（`openNtDayModal`@`app.js:2794`，`_ntRecentDaily`@`app.js:2698` 缓存 daily 供取当日 `signals[]`）；去整卡跳转、去右下角入口、汇总小标题保留。后端 `recent_signals_overview` 的 daily 项加 `signals[]` per-ETF 明细（~5KB，字段 code/name/type/share_change_yi/amount_ratio/intensity/note）。

7. **chip 详情汇总**（commit 01a3630）：每日 chip 从「进4 量4」升级为「进4 净流入X亿 / 量4 放量X倍 / 出X 净流出X亿」——内联聚合从 `signals[]` 算 `sum(share_change_yi)`@`etf_national_team.py:1239` + `mean(amount_ratio)`@1240；CSS `.nt-home-card .sig-items`@`static-site/style.css` 改 flex-wrap 防窄屏截断。

### commits
5540625（7天总况）/ 38a4c4e（tab更名）/ 98779a9（lab 3级tab）/ 74efdd1（明细展开）/ 283bc6b（KPI排序）/ fb02246（卡片重构）/ 01a3630（chip汇总）；data update 1921dac / 3877c83 / 8bfedf7

### 验收（主控逐字）
- 7 个 feat commit 均 push 上线 s.sugas.site
- 关键符号核对在位：`_H5_TAB_NAMES`@app.js:6199、`_SCAN_CHILDREN`@lab.js:3481、`openNtDayModal`@app.js:2794、`kpiCustomOrder`@app.js:3007、`recent_signals_overview(days=7)`@etf_national_team.py:1263、`share_change_yi`@1239、`.nt-home-card .sig-items`@style.css

- 本节 NOTES §39

## §40 产品评估 2026-07-19（资深 PM 视角 8 维度 + P0/P1/P2 清单）

### 评估背景
2026-07-19 以资深 PM 视角评估线上站点 https://s.sugas.site/，覆盖 8 维度：①定位 ②信息架构 ③核心功能 ④内容可信度 ⑤UX ⑥获客留存 ⑦商业化 ⑧技术性能。用户定先做 P0，6 条 P0 已派 agent 实施（p0-main 做 P0-1/2/3/4/5，p0-about 做 P0-6），P1/P2 待办。本节落档评估结论 + 待办清单（§7：重要决策写项目文件，不只存 memory）。

### 总体判断
工程完成度高 + 合规意识强，差异化成立：
- **情绪看板数据深度**：9 个情绪分 + 透明公式（每分有可追溯的计算口径），同类免费工具罕见。
- **策略实验室回测深度**：10 方向二次测试（单策略矩阵 / 融合配对 / 模拟回测 / 维度切片等），把"单边统计达标 ≠ 配对实战赚钱"这类反直觉结论可视化。
- 三大短板（按风险排序）：
  1. **数据残缺诚信披露（最大风险）**：静默隐藏 disabled 指标。8 项指标采集异常 `collect_health=error`（主力净流入 / 换手率分布 5 项 / 炸板数 / 封板率），但 `app.js:1674` 把异常指标直接隐藏，用户看到的是"没有"而非"采不到"，存在误导（看起来数据全而非残缺）。
  2. **高价值信号未首屏放大**：多指数共振冰点是稀缺高价值信号（7-17 全 6 宽基 11-18 分），但 summary-banner 只显示单标签，未做"N/6 宽基进入冰点区"聚合突出。
  3. **合规去荐股化不彻底**：buy/sell/止盈/买点失败 等标签仍有指令语义（"买/卖/止盈"是动作指令），与 §37 合规定位（情绪复盘工具，非荐股）冲突，应改中性标注。

### P0/P1/P2 清单

**P0（6，进行中）**：
1. 数据残缺静默隐藏（8 项指标采集异常 `collect_health=error`：主力净流入 / 换手率分布 5 项 / 炸板数 / 封板率，`app.js:1674` 隐藏）→ KPI 灰态显示「采集异常（数据源中断）」，诚信披露残缺。
2. 6 宽基共振冰点未首屏突出（7-17 全 11-18 分）→ summary-banner 加聚合（≥3 宽基冰点转红 +「N/6 宽基进入冰点区，近 X 月首次」）。
3. 信号 reason 过长 markPoint 显示不全 → 主标签（如「拐点·盈亏+2.3%」）+ 完整 reason 收 hover/弹窗。
4. buy/sell/止盈/买点失败 标签指令语义 → 中性「超卖拐点标注 / 趋势转弱标注 / 相对前拐点+2.3%」。
5. 期货持仓无主导航入口（`renderFuturesSection` 存在 `app.js:5112` 但无独立 tab）→ 指数表现加期货二级 subtab。
6. about.html「策略回测为核心」与首屏矛盾 → 改「情绪复盘为核心 / 策略实验为进阶」。

**P1（7，待办）**：
1. 北向资金 2024-08 停更图加水印（标注数据停更，避免误读为实时）。
2. industry-5y.json 14.8MB 按行业拆分（对齐 industry-all 29MB 拆 31 行业的既有方案，§性能）。
3. 缓存分层（历史长 1-6h · overview 短 60s · JS immutable 1 年）—— 随部署层 gzip/缓存头一起，依赖服务器可改性（见 §21）。
4. 邮件 RSS 每日收盘情绪速递（复用 `config/email.json` 通知通道，每日收盘发情绪速递）。
5. 汪汪队 termTip 首次解释（国家队 ETF 术语首次出现时弹解释卡，降理解门槛）。
6. 凯利 f 值 C 端隐藏改「历史回测正期望强度」（凯利公式 f 值对散户过专业，改中性描述）。
7. 指数表现 vs 情绪温度 tab 边界厘清（两 tab 内容重叠易混，厘清边界）。

**P2（5，待办）**：
1. 首次 onboarding 3 步（新用户引导：看情绪分 → 看冰点共振 → 看策略实验室）。
2. SEO 关键词清理（删 tdsignal-ujpzw01zm 等无搜索量词，§37 网安审计遗留）。
3. 策略实验室新手引导卡 + 91 融合候选 n<30 标灰（样本不足标灰提示，避免误读小样本结论）。
4. purpose-note 改散户语言（去专业术语，对齐 §39 散户白话注释方向）。
5. app.js · lab.js 按模块拆 chunk（按 tab 懒加载，降首屏 JS 体积，远期配合 gzip）。

### 当前 P0 进度
6 条 P0 正在实施（p0-main agent 做 P0-1/2/3/4/5，p0-about agent 做 P0-6）。本节为评估落档，P0 实施细节（改动点 / 关键符号 / commit）待 agent 完成后回填对应章节。

- 本节 NOTES §40

## §41 2026-07-20 8指标首页KPI平铺上线

### 背景
首页 KPI 从 13 个扩到 21 个，新增 8 个宽度/换手指标平铺展示。

### commit 链（已上线 origin/main）
- 9abb062（feat:8指标 5 文件改动）
- e3d9766（merge origin/main，干净无冲突）
- 03b48e5（data update [all] 09:47，deploy.sh 重生成 243 个 JSON）
- 8指标上线时 origin/main HEAD = 03b48e5

### 8 个新 KPI id 及含义
1. `a_width_zb_count` - 炸板数
2. `a_width_seal_rate` - 封板率
3. `a_fund_main` - 主力净流入
4. `a_turnover_mean` - 换手率均值
5. `a_turnover_median` - 换手率中位数
6. `a_turnover_p90` - 换手率 90 分位
7. `a_turnover_p10` - 换手率 10 分位
8. `a_turnover_gt5_pct` - 换手>5% 占比

### 前端改动（static-site/app.js）
- `fmtMetric` 新增 8 个 case 格式化：zb_count 整数；seal_rate/gt5_pct 转%；fund_main 带正负号；turnover 4 分位 2 位%
- `_KPI_BASE_ORDER` 权重 13-20
- `KPI_HISTORY_SOURCE` 8 个 id 映射 astock 源
- `_kpiTips` 8 条文案
- app.min.js 经 build_min.py 压缩
- index.html `?v=5f44dc7c` 破缓存

### 后端改动
- `app/export.py` `KPI_METRIC_IDS` +8 id
- `app/main.py` `KPI_METRIC_IDS` +8 id（两处同步）

### 验收结论
- overview KPI 13->21
- 21 个 KPI + 8 新 id 全在
- `?v=md5` 与 index.html 一致
- a-stock-all.json 含 8 字段（点击历史有数据）

### 关联
- 8 项指标此前为 `collect_health=error` 灰态（见 §40 P0-1），本次扩 KPI 后平铺上线；§42 记 MaoziYun 构建超 300MB 限制致上线一度卡住。

- 本节 NOTES §41

## §42 2026-07-20 MaoziYun构建超300MB限制故障 + 瘦身方案

### 症状
- origin/main 已更新至 5c4312a（含灰卡修复 8ce7385），但 MaoziYun 平台 1hr20min+ 不上线新版本
- 8指标 03b48e5 同样卡在 MaoziYun 未生效
- 线上 curl 验证异常：
  - `?v=d22c6e3b`（旧版，非当时的 df22776d/5f44dc7c）
  - collect_health level=error items=8（8 灰卡仍在）
  - industry-5y-indices 404

### 真因（构建超限，非 webhook 故障）
- **构建报错原文**：`ERROR: directory size exceeds 300MB: 301MB`（static-site/ 实际 312MB 超 MaoziYun 构建 300MB 上限）
- 初判 ee93306 落档时误以为是 git 拉取/webhook 故障，实际是构建阶段因目录超限直接失败，git 已 push 成功（origin 有新 commit）
- 超限根因文件：
  - `industry-5y.json` 14M 历史遗留——前端 `_loadIndustryData`（app.js:6246）已让 5y 走拆分目录 `industry-5y-indices/`，全量 industry-5y.json **0 引用**
  - `__pycache__/` 84K 被打包入构建上下文（原无 `.dockerignore`）

### 瘦身方案（commit 613b769）
1. `git rm static-site/data/industry-5y.json`（-14M）
2. 新建 `static-site/.dockerignore` 排除 `__pycache__/`、`*.pyc`、`*.pyo`、`.DS_Store`（减 build context）
3. `export.py:1270-1271` 已跳过 all/5y 全量 `industry-{rng}.json` 生成（只生成拆分目录），无需再改
4. `lab/` 102M 选择跳过：数据无冗余、已懒加载（lab.js:1746/1637 按选 index 按需 fetch）；降采样会破回测精度风险高，不动

### 结果与线上复验
- 最终体积 static-site/ 297M（< 300M 过限制，但 > 280M 目标未达，余量仅 2M 偏小）
- 后续 commit dfbe978（data update 10:00）+ push HEAD->main ff 成功
- 线上复验 4 项全通过：
  - `?v=5f44dc7c`（8指标 JS 生效）
  - collect_health ok items=0（灰卡消除）
  - industry-5y-indices 200（5y 拆分目录正常）
  - industry-5y.json 404（删除上线 = 构建成功）
- 积压的 8ce7385（灰卡角标变红）+ 03b48e5（8指标首页 KPI 21个）全部线上生效

### 余量 2M 隐患与未来超限解法候选
- industry 数据仍在增长（如 3y 9.1M），若继续增长可能再超 300MB
- 未来超限解法候选（按优先级）：
  1. **industry-3y/1y 等也拆分**：生成 `industry-3y-indices/` 等拆分目录，改 `_loadIndustryData` 让 3y 走拆分——省 9M+，最稳
  2. **lab equity_curve 降采样**：破精度，慎用
  3. **启用 gzip 传输**（fetch + DecompressionStream）：减传输不减构建体积，治标
- 短期监控点：再遇 MaoziYun 长时不更新，先查构建日志是否又报 `directory size exceeds 300MB`，而非怀疑 webhook

### 教训
- MaoziYun 构建有 300MB 目录大小硬限制，超限直接构建失败（非静默跳过），git push 成功 ≠ 上线成功
- 上线后 curl 验证以线上实际 ?v/数据为准，不能只信 git push 成功
- 多部署渠道冗余（§8：MaoziYun/GitHub Pages）的价值再次印证（GitHub Pages 不受 MaoziYun 构建限制影响）
- 历史遗留大文件（如 industry-5y.json）即便 0 引用也占构建体积，需定期清理

- 本节 NOTES §42

## §43 综合AI风险预警算法设计

> 2026-07-15 完成 9 章+附录调研设计,落档 `docs/alert-design.md`(490 行)。只设计不写代码,待回测验证后分期实施。主控派子 agent 调研全站指标体系+表结构+历史范围,产出预警算法草案;后追加第八章原因生成+第九章交互式自定义分析+合规风控。

### 设计文档位置
- `docs/alert-design.md`(全文 490 行,9 章+附录,保留调研路径与关键约束发现)

### 9 章核心摘要
1. **全站信号清单**:按回测可用历史长度分级(★全历史/⚠短历史仅近端)。score_daily(a_sentiment/cross_market/fear_greed/6宽基情绪分)+daily_metric(宽度/量能/位置感/均线/新高新低/资金面/全球/轮动)+signal_daily(买卖点)+etf_signal(汪汪队)+futures_position(机构持仓)全覆盖。⚠近端类(主力净流入130天/qvix_1000停/涨停板池25天)仅实时辅助不参与回测。
2. **高位预警 8 维度**(权重和=1.0):H1 情绪过热0.20 / H2 量价背离0.18(领先) / H3 卖点密集0.15(领先) / H4 位置偏高0.15 / H5 动量衰退0.10 / H6 均线转弱0.10 / H7 汪汪队离场0.07 / H8 全球走弱0.05。公式 `HIGH_ALERT = Σ(w_i × H_i)`,各维度 0-100 强度用 120 日滚动百分位归一化,缺项重归一化。
3. **低位预警 8 维度**:L1 情绪冰点0.20 / L2 买点密集0.18(领先) / L3 位置偏低0.15 / L4 汪汪队入场0.15(强信号,底部有国家队给更高权重) / L5 量能异动0.10 / L6 新低极端0.08 / L7 波指飙升0.07 / L8 价值显现0.07。公式同 HIGH_ALERT。
4. **等级触发**:高位 60-75 关注(黄)/75-88 警示(橙)/>88 高危(红);低位 60-75 关注(浅蓝)/75-88 机会(蓝)/>88 机遇(深蓝)。硬触发:6 宽基≥3 个 is_overheat/is_freeze 直接升级一档(对称现有 freeze-resonance 逻辑)。
5. **与现有情绪分关系**:a_sentiment/cross_market/fear_greed 是"情绪温度"(What is 冷热),作为预警算法的 1 个输入维度(H1/L1);预警算法是"风险信号组合"(What to do),加入量价背离/买卖点密集/位置感/汪汪队/动量等领先维度。互补不替代,复用 `normalize.rolling_percentile` 归一化框架不另起炉灶。存储新增 2 个 score_id(`high_alert`/`low_alert`)写 score_daily 表复用 is_freeze/is_overheat 字段。
6. **历史回测思路**:统一窗口 2016-01 至今(2559 天,保证核心维度同期)。对每个历史触发日算后 5/10/20 日上证/沪深300 收益率(复用 signal_stats forward 收益)。目标胜率:高位>55%(跌占比)/低位>60%(涨占比,底比顶更好抓);盈亏比>1.2。触发频率:高位 3-8 次/年,低位 2-5 次/年。防过拟合:维度精不堆砌/阈值用百分位不硬编码/权重整数化/不逐品种调参/2016-2022 训练定参 2023-2026 样本外验证/维度间低相关。
7. **前端展示**:首页顶部预警条(最高优先级,采集时间横幅下方全宽,无预警不显示/高位黄橙红/低位浅蓝蓝深蓝/双预警分两行);弹窗详情(预警分大数字+等级+8维度雷达图/条形图+每维度当前值/百分位/触发状态/一句话解读+历史回测胜率/盈亏比+近 X 月首次标注);overview 历史预警日卡片+sentiment tab 加 HIGH_ALERT/LOW_ALERT 两走势线;现有 freeze-resonance 横幅降级为 LOW_ALERT 硬触发子条件不再单独展示。
8. **原因生成(第八章)**:每次预警输出 4 部分结构化原因:①命中维度清单(强度≥60 命中/≥75 强命中,降序排列加强命中加粗)②具体数据+阈值对比(当前值/历史百分位/触发阈值/是否超阈值,复用 alert_score 中间值)③历史类比(核心可解释性,特征向量=8 维度强度,双轨相似度:主轨命中维度集合 Jaccard≥0.6 筛同类组合,辅轨强度向量余弦相似度排序取 top-5;类比窗口默认近 3 年可扩 5 年,top-3 相似日+聚合统计"近3年类似 N 次 M 次后10日跌/涨平均 X%")④一句话人话解读(模板化,槽位=情绪分值+前2命中维度+历史类比方向+风险提示词)。
9. **交互式自定义分析(第九章)**:用户输入标的(行业名/宽基名/指数代码/ETF),系统算预警分+原因+合规提示。模糊匹配(多候选按成交额降序自选,匹配不到留空不硬编造)。**单标的降维适配表**:H1/L1 宽基有 sentiment/行业概念现算 RSI 百分位;H7/L4 汪汪队仅宽基 ETF 适用行业概念缺省;H8 全球走弱不适用单标的缺省;缺项重归一化至少 4 维度出分。新增 `/api/alert/analyze` 端点现算(需读 DB 历史类比,不适合纯前端),9 宽基+31 行业可预生成每日快照 JSON 走静态化备选。

### 关键设计:零新增数据采集 + 短历史维度替代
- **复用 alert_score + signal_stats**:全部 8+8 维度数据均已存在(daily_metric/score_daily/signal_daily/etf_signal),仅新增 2 个 score_id,零新增采集源。原因生成复用 alert_score 维度强度+signal_stats forward 收益,仅新增历史类比检索。自定义分析复用 alert_score 算法+单标的适配。两块零新增数据采集。
- **短历史维度替代**(不可回测的维度换长历史同语义):
  - 主力净流入(a_fund_main 仅 130 天)-> 改用两融(a_fund_margin 2021 起 1334 天)+ 南向(hk_south 2014 起 2672 天)
  - a_qvix_1000 已停(2022-2024)-> 波指维度仅用 a_qvix_300(2019 起)
  - position 仅 8 天近端 -> 回测现算(index_daily 全历史 close),上线后 compute_position 每日跑
  - 涨停板池近端类(连板/炸板率/封板率/打板溢价仅 25 天)-> 宽度维度用 zb_count+seal_rate(2016 起 mootdx 回填)替代

### 实现复杂度
- 数据层:零新增采集,仅 2 个 score_id
- 计算层:`app/compute/alert_score.py`(~150 行,复用 normalize 框架)+ `alert_reason.py`(原因生成,复用 alert_score+signal_stats,新增历史类比检索)
- 前端:预警条+弹窗+历史卡片(~300 行 JS+CSS)+ 自定义分析 tab(~250 行 JS+CSS)
- 回测:`scripts/backtest_alert.py`(复用 signal_stats forward 收益逻辑)
- **总量**:原 7 章 2-3 天(计算+前端+回测);追加第八章原因生成+第九章自定义分析后**额外 1-1.5 天**(历史类比检索+单标的适配+API 端点+前端输入框候选列表+合规底栏),合计 3-4.5 天

### 下一步(分期)
- **P1 回测验证**(当前优先):实现 `alert_score.py`+`backtest_alert.py`,跑 2016+ 历史 8 维度预警,验证高位预警后 N 日跌/低位后涨胜率达标(>55%/>60%)。不达标调权重/维度。防过拟合(样本外验证 2023-2026)。
- **P2 预警条+原因上线**:回测有效后,前端加首页预警条+弹窗(含原因生成 4 部分),替换现有 freeze-resonance 横幅(降级为 LOW_ALERT 硬触发子条件)。
- **P4 交互式自定义分析**:上线 `/api/alert/analyze`+前端输入框(模糊匹配联想)+候选列表(按成交额排序)+结果卡片(4 部分原因)+合规底栏(固定风险提示+用词中性白名单+无数据诚信提示)。

### 合规风控(第九章 9.5)
- 固定底栏:`⚠️ 本分析基于历史数据统计,仅供学习参考,不构成投资建议或交易指令,市场有风险,决策需谨慎`
- 用词中性白名单:分析/参考/风险提示/关注/留意/谨慎/防范
- 禁用词:买入/卖出/加仓/减仓/清仓/满仓/抄底/逃顶(用"关注低位机会""留意高位风险"替代)
- 无数据诚信提示:数据不足显示"该标的暂无足够数据进行有效分析"不硬编造
- 历史类比免责:标注"历史统计参考,不代表未来必然走势"

## §44 2026-07-20 本轮成果落档（信号检查+废弃扫描+配色去重+首页虚线+分享图重设计+调度异常根因+预警tab）

> 2026-07-20 落档 7 项成果:信号脚本排查(0715-0717 无买卖点为行情使然非 bug)、static-site/ 废弃文件扫描与瘦身方向、跨市场图冰点去重上线(commit 3a43fd0)、首页 3 图过热/冰点虚线上线(commit bbfae59)、分享图重设计方案(待实施)、0717 调度异常根因(mootdx 数据源故障非漏跑)、预警 tab 设计预占位。

### 1. 信号脚本检查:0715-0717 无买卖点是行情使然(非 bug 非采集断)
- **结论**:signals.py 逻辑正常,0715-0717 无买卖点由行情决定,非脚本 bug 亦非采集中断。
- **sell 被 MA60 多头过滤砍掉**:`signals.py:14/35` 规定"仅 close>MA60 多头才放卖",上证 0710-0717 全程 close<MA60(空头),故无卖点输出。
- **buy 等 RSI 上穿 30**:0717 RSI=29.9 跌破 30 未反弹,需等反弹上穿才触发买点。
- **buy_aux(BB 下轨回归)**:0714 触发 19 个。
- **DB signal_daily 实测**:0714=32(buy12/buy_aux19/sell1)/0715=3/0716=1/0717=0,与行情逐日转冷一致。

### 2. 废弃扫描:static-site/ 294M,99% 有效引用数据
- **总量**:static-site/ 294M,99% 是有效引用数据。
- **可删 5 个废弃 JSON**(共~188K,零风险,前端无 fetch 引用):buy_aux_backtest 101K / lab_montecarlo 54K / lab_fusion_p2 21K / lab_generalize 10K / metrics 2.6K。
- **大头需开发优化**:
  - `lab_sim_*_full.json` 93M(按窗口拆分/字段精简可省 30-50M)
  - `trade_sim_*.html` 51M(94 个,冷门指数可评估下线)

### 3. 配色去重上线(commit 3a43fd0)
- **跨市场图 2 冰点去重**:markLine label 由文字"冰点/过热"改为数值"20/80"标阈值,title 保留"🔵冰点"标状态,避免与 label 重复。
- **删 freeze 死代码**:signalColor/signalLabel 的 freeze 分支删除(signals.py 从不生成 freeze 信号)。

### 4. 首页虚线上线(commit bbfae59)
- **3 张 lineChart 加 markLine 过热+冰点虚线**:首页恐贪指数图(25/75)+A 股情绪分图(20/80)+跨市场图(20/80)。
- **实现模式**:`setOption({series:[{markLine}]})`,对齐情绪温度 tab 样式。

### 5. 分享图重设计方案(待实施)
- **适配 4 套皮肤**:cssVar 读 `--bg-card`/`--text-1`/`--primary` 注入 canvas,保留涨跌色硬编码。
- **4 新区块**:一句话结论 / 8 指数轮动 / 期货机构持仓 / 行业轮动 Top5。
- **画布高度**:H 1350 -> 1500。
- **实施位置**:`drawShareCard`(app.js:6848),5 步实施。

### 6. 调度异常根因:0717 非 漏跑,launchd 正常触发
- **非漏跑**:launchd 17:50 正常触发,Mac 全程未睡。
- **根因 = mootdx 数据源故障**:ok=0 / 5203 全 empty,每只 5s 拖 7h16m(对比 0716 是 0.16s/只 ok=5200);东财同步封 IP,双源全挂。
- **告警已发**:邮件 + `data/alerts/latest.md`。
- **0720 02:00 backfill 兜底重算信号没漏**:schedule_stats 因 update_all 失败未刷新致误判漏跑。
- **修复方向**:mootdx fail>阈值快速跳出 + fallback baostock。

### 7. 预警 tab 设计(预占位,待 a06e6f519a6802e8a agent 完成后补)
- **综合 AI 预警 alert-design.md**(490 行 9 章)已覆盖:高位 8 维+低位 8 维+原因生成+自定义分析+合规。
- **补"策略实验室->预发布二级 tab->自定义分析三级 tab"完整交互**:历史查看+自定义询问+自定义预警逻辑。
- **首页预警条保留作展示层**。

## §45 2026-07-20 ss.fx8.store 主站上线（CF Workers 方案4）+ data 缓存缩短保时效

> 域名策略最终落定:ss.fx8.store 主站(Cloudflare Workers,方案4)/ s.sugas.site 备用1(MaoziYun+GitHub)/ sss.sugas.site 备用2(GitHub Pages)。P0-1 压缩 + P0-2 缓存分层两项长期搁置的性能优化通过主站切 CF Workers 一并解决。

### 1. 域名策略
- **ss.fx8.store = 主站**(CF Workers 方案4):br 压缩 + 缓存分层(worker/headers.js 接管 response headers)+ GitHub push 自动部署(Cloudflare Builds 跑 wrangler deploy)+ lab 读 R2(ssd.fx8.store)。`run_worker_first=true` 时 `_headers` 不生效,所有 headers 在 `worker/headers.js` 统一设置
- **s.sugas.site = 备用1**(MaoziYun + GitHub,max-age=1200):用户个人域名,MaoziYun/3.17.0 托管自动拉 git main 部署,有拉取延迟+max-age=1200 缓存
- **sss.sugas.site = 备用2**(GitHub Pages):兜底
- 切主站动机:MaoziYun 构建超 300MB 限制(§42)+ 零压缩(_headers 不解析,§21),CF Workers 无 300MB 限制且自带 br/gzip 压缩

### 2. P0-1 压缩 ✅ 解决
- CF Workers 自带 Brotli + gzip,echarts 1MB / app.js / 行业全部 24MB 全压缩传输,弱网提速 3-5 倍(单项最高收益)
- 不再依赖 MaoziYun 改 nginx(§21 实测帽子云不可改,非用户 CF 账号)

### 3. P0-2 缓存分层 ✅ 解决（worker/headers.js）
- 有序规则(first-match-wins)5 档:
  1. 版本化 JS/CSS(style.css/app.min.js/lab.min.js/lab.css/qr.js + /vendor/):1 年 immutable(改动靠 ?v= 换 URL 破缓存)
  2. HTML 入口(/ + index.html + trade_sim_* + feed.xml):no-cache, must-revalidate
  3. **实时数据 JSON:60 秒**(global-extras-all/summary/overview/intraday_snapshot/new_high_low/position/rotation/volume_ratio/ma_alignment/signal_freq/schedule_stats/summary_history/etf_national_team_holders/etf_national_team_quarterly/futures/ad_line/*-1m.json)
  4. **纯历史 JSON:1 小时**(lab/ + index/ + industry-*-indices/ 拆分目录 + -3m/6m/1y/3y/5y/all.json)
  5. 兜底:no-cache, must-revalidate
- 关键修复:**global-extras-all.json 原被规则4 的 `-all` 正则匹配走 6h(21600)缓存,致 usdcnh 滞后(停在 7-17 无 7-20,而 s.sugas.site MaoziYun max-age=1200 已刷 7-20)**。现放规则3(60s)在规则4 之前,first-match-wins 保证分钟级刷新
- 历史长周期(5y/all)从 6h 缩短到 1h,统一历史档,保证当日数据最迟 1h 内刷到 CDN

### 4. 验证
- `node --check` 通过;match 逻辑模拟:global-extras-all/summary/overview->60s,a-stock-all/global-3y/industry-all-indices/index-all/lab->3600,index/sh-1m->60s,app.min.js->immutable,/ + index.html + feed.xml + trade_sim->no-cache ✅
- 部署后 curl `https://ss.fx8.store/data/global-extras-all.json` 确认 usdcnh 刷到 7-20(=679.48);CDN 若仍旧缓存等 60s 过期再 curl

## §46 2026-07-20 晚：缓存调优收口 + 分享图三修 + 全站域名同步 P0/P1

> §45 主站切 CF Workers 后，本轮收口三块：worker/headers.js 缓存分层调优（global-extras-all 提前到 60s 档）、分享图三处修复（域名同步/空行收紧/行距加宽）、全站静态资源域名同步 ss.fx8.store。5 个 commit：adf8133 / a752c29 / d733267 / d595500 / 2445197，已 push feat->main，CF 部署延迟 ~155s 后线上生效。

### 1. 缓存调优（commit adf8133）
- worker/headers.js 重构为 5 档 first-match-wins：
  1. 版本化 JS/CSS（style.css/app.min.js/lab.min.js/lab.css/qr.js + /vendor/）：1 年 immutable
  2. HTML 入口（/ + index.html + trade_sim_* + feed.xml）：no-cache, must-revalidate
  3. 实时数据 JSON 60s：global-extras-all/summary/overview/intraday_snapshot/new_high_low/position/rotation/volume_ratio/ma_alignment/signal_freq/schedule_stats/summary_history/etf_national_team_*/futures/ad_line/*-1m.json
  4. 纯历史 JSON 1h：lab/ + index/ + industry-*-indices/ 拆分目录 + -3m/6m/1y/3y/5y/all.json
  5. 兜底：no-cache, must-revalidate
- 关键修复：global-extras-all.json 原被规则4 的 `-all` 正则匹配走 6h（21600）缓存，致 usdcnh 滞后；现放规则3（60s）在规则4 之前，first-match-wins 保证分钟级刷新。
- usdcnh 7-20 排查结论：非缓存问题。源数据 extras.usdcnh 当时只到 7-17=679.34（7-18/19 周末，7-20 周一未采集/未导出），三处（ss.fx8 / s.sugas / 本地 git）一致；后由 20:09 backfill（commit b25fcdb）刷新补入 7-20=679.48。根因待跟（见 TASKS P1）。
- CF CDN：免费全开，cf-cache-status HIT + cf-ray 全球边缘节点，worker/headers.js 设 cache-control 即自动边缘缓存。

### 2. 分享图三处修复（commit a752c29 / d733267 / d595500）
- C1 a752c29 域名同步：app.js L7109 文字 URL s.sugas.site->ss.fx8.store + gen_qr_js.py URL + qr.js 重生成（25x25）+ build_min + bump_asset_version
- C2 d733267 收盘复盘空行收紧：分隔线 320->296、drawConclusion 345->321，整链上移 24px
- C3 d595500 行业领涨行距：考证 31 行业名均 ≤4 字（~84px）横向加宽无效，真正太挤是纵向 itemH=26 < 28px 舒适行高 -> itemH 26->30（L7064）

### 3. 全站 CF 迁移 P0+P1 域名同步（commit 2445197）
- index.html 6 处（canonical / og:url / og:image / twitter:image / JSON-LD url / noscript）+ ICP 注释 -> ss.fx8.store
- about.html 3 处 + ICP 注释；privacy.html 站点声明（去 maozi.io）+ ICP 注释
- gen_rss.py L18 SITE -> ss.fx8.store，重跑生成 feed.xml（30 items，61 处 ss.fx8.store）
- uptime_check.sh L9/L19/L26 探活默认 URL + 注释 -> ss.fx8.store；_headers L5 typo ss.sugas.site->sss.sugas.site
- 约束：未跑 build_min/deploy（JS 没变，避免和分享图 ?v= 撞）

### 4. 上线验证（push feat->main adf8133..2445197，CF 部署延迟 ~155s）
- 线上 ss.fx8.store：canonical/og:url=ss.fx8.store ✓ / feed.xml 61 处 ✓ / app.min.js?v=2c4e779e 分享图域名 ✓ / qr.js?v=1b721750 二维码 ✓ / og.png 200 ✓

> 域名策略见 §45：ss.fx8.store 主站（CF Workers，br+CDN+GitHub push 自动部署）/ s.sugas.site 备用（MaoziYun+GitHub）/ sss.sugas.site 备用（GitHub Pages gzip）/ maozi.io 旧兜底弃用 / s.aisusu.cn 已撤 DNS。
