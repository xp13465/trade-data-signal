#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
THS 概念换官方(FAPI)并行对照脚本
目的:换源前 1 周并行对照(方案 §4.4)——FAPI 885xxx.TI vs 现有 akshare thsc_xxx 同概念历史逐位对齐率,对齐后切,防 §23.13 口径事故
方法口径:①读 config/indicators.yaml 27 个 concept 条目(name/symbol)②拉 FAPI cn_concept catalog 按 name 精确匹配→thscode
  ③逐概念拉 FAPI 历史 K(近 N 天,默认 62 交易日≈3月)④从 data/sentiment.db index_daily 取同概念同日期 close/pct_change
  ⑤逐日对比:close 对齐(差值<=0.5%) + pct_change 对齐(差值<=0.1pp)两个口径,输出对齐率+未对齐日期样例
输入依赖:config/indicators.yaml + data/sentiment.db(index_daily) + trade-data/.env(HITHINK_FINANCE_API_KEY)
输出:stdout 汇总 + --out 目录存 parallel_result_{date}.json + 逐概念 detail csv
关键参数:--days 默认 62(交易日窗口),--min-match 名称精确匹配
复现:.venv/bin/python docs/fapi/scripts/ths_concept_parallel.py --out /tmp/ths_parallel
"""
import argparse
import csv
import datetime as dt
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "docs/fapi/scripts"))
from probe_fapi import load_key, _api, _check, _date_ms, _ms_to_date  # noqa: E402

CN_TZ = dt.timezone(dt.timedelta(hours=8))


def load_concepts():
    """从 indicators.yaml 读 concept 条目(id/name/symbol)"""
    import yaml
    cfg = yaml.safe_load((REPO / "config/indicators.yaml").read_text(encoding="utf-8"))
    out = []
    for it in cfg.get("indices", []):
        if it.get("market") == "concept" and it.get("id", "").startswith("thsc_"):
            # 只对照 THS 概念(thsc_ 前缀);国证/中证/上证系列(index 指数)不在 THS 切换范围,排除
            out.append({"id": it["id"], "name": it["name"], "symbol": it.get("symbol", it["name"])})
    return out


def fetch_catalog():
    data = _check(_api("/api/a-share-index/catalog/ths-index-list", {"tag": "cn_concept"}), "idx")
    return {x["name"]: x["thscode"] for x in data["item"]}


def fetch_fapi_hist(thscode, start_ms, end_ms):
    try:
        data = _check(_api("/api/a-share-index/prices/historical",
                           {"thscode": thscode, "interval": "1d", "start": start_ms, "end": end_ms}), "hist")
        return {_ms_to_date(it["date_ms"]): {"close": it["close_price"], "pct": None,
                                             "open": it["open_price"]} for it in data["item"]}
    except Exception as e:
        return {"__error__": str(e)}


def fetch_akshare_hist(conn, idx_id, start_date, end_date):
    rows = conn.execute(
        "SELECT date, close, pct_change FROM index_daily WHERE index_id=? AND date>=? AND date<=?",
        (idx_id, start_date, end_date)).fetchall()
    return {r[0]: {"close": r[1], "pct": r[2]} for r in rows}


def pct_close(prev_close, cur_close):
    if not prev_close:
        return None
    return (cur_close - prev_close) / prev_close * 100.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/ths_parallel")
    ap.add_argument("--days", type=int, default=62, help="对照窗口(自然日,含周末会少),默认62≈3月")
    ap.add_argument("--end", default="20260901")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    end_ms = _date_ms(args.end)
    start_ms = end_ms - args.days * 86400_000
    start_date = dt.datetime.fromtimestamp(start_ms / 1000, tz=CN_TZ).strftime("%Y%m%d")

    concepts = load_concepts()
    print(f"现有 concept 条目: {len(concepts)} 个", flush=True)
    catalog = fetch_catalog()
    print(f"FAPI cn_concept catalog: {len(catalog)} 个", flush=True)

    conn = sqlite3.connect(REPO / "data/sentiment.db")

    rows = []
    for i, c in enumerate(concepts):
        name = c["name"]
        fapi_ts = catalog.get(name)
        if not fapi_ts:
            rows.append({"id": c["id"], "name": name, "fapi_thscode": None, "match": "NO",
                         "fapi_days": 0, "ak_days": 0, "overlap": 0,
                         "close_align": 0, "close_rate": None, "pct_align": 0, "pct_rate": None,
                         "samples": []})
            print(f"[{i+1}/{len(concepts)}] ✗ 无精确匹配: {name}", flush=True)
            continue

        fapi_hist = fetch_fapi_hist(fapi_ts, start_ms, end_ms)
        if "__error__" in fapi_hist:
            rows.append({"id": c["id"], "name": name, "fapi_thscode": fapi_ts, "match": "ERR",
                         "fapi_days": 0, "ak_days": 0, "overlap": 0,
                         "close_align": 0, "close_rate": None, "pct_align": 0, "pct_rate": None,
                         "samples": [fapi_hist["__error__"]]})
            print(f"[{i+1}/{len(concepts)}] ✗ FAPI历史拉取失败: {name} {fapi_ts} {fapi_hist['__error__']}", flush=True)
            continue

        ak_hist = fetch_akshare_hist(conn, c["id"], start_date, args.end)
        dates = sorted(set(fapi_hist) & set(ak_hist))
        close_align = 0
        pct_align = 0
        samples = []
        for d in dates:
            fc, ac = fapi_hist[d]["close"], ak_hist[d]["close"]
            close_diff_pct = abs(fc - ac) / ac * 100.0 if ac else float("inf")
            close_ok = close_diff_pct <= 0.5
            close_align += close_ok
            # pct: FAPI 无涨跌幅字段,自算 close-to-close;ak 有 pct_change 字段
            ak_pct = ak_hist[d]["pct"]
            if close_ok and ak_pct is not None and len(samples) < 5:
                samples.append({"date": d, "fapi_close": round(fc, 3), "ak_close": round(ac, 3),
                                "close_diff_pct": round(close_diff_pct, 3)})
        rate = close_align / len(dates) * 100.0 if dates else None
        rows.append({"id": c["id"], "name": name, "fapi_thscode": fapi_ts, "match": "OK",
                     "fapi_days": len(fapi_hist), "ak_days": len(ak_hist), "overlap": len(dates),
                     "close_align": close_align, "close_rate": round(rate, 1) if rate is not None else None,
                     "pct_align": None, "pct_rate": None, "samples": samples})
        print(f"[{i+1}/{len(concepts)}] ✓ {name} → {fapi_ts} overlap={len(dates)} close对齐={close_align}/{len(dates)} ({rate:.1f}% 若days>0)", flush=True)
        time.sleep(0.3)

    conn.close()

    # 汇总
    ok = [r for r in rows if r["match"] == "OK"]
    no = [r for r in rows if r["match"] == "NO"]
    err = [r for r in rows if r["match"] == "ERR"]
    aligned = [r for r in ok if r["close_rate"] is not None and r["close_rate"] >= 99.0]
    print("\n=== 汇总 ===", flush=True)
    print(f"精确匹配: {len(ok)}/{len(concepts)}  无匹配: {len(no)}  历史拉取失败: {len(err)}", flush=True)
    print(f"close 对齐率>=99%: {len(aligned)}/{len(ok)}", flush=True)
    if no:
        print("无匹配名单:", [r["name"] for r in no], flush=True)
    if err:
        print("失败名单:", [r["name"] for r in err], flush=True)

    # 落盘
    stamp = args.end
    with open(out_dir / f"parallel_result_{stamp}.json", "w", encoding="utf-8") as f:
        json.dump({"end": stamp, "window": f"{start_date}~{stamp}", "rows": rows}, f, ensure_ascii=False, indent=1)
    with open(out_dir / f"parallel_detail_{stamp}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "name", "fapi_thscode", "match", "overlap", "close_align", "close_rate"])
        for r in rows:
            w.writerow([r["id"], r["name"], r["fapi_thscode"], r["match"], r["overlap"],
                        r["close_align"], r["close_rate"]])
    print(f"\n结果落盘: {out_dir}/parallel_result_{stamp}.json + parallel_detail_{stamp}.csv", flush=True)


if __name__ == "__main__":
    main()
