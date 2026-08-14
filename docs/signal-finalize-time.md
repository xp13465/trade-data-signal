# 交易信号一天中的生成/更新/定稿时点(调研结论,2026-08-12)

> 调研 agent 产出,只读不改。证据:代码点 + 2026-08-11(交易日)实测 DB 数据。
> 回答用户疑问:**15:00 收盘后到 15:35 快照前,交易信号是否可能变化?信号一天中何时定稿不再变?**

## 0. 一句话结论(先给答案)

- **A 股指数信号(首页 signals_today 主体):15:03 收盘后首轮快照已用收盘价重算定稿,15:03 到 15:36 之间不会变**(实测 2026-08-11 两轮信号集合完全一致)。
- **但 15:36 之后到晚间信号还会变**:08-11 实测 15:36 的 5 条 → 18:42 变 8 条(欧洲 DAX/CAC40 + 国债期货当日数据补入)。20:36 晚间快照后当天不再变。
- **15:00-15:35 之间唯一可能的变化点 = 14:56 盘中最后轮(实时价)→ 15:03 收盘价首轮之间**,若某指数 14:56 实时价触发信号而 15:00 收盘价不触发(或反之),该信号在 15:03 那轮消失/出现。08-11 当天恰好两轮内容相同(14:56=15:03=15:36 均 5 条)。
- 港股指数信号要等港股 16:00 收盘价(17:50 update_all 才反哺定稿);情绪分 s.* 信号(cross_market 含龙虎榜)要等晚间源(20:36 后定稿)。

## 1. 信号数据产物与生成链(证据)

- **信号存储表**:`signal_daily`(date/index_id/signal/reason),`app/db.py:47 CREATE TABLE`。
- **写入点**:`app/compute/signals.py:1449 store()` —— `DELETE FROM signal_daily` 后全量重写(DELETE+INSERT 幂等)。
- **计算入口**:`app/compute/signals.py:942 compute()` —— 对 `config/indicators.yaml` 全部 enabled 指数(158 个)逐算买点/辅买/卖点/止损/特买/备买,纯价格技术指标(RSI/布林/MACD/唐奇安/ATR/Supertrend),输入 = `index_daily` 的 OHLC(**不依赖龙虎榜/两融等晚间源**)。
- **两个重算链路**:
  1. `app/compute/runner.py:23-24`(update_all 17:50 → pipeline core → compute_runner)全量重算。
  2. **盘中快照链**:`app/collector/intraday_snapshot.py:2122` `_recompute_signals()` —— 每轮快照反哺当日 OHLC 后重算信号(DELETE+INSERT 全量 70304 条,约 2.8s)。**这是盘中信号会变、也是收盘后立即定稿的机制**(B 方案 2026-07-21)。
- **前端展示数据产物**:`overview.json` 的 `signals_today` 字段 = `app/queries.py:941`(读 signal_daily 当日,排除 `s.*` 情绪分)。盘中 `_export_affected_json`(intraday_snapshot.py:1814)每轮重算后导出 overview,故前端 15:03 后看到的就是收盘价版信号。前端消费:`static-site/app.js:1529` `ov.signals_today`。
- 衍生产物:signal_stats.json / signal_kelly_backtest.json 由 `static-site/export.py:938-953` 在 export 流程生成(基于 signal_daily 全历史),随 update_all 17:50 的 export 步骤更新。

## 2. 一天时间线(2026-08-11 交易日实测,DB signal_intraday_log)

