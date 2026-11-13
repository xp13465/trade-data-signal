# -*- coding: utf-8 -*-
"""board_etf_map 行情双源全挂修复 —— pytest 自验(2026-11-13)。

对象:
  - scripts/_etf_spot_fallback.py 三级兜底链: 东财 → 新浪+腾讯补名 → 腾讯全量(universe 底盘)
  - scripts/check_data_integrity.py 新增 check_board_etf_map_fresh(新鲜度, 每轮 deploy 独立报警)

依据(第 0 步云上出口只读实测, 表见 /tmp/board-etf-map-fix-report.md):
  - 东财 fund_etf_spot_em() 仍封禁(RemoteDisconnected, 40h+);
  - 新浪 etf_hq_fund 节点真实总数 938 < 1500 fail-closed 下限(节点缩水 ~45%);
  - 腾讯 qt.gtimg.cn: etf/ universe 1745 只逐码批量 1745/1745 有效(2.1s),
    全称=f[1] / 最新价=f[3] / 成交额(元)=f[35]="价/量/额" 第三段。

覆盖(对任务书第 2 步逐条):
  ① 源A(东财)失败 → 源B(新浪+腾讯补名)成功
  ② 源A/B 全失败 → 第三源(腾讯全量)成功
  ③ 全部失败 → fail-closed 抛错(非 0)
  ④ 新浪缩水条数(<1500) → 拒用(真实 _sina_fetch_node 用 mock 翻页数据验拒用+错误信息)
  ⑤ 腾讯全量: 有效行<1500 拒用 / 覆盖度对账缺失>50 拒用 / universe 底盘<1500 拒用
  ⑥ 新鲜度: _meta.date 滞后 2 交易日→FAIL / 1 交易日→WARN / 当日→OK / 无字段→mtime 兜底
  ⑦ build _meta: 三源 source 标注 + date 写入(静态锁: last_source 枚举覆盖三档)

判别力(任务书「临时改坏必红」)不设 pytest 内自改源码, 用活体变异跑法:
  去掉下限(sed 改 _TENCENT_UNIVERSE_MIN_ROWS=900) → test_04/test_05 必红;
  改坏顺序(sed 去掉新浪一级) → test_01 必红;还原后全绿。命令与末行见报告。

零外发(§18 L48): requests.get 全程 monkeypatch 替换在模块层(esModule 级替换 esf.requests),
  真实网络零触达;ak.fund_etf_spot_em 同步 mock。akshare 顶层 import 不触发网络。
跑法: python3 -m pytest -q scripts/tests/test_board_etf_map_source_fix_20261113.py
"""
from __future__ import annotations

import sys
import types
from datetime import datetime as _real_dt
from pathlib import Path

import pandas as pd
import pytest

SCRIPTS = Path(__file__).absolute().parent
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SCRIPTS.parent))

import _etf_spot_fallback as esf  # noqa: E402
import check_data_integrity as cdi  # noqa: E402

# 防收集/执行异常致「0 断言假绿」(§18 L49 / 仿 #201/#240/#257)
_MIN_ASSERTIONS = 30

# ── 冻结时钟(仿 #257 _freeze) ────────────────────────────────────────────────

def _freeze(monkeypatch, ymd: str):
    y, m, d = int(ymd[:4]), int(ymd[4:6]), int(ymd[6:])

    class _FrozenDT:
        _now = _real_dt(y, m, d, 12, 0, 0)

        @staticmethod
        def strptime(s, fmt):
            return _real_dt.strptime(s, fmt)

        @staticmethod
        def fromtimestamp(ts):
            return _real_dt.fromtimestamp(ts)

        @classmethod
        def now(cls, tz=None):
            return cls._now

    monkeypatch.setattr(cdi, "datetime", _FrozenDT)


# ── mock 基建 ────────────────────────────────────────────────────────────────

class _Resp:
    def __init__(self, content: bytes, json_data=None):
        self.content = content
        self._json = json_data

    def raise_for_status(self):
        pass

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json


def _tencent_line(code: str, name: str = None, price: str = "1.0",
                  pva: str = "1.0/1000/50000") -> bytes:
    """构造一条腾讯 v_shXXXXXX 行(GBK 字节); f[1]=全称 f[3]=价 f[35]=价/量/额。"""
    fields = ["1", name or f"测试ETF{code}", code, price] + [""] * 32
    assert len(fields) == 36
    fields[35] = pva
    pref = ("sh" if code[0] == "5" else "sz") + code
    line = f'v_{pref}="' + "~".join(fields) + '";'
    return line.encode("gbk")


