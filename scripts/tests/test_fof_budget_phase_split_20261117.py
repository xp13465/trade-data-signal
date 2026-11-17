# -*- coding: utf-8 -*-
"""test_fof_budget_phase_split_20261117.py - FOF 21:10 预算耗尽根治(A+B)验收(2026-11-17)。

依据 /tmp/task-fof-budget-rootfix-20261117.md + /tmp/fof-budget-rca-20261117.md。
六条硬要求逐条对应:
  1. recent 相位截断 ⇒ 仍 raise TimeoutError(rc=1 硬承诺), 摘要如实 truncated;
  2. backfill 到 deadline ⇒ 软停 rc=0 + backfill_not_attempted 与已处理数分开;
  3. 回补相位锁被占 ⇒ main() exit 3(不静默 rc0), recent 相位保持旧语义 rc0;
  4. backfill_pending 优先队列顺序(滞后最久先补) + 游标保底推进(新 code 不饿死);
  5. 收据 expected/observed 同为「只」(按基金去重), 提交事件数另存 committed_events;
  6. 非交易日/全空批退出语义: 合法空 rc0 不假失败, 收据也不假 success。

纪律:
  - 冻结运行日/时钟(§18 L51): 注入 date.today()/datetime.now() + 模块级 monotonic,
    用例不依赖真实 today()/now(); 另跑 TZ=UTC / TZ=Asia/Shanghai 双环境验证。
  - 零网络(fetch 全打桩)、零外发(subprocess.run 全打桩, §18 L48)、临时 SQLite。
  - 看门狗判据边界单测: 恰好 7 个交易日不告警、8 个告警、覆盖率达标不告警。
"""
import json
import sys
import sqlite3
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.collector import public_fund_gap as gap
from scripts import collect_fof_nav as fof
from scripts import check_fof_backfill as watchdog
from scripts import ops_business_evidence as business
from scripts.tests.test_collect_fof_nav_333 import _conn, _seed_basic


# ── 冻结运行日 / 时钟(注入, 不改标准库全局) ───────────────────────────────
_FROZEN_DAY = {'date': date(2026, 11, 17), 'now': datetime(2026, 11, 17, 21, 20, 0)}


class _FrozenDate(date):
    @classmethod
    def today(cls):
        return _FROZEN_DAY['date']


class _FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return _FROZEN_DAY['now']


def _freeze(monkeypatch, day=None, now=None):
    if day is not None:
        _FROZEN_DAY['date'] = day
    if now is not None:
        _FROZEN_DAY['now'] = now
    monkeypatch.setattr(fof, 'date', _FrozenDate)
    monkeypatch.setattr(fof, 'datetime', _FrozenDatetime)


@pytest.fixture(autouse=True)
def frozen_run_day(monkeypatch):
    _freeze(monkeypatch)
    yield
    _FROZEN_DAY['date'] = date(2026, 11, 17)
    _FROZEN_DAY['now'] = datetime(2026, 11, 17, 21, 20, 0)


class _Clock:
    def __init__(self, start=10_000.0):
        self.now = start

    def monotonic(self):
        return self.now

    def time(self):
        return 1_700_000_000.0 + self.now

    def sleep(self, seconds):
        self.now += max(0.0, float(seconds))


@pytest.fixture
def clock(monkeypatch):
    """模块级时钟注入: 只有被测采集器/缺口模块看到假时钟, 证据/告警仍走真实时间。"""
    c = _Clock()
    monkeypatch.setattr(fof, 'time', SimpleNamespace(monotonic=c.monotonic, time=c.time,
                                                     sleep=c.sleep))
    monkeypatch.setattr(gap, 'time', SimpleNamespace(monotonic=c.monotonic))

    def remaining(deadline):
        left = deadline - c.now
        if left <= 0:
            raise TimeoutError('公募整轮预算耗尽')
        return left

    monkeypatch.setattr(gap, 'remaining', remaining)
    return c


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(fof, 'RATE_LIMIT', 0)
    monkeypatch.setattr(fof, '_acquire_lock',
                        lambda nonblock=True, lock_name='public_fund', **kw: True)
    monkeypatch.setattr(fof, 'init_db', lambda: None)  # schema 由 _conn 建
    monkeypatch.setattr(fof, 'fetch_lsjz', lambda *a, **k: pytest.fail('API not mocked'))
    sent = []
    monkeypatch.setattr(fof.subprocess, 'run', lambda cmd, **kw: sent.append(cmd))
    return sent


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / 'data' / 'public_fund.db'
    path.parent.mkdir()
    _conn(path).close()
    monkeypatch.setattr(fof, 'DB_PATH', path)
    monkeypatch.setattr(fof, 'get_conn', lambda: _conn(path))
    return path


