# 数据集授权声明 · CC BY 4.0

> 本文件声明 tdsignal 项目**数据集**的授权条款。代码授权另见 [LICENSE](../LICENSE)（MIT）。

---

## 数据集范围

本授权覆盖 tdsignal 仓库 [`static-site/data/`](../static-site/data/) 目录下所有静态导出的 JSON / XML 数据产物，包括但不限于：

- `overview.json` / `summary.json` / `summary_history.json` - 今日快照与收盘速递
- `sentiment-*.json` - 情绪指数历史（9 个情绪分序列）
- `a-stock-*.json` - A 股 32 指标 + 12 宽基指数
- `hk-*.json` - 港股 3 宽基 + 8 板块指数 + 港股通
- `global-*.json` + `global-extras-*.json` - 全球指数 + 商品/汇率/债券
- `industry-*.json` + `industry-3y-indices/` + `industry-3y-concepts/` - 行业与概念板块
- `etf_national_team-*.json` + `etf_national_team_holders.json` + `etf_national_team_quarterly.json` - 国家队 ETF 资金动向
- `futures.json` - 期货机构持仓
- `signal_stats.json` + `index/{id}-all.json` - 113 品种买卖点回测统计
- `position.json` / `ma_alignment.json` / `ad_line.json` / `new_high_low.json` / `volume_ratio.json` / `rotation.json` - 大盘宽度
- `alert.json` + `alert_analyze_{id}.json` - 风险预警
- `intraday_snapshot.json` - 盘中实时快照
- `etf_score_list.json` - ETF 评分榜单
- `lab/*.json` / `trade_sim/*.json` - 策略实验室与模拟交易回测产物
- `schedule_stats.json` / `signal_freq.json` / `feed.xml` - 调度统计与 RSS

字段说明详见 [data-dictionary.md](data-dictionary.md)，数据来源详见 [data-sources.md](data-sources.md)。

## 授权条款

本数据集以 **[Creative Commons Attribution 4.0 International (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/)** 授权。

### 您可以

- **共享** — 在任何媒介以任何形式复制、发行本作品
- **改编** — 修改、转换或以本作品为基础创作
- **用于任何目的** — 包括商业性使用（含金融研究、量化策略、商业产品）

### 唯一前提

**署名** — 您必须给出适当的署名，提供指向本授权的链接，同时标明是否对原始作品做了修改。署名方式建议：

```
数据来源：tdsignal 市场温度看板（https://ss.fx8.store/）
仓库：https://github.com/xp13465/trade-data-signal
授权：CC BY 4.0（https://creativecommons.org/licenses/by/4.0/）
```

### 完整法律文本

完整授权条款见 Creative Commons 官网：<https://creativecommons.org/licenses/by/4.0/legalcode>

---

## 数据源声明

本数据集所含数据均采集自公开免费数据源（akshare / mootdx / BaoStock / HKEX / CCASS / 东方财富 / 同花顺 / 申万 / 中证指数公司 / 新浪 / 腾讯 / CFFEX / cninfo / legulegu），tdsignal 对原始数据进行了清洗、聚合、计算（情绪分、买卖点信号、回测统计等）。

各原始数据源的版权归各自所有者所有，本授权仅覆盖 tdsignal 项目产出的衍生数据集（清洗/聚合/计算后的 JSON 产物），不覆盖原始数据本身。

## 准确性声明

- 数据准确性受数据源限制，请以官方披露为准
- 申万行业指数 2016-2021 段用当前成分股算宽度存在 ~5-10% 偏差
- 北向资金 2024-08 港交所新规后改季度披露，日频净买额停更
- 买卖点信号为历史回测参考，胜率接近随机，**不构成投资建议**
- ETF 国家队信号为代理推断，非真实国家队席位数据

详见 [data-sources.md 数据准确性声明](data-sources.md#数据准确性声明)。

---

## 相关授权

- **代码**（`app/` / `scripts/` / `static-site/` 的 `.py` / `.js` / `.css` / `.html` 等）：[MIT License](../LICENSE)
- **数据集**（`static-site/data/` 的 `.json` / `.xml` 产物）：本文件声明，CC BY 4.0

---

## 引用建议

如在学术研究或公开作品中使用本数据集，建议引用：

```bibtex
@misc{tdsignal,
  author = {tdsignal},
  title  = {市场温度看板数据集},
  year   = {2026},
  url    = {https://github.com/xp13465/trade-data-signal},
  note   = {CC BY 4.0}
}
```
