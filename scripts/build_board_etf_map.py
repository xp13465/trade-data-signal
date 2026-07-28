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

ROOT = Path(__file__).absolute().parent.parent
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
           "法国", "英国", "韩国", "中韩", "亚太", "纳斯达克", "纳指", "标普", "日经",
           "恒生", "港股", "香港", "QDII", "商品", "豆粕", "REIT", "可转债",
           "国债", "信用", "MOM", "FOF"]

# P2-新-G ETF 联动推荐：宽基/红利/综合/港股指数 -> 跟踪 ETF 候选清单。
# 2026-07-28 方案D第二阶段：用 data/etf_index_map.json 自动采集替代原硬编码 INDEX_ETF_MAP。
#
# 数据源 data/etf_index_map.json（1555只ETF，ok=1228有track_index_code）：
#   结构 {etf_code: {name, track_index_name, track_index_code, track_index_ths_code, amount, status}}
#   建反向映射 {track_index_code: [etf_info列表]}，按指数ID->track_index_code 自动匹配 ETF 候选。
#
# 覆盖 14 个指数（bj50 北证50 无活跃跟踪ETF，留空，前端 _etf_for 返空数组不渲染 tag）：
#   A股宽基 8: sh/sz/hs300/sz50/csi500/csi1000/cyb/kc50
#   红利指数 3: csi_div/div_lowvol/sz_div
#   港股指数 3: hsi/hstech/hscei（跨境ETF，cross_border=True 绕过 EXCLUDE 防御）
#
# 修正原硬编码 bug（2026-07-28）：
#   - hscei 原 513900 实跟踪"中华港股通精选100港元指数"（track_index_code 为空），非 HSCEI！
#     自动采集修正为 510900（恒生中国企业ETF易方达 1.16亿居首）。
#   - hsi 原 513600（0.86亿）非首位，自动采集首位 159920（恒生ETF华夏 4.83亿）。
#   - sz 原 159943（0.81亿）非首位，自动采集首位 159903（深成ETF南方 1.70亿）。
#
# 数据源污染过滤（name_eq 规则）：
#   - csi_div=000922 被"中证红利低波动100指数/中证红利价值指数/中证红利质量指数"共用 track_index_code，
#     需 track_index_name=="中证红利指数" 过滤（排除红利低波100等）。
#   - div_lowvol=930955 被"标普中国A股大盘红利低波50指数/国证港股通红利低波动率指数"共用，
#     需 track_index_name=="中证红利低波动指数" 过滤。
#
# approx 判定：ETF name 含"增强" -> True（增强型ETF，非纯被动跟踪）；否则 False（纯被动精准跟踪）。
# cross_border 判定：港股指数（HSI/HSTECH/HSCEI）-> True，name 含"恒生/港股"会命中 EXCLUDE，需绕过防御。
#
# 候选结构：list[dict]，每项 {"code": str, "name": str, "amount": float, "approx": bool}
#   name/amount 优先用 akshare fund_etf_spot_em() 实时值（df_by_code），查不到用 etf_index_map.json 的 amount。
#   按 amount 降序排（成交额大的居首，流动性最好）。
ETF_INDEX_MAP_PATH = Path(__file__).resolve().parent.parent / "data" / "etf_index_map.json"
# resolve() 解析 symlink：从 trade-data 跑时 scripts/ 是 symlink 指向 trade/scripts/，
# resolve() 后读 trade/data/etf_index_map.json（真实路径，前序任务生成在此）。

