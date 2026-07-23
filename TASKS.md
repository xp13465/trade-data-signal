# TASKS.md - 情绪看板迭代任务清单（监管 + loop 工作模式）

> 这是「监管 + loop」工作模式的唯一共享任务文件。子进程开工前**必读本文件** + `REQUIREMENTS.md`（需求真实来源）+ `NOTES.md`（调研笔记）。监管（主进程）不直接干活，派子进程领任务循环。

> **历史已完成项（2026-07-06 ~ 2026-07-20 晚续3 的交接状态、22 任务全 done 的任务清单/进度看板、综合AI风险预警 P1/P2/P4 全闭环）已归档到 [docs/archive/TASKS-done.md](docs/archive/TASKS-done.md)。本文件只保留头部 + 晚续4 + 工作约定 + R2待办 + 全站性能待办。**

## 总体大纲

A 股 / 港股 / 全球盘后复盘看板。Python 3.11 + FastAPI + SQLite + ECharts，Mac 本地。当前 27 个指标、13 指数、运行在 http://localhost:8000（`--reload`，改文件自动生效，**不要杀进程**）。本轮迭代目标：修回归问题 + 补国债 / 原油白银 / 红利 / A 股十年回溯 / 买卖点优化 / 行业看板 / 概览美化。

相关文件：`REQUIREMENTS.md`（需求 + 实现状态 + §9 变更史）、`NOTES.md`（调研 + 修复史）、`05-回归测试报告.md`（本轮回归）、`01-问题清单.md`（上轮 bug）、`config/indicators.yaml`（指标注册表）、`app/`（采集 + 计算 + API）、`web/`（前端）。

> ⚠ 开工先看 `data/alerts/latest.md` 是否有未处理严重告警，有则优先排查。

## 交接状态（2026-07-21 晚续4，deadcode 清理 + 端到端验锁闭环）

> 收口小节H.3 两条遗留：① L3189/L3192 dead code 清理（远期->已完成）；② update_all 进程互斥锁端到端验证（此前只组件级，本次真跑闭环）。详见 `NOTES.md §48 小节I`。

### ✅ 已完成（2 项闭环，commits 11c9e9e1 + 8839300 端到端验证）
1. **#1 deadcode 清理**（commit `11c9e9e1` + deploy `d8c015ce`）：`app.js` `_KPI_BASE_ORDER` 删两条 dead key：
   - L3189 `a_width_zhaban_rate: 5`（被 L3191 的 13 last-wins 覆盖，5cf9316b 占位 5 + 73848eed 切 13 留下的重复键）。
   - L3191 `a_width_seal_rate: 14`（旧字段，卡片已切 `a_width_fengban_rate: 14`）。
   - 保留活键 `a_width_zhaban_rate: 13` + `a_width_fengban_rate: 14`（第 13/14 位卡片正常显示）。
   - build_min + bump 版本号 `be90399c -> b2a277c7`，deploy.sh 推 `static-site/data/` + `app.min.js`，feat+main 双同步到 `11c9e9e1`。
   - 线上验证：`app.min.js?v=b2a277c7` 生效，grep `zhaban_rate:5`=0 / `seal_rate:14`=0 / `zhaban_rate:13`=1 / `fengban_rate:14`=1 ✅。
2. **#2 端到端验锁闭环**（commit `8839300`，2026-07-20 23:54 真跑通过）：`with_lock.py --nb` fcntl 互斥锁此前只组件级验证，本次真跑 4 场景全通过：
   - 第 1 次占锁（sleep 10）✅ / 第 2 次（`--nb`，锁被占）跳过 exit=0 ✅ / 第 2.5 次（`--nb --on-skip`）跳过+触发回调（打印锁路径）exit=0 ✅ / 第 3 次（锁释放后）成功执行 exit=0 ✅。
   - 生产锁路径 `/tmp/trade_update_all.lock`（`update_all.sh` L39），锁路径是位置参数非 `--lockfile` 选项。
   - `on_skip` 回调 `scripts/on_skip_notify.sh`（发 `notify.py` 邮件 + 写 `alerts/latest.md`，重复跑可见）。
   - 结论：重复跑 update_all 会跳过+通知，无需担心并发撞 `progress.json` 或限流空转。

### 🔄 进行中 / 待验证（承接晚续3）
- ~~**ETF 份额方案 A 零改动 6 天回填**~~：✅ **2026-07-21 验收通过**（commit `d37c2c71`，详见 NOTES §48 小节J）。etf_daily MAX=20260720 / 近 5 日 7-15/16/17/20 各 12 行 / 线上 `overview.json` etf_date="20260720" / 根 `data/` 未 add。
- ~~**ETF ohlc 隐患**（待 7-21 20:07 槽补齐后复查）：凌晨触发 pipeline 时 mootdx OHLC 未采到，7-20 close/amount 为 NULL（ohlc=0）。7-17 数据完整证明正常时点能采到。需 20:07 槽（`scripts/etf_national_team_backfill.sh`）或 17:50 `update_all.sh` 补 OHLC。待办：7-21 20:07 槽跑完后复查 7-20 close/amount 是否补齐。~~ ✅ **2026-07-22 验收通过**（commit `65610d6b` 换 akshare sina 主源 + 7-21 20:07 槽 ohlc=60 补齐；DB 7-17/7-20/7-21 各 12 ETF bad_close=0/bad_amount=0；线上 `overview.json` etf_date=20260721，ss.fx8.store + sss.sugas.site 双站确认；详见 NOTES §48 小节AJ）。
- **usdcnh 7-27 周一 curl 验证**（承接 H.3 遗留）：`currency_boc_sina` 主源稳定后，2026-07-27 收盘后 curl `https://ss.fx8.store/data/global-extras-all.json` 确认 `extras.usdcnh` 末值含当日，无需手动 backfill（防复发）。

### 🔴 近期
- ~~**ETF 方案 A 验证**~~：✅ 2026-07-21 验收通过（commit `d37c2c71`，详见 NOTES §48 小节J）。
- ~~**ETF ohlc 隐患复查**：7-21 20:07 槽跑完后复查 7-20 close/amount 是否补齐。~~ ✅ **2026-07-22 验收通过**（DB 7-17/7-20/7-21 bad_close=0/bad_amount=0，7-21 20:07 槽 ohlc=60，详见 NOTES §48 小节AJ）。
- **usdcnh 7-27 周一 curl 验证**：防复发，确认 `currency_boc_sina` 主源稳定。
- ~~**生产买入信号优化（特买+备买新增）**~~：✅ **2026-07-22 全量上线 + Supertrend 回测审查验收通过**。方案 2026-07-21 定，代码 signals.py L648/654/880 + 生产统计 signal_stats.json + 前端 app.js chip/图例/合规名 + 第一个止损卖过滤（commit 4e515ebe）全上线，等于灰度运行。Supertrend 审查（agent a5207bb15eb95a5c6）：Don20 参数稳健性 7/7 全盈利碾压现有信号 / 生产实绩 sh buy_special win=70.2% pl=2.14 n=506 mean=+6.48% / buy_backup win=68.3% pl=2.31 n=41 mean=+7.20%。agent 建议观察 1-2 个月确认稳定性，详见 NOTES 小节AS。
  - **保留**：主买 C1_RSI30（红色，"红色的超卖拐点"，RSI 上穿30）/ 辅买 B1_BB_lower_revert（玫红色，"玫红色的下轨拐点"，BB 下轨回升）/ 卖 D1_high20_drop5（绿色，20日高回落）。多轮验证低回撤，不推翻。
  - **新增**：特买 Donchian20_up（金色 `#ffd700`，"金色的上轨突破"，唐奇安20日上轨突破，激进战法高回撤高收益）/ 备买 Supertrend_buy（紫色 `#9c27b0`，"紫色的趋势转向"，Supertrend ATR 趋势翻转）
  - **合规命名**：回测口径（指数表现页）保留原名"买点/卖点/辅买"；首页+走势图用合规中文名"[颜色]的[4字技术描述]"（不带"买"字）。前两拐点=均值回归类，后两突破/转向=趋势跟踪类，语义对称。
  - **信号冲突展示**：叠加多色标记（不覆盖，类似汪汪队进出量多色 pin），叠加的特殊 pin 更有价值，覆盖无法体现。
  - **依据**：Donchian20_up 实验室 param_scan robust_profitable 验证过；Supertrend_buy grep 确认在 lab_backtest_*.json 跑过（多指数），robust 性/回撤/收益待审查 agent 报告。
  - **chip 位置**：指数走势图标题旁（最醒目）。重点指数金 chip "备买优势区" / 弱提示指数灰 chip "备买弱势区"。
  - **重点/弱提示清单**：全部展示（4 重点 北证50/中证1000/科创50/中证500 + 5 弱 上证50/沪深300/上证综指/深证成指/创业板），合规性提示（透明告知备买在不同指数表现差异，不藏弱只标强）。
  - **模拟回测弹窗组合**（指数表现 #market tab，`simulate_trade.py` L1286 SIG_LABELS/SIG_TYPES）：单买 4（主买+卖/辅买+卖/特买+卖/备买+卖）+ 双买 6（主买+辅买+卖[现有]/主买+特买+卖/主买+备买+卖/辅买+特买+卖/辅买+备买+卖/特买+备买+卖）= 10 信号组合 × 3 策略 = 30 场景。单买为主、双买辅助；三买/四买远期规划不做。
  - **固定1w(10%) 命题改进**（本次做非远期）：`simulate_trade.py` 策略路径名"买固定1万+卖清仓"->"买固定1万(10%)+卖清仓"，"固定1万进出（FIFO）"->"固定1万(10%)进出（FIFO）"，明确 10 万本金 10%（否则固定1w进出和全仓进出在不知本金时易混）；全仓进出不变。
  - **实施待办**（报告通过后）：改 `app/collector/signals.py` 加 Donchian20_up + Supertrend_buy 信号计算 + 前端五色展示 + chip 标注 + legend + 叠加标记逻辑 + `simulate_trade.py` SIG_LABELS/SIG_TYPES 加 6 新组合（特买+卖/备买+卖/主买+特买+卖/主买+备买+卖/辅买+特买+卖/辅买+备买+卖/特买+备买+卖）+ 策略路径名改(10%) + 收盘后跑 simulate_trade.py --all 重生成 94 HTML。
  - **阶段计划**（2026-07-21 定，a7e0b2 报告后补充细化行号）：
    - 阶段1 后端 `signals.py`：加 Donchian20_up（close>max(high[-20:-1])）+ Supertrend_buy（ATR(10)×3 翻多）计算，L279 return 扩展输出 buy_special/buy_backup，落 signal_daily（signal 字段字符串不加字段）
    - 阶段2 `signal_stats.py` + `check_signals.py`：加 buy_special/buy_backup 统计+去重+邮件通知
    - 阶段3 `intraday_snapshot.py` L895：_recompute_signals 调 signals.compute() 自动覆盖，不需改
    - 阶段4 前端 `app.js` L267-292 + `index.html` + `style.css`：signalColor/signalLabel 加 buy_special 金#ffd700"上轨突破"/buy_backup 紫#9c27b0"趋势转向" + 4色买点pin叠加（参照汪汪队进出量）+ 走势图标题旁chip（9指数硬编码，4重点金/5弱灰）+ 图例说明+备买tooltip风险提示
    - 阶段5 `simulate_trade.py` L1286：SIG_LABELS/SIG_TYPES 加6新组合（10组合×3=30场景）+ 策略路径名改(10%) + 收盘后跑--all重生成94HTML
    - 阶段6 `lab.js` 命名统一（独立先做）：6必改（name×5+tooltip×5+shortName+PARAMSCAN_RULE）+3trigger可选+3prod归类（BB_lower_revert zone/status+LAB_ZONES count 2->3，特买备买上线后3->5）
    - 阶段7 数据上线+验证：跑历史信号回填+deploy.sh推数据+收盘跑simulate_trade.py --all+线上验证
    - **并行规划**：阶段6（lab命名）独立先做和阶段1-3（后端）并行；阶段4+5依赖阶段1；阶段7依赖1-6

