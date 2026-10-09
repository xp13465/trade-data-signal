# W2 三态判据 · 独立审查报告（reviewer agent，独立上下文）

- 审查对象：`feat/alert-w2-tri-state-1010` @ `9e8d46f9b`（base = origin/main `6ad3c742e`，单提交）
- 审查者：独立 reviewer（fresh context，只审不改，未 Edit/Write 任何仓库文件、未切分支、未 commit/push）
- **残留后台任务声明：无待 TaskStop 项。** 本次审查曾出现过 2 个后台化命令：①全量 pytest（nohup，pid 77480）→ 已完成（结果见下）；②误起于错误树的 pytest（pid 76739）→ 已 kill。收尾 `pgrep -fl` 复核无残留进程。
- 结论：**PASS（不阻断合并）**——12/12 项全 PASS；无 ≥80 分问题；低分观察 6 条（见文末，均不阻断）；诚实披露见 ⑨⑩。

## 逐项判定（12 项，每条含证据命令 + 观测值）

### ① PASS：notify.py 零改动
- 证据：`git diff origin/main..HEAD -- scripts/notify.py` → 输出 0 行。
- 观测：本分支 9 个改动文件中无 scripts/notify.py。

### ② PASS：notify_sent() 一字不改
- 证据：分支版 vs origin/main 版 `notify_sent()` 函数体逐字节比较 → IDENTICAL（仅模块 docstring 行号订正：2368/2371→2359/2362、2190→2189、2334→2335）。
- 观测：函数体零差异；新增 `_SUPPRESS_SIGNATURES` / `_is_suppress_line` / `notify_state` 均为纯新增。

### ③ PASS：三态判据正确性（行首锚定够严 + 反向用例）
- 证据：独立 24 用例边界探针（.venv/bin/python 直接 import 分支版 notify_sent 模块跑）→ `TOTAL 24 MISMATCH 0`。
- 覆盖：7 条签名全命中（suppressed）；反向用例 `[notify][tier=warning] 路由完成：{'deferred': True, 'defer_status': 'suppressed'}` → **sent**（sent 优先顺序硬约束实测成立）；`append_failed` → failed；空输出/仅空白/unknown → failed；非抑制同前缀行（如 `[notify][dedup] 窗口已过…`、`[notify][r4]…已发（不在窗口）`、tier 前缀缺标记）→ failed 不误判；裸 `suppress` 词 → failed（无子串分类）。
- 实现核对：`_is_suppress_line` = `lstrip()` + `startswith(prefix)` + 可选行内标记，全部行首锚定。

### ④ PASS：与 W1（feat/alert-l1-meter-1010 @ 23f3304a0）合流后判定仍正确
- 证据：`git show feat/alert-l1-meter-1010:scripts/notify.py` 逐点核对；关键字面量 grep 计数 base vs W1 全同（7 条 suppress 字面量各 1/1、`已发出` 2/2、`全部渠道未发出` 2/2、`路由完成：` 3/3）。
- 观测：W1 新增行仅 `[notify][ledger] 台账登记 …` / `[notify][ledger] 台账写入失败(不影响发送): …` —— 不命中任何签名前缀，也不含 `已发出`/`路由完成：`/`True` + 不干扰 `全部渠道未发出` 优先判定；try/finally 与 wrapper 重绑定不改变 stdout/stderr 文本形态；两分支改动文件交集 = ∅（W2 零改 notify.py）。⇒ **先后合入 main 均不影响三态判定**。

### ⑤ PASS：test_alertchain_hardening fake 改动不是「假样本养绿」（§18 L49）
- 观测：新 fake = `output="[notify] 汇总：已发出 email/feishu\n"`，置于 stderr（对齐 notify.py 打 stderr 的真实形态），字面量 = notify.py:2359 真实生产输出（f-string `已发出 {'/'.join(ok)}` 的实打形态）；旧 fake（空 stderr）反而是现实中不存在的形态（notify.py 通用路径必打两种汇总行之一）。
- 改前/改后判别力对照：旧 fake 在新判据下 = failed → cmh rc=2（旧断言实际靠旧 rc=0 语义养绿——正是本波要修的病灶）；新 fake 走真判据 sent → rc=0。属「真实样」而非「假样」。
- 残余（低分 c）：该 legacy 文件无法再捕获「cmh 退回 rc-only」类回归 → 已由新文件 test_40 red-before-green（旧 rc 语义 lambda 复现「全失败被当成功」）补位。

### ⑥ PASS：fail-safe 双方向
- 被抑制⇒判失败⇒每窗假报警（方向A）：抑制行只在其「成功语义」分支打印（check_dedup L1272-1273 打印后通用路径 return 0；tier L2183 同构；R4/R7/#196/agent-done/同源抑制同）⇒ 判 suppressed → 三站点 return 0 / notify_rc 不置 1 ⇒ 无假报警。实测：24 用例 7 签名全判 suppressed。
- 真失败⇒判成功⇒吞故障（方向B）：全渠道失败打印 `[notify] 汇总：全部渠道未发出（…）`（L2362）且无抑制行 → failed ⇒ cmh rc=2（systemd failed 走 #196 通道）/ gap+plan notify_rc=1 ⇒ 不吞。实测：探针 case3 failed。
- dry-run：模拟成功仍打「已发出」汇总行 → sent（不影响；生产 unit 不带 --dry-run）。

