# -*- coding: utf-8 -*-
"""#246 故障 B 治本(B4-1 兜底链修复 + B4-2 重试策略)pytest 套(2026-10-10)。

【背景】docs/ops/1009-real-faults-rootcause-design-20261009.md §B④。
  10-09 晨 gap_check 链断在兜底细节: 159970 因腾讯时间戳缺失 → `_fetch_intraday_open_via_http`
  直接 raise 终止兜底链(新浪分支不可达)、单标的拖垮全链;且主源「成功但个别标的缺价」只对
  16 前缀 LOF 补兜底(15 前缀不兜),「日期陈旧」路径直接 raise 不走兜底。

【本套锁死的新行为(B4-1/B4-2)】
  ① `_fetch_intraday_open_via_http`: 腾讯失败(含时间戳缺失)→ 降级新浪(新浪[30]日期字段作
     当日性锚);逐标的独立(单标的双源皆失败仅记 missing,不 raise)。
     ⚠️ #254(2026-10-12)签名变更: 现返回 `(out, zero_volume_codes)`,**全灭也不再 raise**
     (fail-closed 决定权上移到 compute_intraday 的 ratio 判据);本套对应用例已同步新签名。
  ② `_fetch_intraday_open_prices`: 主源成功但部分 target 缺有效开盘价 → 对「全部 missing」
     (不限 16 前缀)启用单标的 HTTP 兜底;「日期陈旧」路径并入兜底优先。正常路径(主源新鲜且
     整批命中)行为零变化(missing 空 ⇒ 不触发兜底)。
  ③ `_retry_plan` + main(): 跨 9:30 墙钟锚点重试(09:28/09:31/09:35/09:40,预算硬顶 900s),
     替代原 60s×3 短退避(2026-10-13 跨窗口治本);配合外层 systemd 墙 600→1800。

【零外发(§18 L48)】所有用例把 `requests.get` / `akshare.fund_etf_spot_em` 全量替换为假对象,
  并断言假对象确被调用(证明打桩生效、真实出口未被触达)。main() 用例另把 `_severe_alert`
  (其内部 subprocess 调 notify.py 会真发邮件/飞书)与 `_sync_r2_and_notify` 打桩为 no-op,
  全程零真实外发;`time.sleep` 亦打桩(不留真实等待)。

【红先验】本套针对修复前旧码应失败(见报告 docs/ops/246-faultb-fallback-impl-20261010.md)。
【复现命令】/Users/linhuichen/code/trade/.venv/bin/python -m pytest -q scripts/tests/test_246_faultb_fallback_20261010.py
"""
import ast
import re
import sys
from datetime import datetime
from pathlib import Path

import pytest

pytest.importorskip("yaml", reason="CI 需 pyinstall pyyaml 才能 import signal_kelly_backtest")
pytest.importorskip("pandas", reason="CI ⑧ 需 pandas 构造 fund_etf_spot_em 假表")

ROOT = Path(__file__).absolute().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import pandas as pd  # noqa: E402
import requests as _requests_mod  # noqa: E402

try:
    import signal_kelly_backtest as sk  # noqa: E402
    import nextday_gap_check as ngc  # noqa: E402
except Exception as _e:  # pragma: no cover - 环境缺依赖时降级 skip
    pytest.skip(f"#246 依赖不可用: {_e}", allow_module_level=True)


EXPECT = "20261009"        # 执行日(与 design 10-09 场景一致)
OK_TS = "20261009" + "161500"   # 腾讯时间戳[30] = YYYYMMDDHHMMSS
OK_DATE = "2026-10-09"          # 新浪日期字段[30] = YYYY-MM-DD


# ── 假出口构造(零外发) ────────────────────────────────────────────────────────
class _Resp:
    def __init__(self, content: bytes):
        self.content = content


def _tencent(symbol, open_p, ts):
    """构造腾讯 GBK 波浪号报文: split('~')[5]=今开, [30]=时间戳(前缀无 ~)。"""
    f = [""] * 33
    f[0] = "1"
    f[1] = "ETF"
    f[2] = symbol[2:]
    f[5] = str(open_p)
    f[30] = ts
    return ('v_%s="' % symbol + "~".join(f)).encode("gbk")