### ✅ 2026-07-20 买点信号净化调研（R1/R2 已实施上线 2026-07-21/22；R3 保持现状 / R4/R5 远期研究保留）

> 详见 `NOTES.md §48 小节AB`。回测脚本 `/tmp/buy_purify_backtest.py`，结果 `/tmp/buy_purify_results.json`。基于 2016-2026（10.5 年）90 指数 13900 条买点信号回测。**核心结论**：净化能小幅拉高综合收益率（+14% 均值）但非稳态；趋势类高位过滤方向对但被 buy_special regime 依赖性拖累；均值回归类 pct 高位反而是最佳信号不应过滤。

- ✅ **R1（已实施上线 2026-07-21，升级为更强 B4_hold5d 方案，非原 buy_backup MA60 过滤）**：原 R1 计划对 **buy_backup** 加 `close/MA60 >= 1.15` 过滤（年度稳定 5.7% 滤率 10d +4%）；**实际升级为对 buy_special 加 B4_hold5d 过滤**（stateless 延后触发，覆盖更全面）。实施点：`app/compute/signals.py` L692/L712 `buy_special_filt = donchian20_up_shift5 & b4_hold5d_confirm`。原 buy_backup MA60 过滤未单独采用
- ✅ **R2（已实施上线 2026-07-22，多层叠加真过滤，绕过 regime 难题）**：原 R2 担心 2025 regime 依赖性（净化后 -1.11%）需先建 regime 识别；**实际通过多层叠加绕过 regime 难题**，3 层已上线：① h5 平衡档真过滤（R2 = C + C12 + E2 + 量价背离收紧，commit `02b477d6` + `531ff532`，signals.py L729/L779 `((dev_ma60 > 1.20) & (atr_pct > 0.03))` C 现状）② buy_special 降回撤过滤方案 B + sh 豁免（`atr_pct>=2.5% OR dist_from_low60>30%`，commit `bf373f5e`）③ 第三层 peak_dd_filter_mask 叠加（signals.py L838-843 `buy_special_set` 排除命中日）。详见 NOTES §48 小节 AT/AU/AV
- **R3（不推荐，保持现状）**：对 **buy/buy_aux** 加 pct_rank 过滤。buy 的 pct high 桶 +2.31%/pf 3.47 是最佳（pullback in uptrend），过滤会误杀最佳信号使收益反向
- **R4（远期研究）**：调查 2025 buy_special 高位反超根因 + regime 识别指标（趋势市/震荡市判断），赋能 R2 自适应过滤
- **R5（远期研究）**：当前过滤误杀率 53%（删除组超半数是赢家），本质"非选择性删除"。研究更选择性指标（量价配合/cross 软分级/行业景气）替代简单位置过滤
- **验收数据**（主控逐字复算口径）：
  - 4 类买点 2016+ 总数：buy=2474 / buy_aux=3314 / buy_special=7095 / buy_backup=1017，合计 13900
  - buy_special 占比 51.0%（最频繁，确认用户假设），年均 675 次
  - 10d 基线：buy +1.11%/pf 1.57 / buy_aux +0.37%/1.18 / buy_special +0.61%/1.36 / buy_backup +1.60%/2.26
  - MA60 high 桶 vs mid 桶 10d 均值：buy_special +0.23% vs +0.71%（high 差 68%）/ buy_backup +0.85% vs +1.53%（high 差 44%）
  - buy pct high 桶 vs low 桶 10d 均值：+2.31% vs +0.94%（high 反而好 2.5x，pct 过滤反向）
  - 趋势类 conservative 净化（仅 TF 过滤，MR 不动）：10d +0.72%->+0.82%（+14%），pf 1.40->1.45，filter 36.1%
  - buy_special pct_only_bal 2025：基线 +1.73% -> 净化后 +0.62%（**-1.11%，最大样本年反向**）

### 🆕 2026-07-21 盘中事故后续根治（intraday 覆盖 + 国家队 mootdx 失效）
> 今日盘中修复 3 事故（均已临时修复上线），根治待办防复发。详见 NOTES §48 小节X+Y（已落档，9 根治项 8 闭环 1 遗留 A1）。
- **intraday 事故根治**（commit 94c79041 方案Y deploy 12:29 午休违规，deploy.sh 通配带入工作区 17:55 旧版覆盖 main 的 11:30 实时版；已 commit 64d43f8d/a6d86178 恢复 7-21 实时）：
  1. ~~trade/data/sentiment.db 改 symlink 指向 trade-data DB~~ ✅ 2026-07-22 实施（symlink -> trade-data/data/sentiment.db，collected_at=11:30:06 对齐 trade-data，WAL/SHM 不存在，备份 sentiment.db.bak.20260722，intraday 13:00 写 trade-data 不受影响，详见 NOTES §48 小节AK）
  2. ✅ **deploy.sh 跑前恢复 intraday_snapshot.json/.gz 到 origin/main 版**（已闭环 2026-07-21，commit `c5e2b7ae` L47-52：`git checkout origin/main -- intraday_snapshot.json/.gz` + `reset HEAD` unstage，清工作区残留防通配带入，§8 警告根治）
  3. ✅ **deploy.sh 加时段闸门**（已闭环 2026-07-21，commit `c5e2b7ae` L32-42：交易日盘中 09:30-15:30 拒跑全量 export+deploy，`IS_TRADING` + `CURRENT_HM` 检查，force 参数绕过，类似 intraday_snapshot.sh IS_TRADING 闸门）
  4. ✅ **intraday_snapshot.sh git add 补加 .gz**（已闭环 2026-07-21，commit `3796ecf3` L133-136：原只 add .json 不 add .gz 致 .gz 仍旧版，补 `intraday_snapshot.json.gz` + `schedule_stats.json.gz` + period 通配 `.gz`，参照 59cffecb 7-22 通配补 period .gz）
  5. ✅ **rsync -a -> --checksum 根治 schedule_stats.json quick check 跳过**（2026-07-22，commit 7d9c3c99，详见 NOTES §48 小节AN）：intraday_snapshot.sh L116 + deploy.sh L100 改 `rsync -a` -> `rsync -a --checksum`，强制 MD5 比对根治 quick check 误判（schedule_stats.json last_run "11:30"->"13:05" size 不变+mtime同秒，quick check 跳过拷贝致 worktree 旧版 commit 不含线上执行统计停滞）。trade+trade-data 两版本同改（launchd 跑 trade-data 版本）。deploy.sh L114 DB 同步(--exclude=logs/)不动（sentiment.db 80MB --checksum 开销大+size 每次变）。
- ✅ **mootdx 失效影响范围评估**（已闭环 2026-07-22，4 文件全处理）：① `runner.py` 加 `signal.alarm(1800)` 30min 超时保护防 SIGTERM 阻塞复发（commit `ff250d87`，NOTES §48 小节AL）；② `mootdx_daily.py` 内置 `consecutive_fail_limit=50` 触发后自动切 baostock fallback（commit 历史已具备）；③ `industry_width.py` 用 `mootdx_daily_raw` 表，间接受 baostock fallback 保护；④ `width_history.py` 加 `MIN_CODES_PER_DAY=1000` 保护防残缺样本覆盖正确值（commit `f8897621`，NOTES §48 小节AQ）。原 ETF 国家队已换 akshare fund_etf_hist_sina（commit `65610d6b`）。A 股 tab 有 baostock 兜底正常
- **换源后须同步 `gzip -kf` 补 .gz**（教训：fetchJSON .gz 优先 + DecompressionStream，只生成 .json 不更新 .gz 致线上读旧 .gz 仍显 0）
- **static-site/data/a-stock-*.json 残留 M 确认**：下次 deploy 前确认工作区无旧版残留（94c79041 事故根因再现）
- ✅ **memory MEMORY.md 清理过时条目**（已完成 2026-07-22，commit `84815d3d`，19->18 条：删 trade-sim-time-window 指向不存在文件 + 更新 trade-sim-chip-three-tier hook）：原 ~40 条索引（实测 ~19 条），有些已完成（如"已100%上线"指针）可删，减少每次注入 context token

