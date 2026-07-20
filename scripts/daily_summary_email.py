#!/usr/bin/env python3
"""daily_summary_email.py - 每日收盘情绪速递邮件。

读 static-site/data/summary_history.json 取指定日期(默认当日 YYYYMMDD)的
收盘情绪速递,生成纯文本 + 简单 HTML 邮件,复用 config/email.json 的 SMTP
配置发送。非交易日或当日数据未生成时优雅跳过(只 log,不发邮件,不报错)。

数据源:static-site/data/summary_history.json(由 deploy.sh 部署流水线生成,
含恐贪指数 / 情绪分 / 涨跌家数 / 涨停跌停 / 成效额 / 买卖点 / 领涨领跌板块 /
冰点等)。字段以实际为准,缺字段优雅跳过。

用法:
  python scripts/daily_summary_email.py              # 当日
  python scripts/daily_summary_email.py 20260720     # 指定日期 YYYYMMDD
  python scripts/daily_summary_email.py --dry-run    # 生成正文打印到 stdout,不发
  python scripts/daily_summary_email.py 20260720 --dry-run

== 调度集成说明 ==
方案A(推荐):在 scripts/update_all.sh 末尾(backup_db.sh 调用之前)加一行:
    "$PY" "$REPO/scripts/daily_summary_email.py" || echo "⚠ daily_summary_email 失败(不阻塞) rc=$?" | tee -a "$LOG"
  理由:
    1. update_all.sh 是收盘全量入口,跑到末尾时 deploy.sh 已执行(gen_rss 在
       deploy.sh:54 跑),summary_history.json 已是当日最新,数据就绪。
    2. 末尾调用不阻塞核心看板部署;失败用 `|| echo` 兜底,不影响 update_all
       退出码(仍以 RC_CORE 为准)。
    3. 非交易日 update_all 会跳过采集但仍 deploy(读旧 summary),当日无新
       summary 条目时脚本自动跳过不发邮件,无需额外交易日闸门。
    4. 复用现有 launchd 调度(update_all 的 plist),无需新增定时任务。

方案B:launchd 每日 18:00 单独触发。plist 要点:
    - StartCalendarBinding:hour=18 minute=0 Weekday=1-5(仅工作日)
    - ProgramArguments:调 `python scripts/daily_summary_email.py`
    - 放 scripts/plists/ 下(如 daily_summary_email.plist),load: launchctl load
    - 需保证 18:00 时 update_all 已跑完;若 update_all 滞后则邮件读到旧数据。
  缺点:与 update_all 时序解耦,要额外保证先后;update_all 已含邮件通知管线,
  单独再起 plist 增加维护面,故不推荐。

推荐方案A:数据就绪时机最确定、复用现有调度、失败不阻塞、零新增定时任务。

== 安全 ==
SMTP 密码仅用于 smtplib 连接,绝不 print / log / 写入邮件正文 / 落进度文件。
"""
from __future__ import annotations

import argparse
import json
import logging
import smtplib
import sys
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUMMARY_SRC = REPO / "static-site" / "data" / "summary_history.json"
EMAIL_CONFIG = REPO / "config" / "email.json"
SITE_NAME = "A股情绪看板"
SITE_DOMAIN = "s.sugas.site"

# email.json.example 中的占位密码,识别后跳过实际发送
PLACEHOLDER_PASSWORD = "<填163邮箱SMTP授权码,非登录密码>"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("daily_summary_email")


# ---------------------------------------------------------------- 数据读取
def load_summary_item(date: str) -> dict | None:
    """从 summary_history.json 取指定日期(YYYYMMDD)的 item。

    文件缺失/解析失败/无匹配日期 -> 返回 None(调用方优雅跳过)。
    """
    if not SUMMARY_SRC.exists():
        log.warning("summary_history.json 不存在:%s", SUMMARY_SRC)
        return None
    try:
        data = json.loads(SUMMARY_SRC.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        log.warning("summary_history.json 解析失败:%s", e)
        return None
    items = data.get("items") if isinstance(data, dict) else data
    if not isinstance(items, list):
        log.warning("summary_history.json 无 items 列表")
        return None
    for it in items:
        if isinstance(it, dict) and str(it.get("date", "")) == date:
            return it
    return None


def iso_date(date_str: str) -> str:
    """'20260720' -> '2026-07-20'(非法原样返回)。"""
    try:
        return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
    except Exception:
        return str(date_str)


def weekday_cn(date_str: str) -> str:
    """'20260720' -> '周日'。非法返回空串。"""
    try:
        d = datetime(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:8]))
        return "周" + "一二三四五六日"[d.weekday()]
    except Exception:
        return ""


