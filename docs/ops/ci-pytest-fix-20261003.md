# GitHub CI 门禁 pytest 收集崩溃修复(2026-10-03)

## 根因

`.github/workflows/ci.yml` ⑧(`python3 -m pytest -q scripts/tests/`)自 2026-10-01 起恒红约 2 天
(workflow 349474535 最近 25 次 = 14 failure / 11 cancelled / 0 success):

1. `scripts/tests/` 下 5 个自测文件是**脚本式**(顶层直接执行 + 末行 `sys.exit`),pytest
   收集阶段即执行顶层代码;脚本式文件无 `test_*` 函数 → 收集 INTERNALERROR / no tests collected。
2. `test_notify_r4_dedup_20261001.py` 曾硬编码他人 worktree 绝对路径
   `WT = Path("/Users/linhuichen/code/trade/.claude/worktrees/agent-a45df7aac3ee7ea07")`,
   CI(ubuntu runner)上该路径不存在 → import 即崩溃。

## 逐文件改造对照表(改造前 test 函数数 → 后)

| 文件 | 改造前 | 改造后 | 说明 |
|---|---|---|---|
| test_132_count_file_fail_loud.py | 0(脚本式 5 check) | 5 test | 逐条转 assert, 打真实 `retry_failed_metrics` |
| test_132_morning_slot.py | 0(脚本式 9 check) | 9 test(parametrize 9 组) | 打真实 `backfill_direct_metrics._is_morning_slot` |
| test_132_self_heal_mutex.py | 0(脚本式 5 check) | 2 test(并发实验 5 角度合一 + 串行基线) | `with_lock.py --nb` 真实互斥; VERSHO 硬编码 → `sys.executable` |
| test_notify_r4_dedup_20261001.py | 1(内嵌非收集) | 6 test | import 用 conftest 路径, 硬编码 worktree 路径清零; 模块级桩 autouse 隔离 |
| test_alert_denoise_20261001.py | 0(脚本式 34 check) | 34 test | 28+ 条 check 逐条转 assert, 一条不丢 |
| conftest.py | 不存在 | 新增 | sys.path / REPO / CI 第三方库 stub |
| test_kelly_stats.py / test_loss_rules_20keys.py / test_s06_state_machine.py | 正常 pytest | **未动** | 任务明确「不得动」 |

合计:CI 收集从 0 崩溃 → **133 tests collected, 133 passed**。

## conftest.py 策略与「为什么不会假绿」

conftest 解决三件事:
- ① `sys.path` 注入 `scripts/` + 仓库根(脚本式文件 import `retry_failed_metrics` /
  `backfill_direct_metrics` / `notify` / `alert_denoise_rules` 需要);
- ② `REPO` env setdefault 为仓库根(消除 `backfill_direct_metrics.py` 顶层 `os.environ.get("REPO",
  主仓绝对路径缺省)` 的开发者路径依赖);
- ③ 第三方库 stub:**仅当 `importlib.util.find_spec()` 找不到时才注入空 `ModuleType`**(本地
  venv 已装真实库 → 不 stub, 与生产同构)。

**为什么不会假绿**:
1. stub 只解决「CI 环境 import 不到依赖」这一件事——条件是 find_spec 失败(库未安装)。
   测试只「import 模块 + 调纯判定函数/方向 monkeypatch」, 被测逻辑本身不走进 stub。
2. 任何**运行时**对 stub 的访问:stub 缺该属性 → AttributeError **响亮失败**, 不会静默通过。
   requests stub 的 Session 只带 import 期必需的 `headers`(dict)+ `mount()` 空实现
   (base.py `EM_SESSION = requests.Session()` 后紧跟 `EM_SESSION.headers.update(...)`),
   运行时 `.get` 等不在 stub → 失败不假绿。
3. 迭代实证:先建 CI 模拟裸环境(`/tmp/ci-sim-venv` 只装 pytest+pyyaml), 首轮即暴露
   原 conftest 的 `Session` stub 缺 `headers`(本地 venv 有真实 requests → stub 分支从未
   被走到 = 上一轮 implementer 的盲区), 补 `headers` 后 CI 模拟环境 133 passed。
4. 证伪对照(防改成恒绿摆设, 见下):故意改坏 2 个断言 → 恰在断言点失败; 恢复后全绿。

## 证伪对照证据(2026-10-03)

故意把两个断言改错后单独跑, **恰在该断言点 FAIL**(非恒绿):

```
scripts/tests/test_132_count_file_fail_loud.py:107: AssertionError
  assert c3 == {'a': 99, 'b': 1}  →  real c3={'a': 6, 'b': 1}
FAILED scripts/tests/test_alert_denoise_20261001.py::test_r2_caseA_same_instance_merged
FAILED scripts/tests/test_132_count_file_fail_loud.py::test_4_restored_writable_persist
2 failed in 0.82s
```

恢复后重新全量:

```
本机 trade-data venv : 133 passed in 4.45s
CI 模拟裸 venv        : 133 passed in 3.68s
collect-only          : 133 tests collected
```

## 硬编码清零

`grep -rn "/Users/linhuichen" scripts/tests/`:
- **本任务改造的 5 个文件 + conftest.py:0 命中**(功能级硬编码 + docstring 复现命令均已清)。
- 残留 3 处命中全部位于任务明确「不得动」的 3 个**正常 pytest 文件**的 docstring 复现命令
  (`【复现命令】cd /Users/linhuichen/code/trade && ...`), 为注释非执行代码, 不影响 CI 收集/运行;
  因「不得动」约束未修改, 如实列明不静默。

## 遗留项

- 3 个正常 pytest 文件 docstring 中的开发者本机路径复现命令未改(受「不得动」约束),
  后续如需彻底清零可另行派单仅改注释;非功能风险。
- CI 门禁 ⑧ 的 `pip install pytest pyyaml` 依赖最小化策略不变(requests/pandas/akshare/pyarrow
  由 conftest stub), 未新增重型依赖, 门禁时长不受影响。

## 复现段

```bash
# 全量(本机开发 venv 或仅装 pytest+pyyaml 的裸环境均可)
python3 -m pytest -q scripts/tests/

# 收集数证明(必须 >0, 防「no tests ran」假绿)
python3 -m pytest --collect-only -q scripts/tests/ | tail -1   # 期望: 133 tests collected

# 证伪对照(复现「断言之有 FAIL」):
#   把 scripts/tests/test_132_count_file_fail_loud.py test_4 的期望 {a:6,b:1} 改坏 →
#   该用例即红; 恢复后全绿。

# 硬编码清零复核
grep -rn "/Users/linhuichen" scripts/tests/   # 期望: 仅 3 个「不得动」文件 docstring 注释残留(见上)
```