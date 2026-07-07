# A股/港股/全球 情绪数据复盘看板 · 需求文档

> **本文件是项目需求的唯一真实来源（single source of truth）。**
> 每次开工前先读此文件，了解当前目标与已定/未定项。
> 状态图例：✅ 已定 ｜ ⏳ 待确认 ｜ ⬜ 未开始

最近更新：2026-07-05（买卖点优化 B1+S1：买加 BB 下轨回归辅买点 buy_aux + 卖叠加 MA60 多头过滤；卖/买比 3.02→0.49）

---

## 1. 项目概述

一个**盘后复盘**用的金融情绪数据看板。每日收盘后定时采集 A 股、港股、全球市场的情绪/宽度/资金/结构类指标，存入本地数据库，前端用**按天**的历史折线图展示趋势与拐点，支持周期按钮切换时间窗口；并基于采集数据计算 A 股综合情绪分与跨市场综合评分、在指数图上标注买点/卖点。

**核心价值**：把散落各处的「情绪值、涨跌家数、连板高度」等专业数据汇总到一处，攒成历史序列，辅助复盘判断市场情绪拐点（冰点/过热）与买卖时机。

---

## 2. 已确认决策 ✅

| 项 | 决策 | 备注 |
|---|---|---|
| 使用场景 | 盘后复盘记录 | 非盘中实时；每日收盘后跑一次 |
| 技术栈 | Python + FastAPI + SQLite + ECharts | 前端为本地网页 |
| 部署 | Mac 本地 | 不上服务器，不需实时推送 |
| 定时器 | launchd（倾向） | Mac 原生、开机自启；实现时最终定 |
| 数据来源 | 手动录入 + 公开爬取（akshare） | akshare 1.18.64，经国内镜像安装已验证可用 |
| 历史回溯 | 先采集 1 年起 | 见 §5；后续可延 |
| A 股综合情绪分 | 6 项加权打分 0–100 | 见 §4 |
| 跨市场综合评分 | 去极值截尾均值 0–100 | 见 §6 |
| 买点/卖点标注 | 买=RSI 上穿30（C1 主）+ BB下轨回归（B1 辅 buy_aux）；卖=20日高回落5% ∧ close>MA60（D1+S1） | 见 §7 |
| 宽基指数 | 上证/深成/沪深300/中证500/中证1000/创业板/科创50 | 见 §8 |
| 指标去留原则 | **先全量采集，复盘看过实际数据后再筛减** | 采集与展示均配置驱动、可插拔 |
| 外部数据库 | 用户提供仓库 `simonlin1212/a-stock-data` | ⚠️ github.com DNS 不通，待用户本地提供后做字段映射（非阻塞，先用 akshare） |
| pip 依赖安装 | 国内镜像（清华/阿里/腾讯） | ⚠️ pypi.org DNS 不通；东财/腾讯数据源可直连 |
| 环境风险 | 东财 `index_global_spot_em` 间歇 ProxyError | 已验证；用 sina 源兜底 + 失败重试 |

---

## 3. 指标清单 ✅（全量纳入，先采后筛）

> **原则：先全量采集（含试采项），复盘看过实际数据后再定去留；指标配置驱动、可插拔，便于后续增删。** 明细口径见 §8。

A 股 · 市场宽度：涨跌家数 / 涨停·跌停数 / 连板高度 / 炸板率 / 封板率 / 打板溢价
A 股 · 资金面：北向资金 / 两融余额 / 主力净流入
A 股 · 情绪指数：综合情绪分 / 换手率 / 成交额 / 乐咕活跃度 / 东财情绪 / QVIX（中国 VIX）
A 股 · 宽基指数：上证 / 深成 / 沪深300 / 中证500 / 中证1000 / 创业板 / 科创50
A 股 · 板块与轮动：行业板块涨跌幅 / 行业资金流 / 概念板块涨跌幅 🆕试采
A 股 · 龙虎榜：上榜家数 / 机构净买入 🆕试采
A 股 · 解禁：解禁规模 / 解禁家数 🆕试采
A 股 · IPO：数量 / 募资额 🆕试采
A 股 · 可转债：转股溢价率 / 数量 🆕试采
港股：恒生 / 恒生科技 / 恒生国企 / 港股通净买入
全球：美股三大指数 / QVIX / 美元指数 / 离岸人民币 / 黄金 / 原油

---

## 4. A 股综合情绪分 ✅

**口径：自算 6 项加权 + 现成指数旁证**（2026-07-05 定）

### 综合情绪分（0–100，主图）
加权打分，各分项用**过去 120 个交易日滚动百分位**归一化到 0–100（1 年回溯内可稳定输出 8 个月；窗口可调）：

| 分项 | 权重 | 方向 | 数据源（akshare） |
|---|---|---|---|
| 涨跌家数比（涨/(涨+跌)） | 25% | 越高越热 | 全 A spot `stock_zh_a_spot_em` |
| 涨停数 | 20% | 越多越热 | `stock_zt_pool_em` |
| 炸板率 | 15% | 越低越热（反向） | `stock_zt_pool_zbgc_em` |
| 连板高度（最高连板） | 15% | 越高越热 | `stock_zt_pool_em` |
| 成交额 | 10% | 越大越热 | 指数成交 |
| 北向资金净流入 | 15% | 越多越热 | `stock_hsgt_hist_em` |

阈值：**< 20 = 冰点**，**> 80 = 过热**。权重初版如上，跑出数据后可调。

### 现成指数（旁证列）
- 乐咕市场活跃度（`stock_market_activity_legu`）✅ 已验证
- QVIX 中证 1000/300 ETF 期权波动率（`index_option_300etf_qvix` / `index_option_1000index_qvix`）✅ 已验证，2755 天历史
- 东财市场情绪（接口待验证）

---

## 5. 其他模块（默认方案，待 veto）⏳

- [x] **更新频率**：每交易日 15:30 后跑一次全量采集（盘后复盘，不做盘中）。
- [x] **历史深度**：先回溯 1 年；后续可延。
- [x] **折线展示**：按天粒度折线图；提供周期按钮切换时间窗口 —— **1 月 / 3 月 / 6 月 / 1 年 / 全部**。
- [x] **手动录入**：提供「每日补录」表单（日期 + 指标名 + 值 + 备注），用于 akshare 未覆盖项或主观打分；与自动采集数据合并展示。
- [x] **看板布局**：分页式 —— 概览 / A股 / 港股 / 全球 / 综合情绪 共 5 个 tab。不用单页大屏（盘后在笔记本上看，大屏太挤）。
- [x] **告警**：冰点/过热日在看板上高亮 + 记入告警日志表；暂不做 macOS 推送（需要再加）。
- [x] **指标可插拔**：采集器与前端图表均配置驱动，新增/删除指标改配置即可，不动核心代码。
- [x] **交易日历**：用 `tool_trade_date_hist_sina` 判断交易日，定时任务仅在交易日执行。
- [x] **补采**：采集失败自动重试 + 缺失检测 + 支持手动触发补采。
- [x] **存储**：每日单值指标用宽表，变长数据（板块 Top5 等）用长表；手动录入覆盖同日自动值。
- [x] **首次启动**：库为空自动回填 1 年，之后每日增量；综合分/买卖点每日计算落库。
- [x] **本地访问**：端口 8000，桌面浏览器优先，中文界面；akshare 调用间加小延迟 + 重试防限流。
- [ ] **数据源细节**：akshare 接口已对齐（见 §4/§6/§8，多数已验证）；用户数据库 `simonlin1212/a-stock-data` 待本地提供后做字段映射。

---

## 6. 跨市场综合评分 ✅

与 §4 并列的**第二个综合分**：跨 A 股/港股/全球 的整体市场温度。

- **输入**：所有采集指标各自归一化到 0–100（120 日滚动百分位；反向指标取反——VIX/QVIX、美元指数、炸板率、USD/CNH 人民币贬值方向）
- **聚合**：**去掉最高 1 个 + 最低 1 个**（去极值，即"去除最高最低的最大偏差"），其余取算术均值 → 0–100
- **阈值**：< 20 = 冰点，> 80 = 过热（同 §4）
- **去极值个数可调**：指标多时可改去 top/bottom 2 或按 10% 截尾
- **与 §4 区别**：§4 是 A 股 6 项固定权重加权；本评分跨三市场、等权、去极值，视野更宽更稳健

---

## 6.5 情绪分公式透明度（公开披露，BUG-G）✅

> 合成情绪分（`a_sentiment` / `cross_market`）非黑盒，权重公式与输入源全部公开。实现见 `app/compute/sentiment.py` + `app/compute/cross.py` + `app/compute/normalize.py`，以下为可审计的精确公式。

### A. A 股综合情绪分 `a_sentiment`（§4，固定权重加权）

**公式**：`score = Σ(weight_i × norm_i) / Σ(weight_i for available i)`（缺项按可用重归一化权重，至少 3 个分项才出分，避免单分项误导）。

**归一化 `norm_i`**：各分项原始值经 **120 日滚动百分位**（`rolling(120).rank(pct=True) × 100`，`min_periods=10`）映射到 0–100；`direction=negative` 的分项取反（`100 - p`，即越低越热→归一化后越高越热）。

