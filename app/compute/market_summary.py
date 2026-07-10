"""一句话市场总结：规则引擎生成每日市场摘要。

读取当日所有可用数据，生成一段话总结，散户型用户扫一眼概览即可了解当日行情。
数据源：情绪分、恐贪指数、涨跌家数、成交额、涨跌停、主要指数、买卖点、新高新低、均线排列。
"""

from ..db import get_conn
from ..calendar import last_trading_day
import datetime as dt


def _sentiment_desc(score: float) -> str:
    """情绪分 → 描述。"""
    if score <= 20:
        return "极度悲观"
    elif score <= 35:
        return "情绪低迷"
    elif score <= 45:
        return "偏谨慎"
    elif score <= 55:
        return "情绪平稳"
    elif score <= 70:
        return "情绪回暖"
    elif score <= 85:
        return "乐观积极"
    else:
        return "情绪亢奋"


def _volume_desc(amount: float, avg_amount: float) -> str:
    """成交额对比近5日均值 → 量能描述。"""
    if avg_amount <= 0:
        return "量能未知"
    ratio = amount / avg_amount
    if ratio >= 1.3:
        return "显著放量"
    elif ratio >= 1.1:
        return "温和放量"
    elif ratio <= 0.7:
        return "显著缩量"
    elif ratio <= 0.9:
        return "温和缩量"
    else:
        return "量能平稳"


def _pct_sign(v: float) -> str:
    return "+" if v >= 0 else ""


