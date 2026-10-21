#!/usr/bin/env python3
"""deploy_fail_tracker.py - 记录 deploy 连续失败次数, 达阈值时由 deploy.sh 发独立告警。

【为什么需要它(P0, 2026-10-21)】
  实测: 10-20 / 10-21 两天 deploy 39 次零成功(最后成功 10-19 23:25), 但每次失败只有
  各自闸门的单点告警(6h 去重), **没有「部署连续失败 N 次」这一聚合维度** ⇒ 停摆两天
  无人知。本脚本只做状态记账(纯本地 JSON, 零外发), 由 deploy.sh 的 EXIT trap 调用;
  阈值命中时脚本 exit 10, 由 deploy.sh 发一封独立告警(去重 6h)。

【状态文件】<repo>/data/deploy_fail_state.json(原子写)
  {
    "consecutive_fail": int,        # 连续失败次数(成功清零)
    "last_fail_at": "YYYY-MM-DD HH:MM:SS",
    "last_success_at": "...",
    "last_rc": int, "last_stage": str, "last_log": str,
    "alerted_at": "...",            # 本段连续失败已发过阈值告警的时间
    "alerted_for_count": int        # 发告警时的 consecutive_fail(防同段重复发)
  }

【退出码】0=已记录 / 10=连续失败达阈值(调用方应发告警, 本脚本**不发送**任何通知)。
  阈值 = --threshold 或 env DEPLOY_FAIL_ALERT_THRESHOLD, 默认 2(任务书建议值)。

【自测】--now "2026-10-21 10:00:00" 冻结时间; --repo 指临时目录 ⇒ 零外发/零生产写。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

STATE_FILENAME = "deploy_fail_state.json"


def _parse_now(value: str | None) -> datetime:
    if not value:
        return datetime.now()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y%m%d%H%M%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise SystemExit(f"--now 格式不支持: {value!r}(支持 'YYYY-MM-DD HH:MM:SS' / ISO)")


def _load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 - 缺失/损坏都从零开始, 不阻塞 deploy
        return {}


def _write(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="deploy 连续失败记账 + 阈值判定(零外发)")
    ap.add_argument("command", choices=["failure", "success"])
    ap.add_argument("--repo", default=os.environ.get("REPO", "."),
                    help="数据仓根(状态写 <repo>/data/deploy_fail_state.json)")
    ap.add_argument("--rc", type=int, default=None, help="本次 deploy 退出码(failure 用)")
    ap.add_argument("--stage", default="", help="失败阶段标记(见 deploy.sh DEPLOY_STAGE)")
    ap.add_argument("--log", default="", help="本次 deploy 日志路径")
    ap.add_argument("--threshold", type=int,
                    default=int(os.environ.get("DEPLOY_FAIL_ALERT_THRESHOLD", "2")),
                    help="连续失败告警阈值(默认 2, 亦可用 env DEPLOY_FAIL_ALERT_THRESHOLD)")
    ap.add_argument("--now", default=None, help="自测: 冻结当前时间")
    args = ap.parse_args(argv)

    now = _parse_now(args.now)
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    state_path = Path(args.repo) / "data" / STATE_FILENAME
    state = _load(state_path)

    if args.command == "success":
        state["consecutive_fail"] = 0
        state["last_success_at"] = now_str
        # 新一段计数开始 ⇒ 清空告警标记(下一次连续失败仍会再报一次)
        state.pop("alerted_at", None)
        state.pop("alerted_for_count", None)
        state.pop("last_fail_at", None)
        _write(state_path, state)
        return 0

    count = int(state.get("consecutive_fail") or 0) + 1
    state["consecutive_fail"] = count
    state["last_fail_at"] = now_str
    if args.rc is not None:
        state["last_rc"] = args.rc
    if args.stage:
        state["last_stage"] = args.stage
    if args.log:
        state["last_log"] = args.log

    threshold = max(1, int(args.threshold or 2))
    hit = count == threshold and state.get("alerted_for_count") != count
    if hit:
        state["alerted_at"] = now_str
        state["alerted_for_count"] = count
    _write(state_path, state)
    if hit:
        print(f"[deploy-fail-tracker] 连续失败 {count} 次达到阈值 {threshold} ⇒ 需发独立告警")
        return 10
    print(f"[deploy-fail-tracker] 连续失败 {count} 次(阈值 {threshold})")
    return 0


if __name__ == "__main__":
    sys.exit(main())