| 分项 key | 权重 | 输入 metric_id | 方向 | 数据源 |
|---|---:|---|---|---|
| ratio | 25% | `a_width_up_count` / `a_width_down_count`（涨/(涨+跌)） | positive | `stock_zh_a_spot_em` 全 A spot |
| zt | 20% | `a_width_zt_count`（涨停数） | positive | `stock_zt_pool_em`（近 2 周）/ mootdx 历史 |
| zhaban | 15% | `a_width_zhaban_rate`（炸板率） | **negative**（越低越热） | `stock_zt_pool_zbgc_em` |
| lianban | 15% | `a_width_max_lianban`（连板高度） | positive | `stock_zt_pool_em` |
| amount | 10% | `a_amount`（成交额） | positive | 指数成交 |
| north | 15% | `a_fund_north`（北向资金净流入） | positive | `stock_hsgt_hist_em`（2024-08 停更） |

**阈值**：< 20 = 冰点，> 80 = 过热。**已知限制**：涨停板池接口仅近 2 周历史，`a_sentiment` 历史段（2016-2026）由 `width_history.py` 从 mootdx 全 A 日线按收盘封板口径回填补齐（zt 交叉校验误差 ~3%）；北向资金 2024-08 后停更冻结，故 `north` 分项在 2024-08 后缺失，按可用 5 分项重归一化权重出分。

### B. 跨市场综合评分 `cross_market`（§6，去极值截尾均值 / trimmed mean）

**公式**：`score = mean(sorted(vals)[1:-1])`（升序排序后去掉最高 1 个 + 最低 1 个，其余算术均值）。

**精确算法**（`cross.py::trim_mean`）：
1. 取当日所有 `type=simple && enabled=true` 的 metric（见下表），各自 `normalized()` 归一化（同上 120 日滚动百分位 + direction 取反）；
2. 该日 dropna，若可用指标 `< 3` 个返回 NA（不出分）；
3. 升序排序，`iloc[1:-1]` 去掉最低 1 个 + 最高 1 个（固定去 1 each side，**非 10% 截尾**；指标多时可改去 top/bottom 2 或按 10% 截尾）；
4. 其余取算术均值 → 0–100。

**当前 trim-mean 池**（`config/indicators.yaml` 中 `type: simple, enabled: true` 的全部 metric，按日动态 dropna——以下为有数据的指标；TODO func 未采集的不出分）：

| 类别 | metric_id（方向） |
|---|---|
| A 股宽度 | `a_width_up_count`(+) / `a_width_down_count`(−) / `a_width_zt_count`(+) / `a_width_dt_count`(−) / `a_width_max_lianban`(+) / `a_width_zhaban_rate`(−) / `a_width_daban_premium`(+) / `a_width_zb_count`(−) / `a_width_seal_rate`(+) |
| A 股资金 | `a_fund_north`(+) / `a_fund_margin`(+) / `a_fund_main`(+) |
| A 股情绪 | `a_qvix_300`(−) / `a_qvix_1000`(−) / `a_amount`(+) / `a_turnover_rate`(neutral) / `a_turnover_mean`/`median`/`p90`/`p10`(neutral) / `a_turnover_gt5_pct`(neutral) / `a_div_yield`(−) |
| 港股 / 全球 | `hk_south`(+) / `usdcnh`(−) / `gold`(−) / `oil`(neutral) / `wti_oil`(neutral) / `comex_silver`(neutral) / `cn10y`(neutral) / `us10y`(neutral) |
| 试采 | `lhb_count`(+) / `lhb_inst_net`(+) / `unlock_amount`(−) / `unlock_count`(−) / `ipo_count`(neutral) / `ipo_amount`(neutral) / `cov_count`(neutral) / `cov_premium_median`(neutral) |

> 注：`cn_us_spread` 是 `type: derived`（cn10y − us10y），**不进** trim-mean 池（derived 已含其成分 cn10y/us10y，避免双重计入）。`a_width_fengban_rate` 同理 derived 不进。`direction: neutral` 的指标归一化不取反（直接用滚动百分位）。各指标在缺失日（NaN）被 dropna 跳过，故不同日期参与均值的指标数不同（早期年份池小、近期池大）。

**阈值**：< 20 = 冰点，> 80 = 过热（同 §4）。**与 §4 区别**：§4 固定 6 项加权（A 股 only，权重固定）；§6 跨三市场、等权、去极值（池随配置动态变，视野更宽更稳健，单指标极端值被剔除不污染总分）。

---

## 7. 买点 / 卖点逻辑 ✅

**当前规则：买=RSI 事件化（C1 主）+ BB下轨回归辅买点（B1 buy_aux）；卖=20日高回落5%（D1 high-based）∧ close>MA60（S1 多头过滤）**（2026-07-05 B1+S1 改，见 §7.4 / §7.7 / §9）

最初设计用「跨市场分冰点/过热 + MA 金叉死叉」，但实测发现跨市场分衡量的是宽度/资金情绪，与单只指数价格不同步（拉指数不拉个股时价格高但宽度弱→评分低），导致信号出现在价格高点。**改为指数自身 RSI 做主信号**（保证价格低位买、高位卖）。

E1 版曾用 cross 作共振硬门槛（买 cross<30 冰点、卖 cross>70 狂热）。实测发现近年市场宽度结构变化，cross 多数时落在 30-70 中性区，冰点/狂热极端态罕见，致**近端买点长期为 0、卖点也偏少**（近 1 年 buy 0 / sell 29）。C1 将 cross 降为分级标签写进 reason 供参考，不再作硬过滤，恢复信号可用性。

C1 卖点用 RSI 下穿 70，但回测显示它是**所有 12 个候选方案中最差的卖点**（全史 10 日胜率 43.1%/盈亏比 0.76/均值 +1.29%，信号后价格仍涨 1.29%，方向相反）。D1 改为「close 从近 20 日最高价回落 5%」（high-based），是回测 12 方案中**唯一在 2016+ 窗口达标（胜率 50.6% + 盈亏比 1.04）的卖点**，定位为「趋势转弱/止盈减仓提示」。详见 `07-卖点对策回测.md`。

B1+S1（2026-07-05，依据 `11-买卖点优化方案回测.md` 244 资产回测）：买点加 BB 下轨回归辅买点（buy_aux，与 C1 同为「超卖反弹」语义，强势市更敏感，互补 C1 盲区；回测买点 15007→38547 翻 2.57×，近 3 年 10日 盈亏比 1.18 不降质）；卖点叠加 MA60 多头过滤（仅 close>MA60 才放卖，砍下跌趋势假卖点；回测卖点 59830→36289 砍 39%、近 3 年胜率 55.0% vs D1 53.3%）。组合卖/买比 3.99→0.94（买卖平衡）。

- **买点·主**（C1，不动）= RSI(14) **上穿 30**（前一日 RSI ≤ 30 且当日 RSI > 30，超卖结束、价格有望反弹）。signal='buy'。
- **买点·辅**（B1，2026-07-05 加）= **BB 下轨回归**（前一日 close < 下轨 且当日 close > 下轨，从超卖区反弹回下轨之上）。signal='buy_aux'。C1 与 BB 同日触发时去重（保留 C1 主买）；buy_aux 也算买点（更新 vs前买 游标 + 参与盈亏标注）。
- **卖点**（D1 + S1）= close 从近 20 日最高价（**high-based**，必须用 high 不用 close）**回落 5%**（前一日 close ≥ 阈 且当日 close < 阈，阈 = 近 20 日 high 之 max × 0.95）**且 close > MA60**（60 日多头趋势才放卖，砍下跌趋势假卖点）。signal='sell'。
- **cross 不作硬门槛**，按分级标签附在 reason 末尾：`<30` 冰点 / `30-50` 偏冷 / `50-70` 中性 / `70-80` 偏热 / `≥80` 狂热。
- **RSI 在卖点降级为参考标签**（不作触发条件，附在 sell reason 末尾供参考）；买点 RSI 仍是主信号。

实现见 `app/compute/signals.py` 的 `compute()` + `_compute_value_signals()` + `_cross_tag()` + `_bollinger()`，high 由 `app/compute/normalize.py::load_index_high()` 加载。指数（close）与全球指标/情绪分（g.*/s.* value）均应用 B1+S1；a_sentiment 仍 skip_buy（RSI 结构性失效，buy 与 buy_aux 都跳过，仅算 sell）。

### 7.1 参数

