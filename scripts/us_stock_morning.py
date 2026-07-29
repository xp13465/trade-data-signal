#!/usr/bin/env python3
"""美股指数早采任务（05:00 launchd 触发，美股 04:00 收盘后 1 小时余量防源延迟）。

根因（2026-07-29 调研 agent a0a2137ed08b1b52f 确认）：
- 新浪 index_us_stock_sina 历史源对美股指数发布不同步（.DJI/.IXIC/.NDX 停 7-27，
  只有 .INX 有 7-28，实测 7-29 07:52 仍停），致 overview us_dji_date 滞后 2 天。
- backfill_evening 02:00 跑早于美股 04:00 收盘 + require_today=False 距今≤3天不补
  = 不触发美股补采。

方案A：独立美股早采任务 05:00，换源新浪实时 gb_$（4 只全有完整 OHLC + prev_close +
EDT 日期，实测 7-29 07:52 新浪实时 gb_$dji/gb_$ixic/gb_$inx/gb_$ndx 均有 7-28 收盘
OHLC），新浪历史 index_us_stock_sina 兜底（延迟发布后能补）。

字段映射（新浪 gb_$ 实时，GBK 解码，实测 2026-07-29）：
    var hq_str_gb_$dji="name,close,pct,time,change,open,high,low,52w_h,52w_l,
        vol,amt,...,EDT_time,prev_close,...,year"
    [0]=name  [1]=close  [2]=pct  [3]=time(GMT+8)  [4]=change
    [5]=open  [6]=high  [7]=low
    [10]=volume  [11]=amount
    [25]=EDT_time("Jul 28 05:10PM EDT")  [26]=prev_close  [29]=year

EDT_time 的日期部分即美股交易日（市场 16:00 EDT 收盘，05:xx EDT 为收盘后结算更新），
用 [29] year 字段补全年份 -> trade_date=YYYYMMDD。

东财 push2 API 调研：100.DJIA/100.SPX 正常，但 100.NDX 返回 IXIC 数据（f58="纳斯达克"
非"纳斯达克100"，mislabeled），不可用。故 4 只全走新浪实时 gb_$（一致 + 完整）。

用法（.sh wrapper 设 REPO=trade-data 让 db.py 读主库，§9 cwd=trade-data）：
    REPO=/Users/linhuichen/code/trade-data python scripts/us_stock_morning.py
"""
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import requests

# 让 app.* 能 import：优先 REPO 环境变量（.sh wrapper 设 trade-data，db.py 读主库），
# 否则 fallback 到脚本父目录（trade/，读滞后镜像，仅本地测试用）
REPO = os.environ.get("REPO") or str(Path(__file__).resolve().parent.parent)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from app.collector.base import UA  # noqa: E402
from app.collector.runner import upsert_index_rows  # noqa: E402

_SINA_URL = "http://hq.sinajs.cn/list=gb_$dji,gb_$ixic,gb_$inx,gb_$ndx"
_SINA_HEADERS = {"User-Agent": UA, "Referer": "https://finance.sina.com.cn"}

# gb_$ 代码 -> (index_id, 新浪历史 symbol for fallback)
US_INDEX_MAP = {
    "gb_$dji":  ("us_dji",  ".DJI"),
    "gb_$ixic": ("us_ixic", ".IXIC"),
    "gb_$inx":  ("us_spx",  ".INX"),
    "gb_$ndx":  ("us_ndx",  ".NDX"),
}

_LINE_RE = re.compile(r'var\s+hq_str_(gb_\$\w+)\s*=\s*"([^"]*)"')

_MONTH_MAP = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}


def _parse_edt_date(edt_str, year_str):
    """'Jul 28 05:10PM EDT' + '2026' -> '20260728'。失败返回 None。"""
    m = re.match(r'([A-Z][a-z]{2})\s+(\d{1,2})', edt_str.strip())
    if not m:
        return None
    mon = _MONTH_MAP.get(m.group(1))
    if not mon:
        return None
    try:
        year = int(year_str)
    except (ValueError, TypeError):
        year = datetime.utcnow().year
    return f"{year:04d}{mon:02d}{int(m.group(2)):02d}"


def fetch_sina_realtime():
    """新浪实时 gb_$ 抓 4 只美股指数。

    返回 {gb_$dji: {name,close,open,high,low,pct,prev_close,trade_date,...}, ...}
    失败返回 {}。
    """
    try:
        r = requests.get(_SINA_URL, headers=_SINA_HEADERS, timeout=10)
        text = r.content.decode("gbk", errors="replace")
    except Exception as e:  # noqa: BLE001
        print(f"[us_stock_morning] 新浪实时抓取失败: {type(e).__name__} {e}", flush=True)
        return {}

    out = {}
    for line in text.strip().split(";"):
        line = line.strip()
        if not line:
            continue
        m = _LINE_RE.match(line)
        if not m:
            continue
        code = m.group(1)
        vals = m.group(2).split(",")
        if len(vals) < 27:
            continue

        def f(i):
            try:
                x = vals[i].strip()
                return float(x) if x else None
            except (IndexError, ValueError):
                return None

        edt = vals[25].strip() if len(vals) > 25 else ""
        year = vals[29].strip() if len(vals) > 29 else ""
        trade_date = _parse_edt_date(edt, year) if edt else None

        close = f(1)
        prev_close = f(26)
        # 始终用 close/prev_close 重算 pct（新浪 field[2] 是四舍五入值如 1.03，
        # 历史源给全精度如 0.505951...，重算保持与历史源一致的精度）
        pct = None
        if close and prev_close and prev_close != 0:
            pct = (close / prev_close - 1) * 100

        out[code] = {
            "name": vals[0].strip(),
            "close": close,
            "open": f(5),
            "high": f(6),
            "low": f(7),
            "pct": pct,
            "vol": f(10),
            "amt": f(11),
            "prev_close": prev_close,
            "edt": edt,
            "trade_date": trade_date,
        }
    return out


