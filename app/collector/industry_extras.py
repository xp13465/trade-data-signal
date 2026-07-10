"""行业级资金流 + 换手率采集（F2）。

东财 push2his 的 fflow daykline + kline 端点（非 clist，未被反爬封）按行业 secid 拉取。
- 资金流：fflow daykline，f52=主力净流入（元），历史 ~121 天
- 换手率：kline，f61=换手率（%），可用 beg/end 控制范围（拉 2 年）

secid 格式：90.BKxxxx（东财行业板块代码）。申万一级 801xxx → 东财 BKxxxx 映射通过
clist 端点（fs=m:90 t:2）按名称匹配获取，固化在 SW_EM_MAP 里。

采集入 daily_metric：
- ind_flow_<sw_id>   主力净流入（亿元，÷1e8）
- ind_turn_<sw_id>   换手率（%）
成交额已在 index_daily.amount（F1 的 index_hist_sw 返回），不重复采集。
"""
import time

from .base import em_get, safe_call
from ..db import get_conn

# 申万一级 801xxx → 东财行业板块 BKxxxx 映射（2026-07 通过 clist 按名称匹配获取）
SW_EM_MAP = {
    "sw_801010": "BK0433",  # 农林牧渔
    "sw_801030": "BK1206",  # 基础化工
    "sw_801040": "BK0479",  # 钢铁
    "sw_801050": "BK0478",  # 有色金属
    "sw_801080": "BK1201",  # 电子
    "sw_801880": "BK1211",  # 汽车
    "sw_801110": "BK0456",  # 家用电器
    "sw_801120": "BK0438",  # 食品饮料
    "sw_801130": "BK0436",  # 纺织服饰
    "sw_801140": "BK1212",  # 轻工制造
    "sw_801150": "BK1216",  # 医药生物
    "sw_801160": "BK0427",  # 公用事业
    "sw_801170": "BK1210",  # 交通运输
    "sw_801180": "BK1202",  # 房地产
    "sw_801200": "BK1213",  # 商贸零售
    "sw_801210": "BK1214",  # 社会服务
    "sw_801780": "BK1283",  # 银行
    "sw_801790": "BK1203",  # 非银金融
    "sw_801230": "BK1217",  # 综合
    "sw_801710": "BK1208",  # 建筑材料
    "sw_801720": "BK1209",  # 建筑装饰
    "sw_801730": "BK1200",  # 电力设备
    "sw_801890": "BK1205",  # 机械设备
    "sw_801740": "BK1204",  # 国防军工
    "sw_801750": "BK1207",  # 计算机
    "sw_801760": "BK0486",  # 传媒
    "sw_801770": "BK1215",  # 通信
    "sw_801950": "BK0437",  # 煤炭
    "sw_801960": "BK0464",  # 石油石化
    "sw_801970": "BK0728",  # 环保
    "sw_801980": "BK1035",  # 美容护理
}

FFLOW_URL = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"


def _now_iso():
    from datetime import datetime
    return datetime.now().isoformat()


def _upsert_many(metric_id, rows, source="akshare"):
    """rows: [(date_yyyymmdd, value), ...]"""
    if not rows:
        return 0
    conn = get_conn()
    conn.executemany(
        "INSERT INTO daily_metric (date, metric_id, value, source, updated_at) "
        "VALUES (?,?,?,?,?) "
        "ON CONFLICT(date, metric_id) DO UPDATE SET "
        "value=excluded.value, source=excluded.source, updated_at=excluded.updated_at "
        "WHERE daily_metric.source != 'manual'",
        [(d, metric_id, v, source, _now_iso()) for d, v in rows],
    )
    conn.commit()
    conn.close()
    return len(rows)


def fetch_fund_flow(em_code):
    """行业主力净流入历史。返回 [(date_yyyymmdd, value_亿元), ...]。

    fflow daykline: f51=日期, f52=主力净流入（元）。lmt=0 返全部可用历史（~121 天）。
    """
    def _fetch():
        return em_get(FFLOW_URL, params={
            "lmt": 0, "klt": 101, "secid": f"90.{em_code}",
            "fields1": "f1,f2,f3,f7",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65",
            "ut": "b2884a393a59ad64002292a3e90d46a5",
        }, timeout=5)
    r = safe_call(_fetch, retries=0)
    if isinstance(r, Exception) or r is None:
        return [], f"fflow error: {r}"
    try:
        data = r.json().get("data", {}) or {}
    except Exception as e:  # noqa: BLE001
        return [], f"fflow json error: {e}"
    klines = data.get("klines", []) or []
    rows = []
    for line in klines:
        parts = line.split(",")
        try:
            d = parts[0].replace("-", "")
            v = float(parts[1]) / 1e8  # 元 → 亿元
            if v != v:  # NaN
                continue
            rows.append((d, v))
        except (IndexError, ValueError):
            continue
    return rows, "ok"


