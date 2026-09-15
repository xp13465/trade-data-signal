# 云服务器数据起盘完整清单(2026-09-12,纯只读调研)

> 配套:docs/deploy/migration-inventory-20260912.md(架构盘点)/ migration-checklist-20260912.md(步骤清单)。
> 本清单回答:云上 clone 后 data/ 基本为空,每个文件(DB+状态文件)怎么起盘、来源哪、多久。
> 调研基准:2026-09-12 本机 trade + trade-data 实测 + R2 signal-backup 桶实列(96 对象)。

## 0. 结论速览

1. **R2 备份桶只有 2 个 DB 的备份**(sentiment + etf_national_team,日/周/月三层)。public_fund.db(2.3G)、stock_daily.db(111M)、stock_top_weights.db(93M)没有任何 R2 备份。
2. **public_fund.db 三大路径**:①scp 直传(2.3G,推荐,迁移标准=照搬本机)②gzip 后走 upload-decommissioned 上 R2 私有桶中转(实测压缩率 28.7% → ~660MB;但 download-decommissioned 命令当前不存在,需实施补一个)③重采 stage0_full_manual.sh 约 **25h+**(overview 6.2h + nav 十几h + risk 4.5h + manager 3h)。重采唯一能"自然重建"但最慢,且本机 nav 也只覆盖 ~3.2 年(fund_daily_nav 2216 万行/27758 只≈798 天),5 年全量只会更久。
3. **stock_daily.db 重采可接受**:mootdx 全量 ~10min(源码注释:0.03s/页,5200 只串行 ~10min)+ baostock recent 段(实测增量 5200 只 57min,全量估 1.5-3h)。但 scp 111M 仍然更快。
4. **必须 scp 的状态文件只有两个**:signal_notified.json(不拷=check_signals 把 7 天窗口内信号邮件重发一遍)+ signal_kelly_etf_freeze.json(不拷=历史信号按当前 ETF 映射重新冻结,回测数字与本机不一致)。其余状态文件要么可自动生成,要么不拷只损失"去重记忆"(重发一两次通知)。
5. **前端数据产物(static-site/data/)完全不在 git**(0 个 tracked),cloud 起盘 = 起盘 DB 后跑一次全量 deploy 重新 export + upload_r2。
6. 0B 占位 DB(signal.db/signal_stats.db/board_concept.db/etf_daily.db/fund.db/trade.db)一律不拷——它们是历史占位,拷了反而让 overfit_monitor.find_db 可能误读 0B 文件。

## 1. R2 signal-backup 私有桶实测内容(2026-09-12 实列)

`upload_r2.py list` 等价命令 + `_list_keys` 实测,桶共 **96 对象**:

| 前缀 | 数量 | 内容 |
|---|---|---|
| backup/ | 42 | sentiment×21 + etf_national_team×21(20260814~20260911 逐日 .db.gz,最新 20260911) |
| weekly/ | 8 | sentiment×4 + etf_national_team×4 |
| monthly/ | 6 | sentiment×3 + etf_national_team×3 |
| claude-backup/ | 38 | Claude 自我备份 tar.gz |
| decommissioned/ | 2 | etf_national_team 旧 bak(20260728)+ decommissioned-small-baks-20260903.tar.gz |

**没有**:public_fund / stock_daily / stock_top_weights / 任何状态文件 JSON。
download-db 子命令只支持 `backup/<name>_` 前缀(name=sentiment/etf_national_team),`upload_r2.py L1639-1677`;桶里无通用 download <key> 命令。

## 2. DB 起盘表(云上 data/ 目录)

| 文件 | 本机大小 | 来源 | 起盘命令/方式 | 预计耗时 | 备注 |
|---|---|---|---|---|---|
| public_fund.db | 2.3G | **无 R2 备份** | 推荐 scp;备选见 §4 | scp 取决带宽;重采 25h+ | 19 表,最大 fund_daily_nav 2216 万行 |
| etf_national_team.db | 177M | R2 | `python scripts/upload_r2.py download-db etf_national_team data/`(输出 .db 路径到 stdout) | 下载+解压分钟级(带宽) | 恢复后跑一次 update_all 补齐当日 |
| sentiment.db | 125M | R2 | `python scripts/upload_r2.py download-db sentiment data/` | 同上 | 主库(app/db.py),恢复后补一次 update_all |
| stock_daily.db | 111M | **无 R2 备份** | 推荐 scp;备选重采:`python -m app.collector.mootdx_daily full`(~10min)+ `python -m app.collector.baostock_daily recent`(全量估 1.5-3h) | scp 快;重采 2-4h | 三表:mootdx_daily_raw/stock_daily_raw/baostock_daily_raw |
| stock_top_weights.db | 93M | **无 R2 备份,且非生产链** | **不拷** | - | 研究产物(etf-weight-leader 回测,生成脚本在 worktree docs/kelly/backtest-ai/etf-weight-leader/scripts/stock_daily_backfill.py),数据止于 20260820,生产链路零引用(grep 无果) |
| signal.db / signal_stats.db / board_concept.db / etf_daily.db / fund.db | 0B | - | **不拷** | - | 历史占位;overfit_monitor.find_db 候选 [sentiment.db, signal.db],sentiment.db 就位后不受影响 |
| trade.db | 0B | git tracked | clone 自带 | - | 旧 trade 项目占位 |
| mootdx_daily.db | 不存在 | - | - | - | .gitignore 条目是历史遗留,实际表在 stock_daily.db 内(mootdx_daily.py L3-4) |