@pytest.fixture
def evidence_on(monkeypatch):
    monkeypatch.setenv('OPS_DELIVERY_EVIDENCE_ENABLED', '1')
    monkeypatch.setenv('INVOCATION_ID', 'test-invocation')
    monkeypatch.delenv('OPS_FUND_RUN', raising=False)
    monkeypatch.delenv('OPS_FUND_STARTED', raising=False)


def _progress_path(db: Path) -> Path:
    return db.with_suffix('.fof-nav-progress.json')


def _funds(n):
    return [(f'{i:06d}', 'FOF-测试', 'FOF') for i in range(1, n + 1)]


def _row(code, day='20261116'):
    return dict(date=day, fund_code=code, unit_nav=1.2, acc_nav=1.3,
                prev_unit_nav=1.1, nav_change_pct=0.5)


def _limits(codes):
    return {c: {'history_days': 366, 'gap_fields': 64, 'phase': 'history'} for c in codes}


def _read_receipt(root):
    r = business.bounded_json(root / 'data/ops_delivery/index/fof-nav.json')
    return r, r['consumer_witness'].get('fund_evidence', {})


# ── 1. recent 相位截断 ⇒ rc=1(硬承诺) ───────────────────────────────────
def test_case1_recent_truncation_is_hard_failure(db, clock, monkeypatch, capsys):
    _seed_basic(db, _funds(3))

    def fetch(code, *a, **k):
        clock.now += 150 if code == '000001' else 100
        return [_row(code)]

    monkeypatch.setattr(fof, 'fetch_lsjz', fetch)
    with pytest.raises(TimeoutError):
        fof.collect(batch=3, phase='recent')  # 默认预算=recent 硬上限 200s

    saved = json.loads(_progress_path(db).read_text())
    run = saved['last_runs']['recent']
    assert run['phase'] == 'recent'
    assert run['stage_status'] == 'truncated'
    assert run['terminal_error'] == 'TimeoutError'
    assert (run['selected'], run['attempted']) == (3, 2)
    assert saved['last_code'] == '000002'          # 尝试制: 停在被中断那只, 不回退
    assert fof.LAST_BATCH_FAILED is False          # 预算中断≠整批失败(exit 2)
    out = capsys.readouterr().out
    assert '回补到点软停' not in out               # recent 相位绝不做软完成


def test_case1_budget_cap_is_phase_specific(monkeypatch):
    """相位预算硬上限显式可判: recent 200 < backfill 600; both 保留旧 290。"""
    assert fof.PHASE_BUDGET_CAPS == {'both': 290.0, 'recent': 200.0, 'backfill': 600.0}
    with pytest.raises(ValueError):
        fof.collect(budget_seconds=201, phase='recent')
    with pytest.raises(ValueError):
        fof.collect(budget_seconds=601, phase='backfill')


# ── 2. backfill 到 deadline ⇒ rc=0 + backfill_not_attempted 正确 ─────────
def test_case2_backfill_wall_deadline_soft_stop_rc0(db, clock, monkeypatch, capsys):
    _seed_basic(db, _funds(5))
    _progress_path(db).write_text(json.dumps({
        'version': 1, 'last_code': '000000', 'work_limits': _limits([f'{i:06d}' for i in range(1, 6)]),
    }))
    # 冻结在 21:30, 墙钟截止 21:32 ⇒ 只剩 120s, 挤掉 600s 预算(守门保险生效)。
    _freeze(monkeypatch, now=datetime(2026, 11, 17, 21, 30, 0))

    def fetch(code, *a, **k):
        clock.now += 100
        return [_row(code)]

    monkeypatch.setattr(fof, 'fetch_lsjz', fetch)
    monkeypatch.setattr(sys, 'argv', ['collect_fof_nav', '--phase', 'backfill',
                                      '--batch', '5', '--deadline-at', '21:32'])
    assert fof.main() == 0                          # 软完成 rc=0(不是 rc=1)
    assert fof.LAST_BATCH_FAILED is False
    assert fof.LAST_LOCK_OCCUPIED is False

    saved = json.loads(_progress_path(db).read_text())
    run = saved['last_runs']['backfill']
    assert run['stage_status'] == 'soft_complete'
    assert (run['selected'], run['attempted']) == (5, 2)
    assert run['backfill_not_attempted'] == 3       # 未跑到 3 只, 与已处理 2 只分开
    # 未处置的(含到点被回滚那只)进优先队列, 下轮必再取; 已提交两只出队。
    assert saved['backfill_pending'] == ['000002', '000003', '000004', '000005']
    assert saved['backfill_pending_since']['000002'] == '20261117'
    assert saved['backfill_last_attempt']['000001'] == '20261117'
    assert '000003' not in saved['backfill_last_attempt']
    out = capsys.readouterr().out
    assert '回补到点软停(soft_complete)' in out
    assert 'backfill_not_attempted=3' in out


