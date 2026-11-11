#!/usr/bin/env python3
"""alert_ack.py - 人工确认告警小工具(写 alert_state.json 的 acknowledged 字段)。

ACK表示有人认领，不表示业务恢复。仅补认领字段，不改status、失败次数或通知回执。
新事件不会继承旧事件的认领；--clear只撤销认领。与monitor/notify共用原锁。

用法:
  python scripts/alert_ack.py <key> [key2 ...]   # 确认一个或多个告警 key
  python scripts/alert_ack.py --list             # 列出 active/pending 的 key
  python scripts/alert_ack.py <key> --clear      # 清除确认(恢复默认告警行为)

写入为原子操作(tmp + rename), 并发安全(flock); 生产 alert_state.json 由
schedule_monitor 每 15min 重写, 本工具只合并当前事件的认领字段。
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import getpass
import tempfile
import time
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(os.environ.get("REPO", Path(__file__).absolute().parent.parent)).absolute()
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
    fd, tmp = tempfile.mkstemp(prefix=".alert-ack-", dir=ALERT_STATE_FILE.parent)
    try:
        with os.fdopen(fd, "w") as out:
            os.fchmod(out.fileno(), 0o600)
            json.dump(state, out, ensure_ascii=False, indent=2)
            out.write("\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, ALERT_STATE_FILE)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("keys", nargs="*", help="告警 state key(如 feishu_ws_stale)")
    ap.add_argument("--list", action="store_true", help="列出 active/pending key")
    ap.add_argument("--clear", action="store_true", help="清除指定 key 的 acknowledged")
    ap.add_argument("--owner", default=None, help="认领责任人(默认当前操作用户)")
    ap.add_argument("--note", default="", help="人工处置备注，不作为健康证明")
    args = ap.parse_args()
    owner = (args.owner or getpass.getuser()).strip()
    if not owner or len(owner) > 120 or len(args.note) > 1000:
        ap.error("owner须1–120字符，note最多1000字符")

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
        deadline = time.monotonic() + 2
        while True:
            try:
                fcntl.flock(lf.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    print("[error] alert state lock timeout", file=sys.stderr)
                    return 2
                time.sleep(0.01)
        state = _load()
        changed = []
        for k in args.keys:
            info = state.get(k)
            if not isinstance(info, dict):
                print(f"[warn] key<{k}> 不在 alert_state.json, 跳过(--list 查看)")
                continue
            if args.clear:
                for field in ("acknowledged", "ack_owner", "ack_event_id", "ack_note", "last_ack_log"):
                    info.pop(field, None)
                changed.append((k, "cleared"))
            else:
                info.update(acknowledged=now_str, ack_owner=owner,
                            ack_event_id=info.get("event_id"), ack_note=args.note)
                changed.append((k, f"acknowledged={now_str} owner={owner} (仅认领，未恢复)"))
        if changed:
            _save_atomic(state)
    for k, msg in changed:
        print(f"[ok] {k}: {msg}")
    return 0 if changed else 1


if __name__ == "__main__":
    sys.exit(main())
