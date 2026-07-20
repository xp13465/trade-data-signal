#!/usr/bin/env python3
"""C7 P4-β §9.6 静态化: 预生成 9 宽基 + 31 申万行业 = 40 个 alert_analyze 静态快照。

输出: static-site/data/alert_analyze_{iid}.json
  - 宽基: alert_analyze_hs300.json / alert_analyze_sz50.json / ...
  - 行业: alert_analyze_sw_801080.json / ...

每个 JSON 结构同 /api/alert/analyze 唯一匹配时的 result 字段:
  {
    "target_id": "hs300",
    "target_type": "index",
    "target_name": "沪深300",
    "alert": {date, high, low, high_level, low_level, dims(H1-H8/L1-L8), adapt},
    "reason": {dim_hits, data_thresholds, history_analogy, human_text, compliance_footer, ...}
  }

异常处理: 单个 iid 失败写 {"target_id": iid, "error": msg} 不中断。

用法:
  .venv/bin/python scripts/export_alert_analyze.py
"""
from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.alert_match import PREGEN_TARGETS, _load_index_name_map  # noqa: E402
from app.alert_reason import build_reason  # noqa: E402
from app.alert_score import compute_alert_for_target  # noqa: E402

DATA_DIR = ROOT / "static-site" / "data"


def export_one(target_id: str, target_type: str, name_map: dict[str, str]) -> tuple[dict, float]:
    """单标的算分 + 原因, 返回 (result_dict, 耗时秒)。"""
    t0 = time.time()
    alert = compute_alert_for_target(target_id, target_type)
    reason = build_reason(target_id, target_type, alert_result=alert)
    target_name = name_map.get(target_id, target_id)
    result = {
        "target_id": target_id,
        "target_type": target_type,
        "target_name": target_name,
        "alert": alert,
        "reason": reason,
    }
    return result, time.time() - t0


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    name_map = _load_index_name_map()
    print(f"-> 预生成 {len(PREGEN_TARGETS)} 个 alert_analyze 静态快照 ...")
    ok, err = 0, 0
    t_start = time.time()
    for i, (iid, ttype) in enumerate(PREGEN_TARGETS, 1):
        out_path = DATA_DIR / f"alert_analyze_{iid}.json"
        try:
            result, dt = export_one(iid, ttype, name_map)
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            alert = result.get("alert", {})
            high = alert.get("high")
            low = alert.get("low")
            print(f"  [{i:2d}/{len(PREGEN_TARGETS)}] {iid:14s} type={ttype} "
                  f"high={high} low={low} ({dt:.1f}s) -> {out_path.name}")
            ok += 1
        except Exception as e:
            tb = traceback.format_exc(limit=3)
            err_payload = {
                "target_id": iid,
                "target_type": ttype,
                "error": f"{type(e).__name__}: {e}",
                "traceback": tb,
            }
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(err_payload, f, ensure_ascii=False, indent=2)
            print(f"  [{i:2d}/{len(PREGEN_TARGETS)}] {iid:14s} FAILED: {type(e).__name__}: {e}")
            err += 1
    print(f"\n✓ 完成: ok={ok} err={err} 耗时={time.time() - t_start:.1f}s")
    print(f"  输出目录: {DATA_DIR}/alert_analyze_*.json")


if __name__ == "__main__":
    main()
