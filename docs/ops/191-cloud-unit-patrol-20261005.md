# #191 云上 systemd unit 直连巡检(消 #189 闸门的「快照陈旧」窗口)

> 任务:#191(B/C 级,implementer)。分支 `feat/191-cloud-unit-patrol-20261005`。
> 登记:`docs/pending-features-index.md` #191;触发源 = #189 reviewer P2-1(2026-10-05 独立审查)。
> 日期:2026-10-05。云上:`ssh -i ~/tdsignal.pem ubuntu@122.51.111.173`(读写全权限)。

## 0. 速览

| 项 | 结论 |
|---|---|
| 问题 | #189 挂的 `main-merge.sh` 7.8 闸门锚仓库内**固化快照**,只保证「doc §2 == 快照」,**不保证「快照 == 云上当前 unit」**——云上手改 unit 未刷快照时闸门照样绿,之后重跑 `gen_systemd_units.py` 仍可能把 doc 旧值装回云上(#36 病根被关进「快照陈旧」窗口) |
| 方案 | 取**甲**:云上 `trade-cloud-unit-patrol.timer`(每日 **08:27**)直连 `/etc/systemd/system/trade-*.{service,timer}` 真文件 → 与仓库快照逐字段全量比对 → 漂移即 notify 告警。**只报警不改生产**(取舍见 §2) |
| 复用 | 复用 #189 的 `scripts/systemd_timeout_gradient_audit.py`,新增 `--check-snapshot` 模式(直连真 unit vs 快照,逐字段 + 集合双向比对) |
| 云上状态 | 新增 `trade-cloud-unit-patrol.{timer,service}` 已 **enable + active**,NEXT = `Tue 2026-10-06 08:27:00 CST`;`is-enabled=enabled` `is-active=active` |
| 三源闭合 | 新增后云上 = 41 timer + 41 service = **82 unit**;doc §2 解析 82 ✓;仓库快照 82 ✓;`--check-doc`(doc vs 快照)PASS ✓;云上直连 `--check-snapshot`(云上 vs 快照)PASS ✓ |
| 负样本 | mock 漂移(改 1 个 `TimeoutStartSec`)→ 审计 rc=1、wrapper rc=1、notify dry-run 邮件体含 `unit | field | cloud | snapshot` 表;正向(无漂移)rc=0 静默 ✓ |
| 回滚 | `sudo systemctl disable --now trade-cloud-unit-patrol.timer` + `rm /etc/systemd/system/trade-cloud-unit-patrol.{timer,service}` + `sudo systemctl daemon-reload`(§10) |
| 生产未动 | 云上真 unit 与 #191 前旧快照(80)比对:**差异 = 仅 2 个新增 patrol unit,0 处字段变更**(既有 80 unit 一字未动) |
| 部署依赖 | 巡检脚本在**代码仓**(云上 `git pull` 才生效);merge 进 main + 云上 pull 前,service 因 `ConditionPathExists` 跳过(实测 `ConditionResult=no`)——见 §8 |

**变更文件**(全部本分支,绝对路径以仓库根为基准):
- `scripts/systemd_timeout_gradient_audit.py`(加 `--check-snapshot` / `--snapshot`)
- `scripts/cloud_unit_patrol.sh`(**新增**,云上 timer 的包装)
- `docs/deploy/systemd-units-20260912.md`(加 §2.38 patrol 两 unit + 计数重算 39→40 / 40→41 / 80→82)
- `docs/deploy/systemd-units-cloud-snapshot.txt`(从云上刷新,80→82)
- 计数登记点同步(§5 清单):`README.md`、`scripts/README.md`、`docs/data-sources.md`、`docs/site-deployment.md`、`docs/PARAMS.md`、`docs/r2-deployment.md`、`scripts/check_doc_staleness.py`
- `docs/ops/189-...md` §六#6 / 边界段补指针;`docs/pending-features-index.md` #191 状态列

## 1. 问题定义(要消掉的窗口)

