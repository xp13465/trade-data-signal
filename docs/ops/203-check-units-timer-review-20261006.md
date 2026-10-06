# #203 独立审查报告 · `check_failed_units.py` ②b「脚本存在性」层 timer 空转修复

> 审查对象:分支 `feat/203-check-units-timer-20261006` @ `d0826bcce`(base `origin/main` `33d380090`;4 文件 +463/-44)。
> 审查者:(独立 reviewer,fresh context;只读,唯一写入 = 本报告 + /tmp 探针)。
> 结论:**PASS。merge 资格 = 是。P0 = 0 / P1 = 0 / P2 = 0**(另有 4 项低分报告偏差,见 §8,不阻塞)。
> 审查方式:全文重读 diff + 云上只读采样复核 + 用「云上真值字节」回放真实代码路径(新/旧代码 A/B)+ 注入样本反向对照 + 独立重跑 pytest + flaky 机理手工复现 + 全仓调用方 grep。

---

## 0. 审查约束遵守(§18 L50 / L48)

- **探针 static-only**:全程未 source/exec 任何仓内业务脚本主体。唯一执行的仓库脚本 = 被审对象 `check_failed_units.py` 本体(仅注入样本 + dry 模式,零 subprocess systemctl、零 notify)+ 仓库自带 CI 测试套件(见 §9 披露)。
- **云上只读**:仅 `systemctl show` / `test -f` 类查询,零写(未 restart/reset-failed/enable/disable/PUT/ DELETE;命令原文见 §2)。
- **零外发零生产写证据**:双树 `git status --porcelain` 空;`data/` 目录 60 分钟内零新文件;`pgrep -fl "cloud_unit_patrol|schedule_monitor|self_heal|check_r2_consistency|overfit_monitor|check_monitor_heartbeat|check_data_gap"` 空;本地写入仅 `/tmp/rev203/*` 与 `/tmp/cloud_show_203.txt`。

---

## 1. 根因修复语义正确性 + fail-open 裁定 — PASS

**代码事实**(`scripts/check_failed_units.py` 工作树版):
- `_resolve_exec_entries(unit, kind, show)`(L146-172):`kind != "timer"` 直读自身 ExecStart;timer 走 `Triggers` 拆分 → 逐个被触发 unit 取 ExecStart 聚合 → `Triggers` 空则回退同名前缀 `.service` → 再取不到 `[]`。
- `_run_unit_show` 的 `-p` 列表加 `Triggers`(L119-123);真实/注入两态共用同一解析路径(L253-277);`_as_list` 归一 str/list/None(L138-143)。

**fail-open 裁定(任务问题①:是否"空转挪位置"?)——判恰当,非挪位**,论证:
1. 旧空转是**结构性 100% 必然**(timer 无 ExecStart 属性,7/7 恒空,§2 云上实测证实);新实现空转只可能发生在**解析链故障**时,而解析链故障的两类形态都被相邻层 loud 覆盖:
   - `systemctl show` 整体失败/超时 → `_run_unit_show` 抛错被 `main()` 捕获 → rc=2 → `schedule_monitor.sh`(L1555 附近)把「巡检脚本自身异常」升 SEVERE;或返回空 dict → 状态字段 None → `judge_watchman_units` **fail-loud**(`alert_denoise_rules.py:170` 注释 + `:191-194`:ufs/active None ⇒ 报警)。
   - 仅 Triggers 与同名 service 双双读不到(状态字段却可读)→ 本轮静默,但 next 15min 轮重试自愈;且对 loaded+active 的 timer,Triggers 属性实测恒在(§2)。
2. 「脚本被删」这一层职责场景**不依赖解析成功**:脚本被删时 unit 文件与 ExecStart 串仍在,解析照常非空 ⇒ 检测不受 fail-open 影响(§3 反向对照实证)。
3. fail-open 是本仓该层既有设计(o文件头注释与 `extract_script_paths` 同口径:解析不到绝不报「脚本被删」),非本次新增语义。

**verifier**:
- command: 阅读 `check_failed_units.py:146-172` + `alert_denoise_rules.py:164-195`;`test_judge_watchman_units_none_fields_fail_loud`(test_196 L149-154)。
- expected: 「解析失败」→ 静默且相邻层 loud;「脚本缺失」→ 必报。
- observed: 与上述一致;§3 用例 b(缺脚本必报)、用例 e(解析失败静默)分别实证两端。

