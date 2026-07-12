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
    """申万官方 trend API 补采 sw_* 指数。

    swsresearch.com 的 trend API 返全量历史（无 beg/end 参数），取最新行。
    若最新行 == date 则补采成功；若 < date 说明源 T+1 延迟尚未发布当日数据。

    返回 [(date, idx_id, open, high, low, close, pct, amount)] 或 []。
    """
    import requests
    # base.py 已 monkey-patch DNS，但这里用独立 session 避免影响
    symbol = sw_id.replace("sw_", "")
    url = "https://www.swsresearch.com/institute-sw/api/index_publish/trend/"
    try:
        r = requests.get(url, params={"swindexcode": symbol, "period": "DAY"},
                         headers={"User-Agent": "Mozilla/5.0"}, verify=False, timeout=15)
        data = r.json().get("data", []) or []
    except Exception:
        return []

    if not data:
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
        r = conn.execute(
            "SELECT max(date) AS d FROM index_daily WHERE index_id=?", (idx_id,)
        ).fetchone()
        if r["d"] != date:
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
        r = conn.execute(
            "SELECT max(date) AS d FROM index_daily WHERE index_id=?", (sw_id,)
        ).fetchone()
        if r["d"] != date:
            sw_missing.append(sw_id)
    conn.close()

    if not sw_missing:
        if verbose:
            print(f"  [校验] {len(SW_INDICES)} 个申万行业指数今日({date})齐全 ✓")
    else:
        if verbose:
            print(f"  [校验] {len(sw_missing)} 个申万行业指数缺今日 {date} -> 申万 trend API 补采")
        from .runner import upsert_index_rows
        for sw_id in sw_missing:
            rows = _sw_trend_fetch(sw_id, date)
            if rows:
                upsert_index_rows(rows)
                ok += 1
                details.append((sw_id, "ok", f"backfill sw-trend close={rows[0][5]}"))
                if verbose:
                    print(f"    ✓ {sw_id} <- sw-trend close={rows[0][5]} pct={rows[0][6]}")
            else:
                fail += 1
                details.append((sw_id, "fail", "申万源 T+1 延迟未发布当日数据"))
                if verbose:
                    print(f"    - {sw_id} 申万源未发布当日（T+1 延迟），下次定时任务再补")

    return ok, fail, details


def main():
    """晚间轻量补采兜底入口（供 backfill_indices.sh / launchd 18:00 调用）。

    交易日才跑：校验补采 -> 补到新数据则重算情绪分 + 推送；齐全或三源都缺则跳过。
    与 update_all.sh 区别：不全量采集，只补缺失指数 + 重算 + 推送（几十秒）。
    """
    import subprocess
    import sys
    from pathlib import Path
    from ..calendar import is_trading_day, last_trading_day

    if not is_trading_day():
        print("[backfill] 非交易日,跳过")
        return

    today = last_trading_day().strftime("%Y%m%d")
    print(f"[backfill] 目标日期 {today}")
    ok, fail, _ = verify_and_backfill_indices(today, verbose=True)
    print(f"[backfill] 补采结果 ok={ok} fail={fail}")

    if fail > 0:
        print(f"[backfill] ⚠ {fail} 个指数三源都缺今日(已写 collect_log 告警)")

    if ok > 0:
        print("[backfill] 补到新数据 -> 重算情绪分 + 推送公网")
        repo = Path(__file__).resolve().parent.parent.parent
        subprocess.run([sys.executable, "-m", "app.compute.runner"], check=False)
        subprocess.run(["bash", "scripts/deploy.sh", "backfill"], cwd=repo, check=False)
        print("[backfill] ✓ 补采+重算+推送完成")
    else:
        print("[backfill] 无新数据(15:33 已采全或三源都缺),跳过重算+推送")
