#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ETF 实时行情多源获取：东财主源 + 新浪/腾讯兜底 + 腾讯全量兜底(2026-09-24 新浪/腾讯兜底,
2026-11-13 加第三级腾讯全量)。

背景：东财 push2/push2delay/push2his 行情子域按域特征封禁(本机+云上双地实测 HTTP 000,
akshare fund_etf_spot_em() 直挂 → board_etf_map 连续断档)。本模块提供统一入口：
主源(东财)成功走原路径行为不变；仅主源失败时逐级启用兜底。

兜底链路三级(逐级降级,每级失败都打印告警,绝不静默)：
  1. 新浪行情中心 Market_Center.getHQNodeData(node=etf_hq_fund+lof_hq_fund) 拉全量代码/行情
     (2026-09-24 实测 2045 只; 2026-11-13 实测节点缩水 etf=938/lof=391, 938<1500 被自家
     防截断下限拒用 → 引出第 3 级)
     - amount(成交额)单位=元, ticktime 为当日时点
     - 差异：东财另有 29 只 519/580 段场外基金(无实时行情,amount=0,不参与有效匹配)，新浪无对应行情
  2. 腾讯 qt.gtimg.cn/q=sh|sz+code 批量补**全称名称**(新浪返回的 name 是深交所简称,如"创业板TF"
     而非"创业板ETF南方"，会导致名称关键词匹配全断——已实测腾讯返回全称,批量 500 只 0.3s 稳定)
     - 前缀映射 code[0]=='5'→sh，code[0] in '1234'→sz
  3. 腾讯全量兜底(2026-11-13 双源全挂 40h 后新增): static-site/data/etf/{code}-all.json
     universe 底盘(export_etf_hist.py 产物,云上实测 1745 只,含场内 ETF+LOF) + qt.gtimg.cn
     逐码批量(500/批, 实测 1745/1745 有效/2.1s): 全称=f[1]/最新价=f[3]/成交额(元)=f[35]
     "价/量/额"第三段。三重 fail-closed: universe<1500 拒用/有效行<1500 拒用/覆盖度对账
     (universe 缺失>50)拒用,下限与新浪同值不放宽。
     依据表: /tmp/board-etf-map-fix-report.md(第 0 步云上出口实测, 2026-11-13)。

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
from pathlib import Path
from typing import Dict, Any, List

import akshare as ak
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent

# 本次进程内最后一次 fund_etf_spot_df() 用的源(供 build_board_etf_map 写 _meta.source 标注,
# 纯调试信息字段, 前端/机检不消费, 2026-09-24 核对; 2026-11-13 由 bool 升级为三源枚举)
# 取值: "eastmoney"(东财主源) / "sina_tencent"(新浪全量+腾讯补名) / "tencent_universe"(腾讯全量兜底)
_LAST_SOURCE = "eastmoney"


def was_fallback_used() -> bool:
    """返回最近一次 fund_etf_spot_df() 是否走了兜底(供产物元数据标注,兼容旧消费点)。"""
    return _LAST_SOURCE != "eastmoney"


def last_source() -> str:
    """返回最近一次 fund_etf_spot_df() 实际使用的源名(三源枚举, 2026-11-13)。"""
    return _LAST_SOURCE

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

