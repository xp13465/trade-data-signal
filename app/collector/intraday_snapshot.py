"""盘中实时快照采集（方案 A 后端）。

解决收盘后 pipeline 拿不到当日指数（上证 0%）的问题：盘中直采腾讯实时行情 +
同花顺行业实时涨跌幅，存 DB + dump 静态 JSON，供前端"盘中实时小结"展示。

- 9 指数实时：腾讯 qt.gtimg.cn（主），新浪 hq.sinajs.cn（逐个降级备）。
- 31 申万一级行业实时涨跌幅：复用同花顺 stock_board_industry_summary_ths（90 子行业），
  通过 THS_TO_SW 聚合（涨跌幅按成交额加权、净流入求和、领涨股取涨幅最高子行业）。
- is_market_closed：时间+数据双重判断盘中区间（9:30-11:30/13:00-15:00 交易日），
  传 at=collected_at 时按数据时刻判断，不传默认 now（向后兼容）。
- **指数反哺**：采集完 9 指数后，把当日 OHLC 写入 index_daily 表（UPSERT），
  触发重算 per-index 情绪分 + 恐贪指数 + dump 静态 JSON，
  使指数卡片/恐贪/per-index 情绪分到当日（解决 T+1 延迟致停在 T-2 的问题）。
  非交易日不反哺；快照 datetime 非当日不写（避免旧快照污染）。
"""
import json
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

from ..db import get_conn
from .base import UA, throttle, log_collect
from .industry_extras import THS_TO_SW

# 9 核心 A 股指数 + 3 港股宽基 + 4 signals 触发指数（腾讯 qt 支持混合请求）
# 港股用 r_hkXXX 前缀（腾讯港股实时源），盘中（9:30-16:00）返实时价，16:00 收盘后返收盘价
# 2026-07-27 加 4 个 signals 触发指数（cgb_idx/hk_hsmbi/hk_hsmogi + 预防性 cgb_10y_etf），
# 让盘中 signals.compute() 能算出 buy_special/sell（此前 5 触发指数都不在反哺列表，
# 盘中读不到当日 close -> buy_special/sell/band_hold 当日 NaN -> False，盘后 update_all 才触发）。
# cgb_10y_future（T0 国债期货主连合约）腾讯/新浪实时源都不支持，盘中缺 band_hold 1 条，
# 盘后 update_all 采 T+1 完整 daily 补。
INDEX_CODES = [
    "sh000001",  # 上证指数
    "sz399001",  # 深证成指
    "sh000300",  # 沪深300
    "sh000016",  # 上证50
    "sh000905",  # 中证500
    "sh000852",  # 中证1000
    "sz399006",  # 创业板指
    "sh000688",  # 科创50
    "bj899050",  # 北证50
    "r_hkHSI",   # 恒生指数（港股）
    "r_hkHSTECH",  # 恒生科技指数（港股）
    "r_hkHSCEI",   # 恒生国企（港股）
    "sh000012",    # 上证国债指数 -> cgb_idx（buy_special/sell 触发）
    "sh511260",    # 十年国债ETF -> cgb_10y_etf（预防性加，band_hold 触发）
    "r_hkHSMBI",   # 恒生内地银行 -> hk_hsmbi（buy_special 触发）
    "r_hkHSMOGI",  # 恒生内地油气 -> hk_hsmogi（buy_special 触发）
]

# A 股 codes（用于新浪兜底；新浪不支持 r_hkXXX 格式，港股只走腾讯）
_A_STOCK_CODES = [c for c in INDEX_CODES if not c.startswith("r_hk")]

_TENCENT_URL = "http://qt.gtimg.cn/q=" + ",".join(INDEX_CODES)
_SINA_URL = "http://hq.sinajs.cn/list=" + ",".join(_A_STOCK_CODES)
_SINA_HEADERS = {"User-Agent": UA, "Referer": "https://finance.sina.com.cn"}

# static-site 静态 JSON 输出路径（与 export.py 的 DATA_DIR 同源）
STATIC_DATA_DIR = Path(__file__).absolute().parent.parent.parent / "static-site" / "data"

# 快照 code -> index_daily.index_id 映射（9 核心 A 股 + 3 港股宽基 + 4 signals 触发 + 1 新浪港股）
# 注意：_parse_tencent 提取 key 时 strip "v_" 前缀 + split("_")[-1]，
#   A 股 v_sh000001 -> "sh000001"；港股 v_r_hkHSI -> "hkHSI"（r_ 被吃掉）。
# hkCSHKDIV 由 _fetch_hk_cshkdiv_sina() 单独采（腾讯无代码，新浪 A 股 list 不支持 rt_ 前缀）。
# 5 触发指数中 4 个盘中可采（cgb_idx/cgb_10y_etf/hk_hsmbi/hk_hsmogi + hk_cshkdiv），
# cgb_10y_future（T0 主连）实时源不支持，盘中缺 band_hold 1 条，盘后 update_all 补。
_SNAPSHOT_TO_INDEX_ID = {
    "sh000001": "sh",      # 上证指数
    "sz399001": "sz",      # 深证成指
    "sh000300": "hs300",   # 沪深300
    "sh000016": "sz50",    # 上证50
    "sh000905": "csi500",  # 中证500
    "sh000852": "csi1000",  # 中证1000
    "sz399006": "cyb",     # 创业板指
    "sh000688": "kc50",    # 科创50
    "bj899050": "bj50",    # 北证50
    "hkHSI": "hsi",        # 恒生指数（港股）
    "hkHSTECH": "hstech",  # 恒生科技（港股）
    "hkHSCEI": "hscei",    # 恒生国企（港股）
    "sh000012": "cgb_idx",        # 上证国债指数（buy_special/sell 触发）
    "sh511260": "cgb_10y_etf",    # 十年国债ETF（预防性加，band_hold 触发）
    "hkHSMBI": "hk_hsmbi",        # 恒生内地银行（buy_special 触发）
    "hkHSMOGI": "hk_hsmogi",      # 恒生内地油气（buy_special 触发）
    "hkCSHKDIV": "hk_cshkdiv",    # 中证香港红利（buy_special 触发，新浪 rt_ 单独采）
}

# ============ T+1 治理：商品/外汇/美债实时源（2026-07-29 加）============
# 背景：gold/oil/wti_oil/comex_silver/brent/usdcnh 原走 futures_main_sina/
# futures_foreign_hist/currency_boc_sina 日线函数，盘后才出 T+1 数据，盘中无当日值。
# 新浪 hq.sinajs.cn 实时源盘中直采，覆盖当日 daily_metric（source='intraday'）。
# 收盘 pipeline（T+1 历史序列）次日覆盖为最终收盘值（UPSERT 幂等）。
#
# 源验证（2026-07-29 实测）：
#   - nf_AU0（沪金主连，nf_前缀国内期货）✓ 返回今日实时
#   - nf_SC0（INE原油主连，大写SC！小写sc0返回空）✓ 返回今日实时
#   - hf_CL/hf_SI/hf_OIL（外盘期货）✓ 返回今日实时
#   - hf_XAU（伦敦金现货）✓ 返回今日实时（辅助参考，不强推前端）
#   - fx_susdcny（离岸人民币实时汇率）✓ 返回今日实时
#   - hf_TNX（10年美债收益率）✗ 新浪源全空 -> us10y 保持 bond_zh_us_rate T+1
# 注意：AU0（无 nf_ 前缀）返回 2024 旧数据已废弃，nf_AU0 才是实时源。
#       sc0（小写）返回空，nf_SC0（大写）才有效。新浪代码大小写敏感。
COMMODITY_CODES = [
    "nf_AU0",   # 沪金主连 -> gold（保持 AU0 口径一致，人民币计价沪金期货）
    "nf_SC0",   # 上海原油(INE)主连 -> oil（大写SC！小写sc0返回空）
    "hf_CL",    # WTI原油 -> wti_oil
    "hf_SI",    # COMEX白银 -> comex_silver
    "hf_OIL",   # 布伦特原油 -> brent
    "hf_XAU",   # 伦敦金现货 -> hf_xau（辅助参考，美元计价，与AU0人民币口径不同不强推前端）
]
# 实时源 code -> daily_metric.metric_id 映射
COMMODITY_TO_METRIC = {
    "nf_AU0": "gold",
    "nf_SC0": "oil",
    "hf_CL": "wti_oil",
    "hf_SI": "comex_silver",
    "hf_OIL": "brent",
    "hf_XAU": "hf_xau",  # 辅助参考指标（indicators.yaml 不注册，intraday 直接写）
}
# 离岸人民币实时汇率 -> usdcnh（覆盖 currency_boc_sina T+1 当日值）
FX_CODE = "fx_susdcny"
# sh511260 十年国债ETF -> cn10y_etf（cn10y 收益率本身保持 T+1，ETF实时价作盘中参考）
CN10Y_ETF_INDEX_CODE = "sh511260"
CN10Y_ETF_METRIC_ID = "cn10y_etf"


def _now_iso() -> str:
    return datetime.now().isoformat()


def _parse_tencent(text: str) -> list[dict]:
    """解析腾讯 qt 返回：每条 v_xxx="字段1~字段2~..."，按 ~ split。

    A 股 88 字段 / 港股 78 字段，关键字段位置一致：
    [1]=name [3]=price [4]=pre_close [5]=open [6]=amount(港股)
         [30]=datetime [31]=change [32]=pct_change [33]=high [34]=low

    datetime 差异：A 股 "YYYYMMDDHHMMSS"（无分隔符），
                  港股 "YYYY/MM/DD HH:MM:SS"（有分隔符，需规范化为 YYYYMMDDHHMMSS）。
    """
    out = []
    for line in text.strip().split(";"):
        line = line.strip()
        if not line or "=" not in line or '"' not in line:
            continue
        try:
            key = line.split("=", 1)[0].split("_")[-1]  # sh000001 / hkHSI ...
            vals = line.split('"', 2)[1].split("~")
            if len(vals) < 35:
                continue
        except Exception:  # noqa: BLE001
            continue

        def f(i):
            try:
                return float(vals[i])
            except (IndexError, ValueError):
                return None

        name = vals[1].strip()
        price = f(3)
        pre_close = f(4)
        change = f(31)
        pct = f(32)
        # 腾讯 pct_change 有时丢符号（price<pre_close 但 pct>0），用 change 自算兜底
        if price and pre_close and pre_close != 0:
            if pct is None or (change is not None and abs(pct) < 1e-6 and abs(change) > 1e-6):
                pct = (price - pre_close) / pre_close * 100
            # 符号兜底：change 与 pct 符号不一致以 change 为准
            if change is not None and abs(pct) > 1e-6 and (change > 0) != (pct > 0):
                pct = -abs(pct) if change < 0 else abs(pct)
        # 规范化 datetime：A 股 "YYYYMMDDHHMMSS"，港股 "YYYY/MM/DD HH:MM:SS"
        dtstr_raw = vals[30].strip() if len(vals) > 30 else ""
        if "/" in dtstr_raw:
            # 港股格式 YYYY/MM/DD HH:MM:SS -> YYYYMMDDHHMMSS
            dtstr = dtstr_raw.replace("/", "").replace(" ", "").replace(":", "")
        else:
            dtstr = dtstr_raw
        # 港股 field[6]=成交额(万港元)；A 股 field[6] 非 amount（是成交笔数等），不提取。
        # 收盘后腾讯返收盘价 + 当日完整成交额；盘中返实时累计额。
        amount = None
        if key.startswith("hk"):
            amt_wan = f(6)
            amount = amt_wan * 10000 if amt_wan is not None else None
        out.append({
            "code": key,
            "name": name,
            "price": price,
            "pre_close": pre_close,
            "change": change,
            "pct_change": pct,
            "open": f(5),
            "high": f(33),
            "low": f(34),
            "datetime": dtstr,
            "amount": amount,
        })
    return out


def _parse_sina(text: str) -> list[dict]:
    """解析新浪 hq_str 返回（GBK）。指数行字段（实测 2026-07）：
    [0]=名称 [1]=今开(open) [2]=昨收(pre_close) [3]=现价(price) [4]=最高(high)
    [5]=最低(low) [30]=日期(YYYY-MM-DD) [31]=时间(HH:MM:SS)
    注意：新浪指数行 [1] 是今开不是昨收，[2] 才是昨收（与个股行相反，曾踩坑）。
    """
    out = []
    for line in text.strip().split("\n"):
        line = line.strip().rstrip(";")
        if not line.startswith("var hq_str_") or "=" not in line:
            continue
        try:
            code = line.split("=", 1)[0].replace("var hq_str_", "")
            body = line.split('"', 2)[1]
            fields = body.split(",")
            if len(fields) < 6:
                continue
        except Exception:  # noqa: BLE001
            continue

        def f(i):
            try:
                return float(fields[i])
            except (IndexError, ValueError):
                return None

        name = fields[0].strip()
        pre_close = f(2)  # [2]=昨收
        price = f(3)      # [3]=现价
        change = (price - pre_close) if (price and pre_close) else None
        pct = (change / pre_close * 100) if (change is not None and pre_close) else None
        date = fields[30].strip() if len(fields) > 30 else ""
        tm = fields[31].strip() if len(fields) > 31 else ""
        dtstr = ""
        if date:
            dtstr = date.replace("-", "") + (tm.replace(":", "") if tm else "")
        out.append({
            "code": code,
            "name": name,
            "price": price,
            "pre_close": pre_close,
            "change": change,
            "pct_change": pct,
            "open": f(1),   # [1]=今开
            "high": f(4),
            "low": f(5),
            "datetime": dtstr,
        })
    return out


def _fetch_hk_cshkdiv_sina() -> dict | None:
    """新浪 rt_hkCSHKDIV 港股指数实时接口单独采 hk_cshkdiv。

    腾讯 qt 无 CSHKDIV 代码（实测 r_hkCSHKDIV 返 v_pv_none_match），新浪 A 股 list
    接口也不支持 rt_ 前缀，故港股指数 rt_ 系列走单独的 hq.sinajs.cn/list=rt_hkCSHKDIV
    接口。返回与 _parse_tencent 一致结构的 dict（code="hkCSHKDIV"，供 _SNAPSHOT_TO_INDEX_ID
    映射），失败/无价返 None。

    字段（实测 2026-07-27）:
      [0]=代码 [1]=名称 [2]=昨收 [3]=今开 [4]=最高 [5]=最低 [6]=现价
      [7]=涨跌额 [8]=涨跌幅 [17]=日期(YYYY/MM/DD) [18]=时间(HH:MM:SS)
    amount 留 None（rt_ 字段单位不确定，与 _sina_spot_hk_fallback 一致，盘后 update_all 覆盖补全）。
    """
    try:
        throttle()
        r = requests.get(
            "http://hq.sinajs.cn/list=rt_hkCSHKDIV",
            headers=_SINA_HEADERS, timeout=10)
        body = r.content.decode("gbk")
        if '"' not in body:
            return None
        body = body.split('"', 2)[1]
        fields = body.split(",")
        if len(fields) < 9:
            return None
    except Exception as e:  # noqa: BLE001
        print(f"  [intraday] 新浪 rt_hkCSHKDIV 请求失败: {type(e).__name__} {e}", flush=True)
        return None

    def f(i):
        try:
            return float(fields[i])
        except (IndexError, ValueError):
            return None

    price = f(6)
    if price is None:
        return None
    date = fields[17].strip() if len(fields) > 17 else ""
    tm = fields[18].strip() if len(fields) > 18 else ""
    dtstr = (date.replace("/", "") + tm.replace(":", "")) if date else ""
    return {
        "code": "hkCSHKDIV",
        "name": fields[1].strip(),
        "price": price,
        "pre_close": f(2),
        "change": f(7),
        "pct_change": f(8),
        "open": f(3),
        "high": f(4),
        "low": f(5),
        "datetime": dtstr,
        "amount": None,
    }


