# #181 R2 skip SEVERE 降噪(①d)独立审查报告

- 审查人: reviewer agent(fresh context,独立于实施 agent)
- 日期: 2026-10-07
- 审查对象: 分支 `feat/181-fetchnews-denoise-20261007` @ `2c1fe11801e24137fb8adc1030eae0618b9fe760`(base `d8087f67d`)
- 被审核心: `scripts/schedule_monitor.sh` r2_skip 状态机(①d 三改);配套新增回归测试 + fixture + 实施报告
- 审查判定: **PASS(10/10),merge 资格成立**(3 条低分附注,均非阻断)

## 0. 声明与偏差

1. **未出现 `moved to the background (ID:`** —— 本次审查全程无后台化任务;所有命令均在工具级 timeout 内前台完成。
2. macOS 无 coreutils `timeout` 命令(实测 `command not found`)⇒ 改用 Bash 工具自带 `timeout` 参数实施同一硬约束(偏差记录)。所有命令实际均秒级返回。
3. **未真跑 `scripts/schedule_monitor.sh`**(禁,§18 L48):所有验证 = 静态读码 + AST 提取纯逻辑块 exec + 自建驱动;未 source/exec 业务脚本主体(§18 L50 探针 static-only)。
4. **未 checkout 分支到主工作树**(memory `non-isolated-agent-switches-main-branch`):一律 `git show <ref>:<file>` 导出到 /tmp 只读审。
5. 反事实数字全部为**自建独立提取器/驱动器复算**(/tmp/rev181-replay.py、/tmp/rev181-edge.py,均不落 repo),不引用实施方脚本;样本 fixture 与生产日志做了 ground truth 对账(见 ③/⑤)。
6. 本报告落档后未 commit(reviewer 只读不改业务;报告文件交给主控处置)。

## 1. 十项必审结论

| # | 项目 | 结论 | 一句话证据 |
|---|---|---|---|
| ① | 改动面独立复算(夹带?) | **PASS** | 恰 3 hunk/79+/58−,单文件;新增文件全为报告+测试+fixture,无夹带 |
| ② | ①d 三件真落地与语义精确 | **PASS** | 轮去重/去假清零/seen 补全逐字核;else 清零分支语义原样保留(+1 行清理) |
| ③ | 反事实数字独立复算 | **PASS** | OLD 13 封 13 恢复与生产日志 ground truth 93/93 逐 tick 全等;NEW 5 封逐位与报告一致 |
| ④ | 负控(真缺口仍告警/同轮重复不告警) | **PASS** | 自建 6 用例:真持续缺口仍 fire=1;同轮×5 tick fire=0;滞留 20 tick 无假恢复 |
| ⑤ | 测试真伪(变异/fixture/CI/_MIN_ASSERTIONS) | **PASS** | 4 组变异全响(M1 5F/M2 12F/M3 11F/M4 12F);main 树 8F 证明真读 .sh;CI 收集路径相交 |
| ⑥ | 零真实外发自证可信度 | **PASS** | 块静态无 I/O;哨兵 monkeypatch 三通道,M4 注入生效时必红(已验证) |
| ⑦ | §23.2 同类错误面清单 | **PASS** | 6 条逐条独立核实;#2 marker_buffer 确为同模式但越授权面(另立任务判对) |
| ⑧ | 回归面(兄弟任务/回滚/state 迁移) | **PASS** | 常量未变;feeder 边界不可达;last_round 对旧码回滚无害;恢复循环未改;全量 357p/2s |
| ⑨ | git 纪律 | **PASS** | 单 commit/线性/远端 ref==tip/reflog 无 force/trailer 在/无大文件 |
| ⑩ | 可逆性 | **PASS** | 分支树 index 上反向 apply 干跑 OK;bash -n / ast.parse OK |

## 2. 证据明细

### ① 改动面独立复算 PASS

- `git diff main...feat --stat`: 4 files changed, 959 insertions(+), 58 deletions(-)。`scripts/schedule_monitor.sh` = 79+/58−(137 变更行);实施报告自报「3 处 79+/58−、单文件」**精确**。
- hunk 头恰 3 个:`@@ -558,7 +558,9 @@`(常量区注释)、`@@ -919,21 +921,28 @@`、`@@ -942,62 +951,74 @@`(状态机)。上界 +1024 ⇒ 恢复循环区间(分支版 L1665 起)不在任何 hunk 内。
- 新增文件 3 个:`scripts/tests/test_181_fetchnews_denoise_20261007.py`(332 行,git 内)、`scripts/tests/fixtures/181/ticks.csv`(372 数据行+1 注释,14590 B)、`docs/ops/181-fetchnews-denoise-impl-20261007.md`(174 行)。实施报告 §2/§3/§11 已列明。
- 无夹带:无恢复循环/gen_schedule_stats/前端/版本串/根 data/ 任何改动。

