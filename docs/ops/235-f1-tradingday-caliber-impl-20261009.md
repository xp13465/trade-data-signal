# #235 F1 实施报告:数据新鲜度校验「自然日 → 交易日」口径(2026-10-09)

- 角色: 实施 agent | 分支: `worktree-agent-a075c2034c69c77f0`(worktree 隔离)
- 设计稿(已定稿): `docs/ops/235-f1-tradingday-caliber-design-20261009.md`
- 改动文件: `scripts/check_data_integrity.py`(helper + 8 处替换 + docstring + 16 处文案)
  + `app/calendar.py`(新增口径权威实现 `lag_trading_days`)
  + `scripts/monitor_72h.sh`(ad_line 同病根第三处)
  + 新增 `scripts/tests/test_235_f1_tradingday_caliber_20261009.py`
  + 新增 `scripts/tests/test_235_f1_monitor72h_appcal_20261009.py`(续跑, 见 §10)
- 本次自测**零外发**(全程 monkeypatch `_fetch_r2_json`,ZeroOutboundTrap 兜底,见 §5)

## 1. 结论摘要

1. 新增 helper `_lag_trading_days(date_str) -> int | None`,插在 `_days_ago` 之后(原 L162 后,现 L165)。
   公式 = `max(len(trading_days_between(date, today)) - (1 if is_trading_day(date) else 0), 0)`;
   契约同 `_days_ago`:解析失败返 None。
2. **8 处替换全部落地**;`_days_ago` **保留 2 处**(overview / fund_score)+ nextday_plan 降级分支不动,与稿一致。
3. **稿行号逐条复核:全部实读一致**(8 处 + 2 处不改 + 1 处降级),无偏差(见 §2)。
4. 两道护栏均落地且**有专门测试**:①日历未覆盖 today → 回退自然日(真实日历 2030 远期案例 + 打桩强制)
   ②任何异常 → 回退自然日 fail-safe。
5. 自测 **55 passed**(含稿 §4.3 的 15 组数值表逐位比对、稿 §8.1/§8.2 判据 A/B、s06 档间翻转、
   §15 回归、静态锁);全量 `scripts/tests/` **517 passed / 2 skipped / 0 failed**。
   **续跑**(文案 + monitor_72h 第三处 + 口径单一事实源)另见 **§10**(全量 563 passed)。

## 2. 稿行号逐条复核(任务项 1)

| 稿称 | 实读(改前) | 结果 |
|---|---|---|
| overview 不改 L267 / fund_score 不改 L507 | L267、L507 | ✅ 一致 |
| alert L428 / notifications L456 / ad_line L541 / a_stock L573 | 逐一命中 | ✅ 一致 |
| trade_sim mtime L739 | L739 | ✅ 一致 |
| accum_nav_map L996 | L996 | ✅ 一致 |
| s06 本地门槛 L2141 / s06 R2 L2210 | L2141、L2210 | ✅ 一致 |
| nextday_plan 降级 L1986 | L1986 | ✅ 一致 |
| accum_nav_map docstring L985-986 | L985-986 | ✅ 一致 |

改后行号整体下移(helper 段 +34 行):`_days_ago` 调用余 L301(overview)/L541(fund_score);
`_lag_trading_days` 调用在 L462/490/575/607/773/1032/2177/2246。

## 3. 改动清单

- **helper**:`_lag_trading_days`(`scripts/check_data_integrity.py:165`)。
  - 借 `app.calendar` 的 `is_trading_day` / `last_trading_day` / `trading_days_between`(函数内
    `sys.path.insert`,与同文件 `check_signal_accum_nav_lag` 先例同款)。
  - 护栏①:`if not is_trading_day(last_trading_day(today)): return 自然日`。
  - 护栏②:`except Exception: return 自然日`。
- **8 处替换**(均为 `_days_ago(...)` → `_lag_trading_days(...)`,不含其它改动):
  alert / notifications / ad_line / a_stock / trade_sim(mtime 版多一行 `if days is None` 纯防御)
  / accum_nav_map / s06 本地门槛 / s06 R2。
