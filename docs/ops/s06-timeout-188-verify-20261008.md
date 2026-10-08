# 云上只读取证:s06 超时梯度 / #188 连带 / #191·#194 生效状态(2026-10-08)

- 角色:tester 云上只读取证。主机 ubuntu@122.51.111.173;取证时段 2026-10-08 20:5x~21:3x CST。
- 全程零写:未启停/未改 unit、未跑业务脚本主体(探针 static-only,§18 L50)、未写 R2、零邮件飞书外发、未切分支/未 commit。落档文件在主工作树(main),按任务要求不 commit。
- 进度文件:/tmp/agent-progress-s06-188.md

## 0 结论速览
| # | 项 | 结论 |
|---|---|---|
| 1 | s06 超时梯度(3300s 改动后首跑) | PASS:退出码=0、结束行在、起止 20:35:01→20:35:23(~22s,未触顶) |
| 2 | #188 四小项 | 台账/自测/告警面全 PASS;deploy 行形态三例;今日 verify-r2 因 deploy 中止未跑到(未测) |
| 3 | #191/#194 | patrol timer active+enabled,08:27 趟 exit 0(82 unit 逐字段全量比对通过);脚本 md5==main |
| 4 | 6 个 failed unit | 名单见 §4;6 个 timer 全 active/enabled/Persistent=yes ⇒ 下次触发重跑、成功即自动复位 |

## 1 s06 超时梯度真行为(TimeoutStartSec 600→3300 改后首跑,20:35 档)
- 配置实测:`systemctl show trade-s06-snapshot.service` → **TimeoutStartUSec=55min(=3300s,改动在位)**;Result=success、ExecMainStatus=0、Start 20:35:00 / Exit 20:35:23、ActiveState=inactive/dead。
- 结束行(判据):`=== s06_snapshot.sh 结束 2026-10-08 20:35:23 退出码=0 ===`(data/logs/s06_snapshot_launchd.log)。**退出码=0,非 143、无 SIGTERM/超时杀痕迹**。
- 起止/耗时:开始 2026-10-08 20:35:01 → 结束 20:35:23,约 22s(远小于旧上限 600s ⇒ 正常日不触梯度)。
- 四段链全绿:①gen ✓ ②check_s06_state 机检六项全 PASS(独立复算/时序/键集/阈值单源/锁死不变式/前段元数据)③upload_data_files(kelly_mode_s06_state.json)+ purge ✓ ④kelly_posrating 两树 ✓ + kelly-snapshots 上传 3/3、耗时 6.7s、purge 3/3。
- 上游观察复核:schedule 监控行 `S06_FRESH_OK coverage_end=20261008 index末=20261008 落后=0个交易日 generated_at=2026-10-08T20:35:01`。
- R2 直连对象(互联网侧):Last-Modified=2026-10-08 12:35:03 GMT(=CST 20:35:03)、ETag=`945dd9981f9bfe89fb1df7985b626df9`=本地 md5、610455B。
- 诚实标注:退出码=0 只证明「正常日不触顶」;「卡死日能吃到 3300s 窗口」需卡死场景才能实测(未测,只读任务不做)。
- 数值闭环:gen 打印 `610338`=字符数(wc -m),字节数=610455(wc -c),差=多字节字符所致,非异常。

