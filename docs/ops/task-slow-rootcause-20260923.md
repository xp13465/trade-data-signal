# 盘后计划任务"慢+越来越慢"根因调研(2026-09-23)

> 调研范围:update_all 主链(17:50)全段耗时,数据来源=云上 `/home/ubuntu/code/trade-data/data/logs/`(可追溯 9-13~9-22 共 10 天)+ DB 只读查询 + 本地代码研读。**不 commit 不改代码**。

## 0. 结论摘要(一句话版)

**慢的主因 = deploy.sh 内 fund-nav(fund_nav/{code}.json 共 26458 个文件)R2 上传**——9-22 一次传 21957 个耗时 6225s(1h43m),占 deploy 段(18:14→21:19)的 56%;上传文件数由「当天入库净值的基金数」决定(数据源节奏,非代码可控),单日上限≈基金总数 2.6 万(**有界但值大**);**真正无界增长**的是:fund_daily_nav 历史行数(每年 +17%)、每文件 nav 数组(5年1269行/每天+1行)、signal_kelly 每次全量重算全历史。keep_alive 修复(d94233189,upload_r2.py 主通道复用 HTTPS 连接)9-22 晚已 merge,**9-23 晚生效**,是当前最大单项提速(注释预期 6225s→1500-2000s),但**不是有界化的全部**。

---

## 1. 盘点可追溯历史(调研范围 1)

| 日志 | 保留 | 范围 |
|---|---|---|
| update_all_*.log | 15 个文件 | 9-13~9-22(交易日主批 9-14~9-22 共 7 个,9-13/19/20 非交易日) |
| deploy_*.log | 119 个文件 | 9-13~9-23(含盘中/凌晨多批次,主批按实际开始时间命名) |
| pipeline_*.log | 每日 4 条 | 同窗口 |
| DB(public_fund.db/etf_national_team.db/sentiment.db) | 无裁剪 | fund_daily_nav 2021-07-05 起;**etf_daily 2005-02-23 起**,可追溯 5~21 年 |

结论:**日志仅 10 天窗口,DB 可追溯多年**。趋势判断以日志 10 天 + DB 多年结构数据双支撑。

## 2. update_all 总耗时逐日序列(调研范围 2)

交易日主批(update_all.sh 开始→结束,含 deploy):

| 日期 | 总耗时 | 4pipeline 采集 | deploy 段 | fund-nav 上传 |
|---|---|---|---|---|
| 9-14(一) | 无结束行(异常) | width 17:50→19:25(95min) | 19:28 开始,upload-trade-sim 超时被 kill | 22:07 补跑 3678 个 716s |
| 9-15(二) | 40min | 17:50→18:11 | 18:14→18:30(16min) | 6 个 13s |
| 9-16(三) | 1h43m | 17:50→18:18 | 18:20→19:15(55min) | 1 个 12s |
| 9-17(四) | 1h01m | 17:50→18:12 | 18:14→18:45(31min) | 4 个 9s |
| 9-18(五) | 4h09m | 17:50→18:15 | 18:16→21:24(3h07m) | 26132 待传,7200s 超时被 kill+checkpoint 续传 4132 个 1688s |
| 9-21(一) | 1h47m | width 17:50→19:28(97min,mootdx 停服) | 19:30→19:37(7min) | 60 个 25s |
| 9-22(二) | 3h37m | 17:50→18:13 | 18:15→21:19(3h04m) | **21957 个 6225s** |

**趋势判断:10 天窗口内是"波动"不是"单调增长"。** 高耗时日(9-18/9-22)的耗时单点 = fund-nav 大上传;9-15~9-17 三天小上传日总耗时仅 40~103min。用户感知"越来越慢" = 大上传日出现时(如 9-22)一次拖 3h+,且未见收敛迹象。

## 3. 分段耗时定位(调研范围 3)

deploy 段(9-22 3h04m)拆解:
- **fund-nav 上传 6225s(1h43m,56%)** ← 唯一 7200s 超时通道的通道(deploy.sh L570 `run_r2_upload "upload-fund-nav" 7200`)
- export.py 段:~15-20min(a + holdings 636s + signal_kelly_backtest 157s + 其他全量)
- width pipeline(采集段):正常日 23min(9-22),9-21 因 mootdx 停服+baostock fallback 5850s(异常,外部源)
- verify-r2 对账:补传 75 个(9-22)
- check_signals~结束:7min(9-22)

**结论:涨在哪 = deploy 内 R2 上传段,细分 = fund-nav 通道。**

## 4. fund-nav 上传拆解(调研范围 4,重点)

