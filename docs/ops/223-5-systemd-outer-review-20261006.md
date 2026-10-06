# #223-⑤ 云上两 unit 外层 `TimeoutStartSec` 抬升 —— 独立复核报告(2026-10-07)

- 复审对象:`feat/223-5-systemd-outer-20261006` @ `0aa8fc265`(3 文件:实施报告 + 权威快照重 dump + doc §2 对齐)
- 性质:**对「已生效云上生产变更」的独立复核**(unit 手管、不经 merge 门槛)+ 仓库侧 merge 资格判定
- 方法:全只读;ssh 独立复测;自建新鲜 dump 做字节级比对;三审计复跑 + 负控制;代码 / 生产日志 / 监控三源交叉
- 硬约束遵守:未改云上任何 unit、未执行备份恢复、未 daemon-reload、未 start/stop/restart、未跑任何业务脚本(探针全部 static-only)、零真实外发、未动任何分支/worktree

## 0. 结论摘要

| # | 必审项 | 结论 |
|---|---|---|
| 1 | 云上实值独立复测(1080/1740;除该行外一字未变) | **PASS** |
| 2 | §25 备份与恢复路径独立验证(未执行恢复) | **PASS** |
| 3 | 新值算式独立复算(780 / 1440,串行性与重复计数核查) | **PASS** |
| 4 | **头号必答:新上限是否撞车/造出新盲区** | **PASS(新窗口有界、可接受;如实定性见 §4)** |
| 5 | 零外发 / 零误跑独立证据 | **PASS** |
| 6 | 三审计独立复跑 + 快照实时性(非照抄旧值) | **PASS(含负控制)** |
| 7 | 举一反三独立复核(调用方穷举 / 全表倒挂) | **PASS** |
| 8 | git 纪律(tip / base / 无夹带 / trailer / 无 force) | **PASS** |
| 9 | **实施报告事实准确性** | **FAIL(2 处,必须更正,见 §9)** |

**总判定:条件 PASS** ——
- **云上变更:不建议回滚**(改前 600 已真实吃生产运行:10-04 硬杀实录 + 8 个交易日运行残缺,见 §4.3/§9;回滚=恢复已知病态)。
- **仓库侧:快照 + doc §2 正确,可合**;**实施报告 §1.3/§1.2 两处事实错误必须先更正**(更正文本已给,§9),建议 implementer 在原 feat 分支补一个更正 commit 后整支走 main-merge。
- **运维时序注意(§11)**:merge 后云上树快照端未更新,10-07 08:27 patrol 预期会报一次漂移告警(预期内瞬态)。

## 1. 云上实值独立复测(PASS)

- 我自 `/etc/systemd/system` 只读重 dump 全量 82 unit(`@@@FILE:` 格式),与仓库快照 `docs/deploy/systemd-units-cloud-snapshot.txt` 做 **字节级 diff:全空(逐字节一致)**——比字段级更强的"快照=云上现值"证明。
- 两 unit 现值:**fetch-news=1080、daily-brief=1740**;`systemctl show -p TimeoutStartUSec` = `18min` / `29min`(独立读取吻合)。
- **除 TimeoutStartSec 外一字未变**:云上备份 vs 现文件 `diff` = 恰好 1 行(fetch-news 第 13 行、daily-brief 第 14 行,仅 `600`→`1080`/`1740`);timer 文件未动(mtime 仍 Sep 14);改动窗口 journal 仅见 2×sed + 1×daemon-reload,无其他 unit 动作。

## 2. §25 备份与恢复路径(PASS,未执行恢复)

- **三方 md5 逐位一致**:云上 `~/unit-backup-20261006/` == mac 本地 `~/unit-backup-20261006/` == 报告 §3 表
  - trade-fetch-news.service `fe9aa7375ec8bddbede14cd13d393cfd`
  - trade-daily-brief.service `b7b726c9c80a9b28c24c3aa817050154`
