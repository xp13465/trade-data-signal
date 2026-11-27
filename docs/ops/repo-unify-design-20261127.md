> 归档自 /tmp/repo-unify-design-20261127.md,2026-11-27;原始路径为临时文件,本副本为持久归档

# #384 REPO 路径解析统一口径方案(设计,只读产出)

- 任务书:`/tmp/task-repo-unify-design-20261127.md`
- 依据:`/tmp/repo-paths-research-20261127.md` §4(全景清单;本报告已抽查复核并订正)
- 代码基线:`main@192691ab3`(#383 已合入)
- 取数时点:2026-11-27 13:15-14:20 CST;全程只读(本机 grep/读文件/python 只读实验;云上仅 readlink/ls/stat/systemctl cat)
- 产出性质:纯设计,未改任何代码/unit/云上文件

---

## 0. 复核结论与 §4 清单订正(证据)

### 0.1 抽查复核(≥3 条,全部通过或订正)

| # | 复核项 | 结论 | 证据 |
|---|---|---|---|
| 1 | **absolute vs resolve 分叉**(§4.2-4) | **确认** | 本机同一 `app/db.py`,经 `trade-data` 路径 import → `_HERE=/Users/linhuichen/code/trade-data`;经 `trade` 路径 import → `_HERE=/Users/linhuichen/code/trade`(`.absolute()` 保留 symlink,`.resolve()` 折叠)。命令:两个 `PYTHONPATH=... python -c "import app.db as d;print(d._HERE)"` |
| 2 | **代码仓被当数据候选**(§4.2-1) | **确认** | `scripts/pick_repo.py:44-45` 把 `REPO/GIT_REPO/MAIN_REPO/GIT_REPO_DEFAULT` 全塞进 `candidate_repos()`;`GIT_REPO_DEFAULT=resolve(__file__).parent.parent`(:35)恒落 C。实测经 `trade-data/scripts` import 后 `candidate_repos=[trade-data, trade]` |
| 3 | **云上 unit env 不齐**(§4.2-7) | **确认** | 云上 61 个带 `ExecStart` 的 service;`REPO` 46 / `GIT_REPO` 43 / `MAIN_REPO` 43;缺 MAIN_REPO 恰为 5 个:`trade-fof-nav-backfill` / `trade-fof-nav-collect` / `trade-ops-monitor` / `trade-simtrade-export` / `trade-sim-trade@`(这 5 个也同时缺 GIT_REPO) |
| 4 | **绝对路径直写**(§4.2-8) | **确认** | `trade-sim-trade@.service` 无 REPO env,`ExecStart` 用 `sh -c` 写死 D/C 全部绝对路径 |
| 5 | **云上布局 D(数据实体)/C(代码 symlink)**(§2.2) | **确认** | `trade-data/scripts -> trade-data-signal/scripts`,`app` 同;`trade-data/data`、`static-site` 为实体目录;C 的 `static-site` 也是实体目录(自带 data 镜像) |
| 6 | shell 写死 mac 默认值(§4.2 附注) | **确认(仅 /Users 口径)** | 全仓 `${REPO|GIT_REPO|TRADE_DIR:-/Users/...}` = **0 处**;但漏了 `/home` 口径(见 0.2 新增项) |

### 0.2 对 §4 清单的订正(如实)

| # | §4 原文 | 实测 | 处理 |
|---|---|---|---|
| C1 | M2「6 个 .py import pick_repo」 | **7 个**:gen_daily_brief / brief_ledger / aggregate_shadow / ab_direction_anchor / replay_direction_anchor / fetch_news / **overfit_monitor** | 以 7 为准 |
| C2 | M5「36 个非测试 py 含 `os.environ.get("REPO"`」 | 双引号 33 个;单双引号合计 35 个;REPO/GIT_REPO/MAIN_REPO 三键合计 **40 个** | 以 40(三键)/35(REPO)为准 |
| C3 | M6「resolve().parent.parent 48 文件」 | **49** 文件 | 以 49 为准;157/87/12/裸 3 项均复核一致 |
| C4 | §4.2-1 行号「pick_repo.py:43-44」 | 实际候选元组在 **:44-45** | 行号订正 |
| C5 | §4.2-5 行号「app/db.py:247 本仓 data」 | 「本仓 data」候选 append 在 **:239**;:247 是去重循环尾 | 行号订正 |
| C6 | §4.2-2「aggregate_shadow 漂移」 | **#383 已修**:`_pick_db/_candidate_repos` 已删,`aggregate_shadow.py:162` 直接 `sentiment_db(repo)` | 移出未决项 |
| C7 | §4.2-3「brief_ledger:128 写死 mac 兜底」 | **#383 已修**:`brief_ledger.py:107-111` 已改 `explicit or sentiment_db()`,无 mac 兜底 | 移出未决项 |
| C8 | §4.2-6「deploy.sh:744 注释与事实冲突」 | **#383 已修**:`deploy.sh:742-746` 已改写为「#383 收敛后代码仓 data/*.db 零读取方」 | 移出未决项 |

### 0.3 新增发现(§4 未列)

1. **第 9 条不一致(真缺陷):`scripts/simtrade_export_publish.sh:14-15` 写死 Linux 绝对路径且完全绕过共享 lib**
   `REPO=${REPO:-/home/ubuntu/code/trade-data}` / `CODE=${CODE:-/home/ubuntu/code/trade-data-signal}`,文件**不 source `repo_paths.sh`**。现状在云上因路径正好正确而能跑,但:①仓名/布局一改即断;②mac 上裸跑永远指向不存在的 /home;③它是全仓唯一 `/home` 默认值文件(§4 的「shell 已收口」只测了 `/Users`)。
2. **同类重复解析器未在 §4 单列**:`scripts/check_data_integrity.py:968-990 _db_candidates` 与 `scripts/check_s06_freshness.py:51-58 DEFAULT_REPO_CANDIDATES` 都自建「env REPO/GIT_REPO + mac 默认」候选列表,与 `pick_repo.candidate_repos` 同病(把代码仓当数据候选)。
3. **正面样板(不要动)**:`scripts/ops_monitor.py:95-96` 显式区分 `code_root=C` / `data_root=D`,数据读 `cfg.data_root`(:623/651/803/829/838/865/881),代码读 `cfg.code_root`(:608/899)。这是目标口径的现成范例。

---

## 1. 目标口径(一句话 + 可执行规则)

### 1.1 一句话

**「代码根」与「数据根」两个语义各自只有一个权威解析入口:bash 全走 `scripts/lib/repo_paths.sh:resolve_repo`(REPO=数据根 / GIT_REPO=代码根),python 全走 `scripts/pick_repo.py`(新增 `data_root()`/`code_root()`;`pick_repo()`/`pick_git_repo()` 保留为「写/上传」与「git 操作」入口,`sentiment_db()` 及所有数据读者只经 `data_root()`);任何自解 env、`__file__` 派生、unit 硬编码都必须先声明自己属于哪个根并委托给它,不许自解析。**

### 1.2 两个语义(定义 + 判据)

| 语义 | 别名(现状) | 唯一入口 | 判定规则 | 当前落点 |
|---|---|---|---|---|
| **数据根 DATA_ROOT** | `REPO`、`MAIN_REPO`(部分)、`STATICDATA_REPO`(历史)、`D` | bash `REPO` / py `data_root()` | env `REPO` 有效目录 → 用之(带守卫,见 1.4);否则按 1.3 派生 | 云 D=`/home/ubuntu/code/trade-data`;mac `trade-data` |
| **代码根 CODE_ROOT** | `GIT_REPO`、`CODE`、`OPS_CODE_ROOT`、`TRADE_DIR` | bash `GIT_REPO` / py `code_root()` | env `GIT_REPO` 有效目录 → 用之;否则 `resolve(__file__).parent.parent` | 云 C=`/home/ubuntu/code/trade-data-signal`;mac `trade` |

**归类判据(一句话)**:路径后面要拼 `data/`、`static-site/data/`、`logs/`、DB 文件、R2 上传源 → 数据根;要拼 `scripts/`、`app/`、`docs/` 等源码/可执行文件、或做 git 操作 → 代码根。**同一文件两种用途必须分别取对应根,不许一个变量兼任。**

### 1.3 派生算法(python 与 bash 严格同构,直接复用 `repo_paths.sh:60-68` 的 A/B 候选)

```
CODE_ROOT    = Path(__file__).resolve().parent.parent          # C(恒折叠 symlink)
INVOKED_ROOT = Path(__file__).absolute().parent.parent          # 经 D/scripts symlink 调用时 = D

数据根 =
  ① env REPO 有效目录(且通过 1.4 守卫)
  ② 候选 A:INVOKED_ROOT 且 (INVOKED_ROOT/"scripts").is_symlink() 且 INVOKED_ROOT != CODE_ROOT
            → INVOKED_ROOT(= D)
  ③ 候选 B:CODE_ROOT.parent/"trade-data" 是目录 → 该兄弟目录(= D)
  ④ 真单仓:CODE_ROOT 本身(= C)
```

- 与 bash 完全同构(候选 A 的 `-L scripts` 前提取自 `repo_paths.sh:60` 的 #208 修正,防「祖先 symlink 误判」)。
- 已用合成布局验证:A(D/scripts→C/scripts symlink)、B(经 C 直接调用)、单仓(无兄弟)三形态均返回正确值(见附录 B-3)。
- **不再是「按 overview.json 日期猜最新」**:日期猜测只是 `pick_repo()` 的写侧历史算法(冻结不动);数据根改由布局确定性推导,消除「代码仓 overview 更新就被选中」的误判面。

### 1.4 env REPO 的读侧守卫(复用写侧同款语义,不新造)

- 规则:**若 `env REPO` 解析到 `CODE_ROOT`,且存在独立部署树(派生数据根 ≠ CODE_ROOT),判定为错配 → 响亮失败(SystemExit + 与 `guard_deploy_source_tree` 同款告警文案)**;真单仓(无独立部署树)允许 `REPO == CODE_ROOT`。
- 复用现状:`scripts/pick_repo.py:145-172 guard_deploy_source_tree` 已实现同一判据(实测:REPO=C + 独立 D → SystemExit;REPO=D → 放行)。读侧只需调用它,不新增判据。
- **为什么不 warn 放行**:warn 仍然读到陈旧库(云上 C 的 `sentiment.db` MAX=20261028,D=20261127),等于「静默用坏数据」保留;§23.11 要求发现问题绝不静默。硬失败的代价是 unit 进 failed,`check_failed_units.py` 15 分钟内告警,可发现、可修。

---

## 2. 分批改造清单(5 批;先堵错,再收编长尾)

### 2.0 总表

| 批 | 优先级 | 范围 | 一句话改法 | 实现预期(X→Y) | 证据用例 | 独立回退 |
|---|---|---|---|---|---|---|
| **1** | P0 | `scripts/pick_repo.py` + 新建 `scripts/tests/test_384_data_root_contract.py` | 加 `code_root()/data_root()`(1.3 算法)+ `MAIN_REPO` 默认改派生 + `sentiment_db()` 走 `data_root()` + 读侧守卫;修 #383 遗留两项 | Linux 无 env:pick 从 C(陈旧 MAX 20261028)→ D;env REPO=C 错配:从静默读 C → SystemExit;现网 REPO=D 逐字不变 | 见 2.1 | 单 commit revert |
| **2** | P0 | `app/db.py` + 新建 conformance 用例 | `_HERE` 改为复用 `pick_repo.data_root()/code_root()` 派生,阶梯收敛为「TRADE_SENTIMENT_DB → data_root()/data/sentiment.db」 | 同一模块经 C/D 两条 import 路径解析结果一致(消除 absolute vs resolve 分叉);错配 REPO=C 从静默 C → SystemExit;健康场景路径逐字不变 | 见 2.2 | 单 commit revert |
| **3** | P1 | `scripts/simtrade_export_publish.sh`、`docs/deploy/systemd-units-20260912.md`(5 unit)、`docs/ops/systemd/trade-sim-trade@.service`、新建 `scripts/check_unit_repo_env.py` | 修第 9 条(simtrade 接 lib);5 unit 在**文档源**补 REPO+GIT_REPO;别名登记;新增 unit env 审计器 | simtrade 无 env 时也能自愈(REPO=D/GIT_REPO=C);unit env 审计从「无」→ 可机检 PASS/FAIL + 例外表;云上行为不变 | 见 2.3 | 脚本单 commit;unit 改动云上备份后单独回滚 |
| **4** | P1 | 40 个自解 env 的 py(33 数据型/7 代码型;其中 4 个写死 mac 默认) | 4 个 mac 默认先清零;33 个数据型生产可达者委托 `data_root()`;7 个代码型只加注释声明;docs/ 下属 dev-only 声明不改 | `grep 'os.environ.get("REPO", "/Users'` 从 4 → 0;重复候选列表(check_data_integrity / check_s06_freshness)收敛到单源 | 见 2.4 | 按文件组回退 |
| **5** | P2 | 42 个「`__file__` 派生 → 拼 data」py + 新建 `scripts/check_py_repo_paths_ratchet.py` + CI 挂载 | 生产可达者逐个委托;其余登记 allowlist;新增棘轮「新增自派生数据路径即 FAIL」并挂 CI | 42 长尾可枚举可收缩;新脚本再写 `Path(__file__).../"data"` 从「无人拦」→ CI FAIL | 见 2.5 | 棘轮先 warn 后阻断;代码改动按模块回退 |

> 批与批之间无代码依赖;唯一顺序约束:批 2 依赖批 1 的 `data_root()` 存在,批 5 的棘轮 allowlist 以批 4 完成后的清单为基线。每批一个 feat 分支、一个 commit,merge 走 `scripts/main-merge.sh`。

### 2.1 批 1(P0):python 数据根单源 + #383 遗留两项

**改谁 / 怎么改**
- `scripts/pick_repo.py`:
  - 新增 `code_root()`(即现 `pick_git_repo()` 的 body 抽名,保持 `pick_git_repo()` 兼容)。
  - 新增 `_derive_data_root(code_root, invoked_root) -> Path` 纯函数(1.3 算法,A 候选要求 `<invoked>/scripts` 是 symlink)。
  - 新增 `data_root()`:env `REPO` → 校验(1.4 守卫)→ 否则 `_derive_data_root(...)`。
  - `MAIN_REPO`(:33)由「写死 mac 路径」改为「env `MAIN_REPO` 或派生数据根」;`candidate_repos()`(:38-51)与 `pick_repo()`(:64-88)选中算法**一字不动**。
  - `sentiment_db()`(:91-100)默认从 `pick_repo()` 改 `data_root()`(显式传 repo 时仍拼该树,兼容 `pick_db(repo)` 3 个调用点)。
- 新建 `scripts/tests/test_384_data_root_contract.py`(零网络、全 tmp_path)。**注意:任何触发守卫的用例必须 `monkeypatch.setattr(pick_repo, "_alert_guard_blocked", lambda m: None)`,否则会发真实告警(L48,本次已踩,见 §6)**。

**实现预期(可观测 X→Y)**

| # | 场景(可复现) | 改前实测 | 改后预期 |
|---|---|---|---|
| 1 | Linux 形态:无 REPO/GIT_REPO/MAIN_REPO,D/scripts→C/scripts symlink | 本机仿真 `MAIN_REPO=/nonexistent` 时 `pick_repo()=/Users/linhuichen/code/trade`,`sentiment_db()=trade/data/sentiment.db`(MAX **20261028**) | `pick_repo()=D`,`sentiment_db()=D/data/sentiment.db`(D MAX 最新) |
| 2 | env REPO=C、GIT_REPO=C、MAIN_REPO=D(独立 D 存在) | `sentiment_db()=trade/data/sentiment.db` 静默(实测) | `SystemExit`(loud),文案含「解析到 git 仓…而非部署源树」 |
| 3 | env REPO=D(现网) | D | D 逐字不变 |
| 4 | 单仓(无 D、无 env) | C | C 不变 |
| 5 | `sentiment_db()` 调用点(5 处生产读者) | 返回值 | 返回值不变(现网 D) |

**证据用例(事先写定、可独立复现)**
1. `pytest -q scripts/tests/test_384_data_root_contract.py -v` 全绿,含:
   - `test_derive_candidate_a_symlink` / `test_derive_candidate_b_sibling` / `test_derive_single_repo`;
   - `test_env_repo_data_tree_wins`;
   - `test_env_repo_code_repo_two_tree_raises`(**stub `_alert_guard_blocked`**);
   - `test_sentiment_db_follows_data_root`;
   - `test_main_repo_default_not_mac_literal`(断言模块默认值不含 `/Users/`)。
2. 本机 smoke:`env -u REPO -u GIT_REPO -u MAIN_REPO PYTHONPATH=<repo>/scripts python -c "import pick_repo as p;print(p.data_root(),p.sentiment_db())"` → 打印 D。
3. 现网行为锚点(改前已固化):`grep -a "\[brief_ledger\] repo=" trade-data/data/logs/daily_brief.log | tail -1` 的 `db=` 仍为 D 路径。
4. 云上只读:`stat -c '%Y %s' C/data/sentiment.db-shm` 在 20:40/21:15 两轮后不变(#383 已成立,批 1 不得回退)。

**边界 / 不改**
- 不动 `candidate_repos()`、`pick_repo()` 的日期选择算法、`guard_deploy_source_tree` 判据、`force_env`。
- 不动 `fetch_news.py` 的写路径(它消费 `candidate_repos`,见 §3)。

### 2.2 批 2(P0):`app/db.py` 阶梯收口(absolute vs resolve 分叉)

**改谁 / 怎么改**
- `app/db.py:9 _HERE` 删除,改为从 `pick_repo` 取根:
  - `_CODE_ROOT = Path(__file__).resolve().parent.parent`;`sys.path.insert(0, str(_CODE_ROOT/"scripts"))`;`from pick_repo import code_root, data_root`(pick_repo 只依赖标准库,无循环)。
  - `resolve_db_path()` 阶梯收敛为:`TRADE_SENTIMENT_DB`(最高优先,语义不变)→ `data_root()/"data"/"sentiment.db"`。
  - `DB_PATH` 哨兵与 monkeypatch 口(:17-18、:273-274、:320)完全保留。
- 保留 `_db_candidates()` 名称但内部只调 `data_root()`(或删除并同步调用方;调用方只有本文件)。
- 新建 `scripts/tests/test_384_app_db_contract.py`,含**跨实现一致性用例**:同一组 env/布局下,`pick_repo.data_root()` 与 `app.db` 解析出的库路径必须相等(或同一条错配路径都 raise)。

**实现预期(可观测 X→Y)**

| # | 场景 | 改前 | 改后 |
|---|---|---|---|
| 1 | 经 D 导入 `app.db`(`export.py` 实跑路径) | `_HERE=D` → D | D 不变 |
| 2 | 经 C 导入、无 env、mac 双仓 | `_HERE=C` → 阶梯④ sibling D → D | D 不变 |
| 3 | 经 C 导入、单仓无 D | `_HERE=C` → 阶梯⑤ 本仓 C | C 不变 |
| 4 | env REPO=C + 独立 D | 阶梯② 命中 C,静默读陈旧库 | `SystemExit`(与批 1 同文案) |
| 5 | `TRADE_SENTIMENT_DB` 显式指定 | 用它/无效则报错 | 完全不变 |
| 6 | `monkeypatch DB_PATH` | 尊重 | 完全不变 |

**证据用例**
1. `pytest -q scripts/tests/test_384_app_db_contract.py -v` 全绿(含上表 6 场景)。
2. 真实布局实测:两个 `PYTHONPATH`(D/C)各跑一次 `python -c "from app.db import resolve_db_path;print(resolve_db_path())"`,结果**必须相同**(现网 env 正确时应均为 D)。
3. 调用方冒烟:`scripts/export_alert.py` / `app/alert_match.py` / `app/alert_score.py` / `scripts/detect_intraday_anomaly.py` 的 import + 只读解析路径,不连生产库(用 tmp fixture)。
4. 全量 `pytest -q scripts/tests/`(L52/L59:改 scripts/app 源码必跑全量)。

**边界 / 不改**
- 不建空库 (#335 语义)、不改 `TRADE_SENTIMENT_DB` 优先级、不改 `get_conn()` 建表迁移。
- 不在 `app/db.py` 里重新实现派生算法(必须调 `pick_repo`,否则又成第二份实现)。

### 2.3 批 3(P1):bash / systemd unit env 面

**改谁 / 怎么改**
- `scripts/simtrade_export_publish.sh`:删 :14-15 两条 `/home` 默认,改为两行模板 `source .../lib/repo_paths.sh || exit 2` + `resolve_repo "${BASH_SOURCE[0]}"` + `CODE="$GIT_REPO"`(保留 `$CODE` 变量名给下文,零语义变化);`REPO` 由 lib 赋值。
- `docs/deploy/systemd-units-20260912.md`(unit 唯一文档源,`gen_systemd_units.py --check` 实测可解析 94 个 unit):
  - 5 个缺 env 的 unit 补齐 `Environment=REPO=…` + `Environment=GIT_REPO=…`(:1773 fof-collect、:1811 fof-backfill、:1857 ops-monitor、:1932 simtrade-export;sim-trade@ 单独处理)。
  - 别名统一登记:`OPS_CODE_ROOT`/`CODE`/`TRADE_DIR` 映射到代码根,逐步改为 `GIT_REPO`(先登记、后改名,避免一把梭)。
  - `trade-sim-trade@`(文档源 `docs/ops/systemd/trade-sim-trade@.service`):**冻结为已知例外**,不改成 env(改收益低、风险高),由检查器列例外。
- 新建 `scripts/check_unit_repo_env.py`(只读审计):
  - R1 执行 `.sh` 的 unit:要么 REPO+GIT_REPO 齐,要么该脚本 source lib + resolve_repo(推导证明);
  - R2 直调 python 的 unit:必须 REPO+GIT_REPO(或例外表);
  - R3 别名/绝对路径 → 例外表逐条登记(条目只减不增);
  - R4 恒在自检(防 L49 空转:喂一个标准坏样本必须 FAIL)。
  - 支持 `--units-dir`(CI 用 fixture)/ 默认 `/etc/systemd/system`(云上只读跑)。
- 云上落 unit:单独 ops 步骤,改动前 `cp <unit> <backup>` + `systemctl daemon-reload`;文档源与云上实际 unit **两处同步**(§22/L54 同精神)。

**实现预期(X→Y)**

| # | 场景 | 改前 | 改后 |
|---|---|---|---|
| 1 | `simtrade_export_publish.sh` 无 env 裸跑 | 依赖 `/home/...` 硬编码(云上碰巧对,mac 必错) | lib 推导 REPO=D/GIT_REPO=C,两机都对 |
| 2 | `grep -rn '${REPO:-/home/' --include=*.sh` | 1 文件 2 行 | 0 |
| 3 | 5 个 unit | 缺 MAIN_REPO/GIT_REPO;FOF 靠 lib 自愈、ops-monitor 用别名、sim-trade@ 全绝对 | 文档源补齐 REPO+GIT_REPO;sim-trade@ 登记例外;检查器 PASS |
| 4 | unit env 审计 | 无机制 | `check_unit_repo_env.py` PASS/FAIL + 例外表;变异自测真响 |

**证据用例**
1. `bash -n scripts/simtrade_export_publish.sh` + 本机 `env -u REPO -u GIT_REPO bash -c 'source lib; resolve_repo ...; echo $REPO $GIT_REPO'` → D / C。
2. `python3 scripts/check_unit_repo_env.py --units-dir scripts/tests/fixtures/units` → PASS;`--selftest` 变异(把某 unit env 删掉)→ FAIL。
3. 云上只读:`python3 scripts/check_unit_repo_env.py`(默认 /etc/systemd/system)输出 PASS(改后)对照 FAIL 清单(改前,已固化为 5 unit + 1 绝对路径例外)。
4. `python3 scripts/gen_systemd_units.py --check <tmp>` 仍可解析、无语法破坏。
5. 云上 `systemctl cat <unit>` diff = 只增 env 两行;`systemctl show -p Environment` 核实生效。

**边界 / 不改**
- 不改 unit 的时点(`OnCalendar`)、`ExecStart` 路径、`Condition*`;只补 env。
- 不改 `trade-sim-trade@`(例外);不改 `ops_monitor` 的 code_root/data_root 配置(正面样板)。

### 2.4 批 4(P1):40 个 py 自解 env 收编

**范围与分类(实测)**
- 40 个非测试 py 读 `REPO/GIT_REPO/MAIN_REPO`;其中 **33 个**文件含数据路径字面量(候选数据型),**7 个**无(候选代码型:build_min / with_lock / backup_source_proof / backfill_direct_metrics / check_version_consistency / us_stock_morning / check_large_json_excluded)。
- **4 个写死 mac 默认(先修)**:
  `a-stock-data/backtest_strategies.py:23`、`scripts/fapi_bj_width_export.py:53`、`scripts/check_data_gap_alerts.py:137`、`scripts/backfill_direct_metrics.py:49`。
- 重复候选列表(check_data_integrity:968-990、check_s06_freshness:51-58)归入本批收敛。

**改谁 / 怎么改**
- 4 个 mac 默认:改为 `pick_repo.data_root()`(或显式 `os.environ.get("REPO") or str(data_root())`),**禁止**再写死任何机器路径。
- 33 个数据型:逐个判「生产可达?」(被 unit/ExecStart/cron/CI 调用) → 可达者委托 `data_root()`;不可达的 docs/ 分析脚本标 `dev-only` 不改。
- 7 个代码型:若确实只用于代码根,改注释声明「本文件只取代码根」,不强行改逻辑。
- 每文件改动配最小 import smoke(不连库、不联网)。

**实现预期(X→Y)**

| # | 观测 | 改前 | 改后 |
|---|---|---|---|
| 1 | `grep -rn 'os.environ.get("REPO", "/Users' --include=*.py` | 4 文件 | 0 |
| 2 | check_data_integrity / check_s06_freshness 候选来源 | 各自复制(含代码仓) | 单源 `data_root()` |
| 3 | 云上无 env 时(极端) | 落 mac 不存在路径/代码仓 | 落派生数据根或响亮报错 |

**证据用例**
1. 上面 grep = 0。
2. 每改一个文件跑 `python -c "import <mod>"`(或对应 `--help`)不报错。
3. `pytest -q scripts/tests/` 全量绿。
4. 云上只读抽查 2 个高频检查器(`check_data_integrity.py` / `check_s06_freshness.py`)在 unit env 下解析到的库 = D。

**边界 / 不改**
- `docs/`、`a-stock-data/` 下的纯研究脚本若未进生产链,只标 dev-only,不强行改造(避免无谓改动)。

### 2.5 批 5(P2):42 个「`__file__` → data」长尾 + 棘轮挂 CI

**范围(实测 AST)**:42 个非测试 py 从 `__file__` 派生根再拼 `data`(含 app/db.py、export.py、upload_r2.py、gen_daily_brief.py、nextday_plan_generator.py、check_signals.py、daily_summary_email.py 等;清单见附录 A)。

**改谁 / 怎么改**
- 按模块族分批走:①告警/邮件族 ②导出/上传族 ③回测/分析族 ④docs/ dev-only。生产可达者改为委托 `data_root()`/`code_root()`;确认只用于代码根的(如读 `docs/`、`scripts/` 资源)登记 allowlist 并注释。
- 新建 `scripts/check_py_repo_paths_ratchet.py`:
  - R1:新增「`__file__` 派生根 + 拼 `data`」的**生产侧** py 且不在 allowlist → FAIL;
  - R2:allowlist 只减不增(每批收缩);
  - R3:恒在自检(标准坏样本必须命中)+ `--selftest` 变异(改一个样本为旧形态必须 FAIL,§18 L49 防空转)。
- CI 挂载:按 `memory gate-mount-decision-ci-only`(命令路径与 CI step 显式相交),在 `ci.yml` 增一步跑 ratchet;pytest wrapper 同步(`scripts/tests/test_py_repo_paths_ratchet_pytest.py`),借现成 `pytest -q scripts/tests/`(ci.yml:177-189)兜底。

**实现预期(X→Y)**

| # | 观测 | 改前 | 改后 |
|---|---|---|---|
| 1 | 42 文件 | 各自推导,无法枚举 | allowlist 全量登记 + 每批收缩 |
| 2 | 新脚本写 `Path(__file__).parent.parent/"data"` | 无人拦 | CI ratchet FAIL |
| 3 | 棘轮自测 | 无 | `--selftest` 变异真响 + 负对照 PASS |

**证据用例**
1. `python3 scripts/check_py_repo_paths_ratchet.py` → PASS;`--selftest` → rc=0(含负对照 + 变异 FAIL 两断言)。
2. CI 首跑日志:新增 step 绿;故意在分支加一行坏样本 → CI 红(一次性验证,合入前删除)。
3. `pytest -q scripts/tests/` 全量绿。

**边界 / 不改**
- docs/analysis 脚本 dev-only 不进棘轮 allowlist 的「生产侧」,只登记不判 FAIL。
- 棘轮先 `continue-on-error` 观察 1-2 周再转阻断(参考 ci.yml ⑫ L51 步的观察期做法)。

---

## 3. 冻结面声明(哪些不动 + 动了的代价)

| 冻结对象 | 位置 | 为什么不动 | 硬动的代价 |
|---|---|---|---|
| `pick_repo()` 部署源树选中算法(overview 日期严格大于) | `pick_repo.py:64-88` | 写/上传/staticdata 同步的既有契约;换算法会改变「写哪棵树」,引发 clobber(#2026-08-18 根因) | 部署链写错树/反覆盖线上 |
| `candidate_repos()` 列表构成 | `pick_repo.py:38-51` | `fetch_news.py:86` 直接消费;`pick_repo()` 与写侧判定共用 | 新写路径错位/单仓判定失效 |
| `repo_paths.sh:resolve_repo` 推导 + assign-not-export 契约 | `repo_paths.sh:43-110` | 68 个 shell 已全量迁移且有 T1-T7 单测;生产靠它自愈 | 全 shell 面同时回归,爆炸半径最大 |
| `fetch_news.py` 新闻写路径 | `fetch_news.py:76-90,652-661` | 与 #195 批1 已收口;其 MAIN_REPO 常量注释已标「仅文档锚点」 | 新闻写错树 |
| `deploy.sh` REPO/GIT_REPO 分工与 export | `deploy.sh:24-26` | 唯一把两语义写清楚的样板(§4 M8) | 部署/上传源错位 |
| `app/db.py` `DB_PATH` 哨兵 + `TRADE_SENTIMENT_DB` 最高优先 | `app/db.py:17-18,273-285` | 测试 fixture 与显式指定口的兼容契约 | 测试大面积假失败/无法指定库 |
| `ops_monitor` code_root/data_root 显式分离 | `ops_monitor.py:95-96` | 已是目标口径正面样板 | 监控读错树 |
| `trade-sim-trade@.service` 绝对路径 | `docs/ops/systemd/` + 云上 | 云上单点、路径稳定;改成 env 收益低、需改模板参数 | 改仓名时才会断;登记例外 + 检查器盯 |
| docs/ 纯研究脚本 | `docs/**/scripts/*.py` | 不进生产链 | 无 |

**为修 #383 遗留而必须动的两处(已限定范围,不算破冻结)**:`MAIN_REPO` 模块级默认值(仅「mac 字面量 → 派生」,mac 上取值完全相同);`sentiment_db()` 默认入参(`pick_repo()` → `data_root()`;现网两者同为 D)。

---

## 4. 风险与回退 + 总闸门

### 4.1 最大风险(按影响排序)

1. **严格守卫把「静默读旧库」变成「unit 硬失败」**(批 1/2)。
   - 触发条件:某 unit 的 `REPO` 实际指向代码仓。现网已核实 `trade-daily-brief` / `trade-ab-direction-anchor` 均为 REPO=D,预期不触发;但这是**行为变化**,必须用户知情。
   - 缓解:①merge 放 23:00 后安全窗口,避开 15:35/16:00/17:50/20:35/22:00;②上线后观察**一个完整交易日**(20:40 主链 + 21:15 ab-anchor);③观察锚点 = `daily_brief.log` 的 `[brief_ledger] repo=` 仍为 D + `journalctl -u trade-daily-brief` 无 SystemExit;④异常立即 `git revert` 批 1/2 + 云上 pull。
2. **派生依赖「兄弟目录名 trade-data + 调用路径」**:自定义布局(部署树不叫 trade-data、也不经 symlink 调用)会退回代码根。
   - 缓解:env `REPO` 仍最高优先;批 5 棘轮 + 批 3 检查器把「解析到代码根」显式暴露;文档写死布局前提。
3. **`app/db.py` 引入 `scripts/pick_repo` 的 sys.path 耦合**。
   - 缓解:pick_repo 仅标准库依赖;加循环导入 smoke;conformance 用例覆盖 C/D 两条 import 路径。
4. **unit 定义三副本漂移**(文档源 `docs/deploy/systemd-units-20260912.md` / `docs/ops/systemd/*.service` / 云上 `/etc/systemd/system`)。
   - 缓解:批 3 用 `gen_systemd_units.py --check` + 新检查器做「文档源 vs 云上实际」对账(只读);改 unit 前备份 + `daemon-reload` 后 `systemctl show -p Environment` 核实。
5. **42 长尾里有隐藏数据读者**:分批按模块族、每批跑全量 pytest + 云上只读抽查,不一次性大改。

### 4.2 回退

- 每批 = 一个 feat 分支 + 一个 commit;回退 = `git revert <batch commit>`(批 1/2 无数据迁移、无状态写,纯代码)。
- 批 3 的云上 unit 改动:改前 `cp` 备份到数据树 logs 目录,回退 = 恢复备份 + `daemon-reload`;脚本改动随 feat 回退。
- 批 4/5:按文件组 commit,可单组 revert;棘轮 allowlist 只减不增,回退时同步恢复 allowlist 条目。

### 4.3 总闸门(验收必过)

| 闸门 | 内容 | 落点 |
|---|---|---|
| 单测/回归 | `pytest -q scripts/tests/` 全量(新用例自动收集,ci.yml:177-189) | 本机 + CI |
| 跨实现一致性 | `pick_repo.data_root()` == `app.db` 解析结果(same env/layout) | 批 2 用例 |
| 棘轮 | shell 既有 ratchet + 新 py ratchet(`--selftest` 变异真响) | CI-only 挂载 |
| 冻结核对 | 现网 pick 结果/日志路径逐字不变;C `sentiment.db-shm` mtime 不变 | 云上只读 |
| 一致性 | unit 文档源 vs 云上实际 env 对账 | 批 3 检查器 |
| 上线 | 走 `scripts/main-merge.sh`;上线后按 §0 三查(commit/数据层/前端无关可略) | 主控 |

---

## 5. #383 遗留两项修法(纳入批 1)

### 5.1 遗留 A:env `REPO` 指向代码仓的「伪单仓」形态

- **现状实测(本机)**:`REPO=/Users/linhuichen/code/trade GIT_REPO=trade MAIN_REPO=trade-data` → `pick_repo()=trade`,`sentiment_db()=trade/data/sentiment.db`(MAX **20261028**,陈旧),**无任何提示**。
- **修法**:`data_root()` 对 env REPO 调 `guard_deploy_source_tree`(现成判据):
  - `REPO==CODE_ROOT` 且独立部署树(D)存在 → `SystemExit`(loud),文案沿用「解析到 git 仓…而非部署源树」;
  - 真单仓(无独立 D)→ 允许 `REPO==CODE_ROOT`。
- **实现预期**:上表情景 2:静默 C → SystemExit;单仓仍 C。
- **证据用例**:`test_env_repo_code_repo_two_tree_raises`(stub 告警)+ 本机 scenario 重跑;单仓合成布局 `test_single_repo_repo_equals_code_root_ok`。

### 5.2 遗留 B:Linux 无 env 时 `MAIN_REPO` 默认落代码仓

- **现状实测**:`MAIN_REPO=Path(os.environ.get("MAIN_REPO", "/Users/linhuichen/code/trade-data"))`(`pick_repo.py:33`)。Linux 上该路径不存在;`candidate_repos()` 变成 `[不存在, C]`;`pick_repo()` 因 `C/static-site/data/overview.json` 存在而选中 **C** → `sentiment_db()=C/data/sentiment.db`(陈旧,静默)。本机仿真 `MAIN_REPO=/nonexistent` 已复现:`pick_repo=/Users/linhuichen/code/trade`。
- **修法**:`MAIN_REPO` 默认值改为 `_derive_data_root(CODE_ROOT, INVOKED_ROOT)`(1.3):
  - 云上经 D/scripts 调用 → D;经 C 调用 → 兄弟 trade-data → D;
  - 真单仓 → C;
  - env `MAIN_REPO` 仍最高优先(不改语义)。
- **实现预期**:Linux 无 env → `pick_repo()=D`,`sentiment_db()=D/data`(MAX 最新);mac 无 env 与现状逐字相同(D)。
- **证据用例**:`test_main_repo_default_not_mac_literal` + 合成 Linux 布局用例 + 本机 `env -u ...` smoke。

---

## 6. 自查事故与后续验证纪律(诚实标注,L48)

- **事故**:2026-11-27 14:05:43,设计复核阶段为验证「读侧守卫可复用」,直接调用了 `pick_repo.guard_deploy_source_tree()`(misconfig 场景),该函数内部经 `_alert_guard_blocked()` 调 `scripts/notify.py --severe`,**真实发出一次 critical 告警**。
- **证据(保留不删,L48)**:`data/alerts/alert_ledger.jsonl` 14:05:43 记录 `key=e1cb0973ca84, tier=critical, channels={email:true,feishu:true}, subject="[防再犯E守卫] 写部署源树目标错误(SystemExit 阻断)"`;`data/alerts/latest.md` 有 `## [severe] 2026-11-27 14:05:43` 条目。
- **教训落地**:①任何验证守卫/告警路径的用例**必须先 stub `_alert_guard_blocked`**(批 1/2 用例已写入该要求);②本次告警内容对应的是一个**手工构造的错配 env**,不是生产故障,可忽略,但按规范不删除记录。

---

## 附录 A:42 个「`__file__` → data」文件清单(AST 实测)

```
app/alert_match.py, app/alert_score.py, app/collector/gold_night.py, app/collector/public_fund.py, app/db.py,
docs/ai-predict/scripts/analyze_direction_anchor_52.py, docs/ai-predict/scripts/backtest_direction_anchor.py,
docs/kelly/analysis/scripts/sim_window_loss_mining_20260822/longline_dd_table.py,
docs/kelly/backtest-ai/etf-weight-leader/scripts/signal_kelly_backtest_stock.py,
docs/kelly/backtest-ai/etf-weight-leader/scripts/stock_daily_backfill.py,
scripts/_etf_spot_fallback.py, scripts/backfill_etf_daily.py, scripts/backtest_alert.py,
scripts/build_board_etf_map.py, scripts/check_data_integrity.py, scripts/check_fe_err_stats.py,
scripts/check_nt_signals.py, scripts/check_signals.py, scripts/daily_summary_email.py,
scripts/detect_intraday_anomaly.py, scripts/export_alert.py, scripts/export_alert_analyze.py,
scripts/export_etf_hist.py, scripts/export_etf_score_list.py, scripts/export_notifications.py,
scripts/feishu_missed_fetch.py, scripts/feishu_ws_listener.py, scripts/fetch_etf_track_index.py,
scripts/fetch_lof_track_index.py, scripts/fetch_news.py, scripts/gen_daily_brief.py, scripts/gen_data_pack.py,
scripts/gen_etf_index_map.py, scripts/gen_schedule_stats.py, scripts/kelly_intraday_gate_decider.py,
scripts/nextday_gap_check.py, scripts/nextday_plan_generator.py, scripts/retry_failed_metrics.py,
scripts/rewash_news_digest_html.py, scripts/upload_r2.py, scripts/verify_consensus_mode_votes.py,
static-site/export.py
```

## 附录 B:关键复现命令(只读)

```bash
# B-1 absolute vs resolve(本机)
PYTHONPATH=/Users/linhuichen/code/trade-data python -c "import app.db as d;print(d._HERE)"
PYTHONPATH=/Users/linhuichen/code/trade       python -c "import app.db as d;print(d._HERE)"

# B-2 候选仓含代码仓
PYTHONPATH=/Users/linhuichen/code/trade-data/scripts python -c "import pick_repo as p;print(p.candidate_repos())"

# B-3 派生算法合成布局(A/B/单仓)
# 造 D/scripts -> C/scripts symlink,分别以 D、C、单仓路径调用 derive(),断言各得 D/D/C

# B-4 #383 遗留 A/B
REPO=/Users/linhuichen/code/trade GIT_REPO=/Users/linhuichen/code/trade MAIN_REPO=/Users/linhuichen/code/trade-data \
  PYTHONPATH=/Users/linhuichen/code/trade/scripts python -c "import pick_repo as p;print(p.sentiment_db())"
env -u REPO -u GIT_REPO MAIN_REPO=/nonexistent PYTHONPATH=/Users/linhuichen/code/trade-data/scripts \
  python -c "import pick_repo as p;print(p.pick_repo())"

# B-5 云上只读(unit env / 布局)
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 \
 'readlink /home/ubuntu/code/trade-data/{scripts,app}; \
  cd /etc/systemd/system; grep -c "^ExecStart" *.service; \
  grep -l "^Environment=REPO=" trade-*.service | wc -l; \
  grep -l "^Environment=GIT_REPO=" trade-*.service | wc -l'
```

## 附录 C:维度自查(§5.1⑤ 全局核心问题报告维度)

| 维度 | 本文是否覆盖 |
|---|---|
| 基线复现 | 是(现网 REPO=D、pick 结果 D、C/D MAX 日期) |
| 按年/时间分解 | 不适用(路径解析非收益回测) |
| 稳定性 | 是(三布局矩阵 + 单仓/双仓,批 1/2 用例) |
| 回退 | 是(每批独立 revert + 云上备份) |
| 极端窗口 | 是(env 缺失/错配/单仓/自定义布局) |
| 参数变体 | 是(REPO/GIT_REPO/MAIN_REPO 组合矩阵) |
| 口径诚实标注 | 是(§0 订正 8 项 + §6 自查事故) |
