# -*- coding: utf-8 -*-
"""#254 凯利盘中「数据就绪闸」放宽(方案 A) pytest 套(2026-10-12)。

施工图: docs/ops/kelly-intraday-gate-relax-design-20261012.md
        docs/ops/kelly-intraday-rerun-exit5-20261012.md
冻结参数: R=15% / D=5 / 零成交 TTL=60d / 取不到 TTL=14d(永不静默)
ratio 口径(冻结): 分子 = 未豁免且 class=unfetchable 的码数;分母 = target 数(含零成交豁免码)。

【本套锁死的新行为(#254)】
  a. zero_volume(可证实当日零成交)不 raise, 出档 verdict=tolerate/ratio=0(→ exit 0);
  b. unfetchable 且 ratio>R → abort(exit 5);
  c. 空轮 target=0 → 正常空档(不 raise, verdict=pass, exit 0);
  d. 豁免自动失效五维(集合新增成员/类别变化/源上下文变化/超带/TTL 到期);
  e. 既有降噪通道未被破坏(abort 仍 tier=warning + 同 dedup key/window;unit SuccessExitStatus=5 在位)。

【真实样本(§18 L49: 禁人工构造"看起来合理"样本)】全部输入取自真实生产证据:
  · 语料底座: docs/kelly/analysis/kelly-intraday-gate-zero-volume-series-20261012.json(113 运行日)
  · 生产线逐字锚: 云上日志 L748(10-12: 159513/164508, target=24, 8.3%)
  · 字段值/时间戳语义: 设计稿 §六 V2/V3(零成交 [30]==today 且 今开==0;腾讯 [5]=今开/[30]=时间戳)
  payload 报文按设计稿实测字段位构造(腾讯 split('~')[5]/[30];新浪 split(',')[1]/[30]), 打桩出站(零外发)。

【零外发(§18 L48)】requests.get 全量打桩;decider notify 一律 --dry-run。状态文件用 tmp_path 隔离。
【复现命令】/Users/linhuichen/code/trade/.venv/bin/python -m pytest -q scripts/tests/test_254_intraday_gate_relax_20261012.py
"""
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

pytest.importorskip("yaml", reason="CI 需 pyyaml 才能 import signal_kelly_backtest / decider")

ROOT = Path(__file__).absolute().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import requests as _requests_mod  # noqa: E402

try:
    import signal_kelly_backtest as sk  # noqa: E402
    import kelly_intraday_gate_decider as gate  # noqa: E402
    import kelly_intraday_gate_ack as ack  # noqa: E402
except Exception as _e:  # pragma: no cover
    pytest.skip(f"#254 依赖不可用: {_e}", allow_module_level=True)


EXPECT = "20261012"                     # 执行日(与生产线 10-12 锚一致)
OK_TS = "20261012" + "094000"           # 腾讯时间戳[30] = YYYYMMDDHHMMSS(09:40 考察时点)
OK_DATE = "2026-10-12"                   # 新浪日期[30] = YYYY-MM-DD
NOW = datetime(2026, 10, 12, 9, 40, 0)

# ── 真实生产缺口语料(series 底座 + 生产线逐字) ────────────────────────────────
SERIES = json.loads((ROOT / "docs" / "kelly" / "analysis"
                     / "kelly-intraday-gate-zero-volume-series-20261012.json").read_text(encoding="utf-8"))


def _series_row(run_date):
    for r in SERIES:
        if r["date"] == run_date:
            return r
    raise AssertionError(f"语料底座缺 {run_date}")


# 10-12 真实两码(生产线 L748 逐字): 09:40 前零成交
REAL_1012 = _series_row("2026-10-12")
REAL_1012_CODES = REAL_1012["codes"]                # ['159513', '164508']
REAL_1012_TARGET = REAL_1012["target_count"]        # 24
# 09-23 真实 n=1 100% 日(整源挂/不可细分, 设计稿 §五.5 该日仍 fail-closed)
REAL_0923 = _series_row("2026-09-23")


# ── 假出口(零外发) ────────────────────────────────────────────────────────────
class _Resp:
    def __init__(self, content: bytes):
        self.content = content


def _tencent(symbol, open_p, ts):
    f = [""] * 33
    f[0] = "1"; f[1] = "ETF"; f[2] = symbol[2:]; f[5] = str(open_p); f[30] = ts
    return ('v_%s="' % symbol + "~".join(f)).encode("gbk")


