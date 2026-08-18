# 「覆盖丢失频发」诱因链深挖(2026-08-18/19)

> 触发:用户「虽然相处了根治方法。也定位到了多次覆盖 但是诱因还是没明确 为何以前没有 最近有 是和哪些优化有关么」
> 前置:`docs/conflict-overwrite-rootcause-2026-08-18.md` 已定位共性根因与粗略变化点(08-12 角色拆分/08-13 merge 暴涨),本文把「粗略变化点」实证成**具体诱因链**:哪几个优化/机制变化,把覆盖从「偶发」引出成「频发」。
> 调研:researcher(只读),证据全部来自 `git log/git worktree list/TASKS.md/memory` 交叉,不凭记忆。

## 一、结论一句话

**主诱因 = 08-12 角色拆分 + 08-12/08-13 worktree 隔离落地 →「多 implementer 并行工作流」正式开跑**(merge 从 1-2/天 → 25/天)。覆盖的本质是「两个改动基于不同 base,后 merge 者静默吃掉先 merge 者」,只有并发/并行工作流才可能产生;08-12 前是单 agent 同工作区顺序改、天然免疫。08-14 §24 版本串 bump 机制、08-15 push 规范强化是放大器(各自引入新洞)。

## 二、量化时间线(全部 git 实证)

### merge 数(按天,`git log --merges --since=2026-08-01 --date=short`)
| 日期 | merge | 备注 |
|---|---|---|
| 08-01 | 9 | 月初积压(非日常) |
| 08-02 | 12 | 同上 |
| 08-05~08-08 | 2/1/1/1 | **安全期基线:1-2/天** |
| 08-09~08-11 | 0/0/0 | 无 merge |
| **08-12** | **5** | **机制引入日**(3 跨分支 merge + 2 remote-tracking) |
| **08-13** | **25** | **转折/暴增日** |
| 08-14 | 13 | |
| 08-15 | 20 | |
| 08-16 | 14 | |
| 08-17 | **27** | 峰值 |
| 08-18 | 15 | 爆发日(全天 ~10 起覆盖/丢失) |

### app.js 大文件并发指标(涉及 static-site/app.js 的每日 commit 数)
08-01~08-12 稳定 16-33/天(单 agent 顺序,无并发碰撞);08-13=19、08-17=27。**merge 数才是并发密度的真正指标**(app.js commit 数被单 agent 时代的密集小提交掩盖,并发时代 commit 拆分到多个 feature 分支)。

## 三、机制引入时点(逐条 commit/文件/内存证据)

| 时点 | 机制 | 证据 |
|---|---|---|
| **08-12** | **角色拆分**(.claude/agents + .claude/skills 建立) | `64317b81a`(08-12 docs(role-context): 建 .claude/agents/ 4 角色)、`7e81a9cdb`(08-12 建 4 角色 skill)——「派多 implementer」的制度基础 |
| **08-12 21:28** | **首个 worktree**(agent-a0ba562fbe427e543) | `.claude/worktrees/` 目录 mtime 08-12 21:28;08-12 前**无任何 worktree**(目录 46 项最早 08-12) |
| **08-12** | **首个并发教训 memory**(3AI前端+feishu 同工作区污染) | `memory/concurrent-implementers-worktree-isolation.md`(08-12 首教训,08-15 强化为硬约束) |
| **08-13** | **worktree 批量**(12 个 agent-* + 命名 worktree) | 目录 mtime:agent-a85586e2bf15eac6d 03:31、agent-a34e1dd454faea5a1 12:18、agent-acfec23b5349368cd 12:08、agent-aea48888291da6db1 12:57、agent-a248413dde58b063c 13:26、agent-a3bbf174db52f1a32 13:49、agent-a27b93bf5c30087c2 14:58 等 + kelly-*/skin-theme-fix/sw-update 命名 worktree |
| **08-13** | **25 个 merge 全为并行 feature 分支「合入 main」** | 08-13 全部 merge message 为 `merge(feat-xxx): ... 合入 main`(凯利默认组合/首页AI开关/K档评级/降亏过滤/皮肤弹窗等大需求分解的多子任务) |
| **08-13 19:02** | **「merge 收尾统一 build_min+bump」模式** | `b92238bee`(08-13 19:02 build(merge收尾): 两分支合并后统一 build_min + bump_asset_version)——**08-14 §24 之前的权威 bump 模式** |
| **08-14 21:28** | **§24 前端部署/缓存/SW 防撕裂**(版本串 bump 机制「改码必同 commit bump」) | `f1f209068`(08-14 docs(规范): 新增§24…版本串改序号+改码必同 commit bump)——白屏 P0 根治,但把 bump 权威入口**从「merge 收尾统一」改成「每 agent 改码自己 bump」**,引入撞号新洞 |
| **08-15** | **push 规范强化**(agent push feat + 主控统一 merge) | `memory/concurrent-implementers-worktree-isolation.md` 2026-08-15 强化条款:「commit+push feat 分支,不直接 merge main(主控统一安排上线)」 |