机制(代码确认):
- 产物 = `static-site/data/fund_nav/{code}.json`(每基金一个文件,26458 个,共 578MB),`export_fund_nav.py` **每次全量重算全部基金**(读 fund_daily_nav 全史,9-22 耗时 103s)
- 上传 = `upload_r2.py cmd_upload_fund_nav` 增量(md5 指纹,L896-920)+ checkpoint 断点续传(L958-999)+ 8 线程并发 + 每文件 PUT+HEAD 对账(L736/L746)
- **待传文件数 = 两次 export 之间 DB 新增净值的基金数**(nav 数组内容变化 → md5 变 → 重传)

逐日上传量(数据源节奏驱动,非代码可控):

| 日期 | 待传/全量 | 实传耗时 | 备注 |
|---|---|---|---|
| 9-13(日) | 14870/26370 | 2112s | 非交易日补推(周末净值积压) |
| 9-14(一) | 3678(22:07 补) | 716s | 主批被 kill |
| 9-15~9-17 | 6 / 1 / 4 个 | 9-13s | 净值未大更新 |
| 9-18(五) | 26132/26436 | 7200s 被 kill + 续传 1688s | **净值大面积入库日** |
| 9-20(日) | 12936/26436 | 3672s | 非交易日补推 |
| 9-21(一) | 60/26456 | 25s | |
| 9-22(二) | **21957/26458** | **6225s** | **主因** |

**fund-nav 文件数 = 基金总数,近 12 天 26370→26458(+88,每天约 +7 只新基金),不是暴增;真正影响上传量的是当天入库净值覆盖的基金数,单日上限≈2.6 万(有界但大)。**
每文件耗时(无 keep_alive 时)≈ 6225s/21957 = 0.28s/文件(跨境 HTTPS 握手为主,注释 L743:TCP 1.16s/首字节 2.10s,8 线程摊薄)。

## 5. 数据量增长驱动(调研范围 5)

| 数据 | 现状 | 增长 | 是否无界 |
|---|---|---|---|
| fund_daily_nav 行数 | 2234 万行(2021-07 起) | 每年 +17%(2024:450万→2025:525万→2026前9月:432万);每天 ~2.4-2.6 万行 | **是,线性无界** |
| public_fund.db 体积 | **2.5GB** | 随上表 | 是 |
| fund_nav 单文件 nav 数组 | 5 年 1269 行(000001) | 每天 +1 行/基金 | **是,线性无界**(17% 年增) |
| fund_nav 文件数 | 26458 | +7 只/天(新基金) | 慢增长(约 +1%/年) |
| etf_daily 行数 | 148 万行(2005 起) | 每天 +1600 行,2026 年 27 万行/年 | 是,线性无界 |
| signal_kelly_trades.json | 86.5MB | 随交易事件数,增长缓慢 | 弱线性 |
| signal_kelly_snapshots/ | 22 个文件 | **每天 +1 个文件(无轮换)** | **是,文件数无界** |

## 6. 历史重算面(调研范围 6)

| 脚本 | 重算方式 | 耗时现状 | 增长性 |
|---|---|---|---|
| export_fund_nav.py | **每次全量重算全部 26458 只**全史 | 103-165s | 随行数线性(当前不瓶颈) |
| export.py --incremental | 增量,但 `signal_kelly` 前缀在必更白名单(L855)**每次强制全量** | ~15min(含 holdings 636s) | 弱线性 |
| signal_kelly_backtest.py | **每次全量重算全历史**(读 etf_daily 148 万行全史,输出 all 周期全量 trades 列) | 157s(9-22) | 随交易日线性 |
| signal_kelly_snapshot.py | 每日新增快照文件 | 秒级 | 文件数无界(+1/天) |
| width 采集 | 增量(5200 只/次) | 正常 23min;9-21 mootdx 停服 97min | 外部源波动 |
| backup_db(21:00) | 全库备份 | 秒~分钟级 | 随 DB 体积(2.5GB)增长 |

## 7. 根因结论(每条附证据)

1. **慢的主因 = fund-nav 上传**(9-22 6225s,占 deploy 56%;9-18 超 7200s 被 kill 后 checkpoint 续传)。证据:deploy_20260922_1814.log L883 `[fund-nav] ✓ 上传完成 21957/21957, 耗时 6225.8s`;update_all_20260918_1750.log L1296-1297 超时 kill。
2. **上传量由数据源净值入库节奏决定**:待传数 = 期内存量 DB 新增净值基金数(0~2.6 万波动)。证据:9-15 传 6 个 vs 9-22 传 21957 个;fund_daily_nav 每日行数 2.4-2.6 万。
3. **"越来越慢"的驱动 = 结构无界增长**(当前贡献小,但随时间放大):
   - fund_daily_nav 每年 +17%(DB 2.5GB)→ export_fund_nav 每文件 nav 数组每天 +1 行 → 单文件大小线性增;
   - signal_kelly_backtest 每次全量重算全历史(etf_daily 148 万行),157s 线性增;
   - signal_kelly_snapshots 文件数每天 +1 无轮换;
   - public_fund.db 2.5GB → backup_db/rsync data/ 随之增。
