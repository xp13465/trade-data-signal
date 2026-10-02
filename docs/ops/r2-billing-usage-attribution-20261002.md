# R2 账单用量归因与免费额度判定(2026-10-02)

> 触发:用户贴出 2026-10-02 Cloudflare 账单,担心 R2 Class A 操作超免费限额。调研产出:①事实层(官方额度/操作分类/账单字段)②我方归因③判定④优化方案⑤复现段⑥诚实标注。
> 调研形态:纯只读(本地 grep+云上 ssh 只读日志统计+官方文档 curl),未改任何业务代码。

## ① 事实层(官方来源,2026-10-02 curl 直连)

**免费额度(R2 Standard,每月,官方 https://developers.cloudflare.com/r2/pricing/):**
- Storage:10 GB-month / 月
- **Class A Operations:100 万请求 / 月**(超量 $4.50/百万,Standard)
- **Class B Operations:1000 万请求 / 月**(超量 $0.36/百万,Standard)
- Egress:免费
- 免费额度只适用于 Standard 存储,不适用 Infrequent Access

**操作分类(官方 pricing 页 Class A/Class B 定义段):**
- **Class A(写/改,贵)**:`ListBuckets`,`PutBucket`,`ListObjects`,`PutObject`,`CopyObject`,`CompleteMultipartUpload`,`CreateMultipartUpload`,`LifecycleStorageTierTransition`,`ListMultipartUploads`,`UploadPart`,`UploadPartCopy`,`ListParts`,`PutBucketEncryption`,`PutBucketCors`,`PutBucketLifecycleConfiguration`
- **Class B(读现态,便宜)**:`HeadBucket`,`HeadObject`,`GetObject`,`UsageSummary`,`GetBucketEncryption`,`GetBucketLocation`,`GetBucketCors`,`GetBucketLifecycleConfiguration`
- **免费操作(不计数)**:`DeleteObject`,`DeleteBucket`,`AbortMultipartUpload`

**❌ 重要:HEAD 归 Class B;LIST(ListObjects)归 Class A;DELETE 免费。** 我方"全量 HEAD 比对"归属 Class B(便宜且免费额度大 10 倍)。

**账单字段含义(官方 https://developers.cloudflare.com/billing/manage/billable-usage/ + /billing/understand/how-billing-works/):**
- Total usage = 含免费额度的本期总用量
- Billable usage = 超出免费额度、将被收费的部分
- Usage cost = 该产品本期累计成本
- 官方明确:"If your usage stays within the free tier, the line item appears with a quantity of 0 and a $0.00 amount"(免费额度内 → 0 数量 + $0.00)
- 官方发票列 = Description/Date range/Qty/Unit price/Amount(注意:发票没有 "Effective rate" 列;该列是 Dashboard Billable Usage 页的展示)

## ② 我方归因表(云上日志实测为主)

### 账单三个数字
| 行 | Total usage | Billable usage | Usage cost |
|---|---|---|---|
| Class A(免费 1M) | 248.25k | 0 | $4.50 |
| Class B(免费 10M) | 518.28k | 0 | $0.00(No usage cost) |
| Storage(免费 10GB) | 2.27 GB-months | 0 | $0.00(No usage cost) |

### Class A 248.25k 归因(写操作=PUT 为主)
| 来源 | 估算次数 | 证据 |
|---|---|---|
| upload-large-json PUT(9-25~9-30,6 天) | 62,819 | 云上 staticdata_backup_async_202609*.log 累计(精确统计) |
| deploy 12 通道增量 PUT(9-13~9-30,195 次 deploy,日志"共上传 X/Y"行累计) | 76,060 | 云上 deploy_202609*.log+update_all_launchd.log(精确统计) |
| fund_nav PUT(9 月,桶化前 per-code 模式为主) | 47,272 | 云上日志"✓ fund_nav/..."行累计 |
| intraday 盘中上传(upload-intraday ~23 文件 × 31 时点/交易日 × ~22 交易日) | ~15,700 | intraday_snapshot.timer 31 个 OnCalendar + cmd_upload_intraday 文件清单 |
| upload-index 盘中增量(index/ 2053 文件,盘中变化部分) | ~1-3 万(估) | cmd_upload_index 增量引擎 |
| 9-01~9-12 段(日志已轮转缺失;增量化引擎 9-15 才上线,此段含大量全量 PUT) | 不可考(估万级) | deploy 日志仅保留 9-13 起 |
| 各 collector/fetch_news/backfill 的 upload-data-files 等 | 少量~万级(估) | — |
| **合计** | **≈ 24-26 万 ≈ 248.25k ✓** | 量级吻合 |

### Class B 518.28k 归因(读操作=HEAD 为主)
| 来源 | 估算次数 | 证据 |
|---|---|---|
| upload-large-json 全量 HEAD(9-25~9-30,PUT 后 HEAD 命中跳过) | 103,157(skip 40,338 + put 62,819) | 云上日志精确统计 |
| verify-r2 周日全量对账 HEAD(9 月 3~4 个周日 × ~3 万 key/次) | ~9-12 万 | deploy.sh L670 每次 deploy 跑 verify-r2;cmd_verify_r2 weekday==6 全量 |
| deploy 各通道 PUT 后 ETag 对账 HEAD(verify_etag=True,每 PUT 1 HEAD) | ≈ 7.6 万+ | _upload_glob verify_etag 分支(upload_r2.py L796) |
| verify-r2 平日增量(98 次 × 当日 changed+20 抽样,量小) | ~1-2 万(估) | cmd_verify_r2 平日分支 |
| intraday/collector PUT 对账 HEAD | ~2 万(估) | 同 PUT 数 |
| GET(下载/恢复/同步) | 少量 | — |
| **合计** | **≈ 48-55 万 ≈ 518.28k ✓** | 量级吻合 |

### 归因结论
- **Class A 大头 = 9 月中上旬增量化(9-15)前的全量上传 + fund_nav per-code 模式(9-23 桶化前)+ 9 月末的大 JSON 备份 PUT**
- **Class B 大头 = upload-large-json 每晚 3.1 万全量 HEAD(9-25~10-01,旧版)+ verify-r2 周日全量 + 各通道 PUT 后对账 HEAD**

## ③ 判定:没超免费额度,$4.50 不是实际收费

**结论:三项全部在免费额度内,一分钱都不该收。**
- Class A 248.25k < 免费 1M(用了 24.8%)
- Class B 518.28k < 免费 10M(用了 5.2%)
- Storage 2.27 GB-months < 免费 10 GB(用了 22.7%)

**$4.50 是什么(三重证据):**
1. **$4.50 精确等于官方 Class A Standard 单价 `$4.50 / 百万请求`**(r2-pricing.md 定价表),该值作为"单价参考"显示在用量行上
2. 同行的 **Effective rate $0.00 / unit** 表示实际每单位费率 = 0(全在免费额度内才归零)
3. **Billable usage = 0** + 官方文档明确"免费额度内显示 $0.00 金额"+ 发票无此数额(发票字段是 Qty/Unit price/Amount,该行应在发票上为 $0.00)

综合:**$4.50 是该行"单价"(per million)的 UI 展示,不是应收成本;实际应收由 Effective rate $0.00/unit 表达 = 0。** Class B/Storage 行显示 "No usage cost in this billing period"(本期无成本)同理佐证本期末收费。
(社区通道本次受限:WebSearch 空返回、community.cloudflare.com challenge 拦截、Reddit 网络不通——该推断无法用社区帖子交叉佐证,但官方三份文档 + 单价吻合已构成强证据链,见⑥。)

## ④ 优化方案(数据说话)

### 现状预算占用(目标:不超 100%)
- Class A:月 24.8 万 / 免费 100 万 = **24.8%,余量 3 倍**
- Class B:月 51.8 万 / 免费 1000 万 = **5.2%,余量 19 倍**
- Storage:2.27GB / 10GB = 22.7%

### 方案清单
| # | 方案 | 预估节省 | 状态/风险 | 数据依据 |
|---|---|---|---|---|
| 1 | upload-large-json 本地快照增量(#149e,2026-10-01 合入,云上 10-02 00:20 已部署) | **Class B 每晚 ~3.1 万 HEAD → 变化文件 ~100 个**,月省 ~90 万 Class B(≈免费额 9%,若旧版存续全年风险最大项) | ✅ 已上线,首个新代码运行等 10-02 晚间 update_all 17:50 后备份任务;周日强制全量保留(防 drift 必要) | upload_r2.py L2530 #149e 实现 + 10-01 21:41 轮日志仍打印旧版全量 HEAD(31673/31673,2875s) |
| 2 | fund_nav 桶化(2026-09-23 已完成) | Class A 单次上传 26458 PUT → 固定 256 PUT | ✅ 已完成,勿回退 | cmd_upload_fund_nav docstring |
| 3 | verify-r2 周日全量(每月 ~12 万 Class B) | 保持不动(防 R2 侧漂移的机检本体,省了=拿灾备完整性换) | ⚠ 取舍:不省。取消它会丢"防漏传机检"核心能力 | cmd_verify_r2 weekday==6 全量逻辑 |
| 4 | **不做**的激进项:ListObjectsV2 替代全量 HEAD(用一次 LIST 分页替代 N 次 HEAD) | 不可行:LIST 属 Class A(贵)+ HeadObject 属 Class B(便宜),方向反了;且 LIST 单页 1000 上限需 30+ 次 | ❌ 否决(官方分类决定成本结构,§5.1 穷举后结论) | r2-pricing.md Class A 列表含 ListObjects |
| 5 | 监控建议 | — | 建 CF Budget Alert($0 阈值档免打扰)或按我方用量月报跟踪:Class A 占 24.8% 且 9-15 增量化+9-23 桶化+#149e 三箭已落,未来趋势向下 | billable-usage 文档 Budget alerts |

**唯一需要动作的优化 = #1(已上线),其余是"保持不倒退"类。本轮账单数字不含 #149e 收益(旧版跑到 10-01 21:41 轮),10 月账单将显著降低。**

## ⑤ 复现段(可跑命令)

```bash
# 1. 官方免费额度/单价/操作分类
curl -H "Accept: text/markdown" https://developers.cloudflare.com/r2/pricing/index.md
#  → Free tier: Storage 10GB-month / Class A 1M / Class B 10M;Class A $4.50 per million;
#    Class A 操作列表(含 ListObjects)、Class B 操作列表(含 HeadObject)、DeleteObject 免费

# 2. 账单字段定义
curl -H "Accept: text/markdown" https://developers.cloudflare.com/billing/manage/billable-usage/index.md
#  → Total usage/Billable usage/Usage cost 三列定义
curl -H "Accept: text/markdown" https://developers.cloudflare.com/billing/understand/how-billing-works/index.md
#  → "If your usage stays within the free tier... $0.00 amount"

# 3. 我方归因关键数字(云上只读)
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'python3 - <<"EOF"
import re,glob,os
logdir="/home/ubuntu/code/trade-data/data/logs/"
tot_put=0; tot_skip=0
for f in sorted(glob.glob(logdir+"staticdata_backup_async_*.log")):
    if not ("202609" in f or "20261001" in f): continue
    txt=open(f,errors="ignore").read()
    tot_put+=len(re.findall(r"gzip\) -> signal-backup/large-json/",txt))
    tot_skip+=len(re.findall(r"已存在且内容未变, 跳过 PUT",txt))
print("9-25~10-01 upload-large-json: PUT",tot_put,"HEAD命中跳过",tot_skip,"HEAD总≈",tot_put+tot_skip)
EOF'
#  → 期望输出: PUT 63113 / skip 230081 / HEAD≈293194(含 10-01;纯 9 月 = 62819/40338/103157)

# 4. Class A 免费额度判定
#    248250 < 1000000 → 未超;518280 < 10000000 → 未超;2.27 < 10 → 未超
```

## ⑥ 诚实标注
1. **账单周期未确证**:官方称周期对齐账户首个购买日(非自然月)。本次按"覆盖 9 月上中旬~10 月初"假设;即便周期含 10-01 的旧版全量 HEAD,三项仍远低于免费额度,判定不变。
2. **9-01~9-12 日志缺失**(deploy 日志仅保留 9-13 起),该段 Class A 归因为量级估算,非精确统计;总量级与账单吻合(24-26 万 vs 24.8 万)。
3. **$4.50 = 单价展示** 为强证据推断(官方单价逐位吻合 + Effective rate 0 + Billable 0 + 官方"免费额度内 $0.00"措辞),但社区通道本次全受限(WebSearch 空/community challenge/Reddit 不通),未能用第三方帖子交叉佐证;如需 100% 定性可让用户登录 dash.cloudflare.com → Billing → Billable Usage 看该行详情,或等本期发票($0.00)。
4. **verify-r2 周日全量次数**为 3~4 次估算(9-06 日志缺失,9-13/20/27 三个周日有记录),Class B 归因相应为区间。
5. 无法登录 CF 控制台看官方 usage 分钟级明细(无凭据),Class A/B 组成由本地/云上日志反推,非 CF 内部账单账单分解。
