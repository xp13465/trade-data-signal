"""盘中实时快照采集（方案 A 后端）。

解决收盘后 pipeline 拿不到当日指数（上证 0%）的问题：盘中直采腾讯实时行情 +
同花顺行业实时涨跌幅，存 DB + dump 静态 JSON，供前端"盘中实时小结"展示。

- 9 指数实时：腾讯 qt.gtimg.cn（主），新浪 hq.sinajs.cn（逐个降级备）。
- 31 申万一级行业实时涨跌幅：复用同花顺 stock_board_industry_summary_ths（90 子行业），
  通过 THS_TO_SW 聚合（涨跌幅按成交额加权、净流入求和、领涨股取涨幅最高子行业）。
- is_market_closed：本地时间判断盘中区间（9:30-11:30/13:00-15:00 交易日）。
- **指数反哺**：采集完 9 指数后，把当日 OHLC 写入 index_daily 表（UPSERT），
  触发重算 per-index 情绪分 + 恐贪指数 + dump 静态 JSON，
  使指数卡片/恐贪/per-index 情绪分到当日（解决 T+1 延迟致停在 T-2 的问题）。
  非交易日不反哺；快照 datetime 非当日不写（避免旧快照污染）。
"""
import json
import time
from datetime import datetime
from pathlib import Path

import requests

from ..db import get_conn
from .base import UA, throttle
from .industry_extras import THS_TO_SW

# 9 核心指数（代码 -> 名称兜底，实际 name 取源返回）
INDEX_CODES = [
    "sh000001",  # 上证指数
    "sz399001",  # 深证成指
    "sh000300",  # 沪深300
    "sh000016",  # 上证50
    "sh000905",  # 中证500
    "sh000852",  # 中证1000
    "sz399006",  # 创业板指
    "sh000688",  # 科创50
    "bj899050",  # 北证50
]

_TENCENT_URL = "http://qt.gtimg.cn/q=" + ",".join(INDEX_CODES)
_SINA_URL = "http://hq.sinajs.cn/list=" + ",".join(INDEX_CODES)
_SINA_HEADERS = {"User-Agent": UA, "Referer": "https://finance.sina.com.cn"}

# static-site 静态 JSON 输出路径（与 export.py 的 DATA_DIR 同源）
STATIC_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "static-site" / "data"

# 快照 code -> index_daily.index_id 映射（9 核心指数）
_SNAPSHOT_TO_INDEX_ID = {
    "sh000001": "sh",      # 上证指数
    "sz399001": "sz",      # 深证成指
    "sh000300": "hs300",   # 沪深300
    "sh000016": "sz50",    # 上证50
    "sh000905": "csi500",  # 中证500
    "sh000852": "csi1000",  # 中证1000
    "sz399006": "cyb",     # 创业板指
    "sh000688": "kc50",    # 科创50
    "bj899050": "bj50",    # 北证50
}


def _now_iso() -> str:
    return datetime.now().isoformat()


def _parse_tencent(text: str) -> list[dict]:
    """解析腾讯 qt 返回：每条 v_xxx="字段1~字段2~..."，按 ~ split（88 字段）。

    字段：[1]=name [3]=price [4]=pre_close [5]=open [30]=datetime(YYYYMMDDHHMMSS)
          [31]=change [32]=pct_change [33]=high [34]=low
    """
    out = []
    for line in text.strip().split(";"):
        line = line.strip()
        if not line or "=" not in line or '"' not in line:
            continue
        try:
            key = line.split("=", 1)[0].split("_")[-1]  # sh000001 / sz399001 ...
            vals = line.split('"', 2)[1].split("~")
            if len(vals) < 35:
                continue
        except Exception:  # noqa: BLE001
            continue

        def f(i):
            try:
                return float(vals[i])
            except (IndexError, ValueError):
                return None

        name = vals[1].strip()
        price = f(3)
        pre_close = f(4)
        change = f(31)
        pct = f(32)
        # 腾讯 pct_change 有时丢符号（price<pre_close 但 pct>0），用 change 自算兜底
        if price and pre_close and pre_close != 0:
            if pct is None or (change is not None and abs(pct) < 1e-6 and abs(change) > 1e-6):
                pct = (price - pre_close) / pre_close * 100
            # 符号兜底：change 与 pct 符号不一致以 change 为准
            if change is not None and abs(pct) > 1e-6 and (change > 0) != (pct > 0):
                pct = -abs(pct) if change < 0 else abs(pct)
        dtstr = vals[30].strip() if len(vals) > 30 else ""
        out.append({
            "code": key,
            "name": name,
            "price": price,
            "pre_close": pre_close,
            "change": change,
            "pct_change": pct,
            "open": f(5),
            "high": f(33),
            "low": f(34),
            "datetime": dtstr,
        })
    return out


