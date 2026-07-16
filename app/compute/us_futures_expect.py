"""美股期货 -> 美股指数预期方向。

ES 期货（标普500）chg_pct -> 标普500（us_spx）预期方向；
NQ 期货（纳指100）chg_pct -> 纳指100（us_ndx）预期方向。
阈值 ±0.3%：>0.3 预涨，<-0.3 预跌，否则持平。
ES↔标普500 收盘相关性≈0.95，期货亚盘实时反映美股当晚预期。

落地 daily_metric 表（供历史回测/统计），同时返回 expect dict 给
intraday_snapshot 注入快照（前端"美股预期"提示条读快照字段实时展示）。

metric_id 命名：
  us_futures_es_price / us_futures_es_chg / us_futures_es_signal
  us_futures_nq_price / us_futures_nq_chg / us_futures_nq_signal
signal 数值：1=预涨，0=持平，-1=预跌
"""
from datetime import datetime

from ..collector.us_futures import EXPECT_THRESHOLD, US_FUTURES_META
from ..db import get_conn

EXPECT_UP = "预涨"
EXPECT_DOWN = "预跌"
EXPECT_FLAT = "持平"

# 预估方向 -> 数值（落地 daily_metric signal 用）
_EXPECT_TO_NUM = {EXPECT_UP: 1, EXPECT_FLAT: 0, EXPECT_DOWN: -1}


def _expect_label(chg_pct):
    """chg_pct -> 预估方向标签。None 返回 None。"""
    if chg_pct is None:
        return None
    if chg_pct > EXPECT_THRESHOLD:
        return EXPECT_UP
    if chg_pct < -EXPECT_THRESHOLD:
        return EXPECT_DOWN
    return EXPECT_FLAT


def compute_expect(futures: dict) -> dict:
    """算预估方向。

    futures = {hf_ES: {...}, hf_NQ: {...}}（来自 collector.us_futures.fetch_us_futures）。
    返回同结构，每条追加 expect/target/target_name 字段（price 缺失的条目丢弃）。
    """
    out = {}
    for code, d in (futures or {}).items():
        if not d or d.get("price") is None:
            continue
        meta = US_FUTURES_META.get(code, {})
        chg = d.get("chg_pct")
        out[code] = {
            **d,
            "expect": _expect_label(chg),
            "target": meta.get("target"),
            "target_name": meta.get("target_name"),
        }
    return out


def save_to_db(date: str, expect: dict) -> int:
    """落地 daily_metric（UPSERT）。date=YYYYMMDD（北京采集日）。

    返回写入条数。expect 为 compute_expect 的返回值。
    """
    rows = []
    code_map = {"hf_ES": "es", "hf_NQ": "nq"}
    now = datetime.now().isoformat()
    for code, short in code_map.items():
        d = expect.get(code) if expect else None
        if not d or d.get("price") is None:
            continue
        rows.append((date, f"us_futures_{short}_price", d["price"], "sina_hf", now))
        rows.append((date, f"us_futures_{short}_chg", d.get("chg_pct"), "sina_hf", now))
        sig = _EXPECT_TO_NUM.get(d.get("expect"))
        rows.append((date, f"us_futures_{short}_signal", sig, "compute", now))
    if not rows:
        return 0
    conn = get_conn()
    conn.executemany(
        "INSERT INTO daily_metric (date, metric_id, value, source, updated_at) "
        "VALUES (?,?,?,?,?) "
        "ON CONFLICT(date, metric_id) DO UPDATE SET "
        "value=excluded.value, source=excluded.source, updated_at=excluded.updated_at",
        rows,
    )
    conn.commit()
    conn.close()
    return len(rows)


if __name__ == "__main__":
    import json as _json
    from ..collector.us_futures import fetch_us_futures

    ex = compute_expect(fetch_us_futures())
    print(_json.dumps(ex, ensure_ascii=False, indent=2))
