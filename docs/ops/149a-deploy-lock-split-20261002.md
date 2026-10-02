# #149 根治最后一块:deploy 锁粒度拆分 ①a + ①b(外层锁拆除) + #119(rsync exclude)

日期:2026-10-02 | 分支:`feat/149a-deploy-git-lock-20261002` | 实施:implementer

## 1. 背景与目标

#149 根因:`trade_deploy.lock` 职责错位——本职是串行化 git 写(秒~分钟级),却被 deploy 主链
的 export+R2(31-48min/段)和 async step3.5b R2 跨境 HEAD 比对(26-105min/段)拉长,导致锁队列
结构性不空、排队者连环占死。2026-10-01 已落方案①(本件 ①a)与方案②③(staticdata async/sync 两段式样板)。

本件完成 #149 方案① 的**最后两块**:
- **①a**:`scripts/deploy.sh` 内部 export/R2 段与 git 段解耦,`trade_deploy.lock` 只包 git 写段。
- **①b**:全仓 10 处 backfill/deploy 调用方去掉外层 `with_lock.py` 锁,与 ①a 新形态一致。
- **#119**:代码仓 `data/` 下 4 个 tracked 文件被 deploy.sh rsync 覆盖写致云上 git pull 被挡,加 `--exclude` 根治。

硬约束:只改「谁在锁内」,不改 deploy 对外行为(推送时机/顺序/失败语义);隔离 worktree 分支;
不真跑 production deploy(§14);自验含 §23.2 同类错误面清单;bash -n + lint_scripts.sh 全过。

## 2. ①a:deploy.sh 两段式 exec(锁获取点改造前后对照)

### 2.1 改造后锁获取点对照表

| # | 位置 | 改造前 | 改造后 | 持锁时间 |
|---|---|---|---|---|
| 1 | `update_all.sh`(17:50 主链末尾) | 外层 `with_lock.py --block-timeout 600 /tmp/trade_deploy.lock bash deploy.sh all` | 直接 `bash "$REPO/scripts/deploy.sh" all` | 0(段1 锁外) |
| 2 | `futures_backfill.sh` | 外层 `with_lock.py --block-timeout 600 ... bash deploy.sh futures` | 直接 `bash "$REPO/scripts/deploy.sh" futures` | 0 |
| 3 | `etf_national_team_backfill.sh` | 同上(etf-national-team) | 直接 | 0 |
| 4 | `lhb_backfill.sh` | 同上(lhb) | 直接 | 0 |
| 5 | `rzhb_backfill.sh` | 同上(rzhb) | 直接 | 0 |
| 6 | `public_fund_daily.sh` | 同上(public-fund) | 直接 | 0 |
| 7 | `public_fund_full.sh` | 同上(public-fund) | 直接 | 0 |
| 8 | `public_fund_quarterly.sh` | 同上(public-fund) | 直接 | 0 |
| 9 | `pipeline.sh` | 外层 `with_lock.py --block-timeout 600 ... bash deploy.sh $NAME`(DEPLOY_EACH=1 时) | 直接 | 0 |
| 10 | `app/collector/index_backfill.py` | `subprocess with_lock.py --block-timeout 600 /tmp/trade_deploy.lock bash scripts/deploy.sh backfill` | `subprocess ["bash","scripts/deploy.sh","backfill"]`(保留 cwd=repo + REPO env) | 0 |
| 11 | **deploy.sh 段1**(export+校验+R2+rsync) | 无独立 git 段锁(整体被外层锁包住) | 段1 完全锁外,末尾 `exec with_lock.py --block-timeout 3600 /tmp/trade_deploy.lock bash $0 --git-phase "$@"` 重入 | 0(不持锁) |
| 12 | **deploy.sh 段2**(git add/commit/push + 收尾) | —(原在段1 之后无锁,依赖外层锁) | 重入进程持 `/tmp/trade_deploy.lock` 只跑 git 写段 | 秒~分钟级 |
| 13 | staticdata_backup_async / staticdata_sync(②③,不在本件改动) | 段2 git 段持同一把锁 | 段2 git 段持同一把锁 | 秒~分钟级 |

### 2.2 两段式实现要点(样板=`scripts/staticdata_backup_async.sh`)

