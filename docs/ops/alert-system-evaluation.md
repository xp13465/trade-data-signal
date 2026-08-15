# 运维告警体系评估报告(2026-08-02 ~ 08-15)

> 只读调研产物,不动生产。评估「哪些告警该调机制(阈值/去重/严重级/抑制),哪些该根治内容(任务真退化/慢/挂)」。
> 事实源 = `schedule_monitor_launchd.log`(每 15min 轮询,含全量检测块),不依赖飞书抄送。

## 一、概览

- 统计窗口:2026-08-02 00:00 ~ 2026-08-15 22:00
- 监控轮询:每 15min 一轮,共 **1376 轮**,检测事件 **3193 个**
- 其中 **SEVERE 告警 49 条**(= 实际触发告警的首次发现;`[suppress]` 去重抑制事件 1000+,说明去重机制在正常工作,真正发出去的邮件远少于检测数)
- 恢复事件 55 个(告警自动恢复后发了恢复通知)

**一句话结论**:49 条里,约 **21 条是纯机制误报/噪音**(8/10-14 耗时告警 12 条 + pending但上次exit非0 5 条 + TimeoutError 单次失败 4 条里的大部分),约 **12 条是真实事件但已根治**(8/12 deploy 全站失败、_now/_ETF_POSITION_SIZE NameError、etf_nt mootdx 不可达漏跑、overview 15:30 时效),真正**还需要动作的**是 5 类:①pending_crash_retry 误报机制 ②intraday 盘后槽阈值过紧 ③R2 间歇抖动是否降噪 ④push 失败跨槽恢复判定 ⑤已验证项观察。

---

## 二、全量 SEVERE 告警清单(49 条,按类别分组)

### 类别 1:执行耗时超阈值(12 条,全部 8/10-8/14,全部误报)

| 时间 | 任务 | 耗时 | 阈值(当时) | 实际是否正常 |
|---|---|---|---|---|
| 08-10 18:45 | update_all | 3242s | 1800s | 正常完成 exit=0 |
| 08-10 22:15 | backfill_evening | 3707s | 1800s | 正常完成 exit=0 |
| 08-11 17:15 | backfill_evening | 1961s | 1800s | 正常完成 exit=0 |
| 08-11 19:00 | update_all | 3556s | 1800s | 正常完成 exit=0 |
| 08-11 21:45 | backfill_evening | 1892s | 1800s | 正常完成 exit=0 |
| 08-12 21:00 | intraday_snapshot | 661s | 600s | 正常(仅超 61s) |
| 08-13 18:45 | update_all | 3191s | 1800s | 正常完成 exit=0(18:43 结束) |
| 08-13 21:30 | intraday_snapshot | 2493s | 600s | 慢在 dump+R2 上传段 |
| 08-13 21:45 | backfill_evening | 1917s | 1800s | 正常完成 exit=0 |
| 08-14 02:45 | backfill_evening | 2573s | 1800s | 正常完成 exit=0 |
| 08-14 17:30 | backfill_evening | 2776s | 1800s | 正常完成 exit=0 |
| 08-14 19:00 | update_all | 3609s | 1800s | 正常完成 exit=0 |

### 类别 2:退出失败 exit=1(8 条)

