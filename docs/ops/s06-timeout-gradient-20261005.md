# s06-snapshot 超时梯度修正 + systemd units 计数重算（2026-10-05）

> task: `feat/s06-timeout-grad-20261005`（implementer 落地报告）
> 生成/复现脚本: [`scripts/systemd_timeout_gradient_audit.py`](../../scripts/systemd_timeout_gradient_audit.py)
> 配套 commit: 本报告与全部源码/文档改动同属一个 commit（`git log -1 --format='%h %s' -- docs/ops/s06-timeout-gradient-20261005.md` 可反查）
> 环境: 云上 `ssh -i ~/tdsignal.pem ubuntu@122.51.111.173`（生产 systemd units 手管，git pull 不更新）

## 0. 结论速览

| 项 | 动作 | 状态 |
|---|---|---|
| **A** s06 超时梯度 | 云上 `trade-s06-snapshot.service` `TimeoutStartSec` **600 → 3300**（= 内层串行合计 3000 + 300 余量）+ `daemon-reload` | ✅ 已改已验（只读验证 4 项全 PASS） |
| A 文档同步 | §2.15 服务块值 + 超时梯度修正说明；`timeout-caliber-20260916.md` §七 后记 | ✅ 已改 |
| **B** 计数漂移 | doc §0 `37→39` / §1.4 `32→32`（维持 main 版） / §1.7 `36→40` / §2 标题 `37→39`；README、scripts/README、check_doc_staleness.py 同步 40 | ✅ 已改 |
| B 生成器 | update-all 标题去括号 → `gen_systemd_units.py --check` **78 → 80 unit**（40 timer + 40 service） | ✅ 已修 |
| 同类错误面 | 全 40 service 梯度审计：**倒挂 0 个**（s06 修后余量 300s；r2-consistency 60s；其余无 shell 内层） | ✅ 见 §三 |
| 新发现 | doc §2 内 30 个 service 的 `TimeoutStartSec` 仍是 2026-09-12 迁移批值（云上早已按 #36 改）→ 生成器若重跑会**回退** #36，**未改，上报拍板** | ⏳ 见 §五 |
| 前端/版本串 | 无前端改动 → 不 bump；§21 算法公示 N/A | — |

## 一、A 项：s06 超时梯度（根因修复）

### 1.1 根因（一句话）

`trade-s06-snapshot.service` 外层 `TimeoutStartSec=600` 计量**整条脚本的墙钟**，而 `scripts/s06_snapshot.sh` 内层是 **6 次串行 `run_to` 调用（5 段代码，④a 在双树循环内跑 2 次；合计 3000s）**；外层 < 内层 ⇒ systemd 先于内层看门狗杀脚本 ⇒「结束」行与 `notify.py` 告警都发不出（**内层 > 外层 = 无梯度**；同 memory `watchdog-inner-timeout-no-gradient`）。

### 1.2 三条独立证据（互不依赖）

**① 脚本自身日志（最直接）**——云上 `data/logs/s06_snapshot_launchd.log`：「开始」行 **12** 条 / 「结束」行 **9** 条，缺 3 次，且缺的正是 **最后三个交易日 2026-09-28 / 09-29 / 09-30**；三个块都在 **`✓ S06 快照机检全 PASS` 之后戛然而止**（即卡在 ③ `run_to 900 upload_r2.py upload-data-files` R2 段）。对照组 09-24 同链路 20:35:02 开始 → 20:35:24 结束 退出码=0（22s，说明正常时秒级，R2 段变慢才暴露无梯度）。

```
开始 2026-09-24 20:35:02 … 结束 2026-09-24 20:35:24 退出码=0   ← 正常
开始 2026-09-28 20:35:01 …（无结束）
开始 2026-09-29 20:35:01 …（无结束）
开始 2026-09-30 20:35:01 …（无结束）
```

**② 内层/外层数值倒挂**——③ 段内层 `run_to 900` > 外层 600，单段即倒挂；整脚本内层合计 3000 > 600，倒挂更甚（§1.3）。

**③ 第三方独立记录（另一 agent 写进 main 的代码注释）**——`scripts/schedule_monitor.sh:427-431`（#162，已在 `origin/main`）：

> 实例（s06 09-28~09-30）：s06_snapshot.sh 三次跑到 R2 段被 systemd 600s 杀在内层 run_to 900s 无梯度，日志只留"开始"无"结束"