**低分备注(见 §11)**:`_resolve_exec_entries` 对同一 unit 二次调用 `show()`(行数据已取过),真实模式每轮 21 次 systemctl 调用 vs 旧 7 次。正常耗时 <1s(单次 10-30ms),对 15min 轮无关紧要;极端 systemd 挂死场景旧代码(7×30s)本已超 `schedule_monitor` 的 120s 子进程超时 ⇒ 非新故障类别。

## 2. 「真实生产样本」复核(修复前 0/7 → 修复后 7/7)— PASS

**云上只读采样**(2026-10-06,`ssh -i ~/tdsignal.pem ubuntu@122.51.111.173`,零写;原始输出落 `/tmp/cloud_show_203.txt`):
```
systemd_version: systemd 249 (249.11-0ubuntu3.20)
for t in trade-cloud-unit-patrol trade-check-monitor-heartbeat trade-schedule-monitor trade-self-heal \
         trade-r2-consistency trade-check-data-gap trade-overfit-monitor; do
  systemctl show "$t.timer" -p Id -p LoadState -p ActiveState -p UnitFileState -p Triggers -p ExecStart
  svc=$(systemctl show "$t.timer" -p Triggers --value); systemctl show "$svc" -p Id -p LoadState -p ActiveState -p UnitFileState -p ExecStart
done
for f in cloud_unit_patrol.sh check_monitor_heartbeat.py schedule_monitor.sh self_heal.sh \
         check_r2_consistency.sh check_data_gap_alerts.sh overfit_monitor.sh; do test -f "/home/ubuntu/code/trade-data/scripts/$f"; done
```
**观测值(逐条核)**:
- 7/7 timer:`LoadState=loaded ActiveState=active UnitFileState=enabled`(**无 ExecStart 行**,有 `Triggers=<同名>.service`)= 旧代码恒空的结构性证据。
- 7/7 service:ExecStart 真值逐条与报告 §4 表一致,含 heartbeat 经 `.venv/bin/python` 跑 `.../scripts/check_monitor_heartbeat.py`。
- 7/7 脚本 `test -f` = **OK(全在盘)** ⇒ 修复上线后该层稳态**零假阳性**(这是上线影响的头号风险点,实测解除)。
- **A/B 回放(真实代码路径)**:用上述原始字节造 static-only `systemctl` 回放桩(只 cat 预捕获文本,不 exec 任何脚本),同一份字节分别喂 **新代码** 与 **base(33d380090)代码**:
  - 新代码:rc=1,`CHECK_FAILED_UNITS_FAIL(7 项)`,7 条 「被执行的脚本已不在盘: /home/ubuntu/...」——7/7 全部解析出真实路径(mac 无这些路径 ⇒ 全判缺;证明解析**非空**)。
  - base:`rc=0`,**0 条**判定,stdout=`CHECK_FAILED_UNITS_OK failed=0 watchman=7 个 timer 全部在跑`——即使 7 个脚本"全缺"也一声不吭 = **0/7 空转复现**。
- **对照链闭环**:`md5 base_check_failed_units.py = 1af471190cc5bab46cb1861f4b83f786` == 上游 §0 验证报告(`docs/ops/193-196-live-verify-20261006.md` §2)记录的**云上该文件 md5** ⇒ 云上当前跑的正是被审 base 内容,「修复前生产空转」的样本链完整可信。

## 3. 反向对照与护栏真生效 — PASS(自建临时树探针)

受控树 `/tmp/rev203/cloud`(7 脚本按云上真值文件名铺;注入 JSON 由云上真字节 root 替换生成):

