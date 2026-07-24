"""直爬东财接口（akshare 部分函数被反爬封，这里用 em_get 防封层直连）。"""
import requests

from .base import UA, em_get


def fetch_market_fund_flow():
    """主力资金流（沪+深合计），返回 [(date_YYYYMMDD, 主力净流入_元), ...]。

    主源东财 fflow daykline：f51=日期, f52=主力净流入, ...
    东财封禁/空时 fallback akshare stock_market_fund_flow（同口径沪深主力资金流日K，
    近 120 日；7-13/7-17 间歇封禁兜底）。collect_direct 会按 metric.scale 换算亿元。

    722 伪双源修复：akshare 底层亦走 push2his.eastmoney.com（与主源同 URL 同服务器），
    主源封禁时 akshare 同步被封（722 4 次 backfill 全 fail）。新增第三源 push2/api/qt/clist/get
    汇总全 A 股主力净流入：push2.eastmoney.com/api/qt/clist/get（个股排名接口，非资金流 K 线
    接口），字段 f62=个股主力净流入金额，分页 sum 得大盘主力净流入合计。
    与主源区别：不同 API 路径（clist/get 排名 vs fflow/daykline K 线）+ 不同接口语义
    （个股排名 vs 大盘K线）。722 实测 IP 干净时单次调用可用，push2his 被封但 clist/get HTTP=200。
    限制：① IP 风控可能联动（同 eastmoney.com，触发阈值后联动封）② 只能拿当日（排名是实时数据）
    ③ 分页 53 次需 0.7s 限流约 37s ④ 口径为"全 A 股主力净流入之和"（理论等价于大盘主力净流入）。
    """
    # 主源：东财 push2his（历史日K，近 120 日）
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
        if rows:
            return rows
    except Exception:
        pass  # akshare 同步被封（底层走 push2his） -> 走第三源

    # 第三源：东财 push2/api/qt/clist/get 汇总全 A 股主力净流入（不同 API 路径兜底）
    # 722 伪双源修复：akshare 底层走 push2his（与主源同 URL 同服务器，主源封禁同步死）。
    # 新增第三源用 push2.eastmoney.com/api/qt/clist/get（个股排名接口，非资金流 K 线接口），
    # 字段 f62=个股主力净流入金额（元），分页汇总全 A 股得到大盘主力净流入合计。
    # 与主源区别：① 不同 API 路径（clist/get 排名 vs fflow/daykline 资金流K线）
    # ② 不同接口语义（个股排名 vs 大盘K线）③ 722 实测 IP 干净时单次调用可用。
    # 限制：① IP 风控可能联动（push2his + push2 同属 eastmoney.com，触发阈值后联动封）
    # ② 只能拿当日（个股排名是实时数据，非历史 K 线） ③ 分页 53 次需 0.7s 限流约 37s
    # ④ 口径为"全 A 股主力净流入之和"，理论等价于大盘主力净流入（主力净流入=超大单+大单净额）
    try:
        from datetime import date
        s = requests.Session()
        s.headers.update({"User-Agent": UA, "Referer": "https://data.eastmoney.com/"})
        # fs=沪深A股全集（与 akshare stock_main_fund_flow "沪深A股" 配置一致）
        fs = "m:0 t:6 f:!2,m:0 t:13 f:!2,m:0 t:80 f:!2,m:1 t:2 f:!2,m:1 t:23 f:!2"
        total_net = 0.0
        today_str = date.today().strftime("%Y%m%d")
        for pn in range(1, 60):  # 最多 60 页（每页 100 = 6000 只，覆盖全 A 股）
            try:
                r = s.get(
                    "https://push2.eastmoney.com/api/qt/clist/get",
                    params={
                        "pn": pn, "pz": 100, "po": 1, "np": 1,
                        "fltt": 2, "invt": 2,
                        "fid": "f62",  # 按主力净流入金额排序
                        "fs": fs,
                        "fields": "f12,f14,f62",  # 代码+名称+主力净流入金额
                        "ut": "b2884a393a59ad64002292a3e90d46a5",
                    },
                    timeout=10,
                )
                data = r.json()
                diff = data.get("data", {}).get("diff", []) or []
                if not diff:
                    break  # 无数据=末页
                for item in diff:
                    try:
                        total_net += float(item.get("f62") or 0)
                    except (TypeError, ValueError):
                        continue
                # 末页（不足 100 条）
                if len(diff) < 100:
                    break
            except Exception:
                continue  # 单页失败不跳出（可能是临时网络抖动），继续下一页累计
            # 0.7s 限流避免触发东财风控（>5次/秒触发 IP 封禁）
            import time as _t
            _t.sleep(0.7)
        if total_net != 0:
            return [(today_str, total_net)]
    except Exception:
        pass
    return []  # 三源皆败，返回空（collect_direct 转 fail 记 error）