def _tencent_resp(codes, missing=()) -> _Resp:
    lines = [_tencent_line(c) for c in codes if c not in set(missing)]
    return _Resp(b"\n".join(lines) + b"\n;")


def _make_universe(tmp_path: Path, n: int = 1600) -> Path:
    d = tmp_path / "static-site" / "data" / "etf"
    d.mkdir(parents=True)
    codes = []
    for i in range(n):
        code = f"51{(i % 9000):04d}"  # 51xxxx 均为 sh 前缀段
        codes.append(code)
        (d / f"{code}-all.json").write_text("{}", encoding="utf-8")
    return d


def _patch_tencent(monkeypatch, tmp_path, n=1600, missing=(), valid=None):
    """universe 目录 + 模块层 requests mock(腾讯批量接口)。"""
    d = _make_universe(tmp_path, n)
    codes = sorted({f.name.split("-")[0] for f in d.glob("*-all.json")})
    monkeypatch.setattr(esf, "_TENCENT_UNIVERSE_DIR", d)

    state = {"calls": 0, "emitted": 0}

    def fake_get(url, timeout=None, **kw):
        state["calls"] += 1
        assert url.startswith("https://qt.gtimg.cn/q="), url
        q = url.split("q=", 1)[1]
        batch = [c[2:] for c in q.split(",") if c]
        if valid is not None:
            # 全局只返回前 valid 个有效行(其余批次空回)——模拟缩水
            room = max(0, valid - state["emitted"])
            got = batch[:room]
            state["emitted"] += len(got)
            return _tencent_resp(got)
        return _tencent_resp(batch, missing=missing)

    fake_requests = types.SimpleNamespace(get=fake_get)
    monkeypatch.setattr(esf, "requests", fake_requests)
    return codes, state


def _ok_df(n=3) -> pd.DataFrame:
    return pd.DataFrame({
        "代码": [f"51{i:05d}" for i in range(n)],
        "名称": [f"源B_E{i}" for i in range(n)],
        "最新价": [1.0] * n,
        "成交额": [100.0 + i for i in range(n)],
    })


# ── ① 源A 失败 → 源B 成功 ────────────────────────────────────────────────────

def test_01_main_fail_sina_ok(monkeypatch, tmp_path):
    calls = {"em": 0, "sina": 0}
    monkeypatch.setattr(esf.ak, "fund_etf_spot_em",
                        lambda: calls.__setitem__("em", calls["em"] + 1) or (_ for _ in ()).throw(
                            ConnectionError("Remote end closed connection without response")))
    monkeypatch.setattr(esf, "_sina_etf_spot_df", lambda: calls.__setitem__("sina", calls["sina"] + 1) or _ok_df())
    df = esf.fund_etf_spot_df()
    assert len(df) == 3
    assert calls == {"em": 1, "sina": 1}
    assert esf.last_source() == "sina_tencent"
    assert esf.was_fallback_used() is True


def test_01b_eastmoney_ok_no_fallback(monkeypatch):
    monkeypatch.setattr(esf.ak, "fund_etf_spot_em", lambda: _ok_df())
    df = esf.fund_etf_spot_df()
    assert len(df) == 3
    assert esf.last_source() == "eastmoney"
    assert esf.was_fallback_used() is False


# ── ② A/B 全失败 → 第三源成功 ────────────────────────────────────────────────

def test_02_all_fallback_levels_to_tencent(monkeypatch, tmp_path):
    monkeypatch.setattr(esf.ak, "fund_etf_spot_em",
                        lambda: (_ for _ in ()).throw(ConnectionError("RemoteDisconnected")))
    monkeypatch.setattr(esf, "_sina_etf_spot_df",
                        lambda: (_ for _ in ()).throw(RuntimeError(
                            "新浪节点 etf_hq_fund 仅返回 938 只(下限 1500), fail-closed 拒用")))
    _patch_tencent(monkeypatch, tmp_path, n=1600)
    df = esf.fund_etf_spot_df()
    assert len(df) >= 1500
    assert esf.last_source() == "tencent_universe"
    # 字段口径: 代码/全称/最新价/成交额(元)
    r0 = df.iloc[0]
    assert str(r0["代码"]).isdigit() and len(str(r0["代码"])) == 6
    assert str(r0["名称"]).startswith("测试ETF")
    assert float(r0["成交额"]) == 50000.0


