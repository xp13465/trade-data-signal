# CI 门禁 pytest 收集崩溃修复 — 独立复核报告(2026-10-03, reviewer)

被审分支: `origin/feat/ci-pytest-fix-20261003` @ `24b6a9d86`(base = `origin/main` `fc951666a`,仅 2 笔提交)
判据: 独立构建环境复现 + 独立证伪对照(不复用实施者自测脚本/结论)

## 结论: PASS(假绿 / 漏项 / 断言弱化 / CI 仍会红 四项均未命中)

## 1. 环境复现 — PASS
自建干净 venv(仅 `pip install pytest pyyaml`,Python 3.11,模拟 CI ⑧裸环境),全仓 checkout 模拟(`git archive` 抽被审分支全树,127M 含 app/config/data/static-site):
| 环境 | 结果 |
|---|---|
| clean venv `--collect-only` | `133 tests collected in 0.05s`(收集数 > 0) |
| clean venv `pytest -q scripts/tests/` | `133 passed in 3.70s` |
| 仓库 venv(trade-data/.venv,真库全装) | `133 passed in 4.32s` |
报告声称 133,逐位对上。

## 2. 证伪对照(独立挑 2 个,不同文件,非实施者那 2 个)— PASS
在 `/tmp/ci-review-20261003`(我自建副本)改坏断言:
- `test_132_morning_slot.py`: 02:00 整点用例期望 True→False → `FAILED test_morning_slot[slot0200@0200]`(恰在断言点)
- `test_notify_r4_dedup_20261001.py::test_1`: `assert in st`→`assert not in st` → `FAILED test_1_all_ok_updates_dedup`(恰在断言点)
恢复后重跑全量 `133 passed in 3.65s`;恢复文件 md5 与分支 git 内容逐位一致(`efce196d…`/`9e8adddc…`),`git diff` 干净。

## 3. 假绿专项 — PASS(逐条点名)
- conftest 仅在 `find_spec` 失败才注入 stub;仓库 venv(真库)与干净 venv(全 stub)均 133 passed → 测试结果不依赖 stub,无「stub 环境才过」的分叉。
- 被测模块顶层因 stub 走的分支:
  - `app/collector/base.py`: `EM_SESSION = requests.Session()` → stub `_Session`(headers dict 可 update,`mount()` 空实现);`from requests.adapters import HTTPAdapter` 在干净 venv ImportError → try 块整体跳过。测试从不调用 `em_get`/EM_SESSION 运行时方法;若调用 stub 缺 `.get` → AttributeError 响亮失败(非假绿)。
  - `app/calendar.py`: `import akshare` 得 stub(非 None);`_load_trade_dates` 不被任何测试调用,若调且无 `data/trade_dates.txt` 缓存 → stub 缺属性 AttributeError(响亮,非假绿);该文件已在分支 tracked。
- 5 个改造文件: `try/except/finally` 0 命中,断言无被吞;`pytest.mark.skip/skipif/xfail` 0 命中,无静默空跑。
- 唯一模块级 skip = 既有「不得动」`test_kelly_stats.py:40`(import signal_kelly_backtest 失败则整模块 skip)。干净 venv 收集 32 条(未触发 skip),该文件未被分支改动;若 CI 上其 import 链崩则收集数会掉到 101,可用「收集数=133」做反假绿护栏。

## 4. 一条没丢核验 — PASS
| 文件 | 原件 check | 现 test | 逐条核对 |
|---|---|---|---|
| test_132_count_file_fail_loud.py | 5 段 11 条 check(其中 1 条恒 True 占位) | 5 | 10 条真实断言全覆盖;占位并入 rc==1 断言失败信息(已文档化),非删减 |
| test_132_morning_slot.py | 9 条(表驱动 CASES) | 9 | CASES 逐条一致,assert got==expected 与原 check 同条件 |
| test_132_self_heal_mutex.py | 5 条 | 2 | 并发实验 4 角度合一 + 串行基线 1,5 条全盖 |
| test_notify_r4_dedup_20261001.py | 6 条 | 6 | 逐条对应,断言条件与原 check 一致 |
| test_alert_denoise_20261001.py | 34 条 check() | 34 | **34 条逐条对照: 断言条件与原 check 完全相同,无 `assert x in y`→`assert y` 类弱化** |
无漏项、无弱化。