- **GIT_PHASE 标志**:顶部解析首参 `--git-phase` → `GIT_PHASE=1`,供段2 重入进程检测;`shift` 后 `NAME` 正常取 mode。
- **段1**:`if [ "$GIT_PHASE" != "1" ]; then` 包住原 export+校验+R2+rsync 全段(139-742 行),完全不持 git 写锁,可并发。
- **段1 末尾**(check_version_progress 后):`export DEPLOY_R2_FAIL="${R2_FAIL:-}"`、`export DEPLOY_MAP_STALE="${MAP_STALE:-0}"` → `exec "$PY" "$GIT_REPO/scripts/with_lock.py" --block-timeout "${GIT_LOCK_TIMEOUT:-3600}" "$LOCK" bash "$0" --git-phase "$@"`。
- **段2**(重入进程,744 行起):恢复 `R2_FAIL`/`MAP_STALE`,只跑原 git add/commit/push + staticdata async 触发 + feishu 重启 + 告警收尾。
- **锁路径**:`LOCK="${DEPLOY_LOCK:-/tmp/trade_deploy.lock}"`,测试隔离可覆写;默认与 async/sync 的 git 段同锁统一串行全部 git 写。
- **对外行为不变**:推送时机(校验全过→段2 push)、顺序(rebase 重试/stash 逻辑原样)、失败语义(段1 任一步失败→非0 退出,段2 不跑;段2 持锁排队超时→with_lock 优雅跳过 exit 0,与原外层锁 `--block-timeout 600` 跳过 deploy 整体语义一致)。

### 2.3 自测发现并修复的关键 bug(2026-10-02)

`git_fetch_timeout` / `git_push_timeout` 两个函数**原定义在段1 if 块内**(91/125 行)。段2 重入进程
整脚本重跑但 `if [ "$GIT_PHASE" != "1" ]` 为假 → 跳过段1 → **函数未定义** → 段2 调用报
`command not found`(rc=127)会被误判为 push/fetch 失败,走错误的重试/abort 分支(可能错误 exit 非 0)。

**修复**:两个函数移到段1 if 之外(公共区,75/109 行),段1/段2 共用。回归测试见 §7。

## 3. #119:rsync 覆盖写云上 pull 被挡(方案对比 + 选型)

