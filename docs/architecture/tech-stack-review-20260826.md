# 技术栈与架构评审 · 2026-08-26

## Executive Summary

**核心技术栈选型基本正确，不建议整体重写；当前不是“Python/JavaScript 选错了”，而是工程契约和边界没有跟上业务规模。**

项目已经从单机脚本演进为“本机采集计算 + 静态/R2 read model + Cloudflare Worker 边缘分发”。Python 负责行情源、指标、回测、AI 和批处理是合理选择；Cloudflare Workers/R2/KV/D1 承担边缘缓存和轻 API 也是合理选择；SQLite 继续做本地事务事实源也合适。真正的架构债集中在五处：

1. **前端数据契约倒挂**：首屏 `boot.json` 和默认页消费大量明细，热加载仍解码约 9.58MB，移动 CLS 实测最高 1.34。
2. **缓存策略三实现漂移**：Worker HTTP TTL、Service Worker 策略和 R2/purge 规则缺少同一策略源。
3. **发布可复现性不足**：CI 安装 `wrangler@latest`，Node 只约束 LTS，Python 多个依赖只有下限约束，部署前缺统一测试门禁。
4. **单体前端继续膨胀**：`app.js` 已达 30,362 行，`lab.js` 达 11,715 行；问题不是原生 JS 必然慢，而是 route/modal/data/chart 缺少模块边界。
5. **可靠性层不完整**：部分线上 JSON 直接覆盖写，通知成功前可能进入长期去重状态，launchd 在 macOS 睡眠时不补跑。

最优路径是保留 Python、SQLite、Workers、R2、Playwright 底座；增强数据 contract registry、cache policy manifest、原子写/outbox、性能门禁；用 Vite + TypeScript 做渐进模块化；分析侧试点 DuckDB/Parquet。

## 当前架构总览

| 层 | 当前方案 | 代表证据 | 适配度 |
|---|---|---|---|
| 数据采集 / 指标 / 回测 / AI | Python 3.11 venv、AkShare、MootDX、StockStats、DeepSeek-compatible AI | `requirements.txt:3`、`app/collector/runner.py:246`、`scripts/gen_daily_brief.py:1684` | 高 |
| 动态后端 | FastAPI + Uvicorn，主要用于动态版和本地 API | `app/main.py:13`、`requirements.txt:1` | 中高 |
| 生产边缘 | Cloudflare Workers + Static Assets + R2 + KV + D1 | `wrangler.jsonc:11`、`worker/headers.js:289` | 高 |
| 前端 | 原生 JS SPA、ECharts、Service Worker/PWA、自定义 minify | `static-site/app.js:7572`、`package.json:7` | 功能适配高，工程边界低 |
| 存储 | SQLite/WAL 本地事实源；R2 大产物；KV 会话订阅；D1 基金评分 | `app/db.py:181`、`wrangler.jsonc:19` | 高，但职责需要更显式 |
| 测试 | Playwright 探针、零散 unittest/node check、少量一次性验收脚本 | `scripts/playwright-accept/package.json:14` | 中低，缺统一门禁 |
| 调度 | launchd/cron、fcntl 锁、schedule monitor/self-heal | `scripts/update_all.sh:105`、`scripts/with_lock.py:14` | 单机够用，可靠交付需增强 |

主链路是 launchd/cron 触发 Python collectors/compute/backtests，写入 SQLite；随后导出静态 JSON、构建 minified assets、上传 R2；push main 触发 Wrangler deploy，由 Worker 统一处理 headers/cache/API，浏览器再通过 Service Worker 和 ECharts 消费 read model。

该链路适合当前单人高频迭代和数据产品形态。主要弱点是每段之间靠文件名、TTL、脚本约定和人工检查衔接，缺少机器可读 contract 与自动门禁。

## 替代技术决策表

