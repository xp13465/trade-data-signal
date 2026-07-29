#!/usr/bin/env python3
"""export_notifications.py - 导出 notifications.json 供前端浏览器通知（P2-新-W 方案A）。

读 sentiment.db 当日信号/预警/恐贪 + anomaly_notified.json 异动 + signal_notified.json 去重，
导出 static-site/data/notifications.json。

6 类触发场景（对应 TASKS.md P2-新-W）：
  1. 新买入信号 (buy/buy_aux/buy_special/buy_backup)
  2. 新卖出信号 (sell/sell_stop_loss)
  3. 盘中异常 (volume_surge/breakout/rapid_move) - 从 anomaly_notified.json 读
  4. 综合预警 (high_alert>=72 / low_alert>=85)
  5. 恐贪极值 (fear_greed <20 极度恐惧 / >80 极度贪婪)
  6. 涨停潮 (a_width_zt_count > 5日均×1.8 且 >=50)
  + 盘后速递标志 (post_close=True when hour>=18)

去重三层（对应 TASKS.md P2-新-W）：
  1. 后端：信号复用 signal_notified.json[today]（已邮件推送的跳过，避免双通道重复）
  2. 后端：异动复用 anomaly_notified.json[today]（detect_intraday_anomaly.py 已去重）
  3. 前端：localStorage notified_keys（同事件当日只弹一次）+ Notification tag（同 tag 显最新）

用法：
  cd /Users/linhuichen/code/trade-data && python3 /Users/linhuichen/code/trade/scripts/export_notifications.py

⚠️ cwd 必须在 trade-data/（§9）：sentiment.db 主库在 trade-data/data/（inode 237343239），
   trade/ 是滞后镜像（inode 238648312，仅 deploy.sh rsync 时同步）。
   本脚本用 ROOT = Path(__file__).absolute().parent.parent（不 resolve），
   trade-data/scripts 是 trade/scripts 的 symlink，从 trade-data 跑读 trade-data/data/。
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).absolute().parent.parent  # 不 resolve：trade-data/scripts symlink -> trade/scripts
sys.path.insert(0, str(ROOT))

from app.db import get_conn  # noqa: E402

DB_PATH = ROOT / "data" / "sentiment.db"
DATA_DIR = ROOT / "static-site" / "data"
OUT_JSON = DATA_DIR / "notifications.json"
SIGNAL_NOTIFIED_PATH = ROOT / "data" / "signal_notified.json"
ANOMALY_NOTIFIED_PATH = ROOT / "data" / "anomaly_notified.json"

# 阈值（与 export_alert.py / 前端一致）
HIGH_ALERT_SHOW = 72.0      # 高位预警显示阈值（回测最优）
LOW_ALERT_SHOW = 85.0       # 低位机会显示阈值（回测最优）
FEAR_GREED_LOW = 20.0       # 极度恐惧
FEAR_GREED_HIGH = 80.0      # 极度贪婪
ZT_SPIKE_RATIO = 1.8        # 涨停数 > 5日均×1.8 = 异动
ZT_SPIKE_MIN = 50           # 涨停数绝对值下限（避免低基数误报）

# 信号类型中文标签
SIGNAL_NAMES = {
    "buy": "主买", "buy_aux": "辅买", "buy_special": "追买", "buy_backup": "备买",
    "sell": "卖", "sell_stop_loss": "追止损卖", "band_hold": "波段持有",
}

# 异动类型中文标签
ANOMALY_TYPE_NAMES = {
    "volume_surge": "量能异动",
    "breakout_up": "向上突破",
    "breakout_down": "向下突破",
    "rapid_move": "急涨急跌",
}

# score_daily 中综合分 score_id -> 中文名（与 check_signals.py 一致）
SCORE_NAME_MAP = {
    "cross_market": "跨市场综合分", "a_sentiment": "A股综合情绪分",
    "sentiment_sz50": "上证50情绪分", "sentiment_hs300": "沪深300情绪分",
    "sentiment_csi500": "中证500情绪分", "sentiment_csi1000": "中证1000情绪分",
    "sentiment_cyb": "创业板情绪分", "sentiment_kc50": "科创50情绪分",
}


def _today_str() -> str:
    return datetime.now().strftime("%Y%m%d")


def _load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _load_name_map() -> dict:
    """从 indicators.yaml + 硬编码 score 加载 index_id -> 中文名。"""
    name_map = dict(SCORE_NAME_MAP)
    cfg_path = ROOT / "config" / "indicators.yaml"
    if not cfg_path.exists():
        return name_map
    try:
        import yaml
        cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return name_map
    for m in cfg.get("metrics", []) or []:
        mid, mname = m.get("id"), m.get("name")
        if mid and mname:
            name_map[mid] = mname
    for idx in cfg.get("indices", []) or []:
        iid, iname = idx.get("id"), idx.get("name")
        if iid and iname:
            name_map[iid] = iname
    return name_map


def _index_name(index_id: str, name_map: dict) -> str:
    """去 g./s. 前缀后查映射；未匹配保留原 index_id。"""
    if index_id.startswith("g.") or index_id.startswith("s."):
        key = index_id[2:]
    else:
        key = index_id
    return name_map.get(key, index_id)


def _query_signals(conn, date: str) -> list[dict]:
    rows = conn.execute(
        "SELECT index_id, signal, reason FROM signal_daily WHERE date = ? ORDER BY signal, index_id",
        (date,),
    ).fetchall()
    return [{"index_id": r[0], "signal": r[1], "reason": r[2]} for r in rows]


def _high_level(score) -> str:
    if score is None:
        return "数据不足"
    s = float(score)
    if s > 88:
        return "高危"
    if s > 75:
        return "警示"
    if s > 60:
        return "关注"
    return "中性"


def _low_level(score) -> str:
    if score is None:
        return "数据不足"
    s = float(score)
    if s > 88:
        return "机遇"
    if s > 75:
        return "机会"
    if s > 60:
        return "关注"
    return "中性"


def _query_alert_scores(conn, date: str) -> dict:
    rows = conn.execute(
        "SELECT score_id, value FROM score_daily "
        "WHERE date = ? AND score_id IN ('high_alert', 'low_alert')",
        (date,),
    ).fetchall()
    out = {}
    for sid, val in rows:
        if sid == "high_alert":
            out["high"] = {
                "score": round(float(val), 2) if val is not None else None,
                "level": _high_level(val),
                "triggered": bool(val is not None and float(val) >= HIGH_ALERT_SHOW),
            }
        elif sid == "low_alert":
            out["low"] = {
                "score": round(float(val), 2) if val is not None else None,
                "level": _low_level(val),
                "triggered": bool(val is not None and float(val) >= LOW_ALERT_SHOW),
            }
    return out


def _query_fear_greed(conn, date: str) -> dict | None:
    row = conn.execute(
        "SELECT value FROM score_daily WHERE date = ? AND score_id = 'fear_greed'",
        (date,),
    ).fetchone()
    if not row or row[0] is None:
        return None
    val = float(row[0])
    extreme = None
    if val < FEAR_GREED_LOW:
        extreme = "fear"
    elif val > FEAR_GREED_HIGH:
        extreme = "greed"
    return {"value": round(val, 2), "extreme": extreme}


def _query_limit_up(conn, date: str) -> dict | None:
    """涨停数 + 5日均 + spike 标志。"""
    rows = conn.execute(
        "SELECT date, value FROM daily_metric WHERE metric_id = 'a_width_zt_count' "
        "ORDER BY date DESC LIMIT 6",
    ).fetchall()
    if not rows:
        return None
    today_val = None
    history = []
    for d, v in rows:
        if d == date and v is not None:
            today_val = float(v)
        elif v is not None:
            history.append(float(v))
    if today_val is None:
        return None
    avg = sum(history[:5]) / len(history[:5]) if history[:5] else today_val
    spike = today_val >= ZT_SPIKE_MIN and today_val >= avg * ZT_SPIKE_RATIO
    return {"count": int(today_val), "avg": round(avg, 1), "spike": bool(spike)}


def _load_anomalies_today(date: str) -> list[dict]:
    """从 anomaly_notified.json 读当日异动（detect_intraday_anomaly.py 已去重）。

    格式 {date: {"type|kind|name": iso_timestamp}}。返回 list[dict] 供前端弹通知。
    """
    data = _load_json(ANOMALY_NOTIFIED_PATH, {})
    if not isinstance(data, dict):
        return []
    today_entries = data.get(date, {})
    if not isinstance(today_entries, dict):
        return []
    out = []
    for key, ts in today_entries.items():
        parts = key.split("|", 2)
        if len(parts) != 3:
            continue
        atype, akind, aname = parts
        # 简化分级：rapid_move/breakout_down = severe（急涨急跌/跌破偏严重），
        # volume_surge/breakout_up = strong
        tier = "severe" if atype in ("rapid_move", "breakout_down") else "strong"
        type_label = ANOMALY_TYPE_NAMES.get(atype, atype)
        out.append({
            "type": atype,
            "kind": akind,
            "name": aname,
            "tier": tier,
            "desc": f"{type_label}·{aname}",
            "ts": ts,
        })
    return out


def _is_post_close(date: str) -> bool:
    """判断是否盘后（18:00 后 update_all 已跑，数据定版）。"""
    now = datetime.now()
    today = now.strftime("%Y%m%d")
    if date != today:
        return True  # 历史日期视为盘后
    return now.hour >= 18


def export_notifications(date: str | None = None) -> dict:
    """算指定日(默认今天)通知事件, 导出 notifications.json。返回 dict。"""
    if date is None:
        date = _today_str()
    if not DB_PATH.exists():
        print(f"[export_notifications] DB 不存在：{DB_PATH}", file=sys.stderr)
        return {}
    name_map = _load_name_map()
    conn = get_conn()
    try:
        signals_raw = _query_signals(conn, date)
        alerts = _query_alert_scores(conn, date)
        fear_greed = _query_fear_greed(conn, date)
        limit_up = _query_limit_up(conn, date)
    finally:
        conn.close()

    # 后端去重：信号复用 signal_notified.json[today]（已邮件推送的跳过）
    notified = _load_json(SIGNAL_NOTIFIED_PATH, {})
    if not isinstance(notified, dict):
        notified = {}
    today_notified = {tuple(x) for x in notified.get(date, [])}
    signals = []
    for s in signals_raw:
        if (s["index_id"], s["signal"]) in today_notified:
            continue  # 已邮件推送，跳过避免双通道重复
        s2 = dict(s)
        s2["name"] = _index_name(s["index_id"], name_map)
        s2["label"] = SIGNAL_NAMES.get(s["signal"], s["signal"])
        signals.append(s2)

    # 异动（anomaly_notified.json 已去重，每事件每日只首次）
    anomalies = _load_anomalies_today(date)

    # 盘后标志
    post_close = _is_post_close(date)

    out = {
        "date": date,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "signals": signals,
        "anomalies": anomalies,
        "alerts": alerts,
        "fear_greed": fear_greed,
        "limit_up": limit_up,
        "post_close": post_close,
    }
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(
        f"[export_notifications] 导出 {OUT_JSON.name} "
        f"(date={date} signals={len(signals)}/{len(signals_raw)} "
        f"anomalies={len(anomalies)} "
        f"alerts_high={alerts.get('high', {}).get('triggered', False)} "
        f"alerts_low={alerts.get('low', {}).get('triggered', False)} "
        f"fg={fear_greed['value'] if fear_greed else 'NA'} "
        f"zt={limit_up['count'] if limit_up else 'NA'} "
        f"post_close={post_close})"
    )
    return out


def main():
    import argparse
    ap = argparse.ArgumentParser(description="导出 notifications.json 供前端浏览器通知")
    ap.add_argument("--date", default=None, help="YYYYMMDD（默认今天）")
    args = ap.parse_args()
    result = export_notifications(args.date)
    if result:
        print(f"✓ 通知导出完成: date={result['date']}")


if __name__ == "__main__":
    main()
