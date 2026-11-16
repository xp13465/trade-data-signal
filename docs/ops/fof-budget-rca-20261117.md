# RCA:公募 FOF 21:10 整轮预算耗尽 rc=1(2026-11-16)

> 落地来源: /tmp/fof-budget-rca-20261117.md; 落地时间 2026-11-17

调研:只读(云上只 SELECT/只读日志、未改任何 unit/DB/文件);完成时间 2026-11-17 05:0x CST。

## 0. 一句话结论
`trade-fof-nav-collect`(21:10,FOF/QDII 净值止漏)的「整轮预算」= **代码内 290 秒绝对 deadline**(`--budget-seconds` 默认 290、硬上限 290),不是 systemd 超时。2026-11-13 的「方案 C」把一个批次拆成 pass A(recent 增量扫)+ pass B(回补)共用一个 deadline;11-16 是方案 C 上云后**第一个交易日**:pass A 用掉 176s(61%),pass B 只剩 114s 却要跑 435 只(≈200s+),**必然**撞 deadline → 未捕获 TimeoutError → rc=1 → systemd failed → 告警。数据本身没有损坏(每只基金独立事务,已提交全部保留),但 pass B 约 200 只本批基金本轮未做回补,且**手工重跑也补不到它们**(轮转游标已前进)。

## 1. 任务身份与结构
- 云上 unit:`trade-fof-nav-collect.timer`(OnCalendar `*-*-* 21:10:00`,Persistent=true)/ `.service`(`TimeoutStartSec=900`,User=ubuntu,OPS_DELIVERY_EVIDENCE_ENABLED=1)。
- 入口:`/home/ubuntu/code/trade-data/scripts/run_fof_nav_collect.sh`
  - L11-14 交易日闸门(非交易日 exit 0);
  - L21 `run_to 600 "$PY" -m scripts.collect_fof_nav`,L22 `RC=${PIPESTATUS[0]}`,L23-24 打印 rc 后 exit。
- 主流程:`scripts/collect_fof_nav.py`(云上 md5 `c80de4ac…` = 本仓 HEAD 逐字一致,685 行)。
- 整轮结构:池 = fund_basic 中 `fund_type LIKE 'FOF%' OR 'QDII%'`(实测 1822 只);每轮按 code 轮转最多 500 只(BATCH_SIZE);单轮内两遍:
  - pass A「recent 增量扫」(L572-589):对这批 500 只逐只强制 recent 相位(近 7 自然日),推进轮转游标;
  - pass B「回补」(L590-604):同一批剩余预算逐只跑 history/gap 相位,不动游标。
- 三层时间预算(梯度成立,但真正卡住的是最内层):
  1. 应用层 deadline **290s**(`collect_fof_nav.py:294`,由 `:292-293` 强制 ≤290,`:659` CLI 默认 290);
  2. 脚本 `run_to 600`(run_fof_nav_collect.sh:21);
  3. systemd `TimeoutStartSec=900`。

## 2. 预算机制(变量、算法)
- 变量:`budget_seconds`(默认 290.0)/ `deadline = time.monotonic() + budget_seconds - _fund_setup_seconds()`(`:294`)。
- 算法:**整轮绝对墙钟 deadline,不是按阶段/按剩余时间动态分配**。两遍共用同一个 deadline:
  - `attempt()` 顶部硬检查 `if time.monotonic() >= deadline: conn.close(); raise TimeoutError(...)`(`:439-441`);
  - 异常路径检查 `if time.monotonic() >= deadline: raise TimeoutError(...)`(`:523-525`);
  - 每只结束 `time.sleep(min(RATE_LIMIT=0.3, 剩余))`(`:568-569`),即每只固定 0.3s 限速。
- 预算耗尽语义:抛异常,不吞、不做「优雅收尾 rc=0」(`:30` 注释明写);`main()` 只捕获 ValueError(`:672-673`),TimeoutError 一路冒到顶 → traceback → 进程 exit 1。
- 外层的 `run_to 600` / `TimeoutStartSec=900` 在 11-16 均未触发(实际 292s 就自己抛了)。

## 3. 11-16 这一轮卡在哪(逐段耗时,日志原文)
来源:`journalctl -u trade-fof-nav-collect.service --since 2026-11-16`(与 `data/logs/fof_nav_collect_20261116_2110.log` 同内容)。
- 21:10:00 unit 启动;21:10:02 python 起跑;开轮:总数=1822,轮转起点 026929,本批 500 只。
- pass A(51s~176s):500/500 全部完成,154s-176s 段 `ok=435 fail=65 empty=65 error=0 written=3983`。
  - `empty=65` 全是合法空(封闭期/份额类区间无净值),`error=0` ⇒ 本轮无真实异常。