- **docstring 修正**:`check_accum_nav_map_fresh` 的「口径与 check_overview 一致(自然日…)」→ 交易日口径
  (稿 §7.3 第二 bullet 标「必须修正」,原因:改口径后原句与实现矛盾)。
- **未改**:阈值常量(`STALE_DAYS_WARN=3`/`STALE_DAYS_FAIL=7`)、所有 FAIL/WARN 判据。
- **文案(续跑补,§10)**:8 处口径点的用户可见消息「天」→「交易日」(含阈值显示),见 §10。

## 4. 护栏实现(任务项 3)与实测证据

| 护栏 | 测试 | 结果 |
|---|---|---|
| ①日历未覆盖 today(真实日历) | `test_03`:冻 today=20300615,date=20300601 → 期望自然日 14 | PASS,g=14 且 ≠0(挡住「未覆盖→lag 恒 0」静默放松) |
| ①日历未覆盖 today(打桩) | `test_03b`:打桩 `is_trading_day`→False → 期望自然日 19 | PASS |
| ②异常 → fail-safe 自然日 | `test_04`:打桩 `trading_days_between` 抛异常 → 期望自然日 19 | PASS |
| 契约:解析失败 → None | `test_02`(7 组非法输入,含 None/空/非 8 位/带分隔符) | PASS,全部 None |

## 5. 测试结果(任务项 4/5)

`/Users/linhuichen/code/trade/.venv/bin/python -m pytest -q scripts/tests/test_235_f1_tradingday_caliber_20261009.py`
→ **55 passed**(断言 ~90,`_MIN_ASSERTIONS=60` 兜底防假绿)。覆盖:

- **①数值表(稿 §4.3,15 组)**:新 lag 逐位等于设计表,**并同时断言旧自然日对照值**
  (判别力证据:两口径确有差异,如 date=20260930@today=20261008 → 新 1 / 旧 8)。
- **②判据 A(长假后首日不误报,稿 §8.1)**:6 项数据 date=20260930、today=20261008 → 全部 lag=1 → OK
  (alert/notifications/ad_line/a_stock/accum_nav/trade_sim/s06 逐项断言)。
- **③判据 B(真过期仍报,稿 §8.2)**:每项 WARN 首现档与 FAIL 首现档逐项断言
  (alert/s06 WARN≥5、notifications WARN≥2、ad_line/a_stock/accum_nav/trade_sim WARN≥4;FAIL 均≥8)。
- **④边界(稿 §8.3)**:当日=0 / 昨日=1 / 假期中=1 / 未来日期 clamp=0 / 周末 today 不误报。
- **⑤s06 档间翻转(稿 §2.2)**:today=20261008、coverage_end=20260930 → 旧自然日 8 > 7(翻转诱因)
  vs 新交易日 1 ≤ 7 → `local_fresh=True` 走 ① 本地互证 → OK(改后稳定,不再 allow/deny 翻转)。
- **⑥§15 回归(任务项 5)**:overview / fund_score 仍自然日口径(2 天→OK、8 天→FAIL,断言口径未变);
  #188 ①b 兼容(coverage_end=today → OK;R2 落后 → WARN 不 FAIL)。测试 `test_188` 脚本式 + pytest 包装**双跑 PASS**。
- **⑦静态锁**:AST 断言 `_lag_trading_days` **恰好 8 处**且落在 7 个预期函数(s06 占 2);
  `_days_ago` **恰好 2 处**且仅 check_overview / check_fund_score。阈值常量与判据措辞未变。

**全量回归**:首版 `pytest -q scripts/tests/` → **517 passed / 2 skipped / 0 failed**;续跑后(含文案 + monitor_72h
+ app.calendar 单一事实源)→ **563 passed / 2 skipped / 0 failed (91.65s)**,详见 §10。

## 6. §23.3 举一反三:其它「日期维度判据」清单(任务项 7)

同模式搜索面(全仓 `.days` / 「滞后」全量):

