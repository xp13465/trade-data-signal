# #195 批4 实施报告 —— 其余 unit 直调单点任务 21 个脚本迁移到单点 `resolve_repo`

> 日期 2026-10-06(实施 agent,worktree 隔离 `/Users/linhuichen/code/trade/.claude/worktrees/agent-ad5cf2c28d5104e03`)
> 分支 `feat/195-resolve-repo-batch4-20261006`,base = **`8a3f6b62e`**(= #195 批3 合并点,main)
> 方案:`docs/ops/195-resolve-repo-plan-20261006.md` §4.4 / §3.5 / §3.6 / §4.6 / §6.4
> 上游:`docs/ops/195-batch1-implement-20261006.md` / `195-batch2-implement-20261006.md` / `195-batch3-implement-20261006.md`

## 0. 结论速览

批4 的 **21 个「其余 unit 直调单点任务」脚本**全部迁到单点 `resolve_repo`,**自测 8 条全绿**:
静态断言 21/21、`bash -n` 21/21、单测 `test_resolve_repo.sh` T1-T7 = 11/11、pytest 234 passed/1 skipped、
ratchet PASS(MIGRATED 42、残留命中 0、白名单外 0)+ `--selftest` PASS、**本机真实布局 probe 42/42**(21 文件 × case A/B 两布局)、
云上只读抽样 3 unit PASS。**全程零真实外发、零生产写、零 unit 启停、云上零写、未跑任何业务脚本**。

⚠️ **诚实缺口(同批3)**:本批新代码**至今未在生产跑过** —— 云上内容是 merge 后才会更新(见 §7.3);云上只读抽样核的是
「unit 环境/触发面」,**不是**核本批新代码(抽到的脚本在云上仍是旧版,文件时间 Sep 12/13/28)。

## 1. 改动清单(22 文件 = 21 shell + ratchet)

`git diff --stat` = **22 files changed, 68 insertions(+), 48 deletions(-)**。

| # | 文件 | header 形态 | export before/after |
|---|---|---|---|
| 1 | `scripts/backfill_metrics.sh` | A:1 行赋值→source+resolve | 0 / 0 |
| 2 | `scripts/etf_national_team_backfill.sh` | C:2 行赋值→source+resolve(export 行保留) | 1 / 1 |
| 3 | `scripts/fapi_daily_syn.sh` | A | 0 / 0 |
| 4 | `scripts/futures_backfill.sh` | A | 0 / 0 |
| 5 | `scripts/gold_night.sh` | C | 1 / 1 |
| 6 | `scripts/lhb_backfill.sh` | A | 0 / 0 |
| 7 | `scripts/pf_score_daily.sh` | C | 1 / 1 |
| 8 | `scripts/pf_score_weekly.sh` | C | 1 / 1 |
| 9 | `scripts/public_fund_daily.sh` | A | 0 / 0 |
| 10 | `scripts/public_fund_estimation.sh` | A | 0 / 0 |
| 11 | `scripts/public_fund_full.sh` | A | 0 / 0 |
| 12 | `scripts/public_fund_quarterly.sh` | A | 0 / 0 |
| 13 | `scripts/run_ab_direction_anchor.sh` | **E:TRADE_DIR 变体**(见 §3) | 0 / 0 |
| 14 | `scripts/rzhb_backfill.sh` | A | 0 / 0 |
| 15 | `scripts/stage0_manager.sh` | A | 0 / 0 |
| 16 | `scripts/stage0_nav.sh` | A | 0 / 0 |
| 17 | `scripts/stage0_overview.sh` | A | 0 / 0 |
| 18 | `scripts/stage0_risk.sh` | A | 0 / 0 |
| 19 | `scripts/turnover_backfill.sh` | **D:2 行 `export X=…`→source+resolve+2 行 export** | 2 / 2 |
| 20 | `scripts/update_lab.sh` | C | 1 / 1 |
| 21 | `scripts/us_stock_morning.sh` | **B:2 行赋值(无 export 行)→source+resolve** | 0 / 0 |
| 22 | `scripts/check_repo_paths_ratchet.py` | 21 文件 `PENDING_BASELINE`→`MIGRATED` 批4 组 + 计数注释 | — |

**header 形态说明**:
- **A(13 个)**:原非 export、仅 `REPO="${REPO:-…}"` 一行 → `source …` + `resolve_repo …`。
- **B(1 个)**:`us_stock_morning` 原有 `REPO`/`GIT_REPO` 两行赋值但**无 export 行** → 两行 → source+resolve,**不新增 export**。
- **C(5 个)**:`etf_national_team_backfill`/`gold_night`/`pf_score_daily`/`pf_score_weekly`/`update_lab` 原有两行赋值 + 其后的 `export REPO GIT_REPO` 行 → 只换两行赋值,**export 行原样保留**(不动)。
- **D(1 个)**:`turnover_backfill` 原为 `export REPO="${REPO:-…}"` + `export GIT_REPO=…` 两行内联 export → 换成 source+resolve + `export REPO` + `export GIT_REPO` 两行(**行数守恒=计数口径守恒**)。
- **E(1 个)**:`run_ab_direction_anchor` 唯一 `TRADE_DIR` 变体(见 §3)。

### 1.1 export 语义逐文件 before/after(§3.6 硬约束,口径 `grep -E '^[[:space:]]*export (REPO|GIT_REPO|TRADE_DIR)'`)

**21/21 逐文件相等,合计相等**:**本批 export 类 = 6 个**(etf_national_team_backfill / gold_night / pf_score_daily / pf_score_weekly / turnover_backfill / update_lab),
非 export = 15 个。**无 lib 改动**(`scripts/lib/repo_paths.sh` 一字未动,批1 定稿),故 lib 仍 assign-only;原 export 脚本保留 export ⇒ py 子进程 `os.environ` 可见性逐字节不变。

```
backfill_metrics 0/0   etf_national_team_backfill 1/1  fapi_daily_syn 0/0   futures_backfill 0/0  gold_night 1/1
lhb_backfill 0/0       pf_score_daily 1/1              pf_score_weekly 1/1  public_fund_daily 0/0 public_fund_estimation 0/0
public_fund_full 0/0   public_fund_quarterly 0/0       run_ab_direction_anchor 0/0  rzhb_backfill 0/0   stage0_manager 0/0
stage0_nav 0/0         stage0_overview 0/0             stage0_risk 0/0      turnover_backfill 2/2 update_lab 1/1
us_stock_morning 0/0
```

### ⚠️ 与方案 §4.4 / §2.2 的口径差异(实测 vs 文档,按「读代码现状」为准)

- 方案 **§4.4** 写「**turnover_backfill 为 export 类**保留 export」(暗示本批仅 1 个 export)——**与代码现状不符**:实测**本批 export 类 = 6 个**(见上)。
- 方案 **§2.2 主表**「export」列对 `etf_national_team_backfill`/`gold_night`/`pf_score_daily`/`pf_score_weekly`/`update_lab` 均标「**否**」——实测均为**是**;**`turnover_backfill` 标「是」正确**,`us_stock_morning` 标「否」正确。
- **口径结论**:与 §4.3 的 2026-10-06 订正同源 —— **§2.2 主表 export 列不可作派单依据,一律以读代码现状为准**(本批已按派单指示执行,逐文件 before/after 相等)。

## 2. 逐文件 header 迁移形态(§3.5 两行模板 + §5-1 兜底版)

```bash
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/lib/repo_paths.sh" || { echo "FATAL: repo_paths.sh missing" >&2; exit 2; }
resolve_repo "${BASH_SOURCE[0]}"
```

- **只动 header**:21 文件 diff 面 = 默认值赋值行 → source+resolve 行;export 行原样(C)、inline export 拆行(D)、TRADE_DIR 映射(E)。**不动其它逻辑、不动被调 python、不动 `docs/`**(§23.7 版本冻结契约)。
- 各文件原 `GIT_REPO`/`REPO` 行尾注释(如「git 始终在 trade 仓库…」「云上单仓用 REPO env 覆盖」「§9 cwd=trade-data…」)随该行一并移除;有信息价值的 **export 行注释全部保留**(C/D)。
- `lib/repo_paths.sh` **未改**(批2 后含 #208 修复),`bash -n` rc=0。

## 3. `run_ab_direction_anchor.sh` 的 `TRADE_DIR` 处置(选①,理由 + 逐字节证明)

**选定方案①**:把 `resolve_repo` 推导结果映射回 `TRADE_DIR`,且保 env 优先 —— 落地为:

```bash
source "…/lib/repo_paths.sh" || { …; exit 2; }
resolve_repo "${BASH_SOURCE[0]}"
TRADE_DIR="${TRADE_DIR:-$GIT_REPO}"
```

**为什么映射到 `$GIT_REPO` 而不是 `$REPO`**:本脚本 `TRADE_DIR` 承载的是**「git 仓」语义**(脚本注释「输入依赖:REPO(trade-data 部署源树)」;`TRADE_DIR` 用作 `sys.path.insert` 与 `ab_direction_anchor.py` 的所在树,
**不是**部署源树)。云上 unit 实测 `Environment=TRADE_DIR=/home/ubuntu/code/trade-data-signal` **逐字节等于** `Environment=GIT_REPO=/home/ubuntu/code/trade-data-signal`(见 §4.4 快照),故 `TRADE_DIR ≡ GIT_REPO`;映射到 `$REPO`(=trade-data)会**改语义**。

**为什么用 `${TRADE_DIR:-$GIT_REPO}` 而非裸 `TRADE_DIR="$GIT_REPO"`**:`:-` 形态**保持了原脚本 `${TRADE_DIR:-default}` 的 env 优先零改写语义** —— 若将来某 unit 显式给 `TRADE_DIR` 且与 `GIT_REPO` 不同,行为与迁移前完全一致;env 丢失时才回退 lib 推导的 `GIT_REPO`(自愈)。

**「迁移前后同环境下该变量取值逐字节相同」证明(本机 probe,§4.5)**:
- **env 空**(mac 默认场景):推导 `GIT_REPO=/Users/linhuichen/code/trade` ⇒ `TRADE_DIR=/Users/linhuichen/code/trade` = 迁移前 mac 默认值,逐字节相同 ✅
- **env = git 值**(云上形态,`TRADE_DIR` env 已设):`${TRADE_DIR:-…}` 取 env 值 = `/home/ubuntu/code/trade-data-signal`,与迁移前逐字节相同 ✅
- 脚本内其余 `$TRADE_DIR` 用法(L11 `PY`、L18/26 `sys.path.insert`、L49/54 调 py)**全部仍成立**(变量名未改)。

## 4. 自测结果(逐项 PASS)

### 4.1 静态断言(方案 §6.4)21/21 PASS
每文件:`source lib` 恰 1 行 + `^resolve_repo ` 恰 1 行 + 代码行残留 `:-?/Users/linhuichen` 恰 0 → **21/21 OK**(输出见 §8.1)。

### 4.2 `bash -n` 21/21 PASS
`bash -n <file>` failures = **0**(21 文件全过)。

### 4.3 单测(§3.7)`test_resolve_repo.sh` 11/11 PASS
T1 env 优先 / T2 case A / T3 case B / T3b 容错回退 / T4 fail-loud(exit2+固定日志+逃生阀)/ T5 空值 env / T6 无副作用+assign-only / T7 祖先 symlink —— `汇总: PASS=11 FAIL=0`。

### 4.4 pytest + ratchet + 云上只读抽样
- `pytest -q`(scripts/tests 全量)= **234 passed, 1 skipped**(7.72s)。
- **ratchet `main`**:`RESULT=PASS`,pattern 命中 16(白名单外 0),`MIGRATED 42 个 PASS 42`,R3 残留命中 0,R3 正则健康自检 OK。
- **ratchet `--selftest`**:负对照 PASS + 变异样本 RESULT=FAIL(闸门真响)→ `[ratchet-selftest] PASS`。
- **cloud 只读抽样 3 unit**(`fapi_daily_syn` / `pf_score_daily` / `gold_night`,时间散点跨日):三 unit **均带** `Environment=REPO=/home/ubuntu/code/trade-data GIT_REPO=/home/ubuntu/code/trade-data-signal MAIN_REPO=…`,ExecStart 直调 `/home/ubuntu/code/trade-data/scripts/<x>.sh`;脚本在位。⇒ 云上 env 齐全 ⇒ 迁移后走 `source=env` 分支,**结构性零行为变化**。⚠️ 抽样核的是「unit 环境/触发面」,**非**本批新代码(云上文件时间 Sep 12/13/28 = 旧版,merge 后才更新)。

### 4.5 本机真实布局 probe 42/42 PASS(env 空 → 推导 == 迁移前 mac 默认值)
对 21 文件 × 2 真实布局(case A `~/code/trade-data/scripts/<x>.sh` 经 symlink / case B `~/code/trade/scripts/<x>.sh` 直跑)逐个 `source lib` + `resolve_repo <path>`(仅打印、零业务):
- 42/42 推导 `REPO=/Users/linhuichen/code/trade-data`、`GIT_REPO=/Users/linhuichen/code/trade` = **迁移前 mac 默认值,逐字节一致** ✅
- `run_ab_direction_anchor` 追加:`TRADE_DIR(env空)=/Users/linhuichen/code/trade`、`TRADE_DIR(env=git)=/Users/linhuichen/code/trade` 两者 OK ✅

## 5. 零外发 / 零生产写 证据

- 全程执行的命令仅:`python3`(断言/probe 生成)、`ls`、`bash -n`、`pytest`、`ratchet`、`bash scripts/tests/test_resolve_repo.sh`、**只读 ssh**(`systemctl show` / `grep` / `ls`)。
- **未运行本批任何业务脚本**(21 个里绝大多数会写生产数据/发通知/动 R2);probe 仅 `source lib` + `resolve_repo` + `echo`。
- probe 的 `resolve_repo` 全部走成功路径(推导值有效)⇒ **未触发 fail-loud**、未写任何 `resolve_repo_fatal.*.log`(T4 的 fatal 落在 `mktemp` 沙箱目录内)。
- 云上仅只读(`systemctl show` / `grep` / `ls`),**零写、零 unit 启停**。
- `git status --porcelain` 收工 = 仅 22 个 `M`(21 shell + ratchet),**无 `data/`、无前端、无 untracked**。

## 6. 上报项(发现的不属于本批的问题,只登记不修,§23.7)

1. **方案文档口径失准(非代码问题)**:§4.4「turnover_backfill 为 export 类」(实测 6 个)、§2.2 主表 export 列 5 处误标 —— 与 §4.3 已订正同源。**建议主控在方案 §4.4 补一句口径订正**,防批5 派单再被误导。本批已按「读代码现状」执行。
2. **同模式残留(非本批范围)**:`grep -rl ':-/Users/linhuichen' scripts/` 残留 19 文件 = 批5 的 16 个 PENDING + `scripts/lib/repo_paths.sh`(仅头注释举例)+ `scripts/sensenova-rotate-proxy.sh` / `-kimi.sh`(`SENSENOVA_ENV_FILE:-…` 另一变量族,方案 §2.3 已声明越界)。**本批不动**。
3. **二阶同族(py 侧,方案 §7.2 待拍板#3)**:`scripts/*.py` 内 ≥12 处 `os.environ.get("REPO", <mac默认>)` 不在 shell lib 覆盖面,建议按方案登记为独立任务。本批不涉及。
4. **`us_stock_morning.sh` 无 export 但有 GIT_REPO**:已按现状保持 assign-only(不新增 export),符合 §3.6;仅作口径记录(方案 §2.2 标「否」正确)。

## 7. 给 §0 的待验清单(实施侧验不了 / 需上线后验)

| # | 待验点 | 为什么实施侧验不了 | 建议验证方式 |
|---|---|---|---|
| 1 | **本批新代码生产实跑** | 云上内容 merge 后才更新;本批未部署 | merge 后 48h 内 `journalctl`/`.err` 现 `resolve_repo: … (source=env)`;`systemctl --failed` 空 |
| 2 | **上线后 48h 无新增 failed**(方案 §4.4 验收点) | 需自然 unit 运行一个周期 | 观察 `trade-*` failed 集合无新增(平时为空=空即 PASS) |
| 3 | 云上 md5 == 本批字节 | 属 merge 后步骤 | merge 后 `ssh … md5sum /home/ubuntu/code/trade-data/scripts/<x>.sh` 与本机 worktree 字节比 |
| 4 | merge 时点避盘后(15:35/16:00/17:50/20:35/22:00)与盘中 | agent 不 push main | 主控 `main-merge.sh` 统一入口内含 §14 检查 |

## 8. 复现段(§23.5 四件套之「复现段」)

### 8.1 静态断言(21/21)
```bash
python3 - <<'PY'
import re,os
base="<worktree>/scripts"
files="backfill_metrics etf_national_team_backfill fapi_daily_syn futures_backfill gold_night lhb_backfill pf_score_daily pf_score_weekly public_fund_daily public_fund_estimation public_fund_full public_fund_quarterly run_ab_direction_anchor rzhb_backfill stage0_manager stage0_nav stage0_overview stage0_risk turnover_backfill update_lab us_stock_morning".split()
for f in files:
    L=open(os.path.join(base,f+".sh"),encoding='utf-8').read().splitlines()
    code=[l for l in L if not l.lstrip().startswith("#")]
    n_src=sum(1 for l in L if re.search(r'^source\s+.*lib/repo_paths\.sh',l))
    n_res=sum(1 for l in L if re.search(r'^resolve_repo\s',l))
    n_mac=sum(1 for l in code if re.search(r':-?/Users/linhuichen',l))
    print(f,n_src,n_res,n_mac,"OK" if (n_src==1 and n_res==1 and n_mac==0) else "FAIL")
PY
# 实测:21/21 OK
```

### 8.2 ratchet(白名单搬运经 21 恰,余 16)
```bash
python3 scripts/check_repo_paths_ratchet.py          # RESULT=PASS(MIGRATED 42 / 残留 0 / 白名单外 0)
python3 scripts/check_repo_paths_ratchet.py --selftest   # [ratchet-selftest] PASS
```

### 8.3 单测 + pytest
```bash
bash scripts/tests/test_resolve_repo.sh              # PASS=11 FAIL=0
scripts/tests: python -m pytest -q                   # 234 passed, 1 skipped
```

### 8.4 本机 probe(env 空 → 推导 == mac 默认)
probe 脚本 `/tmp/195b4_probe.sh`(仅 `source lib` + `resolve_repo <mac真实路径>` + echo,零业务);`PROBE_RESULT=0`。

### 8.5 云上只读抽样(零写)
```bash
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 \
  'for u in trade-fapi-daily trade-pf-score-daily trade-gold-night; do \
     systemctl show $u.service -p Environment; grep -h "^ExecStart=" /etc/systemd/system/$u.service; done'
# 实测:三 unit 均 Environment=REPO=/home/ubuntu/code/trade-data GIT_REPO=/home/ubuntu/code/trade-data-signal
```

### 8.6 配套 commit
本报告与 21 脚本迁移 + ratchet 白名单搬运**同一 commit**(见 `git log` 末次 commit 的脚本名列表)。