> 归档自 /tmp/pickdb-review-report-20261127.md,2026-11-27;原始路径为临时文件,本副本为持久归档

# 审查报告:#383 pick_db 单源收敛(feat/pickdb-single-root-20261127 @ 192691ab3)

- 审查者:reviewer(独立 fresh context,只审不改)
- base:`78c062f21`;审查对象:`origin/feat/pickdb-single-root-20261127`(8 文件 +115/−91)
- 依据链:调研 `/tmp/repo-paths-research-20261127.md` §3 / 实施报告 `/tmp/pickdb-impl-report-20261127.md`
- 审查时点:2026-11-27 11:36–12:10(两次 429 中断后续跑)
- 隔离:临时 worktree `/tmp/wt-review-pickdb-20261127`(detached 192691ab3,审毕已 remove);未碰主仓/生产/云上

## 结论:PASS(不阻断合并)

**阻断 0 / 必改 0 / 建议 2**(均为「注释与自验报告措辞口径」,代码行为正确;建议见 §5)
**边界差集 3 项**(见 §4;均已给处置:2 项显式声明不测+归 #384,1 项并入建议 S1)
低分项(<80)已滤 2 个(见文末)。

## 0. 尺子先验(§10.0)与审查手段

| 尺子 | 怎么验过本身 | 判别力证据 |
|---|---|---|
| 新用例基线(`test_383_sentiment_single_root.py`) | 在 feat 分支隔离 worktree 实跑:`4 passed in 4.49s` | 见下两行变异 |
| 变异 1(把 `sentiment_db` 改成返回 `pick_git_repo()/data/sentiment.db`,即代码仓侧) | 先 `grep` 确认 sed 已真改到目标行:`100: return pick_git_repo()/...`;跑完 `git checkout --` 还原,`git status --porcelain` 空 | **4 failed**(4 用例全红) |
| 变异 2(`gen_daily_brief.pick_db` 改为忽略 repo 入参 `return sentiment_db()`) | 同上,`grep` 见 `132: return sentiment_db()`;还原后 status 空 | **1 failed**(test_pick_db_delegates_to_single_root) |
| 全量 pytest | 在隔离 worktree 跑 `pytest -q scripts/tests/`,独立读末行 | `5591 passed, 6 skipped, 1 warning, 176 subtests passed in 738.35s`(与实施报告 5591/6/1/176 逐位一致) |
| 本机两树真实数据尺子 | 直接只读 `sqlite3 file:...?mode=ro` + 读 overview.json | 见 §1.2(真实生产同构数据,非构造) |
| 环境形态探针 | 探针自打印构造路径;不触网/不写库/不开 any 通知链路(本次未运行任何 notify/邮件/飞书脚本) | 输出见 §4 差集 #2 |

无「真实外发链路」被测对象,故无需打桩;全程零网络、零生产 DB 写(tests 只落 pytest tmp_path)。

## 1. 冻结核对(§23.7,本单最重):PASS

### 1.1 `pick_repo.py` 本体未动(调研点名不可动处)
`git diff origin/main..origin/feat` 中 `pick_repo.py` 仅两个 hunk:①docstring 增一行;②`:91-102` 新增 `sentiment_db()`。`candidate_repos()`(`:37-51`)与 `pick_repo()`(`:63-87`)**函数体零改动**——`pick_repo()` L78 的部署源树判定与 `fetch_news.py:86/89` 的 `candidate_repos` 导入均不受影响(fetch_news 未在 diff 内,导入符号仍存在)。

`sentiment_db(repo=None)` = `(repo or pick_repo()) / "data" / "sentiment.db"`,无候选扫描、无 MAX(date)、无兜底回退。

### 1.2 「D 存在」场景逐位等价(改前改后都是 D)

| 场景 | 旧逻辑(候选仓遍历 MAX(date)) | 新逻辑 | 结论 |
|---|---|---|---|
| 云上(调研 §2.1 实测 unit env:REPO=D / GIT_REPO=C / MAIN_REPO=D) | 候选 [D,C];D 20261127 > C 20261028 → D | 各调用点传 `pick_repo()`,env REPO=D 且 is_dir → D | 同 D,路径均为 resolve 后绝对路径,字符串一致 |
| 本机无 env(本次实测两树) | D MAX=20261105 > C MAX=20261028 → D | `pick_repo()` 按 overview.date 选:两树均 20261105,候选序 trade-data 在前且严格大于 → trade-data(D) | 同 D |
| 本机冒烟(实跑) | `pick_db(pick_repo())` → D | `pick_db`/`_pick_db()`/`sentiment_db()` 均打印 `/Users/linhuichen/code/trade-data/data/sentiment.db` | 同 D,完全一致 |
| `brief_ledger --db 显式` | `Path(explicit)` | 未变 | 一致 |
| `replay_direction_anchor` 本机无 env | 旧扫候选选 D(trade-data) | 新取 `REPO_ROOT`=trade/,读 `trade/data/sentiment.db`(MAX 20261028,陈旧) | **行为变化,已由实施报告 §④2 如实标注**(手动回放脚本,非生产;想用最新库需设 REPO=…) |

本机实测数据(只读):
- `/Users/linhuichen/code/trade-data`:overview.date=20261105,db MAX=20261105
- `/Users/linhuichen/code/trade`:overview.date=20261105,db MAX=20261028

### 1.3 「无静默回退旧数据」核验:成立
新 `sentiment_db` 代码内不存在任何候选/回退分支(已逐行读),不存在把 C/mac 镜像当数据源的路径。D 缺失/损坏时:
- `gen_daily_brief.main`:`load_data` 内 `sqlite3.connect(f"file:{db_path}?mode=ro")` 在 **try 之外**(feat `:1167`),异常直接上抛;`run_daily_brief.sh` 捕获非零 → 发 `[告警] daily_brief 生成失败`(dedup-key=daily_brief_fail)并继续后续(脚本设计退出码恒 0,属既有形态)。
- `ab_direction_anchor` / `replay_direction_anchor`:都先调 `gen_daily_brief.load_data` → 同上响亮失败。
- ⚠️ `aggregate_shadow._load_sh_pct_map`(`:36-45` `except Exception: pass`)与 `brief_ledger._load_sh_pct_map`/`check_ledger`(同类吞异常)在 D 缺失时**静默空转(exit 0)**,不是"响亮报错"——见建议 S1。

### 1.4 8 处调用点全覆盖(改后新行号)

| # | 位置 | repo 来源 | 改法 |
|---|---|---|---|
| 1 | `gen_daily_brief.py:4104` | `repo = pick_repo()`(:4102) | `pick_db(repo)` → `sentiment_db(repo)` |
| 2 | `gen_daily_brief.py:1661` | `pick_repo()` | 签名保留,委托 |
| 3 | `gen_daily_brief.py:2175` | `pick_repo()` | 同上 |
| 4 | `aggregate_shadow.py:162` | `repo = pick_repo()`(:149) | `sentiment_db(repo)` |
| 5 | `brief_ledger.py:697` → `_pick_db`(:107-111) | 无参 → `pick_repo()` | `explicit or sentiment_db()` |
| 6 | `ab_direction_anchor.py:263` | `repo = pick_repo()`(:282→更早调用点由 main 传) | `sentiment_db(repo)` |
| 7 | `ab_direction_anchor.py:295` | 同上 | 同上 |
| 8 | `replay_direction_anchor.py:91` | `_pick_repo()` | `sentiment_db(repo)` |

`run_daily_brief.sh:62/75` 对 aggregate/ledger 显式注入 `REPO="$REPO"`,故即使 unit env 缺失,`pick_repo()` 仍拿部署树 → 生产安全。

## 2. 调用面穷举(全仓 grep):PASS

- `git grep -nE "pick_db|_pick_db|_candidate_repos" feat -- ':!docs' ':!*.md'`:仅剩 `gen_daily_brief.pick_db`(定义+3 调用)、`brief_ledger._pick_db`(定义+1 调用)、新测试文件。**无任何残留 import 已删符号**(`aggregate_shadow._pick_db`/`_candidate_repos`、`gen_daily_brief` 的 `candidate_repos` 导入均已清)。
- `from pick_repo import`/`import pick_repo` 全量导入者:ab/aggregate/brief_ledger/fetch_news/gen/overfit_monitor/replay/`run_ab_direction_anchor.sh:23`/新测试——导入符号全部存在(`candidate_repos` 未删)。
- `aggregate_shadow` 删 `import os` 后无残留 `os.` 用法(逐行 grep);`gen_daily_brief`/`brief_ledger` 的 `sqlite3` 仍被其余逻辑使用(grep 证据)。
- `fetch_news.py:86/89` 仍 import `candidate_repos`(函数未改,不受影响)。
- 全仓其它 sentiment.db 解析器(`app/db.py` #335 阶梯、`check_data_integrity._find_sentiment_db`、`build_board_etf_map` 镜像回退、`check_data_gap_alerts` 自有候选)均未改动、未误伤;它们是建议 S1 的证据。

## 3. 测试质量:PASS

- 4 用例覆盖:①排除代码仓(REPO=部署树、代码仓 MAX 更新也不得选)②无 env 回退(打桩 pick_repo → 委托正确)③显式 repo 参数 ④`pick_db` 委托(3 调用点兼容)。与调研 §3「证据用例 1/2」一致。
- L56(裸 os.environ):全部 `monkeypatch.setenv/delenv/setattr` 自动还原——通过。
- L51(时敏):改动代码与新测试均无 `today()/now()` 日期断言;CI step ⑫「+45d 平移」会因 `scripts/tests/` 变更触发新用例,无隔天红风险——通过。
- 判别力:变异 1 → 4 failed;变异 2 → 1 failed(见 §0)。
- CI 可移植性:用例不依赖 mac 路径存在(test1 靠 env REPO;test2 打桩;test3/4 tmp_path),Linux runner 可跑。
- 轻微(<80,已滤):test4 用 `pytest.importorskip("gen_daily_brief")`,若该模块导入坏会 skip 而非 fail;但全量套件另有 gen 相关用例会红,风险可接受。

## 4. 边界完整性独立复核(§10.8):我推清单 vs 实施方清单

先不看实施方清单独立推演,再对账。两边都有:env 组合 / 选中态(部署树 vs 代码仓同存、代码仓更新)/ 时序(不再拼 MAX)/ 上下游(4 模块 + 8 调用)/ 回退(无 env、显式 --db)/ 并发(改动为纯路径计算,无锁)。

**差集(我有、实施方清单没有)3 项:**

| # | 我推的边界 | 实施方现状 | 现状可达性 | 处置 |
|---|---|---|---|---|
| B1 | env `REPO` 本身指向**代码仓/单仓形态**(REPO==GIT_REPO==C):新逻辑信任 env 返回 C 的陈旧库;旧逻辑按 MAX 会选 D | 「状态组合」只覆盖「REPO=部署树、代码仓侧更新」,未覆盖「REPO 本身=代码仓」 | 今日不可达:pick_db 读者只在 `trade-daily-brief`(20:40)与 `trade-ab-direction-anchor`(21:15)两 unit,调研实测二者 REPO=D;但 `pick_repo.py` docstring 记录过云上单仓形态(REPO=GIT_REPO 同路径) | **显式声明不测 + 理由**(现状两 unit REPO=D;语义上显式 REPO 即声明数据树);归 **#384**(REPO 语义统一)另批;主控 merge 后按调研证据用例 2 观察 C `-shm` 不刷新作为正面证据 |
| B2 | **Linux/无 env 且 MAIN_REPO 默认不存在**(默认值 `/Users/linhuichen/code/trade-data` 在 Linux 不存在)→ `pick_repo()` 落 `GIT_REPO_DEFAULT`=脚本所在仓(**代码仓**),`sentiment_db()` = `代码仓/data/sentiment.db`,与 docstring「部署数据树单源」有落差 | 「无 env 回退」用例打桩 `pick_repo`,未覆盖真实无 env 落点 | 今日不可达(两个生产 unit 均注入 REPO;`run_daily_brief.sh` 亦显式 `REPO=`);但属 #384 潜伏面 | **显式声明不测 + 理由**(同上);建议 `sentiment_db` docstring 补一句「env 未注入且 MAIN_REPO 不存在时落脚本所在仓」;归 **#384**。探针实测:`pick_repo()`/`sentiment_db()` 均落构造的代码仓路径 |
| B3 | **D 缺失/损坏时下游静默**:`aggregate_shadow`/`brief_ledger reconcile` 吞异常 → 20:40 链后两步静默空转;实施方「极端值不测,理由=sqlite3 既有报错保证」只覆盖 gen 主链 | 未列 | 可发生(库损坏/磁盘故障,低频) | 并入**建议 S1**:补标注(注释/报告写明"仅 gen 主链响亮,aggregate/brief_ledger reconcile 仍静默");是否加显式存在性硬闸=超 #383 范围,上报主控另议 |

实施方有、我没有的维度:无实质新增(其 7 轴均落入我推演范围)。B1/B2 属「输入域/状态组合」的未覆盖子形态,B3 属「极端值」理由不足。

## 5. 建议(不阻断)

**S1(置信度 90,口径准确性)**:`deploy.sh:744-746` 注释与实施报告 §④1 两处表述过宽:
- "sentiment.db **读者**已…收敛为 pick_repo.sentiment_db 部署数据树单源" —— 实际仍有多处 sentiment.db 解析器:`app/db.py` #335 阶梯(末档「本仓 data」在经代码仓路径 import 时=C)、`check_data_integrity._find_sentiment_db`(候选含 GIT_REPO)、`build_board_etf_map`(trade-data→trade 镜像回退)、`check_data_gap_alerts`(自有候选)。建议措辞收窄为「**pick_db 家族**读者(gen_daily_brief/aggregate_shadow/brief_ledger/ab_direction_anchor/replay)已收敛…;#384 其它解析器另批」。
- "库缺失时调用方 sqlite3(mode=ro) **响亮报错**" —— 仅 `gen_daily_brief.load_data`(及 ab/replay 经 load_data)响亮;`aggregate_shadow._load_sh_pct_map` 与 `brief_ledger._load_sh_pct_map`/`check_ledger` 为 `except Exception: pass` 静默空转。建议补注「20:40 链后两步在库缺失时静默空转(既有吞异常,非本批引入)」。
- 注:该注释所在「排除代码仓 *.db」的决策本身不受影响(20:40/21:15 生产读者 REPO=D,代码仓库缺失/陈旧不会导致错误数据),故不阻断 merge。

**S2(置信度 100,报告自验准确性)**:实施报告 §「同类错误面清单」称“全仓 `scripts/` 内 `SELECT MAX(date) FROM daily_metric` 只剩带 WHERE metric_id 的正常用法”。实际 `brief_ledger.py:654`(`check_ledger` 内)存在 **无 WHERE** 的 `SELECT MAX(date) FROM daily_metric`(用途=ledger 最新行日期 vs DB 最新交易日对账,合法且非候选遍历,属 pre-existing)。建议报告措辞改为「候选遍历 loop 剩 0 处;另有 check_ledger 的 MAX(date) 对账用法保留」。代码无需改。

## 6. 其余规范面(快速核)

- §21 算法公示:无算法/权重/数值口径改动 → N/A。
- §22 数据一致性:不改任何数据产物/展示位/缓存;日志 `[brief_ledger] repo=… db=…` 输出路径不变。
- §24 前端防撕裂:0 个前端文件(app.js/lab.js/common.js/static-site)改动;本分支无需 bump,main-merge 机制 C 照常。
- §23.4/§23.5:实施报告已 scan `docs/pending-features-index.md` #383/#384,无同模块并行项;本次审查未见冲突迹象。
- §9.5 数据供给闭环:非动态数据/择时功能,N/A。
- §10.7 方案可证伪:调研 §3 证据用例 1/4/5 本批**已真跑**(新用例/冒烟/全量);用例 2/3(云上 `-shm` 与 `[brief_ledger]` 日志锚点)实施报告已声明**归主控 merge 后执行** —— 这两条未跑之前,不得向用户宣称“C 读取已消除”已线上验证。
- §23.15 完整版上线:纯内部路径收敛,无残缺展示/残缺口径数字。
- CI 面:`.github/workflows/ci.yml` Job1 ⑧ 命令=`python3 -m pytest -q scripts/tests/`(第 189 行)→ 新用例自动纳入;本次无「登记类计数/列表常量」改动,`ops/monitoring/tests/smoke_local.py` 无相关硬编码断言。

## 7. 低分项(<80)已滤:2 个
1. test4 `importorskip` 可能把导入坏 skip 掉(全量套件另有 gen 用例兜底)。
2. `sentiment_db` 不做 `.resolve()`:repo 为相对/含 `..` 时缓存键 `str(db_path)` 可能与旧值不同(当前调用方均传 resolve 后的 `pick_repo()`,无影响)。

## 8. 复现命令清单(只读)

```bash
git -c core.quotepath=false diff origin/main..origin/feat/pickdb-single-root-20261127
git -c core.quotepath=false grep -nE "pick_db|_pick_db|_candidate_repos" origin/feat/pickdb-single-root-20261127 -- ':!docs'
# 隔离 worktree 实跑(已清理):
#   pytest -q scripts/tests/test_383_sentiment_single_root.py   -> 4 passed
#   pytest -q scripts/tests/                                    -> 5591 passed, 6 skipped, 176 subtests
# 本机两树对照(只读 sqlite3 mode=ro + overview.json)见 §1.2
```

## 9. 结论

**PASS,不阻断合并**(阻断 0 / 必改 0 / 建议 2)。
- 冻结满足:云上 env REPO=D 与本机实测两树下,改前改后 pick 结果均为 D;`candidate_repos()`/`pick_repo()` 本体未动;8 调用点全覆盖、无残留符号。
- 无静默回退旧数据(重构正确);但「响亮报错」并非所有调用方成立 → 建议 S1 修注释/报告措辞。
- merge 后必做(归主控,不属本审查):调研证据用例 2/3 云上复核(C `-shm` 两轮后不变 + `[brief_ledger] repo=... db=/home/ubuntu/code/trade-data/data/sentiment.db` 逐字不变)。
