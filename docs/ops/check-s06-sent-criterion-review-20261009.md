# #241 独立审查报告 —— check_s06_freshness 落签判据(rc 当 sent)修复

- 日期: 2026-10-09
- 审查对象: feat 分支 `worktree-agent-aec6dd505e576120a`(base `81d41bea9`,已 push),commit `3d29dd576`
- 被审交付: 该分支上 `docs/ops/check-s06-sent-criterion-fix-20261009.md` + 代码 5 文件
- 审查方法: 只读(不切分支,`git show`/`git diff` 取差异);判据/调用方独立全仓 grep 复核;红灯沙箱独立复现;fix worktree 全量 pytest 独立复跑;不采信自述,逐条反证

## 0. 结论总表

| # | 维度 | 结论 | 一句话 |
|---|---|---|---|
| 1 | #240 已上线行为影响 | **PASS** | 可达输出形态旧/新判定逐例相同;唯一差异(tier= 行)对 #240 不可达且为 #241 必需超集 |
| 2 | 判据完备性 / fail-safe | **PASS** | notify.py 全打印形态枚举核销;未知/dry/静默路径均走 False,方向正确 |
| 3 | red-before-green 真实性 | **PASS** | 独立沙箱回退 1 处判据 → 4 failed,断言精确落在「全渠道失败不得落签」 |
| 4 | 打桩真实性(§18 L48) | **PASS** | test_00 先证 trap 武装;全 e2e 不 spawn;trap.hits==[];本轮自跑零真实外发 |
| 5 | notify.py 确未被改 | **PASS** | `git diff` 空;commit 仅 5 文件 |
| 6 | 同族面穷举完整性(§23.3) | **FAIL** | 漏网一处同后果(`sensenova-proxy-healthcheck.py`,见 §6.1);另 4 处观测类枚举缺口 |
| 7 | 全量回归(独立复跑) | **PASS** | 462 passed, 2 skipped in 90.97s,与报告逐位一致 |

## 1. 维度 1 —— 对 #240 已上线行为的影响

- 旧实现(check_failed_units main 版 `_notify_sent`,:216-238)与新 `notify_sent` 逐行比对:唯一差异 =
  锚串 `find("升级档路由完成：")` → `find("路由完成：")`(超集,额外匹配 `[notify][tier=…] 路由完成：`)。
- 可达输出形态逐例(旧判/新判):
  - `[notify] 汇总：已发出 {'email': True,…}` → T / T
  - `[notify] 汇总：全部渠道未发出（…）` → F / F(先查全败再查已发出,顺序相同)
  - `[notify][196] 升级档路由完成：{…有 True…}` → T / T;全 False → F / F(「False」不含「True」子串)
  - `[notify][r7] 升级档窗口内已发, suppress` → F / F(无锚)
  - 通用 dedup 静默 `return 0`(无任何锚) → F / F
  - 唯一差异形态 `[notify][tier=…] 路由完成：{…}`:旧 F / 新 True —— #240 调用形态
    (`--severe --dedup-key failed_units_patrol --dedup-window 0`)不可达该行;该差异恰为 #241 所需超集。
- 定性: **修正(补齐超集),非回归**。内契约一致性:`_tier_send_ok`(notify.py:2115-2120)warning ⇔
  defer_status∈(enqueued,suppressed) 与新判据「dict 出现 True」逐位等价(强正确性论据)。

## 2. 维度 2 —— 判据完备性与 fail-safe

- 独立枚举 notify.py 产出端全部形态(逐出口核销): 汇总已发出/全部渠道未发出(:2368/:2371);
  tier 路由完成(:2190)三态 enqueued/suppressed→True、append_failed→False;tier dedup suppress(:2183)→False;
  196/r7 升级档路由完成(:2334)/窗口 suppress→True/False 正确;agent-done suppress→False;
  dry_run(1727-1729 等)→False;通用 dedup 静默 return 0→False。
