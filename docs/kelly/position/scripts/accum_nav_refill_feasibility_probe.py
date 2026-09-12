#!/usr/bin/env python3
"""全量实测 154 只缺价 ETF: 逐只调 fund_open_fund_info_em, 精确统计可补/源缺"""
#!/usr/bin/env python3
"""全量实测 accum_nav 历史缺价可补性(2026-09-06,researcher 实地重采验证)
目的: 回答「不靠外源补不出价格了吗?是采集源问题吗?」——逐只调 akshare fund_open_fund_info_em 全史序列,
     比对 2081 条缺价日是否有源值, 精确统计可补/源缺, 并定位源缺 ETF 名单。
口径: 可补 = 东财累计净值走势全史序列含该日; 源缺 = 序列不含(可能海外休市/时滞/两源均无)。
输入依赖: /tmp/accum_nav_gap_rows.json(由 accum_nav_gap_list.py 生成, 只读主库 etf_national_team.db)
输出: 逐只打印可补/源缺; 结果落 /tmp/accum_nav_full_probe_result.json
复现命令: python3 accum_nav_gap_list.py && python3 accum_nav_refill_feasibility_probe.py
数据截止: 20260904(主库 etf_daily + 东财源最新交易日)
"""

import akshare as ak, json, collections, time, sqlite3, sys

rows = json.load(open('/tmp/accum_nav_gap_rows.json'))
by_etf = collections.defaultdict(list)
for code, d, kind in rows:
    by_etf[code].append((d, kind))

conn = sqlite3.connect('/Users/linhuichen/code/trade-data/data/etf_national_team.db')
cur = conn.cursor()
codes = list({r[0] for r in rows})
ph = ",".join("?" * len(codes))
cur.execute(f"SELECT DISTINCT etf_code, etf_name FROM etf_daily WHERE etf_code IN ({ph})", codes)
name_map = dict(cur.fetchall())

result = {}
refill_total = 0
src_missing_total = 0
day_total = len(rows)
for i, code in enumerate(sorted(codes), 1):
    gap = by_etf[code]
    gap_dates = [d for d, _ in gap]
    names = name_map.get(code, '?')
    time.sleep(0.5)
    try:
        df = ak.fund_open_fund_info_em(symbol=code, indicator="累计净值走势")
        src = {}
        if df is not None and len(df) > 0:
            for _, r in df.iterrows():
                d = str(r.get("净值日期")).replace("-", "")[:8]
                try: src[d] = float(r.get("累计净值"))
                except Exception: pass
        refill = [d for d in gap_dates if d in src]
        miss = [d for d in gap_dates if d not in src]
        refill_total += len(refill)
        src_missing_total += len(miss)
        result[code] = {"name": names, "n": len(gap), "refill": len(refill), "miss": len(miss),
                        "miss_dates": sorted(miss)[:8]}
        print(f"[{i:3d}/{len(codes)}] {code} {names}: 缺{len(gap):3d} 可补{len(refill):3d} 源缺{len(miss):3d}", flush=True)
    except Exception as e:
        result[code] = {"name": names, "n": len(gap), "refill": -1, "miss": -1, "err": str(e)[:80]}
        print(f"[{i:3d}/{len(codes)}] {code} {names}: API异常 {type(e).__name__}", flush=True)
        sys.stdout.flush()

print("\n=== 全量实测汇总 ===")
print(f"总缺价日: {day_total}")
print(f"实测可补: {refill_total} ({refill_total/day_total*100:.1f}%)")
print(f"实测源缺: {src_missing_total} ({src_missing_total/day_total*100:.1f}%)")
src_missing_codes = {c: r for c, r in result.items() if r.get('miss', 0) > 0}
print(f"源缺涉及的ETF数: {len(src_missing_codes)}")
for c, r in sorted(src_missing_codes.items(), key=lambda x: -x[1]['miss']):
    print(f"  {c} {r['name']}: 源缺{r['miss']}日 样例{r['miss_dates'][:6]}")
with open('/tmp/accum_nav_full_probe_result.json', 'w') as f:
    json.dump(result, f, ensure_ascii=False, indent=2)
