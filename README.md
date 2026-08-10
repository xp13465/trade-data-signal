# 📊 市场温度看板 · tdsignal

> **多源 A股情绪看板** —— 把散落各处的情绪值、涨跌家数、连板高度、买卖点信号、ETF 评分、策略实验室汇总到一处，
> 攒成历史序列，用**数据挖掘**从数千笔回测交易中反推出"降亏过滤标志"，每日用 **AI** 生成白话速递，
> 辅助判断市场情绪拐点与买卖时机。

```
    __    ___  ____
   / /   / _ \|  _ \  __ _ ___ _ __ ___   __ _ _ __   __ _ _ __
  / /__ | | | | | | |/ _` / __| '_ ` _ \ / _` | '_ \ / _` | '_ \
 /____/ | |_| | |_| | (_| \__ \ | | | | | (_| | | | | (_| | | | |
         \___/|____/ \__,_|___/_| |_| |_|\__,_|_| |_|\__,_|_| |_|
```

**一句话**：免费数据源 + 情绪指数 + ETF 评分 + 凯利仓位回测 + 数据挖掘降亏过滤 + AI 每日速递，
一个把「数据采集 → 计算 → 可视化 → 交易信号 → 信号质量挖掘 → AI 解读」全链路打通的开源 A股看板。

