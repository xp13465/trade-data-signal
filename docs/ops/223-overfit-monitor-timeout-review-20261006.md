# #223④ overfit_monitor 超时 180→900 + 梯度守卫 —— 独立评审报告(reviewer)

- 评审对象:分支 `feat/223-overfit-monitor-timeout-20261006` tip `06c87d86f`(远端 tip 实测一致)
- 实施报告:`docs/ops/223-overfit-monitor-timeout-20261006.md`(worktree `agent-a63a3b6dd8236cf42`)
- 评审日期:2026-10-06;评审方式:全程只读 + /tmp 隔离副本;未改任何代码、未 push、未 force、未动 worktree
- 改动分级:B 级(改超时逻辑 + 新增守卫函数 + 新增测试),按 §15 完整审(影响面 + 变异测试 + 独立 probe)

## 零、结论:merge 资格 = **可 merge(内审 PASS)**

逐项 1-9 全部 PASS;3 条非阻断注记 + 4 条"没做到/做不到"诚实标注,见文末。
（本判定仅覆盖代码/逻辑/纪律面;按 §0 主控 merge 前仍需自行核对时点窗口。）

## 一、硬门前置复核:PASS(我独立上云实测,只读)

| 项 | 我的实测命令与结果 |
|---|---|
| 外层 systemd 墙 | `ssh ... systemctl show -p TimeoutStartUSec --value trade-overfit-monitor.service` → **`infinity`**;unit 文件 `/etc/systemd/system/trade-overfit-monitor.service:14` `TimeoutStartSec=0` ⇒ **0=无界,前提成立,不存在"内层>外层"有害倒置** |
| 链的触发节奏 | `trade-overfit-monitor.timer` 实测**每天 21:40 一次**(next=10-07 21:40;今日 21:40 已跑完,inactive/dead) |
| 附采样本 | `trade-intraday-snapshot`=infinity、`trade-s06-snapshot`=55min、`trade-kelly-intraday-rerun`=10min、`trade-update-all`=infinity、`trade-lab-auto`=infinity |

只做 `systemctl show/list-timers` 读操作;未启停任何 unit、未 daemon-reload。

## 二、守卫"真修而非注释":PASS(独立 probe,不复用其测试)

我自写 `/tmp/probe223_independent.py`(自行 AST 抽取守卫+常量 exec,§18 L50 static-only),**8×5=40 组合全矩阵 + 边界 599/1199** 独立复算,**0 失败**:

- 倒置输入实证:outer=600 ⇒ 900→**300** + warn;http=1200/outer=0 ⇒ 900→**1500** + warn;outer=300(margin 恰等)⇒ **1** + warn(退化边界,恰由 warn 兜住不静默);outer=599..900 段与 http=600+ 组合走"无法同时满足"冲突分支(保收到值 + warn,外层优先)。
- 全矩阵不变量:outer>0 时 **r<=outer 恒成立(永不越墙)**;凡 r<=http(未解倒置)的 12 个组合**全部有 warn**(无静默倒置)。
- 值依赖:同输入 outer=600,常量 120⇒120 / 900⇒300;outer=1200,常量 1500⇒900 ⇒ **判定确实随运行值变化**,非注释级、非写死。

## 三、L49 家族(假绿)变异测试:PASS(8 变异全部 CAUGHT)

在 `/tmp/mut223` 隔离副本变异源码/测试后重跑其测试(未碰 worktree):

