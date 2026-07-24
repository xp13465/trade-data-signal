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
    update_progress_entry,
)
import baostock as bs


def is_conn_error(msg: str) -> bool:
    """检测 BaoStock 连接断开错误（需 re-login）。

    markers 含"用户未登录"/"10001001"(2026-07-24 修复):baostock session 超时
    服务端返"用户未登录"或错误码 10001001,原 markers 不含这两个 -> 不触发 re-login
    -> fail。加这两个 marker 让 session 超时也走 re-login + retry 路径。
    """
    markers = ("Broken pipe", "接收数据异常", "Connection reset",
               "Connection aborted", "EOF occurred", "uranium",
               "用户未登录", "10001001")
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
    mode = "segment"  # "segment"(段模式,按 seg 拉)或 "update"(增量模式,chunk 含 start/end)
    for a in sys.argv[1:]:
        if a.startswith("--seg="):
            seg = a.split("=", 1)[1]
        elif a.startswith("--chunk="):
            chunk_file = a.split("=", 1)[1]
        elif a.startswith("--mode="):
            mode = a.split("=", 1)[1]

    if not chunk_file:
        print("ERROR: --chunk required", flush=True)
        return 1

    chunk_data = json.loads(Path(chunk_file).read_text(encoding="utf-8"))

    init_db()
    bs.login()
    print(f"worker {os.getpid()}: {len(chunk_data)} items, mode={mode}, seg={seg}", flush=True)

    # 段模式:chunk_data = [code, ...], 算 start/end 基于 seg
    # 增量模式:chunk_data = [(code, start, end), ...], start/end 从 task 取
    if mode == "update":
        items = chunk_data  # [(code, start, end), ...]
    else:
        today = dt.date.today().strftime("%Y-%m-%d")
        start = RECENT_START if seg == "r" else OLD_START
        end = today if seg == "r" else OLD_END
        items = [(code, start, end) for code in chunk_data]

    # save_progress 的 key:增量模式固定 'r'(只拉 recent 段增量),段模式用 seg
    prog_key = "r" if mode == "update" else seg

    ok = fail = total_rows = 0
    for i, (code, start, end) in enumerate(items):
        end_yyyymmdd = end.replace("-", "")
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
                    # Update progress (原子更新,避免多 worker 丢失更新)
                    update_progress_entry(code, prog_key, last)
                    success = True
                elif "empty" in msg or "skip" in msg:
                    if mode == "update" and "empty" in msg:
                        # 增量模式 empty: 不标 done(和串行 run_update 一致),下次重试。
                        # empty 可能是数据未出/非交易日,标 done 会跳过下次采,致缺数据。
                        fail += 1
                        print(f"  [{os.getpid()}] {i+1}/{len(items)} {code}: empty "
                              f"(no new data, will retry next run)", flush=True)
                        success = True
                    else:
                        # 段模式 empty/skip: 标 done(避免重试 dead code)
                        ok += 1
                        update_progress_entry(code, prog_key, end_yyyymmdd)
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
                    print(f"  [{os.getpid()}] {i+1}/{len(items)} {code}: FAIL {msg[:100]}",
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
                print(f"  [{os.getpid()}] {i+1}/{len(items)} {code}: ERR "
                      f"{type(e).__name__}: {emsg[:100]}", flush=True)
                success = True  # give up, move on

        if (i + 1) % 20 == 0:
            print(f"  [{os.getpid()}] progress: {i+1}/{len(items)}, ok={ok} "
                  f"fail={fail} rows={total_rows}", flush=True)

    try:
        bs.logout()
    except Exception:  # noqa: BLE001
        pass
    print(f"worker {os.getpid()} done: ok={ok} fail={fail} rows={total_rows}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