同文件 `:539` 亦注明 `"s06_snapshot": 900` 的构成即 `gen300+check300+R2上传900+posrating300×2+快照上传900`——**3000 的构成由第二方独立印证**。

### 1.3 内层值实测（逐段，来源 `scripts/s06_snapshot.sh`）

| 行号 | 段 | 内层超时 | 次数 | 小计 |
|---|---|---|---|---|
| 84 | ① gen_kelly_mode_s06_state.py 重生成 | `run_to 300` | 1 | 300 |
| 93 | ② check_s06_state.py 四断言机检 | `run_to 300` | 1 | 300 |
| 100 | ③ upload_r2.py upload-data-files（R2 同步） | `run_to 900` | 1 | 900 |
| 123 | ④a kelly_posrating.py（双树 `for _D in A B`） | `run_to 300` | **2** | 600 |
| 128 | ④b upload_r2.py upload-kelly-snapshots | `run_to 900` | 1 | 900 |
| | | | **合计** | **3000** |

> 备注：④a 的 `run_to 300` 在 `for _D in "$REPO/static-site/data" "$GIT_REPO/static-site/data"; do` 循环体内，**执行两次**，故按 300×2=600 计（本报告审计脚本按 `for/done` 栈自动倍增，避免漏计 300）。

### 1.4 取值决策：**3300**（= 内层串行合计 3000 + 300 余量）

**目的先行（主控 2026-10-05 派单补充，已被本报告证据印证）**：这个值的目的**不是「给够时间」，而是让内层 `run_to` 先超时、脚本走完到 L138 把 notify 发出来**。现状外层 600 **先**把整条脚本杀了（退出码 143），内层兜底（124 → `FINAL_RC≠0` → L138 notify）根本没机会跑 ⇒ 这才是「告警与链路同亡」的真根因。⇒ **硬约束：外层 > 内层串行合计**。

**取值对照（同一目的下的三个候选）**：

| 候选 | 外层 | 单段 ③ 挂死场景 | **R2 网障相关失败场景**（③ 与 ④b 同时吃满 900；最需告警） | 结论 |
|---|---|---|---|---|
| 主控初版建议 | 960 | ✗ 960 > 900 但 < 3000，④b 被杀 | ✗ 先杀 | 不可用 |
| 主控修订建议（研究者实测） | 1200 | ✓（>900，脚本能过 ③） | ✗ 1200 < 3000 ⇒ 在 ④b 中途被杀，**notify 仍丢失** | 不达标 |
| **本报告采纳** | **3300** | ✓ | ✓ 外层 3300 > 3000，两段内层各自先超时，脚本必到 L138 | ✅ |

- **为何必须是串行合计而非单段最大值**：`run_to` 是**逐段**的墙钟上限，脚本串行推进；只有当外层 > **各段之和**时，「多层段同时慢」的最坏路径才不会被 systemd 提前截断。而 R2 网障正是**相关失败**——③`upload-data-files` 与 ④b`upload-kelly-snapshots` 走同一条 R2 链路，会一起变慢。取 1200 恰在**最需要告警**的场景失效。
- **余量 300 的来源**：采用研究者 2026-10-05 的余量口径（其原式为「内层 900 + 300」，理由「覆盖 R2 段前后的非上传耗时」）；套到**实测串行合计 3000** 上 ⇒ 3000 + 300 = **3300**。余量覆盖的是 `run_to` 计时之外的段间开销：双树 610KB 原子写 ×2 / posrating ×2 计算 / `notify.py` 子进程 / bash-python 启动。
- **副作用核查（主控要求）**：①**无时点链冲突**——s06 每日仅 20:35 一次，3300s 最坏 21:30 结束，与次日运行隔 23h；与 21:00 并发组（backfill-evening / futures-backfill / backup-db，写 DB 与 sqlite 热备）**无文件级交集**（s06 只写两树 `static-site` JSON + R2），仅在最坏路径下有 CPU/IO 竞争，可接受。②**不触发 6h 陈旧判据**（`schedule_monitor.sh` `IN_PROGRESS_MAX_AGE`），55min ≪ 6h。③满足研究者验收锚点 `TimeoutStartUSec ≥ 960s`（实测 **55min = 3300s** ✓）。
- **口径修正留痕（§5.4/E26）**：本任务开工时主控建议 960，中途修订为 1200（研究者独立实测）；本报告以**实测串行合计 3000** 为准，采纳 1200 的余量口径但否定其取值，最终 **3300**（云上先后落过 3060 → 3300 两版，最终生效 3300）。
- 未动 `OnCalendar`、未 restart/stop 任何服务、未 enable/disable。

