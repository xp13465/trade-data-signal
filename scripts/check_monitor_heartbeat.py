#!/usr/bin/env python3
"""check_monitor_heartbeat.py —— schedule-monitor 心跳消费方（元监控，D3 §6 P0-1）。

背景：schedule_monitor.sh 每轮（15min/轮）在 /tmp/schedule-monitor-heartbeat.txt 更新
时间戳。但全仓 grep 无任何消费方——schedule-monitor 自己挂了没人知道 = 元监控盲区
（监控体系整体停摆无人知）。本脚本是独立消费者：由外部调度器（建议云上 systemd timer
或主控 cron，每 15min 与 schedule_monitor 同频）调用，检查心跳新鲜度，缺失/超时 →
notify --severe 告警到用户（含 latest.md 流水区留痕）。

「沉默即故障」语义：心跳文件缺失/陈旧本身就是「监控停摆」的真故障信号——告警由
沉默触发，不是由异常活跃触发（与 memory alert-denoise-keep-fault-discriminator
一致：判定维度用「心跳是否在推进」这个有因果区分度的特征，不用表面特征降级）。

防告警轰炸：持续故障复用现有 alert_state 事件 + notify 各渠道回执。
  首报保留，重复轮只补失败渠道；真实恢复后新故障使用新 event_id，不继承旧 ACK。
  不再按 1h 窗口重复首报。共享状态不可用时响亮返回 2、保留原文件并直发未知故障。

边界（诚实标注，超出 P0-1 范围）：本消费者自身由外部调度器驱动，调度器挂 = 本检查
也不跑 = 告警链断（元-元监控层）；notify.py 自身崩溃也无法把告警送出（latest.md 也
写不进）。这两层仍是无独立元监控的已知代价（D3 §6 已标注，本次只接 P0-1 消费者）。

用法：
  python3 scripts/check_monitor_heartbeat.py \
      [--heartbeat-path /tmp/schedule-monitor-heartbeat.txt] \
      [--stale-seconds 1800] [--repo <REPO>] [--dry-run]

退出码：0=健康（静默无输出告警）或「已判定异常且事件通知已受理/被同事件回执抑制」；
  2=判定异常但 notify 未确认发出（failed/异常，需人工介入）。
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path

from ops_legacy_events import observe, dispatch

# 默认心跳文件：与 schedule_monitor.sh 尾部 heartbeat 段（L2255 附近）一致
DEFAULT_HEARTBEAT = Path("/tmp/schedule-monitor-heartbeat.txt")
DEFAULT_STALE_SECONDS = 1800  # 30min：连续 2 轮（15min/轮）未更新判定停摆

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="schedule-monitor 心跳消费方（元监控）")
    ap.add_argument("--heartbeat-path", default=str(DEFAULT_HEARTBEAT),
                    help="心跳文件路径（测试可注入临时文件）")
    ap.add_argument("--stale-seconds", type=int, default=DEFAULT_STALE_SECONDS,
                    help="心跳超时阈值秒数（默认 1800=30min）")
    ap.add_argument("--repo", default=None,
                    help="REPO 根（定位 scripts/notify.py；缺省=本脚本所在仓库根）")
    ap.add_argument("--dry-run", action="store_true", help="不真发，只打印将执行的 notify 命令")
    args = ap.parse_args(argv)

    hb = Path(args.heartbeat_path)
    repo = Path(args.repo) if args.repo else Path(__file__).absolute().parent.parent
    notify_py = repo / "scripts" / "notify.py"

    if args.stale_seconds <= 0:
        ap.error("stale-seconds must be positive")
    key = "producer_heartbeat|" + hashlib.sha256(str(hb.absolute()).encode()).hexdigest()

    def probe():
        try:
            age = datetime.now(timezone.utc).timestamp() - hb.stat().st_mtime
        except FileNotFoundError:
            reason = f"heartbeat 文件不存在: {hb}"
        except OSError as exc:
            reason = f"heartbeat stat 失败: {exc}"
        else:
            if 0 <= age <= args.stale_seconds:
                return {"action": False, "message": f"heartbeat age={int(age)}s", "age_seconds": age}
            reason = f"heartbeat 时间异常/陈旧 {int(age)}s (阈值 {args.stale_seconds}s): {hb}"
        return {"action": True, "message": reason}

    if args.dry_run:
        print(f"[monitor-heartbeat][dry-run] {probe()}", file=sys.stderr)
        return 0
    state_unknown = False
    try:
        facts, refs = observe(repo, key, probe)
    except Exception as exc:
        # Never overwrite corrupt state or treat it as recovery / receipt.
        print(f"[monitor-heartbeat] 事件状态 unknown: {exc}", file=sys.stderr)
        facts, refs, state_unknown = probe(), None, True
    if not facts["action"]:
        print(f"[monitor-heartbeat] OK {facts['message']}", file=sys.stderr)
        return 2 if state_unknown else 0
    print(f"[monitor-heartbeat] ✗ {facts['message']}", file=sys.stderr)
    body = ("schedule-monitor 心跳超时，监控体系可能停摆。\n" + facts["message"] +
            "\n请排查 schedule-monitor 对应 timer/service、日志是否仍在推进。" +
            ("\n共享事件状态无法确认；本次为 fail-visible 首报，未证明去重/恢复。" if state_unknown else ""))
    try:
        status = dispatch(repo, notify_py, "[告警] schedule-monitor 心跳超时（监控停摆）",
                          body, refs, source="check_monitor_heartbeat.py")
    except Exception as exc:
        print(f"[monitor-heartbeat] notify 未确认: {exc}", file=sys.stderr)
        return 2
    # Partial/unknown MUST retry missing channels, not masquerade as full success.
    return 0 if not state_unknown and status in ("sent", "suppressed", "superseded") else 2


if __name__ == "__main__":
    sys.exit(main())
