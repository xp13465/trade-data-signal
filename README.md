# 📊 市场温度看板 · tdsignal

> A股 / 港股 / 全球 盘后复盘 **市场温度看板** —— 把散落各处的情绪值、涨跌家数、连板高度、买卖点信号汇总到一处，攒成历史序列，辅助判断市场情绪拐点与买卖时机。

**在线体验**：<https://ss.fx8.store/>（CF Workers 主站，wrangler.jsonc 绑定，push main 自动 deploy，支持 br 压缩 + `_headers` CSP/HSTS）

**备用站点**：
- <https://sss.sugas.site/>（GitHub Pages）
- <https://s.sugas.site/>（MaoziYun，300MB 总大小限制）
- <https://ssd.fx8.store/>（R2 CDN，大 JSON 产物）

⚠️ 旧域 `tdsignal-ujpzw01zm.maozi.io` / `s.aisusu.cn` 已撤 DNS 不可达。

![市场温度看板 · tdsignal](static-site/og.png)

`trade-data-signal` / `tdsignal` / `tdsignal-ujpzw01zm`

---

## ✨ 核心功能

### 🌡️ 情绪温度计
- **A股综合情绪分**（0-100，6 指标加权：涨跌比/涨停数/炸板率/连板高度/成交额/北向资金）
- **跨市场综合评分**（去极值截尾均值，跨 A股/港股/全球）
- **恐贪指数**（8 情绪分等权合成）
- 6 个宽基指数独立情绪分：上证50 / 沪深300 / 中证500 / 中证1000 / 创业板 / 科创50
- 阈值标注：< 20 = 冰点 🔵，> 80 = 过热 🔴

### 📈 买卖点信号（事件化 + 回测验证）
- **主买**：RSI(14) 上穿 30（超卖反弹拐点）
- **辅买**：布林下轨回归（BB lower revert，强势市更敏感）
- **卖点**：20 日高点回落 5% + MA60 多头过滤 + MACD 死叉确认
- 每个信号附 **回测统计**（胜率/盈亏比/样本数/凯利仓位），样本不足自动标注
- **113 品种模拟回测**：全历史信号 × 5/10/20 日 forward 收益

### 📊 市场宽度
- 涨跌家数、涨停/跌停、连板高度、炸板率、封板率、打板溢价
- 涨跌家数比 + 腾落线（AD Line）
- 成交量对比（放量/缩量标注）
- 新高新低家数（52 周 / 20 日）

### 🏭 行业与轮动
- 申万 31 行业涨跌幅热力图（近 1 日 / 近 5 日切换）
- 行业资金流 + 换手率 + 行业内宽度
- 板块轮动速度（5/10/20 日窗口）
- 行业卡片标注对应主流 ETF（点击复制）

### 🏦 期货机构持仓
- 中金所 IF/IC/IH/IM 前 20 会员净多空持仓
- 机构 / 中信 / 国君 三角色持仓追踪
- 同向准确率（跟随机构）+ 逆向准确率（对冲思维）

### 📌 大盘位置感
- 8 指数当前价格在历史区间的分位（进度条可视化）
- 均线排列状态（多头/空头/震荡统计）
- 一句话总结（规则引擎 + 历史回看）

### 🎨 体验与扩展
- **关于页** `/about`（static-site/about.html，9 大 section + 回测表格 + 风险提示 + 目录锚点）
- **策略实验室** `/lab`（lab.js/lab.css，备买 chip 三档 + 参数优化 + 回测）
- **PWA 移动端增强**（manifest.json + sw.js，可安装 + 离线缓存，静态 SWR + 动态 JSON network-first 保证不看到旧数据）
- **4 主题皮肤**（default/dark/redgold/morandi），默认红金中国（localStorage 空时回退 redgold）
- **CSS critical 首屏优化**（inline critical 8.8KB + lazy load preload + FOUC 防护 4 主题变量）
- **queries.py 共享查询层**（app/queries.py，22 函数 DRY，main.py/export.py 共用）

---

## 🛠️ 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.11 + FastAPI + SQLite |
| 前端 | 原生 JS + ECharts（无构建步骤） |
| 数据源 | akshare（东财/新浪/腾讯）+ mootdx（TCP 日线）+ BaoStock |
| 部署 | Cloudflare Workers（wrangler deploy，GH Actions .github/workflows/deploy-cf.yml 自动化，加速 20min->1-2min）+ R2 CDN（大 JSON 产物 ssd.fx8.store）/ 本地 FastAPI（动态） |
| 定时 | macOS launchd，8 个计划任务（主采集 update_all 17:50；另有 intraday 09:35-15:35 每点/futures 20:05&21:00/lhb 18:30&19:30/rzhb 19:15/etf-national-team 20:07&21:30/backfill-evening 02:00&16:35&20:00/lab-auto 19:00） |