def _sina_historical_fallback(idx_id, symbol, target_date):
    """新浪历史 index_us_stock_sina 兜底：拉全量，取含 target_date 的行 upsert。

    返回 (rows, msg)。rows 为空则 msg 说明原因。
    """
    import akshare as ak
    try:
        df = ak.index_us_stock_sina(symbol=symbol)
    except Exception as e:  # noqa: BLE001
        return [], f"sina_hist error: {type(e).__name__} {e}"
    if df is None or len(df) == 0:
        return [], "sina_hist empty"

    dc = "date" if "date" in df.columns else ("日期" if "日期" in df.columns else None)
    if dc is None:
        return [], f"sina_hist no date col (cols={list(df.columns)[:5]})"

    rows = []
    prev = None
    for _, r in df.iterrows():
        d = str(r[dc]).replace("-", "")[:8]
        close = float(r["close"]) if "close" in df.columns and _notna(r["close"]) else None
        pct = None
        if prev and close:
            pct = (close / prev - 1) * 100
        rows.append((
            d, idx_id,
            float(r["open"]) if "open" in df.columns and _notna(r["open"]) else None,
            float(r["high"]) if "high" in df.columns and _notna(r["high"]) else None,
            float(r["low"]) if "low" in df.columns and _notna(r["low"]) else None,
            close, pct,
            0.0,  # 新浪历史源近端 amount=0（仅 volume），与现有数据一致
        ))
        if close:
            prev = close
    has_target = any(r[0] == target_date for r in rows)
    if not has_target:
        return [], f"sina_hist no target_date={target_date} (latest={rows[-1][0] if rows else 'none'})"
    return rows, "sina_hist"


def _notna(v):
    try:
        import pandas as pd
        return pd.notna(v)
    except Exception:  # noqa: BLE001
        return v is not None


def main():
    now = datetime.now()
    today_str = now.strftime("%Y%m%d")
    print(f"=== us_stock_morning 开始 {now} ===", flush=True)

    rt = fetch_sina_realtime()
    if not rt:
        print("[us_stock_morning] 新浪实时全失败，全部走历史兜底", flush=True)

    rows_to_upsert = []
    results = []  # (idx_id, status, detail)

    for code, (idx_id, hist_symbol) in US_INDEX_MAP.items():
        info = rt.get(code)
        used_source = None
        if info and info["close"] and info["trade_date"]:
            td = info["trade_date"]
            # 校验 trade_date 不在未来且距今≤7天（防 stale 数据）
            try:
                td_d = datetime.strptime(td, "%Y%m%d").date()
                days_ago = (now.date() - td_d).days
            except (ValueError, TypeError):
                days_ago = 99
            if 0 <= days_ago <= 7:
                # 新浪实时主源：OHLC 齐全
                rows_to_upsert.append((
                    td, idx_id,
                    info["open"], info["high"], info["low"],
                    info["close"], info["pct"], 0.0,  # amount=0 与现有 us 指数数据一致
                ))
                used_source = "sina_realtime"
                pct_str = f"{info['pct']:.2f}%" if info['pct'] is not None else "N/A"
                results.append((idx_id, "ok",
                    f"{used_source} date={td} close={info['close']} pct={pct_str} "
                    f"O={info['open']} H={info['high']} L={info['low']}"))
                print(f"  ✓ {idx_id} <- {used_source} date={td} close={info['close']} "
                      f"pct={pct_str} O={info['open']} H={info['high']} L={info['low']}", flush=True)
            else:
                print(f"  - {idx_id} 新浪实时 trade_date={td} 距今{days_ago}天(>7或未来)，转历史兜底", flush=True)
        else:
            reason = "无数据" if not info else f"close={info.get('close')} trade_date={info.get('trade_date')}"
            print(f"  - {idx_id} 新浪实时 {reason}，转历史兜底", flush=True)

        # 历史兜底（realtime 失败或 trade_date 异常时）
        if used_source is None:
            # target_date = 今天（历史源若已发布今日数据则采到）
            fb_rows, fb_msg = _sina_historical_fallback(idx_id, hist_symbol, today_str)
            if fb_rows:
                rows_to_upsert.extend(fb_rows)
                latest = fb_rows[-1]
                used_source = "sina_historical"
                results.append((idx_id, "ok",
                    f"{used_source} date={latest[0]} close={latest[5]} ({fb_msg})"))
                print(f"  ✓ {idx_id} <- {used_source} date={latest[0]} close={latest[5]}", flush=True)
            else:
                results.append((idx_id, "fail", fb_msg))
                print(f"  ✗ {idx_id} 历史兜底失败: {fb_msg}", flush=True)

    # 批量 upsert
    if rows_to_upsert:
        upsert_index_rows(rows_to_upsert)
        print(f"=== upsert {len(rows_to_upsert)} 行完成 ===", flush=True)
    else:
        print("=== 无数据可 upsert ===", flush=True)

    # 汇总
    print(f"\n=== us_stock_morning 汇总 ({datetime.now()}) ===", flush=True)
    ok = sum(1 for _, s, _ in results if s == "ok")
    fail = sum(1 for _, s, _ in results if s == "fail")
    for idx_id, status, detail in results:
        print(f"  [{status}] {idx_id}: {detail}", flush=True)
    print(f"=== 结束 ok={ok} fail={fail} ===", flush=True)
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
