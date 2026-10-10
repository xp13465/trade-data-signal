# trade-nextday-gap-check 连续 failed(critical)根因排查与周一观察指引

- **日期**:2026-10-11(深挖窗口 00:46–01:10)
- **执行**:researcher(只读深挖;全程零写:ssh 无写操作、无 systemctl 变更、无 git 写、无残留后台任务)
- **触发**:用户 2026-10-11 投诉「告警这块优化都推进完了吗?怎么还是有告警在提示,而且说的是遗留了 4 天的问题在持续」
- **对象**:云上 `trade-nextday-gap-check.service` failed 持续未清 → 10-11 00:00 升 critical(连续 4 天,自 10-08 起算)
- **关联**:#246(兜底链修复,云上 HEAD `023d73929` 已含);#248(unit 漂移仓库侧同步,深挖顺带坐实,已立项实施中,报告 `docs/ops/248-systemd-drift-sync-impl-20261011.md`)
- **方法**:云上只读探针(systemctl / journalctl / 就位闸日志 / state 文件 / latest.md)+ 新旧代码对照 + 全史归一

## 结论摘要

1. **告警优化全链已上线,该条告警不是噪音**:是真故障残留 —— unit 10-09 运行失败(exit=2)后 failed 状态未清,「连续未清逐日升级」按设计工作(「人工处置超时,需立即介入」为刻意设计)。
2. **根因**:东财 `fund_etf_spot_em` 9:26 时段性风控拒绝 + 旧兜底两缺口(腾讯 ts 缺失终止整链、兜底仅 `16` 前缀)→ 159970 拉不到开盘价 → 就绪闸 FAIL → exit=2。
3. **「遗留 4 天」= 通道级聚合计数**(非 gap-check 单元级):10-08 当天由其它 unit(kelly-intraday-rerun / fapi OOM 等)首次触发通道,此后每天非空 → 逐日升级;gap-check 单元 10-09 才落 failed。
4. **#246 已覆盖根因**(云上已是新版),但「盘前腾讯/新浪当日性锚」从未被采样 ⇒ **周一不能断言必成**(成功率显著高于旧版)。
5. **处置 = 现在刻意不动**(不手动跑、不 reset-failed,理由 §五);**周一 09:26 自然验证**:成功 → 状态自动清 + 恢复邮件;失败 → 按残余风险另立任务(需拍板)。

## 一、10-09 exit=2 根因链(带日志原文)

云上日志 `/home/ubuntu/code/trade-data/data/logs/nextday_gap_check_launchd.log`:

- **10-08(成功日,09:26:00→09:31:17,5m17s)**:attempt1「⚠ 第 1 次拉开盘价失败: akshare fund_etf_spot_em 拉取失败: ConnectionError: ('Connection aborted.', RemoteDisconnected(...)); 且新浪/腾讯双源兜底亦失败: 腾讯行情 560230 时间戳 (缺失) != 执行日 20261008, 当日性无法确认(等效 F4 fail-closed, 拒用旧价)」→「等 300s 重试(9:26→9:31)」→「✓ 重试成功」→ 560230 open=0.697 gap=0.00% → 退出码=0。
- **10-09(失败日,09:26:01→09:31:43,5m43s)**:attempt1 同形态(标的 159970,腾讯 ts 缺失)→ 等 300s → attempt2「⚠ 第 2 次拉开盘价失败: akshare 未返回任何目标 ETF/LOF 的真实开盘价(数据就绪闸 FAIL)」→ severe 告警 rc=0 → 标记 steps 159970 seq1-3 pending → R2 OK → 邮件+飞书已发 → 退出码=2。
- **完整历史(CR 归一后)**:09-23 exit=2 三次(人工重跑,当日修复会话);09-24 / 09-28 exit=0;09-29 attempt1 失败 → 9:31 重试成功;09-30 首拉直接成功;10-01~07 非交易日;10-08 重试成功;10-09 exit=2(唯一落败)。
- **根因三层**:(a) 东财 `fund_etf_spot_em` 9:26 时段性拒绝(TCP 对端断开 = 风控特征;设计文 `docs/ops/1009-real-faults-rootcause-design-20261009.md:115`:9-29 / 10-08 同模式,15:35 复测东财 http=000 而腾讯/新浪正常);(b) 旧兜底缺口 1 = 腾讯 ts 缺失即 raise 终止整链、新浪不可达(`signal_kelly_backtest.py` 旧版 L854 附近);(c) 旧兜底缺口 2 = 兜底仅对 `16` 前缀 LOF 启用,159970 为 `15` 前缀不兜底 → out 空 → 末端 raise → exit 2。
- **exit=2 语义**:①就绪闸 FAIL 重试耗尽(`nextday_gap_check.py` L241-262 return 2)②未捕获异常(L443-458 `sys.exit(2)`)。10-09 属①。耗时:300s sleep + 两次拉数各 ~8-20s + 尾段(标记/R2/通知)~11s;**563s < TimeoutStartSec=600(余量仅 37s)**。

