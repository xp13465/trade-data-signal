#!/usr/bin/env python3
"""daily_summary_email.py - 每日收盘情绪速递邮件。

读 static-site/data/summary_history.json 取指定日期(默认当日 YYYYMMDD)的
收盘情绪速递,生成纯文本 + 简单 HTML 邮件,复用 config/email.json 的 SMTP
配置发送。非交易日或当日数据未生成时优雅跳过(只 log,不发邮件,不报错)。

数据源:static-site/data/summary_history.json(由 deploy.sh 部署流水线生成,
含恐贪指数 / 情绪分 / 涨跌家数 / 涨停跌停 / 成效额 / 关注风险点 / 领涨领跌板块 /
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

REPO = Path(__file__).absolute().parent.parent
SUMMARY_SRC = REPO / "static-site" / "data" / "summary_history.json"
SUBSCRIPTIONS_SRC = REPO / "config" / "subscriptions.json"
EMAIL_CONFIG = REPO / "config" / "email.json"
# 方案B 融合段数据源（均读 static-site/data/ JSON，不碰根 data/ 下文件）
FUTURES_SRC = REPO / "static-site" / "data" / "futures.json"
FUTURES_CONCLUSION_SRC = REPO / "static-site" / "data" / "futures_acc_conclusion.json"
NT_SRC = REPO / "static-site" / "data" / "etf_national_team-1m.json"
PF_SUMMARY_SRC = REPO / "static-site" / "data" / "public_fund_summary.json"
PF_ESTIMATE_SRC = REPO / "static-site" / "data" / "public_fund_position_estimate.json"
PF_BACKTEST_SRC = REPO / "static-site" / "data" / "public_fund_position_backtest.json"
PF_TOP20_SRC = REPO / "static-site" / "data" / "public_fund_top20.json"
SITE_NAME = "信号实验室"
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


def build_text(it: dict, subs: list[dict] | None = None, extras: dict | None = None) -> str:
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

    # 关注/风险点
    buy, sell = it.get("buy_count"), it.get("sell_count")
    if buy is not None and sell is not None:
        lines.append(f"关注/风险点:关注{buy} / 风险{sell}")

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

    # 方案B 融合段（期货风向 / 汪汪队 / 公募基金），缺数据优雅跳过
    if extras:
        fut = extras.get("futures")
        if fut:
            seg = build_futures_text(fut)
            if seg:
                lines.append(seg)
        nt = extras.get("nt")
        if nt:
            seg = build_nt_text(nt)
            if seg:
                lines.append(seg)
        pf = extras.get("pf")
        if pf:
            seg = build_pf_text(pf)
            if seg:
                lines.append(seg)

    # 订阅列表段（失败/无订阅则跳过，不阻塞）
    if subs:
        subs_seg = build_subs_text(subs)
        if subs_seg:
            lines.append(subs_seg)

    lines.append("-" * 44)
    lines.append(f"由 {SITE_NAME} 自动发送 · {SITE_DOMAIN}")
    return "\n".join(lines)


def build_html(it: dict, subs: list[dict] | None = None, extras: dict | None = None) -> str:
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
        add("关注/风险点", f"关注{buy} / 风险{sell}")

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

    # 方案B 融合段（期货风向 / 汪汪队 / 公募基金），缺数据优雅跳过
    extra_html = ""
    if extras:
        fut = extras.get("futures")
        if fut:
            extra_html += build_futures_html(fut)
        nt = extras.get("nt")
        if nt:
            extra_html += build_nt_html(nt)
        pf = extras.get("pf")
        if pf:
            extra_html += build_pf_html(pf)

    # 订阅列表段（失败/无订阅则跳过，不阻塞）
    subs_html = build_subs_html(subs) if subs else ""

    return f"""<html><body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;font-size:14px;color:#1d2129;max-width:560px;">
