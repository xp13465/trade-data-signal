# #222 实施报告：全量 trades 产物撤出「每轮必变」元数据

- 任务：#222（W 批数据可信度），用户 2026-10-11 拍板（§23.7）
- 分支：`feat/222-trades-meta-strip`（worktree `agent-a4bc195e24d6e6227`）
- 实施规范：`docs/ops/next-steps-w3-datacred-20261011.md`（§2 消费方清单 + §4.3 完整建议）
- 时间：2026-10-11 21:35–21:45

## 1. 一句话结论

在生成端撤掉 `signal_kelly_trades.json` / `_sdc.json` 顶层的 `generated_at` + `period_cutoffs`，
使内容本体不变时**整文件 md5 稳定**；上传侧（data-large md5 判据）与 `verify-r2`（HEAD ETag vs 本地整文件 md5）
两把尺子因此合流，本体不变即 0 传输。**生产代码改动 3 个文件 + 新增 1 个自测**，
告警 B2 逻辑一行未动（自动回退 mtime），前端 lab.js / app.js **零改动**（详见 §5 偏离说明）。

## 2. 改动文件清单（绝对路径）

| 文件 | 改动 |
|---|---|
| `/Users/linhuichen/code/trade/scripts/signal_kelly_backtest.py` | `_build_outputs` 的 `trades_output` 撤 `generated_at`+`period_cutoffs`（原 L1686-1692）；`_build_unique_tables` 同款撤两键（原 L1799-1802）；`_export_trades_parts` / `_dump` 注释同步 |
| `/Users/linhuichen/code/trade/scripts/kelly_posrating.py` | `compute_posrating` L922：`trades_doc.get("generated_at")` → `backtest_doc.get("generated_at")` |
| `/Users/linhuichen/code/trade/scripts/check_data_gap_alerts.py` | 文档头 L52 更正 + 删 L73 虚假输入依赖 + 删死常量 `KELLY_BACKTEST_FILE`（原 L172）。**B2 逻辑代码（L1318-1345）零改动** |
| `/Users/linhuichen/code/trade/scripts/tests/test_222_trades_meta_strip.py` | 新增，6 例自测（c0 撤键 + c1 md5 稳定 + c2/c3 负控 + c4 unique 同款 + c5 登记点守护） |

未改：`static-site/lab.js`、`static-site/app.js`、`static-site/export.py`、`scripts/upload_r2.py`、`worker/*`。
未 bump 版本串（主控 merge 时统一处理，机制 C）。

## 3. 四件事逐条交代

### ① 生成端剥离
`trades_output` 撤两键后仅剩 `{buy_amount, fields, quadrants}`——全为数据本体 + 常量，
不随轮次变。sdc 档（`signal_kelly_trades_sdc.json`）走**同一个** `main()` / 同一个 `trades_output`，
故一次改动同时覆盖主档 + sdc 档（§5 偏离 D 有说明报告原文的表述误差）。
`_build_unique_tables`（KELLY_UNIQUE_EXPORT，生产默认关）同族字段一并撤，防口径分叉。

### ② 展示源改读（只有 1 处真需改）
- `kelly_posrating.py:922`：改读同批产出的 `signal_kelly_backtest.json`（`backtest_doc` 是
  `compute_posrating` 的入参，同一轮回测，语义不变=快照数据时间）。这是唯一真需改的消费点。
- 首页显示 `latest_posrating.json.date` 由 `datetime.now().strftime("%Y%m%d")` **自生成**，
  与 trades 的 `generated_at` 无关 → 撤键不影响首页标签。

### ③ 未采用「冻结值 / 日粒度值」
明确按规范**不做**：冻结值法会触发 B2 的 48h 误报。B2 代码（`ts_cands = [mtime]` → 有则 append
generated_at → `min()`）一层未动；撤键后 `generated` 为空串 → 自动回退 mtime。

### ④ §21 公示同步评估
**无需改**。展示口径未变（同是「生成时刻」），只换了同轮次的取值文件；`purpose-notes.js` 中
`generated_at` 出现 0 次，无指向 trades 元数据的公示文案。

## 4. 自验证据

### 4.1 测试结果（全绿）
```
scripts/tests/test_222_trades_meta_strip.py                      6 passed
(219 + kelly_stats + 212 + loss_rules_20keys + 222 合并跑)  119 passed, 1 skipped
py_compile(4 个改动/相关 .py)                                  COMPILE_OK
```

