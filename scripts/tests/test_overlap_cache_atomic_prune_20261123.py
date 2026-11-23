#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""holdings_overlap 缓存原子写 + 过期剪枝用例(2026-11-23)。

覆盖:
  ① 原子写失败路径:os.replace 抛错时旧缓存逐字节不变、不留 .tmp 残骸;
  ② 保存时剪枝:TTL 内保留、超 TTL/恰好 TTL/缺 cached_at/结构损坏一律丢弃;
  ③ 冻结红线:文件名、父目录、resolve 推导路径与缓存条目格式均不变。

CI 只装 pytest/numpy/pandas 等,未装 requests/akshare;本文件按需注入 stub 模块后
按文件路径加载被测模块,不依赖第三方网络/行情库,本机与 CI 行为一致。
"""
import importlib.util
import json
import os
import sys
import types
from pathlib import Path

ROOT = Path(__file__).absolute().parent.parent.parent
SRC = ROOT / "app" / "collector" / "overlap_fetcher.py"

_STUB_NAMES = ("requests", "akshare")


def _load_module():
    """stub requests/akshare 后按路径加载 overlap_fetcher,加载完恢复 sys.modules。"""
    saved = {name: sys.modules.get(name) for name in _STUB_NAMES}
    for name in _STUB_NAMES:
        sys.modules[name] = types.ModuleType(name)
    try:
        spec = importlib.util.spec_from_file_location(
            "overlap_fetcher_under_test", str(SRC)
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        for name, old in saved.items():
            if old is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old


def _entry(cached_at, holders=None):
    return {"cached_at": cached_at, "holders": holders if holders is not None else []}


def test_atomic_write_failure_keeps_old_cache(tmp_path, monkeypatch, capsys):
    """mock os.replace 失败:旧缓存完好、无 .tmp 残骸、只打告警不抛。"""
    mod = _load_module()
    target = tmp_path / "holdings_overlap_cache.json"
    monkeypatch.setattr(mod, "HOLDINGS_CACHE_PATH", target)
    monkeypatch.setattr(mod, "time", types.SimpleNamespace(time=lambda: 1_000_000.0))

    old_payload = {"600000": _entry(999_000.0, [{"fund_code": "510300", "hold_pct": 1.5}])}
    target.write_text(
        json.dumps(old_payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    old_bytes = target.read_bytes()

    def _boom(src, dst):
        raise OSError("模拟 os.replace 失败")

    monkeypatch.setattr(os, "replace", _boom)
    # 不该抛(内部 try/except 吞掉只告警)
    mod._save_holdings_cache({"600000": _entry(990_000.0)})

    assert target.read_bytes() == old_bytes, "replace 失败时旧缓存必须逐字节不变"
    assert list(tmp_path.glob("*.tmp")) == [], "异常路径必须清理临时文件"
    assert "缓存保存失败" in capsys.readouterr().out


def test_save_prunes_expired_entries(tmp_path, monkeypatch):
    """只写回 TTL 内条目;超 TTL/边界/缺字段/结构损坏全部丢弃,格式不变。"""
    mod = _load_module()
    target = tmp_path / "holdings_overlap_cache.json"
    monkeypatch.setattr(mod, "HOLDINGS_CACHE_PATH", target)
    now = 1_800_000_000.0
    monkeypatch.setattr(mod, "time", types.SimpleNamespace(time=lambda: now))

    cache = {
        "600000": _entry(now - 3600, [{"fund_code": "510300", "fund_name": "沪深300ETF",
                                       "hold_pct": 2.1, "report_date": "2026-09-30"}]),
        "600001": _entry(now - 6 * 86400, [{"fund_code": "159915"}]),
        "600002": _entry(now - 8 * 86400),
        "600003": _entry(now - mod.HOLDINGS_CACHE_TTL),  # 恰好 TTL = 过期
        "600004": {"holders": []},                       # 缺 cached_at
        "600005": "not-a-dict",                          # 结构损坏
        "600006": {"cached_at": "abc", "holders": []},   # cached_at 非数值(脏数据)
    }
    mod._save_holdings_cache(cache)

    saved = json.loads(target.read_text(encoding="utf-8"))
    assert set(saved) == {"600000", "600001"}
    assert saved["600000"] == cache["600000"], "保留条目内容必须逐字段不变"
    assert list(tmp_path.glob("*.tmp")) == []


def test_frozen_path_and_filename(monkeypatch):
    """冻结红线:文件名/父目录/路径推导(.resolve 防分叉)不变。"""
    mod = _load_module()
    p = mod.HOLDINGS_CACHE_PATH
    assert p.name == "holdings_overlap_cache.json"
    assert p.parent.name == "data"
    expected = SRC.resolve().parent.parent.parent / "data" / "holdings_overlap_cache.json"
    assert p == expected


def test_load_roundtrip(tmp_path, monkeypatch):
    """加载侧行为不变:文件不存在返回 {},保存后可原样加载。"""
    mod = _load_module()
    target = tmp_path / "holdings_overlap_cache.json"
    monkeypatch.setattr(mod, "HOLDINGS_CACHE_PATH", target)
    now = 1_800_000_000.0
    monkeypatch.setattr(mod, "time", types.SimpleNamespace(time=lambda: now))

    assert mod._load_holdings_cache() == {}

    entry = _entry(now - 60, [{"fund_code": "510300"}])
    mod._save_holdings_cache({"600000": entry})
    assert mod._load_holdings_cache() == {"600000": entry}
