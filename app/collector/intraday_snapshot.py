"""盘中实时快照采集（方案 A 后端）。

解决收盘后 pipeline 拿不到当日指数（上证 0%）的问题：盘中直采腾讯实时行情 +
同花顺行业实时涨跌幅，存 DB + dump 静态 JSON，供前端"盘中实时小结"展示。

- 9 指数实时：腾讯 qt.gtimg.cn（主），新浪 hq.sinajs.cn（逐个降级备）。
- 31 申万一级行业实时涨跌幅：复用同花顺 stock_board_industry_summary_ths（90 子行业），
  通过 THS_TO_SW 聚合（涨跌幅按成交额加权、净流入求和、领涨股取涨幅最高子行业）。
- is_market_closed：时间+数据双重判断盘中区间（9:30-11:30/13:00-15:00 交易日），
  传 at=collected_at 时按数据时刻判断，不传默认 now（向后兼容）。
- **指数反哺**：采集完 9 指数后，把当日 OHLC 写入 index_daily 表（UPSERT），
  触发重算 per-index 情绪分 + 恐贪指数 + dump 静态 JSON，
  使指数卡片/恐贪/per-index 情绪分到当日（解决 T+1 延迟致停在 T-2 的问题）。
  非交易日不反哺；快照 datetime 非当日不写（避免旧快照污染）。
"""
import json
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

from ..db import get_conn
from .base import UA, throttle
from .industry_extras import THS_TO_SW

# 9 核心 A 股指数 + 3 港股指数（腾讯 qt 支持混合请求）
# 港股用 r_hkXXX 前缀（腾讯港股实时源），盘中（9:30-16:00）返实时价，16:00 收盘后返收盘价
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
    "r_hkHSI",   # 恒生指数（港股）
    "r_hkHSTECH",  # 恒生科技指数（港股）
    "r_hkHSCEI",   # 国企指数（港股）
]

# A 股 codes（用于新浪兜底；新浪不支持 r_hkXXX 格式，港股只走腾讯）
_A_STOCK_CODES = [c for c in INDEX_CODES if not c.startswith("r_hk")]

_TENCENT_URL = "http://qt.gtimg.cn/q=" + ",".join(INDEX_CODES)
_SINA_URL = "http://hq.sinajs.cn/list=" + ",".join(_A_STOCK_CODES)
_SINA_HEADERS = {"User-Agent": UA, "Referer": "https://finance.sina.com.cn"}

# static-site 静态 JSON 输出路径（与 export.py 的 DATA_DIR 同源）
STATIC_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "static-site" / "data"

# 快照 code -> index_daily.index_id 映射（9 核心 A 股 + 3 港股）
# 注意：_parse_tencent 提取 key 时 strip "v_" 前缀 + split("_")[-1]，
#   A 股 v_sh000001 -> "sh000001"；港股 v_r_hkHSI -> "hkHSI"（r_ 被吃掉）。
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
    "hkHSI": "hsi",        # 恒生指数（港股）
    "hkHSTECH": "hstech",  # 恒生科技（港股）
    "hkHSCEI": "hscei",    # 国企指数（港股）
}


def _now_iso() -> str:
    return datetime.now().isoformat()


