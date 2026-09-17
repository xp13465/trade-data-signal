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

占位残留过滤(2026-09-06 reviewer F3 根治,与回测/检测器同源):
  9/8 事故残留行 = 真实名 + accum_nav 残留 1.5(open/close/name 已被 backfill 覆盖真实值)。
  生成时用 app/collector/nav_placeholder_defense.is_placeholder_row(单一来源)滤掉
  「孤立跳变到 1.5」的残留行, 防前端净资产曲线/强平日真价取到 1.5 假价;
  真实 1.5 平滑行(588930@20260908 / 159303@20260721 前后连续)不误删。

输入依赖:  $REPO/data/etf_national_team.db(REPO env 缺省 /Users/linhuichen/code/trade-data)
输出:       docs/kelly/position/scripts/accum_nav_map.json(全量) + accum_nav/{code}.json(per-ETF 拆分, 仅 --all)
复现命令:
  python3 scripts/export_accum_nav_map.py --all
"""
import argparse
import json
import os
import sqlite3
import sys

# 供 import app.collector.nav_placeholder_defense(占位残留判定单一来源, F3)
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))  # trade/docs/kelly/position/scripts/
_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(_SCRIPT_DIR))))  # trade/
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)
from app.collector.nav_placeholder_defense import is_placeholder_row, trading_gap_between  # noqa: E402

DEFAULT_REPO = "/Users/linhuichen/code/trade-data"
OUT_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "accum_nav_map.json")
# per-ETF 拆分输出目录(懒加载, 2026-09-17): {code}.json = 该 code 的 {YYYYMMDD: accum_nav}(即全量 maps[code])。
# 与全量 accum_nav_map.json 同源同 dict 逐位一致(§5.4⑦ 生成同源机检对账对象), 前端 per-ETF 懒加载只拉组合涉及 code。
SPLIT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "accum_nav")


def _filter_placeholder(seq: list[tuple]) -> dict[str, float]:
    """过滤占位残留混合行, 返回 {str(date): accum_nav}。

    判定单一来源 is_placeholder_row(单哨兵 accum_nav=1.5 + 前后交易日不连续 + gap 间隔):
    只滤孤立跳变到 1.5 的真残留; 真实 1.5 平滑行(前后连续且间隔 ≤5)保留不误删。
    gap 维度(9/9): seq 只含该 code 非占位行, 索引差≠交易日差——长缺口(530000
    20260810~0907 无行)下相邻行索引差=1 但实际间隔 30, 8.3%<15% 跳变会被误豁免,
    必须走交易日历算真实间隔(与回测/检测器三处同源)。
    """
    out: dict[str, float] = {}
    n = len(seq)
    for i, (d, nav) in enumerate(seq):
        prev_nav = seq[i - 1][1] if i >= 1 else None
        next_nav = seq[i + 1][1] if i + 1 < n else None
        prev_gap = trading_gap_between(seq[i - 1][0], d) if i >= 1 else None
        next_gap = trading_gap_between(d, seq[i + 1][0]) if i + 1 < n else None
        if is_placeholder_row(nav, prev_nav, next_nav, prev_gap, next_gap):
            continue  # 占位残留, 滤掉(防前端取到 1.5 假价)
        out[str(d)] = nav
    return out


def _atomic_write_json(path: str, data) -> None:
    """tmp+os.replace 原子写, 防 deploy 生成/读取窗口读到撕裂文件(1554 个小文件, 成本可忽略)。"""
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)


def _dump_split(maps: dict[str, dict[str, float]], out_dir: str) -> None:
    """按 ETF 拆写 per-ETF 文件 {code}.json(值 = 该 code 的 {date: nav}, 与全量 maps[code] 同一对象)。

    顺带清理 out_dir 下「maps 中已不存在的 code」残留 .json(退市/移除 ETF), 防陈旧 per-ETF 文件
    长期滞留造成全量 vs 拆分不一致(前端懒加载若拉到已退市 code 的旧文件不影响正确性——组合只会要
    trades 中仍在的 code, 但保持同源自洽仍是 §5.4⑦ 机检前提)。
    """
    os.makedirs(out_dir, exist_ok=True)
    valid_names = {f"{c}.json" for c in maps}
    removed = 0
    for f in os.listdir(out_dir):
        if f.endswith(".json") and f not in valid_names:
            try:
                os.remove(os.path.join(out_dir, f))
                removed += 1
            except OSError:
                pass
    for code, m in maps.items():
        _atomic_write_json(os.path.join(out_dir, f"{code}.json"), m)
    if removed:
        print(f"accum_nav/ 清理陈旧文件 {removed} 个")
    print(f"split {len(maps)} ETF per-ETF files -> {out_dir}")


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
        cur_code: str | None = None
        seq: list[tuple] = []
        for r in rows:
            if r["etf_code"] != cur_code:
                if cur_code is not None:
                    maps[cur_code] = _filter_placeholder(seq)
                cur_code = r["etf_code"]
                seq = []
            seq.append((r["date"], r["accum_nav"]))
        if cur_code is not None:
            maps[cur_code] = _filter_placeholder(seq)
    else:
        for c in codes:
            rows = conn.execute(
                "SELECT date, accum_nav FROM etf_daily WHERE etf_code=? AND accum_nav IS NOT NULL ORDER BY date",
                (c,),
            ).fetchall()
            maps[c] = _filter_placeholder([(r["date"], r["accum_nav"]) for r in rows])
    conn.close()

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(maps, f, ensure_ascii=False, separators=(",", ":"))
    n_etf = len(maps)
    n_dates = sum(len(v) for v in maps.values())
    print(f"exported {n_etf} ETF {n_dates} date-rows -> {OUT_JSON}")

    # per-ETF 拆分(懒加载, 2026-09-17): 仅 --all(全量, deploy.sh 调用)才拆写——样例 1000 只不完整,
    # 拆出会造成全量 vs 拆分码集不一致(§5.4⑦ 机检对象以全量为准)。
    if args.all:
        _dump_split(maps, SPLIT_DIR)


if __name__ == "__main__":
    main()