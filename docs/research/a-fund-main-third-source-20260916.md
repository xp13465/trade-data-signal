# 沪深A股主力净流入(a_fund_main)第三独立数据源调研

日期:2026-09-16 调研人:researcher agent(只读调研,未改代码)
任务来源:主控派单。当前采集链 5 源仅 2 供应商(东财 eastmoney.com + 同花顺 10jqka.com.cn),
用户报告两者曾同时失败。目标:找第 3 个真正独立供应商。

## 一、结论一句话

**推荐新浪指数资金流接口(新浪财经,真正独立第三供应商)作为第 6 源**:
zhishu_000001(上证指数=沪市全部)+ zhishu_399106(深证综指=深市全部),
2 个请求拿全市场净流入历史序列。免费无 token、无反爬、500+ 天历史可 backfill、
30 交易日回测方向一致率 vs 东财主力 77%、vs 东财超大单 93%。
口径诚实标注:只能做方向判定(与 simple 类型需求吻合),不能做数值对账。

## 二、候选穷举表

| 候选 | 接口 | 免费/无token | 验证结果(2026-09-16 实测) | 口径 | 结论 |
|---|---|---|---|---|---|
| 新浪-指数资金流 | vip.stock.finance.sina.com.cn/api/json_v2.php/MoneyFlow.ssl_bkzj_zjlrqs?bankuai=zhishu_000001 + zhishu_399106 | 是/是 | **可用**,连发 5/5 成功,500 天历史(2024-08-23~2026-09-15) | netamount=各档净额合计;方向 vs 东财主力 77%、vs 东财超大 93% | **主推** |
| 新浪-个股资金流 | MoneyFlow.ssl_qsfx_zjlrqs?daima=sh600000 | 是/是 | 可用 | 个股 netamount;要全市场须爬几千只,不可行 | 弃(架构上不适合) |
| 新浪-行业资金流 | MoneyFlow.ssl_bkzj_bk?fenlei=0(48行业) | 是/是 | 可用但 fenlei=0 只覆盖沪市;fenlei=1 概念重叠不可求和;fenlei=2 证监会行业 154 个有 30 对前缀重叠 | 沪市 48 行业合计方向一致率 60%(20日) | 次选(覆盖不全) |
| 腾讯 | qt.gtimg.cn/q=ff_sh600519 | 是/是 | **已死**:今日返回 v_pv_none_match;社区 2020-07 实测"资金无法获取 返回零值" | 主力净流入(已失效) | 弃 |
| 网易 | 网易资金流(社区旧接口) | 是 | **已死**:502 | - | 弃 |
| 雪球 | stock.xueqiu.com/v5/stock/capital/flow.json | 是但 | 400016:需登录 cookie | - | 弃 |
| 百度股市通 | 未解出参数 | 是 | ResultNum 0,未验证成功 | - | 弃 |
| Tushare | moneyflow 接口 | 需 token | 免费积分档有 moneyflow(个股),无全市场合计;且底层疑似东财数据 | 主力净流入(东财系) | 不独立,弃 |
| akshare 底层源 | 本地 site-packages 源码核查 | - | stock/stock_fund_em.py=全部东财;stock_feature/stock_fund_flow.py=全部同花顺;**无新浪/腾讯封装** | - | 无新增供应商 |

结论:除新浪外,所有"独立于东财+同花顺"的免费候选要么已死(腾讯/网易),
要么需登录(雪球)、要么不独立(Tushare 东财系)、要么参数未解(百度)。

## 三、口径对标(30 交易日实测数据,零值日显式剔除)

东财主力(f52)= 大单+超大单净额,已用原始 15 字段行逐日验证(f52=f55+f56 精确相等)。
东财全档净额(f52+f53+f54+f55+f56)恒≈0(全市场买=卖恒等式,±4096 元误差),
因此"全部资金净额"对市场层面无意义——同花顺/新浪的"净额"实际都是子集口径。

| 对比对 | 方向一致率(30日) | 说明 |
|---|---|---|
| 新浪指数 net vs 东财主力 | **23/30 = 77%** | simple 类型只需方向,达标 |
| 新浪指数 net vs 东财超大单 | 28/30 = 93% | 新浪 net 更贴近超大单口径 |
| 新浪指数 r0_net vs 东财主力 | 16/30 = 53% | r0_net 口径差,弃用 |
| 东财主力 vs 东财超大单 | 25/30 = 83% | 参照系:东财内部两档也有 17% 分歧 |

量级不稳定(不可做数值对账):09-07 新浪 +1255亿 vs 东财主力 +382亿;09-11 -575.8亿 vs -526.6亿。
→ 新浪源只贡献方向,数值入库会有量级跳变,落地建议见第五节。

同花顺(现有第 5 源)参照:只有"即时"快照接口(无日线历史序列),无法做 30 日回测;
7-25 历史实测 sum=-969.56亿 vs 东财 -774亿(方向一致),2026-09-16 盘中快照 +281.4亿
vs 东财 09-15 主力 -257.9亿(方向相反,弱证据因不同步)。→ 同花顺拿不出方向一致率验证,
新浪源在"可验证性"上明显更优。