- pass B(176s 起):50/500@195s → 100@213s → 150@231s → 200@249s → **250/500@266s**,`ok=460 fail=290 empty=290 error=0 written=5594 舍入对齐=3440`。
- 21:14:52(292s)`collect_fof_nav.py:599 → attempt() → :441 raise TimeoutError('FOF整轮预算耗尽…')`,rc=1。
- 归因(数据说话):
  - **不是外网慢 / 不是重试风暴**:全程 `error=0`,无 FAIL 行,无 429;每只限速 0.3s 就占 pass A 的 85%(500×0.3s=150s / 176s)。
  - **不是串行设计本身**:单遍方案时代(11-09/11-10)同样 500 只只用 162s / 174s 就跑完并 rc=0。
  - **是「两遍共用 290s」的预算分配**:pass A 实测 176s ≈ 设计预估「~0.35s/只 ≈175s」;剩 114s,而 pass B 剩余 435 只按实测 ~0.46s/只需 ≥200s ⇒ 结构性必超。
  - 历史同病:11-11(250/500@244s)、11-12(250/500@244s)、11-13(350/500@277s)全是 rc=1;这三天是单遍代码,但批次处于 history 相位(11-11 `written=40736` / 197 只 ≈ 207 行/只,`fetch_lsjz` 固定 `pageSize=20`(:203/:218),一只一年历史要 ~11 个分页请求)⇒ 单遍也会超。11-13 的「方案 C」只改了**优先级**(先保新鲜度),没改**失败语义**,于是 rc=1 由「偶发」变成「每交易日必发」。
  - 旁证:请求 `pageSize=50` 实测被上游强制回 `PageSize=20`(curl 实测 ErrCode=0/PageSize=20/TotalCount=452/returned=20)⇒ 靠放大分页提速这条路不通。

## 4. 预算耗尽的后果:有没有半成品 / 用户可见不一致
- **数据层:没有半成品**。每只基金一个事务(`BEGIN IMMEDIATE` :476,`commit` :498,异常显式 `rollback` :514-517);跳过的那只(顶检查 raise)根本没开事务。已提交 = 真落库。
- **本轮是"批次级部分完成"**:pass A 100%(attempted=500/500,selected_not_attempted=0),pass B 约 250/500 档位后截断(deadline 在 292s 到,最后一行进度 250/500@266s,剩余 26s 约再跑 50 只 ⇒ **约 200 只本批基金本轮没进 pass B**)。
- **证据收据如实记失败,不是假绿**:`data/ops_delivery/index/fof-nav.json` → `stage_status=failure`、`reason=TimeoutError`、`consumer_witness.fund_evidence.collection_status=failure`,counts:`attempted=500 / committed_rows=9043 / committed_targets=795 / errors=0 / legal_empty=319 / pool_not_attempted=1322`。
- **用户可见面:本轮没有引入不一致**。
  - 该任务只写 `data/public_fund.db`,不写 static-site/R2;站点净值桶 `static-site/data/nav_bucket/*.json` 由 `export_fund_nav.py` 在 16:20/17:00/17:50 链生成(`export_fund_nav.py` 头注:入图最新净值通常为 T-1)。21:10 收来的数据在**次日 17:50** 才上站。
  - 全站 FOF 净值只有一张源表 `fund_daily_nav`(`export_fund_nav.py:146` 等所有消费方同表),不存在多展示位各读一份产物 → §22 风险低。
  - 实测抽样:本批 500 只中 484 只库内最新日 = 11-13(上一交易日),非批次 1322 只中 763 只 @11-13、181 只 @11-11 —— 属轮转 + T+1/T+2 的正常滞后;11-13 全池 1262 行,会随后续几轮轮转补齐到 ~1690(对照 11-06 已成熟 1697 行)。
  - 站点侧抽样 026929:`nav_bucket/b7.json` 最新日 11-03;库内已有 11-04..11-13(11-16 21:10 才补上,晚于 11-16 17:00 的导出)⇒ 属"一个导出周期滞后",不是本轮截断造成,11-17 17:50 后自然上站。
