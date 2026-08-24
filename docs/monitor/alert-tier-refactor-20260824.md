# 告警三级分级 + TCP 无超时根修改造报告(2026-08-24)

> 依据:codex 报告 `docs/codex-reviews/audit-perf-and-alerts-20260824.json`(alert_noise_analysis 段)
> + tester 核查(`/tmp/agent-progress-alert-check.md`)+ 既有告警链路代码。
> 分支:`feat/alert-tier-timeout-refactor`(worktree 隔离开发,基于 origin/main 67273c8da)。
> 冻结契约:**降噪只减假警报,真故障(critical 级)仍即时邮件可达用户**,对照表见 §四。

## 一、三级分级模型(notify.py 统一出口)

| tier | 定义 | 行为 | 典型场景 |
|---|---|---|---|
| **critical** | 真故障:连续3次失败/数据丢失/服务宕 | 立即邮件(+飞书)+写 latest.md,不缓冲 | update_all 超时、R2 断链、72h 监控自停 |
| **warning** | 连续2次失败或单次非瞬时错误 | 入 buffer(`data/alerts/warning_buffer.jsonl`),30min 聚合窗口满后一封批发 | R2 前缀单次 curl 失败、smoke 首次异常 |
| **info** | 单次瞬时抖动(已自愈/人工已知悉) | 只记 dashboard(`data/alerts/info_log.jsonl`,2000行截断保留1000),不推送 | 单次网络抖动、acknowledged 静默期 |

- 出口统一在 `scripts/notify.py --tier {critical,warning,info}`;未知 tier 按 critical 处理(fail-critical,防漏报真故障)。
- warning 批发 subject 前缀 `[告警·聚合]`,发送成功才清已发条目(防丢);坏时间戳行按到期处理。
- flush 接线:`schedule_monitor.sh` 与 `monitor_72h.sh` 每轮收尾调 `notify.py --flush-warnings` 双保险。
- CLI 变更:`subject` 改可选(`nargs="?"`,兼容 `--flush-warnings` 无参调用),位置参数用法完全向后兼容。

## 二、五项改造明细与阈值依据

### 1. intraday_snapshot 超时连续≥3次才 severe(schedule_monitor.sh)
- 病灶实录:R2 PUT 超时连续 **11 次全部自愈**,每轮 SEVERE 邮件=假警报轰炸(codex 报告实证)。
- 机制:`TRANSIENT_TIMEOUT_TASKS={"intraday_snapshot"}`,Timeout 类 log 异常先入稳定桶
  `{task}|transient_timeout` 计数(line md5 每次不同不能按 key 计数),`TRANSIENT_TIMEOUT_THRESHOLD=3`,
  未达阈值只 print dashboard 不通知;循环尾无异常轮桶翻 recovered 自愈重置(已达阈值发过的
  md5 key 恢复通知仍由主恢复循环负责,桶只管计数不管通知生命周期)。
- 其他任务(log 异常/push 冲突等)**维持原状不动**(冻结契约:只新增降噪通道,不改既有判定)。

### 2. 其余阈值(tester 实测依据)
| 项 | 结论 | 依据 |
|---|---|---|
| push 冲突 | 仅最终 exit≠0 才告警(gen_schedule_stats.py scan_log_anomaly 加 last_exit 判据) | PUSH_SUCCESS_RE 四个成功标记不含 backfill 实际输出「[backfill] ✓ 补采+重算+推送完成」,16 条 self-healed 假警报实证;exit code 权威,文案会漂移 |
| 72h smoke curl | 连续≥2 次才告警——**已有机制天然满足**,未改(monitor_72h.sh SELF_HEAL_THRESHOLD=2 × 30min 频率,比"跨15min窗口"更保守) | L176 check_and_alert tier="self_heal",R2 prefix/p0 smoke 全部该档 |
| feishu_ws_stale acknowledged | 新增 `data/alert_state.json[key].acknowledged` 字段,人工确认后 24h 内静默(每小时一条 info 日志),超 24h 自动恢复提醒 | 维度⑨判定块读字段;配套工具 `scripts/alert_ack.py`(原子写+flock,--list/--clear) |
| update_all 超时阈值 | **保持 100min(4200s)+30min 缓冲不动**,仅本文档化 | tester 实测近9交易日 max=3609s(60min),100min 有裕量;历史最长 88min |

