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

# ab-#37 共享熔断 flag(与 baostock_parallel.BLACKLIST_FLAG 同路径):任一 worker 撞
# 10001011 黑名单写此文件,其余 worker 下一 code 读到即短路(账号/IP 级封禁对所有并发
# 连接同效,不各自盲试)。run_update_parallel 启动/结束时清理。
_BLACKLIST_FLAG = Path(__file__).absolute().parent.parent.parent / "data" / "baostock_blacklist.flag"


def _set_blacklist_flag():
    """写共享熔断 flag(写失败不阻塞采集,熔断仍以本地 circuit_open 为准)。"""
    try:
        _BLACKLIST_FLAG.write_text(dt.datetime.now().isoformat(), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def is_conn_error(msg: str) -> bool:
    """检测 BaoStock 连接断开错误（需 re-login）。

    markers 含"用户未登录"/"10001001"(2026-07-24 修复):baostock session 超时
    服务端返"用户未登录"或错误码 10001001,原 markers 不含这两个 -> 不触发 re-login
    -> fail。加这两个 marker 让 session 超时也走 re-login + retry 路径。
    """
    markers = ("Broken pipe", "接收数据异常", "Connection reset",
               "Connection aborted", "EOF occurred", "uranium",
               "用户未登录", "10001001", "10001011")
    return any(m in msg for m in markers)


# 2026-08-14 update_all 提速 方案A第一步:服务端"黑名单用户"错误码 10001011。
# 8-14 17:50 update_all:baostock 对 4 并发中 2 个连接返 10001011,worker0/1 共 825 fail,
# 原 markers 不含 10001011 -> 被封连接不走 re-login,825 code 白等(18.9min)。
#
# 2026-08-14 reviewer FAIL P1 修复:原实现只加 marker 会触发 relogin 盲试放大——
# relogin() 返回值被忽略,内部固定 sleep(2+random(0.5,1.5))≈2.5s,即使 bs.login()
# 仍返 10001011(账号/IP 级封禁,relogin 无法解封)也 sleep 后重试。实证 8-14 worker0/1
# 共 825 fail 全为 10001011,被封 worker 对每个 code 盲试 2 次 relogin ≈70-80min 额外耗时。
# 修复:①relogin 返回 False(login 失败)立即熔断,不做盲重试 ②检测到 10001011 整 worker
# 熔断,短路后续所有 code(账号/IP 级封禁对后续 code 必然同样失败)。


def relogin():
    """重新登录 BaoStock。

    返回 True=登录成功(可重试);False=登录失败(如 10001011 黑名单,relogin 无法解封)。
    """
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
    circuit_open = False  # 10001011 黑名单熔断:账号/IP 级封禁,短路后续所有 code
    for i, (code, start, end) in enumerate(items):
        if circuit_open:
            # 熔断:后续 code 对同一账号/IP 必然同样失败,直接 fail 不盲试(提速核心)
            fail += 1
            if (i + 1) % 20 == 0 or i == 0:
                print(f"  [{os.getpid()}] 熔断: baostock 账号/IP 被封(10001011),"
                      f"跳过后续 code,当前已处理 {i}/{len(items)}", flush=True)
            continue
        if not circuit_open and _BLACKLIST_FLAG.exists():
            # ab-#37 共享熔断:其他 worker 撞 10001011 后写 flag,本 worker 下一 code 短路
            circuit_open = True
            print(f"  [{os.getpid()}] 检测到共享黑名单 flag(其他 worker 已熔断),短路后续 code",
                  flush=True)
            fail += 1
            continue
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
                        if "10001011" in msg:
                            # 账号/IP 级封禁,relogin 无法解封 -> 整 worker 熔断
                            circuit_open = True
                            _set_blacklist_flag()  # ab-#37:写共享 flag 通知其他 worker
                            fail += 1
                            print(f"  [{os.getpid()}] {i+1}/{len(items)} {code}: "
                                  f"检测到 10001011 黑名单,整 worker 熔断(不再盲试)", flush=True)
                            success = True  # 跳出 while,外层短路后续 code
                            break
                        if not relogin():
                            # login 仍失败(大概率同为 10001011) -> 熔断,不盲试
                            circuit_open = True
                            _set_blacklist_flag()  # ab-#37:写共享 flag 通知其他 worker
                            fail += 1
                            print(f"  [{os.getpid()}] {i+1}/{len(items)} {code}: "
                                  f"relogin 失败(账号/IP 封禁),整 worker 熔断", flush=True)
                            success = True
                            break
                        print(f"  [{os.getpid()}] {code}: conn error, re-login "
                              f"(retry {retries+1}/3): {msg[:80]}", flush=True)
                        retries += 1
                        continue
                    fail += 1
                    print(f"  [{os.getpid()}] {i+1}/{len(items)} {code}: FAIL {msg[:100]}",
                          flush=True)
                    success = True  # give up, move on
            except Exception as e:  # noqa: BLE001
                emsg = str(e)
                if is_conn_error(emsg) and retries < 2:
                    if "10001011" in emsg:
                        circuit_open = True
                        _set_blacklist_flag()  # ab-#37:写共享 flag 通知其他 worker
                        fail += 1
                        print(f"  [{os.getpid()}] {i+1}/{len(items)} {code}: "
                              f"异常含 10001011 黑名单,整 worker 熔断", flush=True)
                        success = True
                        break
                    if not relogin():
                        circuit_open = True
                        _set_blacklist_flag()  # ab-#37:写共享 flag 通知其他 worker
                        fail += 1
                        print(f"  [{os.getpid()}] {i+1}/{len(items)} {code}: "
                              f"relogin 失败(账号/IP 封禁),整 worker 熔断", flush=True)
                        success = True
                        break
                    print(f"  [{os.getpid()}] {code}: exc conn error, re-login "
                          f"(retry {retries+1}/3): {emsg[:80]}", flush=True)
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
    if circuit_open:
        # 熔断标记供上层日志/运维识别;退出码 3 = 封禁(baostock_parallel 正则仍匹配 done 行)
        print(f"[CIRCUIT-BREAK] worker {os.getpid()} baostock 10001011 黑名单熔断,"
              f"fail={fail} 中大部分为封禁导致,本次采集因封禁未完成", flush=True)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
