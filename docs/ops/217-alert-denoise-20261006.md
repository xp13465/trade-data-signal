# #217 告警降噪 ①②③ 实施报告(2026-10-06)

- 分支:`feat/217-alert-denoise-20261006`
- base commit(开工时 origin/main):`7cd94594c`(rebase 后 HEAD base 新鲜)
- 首个提交:`a4b495114`(rebase 后 hash 变为 **`d714be25b`**)
- 派单来源:`docs/ops/alert-triage-3d-20261006.md` §5.1 / §5.2-a / §5.2-b
- 第 ④ 条(`standalone_stale` 文案)**不在本次范围**(另派只读复核)

---

## 0. 一句话结论

三条全落地:① 共享锁加「有界等锁重试」,瞬时撞锁不再计入告警;② 看门狗停滞阈值由 300 → 900(> 内层 HTTP 600)并加自动防倒置守卫;③ kill 前把 tmp_log 尾部 30 行落主日志 + 进告警正文。三条的「真故障判别维度」全部保留。自测 ①11/11 + ②③17/17 全 PASS,零真实外发、零业务脚本主体执行。

---

## 1. 现象(改前)

| 条 | 现象 | 证据 |
|---|---|---|
| ① | 近 3 天 14 条 `fetch_news SKIPPED_LOCKED`(最大告警源)。两进程抢 R2 上传锁,后者立即「跳过」并留标记 | triage §5.1 |
| ② | 看门狗停滞阈值 `R2_UPLOAD_STALL_SECS` 默认 **300s** < 内层单请求 HTTP 超时 `R2_UPLOAD_HTTP_TIMEOUT`(**云上 .env=600**)⇒ 内层仍合法重试时外层已判死 kill = **梯度倒置** | triage §2.2 + §5.2-a |
| ③ | kill 前只 `tail -1` tmp_log,kill 后立刻 `rm tmp_log` ⇒ 10-06 17:16 告警正文「详情:**无输出**」,事后不可定因 | triage §2.2 |

---

## 2. 改法

### ① 族 A:`--skip-if-locked` 撞锁前先有界等锁重试(根因单点修)

- **`scripts/upload_r2.py` `_acquire_r2_upload_lock`**(唯一根因点,全部 `--skip-if-locked` 调用方共享):
  撞锁后先在窗口内轮询(`env R2_UPLOAD_SKIP_RETRY_SECS`,默认 **60s**,2s 间隔):
  - 窗口内拿到锁 ⇒ 正常上传,**静默**(不打印 `SKIPPED_LOCKED`、不参与连续轮次计数);
  - 窗口耗尽仍拿不到 ⇒ 才返回哨兵 + 打印 `SKIPPED_LOCKED`(语义不变);
  - `R2_UPLOAD_SKIP_RETRY_SECS=0` ⇒ **旧行为**(拿不到锁立即跳过,完全向后兼容)。
- **`scripts/fetch_news.py` / `scripts/overfit_monitor.py`**(仅有的两个带 subprocess timeout 的 skip 调用方):
  subprocess `timeout` 由 120 → `120 + 重试窗口`(默认 180),防内层重试期间被外层 timeout 杀掉,退化成 `TimeoutExpired`(✗ 真故障标记)而非 `SKIPPED_LOCKED`(设计让路)。
- 未加 skip flag 的调用方(deploy 日链等)**排队语义不变**,不受影响。

### ② 看门狗停滞阈值:梯度对齐 + 自动防倒置

- **`scripts/r2_upload_async.sh` `run_r2_upload`**:默认停滞阈值 `${R2_UPLOAD_STALL_SECS:-300}` → **`${R2_UPLOAD_STALL_SECS:-900}`**(> 云上内层 600,取值对齐 `s06_snapshot.sh` 的 `run_to 900` 同口径先例)。
- 新增**自动守卫**:`_http_to`(默认 30,取 `R2_UPLOAD_HTTP_TIMEOUT`)与 `_stall_secs` 比较,若 `_stall_secs ≤ _http_to`(倒置)⇒ 自动抬到 `_http_to + 300` 并打日志留痕。即使云上 .env 显式设了历史值 300,也会被抬到 900,**不会回归倒置**。

