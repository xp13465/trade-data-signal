"""直爬东财接口（akshare 部分函数被反爬封，这里用 em_get 防封层直连）。"""
from .base import em_get


def fetch_market_fund_flow():
    """主力资金流（沪+深合计），返回 [(date_YYYYMMDD, 主力净流入_元), ...]。

    主源东财 fflow daykline：f51=日期, f52=主力净流入, ...
    东财封禁/空时 fallback akshare stock_market_fund_flow（同口径沪深主力资金流日K，
    近 120 日；7-13/7-17 间歇封禁兜底）。collect_direct 会按 metric.scale 换算亿元。
    """
    # 主源：东财
    try:
        r = em_get(
            "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get",
            params={
                "lmt": 0,
                "klt": 101,
                "secid": "1.000001",
                "secid2": "0.399001",
                "fields1": "f1,f2,f3,f7",
                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65",
                "ut": "b2884a393a59ad64002292a3e90d46a5",
            },
            timeout=15,
        )
        data = r.json()
        klines = data.get("data", {}).get("klines", []) or []
        rows = []
        for line in klines:
            parts = line.split(",")
            try:
                d = parts[0].replace("-", "")
                v = float(parts[1])  # f52 主力净流入（元）
                rows.append((d, v))
            except (IndexError, ValueError):
                continue
        if rows:
            return rows
    except Exception:
        pass  # 东财封禁/网络异常 -> 走 fallback

    # fallback：akshare 同口径沪深主力资金流日K（东财封禁兜底，近 120 日）
    try:
        import akshare as ak
        df = ak.stock_market_fund_flow()
        rows = []
        for _, r in df.iterrows():
            try:
                d = str(r["日期"]).replace("-", "")
                v = float(r["主力净流入-净额"])  # 元
                rows.append((d, v))
            except (KeyError, ValueError, TypeError):
                continue
        return rows
    except Exception:
        return []  # 两源皆败，返回空（collect_direct 转 fail 记 error）
