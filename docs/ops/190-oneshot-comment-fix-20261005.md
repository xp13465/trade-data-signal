# #190 `schedule_monitor.sh` `launchctl_loaded()` 注释陷阱订正(oneshot activating)

- **任务**:#190（`docs/pending-features-index.md:310`）—— 注释陷阱:`launchctl_loaded()` 注释「0=active(在跑)」对 `Type=oneshot` 不成立
- **来源**:#160 P0（`systemctl is-active --quiet` 对 oneshot 运行中 rc=3 ⇒ 判据变死代码）的**同模式扫描**发现（§23.2/§23.3）
- **分支**:`feat/190-oneshot-comment-fix-20261005`（从 `origin/main` 起）
- **改动文件**:`scripts/schedule_monitor.sh`（**仅注释，零代码/零行为变更**）
- **改动分级**:A 级（纯注释，无逻辑变更，用户已拍板「改」）
- **配套 commit**:见文末 §9

---

## 0. 结论速览

| 项 | 结论 |
|---|---|
| 该函数是否 macOS 遗留死代码? | **否** —— 云上 `trade-schedule-monitor.service` 每 15min 跑 `schedule_monitor.sh`，Linux 分支（`shutil.which("systemctl")`）是真生产路径（见 §1） |
| 该函数的**实际语义**是什么? | 「unit **是否已加载**」（loaded/failed/not_loaded），**不是「是否在跑」** —— `activating`（oneshot 运行中）刻意归 `loaded`，语义正确（见 §1/§2） |
| 代码判据有缺陷吗? | **无** —— 它用 `is-active` 的 **stdout 文本 + rc∈(0,3)**，能吃到 `activating`/`failed` 文本，不存在 #160 那种「判据恒不成立」的死代码 |
| 那陷阱在哪? | **在注释** —— 旧注释「`0=active(在跑)`」把 rc=0 绑定「在跑」，对 oneshot 错（运行中 rc=3）；后人照注释写「`rc==0` 在跑」必造死判据 |
| 本次修法 | **纯注释订正**（`docstring` + 行内注释），写明 oneshot activating 陷阱 + 指向正例；**不改判据**（§23.7 冻结契约） |
| 全仓同型缺陷还有吗? | 代码层**无第二处**；正例 2 处（`self_heal.sh` / `check_r2_consistency.sh`）判据+注释均对（完整清单见 §3） |

---

## 1. 事实核查（①调用链证据：谁调它 / 本机与云上是否真跑）

### 1.1 代码级证据（仓内）

- **定义**:`scripts/schedule_monitor.sh:1107 def launchctl_loaded(label)`（本次修复后 docstring 起于 1108，行内注释在 1136）。
- **调用点**:同文件 `:1160 for _label in LAUNCHCTL_LABELS:` → `:1161 _lstate = launchctl_loaded(_label)`；`LAUNCHCTL_LABELS`（`:1079`）列 11 个 unit（`com.trade.update-all` / `backfill-evening` / `intraday-snapshot` / `futures-backfill` / `lhb-backfill` / `rzhb-backfill` / `us-stock-morning` / `etf-national-team` / `lab-auto` / `turnover-backfill` / `self-heal`）。**每次 monitor 运行都会无条件遍历调用它**。
- **平台分支**:`if shutil.which("systemctl"):`（`:1118`）→ 云上（Linux）走 systemd 分支；本机（macOS 无 systemctl）走 `launchctl print` 分支。**macOS 分支才是那半条 legacy 腿**，systemd 分支是活的。

### 1.2 云上实跑证据（只读 ssh，2026-10-05）

```
$ ssh … 'systemctl is-active trade-schedule-monitor.service; systemctl list-timers trade-schedule-monitor.timer --all'
inactive
NEXT                         LEFT       LAST                        PASSED    UNIT
Mon 2026-10-05 17:15:00 CST  5min left  Mon 2026-10-05 17:00:01 CST 9min ago  trade-schedule-monitor.timer  trade-schedule-monitor.service
```

