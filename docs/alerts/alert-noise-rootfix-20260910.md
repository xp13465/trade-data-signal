# 告警噪音源盘点与根治方案(2026-09-10)

> 调研 agent 产出 | 纯调研不改代码 | 阈值修改方案待用户拍板后另派实施
> 进度: 数据口径 = trade-data/data/logs 真实日志 + alert_state.json + notify_dedup.json + latest.md

## 0. 结论摘要(先说人话)

**"每天告警有点多"的最大噪音源是 1 个根因 + 1 个放大器**:

1. **根因(必改)**:`update_all.sh` 内部耗时阈值 `3600s(1h)` 是 **2026-07-11 引入后从未重标**。08-14 调度监控(schedule_monitor.sh)已把 update_all 阈值从 30min→70min→135min 重标两次,但 update_all.sh 自己那个 1h 阈值一直漏着。而 update_all 实际耗时 08-17 起就破 1h,08-31~09-10 连续 9 个交易日 124~226min,**每天必发 1 封"耗时超1h"严重告警**——这是例行噪音,不是故障。
2. **放大器(顺手改)**:告警 dedup key 里**带了具体分钟数**(`update_all_severe:update_all 严重告警：耗时超1h(72分钟)`),每天耗时不同 → key 不同 → 去重完全失效,哪怕同一问题类型也每天新发。
3. **视觉放大器(低优先级)**:telegram 通道配置是占位符(YOUR_BOT_TOKEN),**从未真正启用**,每条告警都带 `telegram=FAIL`,加大"告警很多"的观感。

**其余告警多为一次性真故障或已自愈瞬时抖动**:今日(09-10)7 封里,deploy R2 上传失败是"单文件连接超时但实际 103/103 全部上传成功"的误报;nextday_plan rc=2 和 etf_national_team 退出失败都是同一根因(主树停在 feat 分支 → deploy 被拦)且已切回 main 根治。近 14 天真正有信息量的告警(数据断供/进程挂/分支事故)约 10 条,其余 40+ 条是 update_all 例行耗时 + 已自愈瞬时抖动。

**根治后预期**:每天告警邮件从 2~7 封降到 0~1 封(真故障才报),update_all 每天只留 1 封例行"完成"邮件。

---

## 1. 告警源全景清单(A)

