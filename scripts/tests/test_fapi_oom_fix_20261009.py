# -*- coding: utf-8 -*-
"""#238 trade-fapi-daily OOM 治本(2026-10-09)自测。

背景:docs/ops/fapi-daily-oom-rootcause-20261008.md —— 2026-10-08 18:10 该 unit 处理
10 年全量 dump(1032 万行 / 181MB)时 python 内存冲到 anon-rss 2.0GB,3.8GB RAM + 1GB
swap 双满 → global_oom,整机冻结 47 分钟。两个可治本主矛盾:

  · 触发口径错:`STALE_DAYS=8`(自然日)被国庆 8 天休市**精确击穿** ⇒ 节后首跑必走全量;
    而 `daily-k-10d` dump 本就覆盖 10 个交易日,根本不需要全量。
  · full 路径全程物化:`read_table → to_pandas → sort → map_frame(1032 万 tuple list)
    → executemany` 一次性吃满内存,在 3.6GB 小机上必然 OOM。

本测试覆盖三件:
  ① 阈值护栏:gap 判据=**交易日**(默认 10),长假后首跑不误切全量 + 可 env 覆盖
  ⑤ 口径与防前视:只用 <=today 的日历(gate 显式),未来日期入参不影响判定
  ④ 流式分块:`iter_batches` 分块语义 == 旧 `map_frame`;真实 dump 峰值实测远低于旧全量

零外发:本模块只调纯函数 + 本地 parquet(`§18 L48`:不 import notify、不触网络)。
样本来自**真实产物**:fixtures/238/sample.parquet 为真实 FAPI dump 的切片(非人工构造,
`§18 L49`);内存实测用真实 10 年 dump(本机 / 云上产物,/Users 路径不存在时自动 skip)。
"""
from __future__ import annotations

import datetime as dt
import subprocess
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "238"
SAMPLE = FIXTURES / "sample.parquet"
PROBE = Path(__file__).resolve().parent / "fapi_oom_mem_probe.py"
CAL_CACHE = ROOT / "data" / "trade_dates.txt"
REAL_DUMP = next((p for p in (ROOT / "data" / "daily-k.parquet",
                              Path("/Users/linhuichen/code/trade/data/daily-k.parquet"))
                  if p.exists()), None)

from app.collector import fapi_daily as fd  # noqa: E402

# 一段"含未来日期"的完整交易日历(2026-10-09 之后还有 10-12..10-22),用于防前视机检
FULL_CAL = ["20261008", "20261009", "20261012", "20261013", "20261014",
            "20261015", "20261016", "20261019", "20261020", "20261021", "20261022"]


# ─────────────────────────── ① 阈值护栏(交易日口径) ───────────────────────────
def test_stale_default_threshold_covers_10d_window():
    """默认阈值必须 ≥ daily-k-10d dump 的覆盖能力(10 交易日),否则每次跑都浪费全量。"""
    assert fd.STALE_TRADING_DAYS >= 10, f"默认 {fd.STALE_TRADING_DAYS} < 10 交易日窗口"


def test_stale_long_holiday_first_day_trading_day_caliber():
    """长假后首跑:自然日 gap=9(国庆 8 天休市)但**交易日** gap=2 ⇒ 不走 full。

    旧口径 STALE_DAYS=8(自然日)在此处 gap=8/9 ≥ 8 被精确击穿 ⇒ 节后必全量。
    """
    cal = lambda lo, hi: ["20261008", "20261009"]  # noqa: E731
    assert fd._stale("20260930", today=dt.date(2026, 10, 9), trading_days_fn=cal) is False


@pytest.mark.skipif(not CAL_CACHE.exists(), reason="交易日历缓存不在本机(CI 常态)")
def test_stale_long_holiday_first_day_real_calendar():
    """同一断言用**真实日历**复核(app/calendar.trading_days_between)。"""
    assert fd._stale("20260930", today=dt.date(2026, 10, 9)) is False


def test_stale_normal_day_caliber():
    """常规日:gap 3 交易日 ⇒ 增量;gap 11 交易日(超 10d 窗口)⇒ 才切 full。"""
    def cal_n(n):
        base = dt.date(2026, 10, 1)
        return [(base + dt.timedelta(days=1 + i)).strftime("%Y%m%d") for i in range(n)]

    cal3 = lambda lo, hi: cal_n(3)   # noqa: E731  10-02/10-03/10-04
    cal11 = lambda lo, hi: cal_n(11)  # noqa: E731
    today = dt.date(2026, 10, 20)
    assert fd._stale("20261001", today=today, trading_days_fn=cal3) is False
    assert fd._stale("20261001", today=today, trading_days_fn=cal11) is True


def test_stale_threshold_env_override(monkeypatch):
    """① 可配置:环境变量 FAPI_STALE_TRADING_DAYS 覆盖阈值(非法值回退默认)。"""
    cal = lambda lo, hi: ["20261008", "20261009"]  # noqa: E731  gap=2 交易日
    monkeypatch.setenv("FAPI_STALE_TRADING_DAYS", "1")
    assert fd._stale("20260930", today=dt.date(2026, 10, 9), trading_days_fn=cal) is True
    monkeypatch.setenv("FAPI_STALE_TRADING_DAYS", "100")
    assert fd._stale("20260930", today=dt.date(2026, 10, 9), trading_days_fn=cal) is False
    monkeypatch.setenv("FAPI_STALE_TRADING_DAYS", "not-a-number")
    assert fd._stale_trading_days() == fd.STALE_TRADING_DAYS


