# 飞书机器人接入方案（调研落档 + 实施结果）

> 状态：调研 + 实施完成（2026-08-11）。阶段 1 发送 + 阶段 2 接收均已落地并实测。
> 调研日期：2026-08-11；实施日期：2026-08-11（commit 见 git log docs/feishu-bot-integration-plan.md）。
> 说明：本环境 WebSearch/WebFetch 被网络策略拦截（open.feishu.cn/github.com 均无法抓取），
> 以下基于对飞书开放平台既有能力的知识撰写，**实测为准**。文中权限名/API 名以实际调用成功为准。
> 用户已完成平台配置：自建应用已建（凭证存 trade-data/.env 的 FEISHU_APP_ID/FEISHU_APP_SECRET）+
> 已建 3 群并拉应用进群 + 权限/发布/事件订阅长连接已配好。

---

## §一 现有通知链路盘点

### 1.1 notify.py 接口（scripts/notify.py，单文件，~470 行）

**统一出口**：所有脚本（shell + python）都调 `scripts/notify.py` CLI 或 `import notify` 函数，
是唯一的多渠道通知出口（邮件 + Telegram + alerts 文件）。

**CLI 接口**（`python scripts/notify.py <subject> [<body>] [flags]`）：

| 参数 | 作用 |
|---|---|
| `subject` / `body` | 主题 / HTML 正文 |
| `--severe` | 严重标记。2026-07-20 后**不再改 subject 前缀**（前缀由调用方在 subject 里写 `[告警]`），仅用于"是否写 data/alerts/latest.md"语义 |
| `--alert-issue <issue>` | 写 `data/alerts/latest.md`（最新严重告警，供下轮 Claude 开工优先排查） |
| `--alert-log <path>` | 配合 alert-issue 记录日志路径 |
| `--agent-done <name>` | agent 完成通知模式：subject=结论摘要，直发用户绕过主控队列，5min 去重（dedup_key=`agent_done_<name>`） |
| `--dedup-key / --dedup-window` | 去重：同 key 在 window 秒内不重发（写 `data/notify_dedup.json`，独立于 schedule_monitor 的 alert_state.json） |
| `--from-prefix` | 邮件发件人名前缀（`[告警]` → "From: [告警] 信号实验室"） |
| `--dry-run` | 不真发，只 print 到 stderr（自验用） |

**Python 函数接口**（被 `import notify` 直接调用）：

| 函数 | 用途 |
|---|---|
| `send(subject, body, severe, from_prefix)` | 多渠道分发（邮件+Telegram），各渠道独立失败不互相阻塞，返回 `{"email":bool,"telegram":bool}` |
| `send_to(subject, body, email, chat_id)` | A12 订阅推送：指定收件人（SMTP user/密码、bot_token 仍用 config 全局） |
| `send_telegram` / `_send_email` | 单渠道发送 |
| `write_alert(issue, detail, log_path)` | 覆盖式写 data/alerts/latest.md |
| `check_dedup / update_dedup` | 跨进程去重（写 data/notify_dedup.json） |
| `notify_agent_done(name, summary)` | agent 完成通知（直发用户，绕过主控消息队列） |

**配置方式**（全部 gitignore，用 `.example` 模板，敏感信息不进 git）：

- `config/email.json`：`smtp/port/user/password/to`（163 SMTP SSL）
- `config/telegram.json`：`bot_token/chat_id/api_base`（国内 GFW 不可达时 api_base 设 CF Workers 反代）
- `.env`（trade/ 与 trade-data/ 各一份，gitignore）：`PURGE_SECRET` / `DEEPSEEK_*` / `GITHUB_TOKEN` 等

**已实现渠道**：①邮件（SMTP）②Telegram（Bot API，可 CF 反代）③本地 alerts/latest.md 文件。
无 webhook 类渠道；Telegram 已能"发到指定 chat_id"（send_to），与本方案飞书分组思路同构。

### 1.2 notify.py 全部调用点清单（grep 全仓）

按用途分三类，重点标注**SEVERE 告警类 / agent 完成类 / 正常节点类**。

#### A. SEVERE 告警类（生产异常，`--severe` 或带 alert-issue）