> deploy.sh 自动 push main **不是新诱因**:`deploy.sh` 里 `git -C "$GIT_REPO" push origin main:main`(L386)是定时 deploy 的老机制(07 月 730 deploy 事故、08-05 单分支 feat 自动上线均已记录),R2 迁移后 data 已移出 git,deploy push main 只带代码。它在 08-18 变成放大器(091f26e5b 非 main 分支跑 deploy push HEAD:main 带 feat 上线),但**不是「以前没有」的原因**。

## 四、主诱因与放大器

### 主诱因(单点最大变化)
**08-12 角色拆分(制度)+ 08-12/08-13 worktree 隔离(机制)落地 = 多 implementer 并行工作流正式开跑**,merge 频率从 1-2/天 → 25/天(08-17 峰值 27)。

- 「以前没有」的机理:08-05~08-11 merge 1-2/天,单 agent/主控**同工作区顺序改**,每次改完 push 完再派下一个(memory feat-branch-deploy-pushes-func-commits 记录 08-05 还在单分支 dev 模式)。串行 = 天然无「两个改动基于不同 base」= 天然无覆盖。
- 覆盖的本质:两个改动基于不同 base,后 merge 者 ort 无冲突静默吃掉先 merge 者。**只有并发/并行才可能产生,串行免疫**。

### 放大器(按贡献排序)
1. **同文件(app.js 1.3MB)多 agent 并发无串行**:08-18 一天 10+ feature agent 触碰 app.js(根因报告 §三.2 列出 10 个 commit);§23.4「同文件串行排队」未强制执行。
2. **worktree agent 基于旧 base 提交,无前置校验**:主案例 e3fa985c3 基于 a349 旧 base(祖先链含 bf、内容不含)。根因报告 A/B 都是**事后拦**(merge/上线时),agent 开工前不强制 rebase origin/main、commit 前不校验 base 新鲜度——**事前无防护**。
3. **08-14 §24 bump 机制的多 agent 撞号**:各 worktree agent 各自跑 bump_asset_version → aXXX 撞号/stale bump(根因报告 §1.3 三个旁证:6da0a13e0 a348<main a350 / a3b2d142f / 9c39c2337 a342 重复);且与 08-13 已有的「merge 收尾统一 bump」(b92238bee)两种模式**并存冲突**。
4. **push 控制面分散执行未落实**:08-15 memory 强化「agent push feat,主控统一 merge」,但 08-18 #5 多 agent 各自 push 缺 commit、#6 deploy 非 main 分支跑 push HEAD:main——规范有,执行散。

## 五、诱因 → 根因报告五条机制对应表

