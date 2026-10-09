#!/usr/bin/env python3
"""#238 fapi OOM 内存探针:在**真实 dump** 上实测峰值 RSS(stream 流式 vs legacy 旧全量)。

用法:
    python3 scripts/tests/fapi_oom_mem_probe.py <stream|legacy> <parquet> [batch_size]

输出一行:``PEAK_RSS_MB=<n> BASELINE_MB=<b> ROWS=<r>``

峰值取 ``resource.getrusage(RUSAGE_SELF).ru_maxrss``(进程级峰值),按平台换算:
macOS 单位=字节,Linux 单位=KB。**必须在独立子进程里跑**(ru_maxrss 是进程级峰值,
不能在同一进程里先后测两种模式,否则峰值会互相污染)。

口径:只读,不写库、不触网络(§18 L48 零外发约束)。``legacy`` 复用
``app.collector.fapi_daily.map_frame``(保留的语义参照)= 复现 #238 之前的全量物化路径
(read_table → to_pandas → sort → 1032 万 tuple list),用于对照"内存需求侧"的量级差。
"""
from __future__ import annotations

import platform
import resource
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))
from _ci_stubs import install_missing_third_party_stubs  # noqa: E402

install_missing_third_party_stubs()  # 本脚本是裸子进程, 无 conftest: CI 缺 requests 须自补
# (与 gen_fapi_golden_238.py 的 oracle 子进程同一根因/同一函数; 细则见 _ci_stubs.py)


def _peak_mb() -> float:
    v = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if platform.system() == "Darwin":  # macOS: 字节
        return v / 1024 / 1024
    return v / 1024  # Linux: KB


def _stream(path: str, batch_size: int) -> int:
    from app.collector import fapi_daily as fd
    n = 0

    def _sink(rows):
        nonlocal n
        n += len(rows)
    fd.process_parquet(path, batch_size=batch_size, on_rows=_sink)
    return n


def _legacy(path: str) -> int:
    import pyarrow.parquet as pq
    from app.collector import fapi_daily as fd
    table = pq.read_table(path)
    df = table.to_pandas()
    _ = int(df.duplicated(subset=["thscode", "date_ms"]).sum())
    _ = (df["turnover"].abs() > df["volume"].abs()).mean()
    rows = fd.map_frame(df)
    return len(rows)


def main(argv: list[str]) -> int:
    mode, path = argv[0], argv[1]
    bs = int(argv[2]) if len(argv) > 2 else 100_000
    base = _peak_mb()
    if mode == "stream":
        rows = _stream(path, bs)
    elif mode == "legacy":
        rows = _legacy(path)
    else:
        print(f"unknown mode {mode}", file=sys.stderr)
        return 2
    print(f"PEAK_RSS_MB={_peak_mb():.0f} BASELINE_MB={base:.0f} ROWS={rows}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))