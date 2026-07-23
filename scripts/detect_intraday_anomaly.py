"""A11 异常波动盘中告警

盘中实时检测三档异常，随 intraday_snapshot 30分钟节奏触发（不新增定时任务）：
1. 急涨急跌: 日内涨幅 ±3%/±5%/±7% 三档（指数+行业+概念）
2. 放量: net_inflow ≥ 近5日均 × 2（行业，有净流入字段）
3. 突破: 突破近20日高低点（指数，有 OHLC）

借鉴 app/alert_score.py L5 量能异动模式（L239-244）：
  vol_down = (vs==2)*100 + low_amt = 100 - _rolling_pct(amt)
  l5 = max(vol_down, low_amt)  # 多源合成取最强信号
盘中版简化为阈值判断（30分钟节奏非滚动百分位），保留 max() 取最高档思路。

接入 scripts/intraday_snapshot.sh（R2同步后、push前），失败不阻塞快照。
告警通过 scripts/notify.py 发邮件（盘中提示性，非 --severe 系统级）。
同日同标的同类型去重（data/anomaly_notified.json，不进 git）。
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# 用 .absolute()（非 .resolve()）保留 symlink 路径：trade-data/scripts/ -> trade/scripts/
# 时 REPO=trade-data/，读 trade-data/data/ 的实时 DB（非 trade/data/ 滞后镜像，§9）。
REPO = Path(__file__).absolute().parent.parent
SENT_DB = REPO / "data" / "sentiment.db"
SNAPSHOT_JSON = REPO / "static-site" / "data" / "intraday_snapshot.json"
NOTIFY_PY = REPO / "scripts" / "notify.py"
DEDUP_FILE = REPO / "data" / "anomaly_notified.json"

# --- 三档阈值 ---
RAPID_TIERS = [           # (阈值%, 标签, 档位) 降序，取最高档
    (7.0, "≥7%", "severe"),
    (5.0, "≥5%", "strong"),
    (3.0, "≥3%", "normal"),
]
VOLUME_SURGE_MULT = 2.0   # net_inflow ≥ 5日均 × 2
VOLUME_LOOKBACK = 5       # 近5日
VOLUME_MIN_HISTORY = 3    # 至少3日历史才比较
BREAKOUT_LOOKBACK = 20    # 近20日高低点
BREAKOUT_MIN_HISTORY = 10  # 至少10日历史

# 快照 code -> index_id（复用 intraday_snapshot._SNAPSHOT_TO_INDEX_ID）
SNAPSHOT_TO_INDEX_ID = {
    "sh000001": "sh", "sz399001": "sz", "sh000300": "hs300",
    "sh000016": "sz50", "sh000905": "csi500", "sh000852": "csi1000",
    "sz399006": "cyb", "sh000688": "kc50", "bj899050": "bj50",
    "hkHSI": "hsi", "hkHSTECH": "hstech", "hkHSCEI": "hscei",
}


def _conn():
    c = sqlite3.connect(SENT_DB, timeout=10.0)
    c.row_factory = sqlite3.Row
    return c


def load_snapshot() -> dict | None:
    """读最新盘中快照 JSON。非今日快照返回 None（避免旧数据误报）。"""
    if not SNAPSHOT_JSON.exists():
        print("[anomaly] intraday_snapshot.json 不存在，跳过", file=sys.stderr)
        return None
    try:
        snap = json.loads(SNAPSHOT_JSON.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[anomaly] 读快照失败: {e}", file=sys.stderr)
        return None
    collected = snap.get("collected_at", "")
    today = datetime.now().strftime("%Y-%m-%d")
    if not collected.startswith(today):
        print(f"[anomaly] 快照非今日（{collected[:10]}），跳过", file=sys.stderr)
        return None
    return snap


# ---------------------------------------------------------------------------
# 1) 急涨急跌
# ---------------------------------------------------------------------------
def detect_rapid_move(snapshot: dict) -> list[dict]:
    """急涨急跌: |pct_change| ≥ 3%/5%/7% 三档。

    扫描指数+行业+概念的 pct_change，借鉴 alert_score.py L5 的 max() 合成：
    同一标的只取最高档告警（不重复 3%/5%/7% 三档叠加）。
    """
    alerts = []
    items = []  # (kind, name, pct)
    for idx in snapshot.get("indices", []):
        pct = idx.get("pct_change")
        if pct is not None:
            items.append(("指数", idx.get("name", idx.get("code", "")), pct))
    for ind in snapshot.get("industries", []):
        pct = ind.get("pct_change")
        if pct is not None:
            items.append(("行业", ind.get("sw_name", ind.get("sw_code", "")), pct))
    for con in snapshot.get("concepts", []):
        pct = con.get("pct_change")
        if pct is not None:
            items.append(("概念", con.get("name", con.get("id", "")), pct))

    for kind, name, pct in items:
        for threshold, label, tier in RAPID_TIERS:
            if abs(pct) >= threshold:
                direction = "急涨" if pct > 0 else "急跌"
                alerts.append({
                    "type": "rapid_move", "tier": tier,
                    "kind": kind, "name": name, "pct": round(pct, 2),
                    "desc": f"{direction}{label} {kind}{name} {pct:+.2f}%",
                })
                break  # max 合成：只取最高档
    return alerts


# ---------------------------------------------------------------------------
# 2) 放量
# ---------------------------------------------------------------------------
def detect_volume_surge(snapshot: dict, conn) -> list[dict]:
    """放量: net_inflow ≥ 近5日均 × 2。扫描行业（有 net_inflow 字段）。

    借鉴 alert_score.py L5 的 amount 滚动百分位思路：盘中版简化为
    net_inflow / 5日均 >= 2.0 阈值。均值为0/负（地量行业）跳过避免除零。
    net_inflow 单位为亿元（与 index_daily 一致，同花顺净流入口径）。
    """
    alerts = []
    today = datetime.now().strftime("%Y%m%d")
    for ind in snapshot.get("industries", []):
        sw_code = ind.get("sw_code", "")
        net = ind.get("net_inflow")
        if not sw_code or net is None:
            continue
        rows = conn.execute(
            "SELECT net_inflow FROM index_daily WHERE index_id=? "
            "AND net_inflow IS NOT NULL AND date < ? "
            "ORDER BY date DESC LIMIT ?",
            (sw_code, today, VOLUME_LOOKBACK)
        ).fetchall()
        if len(rows) < VOLUME_MIN_HISTORY:
            continue
        avg_net = sum(r["net_inflow"] for r in rows) / len(rows)
        if avg_net <= 0:  # 地量/净流出行业跳过
            continue
        ratio = net / avg_net
        if ratio >= VOLUME_SURGE_MULT:
            name = ind.get("sw_name", sw_code)
            alerts.append({
                "type": "volume_surge", "tier": "normal",
                "kind": "行业", "name": name,
                "net_inflow": round(net, 2), "avg_5d": round(avg_net, 2),
                "ratio": round(ratio, 2),
                "desc": f"放量 行业{name} 净流入{net:.2f}亿 "
                        f"({ratio:.1f}×5日均{avg_net:.2f}亿)",
            })
    return alerts


# ---------------------------------------------------------------------------
# 3) 突破
# ---------------------------------------------------------------------------
def detect_breakout(snapshot: dict, conn) -> list[dict]:
    """突破: 突破近20日高低点。扫描指数（有 OHLC high/low）。

    借鉴 alert_score.py 的 high_52w/low_52w 突破思路（L528-531），
    盘中版用20日窗口：当日 high > max(近20日high) = 突破20日高，
    当日 low < min(近20日low) = 跌破20日低。用 intraday high/low（非 price）
    捕获盘中任何时点突破（即使回撤也算）。
    """
    alerts = []
    today = datetime.now().strftime("%Y%m%d")
    for idx in snapshot.get("indices", []):
        code = idx.get("code", "")
        index_id = SNAPSHOT_TO_INDEX_ID.get(code)
        if not index_id:
            continue
        intraday_high = idx.get("high")
        intraday_low = idx.get("low")
        if intraday_high is None and intraday_low is None:
            continue
        rows = conn.execute(
            "SELECT high, low FROM index_daily WHERE index_id=? "
            "AND high IS NOT NULL AND low IS NOT NULL AND date < ? "
            "ORDER BY date DESC LIMIT ?",
            (index_id, today, BREAKOUT_LOOKBACK)
        ).fetchall()
        if len(rows) < BREAKOUT_MIN_HISTORY:
            continue
        highs = [r["high"] for r in rows if r["high"] is not None]
        lows = [r["low"] for r in rows if r["low"] is not None]
        if not highs or not lows:
            continue
        hh20 = max(highs)
        ll20 = min(lows)
        name = idx.get("name", code)
        if intraday_high is not None and intraday_high > hh20:
            alerts.append({
                "type": "breakout_up", "tier": "normal",
                "kind": "指数", "name": name,
                "high": round(intraday_high, 2), "hh20": round(hh20, 2),
                "desc": f"突破20日高 指数{name} 当日高{intraday_high:.2f} > 20日高{hh20:.2f}",
            })
        elif intraday_low is not None and intraday_low < ll20:
            alerts.append({
                "type": "breakout_down", "tier": "normal",
                "kind": "指数", "name": name,
                "low": round(intraday_low, 2), "ll20": round(ll20, 2),
                "desc": f"跌破20日低 指数{name} 当日低{intraday_low:.2f} < 20日低{ll20:.2f}",
            })
    return alerts


# ---------------------------------------------------------------------------
# 去重 + 发告警
# ---------------------------------------------------------------------------
def _alert_key(a: dict) -> str:
    """去重 key: type|kind|name（同日同标的同类型只报一次）。"""
    return f"{a['type']}|{a['kind']}|{a['name']}"


def filter_and_record(alerts: list[dict]) -> list[dict]:
    """去重：同日同标的同类型只保留首次。记录到 data/anomaly_notified.json。"""
    today = datetime.now().strftime("%Y%m%d")
    dedup = {}
    if DEDUP_FILE.exists():
        try:
            dedup = json.loads(DEDUP_FILE.read_text(encoding="utf-8"))
        except Exception:
            dedup = {}
    today_set = dedup.get(today, {})
    now = datetime.now().isoformat()
    new_alerts = []
    for a in alerts:
        key = _alert_key(a)
        if key in today_set:
            continue
        today_set[key] = now
        new_alerts.append(a)
    # 只保留今日（清理旧日期避免文件膨胀）
    dedup = {today: today_set}
    try:
        DEDUP_FILE.parent.mkdir(parents=True, exist_ok=True)
        DEDUP_FILE.write_text(json.dumps(dedup, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        print(f"[anomaly] 写去重文件失败: {e}", file=sys.stderr)
    return new_alerts


def send_alert(alerts: list[dict]) -> None:
    """发告警邮件（通过 notify.py，非 severe=盘中提示性）。"""
    if not alerts:
        return
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    severe_n = sum(1 for a in alerts if a.get("tier") == "severe")
    if severe_n:
        subject = f"[盘中异动] {severe_n}项≥7% + {len(alerts)-severe_n}项其他 ({now})"
    else:
        subject = f"[盘中异动] {len(alerts)}项异常 ({now})"

    tier_badge = {"severe": "[严重]", "strong": "[强]", "normal": "[普通]"}
    lines = [f"<h3>盘中异常波动告警 ({now})</h3>",
             f"<p>共 {len(alerts)} 项异常（去重后首次触发）：</p>", "<ul>"]
    for a in alerts:
        badge = tier_badge.get(a.get("tier"), "")
        lines.append(f"<li>{badge} {a['desc']}</li>")
    lines.append("</ul>")
    lines.append("<p style='color:#888;font-size:12px;'>盘中30分钟节奏检测，"
                 "同日同标的同类型只报一次。收盘后 update_all 最终版以信号邮件为准。</p>")
    body = "\n".join(lines)

    try:
        subprocess.run(
            [sys.executable, str(NOTIFY_PY), subject, body],
            timeout=60, check=False, capture_output=True, text=True,
        )
        print(f"[anomaly] 告警邮件已发：{subject}", flush=True)
    except Exception as e:
        print(f"[anomaly] 告警邮件发送失败（不阻塞）: {e}", file=sys.stderr)


def main() -> int:
    snap = load_snapshot()
    if not snap:
        return 0

    print(f"[anomaly] 开始检测 {datetime.now():%H:%M:%S} "
          f"(快照 {snap.get('collected_at', '?')[:19]})", flush=True)

    alerts = []
    with _conn() as conn:
        alerts += detect_rapid_move(snap)
        alerts += detect_volume_surge(snap, conn)
        alerts += detect_breakout(snap, conn)

    print(f"[anomaly] 检测到 {len(alerts)} 项异常（去重前）", flush=True)

    new_alerts = filter_and_record(alerts)
    if new_alerts:
        print(f"[anomaly] 去重后 {len(new_alerts)} 项新异常，发告警：", flush=True)
        for a in new_alerts:
            print(f"  - {a['desc']}", flush=True)
        send_alert(new_alerts)
    else:
        print(f"[anomaly] 无新异常（均已告警过），不发邮件", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
