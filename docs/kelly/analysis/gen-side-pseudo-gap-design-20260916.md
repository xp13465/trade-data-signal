# 生成器侧伪跳空剔除校验 设计报告(2026-09-16)

> 调研任务:用户已拍板「补上生成器侧真的伪跳空校验(用次日开盘价判断,>20% 剔除)」。
> 本报告 = 完整链路证据 + 方案穷举对比 + 推荐方案实施步骤。
> 测试基准 = current baseline(v1.1.7 tag@384005e222,S06 动态 a9/new15 按日切;memory `test-baseline-v112-anchor`)。本改动不触碰回测基准(见 §4)。

## 0. 结论摘要

- **推荐方案 A(A1+A2 两段合一)**:①生成器内把死代码改成真口径校验,对「次日 open 已入库」的历史回填段立即生效(etf_daily 取次日 open);②新增 launchd 任务 `com.trade.nextday-gap-check` 在 T+1 日 9:26(竞价结束后开盘价已定)对当日执行计划做二次剔除(akshare 实时开盘价)。
- **不推荐方案 B**(生成器整体移到 T+1 开盘后):会丢失 21:05「明日计划」预告通知(PRD 阶段一核心交付),且 T+1 重跑=方案 A2 的超集。
- **不需要发中间版本**(§5.4⑥):不动回测默认组合/算法/数字;回测侧 PSEUDO_GAP_EXCLUDE 自 v1.1.4 起已是内置口径。
- **需要 §21 公示同步**:README L72(现写的是旧死代码口径)+ 生成器 docstring + 前端 lab.js 视图(可选角标,状态机已支持 skipped)。

## 1. 现状证据(文件:行号)

### 1.1 回测侧真逻辑(活代码,本次不动)
- `scripts/signal_kelly_backtest.py` L77-78:`PSEUDO_GAP_EXCLUDE = 0.20`(注释:份额折算伪跳空阈值)。
- L674-687(买入定价 `_price_entry` 类函数内):KELLY_BUY_NEXTDAY 口径下
  - L680 `sig_close = close_map[etf][signal_date]`(信号日原始收盘)
  - L681 `nxt_open = open_map[etf][下一交易日]`(次日原始开盘)
  - L682-683 缺任一价 → `return None`(缺价=剔除,同向)
  - L684 `gap = nxt_open / sig_close - 1.0`;L685-686 `abs(gap) > 0.20` → `return None` 整笔剔除
- 数据源:`_batch_load_etf_prices` L495-543,单 SQL 读 etf_daily 原始 open/close/accum_nav;盘中档 `compute_intraday` L1614-1642 用 akshare `fund_etf_spot_em` 注入真实开盘价(`_fetch_intraday_open_prices` L554-586,9:40 已实测可得:516660=0.937/510300=4.638/159920=1.483,数据日期 2026-09-08)。
- 命中频率实证(`docs/kelly/position/kelly-nextday-open-backtest.md` L52-54/L272):全历史仅 2 笔 —— 512560 军工ETF 2021-11-15(close 1.642→open 0.854,-48%,2:1 拆分)、159739;不剔除会虚增 +17,605 元。罕见但必须防。

### 1.2 生成器侧死代码(根因)
- `scripts/nextday_plan_generator.py` L499-511(`_build_plan_for_day` 内):
  - L500 `last_date, sig_close = _prev_close(db_path, etf_code, T)` ← T 日收盘
  - L502 `_, prev_close = _prev_close(db_path, etf_code, T)` ← **同参重复调用**
  - L507-511 `gap = prev_close / sig_close - 1.0` ≡ 0 → 剔除永不触发(死代码)。
- 根因链:KELLY_BUY_NEXTDAY 口径下,生成时点(T 日 20:55)次日开盘价尚不存在;PRD 设计稿把「伪跳空剔除」降级写成「prev_close vs 信号日收盘 ±20%」近似(`docs/auto-trade/nextday-plan-backend-implement-20260910.md` L34、PRD L143),实现时两次同参连近似都没生效。
- docstring L30-31/L48 声称「伪跳空剔除同款」,与实际行为不符。

