#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""路B一次性采集 62 个国证/中证行业主题指数（2026-08-07）。

复用 fetchers.collect_index + runner.upsert_index_rows。逐个采集，失败记录原因继续。
写库后即可 export 生成 static-site/data/index/*.json。

用法:
    python scripts/collect_roadb_indices.py
"""
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).absolute().parent.parent
sys.path.insert(0, str(ROOT))

from app.collector import fetchers
from app.collector.runner import upsert_index_rows
from app.db import get_conn

# 62 个新指数 id（与 indicators.yaml 路B段对应）
NEW_IDS = [
    # A组 国证(7) 新浪
    "gz_399368", "gz_399395", "gz_399396", "gz_399431", "gz_399439", "gz_399440", "gz_399365",
    # B组 中证-深交所(18) 腾讯
    "csi_399975", "csi_399986", "csi_399989", "csi_399976", "csi_399967", "csi_399971",
    "csi_399998", "csi_399808", "csi_399803", "csi_399806", "csi_399807", "csi_399970",
    "csi_399991", "csi_399994", "csi_399995", "csi_399996", "csi_399707", "csi_399811",
    # C组 中证-上交所/深交所(15) 新浪
    "csi_000510", "csi_000903", "csi_000827", "csi_000935", "csi_000998", "csi_000961",
    "csi_000805", "csi_000813", "csi_000010", "csi_000330", "csi_000673", "csi_000102",
    "csi_000680", "csi_000698", "csi_000699",
    # D组 中证指数公司(22) csindex
    "csi_931151", "csi_930050", "csi_932000", "csi_930986", "csi_H30590", "csi_931643",
    "csi_931719", "csi_930632", "csi_931892", "csi_930713", "csi_930721", "csi_930851",
    "csi_932365", "csi_932315", "csi_931752", "csi_931946", "csi_H11059", "csi_932456",
    "csi_930820", "csi_930997", "csi_H30535", "csi_H30199",
]


def main():
    cfg = fetchers.load_config()
    idx_map = {i["id"]: i for i in cfg.get("indices", [])}
    print(f"config loaded: {len(idx_map)} indices total, will collect {len(NEW_IDS)} new")

    # 从 2010-01-01 拉全量历史（和 runner.step2 400 天不同，这里首次回填要全量）
    start = "20100101"
    # end = 最新交易日（不传具体日期，让 collect_index 内部处理；csindex 需 end_date）
    import datetime as dt
    end = dt.date.today().strftime("%Y%m%d")

    ok, fail = 0, 0
    failures = []
    for i, idx_id in enumerate(NEW_IDS, 1):
        idx = idx_map.get(idx_id)
        if not idx:
            print(f"[{i}/{len(NEW_IDS)}] {idx_id}: NOT in config, skip")
            fail += 1
            failures.append((idx_id, "not in config"))
            continue
        t0 = time.time()
        try:
            rows, msg = fetchers.collect_index(idx, start, end)
            if rows:
                upsert_index_rows(rows)
                ok += 1
                elapsed = time.time() - t0
                print(f"[{i}/{len(NEW_IDS)}] {idx_id} OK: {len(rows)} rows ({elapsed:.1f}s)")
            else:
                fail += 1
                elapsed = time.time() - t0
                print(f"[{i}/{len(NEW_IDS)}] {idx_id} FAIL: {msg} ({elapsed:.1f}s)")
                failures.append((idx_id, msg))
        except Exception as e:
            fail += 1
            elapsed = time.time() - t0
            tb = traceback.format_exc()
            print(f"[{i}/{len(NEW_IDS)}] {idx_id} EXC: {e} ({elapsed:.1f}s)")
            print(tb)
            failures.append((idx_id, f"exc: {e}"))

    print("\n=== summary ===")
    print(f"ok: {ok}, fail: {fail}, total: {len(NEW_IDS)}")
    if failures:
        print("failures:")
        for fid, msg in failures:
            print(f"  {fid}: {msg}")

    # 写进度文件
    with open("/tmp/roadb-collect-result.json", "w") as f:
        import json
        json.dump({"ok": ok, "fail": fail, "total": len(NEW_IDS), "failures": failures}, f, ensure_ascii=False, indent=2)

    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
