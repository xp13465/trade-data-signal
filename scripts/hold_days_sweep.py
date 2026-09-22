#!/usr/bin/env python3
"""持有期全谱扫测(5~15 天)× 16 象限 —— 调研只读脚本, 不改生产默认组合、不覆盖生产产物。

复用 signal_kelly_backtest.compute() 现有框架(单一实现防漂移 §5.4⑦), 向 SELL_MODES 注入
HD6..HD14 新模式(hold_days=6,7,8,9,11,12,13,14, stop_profit=None, 与 A=10/E=5/F=15 同语义),
A/E/F 保留作基线对照(注入不得改变现有模式结果 —— 同框内 A/E/F 即基线复现)。

口径:
- 买入: 信号次日开盘(KELLY_BUY_NEXTDAY=1 默认), 每笔 10000 元含费率
- 卖出: 信号日后第 N 个交易日收盘(未来不足 N 日 → 持仓中按当前价预估)
- 冻结表: 读生产副本到临时路径(SIGNAL_KELLY_ETF_FREEZE_PATH 改指 /tmp), 不写生产文件
- KELLY_ASOF 可选: 设=截断到该日期(复现生产 9/13 基线用)

产物(写 docs/kelly/hold-days-sweep/):
  1. hold_sweep_stats.json  16 象限 × 11 持有期 × 5 周期全统计(_compute_stats 原口径)
  2. hold_sweep_yearly.json 16 象限 × 11 持有期的按年(买入年)盈亏/笔数/胜率
  3. hold_sweep_halves.json 16 象限 × 11 持有期的前半/后半分半盈亏
  4. hold_sweep_trades.json 16 象限 × 11 持有期逐笔(compact: 买入日/利润/收益率/持有天数/卖出日)
"""
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import signal_kelly_backtest as skb

def _get_trades_from(trades_output, qk, mk):
    """从 trades_output 列式结构还原 trade dict(仅用定义的字段)。"""
    fields = trades_output["fields"]
    rows = trades_output["quadrants"][qk][mk]
    out = []
    for r in rows:
        t = dict(zip(fields, r))
        t["profit"] = float(t["profit"]) if t["profit"] not in ("", None) else 0.0
        t["return_pct"] = float(t["return_pct"]) if t["return_pct"] not in ("", None) else 0.0
        t["buy_date"] = str(t["buy_date"])
        out.append(t)
    return out

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "docs", "kelly", "hold-days-sweep")

# ── 1. 冻结表走临时副本, 绝不写生产 ──
_prod_freeze = skb._etf_freeze_path()
_tmp_freeze = "/tmp/sweep_etf_freeze.json"
if os.path.exists(_prod_freeze):
    shutil.copy2(_prod_freeze, _tmp_freeze)
    print(f"冻结表副本: {_prod_freeze} -> {_tmp_freeze} (原文件不写)")
os.environ["SIGNAL_KELLY_ETF_FREEZE_PATH"] = _tmp_freeze

# 研究档不触发生产告警通道(冻结缺失告警/邮件), 只打印不发送
skb._alert_frozen_missing = lambda events: print(f"⚠ [研究档] 冻结缺失事件 {len(events)} 个(告警已走打印,不触发 notify)")

# ── 2. 注入 HD6..HD14(5/10/15 已有 A/E/F, 不重复注入, 基线靠同框 A/E/F 复现) ──
HD_ADD = [6, 7, 8, 9, 11, 12, 13, 14]
for hd in HD_ADD:
    key = f"HD{hd}"
    skb.SELL_MODES[key] = {"label": f"持有{hd}天", "hold_days": hd, "stop_profit": None}
    print(f"注入模式: {key} = 持有{hd}天")

FIXED_HD_MODES = ["E", "HD6", "HD7", "HD8", "HD9", "A", "HD11", "HD12", "HD13", "HD14", "F"]

# ── 3. 运行(computed 全量) ──
output, trades_output = skb.compute()

os.makedirs(OUT_DIR, exist_ok=True)

# ── 4. 统计产物: 16 象限 × 5 周期 × 全部模式(含基线 A/E/F) ──
stats_out = {"config": {"asof": skb.KELLY_ASOF, "buy_amount": skb.BUY_AMOUNT,
                        "buy_price_basis": "next_day_open" if skb.KELLY_BUY_NEXTDAY else "signal_day_close",
                        "fixed_hd_modes": {m: skb.SELL_MODES[m] for m in FIXED_HD_MODES},
                        "periods": {k: v["cutoff"] for k, v in skb.PERIODS.items()}},
             "quadrants": {}}
for qk in skb.QUADRANT_META:
    stats_out["quadrants"][qk] = {pk: {mk: output["quadrants"][qk]["periods"][pk][mk]
                                       for mk in skb.SELL_MODES}
                                  for pk in skb.PERIODS}
