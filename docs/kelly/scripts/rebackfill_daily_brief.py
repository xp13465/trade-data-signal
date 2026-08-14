# ============================================================
# 用途: AI预测命中口径 0.1→0.5 后, 历史命中重刷脚本(daily_brief_history.json 重判)
# 日期/来源: 2026-08-14 / tmp
# 结论: HIT_THRESHOLD 0.1→0.5(flat 容忍带 ±0.5%), 历史命中 0/3→2/3
# 依赖: scripts/gen_daily_brief.py(reclassify_all_hits/_history_stats/HISTORY_LIMIT)
# 输入/输出: 读 history json, 只改判定字段重算 stats, 幂等
# 复现: python3 rebackfill_daily_brief.py <path-to-history.json>
# 注意: 原文件依赖 scripts/gen_daily_brief.py, 需在仓库根运行
# ============================================================
"""重刷 daily_brief_history.json:按当前 HIT_THRESHOLD 重判历史命中 + 重算 stats。
用法: python rebackfill_daily_brief.py <path-to-history.json>
只改判定字段,不动 direction/pct 等原始断言。幂等。"""
import sys, json
sys.path.insert(0, "/Users/linhuichen/code/trade/scripts")
from gen_daily_brief import reclassify_all_hits, _history_stats, HISTORY_LIMIT

path = sys.argv[1]
d = json.load(open(path, encoding="utf-8"))
items = d["items"]
reclassify_all_hits(items)
stats = _history_stats(items)
out = {"items": items, "total": len(items), "offset": 0, "limit": HISTORY_LIMIT, "stats": stats}
json.dump(out, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"{path}: stats={stats}")