| 组件 | 决策 | 理由与时机 |
|---|---|---|
| Python 采集/清洗/回测 | **保留 + 增强** | 国内行情源生态最强；Go/Rust 会重写数据源适配和口径。CPU 热点先 profiling，再只抽离孤立 kernel 或向量化，不整体换语言。 |
| FastAPI 动态后端 | **保留，收敛职责** | 本地/动态版有用，但生产主路径已是 Worker + static/R2。长期双后端应把 query/schema/DTO 单源化。 |
| Cloudflare Workers | **保留 + 增强** | 边缘缓存、headers、R2 proxy、KV/D1 小 API 是正确位置。严格限流/计量改 Durable Objects 或 D1 atomic batch。 |
| 原生 JS + ECharts | **保留运行时，渐进模块化** | React/Vue/Svelte 全量重写不会自动解决大 JSON 和缓存问题。用 Vite + TypeScript 管新模块，route/modal 动态加载，图表 registry 化。 |
| SQLite | **保留为本地权威库** | WAL、busy timeout、fcntl 锁已有基础。DuckDB/Parquet 只做离线扫描和历史聚合。 |
| R2 + 静态 JSON | **保留，重构 read model** | 半静态产物走 CDN/R2 正确；问题是 summary/detail/history 不分层和 manifest/fallback 不一致。 |
| Postgres | **暂不引入** | 没有多服务共享在线写入的硬需求；出现多主机事务写入或复杂关系查询后再评估。 |
| ClickHouse | **暂不引入** | 当前量级未证明值得承担专用 OLAP 运维；Parquet + DuckDB 更适合过渡期。 |
| Airflow/Dagster/Temporal | **暂不引入** | 完整编排平台对单机日更任务过重。先做任务契约 + outbox + 远程 watchdog。 |
| Playwright | **保留并收敛** | 不需要 Cypress 二次投资。收敛到 Playwright Test fixture/report/trace/multi-viewport；Vitest 只覆盖新 TS 模块。 |
| LangChain 类框架 | **暂不引入** | OpenAI-compatible 直连、角色流水线、超时重试已够用。抽象 provider/model/retry/cost/outbox 即可。 |
| Bun | **开发工具试点，不作运行时承诺** | 构建速度有吸引力，但生产关键路径已有 Node/Workers 生态。先局部 benchmark，不替换部署链路。 |

## 高风险与瓶颈

### P0：本机 launchd 明文凭据扩散

多个生产 plist 内嵌 `PURGE_SECRET`，例如 `/Users/linhuichen/Library/LaunchAgents/com.trade.update-all.plist:13`。这是本机部署方式造成的凭据扩散，不是语言缺陷。应轮换 secret，建立受限 wrapper 从 macOS Keychain 或最小权限 env 注入；plist 模板禁止保存真实 secret，并加敏感键扫描。

### P1：部分线上 JSON 直接覆盖写

`scripts/fetch_news.py:615`、`scripts/simulate_trade.py:1969`、`scripts/lab/lab_retest.py:484`、`scripts/export_notifications.py:396` 存在 `open(...,"w") + json.dump` 模式，中断或并发写可能留下截断产物。应建立唯一 `atomic_write_json(path, payload)` 工具：临时文件、flush/fsync、`os.replace`；关键产物加进程锁和 schema version。

### P1：监控可能在通知确认前抑制后续告警

`scripts/schedule_monitor.sh:359` 先更新 `alert_state`，`:1545` 后才发送且忽略发送结果。如果通知失败，同类异常可能被去重抑制。通知应改为 outbox 状态机 `pending → sent / failed`；只有成功确认才允许长期 dedup，失败项退避重试并进入死信汇总。

### P1：62MB 凯利全量仍是兜底路径

`static-site/app.js:3474` 注释明示 fallback，`:3478` 存在全量消费路径；分片已存在，但分片失败可能退回大包。应建立唯一 shard loader：manifest → slice → parity check → explicit fallback。全量路径加退役窗口和用户显式动作，CI 断言默认 UI 不引用 raw >5MB full export。

### P1：缓存策略三层漂移

Worker 在 `worker/headers.js:168` 定义 TTL，Python 在 `scripts/upload_r2.py:1299` 镜像一份；Service Worker 又有自己的 `/data/*.json` 规则。应新建 `cache-policy.json` 作为单一来源，生成或校验 Worker HTTP headers、Service Worker strategy、R2 metadata、deploy purge 清单和 CI assertion。策略必须区分 critical-realtime、daily-derived、historical-immutable、versioned-asset 和 shell。

### P1：CSP、依赖锁定与发布门禁

`worker/headers.js:27` 的 CSP 仍 Report-Only 且含 `unsafe-eval`。`.github/workflows/deploy-cf.yml:37` 安装 `wrangler@latest`，Node 只约束 LTS，根 `requirements.txt` 多个依赖只有下限，CI 部署前没有完整测试。应 pin 工具链，建立 Python hash lock/root package-lock，并增加 py_compile、unit、data contract lint、artifact budget 和关键 Playwright smoke。

## Top 5 高 ROI 建议

