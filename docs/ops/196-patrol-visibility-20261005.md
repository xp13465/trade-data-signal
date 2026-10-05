# #196「巡检/链路自身死亡」可见性统一(F1 族静默根治第一批)

- 日期: 2026-10-05(晚批)
- 分支: `feat/196-patrol-visibility-20261005`(worktree 隔离; 只推 feat, 不推 main)
- 角色: implementer
- 关联: #194 reviewer P2-1/P2-2(2026-10-05 独立审查)、#191 reviewer P2-1/P2-2、
  #160(P0「连续 2 天 FAIL 升 critical」先例)、#187(R7 实现)、#154(check_monitor_heartbeat 挂载)
- 用户拍板(2026-10-05): 云上 unit patrol **连续 3 天**仍异常 → 升 critical(口径同 #160 / #187)

---

## 一、病灶(为什么做)

1. **全站没有任何 `systemctl --failed` 的消费方。** `schedule_monitor` 的 11 个 label 无 patrol,
   `schedule_stats` 三副本 `grep -c patrol` = 0。⇒ 任何 unit 静默失败(#194 的 `exit 3`、
   #191 的漂移巡检被删)在 systemd 层可见、在监控层**零消费**,要人工 `systemctl --failed` 才见。
2. **#191 的云上巡检 `scripts/cloud_unit_patrol.sh` 本身不在任何监控里。** 脚本被删 →
   该系统不启动该 unit(见 §三.2 的 `ConditionPathExists`)⇒ 永久静默,**「巡检者死了没人知」**。
3. **#194 P2-1 的「假告警」被换成「静默 SKIP」**: F2 环境守卫让非云上返回 `exit 3`;
   但 `exit 3` 没有消费方 ⇒ 从「误报」变成「静默」。两者都是「真相没到人眼前」。

## 二、交付物(7 改 1 新 + 报告)

| 文件 | 动作 | 作用 |
|---|---|---|
| `scripts/check_failed_units.py` | 新增(~290 行) | ① failed-unit 消费方 + ② 巡检者自身存活 + ②b 脚本存在性 |
| `scripts/alert_denoise_rules.py` | 改 | 通用升档 `consecutive_days_escalate` / `parse_failed_units` / `judge_watchman_units` / `extract_script_paths` / `wrapper_channel_alerted` + 常量(含 `WATCHMAN_UNITS`) |
| `scripts/notify.py` | 改 | 两个新去重 key 的**升档拦截**(连续 3 天 → critical),复用 R7 先例 |
| `scripts/gen_schedule_stats.py` | 改 | TASKS + `LABEL_MAP` 登记 `cloud_unit_patrol`(登记点 1、2) |
| `scripts/schedule_monitor.sh` | 改 | TASKS 登记(登记点 3) + patrol `exit!=0` 定向抑制 + 调用 check_failed_units + 「巡检脚本自身异常」告警位 |
| `scripts/self_heal.sh` | 改(仅注释) | 登记点 4 的收录边界就地写明(巡检/监控类故意不进自愈白名单,理由见 §七) |
| `scripts/tests/test_196_patrol_visibility_20261005.py` | 新增(39 用例) | 本任务全部判定的机检 + §22/§23.3 一致性机检(挂 CI 闸门 ⑧) |
| 本报告 | 新增 | 含 `## 复现段` |

**没有新建任何 systemd unit**: new unit = 生产写操作 + 需同步云上快照与 §2 闸门。
本任务挂在**既有** `trade-schedule-monitor.timer`(15min)上,零生产改动、零新调度器。

## 三、实现要点

### ① failed-unit 消费方(原病灶 1)
`check_failed_units.py` 跑 `systemctl list-units --state=failed --no-legend --no-pager --plain`,
非空即告警(经 `notify.py --severe`,`--dedup-key failed_units_patrol --dedup-window 21600`)。
由 `schedule_monitor.sh`(既有 15min timer)以子进程调用,**只告警不改生产**
(不 restart/reset-failed/enable/disable 任何 unit,处置交人工)。

出口码与调度器侧的映射(「本巡检自己跑挂了」也必须可见):

| 出口码 | 含义 | schedule_monitor 侧 |
|---|---|---|
| 0 | 健康 | 记日志 |
| 1 | 发现异常 | 记日志(自身通道已发告警) |
| 3 | 跳过(非云上, 无 systemctl 且无注入样本) | 记一行 `[196] ... 跳过`, **不告警** |
| 其他/异常 | 巡检脚本自身故障 | 追加一条 `SEVERE` 进主告警邮件(FAIL LOUD) |

### ② patrol 自身纳入监控(原病灶 2)—— 四路互不重叠
| 失败模式 | 谁发现 |
|---|---|
| 脚本被删(注册过的任务) | **注册漏跑**(日志不再出现该任务 → `schedule_monitor` MISSED 告警) |
| 脚本被删(全部 7 个守护 unit) | **②b 脚本存在性**(与注册无关, 见 §三.3) |
| timer 被停 / 禁用 / unit 文件离盘 | **② 巡检者存活**(ActiveState + UnitFileState + LoadState) |
| 跑起来却失败(漂移 / exit 3) | **① failed-unit** + `gen_schedule_stats` 的 `exit!=0` 通道 |

**关键原理(必须写清, 否则会误以为 ② 冗余)**:
`trade-cloud-unit-patrol.service` 带 `ConditionPathExists=<REPO>/scripts/cloud_unit_patrol.sh`
(云上快照第 106 行实证)。脚本被删时 systemd **根本不启动该 unit** = 条件不满足则 **skipped**,
**既不进 failed、也不写 ExecStart 日志**(实测云上 systemd 249)。⇒
① failed-unit 通道**看不见**它,**只有漏跑/脚本存在性通道能发现**。这就是「注册进 TASKS」不是
冗余而是必需的原因。

### ②b 脚本存在性(§23.3 举一反三的扩展)
对 `WATCHMAN_UNITS` 的 7 个守护 unit,解析 `systemctl show -p ExecStart` 的 `argv[]`,
取「以 `/` 开头且以 `.sh`/`.py` 结尾」的 token = 被执行的脚本本体,`Path.exists()` 判在不在盘。

- **零误报设计(fail-open)**: 解析不到(格式不符/无 argv[])就**不判**,绝不把「解析失败」
  报成「脚本被删」。只认 `.sh`/`.py` 绝对路径,解释器/flag/子命令一律不认。
- **只在云上生效**: 本脚本先过「无 systemctl → exit 3」环境守卫,故 `/home/ubuntu/...` 路径可判真伪。
- **云上实测证据(只读)**: 7/7 守护 unit 的脚本全部在盘(mac 侧 ssh 只读执行,结果见 §八)。

### ③ 升档落地(用户拍板「连续 3 天」)
- 通用实现 `alert_denoise_rules.consecutive_days_escalate(state_path, now, escalate_days, log_prefix)`
  → 返回 `("severe"|"critical", 连续天数, 首次失败日)`。
- **计数持久化**(硬要求): 状态写 `data/*_state.json`(`{last_fail_date, consecutive_days,
  first_fail_date, last_grade_time}`),**原子写**;同一天不重复计数;间隔 >1 自然日 → 从 1 重计。
  **重启/重跑不清零**(用户原话要求)。落盘失败 → stderr 明示「计数可能丢失」,不静默。
- **两条通道各自独立升档 key**(不占首日 6h 窗):
  - `cloud_unit_patrol_drift` → `cloud_unit_patrol_drift_escalated`(连续 3 天漂移)
  - `failed_units_patrol` → `failed_units_patrol_escalated`(连续 3 天异常)
- **R7 同源**: `r7_r2_consistency_escalate` 已改为委托同一函数(阈值 2 不变),
  等价性由回归测试逐字锁住(`test_r7_regression_two_days_and_message`)。
- **守 `alert-denoise-keep-fault-discriminator`**: 升级的是**真故障判别维度**
  (unit 真实 failed / 脚本真实消失 / 真实漂移),不是「跑得少」「非交易日」这类环境噪音。

### ④ 默认方案:#194 P2-2 的窄静默窗 → 选「① 本任务统一收口」
两选项:① 等本任务统一收口;② 加「云上特征」二级判别(`/run/systemd/system` 存在 + 目录存在但
无 `trade-*.service` → 换 dedup key 仍告警,**代价 = Linux 开发机/容器会被误伤**)。
**默认取 ①,不取 ②**,理由:
1. ② 的收益窗口(「非云上但被误判成云上」)已被 ①③ 闭死:unit 在云上真实失败 → ① failed-unit 通道;
   unit 离盘/脚本被删 → ②b/漏跑通道。窗内剩余情形(非云上环境伪装成云上)在生产不存在。
2. ② 的代价是真的:Linux 开发机/容器上 `exit 3` 变告警 ⇒ **把降噪规则换成新噪音源**,
   与 `alert-denoise-keep-fault-discriminator` 反向。
3. `exit 3` 在非云上是**正确语义**(确实无法巡检),不该被降级成「要告警」。
⇒ 保持 `exit 3` 静默 + 由本任务三层兜底,是「零附加噪音换同等覆盖」的解。

## 四、告警噪音控制(防一次故障三封邮件)

patrol 漂移时会同时命中三条通道(patrol 自己的 notify + `schedule_monitor` 的 `exit!=0`
+ 本巡检的 failed-unit),故做**定向抑制**:

- `adr.wrapper_channel_alerted(repo, last_run, dedup_key)`: 读 `data/notify_dedup.json`,
  `last_alerted >= last_run` 才算「本次运行实例已发」。**fail-open**: 去重表缺失/发送失败 → 判 False
  → **照报**(绝不吞真故障)。R7/R3 同款先例。
- 只对 `trade-cloud-unit-patrol.service` 这一个 unit 抑制(`check_failed_units.py`);
  其余任何 unit 失败**照报**(它们没有别的通道)。
- **patrol 的 `exit 3` 故意不抑制** —— 那正是 #194 P2-1 要求「可见」的东西。
  `schedule_monitor` 侧对 `cloud_unit_patrol` 的 `exit!=0` 抑制也只在包装器通道已发时生效。
- 状态机细节: `seen_keys_this_run.add(_cfu_key)` 在恢复循环**之前**标记,避免「巡检脚本自己
  恢复正常」被误判成「未见过」。

## 五、§23.2 修 bug 三铁律: 同类错误面清单 + 逐项自测结果

**同类面 = 「os "在跑/健康" 的判据本身不可靠」(#160 P0 同款: oneshot 运行中 `is-active`
返回 `activating` 且 rc=3,与 `inactive` 同 rc)。** 全仓枚举与判定:

| # | 位置 | 现状 | 判定 |
|---|---|---|---|
| E1 | 本任务新增代码(`check_failed_units.py` ②) | 一律 `systemctl show -p ActiveState`,**禁 is-active** | PASS(本任务铁律) |
| E2 | `scripts/check_r2_consistency.sh:82-88` | 已用 `systemctl show -p ActiveState --value` + `case active\|activating)` | PASS(#187 已修) |
| E3 | `scripts/self_heal.sh:103` | 用 `is-active`,但显式处理 `activating`(oneshot 运行中不误判) | PASS(存量, 不在本任务范围; 无行为问题) |
| E4 | `scripts/schedule_monitor.sh:1161 launchctl_loaded()` | 用 `is-active`,但语义**定义**为「unit 是否已加载」而非「是否在跑」,函数内已写明 `rc=3(inactive 或 activating)均 = 已加载`,并写明「判在跑照 self_heal.sh / check_r2_consistency.sh」 | PASS(注释已纠正,**不得照错注释写判据**) |
| E5 | `docs/deploy/systemd-units-cloud-snapshot.txt` 的 patrol/oneshot 说明 | `Type=oneshot` | 已据此设计(只对 `.timer` 判 active) |

**逐项自测**: 见 `scripts/tests/test_196_patrol_visibility_20261005.py`
(39 用例,含 `test_judge_watchman_units_timer_stopped` / `test_cfu_watchman_stopped_rc1` /
`test_extract_script_paths_*` 反向用例)。**根因修而非逐文件补丁**: 判据统一收敛到
`alert_denoise_rules` 这一个纯判定模块(单一事实源),不再各脚本各写一份。

## 六、§23.3 举一反三清单 + 逐项覆盖结果

**同模式(「脚本/守护被删 = 静默无出口」)在云上还被谁用?** 全量扫快照:
`grep -c ConditionPathExists` = **3**(云上快照第 88/106/557 行):

| ConditionPathExists 的 unit | timer 是否进 WATCHMAN_UNITS | 脚本被删时谁发现 | 覆盖结果 |
|---|---|---|---|
| `trade-cloud-unit-patrol.service` | 是 | 注册漏跑(本任务登记)+ ②b 脚本存在性 | 已覆盖 |
| `trade-check-monitor-heartbeat.service` | 是 | ②b 脚本存在性(15min 档, 不适配「每日 HH:MM」漏跑模型) | 已覆盖 |
| `trade-r2-consistency.service` | 是 | 注册漏跑(#160/#187 已登记)+ ②b | 已覆盖 |

⇒ 机检锁死: `test_conditionpathexists_units_all_watchman_covered`
(以后新增任何带 `ConditionPathExists` 的 unit 而没进 WATCHMAN_UNITS → CI FAIL)。

**WATCHMAN_UNITS 收录边界(显式声明, 防「清单越收越肥」)**:
**只收「无数据产物可反证其存活」的守护/巡检/监控调度器**(7 个: patrol / check-monitor-heartbeat /
schedule-monitor / self-heal / r2-consistency / check-data-gap / overfit-monitor)。
**不收**采集器/生成器/发布器 —— 它们死了会表现为**数据陈旧 / 漏跑 / 自己的响亮通知**,
已有判别维度;收进来只会制造同义告警。边界写在 `alert_denoise_rules.WATCHMAN_UNITS` 注释里。

**相关展示位/消费方**: 本任务是告警链改动,**不涉及站点任何展示位**(无前端、无 JSON 产物字段),
故无 §22「多展示位一致性」对象;§22 的对象改为「同一事实的多处代码副本」(见 §七)。

## 七、§22 登记点清单(同一事实多副本)+ 机检

「云上有哪些被监控的定时任务」这一事实在仓库内有 **3 个副本**(即 #196 描述里的
`schedule_stats` 三副本),本任务逐一同步:

| 副本 | 位置 | 登记内容 |
|---|---|---|
| 1 | `scripts/gen_schedule_stats.py` → `TASKS` | `{"task": "cloud_unit_patrol", "name": "云上unit漂移巡检", "script": "cloud_unit_patrol.sh", "schedule": "08:27", "log": "cloud_unit_patrol_launchd.log", "mode": "standard"}` |
| 2 | `scripts/gen_schedule_stats.py` → `LABEL_MAP` | `"cloud_unit_patrol": "com.trade.cloud-unit-patrol"` |
| 3 | `scripts/schedule_monitor.sh` → `TASKS` | `{"task": "cloud_unit_patrol", "log": "cloud_unit_patrol_launchd.log", "trading_day_only": False, "schedules": ["08:27"]}` |

第 4 处候选 `scripts/self_heal.sh` 的 `HEAL_ACTIONS`: **判定不登记** —— 自愈只处理
「已登记且已知可安全重跑」的任务,patrol 是**只读巡检**(重跑无意义, 且它自己失败时应人工排查);
登记进自愈白名单会把「人工确认」变成「自动重跑」,反而掩盖漂移。该判定已写进
`self_heal.sh` 侧注释 + 由 `test_registry_selfheal_subset_of_gen` 兜住方向(子集关系不破)。

**机检(挂 CI 闸门 ⑧ `python3 -m pytest -q scripts/tests/`)**:
- `test_registry_patrol_present_in_all_three`(副本 1/2/3 齐)
- `test_registry_patrol_label_matches_cloud_unit_name`(label→unit 名 ⇔ 云上快照真实 unit)
- `test_registry_monitor_tasks_subset_of_gen`(副本 3 ⊂ 副本 1,否则 = 监控盲区)
- `test_registry_selfheal_subset_of_gen`(自愈白名单 ⊂ 副本 1)
- `test_watchman_units_exist_in_cloud_snapshot` + `test_watchman_units_have_syslog_service_counterpart`
  (防清单写了不存在的 unit → 恒假告警)
- `test_conditionpathexists_units_all_watchman_covered`(§23.3 覆盖面, 见 §六)

## 八、自验命令与结果(逐条可复现)

| 验证 | 命令 | 结果 |
|---|---|---|
| 本任务用例 | `.venv/bin/python -m pytest -q scripts/tests/test_196_patrol_visibility_20261005.py` | **39 passed** |
| 全量回归 | `.venv/bin/python -m pytest -q scripts/tests/` | **231 passed, 1 skipped** |
| shell 语法 | `bash -n scripts/schedule_monitor.sh` | OK |
| python 语法 | `python -c "ast.parse(...)"`(4 文件) | OK |
| 内嵌 heredoc | 抽取 `<<'PYEOF'` 块 `ast.parse` | OK(2618 行) |
| **云上脚本存在性(只读)** | `ssh ubuntu@122.51.111.173 'for u in <7 unit>; do p=$(systemctl show -p ExecStart trade-$u.service \| sed -n ...); [ -f "$p" ] && echo OK...'` | **7/7 OK**(见下) |
| 云上 systemd 版本/格式(只读) | `systemctl --version` / `systemctl show -p ExecStart trade-cloud-unit-patrol.service` | `systemd 249`;`ExecStart={ path=/bin/bash ; argv[]=/bin/bash /home/.../cloud_unit_patrol.sh ; ... }`(解析层按此实测格式实现) |
| 云上 `ConditionPathExists` 可否由 `systemctl show` 读出(只读) | `systemctl show -p ConditionPathExists trade-cloud-unit-patrol.service` | **输出为空** ⇒ 不能用该属性判,改用 ExecStart 解析(故 §三.2b 的存在性层是必要的) |

云上 7/7 实测输出(证明 ②b 层当前**零假阳性**):
```
OK   cloud-unit-patrol     -> /home/ubuntu/code/trade-data/scripts/cloud_unit_patrol.sh
OK   check-monitor-heartbeat -> /home/ubuntu/code/trade-data/scripts/check_monitor_heartbeat.py
OK   schedule-monitor      -> /home/ubuntu/code/trade-data/scripts/schedule_monitor.sh
OK   self-heal             -> /home/ubuntu/code/trade-data/scripts/self_heal.sh
OK   r2-consistency        -> /home/ubuntu/code/trade-data/scripts/check_r2_consistency.sh
OK   check-data-gap        -> /home/ubuntu/code/trade-data/scripts/check_data_gap_alerts.sh
OK   overfit-monitor       -> /home/ubuntu/code/trade-data/scripts/overfit_monitor.sh
```

**自测未产生真实外发(§18 L48 / memory `notify-script-selftest-must-stub`)证据**:
1. `check_failed_units.py` 默认 **dry**(`--notify` 才真发);所有端到端用例走注入样本且不打
   `--notify`,断言 stderr 含 `dry-run: 未真发通知`。
2. `notify.py` 侧用例用 `stubbed_notify` fixture **monkeypatch 掉全部出口**
   (`send_tiered`/`send`/`check_dedup`/`update_dedup`/`write_alert`),只断言入参,跑完零外发。
3. 本任务全程**未对生产做任何写操作**:云上只读查询(`systemctl show` / `-f` 测试 / `systemctl --version`),
   未新建/启用/停用任何 unit,未 `reset-failed`,未改云上文件。

## 九、判定「不适用 / 未做」的规范(显式声明)

- **§21 算法公示同步**: 不适用。无任何算法/数值/权重/阈值/展示口径变更,不碰前端。
- **§23.1 README**: 不适用。未引用外部开源项目,非站点功能发布(纯告警链改造)。
- **§24 前端防撕裂**: 不适用(未改 `app.js`/`lab.js`/`common.js`/`index.html`,故**不 bump 版本串**;
  任务亦明确「不要自行 bump 版本串」)。
- **§23.15 上线必须完整版**: 本任务无数据产物、无残缺展示,不涉及。
- **§25 删除前必备份**: 本任务**无任何删除动作**(未删文件、未清缓存、未 gc)。

## 十、冲突与待上报(§23.4 / §23.11)

- **同模块并行风险**: 并行在跑的 **#193**(R2 通道覆盖缺口)也可能新增 `gen_schedule_stats.TASKS`
  条目(同一处登记点)。本任务与 #193 声明的改动面(`scripts/upload_r2.py` / R2 相关)不重叠,
  但**登记点同文件**属残余风险 ⇒ **上报主控: merge 时若两分支都改 `gen_schedule_stats.py`,
  按 §23.11 人工确认合并结果(不得静默吞掉任一方的 TASKS 条目)**,本任务的机检
  (`test_registry_monitor_tasks_subset_of_gen`)会自动暴露「合并后丢条目」。
- **禁区遵守**: 未改 `scripts/upload_r2.py`(#193)、未改 `scripts/check_r2_consistency.sh`(#187)、
  未碰前端。
- **全程无静默吞掉事件**: 未遇到 git 冲突/覆盖/版本倒退;推送只走 feat 分支。

## 十一、诚实标注 / 残余风险

1. **`check_monitor_heartbeat.py` 的已知边界**(#156 已登记, pre-existing):时钟回拨漏报、
   父目录不可达 rc=1 无告警。本任务**未修**(不在范围),但它是 #182「飞书 hook 心跳永久空转」的
   同族项 —— 已由 ②(WATCHMAN 存活)覆盖其「timer 停摆」面。
2. **②b 依赖 `systemctl show` 的 `argv[]` 文本格式**。云上 7/7 实测同形(systemd 249);
   若未来 systemd 大版本改格式 → 解析返回 `[]` → **fail-open 不报**(宁可漏这一层,
   也不制造假告警);且 `test_extract_script_paths_*` 锁住当前格式,格式漂移会先让 CI 红。
3. **漏跑通道对 15min 档任务不适配**: `schedule_monitor` 的漏跑模型是「每日 HH:MM 槽」,
   `check-monitor-heartbeat`(15min 档)故意**不登记**为漏跑任务(硬塞会造出错误期望值 → 假告警),
   其脚本删除面由 ②b 覆盖。这是**取舍**,不是遗漏。
4. **`failed_units_patrol` 的去重窗 6h**: 15min 一轮 ⇒ 一轮发现 sustained 失败后 6h 内不重发,
   第 2/3 天由升级档通道送达 critical。属设计(防告警风暴), 非缺陷。

---

## 复现段

```bash
# 0) 环境
cd <repo>            # 本分支 feat/196-patrol-visibility-20261005
PY=<repo>/.venv/bin/python

# 1) 本任务全部判定的机检(纯函数 + 端到端 + §22/§23.3 一致性)
$PY -m pytest -q scripts/tests/test_196_patrol_visibility_20261005.py     # 期望 39 passed

# 2) 全量回归(CI 闸门 ⑧ 同款命令)
$PY -m pytest -q scripts/tests/                                          # 期望 231 passed, 1 skipped

# 3) 语法
bash -n scripts/schedule_monitor.sh
$PY -c "import ast;[ast.parse(open(f).read()) for f in
  ['scripts/notify.py','scripts/gen_schedule_stats.py','scripts/alert_denoise_rules.py','scripts/check_failed_units.py']]"

# 4) check_failed_units.py 手动跑(离线注入样本, 默认 dry = 绝不真发通知)
#    A. 健康(期望 rc=0 / CHECK_FAILED_UNITS_OK)
echo -n "" > /tmp/fu.txt
$PY -c "import json,sys;sys.path.insert(0,'scripts');import alert_denoise_rules as a;print(json.dumps({u:{'ActiveState':'active','LoadState':'loaded','UnitFileState':'enabled'} for u,_ in a.WATCHMAN_UNITS}))" > /tmp/show.json
$PY scripts/check_failed_units.py --repo . --failed-units-file /tmp/fu.txt --unit-show-json /tmp/show.json

#    B. 有 failed unit(期望 rc=1 + stderr 出现 "dry-run: 未真发通知")
printf 'trade-xxx.service loaded failed failed desc\n' > /tmp/fu.txt
$PY scripts/check_failed_units.py --repo . --failed-units-file /tmp/fu.txt --unit-show-json /tmp/show.json

#    C. 非云上(无 systemctl 且无注入样本, 期望 rc=3 + "[skip]")
$PY scripts/check_failed_units.py --repo .

# 5) 云上只读核验(证明 ②b 层当前零假阳性; 不写任何文件)
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'for u in cloud-unit-patrol check-monitor-heartbeat \
  schedule-monitor self-heal r2-consistency check-data-gap overfit-monitor; do \
  p=$(systemctl show -p ExecStart trade-$u.service | sed -n "s/.*argv\[\]=[^ ]* \([^ ]*\.\(sh\|py\)\).*/\1/p"); \
  [ -f "$p" ] && echo "OK   $u -> $p" || echo "MISS $u -> $p"; done'
# 期望: 7/7 OK

# 6) §23.3 覆盖面机检(条件路径 unit 的 timer 必须全在 WATCHMAN_UNITS)
grep -n "ConditionPathExists=" docs/deploy/systemd-units-cloud-snapshot.txt   # 期望 3 行
$PY -m pytest -q scripts/tests/test_196_patrol_visibility_20261005.py::test_conditionpathexists_units_all_watchman_covered
```

**修复链/演进说明**: 本报告为首次落档,无「旧假数」需保留。若后续发现
`WATCHMAN_UNITS` 边界或解析格式需调整,请在本节追加一行「YYYY-MM-DD 修订 + 原因 + 影响的机检」,
不要覆盖上文(可反查)。

---

## 返修记录(FAIL 单点) —— 2026-10-06

**病根(一句话)**: `scripts/tests/test_196_patrol_visibility_20261005.py::test_cfu_noncloud_rc3`
**不带注入样本却硬断言 `rc == 3`**(非云上跳过码);凡环境里存在 `systemctl`(CI ubuntu runner /
任何带 systemd 的机器),`check_failed_units.py` L180-182 的「无 systemctl」守卫不触发 → 走真实
systemd 分支 → `rc != 3` → 该例必败。**CI 侧** `.github/workflows/ci.yml` 闸门⑧ 跑全量 ⇒ 合入
main 必红。

**改动(2 行,照 `test_160_r2_consistency_followup_20261005.py:275-277/283-285` 同款 `shutil_which` 写法)**:
在 `test_cfu_noncloud_rc3` 进入处加环境守卫 —— 本机有 `systemctl` → `pytest.skip`(走真实 systemd
判据,非云上 rc=3 由云上证据覆盖);**无 `systemctl` 环境仍断言 `rc == 3`**,语义不变。新增模块级
helper `def shutil_which(name): from shutil import which; return which(name)`(与 #160 逐字同款)。

**两环境复跑数字(单文件 `import` 命令见文首)**:

| 环境 | 修复前 | 修复后 |
|---|---|---|
| 有 `systemctl`(`PATH="/tmp/fake_systemctl_bin:$PATH"`) | **1 failed, 38 passed** | **0 failed, 38 passed, 1 skipped** |
| 无 `systemctl`(本机 mac 默认 PATH) | 39 passed | **39 passed**(该例正常跑,断言 rc==3) |

> 注: 派单描述里 ①② 两环境的「39 passed / skipped」标注与实际相反(有 systemctl 才 skip);以
> 上表实际数字为准,两环境均 **0 failed**。

**全量回归 `pytest -q scripts/tests/`**:

| 环境 | 修复前(基线) | 修复后 |
|---|---|---|
| 本机 mac 默认 PATH | 231 passed, 1 skipped | **231 passed, 1 skipped**(该例在无 systemctl 下本就 pass,数字持平) |
| 有 `systemctl`(CI 态) | 229 passed, 2 skipped, **1 failed** | **229 passed, 3 skipped, 0 failed**(本修复新增 1 skip,passed 未减少) |

> mac 上那 1 个既有 skip 来自 `test_monitor_resource_inprogress_20261005.py:183`(macOS APFS 口径),与本改动无关。

**零真实外发(§18 L48)**: 本轮仅跑 pytest;`test_notify_r4_dedup_20261001.py` 经 autouse fixture
打桩 `notify.send_tiered`(L81-88),`test_196` 全程 dry-run 注入样本,`check_failed_units.py` 默认 dry
不发通知 —— **本次自测未产生任何真实邮件/飞书/告警**。

**未改动(另立小任务,本任务不动)**: P3-a(`PATROL_DRIFT_ESCALATE_DAYS` 定义未引用)、
P3-b(`_cfu_key` 恢复文案 task 名语义偏差)—— reviewer 已建议另立,遵派单不顺手改。