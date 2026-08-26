# Claude ↔ Codex 信号驱动协作桥(agent-inbox watcher)

> 2026-08-26 落档。本文档描述 Claude 主控与 Codex 外部 reviewer 之间的**信号驱动自动协作链路**;协议细节(Request/Report JSON schema、ref 通道、写入与清理规范)见 [`docs/codex-collab-protocol.md`](codex-collab-protocol.md)。
>
> **运行形态(2026-08-26 起)**:watcher 已由 launchd 常驻部署(Label `com.trade.agent-inbox-watcher`,KeepAlive+RunAtLoad),带失败自动重试(≤3 次,间隔 5 分钟)与心跳文件可观测;详见 §6③ 与 §7 风险分析。

## 1. 一句话定位 + 为什么

**一句话**:用「文件信号 + 常驻 watcher」把 Claude↔Codex 协作从 cron 盲轮询升级成秒级信号触发——待机零模型调用(纯 sleep 循环,通讯层 0 token),有活才拉起 codex 干活。

**为什么要做这个**(2026-08-26 用户拍板):原来的模式是主会话设 cron 每隔几分钟轮询 `/tmp/codex-reports/`,平均延迟 7-8 分钟,cron 空转本身还占主会话注意力。现在改成双向文件信号:

- **Claude → Codex 方向**:主控发单后落 `.ready` 信号,watcher 2 秒内扫到,自动 `codex exec` 拉起外部 reviewer——人不在场也能开审。
- **Codex → Claude 方向**:codex 收工瞬间,`~/.codex/config.toml` 的 `notify` 回调推飞书 + 落 `.done` 信号;报告回传侧由 codex 自己调回传脚本落 claude-inbox 信号,watcher 自动做 schema 机检 + 推飞书——主控下次开工直接消费,**cron 从"主力"退化为"兜底"**。

## 2. 架构图

```
        ┌─────────────────────────── Claude 主控侧 ───────────────────────────┐
        │                                                                      │
        │  发单: echo '<json>' | bash scripts/codex-review-request.sh <id>      │
        │    ├─ [文件操作] stdin JSON 校验(必填字段+status+id一致性)              │
        │    ├─ [文件操作] 清场: rm 旧报告/旧信号(防同 id 旧报告误读)              │
        │    ├─ [git 操作] git update-ref refs/codex/req/<id> (request blob 入库)│
        │    └─ [文件操作] 原子写 /tmp/codex-reports/signals/codex-inbox/<id>.ready │
        └──────────────────────────────┬───────────────────────────────────────┘
                                       │ (.ready 文件)
                                       ▼
        ┌──────────────── agent_inbox_watcher.py(常驻,2s stat 轮询)────────────┐
        │  [纯进程,空闲零模型调用] .lock 防双开 / recover_processing 崩溃恢复     │
        │  ID_PATTERN 校验信号名(^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$ 防注入)     │
        │  心跳: 每轮 touch trade-data/data/logs/agent_inbox_watcher.heartbeat │
        │  信号状态机: ready → processing → done / failed / invalid            │
        │    失败且 retry_count<3 → 写回 .ready(+1,5 分钟后才能再消费)          │
        │    失败且 retry_count≥3 → .failed 终态 + 飞书放弃告警                 │
        └──────────────┬──────────────────────────────────┬───────────────────┘
                       │ codex-inbox 有 .ready             │ claude-inbox 有 .ready
                       ▼                                  ▼
        ┌────── Codex 侧(模型调用=花钱点①)──────┐   ┌── 回传机检侧(纯脚本,0 token)──┐
        │ [模型调用] codex exec --cd <repo>     │   │ [文件操作] bash                │
        │   --add-dir /tmp/codex-reports       │   │  scripts/codex-review-report.sh│
        │   --sandbox workspace-write          │   │  <id> → schema 必填字段校验     │
        │  固定 prompt: 先读 AGENTS.md+协议文档  │   └──────────────┬─────────────────┘
        │  → for-each-ref 扫 pending request    │                  │ PASS
        │  → 只读 review(base..head diff)      │                  ▼
        │  → 报告原子写(.tmp→mv rename)         │   ┌──────────────────────────────┐
        │    /tmp/codex-reports/<id>.json      │   │ [HTTP] notify.py send_feishu  │
        │  → 调 scripts/codex_review_complete.py│   │  → 飞书 agent_done 开发群     │
        │    [文件操作] 原子写 claude-inbox      │   │  "外部 review 回传,请消费..."  │
        │    signals/<id>.ready                 │   └──────────────┬───────────────┘
        └──────────────┬───────────────────────┘                  │
                       │ turn 结束                                 ▼
        ┌──── notify 回调(codex config.toml L40)──────────┐  ┌── Claude 主控消费 ──┐
        │ [文件操作+HTTP,0 token]                          │  │ [模型调用=花钱点②]   │
        │ scripts/codex_notify_bridge.py                   │◄─┴─读报告+逐条处置     │
        │  ①飞书 agent_done 群「[codex] turn 完成」          │   findings(必修/建议/  │
        │  ②落 /tmp/codex-reports/<thread_id>.done         │    运营拍板)           │
        └──────────────────────────────────────────────────┘
```

