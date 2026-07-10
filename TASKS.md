# TASKS.md — 情绪看板迭代任务清单（监管 + loop 工作模式）

> 这是「监管 + loop」工作模式的唯一共享任务文件。子进程开工前**必读本文件** + `REQUIREMENTS.md`（需求真实来源）+ `NOTES.md`（调研笔记）。监管（主进程）不直接干活，派子进程领任务循环。

## 总体大纲

A 股 / 港股 / 全球盘后复盘看板。Python 3.11 + FastAPI + SQLite + ECharts，Mac 本地。当前 27 个指标、13 指数、运行在 http://localhost:8000（`--reload`，改文件自动生效，**不要杀进程**）。本轮迭代目标：修回归问题 + 补国债 / 原油白银 / 红利 / A 股十年回溯 / 买卖点优化 / 行业看板 / 概览美化。

相关文件：`REQUIREMENTS.md`（需求 + 实现状态 + §9 变更史）、`NOTES.md`（调研 + 修复史）、`05-回归测试报告.md`（本轮回归）、`01-问题清单.md`（上轮 bug）、`config/indicators.yaml`（指标注册表）、`app/`（采集 + 计算 + API）、`web/`（前端）。

## 交接状态（2026-07-10，update_all 拆并行流水线，c6407aa）

> 用户反馈 `update_all.sh` 跑太慢，串行模式下慢任务（mootdx 5072 只 ~10min）拖累核心数据上线。拆成 4 条并行 pipeline，各自独立 采集->计算->导出->commit+push，慢任务不阻塞快核心。详见 `NOTES.md §12`。

**本轮已完成（1 commit，已推 main）**：
- `c6407aa` update_all 拆并行流水线：core(快核心,先上线) / width(慢宽度,后覆盖) / futures(独立) / stock_daily(后台死端不阻塞)

**关键决策**：
- core 先上线用昨日 width（情绪分略偏差），width 完成后覆盖 -- 符合「不阻塞上线」诉求
- macOS 无 `flock(1)` 命令，用 Python `fcntl.flock`（`with_lock.py`）串行化 git commit+push
- SQLite WAL + busy_timeout（db.py 30s / stock_daily 10s）保多 pipeline 并发写安全
- signal_stats.store 改原子写，避免并发 compute 撕裂
- 旧串行版备份 `scripts/update_all_serial.sh` 可一键回退

**遗留 / 待手动做**：
1. **完整端到端验证**：手动 `bash scripts/update_all.sh`，看 `git log` 出现 `[core]`/`[width]`/`[futures]` 多个 data update commit（按完成顺序，core 先 push），公网核心数据先更新、宽度后更新。组件级验证已全通过（语法/steps守卫/with_lock串行/busy_timeout/原子写）。
2. 之前 H5 轮遗留（GitHub topics / README 截图 / HelloGitHub / og.png 验证 / g.cn10y 回测）见下节。

## 交接状态（2026-07-10，H5打磨 + 获客SEO/分享图/README）

> 本轮聚焦**移动端体验打磨** + **公网获客基础设施**。公网地址 http://tdsignal-ujpzw01zm.maozi.io/ ，目标是让人搜得到、能分享、技术圈可传播。

**工作模式**：用户直接驱动迭代（非 worker 派发），每改完立即验证双版一致 + 跑 `bump_asset_version.py` 破缓存 + commit + push。

**本轮已完成（8 个 commit，全部已推 main）**：
1. `3e4a7b0` 模拟回测浮层加 loading 转圈 -- sim html 最大近 1MB，iframe 加载白屏无反馈；打开时显示转圈+「加载回测中…」，frame.onload 后隐藏
2. `13e63c2` H5 移动端网格列数固定 -- 概览 sparkline 默认 2 列、行业卡片强制 1 列（内容多不再挤）、KPI 小卡片 2 列；移除「1列/2列」按钮（列数已固定为最佳值，留着行业 tab 点无反应困惑）
3. `3fff0c7` H5 概览 KPI 小卡片改用 grid 强制 2 列 -- 原 flex `calc(50%-5px)` + wrap 因 subpixel rounding 换行成 1 列；改 `grid-template-columns:1fr 1fr` 硬约束稳定 2 列
4. `a17f508` 概览隐藏停更指标（北向资金）-- 新增 `isStaleMetric(m.date, r.date, days=30)` 基于数据日期 vs 最新交易日天数差动态判断，恢复更新后自动显示；移除 `tag: m.id==="a_fund_north"?"停更":""` 硬编码
5. `624e8de` 热力图按钮局部重画 + 周期切换保留滚动 -- 热力图抽出 `_heatmapSetOption()` 复用同实例 setOption（不调 renderTab 不丢滚动）；周期按钮记 scrollY + 锁 `content.minHeight` 防清空塌陷跳顶 + 渲染后恢复
6. `7fc98fa` SEO 静态文案 + JSON-LD + OG 标签 + og.png -- head 加 title/description/keywords(含 trade-data-signal/tdsignal/tdsignal-ujpzw01zm)/canonical/OG/Twitter Card/JSON-LD(WebApplication)；body 加 noscript 静态文案区(爬虫可读)；`scripts/gen_og_image.py` Pillow 生成 og.png(1200×630 深色品牌卡片)；main.py 加 /og.png 路由
7. `76f7558` 分享图功能 -- canvas 自绘 1080×1350 品牌分享卡(品牌标题+3情绪分卡+3宽度卡+上证迷你走势+域名)，PC header 📤按钮 + H5 顶部条📤图标按钮，弹窗预览+下载，无第三方库
8. `539f5b0` README 重写为对外吸引版 + LICENSE(MIT) + HelloGitHub 提交文案 -- 前置 demo+og图+6大功能+技术栈+快速开始；`HELLOGITHUB.md` 含提交说明+入选建议

**关键技术决策**：
- **双版同步**：web/(动态 FastAPI) + static-site/(静态 Cloudflare Pages) 每次改动逐字一致，仅数据源 URL 差异（`/api/overview` vs `./data/overview.json`）。所有 diff 验证除该 URL 外一致才提交。
- **分享图自绘不用 html2canvas**：纯 canvas API + PingFang 字体，无依赖、体积小、样式可控、自带品牌引流水印。og.png 用 Pillow 脚本生成（macOS PingFang.ttc 字体）。
- **停更判断动态化**：不硬编码指标 id，用日期差判断（北向 date=20240816 vs r.date=20260709 差近 2 年），任何指标恢复更新自动重新显示。
- **H5 网格用 grid 不用 flex**：flex-basis 是建议值，subpixel rounding 致换行；grid 列宽硬约束稳定。

**遗留 / 待用户手动做**：
1. **GitHub 仓库加 topics 标签**：`finance` `data-visualization` `stock` `echarts` `akshare` `python`（提升搜索发现率）
2. **README 顶部配 1-2 张看板截图**（GIF 更佳，HelloGitHub 入选关键）
3. **提交 HelloGitHub**：按 `HELLOGITHUB.md` 到 https://github.com/521xueweihan/HelloGitHub/issues 提交（审核周期~1 月）
4. **验证 og.png 预览**：公网部署后用 https://www.opengraph.xyz 贴 URL 检查分享卡片效果
5. **g.cn10y buy_aux 回测**（老遗留）：全球指标类（`_compute_value_signals` 路径）回测脚本需单独处理，`backtest_metrics.py` 只覆盖 C1 主买未覆盖 buy_aux

**除 SEO 外的其他获客方法（未实施，供后续选择）**：
- 内容营销：掘金/知乎/CSDN/少数派写"用 Python+ECharts 搭 A 股情绪看板"技术文带链接吃长尾
- 社区分发：V2EX、即刻、少数派 Matrix、开发者头条
- 工具属性独立页：把"情绪温度计""冰点检测"做成独立小页引流主站
- 订阅回访：冰点 RSS/邮件推送（已有邮件通知基础）带看板链接
- 开放免费 API：开发者用时带来源链接
- 友链：和同类 A 股工具站互链
- 微信生态：公众号/群每日冰点提醒带看板链接

**下轮起点**：用户反馈驱动。开工先读本节 + REQUIREMENTS.md + NOTES.md。移动端打磨 + 获客基础设施已就位，下轮关注数据质量监控 / 获客方法落地 / 截图补充。

---

## 交接状态（2026-07-09，用户体验评审后更新）

> 功能建设全部完成（期货指标上线）。进入**体验优化阶段**，依据 `REVIEW_REPORT.md` 评审报告。

### 本轮已完成（概要）
- 全品种模拟回测（77品种 HTML）
- 期货机构净多空持仓（机构/中信/国君三角色）
- index_id 全量中文化转译
- 用户体验评审报告（`REVIEW_REPORT.md`）

### 待办 — 体验优化（按优先级）

#### P0 — 立即改 ✅ 已完成
1. [x] **概览布局改为两列** — 两列布局（左：市场宽度+情绪分，右：买卖点+冰点+位置感），Spark和热力图保持全宽
2. [x] **情绪分加文字标签** — 数字旁标注"冰点/偏冷/中性/偏热/过热"，新增 `sentimentTag()` 函数
3. [x] **KPI 卡片排序** — 涨停→跌停→炸板率→成交额→量比→情绪分→跨市场→两融→北向

#### P1 — 近期改 ✅ 已完成
4. [x] **Tab 合并** — 6→4：概览/大盘(含A股/港股/全球二级Tab)/情绪/行业概念
5. [x] **ruleBar 改为全局浮动按钮** — 右下角蓝色"📋 策略说明"按钮，点击弹出 modal
6. [x] **期货区折叠** — 默认显示概览表+准确率，折线图折叠，点击展开
7. [x] **行业Tab 加锚点导航** — sticky 导航条，申万行业/概念板块 快速跳转+平滑滚动

#### P2 — 新功能 ✅ 已完成
8. [x] **新增涨跌家数比 + 腾落线（AD Line）** — `app/compute/ad_line.py`，概览左列双轴图
9. [x] **新增成交量对比** — `app/compute/volume_ratio.py`，概览 KPI+折线图，放量/缩量标注
10. [x] **新增大盘位置感** — `app/compute/position.py`，概览右列进度条卡片，8指数分位
11. [x] **新增一句话总结** — `app/compute/market_summary.py`，概览顶部横幅，规则引擎

#### P3 — 长期 ✅ 已完成
12. [x] **恐贪指数** — `app/compute/fear_greed.py`，8情绪分等权合成，概览KPI+情绪Tab图表
13. [x] **板块轮动速度** — `app/compute/rotation.py`，行业Tab轮动卡片，5/10/20日窗口
14. [x] **新高新低家数** — `app/compute/new_high_low.py`，概览NH-NL卡片+迷你折线，52周/20日
15. [x] **均线排列状态** — `app/compute/ma_alignment.py`，概览均线卡片，多头/空头/震荡统计

### 遗留
1. **industry-all.json 体积** — 23.74 MiB < 25 MiB，余量 1.26 MiB，2026 年底前需拆分
2. **g.cn10y buy_aux 回测** — 全球指标类（`_compute_value_signals` 路径），回测脚本需单独处理

### 下轮起点
体验优化阶段已完成（15/15 条建议全部实施）。下轮关注：前端样式微调 + 数据质量持续监控 + industry-all.json 体积优化。

---

## 交接状态（2026-07-07 compact 前）

> 本轮在 17 任务 done 基础上，完成外部验证报告修复 + 买卖点优化 + 邮件通知 + 双部署 + 静态化 + 脚本体系。

**工作模式**：监管派子进程（干活+验收 fresh context），监管只读汇报不跑命令，保持上下文干净。参数优化测试驱动（回测报告让用户选）。

**本轮新增工作**：
- **验证报告 8 bug**（交易信号网站验证报告.md）：A/C/D 实机正常（WebFetch 假象）；B 指数滞后=py_mini_racer 损坏已修；F 卖点文案改"走弱概率≈50%"；G REQUIREMENTS §6.5 披露 cross_market trim-mean + a_sentiment 权重公式；H 配对回测（10-买卖点配对回测.md）；E 指数/行业筛选+热力图切换。
- **py_mini_racer 修复**：sqreen py-mini-racer 0.6.0 坏包（muslc.so）覆盖 bpcreech mini-racer 0.14.1。卸载 sqreen + 重装 mini-racer==0.14.1。requirements.txt 锁定。
- **美股指数 4 个**：us_dji(.DJI)/us_ixic(.IXIC)/us_spx(.INX)/us_ndx(.NDX)，akshare index_us_stock_sina，fetchers.py 通用路径零改动。
- **B 扩展指标 signals**：全球 tab 10 指标（cn10y/us10y/wti_oil/comex_silver/gold/oil/usdcnh/a_qvix_300/a_qvix_1000/cn_us_spread）+ 综合情绪（cross_market/a_sentiment）算买卖点。signal_daily 前缀 g.*/s.*。规则：买=RSI(value,14)上穿30（a_sentiment skip_buy RSI 失效）；卖=恒正%回落/含负数std。前端 valueChartWithSignals。
- **B1+S1 买卖点优化**（11-买卖点优化方案回测.md 推荐）：买点加 BB下轨回归辅买 buy_aux（粉紫 #d63384，signal='buy_aux'）+ 卖点加 MA60 多头过滤（close>ma60）。卖/买比 3.99→0.49（买卖平衡）。buy 3861/buy_aux 5782/sell 4700。
- **回测 tips**：signal_stats.py 算每品种全历史 buy/buy_aux/sell × 5/10/20 日 forward 收益（胜率/盈亏比/样本/均值）。存 data/signal_stats.json（60 品种）。API /api/index/{id}+/api/global+/api/sentiment 返回 stats。前端 statsHint 显示 tips："回测(全历史·信号后10日) 买点 胜率X% 盈亏比Y 样本Z 凯利W% | 辅买... | 卖点... | 凯利公式参考仓位，非投资建议"。凯利公式 f*=max(0,(b·p-(1-p))/b)。
- **stats 动态更新**：runner.py step 10 每日重算 signal_stats.json + deploy export.py 导出静态 JSON。新买卖点入库 → 次日 update_all 自动刷新 stats。
- **筛选 UX**：A 股/港股 tab 筛选按钮移到指数折线区前（.indices-section）+ 局部刷新（doRender 不整页，闭包 signalsCache 不 refetch）。
- **邮件通知**：scripts/check_signals.py 查当天 signals + 发邮件（SMTP 163）。config/email.json（授权码 PVqAD9mWjNJtVMtd，发件 wy13465@163.com，收件 234058394@qq.com，.gitignore 排除）。品种中文名映射（index_id→name）。update_all.sh 第3步。14:30 盘中预警 + 15:33 收盘正式（launchd/cron）。
- **双部署**：Cloudflare Pages Connect to Git（xxx.pages.dev 主用）+ GitHub Pages workflow（.github/workflows/deploy-pages.yml，actions/deploy-pages，需用户配 Settings → Pages → Source = GitHub Actions）。
- **百度统计**：web/index.html + static-site/index.html 加百度统计代码（hm.js?e1d50bf3c782798dd0c0515a14b1a48c）。
- **静态化**：static-site/ 子目录（index.html/app.js/style.css/vendor/export.py/DEPLOY.md/data 75 JSON 61.6MB）。export.py minify（industry-all.json 23.86MB <25MB）。
- **脚本体系**：scripts/collect.sh（调 scheduler，含 runner step 1-10）+ deploy.sh（export+git push 总是 push 幂等）+ check_signals.sh（查signals+发邮件）+ update_all.sh（collect+deploy+check_signals）+ README。漏跑回填 width_history.run_recent(30) step 9。
- **回测报告 06-11**：06 RSI阈值/07 卖点对策12方案/08 深度11策略244资产/09 指标/10 配对523回合/11 优化方案B1+S1推荐。
- **git 仓库**：xp13465/trade-data-signal（SSH 已配，偶发网络抖动 push 失败重试成功）。

**遗留**：
- dev server（uvicorn --reload）watchfiles 偶发 stale（改代码后不 reload），重启解决：kill PID + nohup .venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 --app-dir /Users/linhuichen/code/trade。
- 东财 push2his.eastmoney.com IP 封禁（industry_extras 行业资金流/换手率 fail，老问题，代码就绪待 IP 解封）。
- mootdx 依赖 py-mini-racer（pip 元数据），未来 pip install mootdx 可能再拉 sqreen 坏包，需加 constraint。
- GitHub Pages 需用户配 Settings → Pages → Source = GitHub Actions（否则 workflow 不部署）。
- 静态版 industry-all.json 23.86MB，余量 1.14MB（约容 150 交易日增长，2026 年底前需考虑拆分）。

**下轮起点**：用户反馈 → 派子进程修。开工先读 TASKS.md 交接状态节 + REQUIREMENTS.md + NOTES.md。

## 交接状态（2026-07-06 compact 前）

> compact 后先读本节 + 「工作约定」+ 任务清单恢复上下文。记忆 `supervisor-loop-mode` 只是缓存，**以本文件为准**。

**工作模式**：监管（主进程）派**两个子进程**——干活子进程做任务、验收子进程在 fresh context 跑 curl/grep/DB 验收。监管**只读两份汇报，不自己跑命令**（保持上下文干净省 token）。通过即派下一个。不问用户 yes/no，全部完成或卡住才通知。最终用户 + 外部测试整体验收。

**进度（17/17 done）**：
- ✅ done：A1 A2 A3 G1 E1 E2 E3 B1 C1 B2 F1 F2 F3 D1 D2 D3 S1（详各任务条目「结果备注」）
- ✅ 收尾：worker-cleanup（D3 阶段2 校验 + D2 换手率分布补遗，2026-07-06 完成）

**接续步骤**：全部 done。最终用户 + 外部测试整体验收。

**后续优化（2026-07-07，修复 industry-all.json 超 Cloudflare Pages 25MB 限制，worker-fix-size）**：纯静态版修复，不改动态版 `web/` `app/`。问题：`static-site/data/industry-all.json` 26.5 MiB（27,767,367 bytes）超 Cloudflare Pages 25 MiB 单文件限制致部署失败（其他文件最大 a-stock-all 6.5 MiB OK）。**根因**：`static-site/export.py::write_json()` 用 `json.dumps(data, ensure_ascii=False, default=_json_default)` 默认分隔符 `(', ', ': ')`——每条 JSON 后逗号+空格、每个 key 后冒号+空格，industry-all.json 含 31 行业 × ~4000 日 OHLC + signals 共 ~12 万对象，空白累计 ~1.6 MiB。**方案A（实施，minify）**：`write_json` 加 `separators=(",", ":")` 紧凑输出（无 indent、无多余空白）。所有 JSON 都 minify（体积都减小，无害）。**未走方案B（拆分 31 文件）**：minify 后 industry-all.json 25,022,360 bytes = 23.86 MiB < 25 MiB 限制（Cloudflare Pages 限制为 25 MiB 二进制 = 26,214,400 bytes，已用 dataPro 查证），余量 ~1.14 MiB 够用。**注意**：`len(text)`（Python 字符数）= 24,888,806 与 `ls` 字节数 25,022,360 差 ~134KB，因中文字符 UTF-8 占 3 字节但 Python str 算 1 字符——以 `ls`/`du` 字节数为准。**前端无改动**：app.js 用 `fetch(url).then(r=>r.json())` 解析紧凑 JSON 无影响（标准 JSON 解析不依赖空白），未动 app.js/index.html/style.css。**验收**：① export.py 跑通生成 71 JSON（56.8 MB）；② industry-all.json = 25,022,360 bytes（23.86 MiB < 25 MiB）✅；③ a-stock-all.json 6.18 MiB（原 6.5 MiB，未破坏）；④ `node --check static-site/app.js` PASS（未改但确认无回归）；⑤ 静态服务 `python -m http.server` 起得来，curl industry-all.json Content-Length=25022360 + JSON 头部紧凑格式 `{"indices":{"sw_801010":{"name":...` 无空白；⑥ `json.load` 解析 industry-all.json OK（31 indices + 31 heatmap + 全字段 name/data/signals/fund_flow/turnover/width 在）；⑦ git commit + push 成功（commit e947eb5，main -> main）。**未走拆分原因**：minify 已够（<25 MiB），拆分会改 app.js fetch 逻辑增加复杂度且 industry index_id（sw_801xxx）虽与 `data/index/sw_*-all.json` 同 id 但字段不同（industry 含 width/fund_flow/turnover，index/ 仅 ohlc+signals），无法复用需单独拆 `data/industry/{id}-all.json` 31 文件——minify 优先更简。**遗留**：若未来 industry 数据增长超 25 MiB（历史日累积），再走方案B 拆分；当前余量 ~1.14 MiB 约可容 ~150 个交易日增长（每日 ~7KB），够用到 2026 年底。

