# 云上告警排查纪要:2026-10-03 ~ 2026-10-06(近 3 天全量)

> 排查人:researcher 子 agent(只读排查,未触发任何真实告警/未 source 业务脚本主体)。
> **数据截止**:2026-10-06 18:19(最后一次读取);`latest.md` mtime=2026-10-06 17:16:27。
> 权威口径说明:告警权威树=**云上 `/home/ubuntu/code/trade-data`**(数据/日志/告警状态);`trade-data-signal` 树的 `data/alerts/latest.md` 是 **rsync 排除告警状态文件后的过期副本(mtime 2026-09-30 22:35,不可信)**——运维误读风险点,见 §5.5。

## 0. 方法与口径

- 事件驱动扫描(§18 L46):`systemctl list-timers` 全貌 + `find <日志目录> -type f -mmin -4320` 列新鲜文件逐个 tail 近段,再叠关键词 grep。
- 告警出口清单(已全部核对):①`trade-data/data/alerts/latest.md`(severe 流水,50 条滚动)②`trade-data-signal/data/alert_state.json`(140 键,3 条 active)③`trade-data-signal/data/notify_dedup.json`(dedup 状态)④launchd 日志(`schedule_monitor_launchd.log` 等)⑤journalctl 近 3 天。**注意 alert_state.json/notify_dedup.json 在 signal 树被 rsync 排除不在 trade-data 树**——两树分居属既定架构,非异常。
- 严重度口径:severe(邮件+飞书+镜像 latest.md)/ 非 severe(仅计数/列表)。

## 1. 全景:按天 × 按源 × 严重度

### 1.1 按天分解(severe 事件,共 23 事件 / 20 条目)

| 日期 | severe 事件 | 构成 | 非 severe |
|---|---|---|---|
| 10-03 | 1 | fetch_news ×1(00:30) | 0 |
| 10-04 | 15(12 条目,含 2 项与 3 项条目) | fetch_news ×9、backfill_evening ×3、update_all ×2、us_stock_morning ×1 | mass_mismatch ×1(04:07:20) |
| 10-05 | 6 | fetch_news ×4、R2 上传失败 ×1(13:03:49)、R2 purge 失败 ×1(17:59:51) | 0 |
| 10-06 | 1 | R2 上传失败 ×1(17:16:27) | standalone_stale ×1(18:19:38) |

> 10-04 是异常放慢日(update_all 167min+139min、backfill 3 档全超时、us_stock 45min);10-05 起 update_all/backfill/us_stock 全部恢复正常(见 §2.3)。10-05 是 R2 上传链新机制(10-04 21:51 上线)的首个考验日,恰逢网络抖动(见 §2.2)。

### 1.2 按告警来源分解

| 来源 | severe | 非 severe | 说明 |
|---|---|---|---|
| schedule_monitor_notify(计划任务监控) | 20 | 0 | fetch_news×14 + backfill×3 + update_all×2 + us_stock×1 |
| r2_upload_async.sh(看门狗 kill 告警链) | 3 | 1 | 10-05 13:03/17:59、10-06 17:16 severe;10-06 18:19 standalone_stale |
| deploy 链 verify-r2 | 0 | 1 | 10-04 04:07 mass_mismatch(周日全量) |

### 1.3 严重度分级与通道

- 近 3 天全部 severe 条目的通道均为 `email=OK feishu=OK`(告警通道本身无故障)。
- 补证:10-05 起 `r2_upload_async_skip.log` 仅 1 条(10-05 18:10:45 锁跳过登记)——r2_upload_async 并发锁跳过机制上线后仅触发 1 次,健康。

## 2. 逐条证据与三问判定

### 2.1 族 A:fetch_news SKIPPED_LOCKED(14 条,近 3 天最大告警源)

**证据行**(原文摘录,来源 latest.md 行 232~372):
- 10-03 00:30:18 / 10-04 03:30、04:30、06:30、07:30、18:30、19:30、21:30、22:30、23:30 / 10-05 00:30、03:30、13:30、18:30 —— 文案固定:`[SEVERE] fetch_news R2 上传锁连续 3 轮跳过(SKIPPED_LOCKED), 上传缺口持续(收盘版/每日版可能未上 R2), 需人工关注`;触发源=`schedule_monitor_launchd.log`;频次=**14 条**。
- 10-06 未告警:该日 17:00-17:45 计数 1/3→2/3 后 `[r2-skip-stale]` 清零(滞留值>30min 不计数),**未达连续 3 轮阈值**。