```
doc §2 (生成源)  ──7.8 闸门──►  仓库快照 (docs/deploy/systemd-units-cloud-snapshot.txt)
                                       ▲
                                       │  ✗ 无任何机制保证这一段
                                       │
                                 云上 /etc/systemd/system/trade-*.{service,timer}
                                 (手动管理,git pull 不更新)
```

7.8 闸门(`scripts/main-merge.sh`)比对 **doc §2 vs 快照**,任一字段差或集合差(`only_doc`/`only_auth`)即 FAIL。它判定了"仓库内两个副本一致",但**快照是人在某一刻从云上 dump 下来的**,一旦云上手改(如把某 unit 的 `TimeoutStartSec` 调回去)而快照没跟着刷:

1. 7.8 仍绿(它不读云上);
2. 之后任何人重跑 `scripts/gen_systemd_units.py --align-doc` 或按 doc §2 重装 unit,就可能把 doc 里的**旧值**装回云上——#36 修好的超时梯度被悄悄还原。

⇒ 需要第三条腿:一个**直连云上真 unit**的巡检,把它与仓库快照对齐,漂移即报警。这样三源(doc §2 / 快照 / 云上)才真正闭合。

## 2. 方案选择:为什么取「甲」(只报警)

| 维度 | 甲:云上巡检 timer,漂移→告警 | 乙:折进既有云上任务,dump 自动刷快照并回写仓库 |
|---|---|---|
| 是否改生产 | 否(只读真 unit + 发告警) | **会**(自动改快照文件) |
| 回写仓库 | 不需要 | 云上把快照写回仓库 → 必然要 push main |
| 与 §8 冲突 | 无 | **冲突**:§8 规定 main 只走 `scripts/main-merge.sh`,云上自动 push main = 违规;若改"只落云上本地文件",则快照在云上、仓库里还是旧的,7.8 闸门读的是仓库快照 ⇒ 消不掉窗口,等于没做 |
| 生产稳定性(§14/P0) | 告警是人工事件,可审计、可回滚 | 自动改生产描述文件,漂移被"自动刷平",问题被掩盖而非暴露 |
| 对"云上手改"的语义 | 手改=事件:要么手改有误→回滚该 unit;要么有意改→刷新快照 + 对齐 doc §2 走 merge | 手改被静默吸收,失去"发现意图变更"的价值 |
| 结论 | **取甲** | 否(违反 §8;且"本地写回不回 push"做不到闭合) |

甲的代价 = 漂移修复仍需人工一步(刷新快照 + 对齐 doc)。但这一步天然就该走 §8 的 `main-merge.sh`,且是"有人有意变更"时才发生——把不可逆的"自动改生产"换成一次可审计的人工动作,符合生产稳定性 P0。

## 3. 实施

### 3.1 审计器:新增 `--check-snapshot`(`scripts/systemd_timeout_gradient_audit.py`)

- 新增常量 `SNAPSHOT_REL_PATH = docs/deploy/systemd-units-cloud-snapshot.txt` 与 `default_snapshot_path()`。
- 新增 `_set_diffs(a_units, b_units)`:逐字段(经 `unit_field_map`)算差异 + 双向集合差(`only_cloud` / `only_snap`)。
- 新增 `snapshot_sync(args, units)`:权威源(直连 `--units-dir /etc/systemd/system` 或 `--dump`)vs 快照逐字段全量比对;漂移打印 `unit | field | cloud | snapshot` 表并 `exit 1`,一致打印 `✓` 并 `exit 0`;快照缺失/空 `exit 2`。
- 新增 argparse:`--check-snapshot`(store_true)、`--snapshot`(默认 None→`default_snapshot_path()`)。

`main()` 分派:`if args.check_snapshot: units = read_all_units(args) ...; return snapshot_sync(args, units)`。

### 3.2 云上包装:`scripts/cloud_unit_patrol.sh`(新增)

