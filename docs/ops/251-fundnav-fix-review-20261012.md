# #251 公募日净值采集根治 — 独立审查报告

- 审查日期: 2026-10-12(晚间,审查者独立上下文 fresh reviewer)
- 审查对象: 分支 `feat/251-fundnav-col-bugfix`,commit `f224032e166337d89640c00b11c4824024fcdcab`(相对 `origin/main` 恰好 1 commit;3 文件 548+/22-)
  - `app/collector/public_fund.py`(fetch_daily_nav 重写:列名日期解析 + 未发布回退 + UPSERT/COALESCE)
  - `scripts/tests/test_251_fundnav_col_bugfix.py`(新增回归测试)
  - `scripts/backfill_fund_nav_null_days_251.py`(新增一次性回填工具)
- 工作目录: `/Users/linhuichen/code/trade/.claude/worktrees/agent-acd7c288a758f0223`
- 纪律: 全程只读;未执行任何生产脚本主体;云上全部 `file:...?mode=ro` 只读 SQL;未触发任何通知链路(L48)

## Verdict: PASS(核心修复无生产缺陷;附 2 条 must-fix 建议合前处置)

核心结论:
1. **无「1 天延迟」被引入**(死结论,见必查-2):任何 regime 下新代码新鲜度 ≥ 旧代码。
2. **回填可恢复性独立复核对账全过**(死结论,见必查-6):备份在、三天计数逐位一致、prev 链 0 mismatch、pct 复算 0/0/14(14 条已根因为「源分红调整口径」非缺陷)。
3. must-fix 2 条(测试在 CI 中零防护 / 监控判别力被消解),should-fix 2 条,nit 2 条。

## 必查-1 §15 回归面(引用方逐一结论)

调用方(写路径):
- `fetch_daily_nav` 生产调用方唯一链: `scripts/public_fund_daily.sh`(16:30 主 + 17:00 备, IS_TRADING gate)→`python -m app.collector.public_fund daily`。无其他 import 调用(全库 grep)。
- 表级写者(§23.11 写冲突): `public_fund.py:939`(本次改,COALESCE)、`public_fund.py:1171` fetch_nav_history(2026-10-02 起已 COALESCE)、`backfill_fund_nav_null_days_251.py`(COALESCE)、`check_data_gap_alerts.py:2199` / `test_240:592`(仅各自测试临时库)。**全部 fill-only,并发亦收敛,无静默覆盖风险**。

读者(读路径,逐项结论「语义是否变化」):
| 读者 | 位置 | 结论 |
|---|---|---|
| _compute_risk_from_nav / _compute_kelly_inputs / 修复时长 / 月频 | public_fund.py L2468/2487, L2771/2795, L3029/3033, L3082/3085 | unit/acc 语义不变,数据更完整(空变少)=改善 |
| _compute_position_estimate | public_fund.py L4378/4451(过滤 `pct IS NOT NULL AND pct != 0`) | 回退日 pct=None 与旧垃圾 0.0 均被同一过滤排除,无差 |
| export_fund_nav.py(nav_bucket 256 桶) | `WHERE unit_nav IS NOT NULL` | 语义不变;数据修复后更鲜 |
| check_data_integrity.check_fund_nav | DB↔产物抽样逐位 | 无新鲜度断言,不受影响 |
| check_data_gap_alerts 11/12 | L707-880 | 判别力问题见 must-fix-2 |
| 前端 app.js | L27802(unit 必数值/acc 允许 null) | 容忍 null,无破坏 |
| prev_unit_nav 读者 | app/ 内 write-only(8 处全为 schema/注释/写入,无 SELECT);scripts/ 仅 checker+工具+测试 | 无展示语义 |

**结论: 无回归面;唯一行为差异=「撞窗口时的错误形态」从『写全 NULL 行』变为『回退写前一日真值 / 全空时不写』(即修复目标本身)。**

## 必查-2 「1 天延迟」是否被引入 —— 死结论: 无(不引入)

