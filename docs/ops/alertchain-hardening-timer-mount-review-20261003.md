# 独立复核报告:alertchain-hardening 增量 def95ef43 挂载 check_monitor_heartbeat 到云上 systemd timer(2026-10-03)

> reviewer:独立 fresh context,只审增量 `62a69f1d6..def95ef43`(前次 2 commit 已 PASS 不再重审),外加 rebase 保真核查。
> 结论:**PASS**(8 项必查逐项证据齐;3 个低分项(<80)已滤,见 §3,不影响放行)。

## 0. 结论速览

| 必查项 | 结论 | 一句话证据 |
|---|---|---|
| ① rebase 保真 | PASS | 两组 diff md5 各自一致,差异仅 hc-secret 文档(三处 md5 全同) |
| ② brief_push_wrapper.sh | PASS | 仅注释改动(1 行→3 行),bash -n 通过,逻辑零变化 |
| ③ 云上 unit 实况 | PASS | unit 全文 ConditionPathExists 在 [Unit] 段、时点 :11/:26/:41/:56、54 timers 全量逐分钟比对 |
| ④ gen_systemd_units.py --check | PASS | 78 个 unit 待生成;生成物与文档 §2.36 逐行一致 |
| ⑤ dry-run 三场景 | PASS | 本地+云上全过;生产 latest.md mtime 00:45 未动 |
| ⑥ §23.7 冻结契约 | PASS | 纯新增 timer,既有 unit 零改动;merge 前窗口 condition skip 实况 4 条;两显式列表均不含新 unit |
| ⑦ 反例构造 | PASS(含边界标注) | 空/超长/权限正常判定;mtime 未来=漏报(pre-existing 边界);父目录不可达=裸 Traceback(pre-existing 健壮性,生产不触发) |
| ⑧ §23.15 完整版 | PASS | 实际告警范围(缺失/>30min,dedup 1h)= 声称范围,无降级展示项 |

## 1. 必查项逐项证据(trace/verifier 格式)

### ① rebase 保真(逐位对)
- `git diff cf68c7270 c60b8b5af | md5` = `git diff 62a69f1d6 1b78d097f | md5` = `b861fe98f10db9e48ac7472352dc444a`(内容=hc-secret 文档 +199 行)
- `git diff cf68c7270 62a69f1d6 | md5` = `git diff c60b8b5af 1b78d097f | md5` = `4fb386e0097c3ee560132a855089e8ea`(内容=前次复核报告 +187 行)
- hc-secret 文档三处 md5:`0cdda656c` / `c60b8b5af` / `def95ef43` 均 `05dfd738cc05fe5fe121df122b40792a` —— 同源未改
- 结论:rebase 前后实施/report 两组 commit 相对内容完全一致,差异仅 0cdda656c 引入的 hc-secret 文档,无内容丢失/被改。

### ② brief_push_wrapper.sh 只动注释
- diff:仅 L24 一行注释扩为三行(说明 write_alert 不 gate dry_run 的语义),无任何代码/逻辑行变化
- `bash -n scripts/brief_push_wrapper.sh` → SYNTAX_OK
- 结论:注释修正属实,逻辑零变化。

### ③ 云上 unit 实况(自己 ssh 实测,非文档转述)
- `cat /etc/systemd/system/trade-check-monitor-heartbeat.service` 全文:ConditionPathExists= 在 **[Unit] 段**(非 [Service] 段;文档 §3.1 如实记录初写 [Service] 段被拒→修正过程,journal 22:19:34 一次 Failed 为修正前历史,22:19:46 起全部 skip)
- `systemctl list-timers --all`(54 个)自行拉取:heartbeat NEXT=22:56 LAST=22:41:02;schedule-monitor 22:45/22:30、self-heal 22:52/22:37、fetch-news 22:45/22:01 —— 15min 档逐分钟零重合
- **全量 trade-\* timers 分钟位核对新时点 {11,26,41,56}**:与 15min 档 {00,15,30,45}/{07,22,37,52}、fetch-news {01,45} 均无重合;**唯一分钟位重合 = 09:26 的 trade-nextday-gap-check(工作日每日 1 次)**,两任务无共享资源(gap-check 行情跳空检查 vs 心跳消费只读 /tmp 文件 + notify 写告警),systemd 同时启动两个 oneshot 无资源竞争 → 不构成 §14 撞车。文档 §1.1「零冲突」声明在该点不严谨(其自列分钟位集合里已含 26 却说"均不含"),低分项见 §3.1。
- `systemctl is-active` → inactive(rc 3)、`is-failed` → inactive(rc 1):**非 failed** ✓
- journal:`Condition check resulted in ... being skipped` 22:19:46/22:20:00/22:26:01/22:41:02 共 4 条,定时器每 15min 触发且全 skip ✓

