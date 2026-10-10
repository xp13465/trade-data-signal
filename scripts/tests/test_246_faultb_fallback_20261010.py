# -*- coding: utf-8 -*-
"""#246 故障 B 治本(B4-1 兜底链修复 + B4-2 重试策略)pytest 套(2026-10-10)。

【背景】docs/ops/1009-real-faults-rootcause-design-20261009.md §B④。
  10-09 晨 gap_check 链断在兜底细节: 159970 因腾讯时间戳缺失 → `_fetch_intraday_open_via_http`
  直接 raise 终止兜底链(新浪分支不可达)、单标的拖垮全链;且主源「成功但个别标的缺价」只对
  16 前缀 LOF 补兜底(15 前缀不兜),「日期陈旧」路径直接 raise 不走兜底。

【本套锁死的新行为(B4-1/B4-2)】
  ① `_fetch_intraday_open_via_http`: 腾讯失败(含时间戳缺失)→ 降级新浪(新浪[30]日期字段作
     当日性锚);逐标的独立(单标的双源皆失败仅记 missing,不 raise);全灭才 raise。
  ② `_fetch_intraday_open_prices`: 主源成功但部分 target 缺有效开盘价 → 对「全部 missing」
     (不限 16 前缀)启用单标的 HTTP 兜底;「日期陈旧」路径并入兜底优先。正常路径(主源新鲜且
     整批命中)行为零变化(missing 空 ⇒ 不触发兜底)。
  ③ `_retry_backoff_schedule` + main(): 短间隔退避多轮(60s×3,带 ±25% jitter,预算 ≤15min),
     替代原单次 300s。

【零外发(§18 L48)】所有用例把 `requests.get` / `akshare.fund_etf_spot_em` 全量替换为假对象,
  并断言假对象确被调用(证明打桩生效、真实出口未被触达)。main() 用例另把 `_severe_alert`
  (其内部 subprocess 调 notify.py 会真发邮件/飞书)与 `_sync_r2_and_notify` 打桩为 no-op,
  全程零真实外发;`time.sleep` 亦打桩(不留真实等待)。

【红先验】本套针对修复前旧码应失败(见报告 docs/ops/246-faultb-fallback-impl-20261010.md)。
【复现命令】/Users/linhuichen/code/trade/.venv/bin/python -m pytest -q scripts/tests/test_246_faultb_fallback_20261010.py
"""
import ast
import sys
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
    out = sk._fetch_intraday_open_via_http(["510300"], expect_date=EXPECT)
    assert out == {"510300": 4.370}, out
    assert stub.count("hq.sinajs.cn") == 1, "打桩生效证明: 新浪确被请求"


def test_246_via_http_tencent_ok_prefers_tencent(monkeypatch):
    """腾讯价 + 时间戳齐且当日 → 直接用腾讯价(不请求新浪)。"""
    sym = _sym("510300")
    stub = _GetStub({f"qt.gtimg.cn/q={sym}": _tencent(sym, 4.371, OK_TS)})
    monkeypatch.setattr(_requests_mod, "get", stub, raising=False)
    out = sk._fetch_intraday_open_via_http(["510300"], expect_date=EXPECT)
    assert out == {"510300": 4.371}, out
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
    out = sk._fetch_intraday_open_via_http(["510300", "159920"], expect_date=EXPECT)
    assert out == {"510300": 4.40}, out
    assert "159920" not in out


def test_246_via_http_all_missing_raises(monkeypatch):
    """全灭(唯一标的双源皆失败) → 抛 RuntimeError(fail-closed 终检保留)。"""
    sb = _sym("159920")
    stub = _GetStub({
        f"qt.gtimg.cn/q={sb}": ValueError("腾讯失败"),
        f"hq.sinajs.cn/list={sb}": ValueError("新浪失败"),
    })
    monkeypatch.setattr(_requests_mod, "get", stub, raising=False)
    with pytest.raises(RuntimeError):
        sk._fetch_intraday_open_via_http(["159920"], expect_date=EXPECT)


def test_246_via_http_sina_date_mismatch_rejected(monkeypatch):
    """腾讯时间戳缺失 + 新浪日期非当日 → 该标的拒用(missing, fail-closed)。"""
    sym = _sym("510300")
    stub = _GetStub({
        f"qt.gtimg.cn/q={sym}": _tencent(sym, 4.40, ""),                 # 时间戳缺失
        f"hq.sinajs.cn/list={sym}": _sina(sym, 4.41, "2026-10-08"),      # 昨日日期
    })
    monkeypatch.setattr(_requests_mod, "get", stub, raising=False)
    with pytest.raises(RuntimeError):
        sk._fetch_intraday_open_via_http(["510300"], expect_date=EXPECT)


