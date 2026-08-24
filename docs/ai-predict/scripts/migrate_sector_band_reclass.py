#!/usr/bin/env python3
"""migrate_sector_band_reclass.py - 一次性迁移:按 R2「板块层波动率自适应带宽」新口径重刷历史命中(2026-08-24)。

目的:
  R2 上线后,backfill_hits 只对未回填条目生效;历史已回填条目的 sector_hits 仍是旧窄口径
  (AI 原始区间宽度≤0.5pp,数学趋零全脱靶)。本脚本调 gen_daily_brief.reclassify_all_hits(
  history, db_path=生产 sentiment.db) 按「有效判定带=max(median(|pct|,N=5)×k=2.0, min_w=0.3)」
  新口径重算全部已回填条目的 sector_hits(每项保留 raw_hit 旧窄口径对照),并重算 stats。

方法:
  1) 备份原 history 到同目录 .bak-<ts>;
  2) reclassify_all_hits(items, db_path)(单一实现与 backfill_hits 共用,防口径分叉);
  3) 重算 stats(_history_stats)写回;
  4) 打印前后对照(板块层命中数变化 + direction 整体命中变化)。

输入依赖:
  - static-site/data/daily_brief_history.json(默认 git 树 trade;--tree data 切生产树 trade-data)
  - /Users/linhuichen/code/trade-data/data/sentiment.db(index_daily sw_* 序列)

复现命令:
  python3 docs/ai-predict/scripts/migrate_sector_band_reclass.py            # git 树
  python3 docs/ai-predict/scripts/migrate_sector_band_reclass.py --tree data  # 生产树
数据截止:2026-08-24(运行日)。关键口径:N=5 / k=2.0 / min_w=0.3(校准见 calibrate_sector_band.py);
§22 注明:两树各刷一份,R2 线上生效由主控 deploy 链(git 树→R2/CF)完成。
"""
import argparse
import json
import shutil
import sys
import time
from pathlib import Path

TRADE = Path("/Users/linhuichen/code/trade")
TRADE_DATA = Path("/Users/linhuichen/code/trade-data")
DB = TRADE_DATA / "data" / "sentiment.db"

sys.path.insert(0, str(TRADE / "scripts"))
from gen_daily_brief import _history_stats, reclassify_all_hits  # noqa: E402


def _sector_summary(items: list[dict]) -> tuple[int, int, int]:
    """返回(板块项总数, hit=True 数, hit=False 数)(只统计可判定项)。"""
    tot = t_hit = f_hit = 0
    for it in items:
        for s in ((it.get("meta") or {}).get("hit") or {}).get("sector_hits") or []:
            if s.get("hit") is None:
                continue
            tot += 1
            t_hit += 1 if s.get("hit") else 0
            f_hit += 0 if s.get("hit") else 1
    return tot, t_hit, f_hit


def main() -> int:
    ap = argparse.ArgumentParser(description="R2 自适应带宽新口径一次性重刷 history sector_hits")
    ap.add_argument("--tree", choices=["git", "data"], default="git",
                    help="刷哪棵树: git=trade(上线源,默认) / data=trade-data(生产树)")
    ap.add_argument("--dry-run", action="store_true", help="只打印前后对照不写盘")
    args = ap.parse_args()

    root = TRADE if args.tree == "git" else TRADE_DATA
    hp = root / "static-site" / "data" / "daily_brief_history.json"
    if not hp.exists() or not DB.exists():
        print(f"[migrate] 输入缺失: {hp} 或 {DB}", file=sys.stderr)
        return 1

    obj = json.loads(hp.read_text(encoding="utf-8"))
    items = obj.get("items") or []
    before = _sector_summary(items)
    before_stats = obj.get("stats")

    reclassify_all_hits(items, db_path=DB)

    after = _sector_summary(items)
    # stats 重算(与 gen_daily_brief 写链同函数,保证口径一致)
    obj["stats"] = _history_stats(items)

    print(f"[migrate] tree={args.tree} path={hp}")
    print(f"[migrate] 条目数 {len(items)},已回填条目按新口径重算")
    print(f"[migrate] 板块层: 前=总{before[0]} 中{before[1]} 脱{before[2]}  →  后=总{after[0]} 中{after[1]} 脱{after[2]}"
          f"(raw_hit 旧窄口径对照保留在各 sector_hits[].raw_hit)")
    print(f"[migrate] stats: 前={json.dumps(before_stats, ensure_ascii=False)}")
    print(f"[migrate] stats: 后={json.dumps(obj['stats'], ensure_ascii=False)}")

    if args.dry_run:
        print("[migrate] dry-run 不写盘")
        return 0

    ts = time.strftime("%Y%m%d-%H%M%S")
    bak = hp.with_suffix(f".json.bak-bandreclass-{ts}")
    shutil.copy2(hp, bak)
    hp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[migrate] 已备份原文件 → {bak}")
    print(f"[migrate] 已写回 {hp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
