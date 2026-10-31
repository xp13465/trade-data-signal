#!/usr/bin/env python3
"""check_unit_registry_drift.py - UNIT_REGISTRY 与 systemd 真实 unit 漂移机检
(#309/#310 收尾 A, 2026-10-31)

【为什么需要它(病灶)】
  `gen_schedule_stats.py` 的 `UNIT_REGISTRY` 硬编码 43 个 unit(40 业务+基础 + 3 自监控)。
  `schedule_monitor.sh:_coverage_text` 用 `len(stats)+3` 算覆盖数 ⇒ 缺行时仍可能显示 43/43
  「OK 所有任务按计划执行」(假 OK, #309)。新增/改名 timer 若不进登记表 → 静默退出监控
  范围(#310: 24 个 timer 不在巡检范围的同类根因)。本脚本 = 把「登记表 vs 真实 unit 集」
  的漂移做成可机检闸门, 任一侧多/少一个 unit ⇒ 非零退出 + 明列差异。

【口径(单事实源复用, 不新造第三份清单)】
  - 登记表侧: `gen_schedule_stats.UNIT_REGISTRY`(43 个 `.service`, 含 3 个自监控);
  - 真实侧: 仿 `check_failed_units.collect_real_units()` = 静态(`docs/deploy/systemd-units-*.md`
    经 `gen_systemd_units.parse_units` 枚举) ∪ 动态(`systemctl list-unit-files` 现状);
  - 动态取不到(dev/CI 无 systemd)⇒ 回退静态集合 + 打 INFO(不崩、不因此放行);
  - **漂移判据**: 静态/动态真实集与登记表的 `.service` 名集合必须**完全相等**
    (集合对称差非空 ⇒ FAIL)。同时报告 `.timer` 侧仅做信息打印(timer 由 .service 派生,
    登记表只登记 .service, 防止 .timer 数 ≠ .service 数 误导)。

【退出码】
  - 0 = 无漂移(或 dry-run);
  - 2 = 漂移(集合差异非空), 明列「登记表多 / 真实侧多」两组;
  - 3 = 装载失败(导入/解析异常), 不静默放行。

【用法】
  python scripts/check_unit_registry_drift.py [--quiet]
  --quiet: 只打印差异与结论行, 跳过 INFO(适合挂闸门)。

【挂载】
  - main-merge 闸门(本机 merge 前): dev 无 systemd ⇒ 回退静态(docs §2)对比, 拦「登记表 vs 文档」
    漂移; 7.8c 节。
  - 可选云上巡检(后续): --source dynamic 跑真 systemctl, 拦「登记表 vs 运行时」漂移。

【红线】只读静态/子进程只跑 `systemctl list-unit-files`(无副作用, 不 restart/enable 任何 unit)。
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

_CODE_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS_DIR = Path(__file__).resolve().parent

# 与 check_failed_units 保持一致的项目命名空间口径(同源, 不另造常量)
_FORBIDDEN_PREFIX = "trade-"
_UNIT_SUFFIXES = (".service", ".timer", ".socket")


def _load_registry_services():
    """从 gen_schedule_stats.UNIT_REGISTRY 取 .service 名集合(单一事实源)。"""
    if str(_SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS_DIR))
    import gen_schedule_stats as gss  # noqa: PLC0415
    return {r["unit"] for r in gss.UNIT_REGISTRY if r["unit"].endswith(".service")}


def _static_real_services():
    """静态真实 .service 集: docs/deploy/systemd-units-*.md 经 gen_systemd_units 枚举。"""
    if str(_SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS_DIR))
    try:
        import gen_systemd_units as gsu  # noqa: PLC0415
        md_path = _CODE_REPO_ROOT / gsu.MD_REL_PATH
        order, _ = gsu.parse_units(str(md_path))
    except Exception as e:  # noqa: BLE001
        print(f"[INFO] 静态 unit 文档枚举失败({type(e).__name__}): {e}", file=sys.stderr)
        return set()
    return {u for u in order if u.startswith(_FORBIDDEN_PREFIX) and u.endswith(".service")}


def _dynamic_real_units():
    """运行时 systemctl list-unit-files 取 trade-*.{service,timer,socket}(取不到返回空)。"""
    if not shutil.which("systemctl"):
        return set()
    try:
        r = subprocess.run(
            ["systemctl", "list-unit-files", "--no-legend", "--no-pager"],
            capture_output=True, text=True, timeout=15, check=False,
        )
        if r.returncode != 0:
            return set()
    except Exception:  # noqa: BLE001
        return set()
    names = set()
    for line in (r.stdout or "").splitlines():
        parts = line.split()
        if not parts:
            continue
        name = parts[0]
        if name.startswith(_FORBIDDEN_PREFIX) and name.endswith(_UNIT_SUFFIXES):
            names.add(name)
    return names


def collect_real_services():
    """真实侧 .service 集 = 静态(docs) ∪ 动态(systemctl .service)。动态缺 ⇒ 回退静态。"""
    static = _static_real_services()
    dynamic_all = _dynamic_real_units()
    dynamic_svc = {u for u in dynamic_all if u.endswith(".service")}
    if dynamic_svc:
        merged = static | dynamic_svc
        print(f"[INFO] 真实 unit: 静态 {len(static)} + 动态 {len(dynamic_svc)} = 合并 {len(merged)} 个 .service")
        return merged, dynamic_all
    print(f"[INFO] 动态 systemctl 取不到(dev/CI 无 systemd), 回退静态 docs 集合({len(static)} 个 .service)")
    return static, dynamic_all


def check_drift(quiet: bool = False) -> int:
    """主流程: 对比登记表 vs 真实集, 漂移 ⇒ exit 2。"""
    try:
        registry = _load_registry_services()
    except Exception as e:  # noqa: BLE001
        print(f"[FAIL] 装载 UNIT_REGISTRY 失败({type(e).__name__}): {e}", file=sys.stderr)
        return 3
    real, dynamic_all = collect_real_services()

    if not real:
        print("[FAIL] 真实 unit 集为空(docs 缺失 + 无 systemd), 无法判定漂移, 拒绝放行", file=sys.stderr)
        return 3

    in_registry_only = sorted(registry - real)
    in_real_only = sorted(real - registry)
    drift = bool(in_registry_only or in_real_only)

    if not quiet:
        print(f"登记表 {len(registry)} 个 .service; 真实集 {len(real)} 个 .service"
              f"{' (含动态)' if dynamic_all else ' (仅静态)'}")
    # .timer 侧信息打印(登记表只管 .service; timer 由 service 派生, 信息用)
    dyn_timers = sorted(u for u in dynamic_all if u.endswith(".timer"))
    if dyn_timers and not quiet:
        print(f"[INFO] 动态 .timer {len(dyn_timers)} 个(登记表不收录 timer, 仅信息)")

    if not drift:
        print(f"✓ 无漂移: 登记表 {len(registry)} == 真实集 {len(real)} 个 .service")
        return 0

    print("[FAIL] UNIT_REGISTRY 与真实 unit 漂移:", file=sys.stderr)
    if in_registry_only:
        print("  登记表多(已登记但 docs/systemd 找不到, 可能改名/删除未销账):", file=sys.stderr)
        for u in in_registry_only:
            print(f"    - {u}", file=sys.stderr)
    if in_real_only:
        print("  真实侧多(docs/systemd 有但登记表没收录, 新增 timer 漏进监控 = #310 同类):", file=sys.stderr)
        for u in in_real_only:
            print(f"    - {u}", file=sys.stderr)
    print("修复指引: 对齐 gen_schedule_stats.UNIT_REGISTRY 与 docs/deploy/systemd-units-*.md"
          " + (云上)systemctl list-unit-files", file=sys.stderr)
    return 2


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="UNIT_REGISTRY vs 真实 unit 漂移机检(#309/#310 收尾 A)")
    ap.add_argument("--quiet", action="store_true", help="只打印差异与结论行")
    args = ap.parse_args(argv)
    return check_drift(quiet=args.quiet)


if __name__ == "__main__":
    sys.exit(main())