- **真正的后果 = 告警噪音 + 回补延后**:
  - 21:15:10 `check_failed_units` 记 failed unit;21:15:28 `schedule_monitor.sh` 发 ops 告警「[告警] fof_nav_collect unit_exit=1」(邮件+飞书,`data/alerts/alert_ledger.jsonl`),22:15 再升级一次;11-11/11-12/11-13 同款,11-14 周末跳过 exit 0 被当成「[恢复]」。
  - pass B 未跑的约 200 只,因游标已前进(last_code=006862),要等下一次轮转(池 1822 / 批 500 ≈ 4 个交易日)才轮到回补。

## 5. 历史回补与续跑语义 / 幂等
- **下一轮不会补本批未跑的 pass B**:轮转是 code 游标制(`:397` 取 >last_code 的 500 只),11-16 结束时 `data/public_fund.fof-nav-progress.json` 的 `last_code=006862`,下一轮从 006872 起,**换一批**;被截断的基金只保留 `work_limits` 相位,等下一个轮转周期。
- **手工重跑同样补不到**:重跑走同一游标 → 又是下一批 500 只;要定向补只能用 `--fund-code`(单只)或 `--onetime-backfill`(只挑无 state 的基金,与这批无关)。这是「续跑语义」的实际缺口。
- **写库幂等**:UPSERT 用 `COALESCE(库值, 新值)`,只填空不覆盖(`:103-113`);每只一个事务;进度文件 `atomic_write_json`(`:567`);重跑不会重复计数/重复落行。
- **通知幂等**:唯一的业务告警是「同源非空冲突」,`--dedup-key fof_nav_nonnull_conflict --dedup-window 72000`(20h)(`:121-122/:173-176`),重跑不刷屏;本轮 error=0 未发。
- **游标语义**:「尝试制」——空/异常也推进(`:571` 注释、`:585`);`work_limits[code]` 记 history_days/gap_fields/phase/recent_through,原子落盘。
- 结论:**幂等安全,但没有「同一批断点续跑」;被截断的部分只能"等轮转"**。

## 6. `complete` 语义(有定义吗?rc=0 等于业务完成吗?)
- **没有「整轮完整/全库完整」的定义**。代码只定义:本轮尝试到哪(`attempted`)、每只基金的相位状态(`fund_collection_state.history_before/gap_after` + `work_limits`),并在日志和 evidence 里明写「本轮尝试(不代表整窗完整)」「pool_not_attempted」。
- **rc 语义**:
  - rc=0 = 循环在预算内走完(或非交易日/无待采/锁被占直接返回);
  - rc=1 = 预算耗尽(未捕获 TimeoutError);
  - rc=2 = 整批失败(有待采 + 零成功零写入 + error>0,`:626-633`);
  - `main()` 只对 rc=2 有显式分支,其余正常 return 0。
- **complete 的近似物** = `ops_delivery/index/fof-nav.json`:11-16 记 `stage_status=failure / reason=TimeoutError / collection_status=failure`;这是「本轮交付失败」,不是「数据为空」。
- **假成功路径(实测存在)**:
  1. 非交易日跳过 exit 0(`run_fof_nav_collect.sh:12-14`)→ 11-14 21:15 监控发「[恢复] fof_nav_collect unit_exit=1」,把"没跑"当"恢复";
  2. 锁被占 `_acquire_lock(nonblock)` → 打印 WARN 并 `return 0`(`:302-306`),reason=`lock_not_attempted`,监控看不到失败;
  3. 全批合法空(`error=0`)→ rc=0 且零写入(设计如此,`:622-627`);
  4. `pool_not_attempted=1322` 是常态(每轮只跑 500),rc 仍可能 0 ——「跑完了但只覆盖一小部分」不可从 rc 区分。
- **收据单位不一致(顺带发现)**:`expected=500(只)` vs `observed=committed_targets=795(按 range 累计)`(`ops_fund_evidence.py:172-208`),量纲不同,不能直接比;做覆盖率机检前必须先统一为「只」。
- 结论:**rc=0 只表示"这轮没崩",不等于业务完成;整套任务缺一个"每只基金在 N 个交易日内至少成功提交一次"的新鲜度判据**,目前唯一信号是进程退出码。

## 7. 根治方案(两套完整,均不含"加大预算/无限重试/关告警")