def _sina(symbol, open_p, date_str):
    f = [""] * 33
    f[0] = "ETF名称"; f[1] = str(open_p); f[30] = date_str
    return ('var hq_str_%s="' % symbol + ",".join(f) + '";').encode("gbk")


class _GetStub:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, url, **kw):
        self.calls.append(url)
        for key, val in self.routes.items():
            if key in url:
                if isinstance(val, Exception):
                    raise val
                return _Resp(val)
        raise AssertionError(f"[#254] 未预期 URL(打桩漏网): {url}")


def _sym(code):
    return ("sh" if str(code).startswith("5") else "sz") + str(code)


@pytest.fixture(autouse=True)
def _ensure_request_exception(monkeypatch):
    if not hasattr(_requests_mod, "RequestException"):
        monkeypatch.setattr(_requests_mod, "RequestException", Exception, raising=False)


def _report(run_date, target_count, codes, classes, main_ok=False, fb=True):
    infos = [{"code": c, "class": cls, "evidence": "real", "ts": "2026-10-12 09:40:00"}
             for c, cls in zip(codes, classes)]
    return {"run_date": run_date, "target_count": target_count, "missing_count": len(codes),
            "ratio": 0.0, "main_source_ok": main_ok, "fallback_used": fb,
            "codes": infos, "exempted": [], "verdict": ""}


def _ex(code_map, src_ctx=None, band_cap=0.15, confirmed_at="2026-10-12 09:45:00",
        ttl_days=60, status="active", ex_id="ex_test_1"):
    return {"id": ex_id, "codes": sorted(code_map), "class_by_code": dict(code_map),
            "src_ctx": src_ctx or {"main_source_ok": False, "fallback_used": True},
            "band_cap": band_cap, "ttl_days": ttl_days, "confirmed_at": confirmed_at,
            "status": status, "band_strikes": 0, "hits": 0, "note": ""}


# ════════════════════════════════════════════════════════════════════════════
# (c) 空轮 target=0 → 不 raise, verdict=pass
# ════════════════════════════════════════════════════════════════════════════
def test_254_empty_round_via_http_no_raise():
    """空轮: 兜底函数空集 → 返回 ({}, []) 不 raise(旧码 :917-920 会 raise, 实测坐实)。"""
    out, zv = sk._fetch_intraday_open_via_http([], expect_date=EXPECT)
    assert out == {} and zv == [], (out, zv)


def test_254_empty_round_prices_no_raise_real_main_down(monkeypatch):
    """空轮: 真·主源不可用(东财封禁 403 生产实态)→ 不复用主源, 直接返回 ({}, [], meta)。"""
    import akshare as ak_mod
    monkeypatch.setattr(ak_mod, "fund_etf_spot_em",
                        lambda: (_ for _ in ()).throw(RuntimeError("HTTP 403(东财封禁生产实态)")),
                        raising=False)
    out, zv, meta = sk._fetch_intraday_open_prices([], expect_date=EXPECT)
    assert out == {} and zv == [] and meta["fallback_used"] is False, (out, zv, meta)


def test_254_empty_round_prices_no_raise_main_healthy(monkeypatch):
    """空轮: 主源健康(旧码在 :828-829 全灭 raise)→ 现返回 ({}, [], meta) 不 raise。"""
    import pandas as pd
    import akshare as ak_mod
    monkeypatch.setattr(ak_mod, "fund_etf_spot_em",
                        lambda: pd.DataFrame({"代码": ["510300"], "开盘价": [4.50],
                                              "数据日期": ["2026-10-12"]}), raising=False)
    out, zv, meta = sk._fetch_intraday_open_prices([], expect_date=EXPECT)
    assert out == {} and zv == [] and meta["main_source_ok"] is False, (out, zv, meta)


def test_254_empty_round_verdict_pass():
    rep = _report("20261012", 0, [], [])
    dec = gate.evaluate(rep, {"exemptions": [], "tolerate_streak": {}}, NOW, mutate=False)
    assert dec["verdict"] == "pass" and dec["exit_code"] == 0 and dec["tier"] == "silent"


