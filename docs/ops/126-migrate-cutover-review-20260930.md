# #126 staticdata 收口独立复核报告(2026-10-01)

> 复核:reviewer agent(独立 fresh context,只读,云上零写),2026-10-01。
> 复核对象:实施 agent 报告 `docs/ops/126-migrate-cutover-result-20260930.md`(commit c120aed8a)+ 云上 `/home/ubuntu/code/trade-data-signal-staticdata` 实际状态。

## 结论:PASS

收口真实完成且无副作用。9 目录 31239 文件(31235 HEAD 删除 + 4 暂存新增)移出 git 索引,磁盘数据完好,`.gitignore` 逐文件覆盖防加回,commit 内容纯净(31235 全 D、零非 9 目录混入),本地 main 与 origin/main 同 hash,报告每个数字与云上实测逐位一致。

## PASS/FAIL 逐项表

| # | 核查点 | 结果 | 证据(云上实测原始命令 + 输出) |
|---|---|---|---|
| 1 | 收口 commit 真实性 | PASS | `git log origin/main -3 --format="%h %ci %s"` → `ee4a582c4 2026-10-01 01:17:48 +0800 migrate: 9 dirs (31235 tracked deletions)...`;`git branch --show-current` → main;`git rev-parse main origin/main` → 两行均 `ee4a582c4ef9dcd758dcfd9768a6c3ed3ca52eae`;parent=`git rev-parse ee4a582c4^`= `5242b745951c05c41e29a44e97fbbcde1ccb22f5`(与报告基线一致) |
| 2 | commit 内容纯净性(最关键) | PASS | `git show ee4a582c4 --name-status --format="" \| awk '{print $1}' \| sort \| uniq -c` → `31235 D`(全 D);非 D 行 `grep -cv "^D"` → 0;非 9 目录路径 `awk '$1=="D"{print $2}' \| grep -vE '^data/(fund_nav\|etf\|accum_nav\|nav_bucket\|signal_kelly_trades_parts\|signal_kelly_trades_sdc_parts\|index\|lab\|trade_sim)/'` → 空(无匹配 exit=1) |
| 3 | 9 目录移出索引 | PASS | 逐目录 `git ls-files data/<d> \| wc -l` → fund_nav/etf/accum_nav/nav_bucket/signal_kelly_trades_parts/signal_kelly_trades_sdc_parts/index/lab/trade_sim **全 = 0** |
| 4 | 磁盘文件完好 | PASS | `ls data/<d> \| wc -l`:fund_nav **26458**/etf **1718**/accum_nav **1717**/trade_sim **504**/lab **65**/nav_bucket 256/signal_kelly_trades_parts 383/signal_kelly_trades_sdc_parts 391/index 173;9 目录 `[ -d ]` 全 EXISTS。对照基线(fund_nav 26458/etf 1718/accum_nav 1717/trade_sim 504/lab 65)**逐位一致,数据未丢** |
| 5 | .gitignore 覆盖 | PASS | ①`.gitignore` 共 31708 行,**逐文件路径列举** 9 目录:`grep -c "data/fund_nav/"` = 26458、etf = 1718、accum_nav = 1717、nav_bucket = 256、parts = 383、sdc_parts = 391、index+lab = 238、trade_sim = 504 —— 与磁盘文件数全部一致;②`git status --porcelain \| grep -E '^\?\? data/(9dir)/'` → **空**(无未跟踪残留) |
| 6a | 异常1:4 路径「暂存新增」解释 | 成立 | 4 路径(accum_nav/158025、accum_nav/562450、etf/158025-all、etf/562450-all)`git show 5242b7459 --name-status` 无(grep exit=1)→ HEAD 中不存在,确为新增;`git show ee4a582c4 --name-status` 也无 → rm --cached 直接移除不出 D,解释成立;磁盘 4 文件均在(时间戳 09-30 22:27/23:10,收口前夕新生成);`.gitignore` 第 50/1515/1768/3234 行覆盖 |
| 6b | 异常2:163 条 restore --staged 工作区完好(最大风险点) | PASS | `git status --porcelain \| awk '{print substr($0,1,2)}' \| sort \| uniq -c` → `156  M` + `7 ??` = 163,**零 D、零暂存态**;7 条 ?? 全为正常新增(news_digest 2026-09-29/30、2026-10-01.json,signal_kelly_snapshots 20260929/30.json,db/stock_daily.db-shm/-wal);抽查 `git diff --stat -- data/a-stock-1y.json` → `1 insertion(+), 1 deletion(-)` 单值更新正常;`-- data/alert_analyze_sw_801010.json` → 102+/110- JSON 重写正常。**没有任何工作区删除/清空** |
| 7 | 收口后状态健康 | PASS | status = 163(156 M + 7 ??),`grep -cE "data/(9dir)/"` 于 status → **0**(9 目录完全不可见);163 条全为非 9 目录数据文件,`.gitignore` 不挡(故仍显示为变更),下个备份 commit 可正常带走 |
| 8 | 报告一致性 | PASS | 报告 §2/§3 所有可验数字与云上实测**逐位一致**:HEAD/status 163(7??+156M)/fund_nav 26458/etf 1718/accum 1717/nav_bucket 256/parts 383/391/index 173/lab 65/trade_sim 504(磁盘)与 gitignore 行数、D=31235、9 目录 tracked 全 0;§3 基线 tracked(etf 1712/accum_nav 1712/trade_sim 89)验证:commit D 分目录 = etf 1710 + 2 暂存新增(158025-all/562450-all)、accum_nav 1710 + 2(158025/562450)、trade_sim 89 = **31239 总涉及数,与报告逐位一致** |
| 9 | 本地 feat 分支内容 | PASS | 本地 `git show c120aed8a --stat` → 仅 `docs/ops/126-migrate-cutover-result-20260930.md \| 92 +++++++++++++++++++++`(1 file changed, 92 insertions),无夹带;分支归属 = `worktree-agent-ac97136ca84199760` |

