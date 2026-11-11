"""HC07 隔离反例和回归：仅临时SQLite，网络全部替身。"""
import json
from datetime import date, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from scripts import collect_fof_nav as mod
from scripts.tests.test_fof_nav_completeness_20261109 import sandbox
from scripts.tests.test_collect_fof_nav_333 import _conn, _seed_basic, _FakeResp


def source(monkeypatch, records):
    calls = []
    def reply(req, **kw):
        q = parse_qs(urlparse(req.full_url).query)
        calls.append(q)
        selected = [r for r in records if q['startDate'][0] <= r['FSRQ'] <= q['endDate'][0]]
        selected.sort(key=lambda r: r['FSRQ'], reverse=True)
        page, size = int(q['pageIndex'][0]), int(q['pageSize'][0])
        return _FakeResp(json.dumps({'ErrCode': 0, 'Data': {'LSJZList': selected[(page-1)*size:page*size]},
                                    'TotalCount': len(selected), 'PageIndex': page, 'PageSize': size}).encode())
    monkeypatch.setattr(mod.urllib.request, 'urlopen', reply)
    return calls


def records(n=45):
    return [{'FSRQ': (date(2026, 9, 1)+timedelta(days=i)).isoformat(), 'DWJZ': str(1+i/100),
             'LJJZ': str(1+i/100), 'JZZZL': '1'} for i in range(n)]


def test_long_gap_reads_all_pages(sandbox, monkeypatch):
    calls = source(monkeypatch, records())
    rows = mod.fetch_lsjz('000001', '2026-09-01', '2026-11-09')
    assert len(rows) == 45
    assert len(calls) >= 3
    assert rows[19]['prev_unit_nav'] == rows[20]['unit_nav']


def test_late_null_outside_seven_days(sandbox, monkeypatch):
    _seed_basic(sandbox, [('000001', 'FOF', 'FOF')])
    c = _conn(sandbox)
    c.execute("INSERT INTO fund_daily_nav(date,fund_code) VALUES('20260901','000001')")
    c.commit(); c.close()
    source(monkeypatch, records(1))
    mod.collect()
    c = _conn(sandbox)
    assert c.execute("SELECT unit_nav FROM fund_daily_nav WHERE date='20260901'").fetchone()[0] == 1
    c.close()


@pytest.mark.parametrize('mode', ['duplicate', 'missing', 'page', 'count'])
def test_bad_pages_reject_entire_fund(sandbox, monkeypatch, mode):
    _seed_basic(sandbox, [('000001', 'FOF', 'FOF')])
    source(monkeypatch, records())
    real = mod.urllib.request.urlopen
    def corrupt(req, **kw):
        payload = json.loads(real(req, **kw).read())
        if payload['PageIndex'] == 2:
            if mode == 'duplicate':
                payload['Data']['LSJZList'][0]['FSRQ'] = '2026-10-15'
            elif mode == 'missing':
                payload['Data']['LSJZList'].pop()
            elif mode == 'page':
                payload['PageIndex'] = 1
            else:
                payload['TotalCount'] += 1
        return _FakeResp(json.dumps(payload).encode())
    monkeypatch.setattr(mod.urllib.request, 'urlopen', corrupt)
    assert mod.collect() == 0
    assert mod.LAST_BATCH_FAILED
    c = _conn(sandbox)
    assert c.execute('SELECT COUNT(*) FROM fund_daily_nav').fetchone()[0] == 0
    assert c.execute('SELECT COUNT(*) FROM fund_collection_state').fetchone()[0] == 0
    c.close()


