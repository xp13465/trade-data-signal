# #241 同族 B 波:「先落签、后 fire-and-forget 通知」→ 真告警永久丢失 —— 穷举 + 统一修(2026-10-09)

> 基线: `origin/main` @ `4325a27d5`(已含 A 波 `4c9b41efb` + 复审报告销账)
> 适用范围: `scripts/` 全部 notify 调用方 + shell 侧 notify 门控(全仓交叉扫)
> 独立复审输入: `docs/ops/241-family-rc-sent-sweep-review-20261009.md`(§2 FAIL 详证 = 本波反例来源)
> 前置 A 波: `docs/ops/241-family-rc-sent-sweep-20261009.md`(3 处「rc 判 sent」已修)

---

## 0. 病灶定义(A 波 = rc 判 sent;B 波 = 落签后 fire-and-forget)

A 波修的是「**用 `returncode` 判** notify 是否真发出」——`notify.py main()` 所有出口恒 `return 0`,
故全渠道失败也判「成功」⇒ 落签 ⇒ 抑制重试。

本波修的是**同后果、不同机制**:「**先落签(记『已告警』)、后 fire-and-forget 通知**」——
状态(alert_state / dedup / fired / notified)**先落盘**, 通知那步 `check=False` 连返回值都丢。
通道全挂时:①告警没送出 ②state 已落签 ⇒ **条件持续期间每轮命抑制、永不重发 = 永久失报**。

复审报告 §2 已证明:先前「穷举」用「含 notify 且含 returncode」为口径,**结构性漏掉**了
「不出现 rc 字样、但照样落签后 fire-and-forget」的站点。本波改用**后果口径**重扫。

---

## 1. 穷举清单(核心验收点)

口径三条:**① 全 `scripts/` + `app/` 的 notify 调用方逐个读;② 每处问「通知前是否已写状态」;
③ 再问「该状态是否在下一轮抑制重发」**。三类结论:

### 1.1 本波修复(5 站点)

| # | 站点 | 病灶(修前) | 后果 | 修法 |
|---|---|---|---|---|
| B1 | `scripts/schedule_monitor.sh` | 收尾聚合 `save_alert_state(alert_state)`(轮内检查点 + L2757)先于 `subprocess.run([...notify.py...], check=False)`(**15min 全局巡检中枢**) | 通道全挂 ⇒ 当晚「计划任务异常」邮件+飞书丢失, 且 `status=active` 已落 ⇒ 条件持续期每轮命抑制、永不重发(**后果最重**: 承载漏跑/exit失败/数据错/停摆全部告警类) | 主 notify 改 `capture_output` 判 `notify_sent`; 未送达 ⇒ 用轮首快照 diff **回滚本轮新落 active 的 key** 再 save |
| B2 | `scripts/monitor_72h.sh` | 同款: `save_alert_state`(L824)先于主 notify(L837, `check=False`) | 同 B1(72h 期覆盖 采集/R2/发布/稳定性/及时性 5 类) | 同 B1 |
| B3 | `scripts/detect_intraday_anomaly.py` | `filter_and_record` 先 `atomic_write_json(anomaly_notified.json)` 落当日签, 再 `send_alert(check=False)` | 全渠道失败 ⇒ 当日该异动(**含 severe 项**)丢失, 同日同 key 已占 ⇒ 30min 下一轮不再补发 | 拆 compute(`filter_and_record` 只返回) / commit(`record_notified`); `send_alert` 返回 bool; **送达才落签** |
| B4 | `scripts/gen_daily_brief.py` | `results = notify.send(...)` 后 `if not dry_run: notify.update_dedup(dedup_key)` **不判 channels** | 全渠道失败仍占当日去重窗 ⇒ 当日重跑被「通知已发过(date=…)」抑制(该 key 带日期, 次日才恢复) = 当日「每日速递」丢失且不可补发 | `_channels_sent(results)` 门控 `update_dedup`(至少一渠道真发出才占窗) |
| B5 | `scripts/check_signals.py` | fade 子去重 `filter_fade_alerts_intraday` 在主邮件前写 `fade_notified.json` | 全渠道失败 ⇒ 重试邮件会重发主信号但 **缺 fade 警示栏**(该子签已占, 同日不再补) | 主邮件两处失败分支(notify 异常 / `ok_channels` 空)**回滚本轮新落 fade 签** |

### 1.2 前序已修(独立标记, 本波未再动)