⇒ 云上 `trade-schedule-monitor.timer` **每 15min 触发**，`ExecStart=/bin/bash /home/ubuntu/code/trade-data/scripts/schedule_monitor.sh`（见 `docs/deploy/systemd-units-20260912.md:1460`）。服务当前 `inactive` = 两次运行之间（oneshot 正常态）。**结论:该函数在生产被真跑，非死代码。**

### 1.3 云上现存副本 = 旧误导注释（陷阱是"活的"）

```
$ ssh … 'grep -n "is-active 退出码\|0=active" /home/ubuntu/code/trade-data/scripts/schedule_monitor.sh'
1129:        # is-active 退出码: 0=active(在跑), 3=inactive(unit 已注册未跑), 4=unit 不存在;
```

⇒ 云上（=当前 main 版本）L1129 正是被点名的旧注释。本 feat 是**首次订正**，随 merge+云上 pull 生效。

### 1.4 该函数实际语义（读代码得出，非按注释字面理解）

```python
st = (r.stdout or "").strip()
if st == "failed":                       # 已加载但运行失败
    return "failed"
return "loaded" if r.returncode in (0, 3) else "not_loaded"
```

- `active`(rc=0) / `inactive`(rc=3) / **`activating`(rc=3,oneshot 运行中)** → 均 `loaded`
- `failed`(rc=3,stdout='failed') → `failed`
- unit 不存在(rc=4) → `not_loaded`

⇒ 语义 = **「是否已加载」**，`activating` 归 `loaded` 是**刻意的原点设计且正确**（unit 已注册且在跑）；**不是** #160 那种「判在跑恒不成立」的死代码。**故只修注释，不修判据。**

---

## 2. 修复内容（②注释与代码行为逐条一致对照）

### 2.1 改前 / 改后对照（注释文本）

**改前**（`scripts/schedule_monitor.sh` 原 L1129-1131）——**错**：

```
        # is-active 退出码: 0=active(在跑), 3=inactive(unit 已注册未跑), 4=unit 不存在;
        # failed 也是 3 但 stdout='failed'。active/inactive 算 loaded, failed 算 failed(已加载但运行失败),
        # 只有 unit 不存在(exit 4)才算 not_loaded。
```

**改后**（docstring 追加陷阱提示 + 行内注释重写）——**对**：

- docstring（`:1118`）追加：本函数判「是否已加载」非「是否在跑」；云上 trade-*.service 多为 `Type=oneshot(RemainAfterExit=no)`，运行中 `ActiveState=activating` 且 `is-active` rc=3（与 inactive 同码）；判「在跑」照 `self_heal.sh:111` / `check_r2_consistency.sh:91`。
- 行内注释（`:1136`）重写：显式标「旧的『0=active(在跑)』注释是错的，勿照抄」，逐条给出 rc 映射，并标注「切勿改成 `is-active --quiet`（丢 stdout 会把 failed 吞成 loaded）」。

### 2.2 注释 ↔ 代码行为逐条一致核对

| 注释新claim | 代码事实 | 一致? |
|---|---|---|
| 「rc=0(active) = 已加载」 | `returncode in (0,3)` → loaded | ✅ |
| 「rc=3(inactive 或 activating 或 stdout='failed') = 已加载/failed」 | inactive/activating→loaded；failed→"failed" | ✅ |
| 「仅 rc=4(unit 不存在) = not_loaded」 | `else` 分支 → not_loaded | ✅ |
| 「activating 归 loaded 是刻意的（语义=已加载）」 | 代码无 `st=="activating"` 特判，走 `rc∈(0,3)`→loaded | ✅ |
| 「切勿改成 `--quiet`（会把 failed 吞成 loaded）」 | `--quiet` 无 stdout ⇒ `st==""` ⇒ 跳过 `failed` 判定，failed(rc=3)→loaded | ✅（推论已验证，见 §4.2） |
| 「判在跑照 self_heal.sh:111 / check_r2_consistency.sh:91」 | 两处确为正例（§3 行 2/3） | ✅ |

### 2.3 零行为变更证明

`git diff --stat` = `scripts/schedule_monitor.sh | 15 +++++, 3 ---`，逐行看：**15 新增行全是注释（`#`/docstring 内），3 删除行全是旧注释**，无可执行语句变动（`git diff` 全文见 §9 复现段命令）。

