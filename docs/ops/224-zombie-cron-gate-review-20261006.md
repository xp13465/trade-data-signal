# #224 僵尸巡检 cron 机检(纳入 job 生命周期)独立审查报告

- 日期:2026-10-06(审查窗口 23:05–23:25)
- 审查对象:`origin/feat/224-zombie-cron-gate-20261006`(tip `02780c2e6` = 报告落档;代码 `1fbd114ad`;base `24a16e6bd`,main 在其后仅多 1 个 docs commit `002a391af`,无冲突面)
- 审查者:reviewer agent(独立上下文,§15 独立审)
- 审查方式:**独立复算,不采信实施者自报**。核心手段:独立逐分钟 cron 扫描器(自写,与实施者函数对账)、真实生产样本全量对照、真故障/退化样本构造实测、独立跑全量 pytest、独立跑 CLI 四场景退出码、生产目录形态实跑、云上只读取证
- 硬约束遵守:全程只读;未改任何文件/未 commit/未 push;未碰真实 `/tmp/agent-progress-*`(进度文件查询重定向到 `/tmp/224-verify/` 空沙箱);未触发任何真实外发(未跑 notify,全量 pytest 为设计打桩的既有测试且 CI 每日同跑);未跑任何业务脚本主体

## 一句话结论

**merge 资格 PASS(零硬返修项)**。第 1 项(云上阻断回归)经双向证据核实**无回归**(改前改后云上均为 warn 不阻断);判别力经 15 组构造样本 + 独立扫描对账全部保留;报告自报数字(262/1、3 ok/0 fail、2 ok/1 warn)逐项独立复现一致。

---

## 逐项 PASS/FAIL

### 1. 云上会不会被改出阻断(最高优先)——PASS(无【严重】)

**证据链(改前 → 改后 → 运行层双向):**
- **改前代码**(`ecb5243ba` 版 L301-311,原文):`if not cron_p.exists(): return _warn(name, f"scheduled_tasks.json 不存在: {cron_p}(无 cron 可检, 跳过)")` ⇒ 文件缺失 = **warn**,`determine_exit_code` 仅 FAIL 返回 1 ⇒ 不阻断。
- **改后代码**(分支版 L455-457):同段**逐字未变**(diff 只在其后插入 `ready_at` 逻辑)⇒ 文件缺失仍 = warn。
- **云上实测取证(只读 ssh)**:`/home/ubuntu/code/trade-data-signal/.claude/` 内**无** `scheduled_tasks.json`(ls 实查,仅有 agents/plans/settings.json/skills);云上 deploy 日志两轮(`deploy_20261006_1750.log` / `deploy_20261006_2105.log` L597-606)均输出 `⚠ zombie_crons: scheduled_tasks.json 不存在: …(无 cron 可检, 跳过)` + `汇总: 2 ok / 1 warn / 0 fail` + `✓ 任务状态一致性机检通过`(rc=0,未阻断、未发告警)。
- **改后行为模拟(独立 CLI,沙箱)**:无 `.claude/scheduled_tasks.json` 的 repo 跑**分支版脚本** `--deploy-mode` ⇒ C 维度 warn,`rc=0`;`--strict` ⇒ rc=2(warn 当 fail,deploy 不传此参)。
- ⇒ 云上 deploy 阻断面**不存在新增**(行为改前改后同一:file 缺失→warn→rc=0)。本修复的实际生效面 = **有该文件的那棵树(主控本机)** deploy;C 维度在云上系 warn 空转(与实施报告 §8.4 的推断一致,本次已补取证)。

### 2. `ready_at` 推算正确性与失败方向 —— PASS

