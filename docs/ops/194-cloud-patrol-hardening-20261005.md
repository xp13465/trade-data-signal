# #194 云上巡检脚本路径加固 + 环境守卫(cloud_unit_patrol.sh)

- 任务:#194(接 #191 §0 亲验发现 + reviewer P2 必修两条)
- 分支:`feat/194-cloud-patrol-hardening-20261005`
- commit:`8a74e779b`(本轮三条修法)/ 本轮 F2+F3 续跑 commit 见文末
- 产物:本体 `scripts/cloud_unit_patrol.sh` · 自测 `scripts/cloud_unit_patrol_selftest.sh` · 本报告
- 关联:#191(云上巡检引入)/ #189(main-merge 7.8 闸门)/ #188(静默盲区同族)/ #160(近邻同款脚本)

---

## 1. 改动本体

脚本角色:`trade-cloud-unit-patrol.timer`(云上每日 08:27)包装 `scripts/cloud_unit_patrol.sh` → 直连
`/etc/systemd/system/trade-*.{service,timer}` 真文件 vs 仓库固化快照
`docs/deploy/systemd-units-cloud-snapshot.txt` 逐字段全量比对 → 漂移即 `notify --severe`。
**仅告警不改生产**(不改 unit / 不 enable / 不 push)。

### 1.1 三条路径修法(commit `8a74e779b`,#191 §0 亲验)

