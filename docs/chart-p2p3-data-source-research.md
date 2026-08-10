# 走势图统一改造 P2/P3 数据源调研（2026-08-11）

> 调研 agent 产出（只读调研，不实施）。前置方案：docs/chart-refactor-config-plan.md（P0 配置框架 -> P1 轻量走势图 -> P2/P3 数据扩展）。
> 本调研回答 P2/P3 的"数据产物现状 + 扩展方案 + 体积/R2 前缀 + 影响面"。
>
> ⚠️ **重要发现（对 P2/P3 是利好消息）**：调研时发现 **P0 配置框架 + P1 轻量走势图已部分落地**（app.js L3797-3855 `siteCfg()` 单例 + L16637 `_etfTrendLiteHTML` SVG 轻量渲染 + L16995-17001 ETF 弹窗 `charts.lightweight` 双实现切换 + L20579-20628 渲染切换按钮）。P2/P3 的走势图渲染可直接复用该轻量组件/配置机制，不需等 P1。
>
> **核心结论速览**：
> - **P2（ETF 30天外历史）**：数据源**已存在且全史**——`etf_daily` 表（1520 只 ETF，2005-02-23 至今 21 年历史，含前复权基准 accum_nav）。**不需新数据源调研**（原计划待调研的 fund_etf_hist_sina 已由 backfill_etf_daily.py 回填完成）。缺口只是"导出产物"：新增 `etf/{code}-all.json`（per-ETF 懒加载，平均 ~29KB/只）走 R2 新前缀 `etf/`（复刻 index/{iid}-all.json 模式）。
> - **P3（场外基金净值序列）**：DB `fund_daily_nav` 已有 2153 万行 / 25994 只 / 5 年历史（2021-07-05 至今，MAX date=20260810 今日新鲜）。**无前端净值序列产物**（fund_score_top.json 只 Top100 列表 34 字段，已确认无 nav 字段）。缺口是导出：新增 `fund_nav/{code}.json`（per-基金懒加载，~30KB/只）走 R2 新前缀 `fund_nav/`。

---

## P2：ETF 弹窗 30 天外历史

### P2-1 现状（已验证）

**前端渲染逻辑（grep app.js 实测）**：
- 弹窗入口 `openEtfScoreDetailModal(code)`（app.js L16837 当前行号，文件 21615 行，仍在被并发修改）。从 `_etfScoreState.all`（合并 buy/sell/hold 三分类）查 item。
- 走势图区块（L16992-17001）：`siteCfg("charts.lightweight", true)` 为真 → `_etfTrendLiteHTML(e.ohlc)`（SVG 轻量渲染，L16637）；否则 echarts `#etfTrendChart`（L17010-17011 `_dates=e.ohlc.map(d=>d[0])`、`_closes=e.ohlc.map(d=>d[4])`）。⚠️ 这是 P1 已落地证据，非原方案的纯 echarts。
- **数据源字段 = `e.ohlc`**（etf_score_list_{buy,sell,hold}.json item 字段），`[[date,o,h,l,c],...]` 近 30 交易日升序。

**数据产物现状（读 static-site/data/etf_score_list.json 实测）**：
- 结构：`{date:20260803, universe_count:1385, ohlc_days:30, buy_list, sell_list, hold_list, ...}`
- 弹窗可打开范围（三分类去重）：**1211 只**（buy 106 + sell 96 + hold 1009）
- ohlc 长度：每只 30 条（`ohlc_days:30`），全列表总 36330 行。**无更长历史字段**。

**DB 长历史（SQL 查 trade-data/data/etf_national_team.db `etf_daily` 表实测）**：
- 表结构：`(date, etf_code, etf_name, open, high, low, close, amount, fund_share, share_change, share_change_pct, accum_nav, PRIMARY KEY(date, etf_code))`
- 总量：**105.15 万行 / 1520 distinct ETF / 日期 20050223-20260810（21 年）**
- OHLC 完整且 >=100 天：1341 只 / 104.2 万行；>=500 天：676 只 / 88.6 万行
- **1211 只评分列表 ETF 全部在 etf_daily 有 OHLC（0 缺失）**，历史长度分布：
  - >=2000 天（8y+）：77 只；1000-1999：326 只；500-999：221 只；250-499：203 只；100-249：377 只；<100：7 只
- **accum_nav（前复权基准）**：1519 只 / 104.9 万行 / 2005-2026，全历史可用（QDII 跨境 ETF 少部分缺，48 只）

