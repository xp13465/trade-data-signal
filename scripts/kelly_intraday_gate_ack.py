#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kelly_intraday_gate_ack.py — 凯利盘中就绪闸「豁免」人工确认/查看/撤销 CLI(#254 方案 A)。

配套: scripts/kelly_intraday_gate_decider.py(判定器)+ data/alerts/kelly_intraday_gate_state.json。

用法:
  python scripts/kelly_intraday_gate_ack.py --list                         # 列出全部豁免及状态
  python scripts/kelly_intraday_gate_ack.py confirm --report <report.json> [--note "…"]
        # 用当前 gate report 的缺口面确认豁免(推荐: 面从真实运行本身来, 不手抄)
  python scripts/kelly_intraday_gate_ack.py confirm --codes 159513,164508 --class zero_volume \
        --main-source-ok false --fallback-used true [--note "…"]
  python scripts/kelly_intraday_gate_ack.py --clear <id>                   # 撤销(revoked)

⚠️ 语义锚点(§23.13):问题面 = **观测形态**,不区分停牌/清盘/零成交/封禁等成因。
   「09:40 前零成交」≠「当日零成交」:确认范围只覆盖 09:40 这一刻两源无当日成交的形态。
   band_cap = max(R=15%, 确认时 r_band);TTL 零成交类 60 天 / 含取不到类 14 天;命中不自动续期。
