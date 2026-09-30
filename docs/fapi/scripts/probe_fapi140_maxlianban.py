# -*- coding: utf-8 -*-
"""#140 补充:全 4 页拉取验证 max_lianban 截断影响(只读,4 次调用)。"""
import datetime as dt, requests
BASE = "https://fuyao.aicubes.cn"
KEY = None
for cand in ("/Users/linhuichen/code/trade/.env", "/Users/linhuichen/code/trade-data/.env"):
    try:
        for line in open(cand, encoding="utf-8", errors="replace"):
            if line.startswith("HITHINK_FINANCE_API_KEY="):
                KEY = line.split("=",1)[1].strip().strip('"').strip("'"); break
    except (IOError, FileNotFoundError): pass
    if KEY: break
H = {"X-api-key": KEY}
def date_ms(y):
    return int(dt.datetime.strptime(y,"%Y%m%d").replace(tzinfo=dt.timezone(dt.timedelta(hours=8))).timestamp()*1000)
d0 = requests.get(f"{BASE}/api/a-share/special-data/limit-up-pool",
                  headers=H, params={"date_ms": date_ms("20241008"),"page":1,"size":200}, timeout=30).json()["data"]
total, pages = d0["pagination"]["total"], d0["pagination"]["pages"]
all_max = 0; p1_max = 0
for pg in range(1, pages+1):
    d = requests.get(f"{BASE}/api/a-share/special-data/limit-up-pool",
                     headers=H, params={"date_ms": date_ms("20241008"),"page":pg,"size":200}, timeout=30).json()["data"]
    its = d["item"]
    mx = max((it.get("continue_day_cnt") or 0 for it in its), default=0)
    print(f"page={pg} 条数={len(its)} 本页max连板={mx} 末条={its[-1]['name']}连板={its[-1].get('continue_day_cnt')}")
    if pg == 1: p1_max = mx
    if mx > all_max: all_max = mx
print(f"total={total} pages={pages} 第一页max连板={p1_max} 全量max连板={all_max} -> 截断影响max_lianban={p1_max != all_max}")