| # | 调用点（脚本:行） | 用途 | 频率 | 去重 |
|---|---|---|---|---|
| 1 | update_all.sh:231 | `[告警] update_all` 严重（耗时>1h/core rc!=0/数据时效异常） | 每日 17:50 | 无 |
| 2 | intraday_snapshot.sh:135 | `[告警] intraday R2上传失败`(upload-index) | 盘中每 10min | dedup 1800s |
| 3 | intraday_snapshot.sh:146 | `[告警] intraday R2上传失败`(upload-intraday) | 盘中每 10min | dedup 1800s |
| 4 | intraday_snapshot.sh:191 | `[告警] intraday schedule_stats R2上传失败` | 盘中每 10min | dedup 1800s |
| 5 | monitor_72h.sh:814 | `[72h监控] N项异常` | 每 30min | 无（alert_state 去重上游） |
| 6 | schedule_monitor.sh:909 | `[告警] N项计划任务异常` | 每 15min | 无（alert_state 去重上游） |
| 7 | push_schedule_stats.sh:58 | `[告警] schedule_stats R2上传失败` | 定时 | dedup 1800s |
| 8 | deploy.sh:268 | `[告警] deploy R2上传失败` | deploy 时 | dedup 1800s |
| 9 | deploy.sh:553 | `[告警] staticdata备份失败` | deploy 时 | dedup 1800s |
| 10 | self_heal.sh:131 | `[告警] 自愈脚本达每日上限停止` | 每日达上限时 | 无 |
| 11 | verify_backup.sh:84 | `[告警] verify_backup R2下载失败` | 定时 | 无 |
| 12 | verify_backup.sh:202 | `[告警] verify_backup 校验失败` | 定时 | 无 |
| 13 | backup_db.sh:115 | `[告警] backup_db rc!=0 备份失败` | 每日备份时 | 无 |
| 14 | uptime_check.sh:69 | `[告警] 线上探活异常` | 定时 | 无 |
| 15 | gold_night.sh:42 | `[告警] gold_night 采集失败` | 每日 2:40 | dedup 3600s |
| 16 | gold_night.sh:69 | `[告警] gold_night R2上传失败` | 每日 2:40 | dedup 3600s |
| 17 | update_lab.sh:286 | `[告警] update_lab R2上传失败`(upload-lab) | 每日 19:00 | dedup 1800s |
| 18 | update_lab.sh:303 | `[告警] update_lab trade_sim R2上传失败` | 每日 19:00 | dedup 1800s |
| 19 | update_lab.sh:322 | `[告警] update_lab lab_json R2上传失败` | 每日 19:00 | dedup 1800s |
| 20 | on_skip_notify.sh:17 | `[告警] update_all 锁跳过`（with_lock --on-skip） | 撞锁时 | 无 |
| 21 | upload_r2.py:~611 | `[告警] PURGE_SECRET未设 cache purge跳过` | 进程一次 | 进程内 once |
| 22 | upload_r2.py:~688 | `[告警] Cache purge部分失败` | deploy 一次 | dedup 1800s |

#### B. agent 完成类（--agent-done / notify_agent_done）

| # | 调用点 | 用途 | 频率 |
|---|---|---|---|
| 23 | notify.py `notify_agent_done()`（CLI `--agent-done`） | agent 完成通知，绕过主控消息队列直发用户 | **仓库内无脚本调用**，由 agent 完成时按 §16 手动/在 agent prompt 中调用（重要节点才发：上线完成/生产异常/需用户介入） |

> 注：`--agent-done` 调用点在仓库外（harness/主控侧的 agent 完成动作），仓库内 grep 不到脚本调用者，
> 这是本方案"agent 完成切飞书"要改造的核心入口。

#### C. 正常节点 / 恢复 / 信号推送类（非 severe）

| # | 调用点 | 用途 | 频率 |
|---|---|---|---|
| 24 | update_all.sh:233 | `[完成] update_all` 每日完成通知 | 每日 17:50 |
| 25 | update_all.sh:246 | `[告警] 情绪速递邮件失败`（仅 from-prefix，无 --severe） | 每日 |
| 26 | schedule_monitor.sh:942 | `[恢复] 异常恢复` | 每 15min（恢复时） |
| 27 | monitor_72h.sh:847 | `[72h恢复] 异常恢复` | 每 30min（恢复时） |
| 28 | monitor_72h.sh:43 | `[72h监控] 到期停止` | 每 72h 一轮到期 |
| 29 | detect_intraday_anomaly.py（intraday_snapshot.sh:173 驱动） | `[盘中异动]` 盘中提示（非 severe） | 盘中 30min 节奏 |
| 30 | check_signals.py:1261 | 买卖点信号 `notify.send` | 信号触发时 |
| 31 | check_signals.py:377 | 订阅推送 `notify.send_to`（指定 email/chat_id） | 信号触发时 |
| 32 | check_nt_signals.py:344 | 买卖点信号 `notify.send` | 信号触发时 |
| 33 | run_daily_brief.sh:36 | `[告警] daily_brief 生成失败`（无 --severe） | 每日 | dedup 1800s |
| 34 | gen_daily_brief.py:1010 | `[告警] daily_brief 月度费用超阈值` | 每日 | 无 |

