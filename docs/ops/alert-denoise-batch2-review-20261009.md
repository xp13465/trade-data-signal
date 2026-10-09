# #240 告警降噪第二批 4 条 —— 独立审查报告

**审查者**:reviewer agent(独立于实施,全程只读)
**审查对象**:分支 `worktree-agent-a53be26f39c0827d8`(代码+测试 `821df123f`、报告+索引 `a477d48b8`)
**基线**:merge-base `491bda2d9`(main 自 merge-base 起对本批 6 个改动文件零改动 ⇒ `main...branch` diff 即本次改动全集,可信)
**方式**:`git show <branch>:<path>` 逐字读分支版本(不切分支)+ 本机独立红绿对照 + 云上只读 ssh(systemctl/journal/stats)+ 全仓 grep 抽查;全程零真实外发
**日期**:2026-10-09

---

## 0. 结论摘要

| 条 | 结论 | 说明 |
|---|---|---|
| ① finalizer 误报 | **PASS** | 三重判据+负控充分;同类面独立抽查坐实唯一实现 |
| ② failed unit 每日 1 次 | **PASS(附 F1 需修)** | 主路径(每日 1 次/变化立即报)正确;F1:发送失败仍落签 ⇒ 渠道全失败时当日告警丢失 |
| ③ intraday 碰线连续 2 轮 | **PASS(附 F2 需拍板/修)** | 实现与测试到位;F2:盘中 900-1500s「连续 2 轮」结构性不可达,与声称的判别维度保留不符 |
| ④ 公募全 NULL 分档 | **PASS** | 分档/负控/活跃 key 语义/无前视均核毕 |

**merge 建议**:**先修 F1(必需,小改);F2 由主控拍板**(修 or 接受现状+修订报告 §3 描述)。两条修妥后 merge 最稳。若 F2 选择接受现状,F2 的报告失实描述必须一并修订(不允许保留「第 2 轮起报」的失实声称)。

---

## 1. 逐条审查记录

### ① finalizer 误报(gen_schedule_stats.py)—— PASS

- 三重判据零开口(分支版 L537-583 / 接线 L692):全帧基础设施 (`<string>` / `multiprocessing/`) + ≥2 帧 + 末行规范化 sem_unlink 文案(不带路径);三条负控已逐行读:应用帧 Traceback / 带路径 FileNotFoundError / 单帧 —— 均照报(test_01b);Fix A 锚行形态回归(test_01c)。
- §23.2 同类面独立抽查:`grep -rn "Finalize object|finalizer_noise" scripts/`(非 tests)命中唯一文件 `gen_schedule_stats.py` ⇒ 无第二份拷贝 ✓;schedule_monitor.sh 的 MARKER_ANOMALY_RE 极窄,结构上匹配不到 multiprocessing Traceback ⇒ 无漏面 ✓。
- 判定:**PASS**。

### ② failed unit 每日 1 次(check_failed_units.py + alert_denoise_rules.py)—— PASS(附 F1)

- `--dedup-window 21600→0` 前提核实:`notify.py:1256-1257` `check_dedup` window<=0 恒 False(分支版读码,属实)✓。
- dedup-key `failed_units_patrol` 无其它调用方(全仓 grep:仅 notify.py `_ESCALATE_CHANNELS` 升级链精确匹配 + 测试自传 window)✓;升级链 `check_dedup(_esc_escalated_key, args.dedup_window)` 在 window=0 下同样不 suppress,但脚本侧闸门使升级邮件只随当日首发触发 ⇒ 频率 ≤ 旧(边界:同日集合多次变化+升级日,理论可多发,信息真实,罕见)✓。
- 签名覆盖 problems 全量(failed+watchman+script_missing)⇒ 集合任何变化立即报 ✓;「不清签名防 flap」分析:集合任何变化(增/删/换)→ changed 立即发;唯一抑制窗口=当日已发同集合 ⇒ 不漏新故障 ✓。
- 零外发桩覆盖:`_zero_outbound.py` 只桩 urlopen/SMTP/SMTP_SSL —— 独立 grep notify.py 全部出口:仅 L446/L536/L547 urlopen + L938 SMTP_SSL,无 requests/httpx/http.client ⇒ 桩覆盖面与实查一致 ✓;子进程不继承已在 docstring 自认;test_02c 子进程(dry,无 --notify)零外发由 dry 语义+输出断言兜底 ✓。
- **F1(见 §2)**:落签判据 = notify.py rc,而 rc 不反映渠道成败。
- 判定:**PASS 主路径;F1 需修**。

