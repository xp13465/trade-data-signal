#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""净资产走势图·前端实现与 Python 权威复刻逐位对账(2026-09-04 #51 实施自测, §5.4⑦ 同构对账)

目的:
  1) 从 static-site/app.js 源码 vm 提取真实前端函数(_simBuyWithFees/_simSellWithFees/_simNetassetCurve),
     避免手抄第二份实现漂移(§5.4⑦ repro 脚本同构对账铁律)
  2) 与 Python 权威复刻 netasset_daily_repro.daily_netasset 吃同一 kept rows + 同一 initCapital,
     逐点逐字段对比(date/value/holdings/cash/mv)
  3) 对账锚点: 窗口 H K=1 20250901~20260831 期末净资产应 = 46886.46 ±0.01(与报告/任务验收期望一致)

口径:
  前端函数即 app.js 线上实现(曲线口径=现金+持仓市值; 现金=初始-Σ开仓本金+Σ卖出净额; 市值=Σ未平仓份额×当日accum_nav 缺日向前取;
  初始=峰值同时持仓笔数×¥10000), 不改一行。
  本脚本只负责「喂相同输入 + 逐位对比」。

输入依赖:
  - static-site/data/signal_kelly_trades.json(逐笔成交, 管位管线数据源)
  - static-site/data/accum_nav_map.json(ETF 逐日净值)
  - static-site/app.js(提取 _simNetassetCurve 等三个函数)

复现命令:
  cd docs/kelly/analysis/sim-netasset-equity-chart-20260901 && python3 scripts/netasset_frontend_compare.py H 1 20250901 20260831
参数=模式 K 起日 止日(同 netasset_daily_repro.py)。
"""
import json, os, subprocess, sys, tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import netasset_daily_repro as R


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "H"
    K = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    W0 = sys.argv[3] if len(sys.argv) > 3 else "20250901"
    W1 = sys.argv[4] if len(sys.argv) > 4 else "20260831"
    tr, nav, fI = R.load()
    pool = [t for t in R.build_pool(tr, fI, mode)
            if (not W0 or str(t[fI["signal_date"]] or "") >= W0) and (not W1 or str(t[fI["signal_date"]] or "") <= W1)]
    kept = R.top_k(pool, fI, K)
    kept, ghi_peak = R.ghi_hold_cap(kept, fI, mode)
    peak = R.peak_positions(kept, fI)
    init_capital = max(peak, 1) * R.PRIN
    curve_py, realized_acc, nav_ff = R.daily_netasset(kept, nav, fI, R.FP, init_capital)
    curve_py = [c for c in curve_py if (not W0 or c["date"] >= W0) and (not W1 or c["date"] <= W1)]
    if not curve_py:
        print("空窗口"); return
    tmp = tempfile.mkdtemp(prefix="netasset_cmp_")
    kept_f = os.path.join(tmp, "kept.json")
    out_f = os.path.join(tmp, "js_curve.json")
    json.dump({"rows": kept, "fIdx": fI, "fp": R.FP, "initCapital": init_capital}, open(kept_f, "w"))
    mjs = os.path.join(os.path.dirname(os.path.abspath(__file__)), "netasset_frontend_compare.mjs")
    r = subprocess.run(["node", mjs, kept_f, R.NAV, out_f, os.path.join(ROOT, "static-site", "app.js")],
                       capture_output=True, text=True)
    print(r.stdout)
    if r.returncode != 0:
        print("NODE ERR:", r.stderr)
        sys.exit(1)
    js = json.load(open(out_f))["curve"]
    # 前端 _simRenderNetassetChart 在 _render 内按窗口 filter 后再渲染(_simNetassetCurve 只做全量逐日重建);
    # 对账需同一 filter(与 Python curve_py 同口径), 否则点数/起始点不同(全量从最早 nav 日 20110111 起)。
    js = [c for c in js if (not W0 or c["date"] >= W0) and (not W1 or c["date"] <= W1)]
    n = min(len(curve_py), len(js))
    mism, maxdiff = [], 0.0
    for i in range(n):
        a, b = curve_py[i], js[i]
        for k in ("date", "value", "holdings", "cash", "mv"):
            va, vb = a[k], b[k]
            if isinstance(va, (int, float)) and isinstance(vb, (int, float)):
                diff = abs(float(va) - float(vb))
                if diff > maxdiff:
                    maxdiff = diff
                if diff > 0.01:
                    mism.append((i, a["date"], k, va, vb))
            elif va != vb:
                mism.append((i, a["date"], k, va, vb))
    print(f"模式={mode} K={K} 窗口={W0}~{W1}")
    print(f"峰值同时持仓={peak}笔 初始资金={init_capital:.0f}元")
    print(f"Python 曲线点数={len(curve_py)} 末点={curve_py[-1]}")
    print(f"JS    曲线点数={len(js)} 末点={js[-1] if js else None}")
    print(f"逐位对比: 对齐点数={n} 最大差={maxdiff:.6f} 不一致条数={len(mism)}")
    if len(curve_py) != len(js):
        print(f"⚠ 点数不一致: py={len(curve_py)} js={len(js)}")
    if mism:
        print("MISMATCH 前5:", mism[:5])
        sys.exit(2)
    print("✓ 前端 _simNetassetCurve 与 Python 权威复刻逐位一致")
    print(f"对账锚点: 期末净资产={curve_py[-1]['value']:.2f} (任务验收期望 46886.46 ±0.01)")


if __name__ == "__main__":
    main()
