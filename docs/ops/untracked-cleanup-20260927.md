# 未跟踪文件清理落档(2026-09-27)

> 任务:清理 trade 仓库 82 个未跟踪文件,归类落档 + 清 git status 噪音。**零丢失硬要求**。
> 做法:全部文件先进 git 历史(commit A),C 类一次性调试残留再 `git rm` 出工作区(commit B)。任何文件可 `git show <commitA>:<path>` 取回。
> 数据:git status --porcelain 全量 82 = docs 10 + scripts/playwright-accept 72;无任何 M/D 已跟踪改动。

## 一、体积与密钥扫描结果

- **体积扫描**:全部 82 文件逐一 `du -k`,最大 = docs/ops/branch-worktree-cleanup-20260923.md 32KB。**无任何 >20MB 文件**。
- **密钥扫描**:全部 82 文件逐一 grep `sk-`/`ghp_`/`AKIA`/`password=`/`token=`/`api_key=`,**零命中**。可安全入库。

## 二、A 类 = 正式报告(docs/ 下,共 10,进 git)

| # | 文件 | 类别 | 理由 |
|---|---|---|---|
| 1 | docs/auto-trade/k-day-vs-a-20260922.md | 调研报告 | K vs A 前端全信号表收益差异根因调研 |
| 2 | docs/auto-trade/nextday-buy-split-backtest-20260922.md | 回测报告 | 次日买入挂单策略穷举回测 |
| 3 | docs/auto-trade/scripts/nextday_buy_mix.json | 配套数据产物 | 报告 2 的混合比例全表数据 |
| 4 | docs/auto-trade/scripts/nextday_buy_mix_table.py | 配套生成脚本 | 混合比例全表复现脚本 |
| 5 | docs/auto-trade/scripts/nextday_buy_split.json | 配套数据产物 | 报告 2 的拆分挂单场景数据 |
| 6 | docs/auto-trade/scripts/nextday_buy_split_backtest.py | 配套生成脚本 | 报告 2 的拆分挂单回测脚本 |
| 7 | docs/kelly/analysis/signal-kelly-rolling-window-20260923.md | 调研报告 | 滚动窗口重算方案调研 |
| 8 | docs/ops/branch-worktree-cleanup-20260923.md | 运维报告 | 分支/worktree 清理清单 |
| 9 | docs/ops/task-slow-rootcause-20260923.md | 调研报告 | 盘后任务慢根因调研 |
| 10 | docs/ops/update-all-staticdata-backup-eval-20260925.md | 方案评估 | staticdata 备份积压方案评估(pending #110) |

### §23.5 四件套核对(A 类逐一)
- #1 k-day-vs-a:本体 ✓,生成脚本 = 复用前端页面实测+回测 JSON(报告内引 signal_kelly_backtest.json),复现段 ✓(报告含口径与锚点数字)
- #2 nextday-buy-split-backtest:本体 ✓,生成脚本 = #6 nextday_buy_split_backtest.py ✓,配套数据 = #5 nextday_buy_split.json ✓,复现段 ✓(报告含基线核对)
- #3/#4 nextday_buy_mix:配套数据 ✓ + 生成脚本 ✓(随 #2 一起,报告主体为 nextday-buy-mix-table-20260922.md 未在本次未跟踪清单内,脚本 docstring 有同构对账说明)
- #5/#6 nextday_buy_split:配套数据 ✓ + 生成脚本 ✓
- #7 signal-kelly-rolling-window:本体 ✓,调研类(只读实测),复现段 ✓(报告含方法描述)
- #8 branch-worktree-cleanup:本体 ✓,复现段 ✓(含判定方法),临时脚本放 /tmp 不入库
- #9 task-slow-rootcause:本体 ✓,调研类(只读),复现段 ✓(含数据来源)
- #10 update-all-staticdata-backup-eval:本体 ✓,调研类(只读),复现段 ✓(含证据来源)
- **注**:#1/#2 等报告是否缺独立配套 commit 以各自生成时状态为准,本次仅保证文件入库 + 可追溯,不编造补齐。

## 三、B 类 = 可复用验收脚本(scripts/playwright-accept/,共 22,进 git)

| # | 文件 | 理由 |
|---|---|---|
| 1 | measure-tier-card-static.mjs | 四档卡高度测量,参数化用法(`node <file> <CssFileAbs>`),长期可复用 |
| 2 | mobile_site_layout_audit.mjs | 移动端布局审计(`*_audit.mjs`),输出到 /tmp/codex-reports,可复用回归 |
| 3 | p0_verify_all_signal.mjs | 全信号表数据源 fetch 验证(验线上 JSON 源在位) |
| 4 | p0_verify_cards.mjs | 全信号表卡数字渲染验证 |
| 5 | p0_verify_fetch_sources.mjs | 数据源 fetch 链路验证 |
| 6 | p0_verify_live_vs_local.mjs | 线上 vs 本地渲染数字一致性验证 |
| 7 | tier-smoke.mjs | 四档卡冒烟测试,参数化(`node <file> [width] [--shots]`) |
| 8 | timeline_sigkelly_silent_fill.mjs | sigkelly 渐进加载全流程实测,带用法注释,§5.4⑦ 页面实测锚点 |
| 9 | verify_ai_candidate.mjs | AI 候选渲染验证 |
| 10 | verify_buy_rows.mjs | 买入行渲染验证 |
| 11 | verify_cac40.mjs | CAC40 信号验证 |
| 12 | verify_daily_brief_rename.mjs | daily brief 重命名渲染验证 |
| 13 | verify_gih_nav_gate.mjs | GIH nav 门控验收(场景1/2 完整验收脚本) |
| 14 | verify_gih_nav_gate_weaknet.mjs | GIH nav 门控弱网场景加强版 |
| 15 | verify_gih_nav_gate_weaknet2.mjs | GIH nav 门控弱网第四跑合并闭环 |
| 16 | verify_home_signal_0922.mjs | 首页信号渲染层验证 |
| 17 | verify_kelly_card.mjs | kelly 卡验证 |
| 18 | verify_kelly_param_bar_fix.mjs | kelly 参数栏修复验证,机器检查输出 JSON |
| 19 | verify_kept.mjs | kept 保留/排除验证 |
| 20 | verify_kept_debug.mjs | kept debug 验证 |
| 21 | verify_list_dates.mjs | 信号列表日期验证 |
| 22 | verify_universe_live.mjs | 线上回测宇宙渲染校验 |

## 四、C 类 = 一次性调试残留(共 50,先入库 commit A,再 git rm)

> 判定依据:同一问题反复迭代的临时探针(tmp/diag/probe/s06 探索系列),仅针对某一次特定排查,无长期复用价值。

| # | 文件 | 理由 |
|---|---|---|
| 1 | diag-freeze-lab.mjs | lab 页 freeze 单次诊断探针 |
| 2 | diag-lab-tmp.mjs | lab 页诊断 tmp 探针 |
| 3 | diag-lab2-tmp.mjs | 同上迭代(2) |
| 4 | diag-lab3-tmp.mjs | 同上迭代(3) |
| 5 | diag-lab4-tmp.mjs | 同上迭代(4) |
| 6 | diag-lab5-tmp.mjs | 同上迭代(5) |
| 7 | diag-lab6-tmp.mjs | 同上迭代(6) |
| 8 | p0-console-capture.mjs | P0 补测 console 抓取探针 |
| 9 | p0-console-home.mjs | P0 补测首页探针 |
| 10 | p0-console-probe2.mjs | P0 补测探索迭代(2) |
| 11 | p0-console-probe3.mjs | 同上迭代(3) |
| 12 | p0-console-probe4.mjs | 同上迭代(4) |
| 13 | p0-console-probe5.mjs | 同上迭代(5) |
| 14 | p0-console-probe6.mjs | 同上迭代(6) |
| 15 | p0-console-probe7.mjs | 同上迭代(7) |
| 16 | perf_arch_probe.mjs | 性能架构单次探针 |
| 17 | probe-kelly-all.mjs | kelly 全表探针 |
| 18 | probe-kelly-entry.mjs | kelly 入口探针 |
| 19 | probe-kelly-entry2.mjs | kelly 入口探针迭代(2) |
| 20 | probe-kelly-read.mjs | kelly 读取探针 |
| 21 | probe-kelly-read2.mjs | kelly 读取探针迭代(2) |
| 22 | probe-kelly-sdc-basis.mjs | 买入口径当日收盘单次调研探针 |
| 23 | probe-lab-tmp.mjs | lab 页 tmp 探针 |
| 24 | probe_0922_hover.mjs | 9-22 AI 建议 hover 单次探针 |
| 25 | probe_intraday_real.mjs | 盘中表格真实日期单次探针 |
| 26 | probe_intraday_tbl.mjs | 盘中表格探针 |
| 27 | probe_intraday_tbl_date.mjs | 盘中表格日期覆写探针 |
| 28 | probe_intraday_tbl_mock.mjs | 盘中表格 mock 探针 |
| 29 | s06_all_period.mjs | s06 全周期探针 |
| 30 | s06_compare.mjs | s06 对比探针 |
| 31 | s06_compare2.mjs | s06 对比探针迭代(2) |
| 32 | s06_explore.mjs | s06 结构探索探针 |
| 33 | s06_failopen_numbers.mjs | s06 fail-open 数字探针 |
| 34 | s06_kelly_numbers.mjs | s06 kelly 数字探针 |
| 35 | s06_new14_yearly.mjs | s06 NEW14 按年探针 |
| 36 | s06_period_dom.mjs | s06 周期 DOM 探针 |
| 37 | s06_y1_compare.mjs | s06 y1 对比探针 |
| 38 | s06_yearly_table.mjs | s06 按年表探针 |
| 39 | s06warn_fail_probe.mjs | s06 warn fail 探针 |
| 40 | s06warn_probe.mjs | s06 warn 探针 |
| 41 | tier-4tier-probe.mjs | 四档卡极端假数据探针 |
| 42 | tier-natural-height.mjs | 浮层自然高度探针 |
| 43 | tier-tap-probe.mjs | 移动端点按探针 |
| 44 | y1probe-live.mjs | y1 先渲染复现探针 |
| 45 | y1render-diag.mjs | y1 渲染中间态诊断探针 |
| 46 | y1render-diag2.mjs | y1 渲染诊断迭代(2) |
| 47 | y1render-diag3.mjs | y1 渲染诊断迭代(3) |
| 48 | y1render-diag4.mjs | y1 渲染诊断迭代(4) |
| 49 | y1render-diag5.mjs | y1 渲染诊断迭代(5) |
| 50 | y1render-local-verify.mjs | y1 渲染本地中间态对账探针(与 diag2-5 同系列,非长期验收脚本) |

## 五、commit 与 git rm

- commit A(入库 82 + 本报告共 83 个文件)
- commit B:`git rm` 上述 C 类 50 个文件出工作区

## 六、复现段:如何取回 C 类文件

C 类文件已删出工作区,但全部保存在 commit A 的历史里:

```bash
# 1. 找到 commit A
git log --oneline -3  # 第一个 commit 即入库 commit
# 或按日期定位
git log --oneline --since="2026-09-27" -- docs/ops/untracked-cleanup-20260927.md

# 2. 取回单个文件内容到 stdout
git show <commitA>:scripts/playwright-accept/p0-console-probe2.mjs

# 3. 恢复单个文件到工作区
git show <commitA>:scripts/playwright-accept/p0-console-probe2.mjs > /tmp/p0-console-probe2.mjs

# 4. 恢复全部 C 类(批量)
for f in $(git show <commitA> --name-only | grep '^scripts/playwright-accept/'); do
  mkdir -p "$(dirname "$f")"
  git show <commitA>:"$f" > "$f"
done
```

## 七、验证记录

- `git status --porcelain` 清理后:应只剩非本任务残留(若有),C 类 50 个已出工作区
- `git show <commitA>:scripts/playwright-accept/p0-console-probe2.mjs` 内容完整可读
- 分支 docs/untracked-cleanup-20260927,push 后 merge 由主控走 main-merge.sh