# ── 第三源: 腾讯全量行情(etf/ universe 底盘, 2026-11-13 双源全挂后新增) ──────────
# 依据(云上出口 122.51.111.173 只读实测 2026-11-13, 全表见 /tmp/board-etf-map-fix-report.md):
# - 东财 fund_etf_spot_em() 仍封禁(RemoteDisconnected, 出口 IP 级, 40h+);
# - 新浪 etf_hq_fund 节点真实总数 938 < 1500 下限(节点缩水 ~45%, 非瞬时截断)→ 兜底失效;
# - 腾讯 qt.gtimg.cn 云上可用: universe 1745 只逐码批量(500/批)实测 1745/1745 有效(2.1s),
#   全称=f[1] / 最新价=f[3] / 成交额(元)=f[35]("价/量/额"第三段, 与东财同为元口径)。
# universe 底盘 = static-site/data/etf/{code}-all.json 文件名(export_etf_hist.py 产物,
# 云上 deploy 树实测 1745 只, 含场内 ETF+LOF)。deploy 内 gen/build 先于 R2/静态站同步执行,
# 该目录在 deploy 树长期在位(由每周全史导出任务刷新)。
_TENCENT_UNIVERSE_DIR = ROOT / "static-site" / "data" / "etf"
# 有效行下限: 与新浪同值同理由(防静默缩水覆盖, 不放宽; 腾讯实测能拉 ~1745)
_TENCENT_UNIVERSE_MIN_ROWS = 1500
# 覆盖度对账: universe 代码中腾讯未返回有效行情的数 > 此值 = 拒用(防批量请求中途被截断)
_TENCENT_UNIVERSE_MAX_MISSING = 50

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


def _tencent_universe_codes() -> List[str]:
    """第三源 universe 底盘: static-site/data/etf/{code}-all.json 文件名集合。

    目录缺失/为空 → 返回空列表(调用方按 fail-closed 拒用, 不静默换源)。
    """
    d = _TENCENT_UNIVERSE_DIR
    if not d.is_dir():
        return []
    return sorted({f.name.split("-")[0] for f in d.glob("*-all.json")
                   if f.name[:1].isdigit() and f.name[6:7] == "-"})


