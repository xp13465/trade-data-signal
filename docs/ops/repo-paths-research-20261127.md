> 归档自 /tmp/repo-paths-research-20261127.md,2026-11-27;原始路径为临时文件,本副本为持久归档

# 调研:#383 pick_db 读者改造依据 + #384 REPO 路径解析全景(2026-11-27)

- 任务书:`/tmp/task-repo-paths-research-20261127.md`
- 起点文档:`docs/ops/storage-phaseC-report-20261126.md` §1 表第 3 行 + §7.1(已读,本文只做增量取证)
- 全程只读:云上只 systemctl cat / ls / readlink / stat / sha256sum / sqlite3 `mode=ro&immutable=1`;未改任何文件、未动任何 unit
- 取数时点:2026-11-27 08:0x–08:4x CST

## 0. 四行结论(给主控)

1. **pick_db 家族**:4 处定义 + **8 处调用**,除已知 3 个文件外还有 `ab_direction_anchor.py`(2 处调用,21:15 定时链)与 `replay_direction_anchor.py`(1 处,手动回放),两者都委托 `gen_daily_brief.pick_db`,不是独立候选列表。
2. **当前 pick 结果 = D**(`/home/ubuntu/code/trade-data/data/sentiment.db`):D MAX(date)=20261127 > C MAX(date)=20261028,生产日志直接印证 `[brief_ledger] repo=.../trade-data db=.../trade-data/data/sentiment.db`。
3. **推荐案 A(收敛到部署数据树单源 + 抽公共函数去重)**:C 只是冻结的陈旧镜像(10-28 起未更新),镜像兜底在 D 缺失时只会喂 1 个月旧数据;"排除 C"只是黑名单补丁,留着 mac 另一份同样陈旧的镜像(C 与 mac trade/data 的 MAX 都是 20261028)。
4. **#384 解析点规模**:8 类机制、约 450+ 个文件级解析点(68 个 shell 走共享 lib、6 个 py 走 pick_repo、36 个非测试 py 自解 env、257 个 py 用 `__file__.absolute()` 系列、云上 61 个 service 中 46/43/43 份 env 不齐),已列出 8 条互相不一致(见 §4)。

---

## 1. pick_db 家族全量(定位 + 候选构造 + 判据)

### 1.1 定义点(4 处)

| # | 位置 | 候选列表怎么来 | 判"可用"判据 | 兜底 |
|---|---|---|---|---|
| D1 | `scripts/gen_daily_brief.py:127-145` `pick_db(repo)`(canonical) | `candidate_repos()`(`scripts/pick_repo.py:37-51`) | `db.exists()` 才进;`sqlite3 file:...?mode=ro` 读 `SELECT MAX(date) FROM daily_metric`;异常吞掉当 `""`;严格大于才替换 | `repo/"data"/"sentiment.db"`(repo=调用方传的 `pick_repo()`) |
| D2 | `scripts/brief_ledger.py:107-128` `_pick_db(explicit="")` | 显式 `--db` 优先,否则 `candidate_repos()`(L74 import 自 pick_repo) | 同 D1(逐字复制) | **写死 macOS 路径** `/Users/linhuichen/code/trade-data/data/sentiment.db`(L128) |
| D3 | `scripts/aggregate_shadow.py:37-54` `_pick_db()` | **自己的** `_candidate_repos()` L57-75:env `REPO`、env `GIT_REPO`、写死 `/Users/linhuichen/code/trade-data`、写死 `/Users/linhuichen/code/trade`(不读 MAIN_REPO) | 同 D1 | `pick_repo()/"data"/"sentiment.db"` |
| D4 | `scripts/ab_direction_anchor.py:100-103` `_pick_db(repo)` | 不建列表,`return gen_daily_brief.pick_db(repo)` | 同 D1 | 同 D1 |

`candidate_repos()` 顺序(`scripts/pick_repo.py:37-51`):`env REPO` → `env GIT_REPO` → `MAIN_REPO`(`:32`,默认写死 `/Users/linhuichen/code/trade-data`)→ `GIT_REPO_DEFAULT`(`:34`,= `Path(__file__).resolve().parent.parent`)。去重保序。