| 参数 | 值 | 说明 |
|---|---|---|
| RSI 周期 | 14 | Wilder RSI（EWM α=1/14，`adjust=False`），见 `_rsi()` |
| 买触发阈值（C1 主） | 30（上穿） | `rsi_prev ≤ 30 且 rsi > 30`，前一日在超卖区（含边界）、当日升回 30 之上 |
| 买触发（B1 辅） | BB 下轨回归 | `bu,mid,bl = _bollinger(close,20,2.0)`；`buy_aux=(close_prev<bl_prev)&(close>bl)`。前一日跌破下轨、当日收回下轨之上 |
| 布林带 | MA20 ± 2σ（std ddof=0） | `mid=close.rolling(20).mean(); sd=close.rolling(20).std(ddof=0); bu=mid+2σ; bl=mid-2σ`（与 11 回测一致） |
| 卖触发（D1） | 20 日 high 回落 5% | `hh20 = high.rolling(20).max()`；`thresh = hh20*0.95`；`close_prev ≥ thresh_prev 且 close < thresh` |
| 卖过滤（S1） | close > MA60 | `ma60 = close.rolling(60,min_periods=60).mean()`；`sell = sell & (close > ma60)`。多头趋势才放卖，砍下跌市假卖点；MA60 前 60 日 NaN 时不放卖 |
| high-based | 必须用 high 不用 close | 回测实测 close-based 变体 2016+ 10d 胜率仅 45.6%（vs high-based 50.6%，差 5pp）；high 捕捉盘中真实波峰，close 漏掉日内高点 |
| cross 共振门槛 | 无（C1 去除） | E1 曾要求买 cross<30 / 卖 cross>70；C1 改为软分级标签，不作过滤 |

**cross 分级标签**（`_cross_tag()`，写进 reason 供参考，NaN 时省略）：

| 区间 | 标签 | 语义 |
|---|---|---|
| cross < 30 | 冰点 | 市场极度悲观，E1 旧买共振门槛 |
| 30 ≤ cross < 50 | 偏冷 | 情绪偏弱 |
| 50 ≤ cross < 70 | 中性 | 情绪居中（近年常态区间） |
| 70 ≤ cross < 80 | 偏热 | 情绪偏强 |
| cross ≥ 80 | 狂热 | 市场极度乐观，E1 旧卖共振门槛 |

### 7.2 语义说明

- **买·主在「超卖结束、升回 30 之上」时点**（C1，不动）：RSI 从 ≤30 升回 >30 那天，标价格有望反弹的拐点；不是 RSI 仍处于超卖区（≤30）的每一天。
- **买·辅在「跌破下轨后收回」时点**（B1，2026-07-05 加）：close 前一日跌破 BB 下轨、当日收回下轨之上，标超卖反弹辅买点（buy_aux）。语义与 C1 同为「超卖反弹」，但用价格穿越 BB 下轨而非 RSI 阈值，强势市更敏感（RSI 未到 30 但价格已破下轨），互补 C1 盲区。C1 与 BB 同日触发时去重（保留 C1 主买，signal='buy'）。**buy_aux 也算买点**：更新 `last_buy_close` 游标 + 参与 vs前买 盈亏标注。回测近 3 年 10日 盈亏比 1.18（vs C1 1.13，不降质）。
- **卖在「趋势转弱、跌破 5% 回落阈 且仍处多头趋势」时点**（D1+S1）：close 从近 20 日最高价回落 5% 那天，**且 close > MA60**（60 日均线多头）才标止盈减仓提示。S1 过滤砍下跌趋势中的假卖点（熊市 D1 频繁触发但多为下跌中继非止盈点）。语义从 C1 的「超买结束/有望回落」改为「**趋势转弱/止盈减仓提示**」——回测显示任何卖点都难有高胜率（指数向上漂移，D1 2016+ 10 日走弱概率仅 50.6%，接近随机），D1 是反应型信号（不预测顶部，反应已发生的弱势），契合「卖点难预测」的现实。**D1+S1 是止盈减仓提示，非做空/反向交易指令；胜率≈50% 接近随机，不可作为独立卖出指令**——只能作"该检查仓位了"的风险注意灯，需结合仓位成本（vs前买 标注）与趋势背景综合判断。UI/文案避免「做空/反向」与「高胜率卖点」暗示。
- **事件化**：只在「穿越」那一天标，一次连续超卖/回落期只产 1 个点。买点 RSI 反复进出超卖区则每次退出各 1 个点；卖点 close 反复穿越阈值则每次下穿各 1 个点，算独立事件。**结构上不可能出现连续两日的卖点**（T 日 sell 要求 close[T]<thresh[T]，T+1 日 sell 要求 close[T]≥thresh[T]，矛盾）。
- **cross 软分级**：cross 仅作情绪参考标签附在 reason，不影响是否出信号。用户可结合标签判断「技术面拐点 + 市场情绪背景」的强弱（如买点 cross=冰点 比 cross=狂热 更可信）。
- **首日处理**：`rsi.shift(1)` / `close.shift(1)` / `thresh.shift(1)` 首日为 NaN，`.fillna(False)` 跳过不标；`cross` 用 `reindex(close.index)` 对齐，缺失（NaN）时省略 reason 的 cross 段；`high` 用 `reindex(close.index)` 对齐，缺失（NaN）时 hh20 由 rolling 跳过。
- 注：信号为参考用，非交易指令。D1 卖点为「最不坏」方案（非「好」方案），**走弱概率≈50% 接近随机，不可作为独立卖出指令**——预期在震荡/下跌市提供有效止盈提示，在单边上涨市会产生假信号（趋势跟踪类信号的固有代价）。买点 C1 反而有微弱正期望（未来 10 日均值 +1.62%、收益>0 占比 61.8%），是更值得关注的 alpha 来源（详见 `10-买卖点配对回测.md`）。

### 7.3 reason 字符串格式

`signal_daily.reason` 字段记录触发细节便于核查（值取整 `:.0f`）：
- 买点·主（C1）：`RSI上穿30({rsi_prev:.0f}->{rsi:.0f}),cross={cross:.0f}[标签]`，例 `RSI上穿30(29->34),cross=8[冰点]`
- 买点·辅（B1，2026-07-05 加）：`布林下轨回归(下轨{bl:.0f},close{c:.0f}), RSI={r:.0f}, cross={cross:.0f}[标签]`，例 `布林下轨回归(下轨3852,close3870), RSI=41, cross=47[偏冷]`
- 卖点（D1+S1）：`20日高回落5%(高{hh:.0f}->阈{thresh:.0f},close{c:.0f}), RSI={r:.0f}, cross={cross:.0f}[标签], MA60={m:.0f}[趋势过滤], vs前买{±pct:.2f}%[分类]`，例 `20日高回落5%(高4259->阈4046,close4028), RSI=40, cross=53[中性], MA60=4000[趋势过滤], vs前买+2.30%[止盈]`
- RSI 为 NaN 时买点退化为 `RSI=NA`；卖点省略 `RSI=...` 段（RSI 在卖点仅作参考标签）。
- cross 为 NaN 时省略 `cross=...[标签]` 段。
- MA60 为 NaN（前 60 日）时不放卖（S1 过滤），故 sell 信号的 MA60 段恒有值。
- 标签取值见 §7.1 分级表（冰点/偏冷/中性/偏热/狂热）。
- **vs前买 分类标签**（方案 B，2026-07-06）：卖点 reason 末尾附 vs前买 标签，标注相对最近一次前置买点 close 的盈亏——`vs前买+X.XX%[止盈]`（close &gt; 前买点 close）/ `vs前买-X.XX%[买点失败]`（close &lt; 前买点 close）/ `无前买点[趋势中]`（窗口内无前置买点）。B1+S1 后 last_buy_close 游标由 buy 与 buy_aux 共同更新（buy_aux 也是买点）。详见 §7.6。

### 7.6 卖点盈亏标注（方案 B，2026-07-06）

D1 卖点定位为「趋势转弱/止盈减仓提示」，但同一卖点信号在不同持仓成本下操作含义不同——若卖点 close 低于最近买点 close，则该卖点对前置买点而言是**止损**而非止盈。方案 B 在卖点 reason 附 `vs前买{±X.XX%}[分类]` 标签，标注相对最近一次前置买点 close 的盈亏，便于用户判断卖点质量与操作建议。**只加标注，不改触发条件**（买点 C1 + 卖点 D1 触发逻辑不动，信号数不变）。

**实现**（`app/compute/signals.py::compute()`）：按 index_id 维护 `last_buy_close` 游标（每个指数独立，按 date 升序遍历）——遇到 buy 信号时更新 `last_buy_close = 该买点 close`；sell 触发时按 close vs last_buy_close 算 `pct=(close-last_buy_close)/last_buy_close*100` 并分类。

**分类与配色**：

| 分类 | 触发条件 | reason 标签 | 前端 markPoint 配色 | 操作建议 |
|---|---|---|---|---|
| 止盈 | close &gt; 前买点 close（pct &gt; 0） | `vs前买+X.XX%[止盈]` | 绿 `#2e8b57` | 趋势转弱减仓/止盈 |
| 买点失败 | close &lt; 前买点 close（pct &le; 0） | `vs前买-X.XX%[买点失败]` | 灰 `#9e9e9e` | 止损观望非止盈；已持仓止损、未持仓观望，等下个买点或 MA60 转多 |
| 无前买点 | 窗口内无前置买点（last_buy_close=None） | `无前买点[趋势中]` | 橙 `#ff9800` | 无前置买点参照，单独看趋势（不属止盈也不属止损） |

