# #238 fapi OOM 治本 — 独立审查报告(reviewer)

- 日期:2026-10-09 | 审查对象:`feat/238-fapi-oom-20261009`(tip `69b718ced`,parent `aeadb9047`)
- 代码位置:worktree `/Users/linhuichen/code/trade/.claude/worktrees/agent-adef2a5e01eb42947/`(全程只读,未改任何文件、未做任何 git 写)
- 总判:**有条件 merge**——9 项必审全 PASS;唯 1 条条件 = Finding 1(守卫时序变化)需二选一处置(修复 or 落档明示并随 #238 拍板确认);其余为建议项,不阻断

---

## 逐项结论(9 项必审)

### ① §15 回归(正常增量路径行为一致) — PASS
逐块 diff 新 `run()`/`process_parquet()` vs 旧版(`git show aeadb9047:app/collector/fapi_daily.py` → /tmp/old_fapi_daily_238.py):
- UPSERT SQL 字符串逐字相同;写入字段集相同;日志文案相同;返回 dict 键相同(rows/dup/amt_ok);dest 清理相同。
- 行为差异 3 处,逐一定性:
  (a) 守卫校验时机:旧=写前(过了才 map+写);新=流式逐批写完后在 `process_parquet` 尾部判(`:342-367`)。**异常路径行为变化,见 Finding 1**。
  (b) 增量路径亦改为流式(旧走 map_frame):语义等价,已由独立对账证逐位一致(见 ②)。
  (c) 非连续分组 dump:旧=全局 sort 后静默正确处理;新=`_iter_groups` 守卫抛 RuntimeError。属故意 fail-loud(落档 §1/§4);且真实 10 年 dump 在探针跑通(ROWS=10316588)已证连续,实际数据不触发。
- 正常增量路径(库已有最新交易日数据、dump 连续)行为与旧版完全一致。

### ② 流式 == 全量 物化(逐位对账) — PASS
- 仓内对账测试真实存在:`test_streaming_equals_reference_oracle` 参数化 bs=[1,7,13,120,999],`assert got == ref` 逐位比,且覆盖跨批切组。
- 诚实标注其边界:oracle(`map_frame`)与生产共用 `_map_group` ⇒ 仓内测试只覆盖「分组/分批/缓冲」层,不覆盖 `_map_group` 自身迁移史。
- **我补了独立对账**(第二实现,不共享任何代码):旧版 `aeadb9047` 实现 vs 新版流式,在 fixture + 我构造的边界样本(乱序/NaN/0/单行/非连续/NaN 传播链)上 Python 层逐位一致(bs 全谱);DB 层用内存 SQLite 复算,120 行 + 13 行两样本**逐位相同**。
- 唯一差异:`nan` vs `None`(Python 层 dtype 推断),已证 DB 等价(旧 nan 绑进 SQLite 存为 NULL,新 None 亦 NULL;`typeof` 复核)→ 落库无差。

### ③ 防前视(§5.1⑥) — PASS
- 闸门 `latest < d <= today_s`(`fapi_daily.py:399-428`)显式,只数 (latest, today] 交易日。
- 5 个边界实测(用 worktree 真实日历缓存):非交易日 today / future latest / 空日历(降级 weekday 启发式不崩)/ 坏日期(保守走 full)/ 下界 ==latest 不计入——全 OK。
- 阈值 10 交易日与 `daily-k-10d` 覆盖窗(10 交易日)对齐:gap=10 恰覆盖,11 才切 full;短暂滞后 1 天次跑自愈。
- 反证测试带区分度(无闸门会数出 11 > 10 误判 full),非恒真式。

### ④ 旧常量残留 — PASS
- 生产代码无旧 `STALE_DAYS`(仅注释交代历史,`fapi_daily.py:72`);中间态 env `FAPI_STALE_DAYS` 无代码引用;`fapi_daily_syn.sh` 不带任何 env ⇒ 无效 env 迁移负担,默认值即生效路径。
- 前端 `static-site/app.js` `STALE_DAYS=30` 经核为同名不同物(卡片陈旧标记),非同一登记点。
- §21 算法公示:前端仅两处 FAPI 提及(grep 实证),均为数据源说明、与「何时切全量」口径无关 ⇒ 公示无需同步。

### ⑤ §23.2 同类错误面 — PASS
- 全仓(排除 .git/static-site/node_modules/data)大小写不敏感扫描 `read_table|read_parquet|ParquetFile|iter_batches|read_row_group|to_pandas`:生产代码仅 `fapi_daily.py` 一处(已修);`docs/fapi/scripts/probe_fapi.py` 为无调用方本地只读探针,不改合理;其余 0 命中。
- 单点病灶、根因修,无第二处需同款补丁。

### ⑥ 测试真实性 — PASS
- 16/16:15 项 + 峰值 1 项(我实跑 62.41s 通过);fixture 为真实 dump 切片(120 行/4 thscode/11 列真实 schema/连续)。
- red-first 方向静态复核:旧版模块无 `STALE_TRADING_DAYS`/`_iter_groups`/`process_parquet`,`_stale` 无 `trading_days_fn` 参数 ⇒ 新测试在旧版上必然大面积红,与实施报告 15 failed 一致(全量 red-first 重放需覆盖 worktree 文件,受「禁改」约束,以静态符号缺失 + 独立对账等效替代)。
- 断言打点真实:对账断言逐位、守卫断言 raises、防前视断言带反证,非「解析器恒真」式假绿(§18 L49 规避)。

### ⑦ 文档一致性 — PASS(带 1 条补充发现)
- `docs/fapi/fapi-integration-plan-20260901.md:110`(>7 自然日)确为**日期化历史 plan 文本**,且它在旧代码时代(≥8)就已过时;非用户可见面、非契约执行面。实施 agent 已在落档 §8.1 主动标注供拍板 ⇒ 达标,**不必同步改**(历史记录),可选加一行注记。
- **补充发现**:`docs/fapi/fapi-p0-implementation-20260902.md:38` 亦含旧口径文本「≥8 自然日」——同为日期化历史实施记录(2026-09-02,自称「纯新增试点」),非现行机制说明;实施报告 §8.1 只点了 20260901 一处,此份为对称遗漏。非阻断,建议顺手在 20260901+20260902 两份加同款一行注记(一次覆盖,§23.3)。

### ⑧ 全量 pytest — PASS
- 我独立实跑:400 passed / 2 skipped / 88.44s(实施报告 90.19s,一致);基线 384 + 新增 16 = 400 自洽。
- CI 风险:CI(Job1)已 pin numpy/pandas/pyarrow,conftest 对 requests/akshare 打桩,fapi import 链已覆盖;两条重量级用例(真实 dump/真实日历)在 CI 自动 skip,无新红风险。

### ⑨ merge 就绪性 — PASS
- `git diff --name-only origin/main origin/feat/...`:恰 5 文件=预期(app/collector/fapi_daily.py + 测试 2 + fixture + docs/ops 落档),无夹带。
- merge-base..origin/main 新增仅 docs/ops 云上加固文件,与本分支**交集 0** ⇒ 干净可合;远端 feat ref == 本地 tip `69b718ced`。
- 备注(主控流程):`docs/pending-features-index.md` #238 状态列仍「待拍板…均未实施」已过时(①④⑤本分支已实施、②③云上加固已在 main),merge 收尾时按 §23.12-1 三连刷新。

## 亮点
- 峰值实测口径诚实:290MB / 旧 2786MB(9.6x),且主动标注「地板=pyarrow row group 级解码(284MB),非 batch 参数决定」+ 上游 row group 变大的量化风险(~380MB),不夸口「任意 dump <300MB」。
- `_stale` 复用项目既有 `app/calendar.trading_days_between`(未另造第二份日历,§5.4⑦ 慎)。

## Findings(必须处置 1 条 + 建议 4 条)

### Finding 1(条件项,阻断 merge 需先处置)守卫由「写前检」变「写后检」
- 旧:dup/amt_ok 校验在 map+写之前,失败 ⇒ **零写入**;新:流式逐批 `commit` 后才在尾部校验,失败 ⇒ **已写入的批次留在库里**(raise 有告警、UPSERT 幂等可恢复,但该守卫本意=坏数据不进库)。
- 触发面 = 数据契约破坏(主键重复 / turnover-volume 命名翻转超限),正常路径不触发(真实 dump 实测连续、守卫全过)。
- 建议二选一(主控/用户定):
  (a) 修:两遍扫描——pass1 只统计 dup/amt_ok(不映射不写),通过后 pass2 映射+写。代价:full 路径 +15~20s(预算充裕)。
  (b) 落档明示:在 `docs/ops/fapi-daily-oom-fix-20261009.md` §4 补一句「守护断言的口径等价、但校验时机由写前改为写后(异常时可能残留部分批次,幂等可恢复)」,并随 #238 拍板一并确认。
- 注:现行落档 §4 只写了「防御断言与旧全量口径等价」,未披露时序变化,单看文档会被误读为完全等价。

### 建议项(不阻断)
2. `upsert_rows()`(`:370-379`)已无调用方(死代码 ~10 行),可删或标注保留理由。
3. 仓内对账 oracle 与生产共享 `_map_group`:建议后续把「旧实现黄金输出」固化为 fixture(我的独立对账是一次性的,没入库),防未来 `_map_group` 再改动时无独立锚。
4. docs 注记:20260901 plan + 20260902 实施报告各加一行「口径已于 2026-10-09 改为交易日 >10,见 fapi-daily-oom-fix-20261009」。
5. 信息性:Python 层 nan vs None 差异(DB 等价已证),不必处理。

## 复现(本次审查用过的关键命令)
- 对账:/tmp/check_equiv_238.py、/tmp/check_equiv2_238.py(旧版取自 `git show aeadb9047:app/collector/fapi_daily.py`;构造样本 /tmp/edge_238*.parquet)
- pytest:worktree venv `/Users/linhuichen/code/trade/.venv/bin/python3 -m pytest -q scripts/tests/`(先证 `fd.__file__` 落在 worktree,防 symlink 假绿)
- 日志:/tmp/fapi_peak_test.log、/tmp/fapi_full_pytest.log
- 约束遵守:只读;未跑 `fapi_daily.run()/process_parquet()` 对生产库;pytest 为唯一执行例外;`fapi_oom_mem_probe.py` 先静态读源码证只读后才跑;零外发;无残留后台任务。