# 全球指数实时采集清单（AZ89 2026-07-31 P1+P2 全球指数时效优化）
# 新浪 b_ 前缀（全球指数）+ rt_ 前缀（港股指数），GBK 编码，单接口批量采
# akshare index_global_spot_em 走东财 push2.eastmoney.com 实测本机连接被拒
# （RemoteDisconnected，与 CLAUDE.md「东财2源被封弃用」一致），改用新浪 b_/rt_ 系列
# （rt_hkCSHKDIV 已在 _fetch_hk_cshkdiv_sina 验证可用，扩展到全部全球指数）。
# 收盘 pipeline 仍走 index_global_hist_sina 补完整 OHLC（实时源只覆盖当日 latest）。
_GLOBAL_SPOT_CODES = {
    # P1：全球5指数（AZ89 推荐，盘中实时；与 A 股同时区韩日价值最高）
    "nikkei225": ("b_NKY", "b"),      # 日经225
    "kospi": ("b_KOSPI", "b"),        # 首尔综合
    "ftse100": ("b_UKX", "b"),        # 英国富时100
    "dax": ("b_DAX", "b"),            # 德国DAX
    "cac40": ("b_CAC", "b"),          # 法国CAC40
    # P2：亚洲其他同时区（AZ89 可选）
    "asx200": ("b_AS51", "b"),        # 澳大利亚ASX200
    "sensex": ("b_SENSEX", "b"),      # 印度孟买SENSEX（NIFTY50 无 b_ 代码，SENSEX 同覆盖）
    # P2：港股板块8（AZ89 可选，细分行业；3 中证走 rt_，5 恒生/中华走 rt_）
    "hk_cesg10": ("rt_hkCESG10", "rt"),    # 中华博彩
    "hk_hsmogi": ("rt_hkHSMOGI", "rt"),    # 恒生内地油气
    "hk_hsmbi": ("rt_hkHSMBI", "rt"),      # 恒生内地银行
    "hk_hsmpi": ("rt_hkHSMPI", "rt"),      # 恒生内地房地产
    "hk_hscci": ("rt_hkHSCCI", "rt"),      # 红筹指数
    "hk_cshklre": ("rt_hkCSHKLRE", "rt"),  # 中证香港内地地产
    "hk_cshklc": ("rt_hkCSHKLC", "rt"),    # 中证香港内地消费
    "hk_cshkdiv": ("rt_hkCSHKDIV", "rt"),  # 中证香港红利
}


def _fetch_global_realtime_sina() -> dict:
    """新浪 b_/rt_ 前缀全球指数实时批量采集。

    覆盖 AZ89 P1（全球5: nikkei225/kospi/ftse100/dax/cac40）
    + P2（亚洲其他: asx200/sensex + 港股板块8: cesg10/hsmogi/hsmbi/hsmpi/hscci/cshklre/cshklc/cshkdiv）。

    数据源：新浪 hq.sinajs.cn/list=b_NKY,b_KOSPI,...,rt_hkCESG10,...
    - b_ 前缀：全球指数（日经/首尔/富时/DAX/CAC/ASX/SENSEX）
      字段（实测 2026-07-31）：[0]=名称 [1]=最新价 [2]=涨跌额 [3]=涨跌幅
        [4-5]=杂项日期 [6]=行情日期(YYYY-MM-DD) [7]=行情时间(HH:MM:SS)
        [9]=昨收 [10]=最高 [11]=最低 [12]=成交量
      注：b_NIFTY 短格式仅 6 字段（无 date/prev_close/OHLC），b_NIFTY50 无此代码，
      故印度用 b_SENSEX（完整字段）代表，NIFTY50 暂不采。
    - rt_ 前缀：港股指数（与 _fetch_hk_cshkdiv_sina 同源同格式）
      字段：[0]=代码 [1]=名称 [2]=昨收 [3]=今开 [4]=最高 [5]=最低
        [6]=现价 [7]=涨跌额 [8]=涨跌幅 [17]=日期 [18]=时间

    返回 dict：{index_id: {name, price, chg, chg_pct, pre_close, open, high, low,
    date, time, datetime}}。失败的 index 不出现（不报错不阻断快照核心）。
    """
    out = {}
    try:
        codes = [c for c, _ in _GLOBAL_SPOT_CODES.values()]
        url = "https://hq.sinajs.cn/list=" + ",".join(codes)
        r = requests.get(url, headers=_SINA_HEADERS, timeout=10)
        body = r.content.decode("gbk", errors="replace")
    except Exception as e:  # noqa: BLE001
        print(f"[intraday] 全球指数实时采集失败（不阻断）: {type(e).__name__} {e}", flush=True)
        return out

    def _f(i, default=None):
        try:
            v = fields[i].strip()
            return float(v) if v else default
        except (IndexError, ValueError):
            return default

    for idx_id, (sina_code, fmt) in _GLOBAL_SPOT_CODES.items():
        prefix = f'var hq_str_{sina_code}="'
        i = body.find(prefix)
        if i < 0:
            continue
        j = body.find('"', i + len(prefix))
        if j < 0:
            continue
        content = body[i + len(prefix):j]
        if not content:
            continue
        fields = content.split(",")
        if len(fields) < 4:
            continue
        try:
            if fmt == "b":
                name = fields[0].strip()
                price = _f(1)
                chg = _f(2)
                chg_pct = _f(3)
                if len(fields) >= 8:
                    date = fields[6].strip()
                    tm = fields[7].strip()
                else:
                    date = tm = ""
                pre_close = _f(9) if len(fields) > 9 else None
                open_p = None  # b_ 格式无 open 字段
                high = _f(10) if len(fields) > 10 else None
                low = _f(11) if len(fields) > 11 else None
            else:  # rt
                name = fields[1].strip() if len(fields) > 1 else ""
                pre_close = _f(2)
                open_p = _f(3)
                high = _f(4)
                low = _f(5)
                price = _f(6)
                chg = _f(7)
                chg_pct = _f(8)
                date = fields[17].strip() if len(fields) > 17 else ""
                tm = fields[18].strip() if len(fields) > 18 else ""
        except Exception:  # noqa: BLE001
            continue
        if price is None or price <= 0:
            continue
        # datetime 统一为 YYYYMMDDHHMMSS（与 _fetch_hk_cshkdiv_sina / indices 一致，
        # 去除 b_ 的 "-" 和 rt_ 的 "/" 分隔符）
        dtstr = (date.replace("/", "").replace("-", "") + tm.replace(":", "")) if date else ""
        out[idx_id] = {
            "name": name,
            "price": price,
            "chg": chg,
            "chg_pct": chg_pct,
            "pre_close": pre_close,
            "open": open_p,
            "high": high,
            "low": low,
            "date": date,
            "time": tm,
            "datetime": dtstr,
        }
    return out


def _parse_sina_commodity(text: str) -> list[dict]:
    """解析新浪商品期货实时源（nf_/hf_ 前缀，GBK）。

    各品种字段位置（实测 2026-07-29）：
    - nf_ 国内期货（nf_AU0/nf_SC0/nf_AG0 等）:
        [0]=名称 [1]=持仓量 [2]=昨收 [3]=今开 [4]=最高 [5]=最低
        [6]=买价 [7]=卖价 [8]=最新价 [9]=涨跌 [10]=均价
        [15]=交易所 [16]=品种 [17]=日期(YYYY-MM-DD) [18]=状态
    - hf_CL/hf_SI/hf_OIL（外盘期货，格式一致）:
        [0]=最新价 [1]=空 [2]=昨收 [3]=今开 [4]=最高 [5]=最低
        [6]=时间(HH:MM:SS) [7]=? [8]=? [9-11]=量 [12]=日期 [13]=名称 [14]=?
    - hf_XAU（伦敦金现货，格式与前三个不同！）:
        [0]=最新价 [1]=昨收 [2]=今开 [3]=最高 [4]=最低
        [5]=时间(HH:MM:SS) [6-8]=? [9-10]=量 [11]=日期 [12]=名称

    返回 list[dict]（code/name/price/pre_close/change/pct_change/datetime），
    返回空 list 表示无可用数据。失败的 code 不出现。
    """
    out = []
    for line in text.strip().split("\n"):
        line = line.strip().rstrip(";")
        if not line.startswith("var hq_str_") or "=" not in line:
            continue
        try:
            code = line.split("=", 1)[0].replace("var hq_str_", "")
            body = line.split('"', 2)[1]
            fields = body.split(",")
            if len(fields) < 6:
                continue
        except Exception:  # noqa: BLE001
            continue

        def f(i):
            try:
                return float(fields[i])
            except (IndexError, ValueError):
                return None

        price = None
        pre_close = None
        name = code
        date = ""

        if code.startswith("nf_"):
            # 国内期货：[8]=最新价 [2]=昨收 [17]=日期
            price = f(8)
            pre_close = f(2)
            name = fields[0].strip() if fields[0] else code
            date = fields[17].strip() if len(fields) > 17 else ""
        elif code in ("hf_CL", "hf_SI", "hf_OIL"):
            # 外盘 CL/SI/OIL：[0]=最新价 [2]=昨收 [12]=日期 [13]=名称
            price = f(0)
            pre_close = f(2)
            date = fields[12].strip() if len(fields) > 12 else ""
            name = fields[13].strip() if len(fields) > 13 else code
        elif code == "hf_XAU":
            # 伦敦金现货：[0]=最新价 [1]=昨收 [12]=日期 [13]=名称
            # 注意 hf_XAU 比 hf_CL 多一个字段（[5]额外位），date/name 索引偏移到 12/13
            price = f(0)
            pre_close = f(1)
            date = fields[12].strip() if len(fields) > 12 else ""
            name = fields[13].strip() if len(fields) > 13 else code
        else:
            continue

        if price is None:
            continue
        change = (price - pre_close) if (price and pre_close) else None
        pct = (change / pre_close * 100) if (change is not None and pre_close) else None
        dtstr = date.replace("-", "") if date else ""
        out.append({
            "code": code,
            "name": name,
            "price": price,
            "pre_close": pre_close,
            "change": change,
            "pct_change": pct,
            "datetime": dtstr,
        })
    return out


def _parse_sina_fx(text: str) -> dict | None:
    """解析新浪外汇实时源 fx_susdcny（离岸人民币，GBK）。

    字段（实测 2026-07-29）：
      [0]=时间(HH:MM:SS) [1]=买入 [2]=卖出 [3]=最新价 [4]=?
      [5]=? [6]=? [7]=? [8]=昨收价 [9]=名称(显示"在岸人民币"但代码是离岸,新浪命名混乱)
      [10]=涨跌 [11]=涨跌幅 [12]=? [13]=说明 [17]=日期(YYYY-MM-DD)
    """
    for line in text.strip().split("\n"):
        line = line.strip().rstrip(";")
        if not line.startswith("var hq_str_fx_susdcny") or "=" not in line:
            continue
        try:
            body = line.split('"', 2)[1]
            fields = body.split(",")
            if len(fields) < 4:
                return None
        except Exception:  # noqa: BLE001
            return None

        def f(i):
            try:
                return float(fields[i])
            except (IndexError, ValueError):
                return None

        price = f(3)  # 最新价
        if price is None:
            return None
        pre_close = f(8)  # 昨收价
        date = fields[17].strip() if len(fields) > 17 else ""
        name = fields[9].strip() if len(fields) > 9 else "离岸人民币"
        change = f(10)
        pct = f(11)
        dtstr = date.replace("-", "") if date else ""
        return {
            "code": "fx_susdcny",
            "name": name,
            "price": price,
            "pre_close": pre_close,
            "change": change,
            "pct_change": pct,
            "datetime": dtstr,
        }
    return None


def fetch_commodity_realtime() -> list[dict]:
    """采集 6 商品实时行情（新浪 hq.sinajs.cn 批量）。

    nf_AU0(沪金)/nf_SC0(INE原油)/hf_CL(WTI)/hf_SI(COMEX白银)/hf_OIL(布伦特)/hf_XAU(伦敦金)。
    批量请求一次拉全部，返回 list[dict]（失败的 code 不出现）。
    """
    try:
        throttle()
        r = requests.get(
            "http://hq.sinajs.cn/list=" + ",".join(COMMODITY_CODES),
            headers=_SINA_HEADERS, timeout=10)
        data = _parse_sina_commodity(r.content.decode("gbk"))
        got = [d["code"] for d in data]
        miss = [c for c in COMMODITY_CODES if c not in got]
        print(f"  [intraday] 商品实时采集: {len(data)}/{len(COMMODITY_CODES)} 条"
              + (f"（缺失 {miss}）" if miss else ""), flush=True)
        return data
    except Exception as e:  # noqa: BLE001
        print(f"  [intraday] 商品实时采集失败: {type(e).__name__} {e}", flush=True)
        return []


def fetch_fx_realtime() -> dict | None:
    """采集离岸人民币实时汇率（新浪 fx_susdcny）。失败返 None。"""
    try:
        throttle()
        r = requests.get(
            "http://hq.sinajs.cn/list=" + FX_CODE,
            headers=_SINA_HEADERS, timeout=10)
        fx = _parse_sina_fx(r.content.decode("gbk"))
        if fx:
            print(f"  [intraday] 离岸人民币实时: {fx['price']} (source=fx_susdcny)", flush=True)
        else:
            print(f"  [intraday] fx_susdcny 返回空", flush=True)
        return fx
    except Exception as e:  # noqa: BLE001
        print(f"  [intraday] 离岸人民币实时采集失败: {type(e).__name__} {e}", flush=True)
        return None


