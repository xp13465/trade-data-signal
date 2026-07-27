"""一次性 backfill：重算 futures_accuracy 7/15 窗口全历史数据。

计算 5品种 × 3角色 × 2新窗口(7,15) × 全历史日期，插入 futures_accuracy 表。
现有 30/60/120 窗口数据不受影响（INSERT OR REPLACE 按 date+variety+role+window 主键去重）。

运行：cd /Users/linhuichen/code/trade-data && /Users/linhuichen/code/trade/.venv/bin/python /Users/linhuichen/code/trade/scripts/backfill_futures_acc_7_15.py
"""
import sys
from pathlib import Path

# 必须从 trade-data 侧 import app（trade-data/app 是指向 trade/app 的 symlink），
# 这样 app/db.py 的 __file__ 解析为 trade-data/app/db.py，
# DB_PATH = trade-data/data/sentiment.db (主库)。
# 若从 trade/ 侧 import，DB_PATH 会指向 trade/data/sentiment.db (滞后镜像，写不到主库)。
TRADE_DATA = Path("/Users/linhuichen/code/trade-data")
sys.path.insert(0, str(TRADE_DATA))

from app.compute.futures_position import compute_accuracy


if __name__ == "__main__":
    n = compute_accuracy(date=None, windows=[7, 15])
    print(f"=== 7/15 窗口 backfill 完成: {n} 行 ===")
