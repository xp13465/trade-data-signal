# #223② 独立审报告:nextday_plan 内层 R2 上传超时 300→480

- 待审分支:`feat/223-2-nextday-plan-timeout-20261007`,tip `f0d4cb1fe`(单 commit;parent `38c172461` = 实施时 origin/main)
- 审阅:reviewer(独立上下文,只读;未改任何代码/未跑任何业务脚本;云上仅只读读命令,§18 L50)
- 依据:CLAUDE.md §15/§22/§23.2/§23.7/§24(N/A)/§18 L48/L49/L50;role-reviewer skill §2/§10

## 0. 结论速览

| 项 | 结论 |
|---|---|
| 改动分级 | **B 级②**(有隐藏影响面:定时链 + CI 契约测试) |
| **merge 资格** | **阻断 1 项(F1)——当前 tip 不宜直接 merge**;F1 修复后(同分支 1 行改动)即可放行 |
| 值正确性(480 算式 + 云上外墙 600) | PASS(独立复算 + 云上只读实测) |
| 「不加运行时守卫」判定 | 判定成立,但**理由表述不精确(F2,非阻断)** |
| 文案三处口径(§22) | PASS |
| 测试质量(§18 L49/L50) | PASS(6 变异 6 CAUGHT;static-only 结构确证;零外发实证) |
| 同类错误面完整性(§23.2) | PASS(6 个 py→upload_r2 调用点全表核过,无漏) |
| 零夹带 / git 纪律 | PASS |
| §23.7 留痕 | PASS(拍板日期+依据三处可反查) |

## 1. 值正确性(必答 1)

**算式独立复算**:480 + 28 = 508 < 600,余 92s(15.3%)✓;480 > 观测触发下界 300s ✓。
- 28 = 上传前 ≤10s + 超时后处理实测 18s。18s 独立核:云上 log 2026-09-30 22:35:01(300s 超时点)→ 22:35:19(`=== nextday_plan.sh 结束 … 退出码=1 ===`)= 18s ✓;整链 318s = 300+18 自洽(22:30:01 起)。

**云上真值独立核(只读,ssh `-i ~/tdsignal.pem ubuntu@122.51.111.173`)**:
- `systemctl show -p TimeoutStartUSec --value trade-nextday-plan.service` → `10min`(= 600s)✓
- `systemctl cat trade-nextday-plan.service` → `TimeoutStartSec=600`✓(无 drop-in 覆盖)
- 云上 `.env:33` `R2_UPLOAD_HTTP_TIMEOUT=600`✓(即「内层 HTTP 600」前提也真)
- 09-30 事件原文核:`data/logs/nextday_plan_launchd.log:1642` = `⚠ R2 上传超时(300s, 将告警)`✓
- timer:`trade-nextday-plan.timer` 下次 2026-10-07 22:30:00 CST ✓

## 2. 「不加运行时守卫」判定(必答 2)

