# #224 僵尸巡检 cron 机检误判根治(判定纳入 job 生命周期)

- 日期:2026-10-06(用户 22:5x 拍板「都开」)
- 分支:`feat/224-zombie-cron-gate-20261006`(只推 feat,main 由主控 `main-merge.sh` 合)
- base commit:`ecb5243ba78cb83799ae6aeaba6fc3228f445daa`;合前已 rebase `origin/main 24a16e6bd`
- 改动文件:
  - `scripts/check_task_state.py`(C 维度重写 + 新增 cron 解析/生命周期判据)
  - `scripts/tests/test_224_zombie_cron_gate.py`(新增,15 用例)
  - `docs/pending-features-index.md`(#224 状态列:待拍板 → 已实施)
  - 本报告

## 1. 规则复述(修前,逐行读码确认)

判定对象:`.claude/scheduled_tasks.json` 的 `tasks[]` 里满足
`"巡检兜底" in prompt or "agent-progress" in prompt` 的 job(其余 job 一律跳过)。

进度文件路径解析(`PROGRESS_PATH_RE` = `/tmp/agent-progress-([A-Za-z0-9._-]+)\.md` +
`PATROL_NAME_RE` = `巡检兜底\(([^)]+)\)`):两个正则各自抓名 → 拼成 `/tmp/agent-progress-<name>.md`。
两正则都抓不到 → `warn`「未含可解析路径」(非 FAIL)。

FAIL 的**确切触发条件**(修前):
1. 上述某个进度文件**不存在** ⇒ `detail_fail`(「疑似僵尸(任务已结束 cron 未删)」);
2. 文件存在但 `mtime` 距今 > `ZOMBIE_CRON_STALE_DAYS = 7` 天 ⇒ `detail_fail`(「mtime 已 N 天未更新」)。

即:**判定完全是「文件在不在盘上 / 新不新鲜」,与 job 的时点、生命周期毫无关系**。

退出码路径:`detail_fail` 非空 ⇒ `CheckResult.FAIL`;`determine_exit_code` → 有 FAIL 返回 **1**
(有 warn 且 `--strict` 才返回 2)。`--deploy-mode` 只影响调用方的处置,**不改脚本自身判定逻辑**。

两种 flag 的语义(`scripts/check_task_state.py:main()`):
- `--deploy-mode`:deploy 链专用传入(`scripts/deploy.sh:341` `"$GIT_REPO/scripts/check_task_state.py" --repo "$GIT_REPO" --deploy-mode`),
  只看**退出码**:非 0 ⇒ `deploy.sh` 打印「终止部署」+ **真发一条 severe 告警**
  (dedup-key `deploy_check_task_state_fail`,6h 窗)并 `exit`。
- `--skip-zombie-crons`:**整段不跑 C 维度**(只跑 A/B),CI 用
  (`.github/workflows/ci.yml:107` `python3 scripts/check_task_state.py --repo "$GITHUB_WORKSPACE" --deploy-mode --skip-zombie-crons`),
  因为 CI runner 没有本机 `/tmp/agent-progress-*.md`。本次改动**未动这两个 flag 的位置与威力**。

## 2. 病灶:两次真事故

- **事故一(一次性派单 cron)**:主控给 10-08/10-30 排的一次性 cron,其 prompt 按 §0.2 三件套
  **必然写到进度文件路径与兜底 cron 字样** ⇒ 被判为巡检 cron ⇒ 而进度文件**要触发日才存在**
  ⇒ 提前数天**恒 FAIL** ⇒ ①阻断生产部署 ②`deploy.sh` 真发 severe 告警。
- **事故二(巡检 cron 冷启动空窗)**:新建兜底 cron 后、**agent 写下第一条进度之前的数分钟**,
  进度文件同样不存在 ⇒ 又一次 FAIL(当时靠「主控预建占位进度文件」应急绕过)。

两次实测影响均为零(窗口内云上无 deploy 跑),但每次派活都可能引爆 ⇒ 根因 = **把「进度文件不存在」
一律当僵尸,不考虑 job 的时点与生命周期**。

## 3. 修法 + 理由

新增判据 **ready_at = 该 job 的进度文件最早「应当存在」的时刻**,只在 `now >= ready_at` 时才把
「文件不存在」判为僵尸:

```
ready_at = 首次触发时刻(由 cron 表达式推算) + 冷启动宽限 ZOMBIE_CRON_COLD_START_SECS(60min)
cron 不可解析 / 视野(400 天)内无触发 -> 退化为 createdAt + 宽限(如实标注)
两者都没有 -> None -> 维持现行判定(不静默放过)
```

- **① 一次性 job 触发前**:`ready_at` 在数天后 ⇒ 触发前**不判僵尸**(只登记「触发前待观察」)。
  事故一由此根治(24 天后触发的 job 现在恒为「待观察」)。
- **② 触发后**(`now >= ready_at`):文件仍不存在 ⇒ **照旧 FAIL**——区分得开「agent 从未 echo /
  已死」与「还没到时候」。一次性 job 触发后主控还要派 agent,这 60min 宽限覆盖该段。
- **③ recurring 巡检 cron**:建 cron 与派 agent 同轮,首次触发在其创建后 ≤1 个周期,`ready_at`
  = 首触发 + 60min ⇒ **覆盖「建 cron → agent 首条 echo」空窗**(事故二);
  过 `ready_at` 后**完全维持现行语义**(文件不存在 = 僵尸;mtime > 7 天 = 僵尸)。
- **判据为什么不用 `recurring` 字段**(关键,§18 L49 型陷阱):真实样本显示该字段**不可靠** ——
  `fe1005df`(`43 21 7 10 *`,prompt 明写「一次性…2026-10-07 21:43」)却是 `recurring: True`;
  反过来 6 个一次性 job `recurring` **键根本不存在**(不是 `false`!若写成 `t.get("recurring") is False`
  判定,6 个全都漏)。⇒ 用「首次触发时刻」这一**客观时点**做判据,与字段无关,两类都覆盖。
- **不许把真故障判别降没**:僵尸维度的存在意义是抓「agent 已结束但 cron 没删 / 没 echo」。
  修法是**加前置条件**(未到时刻才豁免),不是豁免整类 job;超过 `ready_at` 后判定与修前逐字相同。
- **不是「一律跳过一次性 job」的偷懒解**(§5.1):一次性 job 触发后仍判,且 7 天 mtime 规则未动。

新增实现(全在 `scripts/check_task_state.py`):`_cron_parse_field` / `_cron_parse` /
`_cron_day_matches` / `_cron_next_fire_after`(标准 5 字段 cron,逐月/日/时/分跳进,非逐分钟暴力扫)/
`_job_created_epoch`(`createdAt` 毫秒 → 秒)/ `_progress_ready_at`;`PROGRESS_DIR` 常量(默认 `/tmp`,
仅把硬编码字面量提为常量,便于测试隔离,/tmp 语义不变)。

## 4. 真值表自测

### 4.1 pytest 新增 15 用例(`scripts/tests/test_224_zombie_cron_gate.py`)

`全量 scripts/tests:262 passed, 1 skipped`(新增 15 例全过;原有用例零改动、零削弱 —— 此前
`check_task_state` **没有任何既有测试**,不存在削弱对象)。干净环境可跑:不依赖 `.env`、
不依赖真实 `/tmp` 进度文件(monkeypatch `PROGRESS_DIR` 到 `tmp_path`)。

| 用例 | 断言 |
|---|---|
| ① 一次性 job 触发前(触发日 +2 天) | `OK` + 「待观察/不计僵尸」(修前=FAIL) |
| ② 巡检 cron 冷启动 0.5/5/30/59min | 全 `OK`(事故二) |
| ③ 一次性 job 触发日 -3 天 + 无文件 | `FAIL` 「巡检进度文件不存在」(判别力保留) |
| ④ 巡检 cron 建于 2 天前 + 无文件 | `FAIL`(真故障:agent 死/未写) |
| ⑤ 文件 mtime 10 天前 | `FAIL` 「天未更新」(真故障:cron 未删) |
| ⑥ `recurring=True` 但触发日在将来(真实样本同形态) | `OK`;无 `recurring` 键 + 巡检 cron 建于 2 天前 + 无文件 ⇒ `FAIL` |
| ⑦ cron 不可解析(7 字段) | 近期创建 ⇒ `OK`+「退化按 createdAt」;2 天前 ⇒ `FAIL` |
| ⑧ 兜底语义未削弱 | json 缺失 ⇒ `warn`;无可解析路径 ⇒ `warn`;非巡检 job ⇒ 跳过 |
| ⑨ 闸门威力 | `--deploy-mode` 遇僵尸 **rc=1**(仍阻断);`--skip-zombie-crons` **rc=0** 且 C 维度整段不跑 |
| ⑩ 真实样本对账(本机有真实文件才跑) | job 键集/`createdAt` 毫秒/5 字段 cron 与 fixture 逐字一致;真实 job 跑判定时**只有已过 `ready_at` 的 job 才允许出现在 FAIL 里** |

### 4.2 真实 job 样本对照(旧规则 vs 新规则,样本 = 真实 `.claude/scheduled_tasks.json` 的 9 个 job)

**A) 真实 prompt + 真实 `/tmp`(现状:主控已改写措辞规避)** —— 9 个 job 全部 `OK`,与线上
`3 ok / 0 fail` 基线一致(3 个真巡检 cron:88531003 / ce6be4e8 / 4af653a2,文件均新鲜)。