每一步标注了是**文件操作**(零 token)还是**模型调用**(本来就要花的干活 token)。全链路里只有两处花钱:codex exec 审查、Claude 处置 findings——都是协作本身的干活成本,不存在"为了等对方而烧 token"的环节。

## 3. 组件清单表

| 组件 | 路径 | 职责 | 谁触发 |
|---|---|---|---|
| 协作文档 | `docs/codex-collab-protocol.md` | ref 通道命名 / Request·Report JSON schema / 原子写与清理规范 / 安全约束(本文档的上游协议) | 双方开工先读 |
| 发单入口 | `scripts/codex-review-request.sh` | JSON 校验(含 status 字段)→ 清场(rm 旧报告+旧信号)→ 写 ref → 原子写 codex-inbox `.ready` 信号 | Claude 主控 |
| 收件箱 watcher | `scripts/agent_inbox_watcher.py` | 双 inbox 目录 2s 轮询;codex-inbox `.ready` → 拉起 codex exec;claude-inbox `.ready` → schema 机检+推飞书;失败自动重试(retry_count<3 写回 `.ready` 带 `next_retry_after=now+300`,≥3 次 `.failed` 终态+飞书放弃告警);`.lock` 防双开 / `recover_processing` 崩溃恢复 / `ID_PATTERN` 防注入 / 心跳文件每轮 touch | launchd 常驻(`com.trade.agent-inbox-watcher`)或手动启动 |
| codex 项目级指令 | `AGENTS.md`(仓库根) | codex 进会话先自查 `refs/codex/req` 待办 → 处理 → 报告原子写 → 调回传脚本 → **收工即走不等确认** | codex exec 启动时自动读 |
| codex reviewer 角色 skill | `.agents/codex-reviewer/SKILL.md` | codex 的铁律+反幻觉规则+输出契约(AGENTS.md 第一步指向它) | codex exec 启动时自动读 |
| notify 回调桥 | `scripts/codex_notify_bridge.py` | codex 每次 turn 结束被回调:①飞书 agent_done 群推收工通知 ②落 `/tmp/codex-reports/<thread_id>.done` 信号(原子写);只在 cwd 含 "trade" 时推飞书 | `~/.codex/config.toml` L40 `notify = [...]`,codex 自动调 |
| 回传信号脚本 | `scripts/codex_review_complete.py` | 校验报告可解析且 `request_id`/`verdict` 与参数一致 → 原子写 `/tmp/codex-reports/signals/claude-inbox/<id>.ready` | Codex(每份报告完成后) |
| 报告机检脚本 | `scripts/codex-review-report.sh` | Report JSON 七个必填字段校验(request_id/verdict/summary/issues/impact_surface/smoke_results/recommendation)+ 摘要打印 | watcher(claude-inbox 侧)/ 主控手动 |
| plist(已部署) | `launchd/com.trade.agent-inbox-watcher.plist` | watcher 常驻配置(Label `com.trade.agent-inbox-watcher`,KeepAlive+RunAtLoad,`CODEX_BIN` 环境变量给 codex 绝对路径——launchd 环境 PATH 不含 nvm,不给就找不到 codex;日志指 trade-data 树)。已拷入 `~/Library/LaunchAgents/` 并 bootstrap 加载 | launchd(开机自启+挂了自动拉活) |
| 心跳文件 | `/Users/linhuichen/code/trade-data/data/logs/agent_inbox_watcher.heartbeat` | watcher main 循环每轮 touch;**人工存活检查**:`stat -f "%Sm" <该文件>`,mtime 距今超过 10 分钟 = 僵死(正常 2 秒一跳) | watcher 自动写 / 人或监控读 |
| 报告归档目录 | `docs/review/`(如 `docs/review/codex-rev-20260826-001-kelly-param-bar.json`)、`docs/codex-reviews/` | /tmp 易失,重要报告按协议归档进 git(示例 commit 12ee0b378) | Claude 主控 |