## 3. 状态文件分级清单

### A 级:必须 scp(不拷=上线后行为异常/数字不一致)

| 文件 | 大小 | 不拷的后果(代码证据) |
|---|---|---|
| signal_notified.json | 2.3K | check_signals.py L197-213:文件不存在返回 {} → 去重失效,7 天窗口内信号邮件**全量重发**给用户 |
| signal_kelly_etf_freeze.json | 5.5M | signal_kelly_backtest.py L212-232:不存在返回 {} → 历史信号事件按当前 board_etf_map 重新冻结映射,回测/首页模拟弹窗数字与本机不一致(防换标 lookahead 语义破坏) |

### B 级:建议 scp(小文件零成本,不拷只损失去重记忆)

| 文件 | 大小 | 不拷的后果 |
|---|---|---|
| alert_state.json | 28K | 监控重检当前活跃告警并重发一轮(schedule_monitor.sh L192-200 缺失按空 state) |
| subscriptions_notified.json | 119B | 订阅用户重复收到信号(7 天窗口,check_signals.py L369) |
| notify_dedup.json | 2.5K | 30min 窗口去重失效,最多重复发一两次即时告警(notify.py L89) |
| fade_notified.json / nt_signal_notified.json / anomaly_notified.json / brief_push_state.json | <4K | 同类去重失效,重发一次 |
| signal_kelly_trades.json + .gz | 31M | 前端回测弹窗/lab 凯利区数据;可云端重算(signal_kelly_backtest.py compute,依赖 signal_stats.json+board_etf_map+freeze),但 scp 更省事 |
| baostock_progress.json / mootdx_progress.json | 147K/112K | 断点续传进度丢失,重采从零(只增不减对账,mootdx_daily.py L35-38) |
| etf_track_index.json / lof_track_index.json | 202K/179K | 可重建(fetch_etf_track_index.py 抓 fundf10,0.4-0.6s/只×1567≈15-20min),不拷=需重跑一次 |
| holdings_overlap_cache.json | 112M | overlap_fetcher 持仓重叠缓存,可重建(耗时未测),不拷影响首页持仓重叠功能首刷 |
| ab_direction_anchor.json | 25K | A/B 方向锚实验 harness 状态(7 日实验,ab_direction_anchor.py),不拷=实验从零积累 |

### C 级:可空着自然重建(不拷,自动生成)

| 文件 | 生成方式 |
|---|---|
| nextday_plan.json | nextday_plan_generator.py(干跑模式 AUTO_EXEC_ON=false) |
| trade_dates.txt | git tracked 自带旧版 + refresh_trade_dates 自动刷新(akshare sina,app/calendar.py L40) |
| stock_codes.json | git tracked 自带 + `stock_daily.py codes` 重建 |
| index_etf_map.json | git tracked 自带 |
| etf_index_map.json | deploy.sh 前置 gen_etf_index_map.py 自动生成(akshare ~1567 只) |
| board_etf_map.json | deploy.sh 前置 build_board_etf_map.py 自动生成 |
| sw_components.json | industry_width.py 无则自动拉取(L183) |
| feishu_cacert.pem | feishu_ws_listener.py export_system_cacert() 自动导出(L401/L1013) |
| news_digest.json + news_digest/ | fetch_news.py 30min cron 自动采 |
| sensenova-cooldown.json | 冷却状态,空着自然重建 |
| brief_ledger/brief_shadow/brief_reflections/daily_brief_* 系列 | 简报/反思积累,从零开始 |
| alerts/ backups/ logs/ baostock_logs/ 目录 | 日志与历史备份,云上重新积累 |

## 4. public_fund.db 专项(最大未知,已查清)

