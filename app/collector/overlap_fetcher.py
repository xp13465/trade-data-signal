#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""成分股重叠算法 fetcher -- 给行业/概念指数匹配相关 ETF。

算法：概念成分股 ∩ ETF跟踪指数成分股，Jaccard 重叠度 = |交集|/|并集|。
用途：当 build_board_etf_map.py 的 KW 关键词匹配为空时（如 MCU/CPO/算力等
无同名 ETF 的概念），用成分股重叠度找到最相关的行业 ETF。

数据源：
  - 概念成分股：push2delay.eastmoney.com（东财 BK 板块成分股，push2 被封 delay 子域可用）
  - ETF 成分股：ak.index_stock_cons(symbol=指数代码)（新浪源，支持中证/国证/中证全指）

输出条目格式（与 KW 匹配条目同构，额外含重叠度指标）：
  {code, name, amount, approx, jaccard, coverage, inter}
"""
import time
import json
from pathlib import Path

import requests
import akshare as ak

# ===== 1. 概念 -> 东财 BK 代码映射 =====
# 9 个 KW 匹配为空的 thsc 概念（8 目标 + 东数西算）。
# 验证 agent 已确认 7 个 BK 代码 + MCU 用 BK0891 国产芯片近似。
# thsc_308828 东数西算与 thsc_309068 算力租赁共用 BK1134（东财"算力概念"）。
CONCEPT_BK_MAP: dict[str, dict] = {
    "thsc_308300": {"bk": "BK0891", "name": "MCU芯片",
                    "approx": True,
                    "approx_note": "东财无MCU独立概念,用国产芯片BK0891近似"},
    "thsc_309049": {"bk": "BK1128", "name": "共封装光学(CPO)"},
    "thsc_309068": {"bk": "BK1134", "name": "算力租赁"},
    "thsc_308828": {"bk": "BK1134", "name": "东数西算(算力)"},
    "thsc_308700": {"bk": "BK0952", "name": "第三代半导体"},
    "thsc_308491": {"bk": "BK0864", "name": "氢能源"},
    "thsc_300830": {"bk": "BK0710", "name": "量子科技"},
    "thsc_308725": {"bk": "BK0969", "name": "汽车芯片"},
    "thsc_307940": {"bk": "BK1137", "name": "存储芯片"},
}

# ===== 2. 行业指数池 -> {name, kw} =====
# index_stock_cons 验证可用的 25 个主题指数（跳过 500+ 成分股的宽基指数）。
# kw: 用于在 fund_etf_spot_em 中按 ETF 名称匹配该指数对应的 ETF。
#     kw 匹配任一关键词且不命中 EXCLUDE 即候选（同 build_board_etf_map.py KW 逻辑）。
INDEX_POOL: dict[str, dict] = {
    # -- 芯片/半导体 --
    "980017":  {"name": "中证芯片产业",     "kw": ["芯片"]},
    "931087":  {"name": "半导体材料设备",   "kw": ["半导体设备"]},
    "931079":  {"name": "中证芯片",         "kw": ["芯片"]},
    "931160":  {"name": "通信半导体",       "kw": ["通信", "半导体"]},
    "H30184":  {"name": "国证芯片",         "kw": ["芯片"]},
    # -- 通信 --
    "399389":  {"name": "国证通信",         "kw": ["通信"]},
    # -- AI/算力/云计算 --
    "930712":  {"name": "中证人工智能",     "kw": ["人工智能", "AI"]},
    "930697":  {"name": "中证云计算",       "kw": ["云计算", "云"]},
    "930651":  {"name": "中证云计算50",     "kw": ["云计算", "云"]},
    "931643":  {"name": "中证云计算40",     "kw": ["云计算", "云"]},
    "931865":  {"name": "云计算50",         "kw": ["云计算", "云"]},
    # -- 机器人 --
    "399283":  {"name": "机器人50",         "kw": ["机器人"]},
    # -- 新能源/汽车 --
    "399808":  {"name": "中证新能源",       "kw": ["新能源"]},
    "000941":  {"name": "新能源",           "kw": ["新能源"]},
    "399266":  {"name": "创新能源",         "kw": ["新能源"]},
    "399417":  {"name": "国证新能源汽车",   "kw": ["新能源车", "新能源"]},
    "930998":  {"name": "中证汽车",         "kw": ["汽车"]},
    # -- 军工 --
    "399368":  {"name": "国证军工",         "kw": ["军工", "国防"]},
    "399959":  {"name": "军工指数",         "kw": ["军工"]},
    "399386":  {"name": "中证军工",         "kw": ["军工"]},
    # -- 金融 --
    "399986":  {"name": "中证银行",         "kw": ["银行"]},
    "399975":  {"name": "中证证券",         "kw": ["证券", "券商"]},
    # -- 消费 --
    "399394":  {"name": "国证食品饮料",     "kw": ["食品", "酒", "饮料"]},
    "930627":  {"name": "中证消费电子",     "kw": ["消费电子"]},
    "931022":  {"name": "中证消费电子(21)", "kw": ["消费电子"]},
}

# 排除词（与 build_board_etf_map.py EXCLUDE 同源）
EXCLUDE = ["债", "货币", "黄金", "白银", "原油", "海外", "美国", "日本", "德国",
           "法国", "英国", "韩国", "中韩", "亚太", "纳斯达克", "纳指", "标普", "日经",
           "恒生", "港股", "香港", "QDII", "商品", "豆粕", "REIT", "可转债",
           "国债", "信用", "MOM", "FOF"]

PUSH2_URL = "https://push2delay.eastmoney.com/api/qt/clist/get"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 Chrome/120.0 Safari/537.36",
    "Referer": "https://quote.eastmoney.com/",
}

# 每概念 Top-N 相关指数 -> 每指数 Top-N ETF -> 合并去重后取 Top-N ETF
TOP_N_INDICES = 8   # 每概念取 Jaccard 前 8 的指数
TOP_N_ETFS = 5      # 最终每概念输出 Top-5 ETF
# 交集数阈值：低于此值认为无意义重叠（噪声），跳过
MIN_INTERSECTION = 3


def fetch_concept_cons(bk_code: str) -> set[str]:
    """push2delay 拿东财概念板块成分股，自动翻页。

    返回 6 位股票代码集合；失败返回空集（调用方回退 KW 匹配）。
    """
    all_codes: set[str] = set()
    for pn in range(1, 6):  # 最多 5 页 = 500 只
        params = {
            "pn": str(pn), "pz": "100", "po": "1", "np": "1",
            "ut": "bd1d9ddb04089700cf9c27f6f7426281", "fltt": "2", "invt": "2",
            "fid": "f12", "fs": f"b:{bk_code} f:!50", "fields": "f12,f14",
        }
        try:
            r = requests.get(PUSH2_URL, params=params, headers=HEADERS, timeout=10)
            d = r.json()
            items = d.get("data", {}).get("diff", []) if d.get("data") else []
            if not items:
                break
            for it in items:
                code = str(it.get("f12", "")).zfill(6)
                if code and code != "0":
                    all_codes.add(code)
            if len(items) < 100:
                break
        except Exception:
            break
    return all_codes


def fetch_index_cons(index_code: str) -> set[str]:
    """index_stock_cons 拿指数成分股（新浪源）。

    返回 6 位股票代码集合；失败返回空集。
    """
    try:
        df = ak.index_stock_cons(symbol=index_code)
        # 列名可能为"品种代码"或"代码"
        col = "品种代码" if "品种代码" in df.columns else df.columns[0]
        return set(str(c).zfill(6) for c in df[col] if c)
    except Exception:
        return set()


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def match_overlap(df, df_by_code: dict, excl_mask) -> dict[str, list[dict]]:
    """主入口：对 9 个空概念跑重叠算法，返回 {thsc_id: [etf entries]}。

    参数:
      df: ak.fund_etf_spot_em() 返回的 DataFrame（含 代码/名称/成交额 列）
      df_by_code: {etf_code: row}（build_board_etf_map.py 预计算）
      excl_mask: df 的 boolean Series（True = 命中 EXCLUDE 排除词）

    返回:
      {thsc_id: [{code, name, amount, approx, jaccard, coverage, inter}, ...]}
      每概念 Top-5 ETF，按 Jaccard 降序（同 Jaccard 按成交额降序）。
      概念成分股采不到或全部无交集 -> 返回空列表（调用方保留旧值/KW 空数组）。
    """
    names = df["名称"].astype(str)
    t0 = time.time()

    # Step 1: 采概念成分股
    print("  [overlap] Step1: 采概念成分股 (push2delay)")
    concept_cons: dict[str, set[str]] = {}
    push2_ok = True
    for thsc_id, info in CONCEPT_BK_MAP.items():
        s = time.time()
        codes = fetch_concept_cons(info["bk"])
        concept_cons[thsc_id] = codes
        dt = time.time() - s
        if not codes:
            push2_ok = False
            print(f"    {thsc_id} {info['name']}({info['bk']}): 0只 [WARN]")
        else:
            print(f"    {thsc_id} {info['name']}({info['bk']}): {len(codes)}只 {dt:.2f}s")
        time.sleep(0.4)  # 限流防封

    if not push2_ok:
        print("  [overlap] ⚠ 部分概念成分股采不到(push2delay被封?)，已采到的继续算")

    # Step 2: 采指数成分股（缓存，多概念共用）
    print(f"  [overlap] Step2: 采 {len(INDEX_POOL)} 指数成分股 (index_stock_cons)")
    index_cons: dict[str, set[str]] = {}
    for idx_code, idx_info in INDEX_POOL.items():
        s = time.time()
        codes = fetch_index_cons(idx_code)
        index_cons[idx_code] = codes
        dt = time.time() - s
        if codes:
            print(f"    {idx_code} {idx_info['name']}: {len(codes)}只 {dt:.2f}s")
        else:
            print(f"    {idx_code} {idx_info['name']}: 0只 [SKIP]")
        time.sleep(0.2)

    # Step 3: 每概念算重叠度 -> Top 指数 -> 匹配 ETF
    print("  [overlap] Step3: 重叠度计算 + ETF匹配")
    result: dict[str, list[dict]] = {}

    for thsc_id, info in CONCEPT_BK_MAP.items():
        c_codes = concept_cons.get(thsc_id, set())
        concept_approx = info.get("approx", False)
        if not c_codes:
            print(f"    {thsc_id} {info['name']}: 无成分股,跳过")
            result[thsc_id] = []
            continue

        # 算每个指数的 Jaccard + 交集 + 覆盖率
        scores = []
        for idx_code, idx_info in INDEX_POOL.items():
            e_codes = index_cons.get(idx_code, set())
            if not e_codes:
                continue
            inter = len(c_codes & e_codes)
            if inter < MIN_INTERSECTION:
                continue
            jac = _jaccard(c_codes, e_codes)
            coverage = inter / len(c_codes) if c_codes else 0.0
            scores.append((idx_code, idx_info, len(e_codes), inter, jac, coverage))

        scores.sort(key=lambda x: (x[4], x[3]), reverse=True)  # Jaccard 降序, 交集降序
        top_indices = scores[:TOP_N_INDICES]

        if not top_indices:
            print(f"    {thsc_id} {info['name']}: 无交集≥{MIN_INTERSECTION}的指数,留空")
            result[thsc_id] = []
            continue

        # 对 Top 指数，按 kw 匹配 ETF，每指数的 ETF 继承该指数的 Jaccard
        etf_map: dict[str, dict] = {}  # etf_code -> entry（去重，保留最高 Jaccard）
        for idx_code, idx_info, e_n, inter, jac, cov in top_indices:
            kw = idx_info["kw"]
            mask = ~excl_mask & names.apply(
                lambda n: any(k in str(n) for k in kw)
            )
            hit = df[mask].sort_values("成交额", ascending=False)
            for _, r in hit.iterrows():
                code = str(r["代码"])
                rname = str(r["名称"])
                try:
                    amount = round(float(r["成交额"]) / 1e8, 2)
                except (TypeError, ValueError):
                    amount = 0.0
                approx = concept_approx or ("增强" in rname)
                # 去重：同一 ETF 保留最高 Jaccard
                if code not in etf_map or jac > etf_map[code]["jaccard"]:
                    etf_map[code] = {
                        "code": code,
                        "name": rname,
                        "amount": amount,
                        "approx": approx,
                        "jaccard": round(jac, 4),
                        "coverage": round(cov, 4),
                        "inter": inter,
                    }

        # 按 Jaccard 降序，同 Jaccard 按成交额降序
        etfs = sorted(
            etf_map.values(),
            key=lambda x: (x["jaccard"], x["amount"]),
            reverse=True,
        )[:TOP_N_ETFS]
        result[thsc_id] = etfs

        top_names = [f"{e['code']}({e['name']},J={e['jaccard']})" for e in etfs[:3]]
        print(f"    {thsc_id} {info['name']}: {len(etfs)}只ETF -> {', '.join(top_names)}")

    dt = time.time() - t0
    n_nonempty = sum(1 for v in result.values() if v)
    print(f"  [overlap] 完成: {n_nonempty}/{len(result)} 概念非空, 耗时 {dt:.1f}s")
    return result


if __name__ == "__main__":
    # 独立测试入口
    print("=== overlap_fetcher 独立测试 ===")
    df = ak.fund_etf_spot_em()
    df["成交额"] = df["成交额"].fillna(0)
    names = df["名称"].astype(str)
    excl_mask = names.apply(lambda n: any(ex in n for ex in EXCLUDE))
    df_by_code = {}
    if "代码" in df.columns:
        for _, r in df.iterrows():
            df_by_code[str(r["代码"])] = r

    result = match_overlap(df, df_by_code, excl_mask)
    print("\n=== 结果 ===")
    for thsc_id, etfs in result.items():
        info = CONCEPT_BK_MAP.get(thsc_id, {})
        print(f"\n{thsc_id} {info.get('name','')}: {len(etfs)}只")
        for e in etfs:
            print(f"  {e['code']} {e['name']} {e['amount']}亿 "
                  f"J={e['jaccard']} cov={e['coverage']} inter={e['inter']}"
                  f"{' [approx]' if e.get('approx') else ''}")
