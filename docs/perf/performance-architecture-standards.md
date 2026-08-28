# Performance Architecture Standards

> 生效日期：2026-08-26。  
> 目标：性能不是上线后补救项，而是数据契约、缓存、渲染和发布流程的默认约束。  
> 适用范围：首页、market、sentiment、fund、lab、Kelly 弹窗、图表、导出产物、Worker/Service Worker 以及后续新增页面。

## 1. 架构原则

### 1.1 用户旅程优先，不按函数优化

任何性能工作先定义完整旅程：

```text
用户意图 -> 首帧必须看到什么 -> 首次可操作需要什么 -> 完整功能需要什么 -> 可延迟到交互后是什么
```

禁止把“服务端已有”当成“前端首屏必须拉取”。导出物必须按 UI 旅程建模，而不是按后端聚合 convenience 建模。

### 1.2 Read Model 与内部领域模型分离

内部表、回测明细、监控明细不能直接成为前端契约。每个页面消费的是显式 read model：

- `summary`：卡片、计数、top1、状态、趋势方向；
- `list`：分页或窗口化列表；
- `detail`：单个信号、概念、报告、交易组的展开内容；
- `history`：时间序列，必须支持 range 和降采样；
- `modal-preview`：弹窗首帧小包；
- `full-export`：明确用户主动触发的下载或全量分析。

`summary` 只允许引用其他层的地址，不允许默认内嵌未登记的大数组。

### 1.3 数据契约是公共 API

`static-site/data/*.json` 一旦被前端消费，就是线上 API。变更必须按兼容性处理：

1. 新增字段优先；
2. 删除或改语义字段必须有版本、开关和迁移窗口；
3. 每个产物登记 schema version、producer、consumers、freshness、size class、shard policy、fallback；
4. 同一事实只允许一个权威字段；展示派生值必须可从前端 replay 或后端 parity 测试验证。

### 1.4 缓存策略由单一策略源生成

Worker HTTP header、Service Worker strategy、构建产物 hash、purge 行为必须来自同一份 policy manifest。禁止一层定义 TTL、另一层统一 network-first。

数据分类：

| 类型 | 示例 | 默认策略 |
|---|---|---|
| critical-realtime | 盘中信号、风险提示 | network-first，禁止 stale |
| daily-derived | 日更统计、监控摘要 | SWR + `generated_at` 校验 |
| historical-immutable | 已封盘历史分片 | content hash + immutable |
| versioned-asset | JS/CSS/i18n/notes | hash URL + immutable |
| shell | HTML 入口 | no-store，防止旧壳加载新资产 |

任何 stale 展示必须在 UI 可解释；关键决策数据不得静默使用旧缓存。

### 1.5 渲染必须稳定且渐进

动态首屏必须遵守：

1. skeleton 高度接近真实内容，桌面/移动分别校准；
2. 视口上方元素不得在数据到达后插入；
3. media/chart/details 使用固定 aspect-ratio 或 min-height；
4. 列表默认渲染窗口，不一次性拼接全量 DOM；
5. 更新尽量 keyed/local patch，避免整卡 `innerHTML` 重建；
6. 重计算放到 worker、idle、rAF 或后端预聚合，不阻塞输入。

CLS 是布局契约指标，不是视觉瑕疵。移动端目标 `< 0.10`，理想 `< 0.05`。

### 1.6 模块边界跟随路由与弹窗

单体脚本可以过渡，但不能继续无限增长。新增功能必须声明所属边界：

```text
shell: layout/topbar/theme/session
shared: fetch/cache/format/chart registry
routes/overview|market|sentiment|fund|lab
modals/*
```

route module 只加载当前路由所需逻辑；modal 先加载 preview shard，用户确认后再升级完整数据。禁止为低频说明文本或弹窗正文增加首屏必拉体积。

### 1.7 失败路径是一等公民

分片、懒加载和缓存优化必须定义失败语义：

- manifest 缺失：显示明确空态或降级入口；
- shard 缺失：禁止用另一个时间段的数据冒充结果；
- 版本不一致：拒绝聚合并提示刷新；
- 网络失败：保留缓存时标注更新时间；
- fallback 到大文件必须是显式用户动作或有告警日志。

