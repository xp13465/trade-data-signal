"""直爬东财接口（akshare 部分函数被反爬封，这里用 em_get 防封层直连）。"""
import datetime as _dt
import json
import re as _re
import sqlite3

import requests

from .base import UA, em_get

# HKEX 官方每日统计 JS 模板（C3：北向成交总额权威源）
# 文件内容: tabData = [...] JSON 数组，含 SSE/SZSE Northbound/Southbound 4 条记录
# 北向 schema=['Total Turnover','Total Trade Count','DQB','ETF Turnover']，只有成交总额
# 单位百万 RMB，/100=亿元。保留窗口约 7 个月（实测 2025-12-29 起），周末/假日 404 跳过
HKEX_DAILY_STAT_URL = "https://www.hkex.com.hk/eng/csm/DailyStat/data_tab_daily_{date}e.js"
HKEX_DAILY_STAT_REFERER = "https://www.hkex.com.hk/Mutual-Market/Stock-Connect/Statistics/Historical-Daily"


def _drop_preopen_today(rows):
    """盘前(未开盘)过滤「今日行」, 防 a_fund_main 跨日标注污染。

    2026-08-18 根治: A 股开盘前(本地 <09:30)东财 daykline/akshare 会预生成「今日行」,
    值为上一交易日收盘的主力净流入(如 8/18 凌晨采集到 8/18 行=8/17 收盘 800.70),
    日期却标为今日 -> daily_metric 出现「昨日值标当日行」(8/17 与 8/18 同值 800.70)。
    a_fund_main 是当日盘中/盘后指标, 盘前不可能有当日真实值, 故丢弃今日行
    (当日真实值盘中 9:30 后/盘后 15:00 由 intraday 或正式采集覆盖, 不会丢数据)。
    主源/akshare 返回近 120 日多行, 仅过滤今日行保留历史; 第四/五源盘前返回空 ->
    collect_direct 转 fail 记 error(宁可 error 也不污染当日)。
    """
    from datetime import datetime
    _now = datetime.now()
    _hhmm = _now.hour * 100 + _now.minute
    if _hhmm >= 930:  # A股开盘后(含盘中/盘后), 今日行是真实值, 不过滤
        return rows
    _today = _now.strftime("%Y%m%d")
    return [r for r in rows if r[0] != _today]