### 3. feishu ws 心跳埋点前移(scripts/feishu_ws_listener.py)
- 根因:touch 原在 process_event 内部(5 个 early-return 全不 touch)+ SDK CONTROL PING/PONG 帧
  不走用户回调 → 安静期心跳停更 → 看门狗 2h 自杀 12 轮(feishu_listener.log 8-20 起实证)
  → schedule_monitor 误报 stale。
- 改法:①run_listener 包装 `client._handle_message`(SDK 所有 WS 帧总入口,实例属性覆盖生效),
  任意帧先 `_touch_ws_last_event()` 再透传原处理;②handle 入口前置 touch;
  ③process_event 兜底 touch 保留(双保险幂等)。健康连接每 120s PING 必有 PONG 回帧→心跳最多
  2min 前进一次;TCP 半开僵尸 recv() 挂死收不到任何帧→停更→看门狗正确触发。语义从「需求消息流」
  改为「连接活性」(注释同步)。

### 4. recovered 回写修复(schedule_monitor.sh 孤儿回收块)
- 生产卡死实录:`72h_r2_prefix_industry_fail` / `72h_sw_version_mismatch`(08-12 起 active 至今)、
  `72h_p0_smoke_s5_alert`(pending)。
- 根因链:主恢复循环显式跳过 `72h_` 前缀(2026-08-10 防振荡修复,恢复检测归 monitor_72h 自身)
  + monitor_72h.sh 72h 到期自停(bootout+rm START_FILE)= 恢复检测无人接管,key 永久卡死。
- 改法:孤儿回收块放主恢复循环后——START_FILE 不存在(停摆;在跑时每次重建)+ 最后动作距今 >1h
  (宽限防竞态)→ 72h_ 前缀 active/pending 翻 recovered(recovery_reason=orphan_reaped),
  **静默不发恢复邮件**(监控停摆≠异常消失)。修的是逻辑,不手改 json;生产翻面由上线后首轮
  schedule_monitor 自动完成。
- 自验:生产 alert_state.json 只读副本隔离 exec,变更集恰为上述 3 条 key,其余 56 key 零变动。

### 5. TCP 无超时阻塞根修(app/collector/)
**超时清单(逐文件×调用点)**:
- `app/collector/fetchers.py`:自有代码全部网络调用 **37 处均已有显式 timeout**(多行感知扫描,
  含 requests.get/post/urlopen,11 处初判疑似无超时的实为多行参数形式)——自有代码零缺口。
- 真缺口=第三方库内部:akshare 库裸 socket(sample 抓堆栈实证 sock_connect→internal_connect
  无超时阻塞;lsof 5 个 CLOSE_WAIT,PID runner.run steps='metrics,indices,industry_extras'),
  库文件不可改(venv 只读),逐处枚举源名单追不全 → **统一入口根治**。
- 三层防御:
  ①`base.py` `socket.setdefaulttimeout(30)` 幂等兜底(getdefaulttimeout 为 None 才设,不影响
  requests/urllib3 显式传参);
  ②fetchers 泛化 `_safe_call_guarded(fn, timeout=None)`(daemon 线程+join 超时,返回 TimeoutError
  对象走既有 isinstance 异常分支,**不加新重试不改业务逻辑**),12 处 akshare 调用点全接入:
  东财档 20s(_safe_call_em 向后兼容别名)/默认 60s(_AK_GUARD_TIMEOUT),特殊档:_get_spot_df 120s、
  collect_direct 90s、collect_index 90s(东财特判20s)、collect_tencent 30s、债分块 30s、
  ths_concept/cffex 60s;
  ③requests 层显式 timeout(既有 37 处)。
- 分档函数名表:`_guarded_by_func` 按 `_is_eastmoney_func(func_name)` 自动分档,主链路统一入口。

## 三、同模式排查面清单(§23.2③ 举一反三)

| 同类面 | 处置 |
|---|---|
| monitor_72h.sh 尾部 flush | 已接 --flush-warnings(双保险) |
| 72h 各检查 tier | 核实已全 self_heal(满足连续≥2),未改 |
| gen_schedule_stats push 成功标记 | last_exit 判据根治(文案漂移免疫) |
| alert_ack 工具缺位 | 新建 scripts/alert_ack.py |
| 其他 TRANSIENT 任务(未来) | 加集合成员即可,机制通用 |

## 四、真故障推送行为对照表(冻结契约验证)

