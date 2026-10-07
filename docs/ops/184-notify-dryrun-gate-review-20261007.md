# #184 独立审报告 — notify `--dry-run` 门控(write_alert 单点守卫)

- 被审分支:`feat/184-notify-dryrun-gate-20261007`,tip `8997c6300`(单 commit),merge-base `92fa551ad`
- 实施报告:`docs/ops/184-notify-dryrun-gate-impl-20261007.md`(分支内)
- 审查日期:2026-10-07 | 审查方式:**纯只读** + `/tmp` 沙箱 A/B(未 checkout 分支到主树、未跑任何真发、未改任何文件)
- 残留后台任务:无(本次未出现 `moved to the background`)

## 0. 总结论

| # | 必审项 | 判定 |
|---|---|---|
| 1 | §23.2 修完整(write_alert 调用点穷举 + 绕过路径) | **PASS**(报告 1 处措辞不实,见 D1,影响为 0) |
| 2 | §23.3 同类 6 行「已 gate」判定复核 | **PASS**(逐条独立核实,无「其实没 gate」被误判) |
| 3 | 既有测试改断言(是否真复现 / 是否掏空 / §23.7) | **PASS**(真复现 + 改法正当 + 断言更强;§23.7 见该节) |
| 4 | 零外发哨兵是否真能拦 | **PASS**(两处出网入口实测拦截;1 处措辞打折见 D3) |
| 5 | latest.md 逐位一致证据可信度 | **PASS**(md5 可复算;更强佐证=mtime 早于今日 + tmp 隔离 + 目录级零创建) |
| 6 | out-of-scope 上报(--tier info 写 info_log) | **结论成立**(实测复现;影响面描述需订正,见 D2) |
| 7 | 回归面(非 dry-run 逐位不变) | **PASS**(静态 body diff + 动态 A/B 双证) |
| 8 | git 纪律 | **PASS**(1 项提示:origin/main 已前移且零相交,非 FAIL) |

**0 P0 / 0 P1;披露项 6 个(全部 <80 分,非阻断)。建议:可 merge**(主控 merge 前请自核 §23.7 用户拍板记录,见 §5-1)。

## 1. 逐项证据

### ① §23.2 修完整 — PASS
- 独立穷举调用点(不 grep 字面量、核 def 与全部引用):分支版 `grep -n "write_alert" scripts/notify.py` = 5 个 CLI 调用点(**2194 / 2252 / 2288 / 2339 / 2366**)+ 1 个 def,与实施者「仅 5 处」**一致**;main 版同文件亦 5 处(2181/2238/2273/2323/2349)⇒ **pending-index 里写的「3 处」是旧快照,实施者找到 5 处是对的**(比登记描述更全)。
- 5 处逐字核 diff:全部 `dry_run=args.dry_run`(5 个 hunk 无遗漏)。
- 「绕过 write_alert 直写 latest.md」独立找:`latest.md` 的全部写者 = `write_alert` + `_mirror_severe`,两者同经 `_update_latest`(flock 内读改写);`_replace_latest` 只被 `_update_latest` 调用(def 1170 / call 1192);全仓 `*.py/*.sh` grep `alerts/latest\|ALERTS_FILE` 只剩**注释**与 notify.py 本体 ⇒ **无第三条写路径**。`_mirror_severe` 由 `send()` 的 `if severe and not dry_run`(L998,分支与 main 逐字相同)挡住。
- ⚠️ 报告 §2「write_alert 在 notify.py 之外**无**调用方」**不实**:至少 3 处外部调用(`scripts/check_ds_resilience.py:259/266`、`scripts/tests/test_alertchain_hardening_20261003.py:71/86/97`、`test_196_patrol_visibility_20261005.py:501` 的 monkeypatch)。**影响=0**(前者 ALERTS_FILE 已 monkeypatch 到 tmp、后两者是测试面),但它是「5 处=全量 + 机检兜底未来调用点」这句话的论据基础 ⇒ 见 D1。

### ② §23.3 同类「已 gate」逐条独立复核 — PASS