with open(os.path.join(OUT_DIR, "hold_sweep_stats.json"), "w", encoding="utf-8") as f:
    json.dump(stats_out, f, ensure_ascii=False, separators=(",", ":"), indent=1)
print(f"\n✓ {OUT_DIR}/hold_sweep_stats.json")

# ── 5. 按年分解(16 象限 × 11 固定持有期, 按 buy_date 年) ──
yearly_out = {}
for qk in skb.QUADRANT_META:
    yearly_out[qk] = {}
    for mk in FIXED_HD_MODES:
        rows = {}
        for t in _get_trades_from(trades_output, qk, mk):
            y = t["buy_date"][:4]
            r = rows.setdefault(y, {"n": 0, "total_profit": 0.0, "win": 0})
            r["n"] += 1
            r["total_profit"] += t["profit"]
            if t["profit"] > 0:
                r["win"] += 1
        for y in sorted(rows):
            rows[y]["total_profit"] = round(rows[y]["total_profit"], 2)
            rows[y]["win_rate"] = round(rows[y]["win"] / rows[y]["n"], 4) if rows[y]["n"] else 0
            del rows[y]["win"]
        yearly_out[qk][mk] = rows
with open(os.path.join(OUT_DIR, "hold_sweep_yearly.json"), "w", encoding="utf-8") as f:
    json.dump(yearly_out, f, ensure_ascii=False, separators=(",", ":"), indent=1)
print(f"✓ {OUT_DIR}/hold_sweep_yearly.json")

# ── 6. 分半(16 象限 × 11 持有期, 按 buy_date 时间中位点分前后半) ──
halves_out = {}
for qk in skb.QUADRANT_META:
    halves_out[qk] = {}
    for mk in FIXED_HD_MODES:
        trades = _get_trades_from(trades_output, qk, mk)
        if not trades:
            halves_out[qk][mk] = {"first": None, "second": None}
            continue
        dates = sorted({t["buy_date"] for t in trades})
        mid = dates[len(dates) // 2]
        def _agg(ts):
            n = len(ts)
            if not n:
                return None
            return {"n": n, "total_profit": round(sum(t["profit"] for t in ts), 2),
                    "win_rate": round(sum(1 for t in ts if t["profit"] > 0) / n, 4),
                    "mean_return": round(sum(t["return_pct"] for t in ts) / n, 4)}
        halves_out[qk][mk] = {"first": _agg([t for t in trades if t["buy_date"] < mid]),
                              "second": _agg([t for t in trades if t["buy_date"] >= mid]),
                              "mid_date": mid}
with open(os.path.join(OUT_DIR, "hold_sweep_halves.json"), "w", encoding="utf-8") as f:
    json.dump(halves_out, f, ensure_ascii=False, separators=(",", ":"), indent=1)
print(f"✓ {OUT_DIR}/hold_sweep_halves.json")

# ── 7. 逐笔 compact 导出一份(供回撤/极端窗口专项深挖) ──
trades_out = {"quadrants": {}}
for qk in skb.QUADRANT_META:
    trades_out["quadrants"][qk] = {}
    for mk in FIXED_HD_MODES:
        trades_out["quadrants"][qk][mk] = [
            [t["buy_date"], round(t["profit"], 2), round(t["return_pct"], 4),
             t.get("hold_days"), t.get("sell_date") or "", t["signal_date"], t["index_id"],
             t["signal"], t["etf_code"]]
            for t in _get_trades_from(trades_output, qk, mk)
        ]
with open(os.path.join(OUT_DIR, "hold_sweep_trades.json"), "w", encoding="utf-8") as f:
    json.dump(trades_out, f, ensure_ascii=False, separators=(",", ":"))
print(f"✓ {OUT_DIR}/hold_sweep_trades.json")

# ── 8. 汇总打印: 16 象限平均的固定持有期收益曲线 ──
print("\n=== 16 象限平均(各周期 all)总收益率 total_return_pct 随持有期 ===")
agg = {}
for mk in FIXED_HD_MODES:
    vals = []
    for qk in skb.QUADRANT_META:
        s = output["quadrants"][qk]["periods"]["all"][mk]
        if s["n"] > 0:
            vals.append(s)
    if vals:
        n = sum(v["n"] for v in vals)
        profit = sum(v["total_profit"] for v in vals)
        wr = sum(v["win_count"] for v in vals) / n
        agg[mk] = {"n": n, "total_profit": round(profit, 2),
                   "total_return_pct": round(profit / (n * skb.BUY_AMOUNT) * 100, 4),
                   "win_rate": round(wr, 4)}
        hd = skb.SELL_MODES[mk]["hold_days"]
        print(f"  持有{hd:2d}天: n={n:6d} 总净利={agg[mk]['total_profit']:>11,.2f} 总收益率={agg[mk]['total_return_pct']:>8.4f}% 胜率={agg[mk]['win_rate']:.4f}")

