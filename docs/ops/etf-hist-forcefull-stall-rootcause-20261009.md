# #239 etf-hist 通道「force_full 卡死」定因报告(2026-10-09)

> 角色:调研 agent(只读定因;未改任何业务代码/脚本/配置,未 commit/push)
> 关联:docs/ops/data-lag-audit-20261008.md §7.1/§7.5、#217②、#149、memory `agent-silent-death-pgrep-unreliable`
> 报告本体 + 复现段(复现含本机实测锚点)

## 0. 一句话结论

**etf-hist 不是「force_full 模式卡死」,而是「三链并发下通道子进程在第一步(拿锁)撞上长持锁者」。**
通道进程在 `upload_r2.py` 入口统一互斥锁处(`L3980-3981`)撞上已持锁的 `upload-large-json`,
进入**设计即静默**的排队循环(`L3925-3951`,整个排队分支除 `time.sleep(2)` 外零输出);
外层看门狗(`r2_upload_async.sh L139`)只认「tmp_log 900s 无输出」,不知道锁等待是合法静默,
把一个本可正常完成的进程 kill 了。PUT 零执行 / tmp_log 全空 / marker 无残留 / wchan=hrtimer_nanosleep /
rchar 冻结 —— 全部是「拿锁先于一切业务动作 + 排队静默」的结构性必然,**与 force_full 模式无关**。

## 1. 症状与事实基线

