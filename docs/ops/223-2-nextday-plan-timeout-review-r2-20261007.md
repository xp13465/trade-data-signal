# #223② 独立复审报告(r2):F1 契约测试 480 同步 + F2/[C] 失真文案订正

- 待审分支:`feat/223-2-nextday-plan-timeout-20261007`,tip **`4b3c0b386`**
  (链:`f0d4cb1fe` ②实施[首轮已审] → `054ea45b2` F1+F2 修复 → `4b3c0b386` [C] 文案订正)
- 审阅:reviewer(独立上下文,只读;**未改任何业务代码**;变异测试全部在 `/tmp` 克隆件进行并已还原;零真实外发,§18 L48/L50)
- 依据:CLAUDE.md §15/§22/§23.11/§18 L49/L50;role-reviewer skill §2/§10.5;首轮报告 `docs/ops/223-2-nextday-plan-timeout-review-20261007.md`

## 0. 结论速览

| 项 | 结论 |
|---|---|
| **merge 资格** | **PASS(无阻断,F1 已真修)** |
| 必答 1 F1 真修 + merge 后 CI 绿 | PASS(merge 模拟树 `pytest -q scripts/tests/` = **265 passed, 1 skipped, 0 FAIL**) |
| 必答 2 F2 措辞订正 | PASS(两版守卫行为实证逐条吻合;AST 证零行为变更) |
| 必答 3 [C] 文案订正 | PASS(3 处准确;`:162`/`MIN_ASSERTIONS=33`/`:165` 确未动) |
| 必答 4 §23.3 穷举 | PASS(该链 timeout 断言全仓只剩两个测试文件,均已同步) |
| 必答 5 反向变异(L49) | PASS(M-T/M-S 双 FAIL;已还原,md5 与工作树逐位一致) |
| 必答 6 首轮残留 | 无残留阻断(F1/F2 双闭环) |
| 必答 7 零夹带/git | PASS |

## 1. F1 是否真修(必答 1)

**逐字核**:`scripts/tests/test_223_timeout_gradient_copy.py:161` 现为
`(ROOT / "scripts" / "nextday_plan_generator.py", "timeout=480"),  # #223②(2026-10-07 拍板) 300→480: 契约值同步(该链唯一 CI 契约点)`
—— 与 ② 实施(源 `scripts/nextday_plan_generator.py:1189` `subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=480)`)一致;契约语义 = 「三处契约值在位(120/480/300)+ 各文件带 #223 注释」,与 ② 实施后现状逐项吻合。

**merge 后真会 CI 绿(独立模拟,非推断)**:
- 装置:`/tmp/223-2-merge-sim` = `git clone` 主仓 → `git checkout main`(tip `ec3ea11c4`,== 当前 origin/main)→ `git merge feat-223-2`(**clean merge**,merge commit `cbc78e98b`)。
- 跑 CI Job1 ⑧ 同款命令(`.github/workflows/ci.yml:109-112` = `python3 -m pytest -q scripts/tests/`):**265 passed, 1 skipped, 零 FAIL**
  (skip = `test_monitor_resource_inprogress_20261005.py` 的 macOS APFS 口径,CI Ubuntu 会真跑;与本分支 diff 不相交)。
- 目标文件单跑 `1 passed`;直跑人工口径 **PASS=33 FAIL=0 ALL_PASS**。
- **断言与 main 现状逐位一致**(merge 树实测布尔):`timeout=120` in `gen_daily_brief.py` ✓(2 处)、`timeout=480` in `nextday_plan_generator.py` ✓(1 处 = 调用点)、`timeout=300` in `nextday_gap_check.py` ✓(2 处)、`#223` in 三文件 ✓。
- **环境无关性**:该测试全程 AST/文本只读,无 systemctl/网络/subprocess;唯一环境分支 `data/alerts/latest.md`(CI 无该文件 → else 分支)在克隆件中同样不存在 ⇒ 与 CI 同构。目标两文件 md5 与真实 worktree 逐位一致(`d0c05579deef…` / `5417a105c01a…`)。

