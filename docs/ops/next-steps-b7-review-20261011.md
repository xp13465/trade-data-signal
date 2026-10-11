# B7 独立审查报告 — test_245 两用例日期敏感修复(2026-10-11,只读)

> 任务:next-steps B 批 B7 — CI 红 P0 修复的独立审查(专项:防「改松测试」风险 + 确认日期无偏)。
> 执行:reviewer(role-reviewer);审查对象:分支 `fix/tests-date-sensitive-20261011`,远端 tip `eb837a7ef`(base=merge-base `5a8226b6a`,已核)。
> **残留后台任务:无。** 全程仅一次后台化 = 全量 pytest(nohup,pid 65450),81.46s 自然退出、结果已取回;无遗留进程/无 `moved to the background (ID:` 悬置项。
> **只读声明**:零改业务代码;唯一写入=本报告。审查过程创建过 3 个临时副本(旧版复现 / 日期扫描 / 冻结日对照),均已删除并 grep 复核 0 残留;未 push main、未 force。
> **总判定:PASS** —— 断言零改动(101/101 逐字一致)、修法语义等价(与 10-10 绿日实证一致)、日期无偏(6 日期全绿 + 函数体零真实时钟)、全量 `1 failed / 734 passed / 2 skipped` 独立复现、无改松痕迹。

## 0. 结论速览

| # | 审查项 | 判定 | 一句话证据 |
|---|---|---|---|
| 1 | 断言一字未改 | **PASS** | diff 中 `_chk` 行=0;全文件 101 条断言起始行逐字 diff 为空 |
| 2 | 修法语义等价 | **PASS** | 旧版+模块时钟冻结 10-10 → 两用例 2 passed(历史绿日=修后行为);机制代码逐行核 |
| 3 | 日期无偏独立复算 | **PASS** | 两函数体去注释后零真实时钟读取;6 组日期(含跨年/复发日)全绿 |
| 4 | 全量 pytest 独立复跑 | **PASS** | `1 failed, 734 passed, 2 skipped in 81.46s`,唯一红=test_188(归 B6)与报告逐位一致 |
| 5 | 同类扫描复核 | **PASS** | 抽查 6 例「非病灶」判定全部成立;独立交叉扫「patch datetime ∩ 真实时钟」仅 2 文件(含本病灶) |
| 6 | 红线自证 | **PASS** | 代码文件仅 1 个(未动 upload_r2.py);B7 commit 不在 main;1 commit;无 force 痕迹 |

## 1. 断言一字未改核实(机检三层,本审查最重要项)

1. **diff 层**:`git diff origin/main...HEAD -- scripts/tests/test_245_l2_budget_digest_20261010.py` 全部 +/- 行中 `_chk` 计数=**0**;改动仅 2 个 hunk,内容全部位于用例 setup 段(patch 时钟与条目日构造),断言段及其后上下文行原封。
2. **全文件层**:提取两侧全部 `_chk(` 起始行(101 条)逐字对比 → `diff` 为空(**101/101 一致**,含多行断言的首行;多行断言续行由 hunk 上下文未变佐证)。
3. **改动量层**:`+13/-4` 与派单描述一致;2 条删除=旧时钟混用行,4 条新增=注释 3 行+`_now` 同源化语句;无任何「放宽条件/删断言/改期望值/加 skip」痕迹。

结论:**未被改松**。断言与意图(「23:25 前 no-op」「隔日 stale 必发」)一字未动。

## 2. 修法语义等价(机制层 + 实证层)

**机制层**(`scripts/notify.py:_flush_digest_locked` L2380-2395 逐行核):
- `now=datetime.now()`(经 `_patch_now` 已把 `notify.datetime` 替换为固定值替身 → 全链路唯一时钟=patch 值);
- 条目按 `str(e.get('day'))==today` 分 due / stale;触发=`stale 非空` 或(`now>=23:25` 且 `due 非空` 且 `last_sent_day!=today`)。
- 修后链路:04 条目日=patch 日(10-10)→ 判 due → 12:00 前 no-op;04d 条目日=patch 日前一天(10-09)→ 判 stale → 必发。与意图逐点吻合。

**实证层**(同两用例三态对照,全部实跑):

| 版本 | 时钟源 | 真实日期 10-11 实跑 | 说明 |
|---|---|---|---|
| 旧版(origin/main) | patch 10-10 + 真实时钟**混用** | **2 failed** | 失败方向与修复报告表格逐字一致(test_04 得 `{'sent': True,'n':1,...}`;test_04d 得 `{'sent': False,'n':0,'n_remaining':1}`)→ 病灶复现 |
| 旧版 + 模块时钟冻结 10-10 | 全 10-10 | **2 passed** | 历史绿日行为实证 = 修复所锚定的等价基准 |
| 新版(HEAD) | 全同源 | **2 passed** | 任意日期均可复现绿日行为(见 §3) |

结论:修后语义与修前 10-10 绿日**逐点等价**;且两用例**判别力保留**——旧版实测两处语义反转(no-op 变必发 / 必发变 no-op)均被现有断言精确抓住。

## 3. 日期无偏独立复算(PASS)

- **结构化**:两用例函数体(HEAD L299-314 / L357-371)去注释后 grep `datetime.now` / `.today()` / `time.time` / `_today()` / `weekday` → **0 命中**。结果不可能依赖真实日期。
- **动态(换日期实跑)**:临时副本把两用例共用 `_now` 换为 6 组值,`-k "test_04_ or test_04d"` 逐组实跑:

| `_now` 值 | 说明 | 结果 |
|---|---|---|
| 2026-01-01 | 跨年边界(yday=2025-12-31) | 2 passed |
| 2027-03-15 | 派单指定 | 2 passed |
| 2028-06-30 | 派单指定 | 2 passed |
| 2026-10-10 | 原绿日对照 | 2 passed |
| 2026-10-11 | 复发日对照 | 2 passed |
| 10-10(原文件直跑,真实日=10-11) | 真·错位日 | 2 passed |

