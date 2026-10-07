# 子 agent「完成时自有后台任务仍在跑 ⇒ UI 长期显示卡住未关」根因调研

- 日期:2026-10-07 | 调研:researcher agent(只读,零外发)| 现象首次被用户点名:2026-10-07「有一个子 agent 好像卡住没关,最近几天好像频繁有这情况」
- 本报告为纯取证/调研产物,不 commit,交主控决定后续动作

## 0. 结论(TL;DR)

1. **不是本项目代码 bug,是 Claude Code harness(v2.1.274)的机制**:子 agent 的 Bash 命令超默认 120s 上限后,harness **不杀任务、而是自动转后台**(「Command did not complete within its Ns timeout and was moved to the background (ID: X)」),该后台 shell 成为该 agent 的 live child。
2. 子 agent 工作完(SubagentHandback)时**后台 shell 仍活** ⇒ harness 把该 agent 条目标 `completed` 但打上 **keepaliveReasons**(前缀集 `["bash:","agent:","workflow:"]`,如 `bash:<taskId>`)⇒ 该条目**不进入 30 秒驱逐队列**(停放 parked)⇒ ListAgents / UI 里长期显示「completed」= 用户看到的「卡住没关」。完成通知里带专用备注:「This agent stopped with background work of its own still running...」。
3. 出路只有三条:①后台命令自己退出 →(通常)自动 resume 该 agent → 再收尾 → 正常驱逐(**19/24 走了这条**);②后台命令永不退出(find /、pip install 挂起、无头 Chrome)→ **永久停放**,只能人工 TaskStop 或会话进程退出(**实测最长残留 36.2h**);③命令退出但 resume 失效(上游 open bug #88423,2.1.283 仍在)。
4. **子 agent 其实有能力自救**——TaskStop 可杀自己名下的 `local_bash` 任务(**有成功实证**,见 §9.2),但绝大多数 agent 不知道/误以为「TaskStop 只能停 agent」(a71ca 的思考原文即此误判)。24 例僵尸中 0 例自清。
5. 量化:**24 例 / 12 个自然日**(2026-09-17 ~ 10-06);19 例曾自恢复、5 例全程静默(占比无法精确统计——只能覆盖两个会话文件且「没打备注≠没留过后台任务」,见 §5 诚实标注)。触发主因=**长命令没带 timeout**(24 例涉及 agent 共 1874 次 Bash 调用,只有 138 次(7.4%)显式传 `timeout`;7 次显式 `run_in_background`)。
6. 版本关联:该备注文案 **2026-09-17 15:23 UTC(北京 23:23)首次出现**,恰在 claude.exe v2.1.274 安装(09-17 14:48)后 35 分钟;v2.1.237/2.1.261 会话 0 出现(同环境已有自动后台化)。

## 1. 用户可见症状

- 主控视角:某子 agent 已交回完整报告(通知 status=completed),但**UI/ListAgents 里它一直挂着**(「completed · started Xh ago」),用户看到「卡住没关」。
- 本会话实例(用户点名的那个):`a71ca5848fa5936de`(P0 CI修复独立审 reviewer):10-07 01:08(北京)交回报告并带僵尸备注 → 转录冻结(最后写入 01:08)→ 主控 08:15 TaskStop 才清掉,**残留 7.1 小时**。
- 次生症状:①僵尸会**钉住自己的 worktree**(harness 原文「Agent worktree kept at …: backgrounded owner awaits keepalive, resume pending」,10-02 实测 `worktree-agent-a772ff1b…locked`);②主控的「在跑 agent 数」统计被污染(通知备注容易被忽略);③`turn_duration` 记录里 `pendingBackgroundAgentCount` 长期不为 0。

## 2. 受影响面枚举(方法 + 24 例清单)

**枚举方法(可复核)**:
```bash
# ① 主会话转录里搜 harness 僵尸备注(高信号锚点)
grep -c "background work of its own still running" ~/.claude/projects/-Users-linhuichen-code-trade/*.jsonl
# ② 命中文件:3ba5f717-…(74 条带 task-id 的命中) / d08c47ab-…(3 条);解析 <task-id>([0-9a-f]{17})</task-id> 去重 = 僵尸清单
# ③ 判「是否自恢复」:子agent 转录里 ts > 首次通知 ts 的记录数(>0=曾 resume)
# ④ 判「最终处置」:主转录 grep '"name":"TaskStop"' + task_id
```

| # | agentId | 任务 | 类型 | 首次僵尸通知(北京) | 曾自恢复 | 最终处置(TaskStop) | 残留时长 | 自动转后台次数 | 末次后台化命令(缩略) |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `a2f9a8ad54a662f6d` | 云上 accum_nav 数据就位 | implementer | 09-17 23:23 | 是 | 无记录 | — | 1 | `echo "step3: upload-accum-nav 上传 R2" >> /tmp/agent-progress-nav-` |
| 2 | `a092b9a327b3cd2e7` | 云上清理+pull+复验+备站排查 | implementer | 09-18 15:00 | 是 | 无记录 | — | 1 | `echo '===main分支根目录树(前40)==='; curl -s 'https://api.github.com/re` |
| 3 | `a6be0bbcdd6ca45f3` | 补跑 lab 和 turnover | implementer | 09-19 10:42 | 是 | 无记录 | — | 1 | `ssh -i ~/tdsignal.pem -o ConnectTimeout=15 -o StrictHostKeyCheck` |
| 4 | `ac6fb8c2c29f9217b` | 查 FAIL 路径不推 R2 是否设计意图 | researcher | 09-23 14:57 | 是 | 无记录 | — | 1 | `grep -rn "伪跳空校验未完成\|待人工\|就绪闸\|未完成.*R2\|R2.*未完成" /Users/linhuiche` |
| 5 | `a494dca04ddbce07f` | 补快照机检登记与公示 | implementer | 09-23 21:37 | 是 | 无记录 | — | 1 | `cd /tmp/wt-snapshot-p2 && python3 -c "import ast; ast.parse(open` |
| 6 | `a57a467a733955420` | 回测固化口径影响面 | researcher | 09-23 23:00 | 是 | 无记录 | — | 2 | `curl -s "https://ss.fx8.store/data/signal_kelly_trades.json?v=1"` |
| 7 | `aa7b751a9603583a4` | 补R2 kelly-parts缺口 | implementer | 09-23 23:28 | 是 | 无记录 | — | 3 | `for i in 1 2 3 4 5 6; do sleep 30; DONE=$(ssh -i ~/tdsignal.pem ` |
| 8 | `abd58d157258a4099` | 独立验R2污染清理 | tester | 09-24 01:33 | 是 | 09-24 02:35 | 0.0h | 6 | `cat > /tmp/r2_tail_check.py << 'PYEOF' import importlib.util, os` |
| 9 | `a585326118b8bcfc8` | 本机async收口验证 | implementer | 09-26 15:24 | 是 | 无记录 | — | 1 | `git -C /Users/linhuichen/code/trade-data-signal-staticdata fetch` |
| 10 | `a5946fe58084765b3` | 云上deploy并验前端上线 | tester | 09-26 18:33 | 是 | 无记录 | — | 1 | `echo "step2: 18:02 开始云上跑 deploy(REPO/GIT_REPO 已设)" >> /tmp/agent` |
| 11 | `a5be21d06baa0a91d` | P0云上修复R2解锁补推 | implementer | 09-29 15:58 | 否 | 无记录 | — | 1 | `echo "[第2步] 执行补推: upload-data-large + upload-all-data(均自带CF purg` |
| 12 | `a5e2d7cd43bcf8f87` | 126 staticdata云上迁移 | implementer | 09-30 00:57 | 是 | 无记录 | — | 4 | `ssh -i ~/tdsignal.pem -o BatchMode=yes -o ConnectTimeout=15 ubun` |
| 13 | `a14cd9d40ee0616fe` | Review CSP 白名单改动 | reviewer | 09-30 11:33 | 是 | 10-01 11:15 | 19.5h | 1 | `cd /tmp && node /tmp/csp-review-probe.mjs > /tmp/csp-review-out-` |
| 14 | `a9746102b85183fbe` | 北证50实时失败根因+云中转源方案 | researcher | 09-30 15:03 | 否 | 10-01 11:15 | 20.2h | 2 | `cat > /tmp/rt_probe.html <<'HTMLEOF' <!doctype html> <html><head` |
| 15 | `a728311a73e770659` | 连板历史回补写生产库 | implementer | 10-02 00:13 | 是 | 无记录 | — | 4 | `ssh -n -i ~/tdsignal.pem -o BatchMode=yes -o ConnectTimeout=15 u` |
| 16 | `a01716f9c4489a301` | 云上止血重出fund_nav | implementer | 10-02 22:11 | 是 | 无记录 | — | 1 | `ssh -i ~/tdsignal.pem -o BatchMode=yes -o ConnectTimeout=15 ubun` |
| 17 | `a772ff1bcc9af4d94` | 修图例tooltip字面b标签 | implementer | 10-02 22:49 | 否 | 无记录 | — | 3 | `pip3 install --user playwright 2>&1 | tail -3` |
| 18 | `ac562449df83a621b` | 云上跑完整deploy恢复线上 | implementer | 10-02 23:56 | 是 | 无记录 | — | 3 | `echo "[$(date '+%Y-%m-%d %H:%M:%S')] deploy 进行中:board_etf_map 校验` |
| 19 | `a129175bba57fc061` | PURGE_SECRET 边界+bak 来源 | researcher | 10-03 20:29 | 是 | 无记录 | — | 1 | `ssh -i ~/tdsignal.pem -o BatchMode=yes -o ConnectTimeout=15 ubun` |
| 20 | `acb76651085a17f36` | 轮换 PURGE_SECRET | implementer | 10-03 22:36 | 否 | 10-05 10:48 | 36.2h | 1 | `DIST=/Users/linhuichen/.npm/_npx/32026684e21afda6/node_modules/w` |
| 21 | `ad8cfa7e6d1d82182` | R2备份桶瘦身可行性实测 | researcher | 10-04 00:10 | 是 | 无记录 | — | 1 | `env | grep -i "r2_" | sed 's/=.*/=<redacted>/' ; echo "==="; /Us` |
| 22 | `a7031376632bb45be` | 开盘5分钟横幅修复(A方案) | implementer | 10-04 20:02 | 是 | 10-05 10:48 | 14.2h | 0 | `显式 run_in_background` |
| 23 | `a48d87fad15c10c88` | 查a642未上线原因与安全窗口 | tester | 10-04 21:56 | 是 | 无记录 | — | 1 | `UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/` |
| 24 | `a71ca5848fa5936de` | P0 CI修复(守卫真bug)独立审 | reviewer | 10-07 01:08 | 否 | 10-07 08:15 | 7.1h | 1 | `grep -c "独立逐处核" /Users/linhuichen/code/trade/docs/ops/223-4-ci-f` |

合计 **24 例 / 12 天**;曾自恢复 19 例,全程静默 5 例;有人工 TaskStop 记录 6 例。


## 3. 根因链(harness v2.1.274 二进制级取证)

取证对象: `/Users/linhuichen/.nvm/versions/node/v25.8.0/lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe`(214MB,v2.1.274,安装于 2026-09-17 14:48)。复现命令见 §11。关键代码(反混淆符号):

```js
// ① 「僵尸」判定:完成 + 后台化 + keepaliveReasons 里带 bash:/monitor:/workflow: → 完成通知打僵尸备注
function rzn(e){
  if(!Fn(e) || !e.isBackgrounded || e.status!=="completed") return !1;
  let n=SX();                                  // 运行态开关(混淆名)
  for(let r of IR(e)){                         // IR(e)=keepaliveReasons 集合
    if(r.startsWith("monitor:")||r.startsWith("workflow:")) return !0;
    if(n && r.startsWith("bash:")) return !0
  }
  return !1
}
// ② 备注文案二选一(通知模板处)
//    st = r==="completed" && rzn(Ee) ? "This agent stopped with background work of its own still running. It may resume on its own when that work completes or reports, and the same task-id notifies again if it does; the result below may be interim."
//                                     : "A task-notification fires each time this agent stops with no live background children of its own. ..."
// ③ 驱逐延迟:停放(keepaliveReasons 非空)的条目**不给 evictAfter** = 永不自动驱逐
function cgt(e,n){ if(e.retain)return; if(n.park && (e.keepaliveReasons?.size??0)>0)return; return Date.now()+PC }
var Q3e=3000, PC=30000, OVn=30000;            // PC=普通完成条目驱逐延迟 30s;OVn=agentIdleWindow 30s
// ④ 清扫循环里同款跳过: if("retain" in g && (g.keepaliveReasons?.size??0)>0) return s;   // 有 keepalive 就不删
// ⑤ 30s idle 窗回调只有「reasons 已空」才放行:
function Vus(e,n){ ...; if(Fn(r)&&r.status==="completed"&&IR(r).size===0){ ... R$e(e,n) ... } }
// ⑥ 原因前缀集: var Uus=["bash:","agent:","workflow:"];   // 即 keepaliveReasons 元素形如 "bash:bpkyhseth"
// ⑦ TaskStop 停「停放所有者」时连带杀其孤儿 shell:
//    "killAsyncAgent: killing orphaned shell task ${B} (parked owner ${L} killed)"
// ⑧ 停放会保留 worktree: "Agent worktree kept at ${r}: backgrounded owner awaits keepalive, resume pending"
```

因果链(逐步):

1. **自动后台化**:任何 Bash 调用超 `timeout`(默认 120000ms;显式上限 600000ms)后,harness 不杀、而是转后台,工具结果里给出 `ID: <9位taskId>`,该 shell 成为 agent 的 live child。24 例中 22 例有≥1 次该事件(另外显式 `run_in_background` 也计数,见 §4)。
2. **agent 停止时不扫尾**:子 agent 交回报告停止时后台 shell 仍活(agent 侧常见原因:①它认为「只读无害,随它去」——a71ca 原文「It'll finish on its own; a find / on macOS takes a while but is read-only. Leave it.」;②它误以为没法杀——同段原文「I can't easily kill via TaskStop (that's for agents; this is a Bash background task — I could use KillShell but that tool isn't in my list)」)。
3. **harness 停放**:completed 但 keepaliveReasons 非空 ⇒ 见 ③④⑤,30s 驱逐对它是**死代码**,ListAgents/UI 永久显示 completed。
4. **解锁条件**:后台进程退出 → harness 清 reason →(通常)向该 agent 投递 resume 通知 → agent 醒来收尾(此时无 live child)→ 正常驱逐;**实测 19/24 走了这条**。若进程永不退出,则永久停放。上游另报「进程内子 agent 在 run_in_background Bash 完成时从不被重新调用」(#88423,见 §7)——即第 4 步的 resume 本身不可靠。
5. **人工兜底**:TaskStop(agentId) 停停放所有者,harness 连带杀孤儿 shell(⑦)。注意:**僵尸只存在于该会话进程内**;claude 进程退出即清(3ba5f717 结束后其 `tasks/` 目录已被清扫,仅 d08c47ab 里 bpkyhseth 输出文件存活至被 TaskStop)。

## 4. 触发类型分类(后台命令都是什么)

按 24 例转录中「自动转后台」事件的命令分类(证据级别:A=实证到存活任务结束;B=停止前最后后台事件+终态吻合的强推定;C=类型统计):

| 类型 | 实例 | 说明 |
|---|---|---|
| ① 云上 ssh/scp 长任务(deploy/nohup/上传/等待轮询) | a2f9a8ad、a6be0bbc、aa7b751a、a5946fe5、a5be21d0、a5e2d7cd、a728311a、a01716f9、ac562449、a129175b、a57a467a、a48d87fa | 最多的一类。含 `for i in $(seq…) do sleep 30 …ssh…done` 长轮询等待循环 |
| ② 全盘/大目录扫描 | **a71ca584(证据 A:find / 实际存活 7h07m,直到 TaskStop 被杀)**、ac6fb8c2(目录内 grep -rn) | 无路径白名单的 `find /` 是典型「永不退出」源 |
| ③ 外网 curl(线上 JSON/API) | a092b9a3、a57a467a、a48d87fa | 网络慢时超 120s 转后台 |
| ④ 网络安装 pip install | a772ff1b(pip install playwright 连试 3 次) | 疑似网络/锁挂起 |
| ⑤ 无头浏览器探针 | a9746102(headless Chrome --dump/页面加载) | 无 timeout 的 Chrome 可能挂到天荒地老 |
| ⑥ 本地大 python 脚本(R2 扫描/一致性) | abd58d15(6 次)、ad8cfa7e、a494dca0 | heredoc 直跑的 R2 全量扫描 |
| ⑦ git 远端 fetch | a5853261 | 网络挂起 |
| ⑧ npx/wrangler(CF 工具) | acb76651 | Node CLI 长任务 |
| ⑨ node 探针 mjs | a14cd9d4 | — |

另有 a7031376 无自动后台事件,但用显式 `run_in_background=true` 起了任务(同因)。**共性:都是「网络/全盘 IO/外部进程」类不可控时长命令,且绝大多数没写 timeout。**

## 5. 量化与跨天模式

- **24 例 / 12 天**(UTC 日期):09-17:1、09-18:1、09-19:1、09-23:5、09-26:2、09-29:2、09-30:2、10-01:1、10-02:3、10-03:3、10-04:2、10-06:1(a71ca 北京时间落在 10-07 凌晨)。
- **恢复分布**:19 例在首次停放后曾自恢复(转录在通知后继续);**5 例全程静默**——`a5be21d0`、`a9746102`、`a772ff1b`、`acb76651`、`a71ca5848`(其中 3 例最终人工 TaskStop:a9746102 停于 20.2h、acb76651 停于 36.2h、a71ca 停于 7.1h)。
- **人工 TaskStop 共 6 例**:abd58d15(09-24 02:35,及时发现)、a14cd9d4(09-30 停,10-01 11:15 清,残留 19.5h)、a9746102(20.2h,同一批)、acb76651 + a7031376(10-05 10:48 同一批,残留 36.2h / 14.2h)、a71ca5848(7.1h)。→ 两次批量清理(10-01、10-05)说明**当时是攒着一起清**的,不是收到通知就清。
- **未收尾的 2 例**:a5be21d0(09-29 停;最后提及 10-01 17:08 的 worktree 列表)、a772ff1b(10-02 停;最后提及 10-02 15:11 locked worktree)——无 TaskStop 记录,推测随 3ba5f717 会话进程结束(10-05 03:59)被清理。
- **timeout 参数使用率(24 例 agent 名下全部 Bash 调用)**:1874 次调用中 138 次(7.4%)显式传 `timeout`;7 次显式 `run_in_background`。→ 长命令裸跑是常态,是「频繁发生」的结构性原因。
- **诚实标注(分母口径)**:无法给出「僵尸率 = X%」的严格值——①僵尸备注只在「停止时恰好有 live child」才打,没打备注的 agent 不代表没留过后台任务;②2.1.274 前版本无此备注(§6),跨版本不可比;③本统计只覆盖 `-Users-linhuichen-code-trade` 项目 + 两个会话文件(其他项目未扫,是口径边界)。

## 6. 版本关联(可见性信号是新增的)

- claude.exe v2.1.274 安装:2026-09-17 14:48;**僵尸备注文案首次出现:2026-09-17 15:23 UTC(北京 23:23)**(会话 3ba5f717 第 2036 行),对应 agent `a2f9a8ad54a662f6d`。
- 更早两个会话(27a3871b…、4f92f6a5…,v2.1.237/2.1.261):备注文案 **0 次**,但同期**自动后台化事件确实存在**(如 4f92f6a5:17 个 agent、23 次自动转后台)。→ 「停放」机制可能早已存在,**09-17 起只是多了这个可见信号**;不能反推 09-17 前没有同问题。
- 说明:升级 Claude Code 后应先 grep 二进制看两段备注文案是否还在(`§11` 命令),可 3 秒判断「打了备注=harness 仍会停放」还是「已改为自动清理」。

## 7. 上游佐证(§5.1-L47;7 个 issue,均为 anthropics/claude-code,状态 open)

| # | 标题(要点) |
|---|---|
| 88423 | In-process subagents are never re-invoked when their own run_in_background Bash / Monitor task completes(**正是本报告「出路③」;即正常路径的 resume 不可靠**) |
| 97696 | Background subagent reports "completed" with a live Monitor; the Monitor's event never resumes it (**still present in 2.1.283**, re-filing #86085) |
| 96849 | Second SubagentHandback after resume is rejected…(恢复链的二次收尾会丢报告) |
| 95273 | Background subagent's nested background Bash task stays "running" in UI after subagent completes, **invisible to ListAgents** |
| 99522 | Background subagents/tasks: **orphaned loops run 24h+**, inconsistent state between UI / ListAgents / TaskStop |
| 94392 | Headless `claude -p` exits with its own background subagents still running… |
| 86443 | Desktop (macOS): scheduled sessions with background tasks leak harness processes indefinitely |

结论:这是**上游已知、截至 2.1.283 未修**的类缺陷,不是在用错。

## 8. 次生影响

1. **worktree 钉住**:停放条目保留 worktree(harness 原文「backgrounded owner awaits keepalive, resume pending」);10-02 实测 `worktree-agent-a772ff1b…locked`、`worktree-agent-a5be21d0…` 在列表里挂着——会干扰 worktree/分支大扫除(「locked 且持有者 pid 已死」的怪象之一)。(现状:10-07 复查 `git worktree list` 已只剩 2 条,历史残留已被清。)
2. **主控误判**:僵尸在 ListAgents 上是 completed,又不会被驱逐,主控容易把「带备注的通知」当完成、把 ListAgents 残留当还在跑(两个方向都错)。
3. **机器负载**:find / 类僵尸会持续吃 CPU/IO 数小时(本机实测 7h+)。
4. **通知通道**:每个停放 agent 的完成通知文案带「result below may be interim」,若主控不当心会重复消费同一份结果。

## 9. 根治清单(可执行)

### 9.1 派单侧约束(主控/所有派单 prompt)
- **凡预计 >60s 的命令必须显式 `timeout`**(上限 600000ms;超了就拆步,而不是让它转后台)。
- **云上长任务一律 nohup 化**:`ssh … 'nohup … </dev/null >log 2>&1 & echo started'` 立即返回;等待改用**短轮询命令**(单次 <60s,如 `ps/pgrep` 一轮),禁止 `for i in $(seq 40); do sleep 30; …ssh…; done` 这种长挂(实例:a728311a/aa7b751a/a5e2d7cd 的长轮询循环正是僵尸源)。
- **禁全盘扫描**:禁止 `find /`、无路径白名单的 `grep -r`;一律限定目录白名单(实例:a71ca 的 find / 就是 7h 僵尸本尊)。
- **禁网络安装**:pip/npm 装大件走预置 venv 或专门任务,不在业务 agent 里裸跑(实例:a772ff1b pip install playwright ×3)。
- **headless 浏览器必须带 timeout + `--virtual-time-budget`/`--timeout`**(实例:a9746102)。
- 派单 prompt 固化一句话:**「交回报告前先自查后台任务:凡本次出现过『moved to the background (ID: X)』或 run_in_background 且尚未结束的,先 `TaskStop(task_id=X)` 清掉;确实清不掉的,在报告首行声明『残留后台任务: <ID> <命令>』,由主控收尾。」**

### 9.2 子 agent 侧(建议进 role skill 的收工清单)
- **TaskStop 可自救(已验证)**:2026-10-05 14:23(北京)会话 d08c47ab 的子 agent `aefbc4d3e7ced1236`(Git 分支大扫除)成功执行 `TaskStop {"task_id":"bzzkavjzj"}` → 返回 `{"message":"Successfully stopped task: bzzkavjzj (git fetch --prune origin 2>&1 | tail -20)","task_type":"local_bash"}`。**即子 agent 运行时可以停自己的后台 Bash 任务**;停不了的是 KillShell(该工具不在子 agent 列表)。
- 收工前自查(MEMORY 里已有同精神条目:agent-silent-death-pgrep-unreliable 判活法):转录里 grep `moved to the background (ID:` → 逐 ID TaskStop;完成后 handback。
- 长命令自带 timeout;避免「只读无害随它去」的判断(只读也会钉死会话状态)。

### 9.3 判活/清理 SOP(主控侧)
- **收到带僵尸备注的通知 ≠ 完成**:标记「停放中」,等待第二次通知(resume)或 20min 无动静。
- **判活**:ListAgents 在册 + 该 agent 转录 mtime 在推进 = 活;在册 completed 但转录 mtime 冻结 ≥20min = **停放僵尸 → TaskStop**(与既有 memory 判死法一致;TaskStop 会连带杀孤儿 shell,无需自己找 PID)。
- **一次收工扫描**:收工前跑 §11 的枚举脚本,凡「僵尸通知存在 && 无后续续跑 && 无 TaskStop」= 待清列表。
- 清理时保留证据(agentId/命令/时长)落档,便于统计复发。

### 9.4 机检可行性(能不能自动化)
- **可以(零侵入,读侧)**:`grep -c "background work of its own still running" ~/.claude/projects/<proj>/*.jsonl` + 「无后续 / TaskStop」判定 → 一个只读巡检脚本(建议 `scripts/check_agent_zombies.py` 或并入现有会话收尾检查),输出「僵尸候选清单」。**已在本报告 §11 给出可复用脚本骨架**。
- **可以(写侧)**:收尾提示——主控 CLAUDE.md/主控 SOP 已要求在汇报「在跑 N 个」前核对完成通知;把「僵尸备注」列为第三种状态即可(注:原始 spec 说「已收通知=已完成立即移出在跑」,现在需要加一条「带备注通知=停放中,需确认是否残留」)。
- **不建议**:去读 harness 内存态(keepaliveReasons 只在进程内存,外部读不到);也没有官方 CLI 能列「停放」状态(ListAgents 不区分)。机检只能靠「备注 + 转录 mtime」间接判。
- **不建议**为它写复杂 hook(cron 巡检已覆盖;避免过度设计,§5.2/既有 memory:批量架构别过度工程)。

### 9.5 长期
- 关注上游 #88423 / #97696(2.1.283 仍未修);将来升级 Claude Code 后用 §11 的二进制 grep 3 秒判定行为是否变化。
- 若上游长期不修,可考虑「收工脚本 + TaskStop」常态化(9.3)。

## 10. 证据索引(可复核锚点)

| 证据 | 位置 |
|---|---|
| 僵尸备注原文(通知模板+两种文案分支) | claude.exe 偏移 76159876/178328493(见 §11 grep 命令) |
| rzn/cgt/Vus/Uus/PC=30000/OVn=30000 | 同二进制,偏移 176383815 / 176383133 / 176377122 等 |
| 本会话实例完整链 | `~/.claude/projects/-Users-linhuichen-code-trade/d08c47ab….jsonl`:第 10723 行(通知+备注),10994 行(主控排查思考),11003-11004 行(TaskStop 成功),11025+ 行(清后探查) |
| a71ca 残留 find / 实证 | `/private/tmp/claude-501/-Users-linhuichen-code-trade/d08c47ab-…/tasks/bpkyhseth.output`(12 字节,lmt=2026-10-07 08:15:14=TaskStop 同一秒) |
| a71ca 思考原文(「Leave it.」/误判 TaskStop) | `…/d08c47ab…/subagents/agent-a71ca5848fa5936de.jsonl` 第 186 条 |
| TaskStop 自救成功实证 | `…/d08c47ab…/subagents/agent-aefbc4d3e7ced1236.jsonl` 第 232 条(2026-10-05T06:23:24.666Z) |
| 24 例僵尸通知 | `3ba5f717….jsonl`(74 条)/ `d08c47ab….jsonl`(3 条) |
| worktree 钉住 | `3ba5f717….jsonl` 第 41444/41477 行(10-02 locked 列表) |
| 上游 issue 标题/状态 | `curl -s https://api.github.com/repos/anthropics/claude-code/issues/<N>` |

## 11. 复现命令(全部只读)

```bash
# ① 列僵尸通知(高信号锚点)
grep -c "background work of its own still running" ~/.claude/projects/-Users-linhuichen-code-trade/*.jsonl

# ② 枚举案例(解析 task-id)
python3 - <<'PY'
import json,re,os
proj=os.path.expanduser('~/.claude/projects/-Users-linhuichen-code-trade')
for f in [x for x in os.listdir(proj) if x.endswith('.jsonl')]:
    seen=set()
    for line in open(os.path.join(proj,f),errors='replace'):
        if 'background work of its own still running' in line:
            m=re.search(r'<task-id>([0-9a-f]{17})</task-id>',line)
            t=re.search(r'"timestamp":"([^"]+)"',line)
            if m and m.group(1) not in seen:
                seen.add(m.group(1)); print(f[:8],m.group(1),t.group(1) if t else '?')
PY

# ③ 判自恢复:该 agent 子转录里 ts 大于首次通知的记录数(>0=曾 resume)
#    (逐 agent 打开 <proj>/<sid>/subagents/agent-<id>.jsonl 比对 timestamp)

# ④ harness 行为取证(二进制 grep)
B=/Users/linhuichen/.nvm/versions/node/v25.8.0/lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe
python3 -c "
import re,sys
d=open('$B','rb').read().decode('utf-8','replace')
for k in ['background work of its own still running','function rzn(e){','keepaliveReasons','var Uus=','PC=30000']:
    ms=[m.start() for m in re.finditer(re.escape(k),d)]
    print(k,ms[:6])
"
```

## 附:诚实标注 / 未解项

1. **证据级别**:「存活任务具体是什么」仅 a71ca 一例实证(B 级推定用于 a9746102/acb76651/a5be21d0/a772ff1b;其余为 C 级类型统计)。原因是 3ba5f717 会话结束后其 `tasks/*.output` 已清理,只有 d08c47ab(当前会话)留有一份。
2. `rzn()` 里 `SX()` 的精确语义(混淆名)未展开,按行为推断为「bash: 计数开关」;不影响「keepalive 非空 ⇒ 停放」结论(③④⑤ 三处独立代码互相印证)。
3. **未解**:a5be21d0/a772ff1b 的确切终态(无 TaskStop、无后续提及;推测随会话进程结束被清)。
4. 「19 例自恢复后是否全部正常驱逐」按证据推断(无后续通知/无 TaskStop/转录正常结束),但无 harness 内部回执可证。
5. 分母边界:本统计只覆盖本项目两个会话文件;其他项目/其他机器未扫(口径边界,不作为全局比例)。
