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

2026-08-14 告警邮件优化：
  A5 盘中模式 n_total==0 且仅 fade/timeline 时不发邮件（盘中信号反复消失属常态，避免噪音；
     保留收盘版正常发信）。
  B1 邮件主题与正文统一为"去重新信号"口径（subject_signals 恒 None），正文统计行加
     "(当日去重后新信号 N 条)"标注（--full 全量模式不加）。
  B3 去重新信号全为中性"波段持有"时，主题改"仅波段持有(中性持有,无操作信号)"，只反映实质。
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
# pending-#56(2026-08-18) 通知去重状态权威化: signal_notified/subscriptions_notified/fade_notified
# 是**跨进程共享的去重状态**, 必须读写权威份(trade-data/data), 防 "cd trade 跑 python 读
# trade/data 旧镜像(信号未记录)导致已通知信号重发"(pending-#56)。launchd 正常路径
# REPO=trade-data 天然一致; 手动从生产 trade 仓库跑时把去重状态重定向到其兄弟 trade-data
# 权威目录; 其余路径(worktree 隔离开发等)保留各自 data/(隔离, 非生产, 不影响线上去重)。
# 与 app/db.py .absolute() 读权威主库同口径。非权威时启动打告警(见 log 定义后)。
_AUTHORITY_REPO = REPO
if str(REPO).endswith("trade-data"):
    pass  # 已是最新权威仓库(trade-data)
elif Path(str(REPO)).name == "trade":
    _AUTHORITY_REPO = Path(str(REPO)).parent / "trade-data"
_AUTHORITY_DATA = _AUTHORITY_REPO / "data"
# #61(2026-08-17) 邮件/飞书信号带「回测宇宙+AI过滤+AI警示+AI建议」标记:
# 数据源=overview.json 的 signals_today(queries.py 从回测侧注入 _bt_in_universe/ai_macro,
# §23.6 ③ 禁止自行重算宇宙, 必须读回测侧注入标记)。launchd 跑时 REPO=trade-data 读权威份,
# 手动 trade/ 跑时读 trade 份; 标记字段(index_id 级 _bt_in_universe + 信号级 ai_macro)在
# overview 近 15 日 signals_today 内稳定, 盘中(overview 未到当天)按 (index_id, signal) 降级取
# 最近历史信号标记(收盘 17:50 后 overview 含当天, 用当天权威标记)。
OVERVIEW_PATH = REPO / "static-site" / "data" / "overview.json"
# F 方案（2026-07-21）：邮件去重持久化，记录当日已通知的 (index_id, signal) 集合。
# 格式 {date_str: [[index_id, signal], ...]}，7 天自动清理旧记录（save_signal_notified）。
# 仅在去重模式（默认）下读写；--full 全量模式不读只写（发后全标记已通知）。
# 去重状态走权威份(_AUTHORITY_DATA, 见上), 防误读 trade/data 旧镜像重发(pending-#56)。
NOTIFIED_PATH = _AUTHORITY_DATA / "signal_notified.json"

# A12 订阅推送（2026-07-24）：用户订阅关注的标的，有信号时推送邮件+Telegram。
# 订阅配置 config/subscriptions.json（含邮箱/chat_id，已 gitignore，模板见 subscriptions.json.example）。
# 订阅去重 data/subscriptions_notified.json，格式 {date_str: {sub_id: [[index_id, signal], ...]}}，
# 每订阅每日每信号只推一次（独立于全局 signal_notified.json，互不影响），7 天自动清理。
SUBSCRIPTIONS_PATH = REPO / "config" / "subscriptions.json"
SUBS_NOTIFIED_PATH = _AUTHORITY_DATA / "subscriptions_notified.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("check_signals")
# pending-#56 权威重定向告警(见 _AUTHORITY_REPO 定义注释): 非权威仓库运行仅影响去重状态
# 读取(已重定向到 trade-data/data 权威份), 不影响 DB/config/overview 的 REPO 相对读取(设计如此)。
if _AUTHORITY_REPO != REPO:
    log.warning(
        "check_signals 从非权威仓库(%s)运行, 通知去重状态已重定向到权威份 %s（防误读 "
        "trade/data 旧镜像导致已通知信号重发, pending-#56）",
        REPO,
        _AUTHORITY_DATA,
    )