## 4. 0 token 分析

核心设计:**通讯层全部用文件系统信号,不用任何模型调用传话**。

| 环节 | 模型调用? | 说明 |
|---|---|---|
| watcher 待机 | **否** | 就是 `while True: 扫描 + time.sleep(POLL_SECONDS=2)` 的循环,纯文件 stat,CPU 可忽略、token 为 0。没信号的每一秒都是免费的 |
| 发单(request.sh) | 否 | bash + python3 json.load 校验,纯脚本 |
| codex exec 审查 | **是(花钱点①)** | 但这是 review 本身的干活 token,不管用什么方式派活都得花 |
| codex notify 回调 | 否 | `codex_notify_bridge.py` 明确不调任何 LLM,内容取 payload 截断摘要 |
| 回传信号(complete.py) | 否 | 纯文件写 |
| watcher 机检+飞书 | 否 | report.sh 纯 json.load 校验;send_feishu 是 HTTP |
| Claude 处置 findings | **是(花钱点②)** | 主控读报告做必修/建议/拍板分类——同样是协作本来的成本 |

结论:**相比 cron 盲轮询方案,这套链路新增的模型成本为零**;省掉的反而是原来 cron 每次唤醒主会话扫一眼的开销和 7-8 分钟延迟。

## 5. 完整生命周期时序(以一次真实 review 为例)

以 2026-08-26 移动端凯利参数栏修复的外部 review(`rev-20260826-001`,报告已归档 commit `12ee0b378`)为原型:

1. **主控发单**(内部 reviewer 已 PASS 后)。执行:
   `echo '<request json>' | bash scripts/codex-review-request.sh rev-20260826-001`
   脚本校验必填字段(request_id/repo/base/head/task_type/requirement/status)、status 取值(pending|processing|completed)、JSON 内 id 与参数一致;然后清掉同名旧报告与旧信号,`git update-ref refs/codex/req/rev-20260826-001` 立 ref,最后原子写 `signals/codex-inbox/rev-20260826-001.ready`。
