"""指数采集多源补采。

主源（新浪 stock_zh_index_daily）采完后，校验 8 个核心 A 股指数今日数据是否到位，
缺失则按 baostock -> 腾讯 回退补采。避免单一数据源当日延迟导致：
  - 首页一句话总结「上证涨幅 0.00%」（index_daily 缺今日 sh）
  - KPI 卡片少恐贪指数（per-index 情绪分缺今日 -> fear_greed 缺今日）

数据源（2026-07 实测）：
  新浪 stock_zh_index_daily   全覆盖，close/pct，快         主源
  baostock                    7/8（缺科创50），字段全含pctChg  备用1
  腾讯 stock_zh_index_daily_tx 全覆盖，无pct(自算)，慢(12s/只)  备用2
  东财 index_zh_a_hist / _em   均被封 RemoteDisconnected       弃用

申万一级行业指数（31 个 sw_801xxx）额外补采：
  申万官方 trend API（swsresearch.com）返全量历史，但 T+1 发布延迟（周五数据
  可能要到周一才更新）。新浪/腾讯/baostock/mootdx 均不支持申万行业指数代码，
  东财被封。故 sw_* 只能依赖申万官方源，补采 = 重拉 trend 全量取最新行。
  工作日采集时 trend API 若已发布当日数据则补上；未发布（T+1 延迟）则跳过
  写告警，下次定时任务再补。

  2026-07-13 起 trend API 持续 SSL 故障，加同花顺聚合兜底（industry_extras.
  _fetch_sw_ohlc_ths，90 子行业聚合 31 一级 + 锚定申万末日避免绝对值跳变）。
  SW_OHLC_SOURCE=="ths" 时跳过申万 trend 直接走同花顺；=="sw" 时走申万（恢复
  后回切）。

同花顺概念指数（thsc_* 27 个）：stock_board_concept_index_ths 历史序列 T+1，
  次日才出当日点。盘后用 stock_board_concept_info_ths(symbol=概念名) 当日快照
  合成 OHLC 补采当日行（open=今开/high=最高/low=最低/close=昨收×(1+涨幅/100)/
  pct=板块涨幅/amount=成交额(亿)×1e8 转元对齐历史序列）。

触发：runner.step2 indices 采完后调用 verify_and_backfill_indices(date)。
"""
from .base import log_collect
from ..db import get_conn

# 9 个核心 A 股指数：(baostock_code, tencent_symbol)
# 这 9 个决定上证涨幅展示 + fear_greed 的 6 个 per-index 情绪分 + 北证50 卡片。
CORE_A_INDICES = {
    "sh":      ("sh.000001", "sh000001"),
    "sz":      ("sz.399001", "sz399001"),
    "hs300":   ("sh.000300", "sh000300"),
    "sz50":    ("sh.000016", "sh000016"),
    "csi500":  ("sh.000905", "sh000905"),
    "csi1000": ("sh.000852", "sh000852"),
    "cyb":     ("sz.399006", "sz399006"),
    "kc50":    ("sh.000688", "sh000688"),  # baostock 无，腾讯补
    "bj50":    (None, "bj899050"),          # baostock 无北证50，腾讯补
}

# 31 个申万一级行业指数代码（symbol 传给申万 trend API）
SW_INDICES = [
    "sw_801010", "sw_801030", "sw_801040", "sw_801050", "sw_801080",
    "sw_801880", "sw_801110", "sw_801120", "sw_801130", "sw_801140",
    "sw_801150", "sw_801160", "sw_801170", "sw_801180", "sw_801200",
    "sw_801210", "sw_801780", "sw_801790", "sw_801230", "sw_801710",
    "sw_801720", "sw_801730", "sw_801890", "sw_801740", "sw_801750",
    "sw_801760", "sw_801770", "sw_801950", "sw_801960", "sw_801970",
    "sw_801980",
]


def _f(v):
    """baostock 返回字符串，转 float；空/无效返 None。"""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _baostock_fetch(bs_code, idx_id, bs_date, date):
    """baostock 查单日，返回 [(date, idx_id, open, high, low, close, pct, amount)] 或 []。"""
    import baostock as bs
    rs = bs.query_history_k_data_plus(
        bs_code, "date,open,high,low,close,pctChg,amount",
        start_date=bs_date, end_date=bs_date, frequency="d",
    )
    if rs.error_code != "0":
        return []
    while rs.next():
        r = rs.get_row_data()  # [date, open, high, low, close, pctChg, amount]
        return [(date, idx_id, _f(r[1]), _f(r[2]), _f(r[3]), _f(r[4]), _f(r[5]), _f(r[6]))]
    return []


def _tencent_fetch(tx_symbol, idx_id, date):
    """腾讯返全量历史，取 date 那行。pct 自算；amount 留 None（腾讯单位与新浪不一致，弃填）。
    慢（~12s/只，全量拉取），仅 baostock 补不到时兜底用（基本只 kc50）。
    返回 [(date, idx_id, open, high, low, close, pct, None)] 或 []。"""
    import akshare as ak
    from datetime import datetime
    df = ak.stock_zh_index_daily_tx(symbol=tx_symbol)
    if df is None or len(df) == 0:
        return []
    target = datetime.strptime(date, "%Y%m%d").date()
    row = df[df["date"] == target]
    if len(row) == 0:
        return []
    r = row.iloc[0]
    close = _f(r["close"])
    open_ = _f(r["open"]); high = _f(r["high"]); low = _f(r["low"])
    # pct 自算：取前一交易日 close
    pct = None
    if close:
        prev = df[df["date"] < target]
        if len(prev):
            pc = _f(prev.iloc[-1]["close"])
            if pc:
                pct = (close / pc - 1) * 100
    return [(date, idx_id, open_, high, low, close, pct, None)]


