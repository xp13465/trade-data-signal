"""外盘指数期货实时采集（新浪 hf_/b_ 接口 + Yahoo Finance 备用源）。

背景：A 股收盘时美股未开盘（北京时差晚 21:30 才开盘），用户看不到美股当晚方向。
ES 期货（标普500）↔ 标普500 收盘相关性≈0.95，NQ（纳指100）↔ 纳指100 同理；
YM（道指）↔ 道琼斯，HSI（恒指）↔ 恒生指数 同理。
CME GLOBEX 电子盘亚盘（北京白天）仍在交易，期货实时价反映对应指数当晚/当日开盘预期方向。
2026-08-01 扩充：b_ 全球指数 9 只（DAX/CAC/UKX/SX5E/SENSEX/KOSPI/AS51/NKY/RTY），
让外盘预期覆盖欧/亚/美主要指数而非仅美股 4 只。

主源：新浪 hf_（外盘期货 ES/NQ/YM/HSI）+ b_（全球指数 DAX/CAC/UKX/SX5E/SENSEX/KOSPI/AS51/NKY/RTY）
  - 同接口 hq.sinajs.cn/list= 可混请求 hf_ + b_（实测 2026-08-01 OK）
  - 需 Referer: https://finance.sina.com.cn 头（否则返回空）
  - GBK 解码
  - hf_ 字段（实测 2026-07-15）：
      var hq_str_hf_ES="price,bid,ask,open,high,low,time,prev_close,prev_settle2,
                        ,vol,oi,date,name,0";
      [0]=price [3]=open [4]=high [5]=low [6]=time [7]=prev_close [12]=date [13]=name
  - b_ 字段（实测 2026-08-01）：
      var hq_str_b_DAX="名称,price,chg,chg_pct,date1,date2,date,time,prev_close,high,low,vol";
      [0]=name [1]=price [2]=chg [3]=chg_pct [6]=date [7]=time [9]=prev_close [10]=high [11]=low
      无 open -> 用 prev_close 近似
      特殊：b_RTY 仅 6 字段（无 prev_close/high/low），用 price-chg 推算 prev_close

备用源：Yahoo Finance API（主源空时逐个补采，2026-08-01 接入）
  - https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_symbol}
  - 国内 0.55s 可达，无鉴权，仅需 UA 头
  - yahoo_symbol 在 META 配置（ES=F/NQ=F/.../^GDAXI/...）
  - 与 index_backfill._sina_global_realtime_fallback 思路一致：主源失败切备用源

单一配置源：US_FUTURES_META 是唯一配置，采集 URL / 计算映射 / 前端渲染均从此读，
未来扩充只需加一条 META（前提：新浪 hf_/b_ 接口实测返回非空，或 Yahoo 备用源可用）。

chg_pct = (price - prev_close) / prev_close * 100
"""
import re
import time

import requests

from .base import UA, throttle

_SINA_HEADERS = {"User-Agent": UA, "Referer": "https://finance.sina.com.cn"}
_YAHOO_HEADERS = {"User-Agent": UA}

# 预估方向阈值默认值（META 未逐条覆盖时用此）
EXPECT_THRESHOLD = 0.3