**问题**:deploy.sh 的 `rsync "$REPO/data/" "$GIT_REPO/data/"` 会覆盖代码仓 git tracked 的 4 个文件
(`index_etf_map.json` / `stock_codes.json` / `trade.db` / `trade_dates.txt`),云上 `git pull` 被挡(与 #115/#118 同源)。

**候选方案对比**:
- ① **rsync `--exclude` 这 4 文件**:数据仓(REPO=trade-data)侧继续正常生成/刷新,代码仓(GIT_REPO)侧保留
  clone 种子不再被覆盖写。消费方优先读数据仓侧新版(`_trade_calendar_dates` 遍历 db_path.parent→ROOT/data→
  REPO/data,数据仓先命中),种子语义不破坏。
- ② **rsync `--existing`**:只阻止创建新文件,已存在文件仍被覆盖写,不能解决 M 脏问题 → 排除。
- ③ **脱跟踪(rm --cached)**:新机 clone 不再自带种子,破坏 bootstrap 文档
  (docs/deploy/migration-data-bootstrap-plan-20260912.md L41/72-74/118)定的种子语义,且 `trade_dates.txt`
  有真实代码仓 fallback 消费方 → 排除。

**选型:方案①**。已落:`rsync -a --exclude=logs/ ... --exclude=index_etf_map.json --exclude=stock_codes.json
--exclude=trade.db --exclude=trade_dates.txt "$REPO/data/" "$GIT_REPO/data/"`。

## 4. ①b:10 处外层锁拆除(逐个理由,不一刀切)

改造后 `trade_deploy.lock` 只在 deploy.sh 段2 git 写段被持(秒~分钟级),外层再包锁**既冗余又错位**
(把整个 deploy 重新拉回锁内,重犯 #149)。10 处调用方**全部同构**:原先都是
`with_lock.py --block-timeout 600 /tmp/trade_deploy.lock bash deploy.sh <mode>`,去掉外层锁后
`bash "$REPO/scripts/deploy.sh" <mode>` 即可,段1 锁外并发、段2 git 内部锁串行,deploy 对外行为不变。

| # | 调用方 | mode | 理由 |
|---|---|---|---|
| 1 | update_all.sh(17:50 主链末尾) | all | **主链专项(审查报告 C-5)**:旧外层锁排队超时 600s=当天全站缺一天(update_all 主链 deploy 被跳过)。去掉后段1 锁外立即跑,不再排队;段2 git 锁秒级排队(默认超时 3600s,充足)。 |
| 2-5 | futures / etf_national_team / lhb / rzhb backfill | 各自 mode | 四个 backfill 原先排队等锁超时=backfill 跳过=数据当天不上线(L37 同类)。去锁后段1 锁外并发,段2 短排队,不再因长 export 被跳过。 |
| 6-8 | public_fund_daily / full / quarterly | public-fund | 公募基金链路与 backfill 同构:原先 5.25h full 撞 02:00 锁跳过后续 deploy,当天 JSON 不上线。去锁后段1 锁外跑,段2 秒级排队。 |
| 9 | pipeline.sh(DEPLOY_EACH=1 时) | $NAME | 与 ①a 新形态一致;DEPLOY_EACH=0(默认)不调 deploy。 |
| 10 | index_backfill.py | backfill | Python 侧同构;保留 `cwd=repo` + `env REPO=str(repo)`(根治 2026-07-26 隐藏 bug:export 读镜像非主库)。 |

**重入/死锁论证**:deploy.sh 内部段2 取 `/tmp/trade_deploy.lock`,外层已无任何调用方再取同一把锁
包 deploy → 不存在双层取锁;锁获取顺序单一(git 写段),无环,无死锁。

**残留扫描(举一反三,grep 全仓 `with_lock.py ... trade_deploy.lock`)**:除上述 10 处外,以下持锁方
**不调 deploy.sh、不在本件范围,保留原状**:
- `staticdata_sync.sh` / `staticdata_backup_async.sh`:②③ 已改造为段2 才持锁,与 deploy 段2 同锁排队(正确)。
- `kelly_intraday_rerun.sh:50`:持锁重入自己是盘中防撞 git 写(`--nb` 非阻塞,撞锁跳过留给 17:50 全量),锁内不调 deploy.sh。
- `intraday_snapshot.sh` / `gold_night.sh`:进程互斥/注释说明,非调 deploy 的外层锁形态。
- `upload_r2.py:2404` 注释、`alert_denoise_rules.py` 告警文案:仅引用/注释,非调用。
- 无任何 `with_lock.py ... trade_deploy.lock ... deploy.sh` 调用残留(代码形态,已 grep 确认)。

## 5. 同类错误面清单(§23.2)

| # | 同类错误面 | 覆盖结果 |
|---|---|---|
| 1 | 所有「外层 with_lock 包 deploy.sh」调用(10 处) | 全拆除,统一 `bash deploy.sh <mode>` |
| 2 | deploy.sh 内部「git 段依赖段1 内定义」的函数/变量(if 块作用域陷阱) | `git_fetch_timeout`/`git_push_timeout` 移到公共区;`run_r2_upload` 仅在段1 用、段2 不引用(已核查) |
| 3 | rsync 覆盖写代码仓 tracked 文件(4 文件同类) | 一次性 4 个 exclude 全排除 |
| 4 | 状态跨 exec 丢失(git 段收尾告警依赖段1 累积的 R2_FAIL/MAP_STALE) | env 传递 + 段2 恢复 |
| 5 | 段2 重入时 `$0` 相对路径失效 | 全部调用方传绝对路径 `$REPO/scripts/deploy.sh`;deploy.sh 无 cd(唯一 `cd "$REPO"` 在子 shell 中,不改变主进程 cwd) |
| 6 | `NAME` 参数在重入后错位 | 顶部 `--git-phase` shift 后 `NAME="${1:-all}"` 正确取 mode(4 用例验证) |

## 6. 逐项自测结果

| # | 自测项 | 方法 | 结果 |
|---|---|---|---|
| 1 | 全部改动 shell 语法 | `bash -n`(deploy.sh + 9 调用方) | PASS |
| 2 | Python 语法 | `py_compile app/collector/index_backfill.py` | PASS |
| 3 | 全仓脚本静态检查 | `bash scripts/lint_scripts.sh`(bash -n + 全角扫描 + py_compile) | 全通过(rc=0) |
| 4 | `--git-phase` 参数解析 | 4 用例(`--git-phase all` / `--git-phase public-fund force` / `all` / 无参) | PASS(GIT_PHASE/NAME 全对) |
| 5 | 两段式 exec 重入链路 | 与 deploy.sh 同构模拟脚本 + 真实 with_lock.py + `DEPLOY_LOCK=/tmp/test_149a_deploy.lock` 隔离锁 | PASS(段1 锁外→exec→段2 持锁;R2_FAIL=channel-a,channel-b / MAP_STALE=1 跨 exec 传递成功) |
| 6 | 排队超时优雅跳过语义 | 隔离锁 `with_lock.py --block-timeout 2` 撞 `sleep 6` 持锁 | PASS(>2s 优雅跳过 exit 0,与原外层锁超时语义一致) |
| 7 | 函数作用域回归(§2.3 bug) | 模拟段2 重入进程调用公共区函数 | PASS(push rc=0,段1 内函数段2 不存在=预期) |
| 8 | 残留扫描 | grep 全仓 `with_lock ... trade_deploy.lock` | 无调 deploy 的外层锁残留(仅保留不调 deploy 的持锁方,见 §4) |

## 7. 复现段

- 两段式 exec 模拟脚本:`/tmp/test_149a_reexec.sh`(与 deploy.sh 段1/段2 同构,调真实 with_lock.py)。
  运行:`DEPLOY_LOCK=/tmp/test_149a_deploy.lock REPO_WITHLOCK=<worktree>/scripts/with_lock.py bash /tmp/test_149a_reexec.sh all`
  预期输出:段1 pid→exec 重入→段2 pid 打 R2_FAIL/MAP_STALE 已传递,末行 `RESULT_OK`。
- 函数作用域回归:`/tmp/test_149a_func_scope.sh` → `TEST_PASS`。
- 参数解析 4 用例:`/tmp/test_149a_args.sh`。

## 8. 本机验证不了的部分 + 云上验证命令

**本机(§14)未做**:不真跑 production deploy(export 会写生产数据 + push main);不验证云上 systemd
触发/锁竞争真实场景;不验证 17:50 update_all 主链真实排队消除(C-5 只能云上实测)。

**云上验证命令(上线后)**,按序:
```bash
# 1) 语法已在 lint 全过,上云前先确认改动已 push feat 分支
# 2) 云上取最新代码(git pull feat 分支后手动部署 deploy.sh)
# 3) 手动隔离锁跑 deploy 段1(验证段1 锁外不排队;注意避盘中/盘后时点):
DEPLOY_LOCK=/tmp/manual_test_deploy.lock bash /Users/linhuichen/code/trade-data/scripts/deploy.sh all 2>&1 | tail -20
#    预期: 段1 日志「锁外 export+R2+rsync」→ 段2 日志「锁内 git add/commit/push」,进程短时持锁
# 4) 验证锁队列不再被长活占死:
systemctl list-timers | grep -E "update_all|backfill|public_fund"   # 各任务不再因等锁超时被跳过
# 5) 17:50 主链观测:update_all.sh 日志不再出现「排队超时跳过 deploy」告警
# 6) 云上 git pull 验证 #119:ssh 云上 cd /Users/linhuichen/code/trade && git pull → 不再被 data/ 脏 M 挡
# 7) 若在锁内段2 观察:journalctl -u <deploy unit> 确认 git 段持锁时长秒级(<60s)
```

## 9. 结论

①a + ①b + #119 全部落地:deploy 锁职责回归「只串行 git 写段」;10 处调用方外层锁拆除、段1 锁外并发;
云上 pull 挡路 4 文件 exclude 根治。本机自验全过(语法/解析/重入/超时/作用域/lint);
真实锁竞争与 C-5 主链排队消除需云上按 §8 命令实测。