def _sw_trend_fetch(sw_id, date):
    """申万官方 trend API 补采 sw_* 指数（含 SSL/网络错误重试）。

    swsresearch.com 的 trend API 返全量历史（无 beg/end 参数），取最新行。
    若最新行 == date 则补采成功；若 < date 说明源 T+1 延迟尚未发布当日数据。

    2026-07 实测 SSLEOFError（疑似服务端临时故障）：加 3 次指数退避重试
    (1s/2s/4s)。持续失败不崩，只 warn 日志跳过该行业，不影响其他行业采集，
    等下次定时任务再补。

    返回 [(date, idx_id, open, high, low, close, pct, amount)] 或 []。
    """
    import requests
    import time as _time
    # base.py 已 monkey-patch DNS，但这里用独立 session 避免影响
    symbol = sw_id.replace("sw_", "")
    url = "https://www.swsresearch.com/institute-sw/api/index_publish/trend/"

    # SSL/网络错误重试：1 初始 + 3 重试，指数退避 1s/2s/4s
    _RETRYABLE = ("SSL", "Connection", "Timeout", "Remote", "Protocol", "EOF")
    data = None
    last_err = None
    for attempt in range(4):
        try:
            r = requests.get(url, params={"swindexcode": symbol, "period": "DAY"},
                             headers={"User-Agent": "Mozilla/5.0"}, verify=False, timeout=15)
            data = r.json().get("data", []) or []
            last_err = None
            break
        except Exception as e:
            last_err = e
            ename = type(e).__name__ + " " + str(e)
            if any(k in ename for k in _RETRYABLE) and attempt < 3:
                _time.sleep(2 ** attempt)  # 1s / 2s / 4s
                continue
            break  # 非网络错误（如 JSON 解析失败）不重试

    if last_err is not None:
        log_collect(date, sw_id, "warn",
                    f"申万trend网络故障({type(last_err).__name__}),跳过等下次定时补")
        return []

    if not data:
        log_collect(date, sw_id, "warn",
                    "申万trend返回空data(服务端持续故障?)")
        return []

    # trend API 返全量（升序），取最后一行（最新交易日）
    last = data[-1]
    last_date = str(last.get("bargaindate", ""))[:10].replace("-", "")
    if last_date != date:
        # 源最新数据 != 目标日期（T+1 延迟，周末/节假日未发布）
        return []

    def _tof(v):
        try:
            f = float(v)
            return f if f == f else None  # NaN -> None
        except (TypeError, ValueError):
            return None

    return [(date, sw_id, _tof(last.get("openindex")), _tof(last.get("maxindex")),
             _tof(last.get("minindex")), _tof(last.get("closeindex")),
             _tof(last.get("markup")), _tof(last.get("bargainsum")))]


def _ths_concept_info_fetch(thsc_id, concept_name, date):
    """同花顺概念板块当日快照合成 OHLC 补采。

    stock_board_concept_index_ths 历史序列 T+1（次日才出当日点），盘后用
    stock_board_concept_info_ths(symbol=概念名) 当日快照合成当日行。
    快照返 项目/值 两列 DataFrame，取 今开/昨收/最低/最高/板块涨幅/成交额(亿)。

    合成: open=今开 high=最高 low=最低
          close=昨收×(1+板块涨幅/100) pct=板块涨幅
          amount=成交额(亿)×1e8(转元,对齐 _collect_ths_concept 历史序列入库单位)

    返回 [(date, thsc_id, open, high, low, close, pct, amount)] 或 []。
    """
    import akshare as ak
    try:
        df = ak.stock_board_concept_info_ths(symbol=concept_name)
    except Exception as e:  # noqa: BLE001
        log_collect(date, thsc_id, "warn", f"概念快照获取异常: {e}")
        return []
    if df is None or len(df) == 0:
        return []
    # 快照为 项目/值 两列，转 dict 便于按项目名取值
    d = dict(zip(df["项目"].astype(str), df["值"]))

    def _num(key, strip_pct=False):
        v = d.get(key)
        if v is None:
            return None
        s = str(v).strip()
        if strip_pct:
            s = s.rstrip("%").strip()
        try:
            f = float(s)
            return f if f == f else None  # NaN -> None
        except (TypeError, ValueError):
            return None

    open_ = _num("今开")
    high = _num("最高")
    low = _num("最低")
    pre_close = _num("昨收")
    pct = _num("板块涨幅", strip_pct=True)
    amt_yi = _num("成交额(亿)")  # 单位亿元
    # close 用昨收×(1+涨幅/100)（快照无收盘价字段，反推）
    close = None
    if pre_close is not None and pct is not None:
        close = pre_close * (1 + pct / 100.0)
    # amount 转元对齐历史序列单位
    amount = amt_yi * 1e8 if amt_yi is not None else None
    if close is None:
        return []
    return [(date, thsc_id, open_, high, low, close, pct, amount)]


