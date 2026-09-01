#!/usr/bin/env python3
"""AI 预测方向锚 5.2 穷举子群回测分析(轻量重分析,死脚本副本,§23.5)。

目的:在 5.1 全历史回测 detail JSON 基础上,做子群方向命中分析,回答「方向锚
现版对称规则在哪些特定条件下押方向有效(>0.5 且显著)」,不无脑全量。

方法/口径:
- 输入:docs/ai-predict/scripts/out/direction_anchor_backtest_results.json(5.1 产出,642 样本全明细)
- 命中口径:dir = lean in (up,down)(即押了方向,排除 flat 天然约 0.5 命中)
  dir_win = P(hit | dir)  (hit = lean==actual)
- 二项检验:单边 p = P(X>=k | n, p0=0.5),z 值 = (p_hat - 0.5)/sqrt(0.25/n);
  显著判据 |z|>=1.96(双边 5%)。n 太小的子群(z 不可靠)单独标注。
- 各维度:
  1. T 子群(to_long/to_short/both/none) x dir_win
  2. role 子群(roles 含哪个席位) x dir_win
  3. strength(strong/weak) x dir_win
  4. 叠加 L 因子条件:rate_down / gold_pos / nq_low(仅 20260716 后)各条件 x dir_win
  5. 按年 + 分半(前/后半)稳定性
  6. 阈值敏感度(读 *_thr*.json,由 backtest_direction_anchor.py --threshold 产出)
  7. 前向样本外:2024-2025 选段 vs 2026 验证段
  8. 与 AI 输出在线对照(读 brief_shadow.json + daily_brief_history.json,小样本只作参考)

输入依赖:
- data/sentiment.db(经 5.1 detail JSON 间接)
- docs/ai-predict/scripts/out/direction_anchor_backtest_results.json(主口径 0.5)
- docs/ai-predict/scripts/out/direction_anchor_backtest_results_thr0.3/0.8/1.0.json(阈值敏感度,需先跑 backtest_direction_anchor.py --threshold)
- data/brief_shadow.json / static-site/data/daily_brief_history.json(线上三方对照)

输出:
- docs/ai-predict/scripts/out/direction_anchor_backtest_52.json(本分析结果)

复现命令:
  python docs/ai-predict/scripts/backtest_direction_anchor.py --db data/sentiment.db --threshold 0.3
  python docs/ai-predict/scripts/backtest_direction_anchor.py --db data/sentiment.db --threshold 0.8
  python docs/ai-predict/scripts/backtest_direction_anchor.py --db data/sentiment.db --threshold 1.0
  python docs/ai-predict/scripts/analyze_direction_anchor_52.py

数据截止:detail JSON 20260830(sentiment.db 20260831);brief_shadow 20260828(8条);daily_brief_history 20260831(16条)。
关键口径一句话:方向锚重放现版对称规则,命中=lean==actual 纯方向相等;本分析只看押方向子集
(dir=up/down),不把 flat 桶(天然 ~0.5)当信号。
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent  # trade/
OUT_DIR = Path(__file__).resolve().parent / "out"
MAIN_JSON = OUT_DIR / "direction_anchor_backtest_results.json"          # 0.5 主口径
SHADOW_JSON = ROOT / "data" / "brief_shadow.json"
HISTORY_JSON = ROOT / "static-site" / "data" / "daily_brief_history.json"


def zscore(p_hat: float, n: int, p0: float = 0.5) -> float:
    """单样本比例 z 检验(z = (p_hat - p0)/sqrt(p0(1-p0)/n))。n=0 返回 nan。"""
    if n == 0:
        return float("nan")
    return (p_hat - p0) / math.sqrt(p0 * (1 - p0) / n)


def binomial_p_value(k: int, n: int, p0: float = 0.5) -> float:
    """单边右尾二项 p 值 P(X>=k | n,p0)。n 过大时用正态近似。"""
    if n == 0:
        return float("nan")
    if n > 200:
        p_hat = k / n
        z = zscore(p_hat, n, p0)
        # 单边右尾
        return 0.5 * (1 - math.erf(z / math.sqrt(2)))
    # 精确二项(小 n)
    from math import comb
    p = 0.0
    for i in range(k, n + 1):
        p += comb(n, i) * (p0 ** i) * ((1 - p0) ** (n - i))
    return p


def dir_stats(items):
    """对押方向子集统计 dir_win/n/z/单边p。

    口径(与 5.1 主口径一致):dir = lean in (up,down) AND actual in (up,down)。
    ——即「锚押了方向、且次日真实也走出了方向(非 flat)」的样本。flat-actual 日不计入
    (当日无方向,不判锚对错)。dir_win = P(hit | dir),hit = lean==actual。
    返回 None 若 dir_n=0。
    """
    sub = [it for it in items if it["lean"] in ("up", "down") and it["actual"] in ("up", "down")]
    n = len(sub)
    if n == 0:
        return {"n": 0, "dir_win": None, "z": None, "binom_p": None}
    k = sum(1 for it in sub if it["hit"])
    p_hat = k / n
    return {
        "n": n,
        "dir_win": round(p_hat, 4),
        "z": round(zscore(p_hat, n), 4),
        "binom_p": round(binomial_p_value(k, n), 4),
    }


def bucket_by(items, key_fn):
    """按 key_fn 分组返回 {key: dir_stats}。"""
    groups = {}
    for it in items:
        g = key_fn(it)
        groups.setdefault(g, []).append(it)
    return {k: dir_stats(v) for k, v in sorted(groups.items(), key=lambda x: str(x[0]))}


def main():
    data = json.loads(MAIN_JSON.read_text(encoding="utf-8"))
    detail = data["detail"]
    print(f"总样本 detail={len(detail)}")

    out = {"meta": data["meta"], "total_sample": len(detail)}

    # 1. T 子群
    out["by_T"] = bucket_by(detail, lambda it: it["T"])

    # 2. role 子群(roles 列表含哪个席位,任一匹配即入该席位桶)
    roles_of_interest = ["中信期货", "top20", "国泰君安"]
    role_groups = {r: [it for it in detail if r in it["roles"]] for r in roles_of_interest}
    out["by_role"] = {r: dir_stats(v) for r, v in role_groups.items()}
    # 多席位组合
    multi = [it for it in detail if len(it["roles"]) >= 2]
    out["by_role"]["multi_2plus"] = dir_stats(multi)

    # 3. strength 子群
    out["by_strength"] = bucket_by(detail, lambda it: it["strength"])

    # 4. L 因子条件
    out["cond_rate_down"] = {
        "rate_down_true": dir_stats([it for it in detail if it["rate_down"] is True]),
        "rate_down_false": dir_stats([it for it in detail if it["rate_down"] is False]),
        "rate_down_none": dir_stats([it for it in detail if it["rate_down"] is None]),
    }
    # gold_pos 全为 True(642/642),无对比
    out["cond_gold_pos"] = {"all_gold_pos_true": dir_stats(detail)}
    # nq_low 仅 20260716 起(nq_present)
    out["cond_nq"] = {
        "nq_low_true": dir_stats([it for it in detail if it["nq_low"] is True]),
        "nq_low_false": dir_stats([it for it in detail if it["nq_low"] is False]),
        "nq_present": dir_stats([it for it in detail if it["nq_present"]]),
        "nq_absent": dir_stats([it for it in detail if not it["nq_present"]]),
    }

    # 5. 按年 + 分半
    out["by_year"] = bucket_by(detail, lambda it: it["date"][:4])
    half = len(detail) // 2
    out["by_half"] = {
        "first_half": dir_stats(detail[:half]),
        "second_half": dir_stats(detail[half:]),
    }

    # 7. 前向样本外:2024-2025 选段 vs 2026 验证段
    out["forward_ood"] = {
        "select_2024_2025": dir_stats([it for it in detail if it["date"][:4] in ("2024", "2025")]),
        "validate_2026": dir_stats([it for it in detail if it["date"][:4] == "2026"]),
    }

    # 阈值敏感度:读 *_thr*.json(若存在)
    thr_results = {}
    for t in (0.3, 0.8, 1.0):
        p = OUT_DIR / f"direction_anchor_backtest_results_thr{t}.json"
        if p.exists():
            d = json.loads(p.read_text(encoding="utf-8"))
            thr_results[str(t)] = {
                "overall": d["overall"],
                "dir_win": dir_stats(d["detail"]),
                "overall_dir_win_rate": d["overall"].get("dir_win_rate"),
            }
    # 主口径 0.5
    thr_results["0.5"] = {
        "overall": data["overall"],
        "dir_win": dir_stats(detail),
        "overall_dir_win_rate": data["overall"].get("dir_win_rate"),
    }
    out["threshold_sensitivity"] = thr_results

    # 8. 与 AI 输出在线对照(三方,小样本只作参考)
    tri = {}
    if SHADOW_JSON.exists() and HISTORY_JSON.exists():
        shadow = json.loads(SHADOW_JSON.read_text(encoding="utf-8"))
        hist = json.loads(HISTORY_JSON.read_text(encoding="utf-8"))
        hist_by_date = {}
        for it in hist.get("items", []):
            hist_by_date[it["date"]] = it
        shadow_rows = []
        for s in shadow:
            date = s["date"]
            h = hist_by_date.get(date, {})
            m = h.get("meta", {})
            shadow_rows.append({
                "date": date,
                "shadow_lean": s.get("pred_shadow"),
                "ai_direction": m.get("direction"),
                "ai_call": m.get("direction_call"),
                "actual_dir": (m.get("hit") or {}).get("actual_direction"),
            })
        # 方向锚影子押方向命中。口径与主分析 dir_stats 一致:
        # dir = shadow_lean in (up,down) AND actual_dir in (up,down),命中=相等。
        def _shadow_hit(sr):
            return sr["actual_dir"] is not None and sr["shadow_lean"] == sr["actual_dir"]
        shadow_dir = [r for r in shadow_rows
                      if r["shadow_lean"] in ("up", "down") and r["actual_dir"] in ("up", "down")]
        shadow_dir_all = [r for r in shadow_rows if r["shadow_lean"] in ("up", "down")]
        tri["shadow"] = {
            "n": len(shadow_rows),
            "dir_n": len(shadow_dir),
            "dir_win": round(sum(_shadow_hit(r) for r in shadow_dir) / len(shadow_dir), 4) if shadow_dir else None,
            "dir_n_all_lean": len(shadow_dir_all),
            "dir_win_all_lean": round(sum(_shadow_hit(r) for r in shadow_dir_all) / len(shadow_dir_all), 4) if shadow_dir_all else None,
            "rows": shadow_rows,
        }
        # AI 输出(纯方向相等口径,direction 直接比,口径同 dir_stats:direction 押方向且 actual 有方向)
        ai_rows = []
        for it in hist.get("items", []):
            m = it.get("meta", {})
            h = m.get("hit") or {}
            ai_rows.append({
                "date": it["date"],
                "ai_direction": m.get("direction"),
                "ai_call": m.get("direction_call"),
                "actual_dir": h.get("actual_direction"),
                "hit": h.get("direction"),
            })
        ai_dir = [r for r in ai_rows if r["ai_direction"] in ("up", "down") and r["actual_dir"] in ("up", "down")]
        tri["ai"] = {
            "n": len([r for r in ai_rows if r["actual_dir"] is not None]),
            "dir_n": len(ai_dir),
            "dir_win": round(sum(1 for r in ai_dir if r["ai_direction"] == r["actual_dir"]) / len(ai_dir), 4) if ai_dir else None,
            "rows": ai_rows,
        }
    out["online_triple_compare"] = tri

    # 写 out json
    OUT_DIR.mkdir(exist_ok=True)
    out_path = OUT_DIR / "direction_anchor_backtest_52.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"json -> {out_path}")

    # 摘要打印(供主控快速看)
    def _line(k, v):
        if v and v.get("dir_win") is not None:
            sig = " **显著**" if abs(v["z"]) >= 1.96 else ""
            return f"  {k}: n={v['n']} dir_win={v['dir_win']} z={v['z']}{sig}"
        return f"  {k}: n={v.get('n',0)} (无押方向样本)"
    print("\n=== T 子群 ===")
    for k, v in out["by_T"].items():
        print(_line(k, v))
    print("=== role ===")
    for k, v in out["by_role"].items():
        print(_line(k, v))
    print("=== strength ===")
    for k, v in out["by_strength"].items():
        print(_line(k, v))
    print("=== 按年 ===")
    for k, v in out["by_year"].items():
        print(_line(k, v))
    print("=== 分半 ===")
    for k, v in out["by_half"].items():
        print(_line(k, v))
    print("=== 前向样本外 ===")
    for k, v in out["forward_ood"].items():
        print(_line(k, v))
    print("=== 阈值敏感度(dir_win) ===")
    for k, v in out["threshold_sensitivity"].items():
        print(f"  thr={k}: dir_win={v['dir_win']['dir_win']} n={v['dir_win']['n']} (overall hit={v['overall'].get('hit_rate')})")


if __name__ == "__main__":
    sys.exit(main())