**后续优化（2026-07-07，采集/部署/一键更新脚本，worker-scripts）**：建 `scripts/` 目录 + 3 脚本 + README，串起「本地采集 → 静态 JSON 导出 → git push 自动部署 Cloudflare Pages」全流程。**(1) `scripts/collect.sh`**：调 `.venv/bin/python -m app.scheduler`（含 refresh_trade_dates + is_trading_day 闸门 + 采集 + 计算 + 告警 step 1-8），支持透传日期参数 `bash scripts/collect.sh [YYYYMMDD]`，日志 tee 到 `data/logs/collect_YYYYMMDD_HHMM.log`，`set -u` 但不 `set -e`（scheduler 内部 try/except 兜底，部分失败仍继续记退出码）。**(2) `scripts/deploy.sh`**：跑 `static-site/export.py` 生成 71 JSON → `git add static-site/data/` → `git diff --cached --quiet` 检查变更 → 无变更 echo "no changes, skip push" 退出 0；有变更 commit（msg `data update YYYY-MM-DD_HH:MM`）+ push（Cloudflare Pages 自动部署）。日志 tee `data/logs/deploy_*.log`，每步显式判退出码。**(3) `scripts/update_all.sh`**：顺序跑 collect → deploy，**无论采集成败都继续 deploy**（用现有数据导出推送，公网保持最新可用状态，collect 失败仅记日志不改变最终退出码），退出码=deploy 退出码。**(4) `scripts/README.md`**：3 脚本用法 + 定时任务配置（launchd plist 示例放 `~/Library/LaunchAgents/` + `launchctl load`，含与旧 `com.trade.sentiment.plist`（仅采集 15:33）二选一说明；cron crontab 示例 + macOS ssh-agent 注意）。**约束**：脚本内部 `cd /Users/linhuichen/code/trade` 绝对路径，用 `.venv/bin/python` 绝对路径，不改 `app/` `web/` `static-site/export.py`。**验收**：① 3 脚本 `bash -n` 语法全通过；② 3 脚本 `chmod +x`（755）；③ `deploy.sh` 实测跑通——export.py 生成 71 JSON（56.8 MB，industry-all.json 24,888,806 chars/25,022,360 bytes < 25 MiB Cloudflare 限制）+ git add + `git diff --cached --quiet` 判无变更（数据与上次导出一致）+ skip push 退出 0，日志 `data/logs/deploy_20260707_1255.log` 写入正常；④ collect.sh 不真跑（耗时 + 网络，仅语法检查 + 说明手动跑）；⑤ git commit + push 成功（commit fe5ab1b，2140061..fe5ab1b main -> main）。**定时任务配置方式**：手动 `bash scripts/update_all.sh` 一键；launchd 用 `com.trade.update-all.plist`（ProgramArguments=/bin/bash + update_all.sh，StartCalendarInterval 15:33，WorkingDirectory=/Users/linhuichen/code/trade，StandardOutPath/ErrorPath 写 data/logs/），放 `~/Library/LaunchAgents/` + `launchctl load`，旧 `com.trade.sentiment.plist`（仅采集）需先 unload 避免重复；cron `33 15 * * * /bin/bash /Users/linhuichen/code/trade/scripts/update_all.sh >> .../update_all_cron.log 2>&1`（macOS ssh-agent cron 注入注意，推荐 launchd）。**遗留**：无。

**后续优化（2026-07-06，C1 买卖点软条件化）**：用户拍板，针对 E1 买卖点逻辑的 cross 硬门槛问题做软条件化。E1 要求买 cross<30（冰点）、卖 cross>70（狂热），近年市场宽度结构变化致 cross 多在 30-70 中性区，近 1 年买点 0、卖点仅 29，信号可用性丧失。C1 改动：① `app/compute/signals.py` 去掉 cross 硬门槛（buy/sell 仅 RSI 事件判定 + shift(1).fillna(False)），新增 `_cross_tag()` 返回 `冰点/偏冷/中性/偏热/狂热`，reason 拼成 `RSI上穿30(29->34),cross=8[冰点]`，cross NaN 省略 cross 段；② 重算 signal_daily（`python -m app.compute.runner`），近 1 年 buy 0→114 / sell 29→267，全史 buy 55→3311 / sell 58→3582（共 6893）；③ `REQUIREMENTS.md` §7 整章重写（C1 逻辑 + 分级表 + 变更历史加 C1 条目 + §7.5 对比表改 C1 vs E1）+ §2/§9/§10 同步 + 文件头日期；④ `web/app.js` ruleBar 文案更新（摘要去 cross 硬门槛、详细加分级标签 + C1 变更理由）。验收：node --check + py_compile 通过；7 端点（overview/a-stock/hk/global/sentiment/industry/index）全 200；近 1 年信号数显著增加（达成）。review gate 类，待监管派验收子进程。

**后续优化（2026-07-06，D1 卖点优化，worker-D1-sell）**：用户拍板 D1（回测验证唯一达标，2016+ 胜率 50.6%/盈亏比 1.04）。C1 卖点 RSI 下穿70 经 `07-卖点对策回测.md` 12 方案回测为最差卖点（全史 10日胜率 43.1%/盈亏比 0.76/均值 +1.29%，方向相反）。D1 改动：① `app/compute/normalize.py` 加 `load_index_high(iid)`（从 index_daily 取 high 列，44 指数 high 均有数据）；② `app/compute/signals.py` 卖点改 D1：`hh20=high.rolling(20).max(); thresh=hh20*0.95; sell=(close_prev>=thresh_prev)&(close<thresh)`，fillna(False)；reason 改 `20日高回落5%(高4259->阈4046,close4028), RSI=40, cross=53[中性]`（RSI 降级参考标签、cross 软标签保留）；**买点 C1 不动**（RSI 上穿30 + cross 软标签，验收通过）；③ 重算 signal_daily，买点不变（全史 3311 / 近 1 年 114），卖点改 D1（13 主要指数全史 2453 / 近 1 年 123，与回测完全一致；含 31 行业指数共全史 9162 / 近 1 年 450）；④ `REQUIREMENTS.md` §7 整章重写（D1 卖点 + 止盈提示定位 + RSI 降级参考 + §7.4 变更历史加 D1 条目 + §7.5 对比表改 D1 vs C1）+ §2/§9/§10 同步 + 文件头日期；⑤ `web/app.js` ruleBar 文案更新（摘要卖点改「20日高回落5%（止盈/减仓提示）」+ 详细 D1 逻辑 + 回测结论 50.6%/1.04 + 诚实声明「最不坏非反向信号」）。验收：node --check + py_compile 通过；7 端点全 200；卖信号数学校验（sh 20260605 sample 数学验证通过：close 4057.78→4027.74 跌破阈 4045.92）；事件化校验（连续两日 sell 结构上不可能）。review gate 类，待监管派验收子进程。

**后续优化（2026-07-06，方案 B 卖点盈亏标注，worker-B-annotate）**：用户拍板 B（标注盈亏 + 前端分色 + 操作文案）。D1 卖点定位为「趋势转弱/止盈减仓提示」，但同一卖点在不同持仓成本下操作含义不同——若卖点 close 低于最近买点 close，则该卖点对前置买点是**止损**而非止盈。方案 B 改动：① `app/compute/signals.py::compute()` 按 index_id 维护 `last_buy_close` 游标（每个指数独立，按 date 升序遍历 buy_set|sell_set）——遇 buy 更新 `last_buy_close=该买点 close`，遇 sell 算 `pct=(close-last_buy_close)/last_buy_close*100` 分类：pct>0→`vs前买+X.XX%[止盈]`、pct≤0→`vs前买-X.XX%[买点失败]`、last_buy_close=None→`无前买点[趋势中]`；reason 完整格式 `20日高回落5%(高8864->阈8421,close8300), RSI=33, cross=55[中性], vs前买-2.32%[买点失败]`；**买点 C1 + 卖点 D1 触发逻辑不动**（只加标注，信号数不变）；② 重算 signal_daily，全史 12473 不变（buy 3311 / sell 9162），卖点标注分布：止盈 7227 / 买点失败 1739 / 无前买点 196（9162 卖点全有标签）；③ `web/app.js` 新增 `signalColor(s)` 助手（买=红`#e6492e`、卖止盈=绿`#2e8b57`、卖买点失败=灰`#9e9e9e`、卖无前买=橙`#ff9800`，按 reason 子串判断），`indexChart` + `renderIndustry` markPoint 改用 `signalColor(s)`；`ruleBar` 详细区加 2 div（盈亏标注说明 + 操作建议：灰=止损观望已持仓止损/未持仓观望等下个买点或MA60转多、绿=止盈减仓、橙=单独看趋势）+ 摘要补「卖点附 vs前买 盈亏标注」+ 变更行加方案 B；④ `REQUIREMENTS.md` §7.3 reason 格式加 vs前买 段 + 新增 §7.6 卖点盈亏标注（实现/分类表/分布/例）+ §7.4 变更历史加方案 B 条目 + 文件头日期。验收：node --check + py_compile 通过；8 端点全 200；sz_div 20260623 标 `vs前买-2.32%[买点失败]`（买 20260612 close 8496.65 → 卖 20260623 close 8299.56，符合预期）；9162 卖点全有标签（0 个无标签）。review gate 类，待监管派验收子进程。

**后续优化（2026-07-05，前端 UX：sticky 导航 + 回到顶部，worker-ux-sticky）**：纯前端 UX，不改后端/signals.py。改 2 文件（`web/style.css` + `web/app.js`）。**功能1 右下角浮动"回到顶部"箭头按钮**——`app.js::initBackToTop()` 动态创建 `<button class="back-to-top">↑</button>` 挂到 body；`scroll` 事件（passive）监听 `window.scrollY>300` 切换 `.visible` class（`opacity 0→1` + `pointer-events none→auto` 过渡 0.25s）；点击 `window.scrollTo({top:0,behavior:'smooth'})` 平滑回顶；CSS `.back-to-top{position:fixed;bottom:24px;right:24px;width:44px;height:44px;border-radius:50%;background:rgba(31,35,41,.55);z-index:90}`（低于 modal 100、ECharts tooltip 自带高 z-index 不遮挡），hover 加深背景，`focus-visible` 蓝色 outline 无障碍。**功能2 顶部 tab 栏 + ruleBar sticky 悬浮**——布局决策：**tab 栏与 ruleBar 各自独立 sticky（不合并）**，理由：① ruleBar 由 `ruleBar()` 函数动态渲染进 `#content`，每个 tab 调用一次且位置不同（overview 在 KPI 卡片之后第 6 节、其余 tab 在 content 顶部）；② tab 栏是静态 HTML（`.tabs`，body 直接子元素），ruleBar 是 `#content`（main，body 直接子元素）的子元素，两元素 sticky 上下文都是 viewport，独立 sticky 更灵活；③ 合并需重构 DOM 移动 ruleBar 出 content，破坏现有 render 函数，得不偿失。CSS：`.tabs{position:sticky;top:0;z-index:50;box-shadow:0 1px 3px rgba(0,0,0,.04)}`（已有 `background:#fff` 不透明 + `border-bottom`）；`.rule-bar{position:sticky;top:var(--tab-h,41px);z-index:40}`（已有 `background:#fafbfc` 不透明 + border）；`--tab-h` 由 `app.js::initStickyOffset()` 测量 `.tabs.offsetHeight` 写入 `:root`（resize/load 重测，避免硬编码像素，tab 栏改样式自适应）。**sticky 容器检查**：index.html body/header/.tabs/main 均无 `overflow:hidden/auto`（grep 验证 0 处），sticky 不被破坏。**ECharts 兼容**：sticky 只改 paint position 不改 layout box，图表 div 高度由 inline `height:Npx` 固定，`window.resize` 仍触发 `c.resize()`，渲染不受影响。**验收**：① `node --check web/app.js` PASS；② 7 端点（overview/a-stock/hk/global/sentiment/industry/metrics）+ 静态资源（style.css/app.js/`/`）全 200；③ 已部署生效（curl 静态资源 grep 到 `.back-to-top`/`position:sticky`/`var(--tab-h)`/`initBackToTop` 新规则）；④ 视觉验收留给用户硬刷新（滚动 >300px 浮动按钮淡入、点击平滑回顶、顶部隐藏；tab 栏 + ruleBar 滚动时悬浮）。无遗留（sticky 与 ECharts 无冲突；z-index 层级 modal(100) > back-to-top(90) > tabs(50) > rule-bar(40) > 内容(auto)，modal 打开时遮罩盖住浮动按钮）。

**后续优化（2026-07-05，前端 UX：周期选择器 sticky 悬浮右上角，worker-ux-range-sticky）**：纯前端，不改后端。改 3 文件（`web/index.html` + `web/style.css` + `web/app.js`）。**问题**：时间周期按钮（range 选择器 1月/3月/6月/1年/全部 + 手动补录）原在 `<header>` 内（非 sticky），下滚随 header 滚出视口，不可见不可点；而 sticky tab 栏右端空着。**方案A（实施）**：把 `<div class="periods">` 从 `<header>` 移入 `<nav class="tabs">` 作为末子，CSS `.tabs .periods{margin-left:auto;display:flex;align-items:center}` 推到 tab 栏右端并垂直居中——随 tab 栏 `position:sticky;top:0;z-index:50` 一起悬浮顶部右上角，零额外 sticky 元素。** selector 收窄（关键，防污染）**：① CSS `.tabs button`→`.tabs > button`（仅直接子 tab 按钮），否则会覆盖 `.periods button` 的 padding/border/border-radius/active 蓝底白字样式；② JS tab 点击 handler `querySelectorAll(".tabs button")`→`".tabs button[data-tab]"`，否则 periods 内 range/manual 按钮也会被绑 tab 切换（`state.tab=undefined` 回归）。range handler `'.periods button[data-rng]'` 与 manual `getElementById('manual-btn')` 选择器不依赖父容器，无需改。**z-index/层叠**：range 按钮随 tab 栏 z-index:50，低于 modal(100)/back-to-top(90)，高于 rule-bar(40)。**tab 栏高度**：tab 按钮 padding 10px 18px ≈ 41px 仍是最高的 flex 子项，periods 按钮 padding 6px 12px ≈ 32px 较矮不撑高，`--tab-h`（`initStickyOffset` 测 offsetHeight）不变，ruleBar sticky 偏移不受影响。**header** 现仅剩 h1 标题（`justify-content:space-between` 单子项左对齐，无害），随滚动消失符合预期。**验收**：① `node --check web/app.js` PASS；② 5 range × a-stock + hk/global/sentiment/industry 全 200；③ curl 静态资源确认 periods 已在 `.tabs` 内、`.tabs > button` 与 `[data-tab]` 收窄生效；④ 视觉验收留给用户硬刷新（下滚时周期按钮悬浮右上角可点切 range 触发 render）。无遗留（range 切换功能、tab sticky、ruleBar sticky、ECharts、回顶按钮、手动补录 modal 均无回归）。

**后续优化（2026-07-05，静态化看板，worker-static）**：在 `static-site/` 子目录建一版静态前端 + 预生成 JSON 数据 + 导出脚本，后续托管到 Cloudflare Pages。**动态版 `web/` + FastAPI 不动**（本地开发测试用）。改 6 文件 + 新建 `static-site/` 目录（~71 JSON 数据文件）。**(1) `static-site/export.py`**（~290 行）：从 `data/sentiment.db` 导出所有 API 端点数据为静态 JSON，复刻 `app/main.py` 各端点 SQL 查询逻辑（import `app.db.get_conn` / `app.collector.fetchers.load_config` / `app.calendar.last_trading_day`，保证结构与 API 一致）。导出 71 个 JSON 文件（~63 MB）：`data/overview.json`（10 字段与 /api/overview 一致）+ 5 tab × 5 range = 25 文件（a-stock/hk/global/sentiment/industry 各 1m/3m/6m/1y/all）+ `data/metrics.json` + `data/index/{id}-all.json` × 44 指数（ohlc + signals 全历史）。**range 处理方案**：tab 端点预生成多 range JSON（前端按 state.range 直接读对应文件，逻辑最简）；index 详情仅预生成 all 全历史（44 文件，避免 44×5=220 膨胀），前端读后用 ohlc 日期范围客户端过滤 signals（`filterSignalsByRange` 函数，signals 数组小过滤开销可忽略）。**(2) `static-site/index.html`**：从 `web/index.html` 复制，路径 `/static/...` → `./...`（style.css/vendor/echarts.min.js/app.js）。**(3) `static-site/app.js`**：从 `web/app.js` 改造，仅改数据源：`fetchJSON("/api/overview")` → `fetchJSON("./data/overview.json")`；`fetchJSON("/api/a-stock?range=X")` → `fetchJSON("./data/a-stock-X.json")`（hk/global/sentiment/industry 同理）；`fetchJSON("/api/index/{id}?range=X")` → `fetchJSON("./data/index/{id}-all.json")` + `filterSignalsByRange(sig.signals, idx.data)` 客户端按 ohlc 首尾日期过滤。新增 `filterSignalsByRange()` 辅助函数。其他逻辑（renderOverview/renderAStock/renderHK/renderGlobal/renderSentiment/renderIndustry/renderIndustryGrid/renderIndustryHeatmap/ruleBar/signalColor/indexChart/lineChart/mkCard/initBackToTop/initStickyOffset）**保持功能一致**，只改数据源。手动补录入口无（与动态版一致已移除）。**(4) `static-site/style.css`**：从 `web/style.css` 原样复制（无改动）。**(5) `static-site/vendor/echarts.min.js`**：从 `web/vendor/` 复制。**(6) `static-site/DEPLOY.md`**：部署说明（Cloudflare Pages git push 自动部署 / wrangler CLI 手动部署 / 数据更新流程 / 本地预览 / range 处理方案 / 与动态版关系 / 注意事项）。**(7) `.github/workflows/deploy.yml`**（可选）：GitHub Actions 部署 workflow（仅部署静态文件，数据采集在国内本地跑；push 到 main 且 static-site/ 有改动时触发）。**验收**：① `python static-site/export.py` 生成 71 JSON 文件（63 MB）；② 静态服务 `python -m http.server 8001` 起得来，curl 验证所有 JSON 文件存在 + 内容非空（overview/a-stock-1y/hk-1y/global-1y/sentiment-1y/industry-1y/metrics/index/sh-all/index/sw_801010-all 均 200 + 有数据）；③ `node --check static-site/app.js` PASS；④ JSON 结构与 API 一致（overview 10 字段 keys match、a-stock indices 无 signals 字段与 API 一致、industry indices 含 signals/fund_flow/turnover/width 与 API 一致、index detail 含 ohlc+signals buy/sell、metrics 40 条）；⑤ 静态 JSON vs 动态 API 结构对比确认 keys 完全一致（date=20260706 / scores keys / indices_sparkline keys 全 match）；⑥ 动态版 `web/` + `app/` 未动（零改动）。**遗留**：`industry-all.json` 较大（~28 MB），如需减小体积可只部署 1y/6m range 删 all 文件（前端「全部」range 会 404，可按需禁用该按钮）；视觉验收留给用户（浏览器开 http://localhost:8001 看效果）。

