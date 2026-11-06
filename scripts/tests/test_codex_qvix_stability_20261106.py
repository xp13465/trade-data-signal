"""只在临时SQLite/JSON上断言行为，不触达生产或外部服务。"""
import copy
import datetime as dt
import importlib.util
import json
from pathlib import Path
import sqlite3

import pytest

SPEC = importlib.util.spec_from_file_location(
    'qvix_stability_tool', Path(__file__).resolve().parents[1] / 'check_qvix_history_stability.py')
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)


def snapshot():
    return {'schema_version': 1, 'database_realpath': '/fixture/data/sentiment.db',
            'captured_at_utc': '2026-11-06T00:00:00Z',
            'rows': [{'date': d, 'metric_id': m, 'value': 20., 'source': 'akshare', 'updated_at': 'old'}
                     for m in sorted(tool.METRICS) for d in ('20261104', '20261105')]}


def create_db(path, count=2):
    c = sqlite3.connect(path)
    c.execute('CREATE TABLE daily_metric(date TEXT,metric_id TEXT,value REAL,source TEXT,updated_at TEXT)')
    c.executemany('INSERT INTO daily_metric VALUES(?,?,?,?,?)',
                  [((dt.date(1900, 1, 1)+dt.timedelta(days=i)).strftime('%Y%m%d'), m, None if i == 0 else 0.,
                    None if i == 0 else 'rv_local', None)
                   for m in sorted(tool.METRICS) for i in range(count)])
    c.execute('INSERT INTO daily_metric VALUES(?,?,?,?,?)', ('20261105', 'unrelated', 9, 'x', 'x'))
    c.commit()
    c.close()


def compare_cli(tmp_path, capsys, before, after):
    a, b = tmp_path / 'before.json', tmp_path / 'after.json'
    a.write_text(json.dumps(before))
    b.write_text(json.dumps(after))
    initial = a.read_bytes(), b.read_bytes()
    code = tool.main(['--baseline', str(a), '--current', str(b)])
    result = json.loads(capsys.readouterr().out)
    assert (a.read_bytes(), b.read_bytes()) == initial
    return code, result


def test_primary_correction_and_new_fallback_are_allowed(tmp_path, capsys):
    before = snapshot()
    after = copy.deepcopy(before)
    after['rows'][0].update(value=19.27, updated_at='revised')
    for m in tool.METRICS:
        after['rows'].append({'date': '20261106', 'metric_id': m, 'value': 0,
                              'source': 'rv_local', 'updated_at': None})
    code, result = compare_cli(tmp_path, capsys, before, after)
    assert code == 0 and result['review_count'] == 0
    assert sorted(c['kind'] for c in result['changes']) == ['added', 'added', 'primary_revision']
    assert result['changes'][0]['before']['value'] == 20
    assert result['changes'][0]['after']['value'] == 19.27


@pytest.mark.parametrize('source', ['sse', 'rv_local'])
@pytest.mark.parametrize('field,value', [('value', 1), ('source', 'sse'), ('updated_at', 'new')])
def test_existing_fallback_fields_are_flagged(tmp_path, capsys, source, field, value):
    before = snapshot()
    before['rows'][0]['source'] = source
    after = copy.deepcopy(before)
    after['rows'][0][field] = ('rv_local' if source == 'sse' else 'sse') if field == 'source' else value
    code, result = compare_cli(tmp_path, capsys, before, after)
    assert code == 1 and result['review_count'] == 1
    assert result['changes'][0]['kind'] == 'protected_fields_changed'
    assert result['changes'][0]['fields'] == [field]


@pytest.mark.parametrize('old_source', ['manual', 'legacy', None, '', 'rv_local', 'sse'])
def test_fallback_over_existing_any_origin_is_observation(tmp_path, capsys, old_source):
    before = snapshot()
    before['rows'][0]['source'] = old_source
    after = copy.deepcopy(before)
    after['rows'][0].update(source='sse', value=12)
    code, result = compare_cli(tmp_path, capsys, before, after)
    assert code == 1 and result['changes'][0]['kind'] == 'protected_fields_changed'


def test_delete_and_unknown_manual_review(tmp_path, capsys):
    before, after = snapshot(), snapshot()
    after['rows'].pop(0)
    after['rows'][0]['source'] = 'manual'
    code, result = compare_cli(tmp_path, capsys, before, after)
    assert code == 1
    assert {r['kind'] for r in result['changes']} == {'deleted', 'source_change_review'}


@pytest.mark.parametrize('value', [None, 0, -1.5, 10])
def test_unchanged_nullable_and_finite_values(value):
    before = snapshot()
    before['rows'][0].update(value=value, source=None, updated_at=None)
    assert tool.compare(before, copy.deepcopy(before))['changes'] == []


@pytest.mark.parametrize('case', ['duplicate', 'unknown_metric', 'missing_metric', 'identity', 'backwards',
                                  'nonutc', 'date', 'bool', 'nan', 'infinity', 'missing_field', 'schema'])