**调用方式分布**：shell 脚本走 CLI（22 处），python 脚本走 `import notify` 函数（check_signals / check_nt_signals / upload_r2 / detect_intraday_anomaly）。**绝大多数（22/34）都走 `notify.py` CLI 这一个入口** → 改造飞书渠道只需集中在 notify.py，调用点基本不用动。

### 1.3 现有通知机制定位（CLAUDE.md §11/§16）

- 当前机制四层：cron 兜底为主 + SendMessage/task-notification 补充（不可靠，~1.9%/~12% 送达率）+ 进度文件 DONE + **notify.py 邮件只重要节点**（上线完成/生产异常/需用户介入），非每 agent 完成。
- harness 架构硬限制：无"子 agent 完成结论可靠送达主控 session"的完美主动通知方案；cron 兜底是架构限制下最优残余。
- 现状偏差：实际调用点远多于"只重要节点"（34 处，含每日完成/恢复/信号推送），邮件承载了告警 + 正常节点 + agent 完成三类。
- **飞书群消息是"主动 push"渠道，不依赖 harness 消息队列** → 与 cron 兜底互补，能显著改善"agent 完成/告警被主控看到"的时效与可靠性；接收链路（需求提报）补上"用户 → 主控"的入向通道，正好填补 harness 无可靠入向通知的结构空白。

---

## §二 飞书接入方案

### 2.1 发送链路：两种能力对比

| 维度 | 自定义机器人（群 webhook） | 企业自建应用（im.message API） |
|---|---|---|
| 创建 | 群设置 → 群机器人 → 自定义机器人，每群一个 | 开放平台 → 开发者后台 → 创建企业自建应用 |
| 凭证 | 每群一个 webhook URL（`https://open.feishu.cn/open-apis/bot/v2/hook/<token>`） | 一个 App ID + App Secret → 换 `tenant_access_token` |
| 发送 API | `POST {webhook}`，body `{"msg_type":"text","content":{"text":"..."}}`，无需鉴权头 | `POST /open-apis/im/v1/messages?receive_id_type=chat_id`，Header `Authorization: Bearer <tenant_access_token>` |
| 能否接收 | **不能收**（无事件订阅，只能发） | **能收能发**（事件订阅 im.message.receive_v1） |
| 分组 | 天然按群（webhook 即绑定该群），0 chat_id 管理 | 按 chat_id 分发，可发任意群/用户；需应用进各群 + 拿各群 chat_id |
| 富文本 | 支持 text/interactive(卡片) | 支持 text/post/interactive(卡片)/@ 成员 |
| 频率限制 | 较严（单机器人限流，防轰炸需去重） | 较宽（tenant 级 API 限流） |
| 维护成本 | 每群一个 URL，泄漏需逐群重建；无集中管理 | 一套凭证集中管理；需要 app 进群 + 一次性拿 chat_id |

**推荐：主用"统一自建应用（收发一体）"**，理由：
1. **接收需求必须自建应用**（自定义机器人不能收）——应用反正要建，发送顺带用同一个应用，只多申请发消息权限，省去维护 N 个 webhook。
2. **分组用 chat_id**：3 个群 → 一个应用进 3 个群，配置文件里 3 个 chat_id，比 3 个 webhook URL 更整洁、更安全（token 集中一处）。
3. 应用 API 支持富文本卡片 + @成员，告警展示更好；限流更宽，适配 intraday 每 10min 的告警节奏。
4. 唯一额外成本（拿 chat_id）是**一次性**操作：应用进群后在群里发一条消息，从接收事件 payload 或监听日志里读 `chat_id`（`oc_` 开头）即可。

**降级/快速起步路径（可选，阶段 1 发送用）**：若想先不建应用快速验证发送链路，用自定义机器人（告警群 + agent 完成群各一个 webhook）。webhook 发送零权限零审批，10 分钟能通；阶段 2 建应用后再统一到应用发送。两条路径的 notify.py 改造点相同（都是加一个 feishu 渠道），只是 channel 实现不同（webhook POST vs 应用 API），可平滑切换。

### 2.2 接收链路：长连接模式（推荐，免公网回调）

飞书自建应用收消息两种事件订阅架构：

