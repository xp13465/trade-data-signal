# B7 修复报告:CI 日期敏感测试(10-11 起必挂)—— test_245 两用例时钟同源化

**残留后台任务:无**(本次全程命令均短、未出现 `moved to the background (ID:`;无遗留后台进程)。

- 分支:`fix/tests-date-sensitive-20261011`(自 `origin/main` 切,base commit = `6cb62b5b4`)
- 日期:2026-10-11(休市日;未推 main、未 force)
- 改动文件(1 个 / 13 insertions, 4 deletions):
  `scripts/tests/test_245_l2_budget_digest_20261010.py`

---

## 1. 病灶(日期敏感,与业务代码无关)

`test_245` 两个用例把「patch 时钟」(硬编码固定日 10-10)与「真实时钟 helper」混用,
断言依赖两者的**日期关系**。日历翻到 10-11 后真实日 != patch 日,关系反转 ⇒ 断言必挂
(10-10 当天恰好一致,故当时绿)。

| 用例 | patch 时钟 | 数据构造时钟 | 10-11 实得 |
|---|---|---|---|
| `test_04_flush_before_2325_noop` | `datetime(2026,10,10,12,0)` | `_entry(_today())` = **真实**今日(10-11) | `{'sent': True,'n':1,'n_remaining':0}`(本应 no-op) |
| `test_04d_flush_stale_next_day_sends` | `datetime(2026,10,10,12,0)` | `yday = datetime.now()-1d` = **真实**昨日(10-10) | `{'sent': False,'n':0,'n_remaining':1}`(本应必发) |

机制(`scripts/notify.py:_flush_digest_locked`):`now=datetime.now()`;条目 `day==today`
判 **due**,否则判 **stale**。触发 = stale 非空 **或**(now>=23:25 且 due 非空 且
last_sent_day!=today)。
- 04:条目日(10-11)!= now 日(10-10)⇒ 判 stale ⇒ 12:00 也发(断言语义反转)。
- 04d:条目日(10-10)== now 日(10-10)⇒ 判 due 但 12:00<23:25 ⇒ no-op(断言语义反转)。

## 2. 修法(最小正确改,原断言意图不变)

把两个用例的数据构造时钟**锚到 patch 的那个固定时刻**(同一变量 `_now`),
patch 时钟与数据时钟**同源** ⇒ 结果只由常量驱动,与真实日期彻底解耦。

- 04:`_seed_digest(..., [_entry(_now.strftime("%Y-%m-%d"))])` —— 条目日 = patch 日。
- 04d:`yday = (_now - timedelta(days=1)).strftime("%Y-%m-%d")` —— 条目日 = patch 日前一天。
- 断言(no-op / 必发 / 含前日遗留)一字未改,断言语义与 10-10 当天完全一致。

## 3. 变更行(精确)

```
@@ test_04_flush_before_2325_noop
-    _patch_now(monkeypatch, datetime(2026, 10, 10, 12, 0, 0))
-    _seed_digest(_iso["alerts"], [_entry(_today())])
+    _now = datetime(2026, 10, 10, 12, 0, 0)
+    _patch_now(monkeypatch, _now)
+    _seed_digest(_iso["alerts"], [_entry(_now.strftime("%Y-%m-%d"))])
@@ test_04d_flush_stale_next_day_sends
-    yday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
-    _patch_now(monkeypatch, datetime(2026, 10, 10, 12, 0, 0))  # 非 23:25 也发(stale)
+    _now = datetime(2026, 10, 10, 12, 0, 0)
+    yday = (_now - timedelta(days=1)).strftime("%Y-%m-%d")
+    _patch_now(monkeypatch, _now)  # 非 23:25 也发(stale)
```
(各用例另加 3~4 行注释说明病灶与同源要求。)

## 4. 自验证据

1. **改前复现**(HEAD `6cb62b5b4`):
   `pytest -q scripts/tests/` → `3 failed, 732 passed, 2 skipped`;
   其中 2 红 = 本任务两用例(04/04d),另 1 红 = `test_188_s06_sync_blindspot_pytest.py`
   (他人修的真 bug,**按派单勿动**)。证据 `/tmp/b7-baseline-pytest.txt`。
2. **改后**:
   - 目标文件:`pytest -q scripts/tests/test_245_l2_budget_digest_20261010.py` → **38 passed**。
   - 全量:`pytest -q scripts/tests/` → `1 failed, 734 passed, 2 skipped`;
     唯一红 = `test_188`(非本任务)。**本任务用例全绿**。证据 `/tmp/b7-postfix-pytest.txt`。
