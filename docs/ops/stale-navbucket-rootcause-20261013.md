# nav_bucket/fund_nav 部署校验间歇 FAIL —— 根因报告

- 日期: 2026-10-13（根因调研日; 线上复查 10-13 10:39-10:44）
- 来源: researcher 只读调研报告（云上只读查询 + 线上只读 curl, 未改任何代码/配置/数据）,
  本文收编原文 + 补「复现段」（原文末「修复方向 4 = 校验口径补强」即后实施任务 C2 的前身）。
- 关联实施报告: `docs/ops/deploy-fundnav-selfheal-20261013.md`（C1 自愈 + C2 第三口径, 同日）
- 派单背景: 主控「fund_nav 项间歇 FAIL, 失败即终止部署并邮件+飞书 critical 告警（ledger key=`deploy_check_data_integrity_fail`; 10-13 02:16:35 一次）」

## 0. 根因一句话（TL;DR）
nav_bucket 256 桶产物在 10-12 17:50（update_all 每日**唯一**全量重出窗口）重出时, 输入 DB 正处于
「10-08/09/12 三个交易日净值全 NULL / 错日写入」的破损态（旧 `fetch_daily_nav` 撞东财
「showday 先滚到当日、净值稍后发布」窗口 = #251 同机制）→ payload 最新日停在 09-30（91.7% 基金）。
随后 DB 被修复（10-12 22:41 手工回填 + #251 修复 10-13 00:19 上线）变成「DB 领先产物」; 而产物要等
下一次 17:50 才重出 → 期间**每个** deploy 的 fund_nav 校验必然 FAIL（exit 1 → 终止部署 + 告警）。
定性: **产物生成问题（输入 DB 破损）为主** + 编排特性（重出一天一次, 其余链只过闸不重出）放大;
**#251 修复不是引入者**（FAIL 自 2026-09-14 起就已间歇出现, 早一个月）。

## 时间线（多源证据闭合）
- 09-14 起: fund_nav 校验 FAIL 已间歇出现（`deploy_20260914_1644.log` 起, 见 Q6）。
- 09-28/29/30、10-08/09/12: 采集多次写「全 NULL 行/错日行」（#251 记录的已知受影响日）;
  其中 10-08 全 NULL 在当晚 10-08 22:35 就被 `check_data_gap[severe]` 抓到, 10-09 22:35 再报,
  10-12 22:35 报 10-09（`check_data_gap_launchd.log` L107/L117/L126）。
- 10-12 16:30/17:00: `public_fund_daily` 两次写 @20261012
  （`public_fund_daily_20261012_1630.log` / `_1700.log` 各一行「fund_daily_nav 写入 24240 行 @20261012」）。
  16:4x deploy 校验 FAIL（甲组, 错日值）; 17:00 写入后 17:07-22:00 校验转 PASS。
- 10-12 17:50 update_all: `export_fund_nav` 全量重出（`update_all.sh` L101-107）, 读到破损 DB
  → 256 桶 payload 停在 09-30; 18:16-18:18 完成（256 桶 mtime 全 18:18:29）。
- 10-12 18:20-18:23: 异步上传 R2 成功（21/21 桶, 增量指纹只传变更桶）→ 线上 nav_bucket 停在 09-30。
- 10-12 22:31-22:41: 前会话手工备份（`/home/ubuntu/logs/bk251.log`）+ 回填（`bf251.log`）:
  10-12 真值归位、10-09 用次新列补齐（unit+acc）、10-08 用 10-09 的 prev 链式补 unit（acc 无来源保持 NULL）。
- 10-12 22:46:43: 提交 #251 修复（`f224032e1`）→ 10-13 00:18:19 merge（`0c1de7118`）→ 00:19:10 云上 pull（已上线）。
- 10-13 02:06 deploy FAIL（乙组, 真值态）→ 02:16:35 邮件+飞书直发（ledger）; 05:00 FAIL 被 dedup 抑制
  （`deploy_20261013_0500.log` L594: `suppress ... age=10225s < window=21600s`）。
