# S06 held 语义修复报告(codex008 F2 P0②,2026-08-26 用户拍板)

> 任务:B 级核心算法修复——S06 sticky 状态机 held 语义回归公示。
> 审计来源:`docs/review/codex-claude2codex-20260826-008-s06-daily.json` F2(P0)。

## 一、背景与根因

S06 动态模式状态机(sticky_array)的 held(持有计数)旧实现**只在 premise 命中日递增**(gen/check 两处同源,v6 权威脚本同口径抄写无误但 v6 本身有锁死缺陷)。后果:a9 进入后若持续非命中,held 永久 < MIN_HOLD_DAYS=10,`stay=(broken<15)or(held<10)` 恒真 → **a9 永久锁死**,违反全站公示的时间语义「连续破坏 15 个交易日确认退出」。全史快照 2,865 天中 457 天(16.0%)effective_mode 因此失真(方向全部是 a9 多留)。

审计证据链:构造序列首日命中+后续 336 个非命中日 → 仅进入一次永不退出(codex state_machine_long_run FAIL)。

## 二、修法(用户拍板新语义)

**held = a9 生效交易日数**:进入当日计 1,其后每个交易日递增(无论当日 premise 是否命中);退出条件 = broken≥15 **且** held≥10(与原公示文字一致,原文字本就是时间语义,bug 在实现)。

改动清单:
| 文件 | 改动 |
|---|---|
| `scripts/gen_kelly_mode_s06_state.py` | build_daily held 新语义 + 头部口径注释 + provenance 锚点换新 |
| `scripts/check_s06_state.py` | 独立第二实现同语义重写(带 trace 返回)+ **新增 A5 锁死不变式断言**(全史任一 a9 生效日不得同时满足 held≥10 且 broken≥15)+ 合成长序列 fixture 双场景(纯持续非命中必恰 15 天切出/命中打断 broken 后 held 仍按时间走,T 收盘信号 T+1 生效对齐)+ A4 公示锚点换新 |
| `static-site/common.js` | tooltip held 定义句补公示 + 【举例】按新快照核实改写 + 对照数据换新 + L776 注释锚点换新 |
| `static-site/purpose-notes.js` | lab.sigkelly 内嵌 S06 段:held 定义补充 + 对照数值换新 |
| `README.md` | S06 段:held 定义补充 + 对照数值换新 + 功能锚点 1:1 按 20260826 快照改写 |

机检防漂移:A1 独立复算逐位一致(2865 行)+ A5 全史 0 违例 + fixture 双场景 PASS;fixture 对旧语义有检测力(旧语义场景一锁死 40 天被断言捕获,实测验证)。

## 三、快照全史重跑结果

- coverage 20141114~20260826,共 2,865 天;**a9 总天数 1,961 → 1,504**;**a9 区间 28 → 40 段**;switches=79
- 新旧 effective_mode 差异 **457 天(16.0%)**,方向全部为 a9→new15(锁死多留被正确切出)
- current={date:20260826, mode:a9, since:20260715}
- gen 幂等:连跑两次 daily md5=`063c1fa03f68aa5a` 逐位一致
- check_s06_state 五断言全 PASS(A1/A2/A3/A4/A5)

## 四、回测对照与公示锚点(2026-08-26 同引擎重跑)

同引擎 = mine28.simulate + top1_combined(A/P14PLUS1),唯一变量 held 语义(`scripts/s06-held-semantics-20260826/data/s06_newsem_vs_results.json`):

| 口径 | 旧语义 | 新语义(held=生效日数) |
|---|---|---|
| 验证段净利(2021 起) | +94,436.30 | **+100,572.43** |
| 最大回撤 | -3,811.27 | -3,811.27(trough 同 20221103) |
| 强平口径 | +82,057.81 | **+82,761.50** |
| switches_per_yr | 4.0 | 6.33 |

**分年差诚实标注(vs 旧语义同日重跑)**:2022 +1,014 / 2023 +2,019 / 2024 +4,296 / **2025 -3,538(唯一变差年)** / 2026 +2,344,合计 +6,136。2025 变差已写入 commit message 与 gen 注释,不选择性隐瞒(§5.1④)。

⚠锚点漂移特性:S06 动态回测数字随输入指数序列每日更新而漂移(08-25 首跑 94,150.61 → 08-26 同引擎旧语义复跑 94,436.30;gen 注释旧值 93,813.21 与 results json 差 337 即此病灶)。本次锚点取 2026-08-26 重跑值并注明日期;后续重跑回测须同步 gen 注释/common.js/purpose-notes/README/check A4 五处(注释日期即锚点时点)。