**三问判定**:
1. 老/新:**机制老(持续现象),近 3 天整体是"10-05 之后自愈降频"**。更早可追至 09-24 burst 自 10-01 18:30 起;10-06 归零。
2. 是否已修复:**10-06 未再冒(事实),但机制未改**——属"随网络/锁占用恢复而静默"。判定:半活体。
3. 优化空间(降噪与判别并存):a)跳过前可"等锁+短超时重试一次"再计轮,降低网络抖动噪声;b)**必须保留**"连续 3 轮 = 上传缺口持续"的真故障判别(即当前设计),不能图省事把阈值放宽或关闭。

### 2.2 族 B:R2 上传链(3 条 severe + 1 条非 severe)——**10-05 新机制首考**

**背景(关键)**:
- `scripts/r2_upload_async.sh` **首次提交 = b4c5ff5ff(2026-10-04 21:51:34)**「feat(updateall-perf): R2 上传异步解耦」——**10-03/10-04 无 r2_upload_async_*.log 的原因=机制当时尚未上线**(10-03/04 上传走 deploy 链内 verify-r2,证据:deploy_20261003_0205.log L769「补传 35 个」、deploy_20261004_0205.log L772「补传 114 个」)。
- 看门狗「停滞 300s 判死」由 **9faf92d8e(2026-10-05 11:17:50)**「fix(r2): 看门狗停滞判据 #174」上线;当天 12:25 与 16:51 两轮即出现 kill。

**证据行**:
- 10-05 13:03:49 severe「R2上传失败」:详情「通道 upload-etf-hist 本轮被看门狗超时 kill(force_full 未完成, PUT 未执行), **不适用轻量对账静音, 保留告警**」← #177「KILLED 通道保留告警」在生效。触发:12:25 轮 `upload-etf-hist 停滞 300s 无日志输出, kill pid=613087`。
- 10-05 17:59:51 severe「R2 末尾 purge 低频文件失败」:16:51 轮 13 连 kill 收尾。
- 10-06 17:16:27 severe「R2上传失败」:16:52 轮 `verify-r2 停滞 300s 无日志输出, kill pid=1019507`;告警详情「**无输出**」(tmp_log 已删,主日志只 tail -1)。

**kill 计数(近 3 天共 15 次)**:10-05=14 次(12:25 轮 1 次:upload-etf-hist;16:51 轮 13 次:upload-etf-hist / accum-nav / industry / public-fund / etf-score / data-large / kelly-parts / kelly-parts-sdc / all-data / kelly-snapshots / feed / verify-r2 / purge-low-freq);10-06=1 次(verify-r2)。原文格式:`⚠ <通道> 停滞 300s 无日志输出, kill pid=<PID>`。

**网络抖动佐证(非 kill 本身)**:10-05 16:57:59 `SSLEOFError` 重试(两个 large-json key);10-06 15:00 schedule_monitor「R2 直连不可达(自愈类), 连续1/2, 暂不通知」→ 15:15 `[silent recovery]`。

**机制取证(读码,非执行)**:
- `scripts/r2_upload_async.sh` 66-160 行:看门狗按每通道**私有 tmp_log mtime** 停滞 ≥ `R2_UPLOAD_STALL_SECS:-300` 秒即 kill;主日志只贴 tmp_log 末行(`tail -1`)。
- `scripts/upload_r2.py` L44:`sys.stdout.reconfigure(line_buffering=True)`——**行缓冲已开,print 即 flush**⇒「缓冲导致误判停滞」假设**证伪**;300s 无 mtime 推进=进程真实无输出(16:52 轮 verify-r2 是真卡死,非误杀)。
- 梯度观察项:云上 `trade-data/.env` L33 `R2_UPLOAD_HTTP_TIMEOUT=600`(代码默认 30)⇒ 单请求 600s 超时 vs 看门狗 300s 停滞,**梯度倒置**(合法慢请求可能先被看门狗枪毙)。属设计讨论项(见 §5.2-a)。

**三问判定**:
1. 老/新:**新**(机制 10-05 11:17 上线,首日即遇网络抖动,产出 14/15 次 kill)。非历史老问题。
2. 是否已修复:机制仍在,网络差时会再冒;**已恢复事实**:10-05 21:16 轮补传 34 个无失败、10-06 18:00 轮 rc=0(补传 35 个)。判定:活体但低频。
3. 优化空间:见 §5.2(三条,全部保真故障判别维度)。