"""
from __future__ import annotations

import argparse
import fcntl
import json
import sys
from datetime import datetime

from kelly_intraday_gate_decider import (
    R_THRESHOLD,
    STATE_PATH,
    LOCK_PATH,
    REPORT_PATH,
    _ttl_days_of,
    append_ledger,
    load_state,
    save_state_atomic,
)


def _face_from_report(path) -> dict:
    doc = json.loads(open(path, encoding="utf-8").read())
    codes = [str(c.get("code")) for c in (doc.get("codes") or [])]
    class_by_code = {str(c.get("code")): c.get("class") for c in (doc.get("codes") or [])}
    target_count = int(doc.get("target_count") or 0)
    unfetch = sum(1 for c in codes if class_by_code.get(c) == "unfetchable")
    r_band = (unfetch / target_count) if target_count else 0.0
    return {
        "codes": codes,
        "class_by_code": class_by_code,
        "src_ctx": {"main_source_ok": bool(doc.get("main_source_ok")),
                    "fallback_used": bool(doc.get("fallback_used"))},
        "r_band": r_band,
        "run_date": doc.get("run_date"),
    }


def _face_from_args(args) -> dict:
    codes = [c.strip() for c in (args.codes or "").split(",") if c.strip()]
    cls = args.class_
    class_by_code = {c: cls for c in codes}
    return {
        "codes": codes,
        "class_by_code": class_by_code,
        "src_ctx": {"main_source_ok": bool(args.main_source_ok),
                    "fallback_used": bool(args.fallback_used)},
        "r_band": float(args.r_band or 0.0),
        "run_date": args.run_date,
    }


def _confirm(face: dict, note: str, state_path) -> int:
    if not face["codes"]:
        print("[error] 确认面为空(无缺口码), 拒绝写入", file=sys.stderr)
        return 1
    now = datetime.now()
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCK_PATH, "w") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        state, ok = load_state(state_path)
        if not ok:
            print("[warn] 原状态读失败, 以空白状态重写(可能丢失历史豁免)", file=sys.stderr)
        state.setdefault("exemptions", [])
        run_tag = str(face.get("run_date") or now.strftime("%Y%m%d")).replace("-", "")
        seq = len(state["exemptions"]) + 1
        new_id = f"ex_{run_tag}_{seq}"
        # 扩面确认 → 覆盖旧记录(supersede 留档, 不物理删)
        new_codes = set(face["codes"])
        for ex in state["exemptions"]:
            if ex.get("status") == "active" and set(str(c) for c in ex.get("codes", [])) <= new_codes:
                ex["status"] = "superseded"
                ex["superseded_by"] = new_id
                ex["superseded_at"] = now.strftime("%Y-%m-%d %H:%M:%S")
        band_cap = max(R_THRESHOLD, round(face["r_band"], 6))
        rec = {
            "id": new_id,
            "codes": sorted(new_codes),
            "class_by_code": face["class_by_code"],
            "src_ctx": face["src_ctx"],
            "band_cap": band_cap,
            "ttl_days": _ttl_days_of(face["class_by_code"]),
            "confirmed_at": now.strftime("%Y-%m-%d %H:%M:%S"),
            "status": "active",
            "band_strikes": 0,
            "hits": 0,
            "note": note or "",
        }
        state["exemptions"].append(rec)
        save_state_atomic(state, state_path)
    append_ledger({"ts": now.strftime("%Y-%m-%d %H:%M:%S"), "action": "confirm",
                   "id": rec["id"], "codes": rec["codes"], "ttl_days": rec["ttl_days"],
                   "band_cap": rec["band_cap"], "note": rec["note"]})
    print(f"[ok] 已确认豁免 {rec['id']}")
    print(f"     问题面(观测形态, 不区分停牌/清盘/零成交等成因): {rec['codes']}")
    print(f"     类别: {rec['class_by_code']}  源上下文: {rec['src_ctx']}")
    print(f"     band_cap={rec['band_cap']:.1%}  TTL={rec['ttl_days']} 自然日(自确认日起算, 命中不自动续期)")
    print(("     ⚠ 含「取不到(unfetchable)」类 → 命中时降级 WARN, 永不静默"
           if rec["ttl_days"] != 60 else "     零成交类 → 命中时完全静默(仅 info 留痕)"))
    print("     范围锚点:「09:40 前零成交」≠「当日零成交」")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd")
    ap.add_argument("--state", default=str(STATE_PATH))
    ap.add_argument("--list", action="store_true", help="列出全部豁免及状态")
    ap.add_argument("--clear", metavar="ID", help="撤销指定豁免 id(revoked)")
    pc = sub.add_parser("confirm", help="确认豁免")
    # --state 允许写在子命令之后(SUPPRESS: 未给则沿用全局值, 给了则覆盖)
    pc.add_argument("--state", default=argparse.SUPPRESS, help="豁免状态文件路径(自测可覆盖)")
    pc.add_argument("--report", default=str(REPORT_PATH), help="从 gate report 取缺口面(推荐)")
    pc.add_argument("--codes", help="显式码集合(逗号分隔), 与 --report 二选一")
    pc.add_argument("--class", dest="class_", choices=["zero_volume", "unfetchable"],
                    help="显式类别(配合 --codes)")
    pc.add_argument("--main-source-ok", choices=["true", "false"], default="false")
    pc.add_argument("--fallback-used", choices=["true", "false"], default="true")
    pc.add_argument("--r-band", type=float, default=0.0, help="显式 r_band(配合 --codes)")
    pc.add_argument("--run-date", default=None)
    pc.add_argument("--note", default="")
    args = ap.parse_args(argv)

    state_path = args.state

    if args.list:
        state, ok = load_state(state_path)
        if not ok:
            print("[warn] 状态读失败, 显示空白", file=sys.stderr)
        exs = state.get("exemptions", [])
        if not exs:
            print("(无豁免记录)")
        for ex in exs:
            mark = " ← active" if ex.get("status") == "active" else ""
            print(f"{ex.get('id')}  status={ex.get('status')}  codes={ex.get('codes')}  "
                  f"class={ex.get('class_by_code')}  band_cap={ex.get('band_cap')}  "
                  f"ttl={ex.get('ttl_days')}d  hits={ex.get('hits', 0)}  "
                  f"confirmed={ex.get('confirmed_at')}{mark}")
        return 0

    if args.clear:
        now = datetime.now()
        LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LOCK_PATH, "w") as lf:
            fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
            state, _ = load_state(state_path)
            hit = None
            for ex in state.get("exemptions", []):
                if ex.get("id") == args.clear:
                    ex["status"] = "revoked"
                    ex["revoked_at"] = now.strftime("%Y-%m-%d %H:%M:%S")
                    hit = ex
            if hit is None:
                print(f"[warn] 未找到豁免 id={args.clear}(--list 查看)", file=sys.stderr)
                return 1
            save_state_atomic(state, state_path)
        append_ledger({"ts": now.strftime("%Y-%m-%d %H:%M:%S"), "action": "revoke", "id": args.clear})
        print(f"[ok] 已撤销豁免 {args.clear}")
        return 0

    if args.cmd == "confirm":
        if args.codes:
            face = _face_from_args(args)
        else:
            face = _face_from_report(args.report)
        return _confirm(face, args.note, state_path)

    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())