def test_case2_both_phase_keeps_old_hard_timeout(db, clock, monkeypatch):
    """both 保留旧两遍同预算语义: 预算耗尽仍 raise TimeoutError(不静默转 rc0)。"""
    _seed_basic(db, _funds(2))

    def fetch(code, *a, **k):
        clock.now += 150
        return [_row(code)]

    monkeypatch.setattr(fof, 'fetch_lsjz', fetch)
    with pytest.raises(TimeoutError):
        fof.collect(batch=2, phase='both')


# ── 3. 回补相位锁被占 ⇒ exit 3 ───────────────────────────────────────────
def test_case3_backfill_lock_occupied_exit3(db, clock, monkeypatch):
    _seed_basic(db, _funds(1))
    monkeypatch.setattr(fof, '_acquire_lock',
                        lambda nonblock=True, lock_name='public_fund', **kw: False)

    monkeypatch.setattr(sys, 'argv', ['collect_fof_nav', '--phase', 'backfill', '--batch', '1'])
    assert fof.main() == 3
    assert fof.LAST_LOCK_OCCUPIED is True

    # recent 相位锁被占保持旧语义(每日一次的机会, 下一轮即可), 不升级成 exit 3。
    monkeypatch.setattr(sys, 'argv', ['collect_fof_nav', '--phase', 'recent', '--batch', '1'])
    assert fof.main() == 0
    assert fof.LAST_LOCK_OCCUPIED is False


# ── 4. 优先队列顺序 + 游标保底推进 ───────────────────────────────────────
def test_case4_queue_order_oldest_lag_first_then_cursor(db, clock, monkeypatch):
    _seed_basic(db, _funds(10))
    codes = [f'{i:06d}' for i in range(1, 11)]
    _progress_path(db).write_text(json.dumps({
        'version': 1, 'last_code': '000002', 'work_limits': _limits(codes),
        'backfill_cursor': '000002',
        'backfill_pending': ['000008', '000010', '000009'],
        'backfill_pending_since': {'000010': '20261110', '000008': '20261105',
                                   '000009': '20261107'},
    }))
    fetched = []
    monkeypatch.setattr(fof, 'fetch_lsjz',
                        lambda code, *a, **k: fetched.append(code) or [_row(code)])
    fof.collect(batch=5, phase='backfill')

    # 队列按入队日升序: 000008(1105) → 000009(1107) → 000010(1110), 再按游标补 000003/000004。
    assert fetched == ['000008', '000009', '000010', '000003', '000004']
    saved = json.loads(_progress_path(db).read_text())
    assert saved['backfill_cursor'] == '000004'     # 游标保底推进
    assert saved['backfill_pending'] == []          # 已处置出队


def test_case4_cursor_reserve_prevents_new_code_starvation(db, clock, monkeypatch):
    """大队列占满时仍留 1/5 名额给游标尾部(新 code 不被饿死)。"""
    _seed_basic(db, _funds(20))
    codes = [f'{i:06d}' for i in range(1, 21)]
    queue = [f'{i:06d}' for i in range(11, 21)]
    since = {c: f'202611{d:02d}' for d, c in zip(range(1, 11), queue)}
    _progress_path(db).write_text(json.dumps({
        'version': 1, 'last_code': '000000', 'work_limits': _limits(codes),
        'backfill_cursor': '000000', 'backfill_pending': queue,
        'backfill_pending_since': since,
    }))
    fetched = []
    monkeypatch.setattr(fof, 'fetch_lsjz',
                        lambda code, *a, **k: fetched.append(code) or [_row(code)])
    fof.collect(batch=5, phase='backfill')

    assert len(fetched) == 5
    assert fetched[:4] == ['000011', '000012', '000013', '000014']  # 队列滞后优先
    assert fetched[-1] == '000001'                                  # 游标保底名额
    saved = json.loads(_progress_path(db).read_text())
    assert saved['backfill_cursor'] == '000001'


