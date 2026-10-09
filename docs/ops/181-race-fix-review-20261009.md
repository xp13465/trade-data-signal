# #181race「幻影 +1」修复 独立复审报告(2026-10-09)

- reviewer agent 独立复审(fresh context,不采信实施报告,逐项独立取证)
- 审查对象: 分支 `worktree-agent-a3a04121f613938fa` @ `90aea3d5e`;base = origin/main `4325a27d5`
- 方式: 只读;static-only 探针(ast 抠 monitor heredoc 纯逻辑块 + 直调 gen_schedule_stats);全量 pytest;零外发/零 R2 写/零云上写
- 总判定: **PASS**(可进 merge 流程;附 F1/F2 报告补正 + F3 merge 前动作项,**均不阻断**)

## 0. 逐项判定

| 项 | 判定 |
|---|---|
| ① 根因与修复正确性(最高风险) | PASS |
| ② 改动面边界 | PASS |
| ③ 向后兼容 | PASS(附 F2) |
| ④ 测试数字真实性 | PASS |
| ⑤ §23.3 扫描可信度 | PASS |
| ⑥ §22 字段一致性 | PASS |
| ⑦ 诚实边界 | PASS(附 F1) |

## 1. 审查方法(独立取证)

1. **static-only 探针**(/tmp/probe_181_review.py):`ast` 提取 `schedule_monitor.sh` 内 `<<'PYEOF'` 的 r2_skip 状态机纯逻辑块到受控命名空间 exec(§18 L50:绝不 source/exec 业务脚本主体);`import gen_schedule_stats` 直调 `scan_marker_log` 真函数。6 组探针 P1-P6。
2. **全量 pytest**(mac venv Python 3.11.0 = CI 3.11;scope 与 `.github/workflows/ci.yml` L123 逐字一致)+ 逐 worktree collection 对账。
3. **定向 grep 复核**:字段字面、`last_round` 消费点全量、`st_mtime` 站点抽核、sample 文档引用点。
4. **反事实路径复核**:证明 `r2_round_id` 缺席时新代码与旧代码逐字等价。

## 2. 逐项结论与证据

### ① 根因与修复正确性 — PASS
- **恒定性证明(代码层)**: 回溯搜索 `range(window_start_idx, -1, -1)`(gen L866-871)自窗口起点行向下标递减;新轮的「轮次开始」行下标恒 > window_start_idx(数学上不可达);窗口 `[start 行, EOF)` 在「已写」写入前不前移 ⇒ 标识恒锚**窗口所属轮**,竞态任意 tick 恒定。
- **探针 P2 实测**: 同一日志两形态读(「01:01 轮 已写 为末条」vs「01:45:00 新轮已 flush 无已写」),`window_round_ts` 恒 = `2026-10-09 01:01:00`,skip_count=1 不变;而 M1 的 `round_start_ts` 读到 01:45:00 ⇒ 恰证「直接用最新轮次开始」不足、本修向正确。
- **反事实成立**: r2_round_id 缺失 ⇒ `_r2_round = _r2_lr`(monitor L1057),与旧代码逐字等价;测试 `strip_round=True` 恰在 **01:45:02** 出单发幻影 SEVERE(`fires == ["01:45:02"]`)。
- **新边界逐一核**: 无窗口起点 ⇒ None 回退(P6);多 skip 同窗口 ⇒ 计数正常涨、标识恒(P3);gen_daily_brief(`round_begin_re=None`)⇒ 恒 None 回退(P5);「轮开始行缺失 ⇒ 锚更旧轮」理论不可达(轮开始 = 本轮首行 print,缺行则亦无已写)。
- 关键行号: gen L823/828(窗口起点下标)、L865-871(回溯)、L885(5 元组返回)、L1158(解包)、L1198(`r2_round_id`);monitor L1057/1059/1062、L1100。

