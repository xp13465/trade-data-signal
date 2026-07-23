#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 data/board_etf_map.json：行业/概念 -> 相关 ETF 候选列表（按成交额降序）。

设计原则（对齐用户诉求）：
  - 匹配到多个就全列出来，按成交额（流动性）降序，让用户在前端自选；
  - 匹配不到就留空数组（不再硬塞"代理"ETF，避免名称对不上误导用户）；
  - 关键词尽量精准（避免"消费"误匹配消费电子、"设备"误匹配半导体设备）；
  - 排除跨境/债券/商品/货币等非行业主题 ETF。

数据源：akshare fund_etf_spot_em()（A 股场内 ETF 实时行情，含成交额/流通市值）。
可重复跑：python scripts/build_board_etf_map.py，覆盖 data/board_etf_map.json。
"""
import json
import sys
from pathlib import Path

import akshare as ak

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.collector.fetchers import load_config

OUT = ROOT / "data" / "board_etf_map.json"

# 每个板块的匹配关键词（同义词，ETF 名称命中任一即候选；空列表 = 主动留空）
KW: dict[str, list[str]] = {
    # ---- 申万一级行业 ----
    "sw_801010": ["农林", "农牧", "养殖", "农业", "牧渔"],
    "sw_801030": ["化工"],
    "sw_801040": ["钢铁"],
    "sw_801050": ["有色"],
    "sw_801080": ["电子"],
    "sw_801880": ["汽车", "新能源车"],
    "sw_801110": ["家电"],
    "sw_801120": ["食品", "酒", "饮料"],
    "sw_801130": ["纺织", "服装", "服饰"],
    "sw_801140": ["轻工", "造纸", "家居", "文娱"],
    "sw_801150": ["医药", "医疗", "生物", "创新药", "中药"],
    "sw_801160": ["公用事业"],
    "sw_801170": ["交通", "运输"],
    "sw_801180": ["房地产", "地产"],
    "sw_801200": ["商贸", "零售", "百货", "商业"],
    "sw_801210": ["旅游", "社服"],
    "sw_801780": ["银行"],
    "sw_801790": ["证券", "保险", "非银"],
    "sw_801230": [],  # 综合行业无专门 ETF，主动留空
    "sw_801710": ["建材"],
    "sw_801720": ["建筑", "基建", "装饰"],
    "sw_801730": ["电力设备", "电池", "光伏", "风电", "储能", "新能源"],
    "sw_801890": ["机械", "工程机械", "机床"],
    "sw_801740": ["军工", "国防"],
    "sw_801750": ["计算机", "软件", "信息技术"],
    "sw_801760": ["传媒", "媒体", "游戏"],
    "sw_801770": ["通信"],
    "sw_801950": ["煤炭"],
    "sw_801960": ["石油", "石化"],
    "sw_801970": ["环保"],
    "sw_801980": ["美容", "护理", "化妆品"],
    # ---- 同花顺概念 ----
    "thsc_300816": ["机器人"],
    "thsc_309119": ["机器人"],
    "thsc_308700": ["碳化硅", "氮化镓", "宽禁带", "第三代"],  # 收紧：无专门ETF则留空
    "thsc_309049": ["CPO", "光通信", "光模块", "光子"],
    "thsc_301085": ["芯片", "半导体"],
    "thsc_307940": ["存储芯片", "存储"],
    "thsc_302035": ["人工智能", "AI"],
    "thsc_309068": ["算力", "数据中心", "IDC"],
    "thsc_308828": ["算力", "数据中心", "IDC"],
    "thsc_309020": ["信创", "信息技术应用"],
    "thsc_309060": ["数据"],
    "thsc_300008": ["新能源车", "新能源", "汽车"],
    "thsc_301079": ["光伏"],
    "thsc_300733": ["电池", "锂电"],
    "thsc_306380": ["储能"],
    "thsc_308294": ["固态", "电池"],
    "thsc_309115": ["低空", "通用航空", "eVTOL"],
    "thsc_308014": ["创新药", "医药"],
    "thsc_300082": ["军工", "国防"],
    "thsc_300830": ["量子"],
    "thsc_308725": ["汽车芯片", "车芯片"],  # 收紧：无专门ETF则留空
    "thsc_308300": ["MCU", "单片机"],       # 收紧：无专门ETF则留空
    "thsc_309113": ["eVTOL", "飞行汽车", "通用航空"],
    "thsc_308491": ["氢能", "氢"],
    "thsc_308870": ["数字经济"],
    "thsc_308752": ["元宇宙", "虚拟现实", "VR", "增强现实", "AR"],
    "thsc_309128": ["军工", "国防", "信息化"],
}

# 排除词：跨境/债券/商品/货币等非 A 股行业主题 ETF
EXCLUDE = ["债", "货币", "黄金", "白银", "原油", "海外", "美国", "日本", "德国",
           "法国", "英国", "韩国", "中韩", "亚太", "纳斯达克", "标普", "日经",
           "恒生", "港股", "香港", "QDII", "商品", "豆粕", "REIT", "可转债",
           "国债", "信用", "MOM", "FOF"]

# P2-新-G ETF 联动推荐：宽基/红利指数 -> 跟踪 ETF 代码清单。
# 汪汪队 app/collector/etf_national_team.py ETF_LIST 覆盖 7 宽基
#   (sz50/hs300/csi500/csi1000/cyb/kc50)：直接复用其代码清单。
# 补充汪汪队未覆盖：bj50 北证50 + 3 红利指数（csi_div/div_lowvol/sz_div）。
# sh 上证指数 / sz 深成指为综合指数，性质决定无跟踪 ETF，不加入（前端不渲染 tag，
#   _etf_for 返空数组 -> _renderEtfTag 返空串 -> 标题不显示 ETF tag）。
# 这里只列代码，name/amount 由 akshare fund_etf_spot_em() 实时填（与行业关键词匹配同源）。
INDEX_ETF_MAP: dict[str, list[str]] = {
    # ── 7 宽基（汪汪队 ETF_LIST 覆盖，代码与 ETF_LIST 一致）──
    "sz50":    ["510050"],                                    # 上证50
    "hs300":   ["510300", "510310", "159919"],                # 沪深300
    "csi500":  ["510500", "159922"],                          # 中证500
    "csi1000": ["512100", "159845"],                          # 中证1000
    "cyb":     ["159915", "159952"],                          # 创业板指
    "kc50":    ["588000", "588050"],                          # 科创50
    # ── 汪汪队未覆盖，手动补充 ──
    "bj50":        ["159509", "593550"],                      # 北证50
    "csi_div":     ["515080", "515100", "515090"],            # 中证红利
    "div_lowvol":  ["512890"],                               # 红利低波
    "sz_div":      ["159905"],                               # 深证红利
}


def main():
    cfg = load_config()
    name_by_id = {i["id"]: i["name"] for i in cfg.get("indices", [])}
    # 只为 industry/concept 生成
    board_ids = [i["id"] for i in cfg.get("indices", [])
                 if i.get("market") in ("industry", "concept") and i.get("enabled", True)]

    df = ak.fund_etf_spot_em()
    df["成交额"] = df["成交额"].fillna(0)
    names = df["名称"].astype(str)
    # 预计算排除掩码
    excl_mask = names.apply(lambda n: any(ex in n for ex in EXCLUDE))
    # P2-新-G: 按代码精确匹配宽基/红利指数 ETF（与行业关键词匹配同源，amount 取 fund_etf_spot_em 实时值）
    df_by_code = {}
    if "代码" in df.columns:
        for _, r in df.iterrows():
            df_by_code[str(r["代码"])] = r

    out: dict = {"_meta": {"source": "akshare fund_etf_spot_em",
                           "sort_by": "成交额(亿元,降序)",
                           "note": "匹配不到为空数组；前端按成交额排序展示，用户自选"}}
    empty_boards = []
    for iid in board_ids:
        kws = KW.get(iid, [])
        if not kws:
            out[iid] = []
            empty_boards.append(f"{iid} {name_by_id.get(iid)}")
            continue
        mask = ~excl_mask & names.apply(lambda n: any(k in n for k in kws))
        hit = df[mask].sort_values("成交额", ascending=False)
        etfs = []
        for _, r in hit.iterrows():
            etfs.append({
                "code": str(r["代码"]),
                "name": str(r["名称"]),
                "amount": round(float(r["成交额"]) / 1e8, 2),  # 亿元
            })
        out[iid] = etfs
        if not etfs:
            empty_boards.append(f"{iid} {name_by_id.get(iid)}")

    # P2-新-G: 宽基/红利指数 -> 跟踪 ETF 候选（代码精确匹配，按成交额降序）
    # 覆盖 sz50/hs300/csi500/csi1000/cyb/kc50/bj50/csi_div/div_lowvol/sz_div 10 个指数。
    # sh 上证指数/sz 深成指无跟踪 ETF，不在此处加入（前端不渲染 tag）。
    for iid, codes in INDEX_ETF_MAP.items():
        etfs = []
        for code in codes:
            r = df_by_code.get(code)
            if r is None:
                continue  # akshare 无此代码（已退市/未上市），跳过
            try:
                etfs.append({
                    "code": str(code),
                    "name": str(r["名称"]),
                    "amount": round(float(r["成交额"]) / 1e8, 2),
                })
            except (TypeError, ValueError, KeyError):
                continue
        etfs.sort(key=lambda x: x.get("amount", 0), reverse=True)
        out[iid] = etfs
        if not etfs:
            empty_boards.append(f"{iid} {name_by_id.get(iid, iid)}（宽基/红利）")

    # 写盘
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    # 摘要
    total = len(board_ids)
    n_empty = len(empty_boards)
    dist = {"0": 0, "1": 0, "2-3": 0, "4+": 0}
    for iid in board_ids:
        n = len(out.get(iid, []))
        if n == 0:
            dist["0"] += 1
        elif n == 1:
            dist["1"] += 1
        elif n <= 3:
            dist["2-3"] += 1
        else:
            dist["4+"] += 1
    print(f"生成 {OUT.name}：{total} 板块 + {len(INDEX_ETF_MAP)} 宽基/红利指数")
    print(f"候选数分布(行业/概念): 0个={dist['0']}  1个={dist['1']}  2-3个={dist['2-3']}  4+个={dist['4+']}")
    print(f"\n宽基/红利指数 ETF 联动（{len(INDEX_ETF_MAP)} 个，sh/sz 综合指数无跟踪ETF不含）:")
    for iid in INDEX_ETF_MAP.keys():
        etfs = out.get(iid, [])
        if etfs:
            e = etfs[0]
            extra = f" +{len(etfs)-1}" if len(etfs) > 1 else ""
            print(f"  {name_by_id.get(iid, iid):<10} {e['code']} {e['name']} ({e['amount']}亿){extra}")
        else:
            print(f"  {name_by_id.get(iid, iid):<10} (无匹配ETF)")
    print(f"\n留空板块（{n_empty}，无相关ETF/主动留空）:")
    for b in empty_boards:
        print(f"  {b}")
    # 抽样展示 top1
    print("\n各板块 top1（成交额最大）抽样:")
    for iid in board_ids:
        etfs = out.get(iid, [])
        if etfs:
            e = etfs[0]
            extra = f" +{len(etfs)-1}" if len(etfs) > 1 else ""
            print(f"  {name_by_id.get(iid, iid):<16} {e['code']} {e['name']} ({e['amount']}亿){extra}")


if __name__ == "__main__":
    main()