| 诱因 | 对症机制 | 评估 |
|---|---|---|
| 08-12 角色拆分+多 agent 并行 | **C**(同文件并发串行化) | 部分对症:C 治「同文件并发」冲突面;「多 agent 并行本身」是用户要的效率,不可也不应消除,只能靠 C 把冲突面串行化 |
| 08-12/08-13 worktree 隔离 | **C + D** | worktree 隔离本身是对的(防同工作区污染),但引入新洞「基于旧 base 提交」→ 见缺口① |
| 08-13 并发密度暴涨(25 merge/天) | **C + D** | C 对症主因(消同文件覆盖);D 治 push 分散 |
| 08-14 §24 bump 机制撞号 | **A + C** | A 只拦「版本串倒退」,不拦「撞号/未前进但内容正确」(根因报告 §1.3 三个旁证);C 建议「主控 merge 时统一重跑 build_min+bump」= 回归 08-13 模式,与 §24② 冲突 → 见缺口③ |
| 08-15 push 强化未落实 | **D** | 对症但执行未落实(08-18 #5/#6) |
| 08-18 build_min 读工作区源 | 222db1844(§24 强化,非五条之一) | 已根治(reset --soft 禁+从 git HEAD 读源+deploy push 限 main) |
| 08-18 fetch_news 写错目标树 | **E** | 对症(写部署源树统一 helper) |

## 六、缺口(五条机制未覆盖的事前防线)

- **缺口①【最重要】无「base 新鲜度」事前校验**:worktree agent 开工前不强制 `git fetch origin && git rebase origin/main`,commit 前不校验「我的 base 距 origin/main 多久/多远」。A(版本串倒退)/B(净回退校验)全在 merge/上线时事后拦,事故已发生。**建议**:派单时钉 base commit;agent commit 前 fetch origin/main 比对 base,base 落后则先 rebase;commit 后 diff 校验关键 marker 在位(可并入 check_version_progress.py)。
- **缺口②「同文件串行」无工具支撑**:C 依赖主控记忆核对在跑 agent 文件范围(08-18 显然没执行到位,10+ agent 碰 app.js)。**建议**:派单时 grep 在跑 worktree 的改动文件清单(`git diff --name-only origin/main...<feat>`),同文件占用则排队,工具化替代记忆。
- **缺口③ bump 模式二义性**:08-13「merge 收尾统一 bump」 vs 08-14 §24「改码同 commit bump」并存。**建议**:明确唯一权威入口 = 主控 merge 时统一 bump(§24② 的「改码同 commit bump」在多 agent 下会产生撞号,应改为「agent 改码不 bump 或 bump 本地分支,merge 时主控统一跑 build_min+bump」),并保留 A 的倒退哨兵作为双保险。

## 七、一句话回答用户

「以前没有、最近有」= 以前(08-12 前)单 agent 同工作区顺序改、merge 1-2/天、无并发无覆盖;最近(08-13 起)角色拆分+worktree 隔离把工作流变成「10+ implementer 并行各改各的 app.js、每天 10-27 个 merge」,并发把「工作树 stale + 无内容校验 + 同文件并发 + push 分散」四个洞从偶发逼成频发。**主诱因是 08-12/08-13 的多 agent 并行工作流,不是任何单一代码改动;08-14 版本串 bump、08-15 push 强化是放大器/新洞来源。**

## 复现

```bash
# merge 按天(转折日 08-13:5→25)
git log --merges --pretty=format:'%ad' --date=short --since=2026-08-01 --until=2026-08-19 | sort | uniq -c | sort -k2
# 08-13 当天 25 个 merge 全为并行 feature 分支合入
git log --merges --since="2026-08-13 00:00" --until="2026-08-14 00:00" --format='%h %s'
# 角色拆分引入 commit(08-12)
git log --diff-filter=A --format='%h %ad %s' --date=short -- .claude/agents/ .claude/skills/
# worktree 批量出现时点(目录 mtime:首个 08-12 21:28,08-13 批量)
ls -la .claude/worktrees/ | awk '{print $6, $7, $8, $9}' | sort | head -20
# merge 收尾统一 bump 模式先例(08-13,§24 之前权威模式)
git show b92238bee --format='%h %ad %s' --date=format:'%m-%d %H:%M' -s
# 08-14 §24 bump 机制引入
git show f1f209068 --format='%h %ad %s' --date=short -s
# 覆盖事故集中日对比(08-14~08-17 覆盖类 commit 零散,08-18 爆发)
git log --since="2026-08-14 00:00" --until="2026-08-19 00:00" --format='%h %ad %s' --date=format:'%m-%d' | grep -iE '覆盖|丢失|回退|clobber|白屏|回归'
```
关键口径一句话:诱因链 = 08-12 角色拆分(制度)+08-12/08-13 worktree(机制)→ 08-13 起 25 merge/天多 agent 并行 → 覆盖本质「两改动基于不同 base 后 merge 静默吃掉先 merge」从不可能变频发;08-14 §24 bump/08-15 push 强化为放大器。

*数据截止:2026-08-19(根因报告修复 5feb2df69 已推,诱因链调研基于 08-01~08-18 git 全量)*