def fmt_pct(v, places=2) -> str:
    """浮点涨跌幅 -> '+0.85%' / '-1.20%';None 返回 'NA'。"""
    if v is None:
        return "NA"
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.{places}f}%"


def ind_names(arr, n=3) -> str:
    """板块数组 -> '名称(+x.x%)、名称(-x.x%)';无数据返回空串。"""
    out = []
    for it in (arr or [])[:n]:
        name = it.get("name", "?")
        pct = it.get("pct_change")
        if pct is None:
            out.append(str(name))
        else:
            sign = "+" if pct >= 0 else ""
            out.append(f"{name}({sign}{pct:.1f}%)")
    return "、".join(out)


# ---------------------------------------------------------------- 正文生成
def build_subject(it: dict) -> str:
    """邮件主题:[收盘速递] 2026-07-20 周日 | 恐贪35.8 恐惧 | 情绪低迷。"""
    date_str = it.get("date", "")
    fg = it.get("fear_greed_value")
    fg_label = it.get("fear_greed_label") or ""
    sent_label = it.get("sentiment_label") or ""
    fg_str = f"{fg:.1f}" if isinstance(fg, (int, float)) else "NA"
    wd = weekday_cn(date_str)
    wd_str = f" {wd}" if wd else ""
    parts = [f"恐贪{fg_str}"]
    if fg_label:
        parts[0] = f"恐贪{fg_str} {fg_label}"
    sent_part = f" | {sent_label}" if sent_label else ""
    return f"[收盘速递] {iso_date(date_str)}{wd_str} | {' '.join(parts)}{sent_part}"


def build_text(it: dict) -> str:
    """生成纯文本正文(ASCII 示意格式)。"""
    date_str = it.get("date", "")
    lines = []
    lines.append("=" * 44)
    lines.append(f"  A股收盘情绪速递 · {iso_date(date_str)} {weekday_cn(date_str)}")
    lines.append("=" * 44)

    # 恐贪 + 情绪分
    fg = it.get("fear_greed_value")
    fg_label = it.get("fear_greed_label")
    ss = it.get("sentiment_score")
    slabel = it.get("sentiment_label")
    seg = []
    if isinstance(fg, (int, float)):
        seg.append(f"恐贪指数:{fg:.1f}" + (f"({fg_label})" if fg_label else ""))
    if isinstance(ss, (int, float)):
        seg.append(f"情绪分:{ss:.1f}" + (f"({slabel})" if slabel else ""))
    if seg:
        lines.append(" | ".join(seg))

    # 上证
    sh_pct = it.get("sh_pct")
    sh_close = it.get("sh_close")
    if sh_pct is not None:
        close_str = f" 收 {sh_close:.0f}" if sh_close is not None else ""
        lines.append(f"上证指数:{fmt_pct(sh_pct)}{close_str}")

    # 涨跌家数 + 涨停跌停
    up, down = it.get("up_count"), it.get("down_count")
    zt, dt = it.get("zt_count"), it.get("dt_count")
    mk = []
    if up is not None and down is not None:
        mk.append(f"涨跌家数:{up}涨 / {down}跌")
    if zt is not None and dt is not None:
        mk.append(f"涨停{zt} / 跌停{dt}")
    if mk:
        lines.append(" | ".join(mk))

    # 成交额
    vol = it.get("volume_amount")
    vol_label = it.get("volume_label")
    if vol is not None:
        lines.append(f"成交额:{vol:.0f}亿" + (f"({vol_label})" if vol_label else ""))

    # 买卖点
    buy, sell = it.get("buy_count"), it.get("sell_count")
    if buy is not None and sell is not None:
        lines.append(f"买卖点:买{buy} / 卖{sell}")

    # 新高新低 + 均线多空
    nh, nl = it.get("nh_count"), it.get("nl_count")
    mab, mas = it.get("ma_bullish"), it.get("ma_bearish")
    mk2 = []
    if nh is not None and nl is not None:
        mk2.append(f"新高{nh} / 新低{nl}")
    if mab is not None and mas is not None:
        mk2.append(f"均线 多{mab} / 空{mas}")
    if mk2:
        lines.append(" | ".join(mk2))

    # 冰点
    if it.get("is_freeze") and it.get("freeze_info"):
        lines.append(str(it["freeze_info"]))

    lines.append("-" * 44)
    top = ind_names(it.get("top_industries"))
    bot = ind_names(it.get("bottom_industries"))
    if top:
        lines.append(f"领涨:{top}")
    if bot:
        lines.append(f"领跌:{bot}")

    # 摘要(优先短摘要)
    lines.append("-" * 44)
    summary = it.get("summary_short") or it.get("summary")
    if summary:
        lines.append("摘要:" + str(summary))

    lines.append("-" * 44)
    lines.append(f"由 {SITE_NAME} 自动发送 · {SITE_DOMAIN}")
    return "\n".join(lines)


