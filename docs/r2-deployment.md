# R2 部署文档（r2-deployment.md）

> 完整 R2 数据层架构 + 从零重建/灾备指南。R2 迁移阶段 1a-5 已全部上线 main（2026-08-08）。
> 本文档方便他人用 git 代码项目重建 R2 数据层。

---

## 目录

1. [架构总览](#1-架构总览)
2. [R2 binding 配置](#2-r2-binding-配置)
3. [Worker /data/ rewrite + /api/purge-cache + 分层 TTL](#3-worker-data-rewrite--apipurge-cache--分层-ttl)
4. [upload_r2.py 命令清单](#4-upload_r2py-命令清单)
5. [定时任务双写](#5-定时任务双写)
6. [staticdata git 备份](#6-staticdata-git-备份)
7. [重建步骤](#7-重建步骤)
8. [排障](#8-排障)

---

## 1. 架构总览

### 1.1 核心原则：git 代码 / R2 数据解耦

```
┌──────────────────────────────────────────────────────────────┐
│                    trade git 仓库（主仓库）                     │
│  代码：app/ scripts/ static-site/源码 worker/ wrangler.jsonc   │
│  不含 data/（已 .gitignore，static-site/data/* 全部移出 git）   │
│  唯一保留：static-site/data/feed.xml（RSS，非 JSON 不走 R2）    │
└──────────────────┬───────────────────────────────────────────┘
                   │ export.py 生成 JSON -> upload_r2.py 推 R2
                   ▼
┌──────────────────────────────────────────────────────────────┐
│              R2 signal-data 公开桶（线上分发）                  │
│  前端 fetch /data/*.json -> Worker /data/ rewrite -> R2 直读    │
│  前端 fetch /r2/{prefix}/ -> Worker /r2/ 代理 -> R2 直读        │
│  所有线上静态资源：小 JSON + 大文件（index/industry/lab/...）   │
└──────────────────────────────────────────────────────────────┘
```

**数据唯一走 R2**：`static-site/data/` 已移出 git（`.gitignore` catch-all `static-site/data/*` + `!feed.xml`），R2 是线上数据的唯一来源。前端所有 `/data/*.json` 请求经 Worker `/data/` rewrite 路由到 R2 binding 直读，URL 零改动。

### 1.2 灾备 4 层分工

| 层 | 存储 | 内容 | 用途 |
|---|---|---|---|
| ① trade git | GitHub `xp13465/trade-data-signal` | 代码（app/scripts/static-site源码/worker/wrangler.jsonc），不含 data/ | 代码版本管理 |
| ② staticdata git | GitHub `xp13465/trade-data-signal-staticdata` | 差异日志：DB 原件（本地 rsync，不进 git）+ 配置（脱敏 .env.example/wrangler.jsonc/launchd plist）+ 小 JSON（git diff 追踪每日变化） | 看变化历史（git diff） |
| ③ R2 signal-backup 私有桶 | R2（不绑公开域名） | 备份快照压缩：DB gz 分层（backup/30 天 + weekly/28 天 + monthly/365 天）+ Claude 自我备份 | 全量恢复（解压快照） |
| ④ R2 signal-data 公开桶 | R2（ssd.fx8.store 直链 + Worker binding） | 线上静态资源分发：所有线上用的静态资源（小 JSON + 大文件 index/industry/lab/trade_sim/public_fund） | 前端 fetch |

**脚本生成文件去向规则**：
- 小文件 -> staticdata git（差异日志）+ R2 公开桶（分发）两处
- 大文件 -> 只 R2 公开桶（不进 staticdata，体量大 git 不适合）

**互补不重复**：staticdata 看变化历史（git diff），signal-backup 恢复全量（解压快照），R2 公开桶线上分发。

### 1.3 DB 备份方案

DB 原件（sentiment.db 125MB / etf_national_team.db 179MB / public_fund.db 2.2GB）超 GitHub 100MB 限制，且 sqlite 二进制 git diff 无差异化日志价值。**DB 只靠 R2 signal-backup 私有桶异地备份**（gz 分层 30 daily + 28 weekly + 365 monthly 全量恢复）+ 本地双副本（trade/data 主库 + staticdata/db rsync，同 Mac 防误删不防硬盘挂）。

---

## 2. R2 binding 配置

### 2.1 wrangler.jsonc

```jsonc
{
  "r2_buckets": [
    { "binding": "R2_BUCKET", "bucket_name": "signal-data" }
  ]
}
```

Worker 通过 `env.R2_BUCKET.get(key)` 直读 R2 对象，无需经过公开域名。`run_worker_first: true` 确保 Worker 在 Static Assets 之前执行，接管 `/data/*.json` 路由。

### 2.2 R2 S3 凭证（.env）

upload_r2.py 使用 S3 兼容 API（SigV4 签名，不依赖 boto3/awscli），凭证从 `.env` 读取：

```bash
# Cloudflare R2 (S3 兼容) - 本地凭证不进 git
R2_BUCKET=signal-data
R2_S3_ACCESS_KEY_ID=<R2 Access Key ID>
R2_S3_SECRET_ACCESS_KEY=<R2 Secret Access Key>
R2_S3_ENDPOINT=https://<ACCOUNT_ID>.r2.cloudflarestorage.com
R2_PUBLIC_DOMAIN=https://ssd.fx8.store
# 备份用独立私有桶（不绑公开域名）
R2_BACKUP_BUCKET=signal-backup
```

### 2.3 PURGE_SECRET

Worker `/api/purge-cache` 接口认证密码，需同时在两处配置：

1. **Worker 侧**（CF Dashboard）：`npx wrangler secret put PURGE_SECRET`
2. **本地 .env**（upload_r2.py 调用 purge_cache 时读）：`PURGE_SECRET=<同上>`

### 2.4 Bucket 清单

| Bucket | 可见性 | 用途 | 绑定 |
|---|---|---|---|
| `signal-data` | 公开（ssd.fx8.store 直链 + Worker binding） | 线上数据文件（JSON/HTML） | wrangler.jsonc `R2_BUCKET` |
| `signal-backup` | 私有（不绑域名） | DB 备份 + Claude 自我备份 | upload_r2.py `BACKUP_BUCKET` |

### 2.5 创建 R2 Bucket

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

## 3. Worker /data/ rewrite + /api/purge-cache + 分层 TTL

worker/headers.js 实现三条 R2 路由 + 缓存分层。

### 3.1 /data/*.json rewrite（阶段 2，已上线）

```
前端 fetch /data/overview.json
  -> Worker dataRewriteHandler
  -> Cache API 边缘缓存命中？-> 返回缓存
  -> R2 binding env.R2_BUCKET.get("data/overview.json")
  -> R2 有对象？-> 构造响应 + 分层 TTL + 写边缘缓存
  -> R2 404/错误？-> 回退 ASSETS（静态文件兜底）
```

- **R2 key** = pathname.slice(1)（如 `/data/overview.json` -> `data/overview.json`）
- **边缘缓存 key** 用 pathname（剥离 `?_=Date.now()` cache-bust，带 query 的请求也命中）
- **R2 404 回退 ASSETS**：如 `fund_score_top.json` R2 key 在 `fund_score/` 前缀，`/data/` 404 回退静态文件
- **只缓存 200 响应**：非 200 不写边缘缓存

### 3.2 分层 TTL（dataCacheTtl 函数）

| TTL | 更新频率 | 匹配文件 |
|---|---|---|
| 60s | 盘中高频 | overview/intraday_snapshot/boot/notifications/summary/summary_history/schedule_stats/alert + `-(1m\|3m\|6m\|1y).json` + futures/ad_line/new_high_low/position/rotation/volume_ratio/ma_alignment/signal_freq/etf_national_team_holders/etf_national_team_quarterly/global-extras-all |
| 600s | 每日更新 | signal_stats/daily_metric/futures_acc_trend/futures_acc_conclusion/fund_score_top/trade_sim_indices |
| 3600s | 历史低频 | 兜底（收盘后更新一次的文件） |

### 3.3 /r2/* 代理路由（P0-4）

```
前端 fetch /r2/index/sh000001-all.json
  -> Worker r2ProxyHandler
  -> Cache API 边缘缓存命中？-> 返回缓存
  -> R2 binding env.R2_BUCKET.get("index/sh000001-all.json")
  -> 构造响应 + Cache-Control: public, max-age=3600 + 写边缘缓存
```

- **R2 key** = pathname.slice(4)（去掉 `/r2/` 前缀）
- **替代原 ssd.fx8.store public bucket 直链**（cf-cache-status DYNAMIC 每次回源 ~1s），二次请求边缘 HIT ~50ms
- **所有走 R2 的数据**（大 range 历史 / etf_score / index / industry / lab / public_fund / fund_score / trade_sim）均为收盘后低频更新，1h 边缘缓存安全

### 3.4 /api/purge-cache（阶段 2，已上线）

```
upload_r2.py 上传新数据后调 POST /api/purge-cache
  -> Worker purgeCacheHandler
  -> 验证 body.secret === env.PURGE_SECRET
  -> 遍历 body.keys，调 caches.default.delete(cacheKey)
  -> 返回 { purged, total }
```

- **body 格式**：`{ "secret": "xxx", "keys": ["/data/overview.json", ...] }`
- **PURGE_SECRET 未设**：upload_r2.py 跳过 purge（Worker 返回 403）
- **purge 失败不中断上传流程**（purge 是次要操作，上传是主要操作）

### 3.5 前端 R2 访问方式（最终态）

| 数据类型 | 前端访问方式 | Worker 路由 |
|---|---|---|
| 小 JSON（overview/intraday/summary 等） | `fetchJSON('/data/xxx.json')` | `/data/` rewrite -> R2 binding |
| 大 range 历史（`*-(all\|5y\|3y).json`） | `dataUrl()` helper -> `/data/` rewrite | `/data/` rewrite -> R2 binding |
| index/industry/lab/trade_sim/public_fund | 硬编码 `https://ssd.fx8.store/{prefix}/` URL | R2 公开桶直链 |
| 大文件 R2 代理（P0-4 优化） | `https://ss.fx8.store/r2/{prefix}/` | `/r2/` 代理 -> R2 binding + 边缘缓存 |

---

## 4. upload_r2.py 命令清单

`scripts/upload_r2.py` 使用 Python 标准库 SigV4 签名（不依赖 boto3/awscli），凭证从 `.env` 读取。

### 4.1 数据上传命令

| 命令 | 上传内容 | R2 前缀 | 用途 |
|---|---|---|---|
| `upload-lab` | lab/*.json | `lab/` | 策略实验室数据 |
| `upload-trade-sim` | trade_sim_*.html | `trade_sim/` | 回测 HTML 页面 |
| `upload-trade-sim-json` | trade_sim_*_stats.json + _full.json | `trade_sim_data/` | 回测统计数据 |
| `upload-index` | data/index/*.json | `index/` | 44 指数全历史 |
| `upload-industry` | data/industry-* | `industry/` | 行业数据（拆分目录+单文件） |
| `upload-public-fund` | data/public_fund* | `public_fund/` | 公募基金数据 |
| `upload-offshore-fund` | data/offshore_fund* | `offshore_fund/` | 场外基金数据 |
| `upload-fund-score` | data/fund_score* | `fund_score/` | 基金评分 |
| `upload-etf-score` | data/etf_score_list_*.json | `data/` | ETF 评分（buy/sell/hold） |
| `upload-data-large` | data/ 顶层 >=1MB 或大 range .json | `data/` | 大 JSON（all/5y/3y 等） |
| `upload-all-data` | data/ 全量小 .json | `data/` | 全量小文件双写（排除已走独立命令的） |
| `upload-intraday` | intraday 相关 23 文件 | `data/` | 盘中实时快照 |
| `upload-data-files <f1> [f2]...` | 指定文件列表 | `data/` | 精准上传指定文件 |

### 4.2 备份命令

| 命令 | 上传内容 | R2 前缀 | 桶 | 用途 |
|---|---|---|---|---|
| `upload-db` | sentiment.db + etf_national_team.db（gz 压缩） | `backup/` + `weekly/` + `monthly/` | signal-backup | DB 异地备份（日/周/月三层） |
| `upload-claude-backup [path]` | Claude 自我备份 tar.gz | `claude-backup/` | signal-backup | Claude 配置异地备份 |

### 4.3 管理命令

| 命令 | 用途 |
|---|---|
| `list [prefix]` | 列 bucket 对象 |
| `upload <local> <key>` | 上传单文件 |
| `download-db <name> [dir]` | 下载最新 DB 备份（解压后 .db 路径到 stdout） |
| `delete <key> [bucket]` | 删除单 key |
| `clean-data-backup` | 清理 signal-data/backup/ 旧 key |

### 4.4 上传后 purge_cache

`upload-all-data` / `upload-intraday` / `upload-data-files` 上传成功后自动调 `purge_cache()` 清 CF 边缘缓存，让前端下次请求回源 R2 拿最新数据。

### 4.5 并发上传

`_upload_glob` 使用 `ThreadPoolExecutor` 8 线程并发上传，186 文件串行 3-5min -> 并发约 30-60s。单文件失败（重试 5 次仍错）不中断整批，继续上传后续文件。

### 4.6 exclude 规则（避免双副本）

`upload-all-data` 排除已在独立命令处理的文件前缀（和 `upload-data-large` exclude_prefixes 一致）：
- `industry-` / `public_fund` / `offshore_fund` / `fund_score` / `etf_score_list`（各走独立命令）
- 大 range 文件 `*-(all|5y|3y).json`（upload-data-large 已处理）
- `.gz` 不再生成（CF 自动 br 压缩替代）

---

## 5. 定时任务双写

R2 迁移阶段 3 后，定时任务去 git push 数据改 R2 上传 + purge_cache + notify 告警。

### 5.1 deploy.sh（全量部署）

`scripts/deploy.sh` L263-278 调 `run_r2_upload` 跑 10 个 R2 上传命令：

```
upload-lab / upload-trade-sim / upload-trade-sim-json / upload-index /
upload-industry / upload-public-fund / upload-offshore-fund / upload-etf-score /
upload-data-large / upload-all-data
```

- **R2 上传失败不阻断 deploy**：记 `R2_FAIL` 变量，发 notify 告警邮件（`--severe --dedup-key deploy_r2_upload_fail`）
- **超时保护**：`run_r2_upload` 内置 `R2_UPLOAD_TIMEOUT`（默认 300s），超时 kill 释放 deploy.lock
- **git push 只推代码**：`DATA_FILES` 只含 min JS/CSS + feed.xml（阶段 3：数据走 R2，只 push 代码 + RSS）

### 5.2 intraday_snapshot.sh（盘中快照）

`scripts/intraday_snapshot.sh` 盘中每 10 分钟跑，R2 双写：

1. `upload-index`（L131）：同步 index/ 到 R2（走势图源 kc50-all.json 等），失败发告警邮件
2. `upload-intraday`（L144）：同步 23 个 intraday 相关文件到 R2（overview/intraday_snapshot/a-stock 等），失败发告警邮件
3. `upload-data-files schedule_stats.json`（L168）：gen_stats 刷新后上传到 R2 + purge_cache

- **R2 上传失败发告警邮件**（`notify.py --severe --dedup-key intraday_upload_*_r2_fail`），让 schedule_monitor 发现
- **采集器写 REPO/static-site/data/**（trade-data），upload_r2.py 读 REPO（env）直接上传，无需 rsync

### 5.3 其他脚本

| 脚本 | R2 命令 | 用途 |
|---|---|---|
| `gold_night.sh` | upload-data-large + upload-data-files(global-3m/6m/1y) | 夜盘黄金/全球指数 |
| `push_schedule_stats.sh` | upload-data-files(schedule_stats.json) | 调度统计上传 |
| `pf_score_daily.sh` | upload-fund-score | 公募基金每日评分 |
| `pf_score_weekly.sh` | upload-fund-score | 公募基金周度评分 |
| `backup_db.sh` | upload-db | DB 每日异地备份 |

---

## 6. staticdata git 备份

### 6.1 仓库

`git@github.com:xp13465/trade-data-signal-staticdata.git`，本地路径 `/Users/linhuichen/code/trade-data-signal-staticdata`。

### 6.2 deploy.sh 自动备份（L516-564）

每次 deploy 后（best-effort，失败不阻塞 deploy）：

1. **rsync DB 原件**到 `staticdata/db/`（本地备份，不进 git，`.gitignore` 排除 `db/*.db`）
2. **cp 配置**到 `staticdata/config/`：wrangler.jsonc + launchd plist（sed 脱敏 `/Users/linhuichen` -> `/Users/USER`）
3. **rsync 全量 JSON**到 `staticdata/data/`（全量备份，DB 不在此目录）
4. **git commit + push**（差异化日志，`data backup [deploy] YYYY-MM-DD_HH:MM`）

### 6.3 备份内容

| 内容 | 位置 | 进 git | 说明 |
|---|---|---|---|
| DB 原件 | `staticdata/db/*.db` | 否（.gitignore 排除，GitHub 100MB 限制） | 本地双副本防误删 |
| 配置（脱敏） | `staticdata/config/` | 是 | wrangler.jsonc + launchd plist（路径脱敏） |
| 小 JSON | `staticdata/data/` | 是 | git diff 追踪每日变化 |
| 大文件 | 只 R2 公开桶 | 否 | 体量大 git 不适合 |

### 6.4 失败告警

staticdata 备份部分失败（rsync/push 失败）发 notify 告警邮件（`--severe --dedup-key staticdata_backup_fail`），不阻塞 deploy。

---

## 7. 重建步骤

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
R2_BUCKET=signal-data
R2_S3_ACCESS_KEY_ID=<填入>
R2_S3_SECRET_ACCESS_KEY=<填入>
R2_S3_ENDPOINT=https://<ACCOUNT_ID>.r2.cloudflarestorage.com
R2_PUBLIC_DOMAIN=https://ssd.fx8.store
R2_BACKUP_BUCKET=signal-backup
EOF

# trade-data/.env（运行时密钥）
cd /Users/linhuichen/code/trade-data
cat > .env << 'EOF'
DEEPSEEK_API_KEY=<填入>
DEEPSEEK_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
DEEPSEEK_MODEL=<填入>
PURGE_SECRET=<填入（与步骤7 wrangler secret put 一致）>
EOF

# config/ 配置文件（从 .example 复制）
cd /Users/linhuichen/code/trade
cp config/email.json.example config/email.json
cp config/telegram.json.example config/telegram.json
cp config/subscriptions.json.example config/subscriptions.json
```

### 步骤 5：初始化数据库

```bash
cd /Users/linhuichen/code/trade
.venv/bin/python -m app.db    # 建表

# 或从 R2 备份恢复（如已有历史数据）
.venv/bin/python scripts/upload_r2.py download-db sentiment.db
.venv/bin/python scripts/upload_r2.py download-db etf_national_team.db
.venv/bin/python scripts/upload_r2.py download-db public_fund.db
# 恢复到 trade-data/data/<name>.db
```

### 步骤 6：首次回填历史数据

```bash
cd /Users/linhuichen/code/trade
.venv/bin/python -m app.backfill    # 全量回填（耗时数小时）
```

### 步骤 7：配置 Cloudflare（R2 + Worker）

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
#    R2 -> Manage R2 API Tokens -> Create -> Object Read & Write（两个 bucket）
#    填入 trade/.env（步骤4）

# 6. 创建 KV namespace
npx wrangler kv namespace create SUBSCRIBE_KV
#    将返回的 id 填入 wrangler.jsonc

# 7. 设置 wrangler secrets
npx wrangler secret put PURGE_SECRET          # 与 trade-data/.env 一致
npx wrangler secret put SUBSCRIBE_PASSWORD
npx wrangler secret put GITEE_CLIENT_ID
npx wrangler secret put GITEE_CLIENT_SECRET
npx wrangler secret put GITEE_REDIRECT_URI    # https://ss.fx8.store/api/auth/callback/gitee
npx wrangler secret put SESSION_SECRET

# 8. 设置 GH Actions secret
#    GitHub repo -> Settings -> Secrets -> Actions -> CLOUDFLARE_API_TOKEN

# 9. 绑定自定义域名
#    CF Dashboard -> Workers & Pages -> trade-data-signal -> Triggers -> Custom Domains -> ss.fx8.store

# 10. 本地手动部署 Worker（首次，后续 push main 自动）
npx wrangler deploy
```

### 步骤 8：首次导出 + 填充 R2

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

# 5. 首次填充 R2（全量上传所有数据）
/Users/linhuichen/code/trade/.venv/bin/python /Users/linhuichen/code/trade/scripts/upload_r2.py upload-all-data
/Users/linhuichen/code/trade/.venv/bin/python /Users/linhuichen/code/trade/scripts/upload_r2.py upload-lab
/Users/linhuichen/code/trade/.venv/bin/python /Users/linhuichen/code/trade/scripts/upload_r2.py upload-index
/Users/linhuichen/code/trade/.venv/bin/python /Users/linhuichen/code/trade/scripts/upload_r2.py upload-industry
/Users/linhuichen/code/trade/.venv/bin/python /Users/linhuichen/code/trade/scripts/upload_r2.py upload-public-fund
/Users/linhuichen/code/trade/.venv/bin/python /Users/linhuichen/code/trade/scripts/upload_r2.py upload-offshore-fund
/Users/linhuichen/code/trade/.venv/bin/python /Users/linhuichen/code/trade/scripts/upload_r2.py upload-fund-score
/Users/linhuichen/code/trade/.venv/bin/python /Users/linhuichen/code/trade/scripts/upload_r2.py upload-etf-score
/Users/linhuichen/code/trade/.venv/bin/python /Users/linhuichen/code/trade/scripts/upload_r2.py upload-trade-sim
/Users/linhuichen/code/trade/.venv/bin/python /Users/linhuichen/code/trade/scripts/upload_r2.py upload-trade-sim-json
/Users/linhuichen/code/trade/.venv/bin/python /Users/linhuichen/code/trade/scripts/upload_r2.py upload-data-large

# 6. git push 上线（只推代码 + min JS/CSS + feed.xml）
cd /Users/linhuichen/code/trade
git add static-site/app.min.js static-site/lab.min.js static-site/common.min.js \
  static-site/purpose-notes.min.js static-site/style.min.css static-site/lab.min.css \
  static-site/data/feed.xml
git commit -m "initial deploy"
git push origin main
# -> GH Actions 自动跑 wrangler deploy + GH Pages deploy
```

### 步骤 9：配置 launchd 定时任务

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

> **plist 含机器绝对路径**（`/Users/linhuichen/code/trade-data/scripts/...`），每台机器需修改路径后加载。plist 模板在 staticdata git 仓库 `config/launchd/` 下（路径已脱敏）。

### 步骤 10：验证

```bash
# 验证 CF Workers（/data/ rewrite -> R2）
curl -sI https://ss.fx8.store/data/overview.json | grep -i "cf-cache\|cache-control"
curl -s https://ss.fx8.store/data/overview.json | python3 -m json.tool | head -5

# 验证 /r2/ 代理（R2 binding + 边缘缓存）
curl -sI https://ss.fx8.store/r2/index/sh000001-all.json | grep -i "cf-cache\|cache-control"

# 验证 R2 公开桶直链
curl -sI https://ssd.fx8.store/data/overview.json | grep -i "cf-cache"

# 验证 /api/purge-cache
curl -s -X POST https://ss.fx8.store/api/purge-cache \
  -H "Content-Type: application/json" \
  -d '{"secret":"<PURGE_SECRET>","keys":["/data/overview.json"]}'

# 验证 DB
sqlite3 /Users/linhuichen/code/trade-data/data/sentiment.db "SELECT COUNT(*) FROM daily_metric;"

# 验证定时任务
launchctl list | grep trade
```

---

## 8. 排障

### 8.1 CF 边缘缓存 purge 不生效

| 症状 | 原因 | 解决 |
|---|---|---|
| 上传新数据但前端读旧版 | CF edge 缓存未过期（TTL 窗口内） | upload-all-data/intraday/data-files 自动调 purge_cache；手动：`curl -X POST /api/purge-cache` |
| purge_cache 返回 403 | PURGE_SECRET 不一致 | 检查 trade-data/.env 的 PURGE_SECRET 与 `wrangler secret put` 设的是否一致 |
| purge_cache 返回 0 purged | cache key 不匹配 | cache key 用 pathname（不含 query），确认 keys 格式为 `/data/xxx.json` |

### 8.2 R2 404

| 症状 | 原因 | 解决 |
|---|---|---|
| /data/xxx.json 404 | R2 无此 key | 运行 `upload_r2.py list data/` 确认 key 存在；手动 `upload_r2.py upload-all-data` 补传 |
| /r2/index/sh000001-all.json 404 | 数据缺失（非路由问题） | 运行 `upload_r2.py upload-index` 补传 |
| /data/ 回退 ASSETS（非 R2） | R2 404 自动回退静态文件 | 正常兜底行为；但 static-site/data/ 已移出 git，ASSETS 也无文件时会 404，需补传 R2 |
| R2 直链 ssd.fx8.store DYNAMIC 每次回源 | public bucket 无边缘缓存 | 已改走 Worker /r2/ 代理（Cache API 边缘缓存 1h） |

### 8.3 Worker 路由

| 症状 | 原因 | 解决 |
|---|---|---|
| /data/*.json 返回 ASSETS 旧版 | Worker 未部署（GH Actions 失败） | 检查 GH Actions deploy-cf.yml 状态；本地 `npx wrangler deploy` 手动部署 |
| /r2/* 路由 404 | wrangler.jsonc 未配 r2_buckets binding | 确认 wrangler.jsonc 含 `r2_buckets: [{ binding: "R2_BUCKET", bucket_name: "signal-data" }]` |
| Worker 报 R2 read error | R2 binding 未绑定或 bucket 不存在 | CF Dashboard 确认 Worker 绑定了 R2 bucket；`npx wrangler r2 bucket list` 确认 bucket 存在 |

### 8.4 upload_r2.py 问题

| 症状 | 原因 | 解决 |
|---|---|---|
| 上传失败 | .env 凭证错误/过期 | 检查 R2_S3_ACCESS_KEY_ID/SECRET_ACCESS_KEY/ENDPOINT |
| 卡 TCP SYN_SENT | 网络问题 | deploy.sh 内置超时 kill（R2_UPLOAD_TIMEOUT=300s） |
| 部分文件上传失败 | 单文件 R2 5xx InternalError | upload_r2.py 内置 5 次重试（1s/2s/4s/8s 退避） |
| broken symlink 上传失败 | trade_sim_*.html symlink 目标被删 | _upload_glob 自动过滤 broken symlink；手动检查 `ls -la static-site/trade_sim_*.html` |

### 8.5 s.sugas.site 300MB 限制

| 症状 | 原因 | 解决 |
|---|---|---|
| s.sugas.site 404 | 超 300MB 限制 | 大文件走 R2（ssd.fx8.store），static-site/data/ 已移出 git；s.sugas.site 仅兜底 |
