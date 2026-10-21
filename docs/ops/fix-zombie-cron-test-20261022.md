> 落档:2026-10-22(源报告由本批执行 agent 产出,原样归档)
> 相关合并:见 `docs/ops/batch-fix-20261022.md` 时间线

# 修 test_224_zombie_cron_gate 时敏假红 — 报告(2026-10-22)

残留后台任务:无(曾有 1 个:`bb5l1kcvx` = 全量 pytest,已 completed exit 0,输出 `/private/tmp/claude-501/.../tasks/bb5l1kcvx.output`)

## 1. 根因确认(实测,非推测)

复现命令(python 直跑同款断言):原用例在本机 00:41 起必红,
`AssertionError: 真实 job b0741f7c ready_at=1792602780 在将来, 不应被误判僵尸`。

探针(`/tmp/probe_zombie_224.py`)实测把 FAIL detail 逐行打印,形态:

```
cron 2c7d3713 巡检进度文件不存在: ...(已过应产生时刻...)          <- 真 FAIL 行
cron b0741f7c 进度文件 agent-progress-… 尚未产生 -> ... 不判僵尸     <- pending 行(带 job id)
cron 44e3f6ad …尚未产生 -> … 不判僵尸                              <- pending 行
cron 0ebd321d …尚未产生 -> … 不判僵尸                              <- pending 行
```

- `check_task_state.py:515-517`:FAIL 时 `res.detail = detail_fail + detail_pending`(pending 行也带 job id)。
- 测试 `_fails()` 原实现返回**全部** detail ⇒ ready_at 在将来的 job 只要出现在 pending 说明里就被当成「被 FAIL 提及」。
- 00:33 前 b0741f7c 的 ready_at 未到期 ⇒ 全 pending ⇒ 绿;00:33 后 2c7d3713 先到期真 FAIL,detail 里带出 pending 行 ⇒ 必红 = 时敏(同 L51 教训族)。
- 另有一处耦合:`now = time.time()` 在 `check_zombie_crons` **之后**取,断言与被测时钟不同源。

结论:生产判定语义正确,**测试契约错**(既混同 fail/pending,又与真实时钟耦合)。按要求只改测试,`scripts/check_task_state.py` 零改动(`git diff` 仅 1 个文件)。

## 2. 改动文件:行

`/Users/linhuichen/code/trade/.claude/worktrees/agent-a06593596611528be/scripts/tests/test_224_zombie_cron_gate.py`(唯一改动,+86/-9)

| 行 | 改动 |
|---|---|
| 89-100 | `_fails()` 改为**只返回真 FAIL 行**(过滤含「不判僵尸」的 pending 说明行),docstring 写明根因与 `check_task_state.py:515-517` 锚点 |
| 102-104 | 新增 `_pending_lines()`:只取 pending 说明行,供反向断言「事故形态确实出现」 |
| 111-125 | 新增 `_freeze_now(monkeypatch, epoch)`:只替换 `check_task_state` 模块里的 `time` 名字(不动标准库全局),`time/localtime/mktime/strftime` 统一走桩,保证「当前时刻」与「cron 解析时区」同源 |
| 296-329 | `test_real_jobs_no_false_zombie_when_pending` 重写:时钟冻结在「真实 job 最晚 ready_at 前 1 秒」(由样本数据推导,与运行时刻无关)⇒ 必然 fail/pending 混排;只对真 FAIL 行断言;并反向断言 future job 确实出现在 pending 行 |
| 331-357 | 新增 `test_pending_lines_not_counted_as_fail_when_mixed` + `FROZEN_NOW`(固定时钟锚 1.8e9):**CI 必跑、不依赖真实文件**的直接回归守卫,断言 mix-past 真 FAIL(判别力)、mix-future 不在 FAIL 行但在 pending 行 |

参数化 `shift_secs=[0, 2*3600, 86400]` 覆盖「冻结时间 +2h / +1天仍绿」;两个用例均无写死数据日期字面量(L51)。

## 3. 变异测试证据(判别力不得下降)

| 变异 | 结果 |
|---|---|
| M1:`is_pending = False`(忽略 pending,check_task_state.py:490 临时改) | 红:`test_pending_lines_not_counted_as_fail_when_mixed[0/7200/86400]` 3 个 + `test_real_jobs_no_false_zombie_when_pending[0]` 均 FAILED(共 8 failed) |
| M2:`is_pending = ready_at is not None`(恒 pending) | 红:`test_pending_lines_not_counted_as_fail_when_mixed[0/7200/86400]` 3 个 FAILED(mix-past 未被判 FAIL)(共 8 failed) |
| 还原(`is_pending = ready_at is not None and now < ready_at`) | 绿:该文件 `20 passed` |

生产文件还原验证:`git diff --stat` 仅显示 test 文件 ⇒ `check_task_state.py` 与 main 逐字一致。

## 4. 全量 pytest(L52)

`/Users/linhuichen/code/trade/.venv/bin/python -m pytest -q scripts/tests/`
→ **1106 passed, 2 skipped in 144.89s**(exit 0)

(数字与 266 merge 时的 1134 passed 不同,因本源分支 base `30f7b4583` 落后 origin/main,少 28 条 main 新增用例;本分支改动只碰 1 个测试文件,diff vs origin/main 也只此一处,main 该文件自 `1fbd114ad` 未再变 ⇒ 合入无冲突。)

## 5. 同型时敏扫描清单(读真实文件 + 真实时钟)

