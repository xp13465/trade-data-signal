#!/usr/bin/env python3
"""回填 lhb_count / lhb_inst_net 6m+ 历史到 daily_metric 表。

用 ak.stock_lhb_detail_em / stock_lhb_jgmmtj_em 的 start_date/end_date 参数
分月拉取约 220 天历史（> queries.py six_m_start 的 210 天窗口），按日期分组后
upsert 到 daily_metric，使 lhb_count 卡获得标准 sparkline + 6m 分位 hover。

采集逻辑对齐 app/collector/fetchers.py:
- lhb_count:   stock_lhb_detail_em,  transform=count_rows (= len(df) 单日)
- lhb_inst_net: stock_lhb_jgmmtj_em, transform=sum, column=机构买入净额, scale=1e-8

回填按"上榜日"/"上榜日期"分组复现单日逻辑（批量版）。
写主库 /Users/linhuichen/code/trade-data/data/sentiment.db (CLAUDE.md §9)。
幂等：INSERT OR REPLACE，重复跑覆盖。
"""
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import akshare as ak

DB_PATH = Path("/Users/linhuichen/code/trade-data/data/sentiment.db")
START_OFFSET_DAYS = 220  # > 210 天(6m 窗口) 确保覆盖 six_m_start
SOURCE = "akshare"


def month_ranges(start_date: datetime, end_date: datetime):
    """从 start_date 到 end_date 按自然月分段，返回 [(start_str, end_str), ...]。"""
    ranges = []
    cur = start_date.replace(day=1)
    while cur <= end_date:
        if cur.month == 12:
            nxt = cur.replace(year=cur.year + 1, month=1)
        else:
            nxt = cur.replace(month=cur.month + 1)
        seg_end = min(nxt - timedelta(days=1), end_date)
        seg_start = max(cur, start_date)
        ranges.append((seg_start.strftime("%Y%m%d"), seg_end.strftime("%Y%m%d")))
        cur = nxt
    return ranges


def backfill_lhb_count(conn, start, end):
    """lhb_count: stock_lhb_detail_em 按"上榜日"分组 size()。"""
    df = ak.stock_lhb_detail_em(start_date=start, end_date=end)
    if df is None or len(df) == 0:
        print(f"  lhb_count   {start}-{end}: 空")
        return 0
    df = df.copy()
    df["d"] = df["上榜日"].astype(str).str.replace("-", "")
    grp = df.groupby("d").size()
    now = datetime.now().isoformat()
    n = 0
    for d, v in grp.items():
        conn.execute(
            "INSERT OR REPLACE INTO daily_metric(date, metric_id, value, source, updated_at) "
            "VALUES(?, 'lhb_count', ?, ?, ?)",
            (str(d), float(v), SOURCE, now),
        )
        n += 1
    conn.commit()
    print(f"  lhb_count   {start}-{end}: {len(df)} 行明细 -> {n} 日")
    return n


def backfill_lhb_inst_net(conn, start, end):
    """lhb_inst_net: stock_lhb_jgmmtj_em 按"上榜日期"分组 sum(机构买入净额) * 1e-8。"""
    df = ak.stock_lhb_jgmmtj_em(start_date=start, end_date=end)
    if df is None or len(df) == 0:
        print(f"  lhb_inst_net {start}-{end}: 空")
        return 0
    df = df.copy()
    df["d"] = df["上榜日期"].astype(str).str.replace("-", "")
    grp = df.groupby("d")["机构买入净额"].sum() * 1e-8  # scale=1e-8 (indicators.yaml)
    now = datetime.now().isoformat()
    n = 0
    for d, v in grp.items():
        conn.execute(
            "INSERT OR REPLACE INTO daily_metric(date, metric_id, value, source, updated_at) "
            "VALUES(?, 'lhb_inst_net', ?, ?, ?)",
            (str(d), float(v), SOURCE, now),
        )
        n += 1
    conn.commit()
    print(f"  lhb_inst_net {start}-{end}: {len(df)} 行明细 -> {n} 日")
    return n


def main():
    end_date = datetime.now()
    start_date = end_date - timedelta(days=START_OFFSET_DAYS)
    ranges = month_ranges(start_date, end_date)
    print(f"回填 {START_OFFSET_DAYS} 天历史，{len(ranges)} 段: {ranges[0][0]} ~ {ranges[-1][1]}")
    print(f"DB: {DB_PATH}")
    if not DB_PATH.exists():
        print(f"错误: DB 不存在 {DB_PATH}", file=sys.stderr)
        sys.exit(1)
    conn = sqlite3.connect(str(DB_PATH))
    total_count = 0
    total_inst = 0
    for start, end in ranges:
        print(f"=== {start} ~ {end} ===")
        try:
            total_count += backfill_lhb_count(conn, start, end)
        except Exception as e:
            print(f"  lhb_count   错误: {e}", file=sys.stderr)
        try:
            total_inst += backfill_lhb_inst_net(conn, start, end)
        except Exception as e:
            print(f"  lhb_inst_net 错误: {e}", file=sys.stderr)
        time.sleep(0.5)  # 避免限流
    cur = conn.execute("SELECT MIN(date), MAX(date), COUNT(*) FROM daily_metric WHERE metric_id='lhb_count'")
    print(f"\n完成 lhb_count: {cur.fetchone()} (本次新增/更新 {total_count} 日)")
    cur = conn.execute("SELECT MIN(date), MAX(date), COUNT(*) FROM daily_metric WHERE metric_id='lhb_inst_net'")
    print(f"完成 lhb_inst_net: {cur.fetchone()} (本次新增/更新 {total_inst} 日)")
    conn.close()


if __name__ == "__main__":
    main()