### ④ gen_systemd_units.py 自己跑
- `python3 scripts/gen_systemd_units.py --check` → `78 个 unit 待生成`(与文档声称 76→78 一致)
- 真实生成到 /tmp/genunits-review,`cat` 两文件与文档 §2.36 逐行一致(OnCalendar=*-*-* *:11,26,41,56:00 / Persistent=true / ConditionPathExists 在 [Unit] 段)

### ⑤ dry-run 端到端三场景(本地+云上各跑一遍,生产 latest.md 未污染)
- 本地(worktree python3 + 注入假心跳):
  - 缺失 → `✗ heartbeat 文件不存在` + 完整 notify 命令(dry-run),rc=0
  - 31min stale(1860s) → `✗ heartbeat 陈旧 1860s > 1800s` + notify 命令,rc=0
  - 5min fresh(300s) → `OK heartbeat age=300s <= 1800s` 静默,rc=0
- 云上(scp 副本到 /tmp/hc-review-heartbeat.py,--repo /home/ubuntu/code/trade-data 指向生产 notify.py):
  - 缺失 → 命令指向 `/usr/bin/python3 /home/ubuntu/code/trade-data/scripts/notify.py` 正确,rc=0
  - 31min stale(1860s) → 判定正确,rc=0
  - 生产心跳现状 age=821s → OK 静默,rc=0
- **生产 latest.md 未污染**:跑前/跑后 mtime 均 `Oct 3 00:45`、size 31238 不变;dry-run 分支 print 后 return 0 不调 notify.py(源码逐行确认,与挂载文档 §3.3 声称一致)

### ⑥ §23.7 冻结契约(既有作业行为零变化 + merge 前窗口不惊动)
- 新 timer/service 为纯新增 unit,`systemctl list-timers --all` 全量比对既有 trade-\* 无覆盖/无冲突改动;既有 unit 文件无一改动
- **merge 前窗口(云上脚本尚未 pull 到最新)实测**:`/home/ubuntu/code/trade-data/scripts/check_monitor_heartbeat.py` 不存在(ls 确认),timer 触发 4 次全部 condition skip,`is-failed`=inactive 非 failed
- **不惊动维度逐一核对**:
  - schedule_monitor.sh L958 LAUNCHCTL_LABELS 显式列表(11 label)不含新 unit → `launchctl_loaded` 不探测
  - self_heal.sh L78 LABELS dict(7 label)不含新 unit → 不探测
  - 全仓 grep list-timers/--failed 无全量扫描脚本(仅 check_doc_staleness.py 一个 docs 检查词)
  - 修正前 22:19:34 一次 Failed(systemd Unknown key 拒 [Service] 段条件)同样不会被上述维度探测 → 文档 §3.1 已如实记录此过程
- **误报路径排查**:消费者 :11/:26/:41/:56 恒晚于生产者 +11min,每次读到的是生产者完整跑完写好的心跳;生产者一轮崩溃 → 消费者下一轮看到 26min 旧(<30min 健康)、下下轮 41min(>30min 告警)= 设计内 2 轮容忍,无误报路径

### ⑦ 反例构造(逐个实测)
| 反例 | 注入 | 输出 | 判定 |
|---|---|---|---|
| 文件存在但为空 | touch 空文件 | `OK age=0s` | 不误报不漏报(mtime 判定语义,内容由 schedule_stats 通道校验) |
| 内容超长 200KB | 写 200KB | `OK age=0s` | 不误报不漏报(脚本从不读内容) |
| 权限异常 chmod 000 | chmod 000 | `OK age=0s` | 不误报不漏报(stat 不依赖文件读权限) |
| **mtime 落在未来(时钟回拨)** | touch -t 未来 1h | `OK age=-3599s` | **漏报**(mtime 方案固有边界:时钟回拨→age 恒负→永判健康,直到时间追上) |
| 父目录不可达(无 x) | chmod 000 父目录 | **裸 Traceback rc=1,无告警无诊断输出** | 静默失败(生产 /tmp=1777 不触发;消费者自身崩溃无独立通道=文档 §6 已标注同类元-元边界) |

