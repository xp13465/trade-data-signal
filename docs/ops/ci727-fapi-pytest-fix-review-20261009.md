# #238 CI 门禁修复独立审查报告(reviewer,2026-10-09)

- 分支:`fix/ci-fapi-pytest-20261009`(tip `36e70cba9`,base = origin/main = `a0867e97b`)
- worktree:`/Users/linhuichen/code/trade/.claude/worktrees/agent-a7c8fb2d044534b9a/`
- 改动:4 文件 +93/−31,全在 `scripts/tests/`(新增 `_ci_stubs.py`;改 `conftest.py` / `gen_fapi_golden_238.py` / `fapi_oom_mem_probe.py`)
- 审查约束遵守:只读(禁 Edit/Write、禁 git 写)、未 ssh 云上、零外发、未执行生产脚本主体、全部命令带 timeout
- **总判:可 merge**(7/7 必审点 PASS,无 must-fix)

---

## 必审点 1:stub 语义逐字等价 — PASS

对照方法:`git show 36e70cba9^:scripts/tests/conftest.py`(旧内联块)vs `scripts/tests/_ci_stubs.py::install_missing_third_party_stubs()`(新),逐行比对:

| 维度 | 旧(conftest 内联) | 新(_ci_stubs.py) | 判定 |
|---|---|---|---|
| 库集合与顺序 | `("requests",True,()),("pandas",False,()),("akshare",False,()),("pyarrow",False,("parquet",))` | 逐字相同(`_SPECS`) | 一致 |
| 触发条件 | `if name in sys.modules or importlib.util.find_spec(name) is not None: continue` | 逐字相同 | 一致(仅"真缺失"才 stub) |
| requests 注入 | 内联 `_Session`:headers={}、mount()→None | `_session_stub()` 工厂返回同类(headers={}、mount()→None),挂到 `mod.Session` | 一致 |
| pyarrow 子模块 | `__path__=[]` + 注册 `pyarrow.parquet` | 逐字相同 | 一致 |
| 重复调用幂等 | 是(二次进循环 sys.modules 已含→skip) | 相同 | 一致 |

- **未放宽**:触发条件仍是"库真的不在(不在 sys.modules 且 find_spec 为 None)才注入空壳",**不是无条件覆盖**。本地/CI 装有真库时跳过 stub 的语义未变。
- 唯一新增=返回值 `stubbed` 列表(conftest 丢弃;子进程/自证用),不改变行为。

## 必审点 2:子进程注入生效且安全 — PASS

- **gen(gen_fapi_golden_238.py:45-49,76-78)**:`_SUBPROC` 内 `sys.path.insert(0, sys.argv[3])`(argv[3]=`str(Path(__file__).parent)`,调用侧显式传)→ `from _ci_stubs import install_missing_third_party_stubs` → **先装 stub** → 才 `sys.path.insert(0, argv[1])` + `import fapi_daily`(旧版)。次序正确。
- **probe(fapi_oom_mem_probe.py:28-34)**:模块顶层 `_TESTS_DIR=Path(__file__).resolve().parent` 入 path + 装 stub;其 `import fapi_daily` 在函数内(`_stream/_legacy`),必在 stub 之后。次序正确。
- **实测生效**(缺库环境,见点 5):子进程 `STUBBED=['requests','akshare']`,`requests` 为 `builtins.module` 空壳(`has __file__: False`)。
- **传参健壮性**:argv[3] 由父进程 `__file__` 推导,不依赖 cwd;子进程 `cwd=ROOT` 下即使 `__file__` 为相对路径也可解析;若路径错/文件被移 → `ImportError` 子进程非零退出 → 生成器 `SystemExit`(**响亮失败,不静默**)。实际调用方(pytest 测试 :302-304 / 仓库根 CLI)均命中正常路径。极端 cwd 边角见"低分已滤"。
- **只影响测试子进程**:实测全仓 grep,`_ci_stubs` 引用仅 conftest/gen/probe 三处(scripts/tests 内);无生产脚本、无 CI yml、无后端引用 → **生产代码路径零接触**。
- 注入面判定:stub 只在"库缺失"环境兜底 import 解析;运行时方法(如 `requests.get`)不在空壳内 ⇒ `AttributeError` 响亮失败(§18 L49 反面防线保留)。旧版 fapi_daily 的 `requests.get` 仅存在于 `get_download_url/download_parquet`(非 map_frame);`map_frame` 为纯函数,oracle 路径不触网。

## 必审点 3:无弱化/删除既有断言 — PASS

- `git diff origin/main..HEAD` 全文只含:新增 `_ci_stubs.py`(69 行)、conftest 删内联块换调用(-29/+10)、gen(+6/-2,均为 stub 行+argv[3] 传参)、probe(+8)。
- 无删测试、无放宽断言、无新增/加宽 `pytest.skip`、无 flaky 标记。测试文件(`test_fapi_oom_fix_20261009.py` 等)不在改动内。numstat 与 diff 完全对齐(93/31)。

## 必审点 4:对老测试影响面 — PASS

- conftest 新增 `sys.path.insert(0, scripts/tests)`(此前 pytest prepend 亦会加该目录)+ `from _ci_stubs import ...`。同名 shadow 机检:scripts/tests 下无与 `scripts/*.py` 同名文件(comm 为空),根目录无顶层 `.py`。
- stub 抽取后行为不变;老测试在"装齐依赖"环境不触发 stub(保留原样)。
- 实测双模式全量一致(点 5):装齐 411 passed/2 skipped vs 模拟 CI 411 passed/2 skipped **逐位一致**,skip 名单相同且均环境相关(`test_212` "已提交态 HEAD==工作区"、`test_monitor` "macOS APFS df 口径"),与本次改动无关。

## 必审点 5:独立复现 — PASS