| 维度 | 长连接模式（WebSocket） | Webhook 回调模式 |
|---|---|---|
| 公网要求 | **免公网回调地址**（应用主动连飞书 WS，事件经长连接推送） | 需公网可访问的 HTTPS 回调地址（飞书验证 URL 后推送事件） |
| 本机落地 | 本机常驻 python 进程（lark-oapi WS Client）+ launchd KeepAlive 即可 | 本机无公网需内网穿透（cloudflared/ngrok）或 CF Worker/云函数中转，维护复杂 |
| 可靠性 | SDK 自带断线重连；进程崩溃靠 launchd 拉起 | 依赖穿透隧道稳定性 |
| 推荐 | ✅ **推荐** | ❌ 本机场景不推荐 |

**落地架构（长连接）**：
1. 新增常驻进程 `scripts/feishu_listener.py`：`pip install lark-oapi` 装进 `.venv`（python3.11）。
2. 用 `lark_oapi.ws.Client(app_id, app_secret, event_handler=...)`（旧版本路径 `lark_oapi.ws`，新版本 `lark_oapi.adapter.ws`，以安装版本 API 为准）注册 `im.message.receive_v1` handler（`register_p2_im_message_receive_v1`）。
3. handler 处理逻辑：
   - **过滤**：只处理需求提报群（白名单 chat_id）的消息；再按"@机器人 或 前缀（如 `需求:` / `t:`）"过滤，防群里闲聊误触发。
   - **落盘**：合法需求 append 到 `data/feishu_requests/<ts>.json`（runtime 数据，不进 git，同 alert_state.json 策略）+ 更新 `data/feishu_inbox.jsonl` 尾部标记。
   - **回执**（可选）：调发送 API 回一条"已收到，已记入待办"。
   - **告警自愈**：监听进程异常/断线超时 → 调 notify.py 告警（复用现有告警链路）。
4. **转给主控**（关键，绕过 harness 消息队列不可靠问题）：
   - 方式 A（推荐）：新增/复用 cron 兜底，每 15min 扫 `data/feishu_requests/` 新文件 → 把需求**整理追加进 TASKS.md 待办（git 落档，持久化）** → 标记 consumed。主控每次开工/compact 恢复读 TASKS 即看到需求。这也符合 §7"任何事默认持久化落 git"。
   - 方式 B（补充）：主控开工时直接 Read `data/feishu_inbox.jsonl` 最新条目。
   - 方式 C（即时提醒）：需求新到时调用发送 API 往 agent 完成群 @ 发一条"新需求已入待办"，让用户知道已接收、也让主控侧有痕迹。
5. launchd 常驻：新建 `com.trade.feishu-listener.plist`，`KeepAlive: true`，日志进 `trade-data/data/logs/`（与现有 launchd 任务一致）。

### 2.3 分组设计（3 群）

| 群 | chat_key | 内容 | 发/收 |
|---|---|---|---|
| 告警群 | `alert` | 生产异常/SEVERE（§一 A 类 22 处） | 只发 |
| agent完成群 | `agent_done` | agent 完成通知（--agent-done）+ 完成/恢复节点（可选并入） | 只发 |
| 需求提报群 | `request` | 用户给主控提需求（接收 + 回执） | 只收（+回执发） |

- 也可合并为 2 群（告警+agent完成 合一、需求独立），配置文件里映射表可调。
- 配置放 **`config/feishu.json`**（gitignore + `config/feishu.json.example` 模板，复用 email.json/telegram.json 模式）：

```json
{
  "_help": "飞书配置。app_id/app_secret 从开放平台开发者后台拿。chat_ids 的 chat_id 获取：应用进群后发一条消息，从监听日志读 oc_ 开头 id。webhook_urls 为阶段1自定义机器人备用（每群一个）。",
  "app_id": "cli_xxx",
  "app_secret": "xxx",
  "enabled": true,
  "chat_ids": { "alert": "oc_xxx", "agent_done": "oc_yyy", "request": "oc_zzz" },
  "webhook_urls": { "alert": "", "agent_done": "" },
  "receive": {
    "chat_id_whitelist": ["oc_zzz"],
    "keyword_prefixes": ["需求:", "t:"],
    "inbox_dir": "data/feishu_requests"
  }
}
```

- 也可改放 `.env`（`FEISHU_APP_ID` / `FEISHU_APP_SECRET`），但群映射是结构化数据，`config/feishu.json` 更合适（.env 适合单值密钥，json 适合映射表）。

### 2.4 notify.py 改造点（只改 notify.py，调用点基本不动）

