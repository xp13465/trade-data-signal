# gap_check 开盘价数据源单点调研(2026-09-23)

## 一、根因定位
- `scripts/nextday_gap_check.py` L100-120 `_fetch_opens` → 复用 `scripts/signal_kelly_backtest.py` L717-778 `_fetch_intraday_open_prices`。
- **主源唯一 = akshare `fund_etf_spot_em()`**(底层 `https://push2delay.eastmoney.com/api/qt/clist/get`,L751-752),15 前缀场内 ETF 无任何备源;16 前缀 LOF 有新浪/腾讯双源兜底(L770-775 → `_fetch_lof_open_via_http`)。
- 东财 push2 家族整体封禁:push2delay / push2 / push2his 三端点均 HTTP 000(本机 + 云上 122.51.111.173 双地实测,2026-09-23 15:3x);datacenter-web 端点 200 正常(不受影响)。
- 封禁为**请求模式/IP 级动态触发**:本机首次 curl 200,连续多次后变 000;社区(a.k. akshare GitHub issue #6613/#6658/#6787/#6856)大量同源 RemoteDisconnected 记录,典型为"连续请求~200 次后封,网页端正常",恢复时长从数小时到数天不等,个别长期弃用。

## 二、现有兜底核查
- `_fetch_intraday_open_prices`(signal_kelly_backtest.py L717):主源 fund_etf_spot_em fail-closed(取不到即 RuntimeError→就绪闸 FAIL→severe 告警+标记未完成);LOF 兜底仅限 16 前缀(L773 `c.startswith("16")`)。
- `_fetch_lof_open_via_http`(L781-824)已有现成双源直连结构:新浪 `hq.sinajs.cn/list=sz+code`(需 Referer)+ 腾讯 `qt.gtimg.cn/q=sz+code` 兜底,`split(',')[1]` / `split('~')[5]` = 今开。**该结构可直接泛化到 15 前缀 ETF**(区别仅前缀 sh/sz 映射:5 开头→sh,1 开头→sz)。

## 三、候选源实测矩阵(2026-09-23 收盘后本地+云上实测)

| 候选源 | 可用性(云上) | 今开字段 | 口径 | 限流/封禁风险 | 接入成本 |
|---|---|---|---|---|---|
| 腾讯 qt.gtimg.cn | 200 ✓ 8/8 批量 | split('~')[5] | 与东财同为当日开盘价;实测与新浪逐位一致 | 项目 memory 有"腾讯 WAF 频率风控"(60s 轮询场景),但 gap_check 每日 2 次低频,风险低 | 已有 LOF 兜底同结构,泛化前缀即可 |
| 新浪 hq.sinajs.cn | 200 ✓ 8/8 批量(需 Referer) | split(',')[1] | 同腾讯逐位一致 | 需 Referer;15 次连打实测安全(项目 global-ticker 调研) | 同上 |
| baostock | 未验证(T+1 源) | — | **T+1 日线,9:26 盘中拿不到当日开盘价** | — | **排除** |
| 东财 datacenter-web | 200 ✓ | — | 历史/报表端点,无实时 ETF 行情 | 同东财体系(可能联动封) | 无现成 ETF 开盘价接口 |
| 东财 push2 主 host | 000 ✗ | — | — | 已被封 | 不可用 |
| akshare fund_etf_spot_ths | 200 ✓ 但**返回基金净值非场内行情** | 无开盘价列 | 同花顺场外净值,不适用 | — | 排除 |

**今日受影响真实标的**:云上 20260923 auto_trade_steps.json 中 561120(家电ETF富国)3 条被标「伪跳空校验未完成(待人工)」。腾讯今开=1.250、新浪今开=1.250 逐位一致,双源可兜底。

## 四、推荐默认方案
**泛化现有 LOF 双源兜底到全部 15/16 前缀 ETF,作为 fund_etf_spot_em 失败时的第二数据源(fail-closed 保持,只加源不放松闸)**:
1. 主源保持 akshare `fund_etf_spot_em`(东财,数据日期新鲜度校验 F4 保留)。
2. 主源抛异常时,对全部 target(不再只 16 前缀)走新浪(主)+腾讯(备)双源直连,前缀规则 `code[0]=='5'→'sh'`,`code[0] in '1234'→'sz'`。
3. 兜底源无数据日期列 → 用腾讯时间戳字段[30]=YYYYMMDDHHMMSS 校验当日性(fail-closed 等效)。
4. 两源均取不到真实>0 今开才 RuntimeError(fail-closed 不放松)。
- **需用户拍板点**:①东财源失败才启用兜底,不改变主源口径(开盘价口径三源实测一致) ②涉及核心实用功能(伪跳空剔除),按 §5.4⑥ 动 AI 推荐/过滤链路的默认组合/算法需发中间版本;但此处是**加兜底不改主源默认**,倾向不动版本,由主控确认。
- 判据区分:「临时封禁无需改」= 明日 9:26 前东财自行恢复且连续 N 日稳定;「需建兜底」= 明早仍 000 或反复(本项目历史:东财 push2 家族 2026-07/08/09 反复封禁,memory 已多次弃用,建兜底概率高)。

## 五、兜底已落地(2026-09-23 用户已拍板实施,实现见 `scripts/signal_kelly_backtest.py`)
**泛化已上线到代码**(feat/gapcheck-multisource,实施实现细节):
1. **主源失败路径**:`_fetch_intraday_open_prices`(L717)主源 `ak.fund_etf_spot_em()` 抛异常时,对**全部 target**(不再只 16 前缀)走新泛化函数 `_fetch_intraday_open_via_http`(L795,由原 `_fetch_lof_open_via_http` 泛化)。
2. **主源成功路径行为零变化**:主源成功时仍按原逻辑取 `fund_etf_spot_em`「开盘价」列 + F4 数据日期校验;missing 的 16 前缀 LOF 仍走兜底(但改用泛化函数,L795-789 注释说明"主源成功时行为零变化,15 前缀主源已覆盖,不额外启用兜底")。
3. **前缀规则**:`code[0]=='5'→'sh'`(上交所,如 561120/510300)、`'1'→'sz'`(深交所,如 159920/160717)。
4. **当日性校验(等效 F4)**:兜底用腾讯时间戳字段[30]=YYYYMMDDHHMMSS 前 8 位 == expect_date 校验当日;腾讯取不到/时间戳缺失/非当日 → 该 target 拒用(fail-closed,同 F4「陈旧快照拒用」精神)。
5. **fail-closed 不放松**:任一 target 两源均取不到真实 >0 今开才 RuntimeError(不拿 0/空值当今开);主源失败原因随附在异常消息里便于排查。
- **消费点覆盖**:`_fetch_intraday_open_prices` 两处调用方均自动受益——`scripts/nextday_gap_check.py:120`(gap-check 就绪闸)与 `scripts/signal_kelly_backtest.py:1993`(回测盘中增量档)。
- **未改前端源码,不 bump 版本串**;主源口径/默认组合不变(§5.4⑥ 纯新增降级路径,不动版本)。
