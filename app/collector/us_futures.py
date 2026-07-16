"""美股期货 ES/NQ 实时采集（新浪 hf_ 外盘期货，亚盘实时免费）。

背景：A 股收盘时美股未开盘（北京时差晚 21:30 才开盘），用户看不到美股当晚方向。
ES 期货（标普500）↔ 标普500 收盘相关性≈0.95，NQ（纳指100）↔ 纳指100 同理。
CME GLOBEX 电子盘亚盘（北京白天）仍在交易，ES/NQ 实时价反映美股当晚预期方向。

数据源：新浪 http://hq.sinajs.cn/list=hf_ES,hf_NQ
- 需 Referer: https://finance.sina.com.cn 头（否则返回空）
- GBK 解码
- 字段映射（实测 2026-07-15）：
    var hq_str_hf_ES="price,bid,ask,open,high,low,time,prev_close,prev_settle2,
                      ,vol,oi,date,name,0";
    [0]=price 当前价
    [1]=bid 买价（常空）
    [2]=ask 卖价
    [3]=open 开盘
    [4]=high 最高
    [5]=low 最低
    [6]=time 时间(HH:MM:SS)
    [7]=prev_close 昨结算价（期货涨跌幅基准，行业惯例用昨结算）
    [8]=prev_close2 昨收（≈[7]，仅作参考）
    [9..11]=量/持仓等
    [12]=date 日期(YYYY-MM-DD，CME 合约交易日)
    [13]=name 名称
chg_pct = (price - prev_close[7]) / prev_close[7] * 100
"""
import re

import requests

from .base import UA, throttle

_SINA_URL = "http://hq.sinajs.cn/list=hf_ES,hf_NQ"
_SINA_HEADERS = {"User-Agent": UA, "Referer": "https://finance.sina.com.cn"}

# 期货代码 -> 元信息（展示名 + 对应美股指数 index_id）
US_FUTURES_META = {
    "hf_ES": {"name": "标普500期货", "target": "us_spx", "target_name": "标普500"},
    "hf_NQ": {"name": "纳指100期货", "target": "us_ndx", "target_name": "纳斯达克100"},
}

# 预估方向阈值：|chg_pct| > 0.3% 判定预涨/预跌，否则持平
EXPECT_THRESHOLD = 0.3

_LINE_RE = re.compile(r'var\s+hq_str_(hf_\w+)\s*=\s*"([^"]*)"')


def _parse_sina_hf(text: str) -> dict:
    """解析新浪 hf_ 外盘期货返回（已 GBK 解码后的文本）。

    返回 {hf_ES: {code,name,price,prev_close,open,high,low,chg_pct,time,date}, ...}。
    """
    out = {}
    for line in text.strip().split(";"):
        line = line.strip()
        if not line:
            continue
        m = _LINE_RE.match(line)
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
            "name": vals[13].strip() if len(vals) > 13 and vals[13].strip() else meta.get("name", code),
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


def fetch_us_futures() -> dict:
    """抓 ES/NQ 期货实时。返回 {hf_ES: {...}, hf_NQ: {...}}。失败返回 {}。

    单次请求同时抓两只（list=hf_ES,hf_NQ），新浪支持批量。
    """
    throttle()
    try:
        r = requests.get(_SINA_URL, headers=_SINA_HEADERS, timeout=10)
        text = r.content.decode("gbk", errors="replace")
        return _parse_sina_hf(text)
    except Exception as e:  # noqa: BLE001
        print(f"[us_futures] 抓取失败: {type(e).__name__} {e}", flush=True)
        return {}


if __name__ == "__main__":
    import json as _json
    print(_json.dumps(fetch_us_futures(), ensure_ascii=False, indent=2))
