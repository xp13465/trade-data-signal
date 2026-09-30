# #126 staticdata 收口执行结果(2026-09-30 夜 / 10-01 01:1x)

> 实施:implementer agent(worktree-agent-ac97136ca84199760),2026-10-01 01:00~01:20。
> 结论:**收口完成。9 目录 31239 个 tracked 文件移出 staticdata 仓 git 索引,灾备 git 段恢复提交**,commit `ee4a582c4` 已从云上 push 到远端 origin/main。

## 1. 干了什么

按执行计划 `docs/ops/126-staticdata-migrate-holiday-window-plan.md` §4.1/§4.2 + §9 口径,在云上 `/home/ubuntu/code/trade-data-signal-staticdata` 执行:

1. 前置进程检查:staticdata 相关进程无活(pgrep 仅剩自身 bash -c 包装进程),deploy.sh/upload_r2.py 亦无。
2. 基线记录:<del>见 §3 对照表</del> HEAD=`5242b7459 2026-09-28_19:01`、`git status --porcelain` = 4071、9 目录合计 31239。
3. `git rm --cached -r` 九目录(data/fund_nav etf accum_nav nav_bucket signal_kelly_trades_parts signal_kelly_trades_sdc_parts index lab trade_sim)→ 每目录 tracked 归 0。
4. 提交前核对:staged 变更 = **仅 31235 条 D(全在 9 目录下)**,非 9 目录 staged 条目 = 0。
5. 阈值检查:`large_json_excludes.py --check-staged --repo <staticdata>` 退出码 **0**(文件数=0 字节=0 超阈值=0,原因见 §4 异常 2)。
6. .gitignore 覆盖验证:dry-run `git add -n .` 含 9 目录的条目 = **0**(`.gitignore` 受管区块已逐文件精确路径覆盖 9 目录,计数见 §3 对照表)。
7. commit + push:commit `ee4a582c4`,`git push origin main` 成功(`5242b7459..ee4a582c4 main -> main`,非快进冲突无)。
8. 回读验证:`git log origin/main -1` = `ee4a582c4`;9 目录 tracked 逐个 = 0;本地 main 与 origin/main 同 hash。

## 2. 收口后状态(终点快照)

- 9 目录 tracked 全部 = 0,磁盘文件完好(fund_nav 26458 / etf 1718 / trade_sim 504 / lab 65 抽样=迁移前基线)。
- `git status --porcelain` = 163(7 `??` + 156 ` M`),**全部为非 9 目录数据文件**(overview.json、a-stock-*、news_digest、signal_kelly_snapshots、db WAL 等),将随下个 staticdata 备份 commit 正常提交(预检 §5 已算:9 目录外 tracked 178.72MB < 500MB,`--check-staged` 必过)。
- 9 目录不再出现在 status(被 .gitignore 受管区块覆盖,不会 `git add -A` 加回)。

## 3. 基线 vs 收口后对照

| 项 | 迁移前基线 | 收口后 | 命令 |
|---|---|---|---|
| HEAD | `5242b7459 2026-09-28 19:01:13 +0800` | `ee4a582c4 2026-10-01 01:17:48 +0800` | `git log origin/main -1 --format="%h %ci %s"` |
| status 变更数 | 4071 | 163(7??+156M,非 9 目录) | `git status --porcelain \| wc -l` |
| fund_nav tracked | 26458 | 0 | `git ls-files data/fund_nav \| wc -l` |
| etf tracked | 1712 | 0 | 同上 |
| accum_nav tracked | 1712 | 0 | 同上 |
| nav_bucket tracked | 256 | 0 | 同上 |
| signal_kelly_trades_parts tracked | 383 | 0 | 同上 |
| signal_kelly_trades_sdc_parts tracked | 391 | 0 | 同上 |
| index tracked | 173 | 0 | 同上 |
| lab tracked | 65 | 0 | 同上 |
| trade_sim tracked | 89 | 0 | 同上 |
| 9 目录合计 tracked | 31239 | 0 | 逐目录加总 |
| 收口 commit D 条数 | — | 31235 D | `git diff --cached --name-status \| awk '{print $1}' \| sort \| uniq -c` |
| .gitignore 区块覆盖(fund_nav/etf/accum_nav/nav_bucket/parts/sdc_parts/index/lab/trade_sim) | 26458/1718/1717/256/383/391/173/65/504 | 不变 | `grep -c "^/$d/" .gitignore` |

## 4. 异常/偏差如实记录

1. **status 4071 vs 已知基线 4070,偏差 +1**:新增 `data/news_digest/2026/2026-10-01.json`(今日 news-fetch 备份暂存,git log 无新 commit → 备份只 add 未 commit,正是收口要修的病)。按任务口径「记录差异,不阻断」处理。
2. **⚠ 关键发现:4071 条变更全部已 staged,而非任务假设的工作区未暂存态**。备份进程 staticdata_backup_async `git add -A` 后 commit 被积压阈值拦下,整摊(4060 M + 11 A)留在 index。若直接 `git commit` 会把 163 个非 9 目录数据文件一起带进收口 commit,违反 step4「只允许 9 目录删除 D」。处理:**对非 9 目录 staged 条目精准退暂存**(`git diff --cached --name-only --diff-filter=d -z | xargs -0 git restore --staged --`,只动 index 不动工作区),收口 commit 严格只含 9 目录删除。163 条数据变更留在工作区,随下个备份 commit 正常带走。→ **`--check-staged` 读数 0 字节 而非任务预算的 ~178.7MB**(178.72MB 是 precheck §5「9 目录外 tracked 总字节」=收口后下个备份 commit 的预计读数,非本次收口 commit 现值),exit=0 阈值关通过。
3. **D=31235 而非 31239**:4 个 9 目录内文件(accum_nav/158025.json、accum_nav/562450.json、etf/158025-all.json、etf/562450-all.json)相对 HEAD 是**暂存新增**(A),`git rm --cached` 直接移除不出 D;净效果仍是 31239 个 tracked 文件移出索引(31235 HEAD 删除 + 4 新增去除)。commit message 用准数「31235 tracked deletions」。
4. **无 push 冲突/无 force**:push 为普通快进 `5242b7459..ee4a582c4`,无 §23.11 事件。
5. **R2 兜底真实**:9 目录已从 git 移出后,唯一完整副本 = R2 固定前缀(large-json/<rel>.gz,31663 key,MISSING=0,5/5 md5 与磁盘一致,precheck 文档已验证)+ 云上磁盘双份;收口安全前提成立。

