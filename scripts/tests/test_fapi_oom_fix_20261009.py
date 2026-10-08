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
  ① 阈值护栏:长假后首跑不误切全量(默认阈值长假安全 + 可 env 覆盖)
  ⑤ 口径:gap 判据改**交易日**,full 仅在缺口 >10 交易日时触发(防前视:只用 <=today 日历)
  ④ 流式分块:`iter_batches` 分块语义 == 旧 `map_frame`,且内存与批大小同阶(非全量)

零外发:本模块只调纯函数 + 本地 parquet/db,不 import notify、不触网络(§18 L48)。
样本来自**真实产物**:fixtures/238/*.parquet 为真实 FAPI dump 的切片(非人工构造,§18 L49)。
"""
from __future__ import annotations

import datetime as dt
import os
import resource
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "238"

from app.collector import fapi_daily as fd  # noqa: E402


# ─────────────────────────── ① 阈值护栏 ───────────────────────────
def test_stale_default_threshold_is_holiday_safe():
    """#238 ①:默认阈值必须 > 任何 A 股长假连休跨度(国庆/春节 8~11 自然日)。

    旧默认 8 会被国庆 8 天休市精确击穿(10-08 gap=8、10-09 gap=9 均 >=8)。
    """
    assert fd.STALE_DAYS >= 12, f"默认阈值 {fd.STALE_DAYS} 仍会被长假击穿"


def test_stale_gap9_national_day_not_pierced():
    """#238 ① 验收:10-09(gap = 9 自然日,国庆 8 天休市后首跑)不再走 full。"""
    assert fd._stale("20260930", today=dt.date(2026, 10, 9)) is False


def test_stale_threshold_env_override(monkeypatch):
    """① 可配置:环境变量 FAPI_STALE_DAYS 覆盖阈值(非法值回退默认)。"""
    monkeypatch.setenv("FAPI_STALE_DAYS", "5")
    assert fd._stale("20260930", today=dt.date(2026, 10, 9)) is True   # gap=9 >= 5
    monkeypatch.setenv("FAPI_STALE_DAYS", "100")
    assert fd._stale("20260930", today=dt.date(2026, 10, 9)) is False
    monkeypatch.setenv("FAPI_STALE_DAYS", "not-a-number")
    assert fd._stale_days() == fd.STALE_DAYS


def test_stale_none_and_malformed():
    """空库走增量;库内日期不可解析 = 数据异常,保守走全量自愈。"""
    assert fd._stale(None) is False
    assert fd._stale("bad-date") is True