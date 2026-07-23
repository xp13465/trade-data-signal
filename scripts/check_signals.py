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
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

import yaml

# 不 .resolve()：trade-data/scripts 是 symlink 指向 trade/scripts，resolve 会把
# REPO 钉死到 trade/，导致 launchd 跑时读 trade/data/sentiment.db（滞后）而非
# trade-data/data/sentiment.db（最新，update_all/intraday 写入处）。保留 symlink
# 路径让 trade-data 版读 trade-data/data/，与 app/db.py 的 .absolute() 同口径。
# trade-data/app 是 symlink 指向 trade/app，sys.path 仍可正常 import app 模块。
REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))  # 供 import notify（多渠道通知统一出口）
import notify  # noqa: E402
from app.db import get_conn  # noqa: E402

DB_PATH = REPO / "data" / "sentiment.db"
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

# === fade-detect 盘中信号收盘消失警示（2026-07-23 P1-新-A）===
# buy 系列强度排序（强->弱），用于"降级"判定；sell 系列消失不警示（对已卖出用户利好）
BUY_STRENGTH = {
    "buy": 4,
    "buy_special": 3,
    "buy_aux": 2,
    "buy_backup": 1,
}
SELL_TYPES = {"sell", "sell_stop_loss"}

# fade 警示档位 -> (emoji, 中文标签, 主色)
FADE_LEVEL_INFO = {
    "red":    ("🔴", "严格消失", "#cf1322"),
    "orange": ("🟠", "类型变化", "#d4380d"),
    "yellow": ("🟡", "降级保留", "#d48806"),
}


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


def detect_fade(
    notified_entries: list[list[str]],
    closing_signals: list[tuple[str, str]] | list[dict],
) -> list[dict]:
    """检测盘中推送信号收盘是否消失/变化（fade-detect，2026-07-23 P1-新-A）。

    只对 buy 系列警示（buy/buy_aux/buy_special/buy_backup）；
    sell 系列消失不警示（对已卖出用户利好）。

    三档判定：
      - 严格消失（红 red）：盘中推 (X, buy*) 收盘 signal_daily 无 X 任何信号
      - 类型变化（橙 orange）：盘中推 (X, buy*) 收盘有 (X, sell*)
      - 降级保留（黄 yellow）：盘中推 (X, buy*) 收盘有更弱的 buy*
      - 升级/保持：不警示（X 有同级或更强 buy*）

    Args:
      notified_entries: signal_notified.json[date] 的 [[index_id, signal], ...]
      closing_signals: 收盘 signal_daily[date]，list[(index_id, signal)] 或 list[dict]
        （dict 时取 index_id/signal 字段）

    Returns:
      fade_alerts list[dict]，每项含
        index_id / intraday_signal / closing_signals(list) /
        closing_status(str 中文) / level(red/orange/yellow) / suggestion(str)
    """
    # 收盘信号按 index_id 聚合为 set
    closing_by_idx: dict[str, set[str]] = {}
    for item in closing_signals:
        if isinstance(item, dict):
            idx, sig = item.get("index_id"), item.get("signal")
        else:
            idx, sig = item[0], item[1]
        if not idx or not sig:
            continue
        closing_by_idx.setdefault(idx, set()).add(sig)

    fade_alerts: list[dict] = []
    for entry in notified_entries:
        if not entry or len(entry) < 2:
            continue
        idx, intraday_sig = entry[0], entry[1]
        # sell 系列不警示
        if intraday_sig not in BUY_STRENGTH:
            continue
        closing_sigs = closing_by_idx.get(idx, set())
        closing_buy_sigs = {s for s in closing_sigs if s in BUY_STRENGTH}
        closing_sell_sigs = {s for s in closing_sigs if s in SELL_TYPES}

        if not closing_sigs:
            level = "red"
            closing_status = "无任何信号"
            suggestion = "信号消失，建议人工复核行情"
        elif closing_sell_sigs:
            level = "orange"
            sell_labels = "、".join(_signal_label(s) for s in sorted(closing_sell_sigs))
            closing_status = f"出现卖出信号（{sell_labels}）"
            suggestion = "由买转卖，建议谨慎评估"
        elif closing_buy_sigs:
            intraday_strength = BUY_STRENGTH[intraday_sig]
            max_closing_strength = max(BUY_STRENGTH[s] for s in closing_buy_sigs)
            if max_closing_strength < intraday_strength:
                level = "yellow"
                buy_labels = "、".join(_signal_label(s) for s in sorted(closing_buy_sigs))
                closing_status = f"降级为 {buy_labels}"
                suggestion = "信号强度减弱，关注后续走势"
            else:
                # 同级或升级，不警示
                continue
        else:
            # 收盘有信号但既非 buy 也非 sell（理论不会到这里，保留兜底）
            continue

        fade_alerts.append({
            "index_id": idx,
            "intraday_signal": intraday_sig,
            "closing_signals": sorted(closing_sigs),
            "closing_status": closing_status,
            "level": level,
            "suggestion": suggestion,
        })
    return fade_alerts