**核心思路**：因为 22/34 调用点都走 notify.py CLI，飞书渠道加在 notify.py 内部，**调用点零改动**自动切飞书；只有需要指定"非默认群"的才加参数。

1. **新增 `send_feishu(subject, body, chat_key=None, dry_run=False)`**：
   - 读 config/feishu.json；`enabled=false`/配置缺失 → 静默跳过（同 Telegram 未配置口径）。
   - `chat_key` 显式指定；None 时按 `from_prefix`/`severe` 自动映射（`[告警]`/severe → `alert` 群，`[完成]`/`[恢复]` → `agent_done` 群）。
   - 发送失败只 print 警告不抛异常（不阻塞调用方，同现有多渠道语义）。
   - 文本长度截断（新增 `FEISHU_TEXT_LIMIT`，同 TG_TEXT_LIMIT 思路）。
   - channel 实现两套都留：`_send_feishu_webhook(url)` 与 `_send_feishu_api(chat_id)`，配置里 `mode: "app"|"webhook"` 切换，阶段 1 用 webhook、阶段 2 切 app。
2. **并入 `send()` / `send_to()`**：返回值扩为 `{"email":bool,"telegram":bool,"feishu":bool}`；各渠道独立失败不互相阻塞。
   - `send()` 默认发到按前缀映射的群；`send_to()` 按订阅者无 chat_id 时跳过飞书（或发到 alert 群）。
3. **`notify_agent_done()`**：新增发到 `agent_done` 群（dedup 沿用 5min）。
4. **CLI 新增 `--feishu-group <key>`**（可选覆盖默认群映射）与 `--feishu-only`（调试用）。
5. **保留邮件兜底**：默认"飞书失败不阻塞、邮件照发"；配置 `email_fallback: true|false` 可关闭邮件（建议 P0 生产异常类始终保留邮件兜底，防飞书整体故障时无通知）。

**调用点切飞书清单（不改代码，仅配置映射）**：
- §一 A 类 22 处 SEVERE → 告警群（经 send() 自动映射，0 改动）。
- §一 B 类 --agent-done → agent 完成群（notify_agent_done 内改）。
- §一 C 类完成/恢复 → agent 完成群；信号推送/盘中异动 → 告警群（或按用户偏好）。

---

## §三 用户配合清单（飞书开放平台操作步骤）

> 全程在飞书开放平台 https://open.feishu.cn 操作，约 20-30 分钟。

1. **创建企业自建应用**
   - 打开 https://open.feishu.cn → 右上角"开发者后台" → "创建企业自建应用" → 填名称/描述 → 创建。
   - 应用"凭证与基础信息"页：复制 **App ID**（`cli_` 开头）与 **App Secret**。App Secret 只显示一次，保存好。

2. **申请权限**（应用"权限管理"页 → 添加权限）
   - 发消息：`im:message`（发送消息/以应用身份发送消息）、`im:chat`（获取与更新群组信息，用于定位群）。
   - 收消息：`im:message`（接收消息事件所需）+ 开通事件 **`im.message.receive_v1`**。
   - 部分权限是"企业自建应用可用"即可用；涉及"获取群组中所有消息"等敏感能力的权限可能需**企业管理员审批**——申请后在"权限管理"看状态，需审批的会显示待审批，需在企业管理后台（或飞书管理后台-安全设置-审批）approve。
   - 权限申请后需**发布版本**（应用"版本管理与发布"→ 创建版本 → 申请发布），企业自建应用一般由本人/管理员快速审核通过后生效。

3. **建群 + 把应用加进群**（3 群：告警/agent完成/需求）
   - 飞书建 3 个群（或复用现有群）。
   - 每个群：群设置 → 群机器人 → 添加机器人 → 选择刚创建的应用（应用需在可用范围/或版本发布后可在群内添加）。
   - **拿各群 chat_id**：应用进群后，在群里发一条消息（如"测试"），监听进程启动后从日志读到 `oc_` 开头的 chat_id；或应用"事件订阅"收到 im.message.receive_v1 事件时从 payload 的 `chat_id` 字段读。填进 `config/feishu.json` 的 `chat_ids`。

4. **事件订阅配置（长连接模式，无需公网回调）**
   - 应用"事件与回调" → "事件订阅" → 订阅方式选 **"使用长连接接收事件"**（WebSocket 长连接），**不需要配置请求地址（公网回调 URL）**——这是本机无公网也能收消息的关键。
   - 勾选订阅事件：`im.message.receive_v1`（接收消息）。
   - 确认长连接模式无需配置"加密策略/请求地址"，启动监听进程即可。