### 1.5 云上操作 + 只读验证（§14：只 daemon-reload，不触发任何 timer）

```
# 改前先备份（§25）
sudo cp /etc/systemd/system/trade-s06-snapshot.service \
        /etc/systemd/system/trade-s06-snapshot.service.bak-20261005-pre-timeout
sudo sed -i 's/^TimeoutStartSec=600$/TimeoutStartSec=3300/' \
        /etc/systemd/system/trade-s06-snapshot.service
sudo systemctl daemon-reload
```

| 验证项（只读） | 命令 | 实测 | 判定 |
|---|---|---|---|
| 生效值 | `systemctl show -p TimeoutStartUSec trade-s06-snapshot.service` | `TimeoutStartUSec=55min` | ✅ = 3300s ≥ 960s 验收锚点 |
| 文件值 | `grep TimeoutStartSec /etc/systemd/system/trade-s06-snapshot.service` | `3300` | ✅ |
| 备份留证 | `ls -l …bak-20261005-pre-timeout` + grep | 存在；内含 `TimeoutStartSec=600` | ✅ 原件可反查 |
| OnCalendar 未动 | `systemctl list-timers --all \| grep s06` | 下次 `Mon 2026-10-05 20:35:00 CST`，上次 `Fri 2026-10-02 20:35:01` | ✅ `Mon..Fri 20:35` 保持 |
| timer 总数 | `systemctl list-timers --all \| grep -c 'trade-.*\.timer'` | `40` | ✅ 与 §二 一致 |

### 1.6 备份与回滚（§25，恢复路径一行写明）

- 备份文件：`/etc/systemd/system/trade-s06-snapshot.service.bak-20261005-pre-timeout`（root，508B，内容 `TimeoutStartSec=600`）。
- **恢复命令**：
  ```bash
  sudo cp /etc/systemd/system/trade-s06-snapshot.service.bak-20261005-pre-timeout \
          /etc/systemd/system/trade-s06-snapshot.service && sudo systemctl daemon-reload
  ```

### 1.7 待观察（本会话等不到的验收点）+ 主控验收口径

- **⚠️ 真验证点 = 2026-10-08（周四）20:35，不是今晚**：今晚 10-05 与 10-06/10-07 均在**国庆休市**（本仓日历实测 `app.calendar.is_trading_day`：10-05/06/07 = NON-trading，**10-08 Thu = trading**，10-09 Fri = trading）。timer `Mon..Fri 20:35` 到点虽会跑，但脚本走「非交易日, 跳过 S06 快照重生」分支（**不碰 R2 段**，日志已见 10-01/10-02 两天同款跳过）⇒ **今晚验不出梯度效果**，切莫按「今晚就能验」误判。
- **主控验收口径（2026-10-08 20:35 之后）**：
  1. `ssh 云上 journalctl -u trade-s06-snapshot.service --since "2026-10-08"` → 无 `timed out` / `Killing` / `signal=TERM`，`Result=success`；
  2. `grep -c '结束' data/logs/s06_snapshot_launchd.log` → 比改前 **+1**（改前 9 条，缺 09-28~30 三次；**「结束」行写出 = 梯度修好**）；
  3. 附带看耗时：正常应回到 ~20-30s（09-24 对照 22s）；若显著变长但写出「结束」行，说明梯度已生效、R2 仍慢 → 转 §五-2 立项；
  4. 兜底：若仍无「结束」行，立即按 §1.6 回滚（说明根因不止梯度）。

## 二、B 项：systemd units 计数重算（doc 准确性）

### 2.1 三源实测 = 40

| 源 | 命令/位置 | 值 |
|---|---|---|
| 云上 timer 实例 | `systemctl list-timers --all \| grep -c 'trade-.*\.timer'` | 40 |
| 云上 unit 文件 | `ls /etc/systemd/system/trade-*.timer \| wc -l` / `…*.service \| wc -l` | 40 / 40 |
| doc 自身 §2 单元块 | 以 `gen_systemd_units.py` 的 `TITLE_RE` 解析本文档 | 40 timer（修复标题后，见 §2.5） |

