# 线上性能架构评审 · 2026-08-26

## 结论

当前页面的核心瓶颈不是单点函数慢，而是**数据契约倒挂**：首屏聚合包携带大量明细，历史大包没有统一消费分片，缓存层又把可复用数据反复送进 `JSON.parse`。叠加首屏动态渲染缺少稳定高度，移动端布局漂移已经达到严重级别。

本次线上实测显示：首页冷启动传输约 **1.74MB**，但浏览器要解码约 **9.58MB**；其中 JSON 约 **7.20MB**、JS 约 **2.51MB**。也就是说，即使 CDN 和 Service Worker 把重复传输降到接近零，浏览器仍要反复支付高额解析和渲染成本。交互点击本身不慢，桌面/移动 tab 点击后 **25-48ms** 内就有 DOM 首变且采样中无长任务；用户感知慢更多来自数据完成晚、LCP 晚和页面跳动。

## 实测基线

- URL：`https://ss.fx8.store/`
- 时间：2026-08-26 19:27 左右
- 工具：Playwright Chromium；桌面 1440x900，移动 iPhone 13 profile
- 探针：`scripts/playwright-accept/perf_arch_probe.mjs`
- 原始结果：`/tmp/codex-reports/perf-live-measurement-20260826.json`

| 场景 | TTFB | FCP | LCP | CLS | TBT | 传输 | 解码 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 桌面冷加载 | 3930ms | 4000ms | 6448ms | 0.2327 | 182ms | 1743KB | 9.58MB |
| 桌面热加载 | 476ms | 540ms | 2964ms | 0.1876 | 83ms | 292KB | 9.58MB |
| 移动冷加载 | 1837ms | 1920ms | 9744ms | 1.1181 | 72ms | 1745KB | 9.58MB |
| 移动热加载 | 559ms | 772ms | 5272ms | 1.3435 | 81ms | 885KB | 9.58MB |

多次采样存在网络波动，移动冷 LCP 曾测到 5.7-9.7s 区间；但“热加载仍解码 9.58MB”和“移动 CLS 大于 1”是稳定结构性问题。TTFB 波动受跨区域访问影响，不应作为唯一优化目标。

## 关键资源

| 资源 | raw | gzip | 问题 |
|---|---:|---:|---|
| `data/boot.json` | 2.234MB | 约 303KB | 首屏必拉，但内嵌大量 ETF 明细 |
| `data/overfit_monitor.json` | 3.886MB | 约 475KB 传输 | 默认首页消费过大的监控明细 |
| `app.min.js` | 974KB | 约 304KB | 单体应用，路由/弹窗无边界 |
| `vendor/echarts.min.js` | 1.034MB | 约 336KB | 已懒加载，但生命周期粗放 |
| `kelly-reports-content.min.js` | 241KB | 约 71KB | 首页下载，实际只有 lab 弹窗消费 |
| `signal_kelly_trades.json` | 65.395MB | 10.562MB | 分片已存在，但仍有消费端直拉全量 |
| `industry-all-concepts.json` | 32.256MB | 7.821MB | 历史序列整包加载 |
| `etf_score_list.json` | 18.431MB | 1.074MB | 疑似死产物，应引用核查后停写 |

## P0/P1 治理项

### 1. 重构 boot 数据契约

`overview.signals_today` 有 463 条信号，其中嵌入 2552 个 ETF 对象，序列化约 1.075MB，约占 boot raw 的 48%。本地重写实验显示：

- 只保留 `etf_count`：gzip 从约 303KB 降至 190KB，下降约 37%。
- 保留 top1 + count：gzip 降至 205KB，下降约 32%。

治本方案是把 boot 定义为“首屏摘要协议”：每条信号只带权威 top1、数量、universe 标记和明细地址；完整 ETF 候选放到按日期/index 寻址的 detail shard，hover/展开时懒加载。

预计收益：弱网移动 LCP 减少 0.25-0.9s，JSON 内存同步下降。工作量约 1-3 天。

### 2. 统一凯利交易读取器

`static-site/lab.js` 两处仍会构造 `signal_kelly_trades.json` 全量地址并直接 `resp.json()`；而 recent/year parts 与 lab slices 已经生成。应建立唯一 loader：

1. 先读 manifest/meta；
2. 按 quadrant、mode、时间窗加载小片；
3. 校验 `generated_at`、rows、parts；
4. 缺片时显式降级并提示；
5. 只有用户明确要求全史且无对应片时才允许全量 fallback。

