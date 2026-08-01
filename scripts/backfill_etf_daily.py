#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""补采 ETF 历史 K 线入 etf_daily 表（方案D+F 治本，2026-07-28）。

背景：方案F 用 min_data_days=252 过滤次新 ETF 防 5 窗口退化。但 etf_daily 表中
1371 只 ETF 仅 21 只 >=252 天，1211 只 ok ETF 数据 <252 天（1146 只仅 101-170 天）。
export_etf_score_list.py FETCH_DAYS=252 只采近 252 天 + 只覆盖评分列表 ETF，行业 ETF
根本没被持续采集历史，导致 252 天过滤后 board_etf_map.json 行业 ETF 全空。

正解：补采 ETF 历史 K 线入 etf_daily，让行业 ETF 数据 >=252 天自然恢复。252 天阈值
正确保留不降（降阈值 y1 窗口仍退化）。

数据源：akshare fund_etf_hist_sina（新浪源，返回全史，不复权）。
  - 东财 fund_etf_hist_em（qfq 前复权）被 ban 返回 Empty reply，无法用
  - 新浪源字段：date/open/high/low/close/volume/amount/postVol/postAmt
  - 覆盖 etf_daily 所需 date/open/high/low/close/amount（弃 volume/postVol/postAmt）
  - symbol 需带前缀：5/6 开头=sh，1 开头=sz
  - etf_name 从 data/etf_index_map.json[code]['name'] 取

入库策略：UPSERT + COALESCE 保护已有数据。
  - 主键 (date, etf_code)
  - ON CONFLICT 时 close/amount/open/high/low 用 COALESCE(etf_daily.X, excluded.X)
    只在原值为 NULL 时补新值，不覆盖已有 close
  - fund_share/share_change/share_change_pct 等汪汪队字段完全不动（不在 SET 里）
  - etf_name 用 COALESCE(NULLIF(...,''), excluded) 只在空时补

用法：
  python scripts/backfill_etf_daily.py --limit 5        # 测试
  python scripts/backfill_etf_daily.py --only-industry  # 只补行业/宽基ETF（board_etf_map.json出现+INDEX_TRACK_MAP命中）
  python scripts/backfill_etf_daily.py                  # 全量补采所有 ok ETF（治本）