判定**成立**(不造守卫的结论正确),但注释/测试 docstring 的**理由表述不精确** → F2。独立核对照两先例源码:
- `scripts/fapi_bj_width_export.py:75-93`(#217② 版,外层 = trade-fapi-daily.service = 0/∞):**无外层感知**,`本层 <= 内层 HTTP ⇒ 抬到 内层+300`;照抄本处会 480→900 **越 600 墙** ⇒ 「#217② 版照抄会越墙」这句是对的。
- `scripts/overfit_monitor.py:1706-1736`(#223④ 版,最新):有外层感知——`base>=outer ⇒ 收到 outer-300`;`base<=http_to` 时**若 `http_to+MARGIN >= outer` 则走「外层优先不越墙」分支、保持 base 只打 warn**。代入本链(outer=600,http_to=600):480 保持不动 = 与静态值**行为等价**(副作用:该倒置条件恒真 ⇒ 每次运行打一行永久 warn)。⇒ 「overfit 守卫会把 480 抬过 600」**不成立**。
- 正确表述:「#217②(无外层版)照抄会越墙,不可用;overfit 版(有外层版)在本处行为中性但产生永久告警噪音、且无第二真实使用者 ⇒ 不造守卫(#6.5 少写抽象),不变量由注释+测试固化」——结论同,理由应订正(F2)。

**隐藏风险评估**(任务点名两类):
- ① 外层 unit 未来被改小:无运行时保护(**设计接受**)。静态测试里的 600 是**冻结样本常量**,不连云;云上 unit 手动管理(`git pull` 不更新),该风险由流程兜(#223⑤ 的单元快照/文档 + §25 备份纪律),非本测试兜。属**低分滤除项**(当前 unit 稳定,改小需人工动作且走变更流程)。
- ② 480 vs 内层 HTTP 600:结构性不可同时满足(`L1>600` 与 `L1+28<600` 互斥),接受度对齐 #223④ 守卫「外层优先不越墙」哲学;后果 = 超时点早于 upload_r2 自身 600 窗口时,子进程诊断输出同 300 时代一样会被截断(失败语义同族,只是忍耐带 300-480 加大),且 severe 仍先于 systemd 落 = 可观测性保持。已有拍板诚实标注(取证报告 §3.3「不消灭真故障」)。

## 3. 文案三处口径同步(必答 3)

PASS。分支文件内:代码注释(480+算式)/ `⚠ R2 上传超时(480s, 将告警)` / severe 正文 `R2 upload-data-files 480s 超时` 三处全 480;旧 `timeout=300`、`300s` 文案零残留(仅 1177 行 changelog「300 → 480」与 1180 行下界事实 300 属有意保留)。告警标题无数字;dedup key `nextday_plan_gen_fail` 未动;denoise 规则 `alert_denoise_rules.py:461` 按子串「R2 上传」匹配,不受 300→480 影响 ✓。历史文档(all-alerts-sweep/cloud-healthcheck 等)中「300s」= 当时的日志引文档案,不需改。

## 4. 测试质量(必答 4)

- **断言数澄清**:「24 断言」= 无 `data/alerts/latest.md` 的环境(实施者 worktree / CI);本机主仓有该文件时实跑 **26 断言全 PASS**(差 2 = md5 分支的两条断言)。两环境均 ≥ `_N>=20` 护栏。
- **独立复跑变异负控(自设 6 个,6/6 CAUGHT)**:
  | 变异 | 结果 |
  |---|---|
  | M1 timeout 480→300 回退 | CAUGHT `[#1] 应有恰 1 处 subprocess.run(timeout=480), 实得 []` |
  | M2 severe 文案 480s→300s | CAUGHT `[#15]` |
  | M3 注释短语「不加运行时梯度守卫」移除 | CAUGHT `[#12]` |
  | M4 字面量→运行时表达式 `timeout=int(...)` | CAUGHT `[#1]` |
  | M5 超时日志行 480s→300s | CAUGHT `[#13]` |
  | M6 480→620 越外墙 | CAUGHT `[#1]` |
  (实施者自称「3 变异 CAUGHT」的原文未在仓内/分支落档,本轮以自设 6 变异独立重跑替代,覆盖 ≥3。)
- **AST static-only 确证**:测试仅 import `ast/hashlib/re/pathlib`;对业务文件只 `read_text + ast.parse`,无 import 业务模块、无 exec、无 subprocess;自证断言(不得 import nextday_plan_generator/subprocess/notify)在内 ✓。
- **零真实外发实证**:装置运行前后 + 主仓 `data/alerts/latest.md` md5 `e8e4db889167bdd04aad8aaaa61cf9c8`、mtime `1791279611 (Oct 6 17:40:11)` 前后逐位一致 ✓;装置内 md5 分支(有 dummy latest.md)亦实跑过。
- 限制(如实,同 #223④ N1 型):md5 分支在无 alerts 环境(CI)被 skip 而非 fail;`_N>=20` 是粗下限无自保——真保障 = static-only 结构。

## 5. 同类错误面完整性(必答 5)

独立全仓扫描(py subprocess→upload_r2.py)全表,**无第 7 个漏网点**:

| 调用点 | 现值 | 处置/登记 |
|---|---|---|
| `scripts/nextday_plan_generator.py:1186` | 300→**480** | 本分支(已拍板) |
| `scripts/nextday_gap_check.py:358` | 300 | 取证 §4:触发 0 次,**不动**(登记在案) |
| `scripts/gen_daily_brief.py:3119` | 120 | 取证 §2:不动,归 **#227** |
| `scripts/fetch_news.py:732` | 120+skip_retry(默认 60)=180 | **已在 #223 登记**(待拍板④列出);外层经 **#223⑤** 已抬 1080(=180+600+300)覆盖串行 |
| `scripts/fapi_bj_width_export.py` | 900 + 守卫 | #217②/#223③ 已修(CI 有测试) |
| `scripts/overfit_monitor.py:1959` | 900+skip_retry + 守卫 | #223④ 已修(CI 有测试) |

- `fetch_news.py:732` 判定:其值 **已登记且外层侧已闭环**(#223⑤),**不需新开上报**;「未带 #223 交叉引用注释」属可选(其自身有 #217① 注释说明 120+60 来源)——低分项。
- `#227 乙表未列 fetch_news` 正确:乙表范围 =「外层无界+内层偏紧」候选,fetch_news 外层有界(1080)且有显式设计(等锁窗口),不入乙表不属漏。

## 6. 零夹带 / git 纪律(必答 6)

PASS。`git diff 38c172461..f0d4cb1fe --stat` = **恰 2 文件**(`scripts/nextday_plan_generator.py` 19±、`scripts/tests/test_223_nextday_plan_timeout.py` +130);单 commit;parent = 实施时 origin/main `38c172461`(base 新鲜);trailer `Co-Authored-By: Claude Code <noreply@anthropic.com>` 在位(与近 30 条 commit 94% 一致的项目现行式样);`f0d4cb1fe` **不在 main**;`origin/feat/…` tip == f0d4cb1fe;未 add 根 data/。main 现 `5f78f586d`(主控 docs-only:TASKS/pending-index)与本分支改动零重叠,merge 无冲突面。

## 7. §23.7 留痕(必答 7)

PASS。三处可反查:①代码注释「#223②(2026-10-07 用户拍板)」+ 算式逐字引 `docs/ops/223-123-inner-timeout-evidence-20261006.md §3.3`;②commit message 同口径;③`docs/pending-features-index.md` #223 行:「已拍板 2026-10-07 并实施(分支 … tip f0d4cb1fe:480 + 三处同步 + 测试 24 断言;待独立审)」。

## 8. Findings

### F1(阻断,置信 100)—— merge 后 CI Job1 ⑧ 必红:旧契约测试未随值同步

- trace:diff_range = `f0d4cb1fe`(改动侧)+ `scripts/tests/test_223_timeout_gradient_copy.py:161`(未改动侧契约);linkage = **不满足**;user_request = 用户 2026-10-07 拍板 300→480。
- 事实:`scripts/tests/test_223_timeout_gradient_copy.py` §[C] 断言「`nextday_plan_generator.py` **保留** `timeout=300`(未改值)」;CI 触发面 = `.github/workflows/ci.yml:49-51`(push main / PR)+ `:109-112` Job1 ⑧ `python3 -m pytest -q scripts/tests/`(FAIL 阻断)⇒ push main 后该断言必 FAIL。
- verifier(机检 A/B,均在本机装置 `/tmp/223-2-ci-check` 复跑):
  - command = 以 `38c172461` 全量文件跑该测试 → `1 passed`;仅换入 `f0d4cb1fe:scripts/nextday_plan_generator.py` 再跑
  - expected(合规)= 仍 PASS;**observed = `PASS=32 FAIL=1`,唯一 FAIL 行:`FAIL  nextday_plan_generator.py: timeout=300 保留(未改值)`**
- 修法(给实施指令,同分支续跑 1 个 commit):将 `:161` 元组 `"timeout=300"` 改为 `"timeout=480"`(附 `#223②(2026-10-07 拍板)` 短注);`:162` gap_check 行不动;`MIN_ASSERTIONS=33` 与「已加 #223 注释」断言不动。修后复跑本文件应 PASS,且反向变异(480 改回 300)应 FAIL(守卫有效性保持)。
- over_engineering:无(修 1 行,不增抽象;不建议删该断言——它是该链值的唯一 CI 契约点)。
- 附注:该文件 ⑧ 的 FAIL 也会连带影响 #201/#211 以「CI ⑧ 为强制点」的既有约定(索引 #211 行),故不建议「先合再说」。

### F2(80,建议随分支订正,非阻断)—— 注释/测试 docstring 对 #223④ 守卫行为的表述不精确

- trace:diff_range = `f0d4cb1fe` 改动注释(1181-1184 行区)+ 新测试 docstring;linkage = 不满足(理由文本与先例实态不符);user_request = "origin: reviewer_own"(独立核源码发现)。
- verifier:`command` = 读 `scripts/overfit_monitor.py:1723-1736` 并代入 outer=600/http_to=600 复算;`expected` = 若真会「抬过 600」则该分支应抬;`observed` = 走「外层优先不越墙」分支,**保持 480**。
- 影响:行为零变更;风险 = 未来维护者据该表述误判「守卫族不适用于本链」(实为「适用但中性+噪音」)。修法 = 订正 2 处措辞(见 §2 正确表述)。

### 低分滤除项(<80,共 4 条,不进正式 finding)

1. 新测试文件末尾无换行符(风格)。
2. `fetch_news.py:732` 未加 #223 交叉引用注释(信息性,非错误)。
3. 「24 断言」随环境为 24/26——已澄清,无需动作。
4. 「外层 unit 未来被改小」无运行时守护——设计接受,依赖流程纪律(见 §2①)。

## 9. 诚实标注(本轮未做)

- CI 未真跑(`gh` 不在本机环境);F1 用「同装置 A/B 机检 + 触发面读码」等价取证。
- 云上未跑任何业务脚本/未 start/stop 任何 unit(§18 L50);只读命令清单:systemctl show/cat/list-timers、grep/sed、ls。
- 全量 `scripts/tests` 未整体复跑(仅:本分支新测试 26 断言 + `test_223_timeout_gradient_copy.py` A/B)。
- 实施者「3 变异」原文未落档(分支/仓内无该实施报告文件),以自设 6 变异替代。