### ③ intraday 碰线(schedule_monitor.sh)—— PASS(附 F2)

- 阈值零改动(DUR_THRESHOLDS intraday 盘中 900/盘后 1800 原样,test_03b 锚点)+ 桶键带阈值维度(盘中/盘后分离,test_03 末断言)+ ≥2×阈值单轮立即报 + seen 登记防恢复环误清 —— 实现结构完整 ✓。
- red-before-green 独立复现:`git show 491bda2d9:scripts/schedule_monitor.sh > /tmp/pre240_monitor.sh`,`SCHEDULE_MONITOR_SH=/tmp/pre240_monitor.sh` 跑 `-k test_03`:旧版 **2 failed** / 新版 **2 passed** ⇒ 用例锁住新行为,红绿成立 ✓。注:报告 §6 称「2 failed / 1 passed」,独立实测为「2 failed / 0 passed」(数量表述出入,不影响「旧红新绿」结论);且旧版红发生在常量 guard 层(旧版无 DUR_CONTINUOUS_THRESHOLD,测试 _dur_block 断言先失败),非运行断言层触红 —— 结论方向仍成立。
- **F2(见 §2)**:dur=None 轮把 pending 桶静默翻 recovered 的交互,盘中「连续 2 轮」结构不可达。
- 判定:**PASS;F2 待拍板**。

### ④ 公募全 NULL(check_data_gap_alerts.py)—— PASS

- 分档判据「全 NULL 日==今日 且 ≥20:00」=info,其余(非今日/窗口外)severe;severe 文案路径未改 ✓;test_04 五组参数化(今日窗口内→info / 今日+昨日均全 NULL→severe / 仅昨日→severe / 白天手跑→severe / 有值→无)断言与实现一致 ✓;test_04b(active_keys 含 info 防假恢复)✓。
- 无前视:只读 DB 现有行 + 当前时间;「次日复查仍全 NULL → severe」机制 = 次日运行时昨日行非 today 命中 severe 分支(时序自洽)✓。
- info 不落 state(fired_keys≥1 与 active_keys 全量分离)⇒ 不触发 [恢复] 误报 ✓。
- 判定:**PASS**。

---

## 2. 问题清单

### F1【中高,需修】check_failed_units.py 发送失败仍落签 → 渠道全失败时当日告警丢失

- 证据链:`check_failed_units.py` L365-370 `ok, detail = _send_notify(...)` / `if ok: _write_sig_state(...)`(L370);`_send_notify` L225 `return proc.returncode == 0`;notify.py 全部路径 `return 0`(L2171-2372,含 L2362「全部渠道未发出(:... )」仅打印仍退 0),唯一非 0 = 未捕获异常。
- 后果:通知渠道**全失败**(网络/凭据/超时,多渠道路由全挂)时 ok=True ⇒ 落签名状态 ⇒ 当日同集合全部被抑制 ⇒ 当日告警丢失。与脚本自身新注释「发送失败→不落→下轮重试,不吞真故障」(L369 上方)相悖。
- 回归性质:旧行为下 16:00/22:15 有 6h 窗过的重试机会;新行为下当日无补救 ⇒ 新引入的可见性回归(低概率触发,高后果:当天巡检异常不可见)。
- 修复建议(小改,调用侧):`detail` 已含 notify 汇总文本,判 `ok and "已发出" in detail`(或等价汇总判定);修复后同步 test_02b 记录器返回。(不建议改 notify.py rc 契约 —— 影响全部调用方,属冻结面。)

