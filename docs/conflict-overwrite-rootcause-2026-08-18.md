# 冲突覆盖/改动丢失频发根因调研(2026-08-18)

> 触发:用户「最近怎么老是出现冲突覆盖丢失的问题。之前好像没有 要查一下根因 避免再犯」
> 调研:researcher(只读),证据全部来自 `git log/git show/git rev-parse/git merge-base/git reflog` 实证,不凭记忆。

## 一、本案例完整链路(08-18 主案例:四档收窄改动被静默覆盖)

### 1.1 时间线
| 时间 | commit | 事件 |
|---|---|---|
| 14:05 | `bf8841966` feat(四档收窄仅沪深300) | app.js 色带轴 `max:1→max:2`(高度 1/2→1/4)+ 全站文案「大盘四档」→「沪深300四档」,版本串 bump `a349→a350`,8 文件 |
| 15:55 | `a084cd74a` fix(盘中KPI滞后) | main 继续推进,含 bf8841966 编辑 |
| 16:12:24 | `e3fa985c3` feat(首页要闻自动刷新) | **内容基于 bf 之前的旧 base(a349)提交**,app.js/index.html/app.min.js/about/privacy/sw 共 5 文件相对父 `a084cd74a` 是**内容倒退** |
| 16:12:51 | `efa92ffd8` merge(feat/news-home-auto-refresh) | ort 无冲突 merge 进 main,**静默吃掉 bf8841966 的 app.js 编辑** |
| 23:31 | `5feb2df69` fix(四档收窄): 恢复被 e3fa985c3 覆盖的四档改动 | 恢复 `max:2` + 沪深300四档文案,版本串 `a351→a352`(先 `b17833d65` 临时 commit 后 amend 并入) |

### 1.2 核心证据(每条可复核)
1. **祖先链含但内容不含**:`git merge-base bf8841966 e3fa985c3` = bf8841966 自身(bf 是 e3 的祖先);但 `git show e3fa985c3:static-site/app.js | grep -cE 'max: 2 },|沪深300四档：'` = **0**,`git show a084cd74a:static-site/app.js` 同查 = 2。**祖先在、编辑不在** = rebase/重写后内容丢失的典型签名。
2. **版本串倒退(哨兵信号)**:`index.html` 引用 `app.min.js?v=`:bf8841966=`a350`,e3fa985c3=`a349`,efa92ffd8=`a349`,HEAD(恢复后)=`a352`。**e3fa985c3 相对自己父 a084cd74a(a350)是版本倒退 a349**——提交内容整个来自 bf 之前的旧状态。
3. **merge 无冲突 = 静默**:`efa92ffd8` Merge: a084cd74a e3fa985c3,ort 策略,**无冲突标记**。因为 e3fa985c3 的父就是 a084cd74a,git 直接应用 e3 的 diff(= 含对 bf 5 文件编辑的回退),干净吃掉了 bf 的改动。
4. **丢失持续到修复**:`git log efa92ffd8..HEAD -- static-site/app.js` 为空(merge 后无 app.js 改动),即 efa92ffd8 之后的线上 app.js 一直是旧文案 `max:1`/「大盘四档」/「大盘 ·」,直到 23:31 才恢复。
5. **分支 reflog 极简**:`git reflog show feat/news-home-auto-refresh` = `e3fa985c3 commit` + `a084cd74a branch: Created from HEAD`,无 rebase/reset 记录 → 提交 e3fa985c3 时工作区 app.js 等就是旧内容(基于 a349 状态),与分支基点 a084cd74a(a350)不一致。**提交时「工作树内容 ≠ 提交基点内容」**。

> ⚠️ 修正任务假设:任务原文「e3fa985c3 直接父=a084cd74a(不含 bf8841966 的旧 base)」不精确——a084cd74a **含** bf8841966(祖先关系成立),正确的是 **e3fa985c3 的内容基于旧 base(bf 之前),相对父内容倒退**,不是父不含 bf。

### 1.3 同类但非内容回归的旁证
- `6da0a13e0`(14:47 lab凯利)版本串 a348 < 当时 main a350,但其 app.js **含** bf 标记(2)→ 只是版本串没跟着 bump,内容未回退,低危。
- `a3b2d142f`(13:44 方案B)a347 < 当时 a348,但方案B本身自带 max:2/沪深300四档 → 非回归。
- `9c39c2337`(11:30)版本串 a342 与 10:27 重复(没 bump)→ 版本串未前进,§24 隐患但不属覆盖。

