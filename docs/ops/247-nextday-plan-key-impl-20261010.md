# #247 nextday_plan py/sh dedup key 统一 —— 实施报告(2026-10-10)

> 任务来源:#245 批2 独立审查 §四「决策项 10」(报告 `docs/ops/245-batch2-impl-review-20261010.md:72-84`),
> 用户 2026-10-10 拍板「修吧」(§23.7 已发布告警行为改动授权在案)。
> 分支 `feat/247-nextday-plan-key`;base commit `bf569377f`(origin/main)。

## 一、结论摘要

py `_severe_alert` 的 dedup key 由 `nextday_plan_gen_fail` 统一为包装层同键 **`nextday_plan_fail`**
(方向 = py 改到 sh,同 #245 批2 B4-3 `nextday_gap_check` 先例)。修复后同一事件(py 先发 → 包装层 RC!=0)
只发一封;py 未发(崩溃/超时/被杀)时包装层同键窗内无已发记录 ⇒ **照发兜底**,兜底性不依赖「不同 key」。

- 改动文件(3):`scripts/nextday_plan_generator.py`、`scripts/nextday_plan.sh`、`scripts/tests/test_247_nextday_plan_key_20261010.py`(新增)。
- 测试:新增 8 用例;**红先验 4 failed / 4 passed**(对 main 版两文件);分支 **8 passed**;全量 **735 passed / 2 skipped**(基线 727/2,增量 = 本文件 8)。
- 版本注记**不发**(告警键统一,非 AI 推荐/回测口径,§5.4⑥ 不触发版本升级);**前端零改动**;不触 9 源键集。

## 二、病灶(逐环可复现)

nextday_plan 链路在 **R2 上传失败/超时/异常**、**数据未就绪(缺当日收盘价)**、**主流程未捕获异常** 时:

1. py 侧 `scripts/nextday_plan_generator.py:_severe_alert` 发 `--severe`(`--dedup-key nextday_plan_gen_fail`,
   窗 3600)后 `return 1` / `return 2` / `sys.exit(2)`(调用点:L104-122 helper 定义、L1185-1228 R2 三段、
   L1044-1053 stale gate、L1287-1293 顶层异常兜底)。
2. sh 侧 `scripts/nextday_plan.sh` RC!=0 → 无条件
   `notify.py --severe --dedup-key nextday_plan_fail --dedup-window 3600`(L70-78)。
3. `notify.py` dedup **按 key 判**(`notify.py:2804 check_dedup(args.dedup_key, ...)`)⇒ 两键互不抑制
   ⇒ **同一事件秒级两封 SEVERE**:py 带明细 stderr、sh 带「次日买入计划未生成」汇总。
4. **额外失真**:R2 失败时 py 的 `return 1` 带上来的 sh 文案说「次日买入计划**未生成**」——实际本地已落盘仅
   R2 未同步;统一 key 抑制 sh 兜底句反而减少错误信息(审查报告 §四.5)。

py docstring 原自述「与 nextday_plan.sh 包装的 --severe 双保险, **dedup key 不同不互吞**」——该论证把
「重复告警」误当「双保险」,已废止重写。

## 三、改法(含「方向依据」——为何 py 改到 sh)

**方向 = py → sh 的键**,依据三条(B4-3「当时的统一逻辑」):

1. **B4-3 先例**:`#245` 批2 commit `5a92e6f81` 把 `nextday_gap_check.py` 的 `nextday_gap_check_gen_fail`
   改为 sh 侧的 `nextday_gap_check_fail`(**py 改到 sh**),sh 侧键未动,仅改文案。
2. **下游引用锚点**:`schedule_monitor.sh:727-728`(R3 抑制注释)、`docs/ops/alert-denoise-design-20261001.md:67-71`
   等下游均引用 **`nextday_plan_fail`**(sh/包装层键);`nextday_plan_gen_fail` 仅出现在 py 自身与历史文档,
   **无任何下游代码消费** ⇒ 统一到 sh 键使下游零改动。
3. **审查报告建议(a)**:`245-batch2-impl-review-20261010.md:84`「py key 改 `nextday_plan_fail` 或 sh 侧同键」。

### 改动明细

- `scripts/nextday_plan_generator.py`
  - L121:`"--dedup-key", "nextday_plan_gen_fail"` → `"nextday_plan_fail"`。
  - L104-116 `_severe_alert` docstring:删「不同 key 不互吞=双保险」过时论证,写新语义(先发者占窗、
    带明细的 py 侧优先、包装层同键窗内被抑制、py 未发时包装层照发兜底;兜底性不依赖不同 key)。
  - L1264-1269(notify 失败分支)注释:**明确 py 此处不调 `_severe_alert`** ⇒ 包装层同键窗内无已发记录
    ⇒ 不被抑制,照发(该失败面「计划已生成仅通知未送达」仍由包装层兜底)。
- `scripts/nextday_plan.sh`
  - L74 告警正文:对齐 B4-3 风格加「本条为包装层兜底(py 同 dedup key: py 已发时本条被抑制; py 未发时本条兜底;
    若仅 R2 未同步而本地已落盘, 明细以 py 侧为准)」。`--dedup-key nextday_plan_fail`(L77)**本就正确,一字未改**。
- `scripts/tests/test_247_nextday_plan_key_20261010.py`(新增,8 用例)。

## 四、测试证据

| 项 | 命令 | 结果 |
|---|---|---|
| 分支侧 | `python3 -m pytest -q scripts/tests/test_247_nextday_plan_key_20261010.py` | **8 passed** |
| **红先验**(main 版两文件) | `NEXTDAY_PLAN_GEN_PY=/tmp/red247/scripts/nextday_plan_generator.py NEXTDAY_PLAN_SH=/tmp/red247/scripts/nextday_plan.sh python3 -m pytest -q scripts/tests/test_247_nextday_plan_key_20261010.py` | **4 failed / 4 passed**(FAILED = `test_01_py_sh_key_parity` / `test_02_r2_fail_only_one_mail` / `test_04_mutual_suppress_sh_then_py` / `test_07_text_alignment_static`) |
| 全量 | `python3 -m pytest -q scripts/tests/` | **735 passed, 2 skipped**(92.4s;基线 727/2) |

覆盖(与验收口径 1:1):
- ① 静态机检:py `_severe_alert` 键 == sh `--dedup-key` == `nextday_plan_fail`(红先验核心,main 上 FAIL)。
- ② R2 失败:py 先发(带明细)→ sh 同键被抑制 ⇒ **只一封**(main 上因两键不同 **双发** → FAIL,证明断言有判别力)。
- ③ py 未发(崩溃/超时)→ sh 照发兜底(不断层)。
- ④ 统一键窗口内互抑制(先 sh 后 py 方向亦抑制;main 上 FAIL)。
- ⑤ 窗口过期后可再发(去重非永久)。
- ⑥ **反向负控**:键分歧(回归)→ 两键互不吞 ⇒ 双发 —— 证明 ②③ 非空洞。
- ⑦ 文案/文档静态:sh 段含新语义;py docstring 含「统一为 nextday_plan_fail」+「已废止」。
- 断言下限护栏 `_MIN_ASSERTIONS=18`(防假绿,§18 L49)。

**红先验命令(可重跑)**:
```bash
mkdir -p /tmp/red247/scripts
git show main:scripts/nextday_plan_generator.py > /tmp/red247/scripts/nextday_plan_generator.py
git show main:scripts/nextday_plan.sh            > /tmp/red247/scripts/nextday_plan.sh
NEXTDAY_PLAN_GEN_PY=/tmp/red247/scripts/nextday_plan_generator.py \
NEXTDAY_PLAN_SH=/tmp/red247/scripts/nextday_plan.sh \
  python3 -m pytest -q scripts/tests/test_247_nextday_plan_key_20261010.py   # 4 failed, 4 passed
```

## 五、同类排查(§23.3 举一反三)——全仓 py/sh dedup key 逐对核对

方法:枚举全部 `scripts/*.sh` 的 `--dedup-key` 字面量 与 全部 `scripts/*.py` 的自身 severe/notify key,
按「py 模块 ↔ 其包装 sh」配对,判据 = **同一失败事件** 是否走两通道、两通道 key 是否不同。

| py 模块 | py 自身告警 key | 包装 sh | sh dedup key | 同一事件? | 判定 |
|---|---|---|---|---|---|
| `nextday_plan_generator.py` | `nextday_plan_gen_fail`(修前) | `nextday_plan.sh` | `nextday_plan_fail` | **是**(R2失败/数据未就绪/异常 → py 发 + exit 非0 → sh 发) | **本任务目标 → 已统一为 `nextday_plan_fail`** |
| `nextday_gap_check.py` | `nextday_gap_check_fail` | `nextday_gap_check.sh` | `nextday_gap_check_fail` | 是 | **已由 #245 批2 B4-3 统一,无需改**(本任务核:两键现一致) |
| `signal_kelly_backtest.py` | `signal_kelly_frozen_missing` / `_small` | `kelly_intraday_rerun.sh` | `kelly_intraday_rerun_fail` / `kelly_intraday_verify_fail` / `kelly_intraday_upload_r2_fail` | **否** — 冻结表缺失(历史信号)是数据完整性告警,不驱动 rerun 的退出码(5/142/3);包装 key 对应的是「rerun 退出码/对账/R2 上传」另一失败面 | 非同类,不改 |
| `gen_daily_brief.py` | (无自身 severe) | `run_daily_brief.sh` | `daily_brief_fail` | — py 无自身告警(仅 sh 单通道) | 非同型 |
| `check_r2_consistency.py` | (无自身 dedup key) | `check_r2_consistency.sh` | `r2_consistency_fail` | — 同上 | 非同型 |
| `detect_intraday_anomaly.py` | `anomaly_dedup_write_fail`(状态写入失败) | `intraday_snapshot.sh` | `intraday_upload_index_r2_fail` 等 | **否** — 不同失败面(状态写 vs R2 上传) | 非同类 |
| `gen_schedule_stats.py` | (无自身 dedup key) | `push_schedule_stats.sh` | `schedule_stats_r2_fail` | — py 无自身告警 | 非同型 |
| `app/collector/gold_night.py` | (无自身 severe) | `gold_night.sh` | `gold_night_collect_fail` / `gold_night_r2_upload_fail` | — 同上 | 非同型 |
| `overfit_monitor.py` | 动态 `dedup_key`(自带单通道) | `overfit_monitor.sh` | (纯 launcher,无 dedup-key) | 否 | 非同型 |
| `check_data_gap_alerts.py` | `data_gap_state_write_fail` | `check_data_gap_alerts.sh` | (纯 launcher,无 dedup-key) | 否 | 非同型 |
| `check_failed_units.py` | `FAILED_UNITS_DEDUP_KEY`(自带) | (无 sh 包装) | — | — | 非同型 |
| `check_monitor_heartbeat.py` / `detect_intraday_anomaly.py`(状态键) / `feishu_missed_fetch.py` / `sensenova-proxy-healthcheck.py` / `with_lock.py` / `agent_inbox_watcher.py` / `retry_failed_metrics.py` | 各自独立事件键(状态写入/锁超时等) | 无同名包装 sh | — | — | 非同类 |
| sh-only 通道(`deploy.sh` / `staticdata_*` / `update_lab.sh` / `turnover_backfill.sh` / `intraday_snapshot.sh` / `brief_push_wrapper.sh` / `r2_upload_skip_notify.sh` 等) | — | 自身 | 各自键 | — | 单通道,结构上无 py/sh 分歧 |

**结论:全仓同型分歧仅 `nextday_plan` 一处(本任务已修);`nextday_gap_check` 已由 B4-3 修;其余经逐对核对均非同型,不擅自扩大改动。**

### 配套面核对(举一反三,确认无缺口)

- **monitor 汇总通道**:`schedule_monitor.sh:727-741` 对 `nextday_plan` 已有 **R3 抑制**(产物今日已落盘 ⇒
  exit!=0 汇总不再复述,判据 `alert_denoise_rules.r3_nextday_product_generated_today`),**不消费 dedup key**
  ⇒ 本任务无 monitor 侧改动(B4-3 加 monitor `elif` 是因 gap_check 无产物侧判据,plan 已有)。
- **denoise 映射**:`alert_denoise_rules.category_of` 未映射 plan 任何键(返回 None=不限预算)⇒ 键改名不影响
  denoise;无需像 gap_check 那样补 `_gen_fail` 历史兼容(B4-3 的 `nextday_gap_check_gen_fail` 兼容项是 gap_check
  **在映射表内**才需要,plan 不在表内)。
- **历史告警台账**:旧 `nextday_plan_gen_fail` 记录仅存在于历史台账/文档,无代码消费。

## 六、§23.2 修 bug 三铁律自验 + 零外发声明 + 卫生披露

- **① 修完整(同类错误面清单)**:见 §五全表 —— 同根因(py 自身 severe key ≠ 包装 sh key,同一事件两通道)
  全仓逐对核对,已修 1(nextday_plan)、已存在 1(gap_check/B4-3),其余非同型。
- **② 自测完成(全覆盖)**:8 用例逐条见 §四;红先验 4 failed(核心断言在 main 必败);全量 735/2。
- **③ 排查同类(根因修不逐文件补丁)**:本修复在**根因点**(key 字面量 + 语义文档),非逐文件补丁;
  `_severe_alert` 一处 helper 统一所有调用点(R2/stale/异常三处自动同键)。
- **零外发(§18 L48 / memory `notify-script-selftest-must-stub`)**:全部用例渠道函数
  (`_send_email` / `send_telegram` / `send_feishu`)在 fixture 内打桩为「只记录、返回 True」,外层 `ZeroOutboundTrap`
  包裹最底层 `urllib.request.urlopen` / `smtplib.SMTP(_SSL)`;fixture 收尾断言 `trap.hits == []`。
  **本次自测未产生任何真实外发**(理论 + 陷阱双层保证)。
- **隔离披露(§23.2 自披露)**:新增测试全部落盘面(台账/latest.md/dedup/摘要)指向 `tmp_path`,**不碰生产 data/**。
  但**全量套件**在 worktree 内运行,既有 legacy 套件(不隔离 REPO 的薄包装,非本任务引入)把
  `worktree/data/alerts/*`(worktree **自身** data/,非主仓)写入;取证:worktree `data/alerts/alert_ledger.jsonl`
  inode 263291923(22:17 更新,= 本次跑),主仓 `trade/data/alerts/alert_ledger.jsonl` inode 263108667
  (mtime 22:10:01,**早于本次跑,非本任务产生**)。两处 inode 不同 ⇒ 本次全量跑未写主仓 data/。
- **git 无静默(§23.11)**:本分支仅本地 commit + push feat,不碰 main;无冲突/覆盖/倒退事件。
- **§23.13 口径三源核对**:方向三源(B4-3 先例 / 下游引用 / 审查报告建议)一致,无冲突源。
- **§23.4 团队协作**:开工已 scan `docs/pending-features-index.md` 本模块项 —— 同级 #243(W2,已上线)与
  #245 批2 均有本 py 改动记录;本次仅动 dedup key 字面量,与既有改动不冲突。**注**:本 worktree 副本
  (base `bf569377f`)尚无 `| 247 |` 行(主仓 worktree 有未提交的 pending-index 改动)= 主控登记中,本实施不代改台账状态。

## 七、复现/验收命令

```bash
# 1) 静态机检:py/sh 键统一
grep -n '"--dedup-key"' scripts/nextday_plan_generator.py | head -1          # → nextday_plan_fail
grep -n -- '--dedup-key'  scripts/nextday_plan.sh                            # → nextday_plan_fail
# 2) 单文件测试 + 红先验(见 §四)
python3 -m pytest -q scripts/tests/test_247_nextday_plan_key_20261010.py     # 8 passed
# 3) 全量
python3 -m pytest -q scripts/tests/                                          # 735 passed, 2 skipped
```

## 八、回报摘要(给主控)

- tip:tip-agnostic,以 `git rev-parse feat/247-nextday-plan-key` 为准(报告与 commit 同 hash 自指会循环,不写死)
- base commit:`cd0abca03`(origin/main,rebase 后)
- 改动文件:`scripts/nextday_plan_generator.py`、`scripts/nextday_plan.sh`、`scripts/tests/test_247_nextday_plan_key_20261010.py`(新增)、本报告
- 测试数字:分支 8 passed;红先验 4 failed/4 passed;全量 735 passed/2 skipped(基线 727/2)
- 同类排查结论:同型仅 nextday_plan(已修);gap_check 已 B4-3 修;其余非同型(§五全表)
- 版本注记:不发(告警键统一);前端零改动