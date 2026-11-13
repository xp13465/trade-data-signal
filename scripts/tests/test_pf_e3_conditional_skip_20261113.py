# -*- coding: utf-8 -*-
"""test_pf_e3_conditional_skip_20261113.py — 17:00 补档 E3「仅当同交易日 16:20 轮已成功才跳过」。

被测(app/collector/public_fund.py, 2026-11-13 /tmp/pf-1700-exit2-rca-20261113.md 方案②a):
  · _e3_round_label / _e3_read_marker / _e3_skip_check / _e3_write_marker — 标记判据
  · pipeline_daily 三指数段 — 有条件跳过编排(零 baostock 调用 + stats['index_*'] 标记)
  · main 'daily' 分支 — 跳过路径 exit 0; 调用路径 RuntimeError→2 / TimeoutError→124 逐位不变

判据口径(任务书 /tmp/task-pf-e3-skip-20261113.md):
  跳过必须同时满足: ①wall-clock>=16:50(17:00 补档) ②标记 round=='16:20'
  ③标记 date==今天 ④success===True ⑤三指数 rows 全>0。
  缺失/跨日/rows=0/success=false/损坏 JSON/主档时段(16:20) 一律照跑。

隔离手法(仿 test_fund_index_reconnect_20261109.py 的 test_real_module_import):
  base/akshare 打桩后从源文件加载真实模块, monkeypatch 模块级名字
  (_e3_now 冻结运行日 L51 / E3_SKIP_MARKER_PATH 指向 tmp / fetch_* spy), 零真实网络零真实库。
  时间全冻结: 不取真实 today(), 隔天恒绿。

跑法:
  .venv/bin/python -m pytest -q scripts/tests/test_pf_e3_conditional_skip_20261113.py
"""
import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]

DAY = dt.datetime(2026, 11, 13)  # 冻结运行日(周五交易日), 与真实 today 解耦
LATE = DAY + dt.timedelta(hours=17, minutes=0, seconds=5)   # 17:00 补档
MAIN = DAY + dt.timedelta(hours=16, minutes=21, seconds=0)  # 16:20 主档
YESTERDAY = DAY - dt.timedelta(days=1)


def _marker(date=None, round_="16:20", success=True, rows=None):
    return {
        "date": (date or DAY).strftime("%Y%m%d"),
        "round": round_,
        "success_ts": f"{(date or DAY).strftime('%Y-%m-%d')} 16:22:31",
        "success": success,
        "rows": rows or {"hs300": 8, "csi500": 8, "gem": 8},
    }