def verify_and_backfill_indices(date, verbose=True):
    """step2 采后校验：核心 A 股指数 + 申万行业指数今日缺失则多源补采。

    核心A股（sh/sz/cyb/...9个）：新浪主源 -> baostock -> 腾讯 回退。
    申万行业（sw_801xxx 31个）：申万官方 trend API（唯一支持源，T+1 延迟）。

    返回 (ok, fail, details)。补后仍缺 -> collect_log 写 warn（告警，避免下次
    看首页才发现 0%/卡片缺失）。
    """
    bs_date = f"{date[:4]}-{date[4:6]}-{date[6:]}"

    conn = get_conn()

    # ── 1. 核心A股指数校验 ──
    missing = []
    for idx_id in CORE_A_INDICES:
        # 查 date 行 close 完整性而非 max(date): 防御 intraday 反哺半成品行(close=None)骗校验
        r = conn.execute(
            "SELECT close FROM index_daily WHERE index_id=? AND date=?", (idx_id, date)
        ).fetchone()
        if r is None or r["close"] is None:
            missing.append(idx_id)

    ok = 0
    fail = 0
    details = []

    if not missing:
        if verbose:
            print(f"  [校验] {len(CORE_A_INDICES)} 个核心 A 股指数今日({date})齐全 ✓")
    else:
        if verbose:
            print(f"  [校验] {len(missing)} 个指数缺今日 {date}: {missing} -> 多源补采")

        import baostock as bs
        bs.login()
        try:
            # 延迟 import 避免与 runner 循环导入
            from .runner import upsert_index_rows

            for idx_id in missing:
                bs_code, tx_symbol = CORE_A_INDICES[idx_id]
                rows = []
                src = None
                # 1. baostock（kc50/bj50 跳过：baostock 无该指数）
                if bs_code and idx_id != "kc50":
                    rows = _baostock_fetch(bs_code, idx_id, bs_date, date)
                    if rows:
                        src = "baostock"
                # 2. 腾讯兜底
                if not rows:
                    rows = _tencent_fetch(tx_symbol, idx_id, date)
                    if rows:
                        src = "tencent"
                if rows:
                    upsert_index_rows(rows)
                    ok += 1
                    details.append((idx_id, "ok", f"backfill {src} close={rows[0][5]}"))
                    if verbose:
                        print(f"    ✓ {idx_id} <- {src} close={rows[0][5]} pct={rows[0][6]}")
                else:
                    fail += 1
                    details.append((idx_id, "fail", "三源均无今日数据"))
                    log_collect(date, idx_id, "warn",
                                "指数今日数据缺失：新浪主源未取到，baostock+腾讯补采亦失败")
                    if verbose:
                        print(f"    ✗ {idx_id} 补采失败（三源均无）<- 已写告警")
        finally:
            bs.logout()

    # ── 2. 申万一级行业指数（sw_*）补采 ──────────────────────────────────
    # 申万官方 trend API 是唯一支持 sw_* OHLC 历史的源（新浪/腾讯/baostock/
    # mootdx/东财均不支持申万行业指数代码）。主源 index_hist_sw 已在 runner
    # step1 采过，这里只校验今日是否到位，缺失则重拉 trend 全量取最新行补采。
    # 申万源 T+1 发布延迟：周五数据可能要周一才出，未发布则跳过写告警。
    sw_missing = []
    for sw_id in SW_INDICES:
        # 查 date 行 close 完整性而非 max(date): intraday_snapshot._backfill_industry_daily
        # 会写 pct_change 半成品行(close=None),只看日期会被骗漏补采。
        r = conn.execute(
            "SELECT close FROM index_daily WHERE index_id=? AND date=?", (sw_id, date)
        ).fetchone()
        if r is None or r["close"] is None:
            sw_missing.append(sw_id)

    if not sw_missing:
        if verbose:
            print(f"  [校验] {len(SW_INDICES)} 个申万行业指数今日({date})齐全 ✓")
    else:
        if verbose:
            print(f"  [校验] {len(sw_missing)} 个申万行业指数缺今日 {date} -> 申万 trend API 补采")
        from .runner import upsert_index_rows
        from .industry_extras import SW_OHLC_SOURCE, _fetch_sw_ohlc_ths
        for sw_id in sw_missing:
            # SW_OHLC_SOURCE=="ths" 时申万 trend 已知 SSL 故障，跳过省 31×7s 重试
            rows = []
            src = "ths"
            if SW_OHLC_SOURCE == "sw":
                rows = _sw_trend_fetch(sw_id, date)
                src = "sw-trend"
            if not rows:
                # 申万 trend 故障/未发布 -> 同花顺聚合兜底（只取今日那行）
                rows2, _tmsg = _fetch_sw_ohlc_ths(sw_id, date, date)
                rows = [r for r in rows2 if r[0] == date]
                src = "ths"
            if rows:
                upsert_index_rows(rows)
                ok += 1
                details.append((sw_id, "ok", f"backfill {src} close={rows[0][5]}"))
                if verbose:
                    print(f"    ✓ {sw_id} <- {src} close={rows[0][5]} pct={rows[0][6]}")
            else:
                fail += 1
                details.append((sw_id, "fail", "申万源故障且同花顺当日未发布"))
                if verbose:
                    print(f"    - {sw_id} 申万源故障/同花顺当日未发布，下次定时任务再补")

    # ── 3. 同花顺概念指数（thsc_*）补采 ──────────────────────────────────
    # stock_board_concept_index_ths 历史序列 T+1（次日才出当日点），盘后用
    # stock_board_concept_info_ths 当日快照合成 OHLC 补采当日行（见上方
    # _ths_concept_info_fetch）。概念配置从 indicators.yaml 读 enabled thsc_ 项。
    from . import fetchers as _fetchers_mod
    _concept_cfg = _fetchers_mod.load_config()
    _thsc_cfgs = [i for i in _concept_cfg.get("indices", [])
                  if i.get("id", "").startswith("thsc_") and i.get("enabled", True)]
    thsc_missing = []
    for tc in _thsc_cfgs:
        r = conn.execute(
            "SELECT close FROM index_daily WHERE index_id=? AND date=?", (tc["id"], date)
        ).fetchone()
        if r is None or r["close"] is None:
            thsc_missing.append(tc)
    if not thsc_missing:
        if verbose:
            print(f"  [校验] {len(_thsc_cfgs)} 个概念指数今日({date})齐全 ✓")
    else:
        if verbose:
            print(f"  [校验] {len(thsc_missing)} 个概念指数缺今日 {date} -> 同花顺快照合成补采")
        from .runner import upsert_index_rows
        for tc in thsc_missing:
            rows = _ths_concept_info_fetch(tc["id"], tc["symbol"], date)
            if rows:
                upsert_index_rows(rows)
                ok += 1
                details.append((tc["id"], "ok", f"backfill ths-snapshot close={rows[0][5]} pct={rows[0][6]}"))
                if verbose:
                    print(f"    ✓ {tc['id']} <- ths-snapshot close={rows[0][5]} pct={rows[0][6]}")
            else:
                fail += 1
                details.append((tc["id"], "fail", "同花顺概念快照获取失败"))
                if verbose:
                    print(f"    - {tc['id']} 同花顺快照获取失败，下次定时任务再补")

    # ── 4. 港股+全球指数校验补采 ──────────────────────────────────────────
    # 港股(hsi/hstech/hscei)走新浪全量源 stock_hk_index_daily_sina,16:00收盘后出当日。
    # 美股(us_dji/us_ixic/us_spx/us_ndx)走 index_us_stock_sina,北京时差晚21:30+才开盘,
    # A股交易日时美股最新通常是T-1或T-2(跨周末),不强求当日,校验"最新日期距今<=3天"(覆盖跨周末)即可。
    # 根因: backfill 之前只管A股核心9+申万31,港股美股漏采(17:50没跑就卡T-1)。
    HK_GLOBAL_INDICES = [
        ("hsi", "hsi", True),      # (id, symbol, require_today)
        ("hstech", "HSTECH", True),
        ("hscei", "HSCEI", True),
        # 港股板块指数（market: hk_industry，新浪全量源，无腾讯兜底）
        ("hk_cesg10", "CESG10", True),
        ("hk_hsmogi", "HSMOGI", True),
        ("hk_hsmbi", "HSMBI", True),
        ("hk_hsmpi", "HSMPI", True),
        ("hk_cshklre", "CSHKLRE", True),
        ("hk_cshklc", "CSHKLC", True),
        ("hk_hscci", "HSCCI", True),
        ("hk_cshkdiv", "CSHKDIV", True),
        ("us_dji", ".DJI", False),
        ("us_ixic", ".IXIC", False),
        ("us_spx", ".INX", False),
        ("us_ndx", ".NDX", False),
        # 5 全球指数(2026-07-16 daf06e77 上线, func=index_global_hist_sina)
        # require_today=False: 源(sina)有时延T+1发布(如7-20数据7-21午后才出),
        # 用 (today-last)>3 天阈值覆盖跨周末+源延迟, 避免误报fail。
        # nikkei225: 7/20 日本海之日假期源无数据, 阈值检查不会误报。
        ("nikkei225", "日经225指数", False),
        ("kospi", "首尔综合指数", False),
        ("ftse100", "英国富时100指数", False),
        ("dax", "德国DAX 30种股价指数", False),
        ("cac40", "法CAC40指数", False),
    ]
    from . import fetchers as _fetchers_mod
    from datetime import datetime as _dt, timedelta as _td
    # 港股段 backfill 用：upsert_index_rows 在上方核心A股/申万/概念三段的 else
    # 分支内延迟 import，当前三段全齐全(走 if not missing 不进 else)时那些
    # import 不执行，upsert_index_rows 作为本函数局部变量从未绑定，448 行调用
    # 会 UnboundLocalError。这里补一次 import 保证无论前三段是否齐全都已绑定。
    from .runner import upsert_index_rows
    cfg = _fetchers_mod.load_config()
    idx_cfg_map = {i["id"]: i for i in cfg.get("indices", []) if i.get("enabled", True)}
    for idx_id, _sym, require_today in HK_GLOBAL_INDICES:
        idx_cfg = idx_cfg_map.get(idx_id)
        if idx_cfg is None:
            continue
        r = conn.execute(
            "SELECT date, close, amount FROM index_daily WHERE index_id=? ORDER BY date DESC LIMIT 1",
            (idx_id,)
        ).fetchone()
        need_backfill = False
        if r is None or r["close"] is None:
            need_backfill = True
        elif require_today:
            if r["date"] != date:
                need_backfill = True
            # 港股盘中快照写入 amount=NULL（收盘前价格），需补采收盘数据。
            # 新浪源收盘后延迟发布当日数据，用腾讯实时源兜底拿收盘价+成交额。
            elif r["amount"] is None and idx_id in ("hsi", "hstech", "hscei"):
                need_backfill = True
        else:
            # 美股: 覆盖跨周末即可(周五收盘->周一采集=3天),T+1第二天就该采到昨日。
            # 长假(国庆等)期间 backfill 每天跑会逐步补上,不卡死。
            try:
                last_d = _dt.strptime(r["date"], "%Y%m%d").date()
                today_d = _dt.strptime(date, "%Y%m%d").date()
                if (today_d - last_d).days > 3:
                    need_backfill = True
            except (ValueError, TypeError):
                need_backfill = True
        if not need_backfill:
            continue
        # 新浪全量拉取 UPSERT(collect_index 拉全量,有当日就入没就跳)
        rows, msg = _fetchers_mod.collect_index(idx_cfg, "20200101", date)
        has_today = rows and any(r[0] == date for r in rows)
        if has_today:
            upsert_index_rows(rows)
            # 取最新行确认
            latest = conn.execute(
                "SELECT date, close FROM index_daily WHERE index_id=? ORDER BY date DESC LIMIT 1",
                (idx_id,)
            ).fetchone()
            ok += 1
            details.append((idx_id, "ok", f"backfill 新浪 close={latest['close']} date={latest['date']}"))
            if verbose:
                print(f"    ✓ {idx_id} <- 新浪 close={latest['close']} date={latest['date']}")
        elif idx_id in ("hsi", "hstech", "hscei") or idx_id.startswith("hk_"):
            # 新浪无当日数据（收盘后延迟发布）-> 腾讯实时源兜底
            # 港股板块5个(cesg10/hsmogi/hsmbi/hsmpi/hscci)已纳入 _HK_CODE_MAP 可兜底；
            # 3个中证指数(cshklre/cshklc/cshkdiv)腾讯无代码，_tencent_hk_fallback 安全返回 False
            if rows:
                upsert_index_rows(rows)  # 仍 UPSERT 历史数据
            fixed = _tencent_hk_fallback(idx_id, date, conn, verbose)
            if fixed:
                ok += 1
                details.append((idx_id, "ok", f"backfill 腾讯兜底 date={date}"))
            else:
                fail += 1
                details.append((idx_id, "fail", f"新浪无当日+腾讯兜底失败: {msg}"))
                if verbose:
                    print(f"    ✗ {idx_id} 新浪无当日({msg}), 腾讯兜底也失败")
        else:
            fail += 1
            details.append((idx_id, "fail", f"新浪源空: {msg}"))
            if verbose:
                print(f"    ✗ {idx_id} 新浪源空({msg})")

    # 港股美股校验汇总(已齐全的不打印上面跳过了,这里给个汇总行)
    if verbose:
        print(f"  [校验] 港股+全球指数({len(HK_GLOBAL_INDICES)}个) 最新日期检查完成")

    conn.close()
    return ok, fail, details