**后续优化（2026-07-05，移除前端手动补录入口，worker-remove-manual）**：纯前端，不改后端 API。用户认为手动补录是敏感操作（修改数据），需权限校验或另设入口，不应在主导航暴露。改 3 文件（`web/index.html` + `web/app.js` + `web/style.css`）：① `index.html` 移除 `.periods` 内 `<button id="manual-btn">＋ 手动补录</button>` + 移除 `<div id="manual-modal">` 整块 modal HTML（含 m-date/m-metric/m-value/m-note/m-cancel/m-submit），原位留注释说明入口已移除 + 后端 API 保留；② `app.js` 移除「手动补录」整段 handler（约 36 行：modal 元素引用、manual-btn 点击打开 modal + 拉 /api/metrics 填 select、m-cancel 关闭、m-submit 提交含 /api/manual/check 查重 + POST /api/manual + renderTab 刷新），替换为 3 行注释说明入口已移除 + 后端 API 保留；③ `style.css` 清理 `.tabs > button` 选择器注释里 stale 的「/手动按钮」字样（.modal 相关样式保留，generic 无 manual 字样，无残留）。**后端 API 保留确认**：`curl /api/manual/check` → 422（路由存在，仅缺 date/metric_id 参数被拒，证明可用）；`/api/metrics` → 200；`/` → 200。**验收**：① `node --check web/app.js` PASS；② grep `manual`/`手动`/`补录` 在 web/ 下仅剩注释（index.html 1 行 + app.js 2 行 + style.css 0），无功能性入口代码（manual-btn/manual-modal/m-* ID 全清）；③ range 按钮（1月/3月/6月/1年/全部）/tab 切换/回顶/ruleBar/ECharts 不受影响（未触及其代码）。**遗留**：无。后端 `/api/manual` + `/api/manual/check` 路由完整保留，需要时直接 curl 调 API 或后续另设权限入口（如需 UI 可加登录态校验后单独路由）。

**后续优化（2026-07-05，漏跑工作日自动回填，worker-backfill）**：用户问「工作日漏跑（如周一忘周二跑），数据会回填吗？」。调研结论：历史序列指标（collect_series）自动回填（akshare 拉历史覆盖漏跑日）；今日快照类指标（collect_snapshot 如 stock_zh_a_spot 涨跌家数/成交额）漏跑无法回填（源只当日 + A1 守卫防盖错）；D2 width_history.py 是一次性脚本**未集成 runner**——漏跑工作日的宽度不会自动重算。改动：(1) app/collector/width_history.py 加 run_recent(days=30) + _upsert_width_recent() 辅助——从 mootdx_daily_raw 重算近 N 天全市场宽度（zt/dt/zb/seal_rate/up/down/amount），不依赖 collect_snapshot 当日快照（mootdx 已入库的日线即可算）。**动态 A1 近端值保护**：up/down/amount 查 DB 已有 source='akshare' 的日期并跳过（A1 全市场口径含北交所更准），只写无 akshare 值的漏跑日——比 run() 固定 A1_PROTECT_AFTER=20260702 掩码更灵活，能为漏跑的未来日期补 mootdx 值又不覆盖已采 akshare 近端值；zt/dt/zb/seal_rate 全段覆盖（mootdx 收盘封板口径替代 zt_pool 触板口径，与 run() 一致，已校验误差 ~3%）。所有 upsert WHERE source != 'manual'。CLI 加 --recent [--days=N] [--dry-run]。(2) app/collector/runner.py 加 step 9 调 width_history.run_recent(days=30)（mootdx 增量 step 7 后算近 30 天宽度，覆盖漏跑工作日）。(3) scripts/README.md 加「漏跑工作日自动回填」节，说明四类指标回填机制（历史序列自动 / 全市场宽度 step 9 重算 / 涨停池源不循环历史日需手动 python -m app.backfill 14 / 行业内宽度 step 8 重算）。**zt_pool 回填确认**：DATE_PARAM_FUNCS（zt_pool 系列）源支持近 2 周带日期回填，但 scheduler 每次只采当日（不循环历史日）；漏跑日的涨停池源值由 step 9 width_history.run_recent 用 mootdx 收盘封板口径补全（误差 ~3%），如需精确 zt_pool 触板口径回填近 2 周手动跑 python -m app.backfill 14。**验收**：① py_compile runner.py + width_history.py 通过；② --recent --dry-run 跑通（20 trading days 20260608~20260706，zt total=1967）；③ 真实写跑通（written=134, protected_akshare_dates=2）；④ A1 保护验证——20260703/20260706 up/down/amount 保持 source=akshare 未被覆盖，zt/dt/zb/seal_rate 被 mootdx 覆盖（符合设计）；⑤ 漏跑模拟——删 20260629 全 7 宽度指标后重跑 --recent，7 指标全从 mootdx 补回（zt=106/dt=41/zb=49/seal_rate=0.684/up=2382/down=2698/amount=35175 亿）；⑥ import 验证 runner+width_history 无误；⑦ git commit + push 成功（commit 3870fd4，843fda5..3870fd4 main -> main）。**遗留**：无。

**后续优化（2026-07-07，美股指数采集 us_dji/us_ixic/us_spx，worker-us-indices）**：全球 tab 配置的 3 个美股指数（us_dji 道琼斯/us_ixic 纳斯达克/us_spx 标普500）原 `enabled:false func:TODO` 未实现，本次实现采集 + 入库 + signals + 前端 + 部署。**调研**：akshare 1.18.64 有 `index_us_stock_sina(symbol)`（新浪财经美股指数），symbol 映射 `.DJI`=道琼斯/`.IXIC`=纳斯达克/`.INX`=标普500（另 `.NDX`=纳斯达克100 未用）。返 2004-01-02 起 ~5660 行全量历史，列 `date/open/high/low/close/volume/amount`（英文小写，与 collect_index 通用路径已兼容，**无需改 fetchers.py**——`_date_col` 认 `date`、`g()` 认 `close/open/high/low/amount`，pct_change 自算）。近端 amount=0（仅 volume），无碍。**网络**：trust_env=False（base.py 全局 patch）直连新浪可访问，无需代理（实测无封）。**改动**：(1) `config/indicators.yaml` us_dji/us_ixic/us_spx 三行 `enabled:true func:index_us_stock_sina symbol:.DJI/.IXIC/.INX`（替换 TODO+空 symbol+enabled:false）；(2) fetchers.py **零改动**（通用 collect_index 路径直接处理）。**采集**：3 指数 upsert 入 index_daily——us_dji 5663 行/us_ixic 5661 行/us_spx 5664 行，日期范围 20040102~20260706。**signals**：signals.compute() 重算全 47 enabled 指数（DELETE+INSERT），signal_daily 13054 条，其中美股 577（us_dji buy60/sell134、us_ixic buy45/sell159、us_spx buy50/sell129；C1 买 RSI上穿30 + D1 卖 20日高回落5% + B 标注 vs前买）。**前端**：renderGlobal 遍历 market=global indices 调 indexChart，原 enabled:false 为空，现 3 美股指数折线+买卖点；前端代码零改动（已有逻辑）。**验收**：① `/api/global?range=1y` indices 含 us_dji/us_ixic/us_spx 各 251 pts（20250707~20260706）；② `/api/index/us_dji?range=1y` signals 5 条（含 sell `20日高回落5%...vs前买+12.67%[止盈]`）；③ `node --check web/app.js` PASS；④ py_compile fetchers.py/main.py/signals.py PASS；⑤ static-site global-1y.json 含 3 美股指数 + index/us_dji-all.json(623KB)/us_ixic-all.json(610KB)/us_spx-all.json(590KB) 生成。**部署**：deploy.sh export 74 JSON（60.5MB，index 详情 47 文件含 3 新美股）+ git commit 10eac45 push 成功；config+db 单独 commit ed2e1de push 成功（main->main）。**遗留**：无。注：index_us_stock_sina 返全量历史不滤日期（与 stock_zh_index_daily/stock_hk_index_daily_sina 一致，每次 upsert 全量 ~5660 行幂等无碍）。

**D1 数据现状（2026-07-06 更新）**：东财 push2his IP 封锁致 akshare `stock_daily_raw` 0 行，已改 **mootdx（TCP 7709 不封 IP）主力**采全：`mootdx_daily_raw` 表 5203 只 SH/SZ × 全历史 = **16,385,719 行**（最早 1990-12-19，30min 跑完）。324 只北交所 mootdx `std` 市场不覆盖（留 D3 BaoStock 兜底）。turnover 全 NULL（mootdx 无此字段，D3 补）。D2 算宽度用 `mootdx_daily_raw`（pct_change 自算，跨除权日失真注意）。

**已知大变更（终验供用户定夺）**：
- B1/C1/B2 加 5 宏观指标（cn10y/us10y/wti_oil/comex_silver/a_div_yield）进 cross.py 跨市场 trim-mean 池 + F1 加 31 申万行业指数 → 信号 113→1300（每指数每年 1-5 个，事件化无聚类，合理）。
- F1 关键坑：申万源 swsresearch.com 本地 DNS SERVFAIL，`app/collector/base.py` monkey-patch `socket.getaddrinfo` 绕过（只影响该域）。
- 数据源绕开：中证红利 sina 停更(2019)→csindex 源；QVIX1000 源滞后停 20260313；北向资金 2024-08 停更（前端已标注）。

**后续优化（2026-07-07，外部验证报告 BUG-F/G/H 修复，worker-verify-fix）**：依据 `交易信号网站验证报告.md`（独立 AI 测试代理复现，回测逻辑诚实可复现）修 3 个 P3 体验/合规增强 bug，不改信号触发逻辑（只改文案/加文档/加脚本）。**BUG-F（卖点语义文案）**：ruleBar "胜率50.6%" 易被散户误读为"跟着卖就赢"，改 `web/app.js`+`static-site/app.js` ruleBar 摘要"20日高回落5%（**止盈/减仓提示，非高胜率卖点**；卖点后 10 日走弱概率≈50% 接近随机，不可作独立卖出指令）"+ D1 回测结论行改"卖点后 10 日市场**走弱概率 50.6%（接近随机，非高胜率卖点）**...**不可作为独立卖出依据**"；`REQUIREMENTS.md` §7.2 卖点语义强调"D1 是止盈减仓提示，非做空/反向交易指令；胜率≈50% 接近随机，不可作为独立卖出指令"+ §7 注加"买点 C1 反而有微弱正期望"+ 保留"最不坏非好方案"诚实声明。**BUG-G（情绪分公式透明度）**：`REQUIREMENTS.md` 新增 §6.5 情绪分公式公开披露章节——a_sentiment 披露 6 分项固定权重公式（ratio 25%/zt 20%/zhaban 15%/lianban 15%/amount 10%/north 15%）+ 120 日滚动百分位归一化（min_periods=10）+ direction=negative 取反（100−p）+ 缺项可用权重重归一化（`score=Σ(w_i×norm_i)/Σ(w_i for available i)`，至少 3 分项出分）；cross_market 披露 trim-mean 池（38 个 enabled simple metric 全列出：A 股宽度 9 + 资金 3 + 情绪 10 + 港股全球 8 + 试采 8）+ 精确算法（`dropna→len<3 返 NA→升序 iloc[1:-1] 去最高 1+最低 1→其余算术均值`，非 10% 截尾）+ derived metric（cn_us_spread/a_width_fengban_rate）不进池避免双重计入。实现校对自 `app/compute/sentiment.py`+`cross.py`+`normalize.py`。**BUG-H（买→卖配对回测）**：新建 `a-stock-data/backtest_pair.py`（独立脚本，自复刻 RSI(14) EWM α=1/14 + D1 high-based 20 日回落 5%，不 import app，与 backtest_sell.py 一致）——C1 买入→持有至下一个 D1 卖出（或 60 交易日时间止损）→算完整回合收益（持有期收益/最大回撤/年化/平均持有天数）。13 主要指数全史 **523 回合**：持有期均值 **+0.67%**/中位 -0.56%/胜率 **44.6%**/盈亏比 1.56/年化 **+2.52%**/平均持有 **27.2 日**/最大单回合回撤 55.2%。对比独立买点（C1 后 10 日：n=914 均值 +0.75%/胜率 53.4% 正期望）与独立卖点（D1 后 10 日：n=2449 均值 +0.10%/胜率 50.1% 接近随机）。**关键发现**：D1 卖点平仓回合（86.4%）均值 -0.19%/胜率 38.5%（弱——趋势转弱已回吐浮盈），时间止损回合（12.6%）均值 +6.49%/胜率 83.3%（强——趋势持续未触发 D1 兑现大段涨幅）；策略收益主要由"未触发 D1 的强势回合"贡献，D1 卖点作用是"转弱时止损避免更大亏损"而非"抓住赢家"。窗口对比：2016+ 273 回合年化 +7.81% / 近3年 94 回合年化 +32.21% / 近1年 16 回合年化 +67.88%（近端强势市拉高，含幸存者偏差）。报告 `10-买卖点配对回测.md`。**验收**：① `node --check web/app.js` + `node --check static-site/app.js` PASS；② `py_compile backtest_pair.py` PASS；③ backtest_pair.py 跑通生成报告；④ 文案改"走弱概率≈50%"强调止盈提示非高胜率；⑤ REQUIREMENTS §6.5 披露 cross_market trim-mean 池 + a_sentiment 权重公式。**遗留**：无（仅改文案/加文档/加脚本，未触信号触发逻辑，signal_daily 不变）。git commit c185c91 + push 成功（main -> main）。

**后续优化（2026-07-07，外部验证报告 BUG-E 修复，worker-bug-e）**：依据 `交易信号网站验证报告.md` BUG-E（P3 交互增强）补 3 类前端交互控件，纯前端逻辑不改后端/signals.py。改 4 文件（`web/app.js`+`web/style.css`+`static-site/app.js`+`static-site/style.css`，动态版与静态版逻辑一致仅数据源不同）。**(1) 指数筛选（A 股/港股 tab）**：`renderAStock`/`renderHK` 在 ruleBar 之后渲染 `.filter-bar` 条，内含 `<select>` 列出当前 tab 全部指数 + "全部指数（N）"选项；选特定指数只渲染该指数 `indexChart` 折线，"全部"显示所有。**不影响数据**（仍 fetch 全部，只跳过未选的渲染）；**跨 tab 状态安全**：`indexFilterBar()` 检测当前 tab 不含已选 id 时回退"全部"（防 A 股选 sh000001 后切港股空渲染）。state 加 `indexFilter:"all"`。**(2) 行业筛选（行业 tab）**：`renderIndustry` 在热力图后渲染 `.filter-bar` 含 `<input type="search">`，输入名称/代码关键词实时过滤行业网格（`filterIndicesByName` 按 name 或 id 模糊匹配，250ms 防抖）；section title 显示 `shown/total` 计数。state 加 `industrySearch:""`。**(3) 热力图近1日/近5日切换**：`renderIndustryHeatmap` 重构——不再用 `mkCard`（其标题不支持嵌入控件），自建 `.chart-card` 含 `<h3 class="with-toggle">` 左侧标题 + 右侧 `.heatmap-toggle` 按钮组（近1日/近5日/全部）；按 `state.heatmapRange` 决定 y 轴维度（"1d"→["近 1 日"] / "5d"→["近 5 日"] / "all"→两行），data 仅推对应 yIdx；点击按钮改 state 后 `renderTab()` 重渲染（保持其他筛选状态）。**概览 tab 的热力图也获得切换按钮**（renderOverview 调同一函数，默认 "all" 显示两行，与原行为一致无回归）。state 加 `heatmapRange:"all"`。**(4) CSS**：`.filter-bar`（flex/gap/复用 .periods 配色风格）+ `.chart-card h3.with-toggle`（flex space-between）+ `.heatmap-toggle`（inline-flex 按钮组，active 蓝底白字，hover 浅灰）。**验收**：① `node --check web/app.js` + `node --check static-site/app.js` PASS；② `git status` 仅 4 前端文件改动（app/ 后端零改动，API 定义上不受影响——本地 dev server 未运行无法 curl，但筛选是纯前端逻辑）；③ 控件不破坏现有布局（.filter-bar 在 ruleBar 之后、折线之前，非 sticky 不与 .tabs/.rule-bar sticky 冲突；热力图切换嵌卡片标题内不遮折线）；④ 静态版同步（render 函数与动态版一致，仅 fetchJSON URL/filterSignalsByRange 差异保留）。**遗留**：视觉验收留给用户硬刷新（A 股/港股下拉选指数看折线聚焦、行业搜索框输"银行"看网格过滤、热力图点近1日/近5日看 y 轴切换）。

## 工作约定（子进程必读）

1. **领任务**：读本文件，找第一个 `状态: pending` 且 `依赖` 已满足的任务，把状态改 `in_progress`、填 `负责人`（你的标识）。
2. **干活**：按 `描述` 做，达到 `验收标准`。改动前先读相关源码。技术细节自己定；**碰到方向性分叉不要猜——停下、在 `结果备注` 写明、汇报给监管**。
3. **写结果**：做完（或失败）后在 `结果备注` 写：改了哪些文件、做了什么、成功 / 失败、遗留问题。状态改 `done` / `failed` / `blocked`。
4. **汇报**：你的最终消息就是汇报。说清：做了什么、改了哪些文件、验收标准是否达成、有无遗留、下一步建议。
5. **环境约束**（踩过的坑）：
   - pypi / github 用清华镜像；Clash 代理 `127.0.0.1:7890` 拦截东财 → 全局 `trust_env=False`。
   - 东财 push2 / clist / 板块端点反爬封 → 用 sina 源或直爬 + `em_get` 防封（1s 节流 + 0.1-0.5s jitter + HTTPAdapter Retry 429/5xx）。
   - 手动值保护：upsert 的 `ON CONFLICT DO UPDATE` 末尾必须 `WHERE daily_metric.source != 'manual'`（防日采集覆盖手动补录）。
   - NaN 过滤：`collect_series` 里 `if v != v: continue`（`float(NaN)` 不抛异常，必须显式判）。
   - 不要 `cd` 进 compound 命令（用绝对路径）；不要 commit / push（用户没让）。
6. **验收（2026-07-06 调整）**：监管**不自己跑命令验收**（curl/grep/DB 在监管上下文费 token）。改派**验收子进程**（fresh context）跑抽查（DB/curl/复跑/语法），结论写进任务条目「验收备注」+ 向监管汇报。监管读干活汇报 + 验收汇报决定放行。review gate 任务必派验收子进程；非 review gate 可省（信任干活子进程自验）。不暂停等用户，全部完成或卡住才通知。最终用户 + 外部测试整体验收。详见记忆 `supervisor-loop-mode`。
7. **测试**：API 改动用 `curl localhost:8000/...` 验；采集改动跑 `python -m app.collector.runner`；计算改动跑 `python -m app.compute.runner`；前端改动浏览器看。

## 任务清单

执行顺序按编号（A1→A2→A3→G1→E1→E2→E3→B1→C1→B2→F1→F2→F3→D1→D2→D3→S1），依赖不满足的跳过待后续。**长任务（D1）到时监管可决定后台跑。**

---