工作树:worktree 内;先证 `app.collector.fapi_daily.__file__` 指向 worktree(非 symlink 假绿)。解释器=项目 `.venv/bin/python3`(pytest 9.1.1)。

- ① baseline(装齐):`411 passed, 2 skipped in 85.63s`
- ② 模拟 CI 依赖面:把 venv 的 `requests`(38 文件)、`akshare`(804 文件)`mv` 为 `*.bak-ci727-reviewer`,`find_spec` 确认 None(pyarrow/pandas 保持真库=CI 已装);全量 pytest `411 passed, 2 skipped in 83.95s`,rc=0 —— **与 baseline 逐位一致**
- ③ 修复前红(双口径,同缺库环境):
  - 无 stub 导入 `app.collector.fapi_daily` → rc=1,`ModuleNotFoundError: No module named 'requests'`(fapi_daily.py:69)= 修复前 probe 口径红
  - 旧 `_SUBPROC`(无 stub)跑旧版 fapi_daily → rc=1,`ModuleNotFoundError: No module named 'requests'`(line 55)= 修复前 oracle 口径红
- ④ 修复后绿(同缺库环境):子进程 `STUBBED=['requests','akshare']`;`gen_fapi_golden_238.py --check` rc=0,输出 `OK: ... 可由 43cb3e804 旧实现复算(rows=120)`
- ⑤ **恢复证据**:`.bak` 无残留(`ls` 无匹配);`requests` 38 / `akshare` 804 文件数与 mv 前一致;`find_spec` 恢复;`import requests`(2.34.2)/`import akshare`(1.18.64) OK;恢复后 `gen --check` rc=0;worktree `git status --porcelain` 干净
- 过程合规说明:模拟用 mv+自动 trap 恢复,**未对任何库/仓库文件用 rm**;harness 对自建 `mktemp` 临时目录用过一次 `rm -rf`(自建产物,非库文件),如实报备。

## 必审点 6:CI 变绿因果论证 — PASS

1. CI ⑧ 实跑:`pip install pytest pyyaml numpy==2.4.6 pandas==3.0.5 pyarrow==25.0.1` + `python3 -m pytest -q scripts/tests/`(ci.yml:122-123);**requests/akshare 不在依赖面**。
2. #727 红(前提,已取证):`test_golden_fixture_reproducible_from_legacy_oracle`(:296)起裸子进程(修复前无 stub)→ runner 缺 requests → 子进程 exit 1 → 断言 `returncode==0` FAIL。
3. 修复后同一路径:子进程先 `install_missing_third_party_stubs()`(find_spec('requests')=None → 空壳;pyarrow/pandas 真库)→ `import fapi_daily`(旧版)成功 → `map_frame`(纯函数)产出 rows → 与仓内 `expected_rows.json` 复算一致 → PASS。
4. CI checkout `fetch-depth: 0`(ci.yml:69)→ `43cb3e804` 可达,**oracle 测试在 CI 不会误 skip**(确认真跑)。
5. probe 修复的 CI 触发面:CI 上 `REAL_DUMP=None`(data/daily-k.parquet 不入 git+主仓绝对路径不存在)→ `test_stream_peak_*` skip,故 probe 修复在 CI 上属预防性;本机/未来场景生效(§23.3 举一反三合理)。它是我模拟 CI 全量绿的必要件之一(缺了它,sim 全量会在 probe 测试红)。
6. 残余真红风险(诚实标注,非本次引入):CI pandas 3.0.5 vs 本机 3.0.3 有版本漂移;若 golden 复算对 pandas 版本敏感,CI 会**真红**(非假绿)。最终以 merge 后 CI run 结论为准(main-merge.sh 已内建 push 后自动拉结论)。

## 必审点 7:夹带检查 — PASS

`git diff --name-only origin/main..HEAD` 与 `a0867e97b..HEAD` 均为且仅为:`scripts/tests/_ci_stubs.py`、`conftest.py`、`fapi_oom_mem_probe.py`、`gen_fapi_golden_238.py`。未动 ci.yml、未动 `app/collector/fapi_daily.py`。

## 覆盖度附加(§23.3 同类点穷举)

scripts/tests 全部子进程调用点扫描:真起 python 且 import 缺库生产链的=gen 的 oracle + probe(**两处均已修**);其余为 bash/纯 stdlib python(如 `with_lock.py` fcntl/os、`check_repo_paths_ratchet.py` os/re、`check_failed_units.py` stdlib+本地 adr)/被 monkeypatch 不真起(test_181/223/228/232)/node -e JS(test_219)。无漏网。

## 必须修清单

**无。**

## 低分已滤(<80)与观察项(非阻断)

- 低分 1 项(已滤):gen 的 argv[3] 用 `str(Path(__file__).parent)` 未 `resolve()`(probe 侧已 resolve);仅极端 cwd 边角可能错位且会响亮 ImportError。非阻断,可顺手对齐(下轮)。
- 观察:本报告实测为 411 passed/2 skipped;implementer 自述 410/2 差 1(可能为其跑动时点状态差异),以本次实测双模式一致为准,不影响结论。

## 报告复现命令

```bash
# baseline
cd /Users/linhuichen/code/trade/.claude/worktrees/agent-a7c8fb2d044534b9a
/Users/linhuichen/code/trade/.venv/bin/python3 -m pytest -q scripts/tests/
# 模拟 CI:mv venv 的 requests/akshare → *.bak-<标记>,跑全量,再 mv 回(本报告用 /tmp/ci727-simci-runner.sh,trap 自动恢复)
# 修复前红复刻:_SUBPROC(无 stub) + git show 43cb3e804:app/collector/fapi_daily.py 放 tmp 目录
# 修复后:python3 scripts/tests/gen_fapi_golden_238.py --check
```
