#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ETF 实时行情多源获取：东财主源 + 新浪/腾讯兜底(2026-09-24 用户拍板"加,仅主源失败时启用")。

背景：东财 push2/push2delay/push2his 行情子域按域特征封禁(本机+云上双地实测 HTTP 000,
akshare fund_etf_spot_em() 直挂 → board_etf_map 连续断档)。本模块提供统一入口：
主源(东财)成功走原路径行为不变；仅主源失败时启用新浪+腾讯兜底。

兜底链路(已实测 2026-09-24)：
  1. 新浪行情中心 Market_Center.getHQNodeData(node=etf_hq_fund+lof_hq_fund) 拉全量代码/行情
     - 覆盖东财 fs=b:MK0021-24 等价集，实测 2045 只(场内ETF 1685 + 场内LOF 360)，8/8 连续调用成功
     - amount(成交额)单位=元(量×价比值 1.00-1.01 实测)，ticktime 为当日时点
     - 差异：东财另有 29 只 519/580 段场外基金(无实时行情,amount=0,不参与有效匹配)，新浪无对应行情
  2. 腾讯 qt.gtimg.cn/q=sh|sz+code 批量补**全称名称**(新浪返回的 name 是深交所简称,如"创业板TF"
     而非"创业板ETF南方"，会导致名称关键词匹配全断——已实测腾讯返回全称,批量 500 只 0.3s 稳定)
     - 前缀映射 code[0]=='5'→sh，code[0] in '1234'→sz

本模块为共享单源，供以下消费点复用(均已核对只消费 代码/名称/成交额 三列)：
  - scripts/build_board_etf_map.py (L1418)
  - scripts/gen_etf_index_map.py (L83)
  - scripts/fetch_etf_track_index.py (L105, 周任务,已接入 2026-09-24)
非消费点(职责不同,未接入,见 docs/ops/board-etf-map-sina-fallback-20260924.md)：
  - scripts/signal_kelly_backtest.py `_fetch_intraday_open_via_http`(单点今开 dict 形态,
    自备新浪主+腾讯备双源,已含兜底,不复用本模块)
  - app/collector/overlap_fetcher.py (仅 __main__ 测试入口用 fund_etf_spot_em,生产路径
    df 由 build_board_etf_map.py 预计算传入)
