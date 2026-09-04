# 信号凯利全信号卡停滞根因 + 每日快照演进方案(2026-09-04)

> 双任务:任务A=根因排查(全信号 A 交易记录停在 8/31),任务B=每日快照+演进+告警方案。
> 只读调研,未改任何业务代码。测试基准注意:结论不依赖回测基准口径,是数据链路/调度问题。

## 一、任务A:交易记录停在 8/31 的确定性断链结论

### 结论一句话
**信号源正常(signal_daily 9/1/9/2/9/3 都有 buy 系信号),断在价格库 accum_nav 未补齐 → 回测 `_batch_load_etf_prices` SQL 过滤 `accum_nav IS NOT NULL` 把 9/3 全部行滤掉 → 9/3 的 15 条买入信号全部跳过;9/2 也因 3 条无 ETF 映射 + 1 条(us_dji→513400)的 accum_nav NULL 全跳;9/1 因 cgb_idx 无 ETF 映射全跳。结果:9/1~9/4 无任何成交,全象限最大 signal_date=20260831。**

### 断链链条(证据逐点)

**① 信号源正常**:主库 `/Users/linhuichen/code/trade/data/sentiment.db` signal_daily:9/1=1 条 buy、9/2=4 条、9/3=15 条(探针脚本输出),MAX(date)=20260903。信号不是没产生。

**② 价格库(回测读取端)**:回测 `_get_etf_db_path`(signal_kelly_backtest.py L449)优先读 `/Users/linhuichen/code/trade-data/data/etf_national_team.db`(主库,健康);根目录 `data/etf_national_team.db` 已损坏(malformed)但回测不读它。
- 9/2:1487 行,**5 行 accum_nav NULL**(513100 纳指ETF国泰/513400 道琼斯ETF鹏华/513650 标普500ETF南方/513730 东南亚科技/159509 纳指科技景顺)
- 9/3:**1488 行 accum_nav 全 NULL**(open/close 有值,即 OHLC 已入库但累计净值没补)
- 9/4:仅 12 行(未完整采集,当日盘中)

**③ 断链点确认(探针 probe_sigkelly_sep_signal.py 模拟 9 月信号分类)**:
- 9/1 cgb_idx buy_special → 无 ETF 映射 → 跳
- 9/2 hk_cesg10/hk_cshklre/hk_hsmpi 无 ETF 映射 + us_dji→513400 但 513400 9/2 accum_nav NULL → 全跳
- 9/3 12 条(csi_*/sw_*/sz_div)有 ETF 映射但 9/3 行 accum_nav 全 NULL → 回测 `_batch_load_etf_prices`(L457-486)SQL `AND accum_nav IS NOT NULL`(L475-477)过滤掉 9/3 全部价格行 → 信号日取不到价格 → **断链3,全部跳过**;另 3 条无 ETF 映射
- 结论:trades 全象限最大 signal_date=20260831,9/1-9/4 零成交。

**④ 为什么 9/3 的 accum_nav 没补(调度时序根因)**:
- 9/3 20:07 主槽 `etf_national_team_backfill.sh`:daily 完成 ohlc=7420(近6交易日窗口,不含当日 9/3),accum-nav 只发现 85 行缺失补 68 行 → **9/3 行当时还没入库**
- 9/3 21:30 兜底槽**日志不存在**(20:07 deploy 拖到 21:35,锁占用/超时跳过)→ 当天没有第二次补 accum-nav 的机会
- **9/4 02:00 backfill_metrics 槽**(index_backfill.main L1058-1064):`pipeline_daily()` 把 9/3 的 OHLC 行写入主库(02:04:16 开始,02:07 完成 ohlc=7427),**但该槽只调 pipeline_daily + export_json_files,不调 `update_accum_nav`** → 9/3 行 accum_nav 保持 NULL
- 02:17 回测(export.py L1207 subprocess signal_kelly_backtest.py)读主库 → 9/3 行被过滤 → 9/3 信号全跳
- **根因**:`update_accum_nav` 只在 `etf_national_team_backfill.sh`(20:07/21:30 槽)调用;而 9/3 行实际是 02:00 backfill 槽补采写入的,该槽不跑 accum-nav → 隔日补采的行永远缺 accum_nav,直到下一个 20:07 主槽才补。

