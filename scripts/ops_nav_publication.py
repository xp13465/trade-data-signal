"""Opt-in NAV evidence: committed input -> exporter bytes -> canonical public GET.

No collection, DB query, upload or new notification. Public reads are a separate
explicit, bounded operation. A confirmed selected scope is not whole-pool health,
source completeness, an atomic 256-bucket snapshot or a new publication SLA.
"""
from __future__ import annotations

import argparse
from datetime import timedelta
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import tempfile
import time
import types
import inspect

try:
    from . import ops_business_evidence as business
    from .delivery_evidence import (_canonical, _metadata_failure, _private_dir,
        _validate, emit_receipt, evidence_enabled, loaded_code_identity, read_receipt, receipt_root)
except ImportError:
    import ops_business_evidence as business
    from delivery_evidence import (_canonical, _metadata_failure, _private_dir,
        _validate, emit_receipt, evidence_enabled, loaded_code_identity, read_receipt, receipt_root)

OBJECTS = ('public-fund', 'fof-nav')
INPUT_VERSION = 'nav-committed-scope-v1'
MAX_INPUT_BYTES = 4 * 1024 * 1024
MAX_INPUT_ROWS = 60000
MAX_BUCKET_BYTES = 32 * 1024 * 1024
PUBLIC_BASE = 'https://ss.fx8.store/r2/nav_bucket/'
_CACHE = None
_WORK_SECONDS = 2.0


def fund_bucket(code):
    """Single Python implementation of the existing FNV-1a bucket rule."""
    h = 2166136261
    for ch in str(code or ''):
        h ^= ord(ch)
        h = (h * 16777619) & 0xFFFFFFFF
    return f'{h & 0xFF:02x}'


def _regular(path, limit):
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as f:
        info = os.fstat(f.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError('invalid NAV evidence file')
        raw = f.read(limit + 1)
        if len(raw) > limit:
            raise ValueError('oversized NAV evidence')
        return raw


def _file_identity(info):
    if not stat.S_ISREG(info.st_mode):
        raise ValueError('NAV bucket is not a regular file')
    return {'device': info.st_dev, 'inode': info.st_ino,
            'mtime_ns': info.st_mtime_ns, 'size': info.st_size}


def file_identity(fd):
    """Capture the actual open read/write descriptor, not a later pathname."""
    if not evidence_enabled():
        return None
    try:
        return _file_identity(os.fstat(fd))
    except Exception as exc:
        _metadata_failure(exc)
        return None


def _bucket_path(root, bucket):
    if not re.fullmatch('[a-f0-9]{2}', bucket):
        raise ValueError('invalid bucket')
    return Path(root).absolute() / 'static-site' / 'data' / 'nav_bucket' / (bucket+'.json')


def _current_file(root, bucket):
    # Fixed names only, metadata stat only; never hash/read a business file here.
    return _file_identity(_bucket_path(root, bucket).lstat())


def _input_path(root, object_id, run):
    if object_id not in OBJECTS or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', run):
        raise ValueError('invalid collection identity')
    return receipt_root(root) / 'nav-inputs' / (hashlib.sha256((object_id+':'+run).encode()).hexdigest()+'.json')


def normalized_row(row):
    if isinstance(row, dict):
        code, day, unit, acc = row['fund_code'], row['date'], row['unit_nav'], row.get('acc_nav')
    else:
        day, code, _, unit, acc, *_ = row
    if unit is None:
        return None  # NULL input does not overwrite an old DB value or create a published NAV.
    if not re.fullmatch(r'\d{6}', str(code)) or not re.fullmatch(r'\d{8}', str(day)):
        raise ValueError('invalid NAV row identity')
    for value in (unit, acc):
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)):
            raise ValueError('invalid NAV value')
    # acc=None is COALESCE/no assertion, not an assertion that the DB value is NULL.
    return [str(code), str(day), unit, acc]


