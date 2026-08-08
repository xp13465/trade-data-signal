# 站点部署文档（site-deployment.md）

> 完整站点架构盘点 + 从零重建/灾备镜像搭建指南。
> 最后更新：2026-08-08。R2 数据层迁移已完成（阶段 1a-5 全部上线 main），git 代码 / R2 数据解耦，数据唯一走 R2。完整 R2 部署文档见 [docs/r2-deployment.md](r2-deployment.md)。

---

## 目录

1. [架构总览](#1-架构总览)
2. [代码仓库与目录结构](#2-代码仓库与目录结构)
3. [环境与依赖](#3-环境与依赖)
4. [数据库](#4-数据库)
5. [R2 数据层](#5-r2-数据层)
6. [CF Workers 部署](#6-cf-workers-部署)
7. [多域名配置](#7-多域名配置)
8. [定时任务](#8-定时任务)
9. [重建步骤（从零搭建）](#9-重建步骤从零搭建)
10. [灾备镜像搭建](#10-灾备镜像搭建)
11. [排障](#11-排障)
12. [线上验证](#12-线上验证)

---

## 1. 架构总览

```
                          ┌─────────────────────────────────────────────┐
                          │              用户浏览器 / PWA                 │
                          │   ss.fx8.store (CF Workers 主站)              │
                          │   sss.sugas.site (GH Pages 备站)              │
                          │   s.sugas.site (MaoziYun 备站)                │
                          │   ssd.fx8.store (R2 直链)                     │
                          └──────────┬──────────────────┬────────────────┘
                                     │                  │
                        前端静态资源  │      大 JSON 数据  │
                    (HTML/JS/CSS/小JSON)│  (all/5y/3y/index/│
                                     │    industry/lab等)  │
                          ┌──────────▼──────┐  ┌────────▼────────┐
                          │  CF Workers      │  │  R2 (signal-data) │
                          │  Static Assets   │  │  Public Bucket    │
                          │  + worker/       │  │  ssd.fx8.store    │
                          │    headers.js    │  └──────────────────┘
                          │  (cache rules +  │
                          │   /r2/ proxy +   │
                          │   /data/ rewrite │
                          │   /api/subscribe │
                          │   /api/auth/*)   │
                          └────────┬─────────┘
                                   │ push main 自动 deploy
                                   │ (GH Actions deploy-cf.yml)
                          ┌────────▼─────────┐
                          │  GitHub 仓库      │
                          │  trade-data-signal│
                          │  (static-site/ +  │
                          │   worker/ + app/) │
                          └────────┬─────────┘
                                   │ git push (deploy.sh)
                          ┌────────▼──────────────────────────┐
                          │     本地 Mac (采集+计算+导出)        │
                          │                                     │
                          │  trade-data/ (cwd, DB, .venv)       │
                          │  ├── data/sentiment.db (80MB)       │
                          │  ├── data/etf_national_team.db      │
                          │  ├── data/public_fund.db            │
                          │  ├── .venv/ (Python 3.11)           │
                          │  ├── .env (R2凭证+DeepSeek+Purge)   │
                          │  ├── app -> trade/app (symlink)     │
                          │  ├── scripts -> trade/scripts       │
                          │  └── config -> trade/config         │
                          │                                     │
                          │  trade/ (git 仓库, 代码源)            │
                          │  ├── app/ (FastAPI + 采集 + 计算)    │
                          │  ├── static-site/ (前端 + export.py) │
                          │  ├── scripts/ (deploy/backup/upload) │
                          │  ├── worker/ (CF Worker)             │
                          │  ├── config/ (indicators.yaml等)     │
                          │  ├── wrangler.jsonc                  │
                          │  └── .github/workflows/              │
                          │                                     │
                          │  launchd 24个定时任务                  │
                          │  (采集/计算/导出/推送/监控/自愈)        │
                          └─────────────────────────────────────┘
```

**数据流**：launchd 定时任务 → 采集脚本(akshare/mootdx/baostock) → 写 DB(trade-data/data/) → export.py 导出 JSON → deploy.sh 推 git main + upload_r2.py 推 R2 → CF Workers/GH Pages 自动 deploy → 用户访问。

**关键设计**：
- 采集和 git 上线分离：trade-data 跑采集写 DB，trade 仓库 git push 上线（deploy.sh rsync 同步）
- 线上前端只读静态 JSON，不依赖 DB（DB untracked 不进 git）
- R2 托管所有数据文件（小 JSON 经 Worker /data/ rewrite 直读 R2，大文件经 /r2/ 代理或 ssd.fx8.store 直链），CF Workers 只托管代码 + min JS/CSS
- 多域名冗余：3 个独立托管平台 + 1 个 R2 直链，任一不可达不影响整体可用性

---

## 2. 代码仓库与目录结构

### 2.1 仓库关系

| 路径 | 用途 | git |
|---|---|---|
| `/Users/linhuichen/code/trade` | 主代码仓库（前端+后端+脚本+Worker配置） | git@github.com:xp13465/trade-data-signal.git |
| `/Users/linhuichen/code/trade-data` | 采集运行目录（DB+日志+.venv+.env），通过 symlink 复用 trade 的代码 | 无 git init（不独立 commit，采集后 rsync 到 trade 上线） |
| `staticdata`（规划中） | 数据备份仓库（DB + static-site/data 静态产物备份） | git@github.com:xp13465/trade-data-signal-staticdata.git |

**trade-data 的 symlink 结构**（关键：uvicorn cwd 必须 trade-data/）：

```
trade-data/
├── .venv/              # Python 虚拟环境（独立）
├── .env                # 运行时密钥（R2凭证 + DeepSeek + PURGE_SECRET）
├── data/               # 实际 DB + 日志（launchd 写入路径）
│   ├── sentiment.db
│   ├── etf_national_team.db
│   ├── public_fund.db
│   ├── logs/           # 所有 launchd 日志
│   └── backups/        # 本地 DB 热备（14天滚动）
├── static-site/        # export.py 输出路径（rsync 到 trade/static-site/ 上线）
├── app -> trade/app    # symlink（代码源在 trade）
├── scripts -> trade/scripts
├── config -> trade/config
└── web -> trade/web    # 历史遗留（web/ 已弃用）
```

> **为什么 cwd 必须是 trade-data/**：`app/db.py` 的 `Path(__file__).absolute().parent.parent / "data" / "sentiment.db"` 从 cwd 解析 DB 路径。trade-data/data/ 是 launchd 实际写入的主库，trade/data/ 是 rsync 同步的镜像（可能滞后）。uvicorn 从 trade/ 跑会读滞后镜像致 export 漏数据。

### 2.2 trade 仓库目录结构

```
trade/
├── app/                         # Python 后端
│   ├── main.py                  # FastAPI 入口（挂载 static-site/ + /api/* 路由）
│   ├── db.py                    # SQLite schema + 连接
│   ├── queries.py               # 共享查询层（22函数，main.py/export.py 共用）
│   ├── auth.py                  # OAuth 认证（Gitee/GitHub/Google）
│   ├── calendar.py              # 交易日历判断
│   ├── collector/               # 采集层
│   │   ├── mootdx_daily.py      # 通达信 TCP 日线
│   │   ├── baostock_daily.py    # BaoStock 日线
│   │   ├── baostock_parallel.py # BaoStock 多进程
│   │   ├── tencent.py           # 腾讯实时行情
│   │   ├── etf_national_team.py # ETF 国家队
│   │   ├── public_fund.py       # 公募基金
│   │   ├── intraday_snapshot.py # 盘中快照
│   │   ├── gold_night.py        # 夜盘黄金
│   │   ├── us_futures.py        # 美股期货
│   │   └── ...                  # 其他采集器
│   └── compute/                 # 计算层
│       ├── signals.py           # 买卖点信号
│       ├── sentiment.py         # 情绪分
│       ├── fear_greed.py        # 恐贪指数
│       ├── cross.py             # 跨市场评分
│       └── ...                  # 其他计算
├── static-site/                 # 前端（单版，CF Workers 部署）
│   ├── index.html               # 入口
│   ├── app.js / app.min.js      # 主前端逻辑
│   ├── lab.js / lab.min.js      # 策略实验室
│   ├── style.css / style.min.css
│   ├── lab.css / lab.min.css
│   ├── common.js / common.min.js
│   ├── sw.js                    # Service Worker（PWA 离线缓存）
│   ├── manifest.json            # PWA 清单
│   ├── _headers                 # CF Pages 安全头+缓存分层（Worker 接管时回退）
│   ├── about.html / privacy.html
│   ├── export.py                # SQLite -> JSON 导出脚本
│   ├── data/                    # 预生成 JSON（R2 上传，不进 git）
│   │   ├── overview.json        # 今日快照
│   │   ├── a-stock-{3m,6m,1y}.json  # 小 range 留 git
│   │   ├── ...                  # 大 range (all/5y/3y) 走 R2，.gitignore 移出
│   │   ├── index/               # 44 指数全历史（R2 托管）
│   │   ├── lab/                 # 策略实验室（R2 托管）
│   │   └── trade_sim/           # 回测 HTML（R2 托管）
│   └── vendor/                  # ECharts 等第三方库
├── worker/                      # CF Worker 脚本
│   ├── headers.js               # 主 Worker（cache + /r2/ + /data/ + /api/）
│   ├── subscribe.js             # 订阅接口（KV 存储）
│   └── auth.js                  # OAuth 接口
├── scripts/                     # 运维脚本
│   ├── deploy.sh                # 全量导出+部署（export+R2+git push）
│   ├── update_all.sh            # 主采集（4 pipeline 并行）
│   ├── intraday_snapshot.sh     # 盘中快照（每10min push main）
│   ├── upload_r2.py             # R2 上传/下载（15+命令）
│   ├── backup_db.sh             # DB 热备 + R2 异地
│   ├── verify_backup.sh         # 恢复演练
│   ├── build_min.py             # terser minify JS/CSS
│   ├── bump_asset_version.py    # md5 破缓存
│   ├── check_data_integrity.py  # 数据产物校验（deploy 前置）
│   ├── gen_rss.py               # RSS feed 生成
│   ├── gen_schedule_stats.py    # 定时任务统计
│   ├── notify.py                # 邮件/Telegram 通知
│   ├── pipeline.sh              # 并行 pipeline 封装
│   ├── with_lock.py             # fcntl.flock 互斥锁
│   └── ...                      # 其他采集/回填脚本
├── config/                      # 配置文件
│   ├── indicators.yaml          # 指标注册表（39KB，增删改不动核心代码）
│   ├── email.json               # SMTP 配置（.gitignore）
│   ├── telegram.json            # Telegram bot（.gitignore）
│   ├── subscriptions.json       # 订阅配置（.gitignore）
│   ├── sub_pwd.json             # 订阅密码（.gitignore）
│   └── *.example                # 配置模板（进 git）
├── .github/workflows/
│   ├── deploy-cf.yml            # push main -> wrangler deploy（CF Workers）
│   └── deploy-pages.yml         # push main -> GH Pages deploy
├── .env                         # R2 S3 凭证（.gitignore）
├── .env.example                 # OAuth 环境变量模板
├── wrangler.jsonc               # CF Workers 配置
├── package.json                 # Node 包定义（wrangler 依赖）
├── requirements.txt             # Python 依赖
├── CLAUDE.md                    # 项目工作规范
├── docs/                        # 文档
│   ├── backup-restore.md        # DB 备份与恢复手册
│   ├── data-dictionary.md       # JSON 数据字段说明
│   ├── data-sources.md          # 数据源说明
│   ├── smoke-checklist.md       # 主功能回归清单
│   └── site-deployment.md       # 本文件
└── data/                        # 本地 DB（.gitignore，rsync 镜像）
    ├── sentiment.db
    ├── etf_national_team.db
    └── public_fund.db
```

---

## 3. 环境与依赖

### 3.1 系统环境

| 组件 | 版本/要求 | 说明 |
|---|---|---|
| macOS | Darwin 23+ (Apple Silicon) | launchd 定时任务、Homebrew |
| Python | 3.11+ | .venv 虚拟环境 |
| Node.js | LTS (>=16) | wrangler CLI（npx 或全局安装） |
| Homebrew | 最新 | 包管理（非必需但推荐） |
| Git | 2.x | 代码版本控制 + 数据上线 |

### 3.2 Python 依赖（requirements.txt）

```
fastapi>=0.110              # Web 框架（动态版/API）
uvicorn[standard]>=0.29     # ASGI 服务器
akshare==1.18.64            # 东财/新浪/腾讯数据源
mootdx==0.11.7              # 通达信 TCP 日线
stockstats==0.6.8           # 技术指标计算
pyyaml>=6.0                 # indicators.yaml 解析
python-dateutil>=2.9        # 日期处理
mini-racer==0.14.1          # V8 引擎（akshare 加密 JS 接口依赖）
rcssmin>=1.1                # CSS 压缩（build_min.py 依赖）
```

> **注意 mini-racer**：必须用 `bpcreech/mini-racer`（包名 `mini-racer`），不要装 `sqreen/py-mini-racer==0.6.0`（只带 muslc.so，macOS arm64 不兼容，会导致 akshare 指数采集全挂）。

### 3.3 Node 依赖

```bash
# wrangler 通过 npx 运行，无需全局安装
npx wrangler@latest deploy

# 或 GH Actions 中 npm install wrangler@latest
```

### 3.4 密钥与配置文件

#### .env（trade 根目录，.gitignore）

R2 S3 兼容凭证，供 upload_r2.py 上传/下载数据：

```ini
# Cloudflare R2 (S3 兼容) - 本地凭证不进 git
R2_BUCKET=signal-data
R2_S3_ACCESS_KEY_ID=<R2 Access Key ID>
R2_S3_SECRET_ACCESS_KEY=<R2 Secret Access Key>
# endpoint: https://<ACCOUNT_ID>.r2.cloudflarestorage.com
R2_S3_ENDPOINT=https://<ACCOUNT_ID>.r2.cloudflarestorage.com
R2_PUBLIC_DOMAIN=https://ssd.fx8.store
```

#### trade-data/.env（运行时密钥）

```ini
DEEPSEEK_API_KEY=<DeepSeek API Key>
DEEPSEEK_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
DEEPSEEK_MODEL=<模型名>
PURGE_SECRET=<R2 缓存清除密码>
```

#### wrangler secrets（CF Workers 端）

通过 `wrangler secret put <NAME>` 设置，不进 wrangler.jsonc：

| Secret | 用途 |
|---|---|
| `PURGE_SECRET` | /api/purge-cache 接口认证（清除 R2 边缘缓存） |
| `SUBSCRIBE_PASSWORD` | /api/subscribe 订阅接口认证 |
| `GITEE_CLIENT_ID` | Gitee OAuth |
| `GITEE_CLIENT_SECRET` | Gitee OAuth |
| `GITEE_REDIRECT_URI` | OAuth 回调（生产 `https://ss.fx8.store/api/auth/callback/gitee`） |
| `SESSION_SECRET` | session cookie HMAC 签名密钥 |

#### GH Actions secrets

| Secret | 用途 |
|---|---|
| `CLOUDFLARE_API_TOKEN` | GH Actions 跑 `wrangler deploy` 的 API Token |

#### config/ 配置文件（.gitignore，有 .example 模板）

| 文件 | 用途 |
|---|---|
| `config/email.json` | SMTP 邮件通知（163 邮箱） |
| `config/telegram.json` | Telegram bot 通知 |
| `config/subscriptions.json` | 订阅者列表 |
| `config/sub_pwd.json` | 订阅密码 |
| `config/indicators.yaml` | 指标注册表（进 git，非敏感） |

---

## 4. 数据库

### 4.1 数据库清单

| DB | 路径（生产） | 大小 | 用途 | git |
|---|---|---|---|---|
| sentiment.db | `trade-data/data/sentiment.db` | ~80MB | 情绪/信号/评分/指数/宽度/期货 | untracked |
| etf_national_team.db | `trade-data/data/etf_national_team.db` | ~5MB | ETF 国家队资金动向 | untracked |
| public_fund.db | `trade-data/data/public_fund.db` | ~20MB | 公募基金（21表） | untracked |

> **DB untracked**：2026-07-14 根治（commit 8e3f5fa），DB 移出 git 避免切分支污染。线上前端只读 static-site/data/*.json 静态产物，不依赖 DB。

### 4.2 sentiment.db 表结构（15 表）

| 表 | 主键 | 用途 | 行数（参考） |
|---|---|---|---|
| `daily_metric` | (date, metric_id) | 每日指标值（涨跌家数/成交额/北向等） | ~218K |
| `index_daily` | (date, index_id) | 指数日线（开高低收/涨跌/成交额/净流入） | ~488K |
| `score_daily` | (date, score_id) | 情绪分（综合/恐贪/6宽基） | ~37K |
| `signal_daily` | (date, signal_id) | 买卖点信号 | ~70K |
| `board_daily` | (date, board_type, board_name) | 板块涨跌/资金流 | - |
| `futures_position` | (date, symbol) | 中金所期货机构持仓 | ~9K |
| `futures_ih_detail_acc` | - | IH 期货同向准确度 | - |
| `futures_accuracy` | - | 期货准确度统计 | - |
| `industry_width_daily` | - | 行业宽度 | - |
| `intraday_snapshot` | - | 盘中快照历史 | - |
| `intraday_amount_history` | - | 盘中成交额历史 | - |
| `alert_log` | - | 告警日志 | - |
| `collect_log` | - | 采集日志 | - |
| `manual_entry` | - | 手动补录 | - |
| `users` | - | 用户表（OAuth） | - |

### 4.3 etf_national_team.db 表结构（4 表）

| 表 | 用途 |
|---|---|
| `etf_daily` | ETF 日线（12 只宽基 ETF） |
| `etf_signal` | ETF 信号 |
| `etf_holder_quarterly` | 季度持有人结构 |
| `national_team_holders` | 国家队持有人 |

### 4.4 public_fund.db 表结构（18 表）

| 表 | 用途 |
|---|---|
| `fund_basic` | 基金基本信息（21列） |
| `fund_daily_nav` | 每日净值 |
| `fund_estimation_nav` | 估值净值 |
| `fund_performance` | 业绩 |
| `fund_hold_structure` | 持仓结构 |
| `fund_holding_stock` | 重仓股 |
| `fund_portfolio_hold` | 组合持仓 |
| `fund_asset_alloc` | 资产配置 |
| `fund_industry_alloc` | 行业配置 |
| `fund_position_history` | 仓位历史 |
| `fund_scale_change` | 规模变动 |
| `fund_manager` | 基金经理 |
| `fund_metrics` | 指标 |
| `fund_rating` | 评级 |
| `fund_risk_indicator` | 风险指标 |
| `fund_fee_detail` | 费率 |
| `fund_score` | 评分 |
| `fund_purchase_status` | 申购状态 |
| `fund_index_daily` | 指数日线 |

### 4.5 创建/初始化

```bash
# 初始化 sentiment.db（建表）
cd /Users/linhuichen/code/trade
.venv/bin/python -m app.db

# 首次回填历史数据（mootdx 全 A 股日线 + BaoStock 校验，约 10 年）
.venv/bin/python -m app.backfill
```

### 4.6 备份与恢复

详见 [docs/backup-restore.md](backup-restore.md)，三层备份机制：

1. **本地热备**：`backup_db.sh` 每日 17:50 后自动跑，Python `sqlite3.Connection.backup()` 在线 API（不锁库），`data/backups/` 保留 14 天
2. **R2 异地备份**：gzip 压缩上传到私有桶 `signal-backup`，三层保留（日 30 天 / 周 28 天 / 月 365 天）
3. **恢复演练**：`verify_backup.sh` 每日自动跑，从 R2 下载 → `PRAGMA integrity_check` → 关键表行数对比

从 R2 恢复：

```bash
cd /Users/linhuichen/code/trade
.venv/bin/python scripts/upload_r2.py download-db sentiment.db      # 下载最新
.venv/bin/python scripts/upload_r2.py download-db etf_national_team
.venv/bin/python scripts/upload_r2.py download-db public_fund
# 恢复到生产路径：trade-data/data/<name>.db（非 trade/data/）
```

---

## 5. R2 数据层

> **状态**：R2 迁移阶段 1a-5 已全部上线 main（2026-08-08）。git 代码 / R2 数据解耦完成，`static-site/data/` 移出 git 走 R2 唯一数据来源，定时任务去 git push 改 R2 上传 + purge_cache + notify，staticdata git 差异化日志备份。完整架构 + 重建步骤见 [docs/r2-deployment.md](r2-deployment.md)。

### 5.1 R2 Bucket 清单

| Bucket | 可见性 | 用途 | 绑定 |
|---|---|---|---|
| `signal-data` | 公开（ssd.fx8.store 直链 + Worker binding） | 数据文件（JSON/.gz/HTML） | wrangler.jsonc `R2_BUCKET` |
| `signal-backup` | 私有（不绑域名） | DB 备份 + Claude 自我备份 | upload_r2.py `BACKUP_BUCKET` |

### 5.2 upload_r2.py 命令清单

| 命令 | 上传内容 | R2 前缀 | 用途 |
|---|---|---|---|
| `upload-lab` | lab/*.json | `lab/` | 策略实验室数据 |
| `upload-trade-sim` | trade_sim_*.html | `trade_sim/` | 回测 HTML 页面 |
| `upload-trade-sim-json` | trade_sim_*_stats.json + _full.json | `trade_sim_data/` | 回测统计数据 |
| `upload-index` | data/index/*.json | `index/` | 44 指数全历史 |
| `upload-industry` | data/industry-* | `industry/` | 行业数据（拆分目录+单文件） |
| `upload-public-fund` | data/public_fund* | `public_fund/` | 公募基金数据 |
| `upload-offshore-fund` | data/offshore_fund* | `offshore_fund/` | 场外基金（100K+ 只） |
| `upload-fund-score` | data/fund_score* | `fund_score/` | 基金评分 |
| `upload-etf-score` | data/etf_score_list_*.json | `data/` | ETF 评分（buy/sell/hold） |
| `upload-data-large` | data/ 顶层 >1MB 或大 range .json | `data/` | 大 JSON（all/5y/3y 等） |
| `upload-all-data` | data/ 全量小 .json | `data/` | 全量小文件上 R2（排除已走独立命令的） |
| `upload-intraday` | intraday 相关 23 文件 | `data/` | 盘中实时快照 |
| `upload-data-files <f1> [f2]...` | 指定文件列表 | `data/` | 精准上传指定文件 |
| `upload-db` | sentiment.db + etf_national_team.db | `backup/` + `weekly/` + `monthly/` | DB 异地备份（signal-backup 桶） |
| `upload-claude-backup` | Claude 自我备份 tar.gz | `claude-backup/` | Claude 配置异地备份 |
| `list [prefix]` | 列对象 | - | 查询 |
| `download-db <name>` | 下载最新 DB 备份 | - | 恢复用 |

### 5.3 前端 R2 访问方式

- **所有 /data/*.json**：Worker `/data/` rewrite -> R2 binding 直读，前端 URL 零改动。R2 404 回退 ASSETS（静态文件兜底）。Cache API 边缘缓存 + 分层 TTL（60s/600s/3600s）+ `/api/purge-cache` 主动清除
- **大 range 历史**（`*-(all|5y|3y).json`）：前端 `dataUrl()` helper 路由到 `https://ssd.fx8.store/data/`（R2 公开桶直链）或 Worker `/r2/` 代理
- **index/industry/lab/trade_sim/public_fund/fund_score**：前端硬编码 `https://ssd.fx8.store/{prefix}/` URL

### 5.4 Worker R2 代理路由

worker/headers.js 实现三条 R2 路由：

1. `/r2/*` 代理（P0-4）：R2 binding 直读 + Cache API 边缘缓存 1h。替代原 ssd.fx8.store public bucket 直链（cf-cache-status DYNAMIC 每次回源 ~1s），二次请求边缘 HIT ~50ms
2. `/data/*.json` rewrite（阶段 2）：截获 /data/*.json 请求，R2 key = `data/overview.json`。R2 404 回退 ASSETS。Cache API 边缘缓存 + 分层 TTL（60s/600s/3600s）+ `/api/purge-cache` 主动清除
3. `/api/purge-cache`（阶段 2）：POST + PURGE_SECRET 认证，清除指定 R2 key 的边缘缓存。upload_r2.py 上传新数据后自动调用

### 5.5 创建 R2 Bucket

```bash
# 安装 wrangler 并登录
npx wrangler login

# 创建数据 bucket（公开访问）
npx wrangler r2 bucket create signal-data
# 设置公开访问域名（CF Dashboard -> R2 -> signal-data -> Settings -> Public access）
# 绑定域名 ssd.fx8.store

# 创建备份 bucket（私有，不绑域名）
npx wrangler r2 bucket create signal-backup

# 创建 R2 API Token（S3 兼容）
# CF Dashboard -> R2 -> Manage R2 API Tokens -> Create API Token
# 权限：Object Read & Write（两个 bucket）
# 复制 Access Key ID + Secret Access Key + Endpoint（含 Account ID）
# 填入 trade/.env
```

---

## 6. CF Workers 部署

### 6.1 wrangler.jsonc 配置

```jsonc
{
  "name": "trade-data-signal",
  "compatibility_date": "2026-07-07",
  "main": "worker/headers.js",           // Worker 脚本（接管 response headers）
  "assets": {
    "directory": "./static-site",         // 静态资源目录
    "binding": "ASSETS",
    "run_worker_first": true              // Worker 先于 assets 执行（接管所有 headers）
  },
  "kv_namespaces": [
    {
      "binding": "SUBSCRIBE_KV",          // 订阅接口 KV 存储
      "id": "7d373c3365314ec7a334ac47a73f1578",
      "remote": true
    }
  ],
  "r2_buckets": [
    { "binding": "R2_BUCKET", "bucket_name": "signal-data" }
  ]
}
```

### 6.2 Worker 脚本（worker/headers.js）

功能模块：
- **安全头**：HSTS preload / nosniff / X-Frame-Options / Referrer-Policy / Permissions-Policy / CSP-Report-Only
- **缓存分层**：版本化 JS/CSS 1 年 immutable / HTML no-store / 实时数据 60s / 历史 1h-6h
- **`/r2/*` 代理**：R2 binding 直读 + Cache API 边缘缓存（阶段 P0-4）
- **`/data/*.json` rewrite**：R2 binding 直读 + ASSETS 回退（阶段 2）
- **`/api/purge-cache`**：POST + PURGE_SECRET 认证，清除指定 R2 key 的边缘缓存
- **`/api/subscribe`**：CRUD 订阅接口，SUBSCRIBE_KV 存储 + SUBSCRIBE_PASSWORD 认证
- **`/api/auth/*`**：OAuth 路由（Gitee/GitHub/Google），Web Crypto HMAC session

### 6.3 _headers 文件

`static-site/_headers` 定义安全头 + 缓存分层。**注意**：`run_worker_first=true` 时 _headers 不生效（Worker 接管所有 headers），仅作纯 assets 模式回退兜底。缓存规则在 worker/headers.js 的 `CACHE_RULES` 数组中维护。

### 6.4 GH Actions 自动部署

**deploy-cf.yml**（CF Workers）：
- 触发：push to main（paths: `static-site/**`, `worker/**`, `wrangler.jsonc`, `app/**`）
- 流程：checkout → setup-node LTS → `npm install wrangler@latest` → `npx wrangler deploy`
- Secret：`CLOUDFLARE_API_TOKEN`
- 并发控制：`concurrency: cf-workers-deploy, cancel-in-progress: false`（排队不取消）

**deploy-pages.yml**（GH Pages）：
- 触发：push to main
- 流程：checkout → configure-pages → upload `./static-site` → deploy-pages
- 并发控制：`cancel-in-progress: true`

### 6.5 首次部署

```bash
# 1. 确保 wrangler.jsonc 配置正确
# 2. 设置 GH Actions secret：CLOUDFLARE_API_TOKEN
#    GitHub repo -> Settings -> Secrets and variables -> Actions -> New secret
# 3. git push origin main
#    -> GH Actions 自动跑 wrangler deploy
#    -> 或本地手动：npx wrangler deploy

# 4. 设置 wrangler secrets
npx wrangler secret put PURGE_SECRET
npx wrangler secret put SUBSCRIBE_PASSWORD
npx wrangler secret put GITEE_CLIENT_ID
npx wrangler secret put GITEE_CLIENT_SECRET
npx wrangler secret put GITEE_REDIRECT_URI  # https://ss.fx8.store/api/auth/callback/gitee
npx wrangler secret put SESSION_SECRET

# 5. 创建 KV namespace（如需重新创建）
npx wrangler kv namespace create SUBSCRIBE_KV
# 将返回的 id 填入 wrangler.jsonc

# 6. 绑定自定义域名
# CF Dashboard -> Workers & Pages -> trade-data-signal -> Settings -> Triggers -> Custom Domains
# 添加 ss.fx8.store
```

---

## 7. 多域名配置

| 域名 | 托管平台 | 仓库 | 部署方式 | 特性 | 限制 |
|---|---|---|---|---|---|
| `ss.fx8.store` | CF Workers | xp13465/trade-data-signal | push main → GH Actions → wrangler deploy | br 压缩 / _headers 生效 / R2 binding / KV / server:cloudflare | - |
| `sss.sugas.site` | GitHub Pages | xp13465/trade-data-signal | push main → GH Actions deploy-pages | 原生 GH Pages / max-age=600 | 无 Worker（无 /api/ / /r2/） |
| `s.sugas.site` | MaoziYun | - | 手动/FTP | HSTS 自带 | **300MB 总大小限制**（超了拒绝部署 404） |
| `ssd.fx8.store` | R2 Public Bucket | - | upload_r2.py 上传 | 大 JSON 直链 / cf-cache DYNAMIC | 无 Worker 逻辑 |

### 验证优先级

1. `ss.fx8.store`（CF 主站，优先验证）
2. `sss.sugas.site`（GH Pages 备站）
3. `ssd.fx8.store`（R2 直链，验大文件）
4. `s.sugas.site`（MaoziYun，有 300MB 限制，最后兜底）

> 3 域名任一验证到新版即算上线 OK，不卡单域名 404。

### s.sugas.site 瘦身注意

s.sugas.site 有 300MB 总大小限制。`static-site/data/` 已移出 git（走 R2），不推 s.sugas.site。s.sugas.site 仅作兜底镜像（从 git main 拉 static-site/ 代码 + min JS/CSS）。

---

## 8. 定时任务

### 8.1 launchd 任务清单

所有 plist 在 `~/Library/LaunchAgents/com.trade.*.plist`。`REPO` 环境变量指向 `/Users/linhuichen/code/trade-data`（采集 cwd），`GIT_REPO` 指向 `/Users/linhuichen/code/trade`（git push cwd）。

| 任务 | Label | 时点（CST） | 脚本 | 用途 | push main |
|---|---|---|---|---|---|
| 主采集 | com.trade.update-all | 17:50 | update_all.sh | 4 pipeline 并行采集+计算+导出+部署 | 是（deploy.sh） |
| 盘中快照 | com.trade.intraday-snapshot | 09:25-15:02 每10min + 15:35 + 20:35 | intraday_snapshot.sh | 盘中实时快照推 main | 是（独立 worktree push） |
| 指数回填 | com.trade.backfill-evening | 16:35, 21:00, 02:00 | backfill_indices.sh | 多源补采缺失指数 | 是（deploy.sh） |
| ETF 国家队 | com.trade.etf-national-team | 20:07, 21:30 | etf_national_team_backfill.sh | ETF 国家队资金采集 | 是（deploy.sh） |
| ETF 跟踪指数 | com.trade.etf-track-index | 周日 03:30 | fetch_etf_track_index.py | ETF 跟踪指数映射刷新 | 否（写 data/） |
| 期货回填 | com.trade.futures-backfill | 20:05, 21:00 | futures_backfill.sh | 中金所期货持仓补采 | 是（deploy.sh） |
| 夜盘黄金 | com.trade.gold-night | 02:40 | gold_night.sh | 夜盘黄金/白银采集 | 是（deploy.sh） |
| 策略实验室 | com.trade.lab-auto | 19:00 | update_lab.sh | 策略实验室回测 | 是（deploy.sh） |
| 龙虎榜回填 | com.trade.lhb-backfill | 18:30, 19:30 | lhb_backfill.sh | 龙虎榜数据补采 | 是（deploy.sh） |
| 公募评分(日) | com.trade.pf-score-daily | 16:00 | pf_score_daily.sh | 公募基金每日评分 | 否（写 DB） |
| 公募评分(周) | com.trade.pf-score-weekly | 周日 03:17 | pf_score_weekly.sh | 公募基金周度评分 | 否（写 DB） |
| 公募阶段0-经理 | com.trade.pf-stage0-manager | 每月1日 02:47 | stage0_manager.sh | 基金经理数据采集 | 否（写 DB） |
| 公募阶段0-净值 | com.trade.pf-stage0-nav | 周五 01:43 | stage0_nav.sh | 基金净值采集 | 否（写 DB） |
| 公募阶段0-概览 | com.trade.pf-stage0-overview | 周日 02:17 | stage0_overview.sh | 基金概览采集 | 否（写 DB） |
| 公募阶段0-风险 | com.trade.pf-stage0-risk | 每月15日 02:33 | stage0_risk.sh | 基金风险指标采集 | 否（写 DB） |
| 公募日更 | com.trade.public-fund-daily | 16:30, 17:00 | public_fund_daily.sh | 公募基金每日数据 | 是（deploy.sh） |
| 公募估值 | com.trade.public-fund-estimation | 10:00, 11:00, 13:30, 14:30 | public_fund_estimation.sh | 盘中基金估值 | 否（写 DB） |
| 公募全量 | com.trade.public-fund-full | 22:00 | public_fund_full.sh | 公募基金全量采集 | 否（写 DB） |
| 公募季报 | com.trade.public-fund-quarterly | 03:00, 04:00, 07:00 | public_fund_quarterly.sh | 季报数据采集 | 否（写 DB） |
| 两融回填 | com.trade.rzhb-backfill | 08:00, 19:15 | rzhb_backfill.sh | 融资融券数据补采 | 是（deploy.sh） |
| 调度监控 | com.trade.schedule-monitor | 每15min（:00,:15,:30,:45） | schedule_monitor.sh | 监控所有任务执行状态+告警 | 否 |
| 自愈 | com.trade.self-heal | 每15min（:07,:22,:37,:52） | self_heal.sh | 盘中保护 update_all + 异常恢复 | 否 |
| 美股晨报 | com.trade.us-stock-morning | 05:00 | us_stock_morning.sh | 美股/全球指数采集 | 是（deploy.sh） |

### 8.2 任务冲突时点（push main 安全窗口）

**危险时点**（多任务推 main 可能互相覆盖）：
- 15:35 / 20:35（intraday-snapshot 推 main）
- 16:35 / 21:00 / 02:00（backfill-evening 推 main）
- 17:50（update-all 推 main）
- 20:05 / 21:00（futures-backfill 推 main）
- 18:30 / 19:30（lhb-backfill 推 main）
- 19:00（lab-auto 推 main）
- 20:07 / 21:30（etf-national-team 推 main）
- 08:00 / 19:15（rzhb-backfill 推 main）

**安全窗口**：23:00 后无推 main 任务（3:17 weekly 周日才跑，5:00 us-stock-morning 不写 public_fund.db）。盘中 push 前端代码避开 intraday 每 10 分钟时点（:25/:35/:45/:55/:05/:15），选 :00/:10/:20/:30/:40/:50 之外或等盘后 23:00+ 窗口。

### 8.3 安装定时任务

```bash
# plist 模板在 scripts/plists/（部分）
# 或从现有 ~/Library/LaunchAgents/ 复制

# 加载任务
launchctl load ~/Library/LaunchAgents/com.trade.update-all.plist

# 卸载任务
launchctl unload ~/Library/LaunchAgents/com.trade.update-all.plist

# 查看已加载任务
launchctl list | grep trade

# 查看任务状态（PID 为 - 表示未在运行，退出码 0 表示上次成功）
launchctl list | grep com.trade.update-all
```

> **plist 含机器绝对路径**（`/Users/linhuichen/code/trade-data/scripts/...`），每台机器需修改路径后加载。plist 本身不进 git（`scripts/plists/` 已 .gitignore，部分历史 plist tracked）。

### 8.4 deploy.sh 互斥机制

- `update_all.sh` 通过 `with_lock.py --nb`（fcntl.flock 非阻塞独占锁）串行化，重复跑自动跳过
- `intraday_snapshot.sh` 和 deploy 的 git commit/push 经 `/tmp/trade_deploy.lock` 串行，避免 git index.lock 冲突
- 盘中（09:30-15:30）deploy.sh 拒跑全量 export（防覆盖 intraday 实时版），`force` 参数可绕过

---

## 9. 重建步骤（从零搭建）

### 步骤 1：克隆代码

```bash
cd /Users/linhuichen/code
git clone git@github.com:xp13465/trade-data-signal.git trade
cd trade
```

### 步骤 2：创建 trade-data 工作目录

```bash
cd /Users/linhuichen/code
mkdir trade-data
cd trade-data

# 创建 symlink（复用 trade 代码）
ln -s /Users/linhuichen/code/trade/app app
ln -s /Users/linhuichen/code/trade/scripts scripts
ln -s /Users/linhuichen/code/trade/config config

# 创建数据/日志目录
mkdir -p data/logs data/backups static-site/data
```

### 步骤 3：安装 Python 依赖

```bash
cd /Users/linhuichen/code/trade-data
python3 -m venv .venv
.venv/bin/pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r /Users/linhuichen/code/trade/requirements.txt
```

### 步骤 4：配置密钥

```bash
# trade/.env（R2 凭证）
cd /Users/linhuichen/code/trade
cat > .env << 'EOF'
# Cloudflare R2 (S3 兼容)
R2_BUCKET=signal-data
R2_S3_ACCESS_KEY_ID=<填入>
R2_S3_SECRET_ACCESS_KEY=<填入>
R2_S3_ENDPOINT=https://<ACCOUNT_ID>.r2.cloudflarestorage.com
R2_PUBLIC_DOMAIN=https://ssd.fx8.store
EOF

# trade-data/.env（运行时密钥）
cd /Users/linhuichen/code/trade-data
cat > .env << 'EOF'
DEEPSEEK_API_KEY=<填入>
DEEPSEEK_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
DEEPSEEK_MODEL=<填入>
PURGE_SECRET=<填入>
EOF

# config/ 配置文件（从 .example 复制）
cd /Users/linhuichen/code/trade
cp config/email.json.example config/email.json    # 编辑填入 SMTP
cp config/telegram.json.example config/telegram.json  # 编辑填入 bot token
cp config/subscriptions.json.example config/subscriptions.json
```

### 步骤 5：初始化数据库

```bash
cd /Users/linhuichen/code/trade
.venv/bin/python -m app.db    # 建表

# 或从 R2 备份恢复（如已有历史数据）
.venv/bin/python scripts/upload_r2.py download-db sentiment.db
cp /tmp/restore/sentiment_*.db /Users/linhuichen/code/trade-data/data/sentiment.db
# 同理恢复 etf_national_team.db + public_fund.db
```

### 步骤 6：首次回填历史数据

```bash
cd /Users/linhuichen/code/trade
# 全量回填（mootdx 全 A 股日线 + BaoStock 校验，耗时数小时）
.venv/bin/python -m app.backfill
```

### 步骤 7：配置 Cloudflare

```bash
# 1. 安装 wrangler
npm install -g wrangler  # 或用 npx

# 2. 登录
npx wrangler login

# 3. 创建 R2 buckets
npx wrangler r2 bucket create signal-data
npx wrangler r2 bucket create signal-backup

# 4. 设置 R2 公开访问（CF Dashboard）
#    R2 -> signal-data -> Settings -> Public access -> 绑定 ssd.fx8.store

# 5. 创建 R2 API Token（S3 兼容）
#    R2 -> Manage R2 API Tokens -> Create -> Object Read & Write
#    填入 trade/.env

# 6. 创建 KV namespace
npx wrangler kv namespace create SUBSCRIBE_KV
#    将返回的 id 填入 wrangler.jsonc

# 7. 设置 wrangler secrets
npx wrangler secret put PURGE_SECRET
npx wrangler secret put SUBSCRIBE_PASSWORD
npx wrangler secret put GITEE_CLIENT_ID
npx wrangler secret put GITEE_CLIENT_SECRET
npx wrangler secret put GITEE_REDIRECT_URI
npx wrangler secret put SESSION_SECRET

# 8. 设置 GH Actions secret
#    GitHub repo -> Settings -> Secrets -> Actions -> CLOUDFLARE_API_TOKEN

# 9. 绑定自定义域名
#    CF Dashboard -> Workers & Pages -> trade-data-signal -> Triggers -> Custom Domains -> ss.fx8.store
```

### 步骤 8：首次导出 + 部署

```bash
cd /Users/linhuichen/code/trade-data

# 1. 导出 JSON
/Users/linhuichen/code/trade/.venv/bin/python static-site/export.py

# 2. build min JS/CSS
/Users/linhuichen/code/trade/.venv/bin/python /Users/linhuichen/code/trade/scripts/build_min.py

# 3. bump 版本号
/Users/linhuichen/code/trade/.venv/bin/python /Users/linhuichen/code/trade/scripts/bump_asset_version.py

# 4. rsync 到 trade 仓库
rsync -a --checksum static-site/data/ /Users/linhuichen/code/trade/static-site/data/

# 5. 上传 R2
/Users/linhuichen/code/trade/.venv/bin/python /Users/linhuichen/code/trade/scripts/upload_r2.py upload-all-data
/Users/linhuichen/code/trade/.venv/bin/python /Users/linhuichen/code/trade/scripts/upload_r2.py upload-lab
/Users/linhuichen/code/trade/.venv/bin/python /Users/linhuichen/code/trade/scripts/upload_r2.py upload-index
/Users/linhuichen/code/trade/.venv/bin/python /Users/linhuichen/code/trade/scripts/upload_r2.py upload-industry
/Users/linhuichen/code/trade/.venv/bin/python /Users/linhuichen/code/trade/scripts/upload_r2.py upload-data-large

# 6. git push 上线
cd /Users/linhuichen/code/trade
git add static-site/
git commit -m "initial deploy"
git push origin main
# -> GH Actions 自动跑 wrangler deploy + GH Pages deploy
```

### 步骤 9：配置定时任务

```bash
# 复制 plist 到 LaunchAgents（修改路径为新机器路径）
cp scripts/plists/*.plist ~/Library/LaunchAgents/
# 或手动创建 plist（参考现有 plist 结构）

# 加载所有任务
for plist in ~/Library/LaunchAgents/com.trade.*.plist; do
  launchctl load "$plist"
done

# 验证
launchctl list | grep trade
```

### 步骤 10：验证

```bash
# 验证 CF Workers
curl -sI https://ss.fx8.store/ | grep -i "server\|cf-"
curl -s https://ss.fx8.store/data/overview.json | python3 -m json.tool | head -5

# 验证 GH Pages
curl -sI https://sss.sugas.site/ | grep -i "x-pages"

# 验证 R2
curl -sI https://ssd.fx8.store/data/overview.json | grep -i "cf-cache"

# 验证 DB
sqlite3 /Users/linhuichen/code/trade-data/data/sentiment.db "SELECT COUNT(*) FROM daily_metric;"

# 验证定时任务
launchctl list | grep trade
```

---

## 10. 灾备镜像搭建

### 10.1 目标

在第二台机器（不同域名/不同网络环境）搭建完整镜像，数据从 git + R2 备份恢复，实现异地灾备。

### 10.2 搭建步骤

1. **按第 9 节完整重建**，但使用不同域名（如 `ss2.example.com`）
2. **CF Workers 配置**：新建 Worker（如 `trade-data-signal-backup`），绑定新域名，wrangler.jsonc 修改 `name` 字段
3. **数据恢复**：
   - DB 从 R2 `signal-backup` 桶下载最新备份（`upload_r2.py download-db`）
   - static-site/data 从 R2 `signal-data` 桶恢复（upload_r2.py upload-all-data 重新填充）+ staticdata git 恢复小 JSON
4. **定时任务**：加载相同 plist（修改路径），可错开时点避免与主站同时采集（或只做备份不采集）
5. **R2 共享**：灾备机可共用同一 R2 bucket（只读），或创建独立 bucket 定期同步

### 10.3 数据备份源

| 数据类型 | 备份位置 | 恢复方式 |
|---|---|---|
| 代码 | GitHub 仓库 `xp13465/trade-data-signal` | `git clone` |
| DB | R2 `signal-backup` 桶（日/周/月三层） | `upload_r2.py download-db` |
| 静态 JSON（小） | R2 `signal-data` 桶 + staticdata git | `upload_r2.py list data/` 或 `git pull` staticdata |
| 静态 JSON（大） | R2 `signal-data` 桶 | `upload_r2.py list` + 下载 |
| 配置 | `.example` 模板 + 手动填入 | `cp *.example *.json` |
| Claude 配置 | R2 `signal-backup/claude-backup/` | `upload_r2.py upload-claude-backup` |

### 10.4 静态数据备份仓库（staticdata）

`git@github.com:xp13465/trade-data-signal-staticdata.git`，本地路径 `/Users/linhuichen/code/trade-data-signal-staticdata`。

deploy.sh 每次 deploy 后自动备份（best-effort，失败不阻塞 deploy）：
- **DB 原件** rsync 到 `staticdata/db/`（本地备份，不进 git，GitHub 100MB 限制）
- **配置**（wrangler.jsonc + launchd plist 脱敏）cp 到 `staticdata/config/`
- **全量 JSON** rsync 到 `staticdata/data/`（git diff 追踪每日变化）
- **git commit + push** 差异化日志（`data backup [deploy] YYYY-MM-DD_HH:MM`）

> 此仓库为灾备第 2 层（差异化日志），不替代 R2 备份（第 3/4 层）。DB 因 >100MB 不进 git，仅 rsync 本地 + R2 signal-backup 私有桶 gz 快照异地备份。详见 [r2-deployment.md 第 6 节](r2-deployment.md#6-staticdata-git-备份)。

---

## 11. 排障

### 11.1 CF Workers 缓存问题

| 症状 | 原因 | 解决 |
|---|---|---|
| 改了 JS 但用户看到旧版 | Service Worker CacheFirst 缓存旧 app.min.js | bump `sw.js` 的 `CACHE_VERSION` + `build_min.py` + `bump_asset_version.py` 三步 |
| index.html 被 CDN 缓存旧版 | CF Workers Static Assets 无视 no-cache/private 仍 HIT | worker/headers.js 已改 `no-store, max-age=0`（HTML 入口） |
| overview.json 盘中看到昨日值 | CF edge 60s 窗口缓存 | worker/headers.js 已改 `no-store`（overview/intraday_snapshot） |
| 大 JSON 404（ss.fx8.store） | CF Workers Static Assets 25MB 限制 | 大文件走 R2（ssd.fx8.store 或 Worker /r2/ 代理） |

### 11.2 R2 问题

| 症状 | 原因 | 解决 |
|---|---|---|
| R2 上传失败 | .env 凭证错误/过期 | 检查 R2_S3_ACCESS_KEY_ID/SECRET_ACCESS_KEY/ENDPOINT |
| R2 直链 DYNAMIC 每次回源 ~1s | public bucket 无边缘缓存 | 阶段 P0-4 已改走 Worker /r2/ 代理（Cache API 边缘缓存） |
| upload_r2.py 卡 TCP SYN_SENT | 网络问题 | deploy.sh 内置超时 kill（R2_UPLOAD_TIMEOUT=300s） |
| s.sugas.site 404 | 超 300MB 限制 | 大文件移出走 R2，控制 static-site/data/ 总量 |

### 11.3 DB 问题

| 症状 | 原因 | 解决 |
|---|---|---|
| `database disk image is malformed` | DB 文件损坏 | 从 R2 备份恢复（见第 4.6 节） |
| 切分支后 DB 被覆盖 | DB 曾 tracked（已根治） | DB 已 untracked，不会再发生；如误 `git add data/*.db`，`git rm --cached` |
| 采集写入 trade/data/ 而非 trade-data/data/ | cwd 错误 | uvicorn cwd 必须是 trade-data/（symlink 让代码复用但 DB 路径不同） |
| WAL/SHM 冲突 | 恢复后旧 WAL 未删 | 恢复后 `rm -f data/*.db-wal data/*.db-shm` |

### 11.4 定时任务撞车

| 症状 | 原因 | 解决 |
|---|---|---|
| git push non-fast-forward | 多任务同时推 main | deploy.sh 经 flock 串行化；避开危险时点（见第 8.2 节） |
| intraday_snapshot 被全量 deploy 覆盖 | 盘中跑全量 export | deploy.sh 盘中闸门（09:30-15:30 拒跑，force 可绕过） |
| update_all 漏跑 | Mac 休眠 | `pmset` 工作日 17:48 唤醒 + `caffeinate` 防跑期间睡 |
| git index.lock 冲突 | 多进程同时 git commit | flock /tmp/trade_deploy.lock 串行化 |

### 11.5 deploy.sh 常见失败

| 症状 | 原因 | 解决 |
|---|---|---|
| build_board_etf_map.py 失败阻断 | akshare 反爬/网络 | 14 宽基校验未过，检查 akshare 连通性 |
| check_data_integrity.py 阻断 | 数据产物异常（空 map/爆炸值/丢失） | 检查 export.py 输出，修复数据源 |
| rebase 失败 | 工作区有 unmerged 文件 | deploy.sh 自动清理数据文件 unmerged；代码文件 unmerged 需手动解决 |
| rsync 不同步 | trade-data/static-site/data/ ≠ trade/static-site/data/ | export 后手动 rsync 或确认 deploy.sh rsync 步骤执行 |

---

## 12. 线上验证

### 12.1 三域名验证

```bash
# 1. CF Workers 主站（优先）
curl -sI https://ss.fx8.store/ | grep -i "server\|cf-cache\|content-encoding"
#   期望：server: cloudflare / content-encoding: br

curl -s https://ss.fx8.store/data/overview.json | python3 -c "import sys,json; d=json.load(sys.stdin); print('date:', d.get('date','')); print('keys:', len(d.keys()))"
#   期望：date=今日 / keys>20

# 2. GH Pages 备站
curl -sI https://sss.sugas.site/ | grep -i "x-pages\|server"
curl -s https://sss.sugas.site/data/overview.json | python3 -c "import sys,json; d=json.load(sys.stdin); print('date:', d.get('date',''))"

# 3. R2 直链（大文件）
curl -sI https://ssd.fx8.store/data/a-stock-all.json | grep -i "cf-cache\|content-length"
#   期望：content-length > 0

# 4. MaoziYun 备站（300MB 限制）
curl -sI https://s.sugas.site/ | grep -i "server\|http"
```

### 12.2 JSON 数据层验证（功能生效层）

> 代码在 main + 版本号上线 ≠ 功能生效。必须 curl JSON 验数据层（字段有值/无旧字段残留）。

```bash
# overview.json 关键字段
curl -s https://ss.fx8.store/data/overview.json | python3 -c "
import sys, json
d = json.load(sys.stdin)
print('date:', d.get('date', 'MISSING'))
print('a_amount:', d.get('a_amount', 'MISSING'))
print('amount_forecast:', type(d.get('amount_forecast', {})).__name__, len(d.get('amount_forecast', {})) if isinstance(d.get('amount_forecast'), dict) else 'N/A')
print('signals_today:', len(d.get('signals_today', [])))
"

# intraday_snapshot.json 盘中时效
curl -s https://ss.fx8.store/data/intraday_snapshot.json | python3 -c "
import sys, json
d = json.load(sys.stdin)
print('collected_at:', d.get('collected_at', 'MISSING'))
print('global_realtime:', len(d.get('global_realtime', [])))
"

# board_etf_map.json 非空校验
curl -s https://ss.fx8.store/data/board_etf_map.json | python3 -c "
import sys, json
d = json.load(sys.stdin)
empty = sum(1 for v in d.values() if not v)
total = len(d)
print(f'空数组: {empty}/{total} ({empty/total*100:.0f}%)')
# 期望：空数组占比 < 30%
"

# etf_score_list（R2 托管）
curl -s https://ssd.fx8.store/data/etf_score_list_buy.json | python3 -c "
import sys, json
d = json.load(sys.stdin)
print('buy signals:', len(d) if isinstance(d, list) else 'not a list')
"
```

### 12.3 PWA / Service Worker 验证

```bash
# sw.js 版本号
curl -s https://ss.fx8.store/sw.js | grep "CACHE_VERSION"
#   期望：版本号与最新代码一致

# manifest.json
curl -s https://ss.fx8.store/manifest.json | python3 -m json.tool | head -5
```

### 12.4 回归 smoke 清单

详见 [docs/smoke-checklist.md](smoke-checklist.md)，包含 P0/P1 主功能点清单 + 数据校验规则。

---

## 附录 A：关键文件速查

| 文件 | 用途 |
|---|---|
| `wrangler.jsonc` | CF Workers 配置（assets + R2 + KV binding） |
| `worker/headers.js` | Worker 脚本（cache + /r2/ + /data/ + /api/） |
| `static-site/_headers` | 安全头+缓存分层（Worker 接管时回退） |
| `static-site/sw.js` | Service Worker（PWA 离线缓存） |
| `static-site/export.py` | SQLite -> JSON 导出脚本 |
| `scripts/deploy.sh` | 全量导出+R2上传+git push 部署 |
| `scripts/update_all.sh` | 主采集（4 pipeline 并行） |
| `scripts/intraday_snapshot.sh` | 盘中快照（每10min push main） |
| `scripts/upload_r2.py` | R2 上传/下载（15+命令） |
| `scripts/backup_db.sh` | DB 热备 + R2 异地 |
| `scripts/build_min.py` | terser minify JS/CSS |
| `scripts/bump_asset_version.py` | md5 破缓存 |
| `scripts/check_data_integrity.py` | 数据产物校验（deploy 前置） |
| `.github/workflows/deploy-cf.yml` | GH Actions CF Workers 部署 |
| `.github/workflows/deploy-pages.yml` | GH Actions GH Pages 部署 |
| `config/indicators.yaml` | 指标注册表 |
| `.env` / `.env.example` | R2 凭证 / OAuth 模板 |
| `docs/backup-restore.md` | DB 备份与恢复手册 |
| `docs/data-dictionary.md` | JSON 数据字段说明 |
| `docs/data-sources.md` | 数据源说明 |
| `docs/smoke-checklist.md` | 主功能回归清单 |

## 附录 B：相关文档

- [DB 备份与恢复手册](backup-restore.md) - 三层备份 + 恢复流程
- [数据字典](data-dictionary.md) - static-site/data/ JSON 字段说明
- [数据源说明](data-sources.md) - akshare/mootdx/baostock 等
- [Smoke 清单](smoke-checklist.md) - 主功能回归验证
- [static-site/DEPLOY.md](../static-site/DEPLOY.md) - 旧版静态部署说明（已过时，参考用）
- [R2 部署文档](r2-deployment.md) - R2 数据层完整架构 + 重建步骤 + 排障