买点 markPoint 配色不变（红 `#e6492e`）。前端 `web/app.js::signalColor(s)` 按 reason 子串判断：含「买点失败」→灰、「止盈」→绿、「无前买点」→橙；`indexChart` 与 `renderIndustry` 的 markPoint 均改用 `signalColor(s)`。`ruleBar` 详细区加操作文案（盈亏标注说明 + 操作建议）。

**分布**（重算后，9162 卖点）：止盈 7227 / 买点失败 1739 / 无前买点 196。例：深证红利（sz_div）20260623 卖点 close 8300 vs 前买点 20260612 close 8496.65，pct=-2.32%，标 `vs前买-2.32%[买点失败]`（用户应止损观望非止盈）。

**注**：方案 B 只加标注，**买点 C1 + 卖点 D1 触发逻辑不动**，重算后信号数不变（全史 12473 = buy 3311 + sell 9162）。`last_buy_close` 游标按 index_id 分组维护（每个指数独立），按 date 升序遍历；同日既买又卖时先处理买（更新游标）再处理卖（pct=0 归买点失败，罕见边缘情况）。

### 7.4 变更历史

- **2026-07-05（初版）**：买 = RSI(14) ≤ 30 AND 跨市场分 < 80；卖 = RSI(14) ≥ 70 AND 跨市场分 > 20。跨市场分仅作「不矛盾」过滤（避免在情绪极端相反时下单）。每满足日都标 → 一次超卖期多日多标，信号密度过高。
- **2026-07-06（E1 优化）**：改为事件化 + 跨市场共振。买 = RSI 上穿 30 且 cross<30；卖 = RSI 下穿 70 且 cross>70。一次超卖/超买期只标 1 个点（穿越当日）。共振阈值从 <80/>20 收紧到 <30/>70。重算后 signal_daily 2425→113（-95.3%，buy 898→55 / sell 1527→58）。
- **2026-07-06（C1 软条件化）**：去掉 cross 硬门槛，买 = RSI 上穿 30、卖 = RSI 下穿 70（事件化不变，shift(1).fillna(False) 保留）。cross 降为分级标签（冰点/偏冷/中性/偏热/狂热）写进 reason。背景：近年市场宽度结构变化致 cross 多在 30-70 中性区，E1 的 cross<30/>70 硬门槛致近 1 年买点 0、卖点仅 29，信号可用性丧失。重算后 signal_daily 113→6893（近 1 年 buy 0→114 / sell 29→267；全史 buy 55→3311 / sell 58→3582）。reason 格式扩展为 `RSI上穿30(29->34),cross=8[冰点]`。
- **2026-07-06（D1 卖点优化）**：C1 卖点 RSI 下穿70 经回测验证为最差卖点（全史 10日胜率 43.1%/盈亏比 0.76/均值 +1.29%，方向相反）。改 D1 = close 从近 20 日最高价（high-based）回落 5%：`hh20=high.rolling(20).max(); thresh=hh20*0.95; sell=(close_prev>=thresh_prev)&(close<thresh)`，fillna(False)。回测 12 方案中 D1 唯一在 2016+ 窗口达标（胜率 50.6%/盈亏比 1.04/均值 -0.11%），近 3 年胜率最高（55.6%），评级"B 有效"。RSI 在卖点降级为参考标签附 reason（不作触发）；买点 RSI 不动（C1 验收通过）。high 由新增 `normalize.load_index_high()` 加载。重算后买点不变（全史 3311 / 近 1 年 114），卖点改 D1（13 主要指数：全史 2453 / 近 1 年 123，与回测一致；含 31 行业指数共全史 9162 / 近 1 年 450）。reason 卖点格式改 `20日高回落5%(高4259->阈4046,close4028), RSI=40, cross=53[中性]`。详见 `07-卖点对策回测.md`。
- **2026-07-06（方案 B 卖点盈亏标注）**：D1 卖点 reason 附 `vs前买{±X.XX%}[分类]` 标签，标注相对最近一次前置买点 close 的盈亏——`止盈`（close &gt; 前买 close，前端绿）/ `买点失败`（close &lt; 前买 close，前端灰）/ `无前买点`（窗口内无前置买点，前端橙）。`signals.py::compute()` 按 index_id 维护 `last_buy_close` 游标（按 date 升序遍历，遇 buy 更新、遇 sell 算 pct 分类）。**只加标注，触发逻辑不动**——买点 C1 + 卖点 D1 触发条件不变，重算后信号数不变（全史 12473 = buy 3311 + sell 9162）。前端 `signalColor(s)` 按 reason 子串分色（`indexChart` + `renderIndustry` markPoint），`ruleBar` 加操作文案（灰=止损观望、绿=止盈减仓、橙=单独看趋势）。分布：止盈 7227 / 买点失败 1739 / 无前买点 196。详见 §7.6。
- **2026-07-05（B1+S1 买卖点优化，当前）**：依据 `11-买卖点优化方案回测.md`（244 资产 = 13 指数 + 31 行业 + 200 抽样个股，全史/近3年/近1年 × 5/10/20 日 horizon）。**B1 买点增强**：C1 主买点（RSI 上穿 30，signal='buy'）不动，新增 BB 下轨回归辅买点（signal='buy_aux'）——`bu,mid,bl=_bollinger(close,20,2.0)`（mid=MA20, sd=std ddof=0, bu=mid+2σ, bl=mid-2σ）；`buy_aux=(close_prev<bl_prev)&(close>bl)`，fillna(False)。C1 与 BB 同日触发时去重（保留 C1 主买）；buy_aux 也算买点（更新 last_buy_close 游标 + 参与 vs前买 标注）。回测买点 15007→38547（翻 2.57×），近 3 年 10日 盈亏比 1.18（vs C1 1.13，不降质）。**S1 卖点降噪**：D1 触发逻辑保留，叠加 `close > MA60`（多头趋势才放卖）——`ma60=close.rolling(60,min_periods=60).mean(); sell=sell&(close>ma60)`。回测降噪 39%（全史卖点 59830→36289），近 3 年 10日 胜率 55.0%（vs D1 53.3%，+1.7pp）。新增 `_bollinger()` 辅助函数。reason：buy_aux 加 `布林下轨回归(下轨{bl:.0f},close{c:.0f}), RSI, cross`；sell 加 `MA60={m:.0f}[趋势过滤]` 段。前端 `signalColor` 加 buy_aux 粉紫 `#d63384` + `signalLabel` 辅买标签；`ruleBar` 文案更新（买主+辅 / 卖+MA60过滤）；CSS 加 `.buy_aux` 类。指数 + 全球指标(g.*) + 情绪分(s.*) 均应用 B1+S1；a_sentiment 仍 skip_buy（buy + buy_aux 都跳过）。重算后（含指数+行业+指标+情绪分）：buy 3861（C1 不变）/ buy_aux 5782（新增）/ sell 4700（vs 旧 11655，MA60 过滤砍 60%）；卖/买比 3.02→0.49（买卖平衡，回测 244 资产 3.99→0.94）。详见 §7.7。

### 7.5 与上一版（C1）差异对比

> 历史对比：C1 → D1（2026-07-06 卖点优化）。B1+S1 vs 方案 B 对比见 §7.7。

| 维度 | C1（2026-07-06，上一版） | D1（2026-07-06） |
|---|---|---|
| 买触发条件 | RSI(14) 上穿 30 | RSI(14) 上穿 30（**不变**，C1 验收通过） |
| 卖触发条件 | RSI(14) 下穿 70（超买结束） | close 从近 20 日 high 之 max 回落 5%（趋势转弱） |
| 卖触发数据 | close（算 RSI） | **high + close**（high 算 20 日最高价，close 判穿越；新增 `load_index_high`） |
| RSI 在卖点作用 | 主信号（触发条件） | 降级为参考标签（附 reason，不作触发） |
| cross 作用 | 软分级标签（写进 reason） | 软分级标签（**不变**，买/卖 reason 均附） |
| 事件化 | 是（shift(1).fillna(False)） | 是（不变；卖点结构上不可能连续两日） |
| 卖点回测（2016+ 10日） | 胜率 50.6% / 盈亏比 0.83 / 均值 +0.28%（C 弱有效） | **胜率 50.6% / 盈亏比 1.04 / 均值 -0.11%（B 有效，唯一达标）** |
| 卖点回测（全史 10日） | 胜率 43.1% / 盈亏比 0.76 / 均值 +1.29%（方向相反，最差） | 胜率 50.1% / 盈亏比 0.95 / 均值 +0.10% |
| 卖点定位 | 超买结束/有望回落 | **趋势转弱/止盈减仓提示**（非做空/反向信号） |
| 卖点信号数（13 指数） | 全史 1014 / 近 1 年 74 | 全史 2453 / 近 1 年 123 |
| reason 卖点格式 | `RSI下穿70(72->68),cross=82[狂热]` | `20日高回落5%(高4259->阈4046,close4028), RSI=40, cross=53[中性]` |
| 设计取向 | RSI 双向（低买高卖） | 买 RSI 超卖拐点 + 卖趋势跟踪止盈（反应型，不预测顶部） |