def fetch_index_realtime() -> list[dict]:
    """采集 17 指数实时行情（9 A 股核心 + 3 港股宽基 + 4 signals 触发 + 1 新浪港股）。
    腾讯主，A 股失败逐个降级新浪。港股只走腾讯（新浪不支持 r_hkXXX 格式），
    但 hk_cshkdiv 腾讯无代码，新浪 rt_hkCSHKDIV 港股指数实时接口单独采。返回最多 17 条。"""
    # 1) 腾讯主源（一次拉全部，含 A 股 + 港股）
    result: list[dict] = []
    tdata: list[dict] = []
    missing: list[str] = []
    try:
        throttle()
        r = requests.get(_TENCENT_URL, headers={"User-Agent": UA}, timeout=10)
        tdata = _parse_tencent(r.content.decode("gbk"))
        got = {d["code"] for d in tdata if d.get("price")}
        if len(got) >= len(INDEX_CODES) - 1:  # 容忍 1 个缺失
            result = tdata
        else:
            # 缺的用新浪补（仅 A 股，港股跳过新浪不支持）
            missing = [c for c in INDEX_CODES if c not in got and not c.startswith("r_hk")]
            if missing:
                print(f"  [intraday] 腾讯缺 {len(missing)} A 股指数，新浪补采: {missing}", flush=True)
            hk_missing = [c for c in INDEX_CODES if c not in got and c.startswith("r_hk")]
            if hk_missing:
                print(f"  [intraday] 腾讯缺 {len(hk_missing)} 港股指数（新浪不支持，跳过）: {hk_missing}", flush=True)
    except Exception as e:  # noqa: BLE001
        tdata = []
        missing = [c for c in INDEX_CODES if not c.startswith("r_hk")]  # 全量降级新浪（仅 A 股）
        print(f"  [intraday] 腾讯请求失败，A 股降级新浪: {type(e).__name__} {e}", flush=True)

    # 2) 新浪补缺失（仅 A 股，逐个，新浪支持 list 批量但分批更稳）
    if missing:
        try:
            throttle()
            r = requests.get(
                "http://hq.sinajs.cn/list=" + ",".join(missing),
                headers=_SINA_HEADERS, timeout=10)
            sdata = _parse_sina(r.content.decode("gbk"))
            s_by_code = {d["code"]: d for d in sdata if d.get("price")}
        except Exception as e:  # noqa: BLE001
            print(f"  [intraday] 新浪补采失败: {type(e).__name__} {e}", flush=True)
            s_by_code = {}

        # 合并：腾讯已有的保留，缺失的用新浪
        merged = {d["code"]: d for d in tdata}
        for c in missing:
            if c in s_by_code:
                merged[c] = s_by_code[c]
        # 按 INDEX_CODES 顺序输出
        result = [merged[c] for c in INDEX_CODES if c in merged]

    # 3) 新浪港股 rt_ 单独采 hk_cshkdiv（腾讯无代码，新浪 A 股 list 不支持 rt_ 前缀）
    cshkdiv = _fetch_hk_cshkdiv_sina()
    if cshkdiv:
        result.append(cshkdiv)

    return result


def _load_sw_names() -> dict[str, str]:
    """从 config 读申万一级行业名：{sw_id: name}。读不到时用 THS_TO_SW 反查首个子行业名兜底。"""
    try:
        from .fetchers import load_config
        cfg = load_config()
        names = {}
        for idx in cfg.get("indices", []):
            iid = idx.get("id", "")
            if iid.startswith("sw_") and idx.get("enabled", True):
                names[iid] = idx.get("name", iid)
        return names
    except Exception:  # noqa: BLE001
        return {}


def fetch_industry_realtime() -> list[dict]:
    """31 申万一级行业实时涨跌幅 + 净流入 + 成交额 + 领涨股。

    调同花顺 stock_board_industry_summary_ths() 拿 90 二级行业，通过 THS_TO_SW 聚合：
    - pct_change：子行业涨跌幅按成交额加权平均
    - net_inflow：子行业净流入求和（亿元）
    - amount：子行业成交额求和，元->亿元（与申万 DB amount 单位一致）
    - lead_stock：取该申万行业下涨跌幅最高子行业的领涨股
    返回 31 条 {sw_code, sw_name, pct_change, net_inflow, amount, lead_stock}。
    """
    import akshare as ak

    try:
        df = ak.stock_board_industry_summary_ths()
    except Exception as e:  # noqa: BLE001
        print(f"  [intraday] 同花顺行业 summary 失败: {type(e).__name__} {e}", flush=True)
        return []

    if df is None or len(df) == 0:
        print("  [intraday] 同花顺行业 summary 空", flush=True)
        return []

    sw_names = _load_sw_names()
    # 反向：sw_id -> [(ths_name, pct, amt, net, lead_stock, lead_pct)]
    agg: dict[str, list] = {}
    for _, row in df.iterrows():
        ths_name = str(row["板块"]).strip()
        sw_id = THS_TO_SW.get(ths_name)
        if sw_id is None:
            continue
        try:
            pct = float(row["涨跌幅"])
        except (TypeError, ValueError):
            pct = 0.0
        try:
            amt = float(row["总成交额"])
        except (TypeError, ValueError):
            amt = 0.0
        try:
            net = float(row["净流入"])
        except (TypeError, ValueError):
            net = 0.0
        lead = ""
        try:
            lead = str(row.get("领涨股", "") or "").strip()
        except Exception:  # noqa: BLE001
            pass
        agg.setdefault(sw_id, []).append((ths_name, pct, amt, net, lead))

    out = []
    for sw_id, subs in agg.items():
        tot = sum(s[2] for s in subs) or 1.0
        wpct = sum(s[1] * s[2] for s in subs) / tot
        net = sum(s[3] for s in subs)
        amt = sum(s[2] for s in subs)  # 子行业成交额求和（元）
        # 领涨股：取涨幅最高子行业
        best = max(subs, key=lambda s: s[1]) if subs else None
        lead_stock = best[4] if best else ""
        out.append({
            "sw_code": sw_id,
            "sw_name": sw_names.get(sw_id, sw_id),
            "pct_change": round(wpct, 2),
            "net_inflow": round(net, 2),
            "amount": round(amt / 1e8, 2),  # 元->亿元，与申万 DB amount 单位一致
            "lead_stock": lead_stock,
        })
    # 按 pct_change 降序
    out.sort(key=lambda x: x["pct_change"], reverse=True)
    return out


def fetch_concept_realtime() -> list[dict]:
    """27 同花顺概念板块实时涨跌幅 + OHLC + 成交额。

    复用 index_backfill._ths_concept_info_fetch 的拉取逻辑：
    ak.stock_board_concept_info_ths(symbol=概念名) 拿当日快照（项目/值两列），
    合成 open=今开 / high=最高 / low=最低 / close=昨收×(1+板块涨幅/100) /
    pct=板块涨幅 / amount=成交额(亿)×1e8(转元，对齐历史序列入库单位)。

    与 fetch_industry_realtime 的差异：
    - 行业 summary 一次返 90 子行业（聚合 31 申万），概念需逐个调（27 次）；
    - 概念快照含完整 OHLC（今开/最高/最低），行业 summary 只有涨跌幅（close 需计算法）。

    概念配置从 indicators.yaml 读 enabled thsc_ 项。返回 27 条 dict（失败的跳过），
    按 pct_change 降序，结构与 industries 对齐便于前端复用渲染逻辑。
    """
    from .fetchers import load_config
    from .index_backfill import _ths_concept_info_fetch

    cfg = load_config()
    concepts_cfg = [i for i in cfg.get("indices", [])
                    if i.get("id", "").startswith("thsc_") and i.get("enabled", True)]
    today = datetime.now().strftime("%Y%m%d")

    out = []
    fail = 0
    for tc in concepts_cfg:
        thsc_id = tc["id"]
        # symbol 是 akshare 接口参数（概念名），name 是展示名
        symbol = tc.get("symbol") or tc.get("name", thsc_id)
        # throttle 限流：27 个概念逐个调，避免触发同花顺反爬
        throttle()
        # _ths_concept_info_fetch 返回 [(date, thsc_id, open, high, low, close, pct, amount)]
        rows = _ths_concept_info_fetch(thsc_id, symbol, today)
        if rows:
            r = rows[0]
            out.append({
                "id": thsc_id,
                "name": tc.get("name", thsc_id),
                "pct_change": r[6],
                "close": r[5],
                "open": r[2],
                "high": r[3],
                "low": r[4],
                "amount": r[7],
            })
        else:
            fail += 1
    # 按 pct_change 降序（None 兜底排末尾）
    out.sort(key=lambda x: (x.get("pct_change") is None, x.get("pct_change") or -999), reverse=True)
    print(f"  [intraday] 概念实时采集完成：{len(out)}/{len(concepts_cfg)} 条"
          f"（失败 {fail}）", flush=True)
    return out


def is_market_closed(at: datetime | None = None) -> tuple[bool, str]:
    """判断 A 股是否收盘。返回 (is_closed, label)。

    时间+数据双重判断：传入 at（通常是快照 collected_at）时按该时刻判断
    落在哪个时段；不传默认 now（向后兼容现有无参调用）。

    6 态区分（基于 at 而非当前时钟）：
    - 盘中(9:30-11:30 / 13:00-15:00 周一至五交易日): (False, "盘中实时小结")
    - 集合竞价申报(9:15-9:25): (False, "集合竞价申报中·9:25定开盘价")
      # 9:15 集合竞价开始申报, 开盘价未定(9:25才定), 连续竞价 9:30 才开始.
      # is_closed=False: 非收盘态, 盘中跳过 global 导出省5-10s; 与前端 _isAuctionCall 对齐.
    - 竞价完成(9:25-9:30): (False, "竞价完成·待开盘（9:30开盘）")
      # 9:25 集合竞价完成，开盘价已确定（腾讯实时源返开盘价），但连续竞价未开始。
      # is_closed=False：非收盘态，盘中跳过 global 导出省5-10s；用户 9:25 即可看竞价开盘涨跌。
    - 午休(11:30-13:00): (False, "午休·盘中暂停（13:00复牌）")  # 午休也算未收盘
    - 收盘 / 非交易日: (True, "收盘快照")
    - at 早于今天（旧数据）: (True, "上一交易日收盘")
    """
    at = at or datetime.now()
    today = datetime.now().date()
    at_date = at.date()
    # 数据来自前一交易日 -> 已收盘的旧数据（非今日实时）
    if at_date < today:
        return True, "上一交易日收盘"
    try:
        from ..calendar import is_trading_day
        trading = is_trading_day(at_date)
    except Exception:  # noqa: BLE001
        trading = True  # 拿不到日历默认按交易日处理（仅影响 label 文案）
    if not trading:
        return True, "收盘快照"
    hm = at.hour * 100 + at.minute
    if (930 <= hm <= 1130) or (1300 <= hm < 1500):
        return False, "盘中实时小结"
    if 915 <= hm < 925:
        # 9:15-9:25 集合竞价申报段: 开盘价未定(9:25才定), 连续竞价 9:30 才开始.
        # is_closed=False: 非收盘态, 盘中跳过 global 导出省5-10s; 与前端 _isAuctionCall 对齐.
        return False, "集合竞价申报中·9:25定开盘价"
    if 925 <= hm < 930:
        # 9:25 集合竞价完成，开盘价已定（腾讯实时源返开盘价），连续竞价 9:30 才开始。
        # is_closed=False：非收盘态，盘中跳过 global 导出省5-10s；用户 9:25 即可看竞价开盘涨跌。
        return False, "竞价完成·待开盘（9:30开盘）"
    if 1130 < hm < 1300:
        return False, "午休·盘中暂停（13:00复牌）"
    return True, "收盘快照"


def is_hk_market_closed(at: datetime | None = None) -> tuple[bool, str]:
    """判断港股是否收盘。返回 (is_closed, label)。

    港股交易时间 9:30-12:00 / 13:00-16:00（北京时间，与 A 股同时区）。
    16:00 收盘，A 股 15:00 收盘后到 16:00 之间港股仍在盘中。
    午休 12:00-13:00 属"盘中暂停"而非收盘：is_closed=False，label 提示午休。

    时间+数据双重判断：传入 at 时按该时刻判断；不传默认 now（向后兼容）。
    """
    at = at or datetime.now()
    today = datetime.now().date()
    at_date = at.date()
    if at_date < today:
        return True, "上一交易日收盘"
    try:
        from ..calendar import is_trading_day
        trading = is_trading_day(at_date)
    except Exception:  # noqa: BLE001
        trading = True
    if not trading:
        return True, "收盘快照"
    hm = at.hour * 100 + at.minute
    if (930 <= hm <= 1200) or (1300 <= hm < 1600):
        return False, "盘中实时"
    if 1200 < hm < 1300:
        return False, "午休·盘中暂停（13:00复牌）"
    return True, "收盘快照"


def _save_db(collected_at: str, is_closed: bool,
             indices: list, industries: list, concepts: list = None,
             us_futures: dict = None, global_realtime: dict = None) -> None:
    """存 DB（单行覆盖，id=1）。concepts/us_futures/global_realtime 可选（向后兼容旧调用）。"""
    conn = get_conn()
    if concepts is None:
        concepts = []
    if us_futures is None:
        us_futures = {}
    if global_realtime is None:
        global_realtime = {}
    conn.execute(
        "INSERT INTO intraday_snapshot (id, collected_at, is_closed, indices, industries, concepts, us_futures, global_realtime) "
        "VALUES (1, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET "
        "collected_at=excluded.collected_at, is_closed=excluded.is_closed, "
        "indices=excluded.indices, industries=excluded.industries, concepts=excluded.concepts, "
        "us_futures=excluded.us_futures, global_realtime=excluded.global_realtime",
        (collected_at, 1 if is_closed else 0,
         json.dumps(indices, ensure_ascii=False),
         json.dumps(industries, ensure_ascii=False),
         json.dumps(concepts, ensure_ascii=False),
         json.dumps(us_futures, ensure_ascii=False),
         json.dumps(global_realtime, ensure_ascii=False)),
    )
    conn.commit()
    conn.close()