### TASK-A1 🔴 上涨家数数据回归排查与修复
- 状态: done
- 负责人: worker-A1
- 描述: 回归报告新问题 #2。`a_width_up_count` 的 20260703 值从 3803（与雪球 3804 一致，正确）变为 1856（差 -51%），source=akshare。排查根因并修复，使历史值恢复正确。
- 排查方向: (1) `SELECT date,value,source FROM daily_metric WHERE metric_id='a_width_up_count' AND date IN ('20260703','20260706')` 确认现状；(2) 复跑 `stock_zh_a_spot` + `count_up` transform 看返回范围（1856≈沪市主板量，疑似只回了部分市场）；(3) 查 `app/collector/fetchers.py` 的 `count_up` + `collect_series` 是否在 07-06 修复轮被改动；(4) 查是否有覆盖路径把今日快照写成历史日期。
- 验收标准: 20260703 上涨家数恢复 ~3803（与雪球一致，±5 家容差）；根因写进 `结果备注` + NOTES.md；后续采集不再回归。
- 依赖: 无
- review gate: 是（数据准确性，用户验收）
- 结果备注: 根因=手动跑 `runner 20260703` 回填时，纯当日快照 `stock_zh_a_spot`（无 date 参数）仍返回 07-06 盘中数据却被盖章成 20260703，覆盖了 07-05 正确采集的 3803（collect_log 铁证：07-05 19:24=3803✅ → 07-06 13:10=1856❌）。排除「只回部分市场」假设（实测 sina 返回 5526 行=全市场）。同批次 down_count(1628→3524)、amount(32046.97→23303.91) 也被污染。改动：(1) `app/collector/fetchers.py` `collect_snapshot` 加守卫——func 不在 DATE_PARAM_FUNCS/DATE_RANGE_FUNCS 且 `date!=last_trading_day()` 则跳过（zt_pool 带日期参数近 2 周仍可回填，不受影响）；(2) SQL 恢复 20260703 三值 up=3803/down=1628/amount=32046.97034002。验收：API 确认 20260703 a_width_up_count=3803（与雪球 3804 差 1，±5 内✅）；复跑 `collect_snapshot(up_count, '20260703')` 返回 skip 不再覆盖。根因已写 NOTES.md §4.1。遗留：20260706 三值为 13:36 盘中所采非收盘值，待 scheduler 15:33 重采；守卫依赖 trade_dates 缓存（含 2026 全年），跨年需 refresh（scheduler 当前未调 refresh_trade_dates，建议后续补）。
- 验收备注: 监管独立抽查通过。DB 确认 20260703 up=3803/down=1628/amount=32046.97（source=akshare）；API /api/a-stock 返 3803.0；fetchers.py:113-119 守卫正确（today-only 快照+date≠last_trading_day 才 skip，proceed 路径 121+ 完好，zt_pool 等带日期参数不受影响）。放行。遗留跨年 trade_dates 刷新 → 已立 TASK-S1。

### TASK-A2 🟡 QVIX(1000) 0.0 异常值排查与过滤
- 状态: done
- 负责人: worker-A2
- 描述: 回归报告新问题 #1。`a_qvix_1000` 有 28 条值为 0.0（QVIX 正常 15-30）。NaN 已过滤但 0.0 漏过。排查 0.0 来源（源占位 / 解析缺失），加过滤，清已入库 0.0。
- 排查方向: 查 `app/collector/fetchers.py` QVIX 采集 + `collect_series` 的 `v!=v` 过滤（0.0 不是 NaN 所以漏过）；决定过滤策略（跳过 0.0 或当 NaN）；`DELETE FROM daily_metric WHERE metric_id='a_qvix_1000' AND value=0.0`。
- 验收标准: DB 中 a_qvix_1000 无 0.0 值；采集加 0.0 过滤；根因写 NOTES.md。
- 依赖: 无
- review gate: 否
- 结果备注: 根因=akshare `index_option_1000index_qvix()` 源返 34 行 close=0.0（字面 float 0，非 NaN），分两种形态：整行 NaN+close=0.0（源占位）和 OHLC 有效+close=0.0（源 bug，close<low 不可能）。DB 34 个 0.0 日期与源 34 个一一对应、无多余，污染纯来自源。`collect_series` 的 `if v!=v` 只判 NaN，0.0 漏过。改动：(1) `config/indicators.yaml` 给 `a_qvix_300`/`a_qvix_1000` 加 `drop_zero: true`（300 防御性），yaml 头注释补字段说明；(2) `app/collector/fetchers.py` `collect_series` 在 NaN 过滤后加 `if drop_zero and v == 0: continue`（按指标开关，不误伤资金流/IPO 数等合法 0）；(3) SQL 删 a_qvix_1000 34 行 0.0（a_qvix_300 0 行确认无）。验收：DB a_qvix_1000=807 条全非 0（min 11.76/max 43.57）、a_qvix_300=1567 条全非 0；复跑 collect_series(qvix_1000) 返 807 行 0 个 0.0；`/api/a-stock?range=all` 两 QVIX data 数组均无 0.0；`a_fund_north`/`ipo_count` 无 drop_zero 标记，合法 0 不受影响。附带修复「最新 0.0」（qvix_1000 最新非空值现停在 20260313=17.83，因源 20260313 后只返 0.0/NaN 占位至 20260626，属源问题非脚本 bug）。根因详写 NOTES.md §4.2。
- 验收备注: 监管独立抽查通过。DB a_qvix_1000=807 行 0.0_count=0（min 11.76/max 43.57）、a_qvix_300=1567 行 0.0_count=0；fetchers.py:91 `drop_zero=bool(metric.get('drop_zero'))` + :100 `if drop_zero and v==0: continue` 按指标开关；indicators.yaml 两 QVIX 标 `drop_zero: true`。放行。qvix_1000 latest=20260313 是源滞后（BUG-010/015 已知），非 A2 问题。

### TASK-A3 🟢 北向资金前端标注停更
- 状态: done
- 负责人: worker-A3
- 描述: 回归报告新问题 #3。北向资金已过滤 null 但前端空白，用户分不清停更还是故障。改 `config/indicators.yaml` 名称「北向资金净流入(2024年8月停更)」或前端图表区显示停更提示。
- 验收标准: 概览 / A 股看板北向资金处可见「2024 年 8 月停更」标注。
- 依赖: 无
- review gate: 否
- 结果备注: 两路并做。(1) `config/indicators.yaml` 把 `a_fund_north.name` 从「北向资金净流入」改为「北向资金净流入(2024年8月停更)」——全局生效，看板图例 / 手动补录下拉 / 未来概览 KPI 卡都带标注；(2) `web/app.js` 给 `mkCard`/`lineChart` 加可选 `hint` 参数（默认 null，不影响其他调用方），`renderAStock` 的「资金面」组传橙色提示条文案「注：北向资金数据源自 2024 年 8 月起停更（东财停止实时披露），该序列冻结在 2024-08-16，1 年期窗口内为空属正常」；`web/style.css` 加 `.chart-hint` 样式（#fff2e8 底 / #ffbb96 边 / #d4380d 字）。验收：DB 确认 a_fund_north 最新日期=20240816、2264 条；curl `/api/a-stock?range=1y` 返回 name=`北向资金净流入(2024年8月停更)`、len=0（1 年窗口外，符合预期），同组 a_fund_margin(241)/a_fund_main(120)/a_amount(2) 有数据 → 资金面组渲染 → 提示条显示；curl `/api/metrics` 手动补录下拉 name 已带停更标注；`/static/app.js`、`/static/style.css` 已生效；其他 tab（sentiment 等）lineChart 调用未受影响（hint 默认 null）。NOTES.md §4 修复表补 A3 行。遗留：无；浏览器可能缓存 JS/CSS，用户硬刷新（Cmd+Shift+R）可见新提示条。
- 验收备注: 监管独立抽查通过。API /api/metrics 返 a_fund_north name=`北向资金净流入(2024年8月停更)`；app.js:30 mkCard / :42 lineChart 加 `hint` 参数、:183 资金面组停更文案；config:24 name 已改；style.css:56 `.chart-hint` 样式到位。放行。

### TASK-G1 概览美化（第一版）
- 状态: done
- 负责人: worker-G1-retry
- 描述: 重写 `web/app.js` 的 `renderOverview` + 扩 `app/main.py` 的 `/api/overview` 返回今日快照。落地（上→下）：1) KPI 卡片行（情绪分 / 跨市场分 / 涨停 / 跌停 / 炸板率 / 成交额 / 北向 / 两融，今日值）2) 主要指数 sparkline 网格（上证 / 深成 / 沪深300 / 创业板 / 科创50 / 恒生 / 恒生科技，mini 折线 + 今日涨跌）3) 市场宽度图（上涨 / 下跌家数堆叠面积，近 1 月）4) 跨市场综合评分折线（近 6 月，保留现配色）5) A 股综合情绪分折线（近 6 月，新增）6) 今日买卖点 + 近期冰点日（保留美化）7) 申万行业涨跌幅热力图（联动 F1；F1 未完成时先占位 / 隐藏）。
- 验收方向: `/api/overview` 扩返回 today 快照（各指标最新值）+ 指数 sparkline 数据；前端 ECharts 落地 7 区块；`web/style.css` 配卡片 / 网格样式。
- 验收标准: 概览可见 7 区块（行业热力图可占位）；视觉清爽；不破坏其他 tab。
- 依赖: 无（行业热力图软依赖 F1，可占位）
- review gate: 是（UI 第一版，用户验收）
- 结果备注: 接续上一个 worker-G1（429 中断）。**后端已由前一进程完成**：`app/main.py` `/api/overview` 已扩返回 `today`(scores+metrics) / `indices_sparkline`(7 指数近30日 closes+dates+pct_change+last_date) / `width_1m`(up/down 近1月) / `cross_market_6m`(近6月带 is_freeze/is_overheat) / `a_sentiment_6m`(近6月)，并保留原 `scores`/`signals_today`/`recent_freeze`/`date`。py_compile 通过。**本次完成前端**：重写 `web/app.js` `renderOverview`（原版仅 2 分数卡 + 单独 fetch /api/sentiment?range=3m 画 3 月跨市场图，未用新数据）。新版落地 7 区块：1) KPI 卡片行——`today.scores`(2) + `today.metrics`(6) 共 8 卡，分数带冰点/过热 tag、北向带「停更」stale tag、炸板率按 0-1 小数×100 显示、各卡带 unit·date 副标题；2) sparkline 网格——7 指数 mini 折线（auto-fill 180px 网格，红涨绿跌 pct 徽章 + areaStyle 0.12 透明度 + 无坐标轴 + tooltip）；3) 市场宽度堆叠面积（up/down stack=width，近1月）；4) 跨市场综合评分近6月折线（保留 visualMap lte20红/20-80蓝/gt80绿 dimension:1）；5) A股综合情绪分近6月折线（新增，单色蓝）；6) 今日买卖点+近期冰点日改 2 列卡片排版（signals 为空时显「今日无买卖点信号」empty-note）；7) 申万行业热力图占位 div + 注释「待 F1 接入」。`web/style.css` 新增 `.section-title`/`.kpi-row`/`.card.kpi`/`.card-sub`/`.tag.stale`/`.spark-grid`/`.spark-cell`/`.spark-head`/`.pct-badge`/`.spark-date`/`.ov-2col`(响应式 720px 转 1 列)/`.empty-note`/`.placeholder-body` 样式。**移除**旧版对 `/api/sentiment?range=3m` 的二次 fetch（改为直接用 overview 返回的 6 月数据，减少请求）。未改 `mkCard`/`lineChart`/`indexChart`/`fetchJSON` 及 renderAStock/HK/Global/Sentiment（其他 tab 不受影响）。验收：`node --check web/app.js` 通过；`python -m py_compile app/main.py` 通过；`curl /api/overview`=200 且含全部 9 字段（today.scores 2/today.metrics 6/indices_sparkline 7/width_1m/cross_market_6m 138 点/a_sentiment_6m 7 点）；`curl /api/a-stock`/`/hk`/`/global`/`/sentiment` 均 200；`/static/app.js`/`/static/style.css` 已生效。**数据层观察（非代码 bug）**：width_1m 仅 2 点（20260703/20260706，A1 回归致近 45 日仅这两日有 up/down count，图稀疏但正确）；a_sentiment_6m 仅 7 点（该分数仅近 7 日有计算）；signals_today 为空（20260706 无买卖点，显 empty-note）。视觉留给监管终验（浏览器硬刷新 Cmd+Shift+R）。
- 验收备注: 监管独立抽查通过。/api/overview 9 字段齐全（today.scores 2/today.metrics(list) 6/indices_sparkline 7/width_1m/cross_market_6m 138 点/a_sentiment_6m 7 点 + scores/signals_today/recent_freeze/date）；app.js `node --check` OK；其他 4 tab（a-stock/hk/global/sentiment）全 200。视觉留给终验（用户硬刷新看）。width_1m 仅 2 点 / a_sentiment_6m 仅 7 点是数据稀疏（D1/D2 回填后改善），非 G1 bug。放行。

### TASK-E1 买卖点逻辑优化（事件化 + 跨市场共振）
- 状态: done
- 负责人: worker-E1
- 描述: 改 `app/compute/signals.py`。当前每个满足日都标（RSI≤30 每天都标）→ 标注过多。新逻辑：买点 = RSI(14) **上穿 30** 且 跨市场分 < 30；卖点 = RSI(14) **下穿 70** 且 跨市场分 > 70。事件化（一次超卖 / 超买期只 1 个点）+ 共振（冰点 / 狂热才出）。改完重算 `signal_daily`。
- 验收方向: 「上穿」= 前一日 RSI>30 且当日 RSI≤30 之类的 cross 判定（自己定准确的）；重算后买卖点数大幅下降；`python -m app.compute.runner` 跑通。
- 验收标准: signals.py 改为事件化 + 共振；一次超卖期只 1 个买点；重算无报错。
- 依赖: 无
- review gate: 否（E3 后用户看效果）
- 结果备注: 改 `app/compute/signals.py`。新逻辑：买=RSI(14) 上穿 30（`rsi_prev<=30 & rsi>30`，超卖结束升回 30 之上）且 cross<30（市场冰点）；卖=RSI(14) 下穿 70（`rsi_prev>=70 & rsi<70`，超买结束跌回 70 之下）且 cross>70（市场狂热）。语义按任务说明：买在「超卖结束、有望反弹」时点（RSI 从 ≤30 升回 >30 那天），卖在「超买结束」时点（RSI 从 ≥70 跌回 <70 那天）。事件化：只在穿越当日标，一次连续超卖/超买期只 1 个点（RSI 反复进出则每次退出各 1 个点，算独立事件——如 csi1000 2023-08 三次买点 0817/0822/0829 对应三个独立超卖期，符合语义）。共振阈值从旧 <80/>20 收紧到 <30/>70。cross 判定用 `rsi.shift(1)`，首日 NaN 经 `.fillna(False)` 跳过。reason 字符串改「RSI上穿30(29->34),cross=8」格式便于核查。验收：(1) `python -m app.compute.runner` 跑通无报错，输出「买卖点=113个」；(2) signal_daily 2425→113（buy 898→55 / sell 1527→58，降 95.3%）；(3) 逐条复核全部 113 条信号——每条 buy 均满足 rsi_prev<=30 & rsi>30 & cross<30，每条 sell 均满足 rsi_prev>=70 & rsi<70 & cross>70，0 条异常；(4) 抽查 csi1000 10 个买点分布合理（2017/2018/2020/2023/2024/2025 各超卖期各 1 点，20240206 rsi_prev=17.28→31.59 深度超卖期也只 1 点）；(5) py_compile 通过；API `/api/index/{id}` 返回信号正常（如 csi1000=15 条 10buy/5sell），/api/overview 等 4 端点 200。买卖点数量分布：csi1000(10b/5s) > hsi(6/10) > kc50(8/5) > hscei(6/8) > sz(6/3) > sh(5/7) > csi500(5/3) > cyb(4/7) > hstech(3/3) > hs300(2/7)。未改 runner/normalize/其他文件。遗留：无；E2 文档化时引用本规则即可。
- 验收备注: 

### TASK-E2 买卖点逻辑文档化
- 状态: done
- 负责人: worker-E2
- 描述: `REQUIREMENTS.md` 新增「§买卖点逻辑」章节：当前规则（事件化 + 共振）、参数（RSI14、30/70 阈值、cross 30/70）、变更历史、与旧逻辑差异。
- 验收标准: REQUIREMENTS.md 有该章节，规则与 signals.py 一致。
- 依赖: E1
- review gate: 否
- 结果备注: 改 `/Users/linhuichen/code/trade/REQUIREMENTS.md` 一个文件。把原 §7「买点/卖点标注」整段重写为 §7「买点/卖点逻辑」+ 5 个子节：§7.1 参数表（RSI 周期 14、买触发 rsi_prev≤30 且 rsi>30、卖触发 rsi_prev≥70 且 rsi<70、买共振 cross<30、卖共振 cross>70）；§7.2 语义说明（买在超卖结束升回 30 之上、卖在超买结束跌回 70 之下、事件化=一次超卖/超买期 1 点、共振=冰点/狂热才出、首日 shift NaN 跳过、cross reindex 对齐）；§7.3 reason 字符串格式（`RSI上穿30(29->34),cross=8` / `RSI下穿70(72->68),cross=82`，NaN 退化 `RSI=NA` / 省略 cross 段）；§7.4 变更历史（2026-07-05 初版每满足日都标+<80/>20 → 2026-07-06 E1 事件化+<30/>70，2425→113 -95.3%）；§7.5 与旧逻辑差异对比表（8 维度：买/卖触发条件、买/卖共振阈值、一次期标几点、信号密度、语义、reason 格式）。**逐条核对 signals.py 当前实现完全一致**：`_rsi(period=14, EWM α=1/14, adjust=False)`、`cross.reindex(close.index)`、`rsi.shift(1)`、buy=`(rsi_prev<=30)&(rsi>30)&(cross<30)`、sell=`(rsi_prev>=70)&(rsi<70)&(cross>70)`、`.fillna(False)`、reason f-string 取整 `:.0f` 全部对上。附带一致性修正：§2 决策表「买点/卖点标注」描述改为「RSI 主信号 + 跨市场分共振（事件化）」；§9 加 2026-07-06 E1 变更条目；§10 实现状态「买卖点 2425 个」更新为「113 个（事件化+共振，E1；旧逻辑 2425 个）」；最近更新日期→2026-07-06。未改 signals.py 或其他代码。验收：§7 章节存在且规则与 signals.py 一致 ✓；含变更历史 + 与旧逻辑差异表 ✓。遗留：无。
- 验收备注: 