## 发现的风险(不阻断,上报主控)

1. **`.gitignore` 采用逐文件列举(31708 行)而非目录级模式**(如 `data/fund_nav/`)**。9 目录是每日增长型数据(fund_nav 按基金+日期、trade_sim 按交易记录),未来新生成文件不在 .gitignore 列表中 → 会以 `??` 未跟踪出现 → 若备份脚本仍 `git add -A`,新文件会被**逐步加回 git 索引**,收口效果随时间侵蚀(单次单文件很小,不会触发 500MB 阈值,故是钝刀)。建议主控评估是否改用整目录 ignore(需确认备份脚本 add 范围,防止误伤仍需 tracked 的子集)。

2. **「下个备份 commit 恢复提交」闭环未验证**:报告 §5 自留验证项——建议主控盘中/盘后抽查 `git log origin/main -1`,确认出现非本收口 commit 的新备份提交(17:50 deploy 或 news 备份触发)。

3. **基线 4071 条全部已 staged 的积压病根未根治**:报告 §4.2 揭示备份进程 `git add -A` 后 commit 被积压阈值拦下、变更长期滞留 index(收口前 4071 条全 staged)。本次 restore --staged 只解了收口单次,积压机制本身仍在(23.7 冻结契约:此属发现的历史问题,上报等拍板)。

4. **低分项(<80)已滤**:0 条。

## 复现段(每条数字的原始命令)

全部命令为 ssh 云上只读(不 commit/add/restore/push,未改 index 与工作区):

