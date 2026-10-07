# #184 实施报告:`--dry-run` 真正零落盘(write_alert 门控)

- 分支:`feat/184-notify-dryrun-gate-20261007`
- 日期:2026-10-07
- 范围:只修 `notify.write_alert` 的 dry_run 未贯穿(§23.7 冻结面已确认 / 用户已拍板);同类其他路径只列不扩改(见 §4)。

## 1. 病灶与根因

`notify.write_alert()`(写 `data/alerts/latest.md`)不收 `dry_run` 参数 → CLI
`--alert-issue` 配 `--dry-run` 仍会覆盖写真实 `latest.md`,与 notify.py 自带契约
「`--dry-run` 不真发」(模块 docstring L35)及 `send(severe=True)` 的
`_mirror_severe`(`if severe and not dry_run`)相悖。

**根因修复(§6.5)= 门控收在唯一写入函数内**(单点守卫,非逐调用点打补丁):
`write_alert(issue, detail, log_path=None, dry_run=False)` 最前短路——
`if dry_run: print("[notify][dry-run] write_alert 跳过写 ..."); return`。
5 个 CLI 调用点全部透传 `dry_run=args.dry_run`;未来新增调用点由「函数内守卫 + 机检」
双重兜底(test_184 第 6 条静态机检)。

## 2. §23.2 修完整:`write_alert` 全部调用点逐点判定(共 5 处,均改)

| # | 行(改后) | 场景 | 该不该 gate | 动作 |
|---|---|---|---|---|
| 1 | 2194 | `--tier critical` + `--alert-issue` | 该 —— 原仅 gate `tier==critical`,未 gate dry_run | 透传 `dry_run=args.dry_run` |
| 2 | 2252 | R4 `staticdata_backup_fail` 分级块 `--alert-issue` | 该 —— 块级只有 dedup 的 `not dry_run`,无 alert 门控 | 透传 |
| 3 | 2288 | R7 `r2_consistency` 升级档 `--alert-issue` | 该 —— 同上 | 透传 |
| 4 | 2339 | #196 巡检/链路升级档 `--alert-issue` | 该 —— 同上 | 透传 |
| 5 | 2366 | 通用路径 `--alert-issue` | 该 —— 唯一无任何 dry_run 门控的入口 | 透传 |

grep 全量确认:`grep -n "write_alert(" scripts/notify.py` 仅此 5 个调用点(另 1 处为 def)。
`write_alert` 在 notify.py 之外无调用方(全仓 grep 确认)。

## 3. §23.3 举一反三:同类「dry_run 未贯穿」写入路径逐项判定

| 写入路径 | 目标文件 | dry_run 现状 | 判定 | 动作 |
|---|---|---|---|---|
| `write_alert` | `latest.md`(覆盖式详单区) | **未贯穿(病灶)** | 该 gate | **本次修复** |
| `_mirror_severe`(send severe) | `latest.md`(流水区) | 已 gate(`if severe and not dry_run`,L998) | 无需改 | 保持 |
| `defer_warning` | `warning_buffer.jsonl` + `warning_dedup_state.json` | 已 gate(函数最前短路,L1726) | 无需改 | 保持 |
| `_flush_warning_batch_locked` 收尾 | buffer 重写 + warning_dedup 快照 | 已 gate(`if sent and not dry_run`,L1972) | 无需改 | 保持 |
| `check_dedup`/`update_dedup` | `notify_dedup.json` | 调用点已 gate(`not args.dry_run`);send() 内 release_dedup 亦 gate(L983) | 无需改 | 保持 |
| `_alert_feishu_config_missing` | dedup 占窗 | 已 gate(L722/L746) | 无需改 | 保持 |
| `notify_agent_done` dedup | `notify_dedup.json` | 已 gate(L1333/L1356) | 无需改 | 保持 |
| `log_info`(经 `send_tiered(tier=info)`) | `info_log.jsonl` | **未 gate(真写入!)→ 见 §4** | 该 gate,但**超出本次点名范围** | **只报告,未改** |

## 4. ⚠️ 发现报告外的真写入路径(如实列出,按派单「范围守住不擅自扩改」未改,报主控)

**`notify.py --tier info --dry-run` 仍会写 `data/alerts/info_log.jsonl`。**

- 证据:`send_tiered()` L2084-2086 `if tier == TIER_INFO: log_info(subject, body)` ——
  未透传 dry_run;`log_info()`(L1415-1434)无条件 `_append_jsonl(INFO_LOG_FILE, rec)`
  (+>2000 行时截断重写)。
- 触发面:`--tier info` 是生产在用档位(staticdata_sync.sh L248 / schedule_monitor.sh L2520 /
  self_heal.sh L176 / staticdata_backup_async.sh L397),但它们**不传 --dry-run**;
  仅「手动 `--tier info --dry-run` 自验」组合会命中 → 影响面低但契约仍破。