def _parse_sina(text: str) -> list[dict]:
    """解析新浪 hq_str 返回（GBK）。指数行字段（实测 2026-07）：
    [0]=名称 [1]=今开(open) [2]=昨收(pre_close) [3]=现价(price) [4]=最高(high)
    [5]=最低(low) [30]=日期(YYYY-MM-DD) [31]=时间(HH:MM:SS)
    注意：新浪指数行 [1] 是今开不是昨收，[2] 才是昨收（与个股行相反，曾踩坑）。
    """
    out = []
    for line in text.strip().split("\n"):
        line = line.strip().rstrip(";")
        if not line.startswith("var hq_str_") or "=" not in line:
            continue
        try:
            code = line.split("=", 1)[0].replace("var hq_str_", "")
            body = line.split('"', 2)[1]
            fields = body.split(",")
            if len(fields) < 6:
                continue
        except Exception:  # noqa: BLE001
            continue

        def f(i):
            try:
                return float(fields[i])
            except (IndexError, ValueError):
                return None

        name = fields[0].strip()
        pre_close = f(2)  # [2]=昨收
        price = f(3)      # [3]=现价
        change = (price - pre_close) if (price and pre_close) else None
        pct = (change / pre_close * 100) if (change is not None and pre_close) else None
        date = fields[30].strip() if len(fields) > 30 else ""
        tm = fields[31].strip() if len(fields) > 31 else ""
        dtstr = ""
        if date:
            dtstr = date.replace("-", "") + (tm.replace(":", "") if tm else "")
        out.append({
            "code": code,
            "name": name,
            "price": price,
            "pre_close": pre_close,
            "change": change,
            "pct_change": pct,
            "open": f(1),   # [1]=今开
            "high": f(4),
            "low": f(5),
            "datetime": dtstr,
        })
    return out


def fetch_index_realtime() -> list[dict]:
    """采集 9 指数实时行情。腾讯主，失败逐个降级新浪。返回 9 条。"""
    # 1) 腾讯主源（一次拉全部）
    try:
        throttle()
        r = requests.get(_TENCENT_URL, headers={"User-Agent": UA}, timeout=10)
        tdata = _parse_tencent(r.content.decode("gbk"))
        got = {d["code"] for d in tdata if d.get("price")}
        if len(got) >= len(INDEX_CODES) - 1:  # 容忍 1 个缺失
            return tdata
        # 缺的用新浪补
        missing = [c for c in INDEX_CODES if c not in got]
        print(f"  [intraday] 腾讯缺 {len(missing)} 指数，新浪补采: {missing}", flush=True)
    except Exception as e:  # noqa: BLE001
        tdata = []
        missing = list(INDEX_CODES)
        print(f"  [intraday] 腾讯请求失败，全量降级新浪: {type(e).__name__} {e}", flush=True)

    # 2) 新浪补缺失（逐个，新浪支持 list 批量但分批更稳）
    if missing:
        try:
            throttle()
            r = requests.get(
                "http://hq.sinajs.cn/list=" + ",".join(missing),
                headers=_SINA_HEADERS, timeout=10)
            sdata = _parse_sina(r.content.decode("gbk"))
            s_by_code = {d["code"]: d for d in sdata if d.get("price")}
        except Exception as e:  # noqa: BLE001
            print(f"  [intraday] 新浪补采失败: {type(e).__name__} {e}", flush=True)
            s_by_code = {}

        # 合并：腾讯已有的保留，缺失的用新浪
        merged = {d["code"]: d for d in tdata}
        for c in missing:
            if c in s_by_code:
                merged[c] = s_by_code[c]
        # 按 INDEX_CODES 顺序输出
        return [merged[c] for c in INDEX_CODES if c in merged]

    return tdata


def _load_sw_names() -> dict[str, str]:
    """从 config 读申万一级行业名：{sw_id: name}。读不到时用 THS_TO_SW 反查首个子行业名兜底。"""
    try:
        from .fetchers import load_config
        cfg = load_config()
        names = {}
        for idx in cfg.get("indices", []):
            iid = idx.get("id", "")
            if iid.startswith("sw_") and idx.get("enabled", True):
                names[iid] = idx.get("name", iid)
        return names
    except Exception:  # noqa: BLE001
        return {}