5. **把凭证交给主控（写配置，不进 git）**
   - 提供：`app_id`、`app_secret`、（如走阶段 1 webhook）各群自定义机器人 webhook URL。
   - 主控写入 `config/feishu.json`（已 gitignore，`.example` 模板不含真值）或 `.env`（`FEISHU_APP_ID`/`FEISHU_APP_SECRET`）。
   - （可选，阶段 1 快速起步）在每个群：群设置 → 群机器人 → 添加机器人 → **自定义机器人** → 复制 webhook URL。

6. **测试步骤**
   - 发送测试：主控跑 `python scripts/notify.py --dry-run "[告警] 测试" "飞书测试"` 确认 dry-run 输出，再真发一条验证各群收到。
   - 分组测试：发一条到告警群、一条 agent 完成（`--agent-done 测试`），确认落对群。
   - 接收测试：在需求提报群发 `需求: 测试某功能`，检查监听进程日志落盘 + cron 整理进 TASKS 待办 + （可选）群回执"已收到"。

---

## §四 实施阶段划分

| 阶段 | 内容 | 工时（估） | 验收口径 |
|---|---|---|---|
| **阶段 1：发送** | notify.py 加 `send_feishu`（先 webhook 或直接 app 模式）+ 群映射 + 配置文件 + 3 群中 2 个建好 | 1-2h | ①dry-run 通过 ②真发到告警群/agent 完成群各一条收到 ③SEVERE 类调用点（如 update_all/intraday）触发时自动进对应群 ④邮件兜底仍在 |
| **阶段 2：接收** | 建自建应用（若阶段 1 用 webhook）+ lark-oapi 长连接监听进程 + launchd 常驻 + 落盘 data/feishu_requests/ + cron 整理进 TASKS + 回执 | 2-3h | ①需求群发 `需求: xxx` → 日志落盘 ②cron 后 TASKS 待办出现该需求 ③回执群内可见 ④监听进程 kill 后 launchd 自动拉起 |
| **阶段 3：优化（可选）** | 发送统一到应用 API（弃 webhook）、富文本卡片、@成员、@all 关键字、入向消息转告警群 | 1-2h | 卡片/@ 在群内显示正常；入向关键词触发告警转发 |

总工时约 4-7h。阶段 1 独立可上线（先解决"告警+agent 完成"），阶段 2 再解决"提需求"。

---

## §五 风险与注意

1. **Token 安全（P0）**
   - `app_secret`/webhook URL 一律进 `config/feishu.json`（gitignore）或 `.env`，**不进 git**；用 `.example` 模板占位。
   - 任何带鉴权头的 curl 诊断禁用 `-v/-i`（§18 教训 22：curl -sv 泄漏 token）；token 从配置读不硬编码不 echo。
   - webhook URL 泄漏需在群里重建机器人（旧 URL 作废）。

2. **发消息频率限制**
   - 自定义机器人 webhook 限流较严，自建应用 im.message 限流较宽。intraday 每 10min 告警已带 dedup 1800s（30min 内不重发），schedule_monitor 每 15min 靠 alert_state 去重——**飞书渠道必须沿用 dedup**，防盘中 R2 偶发失败轰炸群。
   - 批量/循环发送注意节流（参考 upload_r2 purge 分批的 R2 经验）。

3. **长连接断线重连**
   - lark-oapi WS Client 自带重连；进程崩溃靠 launchd `KeepAlive` 拉起。
   - 监听进程是**新常驻点**，需纳入自愈/监控（listener 自身异常 → 调 notify.py 告警），否则需求静默丢失。
   - 断线期间消息会丢（长连接无离线补发），可接受（需求一般非高实时）。

4. **接收消息误触发**
   - 白名单 chat_id（只处理需求群）+ 关键词前缀（`需求:`/`t:`）双过滤，防群里闲聊被当需求落盘。
   - 只读消息不回复（除非回执），避免机器人刷屏。

5. **与现有邮件关系 / 兜底**
   - 默认**保留邮件兜底**（飞书失败不阻塞、邮件照发），尤其 P0 生产异常类（schedule_monitor/uptime_check/backup_db 等）。避免"切飞书后邮件全关 + 飞书故障"双重盲区。
   - §11 通知机制四层不因飞书新增而废弃：cron 兜底仍是主控侧唯一可靠通道；飞书是**用户侧/群侧**更好的展示渠道，两者互补。

