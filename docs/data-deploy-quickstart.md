# 数据上线快速上手引导（data-deploy-quickstart.md）

> 子 agent 直接照做的数据上线速查。R2 迁移（2026-08-08 阶段 1-5 完成）后，数据 JSON 不再 git push，走 R2 + Worker /data/ rewrite。
> 本文档是"操作速查"视角：改了东西怎么上线，3 步内做完。深入架构/从零重建/灾备见 [`docs/r2-deployment.md`](r2-deployment.md) + [`docs/site-deployment.md`](site-deployment.md) + CLAUDE.md §8/§8.1/§9。

---

## 0. 先记住这一条（最常踩的坑）

**数据 JSON 走 R2，不 git push。** `static-site/data/` 已全量移出 git（`.gitignore` L188-189：`static-site/data/*` + `!feed.xml`），git 只跟踪 `feed.xml` 一个文件。

```bash
$ git ls-files static-site/data/
static-site/data/feed.xml   # 只有这一个，其余全部 gitignored 走 R2
```

> ⚠️ `git ls-files static-site/data/` 返回只有 feed.xml **≠ 文件不存在**，是 gitignored 走 R2。文件还在本地磁盘 `static-site/data/*.json`，只是不进 git。这是子 agent 最常反复验证的点（每次 fresh context 都会 `git ls-files` 确认一遍）。

---

## 1. 两条上线流程（先判断你改了什么）