### 2.2 逐项历史链（commit 可反查，`git log -S` 实测）

| 日期 | 变化 | §0「周期任务」 | 累计 timer | commit |
|---|---|---|---|---|
| 09-12 | 迁移批首版 | 35 | 35 + 1 backup_db = 36 | `6f7e5b13a` |
| 09-14 | +`trade-lof-track-index`（场内 LOF） | 36 | 37 | `9993cfba5` |
| 09-17 | +`trade-nextday-gap-check`（#45） | 37 | 38 | `fd6d5c78d` |
| 10-03 | +`trade-check-monitor-heartbeat`（P0-1 心跳消费方） | 38 | 39 | （§0 未随之改，见 §2.4） |
| 10-05 | +`trade-r2-consistency`（#160 §22 一致性巡检） | **39** | **40** | 本次重算 |

### 2.3 mtime 交叉验证（独立第二源，云上实测）

40 个 `trade-*.timer` 中 **34 个 mtime 停在 `2026-09-14`**（= 迁移批 36 减去之后被改过的 `trade-update-all`(10-04 周日错峰) 与 `trade-nextday-plan`(09-17)）；其余 6 个 = **4 新增**（lof-track-index 09-15 / nextday-gap-check 09-17 / check-monitor-heartbeat 10-03 / r2-consistency 10-05）+ **2 修改**。**34 + 6 = 40** ✓。
另一独立锚点：`gen_systemd_units.py --check` 的**逐点实测链**（三点，勿混）：`2026-10-03` 体检报告记录 = **78 单元（= 39 timer + 39 service）** → 分支基线 `0ef6fbb98`（已含 #160 的 r2-consistency 对、但 update-all `.timer` 标题仍带尾巴）= **79 单元（= 39 timer + 40 service）** → 本次修复后 = **80 单元（= 40 timer + 40 service）**。78 → 80 差 **2**：+1 = 10-05 新增 r2-consistency 对、+1 = update-all `.timer` 标题解析修复（详见 §2.5）。

### 2.3.1 订正（审查后，2026-10-05）

初稿本节曾写「今日 80 … 恰差 r2-consistency 1 个」与 §2.5 写「78→80 的那 **2** 个 unit」——两处自相矛盾。经审查复核，**基线实跑是 79（非 78）**，且**标题解析修复的生成物差集恰为 1 个文件**（`trade-update-all.timer`）。本文已按 79 → 80（+1 标题修复）+ 78 → 79（+1 r2-consistency）重写；§2.5 同步订正。**注：配套 commit `d6ce93405` 的 message 里写的是「78→80」，按主控指示不 amend（avoid force push），以本订正段为准。**

### 2.4 旧数字差异（逐项解释，历史数字保留可反查）

| 旧值 | 位置 | 性质 | 新值 |
|---|---|---|---|
| `37` | §0 表 | 09-17「+nextday-gap-check」后的中途值，之后 +heartbeat/+r2-consistency 未重算 | **39**（= 40 − 1 backup_db） |
| `32` | §1.4 | 阶段4b 当时的「32 个非 append 例外 unit」= 37 − 5（当时的 shell 型例外数） | **32**（**维持不变**；正确口径 = 全 40 service 分区:6 shell 型 + 2 python heredoc 型 + **32** = 40 ✓。**不是**「39 − 6 = 33」——该式把 base 取成 39 周期且漏扣 2 个 python，会得 6+2+33=41 > 40，算术不成立） |
| `36` | §1.7 | 阶段4b 统一注入三 env 时的 service 数 | **40**（实测 40 service 全注入） |
| `37` | §2 标题「37 个周期任务完整对照表」 | 同 §0 | **39** |

> 处理原则（§5.3① 核心保障 + 任务要求不删历史）：**不删旧数字**，改为在 §0 加「计数口径与重算」注（含历史链 + mtime 双源 + commit），旧值原样保留在同一注里可反查。

### 2.5 #160「差异项 = trade-update-all」claim 验证 —— 成立

`gen_systemd_units.py` 的标题正则要求标题行**精确**为 `` `trade-x.timer`: ``；`trade-update-all` 标题带了尾巴「(云上实际配置,2026-10-04 改)」⇒ 解析漏 1：