**B) 事故形态还原**(把 §0.2 三件套的进度文件提及追加进各 job 的 prompt,指向不存在的文件):

| job | recurring | ready_at(新) | 旧规则 | 新规则 |
|---|---|---|---|---|
| 541d860f | 键不存在 | 2026-10-30 20:07 | **FAIL 文件不存在** | OK 待观察 |
| 72c2bd8b | 键不存在 | 2026-11-01 11:03 | **FAIL** | OK 待观察 |
| 7cf5422c | 键不存在 | 2026-10-08 22:12 | **FAIL** | OK 待观察 |
| ad7f0875 | 键不存在 | 2026-10-08 19:07 | **FAIL** | OK 待观察 |
| fe1005df | `True`(一次性语义) | 2026-10-07 22:43 | **FAIL** | OK 待观察 |
| 94fd5b29 | 键不存在 | 2026-10-08 23:08 | **FAIL** | OK 待观察 |
| 88531003 / ce6be4e8 / 4af653a2 | `True` | 2026-10-06 23:50/23:54/23:56 | **FAIL** | OK 待观察 |

⇒ 事故一、事故二在**真实样本上**均复现(旧 FAIL)并已修好(新 OK)。cron 推算出的触发时刻与
各 job prompt 自述日期逐条吻合(10-30 19:07 / 10-08 21:12 / 10-08 18:07 / 10-07 21:43 / 10-08 22:08)。