### 修复建议(供主控派 implementer)
1. **立即恢复数据**:跑 `python -m app.collector.etf_national_team accum-nav --lookback 30`(在主库 trade-data 环境,补 9/3 的 1488 行),然后重跑 `scripts/signal_kelly_backtest.py --output static-site/data/signal_kelly_backtest.json` + deploy 三步(§22)。
2. **根治**:index_backfill.main 的 etf 补采分支(L1058-1064)在 `pipeline_daily()` 后追加 `update_accum_nav` 调用(02:00/16:35/21:00 槽都能覆盖),或把 `update_accum_nav` 移入 pipeline_daily 内部(幂等)。
3. **监控补盲**:`check_data_integrity.py` 或 monitor_72h 加「signal_daily 最新信号日 vs etf_daily 最新 accum_nav 日」滞后告警(>1 交易日 SEVERE),把本类断链变成自动可见。
4. 附带:**根目录 `data/etf_national_team.db` 损坏**(PRAGMA integrity_check 大量 invalid page),回测不读它所以本次无关,但若其他组件读到会失败,建议定位来源(deploy rsync 副本?)后修复或删除。

## 二、任务B:信号凯利全信号卡每日快照+演进+告警方案

### 2.1 快照存什么(对齐 trades/backtest 产物字段)
每日(回测产物生成后)存一份快照 JSON,内容:
- `date`:交易日期(YYYYMMDD)
- `generated_at`:产物生成时间
- `version`:前端版本串(发版日豁免判定用,从 `static-site/index.html ?v=` 读)
- `max_signal_date`:trades 全象限最大 signal_date(本任务直接观测的"停滞信号")
- `quadrants`:16 象限 × 5 周期(y1/y3/y5/y10/all)× 10 模式(A/B/C/D/E/F/J/G/H/I)的**关键指标子集**:
  - `n`(样本数)/`win_rate`/`pl_ratio`/`mean_return`/`total_return`/`avg_hold_days`/`kelly_f`/`half_kelly`/`kelly_tier`(对齐 signal_kelly_backtest.json 现有字段)
- `recent_trades`:最近 10 笔成交摘要(signal_date/buy_date/etf_code/index_id/profit/return_pct),供人工快速确认演进真实性
- 存储体积:quadrants 16×5×10=800 个指标对象,≈50-100KB/日,一年 ≈20MB,可接受(R2 按日归档,同 `daily_brief_history` 模式)

### 2.2 存储格式(按日追加 + 索引)
- 目录:`data/signal_kelly_snapshots/YYYYMMDD.json`(按日一个文件,避免单文件无限涨)
- 索引:`data/signal_kelly_snapshots/index.json` = 按日聚合的**迷你快照**(仅 max_signal_date + 每象限 A 模式 total_return 等少量标量),供演进曲线/告警快速读,不读全量
- 演进读取方:告警脚本扫 index.json 序列;展示位读 index.json 画曲线
- 生成脚本:`scripts/signal_kelly_snapshot.py`(建议),挂到回测产物生成后(export.py 内 signal_kelly_backtest.py subprocess 成功后 或 backfill_metrics 槽尾部)

### 2.3 展示位(权衡)
- **主展示位=lab 凯利区**「全信号卡」上方加一行「演进」入口(link 到 index.json 驱动的迷你曲线弹窗:max_signal_date / A 模式 total_return 近 30/90 日曲线)。理由:用户看的就是凯利区,且 lab 已有 overfit 监控图先例。
- **备选=首页 AI 监控卡**:已有近期命中率曲线区,可加「凯利回测最新交易日」角标(数据已就绪,前端小改)。
- **不做**=单独新 tab(成本高,用户未要求)。
- 权衡说明:演进曲线用**只读小 JSON(index.json)**渲染,不把全量快照挂前端。