### TASK-E3 买卖点规则说明条（每个看板前）
- 状态: done
- 负责人: worker-E3
- 描述: 前端每个看板（A 股 / 港股 / 全球 / 综合情绪 / 行业）前加规则说明条（小字可折叠），如「买: RSI(14)上穿 30 & 跨市场分<30 · 卖: RSI(14)下穿 70 & 跨市场分>70」。点开看详细。改 `web/app.js` + `web/style.css`。
- 验收标准: 各看板可见规则说明条；折叠 / 展开正常；文案与 signals.py 一致。
- 依赖: E1
- review gate: 是（UI，用户验收）
- 结果备注: 改 2 文件 `web/app.js` + `web/style.css`。**(1) `web/app.js` 新增可复用函数 `ruleBar()`**（紧跟 `fetchJSON` 后，与 `mkCard`/`lineChart`/`indexChart` 同级helper）：默认收起显示一行摘要「**买**: RSI(14)上穿30 & 跨市场分<30 · **卖**: RSI(14)下穿70 & 跨市场分>70」（买红卖绿，复用 `.buy`/`.sell` 配色）；点击展开详细 4 行——参数（RSI 周期=14 Wilder EWM α=1/14；买触发 rsi_prev≤30 且 rsi>30；卖触发 rsi_prev≥70 且 rsi<70）、共振阈值（买 cross<30 冰点 / 卖 cross>70 狂热，过滤伪信号）、语义（买在超卖结束升回30之上、卖在超买结束跌回70之下、事件化一次连续超卖/超买期只标 1 点穿越当日、RSI 反复进出每次退出各 1 点独立事件、首日 shift NaN 跳过、cross 缺失跳过）、reason 示例（`RSI上穿30(29->34),cross=8` / `RSI下穿70(72->68),cross=82`）+ 「信号为参考用，非交易指令」。折叠用 `.hidden` class 切换 + ▸/▾ 三角图标。**(2) 5 个 render 函数各调一次 `ruleBar()`**：`renderOverview`（在 #6 今日买卖点区块前）、`renderAStock`/`renderHK`/`renderGlobal`/`renderSentiment`（各 tab 顶部 `content.innerHTML=""` 后）。行业 tab（F1）未建，函数已留好接口——F1 的 renderIndustry 直接 `ruleBar()` 即可复用。**(3) `web/style.css` 新增 `.rule-bar`/`.rule-summary`/`.rule-toggle`/`.rule-text`/`.rule-detail`/`.rule-detail.hidden`/`b.buy`/`b.sell` 样式**：浅灰底(#fafbfc)+细边、12px 小字不抢眼、cursor pointer、user-select none、虚线分隔摘要与详细，不破坏现有样式。**文案一致性**：逐条对齐 `app/compute/signals.py`（`_rsi(period=14, EWM α=1/14, adjust=False)`、`rsi_prev<=30 & rsi>30 & cross<30`、`rsi_prev>=70 & rsi<70 & cross>70`、`shift(1).fillna(False)`、reason f-string）+ REQUIREMENTS.md §7（参数表 §7.1 / 语义 §7.2 / reason 格式 §7.3 全对上）。验收：`node --check web/app.js` 通过；awk 确认 5 个 render 函数各 1 个 `ruleBar()` 调用（共 5 处，renderOverview/AStock/HK/Global/Sentiment）；grep 确认规则文案「RSI(14)上穿30」「RSI(14)下穿70」「跨市场分」存在；curl /api/overview /a-stock /hk /global /sentiment 均 200；`/static/app.js`（含 7 处 ruleBar）/`/static/style.css`（含 9 处 rule-bar）已热加载生效。未改 `mkCard`/`lineChart`/`indexChart`/`fetchJSON` 签名（其他调用方不受影响）；未改后端。遗留：无；浏览器可能缓存 JS/CSS，用户硬刷新（Cmd+Shift+R）可见规则条。
- 验收备注: 

### TASK-B1 国债指标（中 + 美 10Y + 中美利差）
- 状态: done
- 负责人: worker-B1
- 描述: 加 3 指标入 `config/indicators.yaml` + 采集 + 前端全球看板展示：CN 10Y（`bond_china_yield`，期限 10 年）、US 10Y（`bond_zh_us_rate`，美国 10 年）、中美利差（derived `cn10y - us10y`）。归 global 组。
- 验收方向: 先 curl 确认 `bond_china_yield` / `bond_zh_us_rate` 返回 + 字段（trust_env=False + 东财防封）；再加 config；采集入库；前端全球看板加折线。
- 验收标准: 3 指标有数据（非全 null）；中美利差 = cn-us；前端全球看板可见 3 条折线。
- 依赖: 无
- review gate: 否
- 结果备注: 改 4 文件。(1) `config/indicators.yaml`：global 组加 3 指标——`cn10y`(simple, func=bond_china_yield, column='10年', filter={曲线名称: 中债国债收益率曲线})、`us10y`(simple, func=bond_zh_us_rate, params={start_date:'20160101'}, column=美国国债收益率10年)、`cn_us_spread`(derived, formula="cn10y - us10y")；yaml 头注释补 `filter`/`lookback_days` 字段说明。(2) `app/collector/fetchers.py`：SERIES_FUNCS 加 `bond_china_yield`/`bond_zh_us_rate`；新增 `_fetch_bond_china_yield(fn, lookback_days=3650)` 辅助函数——bond_china_yield 限制 start/end 间隔<1年（超期返回空 df），按 350 天窗口分块拉取后 pd.concat 拼接（默认回溯 3650 天≈10 年，约 11 个 chunk）；`collect_series` 加 bond_china_yield 分块分支 + 通用 `filter` 行过滤（筛「中债国债收益率曲线」一行）。(3) `app/main.py`：`/api/global` extras 列表加 cn10y/us10y/cn_us_spread。(4) `web/app.js`：`renderGlobal` extras 对象加 3 指标各画一条折线。**源验证**：bond_china_yield 返回多曲线（中债国债/中短期票据/商业银行普通债），筛「中债国债收益率曲线」取「10年」列；bond_zh_us_rate 返回中美国债各期限，取「美国国债收益率10年」列（NaN 过滤靠 collect_series 的 v!=v 判断）。**采集**：单采 cn10y(2498 行,20160708~20260706) + us10y(2628 行,20160104~20260702) 入库；derived.compute_derived_formulas 算 cn_us_spread(2333 行,20160708~20260702) 入库。中美利差 2333<2498/2628 因 CN/US 交易日不完全重叠（pandas Series 按日期 index 对齐，仅两方都有值的日子出非 NaN，dropna 后入库）。**验收**：(a) 3 指标非全 null——cn10y 0 null/us10y 0 null/cn_us_spread 0 null；(b) 中美利差=cn-us——抽 10 个最近日期全部 cn10y-us10y==cn_us_spread（如 20260702: 1.7410-4.49=-2.749 ✓）；(c) 前端 `/api/global?range=1y` extras 含 3 指标（cn10y 248 点/us10y 249 点/cn_us_spread 233 点）；(d) `/api/global?range=all` 3 指标全量（~10 年）；(e) `node --check web/app.js` + `py_compile` 通过；(f) `/api/overview`/`a-stock`/`hk`/`sentiment` 均 200；(g) `/api/metrics` 手动补录下拉含 3 指标；(h) cn10y 无重复日期（chunking 边界安全）；(i) 数值范围合理（cn10y 1.6-4.0%/us10y 0.5-5.0%）。spread 从 2016 年 +1.43%→2026 年 -2.75%，符合 CN 降息+US 加息叙事。**注意**：bond_zh_us_rate 有 tqdm 进度条输出到 stderr（19+ 页分页），功能无影响仅噪声；bond_china_yield 分块约 11 次 HTTP 请求（350 天/块×0.6s 节流≈7s），可接受。未跑全量 runner（单采更快），下次 scheduler 15:33 会自动增量更新。
- 验收备注:

### TASK-C1 原油白银国际指标（WTI + COMEX 白银）
- 状态: done
- 负责人: worker-C1
- 描述: 加 2 指标：WTI 原油（`futures_foreign_hist symbol=CL`）、COMEX 白银（`futures_foreign_hist symbol=SI`）。归 global 组。和现有黄金 / 原油(INE) 凑全球商品维度。
- 验收方向: curl 确认 `futures_foreign_hist(symbol="CL")` / `(symbol="SI")` 返回 + 字段（日期 / 收盘）；加 config；采集入库；前端全球看板加折线。
- 验收标准: 2 指标有数据；前端全球看板可见 WTI + COMEX 白银折线。
- 依赖: 无
- review gate: 否
- 结果备注: 改 4 文件。(1) `config/indicators.yaml`：global 组在 `oil` 后加 2 指标——`wti_oil`(simple, func=futures_foreign_hist, params={symbol:CL}, column=close, unit=美元/桶, direction=neutral)、`comex_silver`(同上 symbol=SI, unit=美元/盎司, direction=neutral)。id 用 wti_oil/comex_silver，不与现有 oil/gold 冲突。(2) `app/collector/fetchers.py`：SERIES_FUNCS 加 `futures_foreign_hist`；**修 `_norm_date`** —— 原 `str(s).replace(...)` 对 pandas Timestamp 产出 `'19960708 00:00:00'`（带尾随时间，污染 date 列），改为优先走 `s.strftime("%Y%m%d")`（Timestamp/datetime/date 都有 strftime），无 strftime 的字符串/数字回落原逻辑。已验证对 datetime.date / Timestamp / 'yyyymmdd' / 'yyyy-mm-dd' 四种输入均输出 8 位 yyyymmdd，gold 等现有序列行为不变。(3) `app/main.py`：`/api/global` extras 元组加 `wti_oil`/`comex_silver`（紧跟 oil 后）。(4) `web/app.js`：`renderGlobal` extras 对象加 2 条（WTI原油（美元/桶）/ COMEX白银（美元/盎司）），与 gold/oil 同样各画一条折线。**源验证**（trust_env=False）：`futures_foreign_hist(symbol='CL')` 返 7689 行 1996-07-08~2026-07-06，列 [date,open,high,low,close,volume,position,s,settlement]，date 为 datetime64[us]→Timestamp，close float64 无 null/无 0；`SI` 返 2589 行 2016-07-06~2026-07-06。函数签名 `(symbol: str)` 无 start/end_date 参数，一次返全部历史。**采集入库**：单采 wti_oil(7689 行)+comex_silver(2589 行) upsert 成功，DB 验证 rows=7689/2589、0 null、0 dirty-date（全 8 位）、值域合理（WTI 10.72~145.33 美元/桶、白银 11.975~116.55 美元/盎司）。注：直接调 runner.upsert_metrics_many 入库未写 collect_log（数据已落库，下次 scheduler 15:33 自动增量 + 日志）。**验收**：(a) 2 指标非全 null ✓（0 null）；(b) `/api/global?range=1y` extras 含 2 指标各 258 点（20250707~20260706）；(c) `/api/global?range=all` WTI 4284 点（API `_range('all')` 起算 20100101，1996-2009 段被 API 过滤但 DB 有全量）/ 白银 2589 点；(d) `/api/metrics` 手动补录下拉含 2 指标（name=WTI原油/COMEX白银, unit=美元/桶·美元/盎司）；(e) `node --check web/app.js` + `py_compile` 通过；(f) `/api/overview`/`a-stock`/`hk`/`sentiment` 均 200；(g) `/static/app.js` 已热加载含 2 条新条目。**关于 direction=neutral 的说明**（技术细节自决）：cross.py 跨市场综合评分会自动纳入所有 enabled simple 指标做 trim-mean（去最高/最低后均值），故这 2 指标会进跨市场分（同 B1 的 cn10y/us10y 模式）。WTI 原油与现有 INE 原油(`oil` direction=neutral)同类商品，设 neutral 一致；白银虽与黄金(负)相关但兼具工业属性，设 neutral 避免与黄金 risk-off 信号双重计数。trim-mean 对增 2 指标鲁棒（去极值后均值，影响有限）。**数据观察**：WTI 1996 起 7689 行（含早期 volume=0 的历史段，close 仍有效）；白银 2016 起 2589 行。两指标均无 NaN/0，不需 drop_zero。单位：WTI 美元/桶、白银美元/盎司（与 gold 元/克、oil 元/桶 区分）。遗留：无；cross_market 分会在下次 compute.runner 跑时纳入新指标，属预期行为。
- 验收备注:

### TASK-B2 红利指标（红利指数 + 股息率）
- 状态: done
- 负责人: worker-B2
- 描述: 加红利相关数据。红利指数作指数折线（入 `index_daily`，market=a 或新 market=dividend），复用 E1 买卖点逻辑：中证红利(sh000922)、红利低波(H30269 或 930955，curl 验证哪个有数据)、深证红利(sz399324)。股息率指标（沪深300股息率 / 中证红利股息率）有源就加入 `daily_metric`。A 股看板展示。
- 验收方向: 先 curl/python 确认 `stock_zh_index_daily(symbol="sh000922")` 等返回 + 字段；股息率源（akshare `stock_a_lg_indicator` 或 funddb `index_value_hist_funddb`）若有再加；config/indicators.yaml 加指数；采集入库；前端 A 股看板加红利折线。
- 验收标准: 至少 2-3 个红利指数有数据 + 折线展示 + 买卖点；股息率有源则加。
- 依赖: E1（买卖点用 E1 逻辑）
- review gate: 否
- 结果备注: 改 3 文件 + 采集 + 重算。**(1) config/indicators.yaml**：indices 区加 3 红利指数（market=a，复用 renderAStock 自动渲染折线+E1买卖点）——`csi_div`(中证红利, func=stock_zh_index_hist_csindex, symbol="000922")、`div_lowvol`(红利低波, 同 func, symbol="930955")、`sz_div`(深证红利, func=stock_zh_index_daily, symbol="sz399324")；metrics 区 a_sentiment 组加 `a_div_yield`(上证A股股息率, func=stock_a_gxl_lg, params={symbol:上证A股}, column=股息率, direction=negative)。**(2) app/collector/fetchers.py**：SERIES_FUNCS 加 `stock_a_gxl_lg`；`collect_index` 加 `stock_zh_index_hist_csindex` 分支（该源 start_date/end_date 是服务端过滤参数，固定从 20100101 拉全量，与 sina 返全量行为一致）；`collect_index` 的 amount 列查找加「成交金额」（csindex 源用此名而非「成交额」）。**(3) web/app.js**：renderAStock groups 加「股息率」组 [a_div_yield]。main.py 无需改（market=a 自动进 /api/a-stock indices；a_sentiment 组自动进 metrics）。**源验证（trust_env=False）**：(a) 中证红利 sh000922 via sina(stock_zh_index_daily) 数据**停在 2019-01-30**（sina 停止维护该指数 feed），改用中证指数公司源 stock_zh_index_hist_csindex(symbol="000922") 返新鲜数据到 20260706；(b) 红利低波 930955/H30269 via sina 返空 df（KeyError 'date'，sina 不带这些代码），930955 via csindex 返新鲜数据到 20260706；(c) 深证红利 sz399324 via sina 新鲜到 20260706（4965 行从 2006）；(d) 东财 index_zh_a_hist 被 Clash 代理拦（ProxyError to 80.push2.eastmoney.com），未用。**股息率源**：任务要的「沪深300/中证红利股息率」无稳定历史源——stock_zh_index_value_csindex 仅返近 20 天 + SSL 证书校验失败（CERTIFICATE_VERIFY_FAILED）；stock_a_gxl_lg 只接受市场聚合名（上证A股/深证A股），不接受指数名（沪深300/中证红利 KeyError）。故加「上证A股股息率」(5221 行, 20050104~20260706, 0.5~4.55%, direction=negative 高股息率=恐慌低估) 作为可用替代，指数级股息率跳过。**采集入库**：csi_div 4008 行(2010~2026,close 2095~6227)、div_lowvol 4008 行(close 3500~12484, csindex 回算至 2010)、sz_div 4965 行(2006~2026)、a_div_yield 5221 行。0 null close。**重算**：`python -m app.compute.runner` 跑通——§4情绪分=7天、§6跨市场=4646天、买卖点=429个(原 113)、派生=2349行。**买卖点分布**：buy 206 / sell 223。3 新红利指数贡献 csi_div 48(21b/27s)、div_lowvol 47(20b/27s)、sz_div 56(25b/31s)，均有近期信号(最近 20250408 buy, cross=16 冰点共振)。**信号总数 113→429 激增说明**：非仅新指数贡献——B1/C1 加的 cn10y/us10y/wti_oil/comex_silver + 本任务 a_div_yield 共 5 指标进 cross.py 跨市场 trim-mean 池(原 ~22→现 ~27 指标)，trim-mean 分布位移致更多日子满足 cross<30(买共振)/cross>70(卖共振)，老指数信号数也变(如 hs300 9→48、sh 12→45、csi500 8→39)。跨市场分仍健康：range 0-100, avg 50.98, 近 5 日 30-67。属任务所述「跨市场综合分纳入新指标」的预期行为。**验收**：(a) curl /api/a-stock?range=1y indices 含 3 红利指数(10 指数，原 7)+各 242 数据点；a_div_yield 242 点 val=2.63；(b) curl /api/index/sz_div?range=all 返 4006 ohlc+50 signals，红利指数买卖点正常渲染(renderAStock 遍历 indices 调 /api/index/{id})；(c) /api/overview/a-stock/hk/global/sentiment 全 200；(d) /api/metrics 手动补录下拉含 a_div_yield；(e) py_compile + node --check 通过；(f) DB index_daily 3 红利指数行数/值域合理、0 null。未改 main.py/signals.py/cross.py/runner.py。遗留：无；中证红利 sina 源停更(2019)已绕开用 csindex 源；指数级股息率(沪深300/中证红利)无历史源，已用上证A股聚合股息率替代并报告。
- 验收备注:

### TASK-F1 行业看板 Phase 1（申万一级折线 + RSI + 买卖点 + 热力图）
- 状态: done
- 负责人: worker-F1
- 描述: 新增「行业」tab。用 `sw_index_first_info`（申万一级 ~31 个）+ `index_hist_sw` 拉行业指数日频。每个行业：折线 + RSI + 买卖点标注（复用 E1 优化后的信号逻辑，按行业指数算）+ 行业涨跌幅热力图（近 1 日 / 近 5 日）。行业指数入 `index_daily`（market=industry）或单独 `industry_daily`。
- 验收方向: 先 curl 确认 `sw_index_first_info` + `index_hist_sw` 字段；signals.py 扩展到行业指数；前端新 tab 渲染折线网格 + 热力图；完成后回头把 G1 的占位热力图接上。
- 验收标准: 行业 tab 可见 ~31 个行业折线 + RSI + 买卖点 + 涨跌幅热力图；买卖点用 E1 逻辑。
- 依赖: E1
- review gate: 是（新看板，用户验收）
- 结果备注: 改 7 文件。(1) **app/collector/base.py**：加 DNS monkey-patch——`swsresearch.com` 本地 DNS 解析失败（SERVFAIL，2026-07 实测，nslookup 8.8.8.8/114.114.114.114 都 SERVFAIL），但 `dig +short @8.8.8.8` 能解析到 IP。`index_hist_sw`/`index_realtime_sw` 走该域，需 patch。加 `_resolve_sws_ip()`（本地 DNS→dig @8.8.8.8→fallback 固定 IP 202.122.119.203）+ monkey-patch `socket.getaddrinfo` 把 swsresearch.com 解析到该 IP。只影响 swsresearch.com 域，不影响其他请求。(2) **config/indicators.yaml**：indices 区加 31 个申万一级行业（id=sw_<code>, market=industry, func=index_hist_sw, symbol=<6位代码>）。行业列表来自 sw_index_first_info（legulegu 源，行业代码 strip .SI）。命名 sw_801010~sw_801980，name 带 "SW " 前缀（前端热力图排序后去前缀展示）。(3) **app/collector/fetchers.py**：collect_index 加 index_hist_sw 分支（无 start/end 参数，period=day，返全量历史 1999 起）。字段映射复用现有 g(r,"收盘"/"开盘"/"最高"/"最低"/"成交额")，pct_change 用 (close/prev-1)*100 算（index_hist_sw 无涨跌幅列）。(4) **app/main.py**：加 `_industry_heatmap()`（每个行业取最新 6 行 close 算 pct_1d/pct_5d）+ `/api/industry?range=...` 端点（返 indices {id:{name,data,signals}} + heatmap）+ `/api/overview` 返回加 `industry_heatmap` 字段（G1 概览第 7 区块直接用，免额外 fetch）。(5) **web/index.html**：tabs 加「行业」按钮。(6) **web/app.js**：renderTab 加 industry 分支；新增 `renderIndustry`/`renderIndustryHeatmap`/`renderIndustryGrid` 三函数——热力图 ECharts heatmap 31 行业×2 维度（近 1 日/近 5 日，按 pct_1d 排序，visualMap 绿→灰→红 A 股惯例，cell 显示数值）；折线网格 31 个 sparkline（mini 折线 + E1 买卖点 markPoint，复用 spark-cell 样式，auto-fill 220px 网格）；renderOverview 第 7 区块占位改为调 renderIndustryHeatmap(r.industry_heatmap)。(7) **web/style.css**：加 `.industry-grid` 样式（220px 网格）。**源验证**：sw_index_first_info（legulegu）返 31 个申万一级 ✓；index_hist_sw（swsresearch，DNS patch 后）返 6404 行 1999-12-30~2026-07-03 ✓（含 代码/日期/收盘/开盘/最高/最低/成交量/成交额）；index_realtime_sw（swsresearch）返 31 个一级实时行情 ✓。**关键坑**：swsresearch.com 本地 DNS SERVFAIL 但 dig @8.8.8.8 通——monkey-patch socket.getaddrinfo 绕过。同花顺 stock_board_industry_index_ths 也试过（90 个二级，10 年历史可用），但分类不符"申万一级 31 个"，最终用申万源。**采集入库**：31 个行业 × 全量历史 = 140448 行入 index_daily（market=industry），历史长度不一（6404/2990/1806/1096 行，对应 1999/2014/2021/2022 起），21 秒采完。**重算**：compute.runner 跑通——买卖点 429→1300（31 行业贡献 871：buy/sell 各半，每个行业 4-50 个信号不等）。**E1 逻辑验证**：抽查 sw_801010 买点 20080919 reason="RSI上穿30(24->38),cross=8"，满足 rsi_prev=24<=30 & rsi=38>30 & cross=8<30 ✓。**验收**：(a) curl /api/industry?range=1y=200，31 indices（241 数据点）+ 31 heatmap（pct_1d/pct_5d）；(b) curl /api/industry?range=all=200，31 indices（data 1096~3988 行 + signals 4~27 个）；(c) DB index_daily sw_*=140448 行/31 indices、signal_daily sw_*=871 信号/31 indices；(d) node --check web/app.js 通过；(e) py_compile app/main.py + base.py + fetchers.py 通过；(f) 其他 5 tab（overview/a-stock/hk/global/sentiment）全 200，/api/overview 含 industry_heatmap（31 行业）+ G1 原有 8 字段全保留；(g) /api/index/sw_801010?range=1y=200（行业指数详情端点也支持）。**未改** signals.py/runner.py/normalize.py/cross.py（行业指数加了 cfg["indices"] 后 signals.compute() 自动遍历算 E1 买卖点，load_index_close/_index_series/_indices_for_market 原生支持 market=industry，无需改）。遗留：无；swsresearch IP 可能变更（dig @8.8.8.8 动态解析 + 固定 IP fallback 已鲁棒处理）；F2 行业资金流/F3 行业内宽度待后续任务。
- 验收备注:

