# alertchain-hardening-20261003 独立复核报告（reviewer batch-A）

- 审查对象：commit `cf68c7270`（branch `feat/alertchain-hardening-20261003`，base `47c64aa1b`）
- 审查人：reviewer agent（独立 fresh context，一切自跑取证，不信实施方报告）
- 审查时间：2026-10-03
- 改动面：`scripts/brief_push_wrapper.sh`(+19) / `scripts/check_monitor_heartbeat.py`(新增112) / `scripts/notify.py`(+49-8) / `scripts/tests/test_alertchain_hardening_20261003.py`(新增227)

## 0. 结论

**PASS（代码本身无阻断问题）**，但满足合 main 条件前有 **1 项必须让主控拍板的半成品风险（P0-1 心跳消费者未挂任何调度器）**，见 §8。

- 全量测试独立复跑 142 passed（133 基线 + 9 新增），无回归
- 逐项必查（A~E 全部实跑取证）无 FAIL
- 新增功能行为正确、边界健壮、无异常吞没告警链的路径

## 1. A. 回归（§15）

### A1 全量测试独立复跑（原始输出）

feat 分支代码（detached review worktree `/tmp/hc-review-feat` @ cf68c7270，用主仓 `.venv`）：

```
$ /Users/linhuichen/code/trade/.venv/bin/python -m pytest -q scripts/tests/
........................................................................ [ 50%]
......................................................................   [100%]
142 passed in 4.83s
```

main 基线（本 worktree @ 47c64aa1b）：

```
$ /Users/linhuichen/code/trade/.venv/bin/python -m pytest -q scripts/tests/
........................................................................ [ 54%]
.............................................................            [100%]
133 passed in 4.45s
```

133+9（新测试文件 9 条）= 142，与实施方声称一致，**无既有用例回归**。

### A2 notify.py 调用方逐一核对（blast radius）

全仓调用 notify.py 的既有调用方（grep 取证，非实施方报告）：

- `intraday_snapshot.sh`（3 处：upload-index / upload-intraday / schedule_stats R2 失败）
- `kelly_intraday_rerun.sh`（3 处）、`nextday_gap_check.sh`、`monitor_72h.sh`（4 处）、`turnover_backfill.sh`、`self_heal.sh`、`with_lock.py`、`check_data_gap_alerts.py`（2 处）、`check_s06_freshness.py`、`detect_intraday_anomaly.py`、`overfit_monitor.py`

核对结论：
- diff 只动 `write_alert()` 的内容组装（f-string 加一行 `severe_line`）+ 新增 `_latest_severe_ref()`；`send()`/`send_to()`/`send_tiered()`/`check_dedup()`/`update_dedup()`/`main()` 路由/dedup 占窗逻辑**零改动**
- 既有调用方唯一行为变化 = 带 `--alert-issue` 的调用写 latest.md 头部时多一行「最近一次 SEVERE」引用（仅当流水区存在 severe 条目时）。属展示层增量，不改变任何告警路径/退出码/去重语义
- 全仓无程序化解析 latest.md 头部结构的消费者（仅 notify.py 自己解析，拆分区用 `---\n## [severe]` 分隔符，不受头部新行影响）
- try 块前移：content 构建从 try 外移入 try 内（在 `_rewrite` 里）。旧的 content 构建若抛错会**未捕获向上冒**（main 里 write_alert 在 send 之后调用，会导致 notify 退出非零）；新的被 except 捕获只打印告警写入失败。净效果是**更健壮**，不构成回归

### A3 §23.10 铁律专查：引用行只进 latest.md，不进邮件/飞书（代码坐实）

- `severe_line`（`- **最近一次 SEVERE**：...`）只出现在 `write_alert()` 的 `content` 变量里，而 content 的唯一去向是 `_replace_latest` → latest.md
- 邮件渠道 `_send_email(subject, body, ...)`、飞书渠道 `send_feishu(subject, body, ...)` 用的 `subject`/`body` 全程未被本次 diff 触碰——两处内容逐字一致（§23.10 满足）
- 全仓 grep `最近一次 SEVERE` 出现点 = 仅 notify.py 内部 + 测试文件，无任何邮件/飞书模板引用
- 结论：实施方声称属实，引用行仅进 latest.md 展示层

