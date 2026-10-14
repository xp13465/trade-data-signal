# trades 历史行「重算抹除」根治(A 包)独立审查报告

- 审查对象: `origin/fix/trades-wipe-rootfix-20261014`(tip `42d50eb99c`;merge-base `d45fcd4c5`;13 文件 +1457/-43)
- 对应任务: #252(A 包);根因报告 `docs/ops/trades-wipe-rootcause-20261014.md`、实施报告 `docs/ops/trades-wipe-rootfix-20261014.md`
- 审查身份: reviewer 子 agent,独立于实施方,fresh context
- 审查方式: 全程只读(不在主仓做任何 git 写操作;未改/删任何已跟踪文件;唯一新增文件=本报告)
- 安全约束执行: 全部命令带工具级 timeout;curl 一律 `-s --max-time` 禁 `-v/-i`;未跑任何会被真外发的脚本(复跑前先打桩并证生效,见 §3.5);探针一律 lib 级、只写 DB 副本;未跑 `find /`、未裸跑 pip/npm;数据事实以云上权威库为准(SSH 只读;远程命令无 `$` 变量)
- 残留后台任务: 无(无 `moved to the background` 事件)

## 0. 结论

**PASS —— 未发现阻断级(BLOCKER)问题,本分支具备 merge 资格。** 必改 0 项;建议 5 项(不阻断);提示/交主控 5 项。

独立复核覆盖: 必查清单 11 项全部完成;实施方 §8.1 承诺的证据用例逐条换人复跑(**含其声称 PASS 的 ①-⑤⑧ 全部复现为 PASS;其声称 FAIL/未跑的 ⑥⑦ 我独立补跑并定位性质**);T2 全部核心数字独立复算逐位吻合;新增机制用**云上权威库真实行样本**做 lib 级探针验证全绿。

## 1. 必查清单 11 项逐项判定(全部 CONFIRMED,无 FAIL)

