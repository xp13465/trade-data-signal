#!/usr/bin/env python3
"""calibrate_sector_band.py - 板块层命中区间「波动率自适应带宽」参数校准(2026-08-24 需求R2)。

目的:
  现状板块层命中判定用 AI 原始窄区间(宽度≤0.5pp,实际多 ±0.25pp),而申万板块单日常见
  ±2~4% 波动 → 区间命中数学趋零(20260810-0824 板块层 0/10 全脱靶),前端恒显 0% 误导。
  本脚本为「有效判定带 = 以预测中点为中心、宽 w=max(median(|pct|,N)×k, min_w)」的
  自适应口径校准参数 (N, k, min_w),选「自然覆盖率落在 ~40-65% 且对极端行情不失效」的组合。

方法(两法互证):
  A) 自然覆盖率法(主):对 DB 中全部申万行业(sw_*)指数逐交易日 t(近 LOOKBACK 日),
     band_w(t)=max(median(|pct(t-N+1..t)|)×k, min_w) ——只用 t 及之前数据(防前视,
     t 收盘数据在 t 日 20:40 预测时点已就绪,合法);覆盖率=P(|pct(t)|≤band_w/2)(0 中心近似
     =方向中性假设下的幅度兜住率)。另单独统计极端日(|pct|≥3%)兜住率,验证「极端行情不失效」
     的真实含义=带宽随波动放大而放大,不因固定窄带恒错。
  B) 历史预测反事实法(辅):daily_brief_history.json 已回填 sector_ranges 条目,
     用 AI 预测区间中点+自适应带宽重判,对比原窄口径命中率(样本 n≈10,仅方向性参考)。

输入依赖:
  - $REPO/data/sentiment.db(index_daily sw_* pct_change;缺省 REPO=/Users/linhuichen/code/trade-data)
  - static-site/data/daily_brief_history.json(trade 仓工作区)
输出:各 (N,k,min_w) 组合覆盖率表 + 极端日分析 + 推荐参数(stdout 表格)。

复现命令:
  REPO=/Users/linhuichen/code/trade-data python3 docs/ai-predict/scripts/calibrate_sector_band.py
数据截止:2026-08-24(运行日 DB 最新交易日)。关键口径:band_w=median(|日收益|,N日含t)×k、下限 min_w;
覆盖率以 0 为中心的近似口径(AI 中点非 0 时实际覆盖略偏移,由 B 法补真实验证)。
"""
import json
import sqlite3
import statistics
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]  # docs/ai-predict/scripts/ -> trade 根
DB = Path("/Users/linhuichen/code/trade-data/data/sentiment.db")
HISTORY = REPO / "static-site" / "data" / "daily_brief_history.json"

LOOKBACK = 500          # 自然覆盖率回看交易日数(约 2 年,覆盖多种行情)
EXTREME_TH = 3.0        # 极端日阈值 |pct|≥3%
NS = [5, 10, 20, 30]    # 滚动窗口 N(含当日)
KS = [0.5, 0.8, 1.0, 1.2, 1.5, 2.0]
MIN_WS = [0.3, 0.5]     # 带宽下限(pp)


