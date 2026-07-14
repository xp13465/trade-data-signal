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
from datetime import datetime
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
• 卖（sell）：20 日高点回落 5% + MA60 多头过滤 + MACD 死叉确认（止盈减仓提示）。
  附 RSI 当前值、综合情绪分 cross 状态、相对前一买点盈亏标注。</div>"""

DISCLAIMER = """【免责声明】
本信号由历史数据量化回测生成，仅供研究参考，不构成任何投资建议。
市场有风险，投资需谨慎。请结合自身判断与资金管理做出决策。</div>"""

# 信号类型中文标签
SIGNAL_LABELS = {"buy": "主买", "buy_aux": "辅买", "sell": "卖"}
SIGNAL_ORDER = ["buy", "buy_aux", "sell"]

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


def build_email(date: str, signals: list[dict], name_map: dict[str, str]) -> tuple[str, str]:
    """构建邮件主题 + HTML 正文。返回 (subject, html_body)。"""
    stats = load_signal_stats()

    # 按 signal 类型分组（buy / buy_aux / sell）
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
    n_sell = len(groups["sell"])

    # === 标题：信号类型 + 品种摘要 ===
    parts = []
    for sig_type in SIGNAL_ORDER:
        g = groups[sig_type]
        label = _signal_label(sig_type)
        if g:
            summary = _summary_names(g, name_map, limit=3)
            parts.append(f"{label}×{len(g)} {summary}")
    subject = f"[买卖点信号] {date}  {' | '.join(parts) if parts else '无信号'}"

    # === HTML 正文 ===
    html_parts = [f"""<html><body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;font-size:14px;color:#1d2129;max-width:720px;">
<h2 style="margin:0 0 8px 0;color:#1d2129;">📊 买卖点信号日报</h2>
<p style="margin:0 0 16px 0;color:#86909c;font-size:13px;">{date} · 共 <b>{n_total}</b> 个信号（主买 {n_buy} / 辅买 {n_aux} / 卖 {n_sell}）</p>"""]

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
• 卖（sell）：20 日高点回落 5% + MA60 多头过滤 + MACD 死叉确认（止盈减仓提示）<br>
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
    args = parser.parse_args(argv)

    date = args.date or datetime.now().strftime("%Y%m%d")
    log.info("=== check_signals 开始，查询日期：%s ===", date)

    signals = query_signals(date)
    if not signals:
        log.info("今日（%s）无买卖点信号，不发邮件", date)
        return 0

    n_buy = sum(1 for s in signals if s["signal"] == "buy")
    n_aux = sum(1 for s in signals if s["signal"] == "buy_aux")
    n_sell = sum(1 for s in signals if s["signal"] == "sell")
    log.info("查询到 %d 个信号（主买=%d, 辅买=%d, 卖=%d）", len(signals), n_buy, n_aux, n_sell)

    name_map = load_name_map()
    subject, body = build_email(date, signals, name_map)
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

    return 0


if __name__ == "__main__":
    sys.exit(main())