- `set -u`;`REPO`(默认 `/Users/linhuichen/code/trade-data`,云上由 unit 注入 `/home/ubuntu/code/trade-data`)、`GIT_REPO`、`PY`(用 `$REPO/.venv/bin/python`)。
- `SNAPSHOT` 默认 `$GIT_REPO/docs/deploy/systemd-units-cloud-snapshot.txt`;`AUDIT_ARGS=( --snapshot "$SNAPSHOT" --check-snapshot )`;若设 `CLOUD_UNIT_PATROL_ARBITER_DUMP` 则前置 `--dump <path>`。
- rc!=0 → 取差异段(`sed -n '/^unit /,$p'`)构造正文 → `scripts/notify.py "[告警] 云上 systemd unit 与仓库快照漂移" "<body>…差异: unit | field | cloud | snapshot:<br>…" --severe --from-prefix "[告警]" --dedup-key cloud_unit_patrol_drift --dedup-window 21600`。
- rc=0 → 静默(仅写日志)。日志 `$REPO/data/logs/cloud_unit_patrol_launchd.log`(**脚本自己写固定名 log,故 unit 刻意不设 `StandardOutput` append**——§1.4 例外条款第 7 个 shell 型 service)。
- 自测桩(生产不设,照 `check_r2_consistency` 先例):`CLOUD_UNIT_PATROL_ARBITER_DUMP` / `CLOUD_UNIT_PATROL_SNAPSHOT` / `CLOUD_UNIT_PATROL_NOTIFY_DRYRUN=1`。

### 3.3 云上 unit(手动管理;`git pull` 不更新)

`trade-cloud-unit-patrol.timer`:
```ini
[Unit]
Description=Trade cloud-unit-patrol daily 08:27 (#191 云上 unit 直连巡检)
[Timer]
OnCalendar=*-*-* 08:27:00
Persistent=true
[Install]
WantedBy=timers.target
```
`trade-cloud-unit-patrol.service`:
```ini
[Unit]
Description=Trade cloud-unit-patrol (#191 云上 unit 直连 vs 仓库快照漂移巡检)
ConditionPathExists=/home/ubuntu/code/trade-data/scripts/cloud_unit_patrol.sh
[Service]
User=ubuntu
Type=oneshot
WorkingDirectory=/home/ubuntu/code/trade-data
Environment=GIT_REPO=/home/ubuntu/code/trade-data-signal
Environment=REPO=/home/ubuntu/code/trade-data
Environment=MAIN_REPO=/home/ubuntu/code/trade-data
ExecStart=/bin/bash /home/ubuntu/code/trade-data/scripts/cloud_unit_patrol.sh
Environment=PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
EnvironmentFile=/home/ubuntu/code/trade-data/.env
# 外层 600 > 内层(读 ~80 个小 unit 文件 + python 比对,秒级;外层即唯一看门狗,留梯度)
TimeoutStartSec=600
```

**时点论证(§14)**:08:27 属开盘前闲时,**避开**盘后 15:35/16:00/17:50/20:35/22:00 与盘中 09:30-15:30;避开心跳巡检 `trade-check-monitor-heartbeat` 的 `:11/:26/:41/:56` 分钟位。实测云上该时段邻居:仅 `08:00 rzhb-backfill` 与 `09:25 intraday-snapshot`,08:27 无冲突。每日跑不限交易日——「快照 == 云上」是不变量,周末手改同样要抓。

### 3.4 doc 生成源与快照刷新

- `docs/deploy/systemd-units-20260912.md` 新增 `### 2.38 cloud-unit-patrol`,含上述 timer/service 两个 ini 块;计数链 `39 周期 = 40 timer`→`40 周期 = 41 timer`(§0 重算注、§1.4 = 7 shell 型 / §1.7 = 41 service / §2 标题 40 周期 / §7.9)。
- `docs/deploy/systemd-units-cloud-snapshot.txt` 从云上重新 dump(80→82);与旧快照差异 = **仅新增的 2 个 patrol unit**。

## 4. 自验(逐条过验收口径)

