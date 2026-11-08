# nextday 日志恢复判定：根因修复与两项 P2 续修

本分支初次修复主源降级已恢复仍报异常的问题，提交 `dbbae2b28e4492b5a3fac218d9f84ab6028d9d14`。独立复审发现 **两个 P2 边界缺陷**：异常正文伪造价格和结束行、正常无剔除干跑缺模式标记。本次获用户追加授权，在同一 `codex/alert-nextday-20261109` 分支续修，保留原提交，增加后续提交。base 仍为 `8118feef3bbfdfdcde70e169e950749d3e5a408a`，由 Claude 负责复审、合并、部署。

## 修前三验与实测根因

原三验保留在 `/tmp/codex-reports/alert-rootfix-20261109/nextday-root-cause-initial.json`；续修前已更新原子报告 `nextday-root-cause.json`，先复现、再改源。

- **原始问题**：Nov2 真实窗口主源 `ConnectionError`，兜底 513260 取得 `open=0.904`，全部 1 笔正常，exit0；base 的 `ANOMALY_RE` 抓到错误，但日志没有旧瞬态规则要求的 `⚠ attempt N / 第 N 次`，无法进入旧自愈分支。
- **P2-1 实际问题**：独立复审原样输入 `producer-injected-fakeprice.log`，真实 HTTP 兜底仅有 513260、510300 真实缺价，仍 exit0；异常正文包含两只假价、汇总和假 END。旧 helper 只看到第一个 END 之前，返回 `(None, 0)`。加上新 live 前缀或删除真正 END，旧代码仍错误豁免。
- **P2-2 实际问题**：真实 `main --dry-run` 在全部目标正常时提前 return0，到不了旧 `DRY-RUN` 输出；与正常运行日志无法区分。独立复审原样 `producer-dryrun-normal.log` 被旧代码豁免，真实函数测试也复现该问题。
- **可达修复依据**：在 main 解析参数后、任何读写或提前返回前，记录确定执行模式；豁免前校验未经首个 END 截断的原始运行尾部，并把 nextday 边界限定为独立完整记录。现有逐代码真实价、目标集合、收尾和退出码仍全部核对，无需改价格或策略。

注入原日志的 `落盘完成: ` 行含真实末尾空格；入库测试用 JSON 无损保存全文，解码后与复审 `.log` 字节一致，避免更改证据或引入仓库尾空格。原始 `/tmp` 日志不改动。

两 P2 的红测试原始末行：

```text
4 failed, 29 deselected in 0.10s
```

日志：`/tmp/codex-reports/alert-rootfix-20261109/nextday-p2-red.log`。多行输入是可复现的构造边界，未声称生产曾发生过攻击。

## 最终生产模式契约

`nextday_gap_check.py::main` 在 `args` / 执行日确定后第一时间输出一条模式记录，涵盖正常无剔除、空计划、无计划、独立 recheck 等全部提前返回。

| 参数语义 | 模式 | 可作为生产恢复证明 |
| --- | --- | --- |
| 真实价日常校验，未关闭发布/通知 | `live` | 还须满足全部目标与收尾条件 |
| `--dry-run` | `dry-run` | 否 |
| `--test-open` | `test-open` | 否 |
| `--no-r2` 或 `--no-notify` | `local-only` | 否 |
| `--recheck-pending` | `recheck` | 否 |

生产模式记录为 `[nextday_gap_check] 执行模式=live 执行日=YYYYMMDD`。解析器要求恰好一条，日期与计划一致，且位于计划清单之前。不能靠黑名单词缺席推断生产，也不能借异常正文中的 `⚠ attempt` 词绕进旧上传重试规则。

**历史 Nov2 没有模式记录，当前判为 unknown，不豁免，保留原告警。** [nov2_complete.log](../../../scripts/tests/fixtures/nextday_fallback/nov2_complete.log) 字节未改，SHA-256 仍是 `78b068b77caf5e19aa1678e8a126b9f490e4ece1c1613a6bdbb9e09747d18492`。原成功事实仍保留，但不把它当未来生产模式的证明。测试中的 `LIVE_WINDOW` 明确是新契约合成边界；未来正常恢复另外用真实 main 默认参数产生日志验证。

## 原始窗口与全目标证明

