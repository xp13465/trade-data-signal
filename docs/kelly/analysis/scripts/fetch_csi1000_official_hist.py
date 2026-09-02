#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
目的: 调研中证1000(000852)历史数据前滚可行性 —— 抓取官网(中证指数公司)全史点位并做一致性对账。
方法口径: 官网 index-perf 接口(中证官网, 免费, 带 Referer 校验) 返回 2004-12-31(基日) 起 OHLC 全史。
          akshare 已封装该接口(stock_zh_index_hist_csindex, 当前版本 1.18.64 实测可用)。
          数据 = 指数公司官方回溯点位(基日 2004-12-31, 基点 1000; 指数 2014-10-17 正式发布)。
输入依赖: 1) 本机 akshare(接口 stock_zh_index_hist_csindex); 2) static-site/data/index/csi1000-all.json(现新浪源, 用于重合段对账)。
输出:     /tmp/csi1000-probe/csi1000-official-full.json(全史标准格式 date/open/high/low/close) + 终端对账统计。
复现命令: python3 docs/kelly/analysis/scripts/fetch_csi1000_official_hist.py
"""
import json, warnings, datetime, sys, os
warnings.filterwarnings("ignore")
import akshare as ak

OUT = "/tmp/csi1000-probe/csi1000-official-full.json"
PROJ_JSON = os.path.join(os.path.dirname(__file__), "../../../../static-site/data/index/csi1000-all.json")
# 注意: __file__ 为 docs/kelly/analysis/scripts/, 上溯 4 级到仓库根
PROJ_JSON = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../../static-site/data/index/csi1000-all.json"))

def fetch_segment(symbol, start, end):
    df = ak.stock_zh_index_hist_csindex(symbol=symbol, start_date=start, end_date=end)
    out = []
    for _, r in df.iterrows():
        d = str(r["日期"])
        out.append({"tradeDate": d.replace("-", ""),
                    "open": r["开盘"], "high": r["最高"], "low": r["最低"],
                    "close": r["收盘"], "changePct": r["涨跌幅"]})
    return out

def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    seg1 = fetch_segment("000852", "20041231", "20150101")
    seg2 = fetch_segment("000852", "20150101", "20260902")
    rows = seg1 + seg2
    seen = {}
    for r in rows:
        if r["tradeDate"] not in seen:  # 去重(官网节假日重复行)
            seen[r["tradeDate"]] = r
    keys = sorted(seen)
    # 过滤明显节假日/重复行: 相邻同日值或非工作日由对账报告标注, 这里保留去重后序列
    data = [seen[k] for k in keys]
    json.dump({"count": len(data), "first": keys[0], "last": keys[-1], "data": data},
              open(OUT, "w"), ensure_ascii=False)
    print(f"[fetch] 全史 {keys[0]} ~ {keys[-1]} 共 {len(data)} 交易日, 已存 {OUT}")

    # ---- 重合段对账(20141017~): 官网 vs 项目新浪源 ----
    proj = json.load(open(PROJ_JSON))
    proj_map = {r["date"]: r for r in proj["ohlc"]}
    off_map = {r["tradeDate"]: r for r in data}
    common = sorted(set(proj_map) & set(off_map))
    diff = [(d, proj_map[d]["close"], off_map[d]["close"]) for d in common
            if abs(proj_map[d]["close"] - off_map[d]["close"]) > 0.05]  # 容忍 0.05 舍入差
    print(f"[align] 重合交易日 {len(common)}; close 偏差>0.05 天数: {len(diff)}")
    for d, pc, oc in diff[:5]:
        print(f"    {d}: 新浪={pc} 官网={oc}")

if __name__ == "__main__":
    main()