def test_conflict_rolls_back_new_rows_and_all_fields_with_evidence(sandbox, monkeypatch):
    _seed_basic(sandbox, [('000001', 'FOF', 'FOF')])
    c = _conn(sandbox)
    c.execute("INSERT INTO fund_daily_nav(date,fund_code,unit_nav) VALUES('20260901','000001',9)")
    c.commit(); c.close()
    source(monkeypatch, records())
    assert mod.collect() == 0
    c = _conn(sandbox)
    assert [tuple(r) for r in c.execute('SELECT date,unit_nav,acc_nav FROM fund_daily_nav')] == [('20260901',9,None)]
    assert [tuple(r) for r in c.execute('SELECT date,field,before_value,after_value FROM fund_collection_conflicts')] == [('20260901','unit_nav',9,1)]
    assert c.execute('SELECT COUNT(*) FROM fund_collection_state').fetchone()[0] == 0
    c.close()


def test_timeout_half_batch_preserves_attempt_cursor_and_rolls_back_target(sandbox, monkeypatch):
    import time
    _seed_basic(sandbox, [('000001','FOF','FOF'),('000002','FOF','FOF')])
    def fetch(code, *args, **kwargs):
        if code == '000002':
            time.sleep(.08)
        return [dict(date='20261106',fund_code=code,unit_nav=1,acc_nav=1,prev_unit_nav=None,nav_change_pct=0)]
    monkeypatch.setattr(mod, 'fetch_lsjz', fetch)
    with pytest.raises(TimeoutError):
        mod.collect(budget_seconds=.06)
    progress = json.loads(sandbox.with_suffix('.fof-nav-progress.json').read_text())
    assert progress['last_code'] == '000002'
    assert progress['work_limits']['000002']['history_days'] == 183
    c = _conn(sandbox)
    assert [r[0] for r in c.execute('SELECT fund_code FROM fund_daily_nav')] == ['000001']
    assert [r[0] for r in c.execute('SELECT code FROM fund_collection_state')] == ['000001']
    c.close()
    # 尝试游标不是成功游标：重启继续轮转，失败基金下一圈仍会回来。
    monkeypatch.setattr(mod, 'fetch_lsjz', lambda code,*a,**kw: [dict(date='20261106',fund_code=code,unit_nav=1,acc_nav=1,prev_unit_nav=None,nav_change_pct=0)])
    mod.collect(batch=1)
    assert json.loads(sandbox.with_suffix('.fof-nav-progress.json').read_text())['last_code'] == '000001'
    mod.collect(batch=1)
    assert json.loads(sandbox.with_suffix('.fof-nav-progress.json').read_text())['last_code'] == '000002'


def slow_pages(monkeypatch, rows):
    """真实分页/JSON/SQLite；确定性时钟避免用机器调度快慢决定断言。"""
    from types import SimpleNamespace
    from app.collector import public_fund_gap as gap
    clock = [100.0]
    timer = SimpleNamespace(monotonic=lambda: clock[0], time=lambda: clock[0], sleep=lambda seconds: None)
    monkeypatch.setattr(mod, 'time', timer)
    monkeypatch.setattr(gap, 'time', timer)
    calls = source(monkeypatch, rows)
    original = mod.urllib.request.urlopen
    def slow(req, **kwargs):
        result = original(req, **kwargs)
        clock[0] += .09
        return result
    monkeypatch.setattr(mod.urllib.request, 'urlopen', slow)
    return calls


def test_timeout_rotates_funds_and_eventually_commits_complete_smaller_history(sandbox, monkeypatch):
    _seed_basic(sandbox, [('000001','FOF','FOF'), ('000002','FOF','FOF')])
    calls = slow_pages(monkeypatch, records())
    progress_path = sandbox.with_suffix('.fof-nav-progress.json')
    for expected in ('000001', '000002'):
        with pytest.raises(TimeoutError):
            mod.collect(batch=1, budget_seconds=.22)
        assert json.loads(progress_path.read_text())['last_code'] == expected
        c = _conn(sandbox)
        assert c.execute('SELECT COUNT(*) FROM fund_daily_nav').fetchone()[0] == 0
        assert c.execute('SELECT COUNT(*) FROM fund_collection_state').fetchone()[0] == 0
        c.close()
    # Empty recent windows remain legitimate. History shrinks only after a
    # timeout and eventually admits full responses under the original budget.
    for _ in range(24):
        try:
            mod.collect(batch=1, budget_seconds=.22)
        except TimeoutError:
            pass
    c = _conn(sandbox)
    for code in ('000001', '000002'):
        rows = list(c.execute('SELECT date,unit_nav FROM fund_daily_nav WHERE fund_code=? ORDER BY date', (code,)))
        assert len(rows) == 45
        assert [tuple(r) for r in rows] == [(r['FSRQ'].replace('-',''), float(r['DWJZ'])) for r in records()]
        assert c.execute('SELECT history_before FROM fund_collection_state WHERE code=?', (code,)).fetchone()[0] < '20260901'
    c.close()
    assert {q['fundCode'][0] for q in calls} == {'000001', '000002'}