### 2.4 异常阈值口径(⚠️ 防前视 §5.1⑥)
**硬约束:阈值基准绝不用全期分位,必须 expanding/滚动窗口,且快照是"历史事实"不预判未来。**
- **基准**=滚动窗口(默认近 60 个交易日,可配):对每个 (象限,周期,模式) 的 `total_return`,算滚动窗内 mean/std。
- **告警条件(两档)**:
  - 突变档(SEVERE):当日 `total_return` 相对滚动窗均值偏离 > `k×std`(k 默认 3.0),或单日 Δ > 20pp(可配)
  - 停滞档(WARN):`max_signal_date` 落后最新交易日 ≥2 个交易日(直接命中任务A类事故)
- **区分三类演进,防误报**:
  - 正常演进=缓慢渐变(Δ < 阈值)→ 只记录不告警
  - 真异常=单日大跳变且次日无回补(如 Δ > 阈值且隔日不回归)→ 告警
  - 口径切换(发版)=`version` 变化当日 → 告警文案标注「发版日,豁免跳变告警」或仅记录不告警(可配)
- **防前视机检**:阈值参数(窗口/std 倍数/Δ)写死在脚本常量区并注释「滚动窗基准,非全期分位」;不做任何"用未来数据反推阈值"逻辑。

### 2.5 告警通道(§23.10 飞书+邮件内容一致)
- 复用 `scripts/notify.py`(`send` 同时发邮件+飞书,内容同一 body)。
- 告警 body 必含:①现象(哪个象限/周期/模式、旧值→新值)②判定档位(突变/停滞)③发版豁免标记(若 version 变了)④数据截止日 ⑤影响面提示(「9/1-9/4 零成交=价格库 accum_nav 未补」这类可操作线索)。
- 防抖:notify.py dedup-key(如 `sigkelly_snapshot_jump_<象限>_<周期>_<模式>`)+ dedup-window 24h,同一突变不重复轰炸。

### 2.6 阈值门控防误报
- **样本门**:`n < 20` 的模式不参与跳变告警(小样本噪声大)。
- **趋势门**:连续 2 个交易日同方向超阈值才告警(单日噪声不告警),但停滞档不设趋势门(缺失即告警)。
- **发版门**:version 变化当日豁免跳变告警(已标注)。
- **回测失败门**:signal_kelly_backtest 产物缺 generated_at 或 max_signal_date 倒退(比昨日小)→ SEVERE(产物坏了,不是演进)。

### 2.7 落地清单(供派 implementer)
1. `scripts/signal_kelly_snapshot.py`:读 `signal_kelly_backtest.json` + `signal_kelly_trades.json` → 写 `data/signal_kelly_snapshots/{date}.json` + 更新 `index.json`;滚动窗阈值+三类判定+notify 告警;幂等(同日重跑覆盖)。
2. 挂载:export.py L1207 signal_kelly_backtest subprocess 成功后追加 `subprocess.run([snapshot.py])`(失败不阻塞 export,同回测容忍度);或 backfill_metrics.sh 尾部。
3. `check_data_integrity.py` 加 `signal_kelly_snapshots` 结构校验(当日文件存在+index 最新日=预期交易日,FAIL 阻断)。
4. lab 凯利区「演进」入口(index.json 迷你曲线,只读小 JSON)。
5. 本报告末尾「## 复现」段随实施脚本更新。

## 复现