# ════════════════════════════════════════════════════════════════════════════
# (a) zero_volume 不 raise + verdict=tolerate(ratio=0, silent)
# ════════════════════════════════════════════════════════════════════════════
def test_254_zero_volume_classified_not_priced(monkeypatch):
    """10-12 真实两码 159513/164508: 两源 [30]==today 且 今开==0 → zero_volume, 不 priced 不 raise。"""
    stub = _GetStub({})
    for c in REAL_1012_CODES:
        sym = _sym(c)
        stub.routes[f"qt.gtimg.cn/q={sym}"] = _tencent(sym, 0, OK_TS)      # 今开 0 + 当日时间戳
        stub.routes[f"hq.sinajs.cn/list={sym}"] = _sina(sym, 0.0, OK_DATE)
    monkeypatch.setattr(_requests_mod, "get", stub, raising=False)
    out, zv = sk._fetch_intraday_open_via_http(list(REAL_1012_CODES), expect_date=EXPECT)
    assert out == {}, out
    assert zv == sorted(REAL_1012_CODES), zv


def test_254_zero_volume_verdict_tolerate_silent():
    """10-12 真实底座行(target=24, 2 零成交码)→ verdict=tolerate, ratio=0, exit 0, silent。"""
    rep = _report(REAL_1012["R"], REAL_1012_TARGET, REAL_1012_CODES,
                  ["zero_volume"] * len(REAL_1012_CODES))
    dec = gate.evaluate(rep, {"exemptions": [], "tolerate_streak": {}}, NOW, mutate=False)
    assert dec["verdict"] == "tolerate", dec
    assert dec["ratio"] == 0.0, dec
    assert dec["exit_code"] == 0 and dec["tier"] == "silent", dec


def test_254_unpriced_codes_written_in_intraday_static():
    """static-only(ast, §18 L50): 锁死 compute_intraday 写入盘中档 `intraday` 两个未定价字段(#254 冻结接口)。

    层级实测(以真实产物为准, 非照抄派单措辞): 线上 signal_kelly_trades_intraday.json 的
    top_keys 含 **root 级 `intraday`**、**无 `meta`** ⇒ 字段路径 = `intraday.unpriced_codes`
    (`intraday.unpriced_zero_volume_codes`), 不是 `meta.intraday.*`。
    """
    import ast
    src = (ROOT / "scripts" / "signal_kelly_backtest.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next((n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
               and n.name == "compute_intraday"), None)
    assert fn is not None, "未找到 compute_intraday(改名/删除 = 锚失效)"
    seg = ast.get_source_segment(src, fn)
    assert 'trades_output["intraday"]' in seg and 'output["intraday"]' in seg, \
        "盘中档 intraday 写入点丢失(层级漂移)"
    assert '"unpriced_codes": unpriced_codes' in seg, "unpriced_codes 未写入"
    assert '"unpriced_zero_volume_codes": unpriced_zero_volume_codes' in seg, \
        "unpriced_zero_volume_codes 未写入(接口补丁漂移)"
    # gate report 同批两字段
    assert '"unpriced_codes": unpriced_codes' in src and \
           '"unpriced_zero_volume_codes": unpriced_zero_volume_codes' in src, "gate report 缺字段"


def test_254_unpriced_subsets_real_samples_and_invariant():
    """接口补丁: unpriced_codes 全集 ⊆/⊇ 关系 + 零成交子集正确(真实样本, 不变式硬断言)。"""
    # 真实 10-12 面: 两码皆「09:40 前零成交」
    miss, zv_sub = sk._unpriced_subsets(REAL_1012_CODES, REAL_1012_CODES)
    assert miss == sorted(REAL_1012_CODES) and zv_sub == sorted(REAL_1012_CODES), (miss, zv_sub)
    # 混合面(真实 09-23 不可细分码 + 10-12 零成交码): 子集只能含零成交类
    mixed = list(REAL_0923["codes"]) + list(REAL_1012_CODES)
    miss, zv_sub = sk._unpriced_subsets(mixed, REAL_1012_CODES)
    assert miss == sorted(mixed), miss
    assert zv_sub == sorted(REAL_1012_CODES), zv_sub
    assert set(zv_sub) <= set(miss), "不变式破: 零成交子集必须 ⊆ 未定价全集"
    # 全取不到(无零成交) → 子集为空(前端退回中性措辞)
    miss, zv_sub = sk._unpriced_subsets(REAL_0923["codes"], [])
    assert miss == sorted(REAL_0923["codes"]) and zv_sub == [], (miss, zv_sub)
    # 防御: zero_volume_codes 里混入不在 missing 的码 → 不得进子集
    miss, zv_sub = sk._unpriced_subsets(["561120"], ["159513", "561120"])
    assert zv_sub == ["561120"], zv_sub


