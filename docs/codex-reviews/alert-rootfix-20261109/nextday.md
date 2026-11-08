# nextday 日志恢复判定：根因修复与轮次边界续修

本分支初次修复主源降级已恢复仍报异常的问题，提交 `dbbae2b28e4492b5a3fac218d9f84ab6028d9d14`。独立复审发现 **两个 P2 边界缺陷**：异常正文伪造价格和结束行、正常无剔除干跑缺模式标记。本次获用户追加授权，在同一 `codex/alert-nextday-20261109` 分支续修，保留原提交，增加后续提交。base 仍为 `8118feef3bbfdfdcde70e169e950749d3e5a408a`，由 Claude 负责复审、合并、部署。

R1 独立复验确认前两 P2 通过，新增 1 个状态机 P2：内层 END 清空布尔 pending，后续 START 挤掉未闭合外层 FATAL。本次在 `a7fdef6ed0bac811787eceb65c8e746915fd0ee0` 后继续追加提交，不覆写历史。

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

## R1 轮次状态遗漏与 R2 修复

真实 `scan_log_anomaly` 和 `_build_log_task_row` 在原样 R1 输入中都漏掉外层 FATAL：A.start → FATAL → B.start → B.end → C.start → C 真正 live 完整结果 → C.end，A 没结束。原布尔状态被 B.end 清空，C 把 A 挤出窗口。修前原始末行：

```text
3 failed, 26 deselected in 0.09s
```

源头没有可靠的每行进程身份，单靠日志不能认证嵌套 END 归属，更不能凭后来 live 标记推断先前进程已退出。无需修改 wrapper：现有 `unit_truth.derive_unit_state` 已提供 systemd start/exit/InvocationID。

最小改动仅在 `gen_schedule_stats.py`：

- 无 native 时用配对深度保留未闭合外层，并扫描原始尾部，内层 END 后的真错也不会被截掉。一旦出现同名嵌套即保留歧义状态，后续多条 END 不能靠数量清空歧义。
- 普通前轮完整结束、未发生嵌套，仍可自然选中新轮；曾嵌套或崩溃未结束时，只有真实 native 新轮次能隔离旧异常。
- `_build_log_task_row` **仅 nextday、systemd 模式**向 scanner 传可选 `nextday_native`，复用当前已取得的 `trusted_state`，拒未来 exit，无额外 systemctl 调用。其它任务保持原调用及原解析规则。
- 只有正确 service、loaded、当前 systemd source、非空 InvocationID、正常退出(code0 / exec_code1 / exec_status0 / inactive)、有效 start<exit 的 native 才可提供边界；ledger / stale / unknown 不行。区间内必须唯一且为日志最新的 wrapper start，并有区间内真实 END；同秒多候选、同一 native 内多个 START、缺 END 都保持保守。
- native 只决定从哪里扫描，不替代 live 模式、全部目标真实价和收尾验证；新轮内部真 FATAL、错价、缺价、干跑、注入和无收尾仍告警。

45 个新增专项覆盖同日/次日/多日重启、连续多次崩溃后 native 恢复、真实 row/build 接线、同秒与元数据缺失/过期/未来/非正常终态、重复 END、内层 END 后真错，以及其它任务不变。无 native 的 R1 原反例必须保留 FATAL；不会为了证明重启而手改坏日志。R1 原始输入无损固化为测试 JSON，解码字节相同。

当前仅复用真实模式与已有 systemd 字段，没有新增 wrapper 身份或通用日志框架；本次未改 `nextday_gap_check.py`、`unit_truth.py` 或 freeze 独占源。固定 owner 组合改为读取 `r1-snapshots/primary-combined-fixed.py`，已与 `git show fa20231...` 字节核对，不读后续 worktree 漂移内容。

## 定向验证结果

本分支最终回归命令：

```bash
python -B -m pytest -q \
  scripts/tests/test_nextday_fallback_log_anomaly_20261109.py \
  scripts/tests/test_nextday_fallback_mode_boundaries_20261109.py \
  scripts/tests/test_nextday_native_round_boundary_20261109.py \
  scripts/tests/test_240_alert_denoise_batch2_20261009.py \
  scripts/tests/test_232_marker_buffer_20261007.py \
  scripts/tests/test_log_gz_compat_20261010.py \
  scripts/tests/test_309_gen_stats_exit_source.py \
  scripts/tests/test_309_monitor_branches_20261025.py \
  scripts/tests/test_282_alert_denoise3_20261022.py
```

原始完整末行：

```text
270 passed in 5.26s
```

owner 固定快照组合三专项：设置 `NEXTDAY_FALLBACK_PRODUCER_SOURCE` 指向固定 owner 快照，再执行上述前三个测试文件；原始完整末行：

```text
151 passed in 1.57s
```

原独立 R1 的 90 例使用 `nextday-r2-followup-verifier.py` 重放，只切换被测 parser 为本次代码，生产者仍为原固定快照，90 个断言不变，输出另存以保留历史：

```text
R2_FOLLOWUP_RESULT checks=90 passed=90 failed=0 cases=
```

这不是新一轮独立复审结论。完整证据均在 `/tmp/codex-reports/alert-rootfix-20261109/`：`nextday-r2-regression-final.log`、`nextday-r2-combined-final.log`、`nextday-r2-followup-verifier.log`、`nextday-root-cause.json`。

只跑定向测试，未单独跑全仓。测试禁止真实网络/子进程外发，所有替身文件在临时目录；未运行生产任务、DB、通知、监控或部署。代码变动限定解析器及 main 模式日志，另有相关测试、原样复审 fixture 和本文；未改阈值、页面、业务计划或补价。未 push、未写 main、未部署，由父/Claude 复审合并后验证线上恢复。