def _sina(symbol, open_p, date_str):
    """构造新浪 GBK 逗号报文: split(',')[1]=今开, [30]=日期(前缀无 ,)。"""
    f = [""] * 33
    f[0] = "ETF名称"
    f[1] = str(open_p)
    f[30] = date_str
    return ('var hq_str_%s="' % symbol + ",".join(f) + '";').encode("gbk")


class _GetStub:
    """把 requests.get 全量替换; 未预期 URL → 响亮 AssertionError(打桩漏网证明)。"""

    def __init__(self, routes):
        self.routes = routes          # {url 子串: bytes 报文 | Exception}
        self.calls = []

    def __call__(self, url, **kw):
        self.calls.append(url)
        for key, val in self.routes.items():
            if key in url:
                if isinstance(val, Exception):
                    raise val
                return _Resp(val)
        raise AssertionError(f"[#246] 未预期 URL(打桩漏网): {url}")

    def count(self, needle):
        return sum(1 for u in self.calls if needle in u)


@pytest.fixture(autouse=True)
def _ensure_request_exception(monkeypatch):
    """CI 的 requests 是导入级 stub(空 ModuleType, 无 RequestException);
    业务代码 except 元组会引用 requests.RequestException, 补位防 CI AttributeError。"""
    if not hasattr(_requests_mod, "RequestException"):
        monkeypatch.setattr(_requests_mod, "RequestException", Exception, raising=False)


def _sym(code):
    return ("sh" if str(code).startswith("5") else "sz") + str(code)


# ════════════════════════════════════════════════════════════════════════════
# ① _fetch_intraday_open_via_http —— B4-1(i)
# ════════════════════════════════════════════════════════════════════════════
def test_246_via_http_tencent_ts_missing_degrades_to_sina(monkeypatch):
    """腾讯价有效但时间戳缺失 → 降级新浪, 用新浪日期字段[30]作当日性锚(不再 raise)。"""
    sym = _sym("510300")
    stub = _GetStub({
        f"qt.gtimg.cn/q={sym}": _tencent(sym, 4.369, ""),        # 时间戳缺失
        f"hq.sinajs.cn/list={sym}": _sina(sym, 4.370, OK_DATE),  # 新浪价 + 当日日期
    })
    monkeypatch.setattr(_requests_mod, "get", stub, raising=False)
    out, zv = sk._fetch_intraday_open_via_http(["510300"], expect_date=EXPECT)
    assert out == {"510300": 4.370}, out
    assert zv == [], zv
    assert stub.count("hq.sinajs.cn") == 1, "打桩生效证明: 新浪确被请求"


def test_246_via_http_tencent_ok_prefers_tencent(monkeypatch):
    """腾讯价 + 时间戳齐且当日 → 直接用腾讯价(不请求新浪)。"""
    sym = _sym("510300")
    stub = _GetStub({f"qt.gtimg.cn/q={sym}": _tencent(sym, 4.371, OK_TS)})
    monkeypatch.setattr(_requests_mod, "get", stub, raising=False)
    out, zv = sk._fetch_intraday_open_via_http(["510300"], expect_date=EXPECT)
    assert out == {"510300": 4.371}, out
    assert zv == [], zv
    assert stub.count("hq.sinajs.cn") == 0


def test_246_via_http_per_target_independent(monkeypatch):
    """逐标的独立: A 命中腾讯 / B 双源皆失败 → B 记 missing, A 不受拖累, 不 raise。"""
    sa, sb = _sym("510300"), _sym("159920")
    stub = _GetStub({
        f"qt.gtimg.cn/q={sa}": _tencent(sa, 4.40, OK_TS),
        f"qt.gtimg.cn/q={sb}": ValueError("腾讯 B 失败"),
        f"hq.sinajs.cn/list={sb}": ValueError("新浪 B 失败"),
    })
    monkeypatch.setattr(_requests_mod, "get", stub, raising=False)
    out, zv = sk._fetch_intraday_open_via_http(["510300", "159920"], expect_date=EXPECT)
    assert out == {"510300": 4.40}, out
    assert "159920" not in out
    assert zv == [], zv