| 时点 | 轮次信号数 | 信号内容变化 | 来源任务 |
|---|---|---|---|
| 09:26-14:56 | 4→6 波动(每10分钟一轮) | 盘中实时价,信号出现/消失频繁 | intraday-snapshot plist 每10min |
| **15:03** | **5** | **A 股收盘价首轮重算** | intraday-snapshot 15:02(收盘收尾) |
| **15:36** | **5(与 15:03 完全相同)** | 收盘价不变→信号不变 | intraday-snapshot 15:35 |
| 17:50 | (update_all 启动) | 全量 pipeline 采集/计算/export | com.trade.update-all |
| **18:42** | **8(新增 DAX/CAC40 buy_special + cgb_10y_future band_hold)** | 欧股当日数据+国债期货补入 | update_all 末尾 intraday_snapshot |
| **20:36** | **8(与 18:42 相同)** | 当天最终定稿 | intraday-snapshot 20:35 |
| 21:00/2:00 | 不重算信号 | backfill-evening 只补 daily_metric | com.trade.backfill-evening |

- signal_daily 当日最终 = 8 条(与 20:36 轮一致)。
- **18:42 的 3 条新增来自欧洲股市(DAX/CAC40 北京时间 15:00 开盘,当日数据晚间才入库)与国债期货(cgb_10y_future 15:15 收盘)** —— 证明"全球/欧股维度信号晚间才出"。
- `signal_intraday_log` 表(08-10 加)专门记录盘中每轮信号+时间戳,供收盘邮件生成"每个信号几点出现/几点消失"时间线(scripts/check_signals.py:752)。

## 3. 15:00-15:35 窗口直接回答

- **15:00:00-15:03(第一轮收盘快照完成前)**:signal_daily 仍是 14:56 盘中轮版本(实时价算)。
- **15:03(收盘后首轮快照)**:用 A 股收盘价重算 → 相对 14:56 盘中轮**可能**出现/消失信号(实时价 vs 收盘价),这是 15:00-15:35 窗口内唯一会变的时点。
- **15:03-15:36 之间**:无任务运行,收盘价已固定 → **A 股指数信号不会变**(实测 08-11 15:03=15:36 完全一致)。
- 例外:**港股 hsi/hscei/hstech 16:00 才收盘**,15:35 快照时仍是盘中价(代码注释 intraday_snapshot.py:1103"港股 16:00 收盘 -> 15:35 快照时 price 是盘中实时价"),若港股当日触发信号,17:50 update_all 反哺港股收盘价后可能再变一次。08-11 当日港股未触发,未观察到。
- 结论:用户问"3 点到 3 点半之间信号会不会消失/出现新的" —— **对 A 股指数信号不会(15:03 已用收盘价定稿);对港股/全球信号,变化点在 17:50 update_all(港股收盘价)与 18:4x(欧股/国债补入),不在 15:00-15:35 窗口内**。

## 4. 信号定稿时点(一天中何时不再变)

| 信号类别 | 定稿时点 | 说明 |
|---|---|---|
| A 股指数信号(9 宽基/31 行业/概念/申万) | **15:03(收盘价首轮)** | 收盘价固定,后续 17:50 幂等重算结果相同 |
| 港股指数信号(hsi/hscei/hstech) | **17:50 update_all** | 港股 16:00 收盘,update_all 的 intraday_snapshot 反哺收盘价 |
| 全球/欧股/国债信号(DAX/CAC40/cgb_10y_future) | **约 18:42(update_all 末尾)** | 欧股 15:00 开盘、国债期货 15:15 收盘,当日数据晚间入库 |
| 情绪分 s.* 信号(s.cross_market 含龙虎榜/两融) | **20:36 晚间快照后** | 龙虎榜 18:30 采集、两融 19:15 采集,晚间快照重算含全分项;首页 signals_today 已排除 s.*,仅 KPI 卡片/弹窗可见 |
| 美股指数信号(us_dji 等) | 次日 5:00 后 | 美股 21:30(北京)开盘,us_stock_morning 5:00 采集 |
| **当天全部信号整体** | **20:36 晚间快照后** | 08-11 实测 18:42=20:36,20:36 为当天最终;21:00/2:00 backfill 不重算信号 |

- 关键机制:`signal_daily` 是 DELETE+INSERT 全量重写,任何一轮 `_recompute_signals`/update_all 都会覆盖当天最终态 —— "定稿"取决于**当天最后一次重算**。

## 5. 提前空间分析(主控追加问题)

