"""Fixed, private projections of trade-delivery-receipt-v1; no collector DB/network.

The producer owns business predicates. Indices retain the newest invocation,
including failures. They are observations with a short validity window, not a
permanent recovery flag. Publication uses existing export byte identities.
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import tempfile
import time
import uuid

try:
    from .delivery_evidence import (emit_receipt, read_receipt, receipt_root, _private_dir,
                                   _metadata_failure, evidence_enabled, identity_for_bytes,
                                   identity_for_loaded, loaded_code_identity, _validate, _canonical)
except ImportError:
    from delivery_evidence import (emit_receipt, read_receipt, receipt_root, _private_dir,
                                   _metadata_failure, evidence_enabled, identity_for_bytes,
                                   identity_for_loaded, loaded_code_identity, _validate, _canonical)

RULE = 'ops-business-v1'
INDEX_LOCK_TIMEOUT_SECONDS = 0.25
ZONE = ZoneInfo('Asia/Shanghai')
TURNOVER = ('overview.json', 'boot.json', 'signals_today.json') + tuple('a-stock-' + r + '.json' for r in ('3m', '6m', '1y', '3y', '5y', 'all'))
OVERFIT = ('overfit_monitor.json', 'overfit_monitor_ext.json')
METRICS = ('a_turnover_mean', 'a_turnover_median', 'a_turnover_p90', 'a_turnover_p10', 'a_turnover_gt5_pct')
OBJECTS = {'turnover': ('trade-turnover-backfill.service', 'publication'),
           'overfit': ('trade-overfit-monitor.service', 'publication'),
           **{'backup-' + name: ('trade-backup-db.service', 'backup') for name in ('sentiment', 'etf_national_team', 'stock_daily', 'public_fund')}}


def now():
    return datetime.now(timezone.utc)


def stamp(value):
    return value.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def parsed(value):
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        raise ValueError('timezone required')
    return dt


def bounded_json(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
            raise ValueError('private regular index required')
        payload = stream.read(65537)
    if len(payload) > 65536:
        raise ValueError('index limit')
    return json.loads(payload)


def _index_lock_path(directory, object_id):
    # Ordering is per object; unrelated R2 callbacks must never contend.
    return directory / ('.' + hashlib.sha256(object_id.encode()).hexdigest() + '.lock')


def _acquire_index_lock(fd):
    deadline = time.monotonic() + INDEX_LOCK_TIMEOUT_SECONDS
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError as exc:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('evidence index lock deadline') from exc
            time.sleep(min(0.01, remaining))


def write_index(root, record):
    """No older success can overwrite a newer running or failed invocation."""
    directory = receipt_root(root) / 'index'
    _private_dir(directory)
    target = directory / (record['object_id'] + '.json')
    lock = os.open(_index_lock_path(directory, record['object_id']), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    tmp = None
    try:
        _acquire_index_lock(lock)
        try:
            prior = bounded_json(target)
        except FileNotFoundError:
            prior = None
        def order(r):
            return (parsed(r['producer_time']['started_at']), parsed(r['evaluated_at']))
        if prior and order(prior) >= order(record):
            return
        fd, tmp = tempfile.mkstemp(prefix='.index-', dir=directory)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(_canonical(record)); stream.flush(); os.fsync(stream.fileno())
        os.replace(tmp, target)
    finally:
        if tmp:
            Path(tmp).unlink(missing_ok=True)
        os.close(lock)


def write_publication_index(root, record):
    directory = receipt_root(root) / 'publication'
    _private_dir(directory)
    directory /= hashlib.sha256(record['attempt_id'].encode()).hexdigest()
    _private_dir(directory)
    target = directory / record['object_id']
    lock = os.open(_index_lock_path(directory, record['object_id']), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    tmp = None
    try:
        _acquire_index_lock(lock)
        try:
            prior = bounded_json(target)
        except FileNotFoundError:
            prior = None
        if prior and parsed(prior['evaluated_at']) >= parsed(record['evaluated_at']):
            return
        fd, tmp = tempfile.mkstemp(prefix='.publication-', dir=directory)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(_canonical(record)); stream.flush(); os.fsync(stream.fileno())
        os.replace(tmp, target)
    finally:
        if tmp:
            Path(tmp).unlink(missing_ok=True)
        os.close(lock)


def publication_confirmations(root, run_id, outputs, started_at):
    """Read only this run's named receipts; no directory/history scan."""
    directory = receipt_root(root) / 'publication' / hashlib.sha256(run_id.encode()).hexdigest()
    confirmed = {}
    for name, expected in outputs.items():
        try:
            r = bounded_json(directory / name)
            _validate(r)
            if (r['chain_id'] != 'ops_publication' or r['attempt_id'] != run_id or r['object_id'] != name or
                r['stage_status'] != 'success' or parsed(r['evaluated_at']) < parsed(started_at)):
                continue
            values = r['outputs']
            if len(values) == 1 and values[0].get('object_id') == name and all(values[0].get(k) == expected[k] for k in ('sha256', 'size')):
                confirmed[name] = expected
        except (OSError, ValueError, TypeError, KeyError):
            continue
    return confirmed


