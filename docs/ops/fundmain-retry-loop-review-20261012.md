# a_fund_main 45min 误报环修复 —— 独立审报告（2026-10-12）

> 审查对象：分支 `worktree-agent-a3e38ce1838393e7e` @ `9f106cc5a`（远端别名 `feat/afund-retry-loop-fix`）
> 改动 3 文件：`docs/ops/fundmain-retry-loop-fix-20261012.md`（+212）、`scripts/backfill_direct_metrics.py`（+20/-）、`scripts/tests/test_fundmain_morning_gap_no_retry_loop_20261012.py`（+224）
> 背景：对应今日告警最大单一噪声源 **G3 = `[重采失败] a_fund_main 连续 3 轮重采失败` 8 条/日**（02:52→08:07，严格 45min 间隔）
> **落档方式**：researcher/reviewer 只读、无写权限，本文件由**主控落档**（先例：`docs/ops/kelly-intraday-rerun-exit5-20261012.md`）。

## Verdict：**PASS**（无 must-fix；2 条 should-fix / 3 条 nit，均为文档与测试表述级，不阻断合并）

---

## 死结论 Q1：**不会误伤真故障 —— 判别维度完整保留**

1. **改动范围**：diff 只动 `scripts/backfill_direct_metrics.py` 里 `morning && GAP_MARKER` 这一个分支的 status 串（error→warn，L141-153）。`else`（非凌晨槽 6 源全败）与 `no config/异常` 两分支**仍写 error + `fail+=1` → exit 1**，一字未动。
2. **`collect_log` 消费点全枚举**（全仓 grep）仅三处：
   - `app/queries.py:1765` `collect_health`（`status != "ok"` 即计入 → warn **仍进 item**，只是红点降黄点）
   - `scripts/retry_failed_metrics.py:192`（只认 error，**正是要断的环**）
   - `app/collector/index_backfill.py:158/163/203/303`（写方，**早就在写 warn**，先例成立）
   ⇒ **没有任何告警规则/机检依赖 `collect_health.level=='error'` 或 collect_log 的 error 计数** ⇒ 无「隐性告警通道被一起降噪」。
3. **兜底网实测存在**：`scripts/check_data_gap_alerts.py:161-163` `FUND_IDS=["a_fund_main","a_fund_margin"]`，lag ≥2 交易日 WARN / ≥5 SEVERE（真断供照报）；非凌晨槽（16:35/21:00）同日真故障门未动。
4. **被删链本身不产「当日数据」**：云上 `daily_metric` 的 `20261009` 行 `updated_at=2026-10-12T08:52:15`（=被删的晨间 retry 成功那一刻写的），而 `20261012` 日值 `updated_at=2026-10-12T21:42:08`（21:00 槽写的）⇒ 晨间 retry 成功时源只返回**上一交易日**行，**当日值从来靠晚间槽**；断环不丢当日数据供给。
5. **§23.7 合规**：前端可见面变化实施已主动挂待拍板（doc §4.1 注 + §8），**不算 finding**。

## 死结论 Q2：**8 条/日 → 0，环被真切断**

1. **唯一喂给源**：云上 audit log 每个交易日都是 `[retry] YYYYMMDD 发现 1 个 error 指标: ['a_fund_main']`（10-08=27 轮 / 10-09=36 轮 / 10-12=27 轮），环日名单**只有 a_fund_main 一个**。
2. **环数学复现**：`data/alerts/alert_ledger.jsonl` 10-12 恰 8 条重采失败告警，时间 02:52:17→08:07:18 **严格 45min 间隔**；`retry_failed_metrics_count.json` mtime 08:52 = `{}`，与 08:52:15 那次 `ok 1 rows (retry)`（环终止）自洽。
3. **修后断链**：warn 行 `get_failed_metrics` 永不拾取（测试用 bdm **真实产出行**喂 retry → `[]`）；同时**不压真故障**：同 run_date 的晚间 error 行比 02:00 warn 行更新 → 仍被拾取。
4. 残留（设计内、非缺陷）：02:00 timer 若延迟过 05:00 判非凌晨 → 仍走 error；云上 02:00 timer 准点（实证 error 行 02:17:42），风险不成立。

## Q3：「10-12 首爆非新故障」**成立，证据强于实施自述**

- git：NameError 随通知功能引入（`0a42e6bac`，09-30），`192800415` 修复（author date 10-09 17:57:27）。
- 云上 audit log：NameError **57 次 = 10-08 24 次 + 10-09 33 次**，每次紧跟 `[retry] ... [a_fund_main]` + `[fail]` ⇒ 环确在 notify 处被 NameError 吞掉。
- ledger（起自 10-10）：10-12 之前 **0 条**重采失败，10-12 **8 条**；10-10/10-11 周末（retry 非交易日跳过）⇒ 10-12 = 修好 notify 后**首个交易日**，首爆自洽。
- **加强证据**：环的底层「每日晨间 error 行 + 全天 retry 轮」自 **09-16 起每个交易日都有**（09-15..09-30 = 21~68 轮/日）⇒ 「非新故障」比 doc 所说更硬。

