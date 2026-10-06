# #182 飞书 hook 心跳监控「云上永久空转」——机制定位 + 修复方案(2026-10-06)

- 任务来源:`docs/ops/alert-systematic-review-20261005.md` §三-1 / 编号 N2
- 调研模式:**全只读**(mac 未 source/exec 任何仓内业务脚本;云上 ssh 查询全部为 cat/ls/systemctl/journalctl/ps/pgrep 只读类,零写)
- 关键一句话:**云上维度⑧恒空转实锤(23 天 0 输出);且 mac 侧 09-13~10-06 实际也无人判(盲区真实存在);今日 17:34 mac 重启使 mac monitor「意外复活」,维度⑧⑨判定才被重新覆盖——不可依赖,需按本报告方案固化。**

---

## 一、结论摘要

1. **机制定位**:维度⑧「飞书 hook 心跳自检」在 `scripts/schedule_monitor.sh` **L2215-2354**(源报告所引 L1835-1970 系行号漂移,精确定位以本文为准)。三层判定 + 防误报 + 去重/恢复完整,但**全部输入取自「运行所在机器」的本地环境**。
2. **飞书全链路在 mac**:hook 配置在项目级 `.claude/settings.json`(UserPromptSubmit/Stop → `scripts/feishu_chat_hook.py`),心跳由 mac 上该脚本 touch;ws 接收链 `feishu_ws_listener.py` 也在 mac。**云上没有也不会有这条链路的任何一环。**
3. **云上恒空转实锤**:云上 monitor 23 天连续运行(09-13 ~ 10-06,每天 96-108 行日志),该维度 **0 行输出**;按代码逐行推演云上判定恒 False(不告警、不 warn、不恢复,完全静默)。
4. **mac 侧同期间也无人判**:mac monitor 日志 09-13 14:45 后空白 23 天(迁云窗口停跑)→ 期间「本机 hook 真挂了」确实无人知道 = **盲区真实存在**。
5. **但今日 17:34 mac 重启后 mac monitor 已复活**(plist 残留被 launchd 重新加载):17:45/18:00 连续两轮(runs=2),维度⑧⑨判定能力事实上已恢复;复活轮已**真发**一封 [mac] 告警(含 2 条迁云误报),产生了实际噪音(见 §五)。
6. **修复方向**:本机哨兵(复用 monitor 脚本加作用域开关)+ 云上显式 skip;「心跳外移云上判」方案**不完整**(活跃闸门无法外移,详见 §六方案 B)。

---

## 二、飞书 hook 链路与心跳写入方(任务问题 1)

| 环节 | 位置/内容 | 证据 |
|---|---|---|
| hook 配置 | 项目级 `/Users/linhuichen/code/trade/.claude/settings.json`:UserPromptSubmit → `python3 /Users/linhuichen/code/trade/scripts/feishu_chat_hook.py user`;Stop → 同脚本 `assistant`(PostToolUse=agent_dispatch_cron_reminder.py,无关) | 直接读 settings.json;command 为写死的 mac 绝对路径 |
| 心跳写入方 | `scripts/feishu_chat_hook.py`:L64 `HEARTBEAT_FILE = /tmp/feishu_hook_heartbeat`;L513-520 `main()` 拿 flock 后**无条件 touch**(不依赖发送成败,写失败仅记日志) | 代码行号 + 实测 mtime 随会话刷新(17:48:52 → 17:50) |
| 心跳落点 | **mac 的 /tmp**(代码无任何跨机逻辑);云上 `/tmp/feishu_hook_heartbeat` 不存在 | ssh 实测 `No such file or directory` |
| ws listener(接收链) | `feishu_ws_listener.py` 跑在 **mac**(PID 4155,17:35:27 启动=重启后 launchd 拉起);写 `/tmp/feishu_ws_last_event`(mac,17:53 更新) | mac `ps -axo`;云上变量拼接 pgrep=0(self-match 已排除,见 §4.3) |
| 云上侧 | 无 `.claude` 目录(整个 `/home/ubuntu/.claude` 不存在)、无相关进程、无心跳文件 | ssh 实测 |