**C) 真故障仍抓**(真实 job dict 形状,仅改 cron/createdAt;旧/新逐条对照):

| 场景 | 旧规则 | 新规则 |
|---|---|---|
| C1 一次性 job 触发日已过 + 无文件(agent 从未 echo) | FAIL | **FAIL** ✓ |
| C2 巡检 cron 建于 2 天前 + 无文件(agent 死/未写) | FAIL | **FAIL** ✓ |
| C3 巡检 cron 文件 mtime 10 天前(cron 未删) | FAIL mtime>7d | **FAIL mtime>7d** ✓ |

### 4.3 真实 job 样本佐证(字段形态,L49 防"假样本养绿")

- 真实 job 键集:`id` / `cron` / `prompt` / `createdAt`(**毫秒** epoch,如 `1791298346256`)/
  `createdBySessionId` / `createdByPid` / `createdByProcStart` / `createdInProject`;
  `recurring` **仅真值时存在**(一次性 job 无此键)。
- 真实 cron 形态:一次性 = 月+日定点(如 `12 21 8 10 *`);巡检 = 分钟列表 + `* * * *`
  (如 `11,26,41,56 * * * *`);全部 5 字段。
- pytest ⑩ 把上述事实写成**机检断言**(含 `createdAt > 1e11` = 毫秒),本机跑真实文件对账,
  CI 无此文件自动 skip。
- 本仓 `.claude/scheduled_tasks.json` **未跟踪入 git**(`git ls-files` 无此文件)⇒ 代码不得依赖它存在;
  已用 `WARN`(非 FAIL)处理文件缺失。

## 5. 修后仍能抓到的真故障场景(判别力清单)

| # | 场景 | 修后判定 |
|---|---|---|
| 1 | agent 已结束但 cron 未删,进度文件还在且 mtime > 7 天 | FAIL(mtime 规则未动) |
| 2 | 巡检 cron 建了很久、agent 从未写下进度(文件不存在) | FAIL(`now >= ready_at`) |
| 3 | 一次性 job 触发日已过、目标 agent 从未 echo(文件不存在) | FAIL |
| 4 | agent 派单后已超 60min 仍无首条进度 | FAIL(冷启动宽限已过) |
| 5 | 巡检 cron prompt 无可解析路径 | WARN(维持) |
| 6 | 读到 mtime 失败 | WARN(维持) |

**唯一新豁免面** = `now < 首次触发时刻 + 60min` 这一有限窗口(一次性 job 触发前 / 巡检 cron 冷启动)。
窗口过期后判定与修前逐字相同,不存在"整类 job 永久豁免"。

## 6. 同类面清单(§23.3 举一反三)

**同文件其余维度**:A(pending-index 编号完整性)、B(TASKS 编号对账)—— 判据输入全是
**git 跟踪的仓内文件**(pending-index / TASKS.md / done-list / archive,恒在盘),不存在
"资源尚未产生"的时点维度 ⇒ **无同款问题**,未改。

**其它机检/监控脚本**(逐个核过存在性判定):

