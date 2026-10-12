#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kelly_intraday_gate_decider.py — 凯利盘中「数据就绪闸」判定器(#254 方案 A)。

设计来源(逐字施工图):
  docs/ops/kelly-intraday-gate-relax-design-20261012.md
  docs/ops/kelly-intraday-rerun-exit5-20261012.md
冻结参数(§23.7 冻结: 实施即冻结, 后续变更须用户确认):
  R(单日缺口比例阈值)=15% / D(累计运行日阈值)=5 / 豁免 TTL=60 自然日
  取不到类(unfetchable)豁免 TTL=14 自然日且**永不静默** / band 地板 k>=3 无条件 WARN + r>=50% 超带必 WARN

结构 = A+B 混合(逐码判据/豁免为主闸 + 日级 (R,D) 粗闸兜底):
  P0 逐码分类(绝对前置)  → P1 豁免查表(overlay) → P2 单日比例闸 → P3 累计天数闸
  分类 > 豁免 > 单日 > 累计;单日大缺口(ratio>R)永远 abort(整轮跳过, exit 5)。

ratio 口径(冻结): 分子 = 未豁免且 class=unfetchable 的码数;分母 = 当轮 target 数(含零成交豁免码)。
  ⇒ 零成交类(zero_volume)不推高 ratio(这正是放宽的落点);只有「取不到(unfetchable)」才计入。

本模块**单一事实源**:豁免匹配/五维自动失效/verdict 计算既被
`signal_kelly_backtest.compute_intraday` 复用(mutate=False, 只读算 verdict),也被本 CLI 使用
(mutate=True, 落状态 + 发告警),两处同一函数 ⇒ 零漂移(§5.4⑦ 精神)。

用法:
  python scripts/kelly_intraday_gate_decider.py --report <path> --commit           # 落状态+发告警, 返回 gate 退出码(0/5)
  python scripts/kelly_intraday_gate_decider.py --report <path> --print exit_code  # 只读(不落状态/不发告警)
  python scripts/kelly_intraday_gate_decider.py --report <path> --print tier
  python scripts/kelly_intraday_gate_decider.py --report <path> --dry-run          # 只打印决定, 不发通知(自测)

状态: data/alerts/kelly_intraday_gate_state.json(flock + tmp/rename 原子写, 仿 alert_ack.py)
      + 追加式 data/alerts/kelly_intraday_gate_ledger.jsonl
fail-safe: 状态读失败 → 当无豁免(偏告警) + 独立 WARN(dedup 24h)。
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).absolute().parent.parent
STATE_PATH = REPO / "data" / "alerts" / "kelly_intraday_gate_state.json"
LEDGER_PATH = REPO / "data" / "alerts" / "kelly_intraday_gate_ledger.jsonl"
LOCK_PATH = REPO / "data" / "alerts" / ".kelly_intraday_gate.lock"
REPORT_PATH = REPO / "data" / "kelly_intraday_gate_report.json"
NOTIFY_PY = REPO / "scripts" / "notify.py"

# ── 冻结参数(§23.7) ──────────────────────────────────────────────────────────
R_THRESHOLD = 0.15            # 单日缺口比例阈值(未豁免 unfetchable / target)
D_THRESHOLD = 5               # 累计运行日阈值(容忍带连续天)
TTL_DAYS = 60                 # 零成交类豁免 TTL(自然日)
UNFETCHABLE_TTL_DAYS = 14     # 取不到类豁免 TTL(自然日, 永不静默)
BAND_STRIKES_MAX = 2          # 量级超带连续次数 → invalidated:band
BAND_FLOOR_MIN_CODES = 3      # band 地板: k>=3 无条件 WARN
BAND_FLOOR_RATIO = 0.50       # band 地板: r>=50% 超带必 WARN(防 band_cap 吸收过大)
UNFETCHABLE_DEDUP_WINDOW = 7 * 24 * 3600   # 取不到类豁免命中 → 降级 WARN, 7 天长窗去重
ABORT_DEDUP_KEY = "kelly_intraday_rerun_fail"
ABORT_DEDUP_WINDOW = 1800     # 与 2026-10-12 降噪一致(exit5 → --tier warning)
STATE_READ_FAIL_DEDUP_WINDOW = 24 * 3600