### ② ①d 三件语义精确 PASS(分支版行号)

- **① 轮去重** L957-962:`_r2_same_round = bool(_r2_lr) and _r2_lr == _r2_prev.get("last_round")`;仅 `_r2_fresh and not _r2_same_round`(L959)才 `_r2_n += 1` + 写 `last_round`(L961)。同轮多 tick 不再假 +1。
- **② 去假清零** L1001-1004:滞留 tick 走 `[r2-skip-stale] … 保链不计数`,不再清零;count 落库 L963-966。旧码 stale 清零(base 版 L949-955 `_r2_stale_prev["skip_rounds"] = 0`)在新版**已不存在**(测试 L158-159 有字面守卫 `'_r2_stale_prev["skip_rounds"] = 0' not in block`)。
- **③ seen 补全** L972-973:`seen_keys_this_run.add(_r2_alert_key)` 位于 `_r2_n >= THRESHOLD` 分支内、在 fire/suppress 判定**之前** ⇒ 任何达阈值 skip tick(新轮/同轮重复/滞留)都 mark。对照旧码(base L972):旧码仅「新鲜且 n>=3」tick mark,滞留 tick 不 mark ⇒ 这才是假恢复之门。
- **else 清零分支原样保留** L1013-1022:清零动作(`skip_rounds=0` L1020)+ 打印(L1022)与旧码(base L994-1001)逐字相同,**唯一新增** L1021 `last_round = None`(防跨清零轮残留轮标识,必要清理)。「唯一合法清零点/真恢复入口」语义未变。
- 阈值常量未动:分支 L556 `R2_SKIP_CONTINUOUS_THRESHOLD = 3`、L566 `R2_SKIP_OBS_WINDOW = timedelta(minutes=30)`;测试 `test_constants_unchanged`(测试 L146-150)钉死。
- 语义边界 3 条精核:
  - 同轮重复边界:判定用 stats `last_run` 分钟串相等(非时间差),`bool(_r2_lr)` 防空串误判 ✅
  - `_r2_fresh=True` 兜底(解析失败/缺失当新鲜):保守方向正确(宁多告警不吞真告警)✅
  - 「空 last_run + skip>0」理论过度计数边界 ⇒ 现实不可达(见 ⑧ 与附注 F3)✅

### ③ 反事实数字独立复算 PASS

方法:自建提取器(独立于测试的提取器实现:AST 从 `.sh` heredoc 取 r2_skip 真块 2 语句 + 常量 `exec`)+ 逐 tick 驱动 + 模拟恢复循环;样本 = `/tmp/181-ticks.fixture.csv`(与分支 `scripts/tests/fixtures/181/ticks.csv` **md5 全等** `8636a830560b015642c474b0d1d62cbe`,14590 B)。

- **OLD(base blob 复跑)**:fires = **13** @ [10-04 03:30, 04:30, 06:30, 07:30, 18:30, 19:30, 21:30, 22:30, 23:30, 10-05 00:30, 03:30, 13:30, 18:30];recoveries = **13** @ [同为上述 +15min 时点];打印 skip 43 / stale 20 / clear 4(共 67)。
- **OLD vs 生产日志 ground truth**:对云上导出 monitor 日志(181-monitor-full.log,09-13→10-07)独立分类提取的真实事件 = 13 SEVERE + 13 恢复 + 67 打印,**逐 tick 全等(93/93 零差集)** ⇒ ①fixture 为真实生产样本非人工构造(§18 L49)②实施报告「93/93 MATCH」声明可信。
- **NEW(分支 blob 复跑)**:fires = **5** @ [10-04 04:00, 07:00, 18:15, 10-05 04:00, 18:15];recoveries = **5** @ [10-04 05:00, 08:00, 10-05 01:15, 04:15, 19:00];打印 skip 18 / dup 20 / clear 11(共 49)。
- 与实施报告声明**逐位一致**(13→5、恢复 5、每封「连续 3 轮」= 3 个 distinct last_round,如 10-04 04:00 封的链 02:45/03:01/03:45)。NEW 每封间隔均 >2h,无重报循环残留(测试 L213-216 同口径断言)。

### ④ 负控 PASS(自建 /tmp/rev181-edge.py,6 用例,全部符合预期)