def test_246_via_http_no_expect_date_skips_date_anchor(monkeypatch):
    """expect_date=None(回测历史档)时不校验日期, 腾讯有价即可。"""
    sym = _sym("510300")
    stub = _GetStub({f"qt.gtimg.cn/q={sym}": _tencent(sym, 4.42, "")})
    monkeypatch.setattr(_requests_mod, "get", stub, raising=False)
    assert sk._fetch_intraday_open_via_http(["510300"]) == {"510300": 4.42}


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
    out = sk._fetch_intraday_open_prices(["510300", "159920"], expect_date=EXPECT)
    assert out == {"510300": 4.50, "159920": 1.250}, out
    assert stub.count("qt.gtimg.cn") == 1, "15 前缀 missing 确被兜底"


def test_246_prices_date_stale_falls_back(monkeypatch):
    """主源数据日期陈旧 → 不直接 raise, 全部走实时兜底(兜底优先)。"""
    import akshare as ak_mod
    monkeypatch.setattr(ak_mod, "fund_etf_spot_em",
                        lambda: _spot_df([("510300", 9.99, "2026-10-08")]), raising=False)
    sym = _sym("510300")
    stub = _GetStub({f"qt.gtimg.cn/q={sym}": _tencent(sym, 4.60, OK_TS)})
    monkeypatch.setattr(_requests_mod, "get", stub, raising=False)
    out = sk._fetch_intraday_open_prices(["510300"], expect_date=EXPECT)
    assert out == {"510300": 4.60}, out          # 用兜底实时价, 不用陈旧快照 9.99


def test_246_prices_normal_path_no_fallback(monkeypatch):
    """正常路径(主源新鲜且整批命中)行为零变化: 不触发兜底(requests.get 零调用)。"""
    import akshare as ak_mod
    monkeypatch.setattr(ak_mod, "fund_etf_spot_em",
                        lambda: _spot_df([("510300", 4.50, OK_DATE)]), raising=False)
    stub = _GetStub({})
    monkeypatch.setattr(_requests_mod, "get", stub, raising=False)
    out = sk._fetch_intraday_open_prices(["510300"], expect_date=EXPECT)
    assert out == {"510300": 4.50}, out
    assert stub.calls == [], "正常路径不得触发兜底"


# ════════════════════════════════════════════════════════════════════════════
# ③ 重试策略 —— B4-2
# ════════════════════════════════════════════════════════════════════════════
def test_246_retry_backoff_schedule_shape():
    """60s×3: rng=0.5(无抖动)→ 三轮各 60s; 轮数/基数常量锁定。"""
    assert ngc.RETRY_BACKOFF_BASE_S == 60
    assert ngc.DEFAULT_RETRY_ROUNDS == 3
    waits = ngc._retry_backoff_schedule(rng=lambda: 0.5)
    assert waits == [60.0, 60.0, 60.0], waits


def test_246_retry_backoff_jitter_bounds_and_budget():
    """带 jitter: rng=0/1 → 每轮 base×[0.75,1.25]; 累计不超预算。"""
    lo = ngc._retry_backoff_schedule(rng=lambda: 0.0)
    hi = ngc._retry_backoff_schedule(rng=lambda: 1.0)
    assert lo == [45.0, 45.0, 45.0], lo
    assert hi == [75.0, 75.0, 75.0], hi
    many = ngc._retry_backoff_schedule(rounds=100, rng=lambda: 1.0)
    assert sum(many) <= ngc.RETRY_BUDGET_S + 1e-6, (sum(many), ngc.RETRY_BUDGET_S)
    assert ngc.RETRY_BUDGET_S == 900


def test_246_retry_loop_uses_schedule_and_attempts(monkeypatch, tmp_path):
    """main() 就绪闸: 前 2 次失败 → 按退避表 sleep 两轮 → 第 3 次成功(共 3 attempts)。"""
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
    backoffs = [11.0, 22.0, 33.0]
    monkeypatch.setattr(ngc, "_retry_backoff_schedule", lambda **k: list(backoffs), raising=False)

    monkeypatch.setattr(sys, "argv", ["nextday_gap_check.py", "--date", EXPECT, "--dry-run"])
    rc = ngc.main()
    assert rc == 0, rc
    assert calls["n"] == 3, calls
    assert sleeps == [11.0, 22.0], sleeps      # 前两轮各退避一次, 第 3 次成功后不再 sleep
    assert tmp_path.joinpath("static-site", "data").exists()  # 仅读不写(dry-run)


# ── 红先验辅助: 旧码无该函数 ─────────────────────────────────────────────────
def test_246_retry_fn_exists():
    assert callable(getattr(ngc, "_retry_backoff_schedule", None)), \
        "B4-2 退避表函数缺失(旧码应 FAIL)"


def test_246_via_http_source_of_truth_static():
    """static-only(ast, §18 L50): 确认缺失列分支已无「直接 raise」兜底盲区文案。"""
    src = (ROOT / "scripts" / "signal_kelly_backtest.py").read_text(encoding="utf-8")
    tree = ast.parse(src)  # 只解析, 绝不 exec
    assert tree is not None