def fetch_industry_realtime() -> list[dict]:
    """31 申万一级行业实时涨跌幅 + 净流入 + 领涨股。

    调同花顺 stock_board_industry_summary_ths() 拿 90 二级行业，通过 THS_TO_SW 聚合：
    - pct_change：子行业涨跌幅按成交额加权平均
    - net_inflow：子行业净流入求和（亿元）
    - lead_stock：取该申万行业下涨跌幅最高子行业的领涨股
    返回 31 条 {sw_code, sw_name, pct_change, net_inflow, lead_stock}。
    """
    import akshare as ak

    try:
        df = ak.stock_board_industry_summary_ths()
    except Exception as e:  # noqa: BLE001
        print(f"  [intraday] 同花顺行业 summary 失败: {type(e).__name__} {e}", flush=True)
        return []

    if df is None or len(df) == 0:
        print("  [intraday] 同花顺行业 summary 空", flush=True)
        return []

    sw_names = _load_sw_names()
    # 反向：sw_id -> [(ths_name, pct, amt, net, lead_stock, lead_pct)]
    agg: dict[str, list] = {}
    for _, row in df.iterrows():
        ths_name = str(row["板块"]).strip()
        sw_id = THS_TO_SW.get(ths_name)
        if sw_id is None:
            continue
        try:
            pct = float(row["涨跌幅"])
        except (TypeError, ValueError):
            pct = 0.0
        try:
            amt = float(row["总成交额"])
        except (TypeError, ValueError):
            amt = 0.0
        try:
            net = float(row["净流入"])
        except (TypeError, ValueError):
            net = 0.0
        lead = ""
        try:
            lead = str(row.get("领涨股", "") or "").strip()
        except Exception:  # noqa: BLE001
            pass
        agg.setdefault(sw_id, []).append((ths_name, pct, amt, net, lead))

    out = []
    for sw_id, subs in agg.items():
        tot = sum(s[2] for s in subs) or 1.0
        wpct = sum(s[1] * s[2] for s in subs) / tot
        net = sum(s[3] for s in subs)
        # 领涨股：取涨幅最高子行业
        best = max(subs, key=lambda s: s[1]) if subs else None
        lead_stock = best[4] if best else ""
        out.append({
            "sw_code": sw_id,
            "sw_name": sw_names.get(sw_id, sw_id),
            "pct_change": round(wpct, 2),
            "net_inflow": round(net, 2),
            "lead_stock": lead_stock,
        })
    # 按 pct_change 降序
    out.sort(key=lambda x: x["pct_change"], reverse=True)
    return out


def is_market_closed() -> tuple[bool, str]:
    """判断当前是否收盘。返回 (is_closed, label)。

    用本地时间 + 交易日历判断盘中区间（9:30-11:30/13:00-15:00 周一至五）。
    """
    try:
        from ..calendar import is_trading_day
        trading = is_trading_day()
    except Exception:  # noqa: BLE001
        trading = True  # 拿不到日历默认按交易日处理（仅影响 label 文案）
    now = datetime.now()
    hm = now.hour * 100 + now.minute
    wd = now.weekday()  # 0=Mon
    in_session = (
        trading and wd < 5
        and ((930 <= hm < 1130) or (1300 <= hm < 1500))
    )
    is_closed = not in_session
    label = "收盘快照" if is_closed else "盘中实时小结"
    return is_closed, label


def _save_db(collected_at: str, is_closed: bool,
             indices: list, industries: list) -> None:
    """存 DB（单行覆盖，id=1）。"""
    conn = get_conn()
    conn.execute(
        "INSERT INTO intraday_snapshot (id, collected_at, is_closed, indices, industries) "
        "VALUES (1, ?, ?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET "
        "collected_at=excluded.collected_at, is_closed=excluded.is_closed, "
        "indices=excluded.indices, industries=excluded.industries",
        (collected_at, 1 if is_closed else 0,
         json.dumps(indices, ensure_ascii=False),
         json.dumps(industries, ensure_ascii=False)),
    )
    conn.commit()
    conn.close()