def _ensure_amount_history_table() -> None:
    """确保 intraday_amount_history 表存在（正确 schema：date/time_hhmm/cum_amount）。"""
    conn = get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS intraday_amount_history (
            date TEXT NOT NULL,
            time_hhmm TEXT NOT NULL,
            cum_amount REAL NOT NULL,
            source TEXT DEFAULT 'intraday',
            run_at TEXT,
            PRIMARY KEY (date, time_hhmm)
        )
    """)
    conn.commit()
    conn.close()


def _forecast_amount(today: str, hhmm: str, cum_amount: float):
    """预估全天成交额。方案 C 历史分时占比(>=1 完整日, n<3 与固定曲线混合) + 方案 A 兜底。

    A 股分时成交节奏经验累计占比(截至该时点占全天)，依据 A 股实际分时分布:
      - 集合竞价(9:25)约占 1%；开盘 30min(9:30-10:00)放量段约占全天 30-33%
      - 10:15 累计 ~41%(近期活跃市)；上午(9:30-11:30)约占全天 50%
      - 午后(13:00-15:00)约占 50%；尾盘(14:30-15:00)放量约占 23%
    详见 _EXP_RATIOS 注释。

    边界保护: forecast 限制在历史日均成交额的 0.5-1.8 倍，防分时占比失真致极端值
    (A 股历史单日最高约 3.5 万亿，1.8 倍历史均量≈4.3 万亿已覆盖极端放量日)。

    2026-08-06 二次校准: (1) _EXP_RATIOS 开盘段仍低估(10:15 旧插值0.32 vs 实盘0.411)
        致 forecast 3.23 万亿高估 30%(同花顺 2.49)；按当日 cum/20日均反推重校曲线
        -> 10:15=0.411, forecast 2.51 万亿(误差<1%)。(2) 方案C门槛 3->1 并加 n/3 权重
        混合(防 1-2 日噪声) + 时点接近性校验(>20min 跳过防陈旧点)。
    2026-08-06 三次校准(全段实盘): 二次仅锚 10:15(25141 分母), 10:30-14:55 仍经验值
        低估(11:30=0.50 -> forecast 3.53 万亿高 27% vs 同花顺 2.78)。改全段以 cum/同花顺
        27800 为分母重校(上午 09:25-11:32 实盘, 下午按典型午后分布), 11:30=0.635 ->
        forecast 2.78 万亿。详见 _EXP_RATIOS 注释。
    """
    # 盘后(hhmm >= "15:00")不预估: 保留盘中最后一次 a_amount_forecast 值，
    # 让盘后 hover 预估vs实际显示"盘中预估 vs 收盘实际"(有对比意义)。
    # 盘后 exp_ratio=1.0 致 forecast=actual, 写入会覆盖盘中预估成 actual(偏差0%无意义)。
    if hhmm >= "15:00":
        return None

    # 开盘初样本不足不预估: 9:30-9:45 cum 极小分时占比也极小,外推易爆炸(9:35 曾现 15.47 万亿)
    # 时点 < 9:45 或 cum < 100 亿(数据异常/尚未放量)均返 None,等 9:45 后样本稳定再预估
    if hhmm < "09:45" or cum_amount < 100:
        return None

    hist_avg = None
    hist_ratios = []  # 方案 C: 各完整历史日的 cum_T/full_day
    conn = None
    try:
        conn = get_conn()
        # 历史日均成交额(全天锚，用于边界保护) - 最近 20 个交易日
        row = conn.execute(
            "SELECT AVG(value) as avg_amt FROM (SELECT value FROM daily_metric "
            "WHERE metric_id='a_amount' AND date < ? AND value > 5000 "
            "ORDER BY date DESC LIMIT 20)",
            (today,),
        ).fetchone()
        if row and row["avg_amt"]:
            hist_avg = float(row["avg_amt"])

        # 方案 C：查历史分时占比（>=1 完整日即启用，n<3 与固定曲线混合过渡）
        rows = conn.execute(
            "SELECT date, MAX(cum_amount) as full_day, MAX(time_hhmm) as t_max "
            "FROM intraday_amount_history WHERE date < ? GROUP BY date "
            "ORDER BY date DESC LIMIT 15",
            (today,),
        ).fetchall()
        q_min = int(hhmm[:2]) * 60 + int(hhmm[3:5])
        for r in rows:
            # 完整日校验: t_max >= 14:50 表示有收盘前后数据，full_day 可信
            # (只跑到上午的日 full_day 被低估，ratio 失真，排除)
            if not r["t_max"] or r["t_max"] < "14:50":
                continue
            if not r["full_day"] or r["full_day"] < 5000:
                continue
            h_row = conn.execute(
                "SELECT time_hhmm, cum_amount FROM intraday_amount_history "
                "WHERE date=? AND time_hhmm <= ? ORDER BY time_hhmm DESC LIMIT 1",
                (r["date"], hhmm),
            ).fetchone()
            if h_row and h_row["cum_amount"] and r["full_day"] > 0:
                # 时点接近性校验: 历史时点距查询时点 >20min 视为陈旧，跳过
                # (防历史日缺该时段快照时用很久前的 cum 致 ratio 失真)
                h_min = int(h_row["time_hhmm"][:2]) * 60 + int(h_row["time_hhmm"][3:5])
                if abs(q_min - h_min) <= 20:
                    hist_ratios.append(h_row["cum_amount"] / r["full_day"])
    except Exception:
        pass
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

    # 固定曲线占比(方案 A)，始终计算供混合
    exp_ratio = _exp_cum_ratio(hhmm)

    # 方案 C：>=1 条历史占比时按 n/3 权重与固定曲线混合
    # n<3 平滑过渡: 1日≈33%历史+67%固定, 2日≈67%历史, 3日+纯历史
    # 防 1-2 日噪声(固定曲线已校准作稳定锚)；clamp 0.5-1.8x 日均兜底极端日
    if hist_ratios:
        avg_ratio = sum(hist_ratios) / len(hist_ratios)
        if 0.02 < avg_ratio < 0.99:
            if exp_ratio > 0:
                w = min(len(hist_ratios) / 3.0, 1.0)
                ratio = w * avg_ratio + (1.0 - w) * exp_ratio
            else:
                ratio = avg_ratio
            if ratio > 0:
                return _clamp_forecast(cum_amount / ratio, hist_avg)

    # 方案 A：经验加权兜底（无历史或历史占比失效时）
    if exp_ratio > 0:
        return _clamp_forecast(cum_amount / exp_ratio, hist_avg)
    return None


def _clamp_forecast(fc: float, hist_avg) -> float:
    """边界保护: forecast 限制在历史日均成交额 0.5-1.8 倍区间。
    hist_avg 为 None 时(历史数据缺失)跳过限制，直接返回原值。"""
    if hist_avg is None or hist_avg <= 0:
        return round(fc, 2)
    lo = hist_avg * 0.5
    hi = hist_avg * 1.8
    if fc < lo:
        return round(lo, 2)
    if fc > hi:
        return round(hi, 2)
    return round(fc, 2)


# A 股分时成交额累计占比(截至该时点占全天比例)。
# 2026-08-06 三次校准(全段实盘): 二次校准(bf762e4)仅锚 10:15=0.411(25141 日均分母),
# 10:30-14:55 仍经验值持续低估(11:30=0.50 -> forecast 3.53 万亿, 高 27% vs 同花顺 2.78)。
# 三次校准以当日实盘 cum / 同花顺全天预估(27800 亿)为分母反推全段占比:
#   上午实盘锚点(cum/27800): 09:25=0.9% 09:35=11.1% 09:45=20.6% 09:55=27.4%
#     10:05=33.0% 10:15=37.1% 10:30=43.4% 11:00=54.4% 11:30=63.5%
#   11:32 cum=17648 / 0.635 = 27792 亿 ≈ 2.78 万亿(对标同花顺, 误差<1%)
#   下午 13:00-15:00 今日无实盘(午休前最后快照 11:32), 按典型 A 股午后分布定锚
#   (13:00=11:30=0.635 午休零成交; 14:30 后放量; 收盘 5min 集中), 15:00=1.000
# 全段统一 27800 分母(非二次的 25141): 25141 致上午占 70%(不合常理), 27800 给 63.5%
#   (活跃市合理); 且避免 10:15(25141)/10:30(27800) 分母切换致 forecast 2.51->2.78 万亿
#   10% 跳变。intraday 历史仅 1 日(20260805 无分时点), 方案 C 不触发, 本曲线为唯一驱动。
_EXP_RATIOS = {
    "09:25": 0.009, "09:30": 0.060, "09:35": 0.111, "09:45": 0.206,
    "09:55": 0.274, "10:05": 0.330, "10:15": 0.371, "10:30": 0.434,
    "11:00": 0.544, "11:30": 0.635, "13:00": 0.635, "13:30": 0.693,
    "14:00": 0.752, "14:30": 0.832, "14:45": 0.905, "14:55": 0.956,
    "15:00": 1.000,
}


def _exp_cum_ratio(hhmm: str) -> float:
    """按 _EXP_RATIOS 线性插值计算截至 hhmm 的累计占比(精确到分钟)。

    修复旧逻辑 `hhmm <= t` 边界 bug: 旧逻辑 hhmm 命中锚点时返回前一个 ratio
    (如 09:55 返回 09:45 的 0.12 而非 0.16)，且只取下界不插值。
    线性插值: hhmm 落在 (t1, t2) 之间时按分钟线性插值，命中锚点返回锚点值。
    hhmm < 最早锚点(09:25)时返回 0(竞价前无成交)；> 最晚锚点(15:00)返回 1.0。
    """
    if not hhmm:
        return 0.0
    items = sorted(_EXP_RATIOS.items())  # [(time, ratio), ...]
    if hhmm < items[0][0]:
        return 0.0
    for t, r in items:
        if hhmm == t:
            return r
    if hhmm > items[-1][0]:
        return 1.0
    # 线性插值: 找 hhmm 落在哪两个锚点之间
    for i in range(len(items) - 1):
        t1, r1 = items[i]
        t2, r2 = items[i + 1]
        if t1 < hhmm < t2:
            m1 = int(t1[:2]) * 60 + int(t1[3:5])
            m2 = int(t2[:2]) * 60 + int(t2[3:5])
            mh = int(hhmm[:2]) * 60 + int(hhmm[3:5])
            if m2 <= m1:
                return r1
            return r1 + (r2 - r1) * (mh - m1) / (m2 - m1)
    return 0.0


def _backfill_index_daily(indices: list[dict]) -> int:
    """把盘中快照的当日指数 OHLC 反哺 index_daily 表（UPSERT，幂等）。

    解决 T+1 数据源（baostock/东财 trend）收盘后未出当日数据致指数卡片/恐贪停在 T-2 的问题。
    A 股 15:00 收盘 -> 快照 price 即收盘价；港股 16:00 收盘 -> 15:35 快照时 price 是盘中
    实时价（非最终收盘价），但写入 close 让港股卡片显示当日实时涨跌；17:50 update_all
    再跑 intraday_snapshot 时港股已收盘，腾讯返收盘价 + 成交额，覆盖盘中价。
    港股成交额从腾讯 field[6]（万港元）提取（_parse_tencent），A 股 amount 留 NULL
    （新浪全量源有成交额）。
    非交易日不写；快照 datetime 非当日不写（避免旧快照污染）。
    返回写入的指数条数。
    """
    from ..calendar import is_trading_day

    today = datetime.now().strftime("%Y%m%d")
    if not is_trading_day(today):
        print(f"  [intraday] 非交易日({today})，跳过 index_daily 反哺", flush=True)
        return 0

    conn = get_conn()
    n = 0
    for idx in indices:
        code = idx.get("code", "")
        index_id = _SNAPSHOT_TO_INDEX_ID.get(code)
        if not index_id:
            continue
        price = idx.get("price")
        if price is None:
            continue
        # datetime 校验：必须是当日数据，避免旧快照污染
        dtstr = idx.get("datetime", "")
        snap_date = dtstr[:8] if len(dtstr) >= 8 else ""
        if snap_date and snap_date != today:
            print(f"  [intraday] {code} 快照日期 {snap_date} != 今日 {today}，跳过", flush=True)
            continue

        conn.execute(
            "INSERT INTO index_daily (date, index_id, open, high, low, close, pct_change, amount) "
            "VALUES (?,?,?,?,?,?,?,?) "
            "ON CONFLICT(date, index_id) DO UPDATE SET "
            "open=excluded.open, high=excluded.high, low=excluded.low, "
            "close=excluded.close, pct_change=excluded.pct_change, amount=excluded.amount",
            (today, index_id, idx.get("open"), idx.get("high"), idx.get("low"),
             price, idx.get("pct_change"), idx.get("amount")),
        )
        n += 1
    conn.commit()
    conn.close()
    print(f"  [intraday] index_daily 反哺完成：{n} 条（来源：实时快照，港股含成交额）", flush=True)
    return n


def _backfill_industry_daily(industries: list[dict], target_date: str = None) -> int:
    """把盘中快照的 31 申万行业涨跌幅反哺 index_daily 表（UPSERT，幂等）。

    解决收盘分析历史弹窗领涨空的问题：market_summary 的 top_industries 查
    index_daily WHERE index_id LIKE 'sw_%' AND pct_change IS NOT NULL，
    盘中快照此前只反哺 9 指数没反哺行业，致当日申万行业行不存在 -> 领涨空。
    同花顺行业 summary 只给涨跌幅无 OHLC，盘中用 close 计算法补 close：
      close = prev_close * (1 + pct_change/100)   (prev_close=DB 该 index_id 最后有 close 的行)
    无 prev_close 时（首次/新行业）close 留 NULL（不硬算），保持原行为。
    amount 来自 fetch_industry_realtime 聚合的子行业成交额（亿元）。
    ON CONFLICT 更新 pct_change + net_inflow + close + amount（盘中实时刷新）；
    open/high/low 仍留 NULL（无盘中 OHLC 源），申万晚间 OHLC pipeline 会覆盖。
    非交易日不写；pct_change 为 None 跳过该条。
    返回写入的行业条数。

    target_date 指定时进入历史补采模式：不依赖 fetch_industry_realtime（只返今日），
    改用 _fetch_sw_ohlc_ths 拿该日期真实 OHLC（含 close，比计算法准）；
    THS 失败则回退计算法（DB 已有 pct_change × prev_close）。
    """
    from ..calendar import is_trading_day

    today = target_date or datetime.now().strftime("%Y%m%d")
    if not is_trading_day(today):
        print(f"  [intraday] 非交易日({today})，跳过 index_daily 行业反哺", flush=True)
        return 0

    # 历史日期补采：用 _fetch_sw_ohlc_ths 拿真实 OHLC，失败回退计算法
    if target_date is not None:
        return _backfill_industry_daily_historical(today)

    conn = get_conn()
    n = 0
    calc_n = 0  # close 计算法命中数
    for ind in industries:
        sw_code = ind.get("sw_code", "")
        if not sw_code:
            continue
        pct = ind.get("pct_change")
        if pct is None:
            continue
        net = ind.get("net_inflow")
        amt = ind.get("amount")
        # close 计算法：查 DB 该 index_id 最后有 close 的行作 prev_close
        # 排除当日(date < today)：pct_change 是相对昨收的日涨幅，多次盘中快照
        # 必须锚定同一 prev_close（昨收），否则 close 会累乘偏移
        prev = conn.execute(
            "SELECT close FROM index_daily WHERE index_id=? AND close IS NOT NULL "
            "AND date < ? ORDER BY date DESC LIMIT 1", (sw_code, today)
        ).fetchone()
        close_val = None
        if prev and prev["close"] is not None:
            close_val = round(float(prev["close"]) * (1 + float(pct) / 100.0), 4)
            calc_n += 1
        conn.execute(
            "INSERT INTO index_daily (date, index_id, open, high, low, close, pct_change, amount, net_inflow) "
            "VALUES (?, ?, NULL, NULL, NULL, ?, ?, ?, ?) "
            "ON CONFLICT(date, index_id) DO UPDATE SET "
            "pct_change=excluded.pct_change, net_inflow=excluded.net_inflow, "
            "close=excluded.close, amount=excluded.amount",
            (today, sw_code, close_val, pct, amt, net),
        )
        n += 1
    conn.commit()
    conn.close()
    print(f"  [intraday] index_daily 行业反哺完成：{n} 条（close 计算法 {calc_n} 条，含 net_inflow/amount）", flush=True)
    return n


def _backfill_industry_daily_historical(target_date: str) -> int:
    """历史日期 sw 行业 close 补采（_fetch_sw_ohlc_ths 优先，计算法兜底）。

    补历史日期(如 7/14)时 fetch_industry_realtime 拿不到该日 pct（只返今日），
    改用 _fetch_sw_ohlc_ths 拿该日期真实 OHLC（聚合 90 子行业 -> 31 申万一级，
    锚定 DB 最后有 close 的行作 junction）。THS 返回真实 close/OHLC，比计算法准。
    THS 失败（子行业数据未发布/网络故障）则回退计算法：
      close = prev_close(DB 最后有 close 的行) × (1 + DB 已有 pct_change/100)
    无 pct_change 或无 prev_close 则跳过（close 留 NULL）。
    """
    from .index_backfill import SW_INDICES
    from .industry_extras import _fetch_sw_ohlc_ths
    from .runner import upsert_index_rows

    conn = get_conn()
    n = 0
    ths_n = 0
    calc_n = 0
    skip_n = 0
    for sw_code in SW_INDICES:
        # 已有 close 跳过（幂等）
        r = conn.execute(
            "SELECT close, pct_change FROM index_daily WHERE index_id=? AND date=?",
            (sw_code, target_date)
        ).fetchone()
        if r and r["close"] is not None:
            skip_n += 1
            continue

        # 优先 THS 拿真实 OHLC（含 open/high/low/close/amount）
        rows, _msg = _fetch_sw_ohlc_ths(sw_code, target_date, target_date, verbose=False)
        rows = [rw for rw in rows if rw[0] == target_date]
        if rows:
            upsert_index_rows(rows)
            ths_n += 1
            n += 1
            db_pct = r["pct_change"] if r else None
            print(f"    ✓ {sw_code} <- ths close={rows[0][5]} (db_pct={db_pct})", flush=True)
            continue

        # 回退计算法：prev_close(DB) × (1 + DB 已有 pct_change/100)
        pct = r["pct_change"] if r else None
        if pct is not None:
            prev = conn.execute(
                "SELECT close FROM index_daily WHERE index_id=? AND close IS NOT NULL "
                "AND date < ? ORDER BY date DESC LIMIT 1", (sw_code, target_date)
            ).fetchone()
            if prev and prev["close"] is not None:
                close_val = round(float(prev["close"]) * (1 + float(pct) / 100.0), 4)
                conn.execute(
                    "UPDATE index_daily SET close=? WHERE index_id=? AND date=?",
                    (close_val, sw_code, target_date)
                )
                calc_n += 1
                n += 1
                print(f"    ~ {sw_code} <- calc close={close_val} "
                      f"(prev={prev['close']}, pct={pct})", flush=True)
                continue

        skip_n += 1
        reason = "无 pct_change" if (not r or r["pct_change"] is None) else "无 prev_close"
        print(f"    ✗ {sw_code} 跳过（{reason}）", flush=True)

    conn.commit()
    conn.close()
    print(f"  [intraday] 行业历史补采({target_date})：{n} 条"
          f"（THS {ths_n} + 计算法 {calc_n} + 已有/跳过 {skip_n}）", flush=True)
    return n


def _backfill_concept_daily(concepts: list[dict]) -> int:
    """把盘中快照的 27 概念 OHLC 反哺 index_daily 表（UPSERT，幂等）。

    与 _backfill_industry_daily 对称：行业 summary 只有涨跌幅（close 需计算法、
    open/high/low 留 NULL），而概念快照（stock_board_concept_info_ths）含完整
    今开/最高/最低，故概念反哺写完整 OHLC（比行业更准）。

    close 仍由昨收×(1+涨幅/100) 合成（快照无收盘价字段，_ths_concept_info_fetch
    已反推）。amount 来自快照成交额(亿)×1e8 转元。ON CONFLICT 更新全部 OHLC +
    pct_change + amount（盘中多次快照持续刷新实时值）；收盘 pipeline（T+1 历史序列）
    次日覆盖为最终收盘值。非交易日不写；pct_change 为 None 跳过该条。
    返回写入的概念条数。
    """
    from ..calendar import is_trading_day

    today = datetime.now().strftime("%Y%m%d")
    if not is_trading_day(today):
        print(f"  [intraday] 非交易日({today})，跳过 index_daily 概念反哺", flush=True)
        return 0

    conn = get_conn()
    n = 0
    for c in concepts:
        cid = c.get("id", "")
        if not cid:
            continue
        pct = c.get("pct_change")
        if pct is None:
            continue
        conn.execute(
            "INSERT INTO index_daily (date, index_id, open, high, low, close, pct_change, amount) "
            "VALUES (?,?,?,?,?,?,?,?) "
            "ON CONFLICT(date, index_id) DO UPDATE SET "
            "open=excluded.open, high=excluded.high, low=excluded.low, "
            "close=excluded.close, pct_change=excluded.pct_change, amount=excluded.amount",
            (today, cid, c.get("open"), c.get("high"), c.get("low"),
             c.get("close"), pct, c.get("amount")),
        )
        n += 1
    conn.commit()
    conn.close()
    print(f"  [intraday] index_daily 概念反哺完成：{n} 条（含完整 OHLC + amount）", flush=True)
    return n


def _backfill_commodity_metrics(commodities: list[dict]) -> int:
    """把 6 商品实时价格写入 daily_metric（覆盖当日值，source='intraday'）。

    解决 gold/oil/wti_oil/comex_silver/brent 盘中 T+1 滞后问题：
    原 futures_main_sina/futures_foreign_hist 是日线函数盘后跑，盘中无当日值。
    新浪 nf_/hf_ 实时源盘中直采，覆盖当日 daily_metric。
    收盘 pipeline（T+1 历史序列）次日覆盖为最终收盘值（UPSERT 幂等）。

    日期校验：
    - 国内期货(nf_)日期必须是今日，否则跳过（避免旧数据污染）
    - 外盘期货(hf_)日期可能是昨日（美盘夜间交易北京时间次日白天），不跳过
      （实时价仍有效，反映最近交易时段收盘价）
    非交易日跳过。返回写入条数。
    """
    from ..calendar import is_trading_day
    from .runner import upsert_metric

    today = datetime.now().strftime("%Y%m%d")
    if not is_trading_day(today):
        print(f"  [intraday] 非交易日({today})，跳过商品 daily_metric 写入", flush=True)
        return 0

    n = 0
    for c in commodities:
        code = c.get("code", "")
        metric_id = COMMODITY_TO_METRIC.get(code)
        if not metric_id:
            continue
        price = c.get("price")
        if price is None:
            continue
        dtstr = c.get("datetime", "")
        snap_date = dtstr[:8] if len(dtstr) >= 8 else ""
        if snap_date and snap_date != today:
            # 国内期货日期必须是今日；外盘期货日期可能是昨日（美盘夜间），放行
            if code.startswith("nf_"):
                print(f"  [intraday] {code} 快照日期 {snap_date} != 今日 {today}，跳过", flush=True)
                continue
        upsert_metric(today, metric_id, price, source="intraday")
        n += 1
    print(f"  [intraday] 商品 daily_metric 写入: {n} 条 (source=intraday)", flush=True)
    return n


def _backfill_fx_metric(fx: dict | None) -> int:
    """把离岸人民币实时汇率写入 daily_metric（覆盖当日 usdcnh 值，source='intraday'）。

    解决 usdcnh 前后端不一致：原 currency_boc_sina（中行日报价 T+1）-> 新浪 fx_susdcny 实时。
    盘中覆盖当日 usdcnh 值；收盘 pipeline（currency_boc_sina 历史）次日覆盖。
    非交易日跳过；fx 为 None 跳过。返回写入条数。
    """
    from ..calendar import is_trading_day
    from .runner import upsert_metric

    if not fx:
        return 0
    today = datetime.now().strftime("%Y%m%d")
    if not is_trading_day(today):
        print(f"  [intraday] 非交易日({today})，跳过 usdcnh daily_metric 写入", flush=True)
        return 0

    price = fx.get("price")
    if price is None:
        return 0
    upsert_metric(today, "usdcnh", price, source="intraday")
    print(f"  [intraday] usdcnh daily_metric 写入: {price} (source=fx_susdcny intraday)", flush=True)
    return 1


def _backfill_cn10y_etf_metric(indices: list[dict]) -> int:
    """把 sh511260 十年国债ETF 实时价格写入 daily_metric（cn10y_etf，source='intraday'）。

    cn10y 收益率本身保持 T+1（bond_china_yield 中债源盘后才出）；
    盘中用 sh511260 ETF 实时价格作参考指标 cn10y_etf（元），前端可用它显示盘中国债走势。
    sh511260 已在 INDEX_CODES 采集并反哺 index_daily（cgb_10y_etf），此处额外写 daily_metric。
    非交易日跳过。返回写入条数。
    """
    from ..calendar import is_trading_day
    from .runner import upsert_metric

    today = datetime.now().strftime("%Y%m%d")
    if not is_trading_day(today):
        return 0

    for idx in indices:
        if idx.get("code") == CN10Y_ETF_INDEX_CODE:
            price = idx.get("price")
            if price is None:
                return 0
            upsert_metric(today, CN10Y_ETF_METRIC_ID, price, source="intraday")
            print(f"  [intraday] cn10y_etf daily_metric 写入: {price} (source=intraday)", flush=True)
            return 1
    return 0


def _collect_intraday_width_metrics() -> dict:
    """盘中采集宽度/成交额指标，写入 daily_metric（source='intraday'）。

    解决 KPI metrics 行(涨停/跌停/炸板率/成交额/量比)+width_1m(涨跌家数)+
    a_sentiment/cross_market 停在 T-1 的问题：盘中 30 分钟快照此前只采指数/行业，
    不采这些 width/fund 指标，致 metrics 行/width/a_sentiment 缺当日值。

    数据源（akshare，各 try/except 不互相阻断）：
    - stock_zh_a_spot（全市场实时快照，~20s）-> a_width_up_count/a_width_down_count/a_amount
    - stock_zt_pool_em（涨停池，盘中实时）-> a_width_zt_count + a_width_max_lianban
    - stock_zt_pool_dtgc_em（跌停池）-> a_width_dt_count
    - stock_zt_pool_zbgc_em（炸板池）-> a_width_zhaban_rate = 炸板数/(涨停数+炸板数)

    采完后调 volume_ratio.compute() 算 a_volume_ratio/a_amount_ma5/ma20/a_volume_signal
    （基于 a_amount，需 index_daily 已有当日 sh pct_change，故在 _backfill_index_daily 之后调）。
    source='intraday'：收盘 pipeline（akshare/mootdx source）会覆盖为最终收盘值。
    非交易日跳过。返回采集到的指标 dict（空=未采到任何指标）。
    """
    from ..calendar import is_trading_day
    import akshare as ak
    from .base import safe_call
    from .fetchers import cross_check_zt_pool
    from .runner import upsert_metric
    from ..compute import volume_ratio

    today = datetime.now().strftime("%Y%m%d")
    if not is_trading_day(today):
        print(f"  [intraday] 非交易日({today})，跳过 width 指标采集", flush=True)
        return {}

    results: dict = {}
    conn = get_conn()

    # 1) stock_zh_a_spot -> up_count / down_count / amount（一次调用拿 3 个，~20s）
    #    spot_df 保留供 step3 跌停池失败时降级源兜底（筛 涨跌幅<=-9.8 算跌停数）
    spot_df = None
    t0 = time.time()
    try:
        df = safe_call(ak.stock_zh_a_spot)
        if isinstance(df, Exception) or df is None or len(df) == 0:
            print(f"  [intraday] stock_zh_a_spot 失败/空: "
                  f"{df if isinstance(df, Exception) else 'empty'} ({time.time()-t0:.1f}s)", flush=True)
        else:
            spot_df = df  # 保留供 step3 跌停池降级源兜底
            up = int((df["涨跌幅"] > 0).sum())
            down = int((df["涨跌幅"] < 0).sum())
            amount = float(df["成交额"].sum()) / 1.0e8  # 元 -> 亿元
            upsert_metric(today, "a_width_up_count", up, source="intraday")
            upsert_metric(today, "a_width_down_count", down, source="intraday")
            upsert_metric(today, "a_amount", amount, source="intraday")
            results.update(up_count=up, down_count=down, amount=round(amount, 2))
            # 预估全天成交额 + 历史分时数据积累（独立 try-except，失败不影响现有采集）
            try:
                from datetime import datetime as _dt
                _now = _dt.now()
                _hhmm = _now.strftime("%H:%M")
                # 1) 建表 + 存历史分时数据（方案 C 积累）
                # 用 _fc_conn 局部连接，不覆盖外层 conn（L1339）：
                # 外层 conn 在 L1463 zhaban 块 fallback 查 zt_count 仍要用，
                # 若此处覆盖+close 会导致 L1463 "Cannot operate on a closed database"。
                _ensure_amount_history_table()
                _fc_conn = get_conn()
                _fc_conn.execute(
                    "INSERT OR REPLACE INTO intraday_amount_history (date, time_hhmm, cum_amount, source, run_at) "
                    "VALUES (?,?,?,?,?)",
                    (today, _hhmm, amount, "intraday", _now.isoformat()),
                )
                _fc_conn.commit()
                _fc_conn.close()
                # 2) 算预估全天成交额（方案 A 经验加权立即 + 方案 C 历史占比校准如果数据足够）
                forecast = _forecast_amount(today, _hhmm, amount)
                if forecast is not None:
                    upsert_metric(today, "a_amount_forecast", round(forecast, 2), source="intraday")
                    results["amount_forecast"] = round(forecast, 2)
                    print(f"  [intraday] amount_forecast: {forecast:.0f}亿 (cum={amount:.0f}亿 at {_hhmm})", flush=True)
            except Exception as e:  # noqa: BLE001
                log_collect(today, "a_amount_forecast", "error", f"预估成交额计算异常: {type(e).__name__} {e}")
                print(f"  [intraday] amount_forecast 异常（不影响采集）: {type(e).__name__} {e}", flush=True)
            print(f"  [intraday] spot: up={up} down={down} amount={amount:.0f}亿 "
                  f"({time.time()-t0:.1f}s)", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"  [intraday] stock_zh_a_spot 异常（不阻断）: {type(e).__name__} {e} "
              f"({time.time()-t0:.1f}s)", flush=True)

    # 2) stock_zt_pool_em -> zt_count + max_lianban（涨停池，盘中实时封板口径）
    t0 = time.time()
    try:
        df = safe_call(ak.stock_zt_pool_em, date=today)
        if isinstance(df, Exception) or df is None or len(df) == 0:
            print(f"  [intraday] stock_zt_pool_em 失败/空 ({time.time()-t0:.1f}s)", flush=True)
            # 交叉验证:涨停池也空=源失败(error);跌停池有数据=本池空=真0(ok写0)
            cross_count, cross_msg = cross_check_zt_pool("stock_zt_pool_em", today)
            if cross_count == 0:
                upsert_metric(today, "a_width_zt_count", 0, source="intraday_cross")
                log_collect(today, "a_width_zt_count", "ok",
                            f"cross-check 真0: {cross_msg}")
            else:
                log_collect(today, "a_width_zt_count", "error",
                            f"stock_zt_pool_em 失败/空: {cross_msg}")
        else:
            zt = int(len(df))
            lianban = None
            if "连板数" in df.columns and len(df):
                lianban = int(df["连板数"].max())
            upsert_metric(today, "a_width_zt_count", zt, source="intraday")
            if lianban is not None:
                upsert_metric(today, "a_width_max_lianban", lianban, source="intraday")
            results.update(zt_count=zt, max_lianban=lianban)
            log_collect(today, "a_width_zt_count", "ok", f"zt={zt}")
            if lianban is not None:
                log_collect(today, "a_width_max_lianban", "ok",
                            f"max_lianban={lianban}")
            print(f"  [intraday] zt_pool: zt={zt} max_lianban={lianban} "
                  f"({time.time()-t0:.1f}s)", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"  [intraday] stock_zt_pool_em 异常（不阻断）: {type(e).__name__} {e} "
              f"({time.time()-t0:.1f}s)", flush=True)
        log_collect(today, "a_width_zt_count", "error",
                    f"stock_zt_pool_em 异常: {type(e).__name__} {e}")

    # 3) stock_zt_pool_dtgc_em -> dt_count（跌停池）
    t0 = time.time()
    try:
        df = safe_call(ak.stock_zt_pool_dtgc_em, date=today)
        if isinstance(df, Exception) or df is None or len(df) == 0:
            print(f"  [intraday] stock_zt_pool_dtgc_em 失败/空 ({time.time()-t0:.1f}s)", flush=True)
            # 交叉验证:跌停池也空=源失败(error);涨停池有数据=本池空=真0(ok写0)
            cross_count, cross_msg = cross_check_zt_pool("stock_zt_pool_dtgc_em", today)
            if cross_count == 0:
                upsert_metric(today, "a_width_dt_count", 0, source="intraday_cross")
                log_collect(today, "a_width_dt_count", "ok",
                            f"cross-check 真0: {cross_msg}")
            else:
                # 降级源: 跌停池+交叉验证均失败(源端故障),用 step1 的 stock_zh_a_spot
                # 筛 涨跌幅<=-9.8 近似跌停数(主板-10%口径;创业板/科创板-20%会多算,属兜底近似)
                if spot_df is not None and "涨跌幅" in spot_df.columns and len(spot_df) > 0:
                    dt_fb = int((spot_df["涨跌幅"] <= -9.8).sum())
                    upsert_metric(today, "a_width_dt_count", dt_fb, source="intraday_fallback")
                    results["dt_count"] = dt_fb
                    log_collect(today, "a_width_dt_count", "ok",
                                f"fallback stock_zh_a_spot: dt={dt_fb} (pctChg<=-9.8, {cross_msg})")
                    print(f"  [intraday] dt_pool fallback spot: dt={dt_fb} "
                          f"(source=intraday_fallback, {time.time()-t0:.1f}s)", flush=True)
                else:
                    log_collect(today, "a_width_dt_count", "error",
                                f"stock_zt_pool_dtgc_em 失败/空: {cross_msg} (fallback spot 不可用)")
        else:
            dt = int(len(df))
            upsert_metric(today, "a_width_dt_count", dt, source="intraday")
            results["dt_count"] = dt
            log_collect(today, "a_width_dt_count", "ok", f"dt={dt}")
            print(f"  [intraday] dt_pool: dt={dt} ({time.time()-t0:.1f}s)", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"  [intraday] stock_zt_pool_dtgc_em 异常（不阻断）: {type(e).__name__} {e} "
              f"({time.time()-t0:.1f}s)", flush=True)
        # 降级源: 异常时也尝试 spot_df 兜底
        if spot_df is not None and "涨跌幅" in spot_df.columns and len(spot_df) > 0:
            dt_fb = int((spot_df["涨跌幅"] <= -9.8).sum())
            upsert_metric(today, "a_width_dt_count", dt_fb, source="intraday_fallback")
            results["dt_count"] = dt_fb
            log_collect(today, "a_width_dt_count", "ok",
                        f"fallback stock_zh_a_spot (after exception): dt={dt_fb} (pctChg<=-9.8)")
            print(f"  [intraday] dt_pool fallback spot (after exc): dt={dt_fb} "
                  f"(source=intraday_fallback)", flush=True)
        else:
            log_collect(today, "a_width_dt_count", "error",
                        f"stock_zt_pool_dtgc_em 异常: {type(e).__name__} {e} (fallback spot 不可用)")

    # 4) stock_zt_pool_zbgc_em -> zhaban_rate = 炸板数/(涨停数+炸板数)（ratio 0-1，与收盘口径一致）
    t0 = time.time()
    try:
        df = safe_call(ak.stock_zt_pool_zbgc_em, date=today)
        if isinstance(df, Exception) or df is None or len(df) == 0:
            # 炸板池（zbgc=炸板专用）空窗时点判断:
            #   - 竞价时段(9:25-9:30)/午休(11:30-13:00)/收盘后(15:00后): 连续竞价未运行或已停,
            #     无炸板产生, 池空=正常空窗, 不 upsert 当日值(保持昨日值, 等 9:30 连续竞价后补),
            #     不交叉验证(空=无数据不好判0), 不 log error 消除 collect_health 红点误判
            #   - 连续竞价时段(9:30-11:30 / 13:00-15:00): 池空=可能真采集失败, 保留原 error 逻辑
            _, mkt_label = is_market_closed()
            is_continuous = (mkt_label == "盘中实时小结")
            if is_continuous:
                print(f"  [intraday] stock_zt_pool_zbgc_em 失败/空 (连续竞价时段, 疑似采集失败, "
                      f"{time.time()-t0:.1f}s)", flush=True)
                log_collect(today, "a_width_zhaban_rate", "error",
                            "stock_zt_pool_zbgc_em 失败/空（连续竞价时段, 疑似采集失败）")
            else:
                print(f"  [intraday] stock_zt_pool_zbgc_em 空（{mkt_label}, 正常空窗, "
                      f"保持昨日值, {time.time()-t0:.1f}s)", flush=True)
                log_collect(today, "a_width_zhaban_rate", "ok",
                            f"stock_zt_pool_zbgc_em 空（{mkt_label}, 正常空窗, 保持昨日值）")
        else:
            zhaban_n = int(len(df))
            zt_n = results.get("zt_count")
            # zt_count 可能本函数采到也可能失败（fallback 查 DB 当日值）
            if zt_n is None:
                row = conn.execute(
                    "SELECT value FROM daily_metric WHERE metric_id='a_width_zt_count' "
                    "AND date=? AND value IS NOT NULL",
                    (today,),
                ).fetchone()
                zt_n = int(row["value"]) if row else None
            denom = (zt_n + zhaban_n) if zt_n is not None else None
            zhaban_rate = (zhaban_n / denom) if denom and denom > 0 else None
            if zhaban_rate is not None:
                upsert_metric(today, "a_width_zhaban_rate", zhaban_rate, source="intraday")
            results.update(zhaban_count=zhaban_n,
                          zhaban_rate=round(zhaban_rate, 4) if zhaban_rate is not None else None)
            rate_str = f"{zhaban_rate:.4f}" if zhaban_rate is not None else "n/a"
            log_collect(today, "a_width_zhaban_rate", "ok",
                        f"zhaban={zhaban_n} rate={zhaban_rate}")
            print(f"  [intraday] zhaban_pool: zhaban={zhaban_n} zt={zt_n} "
                  f"rate={rate_str} ({time.time()-t0:.1f}s)", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"  [intraday] stock_zt_pool_zbgc_em 异常（不阻断）: {type(e).__name__} {e} "
              f"({time.time()-t0:.1f}s)", flush=True)
        log_collect(today, "a_width_zhaban_rate", "error",
                    f"stock_zt_pool_zbgc_em 异常: {type(e).__name__} {e}")

    # 采完zhaban后立即重算derived(封板率=1-炸板率), 避免fengban停昨日致KPI角标滞后
    try:
        from ..compute import derived
        derived.store_derived(derived.compute_derived_formulas())
        print("  [intraday] derived重算完成（fengban_rate=1-zhaban_rate 同步到当日）", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"  [intraday] derived重算失败（不阻断）: {type(e).__name__} {e}", flush=True)

    conn.close()

    # 5) volume_ratio 重算（基于 a_amount -> a_volume_ratio/ma5/ma20/signal）
    #    需 index_daily 当日 sh pct_change（_backfill_index_daily 已先执行）
    if results.get("amount") is not None:
        try:
            volume_ratio.compute_volume_ratio(verbose=False)
            print("  [intraday] volume_ratio 重算完成（基于盘中 a_amount）", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"  [intraday] volume_ratio 重算失败（不阻断）: {type(e).__name__} {e}", flush=True)

    print(f"  [intraday] width 指标采集完成：{len(results)} 项", flush=True)
    return results


def _recompute_scores() -> None:
    """反哺后重算 6 个 per-index 情绪分 + 恐贪指数 + a_sentiment + cross_market。

    per-index 情绪分（sentiment_sz50/hs300/csi500/csi1000/cyb/kc50）依赖 index_daily OHLC，
    反哺当日数据后重算即可得到当日值。恐贪 = 8 子情绪分等权平均，6 个 per-index 更新后
    连同已有的 a_sentiment + cross_market 合成恐贪当日值。

    a_sentiment 依赖 width/fund 指标（涨跌家数/涨停/成交额/北向等）。P3-D 起盘中
    _collect_intraday_width_metrics 已采这些 daily_metric 并 source='intraday'，故重算能
    产生当日值（ratio/zt/zhaban/amount 4+ 分项 >= 3 出分）。cross_market 同理（依赖全部
    simple 指标，trim_mean 去 max/min）。重算失败不阻断（已有历史值不受影响，UPSERT 幂等）。
    """
    from ..compute import sentiment, fear_greed, cross

    index_ids = ["sz50", "hs300", "csi500", "csi1000", "cyb", "kc50"]
    for idx_id in index_ids:
        idx_score, idx_comps = sentiment.compute_index_sentiment(idx_id)
        n = sentiment.store(idx_score, idx_comps, score_id=f"sentiment_{idx_id}")
        last_val = round(float(idx_score.dropna().iloc[-1]), 2) if not idx_score.dropna().empty else None
        last_date = idx_score.dropna().index[-1] if not idx_score.dropna().empty else "?"
        print(f"  [intraday] sentiment_{idx_id}: {n}天, 末日={last_date}={last_val}", flush=True)

    n_fg = fear_greed.compute_fear_greed()
    # 查恐贪末日验证
    conn = get_conn()
    fg_last = conn.execute(
        "SELECT date, value FROM score_daily WHERE score_id='fear_greed' ORDER BY date DESC LIMIT 1"
    ).fetchone()
    conn.close()
    fg_str = f"{fg_last['date']}={fg_last['value']}" if fg_last else "?"
    print(f"  [intraday] fear_greed 重算: {n_fg}天, 末日={fg_str}", flush=True)

    # 重算 a_sentiment + cross_market（保持与 per-index 同步；盘中 width/fund 数据可能不全，
    # 不足分项则不出当日值，但不影响已有历史，UPSERT 幂等）
    try:
        asent_score, asent_comps = sentiment.compute()
        n_asent = sentiment.store(asent_score, asent_comps, score_id="a_sentiment")
        last_val = round(float(asent_score.dropna().iloc[-1]), 2) if not asent_score.dropna().empty else None
        last_date = asent_score.dropna().index[-1] if not asent_score.dropna().empty else "?"
        print(f"  [intraday] a_sentiment: {n_asent}天, 末日={last_date}={last_val}", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"  [intraday] a_sentiment 重算失败（不阻断）: {type(e).__name__} {e}", flush=True)

    try:
        cross_score, cross_comps = cross.compute()
        n_cross = cross.store(cross_score, cross_comps)
        last_val = round(float(cross_score.dropna().iloc[-1]), 2) if not cross_score.dropna().empty else None
        last_date = cross_score.dropna().index[-1] if not cross_score.dropna().empty else "?"
        print(f"  [intraday] cross_market: {n_cross}天, 末日={last_date}={last_val}", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"  [intraday] cross_market 重算失败（不阻断）: {type(e).__name__} {e}", flush=True)


def _log_signal_intraday(sigs: list[tuple]) -> int:
    """把当日信号追加到 signal_intraday_log（盘中每轮重算后记录，供收盘邮件时间线）。

    sigs 为 signals.compute() 返回的全历史 (date, index_id, signal, reason) 元组，
    只取 date==today 的当日信号 + 当前 HH:MM 时间戳 append（每轮重算保留过程历史，
    收盘邮件据此生成"每个信号几点出现/几点消失"时间线，见 check_signals.py）。
    失败不阻断（记录是增强，不影响 signal_daily / signal_stats）。
    """
    today = datetime.now().strftime("%Y%m%d")
    now = datetime.now().strftime("%H:%M")
    today_rows = [(today, now, iid, sig, reason)
                  for (d, iid, sig, reason) in sigs if d == today]
    if not today_rows:
        return 0
    conn = get_conn()
    try:
        conn.executemany(
            "INSERT INTO signal_intraday_log (date, time, index_id, signal, reason) "
            "VALUES (?,?,?,?,?)",
            today_rows,
        )
        conn.commit()
    finally:
        conn.close()
    return len(today_rows)


def _recompute_signals() -> None:
    """反哺+重算 scores 后，重算买卖点信号(signal_daily) + 回测 stats(signal_stats.json)。

    盘中反哺当日 close 后 signals.compute() 能算出当日买卖点（依赖 index_daily close +
    score_daily cross_market 标签）。signal_stats.compute() 依赖 signal_daily 表
    （signals.store 之后）。B 方案（2026-07-21）：盘中也产出当日信号，不再只靠 17:50
    update_all。

    耗时：signals ~1.7s + signal_stats ~1.1s ≈ 2.8s（盘中 30 分钟一次可接受）。
    失败不阻断：已有 update_all 17:50 的 signal_daily + signal_stats.json 不受影响
    （DELETE+INSERT 幂等，重算覆盖；并发写撞锁时 try/except 兜底，下轮再算）。
    """
    from ..compute import signals, signal_stats

    try:
        sigs = signals.compute()
        n_sig = signals.store(sigs)
        print(f"  [intraday] signals 重算: {n_sig} 条", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"  [intraday] signals 重算失败（不阻断）: {type(e).__name__} {e}", flush=True)
        return  # signals 失败则 signal_stats 无意义（signal_daily 未更新）

    # 收盘全过程复现（方案A）：每轮重算后把当日信号+时间戳追加到 signal_intraday_log，
    # 供收盘邮件生成"信号几点出现/几点消失"时间线。失败不阻断。
    try:
        n_log = _log_signal_intraday(sigs)
        if n_log:
            print(f"  [intraday] signal_intraday_log 记录 {n_log} 条（{datetime.now():%H:%M}）", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"  [intraday] signal_intraday_log 记录失败（不阻断）: {type(e).__name__} {e}", flush=True)

    try:
        stats = signal_stats.compute()
        n_bytes = signal_stats.store(stats)
        print(f"  [intraday] signal_stats 重算: {n_bytes} 字节", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"  [intraday] signal_stats 重算失败（不阻断）: {type(e).__name__} {e}", flush=True)


def _recompute_rotation() -> None:
    """重算板块轮动速度（sw_ 行业 + thsc_ 概念），写入 daily_metric。

    依赖 index_daily 的 sw_/thsc_ 当日 pct_change（_backfill_industry_daily +
    _backfill_concept_daily 已写入）。显式传 date=today：即使某类板块反哺部分
    失败（如行业 summary 挂但概念成功），也能算出已就绪类别的当日轮动速度，
    不依赖 compute_rotation 默认从 sw_df 推断日期（推断取 sw_ 末日，行业未反哺
    时会停在 T-1）。盘中算出当日速度后，export_rotation 导出的 rotation.json
    才含当日行 + 当日领涨 top3。compute_rotation 读 index_daily 全量算 leader
    变化，store_rotation 写当日 6 个指标（source='derived'，收盘 pipeline 覆盖）。
    失败不阻断。仅交易日调用（由 collect_and_save 的 n_ind/n_concept>0 门控）。
    """
    from ..compute.rotation import compute_rotation, store_rotation

    try:
        today = datetime.now().strftime("%Y%m%d")
        result = compute_rotation(date=today)
        n = store_rotation(result)
        print(f"  [intraday] rotation 重算: {n} 指标, date={result.get('date')} "
              f"sw_leader={result.get('sw_leader')} concept_leader={result.get('concept_leader')}",
              flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"  [intraday] rotation 重算失败（不阻断）: {type(e).__name__} {e}", flush=True)


def _export_affected_json(is_closed: bool = False) -> None:
    """重算后 dump 受影响的静态 JSON（双版同步：static-site/data/）。

    导出：overview + sentiment(5 ranges) + 9 指数 detail + hk + a-stock + global
    + industry-all 拆分（31 行业折线 + 27 概念 + meta 热力图）+ rotation，
    让 static-site 的恐贪/情绪分/指数 sparkline/大盘 tab/行业概念轮动都到当日盘中。
    a-stock 重导后指数图和 width 指标反映盘中最新值（解决大盘 A 股 tab 冻结在早盘）。
    industry-all / rotation 盘中导出含当日实时行：行业/概念已反哺 index_daily，
    前端读这些 JSON 即可盘中可见当日（无需改前端读快照）。

    P1实时性优化(2026-07-20): is_closed=False(盘中)跳过 global 导出省5-10s
    (外盘 T+1/盘后才变,盘中导出数据不变浪费5-10s);is_closed=True(盘后15:05收盘轮)
    正常导出。盘后补导机制:update_all.sh -> deploy.sh -> export.py L295-302 全量生成
    global-{3m/6m/1y/3y/5y/all}.json,盘中跳过不会导致线上 global 停在昨日。
    """
    import importlib.util
    from .fetchers import load_config

    ROOT = Path(__file__).absolute().parent.parent.parent
    spec = importlib.util.spec_from_file_location("export", ROOT / "static-site" / "export.py")
    export_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(export_mod)

    cfg = load_config()
    conn = get_conn()

    # overview（含 scores + indices_sparkline + fear_greed_6m）
    export_mod.write_json(export_mod.DATA_DIR / "overview.json",
                          export_mod.export_overview(conn, cfg))

    # sentiment 5 ranges（含 6 per-index + fear_greed 全历史）
    for rng in export_mod.EXPORT_RANGES:
        export_mod.write_json(export_mod.DATA_DIR / f"sentiment-{rng}.json",
                              export_mod.export_sentiment(conn, cfg, rng))

    # sentiment 5 ranges 上传 R2（盘中即时可见，不依赖17:50 update-all）
    # 根因修复2026-07-20: intraday_snapshot 盘中生成 sentiment-{rng}.json 到主库但不上传R2，
    # 前端 app.js dataUrl 对 -all.json 走 R2(ssd.fx8.store/data/)，R2 停在昨日致盘中无数据。
    # 复用 upload_r2.py upload <local> <key>（只依赖 stdlib，自己加载 .env 获取 R2 凭证）。
    # 独立 try-except：失败不阻断采集，log_collect error 让监控发现。
    # REPO=trade-data 时 export_mod.DATA_DIR 指主库（有当日数据），sys.executable 即当前 .venv python。
    try:
        _script = Path(__file__).absolute().parent.parent.parent / "scripts" / "upload_r2.py"
        _ok, _total = 0, 0
        for _rng in export_mod.EXPORT_RANGES:
            _local = export_mod.DATA_DIR / f"sentiment-{_rng}.json"
            if not _local.exists():
                continue
            _total += 1
            _r = subprocess.run(
                [sys.executable, str(_script), "upload", str(_local), f"data/sentiment-{_rng}.json"],
                capture_output=True, text=True, timeout=60)
            if _r.returncode == 0 and "✓" in _r.stdout:
                _ok += 1
            else:
                print(f"  [intraday] sentiment-{_rng}.json R2上传失败: rc={_r.returncode} "
                      f"stdout={_r.stdout[:200]} stderr={_r.stderr[:200]}", flush=True)
        print(f"  [intraday] sentiment R2上传 {_ok}/{_total}", flush=True)
        if _ok < _total:
            log_collect(datetime.now().strftime("%Y%m%d"), "sentiment_r2_upload", "error",
                        f"sentiment R2上传 {_ok}/{_total} 失败")
    except Exception as _e:  # noqa: BLE001
        print(f"  [intraday] sentiment R2上传异常(不阻断采集): {type(_e).__name__} {_e}", flush=True)
        try:
            log_collect(datetime.now().strftime("%Y%m%d"), "sentiment_r2_upload", "error",
                        f"sentiment R2上传异常: {type(_e).__name__} {_e}")
        except Exception:
            pass

    # summary + summary_history（恐贪/情绪分变了，收盘分析横幅与历史弹窗也要更新）
    export_mod.write_json(export_mod.DATA_DIR / "summary.json",
                          export_mod.export_summary())
    export_mod.write_json(export_mod.DATA_DIR / "summary_history.json",
                          export_mod.export_summary_history())

    # 9 指数 detail（反哺的指数 OHLC + signals，含港股 hsi/hstech/hscei）
    # 方案B(2026-07-28): affected 动态合并 = 17 基础 + 今日有信号的非基础指数。
    # 让 sw_/thsc_/cgb_ 等出信号当日的 per-index -all.json 也盘中到 T 日（原仅 17 基础盘中更新）。
    # 查 signal_daily 当日 DISTINCT index_id，排除已在 17 基础的（避免重复导出）。
    affected = list(_SNAPSHOT_TO_INDEX_ID.values())
    try:
        today = datetime.now().strftime("%Y%m%d")
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT index_id FROM signal_daily WHERE date=?", (today,))
        base_set = set(affected)
        extra = [row[0] for row in cur.fetchall() if row[0] not in base_set]
        if extra:
            affected.extend(extra)
            print(f"  [intraday] affected 动态合并: 17 基础 + {len(extra)} 今日有信号非基础指数 "
                  f"({', '.join(extra)})", flush=True)
        else:
            print(f"  [intraday] affected 动态合并: 今日无非基础指数出信号，保持 17 基础", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"  [intraday] affected 动态合并查询失败（回退 17 基础）: {type(e).__name__} {e}", flush=True)
    for iid in affected:
        try:
            export_mod.write_json(export_mod.INDEX_DIR / f"{iid}-all.json",
                                  export_mod.export_index_detail(conn, cfg, iid))
        except Exception as e:  # noqa: BLE001
            # 方案B: 动态加的非基础指数可能无 index_daily 数据（queries.index_detail 容错），
            # 单个失败不阻断其余指数导出（原 17 基础无 try/catch，动态加的需要容错）。
            print(f"  [intraday] index detail {iid} 导出失败（不阻断）: {type(e).__name__} {e}", flush=True)

    # hk tab JSON（含港股指数 OHLC + 港股通；港股反哺后需更新）
    for rng in export_mod.EXPORT_RANGES:
        export_mod.write_json(export_mod.DATA_DIR / f"hk-{rng}.json",
                              export_mod.export_hk(conn, cfg, rng))

    # a-stock（大盘A股tab，复用 export_a_stock；指数图 + width 指标到当日盘中值）
    # a-stock 读 index_daily（已反哺到当日）+ daily_metric（width 类已采到当日），
    # 重导后指数图和 width 指标反映盘中最新值（解决大盘 A 股 tab 冻结在早盘的问题）。
    for rng in export_mod.EXPORT_RANGES:
        try:
            export_mod.write_json(export_mod.DATA_DIR / f"a-stock-{rng}.json",
                                  export_mod.export_a_stock(conn, cfg, rng))
        except Exception as e:  # noqa: BLE001
            print(f"  [intraday] a-stock-{rng} 导出失败（不阻断）: {type(e).__name__} {e}", flush=True)

    # global（大盘全球tab，复用 export_global；外盘 T+1 重导意义不大但保持完整性）
    # P1实时性优化(2026-07-20): 盘中(is_closed=False)跳过 global 导出省5-10s
    #   (外盘 T+1/盘后才变,盘中导出数据不变浪费5-10s);盘后(is_closed=True)正常导出
    #   盘后补导:update_all.sh -> deploy.sh -> export.py L295-302 全量生成 global-*.json
    if is_closed:
        for rng in export_mod.EXPORT_RANGES:
            try:
                export_mod.write_json(export_mod.DATA_DIR / f"global-{rng}.json",
                                      export_mod.export_global(conn, cfg, rng))
            except Exception as e:  # noqa: BLE001
                print(f"  [intraday] global-{rng} 导出失败（不阻断）: {type(e).__name__} {e}", flush=True)
    else:
        print(f"  [intraday] 盘中跳过 global 导出省5-10s(外盘 T+1 不变,盘后 update_all 补导)",
              flush=True)

    # industry-all/5y 拆分（31 行业折线图 + 27 概念 + meta 热力图）
    # 行业/概念已反哺 index_daily 当日行，重导后 industry-{all,5y}-indices/* 和
    # industry-{all,5y}-concepts.json 含当日实时行 -> 前端行业折线/概念列表盘中可见。
    for rng in ("all", "5y"):
        try:
            export_mod.write_industry_split(conn, cfg, rng)
        except Exception as e:  # noqa: BLE001
            print(f"  [intraday] industry-{rng} 拆分导出失败（不阻断）: {type(e).__name__} {e}", flush=True)

    # rotation（轮动速度 + 当日领涨 top3；_recompute_rotation 已写当日 daily_metric）
    try:
        export_mod.write_json(export_mod.DATA_DIR / "rotation.json",
                              export_mod.export_rotation(conn))
    except Exception as e:  # noqa: BLE001
        print(f"  [intraday] rotation 导出失败（不阻断）: {type(e).__name__} {e}", flush=True)

    # 方案B(2026-08-06): 重新生成 boot.json, 保证 boot.overview 始终最新.
    # 根因: boot.json 只在 export.py(17:50/23:00) 生成, 盘中 intraday 每10min 刷新了
    # overview.json/intraday_snapshot.json/summary.json 但未刷新 boot.json, 致 boot.overview
    # 嵌的是昨夜旧版(a_amount=昨日全天值), 前端 fetchBoot 缓存旧 overview 致成交额卡显示昨日值.
    # 此处 overview/summary/intraday_snapshot 均已刷新落盘, export_boot() 读最新版合并即可.
    try:
        export_mod.export_boot()
    except Exception as e:  # noqa: BLE001
        print(f"  [intraday] boot.json 重新生成失败（不阻断）: {type(e).__name__} {e}", flush=True)

    conn.close()
    _g_cnt = len(export_mod.EXPORT_RANGES) if is_closed else 0
    print(f"  [intraday] 静态 JSON dump 完成：overview + sentiment×5 + index detail×{len(affected)} "
          f"+ hk×{len(export_mod.EXPORT_RANGES)} + a-stock×{len(export_mod.EXPORT_RANGES)} "
          f"+ global×{_g_cnt}{'(盘中跳过)' if not is_closed else ''} + industry-all/5y 拆分 + rotation",
          flush=True)


def build_snapshot() -> dict:
    """采集 + 组装快照 dict（不落库）。供 collect_and_save 和 API 共用。

    在采集前捕获 collected_at，传给 is_market_closed/is_hk_market_closed，
    使 JSON 里的 is_closed/label 反映"这份数据的时效"而非"写入时的时钟"
    （采集行业 summary 可能 20s+，跨 11:30 边界时 now 已进午休但数据是上午盘中的）。
    """
    collected_dt = datetime.now()  # 采集起始时刻 = 数据时间
    indices = fetch_index_realtime()
    industries = fetch_industry_realtime()
    concepts = fetch_concept_realtime()
    # T+1 治理：6 商品 + 离岸人民币盘中实时直采（覆盖 T+1 日线函数的当日空值）
    commodities = fetch_commodity_realtime()
    fx = fetch_fx_realtime()
    is_closed, label = is_market_closed(at=collected_dt)
    is_hk_closed, _ = is_hk_market_closed(at=collected_dt)
    # 给每条指数加 is_closed（A 股按 15:00 判断，港股按 16:00 判断）
    for d in indices:
        code = d.get("code", "")
        d["is_closed"] = is_hk_closed if code.startswith("hk") else is_closed
    # prev_trading_day: 快照日的前一个交易日(YYYYMMDD)，供前端 pending 角标判断
    # 卡片 dataDate == prev_trading_day 为正常 T+1，< 则为数据滞后(采集断了)
    # 用交易日历而非自然日差值，避免周末/节假日误判
    from ..calendar import last_trading_day
    prev_td = last_trading_day(collected_dt.date() - timedelta(days=1))
    # 美股期货 ES/NQ（亚盘实时，预估美股当晚方向）。CME GLOBEX 电子盘北京白天仍交易，
    # ES/NQ 实时价反映美股当晚预期。失败不阻断快照（快照核心是 A 股/港股/行业）。
    us_futures = {}
    try:
        from .us_futures import fetch_us_futures
        from ..compute.us_futures_expect import compute_expect
        us_futures = compute_expect(fetch_us_futures())
        if us_futures:
            _parts = [f"{c}={d['chg_pct']:.2f}%" for c, d in us_futures.items()
                      if d.get("chg_pct") is not None]
            if _parts:
                print(f"[intraday] 外盘期货采集: {' '.join(_parts)}", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"[intraday] 美股期货采集失败（不阻断）: {type(e).__name__} {e}", flush=True)
    # AZ89 P1+P2 全球指数实时：盘中韩日/欧美/港股板块/澳印实时（新浪 b_/rt_ 批量采）
    # 失败不阻断快照核心（A 股/港股宽基/行业）；收盘 pipeline 仍走 index_global_hist_sina 补 OHLC
    global_realtime = _fetch_global_realtime_sina()
    if global_realtime:
        print(f"[intraday] 全球指数实时采集: {len(global_realtime)} 个"
              f"（P1 全球5 + P2 港股8 + ASX200/SENSEX）", flush=True)
    return {
        "collected_at": collected_dt.isoformat(),
        "is_closed": is_closed,
        "label": label,
        "prev_trading_day": prev_td,
        "indices": indices,
        "industries": industries,
        "concepts": concepts,
        "us_futures": us_futures,
        "commodities": commodities,
        "fx": fx,
        "global_realtime": global_realtime,
    }


def collect_and_save() -> dict:
    """采集 + 存 DB + dump 静态 JSON。返回快照 dict。

    采集完腾讯实时 12 指数（9 A 股 + 3 港股）后，把当日 OHLC 反哺 index_daily 表
    （UPSERT），再重算 per-index 情绪分 + 恐贪指数，最后 dump 受影响的静态 JSON，
    使指数卡片/恐贪/per-index 情绪分都能到当日（解决 T+1 延迟致停在 T-2 的问题）。
    港股盘中（15:35 快照）反哺实时价作为 close，17:50 update_all 覆盖为收盘价。
    反哺/重算/export 失败不阻断快照本身（快照已落库落盘）。
    """
    print(f"[intraday] 开始采集盘中实时快照 {datetime.now():%Y-%m-%d %H:%M:%S}", flush=True)
    t0 = time.time()

    snap = build_snapshot()

    # 存 DB
    _save_db(snap["collected_at"], snap["is_closed"],
             snap["indices"], snap["industries"], snap["concepts"],
             snap.get("us_futures"), snap.get("global_realtime"))

    # 美股期货 ES/NQ 预期信号落地 daily_metric（供历史回测/统计）。失败不阻断。
    if snap.get("us_futures"):
        try:
            from ..compute.us_futures_expect import save_to_db as _save_usf
            n_usf = _save_usf(datetime.now().strftime("%Y%m%d"), snap["us_futures"])
            if n_usf:
                print(f"[intraday] 美股期货预期落地 daily_metric {n_usf} 条", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[intraday] 美股期货落地 DB 失败（不阻断）: {type(e).__name__} {e}", flush=True)

    # dump 静态 JSON（双版同步：static-site/data/intraday_snapshot.json）
    STATIC_DATA_DIR.mkdir(parents=True, exist_ok=True)
    out_path = STATIC_DATA_DIR / "intraday_snapshot.json"
    text = json.dumps(snap, ensure_ascii=False, separators=(",", ":"))
    out_path.write_text(text, encoding="utf-8")

    dt = time.time() - t0
    print(f"[intraday] 快照完成：{len(snap['indices'])} 指数（9 A 股 + 3 港股） / "
          f"{len(snap['industries'])} 行业 / {len(snap['concepts'])} 概念 "
          f"({snap['label']})，{dt:.1f}s -> {out_path.name}", flush=True)

    # 反哺 index_daily + 盘中采 width 指标 + 重算情绪分/恐贪/轮动 + dump 静态 JSON
    # 失败不阻断快照本身（快照已落库落盘，反哺是增强）
    try:
        n_backfill = _backfill_index_daily(snap["indices"])
        # T+1 治理：6 商品 + 离岸人民币 + cn10y_etf 盘中实时写 daily_metric（覆盖 T+1 当日空值）
        # 失败不阻断（商品/外汇是增强，不影响指数/行业反哺核心流程）
        n_comm = n_fx = n_cn10y_etf = 0
        try:
            n_comm = _backfill_commodity_metrics(snap.get("commodities", []))
        except Exception as e:  # noqa: BLE001
            print(f"[intraday] 商品 daily_metric 写入失败（不阻断）: {type(e).__name__} {e}", flush=True)
        try:
            n_fx = _backfill_fx_metric(snap.get("fx"))
        except Exception as e:  # noqa: BLE001
            print(f"[intraday] usdcnh daily_metric 写入失败（不阻断）: {type(e).__name__} {e}", flush=True)
        try:
            n_cn10y_etf = _backfill_cn10y_etf_metric(snap["indices"])
        except Exception as e:  # noqa: BLE001
            print(f"[intraday] cn10y_etf daily_metric 写入失败（不阻断）: {type(e).__name__} {e}", flush=True)
        # 盘中采 width/fund 指标（涨停/跌停/炸板率/成交额/涨跌家数）+ volume_ratio 重算
        # 需在 _backfill_index_daily 之后（volume_ratio 依赖当日 sh pct_change）
        width_res: dict = {}
        try:
            width_res = _collect_intraday_width_metrics()
        except Exception as e:  # noqa: BLE001
            print(f"[intraday] width 指标采集失败（不阻断）: {type(e).__name__} {e}", flush=True)
        width_n = len(width_res)
        # 预估成交额写入 snap 并重新 dump intraday_snapshot.json（前端从 a_amount_forecast 字段读）
        if width_res.get("amount_forecast") is not None:
            snap["amount_forecast"] = width_res["amount_forecast"]
            try:
                _snap_text = json.dumps(snap, ensure_ascii=False, separators=(",", ":"))
                out_path.write_text(_snap_text, encoding="utf-8")
                print(f"  [intraday] intraday_snapshot.json 重新 dump（含 amount_forecast={width_res['amount_forecast']}）", flush=True)
            except Exception as e:  # noqa: BLE001
                print(f"  [intraday] 重新 dump intraday_snapshot.json 失败（不阻断）: {type(e).__name__} {e}", flush=True)
        n_ind = _backfill_industry_daily(snap["industries"])
        n_concept = _backfill_concept_daily(snap["concepts"])
        # 重算：指数反哺 或 width 指标采集 都触发（width 有当日值后 a_sentiment/cross_market 能出分）
        if n_backfill > 0 or width_n > 0:
            _recompute_scores()
            _recompute_signals()  # B 方案：盘中也产出当日买卖点信号 + stats（依赖 _recompute_scores 的 cross_market）
        # 行业/概念反哺后重算轮动速度（rotation.json 才有当日行 + 当日领涨 top3）
        if n_ind > 0 or n_concept > 0:
            _recompute_rotation()
        if n_backfill > 0 or n_ind > 0 or n_concept > 0 or width_n > 0:
            _export_affected_json(is_closed=snap["is_closed"])
            print(f"[intraday] 反哺+width+重算+export 完成"
                  f"（{n_backfill} 指数 + {n_ind} 行业 + {n_concept} 概念反哺 + {width_n} width 指标"
                  f" + {n_comm} 商品 + {n_fx} usdcnh + {n_cn10y_etf} cn10y_etf）",
                  flush=True)
        else:
            print(f"[intraday] 无反哺（非交易日或快照非当日），跳过重算", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"[intraday] 反哺/重算/export 失败（快照已保存）: {type(e).__name__} {e}", flush=True)

    return snap


def load_latest_snapshot() -> dict | None:
    """从 DB 读最新快照（供 API / export 用）。无数据返 None。

    label 基于 collected_at 重构（时间+数据双重判断在读端同样生效）：
    DB 只存 is_closed（0/1），label 由 is_market_closed(at=collected_at) 推导，
    这样午休采的快照读出来 label 仍是"午休·盘中暂停"而非丢失成"盘中实时小结"。
    """
    conn = get_conn()
    row = conn.execute(
        "SELECT collected_at, is_closed, indices, industries, concepts, us_futures, global_realtime "
        "FROM intraday_snapshot WHERE id=1"
    ).fetchone()
    conn.close()
    if not row:
        return None
    is_closed = bool(row["is_closed"])
    # 基于 collected_at 重构 label（时间+数据双重判断）
    # 同时算 prev_trading_day(上一交易日)，供前端 pending 角标判断数据是否滞后
    prev_td = ""
    try:
        collected_dt = datetime.fromisoformat(row["collected_at"])
        _, label = is_market_closed(at=collected_dt)
        from ..calendar import last_trading_day
        prev_td = last_trading_day(collected_dt.date() - timedelta(days=1))
    except Exception:  # noqa: BLE001
        label = "收盘快照" if is_closed else "盘中实时小结"
    try:
        indices = json.loads(row["indices"])
    except Exception:  # noqa: BLE001
        indices = []
    try:
        industries = json.loads(row["industries"])
    except Exception:  # noqa: BLE001
        industries = []
    # concepts 列可能不存在于旧 DB（迁移前），用 keys 兜底
    try:
        concepts = json.loads(row["concepts"]) if row["concepts"] else []
    except Exception:  # noqa: BLE001
        concepts = []
    # us_futures 列同理（2026-07-15 加，美股期货 ES/NQ 预估美股方向）
    try:
        us_futures = json.loads(row["us_futures"]) if row["us_futures"] else {}
    except Exception:  # noqa: BLE001
        us_futures = {}
    # global_realtime 列（2026-07-31 加，全球指数实时报价；旧 DB 迁移前 keys() 不含此列）
    # row.keys() 兜底：旧 DB 未 ALTER 前查询 SELECT 此列会报错，但 _migrate 已自动加列，
    # 正常路径都有此列；防御性处理：keys() 不含或值为空返 {}（不阻断快照读）
    try:
        global_realtime = json.loads(row["global_realtime"]) if "global_realtime" in row.keys() and row["global_realtime"] else {}
    except Exception:  # noqa: BLE001
        global_realtime = {}
    return {
        "collected_at": row["collected_at"],
        "is_closed": is_closed,
        "label": label,
        "prev_trading_day": prev_td,
        "indices": indices,
        "industries": industries,
        "concepts": concepts,
        "us_futures": us_futures,
        "global_realtime": global_realtime,
    }


def snapshot_industry_heatmap(snap: dict) -> list[dict]:
    """把盘中快照的行业数据转为 heatmap 结构（用于覆盖 DB 的盘中行业，P2-B）。

    snap.industries 有 {sw_code, sw_name, pct_change, net_inflow, lead_stock}，
    转为 {id, name, pct_1d, pct_5d(NULL), net_inflow, lead_stock, last_date}。
    pct_5d 盘中无法计算（snap 无 OHLC 历史），置 NULL，前端 renderIndustryHeatmap
    已兼容 pct_5d=null（只显 pct_1d，格子显"-"）。
    net_inflow/lead_stock 是 heatmap 原本没有的增强字段（盘中实时），前端 tooltip按需展示。
    """
    if not snap:
        return []
    collected_at = snap.get("collected_at", "")
    # ISO "2026-07-14T11:30..." -> "20260714"
    last_date = collected_at[:10].replace("-", "") if len(collected_at) >= 10 else ""
    out = []
    for ind in snap.get("industries", []):
        out.append({
            "id": ind.get("sw_code"),
            "name": ind.get("sw_name"),
            "pct_1d": ind.get("pct_change"),
            "pct_5d": None,
            "net_inflow": ind.get("net_inflow"),
            "lead_stock": ind.get("lead_stock"),
            "last_date": last_date,
        })
    return out


def maybe_override_heatmap(heatmap: list[dict]) -> list[dict]:
    """盘中时用快照行业覆盖 heatmap 的实时字段（P2-B）；收盘或无今日快照时返回原 heatmap。

    MERGE 而非 REPLACE：保留 DB heatmap 的 pct_5d（盘中已用累乘法算出），
    仅用快照的 pct_1d / net_inflow / lead_stock 覆盖实时字段。
    snap 缺 pct_5d 但多 net_inflow + lead_stock，前端 tooltip 兼容。
    """
    try:
        is_closed, _ = is_market_closed()
        if is_closed:
            return heatmap
        snap = load_latest_snapshot()
        if not snap:
            return heatmap
        collected_at = snap.get("collected_at", "")
        today = datetime.now().strftime("%Y-%m-%d")
        if not collected_at.startswith(today):
            return heatmap
        snap_hm = snapshot_industry_heatmap(snap)
        if not snap_hm:
            return heatmap
        # MERGE: 把 snap 的实时字段(pct_1d/net_inflow/lead_stock)叠加到 DB heatmap 上，
        # 保留 DB 的 pct_5d（累乘法已算出），避免盘中近5日被清空。
        snap_map = {h["id"]: h for h in snap_hm}
        for h in heatmap:
            sh = snap_map.get(h["id"])
            if sh:
                h["pct_1d"] = sh.get("pct_1d")
                h["net_inflow"] = sh.get("net_inflow")
                h["lead_stock"] = sh.get("lead_stock")
                h["last_date"] = sh.get("last_date", h.get("last_date"))
        return heatmap
    except Exception as e:  # noqa: BLE001
        print(f"  [intraday] maybe_override_heatmap 失败（回退 DB heatmap）: {type(e).__name__} {e}", flush=True)
        return heatmap


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="盘中实时快照采集")
    parser.add_argument("--date", type=str, default=None,
                        help="补采指定日期(YYYYMMDD)的申万行业 close，不采集新快照")
    args = parser.parse_args()

    if args.date:
        # 历史补采模式：只补 industry close，不覆盖今日 intraday_snapshot
        n = _backfill_industry_daily([], target_date=args.date)
        print(f"[intraday] 历史补采完成：{args.date} 共补 {n} 条行业 close", flush=True)
    else:
        collect_and_save()