| 用例 | 输入 | 期望 | 实测 |
|---|---|---|---|
| a 存在侧 | 7 脚本全在盘 | rc=0 零假阳性 | **rc=0**,OK 行 |
| b 缺失侧 | 运行时删 `overfit_monitor.sh` | rc=1 且**只报该 1 个** | **rc=1,`FAIL(1 项)`,仅 overfit_monitor.sh** |
| c 护栏1 | timer **自己**带假 ExecStart(指向不存在路径)+ Triggers 链路正常 | 假样本被忽略,链路照判 | **`FAKE_should_be_ignored` 出现 0 次;rc=0** |
| d 护栏2 | trade-x.timer 假 ExecStart + 无 Triggers + 无同名 service | 绝不回落到 timer 自己的 ExecStart | **FAKE2 出现 0 次;0 条判定(fail-open 静默)** |
| e fail-open | Triggers→trade-y.service 但 service 条目缺失 | `[]`,绝不报「脚本被删」 | **0 条判定,rc=0** |

b 用例同时证明解析**确实非空**(若恒空,删脚本必报不出来 = 恒 rc=0 假绿)。

## 4. 测试质量(§18 L49 核心)— PASS

- **新 fixture 是真生产形态**:`_real_cloud_show` 的 timer 条目只带 `Triggers`(无 ExecStart)、service 条目持 ExecStart;逐字段与本次云上采样对齐(仅省略 `ignore_errors=no`/`stop_time`,对 `extract_script_paths` 无影响——只读 `argv[]` 的 .sh/.py token)。
- **删掉的 2 例确系假样本**:旧 `test_cfu_watchman_script_missing_rc1`/`_present_rc0` 均把 ExecStart 喂给 `.timer` 条目 = 云上不存在的输入形态(§18 L49 原病灶),删除正确。
- **无残留假样本**:工作树测试文件全部 `ExecStart` 引用逐一核过 = fixture(service 条目)/ 反假样本护栏 / fallback 测 / service-kind 测 / 真实路径 e2e,**无**给 timer 喂 ExecStart 的正向用例。
- **非空性有双保险**(防再次养绿):`test_resolve_exec_entries_timer_real_cloud_shape_nonempty` 对 7 个 timer 直接断言解析结果 == 云上真值路径;`..._missing_rc1_real_cloud_shape` 删 1 必报(若解析退化恒空,此例必红)。存在侧 rc=0 单测若单独看仍可被"空转"养绿,但与上述两例同套件锁死,组合后无盲区。
- **断言形态对**:断言对象 = 「真实对象**有没有**该字段」(timer 无 ExecStart 有 Triggers、service 有 ExecStart),且本次由审查者独立对云上实测复核(§2),非"只证解析器能解析"。
- 新增 8 例 + 辅助函数 3 个;测试文件 39→45(main 39 / 分支 45,collect 实测)。

## 5. pytest 独立复算 — PASS(并判 flaky 为环境性、与本次改动无因果)

```
worktree: pytest -q scripts/tests/   → 3 连跑均 241 passed, 1 skipped(0 failed;8.4s/6.9s/6.9s)
worktree: test_196 单文件              → 45 passed
main:     pytest -q scripts/tests/   → 235 passed, 1 skipped(collect 236)
main:     test_196 单文件 collect      → 39
```
- 与报告逐项对上:241/1、242 total、净 +6 = 新增 8 − 删 2、45/39。skip 原因实测 = `test_monitor_resource_inprogress_20261005.py:183: macOS APFS 的 df 为容器级口径`(与报告一致,双分支同 skip)。
- **flaky 判定:真环境性,非改动引入**。机理:`test_preflight_real_judge_branch_runs_on_non_systemd`(test_160,mac 分支)走 `check_r2_consistency.sh` 的 pgrep 回退(`pgrep -f "update_all.sh"`);**机器上只要存在任一 cmdline 含 `update_all.sh` 的活进程,该用例必失败**(preflight 误跳 → 断言 `[preflight-skip] not in log` 红)。
  - **手工复现**:`bash -c 'exec -a update_all.sh sleep 45'` 存活期间跑该用例 → **1 failed,报错文本与报告描述完全一致**;kill 后立即 **1 passed**。
  - test_160 与 `check_r2_consistency.sh` 均**不在本分支 diff**;本改动(监控脚本纯函数+测试)不影响任何进程名探测 ⇒ 与 #203 无因果。dev mac 上任意并发命令/agent 命中该字面量即触发,属既有用例的环境依赖(建议后续另立行加固,不阻塞本任务)。

## 6. 回归影响面(§15 / 上线影响)— PASS

