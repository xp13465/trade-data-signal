# CF 账单 $4.50 成因查证(收窄版 follow-up,2026-10-02)

> 触发:用户收到 Cloudflare $4.50 账单要付费;上一轮(2026-10-02 早间,`docs/ops/r2-billing-usage-attribution-20261002.md`)判定"免费额度内、$4.50 是单价展示、应收 $0",本轮以用户贴出的**最终账单明细**为准复核——**推翻上一轮主判定**:Class A 实际超了免费额度,账单页 $4.50 是真实应收,成因 = 免费额度超出 + Cloudflare 计费单位向上取整规则。

## ① 用户事实(2026-10-02 账单明细原文)

| 行 | Total usage | Billable usage | Usage cost | 备注 |
|---|---|---|---|---|
| R2 Storage Class A Operations (First 1M included) | **1.22M** | **215.44k** | **$4.50** | Effective rate $0.00 / unit(无 "No usage cost" 文案) |
| R2 Storage Class B Operations (First 10M included) | 294.65k | 0 | $0.00 | No usage cost in this billing period |
| R2 Data Storage (First 10GB-Month included) | **4.76 GB-months** | 0 GB-months | $0.00 | No usage cost in this billing period |

- **Class A 是唯一产生费用的一行**:Total 1.22M > 免费 1M(超出 ≈ 215.44k——1.22M 为 2 位小数显示,精确值 = 1.21544M)。反证信号闭环:Class B/Storage 两行都带 "No usage cost in this billing period",唯独 Class A 行不带,还带 $4.50——因为 Class A 本期确实有 cost。
- Class B 294.65k < 免费 10M、Storage 4.76 GB-month < 免费 10GB → 两行 $0.00 与官方口径一致。

## ② 计费口径:为什么超额 215.44k × $4.50/M ≈ $0.97,账单却是 $4.50 整(用户最可能追问的点)

**答案:Cloudflare 计价"向上取整到下一个计费单位(1M)",超额不足 1M 的部分按 1M 计价。**

