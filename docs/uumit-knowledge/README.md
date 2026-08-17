# 知识商品 · 产物目录索引

> 本目录存放平台**知识商品**的成册产物(整理成读者视角的可发布文档)。每个册子 = 一份 md + 可选的配套脚本/数据,塞入即归类、随建随更新本索引。
> 上游方案与定价调研见 [`docs/uumit-knowledge-products-research.md`](../uumit-knowledge-products-research.md)。
> 落档规范:CLAUDE.md §23.5(新产物当场落档·塞入即归类)。

## 册子清单

| 册子 | 文件 | 状态 | 说明 |
|---|---|---|---|
| 第一步 B · 量化文献与方法论地图 | [`literature-map.md`](literature-map.md) | ✅ 已上架,1 UT 引流价 published(资产 `649b30d2`,capability `d7ede493`) | 数据源/回测/因子挖掘/AI预测/避坑五章,每条带"本项目用在哪"1:1标注 + 主站落地举例(fx8.store 引流),读者视角白话;0 UT 被平台拒,用户拍板 1 UT 最低正数价上架(见册子「定价定位」段上架实测) |
| 第一步 B · 文献地图交付版 | [`deliverables/literature-map.md`](deliverables/literature-map.md) | ✅ 已作为上架交付物发布 | 对外发布版,去掉内部 `docs/` 路径,保留主站域名引流;已上架知识商店 |
| 第一步 A · 量化回测方法论+避坑小册 | [`retro-manual/00-index.md`](retro-manual/00-index.md) | ✅ 已上架 188 UT(2026-08-18 发布,资产 `265467f2`,审核 auto_approve+human approved 后 publish) | 10 章读者视角手册(口径 / 每日池vs每笔 / 费率 / K档 / 20倍可操作 / walk-forward / K2C5挖掘 / 模式分裂 / 两把尺子 / 避坑+过拟合监控),每章真实 2011-2026 回测数据 + 1:1 落地例子 + 复现段;大纲 [`retro-manual-plan.md`](retro-manual-plan.md);定价 188 UT(划线 228 UT) |
| C · 指标解读手册 | [`indicator-guide/00-index.md`](indicator-guide/00-index.md) | 成册完成(2026-08-17);**UUMit 资产已建** `6c688811`(资产名「指标解读手册」,封面 `31d4959ef1234ec1.png`),待定价上架(后续独立任务);大纲 [`indicator-guide-plan.md`](indicator-guide-plan.md) | 10 章三档互证指标字典(指标地图/监控卡/回测/凯利/情绪/宽度资金/信号/ETF评分/口径底线/每日实战),每类指标白话+场景+1:1 真实数字举例,均从站内数据产物核实+复现段;原料 `docs/理财专员使用指南.md` + `docs/explain-1to1-inventory.md`;定价参考 80-150 UT |
| D · AI 每日预测方法论 | [`ai-predict-methodology-plan.md`](ai-predict-methodology-plan.md) | 大纲已定(2026-08-17);**UUMit 资产已建** `cbc34674`(资产名「AI 每日预测方法论」,封面 `48a6ba7372014d58.png`),内容审核 pending 中,成册后上架 | 11 章:双命中口径/注入面/多角色辩论/新闻面/降级契约/自成长反射/透明展示/质量衡量/可复现流程/合规边界;原料 10 份 ai-predict-*.md + daily-brief-*.md + 3 memory |

## 分类约定

- 内容只放整理后的**读者视角**文档(不是内部 md 搬运);内部推导/数据/复现链接指向原文 `docs/` 对应目录,不重复正文。
- 每个册子定位、定价建议、诚实标注(适用边界/口径声明)写进册子自身末尾,不依赖本索引。

## 索引维护

新增册子/文件后在本表加一行(名称+路径+状态+一句话说明)。删除/改版同步更新。
