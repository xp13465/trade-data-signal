"""BaoStock worker process: fetches a chunk of codes for a given segment.

Each worker is a completely independent Python process with its own BaoStock login.
Reads chunk from a JSON file, fetches each code, upserts to DB, updates progress.
Handles BaoStock connection drops (broken pipe / 接收数据异常) with re-login + retry.
"""
import os
os.environ.setdefault("NO_PROXY", "*")
os.environ.setdefault("no_proxy", "*")
import sys
import json
import time
import random
import datetime as dt
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).absolute().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.collector.baostock_daily import (
    init_db, fetch_one, upsert_rows, load_progress, save_progress,
    RECENT_START, OLD_START, OLD_END, to_baostock_code,
)
import baostock as bs


def is_conn_error(msg: str) -> bool:
    """检测 BaoStock 连接断开错误（需 re-login）。"""
    markers = ("Broken pipe", "接收数据异常", "Connection reset",
               "Connection aborted", "EOF occurred", "uranium")
    return any(m in msg for m in markers)


def relogin():
    """重新登录 BaoStock。"""
    try:
        bs.logout()
    except Exception:  # noqa: BLE001
        pass
    time.sleep(2 + random.uniform(0.5, 1.5))
    lg = bs.login()
    return lg.error_code == "0"


def main():
    seg = "r"
    chunk_file = None
    for a in sys.argv[1:]:
        if a.startswith("--seg="):
            seg = a.split("=", 1)[1]
        elif a.startswith("--chunk="):
            chunk_file = a.split("=", 1)[1]

    if not chunk_file:
        print("ERROR: --chunk required", flush=True)
        return 1

    codes = json.loads(Path(chunk_file).read_text(encoding="utf-8"))
    print(f"worker {os.getpid()}: {len(codes)} codes, seg={seg}", flush=True)

    init_db()
    bs.login()
    print(f"worker {os.getpid()}: baostock logged in", flush=True)

    today = dt.date.today().strftime("%Y-%m-%d")
    start = RECENT_START if seg == "r" else OLD_START
    end = today if seg == "r" else OLD_END
    end_yyyymmdd = end.replace("-", "") if seg == "r" else OLD_END.replace("-", "")

    ok = fail = total_rows = 0
    for i, code in enumerate(codes):
        retries = 0
        success = False
        while retries < 3 and not success:
            try:
                rows, msg = fetch_one(code, start, end)
                if rows:
                    n = upsert_rows(rows)
                    total_rows += n
                    ok += 1
                    last = max(r[1] for r in rows)
                    # Update progress
                    prog = load_progress()
                    entry = prog.get(code, {})
                    entry[seg] = last
                    prog[code] = entry
                    save_progress(prog)
                    success = True
                elif "empty" in msg or "skip" in msg:
                    # Even empty results mark as done (avoid retrying dead codes)
                    ok += 1
                    prog = load_progress()
                    entry = prog.get(code, {})
                    entry[seg] = end_yyyymmdd
                    prog[code] = entry
                    save_progress(prog)
                    success = True
                else:
                    # BaoStock error
                    if is_conn_error(msg) and retries < 2:
                        print(f"  [{os.getpid()}] {code}: conn error, re-login "
                              f"(retry {retries+1}/3): {msg[:80]}", flush=True)
                        relogin()
                        retries += 1
                        continue
                    fail += 1
                    print(f"  [{os.getpid()}] {i+1}/{len(codes)} {code}: FAIL {msg[:100]}",
                          flush=True)
                    success = True  # give up, move on
            except Exception as e:  # noqa: BLE001
                emsg = str(e)
                if is_conn_error(emsg) and retries < 2:
                    print(f"  [{os.getpid()}] {code}: exc conn error, re-login "
                          f"(retry {retries+1}/3): {emsg[:80]}", flush=True)
                    relogin()
                    retries += 1
                    continue
                fail += 1
                print(f"  [{os.getpid()}] {i+1}/{len(codes)} {code}: ERR "
                      f"{type(e).__name__}: {emsg[:100]}", flush=True)
                success = True  # give up, move on

        if (i + 1) % 20 == 0:
            print(f"  [{os.getpid()}] progress: {i+1}/{len(codes)}, ok={ok} "
                  f"fail={fail} rows={total_rows}", flush=True)

    try:
        bs.logout()
    except Exception:  # noqa: BLE001
        pass
    print(f"worker {os.getpid()} done: ok={ok} fail={fail} rows={total_rows}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