def test_sparse_gaps_shrink_without_advancing_failed_coverage(sandbox, monkeypatch):
    from app.collector import public_fund_gap as gap
    _seed_basic(sandbox, [('000001', 'FOF', 'FOF')])
    c = _conn(sandbox); gap.migrate(c)
    c.execute("INSERT INTO fund_collection_state VALUES('nav','000001','19900101','')")
    for i in range(64):
        day = date(2020,1,2)+timedelta(days=10*i)
        c.execute("INSERT INTO fund_daily_nav(date,fund_code,unit_nav,acc_nav,prev_unit_nav,nav_change_pct) VALUES(?,'000001',1,1,1,0)", ((day-timedelta(days=1)).strftime('%Y%m%d'),))
        c.execute("INSERT INTO fund_daily_nav(date,fund_code,unit_nav,prev_unit_nav,nav_change_pct) VALUES(?,'000001',1,1,0)", (day.strftime('%Y%m%d'),))
    c.execute("INSERT INTO fund_daily_nav(date,fund_code,unit_nav,acc_nav,prev_unit_nav,nav_change_pct) VALUES('20261109','000001',1,1,1,0)")
    c.commit(); c.close()
    slow_pages(monkeypatch, [])
    with pytest.raises(TimeoutError):
        mod.collect(batch=1, budget_seconds=.22)
    c = _conn(sandbox)
    assert tuple(c.execute('SELECT history_before,gap_after FROM fund_collection_state').fetchone()) == ('19900101','')
    assert c.execute('SELECT COUNT(*) FROM fund_collection_gaps').fetchone()[0] == 0
    c.close()
    for _ in range(22):
        try:
            mod.collect(batch=1, budget_seconds=.22)
        except TimeoutError:
            pass
    c = _conn(sandbox)
    assert c.execute('SELECT COUNT(*) FROM fund_collection_gaps WHERE attempts>0').fetchone()[0] >= 4
    assert c.execute('SELECT COUNT(*) FROM fund_daily_nav WHERE acc_nav IS NULL').fetchone()[0] == 64
    assert c.execute('SELECT history_before FROM fund_collection_state').fetchone()[0] == '19900101'
    c.close()


def test_adaptive_recent_crosses_complete_empty_windows(sandbox, monkeypatch):
    from app.collector import public_fund_gap as gap
    _seed_basic(sandbox, [('000001','FOF','FOF')])
    c = _conn(sandbox); gap.migrate(c)
    c.execute("INSERT INTO fund_collection_state VALUES('nav','000001','19900101','')")
    c.execute("INSERT INTO fund_daily_nav(date,fund_code,unit_nav,acc_nav,prev_unit_nav,nav_change_pct) VALUES('20260101','000001',1,1,1,0)")
    c.commit(); c.close()
    path = sandbox.with_suffix('.fof-nav-progress.json')
    path.write_text(json.dumps({'version':1,'last_code':'000001','work_limits':{
        '000001':{'history_days':7,'gap_fields':2,'phase':'recent'}}}))
    calls = source(monkeypatch, [dict(FSRQ='2026-01-25',DWJZ='1.2',LJJZ='1.2',JZZZL='0')])
    for _ in range(10):
        mod.collect(batch=1)
    c = _conn(sandbox)
    assert c.execute("SELECT unit_nav FROM fund_daily_nav WHERE date='20260125'").fetchone()[0] == 1.2
    assert c.execute('SELECT COUNT(*) FROM fund_daily_nav').fetchone()[0] == 2
    assert c.execute('SELECT history_before FROM fund_collection_state').fetchone()[0] == '19900101'
    c.close()
    assert json.loads(path.read_text())['work_limits']['000001']['recent_through'] >= '20260125'
    assert any(q['endDate'][0] == '2026-01-08' for q in calls)