**A. 同病候选(自然日新鲜度判据,长假后可能误报)—— 本任务**不动**,建议单开任务**
1. `scripts/monitor_72h.sh:772-794` `ad_line.json` 检查:**纯自然日** `(NOW.date()-date).days > 3 → SEVERE,
   无交易日豁免。长假后首日(date=09-30,today=10-08,age=8>3)会误报 SEVERE。**机制不同**(SEVERE 监控
   告警,非 deploy 闸门)+ 不在 #235 F1 scope(本任务只动 check_data_integrity)→ **续跑已改**(见 §10)。
2. `scripts/check_nt_signals.py:185-192` 邮件标签 `T-{gap}数据`:natural gap,长假后标签偏大(如 T-8)。
   属**展示标签非闸门**,且改动会动邮件文案 → 未动,列此备查。

**B. 已交易日口径(无需改,同类已对齐)**
- ~~`scripts/monitor_72h.sh:741-770` overview / alert:已用 `TODAY/LAST_TRADING_DAY` 集合豁免(交易日感知)✓~~
  **【更正 2026-10-09 复审:此结论错】** 该处白名单**并非**交易日感知 —— `LAST_TRADING_DAY`/`ALERT_EXPECTED_DATE`
  当时是**周几算术**(周六→周五、盘前 offset),**不看交易日历**,长假工作日(如 10-06 周二)会算出
  「今日=交易日」;且 alert 的 else 分支是**纯自然日 `>3`**。属**同类病灶**,已补正,见 §11。
- `scripts/check_s06_freshness.py`:独立交易日兜底链 ✓
- `scripts/signal_kelly_snapshot.py:329` `trading_days_lag`:已交易日 + 自然日 fallback ✓
- `scripts/check_data_integrity.py` 内 `check_signal_accum_nav_lag` / `check_nextday_plan`(allowed 集合)✓
- `scripts/fapi_daily.py`(#238 已把自然日 STALE 改 10 交易日)✓

**C. 语义不同,不动**(自然日该保留)
- `check_data_integrity.py:1122` 季度发布规则(`qe+20 天 <= today`)、`:1470` `_latest_published_quarter_end`
  (CCASS 季度末 +20 天)—— 发布节奏,非日频新鲜度。
- `check_data_integrity.py:1395` `check_fund_nav._dir_note` 方向诊断注记(非 pass/fail)。
- `check_north_gap_backfill.py:74/166/173` 自然日 gap —— 决定**补多少天**,非「是否过期」告警。
- `scripts/us_stock_morning.py:238` 美股补采阈值(美股日历,非 A 股)。

**D. 本文件内保留自然日(稿 §6 已定)**:overview(L301)/ fund_score(L541)/ nextday_plan 降级(L1986)。

## 7. §23.4 团队协作 / 索引对账(任务项)

- `docs/pending-features-index.md` **#235(row 362)** 状态「待拍板」,处置选项②=「根治=6 项改交易日口径」——
  **本任务即选项②的实现**(范围扩到 8 处含 trade_sim/s06 R2,与设计稿 §3 穷举结论一致)。
- 同模块邻项:#236(alert 自锁,结构性,设计 §1.7 标**不在本实施规格**)、#238(同「自然日口径」家族,
  已独立修毕)、#199/#198(同 check_data_integrity 家族)。**无同模块并行占用冲突**(改动只在
  check_data_integrity.py,与 #236/#238 的文件不重叠)。
- §21 算法公示:**不适用** —— 本次改的是 deploy 闸门的新鲜度口径,非前端评分/权重/匹配算法;
  已 grep `static-site/*.js|*.html`(排除 min)确认无「数据新鲜度/滞后天数」用户公示点。

## 8. 诚实标注(与派单约束的取舍)

- **消息文案**:首版按派单硬约束(消息结构不动)未改;主控随后拍板**必改**(§5 一步到位,字面须跟口径一致)
  → 续跑已把 8 处口径点的「天」改「交易日」,见 §10。**只改文本字面,lag 算法/阈值/判据一行未动。**
- **docstring 已改**:稿 §7.3 第二 bullet 标「**必须修正**」(原句与实现矛盾,不改即为错误描述),
  且非用户可见文案 → 已改。若主控认为该并入上条一并暂缓,撤这一处即可(仅 3 行)。
- 稿 §1.7 / §9.3 的「给 alert 增补本地 vs R2 差异只 WARN」是**可选增强、非本规格** → **未做**(按任务项 6)。
- 稿 §9.4 mtime 时区依赖未改变(非新增风险)。

## 9. 复现段(可独立复跑)

> 注:下方 `# … passed` 为**首版(df3c73ea4)时点**的数字;续跑/复审后的最新数字见 §10.5 / §11.4。

```bash
cd <worktree>
/Users/linhuichen/code/trade/.venv/bin/python -m pytest -q scripts/tests/test_235_f1_tradingday_caliber_20261009.py   # 55 passed
/Users/linhuichen/code/trade/.venv/bin/python -m pytest -q scripts/tests/                                           # 517 passed / 2 skipped(首版时点)
/Users/linhuichen/code/trade/.venv/bin/python scripts/test_188_s06_sync_blindspot.py                                # ALL_PASS
```
判别力(red-before-green):`test_08a/08b` 静态锁在旧代码上必 FAIL(旧=9 处 `_days_ago`/0 处新 helper);
`test_01` 数值表同时断言新旧两口径值,若 helper 未换口径即 FAIL。

## 10. 续跑:文案口径 + monitor_72h 同病根第三处 + 单一事实源(2026-10-09,同分支)

主控追加两件(同一 feat 分支 `worktree-agent-a075c2034c69c77f0`):

### 10.1 必做 · 文案口径(「天」→「交易日」)

- 范围 = 8 处口径点里**用户/运维可见的消息文本**(含阈值显示),逐处改:
  `alert`(FAIL/WARN/OK 3 处)、`notifications`(3)、`ad_line`(3)、`a_stock`(2)、
  `trade_sim_indices mtime`(3)、`accum_nav_map`(3)、`线上 S06 快照`(2)—— 共 **19 行消息文本**
  (复核实测:alert 3 + notifications 3 + ad_line 3 + a_stock 2 + trade_sim mtime 3 + accum_nav_map 3
  + S06 线上 2 = 19;另 s06 docstring 1 行,故报「19 消息行 + 1 docstring」)。
  形如 `滞后 {days} 天 > {STALE_DAYS_FAIL} 天` → `滞后 {days} 交易日 > {STALE_DAYS_FAIL} 交易日`。
- s06「本地门槛」那处无用户可见消息(只有「格式异常」不含「天」)→ 无文案改动;
  其 docstring「近 7 天」→「近 7 交易日」一并校正。
- **只改文本字面**:lag 算法、阈值常量、FAIL/WARN 判据**一行未动**(静态锁 `test_08c` 仍在守)。
- **未改**(口径本就自然日,不能改字面):`check_overview` / `check_fund_score` 的全部消息
  (首版 `_ok` 行因与 alert/notifications 同形被 `replace_all` 误改 1 处,已即时回退为「天」,
  见下「自纠」)、DB 领先/落后 `_dir_note`(不同功能)、nextday_plan 降级分支。
- **无多语言分支 / 拼接模板**:8 处均为单 f-string,无 i18n 分支,无跨行拼接(唯一跨行的是
  trade_sim FAIL 的相邻字面量,已随改)。
- **测试断言字符串**:grep `scripts/tests/` 全量确认**无**断言这些消息串(原有 235 测试只断言
  `.status` / 源码静态串)→ 无需同步测试字符串。
- **自纠记录(§23.11 不静默)**:`return _ok(name, f"date={date_str} (滞后 {days} 天)")` 在
  alert / notifications / overview **三处同形**,`replace_all` 会同时命中 overview(不该改);
  已实读定位并**单独把 overview 那处回退为「天」**,复查确认 overview/fund_score 全部保留自然日字面。

### 10.2 评估后做 · monitor_72h.sh ad_line(同病根第三处) —— 结论:能改,已改

- **可行性判定**:`monitor_72h.sh` 虽名为 .sh,但校验主体是 **L81-920 的 python heredoc**
  (`"$REPO/.venv/bin/python" <<'PYEOF'`),且**已 `from app.calendar import is_trading_day`**。
  → 复用交易日口径**零新依赖、不造假日表**,风险低 → **改**。
- **改动**:ad_line 块新增纯函数 `_ad_line_trading_age(ymd)`(单一事实源=app.calendar),
  判据由 `(NOW.date()-date).days > 3` 改 `_ad_line_trading_age(date) > 3`(**阈值 3 不变**);
  文案 `滞后{N}天(>3天)` → `滞后{N}交易日(>3交易日)`;解析失败 → 打印格式异常(不告警);
  app.calendar 不可用 → **回退自然日**(旧口径 fail-safe,不静默跳过检查)。
- **未动**:`check_and_alert` / `check_recovery` / dedup key / tier / escalation 链
  —— 只换「滞后天数怎么算」,告警链零改动(§23.11:无静默吞掉)。
- ~~**同文件它的时效点**:overview(L742)/alert(L753)本就走 `TODAY/LAST_TRADING_DAY` 白名单
  (交易日感知)→ 非同类病灶,未动(§23.3)。~~
  **【更正 2026-10-09 复审:此结论错,见 §11】** 该白名单非交易日感知(见上 §6-B 更正),
  且 alert 的 else 分支是纯自然日 `>3` —— **同类病灶**。复审共确诊 **4 处漏改**
  (stale_alert_date / S5 / S8 / S2),已在本轮补齐(§11)。

### 10.3 口径「单一事实源」上移(防两份实现漂移,§22)

- 新增 `app/calendar.lag_trading_days(date_str, today=None)` = 口径**权威实现**(含两道护栏)。
  `check_data_integrity._lag_trading_days` 改为**委托**(只注入本进程「今日」+ app.calendar
  不可用时 fail-safe 回退);monitor_72h 亦调用同款 → 全仓**唯一实现**,消除漂移面。
- 既有近似实现 `signal_kelly_snapshot.trading_days_lag`(= `len(between)-1`)**语义不同**
  (假定两端皆交易日;假期端点会差 1),**未复用、未改**。

### 10.4 续跑测试结果

`scripts/tests/test_235_f1_monitor72h_appcal_20261009.py`(该文件 **43 条**,含复审新增;详见 §11.4):
- A) `app.calendar.lag_trading_days` 与设计表 §4.3 **逐位一致** + 解析失败 None + 两道护栏;
- B) 静态锁:heredoc 合法 python + 共用 `_trading_age` 用 `lag_trading_days` + 判据 `>3` 保留
  + 文案「交易日」+ **已无纯自然日判据**(`_ad_dt`/`_al_dt` 旧变量均清除);
- B3b/c) **行为实测**:从 heredoc `ast` 提取「最近交易日/预期上一交易日」纯计算片断 exec
  —— 长假工作日 LAST_TRADING_DAY=最近交易日 09-30(非误判今日) + 复现生产假 SEVERE 白名单放行;
- C) **行为实测**:提取纯函数 `_trading_age` 受控命名空间执行(ZeroOutboundTrap 兜底,§18 L50)——
  **长假后首日(today=20261008,date=20260930)→ lag=1 ≤3 不误报**;
  **真过期(today=20261019)→ lag=8 >3 仍报**;含当日/周末/边界/解析失败/app.calendar 不可用回退;
- D) 降级不静默:`_last_trading_day_safe` 在 app.calendar 不可用时回退周几算术(工作日→今日,保守更严)。

**逐项过验收**:两文件 `98 passed`;全量 `pytest -q scripts/tests/` → **571 passed / 2 skipped / 0 failed (92.94s)**。
**数量对账**:基线 517 + origin/main(#241 测试文件 11 用例,rebase 带入)= 528;+ 本文件 43 = **571**(0 fail,无回归)。

### 10.5 复现段(续跑)

```bash
cd <worktree>
/Users/linhuichen/code/trade/.venv/bin/python -m pytest -q scripts/tests/test_235_f1_monitor72h_appcal_20261009.py  # 43 passed
/Users/linhuichen/code/trade/.venv/bin/python -m pytest -q scripts/tests/                                          # 571 passed / 2 skipped
```
- 判别力(red-before-green):`test_B2` 在旧 .sh 上必 FAIL(`(NOW.date() - _ad_dt.date()).days` 仍在);
  `test_C1` 的长假后首日用例在旧自然日口径下 lag=8>3(会误报)→ 新口径 lag=1 不报。

## 11. 复审返工:monitor_72h.sh 同类病灶 4 处补齐(2026-10-09,同分支)

**复审判定**:首版 §23.3 穷举不成立 —— `monitor_72h.sh` 内还有 **4 处**同类(自然日/周几算术)时效点
未改,且 `data/alert_state.json` 有**生产实证**(长假工作日误报)。

**生产实证(2026-10-06,国庆长假,市场休市)**:
`data/alert_state.json` 10-06 17:40 活跃 key:`72h_stale_alert_date`(date=20260930 age=6d)、
`72h_p0_smoke_s5_alert`(date=20260930)、`72h_p0_smoke_s8_notifications`、`72h_p0_smoke_s2_intraday`
—— **4 个假 SEVERE**,根因=长假工作日 `LAST_TRADING_DAY` 被周几算术算成「今日 10-06」,
数据日期 09-30 ≠ 10-06 → 白名单失配。

**改动(§6.5 根因修复:单点根治,非逐文件打补丁)**:

| # | 站点 | 行号(改后) | 旧形态 | 新形态 |
|---|---|---|---|---|
| ① | `stale_alert_date` else 分支 | `L795-806` | 纯自然日 `(NOW.date()-_al_dt.date()).days > 3` | 共用 `_trading_age(date) > 3`(交易日) |
| ② | S5 alert 白名单 | `L661`(依赖 L152) | `ALERT_EXPECTED_DATE`=周几算术 | `ALERT_EXPECTED_DATE`←`app.calendar.last_trading_day` |
| ③ | S8 notifications 白名单 | `L717`(依赖 L136/138/140) | `LAST_TRADING_DAY`=周几算术 | `LAST_TRADING_DAY`←`app.calendar.last_trading_day` |
| ④ | S2 intraday 白名单 | `L605`(依赖 L136/138/140) | 同 ③ | 同 ③ |

- ②③④ **同病根**=共享变量 `LAST_TRADING_DAY`/`ALERT_EXPECTED_DATE` 的「周几算术」(L113-155);
  根治=改其计算(新增 `_last_trading_day_safe(d)` 走 `app.calendar.last_trading_day`),
  **单点收口**,不逐处打补丁。该变量另有 S1(L579)/S6(L683)/overview(L758)消费者 → **一并受益**。
- ① 与 ad_line 合并为**同一个** `_trading_age(ymd)`(共用,消除两份实现)。
- **阈值语义保持**:3 处判据仍 `> 3`(交易日),阈值常量/FAIL-WARN 分档/dedup key/tier/escalation 链**零改动**。
- **降级不静默**(与 ad_line 同款):`app.calendar` 不可用 → `_last_trading_day_safe` 回退周几算术、
  `_trading_age` 回退自然日,均 `print` 到 stderr,不静默跳过检查(`test_C3`/`test_D1` 行为实证)。
- **局部化**:改动落在 L113-155(共享根)与 L764-816(时效块),未碰 L178-206 / L867-890(避开并行支)。

**§11.4 测试(本文件 43 条)**:
- `test_B3a` 静态锁:`LAST_TRADING_DAY`/`ALERT_EXPECTED_DATE` 确由 `_last_trading_day_safe` 计算;
- `test_B3b` **行为**(替换旧字面量假绿):exec 「最近交易日」计算片断,逐案核对 6 组
  —— 长假工作日/周六/交易日盘后/交易日盘前/长假后首日盘前/周一盘前;
- `test_B3c` **行为**:复现生产假 SEVERE 场景(10-06,数据 09-30)→ S2/S5/S8 白名单放行;
- `test_B2`/`test_C1`/`test_D1`:共用 helper + `_trading_age` 行为 + 降级回退。

**判别力(red-before-green)**:`test_B3b` 的长假工作日用例在旧周几算术下 `LAST_TRADING_DAY==TODAY`,
断言 `ltd != today_s` 必 FAIL;`test_B3a` 的 `_offset = 3 if _td.weekday() == 0 else 1` 静态锁在旧 .sh 上必 FAIL。