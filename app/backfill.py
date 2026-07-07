"""历史回填：宽度指标（涨停板池系列）按交易日循环回填，可断点续跑。"""
import sys
import datetime as dt

import akshare as ak

from .db import get_conn
from .calendar import trading_days_between, last_trading_day
from .collector.base import safe_call, log_collect


def _have(metric_id: str, date: str) -> bool:
    conn = get_conn()
    r = conn.execute(
        "SELECT 1 FROM daily_metric WHERE metric_id=? AND date=?", (metric_id, date)
    ).fetchone()
    conn.close()
    return r is not None


def _upsert(date: str, metric_id: str, value):
    if value is None:
        return
    conn = get_conn()
    conn.execute(
        "INSERT INTO daily_metric (date, metric_id, value, source, updated_at) "
        "VALUES (?,?,?,?,?) ON CONFLICT(date, metric_id) DO UPDATE SET "
        "value=excluded.value, source=excluded.source, updated_at=excluded.updated_at",
        (date, metric_id, float(value), "akshare", dt.datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def backfill_width(days: int = 270, verbose: bool = True):
    """回填涨停数/跌停数/连板高度/炸板率/打板溢价。"""
    end = last_trading_day()
    start = (dt.datetime.strptime(end, "%Y%m%d") - dt.timedelta(days=days)).strftime("%Y%m%d")
    dates = trading_days_between(start, end)
    if verbose:
        print(f"回填宽度 {start}~{end}，共 {len(dates)} 个交易日")
    n = skipped = failed = 0
    for i, d in enumerate(dates):
        if _have("a_width_zt_count", d):
            skipped += 1
            continue
        try:
            zt = safe_call(ak.stock_zt_pool_em, date=d)
            dt_ = safe_call(ak.stock_zt_pool_dtgc_em, date=d)
            zbgc = safe_call(ak.stock_zt_pool_zbgc_em, date=d)
            prev = safe_call(ak.stock_zt_pool_previous_em, date=d)

            zt_count = len(zt) if not isinstance(zt, Exception) and zt is not None else 0
            dt_count = len(dt_) if not isinstance(dt_, Exception) and dt_ is not None else 0
            zbgc_count = len(zbgc) if not isinstance(zbgc, Exception) and zbgc is not None else 0

            # 连板高度
            lianban = None
            if not isinstance(zt, Exception) and zt is not None and "连板数" in zt.columns:
                lianban = float(zt["连板数"].max())
            # 炸板率 = 炸板 / (涨停 + 炸板)
            denom = zt_count + zbgc_count
            zhaban_rate = zbgc_count / denom if denom > 0 else None
            # 打板溢价 = 昨涨停今平均涨跌幅
            daban = None
            if not isinstance(prev, Exception) and prev is not None and "涨跌幅" in prev.columns and len(prev):
                daban = float(prev["涨跌幅"].mean())

            _upsert(d, "a_width_zt_count", zt_count or None)
            _upsert(d, "a_width_dt_count", dt_count or None)
            _upsert(d, "a_width_max_lianban", lianban)
            _upsert(d, "a_width_zhaban_rate", zhaban_rate)
            _upsert(d, "a_width_daban_premium", daban)
            n += 1
            if verbose and (i % 10 == 0):
                print(f"  {i+1}/{len(dates)}  {d}: zt={zt_count} dt={dt_count} 连板={lianban} 炸板率={zhaban_rate and round(zhaban_rate,3)}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            log_collect(d, "backfill_width", "error", str(e))
    if verbose:
        print(f"回填完成: 新增 {n} 天，跳过 {skipped}，失败 {failed}")
    return n


if __name__ == "__main__":
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 270
    backfill_width(days)