| 版本 | 可解析 `.timer` 块 | `--check` 总单元 |
|---|---|---|
| 修复前（基线 `0ef6fbb98`） | **39**（update-all `.timer` 行 = `` `trade-update-all.timer`(云上实际配置,2026-10-04 改): `` ⇒ 不匹配；但 update-all `.service` 标题完好） | **79**（= 39 timer + 40 service） |
| 修复后（本次） | **40**（注记移出标题行到独立引用行，标题行还原为 `` `trade-update-all.timer`: ``） | **80**（= 40 timer + 40 service） |

39 + update-all = 40 ✓ 与云上一致 ⇒ **claim 成立**；生成物差集恰为 **1 个文件**（`trade-update-all.timer`），即 `--check` 的 **79 → 80（+1）**。

### 2.6 引用点同步清单（§22：同事实多登记点逐一过）

| 引用点 | 旧 | 处理 |
|---|---|---|
| `docs/deploy/systemd-units-20260912.md` §0/§1.4/§1.7/§2 标题 | 37/32/36/37 | ✅ 改 39/**32**/40/39（§1.4 = 32 **维持 main 版**，按 40-service 分区：6 shell + 2 python heredoc + 32；**非**「39 − 6 = 33」）+ §0 重算注 |
| `README.md:403` / `:418` | 37（两处） | ✅ 改 40（10-05 实测，附清单链接） |
| `scripts/README.md:137` | 37 | ✅ 改 40（10-05 实测） |
| `scripts/check_doc_staleness.py:326` | 「37 个 trade- 前缀 .timer」 | ✅ 改 40（**代码内常量登记点**，§22） |
| `docs/PARAMS.md:859` | 37 | ✅ 改 40（10-05 实测） |
| `docs/site-deployment.md:621` / `:843` | 37 | ✅ 改 40（10-05 实测） |
| `docs/data-sources.md:266` | 37 | ✅ 改 40（10-05 实测） |
| `docs/deploy/timeout-caliber-20260916.md` §三/§四「37 个 service」 | 37 | ⏸ 保留（该文件是 **2026-09-16 当日快照**），另加 §七 后记指向本文档 |
| `docs/ops/cloud-healthcheck-20261003/*`（38 处）、`holiday-window-housekeeping-review-20261001.md`（38）、`cloud-write-trade-tracked-audit-20260927.md`（38） | 38 | ⏸ 保留（**带日期的历史体检报告**，当时实测值，删改反而失真） |
| `docs/deploy/migration-inventory-20260912.md:155` | 「40 个 timer」 | ⏸ 保留（09-12 盘点期**松口径候选数**，与今日 40 巧合同值；非现行权威，权威 = systemd-units doc） |

## 三、同类错误面全量审计（§23.2 修 bug 第三铁律：排查同类）

### 3.1 方法

`python3 scripts/systemd_timeout_gradient_audit.py [--dump <云上 unit dump>]`：对每个 `trade-*.service` 取 `TimeoutStartSec`（缺省 systemd 默认 90s）与 `ExecStart` 指向的 `scripts/*.sh`，用 `for/done` 栈统计脚本内 `run_to N` / `perl 'alarm…' N` 的**串行合计（上界）**，比对外层是否留余量。**只读**，可云上直跑、也可喂 dump 本地复核。

### 3.2 全量结果（云上 40 service，`--dump` 快照）