**特点**：
- 全量免费数据源，无 API key
- 指标配置驱动（`config/indicators.yaml`），增删改不动核心代码
- 双部署：动态版（FastAPI 实时查询）+ 静态版（预生成 JSON，CF Workers + R2 CDN 加速）
- 历史 10 年回溯（mootdx 全 A 股日线 16M 行 + BaoStock 校验）

---

## 🚀 快速开始

```bash
# 1. 安装依赖（国内镜像）
python3 -m venv .venv
.venv/bin/pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt

# 2. 初始化数据库
.venv/bin/python -m app.db

# 3. 首次回填历史数据
.venv/bin/python -m app.backfill

# 4. 启动看板（二选一）
cd /Users/linhuichen/code/trade-data && /Users/linhuichen/code/trade/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000   # 动态版:看页面 + 调 /api/* 读 DB
# ⚠️ cwd=trade-data/ 让 app/db.py .absolute() 读最新主库(trade-data/data/sentiment.db),非 trade/ 滞后镜像
# 或纯静态:python -m http.server -d static-site --port 8000
# 浏览器打开 http://localhost:8000
```

### 定时采集（每交易日 17:50，update_all 主采集）

共 8 个 launchd 计划任务（主采集 `com.trade.sentiment.plist` + 7 辅助任务在 `~/Library/LaunchAgents/`，7/18 重构后日志在 `trade-data/data/logs/`）。

```bash
cp launchd/com.trade.sentiment.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.trade.sentiment.plist
```

或一键脚本 `bash scripts/update_all.sh`（采集 + 静态导出 + 推送部署）。

---

## 📁 项目结构

```
app/
├── collector/      # 采集层（akshare/mootdx/baostock + em_get 防封）
├── compute/        # 计算层（signals 买卖点 / sentiment 情绪分 / cross 跨市场分）
├── db.py           # SQLite schema
└── main.py         # FastAPI 端点（挂载 static-site/ 到根 /，/api/* 读 DB）
static-site/        # 前端（Cloudflare Workers 部署；FastAPI 动态版挂载根 /）
config/indicators.yaml  # 指标注册表（增删改这里）
scripts/            # 采集/部署/一键更新脚本
```

详细文档：
- [REQUIREMENTS.md](REQUIREMENTS.md) - 需求 + 数据字典 + 公式披露
- [NOTES.md](NOTES.md) - 调研笔记 + 修复历史
- [docs/data-dictionary.md](docs/data-dictionary.md) - 数据字典（`static-site/data/` JSON 字段说明）
- [docs/data-sources.md](docs/data-sources.md) - 数据源说明（akshare/mootdx/baostock/HKEX/CCASS/东财/同花顺/新浪/腾讯等）
- [docs/LICENSE-data.md](docs/LICENSE-data.md) - 数据集 CC BY 4.0 授权声明

---

## 📊 数据集说明（可复用）

本看板每日盘后采集产出的 `static-site/data/` 下 JSON 数据集**对外开放可复用**，无需 API key，直接 HTTP 拉取即可。

### 在线数据访问

| 站点 | 用途 |
|---|---|
| `https://ss.fx8.store/data/{filename}` | Cloudflare Workers 主站（push main 自动 deploy，支持 br 压缩） |
| `https://sss.sugas.site/data/{filename}` | GitHub Pages 备站 |
| `https://ssd.fx8.store/data/{filename}` | R2 CDN（大 JSON 产物如 `industry-3y-indices/sw_*.json`） |

示例：`curl https://ss.fx8.store/data/overview.json | jq .` 拉今日快照。

### 核心数据文件

- `overview.json` - 今日快照（恐贪/情绪/涨跌/买卖点/冰点/indices_sparkline 等）
- `sentiment-{3m,6m,1y,3y,5y,all}.json` - 情绪指数历史（9 个情绪分序列 + signals/stats/strategy）
- `a-stock-{3m,6m,1y,3y,5y,all}.json` - A 股 32 指标（a_fund_north/a_fund_margin/a_fund_main/a_amount 等）+ 12 宽基指数 OHLC
- `hk-{3m,6m,1y,3y,5y,all}.json` - 港股 3 宽基 + 8 板块指数 + 港股通
- `global-{3m,6m,1y,3y,5y,all}.json` - 全球指数 + 商品/汇率/债券
- `industry-{3m,6m,1y,3y,5y,all}.json` - 申万 31 行业 + 27 同花顺概念（大文件已拆分到 R2 CDN）
- `etf_national_team-*.json` - 12 只宽基 ETF 国家队资金动向（份额变动 + 信号 + 持有人）
- `futures.json` - 中金所 IF/IC/IH/IM 期货机构持仓
- `summary.json` / `summary_history.json` - 收盘速递（规则引擎 + 历史回看）
- `signal_stats.json` - 113 品种买卖点回测统计（5d/10d/20d forward 收益）
- `index/{id}-all.json` - 44 个指数全历史 OHLC + signals + stats + strategy
- `intraday_snapshot.json` - 盘中实时快照（09:35–15:00 每 15 分钟更新）