“页面看起来正常但数据口径错了”比 404 更严重。

## 2. 资源预算

以下为默认预算。超过预算必须走例外流程。

| 对象 | 默认上限 | 说明 |
|---|---:|---|
| HTML shell | 30KB gzip | 不含内联业务数据 |
| 首屏核心 CSS+JS | 420KB gzip | shell + overview 必需模块 |
| `boot.json` | 250KB gzip | 只含 summary 与 detail 地址 |
| 普通 JSON | 1MB gzip | 单页面常规读取 |
| 明细数组 | 禁止进入 summary | 必须有 contract registry 登记 |
| raw > 5MB 产物 | 必须分片 | manifest + consumer + TTL + purge + fallback |
| 移动 LCP | < 2.5s | 常规网络中位数 |
| CLS | < 0.10 | 发布门禁；理想 < 0.05 |
| TBT | < 200ms | 冷启动采样 |
| 点击首个 DOM 变化 | < 100ms | 关键 tab/弹窗 |
| 操作长任务 | 禁止 > 200ms | 合成测试采样 |

产物体积相对 baseline 变化超过 **10%** 时 CI 失败。合法增长需要 owner 在例外清单签字，并列出回落计划。

## 3. Contract Registry

新增或修改产物时维护机器可读登记，建议落在 `docs/perf/data-contracts.json`：

