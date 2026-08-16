# 分析参考点 AI 监控卡:统计口径 10/15 曲线空白「样本不足」根因调研

> 调研日期:2026-08-16(功能上线当天排查)/ 2026-08-17 复核数据
> 调研 agent:role-researcher | 只调研未动代码,修复方案待主控派单

## 一句话结论

**不是数据没生成、也不是前端漏请求,是今天(08-16 commit 12bf87e37 a295)新加的「统计口径 10/15/30/60/100 可切」功能,在默认 K=1 + AI降亏过滤的 bank 里,10/15 日窗口的实盘样本数被结构性锁死在 10/15(n<20 阈值),永远点不出准确率曲线 —— 属于「阈值策略与 UI 档位不匹配」的设计缺口(用户视角=bug),且不会自愈。**

## 结论速览(每条带证据点)

1. **后端已按 10/15/30/60/100 五档全产数据** —— `scripts/overfit_monitor.py` L73 `WINDOWS = [10, 15, 30, 60, 100]`;数据文件 `static-site/data/overfit_monitor.json`(generated_at 2026-08-16 15:43,线上 CDN 同值已验证)所有 bank 的 `accuracy.rolling.actual/backtest` 都有 `"10"/"15"/"30"/"60"/"100"` 五套窗口,`config.windows=[10,15,30,60,100]`。

2. **根因 = K 档人口上限 × n<20 阈值冲突**:
   - 默认态 `_overfitState = {win:60, roll:60, grade:null, sigType:null, k:1}`(app.js L1525,K 默认 1)+ AI降亏过滤默认开 → `_ovBank()`(app.js L1874-1885)读 `filtered_by_k["1"]` bank。
   - `build_topk_kept_map`(overfit_monitor.py L454)按 signal_date 分组 quality 排序取 `items[:k]`,**K=1 每日只保留 1 个买入信号** → 10 日窗口实盘最大 n=10、15 日最大 n=15,永远 < 阈值 20。
   - 数据实测(filtered_by_k[1].accuracy.rolling.actual):w=10 全部 200 点 `n=10`、`win_rate=null`;w=15 全部 `n=15`、`win_rate=null`;w=30 起 n=30 有值。by_k[1] 同构。

3. **「样本不足」判定在前端,后端同阈值双层**:
   - 后端:`rolling_win_rates(..., min_n=20)`(overfit_monitor.py L688),L705-707 `n < min_n` 时该点 `win_rate=None`。
   - 前端:`_overfitSampleInsufficient`(app.js L1616-1621)取所选窗口序列**末点 n**,`n>=20` 才放行;否则 `_renderOverfitAcc`(L1653-1662)走空态「X日滚动窗口样本不足(n<20), 不画误导曲线」(L1661)。
   - 双层同口径且后端 win_rate 已全 null → 即使去掉前端判定,曲线也画不出来(数据层全是 null)。不是单点误判。

4. **空白的是上图准确率双曲线,下图风险分其实有数据**:filtered_by_k[1].overfit.daily_by_win["10"/"15"] 各 200 点 risk_score 非空(末点 40/yellow)。原因:风险分序列以**回测** win_rate 为基底(_derive_daily_series L1028,回测侧 K=1 每信号 3 模式 A/F/G → 10 日窗口回测 n=30 够 20),实盘侧 n=10 不足只影响上图。

5. **不会自愈(结构性)**:K=1 每日硬上限 1 信号 × 窗口天数 = 硬上限。交易日增长、21:40 定时重跑都不会把 n 推到 20。今晚(08-17 周一)21:40 为 launchd 首次定时触发(载入至今 runs=0,因 08-15 周六/08-16 周日为非交易日、Weekday 1-5 不触发;数据为 08-16 15:43 手动 rebuild 产物),重算后 K=1 的 10/15 仍 n=10/15。

6. **判定 = 设计缺口(需修)**:功能 08-16 当天上线(commit 12bf87e37 a295),未校验「统计口径 10/15」与「K 档默认 1 人口上限」的冲突 —— UI 提供两个默认态下永远点不出曲线的档位。非数据生成/请求/自愈类问题。

## 影响面(多档多维度穷举)

| 场景(bank) | w=10 | w=15 | w=30 |
|---|---|---|---|
| filtered_by_k[1](默认 K=1+降亏开) | n=10 空 | n=15 空 | n=30 正常 |
| by_k[1](K=1+降亏关) | n=10 空 | n=15 空 | n=30 正常 |
| filtered_by_k[2] / by_k[2] | n=18 空(临界) | n=26/27 正常 | 正常 |
| filtered_by_k[3] / by_k[3] | n=24/26 正常 | 正常 | 正常 |
| filtered_by_k[4] / by_k[4] | n=29/33 正常 | 正常 | 正常 |
| filtered(无 K 档,降亏开) | n=62 正常 | n=110 正常 | 正常 |
| raw/total(无 K 档,降亏关) | n=113 正常 | n=181 正常 | 正常 |

