# 同花顺 FAPI 接入方案 + 试点验证报告

- 日期:2026-09-02(报告标题日期沿用任务号 20260901)
- 调研人:researcher(role-researcher skill)
- 对应 TASKS:#16/#17/#18/#19
- 分支:research/fapi-h-k1
- 试点脚本:`docs/fapi/scripts/probe_fapi.py`(一次性探针,只读/test 产物,不碰生产)

---

## 0. 结论速览(TL;DR)

| 任务 | 结论 | 试点证据 |
|---|---|---|
| P0 日线 T+0 | **可行,推荐落地为 mootdx 的官换届兜底**。FAPI 全市场 dump 已实测 T+0:10 交易日窗口最后一日=20260901(当天收盘数据当晚即有),主键 `(thscode,date_ms)` 零重复,单次下载~1.1MB 覆盖 5553 只(含北交所 339 只,mootdx 不覆盖) | dump10d 实测 55448 行/5553 code/10 日窗口 |
| P1 涨停池兜底 | **可行,强一致**:涨停 80 vs 东财 83(差 3 只,~4% 口径差)、跌停 0 vs 0、炸板 6 vs 东财炸板率反推 6、连板高度 7 vs 7(海鸥住工 7 连板逐位一致) | zt 试点 |
| P1 龙虎榜 | **FAPI 有**(dragon-tiger-list 单端点 all/org/hot_money 三榜)。总数 68 vs 东财 79(口径差:东财=上榜记录数含 3 日榜,FAPI 有 range_days 字段区分 1/3 日),org_net_value 可对 lhb_inst_net | lhb 试点 |
| P1 THS 指数官方 | **可行,推荐直接换**:catalog 概念 390 + 行业 320,远超现有 27 概念;白酒概念 885525.TI 历史 K 覆盖到 20260901 | index 试点 |
| P2 盘中延迟 | 方法论已落档(见 §6),**待明日盘中实测** | - |

核心判断:**FAPI 数据与现有东财/mootdx 口径基本逐位一致,官方源无反爬,值得作为 P1 兜底/P1 换源逐步接入;P0 dump T+0 收益最大**(解决 Baostock T+1 痛点 + mootdx 断片补漏 + 北交所缺口)。

## 1. 现状盘点(日线采集链路)

### 1.1 当前链路(17:50 update_all.sh → 4 pipeline)
```
update_all.sh(17:50,flock 互斥)
├─ core pipeline:   metrics / indices / industry_extras      (akshare + 东财直爬)
├─ width pipeline:  mootdx → mootdx_daily_raw(全A日线,T+0) → industry_width + width_history
├─ turnover pipeline: baostock → baostock_daily_raw(T+1) → cleanup_d3d2 算 a_turnover
├─ stock_daily pipeline(后台死端): stock_daily.py(akshare 东财kline,已封停用)
└─ futures pipeline: 期货前20会员持仓
```

### 1.2 相关脚本与数据表
| 表/脚本 | 说明 |
|---|---|
| `data/stock_daily.db:mootdx_daily_raw` | **主力表**(5200 只,10年+),code/date/open/high/low/close/volume/amount/pct_change(自算)/turnover(null)。`idx_*` 全建。库中实际只剩它+baostock 表,`stock_daily_raw`(东财 kline)已无表(被封后废弃) |
| `data/stock_daily.db:baostock_daily_raw` | T+1 兜底,补 turnover(换手率)/preclose。单连接串行 0.3s 节流,万科 5072 只约 1h;默认不跑(RUN_BAOSTOCK 才启用,runner.py L383 注释) |
| `app/collector/mootdx_daily.py` | 通达信 TCP 7709,不受东财 IP 封锁,10 分钟串行全 A,T+0 盘后 |
| `app/collector/baostock_*.py` | T+1,2026-07 起 3 并发封禁两次,降 1 worker(L46 熔断告警前科) |
| `app/collector/stock_daily.py` | akshare 东财 kline,东财 push2his 全家被封后实际停用(runner.py step 5 仍留死端) |
| `app/collector/runner.py L355-378` | stock_daily step;L380-420 baostock step(默认跳过) |
| `scripts/pipeline.sh` | 4 pipeline 定义,stock_daily=死端不 export |