- **解析实现逐读**:5 字段;field 支持 `*` / 列表 / `a-b` / `a-b/n` / `*/n`;dom/dow 双受限取「或」语义正确;dow `0/7` 归一 ✓;分钟/小时/日/月边界与视野(400 天)符合注释。
- **独立对账**(不调用实施者 `_cron_*`,自写逐分钟扫描器):对**真实 8 个 job** 的首次触发时刻 ⇒ 独立计算与 `_progress_ready_at` 输出**逐条一致**(见 §3 表)。8 条触发时刻与各 job prompt 自述日期亦逐条吻合(10-30 19:07 / 11-01 10:03 / 10-08 21:12 / 10-08 18:07 / 10-07 21:43 / 10-08 22:08 / 22:54 / 23:13)。
- **失败方向(重点,宁可误报不可漏报)**:构造实测(沙箱,真实 job 字段集):
  - 6 字段含秒 `0 9 30 10 * *` → 解析 None → 退化 `createdAt+60min` → createdAt 3 天前 ⇒ **FAIL** ✓
  - 英文月 `9 30 * OCT *` → None → 退化 ⇒ **FAIL** ✓
  - 英文周 `30 9 * * MON` → None → 退化 ⇒ **FAIL** ✓
  - 7 字段 → None → 退化 ⇒ **FAIL** ✓
  - **无 `createdAt`** → ready_at=None → **维持现行判定 ⇒ FAIL** ✓(不静默放过)
  - detail 文案如实标注「退化按 createdAt」/「无生命周期信息,维持现行判定」✓
  - 已知边界(报告 §8.1 已如实标注):触发日在 400 天视野外的一次性 job 会退化为 createdAt+60min(误报方向偏保守,罕见)。
- **`createdAt` 单位**:真实样本全部 `>1e11`(**毫秒**,如 1791299355011,我脚本断言独立复核);函数对毫秒/秒双兼容实测(`1791299355000→1791299355.0`、`1791299355→1791299355.0`)均正确。

### 3. 真值表独立复算(真实生产样本全量)—— PASS

样本 = 审查时刻真实 `.claude/scheduled_tasks.json` 的 **全部 8 个 job**(实施报告快照为 9 job,审查时刻文件已演化:巡检 cron 已换为 ce6be4e8 / b7bf5239;我以审查时刻真实文件为准全量复算)。进度文件形态 = 重定向空目录(「事故形态:文件尚未产生」;旧模块经路径重定向,旧逻辑逐字复用 `ecb5243ba` 版):

| job id | 识别为巡检 | cron | 独立首触发(自写扫描) | 独立 ready_at | 函数 ready_at | 旧判 | 新判 |
|---|---|---|---|---|---|---|---|
| 541d860f | 否(skip) | `7 19 30 10 *` | 2026-10-30 19:07 | 20:07 | 20:07(一致) | — | — |
| 72c2bd8b | 否 | `3 10 1 11 *` | 2026-11-01 10:03 | 11:03 | 11:03(一致) | — | — |
| 7cf5422c | 否 | `12 21 8 10 *` | 2026-10-08 21:12 | 22:12 | 22:12(一致) | — | — |
| ad7f0875 | 否 | `7 18 8 10 *` | 2026-10-08 18:07 | 19:07 | 19:07(一致) | — | — |
| fe1005df | 否 | `43 21 7 10 *` | 2026-10-07 21:43 | 22:43 | 22:43(一致) | — | — |
| 94fd5b29 | 否 | `8 22 8 10 *` | 2026-10-08 22:08 | 23:08 | 23:08(一致) | — | — |
| ce6be4e8 | **是** | `9,24,39,54 * * * *` | 2026-10-06 22:54 | 23:54 | 23:54(一致) | **FAIL 文件不存在** | OK 待观察 |
| b7bf5239 | **是** | `13,28,43,58 * * * *` | 2026-10-06 23:13 | 次日 00:13 | 次日 00:13(一致) | **FAIL 文件不存在** | OK 待观察 |

- 6 个非巡检 job 正确 skip(其 prompt 无巡检字样,旧规则同样 skip)✓
- **字段自行核实**(不转述):cron 全部 5 字段;`createdAt` 全部毫秒级;`recurring` 键 = 3 个有 / 5 个无;**反例成立**:`fe1005df` 是 `recurring: True` 但 prompt 语义明写「一次性」(2026-10-07 21:43),另有 5 个一次性 job **无该键**(非 false)⇒ 实施者「判据不用 `recurring` 字段」的理由独立成立。
- 现状形态(真实 `/tmp`,只读):分支版输出 `✓ 巡检 cron 检测 OK(2 个巡检 cron 进度文件均存在且新鲜)`(两文件均 23:09 新鲜)✓

### 4. 判别力没被降没 —— PASS(构造实测 15/15)