def test_246_via_http_all_missing_no_longer_raises(monkeypatch):
    """#254(2026-10-12)行为变更: 全灭(唯一标的双源皆失败=取不到) → **不再 raise**, 返回 ({}, [])。
    旧行为(本套原用例)=此处 raise;fail-closed 决定权上移到 compute_intraday 的 ratio 判据。"""
    sb = _sym("159920")
    stub = _GetStub({
        f"qt.gtimg.cn/q={sb}": ValueError("腾讯失败"),
        f"hq.sinajs.cn/list={sb}": ValueError("新浪失败"),
    })
    monkeypatch.setattr(_requests_mod, "get", stub, raising=False)
    out, zv = sk._fetch_intraday_open_via_http(["159920"], expect_date=EXPECT)
    assert out == {} and zv == [], (out, zv)


def test_246_via_http_sina_date_mismatch_rejected(monkeypatch):
    """腾讯时间戳缺失 + 新浪日期非当日 → 该标的拒用(取不到/unfetchable, 非 priced 也非 zero_volume)。
    #254 起不再 raise, 返回 ({}, []);该码归 unfetchable 由调用方 ratio 判据处理。"""
    sym = _sym("510300")
    stub = _GetStub({
        f"qt.gtimg.cn/q={sym}": _tencent(sym, 4.40, ""),                 # 时间戳缺失
        f"hq.sinajs.cn/list={sym}": _sina(sym, 4.41, "2026-10-08"),      # 昨日日期
    })
    monkeypatch.setattr(_requests_mod, "get", stub, raising=False)
    out, zv = sk._fetch_intraday_open_via_http(["510300"], expect_date=EXPECT)
    assert out == {} and zv == [], (out, zv)


def test_246_via_http_no_expect_date_skips_date_anchor(monkeypatch):
    """expect_date=None(回测历史档)时不校验日期, 腾讯有价即可。"""
    sym = _sym("510300")
    stub = _GetStub({f"qt.gtimg.cn/q={sym}": _tencent(sym, 4.42, "")})
    monkeypatch.setattr(_requests_mod, "get", stub, raising=False)
    out, zv = sk._fetch_intraday_open_via_http(["510300"])
    assert out == {"510300": 4.42}, out
    assert zv == [], zv


# ════════════════════════════════════════════════════════════════════════════
# ② _fetch_intraday_open_prices —— B4-1(ii)
# ════════════════════════════════════════════════════════════════════════════
def _spot_df(rows):
    """rows: [(code, open, date_str)] → fund_etf_spot_em 形态假表(代码/开盘价/数据日期)。"""
    return pd.DataFrame({
        "代码": [r[0] for r in rows],
        "开盘价": [r[1] for r in rows],
        "数据日期": [r[2] for r in rows],
    })


def test_246_prices_partial_missing_falls_back_for_15prefix(monkeypatch):
    """主源成功但 15 前缀 target 缺价 → 对全部 missing 启用兜底(旧码只兜 16 前缀)。"""
    import akshare as ak_mod
    monkeypatch.setattr(ak_mod, "fund_etf_spot_em",
                        lambda: _spot_df([("510300", 4.50, OK_DATE)]), raising=False)
    sym = _sym("159920")
    stub = _GetStub({f"qt.gtimg.cn/q={sym}": _tencent(sym, 1.250, OK_TS)})
    monkeypatch.setattr(_requests_mod, "get", stub, raising=False)
    out, zv, meta = sk._fetch_intraday_open_prices(["510300", "159920"], expect_date=EXPECT)
    assert out == {"510300": 4.50, "159920": 1.250}, out
    assert zv == [], zv
    assert meta == {"main_source_ok": True, "fallback_used": True}, meta
    assert stub.count("qt.gtimg.cn") == 1, "15 前缀 missing 确被兜底"


def test_246_prices_date_stale_falls_back(monkeypatch):
    """主源数据日期陈旧 → 不直接 raise, 全部走实时兜底(兜底优先)。"""
    import akshare as ak_mod
    monkeypatch.setattr(ak_mod, "fund_etf_spot_em",
                        lambda: _spot_df([("510300", 9.99, "2026-10-08")]), raising=False)
    sym = _sym("510300")
    stub = _GetStub({f"qt.gtimg.cn/q={sym}": _tencent(sym, 4.60, OK_TS)})
    monkeypatch.setattr(_requests_mod, "get", stub, raising=False)
    out, zv, meta = sk._fetch_intraday_open_prices(["510300"], expect_date=EXPECT)
    assert out == {"510300": 4.60}, out          # 用兜底实时价, 不用陈旧快照 9.99
    assert zv == [] and meta["main_source_ok"] is False, (zv, meta)


