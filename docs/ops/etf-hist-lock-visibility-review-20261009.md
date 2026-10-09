# #239 止血步独立审查报告 —— 等锁可见性(2026-10-09)

> 角色:reviewer agent(fresh context,独立于实施)。等级:B 级(逻辑分支 + 生产上传核心脚本)。
> 审查对象:分支 `worktree-agent-a17c0cad8ae674069`(base=`origin/main` `16dfee5aa`)
> - `88fecb1d7` 代码+测试(2 文件, +124/-1)· `484ad26bd` 报告(+165)
> 全文对象:`docs/ops/etf-hist-lock-visibility-mitigation-20261009.md`(分支上)
> 方法:全部只读(`git diff/show/log` + 临时树重跑 + 正则机检 + 变异测试);未切分支、未 commit。
> 全文落档:本文件(审查结论各维度均附可复现命令与实测值)。

## 0. 总评

**建议 PASS / 可 merge**(无阻断项)。「纯可见性、不动锁语义」的自述经独立实测成立:
两版(origin/main vs 分支)在**同镜头**下 rc、耗时、非心跳 stderr **逐字一致**,唯一差异 = 心跳行数 0→2。
新增输出对**全部已识别消费方**均不构成误判(逐消费方机检 + 正则阳性对照)。
两条非阻断建议见 §3(F1 报告措辞限定 / F2 上线后观察与前置假设机检)。

## 1. 逐维度结论

### 维度 1 · 纯可见性反证 —— **PASS**

diff 逐行核对(仅 4 处非注释改动):
| 位置 | 改动 | 判定 |
|---|---|---|
| L3859-3863 | 新增常量 `_R2_LOCK_HEARTBEAT_SECS = 30` | 纯新增,无消费者 |
| L3879-3881 | docstring 补段 | 注释 |
| L3936-3938 | `wait_started_at`/`last_beat_at` 初始化(循环前,仅计时) | 纯新增变量 |
| L3957 | `if time.time() >= deadline:` → `now = time.time(); if now >= deadline:` | **等价**:同一调用点同一时刻取值;`>=` 边界(刚好等于 deadline)语义不变;`now` 仅在该点之后使用,skip 分支(continue/return)先于该行,不受影响 |
| L3966-3972 | 排队分支 `sleep(2)` 前心跳 print(`flush=True`) | 纯输出 |

行为等价实测(归一化 diff,命令与实测见 §2-证据1):
```
rc=SystemExit(code=1)   elapsed=6.0    ← 两版逐字相同
✗ R2 上传锁 <TMP>/l.lock 排队等待超 6s ...(fail-closed ...)  ← 两版逐字相同
HEARTBEATS=0(main) → 2(branch)                              ← 唯一差异
```
`sleep(2)` 间隔 / `deadline` / `R2_UPLOAD_LOCK_TIMEOUT` / 拿锁顺序 / flock 语义 / 异常路径 **均未动**(diff 内无其它 hunk);
`r2_upload_async.sh` 一行未改(`git diff origin/main...<branch> -- scripts/r2_upload_async.sh` 空输出);
未加信号处理 / 未加新 env 开关(心跳间隔是模块常量,已核 `grep -n "_R2_LOCK_HEARTBEAT_SECS"` 无 env 读取)。

### 维度 2 · 新增 stderr 是否污染下游解析 —— **PASS**(本次头号风险,逐消费方查清)

心跳行原文:`⏳ 等待 R2 上传锁 30s(上限 7300s, 持锁进程可用 lsof /tmp/trade_r2_upload.lock 排查)`

**机检**:从 `scripts/gen_schedule_stats.py` AST 抽取全部 `*_RE` 正则原文编译执行,对心跳行(30s/7200s 两形态)逐一测试 ⇒
`ANOMALY_RE / MARKER_ANOMALY_RE / TRANSIENT_WARN_LINE_RE / UPLOAD_KEY_RE / PUSH_FAIL_RE / PUSH_SUCCESS_RE / FINALIZER_NOISE_START_RE / MP_*` **全部 no-match**;
`r2_upload_async.sh` 的两条 `grep -Eo` 判据 `\[[0-9]+/[0-9]+\]`、`\([0-9]+B\)` 亦 **no-match**(心跳不含方括号、`(上限 7300s` 不匹配 `\([0-9]+B\)`)。
**阳性对照**(防"全 no-match"是假绿):同一批正则喂真实故障样本 `✗ R2 上传失败(rc=1)` / `Traceback (most recent call last):` / `FATAL x` / `⚠ PUT data/boot.json attempt 1 失败(...)` 均 **HIT** ⇒ 判据有效。

