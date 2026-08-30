#!/usr/bin/env python3
"""GHI 真实价格回测辅助:从主库 etf_daily 导出 accum_nav(累计净值)映射 JSON。

目的:
  为 kelly_ghi_real_price_rebase.mjs 提供"强平日真实卖出净值"的数据源。
  trades.json 的 buy_price/sell_price 均为 accum_nav 口径(已验证:ell_price/0.999 与
 主库 etf_daily.accum_nav 逐位一致),因此强平日真实价 = 该 ETF 该日 accum_nav,
  与 _kellyRecomputeTrade 的卖出还原价完全同口径。

方法口径:
  - 数据源 = 主库 /Users/linhuichen/code/trade-data/data/etf_national_team.db(与 trades 生成同库,
    避免读静态镜像或前复权 ohlc(C_etf 漂移的 6 只新 ETF 同样正确)。
  - 输出 {"etf_code": {"YYYYMMDD": accum_nav, ...}} 紧凑 JSON。
  - 用 soft RECORD 缺省输出(默认 1000 只 ETF 以内样例;全量用 --all)。

输入依赖:  $REPO/data/etf_national_team.db(REPO env 缺省 /Users/linhuichen/code/trade-data)
输出:       docs/kelly/position/scripts/accum_nav_map.json
复现命令:
  python3 scripts/export_accum_nav_map.py --all
"""
import argparse
import json
import os
import sqlite3

DEFAULT_REPO = "/Users/linhuichen/code/trade-data"
OUT_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "accum_nav_map.json")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="全量导出(默认只导出前 1000 只,样例)")
    args = ap.parse_args()

    repo = os.environ.get("REPO", DEFAULT_REPO)
    db = os.path.join(repo, "data", "etf_national_team.db")
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row

    limit = None if args.all else 1000
    if limit:
        codes = [r["etf_code"] for r in conn.execute(
            "SELECT DISTINCT etf_code FROM etf_daily WHERE accum_nav IS NOT NULL LIMIT ?", (limit,)
        )]
    else:
        codes = None

    maps: dict[str, dict[str, float]] = {}
    if codes is None:
        rows = conn.execute(
            "SELECT etf_code, date, accum_nav FROM etf_daily WHERE accum_nav IS NOT NULL ORDER BY etf_code, date"
        ).fetchall()
        for r in rows:
            maps.setdefault(r["etf_code"], {})[str(r["date"])] = r["accum_nav"]
    else:
        for c in codes:
            rows = conn.execute(
                "SELECT date, accum_nav FROM etf_daily WHERE etf_code=? AND accum_nav IS NOT NULL ORDER BY date",
                (c,),
            ).fetchall()
            maps[c] = {str(r["date"]): r["accum_nav"] for r in rows}
    conn.close()

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(maps, f, ensure_ascii=False, separators=(",", ":"))
    n_etf = len(maps)
    n_dates = sum(len(v) for v in maps.values())
    print(f"exported {n_etf} ETF {n_dates} date-rows -> {OUT_JSON}")


if __name__ == "__main__":
    main()