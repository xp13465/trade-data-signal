# scripts/ — 采集 / 部署 / 一键更新

3 个 shell 脚本，串起「本地采集 → 静态 JSON 导出 → git push 自动部署 Cloudflare Pages」全流程。所有脚本内部用绝对路径，可从任意目录调用。

## 脚本

### `collect.sh` — 采集数据（手动 / 定时）

调 `app.scheduler.run()`：刷新交易日历 → 交易日闸门 → 采集 → 计算 → 告警检查（step 1-9）。scheduler 内部各 step 已 try/except，部分失败不阻塞整体。

```bash
bash /Users/linhuichen/code/trade/scripts/collect.sh            # 今天
bash /Users/linhuichen/code/trade/scripts/collect.sh 20260706   # 指定日期（透传给 scheduler）
```

- 日志：`/Users/linhuichen/code/trade/data/logs/collect_YYYYMMDD_HHMM.log`（tee 同时输出到终端）
- 退出码：scheduler 退出码（部分 step 失败仍返 0，scheduler 不抛）
- 注意：`set -u` 但不 `set -e`——采集部分失败仍继续，记录退出码

#### 漏跑工作日自动回填

工作日漏跑（如周一忘周二跑，周三才跑 scheduler）时，各类指标自动回填机制：

- **历史序列指标**（北向资金、融资融券、国债收益率、QVIX 等 `collect_series`）：自动回填——akshare 一次拉全历史，覆盖漏跑日。
- **全市场宽度**（涨跌家数 / 成交额 / 涨停 / 跌停 / 炸板 / 封板率，step 9 `width_history.run_recent(days=30)`）：自动回填——从 `mootdx_daily_raw` 全 A 股日线重算近 30 天宽度，覆盖漏跑日。不依赖当日快照（`stock_zh_a_spot` 只返当日无法回填），从已入库的日线数据算。**A1 近端值保护**：涨跌家数 / 成交额跳过已有 `source='akshare'` 的日期（A1 全市场口径含北交所更准），只补漏跑日；涨停 / 跌停 / 炸板 / 封板率全段覆盖（mootdx 收盘封板口径替代 zt_pool 触板口径）。`upsert WHERE source != 'manual'` 防覆盖手动补录。
- **涨停池源**（`stock_zt_pool_em` 等 `DATE_PARAM_FUNCS`）：源支持近 2 周带日期参数回填，但 scheduler 每次只采当日（不循环历史日）。漏跑日的涨停池源值不自动回填——由 step 9 `width_history.run_recent` 用 mootdx 收盘封板口径补全（与 zt_pool 触板口径误差 ~3%，已校验）。如需精确 zt_pool 源回填近 2 周，手动跑 `python -m app.backfill 14`。
- **行业内宽度**（step 8 `industry_width.run_recent(days=15)`）：自动回填——同 step 9 机制，从 mootdx 重算近 15 天 31 行业内宽度。

### `deploy.sh` — 推送公网（导出 JSON + git push）

跑 `static-site/export.py` 生成静态 JSON → `git add static-site/data/` → 检查有无变更：有变更 commit，无变更跳过 commit → **总是 `git push`**（最后一步，幂等：有未 push commit 就推，无则 "Everything up-to-date"）。Cloudflare Pages 监听 push 自动部署。

```bash
bash /Users/linhuichen/code/trade/scripts/deploy.sh
```

- commit message：`data update YYYY-MM-DD_HH:MM`
- 日志：`/Users/linhuichen/code/trade/data/logs/deploy_YYYYMMDD_HHMM.log`
- 退出码：0=成功（commit+push 或 仅 push up-to-date）；非 0=export 或 push 失败
- 仓库 remote：`git@github.com:xp13465/trade-data-signal.git`（SSH 已认证）
- **总是 push**：即便无新数据变更也执行 `git push`，以兜底「上次 commit 成功但 push 失败」的恢复场景（见下方「重复跑 / 异常中断重跑」）。

### `update_all.sh` — 一键更新（collect + deploy）