```
service                                      script                      outer   inner  status
----------------------------------------------------------------------------------------------
trade-ab-direction-anchor.service            run_ab_direction_anchor.sh    600       -  —(.sh 但无 run_to,外层即唯一看门狗)
trade-backfill-evening.service               backfill_metrics.sh             0       -  —(.sh 但无 run_to,外层即唯一看门狗)
trade-backup-db.service                      backup_db.sh                    0       -  —(.sh 但无 run_to,外层即唯一看门狗)
trade-brief-push.service                     brief_push_wrapper.sh         600       -  —(.sh 但无 run_to,外层即唯一看门狗)
trade-check-data-gap.service                 check_data_gap_alerts.sh      600     300  OK(余量 300s)
trade-check-monitor-heartbeat.service        -                             600       -  —(非 .sh,无 shell 内层看门狗)
trade-daily-brief.service                    -                             600       -  —(非 .sh,无 shell 内层看门狗)
trade-daily-summary-supplement.service       -                             600       -  —(非 .sh,无 shell 内层看门狗)
trade-etf-national-team.service              etf_national_team_backfill.sh   0       -  —(.sh 但无 run_to,外层即唯一看门狗)
trade-etf-track-index.service                -                             600       -  —(非 .sh,无 shell 内层看门狗)
trade-fapi-daily.service                     fapi_daily_syn.sh               0       -  —(.sh 但无 run_to,外层即唯一看门狗)
trade-fetch-news.service                     -                             600       -  —(非 .sh,无 shell 内层看门狗)
trade-futures-backfill.service               futures_backfill.sh             0       -  —(.sh 但无 run_to,外层即唯一看门狗)
trade-gold-night.service                     gold_night.sh                   0       -  —(.sh 但无 run_to,外层即唯一看门狗)
trade-intraday-snapshot.service              intraday_snapshot.sh            0       -  —(.sh 但无 run_to,外层即唯一看门狗)
trade-kelly-intraday-rerun.service           kelly_intraday_rerun.sh       600     180  OK(余量 420s)
trade-lab-auto.service                       update_lab.sh                   0       -  —(.sh 但无 run_to,外层即唯一看门狗)
trade-lhb-backfill.service                   lhb_backfill.sh                 0       -  —(.sh 但无 run_to,外层即唯一看门狗)
trade-lof-track-index.service                -                               0       -  —(非 .sh,无 shell 内层看门狗)
trade-nextday-gap-check.service              nextday_gap_check.sh          600       -  —(.sh 但无 run_to,外层即唯一看门狗)
trade-nextday-plan.service                   nextday_plan.sh               600       -  —(.sh 但无 run_to,外层即唯一看门狗)
trade-overfit-monitor.service                overfit_monitor.sh              0       -  —(.sh 但无 run_to,外层即唯一看门狗)
trade-pf-score-daily.service                 pf_score_daily.sh             600       -  —(.sh 但无 run_to,外层即唯一看门狗)
trade-pf-score-weekly.service                pf_score_weekly.sh              0       -  —(.sh 但无 run_to,外层即唯一看门狗)
trade-pf-stage0-manager.service              stage0_manager.sh               0       -  —(.sh 但无 run_to,外层即唯一看门狗)
trade-pf-stage0-nav.service                  stage0_nav.sh                   0       -  —(.sh 但无 run_to,外层即唯一看门狗)
trade-pf-stage0-overview.service             stage0_overview.sh              0       -  —(.sh 但无 run_to,外层即唯一看门狗)
trade-pf-stage0-risk.service                 stage0_risk.sh                  0       -  —(.sh 但无 run_to,外层即唯一看门狗)
trade-public-fund-daily.service              public_fund_daily.sh          900       -  —(.sh 但无 run_to,外层即唯一看门狗)
trade-public-fund-estimation.service         public_fund_estimation.sh     600       -  —(.sh 但无 run_to,外层即唯一看门狗)
trade-public-fund-full.service               public_fund_full.sh             0       -  —(.sh 但无 run_to,外层即唯一看门狗)
trade-public-fund-quarterly.service          public_fund_quarterly.sh        0       -  —(.sh 但无 run_to,外层即唯一看门狗)
trade-r2-consistency.service                 check_r2_consistency.sh       960     900  OK(余量 60s)
trade-rzhb-backfill.service                  rzhb_backfill.sh              600       -  —(.sh 但无 run_to,外层即唯一看门狗)
trade-s06-snapshot.service                   s06_snapshot.sh              3300    3000  OK(余量 300s)   ← 本次修复后
trade-schedule-monitor.service               schedule_monitor.sh           600       -  —(.sh 但无 run_to,外层即唯一看门狗)
trade-self-heal.service                      self_heal.sh                  600       -  —(.sh 但无 run_to,外层即唯一看门狗)
trade-turnover-backfill.service              turnover_backfill.sh            0    9900  OK(外层=0 无限)
trade-update-all.service                     update_all.sh                   0       -  —(.sh 但无 run_to,外层即唯一看门狗)
trade-us-stock-morning.service               us_stock_morning.sh             0       -  —(.sh 但无 run_to,外层即唯一看门狗)
----------------------------------------------------------------------------------------------
共 40 service;倒挂 FAIL 0 个;.sh 无内层看门狗 29 个(外包 systemd 唯一看门狗)
```

### 3.3 结论（逐类）

