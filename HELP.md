# 使用帮助 · 情绪数据复盘看板

> 配套文档：[REQUIREMENTS.md](REQUIREMENTS.md)（需求与实现状态）、[PLAN.md](PLAN.md)（实现方案）、[README.md](README.md)（快速安装）。
> 本文聚焦**怎么用 + 注意事项 + 故障排查**。

---

## 1. 快速开始

```bash
cd /Users/linhuichen/code/trade

# 启动看板（仅本机访问）
.venv/bin/python -m uvicorn app.main:app --port 8000 --app-dir .

# 启动看板（允许局域网访问 —— 用 --host 0.0.0.0）
.venv/bin/python -m uvicorn app.main:app --port 8000 --host 0.0.0.0 --app-dir .
```

- 本机访问：**http://localhost:8000**
- 局域网访问：**http://<这台 Mac 的局域网 IP>:8000**（查 IP：`ipconfig getifaddr en0`）

停止看板：在运行 uvicorn 的终端按 `Ctrl+C`；若后台运行则 `pkill -f uvicorn`。

> 局域网访问若失败：① macOS 防火墙弹窗点「允许」（或「系统设置 → 网络 → 防火墙」放行 Python）；② 确认访问设备与 Mac 在同一 Wi-Fi。

---

## 2. 每日自动运行（launchd 定时）

每个交易日 15:33 自动采集 + 计算 + 落库。

```bash
# 安装（一次性）
mkdir -p ~/Library/LaunchAgents
cp /Users/linhuichen/code/trade/launchd/com.trade.sentiment.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.trade.sentiment.plist

# 卸载
launchctl unload ~/Library/LaunchAgents/com.trade.sentiment.plist

# 查看运行日志
tail -50 /Users/linhuichen/code/trade/data/logs/scheduler.log
tail -50 /Users/linhuichen/code/trade/data/logs/scheduler.err
```

注意：
- 15:33（不是 15:30）是为了避开收盘瞬间数据未定；A 股 15:00 收盘，港股 16:00 收盘——港股数据可能要 16:00 后才完整，但当日采集会取已有值，次日 launchd 会再补。
- 周末/节假日自动跳过（`app/calendar.py` 判断交易日）。
- 定时任务用的是 `.venv/bin/python`，**别删 venv**。

---

## 3. 手动操作

### 跑一次当日采集 + 计算
```bash
.venv/bin/python -m app.scheduler            # 自动取最近交易日
.venv/bin/python -m app.scheduler 20260703   # 指定日期
```

### 只重新计算综合分 / 买卖点（不重新采集）
```bash
.venv/bin/python -m app.compute.runner
```

### 手动补录数据
看板右上角「＋手动补录」按钮 → 选指标、填日期和数值 → 提交。手动值会**覆盖**同日自动采集值（`source='manual'`）。

### 只回填某个序列指标的历史
序列指标（北向、QVIX、指数、沪金等）在每日采集时已自动拉全部历史，无需单独回填。

---

## 4. 看板说明

### 5 个 Tab
| Tab | 内容 |
|---|---|
| **概览** | 两个综合分最新值 + 冰点/过热标签 + 今日买卖点 + 近期冰点日 + 跨市场分近 3 月趋势 |
| **A股** | 市场宽度（涨跌家数/涨停/连板/炸板率/打板溢价）、资金面（北向/两融/主力/成交额）、QVIX、龙虎榜/解禁/IPO/可转债 + 7 个宽基指数（带买卖点） |
| **港股** | 恒生/恒生科技/恒生国企（带买卖点）+ 港股通净买入 |
| **全球** | 黄金/原油/离岸人民币/QVIX 折线（美股指数暂未接通，见 §5） |
| **综合情绪** | §6 跨市场综合评分 + §4 A股综合情绪分（0-100，红=冰点/绿=过热） |

### 周期按钮
顶部 `1月 / 3月 / 6月 / 1年 / 全部` 切换所有图表的时间窗口。

### 买卖点标注
指数图上的 📍 标注：
- **红「买」** = RSI(14) ≤ 30（价格超卖/低位）且 跨市场分未极端过热（<80）
- **绿「卖」** = RSI(14) ≥ 70（价格超买/高位）且 跨市场分未极端冰点（>20）
- 主信号是指数自身 RSI（保证低买高卖），跨市场分只作「不矛盾」过滤。
- **仅供参考，非交易指令**。

### 综合分含义
- **§6 跨市场综合评分**：跨 A股/港股/全球 所有指标归一化后去最高/最低取均值，0-100。<20 冰点，>80 过热。有 2779 天历史。
- **§4 A股综合情绪分**：A 股 6 项宽度+资金加权（涨跌家数比 25% / 涨停 20% / 炸板率 15% / 连板 15% / 成交额 10% / 北向 15%）。目前只有近 2 周（见限制）。

---

## 5. 注意事项 / 已知限制（重要）

### ① §4 A股情绪分历史只有近 2 周
东财涨停板池接口（`stock_zt_pool_em`）**只保留近 2 周数据**，无法回填更早。§4 从 20260626 起，随每日采集积累向前扩展，约 4 个月后 120 日滚动窗口稳定。
- 想看历史情绪趋势 → 用 **§6 跨市场分**（2779 天）。
- §4 近期值基于 3 个分项（涨停/炸板/连板），min_periods=10，初期会略抖动，属正常。

### ② 7 项指标已禁用（待找源）
| 指标 | 原因 |
|---|---|
| 美股三大指数（道/纳/标普） | sina 全球指数表无美股；东财反爬。待接 `stock_us_index` 或直爬 |
| 行业/概念板块、行业资金流 | 东财 push2 clist 端点反爬封。待直爬实现 |
| 换手率 | sina 全 A 接口无换手率列 |
| 乐咕活跃度 | legulegu.com 不稳定 |
| 东财情绪 | 接口待验证 |

