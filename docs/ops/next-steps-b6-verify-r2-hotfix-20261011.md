# B6 热修:verify-r2 周日 full 模式 UnboundLocalError(standalone_files)

- **日期**:2026-10-11
- **分支**:`fix/verify-r2-full-standalone`(base = `origin/main` @ `11776c31ba2677d083e16b958f4b269fc32ee529`,`base-fresh` 已校验)
- **残留后台任务**:无(唯一的后台运行 = 全量 pytest,ID `bm5b9wuxx`,已正常退出,见 §4;无 `moved to the background` 残留)
- **范围**:`scripts/upload_r2.py`(1 处根因修复 + 1 处函数签名加 `warn` 形参)+ `scripts/tests/test_verify_r2_full_standalone_20261011.py`(新增 CI 单测)。**不动其它逻辑**。

---

## 1. 病灶与根因

`upload_r2.py::cmd_verify_r2`:

```
full = today_weekday == 6          # 周日 = 全量对账
...
if full:
    to_check = files               # ← 只赋 to_check
else:
    ...
    standalone_files = [...]       # ← standalone_files 只在 else(平日)分支赋值
...
if mismatches:                     # full/平日 都会进
    _std_set = {str(f.relative_to(local_dir)) for f in standalone_files}   # ← 无条件引用 → full 模式 UnboundLocalError
```