@pytest.fixture
def pf(tmp_path, monkeypatch):
    """加载真实 public_fund 模块(桩 base/akshare), 标记路径指向 tmp, _e3_now 默认冻结。"""
    import app.collector as collector
    base = ModuleType('app.collector.base')
    base.safe_call = lambda fn, **kw: fn(**kw)
    base.throttle = lambda: None
    monkeypatch.setitem(sys.modules, 'app.collector.base', base)
    monkeypatch.setattr(collector, 'base', base, raising=False)
    monkeypatch.setitem(sys.modules, 'akshare', ModuleType('akshare'))
    spec = importlib.util.spec_from_file_location('app.collector._pf_e3_skip_test',
                                                  ROOT / 'app/collector/public_fund.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    marker = tmp_path / 'e3_index_daily_success.json'
    monkeypatch.setattr(module, 'E3_SKIP_MARKER_PATH', marker)
    return SimpleNamespace(m=module, marker=marker)


def _run_pipeline(pf, monkeypatch, now, fetch=None):
    """冻结 now 跑 pipeline_daily; fetch(index_id) 默认成功返回 8 行。返回 (stats, 调用序列, marker)。"""
    calls = []
    monkeypatch.setattr(pf.m, '_e3_now', lambda: now)
    monkeypatch.setattr(pf.m, 'fetch_daily_nav', lambda: 0)
    monkeypatch.setattr(pf.m, 'fetch_estimation', lambda: 0)

    def _fetch(**kw):
        calls.append(kw['index_id'])
        return fetch(kw['index_id']) if fetch else 8

    monkeypatch.setattr(pf.m, 'fetch_index_daily', _fetch)
    monkeypatch.setattr(pf.m, 'get_conn', lambda **kw: SimpleNamespace(
        execute=lambda *a: SimpleNamespace(fetchall=lambda: []), close=lambda: None))
    stats = pf.m.pipeline_daily()
    marker = json.loads(pf.marker.read_text(encoding='utf-8')) if pf.marker.exists() else None
    return stats, calls, marker


# ── 判据单测(纯函数, 直接喂标记) ────────────────────────────────────────────────

def test_skip_check_requires_same_day_1620_success_marker(pf, monkeypatch):
    monkeypatch.setattr(pf.m, 'E3_SKIP_MARKER_PATH', pf.marker)
    pf.marker.write_text(json.dumps(_marker()), encoding='utf-8')
    assert pf.m._e3_skip_check(now=LATE) == _marker()


def test_skip_check_rejects_missing_marker(pf):
    assert pf.m._e3_skip_check(now=LATE) is None  # 无标记 ⇒ 照跑


def test_skip_check_rejects_yesterday_marker(pf):
    pf.marker.write_text(json.dumps(_marker(date=YESTERDAY)), encoding='utf-8')
    assert pf.m._e3_skip_check(now=LATE) is None  # 跨日失效: 昨天的成功不许当今天证据


def test_skip_check_rejects_zero_rows_or_failed_marker(pf):
    for bad in (_marker(rows={"hs300": 8, "csi500": 0, "gem": 8}),
                _marker(rows={"hs300": 0, "csi500": 0, "gem": 0}),
                _marker(success=False)):
        pf.marker.write_text(json.dumps(bad), encoding='utf-8')
        assert pf.m._e3_skip_check(now=LATE) is None, bad  # rows=0/success=false ⇒ 照跑


def test_skip_check_rejects_corrupt_or_wrong_round_marker(pf):
    for bad in ('{bad json', '', '{"date": "20261113"}'):
        pf.marker.write_text(bad, encoding='utf-8')
        assert pf.m._e3_skip_check(now=LATE) is None, bad  # 损坏/缺字段 ⇒ 照跑
    pf.marker.write_text(json.dumps(_marker(round_="17:00")), encoding='utf-8')
    assert pf.m._e3_skip_check(now=LATE) is None  # 轮次歧义(标记非 16:20)⇒ 不猜, 照跑


def test_skip_check_never_skips_main_round(pf):
    # 16:20 主档自身永不跳过(它是标记生产者), 即使当日有效标记已在也不跳
    pf.marker.write_text(json.dumps(_marker()), encoding='utf-8')
    assert pf.m._e3_skip_check(now=MAIN) is None


# ── pipeline_daily 编排(证据用例 1-4: spy 断言零调用/调用发生) ──────────────────

def test_late_round_skips_with_zero_fetch_calls(pf, monkeypatch, capsys):
    pf.marker.write_text(json.dumps(_marker()), encoding='utf-8')
    stats, calls, _ = _run_pipeline(pf, monkeypatch, LATE)
    assert calls == []  # 当日 16:20 成功标记 ⇒ 17:00 轮零 baostock 调用
    assert stats['index_hs300'] == 'skipped(8)'
    assert stats['index_csi500'] == 'skipped(8)'
    assert stats['index_gem'] == 'skipped(8)'
    out = capsys.readouterr().out
    assert '[E3] skipped: 16:20 round succeeded at 2026-11-13 16:22:31' in out
    assert 'fund_index_daily date=20261113 rows=24' in out  # skip 原因+证据日期可 grep


@pytest.mark.parametrize('bad_marker', [
    None,  # 标记缺失
    lambda: _marker(date=YESTERDAY),  # 昨天的标记 ⇒ 跨日失效
    lambda: _marker(rows={"hs300": 8, "csi500": 0, "gem": 8}),  # rows=0 ⇒ 16:20 失败形态
    lambda: _marker(success=False),
])
def test_late_round_runs_full_e3_without_valid_marker(pf, monkeypatch, bad_marker):
    if bad_marker is not None:
        pf.marker.write_text(json.dumps(bad_marker()), encoding='utf-8')
    stats, calls, marker = _run_pipeline(pf, monkeypatch, LATE)
    assert calls == ['hs300', 'csi500', 'gem']  # 必须调用 E3
    assert stats['index_hs300'] == 8  # stats 与原样一致(int 行数)
    assert marker is not None and marker['round'] == '17:00'  # 成功后写补档标记(无后续轮, 无害)


def test_main_round_always_runs_and_writes_marker(pf, monkeypatch):
    pf.marker.write_text(json.dumps(_marker()), encoding='utf-8')  # 即使有标记, 主档也照跑
    stats, calls, marker = _run_pipeline(pf, monkeypatch, MAIN)
    assert calls == ['hs300', 'csi500', 'gem']
    assert marker['round'] == '16:20' and marker['date'] == '20261113'
    assert marker['success'] is True and marker['rows'] == {'hs300': 8, 'csi500': 8, 'gem': 8}
    assert marker['success_ts'].startswith('2026-11-13 16:21')


def test_two_round_flow_1620_success_then_1700_skips(pf, monkeypatch):
    # 端到端: 16:20 主档成功写标记 → 同日 17:00 补档读标记跳过
    _, calls, marker = _run_pipeline(pf, monkeypatch, MAIN)
    assert calls == ['hs300', 'csi500', 'gem'] and marker['round'] == '16:20'
    stats, calls2, _ = _run_pipeline(pf, monkeypatch, LATE)
    assert calls2 == [] and stats['index_hs300'] == 'skipped(8)'


def test_partial_index_failure_writes_no_marker(pf, monkeypatch):
    # 16:20 轮第二指数失败 ⇒ 无标记 ⇒ (次日)17:00 照跑; 失败异常原样抛给 main 映射 exit 2
    def fetch(iid):
        return 8 if iid == 'hs300' else (_ for _ in ()).throw(RuntimeError('查询失败'))
    monkeypatch.setattr(pf.m, '_e3_now', lambda: MAIN)
    monkeypatch.setattr(pf.m, 'fetch_daily_nav', lambda: 0)
    monkeypatch.setattr(pf.m, 'fetch_estimation', lambda: 0)
    monkeypatch.setattr(pf.m, 'fetch_index_daily', lambda **kw: fetch(kw['index_id']))
    monkeypatch.setattr(pf.m, 'get_conn', lambda **kw: SimpleNamespace(
        execute=lambda *a: SimpleNamespace(fetchall=lambda: []), close=lambda: None))
    with pytest.raises(RuntimeError, match='查询失败'):
        pf.m.pipeline_daily()
    assert not pf.marker.exists()


# ── main 'daily' 分支 exit 码(证据用例 5) ─────────────────────────────────────

def _run_daily_cli(pf, monkeypatch, now, fetch):
    monkeypatch.setattr(sys, 'argv', ['public_fund', 'daily'])
    monkeypatch.setattr(pf.m, '_acquire_lock', lambda **kw: True)
    monkeypatch.setattr(pf.m, 'init_db', lambda: None)  # main 入口先建表, 测试不碰真实库
    monkeypatch.setattr(pf.m, '_e3_now', lambda: now)
    monkeypatch.setattr(pf.m, 'fetch_daily_nav', lambda: 0)
    monkeypatch.setattr(pf.m, 'fetch_estimation', lambda: 0)
    monkeypatch.setattr(pf.m, 'fetch_index_daily', lambda **kw: fetch(kw['index_id']))
    monkeypatch.setattr(pf.m, 'get_conn', lambda **kw: SimpleNamespace(
        execute=lambda *a: SimpleNamespace(fetchall=lambda: []), close=lambda: None))


def test_cli_skip_path_exits_zero(pf, monkeypatch, capsys):
    pf.marker.write_text(json.dumps(_marker()), encoding='utf-8')
    def forbidden(*a, **kw):
        pytest.fail('跳过路径不得调用 baostock')
    _run_daily_cli(pf, monkeypatch, LATE, forbidden)
    assert pf.m.main() is None  # 正常返回 = exit 0
    assert '[E3] skipped:' in capsys.readouterr().out


@pytest.mark.parametrize('exc,expected', [(RuntimeError, 2), (TimeoutError, 124)])
def test_cli_call_path_exit_mapping_unchanged(pf, monkeypatch, exc, expected):
    _run_daily_cli(pf, monkeypatch, LATE,
                   lambda iid: (_ for _ in ()).throw(exc('baostock 挂了')))
    with pytest.raises(SystemExit) as e:
        pf.m.main()
    assert e.value.code == expected  # 与改动前逐位一致, 不被 skip 逻辑掩盖


@pytest.mark.parametrize('exc,expected', [(RuntimeError, 2), (TimeoutError, 124)])
def test_cli_main_round_exit_mapping_unchanged(pf, monkeypatch, exc, expected):
    # 主档(16:20)同口径回归
    _run_daily_cli(pf, monkeypatch, MAIN,
                   lambda iid: (_ for _ in ()).throw(exc('baostock 挂了')))
    with pytest.raises(SystemExit) as e:
        pf.m.main()
    assert e.value.code == expected


def test_exit_mapping_source_shape_frozen(pf):
    # 防回归守卫: :5829-5834 的 exit 码映射一行不改(源码形状逐字)
    src = (ROOT / 'app/collector/public_fund.py').read_text(encoding='utf-8')
    frozen = ("    elif cmd == \"daily\":\n"
              "        try:\n"
              "            stats = pipeline_daily()\n"
              "        except (TimeoutError, RuntimeError) as exc:\n"
              "            print(f\"[daily] 采集失败: {exc}\", file=sys.stderr, flush=True)\n"
              "            sys.exit(124 if isinstance(exc, TimeoutError) else 2)\n")
    assert frozen in src, 'daily 分支 exit 码映射被改动 — 任务书硬约束: 一行不改'
