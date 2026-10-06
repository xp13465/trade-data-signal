# #218 根因报告:R2 上传链「族 B」定性(看门狗 kill 链)+ #217④ standalone_stale 文案复核

> 日期:2026-10-06 | 角色:researcher | 类型:只读取证(未写生产/云上/R2,未跑任何业务脚本主体,未发任何通知;ssh 全部只读,本地全部只读 git/grep)
> 关联:#218(pending-index 主任务)、#217②③(告警降噪,已合 main 64597a0af)、#219(verify-r2 kelly parts)、docs/ops/alert-triage-3d-20261006.md
> 方法:本地读码(r2_upload_async.sh / upload_r2.py / schedule_monitor.sh / 各 push 链)+ 云上只读取证(journalctl、data/logs 窗口日志、state 与台账文件、git reflog)+ 本地只读 git 考古(两版本 diff)

## 0. 结论速览(TL;DR)

1. **卡段**:20 次 kill 的卡点=通道子进程启动后**首个 R2 网络请求挂死、零输出**(唯一的 journal 现场行 + 内层无任何 print;upload_r2.py L44 line_buffering=True 保证 print 必落盘,故"无 print"=未到任何 print 点=卡在最前的网络动作)。旧版 kill 后即 rm tmp_log,细节不可回溯(修复 #217③ 起改为 kill 前落尾部 30 行,见 §4)。
2. **内层参数**:s3_request/s3_head 各 5 attempts、退避 1/2/4/8s;单请求 socket 超时 R2_UPLOAD_HTTP_TIMEOUT(云上 .env=600,代码默认 30);multipart 阈值 100MB。
3. **梯度倒置确认(与 #217② 同源)**:10-05/10-06 运行时版本(signal 树 9faf92d8e,10-05 11:17)停滞判据默认 **300s** < 内层 600s ⇒ 外层杀在内层超时之前=结构性误杀诱因(修复 commit 注释自认,见 §4)。
4. **#217②③ 修复已落地代码层**:commit d714be25b(10-06 22:13,"停滞阈值梯度 / kill 前留定因材料"),已由统一入口合入 main(64597a0af,独立审 PASS 8/8);**云上 22:18:52 pull 的 00229a9b2 暂未包含,待云上下一次 pull/deploy 生效**(merge-base 实测)。
5. **kill 全量 = 20 次(非任务书/alert-triage 的 15 次;勘误见 §6)**:10-05 共 18 次(旧"超900s"判据 4 + 停滞判据 14)、10-06 共 2 次(停滞判据)。
6. **10-06 18:00 轮"静默自愈"实证**:全程无 kill、rc=0、verify 补传 35 个(网络恢复窗口)。
7. **kill 副作用链**:①tmp_log 即删→事后不可定因(修复 #217③ 已备)②marker fail-closed→下轮强制全量(实证 .r2_all_data_uploading.marker="2026-10-06T21:32:42 pid=1099943" 残留)③被杀通道不阻断后续通道,finalize 按 R2_FAIL 收 severe(16:52 轮 17:16:27 实证)。
8. **任务二(#217④)结论:该改文案**(举例与归因双错位),"撤条目"和"改判'待确认真错位'"均不采纳;条目保留(#188 机制按设计工作)。附实证:schedule_stats.json +1 的真凶=**schedule_monitor 每 15 分钟"跑前 gen"**(为读而写,设计内),且当日非交易日 intraday 全天未跑,#219 §4.2 的"intraday 链已收工"归因对当天不适用(见 §5.2)。
9. **mass_mismatch 的 N**:正文原文不可考(旧实现只打计数、不落文件名不落正文);**同轮铁证=114**(deploy_20261004_0205.log L772 "自动补传 114 个"且无 FAILED_FILES;mass dedup last_alerted=10-04 04:07:20 与之同轮;10-04=周日全量对账模式)。**口径:N≈114、>50 已证、不可逐字考。**
10. **修复预期消解量**:20 次 kill 中 4 次已由 #174 判据换代(9faf92d8e,10-05 11:17)消;剩余 16 次"停滞 300s"型将由 #217②(900+自抬)全数消除(以 kill 形式);但网络真断场景本身不消失——表现改为"内层超时/重试耗尽→通道失败→finalize severe"或 7200s 硬兜底+定因材料,**故障可见性不变、kill 噪音归零**(详见 §4.4)。

## 1. 全量 kill 时序表(20 次,逐次带证据)

证据来源:云上 journalctl(--since 10-05 00:00 --until 10-07 00:00;16 条含"停滞 300s"字样)+ 旧判据 4 条("超 900s(估算/显式)",journalctl 02:00-06:30 窗口)。

| # | 时刻(云上 CST) | 轮次 | 被杀通道 | kill pid | 判据 | 备注 |
|---|---|---|---|---|---|---|
| 1 | 10-05 03:21:07 | 10-05 02:16 轮 | upload-etf-hist | 358286 | 超900s(估算/显式,旧总时长判据) | 已随 #174 换代废弃 |
| 2 | 10-05 03:36:09 | 同轮 | upload-accum-nav | 362314 | 同上 | |
| 3 | 10-05 05:26:08 | 10-05 05:10 轮 | upload-etf-hist | 391379 | 同上 | |
| 4 | 10-05 05:41:30 | 同轮 | upload-accum-nav | 395365 | 同上 | |
| 5 | 10-05 12:32:31 | 10-05 12:25 轮 | upload-etf-hist | 508552 | 停滞 300s | 该轮 13:03:49 结束 |
| 6-18 | 10-05 16:59:19→17:59:46(13 连,~302s cadence) | 10-05 16:51 轮 | etf-hist→accum-nav→industry→public-fund→etf-score→data-large→kelly-parts→kelly-parts-sdc→all-data→kelly-snapshots→feed→verify-r2→purge-low-freq(全通道扫一遍) | 613087 / 614506 / 616093 / 617973 / 619758 / 621324 / 622995 / 624412 / 625862 / 627337 / 628769 / 630306 / 631794 | 停滞 300s | 网络约 18:00 恢复;该轮 18:35:17 结束(pending 补跑成功) |
| 19 | 10-06 17:16:09 | 10-06 16:52 轮 | verify-r2 | 1019507 | 停滞 300s | 该轮 17:16:27 结束 + severe deploy_r2_upload_fail@17:16:27 |
| 20 | 10-06 21:37:57 | 10-06 21:16 轮(unit r2-upload-211636) | upload-all-data | 1099943 | 停滞 300s | 该轮 21:45:45 Deactivated;补传 49 |

分布口径:10-05=18 次(02:16 轮 2 / 05:10 轮 2 / 12:25 轮 1 / 16:51 轮 13),10-06=2 次(16:52 轮 1 / 21:16 轮 1)。**注:10-06 18:00 轮、10-05 18:35 轮、10-06 晚其它轮均无 kill。**

关键轮次收口:
- 10-05 12:25 轮:12:32:31 kill → 13:03:49 结束;
- 10-05 16:51 轮:13 连 kill 全程 ~1 小时(16:59:19→17:59:46),13 条间隔全部 ~302-303s(=300s 判据+处理开销,与运行时版本默认 300 逐字吻合);
- 10-06 16:52 轮:verify-r2 被杀 → 17:16:27 收尾 severe(deploy_r2_upload_fail;notify_dedup.json last_alerted=2026-10-06 17:16:27 实证);
- 10-06 18:00 轮(unit r2-upload-180044):**无 kill、exit 0**(18:00:44 开始 → 18:19:50 结束;verify ✓ 补传 35;purged 124/124@18:19:50)——"静默自愈"实证;
- 10-06 21:16 轮(unit r2-upload-211636,21:16:36 由 21:05 deploy 段1 systemd-run 触发):21:37:57 kill all-data → 21:45:45 Deactivated(rc=0;补传 49)。

## 2. 卡段判定(卡在哪一段)

- **判据链(代码)**:当前 main 版 r2_upload_async.sh L112-116 注释:"主判据=停滞:日志 mtime 超 N 秒无新增输出即判死(对齐 rclone --timeout 语义)";运行时版本(9faf92d8e)L91-92 同构且默认 `_stall_secs="${R2_UPLOAD_STALL_SECS:-300}"`。kill 点=L140-142(echo "⚠ $desc 停滞 ${_stall_secs}s 无日志输出, kill pid=$pid")。
- **"无输出"的含义**:通道子进程=upload_r2.py;stdout 重定向到 tmp_log,且 upload_r2.py L44 `sys.stdout.reconfigure(line_buffering=True)`(此前"buffer 误杀"假设已证伪的同一证据)——**任何 print 立即落盘**;tmp_log 300s 内零行 ⇒ 进程未到达任何 print 点 ⇒ 卡在最前的网络动作(连接/证书/首个 HEAD/PUT 未返回)。
- **卡点归类**:**每 kill 都=“首个 R2 网络请求挂死”型**。排除"处理中静默":批量通道有 [N/M] 进度行、verify-r2 每 100 个 key 打"对账 N/N"(upload_r2.py L3529-3531),若在处理中会持续打印。
- **诚实标注**:受旧行为("kill 后 rm -f tmp_log;主日志仅 tail -1")限制,各 kill"卡在第几秒/哪个请求"不可逐次直证——本判定为"高置信推断(现场行+代码路径排除)";修复 #217③ 起 kill 前落尾部 30 行,后续此类事件可直证。

## 3. 内层重试/退避参数(代码锚点)

- **5 attempts**:upload_r2.py L533 `for attempt in range(5):`(s3_request;L513 注释"重试 5 次,SSL/连接错退避 1s/2s/4s/8s");
- **退避**:L605 / L620 `wait = 2 ** attempt  # 1s, 2s, 4s, 8s`;
- **socket 超时**:L311 `R2_UPLOAD_HTTP_TIMEOUT = int(os.environ.get("R2_UPLOAD_HTTP_TIMEOUT") or "30")`(默认 30);云上 .env 设 600;
- **multipart**:L357 `_MULTIPART_THRESHOLD = 100 * 1024 * 1024`(>100MB 走分片,对账改"存在+Content-Length");
- **外层(运行时版本 9faf92d8e)**:停滞 300s(默认;云上 .env 未覆盖)+ 低速判据(60s×5 采样,增量<1MB 且批量>10)+ 7200s 硬兜底;
- **失败通路**:通道失败 → R2_FAIL 累积 → finalize(轻量对账 verify-channels;真缺口 → severe deploy_r2_upload_fail,dedup 21600s)。

## 4. 梯度倒置与 #217② 修复(已落地,含消解量)

### 4.1 倒置事实(两版本对照,git 实证)

- 运行时版本(10-05/10-06 云上 signal 树实际执行版)=`9faf92d8e`(10-05 11:17,"fix(r2): 备份并行+减量/看门狗停滞判据/解静音 #174#176#177"):L92 `_stall_secs="${R2_UPLOAD_STALL_SECS:-300}"` ⇒ **外层 300s < 内层 600s**;
- 修复版本=`d714be25b`(10-06 22:13,"fix(alert): #217 告警降噪 ①②③(skip 等锁重试/停滞阈值梯度/kill 前留定因材料)"):
  - 停滞默认 300→**900**,并新增自抬:`_stall_secs ≤ _http_to(600) → 自动抬到 600+300=900`(打"梯度倒置"日志留痕,防回归);
  - 注释自认根因:"**旧默认 300 < 600,是 10-05/10-06 verify-r2 单通道静默被误杀诱因之一**"(d714be25b diff 逐行取证);
  - #217③:`_dump_kill_tail()` kill 前把 tmp_log 尾部 30 行落主日志 + R2_KILL_CTX 供告警正文(替换旧"kill 后 rm+tail -1"即删行为);
  - #217①:skip 等锁重试。
- **合入状态(本地只读 git 实测)**:
  - `git merge-base --is-ancestor d714be25b HEAD` → YES(本地 main 含);
  - `git branch --contains d714be25b` → main / origin/main;
  - `git log origin/main` 顶端:64597a0af "merge(feat/feat/217-alert-denoise-20261006): 统一入口合并";64d3625db "#217 已合 main 64597a0af(独立审 PASS 8/8)";
  - `git merge-base --is-ancestor d714be25b 00229a9b2` → **NO** ⇒ 云上 22:18:52 pull 的 00229a9b2(#219 的 merge)不含修复,**云上下一次 pull/deploy 同步后生效**。

### 4.2 这些 kill 是不是误杀?(性质分解)

- 4 次"超 900s(估算/显式)"(10-05 02:16/05:10 轮)=旧"总存活时长"判据产物——**该判据已由 #174 换代废弃**(9faf92d8e L66:"总存活时长判据废弃 -> 停滞判据(主)+…");属"旧世界"现象,不再复发。
- 16 次"停滞 300s"型分解——
  - **(a) 网络真断期间(10-05 16:51 轮 13 连、10-06 16:52 轮、10-06 21:16 轮)**:断网时"起跑后第一个请求无响应"完全符合停滞杀;此类杀"救活了后续通道"(避免全链被单通道拖死),但"杀早了"(不禁则内层 600s 超时会自己报错重试)——**性质=“倒置抢跑”,非“完全误伤”**;
  - **(b) 单通道静默但系统健康(如 10-05 12:25 轮 1 次)**:同理属 300s<600s 倒置下的抢先杀。
  - **⇒ "#217② 修复动机"自认语(§4.1)=官方定论:这批 verify-r2/单通道静默被杀=倒置诱因之一。**
- **10-06 18:00 轮的"自愈"说明什么**:网络恢复后同一机制全程零 kill、rc=0、verify 补传 35——**机制在健康网络上工作正常;kill 全部集中在网络故障窗**(16:5x-17:5x 连续窗、21:16 窗),即**问题=“网络抖 + 倒置抢跑”叠加,非机制常态故障**。

### 4.3 kill 副作用链

- **tmp_log 即删**(运行时版 kill 路径 rm -f tmp_log;主日志仅 tail -1)⇒ 现场证据灭失(修复 #217③ 已改制);
- **marker fail-closed**:被杀通道若处于 _incremental_upload 中,其 `.r2_<ch>_uploading.marker` 残留 ⇒ **下一轮强制全量**(安全侧设计);云上实证:`.r2_all_data_uploading.marker` 内容 "2026-10-06T21:32:42 pid=1099943"(21:16 轮被杀残留),次轮补跑前一直存在;
- **续行语义**:被杀通道不阻断后续通道(逐通道 `|| { echo 失败/超时,继续; R2_FAIL+= }`,L201 起通道簇;verify-r2 L254、purge-low-freq L257);finalize 按 R2_FAIL 判 severe(16:52 轮实证 17:16:27)。

### 4.4 若 #217② 落地,#218 预计消掉多少(任务书点名问题)

- **数字口径(20 次全量)**:4 次(旧判据)随 #174 换代已消;**剩余 16 次"停滞 300s"型 kill 预计全数消除**(以 kill 形式)——推理:修复后外层 900s(或自抬 http+300=900)> 内层最坏单请求 600s,任何"单请求挂死"都会先由内层 600s 超时→(5 次重试)接管,外层不再抢跑;
- **但不等于"故障消失"**:网络真断时表现改为"内层 5 次重试耗尽(单请求最坏 ~600s×5+退避 15s ≈ 50min/通道)→ 通道失败 → finalize severe"或"整轮 7200s 硬兜底";**告警可达性不变**(deploy_r2_upload_fail / verify 兜底补传依旧),且 #217③ 起 kill 若再发生自带尾部 30 行定因材料;
- **残余风险(预期变化)**:网络真断时单轮时长上限=7200s 硬兜底(旧行为靠 300s×N 快速包装束)——**以“延长暴露时长”换“不误杀”**,与 s06_snapshot.sh run_to 900 口径一致(修复注释自述)。

## 5. 任务二(#217④):standalone_stale 文案复核 + mass N

### 5.1 复核结论:该改文案(三选一之选)

**背景事实锁定(两源)**:
- 10-06 18:00 轮 verify 补传 35 个的完整名单(180044 主日志 verify 收尾行,upload_r2.py L3631-3632 输出格式):34 个 `data/signal_kelly_trades_parts/*` + `data/signal_kelly_trades_sdc_parts/*`(=#219 已定性的"设计内代差")+ **1 个 `data/schedule_stats.json`**;
- standalone_stale 告警(18:19:38)的名单来源 = mm_rels ∩ standalone 台账(代码 L3540-3544 `stale_standalone_names`、L3586-3601 正文含 `_fmt_name_list(stale_standalone_names)`);#219 所称"实际命中 schedule_stats.json"=该名单成员,与上一条逐字一致。

**文案与实际的三处错位(逐条证据)**:
1. **举例池错位**:文案举例"如 s06_snapshot.sh 20:35 / nextday_plan / daily_brief";而 35 项台账(.r2_standalone_keys.json)实际构成 = 6×a-stock(fapi 链 3m/6m/1y/3y/5y/all)+ overview.json + news_digest 家族 27(news_digest.json + _index + 25 日期档)+ schedule_stats.json;**s06/nextday_plan 的 key 从未入台账**(s06 自 09-30 未跑、key 不在 35 项内;nextday_plan 同理),举例与实际池零重叠;
2. **归因措辞错位**:文案"已连续失败或被截断(生成成功但 R2 没跟上)"对本例不成立——schedule_stats 当日无"失败/截断",其与 R2 的错位 = **“设计内多写点 + 上传点滞后”**(见 5.2 真凶);
3. **来源描述错位**:#219 §4.2 写"它由 intraday 链更新(每 10 分钟)"——**10-06 为非交易日,intraday_snapshot.sh 全天"1 秒跳过"**(各 run 日志实证"非交易日,跳过快照采集");当天实际更新者 = all-data(18:12)/ schedule_monitor 跑前 gen(每 15 分钟,§5.2)/ rzhb trap gen(19:15)/ push 链。

**三选一裁定:该改文案**——
- "撤条目":否决。台账机制(#188)工作正常且该 key 值得平日对账(它确实周期性 R2 滞后,兜底补传有真实价值;撤了会让"真停更"失去平日覆盖);
- "改判'确认是否有真错位'":否决(无需)。**机制已自动"确认+修复"**(verify 每次发现即补传,rc=0;此例补传成功),不存在待确认状态;
- **改文案**:保留条目、修正文案(建议稿见 §7-3:举例扩全 + 归因改写为"生成/回传解耦"双因结构)。

### 5.2 schedule_stats.json +1 的真凶链(本次新取证,证据级)

**真凶 = schedule_monitor.sh 每 15 分钟的“跑前 gen”(为读而写,设计内)**:

- **代码**(本地/云上同源,`scripts/schedule_monitor.sh` L438-446):注释原文"schedule_monitor 每15min跑,但 schedule_stats.json 只在各任务脚本结尾刷新,若任务没跑(如周末),json 滞后旧值(如 etf 143 假告警),schedule_monitor 持续读旧值误告警";L440-443"跑前调 gen_schedule_stats.py 重生成(读最新 launchd.log),保证读到当前真实状态"——`subprocess.run([sys.executable, str(REPO/"scripts"/"gen_schedule_stats.py")], capture_output=True, text=True, timeout=60)`;
- **频率**:15 分钟档(:00/:15/:30/:45;systemctl list-timers 实测,如 22:30:01 跑过、下次 22:45);
- **当日实证**:schedule_monitor_launchd.log `[2026-10-06 18:00:00]` / `[2026-10-06 18:15:02]` / `[2026-10-06 18:30:01]` 三轮连排("OK 所有任务按计划执行");
- **致命时序重叠**:all-data 18:12:34 保存 state(收录 schedule_stats rec md5=33dd8852076ae7af6c4e1662ebcec37d, size=6869)后 **约 2.5 分钟**,**18:15:02 monitor 跑前 gen 重写了 static-site/data/schedule_stats.json**(内容变、md5 变);而 verify-r2 的对账窗口 = 18:13:0x-18:19:40(**18:15 的 gen 落在窗口内**)⇒ 对 `data/schedule_stats.json` 的 HEAD 对账(本地=18:15 版 vs R2=18:12:2x 上传版)**必然不一致** ⇒ → mm_rels → standalone_stale(18:19:38)→ 自动补传(rc=0)。
- **为什么此前"写者无痕"(方法论级教训)**:①monitor 的日志是**固定名 append**(schedule_monitor_launchd.log),不产生 `xxx_YYYYMMDD_HHMM.log` 新文件 ⇒ "find -newermt 窗口"按 mtime 扫文件**永远扫不到它**;②数据文件被后续写者(18:30/18:45/19:00 monitor 轮 + 19:15 rzhb trap gen)覆写,mtime 只剩最新 ⇒ **"find mtime 窗口"只能证明"最后写不在窗口",不能证明"窗口内没写过";判"无写者"必须做日志内容级核对。**
- **旁证链(同机制的另一型)**:rzhb_backfill_20261006_1915.log 第 5 行"✓ static-site/data/schedule_stats.json (19 tasks)"出现在"=== rzhb_backfill.sh 结束(非交易日)2026-10-06 19:15:02 ==="之后 ⇒ **非交易日"1 秒跳过"型链的 trap EXIT 仍会 gen**(写 19:15:03 版;push_schedule_stats_20261006_1915.log"源 6865B mtime 19:15:03"逐字吻合)⇒ 设计上"非交易日 ≠ 不写 schedule_stats"。
- **修正 #219 §4.2**:其"生成后最后一条 intraday 轮未跟上(如 17:50 update_all 又重生成而 intraday 链已收工)"的举例对 10-06 不成立(update_all 非交易日不落数据、intraday 全天跳过;update_all_20261006_1750.log L109/L137 的 schedule_stats 行均为 check_data_integrity 只读校验);正确机理 = monitor 跑前 gen(主)+ 各链 trap gen(副)。**#219 的框架结论"属 #188 机制按设计工作、文案建议扩写"仍成立,仅"具体来源"描述需按本条修正。**

### 5.3 mass_mismatch 正文缺 N 值一事

- **N 能否补出来**:正文原文不可逐字考(旧实现只打计数不落正文;tmp_log 即删;dedup 仅存 key+时间);
- **但同轮铁证可定数**:deploy_20261004_0205.log L772 = "[verify-r2] ✓ 对账完成, 自动补传 114 个"(该轮无 FAILED_FILES)⇒ 修复成功数=114、且修复数=不一致数(全成功)⇒ **N=114(该轮)**;mass dedup `verify_r2_mass_mismatch` last_alerted=2026-10-04 04:07:20 与之同轮;10-04=周日(weekday 实算 Sunday)⇒ 该轮为"周日全量对账"模式(正文自带"若为周日全量对账设计内补传可忽略此提示");
- **结论口径**:**"N 不可逐字考,>50 已证(阈值触发);同轮修复=114、无失败记录 ⇒ N≈114(周日全量对账轮,设计内可忽略场景)"**——可在文案侧把 N 改为动态带出(L3545-3550 已有循环计数,顺手打印即可,属小改,建议随文案修改一并做)。

## 6. 勘误(2 处,均为前序材料与事实不符)

1. **"10-05 16:57:59 SSLEOFError"** → 实为 **10-06 16:57:59**,且来源 unit=`staticdata-backup-165239.service`(**staticdata 备份链** large-json 备份段),**非 r2_upload_async 链**——引用时勿归入 #218 kill 链;
2. **kill 数"15 次"** → 实为 **20 次**:缺计 10-05 02:16 轮 2 次(03:21:07 / 03:36:09,旧"超900s"判据)、10-05 05:10 轮 2 次(05:26:08 / 05:41:30,同)、10-06 21:16 轮 1 次(21:37:57,all-data;在 alert-triage 的 18:19 取证截止之后);分布 = 10-05 18 次 / 10-06 2 次(非"14/1")。

## 7. 建议与风险(每条附风险)

1. **(已就绪,待生效)#217②③ 修复同步云上**:云上下一次 pull/deploy 后即获得 d714be25b(900+自抬+kill 前 30 行)。**风险**:低;若下次同步前再遇网络抖动,kill 行为仍按旧版发生(已知、可控,不阻断)。
2. **保持 marker fail-closed(不建议改动)**:kill 后强制下轮全量=安全侧(宁全量勿漏传)。**风险**:下轮成本上升(实测为正常路径);若要"断点续传"则引入复杂度,不建议本季做。
3. **standalone_stale 文案修改(落地内容建议)**:
   - 举例改为:"如 schedule_stats(多链共享产物)、intraday 直传族、news_digest 归档、s06 快照、nextday_plan、daily_brief 等";
   - 归因改为双因结构:"这类产物存在**多个'为读/为记/为刷'的生成点**(任务链结尾 gen、schedule_monitor 跑前 gen、export 重写)而**上传点滞后**;或该链连续失败/被截断。若对账期内属前者,则本补传即设计内兜平,无需处置;请对照该产物是否有自己的链告警。"
   - 顺带:mass_mismatch / standalone_stale 正文把 N 动态带出(已可算,见 §5.3)。
   - **风险**:纯文案+展示,无行为变化;唯一注意=文案字段为硬编码字符串,改时 grep 全站同类文案(邮件+飞书+R2 三链一致,§23.10)。
4. **schedule_monitor "跑前 gen" 的降噪方案(中期可选,需单独评审)**:
   - 方案 A:monitor 的 gen 输出到临时路径读取(不覆盖产物)——**风险**:改 monitor 逻辑,需回归其全部检查项(15min 频率,回归面大);
   - 方案 B:monitor gen 后顺手 push(把"为读而写"变成正规上传点)——**风险**:15 分钟/次的推送频率过高(资源+告警面),与"低频可迟报"设计冲突;
   - **建议:短期维持现状(文案说清"设计内"),不动机制**;若要根除这类 verify 噪音,走方案 A 专项(先评审)。
5. **不建议给 schedule_stats 加"噪音豁免"**:#219 已立"必须分类降噪、绝不可整类豁免";该 key 的真停更(生成链断)仍须平日可见。**风险**:豁免=重新打开"存量缺口等周日"的盲区。
6. **告警镜像建议(小)**:standalone_stale 与 mass_mismatch 均非 severe、不镜像 latest.md(核实:notify.send 未带 --severe)——若希望 latest.md 可见,属通知面口径变更,需用户拍板。**风险**:低。

## 8. 证据索引(复核对表)

- **本地代码**:
  - `scripts/r2_upload_async.sh`:L57(R2_KILLED)/L85-87(#217③ _dump_kill_tail)/L109(mktemp tmp_log)/L112-120(停滞主判据+默认 900 修复版)/L123-124(自抬 echo)/L140-142(停滞 kill)/L161(batch 计数)/L184(tail -1)/L196-201(通道簇起点)/L254(verify-r2 7200s)/L257(purge-low-freq 900s);
  - `scripts/upload_r2.py`:L44(line_buffering)/L311(R2_UPLOAD_HTTP_TIMEOUT 默认30)/L357(_MULTIPART_THRESHOLD=100MB)/L513-533(s3_request 5 attempts)/L605,L620(wait=2**attempt)/L2103(data_dir=STATIC_DIR/data)/L2111-2157(cmd_upload_intraday;L2131 文件列表含 schedule_stats.json;L2154 _record_standalone_keys)/L2171-2231(_record_standalone_keys)/L3317-3318(all-data 通道:local_dir=lambda STATIC_DIR/data, patterns *.json, r2_prefix data)/L3499-3516(_check 本地md5 vs R2 etag)/L3538-3550(不一致自动补传)/L3561-3579(mass_mismatch>50,dedup 21600)/L3586-3604(standalone_stale,正文含 stale_standalone_names)/L3529-3531(对账进度每100key)/L3631-3632(收尾"自动补传 N 个;涉及文件名:[…]");
  - `scripts/schedule_monitor.sh`:L438-446(跑前 gen 真凶);
  - `scripts/push_schedule_stats.sh`:L47(源=static-site/data/schedule_stats.json)/L73(--skip-if-locked upload-data-files)/L75-83(rc≠0→severe schedule_stats_r2_fail 1800)/L84-88(SKIPPED_LOCKED 非成功);
  - `scripts/rzhb_backfill.sh`:L53-63(trap EXIT gen+push);
  - `scripts/gen_schedule_stats.py`:L32(util_atomic)/L991(atomic_write_json 写盘);
  - gen_schedule_stats 调用方枚举(grep,~17 脚本):各任务链结尾/trap、backfill_metrics、update_all、monitor 类等。
- **本地 git**:`d714be25b`(10-06 22:13 #217 ①②③,含停滞 300→900+自抬+_dump_kill_tail)、`9faf92d8e`(10-05 11:17 #174 判据换代,运行时版)、`64597a0af`(merge #217,审 PASS 8/8)、`00229a9b2`(merge #219;merge-base 实测**不含** d714be25b)。
- **云上(只读)**:journalctl 20 条 kill(§1 表);`data/logs/r2_upload_async_20261006_180044.log`(verify 补传 35 全名单;18:19:50 rc=0);21:16 轮(unit r2-upload-211636,21:45:45 Deactivated);`schedule_monitor_launchd.log`(18:00:00/18:15:02/18:30:01);`self_heal_launchd.log`(18:07:02/18:22:02 无需 heal);`rzhb_backfill_20261006_1915.log`(非交易日 1 秒跳过+trap gen 实证);`push_schedule_stats_20261006_1915.log`(源 6865B mtime 19:15:03);`deploy_20261004_0205.log` L762(旧判据 kill 文本)+L772(补传 114);`data/.r2_all_data_state.json`(updated_at 18:12:34;changed 含 schedule_stats;rec md5=33dd88…/size 6869);`data/.r2_standalone_keys.json`(35 项);`data/.r2_all_data_uploading.marker`("2026-10-06T21:32:42 pid=1099943");`data/notify_dedup.json`(deploy_r2_upload_fail last=10-06 17:16:27;无 r2_unreachable 条目;mass last=10-04 04:07:20);两树 schedule_stats 现状(trade-data/static-site/data:6865B mtime 22:30:03 md5 25070e69…;signal 树:6868B mtime 21:15:01 md5 c09f851b…;trade-data/data/schedule_stats.json 不存在);signal git reflog(17:00:24 / 18:18:37 / 22:18:52 pull)。
- **时点辅助**:10-04=Sunday(周日全量对账)/ 10-05=Monday / 10-06=Tuesday(weekday 实算)。

---
> 报告完 | researcher 只读产出,落档供主控验收;提交/合并由主控决定;两处勘误以 §6 为准。