- 漏报/静默失败两项均**非本次挂载引入**(脚本逻辑 pre-existing,前次复核已 PASS;挂载只加定时调用),生产路径 /tmp=1777、心跳文件 644 ubuntu 属主均不会触发;标注为已知边界(低分项 §3.2/3.3)。

### ⑧ §23.15 完整版核对
- 实际会告警范围 = 心跳缺失 / 陈旧 >30min(每 15min 检查一次,notify --severe --dedup 3600 防轰炸)
- 声称范围 = 心跳消费方接线(挂载文档 §0:缺失/超时告警,dedup 1h)
- **两者一致,无降级展示项**:脚本到位前 condition skip(静默,非降级展示)、到位后自动生效;挂载就绪清单六项全部有对应证据(unit 内容入仓+可复现 / 云上 enable+start+next 正确 / 文档三件 / 三场景实测 / 覆盖核对 / 回退可逆 §4)
- 被挂载脚本源码逐行核对:判定阈值 DEFAULT_STALE_SECONDS=1800、DEDUP 3600、dry-run print+return 0、异常退出码 2 语义,均与文档声称一致;docstring 边界三条诚实标注

## 2. 其他一致性/规范核对

- §22 一致性:unit 内容三处同值(云上 /etc/systemd/system 实文件 / 文档 §2.36 登记 / gen_systemd_units.py 生成物)逐行一致 ✓
- §21 公示:本次零算法改动(服务端逻辑一行不改,挂载只接线),不触发公示同步 ✓
- §23.5 四件套:挂载文档(本体)+ 登记文档(复现段,gen 可复现 78)+ 配套 commit def95ef43 ✓(被挂载脚本为既有,前批已落)
- §9.5 数据供给闭环:定时挂载真实存在(云上 systemd timer enable+start、journal 实跑 4 次)、机检挂链(gen --check 78)、过期告警路径(心跳消费)三者齐 ✓

## 3. 低分项(<80 已滤,留痕防黑箱)

- **3.1(50)文档 §1.1「零冲突」表述不严谨**:实际存在 09:26 与 nextday-gap-check 每日 1 次分钟位重合(无共享资源,不构成 §14 撞车);文档自列分钟位集合含 26 却说"均不含",属文档措辞瑕疵,不影响功能。
- **3.2(25)时钟回拨漏报**:mtime 未来时消费者永判健康(§1 反例表);pre-existing mtime 方案固有边界,生产 ntp 环境下罕见,挂载未引入。
- **3.3(25)父目录不可达静默失败**:hb.exists() 在 try 外,PermissionError 裸 Traceback rc=1 且无告警;生产 /tmp=1777 不触发,pre-existing 健壮性小瑕疵,消费方自身崩溃无独立通道已在脚本 docstring 与挂载文档 §6 诚实标注同类边界。

## 复现段

```bash
# ① rebase 保真
git diff cf68c7270 c60b8b5af | md5; git diff 62a69f1d6 1b78d097f | md5   # 两行均 b861fe98f...
git show 0cdda656c:docs/ops/hc-secret-purge-and-db-bak-research-20261003.md | md5  # 05dfd738c...
# ② 语法
bash -n scripts/brief_push_wrapper.sh
# ④ 生成
python3 scripts/gen_systemd_units.py --check    # 78 个 unit 待生成
# ⑤ 三场景(本地,注入假心跳)
python3 scripts/check_monitor_heartbeat.py --heartbeat-path /tmp/hc-review-missing.txt --dry-run
# 云上实况
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'systemctl list-timers --all; cat /etc/systemd/system/trade-check-monitor-heartbeat.service; systemctl is-active/is-failed trade-check-monitor-heartbeat.service'
```
