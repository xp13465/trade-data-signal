"""免费异源自动切换多重兜底(2026-08-15 实施,调研见 docs/data-sources.md §15 + docs/qvix-data-sources.md)。

用户原则:任何数据源必须有『异源』兜底(不同 host/协议/供应商)。主源失败自动切备用源,
备用源与主源不同 host 供应商(非同一源换接口=伪多源)。切源后落 source 标记溯源。

本模块集中所有『异源兜底抓取器』,按数据类别组织:
  - fetch_treasury_us10y     us10y:东财 bond_zh_us_rate 主源宕机 -> 美国财政部官方 CSV
  - fetch_hkex_south_net     hk_south:东财 stock_hsgt_hist_em 宕机 -> HKEX 官方 JS 反算南向净买额
  - fetch_em_cn10y           cn10y:中债 bond_china_yield 宕机 -> 东财 bond_zh_us_rate(datacenter)
  - fetch_em_index_turnover  a_turnover_rate:腾讯 index_turnover 宕机 -> 东财 push2delay f168
  - fetch_em_index_snapshot  美股/全球指数:新浪 index_*_sina 宕机 -> 东财 push2delay
  - fetch_em_gold_aum        gold(沪金AU0):新浪 futures_main_sina 宕机 -> 东财 futsseapi aum
  - sse_qvix_series          qvix:optbbs 宕机 -> 上交所官方 IV 方差互换自算(真异源,T+1权威历史回填)

所有函数入参统一、返回 [(date_YYYYMMDD, value), ...] 或 None(源不可用)。
source 标记常量:S_source = "treasury"/"hkex"/"em"/... 由调用方(collect_series/collect_tencent)
透传给 daily_metric.source,便于溯源与前端降级透明化。
"""
import csv
import datetime as _dt
import io
import json
import re

import requests

from .base import UA, em_get


# ================ us10y 兜底:美国财政部官方 CSV ================
# 主源:东财 bond_zh_us_rate(akshare)。宕机时用美国财政部官方报价 CSV。
# host: home.treasury.gov(与东财 eastmoney.com 完全异源)。
# 字段:010 Yr 列 = 10 年期国债收益率(%)。8/14 实测与东财逐位一致 4.68。
TREASURY_CSV_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
    "daily-treasury-rates.csv/{year}/all"
    "?type=daily_treasury_yield_curve&field_tdr_date_value={year}&page&_format=csv"
)


def fetch_treasury_us10y(years=(_dt.date.today().year,)):
    """美国财政部 10Y 国债收益率,返回 [(date_YYYYMMDD, 10y_%), ...]。
    按年拉 CSV(每年一个 URL),取 '10 Yr' 列。日期 MM/DD/YYYY -> YYYYMMDD。
    """
    rows = []
    for year in years:
        try:
            r = requests.get(
                TREASURY_CSV_URL.format(year=year),
                headers={"User-Agent": UA},
                timeout=20,
            )
            r.encoding = "utf-8"
            if r.status_code != 200:
                continue
            reader = csv.DictReader(io.StringIO(r.text))
            for row in reader:
                date_raw = (row.get("Date") or "").strip()
                val_raw = (row.get("10 Yr") or "").strip()
                if "/" not in date_raw or not val_raw:
                    continue
                try:
                    mm, dd, yyyy = date_raw.split("/")
                    d = f"{yyyy}{int(mm):02d}{int(dd):02d}"
                    v = float(val_raw)
                    if v != v:  # NaN(未来日无值)
                        continue
                    rows.append((d, v))
                except (ValueError, TypeError):
                    continue
        except Exception:  # noqa: BLE001
            continue
    if not rows:
        return None
    rows.sort(key=lambda x: x[0])
    return rows