def load_sw_series() -> dict[str, list[tuple[str, float]]]:
    """全部申万行业 index_daily pct_change 序列 {index_id: [(date,pct)...]}(只取近 LOOKBACK+N 日)。"""
    out: dict[str, list[tuple[str, float]]] = {}
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=20)
    try:
        rows = conn.execute(
            "SELECT index_id, date, pct_change FROM index_daily "
            "WHERE index_id LIKE 'sw\\_%' ESCAPE '\\' AND pct_change IS NOT NULL ORDER BY index_id, date"
        ).fetchall()
    finally:
        conn.close()
    for iid, d, p in rows:
        out.setdefault(iid, []).append((d, p))
    # 每个只留尾部 LOOKBACK + max(N) 天(省内存,median 只需窗口内)
    tail = LOOKBACK + max(NS)
    return {k: v[-tail:] for k, v in out.items() if len(v) >= LOOKBACK // 2}


def method_a(series: dict[str, list]) -> None:
    print("=" * 100)
    print(f"方法A 自然覆盖率(全部申万行业,近{LOOKBACK}交易日/板块,band_w=max(median(|pct|,N)×k,min_w),0中心)")
    print("=" * 100)
    n_iids = len(series)
    print(f"板块数 n={n_iids}(取近{LOOKBACK}天以上有数据的)")
    header = f"{'N':>3} {'k':>4} {'min_w':>5} | {'覆盖率%':>7} {'极端日n':>6} {'极端兜住%':>8} | {'带宽中位':>8} {'带宽P90':>8}"
    print(header)
    results = []
    for N in NS:
        for k in KS:
            for mw in MIN_WS:
                hit = tot = ext_hit = ext_tot = 0
                widths = []
                for iid, seq in series.items():
                    pcts = [p for _, p in seq]
                    dates = [d for d, _ in seq]
                    start = max(N - 1, len(pcts) - LOOKBACK)
                    for i in range(start, len(pcts)):
                        win = [abs(x) for x in pcts[i - N + 1:i + 1]]
                        med = statistics.median(win)
                        w = max(med * k, mw)
                        p = pcts[i]
                        tot += 1
                        ok = abs(p) <= w / 2
                        hit += 1 if ok else 0
                        widths.append(w)
                        if abs(p) >= EXTREME_TH:
                            ext_tot += 1
                            ext_hit += 1 if ok else 0
                cov = hit / tot * 100 if tot else 0
                ecov = ext_hit / ext_tot * 100 if ext_tot else 0
                widths.sort()
                wmed = widths[len(widths)//2] if widths else 0
                wp90 = widths[int(len(widths)*0.9)] if widths else 0
                print(f"{N:>3} {k:>4} {mw:>5} | {cov:>6.1f}% {ext_tot:>6} {ecov:>7.1f}% | {wmed:>7.2f}pp {wp90:>7.2f}pp")
                results.append((N, k, mw, cov, ecov, wmed))
    # 目标域筛选:覆盖率 40-65%,按覆盖率排序展示 top 组合
    print("\n目标域(覆盖率40-65%)按覆盖率升序:")
    inbox = sorted([r for r in results if 40 <= r[3] <= 65], key=lambda r: r[3])
    for N, k, mw, cov, ecov, wmed in inbox[:12]:
        print(f"  N={N:>2} k={k:<4} min_w={mw} -> 覆盖率 {cov:.1f}%, 极端日兜住 {ecov:.1f}%(n样本见上表), 带宽中位 {wmed:.2f}pp")


def method_b() -> None:
    print()
    print("=" * 100)
    print("方法B 历史预测反事实(daily_brief_history 已回填 sector_ranges,AI中点+自适应带 vs 原窄带)")
    print("=" * 100)
    try:
        obj = json.loads(HISTORY.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"(history 读取失败跳过B法: {e})")
        return
    items = obj.get("items") or []
    # 收集所有板块 id 序列
    need_ids = set()
    recs = []
    for it in items:
        m = it.get("meta") or {}
        h = m.get("hit") or {}
        if h.get("actual_sh_pct") is None or not (m.get("sector_ranges") or []):
            continue  # 未回填或无板块预测
        for s in m["sector_ranges"]:
            if s.get("index_id"):
                need_ids.add(s["index_id"])
        recs.append((it.get("date"), m))
    if not recs:
        print("(无可反事实条目)")
        return
    series: dict[str, dict[str, float]] = {}
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=20)
    try:
        for iid in sorted(need_ids):
            rows = conn.execute(
                "SELECT date, pct_change FROM index_daily WHERE index_id=? AND pct_change IS NOT NULL ORDER BY date",
                (iid,)).fetchall()
            series[iid] = {d: p for d, p in rows}
    finally:
        conn.close()

    def next_pct(idmap: dict[str, float], bdate: str):
        ds = sorted(d for d in idmap if d > bdate)
        return (ds[0], idmap[ds[0]]) if ds else (None, None)

    for combo in [(10, 1.0, 0.3), (10, 1.2, 0.3), (20, 1.0, 0.3), (20, 1.2, 0.5)]:
        N, k, mw = combo
        raw_hit = ad_hit = na = 0
        lines = []
        for bdate, m in recs:
            for s in m["sector_ranges"]:
                iid = s.get("index_id")
                idmap = series.get(iid) or {}
                nd, spct = next_pct(idmap, bdate)
                if nd is None or spct is None:
                    na += 1
                    continue
                lo, hi = s["lo"], s["hi"]
                c = (lo + hi) / 2
                # 防前视:median 只用 <=bdate 的近 N 日
                hist = [abs(p) for d, p in sorted(idmap.items()) if d <= bdate][-N:]
                med = statistics.median(hist) if hist else None
                w = max(med * k, mw) if med is not None else (hi - lo)
                eff_lo, eff_hi = c - w / 2, c + w / 2
                r1 = lo <= spct <= hi
                r2 = eff_lo <= spct <= eff_hi
                raw_hit += r1
                ad_hit += r2
                lines.append(f"  {bdate} {s['name']:<6} 预测[{lo:+.1f},{hi:+.1f}] 实际{spct:+.2f}% "
                             f"| 窄带{'中' if r1 else '脱'} 自适应[{eff_lo:+.2f},{eff_hi:+.2f}]{'中' if r2 else '脱'}")
        tot = len(lines)
        print(f"\n参数 N={N} k={k} min_w={mw}:原窄口径 {raw_hit}/{tot},自适应 {ad_hit}/{tot}(N/A {na})")
        if combo == (10, 1.2, 0.3):
            print("\n".join(lines))


if __name__ == "__main__":
    if not DB.exists():
        print(f"DB 不存在: {DB}", file=sys.stderr)
        sys.exit(1)
    method_a(load_sw_series())
    method_b()