<h2 style="margin:0 0 4px 0;color:#1d2129;">A股收盘情绪速递</h2>
<p style="margin:0 0 12px 0;color:#86909c;font-size:13px;">{iso_date(date_str)} {weekday_cn(date_str)}</p>
<table style="border-collapse:collapse;margin-bottom:4px;">{table_rows}</table>
{freeze_html}
{section_html}
{summary_html}
{extra_html}
{subs_html}
<p style="color:#c9cdd4;font-size:11px;margin-top:16px;">-- 由 {SITE_NAME} 自动发送 · {SITE_DOMAIN}</p>
</body></html>"""


def _esc(s) -> str:
    """HTML 文本转义。"""
    if s is None:
        return ""
    return (str(s).replace("&", "&amp;")
                  .replace("<", "&lt;")
                  .replace(">", "&gt;"))


# ---------------------------------------------------------------- 订阅列表段
# 信号 key -> 中文标签（合规版，与 app.js _SUB_SIGNAL_LABELS + i18n.js compliance dict 对齐）
_SUB_SIGNAL_LABELS = {
    "buy": "主关注",
    "buy_aux": "辅关注",
    "buy_special": "追关注",
    "buy_backup": "备关注",
    "sell": "风险提示",
    "sell_stop_loss": "追风控",
}


def _mask_email(email: str) -> str:
    """邮箱脱敏：首字母 + ***@域名。sugas13465@gmail.com -> s***@gmail.com。

    空串/无@ 原样返回（不脱敏无意义）。
    """
    email = email or ""
    if "@" not in email:
        return email
    local, _, domain = email.partition("@")
    if not local:
        return email
    return f"{local[0]}***@{domain}"


def load_subscriptions() -> list[dict]:
    """读 config/subscriptions.json，返回 subscriptions 列表。

    文件缺失/解析失败/无 subscriptions 字段 -> 返回空列表（调用方优雅跳过该段）。
    失败不阻塞邮件发送。
    """
    if not SUBSCRIPTIONS_SRC.exists():
        log.info("config/subscriptions.json 不存在，跳过订阅列表段")
        return []
    try:
        data = json.loads(SUBSCRIPTIONS_SRC.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        log.warning("config/subscriptions.json 解析失败，跳过订阅列表段：%s", e)
        return []
    subs = data.get("subscriptions") if isinstance(data, dict) else data
    if not isinstance(subs, list):
        return []
    return [s for s in subs if isinstance(s, dict)]


def _format_signals(signals) -> str:
    """信号 key 列表 -> 中文标签用 / 分隔。未知 key 原样保留。"""
    if not isinstance(signals, list):
        return ""
    return "/".join(_SUB_SIGNAL_LABELS.get(str(s), str(s)) for s in signals)


def _format_targets(targets) -> str:
    """标的列表 -> 逗号分隔字符串。"""
    if not isinstance(targets, list):
        return ""
    return ", ".join(str(t) for t in targets)


def build_subs_text(subs: list[dict]) -> str:
    """生成订阅列表纯文本段。空列表返回空串（不输出该段）。"""
    if not subs:
        return ""
    lines = ["", "📋 当前订阅列表（%d 条）：" % len(subs)]
    for i, s in enumerate(subs, 1):
        name = s.get("name", "") or ""
        targets = _format_targets(s.get("targets"))
        signals = _format_signals(s.get("signals"))
        email = _mask_email(s.get("email", ""))
        enabled = "启用" if s.get("enabled", True) else "停用"
        lines.append(
            f"[{i}] {name} ({enabled}) | 标的:{targets} | 信号:{signals} | {email}"
        )
    return "\n".join(lines)


def build_subs_html(subs: list[dict]) -> str:
    """生成订阅列表 HTML 段。空列表返回空串。"""
    if not subs:
        return ""
    rows = ""
    for i, s in enumerate(subs, 1):
        name = _esc(s.get("name", ""))
        targets = _esc(_format_targets(s.get("targets")))
        signals = _esc(_format_signals(s.get("signals")))
        email = _esc(_mask_email(s.get("email", "")))
        enabled = "启用" if s.get("enabled", True) else "停用"
        enabled_color = "#2e8b57" if s.get("enabled", True) else "#86909c"
        rows += (
            f'<tr><td style="padding:4px 8px;color:#86909c;font-size:12px;'
            f'vertical-align:top;">#{i}</td>'
            f'<td style="padding:4px 8px;font-size:12px;line-height:1.6;">'
            f'<b>{name}</b> '
            f'<span style="color:{enabled_color};">({enabled})</span><br>'
            f'<span style="color:#4e5969;">标的:{targets}</span> | '
            f'<span style="color:#4e5969;">信号:{signals}</span><br>'
            f'<span style="color:#c9cdd4;">{email}</span></td></tr>'
        )
    return (
        f'<h3 style="margin:16px 0 6px 0;color:#1d2129;font-size:14px;">'
        f'📋 当前订阅列表（{len(subs)} 条）</h3>'
        f'<table style="border-collapse:collapse;margin-bottom:8px;">{rows}</table>'
    )


# ---------------------------------------------------------------- 通用 JSON 读取
def _load_json_safe(path: Path) -> dict | list | None:
    """安全读 JSON：文件缺失/解析失败返回 None（调用方优雅跳过该段）。"""
    if not path.exists():
        log.info("%s 不存在，跳过对应段", path.name)
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        log.warning("%s 解析失败，跳过对应段：%s", path.name, e)
        return None


# ---------------------------------------------------------------- 段1 期货风向
# (conclusion_key, futures_key, 展示标签)
_FUT_ROLES = [
    ("机构前20", "机构(前20)", "机构前20"),
    ("中信期货", "中信期货", "中信期货"),
    ("国泰君安", "国泰君安", "国泰君安"),
]


def _dir_cn(d) -> str:
    """long/short -> 多/空。"""
    return {"long": "多", "short": "空"}.get(str(d) if d is not None else "", d or "-")


def _bet_mark(net_dir, ret) -> str:
    """次日验证对错标记。long+涨=对，short+跌=对。"""
    if ret is None:
        return "-"
    if net_dir == "long":
        return "✓" if ret > 0 else "✗"
    if net_dir == "short":
        return "✓" if ret < 0 else "✗"
    return "-"


def load_futures_brief() -> dict | None:
    """读 futures.json + futures_acc_conclusion.json，汇总期货风向段数据。

    返回 None=数据缺失（跳过该段）。
    """
    fj = _load_json_safe(FUTURES_SRC)
    cj = _load_json_safe(FUTURES_CONCLUSION_SRC)
    if not isinstance(fj, dict) or not isinstance(cj, dict):
        return None
    acc = fj.get("accuracy") or {}
    bet = fj.get("latest_bet") or {}
    state = cj.get("current_state") or {}
    conclusions = cj.get("conclusions") or []
    roles = []
    for ck, fk, label in _FUT_ROLES:
        st = state.get(ck) or {}
        ac = acc.get(fk) or {}
        bt = bet.get(fk) or {}
        roles.append({
            "label": label,
            "accuracy": st.get("accuracy"),
            "dominant_dir": st.get("dominant_dir"),
            "streak_days": st.get("streak_days"),
            "streak_type": st.get("streak_type"),
            "net_direction": ac.get("net_direction"),  # 当日方向
            "bet_direction": bt.get("net_direction"),  # 验证日下注方向
            "bet_return": bt.get("actual_return"),     # 次日实际涨幅
            "bet_date": bt.get("date"),
        })
    triggered = [c for c in conclusions if isinstance(c, dict) and c.get("triggered")]
    return {
        "futures_date": (fj.get("summary") or {}).get("date"),
        "as_of_date": cj.get("as_of_date"),
        "roles": roles,
        "triggered": triggered,
    }


def build_futures_text(d: dict) -> str:
    """期货风向纯文本段。"""
    lines = ["", "-" * 44, f"期货风向（数据日期 {d.get('futures_date') or d.get('as_of_date') or '-'}）："]
    for r in d.get("roles", []):
        acc = r.get("accuracy")
        ddir = r.get("dominant_dir") or "-"
        stk = r.get("streak_type") or "-"
        sdays = r.get("streak_days")
        net = _dir_cn(r.get("net_direction"))
        acc_s = f"{acc:.1f}%" if isinstance(acc, (int, float)) else "-"
        sd_s = f"{sdays}" if sdays is not None else "-"
        lines.append(f"  {r['label']}  准确率{acc_s} {ddir}连续{sd_s}日 | 当日: {net}")
    tg = d.get("triggered") or []
    if tg:
        parts = []
        for c in tg:
            sig = c.get("signal", "")
            stats = c.get("stats", "")
            act = c.get("action", "")
            parts.append(f"{sig}({stats})->{act}")
        lines.append("  触发规律: " + "；".join(parts))
    # 次日验证
    bet_parts = []
    for r in d.get("roles", []):
        bd = r.get("bet_direction")
        br = r.get("bet_return")
        if bd is None:
            continue
        mark = _bet_mark(bd, br)
        ret_s = fmt_pct(br) if br is not None else "NA"
        bet_parts.append(f"{r['label']} {_dir_cn(bd)} 实涨{ret_s} {mark}")
    if bet_parts:
        bdate = d.get("roles", [{}])[0].get("bet_date") if d.get("roles") else None
        lines.append(f"  次日验证({bdate or '-'}): " + " | ".join(bet_parts))
    return "\n".join(lines)


def build_futures_html(d: dict) -> str:
    """期货风向 HTML 段（内联 style）。"""
    rows_html = ""
    for r in d.get("roles", []):
        acc = r.get("accuracy")
        acc_s = f"{acc:.1f}%" if isinstance(acc, (int, float)) else "-"
        ddir = _esc(r.get("dominant_dir") or "-")
        stk = _esc(r.get("streak_type") or "-")
        sdays = r.get("streak_days")
        sd_s = str(sdays) if sdays is not None else "-"
        net = _esc(_dir_cn(r.get("net_direction")))
        rows_html += (
            f'<tr><td style="padding:4px 10px;color:#4e5969;font-size:13px;">{_esc(r["label"])}</td>'
            f'<td style="padding:4px 10px;font-size:13px;">准确率<b>{_esc(acc_s)}</b> '
            f'{ddir}连续{sd_s}日</td>'
            f'<td style="padding:4px 10px;font-size:13px;color:#86909c;">当日:{net}</td></tr>'
        )
    tg_html = ""
    tg = d.get("triggered") or []
    if tg:
        items = []
        for c in tg:
            items.append(
                f'<div style="margin:2px 0;"><b style="color:#d4380d;">{_esc(c.get("signal",""))}</b>'
                f'<span style="color:#86909c;"> ({_esc(c.get("stats",""))})</span>'
                f' -> {_esc(c.get("action",""))}</div>'
            )
        tg_html = (
            f'<div style="margin:8px 0;font-size:12px;line-height:1.7;">'
            f'<span style="color:#86909c;">触发规律：</span>'
            + "".join(items) + '</div>'
        )
    bet_html = ""
    bet_parts = []
    for r in d.get("roles", []):
        bd = r.get("bet_direction")
        br = r.get("bet_return")
        if bd is None:
            continue
        mark = _bet_mark(bd, br)
        mark_color = "#2e8b57" if mark == "✓" else "#e6492e"
        ret_s = fmt_pct(br) if br is not None else "NA"
        bet_parts.append(
            f'{_esc(r["label"])} {_esc(_dir_cn(bd))} 实涨{_esc(ret_s)} '
            f'<span style="color:{mark_color};font-weight:600;">{mark}</span>'
        )
    if bet_parts:
        bdate = d.get("roles", [{}])[0].get("bet_date") if d.get("roles") else None
        bet_html = (
            f'<div style="margin:8px 0;font-size:12px;color:#4e5969;">'
            f'次日验证({_esc(bdate or "-")}): {" | ".join(bet_parts)}</div>'
        )
    return (
        f'<h3 style="margin:16px 0 6px 0;color:#1d2129;font-size:14px;">📈 期货风向'
        f'<span style="color:#86909c;font-size:12px;font-weight:normal;">（数据日期 {_esc(d.get("futures_date") or d.get("as_of_date") or "-")}）</span></h3>'
        f'<table style="border-collapse:collapse;margin-bottom:4px;">{rows_html}</table>'
        f'{tg_html}{bet_html}'
    )


# ---------------------------------------------------------------- 段2 汪汪队信号
# 共振阈值（与 check_nt_signals.py THR 一致）
_NT_THR = {"surge": 2, "outflow": 2, "volume": 3}
_NT_SIG_LABEL = {"share_surge": "进", "share_outflow": "出", "volume_surge": "量"}
_NT_SIG_COLOR = {"share_surge": "#e6492e", "share_outflow": "#2e8b57", "volume_surge": "#ff9800"}


def load_nt_brief() -> dict | None:
    """读 etf_national_team-1m.json，取最新数据日信号 + 共振。

    ETF 份额 T+1 发布，最新数据日通常为 T-1。无信号返回 None（省略该段）。
    """
    nj = _load_json_safe(NT_SRC)
    if not isinstance(nj, dict):
        return None
    etfs = nj.get("etfs") or []
    if not etfs:
        return None
    # 找最新数据日
    all_dates = set()
    for e in etfs:
        for dd in e.get("daily") or []:
            if dd.get("date"):
                all_dates.add(dd["date"])
    if not all_dates:
        return None
    latest = max(all_dates)
    # 收集当日信号 + 份额变动
    sig_etfs = []  # [{code,name,signals:[{type,share_change,amount_ratio,intensity,note}],share_change_yi}]
    net_share = 0.0
    n_inc = n_dec = 0
    for e in etfs:
        for dd in e.get("daily") or []:
            if dd.get("date") != latest:
                continue
            scy = dd.get("share_change_yi")
            if isinstance(scy, (int, float)):
                net_share += scy
                if scy > 0:
                    n_inc += 1
                elif scy < 0:
                    n_dec += 1
            sigs = dd.get("signals") or []
            if sigs:
                sig_etfs.append({
                    "code": e.get("code", ""),
                    "name": e.get("name", ""),
                    "signals": sigs,
                    "share_change_yi": scy,
                })
            break  # 每只 etf 当日只一条 daily
    if not sig_etfs:
        return None  # 当日无信号 -> 省略该段
    # 共振判断
    codes_by_type = {"share_surge": set(), "share_outflow": set(), "volume_surge": set()}
    for s in sig_etfs:
        for sg in s["signals"]:
            t = sg.get("type")
            if t in codes_by_type:
                codes_by_type[t].add(s["code"])
    n_surge = len(codes_by_type["share_surge"])
    n_outflow = len(codes_by_type["share_outflow"])
    n_volume = len(codes_by_type["volume_surge"])
    is_res = n_surge >= _NT_THR["surge"] or n_outflow >= _NT_THR["outflow"] or n_volume >= _NT_THR["volume"]
    # 信号 ETF top3（按最大 intensity 绝对值排序）
    def _max_abs_intensity(s):
        vals = [abs(sg.get("intensity") or 0) for sg in s.get("signals", [])]
        return max(vals) if vals else 0
    sig_etfs.sort(key=_max_abs_intensity, reverse=True)
    return {
        "data_date": latest,
        "n_surge": n_surge,
        "n_outflow": n_outflow,
        "n_volume": n_volume,
        "is_resonance": is_res,
        "net_share": net_share,
        "n_inc": n_inc,
        "n_dec": n_dec,
        "top_etfs": sig_etfs[:3],
    }


def build_nt_text(d: dict) -> str:
    """汪汪队信号纯文本段。"""
    parts = []
    if d["n_surge"]:
        parts.append(f"进{d['n_surge']}")
    if d["n_outflow"]:
        parts.append(f"出{d['n_outflow']}")
    if d["n_volume"]:
        parts.append(f"量{d['n_volume']}")
    summary = " ".join(parts) if parts else "无信号"
    res_tag = " | 🐾共振" if d.get("is_resonance") else ""
    lines = ["", "-" * 44, f"汪汪队信号（数据日期 {d.get('data_date', '-')} T-1）："]
    lines.append(f"  {summary}{res_tag}")
    net = d.get("net_share", 0)
    net_s = f"+{net:.2f}" if isinstance(net, (int, float)) and net >= 0 else (f"{net:.2f}" if isinstance(net, (int, float)) else "-")
    lines.append(f"  净申购份额 {net_s}亿份 | 增持{d.get('n_inc', 0)}只 减持{d.get('n_dec', 0)}只")
    etf_strs = []
    for s in d.get("top_etfs", []):
        types = "/".join(_NT_SIG_LABEL.get(sg.get("type"), sg.get("type", "")) for sg in s.get("signals", []))
        scy = s.get("share_change_yi")
        scy_s = f"+{scy:.2f}" if isinstance(scy, (int, float)) and scy >= 0 else (f"{scy:.2f}" if isinstance(scy, (int, float)) else "-")
        # 量比取该 etf 信号里最大 amount_ratio
        ratios = [sg.get("amount_ratio") for sg in s.get("signals", []) if sg.get("amount_ratio") is not None]
        ratio_s = f"{max(ratios):.2f}倍" if ratios else ""
        etf_strs.append(f"{s.get('code','')} {s.get('name','')} {types} {scy_s}亿份 {ratio_s}".strip())
    if etf_strs:
        lines.append("  信号ETF: " + " | ".join(etf_strs))
    return "\n".join(lines)


def build_nt_html(d: dict) -> str:
    """汪汪队信号 HTML 段。"""
    parts = []
    if d["n_surge"]:
        parts.append(f'<span style="color:#e6492e;">进{d["n_surge"]}</span>')
    if d["n_outflow"]:
        parts.append(f'<span style="color:#2e8b57;">出{d["n_outflow"]}</span>')
    if d["n_volume"]:
        parts.append(f'<span style="color:#ff9800;">量{d["n_volume"]}</span>')
    summary = " ".join(parts) if parts else "无信号"
    res_tag = ' <span style="color:#b8860b;font-weight:600;">🐾共振</span>' if d.get("is_resonance") else ""
    net = d.get("net_share", 0)
    net_s = f"+{net:.2f}" if isinstance(net, (int, float)) and net >= 0 else (f"{net:.2f}" if isinstance(net, (int, float)) else "-")
    rows = ""
    for s in d.get("top_etfs", []):
        types = []
        for sg in s.get("signals", []):
            t = sg.get("type", "")
            lbl = _NT_SIG_LABEL.get(t, t)
            color = _NT_SIG_COLOR.get(t, "#1d2129")
            types.append(f'<span style="color:{color};font-weight:600;">{lbl}</span>')
        types_s = "/".join(types) if types else ""
        scy = s.get("share_change_yi")
        scy_s = f"+{scy:.2f}" if isinstance(scy, (int, float)) and scy >= 0 else (f"{scy:.2f}" if isinstance(scy, (int, float)) else "-")
        ratios = [sg.get("amount_ratio") for sg in s.get("signals", []) if sg.get("amount_ratio") is not None]
        ratio_s = f"{max(ratios):.2f}倍" if ratios else ""
        rows += (
            f'<tr><td style="padding:4px 10px;font-size:13px;"><b>{_esc(s.get("code",""))}</b> '
            f'{_esc(s.get("name",""))}</td>'
            f'<td style="padding:4px 10px;font-size:13px;">{types_s}</td>'
            f'<td style="padding:4px 10px;font-size:13px;text-align:right;">{_esc(scy_s)}亿份</td>'
            f'<td style="padding:4px 10px;font-size:13px;text-align:right;color:#86909c;">{_esc(ratio_s)}</td></tr>'
        )
    return (
        f'<h3 style="margin:16px 0 6px 0;color:#1d2129;font-size:14px;">🐶 汪汪队信号'
        f'<span style="color:#86909c;font-size:12px;font-weight:normal;">（数据日期 {_esc(d.get("data_date","-"))} T-1）</span></h3>'
        f'<div style="margin:4px 0 8px 0;font-size:13px;">{summary}{res_tag}'
        f' <span style="color:#4e5969;margin-left:12px;">净申购 {_esc(net_s)}亿份'
        f' | 增持{d.get("n_inc",0)}只 减持{d.get("n_dec",0)}只</span></div>'
        f'<table style="border-collapse:collapse;margin-bottom:4px;">{rows}</table>'
    )


# ---------------------------------------------------------------- 段3 公募基金
def _metric_by_id(metrics: list, mid: str) -> dict:
    """从 metrics 数组按 metric_id 取项。"""
    for m in metrics or []:
        if isinstance(m, dict) and m.get("metric_id") == mid:
            return m
    return {}


def load_public_fund_brief() -> dict | None:
    """读公募基金 4 个 JSON，汇总 88 魔咒 + 仓位 + 申赎 + 调仓段数据。"""
    sj = _load_json_safe(PF_SUMMARY_SRC)
    ej = _load_json_safe(PF_ESTIMATE_SRC)
    bj = _load_json_safe(PF_BACKTEST_SRC)
    tj = _load_json_safe(PF_TOP20_SRC)
    if not isinstance(sj, dict):
        return None
    metrics = sj.get("metrics") or []
    avg_pos = _metric_by_id(metrics, "avg_position").get("metric_value")
    conc = _metric_by_id(metrics, "concentration_herfindahl").get("metric_value")
    nr = _metric_by_id(metrics, "net_redeem_ratio")
    nr_val = nr.get("metric_value")
    nr_detail = nr.get("detail") or {}
    pcr = _metric_by_id(metrics, "position_change_ratio").get("metric_value")
    # 预估仓位
    est = None
    if isinstance(ej, dict):
        est = ((ej.get("current") or {}).get("position_estimate"))
        est_date = (ej.get("current") or {}).get("date")
    else:
        est_date = None
    # 88 魔咒
    zone = pct = bpos = spell88 = dip80 = None
    if isinstance(bj, dict):
        cur = bj.get("current") or {}
        zone = cur.get("zone")
        pct = cur.get("percentile")
        bpos = cur.get("position")
        stats = bj.get("stats") or {}
        spell88 = (stats.get("spell_88") or {}).get("win_rate")
        dip80 = (stats.get("dip_80") or {}).get("win_rate")
    # Top20 调仓（按 change_pct 排序，大幅加仓 + 大幅减仓各 top3）
    top20 = []
    if isinstance(tj, dict):
        raw = tj.get("top20") or []
        valid = [t for t in raw if isinstance(t, dict) and t.get("change_pct") is not None]
        sorted_gain = sorted(valid, key=lambda x: x["change_pct"], reverse=True)
        sorted_loss = sorted(valid, key=lambda x: x["change_pct"])
        top20 = {"gains": sorted_gain[:3], "losses": sorted_loss[:3]}
    return {
        "avg_position": avg_pos,
        "concentration": conc,
        "net_redeem_ratio": nr_val,
        "net_purchase_share": nr_detail.get("net_purchase_share"),
        "position_change": pcr,
        "estimate": est,
        "estimate_date": est_date,
        "zone": zone,
        "percentile": pct,
        "backtest_position": bpos,
        "spell88_win": spell88,
        "dip80_win": dip80,
        "top20": top20,
    }


def build_pf_text(d: dict) -> str:
    """公募基金纯文本段。"""
    lines = ["", "-" * 44, "公募基金："]
    # 88 魔咒
    zone = d.get("zone") or "-"
    est = d.get("estimate")
    est_s = f"{est:.2f}%" if isinstance(est, (int, float)) else "-"
    pct = d.get("percentile")
    pct_s = f"{pct*100:.1f}%" if isinstance(pct, (int, float)) else "-"
    s88 = d.get("spell88_win")
    s88_s = f"{s88*100:.1f}%" if isinstance(s88, (int, float)) else "-"
    d80 = d.get("dip80_win")
    d80_s = f"{d80*100:.1f}%" if isinstance(d80, (int, float)) else "-"
    lines.append(f"  88魔咒: 预估仓位{est_s} 处{zone}区(历史{pct_s}分位) | 88魔咒后30日胜率{s88_s} 80抄底后30日胜率{d80_s}")
    # 仓位 + 抱团度
    avg = d.get("avg_position")
    avg_s = f"{avg:.2f}%" if isinstance(avg, (int, float)) else "-"
    pcr = d.get("position_change")
    pcr_s = f"{pcr:+.2f}pp" if isinstance(pcr, (int, float)) else "-"
    conc = d.get("concentration")
    conc_s = f"{conc:.4f}" if isinstance(conc, (int, float)) else "-"
    lines.append(f"  平均仓位{avg_s} 仓位变化{pcr_s} | 抱团度{conc_s}")
    # 净申赎
    nr = d.get("net_redeem_ratio")
    nr_s = f"{nr:+.2f}%" if isinstance(nr, (int, float)) else "-"
    nps = d.get("net_purchase_share")
    nps_s = f"{abs(nps):.0f}亿" if isinstance(nps, (int, float)) else "-"
    direction = "净申购" if isinstance(nps, (int, float)) and nps > 0 else "净赎回"
    lines.append(f"  净申赎{nr_s}({direction}{nps_s})")
    # Top20 调仓
    t20 = d.get("top20") or {}
    gains = t20.get("gains") or []
    losses = t20.get("losses") or []
    if gains or losses:
        g_s = "、".join(f"{g.get('stock_name','')}{g.get('change_pct',0):+.1f}%" for g in gains)
        l_s = "、".join(f"{l.get('stock_name','')}{l.get('change_pct',0):+.1f}%" for l in losses)
        lines.append(f"  Top20调仓: 大幅加仓 {g_s} | 大幅减仓 {l_s}")
    return "\n".join(lines)


def build_pf_html(d: dict) -> str:
    """公募基金 HTML 段。"""
    zone = _esc(d.get("zone") or "-")
    est = d.get("estimate")
    est_s = f"{est:.2f}%" if isinstance(est, (int, float)) else "-"
    pct = d.get("percentile")
    pct_s = f"{pct*100:.1f}%" if isinstance(pct, (int, float)) else "-"
    s88 = d.get("spell88_win")
    s88_s = f"{s88*100:.1f}%" if isinstance(s88, (int, float)) else "-"
    d80 = d.get("dip80_win")
    d80_s = f"{d80*100:.1f}%" if isinstance(d80, (int, float)) else "-"
    avg = d.get("avg_position")
    avg_s = f"{avg:.2f}%" if isinstance(avg, (int, float)) else "-"
    pcr = d.get("position_change")
    pcr_s = f"{pcr:+.2f}pp" if isinstance(pcr, (int, float)) else "-"
    conc = d.get("concentration")
    conc_s = f"{conc:.4f}" if isinstance(conc, (int, float)) else "-"
    nr = d.get("net_redeem_ratio")
    nr_s = f"{nr:+.2f}%" if isinstance(nr, (int, float)) else "-"
    nps = d.get("net_purchase_share")
    nps_s = f"{abs(nps):.0f}亿" if isinstance(nps, (int, float)) else "-"
    direction = "净申购" if isinstance(nps, (int, float)) and nps > 0 else "净赎回"
    nr_color = "#e6492e" if (isinstance(nps, (int, float)) and nps > 0) else "#2e8b57"
    t20 = d.get("top20") or {}
    gains = t20.get("gains") or []
    losses = t20.get("losses") or []
    t20_html = ""
    if gains or losses:
        g_items = "、".join(
            f'{_esc(g.get("stock_name",""))}<span style="color:#e6492e;">{g.get("change_pct",0):+.1f}%</span>'
            for g in gains
        )
        l_items = "、".join(
            f'{_esc(l.get("stock_name",""))}<span style="color:#2e8b57;">{l.get("change_pct",0):+.1f}%</span>'
            for l in losses
        )
        t20_html = (
            f'<div style="margin:8px 0;font-size:12px;line-height:1.8;">'
            f'<span style="color:#86909c;">Top20调仓：</span>'
            f'<span style="color:#4e5969;">大幅加仓</span> {g_items}'
            f' <span style="color:#4e5969;margin-left:8px;">大幅减仓</span> {l_items}</div>'
        )
    return (
        f'<h3 style="margin:16px 0 6px 0;color:#1d2129;font-size:14px;">💰 公募基金</h3>'
        f'<div style="margin:4px 0;font-size:13px;line-height:1.8;">'
        f'<b style="color:#d4380d;">88魔咒</b>: 预估仓位<b>{_esc(est_s)}</b> 处{zone}区'
        f'(历史{pct_s}分位) | 88魔咒后30日胜率{_esc(s88_s)} 80抄底后30日胜率{_esc(d80_s)}<br>'
        f'平均仓位<b>{_esc(avg_s)}</b> 仓位变化{_esc(pcr_s)} | 抱团度{_esc(conc_s)} | '
        f'净申赎<span style="color:{nr_color};">{_esc(nr_s)}</span>'
        f'({_esc(direction)}{_esc(nps_s)})</div>'
        f'{t20_html}'
    )


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
    msg["From"] = formataddr((f"[收盘速递] {SITE_NAME}", user))
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
    # 加载订阅列表（文件缺失/解析失败返回空列表，不阻塞）
    subs = load_subscriptions()
    # 加载方案B 融合段（期货风向 / 汪汪队 / 公募基金），各段独立缺失不阻塞
    extras = {
        "futures": load_futures_brief(),
        "nt": load_nt_brief(),
        "pf": load_public_fund_brief(),
    }
    text_body = build_text(it, subs, extras)
    html_body = build_html(it, subs, extras)

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