这些在 `config/indicators.yaml` 里 `enabled: false`，不影响主流程。后续可逐个补。

### ③ 北向资金 2024 起口径变化
东财 2024 改披露口径，`stock_hsgt_hist_em` 历史止于 **20240816**，之后无数据。2024 后的北向需另找源。

### ④ 主力资金流间歇失败
`direct:market_fund_flow` 直爬东财 push2his，该端点间歇性反爬。失败会记日志、跳过，次日重试常可成。非核心指标。

### ⑤ Clash 代理环境
你 Mac 上的 Clash（127.0.0.1:7890）会把东财流量走境外出口被东财封 IP。代码已用 `trust_env=False` 全局绕过代理直连国内源。
- **如果你关了 Clash 或换代理设置**：不受影响（trust_env=False 不依赖代理）。
- **如果某些境外源（如 legulegu）需要代理**：当前会失败（已禁用）。

### ⑥ 数据更新时机
- 盘后 15:33 跑 → A 股数据齐全；港股 16:00 收盘，港股数据可能滞后一天（次日补）。
- 当日采集的是**最近交易日**的数据（非今天实时）。

---

## 6. 故障排查

### 看板打不开（http://localhost:8000）
```bash
# 确认 uvicorn 在跑
ps aux | grep uvicorn | grep -v grep
# 没在跑就启动
cd /Users/linhuichen/code/trade && .venv/bin/python -m uvicorn app.main:app --port 8000 --app-dir .
# 端口被占？换端口
.venv/bin/python -m uvicorn app.main:app --port 8001 --app-dir .
```

### 采集失败 / 数据为空
```bash
# 看采集日志
.venv/bin/python -c "
import sqlite3; c=sqlite3.connect('data/sentiment.db')
for r in c.execute('SELECT run_date, metric_id, status, message FROM collect_log WHERE status=\"error\" ORDER BY id DESC LIMIT 20'):
    print(r)
c.close()
"
# 手动重跑当日
.venv/bin/python -m app.scheduler
```
常见原因：东财反爬（重试即可）、网络抖动、akshare 接口变更。

### 综合分为空
```bash
.venv/bin/python -m app.compute.runner   # 重算
```
§4 需要 ≥3 个宽度分项 + ≥10 天历史，初期可能为空，积累几天后出现。

### 定时任务没跑
```bash
launchctl list | grep trade.sentiment     # 看是否 loaded
cat data/logs/scheduler.err               # 看错误
# plist 里路径是写死的 /Users/linhuichen/code/trade，移动项目要改 plist
```

### akshare 接口报错
akshare 版本变化会改函数名/列名。检查：
```bash
.venv/bin/python -c "import akshare as ak; print(ak.__version__)"
```
当前锁定 `akshare==1.18.64`。升级后可能需要改 `config/indicators.yaml` 里的 func/column。

---

## 7. 指标管理（增删改）

改 `config/indicators.yaml`，无需动代码：

```yaml
# 禁用一个指标
- {id: a_fund_main, ..., enabled: false}

# 加一个新指标
- {id: a_new_metric, name: 新指标, group: a_width, type: simple,
   func: stock_xxx_em, column: 某列, transform: sum, unit: 亿元,
   direction: positive, enabled: true}
```

改完运行 `.venv/bin/python -m app.scheduler` 重新采集。

### 调整综合分权重 / 买卖点参数
- §4 权重：`app/compute/sentiment.py` 的 `COMPONENTS`
- §6 去极值个数：`app/compute/cross.py` 的 `trim_mean`（当前去 1 max + 1 min）
- 买卖点 MA 周期/放量倍数：`app/compute/signals.py`

改完 `.venv/bin/python -m app.compute.runner` 重算。

---

## 8. 数据库

- 位置：`data/sentiment.db`（SQLite）
- 表：`daily_metric`（单值指标）、`index_daily`（指数 OHLCV）、`board_daily`（板块）、`score_daily`（综合分）、`signal_daily`（买卖点）、`manual_entry`、`collect_log`、`alert_log`

```bash
# 备份
cp data/sentiment.db data/sentiment.db.bak

# 清空重采（慎用）
.venv/bin/python -c "
import sqlite3; c=sqlite3.connect('data/sentiment.db')
for t in ['daily_metric','index_daily','board_daily','score_daily','signal_daily','collect_log']:
    c.execute(f'DELETE FROM {t}')
c.commit(); c.close()
"
.venv/bin/python -m app.collector.runner 20260703   # 重采当日
.venv/bin/python -m app.compute.runner              # 重算

# 直接看数据
sqlite3 data/sentiment.db "SELECT metric_id,count(*),max(date) FROM daily_metric GROUP BY metric_id"
```

---

## 9. 文件结构速查

```
trade/
├── REQUIREMENTS.md        # 需求 + 实现状态（§10）
├── HELP.md                # 本文件
├── config/indicators.yaml # 指标注册表（增删改这里）
├── app/
│   ├── main.py            # FastAPI 看板后端
│   ├── scheduler.py       # 每日定时入口
│   ├── db.py / calendar.py
│   ├── collector/         # 采集（base/fetchers/runner/direct）
│   └── compute/           # 计算（normalize/sentiment/cross/signals）
├── web/                   # 前端（index.html/app.js/style.css/vendor/echarts.min.js）
├── launchd/               # launchd plist
└── data/sentiment.db      # 数据库
```

有疑问先看 `REQUIREMENTS.md §10`（实现状态与限制），或 `data/logs/scheduler.log`。