典型首次弹窗传输可从 10.6MB gzip 降到 0.03-3MB，收益 65%-97%，同时避免数十 MB `JSON.parse` 长任务。工作量约 2-4 天。

### 3. industry concepts 按 id/range 分片

`industry-all-concepts.json` 中历史 `data` 占 84.5%。列表、搜索、热力图只需要 meta；选中概念后才需要历史曲线。

建议生成：

```text
concepts-meta.json
concepts/{id}/{range}.json
```

并限制并发、预取当前高频 id、对图表降采样。all range 首次进入可减少 90% 以上传输，消除 27MB 级解析。工作量约 2-4 天。

### 4. 缓存策略从“三层各自为政”改为单一 policy manifest

现状冲突：

- Worker 已定义 0s / 60s / 600s / 3600s TTL；
- Service Worker 却对所有 `/data/*.json` network-first，并使用 `cache: 'no-store'`；
- 版本化 notes/common/i18n/reports 未全部命中 immutable。

结果是热访问仍重复下载或至少重复解析大 JSON，回访静态资源也无法最大化复用。

治本方案是建立一个机器可读的 cache policy manifest，由它生成 Worker headers、Service Worker strategy 和 CI 断言：

| 类型 | 策略 |
|---|---|
| 盘中关键数据 | network-first，禁止 stale |
| 日更低风险数据 | stale-while-revalidate + `generated_at` 校验 |
| 历史/低频数据 | SWR 或长 TTL + purge |
| 内容寻址分片 | hash URL + immutable |
| HTML | 保持 no-store，避免发布旧壳 |

预期回访传输减少 50%-95%。必须配套 purge 成功率监控和数据一致性 parity 测试。工作量约 2-4 天。

### 5. 首屏列表停止一次性 innerHTML

首页信号网格一次拼 463 条复杂节点。应先做低成本改造：

- 默认只渲染最新 7-10 个交易日；
- 汇总统计仍覆盖完整窗口；
- 滚动到底部再增量加载；
- 筛选结果 memoize；
- 后续升级为 keyed reconcile 或虚拟滚动。

预计该区域字符串构建和 DOM 插入耗时降低 40%-75%。工作量约 1.5-3 天。

## 移动端 CLS 根因

移动端最大单次 layout shift 达 **0.9302**。探针捕获到：

```text
#content: 加载骨架高度 194px -> 实际内容 495.44px
risk-banner: 下移约 14px
h5-topbar / footer / TradingView details 跟随位移
```

这不是字体问题，而是动态首屏没有保留真实高度。修复口径：

1. overview skeleton 必须按移动/桌面分别预留 AI 预测卡、收盘小结、spark grid、KPI 行的真实高度；
2. 禁止数据到达后在视口上方插入新块；
3. TradingView/details/media 使用固定 aspect-ratio 或 min-height；
4. 顶部横幅和风险提示使用稳定高度，不要随文本加载变化；
5. 渲染分区加 `contain: layout paint`；
6. CI 断言移动 CLS < 0.10。

## 运行时架构建议

### 页面数据五层模型

以后新增功能不得把所有数据塞进一个 JSON。统一分为：

| 层 | 内容 | 预算 |
|---|---|---|
| summary | 首屏卡片、计数、top1、状态 | 小而快 |
| list | 分页/窗口列表 | 支持增量和虚拟化 |
| detail | 单个实体展开 | per-entity 寻址 |
| history | 时间序列 | 分 range + 降采样 |
| modal-preview | 弹窗首帧 | preview shard，完整数据异步升级 |

manifest 至少包含：

```json
{
  "schemaVersion": 1,
  "generatedAt": "...",
  "rows": 0,
  "totalBytes": 0,
  "parts": [],
  "fallback": "explicit"
}
```

### 路由模块边界

`app.js` 已有 30330 行，继续追加会让每次小功能都承担全局解析成本。建议逐步拆成：

```text
core shell
shared data/fetch/cache
charts registry
routes/overview
routes/market
routes/sentiment
routes/fund
routes/lab
modals/*
```

短期先拆说明文本、低频弹窗和报告正文；中期由 `renderTab()` 动态加载 route module 并预取相邻高频 tab。首屏 JS gzip 预计可降 20%-45%。

### 图表生命周期