逐消费方结论:
| 消费方 | 判据形态 | 会不会误伤 |
|---|---|---|
| `r2_upload_async.sh` L139(15 通道) | tmp_log mtime 停滞 900s → kill | **有意受益**(刷新 mtime 即本改动目的) |
| 同上 L161/L164(低速判据) | `[N/M]` 与 `(NNNB)` 累加 | 不匹配;且等锁期 `_batch_total=0` ⇒ 低速判据本就不触发 |
| 同上 L184 | `tail -1` 作为通道收尾行 tee 入主 LOG | 心跳只在等锁期,业务收尾仍为末行;极端(等锁期被外部信号杀)末行为心跳,亦不含异常关键词 |
| 同上 `_dump_kill_tail` / `_vc_tail`(告警正文) | tail-30/tail-8 内联 | 仅在**真 kill/真缺口**告警时出现心跳,信息更丰富;告警语义不变(非误报) |
| `gen_schedule_stats.scan_log_anomaly` | 窗口内 ANOMALY_RE + `SKIPPED_LOCKED` 计数 | 不命中;计数不含心跳 |
| `scan_marker_log`(fetch_news/gen_daily_brief) | tail 窗口 + MARKER_ANOMALY_RE | 不命中;且两链走 `--skip-if-locked`(无心跳) |
| `push_schedule_stats.sh` L84 | `grep -q "SKIPPED_LOCKED"` | 不匹配(且该链 skip 分支无心跳) |
| `overfit_monitor.py` L1993 | `"SKIPPED_LOCKED" in (stdout+stderr)` | 不匹配 |
| `staticdata_backup_async.sh` L195 | `grep -q "已被占用"` | 心跳不含该串 |
| `nextday_plan_generator.py` | 仅 rc + 失败时打 stderr 尾部 | 无解析 |
| intraday/turnover/s06/gold_night/backup_db/pf_score/fund_nav_async/update_all | 只看退出码 | 无解析 |
| `alert_denoise_rules.r5` | 匹配**告警文本**含「R2 上传」(拥堵聚合) | 与心跳无关(心跳不入告警主体) |

另:全仓无任何消费方以「有输出/无输出」本身作失败判据(`grep` 未发现 `-n "$(cmd 2>&1)"` 类形态)。

### 维度 3 · 心跳频率合理性 —— **PASS**

- 梯度:30s vs 生产 mtime 判据 900s = **30x**(mtime 最大陈旧 30s,远小于 900s 阈值);且 30s **远大于** watchdog 5s 采样周期,采样必落在新鲜窗口内。
- 日志量上限:`R2_UPLOAD_LOCK_TIMEOUT` 默认 7300s ⇒ 单通道最多 ≈ **243 行 ≈ 22KB**;跨通道(15 通道)理论 < 0.4MB/轮,无膨胀风险。
- 覆盖边界:心跳只覆盖**排队分支**;`--skip-if-locked` 有界重试窗口(默认 60s)仍静默 —— 60s ≪ 900s,零误杀风险,且 #217① 明示「窗口内静默重试」,不动=正确(报告 §4 已列)。
- 生产 stall 取值:全仓 grep `R2_UPLOAD_STALL_SECS` 无任何脚本/.env 覆盖(= 默认 900);云上 `.env` 依据 #217 审查(2026-10-06 云上实测)仅设 `R2_UPLOAD_HTTP_TIMEOUT=600`。
  ⚠ 本次**未**独立 ssh 复核(本机无 `~/.ssh/tdsignal.pem`,`Permission denied (publickey)`)⇒ 该一条采信既有文档记录,标注「未复测」。

### 维度 4 · 测试有效性 —— **PASS**(红-绿-变异三段实测)

| 实验 | 命令要点 | 实测 |
|---|---|---|
| 绿 | 分支码 + 新测试,临时树 `/tmp/239_pass` | **4 passed**(4.14s) |
| 红 | origin/main 版 `upload_r2.py` + 新测试 | **4 failed**(常量缺失,收集后即挂) |
| 变异 | 分支码**仅删心跳 print 块**(保留常量,临时树) | **仅 `test_heartbeat_prints_during_queue_wait` FAIL**,失败点为断言 `assert '等待 R2 上传锁' in err`(实得仅有 fail-closed 行);其余 3 passed |

⇒ ①样本是**真实生产形态**(真 flock 争用、真函数、真 env 键、真消息串),非人工构造假样本;
②断言判别力真实(变异即红),不存在「假样本也能过」的洞;③test2/3 为反证(锁空闲/skip 分支零心跳),test4 为常量守护(30 且 `30*10 < 900`)。
备注:红实验在旧码上先因常量缺失报 AttributeError,「断言层面」的红由变异实验补齐 —— 两段证据都保留在案(建议报告保留该变异证据,单靠红实验不足以证明断言本身有效)。