字段说明详见 [docs/data-dictionary.md](docs/data-dictionary.md)，数据来源详见 [docs/data-sources.md](docs/data-sources.md)。

### 采集时点

- **17:50（CST）** 主采集 [`scripts/update_all.sh`](scripts/update_all.sh)：4 条并行 pipeline（core 快核心 / width 慢宽度 / futures 期货 / stock_daily 后台死端），约 31 分钟跑完，当日下午即可看到当日数据
- **09:35–15:00 盘中** 每 15 分钟跑 `intraday_snapshot` 推 `intraday_snapshot.json` 实时快照
- 另有 7 个辅助 launchd 任务（futures/lhb/rzhb/etf-national-team/backfill-evening/lab-auto/schedule-monitor），详见 [docs/data-sources.md](docs/data-sources.md#采集时点-launchd-8-个任务)
- 非交易日跳过采集仅 deploy + check_signals；盘中 09:30-15:30 拒跑全量 export+deploy（防覆盖 intraday 实时版）

### 数据时效

| 类型 | 时效 |
|---|---|
| A 股宽度/资金/情绪分 | T+0 当日（17:50 后） |
| 港股指数 | T+0 当日 |
| 美股指数 | T+1（时差，次日 17:50 采到前一日） |
| 申万一级行业 | T+1 偶发（申万官方 trend API 偶尔 T+1 才发） |
| 北向资金季度净买额 | 季度（2024-08 港交所新规改季度披露，CCASS 季度末+20 天后发布） |
| ETF 持有人结构 | 半年（cninfo 年报/半年报 PDF，滞后 2-3 月） |

### 🌐 数据开源（全量数据在独立数据仓库）

本看板**代码 MIT 开源**；每日盘后产出的**全量数据在独立数据开源仓库**
[trade-data-signal-staticdata](https://github.com/xp13465/trade-data-signal-staticdata)（数据开源门面）：

- **JSON 数据产物**（857 个文件 / 约 943MB）：情绪指数 / A股宽度 / 港股 / 全球 / 行业概念 / ETF 国家队 / 44 指数全历史 等，
  在 R2 公开桶 `https://ssd.fx8.store/` 直链下载，无鉴权、无需 API key
- **原始 SQLite 数据库**：`sentiment.db` / `etf_national_team.db` / `stock_daily.db` / `public_fund.db`
  打包 tar.gz 挂在数据仓库 GitHub [Releases](https://github.com/xp13465/trade-data-signal-staticdata/releases)
- **授权**：[CC BY 4.0](https://github.com/xp13465/trade-data-signal-staticdata/blob/main/DATA_LICENSE)，第三方声明见数据仓库 [NOTICE](https://github.com/xp13465/trade-data-signal-staticdata/blob/main/NOTICE)

**研究 / 复现 / 离线使用**时一键复原全部数据集：

```bash
git clone https://github.com/xp13465/trade-data-signal-staticdata.git
cd trade-data-signal-staticdata
bash fetch_data.sh        # 按 manifest.json 从 R2 下载全部 JSON（约 1GB，可重复跑，已下载自动跳过）
```

- 数据清单 `manifest.json`（含 `url` / `size` / `sha256` 校验）与还原脚本 `fetch_data.sh` 均在数据仓库
- 在线按需拉取单个文件（无需 clone）：`curl -o overview.json https://ssd.fx8.store/data/overview.json`
- 数据文件清单与格式：见 [docs/data-dictionary.md](docs/data-dictionary.md)（字段说明）与 [docs/data-sources.md](docs/data-sources.md)（数据源与采集时点）

---

## ⚠️ 声明

本看板仅供学习研究，**不构成投资建议**。买卖点信号为历史回测参考，胜率接近随机，不可作为独立交易依据。数据准确性受数据源限制，请以官方披露为准。

## 📄 License

- **代码**：[MIT](LICENSE)（`app/` / `scripts/` / `static-site/` 的 `.py` / `.js` / `.css` / `.html` 等）
- **数据集**：[CC BY 4.0](https://github.com/xp13465/trade-data-signal-staticdata/blob/main/DATA_LICENSE)
  —— 全量数据（JSON 产物 + 原始 SQLite 数据库）授权声明在**数据开源仓库**
  [trade-data-signal-staticdata](https://github.com/xp13465/trade-data-signal-staticdata)
- **第三方声明**：见数据仓库 [NOTICE](https://github.com/xp13465/trade-data-signal-staticdata/blob/main/NOTICE)
- 简述版见 [docs/LICENSE-data.md](docs/LICENSE-data.md)

数据来源均为公开免费数据源（akshare / mootdx / BaoStock / HKEX / CCASS / 东财 / 同花顺 / 申万 / 中证指数公司 / 新浪 / 腾讯 / CFFEX / cninfo），详见 [docs/data-sources.md](docs/data-sources.md)。

本看板仅供学习研究，**不构成投资建议**，详见上方免责声明。