### F2【中,需拍板或修】③ 盘中 900-1500s「连续 2 轮」结构性不可达

- 机制(代码级坐实):dur=None 轮(最新 run 进行中)进不了 dur 块(schedule_monitor.sh L899 `if _dur is not None`),既不 add seen(L922)也不进 else 复位(L971-980)⇒ 主恢复环 pending 分支(L1737-1745)把该桶**静默翻 recovered**;下轮超阈因 status≠pending 从 1 重计(L927-932)⇒ 「连续 2 轮」要求相邻两 tick 均为超阈观测且**中间无 dur=None tick**。
- 数学(云上实测节拍:monitor tick 15min :00/:15/:30/:45;intraday 槽 10min):「两相邻 tick 均观测到已完成超阈 run」的可行条件 = 该 run 时长 D 满足触发相位落在窗口 [5min+D, 20min) 内非空,即 **D < 15min**;阈值恰 = 900s = 15min ⇒ **D ∈ (900s, 1800s) 的盘中 run 数学上凑不出连续 2 观测**。D ≥ 1800s 由 2×阈值单轮兜底、D ≥ 1500s(25min)进行中由 A1 兜底 ⇒ **盘中 900-1500s 区间被完全静默**(旧行为会报,如 10-08 15:02 928s 实例)。
- 影响范围精确界定:intraday **盘中**;盘后 20:35 槽(单 run 完成后续无新 run,长期可见)与全部日频任务(update_all/backfill_evening/us_stock_morning 等完成后长期可见,超阈必达 2 轮)不受影响 —— 报告对这部分结论正确。
- 与报告不符:报告 §3「盘中连续 2 轮 1000s → 第 2 轮起报」在盘中常规节拍下不成立;测试 test_03 的 a3 两连注入未模拟 dur=None 轮与恢复环交互(_dur_tick 直跑 dur 块、不经恢复环),属覆盖盲区。
- 建议:①修(推荐,小改):主恢复环豁免含 `|dur_buffer|` 的键(计数全权由 dur 块自管)+ 桶记 last_run(同一 run 重复观测不增计数;不同 run 连续超阈递增)⇒ 「相邻两 run 各超阈」可达、单 run 偶发仍不报;②或主控拍板接受现状(盘中 900-1500s 静默),但**必须修订报告 §3 的失实描述**并在 #240 文档披露该缺口。

### F3【低】报告/注释三处不一致

- F3a:`check_failed_units.py` L51 docstring 仍写 `--dedup-window 21600`(代码已 0,过时文档)。
- F3b:报告 §6 红绿「2 failed / 1 passed」与独立实测「2 failed / 0 passed」不符(方向结论不受影响)。
- F3c:报告 §8 复现命令 `git show HEAD:scripts/schedule_monitor.sh` 在改动 commit 之后重跑会指向**含改动**的版本(应写 `git show 491bda2d9:` 或注明须在 commit 前执行)。

### F4【低】② 同类面清单不完备(§23.3)

- 独立 grep `21600` 全仓:除报告所列(brief_push_wrapper/check_r2_consistency/cloud_unit_patrol/deploy)外,还有 `upload_r2.py`(L1761/3669/3699 `notify.check_dedup(_dk, 21600)` 直调)、`with_lock.py` L128、`staticdata_sync.sh`(L158-249 五处)、`staticdata_backup_async.sh` L128。
- 抽查结论:这些为「事件驱动+防重试轰炸」形态(staticdata_sync 由生成器调用、upload_r2 随上传触发)⇒「不需同款改造」的方向结论未变;但清单应补全并逐项给形态判定理由。

---

## 3. 其它核查(已过)