## 二、同类案例全量清单(近 2 周,含今天全部)

| # | 时间 | 现象 | 根因类别 | 修复 |
|---|---|---|---|---|
| 1 | 08-18 16:12 | **e3fa985c3 静默覆盖 bf8841966 四档改动**(本报告主案例) | 工作树内容≠提交基点 + 无内容一致性校验 | 5feb2df69(23:31)已推 |
| 2 | 08-18 16:30 | **build_min 事故**:reset --soft 只移 HEAD 留旧工作区 → deploy 读工作区旧源生成旧 min 覆盖正确版 | 工作树内容≠HEAD + build_min 读工作区 | 222db1844(19:23)根治 |
| 2b | 08-18 18:37 | 2 号的下游症状:style.min.css 媒体查询被 16:30 deploy 重生成旧版覆盖回退 | 同 2 | 1ef1fb9e6 |
| 3 | 08-18 22:50 前 | **项6**:deploy.sh cp 目标写 trade(git 仓)而非 trade-data(上传源),rsync 反覆盖线上 board_etf_map 旧版 | 写部署源树路径错误 | 97b6fa4c7(reviewer 拦截) |
| 4 | 08-18 全天 | **fetch_news news_digest 同步写错目标树 → deploy rsync clobber 回 8/17**(数据覆盖) | 同 3 | e10ea0805(20:04)+cf85862d6+5c8ba51a8 |
| 5 | 08-18 | **多 agent 各自 push 缺 commit**:B/about 页 agent 各自会话 push,origin/main 一度缺 97b6fa4c7 | push 控制面分散 | 已进 origin/main |
| 6 | 08-18 17:00 | **091f26e5b**:deploy 在非 main 分支跑,push HEAD:main 把 feat commit 带上 main | deploy 分支约束缺失 | B3 根治(222db1844 含) |
| 7 | 08-18 15:55 | **a084cd74a**:异源兜底重构误删 cross_check_zt_pool 函数定义,需恢复 | 重构删定义漏调用方 | a084cd74a(与 #90 同根,memory refactor-delete-keep-callers-synced) |
| 8 | 08-18 11:30 | **9c39c2337**:盘中大盘四档 chip 被轮询覆盖丢失 | 前端运行时轮询重渲染覆盖(非 git 层) | 9c39c2337 |

**08-18 一天 ~10 起覆盖/丢失事件**,密度异常(08-17 主要是「数据过时/重锚」类运行时问题,git 覆盖类集中在 08-18)。

## 三、共性根因(4 条,按贡献排序)

1. **「工作树内容 ≠ 提交基点内容」无校验(贡献最大,直接导致 #1/#2/#2b)**:
   agent 在 worktree 里基于旧 base 的源文件做了改动(或 reset --soft 留旧工作区),提交/merge 后内容相对父**静默倒退**,没有任何环节校验「commit 内容与其父一致、版本串前进」。merge 是 ort 无冲突=自动放行,§24⑤ 校验只查 min 内容 md5(不查源码净回退),都拦不住。

2. **同文件(尤其 app.js 1.3MB)多 agent 并发改动无串行化**:08-18 一天内 app.js 被 10+ 个 feature agent 触碰(9c39c2337→5cca0e19e→61f78d493→cf85862d6→03e18acee→bf8841966→6da0a13e0→808861e05→a084cd74a→e3fa985c3),各自 worktree 隔离、各自 bump 版本串,§23.4 的「同文件串行排队」未强制执行。

3. **写部署源树/deploy 链路路径错误(导致数据覆盖 #3/#4)**:cp/写目标误写 trade(git 仓)而非 trade-data(上传源),deploy rsync 反覆盖线上产物。同类两次(项6/fetch_news)。

4. **push 控制面分散(#5/#6)**:多 agent 各自可直接 push main,无统一 merge 门;deploy 定时任务在非 main 跑会把 feat commit 带上 main(B3 已堵)。

## 四、变化点(为什么「以前好像没有」)

| 时点 | 证据 | 变化 |
|---|---|---|
| 08-05~08-11 | `git log --merges` 每日 1-2 个 | 单 agent 线性直推 main,顺序执行,无并发冲突 |
| 08-12 | 5 个 merge | **角色拆分日**(CLAUDE.md §0),开始派多 implementer |
| 08-13 | **25 个 merge**(08-17 峰值 27) | **多 agent 并发 + worktree 隔离工作流正式开始**(memory concurrent-implementers-worktree-isolation 08-12/08-15 两轮),每天 10-27 个 feature 分支 merge 进 main |
| 08-18 | 15 个 merge + ~10 起覆盖/丢失 | 冲突密度爆发日 |

**结论**:用户体感正确——08-12 角色拆分、08-13 起多 agent 并发 worktree 工作流,merge 频率从 1-2/天涨到 10-27/天,「工作树 stale + 无内容校验 + 同文件并发 + push 分散」四个洞在高并发下从偶发变成频发。

## 五、防再犯建议(按杠杆/成本排序,全部可落地)

| # | 建议 | 动哪个环节 | 成本 | 收益 |
|---|---|---|---|---|
| A | **版本串倒退哨兵**:任何 commit/merge 后校验 index.html 版本串 `>=` first-parent(倒退=内容大概率有 stale base 回归),加进 check_version_consistency.py,FAIL 阻断上线 | merge/上线校验 | 极低(1 行比较) | 直接抓本次事故类型(本次最早可见信号就是 a350→a349) |
| B | **merge 后「净回退校验」**:对每个 merge commit,`git diff M^1 M` 若含「删除 first-parent 近 3 天新增的关键行」→ 告警/阻断;轻量版=内置热门 marker 清单(app.js 的 max:2/沪深300四档 等) | merge 环节 | 中 | 抓 e3fa985c3 这类静默回退 |
| C | **同文件并发串行化 + worktree agent 不 bump 版本串**:app.js/lab.js 同时只允许 1 个 agent 持有改动权(主控派单前核对在跑 agent 文件范围);版本串统一由主控 merge 时跑一次 build_min+bump(消除 aXXX 撞号+stale bump) | 派单/实施层 | 低 | 消同文件覆盖主因 |
| D | **push main 统一入口**:agent 只 push feat 分支,merge+push main 由主控统一走(含 §24⑤+bump 校验);agent 完成报告必带「base commit + 版本串前后值」 | 协作层 | 低 | 消 push 分散缺 commit |
| E | **写部署源树统一 helper**:所有写 trade-data 源树的入口(gen_daily_brief/fetch_news/export)统一走 REPO 强制覆盖 helper(复用 cf85862d6/5c8ba51a8 逻辑),内部校验目标=源树非 git 仓 | deploy 链路 | 中 | 消数据 rsync clobber 类 |
| F | **回归口径补「近 N 天 marker 在位」**:reviewer/§15 回归 app.js 等大文件时,除验「本功能在」外,验「近 3-5 天其他功能关键 marker 在位」清单(防静默回退漏网) | reviewer/回归 | 低 | 补最后一道人查 |

**优先级建议**:A(今天就能加,直接抓本次类型)→ C+D(机制层消主因)→ B/E(纵深)→ F(回归习惯)。

## 复现
```bash
# 本案例核心链路(全部在 trade git 仓内可复现)
git log --graph --oneline --all | grep -E 'efa92ffd8|e3fa985c3|bf8841966|a084cd74a'
git rev-parse e3fa985c3^                        # = a084cd74a
git merge-base --is-ancestor bf8841966 e3fa985c3 && echo 含 || echo 不含   # 含(祖先)
git show bf8841966:static-site/app.js | grep -cE 'max: 2 },|沪深300四档：'   # 2
git show e3fa985c3:static-site/app.js | grep -cE 'max: 2 },|沪深300四档：'   # 0  ← 内容丢失
git show a084cd74a:static-site/app.js | grep -cE 'max: 2 },|沪深300四档：'   # 2  ← 父有
for c in bf8841966 e3fa985c3 efa92ffd8 HEAD; do git show "$c":static-site/index.html | grep -o 'app.min.js?v=[^"]*' | head -1; done  # a350→a349→a349→a352(倒退)
git log efa92ffd8..HEAD -- static-site/app.js    # 空 = 丢失持续
git reflog show feat/news-home-auto-refresh       # 分支极简,无 rebase/reset
# 变化点(merge 频率)
git log --merges --since="2026-08-04" --format="%ad" --date=format:"%Y-%m-%d" | sort | uniq -c
```
关键口径一句话:本次覆盖 = agent 以旧 base(a349)内容提交,merge 无冲突静默回退父(a350)的 5 文件 app.js 编辑,版本串倒退是哨兵信号。

*数据截止:2026-08-18 23:31(main=origin/main=5feb2df69,修复已推)*