def test_stale_none_and_malformed():
    """空库走增量;库内日期不可解析 = 数据异常,保守走全量自愈。"""
    assert fd._stale(None) is False
    assert fd._stale("bad-date") is True


# ─────────────────────────── ⑤ 防前视机检(§5.1⑥③) ───────────────────────────
def test_stale_lookahead_gate_ignores_future_days():
    """日历源含 >today 的未来日期也不影响判定(显式 `d <= today_s` 闸门)。

    反证:若不做闸门,同一日历会数出 11 个交易日 > 阈值 10 → 会误判 full,
    即该用例能真正区分"有闸门"与"无闸门"(非恒真式)。
    """
    today = dt.date(2026, 10, 9)
    full = lambda lo, hi: list(FULL_CAL)                                # noqa: E731
    trunc = lambda lo, hi: [d for d in FULL_CAL if d <= "20261009"]      # noqa: E731
    a = fd._stale("20260930", today=today, trading_days_fn=full)
    b = fd._stale("20260930", today=today, trading_days_fn=trunc)
    assert a is False and b is False
    assert a == b
    # 反证(无闸门会数到 11 > 10 ⇒ True):
    assert sum(1 for d in FULL_CAL if d > "20260930") == 11 > fd.STALE_TRADING_DAYS


def test_stale_lower_bound_excludes_latest_day(monkeypatch):
    """下界闸门:==latest 的当天不计入缺口(与 (latest, today] 口径一致)。

    阈值设 2 使断言有区分度:gap = 10-08 + 10-09 = 2 ⇒ 2 > 2 为假;
    若把 ==latest 的 09-30 也误算进去则 gap=3 > 2 为真。
    """
    cal = lambda lo, hi: ["20260930", "20261008", "20261009"]  # noqa: E731
    monkeypatch.setenv("FAPI_STALE_TRADING_DAYS", "2")
    assert fd._stale("20260930", today=dt.date(2026, 10, 9), trading_days_fn=cal) is False


# ─────────────────────────── ④ 流式分块(语义等价 + 守卫) ───────────────────────────
def _reference_rows():
    return fd.map_frame(pq.read_table(SAMPLE).to_pandas())


@pytest.mark.parametrize("bs", [1, 7, 13, 120, 999])
def test_streaming_equals_reference_oracle(bs):
    """任意批大小(含跨批切组)流式结果逐位 == 旧参照实现 `map_frame`。"""
    ref = _reference_rows()
    got: list[tuple] = []
    st = fd.process_parquet(str(SAMPLE), batch_size=bs, on_rows=lambda r: got.extend(r))
    assert got == ref
    assert st["rows"] == len(ref) and st["dup"] == 0


def test_streaming_asserts_amount_semantics():
    """真实切片 turnover>volume 占比 100% ⇒ 命名坑守卫通过(样本非人工构造)。"""
    st = fd.process_parquet(str(SAMPLE))
    assert st["amt_ok"] == st["rows"] == len(_reference_rows())


def test_iter_groups_guard_rejects_ungrouped_dump(tmp_path):
    """dump 未按 thscode 连续分组 ⇒ 抛错中止,不静默把 pct_change 算错。"""
    df = pq.read_table(SAMPLE).to_pandas().sort_values(
        ["date_ms", "thscode"]).reset_index(drop=True)  # 交错 thscode
    p = tmp_path / "ungrouped.parquet"
    pq.write_table(pa.Table.from_pandas(df), p)
    with pytest.raises(RuntimeError, match="未按 thscode 连续分组"):
        list(fd._iter_groups(str(p), batch_size=1000))


@pytest.mark.skipif(REAL_DUMP is None,
                    reason="真实 10 年 dump 不在本机(CI 常态),内存实测跳过")
def test_stream_peak_under_target_and_far_below_legacy():
    """真实 1032 万行 dump 上实测峰值 RSS:流式 <300MB 目标(容差 320),
    且比旧全量物化路径低一个量级(≥3x)。"""
    s_peak, s_rows = _run_probe("stream", fd.BATCH_SIZE)
    assert s_rows > 1_000_000
    assert s_peak < 320, f"流式峰值 {s_peak:.0f}MB 超目标 300MB(容差 320)"
    l_peak, l_rows = _run_probe("legacy")
    assert l_rows == s_rows
    assert s_peak * 3 < l_peak, f"流式 {s_peak:.0f}MB vs 旧全量 {l_peak:.0f}MB 未达量级降幅"


def _run_probe(mode: str, bs: int | None = None) -> tuple[float, int]:
    cmd = [sys.executable, str(PROBE), mode, str(REAL_DUMP)]
    if bs is not None:
        cmd.append(str(bs))
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=1200)
    assert out.returncode == 0, (out.stdout[-500:], out.stderr[-2000:])
    line = [ln for ln in out.stdout.splitlines() if ln.startswith("PEAK_RSS_MB=")][-1]
    kv = dict(x.split("=") for x in line.split())
    return float(kv["PEAK_RSS_MB"]), int(kv["ROWS"])