# 指数ID -> {code: track_index_code, name_eq?: 过滤规则, cross_border?: bool} 映射
# code: 该指数跟踪的标准指数代码（etf_index_map.json 的 track_index_code 字段）
# name_eq: 可选，track_index_name 必须精确等于此值（过滤数据源污染）
# cross_border: 可选，True=港股跨境ETF（绕过 EXCLUDE 防御）
INDEX_TRACK_MAP: dict[str, dict] = {
    # ── A股宽基（track_index_code 无污染，直接匹配）──
    "sh":       {"code": "000001"},   # 上证综合指数（8个精准ETF，510210首位14.13亿）
    "sz":       {"code": "399001"},   # 深证成份指数（159903首位1.70亿/159943 0.81亿）
    "hs300":    {"code": "000300"},   # 沪深300（510300首位78.32亿）
    "sz50":     {"code": "000016"},   # 上证50（510050首位23.11亿）
    "csi500":   {"code": "000905"},   # 中证500（510500首位60.44亿）
    "csi1000":  {"code": "000852"},   # 中证1000（512100首位53.03亿）
    "cyb":      {"code": "399006"},   # 创业板指（159915首位127.93亿）
    "kc50":     {"code": "000688"},   # 科创50（588000首位109.59亿）
    # bj50: 899050 北证50，etf_index_map.json 无活跃跟踪ETF，不加入（留空）
    # ── 红利指数（track_index_code 有数据源污染，需 name_eq 过滤）──
    "csi_div":    {"code": "000922", "name_eq": "中证红利指数"},        # 中证红利（515180首位3.77亿）
    "div_lowvol": {"code": "930955", "name_eq": "中证红利低波动指数"},  # 红利低波（512890首位7.75亿）
    "sz_div":     {"code": "399324"},   # 深证红利（159905首位0.69亿，无污染）
    # ── 港股指数（跨境ETF，cross_border=True 绕过 EXCLUDE 防御）──
    "hsi":     {"code": "HSI", "cross_border": True},     # 恒生指数（159920首位4.83亿）
    "hstech":  {"code": "HSTECH", "cross_border": True},  # 恒生科技（513130首位31.24亿）
    "hscei":   {"code": "HSCEI", "cross_border": True},   # 恒生中国企业（510900首位1.16亿，修正原513900 bug）
}


def _load_etf_index_map_reverse() -> dict[str, list[dict]]:
    """读 data/etf_index_map.json，建反向映射 {track_index_code: [etf_info列表]}。

    返回 {track_index_code: [{code, name, amount, track_index_name}, ...]}（只含 status=ok 的 ETF）。
    resolve() 解析 symlink：从 trade-data 跑时读 trade/data/etf_index_map.json（真实路径）。
    读不到返回空 dict（自动采集退化为空，指数ETF候选全空，不影响行业/概念关键词匹配）。
    """
    if not ETF_INDEX_MAP_PATH.exists():
        print(f"⚠ etf_index_map.json 不存在: {ETF_INDEX_MAP_PATH}，指数ETF自动采集退化为空")
        return {}
    try:
        with open(ETF_INDEX_MAP_PATH, encoding="utf-8") as f:
            d = json.load(f)
    except Exception as e:
        print(f"⚠ etf_index_map.json 读取失败: {e}，指数ETF自动采集退化为空")
        return {}
    rev: dict[str, list[dict]] = {}
    for etf_code, info in d.items():
        if etf_code.startswith("_") or not isinstance(info, dict):
            continue
        tic = info.get("track_index_code") or ""
        if not tic:
            continue
        if info.get("status", "") != "ok":
            continue  # 跳过 parse_fail/no_track
        rev.setdefault(tic, []).append({
            "code": etf_code,
            "name": info.get("name", ""),
            "amount": info.get("amount", 0) or 0,
            "track_index_name": info.get("track_index_name", ""),
        })
    return rev