EMPTY_STATE = {"version": 1, "exemptions": [], "tolerate_streak": {"count": 0, "first_date": None, "codes": []}}


# ════════════════════════════════════════════════════════════════════════════
# 状态 I/O(flock + tmp/rename 原子写)
# ════════════════════════════════════════════════════════════════════════════
def load_state(path: Path | None = None):
    """读状态。返回 (state, ok)。读/解析失败 → (EMPTY_STATE, False)(fail-safe: 当无豁免, 偏告警)。"""
    p = Path(path) if path is not None else STATE_PATH
    if not p.exists():
        return dict(EMPTY_STATE), True
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(doc, dict):
            return dict(EMPTY_STATE), False
        doc.setdefault("exemptions", [])
        doc.setdefault("tolerate_streak", {"count": 0, "first_date": None, "codes": []})
        return doc, True
    except Exception:
        return dict(EMPTY_STATE), False


def save_state_atomic(state: dict, path: Path | None = None) -> None:
    p = Path(path) if path is not None else STATE_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(p)


def append_ledger(entry: dict, path: Path | None = None) -> None:
    p = Path(path) if path is not None else LEDGER_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def write_report(report: dict, path: Path | None = None) -> None:
    """原子写机器的可读 gate report(tmp + rename, 防半截文件被 decider 读走)。"""
    p = Path(path) if path is not None else REPORT_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(p)


# ════════════════════════════════════════════════════════════════════════════
# 豁免匹配 + 五维自动失效
# ════════════════════════════════════════════════════════════════════════════
def _parse_ts(s):
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(s), fmt)
        except ValueError:
            continue
    return None


def _src_equal(a: dict, b: dict) -> bool:
    if not isinstance(a, dict):
        return False
    return (bool(a.get("main_source_ok")) == bool(b.get("main_source_ok"))
            and bool(a.get("fallback_used")) == bool(b.get("fallback_used")))


def _ttl_days_of(class_by_code: dict) -> int:
    """含取不到类 → 14 天短 TTL;纯零成交类 → 60 天。"""
    return UNFETCHABLE_TTL_DAYS if any(v == "unfetchable" for v in class_by_code.values()) else TTL_DAYS


def _ttl_expired(ex: dict, now: datetime) -> bool:
    ts = _parse_ts(ex.get("confirmed_at"))
    if ts is None:
        return True
    ttl = int(ex.get("ttl_days") or TTL_DAYS)
    return (now - ts).days > ttl


def match_exemption(ex: dict, face: dict, now: datetime):
    """五维判定一个 active 豁免是否命中当前 face。

    返回 (hit: bool, reason: str):
      hit=True,  reason="hit"               → 完整命中(子集+类别+源+band+未过期)
      hit=False, reason="ttl"               → TTL 到期
      hit=False, reason="source"            → 源上下文变化
      hit=False, reason="class"             → 覆盖码类别变化
      hit=False, reason="band"              → r_band > band_cap
      hit=False, reason="expand"            → 集合新增成员(F.codes ⊄ E.codes, 有交集)
    """
    if ex.get("status") != "active":
        return False, "inactive"
    if _ttl_expired(ex, now):
        return False, "ttl"
    ex_codes = set(str(c) for c in ex.get("codes", []))
    face_codes = set(face["codes"])
    if not (ex_codes & face_codes):
        return False, "unrelated"
    if not _src_equal(ex.get("src_ctx"), face["src_ctx"]):
        return False, "source"
    ex_cls = ex.get("class_by_code") or {}
    for c in (ex_codes & face_codes):
        if face["class_by_code"].get(c) != ex_cls.get(c):
            return False, "class"
    if not face_codes <= ex_codes:
        return False, "expand"
    if face["r_band"] > float(ex.get("band_cap") or R_THRESHOLD) + 1e-9:
        return False, "band"
    return True, "hit"


