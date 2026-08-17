# update_all 2026-08-17 跑 88 分 17 秒(5292s)触发告警 — 慢因分析

> 调研日期:2026-08-17 | 调研人:role-researcher | 数据截止:2026-08-17 19:18:17

## 结论摘要

1. **88min 时间去哪了**:4 条 pipeline 各做一遍**完整 deploy**(export 353 JSON/281MB + 校验 + build_min + rsync + R2 342 keys + staticdata 备份 push 50MB),deploy 全串行共 **77.2min,占 87.5%**;etf_score 全市场评分 **8.5min**;采集/其余 ~3min。
2. **今天不是"非交易日异常触发"**:2026-08-17 是**周一(交易日)**,`交易日判断: IS_TRADING=1 FORCE=0` 正确,跑全量是正常行为(任务描述里的"周日"有误)。
3. **今天 88.2min 是 8 月唯一超 70min 的离群值**;但每遍 deploy 比 8/14 慢 5-7min 是**环境性**(mootdx 停服、东财封 IP、etf_score 同量任务慢 3.5min),非结构新增。
4. **阈值建议:保持 70min,不扩大**。8 月 >70min 仅今天 1 次且确属异常,70min 抓对了;扩阈值会放过真正异常。根因可优化 → 优先优化而非扩阈值。

## 1. 88min 时间线拆解(update_all_20260817_1750.log)

| 段 | 起 | 止 | 耗时 | 占比 | 说明 |
|---|---|---|---|---|---|
| 采集(并行 5 pipeline) | 17:50:05 | ~17:58 | ~8min | 9% | futures 21s / width mootdx 85batch fallback 224s / turnover 5200 parallel 6.3min / core 222 指标 |
| deploy×4(串行) | 17:50:07 | 19:07:23 | **77.2min** | **87.5%** | 每条 pipeline 完成采集后各做一遍完整 deploy |
| ├ futures deploy | 17:50:07 | 18:11:18 | 21.2min | | |
| ├ width deploy | 18:11:18 | 18:30:45 | 19.4min | | |
| ├ turnover deploy | 18:30:45 | 18:48:15 | 17.5min | | |
| └ core deploy | 18:48:15 | 19:07:23 | 19.1min | | |
| check_signals | 19:07:23 | 19:07:29 | 6s | | 信号邮件 |
| intraday+alert+analyze | 19:07:29 | ~19:09 | ~2min | | 快照+重算+预警 |
| **etf_score 全市场** | ~19:09 | ~19:17:30 | **507.5s** | **9.6%** | 1475 只 6 workers |
| fund 日更+评分 | ~19:17:30 | 19:18:17 | ~1min | | |
| **总** | 17:50:05 | 19:18:17 | **5292s=88.2min** | 100% | |

**TOP 慢点 = deploy 4 遍串行(77.2min)>> etf_score(8.5min)>> 采集(8min)**。

## 2. 历史基线对比(8 月 update_all 每日耗时)

| 日期 | 耗时 | 星期 |
|---|---|---|
| 08-03 | 33.1 | 一 |
| 08-04 | 38.5 | 二 |
| 08-05 | 38.1 | 三 |
| 08-06 | 49.4 | 四 |
| 08-07 | 53.1 | 五 |
| 08-10 | 54.0 | 一 |
| 08-11 | 59.3 | 二 |
| 08-12 | 21.5 | 三(异常快,疑部分失败) |
| 08-13 | 53.2 | 四 |
| 08-14 | 60.1 | 五 |
| **08-17** | **88.2** | **一(今天)** |

**统计(11 天):均值 49.9 / 中位 53.1 / 最小 21.5 / P80=59.3 / P90=60.1 / P95=88.2 / 最大 88.2**
**>60min 2 天(8/14 60.1,8/17 88.2);>70min 仅今天 1 天。**

### 各 pipeline deploy 耗时对比(8/14 vs 8/17)

| pipeline | 8/14 | 8/17 | 差 |
|---|---|---|---|
| futures | 14.4min | 21.2min | +6.8 |
| width | 12.9min | 19.4min | +6.5 |
| turnover | 12.7min | 17.5min | +4.8 |
| core | 12.6min | 19.1min | +6.5 |
| **合计** | **52.6min** | **77.2min** | **+24.6** |

## 3. 今天 deploy 每遍慢 5-7min 的根因(环境性,非结构新增)

**已排除**:并发负载(8/14 的 5200 parallel 用 18.9min、今天仅 6.3min,8/14 采集更重却 deploy 更快);数据量(281.8 vs 280.9MB 可忽略);check_universe_alignment(8/14 已有)。
**8/17 新增**:deploy 内 `check_version_consistency.py`(8/14 无),但为秒级文件校验,非主因。
**证据指向环境/网络**:
- mootdx 全停服:`pipeline_width` L4 "连续15只失败(阈值15),mootdx 疑似全停服,剩余70只改 baostock fallback",elapsed=224s。**8/14 同样停服且更慢(422s)** → mootdx 近期不稳是持续性问题。
- 东财封 IP:`pipeline_core` "连续3个换手率失败(东财封IP),提前结束剩余28个"。
- **etf_score 同量任务(1467 vs 1475 只、6 workers):8/14=295.5s,今天=507.5s,慢 212s(+3.5min)**——该任务大量网络 IO 取 OHLC,是最干净的"环境变慢"对照实验。
- 今天 etf_score 内 17 次 `[ohlc] WARNING ... 主源sina+fallback mootdx 均返空`(拉不到数据的重试浪费)。