- nextday 的扫描和 `parse_standard_detail` 都只认独立完整 start/end，单行异常正文里的同名字样不算 wrapper。其它任务边界规则不变。
- nextday 未闭合轮次里的嵌套 start 不会把外层已有的真实 `ConnectionError` 挤出扫描窗。
- `_nextday_fallback_healed_lines` 检查原始 start 到文件末尾，而非首个 END 截断后的片段。重复/嵌套边界、假 END 后真实缺价或真正 END、缺真实收尾、额外尾部记录均不能获得豁免。
- 必须权威 `last_exit=0` 且真实窗口尾部有显式 END exit0；唯一有效非空目标清单、数量/代码集合匹配；最后一次主源降级之后，每个目标恰有一次有限正值 open/sig_close。
- 正常结果要求同执行日、同数量的完整汇总；有真实价的伪跳空剔除要求全部目标判价及持久化收尾。部分缺价即使 exit0 也保留告警。
- 只跳过被证明恢复的确切主源降级行，继续扫描其它 ConnectionError、Traceback、FATAL、R2 失败。原始原因保留，并打印 `[nextday-fallback-self-heal]` 说明恢复依据。旧上传、push、finalizer、自愈缓冲阈值不改。

消费链仍为 `_build_log_task_row → log_anomaly/keyword/line/severity → schedule_monitor.sh log_anomaly 分支`。真实 row 测试验证干跑及原始注入两侧均 `log_anomaly=true`，正常新契约 live 才可恢复；未执行生产监控主体。

## freeze owner 组合验证

本分支**未改** `signal_kelly_backtest.py`。父安排 freeze owner 将异常正文改为 `{str(e)!a}`，覆盖 CR、LF、CRLF、VT、FF、FS、GS、RS、NEL、Unicode LS/PS 的单条日志转义。

已只读提取 owner 提交 `fa20231c7e8462c910bf406c9bad8fe485fdea60` 的真实 `_fetch_intraday_open_prices`，与本分支真实 `main` / `_fetch_opens` / parser 组合执行；仅网络、读写、通知边界用离线替身。源文件 SHA-256 为 `dba7c6fd9cf3474587d7f0640cbd412ce5df0dfbcf9d1270c8082628feae4984`，已核对文件与该提交相同。

原始未转义假 END fixture（含补 live 前缀）仍独立测试，保持告警；组合源测试同时验证 11 种分隔符只生成一条异常记录、真实缺价不能恢复、真正 live 全目标完成可以恢复。没有合并或复制 owner 文件，后续两分支实际合并由父统一回归。

## 定向验证结果

本分支最终回归命令：

```bash
python -B -m pytest -q \
  scripts/tests/test_nextday_fallback_log_anomaly_20261109.py \
  scripts/tests/test_nextday_fallback_mode_boundaries_20261109.py \
  scripts/tests/test_240_alert_denoise_batch2_20261009.py \
  scripts/tests/test_232_marker_buffer_20261007.py \
  scripts/tests/test_log_gz_compat_20261010.py \
  scripts/tests/test_309_gen_stats_exit_source.py \
  scripts/tests/test_309_monitor_branches_20261025.py \
  scripts/tests/test_282_alert_denoise3_20261022.py
```

原始完整末行：

```text
225 passed in 4.95s
```

owner 组合两专项：设置 `NEXTDAY_FALLBACK_PRODUCER_SOURCE` 指向其真实源文件，再执行上述前两个测试文件；原始完整末行：

```text
106 passed in 0.92s
```

另外保留独立复审原 verifier 和证据不动，另存 `nextday-followup-verifier.py`：只适配新的显式生产参数/模式断言、历史 unknown 口径、组合源路径及隔离输出目录，实际重放结果：

```text
INDEPENDENT_RESULT checks=39 passed=39 failed=0 cases=
```

这不是新一轮独立复审结论。完整证据均在 `/tmp/codex-reports/alert-rootfix-20261109/`：`nextday-p2-regression-final.log`、`nextday-p2-combined-final.log`、`nextday-followup-verifier.log`、`nextday-combination-source.json`。

只跑定向测试，未单独跑全仓。测试禁止真实网络/子进程外发，所有替身文件在临时目录；未运行生产任务、DB、通知、监控或部署。代码变动限定解析器及 main 模式日志，另有相关测试、原样复审 fixture 和本文；未改阈值、页面、业务计划或补价。未 push、未写 main、未部署，由父/Claude 复审合并后验证线上恢复。