| 站点 | 出处 | 判据 |
|---|---|---|
| `check_data_gap_alerts.py` / `sensenova-proxy-healthcheck.py` / `overfit_monitor.py` | A 波 `4c9b41efb` | `notify_sent()` |
| `check_s06_freshness.py` / `check_failed_units.py` | 上游 #241 / #240 F1 | `notify_sent()` |

### 1.3 判定「安全」的站点(notify.py `--dedup-key` 自行在**成功后才**落窗)

`notify.py:2366/L749/L2193/L2253` 等:`update_dedup` **只在送达成功分支调用**。故所有「shell →
`notify.py ... --dedup-key ...`」的 fire-and-forget 调用**天然安全**(无「先落签」):
`turnover_backfill.sh` / `kelly_intraday_rerun.sh`(3 处) / `check_r2_consistency.sh` /
`intraday_snapshot.sh`(3 处) / `nextday_gap_check.sh` / `check_monitor_heartbeat.py` /
`feishu_missed_fetch.py` / `alert_denoise_rules._notify_r4_state_write_fail`。

另:`check_nt_signals.py`(L415 `ok_channels` 门控)/ `signal_kelly_snapshot.py`
(`ok = res and any(res.values())`)判据**本身正确**, 无需改。

### 1.4 不动 + 上报(逐条理由, 见 §4)

| 站点 | 归类 |
|---|---|
| `upload_r2.py`(7 处 `notify.send`;6 处 `check_dedup→send→无条件 update_dedup`) | **冻结面(§23.7)** |
| `schedule_monitor.sh` / `monitor_72h.sh` 的**恢复 notify** | dedup-key 抑制歧义 + 回滚致面板振荡 |
| `brief_push.py`(`state["pushed"]=date` 不判 results) | 部分成功语义, 盲目重推会重复投递 |
| `self_heal.sh`(`limit_notified=True` 不判 notify 结果) | info 级 dashboard, 非真告警 |
| `monitor_72h.sh` L68「到期停止」通知 | 一次性自停通知, 无「持续⇒重试」语义 |
| r7/r4 分级计数(`alert_denoise_rules` + notify.py L2110 侧) | notify.py 冻结面; 告警本体走 dedup-key; 计数推进 ≠ 告警丢失 |
| Pattern B(`check_monitor_heartbeat` / `nextday_gap_check` / `nextday_plan_generator`) | A 波已核「不动 + 上报」(rc→升级门, 非落签) |

---

## 2. 统一修法与实现要点

### 2.1 判据:唯一实现 `scripts/notify_sent.py:notify_sent`

`notify.py main()` 全出口恒 `return 0`(含「全部渠道未发出」), **rc 无告知力**。
`notify_sent(输出文本)`:命中 `全部渠道未发出`→False;命中 `已发出`→True;`路由完成：{…True…}`→True;
未知/空→**False(fail-safe: 判不出 ⇒ 不落签 ⇒ 下轮重试)**。本波 5 站点全部委托它(A 波同源)。

### 2.2 两种等价落地

- **Python 拆分/门控**(B3/B4):把「compute」与「commit」拆开, commit 门控在 sent 之后。
  B5 因 fade 签在主邮件前落, 用**精确回滚**(只删本轮新增 key)等价实现「未送达不落签」。
- **Shell 快照 + diff + 回滚**(B1/B2):聚合状态在**收尾才 save**, 无法简单拆 compute/commit ⇒
  在轮首 `_STATE_PRE` 快照, notify 后若未送达 ⇒ `_rollback_transition(alert_state, _STATE_PRE, "active")`
  **只回滚本轮新变 active 的 key**(既有 active / pending 计数 / `r2_pipeline_congestion`(无 status) 一律不动),
  再 save。效果等价「失败轮不落签 ⇒ 下轮重试」。
  - 为什么回滚而不是「先不 save」:轮内已有 7 处检查点 `save_alert_state`(R5 拥堵状态等必须即时持久化),
    收尾聚合状态与它们共用一个文件;回滚是最小侵入且可精确界定「本轮新增」的等价实现。
  - `--alert-issue` 的 `latest.md` 镜像**不依赖渠道成功**(仍写), 故「最新告警页」不丢。

### 2.3 不弱化 fail-safe

未送达/判不出 ⇒ **一律不落签/回滚** ⇒ 下轮重试;送达成功才保留签。未引入任何「不确定也当成功」分支。

---

## 3. 防轰炸评估(§15, 逐站点)