# ================ hk_south 兜底:HKEX 官方 JS 反算南向净买额 ================
# 主源:东财 stock_hsgt_hist_em(akshare,南向资金当日成交净买额)。
# 宕机时用港交所官方每日统计 JS(data_tab_daily_{date}e.js)。
# host: hkex.com.hk(与 eastmoney.com 异源)。
# 反算:南向记录(SSE Southbound + SZSE Southbound)的 (Buy Turnover - Sell Turnover) 合计。
# schema 南向列=['Total Turnover','Buy Turnover','Sell Turnover',...],
# tr[1]=Buy、tr[2]=Sell(百万 RMB)。净买额百万->亿:/100。8/14 实测:
#   SSE 买 37243.07 - 卖 36956.11 = +2.87亿;SZSE 买 20663.38 - 卖 22266.35 = -16.03亿
#   合计 = -13.16亿,与东财 stock_hsgt_hist_em 南向净买额逐位一致。
HKEX_DAILY_STAT_URL = "https://www.hkex.com.hk/eng/csm/DailyStat/data_tab_daily_{date}e.js"
HKEX_DAILY_STAT_REFERER = "https://www.hkex.com.hk/Mutual-Market/Stock-Connect/Statistics/Historical-Daily"


def fetch_hkex_south_net(days=40):
    """反算南向净买额(港股通净买入,亿元),返回 [(date_YYYYMMDD, 亿), ...]。
    保留窗口约 7 个月(更早 404 跳过)。days 默认覆盖最近 ~2 个月交易日足够增量更新。
    """
    rows = []
    today = _dt.date.today()
    for i in range(days * 2):  # 日历日上溯,覆盖交易日
        d = today - _dt.timedelta(days=i)
        date_str = d.strftime("%Y%m%d")
        url = HKEX_DAILY_STAT_URL.format(date=date_str)
        try:
            r = requests.get(
                url,
                headers={"User-Agent": UA, "Referer": HKEX_DAILY_STAT_REFERER},
                timeout=15,
            )
            if r.status_code != 200:
                continue  # 周末/假日/早期 404 跳过
            m = re.search(r"tabData\s*=\s*(\[.*\])\s*;?\s*$", r.text, re.DOTALL)
            if not m:
                continue
            arr = json.loads(m.group(1))
            net = 0.0
            found = 0
            for rec in arr:
                if "Southbound" not in rec.get("market", ""):
                    continue
                content = rec.get("content") or []
                if not content:
                    continue
                trs = (content[0].get("table") or {}).get("tr") or []
                if len(trs) < 3:
                    continue
                buy = _num(trs[1].get("td")[0][0])
                sell = _num(trs[2].get("td")[0][0])
                if buy is not None and sell is not None:
                    net += (buy - sell) / 100.0  # 百万 -> 亿
                    found += 1
            if found == 2:  # 沪 + 深 南向都找到
                rows.append((date_str, round(net, 2)))
        except Exception:  # noqa: BLE001
            continue  # 单日失败不跳出
    if not rows:
        return None
    rows.sort(key=lambda x: x[0])
    return rows


def _num(x):
    """字符串(可能带千分位逗号)转 float;失败返回 None。"""
    try:
        if isinstance(x, list):
            x = x[0] if x else None
        return float(str(x).replace(",", "").strip())
    except (ValueError, TypeError, IndexError):
        return None


# ================ cn10y 兜底:东财 datacenter 中国10Y收益率 ================
# 主源:中债 bond_china_yield(akshare,chinabond 源)。宕机时用东财 datacenter 中美国债收益率
# 报表(RPTA_WEB_TREASURYYIELD)的「中国国债收益率10年」字段(EMM00166466)。
# host: datacenter.eastmoney.com(与 chinabond.com.cn 中债 异源)。8/14 实测 1.6964 与中债完全一致。
EM_TREASURY_REPORT = "RPTA_WEB_TREASURYYIELD"
EM_CN10Y_FIELD = "EMM00166466"  # 中国国债收益率10年


