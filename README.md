# 📊 信号实验室 · tdsignal

> **A股/港股/全球盘后复盘情绪数据看板** —— 把散落各处的情绪值、涨跌家数、连板高度、买卖点信号、ETF 评分、策略实验室汇总到一处，
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
一个把「数据采集 → 计算 → 可视化 → 交易信号 → 信号质量挖掘 → AI 解读 → 自动交易执行」全链路打通的开源情绪数据看板。

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

![信号实验室 · tdsignal](static-site/og.png)

`trade-data-signal` / `tdsignal`

---

## ✨ 功能亮点

### 🌡️ 情绪温度计
- **A股综合情绪分**（0-100，6 指标加权：涨跌比/涨停数/炸板率/连板高度/成交额/北向资金），10 年历史回溯
- **跨市场综合评分**（去极值截尾均值，跨 A股/港股/全球）+ **恐贪指数**（8 情绪分等权合成）
- 6 个宽基指数独立情绪分：上证50 / 沪深300 / 中证500 / 中证1000 / 创业板 / 科创50
- 阈值标注：< 20 = 冰点 🔵，> 80 = 过热 🔴
- **情绪分买卖点信号列表**（市场温度顶行，与冰点/过热热力图同排同高）：首页信号列表已过滤情绪分信号（情绪分是 0-100 衍生指标非可交易标的、无 ETF 参考），此处单独列出 A股综合/跨市场/恐贪/6 宽基共 9 类情绪分的买卖点信号作情绪拐点逆向参考，红=卖（高位回落）、紫=辅买（下轨拐点）、绿=买（超卖拐点），点击查看走势+标注