# score_daily 中的综合分 score_id → 中文名（不入 indicators.yaml，硬编码）
SCORE_NAME_MAP = {
    "cross_market": "跨市场综合评分",
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
• 主买：RSI 上穿 30（超卖反弹启动）。
• 辅买：布林下轨回归（超卖反弹，强势市更敏感，互补主买盲区）。
• 追买：唐奇安20日上轨突破 + B4_hold5d 过滤（收盘价突破前20日最高价且延后5日站稳确认，激进战法高回撤高收益，趋势跟踪类）。
• 备买：Supertrend ATR(10)×3 翻多 + 二次确认过滤（延后3日收盘价确认仍站稳，趋势转向，与主买/辅买均值回归类互补，趋势跟踪类）。
• 卖：20 日高点回落 5% + MA60 多头过滤 + MACD 死叉确认（止盈减仓提示）。
• 追止损卖：A1 Donchian20 下轨止损（收盘价跌破前20日最低价，与追买上轨突破对称，独立止损卖点）。
• 波段持有：当前处于波段持有状态（无超买超卖触发，非买卖操作，中性持有信号，供参考持仓状态）。
  附 RSI 当前值、综合情绪分金叉/死叉状态、相对前一买点盈亏标注。</div>"""

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
    "band_hold": "波段持有",
}
# 含 band_hold（波段持有）：用户定方案B"补充完整展示"（2026-07-28），
# 邮件表格展示所有信号状态（含当前持有），不再过滤 band_hold。
SIGNAL_ORDER = ["buy", "buy_aux", "buy_special", "buy_backup", "sell", "sell_stop_loss", "band_hold"]

# 飞书 post 版（报告群）触发条件摘要截断长度（超长省略，防冗长；完整条件在邮件）
FEISHU_POST_REASON_MAX = 32
# 飞书 post 版买入/卖出/持有分组（买红/卖绿/持有灰，A股红涨绿跌约定，与邮件/平台信号灯一致）
FEISHU_POST_BUY_TYPES = ["buy", "buy_aux", "buy_special", "buy_backup"]
FEISHU_POST_SELL_TYPES = ["sell", "sell_stop_loss"]

# === fade-detect 盘中信号收盘消失警示（2026-07-23 P1-新-A）===
# buy 系列强度排序（强->弱），用于"降级"判定。
BUY_STRENGTH = {
    "buy": 4,
    "buy_special": 3,
    "buy_aux": 2,
    "buy_backup": 1,
}
SELL_TYPES = {"sell", "sell_stop_loss"}
# sell 系列强度排序（强->弱）：追止损卖 > 卖。2026-08-10 加：sell 信号消失也检测+通知
# （用户反馈：14:56 收到波段减仓邮件，15:02 收盘重算后信号消失但无通知，希望提前知晓）。
# sell 消失语义特殊（价格回落不再超买=利好方向），文案设计为"减仓条件解除"，非简单"信号消失"。
SELL_STRENGTH = {
    "sell_stop_loss": 2,
    "sell": 1,
}

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


# AZ54 P1-4 盘中 fade-detect 去重（2026-07-29）：同日同 index_id|level 只推一次。
# 格式 {date_str: {"index_id|level|kind": iso_timestamp}}，仅当日保留（清理旧日期）。
# 仅 intraday 模式使用（10min 一轮频繁，需去重防轰炸）；收盘模式跑一次无需去重。
# 2026-08-10：key 加 kind(buy/sell)，防同日同 index 的 buy fade 与 sell fade 撞 key 漏推。
FADE_NOTIFIED_PATH = _AUTHORITY_DATA / "fade_notified.json"


def filter_fade_alerts_intraday(alerts: list[dict], date: str) -> list[dict]:
    """盘中 fade-detect 去重：同日同 index_id|level 只保留首次出现。

    记录到 data/fade_notified.json（不进 git）。写入失败降级为全发（不阻塞）。
    参考 detect_intraday_anomaly.py 的 anomaly_notified.json 模式。
    """
    dedup: dict = {}
    if FADE_NOTIFIED_PATH.exists():
        try:
            dedup = json.loads(FADE_NOTIFIED_PATH.read_text(encoding="utf-8"))
            if not isinstance(dedup, dict):
                dedup = {}
        except Exception as e:  # noqa: BLE001
            log.warning("fade_notified.json 加载失败：%s（去重降级为全发）", e)
            dedup = {}
    today_set = dedup.get(date, {})
    now = datetime.now().isoformat()
    new_alerts: list[dict] = []
    for a in alerts:
        key = f"{a['index_id']}|{a['level']}|{a.get('kind', 'buy')}"
        if key in today_set:
            continue
        today_set[key] = now
        new_alerts.append(a)
    # 只保留今日（清理旧日期避免文件膨胀）
    dedup = {date: today_set}
    try:
        FADE_NOTIFIED_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = FADE_NOTIFIED_PATH.parent / (FADE_NOTIFIED_PATH.name + ".tmp")
        tmp.write_text(json.dumps(dedup, ensure_ascii=False, separators=(",", ":")),
                       encoding="utf-8")
        tmp.replace(FADE_NOTIFIED_PATH)
    except Exception as e:  # noqa: BLE001
        log.warning("fade_notified.json 写入失败：%s（去重降级为全发）", e)
    return new_alerts


# ============ A12 订阅推送（2026-07-24 P2-新-K）============
def _sync_subscriptions_from_cf() -> None:
    """C 方案（2026-07-24）：跑前从 CF Workers 拉订阅回流本地 config/subscriptions.json。

    best-effort 同步：失败不阻塞（网络错/密码错/未配置），用旧 config/subscriptions.json 兜底。
    调 scripts/sync_subscriptions_from_cf.py，stdout/stderr 仅 log 不抛。
    """
    sync_script = REPO / "scripts" / "sync_subscriptions_from_cf.py"
    if not sync_script.exists():
        return
    try:
        import subprocess
        result = subprocess.run(
            [sys.executable, str(sync_script)],
            capture_output=True, text=True, timeout=30,
        )
        if result.stdout:
            log.info("[sync_subscriptions] %s", result.stdout.strip())
        if result.returncode != 0 and result.stderr:
            log.warning("[sync_subscriptions] %s", result.stderr.strip())
    except Exception as e:  # noqa: BLE001
        log.warning("[sync_subscriptions] 同步异常：%s（用旧 config/subscriptions.json）", e)


def load_subscriptions() -> list[dict]:
    """读 config/subscriptions.json，返回有效订阅列表。

    过滤：enabled=True 且有 email 或 telegram_chat_id 且 targets 非空。
    文件不存在/解析失败返回空 list（静默跳过，不影响全局推送）。
    """
    # C 方案：读本地文件前先 best-effort 从 CF Workers 同步（失败用旧文件兜底）
    _sync_subscriptions_from_cf()
    if not SUBSCRIPTIONS_PATH.exists():
        return []
    try:
        data = json.loads(SUBSCRIPTIONS_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            log.warning("subscriptions.json 格式异常（非 dict），忽略订阅推送")
            return []
        subs = data.get("subscriptions", [])
        if not isinstance(subs, list):
            return []
        return [
            s for s in subs
            if isinstance(s, dict)
            and s.get("enabled", True)
            and (s.get("email") or s.get("telegram_chat_id"))
            and s.get("targets")
            and s.get("id")
        ]
    except Exception as e:  # noqa: BLE001
        log.warning("subscriptions.json 加载失败：%s（订阅推送降级为跳过）", e)
        return []


def filter_signals_for_subscription(sub: dict, signals: list[dict]) -> list[dict]:
    """过滤出订阅者关心的信号（targets 命中 + signals 类型命中）。

    targets: 订阅的 index_id 列表（精确匹配 signal_daily.index_id，含 g./s. 前缀）。
    signals: 订阅的信号类型列表（空/None=全部；可选 buy/buy_aux/buy_special/buy_backup/sell/sell_stop_loss）。
    """
    targets = set(sub.get("targets", []) or [])
    sig_types = sub.get("signals", []) or []
    sig_set = set(sig_types) if sig_types else None
    out = []
    for s in signals:
        if s["index_id"] not in targets:
            continue
        if sig_set is not None and s["signal"] not in sig_set:
            continue
        out.append(s)
    return out


def load_subs_notified() -> dict[str, dict[str, list[list[str]]]]:
    """读 data/subscriptions_notified.json（订阅推送去重持久化）。

    格式 {date_str: {sub_id: [[index_id, signal], ...]}}。不存在/解析失败返回 {}。
    文件已 gitignore（§8 禁推），仅本地持久化跨进程去重。
    """
    if not SUBS_NOTIFIED_PATH.exists():
        return {}
    try:
        data = json.loads(SUBS_NOTIFIED_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            log.warning("subscriptions_notified.json 格式异常（非 dict），忽略")
            return {}
        return data
    except Exception as e:  # noqa: BLE001
        log.warning("subscriptions_notified.json 加载失败：%s（订阅去重降级为全发）", e)
        return {}


def save_subs_notified(data: dict[str, dict[str, list[list[str]]]]) -> None:
    """写 data/subscriptions_notified.json（原子写）。清理 7 天前旧记录避免无限增长。"""
    cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y%m%d")
    cleaned = {d: v for d, v in data.items() if d >= cutoff}
    SUBS_NOTIFIED_PATH.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(cleaned, ensure_ascii=False, separators=(",", ":"))
    tmp = SUBS_NOTIFIED_PATH.parent / (SUBS_NOTIFIED_PATH.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(SUBS_NOTIFIED_PATH)


def push_subscriptions(all_signals: list[dict], name_map: dict[str, str],
                       date: str, intraday: bool = False,
                       dry_run: bool = False,
                       overview_markers: dict | None = None) -> None:
    """A12 订阅推送：对每个订阅，过滤匹配信号（从 all_signals），独立去重后推送。

    与全局推送独立：用 all_signals（不去重），每订阅用 subs_notified.json 独立去重，
    互不影响（全局推过的信号订阅者仍会收到，反之亦然）。

    推送渠道：notify.send_to(subject, body, email, chat_id)
      - SMTP user/password、bot_token/api_base 用 config 全局配置（单一发件方）
      - email/chat_id 用订阅者配置（多收件人）

    推送内容：复用 build_email 构建邮件（按订阅者关心的信号过滤后），主题加 [订阅:name] 前缀。
    失败不阻塞（单订阅失败不影响其他订阅 + 不影响全局流程）。
    overview_markers（#61 2026-08-17）：信号「回测宇宙+AI过滤」标记, 由 main 从 overview.json 读入;
      AI 建议 top-K 在本函数内对每个订阅的 new_signals 单独算(见下方 _ai_sg)。
    """
    subs = load_subscriptions()
    if not subs:
        return
    log.info("=== A12 订阅推送：%d 个有效订阅 ===", len(subs))
    notified = load_subs_notified()
    today_notified = notified.get(date, {})
    pushed_count = 0
    for sub in subs:
        sub_id = sub.get("id", "")
        sub_name = sub.get("name") or sub_id
        sub_signals = filter_signals_for_subscription(sub, all_signals)
        if not sub_signals:
            continue
        # 去重：该订阅今日已推过的 (index_id, signal)
        already = {tuple(x) for x in today_notified.get(sub_id, [])}
        new_signals = [s for s in sub_signals if (s["index_id"], s["signal"]) not in already]
        if not new_signals:
            log.info("订阅 %s(%s)：当日匹配 %d 信号均已推送，跳过", sub_name, sub_id, len(sub_signals))
            continue
        # #61: 对该订阅实际推送的 new_signals 单独算 AI 建议 top-K(展示范围内谁最优, 与订阅邮件对应)
        _ai_sg = build_ai_suggest_map(new_signals, overview_markers or {}, load_signal_stats())
        # 构建专属邮件（复用 build_email，只含该订阅关心的信号；#61 带 AI 标记）
        subject, body = build_email(date, new_signals, name_map, intraday=intraday,
                                    overview_markers=overview_markers,
                                    ai_suggest=_ai_sg)
        subject = f"[订阅:{sub_name}] {subject}"
        # 飞书 post 富文本（订阅推送也走 report 群，3 群差异化同全局推送；#61 带 AI 标记）
        feishu_post = build_feishu_post(subject, new_signals, name_map, intraday=intraday,
                                        overview_markers=overview_markers,
                                        ai_suggest=_ai_sg)
        email = (sub.get("email") or "").strip() or None
        chat_id = (sub.get("telegram_chat_id") or "").strip() or None
        try:
            results = notify.send_to(subject, body, email=email, chat_id=chat_id, dry_run=dry_run,
                                     from_prefix="[买卖点信号]", feishu_post=feishu_post)
        except Exception as e:  # noqa: BLE001
            log.error("订阅 %s(%s) 推送异常：%s（不阻塞其他订阅）", sub_name, sub_id, e)
            continue
        ok_channels = [ch for ch, v in results.items() if v]
        if ok_channels:
            # 标记已推（任一渠道成功即标记，避免重复推）
            today_notified.setdefault(sub_id, [])
            for s in new_signals:
                today_notified[sub_id].append([s["index_id"], s["signal"]])
            pushed_count += 1
            log.info("✓ 订阅 %s(%s) 推送：%s（%d 信号）",
                     sub_name, sub_id, "/".join(ok_channels), len(new_signals))
        else:
            log.warning("✗ 订阅 %s(%s) 推送失败（渠道均未配置/失败）-- 不标记已推，下次重试",
                        sub_name, sub_id)
    # 写回去重记录（仅当日有变更才写；dry_run 模式不写，测试用）
    if pushed_count > 0 and not dry_run:
        notified[date] = today_notified
        save_subs_notified(notified)
        log.info("A12 订阅推送完成：%d 个订阅成功推送，已更新去重记录", pushed_count)
    else:
        log.info("A12 订阅推送完成：%s",
                 f"{pushed_count} 个订阅成功推送（dry-run 不写去重）" if dry_run and pushed_count
                 else "无订阅成功推送（无匹配/全部已去重/全部失败）")


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
    if sig_type == "sell_stop_loss":
        return "🟢"
    if sig_type == "band_hold":
        return "⚪"
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


# ============ #61 邮件/飞书信号带「回测宇宙+AI过滤+AI警示+AI建议」标记 (2026-08-17) ============
# 目标: 邮件/飞书每个信号带首页同款三层标记, 提高可信度——明确告诉用户"这个信号回测认不认、
# AI 认不认"。口径以用户 2026-08-17 两轮澄清定稿为准(见 docs/pending-features-index.md #61)。
#  ①回测宇宙: 不在 _bt_in_universe → 「未入回测宇宙」(历史表现不背书, =首页「未入样本」)
#  ②AI 过滤(统称, 两开关正交的删除线过滤层): 命中降亏键(ai_macro.hit) → 「AI降亏·建议回避」;
#     未入样本(_bt_in_universe===false) → 「未入样本」(归 AI过滤 类, 与①同判定不同展示角度)
#  ③AI 警示(独立类别, 离场保护, 与 AI过滤 正交): 入宇宙卖出信号(sell/sell_stop_loss, _bt_in_universe)
#     → 亮橙「AI警示」(首页 sig-poscap-warn 同语义, 卖出=保护已实现利润/离场, 无K约束不判K)
#  ④AI 建议 top-K(强化展示): 入样买入类信号(非降亏/非卖/非 band_hold)按首页 K=1 主推档排序
#     → 进 top1 = 「AI建议1」亮绿强化 / 其余满足条件 = 「当日已满」灰显(与首页 _posCapSortedFn
#     逐字段同排序口径, 仅去掉前端用户个人档位筛选——邮件为通用广播, 用全档位人口)
# 数据源一致性(§22/§23.6): _bt_in_universe + ai_macro 一律从 overview.json 读回测侧注入标记,
# 不自行重算宇宙; AI 建议 top-K 排序读 overview 信号 etfs.track_score + signal_stats score
# (与首页同数据源同排序), 非凭空自算。

# 首页 AI宏 8 键(基础5+核心3, 与 static-site/app.js _AI_MACRO_FILTER_NAMES 同源 §22)。
# v1.1.2 备选键 legacyMa60Special/declinePhaseSpecial 默认关, 仅凯利区手动开时命中;
# 首页/邮件/飞书永不因备选键判「AI降亏」(queries.py _ai_macro_hit_filters 无条件注入所有命中键,
# 故此处须按 8 键白名单二次过滤, 不能直接用 overview.ai_macro.hit=true 当命中——备选键命中要剔除)。
AI_MACRO_KEYS = {
    "n2NovSpecialIndustry", "excludeSpecialBear", "janMidRating",
    "janMidSpecial", "k2c5HkChase", "r7MayReinforced",
    "excludeAuxCross", "greedy15",
}
# v1.1.2 备选键中文名(仅名称展示用, 不进 AI_MACRO_KEYS 判定; 与 app.js _AI_MACRO_BACKUP_NAMES 同源 §22)
AI_MACRO_BACKUP_KEY_CN = {
    "legacyMa60Special": "老MA60熊×追买",
    "declinePhaseSpecial": "下降期×追关注",
}
# 键中文名映射(与 static-site/app.js _AI_MACRO_FILTER_NAMES 同源, §22 一致性; 邮件/飞书徽标缘由用)
AI_MACRO_KEY_CN = {
    "n2NovSpecialIndustry": "11月+追关注+行业",
    "excludeSpecialBear": "追关注×熊市交叉(四档)",
    "legacyMa60Special": "老MA60熊×追买",
    "declinePhaseSpecial": "下降期×追关注",
    "janMidRating": "1月中旬+中评级",
    "janMidSpecial": "1月中旬+追关注",
    "k2c5HkChase": "港股追涨剔除",
    "r7MayReinforced": "5月强化+3稳定非5月",
    "excludeAuxCross": "辅关注×3/5月交叉",
    "greedy15": "Greedy-15组合",
}
# 首页 AI 建议 top-K 排序的信号类型优先级(buy_backup>buy>buy_aux>buy_special, 与 app.js _sc 同)
_AI_RANK_SIG_ORDER = {"buy_backup": 0, "buy": 1, "buy_aux": 2, "buy_special": 3, "": 9}
# 首页 AI 建议/警示判定(与 app.js _isSellSig/_isSellRow 同): 卖类信号 = sell/sell_stop_loss/波段减仓
_AI_WARN_SELL_TYPES = {"sell", "sell_stop_loss"}


def load_overview_markers(date: str) -> tuple[dict, dict]:
    """读 overview.json 的 signals_today, 建 (index_id, signal) -> 标记 映射。

    返回 (exact, fallback) 两个 dict:
      - exact:  仅收录 date==目标日 的信号(收盘 17:50 后 overview 含当天 → 权威标记)
      - fallback: 收录所有日期(近 15 交易日), 供盘中(overview 未到当天)按 (index_id, signal)
        降级取最近历史信号标记(_bt_in_universe 为 index_id 级稳定, ai_macro 为信号级近似)
    marker = {"_bt_in_universe": bool|None, "ai_macro": dict, "signal": str, "etfs": list}
    读失败/无 signals_today 返回 (dict(), dict()) 空映射(调用方降级为不标注)。
    """
    if not OVERVIEW_PATH.exists():
        log.warning("overview.json 不存在：%s（#61 信号标记跳过）", OVERVIEW_PATH)
        return {}, {}
    try:
        data = json.loads(OVERVIEW_PATH.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        log.warning("overview.json 读取失败：%s（#61 信号标记跳过）", e)
        return {}, {}
    st = data.get("signals_today")
    if not isinstance(st, list):
        return {}, {}
    exact: dict = {}
    fallback: dict = {}
    for s in st:
        if not isinstance(s, dict):
            continue
        iid = s.get("index_id")
        sig = s.get("signal")
        if not iid or not sig:
            continue
        marker = {
            "_bt_in_universe": s.get("_bt_in_universe"),
            "ai_macro": s.get("ai_macro") if isinstance(s.get("ai_macro"), dict) else {},
            "signal": sig,
            "etfs": s.get("etfs") if isinstance(s.get("etfs"), list) else [],
        }
        key = (iid, sig)
        fallback[key] = marker  # 近 15 日同 (iid, sig) 后写入=最新(列表按日期, 直接覆盖)
        if s.get("date") == date:
            exact[key] = marker
    return exact, fallback


def _top_etf_by_score(etfs: list) -> dict | None:
    """复刻首页 _topEtfByScore(app.js L2174): 回测冻结 _bk_top 优先, 否则 max(track_score)
    降序(平手回退 similarity 降序)。返回 ETF dict 或 None。"""
    if not etfs:
        return None
    for e in etfs:
        if e and e.get("_bk_top") is True:
            return e
    def _ts(e):
        return e.get("track_score") if isinstance(e.get("track_score"), (int, float)) else -1
    def _sim(e):
        return e.get("similarity") if isinstance(e.get("similarity"), (int, float)) else -1
    return max(etfs, key=lambda e: (_ts(e), _sim(e)))


def _ai_rating_of_signal(sig: dict, stats: dict) -> str:
    """复刻首页 _ratingOf(app.js L2619): 用 signal_stats[index_id][sig]["10d"].score 分档评级。
    score>=0.75 high / >=0.55 mid / 其他 low; 无 score 返回空串(排最后)。"""
    sig_key = "buy_special" if sig.get("signal") == "buy_special_filtered" else sig.get("signal")
    d = (stats.get(sig.get("index_id") or "", {}).get(sig_key or "", {}) or {}).get("10d")
    sc = d.get("score") if d and isinstance(d.get("score"), (int, float)) else None
    if sc is None:
        return ""
    if sc >= 0.75:
        return "high"
    if sc >= 0.55:
        return "mid"
    return "low"


def build_ai_suggest_map(signals: list[dict], overview_markers: dict, stats: dict) -> dict:
    """复刻首页 K=1 主推档 AI 建议 top-K, 建 (index_id, signal) -> rank 映射。

    首页 _posCapKeptMap(L2641-2658) 口径: 对当日信号(首页 popItems 内), 过滤
      signal not in (band_hold, sell, sell_stop_loss) 且 _bt_in_universe!==false 且非 AI 降亏命中,
      按 _posCapSortedFn(track_score↓→评级high>mid>low→信号类型buy_backup>buy>buy_aux>buy_special)
      排序取前 K 名(K=1 主推档)。
    candidates 只取「本邮件要展示的当日 signals」内满足条件的(展示范围内谁最优, 与邮件展示一一对应;
      邮件为通用广播, 用全量信号人口, 去掉前端用户个人档位筛选)。
    只返回 top1(index_id, signal) -> rank=1(K=1 主推); 其余候选者为「当日已满」(调用方
      _calc_signal_markers 判定 ai_full)。rank 从 1 起。
    """
    candidates = []
    for s in signals:
        iid = s.get("index_id")
        sig = s.get("signal")
        if sig in ("band_hold", "sell", "sell_stop_loss"):
            continue
        m = overview_markers.get((iid, sig))
        if m is None or m.get("_bt_in_universe") is False:
            continue
        if m.get("ai_macro", {}).get("hit"):
            continue
        candidates.append({"index_id": iid, "signal": sig,
                           "track_score": (_top_etf_by_score(m.get("etfs")) or {}).get("track_score"),
                           "rating": _ai_rating_of_signal(s, stats)})
    if not candidates:
        return {}
    # 排序: track_score DESC -> rating(high>mid>low>"") -> signal type(buy_backup>buy>buy_aux>buy_special)
    _rating_rank = {"high": 0, "mid": 1, "low": 2, "": 3}
    def _sort_key(c):
        ts = c["track_score"] if isinstance(c["track_score"], (int, float)) else -1
        rr = _rating_rank.get(c["rating"], 3)
        sr = _AI_RANK_SIG_ORDER.get(c["signal"], 9)
        return (-ts, rr, sr)
    candidates.sort(key=_sort_key)
    top = candidates[0]
    return {(top["index_id"], top["signal"]): 1}


def _calc_signal_markers(sig: dict, overview_markers: dict, stats: dict,
                         ai_suggest: dict) -> dict:
    """为单个信号计算 #61 标记集合(只读 overview 注入 + signal_stats, 不自行重算宇宙)。

    返回 dict:
      in_universe: bool|None (None=overview 无该信号标记, 未知)
      ai_fade: bool 命中 8 键降亏(AI 降亏层)
      ai_fade_keys: list[str] 命中的 8 键英文名(白名单过滤, 邮件/飞书徽标精简缘由用)
      ai_warn: bool 入样卖出信号 → AI 警示(离场保护, 与 AI 过滤正交)
      ai_rank: int|None 首页 K=1 top-K 内的排名(AI 建议 N, 从 1 起)
      ai_full: bool 满足 AI 建议候选条件但超出 top-K → 「当日已满」
    """
    marker = overview_markers.get((sig["index_id"], sig["signal"]))
    in_universe = None
    ai_fade = False
    ai_fade_keys: list = []
    if marker is not None:
        in_universe = marker.get("_bt_in_universe")
        _am = marker.get("ai_macro", {})
        # 命中键英文数组 → 8 键白名单过滤(AI_MACRO_KEYS 不含 v1.1.2 备选键), 防未知/备选键混入;
        # 顺序随 overview 注入, 不重排。首页/邮件/飞书仅 8 键命中才算「AI降亏」(备选键仅凯利区手动开时命中, §22)
        ai_fade_keys = [k for k in (_am.get("filters") or []) if k in AI_MACRO_KEYS]
        ai_fade = bool(ai_fade_keys)
    sig_type = sig.get("signal") or ""
    # AI 警示: 入宇宙卖出(sell/sell_stop_loss), 首页 _isSellSig + _bt_in_universe!==false 同语义
    ai_warn = (sig_type in _AI_WARN_SELL_TYPES) and (in_universe is not False)
    ai_rank = ai_suggest.get((sig["index_id"], sig_type))
    ai_full = False
    if ai_rank is None and not ai_warn and in_universe is not False \
            and sig_type not in ("band_hold",) and not ai_fade:
        # 满足 AI 建议候选(入样买入/非降亏/非持有)但不在 top-K 内 → 当日已满
        ai_full = True
    return {
        "in_universe": in_universe,
        "ai_fade": ai_fade,
        "ai_fade_keys": ai_fade_keys,
        "ai_warn": ai_warn,
        "ai_rank": ai_rank,
        "ai_full": ai_full,
    }


def _ai_fade_label(mk: dict) -> str:
    """AI降亏徽标文案(邮件/飞书共用, §22/§23.10 一致性)。

    命中键非空 → 「AI降亏·建议回避【中文名1、中文名2】」(多键用「、」分隔);
    无命中键(理论不该发生, ai_fade 恒来自命中) → 回退原「AI降亏·建议回避」。
    """
    base = "AI降亏·建议回避"
    keys = mk.get("ai_fade_keys") or []
    if not keys:
        return base
    cns = [AI_MACRO_KEY_CN.get(k, AI_MACRO_BACKUP_KEY_CN.get(k, k)) for k in keys]
    return f"{base}【{'、'.join(cns)}】"


def _signal_marker_badge_html(mk: dict) -> str:
    """生成单个信号的 #61 标记徽标 HTML(空串=无标记)。在的强化展示, 不在的明确标注。

    优先级: AI建议1(亮绿强化, 最高) > AI警示(亮橙) > AI降亏(橙红) > 未入样本(灰红) > 当日已满(灰)。
    未入样本(未入回测宇宙)与 AI降亏 叠加展示; AI警示 与 AI过滤 正交可并存。
    """
    badges = []
    if mk["ai_rank"] is not None:
        badges.append(
            '<span style="background:#f0fff4;border:1px solid #52c41a;color:#237804;'
            'font-size:11px;font-weight:700;padding:1px 6px;border-radius:3px;margin-right:4px;">'
            f'AI建议{mk["ai_rank"]}</span>')
    if mk["ai_warn"]:
        badges.append(
            '<span style="background:#fff7e6;border:1px solid #fa8c16;color:#d46b08;'
            'font-size:11px;font-weight:700;padding:1px 6px;border-radius:3px;margin-right:4px;">'
            'AI警示</span>')
    if mk["ai_fade"]:
        badges.append(
            '<span style="background:#fff1f0;border:1px solid #ff4d4f;color:#cf1322;'
            'font-size:11px;font-weight:700;padding:1px 6px;border-radius:3px;margin-right:4px;">'
            f'{_ai_fade_label(mk)}</span>')
    if mk["in_universe"] is False:
        badges.append(
            '<span style="background:#f7f8fa;border:1px solid #c9cdd4;color:#86909c;'
            'font-size:11px;font-weight:700;padding:1px 6px;border-radius:3px;margin-right:4px;">'
            '未入回测宇宙</span>')
    if mk["ai_full"]:
        badges.append(
            '<span style="background:#f7f8fa;border:1px solid #c9cdd4;color:#86909c;'
            'font-size:11px;font-weight:700;padding:1px 6px;border-radius:3px;margin-right:4px;">'
            '当日已满</span>')
    return "".join(badges)


def _signal_marker_badge_text(mk: dict) -> str:
    """生成单个信号的 #61 标记文本(飞书 post 用, 与邮件徽标内容一致, §23.10)。"""
    parts = []
    if mk["ai_rank"] is not None:
        parts.append(f"AI建议{mk['ai_rank']}")
    if mk["ai_warn"]:
        parts.append("AI警示")
    if mk["ai_fade"]:
        parts.append(_ai_fade_label(mk))
    if mk["in_universe"] is False:
        parts.append("未入回测宇宙")
    if mk["ai_full"]:
        parts.append("当日已满")
    return " ".join(parts)


def _detect_buy_fade(idx: str, intraday_sig: str, closing_sigs: set[str],
                     closing_buy_sigs: set[str], closing_sell_sigs: set[str]) -> dict | None:
    """buy 系列 fade 判定（原逻辑，2026-07-23 P1-新-A）。返回 alert dict 或 None（不警示）。"""
    if not closing_sigs:
        return {"index_id": idx, "intraday_signal": intraday_sig,
                "closing_signals": sorted(closing_sigs), "kind": "buy",
                "level": "red", "closing_status": "无任何信号",
                "suggestion": "信号消失，建议人工复核行情"}
    if closing_sell_sigs:
        sell_labels = "、".join(_signal_label(s) for s in sorted(closing_sell_sigs))
        return {"index_id": idx, "intraday_signal": intraday_sig,
                "closing_signals": sorted(closing_sigs), "kind": "buy",
                "level": "orange", "closing_status": f"出现卖出信号（{sell_labels}）",
                "suggestion": "由买转卖，建议谨慎评估"}
    if closing_buy_sigs:
        intraday_strength = BUY_STRENGTH[intraday_sig]
        max_closing_strength = max(BUY_STRENGTH[s] for s in closing_buy_sigs)
        if max_closing_strength < intraday_strength:
            buy_labels = "、".join(_signal_label(s) for s in sorted(closing_buy_sigs))
            return {"index_id": idx, "intraday_signal": intraday_sig,
                    "closing_signals": sorted(closing_sigs), "kind": "buy",
                    "level": "yellow", "closing_status": f"降级为 {buy_labels}",
                    "suggestion": "信号强度减弱，关注后续走势"}
        return None  # 同级或升级，不警示
    return None  # 收盘有信号但既非 buy 也非 sell（理论不会到这里，兜底）


def _detect_sell_fade(idx: str, intraday_sig: str, closing_sigs: set[str],
                      closing_buy_sigs: set[str], closing_sell_sigs: set[str]) -> dict | None:
    """sell 系列 fade 判定（2026-08-10 加，需求1）。

    sell 消失语义特殊：卖出/减仓信号消失 = 价格回落不再超买 = 利好方向
    （减仓条件解除），非"风险信号消失"。文案明确"减仓条件解除"，避免误导
    用户以为风险解除。盘中严格消失归 red 档（盘中 red 档才推邮件，见 main）。

    判定：
      - 严格消失（红 red）：盘中推 (X, sell*) 收盘无 X 任何 sell*
        （closing_sigs 空 / 仅 band_hold 中性 视为 sell 消失；转 buy* 归橙档）
      - 由卖转买（橙 orange）：收盘有 (X, buy*)
      - 减弱（黄 yellow）：收盘仍有 sell* 但更弱（如追止损卖->卖）
      - 同级/更强保留：不警示
    """
    if closing_sell_sigs:
        intraday_strength = SELL_STRENGTH[intraday_sig]
        max_closing_strength = max(SELL_STRENGTH[s] for s in closing_sell_sigs)
        if max_closing_strength < intraday_strength:
            sell_labels = "、".join(_signal_label(s) for s in sorted(closing_sell_sigs))
            return {"index_id": idx, "intraday_signal": intraday_sig,
                    "closing_signals": sorted(closing_sigs), "kind": "sell",
                    "level": "yellow", "closing_status": f"卖出信号减弱为 {sell_labels}",
                    "suggestion": "卖出压力减轻，减仓紧迫度下降"}
        return None  # 同级或更强 sell 保留，不警示
    if closing_buy_sigs:
        buy_labels = "、".join(_signal_label(s) for s in sorted(closing_buy_sigs))
        return {"index_id": idx, "intraday_signal": intraday_sig,
                "closing_signals": sorted(closing_sigs), "kind": "sell",
                "level": "orange", "closing_status": f"转为买入信号（{buy_labels}）",
                "suggestion": "由卖转买，行情或反转向上"}
    # 收盘无 sell 也无 buy（含仅 band_hold 中性）：卖出信号消失 = 价格回落，减仓条件解除
    return {"index_id": idx, "intraday_signal": intraday_sig,
            "closing_signals": sorted(closing_sigs), "kind": "sell",
            "level": "red", "closing_status": "卖出信号已消失（价格回落，减仓条件解除）",
            "suggestion": "卖出/减仓压力缓解；已减仓可关注回落后的接回机会"}


def detect_fade(
    notified_entries: list[list[str]],
    closing_signals: list[tuple[str, str]] | list[dict],
) -> list[dict]:
    """检测盘中推送信号收盘是否消失/变化（fade-detect，2026-07-23 P1-新-A）。

    buy 系列：严格消失/类型变化/降级保留三档警示（原有）。
    sell 系列（2026-08-10 加，需求1）：卖出/减仓信号消失也警示，语义为
      "减仓条件解除（价格回落）"，文案与 buy 消失区分，避免误导。

    三档判定（buy）：
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
        index_id / intraday_signal / closing_signals(list) / kind(buy/sell) /
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
        # 只跟踪 buy* / sell*（band_hold 中性信号不跟踪）
        if intraday_sig not in BUY_STRENGTH and intraday_sig not in SELL_TYPES:
            continue
        closing_sigs = closing_by_idx.get(idx, set())
        closing_buy_sigs = {s for s in closing_sigs if s in BUY_STRENGTH}
        closing_sell_sigs = {s for s in closing_sigs if s in SELL_TYPES}

        if intraday_sig in SELL_TYPES:
            alert = _detect_sell_fade(idx, intraday_sig, closing_sigs,
                                      closing_buy_sigs, closing_sell_sigs)
        else:
            alert = _detect_buy_fade(idx, intraday_sig, closing_sigs,
                                     closing_buy_sigs, closing_sell_sigs)
        if alert is not None:
            fade_alerts.append(alert)
    return fade_alerts


def run_fade_detect(date: str, closing_signals: list[dict],
                    intraday: bool = False) -> list[dict]:
    """加载盘中 signal_notified.json[date]，对比收盘信号，返回 fade_alerts。

    收盘模式：对比盘中推送 vs 收盘 signal_daily，检测消失/变化。
    盘中模式（intraday=True，AZ54 P1-4 2026-07-29）：对比上一轮推送 vs 本轮 signal_daily，
      检测消失/变化。同日同 index_id|level 去重（fade_notified.json），只返回本轮新出现的 fade。
    盘中无推送记录时返回空 list（不警示）。
    """
    notified = load_signal_notified()
    notified_entries = notified.get(date, [])
    if not notified_entries:
        log.info("fade-detect：%s 无盘中推送记录（signal_notified.json），跳过", date)
        return []
    closing_pairs = [(s["index_id"], s["signal"]) for s in closing_signals]
    fade_alerts = detect_fade(notified_entries, closing_pairs)

    if intraday:
        # 盘中模式：同日同 index_id|level 去重，只返回本轮新出现的 fade
        before = len(fade_alerts)
        fade_alerts = filter_fade_alerts_intraday(fade_alerts, date)
        if before > len(fade_alerts):
            log.info("fade-detect：盘中去重 %d -> %d 条（%d 条已通知跳过）",
                     before, len(fade_alerts), before - len(fade_alerts))

    mode_label = "本轮" if intraday else "收盘"
    if fade_alerts:
        log.warning("fade-detect：%s 盘中推送 %d 条，检测到 %d 条%s消失/变化",
                    date, len(notified_entries), len(fade_alerts), mode_label)
        for a in fade_alerts:
            emoji, level_label, _ = FADE_LEVEL_INFO.get(a["level"], ("⚪", a["level"], ""))
            log.warning("  %s [%s] %s 盘中=%s -> %s=%s",
                        emoji, level_label, a["index_id"],
                        a["intraday_signal"], mode_label, a["closing_status"])
    else:
        log.info("fade-detect：%s 盘中推送 %d 条，%s全部保留/升级，无消失",
                 date, len(notified_entries), mode_label)
    return fade_alerts


def _reset_fade_notified(date: str, fade_alerts: list[dict]) -> bool:
    """盘中模式「消失即重置」：信号消失(fade)时把其已通知状态移除，再现时重新通知（无冷却）。

    用户原则（2026-08-18）：重复通知=状态不变还重复；状态一变（出现→消失→再现→再消失，
    可无限循环）每个动作都是新事件都要通知；消失就重置；不设冷却。
    只 remove 不 add：只清 fade 中信号的已通知标记，其余已通知保留。
    返回是否发生了重置（用于日志）。
    """
    if not fade_alerts:
        return False
    notified = load_signal_notified()
    today = {tuple(x) for x in notified.get(date, [])}
    n = 0
    for a in fade_alerts:
        k = (a["index_id"], a["intraday_signal"])
        if k in today:
            today.discard(k)
            n += 1
    if n:
        notified[date] = sorted([list(x) for x in today])
        save_signal_notified(notified)
        log.info("fade-reset：盘中消失 %d 条已重置已通知状态（再现将重新通知）", n)
    return n > 0


def _clear_fade_dedup_for_reappear(date: str, signals: list[dict]) -> int:
    """盘中「再现即清 fade 去重」：信号再现时清其 fade_notified.json 去重，
    下次再消失能再次发 fade 通知。

    与 _reset_fade_notified（消失即重置 signal_notified）对称，构成
    「出现→消失→再现→再消失…可无限循环，每个动作都通知」完整闭环
    （用户原则 2026-08-18）。无此对称，fade_notified 的「同日同 key 只保留首次」
    去重会吞掉第二次消失（再消失）的 fade 通知。只 remove 不 add。
    返回清理条数。
    """
    if not signals or not FADE_NOTIFIED_PATH.exists():
        return 0
    try:
        dedup = json.loads(FADE_NOTIFIED_PATH.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        log.warning("fade_notified.json 清理读取失败（降级）：%s", e)
        return 0
    if not isinstance(dedup, dict):
        dedup = {}
    today = dedup.get(date, {})
    if not isinstance(today, dict) or not today:
        return 0
    idxs = {s["index_id"] for s in signals}
    n = 0
    for k in list(today.keys()):
        if k.split("|", 1)[0] in idxs:
            del today[k]
            n += 1
    if n:
        dedup[date] = today
        try:
            FADE_NOTIFIED_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp = FADE_NOTIFIED_PATH.parent / (FADE_NOTIFIED_PATH.name + ".tmp")
            tmp.write_text(json.dumps(dedup, ensure_ascii=False, separators=(",", ":")),
                           encoding="utf-8")
            tmp.replace(FADE_NOTIFIED_PATH)
            log.info("fade-dedup-clear：再现 %d 条已清 fade 去重（下次再消失将再发 fade 通知）", n)
        except Exception as e:  # noqa: BLE001
            log.warning("fade_notified.json 清理写入失败（降级）：%s", e)
    return n


def _build_fade_banner(fade_alerts: list[dict], name_map: dict[str, str],
                       intraday: bool = False) -> str:
    """构建 fade 警示横幅 HTML（红/橙/黄三档表格 + sell 行绿色系）。

    intraday=True 时文案用"本轮消失"（盘中实时模式），False 用"收盘消失"（收盘模式）。
    AZ54 P1-4（2026-07-29）：盘中模式文案区分。
    2026-08-10（需求1）：sell 系列 fade（卖出信号消失=减仓条件解除，利好方向）用
      绿色系整行渲染 + 专属文案，与 buy 消失（风险信号）的红色系区分，避免误导。
      全为 sell fade 时横幅整体转绿色标题"卖出/减仓信号解除"。
    """
    rows_html = []
    has_sell = any(a.get("kind") == "sell" for a in fade_alerts)
    for a in fade_alerts:
        name = index_id_to_name(a["index_id"], name_map)
        intraday_label = _signal_label(a["intraday_signal"])
        if a.get("kind") == "sell":
            emoji, row_bg, row_border, sugg_color = "💚", "#f6ffed", "#d9f7be", "#389e0d"
        else:
            emoji, _, _ = FADE_LEVEL_INFO.get(a["level"], ("⚪", a["level"], "#86909c"))
            row_bg, row_border, sugg_color = "#fff1f0", "#ffe7e6", "#cf1322"
        rows_html.append(
            f'<tr style="border-bottom:1px solid {row_border};background:{row_bg};">'
            f'<td style="padding:8px 10px;">{emoji} <b>{name}</b></td>'
            f'<td style="padding:8px 10px;font-size:12px;">{intraday_label}</td>'
            f'<td style="padding:8px 10px;font-size:12px;color:#4e5969;">{a["closing_status"]}</td>'
            f'<td style="padding:8px 10px;font-size:12px;color:{sugg_color};">{a["suggestion"]}</td>'
            f'</tr>'
        )
    rows = "\n".join(rows_html)
    n = len(fade_alerts)
    mode_label = "本轮" if intraday else "收盘"
    all_sell = has_sell and all(a.get("kind") == "sell" for a in fade_alerts)
    if all_sell:
        title = f'✅ 卖出/减仓信号{mode_label}解除（{n} 条）'
        desc = ('以下卖出/减仓信号盘中已推送，但状态消失或减弱（价格回落不再超买，'
                '减仓条件解除，属利好方向而非风险解除）：')
        banner_bg, banner_border, title_color, desc_color = "#f6ffed", "#95de64", "#389e0d", "#237804"
    else:
        title = f'⚠️ 盘中信号{mode_label}消失警示（{n} 条）'
        desc = '以下信号盘中已推送，但状态变化或消失，请重点关注：'
        if has_sell:
            desc += '（绿色行=卖出信号消失，属减仓条件解除，非风险信号）'
        banner_bg, banner_border, title_color, desc_color = "#fff1f0", "#ffa39e", "#cf1322", "#a8071a"
    status_header = "本轮状态" if intraday else "收盘状态"
    return (
        f'<div style="background:{banner_bg};border:2px solid {banner_border};border-radius:6px;'
        'padding:12px 16px;margin:0 0 14px 0;">'
        f'<div style="font-weight:700;color:{title_color};font-size:15px;margin-bottom:6px;">'
        f'{title}</div>'
        f'<p style="margin:0 0 10px 0;color:{desc_color};font-size:13px;line-height:1.6;">'
        f'{desc}</p>'
        '<table style="width:100%;border-collapse:collapse;font-size:13px;background:#fff;">'
        f'<thead><tr style="background:{banner_bg};text-align:left;">'
        f'<th style="padding:8px 10px;border-bottom:2px solid {banner_border};">品种</th>'
        f'<th style="padding:8px 10px;border-bottom:2px solid {banner_border};">盘中信号</th>'
        f'<th style="padding:8px 10px;border-bottom:2px solid {banner_border};">{status_header}</th>'
        f'<th style="padding:8px 10px;border-bottom:2px solid {banner_border};">建议操作</th>'
        '</tr></thead><tbody>'
        f'{rows}'
        '</tbody></table></div>'
    )


def load_signal_intraday_timeline(date: str) -> list[dict]:
    """读 signal_intraday_log 当日记录，生成每个 (index_id, signal) 的出现/消失时间线。

    intraday_snapshot._recompute_signals 每轮重算后追加当日信号 + HH:MM 时间戳
    （方案A，2026-08-10）。返回 list[dict]，按出现时间排序，每项含:
      index_id / signal / appear_time / last_time / persists(bool) / reason / segment
    persists=True=在最后轮（最后出现时间）仍存在，即持续到收盘；
    persists=False=盘中已消失（最后出现后下一轮重算不再出现）。

    分段（2026-08-18 用户原则「状态一变每次都是新事件」）：同一 (index_id, signal)
    出现→消失→再现→再消失...会按时间升序切出多段，每段一条 dict：
      - 段切分：该 key 相邻两次出现时间之间，若当日全量时间集合里存在「中间轮」
        （其它 key 有记录、该 key 缺席）→ 断段，新段开始。
      - appear_time=段首（该段第一次出现时点）；last_time=段末（该段最后一次出现时点）。
      - persists 仅最后一段 = key 在最后轮 last_round_pairs 中；之前各段恒 False。
      - segment = 1-based 段序号。
    消费方（_build_timeline_html 收盘全貌）同一 key 多段显示多行，展示完整序列；
    fade 通知消费方（_build_fade_detail_html / build_feishu_post）取最后一段（最近一次出现）。
    无记录返回 []。
    """
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT time, index_id, signal, reason FROM signal_intraday_log "
            "WHERE date = ? ORDER BY time, index_id, signal",
            (date,),
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        return []
    all_times = sorted({r["time"] for r in rows})
    last_round_time = all_times[-1]
    last_round_pairs = {(r["index_id"], r["signal"]) for r in rows if r["time"] == last_round_time}
    # key -> time -> 该轮该 key 的 reason（取第一个非空）
    reason_at: dict[tuple[str, str], dict[str, str]] = {}
    present_at: dict[str, set[tuple[str, str]]] = {t: set() for t in all_times}
    for r in rows:
        key = (r["index_id"], r["signal"])
        present_at[r["time"]].add(key)
        if r["reason"]:
            reason_at.setdefault(key, {})[r["time"]] = r["reason"]

    out: list[dict] = []
    # 每 key 沿全量时间集合顺序走一遍：出现→(缺席中间轮)→再现 即断段
    all_keys = set()
    for keys in present_at.values():
        all_keys |= keys
    for key in all_keys:
        index_id, signal = key
        cur: dict | None = None
        prev_present = False
        for t in all_times:
            present = key in present_at[t]
            if present:
                if cur is None or not prev_present:
                    if cur is not None:
                        out.append(cur)
                    cur = {
                        "index_id": index_id,
                        "signal": signal,
                        "appear_time": t,
                        "last_time": t,
                        "persists": False,
                        "reason": (reason_at.get(key, {}).get(t) or ""),
                        "segment": 1,
                    }
                else:
                    cur["last_time"] = t
                    if not cur["reason"] and reason_at.get(key, {}).get(t):
                        cur["reason"] = reason_at[key][t]
            prev_present = present
        if cur is not None:
            out.append(cur)
    # 赋段序号 + 最后一段 persists 语义（key 在最后轮=持续到收盘）
    for e in out:
        e["reason"] = e.get("reason") or ""
    per_key = {}
    for e in out:
        per_key.setdefault((e["index_id"], e["signal"]), []).append(e)
    for key, segs in per_key.items():
        segs.sort(key=lambda x: x["appear_time"])
        for i, e in enumerate(segs, 1):
            e["segment"] = i
            if i == len(segs):
                e["persists"] = key in last_round_pairs
    out.sort(key=lambda x: (x["appear_time"], x["index_id"], x["signal"]))
    return out


def _build_timeline_html(timeline: list[dict], name_map: dict[str, str],
                         stats: dict, om: dict | None = None,
                         ai_sg: dict | None = None) -> str:
    """构建当日信号时间线表格 HTML（收盘全过程复现，需求2 方案A）。

    每个信号显示 出现时间 / 状态（持续到收盘 或 消失）：
      - 持续到收盘（绿）：最后轮重算仍在
      - 盘中消失（橙/绿按信号类型）：sell 消失=减仓条件解除（绿，利好），buy 消失=风险（橙）
    om/ai_sg（#61 2026-08-17 用户修正）：时间线信号照常带「AI 标记」列（回测宇宙/AI过滤/AI警示/
      AI建议 top-K，与首页/盘中一致）。去重后只发时间线复盘时信号也带标记，不省略（用户原话：
      "只要推给用户的信号都要带上这个标记，就和用户首页看到的一样"）。None 时降级为不标注。
    """
    om = om if om is not None else {}
    ai_sg = ai_sg if ai_sg is not None else {}
    rows_html = []
    for t in timeline:
        name = index_id_to_name(t["index_id"], name_map)
        label = _signal_label(t["signal"])
        emoji = _signal_emoji(t["signal"])
        reason = (t["reason"] or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        # #61(2026-08-17 用户修正): 时间线信号照常算 AI 标记(回测宇宙/AI过滤/AI警示/AI建议 top-K)
        _mk = _calc_signal_markers(t, om, stats, ai_sg)
        _badge = _signal_marker_badge_html(_mk)
        if t["persists"]:
            status = '<span style="color:#2e8b57;"><b>持续到收盘</b></span>'
        elif t["signal"] in SELL_TYPES:
            status = f'<span style="color:#389e0d;">{t["last_time"]} 后消失（减仓条件解除）</span>'
        else:
            status = f'<span style="color:#d4380d;">{t["last_time"]} 后消失</span>'
        rows_html.append(
            f'<tr style="border-bottom:1px solid #f2f3f5;">'
            f'<td style="padding:7px 10px;">{emoji} <b>{name}</b></td>'
            f'<td style="padding:7px 10px;font-size:12px;">{label}</td>'
            f'<td style="padding:7px 10px;font-size:12px;"><b>{t["appear_time"]}</b></td>'
            f'<td style="padding:7px 10px;font-size:12px;">{status}</td>'
            f'<td style="padding:7px 10px;font-size:12px;">{_badge}</td>'
            f'<td style="padding:7px 10px;font-size:12px;color:#4e5969;">{reason}</td>'
            f'</tr>'
        )
    rows = "\n".join(rows_html)
    return (
        '<div style="background:#f0f5ff;border:1px solid #adc6ff;border-radius:6px;'
        'padding:12px 16px;margin:0 0 14px 0;">'
        '<div style="font-weight:700;color:#1d39c4;font-size:15px;margin-bottom:6px;">'
        f'🕐 当日信号时间线（{len(timeline)} 条）</div>'
        '<p style="margin:0 0 10px 0;color:#597ef7;font-size:13px;line-height:1.6;">'
        '盘中每轮重算实时记录：每个信号几点出现、几点消失（消失=该时点后重算不再出现）。'
        '<b>持续到收盘</b>=最后轮重算仍在；绿色=减仓条件解除（利好），橙色=信号消失（注意）。'
        '信号行带「AI 标记」列（与首页/盘中一致）。'
        '</p>'
        '<table style="width:100%;border-collapse:collapse;font-size:13px;background:#fff;">'
        '<thead><tr style="background:#f0f5ff;text-align:left;">'
        '<th style="padding:7px 10px;border-bottom:2px solid #adc6ff;">品种</th>'
        '<th style="padding:7px 10px;border-bottom:2px solid #adc6ff;">信号</th>'
        '<th style="padding:7px 10px;border-bottom:2px solid #adc6ff;">出现时间</th>'
        '<th style="padding:7px 10px;border-bottom:2px solid #adc6ff;">状态</th>'
        '<th style="padding:7px 10px;border-bottom:2px solid #adc6ff;">AI 标记</th>'
        '<th style="padding:7px 10px;border-bottom:2px solid #adc6ff;">触发条件</th>'
        '</tr></thead><tbody>'
        f'{rows}'
        '</tbody></table></div>'
    )


def _build_fade_detail_html(fade_alerts: list[dict], timeline: list[dict],
                            name_map: dict[str, str], now_hm: str) -> str:
    """盘中 fade 通知的时间线详情（2026-08-10 用户增量：盘中模式也读时间线）。

    盘中模式（--intraday）信号消失发通知时，附上该信号当日在 signal_intraday_log
    里的出现细节（产生时间/通知时间），让用户不用翻历史邮件就知道来龙去脉。
    与收盘全貌时间线（_build_timeline_html）分离：只展示 fade 中的信号。

    timeline 为按 fade alert (index_id, signal) 过滤后的当日时间线子集，每项含
      appear_time（首次出现=产生/推送时点）/ last_time（最后出现后消失）/ reason。
    """
    rows_html = []
    for a in fade_alerts:
        name = index_id_to_name(a["index_id"], name_map)
        label = _signal_label(a["intraday_signal"])
        emoji = _signal_emoji(a["intraday_signal"])
        matches = [t for t in timeline
                   if t["index_id"] == a["index_id"] and t["signal"] == a["intraday_signal"]]
        if matches:
            # 取最后一段（最近一次出现 → 本轮消失段），fade 通知不需要历史段（那是收盘时间线的活）
            m = matches[-1]
            reason = (m.get("reason") or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            # "14:55 出现 → 15:02 消失"：appear_time=本段首次出现(通知)时间, last_time=本段最后出现, 本轮检测消失
            status = f'<b>{m["last_time"]}</b> 后消失（本轮 {now_hm} 检测）'
            rows_html.append(
                f'<tr style="border-bottom:1px solid #d9f7be;background:#f6ffed;">'
                f'<td style="padding:7px 10px;">{emoji} <b>{name}</b></td>'
                f'<td style="padding:7px 10px;font-size:12px;">{label}</td>'
                f'<td style="padding:7px 10px;font-size:12px;"><b>{m["appear_time"]}</b></td>'
                f'<td style="padding:7px 10px;font-size:12px;color:#389e0d;">{status}</td>'
                f'<td style="padding:7px 10px;font-size:12px;color:#4e5969;">{reason}</td>'
                f'</tr>'
            )
        else:
            # 时间线无该信号记录（log 缺失/早于记录起点）：退化只展示 fade 状态
            reason = (a.get("closing_status") or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            rows_html.append(
                f'<tr style="border-bottom:1px solid #f2f3f5;">'
                f'<td style="padding:7px 10px;">{emoji} <b>{name}</b></td>'
                f'<td style="padding:7px 10px;font-size:12px;">{label}</td>'
                f'<td style="padding:7px 10px;font-size:12px;">-</td>'
                f'<td style="padding:7px 10px;font-size:12px;color:#389e0d;">本轮检测消失</td>'
                f'<td style="padding:7px 10px;font-size:12px;color:#4e5969;">{reason}</td>'
                f'</tr>'
            )
    rows = "\n".join(rows_html)
    n = len(fade_alerts)
    return (
        '<div style="background:#f6ffed;border:1px solid #b7eb8f;border-radius:6px;'
        'padding:12px 16px;margin:0 0 14px 0;">'
        '<div style="font-weight:700;color:#389e0d;font-size:15px;margin-bottom:6px;">'
        f'🕐 信号消失详情 · 盘中时间线（{n} 条）</div>'
        '<p style="margin:0 0 10px 0;color:#237804;font-size:13px;line-height:1.6;">'
        '以下为盘中已推送但本轮消失/变化的信号，附其当日出现细节（产生/通知时间 → 消失时点），'
        '免去翻历史邮件：<b>出现(通知)时间</b>=盘中首次出现并推送通知的时点，'
        '<b>消失时间</b>=最后出现后本轮重算不再出现的时点。</p>'
        '<table style="width:100%;border-collapse:collapse;font-size:13px;background:#fff;">'
        '<thead><tr style="background:#f6ffed;text-align:left;">'
        '<th style="padding:7px 10px;border-bottom:2px solid #b7eb8f;">品种</th>'
        '<th style="padding:7px 10px;border-bottom:2px solid #b7eb8f;">信号</th>'
        '<th style="padding:7px 10px;border-bottom:2px solid #b7eb8f;">出现(通知)时间</th>'
        '<th style="padding:7px 10px;border-bottom:2px solid #b7eb8f;">消失时间</th>'
        '<th style="padding:7px 10px;border-bottom:2px solid #b7eb8f;">触发条件</th>'
        '</tr></thead><tbody>'
        f'{rows}'
        '</tbody></table></div>'
    )


def _group_signals(signals: list[dict]) -> dict[str, list[dict]]:
    """按 signal 类型分组（含 SIGNAL_ORDER 全部类型 + 未知类型兜底）。"""
    groups: dict[str, list[dict]] = {k: [] for k in SIGNAL_ORDER}
    for s in signals:
        sig = s["signal"]
        if sig in groups:
            groups[sig].append(s)
        else:
            groups.setdefault(sig, []).append(s)
    return groups


def build_email(date: str, signals: list[dict], name_map: dict[str, str],
                intraday: bool = False,
                fade_alerts: list[dict] | None = None,
                timeline: list[dict] | None = None,
                fade_timeline: list[dict] | None = None,
                subject_signals: list[dict] | None = None,
                dedup_annotate: bool = False,
                overview_markers: dict | None = None,
                ai_suggest: dict | None = None) -> tuple[str, str]:
    """构建邮件主题 + HTML 正文。返回 (subject, html_body)。

    intraday=True 时邮件标注【盘中实时】+ 风险提示横幅（盘中快照非最终，
    收盘后 17:50 update_all 仍发最终版）。默认 False（收盘/历史回测用）。

    timeline（2026-08-10 需求2）：收盘全过程复现时间线，非 intraday 时传入，
      渲染"每个信号几点出现/几点消失"表格（当天全貌）。
    fade_timeline（2026-08-10 用户增量）：盘中模式 fade 通知时传入，附该信号
      当日在 signal_intraday_log 的出现细节（产生/通知时间 → 消失时点），
      与收盘全貌 timeline 分离。
    subject_signals：主题信号摘要用（预留，见 B1 说明；当前统一为与表体一致的去重新信号）。
    dedup_annotate（2026-08-14 告警优化 B1）：True 时正文统计行加"(当日去重后新信号 N 条)"，
      标注主题/正文统一为去重新信号口径。
    overview_markers / ai_suggest（#61 2026-08-17）：信号「回测宇宙+AI过滤+AI警示+AI建议」标记，
      由 main 从 overview.json 读入(load_overview_markers/build_ai_suggest_map)。None 时降级为
      不标注(兼容 test_feishu_post.py 直接调用 build_email 的旧签名)。
    """
    stats = load_signal_stats()
    om = overview_markers if overview_markers is not None else {}
    ai_sg = ai_suggest if ai_suggest is not None else {}

    # 按 signal 类型分组（buy / buy_aux / buy_special / buy_backup / sell / sell_stop_loss）
    groups = _group_signals(signals)
    subj_groups = _group_signals(subject_signals) if subject_signals is not None else groups

    n_total = len(signals)
    n_buy = len(groups["buy"])
    n_aux = len(groups["buy_aux"])
    n_special = len(groups["buy_special"])
    n_backup = len(groups["buy_backup"])
    n_sell = len(groups["sell"])
    n_stop_loss = len(groups["sell_stop_loss"])
    n_hold = len(groups["band_hold"])

    # === 标题：信号类型 + 品种摘要 ===
    # B1(2026-08-14)：主题与正文统一为"去重新信号"口径（subject_signals 当前恒为 None，
    #   subj_groups = groups = 去重 signals）。原"主题用当日全量/表体用去重"两口径无标注
    #   会误导，故统一；正文统计行加"(当日去重后新信号 N 条)"标注（见下方 dedup_annotate）。
    parts = []
    for sig_type in SIGNAL_ORDER:
        g = subj_groups[sig_type]
        label = _signal_label(sig_type)
        if g:
            summary = _summary_names(g, name_map, limit=3)
            parts.append(f"{label}×{len(g)} {summary}")
    # intraday 标注【盘中实时】前缀，收盘/历史不加（保持原"最终版"语义）
    title_prefix = "盘中实时·" if intraday else ""
    # fade-detect 警示存在时主题加 ⚠️ 前缀（2026-07-23 P1-新-A）；时间线存在时加 🕐 前缀
    fade_prefix = "⚠️ " if fade_alerts else ""
    timeline_prefix = "🕐 " if (timeline or fade_timeline) else ""
    # B3(2026-08-14)：去重新信号全为中性"波段持有"时，主题只反映实质 —— 不罗列全部
    #   买卖（会误导以为有买卖动作），改"仅波段持有(中性持有,无操作信号)"。
    _has_action = any(subj_groups[t] for t in SIGNAL_ORDER if t != "band_hold")
    if parts and not _has_action and subj_groups["band_hold"]:
        parts_str = "  仅波段持有(中性持有,无操作信号)"
    elif parts:
        parts_str = "  " + " | ".join(parts)
    elif timeline or fade_timeline:
        # P2-3(2026-08-17 修订)：时间线/盘中 fade 详情存在但当日信号空时，不再笼统报
        # 「信号均已消失」（可能只消失 1 条，误导以为全部信号都没了，尤其 sell 消失=
        # 减仓条件解除属利好）。改为反映实际 fade 条数+品种：sell 消失单独语义化
        # （与 _build_fade_banner 的 all_sell 语义一致）；fade_alerts 为空（如纯收盘时间线
        # 复盘）才退化为「信号均已消失（见时间线）」。fade 标题同口径见 build_feishu_post。
        if fade_alerts:
            _fade_names = "、".join(index_id_to_name(a["index_id"], name_map)
                                    for a in fade_alerts[:5])
            _fade_suffix = "等" if len(fade_alerts) > 5 else ""
            _has_sell = any(a.get("kind") == "sell" for a in fade_alerts)
            _all_sell = _has_sell and all(a.get("kind") == "sell" for a in fade_alerts)
            if _all_sell:
                parts_str = (f"  {_fade_names}{_fade_suffix} 减仓条件解除"
                             f"（{len(fade_alerts)} 条，见时间线）")
            else:
                parts_str = (f"  {len(fade_alerts)} 条信号消失/变化：{_fade_names}"
                             f"{_fade_suffix}（见时间线）")
        else:
            parts_str = "  信号均已消失（见时间线）"
    else:
        parts_str = "  无信号"
    subject = (f"{fade_prefix}{timeline_prefix}[{title_prefix}买卖点信号] {date}"
               f"{parts_str}")

    # === HTML 正文 ===
    # intraday 风险提示横幅：盘中快照非最终，信号可能随行情变化，收盘后 17:50 发最终版
    h2_title = "📊 盘中实时·买卖点信号" if intraday else "📊 买卖点信号日报"
    intraday_banner = ""
    if intraday:
        intraday_banner = (
            '<div style="background:#fff7e6;border:1px solid #ffd591;border-radius:6px;'
            'padding:10px 14px;margin:0 0 14px 0;font-size:13px;color:#d46b08;line-height:1.6;">'
            '<b>⚠️ 盘中实时快照</b>：本邮件基于盘中行情快照生成，<b>信号可能随后续行情变化</b>'
            '（如辅买信号消失/重现）。此为快照非最终，<b>收盘后 17:50 仍发送最终版邮件</b>，'
            '请以收盘最终版为准。</div>'
        )
    # B1(2026-08-14)：正文统计行加"(当日去重后新信号 N 条)"，标注主题/正文统一为去重新信号口径
    _dedup_note = f"（当日去重后新信号 {n_total} 条）" if dedup_annotate else ""
    html_parts = [f"""<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">{notify.MOBILE_EMAIL_CSS}</head><body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;font-size:14px;color:#1d2129;max-width:720px;">
<h2 style="margin:0 0 8px 0;color:#1d2129;">{h2_title}</h2>
<p style="margin:0 0 16px 0;color:#86909c;font-size:13px;">{date} · 共 <b>{n_total}</b> 个信号（主买 {n_buy} / 辅买 {n_aux} / 追买 {n_special} / 备买 {n_backup} / 卖 {n_sell} / 追止损卖 {n_stop_loss} / 波段持有 {n_hold}）{_dedup_note}</p>
{intraday_banner}"""]

    # fade-detect 警示横幅（红/橙/黄三档表格），放正文顶部 intraday 横幅之后（2026-07-23 P1-新-A）
    if fade_alerts:
        html_parts.append(_build_fade_banner(fade_alerts, name_map, intraday=intraday))

    # 盘中 fade 通知的时间线详情（2026-08-10 用户增量）：附 fade 信号前面的出现细节
    # （产生/通知时间 → 消失时点），免去翻历史邮件。仅盘中模式 fade_timeline 传入。
    if fade_timeline:
        html_parts.append(_build_fade_detail_html(
            fade_alerts or [], fade_timeline, name_map, datetime.now().strftime("%H:%M")))

    # 收盘全过程复现时间线（需求2 方案A，2026-08-10）：盘中每轮重算记录，
    # 收盘邮件展示每个信号几点出现/几点消失。放 fade 横幅之后、信号表之前。
    # #61(2026-08-17 用户修正): 时间线信号照常带 AI 标记列(与首页/盘中一致, 去重只发时间线也带)。
    if timeline:
        html_parts.append(_build_timeline_html(timeline, name_map, stats, om, ai_sg))

    if n_total == 0:
        if timeline or fade_timeline:
            html_parts.append('<p style="color:#86909c;">今日无新买卖点信号（已全部推送/消失），完整生命周期见上方时间线表格（信号行已带 AI 标记，与首页/盘中一致）。</p>')
        else:
            html_parts.append('<p style="color:#86909c;">今日无买卖点信号。</p>')
    else:
        # 信号表格（#61 2026-08-17 加「AI 标记」列: 回测宇宙/AI过滤/AI警示/AI建议, 与首页同口径）
        html_parts.append("""<table style="width:100%;border-collapse:collapse;font-size:13px;margin-bottom:16px;">
<thead><tr style="background:#f2f3f5;text-align:left;">
<th style="padding:8px 10px;border-bottom:2px solid #e5e6eb;">品种</th>
<th style="padding:8px 10px;border-bottom:2px solid #e5e6eb;width:48px;">类型</th>
<th style="padding:8px 10px;border-bottom:2px solid #e5e6eb;width:230px;">AI 标记</th>
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
                # #61: 算该信号标记 + 渲染徽标; 「AI建议N」行整行浅绿强化(在的强化展示), 其他正常
                _mk = _calc_signal_markers(s, om, stats, ai_sg)
                _badge = _signal_marker_badge_html(_mk)
                _ai_rank = _mk["ai_rank"]
                # 命中 AI 降亏(ai_fade)的信号行整行灰显弱化(对齐首页 .sig-ai-hit 删除线语义:
                #   opacity~0.45 + line-through), 徽标单元格 text-decoration:none 保留「AI降亏·建议回避」不被划掉
                if _mk["ai_fade"]:
                    _row_style = ' style="opacity:0.45;text-decoration:line-through;background:#f7f8fa;"'
                    _badge_td_extra = 'text-decoration:none;'
                elif _ai_rank is not None:
                    _row_style = ' style="background:#f6ffed;border-bottom:1px solid #b7eb8f;"'
                    _badge_td_extra = ''
                else:
                    _row_style = ''
                    _badge_td_extra = ''
                html_parts.append(f"""<tr{_row_style}>
<td style="padding:8px 10px;">{emoji} <b>{name}</b></td>
<td style="padding:8px 10px;font-size:12px;">{label}</td>
<td style="padding:8px 10px;font-size:11px;{_badge_td_extra}">{_badge}</td>
<td style="padding:8px 10px;font-size:12px;color:#4e5969;">{reason}</td>
<td style="padding:8px 10px;text-align:center;font-weight:600;color:{wr_color};">{wr_str}</td>
<td style="padding:8px 10px;text-align:center;">{pl_str}</td>
<td style="padding:8px 10px;text-align:center;font-size:12px;color:{kelly_color};">{kelly_str}</td>
</tr>""")

        html_parts.append("</tbody></table>")

    # 规则说明 + 免责
    html_parts.append(f"""<div style="background:#f7f8fa;border-radius:6px;padding:12px 16px;margin-bottom:12px;font-size:12px;color:#4e5969;line-height:1.8;">
<div style="font-weight:600;margin-bottom:4px;color:#1d2129;">📋 规则说明</div>
• 主买：RSI 上穿 30（超卖反弹启动）<br>
• 辅买：布林下轨回归（超卖反弹，强势市更敏感，互补主买盲区）<br>
• 追买：唐奇安20日上轨突破 + B4_hold5d 过滤（收盘价突破前20日最高价且延后5日站稳确认，激进战法高回撤高收益，趋势跟踪类）<br>
• 备买：Supertrend ATR(10)×3 翻多 + 二次确认过滤（延后3日收盘价确认仍站稳，趋势转向，与主买/辅买均值回归类互补，趋势跟踪类）<br>
• 卖：20 日高点回落 5% + MA60 多头过滤 + MACD 死叉确认（止盈减仓提示）<br>
• 追止损卖：A1 Donchian20 下轨止损（收盘价跌破前20日最低价，与追买上轨突破对称，独立止损卖点）<br>
• 波段持有：当前处于波段持有状态（无超买超卖触发，非买卖操作，中性持有信号，供参考持仓状态）<br>
• 附 RSI 当前值、综合情绪分金叉/死叉状态、相对前一买点盈亏标注
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


def _signal_post_row(s: dict, name_map: dict[str, str], stats: dict,
                     sig_type: str, om: dict | None = None,
                     ai_sg: dict | None = None) -> list[dict]:
    """单个信号 -> 飞书 post 一行（类型/品种/AI标记/触发条件摘要/凯利建议）。

    精简为一行：`{emoji} {类型} {品种}` + #61 AI 标记 + `| {触发条件摘要}` + 凯利建议（若有）；
    触发条件截断 FEISHU_POST_REASON_MAX 字符（完整在邮件）。
    om/ai_sg（#61）：overview 标记映射 + AI 建议 top-K 映射，None 时降级为不标注。
    """
    name = index_id_to_name(s["index_id"], name_map)
    label = _signal_label(sig_type)
    # post 版 emoji 与分组色一致（买红/卖绿/持有灰，A股红涨绿跌约定，与平台信号灯
    # buy 红 #e6492e / sell 绿 #2e8b57 一致），彩色语义用 emoji 前缀实现
    # （飞书 post text 标签不支持 style.color，实测 230001；见 notify.py 注释）
    if sig_type in FEISHU_POST_BUY_TYPES:
        emoji = "🔴"
    elif sig_type in FEISHU_POST_SELL_TYPES:
        emoji = "🟢"
    else:
        emoji = "⚪"
    reason = (s["reason"] or "").replace("\n", " ").replace("\r", " ").strip()
    if len(reason) > FEISHU_POST_REASON_MAX:
        reason = reason[:FEISHU_POST_REASON_MAX].rstrip() + "…"
    row_text = f"{emoji} {label} {name}"
    # #61: AI 标记文本(与邮件徽标内容一致, §23.10)。AI建议N 加 ⭐ 强化。
    _ai_fade = False
    if om is not None and ai_sg is not None:
        _mk = _calc_signal_markers(s, om, stats, ai_sg)
        _ai_fade = _mk["ai_fade"]
        _mt = _signal_marker_badge_text(_mk)
        if _mt:
            _star = "⭐" if _mk["ai_rank"] is not None else ""
            row_text += f" {_star}[{_mt}]"
    # 命中 AI 降亏(ai_fade)信号行弱化(对齐邮件灰显删除线/首页「AI降亏·建议回避」语义;
    #   飞书 post 纯文本不支持删除线, 用 ⛔ 建议回避 前缀弱化标注, 内容不删, §23.10/§23.3)
    if _ai_fade:
        row_text = f"⛔ 建议回避·{row_text}"
    if reason:
        row_text += f" | {reason}"
    # 凯利建议（复用邮件口径：10d 统计 win_rate/pl，样本≥10 才算）
    sub = stats.get(s["index_id"], {}).get(sig_type, {}).get("10d")
    wr = sub.get("win_rate") if sub else None
    pl = sub.get("pl") if sub else None
    n_s = sub.get("n") if sub else None
    if wr is not None and pl is not None and n_s is not None and n_s >= 10:
        kelly = calc_kelly(wr, pl)
        kelly_s = f"建议{kelly * 100:.0f}%" if kelly > 0 else "不建议入场"
        row_text += f" | 胜率{(wr or 0) * 100:.0f}% 盈亏比{pl:.2f} {kelly_s}"
    return [notify.post_text(row_text)]


def build_feishu_post(subject: str, signals: list[dict], name_map: dict[str, str],
                      intraday: bool = False,
                      fade_alerts: list[dict] | None = None,
                      fade_timeline: list[dict] | None = None,
                      overview_markers: dict | None = None,
                      ai_suggest: dict | None = None,
                      dedup_timeline_only: bool = False) -> dict:
    """构建飞书 post 富文本（报告群版，notify.send(feishu_post=...) 用）。

    按 buy(买)/sell(卖)/hold(波段持有) 分组：买红/卖绿/持有灰（彩色 emoji 前缀实现，
    飞书 post text 不支持 style.color，见 notify.py 注释）；分组表头用 md **加粗**。
    每个信号一行精简（类型/品种/#61 AI标记/触发条件摘要/凯利建议），不冗长；触发条件截断
    FEISHU_POST_REASON_MAX 字符；规则说明省略为一行指引（完整在邮件）。
    超 notify.FEISHU_POST_MAX_ROWS 行时由 send_feishu 分段连发（2026-08-16 用户定：
    放开行数+超长分段连发，标题带 N/M 序号，不省略行，和页面一致）。
    overview_markers / ai_suggest（#61 2026-08-17）：信号「回测宇宙+AI过滤+AI警示+AI建议」标记，
      由 main 从 overview.json 读入(load_overview_markers/build_ai_suggest_map)。None 时降级为
      不标注(兼容 test_feishu_post.py 直接调用 build_feishu_post 的旧签名)。
    """
    stats = load_signal_stats()
    om = overview_markers if overview_markers is not None else {}
    ai_sg = ai_suggest if ai_suggest is not None else {}
    groups = _group_signals(signals)
    n_buy = sum(len(groups[t]) for t in FEISHU_POST_BUY_TYPES)
    n_sell = sum(len(groups[t]) for t in FEISHU_POST_SELL_TYPES)
    n_hold = len(groups["band_hold"])

    lines: list[list[dict]] = []

    # 买入分组（🔴 A股红=买，与平台信号灯 buy 红 #e6492e 一致）
    if n_buy:
        sub = (f"（主买{len(groups['buy'])} 辅买{len(groups['buy_aux'])} "
               f"追买{len(groups['buy_special'])} 备买{len(groups['buy_backup'])}）")
        lines.append([notify.post_md(f"🔴 **买入信号**{sub}")])
        for sig_type in FEISHU_POST_BUY_TYPES:
            for s in groups[sig_type]:
                lines.append(_signal_post_row(s, name_map, stats, sig_type, om, ai_sg))
    # 卖出分组（🟢 A股绿=卖，与平台信号灯 sell 绿 #2e8b57 一致）
    if n_sell:
        sub = f"（卖{len(groups['sell'])} 追止损卖{len(groups['sell_stop_loss'])}）"
        lines.append([notify.post_md(f"🟢 **卖出信号**{sub}")])
        for sig_type in FEISHU_POST_SELL_TYPES:
            for s in groups[sig_type]:
                lines.append(_signal_post_row(s, name_map, stats, sig_type, om, ai_sg))
    # 波段持有（⚪）
    if n_hold:
        lines.append([notify.post_md(f"⚪ **波段持有**（{n_hold}）")])
        for s in groups["band_hold"]:
            lines.append(_signal_post_row(s, name_map, stats, "band_hold", om, ai_sg))

    # fade 警示：概要一行 + 每条 fade 附时间线明细（§23.10 飞书与邮件内容一致，不能少内容；
    # 与邮件 _build_fade_detail_html 同数据源 load_signal_intraday_timeline，格式可不同但内容对齐；
    # 超长由 send_feishu 按 FEISHU_POST_MAX_ROWS 自动分段连发，不省略明细行）。
    if fade_alerts:
        fade_n = len(fade_alerts)
        names = "、".join(index_id_to_name(a["index_id"], name_map) for a in fade_alerts[:5])
        suffix = "等" if fade_n > 5 else ""
        _has_sell = any(a.get("kind") == "sell" for a in fade_alerts)
        _all_sell = _has_sell and all(a.get("kind") == "sell" for a in fade_alerts)
        if _all_sell:
            lines.append([notify.post_md(
                f"✅ **卖出/减仓信号解除 {fade_n} 条**：{names}{suffix}（减仓条件解除，利好方向，见明细）")])
        else:
            lines.append([notify.post_md(
                f"⚠️ **信号消失/变化 {fade_n} 条**：{names}{suffix}（见明细）")])
        # 每条 fade 附时间线明细：品种 信号 出现→消失 触发条件（与邮件 fade 详情口径一致）
        fade_map = {}
        if fade_timeline:
            # 取最后一段（最近一次出现 → 本轮消失段），fade 通知不需要历史段（那是收盘时间线的活）
            for t in fade_timeline:
                fade_map[(t["index_id"], t["signal"])] = t
        for a in fade_alerts:
            _fname = index_id_to_name(a["index_id"], name_map)
            _flabel = _signal_label(a["intraday_signal"])
            # #61(2026-08-17 用户修正): 飞书 fade 明细信号照常带 AI 标记(回测宇宙/AI过滤/AI警示/
            #   AI建议 top-K, 与首页/盘中/邮件一致)。用户原话"只要推给用户的信号都要带上这个标记"。
            #   fade 的 intraday_signal 即当日信号, 用其算标记; AI建议 top-K 用 ai_rank 时加 ⭐。
            _fk = _calc_signal_markers(
                {"index_id": a["index_id"], "signal": a["intraday_signal"]}, om, stats, ai_sg)
            _fmt = _signal_marker_badge_text(_fk)
            _fstar = "⭐" if _fk["ai_rank"] is not None else ""
            _fmark = f" {_fstar}[{_fmt}]" if _fmt else ""
            # §23.10(2026-08-17 #61): 飞书 fade 明细补 suggestion(建议操作, 与邮件
            #   _build_fade_banner/_build_fade_detail_html 的建议列同字段), 飞书与邮件内容一致不精简。
            _sugg = (a.get("suggestion") or "").replace("\n", " ").replace("\r", " ").strip()
            _closing = (a.get("closing_status") or "").replace("\n", " ").replace("\r", " ").strip()
            _t = fade_map.get((a["index_id"], a["intraday_signal"]))
            if _t:
                _reason = (_t.get("reason") or "").replace("\n", " ").replace("\r", " ").strip()
                if len(_reason) > FEISHU_POST_REASON_MAX:
                    _reason = _reason[:FEISHU_POST_REASON_MAX].rstrip() + "…"
                _detail = (f"    {_flabel} {_fname}{_fmark}：{_t['appear_time']} 出现 → "
                           f"{_t['last_time']} 后消失")
                # §23.10(2026-08-17 #61): 飞书 fade 明细 timeline 分支补 closing_status(收盘状态,
                #   与邮件 _build_fade_banner 的 closing_status 列同字段), 飞书与邮件内容一致不精简。
                if _closing:
                    _detail += f" | 收盘状态：{_closing}"
                if _sugg:
                    _detail += f" | 建议：{_sugg}"
                if _reason:
                    _detail += f" | {_reason}"
            else:
                # 时间线无该信号记录（log 缺失/早于记录起点）：退化只展示 fade 状态
                _closing = (a.get("closing_status") or "").replace("\n", " ").replace("\r", " ").strip()
                _detail = f"    {_flabel} {_fname}{_fmark}：本轮检测消失"
                if _sugg:
                    _detail += f" | 建议：{_sugg}"
                if _closing:
                    _detail += f" | {_closing}"
            lines.append([notify.post_text(_detail)])

    # 超 80 行分段由 send_feishu 内部处理（2026-08-16 用户定：放开行数+超长分段连发，不省略）。
    # 此处不再截断省略尾部；完整 lines 交 build_feishu_post，send_feishu 按 FEISHU_POST_MAX_ROWS
    # 每段切分、多段连发（标题带 N/M 序号），杜绝丢「明细行」。

    # #61(2026-08-17 用户修正)：去重后只发时间线场景（dedup_timeline_only），信号照常带 AI 标记
    #   （回测宇宙/AI过滤/AI警示/AI建议 top-K，与首页/盘中/邮件一致）。用户原话"只要推给用户的
    #   信号都要带上这个标记"，故不再省略标记，也不加"不再重复标注"注（信号已带标记，注自相矛盾）。
    # 该分支 signals_to_send 为空（无新信号），信号仅以 fade 明细行形式呈现（上方 fade 循环已补标记）。

    # 规则说明省略为一行指引（完整在邮件；飞书 post 不支持折叠，故精简）
    lines.append([notify.post_text("📋 完整规则与免责见邮件 · 以收盘最终版为准")])

    title = subject.replace("[", "").replace("]", "").strip()
    if not title.startswith("📊"):
        title = "📊 " + title
    return notify.build_feishu_post(title, lines)


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
        "（盘中快照非最终，收盘 17:50 仍发最终版）。不走去重，仍用默认去重。",
    )
    parser.add_argument(
        "--fade-detect",
        action="store_true",
        default=None,
        dest="fade_detect",
        help="检测盘中信号消失/变化（收盘+盘中默认开，AZ54 P1-4 2026-07-29）。"
        "对比 signal_notified.json[date]（已推送）vs 当前 signal_daily[date]，"
        "buy* 系列消失/转 sell*/降级则邮件 ⚠️ 高亮警示。"
        "盘中模式：同日同 index_id|level 去重(fade_notified.json) + 只 red 档推邮件(orange/yellow 仅 log)。",
    )
    parser.add_argument(
        "--no-fade-detect",
        action="store_false",
        dest="fade_detect",
        help="显式关闭 fade-detect（收盘+盘中都不检测消失）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="dry-run：跑逻辑（含 fade-detect）但不发邮件、不写 signal_notified.json（测试用）",
    )
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="增量晚补模式（2026-08-14 P0-1）：backfill-evening 21:00 补采重算后调用。"
        "对比 signal_notified.json[date] 只补通知【当日新增/变化的迟到信号】"
        "（如 div_lowvol/gz_399431），跳过 fade-detect/时间线（那些在 18:42/20:40 主 check "
        "已覆盖，不重发）；幂等：当日已通知的 (index_id, signal) 跳过；无新信号不发邮件。",
    )
    args = parser.parse_args(argv)
    # fade-detect 默认值：收盘+盘中都默认开（AZ54 P1-4，2026-07-29）
    # 盘中模式去重(fade_notified.json)+阈值(只 red 档推邮件)见下方 fade_alerts_for_email 逻辑
    if args.fade_detect is None:
        args.fade_detect = True
    # 增量晚补模式：强制关闭 fade-detect——只针对性补通知新增/变化的迟到信号，
    # 不携带盘中消失警示/时间线复盘（那些属 18:42/20:40 主 check 已报内容，重发=噪音）。
    if args.incremental:
        args.fade_detect = False

    date = args.date or datetime.now().strftime("%Y%m%d")
    log.info(
        "=== check_signals 开始，查询日期：%s（%s模式%s%s%s）===",
        date,
        "全量" if args.full else "去重",
        "·盘中实时" if args.intraday else "",
        f"·fade-detect={'on' if args.fade_detect else 'off'}",
        "·增量晚补" if args.incremental else "",
    )

    signals = query_signals(date)
    # fade-detect：对比盘中 signal_notified.json[date] vs 收盘 signals，检测消失/变化。
    # signals 为 query_signals 返回的全量（含 band_hold 波段持有）；fade-detect 按 index_id
    # 聚合 closing 信号判定档位（band_hold 在 closing -> 非空 -> 不算"严格消失 red"）。
    # AZ54 P1-4（2026-07-29）：盘中模式也开 fade-detect，去重+阈值（只 red 档推邮件）。
    fade_alerts: list[dict] = []
    fade_alerts_for_email: list[dict] = []
    if args.fade_detect:
        fade_alerts = run_fade_detect(date, signals, intraday=args.intraday)
        if args.intraday:
            # 盘中阈值：只 red 档推邮件，orange/yellow 仅 log（10min 一轮波动大防轰炸）
            fade_alerts_for_email = [a for a in fade_alerts if a["level"] == "red"]
            if fade_alerts and not fade_alerts_for_email:
                log.info("fade-detect：盘中检测到 %d 条 fade（仅 orange/yellow），按阈值不发邮件",
                         len(fade_alerts))
        else:
            fade_alerts_for_email = fade_alerts

    # 盘中「消失即重置」（2026-08-18 用户原则）：信号消失(fade)时重置其已通知状态，
    # 再现时重新通知，无冷却。放在所有退出点之前（含 step3 无信号/step4 无新信号 return 0、
    # 以及发送成功段），确保盘中每轮 fade 都被处理。dry-run 不写文件。
    if args.intraday and fade_alerts and not args.dry_run:
        _reset_fade_notified(date, fade_alerts)

    # 时间线读取（signal_intraday_log → "信号几点出现/几点消失"），盘中/收盘两模式分离：
    # 收盘模式（非 intraday）：读当日全量时间线，展示当天全貌（需求2 方案A，2026-08-10）。
    # 盘中模式（--intraday，2026-08-10 用户增量）：仅当有 fade 警示要发邮件时读时间线，
    #   过滤出 fade 信号的出现细节（产生/通知时间 → 消失时点），附在 fade 通知邮件里；
    #   无 fade 要发邮件时不读（省 DB 查询，10min 一轮）。
    timeline: list[dict] = []
    fade_timeline: list[dict] = []
    if args.intraday:
        if fade_alerts_for_email:
            try:
                intraday_timeline = load_signal_intraday_timeline(date)
            except Exception as e:  # noqa: BLE001
                log.warning("signal_intraday_log 时间线读取失败（不阻断）：%s", e)
                intraday_timeline = []
            fade_keys = {(a["index_id"], a["intraday_signal"]) for a in fade_alerts_for_email}
            fade_timeline = [t for t in intraday_timeline
                             if (t["index_id"], t["signal"]) in fade_keys]
            log.info("盘中 fade 通知：读时间线 %d 条，匹配 fade 信号 %d 条",
                     len(intraday_timeline), len(fade_timeline))
    elif not args.incremental:
        # 增量晚补模式（--incremental）不读时间线：只针对补通知新增/变化的迟到信号，
        # 不携带当日全貌复盘（那些属 18:42/20:40 主 check 已报内容，重发=噪音）。
        try:
            timeline = load_signal_intraday_timeline(date)
        except Exception as e:  # noqa: BLE001
            log.warning("signal_intraday_log 时间线读取失败（不阻断）：%s", e)
            timeline = []

    # 方案B（2026-07-28 用户定）：补充完整展示所有信号状态（含 band_hold 波段持有），
    # 不再过滤 band_hold。SIGNAL_ORDER 已含 band_hold（第7类），邮件表格/统计/主题均展示。
    # 原 2026-07-28 盘中 bug（2 个 band_hold 致"共2信号但类型全0/表格空/主题无信号"矛盾）
    # 通过 SIGNAL_ORDER 加 band_hold 自然修复，不需过滤。

    if not signals and not fade_alerts_for_email and not timeline:
        log.info("今日（%s）无买卖点信号且无 fade 警示（red 档），不发邮件", date)
        return 0

    n_buy = sum(1 for s in signals if s["signal"] == "buy")
    n_aux = sum(1 for s in signals if s["signal"] == "buy_aux")
    n_special = sum(1 for s in signals if s["signal"] == "buy_special")
    n_backup = sum(1 for s in signals if s["signal"] == "buy_backup")
    n_sell = sum(1 for s in signals if s["signal"] == "sell")
    n_stop_loss = sum(1 for s in signals if s["signal"] == "sell_stop_loss")
    n_hold = sum(1 for s in signals if s["signal"] == "band_hold")
    log.info(
        "查询到 %d 个信号（主买=%d, 辅买=%d, 追买=%d, 备买=%d, 卖=%d, 追止损卖=%d, 波段持有=%d）",
        len(signals), n_buy, n_aux, n_special, n_backup, n_sell, n_stop_loss, n_hold,
    )

    name_map = load_name_map()
    # #61(2026-08-17): 读 overview.json 信号「回测宇宙+AI过滤」标记。exact(当天)优先, fallback
    #   (近 15 日同 index_id+signal)盘中降级; 标记缺失时 build_email/build_feishu_post 内部降级为
    #   该信号不标注(诚实不误标)。AI 建议 top-K 在 signals_to_send 确定后按当天展示信号单独算。
    #   读失败不阻塞整个流程(降级为不标注)。
    try:
        _exact, _fallback = load_overview_markers(date)
        _om = dict(_fallback); _om.update(_exact)  # 合并: exact 覆盖 fallback 同 key
        log.info("#61 信号标记: overview 当天 %d 条 / 近15日 %d 条", len(_exact), len(_fallback))
    except Exception as e:  # noqa: BLE001
        log.warning("#61 overview 标记加载异常（降级为不标注）：%s", e)
        _om = {}
    # A12 订阅推送（2026-07-24 P2-新-K）：独立于全局推送，用全部 signals（不去重），
    # 每订阅用 subs_notified.json 独立去重。放在 name_map 加载后、全局推送流程之前，
    # 保证退出点 2/3/4（无新信号/dry-run/全局推送失败）也执行，订阅者能收到匹配信号。
    # 失败不阻塞全局推送（push_subscriptions 内部 try/except 兜底）。
    try:
        push_subscriptions(signals, name_map, date,
                           intraday=args.intraday, dry_run=args.dry_run,
                           overview_markers=_om)
    except Exception as e:  # noqa: BLE001
        log.error("A12 订阅推送异常：%s（不阻塞全局推送）", e)
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
            extra = []
            if fade_alerts_for_email:
                extra.append(f"{len(fade_alerts_for_email)} 条 fade 警示")
            if timeline:
                extra.append(f"{len(timeline)} 条信号时间线")
            if extra:
                # A5(2026-08-14)：盘中模式 n_total==0 且仅 fade/timeline 时不发邮件。
                # 盘中信号反复出现/消失属常态，当前无任何信号时 fade/时间线通知成噪音。
                # 保留收盘版正常发信（收盘 fade/时间线是重要复盘信息）。
                if args.intraday and not signals:
                    log.info("盘中模式：当前无信号(n_total=0)且仅 fade/timeline，不发邮件(A5)")
                    return 0
                log.info("无新信号（已去重），但有 %s，仍发邮件", " + ".join(extra))
            else:
                log.info("无新信号（已去重），不发邮件")
                return 0
    # B1(2026-08-14)：主题与正文统一为"去重新信号"口径。subject_signals 恒传 None
    #   （不再用当日全量 signals），避免主题/正文两口径无标注误导；正文统计行加
    #   "(当日去重后新信号 N 条)"标注（dedup_annotate）。--full 全量模式不加该标注。
    # B1 修复(2026-08-14 reviewer FAIL)：收盘时间线邮件（timeline 非空=当日全貌复盘）主题
    #   恢复"当日全量"口径（subject_signals=signals）。0 新信号日（signals_to_send 为空）但
    #   当日有信号已推送时，原主题误标"信号均已消失"（事实错误，信号已推送非消失）；
    #   改传当日全量 signals 让主题呈现"追买×2...|卖×4..."当日汇总。timeline 为空时仍走
    #   去重新信号口径（subject_signals=None）。build_email 内 elif timeline 分支（parts 空）
    #   仅当日 signals 真为空（信号全部消失）时才触发"信号均已消失"，语义正确。
    subject_signals = signals if timeline else None
    # #61: 对本邮件要展示的 signals_to_send 算 K=1 AI 建议 top-K(展示范围内谁最优, 与邮件对应)
    _ai_suggest = build_ai_suggest_map(signals_to_send, _om, load_signal_stats())
    log.info("#61 AI 建议 top-K(展示 %d 信号): %d 条入样买入候选, top1=%s",
             len(signals_to_send), sum(1 for _s in signals_to_send
             if _s.get("signal") not in ("band_hold", "sell", "sell_stop_loss")
             and _om.get((_s["index_id"], _s["signal"]), {}).get("_bt_in_universe") is not False
             and not _om.get((_s["index_id"], _s["signal"]), {}).get("ai_macro", {}).get("hit")),
             next(iter(_ai_suggest), None))
    subject, body = build_email(date, signals_to_send, name_map,
                                intraday=args.intraday, fade_alerts=fade_alerts_for_email,
                                timeline=timeline, fade_timeline=fade_timeline,
                                subject_signals=subject_signals,
                                dedup_annotate=(not args.full),
                                overview_markers=_om, ai_suggest=_ai_suggest)
    # 飞书 post 富文本（报告群版）：buy/sell 分组 + 彩色，替代 _html_to_text 拍平成纯文本
    # dedup_timeline_only（2026-08-17）：去重后无新增信号、只发时间线复盘时 True，
    #   build_feishu_post 加注明（§23.10 与邮件一致）。
    feishu_post = build_feishu_post(subject, signals_to_send, name_map,
                                    intraday=args.intraday,
                                    fade_alerts=fade_alerts_for_email,
                                    fade_timeline=fade_timeline,
                                    overview_markers=_om, ai_suggest=_ai_suggest,
                                    dedup_timeline_only=(not args.full)
                                    and (not signals_to_send) and bool(timeline))
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
        results = notify.send(subject, body, from_prefix="[买卖点信号]",
                              feishu_post=feishu_post)
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
    # 盘中「再现即清 fade 去重」：本次发送的信号=再现（或新出现），清其 fade_notified
    #   （同根因：去重状态阻断循环动作通知），下次再消失能再发 fade 通知（用户原则 2026-08-18
    #   「出现→消失→再现→再消失…无限循环，每个动作都通知」）。与上面 _reset_fade_notified 对称。
    if args.intraday and signals_to_send:
        _clear_fade_dedup_for_reappear(date, signals_to_send)
    log.info(
        "已更新 signal_notified.json：当日已通知 %d 条（%s）",
        len(notified[date]),
        "全量" if args.full else "增量",
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
