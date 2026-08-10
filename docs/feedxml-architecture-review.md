# feed.xml 架构调研报告

> 调研日期：2026-08-10 | 只读调研，不改代码

## 结论与推荐

**feed.xml 可以移出 git 走 R2，推荐移出。**

当初「RSS 不走 R2，必须留 git」是 R2 阶段4a（2026-08-08）的保守决策，非 RSS 固有约束。根因是当天为快速修 `/feed.xml` 404，Worker 重写用了最简单的 `env.ASSETS.fetch()`（从 Static Assets 取），没走 R2。而 `/data/*.json` 已有成熟的 `dataRewriteHandler`（R2 读取 + 404 回退 ASSETS）模式，feed.xml 完全可以复用。

移出后：开发日志消除日均 13.9 次无价值 commit（每个只改 lastBuildDate 1 行），和其他 data 产物架构一致（全走 R2），RSS 阅读器无感知（URL 不变，Worker 透明重写）。

## 1. feed.xml 作用

- **性质**：RSS 2.0 feed，文件 17KB / 220 行
- **生成**：`scripts/gen_rss.py` 读 `static-site/data/summary_history.json`，取最近 30 条生成每日收盘速递（恐贪指数/涨跌家数/量能/板块轮动/买卖点信号摘要）
- **消费**：供 RSS 阅读器订阅。**前端 app.js/lab.js/sw.js 不读 feed.xml**（grep 无匹配），纯 RSS 阅读器访问
- **访问路径**：`https://ss.fx8.store/feed.xml`（RSS 约定路径）+ `https://ss.fx8.store/data/feed.xml`（实际路径），两者 etag 相同（线上 curl 验证 200 OK）
- **URL 兼容**：Worker 内部重写 `/feed.xml -> /data/feed.xml`（commit 16310b647），非 301 redirect，直接返回 200 + feed 内容

## 2. 为何 .gitignore L189 例外保留（当初决策根因）

`.gitignore` L183-189（commit 7d086b1b2d, 2026-08-08 16:48）：

```
# R2 阶段4a（2026-08-08）：static-site/data/ 全量移出 git，R2 为唯一数据来源。
# 阶段1-3 已上线（定时任务去 git push 数据改 R2，前端走 R2 Worker rewrite）。
# 保留 feed.xml（RSS 不走 R2，必须留 git）。
...
static-site/data/*
!static-site/data/feed.xml
```

