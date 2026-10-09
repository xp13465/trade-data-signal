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

防告警轰炸：notify --dedup-key schedule_monitor_heartbeat 窗口 3600s（1h）。
  正常情况每天发 0 封；故障期每 1h 1 封（持续超时每窗口重发，直到心跳恢复 = 文件
  mtime 变新），不逐 15min 轮轰炸。

边界（诚实标注，超出 P0-1 范围）：本消费者自身由外部调度器驱动，调度器挂 = 本检查
也不跑 = 告警链断（元-元监控层）；notify.py 自身崩溃也无法把告警送出（latest.md 也
写不进）。这两层仍是无独立元监控的已知代价（D3 §6 已标注，本次只接 P0-1 消费者）。

用法：
  python3 scripts/check_monitor_heartbeat.py \
      [--heartbeat-path /tmp/schedule-monitor-heartbeat.txt] \
      [--stale-seconds 1800] [--repo <REPO>] [--dry-run]

退出码：0=健康（静默无输出告警）或「已判定异常且告警已发出/被 dedup 窗口抑制」；
  2=判定异常但 notify 未确认发出（failed/异常，需人工介入）。
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from notify_sent import notify_state  # noqa: E402  (#241 Pattern B/W2: 三态判据, 同 notify_sent 唯一实现)

# 默认心跳文件：与 schedule_monitor.sh 尾部 heartbeat 段（L2255 附近）一致
DEFAULT_HEARTBEAT = Path("/tmp/schedule-monitor-heartbeat.txt")
DEFAULT_STALE_SECONDS = 1800  # 30min：连续 2 轮（15min/轮）未更新判定停摆
# 告警去重窗口（秒）：健康期 0 封；故障期每窗口 1 封，防 15min 轮逐轮轰炸
DEDUP_KEY = "schedule_monitor_heartbeat"
DEDUP_WINDOW = 3600


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

    # ── 心跳新鲜度判定（mtime：文件最近更新时间，语义=「上次 monitor 完整跑完」）──
    if not hb.exists():
        reason = f"heartbeat 文件不存在: {hb}"
    else:
        try:
            age = datetime.now(timezone.utc).timestamp() - hb.stat().st_mtime
        except Exception as e:  # noqa: BLE001
            reason = f"heartbeat stat 失败: {e}"
        else:
            if age <= args.stale_seconds:
                # 健康：静默退出，不产生任何告警（反向测：健康路径必须零输出告警）
                print(f"[monitor-heartbeat] OK heartbeat age={int(age)}s <= "
                      f"{args.stale_seconds}s", file=sys.stderr)
                return 0
            reason = f"heartbeat 陈旧 {int(age)}s > {args.stale_seconds}s: {hb}"

    # ── 超时/缺失：发告警（沉默即故障；dedup 防轰炸）─────────────────────────────
    print(f"[monitor-heartbeat] ✗ {reason}", file=sys.stderr)
    subject = "[告警] schedule-monitor 心跳超时（监控停摆）"
    body = (f"schedule-monitor 心跳超时，监控体系可能停摆。\n{reason}\n\n"
            f"本告警由 check_monitor_heartbeat.py（元监控消费者）发出。\n"
            f"请排查：云上 schedule-monitor 对应 timer/service 是否 active、\n"
            f"日志（如 schedule_monitor 日志）是否仍在推进。")
    cmd = [
        sys.executable, str(notify_py),
        subject, body,
        "--severe",
        "--from-prefix", "[告警]",
        "--alert-issue", "schedule-monitor 心跳超时",
        "--dedup-key", DEDUP_KEY, "--dedup-window", str(DEDUP_WINDOW),
    ]
    if args.dry_run:
        cmd.append("--dry-run")
        print(f"[monitor-heartbeat][dry-run] 将执行: {' '.join(cmd)}", file=sys.stderr)
        return 0
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
    except Exception as e:  # noqa: BLE001
        print(f"[monitor-heartbeat] notify 调用失败（告警未能发出）: {e}", file=sys.stderr)
        return 2
    # #241 Pattern B / W2(2026-10-10): rc 无判别力(notify.py main() 所有出口恒 return 0)。
    # 改三态判据(notify_sent.notify_state): sent=真发出; suppressed=被 dedup 窗口抑制
    # (=已发过, 成功且已知, 不重试不报错); failed/未知=保守回 rc 2(交调度层告警)。
    out = (r.stdout or "") + "\n" + (r.stderr or "")
    state = notify_state(out)
    if state in ("sent", "suppressed"):
        print(f"[monitor-heartbeat] notify 已处理({state}, rc={r.returncode}, "
              f"dedup {DEDUP_KEY}/{DEDUP_WINDOW}s)", file=sys.stderr)
        # 告警已由 notify 独立通道发出（email/feishu/latest.md）或被窗口抑制，本脚本正常完成
        return 0
    print(f"[monitor-heartbeat] notify 未发出（state={state}, rc={r.returncode}）: "
          f"{out.strip()[:300]}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