def fetch_em_cn10y(years_limit=6):
    """东财 datacenter 中国 10Y 国债收益率(%),返回 [(date_YYYYMMDD, %), ...]。
    走 RPTA_WEB_TREASURYYIELD 全量历史(自 2002 起,按月过滤近 years_limit 年足够增量)。"""
    rows = []
    try:
        r = em_get(
            "https://datacenter.eastmoney.com/api/data/get",
            params={
                "type": EM_TREASURY_REPORT,
                "sty": "ALL",
                "st": "SOLAR_DATE",
                "sr": "-1",
                "token": "894050c76af8597a853f5b408b759f5d",
                "p": "1",
                "ps": "5000",
                "pageNo": "1",
                "pageNum": "1",
            },
            timeout=25,
        )
        data = r.json().get("result") or {}
        for item in data.get("data") or []:
            try:
                d = str(item.get("SOLAR_DATE", ""))[:10].replace("-", "")
                if d > f"{_dt.date.today().year + 1}0000":  # 数据完整性护栏(忽略异常日期)
                    continue
                v = item.get(EM_CN10Y_FIELD)
                if v is None or v == "":
                    continue
                v = float(v)
                if v != v or v <= 0:  # NaN / 占位 0 跳过
                    continue
                rows.append((d, v))
            except (ValueError, TypeError, KeyError):
                continue
    except Exception:  # noqa: BLE001
        pass
    if not rows:
        return None
    rows.sort(key=lambda x: x[0])
    return rows[-years_limit * 365:]  # 只留近 N 年,防内存膨胀


# ================ a_turnover_rate 兜底:东财 push2delay f168 ================
# 主源:腾讯 qt.gtimg.cn 指数换手率(index_turnover)。宕机时用东财 push2delay secid f168。
# host: push2delay.eastmoney.com。f168=换手率(仅 pb 小数位,8/14=103 -> 1.03%)。
def fetch_em_index_turnover(secid="1.000001"):
    """东财指数换手率(f168*0.01%),返回当日最近交易日的 (date_YYYYMMDD, %)。"""
    try:
        r = em_get(
            "https://push2delay.eastmoney.com/api/qt/stock/get",
            params={
                "secid": secid,
                "fields": "f57,f58,f168,f124",
            },
            timeout=15,
        )
        data = (r.json().get("data") or {}) or {}
        f168 = data.get("f168")
        # f124=日期(YYYYMMDD),交易日内为当日
        date_str = str(data.get("f124") or "")
        if f168 is None:
            return None
        val = float(f168) * 0.01  # f168 单位 0.01%
        if val != val or val == 0:
            return None
        if not date_str or len(date_str) != 8:
            # 兜底:用最近交易日(last_trading_day 返 YYYYMMDD str)
            from ..calendar import last_trading_day
            date_str = last_trading_day()
        return [(date_str, val)]
    except Exception:  # noqa: BLE001
        return None


# ================ 美股/全球指数 兜底:东财 push2delay ================
# 主源:新浪 index_us_stock_sina / index_global_hist_sina。宕机时用东财 push2delay。
# host: push2delay.eastmoney.com。f43=最新价(f43 需按 secid 缩放:美股指数/100,其他按1)。
# 指数映射见 EM_INDEX_MAP。
EM_INDEX_MAP = {
    # id: (secid, scale)  (secid 经 m:100 全球指数表实测校准;f43=0.01单位除100)
    "us_dji": ("100.DJIA", 100.0),    # 道琼斯
    "us_ixic": ("100.NDX", 100.0),    # 纳斯达克综合(f58=纳斯达克,26729.16)
    "us_spx": ("100.SPX", 100.0),     # 标普500
    "us_ndx": ("100.NDX100", 100.0),  # 纳斯达克100(30046.14)
    "nikkei225": ("100.N225", 100.0),  # 日经225
    "kospi": ("100.KS11", 100.0),      # 韩国KOSPI
    "ftse100": ("100.FTSE", 100.0),    # 富时100
    "dax": ("100.GDAXI", 100.0),       # 德国DAX
    "cac40": ("100.FCHI", 100.0),      # 法国CAC40
}