### 1.3 T+1 痛点定位(为什么需要 FAPI)
1. **BaoStock 是 T+1**:17:50 跑 turnover pipeline 时当天数据拿不到,当日宽度/换手率要次日才齐
2. **mootdx 有断片实测**:本地 mootdx_daily_raw 最新日期分布 = 09-01 当天 5176 只 / T-1 9 只 / 超一周断片 15 只(如 000001 停在 08-24,断 6 个交易日)
3. **北交所缺口**:mootdx 不覆盖 430/830/920;baostock 也不支持北交所(baostock_skipped_bj.txt)。FAPI dump 实测含 339 只北交所
4. **兜底质量**:mootdx 通达信全 empty 时(2026-07-17 曾 80 节点 0 可用)自动切 baostock,但 baostock 当天同样缺当日数据——劣质兜底
5. width_history 聚合依赖 mootdx_daily_raw,mootdx 断片日=宽度历史断点

## 2. P0 日线 T+1→T+0 落地设计(FAPI 全市场 dump)

### 2.1 FAPI dump 流程(3 步,已实测)
```
① GET /api/dump/market-dumps/daily-k-10d/download-url  (X-api-key 头)
   → data.presigned_url / expires_in_seconds(实测 URL 为 o.thsi.cn 对象存储,短时效)
② 立即 GET presigned_url 下载 Parquet(dump 实测 1.1MB / 55448 行 / 10 交易日)
③ pyarrow 读 → UPSERT 到专用表,主键 (thscode, date_ms) 天然唯一(实测 0 重复)
```

**dump schema(实测)**:
```
thscode/currency/interval/adjusted/date_ms(int64 毫秒 Asia/Shanghai 零点)
open_price/high_price/low_price/close_price/volume(股)/turnover(成交额!注意命名坑)
```
⚠️ **命名坑:FAPI `turnover` = 成交额(元),而 akshare/mootdx 的 `turnover` = 换手率(%)**。映射必须物理交换,否则换手率/成交额全错。