def test_failed_recent_does_not_advance_verified_window(sandbox, monkeypatch):
    _seed_basic(sandbox, [('000001','FOF','FOF')])
    path = sandbox.with_suffix('.fof-nav-progress.json')
    path.write_text(json.dumps({'version':1,'last_code':'000001','work_limits':{
        '000001':{'history_days':7,'gap_fields':2,'phase':'recent','recent_through':'20260108'}}}))
    def fail(*a, **kw):
        raise TimeoutError('upstream failed before the round deadline')
    monkeypatch.setattr(mod,'fetch_lsjz',fail)
    assert mod.collect(batch=1) == 0
    assert mod.LAST_BATCH_FAILED
    assert json.loads(path.read_text())['work_limits']['000001']['recent_through'] == '20260108'


def test_http_trickle_is_absolute_bounded(sandbox, monkeypatch):
    import time
    class Slow(_FakeResp):
        def read(self):
            time.sleep(2)
            return super().read()
    monkeypatch.setattr(mod.urllib.request,'urlopen',lambda *a,**kw:Slow(b'{}'))
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        mod.fetch_lsjz('000001','2026-01-01','2026-11-09',deadline=started+.04)
    assert time.monotonic()-started < .5


def test_null_queue_fairness_no_repaired_marker_on_empty(sandbox, monkeypatch):
    from app.collector import public_fund_gap as gap
    _seed_basic(sandbox,[('000001','FOF','FOF')])
    c = _conn(sandbox)
    gap.migrate(c)
    c.execute("INSERT INTO fund_collection_state VALUES('nav','000001','19900101','')")
    c.executemany("INSERT INTO fund_daily_nav(date,fund_code) VALUES(?,'000001')",[(r['FSRQ'].replace('-',''),) for r in records(100)])
    c.commit();c.close()
    source(monkeypatch,[])
    for _ in range(4):
        mod.collect()
    c = _conn(sandbox)
    assert c.execute('SELECT COUNT(*) FROM fund_collection_gaps WHERE attempts>0').fetchone()[0] >= 200
    assert c.execute('SELECT COUNT(*) FROM fund_daily_nav WHERE unit_nav IS NOT NULL').fetchone()[0] == 0
    assert not mod.LAST_BATCH_FAILED
    c.close()


def test_initial_history_resumes_without_replacing_fof_cursor(sandbox, monkeypatch):
    _seed_basic(sandbox,[('000001','FOF','FOF')])
    old = dict(FSRQ='2001-01-03',DWJZ='1.1',LJJZ='1.1',JZZZL='0')
    calls=source(monkeypatch,[old])
    for _ in range(37):
        mod.collect()
    c=_conn(sandbox)
    assert c.execute('SELECT unit_nav FROM fund_daily_nav').fetchone()[0] == 1.1
    assert c.execute('SELECT history_before FROM fund_collection_state').fetchone()[0] == '19900101'
    c.close()
    # 初始化完成后不会每次从1990重读；NULL仍单独排队。
    calls.clear();mod.collect()
    assert all(q['startDate'][0] > '1990-01-01' for q in calls)


def index_db(path):
    c=_conn(path)
    c.execute('CREATE TABLE IF NOT EXISTS fund_index_daily(date TEXT,index_id TEXT,close REAL,pct_change REAL,PRIMARY KEY(date,index_id))')
    c.execute("CREATE INDEX IF NOT EXISTS idx_fund_index_daily_id ON fund_index_daily(index_id)")
    c.commit()
    return c