**总原则:重试频率 = 该站点运行频率;通道恢复后首轮送达即止(既有抑制机制在成功后才收口);
用户恰好收到一次。** 逐站点:

| 站点 | 运行频率 | 全挂期间行为 | 通道恢复后 | 判定 |
|---|---|---|---|---|
| B1 schedule_monitor.sh | 15min/轮 | 每轮回滚 ⇒ 每轮重试(发不出) | 首轮送达 ⇒ 落签 ⇒ 抑制(1 封) | **不轰炸**(每轮最多 1 封且发不出) |
| B2 monitor_72h.sh | 30min/轮 | 同上 | 同上(1 封) | **不轰炸** |
| B3 detect_intraday_anomaly.py | 30min/轮 | 不落签 ⇒ 每轮重试 | 首轮送达 ⇒ 落签 ⇒ 去重 | **不轰炸** |
| B4 gen_daily_brief.py | 每日 20:40 | 不占窗 ⇒ **当日运维重跑**可补发 | — | **不轰炸**(无自动重试, 仅解人工重跑抑制) |
| B5 check_signals.py fade | 10min(盘中) | 回滚签 ⇒ 重试邮件带 fade 栏 | 主邮件 Ok ⇒ 落签 | **不轰炸**(fade 栏随主邮件, 主邮件本身有 ok_channels 门控) |

**远端残余(诚实标注)**:若 `notify_sent` 因输出格式漂移误判(把成功判 False)⇒ 每轮重复投递。
概率低, 且失败时 stderr 打印 `rc + 输出尾部 200 字` 可排障。

---

## 4. 不动清单 + 理由(§23.11 绝不静默跳过)

1. **`upload_r2.py`(7 处)** —— **冻结面**:①任务明确「frozen link, evaluate before touching」;
   ②它是 R2 上传链核心, 6 处 `check_dedup→notify.send→无条件 update_dedup` + L2057(无 dedup),
   改动面大且与上传语义交织;③动它需独立决策(+§23.7 用户拍板)。**本波只列不改, 上报主控/用户**。
   (注: 现有 `scripts/test_193_r2_channel_coverage.py` 只断言 `notify.send` 被调用, 若将来改它不会误红。)
2. **两个 `recovery` notify(schedule_monitor.sh / monitor_72h.sh)** —— ①`schedule_monitor` 侧带
   `--dedup-key schedule_monitor_recovery --dedup-window 21600`, 6h 窗内 `notify.py` 以 **rc=0 + 零输出
   静默 suppress** ⇒ 朴素换 `notify_sent` 会把「合法抑制」误判为「未送达」(A 波 Pattern B pivot 已论证同款陷阱);
   ②按「未送达」回滚 `recovered→active` 会让**已恢复**的 key 在通道故障期被翻回 `active`,
   造成 `alert_ack --list` 面板假告警 + `active/recovered` 每轮振荡;③恢复邮件是**低价值提示**(状态已正确置 recovered)。
   ⇒ 与 A 波「dedup-key 站点 不动 + 上报」同款先例。
3. **`brief_push.py`**(`state["pushed"]=date` 不判 `results`) —— 逐**订阅者**推送是**部分成功**语义,
   单一 bool 无法判定; 盲目「未全成功就不落签」会对已成功订阅者**重复投递**; 正解需 per-recipient 落签, 属独立改造。上报。
4. **`self_heal.sh`**(`limit_notified=True` + `save_state` 紧随 `notify_limit_info`) —— 该通知是
   **info 级 dashboard 记录**(达每日上限=正常状态, 不推送邮件), 非真告警; 丢失仅少一条看板信息。
5. **`monitor_72h.sh` L68「到期停止」通知** —— 一次性自停通知, 发完即 `bootout` 停止, 无「条件持续 ⇒ 重试」语义。
6. **r7/r4 分级计数**(`alert_denoise_rules.r7_*` / `r4_*`, 经 `notify.py` L2110 侧调用) ——
   `notify.py` 冻结面; 且其**告警本体**走 `--dedup-key`(成功才落窗)= 安全; 计数(`consecutive_days`)推进
   ≠ 告警丢失。上报。

---

## 5. 测试与证据(§18 L48 / L49, §23.2)

新增 `scripts/tests/test_241_family_b_consign_20261009.py`(16 用例)。

### 5.1 零外发(§18 L48)