- 引入 commit:`09338aa0f`(#188,2026-10-05,「s06 链路同步段检查侧三层盲区根治」)。
- 触发条件:**周日(weekday==6)full 全量对账** + **任一通道出现不一致/缺失**(`mismatches` 非空)。
- 生产证据:10-11(周日)02:16 / 05:11 两次实例日志末行即本条 UnboundLocalError;04:27:55 SEVERE「R2上传失败」已发(05:11 被 6h dedup 抑制)。
- **后果**:周日层3 全量对账在第一个出现不一致的通道处**中断** → 该轮**自动补传不执行** → 轻量对账(verify-channels)rc=1 → 走 deploy 的 R2_FAIL 告警链。

## 2. 修法(两种模式语义都正确,非仅消崩)

B4a 给的二选一方向中,选「**full 模式下补正确的等效逻辑**」——因为 L3730 那段在 full 模式下**本来就有正确的等效输入**:

- `standalone_files` 语义 = 「本通道中、被 `_record_standalone_keys` 登记为**独立上传链产物**的文件」(s06 / nextday_plan / daily_brief / intraday 等走 `upload-data-files`,不经 deploy 通道状态)。
- **平日**:既用于「扩对账覆盖面」(纳入 `to_check`,不受抽样上限截断),也用于 L3747「独立链产物脱节」层4 外围告警记名。
- **full(周日)**:`to_check = files` 已含全池,覆盖面天然满足;但**脱节告警记名仍需要它** —— 这正是 #188 设计初衷场景(事故原文:「直到 10-04 周日 deploy 的全量 verify-r2 才补传治愈」)。若简单补 `standalone_files = []`,则周日发现独立链产物脱节时**不再发声**(静默补传),属语义退化,故不采用。

**改动(3 处,均最小)**:

1. `_load_standalone_keys(warn: bool = True)` 加形参:非 ok 的 4 条 stderr 文案是**平日语义**措辞,full 模式传 `warn=False` 以免周日打「平日对账退回旧行为」的误导文案。默认 `True` 保持既有行为**逐字不变**(既有断言/既有调用全部不受影响)。
2. 台账加载提到模式分支**之外**(`cmd_verify_r2` 开头):
   ```python
   standalone_keys, _ledger_state = _load_standalone_keys(warn=not full)
   ledger_state = None if full else _ledger_state   # 「平日覆盖退化」告警语义仅属平日 → full 不误报
   ```
3. `standalone_files` 计算从 `else` 分支**提到 `if full/else` 之外**:
   `standalone_files = [f for f in files if f"{r2_prefix}/{f.relative_to(local_dir)}" in standalone_keys]`

改后关键位置:`upload_r2.py:3631-3639`(台账加载)/ `3653-3665`(standalone_files 计算)/ `3747`(使用点)。

## 3. 复现与自测证据

### 3.1 复现(修前必崩 → 修后通过)

复现脚本 `/tmp/repro_b6_verify_r2_full.py`(纯 tempdir + 全打桩:`s3_head`/`_upload_glob`/`_uniform_sample`/`notify`/`datetime.date.today()→2026-10-11`,零真实 R2 / 零真实外发):

```
[verify-r2] 模式=周日全量对账
[verify-r2] synth: 对账 2/2
[verify-r2] synth: 发现 1 个不一致/缺失 key(共查 2), 自动补传: kelly_mode_s06_state.json
Traceback (most recent call last):
  File ".../scripts/upload_r2.py", line 3730, in cmd_verify_r2
    _std_set = {str(f.relative_to(local_dir)) for f in standalone_files}
UnboundLocalError: cannot access local variable 'standalone_files' where it is not associated with a value
```

修后同一脚本:

```
[verify-r2] synth: 发现 1 个不一致/缺失 key(共查 2), 自动补传: kelly_mode_s06_state.json
[verify-r2] ⚠ 独立链产物与 R2 脱节: data/kelly_mode_s06_state.json
[verify-r2] ✓ 对账完成, 自动补传 0 个; 涉及文件名: data/kelly_mode_s06_state.json
[repro] RESULT = OK ; 告警 = ['[告警] 独立上传链产物与 R2 脱节(verify-r2 兜底补传)']
```

→ 不仅不崩,**脱节告警在 full 模式照常发声**(语义正确性被证实,非仅消崩)。

### 3.2 变异验证(证明新单测不是空转,§18 L49)

把 `origin/main`(修复前)版 `upload_r2.py` 放到临时树,跑同一份新单测:

```
2 failed, 4 passed
  FAILED ...::test_full_mode_mismatch_no_unboundlocalerror   ← UnboundLocalError @ upload_r2.py:3730
  FAILED ...::test_load_standalone_keys_warn_flag            ← TypeError: unexpected keyword 'warn'
```

→ 2 条针对性断言在修复前**必挂**、修复后**必绿**;另 4 条(反向/回归用例)修复前后都通过 = 说明它们是真正的回归护栏而非空转。

### 3.3 新增 CI 单测(6 条)

`scripts/tests/test_verify_r2_full_standalone_20261011.py`(CI 门禁 ⑧ 会跑,`python3 -m pytest -q scripts/tests/`):

| 用例 | 断言 |
|---|---|
| `test_full_mode_mismatch_no_unboundlocalerror` | 周日 full + 有通道不一致 → 不抛 + 全池逐个 HEAD + **脱节告警照发** |
| `test_full_mode_all_consistent_no_alert` | 周日 full + 全一致 → 不崩、无告警 |
| `test_weekday_standalone_still_selected_and_alert` | 平日(changed 空+抽样空)台账内独立链产物仍被对账 + 脱节告警(修前后行为不变) |
| `test_ledger_missing_full_mode_no_weekday_alert` | 周日 + 台账缺失 → **不发**「平日台账退化」告警(full 不误报) |
| `test_ledger_missing_weekday_alert_unchanged` | 平日 + 台账缺失 → 仍发台账告警(既有行为不被改掉) |
| `test_load_standalone_keys_warn_flag` | `warn=False` 无 stderr 文案;缺省 `True` 仍显式告警 |

全部 tempdir + 打桩 + `ZeroOutboundTrap`(零真实外发);跨环境敏感处显式传参/显式打桩,**不含任何「本机有 X」假设**(#223④ 教训)。

### 3.4 test_188 转绿(co-ordinator 提示的现成样本)

`scripts/tests/test_188_s06_sync_blindspot_pytest.py::test_188_s06_sync_blindspot_wrapped` 走周日 full 分支,修复前必挂于同一条 L3730。**修复后单跑 = 1 passed(11.16s)**。

## 4. 全量 pytest

`python3 -m pytest -q scripts/tests/`(修复后):

```
3 failed, 739 passed, 1 skipped in 91.38s
FAILED scripts/tests/test_212_upload_onfail_loud_pytest.py::test_e_pre_change_source_static
FAILED scripts/tests/test_245_l2_budget_digest_20261010.py::test_04_flush_before_2325_noop
FAILED scripts/tests/test_245_l2_budget_digest_20261010.py::test_04d_flush_stale_next_day_sends
```

**逐条归因(均非本改动引入,已逐条核实)**:

- `test_212::test_e_pre_change_source_static`:该用例设计为「**仅未提交态**才有意义」——断言 `git show HEAD:scripts/upload_r2.py` 里 `_channel_on_fail` 计数 == 0(= #212 改前证据)。而 #212 早已合入 HEAD(`11776c31b`),只有**本地工作区脏**(我改了 upload_r2.py)时才不 skip、才会撞上这条早已过时的断言。**commit 后 HEAD==工作区 → 自动 skip**。与本改动的 `standalone_files` 无关(断言对象是 `_channel_on_fail`)。
  - **提交后实测确认**:`pytest -q scripts/tests/test_212_upload_onfail_loud_pytest.py scripts/tests/test_188_s06_sync_blindspot_pytest.py` → **43 passed / 1 skipped**(该 skip 即 `test_e`,符合其「已提交态自动 skip」设计;同跑的 test_188 绿)。
- `test_245::test_04` / `test_04d`:日期敏感用例(隔日 stale 判定),**由另一任务负责,本任务不触碰**(协调者已明确)。

## 5. 同类错误面清单(§23.2 ③)

**扫描法**:自写 AST 近似流分析(`/tmp/b6_ast_scan.py`:维护「此刻确定已绑定」集合,If 取分支交集、For/While 保守、Try/With 直通;comprehension 目标、嵌套函数/类作用域排除)对**修复前 vs 修复后**两份文件逐条对照。

- **修复前 61 条候选 / 修复后 60 条 —— delta 恰为 1 条**:
  - 修复前独有:`cmd_verify_r2() L3730: standalone_files` ← **即本次病灶**
  - 修复后新增:0 条(未引入新候选)
- 残余 60 条候选经**人工复核全部为已知假阳类**:
  - 组合解包在循环/with 内(`_upload_glob` 的 `rel/key/size`、`cmd_upload_large_json` 的 `relpath/raw/size` 等)——赋值与读取同在循环体内,运行时恒已绑定;
  - `try:` 惰性 import 的模块名(`notify`/`_dt`/`gzip` 等)——模块级或 try 体内已绑定;
  - 嵌套 `def _check` 边界处的 `ok`——扫描器把内层函数体算进了外层引用面(启发式局限,非真隐患)。
- **诚实标注局限**:该扫描器是**候选筛选工具**(非完备流分析),残余假阳需人工判读;本次它对本病灶的**定位是精确的**(delta 恰 1 且指向 L3730)。

**人工复核**:`cmd_verify_r2` 全函数逐句读;`grep -n "standalone_files"` 全仓 → **仅 `upload_r2.py` 5 处(均在本次改动范围内)+ 新增单测**,无其它文件/其它函数存在同名变量。

## 6. 举一反三清单(§23.3)

| 面 | 结论 |
|---|---|
| 同模式(full/平日双分支)变量 | `cmd_verify_r2` 内其它变量(`mm_rels`/`ok,total,failed_rels`/`ledger_state`)逐一复核:前二者仅在 `if mismatches:` 内定义并使用(同块内),后者已显式预置 → 无同类隐患 |
| 同数据源(独立链产物台账 `.r2_standalone_keys.json`) | 读写方 = `_record_standalone_keys`(登记侧)、`_load_standalone_keys`(读侧,加了 `warn` 形参,默认行为不变)、`verify_r2_standalone_stale` / `verify_r2_standalone_ledger_gap` 两条告警 → 均已覆盖,告警语义与模式匹配(full 不发平日台账告警) |
| 同组件(verify-r2 的调用方) | `deploy.sh` 收尾 R2_FAIL 链、`r2_upload_async.sh`;本次不改其接口(仅内部行为),无需联动 |
| 相关展示位(§22 一致性) | 本次**不产出任何数据产物**,不涉 N 文件/N 缓存同步 |
| 其它脚本同类 bug 面 | 病灶形态(「变量仅在某分支赋值、分支外无条件引用」)在仓库其它脚本未发现同源实例;`standalone_files` 全仓唯一 |

## 7. 复现命令

```bash
# 修复前(可对 origin/main 版文件)必崩 / 修复后必过
/Users/linhuichen/code/trade/.venv/bin/python /tmp/repro_b6_verify_r2_full.py <repo>/scripts
# 新增单测
cd <repo> && /Users/linhuichen/code/trade/.venv/bin/python -m pytest -q scripts/tests/test_verify_r2_full_standalone_20261011.py
# 原周日样本(test_188)转绿
cd <repo> && /Users/linhuichen/code/trade/.venv/bin/python -m pytest -q scripts/tests/test_188_s06_sync_blindspot_pytest.py
# 同类错误面扫描(修复前/后对照)
/Users/linhuichen/code/trade/.venv/bin/python /tmp/b6_ast_scan.py <repo>/scripts/upload_r2.py
```

## 8. 红线遵守与未决上报

- **禁止真跑生产全量 verify-r2**:全程未执行 `verify-r2` 真命令;所有验证均在 tempdir + 打桩下完成,**零 R2 写入 / 零真实外发**(`ZeroOutboundTrap` + notify 打桩双层)。
- **今晚 22:30 #220 force_full** 的自然窗口 = 真验证(留给它)。
- 不 push main、不 force push;凭证未进 git;仅改本 bug 相关代码。
- **上报主控(§23.7)**:① `test_212::test_e_pre_change_source_static` 的断言依赖「本地工作区脏」这一脆弱前提,一旦本地有任何 upload_r2.py 改动就会红(CI 上因 HEAD==工作区而 skip)——**这是该用例自身的口径问题**(#212 已合入后「改前版」实际不可得),非本任务范围,建议单独登记。② `test_245` 两条日期敏感用例由另任务负责,本任务未触碰。