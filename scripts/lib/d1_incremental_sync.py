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


def load_d1_hashes(path_or_obj) -> dict:
    """从 JSON 文件路径 / 已读 dict 读 D1 现存哈希。文件不存在或空 → {}(视 D1 为空表)。"""
    if isinstance(path_or_obj, dict):
        return dict(path_or_obj)
    p = Path(path_or_obj)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if isinstance(data, dict):
        return data
    if isinstance(data, list):
        # wrangler --json 的 results 形如 [{"fund_code": "X", "row_hash": "abc"}, ...]
        return {r["fund_code"]: r.get("row_hash") for r in data if r.get("fund_code")}
    return {}
