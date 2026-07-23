"""交互式自定义分析: 模糊匹配输入 -> 候选标的列表 (docs §9.2)。

匹配源:
- index_daily DISTINCT index_id (9宽基 + 31申万行业 + 港股 + 全球 + 概念)
- data/board_etf_map.json (ETF 代码 + 名称, 按成交额降序)
- config/indicators.yaml 中文名

匹配规则:
- 精确匹配 code/name 优先
- 模糊包含(大小写不敏感)
- 多候选按成交额降序, 不含个股
- 匹配不到返回空列表
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parent.parent
_SENT_DB = _REPO / "data" / "sentiment.db"
_NT_DB = _REPO / "data" / "etf_national_team.db"
_BOARD_ETF_MAP = _REPO / "data" / "board_etf_map.json"

# 9 宽基 + 31 申万一级行业 = 40 个预生成静态快照的标的(§9.6)
BROAD_INDEX_IDS = ["sh", "sz", "sz50", "hs300", "csi500", "csi1000", "cyb", "kc50", "bj50"]
# 申万 31 一级行业(与 industry_extras.SW_EM_MAP 对齐, 顺序同 indicators.yaml)
SW_INDEX_IDS = [
    "sw_801010", "sw_801030", "sw_801040", "sw_801050", "sw_801080", "sw_801880",
    "sw_801110", "sw_801120", "sw_801130", "sw_801140", "sw_801150", "sw_801160",
    "sw_801170", "sw_801180", "sw_801200", "sw_801210", "sw_801780", "sw_801790",
    "sw_801230", "sw_801710", "sw_801720", "sw_801730", "sw_801890", "sw_801740",
    "sw_801750", "sw_801760", "sw_801770", "sw_801950", "sw_801960", "sw_801970",
    "sw_801980",
]
# C7 P4 market 融合: 3 红利 + 3 港股 + 9 全球 = 15 个补充标的(2026-07-20)
DIV_INDEX_IDS = ["csi_div", "div_lowvol", "sz_div"]           # 红利(中证红利/红利低波/深证红利)
HK_INDEX_IDS = ["hsi", "hstech", "hscei"]                     # 港股(恒生/恒生科技/恒生国企)
GLOBAL_INDEX_IDS = [                                          # 全球(美股4+亚太2+欧洲3)
    "us_dji", "us_ixic", "us_spx", "us_ndx",                  # 道琼斯/纳指/标普/纳指100
    "nikkei225", "kospi",                                     # 日经/韩国综
    "ftse100", "dax", "cac40",                                # 富时/DAX/CAC
    "cgb_idx", "cgb_10y_etf", "cgb_10y_future",               # 中国国债(上证国债指数/10年国债ETF/10年国债期货)
]
# P1-新-C: 12 国家队宽基 ETF (与 app.collector.etf_national_team.ETF_LIST 对齐;
# 此处硬编码避免循环 import akshare/requests 等重依赖)
NATIONAL_TEAM_ETF_CODES = [
    "510050", "510300", "510310", "159919",  # 上证50 / 沪深300 ×3
    "510500", "159922",                       # 中证500 ×2
    "512100", "159845",                       # 中证1000 ×2
    "159915", "159952",                       # 创业板 ×2
    "588000", "588050",                       # 科创50 ×2
]
# 预生成静态快照全集 (9 宽基 + 31 申万 + 3 红利 + 3 港股 + 9 全球 + 12 ETF = 67)
PREGEN_TARGETS = (
    [(iid, "index") for iid in
     BROAD_INDEX_IDS + SW_INDEX_IDS + DIV_INDEX_IDS + HK_INDEX_IDS + GLOBAL_INDEX_IDS]
    + [(code, "etf") for code in NATIONAL_TEAM_ETF_CODES]
)


def _load_index_name_map() -> dict[str, str]:
    """从 config/indicators.yaml 读 {index_id: 中文名}。"""
    from .collector.fetchers import load_config
    cfg = load_config()
    out = {}
    for it in cfg.get("indices", []):
        iid = it.get("id")
        name = it.get("name")
        if iid and name:
            out[iid] = name
    return out


def _load_index_amounts() -> dict[str, float]:
    """从 index_daily 取各指数各自最新非零 amount (用于候选排序)。

    注意: 不同指数最新有 amount 的日期可能不同(如 sw_801080 在 20260714 有,
    20260715 后变 0/NULL),故取每个 index_id 自己的最新非零值。
    """
    out = {}
    with sqlite3.connect(_SENT_DB) as c:
        rows = c.execute(
            "SELECT index_id, amount FROM index_daily t1 WHERE amount IS NOT NULL AND amount > 0 "
            "AND date = (SELECT MAX(date) FROM index_daily t2 "
            "            WHERE t2.index_id = t1.index_id AND t2.amount IS NOT NULL AND t2.amount > 0)"
        ).fetchall()
    for iid, amt in rows:
        out[iid] = float(amt)
    return out


def _load_etf_candidates() -> list[dict]:
    """从 board_etf_map.json 读全部 ETF 候选 (含每个 sw/thsc key 下的 ETF)。"""
    if not _BOARD_ETF_MAP.exists():
        return []
    with open(_BOARD_ETF_MAP, encoding="utf-8") as f:
        d = json.load(f)
    out = []
    for key, etfs in d.items():
        if key == "_meta" or not isinstance(etfs, list):
            continue
        for e in etfs:
            code = str(e.get("code", ""))
            name = str(e.get("name", ""))
            amount = float(e.get("amount") or 0)
            if code and name:
                out.append({
                    "code": code, "name": name, "amount": amount,
                    "type": "etf", "parent_key": key,
                })
    # 去重(同 code 可能出现在多个 key 下, 取 amount 最大那条)
    seen = {}
    for e in out:
        c = e["code"]
        if c not in seen or e["amount"] > seen[c]["amount"]:
            seen[c] = e
    return list(seen.values())


def _load_etf_latest_amount() -> dict[str, float]:
    """从 etf_daily 取各 ETF 最新日成交额(元)。"""
    out = {}
    with sqlite3.connect(_NT_DB) as c:
        rows = c.execute(
            "SELECT etf_code, amount FROM etf_daily WHERE date IN ("
            "  SELECT MAX(date) FROM etf_daily) AND amount IS NOT NULL AND amount > 0"
        ).fetchall()
    for code, amt in rows:
        out[code] = float(amt)
    return out


# ---------------------------------------------------------------------------
# 候选构建
# ---------------------------------------------------------------------------
def _all_index_candidates(name_map: dict[str, str],
                          amount_map: dict[str, float]) -> list[dict]:
    """全部指数候选 (含宽基/行业/概念/港股/全球)。"""
    with sqlite3.connect(_SENT_DB) as c:
        rows = c.execute(
            "SELECT DISTINCT index_id FROM index_daily"
        ).fetchall()
    out = []
    for (iid,) in rows:
        name = name_map.get(iid, iid)
        out.append({
            "code": iid, "name": name, "type": "index",
            "amount": amount_map.get(iid),
        })
    return out


def _match_score(query: str, code: str, name: str) -> int:
    """匹配评分: 精确=100, 开头=80, 包含=60, 否则 0。"""
    q = query.strip().lower()
    if not q:
        return 0
    c = code.lower()
    n = name.lower()
    if q == c or q == n:
        return 100
    if c.startswith(q) or n.startswith(q):
        return 80
    if q in c or q in n:
        return 60
    return 0


# 行业关键词 -> 申万一级 index_id (语义补充, §9.2 示例"半导体"->sw_801080)
# 覆盖常见子行业/概念名 -> 申万一级的映射 (与 industry_extras.THS_TO_SW 一致, 简化版)
_KEYWORD_TO_SW = {
    "半导体": "sw_801080", "芯片": "sw_801080", "电子": "sw_801080",
    "消费电子": "sw_801080", "光学光电子": "sw_801080",
    "养殖业": "sw_801010", "农业": "sw_801010", "农林牧渔": "sw_801010",
    "化工": "sw_801030", "化学": "sw_801030",
    "钢铁": "sw_801040",
    "有色": "sw_801050", "金属": "sw_801050",
    "汽车": "sw_801880",
    "家电": "sw_801110",
    "食品": "sw_801120", "饮料": "sw_801120", "白酒": "sw_801120",
    "纺织": "sw_801130", "服装": "sw_801130",
    "轻工": "sw_801140", "家居": "sw_801140",
    "医药": "sw_801150", "医疗": "sw_801150", "生物": "sw_801150",
    "电力": "sw_801160", "公用事业": "sw_801160", "燃气": "sw_801160",
    "交通": "sw_801170", "航运": "sw_801170", "物流": "sw_801170",
    "房地产": "sw_801180", "地产": "sw_801180",
    "商贸": "sw_801200", "零售": "sw_801200",
    "社会服务": "sw_801210", "社服": "sw_801210",
    "银行": "sw_801780",
    "非银": "sw_801790", "证券": "sw_801790", "保险": "sw_801790",
    "建材": "sw_801710", "建筑材料": "sw_801710",
    "建筑": "sw_801720", "装饰": "sw_801720",
    "电力设备": "sw_801730", "新能源": "sw_801730", "光伏": "sw_801730", "锂电": "sw_801730",
    "机械": "sw_801890",
    "军工": "sw_801740", "国防": "sw_801740",
    "计算机": "sw_801750", "软件": "sw_801750",
    "传媒": "sw_801760", "游戏": "sw_801760", "影视": "sw_801760",
    "通信": "sw_801770",
    "煤炭": "sw_801950",
    "石油": "sw_801960", "石化": "sw_801960",
    "环保": "sw_801970",
    "美容": "sw_801980", "化妆品": "sw_801980",
}


def _keyword_match(query: str) -> set[str]:
    """关键词 -> index_id 集合 (query 命中任一关键词)。"""
    q = query.strip()
    if not q:
        return set()
    out = set()
    for kw, iid in _KEYWORD_TO_SW.items():
        if kw in q or q in kw:
            out.add(iid)
    return out


def match_candidates(query: str, limit: int = 20) -> list[dict]:
    """模糊匹配: 输入 -> 候选列表 (按匹配度+成交额降序)。

    Args:
        query: 用户输入 (指数代码/中文名/ETF代码/ETF名/行业名)
        limit: 最多返回条数

    Returns:
        [{code, name, type, amount, score}, ...]
        - code: 指数 id (hs300/sw_801080) 或 ETF 代码 (510300)
        - name: 中文名
        - type: 'index' / 'etf'
        - amount: 最新成交额(指数可能为 None)
        - score: 匹配度 0-100
    """
    query = (query or "").strip()
    if not query:
        return []

    name_map = _load_index_name_map()
    idx_amounts = _load_index_amounts()
    etf_amounts = _load_etf_latest_amount()
    etf_candidates = _load_etf_candidates()

    # 1. 指数候选
    idx_cands = _all_index_candidates(name_map, idx_amounts)
    # 2. ETF 候选(补 etf_daily 最新成交额,单位元; board_etf_map 的 amount 是亿元)
    for e in etf_candidates:
        latest = etf_amounts.get(e["code"])
        if latest is not None:
            e["amount"] = latest  # 元,更实时
        # board_etf_map 的 amount 单位是亿元,转元统一(仅在 etf_daily 缺时用)
        elif e.get("amount"):
            e["amount"] = e["amount"] * 1e8

    all_cands = idx_cands + etf_candidates
    kw_hits = _keyword_match(query)
    scored = []
    for c in all_cands:
        s = _match_score(query, c["code"], c["name"])
        if s == 0 and c.get("type") == "index" and c["code"] in kw_hits:
            s = 60  # 关键词语义匹配 (如"半导体"->sw_801080)
        if s > 0:
            c2 = dict(c)
            c2["score"] = s
            scored.append(c2)

    # 排序: 匹配度降序 -> 成交额降序
    scored.sort(key=lambda x: (x["score"], x.get("amount") or 0), reverse=True)
    return scored[:limit]


if __name__ == "__main__":
    import sys
    q = sys.argv[1] if len(sys.argv) > 1 else "半导体"
    print(f"查询: {q}")
    for c in match_candidates(q):
        print(f"  {c['type']:6s} {c['code']:12s} {c['name']:20s} amount={c.get('amount')} score={c['score']}")