- **表构成**:19 表,fund_daily_nav 2216 万行是体积主体(2216 万/27758 只≈798 天≈3.2 年覆盖)。
- **重采成本**(stage0_full_manual.sh L7-10 注释 + public_fund.py L5303-5306):
  - overview 补 fund_basic 15 新列 ~6.2h
  - nav 5 年净值 27409 只断点续采"可能十几 h"
  - risk ~4.5h、manager ~3h;合计 **25h+**,有断点续采(progress.json)可中断续跑
  - quarterly(季度汇总+持仓,~35min,public_fund_quarterly.sh L4)
- **路径对比**:
  1. **scp 直传(推荐)**:2.3G 原始;同地域云内网/公网带宽决定耗时,无中间环节,一步到位,与"照搬本机一模一样"标准一致。
  2. **R2 私有桶中转**:`upload-decommissioned data/public_fund.db public_fund-20260912.gz`(自动 gzip,实测压缩率 28.7% → 约 660MB);但**当前 upload_r2.py 无 download-decommissioned 命令**,需实施补一个 GET 下载(参照 cmd_download_latest_db L1639-1677 范式,或通用 download <key>)。适合"云在异地、scp 慢"的场景。
  3. **重采**:25h+,且产出覆盖与本机不完全一致,仅在前两条都不通时用。
- 前端看板不依赖本地 DB(产物走 R2 public 桶 fund_nav//fund_score/ 前缀),DB 只服务于"云端接替采集职责"的每日增量。

## 5. 起盘操作序列(建议顺序)

1. scp 三个无备份 DB:`public_fund.db`(2.3G)、`stock_daily.db`(111M);scp A 级+B 级状态文件(见 §3,共约 145M 含 trades/freeze/cache)。
2. `download-db sentiment` + `download-db etf_national_team` 从 R2 拉最新(20260911)。
3. 首次全量 deploy(`bash scripts/deploy.sh all`):自动生成 etf_index_map/board_etf_map + 全量 export static-site/data + 上传 R2(注意与线上 §22 一致性:首次全量 deploy 即云端产出,与旧线上产物差异是 DB 恢复日到今日的增量)。
4. 恢复当日数据:`bash scripts/update_all.sh force` 补齐 sentiment/etf_national_team/stock_daily 到今日 + check_signals 正常运转(此时 signal_notified.json 已 scp,不会重发旧信号)。
5. 验证:verify_backup.sh 可复用为"恢复演练";check_data_integrity.py 抽样对账。

## 6. 复现段

```bash
# 桶内容实列
REPO=/Users/linhuichen/code/trade-data python3 -c "import sys;sys.path.insert(0,'scripts');import upload_r2;print(len(upload_r2._list_keys('',bucket=upload_r2.BACKUP_BUCKET)))"  # 96
# 本机 data 全景
ls -lhS /Users/linhuichen/code/trade-data/data/ | head -55
# public_fund.db 表行数
sqlite3 data/public_fund.db "SELECT COUNT(*) FROM fund_daily_nav"  # 22162244
# gzip 压缩率采样(300MB)
dd if=data/public_fund.db bs=1048576 count=300 2>/dev/null | gzip -c -6 | wc -c  # 28.7%
# git tracked data(云上 clone 自带)
git ls-files data/          # index_etf_map.json stock_codes.json trade.db trade_dates.txt
git ls-files static-site/data/ | wc -l  # 0
# baostock 实测增量速度:worker_update_0_20260911_211006.log(21:10 启动 5200 只 update,~57min)
```

## 7. 证据锚点

- backup_db.sh L70-71(只备 sentiment+etf_national_team);L84-90(调 upload-db 推 R2)
- upload_r2.py L1526-1571(cmd_upload_db 目标仅 2 库);L1639-1677(cmd_download_latest_db);L1543-1544(repo/data 路径);L184-187(BACKUP_BUCKET 默认 signal-backup)
- stage0_full_manual.sh L7-10(四步耗时);public_fund.py L5303-5306(stage0 各命令耗时)
- mootdx_daily.py L8-9(0.03s/页,5200 只 ~10min);L35-38(progress 对账)
- check_signals.py L197-213(load_signal_notified 缺失返回 {});L369(subscriptions 7 天)
- signal_kelly_backtest.py L200-232(etf_freeze path + 缺失返回 {})
- overfit_monitor.py L109-113(find_db 候选序)
- app/calendar.py L40(refresh_trade_dates=akshare sina)
- industry_width.py L183(sw_components 无则拉取)
- feishu_ws_listener.py L401/L1013(export_system_cacert)