**数据源**：
- `backfill_etf_daily.py`（2026-07-28）：akshare `fund_etf_hist_sina`（新浪源，**返回全史**，不复权）。东财 fund_etf_hist_em 被 ban 弃用。
- `export_etf_score_list.py` `_fetch_recent_ohlc`（L276-321）：已实现**前复权查询逻辑**（`adj_factor(t)=(accum_nav(t)/close(t))/(accum_nav(latest)/close(latest))`），当前 30 日 ohlc 就是从这里查的，加日期 cutoff 限制。

**结论：P2 数据源问题已解决**。原 plan §4.5 待调研的"fund_etf_hist_sina / 腾讯日K / akshare 历史上限"已由 etf_daily 表全史回填落地。只需扩展导出产物。

### P2-2 扩展方案

**推荐：per-ETF 懒加载 JSON `etf/{code}-all.json`**（复刻 index/{iid}-all.json 模式）：
- 结构：`{date, code, name, ohlc:[[date,o,h,l,c],...]}`（复用现有 e.ohlc 格式，前端零改造数据解析）
- 产出：扩展 `export_etf_score_list.py`，复用 `_fetch_recent_ohlc` 前复权逻辑**去掉日期 cutoff**，对 1211 只评分列表 ETF（或全 1520 只）导出到 `static-site/data/etf/{code}-all.json`
- 上传：新增 `upload_r2.py cmd_upload_etf_hist`（读 `static-site/data/etf/*.json` → R2 `etf/` 前缀，§8.1 按前缀建命令；`upload-data-large` exclude `etf/` 防双副本）；deploy.sh 加上传
- 前端：ETF 弹窗加 period tab（3月/6月/1年/3年/5年/全部），复用信号弹窗 `openSignalChartModal`（app.js L4617+）的 period 切换 + `_signalModalCutoff`（L4657+）客户端过滤模式；数据 `fetchJSON("https://ss.fx8.store/r2/etf/${code}-all.json")`（硬编码 R2 URL，同 index 模式；不匹配 dataUrl 的 `-(all|5y|3y).json$` 正则的 `data/` 前缀，需硬编码）
- 渲染：chartLite / `_etfTrendLiteHTML` 类轻量组件渲染长序列（P1 已落地）

**体积估算（38B/行估计，已算）**：
| 区间 | 单只体积 | 说明 |
|---|---|---|
| 1y ~250 交易日 | ~9 KB | |
| 2y ~500 | ~19 KB | |
| 5y ~1250 | ~46 KB | |
| 10y ~2500 | ~93 KB | |
| 20y ~5000 | ~186 KB | 最老 ETF 510050 自 2005 |

- 1211 只总 95.9 万行 → **per-ETF 懒加载平均 ~29 KB/只**（合理，点开弹窗才拉单只）
- 若合并单文件 `etf_history_all.json` → **~34.8 MB**（单文件过大，前端一次性解析太重，不建议）

**R2 前缀判断**：per-ETF 文件 9-186KB，单文件 <1MB 但**类别数量大（1211+ 文件）**，按 §8.1"新类别按前缀建独立命令"，走 `etf/` 前缀（同 index/ 前缀，index/{iid}-all.json 就是硬编码 R2 URL + upload-index 命令）。CF Static Assets 放 1211+ 文件不经济（且弹窗只需懒加载单只，R2 直链最简）。

### P2-3 改动影响面（§15 回归风险）

- **新增产物不改现有 etf_score_list.json**（纯增量），现有 30 日 ohlc sparkline / 弹窗轻量+echarts 双实现均不受影响（§15 低风险）
- 前端改动点：`openEtfScoreDetailModal` 加 period tab + fetch（单函数）；`_etfTrendLiteHTML`/chartLite 组件复用
- `check_data_integrity.py` 当前**无 etf_score_list 校验**（已 grep 确认），需新增 `etf/{code}-all.json` 生成完整性校验（date 新鲜 + 非空）
- deploy.sh 上传链路三步：export.py 生成 → 新增 upload-etf-hist 命令 → deploy.sh 接入（§18 教训16 上新类别三步）
- 前复权口径：长历史用现有 accum_nav 前复权逻辑（已生产使用，低风险）；QDII 跨境 ETF（48 只无 accum_nav）降级未复权 close（同现有 `_fetch_recent_ohlc` 兜底）

---

## P3：场外基金净值序列

### P3-1 现状（已验证）