# ── 5. 收据量纲一致(expected/observed 同为「只」) ─────────────────────────
def test_case5_receipt_expected_observed_same_unit(db, clock, evidence_on, monkeypatch):
    _seed_basic(db, _funds(3))
    calls = []

    def fetch(code, *a, **k):
        calls.append(code)
        return [_row(code)]

    monkeypatch.setattr(fof, 'fetch_lsjz', fetch)
    fof.collect(batch=3, phase='both')  # 两遍都提交 ⇒ 事件 6 次, 目标仍 3 只
    assert len(calls) == 6

    r, f = _read_receipt(db.parent.parent)
    counts = f['counts']
    assert counts['selected'] == 3
    assert counts['attempted'] == 3
    assert counts['committed_targets'] == 3      # 按基金去重 = 只
    assert counts['committed_events'] == 6       # 提交事件数单独记, 不再顶替 observed
    assert r['counts']['expected'] == 3          # expected = selected(只)
    assert r['counts']['validated'] == 3         # observed = committed_targets(只, 同量纲)
    assert r['counts']['validated'] != counts['committed_events']
    assert r['stage_status'] == 'success' and f['run_status'] == 'complete'


# ── 6. 非交易日 / 全空批退出语义(消除假成功) ─────────────────────────────
def test_case6_all_empty_batch_rc0_but_receipt_not_success(db, clock, evidence_on,
                                                            monkeypatch, capsys):
    _seed_basic(db, _funds(1))
    monkeypatch.setattr(fof, 'fetch_lsjz', lambda *a, **k: [])  # 合法空(封闭期/未发布)
    monkeypatch.setattr(sys, 'argv', ['collect_fof_nav', '--phase', 'recent', '--batch', '1'])
    assert fof.main() == 0                       # 合法空不是 exit 2 假故障
    assert fof.LAST_BATCH_FAILED is False
    r, f = _read_receipt(db.parent.parent)
    assert f['counts']['legal_empty'] == 1
    assert f['counts']['committed_rows'] == 0
    # 合法空仍算「本轮已处置目标」(targets=1, 出优先队列), 但 committed_rows=0 ⇒
    # 收据 status 必须是 unknown 而不是 success(消除假成功; 修复前会记 success)。
    assert f['counts']['committed_targets'] == 1
    assert f['collection_status'] != 'failure'
    assert f['run_status'] == 'complete'
    assert r['stage_status'] == 'unknown'        # 全空批: 跑完也绝不记 success
    assert 'BATCH_FAIL' not in capsys.readouterr().out


def test_case6_wrappers_gate_non_trading_day_and_fix_gradient():
    """非交易日闸门写明 + 相位拆分后的预算字面量(旧 290/两遍混用已清除)。"""
    recent = Path('scripts/run_fof_nav_collect.sh').read_text()
    backfill = Path('scripts/run_fof_nav_backfill.sh').read_text()
    assert 'is_trading_day' in recent and '非交易日，跳过' in recent
    assert 'is_trading_day' in backfill and '非交易日，跳过' in backfill
    assert 'run_to 480' in recent and '--phase recent' in recent
    assert 'run_to 720' in backfill and '--phase backfill --deadline-at 21:35' in backfill
    assert 'run_to 290' not in recent and 'run_to 290' not in backfill
    assert '--phase both' not in recent and '--phase both' not in backfill


