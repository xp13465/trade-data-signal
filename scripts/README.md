# scripts/ — 采集 / 部署 / 一键更新 / 信号通知

4 个 shell 脚本，串起「本地采集 → 静态 JSON 导出 → git push 自动部署 Cloudflare Pages → 买卖点信号邮件通知」全流程。所有脚本内部用绝对路径，可从任意目录调用。

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

### `check_signals.sh` — 买卖点信号邮件通知

调 `scripts/check_signals.py`：查 `signal_daily` 当日（默认 today，可传日期参数）买卖点信号，有则发邮件（SMTP 163 SSL），无信号仅记日志。邮件发送失败不阻塞（退出码非 0 但脚本不崩）。

```bash
bash /Users/linhuichen/code/trade/scripts/check_signals.sh            # 今天
bash /Users/linhuichen/code/trade/scripts/check_signals.sh 20260706   # 指定日期
```

- 邮件主题：`[买卖点信号] YYYYMMDD N个信号`
- 邮件正文：按 buy/sell 分组列出 index_id + reason，附买卖点规则说明 + 免责声明
- 收件人 / SMTP 配置：`config/email.json`（已 gitignore，模板见 `config/email.json.example`）
- 日志：`/Users/linhuichen/code/trade/data/logs/check_signals_YYYYMMDD_HHMM.log`
- 退出码：0=成功 / 无信号 / 占位密码跳过；2=邮件发送失败（不崩）；其他非 0=查询异常

#### 首次配置（必读）

`config/email.json` 含 SMTP 授权码属敏感信息，已 gitignore 不进仓库。首次使用需：

```bash
cp config/email.json.example config/email.json
# 编辑 config/email.json，把 password 字段填上 163 邮箱 SMTP 授权码（非登录密码！）
# 授权码获取：登录 mail.163.com → 设置 → POP3/SMTP/IMAP → 开启 SMTP 服务 → 生成授权码
```

未配置或 password 仍是占位符时，脚本只打印邮件内容到日志，不实际发送（便于测试）。

### `update_all.sh` — 一键更新（collect + deploy + check_signals）

顺序跑 collect → deploy → check_signals。**无论采集成功失败都继续 deploy**——用现有（可能部分更新）数据导出推送，公网保持最新可用状态；collect 失败仅记日志、不改变最终退出码。**check_signals 失败也不阻塞**——邮件发送失败 / 配置缺失仅记日志，不影响公网部署退出码。

```bash
bash /Users/linhuichen/code/trade/scripts/update_all.sh
```

- 日志：`/Users/linhuichen/code/trade/data/logs/update_all_YYYYMMDD_HHMM.log`（含 collect + deploy + check_signals 子日志）
- 退出码：deploy.sh 退出码（最终公网状态）；collect / check_signals 退出码仅记日志

### baostock_daily 日常跳过与手动补数据（2026-07-09 P1 提速后）

**背景**：`update_all.sh` / `collect.sh` 调用的 scheduler 第 6 步（baostock 全 A 股日线增量）默认**跳过**。原因：`baostock_daily_raw` 表仅 `cleanup_d3d2` 手动做数据交叉校验时读，日常看板 / 导出不依赖（全 A 日线主力是 `mootdx_daily`）；而该步 5072 codes 串行 + 45% 失败重试耗时 ~1h，拖慢 `update_all`。故日常不跑，需要时手动补。日志中该步显示 `skip (日常不跑; 需时 RUN_BAOSTOCK=1 或手动 baostock_daily recent)`。

**何时需要手动补**：
- 跑 `cleanup_d3d2`（D3/D2 数据清理，需 baostock 作交叉校验源）前
- 想刷新 baostock 全 A 日线（如 mootdx 与东财均有缺口，需第三方源校验 / 补全）

**手动命令**（均在仓库根目录 `/Users/linhuichen/code/trade` 下执行）：

```bash
cd /Users/linhuichen/code/trade

# 查现状（codes 数 / 行数 / 日期范围 / progress 完成度）
.venv/bin/python -m app.collector.baostock_daily stats

# 增量更新所有 code（recent 段 2016-2026 增量，等价原 scheduler 第 6 步）
.venv/bin/python -m app.collector.baostock_daily update

# 全量回填近 10 年段（2016-2026，D2 急需；~5000 codes 串行，单只 10 年日线 ~6.5s，首次全量 ~9h；已采 code 自动跳过，后续只补新股很快）
.venv/bin/python -m app.collector.baostock_daily recent

# 补老段（1990-2015）
.venv/bin/python -m app.collector.baostock_daily old

# 全段（先 recent 后 old）
.venv/bin/python -m app.collector.baostock_daily full

# 单只增量 / 单只全量（排查单 code 用）
.venv/bin/python -m app.collector.baostock_daily upone 600000
.venv/bin/python -m app.collector.baostock_daily one 600000
```

