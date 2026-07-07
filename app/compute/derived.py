"""派生公式指标：按 config 中 type=derived + formula 计算，入 daily_metric。

例如封板率 = 1 - a_width_zhaban_rate。
formula 里引用的 token 若是 config 中已登记的 metric_id，则替换为该指标序列后求值。
公式来自本仓库 config（非外部输入），用受限命名空间 eval。
"""
from datetime import datetime

import pandas as pd

from ..collector.fetchers import load_config
from ..db import get_conn
from .normalize import load_metric_series


def compute_derived_formulas() -> dict[str, pd.Series]:
    cfg = load_config()
    ids = [m["id"] for m in cfg.get("metrics", []) if m.get("id")]
    out: dict[str, pd.Series] = {}
    for m in cfg.get("metrics", []):
        if m.get("type") != "derived" or not m.get("formula"):
            continue
        formula = m["formula"]
        ns: dict[str, pd.Series] = {}
        for ref in ids:
            if ref in formula:
                s = load_metric_series(ref)
                if not s.empty:
                    ns[ref] = s
        try:
            result = eval(formula, {"__builtins__": {}}, ns)  # noqa: S307
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(result, pd.Series) or result.empty:
            continue
        out[m["id"]] = result
    return out


def store_derived(out: dict[str, pd.Series]) -> int:
    now = datetime.now().isoformat()
    conn = get_conn()
    n = 0
    for mid, s in out.items():
        rows = [(d, mid, float(v), "derived", now) for d, v in s.dropna().items()]
        if not rows:
            continue
        conn.executemany(
            "INSERT INTO daily_metric (date, metric_id, value, source, updated_at) "
            "VALUES (?,?,?,?,?) "
            "ON CONFLICT(date, metric_id) DO UPDATE SET value=excluded.value, "
            "source=excluded.source, updated_at=excluded.updated_at "
            "WHERE daily_metric.source != 'manual'",
            rows,
        )
        n += len(rows)
    conn.commit()
    conn.close()
    return n