### ③ kill 前保留定因材料

- **`scripts/r2_upload_async.sh`** 新增 `_dump_kill_tail()`:kill 前把该通道**私有 tmp_log 尾部 30 行**落主日志(带 header),并做 HTML 转义后逐行 `<br>` 累积到 `R2_KILL_CTX`。
- 三处 kill 分支(停滞 / 7200s 硬兜底 / 低速)统一调用。
- 收尾 `finalize_verify` 的 `--severe` 告警正文追加 `${R2_KILL_CTX}`(即「[通道] kill 前尾部 30 行」)。
- 空 tmp_log 分支标注「(tmp_log 无任何输出——进程启动即无日志/缓冲未刷)」/「（无输出）」,仍可区分「启动即无日志」与「有输出但被 kill」。

---

## 3. 自测证据(全部 static-only / 零真外发)

### 3.1 硬约束遵守证明(§18 L48 / L50)

- 两个自测脚本**只读取**源文件(AST 摘单个函数 / awk 摘函数体 / grep),**从不 source 或 exec 业务脚本主体**:
  - `/tmp/t217_lock_selftest.py`:`ast.parse` 摘出 `_acquire_r2_upload_lock` 单函数→`exec`,不 import `upload_r2`(避开其顶部 `load_env()`/`os.environ["R2_BUCKET"]` 等副作用)。
  - `/tmp/t217_async_selftest.sh`:awk 抽取「梯度守卫块」与 `_dump_kill_tail()` 到临时文件再 source。
- **零真实外发证据**:①自测脚本内不含 `notify`/`schedule_monitor` 调用(grep 无命中);②`pgrep -fl "notify.py|schedule_monitor.sh|r2_upload_async.sh"` = **none**;③worktree 无 `data/logs`(自测未写任何日志/告警产物)。

### 3.2 ① 自测(`/tmp/t217_lock_selftest.py`,真 flock 实测)— **11/11 PASS**

| 用例 | 结果 |
|---|---|
| A 锁空闲 → 直接拿到 fd,无 `SKIPPED_LOCKED` | PASS |
| B **短暂持锁(~5s)后释放** → 等到锁拿 fd(实测等 6.0s),**无 `SKIPPED_LOCKED`**(=不产生告警) | PASS |
| C **一直持锁** + 窗口 4s → 4.0s 后返回哨兵并打印 `SKIPPED_LOCKED` | PASS |
| D `R2_UPLOAD_SKIP_RETRY_SECS=0` → 立即跳过(向后兼容),仍打印 `SKIPPED_LOCKED` | PASS |
| E 排队模式(无 skip) → 语义不变,等锁成功返回 fd | PASS |

### 3.3 ①「连续 3 轮 ⇒ 告警」判别保持(静态核对)

- 计数谓词:`gen_schedule_stats.py:556` / `:684` `skip_count = sum(1 for _l in ... if "SKIPPED_LOCKED" in _l)`。
- 判定:`schedule_monitor.sh:538` `R2_SKIP_CONTINUOUS_THRESHOLD = 3`;`:946` `< 阈值 ⇒ 不告警`;`:959` `≥ 阈值 ⇒ SEVERE`。
- 新消息**仍以 `SKIPPED_LOCKED` 开头**(子串匹配成立,实测 `MATCH: YES`)⇒ 计数不失效、阈值不放松。
- 语义闭合:短暂撞锁 ⇒ 不打印 ⇒ 计数 0 ⇒ 不入告警;一直撞锁 ⇒ 每轮 1 次 ⇒ 第 3 轮 SEVERE(**真缺口判别保持**)。

### 3.4 ②③ 自测(`/tmp/t217_async_selftest.sh`,抽取式)— **17/17 PASS**