### 📈 买卖点信号（事件化 + 回测验证）
- **主买**：RSI(14) 上穿 30（超卖反弹拐点）；**辅买**：布林下轨回归（强势市更敏感）；**卖点**：20 日高点回落 5% + MA60 多头过滤 + MACD 死叉确认
- 每个信号附 **回测统计**（胜率/盈亏比/样本数/**凯利仓位**），样本不足自动标注
- **113 品种模拟回测**：全历史信号 × 5/10/20 日 forward 收益

### 🎯 ETF 评分弹窗（5 区块）
- 决策头 / 手数 or 卖出 / 置信度 / 8 维度评分 / 历史类比，仓位红线断线保护，指数↔ETF 全匹配

### 🚦 信号灯 + 降亏过滤 toggle
- 信号列表信号灯统一配色（分级档位 + 低置信灰蓝虚线），hover 显示减亏/损盈/比值三项
- **降亏过滤开关**：数据挖掘发现的"系统性亏损特征组合"一键 toggle（详见「参考与致敬」段）
- **组合降亏预设宏（2026-08-11 新增，1月调整为 2026-08-11 元素级重组追加）**：4 个命名组合（年末季节 / 稳健核心 / 最大化降亏 / 1月调整），点击组合自动勾选成员 toggle、过滤仍走成员谓词并集（幂等可叠加，多组合=成员并集 OR）；组合勾选态由成员派生（全勾=勾选/部分=半选），hover 显示组合并集口径指标（年末季节 6.50 / 稳健核心 5.95 / 最大化降亏 greedy15——⚠2026-08-12 AI宏 后已从默认剔除（posK2 下边际 -20 万净利杀手，勿与 AI宏 同开）/ 1月调整 J1 4.71、J2 4.49），成员选择依据国外特征选择/组合方法论（IV/WoE、mRMR、RFE、Lasso、López de Prado 特征聚类等，见「参考与致敬」段）
- **1月调整组合（2026-08-11 元素级重组挖掘；2026-08-12 用户拍板并入默认推荐组合默认开启——"只要有增幅就做"，fixed 口径 G 模式 all 增量 +1.2 万/+0.77pp，全 9 模式正增量合计 +7.0 万）**：18,047 个元素交叉组合全扫描发现的唯一新边际——1 月中旬（11-20 日）+ mid 评级（J1，比值 4.71 / 4 窗口全 >2 / 与现有标志 90% 不重叠，附监控 maxSh 0.62）与 1 月中旬+追关注（J2，比值 4.49，覆盖更广）；只做中旬（1 月上旬=盈利口袋全负 -56 万不可动），验证见 [`docs/kelly-jan-adjust-combo-verify.md`](docs/kelly-jan-adjust-combo-verify.md)
- **组合使用建议 + 全信号表（2026-08-12 新增，真实回测口径）**：凯利回测区顶部置顶两块——①**组合使用建议**：回答"4 个组合全开好不好 + 怎么用"（4 组合全开保留 76% 交易、净利 +1,087 万（原始 +1,034 万）、胜率 +5pt、最大回撤减半；组合叠加边际 1月调整 +33.6 万最大；分追高/短线/长线/保守 4 种投资习惯 + 总建议=全信号都看+完全遵守交易页面交易方法（卖出信号 G 模式）），全部数字来自复刻本页过滤/统计管线的真实回测，分析文档 [`docs/kelly-combo-usage-advice.md`](docs/kelly-combo-usage-advice.md)；②**全信号表（最后结果）**：全信号=评级高低分区并集（全量信号不拆分），实时随降亏组合勾选/费率档/周期切换联动 + 按年窗口增长表（净盈亏/累计/胜率/峰值资金收益率——峰值资金收益率=该年累计净盈亏/该年峰值同时持仓资金×100，与卡面/建议面板同口径；4 组合全开 2019 起累计持续增长，2024 +429 万 / 2025 +986 万 / 2026 +1,087 万；2023 -48 万属市场性弱年）；交易记录弹窗中被降亏/仓位控制淘汰的交易以**删除线灰化**展示（不计入统计，仅对照哪些被淘汰）
- **仓位控制过滤 positionCap（2026-08-12 新增，K 敏感性回测；2026-08-12 起默认开启 K=2 + 4 个降亏推荐（AI宏=新默认：追关注×熊市/J1/J2/n2，2026-08-12 用户拍板"替换默认(AI宏=新默认)"，A45/A5 移出默认；数据支撑 /tmp/agent-progress-kelly-ai-macro.md）——5 个默认推荐 toggle（含仓位控制）以金色高亮+⭐ 默认推荐徽标+hover 推荐理由展示，其余 27 个独立小 toggle 默认收起（「组合降亏」行内「细标志(27)展开」按钮手动展开调试）；展开后按 **4 组经济逻辑分组**展示（日历效应·季节调仓 16 / 信号质量·弱信号 3 / 复合并集·广谱管理 7 / 市场防御·大盘择时 1，组内比值降序、⚠监控成员置尾、⚠慎用标注，2026-08-12 纯展示层重归类，不改过滤逻辑））**：金额口径固定=**每笔固定 1 万**（2026-08-12 移除"每日资金池等分"——用户原话"1w 还分 30 个信号买 30 份没意义，仓位控制 1/2/3/4 已足以"）；不勾仓位控制=每笔 1 万买全部信号（原始基线，最大持仓 1,218 万），勾上=每笔 1 万+只买当日最优 K 个。**仓位控制过滤**=按 signal_date 分组当日基笔信号，组内按 跟踪分→评级→信号类型→买入日 排序保留前 K 个，K 可配置 1-4 默认 2（每笔固定 1 万口径 G 模式回测：关=收益率 32.27%/最大持仓 1,218 万；K=1 收益率 48.58% 最高但净利砍最狠 +78.7 万/持仓 162 万；K=2 默认平衡 40.41%/+119.2 万/295 万；K≥3 趋近买全部；⚠fixed 口径下 K 档=收益率↑ vs 净利↓ 权衡）。交易页当日信号列表联动：前 K 个标「建议执行」、其余「当日已满（仓位控制）」灰显。与降亏同开仅推荐 AI宏 默认组合（excludeSpecialBear/janMidRating/janMidSpecial/n2NovSpecialIndustry，默认已开启），绝不同开 live4/COMBO4 全开/greedy 广谱（详见 §21 算法公示与 [`docs/kelly-position-cap-k-sensitivity.md`](docs/kelly-position-cap-k-sensitivity.md)）

### 📊 市场宽度 / 🏭 行业轮动 / 🏦 期货机构持仓
- 涨跌家数、涨停/跌停、连板高度、炸板率、封板率、腾落线、52 周新高新低
- 申万 31 行业热力图（1 日/5 日）+ 行业资金流 + 轮动速度 + 对应 ETF 标注
- 中金所 IF/IC/IH/IM 前 20 会员净多空持仓，同向/逆向准确率

### 🤖 每日 AI 速递（deepseek）
- 收盘后自动生成 **daily_brief 白话解读**（deepseek 生成，本地合规 gating），邮件直发
- **首页并排展示**：横幅「🤖 AI 预测」与「📜 历史收盘分析」并排，弹窗内历史列表分页反查（点开某日=预测内容+meta断言+次日实际涨跌+命中标记）+ 近30/90日命中率（meta机检次日回填）
- **多角色协作式预测**：6 角色子 prompt 编排（技术面/资金面/情绪面/风控分析师并行 → 研究员多空辩论 → 主编组装合规），每角色只喂自己数据域（缩小数据域控幻觉），任一环节失败自动降级单 prompt 主链路；`--multi` 开关或配置 `multi_agent_enabled` 开启，研究员可切 `deepseek-reasoner` 深度辩论（P1-11）
- **辩论详情 + 结论 + 弃用标志**：每条预测首行显示 `🧭 结论`（融合结论=研究员多空辩论收敛结果，不展开即可见）与版本徽标（弃用标志：`🤖 多角色`=6角色完整版（默认）／`旧版单模型`=多角色版上线前旧版（已被取代）／`⚠️ 降级版`=AI生成失败规则兜底（无多角色辩论）／`⚠️ 精简版`=最小兜底，降级/精简版仅供参考）；「🧠 多角色讨论详情」折叠面板可展开看四角色结论与多空论据（标题标角色数与论据数）；AI 预测弹窗 / 历史收盘分析结合展示 / 公示行三处统一（2026-08-12）
- **卖信号口径分层**：买/卖计数只算**真实指数可交易信号**（非 `s.*`，与首页信号列表过滤口径一致）；情绪分模拟信号（`s.*` 前缀 0-100 衍生指标，非可交易标的）单独统计为「情绪买/卖」并标注"情绪分"，横幅 chip / AI 预测 / 历史收盘分析三处口径统一
- **预测把握度 confidence（0-100）**：每次预测必带把握度评分（合规风控）——主编基于多空辩论收敛结果（论据充分性/分歧度/数据支持度）输出整数 0-100 把握度 + 1 句把握度理由：高把握 70-100 / 中等 55-70 / 低把握 30-55 / 看不清 0-30，低把握时方向更倾向震荡不硬猜；规则版/最小版兜底默认 50 保前端零破坏
- **历史收盘分析结合 AI 预测**：弹窗内每日收盘分析下方并排展示对应日期 AI 预测（方向断言+把握度+四段解读+命中标记），AI 预测弹窗默认展开预测内容
- 邮件正文**白话化**：期货风向 + 公募基金解读，非模板套话

### 🤖 飞书机器人通知（2026-08-11 新增，通知分级到 3 群 + 群内提需求）
- **发送链路**：`notify.py` 新增飞书渠道（企业自建应用 `tenant_access_token` + `im/v1/messages` API），按通知类别路由到 3 群——**运维群**（SEVERE 告警 + 计划任务异常）/ **开发群**（agent 完成通知）/ **报告群**（收盘分析 + 盘中信号 + 小时级节点），`--feishu-group` 可显式覆盖，`--feishu-only` 调试单渠道
- **接收链路**：`feishu_ws_listener.py` 长连接常驻（lark-oapi WS Client + launchd KeepAlive，免公网回调），订阅 `im.message.receive_v1`，白名单群 + `需求:`/`t:` 前缀过滤后落盘 `data/feishu_requests/`，主控 cron 轮询整理进 TASKS 待办（补齐 harness 无可靠入向通知的空缺）；落盘成功后**立即秒级回执**「已收到需求…，主控 1 分钟内开始处理」（引用回复用户那条具体消息 reply_to_message_id，best-effort，发送失败不阻塞落盘）
- **邮件兜底保留**：飞书失败不阻塞邮件（best-effort），SEVERE 告警邮件始终发（防飞书故障无通知）
- 实现见 [`docs/feishu-bot-integration-plan.md`](docs/feishu-bot-integration-plan.md)，飞书开放平台能力见「参考与致敬」段

### 📱 体验与扩展
- 盘中**分时多源批量实时**（同花顺批量 + 东财 push2delay2，3 请求根治降并发，1 分钟自愈轮询机制）
- **PWA 移动端**（可安装 + 离线缓存 + iOS 安全区 + 通知面板）
- **4 主题皮肤**（default/dark/redgold/morandi），默认红金中国
- **走势图轻量渲染（2026-08-12）**：首页**全部** ECharts 图表换**轻量 SVG**（外观逐项对等：网格/坐标轴/图例/平滑曲线 + 面积 + 涨跌分色 + 阈值线/买卖点信号 pin(含多信号拼色渐变)/热力图 + hover tooltip），消灭首页全部 echarts.init（~39 sparkline + 恐贪/A股情绪分/市场宽度/跨市场/腾落线/成交额与量比/新高新低 + 行业热力图 + KPI 详情弹窗 + 信号弹窗 + 分时图）提速 200-500ms；皮肤弹窗「⚡ 走势图渲染」一键切回 ECharts 完整版（localStorage 记忆，即时双向重渲染），ETF 评分弹窗近30日走势同开关
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
                                               │  交易信号（可选接执行）
                    ┌──────────────────────────▼──────────────────────────┐
                    │       自动交易执行（可选 · 独立仓库 thsautoorder）    │
                    │      easytrader 二次开发 · 验证码识别 · API 队列监听  │
                    │        看板交易信号 → 自动下单（程序化需备案）        │
                    └─────────────────────────────────────────────────────┘
```

**数据流**：多源采集（防单源封禁，互备降并发）→ SQLite 主库（`sentiment.db` / `etf_national_team.db`）→
指标计算 → 静态 JSON 产物 → R2/CF 分发 → 前端渲染；小文件走 CF，大文件走 R2 直链，`manifest.json + sha256` 全程可校验。
前端展示的交易信号可接**自动交易执行**（可选，easytrader 二次开发 → [thsautoorder](https://github.com/xp13465/thsautoorder)，独立仓库）。

---

## 🛠️ 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.11 + FastAPI + SQLite（`sentiment.db` / `etf_national_team.db`） |
| 采集 | mootdx（TCP 全 A 日线 16M 行）+ BaoStock（校验）+ 腾讯/东财/同花顺（互备）+ 申万/中证/HKEX/CCASS/CFFEX/cninfo |
| 前端 | 原生 JS + ECharts（分时/恐贪/评分弹窗/信号卡/策略实验室）+ Service Worker + PWA，`build_min.py` 压缩 + 版本号破缓存 |
| 存储 | Cloudflare Workers（主站）+ R2 对象存储（全量品种/大 range 历史序列）+ GitHub Pages / MaoziYun（备站） |
| AI | DeepSeek（每日速递白话生成 + 邮件白话化） |
| 交易执行 | easytrader 二次开发 → [thsautoorder](https://github.com/xp13465/thsautoorder)（独立仓库）：验证码识别 / API 接口队列监听 / 可用性提升 |
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
| **子群发现 Subgroup Discovery** | Lavrac/Flach/Kavsek《Adapting classification rule induction to subgroup discovery》(2002)；Atzmueller (2015) 综述；[pysubgroup](https://github.com/flemmerich/pysubgroup) WRAccQF | v3 找高纯度"亏损显著过代表"子群，支撑"比值>2 高纯度子群"路线 |
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

### 📐 组合降亏（特征选择 / 组合方法论，2026-08-11 新增）

**用途**：`策略实验室` 凯利回测的「组合降亏预设宏」——把已有降亏 toggle 打包成命名组合（年末季节/稳健核心/最大化降亏/1月调整），成员选择与组合验证复用国外特征选择/组合方法论（详见 [`docs/kelly-combo-signal-research.md`](docs/kelly-combo-signal-research.md) 调研 + [`docs/kelly-combo-round3-verify.md`](docs/kelly-combo-round3-verify.md) 数据验证 + [`docs/kelly-jan-adjust-combo-verify.md`](docs/kelly-jan-adjust-combo-verify.md) 1月调整元素级验证）。「1月调整」组合来自元素级重组挖掘（18,047 组合全扫描，用户"摘取要素交叉成新标志"直觉的直接产出）：5 标志要素拆解后 1 月是真空地带，1 月中旬（11-20 日）+ mid 评级为唯一新边际（比值 4.71、4 窗口全 >2、与现有标志 90% 不重叠、live4 之上边际 +14.4 万）。组合=成员 toggle 的打包宏，过滤仍走成员谓词并集（零新增过滤逻辑、幂等可叠加、组合勾选态由成员派生），满足「用户视角 N 展示位数据一致」铁律。

| 方法 | 致敬来源 | 本项目用在哪 |
|---|---|---|
| **IV 信息值 / WoE（评分卡）** | Siddiqi《Credit Risk Scorecards》(Wiley, 2006)，FICO 评分卡标准 | 比值（降亏%/损盈%）= 本项目"亏损组 vs 盈利组偏斜强度"的 WoE/IV 交易版，按比值排序选成员 |
| **mRMR 最小冗余最大相关** | Peng, Long & Ding (IEEE TPAMI, 2005) | 组合成员两两 Jaccard 重叠率 <40% 判据（低重叠=去相关互补） |
| **RFE 递归特征消除** | Guyon et al. (Machine Learning, 2002) | 组合成员逐一 drop 验证边际贡献（v4 Closed Itemset 去冗余已实现） |
| **Lasso / Elastic Net（L1 稀疏）** | Tibshirani (JRSS-B, 1996)；Zou & Hastie (JRSS-B, 2005) | 若未来做"成员加权评分"式组合，Lasso 给成员稀疏权重 |
| **特征聚类 + 多重共线性** | López de Prado《Advances in Financial Machine Learning》(Wiley, 2018) Ch.8 | 组合成员先做交易集重叠聚类（同簇只留最强代表），直接决定"进组合/排除谁"；重要性须 OOS 算、高相关特征先正交化 |
| **DSR / PBO 防过拟合度量** | Bailey & López de Prado (JPM 2014 / JCF 2017) | 1502 itemset 挖掘后组合选择的多重试验惩罚（本项目用 maxSh+4 窗口近似） |
| **多重检验校正（t>3 / FDR）** | Harvey, Liu & Zhu (RFS 2016)；Benjamini & Hochberg (JRSS-B 1995) | 成员进组合阈值比单次检验更严（4 窗口全>2 + maxSh<0.6 双门槛） |
| **alpha 组合收缩** | Kakushadze《101 Formulaic Alphas》(2016) | 标志高度相关时组合权重应收缩→组合选低相关成员 |
| **低相关因子分散组合** | Asness, Frazzini, Israel & Moskowitz (JPM 2014) | 组合跨独立经济逻辑线（11/12 月末、纯非五月、广谱 Greedy），不堆叠同逻辑标志 |
| **Walk-forward 滚动验证** | Pardo《The Evaluation and Optimization of Trading Strategies》(Wiley, 1992/2008) | 组合评估标准流程：t-1 年选成员、t 年验证（pre2025 选样/2025+ 验证两段全 >2 才稳） |
| **决策集互斥规则集** | Lakkaraju, Bach & Leskovec (KDD 2016) | 组合优先低重叠成员（决策集宽松版），现用并集幂等无害 |

### 🤖 多 Agent 协作模式（traderagent 启发）

**用途**：本项目用**多 agent 分工做开发协作**——调研 agent（只读定位根因）→ 实施 agent（写码）→
reviewer agent（独立批判性查影响面 + 回归 smoke）→ 测试 agent，配 cron 兜底轮询 + 进度文件回写，
借鉴 **traderagent 风格的多智能体团队模式**（[原版 tradingagents](https://github.com/tauricresearch/tradingagents) / [中文改版 TradingAgents-CN](https://github.com/hsliuping/TradingAgents-CN)，分析师/研究员/交易员/风控分工协作）来组织工程流水线：
- 数据产品线：采集 agent（多源互备）→ 计算 agent → 上线 agent（deploy 三站验证）
- 开发质量线：实施 → reviewer（独立 review 防改坏老功能）→ 主控逐字验收
- 复盘线：总结 agent（过错/经验沉淀）→ 复核 agent（独立复核防总结跑偏）
- 内容生产线：`每日 AI 速递` 的预测同样借鉴 **TradingAgents-CN 的多角色辩论方案**——6 个角色子 prompt（技术/资金/情绪/风控/研究员/主编）各自只注入对应数据域、独立分析后互相校验/辩驳，再由主编合成白话解读（不做交易决策角色，合规）

> 工程规范与协作机制详见 [`CLAUDE.md`](CLAUDE.md)（§2 监工 loop / §11 通知兜底 / §15 回归 / §16 agent 画像）。

### 🧠 AI 预测与解读（DeepSeek）

**用途**：`每日速递` 邮件 —— 收盘后由 [DeepSeek](https://platform.deepseek.com/) 生成 **daily_brief 白话解读**（情绪拐点 + 信号汇总 + 合规 gating），
邮件正文对 **期货风向 / 公募基金** 做白话化改写，让"机器算出来的数字"变成"人读得懂的话"。

### 🔁 自动交易执行（easytrader → thsautoorder）

**用途**：把看板交易信号接上真实下单执行（**可选独立模块**，不进主站点运行链路）。基于开源库
[easytrader](https://github.com/shidenggui/easytrader)（MIT，模拟操作同花顺等客户端 + miniQMT 官方接口模式）做二次开发，
产出独立仓库 [thsautoorder](https://github.com/xp13465/thsautoorder) 独立迭代。二次开发点：**验证码识别**（登录稳定性）、
**API 接口队列监听**（看板信号 → 下单指令）、**可用性提升**（客户端版本变化自愈）。
> 📦 本仓库以 **git submodule** 方式关联 thsautoorder：`easytrader_deploy/` 目录 = submodule，指向 `https://github.com/xp13465/thsautoorder`（自动跟随新仓库迭代）。**git clone 本项目需加 `--recurse-submodules`** 才会拉取该子模块；已 clone 的项目用 `git submodule update --init` 补拉。
> ⚠️ 合规：程序化交易（含低频）须备案，未备案即交易 = 违规（详见 NOTES.md 调研）。本看板只出信号不自动下单，自动执行模块独立可选。

### 📚 公开数据源致谢

本看板 100% 使用免费公开数据源，无 API key。没有这些开源项目与公开接口，就没有这个看板：

| 数据源 | 用途 | 类型 |
|---|---|---|
| [mootdx](https://github.com/mootdx/mootdx) | 全 A 股 TCP 日线（历史 10 年回溯） | 开源库 |
| [BaoStock](https://github.com/baostock) | 指数/日线校验与补采（8/10 指数 + kc50 兜底） | 开源库 |
| [akshare](https://github.com/akfamily/akshare) | 东财/新浪/腾讯行情统一接口 | 开源库 |
| [a-stock-data](https://github.com/simonlin1212/a-stock-data) | 策略实验室回测信号生成（`scripts/lab/*.py` runtime import `gen_buy_signals` / `gen_sell_signals`）+ 采集层东财防封 / 腾讯行情实现参考其 SKILL.md | 开源仓库（代码复用） |
| 腾讯行情 / 东财 push2 | 盘中分时批量实时 + 主力资金 | 公开接口 |
| 同花顺 | 概念板块/行情批量 | 公开接口 |
| 申万宏源 / 中证指数公司 | 行业分类与指数行情 | 公开数据 |
| HKEX / CCASS | 港股指数 + 北向持仓披露 | 公开数据 |
| CFFEX | 期货机构持仓 | 公开数据 |
| cninfo | 公募基金 / ETF 持有人结构 | 公开数据 |

> 数据源细节、采集时点与合规说明见 [`docs/data-sources.md`](docs/data-sources.md)。

### 🤖 飞书开放平台（lark-oapi）

**用途**：`notify.py` 飞书发送渠道 + `feishu_ws_listener.py` 长连接接收进程（企业自建应用收发一体）。

| 能力 | 致敬来源 | 本项目用在哪 |
|---|---|---|
| **飞书开放平台**（自建应用） | [飞书开放平台](https://open.feishu.cn)（中国版域名 open.feishu.cn） | 发消息 API `im/v1/messages`（tenant_access_token 鉴权）+ 长连接事件订阅 `im.message.receive_v1`；应用进 3 群按 chat_id 分组路由 |
| **lark-oapi 官方 SDK** | [lark-oapi](https://github.com/larksuite/oapi-sdk-python)（官方 Python SDK） | `feishu_ws_listener.py` 用 `lark_oapi.ws.Client`（WS 长连接，SDK 自带断线重连）收群消息，事件分发器 `EventDispatcherHandler.register_p2_im_message_receive_v1` |

> 完整实现、3 群映射与接收落盘格式见 [`docs/feishu-bot-integration-plan.md`](docs/feishu-bot-integration-plan.md)。

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
