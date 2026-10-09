# #239 止血步 —— 排队等锁可见性(2026-10-09)

> 角色:实施 agent(isolation=worktree,`worktree-agent-a17c0cad8ae674069`)
> 关联定因报告:`docs/ops/etf-hist-forcefull-stall-rootcause-20261009.md`(§3-4 根因 / §5 同族面 / §7 修复建议)
> 范围:**只做止血**——只加可见性输出,**未动锁语义 / sleep 间隔 / 任何超时值 / 看门狗 kill 判据 / #217② 梯度逻辑 / 信号处理**。
> 本报告含本体 + 复现段;配套 commit `88fecb1d7`(base:`origin/main` `16dfee5aa`,rebase 后 base-fresh)。

## 0. 一句话结论

在 `upload_r2._acquire_r2_upload_lock` 的**排队等锁循环**里加入周期性心跳(每 30s 一行到 stderr + flush),
刷新外层 `tmp_log` 的 mtime ⇒ `r2_upload_async.sh` 的停滞判据(默认 900s 无输出)不再把「合法等锁」误判成
「卡死」而 kill 健康进程。**只加输出,不改任何行为语义**;真卡死仍被同一判据 kill。

## 1. 改动清单(file:line)

| 文件 | 位置 | 改动 |
|---|---|---|
| `scripts/upload_r2.py` | `L3859-3863`(新常量) | 新增 `_R2_LOCK_HEARTBEAT_SECS = 30`(心跳间隔,含取值依据注释) |
| `scripts/upload_r2.py` | `L3879-3881`(函数 docstring) | 补一段说明:排队等锁心跳 = 纯可见性,锁/sleep/超时/看门狗判据均未动 |
| `scripts/upload_r2.py` | `L3936-3938` | 排队循环前初始化 `wait_started_at` / `last_beat_at`(仅计时用) |
| `scripts/upload_r2.py` | `L3957` | `if time.time() >= deadline:` → `now = time.time(); if now >= deadline:`(同一调用的等价改写,仅为复用 `now`) |
| `scripts/upload_r2.py` | `L3966-3972` | **核心**:排队分支在 `time.sleep(2)` 前插入心跳 print(`flush=True`),`now - last_beat_at >= 30s` 才打 |
| `scripts/tests/test_239_lock_heartbeat_20261009.py` | 新文件 | 4 例回归:等锁出心跳 / 锁空闲零心跳 / skip 分支不变 / 常量默认 30 |

diff 规模:`scripts/upload_r2.py` +27 -1;新测试 +97。未改前端(`static-site/` 未动 → §24 不适用、无版本串 bump)、
未改数据产物(§22 不适用)、未动算法/数值(§21 不适用)。

心跳行(实测原样):
```
⏳ 等待 R2 上传锁 30s(上限 7300s, 持锁进程可用 lsof /tmp/trade_r2_upload.lock 排查)
```

## 2. 语义边界(明确「未动」清单)