### 方案 A:相位拆分 = 两个独立 unit(新鲜度硬承诺 + 回补独立窗口/独立预算/独立退出码)
- 改哪个环节(schedule 层 + 入口层):
  1. `run_fof_nav_collect.sh` 加 `--phase recent|backfill|both`,`collect_fof_nav.py` 按 phase 只跑一遍(`recent` = 现 pass A;`backfill` = 现 pass B,单遍模式);
  2. `trade-fof-nav-collect`(21:10)只跑 recent,应用预算 200s(实测 176s + 24s 余量),`run_to 480`,`TimeoutStartSec=600`;pass A 截断 → rc=1(真失败,告警沿用);
  3. 新增 `trade-fof-nav-backfill`(21:20),应用预算 600s,`run_to 600`,`TimeoutStartSec=900`(硬上限 21:35,离 22:00 public-fund-full 留 25 分钟);backfill 到预算就 break、rc=0,记 `backfill_not_attempted`;
  4. 锁策略:backfill 撞 `public_fund.lock`(nonblock)时 **exit 3**,不许 return 0(防"锁被占=假绿")。
- 可观测预期(X→Y):
  - 21:10 `systemctl show -p ExecMainStatus trade-fof-nav-collect` **1 → 0**;该轮耗时 **292s → ~180s**;
  - 21:20 回补单元日志出现 `回补 500/500`(600s 预算 / 0.46-0.98s 每只 → 230-490s 可覆盖全批),`backfill_not_attempted` **~200 → 0**;
  - `unit_exit=1` 告警每晚 **1 次 → 0 次**;回补滞后(>7 交易日未推进)改由独立判据告警。
- 证据用例(可独立复现):
  1. 次日 21:16 执行 `systemctl show -p ExecMainStatus -p Result trade-fof-nav-collect.service` → `0/success`;
  2. `journalctl -u trade-fof-nav-backfill --since today` 含完整完成行且 `systemctl show -p ExecMainStatus` = 0;
  3. `data/public_fund.fof-nav-progress.json` 中 `work_limits` 条数 ≥1000(两轮后),`backfill_pending` 计数为 0;
  4. 判别力:本地/测试环境打桩 `fetch_lsjz` 慢到超 200s → recent 单元必须 rc=1 且 failed(证明不是"关告警")。
- 风险:
  - 22:00 `trade-public-fund-full` 持 `public_fund.lock` 到 23:17(11-16 实测 22:00→23:17,CPU 6m37s);回补单元若越 22:00 会把它挤成"锁被占跳过" ⇒ 必须硬上限 900s(21:20→21:35);
  - 21:15 `trade-ab-direction-anchor`(600s)+ 21:20 `trade-futures-backfill` 同窗口(不同库,冲突面小但需确认);
  - 新增 unit/时点要过 L55/L54 四副本同步(代码脚本、`docs/deploy/systemd-units-20260912.md`、`docs/deploy/systemd-units-cloud-snapshot.txt`、云上 unit + `docs/ops/architecture/01-services-and-schedules.md`);
  - 两个单元共享 DB 锁,任何超时都要靠"退出码可见"而不是"skip 静默"。
- §14 冲突:21:10 turnover-backfill(同刻,不同库)、21:15 ab-anchor、21:20 futures、22:00 public-fund-full;不推 main、不写 D1。

### 方案 B:单单元「硬承诺/软承诺 + 回补优先队列 + 告警挂交付指标」(不新增 unit、不挪时点、不加预算)
- 改哪个环节(collect() 相位循环 + 游标选择 + evidence/监控判据):
  1. **硬承诺**:pass A 保留 `raise TimeoutError`(新鲜度没跑完就是失败,rc=1);
  2. **软承诺**:pass B 到 deadline 改为 `break`(正常收尾),`stats['backfill_not_attempted']=N`,**不置 terminal_error** → rc=0;
  3. **回补优先队列**:`work_limits` 增 `backfill_pending/backfill_last_attempt`;下一轮 pending = 「backfill_pending 的基金(按滞后天数降序)」+「code 游标补齐到 500」;pass B 成功尝试即清标记。解决"截断要等 4 天"的续跑缺口;
  4. **evidence/监控**:`index/fof-nav.json` 增 `backfill_not_attempted`;`reason` 用 `backfill_truncated`(不是 TimeoutError);ops_monitor 的新鲜度判据改为「最近交易日覆盖率 + 某基金回补滞后 >7 交易日 → warning」,`unit_exit` 告警只留给真失败(pass A 截断/整批失败/锁占)。