def test_index_full_incremental_every_field_equal_and_old_gap(sandbox):
    import time
    from app.collector import public_fund_gap as gap
    # 同一输入，有上下文、三个指数、窗口外NULL，不以行数代替逐字段比对。
    values=[dict(date=(date(2025,10,1)+timedelta(days=i)).strftime('%Y%m%d'),close=3000+i,pct_change=i/1000) for i in range(405)]
    full=sandbox.parent/'full.db';inc=sandbox.parent/'inc.db'
    for db in [full,inc]:index_db(db).close()
    calls=[]
    def fetch(start,end,index_id,**kw):
        calls.append((start,end,kw['deadline']))
        return [r for r in values if start<=r['date']<=end]
    deadline=time.monotonic()+15
    for iid in ['hs300','csi500','gem']:
        c=index_db(full)
        # 全量基线与增量使用相同历史下界（增量保留已有更早历史，不能删来凑相等）。
        c.executemany('INSERT INTO fund_index_daily VALUES(?,?,?,?)',
                      [(r['date'],iid,r['close'],r['pct_change']) for r in values if '20251004'<=r['date']<='20261109'])
        c.commit();c.close()
        gap.collect_index(fetch,lambda **kw:index_db(inc),iid,'20261108',deadline,2)
    c=index_db(inc)
    c.execute("UPDATE fund_index_daily SET pct_change=NULL WHERE date='20251015'")
    c.commit();c.close()
    calls.clear()
    for iid in ['hs300','csi500','gem']:
        gap.collect_index(fetch,lambda **kw:index_db(inc),iid,'20261109',deadline,2)
    a=index_db(full);b=index_db(inc)
    assert [tuple(r) for r in a.execute('SELECT * FROM fund_index_daily ORDER BY index_id,date')] == [tuple(r) for r in b.execute('SELECT * FROM fund_index_daily ORDER BY index_id,date')]
    assert all(d==deadline for _,_,d in calls)
    assert sum((date.fromisoformat(f'{e[:4]}-{e[4:6]}-{e[6:]}')-date.fromisoformat(f'{s[:4]}-{s[4:6]}-{s[6:]}')).days for s,e,_ in calls)<100
    a.close();b.close()


def test_index_conflict_and_dry_run_zero_writes(sandbox):
    import time
    from app.collector import public_fund_gap as gap
    c=index_db(sandbox)
    c.execute("INSERT INTO fund_index_daily VALUES('20261106','hs300',4000,NULL)")
    c.commit();c.close()
    before=sandbox.read_bytes()
    fetch=lambda *a,**kw:[dict(date='20261106',close=4000,pct_change=1)]
    import sqlite3
    gap.collect_index(fetch,lambda **kw:sqlite3.connect(sandbox.as_uri()+'?mode=ro',uri=True),'hs300','20261109',time.monotonic()+5,1,True)
    assert sandbox.read_bytes()==before
    def revised(*a,**kw):return [dict(date='20261109',close=4100,pct_change=1),dict(date='20261106',close=4001,pct_change=1)]
    with pytest.raises(gap.NonNullConflict):
        gap.collect_index(revised,lambda **kw:index_db(sandbox),'hs300','20261109',time.monotonic()+5,1)
    c=index_db(sandbox)
    assert [tuple(r) for r in c.execute('SELECT * FROM fund_index_daily')]==[('20261106','hs300',4000,None)]
    assert c.execute('SELECT COUNT(*) FROM fund_collection_conflicts').fetchone()[0]==1
    c.close()


def test_budget_exhausted_starts_no_http(sandbox,monkeypatch):
    import time
    def denied(*a,**kw):raise AssertionError('预算耗尽仍联网')
    monkeypatch.setattr(mod.urllib.request,'urlopen',denied)
    with pytest.raises(TimeoutError):mod.fetch_lsjz('000001','2026-01-01','2026-11-09',deadline=time.monotonic()-1)


