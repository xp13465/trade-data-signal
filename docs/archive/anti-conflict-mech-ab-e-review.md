# 防再犯机制 A/B/E 审查报告(reviewer, 2026-08-19)

- 分支:feat/anti-conflict-mech-a-be(基于 main 4798fa487)
- 审查 commit:854d3c62a(A/B: check_version_progress.py + deploy.sh 挂点) + dafb53c54(E: pick_repo.py + 三脚本接入)
- 审查方式:只读 + git worktree 隔离真实场景验证(所有验证命令见「## 复现」)
- 结论:**PASS(有条件)**——核心机制正确、真实事故场景能抓、正常 deploy 不误伤;1 个 P1 建议修复后 merge

## 一、A 版本串倒退哨兵(核心)

### 1.1 天花板算法能抓本次事故 ✅
用真实 git 历史 worktree 隔离验证:
- `efa92ffd8`(事故 merge 提交,版本串 a349):**FAIL**,`app/lab/common/style` 4 个 asset 全报
  「当前 20260818-a349 < 最近祖先天花板 20260818-a350(@ 5c8ba51a)」,exit 1
- `a084cd74a`(immediate 父,a348):**FAIL**,同样抓到天花板 a350

即:merge 提交处 immediate 父已倒退(a349>a348 直接比父抓不到),但 first-parent 链 40 commit 窗口内
含 bf8841966 的 a350 天花板能抓到——「天花板而非仅 immediate 父」的设计在本事故上验证成立。

### 1.2 不误伤正常 deploy ✅(逐场景实测)
| 场景 | 实测结果 |
|---|---|
| 合法前进(4798fa487 main 上线点) | PASS 无告警 |
| feat HEAD(dafb53c54) | PASS 无告警 |
| 纯数据改动(改 data JSON,不动源码/版本串) | PASS 无告警 |
| 文件没变版本串不变(无 diff commit) | PASS 无告警 |
| 源码 diff 未 bump(模拟忘 bump) | 告警 + PASS(exit 0 不阻断,符合设计) |
| index.html 缺失 | FAIL(exit 1) |

### 1.3 asset 路径匹配 ✅
`./app.min.js?v=20260818-a352` 等引用格式与 KEY_SOURCES 映射(app.js→./app.min.js,
lab.js→./lab.min.js, common.js→./common.min.js, style.css→./style.min.css)完全一致。

### 1.4 ⚠️ P1:git 仓库异常时静默放行(违反 §23.11)
`main()` 中:
```python
if not head or not parent:
    return 0 if not parent else 1
```
**实测 `--repo /tmp/not-a-git-repo-xyz`(无 git 仓)exit=0(静默放行)!** head/parent 都解析失败时
`not parent` 为真 → return 0。语义方向错——本机制要防「静默吞掉」,自身却在 git 仓库不可用时
静默放行,会给「校验通过」的假安全感。
- 同类问题:check_a 中 rev-list 失败(chain 空)→ 全部 asset 天花板跳过 → 静默放行;check_b 中
  `rev-list {parent}~1` 失败 → continue 跳过。
- 修正建议:`if not head: return 1`;仅「head 有、parent 无(首提交)」才 return 0。
- 触发概率低(deploy 实际传 --repo=trade,恒有效),但方向错,建议修后 merge。

## 二、B merge 净回退校验

### 2.1 逻辑 ✅
版本串未前进(≤ 父)且内容 ≠ 父时,当前内容 md5 与父之前 40 个影响该文件的 commit 比对,命中更旧
commit = 净回退 FAIL。事故场景验证:efa92ffd8/a084cd74a 内容已不在历史(被新内容替换)故 B 未命中、
由 A 拦截;净回退场景(synthetic)由 A/B 中对应分支覆盖,逻辑自洽。

### 2.2 cur_advance 判定细节(观察项,非缺陷)
`cur_advance` 只要任一 asset cur ≤ 父即置 False(多跑 B 保守方向),B 找不到历史命中就不 FAIL,
不会误伤;全部 asset 前进时跳过 B。设计偏保守,可接受。

## 三、deploy.sh 挂点位置与衔接 ✅

- 挂点 L330-344 位于:run_r2_upload(purge-low-freq)之后、git add min JS/CSS(阶段2)之前,
  即 **push main(L386)之前**,位置正确。
- deploy.sh 头部注释「**总是 git push**」,无「只上传 R2 不 push」模式 → 不存在非 push 场景误跑;
  盘中 intraday 走 R2 不调 deploy.sh(grep 确认),挂点只在盘后/手动上线链路跑。
- 无 set -e(每步显式判退出码),`PROG_RC=${PIPESTATUS[0]}` 在 tee 管道后取 python 退出码正确;
  校验失败 exit 阻断并打印清晰错误信息,不会卡死(是 FAIL 方向,安全)。
- **trade-data 侧已同步**:trade-data/scripts/check_version_progress.py 与 trade md5 完全一致,
  trade-data/scripts/deploy.sh 与 trade 版本 diff 为空(含挂点)。launchd 从 trade-data 跑不会
  因脚本缺失 FAIL 卡死正常上线。
- 与 §24⑤ 既有 check_version_consistency.py(格式/断链/内容 md5)互补不冲突:旧=静态完整性,
  新=版本串单调进度,两者都在 push 前跑。

## 四、E pick_repo.py + 三脚本接入

### 4.1 行为等价性 ✅
- trade-data/scripts 是 trade/scripts 的 **symlink** → pick_repo.py 从 trade-data 跑时
  `__file__.resolve()` 解析到 trade(git 仓),pick_git_repo() 恒返回 trade,正确。
- pick_repo CLI 生产实测:deploy 模式 → `/Users/linhuichen/code/trade-data`,git 模式 →
  `/Users/linhuichen/code/trade`;trade-data 与 trade 的 overview.json.date 同为 20260818
  (同日期优先 trade-data)→ 生产恒解析到 trade-data,guard 放行,正常写不被误伤。
- 三脚本(fetch_news/gen_daily_brief/overfit_monitor)venv import 全 OK;全仓库无
  `env.setdefault("REPO")` 残留;fetch_news 的 R2 上传与 staticdata 同步两处 subprocess 均走
  force_env(env=env),3 个上传点行为一致。

### 4.2 force_env 的 GIT_REPO 值变化(观察项,低风险)
原 fetch_news 设 `GIT_REPO=repo`(部署源树),新 force_env 设 `GIT_REPO=pick_git_repo()`(trade git 仓)。
查子进程用法:upload_r2.py 中 GIT_REPO 仅用于 .env 查找第 2 优先级 fallback(主路径 ROOT/.env);
staticdata_sync.sh 中 GIT_REPO 仅用于 with_lock.py 路径(存在,且与 scripts symlink 同文件)。
影响为 fallback/等价值,不改变主数据路径,风险低。

### 4.3 ⚠️ P3:guard 触发时无主动告警
overfit_monitor 在 launchd 定时任务跑,若 guard 触发(如 trade-data 意外 stale → pick_repo 解析到
trade → SystemExit 阻断),仅 stderr traceback 进 launchd 日志,无飞书/邮件告警,可能静默失败一段时间。
建议 guard 阻断时发告警。生产正常不触发(trade-data 恒最新),故 P3。

### 4.4 ⚠️ P3:fetch_news import 用宽 except 双路径
`try: from scripts.pick_repo import ... except Exception: from pick_repo import ...`——若第一路径
因 pick_repo.py 自身 import 报错会静默 fallback 第二路径;两路径都失败才 ImportError 崩溃(不静默)。
宽 except 有吞错隐患但最终不静默,低风险。

## 五、回归面

- deploy.sh 主链路仅加 16 行挂点,push 前阻断、错误信息清晰、无 set -e 依赖;不影响既有
  build_min/rsync/R2 步骤;验证了挂点实机等价命令(`$PY $REPO/scripts/check_version_progress.py
  --site-dir $GIT_REPO/static-site --repo $GIT_REPO --deploy-mode`)在真实 trade/trade-data 路径 PASS。
- 三脚本删本地重复 pick_repo 逻辑改走共享 helper,生产行为等价(4.1);overfit_monitor REPO 从
  dirname(SCRIPT_DIR) 改为 guard(pick_repo()) 属设计意图(统一部署源树,防双副本写偏)。
- 本次不改数据产物,无 §22 三处同步问题;§23.11 已在 CLAUDE.md L337。

## 六、问题清单(按严重度)

| 级别 | 问题 | 位置 | 建议 |
|---|---|---|---|
| P1 | git 仓库异常(head/parent 解析失败)时 exit 0 静默放行;同类:rev-list 失败天花板跳过/历史比对失败跳过也静默放行 | check_version_progress.py main() L312-316 / check_a L174-198 / check_b L269-288 | `if not head: return 1`;仅首提交 return 0;git 历史查询失败按 FAIL 处理 |
| P3 | guard_deploy_source_tree 触发仅 SystemExit,无主动告警(launchd 下可能静默) | pick_repo.py L96-101 | 阻断时发飞书/邮件 |
| P3 | fetch_news import 宽 except Exception 双路径 | fetch_news.py L82-91 | 可收窄为 ImportError |
| P3 | check_a 告警集合比较只取 batch 忽略日期(跨天+手动重置 batch 可能误告警,不阻断) | check_version_progress.py L210-219 | 可含日期比较,低优先 |

## 七、验收口径自查

- ✅ 版本串倒退哨兵:真实事故 efa92ffd8/a084cd74a 均 FAIL;4 个正常场景不误伤
- ✅ deploy 挂点:push main 前、无 set -e 卡死路径、trade-data 同步一致
- ✅ E 接入:3 脚本 import OK、无 setdefault 残留、subprocess 全走 force_env、生产解析 trade-data
- ⚠️ §23.11 自审:发现 P1「异常时静默放行」——机制自身存在一个静默口子,建议修复后 merge

## 复现

- 依赖:git 仓库(含 efa92ffd8/a084cd74a/4798fa487 历史)+ trade-data 与 trade 双目录
- 命令(worktree 隔离验证):
  ```
  git worktree add --detach /tmp/wt-<commit> <commit>
  python3 scripts/check_version_progress.py --site-dir /tmp/wt-<commit>/static-site --repo /tmp/wt-<commit> --deploy-mode
  ```
  efa92ffd8 / a084cd74a → 期望 FAIL(exit 1);4798fa487 / dafb53c54 → PASS(exit 0)
- 异常场景:
  ```
  python3 scripts/check_version_progress.py --site-dir <任意含 index.html 的 static-site> --repo /tmp/not-a-git-repo-xyz --deploy-mode
  ```
  → 实测 exit 0(应为 FAIL,P1)
- 数据版本:2026-08-18 版本串机制(a352),git 历史截至 dafb53c54
