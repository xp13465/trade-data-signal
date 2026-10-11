# B4① 云上/R2 只读核查批报告(2026-10-11)

- **任务**:`docs/ops/next-steps-plan-20261011.md` §1 B4①(九项:清欠账 + 喂拍板 D8/D9)
- **纪律**:只读(本报告除外);无 commit / 无 push / 无切分支;R2 仅 LIST(未 GET 对象体,未写);未执行任何 find /;无残留后台任务("moved to the background" 全程未出现)
- **ssh 规范**:`ssh -i /Users/linhuichen/tdsignal.pem -4 -o ConnectTimeout=10 -o ServerAliveInterval=5 -o ServerAliveCountMax=3 ubuntu@122.51.111.173 'xxx'`(命令内无 `$` 变量)
- **R2 工具**:`scripts/r2_list_prefix.py`(只读 LIST,凭据读 repo/.env)
- **云上关键基线**:cloud HEAD `f93de7713`;cloud repo `/home/ubuntu/code/trade-data-signal`;数据/运行目录 `/home/ubuntu/code/trade-data`

---

## 1. #221 recent2.json 两处登记矛盾(存疑核实)

**结论:实物仍在位 ⇒ pending-index #221 行「仍待按 §25 清理,未执行」对;#234 尾注「#221 recent2.json …均闭环」不实。标题日期「2026-08-29」与正文/实物的 09-22 不符,以 09-22 为准。**

