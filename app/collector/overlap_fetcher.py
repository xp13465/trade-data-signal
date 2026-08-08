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


# ===== 3. 第4层：ETF持仓重叠匹配 =====
# 通过 ak.stock_fund_stock_holder(symbol) 反向查找持有概念成分股的ETF。
# 绕过 INDEX_POOL 限制，直接发现持有概念股的ETF（如量子科技 -> 央企科技/通信ETF）。
# 季频数据（基金季报披露），缓存7天避免重复采集。

# 持仓重叠阈值
MIN_OVERLAP_HOLDINGS = 2   # 至少持有2只概念股
TOP_N_HOLDINGS_ETFS = 12   # 每概念输出Top-12 ETF（track_score 后续重排，多给候选）
# 缓存路径（data/ 不入 git，CLAUDE.md §8）
HOLDINGS_CACHE_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "holdings_overlap_cache.json"
HOLDINGS_CACHE_TTL = 7 * 24 * 3600  # 7天（季频数据，7天缓存安全）


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


def _load_holdings_cache() -> dict:
    """加载持仓反查缓存。返回 {stock_code: {holders: [...], cached_at: timestamp}}。"""
    if not HOLDINGS_CACHE_PATH.exists():
        return {}
    try:
        with open(HOLDINGS_CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_holdings_cache(cache: dict) -> None:
    """保存持仓反查缓存。"""
    try:
        HOLDINGS_CACHE_PATH.write_text(
            json.dumps(cache, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
    except Exception as e:
        print(f"  [holdings] ⚠ 缓存保存失败: {e}")


def _fetch_stock_holders(symbol: str, cache: dict) -> list[dict]:
    """查持有指定股票的基金（含ETF），带7天缓存。

    返回 [{fund_code, fund_name, hold_pct, report_date}, ...]
    缓存命中直接返回；未命中调 ak.stock_fund_stock_holder 并缓存结果。
    "No tables found" 是永久错误（无基金持仓数据），不重试直接返空。
    其他异常（网络超时等）重试1次。
    """
    cached = cache.get(symbol)
    if cached and isinstance(cached, dict):
        cached_at = cached.get("cached_at", 0)
        if time.time() - cached_at < HOLDINGS_CACHE_TTL:
            return cached.get("holders", [])

    holders: list[dict] = []
    for attempt in range(2):  # 重试1次
        try:
            df = ak.stock_fund_stock_holder(symbol=symbol)
            if df is None or len(df) == 0:
                break
            for _, row in df.iterrows():
                fund_code = str(row.get("基金代码", "")).zfill(6)
                if not fund_code or fund_code == "000000":
                    continue
                fund_name = str(row.get("基金名称", ""))
                try:
                    hold_pct = float(row.get("占净值比例", 0))
                except (TypeError, ValueError):
                    hold_pct = 0.0
                report_date = str(row.get("截止日期", ""))
                holders.append({
                    "fund_code": fund_code,
                    "fund_name": fund_name,
                    "hold_pct": hold_pct,
                    "report_date": report_date,
                })
            break
        except Exception as e:
            # "No tables found" = 无基金持仓数据（永久错误），不重试
            if "No tables found" in str(e):
                break
            if attempt == 0:
                time.sleep(1)
                continue
            print(f"    [holdings] ⚠ {symbol} 反查失败: {e}")

    cache[symbol] = {"cached_at": time.time(), "holders": holders}
    return holders


def match_holdings_overlap(
    thsc_ids: list[str],
    df_by_code: dict,
    track_idx_map: dict[str, dict] | None = None,
) -> dict[str, list[dict]]:
    """第4层：ETF持仓重叠匹配。

    对指定 thsc 概念，通过 ak.stock_fund_stock_holder 反向查找持有概念成分股的ETF。
    绕过 INDEX_POOL 限制，直接发现持有概念股的ETF（如量子科技 -> 央企科技/通信ETF）。

    算法：
      1. 采概念成分股（复用 fetch_concept_cons）
      2. 每只成分股调 ak.stock_fund_stock_holder 反查持有它的基金
      3. 过滤ETF代码（51/15/56/58开头为场内ETF）+ 排除跨境/债券等非主题ETF
      4. 按ETF聚合 overlap_count(持有几只概念股) + max_hold_pct(最高持仓占比)
      5. MIN_OVERLAP>=2 过滤（至少持有2只概念股）
      6. 综合分 = max_hold_pct * overlap_count 降序排（兼顾集中度和广度）
      7. track_idx_map 去重：同 track_index_name 只保留综合分最高的（防3只电信ETF占3席）

    参数:
      thsc_ids: 需要跑第4层的概念ID列表（1-3层<3只ETF的概念）
      df_by_code: {etf_code: row}（build_board_etf_map.py 预计算，用于取 ETF 名称/成交额）
      track_idx_map: {etf_code: {track_index, ...}}（fundf10 缓存，用于按跟踪指数去重；None 跳过去重）

    返回:
      {thsc_id: [{code, name, amount, approx, overlap_count, max_hold_pct, match_method}]}
    """
    if not thsc_ids:
        return {}

    t0 = time.time()
    cache = _load_holdings_cache()
    cache_new = 0

    result: dict[str, list[dict]] = {}

    for thsc_id in thsc_ids:
        info = CONCEPT_BK_MAP.get(thsc_id)
        if not info:
            result[thsc_id] = []
            continue

        bk_code = info["bk"]
        concept_name = info["name"]

        # Step 1: 采概念成分股
        concept_stocks = fetch_concept_cons(bk_code)
        if not concept_stocks:
            print(f"    [holdings] {thsc_id} {concept_name}: 无成分股,跳过")
            result[thsc_id] = []
            continue

        print(f"    [holdings] {thsc_id} {concept_name}: {len(concept_stocks)}只成分股, 开始反查持仓ETF")

        # Step 2: 每只成分股反查持仓，聚合ETF
        # etf_agg: {etf_code -> {overlap_count, max_hold_pct, fund_name}}
        etf_agg: dict[str, dict] = {}
        sorted_stocks = sorted(concept_stocks)
        for i, stock_code in enumerate(sorted_stocks):
            # 缓存命中计数
            was_cached = stock_code in cache and isinstance(cache[stock_code], dict) \
                and time.time() - cache[stock_code].get("cached_at", 0) < HOLDINGS_CACHE_TTL
            if not was_cached:
                cache_new += 1

            holders = _fetch_stock_holders(stock_code, cache)
            if not holders:
                continue

            # 同一stock内按fund_code去重，取max hold_pct
            # （API可能返回多行同ETF，如不同披露期/份额类别）
            stock_etf_best: dict[str, tuple[float, str]] = {}  # code -> (hold_pct, name)
            for h in holders:
                fc = h["fund_code"]
                # 过滤ETF代码（51/15/56/58开头为场内ETF）
                if not (fc.startswith("51") or fc.startswith("15")
                        or fc.startswith("56") or fc.startswith("58")):
                    continue
                # 排除非行业主题ETF（跨境/债券/商品等）
                fn = h["fund_name"]
                if any(ex in fn for ex in EXCLUDE):
                    continue
                hp = h["hold_pct"]
                if fc not in stock_etf_best or hp > stock_etf_best[fc][0]:
                    stock_etf_best[fc] = (hp, fn)

            # 聚合到全局ETF统计
            for fc, (hp, fn) in stock_etf_best.items():
                if fc not in etf_agg:
                    # ETF名称优先用 df_by_code 实时值
                    r = df_by_code.get(fc) if df_by_code else None
                    if r is not None:
                        try:
                            etf_name = str(r["名称"])
                        except (KeyError, TypeError):
                            etf_name = fn
                    else:
                        etf_name = fn
                    etf_agg[fc] = {
                        "overlap_count": 0,
                        "max_hold_pct": 0.0,
                        "fund_name": etf_name,
                    }
                etf_agg[fc]["overlap_count"] += 1
                if hp > etf_agg[fc]["max_hold_pct"]:
                    etf_agg[fc]["max_hold_pct"] = hp

            if (i + 1) % 10 == 0:
                print(f"      ... {i+1}/{len(sorted_stocks)} stocks processed")

            time.sleep(0.2)  # 限流防封

        # Step 3: MIN_OVERLAP>=2 过滤 + 降序排
        # 综合分 = max_hold_pct * overlap_count（兼顾持仓集中度和持仓广度，
        # 避免"中证1000 overlap=25 但 pct=0.3%"宽基ETF压过"央企科技 overlap=10 pct=9.59%"主题ETF）
        etf_list = [
            (code, v) for code, v in etf_agg.items()
            if v["overlap_count"] >= MIN_OVERLAP_HOLDINGS
        ]
        etf_list.sort(
            key=lambda x: x[1]["max_hold_pct"] * x[1]["overlap_count"],
            reverse=True,
        )

        # Step 3b: track_index 去重（同跟踪指数只保留综合分最高的）
        # 防"3只电信主题ETF占3席"挤压其他主题ETF（大数据/央企科技/通信设备等）
        seen_track_idx: set[str] = set()
        etf_deduped: list[tuple[str, dict]] = []
        for code, v in etf_list:
            tin = ""
            if track_idx_map:
                ti_info = track_idx_map.get(code)
                if ti_info:
                    tin = ti_info.get("track_index", "") or ""
            if tin and tin in seen_track_idx:
                continue  # 同 track_index 已有更高分ETF，跳过
            if tin:
                seen_track_idx.add(tin)
            etf_deduped.append((code, v))

        # Step 4: 构建返回条目（Top-N）
        etfs = []
        for code, v in etf_deduped[:TOP_N_HOLDINGS_ETFS]:
            r = df_by_code.get(code) if df_by_code else None
            if r is not None:
                try:
                    rname = str(r["名称"])
                    amount = round(float(r["成交额"]) / 1e8, 2)
                except (TypeError, ValueError, KeyError):
                    rname = v["fund_name"]
                    amount = 0.0
            else:
                rname = v["fund_name"]
                amount = 0.0
            # track_index_name 从 track_idx_map 取（若有）
            tin = ""
            if track_idx_map:
                ti_info = track_idx_map.get(code)
                if ti_info:
                    tin = ti_info.get("track_index", "") or ""
            entry = {
                "code": code,
                "name": rname,
                "amount": amount,
                "approx": True,  # 持仓重叠匹配，approx=true
                "overlap_count": v["overlap_count"],
                "max_hold_pct": round(v["max_hold_pct"], 4),
                "match_method": "holdings_overlap",
            }
            if tin:
                entry["track_index_name"] = tin
            etfs.append(entry)

        result[thsc_id] = etfs
        top_str = ", ".join(
            f"{e['code']}({e['name']},n={e['overlap_count']},pct={e['max_hold_pct']}%)"
            for e in etfs[:3]
        )
        print(f"    [holdings] {thsc_id} {concept_name}: {len(etfs)}只ETF -> {top_str}")

        # 每概念完成后保存缓存（防中途 kill 丢失已采集数据）
        if cache_new > 0:
            _save_holdings_cache(cache)

    # 最终缓存统计
    if cache_new > 0:
        print(f"  [holdings] 缓存更新: {cache_new} 只股票新采集, 共 {len(cache)} 只缓存")

    dt = time.time() - t0
    n_nonempty = sum(1 for v in result.values() if v)
    print(f"  [holdings] 完成: {n_nonempty}/{len(result)} 概念非空, 耗时 {dt:.1f}s")
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