def test_bad_context_and_rows_exit_two(tmp_path, capsys, case):
    before, after = snapshot(), snapshot()
    if case == 'duplicate':
        after['rows'].append(after['rows'][0].copy())
    elif case == 'unknown_metric':
        after['rows'][0]['metric_id'] = 'us10y'
    elif case == 'missing_metric':
        after['rows'] = [r for r in after['rows'] if r['metric_id'] == 'a_qvix_300']
    elif case == 'identity':
        after['database_realpath'] = '/another/sentiment.db'
    elif case == 'backwards':
        after['captured_at_utc'] = '2026-11-05T00:00:00Z'
    elif case == 'nonutc':
        after['captured_at_utc'] = '2026-11-06T08:00:00+08:00'
    elif case == 'date':
        after['rows'][0]['date'] = '20260230'
    elif case in ('bool', 'nan', 'infinity'):
        after['rows'][0]['value'] = {'bool': True, 'nan': float('nan'), 'infinity': float('inf')}[case]
    elif case == 'missing_field':
        del after['rows'][0]['updated_at']
    else:
        after['schema_version'] = True
    code, result = compare_cli(tmp_path, capsys, before, after)
    assert code == 2 and result['status'] == 'error'


@pytest.mark.parametrize('raw', [b'{', b'\xff', b'[]', b'{"schema_version":1,"schema_version":1}', b'null'])
def test_malformed_json(tmp_path, capsys, raw):
    p = tmp_path / 'bad.json'
    p.write_bytes(raw)
    assert tool.main(['--baseline', str(p), '--current', str(p)]) == 2
    assert json.loads(capsys.readouterr().out)['status'] == 'error'


def test_capture_is_real_readonly_and_does_not_write(tmp_path, monkeypatch, capsys):
    path = tmp_path / 'db with #?.sqlite'
    create_db(path)
    original = path.read_bytes(), path.stat().st_mtime_ns
    connect = sqlite3.connect

    def checked(database, **kwargs):
        assert kwargs['uri'] and database.endswith('?mode=ro')
        c = connect(database, **kwargs)
        with pytest.raises(sqlite3.OperationalError, match='readonly'):
            c.execute('UPDATE daily_metric SET value=999')
        return c

    monkeypatch.setattr(tool.sqlite3, 'connect', checked)
    assert tool.main(['--capture-db', str(path)]) == 0
    captured = json.loads(capsys.readouterr().out)
    assert captured['database_realpath'] == str(path.resolve())
    assert len(captured['rows']) == 4
    assert set(r['metric_id'] for r in captured['rows']) == tool.METRICS
    assert captured['rows'][0]['value'] is None and captured['rows'][0]['source'] is None
    assert (path.read_bytes(), path.stat().st_mtime_ns) == original


def test_missing_database_is_not_created(tmp_path, capsys):
    p = tmp_path / 'absent.sqlite'
    assert tool.main(['--capture-db', str(p)]) == 2
    assert not p.exists()
    assert json.loads(capsys.readouterr().out)['status'] == 'error'


def test_full_history_above_thirty_thousand_rows(tmp_path):
    p = tmp_path / 'large.sqlite'
    create_db(p, count=16_000)
    captured = tool.capture(p)
    assert len(captured['rows']) == 32_000
    raw = tool.compact(captured).encode()
    assert len(raw) > 2 * 1024 * 1024
    f = tmp_path / 'large.json'
    f.write_bytes(raw)
    assert len(tool.load_snapshot(f)['rows']) == 32_000


def test_query_deadline_interrupts_real_sqlite(tmp_path, monkeypatch, capsys):
    p = tmp_path / 'deadline.sqlite'
    create_db(p, count=1000)
    ticks = iter([0.0])
    monkeypatch.setattr(tool.time, 'monotonic', lambda: next(ticks, 4.0))
    assert tool.main(['--capture-db', str(p)]) == 2
    assert 'interrupted' in json.loads(capsys.readouterr().out)['error']


def test_oversize_refuses_without_truncation(tmp_path, monkeypatch, capsys):
    p = tmp_path / 'over.json'
    p.write_text(json.dumps(snapshot()))
    monkeypatch.setattr(tool, 'MAX_BYTES', 20)
    assert tool.main(['--baseline', str(p), '--current', str(p)]) == 2
    assert '16MiB' in json.loads(capsys.readouterr().out)['error']


@pytest.mark.parametrize('source', ['akshare', 'rv_local', 'sse', 'manual', 'unknown', None])
def test_primary_updates_proxy_but_manual_unknown_are_review_only(source):
    before = snapshot()
    before['rows'][0]['source'] = source
    after = copy.deepcopy(before)
    after['rows'][0].update(source='akshare', value=19.27)
    report = tool.compare(before, after)
    allowed = source in ('akshare', 'rv_local', 'sse')
    assert report['review_count'] == (0 if allowed else 1)
    assert report['changes'][0]['kind'] == ('primary_revision' if allowed else 'source_change_review')


def test_row_limit_and_missing_table_fail_closed(tmp_path, capsys, monkeypatch):
    p = tmp_path / 'empty.sqlite'
    sqlite3.connect(p).close()
    assert tool.main(['--capture-db', str(p)]) == 2
    assert json.loads(capsys.readouterr().out)['status'] == 'error'
    monkeypatch.setattr(tool, 'MAX_ROWS', 2)
    with pytest.raises(ValueError, match='rows'):
        tool.validate(snapshot())