- `subprocess.run` 全程替身(进程内 `CompletedProcess`, **不 spawn notify.py**);
  `ZeroOutboundTrap`(底层 `urlopen`/`SMTP`/`SMTP_SSL`)包裹, `test_00` 先**自证已武装**(hits==1);
  各用例收尾断言 `trap.hits == []` = **本次自测零真实外发**。
- 变量无真外发 `curl`/ssh;`schedule_monitor.sh` 的 heredoc python **只 AST 抽取纯函数**, 绝不 exec 业务主体(§18 L50)。

### 5.2 red-before-green(变异自证, 判别力)

将 5 个目标文件复制到 `/tmp/mutB` 并**回退到旧语义**(去掉 helper/`notify_sent` 门控、恢复无条件落签),
跑同一测试文件: **9 failed / 7 passed**; 修复版 **16 passed**。
失败项 = 各站点负控 + 静态锁(B1-B5 全覆盖), 证明测试非恒绿、判别力真实。

### 5.3 关联套件回归(§15)

`pytest -q` 跑 notify/alert 家族相关 12 套 + 本波新套 = **266 passed, 1 skipped**
(含 A 波 `test_241_family_rc_sent_sweep_20261009.py`、`test_240_alert_denoise_batch2`、
`test_alert_denoise_20261001`、`test_alertchain_hardening_20261003`、`test_160_r2_consistency_followup` 等)。
> 备注: `test_160::test_preflight_real_judge_branch_runs_on_non_systemd` 曾在批量跑时**偶发** 1 红 ——
> 根因是它回退 `pgrep -f update_all.sh`, 与本波改动无关的**并发进程**误撞; 单跑 27 passed。

### 5.4 §23.2 修 bug 三铁律

- **修完整**:先列「同类错误面清单」(§1 全表), 覆盖 rc 轴(A 波)与落签轴(本波)两口径。
- **自测完成**:逐站点负控 + 正控 + 静态锁 + 端到端(B3 跑真 `main()`)全覆盖。
- **排查同类**:根因修 = 统一到 `notify_sent` 单一判据 + 快照回滚通用模式, 非逐文件打补丁(§1.3 安全站点亦逐个核过)。

### 5.5 §23.3 举一反三

同模式/同数据源/同组件还被谁用清单 + 逐项覆盖结果 = §1 全表(含「安全」与「不动」两类均逐条列,
无静默跳过)。相关展示位: `latest.md`(不依赖渠道成功, 仍写)/ `alert_ack --list`(见 §4.2 面板振荡权衡)。

---

## 6. 残余与诚实标注

- **B1/B2 轮内检查点**:轮内 7 处 `save_alert_state` 会先持久化本轮 active;回滚在收尾执行。
  若进程在「检查点之后、回滚之前」崩溃 ⇒ 磁盘短暂保留未送达的 active(下轮仍会因 diff 语义重试, 但极端下仍有窗口)。低概率, 如实登记。
- **`alert_ack --list` 面板**:故障期回滚会让本轮新告警暂时不在面板(下轮重落)。这是「状态语义=是否已成功告警」的必然结果(复审建议「本轮新写 active 的 key 不落盘」同向)。
- **未采纳 `notify_sent` 判 recovery notify**:见 §4.2(误判风险 > 收益)。
- **`upload_r2.py` 未改**:冻结面, 见 §4.1。

---

## 7. 改动文件清单

| 文件 | 改动 |
|---|---|
| `scripts/schedule_monitor.sh` | +`from notify_sent import notify_sent`; +`_diff_transition`/`_rollback_transition`/+`_STATE_PRE`; 主 notify 改 capture+判 sent+失败回滚 |
| `scripts/monitor_72h.sh` | 同款 |
| `scripts/detect_intraday_anomaly.py` | +import; `filter_and_record` 拆 compute; +`record_notified`; `send_alert`→bool; main 门控 |
| `scripts/gen_daily_brief.py` | +`_channels_sent`; `update_dedup` 门控在 `not dry_run and _sent` |
| `scripts/check_signals.py` | +`_rollback_fade_notified`; 主邮件两处失败分支回滚本轮 fade 签 |
| `scripts/tests/test_241_family_b_consign_20261009.py` | 新增(16 用例) |
| `docs/ops/241-family-rc-sent-sweep-b-20261009.md` | 本文件 |

未触碰: `notify.py` / `notify_sent.py` / `check_data_integrity.py` / `update_all.sh` / `upload_r2.py` / A 波 3 文件 / #235·#236·#237 文件。

## 8. 跑法

```bash
python3 -m pytest -q scripts/tests/test_241_family_b_consign_20261009.py
```