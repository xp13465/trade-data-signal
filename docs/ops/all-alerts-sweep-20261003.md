# 全量告警穷举排查报告(2026-10-03)

> 任务:用户指令「查一下所有告警邮件,别漏了,是有真问题还是什么」。
> 方法:四通道穷举(L46 事件驱动 + 多通道),只读不改。通道1 本机 alerts 文件;通道2 云上 alerts + 全部日志 grep「邮件已发送至」;通道3 GitHub CI + 本地复现;通道4 其它出口(warning/feishu)。
> 覆盖时窗:2026-09-06(本机 latest.md 流水起点)~ 2026-10-03(今日)。

## 0. 通道覆盖声明

| 通道 | 覆盖物 | 结果 |
|---|---|---|
| 1 本机 | data/alerts/latest.md(378行,覆盖区+26条severe流水)/alert_state.json(2 active)/notify_dedup.json(27 key)/alerts/data_gap_alert_state.json | 本机为纯开发机(最后一次告警活动 09-30 14:07),流水比云上旧,仅作对照 |
| 2 云上 | data/alerts/latest.md(368行,覆盖区+50条severe流水)/info_log.jsonl(68行全量)/warning_dedup_state.json/alert_state.json(151 key,未恢复9条)/data_gap_alert_state.json + data/logs/ 2298文件 grep「邮件已发送至」抽 20+ 文件(无 `*2026100*` 通配,全目录扫) | 云上是权威源,覆盖到 10-03 17:00 |
| 3 GitHub CI | api.github repos/xp13465/trade-data-signal workflow 349474535 全 run 翻页 + 逐 run jobs + 本地复现 pytest | 见 §2 |
| 4 其它 | warning_buffer.jsonl(0B)/warning_dedup_state(排队超时 09-30 5次)/feishu 发送记录(schedule_monitor 日志) | 并入清单表 |

## 1. 全告警清单表

定性取值:`真问题(待修)` / `真问题(已自愈)` / `设计如此(非问题)` / `长期失效(门禁空转)` / `待观察`

