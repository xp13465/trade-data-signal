# #217④ 告警文案订正 + #223 超时梯度 —— 独立评审报告(2026-10-06)

> 【严重】**第 7/8 项范围内存在一处虚 claim(唯一一处,报告开头标出)**:实施报告称「本机无云上 ssh key(`~/.ssh/tdsignal.pem` 不存在)⇒ 我改不了云上」——**实测为虚**(key 在 `~/tdsignal.pem`,本轮已用它完成云上只读取证)。**scope 说明:非决策级**——5 项待拍板的数值 claim 与 ①/② 拒改主依据(云上 systemd=600)全部实测为真,拒改结论与 merge 资格 **不受影响**;详见证 §0-1。

- 分支:`feat/217-223-threshold-copy-20261006` @ **cd3994cb2**(远端 hash 已核对一致;tip 不在 origin/main ⇒ 待本审 PASS 后 merge)
- 审查者:reviewer(独立复算;不采信实施者自报的任何结论)
- 改动面(7 文件,与 merge-base `46d878e53` 比):`scripts/upload_r2.py`(文案)、`scripts/fapi_bj_width_export.py`(守卫)、`scripts/gen_daily_brief.py` / `nextday_plan_generator.py` / `nextday_gap_check.py`(注释)、`scripts/tests/test_223_timeout_gradient_copy.py`(新,211 行)、`docs/ops/217-223-threshold-copy-20261006.md`(报告)

## 0. 结论与严重度说明

**merge 资格 = PASS**(逐项 10/10 通过)。附 3 条非阻断标注:

1. **唯一不实陈述(非决策级)**:报告 §0 拍板项 1 与 §7-2 称「本机无云上 ssh key(`~/.ssh/tdsignal.pem` 不存在)⇒ 我改不了云上」——**不实**:key 在 **`~/tdsignal.pem`**(实测 `-rw------- 1674B`;memory `ssh-cloud-uses-tdsignal-pem` 有记),且云上 ssh 是读写权限(memory `cloud-ssh-full-readwrite-not-readonly`)。影响:不改变 ①/② 拒改结论(拒改主依据=systemd 600 天花板,**已云上实测为真**),但「改不了云上」会误导用户以为必须另找人上云;真阻塞=方向未定 + 改生产需拍板(§23.7/§14),不是没 key。
2. **第二处表述瑕疵(方向级,重要)**:拍板项 5 建议「(600→900 或 systemd 抬)」方向有歧义。若按「Python 侧 600→900 而 systemd 不动」理解 = **反向操作**(制造真倒置,与实施者自己反对 s06 病灶的理由自相矛盾)。⑤ 的正确修法写死为 **抬外层 systemd**(见 §11 表 ⑤ 行)。
3. merge 注意:分支 base = main@46d878e53,main 已前进到 8366bfabc(含 #224);只读 `git merge-tree` 预演 **0 冲突**(两侧改动面不重叠);merge 后 CI 将同时收集 `test_223` 与 `test_224`,应一并复跑(走 main-merge.sh 自然覆盖)。

**第 7/8 项决策级 claim 全部查实为真**(逐条见 §7/§8),拍板依据可靠,无决策级虚 claim。

## 1. ② 告警判别维度保留(最高优先)—— PASS

逐字段精确 diff(`git diff $(git merge-base origin/main …) … -- scripts/upload_r2.py`,两 hunk 只动正文行):

| 维度 | main 版 | 分支版 | 判定 |
|---|---|---|---|
| 阈值(代码) | `if total_mismatch_found > 50:` | 同 | 未动 |
| 阈值(文案) | `(阈值 50)` | 同(原样 context 行) | 未动 |
| dedup key | `verify_r2_mass_mismatch` / `verify_r2_standalone_stale` | 同 | 未动 |
| dedup 窗口 | `check_dedup(…, 21600)` ×2 | 同 | 未动 |
| subject ×2 | `[告警] R2 可能被异源覆盖(verify-r2 大量不一致)` / `[告警] 独立上传链产物与 R2 脱节(verify-r2 兜底补传)` | 同 | 未动 |
| 周日可忽略 | mass 有「(若为周日全量对账设计内补传可忽略此提示)」+新增「①周日全量对账的设计内兜底(见末句,可忽略)」 | 保留+强化 | 未丢 |
| 误跑真故障判别 | 「请查本机是否误跑 export.py/upload_r2.py」 | 保留(并入②) | 未丢 |
| `update_dedup(_dedup_key)` | 有 | 有 | 未动 |

- 注:原 `standalone_stale` 正文**本无**「周日可忽略」措辞(实读 main 版确认),task 书把它列为该条维度属预期差;新正文以「双因结构 (a)设计内/无需处置」覆盖同类语义,不构成丢失。
- **test_188 独立实跑**(该告警路径直接回归):`ALL_PASS` rc=0,含「正例: 脱节 → 发外围告警(verify_r2_standalone_stale)」及「反例: R2 一致 → 无补传、无告警」,另有 34 条 PASS。
- **test_193 独立实跑**(L6 异源覆盖路径):`断言 40 PASS / 0 FAIL / ALL_PASS`。
- 新测试 [E] 静态断言两 subject/两 dedup key/`> 50`/`update_dedup` 全保留 —— 已随全套 pytest 实跑通过。
- **零真实外发实证**(§18 L48):两组测试跑前跑后,主树 `data/alerts/latest.md` md5 恒为 `e8e4db88…`(未变),worktree `latest.md` 始终不存在;两测试均为 `sys.modules['notify']` 桩 + 陷阱(我逐段读过打桩代码)。

## 2. 文案与新事实一致 —— PASS

1. **举例池=台账实有池:真**。云上实读 `~/code/trade-data/data/.r2_standalone_keys.json`(35 项)= `a-stock-{3m,6m,1y,3y,5y,all}.json` + `overview.json` + `news_digest` 家族(`news_digest.json`+`_index`+27 日期档)+ `schedule_stats.json` —— 与新正文枚举**逐项一致**;含 **0 个** s06/nextday_plan/daily_brief(删举例=纠错,非阉割)。
2. **「schedule_monitor 每 15min 跑前 gen」:真**。云上 `trade-schedule-monitor.timer` 实测 15min 档(23:15→23:30);脚本 L440-447 跑前调 `gen_schedule_stats.py` 重生成(写 `schedule_stats.json`,该文件在台账内)⇒「生成点超前于上传点」的机制存在。「trap EXIT gen」亦有实例(`rzhb_backfill.sh:53` / `us_stock_morning.sh:33`)。
3. **N≈114 为口径而非事实数字:成立**。正文明确「量级口径…N 不可逐字考…>50 已证…同轮实测量级 ≈114 —— 本条 N 只作量级参考」。底层证据云上复核:①`deploy_20261004_0205.log` **L772 = 「[verify-r2] ✓ 对账完成, 自动补传 114 个」**,`FAILED_FILES` 0 处(「无失败记录」真);②signal 树 `data/notify_dedup.json` `verify_r2_mass_mismatch last_alerted = 2026-10-04 04:07:20`(与文案引用**逐字一致**);③log mtime 04:07 = 同轮。另注:`verify_r2_standalone_stale last_alerted = 2026-10-06 18:19:38`(被改文案对应**活告警**,非存文本)。

## 3. §23.10 飞书=邮件 —— PASS(附既有机制观察)

- 独立核实实施者断言:真。`notify.send`(notify.py L947)把**同一个 `body` 参数**分发给 `_send_email` / `send_telegram` / `send_feishu`,无按通道改写正文的分支;alert 群走 text 路径(非 report 群的 post 分段),`log_text = subject + "\n\n" + _html_to_text(body)`。
- 本两条告警实测渲染长度:mass 388 字符 / stale 533 字符,均 **< FEISHU_TEXT_LIMIT=2000**,且正文无 `<`/`&` ⇒ `_html_to_text` 恒等变换 ⇒ 飞书副本与邮件正文**逐字相同,无截断**。
- **标出(现行机制,非本次引入,未被触发)**:alert 群飞书 text >2000 会 `[:1970]+\n…(已截断)`(notify.py L839);Telegram >4096 截断(L427)。本次两条远未触线,不影响 PASS 判定。

## 4. §21 判定 N/A —— PASS

独立 grep 复核:生产代码命中仅 `scripts/upload_r2.py`(其余为 `test_188`/`test_193` 断言与注释、docs);`static-site/*.js|*.html` 对「异源覆盖/独立上传链产物/verify-r2」**零命中** ⇒ 无前端公示需同步。N/A 成立。

## 5. B③ 修得对不对 —— PASS(5 个子项全过)

1. **外层墙钟**:云上 `systemctl show trade-fapi-daily.service -p TimeoutStartUSec` = **infinity**;ExecStart=`/bin/bash …/fapi_daily_syn.sh`;该脚本 grep 无 `run_to`/`timeout`/systemd 交互(实测空)⇒ L1=900 是唯一墙钟,无天花板。且该文件仅被 `fapi_daily_syn.sh` 调用(grep 全仓生产路径),无第二条带各自超时的调用链。
2. **守卫逻辑**:`<=` 判零梯度/倒置、抬到 `内层+300`、stdout 警告(flush)文案准确;调用点 `_to = _r2_upload_timeout()` → `subprocess.run(…, timeout=_to)`,超时消息已动态化(残留硬编码 `600s` 清零)。
3. **构造样本实测**(§18 L50 static-only:AST 抽常量+函数 → exec,**未 import 业务模块、未执行任何业务脚本主体**;在 /tmp 副本上做,不碰仓库):
   - 我自写 range 实测 inner ∈ {0,30,60,120,300,599,600,899,900,901,1200,abc}:返回值 **恒 > inner**;警告恰在「常量 ≤ inner」时出现(inner=900→1200+警告;inner=600→900 静默)⇒ **不变量成立,不可能造出新倒置**。
   - 破坏性实验(副本):正文加回 `s06` ⇒ [D] FAIL;常量 900→600 ⇒ [A] FAIL=3;删一条断言 ⇒ 被 `MIN_ASSERTIONS=33` 拦(「断言数仅 32」)。
4. **没造出新倒置**:同上不变量全 range 成立;旧形态(600==600 零梯度)已被消除为 600<900(+300 余量)。
5. 其余三处仅加注释(见 §6),未动值 ⇒ 未制造「外层 900 / systemd 600」错配。

## 6. 注释类改动只动注释 —— PASS

`git diff` 逐处核:`gen_daily_brief.py`(+4 行,全 `#`)、`nextday_plan_generator.py`(+4,全 `#`)、`nextday_gap_check.py`(+3,全 `#`);被注释包着的 `timeout=120` / `timeout=300` / `timeout=300` 值行**未出现在 diff 变更侧**(context 行)。**零值/零逻辑变更**。

## 7. ①/② 拒改理由是否成立 —— 拒改**正确**(理由主链真,表述有 2 处瑕疵见 §0)

云上实测(只读 `systemctl show`):`trade-daily-brief.service` = **10min(600)**、`trade-nextday-plan.service` = **10min(600)**;`.env` `R2_UPLOAD_HTTP_TIMEOUT=600`(两树 grep 取证)。⇒ 推论「单独抬 L1 到 900 会被 systemd 600 先 SIGKILL、`except TimeoutExpired` 的 degrade/severe 永不执行」**成立** ⇒ 拒改正确(得附:①②③ 的外层 .sh 均无 shell 看门狗,已 grep 实测;systemd 是唯一外层)。

## 8. 5 项待拍板 claim 真实性 —— 全部为真(数值级)

| claim | 核实方式 | 判定 |
|---|---|---|
| ③ `nextday_gap_check.py:358` `timeout=300` | 读码(注释正下方 context 行) | 真 |
| ④ `fetch_news.py:722` = `120 + R2_UPLOAD_SKIP_RETRY_SECS(60)` = 180 | 读码(变量式,人读确认) | 真 |
| ④ `overfit_monitor.py:1869` = `120+skip_retry` = 180 | 读码 | 真 |
| ④ overfit_monitor systemd = **0(∞)** | 云上 `systemctl show` = infinity | 真 |
| ⑤ `fetch_news.py:755` staticdata `timeout=600` == systemd 600 | 读码 + 云上 10min | 真 |
| ⑤ `gen_daily_brief.py:3167` staticdata `timeout=600` == systemd 600 | 读码(L3162-3163)+ 云上 10min | 真 |
| 「该维度被现有审计脚本明确排除」 | 实读 `scripts/systemd_timeout_gradient_audit.py` docstring「局限:只识别 shell 层 run_to / perl alarm;Python 侧 subprocess timeout … 不计入」 | 真 |

**唯一虚述** = §0 第 1 条(ssh key)。另:⑤ 建议句方向歧义见 §0 第 2 条/§11 表。

## 9. 新测试质量 —— PASS

- **全套实跑**(venv pytest,CI 同口径命令,分支 tip 树):`249 tests collected` → **248 passed, 1 skipped**(skip=`test_monitor_resource_inprogress…py:183` macOS APFS,`-rs` 核实)。
- **平台分布解释:独立证实**。注入假 `systemctl` 到 PATH(模拟 Linux)后:`test_160…:277`/`test_196…:457` 转为 skip(246 passed + 3 skipped)⇒ 机制与实施者描述一致;云上实测机器=`linux` 且有 `/usr/bin/systemctl` ⇒ CI 侧:monitor 测试不 skip(该项在 main 绿 CI 中长期实跑),test_160/196 skip ⇒ **含新测试 = 247 passed + 2 skipped**(与报告一致;task 书「247+1 / 246+2」= 不含新测试的基线口径,两者条目总数 249/248 各自自洽)。
- **static-only**:文件不 import 任何业务模块(仅 ast/io/os/sys/contextlib/pathlib);抽取全在 test 函数体内(收集期不炸门禁);不依赖 `.env`/`/tmp`/进度文件(只读两个 .py 源)。`conftest.py` 未被本分支改动(diff 0 行)。
- **MIN_ASSERTIONS 有效**:故意删一条断言 ⇒ FAIL(「断言数仅 32(下限 33), 疑似收集/执行异常」);不会假绿。
- 覆盖精度:新测试同时守住「文案改动」([D])与「守卫回归」([A]/[B]),三个破坏实验全部被抓。

## 10. git 卫生 —— PASS

- 分支独有 4 commit;远端 `refs/heads/feat/217-223-threshold-copy-20261006` = **cd3994cb2**(与 tip 一致,已推)。
- 改动面 7 文件,**无根 `data/`、无 `static-site/`、无 `conftest.py`**;worktree 工作区干净(无未提交改动);报告在册(`docs/ops/217-223-threshold-copy-20261006.md`)。
- merge 预演(只读 `git merge-tree`):**0 冲突**;main 侧新文件 `scripts/tests/test_224_zombie_cron_gate.py` 与本分支无重叠,merge 后共存。
- 残留:`.claude/worktrees/agent-a2916e5d980cb8aee`(实施者工作树)仍占分支 `feat/217-223…`;不影响 main-merge(merge 无需 checkout 该分支);若续跑同任务需先 `git worktree remove --force`(memory `resume-same-task-reuse-branch`)。

---

## 11. 【主控追加交付】5 项待拍板 — 逐项定性表

> **判据(主控给定,严格执行)**:不看数字大小,看「谁是抢跑的激进判据(硬杀/提前放弃,进程内无捕获),谁是优雅等待的内层超时(超时后走 except 分支做降级/发告警)」。正确梯度 = **激进的必须比优雅的慢**。
> 三层标记:L0=单请求 R2 HTTP(云上 600);L1=调用方对 `upload_r2.py` 的 Python subprocess 超时(被 except 捕获);L2=systemd `TimeoutStartSec`(**无进程内捕获的硬杀**)。

| 项 | 位置/值(实测) | 外层是谁(值,云上实测) | **是否真倒置** | 建议值 / 是否需动云上 unit | 风险 |
|---|---|---|---|---|---|
| ① | `gen_daily_brief.py:3116` L1=**120**;except→查 R2 新鲜度→⚠degrade / ✗critical | `trade-daily-brief.service` = **600**(10min) | **否(方向正确)**:120 是「优雅判据」(会被 except 捕获、走降级/告警),systemd 600 是「激进硬杀」backstop ⇒ 优雅的更快 = 正确。数字对 120 vs L0=600 属「预算偏紧」调优,不是倒置 | **保持 120**;若要抬,必须 systemd 同批抬(600→≥1200 或 0/∞);**仅当抬值才需动云上 unit** | 现状:上传>120s 走 degrade/critical(有新鲜度复核、绝不静默)可接受;被「顺手修」成 900 而 systemd 不动 = **真倒置**(硬杀抢在 except 前=告警与链路同亡);已加「勿擅改」注释防 |
| ② | `nextday_plan_generator.py:1181` L1=**300**;except→loud severe(刻意 fail-fast) | `trade-nextday-plan.service` = **600** | **否(方向正确)**,同 ① | 保持 300;抬值需 systemd 同批 | 同 ①(该处 loud fail-fast 属刻意设计,见 #217 §4.2) |
| ③(新发现) | `nextday_gap_check.py:358` L1=**300**;except(泛)→log+rc=1 上抛告警 | `trade-nextday-gap-check.service` = **600** | **否(方向正确)**,同 ① | 保持 300;抬值需 systemd 同批 | 同 ① |
| ④a | `fetch_news.py:722` L1=**180**(=120+等锁窗 60,#217 定调);except→✗ | `trade-fetch-news.service` = **600** | **否(方向正确)**(180<600,优雅先跑);180<L0 600 属「不委托子进程重试」的设计选择 | 保持 180;抬值需 systemd 同批 | 同 ①;另该单元「180+600=780>600」合成超预算问题并入 ⑤ |
| ④b | `overfit_monitor.py:1869` L1=**180**(同 #217 结构,`--skip-if-locked`) | `trade-overfit-monitor.service` = **0/∞**(实测 infinity) | **否**;且**无外层天花板** ⇒ 不存在系统级倒置面 | **可单独安全改、可立即做**:若用户想把语义从「等锁窗 180」改为「R2 墙钟 900」,仅改代码即可;保持 180 同样安全 | 无 systemd 天花板风险;唯一代价=语义取舍(改后慢故障等待变长) |
| ⑤ | `fetch_news.py:755` / `gen_daily_brief.py:3167` L1=**600**(staticdata_sync.sh;except→打「⚠ 超时」日志/告警) | `trade-fetch-news.service` = **600** / `trade-daily-brief.service` = **600** | **是,真倒置(零梯度,确定性抢跑)**:优雅=L1(Python,被 except 捕获);激进=L2(systemd SIGKILL,进程内无捕获)。systemd 计时自 unit 启动起算(**早于** sync 启动)⇒ 值相等时 systemd **必然**先杀 ⇒ 「✗ 超时」日志永不打出。且 fetch_news 串行预算 180+600=780>600,即便不等也先杀 | **正确修法=抬外层 systemd(600→900 或 0/∞),代码可不动**;**切勿**抬 Python 侧(600→900 = 让激进更早于优雅,反向加剧);若走「降 Python 侧」路线须 <600 留余量 | 现状:sync 挂死时**零告警**(日志来不及打)+ unit 被 SIGKILL;报告该行建议「(600→900 或 systemd 抬)」方向歧义,若被按「代码侧 600→900」执行=雪上加霜(**此为 §0 第 2 条**) |

### ①/② 正面回答(主控点名)

**按「激进/优雅」判据:①② 的「内层 120/300 < 外层 systemd 600」= 方向正确,不是倒置。**
- 这一对里,**优雅判据 = L1(120/300)**:它超时后会被 `except subprocess.TimeoutExpired` 捕获,走①的「查 R2 新鲜度→degrade/critical」②的「loud severe」——**优雅分支就是挂在 L1 上的**。**激进判据 = systemd 600**:SIGKILL,进程内无任何捕获。规则「激进的必须更慢」⇒ 要求 **L1 < systemd**,120/300 < 600 **满足** ⇒ 方向正确。
- 定性:`120/300` 不是「梯度问题」,而是「**内层预算是否偏紧**」(120s 够不够整包上传 / 是否愿意委托 upload_r2 自身重试)的调优问题。**不该按倒置去改**;唯一禁止动作 = 只把 L1 抬过 600(systemd 不动)——那才制造真倒置。
- 「真正的激进判据是不是别的」:**不是**。①②③ 的外层链(`run_daily_brief.sh` / `nextday_plan.sh` / `nextday_gap_check.sh`)均**无** shell `run_to`/`timeout` 看门狗(grep 实测空),systemd 是唯一外层。**真正需要修正方向的配对是 ⑤**(而非 ①②):⑤ 的激进(systemd 600)与优雅(Python 600)**值相等且 systemd 必先杀** ⇒ 那才是「优雅分支永不执行」的真倒置。

### 分批建议(基于实测,非推断)

- **可单独安全改、可立即做(外层无墙 systemd=0/∞)**:③ `fapi_bj_width_export.py`(**已改完**,infinity 天花板)、④b `overfit_monitor.py`(systemd=∞,若用户决定改语义)。
- **必须「代码 + 云上 unit 同批改」(或仅动云上 unit)**:① / ② / ③′ `nextday_gap_check.py` / ④a `fetch_news.py`——凡要抬 L1,必须同批抬 systemd;⑤ 方向相反:**只动云上 systemd**(600→900 或 0/∞),代码保持 600 不动即修好。

---

## 12. findings(≥80 才入册;均带 trace/verifier)

**F1(90)报告自称「无云上 ssh key ⇒ 改不了云上」不实**
- trace:diff_range=`docs/ops/217-223-threshold-copy-20261006.md` §0 拍板项1「为什么没改」行 + §7-2;linkage=不满足(与实施报告的事实陈述相关);user_request=N/A(origin: reviewer_own)
- verifier:command=`ls -la ~/tdsignal.pem`;expected=存在私有 key;observed=`-rw------- 1674B` 存在(且云上 ssh 读写可用,本轮已实测只读含 systemctl 取证)。影响:非决策级(拒改主链为真),但「改不了」误导上云改 unit 的可达性。
- over_engineering_findings:action=simplify(rationale=报告文字修订一行,`saves_lines`≈0)

**F2(90)拍板项 5 建议句方向歧义,可能被反向执行**
- trace:diff_range=同上 §0 拍板项5「建议:…(600→900 或 systemd 抬)」;linkage=不满足(直接影响用户拍板);user_request=N/A(origin: reviewer_own)
- verifier:command=`sed -n '350,362p' scripts/nextday_gap_check.py` + 云上 `systemctl show -p TimeoutStartUSec trade-fetch-news.service`(=10min);expected=修法方向唯一=抬 systemd;observed=报告句「600→900」可被读成「抬 Python 侧」⇒ 制造「激进 600 抢在优雅 900 前」。正确修法已写入 §11 表 ⑤ 行。
- over_engineering_findings:action=simplify(报告文字写死方向)

**另 4 个低分项(<80)已滤**:① mass 文案硬编码历史时点(10-04 04:07:20)长期成历史噪音(50,设计取舍);② 飞书 2000/TG 4096 既有截断机制(25,pre-existing 未触发,已在 §3 标出);③ 报告 §7-7 public-fund-daily 900 vs 600 文档旧值(25,pre-existing 且实施者已诚实自报);④ 文案「(见末句, 可忽略)」引用略绕(25,措辞 nitpick)。

## 13. 复算命令清单(可直接重跑)

```bash
# 判别维度/meta
git diff $(git merge-base origin/main feat/217-223-threshold-copy-20261006) feat/217-223-threshold-copy-20261006 -- scripts/upload_r2.py
# 全回归(CI 口径;树=分支 tip)
cd .claude/worktrees/agent-a2916e5d980cb8aee && /Users/linhuichen/code/trade/.venv/bin/python -m pytest -q scripts/tests/      # 248 passed, 1 skipped
/Users/linhuichen/code/trade/.venv/bin/python scripts/test_188_s06_sync_blindspot.py                                            # ALL_PASS
/Users/linhuichen/code/trade/.venv/bin/python scripts/test_193_r2_channel_coverage.py                                          # 40 PASS/0 FAIL
# 云上只读取证
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'systemctl show -p TimeoutStartUSec trade-fapi-daily.service trade-daily-brief.service trade-nextday-plan.service trade-nextday-gap-check.service trade-fetch-news.service trade-overfit-monitor.service; grep R2_UPLOAD_HTTP_TIMEOUT ~/code/trade-data/.env; cat ~/code/trade-data/data/.r2_standalone_keys.json'
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'grep -n "自动补传 114" ~/code/trade-data/data/logs/deploy_20261004_0205.log; python3 -c "import json;print(json.load(open(\"/home/ubuntu/code/trade-data-signal/data/notify_dedup.json\"))[\"verify_r2_mass_mismatch\"])"'
```

> 审查者声明:本评审全程未改仓库任何文件(报告落档除外)、未 commit/push、未执行任何业务脚本主体(§18 L50;test_188 的 s06 段经核 `PY=fakepy` 桩)、零真实通知外发(§18 L48,latest.md md5 前后一致)、零 R2/生产数据写。