### 🟢 远期 / 搁置
- ~~**L3189 `zhaban_rate:5` dead code 清理**~~：✅ 已清理（commit `11c9e9e1`，2026-07-21，详见 NOTES §48 小节I.1）。L3192 `a_width_seal_rate:14` 同类一并清理。
- ~~**端到端互斥验证**~~：✅ 已验证（2026-07-20 23:54，`8839300` 真跑 4 场景全通过，详见 NOTES §48 小节I.2）。
- ~~**C7 P4 交互式自定义分析**~~：✅ 已完成（2026-07-21，commit a241d1f1 后端 + 9a0648cb 前端，8+8 维度+历史类比 Top3+55 静态 json，线上 #lab?sub=custom，详见 NOTES §48 小节L）。
  - ~~**market 融合全 55**~~：✅ 已完成（2026-07-21，commit 75a67d03，`_labCustom*` 10 函数+2 常量抽到 common.js 348 行，app.js `_MARKET_ANALYZE_IIDS` 55 白名单+分数卡+3 调用点，alert_match.py PREGEN_TARGETS 40->55+15 新 JSON，详见 NOTES §48 小节M）。
  - ~~**select 检索**~~：✅ 已完成（2026-07-21，commit 644009b7，lab.js selector 加检索 input+oninput 筛选代码/名称+optgroup 无可见子隐藏+无匹配提示，isSwitch/onchange 清空恢复，style.css `.lab-custom-search` 3 皮肤，不破闪烁修复，详见 NOTES §48 小节N）。
  - ~~**select 扩 55**~~：✅ 已完成（2026-07-21，commit 6106d556，common.js 新增 `_LAB_CUSTOM_DIV`(3 红利)+`_LAB_CUSTOM_HK`(3 港股)+`_LAB_CUSTOM_GLOBAL`(9 全球) 3 常量+挂 window，lab.js select 加 3 新 optgroup(红利/港股/全球指数)+3 处 hint 计数扩 5 常量求和，15 新 iid 名称对齐 app.js `_INDEX_NAME_MAP`+global-all.json，不破闪烁修复/检索/不动 `_labCustom*` 函数，跳过 deploy.sh 自行 commit+push feat+main，详见 NOTES §48 小节N 补充）。
  - ~~**human_text 中性档拼接命中维度**~~：✅ 已完成（2026-07-21，commit b28aa6ac + be3bd749，`build_human_text` 中性档（总分<=60）若 dim_hits 有单维度命中（>=60）拼接 `H1 情绪过热/H4 位置偏高 有命中,整体加权后未达关注线`，避免用户困惑"显示中性但维度表有命中"。55 JSON 重生成（HIGH 中性+命中43/LOW 中性+命中27），关注/过热档不变，线上 hsi 验证通过，详见 NOTES §48 小节Q）。
  - ~~**阈值统一方案A**~~：✅ 已完成（2026-07-21，commit fc155ff1 + a8d42e30，`DIM_THRESHOLDS` H1/H4/L1/L3 threshold 80->60 全表 16 维统一 60，消除主表 dim_hits（HIT_THRESHOLD=60）与折叠表 data_thresholds（H1/H4/L1/L3=80）展示冲突（H1=71.79 主表✓命中 vs 折叠表✗未命中）。纯展示层不碰算法（high_alert 走 _weighted_score 不引用 DIM_THRESHOLDS）。55 JSON 重生成，6 个 H1/H4/L1/L3 value in [60,80) hit=True 验证生效（旧 80 下 False），线上 hsi H1 threshold=60 hit=True / cyb H4 value=73.81 threshold=60 hit=True 验证通过，详见 NOTES §48 小节R）。
- **P2-5 app.js/lab.js 拆 chunk**：远期性能，现 CF br 压缩+defer 后可接受。
- **百度推送效果验证**：搁置（用户 2026-07-14 定），后续有需要再启。**2026-07-22 删 HTTP 百度推送（push.zhanzhang.baidu.com）修 mixed content，保留 HTTPS zz.bdstatic.com，见 NOTES §48 小节AE**。
- **trade_sim 迁 R2**：✅ 2026-07-20 评估=不迁（小节G），**2026-07-22 反转=已迁 R2**（s.sugas.site 瘦身需要，97 文件 200M，见小节AK）。**2026-07-22 upload_r2.py Content-Type 根治（octet-stream -> 按扩展名推断），trade_sim/index/industry 重传 R2，curl 验证 text/html，见小节AP**。
- **data JSON 迁 R2**：✅ 阶段1+2+3 全完成（2026-07-22，index/industry/trade_sim 迁 R2，remote 523M->158M 解 s.sugas.site 超限恢复部署；剩裸 JSON .gz 后续按需，详见 NOTES §48 小节AK）。

### 下轮起点
- ~~7-21 收盘后验证 ETF 方案 A 6 天回填是否自动补 7-20 数据。~~ ✅ 2026-07-21 验收通过（commit `d37c2c71`，etf_daily MAX=20260720，详见 NOTES §48 小节J）。
- ~~ETF ohlc 隐患复查：7-21 20:07 槽跑完后复查 7-20 close/amount 是否补齐（凌晨 mootdx OHLC=0，需 20:07 槽或 update_all 补）。~~ ✅ **2026-07-22 验收通过，待办关闭**（commit `65610d6b` 换源 + 7-21 20:07 槽 ohlc=60 + 7-22 02:00 backfill 同 ohlc=60 稳定；DB 7-17/7-20/7-21 各 12 ETF close/amount 全非 NULL 非 0；线上 etf_date=20260721，详见 NOTES §48 小节AJ）。
- usdcnh 7-27 周一 curl 验证防复发。
- R2 P0/P1 已全闭环，P2 data JSON 迁 R2 阶段1+2+3 全完成（2026-07-22，remote 523M->158M，s.sugas.site 恢复部署，详见小节AK）。
- C6 预警条已上线，下步观察线上预警准确性。P4 交互式分析已上线（#lab?sub=custom，详见 NOTES §48 小节L）。
- deadcode + 验锁两条小节H.3 遗留已闭环（晚续4），无遗留。

---

## 工作约定（子进程必读）

1. **领任务**：读本文件，找第一个 `状态: pending` 且 `依赖` 已满足的任务，把状态改 `in_progress`、填 `负责人`（你的标识）。
2. **干活**：按 `描述` 做，达到 `验收标准`。改动前先读相关源码。技术细节自己定；**碰到方向性分叉不要猜——停下、在 `结果备注` 写明、汇报给监管**。
3. **写结果**：做完（或失败）后在 `结果备注` 写：改了哪些文件、做了什么、成功 / 失败、遗留问题。状态改 `done` / `failed` / `blocked`。
4. **汇报**：你的最终消息就是汇报。说清：做了什么、改了哪些文件、验收标准是否达成、有无遗留、下一步建议。
5. **环境约束**（踩过的坑）：
   - pypi / github 用清华镜像；Clash 代理 `127.0.0.1:7890` 拦截东财 → 全局 `trust_env=False`。
   - 东财 push2 / clist / 板块端点反爬封 → 用 sina 源或直爬 + `em_get` 防封（1s 节流 + 0.1-0.5s jitter + HTTPAdapter Retry 429/5xx）。
   - 手动值保护：upsert 的 `ON CONFLICT DO UPDATE` 末尾必须 `WHERE daily_metric.source != 'manual'`（防日采集覆盖手动补录）。
   - NaN 过滤：`collect_series` 里 `if v != v: continue`（`float(NaN)` 不抛异常，必须显式判）。
   - 不要 `cd` 进 compound 命令（用绝对路径）；不要 commit / push（用户没让）。
6. **验收（2026-07-06 调整）**：监管**不自己跑命令验收**（curl/grep/DB 在监管上下文费 token）。改派**验收子进程**（fresh context）跑抽查（DB/curl/复跑/语法），结论写进任务条目「验收备注」+ 向监管汇报。监管读干活汇报 + 验收汇报决定放行。review gate 任务必派验收子进程；非 review gate 可省（信任干活子进程自验）。不暂停等用户，全部完成或卡住才通知。最终用户 + 外部测试整体验收。详见记忆 `supervisor-loop-mode`。
7. **测试**：API 改动用 `curl localhost:8000/...` 验；采集改动跑 `python -m app.collector.runner`；计算改动跑 `python -m app.compute.runner`；前端改动浏览器看。


---

> 22 任务清单（A1/A2/A3/G1/E1/E2/E3/B1/C1/B2/F1/F2/F3/D1/D2/D3/S1/SignalStats/B1S1/HomeSignalGrid 等）+ 进度看板 + 2026-07-13/14/19/20 各轮交接状态已归档到 [docs/archive/TASKS-done.md](docs/archive/TASKS-done.md)。

---


## R2优化+备份方案待办（P0+P1 已全闭环 2026-07-20；P2 data JSON 迁 R2 阶段1+2+3 全闭环 2026-07-22，详见 NOTES §48 小节A+AK）

> 2026-07-15 晚调研，2026-07-20 实施 P0×3 + P1×3 全闭环。.git gc 后 136M（原 1.1G）。DB 压缩实测最优 .dump+gzip 13.8MB(17%)，线上用 .db.gz 24MB(29%)。

### P0（✅ 全 3 条已完成 2026-07-20）
1. ✅ **DB备份压缩改传 .db.gz**（1a573c00）：87MB->24MB 省72%（backup_db.sh 产 .db.gz + upload_r2.py 上传压缩二进制）
2. ✅ **R2 清理改脚本侧分层替代 Dashboard lifecycle**：未配 Dashboard 规则，改 upload_r2.py `_prune_r2_backup` 三层清理 backup/30+weekly/28+monthly/365（更可控，不依赖手配）
3. ✅ **backup 失败邮件告警**（1a573c00）：复用 notify.py（backup_db.sh 失败发邮件，原仅日志无告警风险消除）

### P1（✅ 全 3 条已完成 2026-07-20）
4. ✅ **恢复演练 verify_backup.sh**（500b7338）：R2 拉备份解压 integrity 校验+行数对比，只读不改生产 DB
5. ✅ **R2 多版本保留分层**（0c22524f）：日30天+周4周+月12月（_maybe_upload_weekly/monthly 复用日 payload，ISO week/year+month，节假日顺延）
6. ✅ **git gc**：.git 1.1G->136M（松散925MB 未 gc 积压清理）