def generate_summary(date: str | None = None) -> dict:
    """生成一句话市场总结。

    参数:
        date: 目标日期 (YYYYMMDD)，默认最新交易日

    返回:
        {date, summary, summary_short, sentiment_label, sentiment_score,
         fear_greed_value, fear_greed_label, volume_label, sh_pct,
         up_count, down_count, zt_count, dt_count, buy_count, sell_count,
         nh_count, nl_count, ma_bullish, ma_bearish, top_industries: [...]}
    """
    conn = get_conn()

    if date is None:
        date = last_trading_day()

    # 若该日尚无情绪分数据（今天还没跑），回退到最近有 a_sentiment 的日期。
    # 这样保证一句话总结基于"最近有数据"的交易日，而非空数据的今天。
    if conn.execute(
        "SELECT 1 FROM score_daily WHERE score_id='a_sentiment' AND date=?",
        (date,),
    ).fetchone() is None:
        latest = conn.execute(
            "SELECT date FROM score_daily WHERE score_id='a_sentiment' ORDER BY date DESC LIMIT 1"
        ).fetchone()
        if latest:
            date = latest["date"]

    # ---- 1. 情绪分 + 恐贪指数 ----
    score_row = conn.execute(
        "SELECT value FROM score_daily WHERE score_id='a_sentiment' AND date=?",
        (date,),
    ).fetchone()
    sentiment_score = score_row["value"] if score_row else None
    sentiment_desc_str = _sentiment_desc(sentiment_score) if sentiment_score is not None else "情绪未知"

    fg_row = conn.execute(
        "SELECT value FROM score_daily WHERE score_id='fear_greed' AND date=?",
        (date,),
    ).fetchone()
    fg_value = fg_row["value"] if fg_row else None
    fg_label = ""
    if fg_value is not None:
        if fg_value <= 25:
            fg_label = "极度恐惧"
        elif fg_value <= 40:
            fg_label = "恐惧"
        elif fg_value <= 60:
            fg_label = "中性"
        elif fg_value <= 75:
            fg_label = "贪婪"
        else:
            fg_label = "极度贪婪"

    # 冰点检查
    freeze_row = conn.execute(
        "SELECT score_id, value FROM score_daily WHERE date=? AND is_freeze=1",
        (date,),
    ).fetchone()
    is_freeze = freeze_row is not None
    freeze_info = f"❗{freeze_row['score_id']}情绪冰点({freeze_row['value']:.0f}分)" if freeze_row else ""

    # ---- 2. 上证指数涨跌 ----
    sh_row = conn.execute(
        "SELECT pct_change, close FROM index_daily WHERE index_id='sh' AND date=?",
        (date,),
    ).fetchone()
    sh_pct = sh_row["pct_change"] if sh_row else None
    sh_close = sh_row["close"] if sh_row else None
    direction = "涨" if (sh_pct or 0) >= 0 else "跌"

    # ---- 3. 涨跌家数 + 涨停跌停 ----
    up_row = conn.execute(
        "SELECT value FROM daily_metric WHERE metric_id='a_width_up_count' AND date=?",
        (date,),
    ).fetchone()
    down_row = conn.execute(
        "SELECT value FROM daily_metric WHERE metric_id='a_width_down_count' AND date=?",
        (date,),
    ).fetchone()
    up_count = int(up_row["value"]) if up_row and up_row["value"] is not None else 0
    down_count = int(down_row["value"]) if down_row and down_row["value"] is not None else 0
    total = up_count + down_count

    if total > 0:
        up_ratio = up_count / total
        if up_ratio >= 0.8:
            width_desc = "普涨"
        elif up_ratio >= 0.6:
            width_desc = "多数上涨"
        elif up_ratio >= 0.4:
            width_desc = "涨跌互现"
        elif up_ratio >= 0.2:
            width_desc = "多数下跌"
        else:
            width_desc = "普跌"
    else:
        width_desc = "涨跌未知"

    zt_row = conn.execute(
        "SELECT value FROM daily_metric WHERE metric_id='a_zt_count' AND date=?",
        (date,),
    ).fetchone()
    dt_row = conn.execute(
        "SELECT value FROM daily_metric WHERE metric_id='a_dt_count' AND date=?",
        (date,),
    ).fetchone()
    zt_count = int(zt_row["value"]) if zt_row and zt_row["value"] is not None else 0
    dt_count = int(dt_row["value"]) if dt_row and dt_row["value"] is not None else 0

    # ---- 4. 成交额量能 ----
    amount_row = conn.execute(
        "SELECT value FROM daily_metric WHERE metric_id='a_amount' AND date=?",
        (date,),
    ).fetchone()
    amount = amount_row["value"] if amount_row else None

    avg_rows = conn.execute(
        "SELECT value FROM daily_metric WHERE metric_id='a_amount' AND date < ? "
        "ORDER BY date DESC LIMIT 5",
        (date,),
    ).fetchall()
    avg_amount = 0.0
    if avg_rows:
        avg_amount = sum(r["value"] for r in avg_rows if r["value"]) / len(avg_rows)

    vol_label = _volume_desc(amount, avg_amount) if amount else "成交额未知"
    vol_display = f"{amount:.0f}亿" if amount else ""

    # ---- 5. 买卖点信号 ----
    buy_count = conn.execute(
        "SELECT COUNT(*) as n FROM signal_daily WHERE date=? AND signal='buy'",
        (date,),
    ).fetchone()["n"]
    buy_aux_count = conn.execute(
        "SELECT COUNT(*) as n FROM signal_daily WHERE date=? AND signal='buy_aux'",
        (date,),
    ).fetchone()["n"]
    sell_count = conn.execute(
        "SELECT COUNT(*) as n FROM signal_daily WHERE date=? AND signal='sell'",
        (date,),
    ).fetchone()["n"]
    total_buy = (buy_count or 0) + (buy_aux_count or 0)
    sell_n = sell_count or 0

    signal_desc = ""
    if total_buy > 0 and sell_n > 0:
        signal_desc = f"共{total_buy}个买点、{sell_n}个卖点"
    elif total_buy > 0:
        signal_desc = f"出现{total_buy}个买点信号，无卖点"
    elif sell_n > 0:
        signal_desc = f"出现{sell_n}个卖点信号，无买点"

    # ---- 6. 新高新低 ----
    nhnl_row = conn.execute(
        "SELECT value FROM daily_metric WHERE metric_id='a_nhnl_52w' AND date=?",
        (date,),
    ).fetchone()
    nh_row = conn.execute(
        "SELECT value FROM daily_metric WHERE metric_id='a_nh_52w' AND date=?",
        (date,),
    ).fetchone()
    nl_row = conn.execute(
        "SELECT value FROM daily_metric WHERE metric_id='a_nl_52w' AND date=?",
        (date,),
    ).fetchone()
    nhnl = int(nhnl_row["value"]) if nhnl_row and nhnl_row["value"] is not None else 0
    nh = int(nh_row["value"]) if nh_row and nh_row["value"] is not None else 0
    nl = int(nl_row["value"]) if nl_row and nl_row["value"] is not None else 0

    nhnl_desc = ""
    if nh > 0 and nl == 0:
        nhnl_desc = f"{nh}个指数创年度新高，市场内在强势"
    elif nl > 0 and nh == 0:
        nhnl_desc = f"{nl}个指数创年度新低，市场内在偏弱"
    elif nh > 0 and nl > 0:
        nhnl_desc = f"{nh}创年度新高、{nl}创年度新低，分化明显"
    elif nhnl == 0 and nh == 0 and nl == 0:
        nhnl_desc = "无指数创年度新高/新低"

    # ---- 7. 均线排列 ----
    bullish_row = conn.execute(
        "SELECT value FROM daily_metric WHERE metric_id='a_ma_bullish' AND date=?",
        (date,),
    ).fetchone()
    bearish_row = conn.execute(
        "SELECT value FROM daily_metric WHERE metric_id='a_ma_bearish' AND date=?",
        (date,),
    ).fetchone()
    ma_bullish = int(bullish_row["value"]) if bullish_row and bullish_row["value"] is not None else 0
    ma_bearish = int(bearish_row["value"]) if bearish_row and bearish_row["value"] is not None else 0

    ma_desc = ""
    if ma_bullish >= 6:
        ma_desc = "主要指数多数处于多头排列，趋势向好"
    elif ma_bearish >= 6:
        ma_desc = "主要指数多数处于空头排列，趋势偏弱"
    elif ma_bullish > ma_bearish:
        ma_desc = f"{ma_bullish}个多头、{ma_bearish}个空头，偏多震荡"
    elif ma_bearish > ma_bullish:
        ma_desc = f"{ma_bullish}个多头、{ma_bearish}个空头，偏空震荡"
    else:
        ma_desc = "多空均势，方向不明"

    # ---- 8. 热点板块（取当日涨幅最大的前3个行业）----
    from ..collector.fetchers import load_config
    cfg = load_config()
    idx_name_map = {i["id"]: i["name"] for i in cfg.get("indices", []) if i.get("enabled", True)}
    top_industries = []
    ind_rows = conn.execute(
        "SELECT index_id, pct_change FROM index_daily "
        "WHERE date=? AND index_id LIKE 'sw_%' AND pct_change IS NOT NULL "
        "ORDER BY pct_change DESC LIMIT 3",
        (date,),
    ).fetchall()
    for r in ind_rows:
        code = r["index_id"][3:] if r["index_id"].startswith("sw_") else r["index_id"]
        top_industries.append({
            "code": code,
            "index_id": r["index_id"],
            "name": idx_name_map.get(r["index_id"], r["index_id"]),
            "pct_change": r["pct_change"],
        })

    conn.close()

    # ---- 构建总结文案 ----
    hot_names = "、".join([i["name"].replace("SW ", "") for i in top_industries]) if top_industries else "无明显热点板块"

    # 日期前缀用具体日期替代"今日"，避免盘中/回退日文案误导（用户不知实际数据日）。
    # generated_at 区分盘中快照（date=今天且 15:00 前未收盘）/ 收盘分析，明确数据时效。
    date_prefix = f"{int(date[4:6])}月{int(date[6:8])}日"
    _now = dt.datetime.now()
    if date == _now.strftime("%Y%m%d") and _now.hour < 15:
        generated_at = f"{date_prefix} 盘中快照（截至{_now.hour}:{_now.minute:02d}）"
    else:
        generated_at = f"{date_prefix} 收盘分析"

    # 一句话短版（概览横幅）
    summary_short = (
        f"{date_prefix}A股{sentiment_desc_str}，上证{direction}{abs(sh_pct or 0):.2f}%，"
        f"{width_desc}（{up_count}涨{down_count}跌），"
        f"成交额{vol_display}（{vol_label}）。"
        f"热点：{hot_names}"
    )

    # 段落长版（含更多分析维度）
    parts = []
    parts.append(f"{date_prefix}A股{sentiment_desc_str}")
    if fg_value is not None:
        parts[0] += f"（恐贪指数{fg_value:.0f}，{fg_label}）"
    parts[0] += "。"

    parts.append(f"上证指数{direction}{abs(sh_pct or 0):.2f}%至{sh_close:.0f}点，{width_desc}（{up_count}家上涨、{down_count}家下跌）" if sh_close else f"上证指数{direction}{abs(sh_pct or 0):.2f}%，{width_desc}（{up_count}家上涨、{down_count}家下跌）")
    if zt_count > 0 or dt_count > 0:
        parts[1] += f"，涨停{zt_count}家、跌停{dt_count}家"
    parts[1] += "。"

    parts.append(f"成交额{vol_display}，{vol_label}。")

    if signal_desc:
        parts.append(f"{signal_desc}。")

    if nhnl_desc:
        parts.append(f"{nhnl_desc}。")

    parts.append(f"{ma_desc}。")

    if hot_names:
        parts.append(f"领涨板块：{hot_names}。")

    if freeze_info:
        parts.append(freeze_info)

    summary = "".join(parts)

    return {
        "date": date,
        "generated_at": generated_at,
        "summary": summary,
        "summary_short": summary_short,
        "sentiment_label": sentiment_desc_str,
        "sentiment_score": sentiment_score,
        "fear_greed_value": fg_value,
        "fear_greed_label": fg_label,
        "is_freeze": is_freeze,
        "freeze_info": freeze_info,
        "volume_label": vol_label,
        "volume_amount": amount,
        "sh_pct": sh_pct,
        "sh_close": sh_close,
        "up_count": up_count,
        "down_count": down_count,
        "zt_count": zt_count,
        "dt_count": dt_count,
        "buy_count": total_buy,
        "sell_count": sell_n,
        "nh_count": nh,
        "nl_count": nl,
        "nhnl": nhnl,
        "ma_bullish": ma_bullish,
        "ma_bearish": ma_bearish,
        "top_industries": top_industries,
    }


# 弹窗历史列表展示用的精简字段（去掉 top_industries 等大字段，省 JSON 体积）。
BRIEF_FIELDS = (
    "date", "generated_at", "summary", "summary_short",
    "sentiment_label", "sentiment_score",
    "fear_greed_value", "fear_greed_label", "is_freeze",
    "sh_pct", "up_count", "down_count",
    "zt_count", "dt_count", "buy_count", "sell_count",
)


def summary_brief(s: dict) -> dict:
    """从 generate_summary 完整结果取弹窗展示用精简字段。"""
    return {k: s.get(k) for k in BRIEF_FIELDS}