## 四、推荐落地要点

接口(2 请求):
```
https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/MoneyFlow.ssl_bkzj_zjlrqs?page=1&num=30&sort=opendate&asc=0&bankuai=zhishu_000001
https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/MoneyFlow.ssl_bkzj_zjlrqs?page=1&num=30&sort=opendate&asc=0&bankuai=zhishu_399106
```
- 返回 JSON 数组,字段:opendate(日期)/netamount(净额,**单位元**)/turnover/ratioamount/r0_net/r0_ratio/r0x_ratio/cnt_r0x_ratio。取 netamount。
- 沪深合计 = zhishu_000001.netamount + zhishu_399106.netamount
- 请求头:带浏览器 User-Agent + Referer: https://finance.sina.com.cn/(社区惯例,实测必须带 Referer 否则异常)
- 无 token、无 hexin-v 类反爬(同花顺 2026-09-16 实测:同会话第二次请求即 401,反爬脆弱性实锤)
- 历史深度:num=500 实测返回 500 天(2024-08-23~2026-09-15),支持 backfill
- **数据 T+1**:最新到昨日,盘中无当日数据 → 只适合盘后槽位(15:35/16:00),不能盘中用
- 反爬风险评估:低。vip.stock.finance.sina.com.cn 是新浪公开行情接口,社区广泛使用多年

落地建议(给 implementer):
1. 加入 direct.py fetch_market_fund_flow 第 6 源,排在同花顺之后(同花顺已有 hexin-v 成本,新浪更稳可考虑排同花顺前)
2. 数值跳变问题:simple 类型只看方向,但入库值随源切换会跳变(如主力口径 -258亿 vs 新浪口径 -85亿)。两个选项:A) 按现有模式直接入库值(与同花顺现状一致,同花顺也有 25% 量级差);B) 兜底源只写方向确认。默认推荐 A(保持 5 源现有模式简单,量级差异与同花顺现状相当)
3. 交易日对齐:新浪 opendate 是自然日序列,用 calendar.last_trading_day 对齐取最新交易日
4. backfill_direct_metrics.py 的 GAP_MARKER="两源皆败无数据" 是过期文案,实际五源/六源,顺带更新

## 五、诚实标注(局限)

1. 77% 方向一致率意味着 23% 交易日两源方向分歧——但东财内部"主力 vs 超大单"本身也有 17% 分歧,分歧不是新浪独有的
2. 新浪 netamount 的确切口径(各档阈值)未找到官方定义文案,只验证了 netamount=Σ(r0..r3 各档 in-out)(个股实例精确相等);指数级 netamount 为何不为 0(理论上全市场全档应抵消)未能完全解释——可能与指数成分/统计口径有关,不影响"方向"使用
3. 量级不可对账,数值口径与东财主力差 1.5~15 倍不等
4. T+1 时效,盘中无当日数据

## 六、社区先例

- CSDN「新浪、腾讯股票价格相关接口」(blog.csdn.net/xcxzzx01/article/details/79589012):腾讯 ff_ 字段映射(主力流入/流出/净流入/占比)
- CSDN「个股当日资金流向接口」(blog.csdn.net/weixin_33842328/article/details/94445244,转载 cnblogs ibearpig 2014):新浪 ssi_ssfx_flzjtj 返回结构 {r0_in,r0_out,r0,r1_*,...,netamount},实测验证 netamount=Σ(ri_in-ri_out) 精确相等
- CSDN「腾讯股票接口、和讯网股票接口、新浪股票接口、雪球股票数据、网易股票接口」(blog.csdn.net/weixin_38092816/article/details/123420645):2020-07 社区实测「银河量化:资金无法获取 返回零值」——腾讯 ff_ 接口 2020 年起失效
- 本地 akshare 源码核查:site-packages/akshare/stock/stock_fund_em.py(全东财)、stock_feature/stock_fund_flow.py(全同花顺),无新浪封装

## 七、复现段

```bash
# 东财主力 15 字段原始行(口径验证)
curl -s -H "User-Agent: Mozilla/5.0" "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get?lmt=0&klt=101&secid=1.000001&secid2=0.399001&fields1=f1,f2,f3,f7&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65&ut=b2884a393a59ad64002292a3e90d46a5"
# 新浪指数资金流(沪深各一次,netamount 单位元)
curl -s -H "User-Agent: Mozilla/5.0" -H "Referer: https://finance.sina.com.cn/" "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/MoneyFlow.ssl_bkzj_zjlrqs?page=1&num=30&sort=opendate&asc=0&bankuai=zhishu_000001"
curl -s -H "User-Agent: Mozilla/5.0" -H "Referer: https://finance.sina.com.cn/" "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/MoneyFlow.ssl_bkzj_zjlrqs?page=1&num=30&sort=opendate&asc=0&bankuai=zhishu_399106"
```
方向一致率脚本逻辑:沪深 netamount 逐日相加 → 与东财 f52 逐日比符号(±1e6 元内按零值剔除)。