逐 regime 论证(旧 vs 新):
- R1 正常日(跑批时当日列已发布): 新旧写同一行同值 → 完全无差。
- R2 撞窗口(当日列未发布、前一日列已发布): 旧=写「当日」全 NULL 行(unit/acc/pct 全空)+该日真值此后永不回到自己那天;新=回退写「前一日」真值行。**最新可展示日: 新(D-1) ≥ 旧(≤D-2)**(全 NULL 行被 export 跳过)。
- R3 全列未发布(极端): 新=不写(0 行);旧=写 24218 行全 NULL 垃圾(同样不可展示)→ 展示面相同,新少写垃圾。
- R4 当日发布晚于 17:00 运行(事故根因场景): 当晚新旧都拿不到当日真值(源未发布)。次日运行: 新在「次新已发布列= D」时把 D 真值补进 D 自己行;旧只把 D 真值塞进 D+1 行的 prev_unit_nav,D 行永远全 NULL → **新更鲜**。
- 极端不可能出现「旧能当日入库而新要等次日」: 新 target 取「最新整列已发布」,旧取「第一个日期列」;当日列一旦发布,两者 target 相同。

站点承诺新鲜度: nav_bucket 由 17:50 export 读 `max(unit NOT NULL)`;「通常 T-1」由数据源 16:00-17:00 发布节奏决定,早已在 README/产物 source 文案公示(「T+1 入图」),新旧一致。**§23.7 冻结契约不触发**(行为变化=严格改善 + 修 bug 本身;无回归可上报)。唯一用户可见变化: 窗口日会显示前一日真值(严格更鲜),非延迟。

## 必查-3 写路径冲突: 无(见必查-1 写者清单;全 COALESCE 收敛,`INSERT OR REPLACE` 已从生产路径清除,残留仅在测试自测临时库)

## 必查-4 测试质量(§18 L49)—— 断言输入真实,但**在 CI 中零防护(must-fix-1)**

- fixture 真实性 ✓: REAL_COLS/REAL_ROWS 与 10-12 真实响应同形(2 日期列 + 空串 `""` 未发布形态,`_safe_float("")→None` 正是旧代码 notna() 失守点)。
- fixture 有效性 ✓(我独立复现): 用 `git show origin/main:app/collector/public_fund.py` 逐字提取的旧 fetch_daily_nav 跑 race fixture → 写出 `@20261013` 3 行 unit/acc 全 NULL(test_01 断言同证,PASS;我另跑 /tmp 探针同结论)。
- 「24/24 通过」复现 ✓(`python3 scripts/tests/test_251_fundnav_col_bugfix.py` → 24/24 ALL PASS, exit 0)。
- **致命点**: `_check` 从不 assert,只在 `main()` 汇总;CI 对 scripts/tests/ 的唯一入口 = `.github/workflows/ci.yml:123` `python3 -m pytest -q scripts/tests/`(job ⑧ FAIL 阻断)。**pytest 收集 6 个 test_ 函数,零 assert → 任何失败都不报错**。复现: 将某断言期望改成错误值(0.8051→0.1111)的副本 → `python3 副本` 21/24 + 3 FAIL + exit 1(**断言存在**);同一副本 `/Users/linhuichen/code/trade/.venv/bin/pytest -q 副本` → **6 passed**(空转)。同目录已有 3 文件用 `scripts/tests/_wrap_util.py::run_script_main`(L200)桥接进程式测试的 house 机制,本文件未用。

## 必查-5 探针纪律(§18 L50): 我已遵守

只读文件 + 跑仓库自带测试(tmp DB;`pf.DB_PATH` 指 tmpdir、ak alias 打桩,无网络无生产写)+ /tmp 副本探针;云上纯 SELECT(`mode=ro`)。**未 source/exec 任何业务脚本主体**(未跑 collector/backfill/checker 的 main),未写生产目录,未触发通知。

## 必查-6 回填可恢复性独立复核 —— 死结论: 对账通过

- 备份: `/home/ubuntu/backups/public_fund.db.pre251-20261012` 存在,2,813,755,392 B,2026-10-12 22:31 ✓
- 修复前态(备份内): 10-08/09/12 的 unit_nav 全 NULL(0/24218, 0/24224, 0/24240)、pct 全 NULL → 与事故描述一致 ✓
- 现网复核(只读 SQL): unit 非空 **22085 / 23549 / 22092** 与实施者声称**逐位一致** ✓;acc 非空 0 / 23549 / 22092
- prev 链一致性: `prev@10-08 = unit@09-30`、`prev@10-09 = unit@10-08`、`prev@10-12 = unit@10-09` 逐位 join → **0 mismatch**(10-12↔10-09 全量 0)
- pct 全量复算 vs `ROUND((unit/prev-1)*100,2)`: 10-08 → 0/22085 不符;10-09 → 0/22084;10-12 → 22090 中 14 条不符(13 条 >0.05)
  - 14 条根因(已查实,非缺陷): 源「日增长率」为**分红调整口径**。实例如 023751: `(1.6215+0.086)/1.7446-1 = -2.13%` 与 pct 逐位吻合,acc−unit 差扩大 0.086 → 10-12 分红;旧采集器同样逐字存源值 → 非本次引入、非造数。
  - 注: 回填工具 B 路派生 pct 用 raw 比值,分红日与源口径有微差(见 nit-2)。