def fetch_em_index_snapshot(secid, scale=100.0, date_str=None):
    """东财 push2delay 指数最新价快照,返回 [(date_YYYYMMDD, close), ...](1 行,当日)。
    scale:东财指数 f43 单位为 0.01(如 NDX 返回 2672916=26729.16),除 scale=100。
    仅返回当日/最近交易日 1 行快照(东财 push2delay 无全历史 kline 纯做增量,见 data-sources §15.4)。
    """
    try:
        r = em_get(
            "https://push2delay.eastmoney.com/api/qt/stock/get",
            params={"secid": secid, "fields": "f43,f57,f58,f124,f105"},
            timeout=15,
        )
        data = (r.json().get("data") or {}) or {}
        f43 = data.get("f43")
        if f43 is not None:
            val = float(f43) / scale
            if val != val or val == 0:
                return None
            ds = date_str
            if not ds:
                f124 = str(data.get("f124") or "")
                ds = f124 if len(f124) == 8 else _default_date()
            return [(ds, val)]
    except Exception:  # noqa: BLE001
        pass
    return None


def _default_date():
    from ..calendar import last_trading_day
    return last_trading_day()  # 已返 YYYYMMDD str


# ================ gold(沪金AU0) 兜底:东财 futsseapi aum ================
# 主源:新浪 futures_main_sina 沪金 AU0。宕机时用东财 futsseapi 沪金主连(aum)。
# host: futsseapi.eastmoney.com。差 0.06 元/克量级(口径同为沪金人民币主连)。
EM_FUTSSEAPI_URL = (
    "https://futsseapi.eastmoney.com/list/SHFE,DCE,INE,CZCE,GFEX"
    "?orderBy=dm&sort=asc&pageSize=1200&pageIndex=0"
    "&token=58b2fa8f54638b60b87d69b31969089c&field=dm,sc,name,p,zdf&blockName=callback"
)
EM_AU_DM = "aum"  # 沪金主连(数据源返回 dm 名)


def fetch_em_gold_aum(date_str=None):
    """东财 futsseapi 沪金主连(aum)收盘价(元/克),返回 [(date_YYYYMMDD, price), ...](1 行当日)。"""
    try:
        r = em_get(EM_FUTSSEAPI_URL, timeout=20)
        data = r.json()
        for it in data.get("list") or []:
            if it.get("dm") == EM_AU_DM:
                p = float(it.get("p"))
                if p != p or p <= 0:
                    return None
                return [((date_str or _default_date()), p)]
    except Exception:  # noqa: BLE001
        pass
    return None


# ================ qvix 兜底:上交所官方 IV 方差互换自算 ================
# 主源:optbbs(1.optbbs.com)直接波指 daily k.csv。宕机时真异源兜底:
#   档1 上交所官方 IV(option_risk_indicator_sse,T+1,历史2015至今可回填)——本模块
#   档2 新浪实时 IV(option_sse_greeks_sina,盘中)——下一步(时间复杂度里已留函数钩子)
#   网底 RV(已实现波动率,口径差异)——在 fetchers._qvix_rv_series(从 qvix-rv-backfill 合入)
# 本函数用上交所官方 IV 做方差互换法自算 QVIX(参考 vix 算法 + GitHub nkuguanrui/ivx)。
# 合理性校验(8/14):a_qvix_300(510300)=17.90 vs optbbs 8/13=16.72; a_qvix_1000(510050)=16.48
#                   vs RV 16.61(1% 差,极准)。
SSE_UND = {
    "index_option_300etf_qvix": "510300",
    "index_option_50etf_qvix": "510050",
}