# ── 冻结运行日：隔天仍绿 ─────────────────────────────────────────────────
def test_next_day_still_green_same_cursor_and_status(db, clock, monkeypatch):
    """冻结日平移到次日: 同样的截断场景结论不变(用例不依赖真实 today())。"""
    _freeze(monkeypatch, day=date(2026, 11, 18), now=datetime(2026, 11, 18, 21, 20, 0))
    _seed_basic(db, _funds(3))

    def fetch(code, *a, **k):
        clock.now += 150 if code == '000001' else 100
        return [_row(code, day='20261117')]

    monkeypatch.setattr(fof, 'fetch_lsjz', fetch)
    with pytest.raises(TimeoutError):
        fof.collect(batch=3, phase='recent')
    saved = json.loads(_progress_path(db).read_text())
    run = saved['last_runs']['recent']
    assert run['date'] == '20261118'
    assert run['stage_status'] == 'truncated'
    assert (run['selected'], run['attempted']) == (3, 2)
    assert saved['last_code'] == '000002'


# ── 看门狗判据边界(恰好 7 天不告警 / 8 天告警 / 覆盖率达标不告警) ──────────
def _progress(selected=1, attempted=1, status='complete', pending=None,
              since=None, attempt=None):
    return {
        'version': 1, 'last_code': '000001', 'work_limits': {},
        'backfill_pending': pending or [],
        'backfill_pending_since': since or {},
        'backfill_last_attempt': attempt or {},
        'last_runs': {'recent': {'date': '20261117', 'selected': selected,
                                 'attempted': attempted, 'stage_status': status},
                      'backfill': {'date': '20261117', 'backfill_not_attempted': 4}},
    }


def test_watchdog_trading_days_between_boundary():
    assert watchdog.trading_days_between('20261106', '20261117', None) == 7
    assert watchdog.trading_days_between('20261105', '20261117', None) == 8
    assert watchdog.trading_days_between('20261117', '20261117', None) == 0
    assert watchdog.trading_days_between('20261118', '20261117', None) == 0  # 未来日期不制造负滞后


def test_watchdog_exactly_seven_trading_days_no_alert():
    facts = watchdog.judge(_progress(pending=['000010'],
                                     since={'000010': '20261106'}), '20261117', None)
    assert facts['action'] is False
    assert facts['lag_days'] == 7
    assert '超过阈值 0 只' in facts['visible']
    assert '仅可见, 不告警' in facts['visible']  # backfill_not_attempted 只做可见指标


def test_watchdog_eight_trading_days_alert():
    facts = watchdog.judge(_progress(pending=['000010'],
                                     since={'000010': '20261105'}), '20261117', None)
    assert facts['action'] is True
    assert facts['lag_days'] == 8
    assert facts['lag_codes'] == ['000010']
    assert '回补滞后 > 7 个交易日' in facts['message']


def test_watchdog_lag_anchor_uses_latest_attempt():
    """入队很久但最近刚尝试 ⇒ 不算滞后(锚 = max(入队日, 最近尝试日))。"""
    facts = watchdog.judge(_progress(pending=['000010'],
                                     since={'000010': '20261001'},
                                     attempt={'000010': '20261116'}), '20261117', None)
    assert facts['action'] is False and facts['lag_days'] == 1


def test_watchdog_coverage_ok_no_alert_and_shortfall_alerts():
    ok = watchdog.judge(_progress(selected=5, attempted=5), '20261117', None)
    assert ok['action'] is False and '5/5' in ok['visible']
    bad = watchdog.judge(_progress(selected=5, attempted=4), '20261117', None)
    assert bad['action'] is True
    assert '覆盖率不足' in bad['message'] and '4/5' in bad['message']


def test_watchdog_undated_pending_visible_only_no_alert():
    facts = watchdog.judge(_progress(pending=['000010']), '20261117', None)
    assert facts['action'] is False
    assert '1 只无入队日期' in facts['visible']


def test_watchdog_malformed_progress_raises_not_green():
    with pytest.raises(ValueError):
        watchdog.judge({'backfill_pending': []}, '20261117', None)
    with pytest.raises(ValueError):
        watchdog.judge({'last_runs': []}, '20261117', None)


def test_watchdog_cli_exit_codes(tmp_path, monkeypatch):
    path = tmp_path / 'prog.json'
    path.write_text(json.dumps(_progress(selected=2, attempted=2)))
    monkeypatch.setattr(sys, 'argv', ['check_fof_backfill.py', '--progress', str(path),
                                      '--today', '20261117'])
    assert watchdog.main() == 0
    path.write_text(json.dumps(_progress(selected=2, attempted=1)))
    assert watchdog.main() == 1
    path.write_text('not-json')
    assert watchdog.main() == 2