def fetch_market_fund_flow():
    """主力资金流（沪+深合计），返回 [(date_YYYYMMDD, 主力净流入_元), ...]。

    主源东财 fflow daykline：f51=日期, f52=主力净流入, ...
    东财封禁/空时 fallback akshare stock_market_fund_flow（同口径沪深主力资金流日K，
    近 120 日；7-13/7-17 间歇封禁兜底）。collect_direct 会按 metric.scale 换算亿元。

    722 伪双源修复：akshare 底层亦走 push2his.eastmoney.com（与主源同 URL 同服务器），
    主源封禁时 akshare 同步被封（722 4 次 backfill 全 fail）。新增 clist 源 push2/api/qt/clist/get
    汇总全 A 股主力净流入：字段 f62=个股主力净流入金额，分页 sum 得大盘主力净流入合计。
    限制：① IP 风控可能联动（同 eastmoney.com）② 只能拿当日 ③ 分页 53 次需 0.7s 限流约 37s
    ④ 口径为"全 A 股主力净流入之和"（理论等价于大盘主力净流入）。

    725 第三源修复：7-24 起 push2his 整域名被封 + push2/api/qt/clist/get 被封（端点级反爬），
    主源/akshare/clist 全死。实测 push2/api/qt/stock/fflow/kline/get（非 daykline 历史K线）
    端点未封（dapan.js 网页实时K线端点）。klt=101 日K返回当日/最近交易日 1 行，f52=主力净流入
    （元），口径与主源一致。725 调整为第三源（原 clist 降为第四源）：① 单次调用轻量，不加剧
    反爬 ② 主源/akshare 死后立即试此源 ③ simple 类型 a_fund_main 只需当日值足够。
    限制：只能拿当日 1 行（非历史），等主源解封时优先回切主源拿历史 120 日。

    725 第五源修复：7-24 起 eastmoney.com 全家桶(push2his+push2+datacenter 主力流)联动封，
    四源全死(eastmoney 全家桶 ConnectionError)。新增同花顺行业资金流 data.10jqka.com.cn 作
    非东财独立兜底：akshare stock_fund_flow_industry 走同花顺 ajax，返回 90 行业"净额"，
    sum 得大盘资金流合计。⚠️ 口径差异：同花顺"净额"=流入-流出全部资金净额(含中小单)，
    东财"主力净流入"=超大单+大单净额。725 实测同花顺 sum=-969.56 亿 vs 东财 7-24=-774 亿，
    差异 25%(同花顺绝对值更大，符合"全部资金>主力"预期)，方向一致。simple 类型 a_fund_main
    只需方向判断，25% 偏差可接受；东财解封后优先回切主源拿口径一致+历史数据。
    限制：① 只能拿当日"即时"值(非历史K线) ② 口径为全部资金净额(非主力) ③ 周末访问返回
    周五收盘数据，日期做周末往前推修正。
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
            return _drop_preopen_today(rows)
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
            return _drop_preopen_today(rows)
    except Exception:
        pass  # akshare 同步被封（底层走 push2his） -> 走第三源

    # 第三源：东财 push2/api/qt/stock/fflow/kline/get（实时资金流K线，非 daykline 历史K线）
    # 725 修复：7-24 起 push2his.eastmoney.com 整域名被封 + push2/api/qt/clist/get 被封，
    # 主源/akshare/第三源全死。实测 push2/api/qt/stock/fflow/kline/get 端点未封（dapan.js
    # 网页用的实时K线端点，东财未对此端点反爬）。klt=101 日K返回当日/最近交易日 1 行，
    # f52=主力净流入（元），口径与主源一致（沪深 secid=1.000001+0.399001 合计）。
    # 限制：① 只能拿当日 1 行（非历史 K 线），simple 类型 a_fund_main 只需当日值足够
    # ② 端点可能后续也被反爬，等主源解封时优先回切主源拿历史 120 日
    # 725 实测 7-24 数据 -774 亿（与最近波动 -1700~+465 一致，合理）
    try:
        r = em_get(
            "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get",
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
            return _drop_preopen_today(rows)
    except Exception:
        pass  # 第三源也失败 -> 走第四源
    # 第四源：东财 push2/api/qt/clist/get 汇总全 A 股主力净流入（不同 API 路径重型兜底）
    # 722 伪双源修复原第三源，725 降为第四源：push2 clist 60 页分页会加剧东财反爬，
    # 优先用第三源 fflow/kline 轻量单次调用，第三源也失败才走此重型兜底。
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
            return _drop_preopen_today([(today_str, total_net)])
    except Exception:
        pass

    # 第五源：同花顺行业资金流（非东财独立兜底，防 eastmoney.com 全家桶联动封）
    # 725 新增：7-24 起 eastmoney.com 全家桶(push2his+push2+datacenter 主力流)联动封，四源全死。
    # 同花顺 data.10jqka.com.cn 独立域名，不受东财反爬影响。akshare stock_fund_flow_industry
    # 走同花顺 ajax 接口，返回 90 个行业"流入资金/流出资金/净额(亿)"，sum(净额)≈大盘资金流合计。
    # ⚠️ 口径差异：同花顺"净额"=流入-流出全部资金净额(含中小单)，东财"主力净流入"=超大单+大单净额。
    # 实测 7-25：同花顺 sum=-969.56 亿 vs 东财主源 7-24=-774 亿，差异 25%(绝对值更大符合"全部>主力"预期)，
    # 方向一致。simple 类型 a_fund_main 只需方向判断，25% 偏差可接受。
    # 限制：① 只能拿当日"即时"值(非历史K线) ② 口径为全部资金净额(非主力) ③ 周末往前推到周五修正日期
    try:
        import akshare as ak
        df = ak.stock_fund_flow_industry(symbol="即时")
        total_net_yi = 0.0  # 单位亿元
        for _, r in df.iterrows():
            try:
                v = float(str(r["净额"]).replace(",", ""))
                total_net_yi += v
            except (KeyError, ValueError, TypeError):
                continue
        if total_net_yi != 0:
            # 周末/周日往前推到周五（非交易日数据归交易日，节假日不修正-东财解封时不依赖此源）
            from datetime import date as _date, timedelta as _td
            d = _date.today()
            while d.weekday() >= 5:  # 5=周六, 6=周日
                d -= _td(days=1)
            today_str = d.strftime("%Y%m%d")
            # 同花顺净额单位亿元，转元（与主源 f52 单位一致）
            return _drop_preopen_today([(today_str, total_net_yi * 1e8)])
    except Exception:
        pass

    return []  # 五源皆败，返回空（collect_direct 转 fail 记 error）


# ── a_fund_north 预算治理常量(2026-08-26 根治「90天循环 vs 90s守护预算」矛盾) ──
# 根因:days=90 固定窗口逐日串行(~2s/请求 ≈ 164s+)必超 collect_direct 90s 守护
# (fetchers._safe_call_guarded timeout=90),每次被当假死砍掉,三级 fallback 从未轮到。
HKEX_SOFT_DEADLINE_S = 60.0   # 主源循环软deadline(秒):到点break拿到多少交多少;
                              # 必须 < 90s 外层守护(最坏在途单请求15s → 75s,留15s余量)
HKEX_DAYS_MIN = 3             # 增量缺口下限(天):库已最新也回看3天,防个别日缺行漏补
HKEX_DAYS_MAX = 10            # 增量缺口上限(天):10工作日 × ~2s ≈ <20s,稳在90s预算内
HKEX_DAYS_FULL = 90           # 首次全量窗口(仅库空场景);配合软deadline保证不超预算
# 深缺口分轮累积硬顶(自然日,2026-08-27 P1 修复):略大于 HKEX 源保留窗(~7个月≈213天),
# 分轮回补推到此处仍未闭合即放弃并告警(防源窗外无限空转;回退常规增量)
HKEX_BACKFILL_CAP_DAYS = 210


def _north_fund_gap_days():
    """查主库 daily_metric 里 a_fund_north 最新日期,算增量缺口自然日数。

    返回 (gap_days, known):
    - (int, True)   库有数据,gap = today - MAX(date) 自然日差(≥0)
    - (None, True)  库空 → 首次全量场景,调用方用 HKEX_DAYS_FULL
    - (None, False) 查库异常 → 调用方保守按 HKEX_DAYS_MAX 增量,不冒险走全量慢爬
    读库用 runner 同款 get_conn()(同 hkex_ccass_quarterly._latest_quarter_value 先例),
    只读 SELECT MAX(date),不写库。
    """
    try:
        from ..db import get_conn
        conn = get_conn()
        try:
            row = conn.execute(
                "SELECT MAX(date) FROM daily_metric WHERE metric_id='a_fund_north'"
            ).fetchone()
        finally:
            conn.close()
        latest = row[0] if row else None
        if not latest:
            return None, True
        latest_d = _dt.datetime.strptime(str(latest)[:8], "%Y%m%d").date()
        return max(0, (_dt.date.today() - latest_d).days), True
    except Exception:
        return None, False


# ── 深缺口分轮累积回补状态(v1.1.7 P1 修复:「北向增量截断→递增丢日」根治) ──
# bug 根因: 缺口上限夹到 ≤10 自然日且每轮都从"今天"往回看 → 长假/长停机后 gap>10 时,
# 窗口只盖住最近 10 天,"更早段"不在任何一轮窗口内;MAX(date) 随新数据前进后
# gap 重算变小,更早缺口永远补不上(递增丢日)。
# 修法: 轻量 state 文件记「本轮已覆盖到的最早日期」(前沿),下轮从前沿-1天无缝向前
# 推进一轮 span_max,直到查库撞见既有完好数据行即判闭合清态。行级 upsert 幂等,
# 并发双槽下前沿可能倒退但收敛(state 只许"读到的人"写/清,防误清)。
_NORTH_BACKFILL_STATE = "north_fund_backfill_state.json"


def _north_backfill_state_path():
    from ..db import DB_PATH
    return DB_PATH.parent / _NORTH_BACKFILL_STATE


def _north_backfill_load_earliest():
    """读分轮回补前沿(最早覆盖日 date);无文件/损坏返回 None(失败不影响主流程)。"""
    try:
        with open(_north_backfill_state_path(), encoding="utf-8") as f:
            st = json.loads(f.read())
        s = str(st.get("earliest_covered", ""))[:8]
        return _dt.datetime.strptime(s, "%Y%m%d").date() if len(s) == 8 else None
    except Exception:
        return None


def _north_backfill_save_earliest(d):
    """原子写前沿(tmp+os.replace);失败仅打日志不抛(state 属辅助机制,采集优先)。"""
    import os
    p = _north_backfill_state_path()
    try:
        tmp = str(p) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(json.dumps({
                "metric_id": "a_fund_north",
                "earliest_covered": d.strftime("%Y%m%d"),
                "updated_at": _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }))
        os.replace(tmp, p)
    except Exception as e:
        print(f"[a_fund_north][hkex] backfill 前沿写入失败(不影响本次采集): {e}")


def _north_backfill_clear():
    try:
        _north_backfill_state_path().unlink()
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"[a_fund_north][hkex] backfill 前沿清理失败: {e}")


def _north_fund_date_exists(date_str):
    """查库该指标当日是否已有行(闭合探测;轻量只读连接)。

    失败按不存在处理 → 照常发请求(宁可重复请求不漏数据,重复入库有 upsert 幂等兜底)。
    """
    try:
        from ..db import DB_PATH
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        try:
            row = conn.execute(
                "SELECT 1 FROM daily_metric "
                "WHERE metric_id='a_fund_north' AND date=? LIMIT 1",
                (date_str,),
            ).fetchone()
        finally:
            conn.close()
        return bool(row)
    except Exception:
        return False


def plan_north_gap_window(today, *, gap=None, known=True, resume_from=None,
                          span_max=None, cap_days=None):
    """规划本轮北向采集自然日窗口 [win_start, win_end](闭区间,纯函数可单测)。

    分轮累积(v1.1.7 P1):gap 超 span_max 或已有 resume 前沿时进入深缺口模式——
    - 'deep_start'  深缺口首轮:今日向回 span_max 天;
    - 'deep_resume' 分轮续采:从上次前沿的前一天再向回 span_max 天(无缝衔接,
                    前沿由 fetch 收尾按本轮实际覆盖写入);
    - 'deep_cap'    前沿已越过硬顶(HKEX 源保留窗≈7个月),放弃分轮回归常规增量;
    - 'plain'       常规增量:min(span_max, max(HKEX_DAYS_MIN, gap+1)) 天,与旧版一致;
    - 'no_db'       查库异常:保守 span_max 增量(绝不冒险全量);
    - 'full'        库空首次全量:cap_days 全量窗。
    返回 (win_start, win_end, mode);深缺口模式下 win 内逐日先查库探测闭合。
    """
    if span_max is None:
        span_max = HKEX_DAYS_MAX
    if cap_days is None:
        cap_days = HKEX_BACKFILL_CAP_DAYS
    one_day = _dt.timedelta(days=1)
    if not known:
        return today - one_day * (span_max - 1), today, "no_db"
    if gap is None:
        return today - one_day * (cap_days - 1), today, "full"
    # 有 resume 前沿 或 缺口超上限 = 深缺口模式(前沿存在期间即使 gap 变小也续采)
    deep = (gap + 1) > span_max or resume_from is not None
    if not deep:
        n = min(span_max, max(HKEX_DAYS_MIN, gap + 1))
        return today - one_day * (n - 1), today, "plain"
    if resume_from is not None:
        lower_bound = today - one_day * (cap_days - 1)
        # 前沿已抵/越硬顶(源保留窗):无法再无缝前进一步(再压窗会致 win 倒挂死锁),
        # 放弃分轮回归常规增量
        if resume_from <= lower_bound:
            return today - one_day * (span_max - 1), today, "deep_cap"
        win_end = resume_from - one_day    # 无缝衔接:从上轮覆盖边界前一天继续
        win_start = max(win_end - one_day * (span_max - 1), lower_bound)
        return win_start, win_end, "deep_resume"
    return today - one_day * (span_max - 1), today, "deep_start"


def fetch_north_fund_hkex(days=None, soft_deadline_s=None):
    """HKEX 官方每日统计 JS：北向成交总额（沪股通+深股通 Total Turnover 合计），
    返回 [(date_YYYYMMDD, value_亿元), ...]。

    数据源: HKEX_DAILY_STAT_URL 模板，每天一个 JS 文件，tabData=[...] JSON 数组。
    - SSE/SZSE Northbound 的 content[0].table.tr[0].td[0][0] = Total Turnover（百万 RMB）
    - 沪深合计 / 100 = 亿元
    - 对照：2026-07-24 SSE=136054.83 + SZSE=147782.45 = 283837.28 百万 = 2838.37 亿
      与东财 kamt/get buySellAmt 一致（hk2sh+hk2sz=28383728.86 万=2838.37 亿）

    保留窗口约 7 个月（实测 2025-12-29 起，更早 404）。周末/假日 404 跳过。

    2026-08-26 预算治理(根治 90 天固定窗口 vs 90s 守护预算矛盾):
    - days 缺口自适应:缺省查库内该指标最新日期,只拉缺口天数(HKEX_DAYS_MIN~MAX 夹紧,
      平时 3-10 天 ≈ <20s 完成);仅首次全量(库空)才用 HKEX_DAYS_FULL 大窗口
    - 软 deadline(HKEX_SOFT_DEADLINE_S):循环到点 break「部分采集 N/M 天」,
      部分成功好过被外层 90s 守护整体砍掉(fallback 也因此可达);余量下次采集槽补
    - 跳过周六日:HKEX 周末必 404 但仍花 ~2s/请求,过滤省 ~30% 无效请求

    2026-08-27 深缺口分轮累积(v1.1.7 P1 修复:「增量截断→递增丢日」):
    - 缺口超单轮上限(HKEX_DAYS_MAX)时不再放弃更早段——首轮采最近 span_max 天并把
      「已覆盖最早日期」写 state 前沿(app/data/north_fund_backfill_state.json),
      后续轮从前沿前一天无缝向更早推进一轮 span_max,直到查库撞见既有完好数据行
      (闭合探测)即清前沿回归常规增量;软 deadline 中断同理按实际覆盖记前沿
    - 行级 upsert 幂等,重复请求无害;并发双槽下前沿可能倒退但收敛
    - 硬顶 HKEX_BACKFILL_CAP_DAYS(≈源保留窗):推到顶仍未闭合则清前沿告警,
      回归常规增量(更早历史需人工/fallback 全量兜底)
    - 窗口规划提炼为纯函数 plan_north_gap_window(可单测),复现脚本见
      scripts/check_north_gap_backfill.py

    C3 升级：从东财 kamt/get 切到 HKEX 官方权威源，减少东财依赖，反爬风险更低。
    """
    if soft_deadline_s is None:
        soft_deadline_s = HKEX_SOFT_DEADLINE_S

    rows = []
    today = _dt.date.today()
    t0 = _dt.datetime.now()
    one_day = _dt.timedelta(days=1)
    attempted = 0  # 已发起请求的工作日数(deadline break 日志「部分采集 N/M 天」的 M)
    oldest_done = None   # 本轮实际覆盖到的最早日期(深缺口模式收尾写回前沿)
    closed_date = None   # 闭合探测撞见的既有完好数据日(非 None 即闭合)

    if days is not None:
        # 显式传参(测试/手动):行为与旧版完全一致,不触碰分轮 state
        win_start, win_end, mode = today - one_day * (days - 1), today, "manual"
    else:
        state_e = _north_backfill_load_earliest()
        gap, known = _north_fund_gap_days()
        win_start, win_end, mode = plan_north_gap_window(
            today, gap=gap, known=known, resume_from=state_e)
        if mode == "deep_cap":
            print(f"[a_fund_north][hkex] 分轮回补前沿 {state_e} 已越过硬顶 "
                  f"{HKEX_BACKFILL_CAP_DAYS}天(≈源保留窗),放弃分轮回归常规增量; "
                  f"如需更早历史请人工处理(东财 fallback1 全量或手动补)")
            _north_backfill_clear()   # 放弃分轮:清前沿防无限重试
        elif mode == "plain" and state_e:
            # 常规增量但前沿残留(gap 已收窄至常规可覆盖):视为闭合清态。
            # 注意"只清本轮读到的",并发窗口内他槽新写的前沿不受本路径影响
            _north_backfill_clear()

    probe_deep = mode in ("deep_start", "deep_resume")
    if probe_deep and mode == "deep_resume":
        print(f"[a_fund_north][hkex] 深缺口分轮续采: 本轮窗口 "
              f"{win_start:%Y%m%d}~{win_end:%Y%m%d}(上轮前沿 {win_end + one_day:%Y%m%d} 之前段)")
    elif probe_deep:
        print(f"[a_fund_north][hkex] 深缺口首轮回补: 窗口 {win_start:%Y%m%d}~"
              f"{win_end:%Y%m%d}(缺口超单轮上限,分轮累积逐轮向更早推进)")

    # 倒序产出窗口内非周末日(周末 HKEX 必 404 不浪费 ~2s/请求);
    # 生成器承担推进职责,循环体 continue/break 都不会死循环/漏步进
    def _iter_days():
        dd = win_end
        while dd >= win_start:
            if dd.weekday() < 5:
                yield dd
            dd -= one_day

    for d in _iter_days():
        elapsed = (_dt.datetime.now() - t0).total_seconds()
        if elapsed > soft_deadline_s:
            frontier_s = f"{oldest_done:%Y%m%d}" if oldest_done else "无(本轮尚未覆盖任何日)"
            print(f"[a_fund_north][hkex] 软deadline {soft_deadline_s}s 到点break: "
                  f"部分采集 {len(rows)}行成功/{attempted}工作日已尝试 "
                  f"(本轮窗口{win_start:%Y%m%d}~{win_end:%Y%m%d}未跑完,"
                  f"前沿已记到 {frontier_s},余量下轮续采)")
            break
        oldest_done = d
        date_str = d.strftime("%Y%m%d")
        if probe_deep and _north_fund_date_exists(date_str):
            # 闭合探测:此日库中已有行(既有完好连续段的边界)→ 更早已连续,
            # 整个缺口已补完,清前沿回归常规增量(更深日子无需再扫)
            closed_date = d
            break
        url = HKEX_DAILY_STAT_URL.format(date=date_str)
        try:
            r = requests.get(
                url,
                headers={"User-Agent": UA, "Referer": HKEX_DAILY_STAT_REFERER},
                timeout=15,
            )
            if r.status_code != 200:
                continue  # 周末/假日/早期 404 跳过
            m = _re.search(r"tabData\s*=\s*(\[.*\])\s*;?\s*$", r.text, _re.DOTALL)
            if not m:
                continue
            try:
                arr = json.loads(m.group(1))
            except json.JSONDecodeError:
                continue
            # SSE Northbound + SZSE Northbound 合计
            total = 0.0
            found = 0
            for rec in arr:
                market = rec.get("market", "")
                if "Northbound" not in market:
                    continue
                content = rec.get("content") or []
                if not content:
                    continue
                table = content[0].get("table") or {}
                trs = table.get("tr") or []
                if not trs:
                    continue
                td = trs[0].get("td") or []
                if not td or not td[0]:
                    continue
                # td[0] 是 ["136,054.83"] 列表（schema 第一列 Total Turnover）
                val = td[0][0] if isinstance(td[0], list) else td[0]
                val_str = str(val).replace(",", "").strip()
                try:
                    total += float(val_str)
                    found += 1
                except ValueError:
                    continue
            if found == 2:  # 沪+深都找到
                rows.append((date_str, total / 100.0))  # 百万 -> 亿元
        except Exception:
            continue  # 单日失败不跳出，继续下一日

    # ── 分轮 state 收尾(仅 auto 模式):闭合清态 / 深缺口写前沿 ──
    if days is None and probe_deep:
        if closed_date is not None:
            print(f"[a_fund_north][hkex] 缺口已闭合于既有数据日 "
                  f"{closed_date:%Y%m%d}(本轮取数 {len(rows)}行),"
                  f"清除回补前沿,回归常规增量")
            _north_backfill_clear()
        elif oldest_done is not None:
            _north_backfill_save_earliest(oldest_done)
            print(f"[a_fund_north][hkex] 本轮覆盖至 {oldest_done:%Y%m%d}"
                  f"(取数 {len(rows)}行),前沿已写入;下轮从更早段继续分轮回补")
    return rows


def fetch_north_fund_total():
    """北向资金成交总额（沪股通+深股通 Total Turnover 合计），返回 [(date_YYYYMMDD, value_亿元), ...]。

    背景：2024-08 港交所新规取消盘中实时净买额披露后，东财 RPT_MUTUAL_DEAL_HISTORY 的
    NET_DEAL_AMT（净买额）/BUY_AMT/SELL_AMT 全 null 停更，akshare stock_hsgt_hist_em 的
    「当日成交净买额」返 NaN（fetchers.py L141 跳 NaN 致 20240816 后不入库）。
    方案A 救急：改用同接口的 DEAL_AMT（成交总额=买+卖）替代。语义从「净流入方向」变
    「市场活跃度」，sentiment north direction 仍 positive（成交总额大=市场活跃）。
    方案B（CCASS 反算真净买额）实测不可行：2024-08 新规后北向持股改季度披露，
    只能拿季度末快照，反算出来是季度净买额非日频。改用 C2 季度反算单独指标。

    主源（C3 升级）：HKEX 官方每日统计 JS（权威源，数据与东财一致，反爬风险低）
      2026-08-26 起 days 缺口自适应（fetch_north_fund_hkex 内查库），不再固定 90 天
    fallback 1：东财 datacenter RPT_MUTUAL_DEAL_HISTORY（全量历史 ~2716 日，HKEX 失败兜底）
    fallback 2：东财 push2 kamt/get（当日，datacenter 也失败时最后兜底）

    2026-08-26 预算治理:主源循环带软 deadline(60s < collect_direct 90s 守护),
    主源空/异常时 fallback 真正可达(此前 90 天慢爬必被外层守护整体砍掉,fallback 从未轮到);
    fallback 页循环同样带剩余预算检查,保证整个函数在守护预算内可返回。

    2026-08-27 主源升级深缺口分轮累积(v1.1.7 P1):长假/长停机后缺口 >10 自然日
    不再单轮截断丢更早段,而是逐轮向更早推进直至闭合(详见 fetch_north_fund_hkex docstring)。
    """
    _t0 = _dt.datetime.now()

    def _elapsed():
        return (_dt.datetime.now() - _t0).total_seconds()

    # 主源：HKEX 官方 JS（缺口自适应增量；软 deadline 到点部分返回）
    try:
        rows = fetch_north_fund_hkex()
        if rows:
            return rows
    except Exception:
        pass  # HKEX 封禁/网络异常 -> 走东财 fallback

    # fallback 1：datacenter-web RPT_MUTUAL_DEAL_HISTORY（历史日K，全量 ~3 页）
    # 剩余预算检查:主源已耗 ~60s 时只再给 ~20s(留 ~10s 给 fallback 2 与收尾),
    # 防「主源慢爬 + fallback 全量页」叠加超 90s 守护预算。
    rows = []
    try:
        for page in range(1, 6):  # 最多 5 页兜底（实测 3 页）
            if _elapsed() > 80.0:
                print(f"[a_fund_north] fallback1 剩余预算耗尽({_elapsed():.0f}s), "
                      f"停止翻页,已拿 {len(rows)} 行")
                break
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

    # fallback 2：push2 kamt/get 拿当日（只今天 1 天，无历史）
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


def fetch_north_fund_ccass_quarterly():
    """CCASS 季度反算北向净买额（C2 指标），返回 [(quarter_end_YYYYMMDD, value_亿元), ...]。

    包装 app.collector.hkex_ccass_quarterly.fetch_north_fund_ccass_quarterly。
    详见 hkex_ccass_quarterly.py 模块文档。
    """
    from .hkex_ccass_quarterly import fetch_north_fund_ccass_quarterly as _fetch
    return _fetch()