| 用例 | 期望 | 实测 |
|---|---|---|
| (a) 真持续缺口,每轮新轮+skip ×10 | 仍告警(fire=1,第 3 轮首报) | fires=1 ✅(memory `alert-denoise-keep-fault-discriminator`:降噪未豁免真故障判别维度) |
| (b) 同轮(last_run 不变)重复 tick ×5 | fire=0,count 停 1 | fires=0, cnt=1 ✅ |
| (c) fire 后长滞留 20 tick(last_run 冻结) | fire=1、无假恢复、count 停 3 | fires=1, recoveries=0, cnt=3 ✅ |
| (d) 停摆后恢复(无 skip) | fire=1 + 真恢复=1 | fires=1, recoveries=1 ✅ |
| (e) 链 2 + 停摆 + 新轮 skip:NEW vs OLD 对照 | NEW fire=1;OLD fire=0(假阴性) | NEW=1 / OLD=0 ✅(证明 ①d 修复「真重复 skip 被 stale 清零吞掉」) |
| (f) 空 last_run + skip ×3 | (残余边界演示) | 3 tick 即 fire ⇒ 见附注 F3 |

### ⑤ 测试真伪 PASS

- 分支树(as-committed):`scripts/tests/test_181_fetchnews_denoise_20261007.py` **14 passed**;同一测试在 **main 树 8 failed** ⇒ 测试真读 `scripts/schedule_monitor.sh`(非恒真/非副本)。
- 变异实验(改真源码块判据,测试必须变红):
  - M1 去掉轮去重(还原旧语义)→ **5 failed**
  - M2 阈值 3→5 → **12 failed**
  - M3 摘除 seen 补全 → **11 failed**
  - M4 注入 `subprocess.run` 到块内 `_r2_fresh = True` 前 → **12 failed**(含 `test_zero_real_outbound` 与 `test_min_assertions_guard`)
  - 注:M4 第一次注入在提取锚点(`_r2_skip_cnt = …`)之前 → 未生效(14 passed),后修正注入点。该现象=附注 F2(锚点前语句不被覆盖,但插入中断会让 fires=0 响亮 FAIL,非静默通过)。
- fixture 真实性:与生产日志 ground truth 93/93 对账(见 ③)✅
- CI 收集路径:`.github/workflows/ci.yml` L109-112 `python3 -m pytest -q scripts/tests/`(FAIL 阻断)与文件实际目录 `scripts/tests/` 相交 ⇒ 该测试**会被 CI 收集**(memory `gate-mount-decision-ci-only` 判法)✅
- 防假绿守卫:`_MIN_ASSERTIONS = 30`(测试 L49-50)+ `test_min_assertions_guard`(L330-333)末位校验断言下限;M4 时该守卫红 ✅
- 全量回归(分支 worktree,`PYTHONDONTWRITEBYTECODE=1 -p no:cacheprovider`):`scripts/tests/` **357 passed / 2 skipped**(9.98s,复跑两次一致;worktree 无缓存/残留)。兄弟静态测试(用真 monitor 文件的 test_228 + test_monitor_resource_inprogress)46 passed/1 skipped。

### ⑥ 零真实外发自证 PASS

- 提取块静态审读(L941-1022):只 append 到 `alerts` list、读写 `alert_state` dict、print;无 subprocess/urllib/socket/文件写 ⇒ 结构上无外发出口。
- 哨兵:`test_zero_real_outbound`(测试 L310-325)monkeypatch `subprocess.run` / `urllib.request.urlopen` / `socket.create_connection` 为「一调用即 AssertionError」并计数;M4 变异注射生效时该测试红 ⇒ 哨兵具备检出真外发能力 ✅。
- 我的审查全程未跑 `schedule_monitor.sh` 本体;我的驱动=提取块 exec(纯逻辑)+ 本地模拟恢复循环,零外发 ✅。

### ⑦ §23.2 同类错误面清单 PASS(逐条独立核实)

| 实施报告列项 | 我的独立结论 |
|---|---|
| #2 marker_buffer(pending 态每 tick +1 / degrade marker 轮窗口内跨 tick 重计) | **确为同模式**(「跨 tick 重复计数」同病),但不在 #181 授权面(用户拍板只做 ①d)⇒「另立任务」**判对**。附注:其假恢复被既有 dedup_key seen 挡住,与 r2_skip「假话+假恢复+1h 重报」三症不完全同病 |
| #3 missed\| 漏跑(date+slot key) | 非同病:key 含日期+slot,TOLERANCE 30min 每 slot≤2 查,判定已 epoch 归一 ✅ |
| #4 extra_stale(EXTRA 停摆) | 非同病:单次性告警,无跨 tick 计数 ✅ |
| #5 _ri_key(in_progress 滞留) | 非同病:已有 seen 处理 ✅ |
| #6 exit!=0 | 非同病:stale 保 active、无计数链 ✅ |
| 结论 | 清单 5 非同类 + 1 真同类但越权面,**判对**;另立任务方向正确 ✅ |

### ⑧ 回归面 PASS

