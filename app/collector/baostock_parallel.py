"""Parallel BaoStock fetcher: spawn N independent subprocesses, each handling a chunk of codes.

Each subprocess is a completely independent Python process with its own BaoStock login,
avoiding the global state issues with multiprocessing. BaoStock server handles concurrent
connections from the same IP (tested).
"""
import os
os.environ.setdefault("NO_PROXY", "*")
os.environ.setdefault("no_proxy", "*")
import sys
import time
import json
import subprocess
import datetime as dt
from pathlib import Path

DATA_DIR = Path(__file__).absolute().parent.parent.parent / "data"
PROGRESS_PATH = DATA_DIR / "baostock_progress.json"
LOG_DIR = DATA_DIR / "baostock_logs"
WORKER_SCRIPT = Path(__file__).absolute().parent / "baostock_worker.py"


def load_progress():
    if PROGRESS_PATH.exists():
        try:
            return json.loads(PROGRESS_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def chunk_list(lst, n):
    """Split list into n roughly equal chunks."""
    k, m = divmod(len(lst), n)
    return [lst[i*k+min(i, m):(i+1)*k+min(i+1, m)] for i in range(n)]


def run_parallel(seg="r", n_workers=4, limit=None):
    """Run N parallel subprocesses, each fetching a chunk of codes for given segment.
    seg='r' (recent 2016-2026) or 'o' (old 1990-2015).
    """
    from app.collector.baostock_daily import fetch_stock_codes, to_baostock_code, init_db
    init_db()
    codes = fetch_stock_codes()
    if limit:
        codes = codes[:limit]

    # Filter out bj codes and already-done codes
    progress = load_progress()
    todo = []
    for c in codes:
        if to_baostock_code(c) is None:
            continue
        entry = progress.get(c, {})
        if seg == "r" and entry.get("r"):
            continue
        if seg == "o" and entry.get("o"):
            continue
        todo.append(c)

    print(f"parallel {seg}: {len(todo)} codes to fetch, {n_workers} workers", flush=True)
    if not todo:
        print("nothing to do", flush=True)
        return

    chunks = chunk_list(todo, n_workers)
    chunks = [c for c in chunks if c]  # drop empty

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    procs = []
    for i, chunk in enumerate(chunks):
        log_file = LOG_DIR / f"worker_{seg}_{i}_{ts}.log"
        # Write chunk to a temp file for the worker to read
        chunk_file = LOG_DIR / f"chunk_{seg}_{i}_{ts}.json"
        chunk_file.write_text(json.dumps(chunk), encoding="utf-8")
        p = subprocess.Popen(
            [sys.executable, "-u", str(WORKER_SCRIPT),
             f"--seg={seg}", f"--chunk={chunk_file}"],
            stdout=open(log_file, "w"),
            stderr=subprocess.STDOUT,
        )
        procs.append((p, log_file, len(chunk)))
        print(f"  worker {i}: {len(chunk)} codes -> PID {p.pid}, log {log_file.name}", flush=True)

    print(f"\n{len(procs)} workers launched. Monitoring...", flush=True)
    start = time.time()
    while True:
        time.sleep(30)
        elapsed = time.time() - start
        # Check progress
        prog = load_progress()
        n_done = sum(1 for v in prog.values() if v.get(seg))
        alive = sum(1 for p, _, _ in procs if p.poll() is None)
        rate = n_done / elapsed * 3600 if elapsed > 0 else 0
        eta_h = (len(todo) - n_done) / rate if rate > 0 else float("inf")
        print(f"  [{elapsed/60:.1f}min] progress: {n_done}/{len(todo)} codes done, "
              f"{alive}/{len(procs)} workers alive, rate={rate:.0f}/h, ETA={eta_h:.1f}h",
              flush=True)
        if alive == 0:
            break

    print(f"\n=== all workers done in {(time.time()-start)/60:.1f}min ===", flush=True)
    prog = load_progress()
    n_done = sum(1 for v in prog.values() if v.get(seg))
    print(f"total {seg} done: {n_done}/{len(todo)}", flush=True)


def run_update_parallel(codes, n_workers=4, verbose=True):
    """并行增量更新（recent 段增量）。codes 是已筛选的 todo（有 progress['r'] 的）。

    对每个 code 算 start=progress['r']+1 天, end=today，跳过 up-to-date。
    分 chunk 给 worker subprocess（--mode=update，chunk=[(code,start,end),...]）。
    每个 worker 独立 BaoStock login + 独立 DB conn（WAL 兜底并发写）。

    返回 {ok, fail, skip_bj, skip_done, total_rows, processed, details}，
    与 baostock_daily.run_update 返回结构兼容（runner.py 直接用）。
    """
    import re
    from app.collector.baostock_daily import (
        to_baostock_code, init_db, RECENT_START, TODAY,
    )
    init_db()
    progress_before = load_progress()
    today_ymd = TODAY()

    # 算每个 code 的 (code, start, end)，跳过 bj 和 up-to-date
    tasks = []
    skip_bj = 0
    skip_done = 0
    for code in codes:
        if to_baostock_code(code) is None:
            skip_bj += 1
            continue
        entry = progress_before.get(code, {})
        last_r = entry.get("r")
        if not last_r:
            skip_done += 1
            continue
        d = dt.datetime.strptime(last_r, "%Y%m%d").date() + dt.timedelta(days=1)
        start = d.strftime("%Y-%m-%d")
        end = today_ymd
        if start.replace("-", "") > end.replace("-", ""):
            skip_done += 1
            continue
        tasks.append((code, start, end))

    if not tasks:
        print("parallel update: nothing to do (all up-to-date)", flush=True)
        return {"ok": 0, "fail": 0, "skip_bj": skip_bj, "skip_done": skip_done,
                "total_rows": 0, "processed": len(codes), "details": []}

    print(f"parallel update: {len(tasks)} codes to fetch, {n_workers} workers",
          flush=True)

    chunks = chunk_list(tasks, n_workers)
    chunks = [c for c in chunks if c]

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    procs = []
    for i, chunk in enumerate(chunks):
        log_file = LOG_DIR / f"worker_update_{i}_{ts}.log"
        chunk_file = LOG_DIR / f"chunk_update_{i}_{ts}.json"
        chunk_file.write_text(json.dumps(chunk), encoding="utf-8")
        p = subprocess.Popen(
            [sys.executable, "-u", str(WORKER_SCRIPT),
             f"--chunk={chunk_file}", "--mode=update"],
            stdout=open(log_file, "w"),
            stderr=subprocess.STDOUT,
        )
        procs.append((p, log_file, len(chunk)))
        print(f"  worker {i}: {len(chunk)} codes -> PID {p.pid}, log {log_file.name}",
              flush=True)

    print(f"\n{len(procs)} workers launched. Monitoring...", flush=True)
    start_time = time.time()
    while True:
        time.sleep(15)
        elapsed = time.time() - start_time
        alive = sum(1 for p, _, _ in procs if p.poll() is None)
        # 从 progress 看进度（entry['r'] >= end 视为该 code done）
        prog = load_progress()
        n_done = sum(1 for c, s, e in tasks
                     if prog.get(c, {}).get("r", "") >= e.replace("-", ""))
        if verbose:
            print(f"  [{elapsed/60:.1f}min] progress: {n_done}/{len(tasks)} codes done, "
                  f"{alive}/{len(procs)} workers alive", flush=True)
        if alive == 0:
            break

    elapsed_min = (time.time() - start_time) / 60
    print(f"\n=== all workers done in {elapsed_min:.1f}min ===", flush=True)

    # 从 worker 日志汇总 ok/fail/total_rows（worker 末行 "done: ok=X fail=Y rows=Z"）
    ok = fail = total_rows = 0
    for p, log_file, _ in procs:
        try:
            log_text = log_file.read_text(encoding="utf-8", errors="replace")
            m = re.search(r"done: ok=(\d+) fail=(\d+) rows=(\d+)", log_text)
            if m:
                ok += int(m.group(1))
                fail += int(m.group(2))
                total_rows += int(m.group(3))
        except Exception:  # noqa: BLE001
            pass

    if verbose:
        print(f"parallel update done: ok={ok} fail={fail} rows={total_rows} "
              f"({len(tasks)} codes, {elapsed_min:.1f}min)", flush=True)

    return {"ok": ok, "fail": fail, "skip_bj": skip_bj, "skip_done": skip_done,
            "total_rows": total_rows, "processed": len(codes), "details": []}


if __name__ == "__main__":
    seg = "r"
    n_workers = 4
    limit = None
    for a in sys.argv[1:]:
        if a.startswith("--seg="):
            seg = a.split("=", 1)[1]
        elif a.startswith("--workers="):
            n_workers = int(a.split("=", 1)[1])
        elif a.startswith("--limit="):
            limit = int(a.split("=", 1)[1])
    run_parallel(seg=seg, n_workers=n_workers, limit=limit)