def test_254_gate_report_carries_unpriced_fields_through_write(tmp_path):
    """gate report 落盘后两字段仍在(write_report 往返不丢字段)。"""
    rep = _report(REAL_1012["R"], REAL_1012_TARGET, REAL_1012_CODES,
                  ["zero_volume"] * len(REAL_1012_CODES))
    rep["unpriced_codes"], rep["unpriced_zero_volume_codes"] = sk._unpriced_subsets(
        REAL_1012_CODES, REAL_1012_CODES)
    p = tmp_path / "gate.json"
    gate.write_report(rep, p)
    back = json.loads(p.read_text(encoding="utf-8"))
    assert back["unpriced_zero_volume_codes"] == sorted(REAL_1012_CODES), back
    assert set(back["unpriced_zero_volume_codes"]) <= set(back["unpriced_codes"]), back


# ════════════════════════════════════════════════════════════════════════════
# (b) unfetchable 且 ratio>R → abort exit 5
# ════════════════════════════════════════════════════════════════════════════
def test_254_unfetchable_when_sources_down(monkeypatch):
    """源双腿同死(生产 9-29/30 实况)→ 该码两源皆不可证实当日 → 归 unfetchable({}, [] 不含)。"""
    sym = _sym("561120")
    down = _requests_mod.RequestException            # 生产除的是 requests.RequestException
    stub = _GetStub({f"qt.gtimg.cn/q={sym}": down("腿1 挂"),
                     f"hq.sinajs.cn/list={sym}": down("腿2 挂")})
    monkeypatch.setattr(_requests_mod, "get", stub, raising=False)
    out, zv = sk._fetch_intraday_open_via_http(["561120"], expect_date=EXPECT)
    assert out == {} and zv == [], (out, zv)


def test_254_abort_when_unfetchable_ratio_over_R():
    """09-23 真实 n=1 100% 日(整源挂/不可细分)按保守归 unfetchable → ratio=1.0>R → abort exit5。"""
    rep = _report(REAL_0923["R"], REAL_0923["target_count"], REAL_0923["codes"], ["unfetchable"])
    dec = gate.evaluate(rep, {"exemptions": [], "tolerate_streak": {}}, NOW, mutate=False)
    assert dec["verdict"] == "abort" and dec["exit_code"] == 5, dec
    assert dec["ratio"] == 1.0, dec


def test_254_tolerate_when_unfetchable_under_R():
    """10-08 真实底座行(target=15, 2 码)按 unfetchable → ratio=13.3% <=R → tolerate(不 abort)。"""
    row = _series_row("2026-10-08")
    rep = _report(row["R"], row["target_count"], row["codes"], ["unfetchable"] * len(row["codes"]))
    dec = gate.evaluate(rep, {"exemptions": [], "tolerate_streak": {}}, NOW, mutate=False)
    assert dec["verdict"] == "tolerate" and dec["exit_code"] == 0, dec
    assert abs(dec["ratio"] - round(2 / 15, 6)) < 1e-9, dec   # dec 内已 round(ratio, 6)


# ════════════════════════════════════════════════════════════════════════════
# P1 豁免命中: 取不到类 → 降级 WARN(永不静默); 零成交类 → 静默
# ════════════════════════════════════════════════════════════════════════════
def test_254_unfetchable_exemption_hit_never_silent():
    """09-23 面已确认豁免 → 命中, ratio 归 0 → tolerate, 但仍 tier=warning(取不到类永不静默)。"""
    codes = REAL_0923["codes"]
    # band_cap 按确认口径 = max(R, 确认时 r_band) = max(0.15, 1/1) = 1.0(ack.confirm 同算法)
    state = {"exemptions": [_ex({c: "unfetchable" for c in codes}, band_cap=1.0)],
             "tolerate_streak": {}}
    rep = _report(REAL_0923["R"], 1, codes, ["unfetchable"])
    dec = gate.evaluate(rep, state, NOW, mutate=False)
    assert dec["verdict"] == "tolerate" and dec["exit_code"] == 0, dec
    assert dec["exempted"] == sorted(codes), dec
    assert dec["tier"] == "warning" and dec["reason"] == "unfetchable_exempted_never_silent", dec