| 行 | 独立核实结论 | 证据 |
|---|---|---|
| `_mirror_severe` | 真已 gate | `send()` L998 `if severe and not dry_run`(分支/main 同) |
| `defer_warning` | 真已 gate | L1726 `if dry_run: print; return "dry_run"`,在最前;三处 buffer 追加(1746/1797/1813)全在其后 |
| `_flush_warning_batch_locked` 收尾 | 真已 gate | L1972 `if sent and not dry_run:` 包住 `_save_warning_dedup_state` + buffer 原地重写(2001-2027) |
| `check_dedup`/`update_dedup` | 真已 gate | 7 处 `update_dedup` 全部落在 `not (args.)dry_run` 条件内(2193/2253/2288+2289/2339+2340/2366/749/1371);`check_dedup` 是只读 |
| `_alert_feishu_config_missing` | 真已 gate | L724 `if not dry_run and check_dedup(...)`;L749 `if ok and not dry_run: update_dedup(...)` |
| `notify_agent_done` dedup | 真已 gate | L1347 检查侧 + L1371 更新侧均带 `not dry_run`;函数内无其他写 |
| `log_info`(info 档) | **确实未 gate**(不在「无需改」行,单列 §4 上报) | L1424 `_append_jsonl(INFO_LOG_FILE, rec)` 无条件 + L1429 截断重写 ⇒ 见 ⑥ |
- 另独立扫出**第 7 条**同类事实(不属数据写入):`flush_warning_batch` 在 dry-run 下仍会 `mkdir data/alerts` + `open(warning_buffer.flushlock,"a+")`(实测:干净沙箱跑 `--flush-warnings --dry-run` 后只剩一个 0 字节 `warning_buffer.flushlock`)⇒ pre-existing、非本次 diff 引入,见 D4。

### ③ 既有已上线测试被改(`test_alertchain_hardening_20261003.py`) — PASS

**(a) 改前断言是真复现** —— `/tmp` 沙箱 A/B(用 **main 版** notify.py + main 版 wrapper + `REPO=tmp` + `--dry-run`,即该用例的真实构造):

```
OLD(main):  wrapper --dry-run → 生成 data/alerts/latest.md(739 B)+ .latest.lock   ← 病灶复现
NEW(分支):  同流程 → 连 data/alerts 目录都不创建;日志含「write_alert 跳过写」
```
⇒ 改前 `assert latest.exists()` 能 PASS **只可能**来自 `write_alert` 的写入(main 版 `_mirror_severe` 同被 `not dry_run` 挡住)⇒ **该断言确实是病灶的真复现,不是假绿**。

**(b) 改后是「负控→正控」,不是削弱** —— 新断言 = `not latest.exists()` **+** 日志含 `[notify][dry-run]` 与 **`write_alert 跳过写`**。后一条是**执行证明**(旧断言无法区分「真没写」与「根本没执行」),即新断言比旧断言**更强**;且它会在**旧代码下变红**(上表 OLD 已创建文件)⇒ 判据仍有区分力。

**(c) 覆盖零净损失** —— 「实跑仍写 latest.md」由同文件②组的 3 个用例(直接调 `notify.write_alert` 不传 dry_run,走真实写路径)+ 新文件 test2/test4 承接;我实跑这两文件 **15 passed**(见 §3)。