**边界(诚实)**:main 当前 CI 红的另一病灶(#223④ `test_223_overfit_monitor_timeout.py:92` 写死「本机无 systemctl」,Ubuntu 不过)属独立轨道 `feat/223-4-ci-fix-20261007`(tip `29fe79826`,未进 main),与本分支零关系;本分支自身**不再新增红**。

## 2. F2 措辞订正(必答 2):正确 + 零夹带行为变更

- **独立实证**(沙箱 AST-exec 只抽 `_R2_UPLOAD_TIMEOUT*` 常量 + `_r2_upload_timeout` 函数,不 import 业务模块 = 仓内既有 static-only 范式):
  - #223④ overfit 版代入 outer=600 + http_to=600、基值 480 → 返回 **480**(连续两次调用各打 1 行 warn)⇒ 订正表述「行为中性 / 走外层优先不越墙分支保持 480 / 倒置条件恒真 ⇒ 每次运行打一行永久 warn」**逐条成立**;
  - #217② fapi 版代入基值 480 → 返回 **900 > 600**(越墙)⇒「照抄会越墙、不可用」成立。
- **零行为变更(AST 级证明)**:
  - `scripts/nextday_plan_generator.py`(`054ea45b2`):前后 `ast.dump` **IDENTICAL**(注释不进 AST ⇒ 纯注释);
  - `scripts/tests/test_223_nextday_plan_timeout.py`(`054ea45b2`):抹去全部字符串值后结构 AST **IDENTICAL**,字符串常量仅 **1 处**变化(模块 docstring 本体释文)。

## 3. [C] 节文案订正(必答 3):准确、未引入新失真

- `:11` 模块 docstring → `[C] ① / ② / nextday_gap_check 的超时契约值(② 已随 #223② 300→480; ①/gap_check 未改值)` —— 与取证报告结论(①不动 / ③不动 / ②抬 480)一致,**准确**;
- `:159` 节标题 → `[C] ① / ② / gap_check 契约值(② 已随 #223② 300→480; ①/gap_check 未改值)` —— **准确**;
- `:164` ck 消息 → `{f.name}: {old} 契约值在位` —— **准确**(消灭旧「保留(未改值)」对已改值的 ② 的失真);
- **未动项确证**(AST 字符串常量枚举:删 3/增 3,恰为上述三处;结构 AST 同一):`:161` F1 行、`:162` gap_check 元组、`:46` `MIN_ASSERTIONS = 33`、`:165`「#223 注释」断言 **全未动**(与 4b3c0b386 message 自述逐项吻合)。

## 4. §23.3 穷举(必答 4):该链 timeout 断言全仓穷举

| 位置 | 断言值 | 状态 |
|---|---|---|
| `scripts/tests/test_223_timeout_gradient_copy.py:161` | 480 | 已同步(F1 修) |
| `scripts/tests/test_223_nextday_plan_timeout.py`(AST ~10 处 + 文本) | 480 / 无 300 | 随 ② 同步(`f0d4cb1fe`) |
| `scripts/tests/test_223_timeout_gradient_copy.py:162`(nextday_gap_check) | 300 | 有意保留(gap_check 本期未改,取证 §4) |

全仓 grep(排除 docs)确认**无第三处**引用 `nextday_plan_generator` 的 timeout 断言;其余 `timeout=300/480` 命中均为无关面(`export.py`/`build_min.py`/`probe_fapi.py`/`PRAGMA busy_timeout` 等);旧文案「值未动/保留(未改值)」无其他代码消费者。

## 5. 反向变异(L49 防空转,必答 5):双负控均 FAIL

| 变异 | 结果(逐字证据) |
|---|---|
| **M-T 测试侧 480→300**(`:161` 元组) | `1 failed`;唯一 FAIL 行:`FAIL  nextday_plan_generator.py: timeout=300 契约值在位`(PASS=32 FAIL=1,与首轮 F1 观测态逐位一致) |
| **M-S 源码侧 480→300**(`:1189` 调用点) | 两测试文件均 FAIL:gradient = `FAIL  nextday_plan_generator.py: timeout=480 契约值在位`;新测试 = `AssertionError: [#1] 应有恰 1 处 subprocess.run(timeout=480), 实得 []` |

- 变异在 `/tmp/223-2-merge-sim` 克隆件进行(**非真实 worktree**);计算后还原,`git status --porcelain` 空、无 `.bak` 残留、三文件 md5 与真实 worktree **逐位一致**(`d0c05579…/5417a105…/9d9c4766…`)⇒ 断言真生效、零遗留。

## 6. 首轮残留阻断复查(必答 6)

- F1(阻断):**已闭环**(§1);
- F2(80 非阻断):**已闭环**(§2);
- 首轮低分 4 项现状:①新测试末尾无换行符——仍在(纯风格,非阻断);②fetch_news 无 #223 交叉注释——信息性;③「24/26 断言」澄清——无动作;④「外层 unit 未来改小无运行时守护」——设计接受。**均无新增动作项,无残留阻断**。

## 7. 零夹带 / git(必答 7):PASS

- 增量面 `f0d4cb1fe..4b3c0b386` 恰 3 文件(源文件 = 纯注释;2 个测试文件);全分支 `38c172461..HEAD` 恰 3 文件,无 `data/`/`static-site/`/`app/` 夹带;源文件自 ①实施后 **AST IDENTICAL**(两修复 commit 零逻辑触碰);
- 两 commit trailer 均 `Co-Authored-By: Claude Code <noreply@anthropic.com>`;`4b3c0b386` **不在 origin/main**;`origin/feat/223-2-…` tip == 本地 tip(已推 feat、未推 main);
- base 落差零重叠(§23.11):`38c172461..origin/main` 恰 5 文件(CLAUDE.md/TASKS.md/pending-index/2 docs)与分支 3 文件交集 = **空**;merge 模拟 clean、无冲突;
- 主仓/worktree 工作区均干净;未 add 根 data/;未动 `pending-features-index.md`/`TASKS.md`。

## 8. Findings

- **≥80 findings:0 条**;无阻断项。
- 低分滤除项(<80,共 3 条,列出防黑箱):
  1. (50)`:161` 内联注释「该链唯一 CI 契约点」——严格说同链新增测试文件也钉 480,「唯一」偏松;两处 CI 双保险,任何单边改动仍会红(无实际危害;措辞源自首轮审 F1 修法原文)。
  2. (30)注释/文档串中 `tests/test_223_nextday_plan_timeout.py` 省略 `scripts/` 前缀(nitpick)。
  3. (25)新测试文件末尾无换行符(承首轮低分项,纯风格)。

## 9. 诚实标注(本轮未做/边界)

- 未真跑 CI(`gh` 不在本机;docker daemon 未运行 ⇒ 无法 Ubuntu 容器复现);以「main+分支 clean merge 模拟树 + CI 同款命令」等价取证。
- Job1 其余门禁(①-⑤)未跑:与本分支 3 个 py 文件改动面结构性不相交;⑧ 为唯一相关门禁,已全绿。
- 云上未连、未跑任何业务脚本、未 start/stop 任何 unit(§18 L50);变异只在 `/tmp` 克隆件。
- 首轮报告 §9 所列限制(CI 未真跑等)在本轮同样保留。
