"""HC18: USD/CNH source contracts; legacy rows stay untouched.

Realtime quotes and provider-labelled daily closes are separate datasets. Sina's
public day API does not document the close timezone: staged history is NOT an
active signal input, even when enough rows have accumulated.
"""
import hashlib
import json
import math
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Shanghai")
FX_CODE = "fx_susdcnh"
QUOTE_VERSION = "sina-cnh-quote-v1"
DAY_VERSION = "sina-cnh-day-candidate-v1"
QUOTE_METRIC = "usdcnh.sina_quote.v1"
DAY_METRIC = "usdcnh.sina_day_candidate.v1"
SCORE_VERSION = "fx-excluded-v1"
DEPENDENT_SCORES = ("cross_market", "fear_greed", "high_alert", "low_alert")
ACTIVE_SIGNAL_SQL = "index_id NOT IN ('g.usdcnh','s.cross_market','s.fear_greed')"
UNAVAILABLE = "离岸人民币 USD/CNH 指标不可用：旧历史口径未验证；同口径日线待重建，暂不参与信号和评分。独立实时行情仅供参考。"
DAY_URL = "https://vip.stock.finance.sina.com.cn/forex/api/jsonp.php/fx_history/NewForexService.getDayKLine?symbol=fx_susdcnh"
QUOTE_CONTRACT = dict(instrument_id="USD/CNH", base_currency="USD", quote_currency="CNH",
                      base_amount=1, price_type="provider_latest", source_id="sina:fx_susdcnh",
                      contract_version=QUOTE_VERSION, source_timezone="Asia/Shanghai")
DAY_CONTRACT = dict(instrument_id="USD/CNH", base_currency="USD", quote_currency="CNH",
                    base_amount=1, price_type="provider_daily_close", source_id="sina:NewForexService.getDayKLine:fx_susdcnh",
                    contract_version=DAY_VERSION, source_timezone="unverified", as_of_precision="day")


def _number(value):
    if isinstance(value, bool):
        raise ValueError("invalid_price")
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError("invalid_price")
    return value


def parse_quote(text):
    for line in text.splitlines():
        match = re.fullmatch(r'\s*var hq_str_fx_susdcnh="([^"\n]*)";?\s*', line)
        if not match:
            continue
        fields = match[1].split(",")
        try:
            if len(fields) < 18 or fields[9].strip() != "离岸人民币（香港）":
                return None
            stamp = datetime.strptime(fields[17] + " " + fields[0], "%Y-%m-%d %H:%M:%S").replace(tzinfo=TZ)
            price, previous = _number(fields[8]), _number(fields[3])
            return dict(QUOTE_CONTRACT, code=FX_CODE, name=fields[9], price=price,
                        pre_close=previous, change=price-previous, pct_change=(price/previous-1)*100,
                        datetime=stamp.strftime("%Y%m%d"), as_of=stamp.isoformat())
        except (ValueError, TypeError, IndexError):
            return None
    return None


def validate_quote(quote, now=None):
    now = now or datetime.now(TZ)
    if now.tzinfo is None:
        raise ValueError("timezone_required")
    if not isinstance(quote, dict) or any(quote.get(k) != v for k, v in QUOTE_CONTRACT.items()):
        raise ValueError("fx_contract_mismatch")
    if quote.get("code") != FX_CODE or quote.get("name") != "离岸人民币（香港）":
        raise ValueError("instrument_mismatch")
    stamp = datetime.fromisoformat(quote["as_of"])
    if stamp.tzinfo is None or stamp.utcoffset() != timedelta(hours=8):
        raise ValueError("source_timezone_mismatch")
    age = (now - stamp).total_seconds()
    if stamp.date() != now.astimezone(TZ).date() or not 0 <= age <= 900:
        raise ValueError("source_stale_or_future")
    if quote.get("datetime") != stamp.strftime("%Y%m%d"):
        raise ValueError("source_date_mismatch")
    _number(quote["price"])
    _number(quote["pre_close"])
    return stamp.strftime("%Y%m%d")


def store_quote(conn, quote, now=None):
    """Only the isolated quote metric can be written; never legacy usdcnh."""
    day = validate_quote(quote, now)
    source = json.dumps({k: quote[k] for k in (*QUOTE_CONTRACT, "as_of", "code", "name")}, ensure_ascii=False, sort_keys=True)
    old = conn.execute("SELECT source FROM daily_metric WHERE metric_id=? AND date=?", (QUOTE_METRIC, day)).fetchone()
    if old:
        old_source = json.loads(old[0])
        if old_source["as_of"] > quote["as_of"]:
            return 0
    conn.execute("INSERT INTO daily_metric(date,metric_id,value,source,updated_at) VALUES(?,?,?,?,?) "
                 "ON CONFLICT(date,metric_id) DO UPDATE SET value=excluded.value,source=excluded.source,updated_at=excluded.updated_at "
                 "WHERE json_extract(excluded.source, '$.as_of') > json_extract(daily_metric.source, '$.as_of')",
                 (day, QUOTE_METRIC, quote["price"], source, quote["as_of"]))
    changed = conn.execute("SELECT changes()").fetchone()[0]
    conn.commit()
    return changed