- 建议修法(供主控拍板,一行级):`log_info(subject, detail, dry_run=False)`,最前
  `if dry_run: print(...); return True`;`send_tiered` info 分支透传 `dry_run=dry_run`。
  是否本轮一并修请主控定(涉及另一个已上线档位的行为,§23.7)。

## 5. §18 L48 自测(打桩 + 零外发证据)

新增 `scripts/tests/test_184_notify_dryrun_gate_20261007.py`(6 条,全 tmp 隔离):

**零外发哨兵**(autouse fixture):patch `notify.smtplib.SMTP_SSL` / `notify.urllib.request.urlopen`
为「触达即 RuntimeError」;ALERTS_DIR/INFO_LOG_FILE/DEDUP_FILE 等全部落 tmp。

| 用例 | 断言 | 结果 |
|---|---|---|
| `test_write_alert_dry_run_does_not_write` | dry_run=True 不创建 latest.md | PASS |
| `test_write_alert_default_and_false_write` | 缺省/False 正常落盘(写路径未误伤) | PASS |
| `test_cli_dry_run_alert_issue_no_latest_no_outbound` | CLI `--alert-issue --dry-run` 不写 + 零外发 | PASS |
| `test_cli_real_alert_issue_writes_latest_send_stubbed` | 实跑写 latest.md(send 打桩,零外发) | PASS |
| `test_cli_tier_critical_dry_run_no_latest` | tier=critical 的 dry-run 不写 | PASS |
| `test_all_write_alert_callers_pass_dry_run` | 机检 5 调用点全透传 dry_run=(防未来漏挂) | PASS |

**负控(改前复现「被写」/ 改后不写)**:
- 改前(未修 notify.py):`pytest scripts/tests/test_alertchain_hardening_20261003.py::test_brief_push_failure_produces_alert`
  → **PASS**(该用例当时断言 `latest.exists()`,即 wrapper `--dry-run` 失败分支**确实写了 latest.md**,
  复现病灶)。
- 改后:该用例更新为断言 `not latest.exists()` + dry-run 打印含 `write_alert 跳过写` → PASS;
  新增 6 条全 PASS。
- 改前 `write_alert` 签名(实测)=`(issue, detail, log_path=None)`(无 dry_run);改后含 `dry_run=False`。

**②「latest.md 自测前后逐位一致」证据**:生产 `/Users/linhuichen/code/trade/data/alerts/latest.md`
自测前后 md5 恒为 `e8e4db889167bdd04aad8aaaa61cf9c8`(32353 B, mtime 1791279611 未变)。
(本 worktree 无 `data/alerts/`,自测全走 tmp;测试内 subprocess 亦用 REPO=tmp。)

**①「本次自测未产生任何真实外发」证据**:
1. 哨兵:任一真实邮件/飞书/TG 触达即 RuntimeError → 全用例 PASS 即未触达;
2. 实跑写路径用例以 `notify.send` 桩覆盖,且 SMTP/urlopen 哨兵在位;
3. worktree `config/` 只有 `*.example`,无真实 `email.json/feishu.json` → 即便非 dry 也无凭据可认证;
4. 唯一 subprocess 用例(alertchain wrapper)显式传 `--dry-run`。
5. 全程未执行任何 `notify.py` 的非 dry-run 生产路径。

## 6. 全量回归(CI ⑧ 同口径)

`python3 -m pytest -q scripts/tests/` → **301 passed, 1 skipped**(改后;改前同口径基线 301 passed 中包含旧 alertchain 用例)。
`py_compile scripts/notify.py` / `bash -n` 两个改动 shell 脚本 均 OK。

## 7. 关联文档同步(§22 一致性 / §21 精神)

- `scripts/notify.py`:模块 docstring(`--dry-run` 条目)、`--dry-run` argparse help、`--severe`/`--alert-issue` 说明、
  `write_alert` docstring —— 均补「dry-run 也不写 latest.md」。
- `scripts/brief_push_wrapper.sh` L25-27、`scripts/uptime_check.sh` L32:原先**把病灶当已文档化行为**
  («dry-run 也会写真实 latest.md» 注释)→ 改为反映新契约。
- `scripts/r2_upload_skip_notify.sh` L15 注释本已写「不写 latest.md」——改前与实现相悖(erroneous),
  本次修复后自动对齐,无需改。

## 8. 复现命令

```bash
# 全量
/Users/linhuichen/code/trade/.venv/bin/python -m pytest -q scripts/tests/
# 本次新增 + 受影响
/Users/linhuichen/code/trade/.venv/bin/python -m pytest -q \
  scripts/tests/test_184_notify_dryrun_gate_20261007.py \
  scripts/tests/test_alertchain_hardening_20261003.py
```