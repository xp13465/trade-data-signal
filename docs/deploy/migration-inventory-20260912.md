# macOS → 阿里云轻量服务器(Ubuntu 22.04)迁移盘点(2026-09-12,纯只读调研)

> 配套:migration-checklist-20260912.md(迁移步骤清单,末尾 3 项待精确盘点由本文档补齐)。
> 调研基准:macOS 本机 trade 主树 + trade-data 数据仓 + ~/Library/LaunchAgents 实测,全部数据可复核(复现段见文末)。

## 0. 结论速览

1. **Python 硬前提**:服务器自带 python3.10 **不够**——pandas 3.0.3 / numpy 2.4.6 官方要求 `>=3.11`(PyPI requires_python 实测),必须先装 Python 3.11 再建 venv。
2. **mini-racer 无需换包**:requirements.txt 注释只警示 macOS 别装 sqreen 版;实测 bpcreech `mini-racer 0.14.1` 自带 manylinux x86_64 wheel(PyPI 官方),Linux 直接 pip 装,通吃两平台。
3. **定时任务 41 个**:launchctl 实测 40 个 com.trade.* + 1 个 com.claude.self-backup;另有 3 个 plist 存在但未加载(codex-watcher / monitor-72h / sentiment)。分类:35 个业务/通知/运维必迁(其中 2 个运维脚本依赖 launchctl 需适配)、5 个本机 Claude 开发环境专属不迁、1 个飞书常驻 listener 建议迁(需用户拍板)。
4. **备份现状**:backup_db.sh 单脚本设计,但双仓双跑造成两份(trade/data/backups 10G/44 天份 + trade-data/data/backups 3.2G/11 天份 ≈ 13.2G,约 604M/天)。改法=RETAIN_DAYS 14→7 + 服务器单仓化 + 独立 systemd timer;改后 7 天约 2.1G,40G 盘无压力(全仓预算约 10G)。
5. **单仓化建议**:trade-data 的 app/config/scripts/a-stock-data/docs/web 全是 symlink 指回 trade,双仓结构只是本机"git 仓与数据仓隔离"的产物;服务器上直接单仓 trade(REPO=GIT_REPO 同路径),天然消灭双份 DB/双份备份问题。

## 1. 现状架构(迁移前的 mac 本机)

- trade 仓(23G 全树):代码 + .git(1.8G)+ data(14G,含 backups 10G)+ static-site(1.9G)+ .venv(515M,Python 3.11.0)+ docs(212M)。
- trade-data 仓(9.1G):data(6.6G,含 backups 3.2G)+ .venv(424M,Python 3.11.0);app/config/scripts/a-stock-data/docs/web 全部 symlink 指回 trade(ls -la trade-data 实测,memory trade-data-code-dirs-are-symlinks)。
- data/ 是两仓各自的物理目录(非 symlink、非硬链):sentiment.db 两路径 inode 实测不同(253888142 vs 237343239),即 DB 也是双份;定时任务统一 REPO=trade-data 写 trade-data/data,trade/data 由手动跑遗留(commit bb36c6d79 前默认 REPO=trade)。
- 主要 DB 体量:public_fund.db 2.3G、etf_national_team.db 177M、sentiment.db 125M、stock_daily.db 111M、stock_top_weights.db 93M(9-12 ls -lhS 实测)。
- 密钥位置:config/ 下 brief_push.json/email.json/feishu.json/sub_pwd.json/subscriptions.json/telegram.json/daily_brief.yaml/indicators.yaml/site.yaml/universe_rules.yaml(8+3 个,含 .example 模板);.env 两份:trade/.env(1036B,9-1)+ trade-data/.env(1471B,9-6)(R2 凭证/deepseek key/SENSENOVA keys 所在,仓外)。
- CF Workers + R2 托管在 Cloudflare 平台侧,不受服务器迁移影响(worker/headers.js 由 CF 构建环境部署)。

## 2. Python 完整依赖清单(实测,非 requirements.txt 的 9 个)