def test_246_prices_normal_path_no_fallback(monkeypatch):
    """正常路径(主源新鲜且整批命中)行为零变化: 不触发兜底(requests.get 零调用)。"""
    import akshare as ak_mod
    monkeypatch.setattr(ak_mod, "fund_etf_spot_em",
                        lambda: _spot_df([("510300", 4.50, OK_DATE)]), raising=False)
    stub = _GetStub({})
    monkeypatch.setattr(_requests_mod, "get", stub, raising=False)
    out, zv, meta = sk._fetch_intraday_open_prices(["510300"], expect_date=EXPECT)
    assert out == {"510300": 4.50}, out
    assert zv == [] and meta == {"main_source_ok": True, "fallback_used": False}, (zv, meta)
    assert stub.calls == [], "正常路径不得触发兜底"


# ════════════════════════════════════════════════════════════════════════════
# ③ 重试策略 —— 跨 9:30 锚点重试(2026-10-13 跨窗口治本; 替代 B4-2 的 60s×3)
# ════════════════════════════════════════════════════════════════════════════
def test_246_retry_targets_and_budget_constants():
    """锚点表 / 预算常量锁定: 09:28/09:31/09:35/09:40, 预算硬顶 900s。"""
    assert ngc.RETRY_TARGETS == ("09:28:00", "09:31:00", "09:35:00", "09:40:00"), ngc.RETRY_TARGETS
    assert ngc.RETRY_BUDGET_S == 900, ngc.RETRY_BUDGET_S


def test_246_retry_plan_waits_from_now():
    """给定首拉 now=09:26:00 → 相邻锚点差 120/180/240/300(合计 840 ≤ 900), 末锚点 = 09:40:00。

    差 = 9:28-9:26 / 9:31-9:28 / 9:35-9:31 / 9:40-9:35 ⇒ 顺序 sleep 后恰在四个锚点醒来。
    """
    now = datetime(2026, 10, 13, 9, 26, 0)
    plan = ngc._retry_plan(now)
    assert plan == [("09:28:00", 120.0), ("09:31:00", 180.0),
                    ("09:35:00", 240.0), ("09:40:00", 300.0)], plan
    assert plan[-1][0] == "09:40:00", plan
    assert sum(w for _, w in plan) == 840.0, plan
    assert sum(w for _, w in plan) <= ngc.RETRY_BUDGET_S, plan


def test_246_retry_plan_waits_shift_with_now():
    """now 偏移 → 首轮差随 now 变化, 后续轮差恒等于锚点间距(纯函数, 无 jitter)。"""
    now = datetime(2026, 10, 13, 9, 27, 30)
    plan = ngc._retry_plan(now)
    assert [w for _, w in plan] == [30.0, 180.0, 240.0, 300.0], plan


def test_246_retry_plan_past_anchor_zero():
    """锚点已过 → 该轮 wait=0(立即重试, 不出现负值); 后续轮按剩余间距推进。"""
    now = datetime(2026, 10, 13, 9, 29, 0)
    plan = ngc._retry_plan(now, budget=10000)
    assert [w for _, w in plan] == [0.0, 120.0, 240.0, 300.0], plan
    assert all(w >= 0 for _, w in plan), plan


def test_246_retry_plan_budget_truncation():
    """跨预算 → 当轮截到剩余预算并停止再排(硬顶 ≤ budget); 末锚点不晚于 09:40:00。"""
    now = datetime(2026, 10, 13, 9, 26, 0)
    plan = ngc._retry_plan(now, budget=200)
    assert plan == [("09:28:00", 120.0), ("09:31:00", 80.0)], plan
    assert sum(w for _, w in plan) <= 200, plan
    assert plan[-1][0] <= "09:40:00", plan