| 你改了什么 | 上线方式 | 详见 |
|---|---|---|
| **数据产物 JSON**（overview.json / board_etf_map.json / signal_kelly_trades.json / index\* / industry\* 等） | R2 上传 + purge cache，**不 git push** | [§2](#2-改数据产物如何上线) |
| **前端代码**（app.js / lab.js / style.css / common.js 等） | build_min + bump 版本号 + bump sw.js + git push main | [§3](#3-改前端代码如何上线) |
| **后端逻辑 / Worker**（app/\* / worker/\*.js） | git push main 触发 GH Actions wrangler deploy | [§3](#3-改前端代码如何上线) |

**口诀：数据走 R2，代码走 git。** 改数据不 push，改代码才 push。

---

## 2. 改数据产物如何上线

### 2.1 速查：改了 X 文件，用哪个 upload 命令

`scripts/upload_r2.py` 命令（凭证从 `trade/.env` 读，S3 兼容 SigV4 签名，不依赖 boto3）：

| 改了什么数据 | 命令 | R2 前缀 | 典型场景 |
|---|---|---|---|
| **单个/几个小文件**（最常用） | `upload-data-files <f1> [f2]...` | `data/` | 改了 board_etf_map.json / schedule_stats.json / overview.json 等。**改一两个文件首选这个**，自动 purge |
| 全量小文件 | `upload-all-data` | `data/` | 全量同步小 JSON（排除已走独立命令的） |
| 大文件（>=1MB 或 `*-(all\|5y\|3y).json`） | `upload-data-large` | `data/` | 大 range 历史序列 |
| 指数全历史（data/index/\*.json） | `upload-index` | `index/` | 44 指数走势图源 |
| 行业数据 | `upload-industry` | `industry/` | 31 行业 |
| 策略实验室 | `upload-lab` | `lab/` | lab/\*.json |
| 回测 HTML 页面 | `upload-trade-sim` | `trade_sim/` | trade_sim_\*.html |
| 回测统计数据 | `upload-trade-sim-json` | `trade_sim_data/` | \*_stats.json / _full.json |
| 公募基金 | `upload-public-fund` | `public_fund/` | |
| 场外基金 | `upload-offshore-fund` | `offshore_fund/` | |
| 基金评分 | `upload-fund-score` | `fund_score/` | |
| ETF 评分 | `upload-etf-score` | `data/` | etf_score_list_\*.json |
| 盘中实时快照（23 文件） | `upload-intraday` | `data/` | 盘中定时任务用 |

**判断规则**（CLAUDE.md §8.1）：
- 改一两个文件 → `upload-data-files <文件名>`（精准，自动 purge，最快）
- 不确定/全量 → `upload-all-data`（小文件）+ `upload-data-large`（大文件）兜底
- 按类别 → 用对应 `upload-{prefix}`（新数据类别优先按前缀建独立命令，不依赖 1MB 阈值）

### 2.2 标准操作（改了 board_etf_map.json 为例）

```bash
cd /Users/linhuichen/code/trade
# 1. 确认数据文件在本地存在（trade/static-site/data/ 或 trade-data/static-site/data/，见 §4 路径同步）
ls -la static-site/data/board_etf_map.json

# 2. 上传到 R2（单文件用 upload-data-files，自动 purge CF 边缘缓存）
.venv/bin/python scripts/upload_r2.py upload-data-files board_etf_map.json

# 3. 验证上线（见 §5 三域名验证）
curl -sI https://ss.fx8.store/data/board_etf_map.json | grep -i "cf-cache\|HTTP"
```

### 2.3 全量 deploy（收盘后大批量数据更新）

**只在盘后 15:35 后跑**（盘中撞 intraday-snapshot 定时任务推 main 会互相覆盖，见 CLAUDE.md §8/§14）：

```bash
cd /Users/linhuichen/code/trade-data    # 注意 cwd（见 §4 路径同步）
/Users/linhuichen/code/trade/.venv/bin/python static-site/export.py   # 生成 JSON + 末尾自动跑 R2 上传
bash /Users/linhuichen/code/trade/scripts/deploy.sh                  # build_min + R2 全量上传 + git push 代码
```

`deploy.sh` 会自动跑 10 个 R2 上传命令（upload-lab/index/industry/public-fund/offshore-fund/etf-score/trade-sim/trade-sim-json/data-large/all-data），git 只 push 代码（feed.xml + 6 个 min JS/CSS），**数据 JSON 不进 git**。

> ⚠️ 盘中（09:30-15:30）不跑全量 export + deploy。盘中只有 intraday-snapshot 定时任务推 intraday_snapshot.json。

---

## 3. 改前端代码如何上线

```bash
cd /Users/linhuichen/code/trade

# 1. build min JS/CSS（terser minify app.js+lab.js+common.js+purpose-notes.js+style.css+lab.css）
.venv/bin/python scripts/build_min.py

# 2. bump 版本号（md5 前 8 位破缓存，改 app.min.js 的 ?v= query）
.venv/bin/python scripts/bump_asset_version.py

# 3. ⚠️ 必 bump sw.js CACHE_VERSION（否则旧 Service Worker CacheFirst 缓存旧 app.min.js，用户拿不到新代码）
#    编辑 static-site/sw.js，把 CACHE_VERSION 数字 +1

# 4. git push（只推代码 + min JS/CSS + feed.xml）
git add static-site/app.min.js static-site/lab.min.js static-site/common.min.js \
  static-site/purpose-notes.min.js static-site/style.min.css static-site/lab.min.css \
  static-site/sw.js static-site/data/feed.xml
git commit -m "feat: <说明>

Co-Authored-By: Claude <noreply@anthropic.com>"
git push origin feat/xxx:main    # 或先 push feat 再 merge main
```

push main 触发 GH Actions（`wrangler deploy` Worker + GH Pages 部署 sss.sugas.site）。

> 改 app.js/lab.js **三步缺一不可**：build_min + bump_asset_version + **bump sw.js CACHE_VERSION**（CLAUDE.md §9）。漏 bump sw.js → 旧 Service Worker 缓存旧 app.min.js → 用户硬刷后退回旧数据。
>
> 验证 min 版 JS 上线用**字符串非变量名**（terser mangle 重命名 let 局部变量）：grep class 名/中文字符串（如 `kst-comp-fill` / `分项构成`），不 grep 变量名。

---

## 4. export 路径同步陷阱（§9 cwd=trade-data 衍生）

**最容易踩的坑**：export.py 在 trade-data 跑，JSON 写到 `trade-data/static-site/data/`，但 deploy.sh 从 `trade/static-site/data/` 推 git / 上传 R2。两路径不同步会推旧版。

```
trade-data/   ← launchd 采集 + export.py 写 JSON 落此处（主库 DB 也在此）
trade/        ← git 仓库 + deploy.sh 上线源
```

**处理方式**：
- `deploy.sh` 内置 rsync（L184-187）：`REPO != GIT_REPO` 时自动 `rsync -a --checksum trade-data/static-site/data/ -> trade/static-site/data/`。**跑 deploy.sh 不用手动 cp**。
- **手动跑 export + upload 时**：export 后确认两路径同步，或直接用 `REPO` 环境变量让 upload_r2.py 读 trade-data：
  ```bash
  # upload_r2.py 优先读 REPO env 的 static-site/data/，回退 trade/
  REPO=/Users/linhuichen/code/trade-data .venv/bin/python scripts/upload_r2.py upload-data-files board_etf_map.json
  ```
- 验证同步：`diff trade-data/static-site/data/<file>.json trade/static-site/data/<file>.json`

> upload_r2.py L28-33：`STATIC_DIR = Path(os.environ.get("REPO", str(ROOT))) / "static-site"`。launchd 设 `REPO=trade-data`，故定时任务读采集器刚写的实时数据。手动从 trade 跑（无 REPO）读 trade/static-site/data/（deploy rsync 后的版本）。

---

## 5. 上线验证（三域名 + R2 直链）

**任一域名验证到新版即算上线 OK，不卡单域名 404**（CLAUDE.md §8，2026-07-22 教训：曾死磕 s.sugas.site 404 56 次忘其他域名已上线）。

| 域名 | 类型 | 用途 | 验证 |
|---|---|---|---|
| `https://ss.fx8.store/` | CF Workers 主站 | /data/ rewrite -> R2 binding（首选验证） | `curl -s https://ss.fx8.store/data/overview.json \| python3 -m json.tool \| head` |
| `https://sss.sugas.site/` | GitHub Pages | 备站 | 同上 |
| `https://s.sugas.site/` | MaoziYun 备站 | **有 300MB 限制，超了 404**，仅兜底 | 同上 |
| `https://ssd.fx8.store/` | R2 公开桶直链 | 大文件/按前缀（index/industry/lab/trade_sim/public_fund） | `curl -sI https://ssd.fx8.store/data/board_etf_map.json` |

**验证数据层（不是代码在 main）**：说"已上线"前 curl JSON 验字段有值 / 无旧字段残留（CLAUDE.md §8 教训：代码在 main + 版本号上线 ≠ 功能生效）。

```bash
# 小文件（/data/ rewrite -> R2）
curl -s https://ss.fx8.store/data/overview.json | python3 -c "import sys,json; d=json.load(sys.stdin); print('collected_at:', d.get('collected_at')); print('date:', d.get('date'))"

# 大文件 / 按类别（R2 直链 ssd.fx8.store）
curl -sI https://ssd.fx8.store/index/sh000001-all.json | grep -i "cf-cache\|HTTP/2"

# /r2/ 代理（Worker binding + 边缘缓存，大 range 历史）
curl -sI https://ss.fx8.store/r2/index/sh000001-all.json | grep -i "cf-cache"
```

---

## 6. Worker /data/ rewrite 机制（理解一次即可）

前端 `fetchJSON('/data/overview.json')` URL **零改动**，Worker 在背后 rewrite 到 R2：

```
前端 fetch /data/overview.json
  -> Worker dataRewriteHandler（run_worker_first=true，先于 Static Assets）
  -> Cache API 边缘缓存命中？-> 返回缓存（TTL 60s/600s/3600s 分层）
  -> R2 binding env.R2_BUCKET.get("data/overview.json")
  -> R2 有对象？-> 构造响应 + 分层 TTL Cache-Control + 写边缘缓存
  -> R2 404/错误？-> 回退 ASSETS（静态文件兜底）
```

- **R2 key** = `pathname.slice(1)`（`/data/overview.json` -> `data/overview.json`）
- **分层 TTL**（headers.js `dataCacheTtl`）：盘中高频 60s（overview/intraday/boot/summary/alert/-1m/-3m/-6m/-1y） / 每日 600s（signal_stats/fund_score_top） / 历史低频 3600s（兜底）
- **上传新数据后 purge**：`upload-all-data` / `upload-intraday` / `upload-data-files` 自动调 `POST /api/purge-cache` 清 CF 边缘缓存。手动 purge：
  ```bash
  curl -s -X POST https://ss.fx8.store/api/purge-cache \
    -H "Content-Type: application/json" \
    -d '{"secret":"<PURGE_SECRET>","keys":["/data/overview.json"]}'
  ```

> 大 range 历史序列（`*-(all|5y|3y).json`）和 index/industry/lab/trade_sim/public_fund 走 R2 直链 `ssd.fx8.store/{prefix}/` 或 `/r2/{prefix}/` 代理（边缘缓存 1h）。详见 r2-deployment.md §3.3/§3.5。

---

## 7. 常见坑速查

| 症状 | 原因 | 解决 |
|---|---|---|
| `git ls-files static-site/data/` 只返回 feed.xml | **正常**，数据走 R2 不进 git | 不是文件丢失，文件在本地磁盘，走 R2 上传 |
| 上传新数据但前端读旧版 | CF edge 缓存未过期 | `upload-data-files`/`upload-all-data` 自动 purge；手动 `POST /api/purge-cache` |
| `git add static-site/data/*.json` 报无变更 | **正常**，*.json 全 gitignored | 数据走 R2，不 git add |
| deploy 推旧版数据 | export 写 trade-data/ 但 deploy 从 trade/ 推，路径不同步 | 跑 deploy.sh（内置 rsync）；手动 export 后 cp 或用 `REPO=trade-data` |
| 改 app.js 后用户拿不到新代码 | 没 bump sw.js CACHE_VERSION | 旧 Service Worker CacheFirst 缓存旧 app.min.js，bump sw.js + build_min + bump_asset_version 三步 |
| s.sugas.site 404 | 超 300MB MaoziYun 限制 | 大文件走 R2（ssd.fx8.store），s.sugas.site 仅兜底，验证用 ss.fx8.store/sss.sugas.site |
| /data/xxx.json 404 | R2 无此 key | `upload_r2.py list data/` 确认；`upload_r2.py upload-data-files xxx.json` 补传 |
| R2 直链 ssd.fx8.store DYNAMIC 每次回源 ~1s | public bucket 无边缘缓存 | 用 `/r2/` 代理（Worker binding + Cache API 边缘缓存 1h） |
| grep 验 min 版 JS 找不到变量名 | terser mangle 重命名 let 局部变量 | 用 class 名/中文字符串验证（如 `kst-comp-fill`），不 grep 变量名 |

---

## 8. 何时用 R2 vs CF Static Assets（CLAUDE.md §8.1）

- **走 R2**（满足任一）：全量品种多（100+ index/31 industry/100+ trade_sim/1000+ public_fund）/ 有大 range 历史序列（`-all/-5y/-3y` 单文件 >1MB）/ 类别整体大
- **走 CF Static Assets 小文件**：单文件 <100KB 且类别总量 <5MB（alert.json/daily_metric.json 等状态/监控小文件）
- **新数据类别从第一天走 R2 架构**（按前缀建 `upload-{prefix}` 命令 + 前端 R2 URL + upload-data-large exclude 加前缀防双副本），不等变大才补

---

## 9. 深入参考

- [`docs/r2-deployment.md`](r2-deployment.md) — 完整 R2 架构 + 从零重建 + 灾备 4 层 + 排障
- [`docs/site-deployment.md`](site-deployment.md) — 站点部署全文档
- [`docs/smoke-checklist.md`](smoke-checklist.md) — P0/P1 主功能 smoke 清单（reviewer agent 用）
- CLAUDE.md §8（改完推送 + 三域名验证）/ §8.1（R2 存储架构准则）/ §9（单版前端 + build_min/bump sw）/ §14（生产稳定性 P0 定时任务时点）
- memory：`r2-arch-by-category-not-size` / `r2-migration-complete` / `export-output-path-sync` / `fetchjson-skip-gz` / `r2-upload-from-trade` / `cf-workers-large-json-404-r2-fallback` / `verify-feature-live-not-code-in-main`