- `diff`(备份, 现文件)= 恰一行/各一 ⇒ **备份=改前原件**成立(另两重旁证:Oct 5 21:00 / Oct 5 21:50 / Oct 6 08:27 三次 patrol 全 PASS「云上==云上树快照」,当时两 unit=600;10-05/06 systemctl 记录)。
- 恢复命令语法复核可用(未执行):`ssh ... 'sudo cp ~/unit-backup-20261006/trade-fetch-news.service /etc/systemd/system/ && sudo cp ~/unit-backup-20261006/trade-daily-brief.service /etc/systemd/system/ && sudo systemctl daemon-reload'`。
- 备份前置顺序成立:备份 mtime 10-6 23:47,改动(文件 mtime)23:48:13。

## 3. 新值算式独立复算(PASS)

**fetch-news = 780**(R2 段 120+60 + staticdata 段 600):
- `fetch_news.py:722` R2 subprocess `timeout=120` + `_r2_skip_retry` 默认 60(`:717`,云上 .env 未设 `R2_UPLOAD_SKIP_RETRY_SECS`)⇒ 180;
- `:753-755` staticdata_sync `timeout=600`;两段**同一次运行内串行**(`sync_news_digest_live()` 顺序执行),各自有 `except subprocess.TimeoutExpired`(优雅)⇒ 合计 780;+300=1080 ✓

**daily-brief = 1440**(四段两对,主数据 + run_log):
- `gen_daily_brief.py main()`:`@4390 upload_to_r2`(120,记录于 @4391)→ `@4394 staticdata_sync`(600,记录于 @4395)→ …… → `@4431 upload_to_r2(files=[RUN_LOG_FILE])` → `@4432 staticdata_sync(files=[RUN_LOG_FILE])`;
- 两对为**不同调用点、同一次运行内串行**,逐行核无重复计数 ⇒ 合计 1440;+300=1740 ✓

**边界如实标注(非阻断)**:"L1 链"口径=有 `except TimeoutExpired` 的 subprocess 段(与复审报告 §11 分层一致);同链路还有不计入的耗时层——取数 HTTP(三源,失败即 break,实测常态单轮整体 22~37s、最坏抽样 108s)、multi-agent 生成(6 角色并行)、通知 30s。叠加后:
- fetch-news 全栈典型包络 ≈ 810~930s(偶发复合慢日可越过 960s ⇒ 见 §4 重叠窗);
- daily-brief 全栈最坏 ≈ 1620~1660s,对 1740 余量收窄至 ~80~120s;**复合极端日 systemd 仍可能先行杀**(退化为改前行为,不新增危险类别)。

## 4. 头号必答:新上限会不会撞车 / 造出新盲区 —— 结论:新窗口被引入但有界、可接受

### 4.1 事实基线
- `trade-fetch-news.timer` OnCalendar=`*-*-* *:01,45:00` ⇒ **最小触发间隔 16min=960s**;`trade-daily-brief.timer` 每日 20:40(周期 24h,自身不可能重叠)。
- 语义:oneshot running 时 timer 再触发 ⇒ 新 start job 与既有 start job 合并,**该轮跳过(不排队、不失败)**。来源质量 caveat:官方 freedesktop 页本机网络无法抓取,结论来自社区/文档级共识;journal 内无实测重叠样本可用(旧值 600<960,数学上不可能出现)。

### 4.2 改前为什么没这个问题 + 新类别判定(如实)
- 改前:上界 600 ⇒ fetch-news 单轮 ≤600s < 960s(永不重叠);daily-brief ≤600s ⇒ 最晚 20:50,到不了 21:00。
- 改后 ① fetch-news:上界 1080 > 960,形式上重叠窗存在;但进程寿命绝大多数受 780(L1 硬上界)+ 取数层(失败即断、实测 22~108s)夹住 ⇒ 需要"取数/其他非 L1 段额外悬挂 >~45s"才真摸到 960s。若摸到且恰被下一轮触发:**最坏=跳过一轮 news 刷新,≤44min 后自愈**(下一档 :01/:45 照跑)。
- 改后 ② daily-brief:病态日(两段 staticdata 皆逼近 600 + 余项慢)最坏跑到 ≈21:09,与 **21:00 trade-backup-db** 重叠 ≤9min。backup-db=sqlite 热备+upload-db(R2 小)、**无共享锁、不读同源文件**(149d 文档原位判词:"性质轻……重叠伤害小")⇒ **评估良性**。
- **定性:新类别确有引入(改前数学上不可能,改后存在窄窗)——但被 1080/780 与 1740/1440 双层夹住;最坏后果=一轮跳过(自愈)或与轻任务并行 ≤9min;且该病态日恰是改前"必然被硬杀"的日子**(把"必然失败"换成"完成+与邻无害并行"=净改善)。