② 梯度守卫(6 项):云上 http=600+缺省 → 900;http=600+**显式 300(倒置)→ 自动抬 900**;env 全缺省 → 30/900;显式 1200 合规不动;显式 900(>600)不动;http 非数字 → 回退 30。

③ dump 尾部(11 项):主日志恰好 30 行且**不含第 20 行**、含第 21..50 行;告警片段含通道名 / ≥30 个 `<br>` / 末行 `line-50`;空 tmp_log → 标记「无任何输出」+ 片段「（无输出）」;`<`/`>` HTML 转义正确;三处 kill 分支调用计数 = 3;收尾 `--severe` 正文引用 `R2_KILL_CTX`。

### 3.5 语法/静态检查

- `py_compile`:`upload_r2.py` / `fetch_news.py` / `overfit_monitor.py` **PASS**(pre-commit `lint_scripts.sh` 全绿)。
- `bash -n scripts/r2_upload_async.sh` **PASS**。

---

## 4. 同类错误面清单(§23.2 / §23.3)

### 4.1 ①「skip 式静默让路」同类点

| # | 位置 | 现状 | 判定 | 理由 |
|---|---|---|---|---|
| 1 | `upload_r2.py::_acquire_r2_upload_lock` | 已修 | **修** | 根因单点,4 个 skip 调用方共享(见 4.3) |
| 2 | `fetch_news.py` / `overfit_monitor.py` 调用点 timeout | 已修(120→180) | **修** | 属①影响面:重试窗口必须被外层 timeout 覆盖 |
| 3 | `push_schedule_stats.sh:84` | grep `SKIPPED_LOCKED` → 打 ⚠ 行(不静默) | 不动 | 已有显式标记 + 消费方计数覆盖;仅 shell 无 outer timeout |
| 4 | `intraday_snapshot.sh:139-150` | 20:35 收尾轮改**排队不 skip** | 不动 | 已是正确形态(避免当日最后一轮永不上) |
| 5 | `with_lock.py --nb` | 打印 stderr「已被占用,跳过」+ exit 0 | 不动 | 设计让路 + 有 `--on-skip` 通知钩子;改它会动 update_all 等互斥语义 |
| 6 | `with_lock.py --block-timeout` 排队超时 | 内置 notify(warning,已降过噪) | 不动 | 已有告警,与本条无关 |
| 7 | 各 `TimeoutExpired` 分支(✗ 标记) | 真故障语义 | 不动 | 语义正确(超时≠跳过);本次只保证外层 timeout ≥ 重试窗口 |

### 4.2 ②「外层超时 vs 内层 HTTP 超时」梯度同类点(云上内层 = 600)

| # | 位置 | 外层 | vs 600 | 判定 | 理由 |
|---|---|---|---|---|---|
| 1 | `r2_upload_async.sh` 停滞阈值 | 300→**900** | 已修 | **修**(点名) | 本次任务 |
| 2 | `s06_snapshot.sh:132` `run_to 900` | 900 | 合规 | 不动 | 已是「内层 600 留梯度」先例,本次对齐它 |
| 3 | `fetch_news.py:732` | 120→**180** | 已修 | **修** | 属①影响面 |
| 4 | `overfit_monitor.py:1872` | 120→**180** | 已修 | **修** | 属①影响面 |
| 5 | `gen_daily_brief.py:3115` | 120 | **倒置** | **不动,上报待评估** | 同类;但已有 degrade/critical + 3 轮自愈 + deploy 兜底设计,属既有刻意降噪链;动它越出点名范围 |
| 6 | `nextday_plan_generator.py:1177` | 300 | **倒置** | **不动,上报待评估** | 同类;超时走 **loud severe**(非静默),设计为 fail-fast 告警 |
| 7 | `fapi_bj_width_export.py:75` | 600 | **零梯度**(相等) | **不动,上报待评估** | 相等非倒置;小文件;严格说应 >600 |
| 8 | `intraday_snapshot.sh` / `push_schedule_stats.sh` | 无外层 timeout | — | 不适用 | 无梯度问题 |
| 9 | `deploy.sh` git fetch/push | 120 | — | 不适用 | 包的是 git(非 R2 HTTP),不同类 |