**断点续传**：进度存 `data/baostock_progress.json`（`{code: {"r": yyyymmdd, "o": yyyymmdd}}`），中断（含 `Ctrl+C`）后重跑自动跳过已采 code、只采未完成。`Ctrl+C` 会保存进度再退出（退出码 130）。

**小批量测试**：任一批量命令加 `--limit=N` 先跑 N 只验证，如 `recent --limit=10`。

**临时让 update_all 自动跑一次 baostock**（不想手动、想走完整流程时）：

`RUN_BAOSTOCK=1` 是环境变量前缀，**必须放在命令最前**——它传给 bash 进程，再由 bash 继承给 `collect.sh` → `.venv/bin/python` → scheduler 第 6 步（runner.py 读 `os.environ.get("RUN_BAOSTOCK")`）。放在最前只对该次命令生效，跑完自动恢复默认跳过，不改代码、不污染当前 shell。

```bash
# 你日常用的绝对路径形式（在任意目录都能跑，无需 cd 仓库）：
RUN_BAOSTOCK=1 /bin/bash /Users/linhuichen/code/trade/scripts/update_all.sh

# 或只采集不部署：
RUN_BAOSTOCK=1 /bin/bash /Users/linhuichen/code/trade/scripts/collect.sh
```

也可先 `export RUN_BAOSTOCK=1` 再跑原命令（`/bin/bash /Users/linhuichen/code/trade/scripts/update_all.sh`），但会污染当前 shell 会话，跑完记得 `unset RUN_BAOSTOCK`。

设 `RUN_BAOSTOCK=1` 环境变量即启用 scheduler 第 6 步，跑完即恢复默认跳过（不改代码）。

## 定时任务配置

### 三个时间点

- **14:30 盘中预警**：`collect.sh`（更新盘中数据 + compute）+ `check_signals.sh`（查当日信号 + 发邮件）。盘中数据可能未完整，但买卖点信号（RSI 上穿 30 / 20 日高回落 5%）已可初步判断，提前预警。
- **17:50 收盘正式**：`update_all.sh`（collect + deploy + check_signals）。A 股 15:00 收盘，**baostock 等主源 ~17:45 才发布当日 T+1 数据**（15:33 跑太早采不到当日，已实测），故后移到 17:50；同时推送公网 + 发信号邮件。采后自动多源补采（新浪主源当日延迟则 baostock/腾讯补，见 `app/collector/index_backfill.py`）。申万 trend 通常更晚出，靠快照反哺 + 20:00 backfill 兜底。
- **20:00 晚间补采兜底**：`backfill_indices.sh`（只校验补采缺失指数 + 重算情绪分 + 推送，不全量采集，几十秒）。兜底 17:50 跑时三源还没今日数据的情况——20:00 三源已更新，补上。plist 模板：`scripts/plists/com.trade.backfill-evening.plist`。

### 方案 A：launchd（macOS 推荐）

#### 14:30 盘中预警（`com.trade.check-signals-noon`）

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.trade.check-signals-noon</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>-c</string>
        <string>bash /Users/linhuichen/code/trade/scripts/collect.sh &amp;&amp; bash /Users/linhuichen/code/trade/scripts/check_signals.sh</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>14</integer>
        <key>Minute</key>
        <integer>30</integer>
    </dict>
    <key>WorkingDirectory</key>
    <string>/Users/linhuichen/code/trade</string>
    <key>StandardOutPath</key>
    <string>/Users/linhuichen/code/trade/data/logs/check_signals_noon_launchd.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/linhuichen/code/trade/data/logs/check_signals_noon_launchd.err</string>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
```

#### 17:50 收盘正式（`com.trade.update-all`）

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
cp com.trade.check-signals-noon.plist com.trade.update-all.plist ~/Library/LaunchAgents/

# 加载（生效）
launchctl load ~/Library/LaunchAgents/com.trade.check-signals-noon.plist
launchctl load ~/Library/LaunchAgents/com.trade.update-all.plist

# 立即手动触发一次测试
launchctl start com.trade.check-signals-noon
launchctl start com.trade.update-all

# 查看状态
launchctl list | grep com.trade

# 卸载
launchctl unload ~/Library/LaunchAgents/com.trade.check-signals-noon.plist
launchctl unload ~/Library/LaunchAgents/com.trade.update-all.plist
```

注意：