def fetch_turnover(em_code, beg="20240101", end="20261231"):
    """行业换手率历史。返回 [(date_yyyymmdd, value_pct), ...]。

    kline: f51=日期...f61=换手率（%）。beg/end 控制范围。
    """
    def _fetch():
        return em_get(KLINE_URL, params={
            "secid": f"90.{em_code}",
            "fields1": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "klt": "101", "fqt": "1", "beg": beg, "end": end,
            "ut": "fa5fd1943c7b386f172d6893dbbd1",
        }, timeout=5)
    r = safe_call(_fetch, retries=0)
    if isinstance(r, Exception) or r is None:
        return [], f"kline error: {r}"
    try:
        data = r.json().get("data", {}) or {}
    except Exception as e:  # noqa: BLE001
        return [], f"kline json error: {e}"
    klines = data.get("klines", []) or []
    rows = []
    for line in klines:
        parts = line.split(",")
        try:
            d = parts[0].replace("-", "")
            v = float(parts[10])  # f61=换手率（%）
            if v != v:  # NaN
                continue
            rows.append((d, v))
        except (IndexError, ValueError):
            continue
    return rows, "ok"


def collect_industry_extras(verbose=True):
    """采集 31 个申万一级行业的资金流 + 换手率，入 daily_metric。

    每个行业 2 次 HTTP（fflow + kline），31×2=62 次，3s 节流 ≈ 200s。
    成交额已在 index_daily.amount（F1），不重复采。
    """
    ok = fail = 0
    details = []
    items = list(SW_EM_MAP.items())
    consec_fail = 0  # 连续全失败行业数（东财封 IP 检测，达阈值提前结束避免空等）
    ABORT_THRESHOLD = 3
    for i, (sw_id, em_code) in enumerate(items):
        # 资金流
        rows, msg = fetch_fund_flow(em_code)
        flow_ok = bool(rows)
        if flow_ok:
            _upsert_many(f"ind_flow_{sw_id}", rows)
            ok += 1
            details.append((f"ind_flow_{sw_id}", "ok", f"{len(rows)} rows"))
            if verbose:
                print(f"  [{i+1}/{len(items)}] ind_flow_{sw_id} ok ({len(rows)} rows)", flush=True)
        else:
            fail += 1
            details.append((f"ind_flow_{sw_id}", "fail", msg))
            if verbose:
                print(f"  [{i+1}/{len(items)}] ind_flow_{sw_id} FAIL: {msg}", flush=True)
        time.sleep(0.5)

        # 换手率
        rows, msg = fetch_turnover(em_code)
        turn_ok = bool(rows)
        if turn_ok:
            _upsert_many(f"ind_turn_{sw_id}", rows)
            ok += 1
            details.append((f"ind_turn_{sw_id}", "ok", f"{len(rows)} rows"))
            if verbose:
                print(f"  [{i+1}/{len(items)}] ind_turn_{sw_id} ok ({len(rows)} rows)", flush=True)
        else:
            fail += 1
            details.append((f"ind_turn_{sw_id}", "fail", msg))
            if verbose:
                print(f"  [{i+1}/{len(items)}] ind_turn_{sw_id} FAIL: {msg}", flush=True)
        time.sleep(0.5)

        # 连续全失败 -> 东财封 IP，提前结束避免剩余行业空等重试
        if not flow_ok and not turn_ok:
            consec_fail += 1
            if consec_fail >= ABORT_THRESHOLD:
                skip_n = len(items) - i - 1
                details.append(("industry_extras", "skip",
                                f"连续{ABORT_THRESHOLD}行业全失败(东财封IP),跳过剩余{skip_n}行业"))
                if verbose:
                    print(f"  ⚠ 连续{ABORT_THRESHOLD}个行业全失败(东财封IP),提前结束剩余{skip_n}个行业", flush=True)
                break
        else:
            consec_fail = 0

    if verbose:
        print(f"=== 行业资金流/换手率采集完成: ok={ok} fail={fail} ===")
    return {"ok": ok, "fail": fail, "details": details}


if __name__ == "__main__":
    collect_industry_extras()