### 1.3 生成器完整链路(调研维度 1)
- 文件:`scripts/nextday_plan_generator.py`(主逻辑)+ `scripts/nextday_plan.sh`(launchd 包装,交易日闸门+severe 兜底)。
- 触发:launchd `com.trade.nextday-plan`,交易日 20:55(`~/Library/LaunchAgents/com.trade.nextday-plan.plist` StartCalendarInterval Weekday 1-5 20:55;时点论证在 nextday_plan.sh L13-19:20:35 s06 快照定稿后、21:00 backfill-evening 前空档)。
- 产物(data/nextday_plan.json + 两树 static-site/data/nextday_plan.json + auto_trade_steps.json + R2 upload-data-files + notify 邮件/飞书 follow 群):generator L680-777。
- 主链:`_build_plan_for_day` L435-522;回填段 `_backfill_historical_groups` L525-560(复用同一函数);数据就绪 gate `_plan_stale_codes` L617-624。
- 当前线上实际产物:`static-site/data/nextday_plan.json` = `{date:20260911, plan:[{etf_code:513260, prev_close:1.048, amount:10000, signal:buy_aux, buy_date:20260914}]}`;auto_trade_steps 32 行。

### 1.4 次日买入执行链路(调研维度 2)
- Phase0 干跑(当前,PRD §8/§9):无真实下单,auto_trade_steps.json 行为级状态机(seq1 9:15 挂单/seq2 9:25 竞价判定/seq3 14:55 兜底/seq5 D+10 卖出)由前端 lab.js 按时钟推进**纯展示**,干跑不回写执行状态(README L72)。
- 前端消费:lab.js L13956-13957 `_AT_URL_PLAN="./data/nextday_plan.json"` `_AT_URL_STEPS="./data/auto_trade_steps.json"`;状态机 L13948-13949 `_AT_STATUS_CLS` 已含 `skipped:"gry"`(已跳过灰)——**剔除状态前端渲染基础已具备**。
- Phase1 人工跟单 / Phase2 easytrader 自动(PRD L114:9:15 挂昨收限价单→9:25 竞价判定「O≤昨收按 O 成交」→14:55 尾盘兜底)。执行价=竞价开盘价 O(低开)/昨收(回落)/尾盘市价(兜底)。

