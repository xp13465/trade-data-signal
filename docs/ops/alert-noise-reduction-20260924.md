# 告警降噪 5 条实施报告(2026-09-24)

> 前置:用户拍板「五条全上(P0+P1+P2)」,证据见 `docs/ops/alert-noise-evidence-20260924.md`(近 7 天约 148 封告警邮件,2/3 是已自愈事件被轮询重复轰炸)。
> 硬约束执行:§14 只从去重/聚合/减 payload 下手,不降频/不暂停/不关任务;每条改动均验证「真问题时它还会响」。§23.7 只改授权 5 条,授权外同类面逐一列出处置,不自行改。

## 改动总览(5 条 = 5 个文件 8 处)

| 级别 | 文件:行号 | 改动 | 前 → 后 |
|---|---|---|---|
| P0 | scripts/deploy.sh:1071 | board_etf_map 旧版兜底 dedup | `--dedup-window 3600` → `21600`(key `board_etf_map_stale` 不变) |
| P1 | scripts/deploy.sh:1059 | deploy R2 上传失败 dedup | `--dedup-window 1800` → `21600`(key `deploy_r2_upload_fail` 不变;verify-channels 真缺口保留直发) |
| P1 | scripts/schedule_monitor.sh:236 | RECOVERY_COOLDOWN | `timedelta(minutes=30)` → `timedelta(hours=6)`(同时充当恢复邮件静默窗 + 复现抑制窗) |
| P1 | scripts/schedule_monitor.sh:251 | 新增 `_recurrence_suppressed()` | 退出失败 + log_anomaly 两分支改三分支:恢复后<6h 复现 → 抑制 SEVERE;active/None/超窗 → 原逻辑 |
| P1 | scripts/schedule_monitor.sh:1974 | 恢复邮件加 6h dedup | 新增 `--dedup-key schedule_monitor_recovery --dedup-window 21600`(恢复汇总一次性发) |
| P1 | scripts/signal_kelly_backtest.py:312/334-344 | 冻结缺键分级 | 新增 `FROZEN_MISSING_SEVERE_THRESHOLD=10`;n≥10 SEVERE+1h dedup / n<10 WARN+24h dedup |
| P2 | scripts/with_lock.py:112 | 排队超时跳过告警 dedup | `--dedup-window 1800` → `21600`(key `with_lock_block_timeout:{lockpath}` 不变,保持 --severe) |
| P2 | scripts/self_heal.sh:148-162/185/239 | 达每日上限告警降级 | `notify_severe` → `notify_limit_info`(`--severe` 全套 → `--tier info` 只落盘) |

## 逐条自测证据(每条「真问题时它还会响」)

### ① P0/P1 两类 deploy dedup 6h → 真缺口仍穿透
`/tmp/test_dedup_penetration.py`:monkeypatch `notify.DEDUP_FILE` 到 /tmp 假文件(不碰生产),跑 `check_dedup`/`update_dedup` 5 场景全部 PASS:
- 无记录首次直发 `check_dedup=False`(立即发,不静默)
- 3h 前已发(6h 窗内) `check_dedup=True`(suppress 轰炸)
- 10h 前已发(超窗真缺口) `check_dedup=False`(穿透,真问题仍会响)
- 整 6h 边界 `check_dedup=False`(边界放行)
- `update_dedup` 发送成功才写入

上下文佐证:deploy.sh L1043-1061 注释+代码确认 R2 失败告警**仅 verify-channels rc!=0(确认真缺口)才走到**;L1065-1072 board_etf_map 告警**仅 MAP_STALE=1(build 失败+旧版兜底)才走到**。6h 内同失败面首次直发、不重复轰炸,真缺口不静默。

### ② P1 计划任务异常 recovered 复现抑制 → 真卡死不吞、振荡不轰炸
`/tmp/test_recurrence.py`:从 schedule_monitor.sh **源文件直接提取** `_recurrence_suppressed` 真实代码(防第二份实现漂移),7 场景全部 PASS:
- `None`(首次发现) → 放行发 SEVERE
- `active`(持续异常) → 放行走既有 suppress 分支(首次已发,不重发)
- `recovered` 3h 前(6h 窗内振荡) → 抑制 SEVERE(9-18 一天 13 封根因)
- `recovered` 6h 整前(边界) → 放行(边界=真复发仍响)
- `recovered` 10h 前(超窗真复发) → 放行发 SEVERE(真卡死不吞)
- `recovered` 无 last_recovered(pending) → 放行
- `last_recovered` 格式坏 → 放行(fail-open 安全侧)

上下文佐证:schedule_monitor.sh L1908-1935 SEVERE 发送块**依赖 alert_state status=active 去重(无 notify dedup),首次异常直发不静默**;L1936+ 恢复邮件 r2_ 前缀按 2026-09-22 既有规则抑制,非 r2_ 恢复走 6h dedup 汇总。

### ③ P1 冻结缺键分级 → 小缺口 WARN 低频、大事件 SEVERE 直发
`/tmp/test_kelly_grade.py`:ast 提取 `_alert_frozen_missing` 真实函数 + monkeypatch subprocess 抓 cmd,3 场景全部 PASS:
- n=1(每天 1 个重复键,读侧兜底 9-22 已接住) → 无 `--severe` + `dedup-key=signal_kelly_frozen_missing_small` + `window=86400`(WARN 语义 24h 低频)
- n=11(622 量级批量历史暴露) → `--severe` + `dedup-key=signal_kelly_frozen_missing` + `window=3600`(真 P0 直发)
- n=10(边界) → `--severe`(≥10 判定正确)

