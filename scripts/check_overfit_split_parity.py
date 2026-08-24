#!/usr/bin/env python3
"""AI 监控卡数据拆分 parity 校验 + 测试夹具派生(B件套 2026-08-24 提速组合 A+B+C+D)。

【目的】验证 overfit_monitor.json 主文件 + overfit_monitor_ext.json(by_k/filtered_by_k 拆分,
        scripts/overfit_monitor.py B件套)与拆分前全量文件的数值**逐位一致**(§23.5 报告可复现;
        §23.2 三铁律②自测完成)。另提供 --make-fixtures 从旧全量格式派生拆分后两文件,
        供 playwright 本地验证用(只读生产源+输出独立, memory unreleased-feature-isolation)。
【口径】拆分归属(2026-08-24 定稿): 主文件 = generated_at/version/config/accuracy/overfit/
        filtered/recent/alerts(默认首屏渲染所需——filtered 是降亏开+无K档默认路径 bank,
        recent 是 new14 默认模式组集必需); ext 文件 = by_k/filtered_by_k(K档交互专用, 占原量 77%)。
【断言】①六个数据块(accuracy/overfit/filtered/recent/by_k/filtered_by_k)canonical JSON 序列化
          逐位相等(recent 缺失=老数据, 跳过并标注)
        ②结构合规: 主文件含 accuracy/overfit/filtered/generated_at; ext 含 by_k/filtered_by_k
        ③compact 序列化: 两文件原始字节无 indent(不含 '\\n  "' 缩进模式, A件套验收点)
        ④体积对比输出: src vs main vs ext(indent/compact 双口径)
【输入】--src 拆分前全量 JSON(如 data/overfit_monitor.json 2026-08-21 版, 27.8MB indent 格式)
        --main/--ext 拆分后两文件(生产=overfit_monitor.py 产出; 测试=--make-fixtures 派生)
【输出】stdout 校验报告; 全部 PASS 退出码 0, 任一 FAIL 退出码 1(可挂 deploy/check 链)
【用法】# 校验生产拆分产物(launchd 打点后):
          python3 scripts/check_overfit_split_parity.py --src old_full.json --main data/overfit_monitor.json --ext data/overfit_monitor_ext.json
        # 派生测试夹具(不动生产 data/):
          python3 scripts/check_overfit_split_parity.py --make-fixtures --src data/overfit_monitor.json --out-dir /tmp/aimon-fixture
【复现】python3 scripts/check_overfit_split_parity.py --make-fixtures --src /Users/linhuichen/code/trade-data/static-site/data/overfit_monitor.json --out-dir /tmp/aimon-fixture && python3 scripts/check_overfit_split_parity.py --src /Users/linhuichen/code/trade-data/static-site/data/overfit_monitor.json --main /tmp/aimon-fixture/overfit_monitor.json --ext /tmp/aimon-fixture/overfit_monitor_ext.json
【日期】2026-08-24 | 数据版本基准: 线上 generated_at=2026-08-21 21:40 v2(无 recent 键)
"""
import argparse
import json
import os
import sys

# 拆分归属单一事实源(与 overfit_monitor.py B件套产出/app.js _ovNeedsExtBank 判定同口径)
EXT_KEYS = ("by_k", "filtered_by_k")
DATA_KEYS = ("accuracy", "overfit", "filtered", "recent") + EXT_KEYS


def _canon(obj) -> str:
    """canonical 序列化: sort_keys + compact, 消除键序/空白差异后比内容。"""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def split_full(src: dict):
    """按定稿归属把全量 dict 拆成 (main, ext)。fixture 派生用, 与 py 产出结构对齐。"""
    main = {k: v for k, v in src.items() if k not in EXT_KEYS}
    ext = {
        "generated_at": src.get("generated_at"),
        "version": src.get("version"),
        "by_k": src["by_k"],
        "filtered_by_k": src["filtered_by_k"],
    }
    return main, ext


def make_fixtures(src_path: str, out_dir: str) -> int:
    with open(src_path, encoding="utf-8") as f:
        src = json.load(f)
    main, ext = split_full(src)
    os.makedirs(out_dir, exist_ok=True)
    mp = os.path.join(out_dir, "overfit_monitor.json")
    ep = os.path.join(out_dir, "overfit_monitor_ext.json")
    for p, obj in ((mp, main), (ep, ext)):
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, p)
        print(f"  fixture 已写: {p} ({os.path.getsize(p) / 1048576:.2f}MB)")
    return 0