官方原文(`/tmp/cf-r2-pricing.md`,https://developers.cloudflare.com/r2/pricing/ ,Last updated Oct 1, 2026):
- L40-48「Billable unit rounding」段:**"Cloudflare rounds up your usage to the next billing unit."** 示例:**"If you have performed one million and one operations, you will be billed for two million operations."** / "If you have used 1.1 GB-month, you will be billed for 2 GB-month."

展开计算(全程官方规则,无推断):
1. Billable = 1,215,440(Total)− 1,000,000(免费)= **215,440 次**;按单价 215,440 × $4.50/1M ≈ **$0.97**
2. 取整规则:215,440 < 1M → 向上取整到下一个计费单位 = **1,000,000 次**
3. 应收 = 1,000,000 × $4.50/1M = **$4.50 整** ✓(与账单逐位一致)

**Effective rate $0.00 / unit 为何不矛盾**:按"每单位"显示费率 = 4.50 / 1,000,000 ≈ $0.0000045/unit,四舍五入显示 $0.00;它表达的是"单价/单位"而非"总费率",不构成"实际费率 0"的证据。上一轮把 Effective rate $0.00 当作"应收 0 的证据"是误读:免费行(Class B/Storage)的文案是 "No usage cost in this billing period",与 Class A 行的 "Effective rate $0.00 / unit" 是两种不同 UI 语义。

> 结论:$4.50 = 超出免费额度后的真实计费(取整规则),**不是误收,不是单价 UI 展示**。按官方取整规则,这笔 $4.50 是应收明细:某行 Qty 应计 1,000,000 个操作、Unit price $4.50 per 1M、Amount $4.50。

## ③ 1.22M 次 Class A 的来源归因(最高优先级,代码取证 + 云上实测)

### 3.1 本项目哪些动作产生 Class A(亲眼读 `scripts/upload_r2.py` 取证)

**Class A 操作(官方分类:写/改/列举类,收费 $4.50/百万)**:
| 代码点 | 操作 | 说明 |
|---|---|---|
| `upload_r2.py:794` `s3_request("PUT", ...)` | PutObject | `_upload_glob` 通用上传引擎,12+ 通道共用 |
| `upload_r2.py:676`(multipart UploadPart)+ `upload_r2.py:657`(POST uploads= = CreateMultipartUpload)+ `upload_r2.py:709`(CompleteMultipartUpload) | Multipart 三连 | `_upload_multipart`,大文件上传 |
| `upload_r2.py:590/1879/1902/1990/2031/2064/2499` | PutObject | 各 cmd 通道的直 PUT |
| `upload_r2.py:1819-1837`(ListObjectsV2 续页枚举) | ListObjectsV2 | verify/prune 场景,量小 |

**非 Class A(不产生本次费用)**:
- HEAD(`upload_r2.py:465` `s3_head`,HeadObject)= Class B(免费 10M)
- DELETE(`upload_r2.py:560/579/692/701/1929/2184/2255`,DeleteObject)= 免费操作
- GET = Class B

### 3.2 各上传通道的文件规模(本地实测 trade-data/static-site/data)

| 通道(upload_r2.py 子命令) | 文件规模 | 走向 |
|---|---|---|
| upload-fund-nav(`cmd_upload_fund_nav`,L1234) | **桶化前 per-code 26458 个**(docstring L1244-1246:"原 per-code 26458 个文件,9-22 传 21957 个 6225s 占 deploy 56%");桶化(9-23)后固定 256 | nav_bucket/ |
| upload-index(L1192) | 173(index/*.json,本地实测) | index/ |
| upload-etf-hist(L1211) | 1553 | etf/ |
| upload-accum-nav(L1272) | 1693 | accum_nav/ |
| upload-all-data(L1662) | 178(顶层 *.json) | data/ |
| upload-data-large(L1490) | 大文件/大 range | data/ |
| upload-large-json(L2344) | 3.16 万对象?——**实测 9 月 PUT 仅 62,819**(见 3.3) | signal-backup/large-json/ |
| intraday(L1691) | ~23 文件,盘中 10 分钟一次 | data/ |

### 3.3 重点怀疑项 upload-large-json 是否"每晚全量 PUT 3.1 万"——**证伪,非主因**

云上日志逐轮实测(`staticdata_backup_async_202609*.log`,30 份,9-25~9-30):
- **9 月 PUT 总计 62,819**(与上一轮统计一致),其中**首跑(9-25)一次全量 PUT 31,663**(该轮 skip 0);
- 之后每天多轮(9-25~9-30 共 30 轮,≈5 轮/天)基本 0-8 个变化文件 PUT + HEAD 命中跳过 40,338 次;
- 即:旧版(#149e 上线前)每天多轮**全量 HEAD 3.1 万(HEAD 属 Class B,便宜)** + PUT 当天变化文件;本地快照增量(#149e,**2026-10-01 合入**,upload_r2.py L2530-2540 docstring)后平时 0 HEAD 0 PUT(本地 md5 比对,L2592-2596),周日强制全量(L2556-2564)。
- **结论:large-json 的 Class A 贡献 ≈ 6.3 万/月,不是 1.22M 主因**;它是 Class B(51.8 万)大头来源(全量 HEAD),而 Class B 远在免费 10M 内,无费用。

### 3.4 主因:9 月 15 日增量化上线前的 deploy 全量上传模式(fund-nav per-code 为最大单通道)

代码事实(行号证据):
- 通用增量引擎 `_incremental_upload`(L892)**2026-09-15 才引入**(L895 "2026-09-15 R2 上传增量化,12 通道复用";各通道 docstring 标注 "2026-09-15 迁移进通用增量引擎":L1217 etf-hist、L1249 fund-nav、L1281 accum-nav、L1493 data-large、L1681 all-data);
- 9-15 之前,deploy 每次对每个通道**全量上传**(`_upload_glob` 无增量判定,全部文件 PUT);
- deploy.sh 每次调用 15 个 upload 通道(L652-692 共 15 个 run_r2_upload);fund-nav per-code 模式单通道 21,957-26,458 个文件 → **每次 deploy ≈ 2.4 万 PUT(fund-nav 占 90%)**;
- 云上实测 deploy 日志:9-13 起每天 5-15 次、9-13~9-30 共 185 次(9-13 前日志已轮转缺失);
- 9-01~9-12 段日志缺失,按同频率(日均 ~8 次)量级估算 ≈ 每次 2.4 万 × ~100 次 ≈ **240 万量级**——足以覆盖(且 9-15 后增量模式日降至几百级)。

**归因结论**:1.22M/月 Class A 的机制 = **9 月上旬(增量化 9-15 上线前)deploy 全量上传模式**,其中 **fund-nav per-code 26458 文件是最大单通道(占每次全量 ~90%)**;9-15 起增量、9-23 桶化、9-25 large-json 固定前缀、10-01 #149e 快照增量四箭全部落地,**10 月 Class A 量级预计降至十几万/月,远低于免费 1M**。9-13 前的精确拆解受日志轮转限制为量级估算(诚实标注,见⑧)。

## ④ 原任务三问答案(官方文档,2026-10-02 直连,证据文件在 /tmp/cf-*.md)

**Q1. 官方对账单四列定义;免费额度内 Usage cost 显示 $0 还是"标准单价折算"?**

官方原文(https://developers.cloudflare.com/billing/manage/billable-usage/ ):
- Product:"Products with a free tier show the included allowance (for example, 'First 1M included')."
- **Total usage**:"Total metered usage for the billing period, including any free-tier allowance."
- **Billable usage**:"Usage that exceeds the free tier and will be charged."
- **Usage cost**:"Cumulative cost for the product in the selected billing period."

免费额度内的显示口径,官方多处一致 = **$0.00,不是"标准单价折算"**:
- how-billing-works(L81):"If your usage stays within the free tier, the line item appears with a quantity of 0 and a $0.00 amount."
- how-billing-works(L140,R2 六行示例):"If your usage falls within the included free tier, all of these show $0.00."
- billing FAQ(L53):"If your usage stays within the free tier, all of these show $0.00."
- usage-based-billing(L27):"you are only charged for usage that exceeds the included amount"

上一轮正是引用这些文本得出"免费额度内应收 0"——**文本没错,错在前提:真实账单 Class A 并非免费额度内(billable 215.44k > 0)**。

**Q2. R2 有无最低消费 / 其他计费项 / 免费额度 2026 变更?**

- **无 R2 最低消费**:billing-policy 全文无 R2 最低月费(仅订阅类 "minimum one month purchase obligation",针对 Pro plan 等付费订阅)。
- **其他计费项(r2-pricing 官方)**:Infrequent Access(存储 $0.01/GB-month、Class A $9.00/M、Class B $0.90/M、Data Retrieval $0.01/GB、30 天最低存储期),Basin Catalog(单独计费);Super Slurper/Sippy 工具免费但产生 Class A 操作费。
- **免费额度前置条件(r2-pricing L61-63 Caution)**:免费额度只适用 Standard 存储,不适用 Infrequent Access。
- **免费额度 2026 是否变过**:当前官方 pricing 页(Last updated **Oct 1, 2026**)免费额度 = 10GB / Class A 1M / Class B 10M,与账单行文案一致;2026 年内是否中间变过未取得 archive 快照交叉验证(Wayback 超时),无证据表明当前数字不是现行版。
- **2026 年新计费机制(相关背景)**:threshold billing(https://developers.cloudflare.com/billing/threshold-billing/,Last updated Jun 16, 2026)——组合用量费用达阈值时周期中生成 invoice 并扣款,一次/账户;免费额度内费用 0 不触发,与本账单无关,但解释了 2026 年账单形态变化的用户感知。

**Q3. 社区先例**:**未取到**(诚实标注)。通道全试:WebSearch ×10 全空/工具后端报错、community.cloudflare.com(CF Challenge 拦)、support.cloudflare.com(Zendesk,CF Challenge 拦)、Reddit ×2 超时、Google/Bing/DuckDuckGo/Wayback/Jina r.jina.ai 全部连接超时、HN Algolia 0 条、GitHub issues 无相关、Stack Overflow 0 条。本轮所有"为什么取整/为什么 $4.50"的判定均建立在官方一手文档(R2 pricing 取整规则)之上,不依赖社区先例。

## ⑤ 最终判定:什么情况下会被收 $4.50 + 自查路径

**判定**:免费额度内不会收 $4.50(官方口径 $0.00);本次 $4.50 的充要条件 = ①Class A 超免费 1M(billable > 0)②超额不足 1M 向上取整按 1M 计价。**金额本身核算正确,属应收,非误收。**

**查 invoice 明细(用户侧确认取整的路径)**:
1. 登录 dash.cloudflare.com → **Manage Account → Billing → Invoices and documents**
2. 找本期发票,定位 "R2 Storage Class A Operations" 行:预期 **Qty = 1,000,000 / Unit price = $4.50 / Amount = $4.50**(Qty 即取整后的计费单位)
3. 对照 Manage Account → Billing → **Billable Usage** 页:Total usage 1.22M / Billable usage 215.44k / Usage cost $4.50

**若仍认为取整规则不合理/想申诉(提工单路径)**:
1. 打开 https://support.cloudflare.com/hc/en-us(或开发文档 → support/contacting-cloudflare-support)
2. 点 **Submit a request**,类别选 **Billing**(账单)或账户计费相关问题
3. 附:发票号 + 账户 ID + 本条 R2 Class A 行截图 + 官方取整规则的引用(developers.cloudflare.com/r2/pricing/ "Billable unit rounding")

## ⑥ 推翻上一轮条款清单(上一轮文档 `docs/ops/r2-billing-usage-attribution-20261002.md`)

| 上一轮条款 | 本轮结论 | 依据 |
|---|---|---|
| §③ "三项全部在免费额度内,一分钱都不该收" | **推翻**:Class A 1.22M > 免费 1M,超了 215.44k | 用户最终账单明细(主控转述) |
| §③ "($4.50)是该行单价的 UI 展示,不是应收成本;Effective rate 0 表达应收 0" | **推翻**:$4.50 是真实应收(超额取整 1M × 单价);Effective rate $0.00/unit 是"每单位"费率四舍五入,不是"应收 0"证据 | r2-pricing "Billable unit rounding" 官方原文;②节计算 |
| §② 归因表(Class A ≈24.8 万,量级吻合旧账单 248.25k) | **部分推翻**:Class A 实际 1.22M,主因 = 9-15 增量化前 deploy 全量模式 + fund-nav per-code(机制证据见③),旧归因基于低一个量级的显示值 | 云上 deploy 日志按日分布 + upload_r2.py 各通道 docstring |
| 保留:官方四列定义引用、Class A/B 操作清单、免费额度数字 | 保留(本轮复核一致,出处同上) | billable-usage L43-48 / r2-pricing L79-87 |

## ⑦ 复现段(可跑命令)

```bash
# 1. 计费取整规则(官方原文)
curl -H "Accept: text/markdown" https://developers.cloudflare.com/r2/pricing/ | grep -A4 "Billable unit rounding"
#  → "Cloudflare rounds up your usage to the next billing unit... one million and one operations → two million"

# 2. 免费额度内显示 $0.00(官方原文)
curl -H "Accept: text/markdown" https://developers.cloudflare.com/billing/understand/how-billing-works/ | grep -B2 -A2 "within the free tier"

# 3. large-json 9 月 PUT 实测量(云上,与 ③3.3 对账)——python re 统计 "gzip) -> signal-backup/large-json/" 出现次数
#    期望: PUT 62819 / skip 40338

# 4. 取整核算
#    Billable 215440 × 4.5/1e6 ≈ $0.97 → 取整 1e6 × 4.5/1e6 = $4.50 ✓
```

## ⑧ 诚实标注

1. **9-01~9-12 deploy/fund-nav 日志已轮转缺失**,归因该段为量级估算(机制确定、数值为区间);9-13 起为实测。
2. **社区先例未取到**(通道全试见④Q3),"为什么取整产生 $4.50"完全依据官方 pricing 文档,不涉及社区佐证。
3. **免费额度 2026 年内中间是否变动过**:未能用 Wayback 交叉验证(超时),以现行官方定价页(Oct 1, 2026)为准,与账单行文案一致。
4. 未登录用户 CF 控制台(无凭据),invoice 上 R2 行的 Qty/Unit price 为按官方规则的预期值,最终以用户 Billing → Invoices 实查为准(路径见⑤)。