## 4. 优化清单(按省时排序,每条:改什么/省多少/风险)

### O1. deploy 4 遍 → 1 遍(最大优化,可省 ~50-58min)
- **改什么**:现在 pipeline.sh 每条 pipeline 采集后各跑一遍完整 deploy(export 281MB+校验+build_min+rsync+R2+staticdata push 50MB)。改为前 3 条(futures/width/turnover)只 collect+compute,**不做完整 deploy**,只做轻量 commit+push 采集数据;最后一条(或统一)完成后再跑**一次**完整 deploy。
- **省多少**:按 8/14 水平省 3 遍 ≈ 38min;按今天水平省 ≈ 56min。
- **风险**:中。①需保证统一 deploy 时所有 pipeline 数据已写入 DB(依赖采集时序,现各 pipeline 串行部署正是为"谁先完成谁先上线"的渐进式上线设计);②改 update_all.sh/pipeline.sh 锁逻辑;③与"各 pipeline 独立上线,慢任务不阻塞快核心"的设计初衷冲突——需保留"采集数据小 push 及时上线",仅合并"完整 export+R2+备份"。
- **备注**:deploy 内 export 每次全量重算 353 JSON,4 遍=4 次重复重算,是最纯粹的重复劳动。

### O2. etf_score 提速(可省 2-3min)
- **改什么**:1475 只 ProcessPool 6 workers 用时 507.5s。①workers 提到 8-10;②对 `主源sina+fallback mootdx 均返空` 的 ETF 加结果缓存/降重试(今天 17 次空返浪费);③mootdx 选服务器频繁(今天 ~20 次"选择最快的服务器"),可复用已选服务器。
- **省多少**:按 8/14 水平 295s 推算,消除环境慢后 ~5min;稳定优化空间 ~2-3min。

### O3. mootdx 停服 fallback 降延迟(可省 2-4min,属外部因素)
- **改什么**:85 batch 今天 224s(8/14 422s)全耗在"15 连失败才判停服" + baostock fallback。可降连败阈值或提前并发切 fallback;确认 mootdx 服务器状态。
- **省多少**:~2-4min。
- **风险**:低-中(阈值太低可能误判单次抖动)。

### O4. check_version_consistency(8/17 新增)确认秒级即可忽略
- 若未来发现每遍 deploy 多出分钟级,需在 deploy.sh 各 stage 加时间戳日志定位(目前 deploy 内部无 stage 计时,本次无法精确定位 export/R2/git push 各自耗时,诚实标注)。

## 5. 阈值建议

- **结论:保持 schedule_monitor.sh 的 update_all>70min 阈值,不扩大。**
- 依据:①8 月 dur 分布 P80=59.3/P90=60.1,正常日离 70min 有 ~10min 缓冲,不误报;②>70min 8 月仅今天 1 次且确属异常(88min),70min 正确抓住了它;③扩到 80-90min 会放过真正异常(卡死/数据源全挂),违背"兜底告警"定位;④根因(4 遍 deploy)可优化,优化后正常 dur 有望 30-40min,缓冲更大,更不需要扩大。
- **注意双告警链**:update_all.sh L209 自身有 `ELAPSED>3600(60min)` 即 SEVERE 告警,今天同时触发"自身 60min SEVERE + 外部 70min 监控"两条。若优化后正常 30min,60min 阈值仍有足够缓冲。
- **若担心环境性慢再现**:可折中放 80min(P95≈88.2 附近),但**不推荐**——88min 中 ~25min 是环境慢,放 80min 下次类似异常就漏了。优先优化 O1。

## 复现

- **日志路径**:`/Users/linhuichen/code/trade-data/data/logs/update_all_20260817_1750.log`(汇总)+ `pipeline_{core,width,futures,turnover}_20260817_1750.log`(各 pipeline 独立日志)。
- **耗时统计命令**:对 update_all_*.log grep `update_all.sh 开始/结束` 起止相减;对 pipeline_*.log grep `deploy.sh 开始/结束` 得各遍 deploy 耗时。
- **历史 dur 分布**:同上对 `update_all_202608{03..17}*.log` 循环统计(见 §2 表)。
- **告警阈值**:`scripts/schedule_monitor.sh` L13(update_all>70min,8/14 从 30min 重标)+ `scripts/update_all.sh` L209(ELAPSED>3600 即 SEVERE)。
- **数据源证据**:mootdx 停服 fallback 见 pipeline_width L4/L7(elapsed=224s;8/14=422s);东财封 IP 见 pipeline_core;etf_score 耗时见 update_all 汇总日志 `[parallel] 完成 xxx s`(8/14=295.5s,8/17=507.5s)。
- **数据截止**:2026-08-17 19:18(update_all 结束)。