### 5.1 信号依赖数据源发布时点(按"卡定稿"排序)

| 数据源 | 发布时点 | 影响信号维度 |
|---|---|---|
| A 股指数收盘价(腾讯/新浪全量) | **15:00 收盘,15:05 前就绪** | 全部 A 股指数价格信号(buy/sell/buy_special 等) |
| 涨停/跌停/炸板池、全市场成交额 | 15:00 收盘定稿 | a_sentiment/cross_market 分项(盘中已有实时值) |
| 国债期货 cgb_10y_future | 15:15 收盘 | 国债信号(仅 cgb 系列) |
| 欧股 DAX/CAC40 | **15:00 开盘,当日数据晚间才入库** | 全球信号(buy_special) |
| 港股 hsi/hscei | 16:00 收盘 | 港股信号 |
| 龙虎榜 lhb_count/lhb_inst_net | **18:30/19:30 采集**(交易所盘后发布) | 仅 s.cross_market 情绪分信号(首页 signals_today 已排除) |
| 两融余额 a_fund_margin | 19:15/8:00 采集(T+1) | 仅 s.cross_market 情绪分 |
| 北向资金 a_fund_north | 盘中实时(HKEX),盘后定稿回填 | 仅 s.cross_market 情绪分 |
| 美股 us_* | 次日 5:00 | 美股信号 |

**最晚发布、卡最终定稿的瓶颈源 = 欧股当日数据(15:00 开盘,当日值晚间才入库)+ 港股收盘价(16:00)**,其次是晚间情绪分源(龙虎榜 18:30、两融 19:15,但只影响首页不展示的 s.* 信号)。

### 5.2 若提前到 15:00-15:15(收盘价固定后立即算)会缺什么

- **不缺**:A 股全部指数价格信号(9 宽基/31 行业/概念/申万/中证/深证系列)—— 15:05 收盘价就绪即可完整计算。**首页 signals_today 的主体就是这些,15:15 已可出完整 A 股版**。
- **会缺**(这些信号 15:15 时尚未定稿,需晚间补):
  - 港股信号(16:00 收盘,15:15 无当日收盘价)
  - 全球/欧股信号(DAX/CAC40 15:00 才开盘,当日数据未入库)
  - 国债期货信号(15:15 刚收盘,数据可能未就绪)
  - 情绪分 s.* 的龙虎榜/两融分项(晚间源,只影响 s.* 信号,cross_market 当日值会晚间再变)
- 影响维度小结:**提前到 15:15 可完整覆盖"A 股指数交易信号",缺的是"港股/全球/国债 + 情绪分完整性"**。

### 5.3 两段式(初版/定稿版)可行性

- **可行,且机制已天然支持**:信号引擎 `_recompute_signals()` 随时可跑、DELETE+INSERT 幂等,盘中快照本身就是每 10 分钟一版的"滚动初版"。
- 建议形态:
  - **15:05 初版**:A 股收盘价版(标注"仅 A 股,港股/全球待晚间")。
  - **17:50/18:45 定稿版**:update_all 后含港股/欧股/国债完整版。
  - **20:36 最终版**:含晚间情绪分(lhb/两融)的完整版。
- 前端需加"版本时点/覆盖范围"标注,避免用户混淆(与 §21 算法公示同思路)。这是产品决策,主控定。

### 5.4 理论上信号定稿最早几点可行(按数据源倒推)

- **A 股指数信号(首页主体):理论上 15:05 即可定稿**(收盘价 15:00 后几分钟就绪),当前实为 15:03 快照已做到,无需等 17:50 update_all —— **已有提前空间,且已在用**。
- **含港股版:最早 16:10**(港股 16:00 收盘价就绪后立即重算)。
- **含全球/欧股完整版:最早约 17:00-18:00**(依赖欧股当日数据入库,update_all 17:50 起跑,实际约 18:42 完成)。
- **含晚间情绪分最终版:最早 19:45**(龙虎榜 18:30 采集 + 两融 19:15 采集完成后),当前实为 20:36 晚间快照。
- **结论**:若用户要的"交易信号最终报告"= A 股指数信号,**15:05 就能出,比现在的 17:50 update_all 提前约 3 小时,且当前 15:03 快照已在做**;若要"全市场完整版",瓶颈是港股 16:00 与欧股晚间,理论最早 16:10(港股版)/约 18:00(含欧股版)。

