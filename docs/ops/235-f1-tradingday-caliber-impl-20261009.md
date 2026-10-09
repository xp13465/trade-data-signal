# #235 F1 实施报告:数据新鲜度校验「自然日 → 交易日」口径(2026-10-09)

- 角色: 实施 agent | 分支: `worktree-agent-a075c2034c69c77f0`(worktree 隔离)
- 设计稿(已定稿): `docs/ops/235-f1-tradingday-caliber-design-20261009.md`
- 改动文件: `scripts/check_data_integrity.py`(helper + 8 处替换 + 1 处 docstring)
  + 新增 `scripts/tests/test_235_f1_tradingday_caliber_20261009.py`
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
- **未改**:阈值常量(`STALE_DAYS_WARN=3`/`STALE_DAYS_FAIL=7`)、所有 FAIL/WARN 判据、所有
  用户/运维可见消息文本(见 §7 诚实标注)。

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

**全量回归**:`pytest -q scripts/tests/` → **517 passed / 2 skipped / 0 failed (93.00s)**(改动前基线
517-55=462 量级,新增 55 条全绿,无回归)。

## 6. §23.3 举一反三:其它「日期维度判据」清单(任务项 7)

同模式搜索面(全仓 `.days` / 「滞后」全量):

**A. 同病候选(自然日新鲜度判据,长假后可能误报)—— 本任务**不动**,建议单开任务**
1. `scripts/monitor_72h.sh:772-794` `ad_line.json` 检查:**纯自然日** `(NOW.date()-date).days > 3 → SEVERE,
   无交易日豁免。长假后首日(date=09-30,today=10-08,age=8>3)会误报 SEVERE。**机制不同**(SEVERE 监控
   告警,非 deploy 闸门)+ 不在 #235 F1 scope(本任务只动 check_data_integrity)→ 未动,列此备查。
2. `scripts/check_nt_signals.py:185-192` 邮件标签 `T-{gap}数据`:natural gap,长假后标签偏大(如 T-8)。
   属**展示标签非闸门**,且改动会动邮件文案 → 未动,列此备查。

**B. 已交易日口径(无需改,同类已对齐)**
- `scripts/monitor_72h.sh:741-770` overview / alert:已用 `TODAY/LAST_TRADING_DAY` 集合豁免(交易日感知)✓
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

- **消息文案未改**:稿 §7.3 第一 bullet(FAIL/WARN 消息「X 天」→「X 交易日」)标「**可选但建议**」,
  而派单硬约束为「**消息结构一律不动 / 别顺手改文案**」→ **按派单未改**。代价:改口径后消息里的
  「天」字面=交易日数,存在轻微误导。**若需对齐,建议主控另派一次纯文案改动**(零逻辑风险)。
- **docstring 已改**:稿 §7.3 第二 bullet 标「**必须修正**」(原句与实现矛盾,不改即为错误描述),
  且非用户可见文案 → 已改。若主控认为该并入上条一并暂缓,撤这一处即可(仅 3 行)。
- 稿 §1.7 / §9.3 的「给 alert 增补本地 vs R2 差异只 WARN」是**可选增强、非本规格** → **未做**(按任务项 6)。
- 稿 §9.4 mtime 时区依赖未改变(非新增风险)。

## 9. 复现段(可独立复跑)

```bash
cd <worktree>
/Users/linhuichen/code/trade/.venv/bin/python -m pytest -q scripts/tests/test_235_f1_tradingday_caliber_20261009.py   # 55 passed
/Users/linhuichen/code/trade/.venv/bin/python -m pytest -q scripts/tests/                                           # 517 passed / 2 skipped
/Users/linhuichen/code/trade/.venv/bin/python scripts/test_188_s06_sync_blindspot.py                                # ALL_PASS
```
判别力(red-before-green):`test_08a/08b` 静态锁在旧代码上必 FAIL(旧=9 处 `_days_ago`/0 处新 helper);
`test_01` 数值表同时断言新旧两口径值,若 helper 未换口径即 FAIL。