### 2.2 覆盖与一致性验证(实测)
- 10 个交易日窗口:20260819-20260901,最新日=20260901(T+0 成立,当晚数据在位)
- 唯一性:(thscode,date_ms) 重复 0
- 覆盖:5553 code,最新交易日 5546 行;北交所 339 只(920xxx 样例 920000.BJ 13.65 等)
- 逐位对照:600519.SH@20260901 close=1299.56 vs mootdx 600519 close=1299.56 ✓ 逐位一致
- 与库内口径:mootdx 表 code 为纯代码"600519",FAPI 为"600519.SH"(需去后缀映射,注意 000001 深市与 600xxx 沪市同规则即可,北交所 .BJ 后缀对应 920xxx)
- 8/28-9/1 与本地库横向抽查可复现(见 ## 复现)

### 2.3 落地建议(新建 vs 改造)
**推荐:新建采集脚本 `app/collector/fapi_daily.py` + 新表 `fapi_daily_raw`,不改造现链**:
- 理由 1:不改 mootdx 主链(生产稳定性 §14,17:50 时点已满负荷)
- 理由 2:字段语义差异大(no pct_change/无换手率/成交额命名坑),复用 stock_daily_raw 会污染
- 理由 3:作为「每日 T+0 官换届兜底 + mootdx 断片自动补",与 mootdx 形成双源互证(§15.1 异源互备范式)

**表结构建议**(对齐 mootdx_daily_raw 列语义):
```sql
CREATE TABLE IF NOT EXISTS fapi_daily_raw (
  code TEXT NOT NULL,          -- 600519(去后缀整理)
  date TEXT NOT NULL,          -- 20260901
  thscode TEXT NOT NULL,       -- 600519.SH 保留原始
  open REAL, high REAL, low REAL, close REAL,
  volume REAL, amount REAL,    -- FAPI turnover → amount(成交额)
  UNIQUE (thscode, date_ms),   -- 若存毫秒;或 UNIQUE(code, date)
);
```
(本文档不锁死 sqlite 细节,实施时可对齐 width_history 下游需要的列:width_history 用 open/high/low/close/amount + 自算 pct_change)

**字段映射(dump → 表)**:
| dump 列 | 目标列 | 处理 |
|---|---|---|
| thscode 600519.SH | code=600519 / thscode 原样 | 去后缀 `.SH/.SZ/.BJ` |
| date_ms | date=YYYYMMDD | ms→date, Asia/Shanghai |
| open/high/low/close_price | open/high/low/close | 直接 |
| volume | volume | 股 |
| turnover | amount | **成交额,命名交换** |
| (无) | pct_change | 自算 close/prev_close-1(与 mootdx 同口径) |
| (无) | turnover 换手率 | 缺失,NULL(由现有腾讯/快照链补) |

**增量策略**:
- 常规:daily-k-10d(每交易日下载一次,1.1MB,10 日窗口)
- **10 日增量落后 >7 自然日 → 切 daily-k(10 年全量)重建**(契约原文推荐口径)
- 全量 daily-k 实测 verify:更新 download-url 后下载即可,10y dump 行数约 945 万行(主控情报),单次 ~200-500MB 量级,仅兜底重建用,不每日拉

**调度时点**:17:50 update_all 之后(18:00+),或在 update_all.sh 后追加一个 fapi pipeline;避开 15:35/16:00/17:50/20:35/22:00 既有任务(§14)。**推荐 18:10 独立 launchd 任务**(与 update_all 错峰,7 分钟余量)。

**多源一致性校验(§22)**:
- 每日 fapi_daily_raw vs mootdx_daily_raw 同交易日逐 code 对 close,阈值(如差异 >0.5% 的 code 数 >N)告警
- 挂 deploy 前 check(与 check_universe_alignment 同链),不一致阻断
- N 文件同步:该表仅供宽度/行业宽度下游,不直接上公网 JSON,故无 §22 三文件同步问题(但要保证宽度产物重跑依赖它时重跑部署三步)

### 2.4 风险与边界
- 预签名 URL 短时效(≤5 分钟):流程必须下载=签名+下载连续,不能先签名后隔夜
- FAPI 限流 4001:指数退避最多 3 次(治理规则);dump 端点 1 天 1 次,风险低
- 10d dump 不覆盖停牌股最近日:最新日 5546 vs 5553(7 只停牌缺席)——正常,不用补
- 北交所纳入后 width 口径会变化(总家数增加):**必须先与用户确认宽度宇宙口径是否纳入北交所**,再决定 fapi 是否同步 width,防止 §23.13 口径三源事故
- 上线节奏:新建源默认不替换主源(§23.7 只增不改),先双写互证观察 ≥1 周,数据逐位一致后再评估转主

## 3. P1 涨停池 + 龙虎榜备用源

### 3.1 FAPI 涨跌停字段 vs 现有 stock_zt_pool_em(东财)
现有指标(indicators.yaml L22-29):
| 指标 | 东财 func | transform | FAPI 对应 |
|---|---|---|---|
| a_width_zt_count | stock_zt_pool_em | count_rows | limit-up-pool pagination.total |
| a_width_dt_count | stock_zt_pool_dtgc_em | count_rows | limit-down-pool pagination.total |
| a_width_max_lianban | stock_zt_pool_em | max(连板数) | max(item.continue_day_cnt) |
| a_width_zhaban_rate | zbgc/em 池 | ratio_count | limit-break-pool.total / limit-up-pool.total |
| a_width_fengban_rate | derived | 1-zhaban | 同上 |

FAPI limit-up-pool item 字段:thscode/ticker/name/is_st/is_new/last_price/price_change_ratio_pct/limit_up_time/limit_up_reason/continue_day_text/continue_day_cnt/seal_money/max_seal_money —— 覆盖东财池的代码/名称/涨跌幅/最新价/连板数/封板时间语义,缺:成交额/流通市值/总市值/换手率/炸板次数/所属行业(本指标仅 count/max,不影响)

**实测对比 20260901**:
| 指标 | 东财(daily_metric) | FAPI | 判定 |
|---|---|---|---|
| 涨停数 | 83 | 80 | 差 3 只(~4%),口径差(东财封板口径 vs FAPI 全板?)→ 兜底可接受,替换需先 diff 差集 |
| 跌停数 | 0 | 0 | 一致 |
| 炸板率 | 6.74%(=炸板 6/89) | 炸板池 total=6 | 逐位一致 |
| 连板高度 | 7 | max=7(海鸥住工 7 连板) | 逐位一致 |

### 3.2 龙虎榜:有
**FAPI 有龙虎榜端点**:`GET /api/a-share/special-data/dragon-tiger-list?board_type=all|org|hot_money&date=yyyy-MM-dd`,一次全量不分页,返回:
- stock_items:thscode/ticker/name/change/net_value(净买入额)/net_rate/buy_value/sell_value/hot_rank(同花顺人气)/limit_reason/range_days(1=当日榜,3=3日榜)/org_net_value/org_net_rate/org_buy_num/org_sell_num/amount/hot_money_net_value...
- hot_money_items:游资维度榜单(名称/聚合净买/相关股票列表)

对现有:
| 指标 | 东财 func | FAPI 对应 |
|---|---|---|
| lhb_count | stock_lhb_detail_em | count(记录数) 或 stock_count(去重后股数) |
| lhb_inst_net | stock_lhb_jgmmtj_em sum(机构买入净额) | sum(stock_items.org_net_value) |

实测 20260901:FAPI count=68 stock_count=64 vs 东财 lhb_count=79。差异来源:东财按「上榜记录」计数(含当日+3日榜重复),FAPI 有 range_days 区分。**替换 lhb 前必须逐位 diff 上榜清单**(东财上榜定义 vs FAPI 口径),先并行存一周再切。

### 3.3 兜底切换机制建议
- **涨停池**:沿用现有 multisource.py 模式(fetchers.py `_run_multisource` 已有多源范式:主源空→异源兜底→source 标记),**新增 key=fapi_zt,当前离线池 cross_check 用 FAPI 池替代/补充 akshare 池**(主东财、兜底 FAPI,同花顺信源天然对齐现有同花顺涨停池备用)
- 龙虎榜:lhb 走 collect_snapshot(akshare 东财)→ 空时 FAPI 兜底,source 标 `fapi`
- 并行互校验:反向不搞(不增加请求压力),单向 failover + source 追溯(与现有 daily_metric.source 一致)

## 4. P1 同花顺行业/概念换官方

### 4.1 现状痛点
- 现有 27 个概念走 akshare `stock_board_concept_index_ths`(T+1 偶发:当日点次日才出)+ `stock_board_concept_info_ths` 当日快照合成 OHLC(补当日行);申万 31 一级行业实时涨跌幅走 `stock_board_industry_summary_ths`(90 子行业聚合)
- 痛点:T+1 偶发、akshare 封装不稳定、概念仅 27 个覆盖窄

### 4.2 FAPI 官方端点(capability-map a-share-index)
| 端点 | 用途 | 现替代 |
|---|---|---|
| `GET /api/a-share-index/catalog/ths-index-list?tag=cn_concept\|industry\|region\|tszs` | 概念 390 / 行业 320 指数清单,一次全量 | - |
| `GET /api/a-share-index/constituents/ths-stock-list?thscode=` | 成分股清单(支持 886042.TI 板块 + 000300.SH 标准指数) | legulegu(申万成分) |
| `GET /api/a-share-index/prices/snapshot?thscodes=` | 指数行情快照(批量,必须传 thscodes) | 腾讯/新浪 |
| `GET /api/a-share-index/prices/historical?thscode=&interval=1d&start=&end=` | 单指数历史 K(≤10 年窗口) | akshare index_hist_ths_concept |

### 4.3 实测
- catalog:概念 390 个(含"白酒概念""机器人概念""人形机器人")、行业 320 个(含"白酒""机器人")
- 白酒概念 thscode=885525.TI,历史 K 22 条(20260801-0901),末条 20260901 close=6174.585 ✓ T+0
- ⚠️ **契约示例写 886042.TI 是白酒概念,实测 catalog 里白酒=885525.TI**——以 catalog 为准,示例可能过时

### 4.4 一致性问题
- 现有 indicators.yaml 概念 ID 是 `thsc_300816`(机器人概念)这类**THS 板块 python 代码**,而 FAPI 是 `885xxx.TI`(THS 官方指数码)。**两者不是同一编码体系,需名称映射**(symbol="机器人概念" → catalog name 匹配)
- 实测唯一规:行业 thscode 前缀 881(90 只)/884(230 只),概念 885(293)/886(97 只)——无单一前缀对应关系,换源一律以 catalog name 精确匹配为准。现有 akshare 概念历史表存 THS 板块代码 thsc_xxxx(如 thsc_300816=机器人概念),与 FAPI 885xxx.TI 编码体系不同,须名称映射 + 同概念历史数值逐位核对后换
- 申万 31 一级行业实时涨跌幅 → FAPI 行业指数 320 个,**不是同花顺的行业=申万行业**,不能直接换申万;仅当把同花顺行业/概念纳入展示时才用 FAPI
- **换源前必须先跑 1 周并行对照**(FAPI 885xxx vs akshare thsc_xxx 同概念历史逐位对齐率),对齐后再切换,防 §23.13

## 5. 字段映射总表(实施依据)

| FAPI 端点 | FAPI 字段 | 映射到 | 备注 |
|---|---|---|---|
| prices/snapshot | thscode/ticker/last_price/price_change/price_change_ratio_pct/open_price/high_price/low_price/prev_price/volume/turnover | 腾讯/新浪实时行情 | 无 name(需 search 解析) |
| prices/historical | date_ms/open_price/high_price/low_price/close_price/volume/turnover(+adjust 参数前复权) | stock_daily_raw(OHLC/amount) | 单标的一年请求,10 年窗口上限 |
| dump daily-k-10d / daily-k | thscode/date_ms/OHLC/volume/turnover | mootdx_daily_raw 同构 | **T+0 全市场批量**,P0 主案 |
| dump adjustment-factors | thscode/ex_date_ms/dividend_per_share/per_share_bonus/allotment_ratio/allotment_price | 复权事件(新表) | 可选增强(当前不复权) |
| special-data/limit-up-pool | pagination.total/continue_day_cnt/limit_up_time/seal_money/name/is_st | a_width_zt_count/max_lianban(东财口径兜底) | 实测 80 vs 83 |
| special-data/limit-down-pool | pagination.total/first/last_limit_time/turnover_ratio_pct | a_width_dt_count | 实测 0 vs 0 |
| special-data/limit-break-pool | pagination.total/items | a_width_zhaban_rate 分子 | 实测 6 vs 6 |
| special-data/limit-up-ladder | 近 30 日连板梯队矩阵 | (新能力:连板分布图) | 可选增强 |
| special-data/dragon-tiger-list | count/stock_count/net_value/org_net_value/org_net_rate/buy_value/sell_value/hot_rank/range_days/hot_money_items | lhb_count/lhb_inst_net(兜底) | 实测 68 vs 79,需差集 diff |
| a-share-index/catalog/ths-index-list | thscode/name(tag 四类) | THS 概念/行业清单(现有 27 概念扩展) | 390+320 全量 |
| a-share-index/constituents/ths-stock-list | thscode/ticker/name | legulegu 申万成分替代(概念成分) | 标准指数也支持(000300.SH) |
| a-share-index/prices/snapshot | 同 snapshot item | 盘中指数实时 | 批量必须传 thscodes |
| a-share-index/prices/historical | 同 PriceBarItem(无 adjust) | index_hist_ths_concept 官方版 | 单指数单请求 |
| calendar/trading-days | date_ms/date(yyyyMMdd) | app.calendar 交易日历来源 | 近 1 年固定窗口 |
| meta/tickers/list | 代码表全量 | stock_codes.json 宇宙重建 | 分页按资产类型 |
| auction(集合竞价) | 竞价快照/风向标 | (新能力) | 可选 |

## 6. P2 盘中延迟实测方法论(待明日开盘)

### 6.1 测什么
- **FAPI snapshot 的 `data.timestamp`(数据就绪时间)vs 真实行情时间**(交易所连续竞价 9:30-11:30/13:00-15:00)
- 延迟 = 快照 timestamp - 采样时刻(或对比腾讯/东财同 tick 价格出现的时刻差)

### 6.2 怎么测(盘中脚本)
```python
# 每 60s 一轮,共测 09:35/10:00/10:30/11:00/13:30/14:00/14:30/14:58 等 8-10 个采样点
# 每轮:
#   1) FAPI /api/a-share/prices/snapshot?thscodes=600519.SH,000001.SZ,300750.SZ
#      → 记录 last_price + data.timestamp
#   2) 同刻腾讯 qt.gtimg.cn/q=sh600519,sz000001... → last_price(秒级参考真值)
#   3) 差 = FAPI timestamp(ms) - 本机采样时刻(ms);价格差 = |FAPI last - 腾讯 last|
# 判据:①数据就绪延迟的分位数分布(p50/p90/p99) ②价格逐位一致率
```

### 6.3 判据与用途
| 延迟档 | 适合用途 |
|---|---|
| <5 秒 | 可直接做盘中最面实时(替代腾讯轮询) |
| 5-60 秒 | 分钟级轮询冷启动/短线情绪面板可用 |
| 分钟级(1-5 分) | 仅盘后/复盘场景(现 snapshot 已知包含盘中生效值,可作收盘价兜底) |
| >5 分钟 | 仅 T+0 盘后采集(FAPI 价位收盘一致),不适合盘中 |

### 6.4 测完结论使用方式
- 若秒级:可评估将 intraday_snapshot.py 的指数实时源(腾讯→新浪降级)加 FAPI 为第二兜底(§23.3 举一反三:同链)
- 若分钟级:维持现实时链,仅把 FAPI 用作盘后 T+0 校验源(与 dump 互证)

## 7. 总体接入建议

### 7.1 优先级(建议实施顺序)
1. **P0 dump T+0(本周)**:新脚本 + 新表 + 18:10 launchd,双写 mootdx 互证观察 ≥1 周 → 评估转主
2. **P1 涨停池兜底(下周)**:multisource 加 fapi_zt key,failover 挂上,source 追溯
3. **P1 THS 指数官方(下周)**:先跑 885xxx vs thsc_xxx 并行对照 1 周,对齐后换
4. **P1 龙虎榜兜底(lhb 任务一起)**:先 5 日并行 diff 上榜清单(东财 vs FAPI),一致后 failover
5. **P2 盘中延迟实测(明日开盘)**:脚本化采样,数据说话再定盘中用途

### 7.2 风险清单
| 风险 | 等级 | 缓解 |
|---|---|---|
| FAPI 是单一外部依赖(同花顺),官方 API 不可用时无第二官方源 | 中 | 只做兜底/备用,主链不动;与 mootdx+mootdx 异构双源互备 |
| 4001 限流(约定 QPS) | 低 | 1 天 1 次 dump + 少量特殊数据请求,远低于限流;错误码 1xxx/2xxx 不重试、4001 指数退避 ≤3 次 |
| dump 预签名 URL 5 分钟过期 | 低 | 流程内签名即下载,不跨时点 |
| turnover 字段命名坑(成交额 vs 换手率) | 中 | 物理映射禁止同名直拷;机检字段类型断言 |
| 涨停池 80 vs 83 口径差 | 低 | failover 可接受;若转主力需差集 diff(差 3 只来源) |
| 龙虎榜 68 vs 79 计数口径差 | 中 | 先并行 diff 上榜清单,不一致保留东财 |
| 概念编码体系差异(885/881 vs thsc_xxx) | 中 | 名称映射 + 数值并行对照 1 周 |
| 北交所纳入宽度口径变化 | 中 | **须用户拍板宽度宇宙是否含北交所**,再动 width 下游 |
| Key 泄露 | 高 | 已存 .env;禁入 git/日志/dump;本报告不含 key;probe 脚本从 .env 读 |

### 7.3 是否需发版本(§5.4⑥)
- **P0 dump T+0 + 涨停池/龙虎榜兜底:P1 不涉及「AI 推荐/降亏过滤」核心默认组合,不需发中间版本**(§5.4⑥ 只覆盖动 AI 推荐核心默认组合/算法;数据源兜底属可靠性增强,默认行为不变——主链不动,新源只做互证观察,期间 AI 推荐读数不受影响)
- **P1 THS 指数换源:动的是「指数/概念行情展示」,非 AI 推荐核心,同理不需版本**;但需 §21 公示(指数数据源变更)+ README 数据源段同步(§23.1)
- **若后续要把 FAPI 数据接入 AI 推荐/过滤链路(如信号入样宇宙),必须发中间版本 + §5.4⑥ 全链同步**(18 处键集登记点 + 公示 + 基准定义)
- **观察期结论**:并行互证 ≥1 周逐位一致后,再评估「转主」并上会拍板,不默认切(§23.7)

### 7.4 改动范围(实施时)
- 新增:`app/collector/fapi_daily.py`(dump 下载→读→UPSERT)+ `scripts/pipeline.sh` 加 fapi step 或独立 launchd + 互证校验脚本
- 修改:runner.py `_run_multisource` 加 fapi 兜底 key(涨停池/龙虎榜);fetchers.py collect_snapshot 加 fapi_zt failover
- 不动:mootdx 主链、宽度计算、AI 推荐链路(观察期)

## 复现

**试点脚本**:`docs/fapi/scripts/probe_fapi.py`(一次性探针,已随本报告 commit)

**依赖**:`pip install pyarrow requests`;`.env` 的 `HITHINK_FINANCE_API_KEY`(脚本从 .env 读,不打印)

**重跑命令**(任选,输出落 /tmp/fapi_probe_out/):
```bash
cd /Users/linhuichen/code/trade
.venv/bin/python docs/fapi/scripts/probe_fapi.py dump10d   # dump 下载+唯一性+覆盖+T+0 窗口验证
.venv/bin/python docs/fapi/scripts/probe_fapi.py zt        # 涨停/跌停/炸板池 vs daily_metric 对照
.venv/bin/python docs/fapi/scripts/probe_fapi.py lhb       # 龙虎榜 vs daily_metric 对照
.venv/bin/python docs/fapi/scripts/probe_fapi.py index     # THS 概念/行业目录+白酒概念历史K
.venv/bin/python docs/fapi/scripts/probe_fapi.py snapshot  # 快照 vs 本地日线收盘对照
```

**输入依赖**:`data/stock_daily.db`(mootdx_daily_raw/baostock_daily_raw)、`data/sentiment.db`(daily_metric)、`.env`(API key)

**实测数据截止**:2026-09-02 00:12-00:40 深夜(dump 覆盖 20260819-20260901)

**关键口径一句话**:dump 主键 `(thscode,date_ms)` UPSERT;FAPI `turnover`=成交额(非换手率);涨停/跌停/炸板池 total 对应东财 count_rows 口径(max 连板=continue_day_cnt 取 max 实测 7 板逐位一致)。

**已知偏差(诚实标注)**:
- 涨停池 80 vs 东财 83:差 3 只待 diff(可能封板 vs 全板口径)
- 龙虎榜 68 vs 79:待上榜清单 diff(range_days 1/3 日口径差异)
- 概念编码 885xxx.TI/881xxx.TI vs 现有 thsc_xxxxx:待名称映射 1 周并行对照
- 快照 vs 腾讯实时延迟:待明日盘中实测(今日休市无法测)

**试点输出留档**:/tmp/fapi_probe_out/daily-k-10d.parquet(1.1MB,10 交易日全市场)、dump10d_summary.json