- 10-13 10:39 线上复查: `ss.fx8.store/r2/nav_bucket/2e.json` 001037 date=20260930（仍陈旧）。
- 预期自然恢复: 10-13 17:50 update_all 以修复后 DB 重出 → 校验恢复 PASS → 异步重传变更桶 → 线上恢复。
  注意: 17:50 之前（16:30/16:35/17:00 前后）的 deploy 预计仍 FAIL（产物未重出）。

## Q1 为什么这些 code 的 payload 最新日停在 20260930?（读 export_fund_nav.py）
结论: 不是「某个 code 不被重出」的筛选/增量问题, 而是**生成时刻输入 DB 里这些 code 的
10-08/09/12 行 unit_nav 全为 NULL**, 而产物 date 定义 = 该 code 最大非空 unit_nav 日。
证据:
- `scripts/export_fund_nav.py` L139-143: 取码全量（仅过滤 `fund_code IS NOT NULL/!=''`）, **无任何
  「跳过 code/桶」条件**; L166-206 流式分桶, 每次运行全量重出 256 桶。
- L174-178（核心）: `SELECT date, unit_nav, acc_nav FROM fund_daily_nav WHERE fund_code=?
  AND unit_nav IS NOT NULL ORDER BY date ASC` → L187 payload date = `nav[-1][0]`（最大非空 unit 日）。
  → 什么条件会让某 code「不重出/停在旧日」: ①DB 该 code 新日期行 unit_nav 为 NULL（**本次原因**）;
  ②进程中途被杀致未 flush 桶保留上一版（docstring L31-35; 本次非此因: 256 桶 mtime 全 10-12 18:18:29,
  为一次完整重出）; ③R2 上传层整文件 md5 指纹跳过未变桶（docstring L28-30; 那是"没变化不上传"的
  设计, 本次线上陈旧桶内容本身即陈旧）。
- 输入破损的直接量化（修复前备份 + 回填日志）:
  `/home/ubuntu/logs/bf251.log`「BEFORE: {'20261008': {'n': 24218, 'unit_nn': 0, ...},
  '20261009': {'n': 24224, 'unit_nn': 0, ...}}」;
  `/home/ubuntu/backups/public_fund.db.pre251-20261012`（10-12 22:31 备份）逐日实测:
  20261008: 24218 行 unit 非空 0 / 20261009: 24224 行 非空 0 / **20261012: 24240 行 非空 0**
  → 三日全 NULL; 故导出时（17:50）全库最大非空 unit 日 = 20260930。

## Q2 两组 FAIL 形态分开解释（成因不同, 表现同为「DB 领先产物」）
甲组 = 10-12 16:44 deploy（校验块见 `deploy_20261012_1644.log`; 同文重复于
`backfill_evening_launchd.log` L45070-45132, 校验头 `generated_at=16:49:06`）:
- 日志原文（节选）: `✗ fund_nav: DB↔产物不一致: 001037: [DB 领先产物 12 天(新净值已入库, 产物待重出)]
  DB最新=('20261012', 1.6829, 2.3759) vs 产物最新=('20260930', 1.7941, 2.4871); ... 001324:
  DB最新=('20261012', 1.9875, 1.9875) ... 020934: DB最新=('20261012', 1.0308, 1.0308) ...`
- 定性 = **错日写入态**（旧代码把 10-09 的值写到 10-12 行）: 三个 code 的 10-12「值」逐一证明
  = 各自 10-09 真值 —— 今日 DB 实测 001037 10-09=(1.6829, 2.3759)、001324 10-09=(1.9875, 1.9875)、
  020934 10-09=(1.0308, 1.0308), 与甲组「10-12 行」逐位相同（三 code 全部吻合）。