6. **依赖与版本**
   - `lark-oapi` 需 `pip install` 进 `.venv`（python3.11）。SDK WS Client 路径（`lark_oapi.ws` vs `lark_oapi.adapter.ws`）随版本变动，实施时按安装版本 API 为准。
   - 权限名（`im:message`/`im:chat`/`im.message.receive_v1`）以开发者后台实际显示为准（本调研环境无法联网核对）。

7. **消息大小**
   - 飞书文本消息有长度限制（约 1-2K 量级，卡片更宽），notify.py 加 `FEISHU_TEXT_LIMIT` 截断（同 TG_TEXT_LIMIT 模式）；长 body（如 update_all 明细）截断或转卡片。

8. **入向消息 → 主控的持久化**
   - 需求落盘 `data/feishu_requests/`（runtime，不进 git）+ cron 整理进 **TASKS.md（git 落档）**，符合 §7 默认持久化。只落 /tmp 会丢（§7 教训）。

---

## §六 实施结果（2026-08-11）

> 阶段 1（发送）+ 阶段 2（接收）一并实施完成，3 群实测发送成功，接收长连接已连上飞书 WS。

### 6.1 实际落地清单

| 项 | 落地 | 说明 |
|---|---|---|
| 发送渠道 | `scripts/notify.py` 新增 `send_feishu()` + `_get_tenant_access_token()`（token 缓存 2h，过期前 120s 刷新） | tenant_access_token + `POST /open-apis/im/v1/messages?receive_id_type=chat_id`（msg_type=text，content 为 `{"text":...}` JSON 转义） |
| 配置 | `config/feishu.json`（gitignore）+ `config/feishu.json.example`（模板） | 群映射 `chat_ids: {alert, agent_done, report}` + receive 段（白名单/前缀/落盘目录） |
| 凭证 | `.env` 的 `FEISHU_APP_ID`/`FEISHU_APP_SECRET`（trade-data/.env），notify 从 .env 读不硬编码不 echo | config 也可显式覆盖（占位符检测） |
| 3 群 chat_id | 通过 `im.chat.list` API 按群名匹配获取，已填 config | 见 6.2 |
| 接收进程 | `scripts/feishu_ws_listener.py`（lark-oapi `ws.Client` 长连接）+ launchd `com.trade.feishu-listener`（KeepAlive 常驻） | 订阅 `im.message.receive_v1`，白名单群 + 前缀过滤落盘 |
| 邮件兜底 | 保留（send() 邮件始终先发，飞书失败不阻塞） | SEVERE 告警邮件始终发，防飞书故障无通知 |
| README/文档 | README 功能亮点+参考致谢段补充；本文档实施结果+接收落盘格式 | §18/§21 同步 |

### 6.2 3 群 chat_id（im.chat.list 实测，2026-08-11）

| 群名（后台） | key | chat_id | 内容 |
|---|---|---|---|
| 信号实验室-运维群 | `alert` | `oc_7d8d3eb6b322ddeb6b8e3c53519fae7e` | SEVERE 告警类（notify.py --severe 22 处）+ 计划任务异常 |
| 信号实验室-开发群 | `agent_done` | `oc_98a49be023582358fa6cec24749907b5` | agent 完成通知（--agent-done / notify_agent_done）+ 用户提需求（接收白名单） |
| 信号实验室，报告群 | `report` | `oc_edd9ac6dbe07303bed6f30d44b19604c` | 每日收盘分析 + 盘中信号 + 小时级节点 |

> 群名「报告群」在后台显示为「信号实验室，报告群」（含中文逗号），匹配时按前缀「信号实验室」识别。

### 6.3 notify.py 群路由规则（默认，可用 --feishu-group 覆盖）

| 条件（优先级从高到低） | 目标群 |
|---|---|
| `--severe` 或 subject/from_prefix 含 `[告警]` | `alert`（运维群） |
| subject/from_prefix 含 `[完成]` 或 `[恢复]` | `agent_done`（开发群） |
| 其余（收盘分析/盘中信号/买卖点信号/小时级节点） | `report`（报告群） |

- CLI 新增：`--feishu-group <alert|agent_done|report>`（显式覆盖）、`--feishu-only`（调试只发飞书）。
- `notify_agent_done()` 固定走 `agent_done` 群（feishu_group 可覆盖）。
- `send()`/`send_to()` 返回值扩为 `{"email":bool,"telegram":bool,"feishu":bool}`；调用点零改动自动切飞书（22/34 都走 notify.py CLI）。

### 6.4 实测记录（2026-08-11）

