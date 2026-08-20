#!/usr/bin/env python3
"""aggregate_shadow.py - 影子模式聚算:方向锚影子 lean vs 实际方向对账,产出 7 天命中率。

影子模式定义(2026-08-20 用户拍板,验证机制):线上输出完全不变,gen_daily_brief.py 主流程
按 date 旁路落盘 data/brief_shadow.json(影子 lean + 因子状态)。本脚本:
  1) 回填(reconcile):对每个影子记录,找其后第一个真实交易日上证 sh 涨跌幅(index_daily),
     按 HIT_THRESHOLD=0.5(与 gen_daily_brief._actual_direction 同口径)判 actual_direction,
     回写 data/brief_shadow.json 的 actual 字段(幂等,已回填跳过)。DB 不可用/无下一交易日=留空不硬判。
  2) 聚算(aggregate):影子方向命中率 = pred_shadow(up/down/flat) == actual_direction 的比例;
     按 pred_shadow 分桶、按 basis 因子分组统计误导贡献(top 误导向量),输出表格。
  3) 支持 --date 单日对账(只回填+统计指定影子记录)。

用法:
  python scripts/aggregate_shadow.py                     # 回填全部可回填 + 聚算
  python scripts/aggregate_shadow.py --date 20260820      # 只看某日影子 lean 对账
依赖: README `aggregate_shadow --date` 可复核(数据截止=index_daily 最新交易日)。
"""
import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

# 与 gen_daily_brief 同口径(防口径分叉):HIT_THRESHOLD=0.5 涨跌幅>0.5% 才 up/down 否则 flat
HIT_THRESHOLD = 0.5
SHADOW_FILE = "brief_shadow.json"
# 与 gen_daily_brief.pick_db 同口径帮: 挑 daily_metric 最新的 sentiment.db
# (主库优先,镜像兜底), 与影子记录写入同库同源。

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pick_repo import pick_repo  # noqa: E402
from shadow_track_md import update_shadow_track_md  # noqa: E402  (维护 docs/ai-predict-shadow-track.md)


def _pick_db() -> Path:
    """与 gen_daily_brief.pick_db 同口径挑最新 sentiment.db(主库→镜像兜底)。"""
    repo = pick_repo()
    best, best_date = None, ""
    for r in _candidate_repos():
        db = r / "data" / "sentiment.db"
        if not db.exists():
            continue
        m = ""
        try:
            conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=10)
            m = (conn.execute("SELECT MAX(date) FROM daily_metric").fetchone() or [""])[0] or ""
            conn.close()
        except Exception:
            m = ""
        if m > best_date:
            best_date, best = m, db
    return best or repo / "data" / "sentiment.db"


def _candidate_repos() -> list[Path]:
    """与 pick_repo.candidate_repos 并列: trade-data / trade / 环境 REPO/GIT_REPO。"""
    out: list[Path] = []
    for env in ("REPO", "GIT_REPO"):
        if os.environ.get(env):
            out.append(Path(os.environ[env]).resolve())
    out += [
        Path("/Users/linhuichen/code/trade-data"),
        Path("/Users/linhuichen/code/trade"),
    ]
    uniq: list[Path] = []
    for p in out:
        if p not in uniq:
            uniq.append(p)
    return uniq


def _load_sh_pct_map(db_path: Path) -> dict:
    """index_daily sh 全表 date->pct_change(与 backfill_hits 同源)。"""
    sh_map: dict = {}
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=15)
        for r in conn.execute(
                "SELECT date, pct_change FROM index_daily WHERE index_id='sh' ORDER BY date"):
            sh_map.setdefault(r[0], r[1])
        conn.close()
    except Exception:
        pass
    return sh_map


def _actual_direction(pct) -> str | None:
    if pct is None:
        return None
    if pct > HIT_THRESHOLD:
        return "up"
    if pct < -HIT_THRESHOLD:
        return "down"
    return "flat"


def _load_shadow(shadow_path: Path) -> list[dict]:
    try:
        obj = json.loads(shadow_path.read_text(encoding="utf-8"))
        if isinstance(obj, list):
            return obj
    except Exception:
        pass
    return []


def _reconcile(rows: list[dict], db_path: Path, only_date: str | None) -> tuple[list[dict], int]:
    """为可回填影子记录写入 actual(下一交易日 sh 实际方向)。返回(更新后 rows, 本次新回填数)。"""
    sh_map = _load_sh_pct_map(db_path)
    dates = sorted(sh_map.keys())
    if not dates:
        return rows, 0
    changed = 0
    for rec in rows:
        d = rec.get("date")
        if only_date and d != only_date:
            continue
        if rec.get("actual") is not None or rec.get("actual_direction") is not None:
            continue  # 已回填,幂等跳过
        if not d:
            continue
        # 找 d 之后第一个真实交易日(与 backfill_hits 同"全局交易日对齐")
        nxt = next((x for x in dates if x > d), None)
        if nxt is None:
            continue
        pct = sh_map.get(nxt)
        rec["actual"] = {
            "next_date": nxt,
            "actual_sh_pct": round(pct, 2) if pct is not None else None,
            "actual_direction": _actual_direction(pct),
        }
        changed += 1
    return rows, changed


