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

# TODO(换源): 2026-07-13 实测 push2his.eastmoney.com 全端点被封
# (RemoteDisconnected)，ind_flow_sw_* / ind_turn_sw_* 0710 起采不到。
# base.py 已关系统代理(NO_PROXY=*)仍被封，疑 IP 级封锁非代理问题。
# 资金流已换同花顺 stock_board_industry_summary_ths（见 _fetch_fund_flow_ths）。
# 换手率 fetch_turnover 暂留东财（kline 部分可用，非必痛点）。
# 东财 IP 解封后可回切：把 collect_industry_extras 资金流段改回 fetch_fund_flow。
FFLOW_URL = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"

# 同花顺 90 个二级行业 -> 申万 31 个一级行业映射（人工核对，2026-07 实测）
# 同花顺是二级行业（更细），申万是一级行业（更粗），1 个申万对应多个同花顺子行业。
# 资金流聚合方式：同花顺子行业净流入求和 -> 申万一级行业净流入。
THS_TO_SW = {
    # 农林牧渔 (801010)
    "养殖业": "sw_801010", "种植业与林业": "sw_801010", "农产品加工": "sw_801010",
    # 基础化工 (801030)
    "化学原料": "sw_801030", "化学制品": "sw_801030", "化学纤维": "sw_801030",
    "橡胶制品": "sw_801030", "塑料制品": "sw_801030", "非金属材料": "sw_801030",
    "农化制品": "sw_801030",
    # 钢铁 (801040)
    "钢铁": "sw_801040",
    # 有色金属 (801050)
    "工业金属": "sw_801050", "贵金属": "sw_801050", "小金属": "sw_801050",
    "能源金属": "sw_801050", "金属新材料": "sw_801050",
    # 电子 (801080)
    "半导体": "sw_801080", "消费电子": "sw_801080", "光学光电子": "sw_801080",
    "元件": "sw_801080", "其他电子": "sw_801080", "电子化学品": "sw_801080",
    # 汽车 (801880)
    "汽车整车": "sw_801880", "汽车零部件": "sw_801880", "汽车服务及其他": "sw_801880",
    # 家用电器 (801110)
    "白色家电": "sw_801110", "黑色家电": "sw_801110", "小家电": "sw_801110", "厨卫电器": "sw_801110",
    # 食品饮料 (801120)
    "食品加工制造": "sw_801120", "饮料制造": "sw_801120", "白酒": "sw_801120",
    # 纺织服饰 (801130)
    "服装家纺": "sw_801130", "纺织制造": "sw_801130",
    # 轻工制造 (801140)
    "造纸": "sw_801140", "包装印刷": "sw_801140", "家居用品": "sw_801140",
    # 医药生物 (801150)
    "中药": "sw_801150", "化学制药": "sw_801150", "生物制品": "sw_801150",
    "医疗器械": "sw_801150", "医药商业": "sw_801150", "医疗服务": "sw_801150",
    # 公用事业 (801160)
    "电力": "sw_801160", "燃气": "sw_801160",
    # 交通运输 (801170)
    "港口航运": "sw_801170", "公路铁路运输": "sw_801170", "物流": "sw_801170", "机场航运": "sw_801170",
    # 房地产 (801180)
    "房地产": "sw_801180",
    # 商贸零售 (801200)
    "零售": "sw_801200", "贸易": "sw_801200", "互联网电商": "sw_801200",
    # 社会服务 (801210)
    "教育": "sw_801210", "旅游及酒店": "sw_801210", "其他社会服务": "sw_801210",
    # 银行 (801780)
    "银行": "sw_801780",
    # 非银金融 (801790)
    "证券": "sw_801790", "保险": "sw_801790", "多元金融": "sw_801790",
    # 综合 (801230)
    "综合": "sw_801230",
    # 建筑材料 (801710)
    "建筑材料": "sw_801710",
    # 建筑装饰 (801720)
    "建筑装饰": "sw_801720",
    # 电力设备 (801730)
    "电网设备": "sw_801730", "电池": "sw_801730", "光伏设备": "sw_801730",
    "风电设备": "sw_801730", "其他电源设备": "sw_801730", "电机": "sw_801730",
    # 机械设备 (801890)
    "专用设备": "sw_801890", "通用设备": "sw_801890", "工程机械": "sw_801890",
    "轨交设备": "sw_801890", "自动化设备": "sw_801890",
    # 国防军工 (801740)
    "军工装备": "sw_801740", "军工电子": "sw_801740",
    # 计算机 (801750)
    "软件开发": "sw_801750", "IT服务": "sw_801750", "计算机设备": "sw_801750",
    # 传媒 (801760)
    "文化传媒": "sw_801760", "游戏": "sw_801760", "影视院线": "sw_801760",
    # 通信 (801770)
    "通信服务": "sw_801770", "通信设备": "sw_801770",
    # 煤炭 (801950)
    "煤炭开采加工": "sw_801950",
    # 石油石化 (801960)
    "油气开采及服务": "sw_801960", "石油加工贸易": "sw_801960",
    # 环保 (801970)
    "环境治理": "sw_801970", "环保设备": "sw_801970",
    # 美容护理 (801980)
    "美容护理": "sw_801980",
}


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
    """行业主力净流入历史（东财 fflow daykline）。返回 [(date_yyyymmdd, value_亿元), ...]。

    [已弃用] 2026-07-13 起 push2his.eastmoney.com IP 封，改用同花顺
    _fetch_fund_flow_ths()。代码保留以便东财解封后回切。

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


def _fetch_fund_flow_ths():
    """同花顺行业一览表 -> 31 申万一级行业净流入（今日快照）。

    调 ak.stock_board_industry_summary_ths() 拿 90 个同花顺二级行业今日快照
    （板块/涨跌幅/总成交额/净流入/上涨家数/下跌家数），通过 THS_TO_SW 映射
    聚合到申万 31 个一级行业（子行业净流入求和）。

    净流入单位：亿元（同花顺源已是亿元，无需 ÷1e8）。
    注意：同花顺 summary 是今日快照（非历史OHLC），每日采积攒历史。

    返回 (sw_flow, msg)：sw_flow={sw_id: net_flow_亿元}, msg="ok" 或错误描述。
    """
    import akshare as ak
    try:
        df = ak.stock_board_industry_summary_ths()
    except Exception as e:  # noqa: BLE001
        return {}, f"ths summary error: {e}"

    if df is None or len(df) == 0:
        return {}, "ths summary empty"

    sw_flow = {}
    unmatched = []
    for _, row in df.iterrows():
        ths_name = str(row["板块"]).strip()
        sw_id = THS_TO_SW.get(ths_name)
        if sw_id is None:
            unmatched.append(ths_name)
            continue
        try:
            v = float(row["净流入"])
        except (TypeError, ValueError):
            continue
        if v != v:  # NaN
            continue
        sw_flow[sw_id] = sw_flow.get(sw_id, 0.0) + v

    msg = f"ok ({len(sw_flow)}/31 SW mapped"
    if unmatched:
        msg += f", {len(unmatched)} unmatched: {unmatched[:5]}"
    msg += ")"
    return sw_flow, msg


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

    资金流：同花顺 stock_board_industry_summary_ths（1 次 API 拿 90 子行业 ->
    聚合 31 申万一级）。东财 IP 封后 2026-07-13 换源。
    换手率：东财 kline（暂留东财，非必痛点；封 IP 时连续失败提前结束）。
    成交额已在 index_daily.amount（F1），不重复采。
    """
    from ..calendar import last_trading_day
    from .base import log_collect

    today = last_trading_day()
    ok = fail = 0
    details = []
    items = list(SW_EM_MAP.items())

    # ── 资金流：同花顺（1 次 API 拿全部 31 申万行业）──
    sw_flow, msg = _fetch_fund_flow_ths()
    if sw_flow:
        for sw_id, net_flow in sw_flow.items():
            _upsert_many(f"ind_flow_{sw_id}", [(today, net_flow)], source="ths")
            ok += 1
            details.append((f"ind_flow_{sw_id}", "ok", f"{net_flow:.2f}亿 (ths)"))
            if verbose:
                print(f"  ind_flow_{sw_id} ok ({net_flow:.2f}亿, ths)", flush=True)
        # THS 未返回的申万行业（映射缺失或 API 未覆盖）
        for sw_id, _ in items:
            if sw_id not in sw_flow:
                fail += 1
                details.append((f"ind_flow_{sw_id}", "fail", "ths 未返回该行业"))
                if verbose:
                    print(f"  ind_flow_{sw_id} FAIL: ths 未返回", flush=True)
        if verbose:
            print(f"  [资金流] 同花顺 {len(sw_flow)}/31 行业到位 ({msg})", flush=True)
    else:
        for sw_id, _ in items:
            fail += 1
            details.append((f"ind_flow_{sw_id}", "fail", msg))
        if verbose:
            print(f"  ⚠ 同花顺资金流采集失败: {msg}（{len(items)} 行业全部缺）", flush=True)
        log_collect(today, "industry_extras", "warn",
                    f"同花顺资金流采集失败: {msg}")

    # ── 换手率：东财 kline（暂不换源，IP 封时连续失败提前结束）──
    consec_fail = 0
    ABORT_THRESHOLD = 3
    for i, (sw_id, em_code) in enumerate(items):
        rows, tmsg = fetch_turnover(em_code)
        turn_ok = bool(rows)
        if turn_ok:
            _upsert_many(f"ind_turn_{sw_id}", rows)
            ok += 1
            details.append((f"ind_turn_{sw_id}", "ok", f"{len(rows)} rows"))
            if verbose:
                print(f"  [{i+1}/{len(items)}] ind_turn_{sw_id} ok ({len(rows)} rows)", flush=True)
        else:
            fail += 1
            details.append((f"ind_turn_{sw_id}", "fail", tmsg))
            if verbose:
                print(f"  [{i+1}/{len(items)}] ind_turn_{sw_id} FAIL: {tmsg}", flush=True)
        time.sleep(0.5)

        if not turn_ok:
            consec_fail += 1
            if consec_fail >= ABORT_THRESHOLD:
                skip_n = len(items) - i - 1
                details.append(("industry_extras", "skip",
                                f"连续{ABORT_THRESHOLD}换手率失败(东财封IP),跳过剩余{skip_n}"))
                if verbose:
                    print(f"  ⚠ 连续{ABORT_THRESHOLD}个换手率失败(东财封IP),提前结束剩余{skip_n}个", flush=True)
                break
        else:
            consec_fail = 0

    if verbose:
        print(f"=== 行业资金流/换手率采集完成: ok={ok} fail={fail} ===")
    return {"ok": ok, "fail": fail, "details": details}


if __name__ == "__main__":
    collect_industry_extras()