def _parse_tencent(text: str) -> list[dict]:
    """解析腾讯 qt 返回：每条 v_xxx="字段1~字段2~..."，按 ~ split。

    A 股 88 字段 / 港股 78 字段，关键字段位置一致：
    [1]=name [3]=price [4]=pre_close [5]=open [6]=amount(港股)
         [30]=datetime [31]=change [32]=pct_change [33]=high [34]=low

    datetime 差异：A 股 "YYYYMMDDHHMMSS"（无分隔符），
                  港股 "YYYY/MM/DD HH:MM:SS"（有分隔符，需规范化为 YYYYMMDDHHMMSS）。
    """
    out = []
    for line in text.strip().split(";"):
        line = line.strip()
        if not line or "=" not in line or '"' not in line:
            continue
        try:
            key = line.split("=", 1)[0].split("_")[-1]  # sh000001 / hkHSI ...
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
        # 规范化 datetime：A 股 "YYYYMMDDHHMMSS"，港股 "YYYY/MM/DD HH:MM:SS"
        dtstr_raw = vals[30].strip() if len(vals) > 30 else ""
        if "/" in dtstr_raw:
            # 港股格式 YYYY/MM/DD HH:MM:SS -> YYYYMMDDHHMMSS
            dtstr = dtstr_raw.replace("/", "").replace(" ", "").replace(":", "")
        else:
            dtstr = dtstr_raw
        # 港股 field[6]=成交额(万港元)；A 股 field[6] 非 amount（是成交笔数等），不提取。
        # 收盘后腾讯返收盘价 + 当日完整成交额；盘中返实时累计额。
        amount = None
        if key.startswith("hk"):
            amt_wan = f(6)
            amount = amt_wan * 10000 if amt_wan is not None else None
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
            "amount": amount,
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
    """采集 12 指数实时行情（9 A 股 + 3 港股）。腾讯主，A 股失败逐个降级新浪。
    港股只走腾讯（新浪不支持 r_hkXXX 格式）。返回 12 条。"""
    # 1) 腾讯主源（一次拉全部，含 A 股 + 港股）
    try:
        throttle()
        r = requests.get(_TENCENT_URL, headers={"User-Agent": UA}, timeout=10)
        tdata = _parse_tencent(r.content.decode("gbk"))
        got = {d["code"] for d in tdata if d.get("price")}
        if len(got) >= len(INDEX_CODES) - 1:  # 容忍 1 个缺失
            return tdata
        # 缺的用新浪补（仅 A 股，港股跳过新浪不支持）
        missing = [c for c in INDEX_CODES if c not in got and not c.startswith("r_hk")]
        if missing:
            print(f"  [intraday] 腾讯缺 {len(missing)} A 股指数，新浪补采: {missing}", flush=True)
        hk_missing = [c for c in INDEX_CODES if c not in got and c.startswith("r_hk")]
        if hk_missing:
            print(f"  [intraday] 腾讯缺 {len(hk_missing)} 港股指数（新浪不支持，跳过）: {hk_missing}", flush=True)
    except Exception as e:  # noqa: BLE001
        tdata = []
        missing = [c for c in INDEX_CODES if not c.startswith("r_hk")]  # 全量降级新浪（仅 A 股）
        print(f"  [intraday] 腾讯请求失败，A 股降级新浪: {type(e).__name__} {e}", flush=True)

    # 2) 新浪补缺失（仅 A 股，逐个，新浪支持 list 批量但分批更稳）
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
    """31 申万一级行业实时涨跌幅 + 净流入 + 成交额 + 领涨股。

    调同花顺 stock_board_industry_summary_ths() 拿 90 二级行业，通过 THS_TO_SW 聚合：
    - pct_change：子行业涨跌幅按成交额加权平均
    - net_inflow：子行业净流入求和（亿元）
    - amount：子行业成交额求和，元->亿元（与申万 DB amount 单位一致）
    - lead_stock：取该申万行业下涨跌幅最高子行业的领涨股
    返回 31 条 {sw_code, sw_name, pct_change, net_inflow, amount, lead_stock}。
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
        amt = sum(s[2] for s in subs)  # 子行业成交额求和（元）
        # 领涨股：取涨幅最高子行业
        best = max(subs, key=lambda s: s[1]) if subs else None
        lead_stock = best[4] if best else ""
        out.append({
            "sw_code": sw_id,
            "sw_name": sw_names.get(sw_id, sw_id),
            "pct_change": round(wpct, 2),
            "net_inflow": round(net, 2),
            "amount": round(amt / 1e8, 2),  # 元->亿元，与申万 DB amount 单位一致
            "lead_stock": lead_stock,
        })
    # 按 pct_change 降序
    out.sort(key=lambda x: x["pct_change"], reverse=True)
    return out


def fetch_concept_realtime() -> list[dict]:
    """27 同花顺概念板块实时涨跌幅 + OHLC + 成交额。

    复用 index_backfill._ths_concept_info_fetch 的拉取逻辑：
    ak.stock_board_concept_info_ths(symbol=概念名) 拿当日快照（项目/值两列），
    合成 open=今开 / high=最高 / low=最低 / close=昨收×(1+板块涨幅/100) /
    pct=板块涨幅 / amount=成交额(亿)×1e8(转元，对齐历史序列入库单位)。

    与 fetch_industry_realtime 的差异：
    - 行业 summary 一次返 90 子行业（聚合 31 申万），概念需逐个调（27 次）；
    - 概念快照含完整 OHLC（今开/最高/最低），行业 summary 只有涨跌幅（close 需计算法）。

    概念配置从 indicators.yaml 读 enabled thsc_ 项。返回 27 条 dict（失败的跳过），
    按 pct_change 降序，结构与 industries 对齐便于前端复用渲染逻辑。
    """
    from .fetchers import load_config
    from .index_backfill import _ths_concept_info_fetch

    cfg = load_config()
    concepts_cfg = [i for i in cfg.get("indices", [])
                    if i.get("id", "").startswith("thsc_") and i.get("enabled", True)]
    today = datetime.now().strftime("%Y%m%d")

    out = []
    fail = 0
    for tc in concepts_cfg:
        thsc_id = tc["id"]
        # symbol 是 akshare 接口参数（概念名），name 是展示名
        symbol = tc.get("symbol") or tc.get("name", thsc_id)
        # throttle 限流：27 个概念逐个调，避免触发同花顺反爬
        throttle()
        # _ths_concept_info_fetch 返回 [(date, thsc_id, open, high, low, close, pct, amount)]
        rows = _ths_concept_info_fetch(thsc_id, symbol, today)
        if rows:
            r = rows[0]
            out.append({
                "id": thsc_id,
                "name": tc.get("name", thsc_id),
                "pct_change": r[6],
                "close": r[5],
                "open": r[2],
                "high": r[3],
                "low": r[4],
                "amount": r[7],
            })
        else:
            fail += 1
    # 按 pct_change 降序（None 兜底排末尾）
    out.sort(key=lambda x: (x.get("pct_change") is None, x.get("pct_change") or -999), reverse=True)
    print(f"  [intraday] 概念实时采集完成：{len(out)}/{len(concepts_cfg)} 条"
          f"（失败 {fail}）", flush=True)
    return out


def is_market_closed(at: datetime | None = None) -> tuple[bool, str]:
    """判断 A 股是否收盘。返回 (is_closed, label)。

    时间+数据双重判断：传入 at（通常是快照 collected_at）时按该时刻判断
    落在哪个时段；不传默认 now（向后兼容现有无参调用）。

    4 态区分（基于 at 而非当前时钟）：
    - 盘中(9:30-11:30 / 13:00-15:00 周一至五交易日): (False, "盘中实时小结")
    - 午休(11:30-13:00): (False, "午休·盘中暂停（13:00复牌）")  # 午休也算未收盘
    - 收盘 / 非交易日: (True, "收盘快照")
    - at 早于今天（旧数据）: (True, "上一交易日收盘")
    """
    at = at or datetime.now()
    today = datetime.now().date()
    at_date = at.date()
    # 数据来自前一交易日 -> 已收盘的旧数据（非今日实时）
    if at_date < today:
        return True, "上一交易日收盘"
    try:
        from ..calendar import is_trading_day
        trading = is_trading_day(at_date)
    except Exception:  # noqa: BLE001
        trading = True  # 拿不到日历默认按交易日处理（仅影响 label 文案）
    if not trading:
        return True, "收盘快照"
    hm = at.hour * 100 + at.minute
    if (930 <= hm <= 1130) or (1300 <= hm < 1500):
        return False, "盘中实时小结"
    if 1130 < hm < 1300:
        return False, "午休·盘中暂停（13:00复牌）"
    return True, "收盘快照"


def is_hk_market_closed(at: datetime | None = None) -> tuple[bool, str]:
    """判断港股是否收盘。返回 (is_closed, label)。

    港股交易时间 9:30-12:00 / 13:00-16:00（北京时间，与 A 股同时区）。
    16:00 收盘，A 股 15:00 收盘后到 16:00 之间港股仍在盘中。
    午休 12:00-13:00 属"盘中暂停"而非收盘：is_closed=False，label 提示午休。

    时间+数据双重判断：传入 at 时按该时刻判断；不传默认 now（向后兼容）。
    """
    at = at or datetime.now()
    today = datetime.now().date()
    at_date = at.date()
    if at_date < today:
        return True, "上一交易日收盘"
    try:
        from ..calendar import is_trading_day
        trading = is_trading_day(at_date)
    except Exception:  # noqa: BLE001
        trading = True
    if not trading:
        return True, "收盘快照"
    hm = at.hour * 100 + at.minute
    if (930 <= hm <= 1200) or (1300 <= hm < 1600):
        return False, "盘中实时"
    if 1200 < hm < 1300:
        return False, "午休·盘中暂停（13:00复牌）"
    return True, "收盘快照"


def _save_db(collected_at: str, is_closed: bool,
             indices: list, industries: list, concepts: list = None,
             us_futures: dict = None) -> None:
    """存 DB（单行覆盖，id=1）。concepts/us_futures 可选（向后兼容旧调用）。"""
    conn = get_conn()
    if concepts is None:
        concepts = []
    if us_futures is None:
        us_futures = {}
    conn.execute(
        "INSERT INTO intraday_snapshot (id, collected_at, is_closed, indices, industries, concepts, us_futures) "
        "VALUES (1, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET "
        "collected_at=excluded.collected_at, is_closed=excluded.is_closed, "
        "indices=excluded.indices, industries=excluded.industries, concepts=excluded.concepts, "
        "us_futures=excluded.us_futures",
        (collected_at, 1 if is_closed else 0,
         json.dumps(indices, ensure_ascii=False),
         json.dumps(industries, ensure_ascii=False),
         json.dumps(concepts, ensure_ascii=False),
         json.dumps(us_futures, ensure_ascii=False)),
    )
    conn.commit()
    conn.close()


def _backfill_index_daily(indices: list[dict]) -> int:
    """把盘中快照的当日指数 OHLC 反哺 index_daily 表（UPSERT，幂等）。

    解决 T+1 数据源（baostock/东财 trend）收盘后未出当日数据致指数卡片/恐贪停在 T-2 的问题。
    A 股 15:00 收盘 -> 快照 price 即收盘价；港股 16:00 收盘 -> 15:35 快照时 price 是盘中
    实时价（非最终收盘价），但写入 close 让港股卡片显示当日实时涨跌；17:50 update_all
    再跑 intraday_snapshot 时港股已收盘，腾讯返收盘价 + 成交额，覆盖盘中价。
    港股成交额从腾讯 field[6]（万港元）提取（_parse_tencent），A 股 amount 留 NULL
    （新浪全量源有成交额）。
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
             price, idx.get("pct_change"), idx.get("amount")),
        )
        n += 1
    conn.commit()
    conn.close()
    print(f"  [intraday] index_daily 反哺完成：{n} 条（来源：实时快照，港股含成交额）", flush=True)
    return n