- **根因数据**:主库 `/Users/linhuichen/code/trade-data/data/etf_national_team.db`;`sqlite3` 查 `etf_daily WHERE date='20260903' AND accum_nav IS NULL` 得 1488 行(全 NULL),`date='20260902' AND accum_nav IS NULL` 得 5 行(含 513400)。信号源 `data/sentiment.db` `signal_daily WHERE date>='20260901' AND signal IN ('buy','buy_aux','buy_special','buy_backup')` 得 9/1=1/9/2=4/9/3=15。
- **探针脚本**:`docs/kelly/analysis/scripts/probe_sigkelly_sep_signal.py`(复用 skb 加载函数,读主库+board_etf_map 模拟 9 月信号分类,输出断链点明细)。重跑:`python3 docs/kelly/analysis/scripts/probe_sigkelly_sep_signal.py`。
- **调度证据**:`/Users/linhuichen/code/trade-data/data/logs/etf_national_team_backfill_20260903_2007.log`(daily ohlc=7420 + accum-nav 缺失 85 行)与 `backfill_20260904_0200.log`(02:04 etf daily → 02:07 完成 → 02:17 回测产物)。`etf_national_team_backfill_20260903_2130.log` 不存在(21:30 兜底槽未跑)。
- **回测过滤点**:`scripts/signal_kelly_backtest.py` L449 `_get_etf_db_path`(优先 trade-data 主库)、L457-486 `_batch_load_etf_prices` SQL L475-477 `AND accum_nav IS NOT NULL`、L1086-1095 信号 SQL。
- **数据截止**:2026-09-04(今日);快照方案为待实施设计稿,无历史快照数据。
- **口径一句话**:回测仅买系信号入样(buy/buy_aux/buy_special/buy_backup),买入价=信号日 accum_nav×(次日 open/当日 close),`KELLY_BUY_NEXTDAY=1`;信号日价格行缺 accum_nav 即跳过该信号。

## 实施(2026-09-04, P0 断链修复 + 快照演进告警落地)

> 由 implementer agent 按本报告方案实施完成(任务 A-I)。以下为落地明细, 含复现段。

### A 补数据
- `python -m app.collector.etf_national_team accum-nav --lookback 30`(主库 trade-data 环境, 复用 17:22 已有进程)补齐 9/2 全部 + 9/3 部分 accum_nav。验证:9/3 accum_nav NULL 由全量 1488 行降至 34 行;9/2 由 5 行降至 0 行(数据源 fund_open_fund_info_em 差 9/3 的 34 只 QDII/跨境 ETF, 见**遗留**)。

### B 重跑回测
- `python scripts/signal_kelly_backtest.py --output static-site/data/signal_kelly_backtest.json` 完成(generated_at=2026-09-04 17:45)。**时序卡点**:当前 max_signal_date=20260831, 因 9/4 全量 OHLC+accum_nav 待今晚 20:07 主槽入库(当日仅 12 行盘中); 9/1-9/4 成交须等 20:07 后重跑才能推进到 20260904(见**遗留**)。

### C 根治(commit: 见 feat 分支)
- `app/collector/index_backfill.py` etf 补采分支(L1058-1088)在 `pipeline_daily()` + `export_json_files()` 后追加 `pipeline_accum_nav(lookback_days=30)`(幂等, 无缺口秒回), 覆盖 02:00/16:35/21:00 全部 backfill 槽, 根治「02:00 补采写入的隔日行 accum_nav 永远 NULL」。

### D 监控补盲
- `scripts/check_data_integrity.py` 新增 `check_signal_accum_nav_lag()`(L829-881): signal_daily 最新 buy 系信号日 vs etf_daily 最新 accum_nav 日, 交易历滞后 >1 交易日 = FAIL(SEVERE), 1 交易日(正常盘后时序)=OK。已接入 run_all_checks(L1595 后)。当前数据验证: 信号日 20260904 vs accum_nav 日 20260903 = 1 交易日 OK。

### E 附带修复
- 根目录 `data/etf_national_team.db` 损坏(malformed): 已用主库健康副本覆盖(`cp trade-data/data/etf_national_team.db data/`), PRAGMA integrity_check 通过, 且**不 touch 主库**。