## 二、「自 2026-10-08 起」判据

- 计数 = **通道级**聚合(「云上有 failed unit 未清」),非单元级。实现 `alert_denoise_rules.py` `consecutive_days_escalate`(L198-264);state = `/home/ubuntu/code/trade-data/data/failed_units_patrol_state.json`;仅通道被调用时递增,相邻日 +1,缺口 >1 重置;≥3 天升 critical。
- 云上实值:`{"last_fail_date":"2026-10-11","consecutive_days":4,"first_fail_date":"2026-10-08","last_grade_time":"2026-10-11 00:00:02"}`。
- 起点 = 10-08 的原因:当天有**其它** failed unit 首次触发通道(latest.md 实证 10-08 09:45 `kelly-intraday-rerun` → 10-08 16:00 → 10-08 22:15 六项含 fapi OOM → 10-09 04:30 七项…每天非空)→ 10-10 days=3 升 critical、10-11 days=4 critical(00:00:06 已发 = 用户投诉那条)。
- gap-check 单元 10-09 09:31:43 才落 failed,首次进列表 = 10-09 10:45(latest.md:239)。**「连续 4 天」对通道成立、对单元不成立**;10-08 运行成功与计数不矛盾(当日由其它 unit 触发)。
- 现 failed 集合(`systemctl --failed` 实读)**恰 2 个**:patrol(drift,rc=1 设计)+ gap-check(ExecMainStatus=2);巡检 sig items 只记 gap-check(patrol 被 `wrapper_channel_alerted` 抑制)。

## 三、#246 覆盖判定(逐点)

| 缺口 | 判定 | 依据 |
|---|---|---|
| 缺口 1(腾讯 ts 缺失终止整链) | **覆盖** | 腾讯日期不符记 missing 继续 → 新浪(`[30]` 日期锚),逐标的独立(246 doc L15-17) |
| 缺口 2(兜底仅 16 前缀) | **覆盖** | 兜底对所有缺失项启用(不限 16) |
| 末端 raise | 仅 out 全空才 raise(文案已改) | 同 246 实施 |
| 重试 300s 单次 → 60s×3 | **覆盖但行为差异** | 每轮退避 45~75s、预算硬顶 450s、默认 3 轮 = 135~225s。旧重试落 9:31:17(开盘后,10-08 靠它躲过);新版 4 次尝试估算 ≈9:26:00–9:30:25(jitter 极端偏晚可过 9:30 线)⇒ **救回依赖从「东财 9:31 恢复」换成「腾讯/新浪盘前可用」** |
| 563s vs 450s | 墙内安全 | 旧 5m43s = 300s sleep;新版总时长估算 ≈3-4 分钟(4 次拉数 + 135~225s 退避),TimeoutStartSec=600 安全 |

- **残余风险**:腾讯盘前两次实测 ts=(缺失)(10-08 / 10-09);**新浪盘前从未被采样**(旧码分支不可达)。246 doc 的「两源 9-23 实测 8/8」非盘前时点。
- 云上已确认新版:GIT_REPO HEAD=`023d73929`(10-10);`/home/ubuntu/code/trade-data/scripts` → symlink → `trade-data-signal/scripts`;`nextday_gap_check.py` 含 `RETRY_BACKOFF_BASE_S`(3 处)。

## 四、周一预测与 48h 告警时间表