顺序跑 collect → deploy。**无论采集成功失败都继续 deploy**——用现有（可能部分更新）数据导出推送，公网保持最新可用状态；collect 失败仅记日志、不改变最终退出码。

```bash
bash /Users/linhuichen/code/trade/scripts/update_all.sh
```

- 日志：`/Users/linhuichen/code/trade/data/logs/update_all_YYYYMMDD_HHMM.log`（含 collect + deploy 子日志）
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
- Mac 睡眠时 launchd 不触发，醒来后 `RunAtLoad=false` 不会补跑。如需补跑可临时 `launchctl start` 或手动 `bash /Users/linhuichen/code/trade/scripts/update_all.sh`。

### 方案 B：cron

```bash
crontab -e
```

加一行（每日 15:33 跑 update_all，输出到日志）：

```cron
33 15 * * * /bin/bash /Users/linhuichen/code/trade/scripts/update_all.sh >> /Users/linhuichen/code/trade/data/logs/update_all_cron.log 2>&1
```

注意：cron 环境变量精简，PATH 可能不含 venv。脚本内已用 `.venv/bin/python` 绝对路径，无影响；但 git/ssh 需确保 SSH key 在 cron 用户上下文可用（macOS 默认 ssh-agent 不在 cron 注入，可加 `eval $(ssh-agent -s)` + `ssh-add ~/.ssh/id_*` 到脚本头，或用 launchd 方案更省心）。

## 重复跑 / 异常中断重跑

3 个脚本均**重跑安全**（幂等）。脚本被中断或网络异常后，直接重跑即可补全，无需手动清理。

### `collect.sh` — 幂等

scheduler 各 step 幂等机制（已校验）：

- **upsert 覆盖**：`width_history.upsert_width` / `_upsert_width_recent` 用 `INSERT ... ON CONFLICT DO UPDATE WHERE source != 'manual'`（防覆盖手动补录）。同一日重复采集直接覆盖旧值。
- **DELETE 重算**：信号类指标（如 `signal_daily`）`DELETE FROM signal_daily` 后全表重算，重跑不留旧数据残影。
- **progress 跳过**：baostock 采全 A 股日线时用 `data/baostock_progress.json` 记录已采 code，重跑跳过已完成、只采未完成。
- **`width_history.run_recent(days=30)`**：从 `mootdx_daily_raw` 全 A 股日线重算近 30 天宽度并 upsert，不依赖当日快照——漏跑日自动回填，重复跑覆盖。

中断后重跑：scheduler 从头跑一遍各 step，已落库的覆盖、未完成的补全。

### `deploy.sh` — 幂等

- export.py 重跑生成相同 JSON（数据未变时）。
- `git add` 无新变更 → `git diff --cached --quiet` 通过 → **跳过 commit**（不创建空 commit）。
- **总是 `git push`**（最后一步）：push 本身幂等——
  - 上次 commit 成功但 push 失败（网络中断等）→ 重跑无新变更不 commit → `git push` 推未 push commit。✅
  - 无未 push commit → `git push` 返回 "Everything up-to-date"，无副作用。
  - 有新变更 → commit 后 push，正常流程。

### `update_all.sh` — 幂等

collect + deploy 都幂等 → update_all 重跑安全。中断后直接重跑 `bash scripts/update_all.sh` 即可。

### 例外

- **`git push` 本身失败**（网络不通 / SSH key 不可用 / 权限拒绝）需重跑 `deploy.sh`：脚本退出码非 0，日志记 `✗ git push 失败`。重跑会再 export + git add（无新变更跳过 commit）+ git push 重试。
- collect.sh 内部某 step 抛异常被 scheduler try/except 兜底（部分失败），退出码仍 0，不影响 deploy。

## 文件位置

- 脚本目录：`/Users/linhuichen/code/trade/scripts/`
- 日志目录：`/Users/linhuichen/code/trade/data/logs/`（已在 `.gitignore`，不进仓库）
- 静态 JSON：`/Users/linhuichen/code/trade/static-site/data/`（进仓库，push 部署）
- 数据库：`/Users/linhuichen/code/trade/data/sentiment.db`（进仓库）/ `stock_daily.db`（已 gitignore，4.6GB）