![market-status](https://img.shields.io/badge/语言-中文-brightgreen)
![python](https://img.shields.io/badge/Python-3.11-3776AB)
![fastapi](https://img.shields.io/badge/FastAPI-✓-009688)
![frontend](https://img.shields.io/badge/前端-原生JS%20%2B%20ECharts-FF6384)
![storage](https://img.shields.io/badge/存储-Cloudflare%20Workers%20%2B%20R2-F38020)
![ai](https://img.shields.io/badge/AI-DeepSeek%20每日速递-4D6BFE)
![mining](https://img.shields.io/badge/挖掘-子群发现%20·%20决策树%20·%20对比集-8A2BE2)
![schedule](https://img.shields.io/badge/调度-macOS%20launchd-lightgrey)
![license-code](https://img.shields.io/badge/代码-MIT-green)
![license-data](https://img.shields.io/badge/数据-CC%20BY%204.0-yellowgreen)

---

**在线体验**：<https://ss.fx8.store/>（CF Workers 主站，wrangler.jsonc 绑定，push main 自动 deploy，支持 br 压缩 + `_headers` CSP/HSTS）

**备用站点**：
- <https://sss.sugas.site/>（GitHub Pages）
- <https://s.sugas.site/>（MaoziYun，300MB 总大小限制）
- <https://ssd.fx8.store/>（R2 CDN，大 JSON 产物）

⚠️ 旧域 `tdsignal-ujpzw01zm.maozi.io` / `s.aisusu.cn` 已撤 DNS 不可达。

![市场温度看板 · tdsignal](static-site/og.png)

`trade-data-signal` / `tdsignal` / `tdsignal-ujpzw01zm`

---

## ✨ 功能亮点

### 🌡️ 情绪温度计
- **A股综合情绪分**（0-100，6 指标加权：涨跌比/涨停数/炸板率/连板高度/成交额/北向资金），10 年历史回溯
- **跨市场综合评分**（去极值截尾均值，跨 A股/港股/全球）+ **恐贪指数**（8 情绪分等权合成）
- 6 个宽基指数独立情绪分：上证50 / 沪深300 / 中证500 / 中证1000 / 创业板 / 科创50
- 阈值标注：< 20 = 冰点 🔵，> 80 = 过热 🔴

### 📈 买卖点信号（事件化 + 回测验证）
- **主买**：RSI(14) 上穿 30（超卖反弹拐点）；**辅买**：布林下轨回归（强势市更敏感）；**卖点**：20 日高点回落 5% + MA60 多头过滤 + MACD 死叉确认
- 每个信号附 **回测统计**（胜率/盈亏比/样本数/**凯利仓位**），样本不足自动标注
- **113 品种模拟回测**：全历史信号 × 5/10/20 日 forward 收益

### 🎯 ETF 评分弹窗（5 区块）
- 决策头 / 手数 or 卖出 / 置信度 / 8 维度评分 / 历史类比，仓位红线断线保护，指数↔ETF 全匹配

### 🚦 信号灯 + 降亏过滤 toggle
- 信号列表信号灯统一配色（分级档位 + 低置信灰蓝虚线），hover 显示减亏/损盈/比值三项
- **降亏过滤开关**：数据挖掘发现的"系统性亏损特征组合"一键 toggle（详见「参考与致敬」段）

### 📊 市场宽度 / 🏭 行业轮动 / 🏦 期货机构持仓
- 涨跌家数、涨停/跌停、连板高度、炸板率、封板率、腾落线、52 周新高新低
- 申万 31 行业热力图（1 日/5 日）+ 行业资金流 + 轮动速度 + 对应 ETF 标注
- 中金所 IF/IC/IH/IM 前 20 会员净多空持仓，同向/逆向准确率

### 🤖 每日 AI 速递（deepseek）
- 收盘后自动生成 **daily_brief 白话解读**（deepseek 生成，本地合规 gating），邮件直发
- 邮件正文**白话化**：期货风向 + 公募基金解读，非模板套话

### 📱 体验与扩展
- 盘中**分时多源批量实时**（同花顺批量 + 东财 push2delay2，3 请求根治降并发，1 分钟自愈轮询机制）
- **PWA 移动端**（可安装 + 离线缓存 + iOS 安全区 + 通知面板）
- **4 主题皮肤**（default/dark/redgold/morandi），默认红金中国
- **策略实验室** `/lab`（备买 chip 三档 + 参数优化 + 凯利回测 + 费率/收益口径客调）
- 数据挖掘方法论实战（决策树/beam search/对比集/贪心，详见「参考与致敬」）

---

## 🏗️ 系统架构

```
                    ┌─────────────────────────────────────────────────────┐
                    │                 采集层（多源互备）                  │
                    │   mootdx(TCP)  BaoStock  腾讯  东财  同花顺  申万   │
                    │   中证指数  HKEX/CCASS  CFFEX  cninfo  美指/黄金    │
                    └─────────────────────────────────────────────────────┘
                                               │  launchd 定时调度
        ┌─────────────────────────────┬───────────────────────────┬────────────────────┐
        │ 17:50 update_all 并行流水线 │ 盘中每10min intraday 快照 │ 盘后 export+deploy │
        │ (core/width/futures/stock)  │    (R2 实时,不推 main)    │  (静态 JSON 产物)  │
        └─────────────────────────────┴───────────────────────────┴────────────────────┘
                                               ▼
                    ┌─────────────────────────────────────────────────────┐
                    │           存储层（R2 / CF Static Assets）           │
                    │   全量品种/大range历史序列 → R2 桶 ssd.fx8.store    │
                    │        小状态文件 → CF Workers Static Assets        │
                    └─────────────────────────────────────────────────────┘
                                               │  git push main → CF 自动 deploy
                    ┌──────────────────────────▼──────────────────────────┐
                    │                 前端层（多端一致）                  │
                    │   主站 ss.fx8.store  CF Workers (br压缩+_headers)   │
                    │          备站 sss.sugas.site  GitHub Pages          │
                    │            备站 s.sugas.site   MaoziYun             │
                    │          dataUrl: -all/5y/3y 大文件直连 R2          │
                    └─────────────────────────────────────────────────────┘
                                               │
                    ┌──────────────────────────▼──────────────────────────┐
                    │                浏览器端（SPA + SW）                 │
                    │    原生JS + ECharts · Service Worker 版本化缓存     │
                    │        PWA · 4主题 · 分时1min自愈轮询 · 通知        │
                    └─────────────────────────────────────────────────────┘
```

**数据流**：多源采集（防单源封禁，互备降并发）→ SQLite 主库（`sentiment.db` / `etf_national_team.db`）→
指标计算 → 静态 JSON 产物 → R2/CF 分发 → 前端渲染；小文件走 CF，大文件走 R2 直链，`manifest.json + sha256` 全程可校验。

---

## 🛠️ 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.11 + FastAPI + SQLite（`sentiment.db` / `etf_national_team.db`） |
| 采集 | mootdx（TCP 全 A 日线 16M 行）+ BaoStock（校验）+ 腾讯/东财/同花顺（互备）+ 申万/中证/HKEX/CCASS/CFFEX/cninfo |
| 前端 | 原生 JS + ECharts（分时/恐贪/评分弹窗/信号卡/策略实验室）+ Service Worker + PWA，`build_min.py` 压缩 + 版本号破缓存 |
| 存储 | Cloudflare Workers（主站）+ R2 对象存储（全量品种/大 range 历史序列）+ GitHub Pages / MaoziYun（备站） |
| AI | DeepSeek（每日速递白话生成 + 邮件白话化） |
| 调度 | macOS launchd：17:50 主采集并行流水线 / 盘中每 10min intraday 快照 / 盘后 export+deploy / futures/lhb/rzhb/etf-national-team/backfill/lab-auto/schedule-monitor |
| 部署 | GH Actions deploy-cf.yml + wrangler deploy（加速 20min→1-2min），push main 自动上线 |

**特点**：
- 全量免费数据源，无 API key；多源互备防单源封禁
- 指标配置驱动（`config/indicators.yaml`），增删改不动核心代码
- 双部署：动态版（FastAPI 实时查询）+ 静态版（预生成 JSON，CF Workers + R2 CDN 加速）
- 历史 10 年回溯 + 数据一致性铁律（N 展示位 / N 缓存同版同步）

---

## 🎓 参考与致敬（References & Acknowledgements）

> 本项目的很多模块站在开源社区 / 学术界 / 公开数据源的肩膀上。在此逐一致谢 —— **致敬不是贴标签，是"我真的用了，且说清用在哪"**。

### 📐 数据挖掘方法论（降亏过滤多轮挖掘）

**用途**：`策略实验室` 的凯利回测，从 **44,832 笔真实模拟交易** 中反推「系统性亏损特征组合」作为降亏过滤开关（v1→v4 四轮挖掘，最终 Greedy 组合净提升 PF 1.285→1.713，净 +149 万）。

| 方法 | 致敬来源 | 本项目用在哪 |
|---|---|---|
| **子群发现 Subgroup Discovery** | Lavrac/Flach/Kavsek《Adapting classification rule induction to subgroup discovery》(2002)；Atzmueller (2015) 综述；pysubgroup WRAccQF | v3 找高纯度"亏损显著过代表"子群，支撑"比值>2 高纯度子群"路线 |
| **决策树 CART** | Breiman et al. (1984)；手写多路分裂（非 sklearn） | v3 路径提取 = 规则，路径亏损率 = 规则纯度 |
| **Beam Search** | 子群发现精炼启发式 (Valmarska/Lavrač/Fürnkranz 2017) | v3 子群候选搜索（depth4 beam30） |
| **对比集挖掘 Contrast Set Mining** | Webb et al.; growth rate = supp_loss/supp_gain | v4 找"亏损组显著过代表"条件集（1-4 itemset 主路线） |
| **涌现模式 / JEP** | Dong & Li (1999) Emerging Pattern | v4 识别"只出现在亏损组的模式"（盈利组 support=0） |
| **Apriori / Closed Itemset** | Agrawal & Srikant (1994) | v4 4-itemset Apriori（1502 个 ratio>3）+ 去冗余验证 |
| **贪心组合优化** | 经典贪心逐步选择 | v4 Greedy-7/15 从 930 候选产出最终 toggle 集 |
| **Walk-forward 滚动验证** | 时间序列前向验证范式 | 未来 v5 方向：t-1 年选 toggle、t 年验证，防过拟合 |
| **Decision Set 互斥规则集** | 规则集互斥设计 | 未来 v5 方向：每笔交易至多命中一条规则 |
| **PSM 倾向得分匹配** | Rosenbaum & Rubin (1983) | 未来 v5 方向：消除选择偏差、验证净效果非混淆因素所致 |
| **漂移检测 Drift Detection** | 概念漂移 (concept drift) | 未来 v5 方向：检测标志有效性随时间漂移（5 月 shift 发现雏形） |
| **4 窗口稳定性验证** | out-of-sample 验证共识 | 历轮：比值>2 + maxSh<0.60 + 逐年验证，防 5 月 shift 类过拟合 |

> 完整推导、文献清单与代码见项目内文档：
> - [`docs/kelly-loss-mining-methods.md`](docs/kelly-loss-mining-methods.md) — 8 种方法 Python 代码 + CrossRef 学术文献完整清单 + 推荐流程
> - [`docs/kelly-mining-literature.md`](docs/kelly-mining-literature.md) — 文献/方法论/方案引导速查（fresh context agent 复用）
> - [`docs/kelly-loss-mining-v3.md`](docs/kelly-loss-mining-v3.md) / [`-v4.md`](docs/kelly-loss-mining-v4.md) — 各轮完整推导与候选清单
> - 方法论也受 **"信号过滤 = 训练分类器预测信号质量，过滤低质量信号即减亏"** 这一交易行业共识启发（Kissell《Machine Learning Techniques》; Zhang & Pinsky 策略-分类模型类比）

### 🤖 多 Agent 协作模式（traderagent 启发）

**用途**：本项目用**多 agent 分工做开发协作**——调研 agent（只读定位根因）→ 实施 agent（写码）→
reviewer agent（独立批判性查影响面 + 回归 smoke）→ 测试 agent，配 cron 兜底轮询 + 进度文件回写，
借鉴 **traderagent 风格的多智能体团队模式**（分析师/研究员/交易员/风控分工协作）来组织工程流水线：
- 数据产品线：采集 agent（多源互备）→ 计算 agent → 上线 agent（deploy 三站验证）
- 开发质量线：实施 → reviewer（独立 review 防改坏老功能）→ 主控逐字验收
- 复盘线：总结 agent（过错/经验沉淀）→ 复核 agent（独立复核防总结跑偏）

> 工程规范与协作机制详见 [`CLAUDE.md`](CLAUDE.md)（§2 监工 loop / §11 通知兜底 / §15 回归 / §16 agent 画像）。

### 🧠 AI 预测与解读（DeepSeek）

**用途**：`每日速递` 邮件 —— 收盘后由 DeepSeek 生成 **daily_brief 白话解读**（情绪拐点 + 信号汇总 + 合规 gating），
邮件正文对 **期货风向 / 公募基金** 做白话化改写，让"机器算出来的数字"变成"人读得懂的话"。

### 📚 公开数据源致谢

本看板 100% 使用免费公开数据源，无 API key。没有这些开源项目与公开接口，就没有这个看板：

| 数据源 | 用途 | 类型 |
|---|---|---|
| [mootdx](https://github.com/mootdx/mootdx) | 全 A 股 TCP 日线（历史 10 年回溯） | 开源库 |
| [BaoStock](https://github.com/baostock) | 指数/日线校验与补采（8/10 指数 + kc50 兜底） | 开源库 |
| [akshare](https://github.com/akfamily/akshare) | 东财/新浪/腾讯行情统一接口 | 开源库 |
| 腾讯行情 / 东财 push2 | 盘中分时批量实时 + 主力资金 | 公开接口 |
| 同花顺 | 概念板块/行情批量 | 公开接口 |
| 申万宏源 / 中证指数公司 | 行业分类与指数行情 | 公开数据 |
| HKEX / CCASS | 港股指数 + 北向持仓披露 | 公开数据 |
| CFFEX | 期货机构持仓 | 公开数据 |
| cninfo | 公募基金 / ETF 持有人结构 | 公开数据 |

> 数据源细节、采集时点与合规说明见 [`docs/data-sources.md`](docs/data-sources.md)。

---

## 📊 数据开源（全量数据在独立数据仓库）

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
- 核心数据文件：`overview.json` 今日快照 / `sentiment-*.json` 情绪历史 / `a-stock-*.json` A股 32 指标 / `industry-*.json` 行业概念 / `etf_national_team-*.json` 国家队 ETF / `futures.json` 期货持仓 / `index/{id}-all.json` 44 指数全历史 / `intraday_snapshot.json` 盘中快照
- 字段说明与数据字典：见 [`docs/data-dictionary.md`](docs/data-dictionary.md)（字段说明）与 [`docs/data-sources.md`](docs/data-sources.md)（数据源与采集时点）

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

### 采集时点

- **17:50（CST）** 主采集 [`scripts/update_all.sh`](scripts/update_all.sh)：4 条并行 pipeline（core 快核心 / width 慢宽度 / futures 期货 / stock_daily 后台死端），约 31 分钟跑完，当日下午即可看到当日数据
- **09:35–15:00 盘中** 每 10 分钟跑 `intraday_snapshot` 推 `intraday_snapshot.json` 实时快照（走 R2 实时，不推 main）
- 另有 7 个辅助 launchd 任务（futures/lhb/rzhb/etf-national-team/backfill-evening/lab-auto/schedule-monitor）
- 非交易日跳过采集仅 deploy + check_signals；交易日盘中 09:30-15:30 拒跑全量 export+deploy（防覆盖 intraday 实时版）

---

## 📁 项目结构

```
app/
├── collector/          # 采集层（mootdx/baostock/腾讯/东财 多源互备 + em_get 防封）
├── compute/            # 计算层（signals 买卖点 / sentiment 情绪分 / cross 跨市场分）
├── queries.py          # 共享查询层（22 函数 DRY，main.py/export.py 共用）
├── db.py               # SQLite schema
└── main.py             # FastAPI 端点（挂载 static-site/ 到根 /，/api/* 读 DB）
static-site/            # 前端（Cloudflare Workers 部署；FastAPI 动态版挂载根 /）
config/indicators.yaml  # 指标注册表（增删改这里）
scripts/                # 采集/部署/一键更新/构建压缩脚本
launchd/                # macOS 定时任务 plist
docs/                   # 文档（数据字典/数据源/数据挖掘文献/回测分析/许可声明）
```

**详细文档**：
- [REQUIREMENTS.md](REQUIREMENTS.md) - 需求 + 数据字典 + 公式披露
- [NOTES.md](NOTES.md) - 调研笔记 + 修复历史
- [docs/data-dictionary.md](docs/data-dictionary.md) - 数据字典（`static-site/data/` JSON 字段说明）
- [docs/data-sources.md](docs/data-sources.md) - 数据源说明 + 采集时点
- [docs/kelly-loss-mining-methods.md](docs/kelly-loss-mining-methods.md) - 数据挖掘方法论 + 文献（降亏过滤）
- [docs/LICENSE-data.md](docs/LICENSE-data.md) - 数据集 CC BY 4.0 授权声明

---

## 📡 监控与告警

- **schedule_monitor**：launchd 定时任务状态监控，异常自动发邮件（告警去重，15min 周期不轰炸）
- **check_data_integrity**：数据产物完整性校验（deploy 前置，关键 JSON 空值率超标即阻断上线）
- **check_r2_consistency**：本地 vs R2 一致性审计（数据一致性铁律）
- **self_heal**：盘中保护 update_all，脚本吞异常（exit=0 假成功）自动识别
- **分时自愈轮询**：前端 1min 轮询 5 阶段自愈（超时/去重/降频/心跳/切前台清 in-flight），7x24 不卡死
- **mac 休眠根治**：pmset 工作日唤醒 + caffeinate 防跑期间休眠

---

## ⚠️ 声明

本看板仅供学习研究，**不构成投资建议**。买卖点信号为历史回测参考，胜率接近随机，不可作为独立交易依据。
数据准确性受数据源限制，请以官方披露为准。数据挖掘发现的降亏标志为统计特征，存在过拟合与漂移风险，使用前请复核 4 窗口稳定性。

## 📄 License

- **代码**：[MIT](LICENSE)（`app/` / `scripts/` / `static-site/` 的 `.py` / `.js` / `.css` / `.html` 等）
- **数据集**：[CC BY 4.0](https://github.com/xp13465/trade-data-signal-staticdata/blob/main/DATA_LICENSE)
  —— 全量数据（JSON 产物 + 原始 SQLite 数据库）授权声明在**数据开源仓库**
  [trade-data-signal-staticdata](https://github.com/xp13465/trade-data-signal-staticdata)
- **第三方声明**：见数据仓库 [NOTICE](https://github.com/xp13465/trade-data-signal-staticdata/blob/main/NOTICE)
- 简述版见 [docs/LICENSE-data.md](docs/LICENSE-data.md)

数据来源均为公开免费数据源（akshare / mootdx / BaoStock / HKEX / CCASS / 东财 / 同花顺 / 申万 / 中证指数公司 / 新浪 / 腾讯 / CFFEX / cninfo），详见 [docs/data-sources.md](docs/data-sources.md) 与上方「参考与致敬」段。

本看板仅供学习研究，**不构成投资建议**，详见上方免责声明。