### 1.5 次日开盘价数据源(调研维度 3)
- **源 1 etf_daily.open 列**(表结构 PRAGMA:date/etf_code/etf_name/close/amount/fund_share/share_change/share_change_pct/open/high/low/accum_nav):T+1 日行要等 T+1 日 20:07 etf_national_team 采集才入库(`update_all.sh` L181-182 注释:#38 根因,17:50 跑太早 OHLC 未补完,故挪 20:07)。→ 对「当日计划」太晚;**对「历史回填段」完全可用**(回填窗口最近 10 交易日,其次日 open 早已入库;实测 513080 20260911 行 open=1.753 在库)。
- **源 2 akshare fund_etf_spot_em「开盘价」列**:盘中实时;9:40 已实证(回测盘中档);9:25 集合竞价结束后开盘价即定,9:26 理论可得但**未实测**(诚实标注,设计加就绪闸+重试)。
- 时间锚点:9:25 竞价结束开盘价确定;9:40 kelly_intraday_rerun 用同源已成功;9:25/9:35/9:45 intraday-snapshot 每 10 分钟轮次(plist 实证)。

## 2. 方案穷举对比(调研维度 4)

### 方案 A(推荐):生成器内历史段真校验 + T+1 9:26 二次剔除
**A1(生成器内,20:55,改 L499-511)**:
- 校验口径改为真口径:`gap = etf_daily[T+1 日].open / etf_daily[T 日].close - 1`,|gap|>0.20 → 剔除。
- 分两支:T 的历史回填段(其次日 open 已在 etf_daily)→ 真校验立即生效;T=今日(次日未开盘)→ 跳过(留 A2 兜底)。当日跳过≠回测「缺价剔除」——当日缺价是「还没开盘」不是「无数据」,语义不同,注释写清。
- 非停牌校验 ①(prev_close>0)保留不动。

**A2(新增 launchd,交易日 9:26)**:
- 新脚本 `scripts/nextday_gap_check.py`:读 auto_trade_steps.json 中 date==today 的买入行(及 nextday_plan.json buy_date==today 的条目)→ akshare 拉计划内 ETF 开盘价(复用回测 `_fetch_intraday_open_prices` 同款实现/或 import)→ `gap = today_open / signal_date_close - 1`(|gap|>0.20 剔除)。
- 剔除形态:steps 对应行 status=skipped + status_text「伪跳空剔除(|开盘/信号日收盘-1|=xx%)」;nextday_plan.json 条目加 `gap_excluded:true`;R2 上传 + purge + notify(邮件+飞书)。
- 数据就绪闸:开盘价取不到 → 9:31 重试一次 → 仍失败 → severe 告警 + 行标记「伪跳空校验未完成(待人工)」(干跑阶段);Phase2 接执行器时复用同一判定函数。
- 时点:9:26 与 intraday-snapshot 9:25 轮次错开 1 分钟(该任务秒级);与 9:40 kelly rerun / 9:45 snapshot 不冲突。plist 依 §14 新注册,Weekday 1-5 + 交易日闸门。
- 幂等:执行日行已有 gap 标记则跳过;RunAtLoad=false 防重启重复。

**影响面/改动量**:回测零改动;生成器一个函数内分支改造;新增 1 脚本+1 plist;前端 lab.js 可选加角标(skipped 渲染已支持);README 公示改一段。改动量小~中。

### 方案 B:生成器整体移到 T+1 开盘后
- 直接后果:丢失 T 日 21:05「明日计划」预告通知(PRD 阶段一核心交付=计划先行、人工按表跟单,用户前一晚要知道明日买什么),前端「明日计划」展示位失去预告语义。
- 若要保留预告,只能 20:55 照跑+T+1 开盘后重跑定稿——即退化为方案 A2,且多一次全量重算(信号链/S06/降亏全部重演,增量成本>新增轻量 gap-check)。
- **不推荐**。

### 方案 C:9:15-9:20 竞价匹配价预判撤单(Phase2 执行器增强,非替代)
- 集合竞价 9:15-9:20 可撤单,份额拆分日一开板匹配价即大幅偏离,可预判剔除。
- 未实证项:akshare 竞价阶段「最新价/匹配价」可靠性(开盘价列 9:25 前大概率空)——Phase2 设计时再实测。
- 市场机制附注:拆分日昨收限价单大概率因涨跌停区间调整被交易所拒单(有天然保护),但**不能依赖**。
- 定位:Phase2 执行器(9:15 挂单防成交)的配套,Phase0 不需要,本报告只登记不实施。

### 方案对比表
| 维度 | A(A1+A2) | B(整体后移) | C(竞价预判,仅 Phase2) |
|---|---|---|---|
| 预告通知保留 | ✓ | ✗(或退化为 A2) | ✓(叠加) |
| 剔除时点 vs 成交 | 9:26 判定,干跑无成交;Phase2 挂单前同函数接入 | 9:25 后生成=执行后 | 9:20 前撤单 |
| 数据可得性 | 历史段已实证;9:26 未实证(有闸) | 同 A2 | 未实证 |
| 与回测口径对齐 | ✓(同 gap 公式) | ✓ | ✓ |
| 改动量 | 小~中 | 中(移时点破坏产品语义) | 小(未来) |

## 3. 回测侧 vs 生成器侧口径一致性(调研维度 5)
- 逐字对齐:`gap = nxt_open / sig_close - 1.0`,`abs(gap) > 0.20` 剔除 —— 与 backtest L684-686 完全同式;阈值常量从 generator `PSEUDO_GAP`(L82)复用或集中定义(§22 代码内常量登记点精神:backtest L78 / generator L82 / 新 gap-check 共 3 副本,建议新脚本 import,防漂移)。
- 分母=信号日 etf_daily 原始 close;分子=次日原始开盘价。akshare 实时开盘价 vs etf_daily 收盘后 open 可能有微小源差(盘中档与 17:50 全量版本来就是两套产物),gap-check 用 akshare(执行时点唯一可得),与回测盘中档同源;可留 20:07 后 etf_daily 复核对账(可选,Phase2 时定)。
- 防前视(§5.1⑥):gap-check 在 T+1 9:26 用「已产生的开盘价」判定,无前视;A1 回填段重演历史天然无前视;信号日收盘 17:50 已定稿(20:55 生成时无未来数据)。
- 缺价语义:回测缺 nxt_open → return None(剔);A2 缺开盘价 → 告警+标记待人工(干跑);Phase2 挂单前置判定缺价 → 不挂单(同向),语义对齐留 Phase2 定稿。

## 4. 版本升级判断(调研维度 6,§5.4⑥)
- 伪跳空剔除 = **数据质量处理**(回测报告 kelly-nextday-open-backtest.md §1.4 定性),不是「AI 推荐/降亏过滤」默认组合,也不动 K=1/BUY_AMOUNT/S06 基座/买入口径默认值。
- 回测侧逻辑与数字零变化 → **不需要发中间版本,不需要更新基准定义**(memory `test-baseline-v112-anchor` 不动)。
- 但改动触及「次日买入计划」已上线功能(README L72 已公示)的生成逻辑与产物字段 → 按 §23.7 冻结契约需用户确认;用户已拍板选项 B(补真校验),即已确认。
- 18 处键集登记点(AI 宏键集 a9/new14 等,audit 文档 v115-new14-baseline-alignment-audit.md):与本改动无关,不动。

## 5. 前端公示(调研维度 7,§21)
- **README L72 必须同步改**:现文案「再经 ±20% 伪跳空剔除双校验」描述的是死代码旧口径,应改为「次日开盘 vs 信号日收盘 ±20% 真校验(20:55 生成时历史段可算即算;当日计划由 9:26 gap-check 二次剔除)」。
- purpose-notes.js:无自动交易专用键(仅 lab.sigkelly 等),不动。
- lab.js:自动交易视图无伪跳空文案(仅 L11901「回测买入价口径=信号次日开盘」提及),建议在视图说明补一行「伪跳空剔除」;渲染层 skipped 状态已支持(L13948-13949)。
- 生成器 docstring L30-31/L48 同步改(口径描述修正)。

## 6. 实施步骤(给 implementer 的锚点清单)
1. **A1**:改 `scripts/nextday_plan_generator.py` L499-511:新增 `_next_open(db_path, etf_code, after_date)` 查询(T+1 行 open);T+1 open 存在 → 真校验 gap=nxt_open/sig_close-1 剔除;不存在(当日计划)→ 跳过并 log「次日未开盘,留 9:26 gap-check」。docstring L30-31/L48 同步。
2. **A2**:新增 `scripts/nextday_gap_check.py`(判定函数与 backtest `_fetch_intraday_open_prices` L554-586 同款实现;读 steps date==today 行;标记 skipped+status_text;R2+purge+notify;就绪闸+9:31 重试+severe 告警;幂等)+ `scripts/nextday_gap_check.sh` 包装(交易日闸门)+ plist `com.trade.nextday-gap-check`(Weekday 1-5 9:26,RunAtLoad=false,日志 data/logs/nextday_gap_check_launchd.log 标准开始/结束行供 schedule_monitor)。
3. **前端**:lab.js 提醒视图对 steps 行 status=skipped+伪跳空 status_text 已有渲染;nextday_plan.json 条目 gap_excluded:true → 计划概要角标「伪跳空剔除」(可选,一行角标)。
4. **公示**:README L72 段改写 + lab.js 视图说明补一行 + 生成器 docstring。
5. **回测侧零改动**;阈值常量统一 import。
6. **自测**:`--date` 指定历史 T 复跑回填段验证 A1 真剔除(可选 512560 2021-11-14 信号期样例);gap-check 用假计划+mock 开盘价(参数 `--test-open`)验证标记;dry-run 模式;机检 steps 无重复标记。
7. **时点冲突核查**:9:26 vs intraday-snapshot 9:25/9:35/kelly-intraday-rerun 9:40(§14,均已确认不撞)。

## 7. 副产品发现(上报主控,不在本任务范围)
- **9-12 之后 launchd 批量任务疑似停摆**:`launchctl list` 仅 7 个 trade 任务(原应有数十个);nextday_plan 日志最后一行 2026-09-11 20:55;etf_national_team 日志最后 2026-09-12 21:30;trade 与 trade-data 两库 etf_daily 最新日期均停在 20260911 → 9-14(周一)/9-15(周二)行情采集与次日计划生成全部缺失。疑似机器重启后 LaunchAgents 未加载(会话日期 9-12→9-16 跳变佐证)。影响面远超本任务,建议主控立即派排查。

## 8. 已验证方法/数据源清单
- 代码:backtest L77-78/L495-543/L554-586/L674-687/L1614-1642;generator L79-86/L435-522/L525-560/L563-777;lab.js L11901/L13943-13962。
- 配置:plist 实测(com.trade.nextday-plan 20:55 / kelly-intraday-rerun 9:40 / intraday-snapshot 9:25 起每 10min / backfill-evening 16:35+21:00 / etf-national-team 20:07+21:30)。
- 数据:etf_daily PRAGMA 12 列含 open;两库最新日期 20260911;nextday_plan.json 实际形态;auto_trade_steps 32 行;513080/513260 实例 OHLC。
- 文档:PRD next-day-buy-prd-20260910.md(L66 口径/L114 执行器/L143 价格合理性);nextday-plan-signal-daily-design-20260910.md L34-36;nextday-plan-backend-implement-20260910.md L34;kelly-nextday-open-backtest.md §1.4;update_all.sh L181-182。
- 未实证项(诚实标注):9:26 开盘价可得性(9:40 同源已实证,9:26 未实测);akshare 竞价阶段匹配价(方案 C 依赖)。

## 复现命令
```bash
# A1 验证:历史 T 回填段真校验(次日 open 已入库)
REPO=/Users/linhuichen/code/trade-data GIT_REPO=/Users/linhuichen/code/trade python3 scripts/nextday_plan_generator.py --date 20260910 --dry-run
# A2 验证:mock 开盘价测试剔除标记(落地后)
python3 scripts/nextday_gap_check.py --test-open "513260:0.80" --dry-run
```
