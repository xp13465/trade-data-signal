# W3 = #244(#241B)前端通知与邮件送达解耦 —— 独立审查报告

- 审查者: reviewer agent(fresh context,只读不改;独立工作区 `.claude/worktrees/agent-a35ce10353f58261d`)
- 日期: 2026-10-10
- 审查对象: 分支 `feat/alert-w3-decouple-1010`,tip `049ed2462`(实施提交 `573635a74` + merge origin/main `258aebac6`),base `1d946f685`
- 口径: 本报告全部结论 = 逐字读源码 / 真实生产数据 / 独立复跑所得,**未采信实施报告自述**;每条给可复现命令或文件路径。
- **零外发声明**: 本次审查**未产生任何真实邮件/飞书/告警**(沙箱先证生效 + 全量跑测 0 命中 + 零落库残留,证据 §E)。

## §0 merge 资格判定

**PASS —— 建议入 merge 队列**。12 项必查全 PASS,**0 条阻断 finding**;5 条低分(<80)非阻断项见 §F。

---

## §A 逐项结论表

| # | 必查项 | 结论 | 关键证据(可复现) |
|---|---|---|---|
| 1 | 诊断成立性(落签真与邮件送达解耦) | **PASS** | §A1 |
| 2 | 不回归 B 波(全失败仍可重试 / 重试成功不重复弹) | **PASS** | §A2 |
| 3 | 前端链零改动 + value 仍 ts 字符串 + 邮件状态独立文件 | **PASS** | §A3 |
| 4 | §18 L49 真实样本形态(无养绿) | **PASS** | §A4 |
| 5 | §18 L48 零真实外发(先证沙箱生效) | **PASS** | §A5 / §E |
| 6 | §18 L50 探针 static-only | **PASS** | §A6 |
| 7 | 独立复跑 pytest(CI 同款) | **PASS** | §A7 |
| 8 | 负控翻转 = 真语义翻转(非放宽) | **PASS** | §A8 |
| 9 | 数据产物原子写 / 并发幂等 | **PASS** | §A9 |
| 10 | 与 main/W1/W2 交互无冲突无打架 | **PASS** | §A10 |
| 11 | §23.3 举一反三两条「只报不改」判定 | **PASS** | §A11 |
| 12 | §23.7 冻结契约(无顺带改) | **PASS** | §A12 |

### §A1 诊断成立性 —— PASS

- `scripts/detect_intraday_anomaly.py:426-436`(`main`):`filter_and_record` 算去重 → `record_notified(_dedup_pending)` **无条件落签**(L433),邮件走 `send_or_stage(new_alerts)`(L435)。旧门控 `if send_alert(...): record_notified(...)` 已删。
  - 复现: `grep -n "if send_alert(" scripts/detect_intraday_anomaly.py` → 仅剩 L392(`retry_pending_emails` 内部)/ L401(`send_or_stage` 内部),**main 内不再有**。
- 「`anomaly_notified.json` = 前端浏览器通知唯一数据源」逐环核实(全仓 grep `anomaly_notified`):
  - 唯一写者 = `detect_intraday_anomaly.py`(DEDUP_FILE L39),无第二写者;
  - 读链 = `export_notifications.py:51 ANOMALY_NOTIFIED_PATH` → `:308 _load_anomalies_today`(date 口径 `%Y%m%d`,`:108 _today_str` / `:352` / `:383`)→ `notifications.json.anomalies` → `static-site/app.js:15128 data.anomalies.filter(a => a.tier === 'severe')`。
  - 生产实证(§B):线上 notifications.json 内含 41 条 anomalies 且 `ts` 为字符串。

### §A2 不回归 B 波 —— PASS(逐条给证据)

**① 邮件全渠道失败 ⇒ 前端源仍可得**:`test_07` 轮1 断言 `sign.exists()` + key 在 + value 是 str(我用真实生产文件另复核,§B)。代码侧落签在邮件之前(L433 先于 L435),邮件失败不影响文件。

**② 邮件全渠道失败 ⇒ 进暂存待下轮重试(绝不永久失报)**:轮1 断言 `pend.exists()` + 以 `alert_key` 入账 + **整 payload 含 `desc`**(不能由 key 重建,与 `send_alert` L313-315 的 body 组装一致);轮2 断言 `calls == 1`(**重试真的发生**)+ 账本保留。
- 重试入口在 `main()` 顶部 L409,**早于** `load_snapshot()` 的 `return 0`(L411-413)⇒ 重试不依赖今日快照,每轮都尝试。
- 唯一丢失路径 = `_write_email_pending` 抛错(磁盘满等),此时 fail-loud 打印 stderr、不另发告警(防台账元噪声,plan §5 不变式5);实施报告 §6 已诚实标注。**无阻断项**。