---

## 3. 举一反三（③全仓 `is-active`/`ActiveState` 清单 + 逐条判定）

> grep 范围：全仓 `--include='*.sh|.py|.service|.timer|*.md'`，排除 `.git/` 与 `docs/archive/`。判定维度：**判据对不对 / 注释对不对**。

### 3.1 代码层判据（真的在"用 is-active/ActiveState 判在跑/已加载"）

| # | 位置 | 判据写法 | 语义 | 判据对不对 | 注释对不对 | 处理 |
|---|---|---|---|---|---|---|
| 1 | `scripts/schedule_monitor.sh:1107 launchctl_loaded()` | `is-active`（**非** `--quiet`，读 stdout）+ rc∈(0,3) | 「**已加载**」 | **对**（activating→loaded 是原点设计） | **错**（旧注释「0=active(在跑)」对 oneshot 不成立） | **本次修注释** ✅ |
| 2 | `scripts/self_heal.sh:92/103/111 launchctl_state()` | 读 `is-active` stdout 文本，`return "running" if st in ("active","activating")` | 「**在跑**」 | **对**（显式把 activating 当 running） | **对**（`:111` 注释写明 oneshot 陷阱） | 无需改（**正例**） |
| 3 | `scripts/check_r2_consistency.sh:81-92 update_all_running()` | `systemctl show -p ActiveState --value` ∈ {active, activating} | 「**在跑**」 | **对**（#160 P0 修复后的写法） | **对**（`:82-89` 注释详述 `is-active --quiet` 为何错、`§9.9` 佐证） | 无需改（**正例**） |
| 4 | `scripts/gen_schedule_stats.py:360 _systemd_last_exit()` | `systemctl show -p LoadState -p ExecMainCode -p ExecMainStatus` | 「读**真实退出码**」 | **对**（用 `LoadState`≠`ActiveState`，与 activating 无关；`LoadState!="loaded"`→None 不猜 143） | **对** | 无需改 |

**代码层同型缺陷 = 0 处**（除本次修的 #1 注释外，判据均正确）。

### 3.2 代码层非判据引用（仅文案/日志/标题，不构成判据）

| # | 位置 | 内容 | 判定 |
|---|---|---|---|
| 5 | `scripts/schedule_monitor.sh:1155 not_loaded_help()` | 告警文案 `systemctl is-active {unit} 未加载` | 仅恢复建议文案，非判据，无需改 |
| 6 | `scripts/schedule_monitor.sh:1172/1185/1199` | print 文案 `systemd is-active=failed(...)` | 仅日志，无需改 |
| 7 | `scripts/tests/test_160_r2_consistency_followup_20261005.py` | #160 专项测试（含旧判据 `is-active --quiet` rc=3 的**改前对照**） | 测试，正确，无需改 |

### 3.3 文档层引用（含注释/文档）

| # | 位置 | 内容 | 判定 |
|---|---|---|---|
| 8 | `docs/ops/160-r2-consistency-gate-wiring-20261005.md`（§9.1/§9.6/§9.9 等） | 已注明「`is-active --quiet` 对 oneshot 错」并改 `ActiveState` | **正确**，无需改（本次的权威先例） |
| 9 | `docs/deploy/alert-fix-20260918.md:10/26` | 事故描述：「`is-active` 输出 failed → 判未加载」「inactive(rc=3)→ `launchctl_loaded` 判定已加载」 | 与代码行为一致，无需改 |
| 10 | `docs/deploy/migration-inventory-20260912.md:192`、`docs/deploy/systemd-units-20260912.md:1396` | 历史迁移计划「改 `systemctl is-active/is-failed`」 | 历史计划条目（已执行完），非判据模板；照抄者若读 stdout 文本仍正确。留档，无需改 |
| 11 | `docs/ops/alertchain-hardening-timer-mount-*.md:136/145/36/107`、`docs/ops/cloud-healthcheck-20261003/D1:103`/`D3:59/179/193/227`/`D7:155` | 云体检/复核的**验证命令与证据**（如 `is-active fail2ban=inactive`） | 一次性证据引用，非可复用判据，无需改 |
| 12 | `docs/pending-features-index.md:307`（#187 行**描述列**） | 含 #187 原始推荐「preflight `systemctl is-active` 则跳过写 rc=0」 | 描述列=历史问题陈述；**状态列已闭环**（「①的判据已修」+ `§9.9` 记录改 `ActiveState`）。**不改**（任务状态单一事实源=状态列，§23.12-1；主控已在 `docs/index-189-190-closeout-20261005` 分支收尾索引） |
| 13 | `TASKS.md:17/18/19/25/307` 等 | 会话交接状态日志里的 is-active 叙述 | 历史交接记录，非判据，无需改 |

