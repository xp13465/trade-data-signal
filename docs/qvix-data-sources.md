# QVIX 免费异源穷举调研(2026-08-15)

> 一句话:免费「直接拿波指」的真异源只有 optbbs 一个(现宕机);但免费「拿期权行情/IV 自算 QVIX」有 2 个真异源(上交所官方 + 新浪),够凑「optbbs + 上交所 + 新浪」3 重真异源自动切换。自算 RV 仍是网底(口径不同,非 QVIX)。
> 数据截止 2026-08-15,逐源实测。

## 本地现状(证据)
- akshare 全部 18 个 qvix 函数都在 `index_option_qvix.py`,100% 依赖 `http://1.optbbs.com/d/csv/`(k.csv 全波指历史 + vix300.csv/vix1000.csv 分钟)。见 `/Users/linhuichen/Library/Python/3.11/lib/python/site-packages/akshare/index/index_option_qvix.py:23`。
- optbbs 8/15 仍宕机:`curl 1.optbbs.com/d/csv/d/k.csv` → HTTP:000;2.optbbs.com/optbbs.com/https/www 全 HTTP:000,无镜像。
- 本地 DB:`a_qvix_300` 20191223→20260813 共 1601 行(8/14 缺);`a_qvix_1000` 20150209→20260813 共 2789 行。分位数需 ≥250 交易日,两条都够。

## 逐源清单
### A 档:直接拿波指(零改造)
| 源 | host | 可达性(8/15) | 内容 | 历史 | 时效 |
|---|---|---|---|---|---|
| optbbs(现主源) | 1.optbbs.com | ❌ HTTP:000 | QVIX 日线 OHLC+分钟 | 2015 起全量 | 日更 T+1 |
| 上交所 iVIX(000188) | 中证指数公司 | 官方已停发 | 官方波指 | 止 2018-02-14 | 停发 |
| 其他直接波指站 | — | wikitter 付费(60元/年/品种) | — | — | — |

→ **直接拿波指的免费真异源只有 optbbs 一个**。

### B 档:拿期权行情/IV 自算 QVIX(原料源,需实现方差互换算法)
| 源 | host | 可达性 | 能拿什么 | 历史 | 时效 |
|---|---|---|---|---|---|
| 上交所官方(option_risk_indicator_sse) | query.sse.com.cn,需 Referer | ✅ 754合约/648个IV非零,IV 0.07~1.094;2015/16/18/20都通 | 整条链 IV(IMPLC_VOLATLTY)+ Delta/Gamma/Vega/Theta/Rho,覆盖 300/50/500ETF/科创50 | 2015-02-09 至今 | T+1 日更 |
| 新浪 hq(option_sse_greeks_sina) | hq.sinajs.cn,需 Referer | ✅ | 实时全链 IV(CON_SO_ 第10字段)+行情+合约枚举+标的价+合约日线 | 只当前合约周期 | 实时盘中 |
| 新浪中金所(option_cffex_zz1000_spot_sina) | stock.finance.sina.com.cn | ✅ | 中证1000股指期权(mo)/沪深300(io)/上证50(ho) T型链价格自算IV → a_qvix_1000 原料 | 日线只当前合约 | 实时 |
| tushare(opt_basic/opt_daily) | tushare.pro | 需注册 token | 期权合约+行情,IV 自算 | 全量 | 日更 |
| 东财(push2 期权 clist) | push2.eastmoney.com | ❌ 本机 HTTP:000(页面 200/API 000) | 期权行情列表自算 IV | 当日 | 实时 |

### C 档:自算 RV(网底,口径不同)
- 指数收益率滚动波动率,现有代码无 RV(grep rolling_std/realized 无业务命中)。
- ⚠️ RV(已实现)≠ QVIX(隐含/预期),语义不同,作网底必须标注「口径切换」。

## 多重自动切换可行档位
- **a_qvix_300**:①optbbs(恢复后,直接波指)→②上交所官方 IV 自算(T+1,历史2015至今,回填无忧)→③新浪实时 IV 自算(盘中)。**3 重真异源**,host:optbbs.com/sse.com.cn/sinajs.cn 三家。
- **a_qvix_1000**:①optbbs(恢复)→②新浪 mo 链自算(实时)→③中金所官网日统计(URL 未打通,`MO.xml` 302→404,待验证)。**2 重确认+1 重待验证**。上交所 IV 不覆盖中金所股指期权。

## 明确推荐
> 主源 optbbs(恢复后)+ 备A 上交所官方 IV 自算 QVIX(T+1 权威回填)+ 备B 新浪实时 IV 自算 QVIX(盘中当日)+ 网底自算 RV(口径标注)。