- **生产调用方唯一** = `scripts/schedule_monitor.sh` L1534-1540:`check_failed_units.py --repo REPO --notify`,15min 一轮;rc 映射 0→日志 / 1→日志(自身通道已发)/ 3→跳过 / 其他→**SEVERE 进主告警邮件**。
- 行为变化(设计目标):②b 由「恒静默」→「可报」。上线后**稳态零变化**(rc=0,OK 行格式未动——schedule_monitor 读 stdout 首行);仅「守护脚本被删」这一真故障新增可见性。
- **上线后零假阳性已实测**(§2:7/7 脚本在盘);告警通道/去重 key/文案未动;`--notify` 真发路径、`_send_notify`、抑制逻辑 diff 未触。
- 本改动不涉前端/数据产物/R2/版本串 ⇒ §21 公示、§22 一致性、§24 防撕裂均**不适用**(diff 仅 scripts 3 文件 + docs)。
- `alert_denoise_rules.py` 仅 +4 行 docstring(逐行核过,无逻辑变更)。

## 7. 同类清单独立复核(§23.2③)— PASS

逐点 grep 复核实施报告 §6 清单,全部对:
- `extract_script_paths(` 生产侧调用点**仅** `check_failed_units.py:290`(tests 之外);其余命中均为注释。
- `ExecStart` 消费点:`systemd_timeout_gradient_audit.py`(`read_units` 过滤 `*.service`:dump 分支 `endswith(".service")`、目录分支 glob `trade-*.service`)✓;`gen_schedule_stats._systemd_last_exit` 经 `_label_to_systemd_unit` → `trade-*.service`,读 LoadState/ExecMainCode/ExecMainStatus(服务属性真实存在)✓;**全部 `.sh` 文件零 `ExecStart` 引用**✓。
- `systemctl show` 消费点:`check_r2_consistency.sh`(trade-update-all.service)/`schedule_monitor.sh` launchctl_loaded(trade-*.service)/`check_failed_units.py` 自身 ✓。
- `WATCHMAN_UNITS` 消费方仅 check_failed_units(+tests)。**结论:②b 是唯一「在无该属性的对象上取属性」的点,无同类残留。**

## 8. 报告对账 — 4 项低分偏差(照实列,不进 P0-P2)

| # | 项 | 实况 |
|---|---|---|
| 1 | 报告 §3 表称测试文件「替换 2 个假样本用例为 **7 个**真实形态用例」 | 实为 **8 个**新增用例(§8 的「+8」数字才准确);总账 45 数字正确 |
| 2 | 报告头部「自验:`scripts/tests/` 240 passed / 1 failed(**预存**,与本改动无关)」 | 该次 1 failed 非"预存失败",是 test_160 的环境性偶发(§5 机理复现);§8 正文描述准确,头部措辞易误读 |
| 3 | 报告 §6 表「`systemd_timeout_gradient_audit.exec_script` … `load_services()` 已过滤…(L74-75 注释)」 | 实际函数名 `read_units`(exec_script 经它喂文本),过滤注释在 L72-73;实质结论正确 |
| 4 | 报告 §8 「main 连跑 2 次」等历史跑数 | 无法回溯复核(仅本次 3+1 次实测),机制与结论一致,不构成不符 |

其余对账**全对**:d0826bcce 单 commit、base 33d380090 且为其祖先;`main() L231 起`(base ②b 注释在 L231)✓;`WATCHMAN_UNITS` 7 个 @ `alert_denoise_rules.py:69-77` ✓;「修复前 0/7 → 7/7」样本链 ✓;「7 脚本全在盘」✓;「extract_script_paths 仅此一处调用」✓;242/236/45/39/241/235/1 skip 全部实测复核一致。

## 9. 零外发/零生产写(本次审查)— 证据

- 云上:仅上述只读查询,零写。本地:`/tmp/rev203/*`(探针树/桩/输出)与 `/tmp/cloud_show_203.txt`。
- 双树 git status 空;`data/` 无新文件(60min 窗口);业务进程 pgrep 空。
- **如实披露**:审查期间执行的仓库脚本 = ①被审 `check_failed_units.py`(注入+dry,零 systemctl/零 notify);②仓库自带 CI 测试套件(pytest scripts/tests/,含既有沙箱化用例:test_160 的 wrapper 用 `PY=noop` 桩 + `REPO=tmp`、test_196 全部注入/dry、notify 相关用例 monkeypatch 发送层——自身无真实外发;该套件即 CI 门禁 ⑧ 常规项,非本次新增)。
- flaky 复现用的 `sleep` 进程已 kill 并验证消失(`pgrep` 空)。