def run_fade_detect(date: str, closing_signals: list[dict]) -> list[dict]:
    """加载盘中 signal_notified.json[date]，对比收盘信号，返回 fade_alerts。

    供 main 收盘模式调用。盘中无推送记录时返回空 list（不警示）。
    """
    notified = load_signal_notified()
    notified_entries = notified.get(date, [])
    if not notified_entries:
        log.info("fade-detect：%s 无盘中推送记录（signal_notified.json），跳过", date)
        return []
    closing_pairs = [(s["index_id"], s["signal"]) for s in closing_signals]
    fade_alerts = detect_fade(notified_entries, closing_pairs)
    if fade_alerts:
        log.warning("fade-detect：盘中推送 %d 条，检测到 %d 条收盘消失/变化",
                    len(notified_entries), len(fade_alerts))
        for a in fade_alerts:
            emoji, level_label, _ = FADE_LEVEL_INFO.get(a["level"], ("⚪", a["level"], ""))
            log.warning("  %s [%s] %s 盘中=%s -> 收盘=%s",
                        emoji, level_label, a["index_id"],
                        a["intraday_signal"], a["closing_status"])
    else:
        log.info("fade-detect：盘中推送 %d 条，收盘全部保留/升级，无消失",
                 len(notified_entries))
    return fade_alerts


def _build_fade_banner(fade_alerts: list[dict], name_map: dict[str, str]) -> str:
    """构建 fade 警示横幅 HTML（红/橙/黄三档表格）。"""
    rows_html = []
    for a in fade_alerts:
        emoji, level_label, _ = FADE_LEVEL_INFO.get(
            a["level"], ("⚪", a["level"], "#86909c"))
        name = index_id_to_name(a["index_id"], name_map)
        intraday_label = _signal_label(a["intraday_signal"])
        rows_html.append(
            f'<tr style="border-bottom:1px solid #ffe7e6;">'
            f'<td style="padding:8px 10px;">{emoji} <b>{name}</b></td>'
            f'<td style="padding:8px 10px;font-size:12px;">{intraday_label}</td>'
            f'<td style="padding:8px 10px;font-size:12px;color:#4e5969;">{a["closing_status"]}</td>'
            f'<td style="padding:8px 10px;font-size:12px;color:#4e5969;">{a["suggestion"]}</td>'
            f'</tr>'
        )
    rows = "\n".join(rows_html)
    n = len(fade_alerts)
    return (
        '<div style="background:#fff1f0;border:2px solid #ffa39e;border-radius:6px;'
        'padding:12px 16px;margin:0 0 14px 0;">'
        f'<div style="font-weight:700;color:#cf1322;font-size:15px;margin-bottom:6px;">'
        f'⚠️ 盘中信号收盘消失警示（{n} 条）</div>'
        '<p style="margin:0 0 10px 0;color:#a8071a;font-size:13px;line-height:1.6;">'
        '以下信号盘中已推送，但收盘后状态变化或消失，请重点关注：</p>'
        '<table style="width:100%;border-collapse:collapse;font-size:13px;background:#fff;">'
        '<thead><tr style="background:#ffe7e6;text-align:left;">'
        '<th style="padding:8px 10px;border-bottom:2px solid #ffa39e;">品种</th>'
        '<th style="padding:8px 10px;border-bottom:2px solid #ffa39e;">盘中信号</th>'
        '<th style="padding:8px 10px;border-bottom:2px solid #ffa39e;">收盘状态</th>'
        '<th style="padding:8px 10px;border-bottom:2px solid #ffa39e;">建议操作</th>'
        '</tr></thead><tbody>'
        f'{rows}'
        '</tbody></table></div>'
    )