| 时间 | 任务 | 判定 |
|---|---|---|
| 08-04 21:45 | etf_national_team | 真事件:push non-ff 失败,deploy=1 |
| 08-05 00:00 | etf_national_team | 同上条重复(跨槽恢复前再报) |
| 08-12 19:30 | lhb_backfill | 真事件:8/12 全站 deploy 失败(etf_since_return 校验拦截) |
| 08-12 21:00 | futures_backfill | 真事件:8/12 deploy.sh NON_DATA_UNMERGED 变量 bug |
| 08-13 18:00 | update_all | **误报**:任务实际 18:43 正常结束 exit=0 |
| 08-13 18:30 | lhb_backfill | **误报**:任务实际 18:48 正常结束 exit=0 |
| 08-13 20:15 | futures_backfill | **误报**:任务实际 exit=0 |
| 08-15 05:15 | us_stock_morning | 真 bug:_now NameError(#90 同源,已修) |

### 类别 3:log异常关键词(20 条)

- **push 失败 7 条**:08-04 backfill/futures、08-05 backfill/futures、08-07 backfill、08-08 backfill/update_all、08-10 lab_auto —— 全是 `error: failed to push some refs`(github non-ff 竞争),但任务本身 exit=0 已自愈
- **TimeoutError 4 条**:08-04/08-05/08-11 intraday、08-12 lab_auto —— R2 PUT `attempt 1 失败(TimeoutError)` 重试成功,exit=0
- **Traceback 3 条**:08-06 backfill(`_ETF_POSITION_SIZE` NameError,已修)、08-12 intraday(mootdx 全不可达 RuntimeError,真环境故障)、08-15 backfill(_now NameError,已修)
- **pending但上次exit非0 5 条**:08-12 lhb+futures、08-13 update_all+lhb+futures —— 全是误报机制(详见 bug 节)
- 其他 1 条:08-12 intraday 20:35 Traceback(与上 mootdx 同段)

### 类别 4:R2 直连不可达(5 条)

- 08-09 四段独立事件:13:45 / 14:15 / 15:00 / 22:00,`curl rc=28`(超时)
- 08-12 一段:19:30,`curl rc=6`(TCP 连不上,DNS 解析 OK)
- 判定:间歇性网络抖动/故障,非持续不可达(每段持续 2-3 周期后恢复)

### 类别 5:产物时效滞后(3 条)

- 08-03 / 08-04 / 08-05 15:30,overview.json 3 域名全 lag=27-28min(threshold<20min)
- **已根治**:08-05 16:46 commit `1fd547327` 窗口上限 1530→1505,08-06 起不再复发

### 类别 6:漏跑(1 条)

- 08-12 21:45,etf_national_team 计划 21:30 漏跑,last_run=20:07:16
- 根因:08-12 20:07 段 mootdx 服务器全不可达(RuntimeError: TCP 7709 全超时),`[etf_nt] daily 超时(600s)强制 os._exit(2) 释放锁`,21:30 未启动

---

## 三、分类统计

### 按类型

| 类型 | 条数 | 占比 | 判定 |
|---|---|---|---|
| log异常关键词 | 20 | 41% | 混合:真事件 8 条 + 误报/噪音 12 条 |
| 执行耗时超阈值 | 12 | 24% | **全部误报**(阈值已重标,8/15 起不复发) |
| 退出失败 | 8 | 16% | 混合:真事件 5 条 + 误报 3 条 |
| R2不可达 | 5 | 10% | 真事件(间歇性) |
| 产物时效滞后 | 3 | 6% | 已根治(历史) |
| 漏跑 | 1 | 2% | 真事件(环境故障) |

### 按任务

| 任务 | 条数 | 主要问题 |
|---|---|---|
| backfill_evening | 12 | 耗时误报 6 + push 失败 3 + Traceback 2 + pending 误报 1 |
| update_all | 7 | 耗时误报 4 + exit=1 误报 1 + push 失败 1 + pending 误报 1 |
| intraday_snapshot | 6 | TimeoutError 3 + 耗时 2(1 真 1 边缘)+ mootdx Traceback 1 |
| futures_backfill | 6 | push 失败 2 + pending 误报 2 + exit=1 真 1 + 误报 1 |
| R2 | 5 | 间歇不可达 |
| lhb_backfill | 4 | exit=1 + pending 误报 |
| overview | 3 | 时效滞后(已根治) |
| etf_national_team | 3 | 漏跑 1 + exit=1 2(push 失败) |
| lab_auto | 2 | push 失败 1 + TimeoutError 1 |
| us_stock_morning | 1 | _now NameError 真 bug(已修) |

### suppress(去重抑制)按任务

update_all 373 / backfill_evening 208 / intraday 146 / lab_auto 103 / futures_backfill 90 / etf_national_team 88 / us_stock_morning 67 / R2 6 / lhb 2

→ **去重机制工作正常**:49 条 SEVERE 背后有 1000+ 次 suppress,告警不会刷屏。

---

## 四、逐类判定:调机制 vs 根治(带证据链)

### 1. 执行耗时超阈值 → 该调机制,且 8/14 已重标,建议验证不返工

- **判定**:12 条全部是旧阈值 1800s 误报。任务实际都正常完成(exit=0),update_all 真实耗时 3100-3600s,backfill 真实耗时 1900-3700s,远超旧阈值 1800s 但远未到"退化/卡死"程度。
- **证据**:
  - schedule_monitor.sh 阈值 8/14 19:16 commit `416785bc4` 才重标:update_all 1800→**4200s**、backfill 1800→**4500s**(schedule_monitor.sh L288-293)
  - 8/13 update_all 实际 18:43 正常结束 exit=0(update_all_launchd.log L3436-3531),但 18:00 被误报 exit=1 + 18:45 报 3191s 超阈值
  - 8/14 19:16 重标后,8/15 起 update_all/backfill 均无耗时告警(8/15 backfill 21:00 槽 1831s < 4500s,正常)
- **剩余问题**:intraday 600s 阈值对盘后 20:35 槽过紧。8/12 661s(仅超 61s)、8/13 2493s,快照本身 78.9s 正常,26min 空档在"静态 JSON dump + sentiment R2 上传"段(20:38-21:03,intraday_snapshot_launchd.log L130405-130704)。600s 是按盘中 09:35-15:35 设计的,盘后槽混入了 dump+R2 上传。
- **建议**:update_all/backfill 已验证,不动;intraday 按槽位差异化或盘后槽单独放宽(见建议 P0-2)。

### 2. 退出失败 → 混合:3 条误报机制 + 5 条真事件

- **真事件 5 条**:
  - 8/12 全站 deploy 失败:lhb/futures exit=1,根因 = deploy.sh 数据产物校验拦截(etf_since_return 非 null 占比 85.4% < 90%,pipeline_core_20260812_1750.log)+ futures deploy.sh L88 `NON_DATA_UNMERGED` unbound variable(8/12 futures_backfill_launchd.log L6386-6400)。校验拦截是**保护机制正常工作**(防坏数据上线),NON_DATA_UNMERGED 是真实脚本 bug(已修,当前 deploy.sh L74 有初始化)。
  - 8/4 etf_nt exit=1:push non-ff 失败 deploy=1(etf_national_team_launchd.log L4893-5217)
  - 8/15 us_stock exit=1:_now NameError(#90 同源,当天已修)
- **误报 3 条(8/13)**:
  - 根因 = gen_schedule_stats.py 的 `pending_crash_retry` 逻辑(L399-412):任务在跑(pending_start)+ launchctl 读到上次(8/12)exit=1 → 标 `log异常关键词<pending但上次exit非0>`。
  - 8/12 deploy 失败残留的 exit=1 退出码,污染了 8/13 当天所有在跑任务的判断。任务 8/13 实际都正常(update_all 18:43 exit=0、lhb 18:48 exit=0)。
  - 而且**同一失败报两条**:exit=1 和 pending但上次exit非0 同时报(8/13 18:00 update_all 两行、8/12 19:30 lhb 两行、8/12 21:00 futures 两行都在同块)。

### 3. log异常关键词 → 混合:真 bug 已修,剩 4 类噪音

- **push 失败 7 条**:真实但自动恢复。deploy.sh 已内置 rebase 重试(scripts/deploy.sh L141-160),失败后 push 成功会带成功标记(PUSH_SUCCESS_RE),跨槽场景(8/4 21:00 失败,8/5 00:00 才恢复)覆盖不到。属于"部署时间撞 github non-ff 竞争",低频真实,可保留但建议区分"最终失败 vs 已恢复"。
- **TimeoutError 4 条**:R2 PUT `attempt 1 失败` 是单次重试失败被 try/except 吞,重试最终成功(exit=0)。属于纯噪音——**单次 attempt 失败不该 SEVERE**。
- **Traceback 3 条**:
  - 8/6 backfill `_ETF_POSITION_SIZE NameError`(export.py:1058 → queries.py:504):**真 bug,已修**(当前 queries.py 无该引用)。同类:删 def 忘删调用(与 #90 同源模式)。
  - 8/12 intraday mootdx 全不可达(intraday_snapshot_launchd.log L120325-120359):真环境故障(海外网络 TCP 7709 全超时)。
  - 8/15 backfill `_now NameError`:真 bug,已修。
- **pending但上次exit非0 5 条**:全部误报机制,见 bug 节。

### 4. R2 直连不可达 → 该调机制(降噪)

- **判定**:5 条都是间歇性网络抖动(rc=28 超时 4 次 + rc=6 连接失败 1 次),非持续不可达。self_heal 分级(N=2 连续 30min 才通知)逻辑正确,每段独立事件各发 1 封邮件合理。
- **可优化**:rc=28(超时)语义是"慢",rc=6(连接失败)语义是"断",两者严重级可区分;curl 超时时间可加长(8/9 的 rc=28 可能是 curl 默认超时过短导致)。
- **证据**:schedule_monitor_launchd.log L4186-4219(8/12 19:30 rc=6,持续 6 周期 19:30-20:45 后恢复)。

### 5. 产物时效滞后 → 已根治,历史遗留

- 8/3-5 三天 15:30 报 overview lag=28min,8/5 16:46 commit `1fd547327` 窗口上限 1530→1505 后,8/6 起未再复发。
- **无需动作**,记录为历史已修项。

### 6. 漏跑 → 真事件,环境故障,非机制问题

- 8/12 etf_nt 21:30 漏跑,mootdx 全不可达导致 20:07 槽超时强杀,21:30 槽无法启动。
- 这是海外网络到国内 TDX 服务器的连通性故障,监控正确报出,数据已由后续槽位兜底。

---

## 五、建议清单(改哪 / 改成什么 / 为什么 / 优先级)

### P0(机制层,消误报,本周可做)

**P0-1 修 pending_crash_retry 误报**(改 `gen_schedule_stats.py` L399-412)
- 改成什么:判定"pending 但上次 exit 非 0"时,限制 `上次退出时间` 与 `本次 pending 开始时间` 间隔(如 < 6h 才算关联),避免读到 8/12 这类历史残留退出码;或改为"本次运行结束后再看真实退出码"。
- 为什么:8/13 三条 exit=1 + 五条 pending 误报全是它引起,还导致同一失败报两条。这是 49 条里最大的单点误报源。
- 验收:重跑 gen_schedule_stats.py,8/13 类场景不再出 pending 误报。

**P0-2 intraday 盘后槽阈值差异化**(改 `schedule_monitor.sh` DUR_THRESHOLDS L288-293)
- 改成什么:intraday 按槽位分阈值,盘后 20:35 槽(含 dump+R2 上传)给 1800s;或对 20:35 槽跳过耗时检查只做时效检查。
- 为什么:8/13 2493s 是真慢但**非退化**——快照 78.9s 正常,慢在静态 JSON dump + R2 上传段(20:38-21:03),这是盘后槽的固有工作内容,600s 盘中阈值不适用。
- 验收:8/12 661s、8/13 2493s 类不再触发;盘中 09:35-15:35 槽仍 600s 严格。

### P1(噪音降低,近期可做)

**P1-1 R2 PUT 单次 attempt 失败不报 SEVERE**
- 改成什么:log 异常关键词匹配里,`attempt 1 失败(TimeoutError)` 若同一文件最终重试成功(exit=0),降为 warning 或进 suppress 白名单。
- 为什么:4 条 TimeoutError 全是重试成功的噪音,`attempt 1 失败` 是重试机制的正常过程。

**P1-2 R2 不可达区分 rc=28 vs rc=6 + 加长 curl 超时**
- 改成什么:rc=28(超时)单列降级或加长 curl 超时(如 20s→40s),rc=6(连接拒绝)保持 SEVERE。
- 为什么:8/9 四次 rc=28 是间歇抖动(每段 2-3 周期自愈),语义"慢"不是"断",值得与 rc=6 区分。

### P2(信息增强,低频)

**P2-1 push 失败跨槽恢复判定补强**
- 改成什么:push 失败后,若同一 deploy 窗口内后续 push 成功(带 PUSH_SUCCESS 标记),跨槽场景也标恢复,不跨槽重复报。
- 为什么:8/4 → 8/5 跨槽重复报 etf_nt exit=1 两次。

### P3(验证已修项,观察 1-2 周)

**P3-1 验证 8/14 阈值重标后 update_all/backfill 耗时不再复发**(8/15-8/22 观察,目前 8/15 已无复发)
**P3-2 验证 _now/_ETF_POSITION_SIZE 类删def忘删调用不再复发**(同 #90 模式,见 bug 节)

---

## 六、发现的 bug(待用户确认,含完整证明链路)

### Bug 1:gen_schedule_stats.py pending_crash_retry 误报(机制缺陷)
- 现象:8/13 全天 3 个任务被误报 exit=1 + 5 条 pending 误报,任务实际都正常
- 根因:任务在跑(pending_start 非空)+ launchctl_last_exit 读到的是**上次历史退出码**(8/12 deploy 失败残留=1)→ 标"pending但上次exit非0";且同一失败会 exit=1 与 pending 双条同报
- 证据:schedule_monitor_launchd.log L4184-4185(8/12 19:30 lhb 双条)、8/13 18:00 update_all 双条;gen_schedule_stats.py L399-412;update_all_launchd.log L3436(8/13 实际 18:43 exit=0)
- 影响:误报刷屏 + 掩盖真实告警(狼来了效应)
- 建议:限制"上次退出时间"与"本次开始时间"间隔,或本次结束后再判;修后重跑验证
- **待用户确认是否修**

### Bug 2:_now NameError 复发(#90 同源,删 def 忘删调用)
- 现象:8/15 us_stock_morning exit=1(us10y 采集)+ backfill_evening Traceback + intraday daily_metric 写入失败(不阻断)
- 根因:`NameError: name '_now' is not defined`——删函数定义时漏删调用(与 #90 采集异常同模式)
- 证据:us_stock_morning_launchd.log L3174-3197、backfill_evening_launchd.log L25273-25322、intraday_snapshot_launchd.log L139780-139786
- 影响:us10y 当日数据缺失(已兜底),backfill 16:35 槽 17:00 告警 21:45 恢复
- 修复状态:8/15 白天已修;8/15 21:00 槽 backfill 正常(21:00:05 启动无 Traceback),latest.md 21:45 确认恢复
- **待用户确认**:是否需要加"删 def 必查调用方"的机器检查(grep 防重犯,参考 memory refactor-delete-keep-callers-synced)

### Bug 3:_ETF_POSITION_SIZE NameError(8/6,历史已修)
- 现象:8/6 backfill deploy 阶段 export.py 失败,backfill 退出码仍 0(补采完成但 deploy 失败)
- 根因:`queries.py:504 export_overview` 引用 `_ETF_POSITION_SIZE` 未定义(export.py L1058 入口)
- 证据:backfill_evening_launchd.log L13345-13352(Traceback + `✗ export.py 失败(退出码 1),终止部署`)
- 修复状态:已修(当前 queries.py 无该引用)
- **待用户确认**:与 Bug 2 同源模式(删 def 忘删调用),是否一并加机器检查

### Bug 4:8/12 deploy.sh NON_DATA_UNMERGED unbound variable(历史已修)
- 现象:8/12 futures_backfill exit=1
- 根因:`deploy.sh` L88 引用 `$NON_DATA_UNMERGED` 未初始化(unbound variable),bash 报错退出
- 证据:futures_backfill_launchd.log L6386-6400
- 修复状态:已修(当前 deploy.sh L74 `NON_DATA_UNMERGED=""` 已初始化)
- **待用户确认**:无需动作,仅记录

---

## 七、复现

- 脚本:`docs/ops/scripts/parse_monitor_alerts.py`(死脚本,一次性分析,与报告同目录咬合)
- 输入依赖:`/Users/linhuichen/code/trade-data/data/logs/schedule_monitor_launchd.log`(主监控权威日志,5270+ 行)
- 重跑命令:
  ```bash
  python3 docs/ops/scripts/parse_monitor_alerts.py --since 2026-08-02
  ```
- 数据截止:2026-08-15 22:00(日志尾部可见 8/15 21:45 backfill 恢复)
- 关键口径一句话:监控脚本每 15min 轮询,`检测到 N 个告警:` 块 = 本次轮询的首次发现(active 态会被 suppress),`[suppress]` = 去重抑制,`[recovery]` = 恢复事件;SEVERE 行数 = 实际触发邮件数