**结论**:hook 是 Claude Code **会话机能**(只在 mac 的 Claude Code 会话触发);ws listener 常驻 mac。判定方(monitor)与信号源(心跳/jsonl/进程)物理分离在两台机器 = 空转的结构性根因。

---

## 三、三层判定逐层读(任务问题 2,行号锚点)

判定组合(核心表达式,行号精确):

```python
# L2299-2301
_hb_hb_bad     = (not _hb_fresh) and (_hb_old_proc or not _hb_missing)
_hb_active_use = _hb_session_active or (_hb_long_inactive and bool(_hb_claude_pids))
_hb_alert      = _hb_hb_bad and _hb_active_use
```

| 层 | 判什么(行号) | 依赖 | mac 可判 | 云上可判 | 今日实际 |
|---|---|---|---|---|---|
| a(SEVERE) | 会话活跃(90min 内 jsonl 有更新)+ 心跳陈旧/缺失 → SEVERE(L2227 注释 / L2296 / L2313-2319 文案) | `~/.claude/projects/**/*.jsonl` mtime(L2250-2263) | 可 | **不可**:云上无 projects → `_hb_newest=0` → `_hb_session_active` 恒 False(L2260-2265) | mac(复活轮):活跃+心跳新鲜 → 不告警 ✓;云上:恒不成立 |
| b(warn) | 会话不活跃 + 心跳坏 → 降级 warn 只记日志(L2228 / L2331-2335) | 同 a | 可 | 不可(且到达该分支需 `_hb_hb_bad=True`——云上恒 False,连 warn 都不打) | 云上:静默 |
| c(SEVERE) | >7 天无任何会话活动 + claude 进程存活 + 心跳坏 → SEVERE(L2229-2230 / L2297) | jsonl mtime + `pgrep -f claude`(L2239-2241) | 可 | 不可:`_hb_long_inactive` 恒 True(L2265:无 jsonl),但 `_hb_claude_pids` 实测空 → 不成立 | 云上:恒不成立 |
| 防误报 | 心跳缺失时要求 claude 进程存活 >30min 才计较(L2231 / L2280-2293) | `ps -o lstart` | 可 | 不可(无进程) | — |
| 去重/恢复 | key=`feishu_hb_stale`(L2302-2350);恢复要求 `_hb_hb_bad=False` 且状态 active | alert_state.json | ✓ | 云上永不恢复(见下) | 云上 alert_state 无迁云后更新 |

**云上合值逐行推演**:`_hb_missing=True`(文件不存在,L2272-2279)→ `_hb_old_proc=False`(`_hb_missing and _hb_claude_pids` 不成立,L2282)→ **`_hb_hb_bad = True and (False or False) = False`** → **`_hb_alert=False`**;且进不了 b 层 warn(L2331 前置 False)→ 走恢复分支(`_ex_hb` 状态 recovered,无动作)→ **完全静默,0 行输出**。与实测(云上日志 23 天该维度 0 行)完全吻合。

**潜在「地雷」(调研新增发现)**:云上若未来出现任何**命令行含 "claude" 字样且存活 >30min 的进程**(部署脚本、别名、未来组件),则 L2300 右项 `(True and True)` 立即成立 → **恒 SEVERE 告警**,且因心跳文件永不出现在云上而**永不自动恢复**(除非该进程消失);告警文案还会谎称「Claude Code 会话活跃」(实际云上无会话)。今日干净实测 `pgrep -f claude` = **0**,地雷未触发,但它是"空转→死锁告警"的翻转风险。

---

## 四、现状实测(任务问题 3)

### 4.1 证据矩阵(命令与观测值)