- **兄弟任务**:该块对 stats 全任务生效,但行为改动仅在 `r2_skip_count>0` 场景;生产数据上仅 fetch_news 触发过(overfit_monitor/intraday_snapshot 计数 0,见 `docs/ops/all-alerts-sweep-20261003.md`)✅。
- **回滚无害性**:alert_state.json 无 schema 校验(json.load/dumps);旧代码忽略 `last_round` 字段 ⇒ 若回滚版本,多余字段不解析不报错,**无需 state 迁移** ✅。
- **feeder 边界**(`scripts/gen_schedule_stats.py`,未改):EXTRA 路径 log 不存在 ⇒ `skip_count=0`(scan_marker_log 返回 `(None, 0, …)`);TASKS 路径 `last_run` 与窗口同源 ⇒ 「空 last_run + r2_skip_count>0」组合**现实不可达** ⇒ `_r2_fresh=True` 兜底不会造成实际每 tick 无脑 +1(残余理论边界见 F3)✅。
- **恢复循环**(base L1644 / 分支 L1665 起)不在任何 hunk 内,未改 ✅;新 seen 补全与恢复循环的「active 且未 seen ⇒ 判消失」协同正确(负控 c/d 实证)✅。
- 常量未变、CI 全量绿(357p/2s),前端不可见(纯后端监控脚本,无 §24 面、无 §21 公示对象、无 §22 数据产物一致性面)✅。

### ⑨ git 纪律 PASS

- 单 commit:`git rev-list --count d8087f67d..feat` = **1**;tip = `2c1fe11801e24137fb8adc1030eae0618b9fe760`
- 线性:`git merge-base feat main` = `d8087f67d`(=base)。注:main 此后前进 2 个 **docs-only** commit(`53808e940`/`26ad2ccad`,#181 记账类),无代码冲突面;main-merge 时若报 non-ff 走标准 rebase 流程即可。
- 远端 ref == tip:`git ls-remote origin refs/heads/feat/181-fetchnews-denoise-20261007` = `2c1fe1180…` ✅
- reflog 干净:`Created from origin/main → renamed refs/heads/worktree-… → 1 commit`,无 force/重写 ✅
- trailer:`Co-Authored-By: Claude Code <noreply@anthropic.com>` 在 ✅
- 无大文件(fixture 14590 B)、无根 `data/` 夹带 ✅

### ⑩ 可逆性 PASS

- `git revert 2c1fe1180` 等价干跑:临时 index(`GIT_INDEX_FILE=/tmp/…`)`read-tree 2c1fe1180` + `git apply -R --check --cached <d8087f67d..2c1fe1180 full patch>` ⇒ **REVERT_APPLY_CHECK_OK**(含新增文件删除 + 状态机回退,全 patch 1076 行)✅
- `bash -n scripts/schedule_monitor.sh` OK;heredoc python 段 `ast.parse` OK(2779 行)✅
- 回退无 state 迁移需求(⑧ 已述)✅

## 3. 低分附注(非阻断,不影响 merge)

- **F1(≈50 分)**:`docs/ops/scripts/verify_r2skip_fix.py`(2026-09-24 历史验证脚本)按**旧语义**建模,merge 后语义过时(不属本次改动面)。建议后续订正或加过期标注。
- **F2(≈60 分)**:测试提取锚点 = `_r2_skip_cnt` 赋值语句起;锚点**之前**的语句不在执行块内,未来若在此插入语句不会被测试覆盖——但插入中断会致 fires=0 响亮 FAIL,非静默通过。可选加固:提取外层 For 迭代体全量。
- **F3(≈40 分)**:「`last_run` 空串 + `r2_skip_count>0`」时每 tick 无脑 +1(自建用例 f:3 tick 即误报「连续 3 轮」)。现实不可达(⑧ feeder 边界),但若未来 feeder 改版引入该组合,需补「空 last_run 不计」守卫。

## 4. 上线后观测点(本地禁真跑,替代 smoke)

本改动为后端监控脚本,**不可能本地真跑**(真有外发链路,§18 L48 禁)。merge 后替代验证:
1. 云上下一 tick monitor 日志:**fetch_news 再遇 skip 轮时出现 `[r2-skip-dup] …不重复计数` / `[r2-skip-stale] …保链不计数` 新打印**(旧版无这两种 tag)。
2. 对照 merge 前 10-04/10-05 的「13 封、每小时重报」日志:新行为下同量级事件应显著少发且无 1h 重报循环。
3. 数据层 smoke(C21/C22):`curl -s https://ss.fx8.store/data/schedule_stats.json` 仍 len==9 且无 last_exit ∈ {143,133,1}。
4. §0 上线三查:main 链含 merge commit + 云上仓库 pull 后脚本本体更新(unit 文件不含脚本内容,monitor unit 无需动)。

## 5. merge 资格结论

**全部 10 项必审 PASS(0 FAIL)**;3 条低分附注均非阻断(2 条属历史脚本/测试提取边界,1 条属现实中不可达的理论残余)。分支出处单 commit、可干净 revert、CI 全量绿、反事实数字与生产 ground truth 93/93 全等。

**⇒ merge 资格成立。**
