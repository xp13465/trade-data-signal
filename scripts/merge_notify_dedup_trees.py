#!/usr/bin/env python3
"""#245 L3e 切换瞬态配套: 合并两树 `data/notify_dedup.json`(幂等, 可反复跑)。

背景(为什么需要它)
------------------
L3e(`notify.py` REPO 接 env)把告警去重文件单点化到 **运行树** 后, py 侧告警的
dedup 历史留在 **代码树** 不迁移 ⇒ 切换后 ≤6h 去重窗内, 同一个 key 可能补发一次
(低危, 但可一次性消除)。本脚本把代码树的 `last_alerted` 合并进运行树:
每个 key 取两树中**较晚**的时刻(= 更保守的抑制, 绝不导致「该发而未发」),
写入运行树; 代码树文件**不动**(只读)。

安全契约
--------
- **默认 dry-run**: 不加 `--apply` 只打印将要发生的变更, 零写盘。
- `--apply` 前先把运行树现有文件备份为 `<file>.bak-<ts>`(§25 可逆), 写回用
  tmp + `os.replace` 原子写(与 notify.py `update_dedup` 同精神)。
- **幂等**: 重复跑 `added=0 updated=0`(已合并的两树 max 相同)。
- 纯文件操作: 不 import notify、不发任何通知、不触碰其它文件。
- 无法解析/非 dict 的条目一律跳过并在统计里报出(绝不因脏数据中断)。

用法
----
  # dry-run(默认; 先看数字)
  python3 scripts/merge_notify_dedup_trees.py --run-tree /home/ubuntu/code/trade-data \\
      --code-tree /home/ubuntu/code/trade-data-signal
  # 实际合并(备份 + 原子写)
  python3 scripts/merge_notify_dedup_trees.py --run-tree ... --code-tree ... --apply

`--run-tree` 缺省 = `$REPO`(或脚本所在仓推导); `--code-tree` 缺省 = 自动探测
`<run>/../trade-data-signal` → `<run>/../trade`。

时点: 云上应在 **切换后**(新 notify.py 生效)执行一次即达终态; 切换前跑也无害
(幂等), 只是切换后代码树不再新增, 需再跑一次收尾。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

DEDUP_REL = Path("data") / "notify_dedup.json"


def _default_run_tree() -> Path:
    env = os.environ.get("REPO")
    if env:
        return Path(env)
    return Path(__file__).absolute().parent.parent


def _default_code_tree(run_tree: Path) -> Path | None:
    for cand in (run_tree.parent / "trade-data-signal", run_tree.parent / "trade"):
        if (cand / DEDUP_REL).exists():
            return cand
    return None


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"[merge-dedup] 读取失败 {path}: {exc}", file=sys.stderr)
        return {}
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"[merge-dedup] JSON 解析失败 {path}: {exc}(跳过该树)", file=sys.stderr)
        return {}
    return data if isinstance(data, dict) else {}


def _last_alerted(entry: object) -> str:
    """取条目的 last_alerted 字符串(格式 YYYY-MM-DD HH:MM:SS, 可直接字典序比较)。"""
    if isinstance(entry, dict):
        val = entry.get("last_alerted")
        return val if isinstance(val, str) else ""
    return ""


def merge(run: dict, code: dict) -> tuple[dict, int, int, int]:
    """返回 (merged, added, updated, skipped)。"""
    merged: dict = dict(run)
    added = updated = skipped = 0
    for key, val in code.items():
        if not isinstance(val, dict) or not _last_alerted(val):
            skipped += 1  # 脏数据: 无有效 last_alerted
            continue
        if key not in merged:
            merged[key] = val
            added += 1
            continue
        cur = _last_alerted(merged[key])
        if _last_alerted(val) > cur:
            merged[key] = val
            updated += 1
        elif not cur:
            merged[key] = val
            updated += 1
    return merged, added, updated, skipped


def main() -> int:
    ap = argparse.ArgumentParser(description="合并两树 notify_dedup.json(取每 key 较晚 last_alerted)")
    ap.add_argument("--run-tree", default=None, help="运行树根(缺省 $REPO 或脚本推导)")
    ap.add_argument("--code-tree", default=None, help="代码树根(缺省自动探测)")
    ap.add_argument("--apply", action="store_true", help="实际写入(缺省 dry-run)")
    ap.add_argument("--backup-dir", default=None, help="备份目录(缺省与目标文件同目录)")
    args = ap.parse_args()

    run_tree = Path(args.run_tree) if args.run_tree else _default_run_tree()
    code_tree = Path(args.code_tree) if args.code_tree else _default_code_tree(run_tree)
    if code_tree is None or not (code_tree / DEDUP_REL).exists():
        print(f"[merge-dedup] 找不到代码树 dedup 文件(code_tree={code_tree}); 无历史可迁移, 直接退出",
              file=sys.stderr)
        return 0

    run_file = run_tree / DEDUP_REL
    code_file = code_tree / DEDUP_REL
    run = _load(run_file)
    code = _load(code_file)
    merged, added, updated, skipped = merge(run, code)

    print(f"[merge-dedup] run_tree={run_tree}")
    print(f"[merge-dedup] code_tree={code_tree}")
    print(f"[merge-dedup] run_keys={len(run)} code_keys={len(code)} "
          f"merged_keys={len(merged)} added={added} updated={updated} skipped={skipped}")
    changed = added + updated
    if changed == 0:
        print("[merge-dedup] 无变化(幂等: 两树 max 已一致), 不写盘")
        return 0
    if not args.apply:
        print(f"[merge-dedup] DRY-RUN: 将新增 {added} 键 / 更新 {updated} 键 → {run_file}"
              f"(加 --apply 才写入)")
        return 0

    # ── 备份 + 原子写 ──
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = Path(args.backup_dir) if args.backup_dir else run_file.parent
    backup_dir.mkdir(parents=True, exist_ok=True)
    if run_file.exists():
        backup = backup_dir / f"{run_file.name}.bak-{ts}"
        backup.write_bytes(run_file.read_bytes())
        print(f"[merge-dedup] 已备份原文件 → {backup}")
    tmp = run_file.parent / f"{run_file.name}.tmp-{os.getpid()}"
    tmp.write_text(json.dumps(merged, ensure_ascii=False, indent=2, sort_keys=True),
                   encoding="utf-8")
    os.replace(tmp, run_file)
    print(f"[merge-dedup] 已写入 {run_file}({len(merged)} 键)")

    # 回读校验: 合并结果对每个 key 的 last_alerted == max(两树)
    check = _load(run_file)
    bad = [k for k in code if _last_alerted(code[k]) and
           _last_alerted(check.get(k, {})) < _last_alerted(code[k])]
    print(f"[merge-dedup] 回读校验: post_keys={len(check)} mismatch={len(bad)}"
          + (f" {bad[:5]}" if bad else " PASS"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())