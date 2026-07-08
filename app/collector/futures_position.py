"""期货机构持仓数据采集器。

采集 CFFEX 股指期货（IF/IC/IH/IM）前20名会员持仓排名数据，
按品种汇总计算净多空持仓指标，写入 futures_position 表。

用法:
    python -m app.collector.futures_position daily 20260708
    python -m app.collector.futures_position backfill --start 20240101 --end 20260708
"""
import sys
import datetime as dt

from .fetchers import fetch_futures_position
from ..db import get_conn
from ..calendar import is_trading_day

VARIETIES = ['IF', 'IC', 'IH', 'IM']


def _now():
    return dt.datetime.now().isoformat()


def _upsert(conn, date: str, variety: str, role: str,
            total_long: float, total_short: float,
            net_position: float, net_ratio: float, long_chg: float, short_chg: float,
            contract_count: int):
    conn.execute(
        "INSERT INTO futures_position "
        "(date, variety, role, total_long, total_short, net_position, net_ratio, "
        " long_chg, short_chg, contract_count, source, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(date, variety, role) DO UPDATE SET "
        "total_long=excluded.total_long, total_short=excluded.total_short, "
        "net_position=excluded.net_position, net_ratio=excluded.net_ratio, "
        "long_chg=excluded.long_chg, short_chg=excluded.short_chg, "
        "contract_count=excluded.contract_count, source=excluded.source, "
        "created_at=excluded.created_at",
        (date, variety, role, total_long, total_short, net_position, net_ratio,
         long_chg, short_chg, contract_count, "akshare", _now()),
    )


def collect_daily(date: str) -> dict:
    """采集单日期货持仓数据，按角色 × 品种汇总并写入 DB。

    fetcher 返回: {role: {variety: {total_long, total_short, long_chg, short_chg, contract_count}}}

    返回: {role: {variety: {total_long, total_short, net_position, net_ratio, ...}, ...}, ...}
    """
    data = fetch_futures_position(date)
    if not data:
        print(f"[futures_position] {date}: no data (non-trading day or API error)")
        return {}

    result = {}
    conn = get_conn()
    try:
        for role, agg in data.items():
            role_result = {}

            # 写入各品种
            for variety in VARIETIES:
                if variety in agg:
                    a = agg[variety]
                    denom = a['total_long'] + a['total_short']
                    net = a['total_long'] - a['total_short']
                    ratio = net / denom if denom > 0 else 0.0
                    _upsert(conn, date, variety, role,
                            a['total_long'], a['total_short'],
                            net, ratio,
                            a['long_chg'], a['short_chg'],
                            a['contract_count'])
                    role_result[variety] = {
                        'total_long': a['total_long'], 'total_short': a['total_short'],
                        'net_position': net, 'net_ratio': ratio,
                        'long_chg': a['long_chg'], 'short_chg': a['short_chg'],
                        'contract_count': a['contract_count'],
                    }

            # 综合：汇总 IF+IC+IH+IM 四个品种
            total_long = sum(agg[v]['total_long'] for v in VARIETIES if v in agg)
            total_short = sum(agg[v]['total_short'] for v in VARIETIES if v in agg)
            long_chg = sum(agg[v]['long_chg'] for v in VARIETIES if v in agg)
            short_chg = sum(agg[v]['short_chg'] for v in VARIETIES if v in agg)
            contract_count = sum(agg[v]['contract_count'] for v in VARIETIES if v in agg)
            denom = total_long + total_short
            net = total_long - total_short
            ratio = net / denom if denom > 0 else 0.0
            _upsert(conn, date, '综合', role,
                    total_long, total_short, net, ratio,
                    long_chg, short_chg, contract_count)
            role_result['综合'] = {
                'total_long': total_long, 'total_short': total_short,
                'net_position': net, 'net_ratio': ratio,
                'long_chg': long_chg, 'short_chg': short_chg,
                'contract_count': contract_count,
            }

            result[role] = role_result

        conn.commit()
    finally:
        conn.close()

    total_varieties = sum(len(v) for v in result.values())
    roles_str = ', '.join(result.keys())
    print(f"[futures_position] {date}: collected {total_varieties} variety-role combos "
          f"across roles ({roles_str})")
    return result


def backfill_history(start_date: str, end_date: str) -> dict:
    """从 start_date 到 end_date 逐日回填（只填交易日，非交易日/异常跳过）。

    返回: {ok: int, skip: int, fail: int}
    """
    s = dt.datetime.strptime(start_date, "%Y%m%d").date()
    e = dt.datetime.strptime(end_date, "%Y%m%d").date()
    ok = skip = fail = 0
    cur = s
    while cur <= e:
        d = cur.strftime("%Y%m%d")
        if not is_trading_day(cur):
            skip += 1
            cur += dt.timedelta(days=1)
            continue
        try:
            res = collect_daily(d)
            if res:
                ok += 1
            else:
                skip += 1
        except Exception as ex:
            fail += 1
            print(f"[futures_position] {d}: error {ex}")
        cur += dt.timedelta(days=1)
    print(f"[futures_position] backfill {start_date}~{end_date}: "
          f"ok={ok} skip={skip} fail={fail}")
    return {"ok": ok, "skip": skip, "fail": fail}


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    if cmd == "daily":
        d = sys.argv[2] if len(sys.argv) > 2 else dt.date.today().strftime("%Y%m%d")
        collect_daily(d)
    elif cmd == "backfill":
        args = {}
        argv = sys.argv[2:]
        i = 0
        while i < len(argv):
            a = argv[i]
            if a.startswith("--start"):
                if "=" in a:
                    args["start_date"] = a.split("=", 1)[1]
                elif i + 1 < len(argv):
                    args["start_date"] = argv[i + 1]
                    i += 1
            elif a.startswith("--end"):
                if "=" in a:
                    args["end_date"] = a.split("=", 1)[1]
                elif i + 1 < len(argv):
                    args["end_date"] = argv[i + 1]
                    i += 1
            i += 1
        start_date = args.get("start_date", "20240101")
        end_date = args.get("end_date", dt.date.today().strftime("%Y%m%d"))
        backfill_history(start_date, end_date)
    else:
        print("Usage: python -m app.collector.futures_position <daily|backfill> [--start YYYYMMDD] [--end YYYYMMDD]")
        print("  daily YYYYMMDD      采集单日数据")
        print("  backfill --start YYYYMMDD --end YYYYMMDD  回填历史数据")