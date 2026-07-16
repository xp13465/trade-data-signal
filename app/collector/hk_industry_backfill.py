"""港股板块指数一次性回填脚本。

遍历 config market: hk_industry 的指数，逐只调 collect_index（底层
stock_hk_index_daily_sina，返全量历史），upsert index_daily。
每只间隔 sleep 3s 防封 IP（源码注释"大量采集会被封IP"）。

用法:
    .venv/bin/python -m app.collector.hk_industry_backfill
    # 或
    .venv/bin/python -c "from app.collector.hk_industry_backfill import main; main()"
"""
import time

from . import fetchers
from .runner import upsert_index_rows


def main(verbose: bool = True):
    cfg = fetchers.load_config()
    hk_inds = [i for i in cfg.get("indices", []) if i.get("market") == "hk_industry" and i.get("enabled", True)]
    if not hk_inds:
        print("config 无 market: hk_industry 指数，退出")
        return
    print(f"=== 港股板块指数回填 开始 {len(hk_inds)} 只 ===")
    ok, fail = 0, 0
    for idx in hk_inds:
        idx_id = idx["id"]
        try:
            rows, msg = fetchers.collect_index(idx, "20100101", "20991231")
            if rows:
                upsert_index_rows(rows)
                ok += 1
                last = rows[-1]
                print(f"  ✓ {idx_id} ({idx['name']}): {len(rows)} 行, 最新 {last[0]} close={last[5]}")
            else:
                fail += 1
                print(f"  ✗ {idx_id} ({idx['name']}): 空 ({msg})")
        except Exception as e:  # noqa: BLE001
            fail += 1
            print(f"  ✗ {idx_id} ({idx['name']}): ERROR {e}")
        time.sleep(3)  # 防封 IP
    print(f"=== 港股板块指数回填 完成: ok={ok} fail={fail} ===")


if __name__ == "__main__":
    main()