- 两消费点实际形态(check_s06 不传 --dedup-key;check_failed_units 窗口 0)均不可达 tier-dedup-suppress;
  未知形态→False→不落签→下轮重试(两方向查过: 漏发方向 fail-safe 正确;轰炸方向仅判不出时重试,现形态全覆盖)。
- 测试样本常量 TIER_*/ESC_* 与 notify.py 实际打印逐字一致(已核)。

## 3. 维度 3 —— red-before-green 独立复现

- 沙箱 `/tmp/rev241-red`(worktree scripts 副本,断言「替换数==1」后把 `sent_ok = notify_sent(out)` 回退为
  `sent_ok = proc.returncode == 0`)→ `4 failed, 15 passed in 0.05s`;FAILED =
  {test_02b(静态锁), test_03(`AssertionError: 全渠道失败**不得**落签状态文件`), test_03b(`append_failed 不得落签`),
  test_99(断言数 36 < 下限 40)}——红灯精确落在判据点,判别力成立。
- fix worktree 同文件 `19 passed`。test_05(`lambda out: True` 旧语义)常驻复现 bug 落签路径 ✓。

## 4. 维度 4 —— 打桩真实性(§18 L48)

- test_00 先证 trap 武装(真触达出口即 raise + hits=1);e2e monkeypatch `check_s06_freshness.subprocess.run`
  (notify 子进程根本不 spawn);全程断言 `trap.hits == []`;trap 局限(仅当前进程/仅 urllib+smtplib)
  模块内诚实标注。
- 出口清单与 notify.py 实查三原语一致(urlopen:446/536/547、SMTP_SSL:938)。本轮审查自跑(沙箱+worktree
  两处 pytest)均为进程内打桩,零真实外发。

## 5. 维度 5 —— notify.py 未被改

- `git diff 81d41bea9..3d29dd576 -- scripts/notify.py` 空;`git show --stat 3d29dd576` = 5 文件
  (notify_sent.py 新 / check_failed_units / check_s06_freshness / test_241 新 / 修复报告新)。

## 6. 维度 6 —— 独立全仓穷举(§23.3)与漏网

独立方法: `grep -rln 'notify\.py' --include='*.py' scripts/` 全清单 + 逐文件 returncode/返回值消费追踪
+ `grep -n 'notify\.py' scripts/*.sh` 全 shell 面。判定口径(与报告同): 「(a) 消费 notify rc
(b) 据以写持久化抑制状态(落签→下轮抑制)= 同后果;仅打印/观测=不同类」。

### 6.1 漏网同后果点(报告 §5 表 + §7 均未列 ⇒ 结论「同后果仅 check_data_gap_alerts 一处」不成立)

`sensenova-proxy-healthcheck.py`(商汤代理心跳监控,生产在用):
- `:130-148 _notify`: `:142 if r.returncode != 0: … return False`(`:146 return True`)——rc 恒 0
  (notify.py 全出口恒 0)⇒ False 死分支 ⇒ 返回 True 与「真发出」不等价。
- `:230-232 main`: `ok = _send_alert(…)`; `if ok and not args.dry_run: _save_state({"fired": True,…})` —— rc 当 sent 落签。
- `:221-222`: `if fired:` → 打「已 fired(true) 抑制重复告警」后 `return 0`。
- `:234` 注释自证同族: 「notify 发送失败不记 fired → 下一轮自动重试(参考 check_s06 同款契约)」——
  意图即 #241 修法,但判据是 rc ⇒ 死分支。
- 失败场景: 代理连续 MAX_FAILS 失败 + 当轮通知全渠道未发出(rc 仍 0)⇒ `fired=True` 落盘 ⇒ 此后每轮
  走「已 fired 抑制重复」⇒ 异常持续期间**告警永不送达、永不重试**(直到恢复才清 fired)= 与 #241 同后果。
