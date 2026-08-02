#!/usr/bin/env python3
"""公募基金筛选器阶段0: 导出 offshore_fund_*.json 到 static-site/data/。

从 public_fund.db 7 张表(fund_basic 扩展 + 6 新表)导出 JSON 产物:
  1. offshore_fund_basic.json          fund_basic 全量(27409只×21列)
  2. offshore_fund_performance.json    9区间收益率(20070只)
  3. offshore_fund_rating.json         4家评级(18096只)
  4. offshore_fund_purchase_status.json 申赎状态(27115只)
  5. offshore_fund_manager.json        基金经理(35436行)
  6. offshore_fund_risk_indicator.json 风险指标(逐只3周期)
  7. offshore_fund_fee_detail.json     费率分档(逐只9档)

输出路径: static-site/data/(deploy.sh rsync 同步到 trade/static-site/data/ 推 git)
R2 上传: upload_r2.py upload-offshore-fund(§8.1 新类别按前缀命令)

用法: python scripts/export_offshore_fund.py
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
import sys
import time
from pathlib import Path

# 从 trade-data/app 读 DB(symlink 指向 trade/app, 代码不变)
SCRIPT_DIR = Path(__file__).absolute().parent
REPO = SCRIPT_DIR.parent
sys.path.insert(0, str(REPO))

from app.collector.public_fund import DB_PATH, STATIC_DATA_DIR


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn


def _rows_to_dicts(rows) -> list[dict]:
    """sqlite3.Row 列表 -> dict 列表(None 保留, 空字符串转 None)。"""
    result = []
    for r in rows:
        d = {}
        for k in r.keys():
            v = r[k]
            d[k] = v if v != "" else None
        result.append(d)
    return result


def _write_json(fname: str, data: list[dict], date_str: str) -> int:
    """写 JSON 到 STATIC_DATA_DIR, 返回字节数。"""
    STATIC_DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"date": date_str, "count": len(data), "data": data}
    path = STATIC_DATA_DIR / fname
    path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8")
    size = path.stat().st_size
    print(f"  [export] {fname} ({len(data)} rows, {size} bytes)", flush=True)
    return size


def main():
    t0 = time.time()
    today = dt.date.today().strftime("%Y%m%d")
    print(f"[export_offshore_fund] 导出 7 类 JSON -> {STATIC_DATA_DIR}", flush=True)
    conn = get_conn()
    try:
        # 1. fund_basic 全量(27409只×21列, 含15新列)
        rows = conn.execute(
            "SELECT fund_code, fund_name, fund_type, pinyin_abbr, pinyin_full, "
            "update_date, fund_company, fund_manager, setup_date, scale, "
            "management_fee, custody_fee, purchase_fee, custodian, strategy, "
            "benchmark, tracking_target, issue_date, share_scale, service_fee, "
            "dividend_total FROM fund_basic ORDER BY fund_code"
        ).fetchall()
        _write_json("offshore_fund_basic.json", _rows_to_dicts(rows), today)

        # 2. fund_performance 9区间收益率(取最新update_date)
        rows = conn.execute(
            "SELECT fund_code, update_date, unit_nav, acc_nav, day_growth, "
            "return_1w, return_1m, return_3m, return_6m, return_1y, return_2y, "
            "return_3y, return_ytd, return_since_inception, fee_rate "
            "FROM fund_performance ORDER BY fund_code"
        ).fetchall()
        _write_json("offshore_fund_performance.json", _rows_to_dicts(rows), today)

        # 3. fund_rating 4家评级(取最新rating_date)
        rows = conn.execute(
            "SELECT fund_code, rating_date, shanghai_securities, cms, jajx, "
            "morningstar, five_star_count FROM fund_rating ORDER BY fund_code"
        ).fetchall()
        _write_json("offshore_fund_rating.json", _rows_to_dicts(rows), today)

        # 4. fund_purchase_status 申赎状态(取最新update_date)
        rows = conn.execute(
            "SELECT fund_code, update_date, purchase_status, redeem_status, "
            "next_open_date, purchase_min, daily_limit "
            "FROM fund_purchase_status ORDER BY fund_code"
        ).fetchall()
        _write_json("offshore_fund_purchase_status.json", _rows_to_dicts(rows), today)

        # 5. fund_manager 基金经理(含appoint_date自爬+managed_history)
        rows = conn.execute(
            "SELECT fund_code, manager_name, appoint_date, managed_count, "
            "managed_scale, best_return, managed_history, tenure_days, work_days "
            "FROM fund_manager ORDER BY fund_code"
        ).fetchall()
        # managed_history 是 JSON 字符串, 转成 dict/list 便于前端用
        mgr_data = []
        for r in rows:
            d = dict(zip(r.keys(), r))
            if d.get("managed_history"):
                try:
                    d["managed_history"] = json.loads(d["managed_history"])
                except (json.JSONDecodeError, TypeError):
                    pass  # 保留原始字符串
            mgr_data.append(d)
        _write_json("offshore_fund_manager.json", mgr_data, today)

        # 6. fund_risk_indicator 风险指标(逐只3周期)
        rows = conn.execute(
            "SELECT fund_code, period, sharpe, sortino, calmar, max_drawdown, "
            "annual_volatility, downside_risk, information_ratio, alpha, "
            "risk_return_rank, anti_risk_rank, data_source, update_date "
            "FROM fund_risk_indicator ORDER BY fund_code, period"
        ).fetchall()
        _write_json("offshore_fund_risk_indicator.json", _rows_to_dicts(rows), today)

        # 7. fund_fee_detail 费率分档(逐只9档)
        rows = conn.execute(
            "SELECT fund_code, fee_type, tier_index, condition_desc, fee_rate, "
            "update_date FROM fund_fee_detail ORDER BY fund_code, fee_type, tier_index"
        ).fetchall()
        _write_json("offshore_fund_fee_detail.json", _rows_to_dicts(rows), today)
    finally:
        conn.close()
    print(f"[export_offshore_fund] 完成 7 类 JSON, 耗时={time.time()-t0:.1f}s", flush=True)


if __name__ == "__main__":
    main()