### 3.4 §23.3 清单小结

- **同模式（判"在跑/已加载"）消费点**：4 处代码判据（#1 本次修 / #2#3#4 正例全覆盖）。
- **同数据源**：`systemctl` 判据在仓内**仅** self_heal / schedule_monitor / check_r2_consistency / gen_schedule_stats 四脚本使用（grep 实证），已全列。
- **同组件/相关展示位**：`not_loaded_help` 文案、3 处 print 文案（#5#6）已覆盖。
- **文档面**：#8-#13 全列全判。
- **清单缺项 = 0**。

---

## 4. 行为不变验证（④改前/改后行为对照实测）

### 4.1 函数级六态映射实测（ast 提取**真函数** + 注入假 systemctl）

> 方法：`ast` 从 `scripts/schedule_monitor.sh` 提取 `launchctl_loaded` 函数体真身，`shutil.which` 强返 systemctl（走 Linux 分支），`subprocess.run` 注入真实 systemd v249 的 `is-active` 五态取值。

```
  active        (Type=simple 在跑)    rc=0 stdout='active'       -> loaded      (want loaded)  OK
  inactive      (注册未跑)            rc=3 stdout='inactive'     -> loaded      (want loaded)  OK
  activating    (oneshot 运行中!)      rc=3 stdout='activating'   -> loaded      (want loaded)  OK
  failed        (已加载运行失败)       rc=3 stdout='failed'       -> failed      (want failed)  OK
  unknown       (unit 不存在)         rc=4 stdout='unknown'      -> not_loaded  (want not_loaded)  OK
  deactivating  (正在停)              rc=3 stdout='deactivating' -> loaded      (want loaded)  OK
ALL PASS
```

**关键**：`activating` → `loaded`（=「已加载」，正确）。**本次是注释-only 改动 ⇒ 改后行为与改前逐位相同**（diff 全文验证，§9）。

### 4.2 云上活体探测（验证注释所写事实"activating → is-active rc=3"）

```
$ ssh … 'sudo systemd-run --no-block --unit=probe190 --property=Type=oneshot /bin/sleep 8; ... 采 3 次; reset-failed'
ActiveState=activating is-active_rc=3 is-active_out=activating
ActiveState=activating is-active_rc=3 is-active_out=activating
ActiveState=activating is-active_rc=3 is-active_out=activating
done
```

⇒ 直证：oneshot 运行中 `ActiveState=activating`、`is-active --quiet` **rc=3**、`is-active` stdout=`activating`。**新注释所述事实成立**。探测单元 `probe190` 已 `reset-failed` 清理，未触碰生产单元。

---

## 5. 自验（⑤语法检查 + 测试）

| 检查 | 命令 | 结果 |
|---|---|---|
| bash 语法 | `bash -n scripts/schedule_monitor.sh` | OK |
| 内嵌 Python 语法 | `sed -n '60,2598p' … \| python3 -c "import ast; ast.parse(…)"` | `PY ast.parse OK` |
| 全量测试 | `.venv/bin/python -m pytest scripts/tests -q` | **192 passed, 1 skipped**（与 #160 基线一致，无回归） |
| 函数六态行为 | 见 §4.1 | ALL PASS |
| 云上活体 | 见 §4.2 | 与注释所述一致 |

---

## 6. §23.2 修 bug 三铁律 / §23.4 团队协作 自检

