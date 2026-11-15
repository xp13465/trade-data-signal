# -*- coding: utf-8 -*-
"""增量同步辅助: 行哈希计算 + 新旧哈希 diff + UPSERT 冲突子句构造。

背景(2026-11-08, fund_score/fund_screener D1 增量同步 H1 保守口径):
  旧做法「DELETE FROM <表>; INSERT 全表」每次同步都清空线上表再重插 —— 同步期间
  worker 查到的是空/半成品表, 且写量 = 全表(~28k 行)。改为增量:
    1. 本地为每行算 row_hash(全列含日期列, H1 保守 → 任一列变都触发 changed)
    2. 读 D1 现存 {fund_code: row_hash}
    3. diff: changed(双方都有但哈希变)/ new(本地有 D1 无)/ removed(D1 有本地无)/ unchanged(跳过)
    4. 只 upsert changed+new, 批量 DELETE removed → D1 表全程不被清空, 写量 ≈ 变化行数

本模块只做纯计算(哈希/diff/SQL 片段), 不连 D1、不调 wrangler, 可无副作用单测。
wrangler 读 D1 哈希由调用方(bash 脚本)完成并落 JSON, 本模块读 JSON 即可。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def cell_repr(v) -> str:
    """哈希用的稳定序列化: None -> ''(空串), 其余 str(v)。

    用空串而非 'None' 的原因: NULL 在 D1 与本地语义一致, 不应因 None 文本不同而误判 changed;
    且 'None' 与真实字符串 'None' 会撞哈希。空串无歧义。
    """
    return "" if v is None else str(v)


def compute_row_hash(row: dict, cols: list[str]) -> str:
    """sha256("|".join(cell_repr(row[c]) for c in cols))[:16] —— H1 全列含日期列。

    cols 必须是 row 的全部数据列(不含 row_hash 自身)。fund_code 也计入哈希(常量, 不影响
    变化判定, 但让哈希与行内容完全对应, 防两张表 fund_code 错位时哈希仍相等)。
    """
    payload = "|".join(cell_repr(row.get(c)) for c in cols).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def diff_hashes(local_rows: list[dict], d1_hashes: dict, key_col: str = "fund_code"
                ) -> tuple[list[dict], list[dict], list[str], int]:
    """对比本地行(D1 待写入)与 D1 现存哈希, 返回 (changed, new, removed_codes, unchanged)。

    local_rows : 本地待同步全量行(每行 dict, 含 key_col 与所有数据列)
    d1_hashes  : D1 现存 {fund_code: row_hash}
    key_col    : 主键列名(默认 fund_code)

    返回:
      changed        : 本地有且 D1 有但哈希变了的行(待 upsert)
      new            : 本地有但 D1 没有的行(待 upsert)
      removed_codes  : D1 有但本地没有的 fund_code 列表(待 DELETE)
      unchanged      : 双方都有且哈希相同的行数(跳过, 不写)
    """
    changed, new, unchanged = [], [], 0
    local_codes = set()
    for r in local_rows:
        code = r.get(key_col)
        if code is None:
            continue  # 主键缺失不应发生, 跳过防 KeyError
        local_codes.add(code)
        h = d1_hashes.get(code)
        if h is None:
            new.append(r)
        elif r.get("row_hash") == h:
            unchanged += 1
        else:
            changed.append(r)
    removed_codes = [c for c in d1_hashes if c not in local_codes]
    return changed, new, removed_codes, unchanged


def build_conflict_clause(table: str, set_cols: list[str], key_col: str = "fund_code") -> str:
    """构造 `ON CONFLICT(<key>) DO UPDATE SET c1=excluded.c1, ..., row_hash=excluded.row_hash`。

    set_cols : SET 子句要更新的列(不含 key_col, 含 row_hash)。增量 upsert 时 = 全部数据列 + row_hash。
    """
    assigns = ", ".join(f"{c}=excluded.{c}" for c in set_cols)
    return f"ON CONFLICT({key_col}) DO UPDATE SET {assigns}"


class RoutingMetadataMissing(ValueError):
    """D1 哈希源里缺路由所需的索引列旧值(旧扁平格式 / 该列没读回来)。"""


def _same(old, new) -> bool:
    """NULL 安全相等 —— 与 SQLite `IS` 逐点对应(路由判定必须与三条 WHERE 同语义)。

    · 双方 None ⇒ 相等; 单边 None ⇒ 不等(SQL 里 NULL IS 5 为假)
    · 数字按数值比(80 与 80.0 相等; REAL 列整数值从 D1 JSON 回来可能是 int)
    · 其余(字符串等)按 ==
    判错方向会漏写: 判"相等"但 SQL 判不等 ⇒ 该行既不进 A/B(谓词假)也不进 C(谓词假)。
    """
    if old is None or new is None:
        return old is None and new is None
    if isinstance(old, (int, float)) and isinstance(new, (int, float)):
        return float(old) == float(new)
    return old == new


def load_d1_rows(path_or_obj) -> dict:
    """读 D1 现存行为 {fund_code: {"row_hash": h, <额外列>: 旧值, ...}}。

    支持的来源形态:
      · 嵌套 dict  {"code": {"row_hash": "h", "composite_score": 61.0, ...}}  ← 生产/新版模拟
      · 扁平 dict  {"code": "h"}                                            ← 旧格式(兼容)
      · wrangler --json 的 results 列表 [{fund_code, row_hash, ...}, ...]     ← 兼容
    文件不存在 / 坏 JSON → {}(视 D1 为空表, 全按新增)。
    """
    if isinstance(path_or_obj, dict):
        data = path_or_obj
    else:
        p = Path(path_or_obj)
        if not p.exists():
            return {}
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    if isinstance(data, list):
        return {r["fund_code"]: {k: v for k, v in r.items() if k != "fund_code"}
                for r in data if r.get("fund_code")}
    if not isinstance(data, dict):
        return {}
    rows = {}
    for code, val in data.items():
        if isinstance(val, dict):
            rows[code] = dict(val)
        else:
            rows[code] = {"row_hash": val}   # 旧扁平格式: 只有哈希, 无路由列
    return rows


def load_d1_hashes(path_or_obj) -> dict:
    """从 JSON 文件路径 / 已读 dict 读 D1 现存 {fund_code: row_hash}。空/坏 → {}。"""
    return {c: v.get("row_hash") for c, v in load_d1_rows(path_or_obj).items()}


def split_present_new(new_rows: list[dict], d1_rows: dict) -> tuple[list[dict], list[dict]]:
    """把 diff 的 new(哈希缺失)拆成 (D1 里其实已存在的行, 真·新增行)。

    row_hash 列是 2026-11-08 才补的, 迁移后存量行 row_hash 为 NULL ⇒ diff 把「行已在
    D1、只是哈希没写」也归进 new。这些行在 D1 有旧值可读 ⇒ 必须和 changed 一样按旧值路由,
    否则冲突时若只落到某一条语句, 可能因该语句 WHERE 为假而写不全。
    """
    present = [r for r in new_rows if r.get("fund_code") in d1_rows]
    absent = [r for r in new_rows if r.get("fund_code") not in d1_rows]
    return present, absent


def route_rows(rows: list[dict], d1_rows: dict, secondary_index_cols=(),
               composite_col: str = "composite_score") -> dict:
    """客户端路由: 按「D1 旧值 vs 本地新值」把每条行分进 A/B/C 三类中的**一类**。

    规则(与两个同步脚本三条互斥 WHERE 严格对应):
      · secondary 索引列(fund_type/scale)有变 ⇒ "full"(B, 全列 SET)
      · 否则 composite_score 变               ⇒ "composite"(A, 非索引列 + composite)
      · 否则                                  ⇒ "nonindex"(C, 仅非索引列)

    为什么要客户端先判: 旧实现把每条 changed 行**同时**灌进三条语句, 靠 WHERE 互斥保证只
    写一次 —— 落库对, 但 SQL 包体 = 每行三份(+50%), 撞 30 分钟墙。每行只生成一条语句后
    包体回到「每行一份」, 写行数(rowsWritten)与三条互斥版完全相同。

    返回 {"composite": [...], "full": [...], "nonindex": [...]}。路由列缺失 ⇒
    RoutingMetadataMissing(宁可报错也不猜: 猜错会让该行永远写不进去)。
    """
    buckets = {"composite": [], "full": [], "nonindex": []}
    required = (composite_col,) + tuple(secondary_index_cols)
    for r in rows:
        code = r.get("fund_code")
        old = d1_rows.get(code)
        if not isinstance(old, dict) or any(c not in old for c in required):
            raise RoutingMetadataMissing(
                "D1 哈希源缺路由列(需要 %s; 行 %r 的旧值=%r)。生产由 d1_read_hashes 带"
                "额外列自动产出嵌套格式; DRY_RUN 的 D1_EXISTING_HASHES_FILE 也必须是"
                " {code: {row_hash, %s}}。" % (", ".join(required), code, old,
                                               ", ".join(required)))
        if any(not _same(old[c], r.get(c)) for c in secondary_index_cols):
            buckets["full"].append(r)
        elif not _same(old[composite_col], r.get(composite_col)):
            buckets["composite"].append(r)
        else:
            buckets["nonindex"].append(r)
    return buckets