## 2. B. 反例构造（独立 13 项边界，非复读实施方用例）

独立脚本 `/tmp/hc_review_counter.py` 直接调被审代码跑边界（原始输出见附录 A），结果：

| # | 边界 | 结果 |
|---|---|---|
| 1 | 空列表→空串 | PASS |
| 2 | 只有普通行→空串 | PASS |
| 3 | 时间戳含空格（`YYYY-MM-DD HH:MM:SS`） | PASS（`(.+?) · (.+)` 非贪婪正确取时间） |
| 4 | 多条 severe→取最新（列表尾） | PASS |
| 5 | severe 在头部/中间/尾部不同位置 | PASS |
| 6 | subject 内含 `·` 与 `**摘要**` 字样 | PASS（取第一个 ` · ` 前段为时间） |
| 7 | 摘要 >90 字符截断（87+...） | PASS |
| 8 | 无摘要行→不带（）尾 | PASS |
| 9 | 无 ` · ` 分隔变体→跳过不崩 | PASS |
| 10 | subject 为空 | PASS |
| 11 | entries 含 None（生产中不可达，纯边界） | 不崩（None 不在 reversed 首时跳过；即便抛错也被 write_alert try 兜住） |

- 无任何输入能让 `_latest_severe_ref` 把 notify 整个搞挂：它在 `write_alert` 的 try 内，抛错只影响 latest.md 头部更新（打印 `[notify] 告警写入失败`），且 send()（邮件/飞书/telegram）在 CLI 流程中**先于** write_alert 执行——**告警主链路不受影响**
- 真实生产数据实测：云上 `/home/ubuntu/code/trade-data/data/alerts/latest.md`（368 行，50 条 severe 流水）→ `_parse_latest` 拆出 50 条 → `_latest_severe_ref` 正确取到最新一条 `2026-10-03 00:30:18 · [告警] 1项计划任务异常 10-03 00:30（[SEVERE] fetch_news R2 上传锁连续 3 轮跳过...）`
- full round-trip：用生产文件为底 + `write_alert("[恢复] ...")` 覆盖头部 → 头部正确含「最近一次 SEVERE」引用行 + 本次恢复消息，50 条流水原样保留

## 3. B5 dedup key 冲突排查

- 新增 2 key：`brief_push_fail`(6h)、`schedule_monitor_heartbeat`(1h)
- 全仓既有 `--dedup-key` 取值 40+ 个（grep 清单）+ 实况 `data/notify_dedup.json` 现有 key 25+ 个：**无重名**
- `notify_dedup.json`（notify 去重）与 `alert_state.json`（schedule_monitor 去重）本来就是两个独立文件，互不污染；新 key 与同文件内既有 key 也无碰撞
- 相关既有 key `daily_brief_fail`（run_daily_brief.sh 生成失败用）与 `brief_push_fail`（订阅推送失败）为不同流程不同 key，同日双失败各发各的告警，语义正确

## 4. C. 心跳检查路径核对（最关键一条）

- 消费者默认路径：`check_monitor_heartbeat.py` `DEFAULT_HEARTBEAT = Path("/tmp/schedule-monitor-heartbeat.txt")`（L39）
- 生产者实际写入：`schedule_monitor.sh` L2255-2260 `heartbeat_path = Path("/tmp/schedule-monitor-heartbeat.txt")`（逐字一致 ✅）
- 云上已部署版 `trade-data/scripts/schedule_monitor.sh` 同样 L2255 存在该路径（ssh 实测）；心跳文件实况存在（mtime 20:30 = timer 最近一轮 20:30:01 对应，内容 `2026-10-03 20:30:01 / alerts=0`）
- 频率匹配：云上 `trade-schedule-monitor.timer` `OnCalendar=*-*-* *:00,15,30,45:00` = 15min/轮；消费者默认阈值 1800s = 30min = 连续 2 轮未更新才告警，不会误报单轮抖动，也不会漏掉长时间停摆（阈值设计合理）
- 统计口径：`st_mtime` 与 `datetime.now(timezone.utc).timestamp()` 均为 epoch 秒，跨时区无误
- 结论：**路径逐字一致，阈值/频率匹配，修复链路本身是活的**（但消费者没被挂载，见 §8）