### 1.2 调用点(8 处)

| 位置 | 谁在跑 | 生产是否每日执行 |
|---|---|---|
| `scripts/gen_daily_brief.py:4117` | `trade-daily-brief.service`(20:40)主路径 | 是(每个交易日) |
| `scripts/gen_daily_brief.py:1674` | 方向锚注入(单 prompt 通道) | 是(`config/daily_brief.yaml:96 direction_anchor_enabled: true`) |
| `scripts/gen_daily_brief.py:2188` | 方向锚注入(多角色通道) | 是(同上;`multi_agent_enabled: true`) |
| `scripts/aggregate_shadow.py:201` | 同 unit 内 20:40 影子对账 | 是 |
| `scripts/brief_ledger.py:712` | 同 unit 内 20:40 ledger 对账 | 是 |
| `scripts/ab_direction_anchor.py:269`(`_build_ref`) | `trade-ab-direction-anchor.service`(21:15) | 是(交易日) |
| `scripts/ab_direction_anchor.py:301` | 同上(gate/对比) | 是 |
| `scripts/replay_direction_anchor.py:89` | 手动回放 | 否 |

即:一个交易日里 `pick_db` 家族会把每个候选仓的 `data/sentiment.db` 打开 **≥6 次**(20:40 五次 + 21:15 一次),每次都对 C 真开 sqlite(WAL 库只读打开会刷新 `-shm`)。

### 1.3 三份实现已经漂移(不是"同口径复制")

- D3 `aggregate_shadow._candidate_repos`(L57-75)**漏 MAIN_REPO** 且写死两个 macOS 路径 → 在"unit 只注入 MAIN_REPO 不注入 REPO"的形态下会漏掉云上数据仓。
- D2 兜底写死 macOS 路径(L128),云上若候选全失效会返回一个 Linux 上不存在的路径。
- 三份 `MAX(date)` 循环逐字复制,任何口径调整要改三处(本次改造的正当性之一)。

---

## 2. 云上实测只读取证(ssh -i ~/tdsignal.pem ubuntu@122.51.111.173)

### 2.1 相关 unit 的 WorkingDirectory / Environment(实际值)

`trade-daily-brief.service`(timer 20:40):

```
WorkingDirectory=/home/ubuntu/code/trade-data
Environment=GIT_REPO=/home/ubuntu/code/trade-data-signal
Environment=REPO=/home/ubuntu/code/trade-data
Environment=MAIN_REPO=/home/ubuntu/code/trade-data
ExecStart=/bin/bash /home/ubuntu/code/trade-data/scripts/run_daily_brief.sh --multi
```

`trade-ab-direction-anchor.service`(timer 21:15):同上三行 env,另加 `Environment=TRADE_DIR=/home/ubuntu/code/trade-data-signal`;`ExecStart=/bin/bash .../scripts/run_ab_direction_anchor.sh`。

`trade-brief-push.service`(20:45):同 env,但脚本链不含 pick_db。

`run_daily_brief.sh:56-75`:同一 unit 内串联 `gen_daily_brief.py` → `aggregate_shadow.py` → `brief_ledger.py --reconcile`(三者都会 pick_db)。

### 2.2 目录布局:代码目录是 symlink,数据目录是实体(关键)

```
trade-data/scripts     -> /home/ubuntu/code/trade-data-signal/scripts
trade-data/app         -> /home/ubuntu/code/trade-data-signal/app
trade-data/data        (real dir)
trade-data/static-site (real dir)
```

推论(与 §4 不一致 4/5 直接相关):`Path(__file__).resolve()` 系列必然落到 C;`Path(__file__).absolute()` 系列则保留 D(实测见 2.5)。

### 2.3 两个库的事实