def _expiry_sse_date(exp_yy, asof):
    """由上交所合约后缀(yymm,如 2608)推该到期月第 4 个周三(SSE 期权交割日)。"""
    yy = int("20" + exp_yy[:2])
    mm = int(exp_yy[2:])
    day = _dt.date(yy, mm, 1)
    while day.weekday() != 2:  # 周三=2
        day += _dt.timedelta(days=1)
    return day + _dt.timedelta(days=21)  # 第 4 个周三


def _erf(x):
    """Abramowitz-Stegun 误差函数近似。"""
    import math
    sign = 1 if x >= 0 else -1
    ax = abs(x)
    t = 1.0 / (1.0 + 0.3275911 * ax)
    a = 0.254829592 * t - 0.284496736 * t * t + 1.421413741 * t ** 3 - (
        1.453152027 * t ** 4) + 1.061405429 * t ** 5
    return sign * (1.0 - a * math.exp(-ax * ax))


def _bs_price_sse(S, K, T, r, iv, is_call):
    import math
    sqrtT = math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * iv * iv) * T) / (iv * sqrtT)
    d2 = d1 - iv * sqrtT
    ncdf = lambda z: 0.5 * (1.0 + _erf(z / math.sqrt(2.0)))
    if is_call:
        return S * ncdf(d1) - K * math.exp(-r * T) * ncdf(d2)
    return K * math.exp(-r * T) * ncdf(-d2) - S * ncdf(-d1)


# Shibor 无风险利率(仅用于 QVIX 方差互换的折现),用近月 3M(取最近一档即可,量级影响极小)。
def _shibor_3m():
    """最近交易日 Shibor 3M 利率(小数,如 0.0143)。拉取失败回退 1.5% 常量。"""
    try:
        import akshare as ak
        from ..calendar import last_trading_day
        df = ak.rate_interbank(market="上海银行同业拆借市场", symbol="Shibor人民币", indicator="3月")
        df = df.sort_values("报告日")
        v = float(df["利率"].iloc[-1])
        return v / 100.0 if v > 1 else v  # 兼容量级:1.43->0.0143 或 0.0143
    except Exception:  # noqa: BLE001
        return 0.0150


def sse_qvix_series(date_str, und_code, r=None):
    """上交所官方 IV 方差互换法自算 QVIX,返回 ([(date_YYYYMMDD, qvix)], 口径msg) 或 (None, errmsg)。

    - date_str: 交易日 YYYYMMDD(IV T+1 发布,取该日收盘链)
    - und_code: 510300(a_qvix_300) / 510050(a_qvix_1000)
    - r: 无风险利率(Shibor 3M),None 自动拉
    方差互换法(CBOE VIX 思想):近/次两到期月的期权链 IV -> Black-Scholes 反推期权价 Q(K),
    每 K 选 OTM,sum(ΔK/K²·e^{rT}Q),算远期 F/K0,减凸性项,得两期年化方差,插值到 30 天。
    """
    import math
    import akshare as ak
    from .etf_national_team import fetch_etf_ohlc
    if r is None:
        r = _shibor_3m()
    try:
        df = ak.option_risk_indicator_sse(date=date_str)
    except Exception as e:  # noqa: BLE001
        return None, f"sse IV error: {e}"
    df = df[df["CONTRACT_ID"].str.startswith(und_code)] if df is not None and len(df) else df
    if df is None or len(df) == 0:
        return None, "sse IV empty"
    df = df[df["IMPLC_VOLATLTY"] > 0]
    if len(df) < 6:
        return None, "sse IV 有效合约不足"
    asof = _dt.date(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:8]))
    # 标的价:用 ETF 日线最近收盘
    recs = fetch_etf_ohlc(und_code)
    recs = [x for x in recs if x["date"] <= date_str]
    if not recs:
        return None, "sse QVIX 标的价缺失"
    S = float(recs[-1]["close"])
    # 近/次两到期月
    terms = _sse_terms(asof)
    vterms = []
    for exp_date in terms:
        F, k0, Var = _sse_variance_term(df, asof, exp_date, S, r)
        if Var is not None:
            vterms.append((exp_date, Var, (exp_date - asof).days / 365.0))
    if not vterms:
        return None, "sse QVIX 无有效到期月"
    T30 = 30.0 / 365.0
    if len(vterms) >= 2:
        e1, V1, T1 = vterms[0]
        e2, V2, T2 = vterms[1]
        if T2 - T1 > 0:
            w1 = (T2 - T30) / (T2 - T1)
            w2 = (T30 - T1) / (T2 - T1)
            V30 = V1 if (w1 < 0 or w2 < 0) else (w1 * V1 + w2 * V2)
        else:
            V30 = vterms[0][1]
    else:
        V30 = vterms[0][1]
    if V30 <= 0:
        return None, "sse QVIX V30<=0"
    qv = 100.0 * math.sqrt(V30)
    msg = (
        f"sse官方IV自算QVIX S={S:.3f} r={r * 100:.2f}% "
        f"近T1={vterms[0][0] if vterms else '?'} 次T2={vterms[1][0] if len(vterms) > 1 else '?'} "
        f"V30={V30:.6f}"
    )
    return [(date_str, round(qv, 2))], msg


