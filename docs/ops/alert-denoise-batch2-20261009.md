# 告警降噪第二批 4 条(#240)实施报告 —— 2026-10-09

**任务**:#240 告警降噪第二批候选 4 条(权威口径 `docs/ops/alert-triage-1008-20261008.md`,10-08 外发 19 条 = 9 个独立根因,其中 5 条 ≈26% 纯可降噪)。
**铁律**:只降噪、不降灵敏度;每条保留真故障判别维度;降噪前 vs 降噪后同一真实样本必须给判定对照。
**分支**:`worktree-agent-a53be26f39c0827d8`(worktree 隔离);**未 push main**(agent 只提交 feat)。

---

## 0. 自测零外发证据(必读首段,§18 L48)

**本次全部自测(17 个 pytest 用例 + `check_data_gap_alerts.py --self-test`)未产生任何真实外发**(邮件/飞书/R2 写全零)。三条硬证据:

1. **pytest 全程挂 `ZeroOutboundTrap`**:`scripts/tests/_zero_outbound.py` 对 `urllib.request.urlopen` / `smtplib.SMTP` / `smtplib.SMTP_SSL` 打桩计数 + 命中即 raise;`test_240_*` 中凡走到 notify 出口的用例(② 的 `test_02b`/`test_02c`)均在该 trap 上下文内,且 `test_02b` 另 monkeypatch `check_failed_units._send_notify` 为纯记录器。跑完计数必须为 0,非 0 即 FAIL。
2. **`--self-test` 自身就是打桩形态**(读码确认,非推断):case A4 在临时目录写 `base/scripts/notify.py = "import sys; sys.exit(0)"` 桩,子进程调用命中的是桩文件(`check_data_gap_alerts.py:2087-2090`);case A5 直接 `globals()["_notify"] = _spy_notify` 替换函数(`:2110-2116`),`finally` 还原。⇒ `dry_run=False` 的调用点全部指向桩,不通真链路。
3. **网络侧零请求**:本报告涉及的云端取证只用 `ssh ... "timeout N <cmd>"` 跑 `systemctl`/`journalctl`/`grep` 只读命令;无 curl 外发、无 R2 上传、无 `notify.py` 真实调用。

---

## 1. 候选① finalizer 误报(monitor 关键词加同款过滤)

**改动**:`scripts/gen_schedule_stats.py`
- `L537-545` 新增 `MP_INFRA_FRAME_RE` / `MP_SEMUNLINK_ERR_RE` / `_is_mp_infra_frame()`
- `L547-583` 新增 `_mp_infra_traceback_ranges(lines, lo, hi)`
- `L692` 接入:`finalizer_ranges += _mp_infra_traceback_ranges(lines, last_start_idx, end_idx)`(紧接既有 `_finalizer_noise_ranges` L689)

**根因**(在真实 10-08 云上样本核实):`backfill_evening` 窗口内那条 multiprocessing 清理噪音是**无锚行**形态 —— `Traceback` 帧全为基础设施帧(`<string>` → `spawn.py` → `spawn.py` → `synchronize.py __setstate__`),末行 `FileNotFoundError: [Errno 2] No such file or directory`(**不带路径**);既有 Fix A(`L473 _finalizer_noise_ranges`)锚在 `Exception ignored in: <Finalize object, dead>` 行上,这条没有锚行 ⇒ 漏过。
新判定 = **全部帧均为基础设施帧**(`<string>` 或路径含 `multiprocessing/`)+ **≥2 帧** + **末行是规范化的 sem_unlink 文案**,三个条件同时成立才过滤。

**降噪前 → 降噪后(同一真实样本)**:

| 样本 | 改前 | 改后 |
|---|---|---|
| 10-08 `backfill_evening` 无锚 multiprocessing Traceback(真实日志) | 命中 `Traceback (most recent call last)` ⇒ 计入异常 → 报警 | `scan_log_anomaly()` 返回 `(None, 0)`,打印 `[finalizer-noise] ... 属于 multiprocessing 清理噪音`,不报警 |