def _aggregate(rows: list[dict]) -> dict:
    """聚算影子命中率。只统计已回填(actual_direction 非 None)的记录。"""
    evaled = [r for r in rows if (r.get("actual") or {}).get("actual_direction") is not None]
    total = len(evaled)
    hit = sum(1 for r in evaled if r.get("pred_shadow") == (r["actual"]["actual_direction"]))
    # 按 pred_shadow 分桶
    by_lean: dict = {}
    for r in evaled:
        lean = r.get("pred_shadow") or "?"
        b = by_lean.setdefault(lean, {"n": 0, "hit": 0})
        b["n"] += 1
        b["hit"] += 1 if r["pred_shadow"] == r["actual"]["actual_direction"] else 0
    for b in by_lean.values():
        b["hit_rate"] = round(b["hit"] / b["n"], 3) if b["n"] else None
    # 按 basis 因子分组统计误导贡献(top 误导向量=最常伴随 miss 的因子)
    factor_miss: dict = {}
    for r in evaled:
        if r.get("pred_shadow") == (r["actual"] or {}).get("actual_direction"):
            continue  # 只关注 miss 样本
        for fact in (r.get("basis") or []):
            key = fact.split("×")[0]  # "T1转多×3"->"T1转多", "L3纳指大跌(...)"->"L3纳指大跌(...)"
            factor_miss[key] = factor_miss.get(key, 0) + 1
    top_mislead = sorted(factor_miss.items(), key=lambda kv: -kv[1])[:10]
    # flat 是否是空转(flat 无方向,命中率意义弱,单独标)
    nonflat = [r for r in evaled if r.get("pred_shadow") != "flat"]
    nonflat_hit = sum(1 for r in nonflat if r.get("pred_shadow") == (r["actual"] or {}).get("actual_direction"))
    return {
        "total_eval": total,
        "hit": hit,
        "hit_rate": round(hit / total, 3) if total else None,
        "nonflat_eval": len(nonflat),
        "nonflat_hit": nonflat_hit,
        "nonflat_hit_rate": round(nonflat_hit / len(nonflat), 3) if nonflat else None,
        "by_lean": by_lean,
        "top_mislead_factors": top_mislead,
        "note": "影子探针样本稀疏(7天验证期),命中率仅累积参考,不构成显著统计意义(§5.1 诚实标注)",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="影子模式聚算:方向锚影子 lean vs 实际方向对账")
    ap.add_argument("--date", default="", help="只对账指定影子记录 date(YYYYMMDD)")
    ap.add_argument("--no-reconcile", action="store_true", help="只聚算不回填实际方向")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出聚算结果")
    args = ap.parse_args()

    repo = pick_repo()
    shadow_path = repo / "data" / SHADOW_FILE
    if not shadow_path.exists():
        print(f"[aggregate_shadow] 阴影文件不存在({shadow_path}),无可对账样本。")
        # 仍在下方框给空结果不裸崩(D B 不可用兜底)
        _agg = _aggregate([])
        if args.json:
            print(json.dumps(_agg, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(_agg, ensure_ascii=False, indent=2))
        return 0

    rows = _load_shadow(shadow_path)
    db_path = _pick_db()
    n_rows = len(rows)

    if not args.no_reconcile:
        rows, n_new = _reconcile(rows, db_path, only_date=args.date or None)
        if n_new:
            shadow_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        n_new = 0

    # 渲染影子追踪 md(维护 docs/ai-predict-shadow-track.md):回填后刷新"次日实际/命中"列。
    # 幂等——md 由 brief_shadow.json 全量渲染,重跑只反映"新增行/回填列"差异,不覆盖丢历史。
    try:
        from pick_repo import pick_git_repo as _pick_git  # noqa: F401
        from shadow_track_md import update_shadow_track_md as _upd_md
        _upd_md(repo, _pick_git())  # repo=trade-data 数据根(JSON 所在);md 落 git 仓 trade/docs
    except Exception:
        # md 渲染失败不阻断聚算主链(影子 JSON 对账已落盘,下次还能补渲染)
        pass

    _agg = _aggregate(rows)
    _agg["shadow_path"] = str(shadow_path)
    _agg["shadow_records"] = n_rows
    _agg["reconciled_new"] = n_new

    if args.json:
        print(json.dumps(_agg, ensure_ascii=False, indent=2))
        return 0

    print(f"[aggregate_shadow] 影子记录 {n_rows} 条,本次新回填 {n_new} 条")
    print(f"DB: {db_path}")
    print(f"可评估样本 {_agg['total_eval']} 条:命中 {_agg['hit']} 条,命中率 "
          f"{_agg['hit_rate'] if _agg['hit_rate'] is not None else '--'}")
    if _agg["nonflat_eval"]:
        print(f"非flat样本 {_agg['nonflat_eval']} 条:非flat命中率 "
              f"{_agg['nonflat_hit_rate'] if _agg['nonflat_hit_rate'] is not None else '--'} "
              f"(flat=无方向,空转不计加权)")
    print("按 pred_shadow 分桶:")
    for lean, b in sorted(_agg["by_lean"].items()):
        rate = f"{b['hit_rate']}" if b["hit_rate"] is not None else "--"
        print(f"  {lean}: n={b['n']} hit={b['hit']} hit_rate={rate}")
    if _agg["top_mislead_factors"]:
        print("top 误导向量(miss 样本中伴随因子频次,越靠前越常误导):")
        for fact, cnt in _agg["top_mislead_factors"]:
            print(f"  {fact}: {cnt}")
    else:
        print("(暂无 miss 样本或无 basis 因子可归因)")
    print(f"注: {_agg['note']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
