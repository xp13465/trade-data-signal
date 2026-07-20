#!/usr/bin/env python3
"""生成 RSS feed.xml（RSS 2.0），放 static-site/data/feed.xml。

每日收盘情绪速递：读 static-site/data/summary_history.json（多日历史），
取最近 30 条生成 RSS item。供 RSS 阅读器订阅当日恐贪指数 / 涨跌家数 /
量能 / 板块轮动 / 买卖点信号摘要。

由 deploy.sh 调用（每次部署刷新），也可手动 `python scripts/gen_rss.py`。
容错：summary_history.json 缺失/非法时生成只含 channel 的空 feed，不抛错。
"""
import json
import os
from datetime import datetime

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO, "static-site", "data", "summary_history.json")
DST = os.path.join(REPO, "static-site", "data", "feed.xml")
SITE = "https://s.sugas.site/"

# 英文星期/月份缩写（RFC 822 要求英文，避免依赖系统 locale）
WDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _esc(s):
    """XML 文本转义（用于 title/guid 等非 CDATA 区）。"""
    if s is None:
        return ""
    return (str(s).replace("&", "&amp;")
                  .replace("<", "&lt;")
                  .replace(">", "&gt;"))


def _iso_date(date_str):
    """'20260717' -> '2026-07-17'（非法原样返回）。"""
    try:
        return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
    except Exception:
        return str(date_str)


def _rfc822(date_str):
    """'20260717' -> 'Tue, 15 Jul 2026 15:00:00 +0800'（该日 15:00 收盘 +0800）。"""
    try:
        d = datetime(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:8]), 15, 0, 0)
    except Exception:
        return ""
    return f"{WDAYS[d.weekday()]}, {d.day:02d} {MONTHS[d.month - 1]} {d.year} 15:00:00 +0800"


def _ind_names(arr, n=3):
    """板块数组 -> '名称(+x.x%)、名称(-x.x%)'，无数据返回空串。"""
    out = []
    for it in (arr or [])[:n]:
        name = it.get("name", "?")
        pct = it.get("pct_change")
        if pct is None:
            out.append(name)
        else:
            sign = "+" if pct >= 0 else ""
            out.append(f"{name}({sign}{pct:.1f}%)")
    return "、".join(out)


def _desc(it):
    """生成 description 纯文本摘要（涨跌/量能/买卖点/板块/冰点）。"""
    parts = []
    up, down = it.get("up_count"), it.get("down_count")
    if up is not None and down is not None:
        parts.append(f"涨跌家数:{up}涨/{down}跌")
    zt, dt = it.get("zt_count"), it.get("dt_count")
    if zt is not None and dt is not None:
        parts.append(f"涨停{zt}/跌停{dt}")
    vol, vol_label = it.get("volume_amount"), it.get("volume_label")
    if vol is not None:
        parts.append(f"成交额{vol:.0f}亿({vol_label or '量能未知'})")
    buy, sell = it.get("buy_count"), it.get("sell_count")
    if buy is not None and sell is not None:
        parts.append(f"买点{buy}/卖点{sell}")
    sh_pct, sh_close = it.get("sh_pct"), it.get("sh_close")
    if sh_pct is not None:
        sign = "+" if sh_pct >= 0 else ""
        close_str = f"收{sh_close:.0f}" if sh_close is not None else ""
        parts.append(f"上证{sign}{sh_pct:.2f}%{close_str}")
    top = _ind_names(it.get("top_industries"))
    if top:
        parts.append(f"领涨:{top}")
    bot = _ind_names(it.get("bottom_industries"))
    if bot:
        parts.append(f"领跌:{bot}")
    if it.get("is_freeze") and it.get("freeze_info"):
        parts.append(it["freeze_info"])
    return " | ".join(parts)


def _title(it):
    """'YYYY-MM-DD 收盘 | 恐贪指数 XX.X | 情绪标签'。"""
    date_str = it.get("date", "")
    fg = it.get("fear_greed_value")
    label = it.get("sentiment_label") or it.get("fear_greed_label") or "情绪未知"
    fg_str = f"{fg:.1f}" if isinstance(fg, (int, float)) else "NA"
    return f"{_iso_date(date_str)} 收盘 | 恐贪指数 {fg_str} | {label}"


def main():
    # 读多日历史（容错：缺失/非法 -> 空 items）
    items = []
    try:
        with open(SRC, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            items = data.get("items", [])
        elif isinstance(data, list):
            items = data
    except (FileNotFoundError, ValueError):
        items = []

    # 按日期倒序，最新在前（本身应已倒序，防御性再排），取最近 30 条
    items = sorted(items, key=lambda x: str(x.get("date", "")), reverse=True)[:30]

    now = datetime.now()
    last_build = (f"{WDAYS[now.weekday()]}, {now.day:02d} {MONTHS[now.month - 1]} "
                  f"{now.year} {now.hour:02d}:{now.minute:02d}:{now.second:02d} +0800")

    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<rss version="2.0">',
           "  <channel>",
           "    <title>A股情绪看板每日收盘</title>",
           f"    <link>{SITE}</link>",
           "    <description>A股市场情绪、恐贪指数、涨跌家数、量能与板块轮动每日收盘速递</description>",
           "    <language>zh-CN</language>",
           f"    <lastBuildDate>{last_build}</lastBuildDate>"]

    for it in items:
        date_str = it.get("date", "")
        iso = _iso_date(date_str)
        desc = _desc(it).replace("]]>", "]]]]><![CDATA[>")  # CDATA 内防御
        guid = f"{SITE}?date={iso}" if iso else SITE
        out.append("    <item>")
        out.append(f"      <title>{_esc(_title(it))}</title>")
        out.append(f"      <link>{SITE}</link>")
        out.append(f"      <description><![CDATA[{desc}]]></description>")
        out.append(f"      <pubDate>{_rfc822(date_str)}</pubDate>")
        out.append(f"      <guid>{_esc(guid)}</guid>")
        out.append("    </item>")

    out.append("  </channel>")
    out.append("</rss>")
    out.append("")

    with open(DST, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print(f"✓ {DST} 生成（{len(items)} items）")


if __name__ == "__main__":
    main()