## 2 #188 四小项
### ① 台账(data/.r2_standalone_keys.json)
LEDGER_N=68、STATE=ok、RECONCILABLE=68、DEAD=[](空)、HAS_S06=True(含 data/kelly_mode_s06_state.json)。news_digest/* 属 #193 后「可对账」非死键;feed.xml 不在台账。**PASS**
### ② 平日 verify-r2 是否真对账 s06 + 告警串
- 云上直跑自测:`python3 scripts/test_188_s06_sync_blindspot.py` → **ALL_PASS / TEST_RC=0**;[env] 自测配置树=/home/ubuntu/code/trade-data(.env 解析正常,**未出现「云上跑不动」,无需 dev 侧替代**)。
- 告警串:**零命中**。alert_state.json 无 verify_r2_standalone_stale / verify_r2_standalone_ledger_gap;logs 全量扫 `verify_r2_standalone`=空;notify_dedup.json 中 `s06_snapshot_fail`=2026-09-21 20:35:16 历史条目(非今晚;今晚链退 0 无告警)。
- 生产实跑点(最近一次异步链):r2_upload_async 10-07 21:16:23→21:29:49 退出码=0,内含 `[verify-r2] ✓ 对账完成, 自动补传 2 个; 涉及文件名: data/news_digest/_index.json, data/news_digest/2026/2026-10-07.json`。
- 缺口(如实):今日(10-08)多趟 deploy 因数据闸门中止(见 §5②),**未跑到 verify-r2 环节** ⇒ 今晚无生产对账行可引;「平日分支已生效」当前证据=自测+机制层(单一证据源标注)。
### ③ 当日 deploy 日志 s06 行(三趟,均在 L578)
- deploy_20261008_2025.log:`✗ s06_state: 线上 S06 快照 coverage_end=20260930 滞后 8 天 > 7 天`(再生成前,旧数据+超 7 天 FAIL 分支)
- deploy_20261008_2100.log:`⚠ s06_state: ✓ S06 快照机检全 PASS(……六项);但 R2 用户可见副本 coverage_end=20260930 ≠ 本地 20261008(本地新鲜≠线上新鲜, 疑 s06 20:35 上传链被杀; verify-r2 会补传, 见 #188)`(**新 ①b 真对账已上线并当场命中 CF 旧变体;WARN 不 FAIL,未阻断 deploy**)
- deploy_20261008_2108.log:`✓ s06_state: ✓ S06 快照机检全 PASS(……六项);R2 副本 coverage_end=20261008 与本地一致`(恢复正常)
- 旁证:R2 直连对象自 20:35:03 起即新鲜(§1)⇒ 21:00 读到的旧值=CF edge 短时旧变体(§5①)。**该 WARN 文案中「疑 s06 20:35 上传链被杀」的假设被本次取证证伪**(链路 exit 0、R2 对象 20:35:03 即新鲜);文案是否修订属另派。
### ④ 自测脚本执行
见 ②第一行:云上直跑 ALL_PASS(rc=0),无云上环境问题。

## 3 #191/#194 生效状态
- timer `trade-cloud-unit-patrol.timer`:ActiveState=active / UnitFileState=enabled / OnCalendar=08:27 / Persistent=true。
- 10-08 08:27:01 趟:exit 0,「82 unit 逐字段全量比对通过」(tail -30 data/logs/cloud_unit_patrol_launchd.log)。
- 脚本 scripts/cloud_unit_patrol.sh md5=`619821135f4837587ad8270cb0830f9f` == main 当前版;#194-F2 环境守卫(exit 3 不 notify)/#194-F3 失败出口可写性/#191 标记均在位。
- 对应 commit:b94c32eff(#191)、8a74e779b + d935267f2(#194)。

## 4 6 个 failed unit + 自动复位判断(只读,零修改)
| unit | 失败形态/时点 | 下次触发 |
|---|---|---|
| trade-etf-national-team | exit1,20:07:00→20:18:50;自愈 3 次均败,21:07 达每日上限 | 今晚 21:30 |
| trade-fapi-daily | OOM 被杀(19:23:39,kernel global OOM;受害者 python 10m23s CPU) | 明日 18:10 |
| trade-futures-backfill | exit1 ×2(20:12:36、21:10:11) | 明日 20:05 |
| trade-kelly-intraday-rerun | exit=5(09:40:15) | 明日 09:40 |
| trade-lhb-backfill | exit1(19:37:26) | 明日 18:30 |
| trade-public-fund-daily | exit1(17:06:59) | 明日 16:30 |
- 复位判断:**会**。6 个 timer 全部 active/enabled/**Persistent=yes** ⇒ 到点自动重触发;systemd oneshot 失败态在下次成功启动时自动清除(无需人工 reset-failed)。`systemctl list-unit-files --state=failed`=0(unit 文件层无 failed)。
- 现场实证:截至 21:25:55 检查,etf 21:30 触发时点未到(ActiveState=failed 维持 20:07 态,NEXT=21:30:00)⇒ 现场实证未取;若 etf 21:30 再败则保持 failed 态(自愈已用尽),属链本身问题(§5⑤)。

## 5 异常项(待主控处置)
① **CF 边缘短时旧变体**:21:00 deploy ①b 读到旧变体(610302B、etag c67db…、age≈2877s),约 6 分钟后 4/4 采样新鲜(610455B、md5=945dd…)。影响:目前 ①b=WARN 不阻断;**若未来收紧为 FAIL 会误伤 deploy** ⇒ 建议保持 WARN 或加一次重试(需另派)。
② **alert.json 等 8 天滞后 ⇒ 今晚 20:25/21:00/21:08/05:00 多趟 deploy 于校验环节中止**:与已登记 #235「长假机制型假阳性」同源类,建议归并 #235 一并定性。
③ **trade-fapi-daily 被 OOM 杀(19:23:39)**:主机内存压力实锤(触发者 packagekitd);与今日 18:30 swap 100% SEVERE 用户态停摆同根;建议 fapi 内存/并发治理。
④ **trade-futures-backfill 今日连败 2 次**(exit1;err 仅 resolve_repo 信息行):错因未定,建议另派深挖(超本次只读范围)。
⑤ **etf-national-team 自愈链 3 次失败达上限**:数据链本身需人工关注。
⑥ notify_dedup.json 的 `s06_snapshot_fail`(2026-09-21)=历史条目,无今晚告警,可择机清理。

## 6 未测项(如实)
1. s06 超时梯度「卡死场景真吃到 3300s」未实测(正常日 22s;构造卡死属写操作,只读任务不做)。
2. etf 21:30 重触发的现场复位实证:检查时点 21:25:55 早于触发,未取到现场复位瞬间。
3. futures-backfill exit1 具体错因(超范围)。
4. CF 旧变体对前端实际取数路径的影响(只测 R2 直连 + 原 URL 采样)。
5. 今日生产 verify-r2 行(deploy 多趟中止,未跑到该环节)。

## 7 复现命令(只读)
- s06:`ssh -4 -i <pem> ubuntu@122.51.111.173 "cd /home/ubuntu/code/trade-data/data/logs && tail -8 s06_snapshot_launchd.log && systemctl show trade-s06-snapshot.service -p TimeoutStartUSec -p Result -p ExecMainStatus"`
- #188 自测:`ssh ... "cd /home/ubuntu/code/trade-data-signal && timeout 120 python3 scripts/test_188_s06_sync_blindspot.py"`
- deploy 行:`ssh ... "cd /home/ubuntu/code/trade-data/data/logs && grep -H -n 'coverage_end' deploy_20261008_2025.log deploy_20261008_2100.log deploy_20261008_2108.log"`
- #191/194:`ssh ... "tail -30 /home/ubuntu/code/trade-data/data/logs/cloud_unit_patrol_launchd.log && systemctl show -p ActiveState,UnitFileState trade-cloud-unit-patrol.timer"`

## 8 安全审计自查
- 未执行任何写操作;未启停/修改任何 unit;未跑业务脚本主体(唯一执行=白名单自测脚本 test_188_s06_sync_blindspot.py,已先核三重护栏);curl 均 `--max-time 20 -sL` 未用 -v/-i;ssh 全 `-4 + ConnectTimeout=15 + BatchMode=yes`;grep 均为具名白名单文件(无 -r、无 `find /`);未切分支/未 commit;无 WebFetch;零邮件/飞书外发。

## 9 补记(2026-10-08 21:30:58 追加;覆盖 §4/§6 中「现场实证未取」表述)
- **etf-national-team 21:30 重触发现场实证:已取到**。`systemctl show` → ExecMainStartTimestamp 由 20:07:00 更新为 **2026-10-08 21:30:00**、ActiveState=activating / SubState=start(正在激活运行);journal `Oct 08 21:30:00 ... Starting Trade etf-national-team ...`;上一轮 failed 的 Result=exit-code 已被新一次启动清为 success 历程值 ⇒ **失败态不阻塞下次触发、到点即重跑,timer 层「自动复位」前半段现场坐实**。
- 该次重跑最终成败需 ~21:41 后复查(上一轮 20:07→20:18:50 历时约 11min);至本补记时点仍在激活中,终态未取(仍列未测 §6-2)。