def record_result(root, object_id, *, run_id, started_at, status='unknown', reason='not_observed',
                  inputs=(), outputs=(), confirmed=(), expected=0, observed=0, business_date=None,
                  invocation_id=None, code=None, finished_at=None, valid_until=None, publication_run_id=None):
    """Best effort metadata only; original business return/exception is unchanged."""
    if not evidence_enabled():
        return {'status': 'disabled'}
    try:
        if object_id not in OBJECTS:
            raise ValueError('unregistered business object')
        at = now()
        day = business_date or parsed(started_at).astimezone(ZONE).date().isoformat()
        witness = {'scope': RULE, 'invocation_id': invocation_id if invocation_id is not None else os.environ.get('INVOCATION_ID', 'unknown'),
                   'rule_version': RULE, 'valid_until': valid_until or stamp(parsed(started_at) + timedelta(hours=26)),
                   'confirmed': list(confirmed), 'publication_run_id': publication_run_id}
        result = emit_receipt(data_root=root, stage='restore' if object_id.startswith('backup-') else 'publish',
            chain_id='ops_business', object_id=object_id, session_date=day, attempt_id=run_id,
            batch_id=run_id, stage_status=status, reason=reason, inputs=inputs, outputs=outputs,
            counts={'expected': expected, 'validated': observed},
            code_identity={'sha': code} if code else loaded_code_identity(record_result, root),
            config_identity={'sha256': hashlib.sha256(RULE.encode()).hexdigest()}, consumer_witness=witness,
            producer_time={'started_at': started_at, 'completed_at': finished_at}, evaluated_at=stamp(at),
            evidence_quality='strong' if status == 'success' else 'unknown')
        if result['status'] in ('written', 'idempotent'):
            receipt = read_receipt(receipt_root(root) / 'receipts' / day / 'ops_business' / (result['receipt_id'] + '.json'))
            write_index(root, receipt)
        return result
    except Exception as exc:
        return _metadata_failure(exc)