### 4.3 改后真实事故面(独立新发现)
- **10-04 20:01 轮 fetch-news 曾卡死 600s 被 systemd 硬杀**(journal 实录:`20:01:00 Starting` → `20:11:00 start operation timed out. Terminating.` + `Main process exited, code=killed, status=15/TERM` + `Failed with result 'timeout'`);20:45 下一轮(24s)正常恢复 ⇒ 旧值 600 已真实吃生产运行,本变更方向正确。
- KillMode=control-group / KillSignal=15 / TimeoutStopUSec=30s(独立读取),硬杀语义与推断一致。

## 5. 零外发 / 零误跑独立证据(PASS)

改动窗口(10-6 23:47~23:52,实值单位 mtime 23:48:13):sudo 审计行仅 2×sed + 1×daemon-reload(逐条可见);窗口内无任何 trade-* unit 被触发(journal 仅 23:52:01 self-heal / 23:45 schedule-monitor 等正常节律);`data/alerts/latest.md` mtime=2026-10-06 17:16:27 未变、alerts 目录无新文件;无新 R2 写痕迹;改后首轮 fetch-news(10-07 00:01)正常完成(33s);`systemctl --failed` 空。

## 6. 三审计独立复跑 + 快照实时性(PASS)

| 审计 | 命令(我独立执行) | 结果 |
|---|---|---|
| 梯度 | `systemd_timeout_gradient_audit.py --dump docs/deploy/systemd-units-cloud-snapshot.txt` | 41 service,**倒挂 FAIL 0**;rc=0(1740/1080 显示为"非 .sh,无 shell 内层看门狗"——与脚本头「局限」一致,Python 侧梯度靠 §3 分析覆盖) |
| check-doc | `--dump /tmp/223-5-fresh-cloud-dump-review.txt --check-doc`(权威源=**我自己新 dump 的云上实值**) | ✓ 82 unit 逐字段全量比对通过;rc=0 |
| check-snapshot | `--dump /tmp/223-5-fresh-cloud-dump-review.txt --snapshot docs/deploy/systemd-units-cloud-snapshot.txt --check-snapshot` | ✓ 82 unit 逐字段通过;rc=0 |
| **负控制**(证明审计非空转) | 把新鲜 dump 中 1080 篡改为 999 当快照 | ✗ 正确报差异 1 处(`trade-fetch-news.service TimeoutStartSec ['1080'] vs ['999']`);rc=1 |

**快照实时性**:我自云上新 dump vs 仓库快照 **逐字节一致**(§1),且两处 1080/1740 在场 ⇒ 重 dump 快照真反映云上现值,非照抄旧值。

## 7. 举一反三独立复核(PASS)

- `staticdata_sync.sh` 生产调用方穷举复核=3 处:`fetch_news.py:754`(600,本任务已修)/ `gen_daily_brief.py:3166`(600,本任务已修)/ `intraday_snapshot.sh:202`(`STATICDATA_SYNC_NONBLOCK=1` 且外层 `trade-intraday-snapshot.service TimeoutStartSec=0(∞)`)⇒ 第 3 处无天花板、非同类成立。
- 全量梯度审计 41 service:**除本次两处外无任何"外层≤内层"倒挂 FAIL**;`trade-turnover-backfill`(outer=0/inner=9900 OK)等"外层=0"族无倒挂。
- §21 算法公示 N/A(无算法/数值/评分变更)成立;§23.1 README N/A 成立。

## 8. git 纪律(PASS)

