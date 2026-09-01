# tick-stock-panel (TSP) + 同花顺 Financial-API 开源项目评审(2026-09-01)

> 触发:用户给 codex 抛了 TSP 评审,又要求 Claude 结合 codex 回答 + 独立深挖两份仓库,出最终评审。
> 本文件 = **独立深挖证据 + 对 codex 结论的纠偏 + 跨角色穷举评估(§5.1)+ 实施建议 + 落档**(§23.5)。
> 落档位置:`docs/codex-reviews/`(开源评估统一归档,与 karpathy-skills-evaluation-20260901.md 同位置)。
> 非正式 codex review 报告(对话式评审,未走 ref 通道),故不建 git ref,仅正文落档。

---

## 〇、核心纠偏:codex 评审的一个关键事实错误

codex 说 TSP「采集层 tick 级 L2 多源抓取 ⭐⭐⭐」。**独立深挖代码后证伪**:

- `kline_sync.py`(60KB 主同步代码)grep `requests./httpx/aiohttp/websocket/ws://` **零命中**——TSP **没有任何自建爬虫/直连行情**。
- 它的 tick/分钟/日K 全部来自 **TickFlow 官方 SDK**(付费 API key);"tick 级"是 **TickFlow 的能力,不是 TSP 自建抓取**。
- TSP 真正自己写的是:**同步/归一化/存储/计算层**——能力路由矩阵、令牌桶限流(rpm/batch/sleep_between_batches)、原子写 Parquet(tmp→rename+retry)、北京时间强校验、分层缓存(存储 15 列基础,读取现算 68 列指标)。
- **TSP 的数据源插件 fuyao = 同花顺 REST = 同花顺 Financial-API 仓库**(官网 fuyao.aicubes.cn 对上)。两仓库同生态:TSP 是调用方+工作台,FAPI 是数据供应方。

> 结论:评估落点必须是「TSP 的同步框架/口径治理可蒸馏什么」,而不是「TSP 自己抓了多牛的 tick」。

---

## 一、TSP(tick-stock-panel)评审

### 1.1 是什么
自托管 A 股「选股+监控+回测」量化工作台。FastAPI + React 18 + Polars/DuckDB/Parquet 单容器。25 内置策略 + 因子挖掘 + 连板梯队 + 情绪周期 + 异动监控。MIT。

### 1.2 可复用性(按对我们站点价值排序)

| # | TSP 能力 | 实质 | 价值评级 |
|---|---|---|---|
| 1 | **PIT 财务多源合并** | 按 `(symbol, period_end)` 累积,多源取并集,逐列按**公告日取最新**,公告前一律空值**绝不填 0** | ⭐⭐⭐ 中高,直接借鉴到公募基金财务/持仓采集;同 §23.13 口径治理精神 |
| 2 | **挖掘「晋级发布门槛」量化标准** | 发布候选须:≥2 有效 outer 折 + 正收益折≥2/3 + 样本外 Sharpe≥0.5 + 回撤≤-25% + 交易数≥60 | ⭐⭐⭐ 中高,咱们有穷举挖掘但缺独立"够格发布"量化门槛 |
| 3 | **竞价/偏移异动两 tab** | 竞价=盘前风向标+**当日/次日真实收益对照+追高风险标记**;偏移=交易所偏离值口径(主板3日±20%/双创±30%/北交±40%等),实时接近度 | ⭐⭐⭐ 中高,纯新增展示位(§23.7 只增不改安全) |
| 4 | **分块+限速+原子写框架** | chunked + rpm 限流 + tmp→rename 原子写 + 短退避重试 | ⭐⭐ 中,TSP 更工程化;但咱们 E28 已有免费异源自动切换+多重兜底,更贴合生产,**不重写采集层** |
| 5 | **情绪周期 6 阶段** | 冰点/启动/主升/高潮/退潮/修复,连板梯队驱动,EMA 平滑+2 日确认 | ⭐⭐ 中,维度不同,可作研究对照 |
| 6 | **market_time.py 北京时间工具** | 显式 UTC+8,交易分钟/量比折算兜底 | ⭐ 低-中,咱们有交易日判断(L37/L38),细节可查 |

### 1.3 不值得照搬的
- **Parquet/DuckDB 存储**(codex 建议 P0,不认同):前端 JS 直接拉 JSON,浏览器读不了 Parquet,直接上会破坏前端。可借鉴的只是「存储只留必要列、指标现算」的**瘦身思想**压 JSON 体积,不是上 Parquet。
- **能力路由矩阵**:工程化程度高但重;咱们多源切换已更贴合生产。

---

## 二、同花顺 Financial-API (FAPI)评审

### 2.1 是什么
**同花顺官方**金融数据服务(59 个 REST 端点),MIT,统一 API Key(`X-api-key`)接入,响应信封 `code==0`。覆盖 A股行情/历史日K/复权/财务4表+指标/估值/交易日历/指数板块/集合竞价/涨停·跌停·炸板·连板/异动/热榜/龙虎榜/**公募基金 28 端点**/**全市场 Parquet dump**。多端:MCP / CLI / Python SDK / marketdb(DuckDB)/ Agent Skill。