**前端展示点（grep app.js 实测）**：
- "基金评分" 1级 tab → 二级 tab **"场外基金"**（L17464-17469）→ `renderOffshoreFund`（L17700）
- 数据源：`fund_score_top.json`（R2 `fund_score/` 前缀直链 FUND_SCORE_TOP_URL_R2，CF fallback ./data/），Top100 列表
- **无净值走势图、无行点击/详情弹窗**（Phase B 5区块未做，已 grep `openFundScoreDetail`/`fund-score-row` onclick 均无绑定，行只读）
- fund_score_top.json item 34 字段：fund_code/name/type/composite_score/star_rating + 6维 + 5风险 + 经理 + 凯利 + 市场乘数 + final_suggestion，**无 nav/series/history 字段（已确认 plan 说法）**

**DB `fund_daily_nav`（SQL 查 trade-data/data/public_fund.db 实测）**：
- 表结构：`(date, fund_code, fund_name, unit_nav, acc_nav, prev_unit_nav, nav_change_pct, PRIMARY KEY(date, fund_code))`
- 总量：**2153 万行（unit_nav 非空 2145 万）/ 25994 distinct funds / 日期 20210705-20260810（5 年）**
- **新鲜度：MAX(date)=20260810（今日，已确认）**
- 历史长度分布：1000-1999 天：12880 只；500-999：5706；250-499：3449；100-249：2226；<100：1733
- **Top100 评分基金 nav 覆盖：~1240 行/只（5 年全历史）**（样本 000090/000020/000037 等）

**采集链路（已读脚本）**：
- 日更：`public_fund_daily.sh`（launchd 16:30 主 + 17:00 兜）→ `python -m app.collector.public_fund daily` → `fetch_daily_nav()`（akshare `fund_open_fund_daily_em` ~23738 只/日）
- 5 年历史回填：`stage0_nav.sh`（launchd 周五 01:43）→ `stage0-nav --days 1825`（27409 只分批断点续采）；另 `fetch_nav_history`（E4）回填头部偏股 200 只 400 日（反推仓位用）

**是否已有导出 JSON 产物**：**无**。`export_fund_score.py` 只导 fund_score.json（头部 2000）+ fund_score_top.json（Top100），均不含净值序列（已读脚本 L1-113 确认）。`queries.py public_fund_position_estimate`（L1754）用 fund_daily_nav 算仓位估计但不导前端。fund_score.json/fund_score_top.json 已在 check_data_integrity.py（L61/370 校验 date+count）。

### P3-2 扩展方案

**推荐：per-基金懒加载 JSON `fund_nav/{code}.json`**：
- 结构：`{date, fund_code, fund_name, series:[[date, unit_nav, acc_nav], ...]}`（升序，unit_nav 为主、acc_nav 可选）
- 产出：新脚本 `export_fund_nav.py`（或扩展 export_fund_score.py）——从 fund_daily_nav 按 fund_code 导出。**覆盖范围：优先 fund_score 表全量（~2000+ 只已评分基金）或 Top100**；全市场 25994 只也支持但建议按需/分批
- 上传：新增 `upload_r2.py cmd_upload_fund_nav`（`static-site/data/fund_nav/*.json` → R2 `fund_nav/` 前缀，§8.1 按前缀建命令；upload-data-large exclude 防双副本）；deploy.sh 接入
- 前端：场外基金行加点击 → 详情弹窗（Phase B 5区块：决策头/评分/走势/经理/风险，plan §4.5）+ **净值走势区块**（chartLite 轻量渲染），数据 `fetchJSON("https://ss.fx8.store/r2/fund_nav/${code}.json")` 懒加载（点开才拉单只）
- 净值口径：unit_nav（单位净值）做走势主序列；nav_change_pct 可做涨跌标注。注意累计净值 acc_nav 含分红再投，走势图用 unit_nav 与用户认知一致（§22 一致性：同一 fund_daily_nav 源，卡片/弹窗同序列）

**体积估算（24B/行 [date,nav] 估计，已算）**：
- per-基金 ~1240 行（5 年）→ **~30 KB/只**
- Top100 评分基金合并单文件 → **~3 MB**
- 全市场 25994 只合并单文件 → **~491 MB（过大，必须 per-基金懒加载）**
- fund_score 全量（~2000 只已评分）per-基金懒加载 → 总量 ~60 MB 但单只 ~30KB 按需拉取合理

**R2 前缀判断**：per-基金文件 ~30KB，**类别量大（2000-25994 个文件）**，按 §8.1 走新前缀 `fund_nav/`（同 index/etf/ 模式）。不走 upload-data-large 阈值（防双副本 + 前端硬编码 R2 直链懒加载）。