def test_246_service_wall_matches_budget():
    """机检(#13): doc §2.14-1 service 块 TimeoutStartSec == 1800, 且 ≥ 预算 + 300(梯度)。

    替代原 `RETRY_BUDGET_S <= 570` 的「墙内」断言(墙 600→1800, 2026-10-13 跨窗口治本)。
    """
    md = (ROOT / "docs" / "deploy" / "systemd-units-20260912.md").read_text(encoding="utf-8")
    lines = md.splitlines()
    idx = next((i for i, l in enumerate(lines) if "trade-nextday-gap-check.service" in l), None)
    assert idx is not None, "doc §2.14-1 未找到 trade-nextday-gap-check.service(锚失效)"
    wall = None
    for l in lines[idx:]:
        m = re.match(r"^\s*TimeoutStartSec=(\d+)\s*$", l)
        if m:
            wall = int(m.group(1))
            break
    assert wall is not None, "doc §2.14-1 service 块未找到 TimeoutStartSec(锚失效)"
    assert wall == 1800, wall
    assert wall >= ngc.RETRY_BUDGET_S + 300, (wall, ngc.RETRY_BUDGET_S)


def test_246_retry_loop_uses_plan_and_attempts(monkeypatch, tmp_path):
    """main() 就绪闸: 前 2 次失败 → 按锚点计划 sleep 两轮 → 第 3 次成功(共 3 attempts)。"""
    # 打桩所有外发/R2/告警(§18 L48: 零真实外发)
    monkeypatch.setattr(ngc, "REPO", tmp_path, raising=False)
    monkeypatch.setattr(ngc, "GIT_REPO", tmp_path, raising=False)
    monkeypatch.setattr(ngc, "_severe_alert", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(ngc, "_sync_r2_and_notify", lambda *a, **k: (0, 0), raising=False)
    sleeps = []
    monkeypatch.setattr(ngc.time, "sleep", lambda s: sleeps.append(s), raising=False)

    data_dir = tmp_path / "static-site" / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "nextday_plan.json").write_text(
        '{"plan":[{"buy_date":"%s","etf_code":"510300","prev_close":4.50}]}' % EXPECT,
        encoding="utf-8")

    calls = {"n": 0}

    def _fake_fetch(codes, test_open=None, expect_date=None):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("就绪闸模拟失败")
        return {"510300": 4.50}

    monkeypatch.setattr(ngc, "_fetch_opens", _fake_fetch, raising=False)
    plan = [("09:28:00", 11.0), ("09:31:00", 22.0), ("09:35:00", 33.0)]
    monkeypatch.setattr(ngc, "_retry_plan", lambda *a, **k: list(plan), raising=False)

    monkeypatch.setattr(sys, "argv", ["nextday_gap_check.py", "--date", EXPECT, "--dry-run"])
    rc = ngc.main()
    assert rc == 0, rc
    assert calls["n"] == 3, calls
    assert sleeps == [11.0, 22.0], sleeps      # 前两轮各退避一次, 第 3 次成功后不再 sleep
    assert tmp_path.joinpath("static-site", "data").exists()  # 仅读不写(dry-run)


# ════════════════════════════════════════════════════════════════════════════
# ④ 存量死标记清理 —— _recheck_stale_pending(2026-10-13 治本)
# ════════════════════════════════════════════════════════════════════════════
def _make_db(path, rows):
    """建最小 etf_daily 假库(etf_code/date/etf_name/open)。"""
    import sqlite3
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path))
    con.execute("CREATE TABLE etf_daily (etf_code TEXT, date TEXT, etf_name TEXT, open REAL)")
    con.executemany("INSERT INTO etf_daily VALUES (?,?,?,?)", rows)
    con.commit()
    con.close()


