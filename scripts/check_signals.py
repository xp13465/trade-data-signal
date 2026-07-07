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
DB_PATH = REPO / "data" / "sentiment.db"
EMAIL_CONFIG = REPO / "config" / "email.json"
INDICATORS_CONFIG = REPO / "config" / "indicators.yaml"

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
}

# index_id 前缀（g.=指标/daily_metric，s.=score_daily 分数，无前缀=指数 index_daily）
_PREFIX_RE = re.compile(r"^(?:g|s)\.(.+)$")

# 邮件正文中的买卖点规则摘要
RULE_SUMMARY = """【买卖点规则说明】
• 买入信号（buy）：RSI 上穿 30（超卖反弹启动）。
• 卖出信号（sell）：20 日高点回落 5%（止盈离场）。
  附 RSI 当前值、综合情绪分 cross 状态、相对前一买点涨跌幅。
"""

DISCLAIMER = """【免责声明】
本信号由历史数据量化回测生成，仅供研究参考，不构成任何投资建议。
市场有风险，投资需谨慎。请结合自身判断与资金管理做出决策。"""

# email.json.example 中的占位密码，识别后跳过实际发送（仅打印内容）
PLACEHOLDER_PASSWORD = "<填163邮箱SMTP授权码，非登录密码>"


def query_signals(date: str) -> list[dict]:
    """查询 signal_daily 当日信号，按 signal, index_id 排序。"""
    if not DB_PATH.exists():
        log.error("数据库不存在：%s", DB_PATH)
        return []
    conn = sqlite3.connect(DB_PATH)
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
    """信号列表 → 品种名摘要（最多 limit 个，多了 '等N个'）。无信号返回 '无'。"""
    if not signals:
        return "无"
    names = [index_id_to_name(s["index_id"], name_map) for s in signals]
    head = ",".join(names[:limit])
    if len(names) > limit:
        return f"{head}等{len(names)}个"
    return head


def build_email(date: str, signals: list[dict], name_map: dict[str, str]) -> tuple[str, str]:
    """构建邮件主题 + 正文。返回 (subject, body)。"""
    buys = [s for s in signals if s["signal"] == "buy"]
    sells = [s for s in signals if s["signal"] == "sell"]
    others = [s for s in signals if s["signal"] not in ("buy", "sell")]
    n = len(signals)

    # 主题加品种摘要：买:WTI原油 卖:深成指,恒生（每边最多3个，多了等N个）
    buy_summary = _summary_names(buys, name_map)
    sell_summary = _summary_names(sells, name_map)
    subject = f"[买卖点信号] {date} 买:{buy_summary} 卖:{sell_summary}"

    lines: list[str] = []
    lines.append(f"【买卖点信号】{date}  共 {n} 个信号（买 {len(buys)} / 卖 {len(sells)}）")
    lines.append("")

    # 买入信号
    lines.append(f"═══════════ 📈 买入信号（{len(buys)}） ═══════════")
    if buys:
        for s in buys:
            name = index_id_to_name(s["index_id"], name_map)
            lines.append(f"  • {name}（{s['index_id']}）  {s['reason'] or ''}")
    else:
        lines.append("  （无）")
    lines.append("")

    # 卖出信号
    lines.append(f"═══════════ 📉 卖出信号（{len(sells)}） ═══════════")
    if sells:
        for s in sells:
            name = index_id_to_name(s["index_id"], name_map)
            lines.append(f"  • {name}（{s['index_id']}）  {s['reason'] or ''}")
    else:
        lines.append("  （无）")
    lines.append("")

    # 其他类型（保险起见，理论上只有 buy/sell）
    if others:
        lines.append(f"═══════════ ⚠ 其他信号（{len(others)}） ═══════════")
        for s in others:
            name = index_id_to_name(s["index_id"], name_map)
            lines.append(f"  • {name}（{s['index_id']}）  {s['signal']}: {s['reason'] or ''}")
        lines.append("")

    lines.append("─" * 50)
    lines.append(RULE_SUMMARY)
    lines.append(DISCLAIMER)
    lines.append("")
    lines.append("—— A股/港股/全球情绪数据复盘看板")
    lines.append(f"   生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    body = "\n".join(lines)
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

    msg = MIMEText(body, "plain", "utf-8")
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
    n_sell = sum(1 for s in signals if s["signal"] == "sell")
    log.info("查询到 %d 个信号（buy=%d, sell=%d）", len(signals), n_buy, n_sell)

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