### ① 云上 timer 真 enable + start
```
$ systemctl list-timers "trade-cloud-unit-patrol*" --all --no-pager
NEXT                        LEFT     LAST PASSED UNIT
Tue 2026-10-06 08:27:00 CST 11h left n/a  n/a    trade-cloud-unit-patrol.timer trade-cloud-unit-patrol.service
$ systemctl is-enabled trade-cloud-unit-patrol.timer   → enabled
$ systemctl is-active  trade-cloud-unit-patrol.timer   → active
$ date -d 2026-10-06 +%A                                → Tuesday   # 日历核对(2026-10-06 确为周二)
$ ls -1 /etc/systemd/system/trade-cloud-unit-patrol.*   → .service / .timer 均在
$ systemd-analyze verify <两个 unit>                     → 本 unit 无报错(输出仅他 unit 的告警)rc=0
```
service 首次 `systemctl start` 实测跳过:`ConditionResult=no` `Result=success` `ActiveState=inactive`(因巡检脚本尚未落到云上代码仓,见 §8)。

### ② 三源正向 PASS(82 unit)
```
# doc §2 vs 快照:
$ python3 scripts/systemd_timeout_gradient_audit.py --dump docs/deploy/systemd-units-cloud-snapshot.txt --check-doc
✓ 生成源(doc §2)与权威 unit 源一致(82 unit,逐字段全量比对通过)          rc=0
# 云上真 unit vs 刷新后快照(云上直跑,新版脚本):
$ python3 /tmp/audit_new_191.py --units-dir /etc/systemd/system --check-snapshot --snapshot /tmp/snap_new_191.txt
✓ 云上 unit 与仓库快照一致(82 unit,逐字段全量比对通过)                     rc=0
$ ls -1 /etc/systemd/system/trade-*.timer | wc -l   → 41 ; *.service → 41   (=82)
$ python3 scripts/gen_systemd_units.py --check       → 82 个 unit 待生成     rc=0
```

### ③ 负样本:漂移真会报警(mock,未碰生产 unit)
```
# 复制快照为 mock,把 1 个 TimeoutStartSec=600 改成 601(模拟云上手改)
$ python3 /tmp/audit_new_191.py --dump /tmp/mock_drift_191.txt --check-snapshot --snapshot /tmp/snap_new_191.txt
✗ 云上 unit 与仓库快照漂移:差异字段 1 处,仅云上 0 unit,仅快照 0 unit
unit                                 field            cloud   snapshot
trade-ab-direction-anchor.service    TimeoutStartSec  ['601'] ['600']        rc=1
# 包装层(notify --dry-run):
$ bash cloud_unit_patrol.sh        # CLOUD_UNIT_PATROL_ARBITER_DUMP=mock, NOTIFY_DRYRUN=1
[notify][dry-run] email subject=[告警] 云上 systemd unit 与仓库快照漂移
[notify][dry-run] email body=…unit | field | cloud | snapshot: trade-ab-direction-anchor.service TimeoutStartSec ['601'] ['600']…
wrapper_rc=1
# 正向(无漂移):
$ bash cloud_unit_patrol.sh        # 同桩,dump=快照本身
✓ 云上 unit 与仓库快照一致(82 unit…)  wrapper_rc=0        # 无告警(仅日志)
```
> 负样本全程在 `/tmp`(mock dump + 临时 mini-repo),**未改任何生产 unit**;生产 unit 与 #191 前旧快照(80)比对差异 = 仅 2 个新增,0 处字段变更 → 无需"复原"(无改动可复原)。告警体已含「哪个 unit / 哪个字段 / 云上值 vs 快照值」(§23.10 邮件=飞书同源同体,生产 `REPO` 有 `config/feishu.json` 时双发)。

### ④ 回滚路径(见 §10,逐条可执行)

### ⑤ §22 一致性登记点(见 §5 清单,逐点已过)

## 5. §22 一致性登记点同步清单(同一事实 = "云上 trade-*.timer 数" 的多处副本)