### P2（按需）
7. ✅ **trade_sim HTML 52MB 迁 R2**：2026-07-20 评估=**不迁**（小节G），**2026-07-22 反转=已迁 R2**（s.sugas.site 瘦身 523M->158M 需要，97 文件 200M git rm --cached 保本地 untracked，commit b4b75671，见小节AK）。
8. ✅ **data JSON 迁 R2（阶段1+2+3）**：2026-07-22 全完成。阶段1 R2 上传(trade_sim 97+index 180+industry 268，CORS *)+阶段2 前端改读 R2(app.js 4处+lab.js 3处，commit f145a409，app.min.js?v=b4eaf1ec)+阶段3 线上瘦身(commit b4b75671 git rm --cached index/trade_sim 保本地 untracked+.gitignore L63-65+intraday L131 改 no-op，remote 523M->158M < 300M，s.sugas.site 恢复部署 v=b4eaf1ec tooltip 颜色根治)。STATIC_DIR fix a0ba8431。剩裸 JSON .gz 后续按需。详见 NOTES §48 小节AK

### skip（调研后排除）
- 增量备份：压缩后全量仅24MB，收益锐减
- WAL 改造：已在线热备（backup_db.sh `.backup`），最佳方案无需改
- R2 扩容：700MB 远在 10GB 免费额内

## 全站性能优化待办（2026-07-21 扫描，详见 NOTES §48 小节O）

> 10 维度扫描 s.sugas.site（MaoziYun/3.17.0 静态托管，非 CF，_headers 不生效）。最大痛点 = MaoziYun 零压缩 + 不读 _headers，全站 JS/CSS/JSON 全裸传。完整报告留底 `/tmp/perf-report-full.md`，扫描原始数据 `/tmp/agent-progress-perf-scan.md`。本次只扫描+落档不改码。

### P0（最影响首屏）
1. **零压缩 - 全站无 Content-Encoding**：MaoziYun/3.17.0 不做 gzip/br，JS/CSS/JSON 全裸传。首屏 ~466KB gzip 可降到 ~140KB（省 70%+），echarts 629KB 可降到 ~180KB。
   - ~~根治方案：迁 CF Workers（wrangler.jsonc 已存在）自动 br 压缩，工作量 M（迁移+测试+域名切流）。~~ ✅ **2026-07-22 闭环**：ss.fx8.store `server: cloudflare` 上线，push main 触发 CF 构建环境自动 wrangler deploy（无需本地 wrangler），`content-encoding: br` 生效。验收证据 + 完整闭环见 NOTES §48 小节AR。
2. **大 JSON 无压缩传输** ✅ 已完成（commit eea226f3 + 0b3082f1，2026-07-21，方案B：MaoziYun 不支持 Content-Encoding，前端 DecompressionStream 显式解压，244MB->32MB 省 86.9%）：data/ 244MB / 396 文件全裸传。industry-3y.json 9.6MB / etf_national_team-all.json 8MB / a-stock-all.json 6.9MB，切 tab 等待 1s+。
   - 实施方案：export.py `write_json` 加 .json.gz 输出（>100KB）+ scripts/export_alert_analyze.py 全量 .json.gz + 前端 fetchJSON/fetchJSONProgress 优先 .json.gz + DecompressionStream 解压 + 失败 fallback .json + 3 处直连 fetch alert_analyze 改用 fetchJSON。详见 NOTES §48 小节S。
   - 原"缓解方案：export.py 产 .json 同时产 .json.gz + deploy.sh 上传双份按 Accept-Encoding 选"调整：MaoziYun 不按 Accept-Encoding 选（不支持 Content-Encoding），故走前端显式解压方案B 而非服务器自动选 .gz。

### P1
3. **style.css/lab.css 未 minify** ✅ 已完成（commit ada602e0，2026-07-21，rcssmin 1.2.2，style.css 133KB->97KB 省25.5% / lab.css 57KB->44KB 省23.1%，index/about/privacy 引 .min.css?v=新，线上 s.sugas.site 验证 HTTP 200 + content-length 一致）：原 `scripts/build_min.py` 只处理 JS 不处理 CSS，index.html 直接引非 min 版。
   - 扩 build_min.py 加 CSS minify（rcssmin 1.2.2 纯 Python），产 style.min.css/lab.min.css，index.html 改引用 + bump 版本号，工作量 S（立即可做无需迁站，优先推荐）。**实测压缩率 23-26%（非预估 70-80%：CSS 注释+空白仅占 20% 无 data:URI，rcssmin 不改规则保视觉一致，70%+ 是 JS mangle 水平不适用 CSS；更高压缩需迁 CF br 压缩 P0 项）**。详见 NOTES §48 小节P。
~~4. **缓存策略弱**：所有资源统一 max-age=1200，版本化资源（app.min.js?v=）应 max-age=31536000 immutable。迁 CF 后 _headers 加 `/*.min.js`/`/*.min.css` -> immutable，工作量 S（MaoziYun 不读 _headers 暂无效，迁 CF 后落地）。~~ ✅ **2026-07-22 闭环**：CF Workers 主站上线后 _headers 全生效，curl 验证 `app.min.js` 返回 `cache-control: public, max-age=31536000, immutable`（`/style.css` /`/app.min.js` /`/lab.min.js` /`/lab.css` /`/qr.js` /`/vendor/*` 均配 immutable，见 `static-site/_headers`）。详见 NOTES §48 小节AR。
~~5. **缺 ETag**：仅 Last-Modified 无 ETag 精细化缓存验证（迁 CF 后自动补）。~~ ✅ **2026-07-22 闭环**：迁 CF Workers 后 static assets 由 CF 托管，curl 验证 `app.min.js` 返回 `etag: W/"728ad74e7c4605dd879c90ee36f2c796"`（CF 标准行为自动生成）。详见 NOTES §48 小节AR。
6. **echarts 629KB vendor**：虽已动态加载（P2-5 闭环见 NOTES §48 小节K），单文件仍大。换 echarts core + 按图表类型 import（line/bar/pie/scatter/candlestick 等）可降到 ~200KB，工作量 M（需测图表类型覆盖有回归风险）。

### P2
7. ✅ **lab.css 首页强加载**（已完成 2026-07-22，commit `ff1bfe04`，改 preload 异步加载 + noscript 兜底，省 44KB 首屏阻塞）：原 57KB render-blocking，仅 lab tab 用。原计划改 preload 或按 tab 切换加载，工作量 S 收益小（CSS 已 max-age=1200 缓存）。
8. ✅ **HTML 内联 script 较多**（已完成 2026-07-23，commit `41c0f8a7`，4->1 只剩 theme 防闪烁保守保留）：原 index.html 有 3 个内联 `<script>` 块（hm.baidu/navSticky/zz.bdstatic），已外部化到 `inline-init.js`（defer 统一引用）。theme 防闪烁 script 保留为内联（避免 FOUC 闪烁，保守不外部化）。
~~9. **无 CSP/X-Frame-Options/Permissions-Policy**：_headers 不生效，迁 CF Workers 后落地（CLAUDE.md §8 已记）。~~ ✅ **2026-07-22 闭环**：CF Workers 主站上线后 _headers 全生效，curl 验证 `content-security-policy-report-only`（CSP）/ `strict-transport-security: max-age=63072000; includeSubDomains; preload`（HSTS preload）/ `x-frame-options: SAMEORIGIN` / `permissions-policy: camera=(), microphone=(), geolocation=(), payment=(), usb=(), accelerometer=(), gyroscope=()` 全部返回。详见 NOTES §48 小节AR。

### 优先级建议
P1/S CSS minify ✅ 已完成（小节P）-> P0/M data JSON 预压缩 ✅ 已完成（小节S，方案B 前端 DecompressionStream 显式解压）-> ~~P0/M 迁 CF Workers（根治零压缩+解锁 _headers 全部能力：immutable 长缓存+CSP+ETag+X-Frame）~~ ✅ **2026-07-22 闭环**（ss.fx8.store `server: cloudflare` + `content-encoding: br` + `cache-control: immutable` + `etag` + CSP/HSTS preload/X-Frame/Permissions-Policy 全 curl 验证返回，详见 NOTES §48 小节AR）。

### skip（扫描后排除）
- HTTP/2：已启用 ✓
- HSTS：已启用 ✓（max-age=63072000）
- TTFB：<300ms 可接受（日本节点 cf-ray NRT）
- og.png：60KB 已优化（2026-07-16 67->36KB 256色压缩）
- fetch 冗余：仅 6 次无严重冗余（app.js 4 + lab.js 2 + common.js 0）

---

## 🆕 2026-07-21 全站深度审计（3 agent 报告综合，等用户看后安排修）

> 用户要求"对全站功能全面深度重新检查，看异常/待验证/未发现/误报，改软链后计划任务是否正常"。派 3 background agent：性能+部署（ac225cfc5a50ad58c）/ 计划任务（a6e223adab14a5170）/ 功能（a93a577a3e79a695f）。3 报告全收齐，主控逐字验收关键结论（.gz 滞后 curl 属实）。**不擅自动修，等用户看后安排**。

### P0（线上正在发生/高影响）
1. ✅ **.gz 滞后致前端读旧数据**（已闭环 2026-07-21，commit `d3e6bf8f` P0-1 + `59cffecb` 7-22 通配补 period .gz）：原 overview/summary/schedule_stats/hk-1y/sentiment-all 线上 .gz 滞后 1-12h 到 4 天，前端 fetchJSON .gz 优先（app.js L841-849 DecompressionStream 显式解压）读旧数据。
   - 验收：线上 overview.json.gz collected_at **02:05:50** vs overview.json **14:35:06**（滞后 12.5h）；summary.json.gz **7/20** vs .json **7/21**；schedule_stats.json.gz **7/16** vs .json **7/20 17:50**（est 15分钟旧文案）
   - 根因：intraday-snapshot 定时任务（trade-data 跑）更新 .json 不生成/推送 .gz；全量 deploy（02:06 export.py GZ_THRESHOLD=0）才生成 .gz。盘中 .json 更新到 14:35，.gz 停 02:05
   - 修复：intraday-snapshot.sh 补生成 overview/summary/hk-1y/sentiment-all/schedule_stats 的 .gz 并 push（参照 3796ecf3 修 intraday_snapshot.json.gz 做法）。**盘中改定时任务脚本撞正在跑实例有风险，等收盘后修**（已修，d3e6bf8f 收盘后落地）
