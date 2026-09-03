# 北交所宽度 C 方案 —— 实施说明（独立 a_bj_* 指标组 + 前端卡）

- 日期:2026-09-02
- 实施:implementer(role-implementer skill),方案 = 调研报告拍板「方案 C:单独出北交所宽度,不动现有宽度」
- 前置调研:[`beijiao-exchange-width-universe-20260902.md`](beijiao-exchange-width-universe-20260902.md)(researcher 产出,含 30% 档必要性实证 2.2 节、影响面全清单第 3 节)
- 派单基准:纯展示性宽度指标,北交所不在信号回测买入宇宙,不动 config/universe_rules.yaml,不影响回测入样(§23.6)

---

## 1. 落地内容(一次 commit:7fef306bd)

| 文件 | 改动 |
|---|---|
| `app/collector/beijiao_width.py` | **新增**。从 `fapi_daily_raw`(920xxx.BJ,FAPI 源)算北交所 5 指标,写 `daily_metric` 独立 metric_id(source='fapi') |
| `app/collector/width_history.py` | `limit_rule()` 加 `920→0.30` 分支(单一事实源)。mootdx 不含 920,此分支零影响现有主宽度 |
| `app/collector/runner.py` | 新增 `beijiao_width` step(独立 pipeline 用,不进 17:50 update_all 链) |
| `app/queries.py` | `BJ_WIDTH_METRICS` 字典 + 注入 overview/a-stock KPI 数据流(overview today.metrics + *_6m sparkline + a-stock-* 系列) |
| `scripts/pipeline.sh` | 新增 `beijiao` pipeline(只写库不 export,launchd 每日调) |
| `static-site/app.js` | 北交所宽度 5 卡渲染/排序/格式化 + 点卡双线图(`_loadKpiHistory` a_bj_* 分支)+ hover 口径弹窗(`_BJ_WIDTH_CALIBER_TIP`)+ 6m tooltip。数据读后端注入字段,前端不自算宇宙(§23.6) |
| `static-site/purpose-notes.js` | `market.a-stock` 公示补「北交所宽度(2026-09-02 独立新增)」口径段(§21) |
| `scripts/com.trade.beijiao-width.plist` | 新增。launchd 18:15(避开盘后禁区 §14),FAPI 18:10 采集后 5 分钟算 |
| `README.md` | 功能亮点补「北交所宽度卡(方案C)」段,指向调研+实施两文档(§23.1) |

## 2. 指标口径(与 width_history 同构,仅涨跌幅档位不同)

- 指标(5 个):`a_bj_up_count`(上涨家数)/ `a_bj_down_count`(下跌家数)/ `a_bj_zt_count`(涨停数)/ `a_bj_dt_count`(跌停数)/ `a_bj_amount`(成交额,亿元)
- 数据源:`fapi_daily_raw` `WHERE code LIKE '920%'`(约 339 只),数据起点 20260819
- 涨跌幅规则 = 30%(复用 `width_history.limit_rule()` 920 分支,单一事实源)
- 涨停:`close >= prev_close×(1+0.30)×0.999`;跌停:`close <= prev_close×(1-0.30)×1.001`
- 除权日处理:close 超限价 1.001 或 pct_change 超规则 1.5 倍 → 跳过涨停/跌停判定(与主宽度一致)
- 最小 code 数阈值:MIN_BJ_CODES=300(正常 339,低于此视为采集不全跳过)
- 历史:从 FAPI 已有数据起画(10 日实测+后续累积),不假装完整历史(诚实标注)

## 3. 数据管道

- FAPI 采集:`com.trade.fapi-daily` launchd **已挂载,18:10 每日执行**(2026-09-02 核实)。FAPI 是北交所唯一数据源(T+0),mootdx/baostock 不覆盖北交所
- 北交所宽度计算:`com.trade.beijiao-width` launchd **18:15**(本 commit 附带 plist,需 merge 后由主控/运维挂载;FAPI 18:10 采集后 5 分钟算,避开 17:50 update_all 链——17:50 时 FAPI 当日数据尚未入库,跑了只重复算昨日)
- 手动重跑:`bash scripts/pipeline.sh beijiao` 或 `python -m app.collector.beijiao_width --recent`
- 只写 daily_metric,export 随 update_all 统一 deploy 上线(§22 三步:后端注入字段→前端展示位→R2/static-site 同步)

