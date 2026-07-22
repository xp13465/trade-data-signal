#!/usr/bin/env python3
"""check_signals.py — 检测当天 signal_daily 买卖点信号 + 发邮件通知。

查询 signal_daily 表当日（默认 today，可 --date 指定）的买卖点信号：
- 有信号 → 构建邮件正文（按 buy/sell 分组 + 规则说明 + 免责声明）→ SMTP SSL 发送。
- 无信号 → 仅 log，不发邮件。
- 邮件发送失败 → log 错误，exit 非 0 但不崩（try/except 兜底，不阻塞 update_all）。

用法：
  python scripts/check_signals.py                  # 今天
  python scripts/check_signals.py --date 20260706  # 指定日期

配置：config/email.json（含 SMTP 授权码，已 gitignore；模板见 email.json.example）。
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import smtplib
import sqlite3
import sys
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from app.db import get_conn

DB_PATH = REPO / "data" / "sentiment.db"
EMAIL_CONFIG = REPO / "config" / "email.json"
INDICATORS_CONFIG = REPO / "config" / "indicators.yaml"
STATS_PATH = REPO / "data" / "signal_stats.json"
# F 方案（2026-07-21）：邮件去重持久化，记录当日已通知的 (index_id, signal) 集合。
# 格式 {date_str: [[index_id, signal], ...]}，7 天自动清理旧记录（save_signal_notified）。
# 仅在去重模式（默认）下读写；--full 全量模式不读只写（发后全标记已通知）。
NOTIFIED_PATH = REPO / "data" / "signal_notified.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("check_signals")

# score_daily 中的综合分 score_id → 中文名（不入 indicators.yaml，硬编码）
SCORE_NAME_MAP = {
    "cross_market": "跨市场综合分",
    "a_sentiment": "A股综合情绪分",
    "sentiment_sz50": "上证50情绪分",
    "sentiment_hs300": "沪深300情绪分",
    "sentiment_csi500": "中证500情绪分",
    "sentiment_csi1000": "中证1000情绪分",
    "sentiment_cyb": "创业板情绪分",
    "sentiment_kc50": "科创50情绪分",
}

# index_id 前缀（g.=指标/daily_metric，s.=score_daily 分数，无前缀=指数 index_daily）
_PREFIX_RE = re.compile(r"^(?:g|s)\.(.+)$")

# 邮件正文中的买卖点规则摘要（HTML）
RULE_SUMMARY = """【买卖点规则说明】
• 主买（buy）：RSI 上穿 30（超卖反弹启动）。
• 辅买（buy_aux）：布林下轨回归（超卖反弹，强势市更敏感，互补主买盲区）。
• 追买（buy_special）：唐奇安20日上轨突破 + B4_hold5d 过滤（close 突破前20日最高价且延后5日站稳确认，激进战法高回撤高收益，趋势跟踪类）。
• 备买（buy_backup）：Supertrend ATR(10)×3 翻多 + 二次确认过滤（延后3日 close 确认仍站稳，趋势转向，与主买/辅买均值回归类互补，趋势跟踪类）。
• 卖（sell）：20 日高点回落 5% + MA60 多头过滤 + MACD 死叉确认（止盈减仓提示）。
• 追止损卖（sell_stop_loss）：A1 Donchian20 下轨止损（close 跌破前20日最低价，与追买上轨突破对称，独立止损卖点）。
  附 RSI 当前值、综合情绪分 cross 状态、相对前一买点盈亏标注。</div>"""

DISCLAIMER = """【免责声明】
本信号由历史数据量化回测生成，仅供研究参考，不构成任何投资建议。
市场有风险，投资需谨慎。请结合自身判断与资金管理做出决策。</div>"""

# 信号类型中文标签
SIGNAL_LABELS = {
    "buy": "主买",
    "buy_aux": "辅买",
    "buy_special": "追买",
    "buy_backup": "备买",
    "sell": "卖",
    "sell_stop_loss": "追止损卖",
}
SIGNAL_ORDER = ["buy", "buy_aux", "buy_special", "buy_backup", "sell", "sell_stop_loss"]

# email.json.example 中的占位密码，识别后跳过实际发送（仅打印内容）
PLACEHOLDER_PASSWORD = "<填163邮箱SMTP授权码，非登录密码>"


def calc_kelly(win_rate: float | None, pl: float | None) -> float:
    """凯利公式：计算建议仓位比例。win_rate/pl 无效时返回 0。"""
    if pl is None or win_rate is None or pl <= 0 or win_rate <= 0:
        return 0.0
    b = pl  # 盈亏比
    p = win_rate
    return max(0.0, (b * p - (1 - p)) / b)


def load_signal_stats() -> dict:
    """加载 signal_stats.json。文件不存在或解析失败返回空 dict。"""
    if not STATS_PATH.exists():
        log.warning("signal_stats.json 不存在：%s", STATS_PATH)
        return {}
    try:
        stats = json.loads(STATS_PATH.read_text(encoding="utf-8"))
        if not isinstance(stats, dict):
            log.warning("signal_stats.json 格式异常（非 dict）")
            return {}
        return stats
    except Exception as e:  # noqa: BLE001
        log.warning("signal_stats.json 加载失败：%s", e)
        return {}


def load_signal_notified() -> dict[str, list[list[str]]]:
    """读 data/signal_notified.json（邮件去重持久化）。

    格式 {date_str(YYYYMMDD): [[index_id, signal], ...]}。不存在/解析失败返回 {}。
    文件位于 data/ 且已 gitignore（§8 禁推），仅本地持久化跨进程去重。
    """
    if not NOTIFIED_PATH.exists():
        return {}
    try:
        data = json.loads(NOTIFIED_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            log.warning("signal_notified.json 格式异常（非 dict），忽略")
            return {}
        return data
    except Exception as e:  # noqa: BLE001
        log.warning("signal_notified.json 加载失败：%s（去重降级为全发）", e)
        return {}


def save_signal_notified(data: dict[str, list[list[str]]]) -> None:
    """写 data/signal_notified.json（原子写）。清理 7 天前旧记录避免无限增长。

    原子写（.tmp + replace）：防盘中 intraday_snapshot 30 分钟并发跑 check_signals
    时读到半截 JSON。
    """
    cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y%m%d")
    cleaned = {d: v for d, v in data.items() if d >= cutoff}
    NOTIFIED_PATH.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(cleaned, ensure_ascii=False, separators=(",", ":"))
    tmp = NOTIFIED_PATH.parent / (NOTIFIED_PATH.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(NOTIFIED_PATH)


def query_signals(date: str) -> list[dict]:
    """查询 signal_daily 当日信号，按 signal, index_id 排序。"""
    if not DB_PATH.exists():
        log.error("数据库不存在：%s", DB_PATH)
        return []
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT index_id, signal, reason FROM signal_daily "
            "WHERE date = ? ORDER BY signal, index_id",
            (date,),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def load_name_map() -> dict[str, str]:
    """加载 index_id(去前缀) → 中文名 映射。

    来源：
      - config/indicators.yaml 的 metrics[]（g.<id>）和 indices[]（无前缀）
      - score_daily 综合分（s.<id>，硬编码 SCORE_NAME_MAP）
    未匹配的 index_id 保留原值（调用方兜底）。
    """
    name_map: dict[str, str] = {}
    name_map.update(SCORE_NAME_MAP)
    if not INDICATORS_CONFIG.exists():
        log.warning("config/indicators.yaml 不存在 —— 名称映射仅含硬编码 score")
        return name_map
    try:
        cfg = yaml.safe_load(INDICATORS_CONFIG.read_text(encoding="utf-8")) or {}
    except Exception as e:  # noqa: BLE001
        log.error("config/indicators.yaml 解析失败：%s（仅用硬编码 score 映射）", e)
        return name_map
    for m in cfg.get("metrics", []) or []:
        mid = m.get("id")
        mname = m.get("name")
        if mid and mname:
            name_map[mid] = mname
    for idx in cfg.get("indices", []) or []:
        iid = idx.get("id")
        iname = idx.get("name")
        if iid and iname:
            name_map[iid] = iname
    return name_map


def index_id_to_name(index_id: str, name_map: dict[str, str]) -> str:
    """signal_daily.index_id → 中文名。去 g./s. 前缀后查映射；未匹配保留原 index_id。"""
    m = _PREFIX_RE.match(index_id)
    key = m.group(1) if m else index_id
    return name_map.get(key, index_id)


def _summary_names(signals: list[dict], name_map: dict[str, str], limit: int = 3) -> str:
    """信号列表 → 品种名摘要（最多 limit 个，多了 '等N个'）。无信号返回空串。"""
    if not signals:
        return ""
    names = [index_id_to_name(s["index_id"], name_map) for s in signals]
    head = "、".join(names[:limit])
    if len(names) > limit:
        return f"{head}等{len(names)}个"
    return head


def _signal_label(sig_type: str) -> str:
    """信号类型 → 中文标签。"""
    return SIGNAL_LABELS.get(sig_type, sig_type)


def _signal_emoji(sig_type: str) -> str:
    """信号类型 → 图标。"""
    if sig_type == "buy":
        return "🔴"
    if sig_type == "buy_aux":
        return "🟣"
    if sig_type == "buy_special":
        return "🟡"
    if sig_type == "buy_backup":
        return "🟪"
    if sig_type == "sell":
        return "🟢"
    return "⚪"


def _format_stats_line(stats_entry: dict | None) -> str | None:
    """根据 stats 条目生成回测统计行。无数据返回 None。"""
    if not stats_entry:
        return None
    win_rate = stats_entry.get("win_rate")
    pl = stats_entry.get("pl")
    n = stats_entry.get("n")
    if win_rate is None or pl is None or n is None:
        return None
    kelly = calc_kelly(win_rate, pl)
    kelly_str = f"凯利建议仓位 {kelly*100:.1f}%" if kelly > 0 else "凯利=0（不建议）"
    return (
        f"    回测(10日) 胜率{win_rate*100:.1f}% "
        f"盈亏比{pl:.2f} 样本{n} → {kelly_str}"
    )


def build_email(date: str, signals: list[dict], name_map: dict[str, str],
                intraday: bool = False) -> tuple[str, str]:
    """构建邮件主题 + HTML 正文。返回 (subject, html_body)。

    intraday=True 时邮件标注【盘中实时】+ 风险提示横幅（盘中快照非最终，
    收盘后 17:50 update_all 仍发最终版）。默认 False（收盘/历史回测用）。
    """
    stats = load_signal_stats()

    # 按 signal 类型分组（buy / buy_aux / buy_special / buy_backup / sell / sell_stop_loss）
    groups: dict[str, list[dict]] = {k: [] for k in SIGNAL_ORDER}
    for s in signals:
        sig = s["signal"]
        if sig in groups:
            groups[sig].append(s)
        else:
            groups.setdefault(sig, []).append(s)

    n_total = len(signals)
    n_buy = len(groups["buy"])
    n_aux = len(groups["buy_aux"])
    n_special = len(groups["buy_special"])
    n_backup = len(groups["buy_backup"])
    n_sell = len(groups["sell"])
    n_stop_loss = len(groups["sell_stop_loss"])

    # === 标题：信号类型 + 品种摘要 ===
    parts = []
    for sig_type in SIGNAL_ORDER:
        g = groups[sig_type]
        label = _signal_label(sig_type)
        if g:
            summary = _summary_names(g, name_map, limit=3)
            parts.append(f"{label}×{len(g)} {summary}")
    # intraday 标注【盘中实时】前缀，收盘/历史不加（保持原"最终版"语义）
    title_prefix = "盘中实时·" if intraday else ""
    subject = f"[{title_prefix}买卖点信号] {date}  {' | '.join(parts) if parts else '无信号'}"

    # === HTML 正文 ===
    # intraday 风险提示横幅：盘中快照非最终，信号可能随行情变化，收盘后 17:50 发最终版
    h2_title = "📊 盘中实时·买卖点信号" if intraday else "📊 买卖点信号日报"
    intraday_banner = ""
    if intraday:
        intraday_banner = (
            '<div style="background:#fff7e6;border:1px solid #ffd591;border-radius:6px;'
            'padding:10px 14px;margin:0 0 14px 0;font-size:13px;color:#d46b08;line-height:1.6;">'
            '<b>⚠️ 盘中实时快照</b>：本邮件基于盘中行情快照生成，<b>信号可能随后续行情变化</b>'
            '（如 buy_aux 消失/重现）。此为快照非最终，<b>收盘后 17:50 update_all 仍发最终版邮件</b>，'
            '请以收盘最终版为准。</div>'
        )
    html_parts = [f"""<html><body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;font-size:14px;color:#1d2129;max-width:720px;">