2. ✅ **lab/ 65 JSON 缺 .gz**（已闭环 2026-07-21，commit `d3e6bf8f` P0-2 `export.py` 批量 gzip glob->rglob 递归扫 lab/ 生成 65 个 `lab/*.json.gz`，94MB 未压缩->全量 .gz 上线）

### P1
3. ✅ **全球指数滞后 4 天**（已闭环 2026-07-21，commit `50663a42` P1-3 + `76f71935` rebase 7/20 数据回填）：`app/collector/index_backfill.py` 加 5 全球指数（nikkei225/kospi/ftse100/dax/cac40）到 `HK_GLOBAL_INDICES` backfill 列表，`require_today=False` 用 >3 天阈值覆盖源延迟（sina T+1）+ 跨周末，避免误报 fail。实测 `global-1y.json` gold/oil/wti_oil date=20260722 已更新到 7-22，详见 NOTES §48 小节Z
4. ✅ **两融滞后**（已闭环 2026-07-22，T+1 正常）：`a_fund_margin`（a-stock metrics 内）最新 date=20260721（T+1 滞后正常，7-22 23:00 task 跑后从源拿到 7-21 数据，7-22 数据要等 7-23 23:00 task 跑才更新）。`schedule_stats.json` 两融 `last_run=2026-07-22 23:00` 任务跑了。原 7-17 滞后是采集源 T+1 未发当日数据 + rzhb_backfill.sh 22:10 launchd 槽缺失，已加 launchd 任务（22:10 跑 stock_margin_sse/szse）根治。详见 NOTES §48 小节AD
5. ✅ **mootdx_daily.db 加 .gitignore**（已闭环 2026-07-21，commit `d3e6bf8f` P1-5）：`.gitignore` 已加 `data/mootdx_daily.db` + `-wal` + `-shm`，`git ls-files` 确认未追踪，类比 sentiment.db / etf_national_team.db（§10），防切分支污染已根治
6. ✅ **trade vs trade-data 不同步**（已闭环 2026-07-22，commit `ff1bfe04`，根因 = `export_alert.py` L27 + `export_alert_analyze.py` L31 的 `.resolve()` bug 解析 symlink 跳回 trade，改 `.absolute()` 根治；线上不缺：git add 通配仍 commit，alert.json + alert_analyze_hs300.json curl 200）：原观察 trade-data 缺 alert*.json / alert_analyze*.json ~80 个（trade 上 lhb_backfill 等生成未 rsync 回）。deploy.sh rsync 不带 --delete，trade 数据不丢，但 trade-data 采集端不完整
7. ✅ **lab 数据滞后 11 天**（已闭环 2026-07-22，commit `94b6cdde` P1-7b update_lab.sh 补 5 步 + `c49bb6d8` lab.js line2649 去掉 '2026-07-11' 硬编码兜底改动态显示）：根因 = `update_lab.sh` 漏跑 `lab_retest_honors.py` + 4 个顶层脚本（lab_ablation/cost_compare/param_scan/short_symmetry），致 lab_retest_honors.json 停 7/17 + 顶层 4 文件停 7/17。已补 5 步后每日自动刷新，实测 `lab_backtest_*.json` generated_at/data_cutoff=2026-07-22 已是最新。仍待用户决策更新策略（每日/按周/按需，离线回测性质非每日必须，但当前每日跑）

### P2
8. ✅ **deploy.sh L186 文案修正**（已修 commit 0304e4ef）：改"MaoziYun 自动拉取 git main 部署，有拉取延迟 + max-age=1200 缓存；wrangler 未安装，worker/headers.js 待迁 CF Workers 后手动 wrangler deploy" ~~（"wrangler 未安装待手动 deploy" 已过时）~~ ✅ **2026-07-22 更正**：push main 触发 CF 构建环境自动 `wrangler deploy`（内置 esbuild bundle `worker/headers.js`），**无需本地安装 wrangler**；headers.js 通过 `_headers` 已生效，curl 验证 CSP/HSTS preload/X-Frame/Permissions-Policy 全返回。详见 NOTES §48 小节AR。
9. **app.js/lab.js 拆 chunk**（P2-5 待办，已评估不实施）：app.min.js 252KB / lab.min.js 206KB 单文件。评估结论：拆 chunk ROI 低（4-5 工作日+高回归风险），已有 lab.js 懒加载+echarts 懒加载+defer 足够；~~真正瓶颈是 MaoziYun 不压缩 JS（实测 252KB raw 传输，本地 gzip 仅 77KB），应优先迁 CF Workers（wrangler.jsonc 已存在）一举解决压缩+_headers+CSP。~~ ✅ **2026-07-22 迁 CF Workers 已闭环**（ss.fx8.store `server: cloudflare` + `content-encoding: br` 生效，"MaoziYun 不压缩 JS" 前提已消除；拆 chunk 仍不实施，ROI 低）。保留远期待办，详见 /tmp/agent-progress-p2.md

### 误报/澄清（不需修）
- **summary zt_count 0 非误报**：intraday_snapshot 无 zt 字段，summary zt_count=0 是盘中快照未填。实际涨停在 a-stock metrics a_width_zt_count=85（7/21）/跌停 19
- **龙虎榜/两融无独立 tab**：项目无此功能（grep + ls 均无 lhb/rzhb/margin 文件），两融仅在 a-stock metrics a_fund_margin 内
- **ETF 扩展到 12 个**：prompt 假设 9，实际 12（新增 510310/159919 等），非异常是扩展
- **backfill-evening exit 1**：7-18 历史残留，8b76b6b4 已修 backfill_metrics.sh SyntaxError
- **工作区 223 个 M 文件**：7-21 最新数据（HEAD 是 7-20 旧版），非旧版残留，**不需清理**（清理反丢 7-21 数据）
- **性能审计"CF 缓存 20 分钟"误判**：s.sugas.site 走 MaoziYun 非 CF（CLAUDE.md §8），intraday 盘中被缓存 20 分钟是 MaoziYun max-age=1200 已知现状，非 CF
- ~~**worker/headers.js 未部署 = 安全头缺失**：已知现状（CLAUDE.md §8 已接受，MaoziYun 自带 HSTS + meta referrer 兜底，迁 CF Workers 后落地）~~ ✅ **2026-07-22 闭环**：`worker/headers.js` 经 CF 构建环境自动 `wrangler deploy` 上线（push main 触发，无需本地 wrangler），`_headers` 全安全头生效，curl 验证 CSP/HSTS preload/X-Frame/Permissions-Policy 全返回。详见 NOTES §48 小节AR。
- **futures actual_return 3 角色全 null**（P2-10 已澄清）：`accuracy.<role>.actual_return` 是最新日期(20260720)次日涨跌，次日收盘未就绪必为 null（futures_position.py L119 已注释设计意图）；后端另有 `latest_bet.<role>.actual_return` 查 actual_return IS NOT NULL 的最新完成日(20260717, 1.528451)，app.js L5946-5953 已有回退逻辑（ret==null 时取 latest_bet 并显示日期）。前端不报错，字段保留 latest_bet 用，无需修复

### 计划任务审计 ✅ 无异常
- 8 任务全正常运行（launchctl list 7 exit 0 + backfill-evening exit 1 历史残留已修）
- 软链修复生效（gen_schedule_stats.py L27 去 resolve，schedule_stats.json intraday last_run 7-21 14:05）
- 今日 7-21 日志正常（intraday 9 个 0935-1405 + backfill 0200 + deploy 0206）
- 各 launchd 日志尾部正常（update_all 7-20 17:56 退出码 0，intraday 7-21 14:06 commit 6f700734）

### 修复建议
不擅自动修，等用户看后安排。**P0 .gz 滞后建议收盘后优先修**（盘中改 intraday-snapshot.sh 撞正在跑实例有风险），修复简单（补 .gz 生成+push，参照 3796ecf3）。

## 🆕 2026-07-22 待办（用户睡前列，醒来处理）

### P0（阻塞上线）✅ 2 项全闭环（2026-07-22 验收）
1. ~~**MaoziYun 拉取卡住**：21:35（821265ef）后 MaoziYun 未拉取 main（2.5h+），**ATR×3 改造 + signal_stats.json + 前端展示都没上线**~~ ✅ **2026-07-22 验收通过**（R2 全迁阶段3 瘦身 remote 523M->158M<300M 解超限恢复部署；curl 三站：ss.fx8.store + s.sugas.site 均上线 `app.min.js?v=b4eaf1ec` + `signal_stats.json` 双 200。详见 NOTES §48 小节AK）
2. ~~**schedule_stats 过期版**：0d85d2f0 从 trade 跑 deploy.sh 读旧日志生成过期 schedule_stats（last_run 卡 7-16/7-17 vs 线上 7-21）~~ ✅ **2026-07-22 验收通过**（方案③ symlink：`trade/data/logs` -> `trade-data/data/logs`（8:42 建）+ gen_schedule_stats.py `90eede7f` 支持进行中任务根治时序竞态 + `0b491fc2` 推数据；curl 线上 `schedule_stats.json` last_run：intraday=2026-07-22 11:30 / backfill_evening=2026-07-22 02:00 / 其他 task 7-21（今日未到点正常）；intraday-snapshot 10:06/10:48/11:06/11:31 各推一次刷新。详见 NOTES §48 小节AF+AK）