"""
import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

import akshare as ak
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent  # trade/

ETF_INDEX_MAP_PATH = ROOT / "data" / "etf_index_map.json"
BOARD_ETF_MAP_PATH = ROOT / "data" / "board_etf_map.json"


def _get_etf_db_path() -> Path:
    """ETF DB 路径：优先 trade-data/data/etf_national_team.db（主库）。
    与 build_board_etf_map.py / simulate_trade.py 一致。"""
    main = ROOT.parent / "trade-data" / "data" / "etf_national_team.db"
    if main.exists():
        return main
    return ROOT / "data" / "etf_national_team.db"


def _to_symbol(code: str) -> str:
    """ETF 代码转新浪 symbol（带市场前缀）。
    5/6 开头=沪市 sh（51xxxx/56xxxx/58xxxx），1 开头=深市 sz（15xxxx/16xxxx/18xxxx）。
    """
    code = str(code).strip().zfill(6)
    if code.startswith(("5", "6")):
        return f"sh{code}"
    if code.startswith("1"):
        return f"sz{code}"
    return ""  # 其他前缀（如 0 开头非 ETF）跳过


def _load_etf_index_map() -> dict:
    """读 etf_index_map.json，返回 {code: info}。"""
    if not ETF_INDEX_MAP_PATH.exists():
        print(f"⚠ etf_index_map.json 不存在: {ETF_INDEX_MAP_PATH}")
        return {}
    with open(ETF_INDEX_MAP_PATH, encoding="utf-8") as f:
        return json.load(f)


def _load_board_etf_codes() -> set:
    """读 board_etf_map.json，返回当前出现的所有 ETF 代码集合。"""
    if not BOARD_ETF_MAP_PATH.exists():
        return set()
    with open(BOARD_ETF_MAP_PATH, encoding="utf-8") as f:
        bm = json.load(f)
    codes = set()
    for k, v in bm.items():
        if k == "_meta" or not isinstance(v, list):
            continue
        for e in v:
            if isinstance(e, dict) and e.get("code"):
                codes.add(str(e["code"]).zfill(6))
    return codes


def _get_industry_priority_codes(etf_map: dict) -> list:
    """行业优先级清单：board_etf_map.json 出现的 ETF + 宽基/红利/港股指数跟踪 ETF。
    用于 --only-industry 模式，快速恢复行业 ETF 映射。
    """
    codes = _load_board_etf_codes()
    # 同时纳入 INDEX_TRACK_MAP 命中的宽基/红利/港股 ETF（track_index_code 在 INDEX_TRACK_MAP.values().code）
    index_codes = {"000001", "399001", "000300", "000016", "000905", "000852",
                   "399006", "000688", "000922", "930955", "399324", "HSI", "HSTECH", "HSCEI"}
    for code, info in etf_map.items():
        if not isinstance(info, dict) or info.get("status") != "ok":
            continue
        if info.get("track_index_code") in index_codes:
            codes.add(str(code).zfill(6))
    return sorted(codes)


def fetch_etf_hist(symbol: str, retries: int = 3) -> pd.DataFrame | None:
    """拉单只 ETF 全史 K 线，带重试。失败返回 None。"""
    for i in range(retries):
        try:
            df = ak.fund_etf_hist_sina(symbol=symbol)
            if df is None or len(df) == 0:
                return None
            return df
        except Exception as e:
            if i < retries - 1:
                time.sleep(1.0 * (i + 1))  # 递增退避
            else:
                print(f"    [失败] {symbol}: {type(e).__name__}: {e}")
                return None
    return None


def upsert_etf_daily(conn: sqlite3.Connection, rows: list[tuple]) -> int:
    """UPSERT 批量写入 etf_daily。
    rows: [(date, etf_code, etf_name, close, amount, open, high, low), ...]
    用 COALESCE 保护已有数据（只补 NULL 字段，不覆盖 close/fund_share 等）。
    返回实际插入/更新的行数。
    """
    if not rows:
        return 0
    sql = """
    INSERT INTO etf_daily(date, etf_code, etf_name, close, amount, open, high, low)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(date, etf_code) DO UPDATE SET
      close = COALESCE(etf_daily.close, excluded.close),
      amount = COALESCE(etf_daily.amount, excluded.amount),
      open = COALESCE(etf_daily.open, excluded.open),
      high = COALESCE(etf_daily.high, excluded.high),
      low = COALESCE(etf_daily.low, excluded.low),
      etf_name = COALESCE(NULLIF(etf_daily.etf_name, ''), excluded.etf_name)
    """
    cur = conn.cursor()
    cur.executemany(sql, rows)
    return cur.rowcount


def backfill_one(conn: sqlite3.Connection, code: str, etf_name: str) -> tuple[int, str]:
    """补采单只 ETF。返回 (入库行数, 状态描述)。"""
    symbol = _to_symbol(code)
    if not symbol:
        return 0, f"skip(代码前缀未知:{code})"
    df = fetch_etf_hist(symbol)
    if df is None or len(df) == 0:
        return 0, "fetch_fail"
    # 字段映射：新浪源 date/open/high/low/close/volume/amount
    # date 转 YYYYMMDD（etf_daily 表 date 格式是 20050223 这种）
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y%m%d")
    rows = []
    for _, r in df.iterrows():
        try:
            rows.append((
                str(r["date"]),
                code,
                etf_name,
                float(r["close"]) if pd.notna(r["close"]) else None,
                float(r["amount"]) if pd.notna(r["amount"]) else None,
                float(r["open"]) if pd.notna(r["open"]) else None,
                float(r["high"]) if pd.notna(r["high"]) else None,
                float(r["low"]) if pd.notna(r["low"]) else None,
            ))
        except (ValueError, TypeError):
            continue
    n = upsert_etf_daily(conn, rows)
    conn.commit()
    return n, f"ok({len(df)}天->{n}行)"


def main():
    ap = argparse.ArgumentParser(description="补采 ETF 历史 K 线入 etf_daily")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 只（0=不限）")
    ap.add_argument("--only-industry", action="store_true",
                    help="只补行业/宽基ETF（board_etf_map.json出现+INDEX_TRACK_MAP命中），跳过冷门")
    ap.add_argument("--sleep", type=float, default=0.35, help="每次请求间隔秒数（防ban）")
    args = ap.parse_args()

    db_path = _get_etf_db_path()
    print(f"ETF DB: {db_path}")
    print(f"数据源: akshare fund_etf_hist_sina (新浪, 全史, 不复权)")
    print(f"参数: limit={args.limit}, only_industry={args.only_industry}, sleep={args.sleep}s")

    etf_map = _load_etf_index_map()
    if not etf_map:
        print("✗ etf_index_map.json 读不到，退出")
        return 1

    # 确定补采清单
    if args.only_industry:
        codes = _get_industry_priority_codes(etf_map)
        print(f"--only-industry: 优先清单 {len(codes)} 只（board_etf_map.json + INDEX_TRACK_MAP命中）")
    else:
        codes = [c for c, info in etf_map.items()
                 if isinstance(info, dict) and info.get("status") == "ok"]
        codes = sorted(codes)
        print(f"全量补采: etf_index_map.json status=ok 共 {len(codes)} 只")

    if args.limit > 0:
        codes = codes[:args.limit]
        print(f"--limit {args.limit}: 只跑前 {len(codes)} 只")

    # 查当前 etf_daily 已有天数（补采前快照，便于对比）
    conn = sqlite3.connect(str(db_path), timeout=30.0)
    ph = ",".join("?" * len(codes)) if codes else "''"
    existing = dict(conn.execute(
        f"SELECT etf_code, COUNT(*) FROM etf_daily "
        f"WHERE etf_code IN ({ph}) AND close IS NOT NULL GROUP BY etf_code",
        codes,
    ).fetchall())
    print(f"\n补采前: {sum(1 for c in codes if existing.get(c,0)>=252)}/{len(codes)} 只 >=252天")
    print(f"开始补采...")

    t_start = time.time()
    total_rows = 0
    success = 0
    fail = 0
    fail_codes = []
    progress_file = "/tmp/agent-progress-etf-backfill.md"

    for i, code in enumerate(codes, 1):
        info = etf_map.get(code, {})
        etf_name = info.get("name", "") if isinstance(info, dict) else ""
        t0 = time.time()
        try:
            n, status = backfill_one(conn, code, etf_name)
            total_rows += n
            if "ok" in status:
                success += 1
            else:
                fail += 1
                fail_codes.append((code, status))
        except Exception as e:
            n = 0
            status = f"err:{type(e).__name__}"
            fail += 1
            fail_codes.append((code, status))
        dt = time.time() - t0
        # 每50只或最后一只 echo 进度
        if i % 50 == 0 or i == len(codes):
            elapsed = time.time() - t_start
            rate = i / elapsed if elapsed > 0 else 0
            eta = (len(codes) - i) / rate if rate > 0 else 0
            # 重查这批里>=252天的
            now_good = sum(1 for c in codes[:i] if existing.get(c, 0) >= 252 or
                           # 补采后查一次太慢，用 fetch 返回的行数估算
                           False)
            msg = (f"  [{i}/{len(codes)}] {code} {etf_name[:12]:<12} {status} "
                   f"({dt:.2f}s) | 累计成功{success}失败{fail} 入库{total_rows}行 | "
                   f"elapsed={elapsed:.0f}s eta={eta:.0f}s")
            print(msg)
            # echo 到进度文件
            with open(progress_file, "a", encoding="utf-8") as f:
                f.write(f"\n[{time.strftime('%H:%M:%S')}] 进度 {i}/{len(codes)} "
                        f"成功{success} 失败{fail} 入库{total_rows}行 "
                        f"elapsed={elapsed:.0f}s eta={eta:.0f}s\n")
        time.sleep(args.sleep)

    conn.close()
    elapsed = time.time() - t_start

    # 补采后重查 >=252 天数
    conn = sqlite3.connect(str(db_path), timeout=30.0)
    ph = ",".join("?" * len(codes)) if codes else "''"
    after = dict(conn.execute(
        f"SELECT etf_code, COUNT(*) FROM etf_daily "
        f"WHERE etf_code IN ({ph}) AND close IS NOT NULL GROUP BY etf_code",
        codes,
    ).fetchall())
    after_good = sum(1 for c in codes if after.get(c, 0) >= 252)
    conn.close()

    print(f"\n=== 补采完成 ===")
    print(f"总数 {len(codes)} 只 | 成功 {success} | 失败 {fail} | 入库 {total_rows} 行")
    print(f"耗时 {elapsed:.0f}s ({elapsed/60:.1f}分钟)")
    print(f">=252天: 补采前 {sum(1 for c in codes if existing.get(c,0)>=252)}/{len(codes)} "
          f"-> 补采后 {after_good}/{len(codes)}")
    if fail_codes:
        print(f"\n失败清单({len(fail_codes)}只, 前20):")
        for c, s in fail_codes[:20]:
            print(f"  {c}: {s}")

    # 最终 echo
    with open(progress_file, "a", encoding="utf-8") as f:
        f.write(f"\n### 补采完成 - {time.strftime('%H:%M:%S')}\n")
        f.write(f"总数{len(codes)} 成功{success} 失败{fail} 入库{total_rows}行 耗时{elapsed:.0f}s\n")
        f.write(f">=252天: {sum(1 for c in codes if existing.get(c,0)>=252)} -> {after_good}\n")
        if fail_codes:
            f.write(f"失败{len(fail_codes)}只: {fail_codes[:10]}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