def build_email(date: str, signals: list[dict], name_map: dict[str, str],
                intraday: bool = False,
                fade_alerts: list[dict] | None = None) -> tuple[str, str]:
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
    # fade-detect 警示存在时主题加 ⚠️ 前缀（2026-07-23 P1-新-A）
    fade_prefix = "⚠️ " if fade_alerts else ""
    subject = f"{fade_prefix}[{title_prefix}买卖点信号] {date}  {' | '.join(parts) if parts else '无信号'}"

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

    # fade-detect 警示横幅（红/橙/黄三档表格），放正文顶部 intraday 横幅之后（2026-07-23 P1-新-A）
    if fade_alerts:
        html_parts.append(_build_fade_banner(fade_alerts, name_map))

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
    parser.add_argument(
        "--fade-detect",
        action="store_true",
        default=None,
        dest="fade_detect",
        help="收盘模式检测盘中信号收盘消失/变化（默认：收盘模式开/intraday 模式关）。"
        "对比 signal_notified.json[date]（盘中已推送）vs 收盘 signal_daily[date]，"
        "buy* 系列消失/转 sell*/降级则邮件 ⚠️ 高亮警示。",
    )
    parser.add_argument(
        "--no-fade-detect",
        action="store_false",
        dest="fade_detect",
        help="显式关闭 fade-detect（即使收盘模式也不检测消失）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="dry-run：跑逻辑（含 fade-detect）但不发邮件、不写 signal_notified.json（测试用）",
    )
    args = parser.parse_args(argv)
    # fade-detect 默认值：收盘模式（非 intraday）默认开，intraday 模式默认关
    if args.fade_detect is None:
        args.fade_detect = not args.intraday

    date = args.date or datetime.now().strftime("%Y%m%d")
    log.info(
        "=== check_signals 开始，查询日期：%s（%s模式%s%s）===",
        date,
        "全量" if args.full else "去重",
        "·盘中实时" if args.intraday else "",
        f"·fade-detect={'on' if args.fade_detect else 'off'}",
    )

    signals = query_signals(date)
    # fade-detect：对比盘中 signal_notified.json[date] vs 收盘 signals，检测消失/变化
    fade_alerts: list[dict] = []
    if args.fade_detect:
        fade_alerts = run_fade_detect(date, signals)

    if not signals and not fade_alerts:
        log.info("今日（%s）无买卖点信号且无 fade 警示，不发邮件", date)
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
            if fade_alerts:
                log.info("无新信号（已去重），但有 %d 条 fade 警示，仍发 fade 警示邮件",
                         len(fade_alerts))
            else:
                log.info("无新信号（已去重），不发邮件")
                return 0
    subject, body = build_email(date, signals_to_send, name_map,
                                intraday=args.intraday, fade_alerts=fade_alerts)
    # 始终打印邮件内容（便于日志/调试/未配置场景查看）
    log.info("===== 邮件主题 =====")
    log.info("%s", subject)
    log.info("===== 邮件正文 =====")
    log.info("%s", body)

    if args.dry_run:
        log.info("dry-run：跳过实际发送 + 不更新 signal_notified.json")
        return 0

    # 多渠道分发（邮件 + Telegram）：notify.send 统一出口，各渠道失败不互相阻塞。
    # 任一渠道成功即视为通知已发出 -> 继续更新 signal_notified.json（标记已通知）。
    # 全部渠道未发出（未配置/失败）-> 不更新去重记录，下次重试。
    try:
        results = notify.send(subject, body)
    except Exception as e:  # noqa: BLE001
        log.error("✗ 通知发送异常：%s（不阻塞流程）", e)
        return 2
    ok_channels = [ch for ch, v in results.items() if v]
    fail_channels = [ch for ch, v in results.items() if not v]
    if ok_channels:
        log.info("✓ 通知已发送：%s%s", " ".join(ok_channels),
                 f"（未发出：{' '.join(fail_channels)}）" if fail_channels else "")
    else:
        log.warning("✗ 通知未发出（渠道均未配置或失败）-- 不更新去重记录，下次重试")
        return 0

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
