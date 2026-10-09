"""A11 盘中异动告警

盘中实时检测三档异动，随 intraday_snapshot 30分钟节奏触发（不新增定时任务）：
1. 急涨急跌: 日内涨幅 ±3%/±5%/±7% 三档（指数+行业+概念）
2. 放量: net_inflow ≥ 近5日均 × 2（行业，有净流入字段）
3. 突破: 突破近20日高低点（指数，有 OHLC）

借鉴 app/alert_score.py L5 量能异动模式（L239-244）：
  vol_down = (vs==2)*100 + low_amt = 100 - _rolling_pct(amt)
  l5 = max(vol_down, low_amt)  # 多源合成取最强信号
盘中版简化为阈值判断（30分钟节奏非滚动百分位），保留 max() 取最高档思路。

接入 scripts/intraday_snapshot.sh（R2同步后、push前），失败不阻塞快照。
告警通过 scripts/notify.py 发邮件（盘中提示性，非 --severe 系统级）。
同日同标的同类型去重签 data/anomaly_notified.json（不进 git）——**该文件同时是前端浏览器
通知的唯一数据源**（export_notifications.py -> static-site/data/notifications.json -> 前端弹 severe）。
#241B(2026-10-10)【前端通知与邮件送达解耦】: 落签（写 anomaly_notified.json）与邮件送达**解耦**
—— 异动一旦产出即落签（前端源就绪），邮件送达**单独记账**（未达 ⇒ 整 payload 暂存
data/anomaly_email_pending.json，下一轮重试）。修「邮件通道一挂，前端通知一起静默丢失」。
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
sys.path.insert(0, str(Path(__file__).absolute().parent))
from util_atomic import atomic_write_json  # noqa: E402  (原子写公共模块, 2026-09-22 非 kelly 链路统一)
from notify_sent import notify_sent  # noqa: E402  (#241 同族: notify 真发出判据, 唯一实现)
SENT_DB = REPO / "data" / "sentiment.db"
SNAPSHOT_JSON = REPO / "static-site" / "data" / "intraday_snapshot.json"
NOTIFY_PY = REPO / "scripts" / "notify.py"
DEDUP_FILE = REPO / "data" / "anomaly_notified.json"
# #241B(2026-10-10): 邮件未达暂存账本(与「前端取数源落签」DEDUP_FILE 解耦的独立文件)。
EMAIL_PENDING_FILE = REPO / "data" / "anomaly_email_pending.json"

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


def filter_and_record(alerts: list[dict]) -> tuple[list[dict], dict]:
    """去重：同日同标的同类型只保留首次。**不落签**，返回 (本轮新异动, 待落签 dedup)。

    #241B(2026-10-10): 落签语义见 record_notified —— 与**邮件送达**解耦（异动产出即落签,
    前端源就绪）, 不再等邮件送达。B 波(2026-10-09)「全失败永久失报」由「邮件单独记账 +
    未达 payload 暂存下轮重试」(retry_pending_emails/send_or_stage)承接, 不回归。
    """
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
    return new_alerts, dedup


def record_notified(dedup: dict) -> None:
    """落签 data/anomaly_notified.json（**异动产出即落签**, 由 main 无条件调用）。

    #241B(2026-10-10): 该文件是**前端浏览器通知的唯一数据源**, 落签与**邮件送达解耦**
    —— 只要异动已产出即落签（前端源就绪）, 不因邮件通道故障而缺失。邮件送达由
    send_or_stage/retry_pending_emails 单独记账（未达暂存重试）, 二者互不影响。

    写失败 fail-loud（#132, 2026-10-02）: 去重失效 = 同日同标的同类型异动每 30min 轮重复
    发提示告警(降噪逆反)。独立 warning(dedup 24h), 不升级 severe: 本地基础设施故障,
    异动数据级判定本身不受影响。
    """
    try:
        DEDUP_FILE.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(DEDUP_FILE, dedup)
    except Exception as e:
        print(f"[anomaly] 写去重文件失败(异动告警将重复轰炸): {e}", file=sys.stderr)
        _notify_dedup_write_fail(e)


def _notify_dedup_write_fail(e: Exception) -> None:
    """去重文件写失败告警(#132, 2026-10-02): 独立 warning, dedup 24h。"""
    subject = "[告警][盘中异动] 去重文件写失败, 异动告警可能重复轰炸"
    body = (
        f"<b>detect_intraday_anomaly 去重文件写失败</b>: <code>{DEDUP_FILE}</code><br>"
        f"异常: <code>{e}</code><br>"
        f"影响: 同日同标的同类型去重(data/anomaly_notified.json)失效, "
        f"盘中异动告警每 30min 轮可能重复轰炸。<br>"
        f"建议: 检查 data/ 目录/磁盘权限或空间, 修复后自动恢复。"
    )
    cmd = [sys.executable, str(NOTIFY_PY), subject, body,
           "--tier", "warning", "--from-prefix", "[告警]",
           "--dedup-key", "anomaly_dedup_write_fail", "--dedup-window", "86400"]
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except Exception as ne:  # noqa: BLE001
        print(f"[anomaly] 去重写失败告警发送异常(不阻塞): {ne}", file=sys.stderr)


def send_alert(alerts: list[dict]) -> bool:
    """发告警邮件（通过 notify.py，非 severe=盘中提示性）。返回「是否**真发出**」。

    #241 同族(2026-10-09): 判据改解析 notify.py 输出文本(notify_sent), 不看 rc
    (notify.py main() 所有出口恒 return 0, 全渠道失败也 rc=0 ⇒ rc 无告知力)。
    """
    if not alerts:
        return False
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    severe_n = sum(1 for a in alerts if a.get("tier") == "severe")
    if severe_n:
        subject = f"[盘中异动] {severe_n}项≥7% + {len(alerts)-severe_n}项其他 ({now})"
    else:
        subject = f"[盘中异动] {len(alerts)}项异动 ({now})"

    tier_badge = {"severe": "[严重]", "strong": "[强]", "normal": "[普通]"}
    lines = [f"<h3>盘中异动告警 ({now})</h3>",
             f"<p>共 {len(alerts)} 项异动（去重后首次触发）：</p>", "<ul>"]
    for a in alerts:
        badge = tier_badge.get(a.get("tier"), "")
        lines.append(f"<li>{badge} {a['desc']}</li>")
    lines.append("</ul>")
    lines.append("<p style='color:#888;font-size:12px;'>盘中30分钟节奏检测，"
                 "同日同标的同类型只报一次。收盘后系统将发送最终版信号邮件，请以最终版为准。</p>")
    body = "\n".join(lines)

    try:
        r = subprocess.run(
            [sys.executable, str(NOTIFY_PY), subject, body,
             "--from-prefix", "[盘中异动]"],
            timeout=60, check=False, capture_output=True, text=True,
        )
        out = (r.stdout or "") + (r.stderr or "")
        sent = notify_sent(out)
        if sent:
            print(f"[anomaly] 告警邮件已发：{subject}", flush=True)
        else:
            print(f"[anomaly] 告警邮件**未确认送达**(rc={r.returncode}, 下轮重试不落去重签)："
                  f"{out.strip()[-200:]}", file=sys.stderr)
        return sent
    except Exception as e:
        print(f"[anomaly] 告警邮件发送失败（不阻塞）: {e}", file=sys.stderr)
        return False


# ---------------------------------------------------------------------------
# #241B(2026-10-10) 邮件送达单独记账 —— 与「前端取数源落签」解耦
# ---------------------------------------------------------------------------
# 病灶: anomaly_notified.json 既是「前端浏览器通知的唯一数据源」, 又曾被当作「邮件已送达」
# 的落签门控(B 波「送达成功才落签」) ⇒ 邮件通道一挂, 前端通知一起静默丢失(错误耦合)。
# 修法: ①main 里**落签与邮件送达解耦**(异动产出即落签 = 前端源就绪);
#       ②邮件送达**单独记账** —— 未达 ⇒ 整 payload 暂存, 下一轮重试。
# 不变式(不回归 B 波): 邮件全失败仍会重试直到送达(不永久失报); 前端源不因邮件失败而缺。

def _load_email_pending() -> dict:
    """读「邮件未达」暂存账本 {alert_key: alert_payload}。缺失/损坏 ⇒ 空(降级不阻塞)。"""
    if not EMAIL_PENDING_FILE.exists():
        return {}
    try:
        data = json.loads(EMAIL_PENDING_FILE.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        print(f"[anomaly] 读邮件暂存账本失败(本轮视为空): {e}", file=sys.stderr)
        return {}
    return data if isinstance(data, dict) else {}


def _write_email_pending(pending: dict) -> None:
    """写暂存账本(原子写)。写失败 fail-loud 打印, **不另发告警**(防台账元噪声, plan §5 不变式5)。"""
    try:
        EMAIL_PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(EMAIL_PENDING_FILE, pending)
    except Exception as e:  # noqa: BLE001
        print(f"[anomaly] 写邮件暂存账本失败(未达邮件可能丢失重试): {e}", file=sys.stderr)


def stage_email_pending(alerts: list[dict]) -> None:
    """邮件未达 ⇒ 把**整 payload** 暂存待下轮重试(按 alert_key 去重, 同 key 不重复入账)。

    存整 payload(非 key): send_alert 组装 body 依赖 `a['desc']`(**无法由 _alert_key 重建**),
    ⇒ 必须存下整条 alert dict。
    """
    pending = _load_email_pending()
    for a in alerts:
        pending[_alert_key(a)] = a
    _write_email_pending(pending)


def retry_pending_emails() -> None:
    """下轮重试: 账本非空即整批补发; 成功 ⇒ 清账; 失败 ⇒ 保留再下轮。

    幂等保证(不重复弹前端): 落签早在首次产出时已写, 补发成功**不再触碰** anomaly_notified.json
    ⇒ 前端源内容不变、不会重复弹(前端亦按 localStorage key 当日去重)。绝不因重试而重复落签。
    """
    pending = _load_email_pending()
    if not pending:
        return
    alerts = list(pending.values())
    if send_alert(alerts):
        _write_email_pending({})
        print(f"[anomaly] 补发暂存告警 {len(alerts)} 项成功, 邮件账本已清", flush=True)
    else:
        print(f"[anomaly] 暂存告警 {len(alerts)} 项补发仍未达, 保留账本下轮再试", file=sys.stderr)


def send_or_stage(alerts: list[dict]) -> bool:
    """发邮件; 未达 ⇒ 暂存整 payload 待下轮重试(不回归 B 波「全失败仍可重试」)。返回是否真发出。"""
    if send_alert(alerts):
        return True
    stage_email_pending(alerts)
    return False


def main() -> int:
    # #241B(2026-10-10): 先补发上轮暂存的未达邮件(重试不依赖今日快照, 每次调用都尝试)。
    retry_pending_emails()

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

    print(f"[anomaly] 检测到 {len(alerts)} 项异动（去重前）", flush=True)

    new_alerts, _dedup_pending = filter_and_record(alerts)
    if new_alerts:
        print(f"[anomaly] 去重后 {len(new_alerts)} 项新异动，发告警：", flush=True)
        for a in new_alerts:
            print(f"  - {a['desc']}", flush=True)
        # #241B(2026-10-10): 落签与邮件送达**解耦** —— anomaly_notified.json 是前端浏览器
        # 通知的唯一数据源, 异动一旦产出即落签(前端源就绪), 不再等待邮件送达。
        record_notified(_dedup_pending)
        # 邮件送达**单独记账**: 未达 ⇒ 整 payload 暂存待下轮重试(不回归 B 波「全失败仍可重试」)。
        if not send_or_stage(new_alerts):
            print("[anomaly] 告警邮件未确认送达 ⇒ 已暂存待下轮重试(前端源已落签)", file=sys.stderr)
    else:
        print(f"[anomaly] 无新异动（均已告警过），不发邮件", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