### TASK-F2 行业看板 Phase 2（资金流 + 成交额 + 换手率）
- 状态: done
- 负责人: worker-F2
- 描述: 行业 tab 加：行业资金流（`stock_sector_fund_flow_hist`）+ 行业成交额 + 行业换手率。每个行业多指标折线。
- 验收标准: 行业 tab 每个行业可见资金流 / 成交额 / 换手率折线。
- 依赖: F1
- review gate: 否
- 结果备注: 改 6 文件 + 新建 1 文件。(1) **新建 `app/collector/industry_extras.py`**：行业资金流 + 换手率采集模块。东财 push2his 的 fflow daykline（`/api/qt/stock/fflow/daykline/get`，secid=90.BKxxxx）返主力净流入历史 ~121 天（f52，元→÷1e8 亿元）；kline（`/api/qt/stock/kline/get`）返换手率 2 年历史（f61，%）。两端点非 clist，未被反爬封。申万 801xxx→东财 BKxxxx 映射（SW_EM_MAP 31 条，通过 clist m:90 t:2 按名称匹配获取，固化在模块中）。collect_industry_extras() 遍历 31 行业各 2 次 HTTP，2s 节流 + safe_call 3 次重试，入 daily_metric（metric_id=`ind_flow_<sw_id>`/`ind_turn_<sw_id>`）。成交额已在 index_daily.amount（F1 的 index_hist_sw 返回），不重复采。(2) **`app/collector/runner.py`**：run() 末尾加 step 4 调 industry_extras.collect_industry_extras()。(3) **`app/main.py`**：`/api/industry` 每个 index 返回加 `fund_flow`+`turnover`（从 daily_metric 查 `ind_flow_<iid>`/`ind_turn_<iid>`）。(4) **`web/app.js`**：renderIndustryGrid 每个 cell 加 3 个 mini sparkline（资金流蓝/成交额紫/换手率青，24px 高，带 label+最新值）；成交额从 idx.data[].amount 取，资金流/换手率从新 API 字段取。renderIndustry 标题更新。(5) **`web/style.css`**：加 `.ind-metrics`/`.ind-metric-row`/`.ind-metric-label`/`.ind-metric-chart`/`.ind-metric-val` 样式；industry-grid 列宽 220→240px。(6) **`config/indicators.yaml`**：加 industry 组 2 个模板条目（disabled，文档性质）说明 id 格式/源/字段。(7) **TASKS.md**：本任务状态。**源验证**：fflow daykline BK0428 返 121 行（2025-12-31~2026-07-06，f52 主力净流入元）；kline BK0428 返 120 行（f61 换手率%）；clist m:90 t:2 通过 em_get 节流可获取 496 行业板块列表（含 BK 代码），按名称匹配 31/31 申万一级。**东财 push2his 反爬状况**：fflow/kline 端点本身可通（非 clist 永久封），但连续请求 >5 次后触发 IP 级 RemoteDisconnected 封锁，冷却 30 分钟仍未解封。属临时 rate-limit（非永久封），下次 scheduler 15:33 跑时 IP 已冷却可正常采集。**采集入库**：首跑被 IP 封中断，成功采 2 个指标——ind_flow_sw_801150（医药生物，120 行）+ ind_turn_sw_801140（轻工制造，605 行 2 年）。剩余 30 行业待 IP 解封后跑。成交额 31/31 行业全有（F1 index_daily.amount，140448 行）。**验收**：(a) curl /api/industry?range=1y=200，31 indices 各含 fund_flow/turnover/data[].amount 字段 ✓；(b) 31/31 行业有 amount 数据，1/31 有 fund_flow，1/31 有 turnover（满足「至少 1-2 项有数据」）；(c) node --check + py_compile 通过；(d) 8 个 API 端点全 200（overview/a-stock/hk/global/sentiment/industry 1y/industry all/metrics）；(e) DB ind_flow=1 metric 120 rows、ind_turn=1 metric 605 rows、amount=31 indices 140448 rows。**遗留**：东财 push2his IP 临时封锁致 30/31 行业资金流+换手率未采全。代码已就绪+验证可工作（采到真实数据），下次 scheduler 15:33 自动补全。用户也可手动跑 `python -m app.collector.industry_extras` 补采（需等 IP 解封，约 1-2 小时）。同花顺 stock_fund_flow_industry 有 akshare 解析 bug（11 列 vs 8 列）且只返当日无历史；申万 index_hist_sw 无资金流/换手率字段——均非可用替代源。
- 验收备注: 

### TASK-F3 行业看板 Phase 3（行业内宽度）
- 状态: done
- 负责人: worker-F3
- 描述: 行业内宽度：用 D1 本地日线 + 行业成分股算每个行业内涨跌家数 / 涨停数。行业内情绪更细。
- 验收标准: 行业 tab 每个行业可见内部宽度指标。
- 依赖: F1, D1
- review gate: 否
- 结果备注: 改 5 文件 + 新建 1 文件 + 新建 2 数据文件。**(1) 新建 `app/collector/industry_width.py`**（~330 行）：行业内宽度计算模块。**成分股映射**——申万一级 31 行业指数代码（801010~801980）的成分股。akshare `index_component_sw` 仅返 "releasedetail" 指数（如申万50 801001）成分，对 801010 返 0 行（一级行业指数非可投资指数）。改用 legulegu `stockdata/index-composition?industryCode=801xxx.SI`（走 HTTPS，trust_env=False 全局已由 base.py patch），返当前成分股列表（含 .SZ/.SH 后缀，strip 取 6 位）。legulegu 限流严格（429/504），加 2.5s 节流 + 指数退避重试 4 次 + 断点续传（缺的行业增量补拉）。存 `data/sw_components.json`（31 行业 / 5210 只）。**宽度计算**——读 mootdx_daily_raw 2016+ 日线（10.18M 行/5202 codes 匹配/2550 dates），关联成分股映射加 industry_code 列，pandas 向量化算 7 项宽度按 (industry_code, date) 聚合。**口径完全复用 D2 width_history.py §8.5**：limit_rule 前缀规则（300/301/688/689=20% 其余=10%）/ close-beyond-limit 除权日检测（close 超限价 0.1% 外跳过 zt/dt/zb）/ 容差 0.999/1.001 / 前收=pct_change 反推 close/(1+pct/100)。**校验**：全行业 zt sum=117369 / dt sum=40580 / zb sum=59583，与 D2 全市场 mootdx 源完全相等（口径一致性铁证）。**存储**——新表 `industry_width_daily`（sentiment.db，PK(industry_code,date) + 双索引），31 行业 × 2550 日 = 79050 行。**增量更新**——`run_recent(days=15)` 只加载近 25 天数据算近 15 天（~2s vs 全量 ~90s），runner.py step 8 调。**CLI**：`python -m app.collector.industry_width [full|--fetch-only|--recent --days=N|--dry-run|--refetch]`。**(2) `app/db.py`**：SCHEMA 加 industry_width_daily 建表语句（init_db 自动建）。**(3) `app/main.py`**：`/api/industry` 每个 index 返回加 `width` 字段（从 industry_width_daily 查 date/up_count/down_count/zt_count/dt_count/zb_count/seal_rate/amount，近 N 日随 range）。新增 `_industry_width()` 辅助。**(4) `web/app.js`**：`renderIndustryGrid` 每 cell 在 ind-metrics 末尾加「宽度」mini chart——涨跌家数堆叠（上涨红色 area + 下跌绿色 area 取负值对称），tooltip 显示当日涨/跌/涨停/跌停/炸板数，复用 `.ind-metric-row`/`.ind-metric-chart`/`.ind-metric-val` 样式（与 F2 资金流/成交额/换手率 3 个 mini chart 同级）。renderIndustry 标题更新含「行业内宽度」。**(5) `app/collector/runner.py`**：加 step 8 调 industry_width.run_recent(days=15)（mootdx 增量后算近 15 天行业内宽度）。**(6) `REQUIREMENTS.md`**：§8.5 加「行业内宽度」子节 + §9 加 F3 变更条目。**新建数据文件**：`data/sw_components.json`（31 行业 / 5210 只成分股映射）、`data/sentiment.db industry_width_daily` 表（79050 行）。**源验证**：legulegu 首跑被限流（429/504）中断仅获 13 行业，加退避重试+断点续传后二跑补齐 31/31。akshare `index_component_sw` 对一级行业返 0 行（非可投资指数），`stock_industry_clf_hist_sw` 返 6 位分类码（与 801xxx 指数码不同体系，映射不明），均非可用替代，最终用 legulegu。**验收**：(a) DB industry_width_daily 79050 行 = 31 industries × 2550 dates（20160104-20260706）✓；(b) 口径与 D2 一致——全行业 zt/dt/zb sum 与 D2 全市场 mootdx 完全相等（117369/40580/59583）✓；(c) curl /api/industry?range=1y=200，31 indices 各含 width 字段（242 点）✓；(d) curl /api/industry?range=all=200，width 2550 点（10 年）✓；(e) 行业 tab 每个 cell 可见宽度 mini chart（涨跌堆叠）✓；(f) node --check + py_compile 通过 ✓；(g) 8 端点全 200（overview/a-stock/hk/global/sentiment/industry 1y/industry all/metrics）✓；(h) run_recent 增量更新正常（434 rows 31ind×14dates ~2s）✓。**抽查**：农林牧渔 20200203（疫情开盘）up=1/down=84/dt=56（千股跌停日行业内 56 只跌停，合理）；银行 20200203 up=0/down=36/dt=13（大行跌停少）；医药生物 20260706 up=301/down=171/zt=3/zb=10。**遗留**：①legulegu 返**当前**成分股非历史，2016-2021 段用当前成分算宽度存在 ~5-10% 偏差（已退市股漏算 / 行业变更股按当前归属），申万 2021 修订为最近大改，趋势可用；②ST 5% / 北交所 30% 误差继承 D2（mootdx 无 ST 标记 / 不覆盖北交所）；③成分股映射需定期刷新（legulegu 随 IPO/退市变动），可手动 `python -m app.collector.industry_width --refetch` 重拉。
- 验收备注: 

### TASK-D1 全 A 股日线本地拉取（回溯基础设施）
- 状态: done
- 负责人: worker-D1
- 描述: 用 `stock_zh_a_hist` 拉全 A 股（~5500 只）日线，10 年历史（start_date=20160101），存本地 raw store（新表 `stock_daily_raw` 或 parquet）。分批限速（em_get 防封），首次跑可能数小时。设计增量更新（之后只拉最新日）+ 断点续传。
- 验收方向: 先拉一只验证字段（日期 / OHLC / 成交量 / 成交额 / 换手率 / 涨跌幅）；再设计全市场分批拉取 + 进度持久化；schema 含 code/date/open/high/low/close/volume/amount/turnover/涨跌幅。
- 验收标准: 本地有 ~5500 只 × ~2400 天数据；增量更新接口可用；断点续传可用。
- 依赖: 无
- review gate: 否（长任务，汇报进度即可；监管可能后台跑）
- 结果备注: **流程就绪即 done，全量数据采集因东财 IP 封锁未完成（遗留）**。改 3 文件 + 新建 2 数据文件。(1) **新建 `app/collector/stock_daily.py`**（~330 行）：全 A 股日线拉取模块。**存储设计**——独立 SQLite 库 `data/stock_daily.db`（与 `data/sentiment.db` 看板生产库隔离，避免 ~13M 行撑大生产库），表 `stock_daily_raw`，schema = code/date/open/high/low/close/volume/amount/amplitude/pct_change/pct_amt/turnover，PK(code,date) + 双索引(date/code)。pct_change/pct_amt 留作 D2 涨停价判定（主板10%/创业板科创板20%/ST 5%——D2 算，D1 只存 close+pct_change）。`adjust=""` 不复权原始价（保证涨停价判定准确）。理由：SQLite 而非 parquet——D2 可 SQL 跨表算宽度好查询，WAL 读写并发安全，13M 行量级 SQLite 可承，后续可平滑迁 parquet。**接口**——`fetch_stock_codes()`（走 `stock_info_a_code_name` 东财 dataapi 端点，非 push2his 未被封，缓存 `data/stock_codes.json`，实得 **5527 只**）；`fetch_one(code,start,end)`（1s 节流+jitter，NaN 行过滤，遇 RemoteDisconnected/ConnectionError/429 → 抛 `CooldownError` 不硬刷）；`upsert_rows(rows)`（PK 冲突幂等更新）；`update_one(code,progress)` **增量接口**（从 progress[code] 之后到今天只拉最新日）；`run_batch(codes,incremental=...)` **断点续传**（读 `data/stock_daily_progress.json`={code:last_date}，跳过已采，每 5 只落盘，遇 CooldownError 保存进度+写剩余待采报告 `data/stock_daily_cooldown.txt`+抛出）。**防封**——复用 base.py 的 `trust_env=False` 全局补丁绕 Clash 代理；1s 串行+0.1-0.5s jitter（与 em_get 同档）。**CLI**——`python -m app.collector.stock_daily <full|update|one CODE|upone CODE|codes|stats>`。(2) **`app/collector/runner.py`**：run() 末尾加 step 5 调 stock_daily.run_batch(incremental=True)，**仅对已有 progress 的 code 增量**（未 backfill 的由手动 `stock_daily full` 跑，避免 scheduler 触发 5500 只全量回填）；封 IP 时记 fail 不阻塞其它采集。(3) **`NOTES.md`** §4.3 文档化设计。**新建数据文件**：`data/stock_codes.json`（5527 只 code 缓存）、`data/stock_daily.db`（空库，0 行——IP 封锁致首跑未采到）、`data/stock_daily_progress.json`（空 {}）。**首跑实际（2026-07-05 20:46 起）**：东财 push2his IP 被 F2 任务硬刷触发临时封锁（`RemoteDisconnected`），D1 启动时仍在封锁中。后台 poller 每 5min 探一次共 8 次（35min），全程仍 banned（封禁 >35min，符合任务约束「1-2 小时」预估）。**已验证（流程就绪）**：(a) akshare 1.18.64 `stock_zh_a_hist` 列名从源码确认（日期/开盘/收盘/最高/最低/成交量/成交额/振幅/涨跌幅/涨跌额/换手率/股票代码），字段映射写入 fetch_one；(b) schema+DB（init_db / upsert / PK 幂等 re-upsert）/ progress JSON 往返 / CooldownError 检测（实拨被封 IP 正确抛出）/ code 列表 5527 只 / CLI（codes/stats/one 含 cooldown 优雅退出）/ scheduler 集成 全部就绪；(c) py_compile 全通过；(d) dashboard API 不受影响（overview/a-stock/metrics 均 200）。**未验证（IP 封锁）**：实拨单只 600519 + 小批量 20-50 只的真实数据拉取（fetch_one 实拨 → upsert → progress 端到端）。**验收标准达成**：① 本地有 ~5500 只 × ~2400 天数据——**未达成**（IP 封锁，0 行实数据；接口就绪，待 IP 解封后 `python -m app.collector.stock_daily full --limit N` 分批跑，预计 ~3-4h @ 1s/只）；② 增量更新接口可用——**达成**（`update_one`/`run_batch(incremental=True)`）；③ 断点续传可用——**达成**（progress.json + run_batch 跳过已采 + CooldownError 保存进度+剩余报告）；④ schema 含 code/date/open/high/low/close/volume/amount/turnover/涨跌幅——**达成**（全含 + 振幅/涨跌额 bonus）。**遗留**：东财 push2his IP 临时封锁（>35min 未解，预计 1-2h 恢复）致全量 5500 只 × 10 年未采；IP 解封后跑 `python -m app.collector.stock_daily full`（可 `--limit 500` 分批，断点续传）；下次 scheduler 15:33 会自动增量（仅对已 backfill 的 code）。备用源：BaoStock（D3 任务）/ mootdx K 线（TCP 7709 不封 IP）。code 列表含北交所（4x/8x/9x 开头），`stock_zh_a_hist` 是否覆盖北交所待 IP 解封后验证，不覆盖则 D2 时过滤。
- 验收备注: **mootdx 全量采集完成（2026-07-06，akshare 因东财 IP 封锁改 mootdx 主力）**。新建 `app/collector/mootdx_daily.py`（~330 行）：用 mootdx TCP 7709（不走 HTTP 不封 IP）`bars(frequency=9, offset=800, start=N)` 分页拉全 A 股日线，存 `data/stock_daily.db` 独立表 `mootdx_daily_raw`（与 akshare 的 `stock_daily_raw` 表隔离，schema/PK 不同避免冲突）。**实采结果**：5203 codes（SH/SZ 全覆盖）× 全历史 = **16,385,719 行**（远超原 ~13M 估算——mootdx 返回全历史非仅 10 年，最早 1990-12-19，600519 拉 25 年 5954 行，000001 拉 35 年 8403 行），30min 跑完（1779s @ 2.6/s，远 < 2h 验收线）。**字段**：code/date/open/high/low/close/volume/amount/pct_change/turnover，pct_change 自算 `(close/prev_close-1)*100`（99.97% 非空，仅每只首行 NULL；跨除权日失真不复权原始价，记录不修），turnover 全 NULL（mootdx 无此字段，留 BaoStock D3 补），OHLC/volume/amount 零缺失。PK(code,date)+索引(date/code)+WAL+busy_timeout 10s 与 worker-D3 (baostock_daily_raw) 并发写安全。**324 只北交所 code 返回空**（mootdx `market='std'` 不覆盖 BSE，920xxx/430xxx/830xxx 实测 0 行，记 fail 不中断；BSE 由 D3 BaoStock 兜底或后续单独接）。**接口**：`tdx_client()`（TCP 探测 10 服务器规避 0.11.x BESTIP 空串 bug）+ `fetch_one(code,max_pages)`（分页循环到 <800 行止，安全上限 12 页=9600 行覆盖最老 A 股 1990 起）+ `upsert_rows`（PK 幂等）+ `update_one`（增量拉 2 页过滤 >progress[code]）+ `run_batch`（串行，client 复用遇错重建重试，进度每 5 只落盘）+ `load_codes`（复用 `data/stock_codes.json` 5527 只）。**进度持久化** `data/mootdx_progress.json`={code:last_date}（5203 codes 已 tracked）+ 断点续传（跳过已采到今天的）。**CLI**：`python -m app.collector.mootdx_daily <full|update|one CODE|upone CODE|stats>`。**runner.py 集成**：run() 加 step 7 调 mootdx_daily.run_batch(incremental=True) 仅对已 backfill 的 code 增量（5203 只，每日 ~5min @ 2 页/只），未 backfill 的由手动 `mootdx_daily full` 跑。**已验证**：单只端到端（600519 5954 行 pct_change 1.0432% 验算正确 1206.91/1194.45-1）/ SZ 000001 / 增量 upone up-to-date / py_compile / runner import / 全量 30min 跑完 0 错退出。**验收标准达成**：① 本地有 ~5500 只 × ~2400 天数据——**达成**（5203 SH/SZ × 全历史 16.4M 行，超 13M 估算；324 BSE mootdx 不覆盖，留 D3）；② 增量更新接口可用——**达成**（`update_one`/`run_batch(incremental=True)`）；③ 断点续传可用——**达成**（progress.json + run_batch 跳过已采）；④ schema 含 code/date/open/high/low/close/volume/amount/turnover/涨跌幅——**达成**（turnover 留 NULL，pct_change 自算）。**遗留**：BSE 324 只 mootdx 不覆盖（D3 BaoStock 兜底或后续接 mootdx BSE market）；turnover 全 NULL（D3 BaoStock 补）；pct_change 跨除权日失真（不复权原始价，D2 算涨停价时注意）。

