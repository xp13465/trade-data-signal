> 归档自 /tmp/pickdb-impl-report-20261127.md,2026-11-27;原始路径为临时文件,本副本为持久归档

# #383 pick_db 家族收敛到部署数据树单源 — 实施报告(2026-11-27)

- 分支:`feat/pickdb-single-root-20261127`(worktree `/tmp/wt-pickdb-20261127`)
- base commit:`78c062f21`(origin/main,开工 rebase 后 base-fresh 已校验)
- 方案:调研报告 §3 案 A(权威改动面逐条落地)
- 版本串:本次未改前端源码(app.js/lab.js/common.js/style.css 均未动),不需 build_min/bump(机制 C 由主控 merge 统一处理)

## ① 逐文件改动面

| 文件:行号 | 改动 |
|---|---|
| `scripts/pick_repo.py:11`(docstring)/ `:91-102` | 新增 `sentiment_db(repo: Path \| None = None) -> Path` = `(repo or pick_repo()) / "data" / "sentiment.db"`;模块 docstring 补一行。`candidate_repos()` **未改**(仍服务 `pick_repo()` 与 `fetch_news.py`) |
| `scripts/gen_daily_brief.py:107-109` | import 由 `candidate_repos` 换 `sentiment_db` |
| `scripts/gen_daily_brief.py:127-132` | `pick_db(repo)` 保留签名,函数体改为 `return sentiment_db(repo)`(删 19 行候选遍历+MAX(date));3 个生产调用点(:4117 / :1674 / :2188)零改动 |
| `scripts/brief_ledger.py:74` | import 改 `from pick_repo import pick_repo, sentiment_db` |
| `scripts/brief_ledger.py:107-111` | `_pick_db(explicit)` → `explicit or sentiment_db()`;**删掉写死 macOS 兜底路径**(原 L128) |
| `scripts/aggregate_shadow.py:19-21` / `:27-32` | 删 `import os`(最后唯一用途随 `_candidate_repos` 删除);import 加 `sentiment_db`;口径注释改写 |
| `scripts/aggregate_shadow.py`(原 L37-71 整段删除) | 删私有 `_pick_db` 与 `_candidate_repos`(后者漏 MAIN_REPO、写死两个 macOS 路径的漂移实现) |
| `scripts/aggregate_shadow.py:162` | `db_path = _pick_db()` → `sentiment_db(repo)`(复用 main 内已取的 repo) |
| `scripts/ab_direction_anchor.py:39` | docstring 输入依赖行改「由 sentiment_db 走部署数据树单源」 |
| `scripts/ab_direction_anchor.py:89` | import 加 `sentiment_db` |
| `scripts/ab_direction_anchor.py`(原 L100-103 整段删除) | 删 `_pick_db` 包装(不再依赖 gen_daily_brief 私有实现) |
| `scripts/ab_direction_anchor.py:263` / `:295` | 两处调用(`_build_ref` / `--reconcile`)改 `sentiment_db(repo)` |
| `scripts/replay_direction_anchor.py:56-58` | sys.path 加 scripts 目录 + `from pick_repo import sentiment_db` |
| `scripts/replay_direction_anchor.py:91` | `gen_daily_brief.pick_db(repo)` → `sentiment_db(repo)` |
| `scripts/deploy.sh:744-745` | 注释同步:代码仓 `data/*.db` 零读取方的说明由「pick_db 镜像兜底容忍缺文件」改为「sentiment.db 读者已收敛单源,库缺失时调用方 sqlite3(mode=ro) 响亮报错」 |
| `scripts/tests/test_383_sentiment_single_root.py`(新增) | 4 个用例,见 ② |

去重结果:原 3 份 `SELECT MAX(date) FROM daily_metric` 候选遍历(gen_daily_brief/brief_ledger/aggregate_shadow)已全部删除,全仓 `scripts/` 内该 loop 剩 **0 处**;sentiment.db 路径判定收敛为 `pick_repo.sentiment_db` 单点。

## ② 测试结果

新用例(逐条):

```
$ .venv/bin/python -m pytest -q scripts/tests/test_383_sentiment_single_root.py
....                                                                     [100%]
4 passed in 0.23s
```