**备选方案**：仅在 fund_score_top.json 100 条内嵌 nav 序列（Top100 合并 ~3MB，单请求零新增 fetch）——优点零新产物；缺点只覆盖 Top100，用户搜索/筛选到 Top100 外无图，且 fund_score.json（2000 只）不覆盖。**不推荐作主方案**，可作 P3 Phase A 过渡。

### P3-3 改动影响面（§15 回归风险）

- 新增产物不改 fund_score.json/fund_score_top.json（纯增量，现有列表不受影响）
- 前端改动点：`renderOffshoreFund` 行绑定 click + 新增详情弹窗 + 走势区块（P1 chartLite 复用）；`renderPublicFund`（公募基金持仓 tab）与本需求无关不涉及
- `check_data_integrity.py` 需新增 `fund_nav` 校验（date 新鲜 + count>0），fund_score 现有校验不动
- 依赖 fund_basic 字段补齐（pf-fund-screener-real-requirements，plan L179/TASKS L1214）：指标介绍需基金类型/规模/经理等字段
- 上传链路三步（§18 教训16）：export.py 生成 → 新增 upload-fund-nav 命令 → deploy.sh 接入；backfill 补跑上传

---

## 建议实施阶段归属

| 项 | 归属阶段 | 等级 | 前置依赖 | 验收口径 |
|---|---|---|---|---|
| ETF 历史产物 `etf/{code}-all.json` + upload-etf-hist + deploy 接入 + check_data_integrity | **P2** | C 级（数据+前端） | P1 组件（已部分落地）+ 本调研 | curl R2 `etf/{code}-all.json` 非空且 date 当日；ETF 弹窗 60/90/180 天可看；§22 多周期一致 |
| ETF 弹窗 period tab + 长历史渲染 | **P2** | C 级（前端） | 上述数据产物 | 复用信号弹窗 3m/6m/1y/3y/5y/all 交互；chartLite 渲染长序列；切换按钮回 echarts 仍工作 |
| fund_nav 产物 `fund_nav/{code}.json` + upload-fund-nav + deploy 接入 + check_data_integrity | **P3** | C 级（数据） | P1 组件 | curl R2 `fund_nav/{code}.json` 非空且覆盖 Top100 评分基金 |
| 场外基金行点击 + 详情弹窗 + 净值走势 | **P3** | C 级（前端） | 上述数据产物 + fund_basic 补齐 | 卡片有净值走势；弹窗历史；指标介绍字段补齐 |

**串行理由**：P2/P3 数据产物可并行调研（本调研已出方案），但实施建议按 plan 先 P2（ETF 弹窗，用户已用 30 日，扩展诉求直接）再 P3（场外基金需新建详情弹窗 + 依赖 fund_basic）。P2/P3 都依赖 P1 组件（已部分落地，ETF 弹窗轻量渲染可直接复用 `_etfTrendLiteHTML`/`siteCfg`）。

---

## 附录：已验证证据清单（grep/SQL 实测，不臆断）

- `openEtfScoreDetailModal` app.js L16837（21615 行文件）；`_etfTrendLiteHTML` L16637；`siteCfg()` L3797-3855；`charts.lightweight` 弹窗切换 L16995-17001；渲染切换按钮 L20579-20628
- etf_score_list.json：date=20260803、ohlc_days=30、universe=1385、buy 106/sell 96/hold 1009、去重 1211、总 ohlc 36330 行
- etf_daily：105.15 万行、1520 只、20050223-20260810；OHLC 完整 1341 只(>=100d)/676 只(>=500d)；accum_nav 1519 只全史；1211 评分 ETF 全有 OHLC
- `_fetch_recent_ohlc` 前复权逻辑 export_etf_score_list.py L276-321；backfill_etf_daily.py 数据源 akshare fund_etf_hist_sina（新浪全史）
- `_signalModalCutoff` app.js L4657+（period 客户端过滤模式）；cmd_upload_index upload_r2.py L406-428（index/ 前缀模式）
- fund_daily_nav：2153 万行、25994 只、20210705-20260810、MAX=20260810；Top100 评分基金 ~1240 行/只
- fund_score_top.json item 34 字段**无 nav/series/history**（python 实测）
- export_fund_score.py L1-113（只导列表无序列）；queries.py L1754（nav 只用于仓位估计不导前端）
- fetch_daily_nav public_fund.py L861-908（日更 ~23738 只）；stage0-nav --days 1825（5 年断点续采）；public_fund_daily.sh（launchd 16:30/17:00）
- 场外基金 tab renderOffshoreFund L17700，行无 click 绑定（grep `openFundScoreDetail`/`fund-score-row` onclick 均无）
- check_data_integrity.py 只有 fund_score 校验（L61/370），无 etf_score_list 校验