- 新 alert_state 键 `<task>|dur_buffer|<thresh>`:与既有消费方兼容 —— `alert_ack.py` 只加 `acknowledged` 字段不动 status;`monitor_72h.sh` 恢复环只处理 `72h_` 前缀(L800);`marker_buffer` 桶同构先例(pending/alerted/recovered 全谱)⇒ 无键冲突/污染。
- 云上节拍实测:trade-schedule-monitor 15min;trade-intraday 10min 槽 + 11:32/13:01 特例;今日 11:32 槽 run=251s(正常)。DUR_THRESHOLDS 全清单任务名无 `r2_`/`72h_` 前缀 ⇒ 无前缀豁免干扰。
- 零外发:审查全程未触发真实外发(只读 ssh + 本机 pytest ③ 用例纯 ast 块 + 云上只读 systemctl/journal/stats 读取)。
- 未独立复跑全量测试套件(实施声称 428 passed 2 skipped);独立复核了 ③ 用例红绿 + ①②④ 用例与实现逐行对读。

## 4. smoke 适配性与上线后观察项

- 本批 6 文件全在 `scripts/`(后端监控脚本),不触数据产物/前端/static-site/R2 ⇒ `docs/smoke-checklist.md` C1-C30 无直接适用项;唯一间接关联 C21/C22(`schedule_stats.json` 的生成脚本 ① 被改)—— ①只影响 anomaly 标记,不动 last_exit/len 字段,校验语义不变。
- merge 后观察项(盘后首轮任务后):
  1. 云上 `static-site/data/schedule_stats.json` C21/C22 校验照常(9 项 / last_exit 非 143/133/1);
  2. 下一个交易日 monitor 无 `[finalizer-noise]` 误报,且真 Traceback 照报;
  3. 20:35 intraday 槽后若收 [告警] 云上 unit 巡检,确认同日不重复(验证 ② 生产行为)。
- alert_state.json 位于云上 REPO/data/(untracked),不入 git ✓;`data/failed_units_patrol_sig.json` 同理 ✓。

## 5. 规范判定(独立)

- §21 公示:**不适用**(未动 track_score/评分/权重/匹配等用户可见算法;告警监控口径不在公示范围)。
- §22 一致性:**不适用**(无用户展示位数据产物变化;alert_state 为内部状态,非多展示位源)。
- §24 防撕裂:**不适用**(零前端源/零 min/SW/版本串);未 bump 版本串正确。
- §23.2/§23.3:①✓(唯一实现抽查坐实);②清单不完备(见 F4);③全任务生效已披露 ✓;④对齐 ETF nav 先例 ✓。
- §23.7 冻结:4 条均在 #240 点名范围,无越界 ✓。

## 6. 置信度过滤说明

- 已滤(<80)1 项:云上 dashboard 等对 alert_state 新键的渲染兼容性未逐处验证(置信 ~60;marker_buffer 同构先例覆盖 ⇒ 不影响结论)。
- 正文不含 <80 项。

## 7. 复现命令(本次审查)

```bash
# 红绿对照(本机,不动仓库)
git show 491bda2d9:scripts/schedule_monitor.sh > /tmp/pre240_monitor.sh
PY=/Users/linhuichen/code/trade-data/.venv/bin/python
WT=/Users/linhuichen/code/trade/.claude/worktrees/agent-a53be26f39c0827d8
PYTHONDONTWRITEBYTECODE=1 $PY -m pytest -p no:cacheprovider $WT/scripts/tests/test_240_alert_denoise_batch2_20261009.py -k test_03 -q
#   → 新版 2 passed
SCHEDULE_MONITOR_SH=/tmp/pre240_monitor.sh PYTHONDONTWRITEBYTECODE=1 $PY -m pytest -p no:cacheprovider $WT/scripts/tests/test_240_alert_denoise_batch2_20261009.py -k test_03 -q
#   → 旧版(merge-base)2 failed
# 云上只读节拍核实
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 "systemctl list-timers 'trade-*' --no-pager; systemctl cat trade-schedule-monitor.service"
```

**报告落档**:本文件(主控统一收;审查者未 commit、未 push、未切分支)。