### 2.2 对我们采集的直接帮助

| 能力 | 端点 | 价值 |
|---|---|---|
| **公募基金 28 端点** | 资料/持仓/净值/区间收益/经理/ETF·LOF 场内 + 财务 | ⭐⭐⭐ **最高**,直接对口场外基金阶段0采集(public_fund),主源或兜底源 |
| **全市场 Parquet dump** | 3 次请求下载全 A 10年日K(~945万行)+近10日增量+复权事件 | ⭐⭐⭐ 高,回测数据免逐只拉(baostock 慢+封禁熔断 L46) |
| **特色数据** | 涨停/跌停/炸板/连板/异动/热榜/龙虎榜 | ⭐⭐ 中高,异动监控/连板兜底或新增维度 |
| 财务/估值/日历/指数板块/集合竞价 | — | ⭐⭐ 中,盘后日K/财务因子研究扩展 |
| MCP/CLI/Python SDK/marketdb | 统一 key 多端 | ⭐⭐ 中,Python SDK 可直接进采集脚本 |

### 2.3 关键边界(决定帮不了什么)
- **分钟K、tick、海外、宏观、新闻公告原文、研报 → 不在公开能力范围**。
- 所以:**盘中分时(1min)采集帮不上、新闻 digest 帮不上**。价值集中在**盘后日K/财务/基金/特色数据**。
- 调用频率:不设累计上限,但限流可退避重试(4001 指数退避最多 3 次)。API Key 禁入 git/日志。

### 2.4 质量规范亮点(值得抄的)
统一 Header 认证 + `code==0` 信封 + 错误码表(1xxx/2xxx 调用方可修不重试、4xxx/5xxx 可退避) + **大结果强制落盘不展开** + Key 禁入代码/日志——整套 API 治理可作新数据源接入规范模板。

---

## 三、跨角色穷举(§5.1 铁律,open-source-eval-cross-role-sweep)

| 角色 | TSP 可蒸馏增量 | FAPI 可蒸馏增量 |
|---|---|---|
| **implementer** | PIT 财务合并落地代码、分块限流原子写、market_time 北京时间工具 | Python SDK 接入基金采集、dump 3 步下载流程(签名URL→下载→UPSERT 去重) |
| **reviewer** | 挖掘发布门槛独立对照标准、fail-closed 哲学、T-1 防前视第三方参照系 | 错误码表作接入验收清单 |
| **tester** | 北京时区测试维度(test_kline_sync_timezone 思路)、dump UPSERT 去重用例 | 错误码用例表、基金端点字段不补零校验 |
| **researcher** | 嵌套 walk-forward/日截面 Rank IC 相关去重(与 §5.1 同源交叉印证)、情绪6阶段新维度 | 全市场财务/估值快照 → 财务因子新数据源 |

**结论:两仓库都「选择性采纳」、不整体照搬。TSP 蒸馏 4 项(排序:提交门槛→异动两tab→PIT口径),P1-P2 级;FAPI 是数据源接入(非照搬代码),P0 级,需用户拍板是否申请 API Key。**

---

## 四、复现(§23.5 强约束)

- **评审依据来源**:只读公开仓库,零改动、零 API 调用。
- **证据文件**:`/tmp/tsp_readme.md` `/tmp/fapi_readme.md`(README);`/tmp/tsp_fapi_probe/` 下 GitHub API 目录树(702+532 条)+ 以下关键实现/契约原文:
  - `backend/app/parquet.py`(存储 15 列 schema + 读取现算)
  - `backend/app/market_time.py`(北京时间工具)
  - `docs/custom-data-source.md`(能力路由 + YAML 字段契约 + pct_unit fail-closed)
  - `docs/mining.md`(嵌套 walk-forward + purge/embargo + 晋级门槛)
  - `docs/features.md`(监控/异动/盘后管道)
  - `docs/api/capability-map.md` + `endpoints-fund.md` + `endpoints-market-dumps.md`(FAPI 59 端点全表 + 基金 28 + dump 3)
- **抓取命令**(GitHub raw,任意日期可重跑):
  ```bash
  curl -sL https://raw.githubusercontent.com/shy3130/tick-stock-panel/main/README.md
  curl -sL https://api.github.com/repos/shy3130/tick-stock-panel/git/trees/main?recursive=1
  curl -sL https://raw.githubusercontent.com/HiThink-Tech/Financial-API/main/docs/api/capability-map.md
  ```
- **数据截止**:2026-09-01(当天抓取,仓库 main 分支)。
- **关键口径一句话**:只评估「可蒸馏增量」不做全文比对;纠偏依据=TSP 同步代码无任何自建抓取、fuyao=FAPI 同源。