def test_246_recheck_stale_pending_branches(tmp_path):
    """三分支 + 不动项: 有 open 非伪跳→待执行 / 有 open 伪跳→剔除 / 无 open 不动 /
    当天行不动 / 非 buy 不动; 幂等重跑零改动(不二次刷 updated_at)。"""
    db = tmp_path / "data" / "etf_national_team.db"
    _make_db(db, [
        ("510300", "20260923", "沪深300ETF", 1.00),   # |1.00/1.00-1| = 0% → 非伪跳空
        ("159920", "20260923", "恒生ETF", 2.00),      # |2.00/1.00-1| = 100% > 20% → 剔除
    ])
    stale = "伪跳空校验未完成(待人工)"
    steps = {"steps": [
        {"date": "20260923", "seq": "1", "action": "buy", "etf_code": "510300",
         "order_price": 1.00, "status": "pending", "status_text": stale, "updated_at": "old"},
        {"date": "20260923", "seq": "2", "action": "buy", "etf_code": "159920",
         "order_price": 1.00, "status": "pending", "status_text": stale, "updated_at": "old"},
        {"date": "20260923", "seq": "3", "action": "buy", "etf_code": "000001",
         "order_price": 1.00, "status": "pending", "status_text": stale, "updated_at": "old"},
        {"date": "20261013", "seq": "1", "action": "buy", "etf_code": "510300",
         "order_price": 1.00, "status": "pending", "status_text": stale, "updated_at": "old"},
        {"date": "20260923", "seq": "4", "action": "sell", "etf_code": "510300",
         "order_price": 1.00, "status": "pending", "status_text": stale, "updated_at": "old"},
    ]}
    assert ngc._recheck_stale_pending(steps, "20261013", "2026-10-13 09:26:00", db) is True
    s = steps["steps"]
    assert s[0]["status"] == "pending" and s[0]["status_text"] == "待执行", s[0]
    assert s[0]["updated_at"] == "2026-10-13 09:26:00", s[0]
    assert s[1]["status"] == "skipped" and s[1]["status_text"].startswith("伪跳空剔除"), s[1]
    assert s[2]["status_text"] == stale and s[2]["updated_at"] == "old", s[2]   # 无 open 不动
    assert s[3]["updated_at"] == "old", s[3]                                    # 当天行不动
    assert s[4]["updated_at"] == "old", s[4]                                    # 非 buy 不动
    # 幂等: 重跑零改动, 且不二次刷 updated_at
    assert ngc._recheck_stale_pending(steps, "20261013", "2026-10-13 10:00:00", db) is False
    assert s[0]["updated_at"] == "2026-10-13 09:26:00", s[0]
    assert s[1]["status_text"].startswith("伪跳空剔除"), s[1]


def test_246_recheck_include_today(tmp_path):
    """独立模式 include_today=True → date<=today 也重判(date==today 默认不动)。"""
    db = tmp_path / "data" / "etf_national_team.db"
    _make_db(db, [("510300", "20261013", "沪深300ETF", 1.00)])
    steps = {"steps": [
        {"date": "20261013", "seq": "1", "action": "buy", "etf_code": "510300",
         "order_price": 1.00, "status": "pending",
         "status_text": "伪跳空校验未完成(待人工)", "updated_at": "old"}]}
    assert ngc._recheck_stale_pending(steps, "20261013", "now", db, include_today=False) is False
    assert ngc._recheck_stale_pending(steps, "20261013", "now", db, include_today=True) is True
    assert steps["steps"][0]["status_text"] == "待执行", steps


def test_246_recheck_missing_db_no_clear(tmp_path):
    """DB 缺失 → 不清理(防误清), 行原样。"""
    steps = {"steps": [
        {"date": "20260923", "seq": "1", "action": "buy", "etf_code": "510300",
         "order_price": 1.0, "status": "pending",
         "status_text": "伪跳空校验未完成(待人工)", "updated_at": "old"}]}
    assert ngc._recheck_stale_pending(steps, "20261013", "now", tmp_path / "nope.db") is False
    assert steps["steps"][0]["updated_at"] == "old", steps