# ════════════════════════════════════════════════════════════════════════════
# 核心判定(P0 分类 → P1 豁免 → P2 单日闸 → P3 累计闸)
# ════════════════════════════════════════════════════════════════════════════
def evaluate(report: dict, state: dict, now: datetime, mutate: bool = False,
             state_ok: bool = True) -> dict:
    """读 report + state → 返回 decision dict(不写盘)。

    report 冻结字段: run_date/target_count/missing_count/ratio/main_source_ok/fallback_used/
                     codes[{code,class,evidence,ts}]/exempted/verdict
    decision: exit_code(0/5) / tier(silent|warning) / reason / exempted / unfetchable_exempted /
              zero_volume_exempted / ratio / r_band / streak / forced_warn / invalidations / expansions
    mutate=True 时**就地更新** state(命中 hits / band_strikes / 失效 status / tolerate_streak)。
    """
    target_count = int(report.get("target_count") or 0)
    codes = report.get("codes") or []
    src_ctx = {"main_source_ok": bool(report.get("main_source_ok")),
               "fallback_used": bool(report.get("fallback_used"))}
    face_codes = [str(c.get("code")) for c in codes]
    class_by_code = {str(c.get("code")): c.get("class") for c in codes}
    unfetchable_all = [c for c in face_codes if class_by_code.get(c) == "unfetchable"]
    # band 量级 = 未豁免 unfetchable / target(与确认时同口径)
    r_band = (len(unfetchable_all) / target_count) if target_count else 0.0
    face = {"codes": face_codes, "class_by_code": class_by_code, "src_ctx": src_ctx, "r_band": r_band}

    exempted: list = []
    uncovered: list = []
    forced_warn = False
    invalidations: list = []
    expansions: list = []
    for ex in state.get("exemptions", []):
        if ex.get("status") != "active":
            continue
        hit, reason = match_exemption(ex, face, now)
        if hit:
            exempted = sorted(set(exempted) | set(face_codes))
            if mutate:
                ex["hits"] = int(ex.get("hits") or 0) + 1
                ex["last_hit"] = now.strftime("%Y-%m-%d %H:%M:%S")
        elif reason in ("ttl", "source", "class"):
            # 立即失效(重命名状态, 保留记录防 whack-a-mole)
            if mutate:
                ex["status"] = f"invalidated:{reason}"
                ex["invalidated_at"] = now.strftime("%Y-%m-%d %H:%M:%S")
            invalidations.append({"id": ex.get("id"), "reason": reason})
        elif reason == "band":
            strikes = int(ex.get("band_strikes") or 0) + 1
            if mutate:
                ex["band_strikes"] = strikes
                ex["last_band_strike"] = now.strftime("%Y-%m-%d %H:%M:%S")
                if strikes >= BAND_STRIKES_MAX:
                    ex["status"] = "invalidated:band"
                    ex["invalidated_at"] = now.strftime("%Y-%m-%d %H:%M:%S")
            invalidations.append({"id": ex.get("id"), "reason": "band",
                                  "strikes": strikes,
                                  "invalidated": strikes >= BAND_STRIKES_MAX})
            forced_warn = True
        elif reason == "expand":
            # 曾命中的面出现新成员 → 当日强制至少 WARN 一次(附扩面命令), 不等 D 天
            expansions.append({"id": ex.get("id"), "face_codes": sorted(face_codes),
                               "ex_codes": sorted(str(c) for c in ex.get("codes", []))})
            forced_warn = True

    # band 地板(与 band 解耦): k>=3 无条件 WARN / r>=50% 超带必 WARN
    if len(unfetchable_all) >= BAND_FLOOR_MIN_CODES or r_band >= BAND_FLOOR_RATIO:
        forced_warn = True

    # ratio 口径(冻结): 未豁免且 unfetchable / target_count(含零成交豁免码)
    unfetchable_not_exempted = [c for c in unfetchable_all if c not in set(exempted)]
    ratio = (len(unfetchable_not_exempted) / target_count) if target_count else 0.0

    # P2 单日闸
    if target_count == 0:
        verdict = "pass"
    elif ratio > R_THRESHOLD + 1e-9:
        verdict = "abort"
    elif int(report.get("missing_count") or len(face_codes)) > 0:
        verdict = "tolerate"
    else:
        verdict = "pass"

    # P3 累计天数闸(容忍带 0<ratio<=R 连续 >=D 个运行日)
    streak_obj = state.setdefault("tolerate_streak", {"count": 0, "first_date": None, "codes": []})
    if 0 < ratio <= R_THRESHOLD + 1e-9:
        new_count = int(streak_obj.get("count") or 0) + 1
        first_date = streak_obj.get("first_date") or report.get("run_date")
    else:
        new_count = 0
        first_date = None
    if mutate:
        streak_obj["count"] = new_count
        streak_obj["first_date"] = first_date
        streak_obj["codes"] = sorted(unfetchable_not_exempted)
    persistent = new_count >= D_THRESHOLD

    # 告警等级
    unfetchable_exempted = sorted(c for c in exempted if class_by_code.get(c) == "unfetchable")
    zero_volume_exempted = sorted(c for c in exempted if class_by_code.get(c) == "zero_volume")
    if verdict == "abort":
        tier, reason = "warning", "abort_ratio_over_R"
    elif unfetchable_exempted:
        tier, reason = "warning", "unfetchable_exempted_never_silent"
    elif persistent:
        tier, reason = "warning", "tolerate_streak_ge_D"
    elif forced_warn:
        tier, reason = "warning", "band_floor_or_expand"
    elif invalidations:
        tier, reason = "warning", "exemption_invalidated_notice"
    elif not state_ok:
        tier, reason = "warning", "state_read_fail_fail_safe"
    else:
        tier, reason = "silent", "zero_volume_or_pass"

    return {
        "verdict": verdict,
        "ratio": round(ratio, 6),
        "r_band": round(r_band, 6),
        "exit_code": 5 if verdict == "abort" else 0,
        "tier": tier,
        "reason": reason,
        "exempted": exempted,
        "unfetchable_exempted": unfetchable_exempted,
        "zero_volume_exempted": zero_volume_exempted,
        "unfetchable_not_exempted": sorted(unfetchable_not_exempted),
        "streak": new_count,
        "persistent": persistent,
        "forced_warn": forced_warn,
        "invalidations": invalidations,
        "expansions": expansions,
        "state_ok": state_ok,
    }