| 项 | mac(本机) | 云上(ssh 122.51.111.173) |
|---|---|---|
| `/tmp/feishu_hook_heartbeat` | 存在,0B,mtime 17:48:52→17:50(随会话活动刷新) | **不存在** |
| `~/.claude/projects` jsonl | 存在,newest mtime=当前(17:49:11) | **不存在**(整个 `/home/ubuntu/.claude` 无) |
| `pgrep -f claude` | 有(claude --resume PID 9789,17:47:01 起;沙箱内 pgrep 受限,以 `ps -axo` 复核) | **0**(变量拼接实测,见 §4.3) |
| `feishu_ws_listener` 进程 | 跑(PID 4155) | 0 |
| `/tmp/feishu_ws_last_event` | 存在,17:53 更新 | **不存在** |
| monitor 运行状态 | 09-13 14:45 起 23 天日志空白;10-06 17:34 重启后复活:17:45、18:00 两轮(`launchctl print` runs=2,last exit=0) | 持续运行(日志 09-25~10-06 每天 96-108 行;当日 17:45:01 刚跑,18:00 亦跑) |
| 维度⑧日志输出 | 最后输出 09-13(01:45 SEVERE → 07:15 恢复);今日复活轮无输出(输入正常,不告警) | **23 天 0 行**(grep `hook 心跳\|feishu_hb\|feishu_hook_heartbeat` = 0) |
| 维度⑨(ws)日志输出 | 08-25 历史(缺失告警→恢复);之后无 | **0 行**(同族空转) |
| alert_state `feishu_hb_stale` | first_seen 09-13 01:45:04 → last_recovered 09-13 07:15:05 | first_seen 09-12 02:00:05 → last_recovered 09-12 09:15:05(迁云前遗留,此后再无更新) |

**两条独立结论**:
- 云上恒空转:输入三缺(上述)+ 日志 23 天 0 行 + alert_state 无迁云后记录,三证闭环。
- mac 侧 09-13 14:45 ~ 10-06 17:44 无人判:monitor 日志空白 23 天(盲区成立)。今日 17:45 起 mac 侧恢复覆盖(复活)。

### 4.2 mac monitor「停 23 天 + 今日复活」时间线

- **09-13 14:15** 云上 monitor 首条日志(迁云完成);**09-13 14:45** mac monitor 最后一行 → 迁云窗口内 mac monitor 停跑。
- **09-14 ~ 10-06 17:44**:mac monitor 零输出(23 天空窗)。机理二选一,均有旁证、诚实标注:①mac 长期睡眠/关机——launchd calendar 任务睡眠不触发,现代 macOS 唤醒后不补跑;但 listener 日志证明 mac 于 **09-28 / 10-02 / 10-03** 有短暂活跃(补拉/回执行),monitor 却未跑,提示可能不全是睡眠;②迁云操作曾 bootout 过 monitor 而 plist 文件未删。两机理下修复口径相同(见 §六)。
- **10-06 17:34:21 mac 重启**(`sysctl kern.boottime` 实测);launchd 登录加载 `~/Library/LaunchAgents/` 全部 plist(目录实测有 **41 个 com.trade 文件**,`launchctl list` 实测已加载 **40 个**)→ 17:35 feishu-listener 复活、17:45 monitor 复活(:45 触发点)、17:50 update-all 复活(其 plist Hour=17/Minute=50,RunAtLoad=0)。
- **复活轮行为(实测)**:17:45:05 真发 3 项告警 + 2 项恢复;18:00:05 轮 `OK 所有任务按计划执行`(前 3 项已 active 去重)。
- **噪音告警已真实外发**(需主控知悉):`[notify] 邮件已发送至 234058394@qq.com：[告警] [mac] 3项计划任务异常 10-06 17:45` + 飞书已发送(oc_7d8d…)+ `data/alerts/latest.md` 登记(17:45:16 severe)。其中 `gen_daily_brief 停摆(超26h)`、`fetch_news 停摆(超4h)` 两条系**迁云误报**(mac 本地 schedule_stats 停更于 09-13,任务实际在云上正常跑);`cloud_unit_patrol 退出失败 last_exit=3 last_run=2026-10-05 21:32` 为 mac 本地 stats 旧数。
- **双跑风险(超出 N2,建议另开编号)**:mac 上一整套任务复活后按 mac 本地时点运行(如 update-all 今日 17:50:05 已在跑),与云上任务并行;mac 侧写本地库/数据,对 R2/main 推送影响面待核(§14 生产稳定性视角)。

### 4.3 双链旁证与 debug 备注