def _backfill_industry_daily(industries: list[dict], target_date: str = None) -> int:
    """把盘中快照的 31 申万行业涨跌幅反哺 index_daily 表（UPSERT，幂等）。

    解决收盘分析历史弹窗领涨空的问题：market_summary 的 top_industries 查
    index_daily WHERE index_id LIKE 'sw_%' AND pct_change IS NOT NULL，
    盘中快照此前只反哺 9 指数没反哺行业，致当日申万行业行不存在 -> 领涨空。
    同花顺行业 summary 只给涨跌幅无 OHLC，盘中用 close 计算法补 close：
      close = prev_close * (1 + pct_change/100)   (prev_close=DB 该 index_id 最后有 close 的行)
    无 prev_close 时（首次/新行业）close 留 NULL（不硬算），保持原行为。
    amount 来自 fetch_industry_realtime 聚合的子行业成交额（亿元）。
    ON CONFLICT 更新 pct_change + net_inflow + close + amount（盘中实时刷新）；
    open/high/low 仍留 NULL（无盘中 OHLC 源），申万晚间 OHLC pipeline 会覆盖。
    非交易日不写；pct_change 为 None 跳过该条。
    返回写入的行业条数。

    target_date 指定时进入历史补采模式：不依赖 fetch_industry_realtime（只返今日），
    改用 _fetch_sw_ohlc_ths 拿该日期真实 OHLC（含 close，比计算法准）；
    THS 失败则回退计算法（DB 已有 pct_change × prev_close）。
    """
    from ..calendar import is_trading_day

    today = target_date or datetime.now().strftime("%Y%m%d")
    if not is_trading_day(today):
        print(f"  [intraday] 非交易日({today})，跳过 index_daily 行业反哺", flush=True)
        return 0

    # 历史日期补采：用 _fetch_sw_ohlc_ths 拿真实 OHLC，失败回退计算法
    if target_date is not None:
        return _backfill_industry_daily_historical(today)

    conn = get_conn()
    n = 0
    calc_n = 0  # close 计算法命中数
    for ind in industries:
        sw_code = ind.get("sw_code", "")
        if not sw_code:
            continue
        pct = ind.get("pct_change")
        if pct is None:
            continue
        net = ind.get("net_inflow")
        amt = ind.get("amount")
        # close 计算法：查 DB 该 index_id 最后有 close 的行作 prev_close
        # 排除当日(date < today)：pct_change 是相对昨收的日涨幅，多次盘中快照
        # 必须锚定同一 prev_close（昨收），否则 close 会累乘偏移
        prev = conn.execute(
            "SELECT close FROM index_daily WHERE index_id=? AND close IS NOT NULL "
            "AND date < ? ORDER BY date DESC LIMIT 1", (sw_code, today)
        ).fetchone()
        close_val = None
        if prev and prev["close"] is not None:
            close_val = round(float(prev["close"]) * (1 + float(pct) / 100.0), 4)
            calc_n += 1
        conn.execute(
            "INSERT INTO index_daily (date, index_id, open, high, low, close, pct_change, amount, net_inflow) "
            "VALUES (?, ?, NULL, NULL, NULL, ?, ?, ?, ?) "
            "ON CONFLICT(date, index_id) DO UPDATE SET "
            "pct_change=excluded.pct_change, net_inflow=excluded.net_inflow, "
            "close=excluded.close, amount=excluded.amount",
            (today, sw_code, close_val, pct, amt, net),
        )
        n += 1
    conn.commit()
    conn.close()
    print(f"  [intraday] index_daily 行业反哺完成：{n} 条（close 计算法 {calc_n} 条，含 net_inflow/amount）", flush=True)
    return n