- 目标 560230(buy_date=20261012, prev_close=0.685)。
- 最可能:东财 9:26 仍拒 → 腾讯(盘前 ts 缺失 ×)→ 新浪(未知),4 attempts 全在 ~9:26–9:30:25。**子情 A** = 新浪/腾讯有当日锚 → exit 0 救回(**成功率显著高于旧版**);**子情 B** = 盘前结构性无锚 → exit 2 重现(形态同 10-09)。
- 旁证:新浪+腾讯兜底链本身可用(10-08 deploy 链 5 次「2053 只」全量成功,均为非盘前时点);东财恢复节奏(10-08 9:31、10-09 9:37 前后)均晚于新版末次尝试窗。
- **结论:不能断言必成**;唯一未采样点 = 盘前 9:26-9:30 新浪/腾讯当日性锚。
- **systemd 自动清除 = 成功运行一次即自动清 failed**(oneshot 语义;实锤 `trade-r2-consistency` 10-08 23:23 失败 → 10-09 20:15 仍 failed → 10-09 23:20 成功 → 现 success/inactive;同类 kelly-intraday-rerun / lhb / futures-backfill / etf-national-team 均随后续成功消失)。**无需 reset-failed**。
- 若周一成功:9:26 成功即清 unit;注意 **Mon 00:00 巡检在 9:26 之前 → 会先发一条 critical(连续 5 天)**,9:26 后才止。恢复通知:`nextday_gap_check` 通道走 schedule_monitor 恢复机制(alert_state 键 `nextday_gap_check|exit!=0|2` 与 `nextday_gap_check|ConnectionError:|683c4547` 现 active,first_seen 10-09 09:45)→ 条件消失发**恢复邮件**;`failed_units_patrol` 通道无恢复通知(只是不再发)。
- **未来 48h 告警时间表**:今天(10-11)08:27 漂移 → days=3 critical(未修则发;#248 正连夜修);Mon 00:00 failed-units days=5 critical;Mon 08:27 漂移 days=4 critical(未修);Mon 09:26 gap-check 运行;Mon 09:45 后或见恢复邮件。

## 五、处置清单

**现在(刻意不做,已核理由)**:

- ❌ **不跑 gap-check**(含 force `--dry-run`):`_severe_alert` 在 FAIL 路径的 dry-run 判断**之前**无条件调用(L241-252 + L102-116,不查 dry-run/no-notify;dedup 1h 早已过期)→ 会发真告警;周日数据与 20261012 不符必 FAIL;无收益。
- ❌ **不 reset-failed**(同意主控倾向):只清状态不修根因;保留取证现场;会人为消掉 Mon 00:00 critical(与「不留遗留告警」诉求相反且根因未经周一验证);timer 到点照跑,清状态不影响周一成功与否;周一如成功自动清除。补充:reset 后集合空 → 通道不调用 → days 冻结 4;若周一又失败 gap==1 → days=5 继续 —— reset 并不改变走向,只少发一条。
- 云上 patrol / gap-check 均不 reset。

**等周一**:

- 09:26 后 tail 日志看 exit 0/2;成功 → 零操作;失败 → 按残余风险排查(方向:默认窗口后延跨 9:30,或复用 9:35 后已恢复链路做盘中兜底 —— 属新任务需拍板)。
- 漂移修复:**需在 Mon 08:27 前 merge 且云上 pull 到位**;若想赶「今天 08:27」(days=3 critical)前,需 merge 于云上 ~02:0x / 05:0x deploy pull 之前完成(#248 执行中)。

## 六、顺带项:unit 漂移(→ #248)

- 差异 = `trade-fapi-daily.service` `MemoryHigh ['1.5G']` / `MemoryMax ['2G']` / `MemorySwapMax ['512M']`:云上有、快照 None。
- 定性:**云上 = #238 OOM 加固**(2026-10-09 07:13-07:24,9/9 PASS)有意为之且正确;仓库两份副本过期:①`docs/deploy/systemd-units-cloud-snapshot.txt:187` ②`docs/deploy/systemd-units-20260912.md:402`(`fapi-daily-oom-host-hardening-20261009.md` §5 已登记)。
- 机制:`cloud_unit_patrol.sh` L15/L152(有意改 → 刷新快照 + 对齐 doc §2 走 merge)+ `main-merge.sh` L374-386 闸门 7.8(--check-doc)⇒ **两份必须一起改**。工具:`systemd_timeout_gradient_audit.py --dump <snap> --align-doc`(可对 doc 就地按权威源对齐);快照本体无写模式,手改三行或重 dump。
- 处置(单列任务,不动云上):三行逐字节抄进两份 → merge → 云上 pull 后 08:27 rc=0。现状 drift state:days=2、last=10-10(今天 08:27 将 days=3 critical)。⇒ **已立项 #248,实施中**。

## 七、同类排查

- `systemctl --failed` 恰 2:`patrol`(rc=1 漂移)+ `gap-check`(rc=2 残留);无其它 failed 残留。
- 耗时异常:无新增(历史 10-08 `intraday_snapshot` 928s>900s 已恢复)。关键时点:Mon 00:00 monitor / 08:27 patrol / 09:26 gap-check。

## 附:复现命令(云上只读,入口清单)

```bash
# ssh 前缀(全只读;命令内禁 $ 变量,写绝对路径字面量)
ssh -i /Users/linhuichen/tdsignal.pem -4 -o ConnectTimeout=10 ubuntu@122.51.111.173
# 1) unit 状态与失败码
systemctl show trade-nextday-gap-check.service -p ActiveState,Result,ExecMainStatus,ExecMainStartTimestamp,ExecMainExitTimestamp
# 2) 失败集合(预期恰 2:patrol 漂移 + gap-check)
systemctl --failed
# 3) timer 排班(下次触发)
systemctl list-timers | grep -E 'nextday-gap|cloud-unit-patrol'
# 4) journal 两次运行对照(10-08 成功 / 10-09 exit2)
journalctl -u trade-nextday-gap-check.service --since '2026-10-06' | tail -60
# 5) 就位闸/重试明细日志(根因现场)
tail -80 /home/ubuntu/code/trade-data/data/logs/nextday_gap_check_launchd.log
# 6) 升级状态(通道级计数)
cat /home/ubuntu/code/trade-data/data/failed_units_patrol_state.json
# 7) 告警台账(10-08 起通道触发链)
tail -120 /home/ubuntu/code/trade-data/data/alerts/latest.md
```

> 周一复盘入口:09:26 后执行 #4/#5 看 exit 码与 attempt 明细,与本文 §四「子情 A/B」对照。