# 飞书「[告警·聚合] 6条 warning 刷屏」根因调研(2026-08-26)

> 只读调研报告。触发=用户报「飞书有一个聚合6warning 刷屏啦」。

## 结论(一句话)

**那封「[告警·聚合] 6条 warning 汇总 08-26 10:56」是 B1 修复(feat/fix-notify-flush-race)实施 agent 跑并发回归测试时的事故泄漏**——测试子进程用 spawn 启动后不继承主进程的 mock,首轮测试以真实渠道把 6 条假告警(`A-due-69475-0..5`)发进了真飞书 alert 群+QQ 邮箱;**不是源头持续异常反复入队,也不是 flush 清理失效重发**。8/22~8/26 全量群消息里「[告警·聚合]」仅此 1 封,"刷屏"感知另有两个真实来源(见 §4)。

## 1. 实际发了什么(问题1)

拉取飞书 alert 群(`oc_7d8d3eb6b322ddeb6b8e3c53519fae7e`)im/v1/messages 历史(8/22 00:00 ~ 8/26 12:00):

| 日期 | 群消息总数 | [告警·聚合] 类 |
|---|---|---|
| 08-22 | (窗口内少量) | **0** |
| 08-23 | 合计10条(22-23两日) | **0** |
| 08-24 | 35 | **0** |
| 08-25 | 14 | **0** |
| 08-26 | 1 | **1**(即用户看到的这封) |

唯一一封原文(飞书 API 返回 body.content):

```
[告警·聚合] 6条 warning 汇总 08-26 10:56

2026-08-26 09:56:33 A-due-69475-0
body-A-02026-08-26 09:56:33 A-due-69475-1
body-A-1 ... (共6条 A-due-69475-{0..5} / body-A-{0..5})
```

## 2. 是哪"6条"(问题2)

**不是真实监控告警,是并发回归测试的构造数据**:

- `scripts/test_notify_flush_race.py`(B1 新增,commit 03597ae6a)L54:`"subject": f"A-due-{os.getpid()}-{i}"`,`N_DUE = 6`——与群里 6 条 `A-due-69475-{0..5}` **逐字一致**,`69475` 即当时 writer 子进程 pid;
- 条目 ts=`09:56:33` = `_make_old_ts()`(now-1h,构造"满30min窗口必到期"),发出时间 10:56:38 正好差 1 小时,口径吻合;
- B1 实施 agent 进度文件 `/tmp/agent-progress-notify-flush-race.md` + 主会话汇报自认:"**测试过程踩坑已修:子进程 spawn 不继承 mock 导致首轮真发了一封测试邮件到 QQ 邮箱+飞书 alert 群(内容为 "A-due-N" 假告警,无实害),已改为 worker 进程内重新 mock**";
- 时间线:10:42 开工 → 10:54 notify.py 改造完成开始写测试 → **10:56:38 事故封发出**(mock 未生效的第一轮 T1 三进程并发测试)→ 11:04 测试全绿(mock 已修)→ 11:05 commit。

**佐证(非重复发送)**:生产 buffer `data/alerts/warning_buffer.jsonl` 当前为空、目录 mtime 与 `warning_buffer.flushlock` mtime 均为 08-26 10:56(测试进程 touch 后再无写入);schedule_monitor 日志 8/25 21:45 后全部 `OK 所有任务按计划执行`(除 update_all 耗时的 suppress 行,走 critical 直发非聚合)。flush 发送成功按 rid 精确清理的逻辑(B1 新增 L1253-1267)工作正常,无残留无重发。

## 3. 为什么"重复"(问题3)

**不存在重复**:同一批只发了 1 封。"刷屏"是三件事叠加的用户感知:

1. **测试事故单封**(本报告主体,一次性,已由 agent 自愈 mock);
2. **8/24 feishu_ws_stale 假死循环**:当天 35 条群消息中 `[恢复] feishu_ws` 10 条 + 对应 `[告警]` 5 条——ws listener 心跳误判→告警→恢复→又判陈旧,每 1.5~2h 一轮(00:00/02:00/04:00...20:00),这是真正的"刷屏"主力,8/24 已由三级分级改造(commit 9e1dae802)+ alert_ack.py 人工确认 24h 静默机制处置;
3. **8/25 baostock 封禁熔断(10001011)+覆盖率不足+deploy R2 上传失败 x2+update_all 117min 超时**等 critical 直发密集期。

**机制层结论**:warning 聚合链路(defer_warning→buffer→flush)本身**没有任何去重/静默机制**——同源告警若持续入队,每 30min 窗口必然重发一封(设计如此,防丢不防噪);本次事故恰好撞在链路上线(B1 merge 前夜)敏感期,被当成链路故障怀疑。

## 4. 项目内既有去重参考(问题4)

