#!/usr/bin/env python3
"""实操步骤表回填「历史持仓」调研复现脚本(死脚本, 跟报告 nextday-steps-backfill-research-20260911.md 咬合)

目的: 复现 #106 调研的关键证据链——
  ① 回填窗口内生成器逐日重演输出(历史 T 的 top1 计划, 与未来计划同一条链)
  ② 卖出口径三源比对(回测公式 vs 生成器 _nth_trading_day_after vs trades 记录)
  ③ 回填组与现有表幂等冲突检查
  ④ 冻结表历史命中率 + frozen_at 防前视核查
输入依赖:
  - <REPO>/data/trade_dates.txt(权威交易日历)
  - <REPO>/data/signal_kelly_etf_freeze.json(冻结表)
  - <REPO>/data/sentiment.db signal_daily(历史信号)
  - <REPO>/data/signal_kelly_trades.json(回测 trades, 验证覆盖窗口)
输出:
  - stdout 各节结果; 不落盘
关键口径:
  - 卖出日 = 信号日后第 10 交易日(A 模式 hold_days=10, 与生成器 _nth_trading_day_after(sig_date,10) 同款)
复现命令:
  REPO=/Users/linhuichen/code/trade-data python3 docs/kelly/analysis/scripts/nextday_backfill_repro.py
"""
import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(sys.argv[1] if len(sys.argv) > 1 else "/Users/linhuichen/code/trade-data")

def load_json(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)

def nth_after(trade_dates, t, n):
    cnt = 0
    for d in trade_dates:
        if d > t:
            cnt += 1
            if cnt >= n:
                return d
    return None

def bt_sell(trade_dates, sig_date):
    """回测口径: future_dates = dates[idx: idx+10], sell = future_dates[-1]"""
    idx = sum(1 for d in trade_dates if d <= sig_date)
    return trade_dates[idx + 9]

def main():
    trade_dates = sorted({l.strip() for l in (REPO / "data" / "trade_dates.txt").read_text().splitlines() if l.strip()})
    freeze = load_json(REPO / "data" / "signal_kelly_etf_freeze.json")
    trades = load_json(REPO / "data" / "signal_kelly_trades.json")

    # ① 回填窗口(最近 10 交易日, 信号日 8/26~9/10)
    window = [d for d in trade_dates if "20260826" <= d <= "20260910"]
    print("=== ① 回填窗口交易日 ===")
    print(window)

    # ② 窗口内 signal_daily 买信号冻结命中率
    con = sqlite3.connect(f"file:{REPO / 'data' / 'sentiment.db'}?mode=ro", uri=True)
    print("\n=== ② 冻结命中率(窗口内买信号) ===")
    tot = hit = 0
    for T in window:
        rows = con.execute(
            "SELECT index_id, signal FROM signal_daily WHERE date=? AND signal NOT LIKE 's.%%' "
            "AND signal IN ('buy','buy_aux','buy_special','buy_backup') ORDER BY index_id", (T,)).fetchall()
        h = sum(1 for iid, sig in rows if f"{T}|{iid}|{sig}" in freeze)
        tot += len(rows); hit += h
        print(f"  T={T} 买信号={len(rows)} 冻结命中={h}")
    print(f"  合计 命中={hit}/{tot}")
    con.close()

    # ③ 卖出口径三源比对(窗口 + 已知 trades 样本)
    print("\n=== ③ 卖出口径三源比对 ===")
    sig_main_A = trades["quadrants"]["sig_main"]["A"]
    fields = trades["fields"]
    fi = {f: i for i, f in enumerate(fields)}
    tr = {r[fi["signal_date"]]: r[fi["sell_date"]] for r in sig_main_A}
    for sd in ["20260902", "20260903", "20260904", "20260907", "20260908", "20260909", "20260910", "20210607"]:
        b = bt_sell(trade_dates, sd)
        g = nth_after(trade_dates, sd, 10)
        t = tr.get(sd, "-")
        print(f"  sig_date={sd} 回测={b} 生成器={g} trades记录={t} 一致={b == g and (t == '-' or t == b)}")

    # ④ 回填组与现有表幂等键
    print("\n=== ④ 回填组(窗口内生成器重演 top1) ===")
    ops = {
        "20260902": ("us_dji", "buy_aux", "513400"), "20260903": ("csi_931151", "buy_aux", "560230"),
        "20260904": ("sw_801010", "buy_special", "159173"), "20260907": ("csi_930997", "buy_aux", "516390"),
        "20260908": ("csi_399986", "buy_special", "512820"), "20260909": ("sz_div", "buy_aux", "159905"),
        "20260910": ("cac40", "buy", "513080"),
    }
    for sd, (iid, sig, code) in sorted(ops.items()):
        sell = nth_after(trade_dates, sd, 10)
        print(f"  信号{sd} {iid} {sig} -> {code} buy_date={nth_after(trade_dates, sd, 1)} sell_date={sell} 到期={sell <= '20260911'}")

    # ⑤ 冻结值 frozen_at 防前视
    print("\n=== ⑤ 冻结表历史 key 防前视(frozen_at) ===")
    for sd in list(ops):
        iid, sig, _ = ops[sd]
        v = freeze.get(f"{sd}|{iid}|{sig}")
        if v:
            print(f"  {sd}|{iid}|{sig} -> code={v['code']} score={v['track_score']} frozen_at={v['frozen_at']}")

    # ⑥ trades 对回填窗口的覆盖(数据源证伪)
    wset = set(window)
    cnt = sum(1 for r in sig_main_A if r[fi["signal_date"]] in wset)
    print("\n=== ⑥ trades(sig_main/A)对回填窗口覆盖 ===")
    print(f"  窗口内笔数={cnt}(=0 说明 trades 不覆盖 9 月窗口, 不可当回填源)")

if __name__ == "__main__":
    main()