<h2 style="margin:0 0 8px 0;color:#1d2129;">{h2_title}</h2>
<p style="margin:0 0 16px 0;color:#86909c;font-size:13px;">{date} · 共 <b>{n_total}</b> 个信号（主买 {n_buy} / 辅买 {n_aux} / 追买 {n_special} / 备买 {n_backup} / 卖 {n_sell} / 追止损卖 {n_stop_loss}）</p>
{intraday_banner}"""]

    if n_total == 0:
        html_parts.append('<p style="color:#86909c;">今日无买卖点信号。</p>')
    else:
        # 信号表格
        html_parts.append("""<table style="width:100%;border-collapse:collapse;font-size:13px;margin-bottom:16px;">
<thead><tr style="background:#f2f3f5;text-align:left;">
<th style="padding:8px 10px;border-bottom:2px solid #e5e6eb;">品种</th>
<th style="padding:8px 10px;border-bottom:2px solid #e5e6eb;width:48px;">类型</th>
<th style="padding:8px 10px;border-bottom:2px solid #e5e6eb;">触发条件</th>
<th style="padding:8px 10px;border-bottom:2px solid #e5e6eb;width:56px;text-align:center;">胜率</th>
<th style="padding:8px 10px;border-bottom:2px solid #e5e6eb;width:56px;text-align:center;">盈亏比</th>
<th style="padding:8px 10px;border-bottom:2px solid #e5e6eb;width:130px;text-align:center;">凯利建议</th>
</tr></thead><tbody>""")

        for sig_type in SIGNAL_ORDER:
            for s in groups[sig_type]:
                name = index_id_to_name(s["index_id"], name_map)
                reason = (s["reason"] or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                label = _signal_label(sig_type)
                emoji = _signal_emoji(sig_type)
                # 回测统计
                sub = stats.get(s["index_id"], {}).get(sig_type, {}).get("10d")
                wr = sub.get("win_rate") if sub else None
                pl = sub.get("pl") if sub else None
                n_s = sub.get("n") if sub else None
                wr_str = f'{(wr or 0)*100:.0f}%' if wr is not None else "-"
                pl_str = f'{pl:.2f}' if pl is not None else "-"
                if wr is not None and pl is not None and n_s is not None and n_s >= 10:
                    kelly = calc_kelly(wr, pl)
                    if kelly > 0:
                        kelly_str = f'建议仓位 <b>{kelly*100:.0f}%</b>'
                        kelly_color = "#2e8b57"
                    else:
                        kelly_str = "不建议入场"
                        kelly_color = "#86909c"
                else:
                    kelly_str = f'样本不足({n_s or 0}例)' if n_s else "-"
                    kelly_color = "#c9cdd4"
                wr_color = "#2e8b57" if (wr or 0) >= 0.6 else "#e6492e" if (wr or 0) < 0.4 else "#1d2129"
                html_parts.append(f"""<tr style="border-bottom:1px solid #f2f3f5;">