| 场景(真实 job 字段集构造) | 期望 | 实测 |
|---|---|---|
| T1 一次性 job 触发日已过(10-02)+ 文件不存在 | FAIL | **FAIL** ✓(文案「已过应产生时刻: 首次触发 2026-10-02 19:07 + 宽限」)|
| T2 巡检 cron 建于 2 天前 + 文件不存在 | FAIL | **FAIL** ✓ |
| T3 文件存在 mtime=10 天 | FAIL | **FAIL** ✓ |
| T4 巡检 cron 建于 30 天前 + 文件不存在 | FAIL | **FAIL** ✓ |
| F3 pending(10-30 触发)与真故障(建 3 天前)共存 | 整体 FAIL | **FAIL**(fail 不被 pending 稀释)✓ |
| F1 一次性触发日在将来(事故一) | OK 待观察 | **OK 待观察** ✓ |
| F2 巡检 cron 建 5min 前(事故二) | OK 待观察 | **OK 待观察** ✓ |

唯一新豁免面 = `now < 首次触发+60min` 的有限窗口;窗口过后与旧判定逐字相同。

### 5. 闸门位置与威力未动 —— PASS(独立 CLI rc 四场景)

| 场景(沙箱最小 repo,独立进程跑分支版脚本) | 实测 rc | 期望 |
|---|---|---|
| 真僵尸 job + `--deploy-mode` | **1**(FAIL 阻断,A/B 干净已输出确认) | 1 ✓ |
| 同上 + `--skip-zombie-crons` | **0**(C 维度整段不跑) | 0 ✓ |
| 无 `.claude`(云上形态)+ `--deploy-mode` | **0**(C=warn) | 0 ✓ |
| 无 `.claude` + `--strict` | **2** | 2 ✓ |

- `.github/workflows/ci.yml:107`(`--deploy-mode --skip-zombie-crons`)行号**精确核实无误**,且该文件**未被本分支触碰**(反证:diff 为空);`scripts/deploy.sh` 同(**未被触碰**,340/341/346 行原样)。
- `check_task_state.py` 全仓调用点 grep:仅 deploy.sh:340-346 + ci.yml:107-13,无其它引用面。

### 6. 测试质量 —— PASS

- **独立全量复跑**(导出树 `/tmp/224-tree` = 分支代码,md5 与 git blob 逐位一致已证):`262 passed, 1 skipped in 11.16s` —— 与自报 **262/1 完全一致**。
- **断言实质**:15 用例(我逐个数:15 个 test 函数,与自报一致)全部为「状态 == OK/WARN/FAIL + 关键内容」真断言,含 `--deploy-mode rc=1` / `--skip rc=0` 的退出码断言;无「只断言不抛异常」式空壳,无 skip 混过(2 个 skipif 仅限真实文件存在性,本机实跑覆盖)。
- **「此前无既有测试」独立证实**:`origin/main` 的 `scripts/tests/` 无任何 check_task_state/zombie 相关文件(git ls-tree 实查),grep 全目录亦无;该句**成立**,不存在削弱/删除既有断言的对象。
- 测试隔离正确:`monkeypatch PROGRESS_DIR` 到 `tmp_path`,不碰真实 /tmp ✓;真实样本对账用例(⑩)把「毫秒 createdAt / 5 字段 / recurring 键行为」写成机检断言(L49 防假样本)✓。

### 7. 两处验证口径 —— PASS(生产目录形态亲自跑,工作树跑不算数)

- **生产目录形态**(新代码 + 真实仓库树):`3 ok / 0 warn / 0 fail`,rc=0;`--deploy-mode` 同 rc=0。**与自报一致**;耗时 0.033s。
- **worktree 形态**(导出树自我定位,无 `.claude`):`2 ok / 1 warn / 0 fail`,rc=0,C=warn「scheduled_tasks.json 不存在」——与自报一致。
- 跑前/跑后 `git status --porcelain` 无变化 = **零写**;脚本无发送链路 = **零外发**。

### 8. 没动不该动的 + git 卫生 —— PASS

- 相对 main 恰好 **4 文件**:`scripts/check_task_state.py`(193+/-)| `scripts/tests/test_224_zombie_cron_gate.py`(新增 277)| `docs/pending-features-index.md`(状态列 1 行)| `docs/ops/224-zombie-cron-gate-20261006.md`(报告)。**无根 `data/` / 无 static-site/data 夹带** ✓
- 分支独有 commit = 2(`1fbd114ad`→`02780c2e6`),链式干净、无 merge commit、时间戳单调;**base `24a16e6bd` 是 main 祖先**(rebase 属实);无 force 痕迹迹象;报告与测试文件均在分支 ✓
- 分工对账:`1fbd114ad` = 代码+测试(2 文件);`02780c2e6` = 报告+pending-index 状态列(2 文件)—— 与任务描述「tip 含 1fbd114ad 代码+测试 / 02780c2e6 报告」逐字吻合 ✓