- **10-08 的 acc_nav 仍全空(0/24218)**(unit 已填 22085)→ should-fix-1。

## 必查-7 #252 侧 kelly_coverage: ✓ 现级别 = warn 非 severe(现网 alert_state 只读复核)

## 必查-8 §21/§22 与派生产物自愈

- §21: 纯后端改动,无算法公示/前端文案需同步(与站点/README 既有「T+1 入图」描述一致)。
- §22: 派生产物当前 stale 但一致 —— R2 `https://ssd.fx8.store/nav_bucket/ca.json` HTTP 200,000001 最新 = 20260930/1276,与 static-site 同值(R2=CF=本地 同源);DB 已有 10-08/09/12 → 明日自动重生。
- 自动重生证据: `trade-public-fund-daily.timer` 下一触发 10-13 16:30(public_fund_daily.sh: daily→export L77→deploy.sh public-fund;**public_fund_position_estimate.json 由 public_fund.py:5312 export_json_files 写**) + `trade-update-all.timer` 10-13 17:50(update_all.sh L107 `export_fund_nav.py` → rsync + R2)→ nav_bucket 与 position_estimate 均会在 10-13 当天刷新为含 10-12 的版本。

## 发现分级

### must-fix
1. **测试在 CI 零防护**(test_251 从不 assert;CI=pytest ⇒ 本次修复无回归保护)。修法(二选一,建议 a): a) 用 `scripts/tests/_wrap_util.py::run_script_main` 桥接; b) `_check` 改 assert 或 main() 后 `assert not bad` + `assert len(_RESULTS)>=24` 下限。复现命令见必查-4。
2. **监控判别力被消解**: checker 12(`FUND_NAV_ALLNULL_KEY` L712/check L807)的输入 = 「全 NULL 天」行,修复后此形态不再产生(全空→不写/R2 回退写前一日真值)→ 未来「数据源连续不发布」不再有 timely severe(残余仅 checker 11 的 30 天 acc 计数 warn,滞后数周)。现网 state 可见该键 10-09 曾 severe(正是事故发现通道)。建议补「最大已发布日落后交易日历 ≥2 天 → severe」检查,或主控拍板挂 Follow-up 追踪(不许静默丢判别维度)。

### should-fix
1. 10-08 `acc_nav` 全空(0/24218): 修复工具链式路不造 acc(设计正确),但该日 acc 真实值可由「每只基金历史净值接口」取回 → 建议补一次 acc 专项回填(日常采集不会自愈: 只写最新 1-2 日 + COALESCE)。影响: nav_bucket 该日点 acc=None(前端容忍,展示降级)。
2. (与 must-fix-2 同源,若选择「挂追踪」则本条并入)监控补位落地时同步更新 `check_data_gap_alerts` 自测样本。

### nit
1. test fixture 注释「未发布日的实际返回: 日增长率给 0.00(事故当天 DB nav_change_pct=0 的由来)」与事故备份矛盾 —— 备份显示 10-08/09/12 pct **全 NULL**(非 0.0);该构造比真实更严格(仍有效),注释应订正。
2. backfill 工具 docstring「口径与采集器一致: 单位净值相对前一日 %」在**分红日**不成立(采集器存源调整口径,工具派生 raw 比值);建议注明差异。

## 复现命令集(供抽查)
- 空转: `printf 's/\"unit_nav\"] == 0.8051/\"unit_nav\"] == 0.1111/'` 副本 → `/Users/linhuichen/code/trade/.venv/bin/pytest -q 副本` = 6 passed;`python3 副本` = exit 1。
- 云上对账(只读): `ssh -i /Users/linhuichen/tdsignal.pem -4 ubuntu@122.51.111.173` + `sqlite3.connect('file:/home/ubuntu/code/trade-data/data/public_fund.db?mode=ro',uri=True)`。
- CI 锚点: `.github/workflows/ci.yml:111-123`(job ⑧)。