### 7.7 B1+S1 买卖点优化（2026-07-05，当前）

依据 `11-买卖点优化方案回测.md`（244 资产 = 13 指数 + 31 行业 + 200 抽样个股，全史/近3年/近1年 × 5/10/20 日 horizon 回测）。用户在 6 个组合方案中选 **B1+S1（买卖平衡）**：买点加 BB 下轨回归辅买点（B1_dual）+ 卖点加 MA60 多头过滤（S1_MA60bull）。

**B1 买点增强（辅买点 buy_aux）**：C1 主买点不动，新增 BB 下轨回归辅买点。语义与 C1 同为「超卖反弹」，但用价格穿越 BB 下轨而非 RSI 阈值——强势市 RSI 未到 30 但价格已破下轨时仍能捕捉，互补 C1 盲区。C1 与 BB 同日触发时去重（保留 C1 主买 signal='buy'）；buy_aux 也算买点（更新 last_buy_close 游标 + 参与 vs前买 标注）。

**S1 卖点降噪（MA60 多头过滤）**：D1 触发逻辑保留，叠加 `close > MA60`（60 日多头趋势才放卖）。砍下跌趋势中的假卖点（熊市 D1 频繁触发但多为下跌中继非止盈点）。MA60 前 60 日为 NaN 时不放卖（与 min_periods=60 一致）。

**与方案 B（上一版）差异对比**：

| 维度 | 方案 B（2026-07-06，上一版） | B1+S1（2026-07-05，当前） |
|---|---|---|
| 买触发条件 | C1：RSI(14) 上穿 30 | C1（**不变**）+ B1 辅买：BB 下轨回归（`buy_aux=(close_prev<bl_prev)&(close>bl)`） |
| 买信号类型 | signal='buy' 单一 | signal='buy'（C1 主）+ signal='buy_aux'（B1 辅）；同日去重保留 buy |
| 卖触发条件 | D1：20 日 high 回落 5% | D1（**不变**）∧ close > MA60（S1 多头过滤） |
| 卖触发数据 | high + close | high + close + **MA60**（close.rolling(60).mean()，新增） |
| 买点回测（近3年 10日） | C1：胜率 51.1% / 盈亏比 1.13 / 均值 0.6% | B1_dual：胜率 50.0% / 盈亏比 1.18 / 均值 0.5%（不降质，样本 2321→6473） |
| 卖点回测（近3年 10日） | D1：胜率 53.3% / 盈亏比 0.87 / 均值 0.0% | S1：胜率 55.0% / 盈亏比 0.84 / 均值 -0.1%（+1.7pp，样本 9936→5686） |
| 买信号数（回测 244 资产全史） | 15007 | 38547（**翻 2.57×**，C1 15007 + buy_aux 新增 23540） |
| 卖信号数（回测 244 资产全史） | 59830 | 36289（**砍 39%**） |
| 卖/买比（回测 244 资产） | 3.99（卖点远多于买点，噪声偏高） | **0.94（买卖平衡）** |
| 信号数（本项目重算，含指数+行业+指标+情绪分） | buy 3861 / sell 11655（卖/买 3.02） | buy 3861 / buy_aux 5782 / sell 4700（卖/买 0.49） |
| 前端 markPoint 配色 | 买=红、卖止盈=绿、卖买点失败=灰、卖无前买=橙 | + **辅买=粉紫 #d63384**（标签「辅买」） |
| reason 新增段 | vs前买 标注 | buy_aux：`布林下轨回归(下轨{bl},close{c})`；sell：`MA60={m}[趋势过滤]` |
| 设计取向 | C1 买 + D1 卖 + 盈亏标注（触发不动） | 买增强（补 C1 盲区）+ 卖降噪（砍熊市假卖）+ 盈亏标注（buy_aux 也算买点） |

**诚实声明与局限**：
- B1 辅买点 buy_aux 置信度低于 C1 主买（回测近 3 年 10日 胜率 50.0% vs C1 51.1%，略低但样本翻 2.57×），适合小仓位试探或观察确认，不可替代 C1 主买。
- S1 MA60 过滤会砍掉部分上涨市卖点（多头才放卖）——在单边上涨市可能漏掉转弱信号（趋势过滤的固有代价）；但下跌市假卖点被有效砍除（降噪 39%）。
- 卖点本质难预测（指数向上漂移，S1 近 3 年盈亏比仍 <1），降噪能减噪但不能让卖点变「好」。
- 信号独立统计：买/卖 forward return 各自评估，未模拟「买入→持有→卖出」真实配对收益（见 `10-买卖点配对回测.md`）。

---

## 8. 数据方向明细（数据字典）✅ 多数已验证

> 探针已验证的标 ✅；未验证的标 ⏳。akshare 1.18.64。

### A 股 · 市场宽度
| # | 指标 | 口径 | 数据源（akshare） |
|---|---|---|---|
| 1 | 涨跌家数（涨/跌/平） | 全 A 剔停牌，收盘 vs 昨收 | `stock_zh_a_spot_em` ✅ |
| 2 | 涨停数 / 跌停数 | 含一字/T字板 | `stock_zt_pool_em` ✅ / `stock_zt_pool_dtgc_em` |
| 3 | 连板高度 | 当日最高连板数（连板数列 max） | `stock_zt_pool_em` ✅ |
| 4 | 炸板率 | 炸板家数 / 触及涨停家数 | `stock_zt_pool_zbgc_em` |
| 5 | 封板率 | 1 − 炸板率 | 衍生 |
| 6 | 打板溢价 | 昨涨停股今日平均涨跌幅 | `stock_zt_pool_previous_em` |

### A 股 · 资金面
| # | 指标 | 口径 | 数据源（akshare） | 备注 |
|---|---|---|---|---|
| 7 | 北向资金净流入 | 沪+深股通当日净买入（亿元） | `stock_hsgt_hist_em` ✅ 2701 天 | ⚠️ 2024 起东财改口径且延迟披露 |
| 8 | 两融余额 | 融资+融券余额合计（亿元） | `stock_margin_sse` / `stock_margin_szse` | |
| 9 | 主力净流入 | 全市场大单净流入合计（亿元） | `stock_market_fund_flow` / `stock_main_fund_flow` | |

### A 股 · 情绪指数
| # | 指标 | 口径 | 数据源（akshare） |
|---|---|---|---|
| 10 | 综合情绪分 | 自算 0–100，见 §4 | 衍生 |
| 11 | 换手率 | 全市场加权换手率 | `stock_zh_a_spot_em` |
| 12 | 成交额 | 沪+深合计（亿元） | 指数成交 |
| 13 | 乐咕活跃度 | 现成情绪指数 | `stock_market_activity_legu` ✅ |
| 14 | 东财情绪 | 现成指数 | ⏳ 接口待验证 |
| 15 | QVIX（中国 VIX） | 中证 300/1000 ETF 期权波动率 | `index_option_300etf_qvix` / `index_option_1000index_qvix` ✅ 2755 天 |

### A 股 · 宽基指数
| # | 指标 | 口径 | 数据源（akshare） |
|---|---|---|---|
| 16 | 上证 / 深成 / 沪深300 / 中证500 / 中证1000 / 创业板 / 科创50 | 收盘价、涨跌幅、成交额 | `index_zh_a_hist` |

### A 股 · 板块与轮动 🆕试采
| # | 指标 | 口径 | 数据源（akshare） |
|---|---|---|---|
| 17 | 行业板块涨跌幅 | 全部行业板块当日涨跌幅（Top5/Bottom5） | `stock_board_industry_name_em` |
| 18 | 行业资金流净流入 | 行业板块大单净流入 | `stock_sector_fund_flow_rank` |
| 19 | 概念板块涨跌幅 | 概念板块当日涨跌幅 Top5 | `stock_board_concept_name_em` |

### A 股 · 龙虎榜 🆕试采
| # | 指标 | 口径 | 数据源（akshare） |
|---|---|---|---|
| 20 | 龙虎榜上榜家数 | 当日上榜个股数 | `stock_lhb_detail_em` |
| 21 | 机构净买入额 | 龙虎榜机构席位净买入合计（亿元） | `stock_lhb_jgmmtj_em` |

### A 股 · 解禁 🆕试采
| # | 指标 | 口径 | 数据源（akshare） |
|---|---|---|---|
| 22 | 解禁规模 | 当周/当月解禁市值（亿元） | `stock_restricted_release_summary_em` |
| 23 | 解禁家数 | 当周/当月解禁个股数 | `stock_restricted_release_queue_em` |

### A 股 · IPO 🆕试采
| # | 指标 | 口径 | 数据源（akshare） |
|---|---|---|---|
| 24 | IPO 数量 | 当月新股数量 | `stock_ipo_summary_cninfo` / `stock_ipo_ths` |
| 25 | IPO 募资额 | 当月募资合计（亿元） | 同上 |

### A 股 · 可转债 🆕试采
| # | 指标 | 口径 | 数据源（akshare） |
|---|---|---|---|
| 26 | 可转债中位转股溢价率 | 全市场可转债转股溢价率中位数 | `bond_zh_cov_value_analysis` |
| 27 | 可转债数量 | 存续可转债只数 | `bond_zh_cov` |