"""
import time
from typing import Dict, Any, List

import akshare as ak
import pandas as pd
import requests

# 本次进程内最后一次 fund_etf_spot_df() 是否走了兜底(供 build_board_etf_map 写 _meta.source 标注,
# 纯调试信息字段, 前端/机检不消费, 2026-09-24 核对)
_LAST_USED_FALLBACK = False


def was_fallback_used() -> bool:
    """返回最近一次 fund_etf_spot_df() 是否走了新浪+腾讯兜底(供产物元数据标注)。"""
    return _LAST_USED_FALLBACK

_SINA_HEADERS = {
    "Referer": "https://finance.sina.com.cn",
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
}
_SINA_URL = ("https://vip.stock.finance.sina.com.cn/quotes_service/"
             "api/json_v2.php/Market_Center.getHQNodeData")
# 新浪行情中心两个节点：etf_hq_fund=场内ETF，lof_hq_fund=场内LOF(501/502/160-169 深LOF)
_SINA_NODES = ("etf_hq_fund", "lof_hq_fund")
_SINA_PAGE_SIZE = 100
# 各节点条数下限(实测 2026-09-24: etf=1685/lof=360，留 ~10% 余量防误伤)——
# 低于下限 = 翻页中途静默截断/数据源异常，fail-closed 拒用而非静默只返回前 N 页
_SINA_NODE_MIN_ROWS = {"etf_hq_fund": 1500, "lof_hq_fund": 300}

_TENCENT_URL = "https://qt.gtimg.cn/q="
_TENCENT_BATCH = 500

# 新浪行情字段 → 东财 fund_etf_spot_em 列名映射(仅消费点实际用到的三列必映射，trade 附送)
_SINA_MAP = {
    "code": "代码",
    "name": "名称",
    "amount": "成交额",
    "trade": "最新价",
}


def _sina_fetch_node(node: str) -> List[Dict[str, Any]]:
    """拉取新浪行情中心一个节点全量(翻页 num=100)。

    静默截断防护(§23.11 绝不静默)：
    - 空页可能是瞬时抖动 → 重试一次(同页重新请求)；仍空才视为末页。
    - 节点条数低于下限 → fail-closed 抛错(翻页中途某页静默挂掉会只返回前 N 页，
      条数远低于预期，数量下限能兜住"静默只返回前 29 页"这类截断)。
    """
    rows: List[Dict[str, Any]] = []
    page = 1
    while True:
        params = {
            "page": str(page),
            "num": str(_SINA_PAGE_SIZE),
            "sort": "symbol",
            "asc": "1",
            "node": node,
            "symbol": "",
            "_s_r_a": "init",
        }
        data = None
        for attempt in (1, 2):
            r = requests.get(_SINA_URL, params=params, headers=_SINA_HEADERS, timeout=20)
            r.raise_for_status()
            data = r.json()
            if data:
                break
            time.sleep(0.3)
        if not data:
            break
        rows.extend(data)
        if len(data) < _SINA_PAGE_SIZE:
            break
        page += 1
        time.sleep(0.3)
    min_rows = _SINA_NODE_MIN_ROWS.get(node)
    if min_rows is not None and len(rows) < min_rows:
        raise RuntimeError(
            f"新浪节点 {node} 仅返回 {len(rows)} 只(下限 {min_rows})，疑似翻页中途截断/"
            f"数据源异常，fail-closed 拒用")
    return rows


def _code_prefix(code: str) -> str:
    """东财 6 位代码 → 腾讯/新浪带市场前缀代码。"""
    return ("sh" if code[0] == "5" else "sz") + code


def _tencent_fetch_names(codes: List[str]) -> tuple:
    """腾讯批量补齐 ETF 全称名称(新浪 name 是简称,名称关键词匹配必须用全称)。

    腾讯限频风险(memory 记录: 60s 轮询场景 WAF 风控)，低频批量(500只/批,批间 0.3s)实测稳定。
    返回 (names, missing): names={code: 全称}；missing=腾讯未返回/字段缺失的 code 列表
    (调用方负责按缺失集合 fail-closed，本函数只负责如实上报缺失，不静默回落)。
    """
    names: Dict[str, str] = {}
    missing: List[str] = []
    for i in range(0, len(codes), _TENCENT_BATCH):
        batch_codes = codes[i:i + _TENCENT_BATCH]
        q = ",".join(_code_prefix(c) for c in batch_codes)
        r = requests.get(_TENCENT_URL + q, timeout=20)
        r.raise_for_status()
        # 返回多行 v_sh510050="..."; 名称在第 2 个字段(索引1)
        # 显式 GBK 解码，不依赖 charset 响应头(头缺失/被剥离时 r.text 解析会乱码)
        text = r.content.decode("gbk", errors="replace")
        batch_got: set = set()
        for line in text.strip().split(";"):
            line = line.strip()
            if not line.startswith("v_"):
                continue
            m = line.split("=", 1)
            if len(m) != 2:
                continue
            sym = m[0].strip().removeprefix("v_")
            fields = m[1].strip().strip('"').split("~")
            # 全称在索引1；空串/占位(如 v_xxx="shxxx=""")视为缺失,不记录空名
            if len(fields) > 1 and fields[1].strip():
                names[sym[2:]] = fields[1]
                batch_got.add(sym[2:])
        # 本批请求的代码里腾讯没返回的，记入缺失(后续由调用方重试/refail)
        missing.extend(c for c in batch_codes if c not in batch_got)
        time.sleep(0.3)
    return names, missing