def parse_day_candidate(text, *, source_url, fetched_at):
    """Strict first-party wire format, no eval, no made-up close timestamp."""
    if source_url != DAY_URL or fetched_at.tzinfo is None:
        raise ValueError("source_missing_or_mismatch")
    match = re.fullmatch(r"(?:/\*.*?\*/\s*)?fx_history\((\"[^\n]*\")\);?\s*", text, re.S)
    if not match:
        raise ValueError("invalid_day_payload")
    payload = json.loads(match[1])
    digest = hashlib.sha256(text.encode()).hexdigest()
    result, excluded_dates = [], []
    dates = set()
    for record in payload.split("|"):
        fields = record.split(",")
        if len(fields) not in (5, 6):
            raise ValueError("invalid_day_fields")
        day = datetime.strptime(fields[0], "%Y-%m-%d").date()
        if day > fetched_at.astimezone(TZ).date() or fields[0] in dates:
            raise ValueError("future_or_duplicate_day")
        op, low, high, close = map(_number, fields[1:5])
        if not low <= min(op, close) <= max(op, close) <= high:
            raise ValueError("invalid_ohlc")
        dates.add(fields[0])
        if day == fetched_at.astimezone(TZ).date():
            excluded_dates.append({"date": fields[0], "reason": "current_day_unfinished"})
            continue
        result.append(dict(DAY_CONTRACT, date=day.strftime("%Y%m%d"), value=close,
                           as_of=fields[0], source_url=source_url, fetched_at=fetched_at.isoformat(), payload_sha256=digest))
    return {"rows": sorted(result, key=lambda r: r["date"]), "excluded_dates": excluded_dates}


def _validate_day_row(row):
    if not isinstance(row, dict) or any(row.get(k) != v for k, v in DAY_CONTRACT.items()):
        raise ValueError("day_contract_mismatch")
    if row.get("source_url") != DAY_URL or not re.fullmatch(r"[0-9a-f]{64}", row.get("payload_sha256", "")):
        raise ValueError("day_source_missing")
    day = datetime.strptime(row["as_of"], "%Y-%m-%d").strftime("%Y%m%d")
    if day != row["date"]:
        raise ValueError("day_mismatch")
    fetched = datetime.fromisoformat(row["fetched_at"])
    if fetched.tzinfo is None or day >= fetched.astimezone(TZ).strftime("%Y%m%d"):
        raise ValueError("unfinished_day")
    value = _number(row["value"])
    return day, value


def stage_day_history(conn, rows):
    """Atomic, idempotent import into a candidate metric; conflicts reject batch."""
    staged = []
    for row in rows:
        day, value = _validate_day_row(row)
        staged.append((day, DAY_METRIC, value, json.dumps(row, ensure_ascii=False, sort_keys=True), row["fetched_at"]))
    with conn:
        for row in staged:
            conn.execute("INSERT OR IGNORE INTO daily_metric(date,metric_id,value,source,updated_at) VALUES(?,?,?,?,?)", row)
            old = conn.execute("SELECT value FROM daily_metric WHERE date=? AND metric_id=?", row[:2]).fetchone()
            if old[0] != row[2]:
                raise ValueError("history_conflict")
    return candidate_status(conn)


def candidate_status(conn):
    rows = conn.execute("SELECT date,value,source FROM daily_metric WHERE metric_id=? ORDER BY date", (DAY_METRIC,)).fetchall()
    valid = []
    for day, value, source in rows:
        try:
            meta = json.loads(source)
            source_day, source_value = _validate_day_row(meta)
            if source_day != day or source_value != value:
                raise ValueError("contract_mismatch")
            _number(value)
            valid.append(day)
        except (ValueError, TypeError, KeyError):
            return dict(status="invalid_candidate", count=0, active=False)
    # Sample sufficiency is distinct from activation; long missing spans reset warmup.
    trailing = 0
    previous = None
    for day in valid:
        current = datetime.strptime(day, "%Y%m%d")
        trailing = trailing + 1 if previous is None or (current - previous).days <= 7 else 1
        previous = current
    return dict(status="staged", count=len(valid), contiguous_count=trailing, last_source_day=valid[-1] if valid else None,
                windows={str(n): trailing >= n for n in (20, 60, 90, 120)}, active=False,
                reason="daily_close_timezone_unverified")


def availability():
    return dict(status="unavailable", reason="history_contract_unverified", message=UNAVAILABLE,
                instrument_id="USD/CNH", base_amount=1, quote_currency="CNH", active=False)


def filter_signals(rows):
    # Keep the raw DB/history intact. Cross-market values in old index reasons
    # were soft annotations, not trade triggers; do not show their stale numbers.
    out = []
    for row in rows:
        r = dict(row)
        if r["index_id"] == "g.usdcnh":
            continue
        if r["index_id"] in ("s.cross_market", "s.fear_greed"):
            # No active complete FX contract exists yet, including old marked rows.
            continue
        if isinstance(r.get("reason"), str):
            r["reason"] = re.sub(r",?情绪分=[+-]?[0-9.]+\[[^]]*\]", "", r["reason"])
        out.append(r)
    return out


def guard_score(row):
    """Mask previously persisted cross-market scores without rewriting history."""
    row = dict(row)
    comp = row.get("components")
    try:
        comp = json.loads(comp) if isinstance(comp, str) else comp
    except ValueError:
        comp = None
    if not isinstance(comp, dict) or comp.get("_fx_contract") != SCORE_VERSION or comp.get("_fx_available") is not True:
        row.update(value=None, is_freeze=None, is_overheat=None, components=None, availability="unavailable", unavailable_reason="FX历史合同未验证；评分缺维不可用")
    return row
