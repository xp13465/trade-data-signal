#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_repo_paths_ratchet.py — #195 路径守卫「棘轮」机检(方案 §4.6 R1-R3)。

背景:全仓 57 个 shell 脚本曾写死 `(REPO|GIT_REPO|TRADE_DIR|STATICDATA_REPO):-/Users/linhuichen`
mac 默认值(#195 分批迁移到 scripts/lib 的单点 resolve_repo)。本脚本=防回潮棘轮:

  R1(回潮面):含上述 pattern 的**代码行**所在的 .sh 必须仍在「已知集合」(= 已迁移 MIGRATED ∪
     迁移基线 PENDING_BASELINE)内;都不在 = 新脚本重新写死 mac 路径 → FAIL。
  R2(迁移面):MIGRATED 内每个文件必须**恰好 1 行** source lib 且**恰好 1 行** resolve_repo 调用。
  R3(残留面):MIGRATED 内每个文件**不得**有 `/Users/linhuichen` 默认写法的**代码行**(注释内提及允许)。
      ⚠️ 2026-10-06 返修:原正则 `:/Users/linhuichen` **匹配不到主流病灶形态 `:-/Users/linhuichen`**
      ⇒ 全仓代码行命中 0 ⇒ R3 恒 PASS,**空转闸门**(独立审复现)。已改为 `:-?/Users/linhuichen`
      (同时覆盖 `:-/` 与 `:/`),并加「恒在自检」(见下)+「变异自测 `--selftest`」双重钉死。

判定用**代码行**(行首 `#` 视为注释跳过):lib 自身头注释里对病灶的举例提及不算命中。

**恒在自检(防再次空转,§18 L49 假样本养绿根治)**:每次运行都先用标准病灶样本
`REPO="${REPO:-/Users/linhuichen/x}"` 反查 R3 正则「至少能匹配到一个已知病灶」;匹配不到 → 直接 FAIL
(即「正则自己失效」= 空转,不允许静默 PASS)。

**变异自测 `--selftest`(一条命令验闸门真能响)**:构造临时树,把已迁移文件的 env 默认值**改回**
写死 mac 路径 → 断言 ratchet **必须 FAIL**;同时跑未变异负对照断言 **PASS**(证自测装置本身非恒 FAIL)。
`python3 scripts/check_repo_paths_ratchet.py --selftest`;rc=0 = 自测通过。

⚠️ 本脚本**只创建、不挂任何 deploy 链 / 不设 cron**(方案 §7.2 待拍板#2:先独立手动跑,观察后再议
挂链)。用法:`python3 scripts/check_repo_paths_ratchet.py`;rc=0 = PASS。

随批次推进:某批迁移的文件从 PENDING_BASELINE **删**、加入 MIGRATED(R1 只收紧不放松)。
"""
import os
import re
import sys
from pathlib import Path

# RATCHET_ROOT:测试/变异自测用「仓根覆盖」(默认 = 本脚本所在仓根);生产/日常不设。
ROOT = Path(os.environ.get("RATCHET_ROOT") or Path(__file__).absolute().parent.parent).absolute()
SCRIPTS = ROOT / "scripts"

# 已迁移(批1):scripts/lib/repo_paths.sh + 2 个脚本
MIGRATED = {
    "scripts/check_r2_consistency.sh",
    "scripts/cloud_unit_patrol.sh",
}

# 迁移基线(批1 时刻仍未迁移的 56 个已知病灶 = §2 的 57 减去本批已迁的 check_r2_consistency.sh)。
# 随各批推进:该批文件从此集合删除并移入 MIGRATED。
PENDING_BASELINE = {
    "scripts/backfill_indices.sh",
    "scripts/backfill_metrics.sh",
    "scripts/backup_db.sh",
    "scripts/brief_push_wrapper.sh",
    "scripts/build_echarts.sh",
    "scripts/check_data_gap_alerts.sh",
    "scripts/check_signals.sh",
    "scripts/collect.sh",
    "scripts/deploy.sh",
    "scripts/etf_national_team_backfill.sh",
    "scripts/fapi_daily_syn.sh",
    "scripts/fix_turnover_partial_20260814.sh",
    "scripts/fund_nav_upload_async.sh",
    "scripts/futures_backfill.sh",
    "scripts/gold_night.sh",
    "scripts/intraday_snapshot.sh",
    "scripts/kelly_intraday_rerun.sh",
    "scripts/lhb_backfill.sh",
    "scripts/migrate_large_json_out_of_git.sh",
    "scripts/monitor_72h.sh",
    "scripts/nextday_gap_check.sh",
    "scripts/nextday_plan.sh",
    "scripts/on_skip_notify.sh",
    "scripts/overfit_monitor.sh",
    "scripts/pf_score_daily.sh",
    "scripts/pf_score_weekly.sh",
    "scripts/pipeline.sh",
    "scripts/public_fund_daily.sh",
    "scripts/public_fund_estimation.sh",
    "scripts/public_fund_full.sh",
    "scripts/public_fund_quarterly.sh",
    "scripts/push_schedule_stats.sh",
    "scripts/r2_upload_async.sh",
    "scripts/r2_upload_skip_notify.sh",
    "scripts/run_ab_direction_anchor.sh",
    "scripts/run_daily_brief.sh",
    "scripts/rzhb_backfill.sh",
    "scripts/s06_snapshot.sh",
    "scripts/schedule_monitor.sh",
    "scripts/self_heal.sh",
    "scripts/stage0_full_manual.sh",
    "scripts/stage0_manager.sh",
    "scripts/stage0_nav.sh",
    "scripts/stage0_overview.sh",
    "scripts/stage0_risk.sh",
    "scripts/staticdata_backup_async.sh",
    "scripts/staticdata_sync.sh",
    "scripts/sync_fund_score_to_d1.sh",
    "scripts/turnover_backfill.sh",
    "scripts/turnover_backfill_skip_notify.sh",
    "scripts/update_all.sh",
    "scripts/update_all_serial.sh",
    "scripts/update_lab.sh",
    "scripts/uptime_check.sh",
    "scripts/us_stock_morning.sh",
    "scripts/verify_backup.sh",
}

PATTERN = re.compile(r"(REPO|GIT_REPO|TRADE_DIR|STATICDATA_REPO):-/Users/linhuichen")
# R3 残留面正则:2026-10-06 返修 —— `:-?` 同时覆盖 `:-/Users/...`(全仓主流形态)与 `:/Users/...`。
MAC_DEFAULT = re.compile(r":-?/Users/linhuichen")
SRC_RE = re.compile(r"^source\s+.*lib/repo_paths\.sh")
RES_RE = re.compile(r"^resolve_repo\s")

# 恒在自检样本:任何一次运行都必须能匹配到它,否则 = R3 空转(§18 L49)。
_VACUITY_PROBE = 'REPO="${REPO:-/Users/linhuichen/code/trade-data}"'


def _iter_scripts():
    for p in sorted(SCRIPTS.rglob("*.sh")):
        rel = p.relative_to(ROOT).as_posix()
        if "/worktrees/" in rel:
            continue
        yield rel, p


def _code_lines(text: str):
    for ln in text.splitlines():
        if ln.lstrip().startswith("#"):
            continue
        yield ln


def main() -> int:
    fails = []
    pass_n = 0

    # ── R3 恒在自检(防空转):R3 正则必须能匹配到标准病灶样本 ─────────────────────
    if not MAC_DEFAULT.search(_VACUITY_PROBE):
        fails.append(f"R3 空转自检: MAC_DEFAULT 匹配不到标准病灶样本 {_VACUITY_PROBE!r} "
                     f"(闸门失效, 见 §18 L49)")

    # ── R1:pattern 代码行所在文件必须 ∈ MIGRATED ∪ PENDING_BASELINE ─────────────
    pattern_files = set()
    for rel, p in _iter_scripts():
        text = p.read_text(encoding="utf-8", errors="replace")
        if any(PATTERN.search(ln) for ln in _code_lines(text)):
            pattern_files.add(rel)

    known = MIGRATED | PENDING_BASELINE
    for rel in sorted(pattern_files - known):
        fails.append(f"R1 回潮: {rel} 含 mac 默认 pattern 但不在白名单(已迁移 ∪ 基线)")
    # 棘轮收紧:基线文件若已不再命中 pattern,应已被移入 MIGRATED(提醒用,不判 FAIL)
    tightened = sorted(PENDING_BASELINE - pattern_files)

    # ── R2/R3:MIGRATED 文件必须规范迁移 ──────────────────────────────────────
    n_mac_total = 0
    for rel in sorted(MIGRATED):
        p = ROOT / rel
        if not p.exists():
            fails.append(f"R2 {rel}: 文件不存在")
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        n_src = sum(1 for ln in lines if SRC_RE.search(ln))
        n_res = sum(1 for ln in lines if RES_RE.search(ln))
        if n_src != 1:
            fails.append(f"R2 {rel}: source lib 行数={n_src}(应为 1)")
        if n_res != 1:
            fails.append(f"R2 {rel}: resolve_repo 调用行数={n_res}(应为 1)")
        n_mac = sum(1 for ln in _code_lines(text) if MAC_DEFAULT.search(ln))
        n_mac_total += n_mac
        if n_mac != 0:
            fails.append(f"R3 {rel}: 残留 `:-?/Users/linhuichen` 默认写法 {n_mac} 处(代码行,注释除外)")
        if n_src == 1 and n_res == 1 and n_mac == 0:
            pass_n += 1

    # ── 输出 ────────────────────────────────────────────────────────────────
    print(f"[ratchet] ROOT={ROOT}")
    print(f"[ratchet] 扫描 scripts/**/*.sh:pattern 命中 {len(pattern_files)} 个"
          f"(白名单外 {len(pattern_files - known)})")
    print(f"[ratchet] MIGRATED {len(MIGRATED)} 个,PASS {pass_n};R3 残留命中={n_mac_total}")
    print(f"[ratchet] R3 正则健康自检: {MAC_DEFAULT.pattern!r} 命中标准样本 "
          f"{'OK' if MAC_DEFAULT.search(_VACUITY_PROBE) else 'FAIL(空转!)'}")
    if tightened:
        print(f"[ratchet] INFO 基线内已不再命中(建议移入 MIGRATED): {', '.join(tightened)}")
    for f in fails:
        print(f"[ratchet] FAIL {f}")
    if fails:
        print(f"[ratchet] RESULT=FAIL({len(fails)})")
        return 1
    print("[ratchet] RESULT=PASS")
    return 0


def selftest() -> int:
    """变异自测(§18 L49 假样本养绿根治):证明 R3 闸门**真能响**,不是空转。

    做法:造临时仓根,放两份**真实已迁移文件**;①负对照(未变异)→ 期望 PASS;
    ②把 check_r2_consistency.sh 的 env 默认值改回写死 mac 路径(病灶形态)→ 期望 **FAIL**。
    rc=0 = 自测通过(闸门非空转);任一断言不成立 = FAIL。
    """
    import shutil
    import subprocess
    import tempfile

    me = str(Path(__file__).absolute())
    ok = True

    def _run(root: Path):
        env = dict(os.environ, RATCHET_ROOT=str(root))
        r = subprocess.run([sys.executable, me], capture_output=True, text=True, env=env)
        return r.returncode, (r.stdout + r.stderr)

    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        (t / "scripts").mkdir(parents=True)
        for rel in sorted(MIGRATED):
            shutil.copy2(Path(__file__).absolute().parent.parent / rel, t / rel)

        # ① 负对照:未变异 → 必须 PASS(否则自测装置本身恒 FAIL,证据无效)
        rc0, out0 = _run(t)
        if rc0 == 0 and "RESULT=PASS" in out0:
            print("  PASS: 负对照(未变异样本)→ RESULT=PASS(装置本身非恒 FAIL)")
        else:
            ok = False
            print(f"  FAIL: 负对照(未变异)竟 rc={rc0}, tail={out0.strip().splitlines()[-3:]}")

        # ② 变异:把已迁移文件的 env 默认值改回写死 mac 路径 → 必须 FAIL
        #    注意:锚点必须落在**代码行**(`export REPO GIT_REPO` 在文件头注释里也出现过一次,
        #    若用裸 str.replace(...,1) 会命中注释 → 变异落在注释上被 _code_lines 跳过 → 假 PASS,
        #    正是 §18 L49「假样本养绿」的变体)。故按**整行精确匹配**定位代码行。
        target = t / "scripts/check_r2_consistency.sh"
        lines = target.read_text(encoding="utf-8").splitlines(keepends=True)
        hit_i = None
        for i, ln in enumerate(lines):
            if ln.strip() == "export REPO GIT_REPO":
                hit_i = i
                break
        if hit_i is None:
            ok = False
            print("  FAIL: 变异注入失败(样本里找不到代码行 'export REPO GIT_REPO')")
        else:
            lines[hit_i] = 'export REPO="${REPO:-/Users/linhuichen/code/trade-data}" GIT_REPO\n'
            target.write_text("".join(lines), encoding="utf-8")
            rc1, out1 = _run(t)
            if rc1 != 0 and "R3" in out1 and "RESULT=FAIL" in out1:
                hit = [ln for ln in out1.splitlines() if "R3 " in ln and "残留" in ln]
                print(f"  PASS: 变异样本(第 {hit_i + 1} 行代码)→ RESULT=FAIL(闸门真响);"
                      f"{hit[0].strip() if hit else ''}")
            else:
                ok = False
                print(f"  FAIL: 变异样本竟 rc={rc1}(应 FAIL)⇒ R3 空转复现, tail={out1.strip().splitlines()[-4:]}")

    print(f"[ratchet-selftest] {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv[1:]:
        sys.exit(selftest())
    sys.exit(main())
