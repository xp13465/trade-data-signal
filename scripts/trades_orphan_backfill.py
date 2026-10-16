#!/usr/bin/env python3
"""T2 止血(只读候选清单):冻结表「孤儿买事件」→ 次日开盘价补账候选。

背景(docs/ops/trades-wipe-rootfix-20261014.md)
------------------------------------------------
`signal_daily` 每日全表 DELETE+INSERT 重算(app/compute/signals.py::store),上游 `index_daily`
被整段 UPSERT 重写后,重算吐不出原本存在的历史 buy 行 ⇒ 冻结表里 `frozen_at` 齐全、次日价也齐的
信号事件「凭空消失」(既不成账、也不报孤儿)。10-12 实测 6 条 buy 键(frozen_at=2026-10-12 16:38)
在现值 signal_daily 全无。

本脚本定位 = **止血候选清单生成器,只读**:
  · 只 SELECT,不 UPDATE / 不 INSERT / 不 DELETE;
  · **绝不往 signal_daily 插行** —— 那样下一次全表重算会再次把它抹掉(治标不治本,且制造假账);
  · 补账的去向是 T2「冻结表优先」入账源(scripts/signal_kelly_backtest.py,
    env SIGNAL_KELLY_FREEZE_UNION=1),须用户拍板后才翻默认(§23.7 冻结契约 / §5.4⑥)。

防前视(§5.1⑥)
--------------
买价恒取「信号日之后第一个有行情日的 open」——信号日 t 收盘出信号,t+1 开盘成交,
不使用任何 t 当日/之后已知的收盘信息。

真实执行前置(本脚本不自己执行,须主控批准窗口)
--------------------------------------------
  ① §25 备份并实测可恢复;
  ② §14 时点窗口:盘中 09:30-15:30 / 盘后 15:35·16:00·17:50·20:35·22:00 不写生产 DB(应急同样不豁免);
  ③ 主控批准窗口后再跑;默认 `--out` 缺省只打印 stdout(不落盘)。

用法
----
  python3 scripts/trades_orphan_backfill.py                    # 打印候选 JSON 到 stdout
  python3 scripts/trades_orphan_backfill.py --out /tmp/cands.json
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPT_DIR)


def _skb():
    """惰性 import signal_kelly_backtest(单一事实源: 冻结键筛选/孤儿判据/路径解析零漂移)。"""
    if SCRIPT_DIR not in sys.path:
        sys.path.insert(0, SCRIPT_DIR)
    import signal_kelly_backtest as skb  # noqa: PLC0415
    return skb


def _ro_connect(path):
    """只读连接(mode=ro URI);路径不存在直接 raise,不静默建空库。"""
    if not os.path.exists(path):
        raise FileNotFoundError(f"只读源不存在: {path}")
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30.0)


def load_present_di(db_path):
    """现值 signal_daily 的全部 (date, index_id) 集合(只读)。"""
    conn = _ro_connect(db_path)
    try:
        return {(r[0], r[1]) for r in conn.execute(
            "SELECT DISTINCT date, index_id FROM signal_daily")}
    finally:
        conn.close()


def load_etf_opens(etf_db_path, codes):
    """批量读 etf_daily 的 (code, date, open),仅取 open 非空行。返回 {code: [(date, open), ...]}(按日期升序)。"""
    codes = sorted({c for c in codes if c})
    if not codes:
        return {}
    out = {}
    conn = _ro_connect(etf_db_path)
    try:
        CH = 500
        for i in range(0, len(codes), CH):
            chunk = codes[i:i + CH]
            ph = ",".join("?" * len(chunk))
            for code, date, op in conn.execute(
                f"SELECT etf_code, date, open FROM etf_daily "
                f"WHERE etf_code IN ({ph}) AND open IS NOT NULL ORDER BY etf_code, date",
                chunk,
            ):
                out.setdefault(code, []).append((date, op))
    finally:
        conn.close()
    return out


def next_open_after(opens_for_code, sig_date):
    """信号日之后第一个有行情日的 open(t+1 成交,防前视)。无则返回 (None, None)。"""
    for date, op in opens_for_code:
        if date > sig_date:
            return date, op
    return None, None


def build_candidates(freeze, present_di, etf_db_path):
    """生成补账候选(只读纯函数)。返回 (candidates, stats)。"""
    skb = _skb()
    orphans = skb._detect_freeze_orphan_buy_events(freeze, present_di)
    codes = set()
    for d, iid, sig in orphans:
        entry = freeze.get(f"{d}|{iid}|{sig}") or {}
        if entry.get("code"):
            codes.add(entry["code"])
    opens_map = load_etf_opens(etf_db_path, codes)

    candidates = []
    no_price = []
    for d, iid, sig in orphans:
        entry = freeze.get(f"{d}|{iid}|{sig}") or {}
        code = entry.get("code")
        name = entry.get("name")
        buy_date, buy_open = (None, None)
        if code:
            buy_date, buy_open = next_open_after(opens_map.get(code, []), d)
        if buy_date is None or buy_open is None:
            no_price.append({"date": d, "index_id": iid, "signal": sig,
                             "etf_code": code, "reason": "次日无行情(open 缺失)"})
            continue
        candidates.append({
            "date": d, "index_id": iid, "signal": sig,
            "etf_code": code, "etf_name": name,
            "buy_date": buy_date, "buy_price": buy_open,   # 次日 open,防前视
            "frozen_at": entry.get("frozen_at"),
            "source": "freeze_table_orphan",
        })
    stats = {
        "orphan_events": len(orphans),
        "candidates": len(candidates),
        "no_price": len(no_price),
        "note": "只读清单;绝不写 signal_daily(T2 冻结表优先入账待用户拍板)",
    }
    return {"candidates": candidates, "skipped_no_price": no_price, "stats": stats}


def build_registry(result, generated_at=None):
    """把候选清单(含 no_price 跳过项)转成 #252 定向补账登记表结构(引擎读它补账, 见 signal_kelly_backtest)。

    keys 取**全部孤儿事件**(候选 + 跳过): 「次日无行情」只是那天价还没到(正常 T+1 时点问题),
    事件本体仍是真孤儿; 何时补得上由引擎按当时的 etf_daily 决定, 登记表不预判。
    本函数是该 JSON 格式的**唯一定义处**(防第二份实现漂移 §5.4⑦)。
    """
    keys = sorted(
        {f"{c['date']}|{c['index_id']}|{c['signal']}" for c in result.get("candidates", [])}
        | {f"{s['date']}|{s['index_id']}|{s['signal']}" for s in result.get("skipped_no_price", [])}
    )
    if generated_at is None:
        import datetime  # noqa: PLC0415
        generated_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return {
        "generated_at": generated_at,
        "purpose": "#252 A1 定向补账:冻结表孤儿买事件 → 引擎入账侧补入白名单(只补这些键, 不翻 T2 全局 union 默认)",
        "generated_by": "scripts/trades_orphan_backfill.py --registry-out",
        "counts": result.get("stats", {}),
        "keys": keys,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="冻结表孤儿买事件 → 次日开盘价补账候选(只读)")
    ap.add_argument("--freeze", default=None, help="冻结表 JSON(默认 SIGNAL_KELLY_ETF_FREEZE_PATH 或 data/)")
    ap.add_argument("--db", default=os.path.join(ROOT, "data", "sentiment.db"), help="主库(含 signal_daily),只读")
    ap.add_argument("--etf-db", default=None, help="ETF 库(含 etf_daily),只读;默认走 _get_etf_db_path()")
    ap.add_argument("--out", default=None, help="输出 JSON 路径;缺省打印 stdout")
    ap.add_argument("--registry-out", default=None, metavar="FILE",
                    help="另写 #252 定向补账登记表(引擎读 config/signal_kelly_freeze_orphan_backfill.json)")
    args = ap.parse_args(argv)

    skb = _skb()
    freeze_path = args.freeze or skb._etf_freeze_path()
    etf_db = args.etf_db or skb._get_etf_db_path()
    freeze = skb._load_etf_freeze() if args.freeze is None else json.load(open(args.freeze, encoding="utf-8"))
    present_di = load_present_di(args.db)
    result = build_candidates(freeze, present_di, etf_db)
    result["meta"] = {
        "freeze": freeze_path, "db": args.db, "etf_db": etf_db,
        "freeze_keys": len(freeze), "present_di": len(present_di),
        "readonly": True,
    }
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.registry_out:
        reg = build_registry(result)
        reg["meta"] = result["meta"]
        with open(args.registry_out, "w", encoding="utf-8") as f:
            f.write(json.dumps(reg, ensure_ascii=False, indent=2) + "\n")
        print(f"✓ 定向补账登记表已写 {args.registry_out}({len(reg['keys'])} 键;只读生成,未改任何 DB)",
              file=sys.stderr)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print(f"✓ 候选清单已写 {args.out}(只读生成,未改任何 DB)", file=sys.stderr)
    elif not args.registry_out:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())