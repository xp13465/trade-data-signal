# scripts/ — 采集 / 部署 / 一键更新

3 个 shell 脚本，串起「本地采集 → 静态 JSON 导出 → git push 自动部署 Cloudflare Pages」全流程。所有脚本内部用绝对路径，可从任意目录调用。

## 脚本

### `collect.sh` — 采集数据（手动 / 定时）

调 `app.scheduler.run()`：刷新交易日历 → 交易日闸门 → 采集 → 计算 → 告警检查（step 1-8）。scheduler 内部各 step 已 try/except，部分失败不阻塞整体。

```bash
bash scripts/collect.sh            # 今天
bash scripts/collect.sh 20260706   # 指定日期（透传给 scheduler）
```

- 日志：`data/logs/collect_YYYYMMDD_HHMM.log`（tee 同时输出到终端）
- 退出码：scheduler 退出码（部分 step 失败仍返 0，scheduler 不抛）
- 注意：`set -u` 但不 `set -e`——采集部分失败仍继续，记录退出码

### `deploy.sh` — 推送公网（导出 JSON + git push）

跑 `static-site/export.py` 生成静态 JSON → `git add static-site/data/` → 检查有无变更 → 有变更才 commit + push（Cloudflare Pages 自动部署），无变更 skip。

```bash
bash scripts/deploy.sh
```

- commit message：`data update YYYY-MM-DD_HH:MM`
- 日志：`data/logs/deploy_YYYYMMDD_HHMM.log`
- 退出码：0=成功（push 或 skip）；非 0=export 或 push 失败
- 仓库 remote：`git@github.com:xp13465/trade-data-signal.git`（SSH 已认证）

### `update_all.sh` — 一键更新（collect + deploy）

顺序跑 collect → deploy。**无论采集成功失败都继续 deploy**——用现有（可能部分更新）数据导出推送，公网保持最新可用状态；collect 失败仅记日志、不改变最终退出码。

```bash
bash scripts/update_all.sh
```

- 日志：`data/logs/update_all_YYYYMMDD_HHMM.log`（含 collect + deploy 子日志）
- 退出码：deploy.sh 退出码（最终公网状态）

## 定时任务配置

### 方案 A：launchd（macOS 推荐）

现有 `launchd/com.trade.sentiment.plist` 每日 15:33 直接跑 `app.scheduler`（仅采集，不部署）。如需每日盘后自动「采集 + 部署」一键完成，可改用下面的 `update_all.sh` plist：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.trade.update-all</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>/Users/linhuichen/code/trade/scripts/update_all.sh</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>15</integer>
        <key>Minute</key>
        <integer>33</integer>
    </dict>
    <key>WorkingDirectory</key>
    <string>/Users/linhuichen/code/trade</string>
    <key>StandardOutPath</key>
    <string>/Users/linhuichen/code/trade/data/logs/update_all_launchd.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/linhuichen/code/trade/data/logs/update_all_launchd.err</string>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
```

安装与启用：

```bash
# 放到 ~/Library/LaunchAgents/
cp com.trade.update-all.plist ~/Library/LaunchAgents/

# 加载（生效）
launchctl load ~/Library/LaunchAgents/com.trade.update-all.plist

# 立即手动触发一次测试
launchctl start com.trade.update-all

# 查看状态
launchctl list | grep com.trade

# 卸载
launchctl unload ~/Library/LaunchAgents/com.trade.update-all.plist
```

注意：

- 与旧 plist（`com.trade.sentiment`，仅采集）二选一即可，避免重复采集。如改用 update_all，建议先 `launchctl unload` 旧 plist。
- A 股收盘 15:00，15:33 跑留出 33 分钟等盘后数据落盘；港股 / 美股时差另算。
- Mac 睡眠时 launchd 不触发，醒来后 `RunAtLoad=false` 不会补跑。如需补跑可临时 `launchctl start` 或手动 `bash scripts/update_all.sh`。

### 方案 B：cron

```bash
crontab -e
```

加一行（每日 15:33 跑 update_all，输出到日志）：

```cron
33 15 * * * /bin/bash /Users/linhuichen/code/trade/scripts/update_all.sh >> /Users/linhuichen/code/trade/data/logs/update_all_cron.log 2>&1
```

注意：cron 环境变量精简，PATH 可能不含 venv。脚本内已用 `.venv/bin/python` 绝对路径，无影响；但 git/ssh 需确保 SSH key 在 cron 用户上下文可用（macOS 默认 ssh-agent 不在 cron 注入，可加 `eval $(ssh-agent -s)` + `ssh-add ~/.ssh/id_*` 到脚本头，或用 launchd 方案更省心）。

## 文件位置

- 脚本目录：`/Users/linhuichen/code/trade/scripts/`
- 日志目录：`/Users/linhuichen/code/trade/data/logs/`（已在 `.gitignore`，不进仓库）
- 静态 JSON：`/Users/linhuichen/code/trade/static-site/data/`（进仓库，push 部署）
- 数据库：`/Users/linhuichen/code/trade/data/sentiment.db`（进仓库）/ `stock_daily.db`（已 gitignore，4.6GB）
