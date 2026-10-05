#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_repo_paths_ratchet.py — #195 路径守卫「棘轮」机检(方案 §4.6 R1-R3)。

背景:全仓 57 个 shell 脚本曾写死 `(REPO|GIT_REPO|TRADE_DIR|STATICDATA_REPO):-/Users/linhuichen`
mac 默认值(#195 分批迁移到 scripts/lib 的单点 resolve_repo)。本脚本=防回潮棘轮:

  R1(回潮面):含上述 pattern 的**代码行**所在的 .sh 必须仍在「已知集合」(= 已迁移 MIGRATED ∪
     迁移基线 PENDING_BASELINE)内;都不在 = 新脚本重新写死 mac 路径 → FAIL。
  R2(迁移面):MIGRATED 内每个文件必须**恰好 1 行** source lib 且**恰好 1 行** resolve_repo 调用。
  R3(残留面):MIGRATED 内每个文件**不得**有 `:/Users/linhuichen` 默认写法的代码行(注释内提及允许)。

判定用**代码行**(行首 `#` 视为注释跳过):lib 自身头注释里对病灶的举例提及不算命中。

⚠️ 本脚本**只创建、不挂任何 deploy 链 / 不设 cron**(方案 §7.2 待拍板#2:先独立手动跑,观察后再议
挂链)。用法:`python3 scripts/check_repo_paths_ratchet.py`;rc=0 = PASS。

随批次推进:某批迁移的文件从 PENDING_BASELINE **删**、加入 MIGRATED(R1 只收紧不放松)。
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).absolute().parent.parent
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
MAC_DEFAULT = re.compile(r":/Users/linhuichen")
SRC_RE = re.compile(r"^source\s+.*lib/repo_paths\.sh")
RES_RE = re.compile(r"^resolve_repo\s")


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
        if n_mac != 0:
            fails.append(f"R3 {rel}: 残留 `:/Users/linhuichen` 默认写法 {n_mac} 处(代码行,注释除外)")
        if n_src == 1 and n_res == 1 and n_mac == 0:
            pass_n += 1

    # ── 输出 ────────────────────────────────────────────────────────────────
    print(f"[ratchet] 扫描 scripts/**/*.sh:pattern 命中 {len(pattern_files)} 个"
          f"(白名单外 {len(pattern_files - known)})")
    print(f"[ratchet] MIGRATED {len(MIGRATED)} 个,PASS {pass_n}")
    if tightened:
        print(f"[ratchet] INFO 基线内已不再命中(建议移入 MIGRATED): {', '.join(tightened)}")
    for f in fails:
        print(f"[ratchet] FAIL {f}")
    if fails:
        print(f"[ratchet] RESULT=FAIL({len(fails)})")
        return 1
    print("[ratchet] RESULT=PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