### 港股
| # | 指标 | 口径 | 数据源（akshare） |
|---|---|---|---|
| 28 | 恒生 / 恒生科技 / 恒生国企 | 收盘价、涨跌幅 | `stock_hk_index_daily_sina` ✅ |
| 29 | 港股通净买入 | 沪+深港通当日净买入（亿元） | `stock_hsgt_hist_em`（南向） |

### 全球
| # | 指标 | 口径 | 数据源（akshare） | 备注 |
|---|---|---|---|---|
| 30 | 美股三大指数（道/纳/标普） | 收盘价、涨跌幅 | `index_global_hist_sina` / `index_global_hist_em` ⏳ | `index_global_spot_em` 间歇 ProxyError，用 sina 兜底 |
| 31 | QVIX / VIX | 期权波动率 | QVIX `index_option_300etf_qvix` ✅；美股 VIX ⏳ 无直接函数 | |
| 32 | 美元指数 | 收盘 | ⏳ 无直接函数，走 index_global 或 macro | 待验证 |
| 33 | 离岸人民币 USD/CNH | 收盘 | `currency_boc_sina` ✅ 159 天 | |
| 34 | 黄金 | 沪金主力 | `futures_main_sina(symbol='AU0')` ✅ 4501 天 | |
| 35 | 原油 | INE 原油 / 布油 | `futures_main_sina` ⏳ symbol 待定；`futures_foreign_hist` 布油 symbol 待定 | |

---

## 8.5 宽度指标口径（TASK-D2，2026-07-06）✅

宽度指标（涨停/跌停/炸板/封板率/上涨下跌家数/成交额）的历史段（2016-2026，2550 个交易日）由 `app/collector/width_history.py` 从 `data/stock_daily.db` 的 `mootdx_daily_raw` 表（D1 采集，5203 只 SH/SZ 全历史日线）按日聚合算得，回填 `daily_metric`（source='mootdx'）。替代旧口径靠 `stock_zh_a_spot`（无历史，仅当日）+ `stock_zt_pool_em`（仅近 2 周）。

### 指标与公式

| metric_id | 名称 | 公径 |
|---|---|---|
| `a_width_zt_count` | 涨停数（收盘封板） | `close >= 涨停价 × 0.999`（收盘价达涨停价，封板口径） |
| `a_width_dt_count` | 跌停数（收盘封板） | `close <= 跌停价 × 1.001` |
| `a_width_zb_count` | 炸板数（收盘未封） | `high >= 涨停价 × 0.999 且 close < 涨停价 × 0.999`（曾触板未封住） |
| `a_width_seal_rate` | 封板率 | `zt / (zt + zb)`；分母为 0 → NaN |
| `a_width_up_count` | 上涨家数 | `pct_change > 0`（按涨跌幅符号，含除权日） |
| `a_width_down_count` | 下跌家数 | `pct_change < 0` |
| `a_amount` | 成交额（亿元） | `sum(amount) / 1e8`（全市场成交额求和，元→亿元） |

### 涨跌幅规则（按代码前缀）

| 板块 | 代码前缀 | 涨跌幅 | 说明 |
|---|---|---|---|
| 主板 | 000/001/002/003/600/601/603/605 | ±10% | |
| 创业板 | 300/301 | ±20% | |
| 科创板 | 688/689 | ±20% | |
| 北交所 | 430/830/920 | ±30% | ⚠️ mootdx 不覆盖（324 只由 D3 BaoStock 兜底） |
| B 股 | 200 | ±10% | ⚠️ mootdx 不覆盖 |
| ST | * | ±5% | ⚠️ mootdx 无 ST 标记，**不单独处理**（见下误差） |

涨停价 = 前收 × (1+规则)；跌停价 = 前收 × (1-规则)。前收 = `close / (1 + pct_change/100)`（由 mootdx 预算的 pct_change 反推，pct_change = `(close/prev_close-1)*100`，D1 入库时按不复权原始价自算）。

### 除权日处理（关键）

mootdx 不复权，跨除权日 close 跳水，pct_change 异常大。**判定**：正常交易 close ∈ [跌停价, 涨停价]；若 close 超出限价 0.1% 以外（`close > 涨停价×1.001` 或 `close < 跌停价×0.999`），必为除权日/数据异常（正常交易不可能突破涨跌停板）→ **跳过该日该股 zt/dt/zb 判定**。同时保留 `|pct_change| > 规则×1.5` 辅助阈值。

> 注：原任务草案建议用 `|pct_change| > 规则×1.5`（主板>15%、创业板>30%）作除权日阈值，但该阈值漏判 10-15%/20-30% 段的除权日（正常交易不可能突破 ±规则，故此段必为除权日），致 dt 大量误判。改用 close-beyond-limit 检测更精确（修复后 dt 误差 82%→33%，主要残差为 ST 误判，见下）。

上涨/下跌家数**仍按 pct_change 符号**（含除权日——除权日 close 跳水会被计为"下跌"，已知偏差，但占比小）。

### 浮点容差

涨停 `close >= 涨停价 × 0.999`（0.1% 容差，吸收未取整限价与收盘价四舍五入差异）；跌停 `close <= 跌停价 × 1.001`。每只首行无 pct_change（NULL）→ 跳过该行所有判定。

### 已知误差与限制

1. **ST 5% 不处理**：mootdx 无 ST 标记，ST 股按 10%/20% 规则算。ST 股在除权日 pct≈-10%（超其 5% 限价）会被误判为跌停（close-beyond-limit 用 10% 规则算跌停价，close 未超 10% 跌停价 → 不跳过 → 计 dt）。每日约 4 只 ST 误判，致 dt 系统性偏高 ~20-30%。zt 受影响小（ST 涨停 +5% 未达 10% 涨停价 → 不计 zt，仅漏计，量小）。
2. **北交所/B 股不覆盖**：mootdx 仅 SH/SZ 5203 只，不含北交所 324 只（D3 BaoStock 兜底，待补）。2021-11 北交所开市后，up/down/amount 约漏 6%；2016-2020 影响可忽略（北交所不存在）。a_amount 与 A1 全市场口径（含北交所）差 ~3%。
3. **zt 口径差异**：本表 zt=**收盘封板**（close 达涨停价）；`stock_zt_pool_em`=**盘中触板**（含炸板回封）。两者差 = 炸板回封数。近 16 日交叉校验均值误差 3.36%（中位 1.49%），2 日 >5%（封板 vs 触板口径差异，非计算错误）。
4. **dt 口径差异 + ST**：dt 误差均值 32.8%（含 1 日盘中采集 188%），主因 ST 误判 + 跌停封板 vs 东财跌停股池口径差异。剔除盘中日 + ST 影响后实际误差 ~15-20%。
5. **pct_change 跨除权日失真**：mootdx 不复权，pct_change 在除权日异常大（已用 close-beyond-limit 检测跳过 zt/dt/zb）。

### A1 近端值保护

`a_width_up_count`/`a_width_down_count`/`a_amount` 在 20260703/20260706 有 A1 修复的全市场口径正确值（source='akshare'，含北交所）。D2 回填**仅写 20160101-20260702**，不动 20260703+（A1 保留）。`a_width_zt_count`/`a_width_dt_count` 回填全段 20160101-20260706（覆盖近 2 周 stock_zt_pool_em 值，用收盘封板口径替代）。所有 upsert `ON CONFLICT DO UPDATE ... WHERE source != 'manual'`（防覆盖手动补录）。

### 交叉校验结果（review gate）

- **zt（收盘封板 vs stock_zt_pool_em 触板）**：16 日均值误差 **3.36%** < 5% ✅（剔除盘中采集的 20260706 后 15 日均值 2.21%、中位 1.49%）。
- akshare `stock_zt_pool_em` 近 3 日可取（东财 push2ex 未封锁）：20260706=64、20260703=108、20260702=93，与本表收盘封板 70/102/86 趋势一致（封板≤触板，差异为炸板回封数）。
- dt 误差较高（ST + 口径），不作为 gate（gate 仅要求 zt < 5%）。

### 换手率分布（a_turnover_*，2026-07-06 补）

mootdx turnover 全 NULL（D2 跳过），改用 BaoStock `baostock_daily_raw.turnover`（15.2M 非空）按日聚合算全市场换手率分布，回填 `daily_metric` 2016-2026（2550 日 × 5 指标，source='baostock'）。脚本 `app/collector/cleanup_d3d2.py turnover`。

| metric_id | 名称 | 公径 |
|---|---|---|
| `a_turnover_mean` | 全市场换手率均值 | 每日所有股票 turnover 的算术均值（%） |
| `a_turnover_median` | 中位数 | 每日 turnover 中位数（%） |
| `a_turnover_p90` | 90 分位 | 每日 turnover 90 分位（活跃度头部，%） |
| `a_turnover_p10` | 10 分位 | 每日 turnover 10 分位（活跃度底部，%） |
| `a_turnover_gt5_pct` | 换手率>5% 家数占比 | `(turnover>5 的家数) / 当日总家数`（0-1 小数，体现活跃度分化） |