证据点:
1. R2 主桶 LIST `data/signal_kelly_trades_parts/` 共 **18 对象**,含 `recent2.json`,**17,881,308 B**,LastModified **2026-09-22T04:13:33Z**(命令:`.venv/bin/python scripts/r2_list_prefix.py signal-data data/signal_kelly_trades_parts/ /tmp/b4a/parts.json`;18 = 17 个 trade×档 + recent2,与 #219 复核记的「主桶 NDO parts 18」互证)
2. 本机镜像 `static-site/data/signal_kelly_trades_parts/recent2.json` 同尺寸 17,881,308 B,mtime 09-22 11:27(北京)⇒ 从未被后续 deploy 覆盖,也无「已删」迹象
3. 云上 `/home/ubuntu/code/trade-data/static-site/data/signal_kelly_trades_parts/` **无** recent2.json(云上镜像 17 份)⇒ 该文件只在「R2 + 本机镜像」两处,deploy 不推它(deploy 从 static-site 推送,本机镜像有则会被推)⇒ 唯一权威判据 = R2 对象是否在,答:**在**
4. 归口建议:#234 尾「均闭环」加订正注;#221 标题改 09-22;两项合并(均指向同一对象)→ 仍待 §25 清理执行(清理前须备份 + 写恢复路径)

## 2. #185④ + #186 legacy 清零复核

**结论:PASS。老桶 `large-json/` 日期目录式 legacy 命中 0;#186 A 档前缀全 0;D 档 flat 31,673 仍在位(唯一副本,严禁配删除规则),与「B/D 交 lifecycle」口径一致。**

证据点:
1. 老桶 `signal-backup` LIST `large-json/` = **31,673 对象 / 433.4 MiB**,全部为 flat 固定前缀(**flat 计 31,673**;legacy 计 **0**)⇒ #186 C 档 27,673 个日期目录式对象**已清零确认**
2. A 档复核(主桶 `signal-data`,逐前缀 LIST):`probe/`、`test/`、`r2test/`、`industry-`、`sss.jpg`、`overview.json.gz` **各 0 对象** ⇒ 清零确认
3. 与独立来源互证:restore 侧审查记录 `large-json/` 两桶 key 集 **31,673 == 31,673,差集空**
4. 老桶其余前缀现值(pre-upload 6,308 / weekly 6 / monthly 8 / claude-backup 24 / large-json 31,673 / backup 16 / decommissioned 2 / mac-backups 1)与 #186 记账一致

## 3. #239 首夜误杀数据 + 可机检化点

**结论:修复已上云;首夜(10-09 17:08 → 10-11 05:11,16 轮实例)「停滞 900s」kill = 0 次(基线 = 10-09 00:22 事故实例 1 次,修复前)。诚实标注:「归零」成立但「机制被实战验证」不成立——窗口内心跳行在生产日志不可观测(0 命中),0 次 kill 也可能是 0 次长等锁。**

证据点:
1. 云上 HEAD `f93de7713`(含心跳修复);**三脚本 md5 与本机 main 逐位一致**(`upload_r2.py` / `r2_upload_async.sh` / `schedule_monitor.sh`)
2. 云上 `upload_r2.py` 含 `_R2_LOCK_HEARTBEAT_SECS = 30`(L3951)+ 排队分支心跳输出(L4054-4060)
3. 云上 `data/logs/r2_upload_async_*.log` 32 份(窗口自 10-05 起)逐份 grep「停滞 900s」:仅 `r2_upload_async_20261009_002208.log` = **1 次**(修前事故本尊);**10-09 17:08 起 16 轮全 0**
4. 窗口内锁争用确在发生:实例级 skip 3 次(10-09 18:51 / 20:29 / 22:08,`r2_upload_async_skip.log`);push_schedule_stats「已等锁重试」出现在 10-09 19:15 / 20:19 / 21:41 / 21:58 + 10-11 05:11 ⇒ 压力在,但无逃生记录可读
5. 可观测性缺口实证:10-11 日志 grep「等待 R2 上传锁」= **0 命中**(心跳落 tmp_log 只用于刷 mtime;成功轮 `tail -1` 只留最后一行,tmp_log 即删 ⇒ 心跳行被丢)

**可机检化点(草案,回 D 待拍)**:
- ① 静态梯度断言:heartbeat(30) ≤ stall(900) 且 stall > `R2_UPLOAD_HTTP_TIMEOUT`(600) — 现仅注释说明,挂 CI/机检脚本断言两个常数关系(防未来单边调参致梯度倒挂)
- ② 排队分支全覆盖断言:凡走 `run_r2_upload` 等锁队列的通道,必须命中心跳分支(防未来新增通道漏抄)
- ③ 运行时可观测性(最关键):长耗时(接近 stall)未 kill 的轮次必须能证明心跳出现过 — 方案:心跳行同时落一份留存文件,或成功轮保留 tmp_log 供抽样;否则「没等到锁」与「等到但靠心跳逃生」永远不可区分
- ④ 每日汇总指标:`kill=0` 之外加「等锁发生次数 / 最长等锁时长」两项,从③的留存日志统计

## 4. #198·#200·#202 到期观察回填

### #198 三项观察点 —— **PASS(全闭环)**
1. **claude-backup 已切新桶 + 首跑实证**:新桶 `signal-backup2` 有 6 个 `claude-self-20261006..20261011.tar.gz`,10-06 → 10-11 每日 03:17(北京)连续;老桶 claude-backup 最后 = 10-04T19:17Z(=10-05 03:17 北京,切桶前最后一笔),之后 0 新增
2. **mac-backups 双侧各一份**:老桶 1 个 + 新桶 1 个(同 key 同尺寸 2,278,230,346 B,10-07T15:18Z 副本);两侧均**无**删除规则(刻意保留,与 #179 决定一致)
3. **pre-upload 已切新桶**:新桶 4,708 对象 / 1,735.1 MiB,最早 10-10T08:52Z;老桶最后 10-05T04:55Z(=10-05 12:55 北京)。⚠ **10-05 → 10-10 两桶皆零新增**,归因 #237 跨账号 CopyObject 100% 失败(pre-upload 护栏只记日志不告警);**10-10 relay 上线后恢复**;老桶存量 6,308 / 2,571.9 MiB 由 7 天规则自然排空
- 观察结论:切桶切换(10-05)与 relay 补链(10-10)两段都已实证,无残留断点

### #200(节后首交易日资金流)—— **PASS**
1. 10-01 ~ 10-10 全部 update_all 日志「rsync 同步失败」计数 = **0**(逐份 grep)
2. 10-08(节后首个交易日)17:50 fund_score 上传 **2/2 成功**;该日志无 SEVERE / 无 `[issue]`
3. ⇒ 修后无复发,观察点关闭

### #202(S03 静默单点告警)—— **PASS**
1. `trade-schedule-monitor` journal 自 10-09 起无 patrol / `_cfu_key` 相关 critical 行;10-11 08:27 巡检 **rc=0**;latest.md 中 patrol 命中 **0**
2. 诚实标注:latest.md 近两日两条 severe(10-09 23:30「unit 巡检发现异常」/ 10-10 08:27「unit 与仓库快照漂移」)来源是 `cloud_unit_patrol` 家族(#191/#248),**非** #202 的 schedule_monitor patrol 项,不混算

## 5. #124 冻结表 timer 挂载现状

**结论:未挂载(维持现状),等用户拍板。脚本在位、全仓零引用、云上零挂载点。**

证据点:
1. 云上 `/etc/systemd/system` 全目录 grep `signal_kelly_freeze_cleanup` = **0 命中**;`crontab -l` = 0 命中;`/etc/cron.d/` 仅系统默认三项(e2scrub_all / sgagenttask / yunjing);56 个 timer 清单无 freeze / orphan 相关
2. 脚本在位:云上 `scripts/signal_kelly_freeze_cleanup.py`(7,561 B,10-01 落档)
3. 全仓引用面 = 零(不会被 deploy / update_all 链意外调用)
4. 拍板点不变:是否挂 timer(脚本自身已含 dry-run 默认 + 15 天冷却 + 漂移豁免 + 备份回退);附带待办 = docstring 措辞误导项(review caveat 2)待修

## 6. #231 链路现状(D8 前置)

**结论:cmd_upload 静默失败现网未修(失败仍 exit 0);定时调用 = intraday-snapshot 30 槽,调用方有 stdout「✓」补偿检测(落 collect_log error),但全仓无任何告警消费者 ⇒ 单点告警覆盖 = 缺(只剩 UI 数据健康度)。残余静默窗 = sentiment-3y/5y/all。**

证据点:
1. `upload_r2.py` L768-774(`cmd_upload`):失败分支只 `print(f"✗ status=...")`,**无 `sys.exit(1)`**;分发处 `elif cmd == "upload": cmd_upload(...)`(L4103-4104)⇒ 失败退出码 = 0(**现网现状,未修**)
2. 定时调用链:`trade-intraday-snapshot.timer` 云上 **30 个 OnCalendar 槽**(09:25..15:35 + 15:35 + 20:35,unit 已核);`app/collector/intraday_snapshot.py::_export_affected_json`(L2152-2175,主流程 L2631 调)对 6 个 `EXPORT_RANGES` 各起子进程:`upload_r2.py upload <local> data/sentiment-{rng}.json`(timeout=60)
3. 调用方补偿判据:`_r.returncode == 0 and "✓" in _r.stdout`;失败 → `log_collect(..., "sentiment_r2_upload", "error")`(L2173 / L2178)
4. 消费者盘点:`sentiment_r2_upload` 全仓**仅 intraday_snapshot.py 一个写入点**(grep 命中仅此文件 + 1 处 worktree 副本),**无 monitor / 告警读取方**;UI 由 collect_log → `queries.py` 数据健康度呈现 ⇒ #231 记的「只有 UI 小红点,monitor 十维均不覆盖」**现状成立**
5. 10-09 生产样本:逐轮日志 `[intraday] sentiment R2上传 6/6`(6/6 全成功)
6. 残余静默窗:`sentiment-3m/6m/1y` 另经 `intraday_snapshot.sh` 的 upload-intraday 通道(失败走 SEVERE + dedup 1800s,已覆盖);**`sentiment-3y/5y/all` 只走上述静默单点路径**(upload-intraday 文件清单只含 3m/6m/1y)

**纳入统一告警的要点(4 条,喂 D8)**:
- ① 最省接入点(推荐):`intraday_snapshot.sh` 收尾解析 python 侧 stdout 记号 `[intraday] sentiment R2上传 x/y`,`x<y → notify --severe`(与同脚本既有 3 条 SEVERE 模板同构,见 L157/L170/L232)
- ② 备选:新增 schedule_monitor 维度消费 collect_log 的 `sentiment_r2_upload` error 行(改动面更大,与 UI 读取同源)
- ③ 若改 `cmd_upload` 让失败 exit≠0:**必须先穷举该命令的全部调用方**(同一 `upload` 子命令还被其他路径使用),防回归
- ④ 去重与验收:沿用 `--dedup-key` / `--dedup-window 1800` 同窗口;干跑负控(把 R2 key 改不存在)证明告警会发 + 正常轮零新增

## 7. TASKS-L195 fetch_news 对账(#245 批2 L3c 是否已覆盖周日夜 SEVERE)

**结论:已覆盖(机制级),建议销项。诚实标注:部署(10-10)后尚无修复后周日实测样本,今晚 10-11(周日)为最近自然观察窗。**

证据点:
1. L3c 已在线上:`schedule_monitor.sh` L621 起:`R2_SKIP_TRANSIENT_TASKS=("gen_daily_brief","fetch_news")`(L628)、`R2_SKIP_ESCALATE_ROUNDS=6`(L631);自愈类连续 3~5 轮 → `--tier warning` 入 30min 缓冲聚合,≥6 轮才升级 SEVERE;非自愈类逐字节不变。已合 main `18149cd69`(10-10)+ 云上同步
2. 叠加 10-09 #181race 轮去重(按 `r2_round_id` 去幻影 +1,L1156-1170):原「周日夜 SEVERE」场景实为 counted=3 / distinctRounds=2
3. 按新口径复算该场景:实际轮数 ≈2(<3)⇒ 连告警都不发;3~5 轮 ⇒ warning;只有 ≥6 连续轮(≈90min 锁忙)才 SEVERE ⇒ **原周日夜 SEVERE 在新机制下不可达**
4. 生产痕迹:latest.md 显示 fetch_news 的 `<r2_skip_continuous>` 关键词「首次发现 2026-09-24 12:00:01 → **恢复 2026-10-11 05:00:00**」(17 天常驻 active 链已闭环);`warning_buffer.jsonl` / latest.md 中「自愈类」命中 0 ⇒ L3c 新 warning 分支**尚无生产样本**
5. 销项建议:closed「fetch_news 周日夜 SEVERE 是否接受」未决项;保留一次观察(今晚 10-11 周日 / 最迟 10-18 周日)对照 L2 实跑,若出现新样本应表现为 warning 聚合或静默,而非 SEVERE

## 8. 登记待决① rzhb 漂移(D9 二选一事实依据)

**结论:云上 timer 实有 08:00 + 19:15 两槽;登记表与代码只登 08:00 ⇒ 事实依据倾向「删云上 19:15 槽」(与代码/登记对齐;保留则每天多跑一轮设计上无产出的采集,且槽位核对持续漂移)。**

证据点:
1. 云上 unit 原文 `/etc/systemd/system/trade-rzhb-backfill.timer`:`OnCalendar` = `*-*-* 08:00:00` **和** `*-*-* 19:15:00`(Persistent=true)
2. 登记表:`schedule_monitor.sh` L129-131 rzhb_backfill `"schedules": ["08:00"]`;代码注释 `rzhb_backfill.sh` L6-9:2026-07-29 起源 = 「SSE 官方 T+1 早晨发布 T 日数据,**19:15 连续采不到 T 日**」⇒ 19:15 属历史遗留槽
3. journal 实证 19:15 槽每天真跑:10-09 起跑 63s / 10-10 4s;08:00 槽 4~5s;10-11 08:00 与 10-10 19:15 正文显示「非交易日,跳过两融采集」/ 仅 push schedule_stats
4. 删前建议(写动作,不在本批):看一眼 10-09 19:15 那轮 63s 的日志正文,确认无实质动作后再删;删除 = 改 unit + `daemon-reload`(root)

## 9. 老桶 backup/ lifecycle 14 vs 30 天

**结论:14 天生效(#169 记的 10-04「30 天」读数作废)。memory `r2-backup-bucket-second-account` 的「老桶只有 backup/ 一条规则 + 14vs30 未决」= #179 配置前快照,已过时,建议订正。**

证据点:
1. 实测:老桶 `backup/` 现存 **16 对象**,日期 09-27T13:01Z → 10-04T13:08Z(2/天),最老 ≈13.5 天龄(未到 14 天,尚未被清)
2. **反证 30 天**:代码清链自 10-05 切新桶后不再触老桶,其后仅 lifecycle 能删;09-21 ~ 09-26 的对象(切桶时 8~13 天龄、逃过代码 14 天清链)现在**全不在位** — 若规则是 30 天它们今天应仍在 ⇒ **30 天被否,14 天成立**
3. 交叉佐证(同桶各前缀均见各自规则生效):pre-upload 最老 10-04(7 天规则)、weekly 最老 09-14(28 天)、claude-backup 最老 09-11(30 天)、monthly 最老 07-21(365 天,未删)、decommissioned / mac-backups 无规则(09-03 / 10-04 存量在位)⇒ 与 #179 五规则一致
4. API 侧:两桶 `GET /?lifecycle` 均 **403 AccessDenied**(老账号 + 新账号凭据都试)⇒ 我方查不了,结论靠「对象年龄分布」实测;建议用户 dashboard 再核一眼把 14 钉死
5. memory 裁定:`r2-lifecycle-age-based-existing-objects`(#179 五规则 + 按对象年龄算)与实测一致,对

---

## 附:顺带新发现(必报)

### P0:周日 verify-r2 全量对账崩溃(UnboundLocalError)

- **现象**:今天(10-11,周日)两次生产实例(02:16 / 05:11)日志末行 `UnboundLocalError: cannot access local variable 'standalone_files'`;历史日志窗口(自 10-05 起 32 份)仅 10-11 命中
- **根因**:`upload_r2.py::cmd_verify_r2` — `full = today_weekday == 6`(L3610-3611);`if full:` 分支只赋 `to_check`(L3640-3641),`standalone_files` **仅 else 分支**赋值(L3665);而 L3730 `_std_set = {str(f.relative_to(local_dir)) for f in standalone_files}` **无条件使用** ⇒ 周日 full 模式 + 任一通道有不一致 ⇒ 崩
- **静态证据**:AST 复核 — `if full:` body 赋值名 = ['to_check'];`standalone_files` 出现行 [3665, 3667, 3677, 3682, 3683, 3730],其中 3730 在 `if mismatches:`(非 full/else 分支)内;引入 commit `09338aa0f`(#188,2026-10-05)
- **影响**:周日层3 全量对账中断(**自动补传不执行**)→ 轻量对账(verify-channels)rc=1 发现缺口 → 04:27:55 SEVERE「R2上传失败」已发(邮件+飞书);05:11 轮被 6h dedup 抑制;**今晚(10-11 周日)22:30 #220 force_full 首实战若仍撞周日 full 会重复崩溃**
- **建议**:立即派 implementer 修(2~6 行:full 分支补 `standalone_files = []` 或把 L3730 使用点收进 else;`_std_set` 可 `set()` 兜底)+ 重跑一次周日 full 验证;顺带处理「verify-r2 失败只留 tail -1」致 traceback 不可见的可见性问题

### 其他
- 云上 failed unit = `trade-nextday-gap-check.service`(latest.md 连续 4 天升级 critical,= #246 在册项,处置见 #248 链)
- 10-10 08:27「unit 与仓库快照漂移」告警:仓库侧 `f93de7713` 已对齐(本批只读复核 md5 一致范围内),云上侧复核归 #248 链

## 遗留(转 D/下批)

1. #221:仍待 §25 清理执行(先备份+恢复路径);#234 尾注需订正
2. #239:可机检化 4 点待 D 拍(尤其③运行时可观测性)
3. #231:D8 四要点已列,待拍实施方式
4. rzhb:D9 事实依据已给(倾向删 19:15),待拍
5. lifecycle:14 天结论 + memory `r2-backup-bucket-second-account` 订正建议(含 #169 读数作废标注)
6. verify-r2 周日崩溃:新 P0,建议不等 D、立即派修