### ⑦ PASS：全库 notify_sent 调用面穷举 + 无遗漏 rc 判据站点
- 证据（我独立 sweep）：`git grep -n "notify_sent" -- '*.py' '*.sh'`（排除 tests）→ 存量调用方 = **9 文件 / 9 调用点**：check_data_gap_alerts:1476、check_failed_units:253（经 `_notify_sent` wrapper，:277 处使用）、check_s06_freshness:144、detect_intraday_anomaly:320、overfit_monitor:1447、retry_failed_metrics:163、sensenova-proxy-healthcheck:153、monitor_72h.sh:919、schedule_monitor.sh:2837；与调研文档 Q2-A 明细枚举完全一致。
- 剩余 `returncode` 用法逐文件核对：全部为 crash 检测（overfit_monitor L1728/L1996 系 R2 上传等其它子进程）或失败日志打印（各文件 print(detail) 级），**无「rc 当 sent 判据」遗漏站点**。3 个 W2 站点改 notify_state 为其中仅存的 rc 判据站点。⇒ 结论成立。
- 低分 b：文档标称「存量 12 个调用方」/「调用方 12 处」与明细枚举 9 项对不上（实测 9 文件/9 调用点；若把 6 个测试文件计入=15）→ 计数口径存疑，不影响穷举集合结论（集合我已独立复核一致）。

### ⑧ PASS：§23.7 冻结契约（只有判据变了？）
- 观测：3 站点改动 = 判据替换（rc → notify_state 三态）+ docstring 退出码说明 + `_severe_alert` 日志 rc→state（fire-and-forget 日志措辞）；subprocess 参数不变（capture_output / text / timeout=120 / check=False 与原一致）；通知命令参数不变（dedup-key/window/feishu-group 同）；退出码映射保留：sent/suppressed→0，否则 2（cmh）/ notify_rc=1（gap/plan）。
- 已文档化的唯一 delta：非 0 rc + sent 输出 → 现在判成功（输出优先 rc，本波设计本体之一，实施报告 §5 已写明）。
- 无日志文本消费者受影响（retry_failed_metrics:130 匹配的 L2183 措辞零改动，grep 计数 1/1 复核）。

### ⑨ PASS：零外发（诚实披露）
- ZeroOutboundTrap 武装证据：test_00 断言 trap 已挂（urlopen/SMTP/SMTP_SSL）；全量 624 测试 0 失败 = trap 全程未触发 = **零真实外发**。
- 诚实披露：全量测试会在被测树本地写合成 `data/alerts/latest.md` 行（00:51:25 / 00:59:15 两条 "email=OK feishu=OK"）——经查为**既有 legacy 测试**（test_notify_dedup 等，渠道全打桩 + `_mirror_severe` 本地落盘）行为，非 W2 引入、无外发；该行只存在于 worktree 测试树，主仓 data/ 未动。（对 W1 reviewer 相关：W1 合入后该测试还会写合成台账行。）
- 我本次审查自身：只跑 grep/读代码/探针（import 纯判据函数），零外发。

### ⑩ PASS：回归（我自跑，与实施者数字对账）
- 我复跑全量：`/Users/linhuichen/code/trade/.venv/bin/python -m pytest -q scripts/tests/`（W2 worktree .claude/worktrees/agent-a7744488f202210b8，nohup 落盘）→ **624 passed, 2 skipped in 92.90s**（日志 /tmp/w2-review-pytest.log）。
- 实施者日志 /tmp/w2-pytest.log → 624 passed, 2 skipped in 93.52s → **对账一致**。
- 目标两文件复跑（本报告撰写时重跑）→ 23 passed in 0.50s（test_alertchain_hardening 14 + test_alert_w2_tri_state 9，与声称 14+9 一致）。

### ⑪ PASS：文档订正（survey 逐字对账 + plan 纯文本）
- survey：分支版 sha1 `8de195eceec29d6701f462a4923fed2885a64667` == /tmp 副本（shasum -a 1 比对一致）。
- plan 文档 diff：3 行纯文本订正（§2 写点=3 渠道函数；§3 病灶修正 + 「订正（证伪）」段，明确改走路线 B）；无代码块改动。
- 低分 a：§3「推荐改法(加法,不弱化判别维度)」旧段（推荐动冻结面加行的路线 A 说法）未同步删改，与新订正并列易误读。

### ⑫ PASS：回滚
- 单提交 `9e8d46f9b`（parent 6ad3c742e）⇒ `git revert 9e8d46f9b` 干净可行；未 merge 前弃分支=完全回滚；回滚后 3 站点回到 rc 判据语义（文档 §6 已写明）。

## 低分观察（<80 分，不阻断，建议后续顺带处理）
- (a) ~50：plan §3「推荐改法(加法)」旧段未同步（文档一致性，纯文案）。
- (b) ~50：文档「12 个调用方」计数与实测口径（9 文件/9 调用点）不符（纯文案）。
- (c) ~45：legacy 测试不能捕获 rc-only 回归（由 test_40 补位，跨文件依赖）。
- (d) 既有项（非 W2 引入，需上报）：全量 pytest 在测试树写合成 latest.md 行（W1 合入后叠加假台账行），对 W1 reviewer 相关。
- (e) ~25 理论项：dry-run 打印 body 前 200 字到 stderr，若 body 行首恰为抑制签名理论上可误判 suppressed——对 3 站点不可达（body 机器生成），生产不带 --dry-run。
- (f) 信息项：既有 notify_sent 消费方（check_s06_freshness 等）把 suppressed 视同「未发出」——行为未被本波触及、零回归；后续如需区分可直接复用 notify_state。

## 合并建议
**PASS，可进 merge 队列**（与 W1 先后合入均无冲突：文件交集 ∅、字面量零漂移、合流后判定正确——④已核）。低分 (a)(b) 建议主控顺手派给下一波/实施者订正（不阻断）。