- 远端 main tip=`2e1a564d5…`(与本地 origin/main 一致);分支 tip=`0aa8fc265`(与任务给定一致)。
- base 新鲜度:分支 base=`6f499e775`,**∈ origin/main 祖先链**(merge-base 即该点;origin/main 后续 +2 commit 为 #223④ merge 与 docs 收口,与本分支无文件交叠)。
- reflog:created → commit → rebase(finish),**无 forced-update / 无 reset 重写**。
- 提交仅 3 文件:2×docs/deploy(快照/doc §2 各 2 行)+ 1 报告;**无 data/、无前端 HTML/JS、无版本串 bump**(版本串无关:未动前端源码)。doc/snapshot 两文件 diff 内容=恰 `2×+1080 / 2×+1740 / 4×-600`(即两文件各改两行)。
- trailer:Co-Authored-By 在位(`Claude Code <noreply@anthropic.com>`,与现网 main 最近提交惯例一致;根 CLAUDE.md §8 文本写 `Claude`,为文本陈旧,非本次问题)。

## 9. 实施报告事实错误(2 处,必须更正后再合) —— 本项 FAIL

### 9.1 报告 §1.3 "破例实跑的 09-28/29/30 正常完成" —— **与事实相反**
我的独立取证(三源交叉,全可复现):
1. **launchd 完成回声**(`daily_brief_launchd.log` 44 行全文):0914–1006 共 12 个交易日中,**8 日无任何完成回声**(0914/0916/0917/0918/0922/0928/0929/0930,即 `✓ 完成`/影子对账/ledger 三段全缺);完整完成的只有 0915/0921/0923/0924(总时长 25~47s)。0928 的日志止于 `✗ R2_UPLOAD_TIMEOUT` 后断流。
2. **权威产物 run_log**:条目恰为 `[0924,0923,0921,0915,0914]`(头插+截 5)——0916–0918/0922/0928–0930 **从未写入条目**(若曾写入,列表形状会不同,可反推)。
3. **监控侧**:schedule_monitor 日志有 0928 的 `R2_UPLOAD_TIMEOUT` 告警(last_alerted=2026-09-28 20:45,后转 recovery)。
4. **机制溯源(我新追)**:doc 历史显示迁移批(09-12)daily-brief=900、fetch-news 无(默认 90s)→ 09-14 `ef8d8c46b/50ff32073` 补/调 → **09-16 #36「超时收口」统一压到 600**(docs/deploy/timeout-caliber-20260916.md)。0914(900 时代)与 0916 起(600 时代)行为差异完全吻合:0914 的 run_log 条目(staticdata=600.04 撞满内层 600 上限)说明当日进程活到了尾部阶段(900s 时限内被杀于尾段);0916 起 600 竟先于内层优雅超时 ⇒ 杀干净、无条目。
**更正文本建议(替换该句)**:
> "daily-brief:国庆假期区间均命中「非交易日跳过」(1s);**09-14 起 12 个交易日中 8 日运行未完成**(0914/0916/0917/0918/0922/0928/0929/0930 无完成回声;run_log 最新条目=0924),0928 留 `✗ R2_UPLOAD_TIMEOUT` 后断流;**本修复正针对这一持续真实发生的中断**;另 10-04 20:01 轮 fetch-news 卡死 600s 被 systemd 硬杀(journal 实录:20:01:00 Starting → 20:11:00 `start operation timed out` + `status=15/TERM` + `Failed with result 'timeout'`),20:45 下一轮 24s 恢复正常。"

### 9.2 报告 §1.2 "✗ R2_UPLOAD_TIMEOUT(超 120s,2026-09-29)" —— **日期误记,实为 09-28**
该行位于 `daily_brief.log` 第 189 行,位次夹在「开始生成 2026-09-28」(184)与「开始生成 2026-09-29」(190)之间 ⇒ 发生于 09-28 的轮次;监控 last_alerted=2026-09-28 20:45 亦印证。更正为 **2026-09-28**。

### 9.3 其余数字抽检全对(不列错)
108s 极值=10-05 00:45:00→00:46:48 journal 逐秒吻合;timings 表 [0914/0915/0921/0923/0924] 与 run_log 逐位吻合;备份 md5 / 恢复命令 / 零外发项 / 审计三连均通过(见 §1/§2/§5/§6)。

## 10. 未做到 / 做不到(如实)

1. 9 月 journal 已轮转(现仅存自 10-02 18:08)⇒ 0916–0930 的 systemd 层直接杀记录不可得,以三源旁证(launchd log + run_log + 监控日志)+ doc 溯源替代;10-04 硬杀有 journal 实录。
2. freedesktop 官方文档未能抓取(域名校验失败)⇒ "运行中再触发=跳过"结论来源为社区/文档级共识(已标注);未做云上实测(硬约束禁 start/stop,且无 >960s 历史样本)。
3. 未执行任何备份恢复(遵照硬约束);恢复命令仅语法复核。
4. 10-04 卡死轮的"卡在哪一段"未坐实(轮内日志无逐行时间戳,journal 仅给杀时刻),不展开归因。
5. #223-⑤ 的"用户已批准"审批链来源=报告/主控转述(仓库内无独立凭据),照录不背书。

## 11. merge 资格判定 + 处置建议

1. **仓库侧(快照 + doc §2):可以合**(逐字节=云上实值;check-doc PASS;无代码/数据/前端内容)。
2. **实施报告:更正 §9.1/§9.2 两处后整支 merge**(建议 implementer 原 feat 分支补 1 个更正 commit;若主控评估时效优先,也可随 merge 后立即以 docs 提交补正——两处均为文档事实描述,不影响云上/代码/数据正确性)。
3. **云上变更:不建议回滚**。回滚命令备查(非必需,勿执行):`ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'sudo cp ~/unit-backup-20261006/trade-fetch-news.service /etc/systemd/system/ && sudo cp ~/unit-backup-20261006/trade-daily-brief.service /etc/systemd/system/ && sudo systemctl daemon-reload'`;仓库侧配套 `git revert <本 commit>`。
4. **运维时序(重要)**:云上树(GIT_REPO=trade-data-signal)内快照当前仍 600/600,而 patrol 每日 08:27 比对"云上实值 vs 云上树快照" ⇒ **10-07 08:27 预期报一次漂移告警(预期内瞬态)**;merge 后尽快让云上拉取到新快照即可消除(或接受这一次告警,次日自愈)。
5. `docs/pending-features-index.md` #223 行 ⑤ 完成状态由主控登记(实施报告 §8 已声明未代改)。
6. 观察建议(非阻断):本修复后,交易日 run_log 条目应恢复连续(对"中断类"的验收信号);fetch-news 轮次若出现跳档,按 §4.2 判为已知窄窗自愈行为。

## 附:独立复算命令与证据锚点(可复现)

```
# 新鲜云上 dump(只读)与字节比对
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'cd /etc/systemd/system && for f in trade-*.service trade-*.timer; do echo "@@@FILE:$(basename $f)"; cat "$f"; done' > /tmp/223-5-fresh-cloud-dump-review.txt
diff /tmp/223-5-fresh-cloud-dump-review.txt <repo>/docs/deploy/systemd-units-cloud-snapshot.txt   # 空=逐字节一致
# 三审计(+负控制)
python3 scripts/systemd_timeout_gradient_audit.py --dump <snapshot>
python3 scripts/systemd_timeout_gradient_audit.py --dump /tmp/223-5-fresh-cloud-dump-review.txt --check-doc
python3 scripts/systemd_timeout_gradient_audit.py --dump /tmp/223-5-fresh-cloud-dump-review.txt --snapshot <snapshot> --check-snapshot
# 备份差异 / md5
ssh ... 'sudo diff ~/unit-backup-20261006/trade-fetch-news.service /etc/systemd/system/trade-fetch-news.service'   # 恰 1 行
md5sum(云上备份) / md5 -q(mac 备份)   # fe9aa737… / b7b726c9…
# 生产证据
journalctl -u trade-fetch-news.service --since "2026-10-04 20:00" --until "2026-10-04 20:46"
grep -n "开始生成\|✗" <cloud>/data/logs/daily_brief.log ; cat -n <cloud>/data/logs/daily_brief_launchd.log   # 44 行全文
python3 -c '<读 daily_brief_run_log.json 打印 items>'   # [0924,0923,0921,0915,0914]
git log -p -S "TimeoutStartSec" -- docs/deploy/systemd-units-20260912.md   # 09-16 收口 600 溯源
```
证据快照留存:/tmp/223-5-fresh-cloud-dump-review.txt(云上新 dump,82 unit);评审过程另见进度文件 /tmp/agent-progress-223-5-review.md。
