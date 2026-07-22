#!/usr/bin/env python3
"""综合 AI 风险预警:每日算分入库 + 导出 alert.json 供前端预警条。

设计依据: docs/alert-design.md §4.2(存储方案) + §8(原因生成)。
- 入库: score_daily 表加 high_alert / low_alert 两个 score_id (复用 is_overheat/is_freeze/components)
  - high_alert: value=高位预警分, is_overheat=1 当 >75 (警示级以上), components=8维度JSON
  - low_alert : value=低位预警分, is_freeze=1 当 >75 (机会级以上), components=8维度JSON
- 导出: static-site/data/alert.json (当日总分+等级+触发维度TopN+原因文案+近期预警历史)
- 回测阈值: HIGH>=72 / LOW>=85 (scripts/backtest_alert.py 调参最优, N10胜率达标)

用法:
  .venv/bin/python scripts/export_alert.py              # 当日: 算分入库 + 导出 alert.json
  .venv/bin/python scripts/export_alert.py --backfill   # 历史回填: 2016 至今每日入库 (首次上线跑)
  .venv/bin/python scripts/export_alert.py --date 20260715  # 指定日 (调试)
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).absolute().parent.parent  # 不用 .resolve()：trade-data/scripts 是 trade/scripts 的 symlink，resolve() 会跳回 trade 致 alert*.json 绕过 trade-data 写到 trade
sys.path.insert(0, str(ROOT))

from app.alert_score import (  # noqa: E402
    HIGH_WEIGHTS,
    LOW_WEIGHTS,
    compute_alert_scores,
    load_index_close,
)

_SENT_DB = ROOT / "data" / "sentiment.db"
DATA_DIR = ROOT / "static-site" / "data"
ALERT_JSON = DATA_DIR / "alert.json"

# 维度中文名 (docs/alert-design.md §2.2 / §3.2)
HIGH_DIM_NAMES = {
    "H1": "情绪过热", "H2": "量价背离", "H3": "卖点密集", "H4": "位置偏高",
    "H5": "动量衰退", "H6": "均线转弱", "H7": "汪汪队离场", "H8": "全球走弱",
}
LOW_DIM_NAMES = {
    "L1": "情绪冰点", "L2": "买点密集", "L3": "位置偏低", "L4": "汪汪队入场",
    "L5": "量能异动", "L6": "新低极端", "L7": "波指飙升", "L8": "价值显现",
}

HIT_THRESHOLD = 60.0      # 维度命中线 (docs §8.2①: 强度≥60 算命中)
HIGH_SHOW = 72.0          # 预警条显示阈值 (回测最优, N10下跌占比56.4%)
LOW_SHOW = 85.0           # 预警条显示阈值 (回测最优, N10上涨占比65.7%)
HISTORY_DAYS = 30         # alert.json 近期预警历史回溯天数
HISTORY_LIMIT = 12        # 历史列表最多条数


def _high_level(score) -> str:
    if pd.isna(score):
        return "数据不足"
    if score > 88:
        return "高危"
    if score > 75:
        return "警示"
    if score > 60:
        return "关注"
    return "中性"


def _low_level(score) -> str:
    if pd.isna(score):
        return "数据不足"
    if score > 88:
        return "机遇"
    if score > 75:
        return "机会"
    if score > 60:
        return "关注"
    return "中性"


# 各等级一句话文案 (docs §2.4 / §3.4 + §8.2④)
_HIGH_REASON = {
    "高危": "🔴 高危预警:多维度过热共振,风险显著,留意追高风险",
    "警示": "⚠️ 过热信号密集,警惕阶段性顶部,逢高谨慎",
    "关注": "市场偏热,部分指标进入高位区,留意风险",
    "中性": "高位风险指标处于中性区间",
    "数据不足": "数据不足,暂无法判断高位风险",
}
_LOW_REASON = {
    "机遇": "🔵 机遇预警:多维度冰点共振,机会显著,关注超跌反弹",
    "机会": "❄️ 冰点信号密集,关注阶段性机会,留意布局",
    "关注": "市场偏冷,部分指标进入低位区,关注企稳信号",
    "中性": "低位机会指标处于中性区间",
    "数据不足": "数据不足,暂无法判断低位机会",
}


def _build_dims(row, keys: list[str], names: dict, weights: dict) -> list[dict]:
    """构造维度详情列表 (按贡献降序), hit=强度≥60。"""
    out = []
    for k in keys:
        v = row.get(k)
        if v is None or pd.isna(v):
            continue
        w = weights[k]
        out.append({
            "k": k,
            "name": names[k],
            "score": round(float(v), 2),
            "weight": w,
            "contribution": round(float(v) * w, 2),
            "hit": bool(float(v) >= HIT_THRESHOLD),
        })
    out.sort(key=lambda x: x["contribution"], reverse=True)
    return out


def _reason_text(level: str, dims: list[dict], is_high: bool) -> str:
    """主原因 = 等级文案 + 命中维度前2 (docs §8.2④ 模板槽位)。中性/数据不足级不加维度。"""
    base = _HIGH_REASON[level] if is_high else _LOW_REASON[level]
    if level in ("中性", "数据不足"):
        return base
    hit_names = [d["name"] for d in dims if d["hit"]][:2]
    if not hit_names:
        return base
    first = base.split(",")[0]
    rest = ",".join(base.split(",")[1:])
    return f"{first}({'+'.join(hit_names)}),{rest}" if rest else f"{first}({'+'.join(hit_names)})"


def _store_score(conn, date: str, score_id: str, value, is_overheat: int, is_freeze: int, components: dict):
    conn.execute(
        "INSERT OR REPLACE INTO score_daily (date, score_id, value, is_freeze, is_overheat, components, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (date, score_id, None if pd.isna(value) else round(float(value), 4),
         is_freeze, is_overheat, json.dumps(components, ensure_ascii=False),
         datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    )


def backfill(start: str = "20160101") -> int:
    """历史回填: 算 start 至今每日 high_alert/low_alert 入库 score_daily。返回入库行数。"""
    print(f"-> 回填预警分 {start} ~ 至今 ...")
    df = compute_alert_scores(start=start)
    if df.empty:
        print("  无数据")
        return 0
    hkeys = list(HIGH_WEIGHTS)
    lkeys = list(LOW_WEIGHTS)
    n = 0
    with sqlite3.connect(_SENT_DB) as c:
        c.execute("BEGIN")
        for date, row in df.iterrows():
            ha = row.get("high_alert")
            la = row.get("low_alert")
            hcomps = {k: (None if pd.isna(row.get(k)) else round(float(row[k]), 2)) for k in hkeys}
            lcomps = {k: (None if pd.isna(row.get(k)) else round(float(row[k]), 2)) for k in lkeys}
            _store_score(c, str(date), "high_alert", ha,
                         is_overheat=1 if (not pd.isna(ha) and ha > 75) else 0,
                         is_freeze=0, components=hcomps)
            _store_score(c, str(date), "low_alert", la,
                         is_overheat=0,
                         is_freeze=1 if (not pd.isna(la) and la > 75) else 0,
                         components=lcomps)
            n += 2
        c.execute("COMMIT")
    print(f"  入库 {n} 行 ({len(df)} 日)")
    return n


def _latest_alert_date(conn) -> str:
    row = conn.execute(
        "SELECT max(date) FROM score_daily WHERE score_id='high_alert'"
    ).fetchone()
    return row[0] if row and row[0] else ""


def export_for_date(date: str | None = None) -> dict:
    """算指定日(默认最近交易日)预警分, 入库 + 导出 alert.json。返回 alert dict。"""
    if date is None:
        # 默认最近交易日 (上证 close 序列末日)
        date = str(load_index_close("sh").index[-1])
    df = compute_alert_scores(end=date)
    if df.empty:
        print(f"  无 {date} 预警数据")
        return {}
    df = df[df.index <= date]
    if df.empty:
        return {}
    row = df.iloc[-1]
    actual_date = str(df.index[-1])
    ha = row.get("high_alert")
    la = row.get("low_alert")
    hkeys = list(HIGH_WEIGHTS)
    lkeys = list(LOW_WEIGHTS)

    # 入库当日
    hcomps = {k: (None if pd.isna(row.get(k)) else round(float(row[k]), 2)) for k in hkeys}
    lcomps = {k: (None if pd.isna(row.get(k)) else round(float(row[k]), 2)) for k in lkeys}
    with sqlite3.connect(_SENT_DB) as c:
        _store_score(c, actual_date, "high_alert", ha,
                     is_overheat=1 if (not pd.isna(ha) and ha > 75) else 0,
                     is_freeze=0, components=hcomps)
        _store_score(c, actual_date, "low_alert", la,
                     is_overheat=0,
                     is_freeze=1 if (not pd.isna(la) and la > 75) else 0,
                     components=lcomps)

    h_level = _high_level(ha)
    l_level = _low_level(la)
    h_dims = _build_dims(row, hkeys, HIGH_DIM_NAMES, HIGH_WEIGHTS)
    l_dims = _build_dims(row, lkeys, LOW_DIM_NAMES, LOW_WEIGHTS)

    alert = {
        "date": actual_date,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "high": {
            "score": None if pd.isna(ha) else round(float(ha), 2),
            "level": h_level,
            "triggered": bool(not pd.isna(ha) and ha >= HIGH_SHOW),
            "dims": h_dims,
            "reason": _reason_text(h_level, h_dims, is_high=True),
        },
        "low": {
            "score": None if pd.isna(la) else round(float(la), 2),
            "level": l_level,
            "triggered": bool(not pd.isna(la) and la >= LOW_SHOW),
            "dims": l_dims,
            "reason": _reason_text(l_level, l_dims, is_high=False),
        },
        "history": _recent_history(actual_date),
    }
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(ALERT_JSON, "w", encoding="utf-8") as f:
        json.dump(alert, f, ensure_ascii=False, indent=2)
    print(f"  导出 {ALERT_JSON} (date={actual_date} high={alert['high']['score']} low={alert['low']['score']})")
    return alert


def _recent_history(cur_date: str) -> list[dict]:
    """近 HISTORY_DAYS 日内 is_overheat/is_freeze=1 的预警日 (排除当日)。"""
    with sqlite3.connect(_SENT_DB) as c:
        rows = c.execute(
            "SELECT date, score_id, value, is_freeze, is_overheat FROM score_daily "
            "WHERE (score_id='high_alert' AND is_overheat=1) "
            "   OR (score_id='low_alert' AND is_freeze=1) "
            "ORDER BY date DESC LIMIT ?",
            (HISTORY_LIMIT * 2,),
        ).fetchall()
    out = []
    for d, sid, val, fr, oh in rows:
        if d == cur_date:
            continue
        is_high = sid == "high_alert"
        out.append({
            "date": d,
            "type": "high" if is_high else "low",
            "score": round(float(val), 2) if val is not None else None,
            "level": _high_level(val) if is_high else _low_level(val),
        })
        if len(out) >= HISTORY_LIMIT:
            break
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", action="store_true", help="历史回填 2016 至今入库")
    ap.add_argument("--date", default=None, help="指定日 YYYYMMDD (默认最近交易日)")
    args = ap.parse_args()

    if args.backfill:
        backfill("20160101")
        print("-> 回填完成, 再导出当日 alert.json ...")
    alert = export_for_date(args.date)
    if alert:
        print(f"✓ 预警导出完成: date={alert['date']} "
              f"high={alert['high']['score']}({alert['high']['level']}) "
              f"low={alert['low']['score']}({alert['low']['level']})")


if __name__ == "__main__":
    main()