2. **watcher 秒级接单**(≤2s)。扫到 `.ready` → `ID_PATTERN` 校验信号名 → rename 成 `.processing`(状态机推进)→ 读出 request_id → `dispatch_codex`:拉起 `codex exec --cd /Users/linhuichen/code/trade --add-dir /tmp/codex-reports --ephemeral --sandbox workspace-write`,带固定指令(先读 AGENTS.md 和协议文档,再扫 refs/codex/req 下所有 pending request)。注意:**watcher 把固定指令拼好,信号内容不进模型指令**(防注入)。
3. **Codex 自查开工**(模型调用开始)。按 AGENTS.md:`git for-each-ref refs/codex/req` 发现 ref → `git cat-file blob` 读 request JSON(status=pending 的是新活)→ 按 `base..head` diff + `focus_areas` 执行只读 review(影响面 grep / smoke 验证 / 口径交叉核对),角色铁律见 `.agents/codex-reviewer/SKILL.md`(不信自验报告、真跑命令、进度写 `/tmp/codex-reports/<id>-progress.md`)。
4. **报告原子写**。codex 把结果写成七字段 Report JSON:先写 `<id>.json.tmp`,再 mv 成 `<id>.json`——杜绝主控读到半成品。
5. **回传信号**。codex 对每份完成的报告执行:
   `python3 scripts/codex_review_complete.py rev-20260826-001 --verdict PASS`
   脚本校验报告可解析、`request_id` 与 `--verdict` 和报告内容一致,然后原子写 `signals/claude-inbox/rev-20260826-001.ready`。
6. **watcher 机检**。claude-inbox 的 `.ready` 被扫到 → 转 processing → 跑 `bash scripts/codex-review-report.sh rev-20260826-001` 做七个必填字段的 schema 机检 → 通过则信号转 `.done` 并推飞书;失败转 `.failed`。
7. **飞书通知**(人不在场也可见)。watcher 调 `notify.py send_feishu(..., chat_key="agent_done")` 到开发群:「外部 review 回传,报告已通过 schema 校验」。同时 codex turn 结束瞬间,notify 回调(`codex_notify_bridge.py`)也会推一条「[codex] turn 完成」+ 落 `<thread_id>.done` 信号——两条通道互为印证。
8. **主控消费处置**(模型调用恢复)。主控下次开工看到飞书/信号,读 `/tmp/codex-reports/rev-20260826-001.json`,逐条处置 issues(必修/建议/运营拍板),把重要报告归档进 `docs/review/` 或 `docs/codex-reviews/`(本次实例即 commit `12ee0b378`),可选 `git update-ref refs/codex/resp/<id>` 标记 consumed,双方都过则走 `scripts/main-merge.sh` 合并。

全程只有第 3 步和第 8 步花模型 token,其余全是文件操作。

## 6. 配制方法(从零复现)

### ① ~/.codex/config.toml 加 notify 行

```toml
notify = ["python3", "/Users/linhuichen/code/trade/scripts/codex_notify_bridge.py"]
```

现状即此配置(L40)。生效后 codex 每次 turn 结束会以 JSON 作为最后一个 argv 参数调用该脚本(`{"type":"agent-turn-complete","thread_id":"...","cwd":"...","input_messages":[...],"last_assistant_message":"..."}`)。手动测试:

```bash
python3 scripts/codex_notify_bridge.py '{"type":"agent-turn-complete","thread_id":"test-1","cwd":"/tmp","input_messages":["hi"],"last_assistant_message":"done"}'
# cwd=/tmp 不含 trade → 只落信号不发飞书;ls /tmp/codex-reports/test-1.done 应存在
```

### ② AGENTS.md 放仓库根

`AGENTS.md` + `.agents/codex-reviewer/SKILL.md` 必须在仓库根/对应路径(a24187809 已提交)。codex CLI 约定自动读仓库根 `AGENTS.md` 作为项目级指令;watcher 的 dispatch prompt 里也显式要求先读它,双保险。

### ③ watcher 启动(已用 launchd 常驻)

手动启动(临时/调试用):

```bash
CODEX_BIN=$(which codex) python3 /Users/linhuichen/code/trade/scripts/agent_inbox_watcher.py
# 日志: /tmp/codex-reports/agent-inbox.log;重复启动会被 .lock 拦下退出
```

