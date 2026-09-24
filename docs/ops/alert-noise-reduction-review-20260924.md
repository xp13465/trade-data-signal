# 告警降噪 5 条 Review 报告(2026-09-24)

> reviewer 独立审查 | 对象: `worktree-agent-a2f56d09bf34000ff` @ `64d15f4fb`(base `c3d4a83a7`)
> 结论:**PASS-with-conditions** | 三条 condition 均为可接受 trade-off,不阻塞 merge,见 §4

## 0. 审查口径

- 按 §14 通知即时性铁律(命门):降噪只能去重/聚合/减 payload,禁降频/后台暂停
- §23.7 冻结契约:授权范围 = 用户 2026-09-24 拍板「五条全上(P0+P1+P2)」5 条,重点查夹带
- §10.2 置信度过滤:进报告的 finding 均 ≥80(已验证);另 2 个低分项(<80)已滤,见 §6

## 1. 授权范围与夹带检查 — PASS

diff 仅 6 文件:实施报告 + 5 个授权代码文件(deploy.sh / schedule_monitor.sh / self_heal.sh / signal_kelly_backtest.py / with_lock.py)。
**无前端改动**(app.js/lab.js/common.js/style.css/index.html 均未出现),**无授权范围外代码改动**。符合 §23.7。

| 文件:行号 | 声称改动 | 独立复核 |
|---|---|---|
| deploy.sh:1071 | board_etf_map dedup 3600→21600 | ✓ 逐行确认,key `board_etf_map_stale` 不变 |
| deploy.sh:1059 | R2 失败 dedup 1800→21600 | ✓ key `deploy_r2_upload_fail` 不变;前置条件「verify-channels rc!=0 才走到」核实成立(见 §3.2) |
| schedule_monitor.sh:236 | RECOVERY_COOLDOWN 30min→6h | ✓ `timedelta(hours=6)`;同时供恢复静默窗 + 复现抑制窗 |
| schedule_monitor.sh:251 | 新增 `_recurrence_suppressed` | ✓ 三分支独立走查 + 源提取自测 7 例全 PASS |
| schedule_monitor.sh:1974 | 恢复汇总 dedup 6h | ✓ `--dedup-key schedule_monitor_recovery --dedup-window 21600` |
| signal_kelly_backtest.py:312/334 | 冻结缺键分级阈值=10 | ✓ `FROZEN_MISSING_SEVERE_THRESHOLD = 10`;n≥10 SEVERE+1h dedup / n<10 WARN+24h dedup |
| with_lock.py:112 | 排队超时 dedup 1800→21600 | ✓ key 含 lockpath,保持 --severe |
| self_heal.sh:148/185 | notify_severe→notify_limit_info(--tier info) | ✓ 无 --severe 残留;落盘 data/alerts/info_log.jsonl |

## 2. §14 通知即时性优先铁律(命门)— PASS

**逐条回答「真问题时它还会响吗?多快响?」:**

| 场景 | 还会响吗 | 多快 |
|---|---|---|
| 任务首次异常(exit!=0/log 异常) | 响 | SEVERE 直发,alert_state 首次 None → 发,无 notify dedup(实施方声称属实:L1908-1935 SEVERE 块靠 alert_state active 去重,非 notify dedup) |
| 任务持续异常(active) | 不重复发 | 首次已发;active 走 suppress 不重发(既有行为,非本次引入) |
| 恢复后 **>6h** 复现(真复发) | 响 | `_recurrence_suppressed` 超窗 → return False → 发 SEVERE ✓ |
| 恢复后 **<6h** 复现(振荡) | 抑制 | 设计目标(9-18 一天 13 封根因),降噪授权内 |
| R2 失败 verify 确认缺口(首封) | 响 | 6h 内首次直发 ✓ |
| board_etf_map 旧版兜底(首封) | 响 | 6h 内首次直发 ✓ |
| with_lock 排队超时(首封) | 响 | --severe 保留,6h 内首封直发 ✓ |

**降噪手段合规性**:全部为 dedup 窗口拉长(1800/3600→21600)+ 恢复邮件聚合(dedup-key),**无降频/无后台暂停/无减 payload**。符合 §14 字面。

**fail-open 验证(异常时放行)**:
- notify.check_dedup:文件不存在/解析失败/key 不存在/格式坏 → return False 正常发送(L1208-1226)✓
- `_recurrence_suppressed`:None / active / 无 last_recovered / 格式坏 → 全部 return False 放行 ✓(源提取自测 7 例已核实)

## 3. dedup 吞真告警场景 — 逐处构造验证

### 3.1 board_etf_map(key `board_etf_map_stale`,6h)— 不吞
- 走到 notify 的唯一前提:`MAP_STALE=1`(build 失败 + 旧版兜底,L1068)。6h 内重复 = 同一失败面(akshare 反爬持续),首封已直发。6h 后仍失败重新可发 → 真问题持续可见(32 封/3 天 → 压到每 6h 一封),修复后自然归零。✓

### 3.2 deploy R2 失败(key `deploy_r2_upload_fail`,6h)— **Condition C1(见 §4)**
- 前置核实:走到 notify = `R2_FAIL` 非空(真有文件失败)&& verify-channels rc!=0(轻量对账确认缺口,双重确认)。实施方「仅 rc!=0 真缺口才走到」**属实** ✓
- 风险点:**key 不区分失败通道**。6h 窗口内若两次 deploy 出现**不同通道**的新真缺口,第二封被 dedup 吞。verify-channels 确认过是真缺口,却可能静默。
- 严重度评估:deploy 一天 1-2 次(update_all 17:50 + backfill 偶发),6h 内两次独立真缺口场景罕见;且首封正文已含当时失败通道列表,用户按指引 `upload-all-data` 补刷全量可覆盖后续缺口。→ 可接受 trade-off,但需主控知悉。

