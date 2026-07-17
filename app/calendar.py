"""交易日历：判断是否为 A 股交易日，缓存到本地。"""
import datetime as dt
from functools import lru_cache
from pathlib import Path

try:
    import akshare as ak
except ImportError:  # akshare 未装时降级（仅用周末启发式）
    ak = None

_CACHE_PATH = Path(__file__).absolute().parent.parent / "data" / "trade_dates.txt"


@lru_cache(maxsize=1)
def _load_trade_dates() -> set[str]:
    """返回 'YYYYMMDD' 字符串集合。首次从 akshare 拉，落盘缓存。"""
    if _CACHE_PATH.exists():
        return {line.strip() for line in _CACHE_PATH.read_text().splitlines() if line.strip()}
    if ak is None:
        return set()
    df = ak.tool_trade_date_hist_sina()
    dates = {str(d).replace("-", "") for d in df["trade_date"]}
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_PATH.write_text("\n".join(sorted(dates)))
    return dates


def refresh_trade_dates() -> set[str]:
    """强制刷新缓存（每个交易日闭市后调用，纳入新日期）。

    安全刷新：先拉新数据，成功才原子覆盖旧缓存；拉取失败则保留旧缓存，
    仅清 lru_cache 重读盘。避免网络抖动丢缓存致跨年 / 跨月判断失灵
    （scheduler 每日依赖此函数，旧缓存宁可过时不可缺失）。
    """
    if ak is None:
        # 无 akshare：仅清 lru_cache 重读盘（不删盘文件）
        _load_trade_dates.cache_clear()
        return _load_trade_dates()
    try:
        df = ak.tool_trade_date_hist_sina()
        dates = {str(d).replace("-", "") for d in df["trade_date"]}
    except Exception:
        # 拉取失败：保留旧缓存文件，仅清 lru_cache 重读
        _load_trade_dates.cache_clear()
        return _load_trade_dates()
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    # 原子写：先写临时文件再 rename，避免半写文件污染缓存
    tmp = _CACHE_PATH.with_suffix(".txt.tmp")
    tmp.write_text("\n".join(sorted(dates)))
    tmp.replace(_CACHE_PATH)
    _load_trade_dates.cache_clear()
    return _load_trade_dates()


def _to_yyyymmdd(d) -> str:
    if isinstance(d, str):
        return d.replace("-", "")
    if isinstance(d, dt.date):
        return d.strftime("%Y%m%d")
    raise TypeError(d)


def is_trading_day(d=None) -> bool:
    if d is None:
        d = dt.date.today()
    key = _to_yyyymmdd(d)
    dates = _load_trade_dates()
    if dates:
        return key in dates
    # 降级：周末非交易日
    dd = d if isinstance(d, dt.date) else dt.datetime.strptime(key, "%Y%m%d").date()
    return dd.weekday() < 5


def last_trading_day(d=None, max_lookback: int = 15) -> str:
    """返回 <= d 的最近一个交易日（YYYYMMDD）。"""
    if d is None:
        d = dt.date.today()
    cur = d if isinstance(d, dt.date) else dt.datetime.strptime(_to_yyyymmdd(d), "%Y%m%d").date()
    for _ in range(max_lookback):
        if is_trading_day(cur):
            return cur.strftime("%Y%m%d")
        cur -= dt.timedelta(days=1)
    return d.strftime("%Y%m%d") if isinstance(d, dt.date) else _to_yyyymmdd(d)


def trading_days_between(start: str, end: str) -> list[str]:
    """返回 [start, end] 区间内的交易日列表（YYYYMMDD）。"""
    s = dt.datetime.strptime(_to_yyyymmdd(start), "%Y%m%d").date()
    e = dt.datetime.strptime(_to_yyyymmdd(end), "%Y%m%d").date()
    out = []
    cur = s
    while cur <= e:
        if is_trading_day(cur):
            out.append(cur.strftime("%Y%m%d"))
        cur += dt.timedelta(days=1)
    return out


if __name__ == "__main__":
    print("今天:", dt.date.today(), "交易日?", is_trading_day())
    print("最近交易日:", last_trading_day())