- **未改** flock 语义 / `time.sleep(2)` 间隔 / `deadline` 与 `R2_UPLOAD_LOCK_TIMEOUT`(7300s)/ `skip_if_locked` 分支与 `R2_UPLOAD_SKIP_RETRY_SECS`(#217① 语义原封);
- **未动** `scripts/r2_upload_async.sh`(kill 判据、`R2_UPLOAD_STALL_SECS`、#217② 梯度、7200s 硬兜底、低速判据——一行未改);
- **未加** 任何信号处理 / 新 CLI flag / 新 env 开关(心跳间隔是模块常量,不引入可调面);
- **未动** 超时 fail-closed 文案(实测仍在,见 §3-自验1);
- **兼容性核对**:心跳行为 `(上限 7300s, ...)` **不**匹配看门狗低速判据的 `\([0-9]+B\)`,也**不**匹配 `[N/M]` 进度正则 ⇒ 不干扰 `r2_upload_async.sh` L161-164 的解析;成功路径 `tail -1 tmp_log`(L184)拿到的仍是业务收尾行(心跳只出现在等锁期)。

## 3. 自验(3 项,缺一不可)

环境:mac 本机,零网络、零 R2 写(全程只 `import` 模块 + 调拿锁纯函数 flock 本地文件;`R2_BACKUP_BUCKET=demo-nowhere` 兜底隔离)。
真锁被占手段 = 后台进程对 `/tmp` 假锁文件取 `LOCK_EX`(复刻定因报告 §复现一手法),**不碰生产 R2 桶**。

### 自验 1:假锁被占 → 排队期出现周期性输出(真间隔 30s,可复现证据)

复现命令(见 §7)实测结果:
```
mtime_at_10s=1791521982  now=1791521992      # t=10s tmp_log mtime
mtime_at_35s=1791522013  now=1791522017      # t=35s tmp_log mtime —— 已前进 31s(心跳在 ~30s 处刷新)
waiter_rc=142                                 # 38s 内部 alarm 掐死(全程未拿到锁)
=== log ===
MODULE_LOADED_OK
⏳ 等待 R2 上传锁 30s(上限 7300s, 持锁进程可用 lsof /tmp/239_fakelock 排查)
=== end ===
```
**PASS**:① 排队期出现心跳行;② `tmp_log` mtime 持续刷新(30s 心跳 < 900s 判据);③ 全程无 `LOCK_ACQUIRED`(输出只在等锁分支)。
快速档(心跳 2s / 超时 8s,harness Case A)实测 3 行心跳(`2s / 4s / 6s`)+ 随后超时 fail-closed 文案原样打出:
```
LOADED
⏳ 等待 R2 上传锁 2s(上限 8s, ...)
⏳ 等待 R2 上传锁 4s(上限 8s, ...)
⏳ 等待 R2 上传锁 6s(上限 8s, ...)
✗ R2 上传锁 /tmp/239_hl 排队等待超 8s 仍被占用, 拒绝本次上传(fail-closed, ...)
```

### 自验 2:反证 —— 只在等锁分支加输出,业务路径 / 真卡死路径行为不变

用 harness(`/tmp/239_judge.py`)复刻 `r2_upload_async.sh` L133-148 的停滞判据(唯一核心行
`now - mtime >= stall` → kill;缩放 `stall=6s` 加速),对三类进程跑同一判据:

| 用例 | 进程 | 判据结果 | 结论 |
|---|---|---|---|
| A 等锁+心跳(2s) | `_acquire_r2_upload_lock` 被假锁挡住 | **killed=False**(心跳持续刷新 mtime,判据不误杀) | 止血生效 |
| B 真卡死(20s 无输出) | `sleep 20`,零输出 | **killed=True**(mtime 停滞 ≥6s → 等价 L139 kill,rc=-9) | **真卡死仍被 kill,行为不变** |
| C 锁空闲 | `_acquire_r2_upload_lock` 立即拿锁 | 立即 `ACQUIRED`,`等待 R2 上传锁` **零出现** | 业务路径零变化 |
| D skip 分支 | `--skip-if-locked`,`SKIP_RETRY=0` | 返回哨兵 + `SKIPPED_LOCKED`,**无心跳** | #217① 语义未动 |

harness 全 PASS(`RESULT: ALL PASS`)。**反证成立:新增输出严格只出现在「排队等锁」分支;卡死判据的判别力未被削弱。**

### 自验 3:回归 —— 存量测试无新增失败

- 新增 `test_239_lock_heartbeat_20261009.py`:**4 passed**。
- 存量 `scripts/tests` 全量(提交态,HEAD==工作区):**443 passed, 2 skipped, 0 failed**(90s)。
- **观察项(非本次引入)**:`test_212_upload_onfail_loud_pytest.py::test_e_pre_change_source_static`
  在**未提交态**会 FAIL —— 该例是「仅未提交态可得」的改前/改后静态对照,断言「HEAD 版不含 `_channel_on_fail`」,
  而 #212 早已合入 main(HEAD 已含 27 处)⇒ 只要 `upload_r2.py` 有任何未提交改动它就 FAIL;提交后
  `HEAD==工作区` → 自动 skip(实测:临时还原 HEAD 版跑该例 = `1 skipped`)。属既有测试脆弱点,**不属本任务范围,未顺手改**(§23.7)。

## 4. §23.3 举一反三:同模式清单 + 覆盖结论

**关键洞察(单点修 = 全消费方获得「可见性」;但「免误杀」的受益面必须收窄,非「A/B 类全部受益」)**:
定因报告 §5 的 A/B 类各处「静默等锁」**都走同一个** `_acquire_r2_upload_lock` 排队分支
(均不带 `--skip-if-locked`)⇒ 本次**一处**改动即让它们**全部获得等锁可见性**。但**「免误杀」只覆盖其中一类**:

- **mtime 型看门狗通道(`r2_upload_async.sh` 的 15 个数据通道)→ 免误杀**:停滞判据(mtime ≥ 900s 无输出)被心跳持续刷新 ⇒ 不再 kill;
- **`run_to` 型 4 个调用点(`s06_snapshot.sh:133,161` 的 upload-data-files/upload-kelly-snapshots、`turnover_backfill.sh:145,148` 的 upload-intraday/upload-data-large)→ 仅获得可见性,仍会被总时长截断**:`run_to` = GNU `timeout`(`s06_snapshot.sh:42-52` / `turnover_backfill.sh:47-57`,总时长 SIGTERM),**不是** mtime 停滞判据 —— 心跳刷新的是输出,延不了 `run_to 900` 的总时长;
- **B 类 9 个直调脚本 → 仅获得可见性**:它们本就**无外层 killer**(排队上限 7300s),不涉「免误杀」,只消除日志静默。

| 同模式面 | 位置 | 本次处理 |
|---|---|---|
| 排队等锁循环(默认语义;全部排队分支消费方) | `upload_r2.py:3939-3977` | ✅ 已加心跳(可见性覆盖全部消费方;**免误杀仅限 mtime 型 15 通道**) |
| `run_to` 总时长包装(`s06_snapshot.sh`/`turnover_backfill.sh` 的 4 个 upload_r2 调用点) | `s06_snapshot.sh:133,161` / `turnover_backfill.sh:145,148` | ⛔ 非本步目标:`run_to` 是**总时长 kill**(非停滞判据),心跳只给可见性、**不防截断**;超 900s 仍被 SIGTERM |
| `--skip-if-locked` 有界重试窗口(≤60s,静默) | `upload_r2.py:3944-3949` | ⛔ 未改:窗口上限 60s ≪ 看门狗 900s,误杀风险为零;且 #217① docstring 明示「窗口内静默重试」,改=动语义 |
| 通用锁 `with_lock.py` 阻塞等锁循环 | `with_lock.py:148-172`(`--block-timeout`;`deploy.sh` 用 3600 / `r2_upload_async.sh` 用 600) | ⛔ 未改:同「静默等锁」模式但**另一把锁、另一批链**(deploy/fund_nav/lhb…),动它=改其它链语义(§23.7),**建议主控单列** |
| 停滞判据对「锁等待合法静默」的假设(文档层) | 报告 §3-5(r2_upload_async.sh L112-125 梯度第三级未覆盖锁等待) | ⛔ 未改代码;本报告 §5 记录「心跳存在 = 判据天然不误杀」的前置假设 |
| 长持锁者(`upload-large-json`/`upload-fund-nav`) | 报告 §5-D | ⛔ 治本档,只列出不做(见 §5) |

## 5. §23.2 修 bug 三铁律:同类错误面清单 + 逐项结果

| 同类错误面(与本次同根因:合法静默被误判) | 结果 |
|---|---|
| ① `upload_r2` 排队分支零输出 → 被 **mtime 型**停滞判据误杀(`r2_upload_async.sh` 15 通道) | ✅ 已修(本 commit;自验 1/2 覆盖)**免误杀仅限此 15 通道**;`run_to` 型 4 调用点不在此列(见 §4) |
| ② `upload_r2` skip 分支重试窗口静默 | ✅ 自验确认「有界 60s,零误杀风险」+ 语义未动(harness Case D) |
| ③ `with_lock.py` 阻塞等锁静默(deploy.lock 等) | ⛔ 同族存在,超本步 scope,已上报(§4 表) |
| ④ 真卡死路径判别力 | ✅ 反证不变(harness Case B:仍 kill) |
| ⑤ 低速判据 / 进度正则兼容 | ✅ 静态核对:心跳行不匹配 `\([0-9]+B\)` 与 `[N/M]`(§2) |

## 6. 未做项及原因(定因报告 §7 修复建议逐条对账)

| §7 建议 | 分类 | 本次 |
|---|---|---|
| ① 锁等待心跳(最小改动,直接消误杀) | **止血** | ✅ 已做 |
| ② 梯度原则扩展为三级并成文 / 把「心跳存在」列为看门狗前置假设(机检) | 触及 `r2_upload_async.sh` kill 判据 / #217② 梯度 | ⛔ 派单明令禁止「不动 r2_upload_async.sh 的 kill 判据、不动 #217② 梯度逻辑」⇒ 未做;「心跳存在」假设 + 机检设计方向已落 **§9 上线后跟进** |
| ③ 长持锁者治理(`upload-large-json` 分片 / 分锁) | **治本(根因级)** | ⛔ 只列出不做(派单指定) |
| ④ `verify_channels` L3826「force_full 未完成」文案纠偏(防误导审计) | 文案/审计项,**非止血**(不消误杀) | ⛔ 未做:属「顺手优化」范畴,派单强调「任何顺手优化都不许」(§23.7 冻结契约);且改告警文案涉 §23.10。**留主控定级**——如需,建议单列小任务(该行 `print` 文案 + `bad.append` 告警文案需分别评估) |
| ⑤ fund-nav marker 残留治理 + `r2_upload_trigger_fail` 误报降噪 | 报告自注「建议并入相关批次」 | ⛔ 未做(不属本步) |

其它未做:未改 `docs/pending-features-index.md` #239 状态列(main 已刷新为「定因完成 / 止血步实施中」,
状态治理归主控,避免并发覆盖 §23.11);未跑云上/生产实跑(本步为可见性机制,验收落本机同构复现 + 判据 harness)。

## 7. 复现段(命令)

**复现一:真间隔 30s(实测见 §3-自验1)**
```bash
cd <worktree>
# 终端 A:对假锁取 LOCK_EX 45s(不碰生产 R2)
python3 -c "import fcntl,time; f=open('/tmp/239_fakelock','w'); fcntl.flock(f,fcntl.LOCK_EX); time.sleep(45)" &
# 终端 B:import 模块只调拿锁函数, 38s 内部 alarm 掐死, stderr 落盘
R2_UPLOAD_LOCK=/tmp/239_fakelock python3 -c "
import signal, importlib.util
signal.alarm(38)
spec = importlib.util.spec_from_file_location('u239','<abs>/scripts/upload_r2.py')
u = importlib.util.module_from_spec(spec); spec.loader.exec_module(u)
print('MODULE_LOADED_OK', flush=True)
u._acquire_r2_upload_lock()
print('LOCK_ACQUIRED', flush=True)
" > /tmp/239_v1.log 2>&1 &
sleep 10; stat -f %m /tmp/239_v1.log      # t=10s mtime
sleep 25; stat -f %m /tmp/239_v1.log      # t=35s mtime(应已前进, 心跳刷新)
cat /tmp/239_v1.log                        # 应含「⏳ 等待 R2 上传锁 30s(上限 7300s, ...)」
```
（mac 无 `timeout`;用 Python `signal.alarm` 自掐,不依赖外部命令。）

**复现二:判据 harness(反证;实测见 §3-自验2)** —— `/tmp/239_judge.py`(见本 commit 的测试文件同类判据),
复刻 `r2_upload_async.sh` L133-148 的 `now - mtime >= stall` → kill,`stall=6s`:
`python3 /tmp/239_judge.py` ⇒ `RESULT: ALL PASS`(A 不 kill / B kill / C 零心跳 / D 常量 30)。

**复现三:回归** —— `/Users/linhuichen/code/trade/.venv/bin/python -m pytest scripts/tests -q`

## 8. 诚实标注

- 本步**只做可见性**,**不治本**:长持锁者仍在,等锁通道仍可能等满 7300s;区别只是**不再被误杀 + 可观测**。
  治本(§7-③)待排。
- 自验 2 的「判据」为**缩放复刻**(stall=6s,非生产 900s),复刻的是 `r2_upload_async.sh` L139 的**单行**判据;
  未实跑生产脚本(L50 静态/隔离原则),未触碰云上。
- 心跳间隔常量 30s 为默认值,未提供 env 覆盖(刻意不引可调面);若后续需调,再单列。
- 「一处修 = 全消费方受益」**须分两类读**(见 §4):**可见性**覆盖全部排队分支消费方(mtime 型 15 + run_to 型 4 + B 类 9);
  **免误杀**只覆盖 **mtime 型 15 通道** —— `run_to` 型 4 调用点仅得可见性、仍会被 `run_to 900` 总时长 SIGTERM,B 类本就无外层 killer。
  此为**代码结构推理**(它们都不带 `--skip-if-locked` ⇒ 走同一排队分支),未逐脚本实跑验证
  (报告 §5-B 亦标注「是否已在云上实际发生等锁卡链未做全量日志考古」)。

## 9. 上线后跟进(登记 = 待办清单,**本次不做**)

**① 首夜巡检:看「误杀数」是否归零**
上线后首个交易日盘后,查 `r2_upload_async_*.log` 的停滞 kill 行(形如 `⚠ <通道> 停滞 <N>s 无日志输出, kill pid=`)。
预期 **mtime 型 15 通道的「等锁类误杀」归零**(等锁期应打心跳而非被 kill)。若仍见 kill,回看该行前后是否已出现心跳:
心跳已出现却仍被 kill ⇒ 判据仍有缺口;心跳未出现 ⇒ 未走到等锁分支(另查)。

**② 「心跳存在 = 看门狗前置假设」目前只是「沉默契约」,需做成机检(设计方向)**
本止血的效果**依赖**「排队等锁期必有周期性心跳」这一隐含假设,而它 **①未机检 ②失效时无人报警**。
风险:日后若有人**删掉心跳行**、或把 `_R2_LOCK_HEARTBEAT_SECS` **调大到 ≥ stall**(或把 stall 调小到 ≤ 心跳间隔),
会**静默退回误杀**且**无人察觉**(同 §18 L42「三次声称修好实际零变化」的静默失效病灶)。
- **机检设计方向(供后续单列任务)**:在 `r2_upload_async.sh` 的 kill 判据触发**之前**加一条断言 ——
  「近 `stall` 窗口内 tmp_log **应出现过心跳行**(如 `grep -q '等待 R2 上传锁'`)」;断言成立 ⇒ 判「合法等锁」续等,不成立才 kill。
  等价地,把「(a) 心跳行文本、(b) 心跳间隔 ≪ stall」两条做成跨文件一致性机检(改常量或删心跳行 ⇒ 机检 FAIL 阻断)。
- **状态**:登记为**上线后跟进项,本次不做**(本步派单明令「不动 `r2_upload_async.sh` 的 kill 判据」)。

**③(附)`run_to` 型 4 调用点的总时长截断**仍是误杀残留面(见 §4):心跳只给可见性、不防 `run_to 900` SIGTERM。
根治需给 `run_to` 加「等锁豁免」或让这类通道改走 mtime 型判据 —— **登记,本次不做**(属 §23.7 跨脚本语义改动)。