def _backfill_industry_daily_historical(target_date: str) -> int:
    """历史日期 sw 行业 close 补采（_fetch_sw_ohlc_ths 优先，计算法兜底）。

    补历史日期(如 7/14)时 fetch_industry_realtime 拿不到该日 pct（只返今日），
    改用 _fetch_sw_ohlc_ths 拿该日期真实 OHLC（聚合 90 子行业 -> 31 申万一级，
    锚定 DB 最后有 close 的行作 junction）。THS 返回真实 close/OHLC，比计算法准。
    THS 失败（子行业数据未发布/网络故障）则回退计算法：
      close = prev_close(DB 最后有 close 的行) × (1 + DB 已有 pct_change/100)
    无 pct_change 或无 prev_close 则跳过（close 留 NULL）。
    """
    from .index_backfill import SW_INDICES
    from .industry_extras import _fetch_sw_ohlc_ths
    from .runner import upsert_index_rows

    conn = get_conn()
    n = 0
    ths_n = 0
    calc_n = 0
    skip_n = 0
    for sw_code in SW_INDICES:
        # 已有 close 跳过（幂等）
        r = conn.execute(
            "SELECT close, pct_change FROM index_daily WHERE index_id=? AND date=?",
            (sw_code, target_date)
        ).fetchone()
        if r and r["close"] is not None:
            skip_n += 1
            continue

        # 优先 THS 拿真实 OHLC（含 open/high/low/close/amount）
        rows, _msg = _fetch_sw_ohlc_ths(sw_code, target_date, target_date, verbose=False)
        rows = [rw for rw in rows if rw[0] == target_date]
        if rows:
            upsert_index_rows(rows)
            ths_n += 1
            n += 1
            db_pct = r["pct_change"] if r else None
            print(f"    ✓ {sw_code} <- ths close={rows[0][5]} (db_pct={db_pct})", flush=True)
            continue

        # 回退计算法：prev_close(DB) × (1 + DB 已有 pct_change/100)
        pct = r["pct_change"] if r else None
        if pct is not None:
            prev = conn.execute(
                "SELECT close FROM index_daily WHERE index_id=? AND close IS NOT NULL "
                "AND date < ? ORDER BY date DESC LIMIT 1", (sw_code, target_date)
            ).fetchone()
            if prev and prev["close"] is not None:
                close_val = round(float(prev["close"]) * (1 + float(pct) / 100.0), 4)
                conn.execute(
                    "UPDATE index_daily SET close=? WHERE index_id=? AND date=?",
                    (close_val, sw_code, target_date)
                )
                calc_n += 1
                n += 1
                print(f"    ~ {sw_code} <- calc close={close_val} "
                      f"(prev={prev['close']}, pct={pct})", flush=True)
                continue

        skip_n += 1
        reason = "无 pct_change" if (not r or r["pct_change"] is None) else "无 prev_close"
        print(f"    ✗ {sw_code} 跳过（{reason}）", flush=True)

    conn.commit()
    conn.close()
    print(f"  [intraday] 行业历史补采({target_date})：{n} 条"
          f"（THS {ths_n} + 计算法 {calc_n} + 已有/跳过 {skip_n}）", flush=True)
    return n


def _backfill_concept_daily(concepts: list[dict]) -> int:
    """把盘中快照的 27 概念 OHLC 反哺 index_daily 表（UPSERT，幂等）。

    与 _backfill_industry_daily 对称：行业 summary 只有涨跌幅（close 需计算法、
    open/high/low 留 NULL），而概念快照（stock_board_concept_info_ths）含完整
    今开/最高/最低，故概念反哺写完整 OHLC（比行业更准）。

    close 仍由昨收×(1+涨幅/100) 合成（快照无收盘价字段，_ths_concept_info_fetch
    已反推）。amount 来自快照成交额(亿)×1e8 转元。ON CONFLICT 更新全部 OHLC +
    pct_change + amount（盘中多次快照持续刷新实时值）；收盘 pipeline（T+1 历史序列）
    次日覆盖为最终收盘值。非交易日不写；pct_change 为 None 跳过该条。
    返回写入的概念条数。
    """
    from ..calendar import is_trading_day

    today = datetime.now().strftime("%Y%m%d")
    if not is_trading_day(today):
        print(f"  [intraday] 非交易日({today})，跳过 index_daily 概念反哺", flush=True)
        return 0

    conn = get_conn()
    n = 0
    for c in concepts:
        cid = c.get("id", "")
        if not cid:
            continue
        pct = c.get("pct_change")
        if pct is None:
            continue
        conn.execute(
            "INSERT INTO index_daily (date, index_id, open, high, low, close, pct_change, amount) "
            "VALUES (?,?,?,?,?,?,?,?) "
            "ON CONFLICT(date, index_id) DO UPDATE SET "
            "open=excluded.open, high=excluded.high, low=excluded.low, "
            "close=excluded.close, pct_change=excluded.pct_change, amount=excluded.amount",
            (today, cid, c.get("open"), c.get("high"), c.get("low"),
             c.get("close"), pct, c.get("amount")),
        )
        n += 1
    conn.commit()
    conn.close()
    print(f"  [intraday] index_daily 概念反哺完成：{n} 条（含完整 OHLC + amount）", flush=True)
    return n