**根因：时序+保守决策，非技术硬约束。**
- R2 阶段4a（16:48）把 static-site/data/* 全量移出 git 时，feed.xml 的 Worker 路由还没建（当时 `/feed.xml` 直接 404）
- 同天 17:56 commit 16310b647 修 `/feed.xml` 404，用了最简单的 `env.ASSETS.fetch()` 重写（从 Static Assets 取文件）
- 因为重写走 ASSETS（依赖 git 部署的 static-site/），所以 .gitignore 必须 `!feed.xml` 保留 feed.xml 在 git
- **注释「RSS 不走 R2」是基于当时 ASSETS 重写实现写的，不是 RSS 的固有要求**。RSS 阅读器只关心 URL 返回 200 + XML 内容，不关心后端是 ASSETS 还是 R2

upload_r2.py L718 注释也印证：「feed.xml: 非 .json, *.json glob 天然不匹配」——feed.xml 从未被上传 R2，是 glob 模式天然排除，非主动设计。

## 3. 提交频率证据（问题量化）

```
feed.xml git 提交总数：306 次
最近 30 天日均：13.9 次/天
高峰日：2026-07-21（25 次）、2026-07-20（23 次）、2026-08-03（22 次）
```

每个 commit **只改 feed.xml 1 行**（lastBuildDate 时间戳），示例：

```
31b5ccf6d data update [public-fund] 2026-08-10_07:15
 static-site/data/feed.xml | 2 +-
 1 file changed, 1 insertion(+), 1 deletion(-)
```

**机制**：deploy.sh L169-172 每次部署调 `gen_rss.py` 重新生成 feed.xml（lastBuildDate 变），L276 git add feed.xml，L287 commit "data update [$NAME]"。定时任务（public-fund-daily 16:30/17:00 + backfill/all 等多个任务）每天触发 deploy.sh 多次，每次都产生一个只改 feed.xml 的 commit。

**这些 commit 无开发价值**：lastBuildDate 是运行时时间戳，不是代码变更，git log 里全是噪音，淹没真正的开发 commit。

## 4. 能否移出 git 走 R2（可行性分析）

**可以。** dataRewriteHandler（worker/headers.js L161-208）已实现完整模式：

```javascript
// /data/*.json -> R2 rewrite（阶段2 2026-08-08）
async function dataRewriteHandler(request, env, ctx, url) {
  const key = decodeURIComponent(pathname.slice(1)); // "data/overview.json"
  // 1. 边缘缓存命中（分层 TTL）
  // 2. R2 读取：env.R2_BUCKET.get(key)，404/错误回退 ASSETS
  // 3. 写边缘缓存（后台）
}
```

feed.xml 走 R2 只需：
- Worker 路由扩展：`/data/feed.xml` 和 `/feed.xml` 走 R2 读取（复用 dataRewriteHandler 或新建 feedHandler），404 回退 ASSETS
- upload_r2 上传 feed.xml 到 R2 `data/feed.xml`
- .gitignore 删 `!feed.xml` 例外
- deploy.sh：gen_rss 后 upload R2 + purge，不再 git add feed.xml

**无技术阻碍**：
- CF Workers Static Assets 不要求 feed.xml 在 git（R2 是独立数据源，和其他 *.json 一样）
- RSS 阅读器只看 URL 返回 200 + XML，不关心后端来源
- 前端不读 feed.xml，无前端改动
- upload_r2.py 有 `cmd_upload_data_files(["feed.xml"])` 可直接传单文件 + purge_cache

## 5. 推荐方案：移出 git 走 R2

### 实施步骤

**Step 1：Worker 路由扩展（worker/headers.js）**
- `/data/feed.xml` 走 dataRewriteHandler（扩展匹配条件，当前只匹配 `endsWith('.json')`，加 `|| pathname === '/data/feed.xml'`）
- `/feed.xml` 内部重写到 `/data/feed.xml` 后走 dataRewriteHandler（当前重写后走 `env.ASSETS.fetch`，改为走 dataRewriteHandler）
- dataCacheTtl 加 feed.xml 规则：建议 60s（HIGH_FREQ，和 summary_history 同级，收盘后更新一次但 RSS 阅读器可能盘中轮询）
- purge_cache 需覆盖 `/data/feed.xml` 和 `/feed.xml` 两个 cacheKey（现有 /feed.xml 重写后实际请求 /data/feed.xml，cacheKey 统一用 /data/feed.xml 即可）

**Step 2：upload_r2.py 上传 feed.xml**
- 方案 A（简单）：deploy.sh 里 gen_rss 后直接调 `python3 scripts/upload_r2.py upload-data-files feed.xml`（现有命令，传单文件 + 自动 purge）
- 方案 B（独立命令）：新建 `cmd_upload_feed()`，和 upload-etf-score 等独立命令一致（§8.1 新类别按前缀建独立命令）
- 推荐方案 A（feed.xml 是单文件，无需独立命令，upload-data-files 现成可用）

**Step 3：.gitignore 移出 feed.xml**
- 删 L189 `!static-site/data/feed.xml`（feed.xml 被 L188 `static-site/data/*` catch-all 忽略，移出 git）
- 更新 L185 注释：从「保留 feed.xml（RSS 不走 R2，必须留 git）」改为「feed.xml 已移出 git 走 R2（和其他 data 一致），Worker /feed.xml 重写走 R2」

**Step 4：deploy.sh 调整**
- gen_rss.py 保留（L169-172，生成 feed.xml）
- gen_rss 后加 upload R2：`"$PY" "$REPO/scripts/upload_r2.py" upload-data-files feed.xml`（上传 + purge）
- git add 列表（L276）删 `"static-site/data/feed.xml"`（不再 git push feed.xml）
- `git rm --cached static-site/data/feed.xml`（脱离 git 跟踪，本地文件保留）

**Step 5：验证**
- `curl -s https://ss.fx8.store/feed.xml` 返回 200 + 最新 XML 内容
- `curl -s https://ss.fx8.store/data/feed.xml` 返回 200 + 相同内容
- 确认 git log 不再有 "data update" commit 只含 feed.xml
- 确认 RSS 阅读器订阅正常（让用户确认）

### 权衡

| 维度 | 移出 git 走 R2（推荐） | 保留现状 |
|------|----------------------|---------|
| 开发日志 | 日均 13.9 次无价值 commit 消除 | 持续被淹没，未来不开发也每天 14+ 条 |
| 架构一致性 | 和其他 data 产物一致（全走 R2） | feed.xml 是唯一留 git 的 data 产物 |
| Worker 代码 | 稍复杂（feed.xml 走 R2 handler） | 简单（ASSETS 直接取） |
| R2 存储 | 多 17KB 小文件（可忽略） | 无 |
| RSS 阅读器 | 无感知（URL 不变，Worker 透明） | 无感知 |
| 部署依赖 | feed.xml 走 R2（和 *.json 一样） | 依赖 git 部署 static-site/ |
| 实施成本 | 中（Worker+upload_r2+.gitignore+deploy.sh 4处改） | 无 |

### 备选方案（若不想动 Worker）

若不想改 Worker 路由，**减少提交频率**是次优方案：
- deploy.sh 的 git add 列表删 feed.xml，gen_rss 后只 upload R2 不 git commit（但 Worker 仍走 ASSETS，feed.xml 不在 git 则 ASSETS 404，**此方案不可行**——除非 Worker 同时改走 R2）
- 或 feed.xml 独立数据仓库（如 trade-data-signal repo，和 sss.sugas.site 的 GitHub Pages 一样），但多一个仓库维护成本，不如走 R2

**结论：备选方案都不如直接移出 git 走 R2**（Worker 必须改走 R2 才能移出 git，不如一步到位）。

## 6. 当初架构分离为何遗留 feed.xml

R2 迁移阶段4a（2026-08-08）时，feed.xml 的 Worker 路由尚未建立。同天先后两个 commit：
1. 16:48 commit 7d086b1b2d：static-site/data/* 全量移出 git，feed.xml 例外保留（因 Worker 路由没建，只能靠 ASSETS 服务）
2. 17:56 commit 16310b647：修 /feed.xml 404，用 ASSETS 重写（因 feed.xml 在 git，ASSETS 能取到）

**这是时序导致的保守决策**：阶段4a 移出数据时 feed.xml 还没路由，只能留 git；随后修 404 时 feed.xml 已在 git，ASSETS 重写最简单就用了。没有后续迭代把 feed.xml 也改走 R2，是疏漏而非技术约束。

## 附：关键文件路径

- 生成脚本：`scripts/gen_rss.py`
- Worker 路由：`worker/headers.js`（L161 dataRewriteHandler, L255-263 /feed.xml 重写）
- .gitignore：L183-189（feed.xml 例外）
- deploy.sh：L169-172 gen_rss, L269-281 git add feed.xml, L283-291 commit
- upload_r2.py：L718 注释（feed.xml 非 .json 不匹配）, L785 cmd_upload_data_files（可传单文件）
- wrangler.jsonc：L12-14 ASSETS 绑定 ./static-site, L30 R2_BUCKET 绑定 signal-data