现在切 tab 全量 dispose/rebuild，换肤会对图表多次 `setOption`。应引入 per-tab chart registry：

- 隐藏 tab 先 detach，不立刻 dispose；
- LRU 上限控制内存；
- 主题变化合并成一次 theme patch；
- resize/idle 批处理；
- 显式释放 observer、ECharts instance 和大数组。

多图切换和换肤长任务预计降低 30%-60%。

## 分阶段路线

### Phase 1：止血与高 ROI，1-4 天

1. boot signals_today 改 top1/count + detail shard；
2. kelly-reports-content 改弹窗懒加载；
3. 版本化静态资源补 immutable；
4. overview 移动 skeleton 固定高度；
5. 信号网格默认窗口化；
6. 提交性能探针和 artifact budget 基线。

保守预期：移动冷 LCP 下降 15%-30%，CLS 进入 `< 0.10`，首屏少下载 70-250KB gzip。

### Phase 2：数据与缓存架构，1-2 周

1. 凯利交易统一 shard loader；
2. industry concepts per-id/range；
3. cache policy manifest 生成 Worker/SW 配置；
4. purge 成功率与 generated_at 一致性测试；
5. overfit monitor 输出默认视图预聚合包。

保守预期：默认路径解码量降到 3.5-5MB；重访问传输下降 50%-95%；重型弹窗最坏 payload 下降 65%-97%。

### Phase 3：运行时重构，2-4 周

1. app 路由模块化；
2. chart registry/LRU；
3. 列表虚拟化/keyed update；
4. RUM 采集 LCP/INP/CLS/资源字节；
5. 性能预算门禁接入部署前检查。

乐观目标：常规网络下移动 LCP 2.5-3.5s，热加载低于 2.0s，CLS < 0.05，首屏核心 JS+CSS gzip 不超过 420KB。

## 性能规范与门禁

完整架构准则见 `docs/perf/performance-architecture-standards.md`，覆盖数据契约、缓存策略、渲染稳定性、CI 门禁、反模式、例外治理和 Definition of Done。发布 review 至少强制执行以下硬预算：

1. `boot.json` gzip <= 250KB；
2. 普通 JSON 默认 gzip <= 1MB；
3. raw > 5MB 的产物必须登记 consumer、shard policy、TTL、purge、fallback；
4. 首屏核心 JS+CSS gzip <= 420KB；
5. HTML gzip <= 30KB；
6. 移动 LCP < 2.5s、CLS < 0.10、TBT < 200ms；
7. 点击到首个 DOM 变化 < 100ms，采样操作不得出现 > 200ms 长任务；
8. summary 层禁止内嵌未登记明细数组；
9. 无 runtime consumer 的产物禁止上传；
10. artifact size diff > 10% 时 CI 失败，除非 owner 在例外清单签字。

CI 目标实现（当前仓库尚无这三个 perf 脚本，Phase 2 需新建）：

```bash
node scripts/playwright-accept/perf_arch_probe.mjs
node scripts/perf/artifact_budget_check.mjs
node scripts/perf/data_contract_lint.mjs
node scripts/perf/cache_policy_check.mjs
```

报告必须比较：

- raw/gzip bytes；
- route payload bytes；
- LCP/FCP/CLS/TBT；
- long tasks；
- 点击后首个 DOM 变化时间；
- JSON decode 估算量。

## 交给 Claude 的实施顺序

1. 先做 Phase 1，不改算法口径，只做数据视图和前端渲染分层；
2. boot top1 方案必须提供旧字段开关和 parity 快照；
3.凯利 shard loader 必须先通过行数、金额、胜负、费率后口径 parity；
4. SWR 只允许用于非关键日更/历史数据，盘中关键文件保持 network-first；
5. 每个 Phase 结束跑同一性能探针，输出 before/after JSON；
6. Claude 自验后发独立外审，Codex 复验性能、数据一致性和回归面。

## 验收标准

- 同一时段、同一网络 profile 连续取 5 次中位数；
- 桌面/移动各测冷、热两套；
- Service Worker 启用与 block 各测一套；
- 功能 smoke 覆盖 overview/market/sentiment/lab/kelly 弹窗；
- 无 console/page error；
- 数据 parity 全绿；
- 所有指标满足 Phase 目标或给出明确例外；
- 报告落档到 `docs/review/`，并由 Claude 发起后续外审。