- 中间过程（高置信推断, 证据链完整）: 16:4x 后 17:00 采集再次写 @20261012（24240 行）, 把错日值
  覆盖为 NULL → 22:31 备份实测 10-12 行 unit 非空 0（prev 非空 22849）→ 17:07-22:00 校验 PASS
  （此时 DB 最大非空=09-30=产物）。覆盖动作的具体写入内容未逐行留档, 标注为推断。
乙组 = 10-13 02:06 deploy（`deploy_20261013_0206.log`; 同文 `backfill_evening_launchd.log` L45970-46032）:
- 日志原文（节选）: `016572: [DB 领先产物 12 天] DB最新=('20261012', 1.533, 1.56) vs 产物最新=
  ('20260930', 1.5082, 1.5352); DB尾3=[('20261012', 1.533, 1.56), ('20261009', 1.5051, 1.5321),
  ('20261008', 1.5124, None)] ... 001265 / 014163 同构`
- 定性 = **22:41 回填后的真值态**: 10-12 已是真值（与 22:41 A 路写入一致）, 10-09 已补齐,
  10-08 =(unit, acc=None) —— acc=None 是回填 B 路设计（链式推导只有 unit/涨跌幅, acc 无来源）。
- 两组差异: 甲组 DB 侧=修复前「错的 10-12 值（实为 10-09）」; 乙组 DB 侧=修复后「真的 10-12 值」。
  共同点: DB 最新有效日（10-12）> 产物（09-30）→ 同一断言 FAIL。**成因不同, 表现相同**。
- 附: 每次 FAIL 只展示前 3 个不一致（旧代码 `mismatch[:3]` 截断）, 不是只有 3 个 code。

## Q3 产物生成问题还是编排顺序问题?
结论: **产物生成问题为主**（输入 DB 破损, 见 Q1）; 编排上是**特性放大而非时序倒挂**:
- `update_all.sh` L101-107 注释明说「先刷产物再过闸门（fund_nav 时序倒挂修复 2026-08-27）」:
  历史上出现过「deploy 抽样拿当晚已进新净值的 DB 对昨晚产物比对 → 时序倒挂误拦（17:02/17:58 两连拦）」,
  修复=在链内把 `export_fund_nav` 前置到 O1 统一 deploy（L152）之前。**链内顺序正确**。
- 但 export 只在 update_all（17:50）一天跑一次; 其余带 deploy 的链（`public_fund_daily` 16:30/17:00、
  `backfill` 16:35/21:00/02:00、`us_stock_morning` 05:00、`public_fund_full` 22:00）只过闸**不重出产物**。
- `deploy.sh` 内**不含** fund_nav/nav_bucket 生成（grep `fund_nav`/`nav_bucket` 零命中; `update_all.sh`
  L126-128 注释「deploy.sh 内 run_r2_upload upload-fund-nav 已移除」）。
- 断言本体: `scripts/check_data_integrity.py` `check_fund_nav`; 抽样（30 桶随机取码）
  DB 尾3 vs 产物尾3 逐位比对; 方向注记明确写「场景是'DB 多了新净值、产物待重出'
  （fund_nav 时序倒挂; 根治见 update_all.sh 先 export 再过闸）」; 输出「DB 领先产物 N 天
  （新净值已入库, 产物待重出）」。该「根治」只覆盖 update_all 链自身 —— 任何在 17:50 重出**之前**
  写 DB 的链（如 10-12 22:41 的手工修复、当日 16:30/17:00 采集）之后再跑 deploy, 必然命中 FAIL。
- 跳过分支: 无「DB 领先时自动重出」的补救路径 —— 只有「等明天 17:50」。（→ 本次 C1 自愈补上）