| 类 | 数量 | 说明 |
|---|---|---|
| **倒挂 FAIL** | **0** | s06 修复后唯一曾倒挂的已消除 |
| 有 shell 内层看门狗且留余量 | 5 | s06 300s（本次）/ r2-consistency 60s / check-data-gap 300s / kelly-intraday-rerun 420s / turnover-backfill 外层=0 无限 |
| `.sh` 但无内层看门狗 | 29 | 外层 systemd 即唯一看门狗，**不存在**「内层>外层」倒挂；其中 21 个外层=0（慢任务无限），8 个外层 600/900 |
| 非 `.sh`（python/direct） | 6 | 无 shell 内层 |

**给主控的同类面提醒（不改，非倒挂但值得记）**：

1. **零余量档已到边**：`trade-r2-consistency` 960 vs 900（只剩 **60s**）。若日后脚本再各加一段 300s 的 `run_to`，就会翻成倒挂——建议后续**脚本内层新增 `run_to` 时，同 commit 同步外层**（可把本审计脚本挂进 deploy/巡检机检，见 §五-3）。
2. **python 侧 subprocess 超时不体现在外层关系**：如 `nextday_gap_check.py` 内部有 `timeout=300/120/60` 的 subprocess。这类不产生「内层>外层」倒挂，但外层 600 是唯一墙钟上限，属**设计如此**（该脚本本身秒级）。

## 四、§23.3 举一反三（同模式/同数据源/同组件还被谁用）

| 维度 | 清单 | 覆盖结果 |
|---|---|---|
| **同模式**（外层 systemd 超时 vs 脚本内层看门狗） | 全 40 service | ✅ 逐个审计（§三），倒挂 0 |
| **同数据源**（`TimeoutStartSec` 这个事实的登记点） | 云上 unit 文件 / doc §2 生成源 / `gen_systemd_units.py` / schedule_monitor `DUR_THRESHOLDS` | ✅ doc 生成源已改 3300；云上已改 3300；monitor 阈值 900 不变（它是「耗时超标告警」，须 < 外层）。**发现 doc §2 其余 30 个值陈旧 → §五-1 上报** |
| **同组件**（改写本文档的其它 agent / 生成器解析） | `gen_systemd_units.py`（TITLE_RE 解析） | ✅ 修 update-all 标题解析（§2.5），`--check` **79→80（+1）** |
| **同组件**（timer 计数的全部登记点） | 11 处（§2.6 表） | ✅ 现役 7 处改 40；历史快照 4 类保留并注明 |
| **相关展示位**（用户能看到「40 个 timer」的地方） | README:403/418、scripts/README、PARAMS、site-deployment ×2、data-sources | ✅ 全同步 40 |

## 五、新发现（未改，上报主控拍板）

### 5-1（**重要**）doc §2 内 30 个 service 的 `TimeoutStartSec` 是 2026-09-12 迁移批旧值，与云上现状不符

`gen_systemd_units.py` **以本文档 §2 的 ini 代码块为生成源**。逐项比对「doc 块值 vs 云上实值」= **40 个里 30 个不一致**，全部方向一致：**doc 停在 2026-09-12 迁移批的拍脑袋值，云上早按 #36（2026-09-16 超时收口）改过**。样例：

| service | doc 值 | 云上值 |
|---|---|---|
| trade-update-all | 10800 | 0 |
| trade-intraday-snapshot | 1800 | 0 |
| trade-pf-stage0-overview | 25200 | 0 |
| trade-public-fund-daily | 1800 | **900**（云上连 #36 的 600 都不是，另有一次调整） |
| trade-daily-brief | 900 | 600 |
| trade-self-heal | 10800 | 600 |
| （共 30 项，含 ab-direction-anchor / backup-db / brief-push / etf-national-team / etf-track-index / fapi-daily / futures-backfill / gold-night / kelly-intraday-rerun / lab-auto / lhb-backfill / lof-track-index / overfit-monitor / pf-score-daily / pf-score-weekly / pf-stage0-manager|nav|risk / public-fund-estimation|full|quarterly / rzhb-backfill / turnover-backfill / us-stock-morning 等） |

**风险**：任何人跑一次生成器并装回云上，**§36 超时收口成果被静默回退**（慢任务被 7200/18000/25200 或 600 强杀 → 生产事故级）。**本次未改**：①超出本任务 A/B 范围；②属「动已上线配置口径」，按 §23.7 冻结契约须用户/主控拍板；③该文档正被 #160 支线并发编辑，避免撞车。**建议**：单开一支「doc §2 的 30 个 TimeoutStartSec 对齐云上」+ 给生成器加「生成值与云上实值一致性机检」闸门。
（§1 免责：本报告 §三 的审计表读的是**云上 dump**，故 s06 项显示已修后的 3300，不受 doc 陈旧值影响。）