| 项 | C `/home/ubuntu/code/trade-data-signal/data/sentiment.db` | D `/home/ubuntu/code/trade-data/data/sentiment.db` |
|---|---|---|
| size | 232,124,416 B | 237,850,624 B |
| mtime | 2026-10-28 21:38:34 | 2026-11-27 08:00:02 |
| SHA256 | `861d4ca25a3aabb03309ea2875236d53f2644934c459d9a811a08610cc890622` | `e2bee42567f2fa44cd730af91b0a99c1399525b0d7c617c2746104db81649489` |
| `MAX(date) FROM daily_metric` | **20261028**(235,250 行) | **20261127**(239,427 行) |
| sidecar | `-shm` 32,768B **mtime 2026-11-26 21:15:01.338**;`-wal` 0B / 10-28 21:40 | 无 `-shm`/`-wal`(非 WAL 热态) |

### 2.4 当前 pick 实际选了谁

- 按代码判据逐仓推(云上 unit env):`candidate_repos()` = `[REPO=D, GIT_REPO=C, MAIN_REPO=D, GIT_REPO_DEFAULT=C]` → 去重 `[D, C]`;`D:20261127 > C:20261028` → **选 D**。
- 生产日志直接证据(`trade-data/data/logs/daily_brief.log`,末 3 条):
  `[brief_ledger] repo=/home/ubuntu/code/trade-data db=/home/ubuntu/code/trade-data/data/sentiment.db`
- 即:**结果正确,但过程仍打开 C**(只读 `MAX(date)`),C 的 `-shm` 因此被刷新。

### 2.5 21:15 打开者的锁定

- `trade-ab-direction-anchor.timer` LAST = 2026-11-26 21:15:00;C `sentiment.db-shm` mtime = 21:15:01.338 —— 秒级吻合。
- 20:40 链路(`daily_brief_launchd.log`:11-26 20:40:48 影子/ledger 完成)同样会打开 C,但其后 21:15 的 ab-anchor 再开一次,把 shm mtime 刷新到 21:15。
- 结论:phaseC 报告"每日 21:15 有读者"成立,但要补一句——**20:40 主链也在读**,21:15 只是最后一次刷新者。

### 2.6 本机(非生产)对照

- `trade-data/app -> trade/app`、`trade-data/scripts -> trade/scripts`(与云上同构)。
- 本机 `import app.db` 实测:经 `trade-data` 路径 import → `_HERE=/Users/linhuichen/code/trade-data`;经 `trade` 路径 import → `_HERE=/Users/linhuichen/code/trade`(同一模块、两个根,`app/db.py:9` 用 `.absolute()`)。
- 本机 MAX(date):trade-data 20261105、trade 20261028 → 本机 pick 也选 D,镜像(trade/data)已滞后 3 周(佐证"镜像兜底=喂陈旧数据")。

---

## 3. 改法对比(§5.7 三件套 + §23.7 冻结核对)

前置冻结核对(三案共同前提):**改前改后 pick 结果必须都是 D**。证据:云上 D 20261127 > C 20261028;本机 D 20261105 > C 20261028。冻结满足。

### 案 A(推荐):收敛到"部署数据树"单源 + 去重(一步到位)

改动面:
- `scripts/pick_repo.py`:新增 `sentiment_db(repo: Path | None = None) -> Path`(单源 = `repo or pick_repo()` 下 `data/sentiment.db`),**不改 `candidate_repos()`**(它同时服务 `pick_repo()` L78 的部署源树判定与 `fetch_news.py:86`,不能动)。
- `scripts/gen_daily_brief.py:127-145`:函数体改为委托新函数(保留签名 `pick_db(repo)` 兼容 3 个调用点)。
- `scripts/brief_ledger.py:107-128`:改为 `explicit or sentiment_db()`,**删掉写死 macOS 兜底**。
- `scripts/aggregate_shadow.py:37-75`:删 `_pick_db` 与 `_candidate_repos`,改调用共享函数。
- `scripts/ab_direction_anchor.py:100-103`、`scripts/replay_direction_anchor.py:89`:改调共享函数(行为等价,但不再依赖 gen_daily_brief 的私有实现)。

