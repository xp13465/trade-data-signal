#!/usr/bin/env python3
"""codex-002 high 自验: _export_lab_slices/_export_trades_parts 原子写功能测试。

目的: 验证 ①导出跑通 ②产物内容与源一致 ③无 .tmp 残留 ④历史 .tmp 残留被清理。
输入: 构造的小型 signal_kelly_trades.json(非生产数据, /tmp 下)。
输出: 断言全过打印 ATOMIC_EXPORT_TEST_OK。
复现: python3 docs/kelly/scripts/kelly_atomic_export_test.py
"""
import json
import os
import shutil
import subprocess
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
TMP = "/tmp/kelly-atomic-test"

shutil.rmtree(TMP, ignore_errors=True)
os.makedirs(TMP + "/static-site/data/signal_kelly_trades_parts")
rows_a = [["20260801", "idx1", "buy", "20260802", "ETF一", "1.0", "1.1", "10000", "50.5", "0.5", "10", "sell_ok"] for _ in range(5)]
rows_b = [["20260601", "idx2", "buy", "20260602", "ETF二", "2.0", "2.2", "10000", "-30.0", "-0.3", "20", "stop_loss"] for _ in range(3)]
td = {"generated_at": "2026-08-25 09:00", "buy_amount": 10000,
      "period_cutoffs": {"y1": "20250825", "all": "0"},
      "fields": ["signal_date", "index_id", "signal", "buy_date", "etf_name", "buy_price", "sell_price", "shares", "profit", "return_pct", "hold_days", "sell_reason"],
      "quadrants": {"rating_high": {"A": rows_a, "B": rows_b}}}
json.dump(td, open(TMP + "/static-site/data/signal_kelly_trades.json", "w"), ensure_ascii=False)
# 人为放一个历史中断残留 tmp, 应被导出收尾清理
open(TMP + "/static-site/data/signal_kelly_trades_parts/lab_old__Z_p1.json.12345.999999.tmp", "w").write("半截残留")

r = subprocess.run([sys.executable, os.path.join(REPO, "scripts/signal_kelly_backtest.py"),
                    "--export-lab-slices-only",
                    "--trades-output", TMP + "/static-site/data/signal_kelly_trades.json"],
                   capture_output=True, text=True, cwd=REPO)
print(r.stdout.strip()[-300:])
print("STDERR:", r.stderr.strip()[:200])

pd = TMP + "/static-site/data/signal_kelly_trades_parts"
files = sorted(os.listdir(pd))
print("FILES:", files)
assert not any(f.endswith(".tmp") for f in files), "tmp 残留!"
meta = json.load(open(pd + "/lab_meta.json"))
assert meta["generated_at"] == "2026-08-25 09:00"
p1 = json.load(open(pd + "/lab_rating_high__A_p1.json"))
assert p1["quadrants"]["rating_high"]["A"] == rows_a, "片内容不一致"
print("ATOMIC_EXPORT_TEST_OK")