def assess(root, object_id, at, code, live):
    """Only six bounded private indices; never stat/hash/query business data."""
    ev = {'execution_state': 'not_observed', 'source_reason': 'receipt_missing',
          'unknown_reason': 'receipt_missing', 'next_evidence': 'current_invocation_business_receipt',
          'event_at': None, 'valid_until': None, 'rule_version': RULE}
    def result(reason, status='unknown'):
        ev['source_reason'] = reason
        ev['unknown_reason'] = reason if status == 'unknown' else None
        return status, ev
    try:
        # Reject symlinked index ancestors as well as the leaf.
        directory = receipt_root(root) / 'index'
        for path in (receipt_root(root), directory):
            if path.is_symlink():
                return result('unsafe_index')
        r = bounded_json(directory / (object_id + '.json'))
        _validate(r)
        w, times = r['consumer_witness'], r['producer_time']
        if r['object_id'] != object_id or r['chain_id'] != 'ops_business' or w.get('rule_version') != RULE:
            return result('rule_or_object_mismatch')
        start = parsed(times['started_at'])
        end = parsed(times['completed_at']) if times.get('completed_at') else None
        expiry = parsed(w['valid_until'])
        ev.update(run_id=r['attempt_id'], business_date=r['session_date'], code_ref=r['code_identity'].get('sha'),
                  event_at=stamp(end) if end else None, valid_until=stamp(expiry),
                  coverage_expected=r['counts'].get('expected'), coverage_observed=r['counts'].get('validated'),
                  execution_state='completed' if end else 'running')
        if start > at or (end and (end < start or end > at)) or expiry <= at or expiry > start + timedelta(hours=26):
            return result('expired_or_invalid_time')
        if r['session_date'] != at.astimezone(ZONE).date().isoformat():
            return result('business_date_mismatch')
        if not re.fullmatch('[a-f0-9]{40}', code) or r['code_identity'].get('sha') != code:
            return result('code_ref_mismatch')
        def prop(k):
            v = live.get(k, [])
            return v[0] if v else ''
        if not live or w.get('invocation_id') in (None, '', 'unknown') or w['invocation_id'] != prop('InvocationID'):
            return result('invocation_not_verified')
        if prop('ActiveState') in ('activating', 'reloading') or prop('SubState') in ('start', 'running'):
            ev['execution_state'] = 'running'
            return result('invocation_running')
        if prop('Result') not in ('success', '') or prop('ExecMainStatus') not in ('0', '') or prop('ActiveState') == 'failed':
            ev['execution_state'] = 'failed'
            return result('invocation_failed', 'warning')
        if prop('ActiveState') != 'inactive' or prop('Result') != 'success' or prop('ExecMainStatus') != '0':
            return result('completion_missing')
        if not end:
            return result('completion_missing')
        if r['stage_status'] == 'failure':
            ev['execution_state'] = 'failed'
            return result('business_failed', 'warning')
        if r['stage_status'] != 'success' or not ev['coverage_expected'] or ev['coverage_observed'] != ev['coverage_expected']:
            return result('coverage_or_completion_unverified')
        if object_id == 'overfit':
            token = w.get('publication_run_id')
            if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}', token):
                return result('generation_unverified')
            ev['publication_run_id'] = token
        def identities(values):
            out = {}
            for v in values:
                if (not re.fullmatch('[a-f0-9]{64}', v.get('sha256', '')) or
                    not re.fullmatch('[A-Za-z0-9_.-]{1,100}', v.get('object_id', '')) or v['object_id'] in out):
                    raise ValueError('invalid identity')
                out[v['object_id']] = v['sha256']
            return out
        ins, outs, confirmed = identities(r['inputs']), identities(r['outputs']), identities(w.get('confirmed', []))
        if not ins or not outs or outs != confirmed:
            return result('hash_or_confirmation_missing')
        ev.update(input_hash=hashlib.sha256(_canonical(ins)).hexdigest(), output_hash=hashlib.sha256(_canonical(outs)).hexdigest())
        return result('current_invocation_verified', 'ok')
    except FileNotFoundError:
        return result('receipt_missing')
    except Exception:
        return result('receipt_invalid')


def record_backup(root, entry, run_id, started_at, success):
    raw = dict(entry['raw'], object_id=entry['name'] + '.db')
    source = dict(entry['gzip'], object_id=Path(entry['key']).name)
    counts = entry['tables']
    return record_result(root, 'backup-' + entry['name'], run_id=run_id, started_at=started_at,
        status='success' if success else 'unknown', reason='source_bound_restore' if success else 'restore_started',
        inputs=[source], outputs=[raw] if success else [], confirmed=[raw] if success else [],
        expected=len(counts), observed=sum(type(n) is int and n > 0 for n in counts.values()) if success else 0,
        business_date=datetime.strptime(entry['key'].rsplit('_', 1)[1].split('.')[0], '%Y%m%d').date().isoformat(),
        finished_at=stamp(now()) if success else None)


def record_publication(root, object_id, run_id, started_at, outputs, confirmed, inputs, expected, observed, rc=0, publication_run_id=None):
    """R2 integration seam: existing {name:{size,sha256}} and confirmed same-run map.

    Caller must get confirmed bytes from its existing write/readback result, never
    from command exit alone. No new R2 proof format is required.
    """
    complete = bool(outputs) and outputs == confirmed and expected == observed and expected > 0
    return record_result(root, object_id, run_id=run_id, started_at=started_at,
        status='failure' if rc else 'success' if complete else 'unknown', reason='exit_' + str(rc) if rc else 'business_result' if complete else 'publication_unconfirmed',
        inputs=inputs, outputs=[dict(v, object_id=k) for k, v in outputs.items()],
        confirmed=[dict(v, object_id=k) for k, v in confirmed.items()], expected=expected, observed=observed,
        finished_at=stamp(now()), publication_run_id=publication_run_id)