# ════════════════════════════════════════════════════════════════════════════
# 告警文案 + 外发
# ════════════════════════════════════════════════════════════════════════════
def build_alarm(report: dict, dec: dict, backtest_rc: int | None, now: datetime):
    """返回 (subject, body, tier, dedup_key, dedup_window);tier=="silent" 表示不发。"""
    stamp = now.strftime("%m-%d %H:%M")
    if dec["tier"] == "silent":
        return None
    if dec["verdict"] == "abort":
        rc = backtest_rc if backtest_rc is not None else 5
        subject = f"[告警] 凯利盘中增量回测本轮跳过(数据就绪闸 FAIL, 退出码 {rc}) {stamp}"
        body = (f"kelly_intraday_rerun 退出码 {rc}: 数据就绪闸 FAIL"
                f"(未豁免取不到开盘价 {len(dec['unfetchable_not_exempted'])} 只 / target "
                f"{report.get('target_count')}, ratio={dec['ratio']:.1%} > R=15%), 本轮跳过, 留 17:50 全量兜底。"
                f"<br>codes={dec['unfetchable_not_exempted'][:10]}")
        return subject, body, "warning", ABORT_DEDUP_KEY, ABORT_DEDUP_WINDOW
    if dec["reason"] == "unfetchable_exempted_never_silent":
        subject = f"[告警] 凯利盘中增量档已出档(取不到类豁免命中, 降级 WARN) {stamp}"
        body = (f"凯利盘中增量档已按放宽规则出档(ratio={dec['ratio']:.1%} <= R=15%), 但命中"
                f"「取不到类」豁免(永不静默): {dec['unfetchable_exempted']}。"
                f"<br>详见 gate report: data/kelly_intraday_gate_report.json")
        return subject, body, "warning", "kelly_intraday_gate_unfetchable_exempted", UNFETCHABLE_DEDUP_WINDOW
    if dec["reason"] == "tolerate_streak_ge_D":
        subject = f"[告警] 凯利盘中增量档容忍带连续 >= {D_THRESHOLD} 运行日 {stamp}"
        body = (f"容忍带(0<ratio<=R)已连续 {dec['streak']} 个运行日未清零(>=D={D_THRESHOLD}), "
                f"ratio={dec['ratio']:.1%}。(仅通知, 不回溯阻断)")
        return subject, body, "warning", "kelly_intraday_gate_tolerate_streak_for_streak", 0
    if dec["reason"] == "band_floor_or_expand":
        subject = f"[告警] 凯利盘中就绪闸豁免面扩面/超带(需重新确认) {stamp}"
        body = (f"就绪闸豁免面出现扩面或超带(新增成员/量级超带), 当日强制 WARN: "
                f"expansions={dec['expansions']} invalidations={dec['invalidations']}。"
                f"<br>确认/扩面命令: python scripts/kelly_intraday_gate_ack.py --list")
        return subject, body, "warning", "kelly_intraday_gate_expand_or_band", 24 * 3600
    if dec["reason"] == "exemption_invalidated_notice":
        subject = f"[告警] 凯利盘中就绪闸豁免已自动失效 {stamp}"
        body = (f"就绪闸豁免自动失效(五维之一): {dec['invalidations']}。已恢复原分级。"
                f"<br>如需重新确认: python scripts/kelly_intraday_gate_ack.py --list")
        return subject, body, "warning", "kelly_intraday_gate_invalidated", 24 * 3600
    if dec["reason"] == "state_read_fail_fail_safe":
        subject = f"[告警] 凯利盘中就绪闸状态文件读失败(fail-safe 偏告警) {stamp}"
        body = (f"就绪闸状态读失败 → 本次按「无豁免」判定(偏告警)。请检查 "
                f"{STATE_PATH}。")
        return subject, body, "warning", "kelly_intraday_gate_state_read_fail", STATE_READ_FAIL_DEDUP_WINDOW
    # 兜底: 任何非 silent 都发
    subject = f"[告警] 凯利盘中就绪闸判定 {dec['reason']} {stamp}"
    body = f"verdict={dec['verdict']} ratio={dec['ratio']:.1%} reason={dec['reason']}"
    return subject, body, "warning", "kelly_intraday_gate_misc", ABORT_DEDUP_WINDOW