实现预期(可观测 X→Y):
- 每次运行对 C 的 sqlite 打开次数 6→0;`C/data/sentiment.db-shm` 的 mtime/size 在 20:40 与 21:15 两轮后**保持不变**。
- `pick_db` 返回值不变(D 路径);生产日志 `[brief_ledger] repo=... db=/home/ubuntu/code/trade-data/data/sentiment.db` 逐字不变。
- 3 份重复实现 → 1 份(代码里 `SELECT MAX(date) FROM daily_metric` 只剩 0 处或 1 处集中点)。

风险:
- 丢镜像兜底:D 库缺失/损坏时,旧逻辑会静默回退到 C(1 个月旧数据),新逻辑直接返回 D 路径 → 调用方 `sqlite3.connect(mode=ro)` 报错=**响亮失败**。判定:这是**改善**而非退化(旧行为是静默用坏数据),但要在实施报告里标注该行为变化。
- 不减少"数据新鲜度"防护:`check_data_gap_alerts.py` 等既有新鲜度闸门不动。

### 案 B:显式排除 git 仓根

改动面:`candidate_repos()` 的每个消费者加过滤 `if r.resolve() == pick_git_repo().resolve(): continue` —— 需要改 3 份实现(D1/D2/D3)共 3 处,`pick_repo()`(L78)与 `fetch_news` 若共用同一列表还必须参数化,否则误伤部署源树判定。

实现预期:同案 A 的第一条(C 打开 0 次)。
风险:①黑名单思路,仍保留 `MAIN_REPO` 等任意陈旧镜像(mac `trade/data` MAX=20261028 同样旧);②改点更多、漏一处就复发;③3 份重复实现仍然存在。

### 案 C:不改代码,直接退役 C 的 sentiment.db

事实核查:三个实现都有 `if not db.exists(): continue`(`gen_daily_brief.py:132`、`brief_ledger.py:116`、`aggregate_shadow.py:42`),因此删库后 pick_db 会跳过 C、不会报错,也不会新建(`mode=ro`)。
风险:①无"观察一轮 21:15"窗口(退役即无对照);②若未来任何路径(如 `app/db.py:247` 阶梯末位"本仓 data"、或某脚本用 `GIT_REPO/data`)再需要 C 的旧库,已无回退;③不解决 3 份实现漂移与"代码仓被当数据仓"的语义错误。判定:可作为**兜底方案**,不推荐当主方案。

### 推荐:案 A

一句理由:D 是唯一活跃库(20261127,今日仍在写),C 与 mac 镜像都停在 20261028;与其给"某一棵镜像树"打黑名单,不如把 sentiment.db 收敛成"部署数据树单源",顺手把 3 份漂移实现合并成 1 份——一次把 #383 的读者和"读错仓"的语义病根一起清掉。

### 证据用例(实施前写定、可独立复现)

1. **新单测** `scripts/tests/test_383_sentiment_single_root.py`(目录下现无任何 pick_db/candidate_repos 用例,需新建):
   - 用例 1(排除代码仓):`monkeypatch` env `REPO=/tmp/a`、`GIT_REPO=/tmp/b`、`MAIN_REPO=/tmp/a`;造 `/tmp/a/data/sentiment.db`(MAX=20260101)、`/tmp/b/data/sentiment.db`(MAX=20261231)→ 断言返回 `/tmp/a/...`,**不得**因 MAX 更新选 /tmp/b。
   - 用例 2(无 env 回退):清空三个 env、`pick_repo` 打桩返回 `/tmp/c` → 断言返回 `/tmp/c/data/sentiment.db`。
2. **云上冻结机检**:改前记录 `stat -c '%Y %s' C/data/sentiment.db-shm` 快照;改后跑满一轮 20:40 + 21:15,再 stat,值不变 → PASS(这是"读者已消失"的正面证据,不是"日志没报错")。
3. **行为不变**:`grep -a "\[brief_ledger\] repo=" daily_brief.log | tail -1` 仍为 `db=/home/ubuntu/code/trade-data/data/sentiment.db`(改前锚点已在本报告 §2.4 固化)。
4. **调用点冒烟**:`python3 -c "import sys;sys.path.insert(0,'scripts');import gen_daily_brief as g;print(g.pick_db(g.pick_repo()))"` → 打印 D 路径(无网络、无 DB 写)。
5. **全量回归**:改 `scripts/` 源码后必须 `pytest -q scripts/tests/` 全量(L52/L59 教训)。