→ 受影响 = **K=1(默认态)的 10/15 全空 + K=2 的 10 日临界空**;无 K 档/降亏开关切换后 10/15 均正常。

## 证据点汇总(供主控 §0 单点 grep 验收)

| 环 | 位置 | 证据值 |
|---|---|---|
| 五档窗口配置 | scripts/overfit_monitor.py L73 | `WINDOWS = [10, 15, 30, 60, 100]` |
| 后端 min_n=20 | scripts/overfit_monitor.py L688 / L705-707 | `min_n=20`;n<min_n → win_rate=None |
| K 档每日 top-k | scripts/overfit_monitor.py L454 build_topk_kept_map | `items[:k]`,K=1 → 每日 1 信号 |
| 默认 K=1 | static-site/app.js L1525 | `_overfitState = {..., k: 1}` |
| 默认读 filtered_by_k[1] | static-site/app.js L1874-1885 `_ovBank()` | `filtered_by_k[kk]`(降亏开时) |
| 前端末点 n>=20 | static-site/app.js L1616-1621 | `return !(last && last.n != null && last.n >= 20);` |
| 前端空态文案 | static-site/app.js L1661 | 「样本不足(n<20), 不画误导曲线」 |
| 数据文件(本地=线上) | static-site/data/overfit_monitor.json | filtered_by_k[1].actual w=10 全 n=10/wr=null,w=15 全 n=15,generated_at 2026-08-16 15:43;CDN ss.fx8.store 同值 |
| 定时任务 | ~/Library/LaunchAgents/com.trade.overfit-monitor.plist | 21:40 Weekday 1-5;launchctl print runs=0(08-15 周六载入至今无工作日 21:40,今晚首次) |
| 功能上线 commit | git 12bf87e37(a295, 2026-08-16) | 统计口径可选 10/15/30/60/100 |

## 方案建议(供主控拍板,未动代码)

按 §5 默认准则给一步到位默认集,方向性分叉让用户 veto:
- **方案 A(推荐):样本充足阈值随窗口缩放**。把「flat n>=20」改为 `min_n = min(20, ceil(window*0.5))`(10→5、15→8、30→15、60/100→20),后端 `rolling_win_rates/rolling_win_rates_by_dim/_derive_daily_series` 的 min_n 与前端 `_overfitSampleInsufficient` 同步改;K=1 的 10/15、K=2 的 w=10 随之放行,空态文案同步显示按窗口阈值。统计意义诚实标注:10 例/15 例样本小,曲线工具提示已有「仅供参考」语境。
- **方案 B:默认态(K=1)禁用/置灰 10/15 档**,仅 K≥2 或无 K 档可用 —— 保统计门槛但不提供死档位。
- 涉及改「已发布功能行为/展示」,按 §23.7 需用户确认后主控才派实施。

## 复现

- **数据文件**:`static-site/data/overfit_monitor.json`(generated_at 2026-08-16 15:43;线上 `https://ss.fx8.store/data/overfit_monitor.json` 同值,已 curl 比对一致)
- **重跑命令**:`bash scripts/overfit_monitor.sh force`(交易日 21:40 定时自动跑;非交易日需 force;依赖 signal_kelly_trades.json + signal_daily/index_daily + indicators.yaml,见脚本头注释)
- **查看命令**:
  ```bash
  python3 -c "
  import json
  d=json.load(open('static-site/data/overfit_monitor.json'))
  a=d['filtered_by_k']['1']['accuracy']['rolling']['actual']
  for w in ['10','15','30']:
      arr=a[w]; print(w, 'len=',len(arr), 'last_n=',arr[-1]['n'], 'last_wr=',arr[-1]['win_rate'])
  "
  # 期望输出: 10 len=200 last_n=10 last_wr=None / 15 len=200 last_n=15 last_wr=None / 30 len=200 last_n=30 last_wr=50.0
  ```
- **口径一句话**:滚动窗口 n = 窗口内每日 top-K 保留买入信号唯一计数(实盘侧 K=1 每 1 信号/日);n<20 判样本不足(后端 win_rate 置 null + 前端末点 n<20 走空态)。数据截止:signal_daily_max_date=20260814。