def _sse_terms(asof):
    """返回 >= asof 的近/次两个 SSE 期权到期日。"""
    terms = []
    y, m = asof.year, asof.month
    for _ in range(6):
        e = _expiry_sse_date(f"{y % 100:02d}{m:02d}", asof)
        if e >= asof:
            terms.append(e)
            if len(terms) == 2:
                return terms
        m += 1
        if m > 12:
            m = 1
            y += 1
    return terms


def _sse_variance_term(df, asof, exp_date, S, r):
    """单到期月方差互换项:(F, K0, 年化方差Var)。"""
    import math
    T = (exp_date - asof).days / 365.0
    if T <= 0:
        return None, None, None
    by_k = {}
    for _, row in df.iterrows():
        cid = row["CONTRACT_ID"]
        if _expiry_sse_date(cid[7:11], asof) != exp_date:
            continue
        iv = float(row["IMPLC_VOLATLTY"])
        if iv <= 0:
            continue
        strike = int(cid[cid.index("M") + 1:]) / 1000.0
        is_call = cid[6] == "C"
        price = _bs_price_sse(S, strike, T, r, iv, is_call)
        d = by_k.setdefault(strike, {})
        d["C" if is_call else "P"] = price
    if not by_k:
        return None, None, None
    ks = sorted(by_k)
    # 远期 F:最小 put-call 价差的 strike 组合
    F = None
    bestdiff = float("inf")
    for st in ks:
        c = by_k[st].get("C")
        p = by_k[st].get("P")
        if c is not None and p is not None:
            diff = abs(c - p)
            if diff < bestdiff:
                bestdiff = diff
                F = st + math.exp(r * T) * (c - p)
    if F is None or F <= 0:
        return None, None, None
    # K0:< F 的最大行权
    below = [st for st in ks if st < F]
    k0 = max(below) if below else min(ks)
    # ΔK(端点用单边,内部用相邻平均)
    dK = {}
    for i, st in enumerate(ks):
        if i == 0:
            dK[st] = ks[1] - ks[0]
        elif i == len(ks) - 1:
            dK[st] = st - ks[i - 1]
        else:
            dK[st] = (ks[i + 1] - ks[i - 1]) / 2.0
    vsum = 0.0
    for st in ks:
        if st > k0:
            q = by_k[st].get("C")
        elif st == k0:
            q = ((by_k[st].get("C") or 0) + (by_k[st].get("P") or 0)) / 2.0
        else:
            q = by_k[st].get("P")
        if q is None or q <= 0:
            continue
        vsum += (dK[st] / (st * st)) * math.exp(r * T) * q
    Var = (2.0 / T) * vsum - (1.0 / T) * ((F / k0 - 1.0) ** 2)
    return F, k0, Var