def _backfill_index_daily(indices: list[dict]) -> int:
    """把盘中快照的当日指数 OHLC 反哺 index_daily 表（UPSERT，幂等）。

    解决 T+1 数据源（baostock/东财 trend）收盘后未出当日数据致指数卡片/恐贪停在 T-2 的问题。
    快照无成交额，amount 留 NULL（per-index 情绪分的 volume 分项会缺，但 RSI+pct_change 仍可算）。
    非交易日不写；快照 datetime 非当日不写（避免旧快照污染）。
    返回写入的指数条数。
    """
    from ..calendar import is_trading_day

    today = datetime.now().strftime("%Y%m%d")
    if not is_trading_day(today):
        print(f"  [intraday] 非交易日({today})，跳过 index_daily 反哺", flush=True)
        return 0

    conn = get_conn()
    n = 0
    for idx in indices:
        code = idx.get("code", "")
        index_id = _SNAPSHOT_TO_INDEX_ID.get(code)
        if not index_id:
            continue
        price = idx.get("price")
        if price is None:
            continue
        # datetime 校验：必须是当日数据，避免旧快照污染
        dtstr = idx.get("datetime", "")
        snap_date = dtstr[:8] if len(dtstr) >= 8 else ""
        if snap_date and snap_date != today:
            print(f"  [intraday] {code} 快照日期 {snap_date} != 今日 {today}，跳过", flush=True)
            continue

        conn.execute(
            "INSERT INTO index_daily (date, index_id, open, high, low, close, pct_change, amount) "
            "VALUES (?,?,?,?,?,?,?,?) "
            "ON CONFLICT(date, index_id) DO UPDATE SET "
            "open=excluded.open, high=excluded.high, low=excluded.low, "
            "close=excluded.close, pct_change=excluded.pct_change, amount=excluded.amount",
            (today, index_id, idx.get("open"), idx.get("high"), idx.get("low"),
             price, idx.get("pct_change"), None),
        )
        n += 1
    conn.commit()
    conn.close()
    print(f"  [intraday] index_daily 反哺完成：{n} 条（来源：实时快照，amount=NULL）", flush=True)
    return n


def _recompute_scores() -> None:
    """反哺后重算 6 个 per-index 情绪分 + 恐贪指数。

    per-index 情绪分（sentiment_sz50/hs300/csi500/csi1000/cyb/kc50）依赖 index_daily OHLC，
    反哺当日数据后重算即可得到当日值。恐贪 = 8 子情绪分等权平均，6 个 per-index 更新后
    连同已有的 a_sentiment + cross_market（均到当日）合成恐贪当日值。
    """
    from ..compute import sentiment, fear_greed

    index_ids = ["sz50", "hs300", "csi500", "csi1000", "cyb", "kc50"]
    for idx_id in index_ids:
        idx_score, idx_comps = sentiment.compute_index_sentiment(idx_id)
        n = sentiment.store(idx_score, idx_comps, score_id=f"sentiment_{idx_id}")
        last_val = round(float(idx_score.dropna().iloc[-1]), 2) if not idx_score.dropna().empty else None
        last_date = idx_score.dropna().index[-1] if not idx_score.dropna().empty else "?"
        print(f"  [intraday] sentiment_{idx_id}: {n}天, 末日={last_date}={last_val}", flush=True)

    n_fg = fear_greed.compute_fear_greed()
    # 查恐贪末日验证
    conn = get_conn()
    fg_last = conn.execute(
        "SELECT date, value FROM score_daily WHERE score_id='fear_greed' ORDER BY date DESC LIMIT 1"
    ).fetchone()
    conn.close()
    fg_str = f"{fg_last['date']}={fg_last['value']}" if fg_last else "?"
    print(f"  [intraday] fear_greed 重算: {n_fg}天, 末日={fg_str}", flush=True)