launchd 常驻(**2026-08-26 已部署**,配置在 `launchd/com.trade.agent-inbox-watcher.plist`,已拷入 `~/Library/LaunchAgents/` 并 bootstrap 加载):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
        <!-- launchd 环境 PATH 不含 nvm,watcher 的 os.environ.get("CODEX_BIN", "codex") 必须给绝对路径 -->
        <key>CODEX_BIN</key>
        <string>/Users/linhuichen/.nvm/versions/node/v25.8.0/bin/codex</string>
    </dict>
    <key>Label</key>
    <string>com.trade.agent-inbox-watcher</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>/Users/linhuichen/code/trade/scripts/agent_inbox_watcher.py</string>
    </array>
    <key>KeepAlive</key>
    <true/>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/Users/linhuichen/code/trade-data/data/logs/agent_inbox_watcher_launchd.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/linhuichen/code/trade-data/data/logs/agent_inbox_watcher_launchd.err</string>
</dict>
</plist>
```

三个关键点:①**`CODEX_BIN` 必须给 codex 绝对路径**(本机 codex 装在 nvm 目录 `~/.nvm/versions/node/v25.8.0/bin/codex`,launchd 环境 PATH 短,不设这个 watcher 拉起 codex 会 spawn 失败——部署实测踩过);②日志指 `/Users/linhuichen/code/trade-data/data/logs/`(项目日志统一在 trade-data 树的既有约定,不受 macOS 清 /tmp 影响);③`KeepAlive=true` 挂了自动拉活(实测 kill 后 10 秒内新 pid),`RunAtLoad=true` 开机即启。

部署/更新命令(macOS 新式 bootstrap;改了 plist 必须 bootout 再 bootstrap 才重读,`kickstart -k` 不读新配置):

```bash
cp launchd/com.trade.agent-inbox-watcher.plist ~/Library/LaunchAgents/
launchctl bootout gui/$UID/com.trade.agent-inbox-watcher 2>/dev/null   # 若已在跑先卸
launchctl bootstrap gui/$UID ~/Library/LaunchAgents/com.trade.agent-inbox-watcher.plist
launchctl list | grep agent-inbox-watcher                              # 应看到 pid + exit 0
tail /tmp/codex-reports/agent-inbox.log                                # 应见 "watcher started"
```

**加载前检查**:确认无手动 watcher 实例(`pgrep -fl agent_inbox_watcher` 无输出、无 `.lock` 残留),否则 `.lock` 冲突新实例起不来。

**存活可观测(心跳文件)**:watcher main 循环每轮 touch `/Users/linhuichen/code/trade-data/data/logs/agent_inbox_watcher.heartbeat`,人工检查方法:

```bash
stat -f "%Sm  %N" /Users/linhuichen/code/trade-data/data/logs/agent_inbox_watcher.heartbeat
# mtime 距今超过 10 分钟 = watcher 僵死(正常 2 秒一跳)
```

注意一个判读细节:watcher 干活期间(同步等 codex exec 跑完)心跳会暂停——这是单线程主循环的设计,不是僵死。区分方法:心跳停但 `pgrep -fl "codex exec"` 有进程 = 正在干活;心跳停且无 codex exec 进程、`/tmp/codex-reports/agent-inbox.log` 也无新增行 = 真僵死(此时 launchd KeepAlive 通常已先一步拉活)。

### ④ 端到端验证(test request 全链路)

```bash
cd /Users/linhuichen/code/trade
# 前置:watcher 已在跑(tail 上面的日志确认 "watcher started")
echo '{"request_id":"test-001","timestamp":"'"$(date +%FT%T%z)"'","status":"pending",
"repo":"/Users/linhuichen/code/trade","base":"main","head":"main",
"task_type":"review","change_class":"A","requirement":"端到端连通性测试:只回复无待处理 request 即收工,不要改任何东西",
"focus_areas":["连通性测试"],"internal_reviewer_verdict":"PASS","notes":"e2e test"}' \
  | bash scripts/codex-review-request.sh test-001

# T+2s:tail watcher 日志应见 exec ... exit=0 与 codex_completed request_id=test-001
tail -f /tmp/codex-reports/agent-inbox.log