def test_null_discovery_query_plan_does_not_scan_other_funds(sandbox):
    from app.collector import public_fund_gap as gap
    c=_conn(sandbox)
    gap.migrate(c)
    c.executemany("INSERT INTO fund_daily_nav(date,fund_code,unit_nav,acc_nav,prev_unit_nav,nav_change_pct) VALUES(?,'000001',1,1,1,0)",
                  [(r['FSRQ'].replace('-',''),) for r in records(100)])
    c.execute("INSERT INTO fund_collection_state VALUES('nav','000001','19900101','')")
    c.commit()
    def measure():
        instructions=[0];queries=[]
        def tick():instructions[0]+=1;return 0
        c.set_progress_handler(tick,100)
        c.set_trace_callback(queries.append)
        planned=gap.plan(c,'nav','000001','20261109','19900101')
        c.set_progress_handler(None,0);c.set_trace_callback(None)
        plans=[c.execute('EXPLAIN QUERY PLAN '+q).fetchall() for q in queries if 'FROM fund_daily_nav' in q]
        assert all(any('USING INDEX idx_daily_nav_code' in row[3] for row in plan) for plan in plans)
        assert planned['discovered']==[]
        return instructions[0]
    baseline=measure()
    c.executemany("INSERT INTO fund_daily_nav(date,fund_code) VALUES('20261106',?)",[(f'{i:06d}',) for i in range(2,20002)])
    c.commit()
    assert measure()<=baseline+5  # 其他基金增加两万行，不增加扫描工作量。
    c.execute('DROP INDEX idx_daily_nav_code')
    with pytest.raises(Exception,match='no such index'):
        gap.plan(c,'nav','000001','20261109','19900101')
    c.close()


def test_old_schema_migration_is_idempotent_and_no_business_commit(sandbox):
    from app.collector import public_fund_gap as gap
    c=_conn(sandbox)
    c.execute("INSERT INTO fund_daily_nav(date,fund_code,unit_nav) VALUES('20261106','000001',1)")
    gap.migrate(c);gap.migrate(c)
    c.rollback()
    assert c.execute('SELECT COUNT(*) FROM fund_daily_nav').fetchone()[0]==0
    c.close()


def test_dry_run_never_creates_lock_or_state(sandbox,monkeypatch):
    _seed_basic(sandbox,[('000001','FOF','FOF')])
    source(monkeypatch,records())
    def denied(*a,**kw):raise AssertionError('dry-run写路径')
    monkeypatch.setattr(mod,'init_db',denied)
    monkeypatch.setattr(mod,'get_conn',denied)
    before={p.name:p.read_bytes() for p in sandbox.parent.iterdir() if p.is_file()}
    assert mod.collect(dry_run=True)==45
    after={p.name:p.read_bytes() for p in sandbox.parent.iterdir() if p.is_file()}
    assert before==after


@pytest.mark.parametrize('missing',['TotalCount','PageIndex','PageSize'])
def test_missing_coverage_metadata_is_not_empty_success(sandbox,monkeypatch,missing):
    payload={'ErrCode':0,'Data':{'LSJZList':[]},'TotalCount':0,'PageIndex':1,'PageSize':20}
    del payload[missing]
    monkeypatch.setattr(mod.urllib.request,'urlopen',lambda *a,**kw:_FakeResp(json.dumps(payload).encode()))
    with pytest.raises(ValueError):mod.fetch_lsjz('000001','2026-01-01','2026-11-09')