def check(src_path: str, main_path: str, ext_path: str) -> int:
    fails = []
    with open(src_path, encoding="utf-8") as f:
        src = json.load(f)
    with open(main_path, encoding="utf-8") as f:
        raw_main = f.read()
    with open(ext_path, encoding="utf-8") as f:
        raw_ext = f.read()
    main = json.loads(raw_main)
    ext = json.loads(raw_ext)

    # ① 六数据块逐位一致(canonical)
    print("== ① 数据块逐位一致性(canonical JSON) ==")
    for key in DATA_KEYS:
        if key not in src:
            print(f"  SKIP {key}: 拆分前源无此键(老数据)")
            continue
        in_main = key in main
        in_ext = key in ext
        where = "main" if in_main else ("ext" if in_ext else None)
        if not where:
            fails.append(f"{key}: 拆分后两文件均缺失")
            print(f"  FAIL {key}: 拆分后缺失")
            continue
        got = main[key] if in_main else ext[key]
        ok = _canon(got) == _canon(src[key])
        print(f"  {'PASS' if ok else 'FAIL'} {key}: {'逐位一致' if ok else '数值不一致!'} ({where})")
        if not ok:
            fails.append(f"{key}: canonical 不等")

    # ② 结构合规
    print("== ② 结构合规 ==")
    for k in ("generated_at", "accuracy", "overfit", "filtered"):
        ok = k in main
        print(f"  {'PASS' if ok else 'FAIL'} 主文件含 {k}")
        if not ok:
            fails.append(f"main 缺 {k}")
    for k in ("generated_at", "by_k", "filtered_by_k"):
        ok = k in ext
        print(f"  {'PASS' if ok else 'FAIL'} ext 含 {k}")
        if not ok:
            fails.append(f"ext 缺 {k}")
    if ext.get("generated_at") and main.get("generated_at"):
        ok = ext["generated_at"] == main["generated_at"]
        print(f"  {'PASS' if ok else 'FAIL'} 主/ext generated_at 对齐({main.get('generated_at')})")
        if not ok:
            fails.append("generated_at 不对齐")
    # 键集合守恒: src 数据键不得丢失(元数据 desc 类新增键允许)
    for k in src:
        if k in DATA_KEYS or k in ("generated_at", "version", "config", "alerts"):
            if k == "alerts":
                continue  # alerts 仅打点告警时有, fixture 按原样随 main; 生产回写段单独落
            ok = (k in main) or (k in ext)
            if not ok:
                fails.append(f"键守恒: {k} 丢失")
                print(f"  FAIL 键守恒: {k} 在两文件中均缺失")

    # ③ compact 序列化(A件套): 严格判法=同数据 compact 重序列化与原文件字节级相等
    # (不能用 "含 ': '/'\\n' 子串" 判——字符串值内部可合法含这些文本, 会误报)
    print("== ③ compact 序列化(重序列化等价) ==")
    for name, raw in (("main", raw_main), ("ext", raw_ext)):
        obj = json.loads(raw)
        compact = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
        ok = (compact == raw)
        print(f"  {'PASS' if ok else 'FAIL'} {name} 为 compact 序列化(字节级等价)")
        if not ok:
            fails.append(f"{name}: 非 compact 序列化")

    # ④ 体积对比
    print("== ④ 体积对比(MB) ==")
    sz = lambda p: os.path.getsize(p) / 1048576
    total_after = sz(main_path) + sz(ext_path)
    print(f"  拆分前全量: {sz(src_path):.2f}MB")
    print(f"  拆分后合计: {total_after:.2f}MB (main {sz(main_path):.2f} + ext {sz(ext_path):.2f})")
    print(f"  首屏只需主文件: {sz(src_path):.2f} -> {sz(main_path):.2f}MB "
          f"(-{(1 - sz(main_path) / sz(src_path)) * 100:.0f}%)")

    print("== 结论 ==")
    if fails:
        print(f"❌ FAIL({len(fails)} 项): " + "; ".join(fails))
        return 1
    print("✅ PASS: 拆分前后数值逐位一致, 结构合规, compact 生效")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="overfit_monitor 拆分 parity 校验/夹具派生")
    ap.add_argument("--src", required=True, help="拆分前全量 JSON 路径")
    ap.add_argument("--main", help="拆分后主文件路径(校验模式)")
    ap.add_argument("--ext", help="拆分后 ext 文件路径(校验模式)")
    ap.add_argument("--make-fixtures", action="store_true", help="夹具派生模式")
    ap.add_argument("--out-dir", default="/tmp/aimon-fixture", help="夹具输出目录")
    a = ap.parse_args()
    if a.make_fixtures:
        return make_fixtures(a.src, a.out_dir)
    if not (a.main and a.ext):
        print("校验模式需 --main 与 --ext(或用 --make-fixtures)", file=sys.stderr)
        return 2
    return check(a.src, a.main, a.ext)


if __name__ == "__main__":
    sys.exit(main())