| 时间 | 标题 | 级别 | 通道 | 定性 | 证据 | 是否需修 |
|---|---|---|---|---|---|---|
| 09-06~09-09 | backfill_evening 超时/退出失败/耗时超阈值(6+条) | severe | 云上流水 | 真问题(已自愈) | 09-13 后无复发;恢复邮件 09-29 02:45/09-30 02:45(backfill_evening dur>4500s) | 否 |
| 09-07 | deploy R2 上传失败(upload-* 多桶) | severe | 云上流水 | 真问题(已自愈) | 单日事件,后续 deploy 正常 | 否 |
| 09-07~09-13 | 飞书 hook 心跳陈旧(7 条) | severe | 云上流水 | 设计如此(非问题) | hook 静默停机预警、后续未再触发=本机会话活跃问题,云上无关;09-13 后无复发 | 否 |
| 09-07~09-11 | update_all 超时/耗时超阈值(6 条,171/175/124/144min)+统一deploy失败 | severe | 云上流水 | 真问题(已自愈) | 17:50 起跑慢于阈值,但 overview.date 均 OK;09-12 后无复发 | 否 |
| 09-08 | 过拟合监控 61 分红区 | severe | 云上流水 | 设计如此(非问题) | 监控设计触发(综合分>=60);D1=90 提示回测-实盘偏离,属监控输出非故障 | 否(下一条同类监控输出已在 09-28 复现,见下) |
| 09-09 | com.trade.turnover-backfill 未加载 / baostock 10001011 | severe | 云上流水 | 真问题(已自愈) | turnover 当日缺失,baostock 封禁熔断(记忆 L46 事件),后续恢复 | 否 |
| 09-10 | intraday_snapshot 耗时 772s 超阈值 | severe | 云上流水 | 真问题(已自愈) | 单日退化,后续正常 | 否 |
| 09-10 | nextday_plan 退出码 2 | severe | 云上流水 | 真问题(已自愈) | 09-10 20:55;产物 09-30 正常生成(见 09-30 行) | 否 |
| 09-11 | 数据缺口:交易记录停在 20260909(T-1 应 20260910) | severe | 云上流水 | 真问题(已自愈) | 9/7 断档同形态;09-28 再犯最终于 09-30 降级 warn(见 09-28 行) | 否(已复查) |
| 09-13 | backfill_evening 耗时 5870s | severe | 云上流水 | 真问题(已自愈) | 恢复邮件 09-29/09-30 均已到 | 否 |
| 09-16 04:20 | nextday_plan OperationalError(unable to open db) | severe | 本机覆盖区(email=FAIL feishu=FAIL) | 真问题(已自愈) | 本机开发环境 DB 锁问题,线上未见同类(云上 nextday_plan 09-30 正常跑,10-01/02 非交易日跳过) | 否 |
| 09-18 10:54 | [kelly] 冻结表缺失历史信号事件 622 个 | severe | 本机+云上 | 设计如此(非问题)+已根治 | 详见 §4:09-18 根治落地当天首次触发告警,notify_dedup 停 09-18,云上 09-19~09-30 全部交易日回测均无复发 | 否(已根治) |
| 09-25/26/29/10-01 | staticdata 变更量超阈值跳过 commit(文件 4066~4071 / 字节 1.19~1.21GB >500MB) | severe | 云上流水+info_log(59条) | 设计如此(非问题)→待观察 | 大 JSON backlog(增量 4000+ 文件/日),已设计「仅磁盘留档+次日 deploy rsync 追平」;memory staticdata-old-mirror-keep-decision(8.3G 旧镜像保留至 10-30,勿删);migrate_large_json_out_of_git.sh 已有,未跑 | 待观察(国庆后评估迁移) |
| 09-25 23:00 | fetch_news R2/staticdata 同步超时(timeout) | severe | 云上流水 | 真问题(已自愈) | alert_state fetch_news\|✗[fetch_news] R2\|12115df4 = recovered(09-25 23:00) | 否 |
| 09-27 05:45/06:15 | us_stock_morning 超时/耗时 4076s | severe | 云上流水 | 真问题(已自愈) | 恢复邮件 10-01 05:30(us_stock_morning dur>1800s) | 否 |
| 09-27/28/29/10-01/10-03 | R2 上传锁连续 3 轮跳过(SKIPPED_LOCKED, fetch_news/intraday_snapshot) | severe | 云上流水 | 真问题(已自愈,反复) | 恢复邮件:09-29 12:15(intraday)、10-01 18:45、10-03 00:45(fetch_news);root=R2 上传慢/超时占锁,网络抖动时段,自动恢复 | 否(网络层观察) |
| 09-27 16:35/21:00 | backfill_evening 超时(100min/90min) + 耗时 8829/9355s | severe | 云上流水 | 真问题(已自愈) | 恢复邮件 09-29/09-30 02:45 均已到 | 否 |
| 09-28 13:45~16:00 | R2 intraday lag 19min + intraday_snapshot 漏跑/耗时 907s | severe | 云上流水 | 真问题(已自愈) | 恢复邮件 09-29 12:15(intraday r2_skip)后正常 | 否 |
| 09-28 19:03 | staticdata 变更量 872MB 超阈值 | severe | 云上流水 | 设计如此(非问题) | 同 staticdata backlog 行;文件 510 未超 5000,字节超 500MB | 否(观察) |
| 09-28 19:45 | lhb_backfill 漏跑 | severe | 云上流水 | 真问题(已自愈) | 恢复未见复发,龙虎榜次日正常 | 否 |
| 09-28 20:45 | gen_daily_brief R2_UPLOAD_TIMEOUT | severe | 云上流水 | 真问题(已自愈) | alert_state recovered(09-28 20:45),R2 网络抖动时段链式事件之一 | 否 |
| 09-28 21:00 | intraday_snapshot/s06_snapshot 超时未完成(25min) | severe | 云上流水 | 真问题(已自愈) | s06 当日 exit=143(后续 09-29/09-30 机检六项 PASS);同 R2 网络时段 | 否 |
| 09-28 21:05 | 排队超时跳过 /tmp/trade_deploy.lock(排队 3600s) | severe | 云上流水+通道4 | 真问题(已自愈,已知根因) | 09-30 20:23~23:14 再犯 5 次(warning_dedup_state 记录 notified 2 次);memory trade_deploy.lock 队列结构性积压(#149 已登记) | 否(已登记#149) |
| 09-28 21:40 | 过拟合监控 60 分红区 | severe | 云上流水 | 设计如此(非问题) | 同 09-08,监控正常输出,D1=60 | 否 |
| 09-28 22:35 | 数据缺口:交易记录断档(1 入样信号无交易,深度 3 日,最新 20260922) | severe | 云上流水 | 真问题(已自愈) | 09-30 22:35 降级 warn(深度 1),10-03 16:47 产物已补 20260929(见 §3);09-30 signal_date 无 trade,待 10-08 下一交易日复查 | 待观察(节后复查) |
| 09-29 02:34 | staticdata 备份失败(0:53/05:36/08:49 三次) | severe | 云上流水 | 真问题(已自愈) | 日志=upload_r2.py upload-large-json 失败「不阻塞」,R2 网络抖动时段;磁盘留档已完成 | 否 |
| 09-29 09:15/22:00/09-30 21:45 | fetch_news 停摆(超4h 未运行) | severe | 云上流水 | 真问题(已自愈) | 09-29 05:01~09:15、17:45~22:00 空档后自动恢复;timer 现状正常(17:01 轮) | 否 |
| 09-29 10:00/13:15 | 线上 overview 时效滞后 445min/640min(主站+R2) | severe | 云上流水 | 真问题(已自愈) | 同 09-28~29 R2 网络时段链;09-30 后 overview 时效恢复(10-03 16:40 全绿) | 否 |
| 09-30 05:45/06:00 | us_stock_morning 超时/耗时 2968s | severe | 云上流水 | 真问题(已自愈) | 恢复邮件 10-01 05:30 | 否 |
| 09-30 09:40 | 凯利盘中增量回测失败(退出码 5) | severe | 云上流水 | 真问题(已自愈) | 09-30 单次;恢复邮件未见复发(10-01/02/03 均非交易日跳过) | 否 |
| 09-30 14:30 | overview 滞后 24min(主站+R2) | severe | 云上流水 | 真问题(已自愈) | R2 网络时段;后续正常 | 否 |
| 09-30 21:00~21:15 | intraday_snapshot/s06 超时 + 耗时 2081s | severe | 云上流水 | 真问题(已自愈) | 恢复邮件 09-30 21:15(intraday in_progress_timeout) | 否 |
| 09-30 22:35/22:45 | nextday_plan 退出码 1(失败) | severe | 云上流水 | 真问题(已自愈,根因=R2 上传超时) | 日志证据:「R2 上传超时(300s, 将告警)」+「产物落盘完成」(nextday_plan.json/auto_trade_steps.json/signal_kelly_day_snapshot.json 均已写),rc=1 系 R2 超时致;10-01/02 非交易日跳过 | 否 |
| 09-30 23:00 | R2 直连不可达 ssd.fx8.store(curl rc=28) | severe | 云上流水 | 真问题(已自愈) | alert_state:recovered(10-03 05:45);10-03 05:30 再发(rc=28)也 recovered | 否(网络观察) |
| 10-03 00:30/00:45 | fetch_news R2 锁 3 轮跳过 → 恢复 | severe | 云上流水(覆盖区) | 真问题(已自愈) | 覆盖区=00:45 恢复通知;alert_state fetch_news\|r2_skip_alert recovered(10-03 00:45 last_recovered) | 否 |
| 09-30 14:07 | 防再犯E守卫:写部署源树目标错误(SystemExit 阻断) | severe | 本机流水末条 | 真问题(已自愈/一次性拦截) | 本机 dev 侧识别的部署源树目标误指误拦截,属守卫正常拦截日志(仅本机) | 否 |
| — | GitHub CI Quality Gate ⑧ pytest 恒失败(自 10-01 15:30 UTC 起) | gating | 通道3 | **长期失效(门禁空转)** | 见 §2:test_notify_r4_dedup_20261001.py 引入后 collection 必崩,40+ run 全红,门禁形同虚设 | **是(建议马上修)** |

## 2. CI ⑧ pytest 失败根因专节

### 2.1 现象
- workflow「CI Quality Gate」最后 success = run #394(2026-09-30 17:29Z);#407(10-01 14:04Z)为 workflow 层最后绿;自 #414(2026-10-01 15:30Z)起 quality-gate-static 恒 failure,**失败步骤恒为⑧「算法核心 pytest(P0-1, FAIL 阻断)」**;quality-gate-data 恒 success。
- 实测 run #470/#469/#461/#459/#450/#421/#414 逐 run jobs 确认:均为步骤 10 ⑧ FAIL。

### 2.2 本地复现(唯一允许的写操作:venv 装 pytest)
```
/Users/linhuichen/code/trade-data/.venv/bin/python -m pytest -q scripts/tests/
→ INTERNALERROR(collection 阶段崩溃), no tests ran
```
- 单跑坏文件:`python -m pytest scripts/tests/test_notify_r4_dedup_20261001.py`
  → `ModuleNotFoundError: No module named 'notify'`(硬编码 `/Users/linhuichen/code/trade/.claude/worktrees/agent-a45df7aac3ee7ea07` 路径在 CI 不存在)
- 批量跑(本地有 sys.path 副作用时)走到该文件模块顶层 `sys.exit(0)` → `SystemExit` → INTERNALERROR。两种错误殊途同归:collection 必崩,退出码≠0 → ⑧ FAIL。

### 2.3 根因
文件 `scripts/tests/test_notify_r4_dedup_20261001.py`(commit **5a6439c2d**,2026-10-01 22:13 +0800「fix(notify)+docs(ops): #123 R4块update_dedup无条件落盘修复」引入)是**脚本式自测**(模块顶层直接跑逻辑 + `sys.exit(0 if all_pass else 1)` 结尾,第 121 行),不是 pytest test 函数文件:
- 顶层 `sys.path.insert(0, str(WT / "scripts"))` 指向**他人 worktree 的硬编码本机绝对路径**,CI runner 不存在;
- 顶层执行 `import notify` → CI 上报 ModuleNotFoundError,本地无该 worktree 时同错;
- 即使 import 成功,顶层 `sys.exit()` 也会被 pytest 当 INTERNALERROR。
- 同批 4 个「no tests collected」文件(test_132_*×3、test_alert_denoise_20261001.py)同为脚本式自测,exit 0 不阻塞门禁,但语义上是测试盲区(同一反模式)。

### 2.4 影响面(门禁失效多久)
- 引入 commit 5a6439c2d 上墙时间 = 2026-10-01 22:13 +0800(14:13Z);第一个完整红 run = #414(10-01 15:30Z,北京时间 23:30)。
- **门禁空转 ≈ 2 天(10-01 23:30 北京 → 今日)**,期间 40+ run 全红/取消,#408~#470 之间 main 仍在正常合入(大量 merge commit) → **FAIL 阻断没有任何人看,门禁形同虚设**。
- 不影响线上:quality-gate-data(continue-on-error)恒绿,deploy 链不含此 workflow;线上数据链路 10-03 17:00 仍在正常更新。

### 2.5 修复建议(供实施)
1. `scripts/tests/test_notify_r4_dedup_20261001.py` 改为 pytest 风格:去掉顶层 `import notify` + `sys.exit()`,把 6 个场景拆为 `def test_xxx()` 函数(或在模块顶层消除 WT 绝对路径依赖,用 `Path(__file__).parents[1]` 相对定位);
2. 同批 4 个脚本式文件(test_132_*、test_alert_denoise)要么同样收敛为 pytest 函数,要么移出 scripts/tests/ 到 scripts/self_tests/(改 CI ⑧路径),二选一不留第三种;
3. ⑧ 步骤加 `--strict` 或改 `pytest -q --tb=short`,让「collection 0 test / ERROR」显式 FAIL(现状 pytest 对 0 test 目录 exit 5 已会 FAIL,主要修 1+2);
4. 改完本地跑 `python -m pytest -q scripts/tests/` 全绿 + push,CI 下一 run 应回绿。

## 3. 「未恢复残留」专节(云上 alert_state.json,status != recovered)

总 key 151,真未恢复 3 条 + 语义待解析 6 条:

| key | status | first_seen | 现状核实 | 为什么没恢复 | 会自愈吗 |
|---|---|---|---|---|---|
| s06_snapshot\|exit!=0\|143 | active | 09-28 23:45 | 09-29/09-30 s06 快照机检六项全 PASS,产物 610KB 已写 | 监控器 hold:「任务仍在进行中(dur=null), 不判恢复」(schedule_monitor 日志原文);非交易日(10-01~10-08)s06 不跑,无新运行收口 | 下个交易日(10-08)20:35 运行后由监控器重新评估;当前实为已自愈但状态残留 |
| nextday_plan\|exit!=0\|1 | active | 09-30 22:45 | 09-30 失败=R2 上传超时(300s),产物全部落盘;10-01/02 非交易日跳过 | 监控器已判「距今>24h 旧告警过期,等下次任务跑更新」(日志原文),nextday_plan 下次运行=10-08 22:30 | 10-08 22:30 运行正常即清除;残留无害 |
| r2_intraday_lag\|buffer\|20260929 | pending | 09-29 15:00 | 对应 R2 intraday 滞后已随 09-30 恢复(R2 intraday 数据 09-30 20:35 起正常);同构 key r2_intraday_lag\|buffer\|20260930 已 recovered(09-30 14:45) | 该 day-buffer 条目无独立恢复判定(09-29 当日 R2 数据 20:35 后有推,但 09-29 版 buffer 未显式 recovered) | 无害,等自然滚动;功能等价已恢复 |
| fetch_news\|r2_skip_rounds / overfit_monitor\|r2_skip_rounds / intraday_snapshot\|r2_skip_rounds | (skip_rounds 计数器) | 09-24/09-24/09-29 | **skip_rounds 已全部归 0**(=已恢复的计数器归零),对应 r2_skip_alert 三 key 均 status=recovered(最后一条 10-03 00:45) | 计数器形态无 status 字段,归 0 即恢复 | 已恢复 |
| r2_pipeline_congestion\|20261001/02/03 | (现象暂存) | 10-01/02/03 | 20261001/02 phenomena=[];20261003 有 1 条 fetch_news 锁现象,summary_sent=false | 日度聚合器暂存,非活跃告警 | 设计如此 |

## 4. 「冻结表缺失历史信号事件 622 个」独立核实(2026-09-18 10:54 severe)

- **根因文档**:docs/kelly/analysis/kelly-freeze-timespot-rootfix-20260918.md —— 冻结表 `signal_kelly_etf_freeze.json` 的冻结值=回测脚本「首次碰到信号时点」就地补冻、不锁定信号日,dev sync 后本机 map 新 → 历史信号被重冻产生漂移(实证:9-16 hs300 云上冻结 81.5 vs 本机重冻 78.7)。
- **根治(09-18 当天落地)**:① signal_kelly_backtest.py `_resolve_etf` 对历史信号(date < latest_signal_date)拒绝补冻,记 `_FROZEN_MISSING_EVENTS` 告警;② sync_dev_from_r2.sh 新增 rsync 云上权威冻结表。
- **622 告警本身 = 设计如此的防御闸首次触发**:09-18 根治落地当天,全量回测首次把 622 个历史欠账信号事件识别为「拒绝补冻」并告警提示人工核查(文档验收记录:sync 后重跑「拒绝补冻告警 0 个、冻结表 md5 同云上、键集合零差异」)。
- **复发核查(全通道)**:
  - notify_dedup.json `signal_kelly_frozen_missing` last_alerted = **2026-09-18 10:54:43,之后再无更新**;
  - 云上 latest.md 流水 09-19 起无任何「冻结表缺失」条目;
  - 云上 update_all_launchd.log grep「冻结表缺失/拒绝补冻/_FROZEN_MISSING」= **0 命中**;
  - 云上冻结表现状:28,258 条,最新 key 20260930,10-03 16:47 仍在正常更新 → **09-18 后从未复发,已根治**。
  - 本机为对照:本机 trade-data 冻结表 28,211 条(10-02 sync)、trade/ 冻结表停 09-20(开发机滞后,mtime 09-20 20:06),不影响线上。

## 5. 必须马上修排序建议

| 优先级 | 事项 | 根因 | 证据 | 建议 |
|---|---|---|---|---|
| P0 | CI Quality Gate ⑧ 门禁空转(2 天) | test_notify_r4_dedup_20261001.py 脚本式自测致 pytest collection 必崩(§2) | 40+ run 全红 + 本地复现 ModuleNotFoundError/SystemExit | 修文件为 pytest 风格(§2.5),同批 4 文件二选一收敛;修完 CI 回绿 |
| P1 | staticdata git 变更量 backlog(1.2GB/日,超阈值跳过 commit ≈ 4 天) | 大 JSON 未迁移(记忆 staticdata-old-mirror-keep-decision 8.3G 旧镜像保留至 10-30) | info_log 59 条超阈值+latest.md 5 条 | 国庆后评估 migrate_large_json_out_of_git.sh;镜像删除须守 §25(先备份验证可恢复) |
| P2 | s06/nextday_plan 两条 active 状态残留 | 监控器 hold/过期机制,非任务本体故障(§3) | schedule_monitor 日志原文 | 不急于修;10-08 首个交易日后复查是否自动收口,若持续挂 2 个交易日再修监控器 |
| P3 | R2 网络抖动复发(09-24~10-03 时段性强,rc=28/SKIPPED_LOCKED 交替) | 网络层(云上↔R2),非代码 | 时段链证据(§1) | 观察;若 10-08 后交易日再频发,查 upload_r2 超时参数/网络路径 |

## 6. 附:信息可追溯锚点

- 云上:/home/ubuntu/code/trade-data/data/alerts/{latest.md, info_log.jsonl, alert_state.json, data_gap_alert_state.json, warning_dedup_state.json};日志 /home/ubuntu/code/trade-data/data/logs/
- 本机:/Users/linhuichen/code/trade/data/alerts/latest.md;data/alert_state.json;notify_dedup.json
- CI:https://api.github.com/repos/xp13465/trade-data-signal/actions/workflows/349474535/runs(最后绿 #394=2026-09-30T17:29:34Z;首个红 #414=2026-10-01T15:30:14Z)
- 复现代码:本地 venv `/Users/linhuichen/code/trade-data/.venv/bin/python -m pytest -q scripts/tests/`