| # | 变异 | 结果 |
|---|---|---|
| a | `base >= outer` → `base > outer` | CAUGHT(#21:outer=900 零梯度漏判)|
| b | 规则A margin 300→30 | CAUGHT(#9:570≠300)|
| c | 守卫提前 `return base`(整体失效) | CAUGHT(#9:900≠300)|
| d | warn 去掉 "⚠"(静默化) | CAUGHT(#11)|
| f | 删守卫函数名 | CAUGHT(KeyError,收集即炸非静默)|
| g | 调用点回退 `120 + _r2_skip_retry` | CAUGHT(#3)|
| e1 | 注释掉 20 个单行断言(48→7) | CAUGHT(护栏:"断言数仅 7(下限 30)")|
| e2 | e1 + 连护栏一起删 | **PASS(静默)** ⇒ 护栏是唯一防线、删了就假绿(共性边界,见注记 N2)|
| e3 | 删 8 个断言(48→40,仍≥30) | PASS(不响)⇒ 护栏是粗下限,非精确计数 |

> 三个行为类核心变异(a/b/c)均被**精确数值断言**抓住,不是靠泛泛断言;`MIN_ASSERTIONS` 护栏对"骤降"确有效(e1),但无自保(e2)、非精确(e3)——如实记录边界,不判缺陷。

## 四、行为变化面(头号必答):180→900 的正面回答

① **R2 真挂时判死推迟多久**:内层 subprocess 上限 120+60=**180s** → 900+60=**960s**,判死推迟 **780s(13min)**;失败后行为**不变**:打 `✗ R2_UPLOAD_TIMEOUT ... 请人工确认` 到 stderr(该分支**无邮件/飞书 notify,仅打印**)、`return out` 继续跑完。即"晚 13 分钟在日志里宣告失败",不是新增静默。
② **是否挡后续任务 / 被先收**:不会被 systemd 先收(外层 ∞,实测);云上实测 21:40 后下一个 timer = **23:56**(check-monitor-heartbeat),最坏 21:40+960s=**21:56 结束**,裕度 2h20m;timer 每天一次,不与自身下轮重叠。唯一新增存在感=21:43→21:56 的 13 分钟服务占用窗口,无下游依赖该窗口。
③ **下游消费方**:`static-site/common.js:1156`/`lab.js` fetch `overfit_monitor.json`(看板类,随时刷新,**无按时产出硬依赖**);`check_r2_consistency.py` 列为 R2/CF/MAIN 一致性审计项(非定时消费);R2 缺口由 deploy 日链 upload-data-large/upload-all-data 兜底(deploy.sh L20/L240/L299 注释互证)。⇒ 推迟 780s 无功能影响;R2 真挂时新旧口径都会失败,失败语义与兜底路径相同。
④ **原设计意图(180 覆盖 #217① 等锁重试 120+60)是否仍成立**:**成立且更宽松**。新基预算 900 >> 旧 120(主流程预算反而变宽);`+ _r2_skip_retry`(60)原样保留=等锁窗口不变(代码 L1945-1957 实读确认);900 > 云上 L0(HTTP 600)⇒ L1>L0 方向保持;外层 ∞ ⇒ L1<L2 自动成立。等锁重试窗口的语义没有被这 720s 抬升破坏。
   附:900 的实际收益场景=「R2 慢但能成功」的大上传不再被 120s 误杀;真挂场景只是晚 13 分钟宣告、由 deploy 兜底,不产生新缺口。

## 五、零真实外发:PASS(一处证据陈述弱化,见 N1)

- 主仓 `data/alerts/latest.md` md5=`e8e4db889167bdd04aad8aaaa61cf9c8`、mtime `10-06 17:40:11`,与报告数字一致;我跑其测试(基线 1 次 + 变异 ~15 次)**前后逐位不变、mtime 未变**。
- 独立代码审:测试不 import notify;唯一外呼路径=守卫内 `subprocess.run(["systemctl","show",...])`(本地只读 exec);stub 记录断言有效(我独立复跑 `calls` 恰为 1 条 systemctl show);`Stub 无 Popen` 断言有效(起其它子进程会 AttributeError)。
- **弱化点**:④ worktree 的 `data/` 下**没有** `alerts/latest.md`(仅 index_etf_map.json/stock_codes.json/.gitignore)⇒ 测试 `_latest_md5()` 返回 None 走 else 分支,**该断言在 worktree 自测时实际未执行**;报告 §5.3 的 md5 数字(主仓)属实但"测试内含该断言"的表述在该环境不精确。零外发结论本体由 (代码审 stub 断言 + 我实跑前后核对) 独立支撑 ⇒ 非阻断。

## 六、诚实标注复核:PASS(两处实核属实)

- "overfit_monitor.py 无 勿擅改 注释":`grep -c 勿擅改 scripts/overfit_monitor.py`=**0**;全仓恰 3 处=`gen_daily_brief.py:3111` / `nextday_plan_generator.py:1177` / `nextday_gap_check.py:355`(逐行原文核对)⇒ 属实。
- "全仓 Python 侧 subprocess→upload_r2.py 只有这一处":我独立 grep(排除 tests)⇒ 唯一 subprocess 调用点=`scripts/overfit_monitor.py:1959`;其余全为注释/docstring;test_193/test_204 仅 `import upload_r2`(静态分析,非同型)⇒ 属实;shell 层调用(deploy.sh/update_all.sh 等)与甲表口径一致。

## 七、乙表抽查:已抽查 2 条 + 样本(乙表是"判断"非"统计",如实标注核到程度)

- **#1 `check_signals.py:289`(30s→sync_subscriptions_from_cf)**:①外层 `trade-intraday-snapshot`=infinity —— 云上实测 ✓ 真;②超时仅 `log.warning(...用旧 config/subscriptions.json)` 不抛不中断 ✓ 真(读码 L292-296);③"30s 偏紧"= **部分为真**:内层自带 timeout=15(urlopen/requests 双路径),L0=15<L1=30 不倒置;但 requests 的 timeout=15 为连接+读**各自** 15s,极端合计 30s ⇒ 与外层 30s 零梯度。定性:该条目为合理候选,但非"倒置级"风险,证明强度中等。
- **#2 `overfit_monitor.py:1438`(60s→notify.py)**:timeout=60、`except → return False, str(e)`;外层 overfit-monitor=∞ 实测 ✓ ⇒ 判断合理。
- 其余 3 条未逐条实测(报告已自标"非实测超时统计"),我抽测的外层值样本(6 个服务)与乙/丙表声称一致。

## 八、git 纪律:PASS(一处如实注记)

- 远端 tip(ls-remote)= `06c87d86f...` == 本地 tip ✓;分支独有 commit 仅 06c87d86f(其余在 main 链上)✓
- 夹带:本 commit 恰 3 文件(报告/脚本/测试),**无 data/、无前端、无版本串** ✓;trailer `Co-Authored-By: Claude Code <noreply@anthropic.com>` ✓
- base 新鲜:origin/main tip=`6f499e775`;dc0f3a124 是其祖先;reflog 显示一次 **fetch+rebase**(30d230462 → onto b18b3b271 → 06c87d86f),即 §8 推荐的 non-ff 处理;`git diff 30d230462..06c87d86f` 仅 docs/ 差异,**scripts/ 逐位一致** ⇒ rebase 未改内容、无覆盖/丢失。
- merge 安全性:main 独有 `6f499e775` 只改 TASKS.md + pending-index,与本 commit 文件集**零重叠** ⇒ merge 无冲突。
- force 面:reflog 单调(创建→commit→rebase finish,无 amend);被替换的 30d230462 **不在远端任何 ref** ⇒ 无需 force 的最强可见证据;服务端不可查,无法 100% 排除(见诚实标注)。worktree `git status` 干净 ✓。

## 九、§15 隐藏影响面:PASS

- 全改动面= `import re` + 守卫块 + 调用点单行;新符号 grep 全仓=仅自身+本测试,无其他消费方(不涉及轮询/事件/跨模块)。
- overfit_monitor 其他行为:除超时值 180→960(含 skip_retry),新增每 R2 路径一次 `systemctl show` 探测(云上 ~10ms;mac 失败→0);**现网 outer=∞ 路径零 warn 输出** ⇒ 现网日志相较旧版无新增/删减;✗ 标记(2026-09-24 硬化)不动;其余生产逻辑未动(diff 全量核对)。
- 其他测试无冲突:`test_223_timeout_gradient_copy.py` 仅测 fapi 守卫(无 overfit 断言)、`test_196` 仅引用 unit/脚本名 ⇒ 无断言依赖旧值 180。
- 残余风险注记(低、非阻断):未来若有人把云上 unit 改成有界且 ≤300(margin),守卫会收到 1s 极端值(有 warn);若 systemctl 输出为未覆盖格式且外层实际有界,解析失败→0→放行(现网 infinity 已覆盖,该场景暂无)。

## 十、非阻断注记(3 条)

- **N1**:证据陈述精确化——worktree 无 data/alerts/latest.md,报告 §5.3"测试内含该断言"在该环境实际被 skip(零外发结论仍成立,由 stub+代码审+实跑前后核独立支撑)。
- **N2**:MIN_ASSERTIONS 护栏无自保、为粗下限(mut_e2/e3 实证);属下限护栏共性边界,记录备查。
- **N3**:云上生产实跑验证缺(报告已自标)。补强=云上 systemctl 真实格式实测(infinity/55min/10min 解析均对)+ 逻辑推演 + mac 同码返回 900;建议上线后观察下一个 21:40 一轮(确认无 warn、上传正常)闭环"生产侧实跑实证"(L49 精神)。

## 十一、诚实标注:我没做到/做不到的

1. **全量 `pytest scripts/tests`(声称 264 passed)未独立复跑**:本机 system python3 无 pytest;全量含可能触网/落库的用例(派单风险约束),仅用 `.venv/bin/pytest` 在 /tmp 隔离副本复跑本目标测试文件 ⇒ `1 passed`(pytest 收集形态正常,CI 门禁 ⑧ 命令 `python3 -m pytest -q scripts/tests/` 覆盖本文件 ✓)。以"目标测试复跑 + 8 变异反证 + 独立 probe"替代全量回证。
2. **云上 overfit_monitor 本体实跑未做**(禁跑业务脚本):守卫在云上真实路径的"生产实跑实证"以"云上 systemctl 实测 + 同码探测逻辑"近似,未达真跑级。
3. **"从未 force push"服务端不可证**:仅做可见面取证(旧 hash 不在远端任何 ref、reflog 单调、内容逐位一致)。
4. **乙表未全验**:5 条抽查 2 条 + 6 个服务外层值实测样本;乙表整体仍是"判断清单"。

## 十二、复现命令(评审用)

```bash
# 硬门(只读):云上外层墙
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'systemctl show -p TimeoutStartUSec --value trade-overfit-monitor.service'   # infinity
# 独立 probe(全矩阵+真实样本+stub 唯一外呼)
python3 /tmp/probe223_independent.py
# 变异测试 driver(8 变异,隔离副本)
python3 /tmp/mut223/mut_runner.py; python3 /tmp/mut223/mut_e_redo.py
# 目标测试 pytest 形态(/tmp 副本)
/Users/linhuichen/code/trade/.venv/bin/pytest -q /tmp/mut223/scripts/tests/test_223_overfit_monitor_timeout.py   # 1 passed
# git 纪律
git ls-remote origin refs/heads/main refs/heads/feat/223-overfit-monitor-timeout-20261006
```

> 评审原始探针/变异脚本未进仓(一次性工具);本报告为落档本体。
