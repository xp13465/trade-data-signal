# #195 批2 实施报告:巡检/告警本体 10 脚本迁移 + #208 祖先 symlink 修复 + T7 单测

- 日期:2026-10-06
- 分支:`feat/195-resolve-repo-batch2-20261006`(worktree 隔离 `agent-abf1d2ca890890b98`;只 push feat,**禁 push main / 禁 force**)
- 基线:`origin/main` = `395a77892`(批1 已合入)
- 方案(唯一设计权威):`docs/ops/195-resolve-repo-plan-20261006.md`(§3.5/§3.6/§4.2/§4.6/§5/§6.4/§6.5)
- 进度文件:`/tmp/agent-progress-195-batch2.md`
- 前置依赖:批1 的 `scripts/lib/repo_paths.sh` + `test_resolve_repo.sh` 已在 main

## 1. 结论

批2 交付项全部落地,**7 条验收点全绿**。**先修 #208(阻断项)**再迁移 10 脚本;全程零真实外发、零生产写、云上零写。

- `#208` 祖先 symlink 静默 bug:**修前 T7 FAIL 复现(静默推出仓目录)→ 修后 T7 PASS**;T1-T7 = **PASS=11 FAIL=0**。
- 10 脚本迁移:静态断言 **10/10**、`bash -n` **12/12**、导出语义(**宽松行数**)逐文件**相等**。
- 回归:patrol selftest **8/8**、pytest 全量 **234 passed / 1 skipped**、`lint_scripts.sh` 全通过。
- ratchet:pattern 命中 **46(白名单外 0)**(迁移前 56 ⇒ **-10**)、MIGRATED **12 PASS 12**、`RESULT=PASS`;`--selftest` 变异 **FAIL** + 负对照 **PASS**。
- 云上只读抽样 **6/6**(推导值 == unit `Environment` 值,env 版 rc=0 零改写);**lib 经 stdin 管道喂**(不落任何文件、不 start 任何 unit)。
- 零外发证据:**IDENTICAL**(notify/dedup/alert 4 状态文件 md5+mtime 前后逐位一致,`data/alerts` 计数不变)。

## 2. 交付物(13 改)