def _collect_intraday_width_metrics() -> dict:
    """盘中采集宽度/成交额指标，写入 daily_metric（source='intraday'）。

    解决 KPI metrics 行(涨停/跌停/炸板率/成交额/量比)+width_1m(涨跌家数)+
    a_sentiment/cross_market 停在 T-1 的问题：盘中 30 分钟快照此前只采指数/行业，
    不采这些 width/fund 指标，致 metrics 行/width/a_sentiment 缺当日值。

    数据源（akshare，各 try/except 不互相阻断）：
    - stock_zh_a_spot（全市场实时快照，~20s）-> a_width_up_count/a_width_down_count/a_amount
    - stock_zt_pool_em（涨停池，盘中实时）-> a_width_zt_count + a_width_max_lianban
    - stock_zt_pool_dtgc_em（跌停池）-> a_width_dt_count
    - stock_zt_pool_zbgc_em（炸板池）-> a_width_zhaban_rate = 炸板数/(涨停数+炸板数)

    采完后调 volume_ratio.compute() 算 a_volume_ratio/a_amount_ma5/ma20/a_volume_signal
    （基于 a_amount，需 index_daily 已有当日 sh pct_change，故在 _backfill_index_daily 之后调）。
    source='intraday'：收盘 pipeline（akshare/mootdx source）会覆盖为最终收盘值。
    非交易日跳过。返回采集到的指标 dict（空=未采到任何指标）。
    """
    from ..calendar import is_trading_day
    import akshare as ak
    from .base import safe_call
    from .runner import upsert_metric
    from ..compute import volume_ratio

    today = datetime.now().strftime("%Y%m%d")
    if not is_trading_day(today):
        print(f"  [intraday] 非交易日({today})，跳过 width 指标采集", flush=True)
        return {}

    results: dict = {}
    conn = get_conn()

    # 1) stock_zh_a_spot -> up_count / down_count / amount（一次调用拿 3 个，~20s）
    t0 = time.time()
    try:
        df = safe_call(ak.stock_zh_a_spot)
        if isinstance(df, Exception) or df is None or len(df) == 0:
            print(f"  [intraday] stock_zh_a_spot 失败/空: "
                  f"{df if isinstance(df, Exception) else 'empty'} ({time.time()-t0:.1f}s)", flush=True)
        else:
            up = int((df["涨跌幅"] > 0).sum())
            down = int((df["涨跌幅"] < 0).sum())
            amount = float(df["成交额"].sum()) / 1.0e8  # 元 -> 亿元
            upsert_metric(today, "a_width_up_count", up, source="intraday")
            upsert_metric(today, "a_width_down_count", down, source="intraday")
            upsert_metric(today, "a_amount", amount, source="intraday")
            results.update(up_count=up, down_count=down, amount=round(amount, 2))
            print(f"  [intraday] spot: up={up} down={down} amount={amount:.0f}亿 "
                  f"({time.time()-t0:.1f}s)", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"  [intraday] stock_zh_a_spot 异常（不阻断）: {type(e).__name__} {e} "
              f"({time.time()-t0:.1f}s)", flush=True)

    # 2) stock_zt_pool_em -> zt_count + max_lianban（涨停池，盘中实时封板口径）
    t0 = time.time()
    try:
        df = safe_call(ak.stock_zt_pool_em, date=today)
        if isinstance(df, Exception) or df is None or len(df) == 0:
            print(f"  [intraday] stock_zt_pool_em 失败/空 ({time.time()-t0:.1f}s)", flush=True)
        else:
            zt = int(len(df))
            lianban = None
            if "连板数" in df.columns and len(df):
                lianban = int(df["连板数"].max())
            upsert_metric(today, "a_width_zt_count", zt, source="intraday")
            if lianban is not None:
                upsert_metric(today, "a_width_max_lianban", lianban, source="intraday")
            results.update(zt_count=zt, max_lianban=lianban)
            print(f"  [intraday] zt_pool: zt={zt} max_lianban={lianban} "
                  f"({time.time()-t0:.1f}s)", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"  [intraday] stock_zt_pool_em 异常（不阻断）: {type(e).__name__} {e} "
              f"({time.time()-t0:.1f}s)", flush=True)

    # 3) stock_zt_pool_dtgc_em -> dt_count（跌停池）
    t0 = time.time()
    try:
        df = safe_call(ak.stock_zt_pool_dtgc_em, date=today)
        if isinstance(df, Exception) or df is None or len(df) == 0:
            print(f"  [intraday] stock_zt_pool_dtgc_em 失败/空 ({time.time()-t0:.1f}s)", flush=True)
        else:
            dt = int(len(df))
            upsert_metric(today, "a_width_dt_count", dt, source="intraday")
            results["dt_count"] = dt
            print(f"  [intraday] dt_pool: dt={dt} ({time.time()-t0:.1f}s)", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"  [intraday] stock_zt_pool_dtgc_em 异常（不阻断）: {type(e).__name__} {e} "
              f"({time.time()-t0:.1f}s)", flush=True)

    # 4) stock_zt_pool_zbgc_em -> zhaban_rate = 炸板数/(涨停数+炸板数)（ratio 0-1，与收盘口径一致）
    t0 = time.time()
    try:
        df = safe_call(ak.stock_zt_pool_zbgc_em, date=today)
        if isinstance(df, Exception) or df is None or len(df) == 0:
            print(f"  [intraday] stock_zt_pool_zbgc_em 失败/空 ({time.time()-t0:.1f}s)", flush=True)
        else:
            zhaban_n = int(len(df))
            zt_n = results.get("zt_count")
            # zt_count 可能本函数采到也可能失败（fallback 查 DB 当日值）
            if zt_n is None:
                row = conn.execute(
                    "SELECT value FROM daily_metric WHERE metric_id='a_width_zt_count' "
                    "AND date=? AND value IS NOT NULL",
                    (today,),
                ).fetchone()
                zt_n = int(row["value"]) if row else None
            denom = (zt_n + zhaban_n) if zt_n is not None else None
            zhaban_rate = (zhaban_n / denom) if denom and denom > 0 else None
            if zhaban_rate is not None:
                upsert_metric(today, "a_width_zhaban_rate", zhaban_rate, source="intraday")
            results.update(zhaban_count=zhaban_n,
                          zhaban_rate=round(zhaban_rate, 4) if zhaban_rate is not None else None)
            rate_str = f"{zhaban_rate:.4f}" if zhaban_rate is not None else "n/a"
            print(f"  [intraday] zhaban_pool: zhaban={zhaban_n} zt={zt_n} "
                  f"rate={rate_str} ({time.time()-t0:.1f}s)", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"  [intraday] stock_zt_pool_zbgc_em 异常（不阻断）: {type(e).__name__} {e} "
              f"({time.time()-t0:.1f}s)", flush=True)

    conn.close()

    # 5) volume_ratio 重算（基于 a_amount -> a_volume_ratio/ma5/ma20/signal）
    #    需 index_daily 当日 sh pct_change（_backfill_index_daily 已先执行）
    if results.get("amount") is not None:
        try:
            volume_ratio.compute_volume_ratio(verbose=False)
            print("  [intraday] volume_ratio 重算完成（基于盘中 a_amount）", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"  [intraday] volume_ratio 重算失败（不阻断）: {type(e).__name__} {e}", flush=True)

    print(f"  [intraday] width 指标采集完成：{len(results)} 项", flush=True)
    return results