def test_fof_full_incremental_every_stored_field_equal(sandbox,monkeypatch):
    full=sandbox.parent/'full-nav.db';incremental=sandbox.parent/'incremental-nav.db'
    for db in [full,incremental]:
        _seed_basic(db,[('000001','FOF','FOF')])
    all_rows=records(45)
    def run(db,raw):
        monkeypatch.setattr(mod,'DB_PATH',db)
        monkeypatch.setattr(mod,'get_conn',lambda:_conn(db))
        source(monkeypatch,raw)
        mod.collect()
    run(full,all_rows)
    run(incremental,all_rows[:40])
    c=_conn(incremental)
    c.execute("UPDATE fund_daily_nav SET acc_nav=NULL WHERE date='20260902'")
    c.commit();c.close()
    run(incremental,all_rows)
    a=_conn(full);b=_conn(incremental)
    assert [tuple(r) for r in a.execute('SELECT * FROM fund_daily_nav ORDER BY date,fund_code')] == [tuple(r) for r in b.execute('SELECT * FROM fund_daily_nav ORDER BY date,fund_code')]
    a.close();b.close()


def test_pool_addition_before_cursor_is_eventually_visited(sandbox,monkeypatch):
    _seed_basic(sandbox,[('000002','FOF','FOF'),('000004','FOF','FOF')])
    called=[]
    monkeypatch.setattr(mod,'fetch_lsjz',lambda code,*a,**kw:called.append(code) or [])
    mod.collect(batch=1)
    _seed_basic(sandbox,[('000001','new','FOF')])
    called.clear()
    mod.collect(batch=1);mod.collect(batch=1)
    assert list(dict.fromkeys(called))==['000004','000001']


def test_null_queue_can_repair_dates_older_than_completed_history(sandbox,monkeypatch):
    from app.collector import public_fund_gap as gap
    _seed_basic(sandbox,[('000001','FOF','FOF')])
    c=_conn(sandbox);gap.migrate(c)
    c.execute("INSERT INTO fund_collection_state VALUES('nav','000001','19900101','')")
    c.execute("INSERT INTO fund_daily_nav(date,fund_code) VALUES('20010103','000001')")
    c.execute("INSERT INTO fund_daily_nav VALUES('20261106','000001','FOF',2,2,1,1)")
    c.commit();c.close()
    source(monkeypatch,[dict(FSRQ='2001-01-03',DWJZ='1',LJJZ='1',JZZZL='0')])
    mod.collect()
    c=_conn(sandbox)
    assert c.execute("SELECT unit_nav FROM fund_daily_nav WHERE date='20010103'").fetchone()[0]==1
    assert c.execute("SELECT COUNT(*) FROM fund_collection_gaps WHERE date='20010103' AND field='unit_nav'").fetchone()[0]==0
    c.close()


def test_dry_run_rejects_uncheckpointed_wal_without_hiding_rows(sandbox,monkeypatch):
    _seed_basic(sandbox,[('000001','FOF','FOF')])
    c=_conn(sandbox)
    c.execute("INSERT INTO fund_daily_nav(date,fund_code,unit_nav) VALUES('20261106','000001',2)")
    c.commit()
    before={p.name:p.read_bytes() for p in sandbox.parent.iterdir() if p.is_file()}
    with pytest.raises(ValueError,match='WAL'):mod.collect(dry_run=True)
    assert {p.name:p.read_bytes() for p in sandbox.parent.iterdir() if p.is_file()}==before
    c.close()


from scripts.tests.test_fund_index_reconnect_20261109 import isolated


def test_actual_index_default_entrypoint_is_incremental_with_shared_deadline(isolated,monkeypatch,tmp_path,capsys):
    import time
    import sqlite3
    db=tmp_path/'actual-index.db'
    c=index_db(db);c.close()
    monkeypatch.setitem(isolated.fetch.__globals__,'get_conn',lambda **kw:sqlite3.connect(db))
    deadline=time.monotonic()+5
    assert isolated.fetch(end_date='20261109',deadline=deadline)==6
    first=capsys.readouterr().out
    assert '"start_date": "2025-10-05"' in first
    assert isolated.fetch(end_date='20261109',deadline=deadline)==6
    second=capsys.readouterr().out
    assert '"start_date": "2026-10-26"' in second
    assert all(float(call[7])==deadline for call in isolated.calls)
    c=sqlite3.connect(db)
    assert c.execute('SELECT COUNT(*) FROM fund_index_daily').fetchone()[0]==6
    c.close()