---

## 4. #384 REPO 路径解析全景(只列清单,不设计统一方案)

### 4.1 机制表(8 类)

| 机制 | 代表锚点 | 解析规则 | 云上落点 | 覆盖面 |
|---|---|---|---|---|
| M1 bash 共享 lib | `scripts/lib/repo_paths.sh:45-130` `resolve_repo` | env `REPO`/`GIT_REPO` 优先;否则按 `$0` 双候选推导:候选 A(scripts 目录本身是 symlink)→ REPO=`dirname(raw)`、GIT_REPO=`dirname(real)`;候选 B(物理路径)→ 姐妹 `trade-data` 存在则 REPO=姐妹,否则=GIT_REPO;推导失败 FATAL,env 失败只 warn | D(REPO)/C(GIT_REPO) | 68 个 `.sh` 顶层 source |
| M2 python 共享 lib | `scripts/pick_repo.py:37-51 candidate_repos` / `:63-86 pick_repo` / `:53-60 pick_git_repo` | env REPO 优先;无 env 按 `static-site/data/overview.json` 日期;GIT_REPO 默认 `resolve(__file__).parent.parent` | 同 D/C | 6 个 `.py` import(gen_daily_brief / brief_ledger / aggregate_shadow / ab_direction_anchor / fetch_news / overfit_monitor 中 imports;实际用到 candidate_repos 的 2 个) |
| M3 pick_db 家族 | §1 | 遍历候选仓、逐库 `MAX(date)` | 选 D,但打开 C | 4 定义 / 8 调用 |
| M4 app 层解析阶梯 | `app/db.py:231-247 _db_candidates` + `:251 resolve_db_path`,`_HERE=absolute().parent.parent`(`:9`) | `TRADE_SENTIMENT_DB` → `REPO/data` → `MAIN_REPO/data` → 兄弟 `../trade-data/data` → 本仓 `data/` | 当前命中第 2 档 D;末档在"经 C 路径 import"时 = C/data | 调用方:`app/alert_match.py:86,144`、`app/alert_score.py:113`、`scripts/export_alert.py:171,223,267`、`scripts/detect_intraday_anomaly.py:71` |
| M5 py 自解 env | 36 个非测试 `.py` 含 `os.environ.get("REPO"...)`;带 macOS 默认字面量的 4 处:`a-stock-data/backtest_strategies.py:23`、`scripts/fapi_bj_width_export.py:53`、`scripts/check_data_gap_alerts.py:137`、`scripts/backfill_direct_metrics.py:49` | 各写各的 | 随 env;无 env 时落 macOS 路径(云上不存在) | 36 文件 |
| M6 `__file__` 派生根 | `Path(__file__).absolute().parent.parent` 157 文件、`.absolute().parent.parent.parent` 87、`.resolve().parent.parent` 48、`.resolve().parent.parent.parent` 12、裸 `.parent.parent` 3 | absolute 不解析 symlink / resolve 解析 | 同一模块可能落 D **或** C(2.6 实测) | 257 文件 |
| M7 systemd 单元 env | `/etc/systemd/system/*.service` | 逐 unit 手写 `Environment=` | REPO=D / GIT_REPO=C / MAIN_REPO=D(主流) | 61 个带 ExecStart 的 service:REPO 46、GIT_REPO 43、MAIN_REPO 43 |
| M8 deploy 显式分工 | `scripts/deploy.sh:25-26` | `resolve_repo` 后 `export REPO GIT_REPO`;REPO=部署源树/数据、GIT_REPO=git 操作 | D / C | 单脚本内唯一把两种语义写清楚的样板 |

### 4.2 互相不一致清单(8 条,均为 #384 根因证据)