def _tencent_etf_spot_df() -> pd.DataFrame:
    """第三源(2026-11-13 新增): 腾讯全量行情 = etf/ universe 底盘 + qt.gtimg.cn 逐码批量。

    fail-closed(§23.11 绝不静默, 三重下限一个不放宽):
    - universe 底盘不足 1500 只 → 拒用(底盘残缺说明环境异常, 不能基于残缺清单构建);
    - 有效行情行 < 1500 → 拒用(与新浪 1500 下限同值同理由: 防静默缩水覆盖, 实测能拉 ~1745);
    - 覆盖度对账: universe 中无有效行情的代码 > 50 → 拒用(防批量请求中途截断静默漏码)。
    """
    codes = _tencent_universe_codes()
    if len(codes) < _TENCENT_UNIVERSE_MIN_ROWS:
        raise RuntimeError(
            f"腾讯全量源 universe 底盘不足: {_TENCENT_UNIVERSE_DIR} 仅 {len(codes)} 只"
            f"(< {_TENCENT_UNIVERSE_MIN_ROWS}), 疑似 etf/ 全史产物目录缺失/残缺, fail-closed 拒用")
    rows: List[Dict[str, Any]] = []
    for i in range(0, len(codes), _TENCENT_BATCH):
        batch = codes[i:i + _TENCENT_BATCH]
        q = ",".join(_code_prefix(c) for c in batch)
        r = requests.get(_TENCENT_URL + q, timeout=20)
        r.raise_for_status()
        # 返回多行 v_sh510050="..."; GBK 显式解码(同 _tencent_fetch_names)
        text = r.content.decode("gbk", errors="replace")
        for line in text.strip().split(";"):
            line = line.strip()
            if not line.startswith("v_"):
                continue
            m = line.split("=", 1)
            if len(m) != 2:
                continue
            sym = m[0].strip().removeprefix("v_")
            f = m[1].strip().strip('"').split("~")
            # 全称=索引1, 最新价=索引3, 成交额(元)=索引35 "价/量/额" 第三段(2026-11-13 云上实测)
            if len(f) <= 35:
                continue
            name = f[1].strip()
            pva = f[35].split("/")
            if not name or len(pva) < 3:
                continue
            rows.append({"代码": sym[2:], "名称": name, "最新价": pva[0], "成交额": pva[2]})
        time.sleep(0.3)
    if len(rows) < _TENCENT_UNIVERSE_MIN_ROWS:
        raise RuntimeError(
            f"腾讯全量源仅返回 {len(rows)} 只有效行情(< {_TENCENT_UNIVERSE_MIN_ROWS}),"
            f"疑似批量请求中途截断/数据源异常, fail-closed 拒用")
    got = {r["代码"] for r in rows}
    missing = [c for c in codes if c not in got]
    if len(missing) > _TENCENT_UNIVERSE_MAX_MISSING:
        raise RuntimeError(
            f"腾讯全量源覆盖度对账失败: universe {len(codes)} 只中缺 {len(missing)} 只"
            f"(> {_TENCENT_UNIVERSE_MAX_MISSING}), 如 {','.join(missing[:10])}, fail-closed 拒用")
    df = pd.DataFrame(rows)
    amount_num = pd.to_numeric(df["成交额"], errors="coerce")
    n_bad_amount = int(amount_num.isna().sum())
    if n_bad_amount > 50:
        raise RuntimeError(
            f"腾讯全量源成交额解析失败 {n_bad_amount} 只, fail-closed 拒用")
    df["成交额"] = amount_num.fillna(0)
    if "最新价" in df.columns:
        df["最新价"] = pd.to_numeric(df["最新价"], errors="coerce")
    if n_bad_amount:
        print(f"⚠ [etf-fallback] 腾讯全量源成交额解析失败 {n_bad_amount} 只, 回落 0", flush=True)
    return df


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
    """东财主源 + 新浪/腾讯兜底 + 腾讯全量兜底 统一入口。

    - 主源(东财)成功：返回 ak.fund_etf_spot_em() 原样 df，行为完全不变。
    - 主源失败：启用新浪+腾讯兜底(全量+补全称)，失败再启用腾讯全量兜底
      (etf/ universe 底盘 + qt.gtimg.cn 逐码批量, 2026-11-13 双源全挂 40h 后新增)。
    - 每级失败都打印明确告警日志(不静默降级)；全部失败抛聚合异常，
      消息带每个源名/条数/原因(可诊断, 2026-11-13 加固)。
    """
    global _LAST_SOURCE
    try:
        df = ak.fund_etf_spot_em()
        if df is None or df.empty:
            raise ValueError("东财 fund_etf_spot_em() 返回空 DataFrame")
        _LAST_SOURCE = "eastmoney"
        return df
    except Exception as e_main:
        err_main = f"{type(e_main).__name__}: {e_main}"[:200]
        print(f"⚠ [etf-fallback] 东财主源 fund_etf_spot_em() 失败({err_main})，"
              f"启用新浪+腾讯兜底(新浪全量+腾讯全称) ...", flush=True)
        try:
            df = _sina_etf_spot_df()
            _LAST_SOURCE = "sina_tencent"
            print(f"✅ [etf-fallback] 新浪+腾讯兜底成功：{len(df)} 只(代码/名称全称/成交额口径)",
                  flush=True)
            return df
        except Exception as e_fb1:
            err_fb1 = f"{type(e_fb1).__name__}: {e_fb1}"[:200]
            print(f"⚠ [etf-fallback] 新浪+腾讯兜底失败({err_fb1})，"
                  f"启用腾讯全量兜底(etf/ universe 底盘 + qt.gtimg.cn 逐码批量) ...", flush=True)
            try:
                df = _tencent_etf_spot_df()
                _LAST_SOURCE = "tencent_universe"
                print(f"✅ [etf-fallback] 腾讯全量兜底成功：{len(df)} 只"
                      f"(universe 底盘 + 代码/全称/最新价/成交额口径)", flush=True)
                return df
            except Exception as e_fb2:
                err_fb2 = f"{type(e_fb2).__name__}: {e_fb2}"[:200]
                raise RuntimeError(
                    f"ETF 实时行情三源均失败：东财({err_main})；"
                    f"新浪+腾讯兜底({err_fb1})；腾讯全量兜底({err_fb2})") from e_fb2