## 5. 不动不该动的 — PASS
- 3 个既有正常 pytest(test_kelly_stats / test_loss_rules_20keys / test_s06_state_machine): `git diff origin/main..branch -- <各文件>` 均为 0 字节。
- 生产代码 / 前端源码 / 版本串 / ci.yml: 分支 diff 仅 `scripts/tests/*`(5 文件)+ `conftest.py` + 报告 1 篇,全量 stat 7 文件,无其它。
- 未 push main: `git log origin/main..origin/feat/ci-pytest-fix-20261003` 恰好 2 笔(`0c1a5aebd` 主修复 + `24b6a9d86` 报告修正)。

## 6. 报告对账 — PASS
逐文件收集数(clean venv 实测)vs 报告表:
| 文件 | 报告 | 实测收集 |
|---|---|---|
| test_132_count_file_fail_loud | 5 | 5 |
| test_132_morning_slot | 9(parametrize 9 组) | 9 |
| test_132_self_heal_mutex | 2 | 2 |
| test_notify_r4_dedup | 6 | 6 |
| test_alert_denoise | 34 | 34 |
| 3 个正常文件 | 未动 | 32 / 33 / 12 |
| 合计 | 133 | 133 |
- 提示项 `test_132_morning_slot.py`: 文件内 "parametrize" 字面 2 处(第 6 行 docstring + 第 41 行实际装饰器),实际仅 1 个装饰器 × 9 CASES = **9 tests,与报告 "9" 对上**。
- 报告修正 commit(`24b6a9d86`)把 test_notify 改造前从「1(内嵌非收集)」改为「0(脚本式 6 check)」: 原件确实无 `def test_` 全脚本式 6 check,修正后数字准确。

## 7. CI 真能转绿吗 — PASS
- 仓库无 `pytest.ini`/`pyproject.toml`/`setup.cfg`/`tox.ini`,无根级 `conftest.py` → 无 addopts/rootdir 干扰。
- 被审分支 `scripts/tests/` 仅 8 个测试文件 + conftest,无 `__pycache__`/`.bak`/`.orig` 残留。
- ⑧ 前置步骤实测全绿(我的 worktree = base main,分支未动这些输入): ① check_fade_keys_alignment EXIT=0; ② check_version_progress EXIT=0; ③ check_version_consistency EXIT=0(且 continue-on-error); ④ node --check 9 个前端源 JS 全过; ⑤ check_task_state EXIT=0。
- ⑧ 模拟: 干净 venv `pip install pytest pyyaml` → pytest 9.1.1,全仓 checkout 跑 `python3 -m pytest -q scripts/tests/` = 133 passed(ubuntu runner 同语义)。
- 依赖输入齐备: `config/indicators.yaml`(load_config 用)与 `data/trade_dates.txt`(app/calendar 缓存)均在被审分支 tracked,CI checkout 自带。

## 观察项(非阻断)
- `test_kelly_stats.py` 既有模块级 try/except→`pytest.skip(allow_module_level=True)`(「不得动」文件,非本次改动引入): CI 收集数=133 可作其未静默跳过的反假绿护栏,若未来某日收集数低于 133 须查该文件 import 链。
- 干净 venv 与仓库 venv 均 133 passed → 测试对第三方库 stub 与否不敏感,无「stub 掩盖真失败」分叉。

# 复现段
```bash
# 1) 建干净 venv(模拟 CI ⑧裸环境,只装 pytest+pyyaml)
/usr/local/bin/python3 -m venv /tmp/ci-review-venv
/tmp/ci-review-venv/bin/pip install pytest pyyaml

# 2) 全仓 checkout 模拟(只读,抽被审分支全树到 /tmp)
mkdir -p /tmp/ci-review-20261003 && cd /tmp/ci-review-20261003
git archive origin/feat/ci-pytest-fix-20261003 -o /tmp/full-branch.tar
tar -xf /tmp/full-branch.tar

# 3) 收集数(必须 >0,防 no tests ran 假绿;预期 133)
/tmp/ci-review-venv/bin/python -m pytest --collect-only -q scripts/tests/ | tail -1

# 4) 全量(预期 133 passed)
/tmp/ci-review-venv/bin/python -m pytest -q scripts/tests/

# 5) 证伪对照(自建副本改坏断言,验证 FAIL 恰在断言点,恢复后 md5 一致)
cp scripts/tests/test_132_morning_slot.py /tmp/bak.py
# 把 CASES 里 02:00 整点用例 expected True 改 False → FAILED test_morning_slot[slot0200@0200]
cp /tmp/bak.py scripts/tests/test_132_morning_slot.py   # 恢复
```