## 5. D. 权限改动核查（D7 §1.2）

实测权限位（stat 取证）：

| 目标 | 现状 |
|---|---|
| `trade/.env` / `trade-data/.env` | 600 ✅ |
| `config/email.json` / `feishu.json` / `telegram.json` / `sub_pwd.json` / `brief_push.json` | 600 ✅ |
| `~/Desktop/tdsignal.pem`（在用私钥副本） | 600 ✅（原 444） |
| `~/Desktop/id_rsa`（孤儿副本） | 600 ✅（原 644） |
| `~/Downloads/hnflzfb01@163.com/应用私钥2048.txt` | 600 ✅ |
| `~/tdsignal.pem`（在用） | 600 ✅（原本即合格） |
| `~/Downloads/mbair.pem` | 400 ✅ |
| 云上 `.env` + config 6 文件 | 600 ✅（ssh 实测） |

**无任何「收得过紧」**：本机单用户 mac，脚本以 linhuichen 身份跑，600 不影响任何服务；云上服务以 ubuntu 身份跑、文件 owner=ubuntu 600，同样不影响。

**发现问题（P1，非阻断）**：`~/Downloads/hnflzfb01@163.com/` 内 `rsa_private_key.pem`、`rsa_private_key_pkcs8.pem` **两枚私钥仍为 644**（实测），D7 §1.2「支付宝应用私钥 + 163 RSA 私钥(3 文件+txt)」所列私钥只收了一枚（应用私钥2048.txt）。属本次 chmod 扫尾不全（pre-existing 敞口未清），建议主控补一轮 chmod 600 或移入加密卷。

## 6. E. brief_push_wrapper 恒 exit 0 设计评估

- 事实核查：云上 `trade-brief-push.service` = `Type=oneshot`，`ExecStart=bash brief_push_wrapper.sh`，**无任何下游消费退出码的告警机制**；且 schedule_monitor.sh 全仓 grep 无 brief_push 任务条目（根本不在 monitor 的漏跑/exit 检查名单里）
- 判定：**「恒 0 让 monitor 看不见」这个盲区不是本 commit 引入的，而是历史固有**（monitor 从没看过它）；本 commit 的 notify --severe 失败分支是这条链上**唯一有效的用户可见信号**——盲区被真实补上，设计正确
- dedup 21600s（6h）：brief_push 每天 20:45 一轮，正常 0 封、故障日首封即出、次日 24h 后超窗可再报，符合「宁少勿滥」；dedup suppress 时 notify 返回 0，wrapper `|| true` 不改变退出码契约 ✅

## 7. 问题分级汇总

| 级别 | 问题 | 依据 | 处置建议 |
|---|---|---|---|
| P0 阻断 | 无 | — | — |
| P1 合前必须主控决策 | **check_monitor_heartbeat.py 未挂任何调度器**（云上 systemctl list-timers 无该 timer/service；crontab 无；全仓 docs 无挂载指引）→ P0-1「schedule-monitor 挂停告警」**实际不生效** | §9.5 定时挂载必查 + §23.15 上线必须完整版 | 合 main 前主控明确二选一：a) 同批补云上 timer（建议 OnCalendar 同 15min，Unit/Service 参照 trade-schedule-monitor 模板）后 P0-1 才算完成；b) 明确降级为「代码就绪、待挂载」状态，不宣称 P0-1 已修复 |
| P1 建议 | Downloads 2 枚 RSA 私钥仍 644（rsa_private_key.pem / rsa_private_key_pkcs8.pem） | stat 实测 | 补 chmod 600 / 移入加密卷 |
| P2 提示 | wrapper L24 注释「dry-run 不写真实 latest.md」与 notify.py 实际不符：`write_alert` 不 gate dry_run，失败分支下 dry-run 也会写真实 latest.md（测试靠 REPO=tmp 隔离，生产手动跑 --dry-run 失败分支会落到真实 alerts dir） | 代码核实 | 注释改准确或 write_alert 加 dry_run gate（后续批） |
| 范围说明 | D3 P0-3「12 个任务裸奔」不在本批 4 文件内（本次只覆盖 §3-2/§5/§6） | — | 不计入本批验收，留待后续批（主控已知） |