| # | 告警源 | 触发条件 | 当前阈值 | dedup key | 近30天触发 | 分类 |
|---|---|---|---|---|---|---|
| 1 | update_all.sh 内部耗时告警 | 总耗时>3600s(1h) | **3600s(失真)** | `update_all_severe:...(含分钟数)` | **9 次(08-31~09-10 每交易日 1 封)** | **例行噪音** |
| 2 | schedule_monitor 耗时告警(update_all) | last_duration_sec>阈值 | 8100s=135min(#82 C6 重标) | `update_all\|dur>8100s` | 1 次(09-09 拿 09-08 的 175min) | 阈值合理,保留 |
| 3 | schedule_monitor 耗时告警(intraday_snapshot) | dur>600s(10min) | 600s(正常 286s) | `intraday_snapshot\|dur>600s` | 1 次(09-10 772s) | 真告警但低概率 |
| 4 | deploy.sh R2 上传失败 | upload_r2 某通道退出码≠0 | 各通道超时 300~7200s | `deploy_r2_upload_fail` | 1 次(09-10 18:52) | **误报(实际全成功)** |
| 5 | overfit 综合分>=60(红区) | risk_score>=60 | 60 | `overfit_overfit_high` | 1 次(09-08) | 真信号 |
| 6 | overfit 参数尖峰 | d3>=90(卖出模式微扰>30%) | 90 | `overfit_param_spike` | 1 次(09-10 21:41) | 真信号(WARN) |
| 7 | schedule_monitor 退出失败(etf_national_team) | last_exit≠0 / pending 非0 | — | 状态派生 | 9 次(8 月底~09-10,多为修复史+今日分支事故) | 真故障(今日已根治) |
| 8 | intraday_snapshot 瞬时超时 | 日志含 TimeoutError | 3 次稳定桶才发(TRANSIENT) | 状态派生 | 6 次(多数已自愈 recovered) | 已自愈抖动 |
| 9 | check_data_gap 数据缺口 | 各检测器(见 state) | 见检测器阈值 | `data_gap:*` | 2 条 warn(09-10,含 kelly_backtest_fail 分支误报) | 真信号+1 误报 |
| 10 | nextday_plan 生成失败 | 退出码≠0 | — | `nextday_plan_fail` | 1 次(09-10 rc=2) | 真故障(已根治) |
| 11 | telegram 通道 | 配置缺失 | — | — | **每条告警都带 telegram=FAIL** | **配置未启用** |
| 12 | 飞书 hook 心跳陈旧 | session 活跃但心跳>90min | 90min | `feishu_hb_stale` | 2 次(09-09/09-10) | 偶发假阳性(#84 C3 已降噪) |
| 13 | 其他(72h 监控/backup/gold_night/费用月报等) | 各自条件 | — | 各自 | 各 0~1 次 | 低频,保留 |

**近 14 天(08-25~09-10)schedule_monitor 侧告警按天**:08-25:3 | 08-26:1 | 08-27:2 | 08-28:7(集中爆发日) | 08-31:3 | 09-04:1 | 09-06:3 | 09-07:5 | 09-08:4 | 09-09:5 | 09-10:3。加 notify 直发(update_all ×9、overfit ×2、deploy ×1、nextday ×1、intraday_upload ×1),近 14 天用户实际收到约 **55 封**告警邮件,其中 update_all 耗时 9 封是绝对大头。

---

## 2. 主噪音源逐项定案(B)

### B1. update_all 耗时阈值 —— 每天必报的根因 ★核心

**现状**:
- `update_all.sh` L282:`[ "$ELAPSED" -gt 3600 ] && SEVERE=1`(2026-07-11 引入,git 041a08e33,**从未重标**)
- L309: ISSUE 串 `耗时超1h(72分钟)` 带分钟数 → L321 dedup key `update_all_severe:${ISSUE}` 含分钟数 → **每天 key 不同,去重失效**
- 对照:schedule_monitor.sh 的 DUR_THRESHOLDS 里 update_all 已重标两次:08-14 30min→70min(4200s),09-09 #82 C6 摘出 turnover 后→135min(8100s)。**update_all.sh 内部 1h 阈值是漏网之鱼**

**近 38 个交易日 update_all 实际耗时分布**(从 update_all_YYYYMMDD_1750.log 起止时间实算):
```
min=735s(12min)  p50=3247s(54min)  p90=9991s(167min)  p95=10500s(175min)  max=13589s(226min)
>3600s: 15/38 次 | >8100s: 6/38 次
```
**关键时间线**:08-14 前 26~60min(阈值够)→ 08-17 起破 1h → 08-31~09-08 常态 124~226min → 09-09 #82 C6 落地(turnover 摘出独立任务 21:10)→ 09-10 回落 **72min(4328s)**。

**为什么 09-10 已经 72min 了还告警?** 因为 72min=4328s 仍 >3600s。C6 摘出 turnover 后主链 = width 采集(31min)+ deploy(35min)+ 串行其余 ≈ 72min,是**新常态**,不是故障。

**建议(核心)**:
- `update_all.sh` L282 阈值 **3600s → 5400s(90min)**:72min 新常态 + 25% 裕量,异常退化(>90min)仍能捕获
- dedup key **去掉分钟数**:固定为 `update_all_severe:耗时超阈值`(同一问题组合当天只 1 封;若希望"严重度上升再发",可把 ISSUE 里的其他触发项保留在 key 里,只剔除分钟数)
- 与 schedule_monitor 的 8100s 保持一致精神:C6 后主链 ~72min,8100s 是更保守的兜底,可不动

**影响面**:改的是告警判定与文案,不影响数据链路/产物;改后 update_all 正常日不再发"严重告警",真退化(>90min)仍报。

---

### B2. deploy R2 上传失败(09-10 18:52)—— 误报,自愈成功仍发

**现状**:deploy_20260910_1822.log 里 upload-lab 通道打印 `TimeoutError: The write operation timed out` → `⚠ upload-lab 失败/超时` → R2_FAIL 置位 → 发"deploy R2上传失败,需手动补刷"。但同日志随后显示:
```
共上传 103/103 -> https://ssd.fx8.store/trade_sim/   ← 103 个文件全部成功
✓ Cache purge 完成: 全部 17 批成功, 共 purged 504/504 keys  ← purge 全成功
=== deploy.sh 结束 2026-09-10 18:57:14 退出码=0 ===  ← deploy 最终 rc=0
```
**结论**:某文件 PUT 连接超时(网络抖动)导致 upload_r2.py 进程异常退出(rc≠0)触发告警,但**实际上传与 purge 全部成功,无需手动补刷**。这是"发送时机过早"的误报——告警在 deploy 中途发出,后续通道自愈成功。

**建议**:deploy.sh 把 R2_FAIL 告警**延迟到 deploy 收尾**:若最终 deploy rc=0 且失败通道文件在后续重跑/清单中已补传成功,则不发或发"已自愈恢复"信息(参考 intraday 的 TRANSIENT 稳定桶思路);upload_r2.py 对单文件 PUT 超时补 try/except 兜住 TimeoutError(现 5 次重试未覆盖异常冒泡路径)。

**影响面**:该告警 30 天 1 次,低频;改后误报消除,真 R2 断供仍会报(其他通道真实失败时 rc≠0 仍发)。

---

### B3. overfit 参数尖峰(09-10 21:41)—— 真信号,保留但理解含义

**现状**:overfit_monitor.py `param_spike`:d3(卖出模式 A↔F↔G 微扰,近 60 日滚动收益率最大敏感度)>30% 或符号翻转 → d3=90 → WARN。09-10 实测 current = {d1:60, d2:20, d3:90, d4:53, risk_score:55(黄)}。近 45 天 d3>=90 仅 09-10 一次;risk>=60(红区)近 45 天 6 次(7/20~7/28 集中)。近 30 天 overfit 类告警共 2 次。

**建议**:**保留**。d3=90 是真实敏感信号(不同卖出模式近 60 日收益方向差异大),WARN 级+24h dedup,频率低不构成噪音。若后续频繁触发,可加"连续 N 天才升 SEVERE"或并入日报,当前不需动。

**影响面**:无改动。

---

### B4. telegram 通道持续 FAIL —— 从未配置,视觉放大器

**现状**:`config/telegram.json` 是占位符(`YOUR_BOT_TOKEN`/`YOUR_CHAT_ID`),notify.py 识别占位符后"跳过发送"并打 stderr。**该通道从未真正启用**,每条告警都统计为 telegram=FAIL,并在 latest.md 里展示。

**建议**:两个方向二选一,推荐 **②**(不动配置):
- ① 补配 telegram(需用户提供 bot_token/chat_id + api_base 反代,国内直连 GFW 不可达)
- ② notify.py 把"未配置(占位符)"从"发送失败(FAIL)"降级为"未配置(跳过)":汇总里不显示 telegram=FAIL,latest.md 通道行只列已启用的 email/feishu

**影响面**:纯展示/统计口径,无数据影响;改后告警观感直接降一档。

---

### B5. 飞书 hook 心跳陈旧(09-09 16:15 / 09-10 01:45)—— 偶发假阳性,已降噪

**现状**:schedule_monitor 维度⑧:session 活跃(90min 内 jsonl 有新增)但 `/tmp/feishu_hook_heartbeat` >90min 陈旧 → SEVERE。09-09 #84 C3 已把"会话活跃"判定从 `pgrep claude` 改为 jsonl mtime(消除深夜/周末假阳性)。09-10 01:45 那次是凌晨 session 判定仍活跃但 hook 未触发(用户只读操作不触发 UserPromptSubmit hook?)。当前心跳文件新鲜(09-10 23:40 mtime),hook 正常。

**建议**:**保留**。近 14 天 2 次、已降噪、hook 正常时不发;若再偶发可在判定里加"心跳陈旧且 hook 进程不存在"双条件,当前不动。

**影响面**:无改动。

---

### B6. 今日分支事故链(nextday_plan rc=2 + etf_national_team exit=1 + kelly_backtest_fail)—— 真故障,已根治

**现状**:根因相同——**主树停在 feat 分支(如 feat/nextday-plan-signal-daily)时,deploy.sh 分支校验拦截所有 deploy**(deploy_20260910_2157.log: `✗ deploy 必须在 main 分支跑(当前分支: feat/...)`),导致 20:07/21:30 etf 任务 deploy 失败、21:57 lab deploy 失败 → 22:26 etf_national_team exit=1 → 22:30 告警 + 22:35 kelly_backtest_fail warn。nextday_plan 20:55 rc=2 根因已由 commit 237154f6a(0e4a5f2b9 nextday_plan 方案A根治)合 main 修复。

**建议**:已切回 main + 已合修复,**观察期确认 1~2 个交易日不再复发即可销案**。防再犯:deploy 被分支校验拦下时,可让告警文案明确写"当前分支=X,需切回 main"(现状已写,好评)。

**影响面**:无改动,已根治。

---

### B7. 其余低频告警(保留清单)

- intraday_snapshot dur>600s(09-10 772s):一次偏慢(正常 286s),600s 阈值对正常值裕量 2 倍,合理,**保留**
- schedule_monitor update_all 8100s:与 B1 互补的兜底,**保留**
- check_data_gap 各检测器(accum_nav/宽度族/交易断档等):均为数据断供级信号,近 30 天低频,**保留**
- 72h 上线后监控(R2迁移后 72h):08-12 一批已过监控期,不再活跃,**可清理**或自然停
- daily_brief 月度费用告警:每月 1 次,**保留**

---

## 3. 统一原则与告警分级(方案主体)

**原则:真故障必报(宁多勿漏),例行噪音降阈值/改条件,误报修根因。** 与 §5.1 数据说话一致,全部基于近 30 天真实触发数据。

建议引入轻量 **三级告警分级**(落到 notify.py 或各调用方):

| 级别 | 含义 | 例子 | 策略 |
|---|---|---|---|
| S0 真故障 | 数据断供/进程挂/deploy 硬失败/产物缺失 | etf 分支被拦、nextday_plan 失败、数据缺口 | 立即邮件+飞书,严重 |
| S1 例行超时 | 任务变慢但未断供 | update_all >90min、intraday >10min | 改阈值到新常态+裕量,或并入"当日任务日报",不逐条吓人 |
| S2 自愈抖动 | 瞬时超时已恢复 | R2 单文件 PUT 超时(实际成功)、intraday TimeoutError 已 recovered | 不发或只在"恢复/日报"里带过;TRANSIENT 稳定桶思路推广 |

**安静期概念**:对 update_all 这类"每天例行慢"的任务,阈值应锚定"当前新常态 + 裕量"而非历史 max;只有当耗时突破常态上沿(如 >90min)才算退化信号。这比"每天看一眼 1h 过了没"更有信息量。

---

## 4. 实施方案汇总(待用户拍板后另派实施)

| # | 改动 | 文件:行 | 类型 | 优先级 |
|---|---|---|---|---|
| 1 | update_all 耗时阈值 3600→5400s | scripts/update_all.sh:282,309 | 阈值 | ★P0 |
| 2 | update_all dedup key 去分钟数 | scripts/update_all.sh:321 | 去重 | ★P0 |
| 3 | telegram 未配置不算 FAIL(或补配置) | scripts/notify.py:400 附近 | 展示口径 | P1 |
| 4 | deploy R2 失败告警延迟到收尾,自愈成功不发 | scripts/deploy.sh:447 | 降噪 | P1 |
| 5 | upload_r2.py 补 TimeoutError try/except | scripts/upload_r2.py:232 附近 | 根因 | P1 |
| 6 | 观察 nextday_plan/etf 分支事故是否复发销案 | — | 观察 | P2 |
| 7 | 72h 监控清理(可选) | scripts/monitor_72h.sh | 清理 | P3 |

**改动面评估**:全部为告警判定/展示逻辑,不碰数据产物与前端;改后自动生效,无需 deploy 数据。实施时注意:改 update_all.sh 属"调度脚本",按 §14 盘后时点别在 17:50~19:00 窗口内 push main。

---

## 5. 诚实标注

- **update_all 耗时分布**基于 update_all_*.log 起止时间(结束行"update_all.sh 结束"完整存在),08-22/08-24 两个日志无结束行(中断),已排除;非交易日(短耗时<600s)已排除。
- 09-09 的 8100s 告警是 schedule_monitor 拿**前一交易日(09-08,175min)**判的,当日 update_all 实际 124min,不影响结论。
- "近 14 天 55 封"是 alert_state(last_alerted>=08-25)+notify_dedup(last_alerted>=08-25)+data_gap state 的**触发次数汇总**,单封邮件可含多条 issue(如 update_all 一条邮件可含"耗时超1h+统一deploy失败"两个 issue),实际邮件数略低于 55,方向不变。
- telegram=FAIL 在每条告警里都出现,是"未配置跳过"而非发送失败,已在 B4 说明。
- 今日 7 封里 2 封是分支事故连锁(已根治)、1 封误报(deploy R2)、1 封例行噪音(update_all 72min>1h)、1 封真实信号(overfit)、1 封一次性偏慢(intraday 772s)、1 封待观察(kelly_backtest_fail 亦分支连锁)。

## 复现

- **脚本路径**:无新脚本,全部数据来自既有产物,复现命令如下。
- **update_all 耗时分布**:
  ```bash
  cd /Users/linhuichen/code/trade-data/data/logs
  python3 - <<'PY'
  import datetime, glob, re, statistics
  rows=[]
  for f in glob.glob('update_all_2026*.log'):
      m=re.search(r'update_all_(\d{8})_(\d{4})\.log',f)
      if not m: continue
      s=datetime.datetime.strptime(m.group(1)+m.group(2),'%Y%m%d%H%M'); end=nt=None
      for line in open(f,errors='ignore'):
          mm=re.search(r'update_all\.sh 结束(（非交易日）)? (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})',line)
          if mm: end=datetime.datetime.strptime(mm.group(2),'%Y-%m-%d %H:%M:%S'); nt=bool(mm.group(1)); break
      if end: rows.append(((end-s).total_seconds(),nt))
  d=sorted([x[0] for x in rows if not x[1] and x[0]>600]); n=len(d)
  print(f"n={n} min={d[0]/60:.0f}min p50={d[n//2]/60:.0f}min p90={d[int(n*0.9)]/60:.0f}min p95={d[min(n-1,int(n*0.95))]/60:.0f}min max={d[-1]/60:.0f}min >3600s={sum(1 for x in d if x>3600)}")
  PY
  ```
- **关键输入依赖**:`data/logs/update_all_2026*.log`(起止时间)、`data/alerts/latest.md`(告警正文)、`data/notify_dedup.json`(dedup key 与触发时间)、`data/alert_state.json`(schedule_monitor 历史)、`data/alerts/data_gap_alert_state.json`(数据缺口)、`static-site/data/schedule_stats.json`(任务耗时)。
- **关键阈值口径**:update_all.sh L282 `ELAPSED>3600`;schedule_monitor.sh L352 `update_all:8100`;DUR_THRESHOLDS 其余见 L345-357;notify.py telegram 占位符判定 L400;overfit ALERT_RULES L1370-1374。
- **数据截止**:2026-09-10 收盘后;数据版本 = 当日 update_all 产出。
- **报告生成**:本文件由 researcher 于 2026-09-10 调研产出,无配套生成脚本(纯查证报告)。

---

## 实施记录(2026-09-11 implementer 续跑落地)

### 改动(commit `a0d919c5f`,feat 分支 `feat/alert-noise-rootfix`,base=origin/main@44936cc54)

| # | 改动 | 文件:行 | 自测 |
|---|---|---|---|
| P0-1 | 耗时阈值 3600→5400s(90min=72min 新常态+25% 裕量),文案 1h→90min | scripts/update_all.sh L282/L309 | bash -n PASS |
| P0-2 | ISSUE 串去掉 `${ELAPSED_MIN}分钟` → dedup key 同日同类型稳定 | scripts/update_all.sh L309-311/dedup key L327 | dedup 稳定性单测 PASS(两耗时同 key/触发项变化异 key) |
| P1-1 | telegram 未配置(占位符)不再标 FAIL:新增 `telegram_configured()`,`_mirror_severe` 通道行只列已启用通道,CLI 汇总 fail 同口径 | scripts/notify.py telegram_configured()(_after L233)/_mirror_severe(L1141-1149)/汇总 2 处 | 渲染验证 PASS(占位符无 telegram 字段;真配置发送失败仍显 telegram=FAIL) |
| P1-2a | deploy.sh R2_FAIL 告警从通道失败立即发→延迟到整个 deploy 收尾(走到收尾=整体退出码走进 exit 0;配合 ② 的 rc 准确化,R2_FAIL 非空=真有文件失败) | scripts/deploy.sh L447-449 删立即块 + 收尾段(L811-823 附近) | bash -n PASS |
| P1-2b | upload_r2.py `cmd_upload_lab` 顺序循环补 try/except(09-10 事故点:单文件 TimeoutError 5 次重试后 raise 无兜底,进程异常退出 rc≠0 → deploy 误报"R2 上传失败"):单文件失败打印跳过继续,末尾 `ok<total` 才 exit 1 | scripts/upload_r2.py cmd_upload_lab | 3 场景单测 PASS(单文件 TimeoutError 兜住/全部成功 rc=0/非200 失败 exit 1) |

### 自验同类错误面清单(§23.2)

- **同模式(顺序循环直接 s3_request PUT 无 try)**:grep 全量 `s3_request("PUT")` 调用点了 9 处,deploy 链唯一无兜底顺序循环 = cmd_upload_lab(事故点,本次修);cmd_upload_data_large 已有 try/except(不异常中断,维持现状);purge 的 weekly/monthly 与 backup 系列为定时/手动命令非 deploy 链(不动)。
- **同 dedup key 构造**:grep 全 scripts 下 notify `--dedup-key` 调用,update_all 是唯一 ISSUE 带动态分钟数的(本次修);deploy/schedule_monitor 等 key 均为静态前缀(无此病灶)。
- **同 telegram 展示位**:`_mirror_severe` 通道行 + send/agent-done 两处 CLI 汇总 fail 列表(3 处全部对齐,未配置=跳过非失败,已配置仍可显示 FAIL);配置生效后自动恢复显示,无永久降级。

### 上线后预期

- update_all 正常日(≤90min)不再发"严重告警"新封(仍每天发 1 封例行"完成"邮件);
- 同一天同类型 update_all 严重告警 30min 窗口去重真正生效(需严重度升级才新发);
- 告警邮件通道行不再每封带 `telegram=FAIL` 观感降一档;
- deploy R2 瞬时单文件超时不误报"整体上传失败"(自愈成功不报,真失败收尾仍报)。