def save_inputs(root, object_id, run, started, rows):
    """One private sidecar per completed collection, outside the 64KiB receipt.

    Caller supplies only rows after commit. Errors are metadata failures, never
    collector errors. No latest-pointer or production data mutation is performed.
    """
    if not evidence_enabled():
        return None
    try:
        if not rows or len(rows) > MAX_INPUT_ROWS:
            raise ValueError('empty or oversized committed scope')
        ordered = sorted(rows.values(), key=lambda r: (r[0], r[1]))
        body = {'version': INPUT_VERSION, 'object_id': object_id, 'run': run,
                'started_at': started, 'rows': ordered}
        raw = _canonical(body)
        if len(raw) > MAX_INPUT_BYTES:
            raise ValueError('committed scope exceeds evidence budget')
        target = _input_path(root, object_id, run)
        _private_dir(target.parent)
        if target.exists():
            if _regular(target, MAX_INPUT_BYTES) != raw:
                raise ValueError('immutable committed scope conflict')
        else:
            fd, temp = tempfile.mkstemp(prefix='.nav-input-', dir=target.parent)
            try:
                with os.fdopen(fd, 'wb') as f:
                    f.write(raw); f.flush(); os.fsync(f.fileno())
                # Atomic create, never replace an existing run's input.
                try:
                    os.link(temp, target)
                except FileExistsError:
                    if _regular(target, MAX_INPUT_BYTES) != raw:
                        raise ValueError('concurrent committed scope conflict')
            finally:
                Path(temp).unlink(missing_ok=True)
        return {'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw), 'rows': len(ordered)}
    except Exception as exc:
        _metadata_failure(exc)
        return None


def _scope(root, receipt, bucket_fn):
    _validate(receipt)
    obj, run = receipt['object_id'], receipt['attempt_id']
    if obj not in OBJECTS or receipt['chain_id'] != 'ops_business':
        raise ValueError('not a NAV collection receipt')
    started = receipt['producer_time']['started_at']
    at = business.now()
    if not business.parsed(started) <= at <= business.parsed(started) + timedelta(hours=26):
        raise ValueError('expired/future collection')
    identity = receipt['consumer_witness']['fund_evidence']['publication_input']
    path = _input_path(root, obj, run)
    if not stat.S_ISDIR(path.parent.lstat().st_mode) or stat.S_IMODE(path.parent.stat().st_mode) != 0o700:
        raise ValueError('input directory is not private/regular')
    raw = _regular(path, MAX_INPUT_BYTES)
    if len(raw) != identity['size'] or hashlib.sha256(raw).hexdigest() != identity['sha256']:
        raise ValueError('committed scope hash mismatch')
    data = json.loads(raw)
    if (data['version'], data['object_id'], data['run'], data['started_at']) != (INPUT_VERSION, obj, run, started):
        raise ValueError('committed scope belongs to another run')
    rows = data['rows']
    if not rows or len(rows) > MAX_INPUT_ROWS or len(rows) != identity['rows']:
        raise ValueError('invalid scope denominator')
    by_bucket, seen = {}, set()
    for row in rows:
        code, day, unit, acc = row
        if normalized_row({'fund_code': code, 'date': day, 'unit_nav': unit, 'acc_nav': acc}) is None:
            raise ValueError('NULL input is not an exported row')
        key = (code, day)
        if key in seen:
            raise ValueError('duplicate scope row')
        seen.add(key)
        by_bucket.setdefault(bucket_fn(code), []).append(row)
    return {'receipt': receipt, 'identity': identity, 'buckets': by_bucket}


def _bucket_fn():
    return fund_bucket  # No importer of DB/business modules in the monitor.


def code_identity(fn, root):
    namespace = dict(fn.__globals__)
    namespace.update({'nav.'+k: v for k, v in globals().items() if inspect.isfunction(v)})
    namespace['nav.publication_index'] = business.write_publication_index
    return loaded_code_identity(types.FunctionType(fn.__code__, namespace), root)


def export_begin(root, producer=None):
    global _CACHE
    _CACHE = None
    if not evidence_enabled():
        return
    try:
        scopes = []
        for obj in OBJECTS:
            try:
                r = business.bounded_json(receipt_root(root) / 'index' / (obj+'.json'))
                scopes.append(_scope(root, r, _bucket_fn()))
            except (OSError, ValueError, KeyError, TypeError):
                continue
        _CACHE = {'root': str(Path(root).absolute()), 'scopes': scopes, 'work': 0.0,
                  'code': code_identity(producer, root) if producer is not None else {'sha': 'unknown'}}
    except Exception as exc:
        _metadata_failure(exc)
        _CACHE = {'root': str(Path(root).absolute()), 'scopes': [], 'work': _WORK_SECONDS, 'code': {'sha': 'unknown'}}


def _emit(root, scope, bucket, chain, output, witness, matched=True):
    r = scope['receipt']
    object_id = ('nav-export-' if chain == 'ops_nav_export' else 'nav-public-') + bucket + '.json'
    code = _CACHE['code'] if chain == 'ops_nav_export' and _CACHE is not None else code_identity(verify, root)
    if matched and chain == 'ops_nav_export':
        try:
            old = _indexed(root, r['attempt_id'], object_id)
            if (old['stage_status'] == 'success' and old['outputs'] == [output] and old['code_identity'] == code and
                    old['consumer_witness'].get('input_sha256') == scope['identity']['sha256'] and
                    old['consumer_witness'].get('local_file') == witness.get('local_file')):
                return  # Identical bytes/scope preserve an already verified generation.
        except (OSError, ValueError, KeyError, TypeError):
            pass
    result = emit_receipt(data_root=root, stage='publish', chain_id=chain, object_id=object_id,
        session_date=r['session_date'], attempt_id=r['attempt_id'], batch_id=r['attempt_id'],
        stage_status='success' if matched else 'unknown', reason='selected_NAV_bytes_verified' if matched else 'selected_NAV_mismatch', inputs=[dict(scope['identity'], object_id='committed_NAV_scope')],
        outputs=[output], counts={'expected': len(scope['buckets'][bucket]), 'validated': len(scope['buckets'][bucket]) if matched else 0},
        code_identity=code, evidence_quality='strong' if matched else 'unknown',
        consumer_witness=dict(witness, collection_object=r['object_id'], collection_started=r['producer_time']['started_at'],
                              input_sha256=scope['identity']['sha256'], remote_key='nav_bucket/'+bucket+'.json'))
    if result['status'] in ('written', 'idempotent'):
        p = receipt_root(root) / 'receipts' / r['session_date'] / chain / (result['receipt_id']+'.json')
        def still_current():
            if witness.get('local_file') != _current_file(root, bucket):
                raise ValueError('bucket generation changed before indexing')
            if chain == 'ops_nav_public' and _export_record(root, scope, bucket)['receipt_id'] != witness.get('export_receipt_id'):
                raise ValueError('export generation changed before indexing')
        business.write_publication_index(root, read_receipt(p), validate_current=still_current)


def export_bucket(root, path, bmap, raw, producer=None, file_token=None):
    """Observe only successful writes or the exact unchanged bytes actually read."""
    global _CACHE
    if not evidence_enabled():
        return
    began = time.monotonic()
    try:
        if _CACHE is None or _CACHE['root'] != str(Path(root).absolute()):
            export_begin(root, producer)
        if _CACHE['work'] >= _WORK_SECONDS:
            return
        bucket = Path(path).stem
        if not re.fullmatch('[a-f0-9]{2}', bucket) or len(raw) > MAX_BUCKET_BYTES:
            raise ValueError('unsupported NAV bucket')
        if (Path(path).absolute() != _bucket_path(root, bucket) or file_token is None or
                file_token != _current_file(root, bucket) or file_token['size'] != len(raw)):
            raise ValueError('export descriptor no longer names current canonical bucket')
        output = {'object_id': 'nav-bucket-'+bucket+'.json', 'sha256': hashlib.sha256(raw).hexdigest(),
                  'size': len(raw), 'identity_kind': 'exact_export_bytes'}
        for scope in _CACHE['scopes']:
            wanted = scope['buckets'].get(bucket)
            if not wanted:
                continue
            by_code = {}
            for code, day, unit, acc in wanted:
                by_code.setdefault(code, {})[day] = (unit, acc)
            good = True
            for code, days in by_code.items():
                payload = bmap.get(code, {})
                if payload.get('code') != code:
                    good = False; break
                remaining = dict(days)
                for row in reversed(payload.get('nav', [])):
                    if time.monotonic() - began + _CACHE['work'] > _WORK_SECONDS:
                        raise TimeoutError('NAV witness work budget')
                    if row[0] in remaining:
                        unit, acc = remaining.pop(row[0])
                        if row[1] != unit or (acc is not None and row[2] != acc):
                            good = False; break
                    if not remaining:
                        break
                if remaining or not good:
                    good = False; break
            _emit(root, scope, bucket, 'ops_nav_export', output,
                  {'scope': 'selected_committed_rows', 'public': False, 'local_file': file_token}, matched=good)
    except Exception as exc:
        _metadata_failure(exc)
    finally:
        if _CACHE is not None:
            _CACHE['work'] += time.monotonic() - began


def _indexed(root, run, name):
    p = receipt_root(root) / 'publication' / hashlib.sha256(run.encode()).hexdigest() / name
    r = business.bounded_json(p)
    _validate(r)
    return r


def _export_record(root, scope, bucket):
    r = scope['receipt']; run = r['attempt_id']
    e = _indexed(root, run, 'nav-export-'+bucket+'.json')
    w = e['consumer_witness']
    if (e['chain_id'] != 'ops_nav_export' or e['object_id'] != 'nav-export-'+bucket+'.json' or e['attempt_id'] != run or e['stage_status'] != 'success' or
        e['code_identity'].get('sha') != r['code_identity'].get('sha') or
        not re.fullmatch('[a-f0-9]{40}', e['code_identity'].get('sha', '')) or
        w.get('input_sha256') != scope['identity']['sha256'] or w.get('collection_object') != r['object_id'] or
        w.get('collection_started') != r['producer_time']['started_at'] or w.get('remote_key') != 'nav_bucket/'+bucket+'.json' or
        e['counts'] != {'expected': len(scope['buckets'][bucket]), 'validated': len(scope['buckets'][bucket])} or
        len(e['outputs']) != 1 or business.parsed(e['evaluated_at']) < business.parsed(r['producer_time']['started_at'])):
        raise ValueError('export witness not bound to current scope')
    o = e['outputs'][0]
    if o.get('object_id') != 'nav-bucket-'+bucket+'.json' or not re.fullmatch('[a-f0-9]{64}', o.get('sha256', '')) or type(o.get('size')) is not int or not 0 < o['size'] <= MAX_BUCKET_BYTES:
        raise ValueError('invalid export bytes')
    if w.get('local_file') != _current_file(root, bucket):
        raise ValueError('local export was replaced or changed without this witness')
    return e


def _confirmed(root, scope, bucket, export):
    try:
        p = _indexed(root, scope['receipt']['attempt_id'], 'nav-public-'+bucket+'.json')
        w = p['consumer_witness']
        return (p['chain_id'] == 'ops_nav_public' and p['object_id'] == 'nav-public-'+bucket+'.json' and p['stage_status'] == 'success' and
                p['code_identity'].get('sha') == export['code_identity'].get('sha') and
                p['attempt_id'] == scope['receipt']['attempt_id'] and p['outputs'] == export['outputs'] and
                w.get('export_receipt_id') == export['receipt_id'] and
                w.get('input_sha256') == scope['identity']['sha256'] and
                w.get('collection_object') == scope['receipt']['object_id'] and
                w.get('collection_started') == scope['receipt']['producer_time']['started_at'] and
                w.get('remote_key') == 'nav_bucket/'+bucket+'.json' and p['counts'] == export['counts'] and
                w.get('local_file') == export['consumer_witness'].get('local_file') == _current_file(root, bucket) and
                w.get('public_url') == PUBLIC_BASE+bucket+'.json' and
                business.parsed(p['evaluated_at']) >= business.parsed(export['evaluated_at']))
    except (OSError, ValueError, KeyError, TypeError):
        return False


def inspect_scope(root, receipt, seconds=1.0):
    result = {'state': 'unknown', 'scope': 'selected_committed_rows', 'expected_buckets': 0,
              'exported_buckets': 0, 'public_buckets': 0, 'whole_pool_verified': False}
    deadline = time.monotonic() + seconds
    try:
        scope = _scope(root, receipt, _bucket_fn())
        result['expected_buckets'] = len(scope['buckets'])
        for b in scope['buckets']:
            if time.monotonic() >= deadline:
                result['reason'] = 'inspection_budget'; return result
            try:
                e = _export_record(root, scope, b)
                result['exported_buckets'] += 1
                result['public_buckets'] += int(_confirmed(root, scope, b, e))
            except (OSError, ValueError, KeyError, TypeError):
                continue
        result['state'] = 'scoped_confirmed' if result['public_buckets'] == result['expected_buckets'] else 'partial' if result['public_buckets'] else 'unknown'
    except (OSError, ValueError, KeyError, TypeError):
        result['reason'] = 'input_or_witness_unverified'
    return result


def _fetch_public(bucket, expected_size, deadline):
    import ssl
    import urllib.request
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    context = ssl.create_default_context()
    opener = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPSHandler(context=context))
    req = urllib.request.Request(PUBLIC_BASE+bucket+'.json', headers={'Accept-Encoding': 'identity'})
    with opener.open(req, timeout=max(.1, min(5, deadline-time.monotonic()))) as response:
        if response.status != 200 or response.headers.get('Content-Encoding', 'identity') != 'identity':
            raise ValueError('public NAV response unavailable/encoded')
        body = bytearray()
        while len(body) <= expected_size:
            if time.monotonic() >= deadline:
                raise TimeoutError('public readback deadline')
            # read(n) can keep waiting across a slow trickle until n is filled.
            # read1 makes at most one raw read, allowing the deadline to be rechecked.
            chunk = response.read1(min(65536, expected_size+1-len(body)))
            if not chunk: break
            body.extend(chunk)
        return bytes(body)