1. **代码仓被当数据仓**:`pick_repo.py:43-44` 把 `GIT_REPO` 与 `GIT_REPO_DEFAULT(=resolve(__file__).parent.parent)` 都塞进数据候选,`gen_daily_brief.py:130` 直接遍历 → C 被读(本案本体)。
2. **同类实现漂移**:`aggregate_shadow.py:57-75` 不复用 `pick_repo.candidate_repos`,漏 `MAIN_REPO`、写死两个 macOS 路径。
3. **兜底口径不一**:`brief_ledger.py:128` 兜底写死 macOS 路径;其余两处兜底是 `pick_repo()/data/...`。
4. **absolute vs resolve**:`app/db.py:9` 用 `.absolute()`(实测同一模块经 D 路径 import → D,经 C 路径 import → C),而 `pick_repo.py:34` 用 `.resolve()`(恒落 C)。同一 symlink 布局,两套机制两个答案。
5. **app 阶梯末位是代码仓**:`app/db.py:247` "本仓 data" 在经 C 路径 import 时 = `C/data/sentiment.db`(当前被第 2 档 `REPO` 遮住,属潜伏项)。
6. **注释与事实冲突**:`scripts/deploy.sh:744` "代码仓 data/*.db 云上零读取方" 与 pick_db 家族矛盾(phaseC 报告 §1 附注已记录)。
7. **unit env 不齐 / 语义别名过多**:5 个 trade unit 缺 MAIN_REPO(`trade-fof-nav-backfill`/`trade-fof-nav-collect` 只给 REPO;`trade-ops-monitor` 用 `OPS_CODE_ROOT`;`trade-simtrade-export` 用 `REPO`+`CODE`;`trade-sim-trade@` 无 env);"代码仓"至少 4 个别名:`GIT_REPO` / `CODE` / `OPS_CODE_ROOT` / `TRADE_DIR`。
8. **绝对路径直写**:`trade-sim-trade@.service` 的 `ExecStart` 把 D/C 全部绝对路径写死在 sh -c 里,完全绕过 env/解析机制(改仓名就断)。

附:shell 侧迁移已基本收口——全仓 `.sh` 里 `$(REPO|GIT_REPO|TRADE_DIR):-/Users/...` 剩 0 处,仅 `scripts/sensenova-rotate-proxy*.sh:10/11` 还有 `.env` 的 macOS 默认路径(开发工具脚本,非仓库根解析)。

### 4.3 复现命令(只读)

```bash
# 家族定位
grep -rn "pick_db" --include="*.py" . | grep -v "\.claude/worktrees/"
# 候选构造
sed -n '30,90p' scripts/pick_repo.py
# 解析点规模
grep -rl "lib/repo_paths.sh" --include="*.sh" . | grep -v worktrees | wc -l
grep -rl 'os.environ.get("REPO"' --include="*.py" . | grep -v worktrees | grep -v /tests/ | wc -l
grep -rl -F 'Path(__file__).absolute().parent.parent' --include="*.py" . | grep -v worktrees | wc -l
# 云上(只读)
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 \
  'systemctl cat trade-daily-brief.service trade-ab-direction-anchor.service --no-pager; \
   readlink /home/ubuntu/code/trade-data/{scripts,app}; \
   stat -c "%n %s %y" /home/ubuntu/code/trade-data-signal/data/sentiment.db* /home/ubuntu/code/trade-data/data/sentiment.db'
```

## 5. 已验证方法/数据源清单(供主控判断充分性)

- 代码面:全仓 grep(`pick_db`/`_pick_db`/`candidate_repos`/`REPO|GIT_REPO|MAIN_REPO`/`sentiment.db`),排除 `.claude/worktrees/`。
- 生产面:云上 2 个 unit 实测定义 + timer 表 + 2 个库 stat/SHA256/`MAX(date)`(immutable 只读)+ 两份日志(`daily_brief.log`、`daily_brief_launchd.log`)+ `-shm` mtime 对齐。
- 本机面:同构 symlink 布局实测 + `app.db` 导入路径双根实验 + 两库 MAX(date) 对照。
- 未做(超出本批范围):未跑任何改造、未触发任何生产重跑、未设计 #384 统一方案(任务书要求另批)。