### P1（方向决策，待用户定）
3. ✅ **ATR×3 口径错位**（已闭环 2026-07-22）：用户"信号重复"核心诉求已闭环。前端 `app.js signalLabel sell_stop_loss` 从 reason 动态提取 ATR 倍数（commit `dd463d93`，不再硬编码 ×3.5）+ 后端首次跌破触发去重 + 方案A定倍（commit `a45819e8`：csi_div 4.5 / div_lowvol 3.5 / sz_div 3.5）。原 A/B/C/D 决策不再需要（信号重复根因是 dtype bug 致 6-7x 误增，修复后已根治）。详见 NOTES §48 小节 AC/AO
4. ~~**尖尖信号过滤**（已上线预览，待观察切真过滤）：h5 预览模式（灰 pin 不删除 buy_special）已上线 **R2 = C + C12 + E2 + 量价背离收紧**。C=偏离 ma60>20% AND ATR>3%；C12=均线附近假突破(dev∈(1.0,1.1] AND drawdown_hh20<-0.02)；**E2=布林上轨外 AND ATR>3%**（新增）；**量价背离收紧=price_vol_div==1 AND ATR>2.5%**（新增，ATR 从 0.03 收紧到 0.025）。pkl 实测 R2+C12 滤率 14.24%/滤中套牢 23.31%/滤后套牢 11.09%(基线 12.83%)/滤后 10d +1.731%(基线 +1.656%)。compute() 实跑 buy_special_filtered 2454/12892=19.03%（含 90 年代高波动期数据偏多）。预览模式安全，待观察后切真过滤（drop buy_special_filtered）。详见 NOTES §48 小节AM~~ ✅ **2026-07-22 尖尖逃顶过滤上线**（close 站稳+2%容差 + R2 真过滤 OR 组合）。B4_hold5d 升级 low->close+2%容差（降假确认）+ h5 预览标灰改真过滤 drop（降套牢优先）。回测：滤率 10.66%/trap-1.43pp(12.83%->11.40%)/win+0.6pp/pf+0.04/误杀 55.82% 最低/mean 持平。compute() 验证 buy_special_filtered=0。buy_special_filtered 类型废弃（前端灰 pin 渲染保留无数据不影响）。详见 NOTES §48 小节AT
5. ✅ **买点净化**（R1/R2 已实施上线 2026-07-21/22；R3 不推荐保持现状；R4/R5 远期研究保留，与 L62-79 项一致）：R1 升级为 B4_hold5d 过滤 buy_special（非原 buy_backup MA60 过滤）；R2 多层叠加真过滤绕过 regime 难题（h5 平衡档 + buy_special 降回撤方案B + peak_dd_filter 第三层）；R3 buy/buy_aux pct 过滤不推荐（误杀 pullback-in-uptrend 最佳信号）；R4 调查 2025 buy_special 高位反超根因 + regime 识别指标；R5 研究更选择性指标替代简单位置过滤（当前过滤误杀率 53%）。详见 NOTES §48 小节AB/AT/AU/AV

### 🆕 P1-新（2026-07-22 闭环）
9. ✅ **sell_stop_loss 首次跌破 dtype bug 修复 + 方案A定倍**（2026-07-22，commit a45819e8）：`sell_stop_cond.shift(1).fillna(False)` 返回 object dtype，`~object` 是位运算非布尔取反，致 first_break==below 完全不去重（6-7x 误增）。修复 `.astype(bool)`。raw 去重：csi_div 580->117 (5x)、hs300 1765->231 (7.6x)、us_spx 856->193 (4.4x)。方案A定倍 csi_div 3.5->4.5（raw 151->115 再降24%）。同日叠加过滤逻辑仍成立（副作用：最终窗口化信号数略升 csi_div 64->86，因 BUG 版过度过滤被修正，每个保留信号都是真首次跌破）。详见 NOTES §48 小节AO
10. ✅ **buy_special 降回撤过滤方案B + sh 豁免上线**（2026-07-22）：尖尖逃顶（小节AT）trap-1.43pp 但 mdd 未改善（基线 mdd_20d -4.52%/尖尖率 11.34%）。agent 调研方案 A/B/C，用户确认采纳 **方案 B = `(atr_pct>=2.5%) OR (dist_from_low60>0.30)` + sh 豁免**。效果：保留 12085/15809(76.5%) / mdd -4.52%->-4.01%(-0.51pp) / 尖尖率 11.34%->8.50%(-2.84pp，过滤率25%) / ret20 +2.47%->+1.62%(-0.85pp 可接受)。sh 豁免：sh 实测 mdd 微退化(-3.72->-3.91) + ret20 损大(+5.27->+1.90) 故不应用，其他9指数均改善。第三层叠加（不替换 B4 close 站稳 + h5 R2 真过滤），buy_special_set 排除 peak_dd_filter 命中日不发不更新游标。signals.py 改 4 处（L666 占位 + L785-800 计算+sh豁免 + L820-823 set排除）。compute()+store() 验证：buy_special 15809->12369(含美股)，sh 742 不变，国内 sz/hs300/csi500/csi_div 与调研完全一致。详见 NOTES §48 小节AU
11. ✅ **sh 专属 C1|D1a 叠加降尖尖上线**（2026-07-22，替代小节AU sh 豁免，升级自单 C1）：sh 豁免致 sh 尖尖率 10.38%（10 指数最高）。agent 调研方案 B 对 sh 误滤根因（dist_from_low60>30% 对 sh 趋势中继误滤）+ C1 洞察（dist_from_high>=15% 精准滤低位假突破，尖尖组 11.13% vs 非尖尖 5.59% ratio 1.99，>=15% 档尖尖率 23.91% baseline 2.3 倍）。先上线单 C1（commit 0da514e0 + 5dce98f7，sh buy_special 612），再升级为 **C1|D1a 叠加**（用户 2026-07-22 确认）。叠加公式 `((atr_pct>=0.025)|(dist_from_high>=0.15)) OR ((atr_pct∈[0.018,0.025))&(dist_from_low60>0.15)&(dev_ma60>1.05))`，D1a 补 C1 未覆盖的"中波动+涨多+均线之上"共振区。叠加效果（vs 单 C1）：612->502(保留 82.2%) / peak(<-10%) 7.35%->5.58%(-1.78pp/降 24%) / mdd -3.72%->-2.65%(改善 1.07pp) / ret20 +6.29%->+4.31%(损 1.96pp 可接受) / bot_acc 69.12%->68.33%(-0.79pp) / Jaccard 重叠率 30.8%（C1 与 D1a 互补性强）。其他 9 指数继续方案 B 不变。signals.py 改 sh 分支 L809-821 为叠加 mask + 注释。compute()+store() 验证：sh 612->502，20d mean +4.31%/win_rate 68.33%（signal_stats.json 完全吻合）。详见 NOTES §48 小节AV

### P2
6. ~~**width pipeline 7-21 18:03 被 Terminated:15**：查 width 数据完整性，必要时重跑 backfill_evening 补 width~~ ✅ **2026-07-22 P0-b 闭环**（runner.py mootdx step 加 30min `signal.alarm` 超时保护防 SIGTERM 阻塞复发，详见 NOTES §48 小节AL；**错误值修复 P0-a**（7-17~7-20 用 84 只残缺样本算错误宽度 a_width_zt_count=1）✅ 2026-07-22 闭环（7/20 baostock 数据补 mootdx + 7/1-7/19 从备份恢复 17932 行 + width_history.py 加 MIN_CODES_PER_DAY=1000 保护防复发，详见 NOTES §48 小节AQ）
7. ✅ **collect_health level=error 但 message=ok**（已验证 2026-07-22，`8420871a` fetchers.py L201-202 在位，矛盾消失：线上 overview.json level=error + message="direct:market_fund_flow 两源皆败无数据"，status 与 message 一致。注：level=error 本身是真实采集失败（a_fund_main 两源没采到）非误报，属另一采集问题，见下条补注）：8420871a 已修 fetchers.py（空列表返"两源皆败无数据"）但 overview.json 仍矛盾，从 trade-data 重跑 export 验证修复是否生效
   - ✅ **主力净流入第三源 IP 风控联动监测**（已实施 2026-07-22，commit `30be6f45`，`direct.py::fetch_market_fund_flow` 加第三源 `push2/api/qt/clist/get`）：722 主力净流入 4 次 backfill 全 fail，根因调研发现"双源"实为伪双源（akshare 备源底层与主源同 URL push2his）。新增第三源用不同 API 路径（clist/get 个股排名 vs fflow/daykline 资金流 K 线）+ 不同接口语义兜底。NOTES §48 小节AW 落档 IP 风控联动行为：push2his + push2 同属 eastmoney.com，触发阈值后联动封，第三源不在反爬名单仍可用。验证：主源 -195.55 亿 vs 第三源 -195.36 亿（5206 只汇总），差异 0.1% 口径对齐。限制：① 联动风控可能同步封 ② 只能拿当日不能补历史
8. **两融 T+1 显示**（可接受现状）：7-21 23:00 跑了源 T+1 未发当日（latest=20260720），last_run 卡 7-20。可改 schedule_stats 逻辑(任务跑了就更新 last_run 标"无新数据")或前端"数据更新规则"加注两融 T+1
9. 🔄 **trade_sim JSON 持有时长旧 bug 值清理**（2026-07-23 核实，真未完成）：3 个 JSON 文件（`trade_sim_sh_full.json` mtime=7-22 22:55 / `trade_sim_hk_hscci_full.json` / `trade_sim_sw_801040_full.json`）仍含多笔分批建仓子回合 hold_days 累加的旧 bug 值（实测 sh_full 最大 9253 天、hk_hscci 最大 6982 天，commit message 举的 2037->451 天例子是 csi_div 品种）。**后端已修**：`scripts/simulate_trade.py` L509 改最早买入->卖出方案A（commit `a1f2b281` 7-23 00:04）。**前端已兼容**：`app.js _tradeSimHoldDays` L7531 重算旧 JSON 显示 451 天（UI 零影响）。**真未完成**：a1f2b281 commit 后未重生这 3 个 JSON（mtime 早于 commit 时点），下次跑 `simulate_trade.py --all` 重生 100 品种时自动清理，或单独重生这 3 个品种。详见 NOTES §48 小节AX 遗留

---

## 🆕 2026-07-23 待办（用户列，已验收方案待实施）

### P1-新-A 盘中信号收盘消失高亮提醒（方案已验收，待实施）

**背景**：盘中每30min（9:35~15:05）intraday_snapshot 重算 signal_daily 覆盖+推邮件（信号进 `signal_notified.json` 去重）；17:50 收盘 update_all 用收盘价再覆盖 signal_daily。现无任何"盘中 vs 收盘"对比机制。用户诉求：盘中推了某 buy* 信号后若收盘消失，应高亮提醒已执行买入用户隔日止盈/止损避免伤害。