# codex 侧按 AGENTS.md 会发现无 pending(ref 已被它处理或它判定无需产出),验证点:
#   a) codex-inbox/test-001 从 .ready 变成 .done(watcher 拉起成功)
#   b) codex turn 结束后 /tmp/codex-reports/<thread_id>.done 出现(notify 回调通了)+ 飞书收到「turn 完成」
#   c) 若造一份合规报告再跑 codex_review_complete.py,则 claude-inbox/test-001.ready 出现 →
#      watcher 机检通过 → 飞书收到「外部 review 回传」,信号转 .done —— 全链路闭合
python3 scripts/codex_review_complete.py test-001 --verdict PASS   # 步骤 c 手动模拟
# 收尾清理(7 天保留期约定之外的测试产物随手清):
git update-ref -d refs/codex/req/test-001; rm -f /tmp/codex-reports/test-001.json* /tmp/codex-reports/signals/*/test-001.*
```

## 7. 利弊诚实分析

**利**

1. **秒级响应**:watcher 2 秒轮询,vs 原 cron 盲轮询平均 7-8 分钟延迟;codex 收工→飞书到手机是秒级。
2. **通讯层零 token**:待机纯 sleep 循环零模型调用;传话全靠文件信号,不为"等对方"烧一分钱(§4 全表)。
3. **双向自动化闭环**:发单→审查→回传→机检→通知全自动,人不在场也能完成一轮外部 review,回来只看结论。
4. **工程完备**:崩溃恢复(`recover_processing`:启动时把遗留 `.processing` 还原成 `.ready` 重跑,部署实测 kill 后生效)、防双开(`.lock` O_EXCL + 存活 pid 探测)、防注入(`ID_PATTERN` 正则校验信号名,固定 prompt 不拼信号内容)、原子写(tmp→rename)贯穿全链路、launchd KeepAlive 常驻保活(实测 kill 后 10 秒内拉活)。

**弊与风险**

1. **watcher 挂了链路就断(已有缓解,监控兜底待接)**。launchd KeepAlive 已上线(实测 kill 进程 10 秒内自动拉活),心跳文件可人工查存活;但现有 `schedule_monitor` **没有覆盖它**(grep schedule_monitor.sh 无 agent-inbox/codex 相关检查),自动化监控告警**待接**(trade-data 树的 schedule_monitor 改动另行走批,不在本次范围)。当前兜底=KeepAlive 自动拉活 + 心跳 mtime 人工检查。
2. ~~失败无重试~~ → **已缓解(2026-08-26)**:失败不再直接落 `.failed` 终态,而是读信号 JSON 的 `retry_count`(payload 无则视为 0),<3 次 → 原子写回 `.ready`(retry_count+1、记 `last_failed_at`、带 `next_retry_after=now+300` 5 分钟冷却,主循环扫到未到期的 `.ready` 直接跳过,防疯转);≥3 次 → 落 `.failed` 终态 + 飞书 agent_done 群放弃告警(request_id+已重试3次放弃)。重试耗尽仍需人工看 `/tmp/codex-reports/agent-inbox.log` 定位后换新 id 重发。
3. **依赖 /tmp,易失**:macOS 重启会清 `/tmp`,信号与报告都不持久。重要报告必须及时归档进 git(`docs/review/`、`docs/codex-reviews/`,12ee0b378 是范例);ref 在 git 里不怕丢,但报告文件丢了就得让 codex 重审。(watcher 自身日志与 launchd 日志已在 trade-data 树,不受此影响。)
4. **沙箱内 DNS 受限时飞书发送会被跳过**:codex workspace-write 沙箱内实测网络受限时,`send_feishu` 异常只打日志不阻断(设计如此,notify 失败绝不反噬 codex;2026-08-26 实例 rev-20260826-001 曾因此失败过一次,该失败现在会走 §7.2 的自动重试)。表现为"codex 干完活了但没收到飞书"——以 `.done` 信号和报告文件为准,飞书只是增强通知。
5. **POLL_SECONDS=2 的轮询是文件 stat 级别**:不是 inotify 事件推送,理论上有 ≤2s 感知延迟;但 stat 循环 CPU 占用可忽略,不构成实际负担。

## 8. 已知边界与 FAQ

**Q1:ref 队列怎么管理?**
`git for-each-ref refs/codex/req` 就是待办队列。处理完成后 ref 可保留审计,也可 `git update-ref -d refs/codex/req/<id>` 清理;过期(建议 7 天)由 Claude 主控负责清理。当前队列实况可用这条命令随时查看。

**Q2:同 id 能重跑吗?**
能,但有规则:必须换新 id,或确认走 `codex-review-request.sh` 重发(脚本②会自动 rm 旧报告+旧信号,保证 ref 出现时绝无旧报告残留)。**禁止**直接依赖残留的旧报告当本次结果——这是协议补的最危险缺口(旧完整报告可解析、最易误读)。

**Q3:信号状态机各态含义?**
`.ready`=待消费;watcher 取货时 rename 成 `.processing`(正在干);成功转 `.done`;失败且 `retry_count<3` 写回 `.ready`(带 `next_retry_after`,5 分钟冷却后再试);失败重试耗尽(≥3 次)转 `.failed` 终态并触发飞书放弃告警;信号名/内容不合规格转 `.invalid`(终态,不重试)。同名冲突时追加计数器(`.done.1`)不覆盖。崩溃恢复:下次启动把遗留 `.processing` 还原成 `.ready` 重跑。

**Q4:信号文件里是什么内容?会不会变成注入载体?**
只是元数据 JSON(如 `{"request_id":"rev-xxx"}`),**不承载可执行 prompt**。信号名必须匹配 `^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$`,watcher 用固定指令调 CLI,禁止把信号内容拼进模型指令(协议⑤)。

**Q5:报告在 /tmp 会丢,怎么保证不白干?**
两层:①协议④约定 ref 与报告建议保留 7 天、由主控负责清理;②重要报告当场归档进 git——`docs/review/`(如 `docs/review/codex-rev-20260826-001-kelly-param-bar.json`)或 `docs/codex-reviews/`。归档前 /tmp 丢失只能重审,这是接受的成本(换来零部署成本的轻量通道)。

**Q6:.done 信号(`<thread_id>.done`)和 claude-inbox 信号什么关系?**
两条并行通道:`<thread_id>.done` 由 notify 回调落,代表"codex 这个 turn 结束了"(粒度是会话);claude-inbox `.ready` 由 `codex_review_complete.py` 落,代表"某份报告正式交付了"(粒度是请求)。前者偏通知,后者驱动 watcher 机检+飞书提醒,主控消费以后者为准。

**Q7:重试期间怎么知道一个信号正在冷却?**
看 `.ready` 文件内容:`retry_count`(已失败次数)、`last_failed_at`(上次失败时间)、`next_retry_after`(unix 时间戳,到期前 watcher 跳过不消费)。人工想立即重试可手动把 `next_retry_after` 改成过去的时间戳,或直接换新 id 重发。

**已知边界**:①schedule_monitor 尚未接入 watcher 心跳检查(自动化监控告警待办,trade-data 树改动另行走批),当前存活兜底=launchd KeepAlive 自动拉活+心跳 mtime 人工检查;②协议文档 §「写入与清理规范」⑥仍写着"watcher 只在需要协作时由用户手动启动、com.trade.agent-inbox.plist 仅是可选模板默认不入 LaunchAgents",此描述已被 2026-08-26 的常驻部署取代,以本文档为准(协议文档下次随协议修订同步)。

---

## 关联

- 上游协议(Request/Report schema、清理规范):[`docs/codex-collab-protocol.md`](codex-collab-protocol.md)
- codex 侧角色规范:[`.agents/codex-reviewer/SKILL.md`](../.agents/codex-reviewer/SKILL.md)
- 相关 commit:a24187809(signal-triggered review handoff,链路固化)、12ee0b378(报告归档范例)
