"""腾讯财经实时行情（不封 IP，GBK，~分隔 88 字段）。抄自 a-stock-data SKILL.md。

用于换手率等腾讯独有字段（mootdx 无换手率、sina 全A无换手率列）。
"""
import requests

from .base import throttle


def tencent_quote(codes: list[str]) -> dict[str, dict]:
    """批量拉腾讯实时行情。

    codes: ['688017', '000001']（也支持指数 sh000001/sz399006、ETF）。
    返回 {code: {name, price, change_pct, turnover_pct, pe_ttm, mcap_yi, pb, ...}}。
    """
    prefixed = []
    for c in codes:
        if c.startswith(("6", "9")):
            prefixed.append(f"sh{c}")
        elif c.startswith("8"):
            prefixed.append(f"bj{c}")
        else:
            prefixed.append(f"sz{c}")
    url = "https://qt.gtimg.cn/q=" + ",".join(prefixed)
    throttle()
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
    data = r.content.decode("gbk")
    result = {}
    for line in data.strip().split(";"):
        if not line.strip() or "=" not in line or '"' not in line:
            continue
        key = line.split("=")[0].split("_")[-1]
        vals = line.split('"')[1].split("~")
        if len(vals) < 53:
            continue
        code = key[2:]

        def f(i):
            try:
                return float(vals[i])
            except (IndexError, ValueError):
                return 0.0

        result[code] = {
            "name": vals[1],
            "price": f(3),
            "last_close": f(4),
            "change_pct": f(32),
            "turnover_pct": f(38),
            "pe_ttm": f(39),
            "amplitude_pct": f(43),
            "mcap_yi": f(44),
            "float_mcap_yi": f(45),
            "pb": f(46),
        }
    return result


def fetch_index_turnover(code: str = "000001") -> float:
    """指数换手率（%）。code='000001'→上证指数。返回当日实时换手率。"""
    q = tencent_quote([code])
    if code in q:
        return q[code]["turnover_pct"]
    return None