def fetch_north_fund_total():
    """北向资金成交总额（沪股通+深股通 buySellAmt 之和），返回 [(date_YYYYMMDD, value_亿元), ...]。

    背景：2024-08 港交所新规取消盘中实时净买额披露后，东财 RPT_MUTUAL_DEAL_HISTORY 的
    NET_DEAL_AMT（净买额）/BUY_AMT/SELL_AMT 全 null 停更，akshare stock_hsgt_hist_em 的
    「当日成交净买额」返 NaN（fetchers.py L141 跳 NaN 致 20240816 后不入库）。
    方案A 救急：改用同接口的 DEAL_AMT（成交总额=买+卖）替代。语义从「净流入方向」变
    「市场活跃度」，sentiment north direction 仍 positive（成交总额大=市场活跃）。
    方案B（CCASS 反算真净买额）为后续单独大任务 TODO，本 fetcher 不实现。

    主源：datacenter-web.eastmoney.com RPT_MUTUAL_DEAL_HISTORY（MUTUAL_TYPE=005 北向合计），
    返回 2014-11 至今 ~2716 日，3 页（pageSize=1000）。DEAL_AMT 原值单位百元，/100=亿元。
    对照：2026-07-24 DEAL_AMT=283837.28 -> 2838.37 亿，与 push2 kamt/get 的
    hk2sh.buySellAmt(13605483.14万)+hk2sz.buySellAmt(14778245.72万)=28383728.86万=2838.37亿 吻合。

    fallback：datacenter 失败时用 push2 kamt/get 拿当日（只今天 1 天，无历史回填），
    buySellAmt 单位万元，/10000=亿元。仅兜底，正常路径走主源拿全量历史。
    """
    # 主源：datacenter-web RPT_MUTUAL_DEAL_HISTORY（历史日K，全量 ~3 页）
    rows = []
    try:
        for page in range(1, 6):  # 最多 5 页兜底（实测 3 页）
            r = em_get(
                "https://datacenter-web.eastmoney.com/api/data/v1/get",
                params={
                    "sortColumns": "TRADE_DATE",
                    "sortTypes": "-1",
                    "pageSize": "1000",
                    "pageNumber": str(page),
                    "reportName": "RPT_MUTUAL_DEAL_HISTORY",
                    "columns": "ALL",
                    "source": "WEB",
                    "client": "WEB",
                    "filter": '(MUTUAL_TYPE="005")',
                },
                timeout=20,
            )
            data = r.json()
            result = data.get("result") or {}
            page_rows = result.get("data") or []
            if not page_rows:
                break
            for item in page_rows:
                try:
                    d = str(item.get("TRADE_DATE", ""))[:10].replace("-", "")
                    v = float(item.get("DEAL_AMT")) / 100.0  # 百元 -> 亿元
                    if v == v:  # NaN 跳过
                        rows.append((d, v))
                except (TypeError, ValueError, KeyError):
                    continue
            total_pages = int(result.get("pages", 0))
            if page >= total_pages:
                break
        if rows:
            return rows
    except Exception:
        pass  # datacenter 封禁/网络异常 -> 走 fallback

    # fallback：push2 kamt/get 拿当日（只今天 1 天，无历史）
    try:
        r = em_get(
            "https://push2.eastmoney.com/api/qt/kamt/get",
            params={
                "ut": "b2884a393a59ad64002292a3e90d46a5",
                "fields1": "f1,f2,f3,f4",
                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65",
            },
            timeout=15,
        )
        data = r.json().get("data", {}) or {}
        hk2sh = data.get("hk2sh", {}) or {}
        hk2sz = data.get("hk2sz", {}) or {}
        d = str(hk2sh.get("date2", "")).replace("-", "")
        if d:
            total = float(hk2sh.get("buySellAmt") or 0) + float(hk2sz.get("buySellAmt") or 0)
            # buySellAmt 单位万元，/10000=亿元
            if total > 0:
                rows.append((d, total / 10000.0))
    except Exception:
        pass
    return rows