def test_254_zero_volume_exemption_hit_silent():
    """10-12 零成交面已确认豁免 → 命中, 静默(仅 info 留痕)。"""
    codes = REAL_1012_CODES
    state = {"exemptions": [_ex({c: "zero_volume" for c in codes}, ttl_days=60)], "tolerate_streak": {}}
    rep = _report(REAL_1012["R"], REAL_1012_TARGET, codes, ["zero_volume"] * len(codes))
    dec = gate.evaluate(rep, state, NOW, mutate=False)
    assert dec["exempted"] == sorted(codes), dec
    assert dec["tier"] == "silent" and dec["zero_volume_exempted"] == sorted(codes), dec


# ════════════════════════════════════════════════════════════════════════════
# (d) 豁免五维自动失效
# ════════════════════════════════════════════════════════════════════════════
def test_254_dim_ttl_expired():
    codes = ["159501"]
    old = (NOW - timedelta(days=61)).strftime("%Y-%m-%d %H:%M:%S")
    state = {"exemptions": [_ex({"159501": "zero_volume"}, confirmed_at=old, ttl_days=60)],
             "tolerate_streak": {}}
    rep = _report("20261012", 4, codes, ["zero_volume"])
    dec = gate.evaluate(rep, state, NOW, mutate=True)
    assert dec["invalidations"] and dec["invalidations"][0]["reason"] == "ttl", dec
    assert state["exemptions"][0]["status"] == "invalidated:ttl", state


def test_254_dim_unfetchable_ttl_14d():
    old = (NOW - timedelta(days=15)).strftime("%Y-%m-%d %H:%M:%S")
    state = {"exemptions": [_ex({"561120": "unfetchable"}, confirmed_at=old, ttl_days=14)],
             "tolerate_streak": {}}
    rep = _report("20261012", 1, ["561120"], ["unfetchable"])
    dec = gate.evaluate(rep, state, NOW, mutate=True)
    assert dec["invalidations"][0]["reason"] == "ttl", dec


def test_254_dim_class_change():
    state = {"exemptions": [_ex({"159513": "zero_volume"})], "tolerate_streak": {}}
    rep = _report("20261012", 24, ["159513"], ["unfetchable"])   # 类别变化
    dec = gate.evaluate(rep, state, NOW, mutate=True)
    assert dec["invalidations"][0]["reason"] == "class", dec
    assert state["exemptions"][0]["status"] == "invalidated:class", state


def test_254_dim_source_change():
    state = {"exemptions": [_ex({"159513": "zero_volume"},
                               src_ctx={"main_source_ok": True, "fallback_used": False})],
             "tolerate_streak": {}}
    rep = _report("20261012", 24, ["159513"], ["zero_volume"], main_ok=False, fb=True)
    dec = gate.evaluate(rep, state, NOW, mutate=True)
    assert dec["invalidations"][0]["reason"] == "source", dec
    assert state["exemptions"][0]["status"] == "invalidated:source", state


def test_254_dim_expand_new_member_forces_warn():
    """集合新增成员: 曾命中的面出现新码 → 不命中 + expand(当日强制 WARN), 旧记录保持 active。"""
    state = {"exemptions": [_ex({"159513": "zero_volume"})], "tolerate_streak": {}}
    rep = _report("20261012", 24, ["159513", "164508"], ["zero_volume", "zero_volume"])
    dec = gate.evaluate(rep, state, NOW, mutate=True)
    assert dec["exempted"] == [], dec
    assert dec["expansions"] and dec["forced_warn"] is True, dec
    assert dec["tier"] == "warning", dec
    assert state["exemptions"][0]["status"] == "active", state


def test_254_dim_band_strikes_two_then_invalidated():
    """量级超带: r_band > band_cap 连续 2 次 → invalidated:band。"""
    codes = ["561120", "561121", "561122", "561123"]
    state = {"exemptions": [_ex({c: "unfetchable" for c in codes}, band_cap=0.15)],
             "tolerate_streak": {}}
    rep = _report("20261012", 4, codes, ["unfetchable"] * 4)   # r_band = 4/4 = 1.0 > 0.15
    d1 = gate.evaluate(rep, state, NOW, mutate=True)
    assert d1["invalidations"][0]["reason"] == "band" and d1["invalidations"][0]["invalidated"] is False, d1
    assert state["exemptions"][0]["status"] == "active", state
    d2 = gate.evaluate(rep, state, NOW, mutate=True)
    assert state["exemptions"][0]["status"] == "invalidated:band", state
    assert d2["invalidations"][0]["invalidated"] is True, d2