**verify-r2 每轮补传(待根因,重点)**:
- 近 3 天事实:10-04 周日全量 114 个;10-05 各轮 34/34/36;10-06 各轮 34/35/35(另见 38/8/1/0 等轮)。**命中清单高度稳定**:`signal_kelly_trades_parts/t2011-2026+recent`(17)+`signal_kelly_trades_sdc_parts/`(17)+偶发 `schedule_stats.json`=34~36 个/轮。
- **根因未定(诚实标注)**:候选方向——kelly parts 每轮 export 重写致 md5 变化 vs verify 侧比对口径(ETag vs md5)/独立链产物台账(`.r2_standalone_keys.json` 35 项,kelly parts **不在**台账)交互。**建议立项深挖**:“每轮固定补传”既是带宽浪费也是 standalone_stale 告警的常驻噪声源。
- 非 severe「standalone_stale」10-06 18:19:38 首冒(机制 #188,2026-10-05 上线):10-06 18:00 轮「补传 35 个」后触发;dedup 6h。

### 2.3 族 C:10-04 放慢日(6 条 severe)

**证据行(10-04)**:
- 03:30:07 backfill_evening 02:00 档「已运行90min(阈值4500s+缓冲15min=<03:30> 仍未完成)」;18:15:09 16:35 档「已运行100min」;22:30:12 21:00 档「已运行90min」——3 档全超时。
- 05:45:06 us_stock_morning「已运行45min(阈值1800s+缓冲10min)」。
- 20:45:17 update_all「执行耗时 10055s 超阈值 8100s last_run<17:50>」;22:30:12 update_all「超时未完成…(截断)」。
- 佐证:update_all 日志 10-04 两轮 17:50→20:37(167min)与 22:30→00:49(139min);对比 10-05/10-06 ~10min。

**三问判定**:
1. 老/新:**新(孤立日)**;10-05/06 全恢复。
2. 是否已修复:**现象已消失(10-05 起正常),根因未定**——10-04 为周日(全量 deploy+大 JSON+staticdata 备份同日落),疑似"周日全量叠加"致资源竞争,但**无直接证据,列为未定**。
3. 优化空间:先定因再谈阈值;若确为"周日全量日"结构性问题,可评估周日档独立阈值(现:update_all 8100s/backfill 4500s 统一阈值)。

### 2.4 非 severe(2 条)

- **mass_mismatch 10-04 04:07:20**(export-guard L6,10-03 上线):周日全量对账 >50 条不一致触发;deploy_20261004_0205.log L772「补传 114 个」。**N 值不可考**(详情随 tmp_log 丢失,主日志只 tail -1)——诚实标注。
- **standalone_stale 10-06 18:19:38**(#188,10-05 上线):见 §2.2。

### 2.5 老 active 残留(alert_state.json 3 条,近 3 天均 0 复燃)

| key | 首见 | last_alerted | 近3天 | 判定 |
|---|---|---|---|---|
| nextday_plan\|exit!=0|1 | — | 09-30 22:30 | 0 复燃 | 老;等下次交易日复跑更新(10-01/02/05 非交易日跳过;self_heal 每 15min `SKIP_STALE … age=139h`) |
| s06_snapshot\|exit!=0|143 | — | 09-28 23:45 | 0 复燃 | 老;静默 |
| gen_daily_brief\|R2_UPLOAD_TIMEOUT|98423251 | — | 09-28 20:45 | 0 复燃 | 老;静默 |
| etf_national_team\|exit!=0|1(active) | 09-24 | 09-28 22:30 | 0 复燃 | 老;静默 |

> 3 条 active 的「仍在 active」本身是显示状态(等下次任务跑更新);近 3 天无复燃证据。**预测**:nextday_plan 下次交易日(如 10-07)晚将复跑,届时 active 自动消解或复告警,无需现在人工干预。

## 3. 仍在冒的活体告警清单

| # | 活体 | 最近证据 | 性质 |
|---|---|---|---|
| 1 | verify-r2 每轮补传 34~36 个(kelly parts 家族) | 10-06 18:19:50 rc=0 补传 35 个 | 待根因(§2.2) |
| 2 | R2 上传链网络抖动 kill | 10-06 16:52 轮 kill 1 次(17:16 告警) | 机制性,随网络 |
| 3 | standalone_stale 告警(新机制) | 10-06 18:19:38 首冒,dedup 6h | 观察期 |
| 4 | fetch_news 锁跳过(未达阈值) | 10-06 17:45 清零未告警 | 半活体 |
| 5 | nextday_plan active 残留 | 等下次交易日复跑 | 状态性 |

**已静默(近 3 天后半段零复燃)**:mass_mismatch、purge 失败、update_all/backfill/us_stock 超时、gen_daily_brief/s06/etf_national_team 残留。

## 4. 与 #182 / #203 / #214 / #216 登记项对照

- **#182(飞书 hook 心跳云上空转)**:与本案告警无交集(那是心跳可见性议题);本次未新增证据。对照结论:无关联。
- **#203(check_failed_units timer)**:正面证据——10-06 `schedule_monitor_launchd.log` 含 `[196] CHECK_FAILED_UNITS_OK failed=0`,机制在跑且 PASS。
- **#214(mac 残留复活)**:非告警范畴,本次未涉。
- **#216(监控元盲区)**:本次排查发现 2 个同类新证据(见 §5.5):a) signal 树 latest.md 永不过期副本(09-30 22:35)误导运维;b) tmp_log 删除+主日志 tail -1 ⇒ 事后定因不可能(10-06 告警「详情: 无输出」)。建议并入 #216 问题域。

## 5. 降噪建议(全部保留真故障判别维度)

> 总原则(memory `alert-denoise-keep-fault-discriminator`):降噪不得删「真故障判别维度」;以下每条都给「降什么/留什么」。

1. **fetch_news 锁跳过**:跳过前加「等锁+短超时(如 60s)重试一次」再计轮 → 降网络抖动噪声;**保留**:连续 3 轮=上传缺口持续(现有判别不动)。
2. **R2 看门狗(机制层,建议立项)**:
   a. **停滞阈值与 HTTP 超时梯度对齐**:现 300s(停滞)< 600s(HTTP)倒置;建议停滞阈值 ≥ 单请求超时,或 verify-r2 通道用专用更长阈值(其全量对账 3 万 HEAD 天然长静默)。**保留**:KILLED 通道保留告警(#177 已做)、轻量对账静音边界。
   b. **kill 时保留定因材料**:kill 分支把 tmp_log 尾部(如 30 行)贴进主日志(当前只 tail -1,告警详情「无输出」不可定因)。**保留**:正常运行不灌主日志(降噪本意不动)。
   c. **skip/pending 锁机制**:r2_upload_async_skip.log 机制健康(1 条),维持。
3. **standalone_stale 告警文案归因**:文案「排期上传链如 s06/nextday_plan」与实际常命中(仅 kelly parts=deploy 链通道) **不匹配**——建议改文案或扩机制覆盖,防运维按错方向排查。**保留**:6h dedup 与真 stale 判别。
4. **mass_mismatch 的 N 值保留**:告警正文建议直接写入「不一致条数 N + 前若干文件名」(现在随 tmp_log 丢,只剩"补传 N 个")。**保留**:>50 阈值判别与周日全量口径。
5. **signal 树过期副本治理**:两树并存的 latest.md,建议 signal 树放 README 指针或让 rsync 同步一份(只读镜像)。**保留**:trade-data 为唯一权威。(并入 #216 域)
6. **10-04 放慢日**:现象已消失,暂不动作;若复发再定因+评估周日档阈值。**保留**:统一阈值文档注明"周日全量日例外待评估"。

## 6. 诚实标注(未知/待验证,不做过度声称)

- mass_mismatch 的**N 值不可考**(>50 已证,具体值随 tmp_log 丢失);10-06 17:16 告警「详情: 无输出」同因。
- **kelly parts 每轮补传根因未定**(候选方向见 §2.2,需立项复现)。
- **10-04 放慢日根因未定**(周日全量叠加为怀疑,非结论)。
- 300s/600s 梯度倒置已核代码,但「是否已真实误杀合法慢请求」无直接证据(10-05 kill 通道事后补跑成功),标为设计讨论项而非已证 bug。
- 「buffer 误杀」假设已**证伪**(upload_r2.py L44 行缓冲)。
- 10-03/10-04 告警中 R2 链无 kill 记录属**机制未上线**(10-04 21:51 起),非"当时无问题"。

## 7. 关键证据锚点

- `trade-data/data/alerts/latest.md` 行 232~372(近 3 天 20 条目);mtime 2026-10-06 17:16:27
- `trade-data-signal/data/alert_state.json`(active 3 条)、`notify_dedup.json`(近 3 天 2 条)
- `trade-data/data/logs/r2_upload_async_20261005_122501.log / _20261005_165149.log / _20261006_165223.log / _20261006_180044.log`(+ `r2_upload_async_skip.log` 1 条)
- `trade-data/data/logs/deploy_20261003_0205.log` L769 / `deploy_20261004_0205.log` L772
- `trade-data-signal/scripts/r2_upload_async.sh`(看门狗 66-160/通道 160-240)、`scripts/upload_r2.py` L44/L306-335/L3520-3530
- `trade-data/.env` L33(`R2_UPLOAD_HTTP_TIMEOUT=600`)
- commits:b4c5ff5ff(10-04 21:51 异步解耦上线)/ 69803a006(10-04 23:28)/ 9faf92d8e(10-05 11:17 #174 看门狗判据)/ 7c013d87e(10-06 03:36)
- `trade-data/data/logs/schedule_monitor_launchd.log`、`self_heal_audit.log`、`update_all_launchd.log`、`backfill_evening_launchd.log`