**③ 重试成功 ⇒ 清账 + 落签逐位不变(不重复弹前端)**:轮3 断言账本 `{}` + 落签结构 == 轮1。
- 代码侧逐字核 `retry_pending_emails`(L382-396):只 `_load_email_pending` / `send_alert` / `_write_email_pending`,**从不触碰 `DEDUP_FILE`** ⇒ 落签无写入路径(不止"内容相同")。

**④ 邮件口径不弱化**:同日同 key 仍最多一封(落签→`filter_and_record` 过滤),失败则暂存一份等待重试 ⇒ 无重复发送、无告警风暴。

### §A3 前端链零改动 —— PASS

- `git diff --stat 258aebac6 049ed2462 -- scripts/export_notifications.py static-site/app.js static-site/index.html` → **空**(逐字未变)。
- 实施提交 `git show --name-only 573635a74` = 仅 3 文件:`docs/ops/w3-decouple-20261010.md` + `scripts/detect_intraday_anomaly.py` + `scripts/tests/test_241_family_b_consign_20261009.py`。无 app.min.js / sw.js / 版本串改动(前端 bump 仍归 main-merge 机制 C,未被本分支触碰)。
- `anomaly_notified.json` 的 value **仍是 ts 字符串**:`record_notified`(L257-273)与 base 逐字一致,写 `{date: {key: iso_ts}}`;`test_07` 断言 `isinstance(value, str)`;真实生产文件复核见 §B。
- 邮件状态写**独立文件** `data/anomaly_email_pending.json`(L41):全仓 grep 只被 detect 与其测试引用,**无 export/前端读者**;且被 `data/.gitignore`(首行 `*`)忽略 —— `git check-ignore -v data/anomaly_email_pending.json` 命中 `data/.gitignore:1:*` ⇒ 不会被误提交进 git。

### §A4 §18 L49 真实样本形态 —— PASS(无「人造样本养绿」)

- **判据输入 = notify.py 真实打点行逐字**:`grep -n "已发出\|全部渠道未发出" scripts/notify.py` → L2540 `[notify] 汇总：已发出 {'/'.join(ok)}` / L2543 `[notify] 汇总：全部渠道未发出（...）`,与测试常量 `SUCCESS_GENERAL` / `FAIL_GENERAL`(test L76-77)一致(ok 非空时 join 出的正是 `email/feishu` 形态)。
- **真实对象「有没有该字段」而非「解析器能否解析」**(L49 核心判法):
  - `anomaly_notified.json` 真实文件 value 确为 **str** —— 实读本地生产文件 `data/anomaly_notified.json`(§B),不是只看解析结果;
  - 快照 fixture(`_snap_today`)的 `indices` 字段(code/name/pct_change)与真实生产链路一致 —— 该链路已在生产跑出 41 条真实异动(§B),不是纸上形态。
- 断言对象 = **文件是否落盘 / 内容是否变化**(行为级),不是「扫描某个可能恒空的集合」⇒ 不存在 L49 式「机制层空转被养绿」结构。

### §A5 §18 L48 零真实外发 —— PASS(先证沙箱生效,见 §E)

### §A6 §18 L50 探针 static-only —— PASS

- 本次审查全部手段 = grep / 读文件 / `git diff` / `inspect.getsource` 静态核对 + 跑单元测试;**未 source / exec 任何业务脚本主体**;未运行真实 `detect_intraday_anomaly.py`(§14 盘中链路);未碰生产数据。

### §A7 独立复跑 pytest —— PASS

```
$ cd <worktree> && PYTHONPATH=/tmp/rv_w3_guard /Users/linhuichen/code/trade/.venv/bin/python -m pytest -q scripts/tests/
639 passed, 2 skipped in 92.65s (0:01:32)
```
- 与实施自述 **逐字一致**(639 passed / 2 skipped)⇒ 独立复算通过。
- 命令与 CI 同款核过:`.github/workflows/ci.yml:123` = `python3 -m pytest -q scripts/tests/`;未用 `/usr/local/bin/python3`,未 `| tail` 吞退出码。

### §A8 负控翻转 = 真语义翻转 —— PASS(不是放宽)

