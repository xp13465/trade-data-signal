# 同族小尾巴三件 (#200 / #199 / #202) 实施报告 — 2026-10-06

- 分支:`feat/silence-family-tails-20261006`(基于 `origin/main` = `43b0bae53`,`base-fresh`,§3)
- 范围:B 级以下、涉生产链的三条小尾巴,同一分支三个修复 commit + 本报告 commit
- 前端版本串:**未动**(无前端源码改动 → 机制 C 不 bump,由主控 merge 统一处理)
- 「真实外发」声明:**本次自测全程零真实外发**(邮件/飞书/告警/R2 写均为打桩或未执行,证据见 §4)

---

## 1. 改动清单(文件:行)

### #200 —— `scripts/update_all.sh` 三条「镜像 rsync 失败仅 echo」静默点 loud 化
病灶:rsync `$REPO/static-site/data/*` → `$GIT_REPO/static-site/data/`(镜像同步,deploy 从 GIT_REPO 读)失败时
仅 `echo "⚠ …rsync 同步失败, 可能发布不全"`,**不进** update_all.sh 既有的 SEVERE/ISSUE 聚合框架 ⇒ 用户看不到告警。

| 行 | 点 | 改动 |
|---|---|---|
| 119-121 | `nav_bucket` rsync(fund_nav 镜像) | `\|\| echo` → `\|\| FUND_NAV_RSYNC_RC=$?` + `[ ${FUND_NAV_RSYNC_RC:-0} -ne 0 ] && echo …` |
| 201-203 | `etf_score_list` rsync | 同上 → `SCORE_LIST_RSYNC_RC` |
| 240-242 | `fund_score` rsync(**#200 主项**) | 同上 → `FUND_SCORE_RSYNC_RC` |
| 313-315 | SEVERE 聚合 | +3 行 `[ ${X_RSYNC_RC:-0} -ne 0 ] && SEVERE=1` |
| 345-347 | ISSUE 文案聚合 | +3 行 `…镜像rsync失败(rc=…,镜像未同步) `(进邮件 subject/正文 + dedup key) |

通道/措辞/退出码语义与同文件「导出失败族」(`FUND_NAV_RC`/`SCORE_LIST_RC`/`FUND_SCORE_RC` → SEVERE/ISSUE)**完全一致**
(「样板抄齐」)。`${X:-0}` 兜底:`REPO==GIT_REPO`(云上单仓)下 rsync no-op → 变量不设 → 判 0 **不误报**。

### #199 —— `scripts/backup_claude_self.sh` 成功文案写死老桶名
病灶:成功日志写死 `signal-backup/claude-backup/…`,备份桶已迁 `signal-backup2`(#178)→ 与实际不符。

| 行 | 改动(纯文案,零逻辑) |
|---|---|
| 8(文件头注释) | `推 R2 signal-backup 私有桶` → `推 R2 私有备份桶`(去掉写死桶名,指向 `upload_r2.py _route_bucket` 单一事实源) |
| 23(注释) | `R2 signal-backup 是私有桶` → `R2 备份桶为私有桶`(同文件同族点,§23.3) |
| 46 | `R2 云端备份成功: signal-backup/claude-backup/claude-self-$TS.tar.gz` → `R2 云端备份成功: claude-backup/claude-self-$TS.tar.gz`(**去掉桶名,只留 key**) |

**取「去掉桶名」而非「改成 signal-backup2」的根因**:改成新名 = 又一次写死,下次切桶再漂移(同一病灶);真实桶名
由**上一行 `upload_r2.py` 自身输出**(`cmd_upload_claude_backup:2576` 打印 `{BACKUP_BUCKET}/{key}`,单一事实源),
不再本地复制。**无任何逻辑变更**(未改 `if`/调用/控制流,注释与 echo 字面量之外零改动)。

### #202 —— #196 遗留 P3 两项
| 项 | 文件:行 | 改动 |
|---|---|---|
| P3-a | `scripts/notify.py:2283-2299` | `_ESCALATE_CHANNELS` 由 3 元组扩 4 元组,每通道带**自己的**升档天数常量(patrol→`PATROL_DRIFT_ESCALATE_DAYS`,failed→`FAILED_UNITS_ESCALATE_DAYS`);调用点改用 `_esc_escalate_days`。此前双通道都硬传 `FAILED_UNITS_ESCALATE_DAYS`,`PATROL_DRIFT_ESCALATE_DAYS` 定义悬空。 |
| P3-b | `scripts/schedule_monitor.sh:1527` | `_cfu_key` 首段(task 名,恢复循环取 `_key.split("|")[0]` 展示)`cloud_unit_patrol` → `check_failed_units`。#196 复审:「实际监控对象 = check_failed_units.py,恢复文案会显示 cloud_unit_patrol」语义偏差。 |

**#202 行为逐位不变**(证据见 §4.2):P3-a 两常量现值同为 3,改后同输入输出逐位一致;P3-b 仅改内部标识串,
触发/去重/恢复判定逻辑一字未动(key 只在 `seen_keys_this_run.add` / `alert_state[key]` / `get(key)` 三处自洽使用)。

---

## 2. 同类错误面清单(§23.2 修 bug 三铁律 + §23.3 举一反三)

### 2.1 #200:`update_all.sh` 内全部「仅 echo、不进聚合」失败点逐个判定
| 行 | 点 | 同病灶? | 判定依据 |
|---|---|---|---|
| 121/203/242 | **镜像 rsync ×3** | ✅ **是 → 已统一修** | 同一机制(REPO→GIT_REPO 镜像同步)+ 同一后果(发布不全)+ 同一写法(`\|\| echo`) |
| 134 | fund-nav 异步上传触发失败(systemd-run) | ❌ 否 | 非镜像 rsync;真实上传失败由 `fund_nav_upload_async.sh` 内部 notify(L123 注释)已 loud |
| 164 | check_signals 退出码非 0 | ❌ 否 | 非镜像;非阻塞邮件链路,check_signals.sh 自带通道 |
| 171 | intraday_snapshot 采集失败 | ❌ 否 | 非镜像;其**后果**(快照陈旧)已由 FRESH_OK 断言(L299→SEVERE)覆盖 |
| 177/183 | export_alert / export_alert_analyze 失败 | ❌ 否 | 非镜像;二级预警 JSON,不阻塞主流程 |
| 205 | **upload-etf-score R2 上传失败** | ⚠️ 同症状族、**异机制** | R2 上传侧(非 rsync);#193 仅给 offshore-fund/fund-score 加了 `upload_r2.py` 内部 notify(`_notify_channel_upload_fail` 只 2 处调用),etf-score 此点仍仅 echo。**属 #193 R2 channel 家族,不在 #200 rsync 范围 —— 见 §5 上报,未改** |
| 217 | export_notifications 失败 | ❌ 否 | 非镜像;二级通知源 |
| 224 | stage0-daily 失败 | ❌ 否 | 非镜像;采集器 |
| 231 | compute_all_scores 失败 | ❌ 否 | 非镜像;其产物导出 rc 已被 FUND_SCORE_RC 覆盖 |
| 244 | upload-fund-score R2 上传失败 | ❌ 否(已 loud) | #193 已给 `upload_r2.py cmd_upload_fund_score` 内部 notify;此 echo 为冗余 |
| 368 | daily_summary_email 失败 | ❌ 否(已 loud) | 紧接一行 `notify.py "[告警] 情绪速递邮件失败"` |
| 388/391 | gen_schedule_stats / push_schedule_stats 失败 | ❌ 否 | 非镜像;stats 刷新另有监控 |

**结论**:同机制/同根因 = 三条镜像 rsync,已根因统一修(非逐点补丁);其余经判定为异机制/已被别的通道覆盖。

### 2.2 #199:全仓 scripts/ 「老桶名 `signal-backup`」残留面逐个判定
| 文件 | 出现 | 判定 |
|---|---|---|
| `backup_claude_self.sh`(本任务) | 3 处写死/注释 | ✅ 已修(去桶名) |
| `verify_backup.sh:6/68/76/88` | 日志/正文写 `R2 signal-backup 桶`(实际写 `signal-backup2`) | ⚠️ **同病灶(文案漂移),未改** —— 见 §5 |
| `restore-r2-backup.sh:2/8/33`、`restore-large-json.sh:2/5/12/44`、`staticdata_backup_async.sh:30` | 文档/日志写 `signal-backup` | ⚠️ 疑似同病灶,需逐处判(部分是 legacy 恢复归档语义)—— 见 §5 |
| `upload_r2.py`(多处)、`check_r2_channel_coverage.py:32` | 迁移说明 + 新名 `signal-backup2` 并存 | ❌ 否 | 描述老/新桶迁移关系,语义正确,非漂移 |

**结论**:#199 只改本文件(任务范围);跨文件同类「老桶名文案漂移」已列清单上报(§5),不擅自扩大范围。

### 2.3 #202:同组件/同模式
`PATROL_DRIFT_ESCALATE_DAYS` 全仓唯一出现即定义行(改前);`_cfu_key` 全仓唯一出现即定义行。无其他消费点。

---

## 3. 与 #195 / 同模块待办的冲突检查(§23.4)
- `docs/pending-features-index.md` 本模块项:#193(已合,`c0e87ce92`)、#196(已合,`351f63817`)、#201(§22 机检挂链,**待拍板**)、**#195(57 个 shell mac 硬编码扫描,未实施)**。
- **#195 重叠标注**:#195 会横扫含 `update_all.sh` 的 57 个 shell。#200 只改 `update_all.sh` 的 rsync-失败告警聚合(与 `cd`/路径硬编码无交集);#199 只改 `backup_claude_self.sh` 文案。二者与 #195 的扫描维度(mac 硬编码路径)不重叠,但 #195 实施时需以本分支合并后版本为基(避免行号/上下文漂移)。
- **#193/#201 边界**:#200 的 R2 上传侧同类点(upload-etf-score,§2.1)刻意留归 #193/#201 家族,未越界修改。

---

## 4. 逐项自测结果(全部隔离;含打桩生效证据)

### 4.1 #200 —— `update_all.sh` 隔离自测(**未端到端跑 update_all.sh**)
方法:用 `sed` 从**真实文件**抽取改动行(source 的就是真码,非复刻)到 harness `source` 执行;notify 调用行以
假 `$PY` stub 替换(只记录 argv,不碰 `notify.py`/网络)。

复跑命令:
```
bash /tmp/t200_harness.sh        # after 固定片段(harness 注释含抽取行号)
bash /tmp/t200_before.sh         # before 固定片段(来自 git show HEAD:scripts/update_all.sh)
```
结果:
| 场景 | 3 条 rsync | RC | SEVERE | ISSUE |
|---|---|---|---|---|
| all_fail(源缺失) | 全失败 rc=23 | nav/score_list/fund_score=23 | **1** | `base:nav_bucket镜像rsync失败(rc=23,镜像未同步) etf_score_list… fund_score…` |
| all_ok(源在位) | 全成功 | `<unset>` | **0** | 不变(`base:`) |
| single_repo(REPO==GIT_REPO) | no-op 跳过 | `<unset>` | **0** | 不变 ⇒ 云上单仓**不误报** |

- **改前对照(证明病灶真实)**:`t200_before.sh` — 三条 rsync 全失败时 `SEVERE=0` 且 `ISSUE` 无 rsync 条目 ⇒ **静默**;改后 `SEVERE=1` 且 3 条进 ISSUE。
- **打桩生效 / 零外发证据**:harness 里真·notify 调用行(354)的 `$PY` = stub,执行后 `notify_calls.log` 出现
  `STUB_PY_INVOKED …/repo_all_fail/scripts/notify.py [告警] update_all base:… fund_score镜像rsync失败(rc=23,…) …`
  ⇒ 聚合结果确已喂给 notify 通道,且**被 stub 拦截**;`pgrep -f scripts/notify.py` = 无 ⇒ **本次自测未产生真实外发**。
- 语法:`bash -n scripts/update_all.sh` → OK。

### 4.2 #202 —— 同输入输出逐位一致证明
复跑命令:
```
/Users/linhuichen/code/trade/.venv/bin/python /tmp/t202_harness.py
/Users/linhuichen/code/trade/.venv/bin/python -m pytest -q scripts/tests/test_196_patrol_visibility_20261005.py
```
- **P3-a 结构 + 等价**:harness 用 `ast` 抽取 `notify.py` 的**真实** `_ESCALATE_CHANNELS` 字面量 exec(用真 `adr`),
  断言 4 元组、`patrol[3] is PATROL_DRIFT_ESCALATE_DAYS`、`failed[3] is FAILED_UNITS_ESCALATE_DAYS`。
  改前(两通道都传 `FAILED_UNITS_ESCALATE_DAYS`)vs 改后(各传各的)对 2 通道 × 5 连续天数 × 3 间隔 = **30 组同输入,
  tier/consecutive_days/first_fail_date 逐位一致,mismatch=0**。
- **#196 全套回归(打桩发送层,零真外发)**:`39 passed` —— 其中 ④ `test_notify_escalation_patrol_drift_third_day` /
  `test_notify_escalation_failed_units_third_day` 直接跑**真实 `notify.main()`**(monkeypatch `send_tiered/send/check_dedup/
  update_dedup/write_alert`)→ 两通道均仍在「连续 3 天」升 critical ⇒ 证明 P3-a 改后**行为逐位不变**且 4 元组接线正确。
- **P3-b**:`_cfu_key` 首段 `cloud_unit_patrol`→`check_failed_units`;改后恢复文案 task = `check_failed_units`(改前 `cloud_unit_patrol`)。
  改动的仅是**内部标识串**;`seen_keys_this_run.add(key)`/`alert_state[key]`/`get(key)` 三处同一标识、自洽,触发/去重/恢复判定未动。
- 语法:`bash -n scripts/schedule_monitor.sh` OK;`ast.parse(notify.py)` OK。

### 4.3 #199 —— 纯文案
- **未执行 `backup_claude_self.sh`**(执行会真写 R2 ⇒ 明确禁止)⇒ 零外发风险。
- 语法 `bash -n scripts/backup_claude_self.sh` OK。
- 改动校验:`grep -n signal-backup scripts/backup_claude_self.sh` → 仅剩注释里的历史说明(已改),成功行只剩 key(见 §1)。
- 交叉核对(真实桶名不丢失):`upload_r2.py:2576` 打印 `✓ <file> (NKB) -> {BACKUP_BUCKET}/claude-backup/…`(紧邻**上一行**),
  `BACKUP_BUCKET = R2_BACKUP_BUCKET | R2_BACKUP2_BUCKET(默认 signal-backup2)`(`upload_r2.py:286/299`)⇒ 日志仍含真实桶名。

---

## 5. 未覆盖项 / 上报(§23.4 暴露边界,不擅自扩大范围)
1. **R2 上传侧同类点(异机制)**:`update_all.sh:205` `upload-etf-score` 失败仍仅 echo;`upload_r2.py cmd_upload_etf_score`
   未接 `_notify_channel_upload_fail`(#193 只接了 offshore-fund/fund-score)。建议登记为 **#193 R2 channel 家族**后续项
   (或并入 #201 通道机检决策)。**本次未改**(越界 + 避免与 #193/#201 冲突)。
2. **跨文件「老桶名文案漂移」**:`verify_backup.sh` / `restore-r2-backup.sh` / `restore-large-json.sh` /
   `staticdata_backup_async.sh` 的日志/文档仍写 `signal-backup`(见 §2.2)。建议单列小任务逐处判定(部分是 legacy 恢复语义)。
3. **P3-b 生产状态迁移**:若云上 `alert_state.json` 存在旧 key `cloud_unit_patrol|self|dead`(仅当 `check_failed_units.py`
   自身曾异常才会写入,10-05 新脚本,概率极低),改名后该旧 key 会被恢复循环按原逻辑回收(发一条 task=`cloud_unit_patrol`
   的恢复)—— 此为**原逻辑本就会发生**的行为,非改名引入;改名**不新增**任何外发。

---

## 6. 复现段(可复跑)
```bash
# 1) #200 隔离自测(真码片段 source;notify 打桩 ⇒ 零外发)
bash /tmp/t200_harness.sh          # after: all_fail→SEVERE=1/ISSUE 3 条; all_ok,single_repo→SEVERE=0
bash /tmp/t200_before.sh           # before: 全失败仍 SEVERE=0(证明静默病灶)
# 2) #202 逐位一致 + 回归(stub 发送层)
/Users/linhuichen/code/trade/.venv/bin/python /tmp/t202_harness.py
/Users/linhuichen/code/trade/.venv/bin/python -m pytest -q scripts/tests/test_196_patrol_visibility_20261005.py
# 3) 语法
bash -n scripts/update_all.sh && bash -n scripts/backup_claude_self.sh && bash -n scripts/schedule_monitor.sh
/Users/linhuichen/code/trade/.venv/bin/python -c "import ast; ast.parse(open('scripts/notify.py').read()); print('ok')"
# 4) #199 文案核对(不执行脚本, 零 R2 写)
grep -n 'R2 云端备份成功' scripts/backup_claude_self.sh
```
> 注:`/tmp/t200_harness.sh`、`/tmp/t202_harness.py` 为一次性自测 harness(含抽取行号),不入库;复现段命令可直接重建(见 §4 描述)。

## 7. 关联规范
§8(只推 feat)/§14(时点)/§18 L48(bug 脚本自测先打桩)/§22(数据一致性)/§23.2(修 bug 三铁律)/§23.3(举一反三)/
§23.4(团队协作·同模块冲突)/§23.5(报告四件套)/§24(未动前端源码,不涉版本串)。