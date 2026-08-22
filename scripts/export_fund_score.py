#!/usr/bin/env python3
"""阶段1 评分引擎: 导出 fund_score.json + fund_score_top.json 到 static-site/data/。

从 public_fund.db fund_score 表导出 2 类 JSON:
  1. fund_score.json      头部2000只明细(按综合分降序), 含6维度+5指标+经理+凯利完整字段
  2. fund_score_top.json  Top100 精选(按综合分降序), 同结构

#79 step1 字段补齐(2026-08-22): JOIN fund_basic 带出扩展 9 字段(详情弹窗基础信息+
    #83 公募筛选器字段前置): fund_company/fund_manager/setup_date/scale/
    management_fee/custody_fee/purchase_fee/strategy/benchmark_text。
    ⚠️ b.benchmark(业绩比较基准文本)输出改名 benchmark_text, 避免覆盖
    s.benchmark(评分基准指数 hs300/csi500/gem)。
    数据覆盖率: 扩展字段由 stage0 Fetcher N fetch_fund_overview 逐只补全,
    未采集到的基金这些字段为 null(前端需容错)。

输出路径: static-site/data/(deploy.sh rsync 同步到 trade/static-site/data/ 推 git)
R2 上传: upload_r2.py upload-fund-score(§8.1 新类别按前缀命令)

用法: python scripts/export_fund_score.py [--top-n 2000]

复现: cd /Users/linhuichen/code/trade-data && .venv/bin/python scripts/export_fund_score.py --top-n 2000
依赖: data/public_fund.db (fund_score 最新 score_date + fund_basic 扩展字段)
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


def _row_to_dict(r) -> dict:
    """sqlite3.Row -> dict (None 保留, 空字符串转 None)。"""
    d = {}
    for k in r.keys():
        v = r[k]
        d[k] = v if v != "" else None
    return d


def _query_top_funds(conn: sqlite3.Connection, top_n: int) -> list[dict]:
    """查 fund_score 头部 N 只 (按综合分降序), JOIN fund_basic 拿基金名+类型+扩展字段。

    #79 step1(2026-08-22): 补 fund_company/fund_manager/setup_date/scale/
    management_fee/custody_fee/purchase_fee/strategy/benchmark_text 9 字段
    (详情弹窗基础信息区块 + #83 公募筛选器字段前置)。
    b.benchmark 改名 benchmark_text 输出, 不覆盖 s.benchmark(评分基准指数)。
    """
    rows = conn.execute(
        "SELECT s.fund_code, b.fund_name, b.fund_type, "
        "b.fund_company, b.fund_manager, b.setup_date, b.scale, "
        "b.management_fee, b.custody_fee, b.purchase_fee, "
        "b.strategy, b.benchmark AS benchmark_text, "
        "s.composite_score, s.star_rating, "
        "s.score_return, s.score_risk_adjusted, s.score_drawdown, "
        "s.score_stability, s.score_scale, s.score_fee, "
        "s.sharpe, s.sortino, s.calmar, s.information_ratio, s.alpha, "
        "s.manager_score, s.m1_tenure, s.m2_scale, s.m3_perf_stability, "
        "s.m4_drawdown, s.m5_coherence, s.m6_focus, "
        "s.kelly_fraction, s.half_kelly_position, s.kelly_win_rate, "
        "s.kelly_win_loss_ratio, s.kelly_tier, s.market_adjustment, "
        "s.final_suggestion, s.benchmark, s.score_method, "
        "s.data_completeness, s.update_date "
        "FROM fund_score s LEFT JOIN fund_basic b ON s.fund_code=b.fund_code "
        "WHERE s.score_date=(SELECT MAX(score_date) FROM fund_score) "
        "  AND s.composite_score IS NOT NULL "
        "ORDER BY s.composite_score DESC LIMIT ?",
        (top_n,)
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def _write_json(fname: str, data: list[dict], date_str: str, label: str) -> int:
    """写 JSON 到 STATIC_DATA_DIR, 返回字节数。"""
    STATIC_DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "date": date_str,
        "count": len(data),
        "method": data[0]["score_method"] if data else None,
        "data": data,
    }
    path = STATIC_DATA_DIR / fname
    path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8")
    size = path.stat().st_size
    print(f"  [export] {fname} ({label} {len(data)} rows, {size} bytes)", flush=True)
    return size


def main():
    t0 = time.time()
    top_n = 2000
    for i, a in enumerate(sys.argv[1:], 1):
        if a == "--top-n" and i + 1 < len(sys.argv):
            top_n = int(sys.argv[i + 1])

    print(f"[export_fund_score] 导出 fund_score JSON -> {STATIC_DATA_DIR} (top_n={top_n})", flush=True)
    conn = get_conn()
    try:
        # 最新 score_date
        row = conn.execute(
            "SELECT MAX(score_date) as latest, COUNT(*) as n FROM fund_score"
        ).fetchone()
        latest_date = row["latest"]
        total = row["n"]
        if not latest_date:
            print("[export_fund_score] WARN: fund_score 表为空, 请先跑 compute_all_scores", flush=True)
            return
        print(f"  最新 score_date={latest_date} 总行数={total}", flush=True)

        # 头部 top_n 只 (默认2000)
        full_data = _query_top_funds(conn, top_n)
        _write_json("fund_score.json", full_data, latest_date, "头部")

        # Top100 精选
        top100 = full_data[:100] if len(full_data) >= 100 else full_data
        _write_json("fund_score_top.json", top100, latest_date, "Top100")
    finally:
        conn.close()
    print(f"[export_fund_score] 完成, 耗时={time.time()-t0:.1f}s", flush=True)


if __name__ == "__main__":
    main()