- 用例 1 `test_excludes_git_repo_even_if_newer`:REPO=/tmp/trade-data(MAX 20260101)、GIT_REPO=/tmp/trade(MAX 20261231)→ 断言返回部署树库,代码仓侧"更新"也不得被选中(旧逻辑会选它)。
- 用例 2 `test_no_env_falls_back_to_pick_repo`:清空 REPO/GIT_REPO/MAIN_REPO + `monkeypatch.setattr(pick_repo, "pick_repo", lambda: chosen)` → 断言 `chosen/data/sentiment.db`。
- 用例 3 `test_explicit_repo_param_wins`:显式 repo 参数直接拼该树路径。
- 用例 4 `test_pick_db_delegates_to_single_root`:`gen_daily_brief.pick_db(repo)` 委托单源(3 调用点兼容)。
- 纪律:全部用 `monkeypatch.setenv/delenv/setattr` 自动还原,未裸写 `os.environ[...]`(L56);不依赖当前日期,无"隔天红"风险(L51);零网络零生产 DB 写。

全量(改 scripts/ 源码必跑,L52/L59),原样末行:

```
5591 passed, 6 skipped, 1 warning, 176 subtests passed in 748.55s (0:12:28)
```

独立断言面核对(L59):本次未改任何「登记类列表/计数常量」,全仓 grep `_candidate_repos` / `aggregate_shadow._pick_db` / `brief_ledger._pick_db` 无残余引用(排除 docs 历史报告);`ops/monitoring/tests/smoke_local.py` 无与本次相关的硬编码数字/长度断言。CI 静态闸门无 flake8/ruff/pyflakes 配置(已 grep `.github/workflows/`)。改动后 7 个 py 文件 `py_compile` 全过、4 个模块 `import` 全过。

## ③ 本地冒烟输出(证据用例 4)

```
$ python -c "import sys;sys.path.insert(0,'scripts');import gen_daily_brief as g;print(g.pick_db(g.pick_repo()))"
/Users/linhuichen/code/trade-data/data/sentiment.db
$ python -c "... import brief_ledger,aggregate_shadow,ab_direction_anchor,replay_direction_anchor; print('IMPORT_OK', brief_ledger._pick_db())"
IMPORT_OK /Users/linhuichen/code/trade-data/data/sentiment.db
```

= 本机部署数据树 D 路径(旧逻辑本机也选 D,故 pick 结果不变,§23.7 冻结满足);零网络、零 DB 写。

## ④ 行为变化标注(如实)

