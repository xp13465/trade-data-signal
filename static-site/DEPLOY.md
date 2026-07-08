# 静态化看板部署说明

静态版看板：纯前端 + 预生成 JSON 数据，无后端依赖，可托管到 Cloudflare Pages（或任何静态托管）。

## 目录结构

```
static-site/
├── index.html              # 入口 HTML（引用 ./style.css / ./vendor/echarts.min.js / ./app.js）
├── app.js                  # 前端逻辑（读 ./data/*.json，与动态版 web/app.js 功能一致）
├── style.css               # 样式（从 web/style.css 复制，无改动）
├── vendor/
│   └── echarts.min.js      # ECharts 图表库（从 web/vendor/ 复制）
├── data/                   # 预生成 JSON 数据（export.py 产出）
│   ├── overview.json       # 概览（今日快照 + sparkline + 宽度 + 分数 + 行业热力图 + 买卖点）
│   ├── a-stock-{1m,3m,6m,1y,all}.json    # A 股看板（各 range 一个文件）
│   ├── hk-{1m,3m,6m,1y,all}.json         # 港股看板
│   ├── global-{1m,3m,6m,1y,all}.json     # 全球看板
│   ├── sentiment-{1m,3m,6m,1y,all}.json  # 综合情绪看板
│   ├── industry-{1m,3m,6m,1y,all}.json   # 行业看板
│   ├── metrics.json       # 指标注册表
│   └── index/{id}-all.json # 44 个指数 ohlc + signals 全历史
├── export.py               # SQLite → JSON 导出脚本（可重复跑）
└── DEPLOY.md               # 本文件
```

## 数据更新流程

静态版数据由 `export.py` 从本地 SQLite（`data/sentiment.db`）导出。每次本地跑完采集 + 计算（`python -m app.collector.runner` + `python -m app.compute.runner`）后，执行：

```bash
cd /Users/linhuichen/code/trade
.venv/bin/python static-site/export.py
```

这会重新生成 `static-site/data/` 下所有 JSON（覆盖旧文件）。导出约 1-2 秒，产出 71 个 JSON 文件（~63 MB）。

## 部署到 Cloudflare（Workers Static Assets）

后台用 `wrangler deploy`（Worker 模式，**非 Pages**）。仓库根 `wrangler.jsonc` 配 Workers Static Assets：`assets.directory` 指向 `static-site/`，Cloudflare 自动生成静态托管 Worker（无需 Worker 代码，无 `main`）。push 到 main 后 Cloudflare 构建环境跑 `wrangler deploy`，读 `wrangler.jsonc` 更新现有 Worker `trade-data-signal`。

### 方式一：Git push 自动部署（推荐，as code）

1. 仓库根已有 `wrangler.jsonc`（`name=trade-data-signal`、`assets.directory=./static-site`、`compatibility_date=2026-07-07`）。
2. Cloudflare Dashboard → Workers & Pages → trade-data-signal → Settings → Build & deploy，Build command 配 `wrangler deploy`，Root directory=`/`。
3. 每次 `git push origin main` 自动触发部署（~30-60 秒生效）。

**数据更新流程**：本地跑 `export.py` → `git add static-site/data/ && git commit -m "update data" && git push` → Cloudflare 自动 `wrangler deploy`。

### 方式二：wrangler CLI 手动部署

```bash
# 安装 wrangler（Node.js >= 16）
npm install -g wrangler

# 登录 Cloudflare
wrangler login

# 部署（读仓库根 wrangler.jsonc，部署 Static Assets Worker）
cd /Users/linhuichen/code/trade
wrangler deploy
```

首次会提示创建项目。之后每次更新数据后重新跑 `export.py` + `wrangler deploy` 即可。

## 本地预览

```bash
cd /Users/linhuichen/code/trade/static-site
/Users/linhuichen/code/trade/.venv/bin/python -m http.server 8001
# 浏览器打开 http://localhost:8001
```

## 与动态版的关系

- **动态版**（`web/` + `app/` FastAPI）：本地开发测试用，运行在 `http://localhost:8000`，数据实时从 SQLite 查询。
- **静态版**（`static-site/`）：部署用，数据预生成 JSON，无后端依赖。
- 两版前端逻辑一致（render/ruleBar/signalColor/sticky/回顶等功能完全相同），仅数据源不同（API → JSON 文件）。
- 动态版不被静态版改动影响（独立目录，互不干扰）。

## range 处理方案

- **tab 端点**（a-stock/hk/global/sentiment/industry）：预生成多 range JSON（各 5 个文件：1m/3m/6m/1y/all），前端按 `state.range` 直接读对应文件。优点：前端逻辑最简，无需客户端切片。
- **index 详情**：仅预生成 `all` 全历史（44 文件），前端读后用 ohlc 日期范围客户端过滤 signals（`filterSignalsByRange` 函数）。优点：避免 44×5=220 文件膨胀；signals 数组小，过滤开销可忽略。

## 注意事项

- `data/industry-all.json` 较大（~28 MB，31 行业 × 全历史 × ohlc + signals + 资金流 + 换手率 + 宽度）。如需减小体积，可只部署 `1y`/`6m` 等 range，删除 `all` 文件（前端 `全部` range 会 404，可按需禁用该按钮）。
- `data/sentiment.db` 不部署（仅本地用）。静态版不依赖任何数据库。
- 导出脚本依赖 `app/` 包代码（`app.db.get_conn` / `app.collector.fetchers.load_config` / `app.calendar.last_trading_day`），需在项目根目录运行。
