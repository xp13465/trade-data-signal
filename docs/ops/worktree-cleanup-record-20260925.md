# worktree / 分支堆积清理执行记录(2026-09-25)

- **日期**:2026-09-25
- **执行**:主控(仓库级 git 运维,非业务代码实施)
- **依据**:审计报告 `docs/ops/worktree-audit-20260925.md` + 用户 2026-09-25 拍板「全部按你建议的来吧」
- **背景**:worktree 堆积不只是占磁盘 —— 它会**占死分支**。同一任务续跑时 agent `git checkout <原分支>` 报 `fatal: already checked out`,只能 cherry-pick 到新分支,造成分支身份漂移 + hash 漂移(根因见 memory `resume-same-task-reuse-branch`)

## 1. 清理范围

清理前 `git worktree list` = **28 个**(含主 worktree)。

### 1.1 删除 26 个 worktree

| 组 | 数量 | 处理 | 依据 |
|---|---|---|---|
| A 组 | 23 | 删 worktree,**分支保留** | 内容已全在 main(17 个为 main 祖先,3 个做过 blob 逐字节比对一致,其余为纯文档/已合入) |
| B 组 | 3 | 删 worktree + **删分支** | 见 1.2 |

A 组 23 个:

- `/private/tmp/wt-caliber-fix`(feat/backtest-caliber-report-20260923)
- `/private/tmp/wt-signal-freeze`(feat/signal-historical-freeze)
- `/private/tmp/wt-snapshot-p2`(feat/signalfreeze-p2-check)
- `.claude/worktrees/agent-a0871d3eef48492a7`
- `.claude/worktrees/agent-a13e6a52752824cbe`
- `.claude/worktrees/agent-a2116770808fae4ed`
- `.claude/worktrees/agent-a254918c7ae5f2985`
- `.claude/worktrees/agent-a2f56d09bf34000ff`
- `.claude/worktrees/agent-a4474317daa5a4a07`
- `.claude/worktrees/agent-a4d6d2f9ab211ddf4`
- `.claude/worktrees/agent-a6c5d46b28ba49275`
- `.claude/worktrees/agent-a7856132ec7f3894c`
- `.claude/worktrees/agent-a7a512194ebe31e43`
- `.claude/worktrees/agent-a85ae8e9941f8de93`
- `.claude/worktrees/agent-a90417b764ef6370a`
- `.claude/worktrees/agent-abd28234902d47e47`
- `.claude/worktrees/agent-ac8bf1e12974d4cc5`
- `.claude/worktrees/agent-ada4e557517366569`
- `.claude/worktrees/agent-ae2c9fa42fc7a6a21`
- `.claude/worktrees/agent-aec22047efaf26f81`
- `.claude/worktrees/agent-aec4d27d16e687b98`
- `.claude/worktrees/agent-af47e386c7e9e020d`
- `.claude/worktrees/agent-afd201d75625b1456`

### 1.2 删除 3 个分支(B 组,**hash 已记录可反查**)

| 分支 | 删除前 hash | 理由 |
|---|---|---|
| `worktree-agent-a550f7036cd5b2469` | `c5ea51a2a` | 北交所宽度 **2026-09-02 初版实施**。main 已演进为 `app/collector/bj_width.py`(299 行 vs 分支 `beijiao_width.py` 241 行)+ `scripts/fapi_bj_width_export.py`,且 `ea2b27aca` 已把导出改为 **18:10 链式内 export**(不等次日 17:50)—— 分支残留的 `com.trade.beijiao-width.plist`(launchd 18:15)是死物,其实施文档描述的旧管道会误导后来者。口径权威 = main 代码 + 已在 main 的调研报告 `docs/analysis/beijiao-exchange-width-universe-20260902.md` |
| `worktree-agent-ae30594839233ea8c` | `e73fcb646` | cgb_10y_etf self-ETF 可行性调研(结论「不配」)。**文档已 cherry-pick 进 main**(`d5ce38a01`,落 `docs/ops/cgb10y-self-etf-feasibility-20260924.md`)—— 负面结论留档可避免将来重复调研 |
| `worktree-agent-ae5e8d204adef9e71` | `be8c710f7` | proxy env 加固 delta 复审。**文档其实早已在 main**(`docs/ops/proxy-env-hardening-delta-review-20260924.md`),cherry-pick 出来是空 commit;其核心待办(PEAK_HOURS 同类漏网)亦已在 main 修掉(`8fbd8f1d4`) |

### 1.3 保留 2 个

- `/Users/linhuichen/code/trade`(主 worktree)
- `.claude/worktrees/codex-reviewer`(`codex/mobile-ux-a11y-overreach-v4`)—— codex 外审固定工作区,按 memory `codex-worktree-isolation` 保留

## 2. 可逆性说明

- **worktree 删除可逆**:`git worktree remove` 只删工作目录,**分支全部保留**(A 组 23 个分支未动),需要时 `git worktree add <path> <branch>` 一条命令恢复
- **分支删除**:B 组 3 个分支已删,hash 记录于 1.2;git 对象在 gc 窗口内仍可达(`git show <hash>` / `git cat-file -p <hash>`),超窗口后不可恢复。B 组 3 个内容均已在 main 或被判定为过时/死物,无信息损失
- A 组保留的 23 个分支构成「陈旧分支堆积」,本次**按建议不动**(可逆优先);若后续确认无回查需求,可再单独清理

## 3. 顺带发现(审计结论需修正处)

审计 agent 报告「proxy env 复审文档不在 main」**有误**:该文件早已在 main(`docs/ops/proxy-env-hardening-delta-review-20260924.md`),不在 main 的是**那个 commit**。判「内容是否已在 main」不能只看 commit 是否在 main 链上,要看**文件内容**是否已存在 —— 本次 cherry-pick 出现空 commit 才暴露该误判。

## 4. 结果

- worktree:**28 → 2**(主 + codex-reviewer)
- 本地分支:48 个(A 组 23 个分支按建议保留,可逆优先)
- 未动:任何 main 上的代码/数据