| 场景 | 改造前 | 改造后 |
|---|---|---|
| update_all 卡死/超时 | 立即 SEVERE 邮件 | **不变**(4200s+30min 阈值原样,critical 即时) |
| R2 断链持续≥2轮 | 第2轮起 SEVERE | **不变**(self_heal 原样) |
| 服务宕(launchd 未加载) | 立即 SEVERE | **不变** |
| 数据丢失(p0 smoke high.score fail) | 立即 SEVERE | **不变**(s5 high.score 档仍 severe) |
| exit!=0 连续失败 | 立即 SEVERE | **不变**(dedup suppress 原样) |
| intraday R2 PUT 超时单次/两次 | 每轮 SEVERE(11连发轰炸) | 前2轮只记 dashboard,第3轮起 SEVERE(**真故障第3轮必达**) |
| 飞书 ws 心跳陈旧(用户已核实) | 24h 阈值到期反复 SEVERE | ack 后 24h 静默(info 可见),超期自动恢复提醒 |

结论:所有「真故障」路径行为零削弱;削减的只有「瞬时抖动重复轰炸」「成功被误判失败」两类假警报。

## 五、改动文件清单

| 文件 | 改动 |
|---|---|
| app/collector/base.py | socket.setdefaulttimeout(30) 幂等兜底 |
| app/collector/fetchers.py | _safe_call_guarded 泛化+12 调用点接入+_guarded_by_func 分档 |
| scripts/notify.py | 三级分级(tier 参数/warning buffer/info log/flush)+subject 可选化 |
| scripts/schedule_monitor.sh | 瞬时超时桶/孤儿回收/acknowledged 抑制/flush 接线 四处 |
| scripts/monitor_72h.sh | 尾部 flush 接线 |
| scripts/gen_schedule_stats.py | push 冲突仅最终 exit≠0 告警(last_exit 判据) |
| scripts/feishu_ws_listener.py | 心跳埋点前移到 WS 帧层(wrap _handle_message+入口前置) |
| scripts/alert_ack.py | 新建:人工确认工具(--list/--clear/原子写+flock) |

## 六、复现

- **脚本路径**:本批均为活脚本(git 内 scripts/ 下 8 个文件,无一次性死脚本);验证脚本为内联
  python(见下方命令),无独立数据产物。
- **输入依赖**:
  - 分级自验:`scripts/notify.py`(config/email.json 可缺,dry-run 不真发);
  - 孤儿回收自验:生产 `data/alert_state.json` 快照(2026-08-24 22:00 前后,含 3 条卡死 key)+
    `/tmp/monitor_72h_start` 不存在环境(worktree 天然满足);
  - guard 单测:`app/collector/base.py` safe_call 语义(捕获一切异常返回异常对象)。
- **重跑命令**(worktree 或任意检出本分支的目录):
  ```bash
  # ①分级路由三态+到期批发(dry-run, 不真发)
  python3 scripts/notify.py "[告警]t" "b" --tier critical --dry-run
  python3 scripts/notify.py "w" "b" --tier warning          # 入 buffer
  python3 scripts/notify.py "i" "b" --tier info             # 只落盘
  python3 scripts/notify.py --flush-warnings --dry-run      # 到期聚合批发
  # ②语法: 两 shell 内嵌 python + 全部 py 文件
  python3 -m py_compile scripts/{feishu_ws_listener,notify,gen_schedule_stats,alert_ack}.py app/collector/{base,fetchers}.py
  # ③孤儿回收隔离验证: cp 生产 data/alert_state.json /tmp/copy.json 后按报告 §二.4 抽块 exec 比对变更集
  # ④guard 三路径单测: 按 §二.5 exec 函数体测 正常/异常透传/超时放弃
  ```
- **数据截止日期**:2026-08-24(alert_state.json 生产快照 22:00 前后;72h 卡死 key first_seen=08-12)。
- **关键口径一句话**:warning 级入 30min 聚合 buffer 满窗批发、info 级只落盘、critical 及未知 tier
  立即发(fail-critical);intraday_snapshot 的 Timeout 类异常连续 ≥3 轮才 SEVERE;72h_ 前缀孤儿
  key 在 START_FILE 缺失且最后动作 >1h 时静默翻 recovered(orphan_reaped);自有采集代码 37 处
  网络调用全有显式 timeout,库内部缺口由 setdefaulttimeout(30)+daemon 线程 guard(东财 20s/
  默认 60s)双层兜底。