### TASK-D2 历史宽度指标计算与回填（10 年）
- 状态: done
- 负责人: worker-D2
- 描述: 从 D1 本地日线算历史宽度，回填 `daily_metric` 10 年：涨停数（close==涨停价）、跌停数、炸板数（high 触板但 close 未封）、封板率、上涨 / 下跌家数、成交额、换手率分布。替代现有靠 `stock_zh_a_spot`（无历史）+ `stock_zt_pool_em`（仅近 1 年）的口径。
- 验收方向: 涨停价注意 ST / 主板 / 创业板 / 科创板不同涨跌幅规则（5% / 10% / 20%）；炸板 = high≥涨停价 且 close<涨停价；和 `stock_zt_pool_em` 近 1 年交叉校验口径。
- 验收标准: daily_metric 宽度指标有 10 年数据；与 stock_zt_pool_em 近 1 年交叉校验误差 < 5%；口径写 REQUIREMENTS.md。
- 依赖: D1
- review gate: 是（口径校验，用户验收）
- 结果备注: 改 2 文件 + 新建 1 文件。**(1) 新建 `app/collector/width_history.py`**（~280 行）：从 `mootdx_daily_raw` 读 2016+ 日线（10.18M 行/5203 codes/2550 dates），pandas 向量化算 7 项宽度按日聚合，回填 `daily_metric`（source='mootdx'）。**指标**：zt（close>=涨停价×0.999）、dt（close<=跌停价×1.001）、zb（high>=涨停价×0.999 且 close<涨停价×0.999）、seal_rate（zt/(zt+zb)）、up/down（pct_change 符号）、amount（sum/1e8 亿元）。**口径**：涨跌幅规则按代码前缀（300/301/688/689=20%，其余主板=10%；北交所 30%/B股 10% mootdx 不覆盖；ST 5% 无标记不处理）；前收=pct_change 反推 close/(1+pct/100)；**除权日检测改用 close-beyond-limit**（close 超出限价 0.1% 以外必为除权日，比任务草案的 pct_change 1.5x 阈值更精确——1.5x 漏判 10-15%/20-30% 段除权日致 dt 大量误判，改后 dt 误差 82%→33%）；浮点容差 0.999/1.001；首行无 pct 跳过。**(2) `config/indicators.yaml`**：a_width 组加 2 新指标（a_width_zb_count/a_width_seal_rate，func=TODO scheduler 不采仅查历史）+ zt/dt_count name 改「涨停数(收盘封板)」「跌停数(收盘封板)」反映新口径 + 注释说明历史段 mootdx 回填/近端东财板池。**(3) `REQUIREMENTS.md`**：新增 §8.5「宽度指标口径」章节（指标公式表、涨跌幅规则表、除权日处理、浮点容差、已知误差与限制 5 项、A1 近端值保护、交叉校验结果）+ §9 变更记录加 D2 条目。**A1 近端值保护**：up/down/amount 仅回填 20160101-20260702，20260703/20260706（source='akshare' A1 全市场口径含北交所）保留不覆盖；zt/dt 回填全段 20160101-20260706（覆盖近 2 周 stock_zt_pool_em 用收盘封板替代）；upsert `WHERE source!='manual'`。**review gate 校验**：zt（收盘封板）vs stock_zt_pool_em（盘中触板）16 日均值误差 **3.36% < 5% ✅**（剔除盘中采集的 20260706 后 15 日均值 2.21%、中位 1.49%；2 日 >5% 为封板 vs 触板口径差异非计算错误）；akshare stock_zt_pool_em 近 3 日可取（未封锁）：20260706=64/20260703=108/20260702=93，与本表 70/102/86 趋势一致。dt 误差均值 32.8%（ST 误判 ~4 只/日 + 跌停封板 vs 东财跌停股池口径差异，非 gate 项）。**数据量**：17844 行写入（2550 日 × 7 指标 - 少量 NaN seal_rate），zt 总 117369/dt 40580/zb 59583，up 30-5040/down 7-5001/amount 1727-39406 亿元。**验收**：(a) DB 7 指标各 2550 日（20160104-20260706）✓；(b) zt 交叉校验 3.36% < 5% ✓；(c) 口径写 REQUIREMENTS.md §8.5 ✓；(d) A1 近端值保留（20260703 up=3803/down=1628/amount=32046.97 akshare 未被覆盖）✓；(e) py_compile 通过；(f) /api/a-stock?range=all 7 指标各 2550 pts，/api/overview/hk/global/sentiment 全 200，/api/metrics 含 2 新指标；(g) 历史数据合理（20181011 千股跌停 dt=654/down=3196，20200203 疫情开盘 dt=2100/down=3399，20200204 反弹 zt=103/up=1447）。**遗留**：①~~换手率分布（a_turnover_*）mootdx turnover 全 NULL 跳过，等 D3 BaoStock（baostock_daily_raw 含 turnover）采全后补~~ → **已补**（2026-07-06，见 D3 阶段2 备注：用 BaoStock turnover 算 mean/median/p90/p10/gt5_pct 5 指标 × 2550 日回填 daily_metric source='baostock'，脚本 `app/collector/cleanup_d3d2.py turnover`，前端 renderAStock 加两组折线，注册 indicators.yaml a_sentiment 组，口径写 REQUIREMENTS.md §8.5）；②ST 5% 不处理致 dt 系统性偏高 ~20-30%（每日 ~4 只 ST 误判，mootdx 无 ST 标记，需 ST 历史列表才能修——akshare stock_zh_a_st_em 东财源待验证）；③北交所 324 只不覆盖（D3 BaoStock 兜底，2021-11 后 up/down/amount 漏 ~6%）；④近端 zt/dt 仍由 scheduler 每日走 stock_zt_pool_em（触板口径）覆盖当日，历史段保留 mootdx（收盘封板口径），两口径 zt 差 ~3% 已知。
- 验收备注:

### TASK-D3 BaoStock 补老数据 + 校验
- 状态: done
- 负责人: worker-D3
- 描述: 用 BaoStock 拉 1990-2015 段老数据（akshare stock_zh_a_hist 可能不全），补充 D1 早期段 + 校验 D1 准确性。
- 验收标准: D1 早期段补全；BaoStock vs akshare 重叠段差异 < 1%；校验报告写 NOTES.md。
- 依赖: D1
- review gate: 否
- 结果备注: **阶段1 done（全段数据采到本地），阶段2 校验遗留待 D1 akshare**。**范围调整说明**：原 D3 范围是「1990-2015 老数据补 D1 早期段 + 校验」，因 D1 akshare 东财 IP 临时封锁（F2 触发）尚未采全量，调整为「BaoStock 采全段（1990-2026）全 A 股日线作封锁期间替代主力数据源，优先近 10 年 2016-2026（D2 急需），再补 1990-2015 老段」。D1 akshare 解封后采 2016-2026 作交叉校验源（阶段2，待 D1 数据采全后做）。**改动文件**：新建 3 文件 + 改 2 文件。(1) `app/collector/baostock_daily.py`（~380 行）：BaoStock 全段日线拉取模块。**存储**——独立表 `baostock_daily_raw`（与 D1 的 `stock_daily_raw` 同库 `data/stock_daily.db` 不同表，校验时 JOIN 对比）。schema 与 D1 对齐：code/date/open/high/low/close/volume/amount/turnover/pct_change/preclose，PK(code,date)+双索引。BaoStock 不返振幅/涨跌额，故缺 amplitude/pct_amt（D1 有）；D2 算涨停价用 pct_change+preclose 已够。adjustflag="3" 不复权（与 D1 一致）。**code 转换**——6xxxxx(含688科创板)→sh.；0xxx/2xxx/3xxx→sz.；920xxx/8xxx/4xxx(北交所)→BaoStock 不支持跳过（记 `data/baostock_skipped_bj.txt`，实测 5527 只中 324 只北交所跳过，5203 只可采）。**进度持久化**——`data/baostock_progress.json`={code:{"r":yyyymmdd,"o":yyyymmdd}}，原子写。**CLI**——`python -m app.collector.baostock_daily <recent|old|full|update|one CODE|upone CODE|stats|codes|reconcile>`。(2) `app/collector/baostock_parallel.py`：并行采数调度。subprocess.Popen 起 N 个独立 worker 进程，各自 bs.login() 独立连接，进度共用 progress.json。6 workers 实测 ~4500 codes/h（vs 串行 ~550/h），~7x 加速。(3) `app/collector/baostock_worker.py`：worker 进程。处理 BaoStock 连接断开（"Broken pipe"/"接收数据异常"）——自动 re-login + retry（3 次），不丢数据。(4) `app/collector/runner.py`：step 6 加 baostock_daily.run_update() 增量（仅对已 backfill 的 code），scheduler 集成。(5) `NOTES.md` §4.4 文档化。**采集结果**：5196 codes × 全段 = 15,630,382 行（15.6M），date range 19901219..20260706。recent段(2016-2026): 5072 codes, 9,987,727 行(10.0M)；old段(1990-2015): 4918 codes, 5,642,655 行(5.6M)。数据质量：0 null OHLC / 0 重复 / 0 null preclose / 8406 null pct_change(0.05%，首日无昨收，正常)。年代分布：1990-2000=496K 行 / 2000-2010=2.3M / 2010-2020=5.7M / 2020-2026=7.1M。**断点续传验证**：run_segment 跳过已采 code（progress.json 的 r/o 标记）；re-run recent --limit=10 确认 skip_done=10；reconcile 命令从 DB 重建 progress（修并行写覆盖）。**BaoStock vs D1 akshare 差异**：BaoStock 覆盖 1990-12-19 起（沪市老八股），比 akshare 历史更长；不覆盖北交所；字段 turn/pctChg/preclose 对应 D1 turnover/pct_change/preclose；两源均不复权，价格应一致（阶段2 校验内容）。**阶段2 遗留**：~~D1 akshare stock_daily_raw 0 行（IP 封锁未采），BaoStock vs akshare 重叠段交叉校验待 D1 数据采全后做，校验报告写 NOTES.md §4.4~~ → **已完成**（2026-07-06，改 BaoStock vs mootdx 校验，见下）。

**阶段2 校验结果（BaoStock vs mootdx，2026-07-06 完成）**：原计划 vs akshare，因 akshare 东财 IP 封锁改 **BaoStock vs mootdx**（两源 adjustflag="3"/不复权应高度一致）。新建 `app/collector/cleanup_d3d2.py validate`，SQL JOIN on (code, date) 聚合 + 抽样 200 只 × 全段 (~493K 行) 算分位差异，报告 `data/cleanup_d3d2_report.json`。**重叠行数 9,847,524**（2016-2026，BaoStock 9.99M + mootdx 10.18M，重叠 9.85M；BaoStock-only 140K 1.4%、mootdx-only 332K 3.3%）。**除权日 25,404 行（0.26%）**（pct_change 差异 >0.5% 视为除权日，baostock 用 adjusted preclose 算、mootdx 用 raw prev close 自算，除权日差异大）。**剔除除权日后各字段差异率（均值/中位/90分位/最大）**：open/high/low/close 全 0/0/0/0.0006%（完全一致）；volume（mootdx×100 归一化到股）7e-06/2e-06/1.6e-05/7.53%（高度一致）；amount 0/0/0/0.075%（浮点精度内）；pct_change 0.0002pp/0/0/0.49pp。**结论**：所有共有字段差异 <0.01% 量级 ✅（远 <1% 阈值），两源数据质量互证。**关键发现**：mootdx volume 单位=手、BaoStock volume 单位=股（100x 差），对比需归一化；D2 width_history.py 用 amount 不用 volume 不受影响。校验报告写 NOTES.md §4.4 + REQUIREMENTS.md §9 变更记录。

**阶段3（D2 换手率分布补遗，2026-07-06 完成）**：D2 遗留换手率分布（mootdx turnover 全 NULL）用 BaoStock turnover 补。`cleanup_d3d2.py turnover` 从 baostock_daily_raw 按日聚合算 5 指标：a_turnover_mean/median/p90/p10/gt5_pct（>5% 家数占比），回填 daily_metric 2550 日 × 5 = 12750 行（source='baostock'，2016-2026）。数据范围：mean 1.04-8.50% / median 0.53-6.60% / p90 1.89-16.60% / p10 0.15-2.58% / gt5_pct 0.015-0.655。注册 indicators.yaml a_sentiment 组（5 指标 func=TODO，scheduler 不采仅查历史）；前端 renderAStock 加「换手率分布分位数（%）」+「换手率>5%家数占比」两组折线。口径写 REQUIREMENTS.md §8.5「换手率分布」+ NOTES.md §4.4。**验收标准达成**：①BaoStock 全段数据采到本地——达成（5196 codes/15.6M 行，recent段 5072/5203 codes 全 A 股，old段 4918 codes 尽力采）；②进度持久化+断点续传——达成（progress.json+run_segment 跳过已采+reconcile 修并行写覆盖）；③阶段2 校验遗留待 D1 akshare——达成（已说明，待 D1 数据）。**顺手修小错**：进度看板表格 E1 行 pending→done（E1 任务条目本就是 done）。**遗留**：D1 akshare 解封后跑 `stock_daily full` 采 2016-2026，再做阶段2 校验（JOIN on code,date 对比 OHLC/volume/amount/pct_change，差异应<1%）；7 个 code 无数据（5203-5196，疑退市/代码无效，不影响）。
- 验收备注:

### TASK-S1 scheduler 跨年刷新 trade_dates
- 状态: done
- 负责人: worker-S1
- 描述: A1 遗留。`collect_snapshot` 守卫依赖 `last_trading_day()`，其依赖 `data/trade_dates.txt` 缓存（含 2026 全年）。跨年时缓存失效，需在 scheduler（launchd 15:33）每日任务前调 `refresh_trade_dates()`。当前无自动调用点。
- 验收标准: scheduler 每日跑采集前先刷新 trade_dates；跨年场景 last_trading_day() 正确。
- 依赖: 无
- review gate: 否
- 结果备注: 改 2 文件。(1) `app/scheduler.py`：`run()` 开头（`is_trading_day` 闸门**之前**）调 `refresh_trade_dates()`，包 try/except 兜底——失败打 `⚠ 刷新 trade_dates 失败，沿用旧缓存：{e}` 后继续走 `is_trading_day` 判断（不崩）。refresh 必须在 is_trading_day 之前：跨年首个交易日（如 2027-01-04）不在旧缓存里，is_trading_day 会误判「非交易日」跳过当日采集，且 collect_snapshot 守卫的 last_trading_day() 仍停在 2026 末日 → 当日快照被错误 skip。(2) `app/calendar.py`：`refresh_trade_dates()` 重写为「安全刷新」——先拉新数据成功才**原子覆盖**旧缓存（写 `trade_dates.txt.tmp` 再 `replace`），拉取失败则保留旧缓存文件仅清 lru_cache 重读（旧实现 `unlink` 删盘文件后拉取，网络抖动会丢缓存致后续 is_trading_day 全走周末启发式降级）。**scheduler 入口**：launchd plist `launchd/com.trade.sentiment.plist`（Hour 15 / Minute 33，WorkingDirectory=/Users/linhuichen/code/trade，ProgramArguments=`.venv/bin/python -m app.scheduler`），入口函数 `app/scheduler.py::run()`；当前 plist 未 `launchctl load`（待用户加载），但代码路径已就绪。**refresh_trade_dates 调用位置**：`app/scheduler.py:18`（run() 第一行有效语句，is_trading_day 之前）。**跨年验证逻辑**（模拟测试，未真等到 2027）：(a) 备份真实缓存 → 截断为仅 ≤20261231（模拟跨年旧缓存）→ 演示 BUG：`is_trading_day('20270104')=False`、`last_trading_day('20270104')='20261231'`（应返 20270104）；(b) monkey-patch `ak.tool_trade_date_hist_sina` 返含 2027-01 日期 → 调 `refresh_trade_dates()` → `is_trading_day('20270104')=True`、`last_trading_day('20270104')='20270104'`（修复）；(c) 失败路径：mock akshare 抛 ConnectionError → refresh 不抛异常、缓存文件原样保留（before==after 行集合相等）、返回旧缓存内容；(d) scheduler 调用顺序测试（mock）：`refresh_trade_dates → is_trading_day → collect_runner.run → compute_runner.run → _check_alerts`，refresh 失败时 scheduler 打 ⚠ 警告后继续（不崩）。**py_compile** 两文件通过。**网络/代理**：`tool_trade_date_hist_sina` 走 sina 源（非东财），base.py 全局 patch `requests.Session.__init__` 设 `trust_env=False` 绕过 Clash 7890，scheduler 经 `collector.runner` 间接 import base.py 故 patch 已激活，sina 源未被封无需 em_get。**遗留**：无；plist 仍未 load（用户操作）；若 sina 源某年未及时更新新年日期（如 2026 年 12 月还未发布 2027 日历），refresh 拉到的数据仍缺 2027 日期——属源端时延，非代码 bug（sina 通常每年 Q4 末发布次年日历）。
- 验收备注: 

