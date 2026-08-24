#!/usr/bin/env python3
"""alert_ack.py - 人工确认告警小工具(写 alert_state.json 的 acknowledged 字段)。

2026-08-24 告警三级分级配套: 某些"持续中但人工核实属正常"的告警(如周末飞书群
无消息导致 ws 心跳陈旧、假期数据源静默), 用户核实后用本工具确认, 确认后 24h 内
监控不重复推送同 key 告警(schedule_monitor.sh 维度⑨等读 acknowledged 判定),
超 24h 未恢复自动恢复提醒。只加字段不动 status/其他键, 不影响原恢复检测。

用法:
  python scripts/alert_ack.py <key> [key2 ...]   # 确认一个或多个告警 key
  python scripts/alert_ack.py --list             # 列出 active/pending 的 key
  python scripts/alert_ack.py <key> --clear      # 清除确认(恢复默认告警行为)

写入为原子操作(tmp + rename), 并发安全(flock); 生产 alert_state.json 由
schedule_monitor 每 15min 重写, 本工具只补 acknowledged/ack_note 两个字段。
"""
from __future__ import annotations

import argparse
import fcntl
import json
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).absolute().parent.parent
ALERT_STATE_FILE = REPO / "data" / "alert_state.json"
LOCK_FILE = REPO / "data" / ".alert_state.lock"
ACK_VALID_HOURS = 24


def _load() -> dict:
    if not ALERT_STATE_FILE.exists():
        return {}
    try:
        return json.loads(ALERT_STATE_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[error] 读 {ALERT_STATE_FILE} 失败: {e}", file=sys.stderr)
        sys.exit(1)


def _save_atomic(state: dict) -> None:
    """原子写(tmp + rename), 防半截文件被 monitor 读走。"""
    ALERT_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = ALERT_STATE_FILE.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    tmp.replace(ALERT_STATE_FILE)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("keys", nargs="*", help="告警 state key(如 feishu_ws_stale)")
    ap.add_argument("--list", action="store_true", help="列出 active/pending key")
    ap.add_argument("--clear", action="store_true", help="清除指定 key 的 acknowledged")
    args = ap.parse_args()

    state = _load()

    if args.list:
        rows = [
            (k, v.get("status"), v.get("last_alerted"), v.get("first_seen"))
            for k, v in state.items()
            if isinstance(v, dict) and v.get("status") in ("active", "pending")
        ]
        if not rows:
            print("(无 active/pending 告警)")
        for k, st, la, fs in sorted(rows):
            ack = state[k].get("acknowledged")
            mark = f" [已确认 {ack}]" if ack else ""
            print(f"{k}  status={st}  last_alerted={la}  first_seen={fs}{mark}")
        return 0

    if not args.keys:
        ap.error("需要至少一个 key, 或 --list")

    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOCK_FILE, "w") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        state = _load()
        changed = []
        for k in args.keys:
            info = state.get(k)
            if not isinstance(info, dict):
                print(f"[warn] key<{k}> 不在 alert_state.json, 跳过(--list 查看)")
                continue
            if args.clear:
                info.pop("acknowledged", None)
                info.pop("last_ack_log", None)
                changed.append((k, "cleared"))
            else:
                info["acknowledged"] = now_str
                changed.append((k, f"acknowledged={now_str} (24h 内静默)"))
        if changed:
            _save_atomic(state)
    for k, msg in changed:
        print(f"[ok] {k}: {msg}")
    return 0 if changed else 1


if __name__ == "__main__":
    sys.exit(main())
