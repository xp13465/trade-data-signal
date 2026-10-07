# #213 ⑧ 步依赖注释漂移订正(2026-10-07)

> implementer 续跑产出(独立审 P3① 项)。**纯注释/docstring 改动, 零运行影响(代码行零改动)**。
> 分支 `feat/213-ci-batch12-20261007`, 本项 commit `f634525fc`(base `5826fc9e6`)。

## 1. 问题(注释与事实漂移)

`.github/workflows/ci.yml` ⑧ 步实际安装命令(本项改动后 L122)为:

    pip install pytest pyyaml numpy==2.4.6 pandas==3.0.5 pyarrow==25.0.1

但同文件头部挂载项说明(L17)与 `scripts/tests/conftest.py`(L16)仍写「仅需 pip install
pytest pyyaml」的旧口径 —— 与 `5826fc9e6`(pin 对齐生产 pandas 3.0.5)后的事实不符。

## 2. 改动(3 处, 全部注释/docstring)

| 文件 | 位置 | 改动 |
|---|---|---|
| `.github/workflows/ci.yml` | 头部挂载项 ⑧(L17 附近) | 「(仅需 pip install pytest pyyaml)」→「#213 方案 A2 起依赖面 = pytest + pyyaml + numpy/pandas/pyarrow 5 件真数值库, 版本 pin 与依据见 docs/ops/213-batch2-dependency-decision-20261007.md」 |
| `scripts/tests/conftest.py` | 模块 docstring ③(L16 附近) | 「CI ⑧ 只 pip install pytest pyyaml」→「CI ⑧ 装 pytest + pyyaml + numpy/pandas/pyarrow(#213 方案 A2, 2026-10-07 起)」; 并补明 numpy/pandas/pyarrow 已装 ⇒ CI `find_spec` 命中 → **不 stub**, 仅 requests/akshare 仍走 stub(stub 跳过逻辑代码零改动) |
| `scripts/tests/test_kelly_stats.py` | 模块 docstring【依赖】(L17) | 「CI ⑧ 已 pip install pytest pyyaml」→「CI ⑧ 已装 pytest + pyyaml + numpy/pandas/pyarrow(#213 方案 A2)」 |

第 3 处为 §23.3 举一反三产物: 任务点名 2 处, 广义 `grep "pip install pytest pyyaml"` 另捞出
同模式残留第 3 处(同一「CI ⑧ 依赖口径」事实), 一并订正。

## 3. 自验(逐条)

1. `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"` → **YAML_OK**
2. `grep -rn "仅需 pip install pytest pyyaml\|仅需 pytest pyyaml" .github/ scripts/tests/` → **零残留**
3. 广义 `grep -rn "pip install pytest pyyaml" .github/ scripts/tests/` → 仅剩 L122 真安装命令(准确)
4. `pytest -q --collect-only scripts/tests/`(项目 venv pytest 9.1.1 / py3.11) → **386 tests collected, 零错误**
5. `git show --stat HEAD` → 3 files changed, 14 insertions(+), 9 deletions(-); 逐行核 diff **全部落在 `#` 注释行 / 模块 docstring 内, 代码行零改动**

## 4. 备注

- 报告所指向的 `docs/ops/213-batch2-dependency-decision-20261007.md` 已在 origin/main
  (本 feat 分支创建早于其落 main, 故分支内不存在该文件; merge 后引用有效, 与本分支已存在的
  ci.yml L112 引用同源)。
- 分支相对 origin/main 为 base-stale(3 ahead / 5 behind); 因分支已推送且「不 force」为硬约束,
  本项以 fast-forward 追加 1 commit, 未 rebase;base 新鲜度由主控 `main-merge.sh` 合并入口处理。
- 历史 docs 报告(如 ci-pytest-review-20261003.md 等)内「pip install pytest pyyaml」为其时点
  真实记录, 属历史事实, 不属本次漂移订正范围。