| 机制 | 位置 | 口径 | 适用评估 |
|---|---|---|---|
| `--dedup-key/--dedup-window` | notify.py L937 check_dedup,data/notify_dedup.json | 同 key N 秒内(默认1800,可传86400)不重发,发送成功才标记 | **可直接复用**:flush 发送侧对同指纹 subject 计数即可 |
| `alert_ack.py` 人工确认 | scripts/alert_ack.py + schedule_monitor 维度⑨ | 用户确认后 24h 静默同 key | 治理"持续中但人工核实正常",需人工介入 |
| 业务指纹去重 | fade_notified.json / nt_signal_notified.json | 内容 hash 指纹集合 | 同思路,按 subject 归一化指纹 |
| `[suppress]` 持续中抑制 | schedule_monitor.sh 多处 | last_alerted 未变则打印 suppress 不重发 | critical 专用,warning 可借鉴 |

套用成本最低的是第 1 种:flush_warning_batch 里对 due 条目做归一化指纹(subject 去掉时间戳/pid 后缀),查 dedup file,窗口内已发过则跳过或合并计数。

## 5. 方案建议(问题5,只方案不实施)

按根因分层——本次事故根因是"测试打到生产渠道",去重机制治不了它,两类都要:

**A. 防测试事故复发(对症本次)**
- 测试脚本强制双保险:①setUp 断言 `WARNING_BUFFER_FILE` 已指向 tmp 且路径含 `notify_flush_race_` 前缀,否则 fail-fast;②渠道 mock 改为模块级常量注入(如 notify._TEST_MODE 环境变量,send() 入口直接短路),不再依赖 patch.object 被 spawn 子进程继承。
- 利:根治;弊:无(纯测试代码改动,不触生产冻结契约)。

**B. warning 聚合降噪(治"同源反复入队"类真刷屏,空仓精神:降噪不能吞真告警)**
- 方案B1 同源指纹去重窗口:归一化指纹 N 小时(建议 4h=覆盖盘后全时段)内不重发。利:实现最小(复用 notify_dedup.json);弊:N 内真恶化也看不到增量。
- 方案B2 "第 X 次重复"计数合并:窗口内同指纹不新起一封,而是更新计数,下一封聚合消息里显示「该告警已连续入队 X 次」。利:不丢频次信息,用户可判断恶化程度;弊:需要 buffer 内合并逻辑,改动中等。
- 方案B3 恢复即静默:告警消失发[恢复]后,同指纹 24h 不再 warning。利:与既有[恢复]语义闭环;弊:间歇性抖动(恢复又复发)会被压掉。
- **穿透硬门槛(任选哪个都必须带)**:窗口内同指纹条数较上次翻倍、或出现 SEVERE/critical 升级、或 subject 含"漏跑/退出失败/超时"关键词组合变化 → 忽略去重窗口立即穿透发送。对应项目 memory「空仓也是正当策略手段」精神——降噪规则必须有升级逃生通道,不能把真故障静默成空仓。

**推荐默认:B(测试双保险,A/B1+B2 组合)**——B1 保底止血,B2 保留频次可见性,B3 可并入 B2(恢复清零计数)。理由:一步到位且不吞真告警;纯新增不改既有 critical 行为,符合 §23.7 冻结契约。

## 复现

- **脚本/命令**:
  - 拉群消息(只读):见下方 python 片段依赖 `scripts/feishu_ws_listener.py` 的 `load_config/load_env/_get_tenant_access_token`
    ```bash
    # 参数:chat_ids.alert=oc_7d8d3eb6...,start=2026-08-22 00:00,end=now
    python3 - <<'PY'
    import sys,json,time,ssl,urllib.request
    sys.path.insert(0,'/Users/linhuichen/code/trade/scripts')
    from feishu_ws_listener import load_config,load_env,_get_tenant_access_token
    load_env(); cfg=load_config(); token=_get_tenant_access_token()
    chat=cfg['chat_ids']['alert']
    s=int(time.mktime(time.strptime('2026-08-22 00:00:00','%Y-%m-%d %H:%M:%S'))); e=int(time.time())
    url=f'https://open.feishu.cn/open-apis/im/v1/messages?container_id_type=chat&container_id={chat}&start_time={s}&end_time={e}&page_size=50&sort_by=create_time'
    ctx=ssl.create_default_context();ctx.check_hostname=False;ctx.verify_mode=ssl.CERT_NONE
    d=json.loads(urllib.request.urlopen(urllib.request.Request(url,headers={'Authorization':f'Bearer {token}'}),timeout=30,context=ctx).read())
    for it in (d.get('data') or {}).get('items') or []:
        c=((it.get('body') or {}).get('content') or '')
        if '告警·聚合' in c: print(it['create_time'],c[:200])
    PY
    ```
  - 测试数据来源:`git show 03597ae6a:scripts/test_notify_flush_race.py | sed -n '45,60p'`(N_DUE=6 + A-due-{pid}-{i})
  - 时间线:`cat /tmp/agent-progress-notify-flush-race.md`;事故自认:主会话 jsonl 行17884(2026-08-26T03:07:44Z)
- **输入依赖**:config/feishu.json(alert 群 id)、trade-data/.env(FEISHU_APP_ID/SECRET)、data/alerts/warning_buffer.flushlock(mtime 佐证)、trade-data/data/logs/schedule_monitor_launchd.log
- **数据截止**:2026-08-26 12:00(群消息拉取时刻)
- **关键口径**:「[告警·聚合]」subject 仅由 notify.py `_flush_warning_batch_locked` L1239 生成;critical([SEVERE])直发不经聚合,两者 subject 可区分