1. **库缺失/损坏时的行为变化(改善,非退化)**:旧逻辑遍历候选仓,某仓库打不开/不存在会静默跳过并对另一仓回退;D 库缺失时会静默回退到 C 或 mac 镜像(均为 20261028 起的陈旧数据,喂 1 个月旧数据)。新逻辑只返回部署数据树的路径,库缺失/损坏时由调用方 `sqlite3.connect(mode=ro)` **响亮报错**。本机与云上当前 D 库均存在且最新(本机 D=20261105,C=20261028;云上 D=20261127,C=20261028),正常路径无变化。
2. **`replay_direction_anchor.py` 手动回放**:原 `pick_db(repo)` 会在候选仓里挑最新库,即使 `repo` 是 trade/ 也可能读到 trade-data/ 的库;现在严格用 `sentiment_db(repo)`。本机无 env 时 `_pick_repo()` 返回 `REPO_ROOT`(trade/),即回放改读 `trade/data/sentiment.db`(本机该库 MAX=20261028,滞后于 trade-data 的 20261105)。**手动回放脚本的用户需注意**:想用最新库请设 `REPO=/Users/linhuichen/code/trade-data`(或云上对应路径)。这是"单源"语义的必然结果,已在脚本输入依赖段说明。
3. **`aggregate_shadow` 的 `_candidate_repos` 漂移消失**:旧实现在"只注入 MAIN_REPO、不注入 REPO/GIT_REPO"的形态下会漏掉云上数据仓(漏 MAIN_REPO + 写死 macOS 路径);现跟随 `pick_repo()`,该形态下正确落部署树。
4. **不影响既有防护**:`check_data_gap_alerts.py` 等新鲜度闸门、`app/db.py` 解析阶梯(#335/#384 范畴)均未改动。
5. **云上观察不归本 agent**:C 库 `-shm` 在 20:40/21:15 两轮后不再刷新、`[brief_ledger] repo=... db=/home/ubuntu/code/trade-data/data/sentiment.db` 日志逐字不变,由主控 merge 后做(证据用例 2/3)。

## 举一反三覆盖清单(§23.3)

- 同模式(pick_db 家族):4 定义 → 1 定义(pick_repo.sentiment_db);8 调用点全部覆核:gen_daily_brief :4117/:1674/:2188(签名保留、零改)、aggregate_shadow :162(已改)、brief_ledger :712(经 `_pick_db` 已改)、ab_direction_anchor :263/:295(已改)、replay_direction_anchor :91(已改)。
- 同数据源(sentiment.db)其他读者:`app/db.py` 解析阶梯(#335,`TRADE_SENTIMENT_DB→REPO→MAIN_REPO→兄弟仓→本仓`)、`app/alert_*`、`scripts/export_alert.py`、`collector/*` 走 `app.db.get_conn()` / 各 collector 自身 cwd 口径 —— 均不在本次改动面(调研 §4 M4/#384 另批),本次未动、未误伤。
- 同组件(repo 解析):`candidate_repos()` 保持原样(仍服务 `pick_repo()` 部署源树判定与 `fetch_news.py:86`),`check_s06_freshness.py` 的选择器是按 `static-site/data` 存在性选仓、不开 sentiment.db,不属 pick_db 家族(未动)。
- 展示位:本次纯后端读写路径收敛,不产生任何用户可见数据/展示变化(输出路径不变)。
- 待开发功能衔接:已查 `docs/pending-features-index.md` #383(本任务)/#384(REPO 路径解析,另批),无同模块并行任务冲突;未预留新接口。

## 同类错误面清单(§23.2/§6,修 bug 视角)

本次属"结构性收敛"而非修 bug,但仍按三铁律排查:①同根因面 = 所有"把 git 仓当数据仓读"的 pick_db 实现(已全删);②同类 fallback 面 = 三处 `best or <兜底>`(已全删,统一 `sentiment_db`);③同类写死路径面 = `brief_ledger` macOS 兜底、`aggregate_shadow` 两个 macOS 字面量(已删)。全仓 `scripts/` 内 `SELECT MAX(date) FROM daily_metric` 只剩带 WHERE metric_id 的正常用法(非候选遍历)。

## 边界维度清单(§5.8③ 七轴,供 reviewer §10.8 独立复核对账)

| 维度 | 测/不测 | 说明与来源 |
|---|---|---|
| 输入域(env 组合) | **测** | REPO/GIT_REPO/MAIN_REPO 三 env 齐 + 代码仓 MAX 更新(用例 1);三 env 全无(用例 2);显式 repo 参数(用例 3) |
| 状态组合(repo 选中态) | **测** | 部署树 vs 代码仓同存、代码仓更新更"新"——用例 1 覆盖关键对立态;多候选仓并存不再存在(单源) |
| 时序 | **测** | 单源后不再依赖"哪库 MAX 更大",用例 1 证明 NEWER 不生效;无日期敏感断言(不依赖 today) |
| 上下游依赖 | **测** | 4 个模块 import + `pick_db` 委托(用例 4 + 冒烟 IMPORT_OK);调用方签名兼容(3 个 gen 调用点未改、全量 pytest 覆盖) |
| 极端值 | 不测(理由) | 库缺失/损坏的"响亮报错"属新行为,单测不造损坏库(避免建非法 sqlite 文件误导),由代码语义 + sqlite3 既有报错保证;`repo=None` 已由用例 2 覆盖 |
| 回退路径 | **测** | 无 env → pick_repo(用例 2);`--db` 显式优先(brief_ledger 代码路径,全量 pytest 内既有用例覆盖);无静默回退旧库(已删) |
| 并发与重入 | 不测(理由) | 改动是纯路径计算(无 I/O、无锁、无状态写入),不存在并发分支;原 MAX(date) 只读打开才是并发/锁相关面,已被删除 |

## 未做/归主控

- 不推 main(只 push feat);不部署、不动云上;C 库 `-shm` 观察与生产日志锚点复核归主控 merge 后做。
- `docs/pending-features-index.md` #383 状态列更新归主控(任务状态单一事实源,§23.12-1)。
- #384(M4/M6 等 REPO 解析统一)不在本批。
