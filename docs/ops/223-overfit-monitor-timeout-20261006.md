# #223-④ overfit_monitor 内层 R2 上传超时 180 → 900 + 运行时梯度守卫

- 任务:#223 五个「超时梯度」待拍板项里的 **④ overfit_monitor** 单一处(用户已拍板本批唯一一项)。
- 分支:`feat/223-overfit-monitor-timeout-20261006`(基于 origin/main `dc0f3a124`,base 新鲜)
- 日期:2026-10-06

## 一、结论

**改一处、只改一处**:`scripts/overfit_monitor.py` 对 `upload_r2.py` 的 subprocess 超时预算
`_r2_timeout`(旧值 `120 + _r2_skip_retry` = 180s)**抬到 900s 基预算**,并新增**运行时梯度守卫**
`_r2_upload_timeout()`(对齐 #217② `fapi_bj_width_export.py` 先例)。外层 systemd 墙 = **0(无界)**,
故内层预算是该链唯一墙钟,可单独抬升,无需动云上单元。

改动文件(2 个):
- `scripts/overfit_monitor.py`(改;+90 / -1)
- `scripts/tests/test_223_overfit_monitor_timeout.py`(新增;static-only 机检)

## 二、三层梯度(逐层实测锚定)

| 层 | 位置 | 值 | 性质 |
|---|---|---|---|
| L0 内层 | `upload_r2.py` 单请求 HTTP 超时 `R2_UPLOAD_HTTP_TIMEOUT` | 本机默认 **30** / 云上 `.env` **600** | 子进程内部 HTTP,被 upload_r2 自己捕获 |
| L1 本层 | overfit_monitor → `upload_r2.py` 的 subprocess 超时 `_R2_UPLOAD_TIMEOUT` | 旧 **180**(=120+skip_retry) → 新 **900**(+skip_retry) | 被 `except subprocess.TimeoutExpired` **捕获(优雅)** |
| L2 外层 | systemd `TimeoutStartSec`(`trade-overfit-monitor.service`) | **0 = infinity(无界,云上实测)** | SIGKILL,**进程内无法捕获(激进)** |

**判据(优雅 vs 激进)**:L1 超时后被本进程 `except subprocess.TimeoutExpired` 接住 → 打 ✗ `R2_UPLOAD_TIMEOUT`
标记继续(优雅);L2 = systemd 硬杀,进程内零捕获(激进)。**正确梯度 = 激进必须更慢 ⇒ L1 < L2**;
L2 = 0(无界)时无上界约束 ⇒ 放行,**不生硬比较**。另守 #217② 先例:**L1 > L0**,否则本层会在
`upload_r2` 自身 HTTP 超时前杀子进程,丢了子进程诊断输出与 `--skip-if-locked` 等锁重试窗口。

## 三、硬门(开工前先过,已过)

| 门 | 实测命令 | 结果 |
|---|---|---|
| ① 读 1869 上下文 | `sed -n '1930,1965p' scripts/overfit_monitor.py` | L1 = subprocess → `upload_r2.py`;`except subprocess.TimeoutExpired` 打 `✗ R2_UPLOAD_TIMEOUT` 继续(优雅);旧值 `120 + _r2_skip_retry` = 180 |
| ② 云上 systemd 墙(**只读**) | `ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'systemctl show -p TimeoutStartUSec --value trade-overfit-monitor.service'` | **`infinity`(即 0,无界)**;单元文件 `TimeoutStartSec=0` ⇒ 放行,可单独抬内层 |
| ③ 任务前提「已有 `#223 勿擅改` 注释」核对 | `grep -n "勿擅改" scripts/overfit_monitor.py` | **不存在**(该注释只在 ①`gen_daily_brief.py:3111` / ②`nextday_plan_generator.py:1177` / ③`nextday_gap_check.py:355` 三处)。**如实上报,未假设其存在** |

> **只读声明**:门 ② 全程只 `systemctl show`(读);**未改任何云上单元、未 `daemon-reload`、未 restart**。

## 四、改动内容

### 4.1 常量 + 守卫(`scripts/overfit_monitor.py`)

- `scripts/overfit_monitor.py:60` 新增 `import re`(解析 systemd 时间跨度)。
- `scripts/overfit_monitor.py:1655-1738` 新增守卫块(在 `def build_output` 之前):
  - `scripts/overfit_monitor.py:1664` `_R2_UPLOAD_TIMEOUT = 900`(#223④ 由 180 抬到 900)
  - `scripts/overfit_monitor.py:1665` `_R2_UPLOAD_TIMEOUT_MARGIN = 300`
  - `scripts/overfit_monitor.py:1666` `_OVERFIT_SYSTEMD_UNIT = "trade-overfit-monitor.service"`
  - `scripts/overfit_monitor.py:1669` `_SYSTEMD_SPAN_UNITS`(单位表)
  - `scripts/overfit_monitor.py:1680` `_parse_systemd_span_secs()`(systemd 时间跨度 → 秒;`infinity`/空/无法解析 → 0)
  - `scripts/overfit_monitor.py:1695` `_systemd_outer_wall_secs()`(运行时探测外层墙;探测失败 → 0 = 视为无界)
  - `scripts/overfit_monitor.py:1706` `_r2_upload_timeout()`(**梯度守卫**,可传 `outer_wall_secs` 便于测试)

守卫两条规则:
- **规则 A(外层)**:`outer > 0 且 base ≥ outer` ⇒ 梯度倒置(systemd 硬杀会抢在优雅超时之前)⇒
  **自动收到 `outer - 300`** 并 warn;`outer = 0` ⇒ **放行**(不生硬比较)。
- **规则 B(内层 HTTP,#217② 先例)**:`base ≤ R2_UPLOAD_HTTP_TIMEOUT` ⇒ 倒置/零梯度(本层会在
  `upload_r2` 自身 HTTP 超时前杀子进程)⇒ **自动抬到 `内层 + 300`** 并 warn。
- 冲突分支:内层与外层无法同时满足梯度时,**外层优先不越墙**,并明确 warn。

### 4.2 调用点(`scripts/overfit_monitor.py:1954-1961`)

```python
# #223④(2026-10-06): 本层基预算 120 → 900——_r2_upload_timeout() 带运行时梯度守卫
# (外层 systemd=0/无界 ⇒ 放行; 有界且倒置 ⇒ 收回; 内层 HTTP 倒置 ⇒ 抬升), #217①
# 等锁重试窗口(R2_UPLOAD_SKIP_RETRY_SECS)照旧加在本层预算之上(默认合计 960s)。
_r2_timeout = _r2_upload_timeout() + _r2_skip_retry
```

旧 `_r2_timeout = 120 + _r2_skip_retry` 已清除;`+ _r2_skip_retry`(#217① 等锁窗口)保留不动。

## 五、证据点

### 5.1 硬门证据
- 云上外层墙:**`infinity`**(=0,无界)。命令见 §三 门 ②;同批取的 42 个 `trade-*.service` 全表:
  21 个 `infinity`,其余有界(含 `trade-s06-snapshot.service` = **55min**)。
- 本机(dev,mac,无 `systemctl`):守卫探测失败 → 视为无界 → 返回 900(与云上一致)。

### 5.2 「守卫真修了而非注释级」证据(可复现)
`scripts/tests/test_223_overfit_monitor_timeout.py`(**static-only**,§18 L50:只 `ast` 抽守卫函数
+ 常量 → `exec` 到隔离命名空间,**绝不 import 业务模块、绝不执行任何业务脚本主体**):

| 输入 | 期望 | 实测 |
|---|---|---|
| 外层 `0`(无界) | 900,不 warn | ✅ 900,无 warn |
| 外层 `600`(**倒置**) | **纠正为 300**(600-300)并 warn | ✅ 300 + `⚠ 自动收到` |
| 内层 HTTP `1200`(> 900) | **纠正为 1500**(1200+300)并 warn | ✅ 1500 + `⚠ 自动抬到` |
| 云上口径(内层 600,外层 0) | 900,静默 | ✅ 900,无 warn |
| 不变量:外层 ∈ {0,60,300,600,900,1200} | 结果 < 外层(或 0 放行) | ✅ 全过 |
| 退化:外层 `1` | 取最小 1 且 warn(不静默) | ✅ 1 + warn |
| 不变量:内层 HTTP ∈ {0,…,1200} | 结果 > 内层 | ✅ 全过 |
| **值依赖**:同输入(外层 600)下常量 900 ⇒ 300 / 常量 120 ⇒ 120 | 两者不同 | ✅ 证明非注释级、判定随运行值改变 |
| `_parse_systemd_span_secs` 真实格式样本 | `infinity→0`/`10min→600`/`1h 30min→5400`/`500ms→0`/`abc→0` | ✅ 全过 |

→ **喂倒置输入 ⇒ 守卫真的纠正了返回值**,不是写在注释里。断言数 **≥ 30**,末尾下限护栏防「收集异常假绿」。

### 5.3 零真实外发证据(§18 L48)
- **本次自测未产生真实外发**。证据(**非自述**):
  - `data/alerts/latest.md` md5 = `e8e4db889167bdd04aad8aaaa61cf9c8`,mtime `10-6 17:40`,**自测前后逐位不变**(测试内含该断言)。
  - 测试全程 **未 import `notify`**、未持有 `send_notify`(静态断言);未向邮件/Telegram/飞书任何链路发请求。
  - 探针 **static-only**:只 `ast` 抽取守卫函数 + 常量 `exec`,未 source/exec 任何业务脚本主体。
- 自测前置打桩说明:本守卫**纯计算 + 只读 `systemctl show`**,不含任何发送调用;测试对该探测函数注入
  参数(`outer_wall_secs=...`)替代真实探测 ⇒ 连 `systemctl` 都不实际执行,更无外发面。

### 5.4 全量回归
- `scripts/tests/` 全量:pytest 结果 **264 passed, 1 skipped**(新测试计入)。
- 新测试单跑:`1 passed`。

## 六、复现命令

```bash
cd <repo>
# 硬门:云上外层墙(只读)
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 \
  'systemctl show -p TimeoutStartUSec --value trade-overfit-monitor.service'   # 期望: infinity

# 守卫行为(本机,mac 无 systemctl ⇒ 探测=无界)
python3 scripts/tests/test_223_overfit_monitor_timeout.py        # 或 pytest 该文件

# 全量回归
python3 -m pytest scripts/tests -q
```

## 七、回滚命令

```bash
# 方式一:revert 本次 commit(分支内)
git revert --no-edit <本 commit hash>

# 方式二:分支未 merge,直接丢弃分支
git checkout main && git branch -D feat/223-overfit-monitor-timeout-20261006

# 方式三:只回滚代码文件到改动前
git checkout dc0f3a124 -- scripts/overfit_monitor.py
rm -f scripts/tests/test_223_overfit_monitor_timeout.py
```
> 无需回滚云上单元:**本次未改任何云上 systemd 单元**。

## 八、举一反三(只报不改)

扫描口径:**「外层无界(systemd `TimeoutStartSec` = 0 / 无 systemd 墙)且内层预算可能偏紧」**。
方法:云上 42 个 `trade-*.service` 逐个取 `TimeoutStartUSec` + `ExecStart`(只读)→ 得 **21 个无界**;
再对无界服务的包装脚本与其 Python 被调方 grep `run_to` / `timeout=`。
**本清单内一律未改**(除本任务点名的 `overfit_monitor.py`)。

### 甲、真同类(subprocess → `upload_r2.py`,与本次完全同型)
**全仓仅 `overfit_monitor.py` 一处已修**。其余 `upload_r2` 调用**都在 shell 层**
(`deploy.sh` / `update_all.sh` / `kelly_intraday_rerun.sh` / `r2_upload_async.sh` /
`staticdata_backup_async.sh`),无 Python 侧 subprocess 预算 ⇒ **无第二个同型站点**。

### 乙、外层无界 + 内层子进程预算偏紧(候选,按风险排序)

| # | 站点 | 内层值 | 下游 | 外层 | 备注 |
|---|---|---|---|---|---|
| 1 | `scripts/check_signals.py:289` | **30** | `sync_subscriptions_from_cf.py`(CF API 网络调用) | `trade-intraday-snapshot` = **∞** | **最像真风险**:网络型子进程 30s 偏紧,且超时后**仅 log 不抛**(静默) |
| 2 | `scripts/overfit_monitor.py:1438` | 60 | `notify.py`(冻结缺失告警) | `trade-overfit-monitor` = **∞** | 同一脚本另一处子进程(非 R2 链);notify HTTP 通常 <30s |
| 3 | `scripts/detect_intraday_anomaly.py:268` | 120 | `notify.py`(dedup 写失败告警) | `trade-intraday-snapshot` = **∞** | 同上 |
| 4 | `scripts/with_lock.py:129` | 60 | `notify.py`(排队超时告警) | `update_all`/`lab-auto` = **∞** | 告警发送 |
| 5 | `scripts/gen_schedule_stats.py:340,379` | 10 | `systemctl`/`launchctl`(本地查询) | `update_all`/`lab-auto` = **∞** | 10s 对本地查询够用,**不偏紧** |

### 丙、外层有界(梯度正确,不动也安全)
`check_data_gap_alerts.py:1430/1484`(120)、`check_monitor_heartbeat.py:97`(120)→ 外层 10min;
`signal_kelly_backtest.py:342`(60)→ `trade-kelly-intraday-rerun` 10min;
`s06_snapshot.sh` `run_to 300` → `trade-s06-snapshot` **55min**;
`nextday_gap_check.py:358` / `nextday_plan_generator.py:1181` / `gen_daily_brief.py:3116` → 外层 600
(**即 #223 ①/②/③ 待拍板项,单改会先被 systemd 硬杀,必须代码+云上同批**);
`turnover_backfill.sh` `run_to 900/7200` → 外层 ∞ 但均 > 600,合规。

### 丁、无 systemd 墙(`outer` 视为无界,但非生产定时链)
`scripts/agent_inbox_watcher.py:92`(120,dev 机 launchd)、`scripts/build_min.py:168`(300,被
`deploy.sh`/`main-merge.sh` 调用,无 systemd)。

> **#223 剩余待拍板项**(①`gen_daily_brief.py:3116` / ②`nextday_plan_generator.py:1181` /
> ③`nextday_gap_check.py:358` / ⑤`fetch_news.py:755`·`gen_daily_brief.py:3167`)与 ④ 的
> `fetch_news.py:722` 分支**本任务一字未动**(照单执行,§23.7 冻结契约 + 派单约束)。

## 九、自验清单

- **§23.2 修 bug 三铁律**:修完整(改动只在点名一处,无逐文件补丁面)/自测完成(30+ 断言 + 全量 264 passed)/
  同类错误面清单见 §八(全仓同型仅一处,已覆盖)。
- **§23.3 举一反三**:同模式(甲)/同数据源/同组件还被谁用(乙丙丁)清单 + 逐项覆盖结果,见 §八。
- **§21 算法公示**:N/A —— 本次只改超时预算,不动 track_score/评分/权重/分段/匹配规则,无算法公示点需同步。
- **§22 数据一致性**:N/A —— 无数据产物变更,无 R2/CF 同步点。
- **§23.5 产物落档**:本报告 + 生成脚本(测试)+ 复现段 + 配套 commit,四件套齐。
- **§24 前端防撕裂**:N/A —— 未改任何前端源(app.js/lab.js/common.js/index.html/sw.js)。
- **data/ 隔离**:未 `git add` 根目录 `data/` 任何文件。
- **分支自证**:commit 后 `git branch --show-current` = `feat/223-overfit-monitor-timeout-20261006`;只 push feat 分支,禁 push main,未强推。
- **诚实标注**:①任务前提「已有 `#223 勿擅改` 注释」在 `overfit_monitor.py` **不存在**(§三 门 ③);
  ②本改动**未经云上实跑**(云上外层实测=无界,但本层新值尚未在生产链验证);③乙表「是否偏紧」为判断,
  非实测超时统计。