**(d) §23.7 判定:不需要单独的「改测试」授权,但需要「改行为」的授权记录** —— 测试文件是行为契约的镜像,不是产品功能本体;被测行为本身已立项(#184)并按 pending-index 状态列「用户已拍板授权」;断言不同步的唯一后果是 CI 恒红。**结论:改法正当**;但「用户拍板」是仓外事实,见 §5-1。

### ④ 零外发哨兵 — PASS

- **覆盖完整**:notify.py 全部出网入口 = `smtplib.SMTP_SSL`(L938)与 `urllib.request.urlopen`(L446/536/547);无 `requests`/`socket`/`http.client` ⇒ fixture 的两个 patch 覆盖全部真实发送路径(飞书 token/消息、TG、邮件)。
- **实测「真能拦」**(沙箱假凭据 + 把两函数换成 raiser):`_send_email`(非 dry)触达哨兵 1 次;`_feishu_http_post_json` 触达 1 次;`_send_email(dry_run=True)` **触达 0 次**(dry-run 真短路)⇒ 哨兵不是摆设。
- **用例面**:6 例全部 tmp 隔离(fixture autouse patch `ALERTS_DIR/ALERTS_FILE/WARNING_BUFFER_FILE/INFO_LOG_FILE/WARNING_DEDUP_STATE_FILE/DEDUP_FILE`);唯一非 dry-run 用例以 `notify.send` 桩覆盖;文件内**无 subprocess**;`--dedup-key` 未使用 ⇒ 不会写 `alert_denoise_rules` 的 state 文件。
- ⚠️ 措辞打折(见 D3):`_send_email` 把异常吞成「print 警告 + 返 False」,故邮件通道**只阻断、不响亮**;urlopen 侧 RuntimeError 会上抛=响亮。

### ⑤ latest.md 逐位一致证据 — PASS(按 mtime+隔离读,不是单靠 md5)

- 可复算:今日复算生产 `data/alerts/latest.md` = `e8e4db889167bdd04aad8aaaa61cf9c8` / 32353 B —— 与报告**逐位一致**。
- 「真没写」vs「没执行」的区分:单看 md5 确实分不出(报告这条证据本身偏弱),但**更强佐证在位**:该文件 **mtime=1791279611 = 2026-10-06 17:40:11**,**早于今天全部自测**(mtime 不会被 python 写入保留);叠加 ①fixture 把 ALERTS_DIR 指向 tmp ②实施者 worktree **无** `data/alerts/` ③wrapper 用例 `REPO=tmp` 实测生效(`resolve_repo: REPO=/tmp/... (source=env)`)④新流程实测**连 data/alerts 目录都不建** ⇒ 组合证据成立。
- 本轮审查期间(审前/审后各一次)该文件 md5+mtime **均未变**。

### ⑥ out-of-scope 上报复核 — 结论成立,影响面描述需订正

- **病灶实测复现**(分支版,沙箱):`notify.py "test info" "detail" --tier info --dry-run` → 生成 `info_log.jsonl`(74 B 真记录)。代码链:`send_tiered` L2070-2071 info 分支 **不透传 dry_run**;`log_info` L1424 无条件 `_append_jsonl`(+>2000 行截断重写 L1429)⇒ 实施者判定「该 gate 但超范围,只报告未改」**正确**。
- ⚠️ 「生产 4 个用 `--tier info` 的脚本**均不传** `--dry-run`」**不实**:`staticdata_sync.sh:248` 与 `staticdata_backup_async.sh:397` 都带 `"${_NOTIFY_DRY[@]}"`,由 env 钩子 `STATICDATA_SYNC_NOTIFY_DRY_RUN=1` / `STATICDATA_BACKUP_NOTIFY_DRY_RUN=1` 注入 `--dry-run`(自验场景**真会命中**);`schedule_monitor.sh:2520` 与 `self_heal.sh:176` 确无 dry-run(这一半属实)⇒ 见 D2。
- **影响面仍判「低」**:`info_log.jsonl` 是 dashboard 滚动日志,非外发、非 `latest.md`(Claude 开工登记面)、非告警流水;推荐修法一行级(`log_info` 收 dry_run + 透传),但属另一已上线档位 → §23.7 待拍板,**本轮不扩改是对的**。

### ⑦ 回归面 — PASS(双重证据)

- **静态**:`write_alert` 函数体 main vs 分支逐行 diff = **仅**「签名 + docstring + 4 行守卫」;两 shell 脚本改动经「非注释行」过滤器核实**全为注释**(`uptime_check.sh` 唯一像代码的那行,代码部分逐字相同,只改了行尾注释)。
- **动态 A/B**(沙箱分别用 main/分支 notify.py 跑同一组**非 dry-run** 命令):
  - `--severe --from-prefix --alert-issue --alert-log` → 归一化时间戳后 `latest.md` **逐字节 diff 为空**(含 `_mirror_severe` 流水镜像行),stdout/stderr diff 为空;
  - `--tier critical --alert-issue --dedup-key` / `--tier warning` / `--flush-warnings` / `--agent-done` → 输出一致 + **落盘文件集合逐一相同** + `latest.md`/`notify_dedup.json` 内容一致(warning_buffer 仅 `rid` 内嵌时间/pid 位不同,fp 指纹相同=预期非确定性);
  - 零外发(沙箱无 `config/email.json`/`feishu.json` ⇒ 实打印「config/email.json 不存在，跳过邮件」「汇总：全部渠道未发出」)。
- **dry_run=True 时守卫在最前**(`ALERTS_DIR.mkdir` 之前)⇒ 不产生目录/锁文件(实测)。

### ⑧ git 纪律 — PASS(1 项提示)

- 单 commit(`main..feat` = `8997c6300`);merge-base == `92fa551ad` ✓;tip == `origin/feat/184-...`(都是 `8997c6300`,**无 force 迹象**);未碰 main;`diff --name-status` 仅 7 文件(`notify.py` / 2 shell / 2 tests / docs/ops 报告 / pending-index),**无根 `data/`、无 `static-site/data/`、无二进制**。
- 提示(非 FAIL):审查期间 `origin/main` 已前移到 `18f758e6c`(TASKS.md + #212/#213 两份 docs,纯文档),与 feat 分支文件**零相交**(`comm -12` 为空)⇒ 无 rebase 冲突风险;base-fresh 在派单时成立,merge 走 `main-merge.sh` 新鲜度检查即可。

## 2. 披露项(全部 <80 分,非阻断;按 §10.2 计 6 条)

- **D1(75)** 报告 §2「write_alert 全仓无 notify.py 外调用方」不实(3 处外部调用)。trace:`scripts/check_ds_resilience.py:259/266`;linkage=uncertain(报告断言);verifier:`grep -rn "write_alert" scripts/ app/ tools/`;observed=3 文件命中。**动作:报告措辞订正一行**(不阻断 merge);顺带说明机检 test#6 只扫 notify.py 源码,跨文件新调用点不会被它抓(但函数内守卫仍保护任何显式传 `dry_run=True` 的调用)。over_engineering:无需改动代码。
- **D2(75)** 报告 §4/索引「4 脚本均不传 --dry-run」不实(2 个 staticdata 脚本有 env 钩子会传)。trace:`scripts/staticdata_sync.sh:44-46,248` / `scripts/staticdata_backup_async.sh:110-112,397`;verifier:读码 + 上面 ⑥ 实测;observed=钩子存在。**动作:订正为「生产常态不传;自验钩子会传,故 info_log 缺口在自验场景真会命中,但仍是 dashboard 级」。**
- **D3(65,已滤)** 新测试「任何真实发送触达即 RuntimeError 响亮失败」对**邮件**通道不成立:`_send_email` 内层 `except` 吞异常 → 返回 False(`observed`:打印「[notify] 邮件发送失败（不阻塞）：OUTBOUND BLOCKED」,返回值 False,进程不红)。**阻断属性仍在**(SMTP_SSL/urlopen 已被替换,真连接不可能发生)⇒ 只是可检测性打折。建议 docstring 改「邮件侧=阻断,urlopen 侧=阻断+响亮」。
- **D4(65,已滤)** `--flush-warnings --dry-run` 仍创建 `data/alerts/` + 0 字节 `warning_buffer.flushlock`(pre-existing,非本 diff)。报告/索引标题「零落盘」宜限定为「`write_alert`/`latest.md` 零落盘」。verifier:`ls -la <沙箱>/data/alerts/`。
- **D5(60,已滤)** 机检 test#6 的三处脆弱性(实测样例):①`src.index(")")` 按**第一个**右括号截断 ⇒ 参数中含嵌套括号(`build(x).body`)**假红**;②硬编码字面量 `dry_run=args.dry_run` ⇒ 写成 `dry_run = args.dry_run` **假红**;③只认 `args.alert_issue`,换变量名的未来调用点会被**跳过**(假绿面)。方向安全(假红=宁多勿漏),但建议后续改 AST 解析(如 `ast.parse` 遍历 Call 节点)根治。
- **D6(50,已滤)** nitpick:测试断言耦合打印字符串(改文案即假红);新文件末尾无换行。

**over_engineering 维度(§10.6)**:本次代码类改动**无删除/简化建议** —— 4 行守卫是单点根因修(优于「5 处各打补丁」);5 处透传是必要显式性(换成模块级全局 flag 反而引入隐式状态);那句 `print` 不是装饰,是新测试「执行证明」断言的载荷(去掉会削弱区分力)。

## 3. 复现命令(全部 /tmp 沙箱,零生产影响)

```bash
# ① A/B 病灶复现(CLI 级)
mkdir -p /tmp/184-ab/{old,new}/scripts
git show main:scripts/notify.py   > /tmp/184-ab/old/scripts/notify.py
git show main:scripts/alert_denoise_rules.py > /tmp/184-ab/old/scripts/alert_denoise_rules.py
git show feat/184-notify-dryrun-gate-20261007:scripts/notify.py > /tmp/184-ab/new/scripts/notify.py
git show feat/184-notify-dryrun-gate-20261007:scripts/alert_denoise_rules.py > /tmp/184-ab/new/scripts/alert_denoise_rules.py
PY=/Users/linhuichen/code/trade/.venv/bin/python
for V in old new; do $PY /tmp/184-ab/$V/scripts/notify.py "S" "B" --severe --from-prefix "[告警]" \
  --alert-issue "ISSUE" --dry-run; ls -la /tmp/184-ab/$V/data/alerts/ 2>&1; done
#   期望:old 生成 latest.md;new 无 data/alerts 目录 + 打印「write_alert 跳过写」
# ② 非 dry-run 逐位一致(去掉 --dry-run 重跑同命令,时间戳归一化后 diff = 空)
# ③ out-of-scope 复现
$PY /tmp/184-ab/new/scripts/notify.py "t" "d" --tier info --dry-run; cat /tmp/184-ab/new/data/alerts/info_log.jsonl
# ④ 两个测试文件(在实施者 worktree 内跑,禁写缓存/字节码)
WT=/Users/linhuichen/code/trade/.claude/worktrees/agent-a6c1af9760fa62d00
PYTHONDONTWRITEBYTECODE=1 $PY -m pytest -q -p no:cacheprovider \
  $WT/scripts/tests/test_184_notify_dryrun_gate_20261007.py \
  $WT/scripts/tests/test_alertchain_hardening_20261003.py    # → 15 passed
```

**零生产影响证据**:①全部实验在 `/tmp/184-ab/**`;②未 checkout 分支到主树(只 `git show` 读内容);③生产 `data/alerts/latest.md` md5+mtime 审前/审后两次复核**均不变**;④实施者 worktree 跑完 pytest 后 `git status --porcelain` 仍**为空**、仍停 `8997c6300`,worktree 内无 `data/alerts/` 生成;⑤全程无真发(沙箱无凭据 + dry-run + 哨兵探针只 patch 不真连)。

## 4. 规范适用性

- §24(前端部署防撕裂四查)/ §21(算法公示同步):**不触发**(未动任何前端源文件/算法/数值)。
- §22(数据一致性)/ C 级数据校验:`latest.md` 是单文件、无多展示位/多缓存,无跨文件同值面 ⇒ **不触发**;未动 static-site/R2/CF。
- §15/§18 回归:**已做**(见 ⑦)。
- §25(删前备份):本轮为只读审查,无删除动作;为防意外仍先备份生产 `latest.md` 至 `/tmp/184-backup-latest.md`(md5 一致)。

## 5. 上报 / 未决(请主控处理)

1. **§23.7 用户拍板记录自核**:分支与 pending-index 均记「用户已拍板授权,§23.7 冻结面已确认」,但这是**仓外事实**,reviewer 无法从仓内证伪/证实。merge 前请主控核对该拍板记录(尤其「动已上线行为」的点名授权)。
2. **info_log.jsonl(#184 同类未修)**:是否本轮顺手修(一行级)或另立编号,待主控/用户拍板。
3. **origin/main 前移说明**:现 `18f758e6c`(纯 docs,零相交),merge 无冲突风险。
4. **D1/D2 措辞订正**:可在 merge 前由主控顺手改实施报告/索引两处措辞(非阻断)。
5. **D5 建议**:机检 test#6 后续可改 AST 遍历(登记待办即可,不急)。