4. **波动源**:width pipeline 外部源(mootdx 停服 9-21 5850s)、holdings/akshare 网络。
5. **keep_alive 修复已钩**:d94233189(13799cbda)9-22 22:46 merge,upload_r2.py L736/L746 PUT+HEAD 复用线程连接,注释预期 21957 文件 6225s→1500-2000s,9-23 晚首效。

## 8. 提速方案(keep_alive 之外)

| 方案 | 动作 | 落点 | 估算收益 |
|---|---|---|---|
| ① keep_alive(已 merge) | PUT+HEAD 复用连接 | upload_r2.py L736/L746 | 21957:6225s→1500-2000s(fund-nav 单通道) |
| ② fund-nav 上传拆出主链异步 | deploy.sh 内 upload-fund-nav 改为 `&` 后台 + update_all 尾部不再重复跑 | deploy.sh L570 / update_all.sh L221-226 | 主链固定少 25~100min;异步任务单独完成 |
| ③ update_all 尾部重复的 upload-fund-nav 去掉 | 第二次扫描(10s)虽小但每次多摸 26458 文件 | update_all.sh L225 | ~10s,顺带减文件 IO |
| ④ verify-r2 只对账当日 changed key,不全量 HEAD 3 万 | verify-r2 已增量?确认 | upload_r2.py verify-r2 | 视现状 |
| ⑤ 上传并发 8→16 线程 | ThreadPoolExecutor max_workers | upload_r2.py L761/L2150 | 网络非瓶颈时 ~30-40% |

## 9. 有界化方案(核心,每条含"为什么有界")

### A. fund-nav 上传解耦异步(主链时长有界)
- **动作**:deploy.sh 的 `run_r2_upload "upload-fund-nav"` 拆为独立后台任务(如 20:00 独立 systemd timer),update_all 主链不等它;或 deploy 内最后 fire-and-forget。产物生成仍在主链,上传异步入 R2。
- **为什么有界**:主链固定区间 = 采集+export+其他通道(现约 1.5h);fund-nav 上传的耗时不再计入用户等待区间。
- **落点**:deploy.sh L570 / update_all.sh L221-226。
- **风险**:上传失败告警由独立任务负责;check_signals 不依赖 R2 上传(读本地产物),已验证。

### B. fund-nav 桶化合并,PUT 次数固定(上传耗时上限有界)
- **动作**:export_fund_nav.py 输出改 256 桶(按 code 前 2 位分桶,每桶 `nav_bucket/{xx}.json`,内含该桶基金 map)。PUT 次数从 26458 → **256(固定)**。
- **为什么有界**:桶数恒定,不再随基金数/新基金发行增长;单桶 ~2.3MB,单 PUT 时间可控(<100MB 不走 multipart)。
- **落点**:export_fund_nav.py(输出结构)+ upload_r2.py cmd_upload_fund_nav(glob 改桶)+ **前端 app.js L26923**(`r2/fund_nav/{code}.json` 改为读桶内再取 code;弹窗懒加载语义需 eval:per-code 改 per-bucket 拉取,首屏多拉 2.3MB,当前 nav 5 年 1269 行/20KB,桶 256 只全拉约 5MB——可接受或有取舍需要用户拍板)。
- **诚实标注**:这是"文件数 vs 懒加载粒度"的取舍:文件合并牺牲"点开才拉",换来上传次数恒定。若保留懒加载,则上传次数上限 = 基金总数 2.6 万,但增长极慢(~+1%/年),配合 ①keep_alive 单文件 0.08s,单日上限 ~35min 也算"有界"(上限值固定)。

### C. 单文件内容有界:nav 历史截断/归档(文件大小有界)
- **动作**:export_fund_nav.py 加 `--retain-years N`(建议 5 年,当前即 5 年),满 N 年的老 nav 历史移出每日文件(归档 R2 低频前缀如 fund_nav_hist/,或截断前端 all tab 不可达处)。
- **为什么有界**:每文件 nav 行数封顶 → 文件字节封顶 → PUT 时间与历史长度无关。
- **落点**:export_fund_nav.py L124-145(查询 WHERE date >= cutoff)+ 前端 all tab 边界。
- **诚实标注**:前端"全部历史" tab 会降级为近 N 年;需要用户确认 N(基金净值弹窗 5 年足够?),或老数据走低频归档区保持全史可达。