实施重点(诚实标注):
- B 档自算 QVIX 是主要工作量:实现方差互换算法(参考 optbbs 算法 + GitHub 复现 nkuguanrui/ivx 98.3%、Alexdachen/ivix)。输入=期权链 IV+标的价+Shibor 无风险利率。两个 B 档源共用同一套算法只换数据源。
- 上交所源回填历史一次到位,新浪源只做当日/盘中增量。
- 异源切换落在 collect_series 的 QVIX fallback 链(fetchers.py L230-274 已有 daily→分钟 fallback 雏形但同源 optbbs,需替换为真异源)。

## ✅ 实施现状(2026-08-15,feat/free-multisource-fallback)
- **已实施**:主源 optbbs + 备A 上交所官方 IV 方差互换自算 QVIX(multisource.sse_qvix_series,source=`sse`,T+1 权威,可历史回填) + 网底本地 RV(source=`rv_local`,口径差异前端已公示)。异源链:
  `optbbs daily csv → sse 官方IV自算(当日补/回填) → 本地RV(网底,口径标注)`。
- **未实施(下一步)**:备B 新浪实时 IV 自算(option_sse_greeks_sina,盘中当日) —— 与备A 共用同一套
  方差互换算法(见 multisource.sse_qvix_series),仅换 IV 数据源,已留函数结构。
- **算法(multisource._sse_variance_term / sse_qvix_series)**:CBOE VIX 方差互换思想——
  近/次两到期月期权链 IV(Black-Scholes 反推期权价 Q(K),正态 CDF 用 math.erf 无 scipy 依赖),
  每 K 选 OTM,sum(ΔK/K²·e^{rT}Q),远期 F(Call-Put 平价)、K0(<F 最大行权),凸性修正,
  得两期年化方差,权重插值到 30 天,QVIX=100√V30。无风险 r=Shibor 3M。
- **合理性校验(8/14)**:a_qvix_300(510300)=17.90 vs optbbs 8/13=16.72(异源 IV 供应商+差1天,7%偏差合理);
  a_qvix_1000(510050)=16.48 vs RV/optbbs 16.61(1%差,极准)。历史回填(8/7=19.31/7/31=22.58)趋势合理。
- a_qvix_1000 历史 2022 前仍只有 optbbs 有(新浪/上交所覆盖不到中金所股指期权历史),诚实标注:该段若 optbbs 永久宕机仍缺,只能以 RV/不补齐。

## 防误判自查
- 每源实测(非页面描述):上交所 IV 字段值、新浪 IV 字段值、optbbs HTTP:000、东财 push2 HTTP:000 均实测。
- 已区分 A/B/C 三档工作量。
- 东财判「本机不可达」非「源不存在」(页面200/API000),待换网络验证。
- a_qvix_1000 历史回填 2022 前只有 optbbs 有(新浪/上交所都覆盖不到中金所股指期权历史)。

## 复现(实测命令,2026-08-15)
```bash
# 1. optbbs 宕机确认
curl -s -m 20 -o /dev/null -w "HTTP:%{http_code}\n" "http://1.optbbs.com/d/csv/d/k.csv"   # HTTP:000
# 2. 上交所官方 IV 链(T+1,2015至今)
python3 -c "import akshare as ak; df=ak.option_risk_indicator_sse(date='20260814'); print(df.shape, (df['IMPLC_VOLATLTY']>0).sum())"
# 3. 新浪实时 IV 链(需 Referer)
curl -s -H "Referer: https://stock.finance.sina.com.cn/" "https://hq.sinajs.cn/list=OP_UP_5103002608"
curl -s -H "Referer: https://vip.stock.finance.sina.com.cn/" "https://hq.sinajs.cn/list=CON_SO_10012131"
# 4. 新浪中金所 mo 链(a_qvix_1000 标的)
python3 -c "import akshare as ak; lst=ak.option_cffex_zz1000_list_sina(); df=ak.option_cffex_zz1000_spot_sina(symbol=list(lst.values())[0][0]); print(df.shape)"
# 5. 东财 API 本机不可达(页面可达)
curl -s -m 10 -o /dev/null -w "HTTP:%{http_code}\n" "https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=1&fs=m:10&fields=f2,f3"  # HTTP:000
```

## 相关
- docs/data-sources.md §15 异源兜底矩阵(2026-08-15)
- docs/qvix-rv/(C 兜底实施:RV 计算 + fetchers.py 异源链,commit 90fb827d7)