### 5-2 s06 的 R2 段为何在 09-28 起连续三天变慢

09-24 同链路 22s 跑完，09-28~30 却在 R2 段挂到被 600s 杀。梯度修好后**不会再杀**，但「为什么变慢」未知（可能与当日 R2/网络/文件体积有关）。建议观察 **2026-10-08（下个交易日）** 20:35 的耗时；若再现长时间挂 R2（内层 900s 兜住时），单独立项查根因。

### 5-3 建议把梯度审计挂进机检（可选）

`scripts/systemd_timeout_gradient_audit.py` 已能一键出「倒挂 FAIL」表（exit 1）。可挂到云上巡检/`main-merge.sh` 或 `update_all` 链尾，防日后新增 `run_to` 再次悄悄制造倒挂（成本零，纯只读）。

## 六、改动文件清单

**云上（手管 units，git 不同步）**
- `/etc/systemd/system/trade-s06-snapshot.service`：`TimeoutStartSec=600 → 3300`（中间落过 3060，最终生效 3300）；备份 `.bak-20261005-pre-timeout`（内容仍是原件 600）；已 `daemon-reload`

**仓库（feat 分支 `feat/s06-timeout-grad-20261005`）**
- `scripts/systemd_timeout_gradient_audit.py`（新增，审计/复现脚本）
- `docs/deploy/systemd-units-20260912.md`：§2.15 值 600→3300 + 梯度修正说明；§0 计数表 37→39 + 重算注（历史链/commit/mtime 双源）；§1.4 = **32（维持 main 版，按 40-service 分区）** + 6 个 shell 型清单；§1.7 36→40；§2 标题 37→39；update-all 标题去括号（生成器可解析）
- `docs/deploy/timeout-caliber-20260916.md`：§七 后记（s06 值过时说明 + 内层合计 3000 + 云上 600→3300 + 同类面）
- `README.md`（2 处）、`scripts/README.md`、`docs/PARAMS.md`、`docs/site-deployment.md`（2 处）、`docs/data-sources.md`、`scripts/check_doc_staleness.py`：计数 37 → 40（2026-10-05 实测）
- `docs/ops/s06-timeout-gradient-20261005.md`（本报告）

## 复现

```bash
# 0) 环境
cd <trade 仓>/  # 本任务 worktree: .claude/worktrees/agent-adabd06db362af3d4
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173   # 云上只读取 unit dump

# 1) 云上取全部 trade service 快照（默认跑法：直接在云上读 /etc/systemd/system）
python3 scripts/systemd_timeout_gradient_audit.py
#    本地复核法（喂 dump，产出本报告 §三 的表）
#    sudo bash -c 'for f in /etc/systemd/system/trade-*.service; do echo "@@@FILE:$(basename $f)"; cat $f; done' > /tmp/cloudunits/dump.txt
python3 scripts/systemd_timeout_gradient_audit.py --dump /tmp/cloudunits/dump.txt

# 2) 回看 s06 修复证据：外层 3300 / 内层 3000 / 备份 600
systemctl show -p TimeoutStartUSec trade-s06-snapshot.service      # 55min
grep TimeoutStartSec /etc/systemd/system/trade-s06-snapshot.service*
grep -c '开始\|结束' /home/ubuntu/code/trade-data/data/logs/s06_snapshot_launchd.log   # 12 / 9（缺 09-28~30）

# 3) 计数三源
systemctl list-timers --all | grep -c 'trade-.*\.timer'            # 40
ls /etc/systemd/system/trade-*.timer | wc -l                       # 40
python3 scripts/gen_systemd_units.py --check                       # 80 个 unit 待生成

# 4) 回滚 s06（如需）
sudo cp /etc/systemd/system/trade-s06-snapshot.service.bak-20261005-pre-timeout \
        /etc/systemd/system/trade-s06-snapshot.service && sudo systemctl daemon-reload
```

**配套 commit**：本报告 + `scripts/systemd_timeout_gradient_audit.py` + 上述文档改动同属一个 commit（`git log -1 --format='%h %s' -- docs/ops/s06-timeout-gradient-20261005.md`）。