事故进程(#7.1 采样记录):
- etf-hist 通道子进程 pid=1928109,900s 无 IO/无输出被看门狗 kill,**PUT 零执行、tmp_log 全空**;
- 进程采样:`rchar` 固定 1,907,668 不动、`wchar=0`、`wchan=hrtimer_nanosleep`、0 网络连接;
- `r2_upload_async_20261009_002208.log` kill 行原样:
  `⚠ upload-etf-hist 停滞 900s 无日志输出, kill pid=1928109` + `(tmp_log 无任何输出——进程启动即无日志/缓冲未刷)`;
- `.r2_etf_hist_uploading.marker` **无残留**;`.r2_etf_hist_state.json` 已被后续轮回写(无 00:2x 痕迹);
- 用户可见影响:**无**。101 个缺口(2 个 index + ~98 个 etf/*-all.json + 1 个 nav_bucket,见下)已被同轮 verify-r2 层 3 对账自动补传(00:49~01:12),
  复验:`curl -sI https://ssd.fx8.store/nav_bucket/2c.json` → HTTP 200,`last-modified: Thu, 08 Oct 2026 17:10 GMT`(=北京 10-09 01:10,落在补传窗内)。

## 2. 根因链与完整时间线

三条链并发 + 一把全局锁 + 一个「静默是合法态」的看门狗:

| 时刻(北京) | 事件 | 证据 |
|---|---|---|
| 10-08 深夜~00:13 | deploy_0013 段1 跑(10-08 数据补齐链) | `data/logs/deploy_20261009_0013.log` |
| 00:13:54 | deploy_0013 段1 尾段到达「触发 R2 上传」点 | 同上(deploy 链 R2 异步触发段,deploy.sh L574-604) |
| **00:22:08** | **A 实例启动**:systemd unit `r2-upload-002208.service`(名字即时戳),由 deploy_0013 段1 触发;同一触发点另有一次重复创建被拒(`Unit r2-upload-002208.service already exists`,rc=1 → `r2_upload_trigger_fail` 误报告警「需手动补跑」,实际 unit 正在跑) | `deploy_20261009_0013.log L1472-1490`(「Failed to start … already exists」+「Running as unit: r2-upload-002208.service」+ 告警四连) |
| 00:22:08~00:22:5x | A 实例通道 1-4 顺序完成:**lab(0.3s)→ trade-sim(0.7s)→ trade-sim-json(未变化)→ index(上传 158 keys)** | `r2_upload_async_20261009_002208.log` kill 行前恰 4 行 tail(`tail -1` 语义 `r2_upload_async.sh L184`);158 = index 目录 173 个 json 中本次变化的 158 个 |
| **~00:22:50** | **`upload-large-json`(staticdata backup step3.5b)取得主锁** | `staticdata_backup_async_20261009_002224.log`:`[step3.5 large-json 排除+R2] 1155s`、`段2 start 00:42:05` ⇒ 00:22:50~00:42:05 持锁 1155s(内含 108.3s 纯本地指纹扫描) |
| **~00:22:5x** | **etf-hist 通道(通道 5)启动 → 撞锁 → 静默 sleep(2) 排队** | A 实例日志 kill 行位置=通道 5;等待期零输出(marker 写于 L1394-1396,未残留 ⇒ 未过锁) |
| 00:22:24 | `staticdata_backup_async_002224` 段1 启动(trigger=etf-national-team,by etf_nt backfill 链) | 上述日志首行 |
| 00:22:25~00:23:25 | **独立互证**:push_schedule_stats 走 `--skip-if-locked` 60s 窗口**全忙**→ SKIPPED_LOCKED | `etf_national_team_heal.log L13072-13077`;`data/logs/etf_national_team_heal.log` |
| **~00:37:5x** | **看门狗 900s 停滞判据 kill etf-hist(pid 1928109)**,tmp_log 空 | A 实例日志 kill 行;`r2_upload_async.sh L139-148` |
| 00:42:05~00:42:23 | 主锁释放(staticdata 段2 start)→ backup 完成 | staticdata 日志 |
| 00:42:05 后 | A 实例通道 6-15(accum-nav 1600 keys / industry 133 / … / feed 1)顺序完成 | A 实例日志 kill 后 10 行 tail(15 数据通道逐一对齐) |
| 00:49:10 | 另一 r2_upload_async 实例被跳过(写 pending marker) | `r2_upload_async_skip.log` |
| 00:49~01:12 | verify-r2 对账完成,**自动补传 101 个** | A 实例日志 `[verify-r2] ✓ 对账完成, 自动补传 101 个` |
| 01:12:07 | 告警(邮件/飞书)`[告警] [cloud] R2上传失败` | A 实例日志 notify 段 |
| 01:13:32 | A 实例结束(含 pending 补跑轮)exit 0 | A 实例日志尾行 |

（附图:锁时间轴）
```
主锁 /tmp/trade_r2_upload.lock 占用:
00:22:1x        index 通道(上传 158 keys)         |  push_schedule_stats 60s 窗口:
00:22:52        upload-large-json(1155s)         |  00:22:25 ────────────────► 00:23:25 全忙
00:42:05        (释放;后续通道 6-15 排队取得)     |  ⇒ 与左列无缝衔接,60s 内从未抢到
etf-hist: 00:22:5x 启动 → 等锁 → 00:37:5x 被 900s 停滞判据 kill(PUT 0,marker 0)
```

## 3. 代码级定位(为什么必然零输出)

1. **拿锁是进程的第一步业务动作**:`upload_r2.py L3980-3981` —— 除 `list/delete/download-db/clean-data-backup/upload` 五个豁免命令外,
   所有 `upload-*/verify-*/purge-*` 在 **dispatch 之前**先调 `_acquire_r2_upload_lock(skip_if_locked=...)`;
   L44 `sys.stdout.reconfigure(line_buffering=True)` ⇒ **tmp_log 全空 = 从未到达任何 print**(包括 L1315「模式=…」)。
2. **排队分支设计即静默**:`_acquire_r2_upload_lock` L3925-3951 ——
   ```python
   while True:
       try:
           fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB); return fd
       except OSError:
           ...
           if time.time() >= deadline:   # deadline = now + R2_UPLOAD_LOCK_TIMEOUT(默认 7300s)
               print(...排队等待超 {timeout}s 仍被占用...); sys.exit(1)
           time.sleep(2)                 # ← 排队期唯一动作; 零 print/零 IO
   ```
   ⇒ 只要没到 7300s,**stdout/stderr 全程为空**;无 socket、无文件读、进程 99% 时间在 nanosleep —
   **与五项采样(rchar 冻结 / wchar=0 / wchan=hrtimer_nanosleep / 0 网络连接 / 零输出)逐项吻合**。
3. **marker 语义闭环**:marker 写于 `L1394-1396`(**锁获取之后**、PUT 之前);被 kill 时 marker 无残留 ⇒ 进程未取得锁。
   （fail-closed 设计:marker 残留才触发下轮全量;本次无残留,故不存在「kill→全量→再撞锁」死循环。）
4. **看门狗盲区**:`r2_upload_async.sh L110-148` 判停 = tmp_log mtime 900s 不更新(L120,`R2_UPLOAD_STALL_SECS` 默认 900),
   该判据**对「锁等待」这一类合法静默无感知**;#217②(L112-125)修的梯度是「停滞阈值 > 内层单请求 HTTP 超时(600s)」,
   而**锁等待不在 HTTP 超时保护伞内**(纯本地 flock 轮询,上限 7300s)⇒ 梯度第三级未覆盖。
5. 设计文档自身的盲区(docstring L3871/3878-3879 逐字):「正常等待时间 = 前一个上传通道实际耗时(有界)」、
   「deploy 持锁时长受其看门狗 kill 约束,**实测远小于对应上限**」—— 该假设对 deploy 链小通道成立,
   但对 `upload-large-json`(26~105min 级)与 `upload-fund-nav`(10-08 实测 4089.8s≈68min,见 §5-D)失效 ⇒ **长持锁者存在时,等锁方必超外层停滞阈值**。

## 4. 「force_full」措辞更正(防后续审计被误导)

- 审计报告「卡死轮为 force_full 模式」的来源 = `upload_r2.py L3826-3828` **硬编码字符串**:
  `通道 {desc} 本轮被看门狗超时 kill(force_full 未完成, PUT 未执行), 不适用轻量对账静音, 保留告警` ——
  该文案对**任何**被 kill 通道都原样输出,与真实模式无关(代码里 `killed` 集合只来自 `R2_KILLED` env)。
- 反证三连:① tmp_log 全空 ⇒ `L1315` 的模式行从未打印,「force_full」无从谈起;
  ② marker 无残留 ⇒ 未过 L1395;③ 后续轮(05:11 等)etf-hist 增量行为正常(05:14:51 state),无死循环。
- 正确表述:**任何模式(含纯增量)只要撞上长持锁者,都会被同样的机制杀**;模式不是变量,锁竞争才是。

## 5. 同族面清单(§23.3 举一反三)

**A 类:被误杀型(静默等锁 × 外层停滞/时长 kill)——「同一 bug 的未修面」**
| 面 | 位置 | killer 形态 |
|---|---|---|
| r2_upload_async.sh 全部 **15 个数据通道** | L201-226(`run_r2_upload`,停滞判据 900/1800s) | tmp_log 停滞 kill(本次受害者) |
| s06_snapshot.sh upload-data-files / upload-kelly-snapshots | L133 / L161(`run_to 900`) | **总时长 timeout 900s**(L42-55 三平台包装) |
| turnover_backfill.sh upload-intraday / upload-data-large | L145 / L148(`run_to 900`) | 同上 |

**B 类:静默等锁、无外层 killer(不 kill,但卡链最长 7300s、日志静默、拖下游)**
- `etf_national_team_backfill.sh:112`(upload-etf-hist 直调,tee 无超时)
- `update_all.sh L206/L245`(upload-etf-score / upload-fund-score,>> LOG,无 run_to)
- `gold_night.sh L65/L69`、`kelly_intraday_rerun.sh:127`、`backup_db.sh:94`、`pf_score_daily.sh:46`/`pf_score_weekly.sh:46`、`update_lab.sh L294/311/328`、`fund_nav_upload_async.sh:38`、`staticdata_backup_async.sh:194`(upload-large-json 自身也是等锁者)
- （判定依据:均未带 `--skip-if-locked`,排队语义 L3960-3967）

**C 类:安全降级型(已有 --skip-if-locked,60s 有界 + SKIPPED_LOCKED 不挂死)**
- `intraday_snapshot.sh L150/157/170/180/232`、`push_schedule_stats.sh:73`(事故当夜 60s 全忙 SKIPPED_LOCKED 即此形态)

**D 类:长持锁者清单(误杀触发的根上竞争源)**
| 持锁者 | 实测持锁时长 | 证据 |
|---|---|---|
| `upload-large-json`(step3.5b)| 26~105min(历史);10-09 夜 1155s | staticdata_backup_async.sh L63 注释 + `staticdata_backup_async_20261009_002224.log` |
| `upload-fund-nav` | **4089.8s≈68min**(10-08) | `fund_nav_upload_async_20261008_182838.log`(255/256 桶跨境) |
| verify-r2 / upload-trade-sim-json(1800s 档)/ upload-db / upload-claude-backup | 分钟~20min 级 | r2_upload_async.sh 通道表 + 各自脚本 |

**E 类:附带发现(非本次卡死,但同源)**
- fund-nav 10-08 轮:255/256 上传、单文件 `2c.json` FAILED_FILES rc=1、marker 残留(`.r2_fund_nav_uploading.marker` pid=1811294, 2026-10-08T18:28:39);
  **2c.json 已由同夜 verify-r2 补传**(线上 Last-Modified 10-09 01:10 北京,推断为 101 补传之一);
  注意:marker 残留 ⇒ 下一轮 fund-nav 将按 fail-closed 强制全量重传 256 桶(~68min 级),将再次长占主锁 —— 与 §7-③ 协同治理。
- `deploy_0013` 的重复触发告警(`r2_upload_trigger_fail`「需手动补跑」在 unit 已在跑时误报)属降噪观察项。
- export-guard L2(`upload_r2.py L83-128`)提示文案「本机如需验证隔离请用 R2_BACKUP_BUCKET=…」与实际判定不符:
  L118-128 对 darwin 上任何公桶写命令**无条件 exit 2**(R2_BACKUP_BUCKET 不参与该判定)⇒ 文案误导,复现只能走函数级(见 §6)。

## 6. 复现段

**复现一:本机函数级最小复现(已实测;零网络、零 R2 写)**
> 因 export-guard L2 拦 darwin 公桶写命令(exit 2),复现走「只 import 模块、只调拿锁函数」,绕开 __main__ 与一切网络路径。

```bash
# 终端 A:造一个被占用的假锁(30s)
python3 -c "import fcntl,time; f=open('/tmp/fake_r2_lock_239','w'); fcntl.flock(f, fcntl.LOCK_EX); time.sleep(30)" &
# 终端 B:只调拿锁函数,10s 掐死
cd <repo> && R2_UPLOAD_LOCK=/tmp/fake_r2_lock_239 perl -e 'alarm 10; exec @ARGV or exit 127' python3 -c "
import importlib.util
spec = importlib.util.spec_from_file_location('u239', 'scripts/upload_r2.py')
u = importlib.util.module_from_spec(spec); spec.loader.exec_module(u)
print('MODULE_LOADED_OK', flush=True)
u._acquire_r2_upload_lock()   # 默认排队语义: 假锁被占 → 静默 sleep(2) 至 7300s 上限
print('LOCK_ACQUIRED', flush=True)"
```
**实测结果(2026-10-09)**:`MODULE_LOADED_OK` 后 **10 秒零输出**,rc=142(SIGALRM 掐死)——
证明「撞锁 ⇒ 静默等待、零输出」是设计必然,与事故现场(tmp_log 空 / wchan=nanosleep / rchar 冻结)同构。

**复现二:云上证据链(只读,逐条可复核)**
1. `data/logs/r2_upload_async_20261009_002208.log` —— kill 行 + 空 tmp_log 转储 + 15 通道 tail 行序;
2. `data/logs/staticdata_backup_async_20261009_002224.log` —— `段1 start 00:22:24` / `[step3.5 …] 1155s` / `段2 start 00:42:05`(持锁窗口);
3. `data/logs/etf_national_team_heal.log L13072-13077` —— push_schedule_stats 00:22:25→00:23:25 SKIPPED_LOCKED(锁忙独立互证);
4. `data/logs/deploy_20261009_0013.log L1472-1490` —— A 实例触发原文;
5. `ls /home/ubuntu/code/trade-data/data/.r2_etf_hist_uploading.marker` —— **不存在**(正确路径已核实;marker 写于锁后);
6. `curl -sI https://ssd.fx8.store/nav_bucket/2c.json` —— `last-modified: 2026-10-09 01:10 +08`(补传闭环)。

**复现三:现场指纹对照表**(判定同类事故的速查)
| 指纹 | 本 bug(等锁) | 区分:HTTP 慢/挂(如 #217②) |
|---|---|---|
| tmp_log | 全空 | 通常已有进度行/→停滞前有输出 |
| wchan | hrtimer_nanosleep(常驻) | 多在 socket 等待(如 sk_wait_data) |
| rchar | 冻结在小值(仅解释器/import) | 持续增长后停滞 |
| 网络连接 | 0 个 | ≥1 个(或 TIME_WAIT 残留) |
| marker | 无(未写) | 可能残留(已过 L1395 被 kill) |

## 7. 修复方向建议(建议;本次未实施)

① **锁等待心跳(最小改动,直接消误杀)**:`_acquire_r2_upload_lock` 排队分支每 30~60s 打一行
  `⏳ 等待 R2 主锁中(已等 Ns, 持锁进程可用 lsof <lock> 排查)` 到 stdout/stderr ——
  tmp_log mtime 被刷新 ⇒ 停滞判据不再误杀;人工/告警侧可见状态。(顺带满足 §3-4 的「已知静默」问题根源。)
② **梯度原则扩展为三级并成文**:停滞阈值 > max(内层 HTTP 超时 600s, **锁等待合法静默上限**);
  或明确「锁等待心跳上线后,等待期有输出 ⇒ 停滞判据天然不误杀」,把「心跳存在」列为看门狗前置假设(机检)。
③ **长持锁者治理(根因级)**:`upload-large-json`(26~105min)与 `upload-fund-nav`(68min)是反复竞争源;
  参照 #149 方案②(备份桶独立锁)先例,评估「大对象上传与数据通道分锁」或提升其内部并发;
  最低限度:把「长持锁者清单 + 实测持锁时长」文档化,供等锁侧阈值设计。
④ **verify_channels 文案纠偏**:L3826 硬编码「force_full 未完成」改为中性/实际 kill 原因(如「看门狗停滞 kill, PUT 未执行」),防误导审计。
⑤ **顺带**:fund-nav marker 残留治理(下轮全量前的确认路径)与 `r2_upload_trigger_fail` 误报降噪(unit 已在跑时不算失败),建议并入相关批次。

## 8. 诚实标注(未验证/推算项)

- etf-hist 通道**启动秒级时刻与 kill 秒级时刻**为推算(≈00:22:5x 启动 / ≈00:37:5x kill):A 实例日志中间行无时戳,
  推算链=「kill 行前 4 行 tail 已完成 + push_schedule_stats 全窗忙 ⇒ 启动 ≥00:22:52」+「900s 停滞判据」;
- 「00:22:25-00:22:52 窗口持锁者=index 通道(158 keys 上传中)」为推理链结论(state 文件已被后续轮回写,无直证):
  证据=① A 实例 kill 行前恰 4 行 tail(前 4 通道完成)② push 60s 全窗忙(窗口前段必有人持锁,而该时段唯一活跃上传者=index);
- 101 补传清单含 `nav_bucket/2c.json` 为推断(日志只显示前 50 个 +(共 101 个);支撑=2c.json Last-Modified 落在补传窗内且该时段无其他上传进程);
- B 类(尤其 update_all/gold_night 等)是否已在云上实际发生「等锁卡链」未做全量日志考古;其外层 systemd/整链时限兜底行为未验证;
- 本报告未评估「按 §5.4 版本升级原则」的改动定级,修复落地方案由主控按流程派单。