def _recompute_scores() -> None:
    """反哺后重算 6 个 per-index 情绪分 + 恐贪指数 + a_sentiment + cross_market。

    per-index 情绪分（sentiment_sz50/hs300/csi500/csi1000/cyb/kc50）依赖 index_daily OHLC，
    反哺当日数据后重算即可得到当日值。恐贪 = 8 子情绪分等权平均，6 个 per-index 更新后
    连同已有的 a_sentiment + cross_market 合成恐贪当日值。

    a_sentiment 依赖 width/fund 指标（涨跌家数/涨停/成交额/北向等）。P3-D 起盘中
    _collect_intraday_width_metrics 已采这些 daily_metric 并 source='intraday'，故重算能
    产生当日值（ratio/zt/zhaban/amount 4+ 分项 >= 3 出分）。cross_market 同理（依赖全部
    simple 指标，trim_mean 去 max/min）。重算失败不阻断（已有历史值不受影响，UPSERT 幂等）。
    """
    from ..compute import sentiment, fear_greed, cross

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

    # 重算 a_sentiment + cross_market（保持与 per-index 同步；盘中 width/fund 数据可能不全，
    # 不足分项则不出当日值，但不影响已有历史，UPSERT 幂等）
    try:
        asent_score, asent_comps = sentiment.compute()
        n_asent = sentiment.store(asent_score, asent_comps, score_id="a_sentiment")
        last_val = round(float(asent_score.dropna().iloc[-1]), 2) if not asent_score.dropna().empty else None
        last_date = asent_score.dropna().index[-1] if not asent_score.dropna().empty else "?"
        print(f"  [intraday] a_sentiment: {n_asent}天, 末日={last_date}={last_val}", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"  [intraday] a_sentiment 重算失败（不阻断）: {type(e).__name__} {e}", flush=True)

    try:
        cross_score, cross_comps = cross.compute()
        n_cross = cross.store(cross_score, cross_comps)
        last_val = round(float(cross_score.dropna().iloc[-1]), 2) if not cross_score.dropna().empty else None
        last_date = cross_score.dropna().index[-1] if not cross_score.dropna().empty else "?"
        print(f"  [intraday] cross_market: {n_cross}天, 末日={last_date}={last_val}", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"  [intraday] cross_market 重算失败（不阻断）: {type(e).__name__} {e}", flush=True)


def _recompute_rotation() -> None:
    """重算板块轮动速度（sw_ 行业 + thsc_ 概念），写入 daily_metric。

    依赖 index_daily 的 sw_/thsc_ 当日 pct_change（_backfill_industry_daily +
    _backfill_concept_daily 已写入）。显式传 date=today：即使某类板块反哺部分
    失败（如行业 summary 挂但概念成功），也能算出已就绪类别的当日轮动速度，
    不依赖 compute_rotation 默认从 sw_df 推断日期（推断取 sw_ 末日，行业未反哺
    时会停在 T-1）。盘中算出当日速度后，export_rotation 导出的 rotation.json
    才含当日行 + 当日领涨 top3。compute_rotation 读 index_daily 全量算 leader
    变化，store_rotation 写当日 6 个指标（source='derived'，收盘 pipeline 覆盖）。
    失败不阻断。仅交易日调用（由 collect_and_save 的 n_ind/n_concept>0 门控）。
    """
    from ..compute.rotation import compute_rotation, store_rotation

    try:
        today = datetime.now().strftime("%Y%m%d")
        result = compute_rotation(date=today)
        n = store_rotation(result)
        print(f"  [intraday] rotation 重算: {n} 指标, date={result.get('date')} "
              f"sw_leader={result.get('sw_leader')} concept_leader={result.get('concept_leader')}",
              flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"  [intraday] rotation 重算失败（不阻断）: {type(e).__name__} {e}", flush=True)