| 脚本 | 存在性判定 | 是否同款 | 结论 |
|---|---|---|---|
| `check_monitor_heartbeat.py:62` | 心跳文件不存在 ⇒ 告警 | **最接近** | 心跳由 monitor 每轮写;**首次部署冷启动窗口**(监控还没跑第一轮)理论上会误告警一次。非 deploy 闸门、有 dedup+告警语义,属观察项,**超范围未改**(上报主控) |
| `check_failed_units.py:291` | unit 被执行的脚本不在盘 ⇒ 问题项 | 否 | 脚本被删 = 真故障(L49/#203 场景);判据 fail-open(解析不到不判) |
| `check_version_progress.py:113/151/284` | 版本串引用文件不存在 ⇒ 不一致 | 否 | 防撕裂(§24⑤)设计使然:引用了就必须在 |
| `check_data_gap_alerts.py`(多处 `not db.exists()`) | 数据 DB 不存在 | 否 | 数据源缺失 = 采集故障,自带日期窗口语义 |
| `check_s06_freshness.py` / `check_doc_staleness.py` | 新鲜度/陈旧度 | 否 | 本身就是时间语义 |
| `scripts/agent_dispatch_cron_reminder.py` | 派单 prompt 是否含进度路径 | 否 | 派单时(PostToolUse)机检,不判僵尸;与该规则无重复实现 |

**规则重复实现检查**:`grep -rn "zombie|agent-progress|巡检兜底"` 全仓脚本,僵尸规则**只有本脚本一处实现**
(无第二份副本需同步)。

## 7. 回退说明(一键)

`git revert <本 commit>`(主控 merge 后生效);应急可 `git checkout ecb5243ba -- scripts/check_task_state.py`
还原旧判定(**C 维度即回到「文件不存在 = FAIL」**),`git checkout` 后须 `git status` 核对工作区无残留 M。
本改动**未动** `--deploy-mode` / `--skip-zombie-crons` 位置与语义,回退面仅 C 维度判据本身。

## 8. 未覆盖项(如实标注)

1. **cron 表达式只在 5 字段数值语法内可解析**(`*` / 列表 / 区间 / 步长)。若将来平台改用 6 字段(含秒)
   或月/周英文名,则退化为 `createdAt + 60min` 粗判(**判定仍不放过真故障**,只是精度下降),
   报告里已在 detail 文案标注「退化按 createdAt」便于识别。
2. **`ready_at` 用「首次触发时刻」近似代替「agent 该写进度的时刻」**:对"建 cron 与派 agent 同轮"
   的现行纪律(§0.2)成立;若将来出现"提前建 cron、很久后才派 agent"的用法,一次性 job 会在
   首次触发 + 60min 后就要求文件存在 ⇒ 可能误报(当前真实样本无此形态)。
3. **60min 宽限是常量**(`ZOMBIE_CRON_COLD_START_SECS`),未做成随 cron 周期自适应;取 60min 的理由 =
   远大于实际派单空窗(数分钟)、又远小于"真故障被漏"的容忍度,且 > 巡检 cron 自身的 20min 停滞阈值。
4. **生效前提未上云取证(如实标注)**:C 维度要求跑机检的那棵树内存在 `.claude/scheduled_tasks.json` ——
   该文件**未入 git**(仅 `.git/info/exclude` 本机排除,`git ls-files` 无),故在**没有它的树**里 C 恒为
   `warn`「scheduled_tasks.json 不存在(无 cron 可检, 跳过)」(CI 即是;worktree 实测亦然)。
   ⇒ 阻断面 = **有该文件的那棵树**(主控本机;主控本机跑 deploy.sh 时生效)。云上树内是否落地该文件
   **本次未取证**(未 ssh),留给主控确认——若云上同样无此文件,则 C 维度在云上 deploy 链路本就是 warn 空转,
   本次修的是**主控本机** deploy 的误炸面。两处验证(见 §9)均为**只读跑校验**,零外发、零生产写。

## 9. 验证结果(两处)

| 环境 | 命令 | 结果 |
|---|---|---|
| worktree(新代码 + worktree 树,无 `.claude/scheduled_tasks.json`) | `python3 scripts/check_task_state.py`(无 `--skip-zombie-crons`) | `2 ok / 1 warn / 0 fail`,rc=0;C 维度 = `warn`「scheduled_tasks.json 不存在(无 cron 可检, 跳过)」 |
| **真实仓库目录形态**(新代码 + 真实仓库树 `/Users/linhuichen/code/trade`) | `python3 <worktree>/scripts/check_task_state.py --repo /Users/linhuichen/code/trade` | **`3 ok / 0 warn / 0 fail`**,rc=0;C 维度 = `巡检 cron 检测 OK(3 个巡检 cron 进度文件均存在且新鲜)` — 与线上基线一致,**未误报** |
| 全量回归 | `python -m pytest scripts/tests/ -q` | 262 passed, 1 skipped |

零外发:本次自测**未发任何通知**(脚本自身无发送链路;未跑 `notify.py`、未跑任何业务脚本主体),
未写任何生产数据,未 `git add` 根 `data/`。