### D. signal_kelly 增量重算(重算范围有界)
- **动作**:signal_kelly_backtest.py 增加"滚动窗口"模式:只重算最近 N 个交易日(如 60 天)的事件,更早交易记录复用上次产物段拼接;trades 列式文件按日 append。
- **为什么有界**:每日新增交易日带来的重算范围固定为 N 天,与全历史(2021 起 1900+ 交易日)无关。
- **落点**:signal_kelly_backtest.py(读 etf_daily 的 SQL L615 `_batch_load_etf_prices` 加 date >= cutoff;输出拼接)
- **注意**:前端按 cutoff 过滤 y1/y3 依赖全量列(注释 L177),拼接须保证 y1/y3 窗口口径不变,防前视铁律(§5.1⑥)复核:截断重算与全量算出的 t 之前部分逐位一致。

### E. DB 历史归档(DB/备份有界)
- **动作**:fund_daily_nav/etf_daily 老于 N 年(如 3 年)数据迁归档表(同库 or 独立 public_fund_hist.db),主库每日增量只进近 N 年区。
- **为什么有界**:主库行数封顶 → public_fund.db 体积封顶(现 2.5GB 年 +17%)→ backup_db/rsync/查询耗时封顶。
- **落点**:采集层 cleanup + backup_db.sh 范围。**影响面大**(所有读全史的脚本/回测),须版本治理(§5.4⑥),建议独立排期,与"本次提速"解耦。

### F. signal_kelly_snapshots 轮换(文件数有界)
- **动作**:只保留最近 60 个每日快照,更老归档 R2 低频或删除;此前端 lab「演进」展示保留 60 日窗口。
- **为什么有界**:文件数封顶 60+2,不再每天 +1。
- **落点**:signal_kelly_snapshot.py(生成后轮换)+ upload_r2.py upload-kelly-snapshots 同频。

### G. 超时兜底机制改为"任务级预算"而非"单通道放水"
- **动作**:deploy.sh 引入全链时长预算(如 90min),超预算时:上传通道降级为异步继续、其余步骤不受阻塞;fund-nav 超时从"7200s 硬等"改为"入异步队列"。
- **为什么有界**:任何单通道异常不再拖垮整链时长;既有 checkpoint 续传(已上线)保证 kill 后可续。
- **落点**:deploy.sh run_r2_upload 封装 + update_all.sh 流程编排。

## 10. 方案优先级建议

| 优先级 | 方案 | 理由 |
|---|---|---|
| P0(已合并) | ① keep_alive | 已生效,6225→1500-2000s |
| P1 | ② fund-nav 上传异步解耦 | 主链时长立即有界,单点改动小 |
| P1 | ③ 去重复 upload-fund-nav | 顺手 |
| P2 | B 桶化 或 C 截断(需用户拍板取舍) | 上传上限从 2.6 万次 → 256 次/或文件大小封顶 |
| P2 | D signal_kelly 增量 | 治全量重算线性增长 |
| P3 | E/F/G | 长期治理,独立排期 |

## 11. 诚实标注

1. **趋势":越来越慢"在 10 天窗口内 = 波动,不是已证实的单调增长**;但结构性无界增长源(fund_daily_nav 年 +17%、snapshots 文件数每日 +1、signal_kelly 全量重算)有 DB 多年数据支撑,长期必放大。
2. **驱动 100% 确认项**:9-22 慢 = fund-nav 上传 6225s(日志行直接证据);上传量 = 净值入库基金数(DB 每日行数 vs 上传行数吻合)。**待验证项**:①keep_alive 后实际每文件耗时(9-23 晚首效后从日志实测确认)②净值入库节奏为何 9-15~17 极小/9-18/22 极大(数据源发布延迟+采集任务时点,未逐日对账采集日志)③export.py 段精确秒数(日志无逐行时间戳,估算)。
3. **keep_alive 收益数值来自代码注释(upload_r2.py L744 预估),非实测**,9-23 后需实测回填。
4. 报告数字均来自只读查询与日志,无写操作。

## 复现命令

```bash
# 云上抽 fund-nav 上传行(任意日)
grep "\[fund-nav\]" /home/ubuntu/code/trade-data/data/logs/update_all_20260922_1750.log
# 抽 deploy 段起止
grep -m1 "deploy.sh 开始\|deploy.sh 结束" /home/ubuntu/code/trade-data/data/logs/update_all_20260922_1750.log
# DB 每日净值入库数
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'python3 -c "import sqlite3;c=sqlite3.connect(\"/home/ubuntu/code/trade-data/data/public_fund.db\");print(c.execute(\"SELECT date,COUNT(*) FROM fund_daily_nav WHERE date>=\\\"20260901\\\" GROUP BY date ORDER BY date\").fetchall())"'
```