def _export_affected_json() -> None:
    """重算后 dump 受影响的静态 JSON（双版同步：static-site/data/）。

    导出：overview + sentiment(5 ranges) + 9 指数 detail + hk + a-stock + global
    + industry-all 拆分（31 行业折线 + 27 概念 + meta 热力图）+ rotation，
    让 static-site 的恐贪/情绪分/指数 sparkline/大盘 tab/行业概念轮动都到当日盘中。
    a-stock 重导后指数图和 width 指标反映盘中最新值（解决大盘 A 股 tab 冻结在早盘）。
    industry-all / rotation 盘中导出含当日实时行：行业/概念已反哺 index_daily，
    前端读这些 JSON 即可盘中可见当日（无需改前端读快照）。
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

    # 9 指数 detail（反哺的指数 OHLC + signals，含港股 hsi/hstech/hscei）
    affected = list(_SNAPSHOT_TO_INDEX_ID.values())
    for iid in affected:
        export_mod.write_json(export_mod.INDEX_DIR / f"{iid}-all.json",
                              export_mod.export_index_detail(conn, cfg, iid))

    # hk tab JSON（含港股指数 OHLC + 港股通；港股反哺后需更新）
    for rng in export_mod.ALL_RANGES:
        export_mod.write_json(export_mod.DATA_DIR / f"hk-{rng}.json",
                              export_mod.export_hk(conn, cfg, rng))

    # a-stock（大盘A股tab，复用 export_a_stock；指数图 + width 指标到当日盘中值）
    # a-stock 读 index_daily（已反哺到当日）+ daily_metric（width 类已采到当日），
    # 重导后指数图和 width 指标反映盘中最新值（解决大盘 A 股 tab 冻结在早盘的问题）。
    for rng in export_mod.ALL_RANGES:
        try:
            export_mod.write_json(export_mod.DATA_DIR / f"a-stock-{rng}.json",
                                  export_mod.export_a_stock(conn, cfg, rng))
        except Exception as e:  # noqa: BLE001
            print(f"  [intraday] a-stock-{rng} 导出失败（不阻断）: {type(e).__name__} {e}", flush=True)

    # global（大盘全球tab，复用 export_global；外盘 T+1 重导意义不大但保持完整性）
    for rng in export_mod.ALL_RANGES:
        try:
            export_mod.write_json(export_mod.DATA_DIR / f"global-{rng}.json",
                                  export_mod.export_global(conn, cfg, rng))
        except Exception as e:  # noqa: BLE001
            print(f"  [intraday] global-{rng} 导出失败（不阻断）: {type(e).__name__} {e}", flush=True)

    # industry-all 拆分（31 行业折线图 + 27 概念 + meta 热力图）
    # 行业/概念已反哺 index_daily 当日行，重导后 industry-all-indices/* 和
    # industry-all-concepts.json 含当日实时行 -> 前端行业折线/概念列表盘中可见。
    try:
        export_mod.write_industry_all_split(conn, cfg)
    except Exception as e:  # noqa: BLE001
        print(f"  [intraday] industry-all 拆分导出失败（不阻断）: {type(e).__name__} {e}", flush=True)

    # rotation（轮动速度 + 当日领涨 top3；_recompute_rotation 已写当日 daily_metric）
    try:
        export_mod.write_json(export_mod.DATA_DIR / "rotation.json",
                              export_mod.export_rotation(conn))
    except Exception as e:  # noqa: BLE001
        print(f"  [intraday] rotation 导出失败（不阻断）: {type(e).__name__} {e}", flush=True)

    conn.close()
    print(f"  [intraday] 静态 JSON dump 完成：overview + sentiment×5 + index detail×{len(affected)} "
          f"+ hk×{len(export_mod.ALL_RANGES)} + a-stock×{len(export_mod.ALL_RANGES)} "
          f"+ global×{len(export_mod.ALL_RANGES)} + industry-all 拆分 + rotation",
          flush=True)


def build_snapshot() -> dict:
    """采集 + 组装快照 dict（不落库）。供 collect_and_save 和 API 共用。

    在采集前捕获 collected_at，传给 is_market_closed/is_hk_market_closed，
    使 JSON 里的 is_closed/label 反映"这份数据的时效"而非"写入时的时钟"
    （采集行业 summary 可能 20s+，跨 11:30 边界时 now 已进午休但数据是上午盘中的）。
    """
    collected_dt = datetime.now()  # 采集起始时刻 = 数据时间
    indices = fetch_index_realtime()
    industries = fetch_industry_realtime()
    concepts = fetch_concept_realtime()
    is_closed, label = is_market_closed(at=collected_dt)
    is_hk_closed, _ = is_hk_market_closed(at=collected_dt)
    # 给每条指数加 is_closed（A 股按 15:00 判断，港股按 16:00 判断）
    for d in indices:
        code = d.get("code", "")
        d["is_closed"] = is_hk_closed if code.startswith("hk") else is_closed
    # prev_trading_day: 快照日的前一个交易日(YYYYMMDD)，供前端 pending 角标判断
    # 卡片 dataDate == prev_trading_day 为正常 T+1，< 则为数据滞后(采集断了)
    # 用交易日历而非自然日差值，避免周末/节假日误判
    from ..calendar import last_trading_day
    prev_td = last_trading_day(collected_dt.date() - timedelta(days=1))
    # 美股期货 ES/NQ（亚盘实时，预估美股当晚方向）。CME GLOBEX 电子盘北京白天仍交易，
    # ES/NQ 实时价反映美股当晚预期。失败不阻断快照（快照核心是 A 股/港股/行业）。
    us_futures = {}
    try:
        from .us_futures import fetch_us_futures
        from ..compute.us_futures_expect import compute_expect
        us_futures = compute_expect(fetch_us_futures())
        if us_futures:
            print(f"[intraday] 美股期货采集: ES={us_futures.get('hf_ES', {}).get('chg_pct'):.2f}% "
                  f"NQ={us_futures.get('hf_NQ', {}).get('chg_pct'):.2f}%", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"[intraday] 美股期货采集失败（不阻断）: {type(e).__name__} {e}", flush=True)
    return {
        "collected_at": collected_dt.isoformat(),
        "is_closed": is_closed,
        "label": label,
        "prev_trading_day": prev_td,
        "indices": indices,
        "industries": industries,
        "concepts": concepts,
        "us_futures": us_futures,
    }


def collect_and_save() -> dict:
    """采集 + 存 DB + dump 静态 JSON。返回快照 dict。

    采集完腾讯实时 12 指数（9 A 股 + 3 港股）后，把当日 OHLC 反哺 index_daily 表
    （UPSERT），再重算 per-index 情绪分 + 恐贪指数，最后 dump 受影响的静态 JSON，
    使指数卡片/恐贪/per-index 情绪分都能到当日（解决 T+1 延迟致停在 T-2 的问题）。
    港股盘中（15:35 快照）反哺实时价作为 close，17:50 update_all 覆盖为收盘价。
    反哺/重算/export 失败不阻断快照本身（快照已落库落盘）。
    """
    print(f"[intraday] 开始采集盘中实时快照 {datetime.now():%Y-%m-%d %H:%M:%S}", flush=True)
    t0 = time.time()

    snap = build_snapshot()

    # 存 DB
    _save_db(snap["collected_at"], snap["is_closed"],
             snap["indices"], snap["industries"], snap["concepts"],
             snap.get("us_futures"))

    # 美股期货 ES/NQ 预期信号落地 daily_metric（供历史回测/统计）。失败不阻断。
    if snap.get("us_futures"):
        try:
            from ..compute.us_futures_expect import save_to_db as _save_usf
            n_usf = _save_usf(datetime.now().strftime("%Y%m%d"), snap["us_futures"])
            if n_usf:
                print(f"[intraday] 美股期货预期落地 daily_metric {n_usf} 条", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[intraday] 美股期货落地 DB 失败（不阻断）: {type(e).__name__} {e}", flush=True)

    # dump 静态 JSON（双版同步：static-site/data/intraday_snapshot.json）
    STATIC_DATA_DIR.mkdir(parents=True, exist_ok=True)
    out_path = STATIC_DATA_DIR / "intraday_snapshot.json"
    text = json.dumps(snap, ensure_ascii=False, separators=(",", ":"))
    out_path.write_text(text, encoding="utf-8")

    dt = time.time() - t0
    print(f"[intraday] 快照完成：{len(snap['indices'])} 指数（9 A 股 + 3 港股） / "
          f"{len(snap['industries'])} 行业 / {len(snap['concepts'])} 概念 "
          f"({snap['label']})，{dt:.1f}s -> {out_path.name}", flush=True)

    # 反哺 index_daily + 盘中采 width 指标 + 重算情绪分/恐贪/轮动 + dump 静态 JSON
    # 失败不阻断快照本身（快照已落库落盘，反哺是增强）
    try:
        n_backfill = _backfill_index_daily(snap["indices"])
        # 盘中采 width/fund 指标（涨停/跌停/炸板率/成交额/涨跌家数）+ volume_ratio 重算
        # 需在 _backfill_index_daily 之后（volume_ratio 依赖当日 sh pct_change）
        width_res: dict = {}
        try:
            width_res = _collect_intraday_width_metrics()
        except Exception as e:  # noqa: BLE001
            print(f"[intraday] width 指标采集失败（不阻断）: {type(e).__name__} {e}", flush=True)
        width_n = len(width_res)
        n_ind = _backfill_industry_daily(snap["industries"])
        n_concept = _backfill_concept_daily(snap["concepts"])
        # 重算：指数反哺 或 width 指标采集 都触发（width 有当日值后 a_sentiment/cross_market 能出分）
        if n_backfill > 0 or width_n > 0:
            _recompute_scores()
        # 行业/概念反哺后重算轮动速度（rotation.json 才有当日行 + 当日领涨 top3）
        if n_ind > 0 or n_concept > 0:
            _recompute_rotation()
        if n_backfill > 0 or n_ind > 0 or n_concept > 0 or width_n > 0:
            _export_affected_json()
            print(f"[intraday] 反哺+width+重算+export 完成"
                  f"（{n_backfill} 指数 + {n_ind} 行业 + {n_concept} 概念反哺 + {width_n} width 指标）",
                  flush=True)
        else:
            print(f"[intraday] 无反哺（非交易日或快照非当日），跳过重算", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"[intraday] 反哺/重算/export 失败（快照已保存）: {type(e).__name__} {e}", flush=True)

    return snap


def load_latest_snapshot() -> dict | None:
    """从 DB 读最新快照（供 API / export 用）。无数据返 None。

    label 基于 collected_at 重构（时间+数据双重判断在读端同样生效）：
    DB 只存 is_closed（0/1），label 由 is_market_closed(at=collected_at) 推导，
    这样午休采的快照读出来 label 仍是"午休·盘中暂停"而非丢失成"盘中实时小结"。
    """
    conn = get_conn()
    row = conn.execute(
        "SELECT collected_at, is_closed, indices, industries, concepts, us_futures "
        "FROM intraday_snapshot WHERE id=1"
    ).fetchone()
    conn.close()
    if not row:
        return None
    is_closed = bool(row["is_closed"])
    # 基于 collected_at 重构 label（时间+数据双重判断）
    # 同时算 prev_trading_day(上一交易日)，供前端 pending 角标判断数据是否滞后
    prev_td = ""
    try:
        collected_dt = datetime.fromisoformat(row["collected_at"])
        _, label = is_market_closed(at=collected_dt)
        from ..calendar import last_trading_day
        prev_td = last_trading_day(collected_dt.date() - timedelta(days=1))
    except Exception:  # noqa: BLE001
        label = "收盘快照" if is_closed else "盘中实时小结"
    try:
        indices = json.loads(row["indices"])
    except Exception:  # noqa: BLE001
        indices = []
    try:
        industries = json.loads(row["industries"])
    except Exception:  # noqa: BLE001
        industries = []
    # concepts 列可能不存在于旧 DB（迁移前），用 keys 兜底
    try:
        concepts = json.loads(row["concepts"]) if row["concepts"] else []
    except Exception:  # noqa: BLE001
        concepts = []
    # us_futures 列同理（2026-07-15 加，美股期货 ES/NQ 预估美股方向）
    try:
        us_futures = json.loads(row["us_futures"]) if row["us_futures"] else {}
    except Exception:  # noqa: BLE001
        us_futures = {}
    return {
        "collected_at": row["collected_at"],
        "is_closed": is_closed,
        "label": label,
        "prev_trading_day": prev_td,
        "indices": indices,
        "industries": industries,
        "concepts": concepts,
        "us_futures": us_futures,
    }


def snapshot_industry_heatmap(snap: dict) -> list[dict]:
    """把盘中快照的行业数据转为 heatmap 结构（用于覆盖 DB 的盘中行业，P2-B）。

    snap.industries 有 {sw_code, sw_name, pct_change, net_inflow, lead_stock}，
    转为 {id, name, pct_1d, pct_5d(NULL), net_inflow, lead_stock, last_date}。
    pct_5d 盘中无法计算（snap 无 OHLC 历史），置 NULL，前端 renderIndustryHeatmap
    已兼容 pct_5d=null（只显 pct_1d，格子显"-"）。
    net_inflow/lead_stock 是 heatmap 原本没有的增强字段（盘中实时），前端 tooltip按需展示。
    """
    if not snap:
        return []
    collected_at = snap.get("collected_at", "")
    # ISO "2026-07-14T11:30..." -> "20260714"
    last_date = collected_at[:10].replace("-", "") if len(collected_at) >= 10 else ""
    out = []
    for ind in snap.get("industries", []):
        out.append({
            "id": ind.get("sw_code"),
            "name": ind.get("sw_name"),
            "pct_1d": ind.get("pct_change"),
            "pct_5d": None,
            "net_inflow": ind.get("net_inflow"),
            "lead_stock": ind.get("lead_stock"),
            "last_date": last_date,
        })
    return out


def maybe_override_heatmap(heatmap: list[dict]) -> list[dict]:
    """盘中时用快照行业覆盖 heatmap 的实时字段（P2-B）；收盘或无今日快照时返回原 heatmap。

    MERGE 而非 REPLACE：保留 DB heatmap 的 pct_5d（盘中已用累乘法算出），
    仅用快照的 pct_1d / net_inflow / lead_stock 覆盖实时字段。
    snap 缺 pct_5d 但多 net_inflow + lead_stock，前端 tooltip 兼容。
    """
    try:
        is_closed, _ = is_market_closed()
        if is_closed:
            return heatmap
        snap = load_latest_snapshot()
        if not snap:
            return heatmap
        collected_at = snap.get("collected_at", "")
        today = datetime.now().strftime("%Y-%m-%d")
        if not collected_at.startswith(today):
            return heatmap
        snap_hm = snapshot_industry_heatmap(snap)
        if not snap_hm:
            return heatmap
        # MERGE: 把 snap 的实时字段(pct_1d/net_inflow/lead_stock)叠加到 DB heatmap 上，
        # 保留 DB 的 pct_5d（累乘法已算出），避免盘中近5日被清空。
        snap_map = {h["id"]: h for h in snap_hm}
        for h in heatmap:
            sh = snap_map.get(h["id"])
            if sh:
                h["pct_1d"] = sh.get("pct_1d")
                h["net_inflow"] = sh.get("net_inflow")
                h["lead_stock"] = sh.get("lead_stock")
                h["last_date"] = sh.get("last_date", h.get("last_date"))
        return heatmap
    except Exception as e:  # noqa: BLE001
        print(f"  [intraday] maybe_override_heatmap 失败（回退 DB heatmap）: {type(e).__name__} {e}", flush=True)
        return heatmap


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="盘中实时快照采集")
    parser.add_argument("--date", type=str, default=None,
                        help="补采指定日期(YYYYMMDD)的申万行业 close，不采集新快照")
    args = parser.parse_args()

    if args.date:
        # 历史补采模式：只补 industry close，不覆盖今日 intraday_snapshot
        n = _backfill_industry_daily([], target_date=args.date)
        print(f"[intraday] 历史补采完成：{args.date} 共补 {n} 条行业 close", flush=True)
    else:
        collect_and_save()