### ② 改动面边界 — PASS
- monitor diff 净 16 行 = 13 增(9 注释 + 4 代码)/ 3 删;**`_r2_fresh` 与阈值常量(L556 `R2_SKIP_CONTINUOUS_THRESHOLD=3` / L566 `R2_SKIP_OBS_WINDOW`)均不在 diff**。
- `last_round` 全仓消费点 = schedule_monitor.sh L1059/1062/1100/1122 + 测试;**无任何第三方按时间戳语义消费**;`check_signals.py` 的 `last_round_time/last_round_pairs`(L1171/1189/1190/1242)为信号持续性概念,与本 alert_state 无关(同名不同物)。
- 前端: static-site 全量 grep `r2_round_id` = **0 命中**;`r2_skip_count` 消费不涉及 last_round 格式。

### ③ 向后兼容 — PASS(附 F2)
- 缺 `r2_round_id`(旧 stats / 非 EXTRA 任务 / 无窗口起点)⇒ 回退 `last_run`,行为与改动前逐字一致;非 EXTRA 任务(如 overfit_monitor)不受影响。
- **F2(升级瞬变,已复现)见 §3**,一次性 + 自愈、现网≈0 风险,不阻断。

### ④ 测试数字真实性 — PASS
- 本分支实测(仿 CI scope): `pytest -q scripts/tests/` = **482 passed, 2 skipped(92.2s)**,collect **484**(42 个测试文件)。
- **算术闭合**: base main collect 475(main 版 test_181+228 收集 37 vs 分支 46,+9)⇒ 475+9=484 ✓。
- **"563" 不可复现**: 现存各 worktree collection = 464 / 475 / 502 / 573(各分支测试文件集不同);差异源 = 分支文件集不同,**非缩幅/漏跑**;无其它 pytest 可收集目录(`scripts/test_*.py` 为脚本式、0 test 函数)。
- **2 skip 定位**: `test_212_upload_onfail_loud_pytest.py:385`(干净 worktree「已提交态」跳过静态对照)+ `test_monitor_resource_inprogress_20261005.py:183`(macOS APFS 平台差异)——均既有环境性跳过,与本次改动无关;新用例 46 项(test_181+228)全 pass 0 skip。

### ⑤ §23.3 扫描可信度 — PASS
- 抽核 6 处 `st_mtime/getmtime` 站点: schedule_monitor.sh L2453/2472、check_monitor_heartbeat.py L66、lock_watchdog.py L77、alert_denoise_rules.py L380、check_data_gap_alerts.py L886、feishu_ws_listener.py L898-913 —— **全部为新鲜度/年龄/stall/缓存/排序用途**,年龄阈值均 ≫ 秒级 ⇒ 「mtime-as-round-identity 唯此一处」结论可信。
- M1 通道: `round_state` 用内容时间戳 + `unit_active_state`/GRACE 双护栏,同秒起跑不产生同款幻影(复核实施报告 §4.3 与代码一致)。

### ⑥ §22 字段一致性 — PASS
- 生产侧 gen L1198 `"r2_round_id": _window_round_ts` / 消费侧 monitor L1057 `s.get("r2_round_id")` —— 字面逐字相同;机检用例 `test_field_name_wired_producer_to_consumer` 对两侧字面做双向校验,真实挂链。
- 字段为纯新增: 无「同事实多副本」登记点、无前端展示面 ⇒ 无 §22 多展示位同步面。

### ⑦ 诚实边界 — PASS(附 F1)
- fixture 行**逐字核对真 print**: `fetch_news.py` L585(轮次开始,flush)/ L633(已写)/ L747-749(SKIPPED_LOCKED 含兜底后缀)/ L768(同步上线完成);链 E 行号引用与 sample 文档 §5.1 一致。
- 判别力: 反事实精确命中 01:45:02 单发 ⇒ 形态具判别力且被真代码路径驱动。

## 3. 发现(F1/F2)+ merge 前动作项(F3)