## 5. 遗留(交主控)

- `docs/pending-features-index.md` #126 状态更新由主控统一处理(本 agent 不碰)。
- 云上下个 staticdata 备份 commit(预计今日 17:50 deploy 或新闻备份触发)将首次恢复提交;建议主控盘中/盘后抽查一次 `git log origin/main -1` 确认有非本 commit 的新备份提交,验证「提交记录恢复」闭环。

## 复现段(每条数字的原始命令)

```bash
# 0) 进程无活
ssh -i ~/tdsignal.pem -o BatchMode=yes -o ConnectTimeout=15 ubuntu@122.51.111.173 'pgrep -af "staticdata_backup_async|staticdata_sync" || echo CLEAR'        # → 仅自身包装进程
ssh ... 'pgrep -af "deploy.sh|upload_r2.py" || echo CLEAR2'                                                                                                # → 仅自身包装进程

# 1) 基线
ssh ... 'cd /home/ubuntu/code/trade-data-signal-staticdata && git log -1 --format="%h %ci %s" && git status --porcelain | wc -l'                            # → 5242b7459 / 4071
# 9 目录 tracked 逐目录 git ls-files $d | wc -l → 26458/1712/1712/256/383/391/173/65/89,合计 31239

# 2) rm --cached
ssh ... 'cd /home/ubuntu/code/trade-data-signal-staticdata && for d in data/fund_nav data/etf data/accum_nav data/nav_bucket data/signal_kelly_trades_parts data/signal_kelly_trades_sdc_parts data/index data/lab data/trade_sim; do git rm --cached -r "$d"; done'
ssh ... 'cd ...staticdata && for d in <9dirs>; do printf "%s %s\n" "$d" "$(git ls-files $d | wc -l)"; done'                                                # → 每目录 0

# 3) staged 清洗(只动 index)
ssh ... 'cd ...staticdata && git diff --cached --name-status | awk "{print \$1}" | sort | uniq -c'                                                          # → 7 A / 31235 D / 156 M(rm 后,清洗前)
ssh ... 'cd ...staticdata && git diff --cached --name-only --diff-filter=d -z | xargs -0 -r git restore --staged --'                                      # → 退暂存 163 个非 9 目录条目
ssh ... 'cd ...staticdata && git diff --cached --name-status | awk "{print \$1}" | sort | uniq -c'                                                          # → 31235 D(全 9 目录)
ssh ... 'cd ...staticdata && git diff --cached --name-only --diff-filter=d | grep -vE "^(data/(fund_nav|etf|accum_nav|nav_bucket|signal_kelly_trades_parts|signal_kelly_trades_sdc_parts|index|lab|trade_sim)/)" | wc -l'   # → 0

# 4) 阈值 + gitignore 佐证
ssh ... 'cd ...staticdata && python3 /home/ubuntu/code/trade-data-signal/scripts/large_json_excludes.py --check-staged --repo /home/ubuntu/code/trade-data-signal-staticdata; echo exit=$?'     # → 文件数=0 字节=0 超阈值=0,exit=0
ssh ... 'cd ...staticdata && git add -n . | grep -cE "^add .*data/(fund_nav|etf|accum_nav|nav_bucket|signal_kelly_trades_parts|signal_kelly_trades_sdc_parts|index|lab|trade_sim)/"; echo grep_exit=$?'            # → 0,grep_exit=1(无匹配)

# 5) commit + push
ssh ... 'cd ...staticdata && git commit -m "migrate: 9 dirs (31235 tracked deletions) out of git tracking, R2 backup complete"'                              # → [main ee4a582c4]
ssh ... 'cd ...staticdata && git push origin main'                                                                                                          # → 5242b7459..ee4a582c4 main -> main

# 6) 回读
ssh ... 'cd ...staticdata && git log origin/main -1 --format="%h %ci %s"'                                                                                  # → ee4a582c4 2026-10-01 01:17:48 +0800
ssh ... 'cd ...staticdata && for d in <9dirs>; do printf "%s %s\n" "$d" "$(git ls-files $d | wc -l)"; done'                                                # → 每目录 0
ssh ... 'cd ...staticdata && git rev-parse main origin/main'                                                                                                # → 两行同 hash ee4a582c4...
ssh ... 'cd ...staticdata && for d in data/fund_nav data/etf data/trade_sim data/lab; do printf "%s %s\n" "$d" "$(find $d -type f | wc -l)"; done'           # → 26458/1718/504/65(与 precheck 磁盘基线一致)
ssh ... 'cd ...staticdata && git status --porcelain | awk "{print substr(\$1,1,1)}" | sort | uniq -c'                                                       # → 7 ? + 156 M(=163,全非 9 目录)
```