### 3.3 with_lock(key 含 lockpath,6h)— 不吞
- 排队超时 = 锁竞争瞬时已自愈(8 封/周噪音)。6h 内同 lockpath 二次超时 = 另一次瞬时竞争,非新真问题。真锁死(排队互相饿死)由 schedule_monitor exit/产物时效/进行中超时通道兜底,不掩盖。✓

## 4. Conditions(可接受 trade-off,建议知悉,不阻塞 merge)

- **C1(deploy R2 dedup key 粒度)**:`deploy_r2_upload_fail` 不区分失败通道,6h 内不同通道新缺口可能被吞。**最小修法(如需)**:key 加失败通道维度,如 `deploy_r2_upload_fail:{通道hash}`(代价:9-20 一天 8 封的降噪会按通道打折)。**或接受现状**(首封含失败通道列表 + 补刷全量覆盖)。
- **C2(schedule_monitor 恢复后 <6h 复现且持续异常)**:复现那轮 SEVERE 被抑制并翻 active,之后即使异常持续 >6h 也不会自动重新 SEVERE(active 走 suppress)。用户只收到首封 SEVERE + 恢复邮件,复现后持续坏仅 alert_state.json 可查。这是振荡抑制的设计意图(无法区分振荡 vs 真复发),但实施方「真卡死不吞」表述应精确化为「首次异常不吞;恢复后 <6h 复现被抑制(降噪设计)」。**最小修法(如需)**:抑制时记 `suppressed_at`,active 持续 >6h 后允许再触发一次 SEVERE。
- **C3(info_log.jsonl 无展示面)**:self_heal 达上限降 `--tier info` 后落盘 `data/alerts/info_log.jsonl`,但该文件**无任何前端/管理端展示面**(grep static-site/app/templates 均无引用)。「只落盘 dashboard」表述与现状不符——是可查文件(能 grep)非页面可见。达上限本身是低价值信号(自愈机制正常工作,次日重置),且机制失效由 schedule_monitor launchctl failed 通道兜底(已核实 L820-838:com.trade.self-heal 不在 _schedule_stats_labels → failed 降级告警保留发现能力),可接受。**最小修法(如需)**:管理端 dashboard 读 info_log.jsonl(建议记待办,不在本任务范围)。

## 5. 其余审查点

- **冻结缺键分级阈值=10 依据**:证据文档 §2.4 —— 9-18 622 大事件(真 P0,冻结键与信号类型漂移)vs 9-21 起每天 1 个重复键(读侧兜底 9-22 已接住)。622 ≫ 10 ≫ 1,分界清晰,**622 量级仍 SEVERE**(n≥10 → --severe + 1h dedup 直发);**小缺口降 WARN 仍可见**(走 send() 默认发 email+telegram,仅不镜像 latest.md,24h dedup 低频)。非彻底消失。✓
- **self_heal 无 --severe 残留**:grep self_heal.sh 确认 `notify_severe(` 无残留 ✓(测试也验证)
- **同类错误面穷尽性(§23.2③)**:独立 grep 全部 53 个 notify.py 调用方。实施方 B/C/D/E 分类逐一核实行号与窗口值全部属实。**唯一遗漏**:intraday_snapshot.sh 有 3 处 1800 dedup(盘中 10min 轮询面,与 with_lock 同类根因),实施方报告未列——但近 7 天 intraday R2 失败噪音低(证据未单列,计划任务异常里 intraday 仅 2 次),30min dedup 已够用,不改合理。属清单完整性小瑕疵,非功能问题。
- **自测可信度**:4 个测试脚本均**从源文件提取真实代码**(worktree 路径与 origin 分支内容 diff 一致,防第二份实现漂移),我全部重跑:**复现抑制 7 例 / dedup 穿透 5 例 / kelly 分级 3 例 / with_lock+self_heal 3 例全部 PASS**。
- **测试碰生产 state 检查**:`data/notify_dedup.json` mtime=9-18、`data/alert_state.json` mtime=9-13(均非今天,测试在 9-24 20:31-36 跑);`data/logs/self_heal_state.json` 本地不存在(生产在云上);测试 monkeypatch DEDUP_FILE 到 /tmp。**未碰生产 state** ✓
- **§23.11 git 冲突 / §24 前端**:diff 无前端文件、无版本串倒退、无静默覆盖;fetch/diff 正常。✓
- **语法**:bash -n × 3(deploy/schedule_monitor/self_heal)+ py_compile × 2(with_lock/signal_kelly_backtest)全部通过 ✓

## 6. 已滤低分项(<80)

2 个低分项已滤:①schedule_monitor 恢复邮件 dedup 全局 key(`schedule_monitor_recovery`)在 6h 内会吞掉其他任务的恢复邮件(恢复=低价值信息,alert_state 已置 recovered,可接受,未进正式 condition);②self_heal 达上限后用户无法从邮件感知今日额度耗尽(机制失效有 launchctl failed 兜底通道,可接受)。

## 7. 复现段

- `/tmp/test_recurrence.py`(源提取,7 例)— 全部 PASS
- `/tmp/test_dedup_penetration.py`(monkeypatch DEDUP_FILE 到 /tmp,5 例)— 全部 PASS
- `/tmp/test_kelly_grade.py`(ast 提取,3 例)— 全部 PASS
- `/tmp/test_wl_sh.py`(ast 提取,3 例)— 全部 PASS