requirements.txt 只有 9 个包(fastapi/uvicorn/akshare/mootdx/stockstats/pyyaml/python-dateutil/mini-racer/rcssmin);实测两个 venv 各 80+ 包。以下按用途分组,版本取 trade 主 venv pip list(2026-09-12 实测)。

### A. 数据采集组(必装)
| 包 | 版本 | requires_python | Linux wheel | 备注 |
|---|---|---|---|---|
| akshare | 1.18.64 | >=3.9 | 纯 py | 核心采集源 |
| mootdx | 0.11.7 | >=3.8 | 纯 py | 通达信行情;依赖 py-mini-racer(由 mini-racer 满足) |
| tdxpy | 0.2.7 | - | 纯 py | mootdx 依赖 |
| baostock | 0.9.2 / 0.9.3 | 无限制 | 纯 py | 两 venv 版本不一,建议统一 0.9.3 |
| mini-racer | 0.14.1 | >=3.10 | **有 manylinux_2_27 x86_64 wheel** | akshare 加密 JS 接口依赖;**别换 sqreen py-mini-racer**(它会覆盖 py_mini_racer 模块) |
| requests | 2.34.2 | - | - | |
| httpx | 0.25.2 | - | - | mootdx/lark 依赖 |
| curl-cffi | 0.15.0 | - | 有 Linux wheel | akshare 依赖 |
| lxml | 6.1.1 | - | 有 | akshare/pdfplumber 传递依赖 |
| beautifulsoup4 | 4.15.0 | - | 纯 py | |
| html5lib | 1.1 | - | - | akshare 依赖 |
| openpyxl | 3.1.5 / xlrd 2.0.2 | - | - | akshare 依赖 |
| jsonpath 0.82.2 / tabulate 0.10.0 / tqdm 4.68.x / prettytable 3.18.0 / tenacity 8.5.0 | | | | akshare/mootdx 依赖 |
| pyarrow | 25.0.1 | >=3.10 | 有 cp310 manylinux | 可选提速(parquet),至少 trade venv 已装 |

### B. 数值/存储组(必装,**卡 Python 3.11**)
| 包 | 版本 | requires_python | 说明 |
|---|---|---|---|
| pandas | 3.0.3 | **>=3.11** | PyPI 官方实测,有 cp311 manylinux_2_24 x86_64 wheel |
| numpy | 2.4.6 | **>=3.11** | 同上,cp311 manylinux_2_27 wheel |
| stockstats | 0.6.8 | - | |
| python-dateutil | 2.9.0.post0 / pyyaml 6.0.3 / pydantic 2.13.4 | - | |

> **结论:服务器 Ubuntu 22.04 默认 python3.10 装不了 pandas/numpy 现版本,必须先装 Python 3.11**(deadsnakes PPA `python3.11` 或 pyenv),再 `python3.11 -m venv`。

### C. 前端 build 组(必装,deploy 链用)
- nodejs + npm(系统包):build_min.py 用 `npx --yes terser`(首次自动拉取,package.json 无项目内 npm 依赖,实测 package.json scripts.build 为空壳)。
- rcssmin 1.2.2(pip):CSS 压缩;requirements.txt 注释明确"deploy.sh 跑 build_min 需要,缺了 CSS 压缩静默跳过"。

### D. 通知/飞书/媒体组(必装)
- lark-oapi 1.5.5(>=3.7):feishu_ws_listener.py 用 lark_oapi.ws 长连接(实测 scripts/feishu_ws_listener.py L461/L465);**只有 trade venv 装了,trade-data venv 没有**。
- edge-tts 7.2.8(>=3.7):**只有 trade-data venv 装了**(daily-brief 语音用途),合并单 venv 时补。
- Pillow 12.3.0 + qrcode(gen_og_image.py/gen_qr_js.py/uumit 封面脚本用,仅 trade venv)。
- aiohttp 3.14.3(及 attrs/frozenlist/multidict/propcache/yarl 家族):仅 trade-data venv。
- smtplib 走标准库(notify.py 实测 import,Resend SMTP)。
- pdfplumber 0.11.10 / pypdfium2 5.11.0 / pdfminer.six / pycryptodome 3.23.0 / cryptography 49.0.0(仅 trade venv,PDF 解析与加密用途)。