| # | 项 | 判定 | 一句话证据 |
|---|---|---|---|
| 1 | §10.8 边界完整性独立复核 | **CONFIRMED** | 先独立自推 7 维度边界清单,再与实施方 §6(12 行)对账,分三类 + 差集逐条处置(见 §2) |
| 2 | §10.7 证据用例真跑过 + 预期达成 | **CONFIRMED** | §8.1 逐条换人复跑:①-⑤⑧ 复现 PASS;⑥ FAIL(预存在,已独立复现到层);⑦ 实施方未跑→我补跑并定位「main 亦 FAIL」= 预存在;§5.7 预期全部达成(见 §3) |
| 3 | §15 影响面穷举 + 回归 | **CONFIRMED** | 6 大改写点 + notify 出口逐点核(见 §4);P0 冒烟基线在(overview/scores 非空、sh-all ohlc 4072/signals 538、alert 20261013 正常) |
| 4 | §18 L49 假样本养绿独立复核 | **CONFIRMED** | 测试样本形状=真实库行(8 元组,列序与 schema 逐一比对);另以云上真实行样本 lib 级探针全绿(见 §3.5);「生产侧实跑」属上线后观察点→提示 6 |
| 5 | §18 L48 零外发独立复验 | **CONFIRMED** | 我的独立沙箱复跑(正控 SANDBOX-OK 先证生效,全用例无子进程 notify.py);真样本探针把 `subprocess.run` 打桩,3 次告警调用全被拦截(计数 3),源文件零变化 |
| 6 | T2 数字独立复算 | **CONFIRMED** | 买信号 42221→42262(+41);trades 339548→341352(+1804);880 格变好 151/变差 564/不变 165、最大 \|Δrmh\|=1.8569pp(@sig_main/y10/J) —— 全部逐位吻合;base_trades.json md5=`99fff222…` == 线上 ETag(逐字节级对账);base_vs_live backtest 深度相等(排除 generated_at)=True;T2 默认真关(见 §3.2) |
| 7 | F1 CI ⑥⑦ 门禁空转独立认定 | **CONFIRMED** | run 38498123925/38105915179:quality-gate-data 步骤5 success、⑥⑦ skipped、job conclusion=success;`.github/workflows/ci.yml` L138-165 下载步骤恒 exit 0 + `if: ok=='1'` 门控 + job `continue-on-error: true` 三重叠加 |
| 8 | F2 生产 kelly_loss_features 与挖掘 20260824 不一致 | **CONFIRMED(不选边)** | 独立搭副本跑 ⑥:层3 PASS(14)/层1 PASS(12 特征)/**层2 FAIL:S1/S2 各 2 行不一致**(样本:20260824 buy_aux 挖掘=False 生产=True);实施方把层2 误写成「层1 特征 20 项」(建议 5) |
| 9 | §21 算法公示同步 | **CONFIRMED** | 分支零前端改动(13 文件无 JS);T2 默认关=不改用户可见数字 ⇒ 无需公示;orphan 告警默认关且非公示对象;若未来翻默认则按 §5.4⑥/§23.7 走版本+公示(实施方已写明) |
| 10 | §23.7 冻结契约 | **CONFIRMED** | T2 默认关:`os.environ.get("SIGNAL_KELLY_FREEZE_UNION","0")=="1"` 才启用,全仓 grep 无生产设置点;默认口径产物与线上逐位一致(§3.2 对账);「翻默认须用户拍板」写入代码注释与报告;止血脚本「未跑」是刻意的(§5) |
| 11 | §14/§25 止血脚本未执行 + 只读安全 + 防前视 | **CONFIRMED** | 全新文件、无任何 cron/systemd/timer 挂载(只有文档与测试引用);`mode=ro` URI 双库只读;`next_open_after` 严格 `date > sig_date`(t+1,防前视);ETF 取冻结表记录值(成交日冻结,非现值 best);`--out` 缺省只打印 |

## 2. §10.8 边界完整性对账(先独立自推,后对账)

我独立自推的 7 维度边界清单(不看实施方 §6 先写): ①signal_daily 全部写方 ②index_daily 全部写方(含局部 UPDATE) ③同模式「整段 UPSERT 覆盖历史行」其它表(daily_metric/width 系/个股系/公募系) ④append-only 过程历史表 ⑤固化/冻结类产物 ⑥每日重生派生产物 ⑦审计动作自身的边界(表增长/并发窗口/出站)。

对账结果三分类:

| 类 | 项 | 处置 |
|---|---|---|
| **双方都列(一致)** | signal_daily 全表重算(实施 #1);index_daily 整段 UPSERT(#2);index_backfill 3 处兜底(#3);intraday 计算法局部 UPDATE(#4);intraday 当日反哺/补采 3 处(#5);daily_metric 及 width 系「已有 source!='manual' 保护」(#6/#7);个股/公募(低风险标注,#8/#9);signal_intraday_log append-only(#10);freeze.json 只增不改(#11);signal_stats/trades 类每日重生(#12) | 全部独立核证成立:保护 SQL 实测在(runner.py:107/123、bj_width.py:191/246、cleanup_d3d2.py:452/558、app/backfill_lianban.py:368);#5 三处逐点核 date 参数=today,均无历史写能力(1179/1512 另有「快照日期≠今日跳过」守卫@1172/1501,1364 有非交易日守卫@1352) |
| **我列它没列(差集→处置)** | ①审计动作自身边界(表增长无清理/并发窗口噪声/告警失败留痕强度) ②fapi 域 `daily-k.parquet` 整文件重写(独立子系统) | ①已逐条评估→建议 1、提示 9;②判定「非本根因面,可接受范围外」→提示 8(交主控决定是否另立观察) |
| **它列我漏(补充理解)** | 实施 #5 的「当日行审计范围外」判据(我原先只把它当「单行写入」,未细究日期语义) | 已逐点核验判据成立(见上表) |

差集均逐条处置,无「发现了但没下文」的悬空项。

## 3. 关键复核细节(证据点)

### 3.1 T2 数字独立复算(全吻合)
- 平台:`/tmp/t2run/out/{base,union}_backtest.json` + `{base,union}_trades.json`(实施方留存的同库同引擎产物);我另在 `/tmp/reviewer_t2/` 独立下载线上产物对照。
- 880 格复算(脚本独立自写,直接读两 JSON): better/worse/same = **151/564/165**,total=880;max |Δrmh| = **1.8569pp** cell=(sig_main,y10,J) —— 与实施方报告 §4.2 数字逐位一致。
- 象限表整表复算: 报告 §4.2 的 15 行数字全部一致;**发现漏列 sig_special 行(实测 n 3485→3490,rmh 8.3031→8.2761,Δ-0.03)** → 建议 4。

### 3.2「默认关=行为零变化」的逐字节证据(§23.7 核心)
- `base_trades.json` md5 = `99fff222c97cbba30eb56e513e1e3fcd`,**==** 线上 `signal_kelly_trades.json` 当前 ETag(复查两次一致);
- `base_backtest.json` vs 线上下载 `live_now.json`: 排除 `generated_at` 后**深度相等 True**(两者均 564,104B);
- T2 开关默认值复核: `FREEZE_UNION_ENV` 默认 "0"、`FREEZE_ORPHAN_ALERT_ENV` 默认 "0",全仓无生产环境设置点;默认运行仅向 stderr 打印孤儿数量(36 条),不发通知。

### 3.3 CI ⑥⑦ 空转(F1)+ ⑦ 补跑定位
- F1 属实(行号级证据见必查 7);
- 我独立补跑 ⑦ `check_fade_predicate_parity.mjs`(TRADES_JSON 指向 base_trades.json、FEAT_JSON 指向线上特征):**FAIL —— home.whitelist 断言 p8(8 键)≠_AI_MACRO_FILTER_NAMES(10 键),差 k3ConceptBuy/r10May6NonMay**;
- 关键定性: 在**主仓 main 工作树**用同参复跑得到**逐字符相同**的 FAIL ⇒ **预存在问题、非本分支引入**(分支 13 文件不触前端);该证据同时说明:⑦ 若被启用会直接转红 ⇒ 归入 #261(CI 门禁空转)修复时的必解项(提示 7)。

### 3.4 F2(交主控,不选边)
- 层级修正: 不是「层1 特征 20 项」而是**层2(20 键谓词一致性)**:S1/S2 各 2 行不一致,样本 `20260824 buy_aux`(挖掘快照=False,生产=True);层1(12 特征)与层3(14 项)均 PASS。
- 本报告不选边:生产口径是否应为 True、挖掘快照是否过期,证据在案交主控/用户裁。

### 3.5 真样本 lib 级探针(L49 精神;全绿)
脚本 `/tmp/reviewer_probe/probe_real_sample.py`(只 import lib + 调纯函数;DB 用云上快照副本;`subprocess.run` 先打桩并断言生效):
- 旧库兼容: 去 `source` 列 + 去审计表 → 分支 SCHEMA+`_migrate` 恢复列/建表,**幂等二跑 OK**(duplicate 忽略);
- 真实行(csi_000673/20261012 close=3057.907):原值回写→0 误报;close+1.0→1 条 changed 且 before/after 字段正确落表;1e-7 相对噪声→0 误报(容差有效);
- 真实 signal_daily 行删除(20261012 cgb_10y_etf/band_hold)→**disappeared 正确捕获**;同三元组纯回填(仅出现)→appeared 且**不落表不告警**(设计符合);
- 局部字段审计: 历史行改 close→1 条;当日行(整行/局部)→0(范围外守卫成立);
- 出站: 3 次告警 subprocess 全部被拦截(计数 3,首条 subject=「[历史行改写] index_daily…」),**零真外发**;副本源文件大小不变。
- 附带观察(提示 9): 审计表在「不走 `get_conn` 的直连连接」上会缺表 → 被 except 容错为 print 不阻断;生产主链路均走 `get_conn`(首跑 executescript 建表),不受影响。

## 4. §15 影响面清单(改动文件 × 被谁引用 × 回归结论)

| 改动点 | 被谁引用/触发 | 独立核验结论 |
|---|---|---|
| `app/compute/signals.py::store`(+2 审计调用,全 try/except) | 盘中每轮 `_recompute_signals`、17:50 `compute/runner`、lhb/rzhb 补采链、index_backfill 重算 | 快照在 DELETE 前、diff 在 commit 后(signals.py:1452/1455/1463/1466);快照失败/审计失败均回退为不阻断;主产物行为不变(17 行改动全部为“包裹式”) |
| `app/collector/runner.py::upsert_index_rows(rows, source="collect")` | index_backfill THS 分支(`upsert_index_rows(rows)`)、intraday 行业内补采 | 审计在 executemany **之前**(读 pre-write 值,正确);`[tuple(r)+(source,)]` 形状与 9 占位符逐一核;整段 UPSERT 语义未变(仅多写 source 列);消费者侧 falsy-0 source 语义无影响(新增列,旧代码不读) |
| `app/collector/intraday_snapshot.py`(4 INSERT 带 source + 1 calc UPDATE 加审计) | trade-intraday-snapshot timer(:25/:35/:55 起 + 20:35 一轮) | 4 处 INSERT 全部 date=today(2 处带快照日期守卫);calc UPDATE 面向 `target_date`(可历史)→ 已接 `_audit_hist_partial`(局部字段,不误报);4 处 INSERT 的 source 实参逐一核=常量 `'intraday_snapshot'`(1179 参传/1364/1512 SQL 字面量),calc 位= `'calc'`(1249 INSERT 参传/1314 UPDATE 字面量) |
| `app/db.py`(`_migrate` 加列;SCHEMA 加表) | 全部 `get_conn()` 调用方 | `duplicate column name` 并发容错在;新列/新表为纯增量;旧行 source=NULL(未标注)语义明确 |
| `app/history_audit.py`(新,284 行) | store / runner / index_backfill / intraday 四路 | 判据独立评审:只审 `date < run_date`(YYYYMMDD 字符串比较);disappeared=集合差;纯回填不落表;容差相对 1e-4+绝对 1e-6;跨行无副作用(真样本探针背书) |
| `app/notify_hook.py`(新,62 行;runner._notify 下沉) | runner 5 处调用点、history_audit | 行为等价核到 argv 级:唯一差异=选项**顺序**(新:--from-prefix 在前/--severe 末尾;旧:--severe 在前)——`scripts/notify.py` 全为 argparse 选项+`nargs="?"` 位置参 ⇒ 语义等价;fail_hook 双通道留痕保留(_notify_fail_trace 原样传入);timeout=60/check=False/capture_output 全保留 |
| `scripts/signal_kelly_backtest.py`(T2 块 397-480) | 每日入账产物生成(run_daily 链) | 默认关;`_detect_freeze_orphan_buy_events` 判据=整行缺失(信号类型漂移不算孤儿,与既有 `_freeze_fallback` 互补,不重复);默认 stderr 打印 36 条;告警/入账均 env 门控 |
| `scripts/trades_orphan_backfill.py`(新,171 行) | 仅手动(无任何挂载) | 只读+防前视(见必查 11);`_skb()` 复用回测模块的孤儿检测(**无第二份实现**,符合 §5.4⑦) |
| 前端/export/R2/邮件链 | — | 分支零前端、零 export/R2 改动 ⇒ §21/§24/§22 不涉;邮件预警链未动 |

## 5. Findings

### 必改(BLOCKER 级)
**无。**

### 建议(不阻断 merge;按影响排序)
1. **history_audit 告警失败留痕弱一档**: `_alert` 调 `send_alert` 未传 `fail_hook`(history_audit.py:280),失败时仅 stderr 单通道;runner 路径是 collect_log DB 行+stderr 双通道(2026-08-23 P1-E4 精神)。建议下轮补 fail_hook(可直接复用 `runner._notify_fail_trace` 同款 log_collect)。
2. **T2 告警是第 3 份 notify.py 协议副本**: `signal_kelly_backtest.py:455-462` 手写 subprocess 调 notify.py(未走本分支同 PR 新建的 `app.notify_hook.send_alert`,而该脚本已有 `sys.path` 可 import app);与 notify_hook docstring 自述的「同一调用协议多副本必然漂移」原则自相矛盾,且同样只有 stderr 留痕。建议收敛(或注释说明为何不能)。
3. **runner.py 重构遗留死代码**: `_NOTIFY_PY`(runner.py:22)与 `import subprocess`(runner.py:11)在委托 send_alert 后已无使用点,建议随手清理。
4. **实施报告 §4.2 象限表漏 sig_special 行**(实测 n 3485→3490、Δrmh -0.03):报告完整性修正;结论数字(151/564/165)不受影响。
5. **实施报告 F2 层级措辞错误**:「层1 特征 20 项」应为「层2(20 键谓词)」+「S1/S2 各 2 行」;事实本身成立(我已独立复现)。

### 提示(交主控决策/周知,不阻断)
6. **运维告知(重要)**: 上线后,每当发生历史行改写即触发 severe 告警(signal_daily 去重 1h、index_daily 去重 24h,均 severe=True 手机可见);按根因调研,历史改写是**常态化**现象 ⇒ 用户可能**每天**收到「[历史行改写]」告警。这是本包设计意图(让不可见变可见),但需主控/用户预知,避免误判为新事故;若嫌吵可先评估规模再决定告警策略(代码内已留 dedup)。
7. **⑦ 门禁若启用会红**: 预存在 FAIL(p8≠names,差 k3ConceptBuy/r10May6NonMay;main 同)。请归入 #261 修复清单(与 F1 空转是同一问题的两面)。
8. **范围外提示**: fapi 域(`daily-k.parquet` 整文件重写)未在本包边界扫描内;判定非本根因面(独立子系统),是否另立观察由主控定。
9. **低危观察**: ①审计 SELECT 与后续写非原子(并发窗口会产生审计噪音,概率低) ②`history_overwrite_audit` 无清理策略(增长缓慢,可留观察) ③直连非 `get_conn` 连接遇审计表缺失时会静默降级为 print(设计容错,已探针验证)。
10. **报告行号微漂移**: 实施报告 §6 #5 引用行号(1166/1350/1498)与实际写入点(1179/1364/1512)差 ~13 行;判定结论(当日行)经我逐点核验成立,仅引用精度问题。

### 置信度过滤说明
- 本轮未静默丢弃任何候选发现;上述建议/提示项完整列出,0 条因「工作量/不确定」被滤掉。

## 6. 复现指引(关键命令)

- 分支 diff: `git -C /Users/linhuichen/code/trade diff origin/main...origin/fix/trades-wipe-rootfix-20261014`
- 880 格复算: 读 `/tmp/t2run/out/{base,union}_backtest.json`,`return_pct_max_holding` 逐格 diff(见本报告 §3.1;独立脚本一行式)
- 线上对账: `md5 -q /tmp/t2run/out/base_trades.json` vs `curl -s --max-time 20 -I https://ss.fx8.store/data/signal_kelly_trades.json | grep -i etag`
- 真样本探针: `cd <worktree> && python3 /tmp/reviewer_probe/probe_real_sample.py`(自带 subprocess 打桩)
- ⑦ 补跑: `TRADES_JSON=/tmp/t2run/out/base_trades.json FEAT_JSON=/tmp/reviewer_t2/kelly_loss_features_live.json node scripts/check_fade_predicate_parity.mjs --ref d45fcd4c57ba1cb7ef1473408d87600a1d20af70`