## 五、参数稳定性复核(独立件,只出数据不动参数)

q30(th=-3.524225)/cd15/minhold10 是旧语义下选出的冻结参数。用新语义引擎重跑 q×cd 全网格(qs=.2/.25/.3/.4/.5/.6 × cd=10/15/20/25/30,minhold=max(cd//2,5),选段 2016-2020 trailing 分位防前视,骨架=codex s06_grid_selection_freeze.py;`data/s06_held_sem_param_recheck.json`):

| 问 | 结论 |
|---|---|
| ①现参数新语义排名? | **(q30,cd15) 选段排名 1/30,新旧语义下均第一,不漂移** |
| ②网格最优是否变? | 不变:新旧语义 best 均为 q30/cd15(选段 +34,893 vs 旧 +35,615) |
| ③生产 minhold10 vs 网格派生 minhold7? | 新语义验证段完全一致(+100,038.94/mdd -3,811.27)——时间语义下 confirm 主导退出,minhold 不敏感,稳健性佳 |

**结论:现冻结参数在新语义下仍稳,无需变更(本报告不动 THRESHOLD/CONFIRM_DAYS/MIN_HOLD_DAYS;如需变更另行拍板 §23.7)。**

⚠口径差异标注:网格链 top1=A/NEW 静态池(best_val +100,038.94),锚点链=A/P14PLUS1 切换(+100,572.43),两口径基座池不同数字本就不同,均为各自链内相对比较有效,勿跨链对数。

## 六、上线时序风险上报主控

今晚 20:35 launchd `com.trade.s06-snapshot` 会用**主仓库脚本**重生快照:merge 若在 20:35 前完成则主仓已是新版自动衔接;若未赶上,**当晚快照与 R2 会被旧版链盖回旧语义(gen/check 全 PASS 静默回退)**,需次日 merge 后 force 补跑 `s06_snapshot.sh`(或手动重跑三段链)。当前 R2 已同步新语义快照(curl 验证 daily md5 与本地一致),git 渠道随 merge+deploy 追上(既有设计容忍窗口,s06_snapshot.sh 头注同口径)。

## 七、同类错误面排查清单(§23.2③)

1. held 语义复刻处:全站仅 gen/check 两处(已同改);前端零自算(grep common/app/lab 无 sticky 状态机,lab.js "sticky" 为 CSS 吸顶无关);check_s06_freshness 只查新鲜度不含状态机 ✓
2. 旧锚点数值残留:+93,813/+81,435/+94,150 全站(js/py/html/md 非 min)grep 清零 ✓
3. 公示三源(common.js tooltip/purpose-notes/README)held 语义句+对照数值+1:1 例子全部按新快照核实改写(例:6-09 段实为至 7-06 共 19 天、7-07 切出前恰 15 个连续非命中日,均从 20260826 快照逐日核实)✓
4. 历史报告(s06-mode-implement-report-20260825.md 等)含旧锚点数字,属当时事实记录不改本体,以本报告为准(§23.7 冻结精神)

## 复现

```bash
# ① 快照重生+机检(worktree 或 main):
python3 scripts/gen_kelly_mode_s06_state.py --repo /Users/linhuichen/code/trade-data --git-repo <git树>
python3 scripts/check_s06_state.py --repo <git树> --data-repo /Users/linhuichen/code/trade-data
# 输入依赖: trade-data/static-site/data/index/{csi1000,hs300}-all.json(截至 20260826)
# 关键口径: size_spread=csi1000 ret20-hs300 ret20,q30 冻结阈值 -3.524224785046781,
#           T 收盘信号 T+1 生效,held=生效日数(进入当日计1),broken>=15 且 held>=10 切出

# ② 新旧语义回测对照(锚点来源):
python3 docs/kelly/analysis/scripts/s06-held-semantics-20260826/s06_newsem_vs_14plus1.py

# ③ 参数网格(第五节):
python3 docs/kelly/analysis/scripts/s06-held-semantics-20260826/s06_held_sem_param_recheck.py
# ②③共用依赖: 同目录 external_factor_v6*.py 为 codex 工作副本归档(路径已本地化),
#  mine28_regime_rotation=docs/kelly/analysis/scripts/sim_window_loss_mining_20260822/
#  与 signal_kelly_trades.json; 数据版本: trades/index 截至 2026-08-26, 数字随数据更新会漂移见第四节
```