数据范围（2016-2026，2550 日）：mean 1.04-8.50% / median 0.53-6.60% / p90 1.89-16.60% / p10 0.15-2.58% / gt5_pct 0.015-0.655。均值 3.04% / 中位 1.62%（右偏分布，头部活跃股拉高均值）。分布体现市场情绪周期：2016 初（熊市余波）mean 高、2018 底（冰点）mean 低、2020-2021（结构牛）p90 飙升。upsert `WHERE source != 'manual'`，NaN 过滤 `if v != v: continue`。

### 行业内宽度（TASK-F3，2026-07-06）

`industry_width_daily` 表（存 `data/sentiment.db`，PK(industry_code,date)）按申万一级 31 行业 × 2550 日（2016-2026，~79000 行）存**行业内**宽度。口径**完全复用本节上述 D2 §8.5 规则**（前缀涨跌幅 / close-beyond-limit 除权日 / 容差 0.999/1.001 / 前收反推），区别仅在分组维度：D2 按日聚合全市场，F3 按 (industry_code, date) 聚合。全行业 zt/dt/zb sum 与 D2 全市场 mootdx 源完全一致（zt 117369 / dt 40580 / zb 59583），口径一致性已校验。

成分股映射源：legulegu `stockdata/index-composition?industryCode=801xxx.SI`（akshare `index_component_sw` 仅返可投资指数成分，不含 31 一级行业指数；legulegu 返当前成分股）。存 `data/sw_components.json`（31 行业 / 5210 只）。**已知限制**：legulegu 返当前成分，非历史——2016-2021 段用当前成分算宽度存在偏差（已退市股漏算 / 行业变更股按当前归属），整体趋势可用，单日绝对值 ~5-10% 偏差。申万 2021 修订为最近大改。

---

## 9. 变更记录

- **2026-07-05**：初始化需求文档。已定：场景=盘后复盘、技术栈=Python/FastAPI/SQLite/ECharts、部署=Mac本地、历史回溯先 1 年、按天折线 + 周期按钮（1月/3月/6月/1年/全部）。两个综合分：§4 A 股综合情绪分（6 项加权，120 日滚动百分位）、§6 跨市场综合评分（去极值截尾均值）。§7 买点/卖点=情绪+技术双确认。宽基指数补充中证500/中证1000。指标全量纳入共 35 项（含板块轮动/龙虎榜/解禁/IPO/可转债 5 类试采项 + QVIX），原则：先采后筛、配置驱动可插拔。
- **2026-07-05（探针验证）**：akshare 1.18.64 经清华镜像安装成功并探针验证。已通：涨停板池、乐咕活跃度、北向资金(`stock_hsgt_hist_em` 2701 天)、QVIX(2755 天)、沪金(4501 天)、离岸人民币。修正函数名：北向→`stock_hsgt_hist_em`、VIX→QVIX、离岸人民币→`currency_boc_sina`、解禁→`stock_restricted_release_summary_em`。风险：东财 `index_global_spot_em` 间歇 ProxyError，用 sina 源兜底。待验证：东财情绪、美股三大指数 symbol、美元指数、布油 symbol。环境约束：pypi/github DNS 不通。
- **2026-07-06（测试轮修复）**：workbuddy 测试发现 17 bug + 额外 3 bug，全部修复。核心：①手动补录被每日采集覆盖（`upsert` 加 `WHERE source!='manual'`）；②`collect_series` 过滤 NaN（清 3679 null 行）；③新增 `compute/derived.py` 算派生封板率（1-炸板率）；④两融加日期范围(2000天)+scale 1e-8 回填 241 条；⑤`/api/manual` 校验 metric_id+date + `/api/manual/check` 端点 + 前端覆盖确认；⑥`/api/index` 未知 code→404、range 非法→400、favicon→204；⑦删 `a_sentiment_score`/`cross_market_score` 错配 metrics 条目；⑧口径标注（成交额沪深京/涨停东财板池/原油INE主力连续）。**诊断修正**：北向 null 非脚本 bug（akshare 返 2024-08 后全 NaN，东财停实时披露）；QVIX 6-26 后断（期权论坛源滞后）。详见 `01-问题清单.md` 修复跟踪表 + `NOTES.md` §4。
- **2026-07-06（买卖点优化 E1）**：`app/compute/signals.py` 改为事件化 + 跨市场共振。旧逻辑每满足日都标（RSI≤30 且 cross<80 标买；RSI≥70 且 cross>20 标卖）→ 一次超卖期多日多标、信号过密。新逻辑：买=RSI(14) 上穿 30（`rsi_prev≤30 且 rsi>30`）且 cross<30；卖=RSI(14) 下穿 70（`rsi_prev≥70 且 rsi<70`）且 cross>70；一次超卖/超买期只标穿越当日 1 个点。共振阈值从 <80/>20 收紧到 <30/>70。重算 signal_daily 2425→113（-95.3%，buy 898→55 / sell 1527→58）。reason 字符串规范为 `RSI上穿30(29->34),cross=8` 格式。规则详见 §7。
- **2026-07-06（D2 历史宽度回填）**：新建 `app/collector/width_history.py`，从 `mootdx_daily_raw`（D1 全 A 股 10.18M 行）按日聚合算 7 项宽度指标（zt/dt/zb/seal_rate/up/down/amount），回填 `daily_metric` 2550 个交易日（2016-2026），source='mootdx'。替代旧口径靠 `stock_zh_a_spot`（无历史）+ `stock_zt_pool_em`（仅近 2 周）。口径：收盘封板（close 达涨停价）+ close-beyond-limit 除权日检测 + 主板10%/创业板科创板20% 规则（ST 5%/北交所 30% 不覆盖，已知误差）。zt 与 stock_zt_pool_em 交叉校验均值误差 3.36% < 5% ✅。A1 近端值（20260703/20260706 up/down/amount）保留不覆盖。新增 metric `a_width_zb_count`/`a_width_seal_rate`。口径详见 §8.5。
- **2026-07-06（F3 行业内宽度）**：新建 `app/collector/industry_width.py`，用 D1 mootdx 日线 + 申万一级成分股映射（legulegu 源，5210 只 / 31 行业），按 (industry_code, date) 分组算行业内宽度（7 项指标同 D2 口径），回填 `industry_width_daily` 表（sentiment.db，31 行业 × 2550 日 = 79050 行）。口径与 D2 §8.5 一致（全行业 zt/dt/zb sum 与 D2 全市场完全相等）。成分股映射存 `data/sw_components.json`。已知限制：legulegu 返当前成分非历史，2016-2021 段有 ~5-10% 偏差。API `/api/industry` 每 index 加 `width` 字段；前端 `renderIndustryGrid` 每 cell 加宽度 mini chart（涨跌家数堆叠：红涨/绿跌）。runner.py 加 step 8 增量更新近 15 天。口径详见 §8.5「行业内宽度」。
- **2026-07-06（D3 阶段2 校验 + D2 换手率分布补遗）**：D3 阶段2 原计划 BaoStock vs akshare，因 akshare 东财 IP 封锁改 **BaoStock vs mootdx** 交叉校验。新建 `app/collector/cleanup_d3d2.py`，SQL JOIN on (code, date) 对比共有字段（open/high/low/close/volume/amount/pct_change）。重叠 9,847,524 行（2016-2026），除权日 25,404 行（0.26%，pct_change 差异 >0.5%）。剔除除权日后所有字段差异 <0.01% 量级（OHLC/amount 完全一致、volume 归一化后 7e-06 均值、pct_change 0.0002pp 均值），远 <1% 阈值 ✅。**关键发现**：mootdx volume 单位=手、BaoStock volume 单位=股（100x 差），对比需归一化；D2 用 amount 不受影响。同时用 BaoStock turnover 算全市场换手率分布 5 指标（mean/median/p90/p10/gt5_pct）回填 `daily_metric` 2550 日 × 5 = 12750 行（source='baostock'），补 D2 mootdx turnover 全 NULL 遗留。注册到 `config/indicators.yaml` a_sentiment 组；前端 `renderAStock` 加「换手率分布分位数」+「换手率>5%家数占比」两组折线。校验报告 `data/cleanup_d3d2_report.json`，口径详见 §8.5「换手率分布」+ NOTES.md §4.4。
- **2026-07-06（C1 买卖点软条件化）**：`app/compute/signals.py` 去掉 cross 硬门槛。E1 版买要 cross<30（冰点）、卖要 cross>70（狂热），近年市场宽度结构变化致 cross 多在 30-70 中性区，近 1 年买点 0、卖点仅 29，信号可用性丧失。C1 改为：买 = RSI(14) 上穿 30、卖 = RSI(14) 下穿 70（事件化不变，shift(1).fillna(False) 保留）；cross 降为分级标签（`<30`冰点 / `30-50`偏冷 / `50-70`中性 / `70-80`偏热 / `≥80`狂热）经 `_cross_tag()` 写进 reason，NaN 时省略。reason 格式扩展为 `RSI上穿30(29->34),cross=8[冰点]`。重算 signal_daily 113→6893（近 1 年 buy 0→114 / sell 29→267；全史 buy 55→3311 / sell 58→3582）。规则详见 §7。
- **2026-07-06（D1 卖点优化）**：`app/compute/signals.py` 卖点改 D1 = 20 日高回落 5%（high-based）。C1 卖点 RSI 下穿70 经回测（`07-卖点对策回测.md`，12 方案）验证为最差卖点（全史 10日胜率 43.1%/盈亏比 0.76/均值 +1.29%，方向相反）。D1：`hh20=high.rolling(20).max(); thresh=hh20*0.95; sell=(close_prev>=thresh_prev)&(close<thresh)`，fillna(False)。回测中 D1 唯一在 2016+ 窗口达标（胜率 50.6%/盈亏比 1.04，B 有效）。新增 `normalize.load_index_high()` 加载 high 列。RSI 在卖点降级为参考标签附 reason（不作触发）；买点 C1 不动（验收通过）。卖点定位改「趋势转弱/止盈减仓提示」（非做空/反向信号）。重算后买点不变（全史 3311 / 近 1 年 114），卖点改 D1（13 主要指数全史 2453 / 近 1 年 123，与回测一致；含 31 行业指数共全史 9162 / 近 1 年 450）。reason 卖点格式改 `20日高回落5%(高4259->阈4046,close4028), RSI=40, cross=53[中性]`。规则详见 §7。
- **2026-07-07（外部验证报告 BUG-F/G/H 修复）**：依据 `交易信号网站验证报告.md`（独立 AI 测试代理复现）修 3 个 P3 体验/合规增强 bug。**BUG-F（卖点语义文案）**：ruleBar（`web/app.js` + `static-site/app.js`）"胜率50.6%"易被散户误读为高胜率卖点，改"走弱概率≈50%（接近随机，非高胜率卖点）"+ 强调"止盈减仓提示，不可作为独立卖出指令"；§7.2/§7 注同步强调"D1 非做空/反向交易指令；胜率≈50% 接近随机，不可作为独立卖出指令"，保留"最不坏非好方案"诚实声明。**BUG-G（情绪分公式透明度）**：新增 §6.5 情绪分公式公开披露章节——a_sentiment 披露 6 分项固定权重公式（ratio 25%/zt 20%/zhaban 15%/lianban 15%/amount 10%/north 15%）+ 120 日滚动百分位归一化 + 缺项可用权重重归一化（至少 3 分项出分）；cross_market 披露 trim-mean 池（38 个 enabled simple metric，含 cn10y/us10y/wti_oil/comex_silver/a_div_yield 等）+ 精确算法（dropna→<3 返 NA→升序去 iloc[1:-1] 即去最高 1+最低 1→其余算术均值）。实现校对自 `app/compute/sentiment.py`+`cross.py`+`normalize.py`。**BUG-H（买→卖配对回测）**：新建 `a-stock-data/backtest_pair.py`（独立脚本，自复刻 RSI/D1，不 import app）—— C1 买入→持有至下一个 D1 卖出（或 60 日时间止损）→算完整回合收益。13 主要指数全史 523 回合，持有期均值 +0.67%/胜率 44.6%/年化 +2.52%/平均持有 27.2 日/最大回撤 55.2%。关键发现：D1 卖点平仓回合（86.4%）均值 -0.19%（趋势转弱回吐浮盈），时间止损回合（12.6%）均值 +6.49%（强势趋势未触发 D1）；策略收益主要由强势回合贡献，D1 卖点作用是"转弱时止损避免更大亏损"而非"抓住赢家"。报告 `10-买卖点配对回测.md`。验收：node --check + py_compile 通过。
- **2026-07-05（B1+S1 买卖点优化）**：依据 `11-买卖点优化方案回测.md`（244 资产回测，6 组合方案）实施用户选定的 B1+S1（买卖平衡）。**B1 买点增强**：`app/compute/signals.py` 新增 BB 下轨回归辅买点（signal='buy_aux'）——新增 `_bollinger()` 辅助函数（mid=MA20, sd=std ddof=0, bu=mid+2σ, bl=mid-2σ）；`buy_aux=(close_prev<bl_prev)&(close>bl)`。C1 主买点（signal='buy'）不动；C1 与 BB 同日触发时去重（保留 C1）；buy_aux 也算买点（更新 last_buy_close 游标 + 参与 vs前买 标注）。**S1 卖点降噪**：D1 触发逻辑保留，叠加 `close > MA60`（`ma60=close.rolling(60,min_periods=60).mean(); sell=sell&(close>ma60)`）——多头趋势才放卖，砍下跌市假卖点。指数 + 全球指标(g.*) + 情绪分(s.*) 均应用；a_sentiment 仍 skip_buy（buy+buy_aux 都跳过）。reason：buy_aux 加 `布林下轨回归(下轨{bl:.0f},close{c:.0f})`；sell 加 `MA60={m:.0f}[趋势过滤]`。前端 `web/app.js`+`static-site/app.js`：`signalColor` 加 buy_aux 粉紫 `#d63384` + 新增 `signalLabel` 辅助函数（buy→买/buy_aux→辅买/sell→卖）；`indexChart`/`valueChartWithSignals`/`renderIndustryGrid`/`renderOverview` 改用 `signalLabel`；`ruleBar` 文案更新（买主+辅 / 卖+MA60过滤 / 变更历史 / reason示例）；CSS（web+static-site `style.css`）加 `.buy_aux` 类（粉紫 #d63384）。REQUIREMENTS §7 全面更新（§7.1 参数加 BB+MA60 / §7.2 语义加 buy_aux+MA60 / §7.3 reason 格式 / §7.4 变更历史 / §7.7 新增 B1+S1 对比表）。重算 signal_daily：buy 3861（C1 不变）/ buy_aux 5782（新增）/ sell 4700（vs 旧 11655，MA60 砍 60%）；卖/买比 3.02→0.49（回测 244 资产 3.99→0.94）。验收：py_compile + node --check + curl API 200（/api/index/sh 含 buy_aux、/api/global extras_signals、/api/sentiment a_sentiment 仅 sell 验证 skip_buy）+ sqlite3 统计。详见 §7.7。