扫描手段:`grep -rn "st_mtime|getmtime|time.time()|datetime.now()|date.today()|/Users/linhuichen" scripts/tests/*.py` 逐条看上下文。

| 文件 | 形态 | 判定 |
|---|---|---|
| `test_224_zombie_cron_gate.py` | 读真实 `.claude/scheduled_tasks.json` + 真实时钟 | **同型,本批已修**(冻结时钟 + 由样本推导) |
| `test_alertchain_hardening_20261003.py:202/205, 231/234` | `os.utime(hb, now-60/now-7200)` 造 tmp 心跳文件 | 非时敏:全部相对真实 now 生成,任何时刻跑都成立 |
| `test_258_lock_work_budget_20261017.py:61/132-134` | `time.time()` 计时 + 读自己刚写的心跳 mtime 差 | 非时敏:测量相对间隔 |
| `test_196_patrol_visibility_20261005.py:517-534` | `datetime.now()` 生成「今天/昨/前天」字符串 | 非时敏:相对 now 构造,不比对真实数据日期 |
| `test_218k1_253d2_mirror_digest_20261017.py:103/359/374` | `datetime.now()/date.today()` 生成日期标签 | 非时敏(相对) |
| `test_241_family_b_consign_20261009.py:246/286/332/349`、`test_245_l2_budget_digest_20261010.py:108` | 同上,相对 now 生成 fixture 日期 | 非时敏(相对) |
| `test_235_f1_tradingday_caliber_20261009.py:51` | 显式冻结 `cdi.datetime.now()` | 已是正确做法(冻结式) |
| `test_237_preupload_relay_pytest.py:236` | `date.today()` 生成 fixture 命名 | 非时敏(相对) |
| `test_253_c1_night_full_defer_20261017.py:97-107` | 断言的正是「不得直取 date.today()」 | 静态守卫,非时敏 |
| `test_fapi_oom_fix_20261009.py:45` | 引用真实 `data/daily-k.parquet` | 需主控确认:仅有条件读取,未见时间断言;非本批范围 |

结论:除本文件外,**无第二个测试把「真实生产文件的时刻」与「真实时钟」做断言对比**。存量相对 now 构造的用例(上表多数)本质稳定;真正的时敏风险集中在「读真实状态文件 + 与 now 比大小」这一类,已扫完仅 test_224 一例。

## 6. 边界维度清单(§5.8① 七轴,tester skill §5.3.1 口径)

| 轴 | 测/不测 | 说明与来源 |
|---|---|---|
| 输入域(FAIL/OK/WARN 三种 res 状态) | 测 | `_fails` 仅 FAIL 返回内容;OK/WARN 返回 ""(既有 8/9 用例覆盖 warn/ok 分支);来源:改动点 `_fails` |
| 状态组合(fail+pending 混排 / 全 pending / 全 fail) | 测 | 全 pending:用例①;全 fail:用例③④;混排:新用例⑪ + 真实样本用例;来源:事故形态 |
| 时序(ready_at 在将来 / 已过 / 边界 ±1s) | 测 | 新用例 ready_at=now+3d+1h;真实用例锚 `max(ready_at)-1`(边界前 1 秒);平移 +2h/+1d;来源:L51 |
| 上下游依赖(依赖 check_task_state 生产语义) | 测 | 生产零改动,变异测试双向验证判定未被测试妥协;来源:派单要求 2/3 |
| 极端值(cron 不可解析 / 无 createdAt) | 测(既有) | 用例⑦ 覆盖退化路径;本次未改其契约;来源:既有回归 |
| 回退路径(CI 无真实 .claude/scheduled_tasks.json 时 skip) | 测 | 真实样本用例 skipif;CI 必跑守卫用例⑪ 不依赖真实文件,故 CI 仍有判别力;来源:派单要求 3 |
| 并发与重入(monkeypatch 时钟的进程级副作用) | 测(设计) | `_freeze_now` 只替换模块属性 `m.time`,不动标准库全局 ⇒ 无跨线程/其他用例污染;monkeypatch 自动还原;来源:`_freeze_now` 实现 |

## 7. 同类错误面清单(§23.2①)+ 举一反三(§23.3)

- 同类错误面:①`_fails` 混同 fail/pending(已修)②真实样本断言与真实 clock 不同源(已修)③同文件其他用例是否受影响 → 已逐条跑,20 passed ④生产侧是否有同类「同一 detail 字段混装两类语义」→ `check_zombie_crons` 是唯一把 pending 拼进 FAIL detail 的检查(其余 check_* 无 detail_pending 概念),故不扩散修改。
- 举一反三覆盖点:其他测试的时敏扫描(§5);`_pending_text` 保持原语义(OK 分支断言「不判僵尸」需要全量 detail),未被 `_fails` 改动波及。

## 8. 交付信息

- 分支:`feat/pf-screener-p1-20261019`(续跑,未新开分支;`git branch --show-current` 已确认)
- base commit:`30f7b4583`;`git merge-base --is-ancestor origin/main HEAD` = **base-stale**(本分支落后 origin/main;未擅自 rebase,避免改写他人已引用的 pf-screener 提交 hash;目标文件 diff vs origin/main 只有本次改动,合入无冲突)
- commit hash:`7b4e4d876`
- push:`30f7b4583..7b4e4d876 feat/pf-screener-p1-20261019`(只推 feat,未碰 main,未 force)