### 9. 举一反三(§23.3)超范围项核实 —— PASS

- `scripts/check_monitor_heartbeat.py:62` 描述**准确**:心跳文件不存在 ⇒ 进入告警路径(实读 L61-63 + 发送段 L77-107);**有 dedup**(`DEDUP_KEY=schedule_monitor_heartbeat`,窗口 3600s,传给 notify `--dedup-key/--dedup-window` 实读证);**非 deploy 闸门**(不在 deploy.sh 调用链,grep 无引用);首次部署冷启动窗口理论误告警一次(有 dedup 静默)。
- **判定「确实不该在本次改」成立**:①非阻断链,风险等级低;②「monitor 停摆」本身是需要大声告警的严重故障,冷启动一次误报(有 dedup)远优于为它引入豁免而增加漏报面;③实施者按 §23.7/§5.1 只报不改 + 列观察项上报,边界正确。
- 重复实现独立核实:全仓 grep `agent-progress`/`巡检兜底` —— 其它命中均为**进度文件生产方**(backfill_etf_daily/sync_dev_from_r2/backtest_alert 写自己的进度)或**其它用途**(check_file_owners 扫声明、agent_dispatch_cron_reminder 派单 hook),**僵尸判定规则确实仅本脚本一处实现**,报告 §6 准确。

### 10. 回退路径有效 —— PASS

- `git cat-file -t 1fbd114ad` / `ecb5243ba` / `02780c2e6` 三枚 hash **均真实存在**(commit)。
- `git diff 24a16e6bd ecb5243ba -- scripts/check_task_state.py` **为空** ⇒ `git checkout ecb5243ba -- scripts/check_task_state.py` 得到的正是旧判定版本(与我复算所用旧版一致,`/tmp/224-old-check_task_state.py` 即出自该 commit)。
- `git revert 1fbd114ad` 干净性:该 commit 只动 2 文件(check_task_state.py + 新增 test),`02780c2e6` 只动 docs 两文件、**未触碰**代码文件 ⇒ revert 无冲突,恢复旧判定成立 ✓

## 规范符合性(其余)

- **§21 算法公示**:不适用(纯后端机检脚本,无前端算法/公示文案改动)。
- **§22 数据一致性**:不适用(无数据产物/展示位;非数据生成链)。
- **§23.7 冻结契约**:本次为「修已上线机检的误报」,属用户拍板(#224 登记「都开」)范围的根治,判据收窄仅作用于「文件不存在」分支的时点豁免,不改其余语义 ✓
- **§23.13 口径三源**:判定语义与 pending-index 登记原文、deploy.sh 注释、UI 无涉,无三源分叉。

## 低分项(<80,已滤,仅附注防黑箱)

1. (≈25)OK 消息文案「其余进度文件存在且新鲜」在「全部 job 均为 pending」的极端情形下措辞不通(纯文案,不影响判定)。
2. (≈35)报告 §4.3「6 个一次性 job `recurring` 键根本不存在」与审查时刻真实快照(6 个一次性中 5 个无键,`fe1005df` 有键)有轻微数字差;不影响「字段不可靠」结论(反例独立复现成立),疑为 9-job 快照代差。
3. (≈25)`test_real_jobs_no_false_zombie_when_pending` 只断言「ready_at 未到不许 FAIL」,未反向断言「ready_at 已到必须 FAIL」——判别力方向已由其它用例覆盖,覆盖边界可接受。

## 附:审查证据文件(本地 /tmp,可随时复核)

- `/tmp/224-verify/out1.txt` 复算 1 全输出(真实样本对照) | `/tmp/224-verify/out2.txt` 复算 2 全输出(15/15 构造样本)
- `/tmp/224-verify/out-real-cli.txt` 生产目录形态 CLI 输出
- `/tmp/224-old-check_task_state.py`(ecb5243ba 旧版) | `/tmp/224-tree/`(分支代码导出树,md5 与 git blob 一致)
- 云上取证:两轮 deploy 日志 L597-606(只读 ssh,未写入云上任何内容)