# ── 单一配置源：期货代码 -> 元信息 ─────────────────────────────────────
# 未来扩充只改这里（前提：新浪 hf_/b_ 接口实测返回非空，或 Yahoo 备用源可用）。
# 不可用的代码不要硬塞进配置（会导致采集失败，不如留空等未来实测）。
# 字段：
#   index_id:      对应指数 ID（与 index_backfill.HK_GLOBAL_INDICES / intraday_snapshot._GLOBAL_SPOT_CODES 对齐）
#   display_name:  前端卡片展示名（指数名）
#   futures_name:  期货名（新浪返回的 name 优先，此字段作兜底）
#   short:         daily_metric metric_id 短名（us_futures_<short>_{price,chg,signal}）
#   relevance:     期货↔指数收盘相关性（实测的填实测，新增的填理论值）
#   threshold:     预估方向阈值 |chg%|>threshold 判涨跌（默认 EXPECT_THRESHOLD）
#   yahoo_symbol:  Yahoo Finance API 备用源代码（主源空时逐个补采）
US_FUTURES_META = {
    # ── 主源 hf_ 外盘期货 4 只（CME GLOBEX 电子盘亚盘实时） ──
    "hf_ES": {
        "index_id": "us_spx",
        "display_name": "标普500",
        "futures_name": "标普500期货",
        "short": "es",
        "relevance": 0.95,
        "threshold": 0.3,
        "yahoo_symbol": "ES=F",
    },
    "hf_NQ": {
        "index_id": "us_ndx",
        "display_name": "纳斯达克100",
        "futures_name": "纳指100期货",
        "short": "nq",
        "relevance": 0.95,
        "threshold": 0.3,
        "yahoo_symbol": "NQ=F",
    },
    "hf_YM": {
        "index_id": "us_dji",
        "display_name": "道琼斯",
        "futures_name": "道指期货",
        "short": "ym",
        "relevance": 0.95,
        "threshold": 0.3,
        "yahoo_symbol": "YM=F",
    },
    "hf_HSI": {
        "index_id": "hsi",
        "display_name": "恒生指数",
        "futures_name": "恒指期货",
        "short": "hsi",
        "relevance": 0.95,
        "threshold": 0.3,
        "yahoo_symbol": "HSI=F",
    },
    # ── 主源 b_ 全球指数 9 只（新浪 b_ 实时接口，2026-08-01 扩充） ──
    # index_id 与 intraday_snapshot._GLOBAL_SPOT_CODES 对齐（dax/cac40/ftse100/nikkei225/kospi/asx200/sensex）
    # sx5e/us_rty 是新增（_GLOBAL_SPOT_CODES 未含，Yahoo 备用源仍可补）
    "b_DAX": {
        "index_id": "dax",
        "display_name": "德国DAX",
        "futures_name": "德指期货",
        "short": "dax",
        "relevance": 0.95,
        "threshold": 0.3,
        "yahoo_symbol": "^GDAXI",
    },
    "b_CAC": {
        "index_id": "cac40",
        "display_name": "法国CAC40",
        "futures_name": "法指期货",
        "short": "cac40",
        "relevance": 0.95,
        "threshold": 0.3,
        "yahoo_symbol": "^FCHI",
    },
    "b_UKX": {
        "index_id": "ftse100",
        "display_name": "富时100",
        "futures_name": "英指期货",
        "short": "ftse100",
        "relevance": 0.95,
        "threshold": 0.3,
        "yahoo_symbol": "^FTSE",
    },
    "b_SX5E": {
        "index_id": "sx5e",
        "display_name": "欧洲斯托克50",
        "futures_name": "欧洲斯托克50期货",
        "short": "sx5e",
        "relevance": 0.95,
        "threshold": 0.3,
        "yahoo_symbol": "^STOXX50E",
    },
    "b_SENSEX": {
        "index_id": "sensex",
        "display_name": "印度Sensex",
        "futures_name": "印度期货",
        "short": "sensex",
        "relevance": 0.95,
        "threshold": 0.3,
        "yahoo_symbol": "^BSESN",
    },
    "b_KOSPI": {
        "index_id": "kospi",
        "display_name": "韩国KOSPI",
        "futures_name": "韩指期货",
        "short": "kospi",
        "relevance": 0.95,
        "threshold": 0.3,
        "yahoo_symbol": "^KS11",
    },
    "b_AS51": {
        "index_id": "asx200",
        "display_name": "澳洲ASX200",
        "futures_name": "澳指期货",
        "short": "asx200",
        "relevance": 0.95,
        "threshold": 0.3,
        "yahoo_symbol": "^AXJO",
    },
    "b_NKY": {
        "index_id": "nikkei225",
        "display_name": "日经225",
        "futures_name": "日经期货",
        "short": "nikkei225",
        "relevance": 0.95,
        "threshold": 0.3,
        "yahoo_symbol": "^N225",
    },
    "b_RTY": {
        "index_id": "us_rty",
        "display_name": "罗素2000",
        "futures_name": "罗素2000期货",
        "short": "rty",
        "relevance": 0.95,
        "threshold": 0.3,
        "yahoo_symbol": "^RUT",  # Yahoo Russell 2000 标准代码（^RTY 无数据）
    },
}