**真故障负控(降噪后仍报)**:
- 应用帧 Traceback(帧路径是业务 `.py`)⇒ 照报
- 基础设施帧但末行**带路径**的 `FileNotFoundError`(如 `/data/xxx.json`)⇒ 照报
- **单帧** Traceback(不足 2 帧)⇒ 照报
- Fix A 锚行形态(`Exception ignored in: `<Finalize object, dead>` + 后续 Traceback)⇒ 仍走老路径过滤(回归不变)

**同类错误面清单(§23.2 排查同类)**:全仓 `grep -rn "finalizer-noise\|Finalize object, dead" scripts/` 命中**唯一一处** = `gen_schedule_stats.py`(L291/L294/L297/L477/L485/L534/L700),**无第二份拷贝** ⇒ 不同步问题不存在。另一条扫描器 `schedule_monitor.sh` 的 `scan_marker_log()` 用**极窄**的 `MARKER_ANOMALY_RE`(只匹配 ⚠ fetch_news/R2 标记),结构上匹配不到 multiprocessing Traceback ⇒ **无同类漏面**,不动。

---

## 2. 候选② failed unit 每 6h 重报 → 每日 1 次 / 变化立即报

**改动**:
- `scripts/alert_denoise_rules.py`:`L90-91` 常量 `FAILED_UNITS_SIG_STATE_FILENAME="failed_units_patrol_sig.json"` / `FAILED_UNITS_SIG_LEN=12`;`L94` `failed_units_signature(problems)`(排序后 md5 前 12 位,空集返回 "");`L106` `failed_units_daily_judge(state, signature, today_str) -> (send, reason)`,reason ∈ {empty / changed / daily-first / same-set-same-day}(纯函数,可单测)
- `scripts/check_failed_units.py`:`L186/L195` 新增 `_read_sig_state` / `_write_sig_state`(tmp+replace 原子写);`L213-222` `_send_notify` 的 `--dedup-window` **21600 → 0**(`--dedup-key` 保持 `failed_units_patrol` 不变,见下);`L346-348` main 内取签名 + 判定;`L370` **仅真发成功**才写状态

**关键取舍(为什么 dedup-window 归零)**:6h 窗口会**吞掉**「集合变化 → 立即报」的告警(变化发生在窗内就被 notify.py 抑制)。改为 0 后,窗口语义交给脚本自管,notify.py 侧 `check_dedup(key, window<=0)` 恒返回 False(`scripts/notify.py:1256-1257`,已读码确认)。`--dedup-key` 保持原值,是为了让 `notify.py:2306-2313` 的 `_ESCALATE_CHANNELS`(#196③ 严重档升级链)仍能按 key 命中 —— 该升级块在通用 dedup **之前**执行并 early return,故升级邮件仍走原通道;而脚本侧闸门已保证最多 1 次/天,升级邮件频率**只降不升**。

**为什么集合空时不清签名**:清签会引入 flap(unit 时有时无 → 每次都算 changed 又变成轰炸);保留签名后,**真有新 unit 加入**依然命中 `changed` 立即报。

**降噪前 → 降噪后(同一真实样本,09:45/16:00/22:15 三连)**:

| 轮次 | 请求(unit 集合) | 改前 | 改后 |
|---|---|---|---|
| 09:45 | {A,B} | 发邮件 | 发(reason=`daily-first`),落签 |
| 16:00 | {A,B}(相同) | **重发**(6h 窗已过) | **不发**(reason=`same-set-same-day`) |
| 22:15 | {A,B}(相同) | **重发** | **不发** |
| 次日 09:45 | {A,B}(相同) | 重发 | 发(新的一天 → `daily-first`) |
| 任意时刻 | {A,B,C}(新增 C) | 发 | **发**(reason=`changed`)✅ 灵敏度保留 |

**真故障负控**:集合新增/替换成员 → 立即发;集合非空且跨日 → 每日首轮发;`problems` 为空 → 走既有 early-return 不变(空集合报「全正常」的原逻辑不动)。

**同类错误面清单(§23.2)**:`grep -rn "21600" scripts/` 找出其余 6h 窗调用方 = `brief_push_wrapper.sh`(事件驱动,一次性)、`check_r2_consistency.sh` / `cloud_unit_patrol.sh`(各自已有独立升级链)、`deploy.sh` 闸门(一次性)。**逐个核对:均非「同一状态每 6h 定时重报」形态** ⇒ 不需要同款改造,如实披露不改。

---

## 3. 候选③ intraday 碰线(928s vs 900s,仅超 3%)→ 连续轮次判定

**改动**:`scripts/schedule_monitor.sh`
- `L586-587` 新增 `DUR_CONTINUOUS_THRESHOLD = 2` / `DUR_IMMEDIATE_MULTIPLE = 2`(**阈值本身一个没动**:intraday 盘中 900s、盘后 1800s 原样保留)
- `L919-948` dur 块内新增「pending → active」连续轮次桶,键 `f"{task}|dur_buffer|{thresh}"`(**带阈值维度** ⇒ 盘中 900 槽与盘后 1800 槽计数互不串用);`L925-926` `dur >= 2×阈值` ⇒ 单轮即视同达连续阈值(立即 SEVERE);`L944-948` 未达阈值只打印 `连续 N/2 轮, 暂不通知`
- `L971` 外层(`dur <= 阈值`)新增归零分支:`status: "recovered", consecutive_count: 0`
- 桶键 `seen_keys_this_run.add(...)` 必须登记(#232 修复的同款约束),否则主恢复环(L1682-1735)每轮会把 pending 桶当"已恢复"清掉、计数永远到不了 2

**数据支撑**:盘中 387 轮实测 p95=796s / p99=935s / max=1398s(**全部 exit=0** ⇒ 单轮碰线是常态抖动);盘后 20:35 轮实测 4045s(09-29)/ 2081s(09-30)。

**降噪前 → 降噪后(同一真实样本)**:

| 样本 | 改前 | 改后 |
|---|---|---|
| 盘中 928s(单轮,超 900 阈 3%) | SEVERE 告警 + 次轮 15min 后 `[恢复]` = **2 条外发** | `pending`,只打印不通知 = **0 条外发** |
| 盘中 334s(回落) | 无告警 | 桶置 `recovered`,计数 0 |
| 盘中连续 2 轮 1000s | 2 条 SEVERE | **SEVERE**(第 2 轮起报,真持续劣化保留) |
| 盘中单轮 1900s(≥2×900) | SEVERE | **立即 SEVERE**(不等待第 2 轮) |
| 盘后 2081s(09-30,同一 last_run 被多轮看到) | SEVERE | **SEVERE**(第 2 轮即报,每日 1 run 但桶跨轮保留) |

**真故障负控**:持续超阈(连续 2 轮)照报;极端超阈(≥2×)单轮即报;阈值未下调任何一档 ⇒ 灵敏度零损失。A1「in-progress 超时」通道(900s + 10min buffer)作为挂死类独立通道**原样保留**,不受本次影响。

**适用范围(§23.3)**:改动落在 **通用 dur 块**内 ⇒ 生效对象 = `DUR_THRESHOLDS` 中的**全部任务**(不只 intraday)。这是有意为之:同形态抖动其他任务同样存在。

---

## 4. 候选④ 公募全 NULL 时滞判 severe → 分档

**改动**:`scripts/check_data_gap_alerts.py`
- `L710` 新增 `FUND_NAV_PUBLISH_WINDOW_HOUR = 20`
- `L795-856` `check_fund_nav_allnull` 重构:遍历行时 **至多产出一个 Finding**
  - 全 NULL 日 == 今日 **且** 当前小时 ≥ 20(净值发布窗口内)⇒ **info**,标题 `公募基金 {d} 采集全 NULL(首日净值时滞, 次日复查)`(`:852-854`)
  - 其余任何全 NULL 日(含今日白天手工跑)⇒ **severe**,消息文案**一字未改**
  - `break` 语义保留「只告警最近一日」

**为什么 info 档不会造成「漏报 + 假恢复」**:`run_alerts` 的 `fired_keys`(level≥1)与 `active_keys`(任意 level,含 info)**分开**;info 档仍进 `active_keys` ⇒ 该 key 保持活跃,**不会**触发 `[恢复]` 误报,只是 `sev < 1` 走 log-only(`[info 只记日志]`)。

**降噪前 → 降噪后(同一真实样本,24218 行全 NULL)**:

| 场景 | 改前 | 改后 |
|---|---|---|
| 10-08 20:35 采集全 NULL(净值尚未发布) | **severe** 邮件 | **info**:只记日志,零外发;key 保持活跃 |
| 10-09 复查仍全 NULL(次日仍未补齐) | severe | **severe**(时滞已持续 ⇒ 真故障保留) |
| 10-08 白天 14:00 手工跑发现全 NULL | severe | **severe**(白天不该全 NULL,保留 fail-loud) |
| 任意日历史某天全 NULL(非今日) | severe | **severe**(文案不变) |

**判据(§ 铁律「保留真故障判别维度」)**:判别维度 = 「**是不是今日 + 是不是在净值发布窗口内**」;窗口外 / 非今日 = 真缺失 ⇒ 一律 severe。

---

## 5. 举一反三清单(§23.3)

| 面 | 结论 |
|---|---|
| ① 同模式(别的扫描器要不要同款过滤) | `scan_marker_log()` 的窄正则结构上匹配不到 multiprocessing Traceback ⇒ 无漏面;finalizer 过滤全仓只有 1 处实现 |
| ② 同模式(6h 窗「状态不变重复报」) | 6 个 21600 调用方逐个核对,均非该形态 ⇒ 不同批改造,已披露 |
| ③ 同数据源(DUR_THRESHOLDS) | 全部任务生效(设计如此,非遗漏) |
| ④ 同组件(其他 severe 无 grace 的检查器) | ETF nav 时滞早已走 info(本次对齐先例);`check_fund_nav_allnull` 是公募侧唯一对标项 |
| 展示位(R2/前端/static-site) | 无:4 条全为后端监控脚本,**不改任何数据产物/前端/JSON 字段** ⇒ §22 一致性 / §24 防撕裂 / 版本串 bump **均不适用** |
| §21 算法公示 | **不适用**:未动 track_score / 评分 / 权重 / 分位 / 匹配规则等任何用户可见算法,改的是告警监控口径 ⇒ 前端公示文案无需同步 |
| §23.1 README | **不适用**:未引用任何外部开源项目/库,无站点新功能发布 |
| §23.7 版本功能冻结(顺手优化老功能) | 本次 4 条**全部**是 #240 派单点名范围,无越界「顺手优化」 |

---

## 6. 自验结果(命令 + 结论)

| 命令 | 结果 |
|---|---|
| `bash -n scripts/schedule_monitor.sh` | OK(退出码 0) |
| `ast.parse` 5 个改动脚本 + 新测试文件 | OK |
| `pytest scripts/tests/test_240_alert_denoise_batch2_20261009.py` | **17 passed**(含零外发 ZeroOutboundTrap 断言 + `_MIN_ASSERTIONS=40` 断言数兜底) |
| ③ red-before-green(`/tmp/pre240_monitor.sh` = `git show HEAD:scripts/schedule_monitor.sh`) | 用旧版跑新用例 = **2 failed / 1 passed** ⇒ 证明新用例确实锁住了新行为(不是空转绿) |
| 相关既有 8 个测试套 | **165 passed, 1 skipped** |
| `pytest scripts/tests/`(全量) | **428 passed, 2 skipped in 87.81s** |
| `python3 scripts/check_data_gap_alerts.py --self-test` | PASS(且经读码确认全程打桩,零外发) |

自测窗口说明(memory `selftest-window-two-x-period`):③ 的连续轮次判定用**逐轮注入 `_dur_tick()`** 直接跑多轮状态机(不依赖真实 15min 墙钟),等价于覆盖 ≥2 倍机制周期;② 的「跨日」用注入 `today_str` 覆盖,不受墙钟约束。

---

## 7. 未做项及原因

1. **未在本机跑 `schedule_monitor.sh` 生产入口做端到端实跑**:该脚本会走真实 notify 链路(main 侧的 `send` 分支),按 L48 打桩铁律**不该在无沙箱时跑**;改用 ast 抽取真实代码块 + 注入命名空间单测(与 #232/#181/#228 同款先例,避免第二份实现漂移)。
2. **未改 `notify.py`**:4 条全部在调用侧解决,`notify.py` 未动 min 影响面。
3. **未改其余 6h 窗调用方**(见 §2 同类面):证据显示非同形态,不属本次范围,已披露待评估。
4. **未 push / 未 merge main**:按派单纪律 agent 只 commit feat 分支。
5. **未 bump 版本串 / 未 build_min / 未 deploy**:无前端与数据产物改动(见 §5)。

---

## 8. 复现段(怎么重跑这批自验)

```bash
cd /Users/linhuichen/code/trade/.claude/worktrees/agent-a53be26f39c0827d8
PY=/Users/linhuichen/code/trade-data/.venv/bin/python   # 本机 python3 无 pytest
bash -n scripts/schedule_monitor.sh
$PY -m pytest scripts/tests/test_240_alert_denoise_batch2_20261009.py -q
$PY -m pytest scripts/tests/ -q
$PY scripts/check_data_gap_alerts.py --self-test
```

③ red-before-green 复现:`git show HEAD:scripts/schedule_monitor.sh > /tmp/pre240_monitor.sh`,再把测试里的监控源路径指向该文件跑同一用例(预期 2 failed / 1 passed)。

**生成脚本 / 复现说明**:本报告无独立生成脚本 —— 数据来源全部是①实跑命令输出 ②云上只读 `journalctl`/日志取样的既有事实(详见 `docs/ops/alert-triage-1008-20261008.md`)。测试用例本身即复现脚本(`scripts/tests/test_240_alert_denoise_batch2_20261009.py`,17 用例覆盖 4 条候选的正控 + 负控)。

**配套 commit**:代码 + 测试 = `821df123f`(feat 分支 `worktree-agent-a53be26f39c0827d8`);本报告 + 索引 #240 状态刷新 = 同批第二个 commit。**两笔均未 push main**(agent 只提交 feat)。

---

## 9. 影响面 / 一致性核对

- 改动文件 5 个 + 新增测试 1 个,**全部在 `scripts/` 下**(后端监控脚本),**零前端 / 零数据产物 / 零 R2 / 零 static-site** ⇒ §22 数据一致性、§24 防撕裂、§21 算法公示 三条**均不适用**(理由见 §5)。
- 新增运行期状态文件:`data/failed_units_patrol_sig.json`(仅本机/云端 `data/` 下,untracked,不进 git)。
- 新增 alert_state 键:`<task>|dur_buffer|<thresh>`(沿用 `data/alert_state.json`)。