### F 快照+演进+告警
- 新增 `scripts/signal_kelly_snapshot.py`: 读 backtest+trades → 写 `static-site/data/signal_kelly_snapshots/{date}.json`(16 象限×5 周期×10 模式 key metric 子集 + max_signal_date + 最近 10 笔成交 + version) + `index.json`(迷你演进序列); `--check` 模式扫 index 做停滞(>1 交易日 WARN/SEVERE)与突变(滚动窗 60 交易日 mean±3std / 单日Δ>20pp 且 n≥20 且连 2 日同向; 防前视=只用 t 之前快照)告警, 走 notify.py 邮件+飞书同 body(dedup 24h); 发版日(version 变化)豁免突变告警; 回测失败门(max_signal_date 倒退 SEVERE)。
- 挂载: `static-site/export.py` L1205-1243 backtest 成功分支后追加 `subprocess.run(snapshot.py --data-dir DATA_DIR)`(失败不阻塞 export); `scripts/backfill_metrics.sh` 尾部追加 `snapshot.py --check`(02:00/16:35/21:00 槽)。首份快照已生成(20260904.json, max_signal_date=20260831, 与当前数据一致)。
- 展示位(lab 凯利区「演进」入口): `static-site/lab.js` bar-head 新增「📈 演进」按钮 + `_labKellyEvoOpen/_labKellyEvoModalHTML/_labKellyEvoSVG`(读 index.json 迷你曲线, 纯 SVG 轻量, 复用 lab-signal-modal 容器); `static-site/lab.css` 增配套样式。首页 AI 监控卡角标(备选展示位)未做——lab 为主展示位(方案 2.3 主+备)。

### G 落档
- 本报告「## 实施」段及以下「## 复现(实施版)」; 探针脚本 `docs/kelly/analysis/scripts/probe_sigkelly_sep_signal.py` 已在同目录留档(§23.5)。
- README 功能亮点段补「信号凯利回测演进」描述(§23.1)。

### H 验证(剩余项, 见**遗留**)
- 同构对账机检(§5.4⑦): 快照脚本读 backtest.quadrants 结构与 lab 凯利区渲染同源(脚本已验证结构=16×5×10, 前端弹窗读 index.json.days). **待今晚 20:07 数据入库后重跑回测+快照, 验证 max_signal_date 推进到 20260904 + 9/1-9/4 有成交记录**。

## 复现(实施版)

- **快照脚本**: `python scripts/signal_kelly_snapshot.py`(生成当日快照+更新 index); 告警检测: `python scripts/signal_kelly_snapshot.py --check`(挂 backfill 02:00/16:35/21:00)。输入依赖: static-site/data/signal_kelly_backtest.json + signal_kelly_trades.json; 输出: static-site/data/signal_kelly_snapshots/。
- **监控校验**: `python3 scripts/check_data_integrity.py --strict`(含 check_signal_accum_nav_lag)。
- **断链探针**: `python3 docs/kelly/analysis/scripts/probe_sigkelly_sep_signal.py`(复用 skb 函数模拟 9 月信号分类, 读主库)。
- **数据截止**: 2026-09-04(回测产物 17:45 生成; 9/4 全量数据待 20:07 主槽); 快照初始第 1 份(20260904)。
- **口径一句话**: 快照 key metric = {n, win_rate, pl_ratio, mean_return, total_return, annualized_return}; max_signal_date = 全成交 signal_date 最大值; 停滞告警阈值=落后 ≥2 交易日; 突变告警=滚动 60 快照日 mean±3.0std 或单日Δ>20pp 且 n≥20 且连 2 日同向。

## 遗留(待今晚 20:07 数据入库后完成)
1. **B/H**: 20:07 主槽全量 OHLC+accum_nav 入库后, 重跑 `python scripts/signal_kelly_backtest.py`(或等今晚主控 main-merge.sh 统一 export), 验证: ①全象限 max_signal_date=20260904 ②9/1-9/4 有成交 ③快照 index 第二份快照 max_signal_date 推进。当前(max_signal_date=20260831)为本时序的正常中间态, 不是代码缺陷。
2. 34 只 QDII/跨境 ETF 9/3 accum_nav 差(数据源 fund_open_fund_info_em 未发布), 若 20:07 后仍未补, 9/3 中这些 ETF 的信号日可能仍跳(影响面 34/1488≈2.3% 价格行), 持续观察。
