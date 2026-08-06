#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 data/etf_index_map.json：全量 ETF -> 跟踪指数代码反向映射表。

数据源：akshare fund_etf_spot_em()（A 股场内 ETF 实时行情，~1567 只）。
akshare 的 fund_etf_spot_em 本身不返回 track_index_code 字段，本脚本通过 ETF 名称
关键词匹配（INDEX_NAME_RULES include/exclude）反推每只 ETF 跟踪的标准指数代码，
生成 build_board_etf_map.py 所需的 {etf_code: {name, track_index_name, track_index_code,
track_index_ths_code, amount, status}} 结构。

设计背景（2026-08-06 事故修复）：
  - 原 data/etf_index_map.json（1555 只，ok=1228 有 track_index_code）从未成功生成进 git，
    生成脚本也不在 repo，本地丢失。
  - build_board_etf_map.py 的 _load_etf_index_map_reverse 读不到只 warning + exit 0 静默失败，
    致 board_etf_map.json 14 宽基/红利/港股指数全空数组，首页"全部无 ETF"。
  - 本脚本由 deploy.sh 前置调用，每次 deploy 刷新 etf_index_map.json，确保映射是新的。
  - 名称匹配反推 track_index_code 是 akshare 无 bulk track_index_code 接口下的务实方案，
    覆盖 build_board_etf_map.py INDEX_TRACK_MAP 的 14 个指数（唯一消费者）。
    其他 ETF（非 14 指数跟踪）status=no_track，track_index_code 为空。