## Q4 规模统计（实测, 云上只读脚本）
- DB `fund_daily_nav` 每 code 最大日期 vs 256 桶 payload 最新日期（全量比对, 本轮早段实测）:
  - stale（DB 最新日 > 产物最新日） = **23,524 / 26,657 = 88.2%**;
  - payload 最新日分布（主要）: **09-30 = 24,461（91.7%）**、09-28 = 995、09-29 = 748、09-24 = 78、空 = 59;
  - stale 的 DB 最新日: 10-12 × 22,088 + 10-09 × 1,431 + 10-08 × 5 = 23,524（闭合）;
  - only_db = 0 / only_payload = 0（同集, 无增删）;
  - 分布: 256/256 桶均有 stale（每桶 79~119 只, **无桶聚集**）;
  - 类型: 混合型-偏股 98%、债券型-长债 98%、指数型-股票 72%、货币型 0%、FOF 10-16%, 总 88.2%
    （非某类基金特有）。
- 残留旧破损: payload 停在 09-28/09-29 的 995/748 只 = 更早（09-28/29/30）全 NULL 波的未复原者。

## Q5 爆炸半径（一次 deploy 除 nav_bucket 外还发布什么? 终止后线上缺什么?）
- deploy 段序（正常 PASS 例）: `etf_index_map`/`export`/`accum_nav` 同步 → **数据产物校验闸门
  （deploy.sh L323-324）** → build_min → rsync 静态 JSON→signal 树 → rsync data/ → 触发 R2 上传
  → `check_version_progress` → 段2（git commit/push + staticdata 备份）。**FAIL 时以上全部跳过**
  （日志原文「✗ 数据产物校验失败（退出码 1）, 终止部署（4 类事故拦截）」）。
- nav_bucket 上传**不在 deploy.sh**: 由 update_all 链 rsync 后异步触发 `fund_nav_upload_async.sh`
  （`update_all.sh` L120-140, systemd-run）; 故线上 nav_bucket 陈旧 = 「产物本身按破损 DB 生成（09-30）
  + 18:20-18:23 增量上传」的结果, **不是** deploy 终止造成。
- 终止的部署本身不丢数据: 其产物生成步在校验之前已完成, 被跳过的只是「发布」（build_min/rsync/R2/git）;
  后续成功 deploy 会全量带上。10-12 16:32/16:44 终止 → 17:07-22:00 系列成功补发 ✓;
  10-13 02:06/05:00 终止 → **至今（10-13 10:44）0 次成功 deploy**, 待 16:30+ 下一次尝试。
- 线上实测（10-13 10:39-10:44, curl 带浏览器 UA）:
  - `ss.fx8.store/r2/nav_bucket/2e.json`（前端 app.js 走此路径）: 200, content-length 2162799,
    etag=「1848ff244a1a3b5238e014e3d6cb6859」== 下载体 md5; 001037 date=20260930, count=1276,
    nav 尾3 = 09-28/29/30 —— **确认线上仍陈旧**;
  - `ssd.fx8.store`: `/r2/nav_bucket/2e.json` → 404（CF HTML）; **`/nav_bucket/2e.json`（无 /r2/ 前缀）
    → 200 同 md5 `1848ff...`**（同 R2 对象, 同为 09-30 陈旧）;
  - `s.sugas.site` / `sss.sugas.site`: `/r2/nav_bucket/` 与 `/nav_bucket/` 两路径均 404（该路径不供此文件）;
  - 对照（其余数据新鲜）: `ss.fx8.store/data/signal_kelly_snapshots/index.json` updated_at=2026-10-12 22:07。
- 用户可见影响: 仅「基金评分弹窗-净值走势」少 10-08/09/12 三个交易日（还叠加 09-28/29 的 995/748 只
  更早缺口）; 其余站点功能数据由各链与后续成功 deploy 正常刷新。

## Q6 与 #251 的因果判定
结论: **无因果（#251 修复未引入该 FAIL）; 但本次「10-08/09/12 全 NULL 停摆」与 #251 同根因机制。**
- 最早出现: **2026-09-14**（`deploy_20260914_1644.log` 与 `deploy_20260914_1830.log` 各 1 次）, 早于
  #251 修复提交（10-12 22:46:43）约一个月, 且此前已横跨多日复发。