# 采集 URL 从 META keys 自动拼（未来扩充只改 META，URL 自动跟上，不再硬编码）
# 新浪 hq.sinajs.cn/list= 支持 hf_ 与 b_ 混请求（实测 2026-08-01 OK）
_SINA_URL = "http://hq.sinajs.cn/list=" + ",".join(US_FUTURES_META.keys())

_HF_LINE_RE = re.compile(r'var\s+hq_str_(hf_\w+)\s*=\s*"([^"]*)"')
_B_LINE_RE = re.compile(r'var\s+hq_str_(b_\w+)\s*=\s*"([^"]*)"')


def _parse_sina_hf(text: str) -> dict:
    """解析新浪 hf_ 外盘期货返回（已 GBK 解码后的文本）。

    返回 {hf_ES: {code,source,name,price,prev_close,open,high,low,chg_pct,time,date}, ...}。
    """
    out = {}
    for line in text.strip().split(";"):
        line = line.strip()
        if not line:
            continue
        m = _HF_LINE_RE.match(line)
        if not m:
            continue
        code = m.group(1)
        vals = m.group(2).split(",")
        if len(vals) < 14:
            continue

        def f(i):
            try:
                x = vals[i].strip()
                return float(x) if x else None
            except (IndexError, ValueError):
                return None

        price = f(0)
        prev_close = f(7)  # 昨结算价（涨跌幅基准）
        chg_pct = None
        if price is not None and prev_close and prev_close != 0:
            chg_pct = (price - prev_close) / prev_close * 100
        meta = US_FUTURES_META.get(code, {})
        out[code] = {
            "code": code,
            "source": "sina_hf",
            "name": vals[13].strip() if len(vals) > 13 and vals[13].strip() else meta.get("futures_name", code),
            "price": price,
            "prev_close": prev_close,
            "open": f(3),
            "high": f(4),
            "low": f(5),
            "chg_pct": chg_pct,
            "time": vals[6].strip() if len(vals) > 6 else "",
            "date": vals[12].strip() if len(vals) > 12 else "",
        }
    return out


def _parse_sina_b(text: str) -> dict:
    """解析新浪 b_ 全球指数实时返回（已 GBK 解码后的文本）。

    b_ 字段（实测 2026-08-01）：
      [0]=名称 [1]=最新价 [2]=涨跌额 [3]=涨跌幅 [4]=杂项日期 [5]=杂项日期2
      [6]=行情日期(YYYY-MM-DD) [7]=行情时间(HH:MM:SS) [8]=杂项
      [9]=昨收 [10]=最高 [11]=最低 [12]=成交量
    无 open -> 用 prev_close 近似（与 index_backfill._sina_global_realtime_fallback 一致）。
    特殊：b_RTY 仅 6 字段（[0]名称 [1]price [2]chg [3]chg_pct [4]date [5]date2），
    无 prev_close/high/low -> 用 price-chg 推算 prev_close，high/low 留空。
    返回 {b_DAX: {code,source,name,price,prev_close,open,high,low,chg_pct,time,date}, ...}。
    """
    out = {}
    for line in text.strip().split(";"):
        line = line.strip()
        if not line:
            continue
        m = _B_LINE_RE.match(line)
        if not m:
            continue
        code = m.group(1)
        vals = m.group(2).split(",")
        if len(vals) < 4:
            continue

        def f(i):
            try:
                x = vals[i].strip()
                return float(x) if x else None
            except (IndexError, ValueError):
                return None

        meta = US_FUTURES_META.get(code, {})
        name = vals[0].strip() if vals[0].strip() else meta.get("futures_name", code)
        price = f(1)
        chg = f(2)
        chg_pct = f(3)
        # 字段完整（>=12）: 取 date/time/prev_close/high/low
        if len(vals) >= 12:
            date = vals[6].strip() if len(vals) > 6 else ""
            time_ = vals[7].strip() if len(vals) > 7 else ""
            prev_close = f(9)
            high = f(10)
            low = f(11)
        else:
            # b_RTY 短格式（6 字段）: date 取 [4]/[5], prev_close 用 price-chg 推算, high/low=None
            date = vals[5].strip() if len(vals) > 5 else (vals[4].strip() if len(vals) > 4 else "")
            time_ = ""
            prev_close = None
            if price is not None and chg is not None:
                prev_close = price - chg
            high = None
            low = None
        # chg_pct 兜底：源端未给则用 price/prev_close 算
        if (chg_pct is None or abs(chg_pct) < 1e-9) and price and prev_close and prev_close != 0:
            chg_pct = (price - prev_close) / prev_close * 100
        out[code] = {
            "code": code,
            "source": "sina_b",
            "name": name,
            "price": price,
            "prev_close": prev_close,
            "open": prev_close,  # b_ 无 open, 用 prev_close 近似
            "high": high,
            "low": low,
            "chg_pct": chg_pct,
            "time": time_,
            "date": date,
        }
    return out