病灶:原第 36/37 行对 `REPO`/`GIT_REPO` 写死 mac 默认值(`/Users/linhuichen/...`),生产靠 unit 的
`Environment=REPO=/GIT_REPO=` 兜住。一旦那两行丢失 → 拿 mac 路径 `cd`/调 python,rc=127,且
`$PY` 同源于坏 `REPO` ⇒ **notify 一样调不动** ⇒「失败恰恰是最没声音的时候」(与 #188 同族)。

1. **fail-fast(脚本 `#194` 校验段)**:`cd`/调 python **之前**校验 `REPO` 目录、`GIT_REPO` 目录、
   `$REPO/.venv/bin/python`、`$PY` 可执行;不成立即把「实际取值 + env/unit 配置可能丢失」提示打到
   stderr 并 `exit 2`(显式可见,不再哑火)。
2. **去 mac 隐式默认**:`env 覆盖 > 从 $0 推导 > fail-fast`,绝不猜 mac 路径继续跑。推导依据:
   `<REPO>/scripts` 是指向 git 仓 `scripts/` 的 symlink(云 `trade-data/scripts`→`trade-data-signal/scripts`;
   mac `trade-data/scripts`→`trade/scripts`)⇒ `$0` 的 scripts **父目录**=REPO、**解 symlink 后**父目录=GIT_REPO。
3. **失败出口兜底**:失败本身有出口 —— ①stderr(unit 无 `StandardOutput` append ⇒ 进 systemd journal)
   ②固定位置日志(见 §1.3 F3)。

### 1.2 F2 环境守卫(reviewer 实测事故根治 —— 本轮新增)

**事故**:本脚本**云上专用**。reviewer 用旧版在 mac 上跑自测,旧脚本不理会沙箱 env、权威源读不到
(旧脚本 `audit rc=2`)→ 被判「漂移」→ **真发出 1 邮件 + 1 飞书 severe**(本地取证
`trade-data/data/logs/cloud_unit_patrol_launchd.log` `21:24:30` 段:email + feishu 真发)。

**判据(仓库无先例,自定并明写)**:权威源「存在且像真的」才允许巡检;不成立一律**只写日志 +
`exit 3`,绝不调用 notify**。权威源与 `systemd_timeout_gradient_audit.py` 的 `read_all_units` **同源**
(避免「守卫看的源 ≠ 审计读的源」):
- ①生产模式(无 dump):unit 目录(默认 `/etc/systemd/system`,或 `CLOUD_UNIT_PATROL_UNITS_DIR` 覆盖)
  存在 **且含 `trade-*.service`**;
- ②测试桩模式(`CLOUD_UNIT_PATROL_ARBITER_DUMP` 已设):dump 文件存在且非空;**该模式纯诊断,
  永不发通知**(有意设桩=在做测试,不该惊动用户)。

`exit 3` 非 0:让「巡检自身没跑成」在 systemd/监控里可见(不做静默)。

### 1.3 F3 失败出口②可写性(本轮新增)

**事故**:出口② `/tmp/cloud_unit_patrol_fatal.log` 曾被 root 属主化(某次以 root 跑留下 644 root
文件)→ 之后 ubuntu 身份 append 被拒 → **出口②降级失效**(云上实测 `Permission denied`)。

**修法**:文件名带 `$(id -un)` 后缀(默认 `${TMPDIR:-/tmp}/cloud_unit_patrol_fatal.$(id -un).log`),
每用户独立、避开 root/他人残留;出口①(stderr→journal)恒在,即使文件写不进也有 journal 兜底。
`CLOUD_UNIT_PATROL_FATAL_LOG` 可覆盖。顺手清理云上 root 残留(见 §3)。

### 1.4 范围

只改 `scripts/cloud_unit_patrol.sh` + 新增 `scripts/cloud_unit_patrol_selftest.sh`。
**未碰** unit 文件 / doc §2 / 快照 / `upload_r2.py` / `s06_snapshot.sh` / `check_data_integrity.py`(后三者属 #188)。

---

## 复现段

自测脚本:`bash scripts/cloud_unit_patrol_selftest.sh`(无副作用,全在 `mktemp` 沙箱)。云上/CI 有
python3 时全跑(T0-T7 共 8 项);`T4-T7` 需 python3。要点覆盖:T1-T3 fail-fast、T4 `$0` 推导
(symlink 布局)、T5 环境守卫(权威源不存在→exit 3 且**哨兵证明 notify 未被调用**)、T6 守卫不误伤
(像云上+漂移→notify 可达)、T7 dump 诊断模式不发通知。

### 云上怎么验(本轮实测)

```bash
# 0) 备份(§25):先 .bak 后改,测完复原
S=/home/ubuntu/code/trade-data-signal/scripts/cloud_unit_patrol.sh
cp -a "$S" "$S.bak-20261005b"; md5sum "$S" "$S.bak-20261005b"   # 两 md5 应相等
# 1) 放置被测版本(scp 到 /tmp 再 cp 入位),核对 md5 == 本地
# 2) 正向·带 env(生产同款)      → rc=0,日志与基线逐字一致
REPO=/home/ubuntu/code/trade-data GIT_REPO=/home/ubuntu/code/trade-data-signal bash "$S"
# 3) 正向·不带 env(验 $0 推导)  → rc=0
env -u REPO -u GIT_REPO bash /home/ubuntu/code/trade-data/scripts/cloud_unit_patrol.sh
# 4) 漂移 + dry-run(证明守卫不误伤、告警可达、且不真发)
mkdir -p /tmp/cup_units; printf '[Service]\nTimeoutStartSec=600\n' > /tmp/cup_units/trade-mock-xyz.service
CLOUD_UNIT_PATROL_UNITS_DIR=/tmp/cup_units CLOUD_UNIT_PATROL_NOTIFY_DRYRUN=1 \
  REPO=/home/ubuntu/code/trade-data GIT_REPO=/home/ubuntu/code/trade-data-signal bash "$S"   # rc=1,notify --dry-run
# 5) F3 可写性:REPO 打坏 → 落到带 id -un 的用户可写路径
REPO=/nonexistent/xyz GIT_REPO=/home/ubuntu/code/trade-data-signal bash "$S"                # rc=2
ls -l /tmp/cloud_unit_patrol_fatal.ubuntu.log     # ubuntu:ubuntu,可重复追加
# 6) 复原:cp -a .bak 回原位,md5 回到基线,git status 干净,日志恢复基线 3 行
```

### mac 零通知取证

```bash
# 默认权威源(/etc/systemd/system 在 mac 不存在)→ 守卫直接拦下,不进 audit、不碰 notify
REPO=/Users/linhuichen/code/trade-data GIT_REPO=<repo> bash scripts/cloud_unit_patrol.sh
# → [cloud_unit_patrol] SKIP: ... rc=3
```
日志 `.../cloud_unit_patrol_launchd.log` 只新增 `[skip] ... 退出码=3(环境守卫跳过)` 一段,
**无任何 notify 行**(对照上面同文件 `21:24:30` 旧版事故段的 email/feishu 行即知差别)。
另有自测 T5 用哨兵 `notify.py` 桩证明「exit 3 时 notify 从未被调用」(sentinel 不存在)。

### md5 对账

- 基线(改动前,= `git show 50090c642:scripts/cloud_unit_patrol.sh`):`e51a270ddb662ed476e77ed3b841ae57`
- 云上被测版本 = 本地提交版本(逐位一致,见 §3)

---

## 3. 云上复原证据(.bak 与 md5)

| 步骤 | 证据 |
|---|---|
| 改动前基线 md5 | `e51a270ddb662ed476e77ed3b841ae57` |
| 备份 | `cp -a $S $S.bak-20261005b`;`md5sum` 两份相等 |
| 被测版本 md5 | 第二轮 = `e6c493b794a0ae72507e3a1949fbedee`(= 本轮本地提交版本) |
| 复原后 md5 | 回到 `e51a270ddb662ed476e77ed3b841ae57`(= 基线) |
| 复原后 git 状态 | `git status --porcelain scripts/cloud_unit_patrol.sh` → 0 行(该文件干净) |
| 日志复原 | 巡检日志恢复为基线 3 行(`21:00:37` 段) |
| root 残留清理 | 删前 `ls -l /tmp/cloud_unit_patrol_fatal.log` = `root root 644`;`sudo cat` 留内容(2 行,含 reviewer 于 `/tmp/r194test` 的复现);`sudo rm -f` 后 `ls` = No such file |
| 临时清理 | `.bak-20261005b` / `/tmp/*.v2` / `/tmp/cupst2` / `/tmp/cup_units` 已删 |

**恢复路径**(§25④):云上原版 = `git show 50090c642:scripts/cloud_unit_patrol.sh`;
`.bak` 若误删,用此命令取回即可。

---

## 4. 同类错误面 + 举一反三

- **同类错误面(#23.2)**:本文件内所有 `cd` / 调用点(`mkdir -p $LOGDIR`、`cd $REPO`、
  两处 `"$PY" scripts/...`)全在 4 条 fail-fast 校验**之后**;`$PY` 派生顺序在 `REPO` 校验之后
  (消「PY 同源于坏 REPO」)。环境守卫与 audit 读同一权威源(无「守卫 ≠ 审计」缝隙)。
- **举一反三(#23.3,引用 reviewer 结论,不自行扩面)**:全仓同款「写死 mac 默认 REPO/GIT_REPO」
  脚本 **57 个**,其中 **36 个正被云上 unit 调用** —— 与 #194 是同一「Environment 一丢就静默哑火」
  病灶(近邻 `check_r2_consistency.sh` 同为巡检且 notify 同源于 `$PY`,风险最高)。
  正解 = 抽共享 `resolve_repo` 单点守卫(单点优于逐文件补丁)。**本轮按派单只改本文件;这两条
  (F1「fail-fast 无 notify + 全站无 failed-unit 巡检」+ 共享 `resolve_repo`)由主控登记为独立任务。**

---

## 5. 必读交接点

1. **部署依赖**:本次只 commit 到 `feat/194-cloud-patrol-hardening-20261005`,**未 push main**。
   合并走 `scripts/main-merge.sh`;云上需 `git pull` 后才生效(当前云上文件已是**复原后的旧版**,
   timer 每日 08:27 仍跑旧版直到 pull)。**不动 unit / doc §2 / 快照**(否则撞 #189 的 7.8 一致性闸门)。
2. **与 #189 7.8 闸门关系**:7.8 保证「doc §2 == 快照」;本巡检保证「快照 == 云上当前」;二者互补,
   **本巡检不在任何推送链上、不阻断谁**(仅告警)。改本脚本不改快照 → 不触发 7.8。
3. **行为变更须知(运维)**:新增 `exit 3` 语义 = 「非云上/权威源不可用 → 跳过且不告警」。
   云上生产(unit 环境)不会走到它;若在云上意外出现 `exit 3`,说明 `/etc/systemd/system` 下
   已无 `trade-*.service`(与预期严重不符,应当排查)。
4. **新增可注入桩**(生产不设):`CLOUD_UNIT_PATROL_UNITS_DIR`(权威目录覆盖)、
   `CLOUD_UNIT_PATROL_FATAL_LOG`(失败日志路径覆盖);既有 `..._ARBITER_DUMP` / `..._SNAPSHOT` /
   `..._NOTIFY_DRYRUN` 保留。**dump 模式永不发通知**。
5. **自测入口**:`bash scripts/cloud_unit_patrol_selftest.sh`(8 项;有 python3 时全跑)。