## Q4：测试质量 **PASS**

- **夹具 = 生产原样**：云上日志 `[gap] a_fund_main direct:market_fund_flow 多源皆败无数据 (02:00 槽预期缺口, 静默)` 的 `msg` 与测试 `GAP_MSG` **逐字一致**（§18 L49 ✅）。
- **真代码路径**：`bdm.main()` 真跑，只打桩两个 I/O 边界（`collect_direct` 网络 / `log_collect` DB）+ `_is_morning_slot`；retry 侧用真 `get_failed_metrics` 打真 sqlite 临时库。
- **红前绿（独立实跑复现）**：main 版 bdm + 新测试 → **2 failed / 8 passed**，失败正是两条 warn 断言用例。
- **变异验证**：把非凌晨槽分支 error→warn → `test_non_morning_gap_still_error_and_fail` **FAIL** ⇒ 判别维度被用例锁住。
- **CI 入口**：`--collect-only` 确认 `python3 -m pytest -q scripts/tests/`（ci.yml:123）收集 **767 项含新文件 10 项**；断言下限 `_MIN_ASSERTIONS=12` 防空转；`ZeroOutboundTrap` 断言零外发（§18 L48 ✅）。
- 兼容性：`collect_log` 表**无 CHECK 约束**，且云上已有 index_backfill 的 warn 行 ⇒ warn 落库不抛异常。

## should-fix / nit

| 级别 | 内容 | 证据 |
|---|---|---|
| should-fix S1 | doc §4.1 影响面表补一行「**前日行缺失时的隐式补采随环一并消失**」+ 残差说明（被删链兼作「上一交易日行缺失时的隐式补采」；修后没了，但晚间槽 + freshness 检查器 + schedule_monitor 三层仍在） | `daily_metric` 20261009 行 `updated_at=2026-10-12T08:52:15` |
| nit N1 | doc §6「红前绿 1 failed/9 passed」与独立复现 **2 failed/8 passed** 不符，应按 §5.4⑦ 对账纪律订正 | `/tmp/oldcode` 实跑 |
| nit N2 | doc §2「环自 10-08 起」低估（底层环 09-16 起每日都在），应补进 doc 以增强「非新故障」论证 | audit log 按日 retry 轮数 |
| nit N3 | `test_full_trading_day_morning_gaps_never_notify` 是自种 warn 行、旧代码上也 PASS（判别力弱，靠另两条用例撑）；保留可，建议 doc 标注口径 | 旧代码实跑 |

## §10.6 over-engineering：**无**（本改动就是「最少改动」本身：1 行行为 + 注释，零新增抽象）

## §25 / §18 L50 自查
- §25：本次改动不涉任何删除（仅 status 串变化，历史 error 行仍在，由下次成功采集按原逻辑清非 ok 行）。
- §18 L50：全程 static-only —— 未 exec 任何业务脚本主体（只跑仓内既有 pytest 用例，两 I/O 边界均打桩；旧版/变异跑在 `/tmp` 副本树，零写 worktree）；云上全程只读（DB 一律 `mode=ro`，仅 SELECT；日志只 grep/awk；未杀进程、未写文件）。

---

## 给主控的决策输入

1. **合并后效应点 = 10-13（周二）02:00 凌晨槽**：`main-merge.sh` 第 10 步「merge 即同步：ssh 云上 git pull」会把新脚本立刻拉到云上 ⇒ **次日晨 0 条重采失败**即可判 PASS；若该步失败（§23.11 会醒目标警），云上仍是旧脚本 → 10-13 还会响一次 8 条，效应点顺延 10-14。
   - 验收锚点：`data/alerts/alert_ledger.jsonl` 当日「重采失败」计数 + `collect_log` 该日为 warn 行。
2. **⚠️ 真故障观测面变化（合并前需用户点头，§23.7）**：02:00-16:52 之间 `collect_health` 由**红点降为黄点**、a_fund_main 卡的「⚠ 采集异常」badge（`app.js:16639`）不再出现；真故障面（非凌晨槽 6 源全败 / 数据断供 WARN@2·SEVERE@5 交易日）**不变**。实施已按 §23.7 在 doc §8 挂待拍板。

---

*生成：2026-10-12 深夜，源 = reviewer 独立审报告正文，由主控落档。*