- **同类错误面清单**（§23.2 ③）：全仓 `is-active`/`ActiveState` 判据 4 处（§3.1），本次修 1 处（注释），另 3 处判据+注释均正确，**同型缺陷 0 处**。
- **根因**：非「某一处判据写错」，而是「**注释把 rc=0 绑定『在跑』**」这一表述在 oneshot 语义下失真的**扩散源**；根治 = 注释与代码行为对齐 + 写明陷阱（本次），而非逐文件打补丁。
- **§23.4 同模块占用**：scan `docs/pending-features-index.md` 含 `schedule_monitor` 的项（#162 s06 状态 hold / #164 资源维度盲区 / #190 本项）——**均不涉 `launchctl_loaded()` 函数**，无同模块后覆盖前风险。主控已在 `docs/index-189-190-closeout-20261005` 分支做索引收尾（故本次**不碰** pending index）。
- **§23.7 冻结契约**：本次**只改注释**，不动任何判据/逻辑/口径；未顺手优化他处。

---

## 7. 遗留 / 建议（上报主控）

1. **#190 状态列**：现为「**待拍板**」。本次已按用户拍板「改」实施于 feat 分支，**建议主控 merge 后**将状态列更新为「已合 main（merge `<hash>`；纯注释零行为变更）」——本次**不擅改** index（任务状态单一事实源·状态列由主控收尾，§23.12-1）。
2. **#187 行描述列的过时推荐**（§3.3 #12）：`docs/pending-features-index.md:307` 描述列仍含「preflight `systemctl is-active` 则跳过写 rc=0」的原始推荐（已被 `§9.9` 证伪，改 `ActiveState`）。因其**状态列已闭环**且属历史问题陈述，本次不改；如主控认为描述列也需加指向 `§9.9` 的订正，可一并处理（低风险）。
3. `launchctl_loaded` **macOS 分支**（`launchctl print`）本机已无 launchd 生产任务、无 systemctl ⇒ 本机走该分支仅作探测（`not_loaded`），属已知现状，非缺陷，未动。

---

## 8. §23.5 四件套

| 件 | 内容 |
|---|---|
| 报告本体 | 本文件 `docs/ops/190-oneshot-comment-fix-20261005.md` ✅ |
| 生成脚本 | **无**（本次为手工注释订正，无数据产物/无生成脚本，故无配套脚本） |
| ## 复现段 | 见 §9 |
| 配套 commit | 见 §9 |

---

## 9. 复现段（可复现命令）

```bash
# 分支 / base
git branch --show-current                 # feat/190-oneshot-comment-fix-20261005
git merge-base HEAD origin/main           # base（应 == 开工时 origin/main）

# 改动全文（纯注释：15 增 3 删，无代码行）
git show --stat HEAD -- scripts/schedule_monitor.sh
git show HEAD -- scripts/schedule_monitor.sh

# 语法
bash -n scripts/schedule_monitor.sh
sed -n '60,2598p' scripts/schedule_monitor.sh > /tmp/sm190_extract.py
python3 -c "import ast; ast.parse(open('/tmp/sm190_extract.py').read()); print('PY ast.parse OK')"

# 测试（用 trade-data venv 的 pytest）
/Users/linhuichen/code/trade-data/.venv/bin/python -m pytest scripts/tests -q   # 192 passed, 1 skipped

# 云上活体（只读 + 瞬态单元，可复现 §4.2）
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 \
  'sudo systemd-run --no-block --unit=probe190 --property=Type=oneshot /bin/sleep 8; sleep 1; \
   for i in 1 2 3; do echo "ActiveState=$(systemctl show -p ActiveState --value probe190.service) \
   is-active_rc=$(systemctl is-active --quiet probe190.service; echo $?)"; sleep 2; done; \
   sudo systemctl reset-failed probe190.service'
```

**配套 commit**:`f868d06f1`（`fix(190): 订正 schedule_monitor.launchctl_loaded() 注释陷阱(oneshot activating)`；`Co-Authored-By: Claude Code <noreply@anthropic.com>`）。分支 `feat/190-oneshot-comment-fix-20261005`，base == 开工时 `origin/main`。