**关键发现（调研已验收）**：
- `data/signal_notified.json`（格式 `{date_str: [[index_id, signal], ...]}`，7天清理）天然就是"盘中已推送信号快照"，收盘 signal_daily 全量覆盖后对比即可，**无需新建表/改表结构/额外采集**
- 信号消失敏感性：buy_backup（Supertrend对当日close极敏感）> buy_special（Donchian+5日站稳确认）> buy/buy_aux/sell/sell_stop_loss（中等）
- `check_signals.py` L40/L42/L120 已有 load_signal_notified，现只做去重不做 fade 检测
- 插入点：update_all.sh L91 收盘 check_signals.sh 之后（此时 signal_daily 已是收盘最终版）

**方案（推荐，~100行单文件为主）**：收盘 check_signals 加 `--fade-detect` 模式，对比 `signal_notified[date]` vs 收盘 `signal_daily[date]`：
- 严格消失（红警）：盘中推 (X, buy*) 收盘无 X 任何信号 = 买入理由失效
- 类型变化（橙警）：盘中 buy_backup -> 收盘 sell* = 反转
- 降级保留（黄警）：盘中 buy -> 收盘 buy_backup = 弱化
- 邮件并入收盘信号邮件一栏：主题加 ⚠️ 前缀 + 正文顶部红色横幅 + 消失信号表格（品种/盘中信号/收盘状态/建议操作），不增邮件总数

**改动点**：`scripts/check_signals.py` +80~120行（detect_fade 函数 + build_email 加 fade_alerts 参数渲染红横幅+表格，收盘模式默认开 fade-detect）/ `scripts/check_signals.sh` +2行 / `scripts/update_all.sh` 0~2行。约半天。

**产品分叉（已定推荐，等用户拍板）**：
1. 消失定义：**C 分等级**（红/橙/黄三档最完整）
2. buy 类型分级：**A 统一警示**（简单，用户自看品种）
3. sell 消失：**A 不提示**（对已卖出用户利好不提醒）
4. 盘中标签：**A 不显式打标签**（已有黄色横幅"待确认"语义够）
5. 邮件形态：**A 并入收盘邮件一栏**（不增邮件总数，⚠️前缀+红横幅够显眼）

**风险**：① 盘中信号误判频繁消失/重现 -> signal_notified.json 去重天然缓解（同日同信号只记一次，收盘只对比一次）② 无法知用户是否真买了，假设"盘中推了 buy* 就当可能买了"是合理假设 ③ update_all 失败致 signal_daily 是盘中版 -> update_all.sh L92 已有 SIGNAL_RC 检查+告警兜底

### P1-新-B pin 图表标题策略问号弹窗（方案已验收，待实施）

**背景**：右下角 📋 买卖策略弹窗是全局通用描述（所有指数共用一份静态文本）。但每个指数有 per-index 定制或多策略混搭过滤，用户诉求：每个标了 pin 信号的图表标题后加 ❓，点开显示该品类指数实际执行的所有交易策略（足够细致完整，含参数/组合/过滤条件）。

**关键发现（调研已验收）**：
- `signals.py` L346-399 `strategy_desc(index_id, cfg)` 函数**已存在但只返回 {buy, buy_aux, sell} 3 字段**，扩展到 6 字段是增量改动
- per-index 定制真实存在（坐实问号有价值）：
  - `buy_filter`（4品类 RSI 阈值收紧）：kc50/sw_801730/sw_801760 = rsi_cross_25（基线30->25）
  - `buy_aux_filter`（19品类辅买增强）：csi1000/cyb 等 = rsi_cross_40；sw_801010 等 = close_above_bl_2pct
  - `sell_no_trend_filter`（1品类）：usdcnh = true（干预市单边上行 MA60 砍光卖点）
  - skip 机制：usdcnh skip_buy / cn_us_spread skip_sell / s.a_sentiment skip_buy（RSI结构性≥40）
- export.py L491/500/507/517/527/594/611/627 + main.py 已自动透传 strategy 字段到多个 JSON，**后端扩展后前端读 JSON 自动同步**
- 前端已有成熟机制可复用：`signalHelpTip`（L816 hover+click）/ `termTip`（L702 hover）/ `rule-modal` 样式 / `_initTermPop` 事件委托（L831-903）/ `_SIGNAL_HELP_ITEMS`（L709 6类信号描述）
- 现有 hint 蓝色行（L973-975 statsHint）"📋 策略｜买:.. 辅买:.. 卖:.."只 3 字段摘要，缺 buy_special/buy_backup/sell_stop_loss + per-index 参数细节

**方案 B（推荐）**：后端扩展 strategy_desc 从 3->6 字段，每字段含 `{desc, params, filter, enabled}`（enabled="skip" 标灰删除线），export 自动写 JSON，前端标题加 ❓：
- hover pop = 一句话摘要（如"本指数：主买 RSI上穿25[收紧] + 辅买 BB下轨+RSI上穿40 + 卖 20日高回落5%+MA60+MACD + 追买/备买/止损 全启用"）
- click modal = 展开该指数 6 类策略+per-index 参数+skip 标灰+引用 📋 全局警示

**方案选型**：A 前端硬编码（维护成本高✗）/ **B 后端扩展 strategy_desc（一处改自动同步✓）**/ C 过滤现有全局（只显示触发了哪些类型不显示参数，不满足诉求✗）

**子方案**：**B1 紧凑版（推荐）** modal 只显示 6 类信号+该指数 per-index 定制参数差异（如 kc50 显示"主买 RSI上穿25[本指数收紧，基线30]"），通用过滤层（h5/R2/B4_hold5d/3日确认）引用 📋 全局弹窗不重复展开 ~30行 / B2 完整版展开所有过滤层 ~60行信息密度高

**改动点**：`app/compute/signals.py` +60行（strategy_desc 重写 L346-399 扩展6字段）/ `static-site/app.js` ~80行（statsHint 注入 ❓ + 新增 _strategyModalHTML + _openStrategyModal + click 委托 [data-strategy-help]）/ `static-site/style.css` ~10行（复用 .term-tip/.rule-modal 微调策略行）。1 个 agent 1-2 小时。

**风险**：① strategy_desc 描述须与 compute() 主循环（L582-1057）实际触发逻辑保持一致 -> 缓解：strategy_desc 内部直接读 buy_filters/buy_aux_filters dict（已实现），buy_special/buy_backup/sell_stop_loss 全局参数写常量加注释"改 compute L683/L711/L727 同步改这里"，可考虑提到模块级常量双方共用 ② 多策略混搭过滤表达 -> skip 机制 modal 显式标灰删除线 ③ 与 hint 蓝色行重复 -> 保留蓝色行作摘要条，❓ modal 作完整版，两者互补 ④ 与 pin-label-fix agent 并行不冲突（改 L973-1047 statsHint + 新增函数，不看 markPoint label L355/1093 等）

### P1-新-C ETF买卖清单 AI评分 tab（方案已验收+用户决策已定，待实施）

**背景**：用户诉求自定义分析 tab 拆"AI预警"（现有功能原样）+"AI评分"（新 ETF 买卖清单）。清单格式：序号/ETF名/买几手（1层仓=1手）/评分/选定理由（点击弹窗看详情）。分买卖两列表按评分排序。解决场景：①开仓买什么性价比高不被套 ②手里有ETF不知该不该卖。评分综合自定义分析+近期买卖点+情绪分。手数逻辑：3手是市场均衡基准+上限，AI价值=向下减档到2/1/0手（0手不开仓也是有效输出）。

**关键发现（调研已验收）**：
- tab 拆分有先例：lab.js L3588 `_LAB_SUB_TABS` 数组，custom 改名"🤖 AI预警"+新增"📈 AI评分"子 tab，renderSignalLab 加分支 + hash 白名单加 aiscore
- **核心评分能力现成可复用**：`app/alert_score.py` L527 `compute_alert_for_target(target_id, target_type="etf")` 已支持 ETF，8+8 维度加权评分（H1情绪过热/L1情绪冰点/H7汪汪队离场/L4入场等）；L496 有 ETF 专属逻辑（H1/L1用RSI 120日滚动百分位，H7/L4汪汪队share_outflow/share_surge）
- **理由弹窗现成可复用**：`app/alert_reason.py` L363 `build_reason()` 返回完整 reason（dim_hits/data_thresholds/history_analogy/human_text/compliance_footer），前端 `_labCustomDimsTableHTML/_labCustomHistoryHTML/_labCustomThresholdsHTML/_labCustomFooterHTML` 4 函数已抽 common.js 0改动可复用
- ETF 数据缺口：etf_daily 表只有 close 无 open/high/low，**ETF 不走 signals.compute() 主循环无6色买卖点信号**，H3/L2维度缺省
- 全市场 ETF 映射：`data/board_etf_map.json` 59 key->485 ETF code（按成交额降序）

**用户决策（已定）**：
1. **ETF范围 = 全市场485个**（C代表ETF或12国家队相关做标注提示区分）。需扩展 etf_daily 采集覆盖485个（现仅12个国家队）
2. **卖清单 = 用户输入持仓**（C）：增加交互让用户输入持有的ETF，系统对其评分给卖出建议。违背"开tab就看"轻量诉求但用户明确要
3. **手数 = 评分分档3/2/1/0**（A）：极佳3手/较好2手/一般1手/差0手不入清单（3手基准向下减档）
4. **权重 = ETF专属调权**（B）：提高 H7/L4 汪汪队权重（ETF国家队动作重要）+ 降低 H3/L2（ETF无6色信号），需调参测试

**方案设计**：
- 后端：① 扩展 etf_daily 采集到全市场485个（需 OHLC，现只有close，扩采集工作量M）② `scripts/export_alert_analyze.py` 加 ETF 配置生成 `alert_analyze_etf_{code}.json` ③ 新增 `scripts/export_etf_score_list.py` 聚合485 ETF评分排序输出 `etf_score_list.json`（buy_list/sell_list两数组，每项含etf_code/name/score/hands/reason_summary/is_national_team标注） ④ alert_match.py PREGEN_TARGETS 加485 ETF元组
- 前端：lab.js 加 aiscore 子 tab + `renderAIScoreListLab()`（~250行）：买清单（low_alert降序+high_alert<60过滤+手数映射）/ 卖清单（用户输入持仓->对该持仓ETF算high_alert排序）/ 理由弹窗（复用_labCustom*HTML）/ 国家队或代表ETF标注
- 评分调权：alert_score.py ETF分支提高 H7/L4 权重降低 H3/L2，需回测验证
- 数据流：后端 export 生成 JSON 静态化（update_all 收盘后跑），前端 fetch 渲染