### E. Web 服务组(备站/API 用,保留)
- fastapi 0.139.x、uvicorn 0.50/0.51、uvloop 0.22.1、watchfiles 1.2.0、websockets 16.x、starlette、python-dotenv 1.2.2。
- 说明:线上 /api/* 被 CF Workers(worker/headers.js)拦截不回源(app/auth.py 注释),FastAPI 是本地备站/开发服务,不迁移也能活,但依赖保留成本低。

### F. 测试组
- pytest 9.1.1(仅 trade venv)。

### G. macOS 专属(迁移时的处理)
- **pip 层面:无 macOS 专属包**(全部依赖在 Linux 有 wheel 或纯 py)。
- **shell 层面(需删除/适配段)**:`pmset/caffeinate` 出现于 10 个脚本(backfill_indices.sh/backfill_metrics.sh/check_data_gap_alerts.sh/etf_national_team_backfill.sh/gold_night.sh/futures_backfill.sh/lhb_backfill.sh/nextday_plan.sh/intraday_snapshot.sh/kelly_intraday_rerun.sh)——Linux 上直接删防睡眠段;`gtimeout`(brew coreutils)出现在 s06_snapshot.sh L37 降级链(timeout→gtimeout→perl),Linux 原生 timeout 直接可用;`stat -f`/`stat -c` 双兼容已内置(backup_db.sh L44/L49);`/opt/homebrew/bin` PATH 改 `/usr/local/bin:/usr/bin:/bin`。

### H. Windows 专属(不迁)
- easytrader_deploy/ 整目录(交易端,部署在 Windows 券商电脑):easytrader>=0.23.7/flask/pywinauto/easyocr/pillow/numpy/pytesseract(实测 easytrader_deploy/requirements.txt);主树脚本无 easytrader import(nextday_plan_generator.py 只在注释提,干跑模式不连)。
- mac_trader_client.py 属本机客户端,不迁。

### I. 任务书预判修正(证据)
- tushare / playwright / schedule / apscheduler:**主树 py 零 import**(AST 全量扫描 + grep 实测;playwright 仅 check_overfit_split_parity.py 注释提及,venv 未装)。
- mini-racer:Linux 直接用 bpcreech 0.14.1(PyPI 有 manylinux/musllinux wheel),无"Linux 特殊版"问题。

### J. 两 venv 差异与合并建议
| 独有包 | trade venv | trade-data venv |
|---|---|---|
| lark-oapi 1.5.5 / requests-toolbelt / Pillow / pdfplumber / pypdfium2 / pycryptodome / cryptography / uvloop / watchfiles / websockets / pytest / Markdown / Pygments | 有 | 无 |
| edge-tts 7.2.8 / aiohttp 3.14.3 / baostock 0.9.3 / uvicorn 0.51 | 无 | 有 |

**建议**:服务器单仓后建单 venv = trade venv 全集 + edge-tts + aiohttp + baostock 0.9.3;requirements.txt 补充完整(现在 9 个不够,pip 装依赖靠传递,但顶层直接 import 的 baostock/lark-oapi/edge-tts/Pillow/qrcode/pyarrow/pytest 都没登记)。

## 3. launchd 定时任务 41 个分类表(launchctl list 实测 40 + 1)

> 时点 = plist StartCalendarInterval 实测(服务器设 Asia/Shanghai 时区后全部直接复用)。
> plist 位置:~/.claude 外 ~/Library/LaunchAgents/ 为主,launchd/ 与 scripts/ 下为辅(逐个 plutil -p 提取,复现段有命令)。

### 组 1:核心业务/采集/通知/运维(必迁,35 个)

| # | 任务 | 脚本(scripts/ 下) | 时点 | 备注 |
|---|---|---|---|---|
| 1 | update-all | update_all.sh | 每天 17:50 | 4 并行 pipeline(core/width/futures/stock_daily)+末尾统一 deploy + 内嵌 backup_db.sh(L357)。盘后主链 |
| 2 | intraday-snapshot | intraday_snapshot.sh | 交易日 9:25~15:35 每 10 分钟(30 个时点)+20:35 | 腾讯指数+同花顺行业实时,flock 锁 /tmp/trade_intraday_snapshot.lock,Linux 兼容 |
| 3 | kelly-intraday-rerun | kelly_intraday_rerun.sh | 9:40 | |
| 4 | backfill-evening | backfill_metrics.sh | 16:35 / 21:00 / 2:00 | env 带 PURGE_SECRET,需随迁 |
| 5 | etf-national-team | etf_national_team_backfill.sh | 20:07 / 21:30 | env 带 PURGE_SECRET |
| 6 | etf-track-index | fetch_etf_track_index.py | 周日 3:30 | |
| 7 | fapi-daily | fapi_daily_syn.sh | 18:10 | |
| 8 | futures-backfill | futures_backfill.sh | 20:05 / 21:00 | |
| 9 | gold-night | gold_night.sh | 2:40 | 黄金夜盘 |
| 10 | lhb-backfill | lhb_backfill.sh | 18:30 / 19:30 | 龙虎榜 |
| 11 | rzhb-backfill | rzhb_backfill.sh | 8:00 / 19:15 | 融资融券 |
| 12 | turnover-backfill | turnover_backfill.sh | 21:10 周一~五 | |
| 13 | ab-direction-anchor | run_ab_direction_anchor.sh | 21:15 | env TRADE_DIR=trade |
| 14 | nextday-plan | nextday_plan.sh | 22:30 周一~五 | 次日计划生成(干跑,不连 easytrader) |
| 15 | s06-snapshot | s06_snapshot.sh | 20:35 周一~五 | timeout 降级链需 Linux 化(见 §5) |
| 16 | check-data-gap | check_data_gap_alerts.sh | 22:35 周一~五 | |
| 17 | daily-brief | run_daily_brief.sh --multi | 20:40 | deepseek 官方 API(§5.6 峰谷:20:40 低谷,key 在 trade-data/.env 需迁) |
| 18 | daily-summary-supplement | daily_summary_email.py --mode supplement | 20:30 | |
| 19 | brief-push | brief_push_wrapper.sh | 20:45 | |
| 20 | fetch-news | fetch_news.py | 每天 48 次(每小时 :01 与 :31) | 新闻采集 |
| 21 | pf-score-daily | pf_score_daily.sh | 16:00 | 场外基金评分 |
| 22 | pf-score-weekly | pf_score_weekly.sh | 周日 3:17 | |
| 23 | pf-stage0-nav | stage0_nav.sh | 周五 1:43 | |
| 24 | pf-stage0-overview | stage0_overview.sh | 周日 2:17 | |
| 25 | pf-stage0-risk | stage0_risk.sh | 每月 15 日 2:33 | |
| 26 | pf-stage0-manager | stage0_manager.sh | 每月 1 日 2:47 | |
| 27 | public-fund-daily | public_fund_daily.sh | 16:30 / 17:00 | |
| 28 | public-fund-estimation | public_fund_estimation.sh | 10:00/11:00/13:30/14:30 | |
| 29 | public-fund-full | public_fund_full.sh | 22:00 | |
| 30 | public-fund-quarterly | public_fund_quarterly.sh | 3:00/4:00/7:00 | |
| 31 | overfit-monitor | overfit_monitor.sh | 21:40 周一~五 | |
| 32 | lab-auto | update_lab.sh | 19:00 | lab 页数据 |
| 33 | us-stock-morning | us_stock_morning.sh | 5:00 | 美股早盘数据 |
| 34 | self-heal | self_heal.sh | 每 15 分(:07/:22/:37/:52) | **依赖 launchctl state(L73 起),Linux 需改 systemctl 探测或先删该检查** |
| 35 | schedule-monitor | schedule_monitor.sh | 每 15 分(:00/:15/:30/:45) | **L646-651 launchctl 加载检查需 Linux 适配** |

### 组 2:本机 Claude 开发环境专属(不迁/拍板,5+1 个)

| 任务 | 脚本 | 判定 | 理由(证据) |
|---|---|---|---|
| thinking-proxy | sensenova-rotate-proxy.sh | **不迁** | 商汤 5-7 把 key 轮换代理(127.0.0.1:8899),只服务本机 Claude Code 的 ANTHROPIC_BASE_URL;服务器不跑 Claude Code 即无用(plist 全文注释) |
| sensenova-healthcheck | sensenova-proxy-healthcheck.py | **不迁** | 每 5 分钟 GET 127.0.0.1:8899/healthz 心跳,代理不迁则无监控对象 |
| agent-inbox-watcher | agent_inbox_watcher.py | **不迁** | 轮询 Claude/codex inbox,env 依赖 CLAUDE_BIN/CODEX_BIN(nvm 路径)+ KeepAlive |
| token-cache-stats | token_cache_stats.py --append-daily | **不迁** | Claude token 缓存统计,23:30 |
| com.claude.self-backup | backup_claude_self.sh | **不迁(或改法)** | 备份 ~/.claude memory/skills 到 R2 claude-backup/,纯本机 Claude 环境;若服务器也跑 Claude Code 才迁 |
| feishu-listener | feishu_ws_listener.py | **建议迁,需拍板** | 飞书 WS 长连接监听用户指令(业务入口,lark-oapi 1.5.5+config/feishu.json);服务器 24h 在线比 mac 睡眠断连更稳;但涉及飞书 app 凭证迁移,由用户拍板 |

### 组 3:plist 存在但未加载(不迁)

codex-watcher(scripts/ 下 plist)、monitor-72h(LaunchAgents 残留)、sentiment(launchd/ 目录):launchctl list 实测无这三个 label,历史遗留。

### launchd → Linux 定时器映射建议
- 周期任务 → systemd timer(OnCalendar=)或 crontab;40 个 timer 建议用脚本一次性生成 crontab 等价表(时点已在上表)。
- 常驻任务(feishu-listener 若迁)→ systemd service(Restart=always 代替 KeepAlive)。
- launchd 参数映射:ExitTimeOut→TimeoutStartSec;StartInterval→OnUnitActiveSec/OnCalendar;EnvironmentVariables→Environment=。
- §14 时点纪律不变(17:50 update-all / 20:40 daily-brief / 盘中 9:30-15:30 不跑全量 export+deploy;服务器同北京时间)。

## 4. 备份逻辑与改法

### 4.1 当前逻辑(backup_db.sh 全读)
1. 用 Python sqlite3 `.backup()` 在线热备 **sentiment.db + etf_national_team.db**(不锁库,WAL 一致快照);
2. 写到 `$REPO/data/backups/`(BACKUP_DIR 环境变量可覆盖),文件名 `*_YYYYMMDD_HHMM.db`;
3. 保留 `RETAIN_DAYS=14` 天(默认值,L16 `RETAIN_DAYS="${RETAIN_DAYS:-14}"`),按 mtime 删除;
4. `upload_r2.py upload-db` 推 R2 signal-backup 桶异地备份(压缩保留 30 天,commit 1a573c000);
5. `verify_backup.sh` 立即从 R2 下载演练(integrity_check+行数对比,只读临时目录);
6. 本地失败 `notify.py --severe` 邮件告警(R2 失败软处理不阻塞)。
- 调用链:update_all.sh L357 `bash "$REPO/scripts/backup_db.sh"`(17:50 主链内嵌,REPO=trade-data);无独立 launchd 任务。

### 4.2 现状实测(2026-09-12)
- trade/data/backups:**10G,228 文件(88 个 .db = 44 天份)**;日期范围 2026-07-18~2026-09-11,几乎每个交易日一份;含 0 字节残留(sentiment.db/etf_national_team.db 空文件)与 .db-shm/.db-wal 垃圾。
- trade-data/data/backups:**3.2G,114 文件(22 个 .db = 11 天份)**;RETAIN_DAYS=14 生效(只留 14 天内)。
- 两份同名文件时间戳**逐日完全相同**(9-7~9-11:20:41/20:45/19:54/19:02/20:15 双仓一致,9-11 两份 birthtime 同为 20:15:03 同秒)且 inode 不同(253313203 vs 253299282)= 同刻双写两份,非 symlink/硬链。
- 日增:**302M/天/仓**(125M sentiment + 177M etf_national_team,9-11 实测字节),双仓 ≈ **604M/天**。
- 根因链:git 史 bb36c6d79 之前 backup_db.sh 默认 `REPO=trade`(diff 实测 `-REPO=.../trade +REPO=.../trade-data`)→ trade 仓遗留 44 天份;trade/data/logs 下**无任何 backup_db_*.log**(find 实测),说明 trade 侧写入不走正常日志路径(疑似 BACKUP_DIR 覆盖双跑/手动双跑),代码中无 trade 侧调用者(grep data/backups 仅 backup_db.sh 自身)。
- 时点异常:落盘时点分散(19:02/19:54/20:41/20:45/20:15),非 17:50,存在手动补跑习惯;9-12 17:50 未到前最新备份停留在 9-11 20:15。

### 4.3 改"单仓+保留 7 天"具体改法(改哪个文件哪个参数)
1. **单仓**(结构层,非脚本改):服务器只建一个 /opt/trade(REPO=GIT_REPO 同路径),不复制 trade-data 双仓;backup_db.sh L13-14 `REPO="${REPO:-/Users/linhuichen/code/trade-data}"`/`GIT_REPO="${GIT_REPO:-/Users/linhuichen/code/trade}"` 两行默认值改成服务器路径(或用 systemd `Environment=REPO=/opt/trade` 注入,一行不改)。
2. **保留期**:backup_db.sh **L16** `RETAIN_DAYS="${RETAIN_DAYS:-14}"` → `7`(或 systemd 注入 `RETAIN_DAYS=7`)。改后 7 天 × 302M ≈ 2.1G。
3. **定时**:从 update_all.sh L357 内嵌改为**独立 systemd timer 21:00**(update-all 17:50 完成后 DB 最新;顺带消灭"手动补跑"依赖);update_all.sh L357 段删除,备份单点管理。
4. **起盘**:服务器首日数据从 R2 signal-backup 桶 `upload_r2.py download-db` 拉最新备份(每日推 R2+verify 演练已保证 R2 可恢复),不必拷贝 13.2G 本地双仓;trade/data/backups 10G 旧仓不迁。
5. **容量账**:40G 盘预算 ≈ 数据本体单份 4G(public_fund 2.3G+其余 DB 1.7G)+ backups 2.1G + static-site 1.9G + venv 0.5G + git 浅克隆 ~0.5G + 临时 ≈ 9G,充裕。

## 5. macOS 专属点 Linux 适配清单

| 点 | 位置(证据) | 改法 |
|---|---|---|
| pmset/caffeinate 防睡眠 | 10 个 sh(grep 实测,§2-G 清单) | Linux 服务器不睡眠,删段(删时防 `set -u` 变量残留报错) |
| timeout→gtimeout→perl 降级链 | s06_snapshot.sh L37 注释 | 直接用 Linux 原生 timeout,删降级 |
| launchctl state/加载检查 | self_heal.sh L73 起、schedule_monitor.sh L646-651 | 改 systemctl is-active/is-failed 或迁移首期删检查(补监控) |
| stat -f 语法 | backup_db.sh L44/L49(已双兼容) | 无需改;其他脚本 grep stat -f 逐查 |
| /opt/homebrew/bin PATH | 各 plist EnvironmentVariables | 改 /usr/local/bin:/usr/bin:/bin |
| /usr/bin/python3 系统解释器 | agent-inbox-watcher/token-cache-stats/healthcheck plist | 不迁任务免改;迁的任务改 venv python |
| fcntl.flock 进程互斥 | update_all 4 pipeline(intraday_snapshot.sh 注释) | Linux 原生,无需改 |
| 时区 | - | 服务器设 Asia/Shanghai,41 个时点直接复用 |

## 6. 迁移硬前提与风险清单
1. **Python 3.11**(pandas/numpy requires_python,§2-B)装好再建 venv;
2. **nodejs+npm**(build_min terser)、git、rsync、curl(apt 装);
3. **密钥随迁**:config/ 11 个 json/yaml + trade-data/.env(R2 凭证/deepseek key 必迁;SENSENOVA_KEY* 若 thinking-proxy 不迁则不必迁);
4. **PURGE_SECRET** 等 plist 内嵌环境变量逐项随 systemd unit 迁移(backfill-evening/etf-national-team/etf-track-index 三任务);
5. §14 生产稳定性纪律与 §5.6 deepseek 峰谷(daily-brief 20:40 低谷)在新机器同样生效;
6. 双份 DB 迁移取 trade-data/data 为准(定时链 REPO 统一 trade-data);手动跑遗留的 trade/data 侧库不迁(单仓化后问题自然消失);
7. worker/(CF Workers)与 R2 配置不迁(平台侧);deploy.sh 的 git push 目标不变(服务器持有 git 凭证)。

## 复现段(2026-09-12 调研,全部命令可重跑复核)
```
# 定时任务实测
launchctl list | grep -i trade          # 40 个
ls ~/Library/LaunchAgents/ | grep trade # 41 个文件(codex-watcher/monitor-72h 未加载残留)
# plist 批量提取(本文档 §3 表数据来源)
for name in $(launchctl list|grep trade|awk '{print $3}'); do
  f=~/Library/LaunchAgents/com.trade.$name.plist
  [ -f "$f" ] || f=/Users/linhuichen/code/trade/launchd/com.trade.$name.plist
  [ -f "$f" ] || f=/Users/linhuichen/code/trade/scripts/com.trade.$name.plist
  [ -f "$f" ] || f=/Users/linhuichen/code/trade/scripts/plists/com.trade.$name.plist
  plutil -p "$f" | grep -E "ProgramArguments|Hour|Minute|Weekday|StartInterval"
done
# 依赖实测
/Users/linhuichen/code/trade/.venv/bin/pip list && /Users/linhuichen/code/trade-data/.venv/bin/pip list
# 第三方 import 全量(AST,排除标准库)
python3 - <<'EOF'   # 遍历 scripts/app/a-stock-data/easytrader_deploy/worker/static-site 的 import/ImportFrom,与 sys.stdlib_module_names 差集
EOF
# PyPI 官方 requires_python / Linux wheel(§2 表数据来源)
curl -s https://pypi.org/pypi/pandas/3.0.3/json | python3 -c "import json,sys;d=json.load(sys.stdin);print(d['info']['requires_python'],[f['filename'] for f in d['urls'] if 'manylinux' in f['filename']][:1])"
# 备份实测
du -sh /Users/linhuichen/code/trade/data/backups /Users/linhuichen/code/trade-data/data/backups   # 10G / 3.2G
ls /Users/linhuichen/code/trade/data/backups/sentiment_*.db | sed 's/.*_//;s/\.db//' | sort | head -1; # ... | tail -1  # 7-18~9-11
git -C /Users/linhuichen/code/trade show bb36c6d79 -- scripts/backup_db.sh | grep REPO   # 默认仓 trade→trade-data 变更
grep -n "RETAIN_DAYS\|BACKUP_DIR\|REPO=" /Users/linhuichen/code/trade/scripts/backup_db.sh  # L13/L14/L16
grep -n "backup_db.sh" /Users/linhuichen/code/trade/scripts/update_all.sh                  # L357 内嵌调用
# macOS 专属 grep
grep -rln "pmset\|caffeinate" /Users/linhuichen/code/trade/scripts/*.sh
grep -n "gtimeout" /Users/linhuichen/code/trade/scripts/s06_snapshot.sh
grep -n "launchctl" /Users/linhuichen/code/trade/scripts/schedule_monitor.sh | head -3
```
