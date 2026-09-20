#!/usr/bin/env python3
"""分片唯一化三表 -> 原分片 quadrants 无损还原对账(L42 数据瘦身步2 Phase1 附产工具, 2026-09-20)。

用法:
  python3 scripts/check_kelly_unique_parts_restore.py \
      --trades static-site/data/signal_kelly_trades.json
  (sdc 档: --trades static-site/data/signal_kelly_trades_sdc.json)

对每个分片(recent + t{YYYY})做「三表重建 vs 原分片 quadrants」逐位对账(§5.4⑦ 同构对账铁律):
  1. 以 KELLY_UNIQUE_EXPORT=1 调 _export_trades_parts, 在临时目录生成新旧两类分片
     (旧 quadrants 分片 + 新 unique_ 三表分片)。
  2. 对每片: unique_{name} 三表重建 {qk:{mode:[row27]}} == 原 {name} quadrants
     (键集等价 + 值逐位 + 总行数三查)。
任意一片 FAIL 即退出码 1。schema 与还原规则见
docs/kelly/analysis/kelly-unique-schema-20260920.md + docs/kelly/analysis/kelly-unique-parts-schema-20260920.md。
"""
import argparse
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import signal_kelly_backtest as skb  # noqa: E402
from check_kelly_unique_restore import build_rebuilt, base_key  # noqa: E402


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def check_shard(shard_path, uniq_path):
    """对一片做 A 键集 / B 值逐位 / C 总行数 三查, 返回 (ok, detail)。"""
    shard = load(shard_path)
    uniq = load(uniq_path)
    rebuilt, key_idx = build_rebuilt(uniq)

    # A) 键集等价
    orig_set = {(qk, m, base_key(r, key_idx))
                for qk, mk in shard["quadrants"].items()
                for m, rows in mk.items() for r in rows}
    reb_set = {(qk, m, base_key(r, key_idx))
               for qk, mk in rebuilt.items()
               for m, rows in mk.items() for r in rows}
    only_orig = orig_set - reb_set
    only_reb = reb_set - orig_set
    a_ok = not only_orig and not only_reb

    # B) 值逐位(索引法, 按原行序)
    reb_index = {(qk, m, base_key(r, key_idx)): r
                 for qk, mk in rebuilt.items()
                 for m, rows in mk.items() for r in rows}
    mismatch = missing = checked = 0
    for qk, mk in shard["quadrants"].items():
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
                        diffs = [skb.TRADE_FIELDS[i] for i in range(len(skb.TRADE_FIELDS))
                                 if rb[i] != r[i]]
                        print(f"    值不一致 {qk} {m} {base_key(r, key_idx)}: diff={diffs}")
    b_ok = mismatch == 0 and missing == 0

    # C) 总行数
    orig_n = sum(len(rows) for mk in shard["quadrants"].values() for rows in mk.values())
    reb_n = sum(len(rows) for mk in rebuilt.values() for rows in mk.values())
    c_ok = orig_n == reb_n

    ok = a_ok and b_ok and c_ok
    detail = (f"A键集 orig={len(orig_set)} reb={len(reb_set)} 独有={len(only_orig)}/{len(only_reb)} "
              f"B值 checked={checked} miss={missing} diff={mismatch} C行数 {orig_n}/{reb_n}")
    return ok, detail


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--trades", required=True, help="原 trades JSON(对账基准)")
    ap.add_argument("--out", default=None, help="临时输出目录(默认系统 temp, 用完自删; 传了就保留)")
    args = ap.parse_args()

    trades = load(args.trades)
    if not trades.get("quadrants"):
        print("✗ 输入无 quadrants, 无交易记录, 跳过")
        return 1

    skb.KELLY_UNIQUE_EXPORT = 1
    if args.out:
        out_dir = args.out
        os.makedirs(out_dir, exist_ok=True)
        tmp = None
    else:
        tmp = tempfile.mkdtemp(prefix="kelly-unique-parts-")
        out_dir = tmp
    try:
        # trades_path 放 out_dir, 由其派生 parts_dir(<out_dir>/signal_kelly_trades_parts/)
        trades_path = os.path.join(out_dir, "signal_kelly_trades.json")
        skb._export_trades_parts(trades, trades_path)
        parts_dir = skb._trades_parts_dir(trades_path)

        # 逐片配对检查(recent + t{YYYY}), unique_ 前缀的是本工具产出源, 跳过
        pairs = []
        quad_sizes = 0
        uniq_sizes = 0
        for fn in sorted(os.listdir(parts_dir)):
            if not fn.endswith(".json") or fn.startswith("unique_") or fn.startswith("_"):
                continue
            ufn = "unique_" + fn
            if not os.path.exists(os.path.join(parts_dir, ufn)):
                print(f"✗ 缺唯一化分片: {ufn} (对应 {fn})")
                return 1
            pairs.append((fn, ufn))
            quad_sizes += os.path.getsize(os.path.join(parts_dir, fn))
            uniq_sizes += os.path.getsize(os.path.join(parts_dir, ufn))

        all_ok = True
        for fn, ufn in pairs:
            ok, detail = check_shard(
                os.path.join(parts_dir, fn), os.path.join(parts_dir, ufn))
            all_ok = all_ok and ok
            mark = "PASS" if ok else "FAIL"
            print(f"  [{mark}] {fn} vs {ufn}: {detail}")

        n_uniq_base = 0
        for fn, _ in pairs:
            if fn == "recent.json":
                continue
            u = load(os.path.join(parts_dir, "unique_" + fn))
            n_uniq_base += u["n_base"]
        print(f"\n分片体积: quadrants 原分片={quad_sizes/1024:.1f} KB, "
              f"唯一化分片={uniq_sizes/1024:.1f} KB, "
              f"压缩率={quad_sizes/uniq_sizes:.1f}x (gz 未计)")
        print(f"分片数: {len(pairs)} (recent + 年片 {len(pairs)-1})")
        if all_ok:
            print("RESULT: ALL PASS")
            return 0
        print("RESULT: FAIL")
        return 1
    finally:
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
