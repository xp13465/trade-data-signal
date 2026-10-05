# #189 doc §2 生成源 `TimeoutStartSec` 对齐云上实值 + 生成源防漂移机检(2026-10-05)

> task: #189(登记于 `docs/pending-features-index.md`;出处 = s06 unit 支线同类错误面扫描)
> 生成/复现脚本: [`scripts/systemd_timeout_gradient_audit.py`](../../scripts/systemd_timeout_gradient_audit.py) 新增 `--check-doc` / `--align-doc` 两模式
> 配套 commit: 本报告 + doc 对齐 + 快照 + 审计器 + main-merge 挂链同属一个 commit(`git log -1 --format='%h %s' -- docs/ops/189-systemd-units-timeout-doc-sync-20261005.md` 可反查)
> 环境: 云上 `ssh -i ~/tdsignal.pem ubuntu@122.51.111.173`(生产 unit 手管,`git pull` 不更新)

## 0. 结论速览

| 项 | 动作 | 状态 |
|---|---|---|
| **A** 生成源防漂移根因 | `gen_systemd_units.py` 以 `docs/deploy/systemd-units-20260912.md` §2 ini 块为生成源;该源 30 个 service 的 `TimeoutStartSec` 停在 2026-09-12 迁移批旧值 ⇒ 重跑生成器装回云上 = **静默回退 #36 超时收口**(生产事故级) | ✅ 已修 |
| **B** doc §2 对齐 | 30 处 `TimeoutStartSec` 就地改写为云上实值(`--align-doc`);diff = 30 insert + 30 delete,**非 TimeoutStartSec 变更行 = 0** | ✅ 已改 |
| **C** 机检 + 挂链 | 审计器新增 `--check-doc`(逐字段全量比对 doc §2 生成物 vs 权威 unit 源);固化快照 `docs/deploy/systemd-units-cloud-snapshot.txt`;挂 `main-merge.sh` **7.8** | ✅ 已加 |
| **D** 机检非空转 | 注入错值(快照侧 / doc 侧各一次)→ **FAIL exit=1**;改前 30 处不一致 → exit=1;改后 → exit=0 | ✅ 见 §三 |
| **E** 举一反三全字段 | 80 unit 逐字段(doc §2 vs 云上)全量扫描:**仅 TimeoutStartSec 漂移**,其余字段(Restart/OnCalendar/Persistent/Environment/ExecStart/Standard*)0 差异 | ✅ 见 §四 |
| **F** 计数自洽 | §0=39 周期+1 backup_db=40 / §1.4=6+2+32=40 / §1.7=40 / §2 标题=39;`gen --check`=80 单元 —— **改前=改后** | ✅ 见 §五 |
| 前端/版本串 | 无前端改动 → 不 bump;§21 算法公示 N/A | — |

**风险闭合一句话**:以前「doc §2 与云上不一致」这件事**无人机检**——只有人肉扫,而人肉扫必然漏(这正是 s06 支线同类错误面扫描才发现的)。现在每次 merge main 都会拿 doc §2 生成物逐字段撞固化快照,不一致直接 FAIL 阻断。

## 一、实测:40 service 三列对照表(改前)