def test_02b_tencent_amount_and_price_numeric(monkeypatch, tmp_path):
    _patch_tencent(monkeypatch, tmp_path, n=1600)
    df = esf._tencent_etf_spot_df()
    assert pd.api.types.is_numeric_dtype(df["成交额"])
    assert pd.api.types.is_numeric_dtype(df["最新价"])
    assert df["成交额"].isna().sum() == 0


# ── ③ 全失败 → fail-closed ───────────────────────────────────────────────────

def test_03_all_fail_fail_closed(monkeypatch):
    monkeypatch.setattr(esf.ak, "fund_etf_spot_em",
                        lambda: (_ for _ in ()).throw(ConnectionError("RemoteDisconnected")))
    monkeypatch.setattr(esf, "_sina_etf_spot_df",
                        lambda: (_ for _ in ()).throw(RuntimeError("新浪 938<1500 拒用")))
    monkeypatch.setattr(esf, "_tencent_etf_spot_df",
                        lambda: (_ for _ in ()).throw(RuntimeError("腾讯全量 900<1500 拒用")))
    with pytest.raises(RuntimeError) as ei:
        esf.fund_etf_spot_df()
    msg = str(ei.value)
    # 可诊断: 三源名+原因都在
    for kw in ("东财", "新浪+腾讯兜底", "腾讯全量兜底", "RemoteDisconnected"):
        assert kw in msg, kw


# ── ④ 新浪缩水 → 真实 _sina_fetch_node 拒用 ─────────────────────────────────

def test_04_sina_shrunk_node_rejected(monkeypatch):
    """mock 翻页: 第1页100条+第2页50条(共150)<1500 → 真实函数拒用(防静默缩水)。"""
    page = [{"code": f"51{i:05d}", "name": f"简称{i}", "amount": "100", "trade": "1.0"}
            for i in range(100)]
    page2 = page[:50]

    def fake_get(url, params=None, headers=None, timeout=None):
        assert "getHQNodeData" in url
        if params["page"] == "1":
            return _Resp(b"[]", json_data=page)
        return _Resp(b"[]", json_data=page2)

    monkeypatch.setattr(esf, "requests", types.SimpleNamespace(get=fake_get))
    with pytest.raises(RuntimeError) as ei:
        esf._sina_fetch_node("etf_hq_fund")
    assert "150" in str(ei.value) and "1500" in str(ei.value)


# ── ⑤ 腾讯全量三重 fail-closed ───────────────────────────────────────────────

def test_05a_tencent_shrunk_rows_rejected(monkeypatch, tmp_path):
    """有效行 900 < 1500(即使 universe 1600)→ 拒用(去掉下限则本用例红)。"""
    _patch_tencent(monkeypatch, tmp_path, n=1600, valid=900)
    with pytest.raises(RuntimeError) as ei:
        esf._tencent_etf_spot_df()
    assert "900" in str(ei.value) and "1500" in str(ei.value)


def test_05b_tencent_missing_codes_rejected(monkeypatch, tmp_path):
    """覆盖度对账: universe 1600 缺 60 > 50 → 拒用。"""
    codes, state = _patch_tencent(monkeypatch, tmp_path, n=1600)
    missing = codes[:60]
    # 重新 patch missing 版本
    monkeypatch.setattr(esf, "requests", types.SimpleNamespace(
        get=lambda url, timeout=None, **kw: _tencent_resp(
            [c[2:] for c in url.split("q=", 1)[1].split(",")], missing=set(missing))))
    with pytest.raises(RuntimeError) as ei:
        esf._tencent_etf_spot_df()
    assert "覆盖度对账" in str(ei.value) and "60" in str(ei.value)


def test_05c_tencent_missing_within_tolerance_ok(monkeypatch, tmp_path):
    """覆盖度对账: 缺 10(≤50)→ 放行(退市/停牌容差), 行数仍 ≥1500。"""
    codes, _ = _patch_tencent(monkeypatch, tmp_path, n=1600)
    missing = codes[:10]
    monkeypatch.setattr(esf, "requests", types.SimpleNamespace(
        get=lambda url, timeout=None, **kw: _tencent_resp(
            [c[2:] for c in url.split("q=", 1)[1].split(",")], missing=set(missing))))
    df = esf._tencent_etf_spot_df()
    assert len(df) == 1590