def build_html(it: dict) -> str:
    """生成简单 HTML 正文(内联 style,禁图片/外部资源/外部 URL)。"""
    date_str = it.get("date", "")
    rows = []  # (label, value)

    def add(label, value):
        if value:
            rows.append((label, value))

    fg = it.get("fear_greed_value")
    fg_label = it.get("fear_greed_label")
    if isinstance(fg, (int, float)):
        add("恐贪指数", f"{fg:.1f}" + (f"({fg_label})" if fg_label else ""))
    ss = it.get("sentiment_score")
    slabel = it.get("sentiment_label")
    if isinstance(ss, (int, float)):
        add("情绪分", f"{ss:.1f}" + (f"({slabel})" if slabel else ""))

    sh_pct = it.get("sh_pct")
    sh_close = it.get("sh_close")
    if sh_pct is not None:
        color = "#e6492e" if sh_pct >= 0 else "#2e8b57"
        close_str = f" 收 {sh_close:.0f}" if sh_close is not None else ""
        add("上证指数", f'<span style="color:{color};">{fmt_pct(sh_pct)}</span>{close_str}')

    up, down = it.get("up_count"), it.get("down_count")
    if up is not None and down is not None:
        add("涨跌家数", f'{up}涨 / <span style="color:#2e8b57;">{down}跌</span>')
    zt, dt = it.get("zt_count"), it.get("dt_count")
    if zt is not None and dt is not None:
        add("涨停/跌停", f"{zt} / {dt}")

    vol = it.get("volume_amount")
    vol_label = it.get("volume_label")
    if vol is not None:
        add("成交额", f"{vol:.0f}亿" + (f"({vol_label})" if vol_label else ""))

    buy, sell = it.get("buy_count"), it.get("sell_count")
    if buy is not None and sell is not None:
        add("买卖点", f"买{buy} / 卖{sell}")

    nh, nl = it.get("nh_count"), it.get("nl_count")
    if nh is not None and nl is not None:
        add("新高/新低", f"{nh} / {nl}")
    mab, mas = it.get("ma_bullish"), it.get("ma_bearish")
    if mab is not None and mas is not None:
        add("均线多空", f"多{mab} / 空{mas}")

    freeze_html = ""
    if it.get("is_freeze") and it.get("freeze_info"):
        freeze_html = (
            f'<div style="margin:8px 0;padding:8px 12px;background:#fff7e6;'
            f'border-left:3px solid #fa8c16;border-radius:4px;font-size:13px;">'
            f'{_esc(it["freeze_info"])}</div>'
        )

    top = ind_names(it.get("top_industries"))
    bot = ind_names(it.get("bottom_industries"))
    summary = it.get("summary_short") or it.get("summary")

    table_rows = ""
    for label, value in rows:
        table_rows += (
            f'<tr><td style="padding:6px 12px;color:#86909c;font-size:13px;'
            f'white-space:nowrap;">{label}</td>'
            f'<td style="padding:6px 12px;font-size:13px;font-weight:600;">{value}</td></tr>'
        )

    section_html = ""
    if top or bot:
        sec = ['<div style="margin:12px 0;font-size:13px;line-height:1.8;">']
        if top:
            sec.append(f'<div>领涨:<span style="color:#e6492e;">{_esc(top)}</span></div>')
        if bot:
            sec.append(f'<div>领跌:<span style="color:#2e8b57;">{_esc(bot)}</span></div>')
        sec.append("</div>")
        section_html = "".join(sec)

    summary_html = ""
    if summary:
        summary_html = (
            f'<div style="margin:12px 0;padding:10px 12px;background:#f7f8fa;'
            f'border-radius:6px;font-size:13px;color:#4e5969;line-height:1.7;">'
            f'{_esc(summary)}</div>'
        )

    return f"""<html><body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;font-size:14px;color:#1d2129;max-width:560px;">
<h2 style="margin:0 0 4px 0;color:#1d2129;">A股收盘情绪速递</h2>
<p style="margin:0 0 12px 0;color:#86909c;font-size:13px;">{iso_date(date_str)} {weekday_cn(date_str)}</p>
<table style="border-collapse:collapse;margin-bottom:4px;">{table_rows}</table>
{freeze_html}
{section_html}
{summary_html}
<p style="color:#c9cdd4;font-size:11px;margin-top:16px;">-- 由 {SITE_NAME} 自动发送 · {SITE_DOMAIN}</p>
</body></html>"""


