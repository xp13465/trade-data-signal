"""外盘指数期货 -> 对应指数预期方向。

ES 期货（标普500）chg_pct -> 标普500（us_spx）预期方向；
NQ 期货（纳指100）-> 纳指100（us_ndx）；
YM 期货（道指）-> 道琼斯（us_dji）；
HSI 期货（恒指）-> 恒生指数（hsi）。
阈值 ±0.3%：>0.3 预涨，<-0.3 预跌，否则持平（每条可从 META.threshold 覆盖）。
期货↔指数收盘相关性≈0.95，亚盘实时反映对应指数开盘预期。

单一配置源：从 collector.us_futures.US_FUTURES_META 读 index_id/display_name/short/threshold
映射，无硬编码 code_map。未来扩充只改 META，计算/落地自动跟上。

落地 daily_metric 表（供历史回测/统计），同时返回 expect dict 给
intraday_snapshot 注入快照（前端"外盘指数预期"提示条读快照字段实时展示）。

metric_id 命名：us_futures_<short>_{price,chg,signal}（short 从 META 读）
  例：us_futures_es_price / us_futures_es_chg / us_futures_es_signal
      us_futures_nq_* / us_futures_ym_* / us_futures_hsi_*
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


def _expect_label(chg_pct, threshold=None):
    """chg_pct -> 预估方向标签。None 返回 None。

    threshold 默认 EXPECT_THRESHOLD，可逐条覆盖（从 META.threshold 读）。
    """
    if chg_pct is None:
        return None
    th = threshold if threshold is not None else EXPECT_THRESHOLD
    if chg_pct > th:
        return EXPECT_UP
    if chg_pct < -th:
        return EXPECT_DOWN
    return EXPECT_FLAT


def compute_expect(futures: dict) -> dict:
    """算预估方向。

    futures = {hf_ES: {...}, ...}（来自 collector.us_futures.fetch_us_futures）。
    返回同结构，每条追加 expect/index_id/display_name/relevance 字段（price 缺失的条目丢弃）。
    映射从 US_FUTURES_META 读，无硬编码。
    """
    out = {}
    for code, d in (futures or {}).items():
        if not d or d.get("price") is None:
            continue
        meta = US_FUTURES_META.get(code, {})
        chg = d.get("chg_pct")
        out[code] = {
            **d,
            "expect": _expect_label(chg, meta.get("threshold")),
            "index_id": meta.get("index_id"),
            "display_name": meta.get("display_name"),
            "relevance": meta.get("relevance"),
        }
    return out


def save_to_db(date: str, expect: dict) -> int:
    """落地 daily_metric（UPSERT）。date=YYYYMMDD（北京采集日）。

    返回写入条数。expect 为 compute_expect 的返回值。
    short 从 US_FUTURES_META 读（无硬编码 code_map，未来扩充自动跟上）。
    """
    rows = []
    now = datetime.now().isoformat()
    for code, meta in US_FUTURES_META.items():
        short = meta.get("short")
        if not short:
            continue
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