def _build_index_etf_map_auto(reverse_map: dict[str, list[dict]], df_by_code: dict) -> dict[str, list[dict]]:
    """自动采集生成指数->ETF候选映射: {index_id: [{code, name, amount, approx}, ...]}。

    - 从 reverse_map 按 track_index_code 拿 ETF 列表
    - 按 track_index_name 过滤（name_eq 规则，排除数据源污染）
    - 按 etf_index_map.json 的 amount 降序预排（akshare 实时 amount 后面填，顺序基本一致）
    - approx: ETF name 含"增强" -> True（增强型ETF），否则 False（纯被动）
    - cross_border: 港股指数 -> True（绕过 EXCLUDE 防御）
    - amount/name 优先用 akshare 实时值（df_by_code），查不到用 etf_index_map.json 的 amount
    - 代码复用绕过防御：非跨境ETF检查 akshare name 不含 EXCLUDE（2026-07-20 事故：159509复用为纳指科技）
    """
    result: dict[str, list[dict]] = {}
    for iid, rule in INDEX_TRACK_MAP.items():
        tic = rule["code"]
        name_eq = rule.get("name_eq")
        cross_border = rule.get("cross_border", False)
        cands = reverse_map.get(tic, [])
        if name_eq:
            cands = [c for c in cands if c["track_index_name"] == name_eq]
        cands_sorted = sorted(cands, key=lambda x: x["amount"], reverse=True)
        etfs = []
        for c in cands_sorted:
            code = c["code"]
            etf_name_src = c["name"]
            approx = "增强" in etf_name_src
            r = df_by_code.get(code) if df_by_code else None
            if r is not None:
                try:
                    rname = str(r["名称"])
                    if not cross_border and any(ex in rname for ex in EXCLUDE):
                        print(f"  [跳过] {iid} {code} {rname}（name 命中 EXCLUDE，代码复用绕过防御）")
                        continue
                    amount = round(float(r["成交额"]) / 1e8, 2)
                    etf_name = rname
                except (TypeError, ValueError, KeyError):
                    amount = round(c["amount"] / 1e8, 2)
                    etf_name = etf_name_src
            else:
                amount = round(c["amount"] / 1e8, 2)
                etf_name = etf_name_src
            etfs.append({"code": code, "name": etf_name, "amount": amount, "approx": approx})
        result[iid] = etfs
    return result


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
                "approx": False,  # 行业/概念关键词匹配均为精准跟踪
            })
        out[iid] = etfs
        if not etfs:
            empty_boards.append(f"{iid} {name_by_id.get(iid)}")

    # P2-新-G: 宽基/红利/综合/港股指数 -> 跟踪 ETF 候选（自动采集，按成交额降序）
    # 从 data/etf_index_map.json 自动采集替代原硬编码 INDEX_ETF_MAP（2026-07-28 方案D第二阶段）。
    # 覆盖 sh/sz/hs300/sz50/csi500/csi1000/cyb/kc50/csi_div/div_lowvol/sz_div/hsi/hstech/hscei 14 个指数
    # （bj50 北证50 无活跃跟踪ETF，留空）。
    # 修正原硬编码 bug：hscei 原 513900 实跟踪"中华港股通精选100"非 HSCEI，自动采集修正为 510900 居首。
    reverse_map = _load_etf_index_map_reverse()
    index_etf_map = _build_index_etf_map_auto(reverse_map, df_by_code)
    for iid, etfs in index_etf_map.items():
        out[iid] = etfs
        if not etfs:
            empty_boards.append(f"{iid} {name_by_id.get(iid, iid)}（宽基/红利/综合/港股）")

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
    print(f"生成 {OUT.name}：{total} 板块 + {len(index_etf_map)} 宽基/红利/综合/港股指数（自动采集自 etf_index_map.json）")
    print(f"候选数分布(行业/概念): 0个={dist['0']}  1个={dist['1']}  2-3个={dist['2-3']}  4+个={dist['4+']}")
    print(f"\n宽基/红利/综合/港股指数 ETF 联动（{len(index_etf_map)} 个，自动采集）:")
    for iid in index_etf_map.keys():
        etfs = out.get(iid, [])
        if etfs:
            e = etfs[0]
            extra = f" +{len(etfs)-1}" if len(etfs) > 1 else ""
            approx_tag = " [approx]" if e.get("approx") else ""
            print(f"  {name_by_id.get(iid, iid):<10} {e['code']} {e['name']} ({e['amount']}亿){extra}{approx_tag}")
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
