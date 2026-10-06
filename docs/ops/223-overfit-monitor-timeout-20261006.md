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

## 十、补丁(2026-10-07):测试写死开发机假设致 CI 红(P0)+ 守卫「假墙」根因修

- 分支:`feat/223-4-ci-fix-20261007`(base=origin/main `6fe16ad83`);定级:**守卫真 bug + 测试环境假设**,两者同批修。
- 现象:GitHub Actions `quality-gate-static` 自 ④ 合 main(`2e1a564d5`)起 **连红 2 轮**(run #655 `38c172461` /
  #656 `5f78f586d`),`test_223_overfit_monitor_timeout.py:92` 断言「默认探测应 900」**实得 1**;**本机 mac 绿**。

### 10.1 根因(已确证,非推断)

两条独立病灶:
1. **测试侧(表面)**:断言注释写死「本机无 systemctl ⇒ 探测=无界」——CI Ubuntu runner **有 systemd**,该假设不成立。
2. **守卫侧(真 bug)**:`systemctl show` 对**不存在的 unit** 既不报错也不返回空,而是回填**编译期默认值**
   `TimeoutStartUSec='1min 30s'`(=90s, **exit 0**;上游依据 systemd/systemd#40046)。旧实现只 `--value` 取
   TimeoutStartUSec ⇒ 拿到 90s 这个**假墙** ⇒ `base(900) >= 90` ⇒ 守卫按「外层-余量」收成
   `max(90-300,1) = 1`s ⇒ **R2 上传 1 秒即被杀**(CI 实得 1 与之逐位吻合)。

**定性:守卫真 bug(生产风险成立)**,不只是"仅测试环境假设"。触发面:unit **改名**(常量 `_OVERFIT_SYSTEMD_UNIT`
与实际单元漂移)、**尚未 `daemon-reload`**(新写单元文件尚未加载 ⇒ LoadState 非 loaded)、**systemd 未就绪/查询失败**
—— 任一发生,守卫都会把 900 静默塌成 1s(只 warn 到 stderr,**不 notify 到人**),R2 上传链当场变哑。
现网暂未踩中(云上单元实测 `LoadState=loaded` + `TimeoutStartUSec=infinity`),属**潜伏型**,但代价与"无界"完全相反。

### 10.2 修法(根因修,不逐文件补丁)

- **守卫**(`scripts/overfit_monitor.py:_systemd_outer_wall_secs`):一次 `systemctl show <unit> -p LoadState
  -p TimeoutStartUSec` 取**两个属性**(带属性名前缀 key=value,免 `--value` 输出顺序依赖),**只有 `LoadState == 'loaded'`
  才采信 TimeoutStartUSec**;缺失 / not-found / error / masked / `returncode != 0` / 无 systemctl(异常)⇒ **一律返回 0
  (=无上界)⇒ 放行 base 900**,绝不塌到 1s。形态**对齐同根因先例** `gen_schedule_stats.py:_systemd_last_exit`
  (2026-09-22 同款:LoadState 守卫 + returncode 门 + key=value 解析)。
- **测试**(`scripts/tests/test_223_overfit_monitor_timeout.py`):①「默认探测」那条改成**契约不变量**
  (探测无界 ⇒ 恰 900 静默;探测有界 X ⇒ 0 < rc < X),mac/CI 两种语义都成立,断言里**不再出现"本机有无 systemctl"**;
  ②新增注入替身 subprocess 的矩阵(走真实探测代码路径),显式覆盖 not-found / 未 daemon-reload / 空输出 / error /
  masked / returncode≠0 ⇒ **都必须退化为 900**,另加两条反向断言(loaded+infinity ⇒ 900 静默;loaded+10min ⇒ 仍收回 300+warn,
  证明修复没把"有界真墙"一并放行)。断言数 30+ → **64**。

### 10.3 证据点(可复现)

1. **云上真机只读实测(新命令形态在本链真实环境下成立,§18 L49 真实样本)**:
   `ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'systemctl show trade-overfit-monitor.service
   -p LoadState -p TimeoutStartUSec'` ⇒ 逐字输出 **`TimeoutStartUSec=infinity` + `LoadState=loaded`**, `rc=0`。
   ⇒ 生产上 `outer=0 ⇒ 放行 900`(与修复前一致)。**附带实证**:真实属性输出顺序 = **与 `-p` 参数顺序相反**
   (我传 `-p LoadState -p TimeoutStartUSec`,`TimeoutStartUSec` 先说)—— 故解析**必须按属性名**,按位置会被真实环境证伪;
   测试已加"顺序颠倒 ⇒ 结果一致"断言守此点,样本亦改用**云上逐字顺序**。
2. **CI 复现(本机等价覆盖)**:`PATH` 注入假 `systemctl`(回放 CI 形态 `LoadState=not-found` +
   `TimeoutStartUSec=1min 30s`,exit 0)⇒ 跑**修复前**源码(HEAD)得 `outer=90 / rc_none=1`,**与 CI 实得 1 逐位一致**;
   跑**修复后**得 `outer=0 / rc_none=900`。⇒ mac 虽无 systemd,但**能造出与 CI 同形的探测响应**做等价覆盖。
3. **测试双环境绿**:mac 真实环境 `1 passed`;`PATH=/tmp/fakebin_ci:$PATH`(模拟 CI)`1 passed`。
   断言数两环境均 **64 断言全 PASS**。
4. **全量回归**:mac `264 passed, 1 skipped`;模拟 CI `262 passed, 3 skipped`(多出的 2 skip = #160/#196 在
   「检测到 systemctl」时按设计 `pytest.skip`,与真 CI 一致),**两端零 FAIL**。
5. **同类面(§23.2③,只报不改)**:`scripts/tests/*.py` 全量扫「依赖开发机环境」的断言 —— 命中仅本报此一处(已修);
   `test_160`/`test_196` 用 `shutil.which("systemctl")` → `pytest.skip`(**skip 而非断言**,环境无关,合规);
   `test_monitor_resource_inprogress` 的 `skipif(not _ON_LINUX)`(只在 Linux 断言 df 口径)是**有意为之且已注释**,合规;
   `test_resolve_repo_pytest` 无 bash 则 skip,合规。**同根因(采信 systemctl 假值)面**:`fapi_bj_width_export.py`
   守卫**根本不探测 systemd**(硬编码外层=0,有文档),无此缺陷;`check_failed_units.py` / `alert_denoise_rules.py`
   已按 LoadState/ActiveState + fail-loud 处理;`check_r2_consistency.sh` / `schedule_monitor.sh` 只看 ActiveState
   (not-found ⇒ inactive,方向安全)。⇒ **全仓同型守卫仅 `overfit_monitor.py` 一处,已修**。

### 10.4 复现命令

```bash
# 1) 造 CI 同形 systemctl(unit 不存在, show 回填默认; 顺序按云上实测惯例=与 -p 参数序相反)
mkdir -p /tmp/fakebin_ci && cat > /tmp/fakebin_ci/systemctl <<'EOF'
#!/bin/sh
printf 'TimeoutStartUSec=1min 30s\nLoadState=not-found\n'; exit 0
EOF
chmod +x /tmp/fakebin_ci/systemctl
# 2) 双环境跑测试(均应 1 passed; 也可直跑, 会打印断言数并给非零退出码)
python3 -m pytest -q scripts/tests/test_223_overfit_monitor_timeout.py
PATH=/tmp/fakebin_ci:$PATH python3 -m pytest -q scripts/tests/test_223_overfit_monitor_timeout.py
# 3) 全量(应 264 passed,1 skipped ↔ 262 passed,3 skipped)
python3 -m pytest -q scripts/tests/
# 4) 云上真机(只读; 期望 TimeoutStartUSec=infinity + LoadState=loaded)
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 \
  'systemctl show trade-overfit-monitor.service -p LoadState -p TimeoutStartUSec'
```

### 10.5 自验清单(§23.2/§23.3/§21/§22/§24)

- **§23.2**:修完整(同批修守卫+测试;同类面清单见 10.3-⑤)/自测完成(64 断言 + 双环境全量)/根因修(LoadState 门,
  非在断言处打补丁)。
- **§23.3**:「同模式/同数据源/同组件还被谁用」清单见 10.3-⑤(仓内 systemctl 消费点 6 处逐个定性)。
- **§21 算法公示**:N/A(只改超时守卫判定,不涉 track_score/评分/权重/分段/匹配)。
- **§22 数据一致性**:N/A(无数据产物变更,无 R2/CF 同步点)。
- **§24 前端防撕裂**:N/A(未改任何前端源;不 bump 版本串)。
- **§18 L49/L50/L48**:断言输入取**真实生产实测样本**(unit 名 / `infinity` / `1min 30s` / 属性名格式,均来自云上实测
  与上游 issue,未伪造);测试仍 **static-only**(AST 抽取 + exec,不 import 业务模块/不起真子进程);**零外发**
  (唯一外呼=只读 `systemctl show`,stub 断言独立保证)。
- **诚实标注**:①**CI 真机未实跑**(GitHub runner 不可本地复现;用 PATH 注入假 `systemctl` 做**等价覆盖**, 已见
  10.3-2 的 A/B 逐位吻合);②**云上业务脚本未实跑**(§18 L50 禁执行业务主体;但**新探测命令已在云上只读实跑**,
  见 10.3-1);③生产当前**未踩中**该潜伏路径(`LoadState=loaded` + `infinity` 已实测), 风险定性为"**潜伏型**"
  (触发条件:unit 改名 / 未 daemon-reload / systemd 未就绪);④本改动 `overfit_monitor.py` 是**生产定时链**
  (`trade-overfit-monitor`, 每天 21:40 一次)所用代码,merge 后**下一轮 21:40 日志应无 warn**=生产实证闭环。