def turnover_result(root, run_id, started_at, rc):
    """Producer-only fixed-date SELECT. Collector never calls this function."""
    try:
        from r2_export_proof import load_run_proof, output_record
        day = parsed(started_at).astimezone(ZONE).strftime('%Y%m%d')
        con = sqlite3.connect((Path(root) / 'data/sentiment.db').absolute().as_uri() + '?mode=ro', uri=True, timeout=1)
        try:
            con.set_progress_handler(lambda: 1, 100000)
            rows = con.execute('SELECT metric_id,value FROM daily_metric WHERE date=? AND metric_id IN (?,?,?,?,?) LIMIT 6', (day, *METRICS)).fetchall()
        finally:
            con.close()
        import math
        good = len(rows) == len(METRICS) and {r[0] for r in rows} == set(METRICS) and all(isinstance(r[1], (int, float)) and math.isfinite(r[1]) for r in rows)
        outputs = load_run_proof(os.environ.get('OPS_TURNOVER_PROOF'), run_id, Path(root) / 'static-site')
        outputs = {k: v for k, v in outputs.items() if k in TURNOVER}
        # Bind actual date/value content to the existing byte proof, not just a
        # successful SQL query plus unrelated current-sized export files.
        decoded = {}
        budget = 64 << 20
        for name in TURNOVER:
            fd = os.open(Path(root) / 'static-site/data' / name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, 'rb') as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise ValueError('regular export required')
                payload = stream.read(min(budget, 32 << 20) + 1)
            if len(payload) > min(budget, 32 << 20) or output_record(payload) != outputs.get(name):
                raise ValueError('export byte proof mismatch')
            budget -= len(payload)
            decoded[name] = json.loads(payload)
        values = dict(rows)
        ov = decoded['overview.json']
        def same_rows(items, key):
            return good and all(len(found := [r for r in items if r.get(key) == mid and r.get('date') == day]) == 1
                                and found[0].get('value') == values[mid] for mid in METRICS)
        valid = same_rows(ov['today']['metrics'], 'id')
        expected_boot = dict(ov); expected_boot.pop('signals_today', None)
        valid = valid and decoded['boot.json']['overview'] == expected_boot
        valid = valid and decoded['signals_today.json'] == {k:ov.get(k) for k in ('date','signals_today','signals_meta')}
        for name in TURNOVER[3:]:
            metrics = decoded[name]['metrics']
            valid = valid and all(len(found := [r for r in metrics[mid]['data'] if r.get('date') == day]) == 1
                                  and found[0].get('value') == values[mid] for mid in METRICS)
        confirmed = publication_confirmations(root, run_id, outputs, started_at)
        return record_publication(root, 'turnover', run_id, started_at, outputs, confirmed,
            [identity_for_loaded('turnover_daily_rows', rows)], len(METRICS) + len(TURNOVER),
            (len(METRICS) if good else 0) + (len(outputs) if valid else 0), rc)
    except Exception as exc:
        _metadata_failure(exc)
        return record_result(root, 'turnover', run_id=run_id, started_at=started_at,
            status='failure' if rc else 'unknown', reason='business_result_unavailable', finished_at=stamp(now()))


def main():
    p = argparse.ArgumentParser()
    p.add_argument('action', choices=('begin', 'turnover', 'failure'))
    p.add_argument('--object', choices=OBJECTS, required=True)
    p.add_argument('--root', required=True); p.add_argument('--run', required=True)
    p.add_argument('--started', required=True); p.add_argument('--rc', type=int, default=0)
    a = p.parse_args()
    if not evidence_enabled():
        return
    if a.action == 'turnover':
        turnover_result(a.root, a.run, a.started, a.rc)
    else:
        record_result(a.root, a.object, run_id=a.run, started_at=a.started,
            status='failure' if a.action == 'failure' else 'unknown', reason='exit_' + str(a.rc) if a.action == 'failure' else 'running',
            finished_at=stamp(now()) if a.action == 'failure' else None)


if __name__ == '__main__':
    main()
