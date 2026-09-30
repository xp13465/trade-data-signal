# -*- coding: utf-8 -*-
"""#140 实测:FAPI 涨停池分页行为(只读,2 次调用)。验证 size=200 是否被 clamp + total vs 返回条数。"""
import datetime as dt
import sys
import requests

BASE = "https://fuyao.aicubes.cn"
KEY = None
for cand in ("/Users/linhuichen/code/trade/.env", "/Users/linhuichen/code/trade-data/.env"):
    try:
        for line in open(cand, encoding="utf-8", errors="replace"):
            if line.startswith("HITHINK_FINANCE_API_KEY="):
                KEY = line.split("=", 1)[1].strip().strip('"').strip("'")
                break
    except (IOError, FileNotFoundError):
        pass
    if KEY:
        break
assert KEY, "key not found"
H = {"X-api-key": KEY}

def date_ms(yyyymmdd):
    d = dt.datetime.strptime(yyyymmdd, "%Y%m%d").replace(tzinfo=dt.timezone(dt.timedelta(hours=8)))
    return int(d.timestamp() * 1000)

def call(path, params, tag):
    r = requests.get(f"{BASE}{path}", headers=H, params=params, timeout=30)
    j = r.json()
    print(f"[{tag}] http={r.status_code} code={j.get('code')} msg={str(j.get('message'))[:60]}")
    return j.get("data") or {}

for date in ("20241008", "20240930"):
    d = call("/api/a-share/special-data/limit-up-pool",
             {"date_ms": date_ms(date), "page": 1, "size": 200}, f"up {date} size200")
    pag = d.get("pagination") or {}
    items = d.get("item") or []
    print(f"  total={pag.get('total')} pages={pag.get('pages')} page={pag.get('page')} "
          f"size={pag.get('size')} 返回条数={len(items)}")
    if items:
        print(f"  首条={items[0].get('name')} 连板={items[0].get('continue_day_cnt')}  末条={items[-1].get('name')} 连板={items[-1].get('continue_day_cnt')}")

# 用 20241008 验证 size=500 是否被 clamp(多拿一页对比)
d = call("/api/a-share/special-data/limit-up-pool",
         {"date_ms": date_ms("20241008"), "page": 1, "size": 500}, "up 20241008 size500")
pag = d.get("pagination") or {}
items = d.get("item") or []
print(f"  total={pag.get('total')} pages={pag.get('pages')} page={pag.get('page')} "
      f"size={pag.get('size')} 返回条数={len(items)}")

# 翻页验证 page=2
d = call("/api/a-share/special-data/limit-up-pool",
         {"date_ms": date_ms("20241008"), "page": 2, "size": 200}, "up 20241008 page2")
pag = d.get("pagination") or {}
items = d.get("item") or []
print(f"  total={pag.get('total')} pages={pag.get('pages')} page={pag.get('page')} "
      f"size={pag.get('size')} 返回条数={len(items)}")