def test_254_p3_streak_ge_D_persistent_warn():
    """P3 累计: 容忍带 0<ratio<=R 连续 >=D=5 运行日 → persistent WARN(仅通知不阻断)。"""
    state = {"exemptions": [], "tolerate_streak": {}}
    row = _series_row("2026-10-08")   # ratio 13.3% 落在容忍带
    rep = _report(row["R"], row["target_count"], row["codes"], ["unfetchable"] * len(row["codes"]))
    for i in range(gate.D_THRESHOLD):
        dec = gate.evaluate(rep, state, NOW, mutate=True)
    assert dec["persistent"] is True and dec["streak"] >= gate.D_THRESHOLD, dec
    assert dec["tier"] == "warning" and dec["reason"] == "tolerate_streak_ge_D", dec
    # 恢复正常(ratio=0)→ streak 清零
    gate.evaluate(_report("20261012", 24, [], []), state, NOW, mutate=True)
    assert state["tolerate_streak"]["count"] == 0, state


# ════════════════════════════════════════════════════════════════════════════
# (e) 既有降噪通道未被破坏
# ════════════════════════════════════════════════════════════════════════════
def test_254_abort_tier_and_dedup_unchanged():
    """abort 的告警档必须与 2026-10-12 降噪逐字一致(tier=warning + 同 dedup key/window)。"""
    assert gate.ABORT_DEDUP_KEY == "kelly_intraday_rerun_fail"
    assert gate.ABORT_DEDUP_WINDOW == 1800
    rep = _report(REAL_0923["R"], 1, REAL_0923["codes"], ["unfetchable"])
    dec = gate.evaluate(rep, {"exemptions": [], "tolerate_streak": {}}, NOW, mutate=False)
    alarm = gate.build_alarm(rep, dec, 5, NOW)
    assert alarm is not None, alarm
    subj, body, tier, key, win = alarm
    assert tier == "warning" and key == "kelly_intraday_rerun_fail" and win == 1800, alarm
    assert "退出码 5" in subj and "本轮跳过" in subj, subj


def test_254_decider_cli_commit_dry_run_abort(tmp_path, capsys):
    """decider --commit --dry-run: 读 abort report → 返回 5, 零真实外发, 状态/ledger 落 tmp。"""
    rep_path = tmp_path / "report.json"
    rep_path.write_text(json.dumps(_report(REAL_0923["R"], 1, REAL_0923["codes"], ["unfetchable"])),
                        encoding="utf-8")
    state_path = tmp_path / "state.json"
    rc = gate.main(["--report", str(rep_path), "--state", str(state_path), "--commit",
                    "--backtest-rc", "5", "--dry-run"])
    out = capsys.readouterr().out
    assert rc == 5, (rc, out)
    assert "[dry-run] notify" in out, out
    assert state_path.exists(), "commit 未落状态"


def test_254_notify_sandbox_is_effective(monkeypatch, tmp_path, capsys):
    """§18 L48: 先证沙箱判定生效 —— dry-run 路径**绝不**触碰 subprocess.run(零外发硬证据);
    非 dry-run 路径的 notify.py 命令构造(tier/dedup key/window)单独用捕获式假 run 验证(仍零外发)。"""
    called = []
    monkeypatch.setattr(gate.subprocess, "run",
                        lambda *a, **k: called.append(a) or (_ for _ in ()).throw(
                            AssertionError("[#254] dry-run 竟然调用了 subprocess.run(外发泄漏!)")),
                        raising=True)
    rep = _report(REAL_0923["R"], 1, REAL_0923["codes"], ["unfetchable"])
    rep_path = tmp_path / "r.json"
    rep_path.write_text(json.dumps(rep), encoding="utf-8")
    rc = gate.main(["--report", str(rep_path), "--state", str(tmp_path / "s.json"),
                    "--commit", "--backtest-rc", "5", "--dry-run"])
    assert rc == 5 and called == [], called          # 沙箱生效: 零 subprocess 调用

    # 命令构造验证: 假 run 捕获 argv, 断言与既有降噪契约一致
    seen = {}

    class _Done:
        returncode = 0

    def _fake_run(cmd, **kw):
        seen["cmd"] = cmd
        return _Done()

    monkeypatch.setattr(gate.subprocess, "run", _fake_run, raising=True)
    dec = gate.evaluate(rep, {"exemptions": [], "tolerate_streak": {}}, NOW, mutate=False)
    rc2 = gate.dispatch_notify(gate.build_alarm(rep, dec, 5, NOW), dry_run=False)
    assert rc2 == 0, rc2
    cmd = seen["cmd"]
    joined = " ".join(str(x) for x in cmd)
    assert str(gate.NOTIFY_PY) in joined and "--tier warning" in joined
    assert "kelly_intraday_rerun_fail" in joined and "1800" in joined, joined