def _sina_etf_spot_df() -> pd.DataFrame:
    """新浪+腾讯兜底：新浪拉全量代码/行情 → 腾讯批量补全称，映射列名到东财口径。"""
    all_rows: List[Dict[str, Any]] = []
    for node in _SINA_NODES:
        node_rows = _sina_fetch_node(node)
        all_rows.extend(node_rows)
    if not all_rows:
        raise RuntimeError("新浪行情中心返回空(两节点均无数据)")
    df = pd.DataFrame(all_rows)
    keep = {}
    for sina_col, em_col in _SINA_MAP.items():
        if sina_col in df.columns:
            keep[sina_col] = em_col
    df = df[list(keep.keys())].rename(columns=keep)
    # 成交额解析: 静默回落 0 会污染排序/匹配，超过阈值 fail-closed，少量打日志
    amount_num = pd.to_numeric(df["成交额"], errors="coerce")
    n_bad_amount = int(amount_num.isna().sum())
    if n_bad_amount:
        bad_codes = df.loc[amount_num.isna(), "代码"].astype(str).tolist()
        if n_bad_amount > 50:
            raise RuntimeError(
                f"新浪成交额解析失败 {n_bad_amount} 只(如 {','.join(bad_codes[:5])}...)，"
                f"fail-closed 拒用")
        print(f"⚠ [etf-fallback] 新浪成交额解析失败 {n_bad_amount} 只("
              f"{','.join(bad_codes[:10])}{'...' if len(bad_codes) > 10 else ''})，回落 0", flush=True)
    df["成交额"] = amount_num.fillna(0)
    if "最新价" in df.columns:
        df["最新价"] = pd.to_numeric(df["最新价"], errors="coerce")

    # 全称补齐：新浪 name(简称) → 腾讯全称
    # fail-closed：腾讯返回的代码集合必须 ⊇ 新浪 df 的代码集合（只比对长度不够，长度相等但
    # 代码错位同样会静默带截断名流入匹配链，2026-08-06 空数组事故的变种通道，§23.11 绝不静默）。
    codes = df["代码"].astype(str).tolist()
    full_names, missing = _tencent_fetch_names(codes)
    if missing:
        # 部分缺失多为瞬时抖动：重试一次缺失批次，能救就不整轮 fail
        print(f"⚠ [etf-fallback] 腾讯补全称缺失 {len(missing)} 只({','.join(sorted(missing)[:5])}"
              f"{'...' if len(missing) > 5 else ''})，重试一次缺失批次 ...", flush=True)
        retry_names, retry_missing = _tencent_fetch_names(missing)
        full_names.update(retry_names)
        missing = retry_missing
    if missing:
        raise RuntimeError(
            f"腾讯补全称缺失 {len(missing)} 只代码(重试后仍缺)，fail-closed 拒用，"
            f"缺失代码: {','.join(sorted(missing)[:50])}{'...' if len(missing) > 50 else ''}")
    df["名称"] = df["代码"].astype(str).map(full_names)
    return df


def fund_etf_spot_df() -> pd.DataFrame:
    """东财主源 + 新浪/腾讯兜底统一入口。

    - 主源(东财)成功：返回 ak.fund_etf_spot_em() 原样 df，行为完全不变。
    - 仅主源失败：启用新浪+腾讯兜底，打印明确告警日志(不静默降级)。
    - 两源都失败：抛异常如实报错(上游感知失败)。
    """
    global _LAST_USED_FALLBACK
    try:
        df = ak.fund_etf_spot_em()
        if df is None or df.empty:
            raise ValueError("东财 fund_etf_spot_em() 返回空 DataFrame")
        _LAST_USED_FALLBACK = False
        return df
    except Exception as e_main:
        err_main = f"{type(e_main).__name__}: {e_main}"[:200]
        print(f"⚠ [etf-fallback] 东财主源 fund_etf_spot_em() 失败({err_main})，"
              f"启用新浪+腾讯兜底(新浪全量+腾讯全称) ...", flush=True)
        try:
            df = _sina_etf_spot_df()
            _LAST_USED_FALLBACK = True
            print(f"✅ [etf-fallback] 新浪+腾讯兜底成功：{len(df)} 只(代码/名称全称/成交额口径)",
                  flush=True)
            return df
        except Exception as e_fb:
            err_fb = f"{type(e_fb).__name__}: {e_fb}"[:200]
            raise RuntimeError(
                f"ETF 实时行情两源均失败：东财({err_main})；新浪+腾讯兜底({err_fb})") from e_fb