- 修法同构(建议): `_notify` 判据改 `notify_sent((r.stdout or "")+(r.stderr or ""))`;该形态走默认 send 路径
  (输出含「汇总: 已发出/全部渠道未发出」),共享判据直接适用;dry 行判 False 与 main 的 `not args.dry_run` 门兼容。
  按 §23.7 冻结契约,处置=上报用户拍板,不擅动。

### 6.2 观测类枚举缺口(不丢真告警,建议报告 §5 补记/泛化)

| 位置 | 事实 | 定性 |
|---|---|---|
| check_monitor_heartbeat.py:101-105 | rc!=0 死分支(return 2 永不可达)+ rc==0 打「已发起告警」不实 | 观测不实;无落签,notify 自身 dedup 失败不占窗 ⇒ 有自动重试,不丢告警 |
| detect_intraday_anomaly.py:244/301 | filter_and_record 先写 dedup 后发(先写后发,非 rc);send_alert 无条件打「告警邮件已发」 | 无 rc 消费;先写后发残余(当日重复轮丢重试,次日重生) |
| signal_kelly_backtest.py:343-348 | rc 死分支仅打印 stderr 明细 | 观测不实 |
| nextday_plan_generator.py:1247-1254 | rc!=0 死分支 `notify_rc=1`(包装层升级告警永不可达) | 观测/升级不实 |

### 6.3 独立复核为「不同类」的其余全清单

check_signals.py(进程内 send/send_to 真实结果 dict 门控落签=正确模式,:439/:2042);brief_push.py、
gen_daily_brief.py:3037(check=False 不读 rc、无落签);check_failed_units.py(#240 已修;:248 rc 仅文案);
nextday_gap_check.py:66/374(仅日志);retry_failed_metrics.py:114/148(仅打印;报告标 :113/150 行号小差);
overfit_monitor.py:1439(报告已列);with_lock.py:179(通用包装器 rc 透传);check_data_integrity.py:2164
(调 check_s06_state,rc 语义);agent_inbox_watcher(git cat-file)/feishu_ws_listener(security)/
gen_schedule_stats(launchctl)与 notify rc 无关。`.sh` 全清单(grep 共 20+ 文件): 均 `|| true`/fire-and-forget/
自身 rc;schedule_monitor.sh:667-690 用 notify_dedup.json 台账判重(反例方向=照发,防吞;非 rc);
:1721-1733 的 rc 是 check_failed_units 自身语义退出码(非 notify rc)。

### 6.4 已列项复核

check_data_gap_alerts.py:1457-1467 + 1569/1573-1575 逐字复核成立(ok→`state[f.key]={last_fired: today}` +
`last_fired==today: skip`)——同后果确认;处置(§23.7 待拍板不擅动)正确。

## 7. 需修项

1. 【维度 6 阻断(文档面)】报告 §5 表 + §7 补列 `sensenova-proxy-healthcheck.py:130-148/221-222/230-232`
   为同后果同类面(处置建议同 check_data_gap_alerts=待拍板);§5 结论句「同后果…仅一处」须改「两处」。
   补记纯文档、不动代码。
2. 【非阻断】报告 §5 第 4 行补 §6.2 表 4 处观测类(或改泛化表述)。
3. 【nit】`scripts/notify_sent.py` 文件末行无换行(尾标记 `\ No newline at end of file`);CI 无 lint 门禁
   (ci.yml 实查无 flake8/ruff 步骤),不红不阻断,建议顺手补。

## 8. merge 建议

fix 本体(check_s06 判据替换 + `_notify_sent` 委托 + 唯一判据抽取 + 测试 + notify.py 未动)维度 1-5/7 全 PASS:
判据有判别力(红灯独立复现)、#240 零回归(逐例)、全量 462/2 独立复跑一致、零真实外发。**唯一未过=维度 6**
(同类面清单漏一处同后果)。该漏网点在另一脚本、不因本 merge 恶化;但 §23.2 验收口径要求清单完整。
建议: **implementer 补报告 §5/§7(纯文档补记)→ 即达全 PASS → merge**;若主控拍板可后补,代码面无阻断。