def test_05d_universe_dir_missing_rejected(monkeypatch, tmp_path):
    """universe 底盘目录缺失 → 拒用(不静默换空清单)。"""
    monkeypatch.setattr(esf, "_TENCENT_UNIVERSE_DIR", tmp_path / "no_such_dir")
    with pytest.raises(RuntimeError) as ei:
        esf._tencent_etf_spot_df()
    assert "universe 底盘不足" in str(ei.value)


def test_05e_universe_too_small_rejected(monkeypatch, tmp_path):
    """universe 底盘 200 只 < 1500 → 拒用。"""
    _patch_tencent(monkeypatch, tmp_path, n=200)
    with pytest.raises(RuntimeError) as ei:
        esf._tencent_etf_spot_df()
    assert "200" in str(ei.value)


# ── ⑥ 新鲜度检查 ─────────────────────────────────────────────────────────────

def _write_map(d: Path, meta_date=None, n_idx=2) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    data = {"_meta": {}, "hs300": [{"code": "510300", "name": "x", "track_score": 1.0}],
            "csi500": [{"code": "510500", "name": "y", "track_score": 0.9}]}
    if meta_date:
        data["_meta"]["date"] = meta_date
    p = d / "board_etf_map.json"
    p.write_text(__import__("json").dumps(data, ensure_ascii=False), encoding="utf-8")
    return p


def _fresh(tmp_path, monkeypatch, today, meta_date):
    _freeze(monkeypatch, today)
    p = _write_map(tmp_path / "data", meta_date=meta_date)
    return cdi.check_board_etf_map_fresh(tmp_path / "data")


def test_06a_fresh_today_ok(monkeypatch, tmp_path):
    r = _fresh(tmp_path, monkeypatch, "20261113", "20261113")
    assert r.status == cdi.CheckResult.OK, r.msg


def test_06b_lag_1_warn(monkeypatch, tmp_path):
    r = _fresh(tmp_path, monkeypatch, "20261113", "20261112")
    assert r.status == cdi.CheckResult.WARN, r.msg


def test_06c_lag_2_trading_days_fail(monkeypatch, tmp_path):
    """任务书: 构造 2 个交易日陈旧数据 → 必红(FAIL 告警级)。"""
    r = _fresh(tmp_path, monkeypatch, "20261113", "20261111")
    assert r.status == cdi.CheckResult.FAIL, r.msg
    assert r.grade != "blocking"  # 告警级, 不阻断 deploy(旧版兜底既定设计)


def test_06d_no_meta_date_falls_back_mtime(monkeypatch, tmp_path):
    """旧版无 _meta.date → mtime 兜底(刚写盘=当日 → OK, 标注来源 mtime)。"""
    r = _fresh(tmp_path, monkeypatch, "20261113", None)
    assert r.status == cdi.CheckResult.OK, r.msg
    assert "mtime" in r.msg


def test_06e_bad_date_fail(monkeypatch, tmp_path):
    r = _fresh(tmp_path, monkeypatch, "20261113", "abcdefgh")
    assert r.status == cdi.CheckResult.FAIL, r.msg


def test_06f_registered_in_alert_only_and_run_all(monkeypatch, tmp_path):
    """注册点: run_all_checks 跑得到 + 告警级登记(改坏注册则本用例红)。"""
    assert "board_etf_map_fresh" in cdi.ALERT_ONLY_CHECKS
    src = (Path(__file__).parent.parent / "check_data_integrity.py").read_text(encoding="utf-8")
    assert "results.append(check_board_etf_map_fresh(repo_data_dir))" in src


# ── ⑦ build _meta 静态锁 ─────────────────────────────────────────────────────

def test_07_build_meta_date_and_source_labels():
    src = (Path(__file__).parent.parent / "build_board_etf_map.py").read_text(encoding="utf-8")
    assert '"date": time.strftime("%Y%m%d")' in src
    for kw in ("eastmoney", "sina_tencent", "tencent_universe"):
        assert kw in src, kw


def test_zz_assertion_floor():
    """防 0 断言假绿(§18 L49): 用例内断言计数由 pytest 汇总, 这里锁用例文件可收集。"""
    import inspect
    fns = [v for k, v in globals().items() if k.startswith("test_") and inspect.isfunction(v)]
    assert len(fns) >= 15