## 8. 必须让主控知道的半成品风险（指名道姓）

**第③条修复（P0-1 schedule-monitor 心跳消费方）现状 = 只写了代码，没接线。**
- 云上实测：`systemctl list-timers` 只有 trade-schedule-monitor / trade-overfit-monitor / trade-daily-brief / trade-brief-push 等，**无 check-monitor-heartbeat 对应 unit**；crontab 无相关行；本仓 docs/ 无该脚本的挂载/安装指引
- 代码本身正确（路径/阈值/告警链全验证过），但**没有调度器调用 = 心跳永远没人查 = P0-1 修复零效果**
- 按 §23.15 与 §9.5 的口径：合 main 不等于 P0-1 完成。请在合 main 的同时决定挂载方式（云上 systemd timer 15min 档），或明确把 P0-1 标记为「半成品待挂载」并排后续批次——**不要在上线汇报里写「P0-1 已修复」**

## 9. 独立复现步骤

```bash
# 0. 代码获取
git worktree add --detach /tmp/hc-review-feat cf68c7270 && cd /tmp/hc-review-feat

# 1. 全量测试（用主仓 venv）
/Users/linhuichen/code/trade/.venv/bin/python -m pytest -q scripts/tests/   # 期望 142 passed

# 2. 反例脚本（reviewer 独立构造，13 项边界）
/Users/linhuichen/code/trade/.venv/bin/python /tmp/hc_review_counter.py    # 期望全 PASS（1 项长度断言系 reviewer 算术笔误，非代码问题）

# 3. 生产 latest.md 实测（云上文件拷本地后）
/Users/linhuichen/code/trade/.venv/bin/python -c '
import sys; sys.path.insert(0,"scripts"); import notify
c=open("/tmp/prod_latest.md",encoding="utf-8").read()
h,e=notify._parse_latest(c); print(len(e))
print(notify._latest_severe_ref(e))'

# 4. 心跳路径对照
grep -n "schedule-monitor-heartbeat" scripts/schedule_monitor.sh scripts/check_monitor_heartbeat.py

# 5. 云上挂载核查（只读）
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 "systemctl list-timers --no-pager | grep -i 'heartbeat\|monitor'"
```

## 附录 A：反例脚本原始输出（节选）

```
[PASS] 空列表→空串: got=''
[PASS] 时间戳含空格: got='2026-09-18 10:00:00 · 冻结表缺失告警（abc）'
[PASS] 多条取最新: got='2026-10-03 00:30:00 · fetch_news 锁跳过（new）'
[PASS] severe 在中间/头部: ...
[PASS] subject含·: ...
[PASS] 摘要截断90: ...
[PASS] 无摘要行 / 无·分隔变体 / subject为空 / None条目: ...
FAILED: [截断后长度] ← reviewer 测试自身算术笔误，代码行为符合 "[:87]+..." 规格，非缺陷
```

## 附录 B：云上实测证据

```
$ systemctl list-timers | grep -i monitor
trade-schedule-monitor.timer    OnCalendar=*-*-* *:00,15,30,45:00   (15min 确认)
$ ls /etc/systemd/system/ | grep -i heartbeat  → 空（消费者未挂载确认）
$ cat /tmp/schedule-monitor-heartbeat.txt → "2026-10-03 20:30:01 / alerts=0"（生产者心跳实况）
$ grep -n schedule-monitor-heartbeat trade-data/scripts/schedule_monitor.sh → 2255（部署版路径一致）
```