- 与旧 plist（`com.trade.sentiment`，仅采集）二选一即可，避免重复采集。如改用 update_all，建议先 `launchctl unload` 旧 plist。
- A 股收盘 15:00，17:50 跑留出 约 2 小时 50 分钟等 baostock 等主源发布当日 T+1 数据；港股 / 美股时差另算。
- Mac 睡眠时 launchd 不触发，醒来后 `RunAtLoad=false` 不会补跑。如需补跑可临时 `launchctl start` 或手动 `bash /Users/linhuichen/code/trade/scripts/update_all.sh`。
- 14:30 盘中预警只跑 collect + check_signals（不 deploy），避免盘中数据未完整就推送公网；17:50 收盘正式才跑完整 update_all（含 deploy）。

### 方案 B：cron

```bash
crontab -e
```

加两行（14:30 盘中预警 + 17:50 收盘正式，输出到日志）：

```cron
30 14 * * * /bin/bash -c 'bash /Users/linhuichen/code/trade/scripts/collect.sh && bash /Users/linhuichen/code/trade/scripts/check_signals.sh' >> /Users/linhuichen/code/trade/data/logs/check_signals_noon_cron.log 2>&1
33 15 * * * /bin/bash /Users/linhuichen/code/trade/scripts/update_all.sh >> /Users/linhuichen/code/trade/data/logs/update_all_cron.log 2>&1
```

注意：cron 环境变量精简，PATH 可能不含 venv。脚本内已用 `.venv/bin/python` 绝对路径，无影响；但 git/ssh 需确保 SSH key 在 cron 用户上下文可用（macOS 默认 ssh-agent 不在 cron 注入，可加 `eval $(ssh-agent -s)` + `ssh-add ~/.ssh/id_*` 到脚本头，或用 launchd 方案更省心）。

### 手动执行

```bash
# 假设数据已更新，只查信号 + 发邮件
bash /Users/linhuichen/code/trade/scripts/check_signals.sh

# 完整流程：采集 + 部署 + 信号通知
bash /Users/linhuichen/code/trade/scripts/update_all.sh

# 指定日期回看信号（不发真邮件如果 password 是占位符）
bash /Users/linhuichen/code/trade/scripts/check_signals.sh 20260701
```

## 重复跑 / 异常中断重跑

4 个脚本均**重跑安全**（幂等）。脚本被中断或网络异常后，直接重跑即可补全，无需手动清理。

### `collect.sh` — 幂等

scheduler 各 step 幂等机制（已校验）：

- **upsert 覆盖**：`width_history.upsert_width` / `_upsert_width_recent` 用 `INSERT ... ON CONFLICT DO UPDATE WHERE source != 'manual'`（防覆盖手动补录）。同一日重复采集直接覆盖旧值。
- **DELETE 重算**：信号类指标（如 `signal_daily`）`DELETE FROM signal_daily` 后全表重算，重跑不留旧数据残影。
- **progress 跳过**：baostock 采全 A 股日线时用 `data/baostock_progress.json` 记录已采 code，重跑跳过已完成、只采未完成。（注：P1 提速后 scheduler 第 6 步默认跳过 baostock，此幂等机制对手动 `baostock_daily update/recent` 同样生效；手动补数据见下文「baostock_daily 日常跳过与手动补数据」节）
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

collect + deploy + check_signals 都幂等 → update_all 重跑安全。中断后直接重跑 `bash scripts/update_all.sh` 即可。

### `check_signals.sh` — 幂等

- 只读 `signal_daily` 当日数据 + 发邮件，无写入副作用。
- 重跑发多封邮件（内容相同）——如不想重复收信，可重跑前先看日志确认。
- 邮件发送失败重跑会重试发送（SMTP 幂等性由邮件服务器保证，重复 sendmail 可能产生多封相同邮件）。

### 例外

- **`git push` 本身失败**（网络不通 / SSH key 不可用 / 权限拒绝）需重跑 `deploy.sh`：脚本退出码非 0，日志记 `✗ git push 失败`。重跑会再 export + git add（无新变更跳过 commit）+ git push 重试。
- collect.sh 内部某 step 抛异常被 scheduler try/except 兜底（部分失败），退出码仍 0，不影响 deploy。
- check_signals.sh 邮件发送失败（SMTP 拒绝 / 授权码失效 / 网络不通）退出码 2，但不阻塞 update_all.sh，公网部署仍正常完成。需手动看日志修复 email.json 后重跑 `bash scripts/check_signals.sh`。

## 文件位置

- 脚本目录：`/Users/linhuichen/code/trade/scripts/`
- 日志目录：`/Users/linhuichen/code/trade/data/logs/`（已在 `.gitignore`，不进仓库）
- 静态 JSON：`/Users/linhuichen/code/trade/static-site/data/`（进仓库，push 部署）
- 数据库：`/Users/linhuichen/code/trade/data/sentiment.db`（进仓库）/ `stock_daily.db`（已 gitignore，4.6GB）
