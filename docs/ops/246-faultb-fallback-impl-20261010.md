# #246 故障 B 治本:B4-1 兜底链修复 + B4-2 重试策略(实施落档)

> 残留后台任务:**无**。本次未出现 `moved to the background (ID:`;全量 pytest 是自管 nohup 短任务(已回收),不留活进程。
> 分支:`feat/246-faultb-fallback`(worktree `agent-a173b32fb96985c3b`);只 commit+push 本 feat 分支,**未 push main**。
> 依据:`docs/ops/1009-real-faults-rootcause-design-20261009.md` §B④(L126-153)。**B4-3 不属本任务**(归 #245 批2)。

---

## 一、改法

### B4-1(i) `_fetch_intraday_open_via_http`(scripts/signal_kelly_backtest.py)

| 项 | 改前 | 改后 |
|---|---|---|
| 腾讯时间戳缺失/非当日 | `raise RuntimeError("腾讯行情 {code} 时间戳...当日性无法确认")` —— **该 raise 终止整条兜底链,新浪分支不可达**(缺口1) | 只把该标的记 missing,**继续降到新浪**;新浪自带日期字段(`split(',')[30]` = `YYYY-MM-DD`)作当日性锚 |
| 逐标的独立 | 单标的 raise 拖垮全链 | 每标的独立 try:腾讯失败→新浪失败→记 missing,**不 raise、不拖累其他标的** |
| 全失败 | — | 仅当**结果集为空**才 `raise RuntimeError("新浪/腾讯行情均未取得任何目标真实开盘价(数据就绪闸 FAIL, target=N)")` |

源优先级按设计文 **腾讯 → 新浪**(B③ 原文"腾讯→新浪单标的直连")。两源今开此前已实测逐位一致(设计文 §B②:9-23 两源 8/8 成功、逐位一致),故**不改变任何数值口径**,只提高失败态的成功率。

新增当日性判定辅助(纯函数):
```python
def _date_matches(field, expect):
    if not field:
        return False
    norm = str(field).strip().replace("-", "")
    head = norm[:8]
    return len(norm) >= 8 and head.isdigit() and head == expect
```
(取前 8 位 = 兼容腾讯 `[30]` 的 14 位 `YYYYMMDDHHMMSS` 与新浪的 `YYYY-MM-DD`;`expect_date` 为空则跳过当日性校验。)

### B4-1(ii) `_fetch_intraday_open_prices`(同文件)

- **缺列/空 df 不再直接 raise**:新增 `main_cols_ok` 判定(非空 + 含 `代码`/`开盘价` 列)。主源返回空或缺列 → 不再抛,沉入兜底(缺口3 的一半)。
- **日期陈旧并入兜底优先**:`_verify_spot_data_date`(F4)抛错 → 记 `date_stale=True` 不抛,整批下沉兜底(兜底拿的是**即时**行情,比东财昨日快照更新鲜,正是设计文缺口3 的原话)。
- **兜底范围放大**:原 `missing` 只对 `16` 前缀(LOF)补兜底(注释自认"主源成功时行为零变化"),现改为**对全部 missing 逐个补兜底**:
  ```python
  missing = [c for c in target if c not in out]
  if missing:
      out.update(_fetch_intraday_open_via_http(missing, expect_date=expect_date))
  ```
- 收尾 `if not out: raise RuntimeError("akshare 未返回任何目标 ETF/LOF 的真实开盘价(数据就绪闸 FAIL)")` **保留** = 数据就绪闸 fail-closed 语义不变。

### B4-2 重试策略(scripts/nextday_gap_check.py + 包装/监控/文档)

采用设计文**推荐档 = 兜底修复 + 60s×3 退避(带 jitter,总预算硬顶)**:

- 常量:`RETRY_BACKOFF_BASE_S=60` / `RETRY_JITTER_FRAC=0.25`(每轮 60×[0.75,1.25] = 45~75s)/ `RETRY_BUDGET_S=900` / `DEFAULT_RETRY_ROUNDS=3`(首拉 + 3 轮重试 = 4 attempts);删原 `DEFAULT_RETRY_WAIT=300`。
- 新纯函数 `_retry_backoff_schedule(rounds, base, jitter, budget, rng)` → 返回等待秒表,逐轮累加**不超预算**(超则截断),达预算即截断;`rng` 可注入 ⇒ 可确定性测试。
- `main()` 重试循环改为按 schedule 逐轮退避;成功于 attempt>1 时日志 `✓ 重试成功(第{attempt-1}次失败后重试)`(**逐字保留该串**,供 `gen_schedule_stats.py` 的 `GAP_RETRY_SUCCESS_RE` 匹配);失败中间日志 `⚠ ... 第 N 次`(**逐字保留**,供 `TRANSIENT_WARN_LINE_RE`)。
- CLI:`--retry-wait` 语义改为"退避基数"(默认 60),新增 `--retry-rounds`(默认 3),`--no-retry` 不变(单次 attempts=1)。
- 告警文案:severe 由"拉取 akshare 开盘价两次失败" → "拉取开盘价多轮重试(60s×3 退避)后仍失败";`nextday_gap_check.sh` 包装层 dedup 文案同步("主源+腾讯/新浪双源兜底多轮退避后均取不到")。
- `scripts/schedule_monitor.sh`:两处注释(阈值段)更新为"60s×3 退避(≈180~225s,硬顶预算 15min)";**阈值数值 900 不变**。
- `docs/deploy/systemd-units-20260912.md` L675 父级说明 "300s 重试" → "60s×3 短退避重试,2026-10-10 #246 B4-2"(ini 块外,服务单元生成器源文档;`--check` 不受影响)。

---

## 二、测试红绿证据

新增 `scripts/tests/test_246_faultb_fallback_20261010.py`(14 test,299 行):
- 打桩工具:`_tencent`/`_sina`(构造 GBK 原文)/`_Resp`/`_GetStub`(URL 白名单,**未预期 URL 即 AssertionError = 防打桩漏网**)。
- autouse fixture 兜底补 `requests.RequestException`(CI stub 的 requests 无此属性)。
- **§18 L48 零外发**:全部 HTTP 走打桩;`test_246_retry_loop_uses_schedule_and_attempts` 另打桩 `_severe_alert`/`_sync_r2_and_notify`/`time.sleep`/`_fetch_opens`,REPO/GIT_REPO 指 tmp_path,`--dry-run` ⇒ 全程无真实网络、无真实告警、无真实落库。

覆盖矩阵(14 项):
| # | test | 覆盖点 |
|---|---|---|
| 1 | `..._tencent_ts_missing_degrades_to_sina` | B4-1(i) 缺口1:腾讯时间戳缺失 → 降级新浪成交 |
| 2 | `..._tencent_ok_prefers_tencent` | 源优先级 腾讯>新浪(腾讯可用时不请求新浪) |
| 3 | `..._per_target_independent` | B4-1(i) 逐标的独立:一标的腾讯+新浪双败,另一标的仍取到;不 raise |
| 4 | `..._all_missing_raises` | 全失败才 raise(就绪闸 fail-closed 保留) |
| 5 | `..._sina_date_mismatch_rejected` | 新浪日期非当日 → 拒绝(不被旧价污染) |
| 6 | `..._no_expect_date_skips_date_anchor` | expect_date=None 时跳过当日性校验 |
| 7 | `..._prices_partial_missing_falls_back_for_15prefix` | B4-1(ii) 缺口2:**15 前缀**(非 16)缺价也走兜底 |
| 8 | `..._prices_date_stale_falls_back` | B4-1(ii) 缺口3:日期陈旧 → 全批下沉兜底 |
| 9 | `..._prices_normal_path_no_fallback` | **正常路径零变化**:healthy 主源 → requests.get 调用数 = 0 |
| 10 | `..._retry_backoff_schedule_shape` | B4-2 schedule = `[60,60,60]`、长度 3 |
| 11 | `..._retry_backoff_jitter_bounds_and_budget` | jitter ∈ ±25%;预算截断生效 |
| 12 | `..._retry_loop_uses_schedule_and_attempts` | main() 真按 schedule 走 4 attempts 且退避值来自 schedule |
| 13 | `..._retry_fn_exists` | 常量/函数到齐 |
| 14 | `..._via_http_source_of_truth_static` | ast 静态检查:源码里 tencent 在 sina 之前(防顺序漂移) |

**红先验(旧码跑新测试必 fail)**:把**未改动的**测试文件对**原始码**跑 → `10 failed, 4 passed in 0.86s`。
- 10 红 = 缺口1/2/3 + 逐标的独立 + 源优先级 + 全部 B4-2 项(全在旧码上 fail,证明测试确实锚住了本轮改动)。
- 4 绿 = **刻意不变**的行为(#4 全失败 raise / #5 新浪日期校验 / #6 expect_date 空 / #9 正常路径零变化)——旧码本就正确,红先验里仍绿 = 反证"我没顺手改正常路径"。

**绿(改后)**:`14 passed in 0.40s`。

**CI 同款全量**:`/Users/linhuichen/code/trade/.venv/bin/python -m pytest -q scripts/tests/` ⇒ 见文末"最终全量结果"节(改前基线 670 passed / 2 skipped;本轮 +14)。无失败;2 项 skip 为**存量**(与本改动无关,非我引入、未静默掩盖)。语法:`py_compile` 两 py OK;`bash -n` 两 sh OK。

---

## 三、行为变化清单(逐条)

| # | 变化 | 触发条件 | 影响 |
|---|---|---|---|
| 1 | 腾讯失败(含时间戳缺失)→ 新浪兜底 | 腾讯不可用/时间戳非当日 | **失败率改善**:原"待人工"的标的可能被救回;拿到仍是真实当日开盘价 ⇒ **非口径变化** |
| 2 | 逐标的独立,单标的失败不再拖垮全链 | 任一标的双源失败 | 其余标的照常;仅该标的记 missing |
| 3 | 主源"成功但个别标的缺价"→ 全部 missing 兜底(原仅 16 前缀) | 主源返回不含某 15 前缀标的 | 同上,失败率改善 |
| 4 | 日期陈旧不再直接 raise,改走兜底(即时行情) | F4 判东财快照日期陈旧 | 用即时价替代陈旧快照,仍是真实开盘价 |
| 5 | 空 df / 缺列不再直接 raise,沉入兜底 | 主源返回异常 | 同上 |
| 6 | 重试:单次 300s → 60s×3 退避(45~75s×3) | 9:26 首拉失败 | 重试窗口 ~180–225s(vs 原 300s);告警延迟上限下降 |
| 7 | `--retry-wait` 语义=退避基数(默认 60);新增 `--retry-rounds`;`--no-retry` 不变 | CLI | 向后兼容(默认行为变,但语义标注清晰) |
| 8 | 三处告警/监控注释文案更新;阈值数值**不变** | — | 纯文案 |
| 9 | **正常路径(主源健康)零变化** | 主源成功且全部 target 有价且日期新鲜 | test#9 机检 requests.get 调用数 = 0 |
| 10 | gap 判定阈值/口径**未动**(`|gap|>20%` 等原样) | — | §23.7 已获用户批准只动失败路径 |

**口径 / 版本注记**:按用户 2026-10-10 拍板 —— **不发版本注记**(失败率改善非口径变化,不升级测试基准,§5.4⑥)。设计文亦同结论("不动测试基准,是否发 patch 由用户拍板")。

---

## 四、风险与警示(诚实标注)

**R1(需主控拍板的既有约束,非本改动引入)**:`RETRY_BUDGET_S=900`(15min,取自设计文"总预算 ≤15min")**大于**云上 `trade-nextday-gap-check.service` 的 `TimeoutStartSec=600`。含义:
- 默认配置(60×3,jitter 后 ≤225s)远低于 600 ⇒ **现状无风险**,且**比改前更安全**:旧码单次 300s + R2 ≤300s 可能达 ~600 触墙,新码 ≤225s + 300 = ~525 < 600,梯度余量反而变大。
- 但 900 这个"硬顶"在 systemd 600s 墙面前**无法真正兜住超长配置**(如误传 `--retry-rounds 15`)。设计文假设外层可到 900(#223 亦记"若做 retry 组合须按外层 900 重算"),而**当前云上仍是 600**;提外层墙是云上 unit 手动管理动作(非本 feat 能覆盖)。
- **建议(待主控决策)**:①稳妥 = 把 `RETRY_BUDGET_S` 下调到 ≤450(保梯度);②或维持 900 并在云上把 `TimeoutStartSec` 提到 900。**本实现按设计文原值 900 落地,未擅自偏离**,此处只如实标注。

**R2(存量,非本改动引入)**:`scripts/nextday_gap_check.py` 内 `timeout=300`(R2 上传子进程,L399 附近,#223③ 已记录"触发 0 次 ⇒ 不动")本次**未改动**;`timeout=60`(L106)/`timeout=120`(L422)亦未动。

**R3**:若未来有人调用 `_fetch_intraday_open_via_http` 时传错 `expect_date`,`_date_matches` 会全判不匹配 → 单标的全记 missing → 上游收尾 `if not out: raise` 仍 fail-closed,不会静默给出错价(安全侧)。

---

## 五、自验(§23.2 / §23.3 / §23.4 / §21 / §23.7)

### §23.2 修 bug 三铁律 —— 同类错误面清单(含"已排查但不动"的说明)

同一病灶族(兜底链 raise 早退 / 单标的拖垮全链 / 缺价不兜底)全景排查:

| # | 位置 | 结论 |
|---|---|---|
| 1 | `_fetch_intraday_open_via_http` 腾讯 ts 缺失 raise | **本次修**(缺口1) |
| 2 | 同上:单标的失败拖垮全链 | **本次修** |
| 3 | `_fetch_intraday_open_prices` 仅 16 前缀兜底 | **本次修**(缺口2) |
| 4 | 同上:日期陈旧/空 df/缺列直接 raise | **本次修**(缺口3) |
| 5 | 同上:全批无价时的收尾 raise | **保留**(就绪闸 fail-closed,刻意) |
| 6 | `nextday_gap_check.py` 重试单次 300s | **本次修**(B4-2) |
| 7 | `_etf_spot_fallback.fund_etf_spot_df()`(东财→新浪→腾讯全称) | **不动**:无开盘价列,不属本链路;其多源实现已是范式 |
| 8 | 其它 akshare 单源调用(设计文 §B⑤ 粗筛表) | **不动**:超本任务范围(B 项只治 gap_check 链路);§B⑤ 表已由设计文登记 |
| 9 | `timeout=300/120/60`(R2/子进程) | **不动**(#223③ 已记"触发 0 次") |

### §23.3 举一反三 —— 同模式/同数据源/同组件还被谁用

| 维度 | 清单 | 覆盖结果 |
|---|---|---|
| 同组件(该函数)调用方 | `_fetch_intraday_open_via_http` 仅 `_fetch_intraday_open_prices` 调;后者仅 `nextday_gap_check.py:L156` 调 | 已被本改动统一覆盖 |
| 同组件(读开盘价)其它调用方 | `signal_kelly_backtest.py:2054` 盘中重跑:**仍对 any missing raise**(fail-closed 保留,未放宽) | 已核:改动只影响 missing 来源,不影响其 fail-closed 语义 |
| 同数据源(东财 push2 家族) | deploy 链 `etf-fallback`、backfill 等 | 各有兜底(设计文 §B②③ 已证);不在本任务范围 |
| 同模式(重试语义) | `DEFAULT_RETRY_WAIT` 仅 nextday_gap_check.py 用(grep 全仓) | 改动无外溢 |
| 同模式(monitor 集成) | `gen_schedule_stats.py` 两条 regex(`✓ 重试成功` / `⚠ 第 N 次`)、`schedule_monitor.sh:216/678` | 日志串**逐字保留** + 注释同步;阈值 900 不变 |
| 相关展示位(前端) | gap-check 结果→首页/计划页"伪跳空剔除"标注 | 文案无变化(仅后端行为改善) |
| 文档链 | systemd 单元源文档 / 包装脚本 / 监控脚本注释 | 三处已同步 |

### §23.4 团队协作 / pending-features-index

- `docs/pending-features-index.md` 扫描:**#246 未单列**为独立编号项(本轮由主控补号入册);**B4-3 属 #245 批2**(另一在跑 agent),**与 B4-1/B4-2 无文件冲突**(B4-3 只碰 `notify.py` REPO + `nextday_gap_check.py` 告警 dedup key + monitor 段 —— 其中 `nextday_gap_check.py` 是**共享文件**)。⚠️ **已识别共享面**:本改动改了 `nextday_gap_check.py` 的告警文案/常量区;B4-3 会改同文件的 `--dedup-key`(py 侧)。两改**不同代码段**(告警文案 vs dedup key 参数),但同文件 ⇒ merge 时若两 feat 都上 main 需注意顺序/冲突(已上报主控)。
- 无同模块"后覆盖前"风险(未发现与本任务抢同一行的在建项)。

### §21 算法公示同步 —— **不触发**

grep 前端:`static-site/purpose-notes.js` 命中 0;`static-site/lab.js` 仅 L14591 "伪跳空剔除"标签(未改)。本改动**不动 track_score/评分/权重/阈值**,且不改变任何数值口径 ⇒ 无公示点需同步。

### §23.7 冻结契约

失败路径加固**已获用户 2026-10-10 批准**(派单原文:"§23.7 本项已获用户批准动失败路径");**正常路径与口径未动**(见行为变化表 #9/#10)。gap 判定阈值 `|gap|>20%` 原样保留。

### §23.11 git 纪律

全程 feat 分支;未 push main;未 add 根 `data/` 下任何文件;`git diff --stat` 与预期一致(见下);无静默覆盖/倒退/吞冲突。

---

## 六、最终全量结果(实跑)

```
$ /Users/linhuichen/code/trade/.venv/bin/python -m pytest -q scripts/tests/
684 passed, 2 skipped in 92.00s (0:01:32)   EXIT=0

$ ... -q -rs scripts/tests/   # 追问 2 项 skip 归属
SKIPPED [1] test_212_upload_onfail_loud_pytest.py:386: 已提交态(HEAD==工作区): 改前版不可得, 跳过静态对照
SKIPPED [1] test_monitor_resource_inprogress_20261005.py:183: macOS APFS 的 df 为容器级口径, 与 statvfs 卷级不同
684 passed, 2 skipped in 90.56s
```

- 2 项 skip **均为存量、均非本改动引入**:
  - `test_212:386` = git 状态型条件(该测对比 `upload_r2.py` 改前/改后版;本改动未碰该文件 ⇒ HEAD==工作区 ⇒ 按设计跳过)。改前改后两轮均如此,**跳过与否与本改动无关**。
  - `test_monitor_resource_inprogress:183` = macOS 专有(df 口径差异);**CI(Ubuntu)上会真跑,不跳**。属既有环境性分支,非我新增。
- 本改动新增的 test 文件**0 skip**:14 项全绿(`14 passed in 0.40s`);其 `importorskip(yaml/pandas)` 仅为 CI 缺依赖时的模块级兜底,**本机与 CI(⑧ 已装 pyyaml/pandas)均不触发**。
- 改前基线**未单独实跑**(诚实标注);由现 684 − 本轮新增 14 = **670 推算**。**无"用 skip 掩盖失败"**:本轮新增的 14 项全绿、无 skip,skip 总数未被抬高。

## 七、产物清单

改动(5 改 + 1 新):
- `scripts/signal_kelly_backtest.py`(+161/- 内,B4-1)
- `scripts/nextday_gap_check.py`(B4-2 常量/纯函数/重试循环/CLI)
- `scripts/nextday_gap_check.sh`(dedup 文案)
- `scripts/schedule_monitor.sh`(两处注释)
- `docs/deploy/systemd-units-20260912.md`(1 行说明)
- `scripts/tests/test_246_faultb_fallback_20261010.py`(**新**,14 test)
- 本报告 `docs/ops/246-faultb-fallback-impl-20261010.md`(**新**)

复现命令:
```
/Users/linhuichen/code/trade/.venv/bin/python -m pytest -q scripts/tests/test_246_faultb_fallback_20261010.py
/Users/linhuichen/code/trade/.venv/bin/python -m pytest -q scripts/tests/
```