> 三列 = `unit | doc §2 ini(改前/HEAD) | 云上实值`(云上实值取自 `ssh 云上 grep -H TimeoutStartSec /etc/systemd/system/trade-*.service`,即权威真值,理由:云上单元手管、`git pull` 不更新,而 #36 收口是当天直接改在云上的)。
> 对照口径:本表 40 行 = **40 个 `trade-*.service` 全量**(timer 无此字段),无省略。

总 service 40; DIFF 30; OK 10

| unit | doc §2 ini(改前) | 云上实值 | 一致? |
|---|---|---|---|
| trade-update-all.service | 10800 | 0 | **不一致** |
| trade-intraday-snapshot.service | 1800 | 0 | **不一致** |
| trade-kelly-intraday-rerun.service | 200 | 600 | **不一致** |
| trade-backfill-evening.service | 0 | 0 | 一致 |
| trade-etf-national-team.service | 7200 | 0 | **不一致** |
| trade-etf-track-index.service | 1800 | 600 | **不一致** |
| trade-lof-track-index.service | 1800 | 0 | **不一致** |
| trade-fapi-daily.service | 600 | 0 | **不一致** |
| trade-futures-backfill.service | 7200 | 0 | **不一致** |
| trade-gold-night.service | 600 | 0 | **不一致** |
| trade-lhb-backfill.service | 7200 | 0 | **不一致** |
| trade-rzhb-backfill.service | 7200 | 600 | **不一致** |
| trade-turnover-backfill.service | 300 | 0 | **不一致** |
| trade-ab-direction-anchor.service | 900 | 600 | **不一致** |
| trade-nextday-plan.service | 600 | 600 | 一致 |
| trade-nextday-gap-check.service | 600 | 600 | 一致 |
| trade-s06-snapshot.service | 3300 | 3300 | 一致 |
| trade-check-data-gap.service | 600 | 600 | 一致 |
| trade-daily-brief.service | 900 | 600 | **不一致** |
| trade-daily-summary-supplement.service | 600 | 600 | 一致 |
| trade-brief-push.service | 300 | 600 | **不一致** |
| trade-fetch-news.service | 600 | 600 | 一致 |
| trade-pf-score-daily.service | 1800 | 600 | **不一致** |
| trade-pf-score-weekly.service | 14400 | 0 | **不一致** |
| trade-pf-stage0-nav.service | 21600 | 0 | **不一致** |
| trade-pf-stage0-overview.service | 25200 | 0 | **不一致** |
| trade-pf-stage0-risk.service | 18000 | 0 | **不一致** |
| trade-pf-stage0-manager.service | 12600 | 0 | **不一致** |
| trade-public-fund-daily.service | 1800 | 900 | **不一致** |
| trade-public-fund-estimation.service | 120 | 600 | **不一致** |
| trade-public-fund-full.service | 21600 | 0 | **不一致** |
| trade-public-fund-quarterly.service | 7200 | 0 | **不一致** |
| trade-overfit-monitor.service | 900 | 0 | **不一致** |
| trade-lab-auto.service | 7200 | 0 | **不一致** |
| trade-us-stock-morning.service | 7200 | 0 | **不一致** |
| trade-self-heal.service | 10800 | 600 | **不一致** |
| trade-schedule-monitor.service | 600 | 600 | 一致 |
| trade-check-monitor-heartbeat.service | 600 | 600 | 一致 |
| trade-backup-db.service | 7200 | 0 | **不一致** |
| trade-r2-consistency.service | 960 | 960 | 一致 |

### 1.1 漂移方向分两类(都危险,但方向相反)

- **doc 比云上宽松(会「回退」#36 的收口)**:doc 值 > 云上值的 **27 项**(如 `update-all` 10800→0、`pf-stage0-overview` 25200→0、`self-heal` 10800→600、`ab-direction-anchor`/`daily-brief` 900→600)。这类一旦装回云上 = 慢任务被旧硬超时强杀 = 正是 #36 要消灭的病。
- **doc 比云上收紧(会「制造新的强杀」)**:3 项反向——`kelly-intraday-rerun` 200(`<` 云上 600)、`public-fund-estimation` 120(`<` 云上 600)、`brief-push` 300(`<` 云上 600)。其中 `kelly-intraday-rerun` doc=200 距其脚本内层 `run_to 180` 只余 20s,装回云上即**逼近新的倒挂**(现有云上 600>180 余 420s,安全)。

> 结论:**不是单向"旧值都宽松",而是两个方向都有**,更能说明「doc §2 必须逐字段等于云上,不能凭方向直觉挑着改」。

## 二、逐条对齐(30/30)

用审计器新 `--align-doc` 就地把 doc §2 ini 块内「两侧同名且各出现一次」的 key 值改写为权威源值(只改 ```ini 块内,不动标题/prose/结构):

```
$ python3 scripts/systemd_timeout_gradient_audit.py --dump docs/deploy/systemd-units-cloud-snapshot.txt --align-doc
已对齐 30 处字段值 → docs/deploy/systemd-units-20260912.md
$ python3 scripts/systemd_timeout_gradient_audit.py --dump docs/deploy/systemd-units-cloud-snapshot.txt --check-doc
✓ 生成源(doc §2)与权威 unit 源一致(80 unit,逐字段全量比对通过)   # exit=0
```

diff 统计:`30 insertions(+), 30 deletions(-)`;非 `TimeoutStartSec` 变更行 = **0**(见 §六 校验命令)。

同步改了 doc 内**两处会与 ini 值打架的 prose**(§22 同一事实多登记点):
- §2.1 update-all 尾注 `(service TimeoutStartSec=10800)` → 注明「迁移批取 10800;2026-09-16 #36 收口为 `0`=无限」。
- §2.13 ab-direction-anchor env 注 `TimeoutStartSec=900 保险` → 注明「迁移批取 `900`,#36 收口为 `600`」。
- 并在 §2 头加一条**口径说明**:ini 块 = 云上当前实值;`- 脚本:… | ExitTimeOut=N` 行的 N 是**迁移源 plist 的 ExitTimeOut**(非云上现值),仅作迁移溯源;生成源必须与云上实值一致、由 7.8 机检兜底。

`gen_systemd_units.py --check` 仍报 **80 个 unit 待生成**(改前=改后,解析不受影响)。

## 三、机检(设计 + 挂链 + 非空转证据)

### 3.1 设计(复用而非新造抽象)

扩展现有审计器 `scripts/systemd_timeout_gradient_audit.py`(它已有「读云上 unit / 读 dump」能力),新增两模式:

| 模式 | 语义 | 退出码 |
|---|---|---|
| `--check-doc` | 用 `gen_systemd_units.parse_units` 解析 doc §2 → 逐字段(`key=value` 多重集,order-insensitive)比对权威 unit 源(service **+ timer**);报差异表 | 0=一致 / 1=有差异 |
| `--align-doc` | 就地把 doc §2 ini 块内字段值对齐权威源(仅覆盖两侧同名且各出现一次的 key;多值 key 保守跳过留人工) | 0 |

- 复用点:`gen_systemd_units.parse_units`(生成源解析)、本脚本既有 `parse_dump`(云上快照读取)、`read_units`(云上实值读取);**未引入任何新抽象层**。
- 权威源两档:`--units-dir /etc/systemd/system`(云上直跑)或 `--dump <快照>`(本地/merge 闸门用)。

### 3.2 挂链(main-merge.sh 7.8)

`scripts/main-merge.sh` 新增 **7.8**(紧随 7.6 文档口径机检、7.7 console 哨兵之前),`DRY_RUN` 时跳过:

```bash
if ! "$PY" "$REPO/scripts/systemd_timeout_gradient_audit.py" \
      --dump "$REPO/docs/deploy/systemd-units-cloud-snapshot.txt" --check-doc; then
  echo "✗ systemd 生成源(doc §2)与云上快照不一致, 阻断 merge(#189, 修复: 对齐 doc §2 或刷新快照)" >&2
  exit 1
fi
```

- **为什么用「固化快照」而不是直连云上**:merge 在 mac 本地跑,无 `/etc/systemd/system/trade-*`;故把云上实值固化为 `docs/deploy/systemd-units-cloud-snapshot.txt`(`@@@FILE:` dump 格式,80 unit),即 #189 任务书所说的「仓库内固化的真值清单」。快照刷新 = 云上 `sudo bash -c 'for f in /etc/systemd/system/trade-*.service /etc/systemd/system/trade-*.timer; do echo "@@@FILE:$(basename $f)"; cat $f; done' > 快照` 覆盖后同 commit 更新。
- 为什么挂在 merge 入口而不是只留在云上:这条风险的触发路径是「有人重跑生成器并把 doc 装回云上」,`gen_systemd_units` 源头永远在仓库 —— 在 doc 改动进 main 之前拦下,才能防患于未然(云上直跑只能事后发现)。

### 3.3 非空转证据(注入错值 → FAIL)

| 场景 | 命令 | 实测输出 | 退出码 |
|---|---|---|---|
| 改前(未对齐) | `--dump <快照> --check-doc` | `✗ ...差异字段 30 处`(逐行列出 30 unit) | **1** |
| 改后(已对齐) | 同上 | `✓ ...一致(80 unit,逐字段全量比对通过)` | **0** |
| **注入错值①(快照侧)** | 把快照 `trade-self-heal` 的 600 改 10800 → `--dump /tmp/snap_bad.txt --check-doc` | `trade-self-heal.service TimeoutStartSec doc=['600'] auth=['10800']` | **1** |
| **注入错值②(doc 侧)** | 把 doc 副本 `trade-self-heal` 的 600 改 9999 → `--check-doc --md /tmp/doc_bad.md` | `trade-self-heal.service TimeoutStartSec doc=['9999'] auth=['600']` | **1** |

两侧注入均 FAIL 且**差异行精确定位到 unit+field+两侧值**,证明机检非空转。

## 四、举一反三(§23.3):同模式字段全量扫描

**方法**:对 doc §2 生成物 vs 云上快照的 **80 unit 全量逐字段**比对(即 7.8 机检本身),列出所有差异的字段:

| 维度 | 清单 | 覆盖结果 |
|---|---|---|
| **同字段(doc §2 ini vs 云上,其余字段)** | `Restart` / `StartLimitIntervalSec` / `StartLimitBurst` / `OnCalendar` / `Persistent` / `Unit`=Section / `User` / `Type` / `WorkingDirectory` / `Environment` / `EnvironmentFile` / `ExecStart` / `StandardOutput` / `StandardError` / `WantedBy` 等全部 key | ✅ **0 差异**(80 unit 全量;唯一差异字段 = `TimeoutStartSec`) |
| **同数据源(同一事实的其他登记点)** | ①云上 unit 文件 ②doc §2 生成源 ③`gen_systemd_units.py` ④固化快照 ⑤`timeout-caliber-20260916.md`(#36 历史快照)⑥s06 报告 ⑦`schedule_monitor.sh`(阈值 900)⑧代码注释 | ✅ ①=②=④(机检);⑤⑥为带日期历史快照保留(§七 后记已指);⑦`r2-consistency` 960 与云上一致(见下);⑧无 per-service 现值副本 |
| **同组件(其他"生成/装配 systemd unit"的源)** | 全仓 grep `TimeoutStartSec` 仅 `gen_systemd_units.py` 一个生成器;`main-merge.sh`/审计器为校验方 | ✅ 无第二生成源 |
| **相关展示位** | 用户/运维能看到 unit 清单的:README、scripts/README、PARAMS、site-deployment、data-sources 等只涉**计数**(40),不涉单值 | ✅ 计数本次未动(见 §五) |

**脚本内 `TimeoutStartSec` 常量核查**(§22 代码内常量登记点):
- `scripts/schedule_monitor.sh:162/166` — 注释「外层 systemd TimeoutStartSec=**960**」用于 `r2-consistency`(云上实值 960 ✓,一致,非陈旧)。
- `scripts/gen_schedule_stats.py:300/896`、`scripts/with_lock.py:33` — 均为「`TimeoutStartSec=0` 不杀」的**语义说明**(概念,非 per-service 现值),无陈旧。
- 结论:**无第三处 per-service `TimeoutStartSec` 现值登记点漂移**。

## 五、计数自洽(改前/改后对照,§22 防两处口径打架)

doc 由 #160/s06 支线刚重算过计数;本次只改 `TimeoutStartSec` 值,不动任何计数。实测对照:

| 锚点 | 改前(HEAD) | 改后(工作区) | 一致? |
|---|---|---|---|
| §0 周期任务(必迁) | 39 | 39 | ✅ |
| §0/§1.4「其余 **32** = 40」分区 | 32(=6 shell + 2 python heredoc + 32) | 32 | ✅ |
| §1.7 = 40 | 40 | 40 | ✅ |
| §2 标题「39 个周期任务完整对照表」 | 39 | 39 | ✅ |
| `gen_systemd_units.py --check` | 80 个 unit(timer 40 / service 40) | 80 | ✅ |

**口径不打架**:§0 = 39 周期 + 1 backup_db = 40;§1.4 = 6+2+32 = 40;§1.7 = 40;三者与 80 单元(40 timer + 40 service)自洽,改前=改后。

## 六、同类错误面清单(§23.2 第三铁律:排查同类)

「生成源与云上实值不一致 ⇒ 重跑生成器静默回退」这一根因,同类面逐个排查:

| # | 同类面 | 是否同类问题 | 结论 |
|---|---|---|---|
| 1 | doc §2 其余 **39** 个 `TimeoutStartSec`(现全 40 项) | 同类 | ✅ 本次全量对齐(40/40 一致) |
| 2 | doc §2 **其他字段**(Restart/OnCalendar/Environment/…)与云上 | 同模式(生成源字段漂移) | ✅ 游离字段 0(§四 全量扫描) |
| 3 | **timer 块** `OnCalendar` vs 云上 | 同模式 | ✅ 0 差异(含 fetch-news `:01,45`、update-all 周日 22:30) |
| 4 | **其他"生成器 + 手管目标"对**(如 `schedule_stats` 生成 vs 云上) | 同结构 | ⏳ 未发现同类"doc 生成→装回手管目标"的第二对;若未来出现,套用 7.8 同法 |
| 5 | **`--check-doc` 挂在别处**? | — | merge 入口已挂;云上可直跑(`--units-dir`)做独立复核 |
| 6 | 快照本身陈旧(云上改了、快照没刷) | 反向盲区 | ⚠️ 见「遗留」:快照是"冻结真值",云上后续手改需人工刷新快照;已写入 §2 口径说明与下方遗留 |

**已覆盖 / 未覆盖边界诚实标注**:7.8 机检保证「doc §2 == 快照」;**不保证「快照 == 云上当前」**(云上手改后需刷快照)。这是"仓库内固化真值"方案的结构性边界(要完全消除需在云上加一个直连云上 unit 的巡检 timer,属另一支线)。

## 七、改动文件清单

**仓库(feat 分支 `feat/systemd-units-doc-sync-20261005`)**
- `docs/deploy/systemd-units-20260912.md` — §2 内 **30 处** `TimeoutStartSec` 对齐云上实值;§2 头加口径说明;§2.1/§2.13 两处 prose 同步
- `docs/deploy/systemd-units-cloud-snapshot.txt`(**新增**) — 云上 80 unit dump 固化快照(`@@@FILE:` 格式,权威真值)
- `scripts/systemd_timeout_gradient_audit.py` — 新增 `--check-doc` / `--align-doc` / `--md`;`read_all_units` / `unit_field_map` / `doc_sync` / `_align_doc_inplace`
- `scripts/main-merge.sh` — 新增 7.8 生成源一致性闸门
- `docs/ops/189-systemd-units-timeout-doc-sync-20261005.md`(本报告)

**云上**:本次**未改任何云上 unit**(只读取云上实值作对齐基准)。s06 unit(3300)为上支线所改,本次未动。

## 遗留 / 上报

- **快照刷新职责**:云上 unit 若被手改(正常运维),需同 commit 刷新快照 + 对齐 doc §2(否则 7.8 会 FAIL——这是**期望行为**:逼"doc/快照/云上"三者同频)。刷新命令见 §3.2。
- **未消除的盲区**:7.8 无法感知"云上被手改但快照没刷"(§六 #6)。彻底消除需云上直连 unit 的巡检(可选,建议后续单独立项)。

## 复现

```bash
# 0) 环境:本任务 worktree /Users/linhuichen/code/trade/.claude/worktrees/agent-a6e0cf880854efd8c
#    云上只读:ssh -i ~/tdsignal.pem ubuntu@122.51.111.173

# 1) 取云上实值(权威真值) → 固化快照
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 \
  'sudo bash -c "for f in /etc/systemd/system/trade-*.service /etc/systemd/system/trade-*.timer; do echo \"@@@FILE:\$(basename \$f)\"; cat \$f; done"' \
  > docs/deploy/systemd-units-cloud-snapshot.txt

# 2) 改前:生成源 vs 快照 → 期望 FAIL(30 处)
git show HEAD:docs/deploy/systemd-units-20260912.md > /tmp/doc_head.md
python3 scripts/systemd_timeout_gradient_audit.py --dump docs/deploy/systemd-units-cloud-snapshot.txt --check-doc --md /tmp/doc_head.md   # exit=1

# 3) 对齐 + 复检 → 期望 PASS
python3 scripts/systemd_timeout_gradient_audit.py --dump docs/deploy/systemd-units-cloud-snapshot.txt --align-doc
python3 scripts/systemd_timeout_gradient_audit.py --dump docs/deploy/systemd-units-cloud-snapshot.txt --check-doc   # exit=0

# 4) 机检非空转:注入错值 → 期望 FAIL
cp docs/deploy/systemd-units-cloud-snapshot.txt /tmp/snap_bad.txt
#   把 /tmp/snap_bad.txt 内 trade-self-heal 块的 TimeoutStartSec=600 改为 10800
python3 scripts/systemd_timeout_gradient_audit.py --dump /tmp/snap_bad.txt --check-doc   # exit=1

# 5) 计数自洽(改前=改后)
python3 scripts/gen_systemd_units.py --check   # 80 个 unit
grep -n "周期任务(必迁) | 39\|其余 \*\*32\*\* = 40\|§1.7 = 40\|39 个周期任务完整对照表" docs/deploy/systemd-units-20260912.md

# 6) diff 只含 TimeoutStartSec(应为 0)
git diff docs/deploy/systemd-units-20260912.md | grep -E '^[+-]' | grep -v '^[+-][+-]' | grep -vc 'TimeoutStartSec'
```

**配套 commit**:本报告 + `docs/deploy/systemd-units-20260912.md` + `docs/deploy/systemd-units-cloud-snapshot.txt` + `scripts/systemd_timeout_gradient_audit.py` + `scripts/main-merge.sh` 同属一个 commit。