```json
{
  "schemaVersion": 1,
  "artifacts": [
    {
      "id": "signal-kelly-trades",
      "path": "data/signal_kelly_trades.json",
      "producer": "scripts/signal_kelly_backtest.py",
      "consumers": ["static-site/lab.js"],
      "accessPattern": "quadrant+mode+range",
      "volatility": "daily",
      "correctnessRisk": "high",
      "rawBytesBudget": 5000000,
      "shardPolicy": "by-quadrant-mode-page",
      "manifest": "data/kelly/trades-manifest.json",
      "cache": "historical-immutable-or-swr",
      "fallback": "explicit-full-download",
      "parityChecks": ["rows", "win-rate", "fees", "generated_at"],
      "owner": "claude"
    }
  ]
}

未登记的运行时产物不得上传。CI 检查：

1. 产物存在 registry；
2. registry consumer 至少有一个真实 runtime 引用；
3. size class 与 shardPolicy 匹配；
4. critical-realtime 不允许 SWR；
5. historical-immutable URL 必须带 hash 或版本。

## 4. 设计评审清单

新页面、新 tab、新弹窗、新图表、新导出产物合入前逐项回答：

1. 首屏 summary 是多少字节？为什么每个字段必须存在？
2. 哪些数据可以等 hover、展开、筛选或弹窗后再取？
3. 时间序列是否支持 range、降采样和增量？
4. 列表最大行数是多少？是否有窗口化或分页？
5. skeleton 是否匹配真实高度？
6. 更新是局部 keyed patch 还是整块重建？
7. Worker、SW、HTTP cache 三层策略是否来自同一 manifest？
8. 发布后如何 purge？purge 失败如何发现？
9. 分片缺失时的 UI 和日志是什么？
10. 图表实例、observer、worker、定时器如何释放？
11. 桌面/移动冷热加载预算是多少？
12. before/after parity 如何证明算法和数据没变？

任一项无法回答，review 不得以 PASS 结束。

## 5. CI 与发布门禁

### 5.1 Static Gate

每次部署前执行以下目标命令；脚本尚未建立前，Phase 2 必须先补齐，禁止把人工检查长期当作门禁：

```bash
node scripts/perf/artifact_budget_check.mjs
node scripts/perf/data_contract_lint.mjs
node scripts/perf/cache_policy_check.mjs
```

最小检查：

- artifact raw/gzip bytes 对比 baseline；
- boot summary 大数组白名单；
- >1MB 产物 registry；
- >5MB 产物分片策略；
- 无消费者产物禁止生成/上传；
- `?v=` 资产命中 immutable；
- HTML no-store；
- critical JSON 不允许 stale-first。

### 5.2 Synthetic Gate

关键路径至少覆盖：

```text
/                 overview
/ or #market      market
sentiment popup   sentiment
lab               Kelly 弹窗
industry          concepts/history
```

矩阵：

| 维度 | 取值 |
|---|---|
| 设备 | desktop 1440x900 / iPhone-class mobile |
| 网络 | cold / warm |
| Service Worker | enabled / blocked |
| 数据 | fixture + selected live snapshot |

输出指标：

```json
{
  "lcpMs": 0,
  "fcpMs": 0,
  "cls": 0,
  "tbtMs": 0,
  "inpMs": 0,
  "transferBytes": 0,
  "decodedJsonBytes": 0,
  "longTasks": [],
  "firstDomChangeAfterClickMs": {},
  "consoleErrors": [],
  "pageErrors": []
}
```

连续取 5 次取中位数；单次尖峰要保留证据但不能直接替代中位数结论。

### 5.3 Release Gate

发布要求：

1. static/synthetic/parity 全绿；
2. before/after 报告落档 `docs/review/` 或 `docs/perf/`；
3. Claude 自验完成后发起 Codex 外审；
4. Codex 外审覆盖数据一致性、移动端、缓存和回归面；
5. P0/P1 清零或明确 BLOCKED；
6. 例外项有 owner、到期时间和整改 ticket。

## 6. 反模式与替代方案

| 反模式 | 为什么错 | 替代方案 |
|---|---|---|
| 一个大 JSON 服务所有视图 | 首屏替所有低频场景付费 | summary/list/detail/history/modal-preview 分层 |
| 先拉全量再前端过滤 | 传输、解析、内存三重浪费 | 后端预聚合或按 key/range shard |
| `innerHTML` 拼全量列表 | 长任务、丢状态、CLS 风险 | 窗口化 + keyed update |
| Worker/SW 各写一套缓存规则 | 策略漂移不可审计 | cache policy manifest 单源生成 |
| 无 manifest 直接读分片 | 无法验证完整性 | manifest 带 rows/hash/generatedAt/parts |
| 静默 fallback 全量包 | 用户不知情且性能突然劣化 | 显式确认 + UI 提示 + 日志 |
| 新图表只管创建不管销毁 | 内存泄漏和切换变慢 | chart registry/LRU/release |
| 性能只在投诉后测 | 回归被发现太晚 | budget + synthetic + RUM 门禁 |
| 用一次快照证明性能 | 网络波动造成假阳性/假阴性 | 固定 profile 多次取中位数 |

## 7. 例外治理

允许临时超限，但必须在 PR 和 registry 记录：

```json
{
  "artifactId": "industry-all-concepts",
  "reason": "legacy consumer migration pending",
  "owner": "claude",
  "expiresAt": "2026-09-30",
  "userImpact": "industry first entry downloads 7.8MB gzip",
  "mitigation": "per-id chunks behind flag",
  "remediationTicket": "PERF-003"
}
```

到期未处理则 CI 升级为 FAIL。禁止“永久例外”。

## 8. 分阶段落地

### Phase 0：规范固化，0.5-1 天

1. 本文档合入项目规范索引；
2. 建立 baseline JSON；
3. PR 模板加入性能影响面四问；
4. Claude/Codex review checklist 引用本文档。

### Phase 1：止血，1-4 天

1. `boot.json` 改 top1/count + detail shard；
2. Kelly report 正文懒加载；
3. 移动 skeleton 固定高度；
4. 信号网格窗口化；
5. 版本化静态资源 immutable。

### Phase 2：数据与缓存架构，1-2 周

1. Kelly trades 统一 loader；
2. industry concepts per-id/range；
3. cache policy manifest；
4. overfit monitor 预聚合默认视图；
5. data contract lint 和 budget gate。

### Phase 3：运行时重构，2-4 周

1. route module split；
2. chart registry/LRU；
3. list virtualization/keyed reconcile；
4. RUM 采集；
5. release dashboard 与长期回归跟踪。

## 9. Definition of Done

一个性能改造只有同时满足以下条件才算完成：

1. 用户可见指标达到 Phase 目标；
2. 数据 parity 与功能 smoke 全绿；
3. 桌面/移动、冷/热、SW 启用/block 均验证；
4. before/after 报告和探针可复跑；
5. 相关 contract registry、缓存策略、文档同步更新；
6. 没有引入静默降级、内存泄漏或新的单点长任务；
7. Codex 独立外审 PASS。