- 复发普查（✗ fund_nav 计数）: `deploy_*.log` 共 **34 个日志文件**各 1 次（09-14/16/17/18/22/24/28/29/30、
  10-02×5、10-08、10-09、10-12、10-13）; `backfill_evening_launchd.log` 16 次;
  `public_fund_daily_launchd.log` 13 次（主控口径「同日志累计 20 次」与文件选择有关, 以实测计数为准）。
- 时间线上 #251 修复（10-13 00:19 云上 pull）之后的首次 deploy=02:06 恰 FAIL, 但那是「产物未重出」的
  延续（乙组形态）, **不是修复回归**; 22:41 的手工回填（在合并前）同样不消除 FAIL（FAIL 只取决于
  「DB 领先产物」, 唯一消除=产物重出）。
- 机制同源: 10-08/09/12 三日全 NULL/错日行 = #251 记录的「东财先滚 showday、稍后发布净值」窗口期
  旧 `fetch_daily_nav` 写空/错日行, 与 #251 docstring「已知受影响日: 09-28/29/30、10-08/10-09/10-12」一致。

## 复现段（本轮补, 2026-10-13）

### ① 88.2% stale 是怎么算出来的
云上只读脚本（沿现网只读通路）:
1. 取 DB 侧: `SELECT fund_code, MAX(date) FROM fund_daily_nav WHERE unit_nav IS NOT NULL GROUP BY fund_code`
   （= 每只基金「最新有效净值日」, 与导出器 L174-178/L187 的口径**逐字同源**）。
2. 取产物侧: 遍历 `static-site/data/nav_bucket/*.json` 256 桶, 逐桶取 `payload["date"]`。
3. 比对: `stale = count(db_max_date > payload_date)` / `count(∪ codes)`。
   → 实测 `23,524 / 26,657 = 88.2%`; 分桶直方图显示 256/256 桶均有 stale、每桶 79~119 只（无桶聚集）。
4. 交叉校验（闭合性）: `stale` 的 DB 最新日分布 `10-12 × 22,088 + 10-09 × 1,431 + 10-08 × 5 = 23,524` 与
   总数逐位闭合; `only_db = only_payload = 0`（同集无增删）。
说明: 上述「口径同源」很关键 —— 若换成「DB 任意最大日」而非「最大**非空**单位净值日」, 会把全 NULL
行也算进来, 得到虚高的 stale 比例。本报告口径 = 导出器口径。

### ② 「DB 领先产物 → 校验 FAIL」怎么复现（本机, 零生产触达）
自动化脚本（入库）: `scripts/tests/repro_fundnav_selfheal_20261013.sh`
（`bash scripts/tests/repro_fundnav_selfheal_20261013.sh`, 人工跑, 不进 CI）。
它用**真** `export_fund_nav.py` + **真** `check_fund_nav` 在 tmp 沙箱跑完整闭环:
```
[1] 造正常态(DB 仅 D0) → 真 export → 校验 ok / 探针 rc=0        ← 负控: 不构造时不误触发
[2] DB 加更近一行 D1、产物不重出 → 校验 fail「DB 领先产物 12 天」/ 探针 rc=3   ← 复现病灶
[3] 跑 fund_nav_selfheal.sh → exit 0 → 产物重出 → 校验转 ok      ← C1 闭环
[4] DB 最新显著日整列 NULL → 校验 fail(第三口径) / 同源侧探针 rc=0 ← C2 治假绿
```
沙箱防误写真树: 脚本开跑即断言 `DB_PATH`/`STATIC_DATA_DIR` 落在 `$SB/` 内, 否则 `exit 9`。
（`export_fund_nav.py` 的 `ROOT` 由 `Path(__file__).absolute().parent.parent` 推导, 刻意不 resolve symlink,
故沙箱内 symlink 亦读写落沙箱。）