## 6. 已验证方法/数据源清单(证据复核点)

- `app/compute/signals.py:942` compute()/`:1449` store() —— 信号算法与全量重写
- `app/compute/runner.py:23` —— update_all 17:50 重算
- `app/collector/intraday_snapshot.py:1750` _recompute_signals()/`:2122` 调用/`:1099` _backfill_index_daily(UPSERT)/`:1103` 港股注释/`:1814` _export_affected_json 导出 overview
- `app/queries.py:941` signals_today(排除 s.*)/`static-site/app.js:1529` 前端消费
- `config/indicators.yaml` —— 158 enabled 指数(含 hsi/hscei/us_*/cgb_*);metric 分组 lhb(龙虎榜)/a_fund(两融北向)/global
- launchd 时点:`com.trade.update-all` 17:50 / `com.trade.intraday-snapshot` 每10min + 15:02/15:35/20:35 / `com.trade.lhb-backfill` 18:30/19:30 / `com.trade.backfill-evening` 16:35/21:00/2:00 / `com.trade.us-stock-morning` 5:00
- **实测数据(2026-08-11,DB)**:`signal_intraday_log` 09:26-14:56 每轮 4-6 条波动;15:03=15:36=5 条(内容完全相同);18:42=20:36=8 条;signal_daily 当日最终 8 条
- 日志:`update_all_20260811_1750.log`(17:50:05 开始,18:41 check_signals,18:49 结束,末尾 intraday_snapshot signals 重算 70304 条)

## 7. 已实施注记(2026-08-14, 两段式信号固化上线)

> 本方案 §5.3「两段式」已实施(主控派单, 见 pending-features-index #36)。机制由 overview() 后端注入 signals_meta 三态驱动, 前端不硬编码时间。

- **后端 `app/queries.py` overview()**:注入 `signals_meta` 对象(version=`a-share-close`/`full`/`evening` + finalized + coverage + generated_at + finalized_note + operable_window)。版本判定基于**服务端当前时点 + 当日是否有数据**(score_date==今日且当前≥15:03 → a-share-close finalized;≥17:50 → full;≥20:36 → evening;盘中/无当日信号 → a-share-close finalized=false;非交易日 score_date!=今日 → full)。**每条信号补 `close`(该信号日指数收盘价, 复用 index_daily), etfs[] 每条补 `etf_close`(复用 etf_daily.close)**。零新增采集/launchd(挂在 overview 导出链)。
- **前端 `static-site/app.js`**:①信号区标题下三态提示条 `_signalFinalizeBannerHtml`(盘中预估⚠ / A股已固化✅ / 完整版定稿✅);②AI建议区「⏰ 已固化·可操作(盘后窗口)」标签(A股已固化时, `_sigSwitchHtml`);③参考说明弹窗 `_openRefHelpModal` + hoverpop `_sigHelpPopHtml` 补「⏰ 当日实操建议」段。`static-site/style.css` 加 `.sig-finalize-bar`/`.sig-finalize-ashare-tag`/`.sig-kbtn-help-pop-tag-time` 样式。
- **§21 公示**:purpose-notes.js `lab.sigkelly` 补「信号固化时点」说明(15:03 A股定稿 / 17:50 完整版 / 20:36 最终版)。
- **§22 一致性**:overview 是 signals_today 唯一权威数据源, 所有消费 overview 的展示位(首页信号卡/重绘 hook)统一读 signals_meta/close。
- 版本判定规则与前端提示文案对齐本文件 §2 时间线(15:03/17:50/20:36)。