def dispatch_notify(alarm, dry_run: bool = False) -> int:
    """调 notify.py 发分级告警(返 0 成功/非零失败)。dry_run=True 零外发(自测)。"""
    if alarm is None:
        return 0
    subject, body, tier, dedup_key, dedup_window = alarm
    cmd = [sys.executable, str(NOTIFY_PY), subject, body, "--tier", tier,
           "--from-prefix", "[告警]", "--dedup-key", dedup_key,
           "--dedup-window", str(int(dedup_window))]
    if dry_run:
        print(f"[dry-run] notify: tier={tier} dedup={dedup_key} window={dedup_window} subj={subject}")
        return 0
    try:
        return subprocess.run(cmd, timeout=120).returncode
    except Exception as e:  # noqa: BLE001
        print(f"[error] notify 外发失败: {type(e).__name__}: {e}", file=sys.stderr)
        return 1


# ════════════════════════════════════════════════════════════════════════════
# CLI
# ════════════════════════════════════════════════════════════════════════════
def _load_report(path: Path):
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else None
    except Exception:
        return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--report", default=str(REPORT_PATH), help="gate report json 路径")
    ap.add_argument("--state", default=str(STATE_PATH), help="豁免状态文件路径(自测可覆盖)")
    ap.add_argument("--backtest-rc", type=int, default=None, help="回测退出码(供 abort 文案/缺 report fail-safe)")
    ap.add_argument("--commit", action="store_true", help="落状态 + 追加 ledger + 按 tier 发告警")
    ap.add_argument("--print", dest="print_field", choices=["exit_code", "tier", "verdict", "reason"],
                    help="只读打印单字段(不落状态/不发告警)")
    ap.add_argument("--dry-run", action="store_true", help="不发真实通知(自测)")
    ap.add_argument("--json", action="store_true", help="打印完整 decision JSON")
    args = ap.parse_args(argv)

    now = datetime.now()
    state, state_ok = load_state(Path(args.state))
    report = _load_report(args.report)

    if report is None:
        # report 缺失: fail-safe 偏告警
        rc = args.backtest_rc if args.backtest_rc in (0, 5) else 5
        dec = {"verdict": "tolerate" if rc == 0 else "abort", "ratio": 0.0, "r_band": 0.0,
               "exit_code": rc, "tier": "warning", "reason": "report_missing",
               "exempted": [], "unfetchable_exempted": [], "zero_volume_exempted": [],
               "unfetchable_not_exempted": [], "streak": 0, "persistent": False,
               "unpriced_codes": [], "unpriced_zero_volume_codes": [],
               "forced_warn": False, "invalidations": [], "expansions": [], "state_ok": state_ok}
        if args.print_field:
            print(dec.get(args.print_field))
            return rc
        if args.commit:
            append_ledger({"ts": now.strftime("%Y-%m-%d %H:%M:%S"), "reason": "report_missing",
                           "exit_code": rc, "report": str(args.report)})
            subject = f"[告警] 凯利盘中就绪闸 report 缺失 {now.strftime('%m-%d %H:%M')}"
            body = f"gate report 不存在: {args.report}。就绪闸无法判定, 按偏告警处理。"
            dispatch_notify((subject, body, "warning", "kelly_intraday_gate_report_missing",
                             STATE_READ_FAIL_DEDUP_WINDOW), dry_run=args.dry_run)
        if args.json:
            print(json.dumps(dec, ensure_ascii=False))
        print(f"verdict={dec['verdict']} tier={dec['tier']} exit_code={rc} reason=report_missing")
        return rc

    dec = evaluate(report, state, now, mutate=args.commit, state_ok=state_ok)

    if args.print_field:
        print(dec.get(args.print_field))
        return int(dec["exit_code"])

    if args.commit:
        LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LOCK_PATH, "w") as lf:
            fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
            state, _ = load_state(Path(args.state))   # 锁内重读防并发覆盖
            state.setdefault("exemptions", [])
            state.setdefault("tolerate_streak", {"count": 0, "first_date": None, "codes": []})
            dec = evaluate(report, state, now, mutate=True, state_ok=state_ok)
            save_state_atomic(state, Path(args.state))
        append_ledger({
            "ts": now.strftime("%Y-%m-%d %H:%M:%S"), "run_date": report.get("run_date"),
            "verdict": dec["verdict"], "ratio": dec["ratio"], "r_band": dec["r_band"],
            "target_count": report.get("target_count"), "missing_count": report.get("missing_count"),
            "exempted": dec["exempted"], "invalidations": dec["invalidations"],
            "expansions": dec["expansions"], "streak": dec["streak"], "tier": dec["tier"],
            "reason": dec["reason"], "state_ok": state_ok,
        })
        alarm = build_alarm(report, dec, args.backtest_rc, now)
        dispatch_notify(alarm, dry_run=args.dry_run)

    if args.json:
        print(json.dumps(dec, ensure_ascii=False))
    print(f"verdict={dec['verdict']} tier={dec['tier']} exit_code={dec['exit_code']} "
          f"ratio={dec['ratio']:.4f} reason={dec['reason']} "
          f"exempted={dec['exempted']} streak={dec['streak']}")
    return int(dec["exit_code"])


if __name__ == "__main__":
    sys.exit(main())