- 可观测预期(X→Y):
  - 次日 21:10 `ExecMainStatus` **1 → 0**;`index/fof-nav.json` `stage_status` **failure → success**,counts 出现 `backfill_not_attempted≈200`;
  - 下一轮日志 pending 列表前 ~200 位 = 本轮被截断的代码(可从 progress `backfill_pending` 对账);
  - 每晚 `unit_exit=1` 告警 **1 → 0**;回补滞后告警从「无」→「按阈值出现」(不是关告警,是换挂点);
  - 单只回补周期 4 交易日 → 被截断部分次日即可补。
- 证据用例:
  1. 改现有单测 `scripts/tests/test_fof_nav_budget_fix_20261113.py` 用例 3/4:pass B 到 deadline ⇒ 不抛、`backfill_not_attempted>0`、rc=0;pass A 到 deadline ⇒ 仍抛、rc=1;
  2. 生产次日:`journalctl` 见 `完成 ... 回补截断=N`,evidence `stage_status=success`,progress 里 `backfill_pending` 数 = N;
  3. 判别力:打桩 pass A 变慢 ⇒ rc=1 + unit failed 仍出现;打桩全批合法空 ⇒ rc=0 但 `legal_empty` 计数可查。
- 风险:
  - **rc 语义是已上线行为**(§23.7 冻结契约),必须用户拍板;且必须同批改 evidence/监控,否则 ops_monitor 仍按 `collection_status=failure` 报警(`ops_business_evidence.py:246` 起);
  - 软截断若无滞后看门狗,就是变相关告警 ⇒ 滞后判据是本方案的硬配套,不可省;
  - 优先队列可能让 code 游标尾部长期饿死 ⇒ 每轮保证游标至少推进 N 只(如 100)。
- §14 冲突:不动时点,零新增窗口;风险最低。

### 推荐
B 是"最小结构修"(不动时点、不加预算、消假失败 + 补上续跑缺口),A 是"产能根治"(回补预算 114s→600s、截断归零),但引入新时点与四副本同步成本。**终极合集 = A 的拆分 + B 的硬软承诺/优先队列/滞后看门狗**:21:10 单元只承诺新鲜度(硬),21:20 单元专做回补(独立预算,截断 rc=0 + 滞后告警)。

## 8. 已验证方法 / 数据源清单(便于复核)
1. 云上 `systemctl list-timers --all` / `systemctl cat` / `systemctl show -p Result/ExecMainStatus/TimeoutStartUSec`(只读)。
2. `journalctl -u trade-fof-nav-collect.service --since 2026-11-14`(拿到 11-16 全段逐行进度 + traceback)。
3. 云上业务日志 `data/logs/fof_nav_collect_2026110X_2110.log`(11-09/10 基线 rc=0 162s/174s;11-11/12/13 rc=1)。
4. `data/public_fund.fof-nav-progress.json`(last_code=006862;work_limits 500 条,phase gap295/history205;无 recent_through)。
5. `data/ops_delivery/index/fof-nav.json`(failure/TimeoutError/counts)。
6. `data/public_fund.db` 只读 SQL:池 1822;批次 max(date) 484@11-13;11-13 全池 1262 行;11-16 仅 15 行;`fund_collection_state` 1310 条、history 完成(≤19900101)0 条;冲突表最新 observed_at 2026-11-14。
7. `data/alerts/alert_ledger.jsonl` + `latest.md`(11-16 21:15:28 unit_exit=1;11-14 恢复;check_failed_units 21:15:10)。
8. 站点数据 `static-site/data/nav_bucket/b7.json`(026929 最新日 11-03)。
9. 上游 API 实测:`pageSize=50` 被强制 `PageSize=20`(单次只读 GET,`fundCode=000001`)。
10. 代码实文:`scripts/collect_fof_nav.py`、`scripts/run_fof_nav_collect.sh`、`scripts/ops_fund_evidence.py`、`scripts/ops_business_evidence.py`、`app/collector/public_fund_gap.py`、`scripts/export_fund_nav.py`;git log(方案 C = `571d5c13e` 11-13 23:22,上云 mtime 11-14 14:25,11-14/15 周末跳过 ⇒ 11-16 为首个交易日)。
11. 顺带发现:11-13 RCA 引用的依据文件 `/tmp/fof-budget-rca-20261113.md` 云上已不存在、仓库无落档(依据链断),建议本次 RCA 落 `docs/ops/`。

## 9. 残留声明
- 全程只读:云上未 restart / 未 reset-failed / 未改 unit/timer / 未写 DB/R2 / 未跑生产补数脚本;DB 仅 SELECT。
- 未发任何通知(本轮调研没触发邮件/飞书);未 push/merge;未写 `~/.claude/`。
- 无残留后台任务。
