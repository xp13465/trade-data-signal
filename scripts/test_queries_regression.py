#!/usr/bin/env python3
"""回归测试：对比 API 返回（queries.xxx 直调，模拟 main.py）vs export JSON（export.py 生成）。

14端点字段级diff，确保重构后前端无破坏。

已知差异（非bug，原样保留）：
- a_stock: API 无 etfs / JSON 有 etfs -> 比较前从 JSON 移除 etfs
- index_detail: API 无 etfs / JSON 有 etfs -> 比较前从 JSON 移除 etfs
- sentiment: API 有 futures / JSON 无 futures -> 比较前从 API 移除 futures
- summary_history: API 返回 {items,total,offset,limit} / JSON 也有(queries统一) -> 应一致

2bug修（预期变化）：
- rotation: latest 统一用 compute_rotation()（含门控），JSON 原直接SQL无门控 -> 可能diff
- stats_all: 统一用 sigstats.compute() 现算 -> 应一致（export 原也是 compute）
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).absolute().parent.parent
sys.path.insert(0, str(ROOT))

from app import queries
from app.db import get_conn
from app.collector.fetchers import load_config

DATA_DIR = ROOT / "static-site" / "data"


def load_json(name):
    p = DATA_DIR / name
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def deep_diff(a, b, path=""):
    """递归对比两个 JSON 结构，返回差异列表。"""
    diffs = []
    # numpy 类型统一转 Python 原生（compute_rotation 返回 float64，json.dumps 后变 float）
    try:
        import numpy as np
        if isinstance(a, np.generic):
            a = a.item()
        if isinstance(b, np.generic):
            b = b.item()
    except ImportError:
        pass
    if type(a) != type(b):
        # float vs int 等数值类型容错：值相等即通过
        if isinstance(a, (int, float)) and isinstance(b, (int, float)) and a == b:
            return diffs
        diffs.append(f"{path}: type mismatch {type(a).__name__} vs {type(b).__name__}")
        return diffs
    if isinstance(a, dict):
        keys_a = set(a.keys())
        keys_b = set(b.keys())
        for k in keys_a - keys_b:
            diffs.append(f"{path}.{k}: only in API (missing in JSON)")
        for k in keys_b - keys_a:
            diffs.append(f"{path}.{k}: only in JSON (missing in API)")
        for k in keys_a & keys_b:
            diffs.extend(deep_diff(a[k], b[k], f"{path}.{k}"))
    elif isinstance(a, list):
        if len(a) != len(b):
            diffs.append(f"{path}: list length {len(a)} vs {len(b)}")
        else:
            for i, (x, y) in enumerate(zip(a, b)):
                diffs.extend(deep_diff(x, y, f"{path}[{i}]"))
    else:
        if a != b:
            diffs.append(f"{path}: value {a!r} vs {b!r}")
    return diffs


def remove_etfs(obj):
    """递归移除 etfs 字段（a_stock/index_detail 的已知差异）。"""
    if isinstance(obj, dict):
        obj.pop("etfs", None)
        for v in obj.values():
            remove_etfs(v)
    elif isinstance(obj, list):
        for item in obj:
            remove_etfs(item)


def run_tests():
    cfg = load_config()
    conn = get_conn()
    all_pass = True

    tests = [
        # (name, api_fn, json_name, preprocess_api, preprocess_json)
        ("overview", lambda: queries.overview(conn, cfg), "overview.json", None, None),
        ("a_stock(1y)", lambda: queries.a_stock(conn, cfg, *queries.range_for("1y")),
         "a-stock-1y.json", None, remove_etfs),
        ("hk(1y)", lambda: queries.hk(conn, cfg, *queries.range_for("1y")),
         "hk-1y.json", None, None),
        ("global(1y)", lambda: queries.global_market(conn, cfg, *queries.range_for("1y")),
         "global-1y.json", None, None),
        ("sentiment(1y)", lambda: queries.sentiment(conn, cfg, *queries.range_for("1y")),
         "sentiment-1y.json", lambda x: x.pop("futures", None), None),
        ("industry(1y)", lambda: queries.industry(conn, cfg, *queries.range_for("1y")),
         "industry-1y.json", None, None),
        ("futures", lambda: queries.futures_data(conn), "futures.json", None, None),
        ("ad_line", lambda: queries.ad_line(conn), "ad_line.json", None, None),
        ("volume_ratio", lambda: queries.volume_ratio(conn), "volume_ratio.json", None, None),
        ("new_high_low", lambda: queries.new_high_low(conn), "new_high_low.json", None, None),
        ("ma_alignment", lambda: queries.ma_alignment(conn), "ma_alignment.json", None, None),
        ("rotation", lambda: queries.rotation(conn), "rotation.json", None, None),
        ("summary_history", lambda: queries.summary_history(conn, 0, 90),
         "summary_history.json", None, None),
        ("intraday_snapshot", lambda: queries.intraday_snapshot(),
         "intraday_snapshot.json", None, None),
        ("index_detail(sh)", lambda: queries.index_detail(conn, cfg, "sh", *queries.range_for("all")),
         "index/sh-all.json", None, remove_etfs),
    ]

    for name, api_fn, json_name, pre_api, pre_json in tests:
        print(f"\n=== {name} vs {json_name} ===")
        try:
            api_result = api_fn()
        except Exception as e:
            print(f"  FAIL: API call error: {e}")
            all_pass = False
            continue

        json_result = load_json(json_name)
        if json_result is None:
            print(f"  SKIP: {json_name} not found")
            continue

        # Apply preprocessing for known differences
        if pre_api:
            pre_api(api_result)
        if pre_json:
            pre_json(json_result)

        diffs = deep_diff(api_result, json_result, name)
        if not diffs:
            print(f"  PASS: identical ({len(json.dumps(api_result))} bytes)")
        else:
            print(f"  DIFF ({len(diffs)} differences):")
            for d in diffs[:10]:
                print(f"    {d}")
            if len(diffs) > 10:
                print(f"    ... and {len(diffs) - 10} more")
            all_pass = False

    conn.close()
    print(f"\n{'='*60}")
    print(f"{'ALL PASS' if all_pass else 'SOME DIFFS (check above)'}")
    return all_pass


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