def _export_affected_json() -> None:
    """重算后 dump 受影响的静态 JSON（双版同步：static-site/data/）。

    导出：overview + sentiment(5 ranges) + 9 指数 detail，
    让 static-site 的恐贪/情绪分/指数 sparkline 都到当日。
    """
    import importlib.util
    from .fetchers import load_config

    ROOT = Path(__file__).resolve().parent.parent.parent
    spec = importlib.util.spec_from_file_location("export", ROOT / "static-site" / "export.py")
    export_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(export_mod)

    cfg = load_config()
    conn = get_conn()

    # overview（含 scores + indices_sparkline + fear_greed_6m）
    export_mod.write_json(export_mod.DATA_DIR / "overview.json",
                          export_mod.export_overview(conn, cfg))

    # sentiment 5 ranges（含 6 per-index + fear_greed 全历史）
    for rng in export_mod.ALL_RANGES:
        export_mod.write_json(export_mod.DATA_DIR / f"sentiment-{rng}.json",
                              export_mod.export_sentiment(conn, cfg, rng))

    # summary + summary_history（恐贪/情绪分变了，收盘分析横幅与历史弹窗也要更新）
    export_mod.write_json(export_mod.DATA_DIR / "summary.json",
                          export_mod.export_summary())
    export_mod.write_json(export_mod.DATA_DIR / "summary_history.json",
                          export_mod.export_summary_history())

    # 9 指数 detail（反哺的指数 OHLC + signals）
    affected = list(_SNAPSHOT_TO_INDEX_ID.values())
    for iid in affected:
        export_mod.write_json(export_mod.INDEX_DIR / f"{iid}-all.json",
                              export_mod.export_index_detail(conn, cfg, iid))

    conn.close()
    print(f"  [intraday] 静态 JSON dump 完成：overview + sentiment×5 + index detail×{len(affected)}",
          flush=True)


def build_snapshot() -> dict:
    """采集 + 组装快照 dict（不落库）。供 collect_and_save 和 API 共用。"""
    indices = fetch_index_realtime()
    industries = fetch_industry_realtime()
    is_closed, label = is_market_closed()
    return {
        "collected_at": _now_iso(),
        "is_closed": is_closed,
        "label": label,
        "indices": indices,
        "industries": industries,
    }


def collect_and_save() -> dict:
    """采集 + 存 DB + dump 静态 JSON。返回快照 dict。

    采集完腾讯实时 9 指数后，把当日 OHLC 反哺 index_daily 表（UPSERT），
    再重算 per-index 情绪分 + 恐贪指数，最后 dump 受影响的静态 JSON，
    使指数卡片/恐贪/per-index 情绪分都能到当日（解决 T+1 延迟致停在 T-2 的问题）。
    反哺/重算/export 失败不阻断快照本身（快照已落库落盘）。
    """
    print(f"[intraday] 开始采集盘中实时快照 {datetime.now():%Y-%m-%d %H:%M:%S}", flush=True)
    t0 = time.time()

    snap = build_snapshot()

    # 存 DB
    _save_db(snap["collected_at"], snap["is_closed"],
             snap["indices"], snap["industries"])

    # dump 静态 JSON（双版同步：static-site/data/intraday_snapshot.json）
    STATIC_DATA_DIR.mkdir(parents=True, exist_ok=True)
    out_path = STATIC_DATA_DIR / "intraday_snapshot.json"
    text = json.dumps(snap, ensure_ascii=False, separators=(",", ":"))
    out_path.write_text(text, encoding="utf-8")

    dt = time.time() - t0
    print(f"[intraday] 快照完成：{len(snap['indices'])} 指数 / {len(snap['industries'])} 行业 "
          f"({snap['label']})，{dt:.1f}s -> {out_path.name}", flush=True)

    # 反哺 index_daily + 重算情绪分/恐贪 + dump 静态 JSON
    # 失败不阻断快照本身（快照已落库落盘，反哺是增强）
    try:
        n_backfill = _backfill_index_daily(snap["indices"])
        if n_backfill > 0:
            _recompute_scores()
            _export_affected_json()
            print(f"[intraday] 反哺+重算+export 完成（{n_backfill} 指数反哺）", flush=True)
        else:
            print(f"[intraday] 无指数反哺（非交易日或快照非当日），跳过重算", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"[intraday] 反哺/重算/export 失败（快照已保存）: {type(e).__name__} {e}", flush=True)

    return snap


def load_latest_snapshot() -> dict | None:
    """从 DB 读最新快照（供 API / export 用）。无数据返 None。"""
    conn = get_conn()
    row = conn.execute(
        "SELECT collected_at, is_closed, indices, industries "
        "FROM intraday_snapshot WHERE id=1"
    ).fetchone()
    conn.close()
    if not row:
        return None
    is_closed = bool(row["is_closed"])
    try:
        indices = json.loads(row["indices"])
    except Exception:  # noqa: BLE001
        indices = []
    try:
        industries = json.loads(row["industries"])
    except Exception:  # noqa: BLE001
        industries = []
    return {
        "collected_at": row["collected_at"],
        "is_closed": is_closed,
        "label": "收盘快照" if is_closed else "盘中实时小结",
        "indices": indices,
        "industries": industries,
    }


if __name__ == "__main__":
    collect_and_save()
