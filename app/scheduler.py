"""每日定时入口：刷新交易日历 → 交易日判断 → 采集 → 计算 → 告警检查。"""
import sys
from datetime import datetime

from .calendar import is_trading_day, last_trading_day, refresh_trade_dates
from .collector import runner as collect_runner
from .compute import runner as compute_runner
from .db import get_conn


def run(date: str | None = None):
    today = date or datetime.now().strftime("%Y%m%d")
    # 先刷新交易日历缓存：跨年时（如 2027-01-04 首个交易日）旧缓存缺新年日期，
    # 会导致 is_trading_day 误判「非交易日」跳过当日采集，且 collect_snapshot 守卫的
    # last_trading_day() 仍停在旧年最后一日 → 当日快照被错误 skip。
    # 失败不致命：降级沿用旧缓存（旧缓存可能缺新年日期，但优于崩溃）。
    try:
        refresh_trade_dates()
    except Exception as e:  # noqa: BLE001
        print(f"  ⚠ 刷新 trade_dates 失败，沿用旧缓存：{e}")
    if not is_trading_day(today):
        print(f"{today} 非交易日，跳过")
        return
    print(f"=== 每日任务 {today} 开始 ===")
    collect_runner.run(today)
    compute_runner.run()
    _check_alerts(today)
    print("=== 每日任务完成 ===")


def _check_alerts(date: str):
    d = last_trading_day(date)
    conn = get_conn()
    rows = conn.execute(
        "SELECT score_id, value, is_freeze, is_overheat FROM score_daily WHERE date=?", (d,)
    ).fetchall()
    conn.close()
    for r in rows:
        if r["is_freeze"]:
            print(f"  ⚠ {r['score_id']}={r['value']:.1f} 冰点")
        if r["is_overheat"]:
            print(f"  ⚠ {r['score_id']}={r['value']:.1f} 过热")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else None)
