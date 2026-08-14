# 汪汪队「最新信号日期卡 7/31」bug 修复记录(2026-08-14)

> 关键词:汪汪队 / etf_national_team / 最新信号日期 / 信号 stale / MAX(etf_signal) 卡死 / 数据日期 vs 信号日期
> 归属:修 bug 三铁律(§23.2) + 举一反三(§23.3) + §22 展示位一致性

## 一、根因

汪汪队(ETF 国家队)信号表 `etf_signal` 是**事件表**——**只在信号触发时写行**,无触发则不写。
因此 `MAX(etf_signal.date)` 会停在最后一次触发日:
- `etf_signal.MAX(date) = 20260731`(8 月至今零触发 → 卡死 7/31)
- `etf_daily.MAX(date) = 20260814`(每日健康,写到最近交易日)

用户视角 bug:前端首页🐶卡片标题用 `MAX(etf_signal.date)` 语义展示「最近信号」,
8 月明明有每日数据(`etf_daily` 健康到 8/14),却显示「最近信号 07-31」,误导用户以为 8 月没数据。

## 二、修法(数据日期 + stale 标记,不伪装"有最新信号")

### 后端 `app/collector/etf_national_team.py::latest_signals_overview()`
- 保留 `date` = 最后一次信号触发日(`MAX etf_signal.date`,向后兼容,不再当作"数据最新日期")
- 新增 `data_date` = `MAX(etf_daily.date)`(**真实数据日期**,每日健康)
- 新增 `signal_stale`(bool) + `signal_stale_td`(int,信号日到数据日**交易日数差**)
  - 阈值 `_NT_SIGNAL_STALE_TD = 2`:信号日落后数据日 >2 交易日 → stale
  - 用 `calendar.trading_days_between()` 算交易日差(信号 T+1 发布,正常滞后 ≤2 交易日)

### 前端首页卡片 `static-site/app.js`(renderOverview 汪汪队卡片区)
- 数据日期展示改取 `nt.data_date || r.etf_date`(每日健康)
- `signal_stale=true` 时:
  - 卡片标题灰色 stale 样式(`.nt-date-tag.nt-date-stale`,含 ⚠ 前缀 + 斜体)
  - 文案:「⚠ 近 N 个交易日无信号触发(数据仍更新至 MM-DD)」
  - **不把旧信号日当"今日"高亮**(`_renderNtSignalList` 的 todayDate 传空)
- **前端兜底**:旧 overview 数据无 `signal_stale` 字段时,用信号日 vs 数据日日历日差(>3 天)本地判 stale,
  保证修复对**新旧数据都立即生效**(不等数据重跑)。

### 前端专区(汪汪队专区「近期信号按日期」)`static-site/app.js`(renderNationalTeamOverview)
- 同类(§22 一致性):最近信号日落后数据日(取 `etfs[].daily` 最大日期)>3 日历日时,
  不把旧信号日当「今日」高亮(与首页卡片同语义)。

### AI 预测 `scripts/gen_daily_brief.py`(trade-data,trade 为硬链接同文件)
- 新鲜度守卫:读 `nt_signals_today` 的 `data_date`/`signal_stale`/`signal_stale_td`,
  stale 时在 `etf_national_team_note` 注入「新鲜度提示」,明确「data_date 每日健康、最近信号日=旧日、
  近 N 交易日无信号触发」,防止 AI 把旧信号当今日实时数据呈现。

### 样式 `static-site/style.css`
- 新增 `.nt-date-tag.nt-date-stale`(灰色 + ⚠ 前缀 + 斜体)。

## 三、展示位清单(§22 一致性:所有展示位同语义)

| 展示位 | 文件/位置 | 处理 |
|---|---|---|
| 首页🐶卡片标题「数据/最近信号」 | app.js renderOverview | 改取 data_date + stale 标记 |
| 首页🐶卡片信号列表"今日"高亮 | app.js `_renderNtSignalList` todayDate | stale 时传空,不把旧信号日当今日 |
| 专区「近期信号按日期」今日高亮 | app.js renderNationalTeamOverview rcTodayDate | stale 时抑制高亮 |
| 专区图表/总盘(份额/净增持) | app.js(基于 etf_daily) | 本来就读每日健康数据,无卡死问题(已核对) |
| 通知(有信号才发) | trade-data/scripts/check_nt_signals.py | 已有跨日去重(根治 7-21~7-29 重复发旧邮件),无卡死误报 |
| AI 每日速递 | scripts/gen_daily_brief.py | 注入新鲜度守卫 |

## 四、同类排查(修 bug 三铁律③)

- 全库只有 `etf_national_team.db.etf_signal` 是**事件表**(只在触发时写行) → 这是本 bug 唯一根源表。
- 主库 sentiment.db 的 `signal_daily`(20260814)/`signal_intraday_log`(20260814) 都是**每日健康写入**,
  无"零触发 MAX 卡死"问题;`alert_log` 用 timestamp 非 date。已逐表核对,无同类。
- 通知路径 `check_nt_signals.py` 已用跨日去重解决"每晚重复发 7-20/7-31 旧邮件"同类问题(7-21~7-29 已有根治记录)。
- 前端其他信号展示(signals_today / signal_stats)都由每日健康表派生,无同类卡死。

## 五、数据层情况(损坏 DB,未擅自删,待主控定夺)

- **生产主库** = `../trade-data/data/etf_national_team.db`(launchd `cd $REPO`=trade-data 运行,健康,
  signal=7/31, daily=8/14)。生产链路(launchd + deploy.sh)一律走 trade-data,读不到 trade 本地库。
- **本地冗余副本** = `trade/data/etf_national_team.db`(180MB,**database disk image is malformed**)。
  `DB_PATH = Path(__file__).absolute().../data`,从 trade cwd 手动跑才会读到它;生产不读。
  → 属冗余损坏备份,**按 §18 L30 不擅自删**,是否删除/重建等主控确认(本次仅代码修复,未动数据层)。

## 六、上线影响

- 本次为**代码修复**,不重跑数据、不跑 deploy.sh。
- 前端已做旧数据兜底(本地判 stale),修复对当前线上 overview.json 立即生效。
- 后端新字段(`data_date`/`signal_stale`/`signal_stale_td`)在下次数据重跑(export)后写入 overview.json,
  前端优先读后端字段,二者结果一致(§22)。