1. **先治数据契约，而不是换框架。** `boot.json` 只保留 summary/top1/count/detail 地址，ETF 明细懒加载。预期 gzip 下降 32%-37%，弱网移动 LCP 减少 0.25-0.9s；工作量 1-3 天。
2. **统一大 JSON shard loader 与退役计划。** 覆盖 Kelly trades、industry concepts、overfit monitor、fund history。登记 producer/consumer/access pattern/shard policy/fallback/parity checks。重型弹窗 payload 预计下降 65%-97%。
3. **用 cache policy manifest 统一四层行为。** 同一清单驱动 Worker/SW/R2/purge，并监控 purge 成功率与 `generated_at` parity。回访传输预计下降 50%-95%。
4. **建立发布前性能与正确性门禁。** 最小组合是 py_compile、pytest、node syntax、artifact budget、data contract lint、cache policy lint 和关键 Playwright smoke。预算采用移动 LCP `<2.5s`、CLS `<0.10`、首屏核心 CSS+JS gzip `<420KB`、raw >5MB 必须分片。
5. **DuckDB/Parquet 只做分析侧试点。** SQLite 继续作为事务事实源；public fund 历史、ETF 历史、凯利批量输入输出转 Parquet shard，用 DuckDB 查询。不要直接迁 Postgres/ClickHouse。

## 明确不建议做的事

- 不要把 Python 全部换成 Go/Rust；这会破坏 AkShare/MootDX 生态和回测复现性。
- 不要因为 `app.js` 大就立即迁 React/Vue/Svelte；先拆 route/modal/shared boundary。
- 不要把所有静态 JSON 改成实时 API；半静态数据走 CDN/R2 是正确形态。
- 不要为了“现代架构”马上上 Kubernetes/Airflow/Temporal/ClickHouse。
- 不要让 Worker 和 Service Worker 各自演化缓存规则。

## 分阶段路线图

### Phase 0 · 安全与止血，0-3 天

1. 轮换并收口 plist 明文 secret。
2. 新增统一 atomic JSON writer，改造新闻、模拟交易、lab retest、notification export。
3. 通知 outbox 最小实现：pending/sent/failed、retry/dead-letter。
4. Pin Wrangler、Node 和关键 Python 依赖。

### Phase 1 · 性能与数据契约，1-2 周

1. `boot.json` 改 summary 协议，ETF detail 懒加载。
2. Kelly trades 统一 shard loader，限制 full fallback。
3. industry concepts 按 id/range 分片。
4. 移动端 skeleton 固定高度，信号列表窗口渲染。
5. 上线 artifact budget 和 data contract lint。

目标：移动冷 LCP 下降 15%-30%，CLS `<0.10`，首屏少下载 70-250KB gzip。

### Phase 2 · 可靠性与缓存架构，2-4 周

1. `cache-policy.json` 单源化 Worker/SW/R2/purge。
2. overfit monitor 默认视图预聚合。
3. schedule task registry 记录 schedule、lock、timeout、idempotency key、outputs 和 failure action。
4. 远程 heartbeat/watchdog，处理 macOS 睡眠后漏跑。
5. CSP 从 report-only 过渡到 enforcing。

目标：默认路径解码 3.5-5MB，回访传输下降 50%-95%，关键告警不再因发送失败被静默吞掉。

### Phase 3 · 工程化与渐进重构，1-2 月

1. Vite + TypeScript 新模块边界；旧 JS 不做一次性迁移。
2. route/modal 动态加载；说明文本和大报告移出首屏。
3. chart registry、LRU、主题 patch 合并。
4. 共享 JSON Schema/DTO 生成。
5. DuckDB/Parquet 分析试点。
6. CI 完整 fast/release 双门禁。

目标：移动常规网络 LCP 2.5-3.5s，热加载 `<2s`，CLS `<0.05`，首屏核心 CSS+JS gzip `<420KB`。

## 验收指标

| 维度 | 当前基线 / 问题 | 目标 |
|---|---|---|
| 移动冷 LCP | 实测 9.74s，采样区间 5.7-9.7s | `<2.5s` |
| 移动 CLS | 实测 1.1181-1.3435 | `<0.10`，理想 `<0.05` |
| 浏览器 JSON 解码 | 冷热均约 9.58MB | 默认路径 3.5-5MB |
| 首屏核心 CSS+JS | 约 640KB gzip | `<420KB` |
| 重型弹窗最坏 payload | 10.56MB gzip | 下降 65%-97% |
| 部署依赖 | Wrangler latest、Node LTS、Python 下限 | 全部锁定 |
| 发布门禁 | 无统一 pre-deploy gate | py/test/schema/perf/smoke 全过 |
| 通知可靠性 | 发送失败可能被提前去重 | pending/sent/failed + retry/dead-letter |
| 线上 JSON 写入 | 多处直写 | 统一 atomic writer |

## 最终结论

技术底座不需要推倒重来。项目需要从“脚本能跑”升级到“契约可验证”：数据产物变成显式 read model，缓存失效由单一策略源驱动，发布由机器门禁保护，前端模块边界阻止单体继续膨胀，通知、调度和写入具备明确失败语义。完成 Phase 0/1 后用户感知会有明显改善；完成 Phase 2 后系统才具备长期高频迭代的稳定性。