- 改前(`573635a74^`,test L279-285):主张「全渠道失败 ⇒ **不得**落签(否则同日不再补发 = 永久丢失)」+ 下轮重试。
- 改后:主张「全渠道失败 ⇒ **已落签(前端源可得)** + 邮件进暂存待重试」,断言**更多更严**(4 条 → 13 条):落签存在 / value 必须 str / 暂存按 alert_key / 整 payload 含 desc / 轮2 重试发生且账本保留 / 落签结构不变 / 轮3 清账 / 落签结构不变。
- **判别力反事实**(三个方向都会被新用例逮到):①若落签又挂回邮件送达 → 轮1 `sign.exists()` FAIL;②若暂存但不重试 → 轮2 `calls == 1` FAIL;③若重试顺手重写落签 → 轮2/3 结构比对 FAIL。
- B 波核心不变式(「下轮必重试」)在新用例里**被保留**(轮2 `calls == 1`),不是被删。

### §A9 原子写 / 并发幂等 —— PASS

- `_write_email_pending`(L361-367) → `util_atomic.atomic_write_json`(同目录 `.tmp{pid.rand}` + `fchmod 0644` + write/flush/fsync + `os.replace`,finally 清 tmp)⇒ 读侧「要么旧完整要么新完整」,符合 §22。
- 并发:唯一调用方 = `scripts/intraday_snapshot.sh:216`(全仓 grep),该脚本持 `/tmp/trade_intraday_snapshot.lock`(`with_lock.py --nb`,L52)⇒ 单写者、无并发双写。
- 幂等:`stage_email_pending` 按 `alert_key` 覆盖入账(同 key 不重复),`retry_pending_emails` 空账 no-op。
- 边界(诚实标注):读-改-写三步的原子性由脚本层锁保证(非锁内员);手动并发跑极端情况下可能 last-write-wins —— 与既有 `DEDUP_FILE` 同款模式,**非本波新增风险**。

### §A10 与 main / W1 / W2 交互 —— PASS

- **文件面**:实施提交未碰 `scripts/notify.py`(W1 冻结面)/ `scripts/notify_sent.py`(W2);merge 提交 `049ed2462` 相对 `258aebac6` 只带这 3 个文件(无冲突解决损坏,§23.11)。
- **判据面**:仍复用 `notify_sent`(W2 逐字未改的唯一实现)。**为何两态够用(独立复核,非采信自述)**:`notify.py:2527` 的抑制分支门控在 `args.dedup_key`,而 detect 的 notify 调用**不带 `--dedup-key`** ⇒ 该路线**不存在 suppressed 态**(W2 三态前提不成立)。偏差方向 **fail-safe**(若判 False 只会暂存重试,不会误清账丢告警),实施报告 §6 已写明,判**可接受**。
- **反向假阳性(跨波)专查**:若某行在「未真发出」时含「已发出」/「路由完成：」,`notify_sent` 会误判送达 ⇒ W3 误清账 ⇒ 丢邮件。实查:全 `notify.py` 含「已发出」仅 L2392 / L2540 两行,均门控 `ok` 非空;W1 新增台账行文案 =「台账登记」/「台账写入失败(不影响发送)」,**不含**两式判据串;「路由完成：」三处(L2368 tier / L2462 r7 / L2514 196③)均需 dedup_key 特定值。⇒ 对本路线判据恒准。

### §A11 §23.3 举一反三两条「只报不改」复核 —— PASS(两条判定均正确)

1. `static-site/app.js:14765` 注释(W3 后是否该改):**只报不改正确** —— 该行属前端「三层去重」说明段(L14759-14765),改动它需重建 min + bump 版本串,属另一波;且任务硬要求④ = 前端链零改动 + §23.7 冻结面。
   - **但「语义已过时」的说法偏强**:该行说「后端 signal_notified/anomaly_notified 已做**邮件去重**」——落签后当日同 key 仍不会再发邮件(去重照旧成立),变化的是「落签不再等价于邮件已送达」。建议主控/用户按「措辞精度」而非「错误」处理(可随任一次前端发版顺手订正)。
2. `scripts/export_notifications.py:50 SIGNAL_NOTIFIED_PATH`:死定义判定**成立** —— `grep -rn SIGNAL_NOTIFIED_PATH` 全仓仅 1 处命中 = 定义行自身。删除属越范围(§23.7),只报不改正确。
3. 补充复核「同类错误面只有一处」这一结论方向:全仓 grep 无第二写者、无第二「前端展示源被门控在邮件送达后」的站点,方向成立。