def verify(root, *, seconds=60, max_bytes=64*1024*1024, fetch=_fetch_public):
    """Explicit GET only; no upload, purge, source refresh or success from rc0."""
    if not evidence_enabled():
        return {'status': 'disabled', 'attempted': 0}
    deadline = time.monotonic()+seconds
    report = {'status': 'unknown', 'attempted': 0, 'confirmed': 0, 'reserved_bytes': 0, 'unverified': 0}
    for obj in OBJECTS:
        if time.monotonic() >= deadline:
            report['budget_exhausted'] = True; return report
        try:
            r = business.bounded_json(receipt_root(root)/'index'/(obj+'.json'))
            scope = _scope(root, r, _bucket_fn())
        except (OSError, ValueError, KeyError, TypeError):
            continue
        for bucket in sorted(scope['buckets']):
            if time.monotonic() >= deadline:
                report['budget_exhausted'] = True; return report
            try:
                e = _export_record(root, scope, bucket)
                if _confirmed(root, scope, bucket, e): continue
                o = e['outputs'][0]
                charge = o['size'] + 1
                if time.monotonic() >= deadline or report['reserved_bytes']+charge > max_bytes:
                    report['budget_exhausted'] = True; return report
                report['attempted'] += 1
                # Charge the full request before starting, including failed reads.
                report['reserved_bytes'] += charge
                raw = fetch(bucket, o['size'], deadline)
                if time.monotonic() >= deadline:
                    raise TimeoutError('public readback completed after deadline')
                if len(raw) != o['size'] or hashlib.sha256(raw).hexdigest() != o['sha256']:
                    raise ValueError('public bytes differ from scoped export')
                if _export_record(root, scope, bucket)['receipt_id'] != e['receipt_id']:
                    raise ValueError('export changed during public readback')
                _emit(root, scope, bucket, 'ops_nav_public', o,
                      {'scope': 'selected_committed_rows', 'public_url': PUBLIC_BASE+bucket+'.json',
                       'local_file': e['consumer_witness']['local_file'],
                       'export_receipt_id': e['receipt_id']})
                confirmed = _confirmed(root, scope, bucket, e)
                report['confirmed'] += int(confirmed)
                report['unverified'] += int(not confirmed)
            except Exception:
                report['unverified'] += 1
    # This is an operation report; inspect_scope is the per-collection conclusion.
    report['status'] = 'checked'
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('inspect', 'verify'))
    p.add_argument('--root', required=True)
    p.add_argument('--seconds', type=float, default=60)
    p.add_argument('--max-bytes', type=int, default=64*1024*1024)
    a = p.parse_args()
    if not Path(a.root).is_absolute() or not 0 < a.seconds <= 300 or not 0 < a.max_bytes <= 1024*1024*1024:
        p.error('absolute root and bounded positive budgets required')
    if a.action == 'verify':
        # CLI runs on the project's Unix hosts. A process alarm also covers DNS
        # lookup, which urllib's per-socket timeout cannot bound. Library callers
        # remain responsible for their execution deadline.
        import signal
        def expired(*unused):
            raise TimeoutError('NAV readback process deadline')
        previous = signal.signal(signal.SIGALRM, expired)
        signal.setitimer(signal.ITIMER_REAL, a.seconds)
        try:
            result = verify(a.root, seconds=a.seconds, max_bytes=a.max_bytes)
        except TimeoutError:
            result = {'status': 'unknown', 'budget_exhausted': True}
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous)
    else:
        result = {}
        for obj in OBJECTS:
            try:
                r = business.bounded_json(receipt_root(a.root)/'index'/(obj+'.json'))
                result[obj] = inspect_scope(a.root, r)
            except (OSError, ValueError):
                result[obj] = {'state': 'unknown'}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