阈值依据:9-18 622 大事件(冻结键与信号类型漂移,真 P0)vs 9-21 起每天 1 个重复键(读侧兜底已接住)的分界,取 10。

### ④ P2 with_lock 排队超时 → 仍 SEVERE 直发,6h 同锁面不轰炸
`/tmp/test_wl_sh.py`:ast 提取 `_notify_block_timeout` 真实函数验证 cmd 含 `--severe` + `--dedup-key with_lock_block_timeout:<lockpath>` + `--dedup-window 21600` PASS。
语义:排队超时=锁竞争瞬时已自愈(8 封/周噪音),保持 --severe(任务被跳过需补跑提示),首封立即发;真锁死(排队任务互相饿死)由 schedule_monitor exit/产物时效/进行中超时通道兜底,不掩盖。

### ⑤ P2 self_heal 达上限 → 记 info 只落盘,机制失效另有通道兜底
`/tmp/test_wl_sh.py`:提取 `notify_limit_info` 验证 cmd 含 `--tier info`、无 `--severe/--alert-issue/--alert-log` PASS;grep 确认 self_heal.sh 已无 `notify_severe` 残留。
语义:额度用光=自愈机制正常工作的信号(次日自动重置),非故障;真自愈机制失效由 schedule_monitor 的 launchctl failed 通道(不在 schedule_stats TASKS → 降级 SEVERE 直发)兜底,与任务 exit!=0 通道互不掩盖。

## 同类错误面清单(§23.2③ 逐个处置)

grep 全部 notify.py 调用点(~50 文件,含测试/桥接脚本),按「重复轰炸」同类根因分类:

### A. 授权 5 条直接改动(8 处,已改)——见上表

### B. 同「30min dedup 窗口」模式但根因不同(单次任务失败告警,非轮询已自愈轰炸)——不改
| 调用点 | 现状 | 为什么不改 |
|---|---|---|
| scripts/run_daily_brief.sh:52 `daily_brief_fail` 1800 | 每天 20:40 单次运行 | 无 15min 轮询面,30min 窗口已足够,拉长无增益 |
| scripts/update_all.sh:335 `update_all_severe:${ISSUE}` 1800 | 按 ISSUE 分 key | update_all 有限次运行,同 ISSUE 30min 防重复;不同 ISSUE key 隔离 |
| scripts/update_lab.sh:303/320/338 三个 R2 fail 1800 | 盘后单次运行内防抖 | 同根因=单次任务失败,非监控轮询已自愈;key 已按失败面分 |
| scripts/push_schedule_stats.sh:74 `schedule_stats_r2_fail` 1800 | 同上 | 同上 |

### C. 已有 ≥1h dedup(3600/86400)已防轰炸——不改
nextday_gap_check.py:71(3600)/372(86400)、turnover_backfill.sh:162(3600)、nextday_plan_generator.py:113(3600)/1157(86400)、overfit_monitor.py:1428(86400)、gold_night.sh:47/77(3600)、s06_snapshot.sh:144(3600)、fund_nav_upload_async.sh:46(3600)。

### D. 真 severe 直发(低频/单点故障,§14 不静默)——保留,不改
backup_db.sh:101/124、check_data_gap_alerts.py、detect_intraday_anomaly.py、monitor_72h.sh:838、intraday_snapshot.sh 失败通道、schedule_monitor.sh:1923 SEVERE 块(首次异常直发,alert_state 去重)、signal_kelly_backtest.py:336(大事件 1h dedup)。
这些要么低频单点,要么是首次异常直发通道——拉长 dedup 会推迟真故障通知,违反「真 severe 不静默」。

### E. 研究档覆写(已验证不受分级影响)——不改
scripts/hold_days_sweep.py:55 monkeypatch `skb._alert_frozen_missing = lambda...` 只打印不 notify,研究档自动绕过告警通道,分级改动不影响。

## §23.7 冻结契约:未做/上报项
- **授权外未自行改**:B 类 6 处 30min dedup 窗口调用点未拉长(理由见上,均为单次任务失败告警,非授权 5 条同类根因)。
- **无新发现历史遗留需上报**:改动过程中未发现授权 5 条之外的老功能 bug;schedule_monitor 恢复邮件 r2_ 前缀抑制为 2026-09-22 既有行为,非本次新发现。
- 未碰前端(app.js/lab.js/style.css/公示文案)——本任务纯后端告警链路,无算法/口径公示联动。

## 复现段
- `/tmp/test_recurrence.py`:schedule_monitor 复现抑制 7 场景(源文件提取真实函数)
- `/tmp/test_dedup_penetration.py`:notify dedup 穿透 5 场景(monkeypatch DEDUP_FILE 到 /tmp)
- `/tmp/test_kelly_grade.py`:冻结缺键分级 3 场景(ast 提取 + monkeypatch subprocess)
- `/tmp/test_wl_sh.py`:with_lock + self_heal 参数 3 场景
- 语法:bash -n ×3 + py_compile ×3 全部通过

## 上线注意
- agent 只 push feat 分支(`worktree-agent-a2f56d09bf34000ff`),merge+push main 由主控 `scripts/main-merge.sh` 统一执行。
- 上生产后建议观察:计划任务异常邮件量(预期 57 封/周 → ~0,仅真卡死/超窗复发直发)、deploy 相关 23 封 → 仅真缺口、冻结缺键 12 封 → 小缺口降 24h WARN。