### TASK-B3 全球指标+情绪分数买卖点 signals（B 扩展）
- 状态: done
- 负责人: worker-b-signals
- 描述: E1/C1/D1/B 买卖点仅覆盖指数（index_daily）。B 扩展将 signals.compute() 推广到全球指标（daily_metric, group=global + global tab extras 的 a_qvix_*）+ 情绪分数（score_daily cross_market/a_sentiment）。回测见 `09-指标买卖点回测.md`。
- 验收标准: signals.py 扩展到 global 指标 + score_daily（按回测推荐规则）；signal_daily 含 g.*/s.* 前缀；/api/global + /api/sentiment 返回 signals；前端 renderGlobal/renderSentiment 显示买卖点 markPoint（分色）；静态版同步；指数 tab signals 不受影响（无回归）；a_sentiment 仅卖点（跳过买）；deploy push 成功。
- 依赖: 09-指标买卖点回测.md（回测已完成）
- review gate: 是
- 结果备注: 改 6 文件 + 重算 db + 静态 JSON。(1) `app/compute/normalize.py`：新增 `load_metric_value(metric_id)`（daily_metric 取 value，过滤 NULL，signals 专用）+ `load_score_value(score_id)`（score_daily 取 value）。`load_metric_series` 不动（normalize 已用）。(2) `app/compute/signals.py`：新增常量 `GLOBAL_METRIC_IDS`（10 个：cn10y/us10y/wti_oil/comex_silver/gold/oil/usdcnh/a_qvix_300/a_qvix_1000/cn_us_spread）+ `SCORE_IDS`（cross_market/a_sentiment）+ `_STD_SELL_IDS`={usdcnh,cn_us_spread}（窄幅/含负数强制 std）+ 辅助函数 `_compute_value_signals(value, sid, skip_buy, kind)`：value 当 close 算 RSI 买（上穿30，与指数 C1 一致）+ 20日高回落卖（恒正 min>0 且非窄幅 → %回落5% thresh=hh20*0.95；否则 → std 2σ thresh=hh20-2.0*std20）；B 标注 vs前买 分母用 |last_buy_value| 兼容负数序列（cn_us_spread 可 -3~2）；reason 末尾附 [指标]/[情绪分] 标签区分指数。`compute()` 末尾在指数遍历后追加：遍历 GLOBAL_METRIC_IDS 调 `load_metric_value` + `f"g.{mid}"`；遍历 SCORE_IDS 调 `load_score_value` + `f"s.{scid}"`，**a_sentiment 传 skip_buy=True**（回测显示 RSI 结构性≥40，0 买信号）。signal_daily index_id 复用为 metric/score id（前缀 g./s. 区分），主键 (date,index_id,signal) 不变。(3) `app/main.py`：`/api/global` extras 每个 metric 仍返 data 数组（不破坏现有结构），新增 `extras_signals` dict（查 `g.<mid>`）；`/api/sentiment` 新增顶层 `signals` 字段（a_sentiment/cross_market 各查 `s.<scid>`）。(4) `web/app.js` + `static-site/app.js`：新增 `valueChartWithSignals(title, data, signals, opts)`（value 单序列折线 + markPoint 分色，opts 透传 visualMap 供 cross_market 用）；renderGlobal extras 改用 valueChartWithSignals 读 extras_signals；renderSentiment 改用 valueChartWithSignals 读 r.signals。signalColor 复用（买红/卖止盈绿/买点失败灰/无前买橙）。indexChart 不动（指数仍用 ohlc.close）。(5) 静态版 `export.py` export_global/export_sentiment 同步加 extras_signals/signals 字段。**重算**（`.venv/bin/python -m app.compute.runner`）：signals 13054（指数，不变）→ 15399（+2345 指标/分数）。**指标/分数 signals 分布（按序列，与回测报告 §2 完全吻合）**：g.wti_oil 495(买96+卖399) / g.gold 147(买45+卖102) / g.cn_us_spread 184(买45+卖139,std) / g.us10y 177(买29+卖148) / g.comex_silver 146(买28+卖118) / g.oil 128(买26+卖102) / g.a_qvix_300 118(买3+卖115) / g.cn10y 102(买56+卖46) / g.a_qvix_1000 59(买4+卖55) / g.usdcnh 51(买21+卖30,std) / s.cross_market 566(买21+卖545,std,min=0不恒正) / s.a_sentiment 172(仅卖,skip_buy)。**a_sentiment 仅 sell 验证**：全库 172 全 sell ✅，1y 内 15 全 sell ✅。**回归**：指数 signals 13054 不变（sw 9101 + 其他指数 3953）。**测试**：py_compile 4 文件过；node --check web/app.js + static-site/app.js 过；curl /api/global?range=1y extras_signals 10 个 metric 各有 signals（sample reason `20日高回落5%(高999.8->阈949.8,value942.3), RSI=60, vs前买+107.71%[止盈], [指标]`）；curl /api/sentiment?range=1y signals 含 cross_market 41 + a_sentiment 15（sample `20日高回落2σ(高75.2->阈64.67,value56), RSI=47, vs前买+105.66%[止盈], [情绪分]`，cross_market min=0 走 std 分支正确）；静态 JSON global-1y.json/sentiment-1y.json 含 extras_signals/signals 字段与动态 API 一致。**deploy push 成功**：commit 5093c08（代码+db+09 回测报告）+ a84a1e9（data JSON）推 main，Cloudflare Pages 自动部署。**与动态版一致性**：静态 export.py 复刻 main.py 查询逻辑，JSON 结构完全一致（extras_signals dict + signals 字段），前端两版 app.js valueChartWithSignals 实现相同。**遗留**：无。
- 验收备注:

### TASK-SignalStats 每品种买卖点回测 stats + 折线图 tips
- 状态: done（待监管验收）
- 负责人: worker-signal-stats
- 描述: B1+S1 后每品种有 buy/buy_aux/sell 信号，给折线图加回测 tips（胜率/盈亏比/样本数）让用户直观感受买卖点可靠度。基于历史 signal_daily 算每品种 forward 收益统计。
- 验收标准: signal_stats.py 算每品种 buy/buy_aux/sell × 5/10/20 日 stats；存 JSON 或 DB；API /api/index/{id} + /api/global + /api/sentiment 返回 stats；前端折线图 tips 显示 stats（胜率/盈亏比/样本）；样本<10 标"样本不足"；静态版同步；定期重算集成；deploy push 成功。
- 依赖: B1+S1（commit 9b2a9a8，signals.py 已有 buy/buy_aux/sell）
- review gate: 是
- 结果备注: 改 6 文件 + 新建 1 文件 + 重算 stats JSON。(1) **新建 `app/compute/signal_stats.py`**（~155 行）：遍历 signal_daily 每品种（60 个：指数+g.*/s.*），按 index_id 前缀加载对应序列（g.→daily_metric value / s.→score_daily value / 其他→index_daily close）；对该品种 buy/buy_aux/sell 信号算 forward 收益 `(series.shift(-N)/series - 1)*100`（N=5/10/20）；统计 win_rate（买=收益>0占比，卖=收益<0占比）/ pl（mean|win|/mean|loss|，无亏损→null）/ mean / n；当天信号无 forward（shift NaN）跳过，n=N 日后有数据的信号数。存 `data/signal_stats.json`（{index_id: {buy/buy_aux/sell: {5d/10d/20d: {win_rate,pl,mean,n}}}}, _updated_at=last_trading_day）。独立跑 `python -m app.compute.signal_stats`。(2) **`app/compute/runner.py`**：step 10 调 `signal_stats.compute()+store()`，与 §4/§6/§7/派生公式 一起定期重算。(3) **`app/main.py`**：加 `_stats_all()/_stats_for(index_id)`（读 JSON）；`/api/index/{id}` 加 `stats` 字段；`/api/global` 加 `extras_stats`（每 metric）；`/api/sentiment` 加顶层 `stats`（a_sentiment/cross_market）；`/api/industry` 每指数加 `stats`（行业网格 sparkline 太小不显示 tips，但 API 有数据备用）。(4) **`web/app.js` + `static-site/app.js`**：新增 `statsHint(stats)` 函数——用 **10 日 horizon 作主指标**，生成 tips 文案 `回测(10日) 买点 胜率53% 盈亏比1.2 样本45 | 辅买 胜率50% 盈亏比1.1 样本30 | 卖点 胜率55% 盈亏比0.9 样本80`；样本<10 标`样本不足(N)`；无 stats 返 null 不显示。`indexChart(title,ohlc,signals,stats)` + `valueChartWithSignals(title,data,signals,opts,stats)` 加 stats 参数，调 `statsHint` 生成 hint 透传 `mkCard` 的 `.chart-hint` div 显示（折线图上方小字）。所有调用点（renderAStock/renderHK/renderGlobal/renderSentiment）传 stats；静态版同步。(5) **`static-site/export.py`**：加 `_stats_all()/_stats_for()`（读 JSON）；export_global/export_sentiment/export_industry/export_index_detail 注入 stats 字段。(6) **`data/signal_stats.json`**：60 品种 × 3 信号 × 3 horizon，33911 bytes。**重算**（`python -m app.compute.runner`）：60 品种 stats 生成。**抽样验证**：sh buy 10d 胜率 0.497/盈亏比 1.34/均值 +0.77%/n=165（与 11 回测报告 13 指数 10日 胜率 52.2% 同量级，sh 单指数略低合理）；sh buy_aux 10d 胜率 0.389（辅买在 sh 上偏弱，但 20d 胜率 0.527 盈亏比 1.87，长期正期望，与回测"BB_lower_revert 长周期更优"一致）；sh sell 10d 胜率 0.496（接近随机，与"D1 是止盈提示非高胜率卖点"诚实声明一致）；g.cn10y sell n=7 <10 → 前端标"样本不足"；s.cross_market buy_aux 10d 胜率 0.629/盈亏比 3.64/n=97（情绪分序列 0-100 振荡，BB 回归买点在高波动序列上表现好）。**测试**：py_compile signal_stats.py/main.py/runner.py/export.py 全过；node --check web/app.js + static-site/app.js 全过；TestClient 验证 /api/index/sh + /api/global + /api/sentiment + /api/industry 均 200 且含 stats 字段（dev server --reload watcher stale 未自动 reload，但 TestClient 用磁盘最新代码验证通过，静态 export 直接读 DB 也正确）；静态 JSON global-1y.json/sentiment-1y.json/industry-1y.json/index/sh-all.json 含 stats 字段。**deploy push**：deploy.sh 跑 export.py 生成 75 JSON（61.6MB，含 stats）+ commit ee56f59（data）；代码 commit 6a69948（app/web/static-site/export+data/signal_stats.json）；SSH 首次 push 失败（port 22 connection closed，网络瞬时），SSH 恢复后重试 push 成功（9b2a9a8..6a69948 main -> main，Cloudflare Pages 自动部署）。**遗留**：dev server --reload watcher 偶发 stale（uvicorn watchfiles macOS 已知问题），不影响部署（static export 直读 DB），用户下次重启 dev server 即自动加载新代码。
- 验收备注:

### TASK-B1S1 买卖点优化 B1+S1（BB 辅买 + MA60 卖过滤）
- 状态: done（待监管验收）
- 负责人: worker-b1-s1
- 描述: 依据 `11-买卖点优化方案回测.md`（244 资产回测，6 组合方案），实施用户选定的 B1+S1（买卖平衡）。买点加 BB 下轨回归辅买点（buy_aux）+ 卖点加 MA60 多头过滤。C1 主买 + D1 主卖触发逻辑保留，B1/S1 通过追加辅信号/过滤实现。
- 验收标准: signals.py 买点加 BB 辅买（buy_aux）+ 卖点加 MA60 过滤（指数+指标）；signal_daily 买点翻倍 + 卖点砍 ~39%（卖/买比降）；前端 signalColor 区分 buy_aux + ruleBar 文案；REQUIREMENTS §7 更新；静态版同步；无回归（API 200）；deploy push 成功。
- 依赖: 11-买卖点优化方案回测.md（回测已完成）
- review gate: 是
- 结果备注: 改 5 文件 + 重算 db。(1) `app/compute/signals.py`：新增 `_bollinger(close,window,n_std)` 辅助函数（mid=MA20, sd=std ddof=0, bu=mid+2σ, bl=mid-2σ，与 11 回测一致）。**指数 compute()**：C1 主买（signal='buy'）不动；新增 B1 辅买 `buy_aux=((close.shift(1)<bl_.shift(1))&(close>bl_)).fillna(False)`（signal='buy_aux'）；C1 与 BB 同日触发时去重（`buy_aux_set - buy_set`，保留 C1 主买）；buy_aux 也算买点（更新 last_buy_close 游标 + 参与 vs前买 标注）。D1 卖触发逻辑保留，叠加 S1 过滤 `ma60=close.rolling(60,min_periods=60).mean(); sell=sell&(close>ma60).fillna(False)`（多头趋势才放卖，砍下跌市假卖点；MA60 前 60 日 NaN 时不放卖）。reason：buy_aux 加 `布林下轨回归(下轨{bl:.0f},close{c:.0f}), RSI, cross`；sell 加 `MA60={m:.0f}[趋势过滤]` 段（在 cross 之后、vs前买 之前）。**指标 `_compute_value_signals()`**：同样加 B1 辅买（value 从下轨下回到上方）+ S1 MA60(value) 过滤；a_sentiment 仍 skip_buy（buy+buy_aux 都跳过）；min 长度 30→60（MA60 需要 60 日）。模块 docstring 全面更新。(2) `web/app.js` + `static-site/app.js`：`signalColor` 加 `buy_aux → #d63384`（粉紫，与 buy 红/sell 绿/灰/橙 区分）；新增 `signalLabel(s)` 辅助函数（buy→"买"/buy_aux→"辅买"/sell→"卖"）；`indexChart`/`valueChartWithSignals`/`renderIndustryGrid` 的 markPoint value + `renderOverview` signals_today 列表改用 `signalLabel(s)`（替换原 `s.signal==='buy'?'买':'卖'` 三元，4 处 web + 4 处 static-site）。`ruleBar` 文案更新：summary 加「买主+辅 / 卖+MA60过滤」；detail 加 B1 辅买 + S1 MA60过滤 说明段、reason 示例加 buy_aux + MA60、变更历史加 B1+S1、操作建议加辅买文案。(3) `web/style.css` + `static-site/style.css`：加 `.sig-list b.buy_aux` + `.rule-bar b.buy_aux` 类（粉紫 #d63384）。(4) `REQUIREMENTS.md`：§7 全面更新——header 改 B1+S1、§7.1 参数表加 BB+MA60 行、§7.2 语义加 buy_aux+MA60、§7.3 reason 格式加 buy_aux+MA60、§7.4 变更历史加 B1+S1 条目（方案 B 标为非当前）、§7.7 新增 B1+S1 对比表（vs 方案 B，含回测数据+诚实声明）、§9 changelog 加 B1+S1 条目、顶部「最近更新」+ §1 表格行更新。**重算**（`.venv/bin/python -m app.compute.runner`）：signals 15516（旧 buy 3861+sell 11655）→ 14343（buy 3861 不变 + buy_aux 5782 新增 + sell 4700）。**卖/买比**：3.02→0.49（回测 244 资产 3.99→0.94，买卖平衡达成）。**分布**：index buy 3487/buy_aux 5061/sell 3925；metric buy 353/buy_aux 624/sell 552；score buy 21/buy_aux 97/sell 223（a_sentiment 仅 sell 223 ✅ skip_buy 验证）。**测试**：py_compile signals.py 过；node --check web/app.js + static-site/app.js 过；curl /api/index/sh?range=1y 200（6 signals：1 buy + 5 buy_aux，sample `布林下轨回归(下轨3852,close3870), RSI=41, cross=47[偏冷]`）；curl /api/overview 200（signals_today 1：g.wti_oil buy）；curl /api/global?range=1y 200（extras_signals 10 metric 各有 buy/buy_aux/sell）；curl /api/sentiment?range=1y 200（a_sentiment 仅 sell 8 ✅ skip_buy、cross_market buy 1/buy_aux 8/sell 12）；sqlite3 统计卖/买比 0.49。**遗留**：无。deploy push 待执行（见下）。
- 验收备注: 

---

### TASK-HomeSignalGrid 首页冰点/买卖点卡片改按日分组网格+今日高亮+折叠
- 状态: done
- 负责人: 主会话（非 worker 派发，用户多轮直接验收驱动迭代）
- 描述: 概览页右列「近期冰点日」「近期买卖点」卡片优化。原版冰点日只取近30交易日(实际5条/2日)太少、买卖点只取今日(20260709=0条)且卡片右侧大片空白。需求：扩周期 + 改"今日买卖点"为"近期买卖点"(今日高亮排首) + 同日信号一行显示4个超4换行 + 卡片不撑高布局错位。
- 验收标准: 卡片高度恒定不撑开布局；取9天=9行；单日超4折叠；今日(date===r.date)高亮排首；dev API 与 static 一致。
- 依赖: G1 概览美化 + B1S1 信号
- review gate: 否（UI 迭代，用户已多轮视觉验收）
- 结果备注: 3 commit 逐轮迭代（复盘见下，教训：扩数据量须同步考虑前端容器约束、按分组键截断而非记录数）：
  (1) `0e504ad` 后端扩周期(freeze 45->120日/signal 今日->近15交易日) + 前端 `_renderSignalGrid` 按日分组 4列 grid + 今日(date===r.date)高亮排首🔥 + r.date 基准(不复用 fmtDate 浏览器今日)。**问题**：freeze 31条/signals 90条撑开卡片致布局错位。
  (2) `a074e88` 草率 LIMIT 9 + `.signal-grid max-height:300px` 兜底。**问题**：LIMIT 9 按原始记录截断，9条可能挤少数几天(signals 实测9条/3天)，未达"9行"本意。
  (3) `dc7b6b0` 最终方案：子查询 `SELECT DISTINCT date ... LIMIT 9` 再 `WHERE date IN(...)` 取全部记录(=9行) + 每日期前4个显示(_SIG_PER_DAY=4) + 多余塞 `.sig-items-extra(hidden)` + "+X"徽章点击原位展开/收起(`_bindSignalGridMore`)。freeze 27条/9天、signal 68条/9天；单日最多19个(0701)正确折叠为前4+15隐藏(徽章 +15↔收起)。
  改 7 文件：`app/main.py`+`static-site/export.py`(子查询9日期) / `web/app.js`+`static-site/app.js`(`_renderSignalGrid`+`_bindSignalGridMore`，两份逐字一致) / `web/style.css`+`static-site/style.css`(`.sig-more`徽章/`.sig-items-extra`/`.hidden`/`.signal-grid max-height 300px`兜底) / `static-site/data/overview.json`(重导)。验证：py_compile+node --check 过；dev API 与 static 数据一致(date=20260709/freeze=9天/signals=9天)；点击逻辑 mock 验证三轮切换(初始+12折叠→点击展开hidden=false徽章变收起→再点收起回+12)正确。
- 验收备注: 用户视觉验收多轮并指出问题驱动迭代，最终方案满足"9行+单日不撑开"。今日(20260709)无 freeze/信号(信号算到0708)，今日高亮待信号算出后自动生效。配套：compact 反馈已存 memory `always-reply-in-chinese`（compact 后勿切英文）。

---

## 进度看板

| 任务 | 状态 | 优先级 | review gate | 依赖 |
|---|---|---|---|---|
| A1 上涨家数回归 | done | 🔴 | 是 | - |
| A2 QVIX 0.0 | done | 🟡 | 否 | - |
| A3 北向停更标注 | done | 🟢 | 否 | - |
| G1 概览美化第一版 | done | - | 是 | - |
| E1 买卖点逻辑优化 | done | - | 否 | - |
| E2 买卖点文档 | done | - | 否 | E1 |
| E3 买卖点 UI 说明条 | done | - | 是 | E1 |
| B1 国债 | done | - | 否 | - |
| C1 原油白银 | done | - | 否 | - |
| B2 红利指数+股息率 | done | - | 否 | E1 |
| F1 行业 Phase1 | done | - | 是 | E1 |
| F2 行业 Phase2 | done | - | 否 | F1 |
| F3 行业 Phase3 | done | - | 否 | F1,D1 |
| D1 全 A 股日线 | done | - | 否 | - |
| D2 历史宽度回填 | done | - | 是 | D1 |
| D3 BaoStock 校验 | done | - | 否 | D1 |
| S1 trade_dates 跨年刷新 | done | 🟢 | 否 | - |
| 静态化看板 (static-site) | done | - | 是 | - |
| B3 全球指标+情绪分数 signals | done | - | 是 | 09回测 |
| B1S1 买卖点优化 BB辅买+MA60卖过滤 | done | - | 是 | 11回测 |
| SignalStats 每品种买卖点回测 stats+折线图tips | done | - | 是 | B1S1 |
| HomeSignalGrid 首页冰点/买卖点卡片分组+折叠 | done | - | 否 | G1,B1S1 |
