#!/usr/bin/env python3
"""基笔唯一化三表 -> 原 quadrants 无损还原对账(L42 数据瘦身步1 附产工具, 2026-09-20)。

用法:
  python3 scripts/check_kelly_unique_restore.py \
      --unique  static-site/data/signal_kelly_trades_unique.json \
      --trades  static-site/data/signal_kelly_trades.json

做两路独立对账(§5.4⑦ 同构对账铁律):
  A) 集合等价: 三表重建的 {(qk, mode, base_key)} 键集 == 原 quadrants 键集, 零缺零多。
  B) 值逐位:   遍历原 quadrants 每行(按原行序), base_key 索引三表还原 27 列, 与原行逐位比对。
部分一致即 FAIL(退出码 1)。schema 与字段划分实证见
docs/kelly/analysis/kelly-unique-schema-20260920.md。
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from signal_kelly_backtest import TRADE_FIELDS  # noqa: E402  # 单一事实源, 防列序漂移


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def base_key(row27, key_idx):
    return tuple(row27[i] for i in key_idx)


def build_rebuilt(u):
    """从三表重建 {qk: {mode: [row27,...]}}。"""
    import collections
    share_fields = u["fields"]
    qk_groups = u["qk_groups"]
    key_fields = u["base_key_fields"]
    fIdx = {f: i for i, f in enumerate(TRADE_FIELDS)}
    share_tf_idx = [fIdx[f] for f in share_fields]
    key_idx = [fIdx[f] for f in key_fields]
    n_share = len(share_fields)

    rebuilt = collections.defaultdict(dict)
    for i, brow in enumerate(u["base"]):
        share_vals = brow[:n_share]
        attr = brow[n_share:]  # 4 枚举码, 顺序 = qk_groups 键序
        for m in u["modes"]:
            vrow = u["variants"][m][i]
            if vrow is None:
                continue  # 该基笔该 mode 无有效回测(None 哨兵, 当前数据全覆盖)
            # 按 TRADE_FIELDS 原列序拼回 27 列: 共享字段按序取 share_vals, 卖出字段按序取 vrow
            row27 = []
            sh_j = sv_j = 0
            for fi in range(len(TRADE_FIELDS)):
                if fi in share_tf_idx:
                    row27.append(share_vals[sh_j]); sh_j += 1
                else:
                    row27.append(vrow[sv_j]); sv_j += 1
            for gi, g in enumerate(qk_groups):
                code = attr[gi]
                if code < 0:
                    continue
                qk = qk_groups[g][code]
                rebuilt[qk].setdefault(m, []).append(row27)
    return rebuilt, key_idx


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--unique", required=True, help="唯一化三表 JSON")
    ap.add_argument("--trades", required=True, help="原 trades JSON(对账基准)")
    args = ap.parse_args()

    u = load(args.unique)
    o = load(args.trades)
    rebuilt, key_idx = build_rebuilt(u)

    # A) 键集等价
    orig_set = set()
    for qk, mk in o["quadrants"].items():
        for m, rows in mk.items():
            for r in rows:
                orig_set.add((qk, m, base_key(r, key_idx)))
    reb_set = set()
    for qk, mk in rebuilt.items():
        for m, rows in mk.items():
            for r in rows:
                reb_set.add((qk, m, base_key(r, key_idx)))
    only_orig = orig_set - reb_set
    only_reb = reb_set - orig_set
    print(f"A) 键集: 原={len(orig_set)} 三表重建={len(reb_set)} "
          f"原独有={len(only_orig)} 重建独有={len(only_reb)} "
          f"-> {'PASS' if not only_orig and not only_reb else 'FAIL'}")
    a_ok = not only_orig and not only_reb

    # B) 值逐位(索引法, 按原行序)
    reb_index = {}
    for qk, mk in rebuilt.items():
        for m, rows in mk.items():
            for r in rows:
                reb_index[(qk, m, base_key(r, key_idx))] = r
    mismatch = missing = checked = 0
    for qk, mk in o["quadrants"].items():
        for m, rows in mk.items():
            for r in rows:
                checked += 1
                rb = reb_index.get((qk, m, base_key(r, key_idx)))
                if rb is None:
                    missing += 1
                    continue
                if rb != r:
                    mismatch += 1
                    if mismatch <= 3:
                        diffs = [TRADE_FIELDS[i] for i in range(len(TRADE_FIELDS)) if rb[i] != r[i]]
                        print(f"  值不一致 {qk} {m} {base_key(r, key_idx)}: diff={diffs}")
    b_ok = mismatch == 0 and missing == 0 and checked == len(orig_set)
    print(f"B) 值逐位: 对比 {checked} 行, 缺失 {missing}, 值不一致 {mismatch} -> {'PASS' if b_ok else 'FAIL'}")

    orig_n = sum(len(rows) for qk in o["quadrants"] for rows in o["quadrants"][qk].values())
    reb_n = sum(len(rows) for qk in rebuilt for rows in rebuilt[qk].values())
    c_ok = orig_n == reb_n
    print(f"C) 总行数: 原={orig_n} 重建={reb_n} -> {'PASS' if c_ok else 'FAIL'}")

    print(f"\n{u['n_base']} 基笔 × {len(u['modes'])} mode; variants 每 mode 长度="
          f"{ {m: len(v) for m, v in u['variants'].items()} }")
    if a_ok and b_ok and c_ok:
        print("RESULT: ALL PASS")
        return 0
    print("RESULT: FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(main())