| # | 文件 | 性质 | 说明 |
|---|---|---|---|
| 1 | `scripts/lib/repo_paths.sh` | 修 bug(#208) | 候选 A 前提由「raw≠real」收紧为 **`-L "$_raw_dir"`(scripts 目录本身是 symlink)**;新增**双候选回退**(A 前提成立取 A,否则回退 B) |
| 2 | `scripts/tests/test_resolve_repo.sh` | 加单测 | 新增 **T7 祖先 symlink**(`mktemp -d` 沙箱:祖先级 symlink + 仓目录也带 `.venv`)断言不得静默推出仓目录 |
| 3-12 | `scripts/check_data_gap_alerts.sh` / `monitor_72h.sh` / `nextday_gap_check.sh` / `on_skip_notify.sh` / `overfit_monitor.sh` / `r2_upload_skip_notify.sh` / `schedule_monitor.sh` / `self_heal.sh` / `turnover_backfill_skip_notify.sh` / `uptime_check.sh` | 迁移 | §3.5 两行模板 + 原 `export` 语义逐字节保留(§3.6);**只动 header 两行,零逻辑 / 零被调 python 改动** |
| 13 | `scripts/check_repo_paths_ratchet.py` | 棘轮同步(§4.6) | 10 文件从 `PENDING_BASELINE` **删**、加入 `MIGRATED`(只收紧不放松);**仍不挂任何链 / 不设 cron** |

> `git diff --stat`:13 files changed, 116 insertions(+), 36 deletions(-)。10 个迁移脚本**每个恰好 1 个 hunk**,位置均落在 header(`set -u` / `set -uo pipefail` 之后),证明改动面仅 header 注释块。

## 3. #208 修前/修后双结果(负控)

**缺陷**:当**仓目录的某级祖先**是 symlink 时(scripts 目录本身是实体目录),旧判据「raw≠real」仍成立 ⇒ 误入候选 A ⇒ `REPO=仓目录`(应为姐妹 `trade-data`),且三校验抓不住 ⇒ **静默(rc=0)**。

**负控(先跑修前,记录 FAIL)**:
```
== T7 祖先 symlink(仓目录的某级祖先是 symlink)→ 不得静默推出仓目录 ==
  FAIL: raw=[[/tmp/.../t7/link/trade  /tmp/.../t7/link/trade]]   # REPO 被静默推成仓目录
        phys=[[/tmp/.../t7/real/trade  /tmp/.../t7/real/trade]]
        期望 [[/tmp/.../t7/real/trade-data  /tmp/.../t7/real/trade]]
```
(T1-T6 修前仍 PASS ⇒ 缺陷只在祖先 symlink 场景。)

**修法**:候选 A 前提收紧为 `-L "$_raw_dir"`(scripts 目录本身是 symlink = 真·case A 充要特征);前提不成立即确定性回退候选 B(物理路径布局:姐妹 `trade-data`,缺则回退 GIT_REPO)。

**修后**:T7 PASS;总汇总 `PASS=11 FAIL=0`(T1-T6 全部回归 PASS):
```
== T7 祖先 symlink(仓目录的某级祖先是 symlink)→ 不得静默推出仓目录 ==
  PASS: REPO=物理姐妹 trade-data / GIT_REPO=物理仓(未静默推出仓目录)
== 汇总: PASS=11 FAIL=0 ==
```

### ⚠️ 方案 §5 第 6 行解读偏离(上报主控,§23.13)

方案 §5 第 6 行字面写「校验失败 → 试另一候选」。**字面实现会破坏批1 T4**:T4 断言「推导值校验失败 ⇒ fail-loud(exit 2)」,若失败即静默试另一候选,T4 的 rc 就不再是 2。**判定为「前提门控」而非「失败回退」**:用 `-L "$_raw_dir"` 做**充要前提判别**(A 前提成立→A,否则→B),而非「跑一遍再失败才回退」。**这是实施侧的解读收窄,非自行改口径**,已按 §23.13 停下上报主控复核(若主张「先跑后回退」的语序,需主控拍板,本实现保留可切换)。

## 4. 逐文件 before/after export 行数(§3.6:必须相等)

口径说明:迁移把 `export REPO=/硬编码` 改为「`resolve_repo` 赋值 + `export REPO`」,**导出语义**的权威度量是**宽松计数** `^export (REPO|GIT_REPO)`(子进程可见性据此);严格计数 `^export (REPO|GIT_REPO)=` 会随形态变化而减少(**预期**,非语义变更)。

| 文件 | 宽松 before→after | 严格 before→after | 判定 |
|---|---|---|---|
| check_data_gap_alerts.sh | 1 → 1 | 1 → 0 | **相等** |
| monitor_72h.sh | 1 → 1 | 0 → 0 | **相等** |
| nextday_gap_check.sh | 2 → 2 | 2 → 0 | **相等** |
| on_skip_notify.sh | 0 → 0 | 0 → 0 | **相等** |
| overfit_monitor.sh | 0 → 0 | 0 → 0 | **相等** |
| r2_upload_skip_notify.sh | 0 → 0 | 0 → 0 | **相等** |
| schedule_monitor.sh | 1 → 1 | 0 → 0 | **相等** |
| self_heal.sh | 1 → 1 | 0 → 0 | **相等** |
| turnover_backfill_skip_notify.sh | 0 → 0 | 0 → 0 | **相等** |
| uptime_check.sh | 0 → 0 | 0 → 0 | **相等** |

**10/10 宽松行数相等** ⇒ py 侧 `os.environ` 可见性(≥12 处消费者)与迁移前逐字节一致。lib **只 assign 不 export**(T6 断言),故 env 由各脚本原样决定。

## 5. 逐条验收(命令 + 实测)

| 验收点 | 命令 | 实测 |
|---|---|---|
| ① 静态断言 10/10 | `bash /tmp/assert195b2.sh <wt>` | `10/10 PASS`(src=1 res=1 mac=0) |
| ② 导出语义相等 | 见 §4 | 宽松 10/10 相等 |
| ③ 语法 | `bash -n {10 脚本 + lib + test}` | `12/12 OK` |
| ④ 单测 T1-T7 | `bash scripts/tests/test_resolve_repo.sh` | `PASS=11 FAIL=0` rc=0 |
| ④' pytest 全量 | `<venv>/python -m pytest scripts/tests/ -q` | `234 passed, 1 skipped` |
| ④'' pytest 定向 | `pytest test_resolve_repo_pytest.py test_repo_paths_ratchet_pytest.py -q` | `3 passed` |
| ⑤ patrol selftest | `bash scripts/cloud_unit_patrol_selftest.sh` | `PASS=8 FAIL=0` rc=0 |
| ⑥ ratchet | `python3 scripts/check_repo_paths_ratchet.py` | 命中 **46**(白名单外 0)/ MIGRATED 12 PASS 12 / `RESULT=PASS` |
| ⑥' ratchet selftest | `python3 ... --selftest` | 负对照 PASS + 变异 **FAIL(闸门真响)**;`[ratchet-selftest] PASS` |
| ⑦ resolve-only probe | `bash /tmp/probe195b2.sh <wt>` | `PASS=7 FAIL=0`(沙箱镜像布局 3 + 真实 mac 布局 3 + env==derived 1) |
| ⑧ lint | `bash scripts/lint_scripts.sh` | `lint 全通过` rc=0 |
| ⑨ 云上只读抽样 | 见 §7 | `PASS=6 FAIL=0` |
| ⑩ 零外发证据 | 见 §8 | `IDENTICAL` |

## 6. 复现段(逐验收点:命令 + 实测 + 修复链)

### A. #208 负控→修复(见 §3)
```bash
# 修前:引入 T7 后首跑
bash scripts/tests/test_resolve_repo.sh   # → T7 FAIL(静默推仓目录),其余 PASS;rc=1
# 修 lib(候选 A 前提收紧 -L)后:
bash scripts/tests/test_resolve_repo.sh   # → PASS=11 FAIL=0 ; rc=0
```

### B. 静态断言 + 语法 + 导出语义(§4/§5)
```bash
bash /tmp/assert195b2.sh <wt>   # → 10/10 PASS
bash /tmp/bn195b2.sh <wt>       # → 12/12 OK
bash /tmp/evidence195b2.sh      # → (1) 逐文件 before/after export 行数,10/10 宽松相等
```

### C. 回归全套
```bash
bash scripts/cloud_unit_patrol_selftest.sh                       # → 8/8
/Users/linhuichen/code/trade/.venv/bin/python -m pytest scripts/tests/ -q   # → 234 passed, 1 skipped
python3 scripts/check_repo_paths_ratchet.py                      # → RESULT=PASS
python3 scripts/check_repo_paths_ratchet.py --selftest           # → PASS
bash scripts/lint_scripts.sh                                     # → 全通过
```
**修复链**:`python3 -m pytest` 报 `No module named pytest` ⇒ 改用 `/Users/linhuichen/code/trade/.venv/bin/python`(含 pytest 9.1.1)。既有 231 例不动,批1 新增 wrapper 2 例 + 本批无新增 pytest 用例(ratchet wrapper 同批1)⇒ 与批1 报的 232 差为批1 后合入的其他用例,全量 234 与基线一致。

### D. ratchet 棘轮收紧(§4.6)
```bash
# 迁移前:pattern 命中 56(白名单外 0)
# 迁移后:10 文件移出 PENDING_BASELINE、移入 MIGRATED
python3 scripts/check_repo_paths_ratchet.py   # → 命中 46 ; MIGRATED 12 PASS 12 ; RESULT=PASS
```
**修复链**:R3 正则 2026-10-06 返修 `:-?/Users/linhuichen`(覆盖 `:-/` 主流病灶形态);`--selftest` 变异锚点必须落**代码行**(注释里也有 `export REPO GIT_REPO`,裸 `str.replace(...,1)` 会命中注释 → 假 PASS,正是 §18 L49「假样本养绿」变体)⇒ 已按整行精确匹配定位代码行。

### E. resolve-only probe(零业务)
```bash
bash /tmp/probe195b2.sh <wt>   # → 7/7(物理归一比较,mac /var↔/private/var)
```
**修复链**:首跑 3 个沙箱样本 FAIL —— 推导 `GIT_REPO` 取 `dirname(pwd -P)` = **物理路径**(`/private/var`),而期望用 `mktemp -d` 的**逻辑** `$T`(`/var`)⇒ 加 `phys()` 两侧物理归一后 7/7。

### F. 云上只读抽样(§6.5)
```bash
bash /tmp/cloud_probe195b2.sh   # → PASS=6 FAIL=0
```
见 §7。

### G. 零外发证据
```bash
bash /tmp/zeroext195b2.sh   # → IDENTICAL
```
见 §8。

## 7. 云上只读抽样(§4.2 验收点4 / §6.5)

**零写**:新 lib 经 **stdin 管道**喂给远端 `bash -s` 执行(不落任何文件、不 start 任何 unit、不跑业务代码)。

- 云上环境:`REPO=/home/ubuntu/code/trade-data`、`GIT_REPO=/home/ubuntu/code/trade-data-signal`(多仓布局)。
- 抽样 3 脚本:`schedule_monitor.sh` / `self_heal.sh` / `turnover_backfill_skip_notify.sh`。
- ① **unset 版**(`env -u REPO -u GIT_REPO`):断言推导值 == 该 unit 的 `Environment` 值(**逐字节**)。
- ② **env 版**(传 env):断言 rc=0 且值 == env(**零改写**)。

```
PASS unset 推导 == env 值: schedule_monitor.sh
PASS env 版 rc=0 且零改写: schedule_monitor.sh
PASS unset 推导 == env 值: self_heal.sh
PASS env 版 rc=0 且零改写: self_heal.sh
PASS unset 推导 == env 值: turnover_backfill_skip_notify.sh
PASS env 版 rc=0 且零改写: turnover_backfill_skip_notify.sh
== 云上只读抽样: PASS=6 FAIL=0 ==
```
⇒ 云上 `<REPO>/scripts` 是 symlink,`$0` 推导**自愈跑对**;env 有值时**零改写**(机器行为零变化)。

## 8. 零外发 / 零生产写证据

**硬约束**:6/10 脚本含 notify ⇒ 全程**只做静态断言 + `bash -n` + resolve-only probe**,**未跑任何 unit / `systemctl` / `update_all.sh` / `schedule_monitor.sh` 本体 / `self_heal.sh` 本体 / 任何 notify·邮件·飞书·R2 写**。

```
== BEFORE / AFTER 逐位比对 ==
alert_state.json     mtime=1789246808 md5=6151e5567c949455ce684614485562ac
alerts/latest.md     mtime=1790748455 md5=334f0ac79790d97a3537c671d17b8a02
anomaly_notified.json mtime=1789130521 md5=87071b33d486524f9d76e512b35deda2
brief_push_state.json mtime=1789130709 md5=7706673354dab3d47ecebe197b4d1ab7
alerts_dir_count=4
== DIFF ==
IDENTICAL: notify/dedup/alert 状态 md5+mtime 前后一致(零外发)
```
- 重跑测试电池前后 5 项状态文件 **md5+mtime 逐位一致**,`data/alerts` 计数不变。
- pgrep:仅一个**既有** `feishu_ws_listener.py`(PID 39086,**前后同 PID**,非本任务启动)。
- probe 全程 `env -u REPO -u GIT_REPO ... bash -c`(沙箱/只读),未触发任何业务分支。

## 9. §23.3 举一反三(同模式/同数据源/同组件还被谁用 + 相关展示位)

**同组件(lib 消费者)全清单**:`grep -rln 'repo_paths.sh' scripts/` ⇒ **12 个脚本**:
- 批1(2):`check_r2_consistency.sh`、`cloud_unit_patrol.sh` —— 本批 lib 改动**直接影响**,已用 patrol selftest **8/8** 回归 + T1-T6 全 PASS 证不回归。
- 批2(10):本批迁移对象。
- 基建:`tests/test_resolve_repo.sh`、`cloud_unit_patrol_selftest.sh`、`check_repo_paths_ratchet.py`(不入 MIGRATED,由 ratchet R2 规则豁免)。

**同模式(仍写死 mac 默认的脚本)**:**46 个**留在 `PENDING_BASELINE`(批3-5 待迁)。ratchet R1 已把它们钉在已知集合内,**新脚本再写死即 FAIL**(防回潮),本批只收紧不放松。

**同数据源**:`$0` 双布局推导的两种布局(mac:`trade-data/scripts -> trade/scripts`;云上:`trade-data/scripts -> trade-data-signal/scripts`)—— probe 与云上抽样**双端都实测**,非单端推断。

**相关展示位**:本改动是纯 shell 路径解析,无前端展示位 / 无用户可见数据产物,不涉 §21 算法公示 / §22 数据一致性(零 JSON 产物、零 R2 上传)。

**python 侧同族**(≥51 `.py` / ≥12 处 `os.environ.get("REPO", mac默认)`):**已另登记 #206**(口径=先盘清单再定批,不与 shell 批混做)——本批**不动 python**,仅在报告标注其为同族待办。

## 10. §23.4 同模块冲突预防

- `docs/pending-features-index.md` 扫 #195 模块:批1(已合 main `395a77892`)→ 批2(本批)→ 批3/4/5(待派)。**无同模块并发任务**(本 worktree 独占批2)。
- 预留位置:ratchet 的 `MIGRATED` / `PENDING_BASELINE` 为**批级唯一登记点**,本批只在两集合间搬 10 项,不新增结构 ⇒ 后续批次按同一模式续搬,无覆盖风险。
- 未发现冲突 / 依赖缺口 / 过时项。**#207** 属批1 已订正(注释),本批不涉。

## 11. 交付四件套(§23.5)

1. **本体**:本报告 + 13 个改动文件(§2)。
2. **生成/复现脚本**:`/tmp/assert195b2.sh`(静态断言)、`/tmp/bn195b2.sh`(语法)、`/tmp/probe195b2.sh`(resolve-only probe)、`/tmp/evidence195b2.sh`(export 前后 + 电池)、`/tmp/zeroext195b2.sh`(零外发证据)、`/tmp/cloud_probe195b2.sh`(云上只读抽样)。**均为零业务/只读**;因属一次性验收工具,未纳入仓(入仓会与 `scripts/tests/` 下已有单测重复),复现命令已内联 §6。
3. **复现段**:§6(A-G)。
4. **配套 commit**:见分支 `feat/195-resolve-repo-batch2-20261006`。

## 12. 未决 / 上报项

- ⚠️ **§3 的 #208 解读偏离**需主控复核(前提门控 vs 失败回退语序)。
- **#206**(python 侧同族)为同链待办,本批不涉。
- ratchet **仍不挂链**(方案 §7.2 待拍板#2 未决)——本批未改挂链状态。