可重复跑：python scripts/gen_etf_index_map.py，覆盖 data/etf_index_map.json。
"""
import json
import sys
from pathlib import Path

import akshare as ak

ROOT = Path(__file__).absolute().parent.parent
OUT = ROOT / "data" / "etf_index_map.json"

# 14 指数名称匹配规则（include/exclude 关键词，反推 track_index_code）。
# 覆盖 build_board_etf_map.py INDEX_TRACK_MAP 的 14 个指数：
#   A股宽基 8: sh/sz/hs300/sz50/csi500/csi1000/cyb/kc50
#   红利指数 3: csi_div/div_lowvol/sz_div
#   港股指数 3: hsi/hstech/hscei
# include: ETF 名称命中任一即候选；exclude: 命中任一排除（精度过滤）。
# 规则已用 fund_etf_spot_em 实盘数据验证精度（2026-08-06）。
#
# sz_div（深证红利 399324）：ETF 名"红利ETF工银"(159905) 无"深"字，名称无法区分深证红利
# vs 上证红利，include=[] 主动留空（前端 _etf_for 返空数组不渲染 tag，非事故）。
INDEX_NAME_RULES: dict[str, dict] = {
    # ── A股宽基 ──
    "sh":        {"code": "000001", "name": "上证综合指数",
                  "include": ["上证指数", "上证综指", "上证综合"], "exclude": []},
    "sz":        {"code": "399001", "name": "深证成份指数",
                  "include": ["深成", "深证成指"], "exclude": ["深成长", "深成成长"]},
    "hs300":     {"code": "000300", "name": "沪深300指数",
                  "include": ["沪深300"], "exclude": []},
    "sz50":      {"code": "000016", "name": "上证50指数",
                  "include": ["上证50"], "exclude": []},
    "csi500":    {"code": "000905", "name": "中证500指数",
                  "include": ["中证500"], "exclude": ["A500"]},
    "csi1000":   {"code": "000852", "name": "中证1000指数",
                  "include": ["中证1000"], "exclude": []},
    "cyb":       {"code": "399006", "name": "创业板指数",
                  "include": ["创业板ETF", "创业板增强"], "exclude": []},
    "kc50":      {"code": "000688", "name": "科创50指数",
                  "include": ["科创50"], "exclude": []},
    # ── 红利指数 ──
    "csi_div":    {"code": "000922", "name": "中证红利指数",
                   "include": ["中证红利"], "exclude": ["低波"]},
    "div_lowvol": {"code": "930955", "name": "中证红利低波动指数",
                   "include": ["红利低波"],
                   "exclude": ["50", "100", "300", "800", "恒生", "港股"]},
    "sz_div":     {"code": "399324", "name": "深证红利指数",
                   "include": [], "exclude": []},  # 名称无法区分，留空
    # ── 港股指数（跨境ETF）──
    "hsi":     {"code": "HSI", "name": "恒生指数",
                "include": ["恒生ETF", "恒生指数"],
                "exclude": ["科技", "中国企业", "互联", "医疗"]},
    "hstech":  {"code": "HSTECH", "name": "恒生科技指数",
                "include": ["恒生科技"], "exclude": []},
    "hscei":   {"code": "HSCEI", "name": "恒生中国企业指数",
                "include": ["恒生中国企业", "恒生国企"], "exclude": []},
}


def main():
    print(f"-> 拉取 akshare fund_etf_spot_em() 全量 ETF 行情 ...")
    df = ak.fund_etf_spot_em()
    df["成交额"] = df["成交额"].fillna(0)
    print(f"   共 {len(df)} 只 ETF")

    # 建 指数code -> rule 反查表（一只 ETF 可能命中多个指数？理论上不会，名称互斥）
    # 按 include/exclude 匹配，记录每只 ETF 命中的指数
    out: dict = {}
    n_ok = 0
    n_no_track = 0
    # 统计每指数命中数
    per_index: dict[str, int] = {iid: 0 for iid in INDEX_NAME_RULES}

    for _, r in df.iterrows():
        code = str(r["代码"])
        name = str(r["名称"])
        amount = float(r["成交额"]) or 0.0
        matched_iid = None
        for iid, rule in INDEX_NAME_RULES.items():
            inc = rule["include"]
            exc = rule["exclude"]
            if not inc:
                continue  # sz_div 主动留空
            if any(k in name for k in inc) and not any(k in name for k in exc):
                matched_iid = iid
                break  # 取首个命中（名称互斥，不会多命中）
        if matched_iid:
            rule = INDEX_NAME_RULES[matched_iid]
            out[code] = {
                "name": name,
                "track_index_name": rule["name"],
                "track_index_code": rule["code"],
                "track_index_ths_code": "",  # akshare 无此字段，留空
                "amount": round(amount, 2),  # 元
                "status": "ok",
            }
            n_ok += 1
            per_index[matched_iid] += 1
        else:
            out[code] = {
                "name": name,
                "track_index_name": "",
                "track_index_code": "",
                "track_index_ths_code": "",
                "amount": round(amount, 2),
                "status": "no_track",  # 非 14 指数跟踪，无 track_index_code
            }
            n_no_track += 1

    # 写盘
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    # 摘要
    print(f"✓ 生成 {OUT.name}：{len(out)} 只 ETF（ok={n_ok} 有 track_index_code，no_track={n_no_track}）")
    print(f"\n14 指数命中分布（名称匹配反推 track_index_code）:")
    for iid, rule in INDEX_NAME_RULES.items():
        n = per_index[iid]
        tag = "（主动留空，名称无法区分）" if not rule["include"] else ""
        print(f"  {iid:<12} {rule['code']:<8} {rule['name']:<20} {n} 只{tag}")

    # 校验：14 指数中非 sz_div 的 13 个必须有命中（sz_div 留空属预期）
    empty_unexpected = [iid for iid in INDEX_NAME_RULES
                        if INDEX_NAME_RULES[iid]["include"] and per_index[iid] == 0]
    if empty_unexpected:
        print(f"\n✗ 校验失败：以下指数名称匹配 0 命中（规则过严或 akshare 数据异常）: {empty_unexpected}",
              file=sys.stderr)
        sys.exit(1)
    print(f"\n✓ 校验通过：13 个指数（除 sz_div 主动留空）均有 ETF 命中")


if __name__ == "__main__":
    main()