def test_246_recheck_pending_cli_e2e(monkeypatch, tmp_path):
    """--recheck-pending 端到端(tmp 假 JSON + 假库): 清 1 行 → 落盘「待执行」; 再跑零改动。"""
    import json
    _make_db(tmp_path / "data" / "etf_national_team.db",
             [("510300", "20260923", "沪深300ETF", 1.00)])
    monkeypatch.setattr(ngc, "REPO", tmp_path, raising=False)
    monkeypatch.setattr(ngc, "GIT_REPO", tmp_path, raising=False)
    monkeypatch.setattr(ngc, "_sync_r2_and_notify", lambda *a, **k: (0, 0), raising=False)
    d = tmp_path / "static-site" / "data"
    d.mkdir(parents=True)
    (d / "auto_trade_steps.json").write_text(json.dumps({"steps": [
        {"date": "20260923", "seq": "1", "action": "buy", "etf_code": "510300",
         "order_price": 1.00, "status": "pending",
         "status_text": "伪跳空校验未完成(待人工)", "updated_at": "old"}]}), encoding="utf-8")
    argv = ["nextday_gap_check.py", "--recheck-pending", "--date", "20261013",
            "--no-r2", "--no-notify"]
    monkeypatch.setattr(sys, "argv", list(argv))
    assert ngc.main() == 0
    doc = json.loads((d / "auto_trade_steps.json").read_text(encoding="utf-8"))
    assert doc["steps"][0]["status"] == "pending", doc
    assert doc["steps"][0]["status_text"] == "待执行", doc
    monkeypatch.setattr(sys, "argv", list(argv))
    assert ngc.main() == 0
    after = json.loads((d / "auto_trade_steps.json").read_text(encoding="utf-8"))
    assert after == doc, "重跑应零改动(幂等)"


def test_246_recheck_planning_not_touched_when_no_plan(monkeypatch, tmp_path):
    """挂载点 A: 无 nextday_plan(空)时早退, 但 recheck 清出的改动仍落盘(§22 闭环)。"""
    import json
    _make_db(tmp_path / "data" / "etf_national_team.db",
             [("510300", "20260923", "沪深300ETF", 1.00)])
    monkeypatch.setattr(ngc, "REPO", tmp_path, raising=False)
    monkeypatch.setattr(ngc, "GIT_REPO", tmp_path, raising=False)
    monkeypatch.setattr(ngc, "_sync_r2_and_notify", lambda *a, **k: (0, 0), raising=False)
    d = tmp_path / "static-site" / "data"
    d.mkdir(parents=True)
    (d / "auto_trade_steps.json").write_text(json.dumps({"steps": [
        {"date": "20260923", "seq": "1", "action": "buy", "etf_code": "510300",
         "order_price": 1.00, "status": "pending",
         "status_text": "伪跳空校验未完成(待人工)", "updated_at": "old"}]}), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["nextday_gap_check.py", "--date", "20261013",
                                      "--no-r2", "--no-notify"])
    assert ngc.main() == 0                       # 无计划 → 退出 0
    doc = json.loads((d / "auto_trade_steps.json").read_text(encoding="utf-8"))
    assert doc["steps"][0]["status_text"] == "待执行", doc


# ── 红先验辅助: 旧码无该函数 ─────────────────────────────────────────────────
def test_246_retry_fn_exists():
    assert callable(getattr(ngc, "_retry_plan", None)), \
        "锚点重试计划函数缺失(旧码应 FAIL)"


def test_246_via_http_source_of_truth_static():
    """static-only(ast, §18 L50)——**真·顺序检查**(2026-10-10 审查订正①: 原为空壳
    `assert tree is not None`, 现改为实断言):锁死 `_fetch_intraday_open_via_http` 函数体内
    「腾讯源 URL 出现在新浪源 URL 之前」= 源优先级 腾讯→新浪(#246 B4-1(i) 核心语义),
    防后续被顺序漂移静默改回「新浪主/腾讯备」。"""
    src = (ROOT / "scripts" / "signal_kelly_backtest.py").read_text(encoding="utf-8")
    tree = ast.parse(src)  # 只解析, 绝不 exec(§18 L50 static-only)
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef)
               and n.name == "_fetch_intraday_open_via_http"), None)
    assert fn is not None, "未找到 _fetch_intraday_open_via_http(改名/删除 = 锚失效)"
    seg = ast.get_source_segment(src, fn)
    assert seg, "无法取出函数源码段(ast.get_source_segment 失效)"
    i_ten, i_sina = seg.find("qt.gtimg.cn"), seg.find("hq.sinajs.cn")
    assert i_ten != -1, "函数体内未出现腾讯源 URL(锚失效, 请同步本测试锚)"
    assert i_sina != -1, "函数体内未出现新浪源 URL(锚失效, 请同步本测试锚)"
    assert i_ten < i_sina, f"源优先级漂移: 腾讯({i_ten}) 必须先于 新浪({i_sina})"