# 量化知识/方法论商品化调研(2026-08-17)

> 来源:researcher 调研(aebc4216be2c7af83),用户 2026-08-17 想法「数字资产还包括知识和方法论,可整理成册;不只一种产品」。本文为落档版。

## 一句话结论
**值得做,零新通路、原料现成且稀缺、有实锤先例**。平台知识商店文件/链接交付通道已验证就绪,191 篇内部文档(其中 kelly 系列 60 篇是"真实 2011-2026 数据结论+脚本可复现")是市面教程少有的稀缺原料。建议 4 个产品形态,第一步用最低成本的「文献地图」验证全链路,再上「回测方法论+避坑小册」核心价值品。

## 一、平台现有商品盘点
- **当前无知识类先例**:全部是 API/数据包/速递类(能力 2 类、知识商店 1 类=金融衍生数据包 112UT/划线150、链接知识商品 1 类=在线速递 168UT/划线268、数据广场 6 类)。
- **知识商品通道已就绪**:①文件交付(电子书/PDF/文档包):`upload/file`→`quick-upload`→`publish`,uumit-agent skill `API_REFERENCE.md §16.1` 示例 `file_type: application/pdf`,购买走 `GET /api/v1/deliverables/{access_token}/download`(数据包已验证 published)②链接交付(在线手册+访问密码):`register-link` ③定价必须 `GET /api/v1/pricing/suggestion` 拿建议价(按 category/pricing_model,不能静默自定义)。

## 二、市面形态与定价(带来源)
| 形态 | 先例 | 定价特征 |
|---|---|---|
| 文献/资源地图(黄页导航) | **awesome-quant** 实抓:GitHub 28,888 星/3,862 fork,"curated list for quants",18 大章节 | 免费公开,星标流量获客 |
| 平台免费课程获客 | BigQuant 实抓:量化学院免费课程+1000+策略源码,靠数据/工具收费 | 知识免费作入口 |
| 线上课程 | Udemy/Coursera/网易云课堂生态(cn.bing 证实) | 国内 ¥199-699;Udemy 量化 $19.99-99.99;知识星球 ¥365-1999/年(领域常识参考,反爬未实抓逐页) |
| 避坑指南/付费专栏 | 知乎/公众号/知识星球形态普遍 | 零散免费,成册付费 |

## 三、平台资产原料清单(docs/ 共 191 md)
| 类别 | 原料 | 可成形态 |
|---|---|---|
| 算法知识(凯利/降亏/回测口径) | `docs/kelly/{analysis,position,backtest-ai,combo,toggle}/` 60 篇(每篇=结论+数据+脚本+复现段) | **《量化回测方法论手册》**:口径(每日池 vs 固定)/费率差异/K 档/样本外验证/20 倍本金可操作性——最有稀缺性 |
| 数据挖掘方法论 | `docs/kelly/mining/`(8 种方法 Python+文献)+ 顶层 overfit-* | 《降亏/过拟合数据挖掘实战》 |
| 避坑指南(反直觉/已踩坑) | `docs/archive/CLAUDE-errors-2026-08.md`(41 过错+30 经验,每条=根因+场景+防重犯) | 《量化项目避坑手册》——注意工程坑需转译给交易学习者 |
| 文献目录地图 | `README.md §参考与致敬`(30+ 文献含 DOI,标"用在哪")+ mining-literature + data-sources | 《量化文献与方法论地图》——比 awesome-quant 多"每篇实际用在哪"的 1:1 标注 |
| AI 预测方法论 | `docs/ai-predict-*.md` + daily-brief-*.md | 《AI 每日预测方法论》 |
| 指标解读(现成雏形) | `docs/理财专员使用指南.md` + `docs/explain-1to1-inventory.md`(§23.9 三档互证) | 《指标解读手册》——读者视角成品雏形 |

## 四、建议
### 4 个产品形态(按价值排序)
1. **《量化回测方法论+避坑小册》**(最高价值,第一优先):kelly 60 篇提炼口径对比/费率/K 档/样本外/20 倍可操作性/过拟合 4 维 + 反直觉坑清单
2. **《量化文献与方法论地图》**(最低成本起步):README 致敬表+literature 整理成导航册,带"用在哪"标注
3. **《指标解读手册》**:三档互证指标字典
4. **《AI 每日预测方法论》**:双命中口径/多角色辩论/降级契约

### 定价参考(对照平台现有体系,落地仍须跑 /pricing/suggestion 复核)
- 文献地图:30-80 UT(对标免费获客逻辑,可 0 UT 引流)
- 避坑指南:60-120 UT(对标卖出警示 API 60UT 档)
- 回测方法论小册:112-200 UT(对标数据包 112/在线速递 168 区间,方法论信息密度更高)
- 指标解读:80-150 UT
- 订阅连载(每周一篇方法论):对标 AI 速递订阅 1500 UT/月的 1/3-1/2

### 第一步(先 B 后 A)
- **B. 文献地图**(1 天量级):README 致敬表+literature+data-sources → PDF/在线页 → quick-upload 上架,验证知识商品全链路 + 立骨架
- **A. 回测方法论小册**(3-5 天):B 验证后,从 kelly/analysis 25 篇挑 5-8 篇口径类(walk-forward/费率/K2C5/可操作性)提炼第一本小册

## 五、诚实标注(局限)
- ① 回测结论(降亏比值>2/特定宇宙)基于特定口径,成册必须带**适用边界/口径声明**,不当普适结论卖
- ② 避坑归档大量是工程/开发坑,对交易学习者需**转译**,不直接丢原文
- ③ 内部文档是给 agent/自己看的,对外卖必须**重写受众视角**(白话+1:1 举例,§23.9 教学法现成可套),除非定位成"真实研究档案"卖档案价值

## 复现(调研方法/数据源)
- 平台侧:读 `docs/uumit-listing-materials.md` 全文、`docs/uumit-24h-limit-research.md`、uumit-agent skill `API_REFERENCE.md §3.6/§16.1/§4`、`CHANGELOG.md:20`
- 市面侧:GitHub API 实抓 awesome-quant(stars=28888)、bigquant.com 实抓、cn.bing(WebSearch 空返回时切 DoH+curl 通路);课程页定价反爬未实抓,标注为领域常识
- 资产侧:统计 docs/ 191 md,逐目录读 README 索引
- URL:github.com/wilsonfreitas/awesome-quant、bigquant.com、cn.bing.com、ai-tradingagents.com、udemy.com、coursera.org