### F1(报告问题,不阻断): 报告 §4.1 格式陈述错误 + fixture 列格式简化
- 实施报告 §4.1 称「`last_round` 状态值格式仍是 `YYYY-MM-DD HH:MM`」——**实为带秒** `YYYY-MM-DD HH:MM:SS`(`_ROUND_TS_RE` gen L198-200 捕获秒;探针实测 `2026-10-09 01:01:00`)。
- `race_ticks.csv` 第 4 列 r2_round_id 用**分钟粒度**(如 `2026-10-09 01:01`),与生产秒粒度不同流:不损等值判别力(比较为纯字符串相等),但掩盖了 F2 格式迁移面(若用秒值可另加一例锁死迁移行为)。
- 建议: 报告 §4.1 更正;后续可给 fixture 补秒粒度样例(非阻断)。

### F2(升级瞬变,已复现,不阻断): 升级首 tick 一次有效 +1
- 机制(探针 P1 实测 n 1→2): 升级瞬间 alert_state 旧值 = 分钟串(`2026-10-09 01:02`),gen 新产 = 秒串(`2026-10-09 01:01:00`),同一真轮字符串必不等 ⇒ `_r2_same_round=False` ⇒ +1。
- 后果: 若升级时刻恰处 n=2 链上 ⇒ 多发一次 SEVERE(即本修复所灭的幻影类);**一次性**(格式迁移只发生一次)+ **自愈**(下个非 skip tick 清零)。
- 现网风险≈0: sample 文档 §3.3 显示云上链已清零。回滚(新状态秒串 + 旧代码分钟串)对称同瞬变、同样自愈。
- 建议: 实施报告 §4 补一段「升级瞬变」诚实披露(无需代码改动)。

### F3(merge 前动作项,75 分): sample 文档未在 git
- `docs/ops/181-denoise-prod-sample-20261008.md` 被 4 处引用: gen_schedule_stats.py L851 注释、schedule_monitor.sh L1054 注释、race_ticks.csv 头部、实施报告 §前置证据源 —— 但该文档**仅存在于主仓工作区(untracked)**,不在本分支、不在任何 commit。
- 动作: merge 前由主控确认将该文档落档(§23.5),否则新注释的引用链悬空。

## 4. 低分滤除(记录不计缺陷)

- L1(50): monitor L1020 旧注释仍写「last_round(= stats last_run 分钟串)」,与下方新注释(L1049-1055)/新实现(存 r2_round_id 秒串)自相矛盾 —— 纯注释陈旧,不改判别。
- L2(50): 极端形态「轮开始行缺失 ⇒ 窗口锚到更旧轮」——理论不可达(轮开始 = 本轮首行 print)。
- L3(50): 4 天窗口既有用例走**回退(mtime)语义**,其「5 发」是旧语义基线 ≠ 新语义下生产预期(新语义下残留幻影链会更少);语义分工已在夹具注释写明,非缺陷。
- L4(25): dup 调试打印 `last_round=` 值格式由分钟变秒,信息性,不改判别。

## 5. 合规自证

- **只读**: 业务文件零改动;worktree 仅新增本报告文件(不 commit)。
- **零外发**: 探针 = ast 纯逻辑块(结构上无 notify/网络/子进程调用面);全量 pytest 与既有 `test_zero_real_outbound` 打桩守门同跑。
- **零 R2 写 / 零云上写**: 全程本机只读。
- 无 `find /`、无无白名单 `grep -r`、无裸跑 pip/npm、无 Docker、无 WebFetch;每条 Bash 带超时。
- **残留后台任务: 无**(全程无 `moved to the background` 事件)。

## 6. 复现命令(只读)

```bash
cd /Users/linhuichen/code/trade/.claude/worktrees/agent-a3a04121f613938fa
/Users/linhuichen/code/trade/.venv/bin/python -m pytest -q scripts/tests/    # 482 passed / 2 skipped
git diff --stat origin/main..HEAD                                          # 6 文件(+383/-12)
/Users/linhuichen/code/trade/.venv/bin/python -m pytest -q -rs \
  scripts/tests/test_181_fetchnews_denoise_20261007.py \
  scripts/tests/test_228_round_incomplete_20261007.py                       # 46 passed(含反事实)
```