| 登记点 | 旧 | 新 | 备注 |
|---|---|---|---|
| `docs/deploy/systemd-units-20260912.md`(生成源,§0/§1.4/§1.7/§2/§7.9 + 新增 §2.38) | 39 周期/40 timer/80 unit | 40 周期/41 timer/82 unit | 权威生成源 |
| `docs/deploy/systemd-units-cloud-snapshot.txt` | 80 | 82 | 从云上刷新 |
| `README.md:403` / `:418` | 40 | 41 | |
| `scripts/README.md:137` | 40 | 41 | |
| `docs/data-sources.md:266` | 40 | 41 | |
| `docs/site-deployment.md:621` / `:843` | 40 | 41 | |
| `docs/PARAMS.md:859` | 40 | 41 | |
| `docs/r2-deployment.md:532` | 37 | 41 | **#188 计数重算清单里漏的点,本次补上** |
| `scripts/check_doc_staleness.py:326` | 40 | 41 | **代码内常量登记点**(§22) |
| `docs/ops/189-...md` §六#6 / 边界段 | 「遗留」 | 指向本报告 | 指针 |

机检:`python3 scripts/check_doc_staleness.py` → ✓ 通过(扫 229 文件)。历史日期报告(`docs/ops/cloud-healthcheck-20261003/*`、`s06-timeout-gradient-20261005.md`、`docs/deploy/timeout-caliber-20260916.md` 等)按当时实测值保留不改(删改反而失真,同 #188 §2.6 口径)。

## 6. §23.3 举一反三(同模式 / 同数据源 / 同组件还被谁用)

| 面 | 是否同源 | 处理 |
|---|---|---|
| 云上**其他**手动管理的 unit 描述文件 | 同模式(手动 + git pull 不更新) | 本巡检覆盖**全部** `trade-*.{service,timer}`(82),不止新增的 patrol 自己 |
| 仓库快照 `systemd-units-cloud-snapshot.txt` 的消费者 | 同数据源 | 7.8 闸门(`main-merge.sh`)、`--check-doc`、本巡检三方;刷新快照后三方口径已对(§5) |
| `gen_systemd_units.py --check` / `--align-doc` | 同组件(会写 doc / 可装回云上) | 正是"#36 被装回"的出口;本巡检把它的前提(快照==云上)补上,§2 已论证 |
| "云上 unit 计数"这一事实的多登记点 | 同数据源 | §5 全表逐个过(含 #188 漏的 `r2-deployment.md:532`) |
| `check_r2_consistency`(#160)等其他云上巡检 | 同模式(云上 timer + notify + 固定名 log + 自测桩) | 本脚本照其先例写(包装结构 / 桩命名 / log 约定) |
| 本机 mac 既有 launchd 巡检(已废弃) | 同名残留 | 本机不跑生产巡检(memory `local-dev-cloud-prod-split`);脚本本机仅可手动跑 |

## 7. §23.2 同类错误面(修 bug 三铁律之"排查同类")

本次非修 bug 而是补盲区,但同类面已查:

- **同类窗口是否还有别处?** 7.8 只覆盖 systemd unit 这一族;同构的"仓库内固化真值 vs 线上真值"还有 `check_r2_consistency`(#160,覆盖数据产物本地 vs R2)与 `check_universe_alignment`(入样宇宙)——这两族**已有**各自直连线上真值的巡检,不需要再补。本族是唯一缺口,本次补齐。
- **快照刷新是否有别的入口?** 只有人肉 dump(`--dump` 到快照),无自动写回(#191 刻意不做,§2)——已在本报告与脚本头注、unit Description 三处写明"漂移=人工事件"。

## 8. 部署依赖与生效时序(重要)

巡检**脚本**在**代码仓**;云上 `/home/ubuntu/code/trade-data/scripts` 是 `/home/ubuntu/code/trade-data-signal/scripts` 的软链(`git pull` 才更新)。故:

1. 本 feat 合并进 main + 云上 `git pull` 之前:service 的 `ConditionPathExists=/home/ubuntu/code/trade-data/scripts/cloud_unit_patrol.sh` 为假 ⇒ **service 跳过**(实测 `ConditionResult=no`),不会误报;
2. 合并 + pull 之后:脚本 + 新版审计器 + 刷新后快照(82)同时到位 ⇒ 08:27 首跑应 rc=0 静默;若届时云上 unit 又被人改过未刷快照 ⇒ 正确报警。
3. **合并前云上仓库快照仍是旧版(80)**,此刻若手动跑巡检会报 `only_cloud 2`(那 2 个新 patrol unit)——这是"仓库快照未跟上"的**正确**信号,非故障;随 merge+pull 消解。

⇒ 主控 merge 本分支后,请提醒云上执行 `git pull`(或等 update_all 17:50 O1 统一 deploy 链的下一次 pull)。

## 9. 复现(命令全集)

```bash
# 分支
git checkout feat/191-cloud-unit-patrol-20261005

# 本地:三源一致性
python3 scripts/systemd_timeout_gradient_audit.py --dump docs/deploy/systemd-units-cloud-snapshot.txt --check-doc   # rc=0,82
python3 scripts/gen_systemd_units.py --check                                                                         # rc=0,82
python3 scripts/check_doc_staleness.py                                                                               # rc=0
bash -n scripts/cloud_unit_patrol.sh; python3 -c "import ast;ast.parse(open('scripts/systemd_timeout_gradient_audit.py').read())"

# 云上:正向 / 负样本(只读 + dry-run,不改生产)
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173
  systemctl list-timers "trade-cloud-unit-patrol*" --all --no-pager
  systemctl is-enabled trade-cloud-unit-patrol.timer; systemctl is-active trade-cloud-unit-patrol.timer
  python3 <新版审计器> --units-dir /etc/systemd/system --check-snapshot --snapshot <刷新后快照>   # rc=0,82(正向)
  # 负样本:快照复制为 mock,改 1 个值 → 审计 rc=1;包装层 + NOTIFY_DRYRUN=1 → 发 dry-run 告警
```

## 10. 回滚路径(可执行,§25 可逆)

> 本任务**只新增** unit,未改/未删任何既有 unit ⇒ 无需 `.bak`(无被覆盖的旧版本);变更前状态已留档:`/home/ubuntu/backup/191-cloud-unit-patrol/{units-after,timers-after}.txt`(变更后清单,与旧快照比对可证"仅新增 2 个")。

**禁用 + 删除**(完全回到 #191 前):
```bash
sudo systemctl disable --now trade-cloud-unit-patrol.timer
sudo rm /etc/systemd/system/trade-cloud-unit-patrol.timer /etc/systemd/system/trade-cloud-unit-patrol.service
sudo systemctl daemon-reload
sudo systemctl reset-failed trade-cloud-unit-patrol.service 2>/dev/null || true
```
**只禁用不删**(想留文件):
```bash
sudo systemctl disable --now trade-cloud-unit-patrol.timer
```
**代码侧回滚**:revert 本分支 commit(`scripts/cloud_unit_patrol.sh` 删除、`systemd_timeout_gradient_audit.py` 去掉 `--check-snapshot`、快照回 80、§5 各计数点回 40/37)——走 `main-merge.sh` 正常流程,不 force。

**恢复**(若之后想重装):重跑 `bash scripts/gen_systemd_units.py` 生成 §2.38 两 unit → 落 `/etc/systemd/system/` → `systemctl enable --now trade-cloud-unit-patrol.timer`。

## 11. 遗留 / 交接

- **P3 观察项**:08:27 首跑(merge+pull 后首个交易日)确认 rc=0 静默一次,即可判"上线稳定";若首跑 `ConditionResult=yes` 但 rc!=0,按 §3.2 告警处置。
- **跨分支冲突提示(§23.11)**:`scripts/check_doc_staleness.py:326` 本分支 40→41;#188 分支(s06)曾把该行 37→40(已随 `d6ce93405` 入 main)。若 #188 续跑再次落笔该行,merge 时可能在该行冲突——届时以 **41** 为准。
- 未新增/改动任何 s06 相关文件(`upload_r2.py` / `check_data_integrity.py` / `s06_snapshot.sh` 一字未碰,任务 #188 边界)。