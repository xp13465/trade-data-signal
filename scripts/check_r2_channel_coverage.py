#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#193 (2026-10-05) R2 通道覆盖机检 —— 「上传命令产出的前缀」与「对账通道清单」双向对齐。

背景(§22 数据一致性铁律「代码内常量登记点也是一致性对象」):
  upload_r2.py 里同一事实(R2 前缀集合)存在两处独立登记点, 二者漏配 = 静默缺口:
    ① 上传侧: 各 cmd_upload_*/_upload_glob/_incremental_upload 实参写出的 r2_prefix(真正 PUT 到 R2 的前缀);
    ② 对账侧: _R2_CHANNELS 清单(verify-r2 平日/周日实际会对账的前缀)。
  #193 事故形态: offshore_fund / fund_score 只在①存在、②漏登记 ⇒ 连周日全量都不对账(静默)。
  本机检把这条漏配变成可执行断言, 防同族静默复发(§23.2 根因修: 不是逐文件补刀, 而是加结构性检查)。

两类断言:
  [1] 产出侧全覆盖: 上传命令写出的每个前缀, 必须被 ≥1 个通道前缀覆盖(相等或为其子前缀),
      或在白名单 _EXEMPT_PREFIXES 内(附理由); 否则 FAIL。
  [2] 通道侧有来源: 每个通道前缀必须被 ≥1 个上传命令前缀覆盖(相等或为子前缀),
      否则 = 孤儿通道(对账永远对不上任何东西) FAIL。

实现: 纯 AST 静态分析(不 import upload_r2 —— 免 .env / 免任何副作用), 读 scripts/upload_r2.py。
用法: python3 scripts/check_r2_channel_coverage.py            (默认检查同目录 upload_r2.py)
      python3 scripts/check_r2_channel_coverage.py <路径>    (检查指定文件 — 可喂历史版本做回归对照,
                                                              如 git show HEAD:scripts/upload_r2.py > /tmp/old.py)
"""
import ast
import sys
from pathlib import Path

SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent / "upload_r2.py"

# 产出前缀但不属「站点公开数据桶对账」范畴的白名单(私桶备份/运维件), 附理由。
# 新增此处条目 = 显式声明「该前缀故意不进对账」, 防未来静默漏配。
_EXEMPT_PREFIXES = {
    "backup": "私有桶 signal-backup2 的 DB 日备份(独立桶/独立生命周期, 非站点数据桶)",
    "weekly": "私有桶 DB 周备份副本(同上)",
    "monthly": "私有桶 DB 月备份副本(同上)",
    "decommissioned": "私有桶退役归档(长期留存, 非站点数据桶)",
    "claude-backup": "私有桶 Claude 自备份 tar.gz(运维备份, 非站点数据桶)",
    "large-json": "私有桶 staticdata 大 JSON 备份(自带 manifest/恢复脚本, 独立校验链)",
}

_HELPERS = {"_upload_glob", "_incremental_upload"}


def _const_str(node):
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def parse_producer_prefixes(tree):
    """返回 {(prefix, func_name, lineno)}: 所有 _upload_glob/_incremental_upload 调用写出的前缀。"""
    out = set()
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        fname = getattr(n.func, "id", None) or getattr(n.func, "attr", None)
        if fname not in _HELPERS:
            continue
        pfx = None
        for kw in n.keywords:
            if kw.arg == "r2_prefix":
                pfx = _const_str(kw.value)
        if pfx is None and len(n.args) >= 3:
            pfx = _const_str(n.args[2])
        if pfx:
            out.add((pfx, fname, n.lineno))
    return out


def parse_channel_prefixes(tree):
    """返回 [(label, r2_prefix, lineno)]: _R2_CHANNELS 字面量里的每项(只取字符串常量字段)。

    值的 local_dir 是 lambda(非常量) 无所谓 —— 本机检只需 label / r2_prefix / state_name 这些字符串登记点。
    """
    for n in ast.walk(tree):
        if not isinstance(n, ast.Assign):
            continue
        tgts = [t.id for t in n.targets if isinstance(t, ast.Name)]
        if "_R2_CHANNELS" not in tgts or not isinstance(n.value, ast.List):
            continue
        out = []
        for elt in n.value.elts:
            if not isinstance(elt, ast.Dict):
                continue
            d = {}
            for k, v in zip(elt.keys, elt.values):
                kk = _const_str(k)
                if kk in ("label", "r2_prefix", "state_name"):
                    d[kk] = _const_str(v)  # 非常量(如 lambda 的结果)记 None
            out.append((d.get("label"), d.get("r2_prefix"), getattr(elt, "lineno", 0)))
        return out
    return []


def _covers(cover_prefix, target):
    """cover_prefix 是否覆盖 target(相等, 或 target 在其下 = 子前缀)。"""
    return target == cover_prefix or target.startswith(cover_prefix + "/")


def main():
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    producers = parse_producer_prefixes(tree)
    channels = parse_channel_prefixes(tree)

    prod_prefixes = sorted({p for p, _, _ in producers})
    chan_prefixes = sorted({p for _, p, _ in channels if p})

    fails, warns = [], []

    # [1] 产出侧全覆盖
    print("== [1] 产出侧全覆盖(上传命令写出的每个前缀都能被对账) ==")
    for pfx in prod_prefixes:
        if pfx in _EXEMPT_PREFIXES:
            print(f"  豁免 {pfx:<14} — {_EXEMPT_PREFIXES[pfx]}")
            continue
        if any(_covers(c, pfx) for c in chan_prefixes):
            hit = sorted(c for c in chan_prefixes if _covers(c, pfx))
            print(f"  PASS {pfx:<14} 被通道 {hit} 覆盖")
        else:
            sites = ", ".join(f"{f}:L{ln}" for p, f, ln in sorted(producers) if p == pfx)
            fails.append(f"产出前缀 {pfx!r} 无任何通道覆盖(命令 {sites}) ⇒ 静默缺口(#193 同族)")
            print(f"  FAIL {pfx:<14} 无通道覆盖(命令 {sites})")

    # [2] 通道侧有来源(孤儿通道检测)
    print("== [2] 通道侧有来源(无孤儿通道) ==")
    for ch in chan_prefixes:
        if any(_covers(p, ch) for p in prod_prefixes):
            print(f"  PASS {ch:<32} 有上传命令产出")
        else:
            # 允许: 通道前缀是某个产出前缀的子前缀(如 data/news_digest ⊂ data), 已在上式覆盖。
            fails.append(f"通道前缀 {ch!r} 无任何上传命令产出(孤儿通道) ⟺ 对账永远对不上东西")
            print(f"  FAIL {ch:<32} 无上传命令产出")

    # [3] 结构卫生(信息性, 不 FAIL; 重复 label 会让日志/告警混淆)
    labels = [l for l, _, _ in channels]
    dup = sorted({l for l in labels if l and labels.count(l) > 1})
    if dup:
        warns.append(f"重复通道 label: {dup}(日志/告警可能混淆)")
    print(f"== [3] 统计 ==  产出前缀 {len(prod_prefixes)} 个 / 通道 {len(channels)} 个 / 豁免 {len(_EXEMPT_PREFIXES)} 个")

    if warns:
        for w in warns:
            print(f"  WARN {w}")
    if fails:
        print(f"\nHAS_FAIL({len(fails)})")
        for f in fails:
            print(f"  ✗ {f}")
        return 1
    print("\nALL_PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())