---

## 10. 实现状态（2026-07-06，含测试轮修复）✅ P1–P7 完成

**已跑通**：
- 采集：**27 启用指标**（akshare + sina 源 + direct 直爬 + tencent），序列指标自动回填完整历史（上证 8674 天、北向 2264 天止 20240816、QVIX 1567 天止 20260626、沪金 4501 天、两融 1324 天等）
- 计算：**§6 跨市场分 2735 天**、**§4 A股情绪分 7 天**（近期）、**买卖点 12473 个**（买 RSI 上穿30 C1 + 卖 20日高回落5% D1 high-based；买 3311 / 卖 9162）、**派生封板率 16 天**
- API：FastAPI 端点（overview/a_stock/hk/global/sentiment/index）+ 手动补录（含 metric_id/date 校验 + `/api/manual/check` 覆盖确认）+ range/index 校验（400/404）+ favicon
- 前端：5 tab + ECharts 折线 + 周期按钮（1月/3月/6月/1年/全部）+ 买卖点 markPoint + 手动补录弹窗（日期默认当天、覆盖确认）
- 计算层：§4 加权 / §6 去极值 / RSI 买卖点 / **派生公式（derived.py）**
- 数据完整性：NaN 不入库；手动补录值不被采集覆盖（`source!='manual'` 保护）
- 定时：`scheduler.py` + `launchd` plist（待用户 `launchctl load`）

**已知限制**：
- **§4 A股情绪分历史仅近 2 周**：涨停板池接口 `stock_zt_pool_em` 只保留近 2 周数据，无法回填更早。§4 从 20260626 起，随每日采集积累向前扩展，120 日窗口逐步稳定（min_periods=10）。
- **北向资金冻结 20240816**：akshare `stock_hsgt_hist_em` 返 2024-08 后行但全 NaN（东财停实时披露），已过滤 NaN。雪球有盘后数据但需另写爬虫（未做）。
- **QVIX 滞后停 20260626**：源（期权论坛）未更新 7 月数据，重采仍无，源问题不可修。
- **2 metric + 3 指数 + 3 板块禁用**：乐咕/东财情绪（无源）、美股三大指数（A股only）、板块3项（东财 push2 clist 硬反爬）。
- **龙虎榜当日盘后延迟**：`stock_lhb_detail_em` 当日可能返 None，次日可补。
- **环境**：macOS Clash 代理（127.0.0.1:7890）拦截东财流量 → 已用 `trust_env=False` 全局绕过 + sina 源替代。

**运行命令**：
```bash
# 看板（浏览器打开 http://localhost:8000，局域网 http://192.168.31.207:8000）
.venv/bin/python -m uvicorn app.main:app --port 8000 --host 0.0.0.0 --app-dir .

# 手动跑当日采集+计算
.venv/bin/python -m app.scheduler

# 安装定时任务（每交易日 15:33）
cp launchd/com.trade.sentiment.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.trade.sentiment.plist
```