- **「mac monitor 自身存活」也无监控(同族盲区)**:云上 `check_monitor_heartbeat.py`(:11/:26/:41/:56,10-03 新增 P0-1)消费**云上** `/tmp/schedule-monitor-heartbeat.txt` → 只覆盖云上 monitor。mac monitor 也在写自己的 `/tmp/schedule-monitor-heartbeat.txt`(`schedule_monitor.sh` L2665;今日 18:00 mtime 实测)——**无任何消费者**。mac monitor 停了 23 天,零告警,即为例证。
- **云上 pgrep 陷阱**:`pgrep -f claude` 在云上直接跑会 **self-match**(检测命令自身命令行含 "claude");本报告所有「云上 0 进程」结论均用变量拼接复测(`A=cl; B=aude; pgrep -f "${A}${B}"` = 0)。
- mac 沙箱内 `pgrep` 受限(返回 0 与 `ps -axo` 矛盾),mac 侧进程结论以 `ps -axo` 为准。

---

## 五、今日已发生的实际影响(主控需知悉)

1. mac 重启 → 40 个残留任务加载 → **已向用户真发 1 封 [mac] 告警**(邮件+飞书+latest.md),内含 2 条迁云误报(gen_daily_brief/fetch_news "停摆")。
2. update-all 等采集类任务在 mac 复活运行,与云上存在双跑面(建议与 mac 残留清理一起另开编号统一处置)。

---

## 六、方案(任务问题 4)

### 6.0 前置坐标系(为什么方案长这样)

- 判定输入(心跳文件 / jsonl / 进程)全在 mac;「会话活跃闸门」(jsonl mtime)只能本机读。**云上判「本机 hook 死活」在物理上缺输入**,除非"心跳+活跃"双信号都外移 + 在 mac 部署独立于 hook 的上报者——而那个上报者本身就是「本机哨兵」,方案即收敛回 A。
- 既有先例:环境维度裁剪已存在——#196 failed-unit 巡检在 mac 上打印 `[skip] 非云上巡检环境`(今日复活轮日志实测:`[196] failed-unit 巡检跳过(非云上环境): [skip] 非云上巡检环境`)。N2 修复对齐此模式即可。

### 方案 A(推荐核心):本机哨兵 = schedule_monitor.sh 加「作用域」开关

- **设计**:新增 `MONITOR_SCOPE=local|cloud|full`(默认 `full`=现状,零破坏)。
  - `local`(mac):只跑**本机链路维度**(⑧ hook 心跳、⑨ ws 心跳);任务面维度(漏跑/退出/耗时/统计)不跑——消除今日已发生的"迁云误报"类噪音。
  - `cloud`(云上):跑任务面/数据面全套;⑧⑨ 打印一行 `[skip] 本机专属维度(信号源在 mac)`——替代静默空转,名实相符、可观测。
  - ⑦ 飞书配置维度两端都有意义(各判自身 `config/feishu.json`),不裁。
- **落点**:mac `com.trade.schedule-monitor.plist` 加 EnvironmentVariables `MONITOR_SCOPE=local`;云上 unit `Environment` 加 `MONITOR_SCOPE=cloud`(显式优于隐式)。
- **爆炸半径**:`schedule_monitor.sh` 是生产脚本(云上跑)——改动仅"维度启用集 + skip 输出一行",**判定逻辑零改动**;reviewer 需核「full 模式行为与今日逐位一致」。
- **与「本机纯开发·定时任务全在云上」架构冲突逐条分析**(任务要求):
  1. **业务定时任务仍全在云上**;哨兵属"本机链路自检",非业务任务。且现状它**已在跑**(今日复活),本方案只是把"意外存活"变成"显式、受控、有清单"。
  2. **mac 睡眠/关机期哨兵不跑 = 漏检窗口**:但该窗口内用户不在 mac 上工作(无损害场景:没人用 Claude Code 时 hook 挂不挂无所谓);唤醒后下一触发点即恢复。本机链路监控的可靠上天花板 = mac 在线率,**接受**;云上判反而更差(不知道 mac 是否在用,必假阳性)。
  3. **单一巡检入口**:巡检文档加"mac 哨兵"一项(查 `launchctl print gui/501/com.trade.schedule-monitor` + mac 日志);可选增强把哨兵每轮心跳镜像到 R2/云上供 dashboard(见 D-4,默认不做,防过度设计)。
  4. **与残留清理协同**:清理 mac 40 个残留任务时**显式保留** schedule-monitor(哨兵)+ feishu-listener(接收链常驻)+ 其它确属本机专属者;清理清单须落档——防两种事故:「清理不彻底→plist 留目录→重启全员复活」(今日实例)与「清理过头→哨兵被删→盲区复发」。