结论:**6/6 全绿**,既覆盖原绿日也覆盖复发日与跨年边界 → 与具体日期值无关。

## 4. 全量 pytest 独立复跑(PASS)

- 命令(与 CI 同命令同范围,ci.yml L123):`pytest -q scripts/tests/` → **`1 failed, 734 passed, 2 skipped in 81.46s`**(输出留存 `/tmp/b7-review-full-pytest.txt`)。
- 唯一红 = `test_188_s06_sync_blindspot_pytest.py::test_188_s06_sync_blindspot_wrapped`(归 B6,勿动;该文件不在本分支 diff,其红与 B7 改动无因果——B7 仅动 test_245 单文件)。
- 与修复报告数字**逐位一致**(1F/734P/2S)。
- 诚实标注:基线「`3 failed / 732 passed`」未整跑复核,以「旧版定向复现 2 failed(§2)+ test_188 独立红(本节)」两点覆盖该结论(3=2+1)。
- smoke 清单不适用:纯测试档改动、无用户可见面/数据产物 → 以全量套件 + CI 外部锚点(§7)替代。

## 5. 同类扫描复核(抽 6 例 + 独立交叉扫,PASS)

抽查 6 例被报告定性「非病灶」的用例,独立复核判定合理性:

| 文件 | 报告判定 | reviewer 复核 |
|---|---|---|
| test_235_f1_tradingday_caliber | `_freeze` 与数据参数同源 | 成立:冻结值=显式参数(同字面量),`_real_dt` 仅用于构造冻结实例;全固定、确定性 |
| test_196_patrol_visibility | 固定 dt 与 now 分处不同用例 | 成立:固定值=注入函数参数(与固定 state 对应);真实时钟=相对 now 偏移、同源自洽(报告该行措辞略松,判定正确) |
| test_224_zombie_cron_gate | 双时钟均为真实 now 相对偏移 | 成立:`time.time()-age`、`now+2d` 与被测代码同取真实 now |
| test_237_preupload_relay | 期望 key 与 fixture key 均取真实 today | 成立:L112/L121 两侧同用 `_today()` |
| test_s06_state_machine | `weekday()` 作用于固定基准日 | 成立:基准 `date(2026,1,7)` 固定,循环内 weekday 确定性 |
| test_241_family_b_consign | 数据与代码均真实时钟 | 成立(sign key 期望侧与代码侧同取真实 today) |

**独立交叉扫**(不走报告口径):全目录「monkeypatch 替换 `datetime` 属性 ∩ 真实时钟读取(`datetime.now()`/`date.today()`/`time.time()`)」交叉后**仅 2 文件** = `test_245`(本病灶)+ `test_235_f1_tradingday_caliber`(上表已核自洽)→ 报告「同型仅此 2 例」**成立**。

## 6. 红线自证核对(PASS)

- `git diff origin/main...HEAD --name-only` = `scripts/tests/test_245_l2_budget_digest_20261010.py`(**唯一代码文件**,+13/-4)+ `docs/ops/next-steps-b7-tests-date-fix-20261011.md`(修复报告)。**未动 `upload_r2.py`**、无其他代码文件。
- 分支仅 1 commit(`eb837a7ef`);`git merge-base --is-ancestor eb837a7ef origin/main` 判否 → **B7 未进 main**;远端分支 tip==本地 tip(无 force 痕迹:单 commit 直接坐落 base `5a8226b6a`)。
- origin/main 审查期间已前移(`5a8226b6a`→`6cd81e3db`),新增仅 TASKS.md 2 个文档 commit,与本分支文件**零重叠** → 后续 merge 无冲突面。

## 7. 外部锚点(CI 实拉,独立于修复报告)

- GitHub API 实拉 main 的 `CI Quality Gate` 历史:UTC **10-10 全部 4 runs success**、UTC **10-11 起全部 runs failure** → 与「10-10 绿、10-11 起红」逐点吻合。
- 注:CI 跑在 UTC 时钟,翻红时刻=UTC 翻日(北京约 08:0x 起);base commit `5a8226b6a` 的 run 失败 job=`quality-gate-static`(含 pytest 步),`quality-gate-data` success。job 日志下载需 admin 权限(403),未取正文;以「job 级失败 + 本地定向复现」双证替代。

## 8. 问题清单

- **无 ≥80 分 finding。**
- 已滤低分项(<80,共 2 条,防黑箱列明):
  1. (≤50 措辞类)修复报告 §5 对 test_196 的描述语「前者配固定 state,后者配真实 state」表述不精确(实为:固定值注入函数参数 / 真实时钟取相对偏移);判定结论本身正确,不影响修复正确性。
  2. (50 分,观察项,**pre-existing 非本 diff 引入**)多个测试存在「期望值取真实时钟 vs 被测代码执行时取真实时钟」的跨午夜微竞态(如 test_237 期望 key 取 `date.today()` 后调用代码;test_196 同段两取 now 之间亦同型)。暴露窗毫秒级、全目录同模式、非本分支引入。按 §10.3 不为本次 finding,如实记录供主控决定是否登记后续(不建议随本分支处理)。

## 9. 总判定

**PASS** —— 未改松测试(断言 101/101 逐字一致)、修法语义等价(旧版冻结日实证)、日期无偏(6 日期全绿 + 零真实时钟)、全量数字逐位复现、红线全过。可进 merge 链(内审门槛已过);B7 分支 merge 后预计 main CI 从「2 日期红」减至「仅 test_188 红」(待 B6 分支覆盖)。