def test_254_decider_cli_print_exit_code(tmp_path, capsys):
    rep_path = tmp_path / "report.json"
    rep_path.write_text(json.dumps(_report(REAL_1012["R"], REAL_1012_TARGET, REAL_1012_CODES,
                                           ["zero_volume"] * len(REAL_1012_CODES))), encoding="utf-8")
    state_path = tmp_path / "state.json"
    rc = gate.main(["--report", str(rep_path), "--state", str(state_path), "--print", "exit_code"])
    assert rc == 0, rc
    assert capsys.readouterr().out.strip() == "0"


def test_254_rerun_sh_delegates_to_decider_and_keeps_exit5_semantics():
    """rerun.sh 必须接 decider, 且保留 exits 5/142/3 语义与 SuccessExitStatus=5 契约(文本锚)。"""
    sh = (ROOT / "scripts" / "kelly_intraday_rerun.sh").read_text(encoding="utf-8")
    assert "kelly_intraday_gate_decider.py" in sh, "rerun.sh 未接 decider"
    assert "--commit" in sh and "--backtest-rc" in sh, sh
    assert 'exit 5' in sh, "abort 退出码 5 语义丢失"
    assert "142" in sh and "exit \"$BK_RC\"" in sh, "非就绪闸失败(142/3)SEVERE 直达链丢失"
    # decider 崩溃回退保险(§23.11 不静默): abort 分支保旧 dedup key + tolerate 分支独立 key
    assert "kelly_intraday_rerun_fail" in sh and "kelly_intraday_gate_decider_crash" in sh, sh


def test_254_unit_success_exit_status_5_present():
    """unit 契约: SuccessExitStatus=5 在位(exit5 是刻意正常跳过, 数据就绪闸 abort)。"""
    doc = (ROOT / "docs" / "deploy" / "systemd-units-20260912.md").read_text(encoding="utf-8")
    snap = (ROOT / "docs" / "deploy" / "systemd-units-cloud-snapshot.txt").read_text(encoding="utf-8")
    assert "SuccessExitStatus=5" in doc and "SuccessExitStatus=5" in snap, "unit 文档缺 SuccessExitStatus=5"


# ════════════════════════════════════════════════════════════════════════════
# 豁免状态机 CLI(confirm / --list / --clear)
# ════════════════════════════════════════════════════════════════════════════
def test_254_ack_confirm_list_clear(tmp_path, capsys):
    state_path = tmp_path / "state.json"
    rep_path = tmp_path / "report.json"
    rep_path.write_text(json.dumps(_report(REAL_1012["R"], REAL_1012_TARGET, REAL_1012_CODES,
                                           ["zero_volume"] * len(REAL_1012_CODES))), encoding="utf-8")
    rc = ack.main(["confirm", "--report", str(rep_path), "--state", str(state_path), "--note", "t"])
    assert rc == 0, capsys.readouterr().out
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert len(state["exemptions"]) == 1 and state["exemptions"][0]["status"] == "active"
    ex_id = state["exemptions"][0]["id"]
    assert state["exemptions"][0]["ttl_days"] == 60, state["exemptions"][0]
    rc = ack.main(["--list", "--state", str(state_path)])
    assert ex_id in capsys.readouterr().out
    rc = ack.main(["--clear", ex_id, "--state", str(state_path)])
    assert rc == 0
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["exemptions"][0]["status"] == "revoked", state


def test_254_freeze_constants():
    """冻结参数(§23.7): R=15% / D=5 / TTL 60d / 取不到 14d / band 地板。"""
    assert gate.R_THRESHOLD == 0.15 and gate.D_THRESHOLD == 5
    assert gate.TTL_DAYS == 60 and gate.UNFETCHABLE_TTL_DAYS == 14
    assert gate.BAND_FLOOR_MIN_CODES == 3 and gate.BAND_FLOOR_RATIO == 0.50