def _tencent_hk_fallback(idx_id: str, date: str, conn, verbose: bool = False) -> bool:
    """腾讯实时源港股兜底：新浪无当日数据时，用腾讯拿收盘价+成交额写入 index_daily。

    港股 16:00 收盘后腾讯返收盘价（price=收盘, pct=当日涨跌幅, field[6]=成交额万港元）。
    盘中（<16:00）返实时价，不写（避免盘中价覆盖）。
    返回 True=写入成功, False=未写入（盘中/数据异常）。
    """
    import requests
    # 腾讯实时源支持的港股指数代码映射（r_hk + 新浪 symbol 大写）。
    # 宽基3个 + 港股板块5个（恒生/中华系列，腾讯 qt.gtimg.cn 实测支持，字段结构与宽基一致）。
    # 港股板块共8个，其中3个中证指数(cshklre/cshklc/cshkdiv)腾讯无对应代码(实测 r_hkCSHKLRE
    # /r_hkCSHKLC/r_hkCSHKDIV 等多种格式均 v_pv_none_match)，不在此映射，保持新浪单点。
    _HK_CODE_MAP = {
        "hsi": "r_hkHSI", "hstech": "r_hkHSTECH", "hscei": "r_hkHSCEI",
        "hk_cesg10": "r_hkCESG10",   # 中华博彩
        "hk_hsmogi": "r_hkHSMOGI",   # 恒生内地油气
        "hk_hsmbi":  "r_hkHSMBI",    # 恒生内地银行
        "hk_hsmpi":  "r_hkHSMPI",    # 恒生内地房地产
        "hk_hscci":  "r_hkHSCCI",    # 红筹指数
    }
    tencent_code = _HK_CODE_MAP.get(idx_id)
    if not tencent_code:
        return False
    try:
        # 与 intraday_snapshot 一致：http + gbk 解码（requests 不会自动识别腾讯 GBK 编码，
        # 默认 latin-1 会乱码；数字字段是 ASCII 不影响解析，但 gbk 才正确）
        resp = requests.get(f"http://qt.gtimg.cn/q={tencent_code}",
                            headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        vals = resp.content.decode("gbk", errors="replace").split('"', 2)[1].split("~")
        if len(vals) < 35:
            return False
    except Exception:  # noqa: BLE001
        return False

    def f(i):
        try:
            return float(vals[i])
        except (IndexError, ValueError):
            return None

    # datetime 校验：必须是当日（腾讯港股格式 YYYY/MM/DD HH:MM:SS）
    dtstr_raw = vals[30].strip() if len(vals) > 30 else ""
    snap_date = dtstr_raw[:10].replace("/", "") if "/" in dtstr_raw else dtstr_raw[:8]
    if snap_date != date:
        if verbose:
            print(f"    ~ {idx_id} 腾讯兜底: 日期 {snap_date} != {date}，跳过")
        return False

    price = f(3)
    if price is None:
        return False
    open_ = f(5)
    amt_wan = f(6)  # 成交额(万港元)
    amount = amt_wan * 10000 if amt_wan is not None else None
    change = f(31)
    pct = f(32)
    pre_close = f(4)
    # pct 符号兜底
    if price and pre_close and pre_close != 0:
        if pct is None or (change is not None and abs(pct) < 1e-6 and abs(change) > 1e-6):
            pct = (price - pre_close) / pre_close * 100
        if change is not None and abs(pct) > 1e-6 and (change > 0) != (pct > 0):
            pct = -abs(pct) if change < 0 else abs(pct)
    high = f(33)
    low = f(34)

    conn.execute(
        "INSERT INTO index_daily (date, index_id, open, high, low, close, pct_change, amount) "
        "VALUES (?,?,?,?,?,?,?,?) "
        "ON CONFLICT(date, index_id) DO UPDATE SET "
        "open=excluded.open, high=excluded.high, low=excluded.low, "
        "close=excluded.close, pct_change=excluded.pct_change, amount=excluded.amount",
        (date, idx_id, open_, high, low, price, pct, amount),
    )
    conn.commit()
    if verbose:
        print(f"    ✓ {idx_id} <- 腾讯兜底 close={price} pct={pct} amount={amount} date={date}")
    return True


def backfill_series_metrics(date):
    """重跑 collect_series 补采晚发布的序列指标。

    SSE 两融余额(stock_margin_sse)盘后 ~18:00-19:00 才发布当日数据，
    17:50 update_all 跑时源还没出 -> 两融停在 T-1。20:00/02:00 backfill
    时重跑这些 SERIES_FUNCS 指标，兜底补采当日数据。

    返回 (ok_count, has_today_new)：has_today_new=True 表示至少一个指标
    采到了 date 当日的新数据（需要重算+推送）。
    """
    import yaml
    from pathlib import Path
    from . import fetchers, runner
    from .base import log_collect

    config_path = Path(__file__).absolute().parent.parent.parent / "config" / "indicators.yaml"
    with open(config_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    ok = 0
    has_today_new = False
    for m in cfg.get("metrics", []):
        if not m.get("enabled") or m.get("type") == "derived":
            continue
        if m.get("func") not in fetchers.SERIES_FUNCS:
            continue
        mid = m["id"]
        try:
            rows, msg = fetchers.collect_series(m)
            if rows:
                runner.upsert_metrics_many(mid, rows)
                log_collect(date, mid, "ok", f"{len(rows)} rows (series backfill)")
                ok += 1
                if any(d == date for d, _ in rows):
                    has_today_new = True
                    print(f"  [series] {mid:25s} ok ({len(rows)} rows, has {date})")
                else:
                    print(f"  [series] {mid:25s} ok ({len(rows)} rows, latest={rows[-1][0]})")
            else:
                print(f"  [series] {mid:25s} skip ({msg})")
        except Exception as e:  # noqa: BLE001
            print(f"  [series] {mid:25s} error: {e}")
            log_collect(date, mid, "error", f"series backfill error: {e}")
    return ok, has_today_new


def backfill_history_gaps(date, verbose=True):
    """检查所有 enabled 指数/序列指标的历史缺口,latest 落后期望日期则补采。

    根治 2026-07-15 事故:backfill 之前只查"今日"缺失,某天 T+1 源因时差/
    源延迟没拿到(如 7-15 20:00 两融源 latest=20260714 还没出 7-15),后续
    backfill 查新今日,不回头补 7-15 缺口,致数据永久停滞后(7-16 凌晨发现
    美股 us_* 停 7-14、两融 a_fund_margin 停 7-14、深证红利 sz_div 停 7-14
    仍不补)。本函数检查每个品种 series 的 latest date,若 latest < 期望最新
    日期(有缺口),补采到期望日期。collect_index/collect_series 拉全量幂等
    upsert,重复补采无害。

    期望最新日期(避免误补 T+1 源正常延迟):
      - A股/港股指数(market in a/hk): date(最近交易日),latest<date=缺口
      - 全球/美股指数(market=global): 允许滞后1天(美股收盘晚于A股一个时差,
        latest 距 date <=1天=正常 T+1;>1天=真缺口)
      - 序列指标: date(T+1源次日应出;源没出则 collect_series 空跑跳过)

    与 verify_and_backfill_indices 互补:后者只校验 CORE_A/SW/thsc/HK_GLOBAL
    的"今日";本函数覆盖所有 enabled 指数(含 sz_div 等非核心)+ 序列指标,
    且检查历史缺口(非仅今日)。与方案C(未收盘回退)互补:C 解决"非交易时段
    幽灵当日",本函数解决"历史缺口"。返回补采到新数据的品种数。
    """
    import yaml
    from pathlib import Path
    from datetime import datetime as _dt
    from . import fetchers as _fetchers_mod
    from .runner import upsert_index_rows, upsert_metrics_many
    from .base import log_collect

    config_path = Path(__file__).absolute().parent.parent.parent / "config" / "indicators.yaml"
    with open(config_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    target_d = _dt.strptime(date, "%Y%m%d").date()
    fixed = 0

    conn = get_conn()
    try:
        # ── 指数缺口检测 ──
        for idx in cfg.get("indices", []):
            if not idx.get("enabled", True):
                continue
            idx_id = idx["id"]
            r = conn.execute(
                "SELECT MAX(date) FROM index_daily WHERE index_id=?", (idx_id,)
            ).fetchone()
            latest = r[0] if r else None
            if latest is None:
                continue  # 首次采集品种由主采集流程处理,非"历史缺口"
            try:
                last_d = _dt.strptime(latest, "%Y%m%d").date()
            except ValueError:
                continue
            market = idx.get("market", "a")
            if market == "global":
                # 美股/全球:T+1源,允许滞后1天(美股收盘晚于A股一个时差)
                is_gap = (target_d - last_d).days > 1
            else:
                is_gap = last_d < target_d
            if not is_gap:
                continue
            # 有缺口,补采(collect_index 拉全量幂等 upsert)
            try:
                rows, msg = _fetchers_mod.collect_index(idx, "20100101", date)
            except Exception as e:  # noqa: BLE001
                if verbose:
                    print(f"  [gap] {idx_id} 补采异常: {e}")
                log_collect(date, idx_id, "warn", f"缺口补采异常: {e}")
                continue
            # 判断是否补到比 latest 更新的数据(rows 第0列=date "YYYYMMDD")
            newer = [rw for rw in rows if rw[0] > latest] if rows else []
            if newer:
                upsert_index_rows(rows)
                new_latest = max(rw[0] for rw in newer)
                fixed += 1
                if verbose:
                    print(f"  [gap] ✓ {idx_id} latest {latest}->{new_latest} (+{len(newer)}行)")
                log_collect(date, idx_id, "ok", f"缺口补采 {latest}->{new_latest}")
            else:
                if verbose:
                    print(f"  [gap] - {idx_id} latest={latest} 缺口但源无新数据({msg})")

        # ── 序列指标缺口检测(两融/美债/QVIX 等晚发布序列) ──
        for m in cfg.get("metrics", []):
            if not m.get("enabled") or m.get("type") == "derived":
                continue
            if m.get("func") not in _fetchers_mod.SERIES_FUNCS:
                continue
            mid = m["id"]
            r = conn.execute(
                "SELECT MAX(date) FROM daily_metric WHERE metric_id=?", (mid,)
            ).fetchone()
            latest = r[0] if r else None
            if latest is None:
                continue
            try:
                last_d = _dt.strptime(latest, "%Y%m%d").date()
            except ValueError:
                continue
            # 序列指标统一用 date(最近交易日);T+1源没出则 collect_series 空跑跳过
            if last_d >= target_d:
                continue
            try:
                rows, msg = _fetchers_mod.collect_series(m)
            except Exception as e:  # noqa: BLE001
                if verbose:
                    print(f"  [gap] {mid} 补采异常: {e}")
                continue
            newer = [rw for rw in rows if rw[0] > latest] if rows else []
            if newer:
                upsert_metrics_many(mid, rows)
                new_latest = max(rw[0] for rw in newer)
                fixed += 1
                if verbose:
                    print(f"  [gap] ✓ {mid} latest {latest}->{new_latest} (+{len(newer)}行)")
            else:
                if verbose:
                    print(f"  [gap] - {mid} latest={latest} 缺口但源无新数据({msg})")
    finally:
        conn.close()

    if verbose:
        print(f"  [缺口检测] 检查完成,补采到新数据 {fixed} 个品种")
    return fixed


def main():
    """晚间轻量补采兜底入口（供 backfill_indices.sh / launchd 16:35/20:00/02:00 调用）。

    交易日才跑：
      1) 重跑 collect_series 补采晚发布序列指标（两融/QVIX/国债收益率等）
      2) 校验补采缺失指数（baostock/腾讯兜底）
      补到新数据则重算情绪分 + 推送；齐全或三源都缺则跳过。
    与 update_all.sh 区别：不全量采集，只补缺失 + 重算 + 推送（几十秒）。
    """
    import subprocess
    import sys
    from pathlib import Path
    from datetime import datetime, timedelta
    from ..calendar import is_trading_day, last_trading_day

    if not is_trading_day():
        print("[backfill] 非交易日,跳过")
        return

    today = last_trading_day()  # 已是 YYYYMMDD str
    if hasattr(today, "strftime"):
        today = today.strftime("%Y%m%d")
    # 门控(2026-07-16):last_trading_day() 在交易日当天未收盘(<15:00)仍返回今日,
    # 此时数据源(同花顺概念快照/行业聚合)在非交易时段返回 T-1 数据但被标今日日期
    # 写入 index_daily,产生幽灵当日行 -> compute_rotation 算出幽灵 rotation。
    # 未收盘时回退到前一真实交易日,只补历史(02:00 凌晨 backfill 走此分支);
    # 20:00 backfill(已收盘 15:00+)不回退,补当日真实收盘数据。
    now = datetime.now()
    if today == now.strftime("%Y%m%d") and now.hour < 15:
        prev = last_trading_day(now.date() - timedelta(days=1))
        if hasattr(prev, "strftime"):
            prev = prev.strftime("%Y%m%d")
        print(f"[backfill] 未收盘(<15:00),回退到前一交易日 {prev}(避免非交易时段幽灵当日数据)")
        today = prev
    print(f"[backfill] 目标日期 {today}")

    # 1) 序列指标补采（两融等晚发布指标，17:50 update_all 赶不上的兜底）
    print("[backfill] -> 序列指标补采 (stock_margin_sse 等)...")
    s_ok, s_has_today = backfill_series_metrics(today)
    print(f"[backfill] 序列补采: {s_ok} 个指标成功, 当日新数据={'是' if s_has_today else '否'}")

    # 2) 指数补采
    ok, fail, _ = verify_and_backfill_indices(today, verbose=True)
    print(f"[backfill] 指数补采结果 ok={ok} fail={fail}")

    if fail > 0:
        print(f"[backfill] ⚠ {fail} 个指数三源都缺今日(已写 collect_log 告警)")

    # 2.5) 历史缺口检测+补采(根治:不只查"今日",检查所有 enabled 品种 latest
    # 是否滞后于最近交易日,有缺口则补采。解决"T+1源某天延迟漏采后永久停滞后"。
    # 与 verify(查今日)互补:本函数覆盖所有 enabled 指数(含 sz_div 等非核心)
    # + 序列指标,且检测历史缺口(非仅今日)。)
    print("[backfill] -> 历史缺口检测+补采 ...")
    gap_fixed = backfill_history_gaps(today, verbose=True)
    print(f"[backfill] 历史缺口补采 {gap_fixed} 个品种")

    # 2.6) 凌晨兜底:补 futures/lhb/etf(02:00 backfill 原只补 SERIES_FUNCS+指数,
    # 这三类不覆盖)。复用上方 today(now.hour<15 已回退前一交易日,凌晨跑补到昨天)。
    _extra_new = False

    # futures 持仓补采 + 准确率重算
    try:
        from .futures_position import collect_daily as _fp_collect
        _fp_res = _fp_collect(today)
        if _fp_res:
            _extra_new = True
            print(f"[backfill] futures 补采到 {today} 数据 ({sum(len(v) for v in _fp_res.values())} 组)")
            try:
                from ..compute.futures_position import compute_accuracy as _fp_acc
                _fp_acc(date=today)
            except Exception as _e:  # noqa: BLE001
                print(f"[backfill] futures compute_accuracy 失败: {_e}")
        else:
            print(f"[backfill] futures 无新数据 ({today})")
    except Exception as _e:  # noqa: BLE001
        print(f"[backfill] futures 补采失败: {_e}")

    # etf 国家队宽基补采(pipeline_daily 内部补近5日幂等,凌晨跑补到昨天)
    try:
        from .etf_national_team import pipeline_daily as _etf_daily, export_json_files as _etf_export
        _etf_stats = _etf_daily()
        # pipeline_daily 采到新 OHLC/份额 -> 导出 static-site/data/etf_national_team-*.json
        # (deploy.sh 不导出 etf,须显式调 export_json_files 写 JSON 供 deploy 提交)
        _etf_export()
        if _etf_stats and (_etf_stats.get("ohlc") or _etf_stats.get("sse") or _etf_stats.get("szse")):
            _extra_new = True
            print(f"[backfill] etf 补采到新数据: {_etf_stats}")
        else:
            print(f"[backfill] etf 无新数据: {_etf_stats}")
    except Exception as _e:  # noqa: BLE001
        print(f"[backfill] etf 补采失败: {_e}")

    # lhb 龙虎榜补采(遍历 group=lhb 指标调 collect_snapshot,DATE_RANGE_FUNCS 不在
    # SERIES_FUNCS 需单独遍历;collect_snapshot 返回 (val, msg),val 非 None 则 upsert)
    try:
        import yaml as _yaml
        from pathlib import Path as _P
        from . import fetchers as _f
        from .runner import upsert_metric as _upsert_metric
        _cfg_path = _P(__file__).absolute().parent.parent.parent / "config" / "indicators.yaml"
        with open(_cfg_path, encoding="utf-8") as _fh:
            _lhb_cfg = _yaml.safe_load(_fh)
        for m in (_lhb_cfg.get("metrics") or []):
            if m.get("group") != "lhb" or not m.get("enabled"):
                continue
            try:
                _val, _msg = _f.collect_snapshot(m, today)
                if _val is not None:
                    _upsert_metric(today, m["id"], _val)
                    _extra_new = True
                    print(f"[backfill] lhb {m['id']} = {_val:.4g}")
                else:
                    print(f"[backfill] lhb {m['id']} skip ({_msg})")
            except Exception as _e:  # noqa: BLE001
                print(f"[backfill] lhb {m.get('id')} 失败: {_e}")
    except Exception as _e:  # noqa: BLE001
        print(f"[backfill] lhb 遍历失败: {_e}")

    # 3) 任一补采拿到新数据(当日 or 历史缺口 or futures/lhb/etf 兜底) -> 重算 + 推送
    if ok > 0 or s_has_today or gap_fixed > 0 or _extra_new:
        print("[backfill] 补到新数据 -> 重算情绪分 + 推送公网")
        # 写 collect_log 让 overview.json 的 collected_at 更新为本次 backfill 时间
        # (export.py collected_at 读 collect_log 最新 run_at; compute.runner 不写它,
        #  不写则前端采集时间卡在上次 update_all 时间,用户以为没更新)
        from .base import log_collect
        log_collect(today, "backfill", "ok", f"backfill补采(指数{ok}+序列{s_ok})->重算+推送")
        repo = Path(__file__).absolute().parent.parent.parent
        subprocess.run([sys.executable, "-m", "app.compute.runner"], check=False)
        # deploy 持 /tmp/trade_deploy.lock 串行化 git（阻塞排队），与 pipeline.sh /
        # intraday_snapshot.sh 共享 deploy 锁，避免 20:00 前后撞 update_all pipeline
        # 的 git add/commit/push 致 .git/index.lock 冲突（原裸调 deploy 无锁=隐患）。
        subprocess.run(
            [sys.executable, str(repo / "scripts" / "with_lock.py"),
             "/tmp/trade_deploy.lock", "bash", "scripts/deploy.sh", "backfill"],
            cwd=repo, check=False)
        print("[backfill] ✓ 补采+重算+推送完成")
    else:
        print("[backfill] 无新数据(已采全或源未发布),跳过重算+推送")