> **给主控**:#5/#6/#7 判为「同类未修、建议评估」,未擅自扩scope(§L11/§23.7)。若认为该统一口径,建议另立小任务(涉及 gen_daily_brief / nextday_plan / fapi_bj_width 三条生产链)。

### 4.3 ①影响面(共享根因点的受益调用方)

全量 `--skip-if-locked` 调用方(4 处,均因根因单点修自动受益):
`fetch_news.py:731`、`overfit_monitor.py:1871`、`push_schedule_stats.sh:73`、`intraday_snapshot.sh:150`。

> 其中 shell 两处无 outer subprocess timeout,重试窗口最多多等 60s(implementer 已核:不触任何 systemd `TimeoutStartSec` 风险;云上 unit 分子本会话未取到,ssh key 不在本机,故为**诚实待核项**,见 §5)。

### 4.4 ③「kill/超时丢日志」同类点

| # | 位置 | 现状 | 判定 |
|---|---|---|---|
| 1 | `r2_upload_async.sh`(3 处 kill) | 已修(补 dump 尾 30) | **修** |
| 2 | `deploy.sh` `git_fetch_timeout`/`git_push_timeout` | 已 `tail -n 30 >> LOG` | 不动(已合规) |
| 3 | `staticdata_backup_async.sh:433` | 已 `tail -n 30` | 不动(已合规) |
| 4 | `fund_nav_upload_async.sh` | 无 kill 分支 | 不适用 |

---

## 5. 诚实标注 / 待核项

1. **云上 .env 未能在本会话核实**:本机无 cloud ssh key(`~/.ssh/tdsignal.pem` 不存在),故 `R2_UPLOAD_HTTP_TIMEOUT=600`(云上)采信 `docs/ops/alert-triage-3d-20261006.md` §2.2 记录。**但设计对此稳健**:即便云上 .env 显式设了历史 `R2_UPLOAD_STALL_SECS=300`,② 的自动守卫也会把它抬到 900,不会回归倒置。
2. **无第二消费者依赖 300**:`grep R2_UPLOAD_STALL_SECS` 全仓仅命中 `r2_upload_async.sh` 自身默认值 + 两份**历史报告文档**(`docs/ops/alert-triage-3d-20261006.md:68`、`docs/ops/r2-residual-risks-20261005.md:51`)的描述文字 ⇒ **未发现「别处真依赖 300」**,故未触发「停下上报」条件;两份文档为时点快照,未追改(如需可另补注)。
3. **§21 / §24 / §23.1 不适用**:本次为运维链路告警 Plumbing 改动,未改任何前端算法/公示数值/前端源码 ⇒ 无算法公示同步、无版本串 bump、无 README 参考致敬段要求。
4. **未跑任何业务脚本主体、未真发任何通知**(§18 L48/L50),见 §3.1 证据。
5. **上线的第二条锁**:本改动**尚未合 main/上线**(agent 只 push feat)。生产生效需主控走 `main-merge.sh`(主控侧 §14 安全窗口 + §24 检查)。

---

## 6. 复现命令

```bash
# ① 单函数实测(真 flock,不 import 业务模块)
/Users/linhuichen/code/trade/.venv/bin/python /tmp/t217_lock_selftest.py scripts/upload_r2.py
# ②③ 抽取式静态自测
bash /tmp/t217_async_selftest.sh scripts/r2_upload_async.sh
# 语法
/Users/linhuichen/code/trade/.venv/bin/python -m py_compile scripts/{upload_r2,fetch_news,overfit_monitor}.py
bash -n scripts/r2_upload_async.sh
```

> 自测脚本位于 `/tmp`(非仓内产物),如需长期保留请另行归档。若 `/tmp` 已清,可依 §2 改法在本报告描述上重建同构自测。