- **备选 A'**(独立新脚本 + 新 plist,复用 notify.py):隔离性好,但会形成 L2234-2354 判定的**第二份实现**(同构漂移风险,§5.4⑦ 精神);不推荐为主选,实施评估阶段可讨论。

### 方案 B(心跳外移,由云上判):不完整,不推荐为主轴

- **B-单向(只外移心跳)**:无法区分「用户没用」vs「hook 挂了」→ 深夜/周末/假期恒假阳性 = **回归 #84 C3 之前**(该降噪机制的存在理由就是当年 7 天 12 封假 SEVERE)。不可取。
- **B-完整(心跳+活跃双外移)**:「活跃」信号必须由**独立于 hook** 的 mac 侧器件产生(挂的就是 hook,它不能自证活跃)= 仍然是哨兵;再叠加"hook 同步路径写 R2"(UserPromptSubmit 在交互路径上,加网络写有延迟/失败静默风险)→ 复杂度与故障面均高于 A,收敛后的净差异只剩"判定跑在云上"。
- **结论**:主轴不做。唯一可借鉴点 = 「哨兵存活信号外移」(D-4 可选增强)。

### 方案 C(其他)

- **C1 云上显式 skip**(并入推荐 D):消除"看似有监控实则恒空转"的误导,对齐 #196 先例。
- **C2 端到端探针**(云上定时向飞书群发测试消息 → listener 侧确认回执):覆盖「云上→飞书→listener 接收」链路,可作为维度⑨补充;不覆盖「mac hook 触发」(维度⑧本体),不替代 A。建议另编号。
- **C3 listener/hook 迁云:否决**——hook 是 Claude Code 会话机能(只在 mac 会话触发),listener 的落盘/回执在本机;迁云 = 改能力本体且无收益。
- **C4 hook 自诊断补记**(`feishu_chat_hook.py` 下次触发时发现"距上次心跳 gap 异常大"则记日志/补报):轻量,可作为 A 的补充(哨兵不在线窗口的兜底),不能替代哨兵(挂着的时候它根本不触发)。

### 推荐 D(完整版)= A + C1 + 清理协同 + 验收口径

1. monitor 加 scope(§方案 A);
2. 云上 ⑧⑨ 显式 skip 留痕(§C1);
3. mac 残留任务清理清单(保留哨兵/feishu-listener,其余逐个拍板)——与今日噪音/双跑一起,**建议另开编号**统一处置;
4. (可选)D-4:哨兵存活信号镜像(每轮心跳写 R2/云上小文件,dashboard 级不告警;默认不做,防过度设计,是否做由主控定);
5. **验收口径**:§18 L48(改动自测**必须打桩、严禁真发**——今日已有真告警先例,测试误发=事故)、L49(验收用真实 mac 样本:真心跳文件/真 jsonl/真进程)、L46(哨兵告警落 latest.md;巡检事件驱动)、L50(测试不得跑生产脚本本体;探针 static-only)。

---

## 七、与同族边界(任务问题 5)