### §A12 §23.7 冻结契约(无顺带改) —— PASS

除任务点名行为(落签门控解耦 + 邮件单独记账)外,**diff 内无别的已上线行为改动**。逐条核:
- `filter_and_record`:`git diff` 只动 docstring,函数体逐字未变;
- `record_notified`:只动 docstring,函数体(#132 写失败告警路径)完整保留;
- `send_alert`:**逐字未改**(判据 / 文案 / `timeout=60` 均同 base);
- 其余 = 纯新增 helper + `main` 门控重排;`_MIN_ASSERTIONS` 36→90 属测试自护(防收集异常假绿);
- 报告/文档(3 处失真 docstring)订正属「文档与实现一致」,非行为改动。

---

## §B 生产数据面复核(真实文件 + 线上,非自述)

1. 本地真实生产形态文件 `data/anomaly_notified.json`(2026-09-11 落地):
   `{"20260911": {"breakout_down|指数|上证指数": "2026-09-11T09:27:53.953181", "breakout_down|指数|深证成指": "..."}}`
   ⇒ key = `type|kind|name`,**value = str(ts)**,与 W3 保持的契约一致。
2. 线上 `curl -s -A <browser UA> https://ss.fx8.store/data/notifications.json`(禁 -v/-i):`date=20261009`、`generated_at=2026-10-09 20:40:22`、`signals=26`、`anomalies=41`(全部带 str `ts`;tier: severe 40 / strong 1)、`alerts=2`
   ⇒ **端到端链路生产在跑**:`anomaly_notified.json → export_notifications(同 REPO 树)→ notifications.json.anomalies → app.js:15128`。
3. 今日 2026-10-10 = **星期六**(非交易日)⇒ 线上 date 停在 20261009 属正常,不是停摆;且 `intraday_snapshot.sh` L58-66 有交易日闸门(非交易日默认跳过)⇒ 不会在休市日误触发「邮件暂存重试」。

---

## §C smoke(docs/smoke-checklist.md P0-12 通知面板,相关项)

| 项 | 规则 | 实测 | 判定 |
|---|---|---|---|
| C19 | `notifications.json` `date` == 今日或最近交易日 | `20261009`(= 最近交易日,今日周六) | PASS |
| C20 | `signals` 是数组 | list,len 26 | PASS |
| P0-12 | 数据层 curl 通 + anomalies 有值 | 41 条 | PASS |

本次改动**不动 notifications.json 的生成逻辑**(export 零改动)⇒ 无新增回归面;唯一行为差异 = 邮件通道故障时,前端源不再一起缺失(用户可见效果 = 邮件挂时前端仍弹 severe)。

---

## §D 判定汇总(证据强度)

| 断言 | 证据类型 | 强度 |
|---|---|---|
| 落签与邮件送达解耦 | 源码逐字 + 旧门控已删 grep + 行为用例 | 强(直接) |
| 全失败仍可重试 / 不永久失报 | 用例 3 轮 + 只有一条丢信路径(已诚实标注) | 强 |
| 重试成功不重复弹前端 | 用例结构比对 + 重试路径不触 DEDUP_FILE(代码) | 强 |
| 前端链零改动 | `git diff --stat` 空 + 提交文件清单 | 强 |
| value 仍 ts 字符串 | 真实文件 + 线上 41 条 | 强 |
| 零外发 | 沙箱先证生效 + 跑测 0 命中 + 零落库 | 强 |
| 独立 pytest 复算 | 639 passed / 2 skipped(实测) | 强 |
| 跨波无打架 | notify.py 判据行逐条 grep + dedup_key 门控核 | 强 |

**诚实缺口**:未在**生产**(云上)实跑验证「邮件挂 + 前端弹」的端到端场景 —— 需人为断邮件通道,不在只读审查范围;建议主控按 §0 生产实证口径或后续观察项跟踪(可选:人工用 `NOTIFY` 桩/临时改 notify 配置做一次演练)。

---

## §E 零外发证据(§18 L48)与本次审查的自我约束

1. **沙箱先证生效**:新建 `/tmp/rv_w3_guard/sitecustomize.py`(拦 `urllib.request.urlopen` / `smtplib.SMTP` / `smtplib.SMTP_SSL`,与项目 `scripts/tests/_zero_outbound.py` 同一组出口),**先期实测**:三出口在①本进程 ②子进程(`PYTHONPATH` 继承)分别 raise `[REVIEW-GUARD]` ⇒ 沙箱判定有效(不是「应该有」)。
2. **跑测 0 命中**:全量 pytest 日志 `grep -c "[REVIEW-GUARD]"` = **0** ⇒ 本次跑测无任何真实外发(含子进程)。
3. **零落库**:主仓 `data/` 近 45 分钟零文件被改;`data/anomaly_email_pending.json` 未生成;跑测后 worktree `git status --porcelain` 仍 **clean**。
4. **诚实标注(避免误读)**:审查时间窗内 `data/alerts/alert_ledger.jsonl` 新增 2 行(`source=feishu_chat_hook.py`, `group=agent_done`, subject `🤖 主会话`, 01:34:16 / 01:37:33)—— 这是 **harness 的 agent-done 飞书 hook** 触发(独立进程),不是本审查 pytest 进程(沙箱会拦其外发);与本波无关,仅记录。
5. 未跑真实业务脚本(§14 盘中链路 `detect_intraday_anomaly.py`)、未 `find /`、未裸跑 pip/npm、未 Docker、未 `curl -v/-i`、token 未进 argv。
6. **残留后台任务自查**:本次未出现 `moved to the background (ID:`;`nohup` 起的 pytest 已正常退出(`pgrep -fl pytest` 空)⇒ **无残留后台任务**。

---

## §F 低分项(<80,按 role-reviewer §10.2 不入正式 finding,列此供实施方/主控取舍;共 5 条,0 阻断)

1. **(60)`:332-333` stderr 文案已失真**:`send_alert` 失败分支打印「告警邮件**未确认送达**(rc=..., **下轮重试不落去重签**)」—— W3 后落签**已落**,重试也不靠"不落签"而靠暂存账本;该行是**本次改动使之失真**的第 4 处文案(实施方只订正了 3 处)。建议顺手改一行文案(零逻辑),或在 W4 一并处理。复现:`sed -n '331,334p' scripts/detect_intraday_anomaly.py`(逐字与 base 相同)。
2. **(40)报告口径小偏差**:实施报告 §2 写重试「随 intraday_snapshot.sh 30min 节奏」—— 实际 `scripts/intraday_snapshot.sh` 头部注释 = 盘中每 **10 分钟** + `docs/signal-finalize-time.md:113`(`trade-intraday-snapshot` 每10min + 15:02/15:35/20:35)⇒ 重试比报告所述**更频繁**(方向无害)。溯源:`detect_intraday_anomaly.py` 模块 docstring 的「30分钟节奏」是 base 既有文字(非本波引入)。
3. **(25)`test_07` 的「逐位不变」实为解析结构相等**(`json.loads(a) == json.loads(b)`),不能区分「内容相同但被重写」;因重试路径根本无写签代码,实践等价,不构成缺口。
4. **(25)`send_or_stage([])`** 会走 `stage_email_pending([])` 并对账本做一次无效写(测试 L401 只断言返回 False);生产无空列表调用路径(受 `if new_alerts:` 保护),纯 nitpick。
5. **(25)force 模式边界**:非交易日人工 `intraday_snapshot.sh force` 时,`detect` 会执行顶部重试(默认路径被 L58-66 交易日闸门拦住)⇒ 极端情况下休市日可能收到「补发」异动邮件。需人为 force 才可能,记为已知边界。

---

## §G 复现命令清单(全部只读)

```bash
# 改动面
git -C <repo> diff --stat 258aebac6 049ed2462
git -C <repo> show --name-only 573635a74
git -C <repo> diff --stat 258aebac6 049ed2462 -- scripts/export_notifications.py static-site/app.js

# 门控与遗留
grep -n "if send_alert(" scripts/detect_intraday_anomaly.py
sed -n '407,436p' scripts/detect_intraday_anomaly.py

# 判据真实性
grep -n "已发出\|全部渠道未发出" scripts/notify.py
sed -n '2525,2545p' scripts/notify.py
grep -rn "SIGNAL_NOTIFIED_PATH" scripts static-site

# 状态文件隔离 / 忽略
grep -rn "anomaly_email_pending" scripts static-site
git check-ignore -v data/anomaly_email_pending.json

# 独立复跑(CI 同款)
PYTHONPATH=/tmp/rv_w3_guard /Users/linhuichen/code/trade/.venv/bin/python -m pytest -q scripts/tests/

# 生产数据面
curl -s -A "<browser UA>" https://ss.fx8.store/data/notifications.json
```