<td style="padding:8px 10px;">{emoji} <b>{name}</b></td>
<td style="padding:8px 10px;font-size:12px;">{label}</td>
<td style="padding:8px 10px;font-size:12px;color:#4e5969;">{reason}</td>
<td style="padding:8px 10px;text-align:center;font-weight:600;color:{wr_color};">{wr_str}</td>
<td style="padding:8px 10px;text-align:center;">{pl_str}</td>
<td style="padding:8px 10px;text-align:center;font-size:12px;color:{kelly_color};">{kelly_str}</td>
</tr>""")

        html_parts.append("</tbody></table>")

    # 规则说明 + 免责
    html_parts.append(f"""<div style="background:#f7f8fa;border-radius:6px;padding:12px 16px;margin-bottom:12px;font-size:12px;color:#4e5969;line-height:1.8;">
<div style="font-weight:600;margin-bottom:4px;color:#1d2129;">📋 规则说明</div>
• 主买（buy）：RSI 上穿 30（超卖反弹启动）<br>
• 辅买（buy_aux）：布林下轨回归（超卖反弹，强势市更敏感，互补主买盲区）<br>
• 追买（buy_special）：唐奇安20日上轨突破 + B4_hold5d 过滤（close 突破前20日最高价且延后5日站稳确认，激进战法高回撤高收益，趋势跟踪类）<br>
• 备买（buy_backup）：Supertrend ATR(10)×3 翻多 + 二次确认过滤（延后3日 close 确认仍站稳，趋势转向，与主买/辅买均值回归类互补，趋势跟踪类）<br>
• 卖（sell）：20 日高点回落 5% + MA60 多头过滤 + MACD 死叉确认（止盈减仓提示）<br>
• 追止损卖（sell_stop_loss）：A1 Donchian20 下轨止损（close 跌破前20日最低价，与追买上轨突破对称，独立止损卖点）<br>
• 附 RSI 当前值、综合情绪分 cross 状态、相对前一买点盈亏标注
</div>
<div style="background:#f7f8fa;border-radius:6px;padding:12px 16px;font-size:12px;color:#86909c;line-height:1.8;">
<div style="font-weight:600;margin-bottom:4px;color:#1d2129;">⚠️ 免责声明</div>
本信号由历史数据量化回测生成，仅供研究参考，不构成任何投资建议。<br>
市场有风险，投资需谨慎。请结合自身判断与资金管理做出决策。
</div>
<p style="color:#c9cdd4;font-size:11px;margin-top:16px;">—— A股/港股/全球情绪数据复盘看板 · 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
</body></html>""")

    body = "\n".join(html_parts)
    return subject, body


def load_email_config() -> dict | None:
    """读 config/email.json。不存在或解析失败返回 None。"""
    if not EMAIL_CONFIG.exists():
        log.warning("config/email.json 不存在（复制 email.json.example 并填 SMTP 授权码后启用邮件）")
        return None
    try:
        cfg = json.loads(EMAIL_CONFIG.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        log.error("config/email.json 解析失败：%s", e)
        return None
    return cfg


def send_email(cfg: dict, subject: str, body: str) -> None:
    """SMTP SSL 发邮件。失败抛异常（由调用方 try/except 兜底）。

    password 为占位符时跳过实际发送（仅日志，用于测试/未配置场景）。
    """
    smtp = cfg.get("smtp", "smtp.163.com")
    port = int(cfg.get("port", 465))
    user = cfg.get("user", "")
    password = cfg.get("password", "")
    to = cfg.get("to", user)

    if not user or not password or password == PLACEHOLDER_PASSWORD:
        log.warning("SMTP password 仍是占位符 —— 跳过实际发送（邮件内容已打印到日志）")
        return

    msg = MIMEText(body, "html", "utf-8")
    msg["Subject"] = subject
    msg["From"] = formataddr(("A股情绪看板", user))
    msg["To"] = to
    msg["Date"] = formatdate(localtime=True)

    with smtplib.SMTP_SSL(smtp, port, timeout=30) as srv:
        srv.login(user, password)
        srv.sendmail(user, [to], msg.as_string())
    log.info("✓ 邮件已发送至 %s", to)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="检测当天 signal_daily 买卖点信号 + 发邮件通知"
    )
    parser.add_argument("--date", help="查询日期 YYYYMMDD（默认今天）")
    parser.add_argument(
        "--full",
        action="store_true",
        help="全量模式（跳过去重，发当日所有信号；收盘速递用）。默认去重只发当日新信号。",
    )
    parser.add_argument(
        "--intraday",
        action="store_true",
        help="盘中实时模式：邮件标题加【盘中实时】+ 正文加风险提示横幅"
        "（盘中快照非最终，收盘 17:50 update_all 仍发最终版）。不走去重，仍用默认去重。",
    )
    args = parser.parse_args(argv)

    date = args.date or datetime.now().strftime("%Y%m%d")
    log.info(
        "=== check_signals 开始，查询日期：%s（%s模式%s）===",
        date,
        "全量" if args.full else "去重",
        "·盘中实时" if args.intraday else "",
    )

    signals = query_signals(date)
    if not signals:
        log.info("今日（%s）无买卖点信号，不发邮件", date)
        return 0

    n_buy = sum(1 for s in signals if s["signal"] == "buy")
    n_aux = sum(1 for s in signals if s["signal"] == "buy_aux")
    n_special = sum(1 for s in signals if s["signal"] == "buy_special")
    n_backup = sum(1 for s in signals if s["signal"] == "buy_backup")
    n_sell = sum(1 for s in signals if s["signal"] == "sell")
    n_stop_loss = sum(1 for s in signals if s["signal"] == "sell_stop_loss")
    log.info(
        "查询到 %d 个信号（主买=%d, 辅买=%d, 追买=%d, 备买=%d, 卖=%d, 追止损卖=%d）",
        len(signals), n_buy, n_aux, n_special, n_backup, n_sell, n_stop_loss,
    )

    name_map = load_name_map()
    # F 方案（2026-07-21）邮件去重：默认只发当日新 (index_id, signal)；
    # --full 全量模式发当日全部（收盘速递用，不走去重）。
    if args.full:
        log.info("全量模式（--full）：发当日全部 %d 信号", len(signals))
        signals_to_send = signals
    else:
        notified = load_signal_notified()
        today_notified = {tuple(x) for x in notified.get(date, [])}
        signals_to_send = [
            s for s in signals if (s["index_id"], s["signal"]) not in today_notified
        ]
        n_dup = len(signals) - len(signals_to_send)
        log.info(
            "去重模式：当日 %d 信号，新 %d / 已通知 %d", len(signals), len(signals_to_send), n_dup
        )
        if not signals_to_send:
            log.info("无新信号（已去重），不发邮件")
            return 0
    subject, body = build_email(date, signals_to_send, name_map, intraday=args.intraday)
    # 始终打印邮件内容（便于日志/调试/未配置场景查看）
    log.info("===== 邮件主题 =====")
    log.info("%s", subject)
    log.info("===== 邮件正文 =====")
    log.info("%s", body)

    cfg = load_email_config()
    if cfg is None:
        log.warning("未配置 config/email.json —— 跳过实际发送（邮件内容已打印到日志）")
        return 0

    try:
        send_email(cfg, subject, body)
    except Exception as e:  # noqa: BLE001
        log.error("✗ 邮件发送失败：%s（不阻塞流程）", e)
        return 2  # 非 0 但不崩

    # 发送成功后更新 signal_notified.json（标记当日已通知，下次去重跳过）。
    # --full 模式也更新：把当日全部信号标记已通知，防止之后去重模式重复发。
    notified = load_signal_notified()
    today_set = {tuple(x) for x in notified.get(date, [])}
    for s in signals_to_send:
        today_set.add((s["index_id"], s["signal"]))
    notified[date] = sorted([list(x) for x in today_set])
    save_signal_notified(notified)
    log.info(
        "已更新 signal_notified.json：当日已通知 %d 条（%s）",
        len(notified[date]),
        "全量" if args.full else "增量",
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