### 4.2 md5 稳定性实证（真实数据，非合成）
真实产物 `/Users/linhuichen/code/trade/static-site/data/signal_kelly_trades.json`（86,254,426 B）：
- 撤键前顶层键实测 = `['generated_at','buy_amount','period_cutoffs','fields','quadrants']`
  （`generated_at=2026-09-22 11:20`，`period_cutoffs` 含 y1/y3/y5…）← 病灶实证
- 用该真实本体，模拟两轮不同生成时刻：

| | roundA | roundB |
|---|---|---|
| 旧格式（带两键） | `252e02f3848f961f0a325b9a215fd7fa` | `77289218251416ae577b15cbc4601e7b` ✗ 变 |
| 新格式（撤键后） | `3b794bfe46801f614e36abf7c42a0747` | `3b794bfe46801f614e36abf7c42a0747` ✓ 稳 |

脚本：`/tmp/agent-progress-w3b-222-md5.py`（仅读真实产物，未写入 data/）。

### 4.3 消费方反查（全仓库穷举）
- **trades `generated_at` 的消费方**：`check_data_gap_alerts` B2（回退 mtime，安全）、
  `overfit_monitor.py:416`（写入 `trades_generated_at`，其下游 0 消费者 → 变 "" 无影响）、
  `kelly_posrating.py`（已改源）。前端 0 处读 trades 的 `generated_at`。
- **trades `period_cutoffs` 的消费方**：0 处。`lab.js:8971 / 12959` 读的是
  `state.labSigKellyData.config.period_cutoffs` = `signal_kelly_backtest.json`（非 trades 档）；
  `upload_r2._kelly_parts_md5` 的 `pop` 是 parts 的防御性剔除；`sync_dev_from_r2.sh META_KEYS` 是忽略集。均不受影响。
- **无任何断言/机检依赖 trades 的这两个键**（已 grep 全 `scripts/*.py` 核实）。

## 5. 偏离任务书之处（如实上报）

- **A. lab.js 无需改动**。任务书写「② 修改 2 个显示来源：`kelly_posrating.py:920` 和
  `static-site/lab.js:9341`」。实测 `lab.js:9341` 的 `data` = `state.labSigKellyData`，
  在 `lab.js:9682` 被赋值为 `./data/${_labKellySummaryName()}.json`（= `signal_kelly_backtest[_sdc].json`，
  **保留** `generated_at`）→ 无需改。`lab.js:8697 _labKellyParseTrades` 解析 trades 时本就丢弃 `generated_at`。
- **B. 报告 §2 第 2 行（首页显示）不准**。报告称首页用 trades 的 `generated_at`；实测首页
  `latest_posrating.json.date` 是 `posrating` 自生成的 YYYYMMDD（`kelly_posrating.py:919`），
  与 trades `generated_at` 无关。报告引的「线上实测显示 2026-10-11 16:47」实为 **LAB 弹窗** 的展示格式，
  被错归给首页。
- **C. 报告 §2 第 3 行（lab.js:9341 用 trades 档）不准**，见 A。
- **D. 报告「sdc 变体 L1799-1802」表述有误**。该位置是 `_build_unique_tables`（KELLY_UNIQUE_EXPORT，
  生产默认关），**不是** sdc trades 档。sdc trades 与主档共用 `main()` 的 `trades_output`，
  故 L1686-1692 一次剥离主档 + sdc 全覆盖。此外 `_build_unique_tables` 我也一并撤了两键
  （它确实是同族「每轮必变」产物）。
- **E. 附带项处理**：`check_data_gap_alerts.py` 的 `KELLY_BACKTEST_FILE` 确认零引用（死代码）→ 已删；
  文档 L73 虚假输入依赖已删；文档头 L52 已更正。

## 6. 未做 / 留给主控

- 未 push、未 merge、未 deploy（按任务约束；merge 由主控明早经 `scripts/main-merge.sh` 执行）。
- 未 bump 版本串（机制 C，主控 merge 时统一）。
- 未改 `docs/pending-features-index.md` 状态列（#222 状态由主控统一记账，避免并发冲突）。
- 复现命令：`/Users/linhuichen/code/trade/.venv/bin/python -m pytest scripts/tests/test_222_trades_meta_strip.py -q`
- 恢复：本报告 + 4 个改动文件均在 `feat/222-trades-meta-strip` 分支，`git revert <commit>` 可逆。