def _esc(s) -> str:
    """HTML 文本转义。"""
    if s is None:
        return ""
    return (str(s).replace("&", "&amp;")
                  .replace("<", "&lt;")
                  .replace(">", "&gt;"))


# ---------------------------------------------------------------- 邮件发送
def load_email_config() -> dict | None:
    """读 config/email.json。不存在/解析失败返回 None。不泄露密码。"""
    if not EMAIL_CONFIG.exists():
        log.warning("config/email.json 不存在,跳过邮件(复制 email.json.example 并填 SMTP 授权码后启用)")
        return None
    try:
        return json.loads(EMAIL_CONFIG.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        log.error("config/email.json 解析失败:%s", e)
        return None


def _resolve_recipients(cfg: dict, user: str) -> list[str]:
    """to 兼容 str(逗号分隔)/list -> list[str]。空则回退到 user。"""
    to_raw = cfg.get("to", user)
    if isinstance(to_raw, str):
        tos = [t.strip() for t in to_raw.split(",") if t.strip()]
    elif isinstance(to_raw, list):
        tos = [str(t).strip() for t in to_raw if str(t).strip()]
    else:
        tos = []
    return tos or [user]


def send_email(cfg: dict, subject: str, text_body: str, html_body: str) -> bool:
    """SMTP SSL 发邮件(MIMEMultipart alternative:纯文本 + HTML)。

    password 仅用于连接,绝不输出。发送失败只 log 不抛。
    返回 True=发出(或配置缺失跳过算 False),False=未发。
    """
    smtp = cfg.get("smtp", "smtp.163.com")
    port = int(cfg.get("port", 465))
    user = cfg.get("user", "")
    password = cfg.get("password", "")
    to_list = _resolve_recipients(cfg, user)

    if not user or not password or password == PLACEHOLDER_PASSWORD:
        log.warning("SMTP password 缺失或仍为占位符 -- 跳过实际发送(正文已打印到日志)")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = formataddr((SITE_NAME, user))
    msg["To"] = ", ".join(to_list)
    msg["Date"] = formatdate(localtime=True)
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP_SSL(smtp, port, timeout=30) as srv:
            srv.login(user, password)
            srv.sendmail(user, to_list, msg.as_string())
        log.info("✓ 邮件已发送至 %s:%s", ", ".join(to_list), subject)
        return True
    except Exception as e:  # noqa: BLE001
        log.error("✗ 邮件发送失败(不阻塞):%s", e)
        return False


# ---------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="每日收盘情绪速递邮件")
    parser.add_argument("date", nargs="?", help="日期 YYYYMMDD(默认当日)")
    parser.add_argument("--dry-run", action="store_true", help="生成正文打印到 stdout,不发邮件")
    args = parser.parse_args(argv)

    date = args.date or datetime.now().strftime("%Y%m%d")
    log.info("=== daily_summary_email 开始,日期:%s%s ===", date, " [dry-run]" if args.dry_run else "")

    it = load_summary_item(date)
    if it is None:
        log.info("日期 %s 无 summary_history 数据(非交易日或数据未生成),跳过不发邮件", date)
        if args.dry_run:
            print(f"[dry-run] 日期 {date} 无数据,容错跳过(证明容错生效)")
        return 0

    subject = build_subject(it)
    text_body = build_text(it)
    html_body = build_html(it)

    if args.dry_run:
        print("===== 邮件主题 =====")
        print(subject)
        print("===== 纯文本正文 =====")
        print(text_body)
        print("===== HTML 正文 =====")
        print(html_body)
        return 0

    cfg = load_email_config()
    if cfg is None:
        # 配置缺失也算正常退出(不阻塞调度)
        return 0

    send_email(cfg, subject, text_body, html_body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