- **N3(utf-8 截断仅 warn,#183)**:monitor 内另一检查块;与本文无交集。
- **N4(dry-run 写 latest.md,#184)**:notify.py 语义问题;本报告发现的是**真发**告警(非 dry-run),互不越界。
- **维度⑨(feishu_ws_stale)**:与⑧同族同病(云上输入全缺、23 天 0 输出、判定仰赖 mac 进程/文件)。本报告哨兵方案默认一次覆盖⑧⑨;是否并入 N2 或另立编号由主控定。
- **衍生(超出 N2)**:mac 残留 40 任务复活/噪音告警/双跑风险——建议另开编号;本报告只附证据。

---

## 八、复现命令(逐条可复核)

```
# mac 侧(全部只读)
stat -f "mtime=%Sm" /tmp/feishu_hook_heartbeat /tmp/feishu_ws_last_event     # 心跳实时刷新(17:48-17:53 随会话)
find ~/.claude/projects -name '*.jsonl' ... | stat mtime                     # newest=当前时刻(会话活跃)
ps -axo pid,lstart,command | grep claude | grep -v grep                       # claude --resume PID 9789
ps -o pid=,command= -p 4155                                                   # feishu_ws_listener.py 在 mac
ls ~/Library/LaunchAgents/ | grep -c com.trade                                # 41 个 com.trade 文件(40 plist + 1 个 .json-bak)
launchctl list | grep -ci trade                                               # 40 个已加载
launchctl print gui/501/com.trade.schedule-monitor | grep runs                # runs=2(17:45/18:00 两轮)
grep -n "飞书 hook 心跳\|feishu_hb" data/logs/schedule_monitor_launchd.log    # 最后=09-13(07:15 恢复);今日复活轮无输出
grep -c "^\[2026-10-06 18:" data/logs/schedule_monitor_launchd.log            # 18:00 轮 = 1 行 OK
tail -18 data/alerts/latest.md                                                # 17:45:16 [mac] 3 项告警登记
sysctl -n kern.boottime                                                       # Tue Oct 6 17:34:21(今日重启)

# 云上(ssh -i ~/tdsignal.pem ubuntu@122.51.111.173,全部只读)
ls /tmp/feishu_hook_heartbeat /tmp/feishu_ws_last_event                       # 均 No such file
ls -d ~/.claude/projects                                                      # 不存在(整个 .claude 无)
A=cl; B=aude; pgrep -f "${A}${B}" | wc -l                                     # 0(防 self-match)
pgrep -f "feishu_ws_listener" | wc -l  # 注意该写法会 self-match;用变量拼接复测=0
systemctl list-timers --all | grep monitor                                    # trade-schedule-monitor.timer 活跃 :00/:15/:30/:45
grep -c "hook 心跳\|feishu_hb" data/logs/schedule_monitor_launchd.log         # 0(23 天零输出)
grep -oE "^\[2026-[0-9]{2}-[0-9]{2}" data/logs/schedule_monitor_launchd.log | sort | uniq -c | tail   # 每天 96-108 行(连续运行)
python3 -c "import json;d=json.load(open('data/alert_state.json'));print(d.get('feishu_hb_stale'))"  # recovered 09-12(迁云前)
```

---

## 九、诚实标注 / 未决项

1. mac monitor 09-14~10-06 无输出的机理(**长期睡眠/关机** vs **迁云时人为停跑**)未 100% 定论——pmset log 仅存今日记录;listener 日志证明 mac 于 09-28/10-02/10-03 有短暂活跃而 monitor 未跑。两种机理下「plist 残留 + 重启复活」的事实与修复口径相同。
2. mac monitor 复活后长期稳定性待观察(今日 runs=2 连续两轮;mac 再睡眠/关机/重载后的行为未测)。
3. 云上 8899 监听探测未果(ss 无输出,可能有权限限制)——不影响本报告结论(该假想信号源不可用)。
4. 本报告全程只读:mac 未执行任何仓内业务脚本;云上查询全部为只读类,零写。
5. 心跳文件写入方验证为**代码级确认**(L513-520)+ 运行态 mtime 观测;未做「人为停 hook 观察云上反应」类主动实验(违反只读约束且无必要——推演 + 0 输出证据已闭环)。

---

## 附:维度清单完成度(任务 5 问自查)

| # | 要求 | 完成 |
|---|---|---|
| 1 | 飞书 hook 跑在哪 / 心跳写入方 / 台机器 | ✅ §二 |
| 2 | 三层判定逐层读 + 行号锚点 | ✅ §三(L2215-2354,含源报告行号漂移纠正) |
| 3 | 今日是否恒空转(mac/云上实测取证) | ✅ §四(三证闭环)+ 复活事件时间线 |
| 4 | 方案 A/B/C 完整正确版 + L46/L48/L49 关系 | ✅ §六(含推荐 D 与验收口径) |
| 5 | 与 N3/N4 边界 | ✅ §七(并发现维度⑨同族,已标注不越界) |