### 维度 5 · `test_212::test_e` 归因 —— **PASS(自述正确,独立复现)**

- 未提交态(HEAD 版已含 #212 `_channel_on_fail`,工作区有改动)⇒ **FAIL:`assert 27 == 0`**(`test_212_upload_onfail_loud_pytest.py:386`)。
- 提交态(HEAD==工作区)⇒ **SKIP**:「已提交态(HEAD==工作区): 改前版不可得, 跳过静态对照」。
- 归因成立:该例前提「HEAD 版不含 `_channel_on_fail`」只在 #212 **自身未提交期**成立;#212 合入 main 后,任何 `upload_r2.py` 的未提交改动都会触发它 —— **既有脆弱点,非本次引入**(本次未顺手改 = 符合派单禁「顺手优化」)。

### 维度 6 · 「单点修即全消费方受益」—— **PASS(带 F1 措辞限定)**

- 锁在 `__main__` 统一入口获取(`/tmp/239_upload_r2.py:4006-4008`):除 `{list,delete,download-db,clean-data-backup,upload}` 外**全部命令持锁** ⇒ 消费方不各自实现等锁。
- `r2_upload_async.sh` 通道清单(15 条 `run_r2_upload`,含本次事故通道 `upload-etf-hist` L210)**无一带 `--skip-if-locked`** ⇒ 全部走排队分支、全部受益(免误杀)。
- B 类直调脚本逐个核对:`turnover_backfill / s06_snapshot / gold_night / backup_db / fund_nav_upload_async / pf_score_daily / update_all / etf_national_team_backfill / kelly_intraday_rerun / nextday_plan_generator / staticdata_backup_async` 均无 skip flag ⇒ 走排队分支;`overfit_monitor / push_schedule_stats / intraday 15:35~20:30 轮` 走 skip 分支(≤60s,零误杀风险,报告已列)。
- **漏项 2 类**(均已在报告 §4 单列,非静默):① `with_lock.py` 阻塞等锁(deploy.lock 等另一把锁/另一批链,#23.7 不宜裹入,建议单列)✓ 合理;
  ② **`run_to N` 总时长型消费方**(见 F1)—— 它们的 kill 判据是 GNU `timeout`(总时长,非 mtime),心跳**只给可见性、不给免杀**。

### 维度 7 · §23.7 冻结契约 —— **留意但可放行**

- 触及生产脚本 = 触及已发布功能;新增输出 + **改变了「等锁 >900s 被停滞判据 kill」这一生产结局**(这正是止血目的)。
- 影响面精算:等锁分支新增 2 行/分钟 stderr(单通道 ≤243 行/轮);停滞判据不再误杀健康等锁进程;真卡死(如业务零输出)判别力不变(实施 harness Case B + 本次消费方机检双重佐证)。
- 已披露:报告 §8 诚实标注「不治本,长持锁者仍在,等锁通道仍可能等满 7300s」。
- 建议:merge 前主控向用户点明「本次动的是生产上传核心脚本」;上线后首夜看一次 r2_upload_async 日志(见 F2)。

### 维度 8 · 报告「未做项」定级 —— **PASS**

| 未做项 | 报告定级 | 审查判定 |
|---|---|---|
| §7-② 梯度成文/「心跳存在」作看门狗前置假设(机检) | ⛔ 未做(派单禁动 kill 判据/梯度) | 合理;但见 F2,建议不无限期推迟 |
| §7-③ 长持锁者治本(分片/分锁) | ⛔ 只列不做(派单指定) | 合理(根因级,应单独立项) |
| §7-④ `verify_channels` L3826「force_full 未完成」文案纠偏 | ⛔ 未做,**留主控定级** | **定级正确**:属「顺手优化」(派单明令禁止)+ 涉告警文案一致性(§23.10),应单列小任务;且它**不消误杀**,与止血无关 |
| §7-⑤ fund-nav marker 残留 + `r2_upload_trigger_fail` 误报降噪 | ⛔ 未做 | 合理(另一批) |
| `with_lock.py` 阻塞等锁静默 | ⛔ 单列 | 合理(另锁另链,§23.7) |
| 未改 `pending-features-index.md` #239 状态列 | 交给主控 | 合理(避免并发覆盖,§23.11;已核:分支 3 文件中无该索引) |

## 2. 证据(可复现)

**证据1 · 两版行为等价(归一化 diff)**:临时树分别放 `origin/main` 版与分支版 `upload_r2.py` + 同一 dump 测试(真锁被占、`R2_UPLOAD_LOCK_TIMEOUT=6`、分支版把心跳间隔 monkeypatch 成 2s),输出路径归一化后 diff ⇒ 唯一差异 `HEARTBEATS=0 → 2`,rc/耗时/其它 stderr 逐字相同(§1-维度1 表格实测值)。

**证据2 · 消费方正则机检**:AST 抽取 `gen_schedule_stats` 全部正则原文 + 手工取 `r2_upload_async.sh` 两条 `-Eo` 判据,对心跳行两形态测 no-match,并对真实故障样本测 HIT(阳性对照)。

**证据3 · 红-绿-变异三段**:`/tmp/239_rbg`(旧码=4 failed)、`/tmp/239_pass`(分支=4 passed)、`/tmp/239_mut`(仅删心跳 print=1 failed 3 passed,失败点=心跳断言)。

**证据4 · 存量回归(upload_r2 相关测试,分支版脚本,临时树 farm)**:`test_219/test_223×3/test_193/test_212/test_239` ⇒ **56 passed + 1 skipped**(skip=test_212 test_e 无 git 环境;**全部 scripts/tests 相关用例已覆盖**)。注:实施报告称「全量 443 passed / 2 skipped」,**本次未复跑全量**(临时树无完整仓上下文),仅独立复跑了与 `upload_r2` 相关的全部用例 —— 全量数字仍属实施自述,标注「部分独立验证」。

**证据5 · test_212::test_e 归因**:临时 git 仓复现未提交态 `assert 27 == 0` FAIL、提交态 SKIP。

## 3. 需修项 / 建议(均非阻断)

**F1(建议 · 报告措辞限定,非代码)· `run_to` 总时长型消费方不受心跳保护**
- trace:diff_range = 分支报告 `docs/ops/etf-hist-lock-visibility-mitigation-20261009.md` §4「一处改动即令 A/B 类全部消费方获得等锁可见性」;linkage=uncertain(措辞精度);user_request=派单维度6「是否有走别的等锁路径的消费方漏掉」
- verifier:command=`grep -n -A 10 "^run_to()" scripts/s06_snapshot.sh`;expected=区分 mtime 判据 vs 总时长判据;observed=`run_to` = GNU `timeout`/`gtimeout`/perl alarm(**总时长**),故 `scripts/s06_snapshot.sh:133,161` 与 `scripts/turnover_backfill.sh:145,148` 的 `run_to 900` 等锁超 900s 仍被 SIGTERM 杀掉 —— 心跳只给它们可见性,不给免杀
- 建议:报告 §4 把「A/B 类全部受益」限定为「**mtime 型看门狗(r2_upload_async.sh 15 通道)免误杀;run_to 总时长型(2 脚本 4 调用点)仅获可见性**」;这两处是否要放宽属另一决策(不动=现状)。
- over_engineering:`action=n/a(纯措辞)`;`saves_lines=0`;`rationale=仅文档一行限定`

**F2(建议 · 上线后跟进)**
- ① 上线后**首夜巡检**(E30 精神):看 `r2_upload_async` 日志是否出现心跳行、被误杀数是否归零;② 报告 §7-② 的「心跳存在=看门狗前置假设」建议尽快做成机检(现在该假设只是**沉默契约**:若未来心跳被删/间隔被调大 ≥stall,看门狗会静默回到误杀,而无人报警)。定级:建议(非本次 merge 条件)。

**F3(低分滤除,<80,列此备查)**:① 心跳只覆盖排队分支 —— 若未来有人把 `R2_UPLOAD_SKIP_RETRY_SECS` 设到 >900,skip 分支静默期会重新暴露误杀(当前全仓无此配置(云上按 #217 记录亦未设,本次未独立复核));② 间隔不变量只对默认 900 做了守护(`30*10<900`),对「非云上 HTTP=30 环境下显式设 stall=33~60」这种薄梯度无守护。两条当前暴露为零,滤除不入正式 finding,建议并入 F2-② 的机检设计一起覆盖。

## 4. 未测/未复核项(诚实标注)

- 云上 `.env` 超时键:**未独立 ssh 复核**(本机无 `~/.ssh/tdsignal.pem`,`Permission denied (publickey)`)⇒ `R2_UPLOAD_STALL_SECS` 未设=采信 #217 审查文档(2026-10-06 云上实测记录)+ 全仓 grep 无覆盖。
- 存量全量测试(443 passed):**未复跑**,仅复跑 upload_r2 相关全部用例(见证据4)。
- 生产环境实跑:未做(本步为可见性机制;判据行为由两版对照 + 变异实验覆盖)。
- 低分滤除项另有 **2 条**(<80,见 F3),已按 §10.2 记录在上文备查。

## 5. merge 建议

**PASS,可 merge**(分支 `worktree-agent-a17c0cad8ae674069`,`88fecb1d7` + `484ad26bd`)。
无阻断 finding;F1 建议随 merge 前顺手在报告加一行措辞限定,F2 作为上线后跟进项登记即可。
