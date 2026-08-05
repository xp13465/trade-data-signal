"""黄金/原油夜盘收盘价补采 + global JSON 导出。

02:40 launchd 触发(com.trade.gold-night, 02:30 夜盘收盘后 10min 裕量)。
闸门 is_trading_day(昨日): 昨晚有夜盘才跑(覆盖周五夜盘周六02:40跑;
周日/周一凌晨跳过, 周日晚无夜盘)。

采 nf_AU0(沪金)->gold / nf_SC0(INE原油)->oil 夜盘收盘价,
写 daily_metric source=gold_night; 导出 global-{3m,6m,1y,3y,5y,all}.json
+ global-extras-all.json。

夜盘缺口(本任务补): intraday_snapshot 最后一槽 20:35 在夜盘21:00开盘前
拿日盘收盘价; 02:00 backfill / 05:00 us-stock-morning 都不采 gold;
夜盘21:00-02:30收盘价无任务采, 要到次日09:25 intraday 才反映。

日期归属: 写 date=today(自然日, nf_AU0[17] 跨日后=今日)。
- 周二-周五02:40 写夜盘收盘价, 当日09:25 intraday 覆盖为日盘开盘价(用户要的效果);
- 周六02:40 写周五夜盘收盘价 date=周六(非交易日 intraday 跳过, 值保留);
- futures_main_sina(T+1日线, indicators.yaml gold 配置) 次日盘后覆盖为最终收盘历史值
  (写 date=交易日, UPSERT 幂等, 不动 date=周六点)。

跑法: cd trade-data && python -m app.collector.gold_night
(cwd=trade-data 让 app.db 读主库 trade-data/data/sentiment.db, 见 CLAUDE.md §9)
"""
import datetime as dt
import sys
from pathlib import Path

# __file__ 从 -m 跑 = trade-data/app/collector/gold_night.py (symlink 不 resolve)
# _ROOT = trade-data/ (读主库 + 写 trade-data/static-site/data, rsync 源)
# _TRADE = trade/ (resolve symlink, 找 static-site/export.py)
_ROOT = Path(__file__).absolute().parent.parent.parent
_TRADE = Path(__file__).resolve().parent.parent.parent

# 先确保 trade-data/ 在 sys.path 最前(-m 已加 cwd=trade-data, 显式保险),
# 让 import app 从 trade-data/app(symlink) 加载 -> db.py 读主库
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# 1) 先 import app.*(从 trade-data/ 加载并缓存, 读主库 trade-data/data/sentiment.db)
from app.calendar import is_trading_day  # noqa: E402
from app.collector.fetchers import load_config  # noqa: E402
from app.collector.intraday_snapshot import fetch_commodity_realtime  # noqa: E402
from app.collector.runner import upsert_metric  # noqa: E402
from app.db import get_conn  # noqa: E402

# 2) 后 import export(export.py sys.path.insert(trade/), 但 app 已缓存读主库)
sys.path.insert(0, str(_TRADE / "static-site"))
import export as ex  # noqa: E402

DATA_DIR = _ROOT / "static-site" / "data"  # trade-data/static-site/data (rsync 源)

# nf_ 国内期货 -> metric_id 映射(同 intraday_snapshot.COMMODITY_TO_METRIC 子集)
COMMODITY_METRIC = {"nf_AU0": "gold", "nf_SC0": "oil"}


def main() -> int:
    today = dt.date.today()
    yesterday = today - dt.timedelta(days=1)
    # 闸门: 昨晚有夜盘才跑(昨日是交易日)。覆盖周五夜盘周六02:40跑;
    # 不用 is_trading_day(today) 避免周六跳过漏周五夜盘。
    if not is_trading_day(yesterday):
        print(f"[gold_night] 昨日 {yesterday} 非交易日, 无夜盘, 跳过", flush=True)
        return 0

    today_str = today.strftime("%Y%m%d")
    print(f"[gold_night] 开始 {dt.datetime.now().isoformat()} "
          f"今日={today_str} 昨日={yesterday}(交易日) -> 采夜盘收盘价", flush=True)

    # 1) 采集 nf_AU0/nf_SC0 夜盘收盘价(新浪批量实时源, 02:30 收盘后返回定格收盘价)
    commodities = fetch_commodity_realtime()
    if not commodities:
        print("[gold_night] 商品实时采集返回空, 跳过", flush=True)
        return 1

    n = 0
    for c in commodities:
        code = c.get("code", "")
        metric_id = COMMODITY_METRIC.get(code)
        if not metric_id:
            continue  # 只写 gold/oil, 跳过外盘 hf_*
        price = c.get("price")
        if price is None:
            print(f"[gold_night] {code} price=None 跳过", flush=True)
            continue
        snap = c.get("datetime", "")
        upsert_metric(today_str, metric_id, price, source="gold_night")
        print(f"[gold_night] 写入 daily_metric {metric_id}={price} "
              f"date={today_str} snap={snap} source=gold_night", flush=True)
        n += 1

    if n == 0:
        print("[gold_night] 未写入任何商品指标(nf_AU0/nf_SC0 均缺失), 跳过导出", flush=True)
        return 1

    # 2) 导出 global-*.json + global-extras-all.json(复用 export.export_global + write_json)
    # conn 用 app.db.get_conn(主库 trade-data/data/sentiment.db, 上面 import 已缓存读主库)
    cfg = load_config()
    conn = get_conn()
    ex._series_cache.clear()  # 新进程本就空, 显式清保险
    for rng in ex.EXPORT_RANGES:
        data = ex.export_global(conn, cfg, rng)
        fname = f"global-{rng}.json"
        sz = ex.write_json(DATA_DIR / fname, data)
        print(f"[gold_night] {fname} ({sz} bytes)", flush=True)
        if rng == "all":
            # 信号弹窗 extras 四件套(同 export.py main L710-714)
            sz2 = ex.write_json(
                DATA_DIR / "global-extras-all.json",
                {k: data[k] for k in ("extras", "extras_signals",
                                      "extras_stats", "extras_strategy")})
            print(f"[gold_night] global-extras-all.json ({sz2} bytes)", flush=True)
    conn.close()
    print(f"[gold_night] 完成: 写入 {n} 指标 + 导出 global {len(ex.EXPORT_RANGES)} range",
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
