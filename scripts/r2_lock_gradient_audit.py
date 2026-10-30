#!/usr/bin/env python3
"""R2 上传锁: 分域声明 + 超时梯度审计(只读静态检查, 2026-10-28)。

背景(任务书 /tmp/task-r2lock-20261028.md, 台账 L55 梯度):
  全局单锁时代所有 R2 上传串行排队, 10-27 实测 S06 等锁 870s 被自身 900s 上限杀掉(rc=124),
  最长等锁 3990s。改造后: 调用方按产物域声明 R2_UPLOAD_LOCK_DOMAIN(域锁 EX + 全局 SH 屏障),
  未声明域者回落全局 EX(向后兼容)。本脚本机检三件事:

  ① 所有 upload_r2.py 调用方都**显式声明域**(或登记在「不适用」豁免表, 且理由可核);
  ② 每个调用方「锁等待上限 < 自身内层超时预算」(内层无界=不适用, 显式标注);
  ③ 每个调用方「内层预算 < 外层 systemd TimeoutStartSec」(外层 0/无=不适用; 已知例外入
     KNOWN_INNER_OVER_OUTER 豁免并写清旧账锚点, 不许静默放过)。

用法: python3 scripts/r2_lock_gradient_audit.py            # 表格 + PASS/FAIL, FAIL 退出 1
      python3 scripts/r2_lock_gradient_audit.py --json     # 机读输出
只读: 不跑上传/不碰锁文件/不发网络(static-only, §18 L50)。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SNAPSHOT = REPO / "docs" / "deploy" / "systemd-units-cloud-snapshot.txt"
UR_PY = REPO / "scripts" / "upload_r2.py"
PROBE_PY = REPO / "scripts" / "r2_lock_probe.py"

if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))
# 域名白名单的唯一事实源(与 upload_r2.py / r2_lock_probe.py 同源, 禁止手抄第二份)。
from r2_lock_paths import DOMAIN_ENV, LOCK_DOMAINS  # noqa: E402

# 产物域登记表: 域 → 该域写者共同占用的对象 key 前缀(证明域间不重叠的权威清单;
# 勘察依据 = docs/ops/r2-lock-domains-20261028.md)。
DOMAINS = {
    "data": ["data/*.json(顶层: data-large/all-data/intraday/data-files/etf-score 外)"],
    "kelly_parts": ["data/signal_kelly_trades_parts/"],
    "kelly_sdc": ["data/signal_kelly_trades_sdc_parts/"],
    "kelly_snapshots": ["data/signal_kelly_snapshots/"],
    "lab": ["lab/"],
    "trade_sim": ["trade_sim/"],
    "trade_sim_data": ["trade_sim_data/"],
    "index": ["index/"],
    "etf": ["etf/"],
    "accum_nav": ["accum_nav/"],
    "industry": ["industry/"],
    "public_fund": ["public_fund/"],
    "offshore_fund": ["offshore_fund/"],
    "fund_score": ["fund_score/"],
    "etf_score": ["data/etf_score_list_*.json(data-large/all-data 共同排除)"],
    "fund_nav": ["nav_bucket/"],
    "backup_db": ["backup/(私有桶)"],
    "large_json": ["large-json/(私有桶)"],
    "claude_backup": ["claude-backup/(私有桶)"],
    "decommissioned": ["decommissioned/(私有桶)"],
}

# 每个调用点: (脚本, 站点说明, 域|None, 锁等待上限, 内层预算|None=无界, 外层 unit, 脚本内必含标记)
# 锁等待/内层单位=秒; 外层 unit 名 → 从 docs/deploy/systemd-units-cloud-snapshot.txt 读 TimeoutStartSec。
SITES = [
    # ── r2_upload_async.sh(异步通道; 外层 = systemd-run 瞬时 service, 本表按 0=无界 登记) ──
    ("scripts/r2_upload_async.sh", "upload-lab", "lab", 600, 7200, None, 'run_r2_upload "upload-lab" 900 --lock-domain lab --lock-wait 600'),
    ("scripts/r2_upload_async.sh", "upload-trade-sim", "trade_sim", 600, 7200, None, 'run_r2_upload "upload-trade-sim" 900 --lock-domain trade_sim --lock-wait 600'),
    ("scripts/r2_upload_async.sh", "upload-trade-sim-json", "trade_sim_data", 1200, 7200, None, 'run_r2_upload "upload-trade-sim-json" 1800 --lock-domain trade_sim_data --lock-wait 1200'),
    ("scripts/r2_upload_async.sh", "upload-index", "index", 600, 7200, None, 'run_r2_upload "upload-index" 900 --lock-domain index --lock-wait 600'),
    ("scripts/r2_upload_async.sh", "upload-etf-hist", "etf", 600, 7200, None, 'run_r2_upload "upload-etf-hist" 900 --lock-domain etf --lock-wait 600'),
    ("scripts/r2_upload_async.sh", "upload-accum-nav", "accum_nav", 600, 7200, None, 'run_r2_upload "upload-accum-nav" 900 --lock-domain accum_nav --lock-wait 600'),
    ("scripts/r2_upload_async.sh", "upload-industry", "industry", 600, 7200, None, 'run_r2_upload "upload-industry" 900 --lock-domain industry --lock-wait 600'),
    ("scripts/r2_upload_async.sh", "upload-public-fund", "public_fund", 600, 7200, None, 'run_r2_upload "upload-public-fund" 900 --lock-domain public_fund --lock-wait 600'),
    ("scripts/r2_upload_async.sh", "upload-etf-score", "etf_score", 600, 7200, None, 'run_r2_upload "upload-etf-score" 900 --lock-domain etf_score --lock-wait 600'),
    ("scripts/r2_upload_async.sh", "upload-data-large", "data", 600, 7200, None, 'run_r2_upload "upload-data-large" --lock-domain data --lock-wait 600'),
    ("scripts/r2_upload_async.sh", "upload-kelly-parts", "kelly_parts", 600, 7200, None, 'run_r2_upload "upload-kelly-parts" --lock-domain kelly_parts --lock-wait 600'),
    ("scripts/r2_upload_async.sh", "upload-kelly-parts-sdc", "kelly_sdc", 600, 7200, None, 'run_r2_upload "upload-kelly-parts-sdc" --lock-domain kelly_sdc --lock-wait 600'),
    ("scripts/r2_upload_async.sh", "upload-all-data", "data", 600, 7200, None, 'run_r2_upload "upload-all-data" 900 --lock-domain data --lock-wait 600'),
    ("scripts/r2_upload_async.sh", "upload-kelly-snapshots", "kelly_snapshots", 600, 7200, None, 'run_r2_upload "upload-kelly-snapshots" 900 --lock-domain kelly_snapshots --lock-wait 600'),
    ("scripts/r2_upload_async.sh", "upload-feed", "data", 600, 7200, None, 'run_r2_upload "upload-feed" 900 --lock-domain data --lock-wait 600'),
    ("scripts/r2_upload_async.sh", "verify-r2(只读对账)", None, 6000, 7200, None, 'run_r2_upload "verify-r2" 7200 --lock-wait 6000'),
    ("scripts/r2_upload_async.sh", "purge-low-freq", None, 600, 7200, None, 'run_r2_upload "purge-low-freq" 900 --lock-wait 600'),
    # ── 定时链 shell 调用方 ──
    ("scripts/s06_snapshot.sh", "s06 state(顶层 data)", "data", 600, 900, "trade-s06-snapshot.service", 'R2_UPLOAD_LOCK_DOMAIN=data R2_UPLOAD_LOCK_TIMEOUT=600'),
    ("scripts/s06_snapshot.sh", "kelly snapshots", "kelly_snapshots", 600, 900, "trade-s06-snapshot.service", 'R2_UPLOAD_LOCK_DOMAIN=kelly_snapshots R2_UPLOAD_LOCK_TIMEOUT=600'),
    # #364: 两步各自内层工作预算 + 外层 shell run_to(unit TimeoutStartSec=infinity ⇒ 外层墙在 shell)。
    ("scripts/turnover_backfill.sh", "intraday(外层 run_to 2460 / 工作 600)", "data", 1800, 2460, "trade-turnover-backfill.service", 'R2_UPLOAD_WORK_TIMEOUT="$R2_WORK_BUDGET_INTRADAY" R2_UPLOAD_LOCK_DOMAIN=data'),
    ("scripts/turnover_backfill.sh", "data-large(外层 run_to 4260 / 工作 2400)", "data", 1800, 4260, "trade-turnover-backfill.service", 'R2_UPLOAD_WORK_TIMEOUT="$R2_WORK_BUDGET" R2_UPLOAD_LOCK_DOMAIN=data'),
    ("scripts/intraday_snapshot.sh", "index(盘中 :157)", "index", 600, None, "trade-intraday-snapshot.service", 'R2_UPLOAD_LOCK_DOMAIN=index R2_UPLOAD_LOCK_TIMEOUT=600'),
    ("scripts/intraday_snapshot.sh", "intraday + schedule_stats(盘中 :170/:232)", "data", 600, None, "trade-intraday-snapshot.service", 'R2_UPLOAD_LOCK_DOMAIN=data R2_UPLOAD_LOCK_TIMEOUT=600'),
    ("scripts/intraday_snapshot.sh", "signal_kelly_trades_intraday.json(盘中 :180)", "data", 600, None, "trade-intraday-snapshot.service", 'upload-data-files signal_kelly_trades_intraday.json'),
    ("scripts/update_lab.sh", "lab", "lab", 600, None, "trade-lab-auto.service", 'R2_UPLOAD_LOCK_DOMAIN=lab R2_UPLOAD_LOCK_TIMEOUT=600'),
    ("scripts/update_lab.sh", "trade_sim_data", "trade_sim_data", 600, None, "trade-lab-auto.service", 'R2_UPLOAD_LOCK_DOMAIN=trade_sim_data R2_UPLOAD_LOCK_TIMEOUT=600'),
    ("scripts/update_lab.sh", "lab_*.json(顶层 data)", "data", 600, None, "trade-lab-auto.service", 'R2_UPLOAD_LOCK_DOMAIN=data R2_UPLOAD_LOCK_TIMEOUT=600'),
    ("scripts/gold_night.sh", "gold 数据", "data", 900, None, "trade-gold-night.service", 'R2_UPLOAD_LOCK_DOMAIN=data R2_UPLOAD_LOCK_TIMEOUT=900'),
    ("scripts/etf_national_team_backfill.sh", "etf hist", "etf", 900, None, "trade-etf-national-team.service", 'R2_UPLOAD_LOCK_DOMAIN=etf R2_UPLOAD_LOCK_TIMEOUT=900'),
    ("scripts/fund_nav_upload_async.sh", "fund nav", "fund_nav", 1800, None, None, 'R2_UPLOAD_LOCK_DOMAIN=fund_nav R2_UPLOAD_LOCK_TIMEOUT=1800'),
    ("scripts/pf_score_daily.sh", "fund score", "fund_score", 400, None, "trade-pf-score-daily.service", 'R2_UPLOAD_LOCK_DOMAIN=fund_score R2_UPLOAD_LOCK_TIMEOUT=400'),
    ("scripts/pf_score_weekly.sh", "fund score", "fund_score", 1800, None, "trade-pf-score-weekly.service", 'R2_UPLOAD_LOCK_DOMAIN=fund_score R2_UPLOAD_LOCK_TIMEOUT=1800'),
    ("scripts/backup_db.sh", "db 私有桶", "backup_db", 9000, None, "trade-backup-db.service", 'R2_UPLOAD_LOCK_DOMAIN=backup_db R2_UPLOAD_LOCK_TIMEOUT=9000'),
    ("scripts/staticdata_backup_async.sh", "large json 私有桶", "large_json", 3000, None, None, 'R2_UPLOAD_LOCK_DOMAIN=large_json R2_UPLOAD_LOCK_TIMEOUT=3000'),
    ("scripts/migrate_large_json_out_of_git.sh", "large json 迁移", "large_json", 3000, None, None, 'R2_UPLOAD_LOCK_DOMAIN=large_json R2_UPLOAD_LOCK_TIMEOUT=3000'),
    ("scripts/update_all.sh", "alert 预警数据", "data", 300, None, "trade-update-all.service", 'R2_UPLOAD_LOCK_DOMAIN=data R2_UPLOAD_LOCK_TIMEOUT=300'),
    ("scripts/update_all.sh", "etf score", "etf_score", 600, None, "trade-update-all.service", 'R2_UPLOAD_LOCK_DOMAIN=etf_score R2_UPLOAD_LOCK_TIMEOUT=600'),
    ("scripts/update_all.sh", "fund score", "fund_score", 600, None, "trade-update-all.service", 'R2_UPLOAD_LOCK_DOMAIN=fund_score R2_UPLOAD_LOCK_TIMEOUT=600'),
    ("scripts/kelly_intraday_rerun.sh", "盘中增量档", "data", 400, None, "trade-kelly-intraday-rerun.service", 'R2_UPLOAD_LOCK_DOMAIN=data R2_UPLOAD_LOCK_TIMEOUT=400'),
    ("scripts/push_schedule_stats.sh", "schedule_stats", "data", 120, None, None, 'R2_UPLOAD_LOCK_DOMAIN=data R2_UPLOAD_LOCK_TIMEOUT=120'),
    # ── Python 调用方(subprocess timeout = 内层预算) ──
    ("scripts/fetch_news.py", "news_digest 归档", "data", 120, 180, "trade-fetch-news.service", 'R2_UPLOAD_LOCK_TIMEOUT"] = "120"'),
    ("scripts/gen_daily_brief.py", "daily brief", "data", 80, 120, "trade-daily-brief.service", 'R2_UPLOAD_LOCK_TIMEOUT"] = "80"'),
    ("scripts/nextday_plan_generator.py", "次日买入计划", "data", 320, 480, "trade-nextday-plan.service", 'R2_UPLOAD_LOCK_TIMEOUT"] = "320"'),
    ("scripts/nextday_gap_check.py", "次日缺口检查", "data", 200, 300, "trade-nextday-gap-check.service", 'R2_UPLOAD_LOCK_TIMEOUT"] = "200"'),
    ("scripts/overfit_monitor.py", "overfit_monitor.json", "data", 240, 960, "trade-overfit-monitor.service", 'R2_UPLOAD_LOCK_TIMEOUT"] = "240"'),
    ("scripts/fapi_bj_width_export.py", "fapi 宽度导出", "data", 600, 900, "trade-fapi-daily.service", 'R2_UPLOAD_LOCK_TIMEOUT"] = "600"'),
    ("scripts/backup_claude_self.sh", "claude 自我备份(私有桶)", "claude_backup", 900, None, None, 'R2_UPLOAD_LOCK_DOMAIN=claude_backup R2_UPLOAD_LOCK_TIMEOUT=900'),
]

# 提到 upload_r2.py 但**不是上传调用方**的文件(注释/文档字符串/自身实现), 必须写明理由。
KNOWN_NON_CALLERS = {
    "scripts/upload_r2.py": "自身实现",
    "scripts/deploy.sh": "仅注释引用(2026-10-04 起 R2 段已拆出 r2_upload_async.sh), 无 upload_r2.py 执行",
    "scripts/r2_lock_gradient_audit.py": "本审计脚本(只读扫描, 不调用)",
}

# 已知「内层 > 外层」旧账(本单不改调度/不抬 outer, 只登记; 锚点可反查)。
KNOWN_INNER_OVER_OUTER = {
    ("scripts/overfit_monitor.py", "trade-overfit-monitor.service"):
        "#223④(2026-10-06) 本层 960 > 外层 360 为既有倒置, 已由运行时梯度守卫兜底; 抬外层属另案",
}

# 已知「变量形式的域声明」= 静态不可解析, 必须逐条给出明确处置(不许静默放过)。
# key = (文件, 行内可辨识标记子串), value = 处置理由。
KNOWN_VARIABLE_FORMS = {
    ("scripts/r2_upload_async.sh", '${_lock_domain:+R2_UPLOAD_LOCK_DOMAIN="$_lock_domain"}'):
        "转发包装层的 pass-through 行: 域由各 run_r2_upload 调用的 --lock-domain <字面量> 决定, "
        "逐通道已在 SITES 登记(本行只是把解析结果注入子进程 env, 不单独代表某个调用点)",
}

# 域声明出现的位置: shell 的字面量赋值 / Python 的 env 字典赋值(2026-10-28 返工,R3 补盲:
# 原审计只扫 shell 同行字面量 ⇒ 新增 Python 调用方 / 变量形式全靠人眼)。
_SHELL_DOMAIN_LITERAL = re.compile(r"""R2_UPLOAD_LOCK_DOMAIN=["']?([a-z0-9_-]+)["']?\s""")
_PY_DOMAIN_LITERAL = re.compile(r'''R2_UPLOAD_LOCK_DOMAIN"\]\s*=\s*"([a-z0-9_-]+)"''')
_SHELL_DOMAIN_VARIABLE = re.compile(r"""(?:R2_UPLOAD_LOCK_DOMAIN=["']?\$|--lock-domain\s+["']?\$)""")


def _parse_outer_timeouts() -> dict[str, int]:
    if not SNAPSHOT.exists():
        return {}
    text = SNAPSHOT.read_text(encoding="utf-8", errors="replace")
    out: dict[str, int] = {}
    for block in re.split(r"^@@@FILE:", text, flags=re.M)[1:]:
        name = block.splitlines()[0].strip()
        m = re.search(r"^TimeoutStartSec=(\S+)", block, flags=re.M)
        if not name.endswith(".service"):
            continue
        if not m:
            out[name] = 0
            continue
        try:
            out[name] = int(m.group(1))
        except ValueError:
            out[name] = 0
    return out


_WRITE_INVOKE = re.compile(
    r"""upload_r2\.py["']?\s+(upload-data-files|upload-data-large|upload-all-data|upload-lab|"""
    r"""upload-trade-sim-json|upload-trade-sim|upload-index|upload-etf-hist|upload-fund-nav|"""
    r"""upload-accum-nav|upload-industry|upload-public-fund|upload-offshore-fund|"""
    r"""upload-fund-score|upload-etf-score|upload-kelly-parts-sdc|upload-kelly-parts|"""
    r"""upload-kelly-snapshots|upload-intraday|upload-db|upload-large-json|"""
    r"""upload-claude-backup|upload-decommissioned|verify-r2|purge-low-freq)\b""")


def _upload_callers() -> set[str]:
    """扫 scripts/ 顶层 shell 脚本里**真实执行**的上传调用 = 调用方候选集。

    只认「非注释行 + 与 upload_r2.py 同一行的写命令」; 注释/告警文案里的「手动补刷」示例
    不算调用方(它们不执行)。Python 调用方在 SITES 表逐个登记(调用点跨行, 静态同行匹配不可靠)。
    """
    found = set()
    for p in sorted((REPO / "scripts").glob("*.sh")):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            st = line.strip()
            if st.startswith("#") or "手动" in line or "补刷" in line:
                continue
            if _WRITE_INVOKE.search(line):
                found.add(f"scripts/{p.name}")
                break
    return found


def _python_caller_domains() -> dict[str, set[str]]:
    """扫 scripts/*.py 的 Python 调用方: 文件 → 它声明过的域集合。

    审查实证(2026-10-28): 原审计只扫 shell 同行字面量, 新增一个 Python 调用方(或把字面量改成
    变量)不会被发现 ⇒ 漏改调用方回落全局锁却审计全绿。这里按「env 字典赋值」收集, 与 SITES 对账。
    排除本审计脚本自身与 upload_r2.py(实现侧)。
    """
    found: dict[str, set[str]] = {}
    for p in sorted((REPO / "scripts").glob("*.py")):
        rel = f"scripts/{p.name}"
        if rel in ("scripts/upload_r2.py", "scripts/r2_lock_gradient_audit.py",
                   "scripts/r2_lock_paths.py", "scripts/r2_lock_probe.py"):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        domains = set(_PY_DOMAIN_LITERAL.findall(text))
        if domains:
            found[rel] = domains
    return found


def _shell_domain_literals() -> list[tuple[str, str]]:
    """扫 scripts/*.sh 的**字面量**域声明, 返回 [(文件, 域), ...](去重)。

    用途: 与 SITES 登记对账 —— 同一脚本里写了两处不同域、SITES 只登记了一行时, 原审计会因为
    「标记字符串存在」而 PASS(实证: update_all.sh 的 etf_score/fund_score 两处曾合并成一行,
    fund_score 那处无人核对)。变量形式不在此列(由 `_shell_variable_forms` 单独给处置)。
    """
    out = set()
    for p in sorted((REPO / "scripts").glob("*.sh")):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            st = line.strip()
            if st.startswith("#"):
                continue
            for d in _SHELL_DOMAIN_LITERAL.findall(line):
                out.add((f"scripts/{p.name}", d))
    return sorted(out)


def _shell_variable_forms() -> list[tuple[str, str]]:
    """扫 scripts/*.sh 里**静态不可解析的域声明**(变量形式), 返回 [(文件, 行内容), ...]。

    注释行不算(不执行)。每一处都要有明确处置: 命中 KNOWN_VARIABLE_FORMS ⇒ 已登记; 否则
    列入「人工确认清单」并 FAIL(不许静默放过 —— 变量形式既可能解析成合法域, 也可能拼错)。
    """
    out = []
    for p in sorted((REPO / "scripts").glob("*.sh")):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            st = line.strip()
            if st.startswith("#"):
                continue
            if _SHELL_DOMAIN_VARIABLE.search(line):
                out.append((f"scripts/{p.name}", line.strip()))
    return out


def audit() -> tuple[list[dict], list[str]]:
    rows, errs = [], []
    outer = _parse_outer_timeouts()
    cache: dict[str, str] = {}
    for owner, site, domain, lock_wait, inner, unit, marker in SITES:
        row = {"owner": owner, "site": site, "domain": domain, "lock_wait": lock_wait,
               "inner": inner, "unit": unit, "outer": (outer.get(unit, 0) if unit else 0),
               "status": "PASS", "note": ""}
        if owner not in cache:
            cache[owner] = (REPO / owner).read_text(encoding="utf-8", errors="replace")
        text = cache[owner]
        # ① 显式声明域 / 非上传命令显式声明「无域 + 锁等待」
        if marker not in text:
            row["status"] = "FAIL"
            row["note"] = "脚本内找不到显式声明(域/锁等待标记)"
        elif domain is not None and not any(
                s in text for s in (f"R2_UPLOAD_LOCK_DOMAIN={domain}",
                                    f'R2_UPLOAD_LOCK_DOMAIN"] = "{domain}"',
                                    f"--lock-domain {domain}")):
            row["status"] = "FAIL"
            row["note"] = "声明域与登记表不一致"
        # ② 锁等待 < 内层预算
        if row["status"] == "PASS" and inner:
            if lock_wait >= inner:
                row["status"] = "FAIL"
                row["note"] = f"锁等待 {lock_wait}s ≥ 内层 {inner}s(梯度倒置)"
        # ③ 内层 < 外层 unit(0=无界, 不适用)
        if row["status"] == "PASS" and unit and row["outer"] and inner:
            if inner >= row["outer"]:
                key = (owner, unit)
                if key in KNOWN_INNER_OVER_OUTER:
                    row["status"] = "WAIVED"
                    row["note"] = KNOWN_INNER_OVER_OUTER[key]
                else:
                    row["status"] = "FAIL"
                    row["note"] = f"内层 {inner}s ≥ 外层 {unit} {row['outer']}s(梯度倒置)"
        if row["status"] == "PASS" and unit and not row["outer"] and unit not in outer:
            row["status"] = "WAIVED"
            row["note"] = f"外层 unit {unit} 不在快照(0/未登记 ⇒ 无界)"
        if domain is not None and domain not in DOMAINS:
            row["status"] = "FAIL"
            row["note"] = f"域 {domain} 不在域登记表"
        rows.append(row)
    # 覆盖性: 所有调用方必须有登记(或豁免), 防漏改调用方变成「未声明域」
    covered = {r["owner"] for r in rows}
    for caller in _upload_callers():
        if caller in covered or caller in KNOWN_NON_CALLERS:
            continue
        rows.append({"owner": caller, "site": "?", "domain": None, "lock_wait": 0,
                     "inner": None, "unit": None, "outer": 0, "status": "FAIL",
                     "note": "上传调用方未登记域/锁等待(漏改 ⇒ 回落全局锁)"})
    # 实现侧契约: 域锁 + 全局 SH 屏障 + 未声明回落全局 + 白名单回落
    ur = UR_PY.read_text(encoding="utf-8", errors="replace")
    for needle, why in [
        ('_LOCK_DOMAIN_ENV = "R2_UPLOAD_LOCK_DOMAIN"', "域 env 常量丢失"),
        ("_domain_upload_lock_path", "域锁路径派生丢失"),
        ("fcntl.LOCK_SH", "全局 SH 屏障丢失(未声明写者将无法挡住域写者)"),
        ("lock_plan = [(lock_path, fcntl.LOCK_EX)]", "未声明域回落全局 EX 丢失"),
        ("_rlp.LOCK_DOMAINS", "域名白名单校验丢失(打错域名会自建新锁、静默失去同 key 互斥)"),
        ("return _rlp.domain_lock_path(domain)", "域锁路径未走单一事实源(手抄第二份必然漂移)"),
    ]:
        if needle not in ur:
            errs.append(f"upload_r2.py 契约缺失: {why}(找不到 {needle!r})")
    if f'_LOCK_DOMAIN_ENV = "{DOMAIN_ENV}"' not in ur:
        errs.append(f"upload_r2.py 的 _LOCK_DOMAIN_ENV 与 r2_lock_paths.DOMAIN_ENV({DOMAIN_ENV!r})不同值")

    # 域名登记表 ↔ 白名单双向一致(单一事实源 = r2_lock_paths.LOCK_DOMAINS)
    missing = sorted(LOCK_DOMAINS - set(DOMAINS))
    extra = sorted(set(DOMAINS) - LOCK_DOMAINS)
    if missing:
        errs.append(f"域登记表缺白名单域名 {missing}(补本表说明文字; 白名单已承认但审计无对象 key 依据)")
    if extra:
        errs.append(f"域登记表含白名单外域名 {extra}(upload_r2 会回落全局锁, 分域形同虚设)")

    # Python 调用方补盲: 声明了域却未登记 / 声明域与登记不一致
    registered: dict[str, set[str]] = {}
    for owner, _site, domain, *_rest in SITES:
        if domain:
            registered.setdefault(owner, set()).add(domain)
    for owner, domains in _python_caller_domains().items():
        if owner not in registered:
            errs.append(f"{owner}: Python 调用方声明了域 {sorted(domains)} 但未在 SITES 登记"
                        f"(新增调用方漏登记 ⇒ 域/梯度无人核对)")
            continue
        stranger = sorted(domains - registered[owner])
        if stranger:
            errs.append(f"{owner}: 声明域 {stranger} 与 SITES 登记 {sorted(registered[owner])} 不一致")

    # shell 字面量域 ↔ SITES 登记对账(同一脚本多域只登记一行 = 漏核对)
    for owner, domain in _shell_domain_literals():
        if domain not in LOCK_DOMAINS:
            errs.append(f"{owner}: 脚本内声明了未登记域名 {domain!r}(会回落全局锁)")
        elif domain not in registered.get(owner, set()):
            errs.append(f"{owner}: 脚本内声明域 {domain!r} 无对应 SITES 登记行"
                        f"(该调用点的锁等待/梯度无人核对)")

    # shell 变量形式: 逐条明确处置(已登记给理由 / 未登记进人工确认清单 + FAIL)
    for owner, line in _shell_variable_forms():
        if any(owner == k[0] and k[1] in line for k in KNOWN_VARIABLE_FORMS):
            continue
        errs.append(f"{owner}: 域声明是变量形式, 静态不可解析 ⇒ 人工确认清单: {line[:140]}")

    # 诊断探针完整性(R1): 调用方必须显式要求带域锁, 否则分域后超时诊断会指错文件
    probe = PROBE_PY.read_text(encoding="utf-8", errors="replace")
    for needle, why in [
        ("import r2_lock_paths as _rlp", "探针未复用锁路径单一事实源(手抄第二份会漏域锁)"),
        ("_rlp.lock_endpoints(include_domains=include_domains)", "探针未把域锁纳入探测集"),
    ]:
        if needle not in probe:
            errs.append(f"r2_lock_probe.py 契约缺失: {why}(找不到 {needle!r})")
    for p in sorted((REPO / "scripts").glob("*.py")):
        if p.name in ("r2_lock_probe.py", "r2_lock_gradient_audit.py"):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            st = line.strip()
            if st.startswith("def ") or "lock_paths_from_env(" not in line:
                continue
            if "include_domains=True" not in line:
                errs.append(f"scripts/{p.name}: 诊断未探测域锁(缺 include_domains=True): {st[:140]}")
    for r in rows:
        if r["status"] == "FAIL":
            errs.append(f"{r['owner']} [{r['site']}]: {r['note']}")
    return rows, errs


def _fmt(rows: list[dict]) -> str:
    head = f"{'脚本':34} {'站点':26} {'域':14} {'锁等待':>6} {'内层':>6} {'外层':>6} 状态"
    lines = [head, "-" * len(head)]
    for r in rows:
        inner = "-" if not r["inner"] else str(r["inner"])
        outer = str(r["outer"]) if r["unit"] else "-"
        lines.append(f"{r['owner']:34} {r['site']:26} {str(r['domain'] or '-'):14} "
                     f"{r['lock_wait']:>6} {inner:>6} {outer:>6} {r['status']}")
        if r["note"]:
            lines.append(f"    ↳ {r['note']}")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    rows, errs = audit()
    if "--json" in argv:
        print(json.dumps({"rows": rows, "errors": errs}, ensure_ascii=False, indent=2))
        return 1 if errs else 0
    print("== R2 上传锁域 + 超时梯度审计(只读) ==")
    print(_fmt(rows))
    manual = _shell_variable_forms()
    print("\n-- 人工确认清单(变量形式的域声明: 静态不可解析, 逐条给处置) --")
    if not manual:
        print("  (无)")
    for owner, line in manual:
        known = next((v for k, v in KNOWN_VARIABLE_FORMS.items()
                      if owner == k[0] and k[1] in line), None)
        print(f"  {'已登记' if known else '待确认'} {owner}: {line[:140]}")
        if known:
            print(f"      ↳ {known}")
    bad = [r for r in rows if r["status"] == "FAIL"]
    waived = [r for r in rows if r["status"] == "WAIVED"]
    print(f"\n合计 {len(rows)} 个调用点: PASS={len(rows) - len(bad) - len(waived)} "
          f"WAIVED={len(waived)} FAIL={len(bad)}")
    if errs:
        print("\nFAIL 明细:")
        for e in errs:
            print(f"  ✗ {e}")
        return 1
    print("PASS: 全部调用方已显式声明域/锁等待上限, 且锁等待 < 内层 < 外层(或有豁免留痕)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))