```bash
# 1) commit 真实性
ssh -i ~/tdsignal.pem -o BatchMode=yes -o ConnectTimeout=15 ubuntu@122.51.111.173 'cd /home/ubuntu/code/trade-data-signal-staticdata && git log origin/main -3 --format="%h %ci %s" && git branch --show-current && git rev-parse main origin/main && git status --porcelain | wc -l'
# → ee4a582c4 2026-10-01 01:17:48 / main / 两行同 hash / 163

# 2) commit 内容纯净
ssh ... 'cd ...staticdata && git show ee4a582c4 --name-status --format="" | awk "{print \$1}" | sort | uniq -c'          # → 31235 D
ssh ... 'cd ...staticdata && git show ee4a582c4 --name-status --format="" | grep -cv "^D"'                              # → 0
ssh ... 'cd ...staticdata && git show ee4a582c4 --name-status --format="" | awk "\$1==\"D\"{print \$2}" | grep -vE "^data/(fund_nav|etf|accum_nav|nav_bucket|signal_kelly_trades_parts|signal_kelly_trades_sdc_parts|index|lab|trade_sim)/"'  # → 空

# 3) 9 目录 tracked
ssh ... 'cd ...staticdata && for d in fund_nav etf accum_nav nav_bucket signal_kelly_trades_parts signal_kelly_trades_sdc_parts index lab trade_sim; do git ls-files "data/$d" | wc -l; done'   # → 全 0

# 4) 磁盘文件
ssh ... 'cd ...staticdata/data && for d in fund_nav etf accum_nav trade_sim lab; do echo -n "$d "; ls $d | wc -l; done'    # → 26458/1718/1717/504/65(与基线一致)

# 5) .gitignore
ssh ... 'cd ...staticdata && grep -c "data/fund_nav/" .gitignore && grep -c "data/etf/" .gitignore && grep -c "data/accum_nav/" .gitignore && git status --porcelain | grep -E "^\\?\\? data/(fund_nav|etf|accum_nav|nav_bucket|signal_kelly_trades_parts|signal_kelly_trades_sdc_parts|index|lab|trade_sim)/"'  # → 26458/1718/1717 + 空

# 6b) 工作区完好(最大风险点)
ssh ... 'cd ...staticdata && git status --porcelain | awk "{print substr(\$0,1,2)}" | sort | uniq -c'                     # → 7 ?? / 156 M / 无 D
ssh ... 'cd ...staticdata && git diff --stat -- data/a-stock-1y.json'                                                    # → 1 insertion(+), 1 deletion(-)
ssh ... 'cd ...staticdata && git diff --numstat -- data/alert_analyze_sw_801010.json'                                     # → 102 110

# 6a) 异常1 对照
ssh ... 'cd ...staticdata && git show 5242b7459 --name-status --format="" | grep -E "(accum_nav/158025|accum_nav/562450|etf/158025-all|etf/562450-all)"'   # → 空(新增非历史)
ssh ... 'cd ...staticdata && git show ee4a582c4 --name-status --format="" | grep -E "(accum_nav/158025|accum_nav/562450|etf/158025-all|etf/562450-all)"'       # → 空(rm 直移不出 D)
ssh ... 'cd ...staticdata && ls -la data/accum_nav/158025.json data/accum_nav/562450.json data/etf/158025-all.json data/etf/562450-all.json'                    # → 4 文件均在

# 终验: parent + 各目录 D 数 + status 残留
ssh ... 'cd ...staticdata && git rev-parse ee4a582c4^'                                                                    # → 5242b7459
ssh ... 'cd ...staticdata && for d in etf accum_nav trade_sim fund_nav; do git show ee4a582c4 --name-status --format="" | grep -cE "^D[[:space:]]+data/$d/"; done'  # → 1710/1710/89/26458(+2+2 暂存新增=31239,与报告 baseline 对齐)
ssh ... 'cd ...staticdata && git status --porcelain | grep -cE "data/(fund_nav|etf|accum_nav|nav_bucket|signal_kelly_trades_parts|signal_kelly_trades_sdc_parts|index|lab|trade_sim)/"'   # → 0

# 9) 本地 feat 分支(本地主仓,只读)
cd /Users/linhuichen/code/trade && git show c120aed8a --stat --format="%h %ci %s"        # → 仅 docs/ops/126-migrate-cutover-result-20260930.md 92 行
```

## 复核范围说明

- 云上全程只读:未运行任何会改 index/工作区的命令(`git add -n` 等 dry-run 也未跑,未复现项直接标注;`.gitignore` 覆盖以 `git status` 无 `??` 残留为实证,等效成立)。
- 迁移前基线(4071/31239)已不可回检(收口后 HEAD 前移),以 commit parent 关系 + 收口 commit D 分目录数与报告 baseline 的交叉对齐为准。
- R2 兜底完整性(R2 侧 31663 key/md5)与进程无活属实施报告 §4 自验项,本次未重跑(超出只读核查点),依赖 precheck 文档 + 报告自述,已在「发现的风险」外备注。