**改动点**：
| 文件 | 改动 | 行数 |
|---|---|---|
| app/collector/（新增扩ETF采集） | etf_daily 扩到485个+加OHLC采集 | ~200 |
| app/alert_score.py | ETF专属调权 H7/L4↑ H3/L2↓ | ~30 |
| app/alert_match.py | PREGEN_TARGETS 加485 ETF | ~10 |
| scripts/export_alert_analyze.py | 配置485 ETF导出 | ~30 |
| scripts/export_etf_score_list.py | 新增聚合评分生成清单JSON | ~150 |
| scripts/update_all.sh | 加调用 | ~3 |
| static-site/lab.js | aiscore子tab+renderAIScoreListLab+卖清单持仓输入交互 | ~350 |
| static-site/style.css | 清单表格+手数badge+持仓输入样式 | ~100 |
| **合计** | | **~870行** |

**工作量**：2-3天（含扩采集+调权测试+前端持仓交互）。比 MVP（国家队12个+现成权重+卖点列表）大很多，因用户选全市场485+用户输入持仓+ETF专属调权。

**风险**：
1. 全市场485 ETF 采集扩容工作量大（需 OHLC，现 etf_daily 只有 close）+ akshare 限流风险
2. ETF 专属调权需回测验证（不能拍脑袋定权重，要跑历史数据看评分有效性）
3. 用户输入持仓交互复杂（输入ETF代码/名称->匹配->评分->卖出建议），违背静态化架构（但卖清单必须基于用户持仓）
4. 同指数多 ETF 同质化（510300/510310/159919都是hs300）-> 全市场更严重，需去重或按成交额差异化
5. ETF 无6色买卖点信号，评分维度比指数少2个（H3/L2缺省），调权后可能仍不如指数版精确
6. 数据时效 T+1（ETF数据收盘后才更新），盘中不能用

**实施顺序建议**：分两阶段
- 阶段1 MVP：先上国家队12个+现成权重+卖清单卖点信号列表（方案C+A+A+A，1-2天），验证评分模型+前端清单交互可用
- 阶段2 扩展：全市场485+ETF专属调权+用户输入持仓（用户选的方案，2-3天），在MVP验证后扩

**与 P1-新-A/B 关系**：同属"AI 评分/预警"主题，P1-新-A（盘中信号消失）+P1-新-B（pin策略问号）+P1-新-C（ETF清单）三个可串行实施，互不冲突（A改check_signals后端/B改signals.py+app.js/C改lab.js+新增脚本，不同文件）

---

## 🆕 2026-07-23 待办外5方向（用户感兴趣，已调研落档待排期，详见 NOTES §48 小节AZ）

> 用户问"待办外建议"，提了5方向都感兴趣，派2个调研 agent（前端3+后端2）只读摸现状给方案。**结论：5方向中 DB灾备已大部分实现，其余4方向待实施。** 收盘 deploy 完再开（盘中不改 app.js/build）。

### P2-新-A 数据可信度透明化 · 采集健康度小灯（前端方向1，~80行）
- **现状**：后端 `collect_health`（level=ok/warn/error + items）已导出 overview.json（export.py L361），但前端**采集时间旁没暴露小灯**（app.js L2465-2466 注释明说"留给后端日志不展示"）。KPI 灰态卡片只覆盖 9 个白名单指标（L3891-3895），其他 metric_id 的 error 不显示
- **方案**：采集时间旁（`_renderCollectTime` L2485）加🟢🟡🔴小灯，hover 弹失败源 metric_id+message。`fetchCollectTime` 传 `r.collect_health`，复用现有 data-tip hover 机制
- **风险**：① collect_health error 可能误报（export.py L382-394 已过滤陈旧误报但非100%）② 与"数据更新规则 modal"时效展示语义不同需文案区分（小灯=采集动作成败 / modal=数据到没到最新）
- **决策点**：① 小灯位置（采集时间旁 推荐）② warn 是否显示（推荐显示但弱化文案）③ 是否同步补全灰态卡片白名单

### P2-新-B 信号历史复盘展示（前端方向2，分2档）
- **现状**：`signal_stats.json` 已导出 static-site/data/（230KB，110品种×6信号×3窗口），但 app.js L745 `_aggregateSignalStats` **硬编码只取 `s["10d"]`**，5d/20d 数据浪费；L792 注释过期说"未导出"实际已导出
- **方案2a（简单，~30行，先做）**：信号 modal 分析概况从"10日单一窗口"扩"5d/10d/20d 三窗口对比"，让用户看短/中/长期表现。零风险（数据已有+渲染逻辑已有）
- **方案2b（复杂，~200行，后做）**：具体 pin 旁标"X天前buy_aux至今+3.2%"真复盘。查 `indices_sparkline[index_id]` close 序列算涨跌。难点：sparkline 只含宽基，行业/全球指数 close 序列需另查 industry.json/global-all.json
- **风险**：① 2b 数据覆盖度（sparkline 只宽基）② 2b 真实性 vs signal_stats 聚合语义不同（用户预期真复盘，signal_stats 是统计聚合）③ 样本数 n<5 误导需标注
- **决策点**：① 2a vs 2b vs 都做（推荐先2a后2b）② 2b 展示位置（pin旁徽章 推荐 vs modal内）

### P2-新-C 移动端 PWA（前端方向3，~150行+2 icon）
- **现状**：完全空白。index.html 无 manifest/SW/theme-color（grep 计数0），无 icon-192/512.png，无 sw.js。有利条件：纯静态站 SW 友好 + 已有4套皮肤 + favicon.svg 矢量可生成 icon + _headers 已配 CSP 无冲突
- **方案三件套**：
  1. `manifest.json`（name/short_name/theme_color=#d4af37 redgold/icons/start_url）
  2. `sw.js` 缓存分层：App Shell `CacheFirst` + 数据JSON `stale-while-revalidate`（盘中3分钟刷，SWR最优）+ intraday_snapshot `NetworkFirst` + 第三方不缓存。版本管理 `CACHE_VERSION` bump 清旧
  3. index.html 加 `<link rel="manifest">` + meta + SW 注册脚本
- **风险**：① SW 缓存策略误伤盘中数据（必须 SWR 不能 CacheFirst）② SW 更新滞后需 skipWaiting+clients.claim 但有 mid-session 切版本风险（推荐显式提示刷新）③ icon 生成（favicon.svg 35字节极简，转512可能模糊，需重做或用 og.png 裁剪）④ iOS standalone 不支持 push（本方案没用到无影响）
- **决策点**：① 缓存策略（推荐 App Shell CacheFirst + 数据 SWR + intraday NetworkFirst）② icon 来源（复用favicon vs 重做高清 vs og.png裁剪）③ theme_color（固定redgold 推荐 vs 跟随皮肤动态切换复杂）④ 是否做完整 offline（推荐不做，只缓存 App Shell+上次快照）

### P2-新-D DB 灾备补强（后端方向3，~70行但大部分已实现）
- **意外发现**：任务描述说"缺DB备份"**实际已完整实现**：
  - `backup_db.sh` L48 `src.backup(dst)` sqlite3 在线热备（WAL一致快照不锁库）+ 14天本地滚动 + 失败 notify 告警
  - `upload_r2.py upload-db` 三层备份（`backup/` 日30天 + `weekly/` 周28天 + `monthly/` 月365天）+ 私有桶 `signal-backup` + gzip（102MB→30MB）
  - `verify_backup.sh` 每日恢复演练（下载+integrity_check+COUNT对比）
  - `update_all.sh` L202 串接，日志确认最近3天都在跑
- **只剩补强**：① 恢复操作文档（脚本支持 `download-db` 但无流程文档）② 可选独立 plist 18:30 双保险（主控判断：plist 双保险价值不大，update_all 串接已够稳+有告警，**只做恢复文档即可**）
- **决策点**：① DB备份触发方式（A现状update_all串接 / B独立plist / C双保险推荐但主控倾向只A+文档）② 异地备份层无需再上云盘（R2三层+verify已够）

### P2-新-E 告警渠道扩展 Telegram bot（后端方向4，~70行）
- **现状**：纯邮件。notify.py `send()` 单一 SMTP，无即时渠道。check_signals.py L574-598 **重复实现 `send_email()`** 25行（与 notify.py 几乎一样，不走 notify.py）。fade-detect 红警纯邮件触达
- **方案**：
  1. `config/telegram.json`（gitignore，bot_token/chat_id/api_base，模板 telegram.json.example）
  2. notify.py 加 `send_telegram(text)`（POST api.telegram.org/bot{token}/sendMessage）+ `send()` 改多渠道分发（邮件+Telegram并行，任一成功即OK，8处调用方零改动自动获益）
  3. 顺带删 check_signals.py 重复 `send_email()` 改调 notify.send（fade-detect 红警自动走多渠道）
  4. CF Workers 反代解决国内可达（复用 ss.fx8.store 基础设施）
- **风险**：① Telegram 国内可达需 CF Workers 反代 ② bot token 隐私 gitignore ③ 消息频率限制（intraday 30分钟一次远低于限制OK）④ check_signals 重构动 fade-detect 邮件链路需 --dry-run 测试
- **决策点**：① 渠道选型（A只Telegram推荐 / B只企业微信webhook国内直连但内容简化4096字节限 / C都加）② notify.py 多渠道架构（改A `send()` 内部分发推荐 调用方零改动 / 改B独立函数调用方改8处）

### 5方向排期建议
- **改动量**：A(80行) / B-2a(30行)+2b(200行) / C(150行) / D(只文档) / E(70行)
- **价值排序（主控推荐）**：D(只补文档,0成本闭环) > B-2a(30行快见效) > A(数据诚信) > E(即时告警) > C(PWA体验) > B-2b(真复盘,大工作量)
- **并行性**：A/B/C改 app.js（需build,串行）+ D/E改 scripts（不碰build,可任何时候并行）。D/E 可先做不撞 deploy
- **等用户拍板排期后实施**
