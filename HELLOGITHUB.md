# HelloGitHub 提交文案

> HelloGitHub 是一个分享有趣、入门级开源项目的中文社区，通过 GitHub Issue 提交推荐。
> 提交地址：https://github.com/521xueweihan/HelloGitHub/issues

---

## 标题

tdsignal - A股/港股/全球盘后复盘情绪数据看板

## 推荐理由

一个把"散落各处的情绪数据"汇总到一处的盘后复盘工具。每日收盘后自动采集 A股/港股/全球的情绪、宽度、资金、结构类指标，攒成 10 年历史序列，计算综合情绪分，在指数图上标注买卖点，辅助判断市场情绪拐点（冰点/过热）与买卖时机。

**亮点**：
- 全量免费数据源（akshare + mootdx + BaoStock），无 API key，本地即可跑
- 两个自研综合分：A股综合情绪分（6 指标加权）+ 跨市场综合评分（去极值截尾均值），公式全公开可审计
- 买卖点信号事件化 + 回测验证：RSI 主买 + 布林辅买 + MA60/MACD 卖点确认，每个信号附胜率/盈亏比/凯利仓位
- 82 品种买卖点模拟回测，申万 31 行业涨跌幅热力图，期货机构净多空持仓追踪
- 纯前端 ECharts 无构建步骤，指标配置驱动增删改不动核心代码
- 双部署：动态 FastAPI + 静态 Cloudflare Pages

技术栈：Python + FastAPI + SQLite + ECharts + akshare/mootdx/BaoStock。

## 项目地址

https://github.com/xp13465/trade-data-signal

## 在线 Demo

http://tdsignal-ujpzw01zm.maozi.io/

## 类别

数据分析 / 金融 / 可视化

## 编程语言

Python (后端) + JavaScript (前端)

## License

MIT

---

## 提交说明（给用户）

1. 打开 https://github.com/521xueweihan/HelloGitHub/issues/new
2. 标题用上面的"标题"
3. 正文填"推荐理由 + 项目地址 + Demo + 类别 + 语言 + License"
4. HelloGitHub 每月一期，审核周期约 1 个月，入选后会收录到月刊

**提升入选率的建议**：
- 配 1-2 张看板截图（GIF 更佳）放到 README 顶部
- 给仓库加 topics 标签：`finance` `data-visualization` `stock` `echarts` `akshare` `python`
- star 数 < 50 入选概率较低，可先在 V2EX/掘金/即刻 做一轮传播攒 star
- HelloGitHub 偏好"有趣、易上手"的项目，README 的 demo 链接和截图是关键