def _fetch_yahoo(symbol: str) -> dict:
    """Yahoo Finance API 备用源。返回 {price,prev_close,open,high,low,chg_pct,source} 或 {}。

    国内 0.55s 可达，无鉴权，仅需 UA 头。失败返回 {}（不抛异常，由调用方决定是否继续）。
    """
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=1d&interval=1m"
        r = requests.get(url, headers=_YAHOO_HEADERS, timeout=8)
        d = r.json()
        meta = d["chart"]["result"][0]["meta"]
        price = meta.get("regularMarketPrice")
        prev_close = meta.get("chartPreviousClose") or meta.get("previousClose")
        chg_pct = None
        if price is not None and prev_close and prev_close != 0:
            chg_pct = (price - prev_close) / prev_close * 100
        if price is None:
            return {}
        return {
            "price": price,
            "prev_close": prev_close,
            "open": prev_close,  # Yahoo 不返 open, 用 prev_close 近似
            "high": meta.get("regularMarketDayHigh"),
            "low": meta.get("regularMarketDayLow"),
            "chg_pct": chg_pct,
        }
    except Exception as e:  # noqa: BLE001
        print(f"[us_futures] Yahoo {symbol} 失败: {type(e).__name__} {e}", flush=True)
        return {}


def fetch_us_futures() -> dict:
    """抓外盘指数期货实时。返回 {hf_ES: {...}, ...}。失败返回 {}。

    主源：新浪 hf_+b_ 单次请求批量采（list=hf_ES,...,b_DAX,...）。
    备用源：主源未采到或 price 为空的项，用 Yahoo Finance API 逐个补采（META.yahoo_symbol）。
    失败不抛异常，返回已采到的部分（与 index_backfill._sina_global_realtime_fallback 思路一致）。
    """
    throttle()
    out = {}
    try:
        r = requests.get(_SINA_URL, headers=_SINA_HEADERS, timeout=10)
        text = r.content.decode("gbk", errors="replace")
        out.update(_parse_sina_hf(text))
        out.update(_parse_sina_b(text))
    except Exception as e:  # noqa: BLE001
        print(f"[us_futures] 主源抓取失败: {type(e).__name__} {e}", flush=True)

    # Yahoo 备用源：主源未采到 / price 为空的项逐个补采
    # sleep 0.6s 防限流（Yahoo 无 key 限流约 100/min，连续快速触发会被拉黑几分钟）
    missing = [c for c in US_FUTURES_META
               if c not in out or not out[c].get("price")]
    for code in missing:
        sym = US_FUTURES_META[code].get("yahoo_symbol")
        if not sym:
            continue
        d = _fetch_yahoo(sym)
        if d and d.get("price") is not None:
            meta = US_FUTURES_META[code]
            out[code] = {
                "code": code,
                "source": "yahoo",
                "name": meta.get("futures_name", code),
                **d,
            }
        time.sleep(0.6)  # 防Yahoo限流
    return out


if __name__ == "__main__":
    import json as _json
    print(_json.dumps(fetch_us_futures(), ensure_ascii=False, indent=2))