手工单步（等价、便于现场排障）:
```bash
# 1) 造 fixture DB（两日: 09-30 有值 / 10-12 有值）
sqlite3 /tmp/sb/data/public_fund.db "CREATE TABLE fund_daily_nav(date TEXT,fund_code TEXT,fund_name TEXT,unit_nav REAL,acc_nav REAL,PRIMARY KEY(date,fund_code));"
# 2) 只按 D0 导出一次 → 产物停在 09-30
REPO=/tmp/sb .venv/bin/python scripts/export_fund_nav.py
# 3) 追加 D1（不重出产物 = 模拟「DB 被改新」）
sqlite3 /tmp/sb/data/public_fund.db "INSERT INTO fund_daily_nav VALUES('20261012','000001','x',1.1,2.1);"
# 4) 跑校验 → 必 FAIL（DB 领先产物）; 跑探针 → rc=3
REPO=/tmp/sb .venv/bin/python scripts/check_data_integrity.py --deploy-mode --data-dir /tmp/sb/static-site/data
REPO=/tmp/sb .venv/bin/python scripts/check_data_integrity.py --fundnav-stale-probe --data-dir /tmp/sb/static-site/data
```

### ③ 「同源比对假绿」怎么复现（C2 修前）
把 DB 最新显著交易日整列 `unit_nav` 设 NULL 后**按同一 DB 重出产物**:
- 同源抽样比对（DB 尾3 vs 产物尾3）**两侧同值 ⇒ 判一致**（这就是假绿）;
- `--fundnav-stale-probe` 同样 `rc=0`（它只认「DB 领先」方向）;
- 修复后由第三口径（`_fund_nav_db_day_coverage`）直接看源 DB 的「最新显著交易日 unit_nav 非空数 == 0」
  → FAIL。`repro_*.sh` 步骤 [4] 即此复现, 且**同时**打印「同源侧 rc=0」作为假绿机理的对照证据。

## 原始证据索引（可复核）
- 云上日志（`/home/ubuntu/code/trade-data/data/logs/`）: `deploy_20261012_1644.log`（甲组）、
  `deploy_20261013_0206.log` / `_0500.log`（乙组）、`backfill_evening_launchd.log` L45070-45132 与
  L45970-46032、`check_data_gap_launchd.log` L107/117/126、`public_fund_daily_20261012_1630.log` /
  `_1700.log`、`deploy_20261013_0500.log` L594（dedup）。
- 云上运行痕迹: `/home/ubuntu/logs/bf251.log`（回填前后对照）、`bk251.log`（备份验证）;
  `/home/ubuntu/backups/public_fund.db.pre251-20261012`（2813755392B, 10-12 22:31）。
- 本地代码: `scripts/export_fund_nav.py` L139-143/L174-178/L187; `scripts/check_data_integrity.py`
  （`check_fund_nav` 及其 5 层结构）; `scripts/update_all.sh` L101-141/L152; `scripts/deploy.sh`（原无 fund_nav）。
- 线上 curl（10-13 10:39-10:44）: ss/ssd `nav_bucket/2e.json`（md5 `1848ff...`, date=20260930）;
  `signal_kelly_snapshots/index.json`（updated_at 10-12 22:07）。
- 数据: 云上只读 SQL（trade-data 主库 + pre251 备份 + `/tmp/backfill_251.py` 同源逻辑）、
  `bf251.log` BEFORE/AFTER 对照。

## 遗留（本轮未动, 仅登记）
1. 10-08 `acc_nav` 全 NULL（22,085 行）: 回填 B 路链式推导只有 unit/涨跌幅, acc 无来源 ⇒ 现仍未恢复;
   第三口径只判 `unit_nav`（判 acc 会永久阻断 deploy）⇒ **acc 维度仍是盲区**。
2. payload 停在 09-28/09-29 的 995/748 只（09-28/29/30 全 NULL 波的未复原者）。
3. 云上 `/home/ubuntu/code/trade-data-signal/data/public_fund.db` 是旧副本（mtime 10-12 18:41, 含全 NULL;
   校验链 gap-check/闸门都读 `REPO=trade-data` 主库, 该副本未参与）—— 建议确认用途或同步。