## 10. merge 前提示(给主控)

- `origin/main` 在审查期间前移至 `b80c884bf`(33d380090 之后仅 2 个 docs-only commit,**未触被审 4 文件**)——merge 走 `main-merge.sh` 常规即可,无冲突面。
- 上线路径:merge → 云上 `trade-data-signal` pull(`trade-data/scripts` 为其 symlink,§0 报告已证)。上线后 15min 内可观测生产首轮;建议 §0 观察 `schedule_monitor_launchd.log` 的 `[196] CHECK_FAILED_UNITS_OK ...` 行 + `systemctl --failed` 空(预期 rc=0 无噪音)。
- §23.4:`docs/pending-features-index.md` #203 行修法描述(「改查配对 .service」)与本实现(Triggers 权威字段 + 同名回退,超集)一致,index 状态列待主控收口;本层无前端/产物展示位 ⇒ 无 §21/§22 同步项。

## 11. 低分项(<80,已滤出正式结论,列出防黑箱)

1. `_resolve_exec_entries` 重复取同一 unit 的 show(行构建已取;可选优化:把行 dict 传入,省 2-4 行/轮 7 次调用;over_engineering: action=simplify, saves_lines≈2, rationale=复用既有 dict)≈25 分,不影响功能。
2. 真实模式 systemctl 调用 7→21 次/轮;正常 <1s,极端挂死场景旧代码本已超 120s 父超时 ⇒ 非新类别。≈25 分。
3. 报告 §3「7 个用例」/头部「预存」措辞(见 §8-1/8-2)。≈50 分(仅是报告措辞)。
4. test_160 flaky 属既有用例环境依赖(建议另立行:加进程白名单/环境闸门),不属 #203。≈50 分。

## 12. 复现段(命令合集)

```bash
# ① 云上只读采样(零写;原始输出对比 /tmp/cloud_show_203.txt)
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'bash -s' <<'R'
for t in trade-cloud-unit-patrol trade-check-monitor-heartbeat trade-schedule-monitor trade-self-heal \
         trade-r2-consistency trade-check-data-gap trade-overfit-monitor; do
  systemctl show "$t.timer" -p Id -p LoadState -p ActiveState -p UnitFileState -p Triggers -p ExecStart
  svc=$(systemctl show "$t.timer" -p Triggers --value); systemctl show "$svc" -p Id -p LoadState -p ActiveState -p UnitFileState -p ExecStart; done
for f in cloud_unit_patrol.sh check_monitor_heartbeat.py schedule_monitor.sh self_heal.sh check_r2_consistency.sh check_data_gap_alerts.sh overfit_monitor.sh; do test -f "/home/ubuntu/code/trade-data/scripts/$f" && echo "OK $f"; done
R
# ② A/B 回放(新 vs base, 云上真字节 + static-only systemctl 回放桩; 见本报告 §2)
# ③ 反向对照/护栏(注入 JSON 探针; 见 §3)
# ④ 全量复算
.venv/bin/python -m pytest -q scripts/tests/                       # worktree 3 连: 241 passed/1 skipped
cd /Users/linhuichen/code/trade && .venv/bin/python -m pytest -q scripts/tests/   # main: 235 passed/1 skipped
# ⑤ flaky 机理复现(慎跑:会造一个 sleep 进程;结束即 kill)
bash -c 'exec -a update_all.sh sleep 45' & disown; sleep 1
.venv/bin/python -m pytest -q "scripts/tests/test_160_r2_consistency_followup_20261005.py::test_preflight_real_judge_branch_runs_on_non_systemd"  # 期望 FAIL(复现)
```

## 13. 参考

- 施工报告:`docs/ops/203-check-units-timer-20261006.md`;上游发现:`docs/ops/193-196-live-verify-20261006.md` §5/§P2。
- 规范:CLAUDE.md §18 L49/L50、§23.2/§23.3/§23.4、§15 分级;role-reviewer skill §10.2/§10.5/§10.6。