3. **日期无偏论证**:
   - 结构化:改后两用例函数体内**零真实时钟读取**(无 `.now()/.today()/time.time()/_today()`;
     仅注释文字提到这些词)。结果不可能依赖真实日期。
   - 动态模拟「换一天」:把两用例共享的 `_now` 常量分别换成
     `2026-01-01 / 2026-10-10 / 2026-10-11 / 2026-12-31 / 2027-03-15 / 2028-06-30`
     六个日期字面量(临时副本运行后即删),两用例 **6/6 全绿**
     (`2 passed` × 6)。既覆盖原绿日(10-10)也覆盖复发日(10-11),证明与具体日期值无关
     ⇒ 与真实日期无关。

## 5. 同类扫描清单(§23.2 三铁律)

扫描面:`scripts/tests/` 全量(`--include='*.py'`),三组机检:
1. 时钟替身:`_patch_now` / `class _DT` / `setattr(*,"datetime")` / `_FrozenDT`
2. 硬编码日:`datetime(2026` / `datetime.datetime(2026`
3. 真实时钟:`datetime.now()` / `.today()` / `date.today()` / `time.time()`
4. 真实星期几:`weekday()` / `isoweekday` / `isocalendar`

**结论:同型病灶仅 test_245 两例**;其余全部为「同源自洽」,判定如下:

| 文件 | 现象 | 判定 |
|---|---|---|
| `test_235_f1_tradingday_caliber` | `_freeze` 冻结 `cdi.datetime` | 数据参数(`date/today` 列)与冻结值同源 ⇒ 自洽,**非病灶** |
| `test_235_f1_monitor72h_appcal` | 固定 `datetime(2026,10,6)` 与 `_table` 同源 | 全固定、自洽,**非病灶** |
| `test_196_patrol_visibility` | 既有固定 `datetime(2026,10,5)`,又有 `datetime.now()` | 分处不同用例(前者配固定 state,后者配真实 state),无「同用例内混用」,**非病灶** |
| `test_224_zombie_cron_gate` | `time.time()` + `datetime.now()` | 两者都相对真实 now 取偏移,自洽,**非病灶** |
| `test_228_round_incomplete` | 固定 `NOW` + 固定 `_row` ts | 同源固定,自洽,**非病灶** |
| `test_240` / `test_241_family_rc_sent_sweep` / `test_181` / `test_monitor_resource_inprogress` | 固定 `datetime(2026,...)` 配固定输入串 | 自洽,**非病灶** |
| `test_132_morning_slot` | 固定 dt + slot 字符串 | 参数化输入,自洽,**非病灶** |
| `test_237_preupload_relay` | `date.today()` | 期望 key 与 fixture key 均取真实 today,同源,**非病灶** |
| `test_241_family_b_consign` | `datetime.now()` | 数据与被测代码均真实时钟,同源,**非病灶** |
| `test_alertchain_hardening` | `time.time()` | 单一时钟,无混用,**非病灶** |
| `test_s06_state_machine` | `weekday()` | 基准日 `date(2026,1,7)` 固定,`weekday()` 作用于固定日 ⇒ 确定性,**非病灶** |
| `test_188_s06_sync_blindspot_pytest.py` | —— | 另一真 bug(他人修),无时钟混用特征,**勿动** |

「同源化」判据:同用例内 patch/freeze 时钟与数据构造时钟取自**同一源**(同固定值或同真实值);
本任务前唯一违反者 = test_245 的 04/04d。

## 6. 举一反三 / 复用点(§23.3 / §6.5)

- 复用:沿用文件既有 helper `_patch_now` / `_entry`,**零新增抽象**;不重写副本。
- 根因修:在「patch 与数据同源」这一个根因点改,**不逐用例打补丁**。
- 同模式面(全部 patch+真实混用者)已在 §5 穷举并逐条定性;相关展示位 = 不适用(纯测试档,无前端/数据产物)。

## 7. 复现命令

```bash
cd <worktree or trade root>
# 复现旧红(10-11 当天):
git checkout 6cb62b5b4 -- scripts/tests/test_245_l2_budget_digest_20261010.py
/Users/linhuichen/code/trade/.venv/bin/python -m pytest -q \
  scripts/tests/test_245_l2_budget_digest_20261010.py -k "test_04_ or test_04d"
# 验修后:
/Users/linhuichen/code/trade/.venv/bin/python -m pytest -q scripts/tests/
# 期望:唯一红 = test_188_s06_sync_blindspot_pytest.py(非本任务)
```

## 8. 红线合规

- 未 push main、未 force push;仅 commit + push feat 分支。
- 未动 `upload_r2.py`(归另一任务)。
- 凭证不进 git;所有命令短时执行、无残留后台任务。
- git 全程无冲突/覆盖/倒退事件(§23.11);单文件单点改动。
- 索引/任务状态:本块(B7)未登记于 `docs/pending-features-index.md`,报告落 `docs/ops/`
  (与 B1/B3/B4/B5 同约定);登记归主控,本次未擅自改索引。