## 4. 前端展示位

- 首页「上涨/下跌家数」KPI 卡旁新增 5 张北交所宽度卡(排序 4.1-4.5,紧跟主宽度卡)
- 点卡=逐日双线走势(上涨/下跌双线、涨停/跌停双线、成交额单线),复用 `_lwSetup` 零新 echarts
- hover 弹窗标注口径「北交所·30% 档」与主宽度「沪深·10/20% 档」区分(§22 一致性)

## 5. 回归验证(2026-09-02,生产库)

- 主宽度 4 项逐位对账:本地 overview(改动版生成)vs 生产库直接查询,`a_width_up/down/zt/dt_count` 20260903 全部一致(1845/3570/44/16)
- a-stock-6m 历史序列 vs 线上 R2:`a_width_up_count/down_count/zt_count/dt_count/zhaban_rate/a_amount/turnover_mean` 共同 124 天 **DIFF=0**,local 多 5 个 metrics = 恰为新增 a_bj_* 组
- 前端 Playwright 无痕浏览器实操(本地 static-site + 改动版 min + 生产库 JSON):
  - 桌面端:5 张北交所卡渲染,值=40/295/0/0/216.0 亿(20260903);hover 弹窗口径标注含「30% 档」;点卡弹双线 SVG 走势 + hint「数据自 2026-08-19 起」
  - 移动端(390×844):5 卡可见可点,二次 tap 弹「北交所上涨家数走势」modal
  - 主宽度/恐贪/AD 线卡渲染不受影响(改动前数值一致)
- 后端:JS 语法 node --check 过 + Python ast.parse 过 + pre-commit lint 全过(bash -n/py_compile/多字节扫描)

## 6. 诚实标注 / 已知事项

- 数据起点 20260819 = FAPI 采集起点,前端/公示已标注「不假装完整历史」;北交所 2021-11 上市前的历史无法从 FAPI 920 段取得(920 段 2024 才启用,调研报告 §4)
- `com.trade.beijiao-width` plist 已提交但**未挂载**(代码 merge 后由主控/运维执行 `cp` + `launchctl bootstrap`);挂载前北交所宽度需手动 `pipeline.sh beijiao` 补算
- FAPI 10 日实测稳定,但为带 key 官方 API 试点源,若 FAPI 停服,北交所宽度 n_codes<300 自动跳过(诚实降级,不写假数据)

## 7. 复现段

- 重跑命令(北交所宽度计算):
  ```
  # 全量回填(FAPI 数据起点起)
  cd /Users/linhuichen/code/trade && .venv/bin/python -m app.collector.beijiao_width
  # 增量重算近 30 天(launchd 每日调)
  .venv/bin/python -m app.collector.beijiao_width --recent
  # 只算不写
  .venv/bin/python -m app.collector.beijiao_width --dry-run
  ```
- 输入依赖:
  - `data/stock_daily.db:fapi_daily_raw`(FAPI 源 920 前缀北交所日线,数据起点 20260819,com.trade.fapi-daily 18:10 每日写入)
  - `data/sentiment.db:daily_metric`(写入目标,source='fapi',ON CONFLICT WHERE source!='manual')
- 数据截止:2026-09-03(生产库 daily_metric 实测:20260901 上涨 292/下跌 45/涨停 3/成交额 190.49 亿;20260903 上涨 40/下跌 295/涨停 0/成交额 215.97 亿)
- 口径一句话:北交所 920xxx(FAPI 源,约 339 只),涨跌幅规则 30% 档,涨停=close≥prev×(1.30)×0.999,最小 code 数 300 过滤采集不全日
- 相关脚本:`scripts/pipeline.sh beijiao`(pipeline 入口)/ `scripts/com.trade.beijiao-width.plist`(launchd 18:15)
- 修复链:本实施纯新增,无复刻脚本/页面数字断言,不涉及 §5.4⑦ 对账;回归对账用「改动版本地 JSON vs 线上 R2 + 生产库直接 SQL」双锚点,见第 5 节
