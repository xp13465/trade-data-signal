# nextday 主源降级已恢复仍报 SEVERE：根因和修复

本轮修复 **1 个日志判定缺陷**。用户 2026-11-09 特批 Codex 修改业务解析器，限定 worktree `.claude/worktrees/codex-alert-nextday-20261109` / 分支 `codex/alert-nextday-20261109`；base 为 `8118feef3bbfdfdcde70e169e950749d3e5a408a`。只本地提交，由 Claude 审核、合并和部署。

## 修前三验

三验先于解析器修改完成，原子报告：`/tmp/codex-reports/alert-rootfix-20261109/nextday-root-cause.json`。

1. **实际问题**：原证据 `/tmp/codex-reports/alert-mail-audit-20261109/nextday-fallback-parser-reproduction.json` 的 Nov2 完整原始窗口，现逐字固化为 [nov2_complete.log](../../../scripts/tests/fixtures/nextday_fallback/nov2_complete.log)。主源 `ConnectionError` 后，513260 取得 `open=0.904`，全部 1 笔无伪跳空，结束退出码 0。旧 `scan_log_anomaly` 实际返回 `ConnectionError:`，而不是“已恢复”。
2. **真正根因**：`ANOMALY_RE` 会抓到 `ConnectionError:`；`TRANSIENT_WARN_LINE_RE` 却要求 `⚠` 及 `attempt N` / `第 N 次`。实际主源日志为 `[就绪闸] 主源 fund_etf_spot_em 失败(...), 全量走双源兜底`，不符合旧重试契约，进不了 `_retry_self_healed`。这不是兜底取价失败，也不是告警阈值问题。
3. **可修依据**：生产者已输出目标清单、逐目标真实价及收尾。解析器可在现有窗口内证明每个目标恢复，只跳过被证明恢复的主源降级行，不需要新增生产者日志或补价。

## 已核实的生产者与消费者

- `signal_kelly_backtest.py::_fetch_intraday_open_prices` 捕获主源异常，向 stderr 打上述确切降级行，立即调用 `_fetch_intraday_open_via_http(target, expect_date=...)`，返回真实价及来源元数据。新测试直接提取并执行此生产函数：主源抛 `ConnectionError`，HTTP 边界返回固定真价，核对实际输出字符串；不访问远端接口。
- `nextday_gap_check.py::main` 输出 `sorted(target)` 和唯一代码数；逐目标输出 `✓ <code> 正常 open=... sig_close=... gap=...%`，或已取到价的 `✗ <code> 伪跳空剔除 ...`。缺价则输出 `~ <code> 开盘价未取得`，**部分缺价仍可能 exit0**，所以 exit0 本身不能证明成功。
- 没有剔除/缺价时，输出同执行日的 `全部 N 笔无伪跳空, 无标记`；有剔除时，需要持久化收尾 `落盘完成: ...`，同步失败则返回非零。`--test-open` 和 `DRY-RUN` 都有明确标识。
- `nextday_gap_check.sh` 输出标准 start/end，结束行带实际 `退出码=$RC`。`log()` 及主源 stderr 输出都显式 flush，顺序证据可用。
- `gen_schedule_stats.py::_build_log_task_row` 把扫描结果转换为 `log_anomaly`、keyword、line、severity；`schedule_monitor.sh` 的 `if s.get("log_anomaly")` 消费这些字段。exit0 不会替此类真实异常兜底。因此应在语义解析处修复，监控阈值和策略无需改。

## 修复机制

`gen_schedule_stats.py::_nextday_fallback_healed_lines` 复用 `scan_log_anomaly` 已选出的最后一次 standard 运行窗口，仅接受 `nextday_gap_check.sh`。

必须同时满足：

- 权威 `last_exit == 0`，且当前窗口有带明确 `退出码=0` 的本任务结束行；不能用其它轮次或 unit 的旧成功码替代缺失收尾。
- 恰好一条计划清单，代码为 6 位字符串、无重复、非空，数量与声明一致；计划行早于降级行。
- 降级行完整匹配生产者的“主源失败→全量走双源兜底”字符串。
- **最后一次**主源降级之后，每个计划目标恰有一条有限正值 `open` / `sig_close` 的实际判价记录，目标集合完整一致；不以一条任意 `✓` 或 `重试成功` 代替覆盖。
- 逐价之后有同执行日、同数量的正常汇总；若存在有真价的伪跳空剔除，则要求全部目标判价及持久化收尾。
- 没有嵌套运行窗口、注入价、干跑、缺价或就绪闸失败等矛盾证据。

只返回通过证明的主源降级行索引。扫描器仅跳过这些行，继续检查其它 `ConnectionError` / `Traceback` / `FATAL` / R2 失败。原始日志不删除、不改写，并打印 `[nextday-fallback-self-heal]` 解释恢复依据，主源降级仍可查。

旧上传重试、push、finalizer、自愈缓冲逻辑不变。未增加全局异常忽略名单，也未把该主源行塞进会仅凭 exit0 放行的旧瞬态正则。

## 红绿证据与回归

先固化真实 fixture 并在旧代码上运行：

```text
1 failed, 55 deselected in 0.05s
```

失败断言是实际得到 `ConnectionError:`，而期望已恢复。原始日志：`/tmp/codex-reports/alert-rootfix-20261109/nextday-red.log`。

新专项 67 个用例覆盖：真实单目标、多目标、有真实价的剔除收尾、生产函数确切输出、真实 build 输出字段及 gzip。负例包括全源失败、部分缺价仍 exit0、伪汇总、零/负/NaN/Inf/溢出价、坏清单、数量/目标/日期不符、重复目标、缺收尾、未知/非零退出、跨轮/嵌套轮次/行序错位、注入价、任意成功行及无关真实异常。另钉住上传同 key 自愈、异 key 不自愈、进行中 degrade 和旧 exit0 规则。

最终回归命令（本地 venv Python，所有输出及文件写入测试临时目录）：

```bash
python -m pytest -q \
  scripts/tests/test_nextday_fallback_log_anomaly_20261109.py \
  scripts/tests/test_240_alert_denoise_batch2_20261009.py \
  scripts/tests/test_232_marker_buffer_20261007.py \
  scripts/tests/test_log_gz_compat_20261010.py \
  scripts/tests/test_309_gen_stats_exit_source.py \
  scripts/tests/test_309_monitor_branches_20261025.py \
  scripts/tests/test_282_alert_denoise3_20261022.py
```

原始完整测试末行：

```text
186 passed in 4.58s
```

完整输出：`/tmp/codex-reports/alert-rootfix-20261109/nextday-regression-final.log`。新测试用网络/子进程闸门禁止外发；build 的无关 unit 查询注入 None，实际运行日志解析和 JSON 生成。未执行全仓测试，未运行生产任务、生产监控或远程部署。

## 范围和交接边界

本次只改解析器、相关新测试/原样 fixture、本说明。未改生产者、策略阈值、页面、业务计划或价格，也不处置其它告警待办。已检查 pending-features-index 中告警降噪及 nextday 旧项（#123/#240/#245/#247/#321 等），本次不重开已完成项、不覆盖其它工作分支。单点复用现有窗口和扫描出口，使用 Python 标准库，未加依赖或通用框架。

日志格式未来漂移时默认保留告警；不确定或缺证据不会推断成功。未 push、未合 main、未部署；部署后的真实告警恢复由 Claude 审合后验证。没有发送飞书或邮件。

Fixture SHA-256：`78b068b77caf5e19aa1678e8a126b9f490e4ece1c1613a6bdbb9e09747d18492`。