- **发送**：3 群各发 1 条 `--feishu-only` 测试消息，均 `[notify] Feishu 已发送至 oc_xxx` 成功（用户群内可见）：
  - 运维群：[告警] 飞书接入测试(运维群)
  - 开发群：[完成] 飞书接入测试(开发群)
  - 报告群：[报告] 飞书接入测试(报告群)
- **接收**：`feishu_ws_listener.py` 以 launchd 常驻，日志确认 `connected to wss://msg-frontier.feishu.cn/ws/v2?...`（飞书长连接已建立）；单测验证白名单+前缀过滤+落盘逻辑全过（合法需求落盘 / 无前缀闲聊跳过 / 非白名单群跳过 / post 富文本解析）。
- **接收 E2E 需用户在开发群发「需求: xxx」实测**（应用收不到自己发的消息），落盘后主控 cron 整理进 TASKS。
- **本地 SSL 环境**：本机 MITM 代理自签证书致 Python 默认校验失败，notify.py 发送遇 `CERTIFICATE_VERIFY_FAILED` 自动退化不校验重试一次（仅飞书 API）；listener 启动时 `security` 导出系统信任证书 PEM，设 `SSL_CERT_FILE`+`REQUESTS_CA_BUNDLE` 解决（用系统信任链，非关闭校验）。

### 6.5 接收落盘格式（主控读取指引）

`feishu_ws_listener.py` 收到白名单群 + 前缀（`需求:`/`t:`）匹配的消息，落盘 `data/feishu_requests/<ts>-<message_id>.json`（gitignore，不进 git），每文件：

```json
{
  "ts": 1723352400,
  "ts_iso": "2026-08-11 16:00:00",
  "sender": "ou_xxx",           // 发送人 open_id/user_id
  "chat_id": "oc_98a49be023582358fa6cec24749907b5",
  "msg_type": "text",
  "content": "需求: 做一个小功能",   // 明文（text 取 {"text":...}，post 拼 text 节点）
  "message_id": "om_xxx",
  "raw_content": "{\"text\":\"需求: 做一个小功能\"}"
}
```

**主控侧处理**（§2.2 方式 A，主控负责设）：cron 兜底每 15min 扫 `data/feishu_requests/` 新文件 → 把 `content`（去掉前缀）整理追加进 `TASKS.md` 待办（git 落档持久化）→ 已处理文件标记/移动（如改名 `*.consumed` 或移到 `data/feishu_requests/processed/`）。主控开工/compact 恢复读 TASKS 即看到需求。

### 6.6 依赖与版本（实测）

- `.venv` python3.11，`lark-oapi` 需 **>=1.1**（`lark_oapi.ws` 才存在；实测 1.0.5 无 ws 模块，升到 1.5.5 有 `lark_oapi.ws.Client`；1.5.5 无 `lark_oapi.adapter.ws` 路径）。`websockets`（SDK 依赖）16.0 已装。
- SDK `ws.Client(app_id, app_secret, event_handler, log_level, domain, auto_reconnect)`，`EventDispatcherHandler.builder("","").register_p2_im_message_receive_v1(handler).build()`。
- 事件模型：`data.event.message.{chat_id,message_type,content,create_time,message_id}` / `data.event.sender.sender_id.{user_id,open_id}`。
- 本地 MITM 证书 workaround：listener 启动 `security find-certificate -a -p` 导系统证书（3 段）→ `trade-data/data/feishu_cacert.pem`（runtime 不进 git）→ 设 env。`--no-ssl-workaround` 可跳过（纯净网络环境）。

### 6.7 手动测试命令（用户侧）

```bash
# 发送自测（--feishu-only 只发飞书不扰邮件）
cd /Users/linhuichen/code/trade
.venv/bin/python scripts/notify.py "[告警] 测试" "运维群测试" --severe --feishu-only
.venv/bin/python scripts/notify.py --feishu-group agent_done "开发群测试" --feishu-only
.venv/bin/python scripts/notify.py --feishu-group report "报告群测试" --feishu-only

# 接收 E2E（在开发群发消息，确认落盘）
# 1) 飞书开发群发：需求: 测试某功能
# 2) 查日志：tail -5 /Users/linhuichen/code/trade-data/data/logs/feishu_listener.log
# 3) 查落盘：ls -t /Users/linhuichen/code/trade/data/feishu_requests/ | head

# listener 手动启动（launchd 已常驻，无需手动；停止/重启）
launchctl kickstart -k gui/$(id -u)/com.trade.feishu-listener   # 重启
launchctl bootout gui/$(id -u)/com.trade.feishu-listener         # 停止
```
