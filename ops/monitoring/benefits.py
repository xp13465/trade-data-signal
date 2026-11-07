#!/usr/bin/env python3
"""Bounded, offline delivery normalization. Only fixed evidence sources are opened.

No producer/business imports, environment reads, network, notifications or commands.
Control attestations remain an operator trust boundary; digests are not signatures.
"""
from __future__ import annotations
import argparse
from contextlib import contextmanager
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys
import time

CHAINS = {
    'market_signal_freeze_plan': ('signal', 'freeze', 'plan'),
    'backtest_publish_consume': ('backtest', 'publish', 'consumer'),
    'backup_isolated_restore': ('backup', 'restore'),
}
CONTROL = 'data/ops_delivery/benefits-control.json'
RECEIPTS = 'data/ops_delivery/receipts'
SOURCES = ('data/alerts/alert_ledger.jsonl', 'static-site/data/schedule_stats.json')
KEYS = ('record_kind', 'contract_id', 'chain_id', 'session_date', 'batch_id',
        'measurement_kind', 'deadline_at', 'expected', 'success', 'failure', 'unknown',
        'code_sha', 'config_sha', 'calendar_sha', 'proof_sha', 'evaluated_at',
        'inventory_complete', 'reason', 'strength', 'source_at')
MAX_FILE = 64 * 1024
MAX_RECEIPTS = 128
MAX_TOTAL = 2 * 1024 * 1024
SAFE = re.compile(r'[A-Za-z0-9:._-]{1,160}\Z')


class EvidenceError(ValueError):
    pass


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(obj):
    return hashlib.sha256(canonical(obj)).hexdigest()


def is_sha(value, length=64):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{%d}' % length, value) is not None


def stamp(value):
    if not isinstance(value, str):
        raise EvidenceError('time')
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.utcoffset() is None:
        raise EvidenceError('time')
    return dt


def day(value):
    return isinstance(value, str) and date.fromisoformat(value).isoformat() == value


def safe(value):
    return isinstance(value, str) and SAFE.fullmatch(value) is not None


def parse(raw):
    def pairs(items):
        obj = {}
        for k, v in items:
            if k in obj:
                raise EvidenceError('duplicate')
            obj[k] = v
        return obj
    def bad(_):
        raise EvidenceError('nonfinite')
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=bad)


class Reader:
    def __init__(self, root, seconds=1.5, clock=time.monotonic):
        self.root = Path(root)
        self.clock, self.deadline = clock, clock() + seconds
        self.bytes = 0
        self.entries = 0

    def remaining(self):
        if self.clock() >= self.deadline:
            raise EvidenceError('budget')

    @contextmanager
    def directory(self, relative):
        """Pin each directory with openat/O_NOFOLLOW; reject symlink parents too."""
        self.remaining()
        root = self.root.absolute()
        fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
        try:
            for part in (*root.parts[1:], *Path(relative).parts):
                if part in ('', '.', '..'):
                    raise EvidenceError('directory')
                new = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = new
                self.remaining()
            yield fd
        finally:
            os.close(fd)

    def read_at(self, directory, filename, cap=MAX_FILE):
        self.remaining()
        fd = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(fd, 'rb') as f:
            before = os.fstat(f.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > cap:
                raise EvidenceError('size')
            raw = f.read(cap + 1)
            after = os.fstat(f.fileno())
        self.bytes += len(raw)
        self.remaining()
        if (len(raw) > cap or self.bytes > MAX_TOTAL or
                (before.st_ino, before.st_size, before.st_mtime_ns) !=
                (after.st_ino, after.st_size, after.st_mtime_ns)):
            raise EvidenceError('changed_or_limit')
        return raw

    def read(self, relative, cap=MAX_FILE):
        path = Path(relative)
        with self.directory(str(path.parent)) as fd:
            return self.read_at(fd, path.name, cap)

    def receipts(self, session, chain):
        if not day(session) or chain not in CHAINS:
            raise EvidenceError('partition')
        result = []
        with self.directory(RECEIPTS + '/' + session + '/' + chain) as fd:
            with os.scandir(fd) as entries:
                for n, entry in enumerate(entries):
                    self.remaining()
                    self.entries += 1
                    if n >= MAX_RECEIPTS or self.entries > 256:
                        raise EvidenceError('receipt_limit')
                    if entry.name.startswith('.receipt-'):
                        continue  # unpublished producer temporary file, never a fact
                    if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,199}\.json', entry.name):
                        raise EvidenceError('unexpected_partition_entry')
                    raw = self.read_at(fd, entry.name)
                    obj = parse(raw)
                    if (not isinstance(obj, dict) or entry.name != obj.get('receipt_id', '') + '.json'
                            or obj.get('session_date') != session or obj.get('chain_id') != chain):
                        raise EvidenceError('receipt_shape')
                    result.append((hashlib.sha256(raw).hexdigest(), obj))
        return sorted(result, key=lambda r: r[0])


def validate_control(c):
    if not isinstance(c, dict) or c.get('schema_version') != 'benefits-control-v1':
        raise EvidenceError('control')
    if c.get('measurement_kind') not in ('real', 'synthetic'):
        raise EvidenceError('measurement_kind')
    # Disabled/unreviewed configuration is observable, never a green inventory.
    if c.get('policy', {}).get('reviewed') is not True or not is_sha(c['policy'].get('approval_sha256')):
        raise EvidenceError('policy_unreviewed')
    stamp(c['policy']['approved_at'])
    cal = c.get('calendar', {})
    dates = cal.get('trading_days')
    if (cal.get('verified_complete') is not True or cal.get('timezone') != 'Asia/Shanghai'
            or not isinstance(dates, list) or len(dates) > 4096
            or not all(day(d) for d in dates) or dates != sorted(set(dates))
            or not isinstance(cal.get('source_ref'), str) or not cal['source_ref']
            or cal.get('sha256') != hashlib.sha256(json.dumps(dates, separators=(',', ':')).encode()).hexdigest()):
        raise EvidenceError('calendar_unverified')
    for k in ('contract_id', 'caliber_id', 'population_id', 'schedule_id', 'exclusion_policy_id'):
        if not safe(c.get(k)):
            raise EvidenceError('control_identity')
    if not is_sha(c.get('normalizer_sha'), 40):
        raise EvidenceError('normalizer_identity')
    sessions = c.get('sessions')
    if not isinstance(sessions, list) or len(sessions) > 64:
        raise EvidenceError('sessions')
    if len({s['date'] for s in sessions}) != len(sessions):
        raise EvidenceError('duplicate_session')
    for s in sessions:
        if s['date'] not in dates or not isinstance(s.get('chains'), dict) or set(s['chains']) - set(CHAINS):
            raise EvidenceError('session_calendar')
    return c


def inventory(c, chain, session, now):
    s = next(s for s in c['sessions'] if s['date'] == session)
    p = s['chains'].get(chain, {})
    if p.get('inventory_complete') is not True or not safe(p.get('inventory_id')):
        raise EvidenceError('inventory_missing')
    if stamp(c['policy']['approved_at']) >= stamp(p['deadline_at']):
        raise EvidenceError('policy_not_predeclared')
    from zoneinfo import ZoneInfo
    if stamp(p['deadline_at']).astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat() < session:
        raise EvidenceError('deadline_precedes_session')
    if stamp(p['deadline_at']) > now:
        raise EvidenceError('window_open')
    if not is_sha(p.get('code_sha'), 40) or not is_sha(p.get('config_sha')):
        raise EvidenceError('version_unknown')
    batches = p.get('batches')
    if not isinstance(batches, list) or len(batches) > 32 or len(set(batches)) != len(batches) or not all(safe(b) for b in batches):
        raise EvidenceError('required_batches')
    required = p.get('required')
    if not isinstance(required, list) or not required or len(required) > 16:
        raise EvidenceError('required_set')
    if set(r['stage'] for r in required) != set(CHAINS[chain]):
        raise EvidenceError('required_stages')
    order = [CHAINS[chain].index(r['stage']) for r in required]
    if order != sorted(order):
        raise EvidenceError('stage_order')
    if any(not is_sha(r.get('code_sha', p['code_sha']), 40) or not is_sha(r.get('config_sha', p['config_sha'])) for r in required):
        raise EvidenceError('stage_version_unknown')
    nodes = [(r['stage'], r['object_id']) for r in required]
    if len(nodes) != len(set(nodes)) or any(not safe(r['object_id']) for r in required):
        raise EvidenceError('required_identity')
    edges = p.get('edges', [])
    if not isinstance(edges, list) or len(edges) > 32:
        raise EvidenceError('edges')
    # All later nodes need an explicit upstream edge; no day-only stitching.
    covered = set()
    for e in edges:
        src, dest = tuple(e['from']), tuple(e['to'])
        if src not in nodes or dest not in nodes or nodes.index(src) >= nodes.index(dest) or not safe(e['object_id']):
            raise EvidenceError('edge_identity')
        covered.add(dest)
    if set(nodes[1:]) - covered:
        raise EvidenceError('edge_missing')
    if not safe(required[-1].get('consumer_scope')):
        raise EvidenceError('consumer_scope_missing')
    return p


def identities(r, kind, required_ids):
    rows = r.get(kind)
    if not isinstance(rows, list) or len(rows) > 64:
        return None
    good = {}
    for v in rows:
        if (not isinstance(v, dict) or v.get('quality') != 'strong'
                or v.get('session_date') != r['session_date'] or not is_sha(v.get('sha256'))):
            continue
        if v.get('object_id') in good:
            return None
        try:
            if stamp(v.get('observed_at')) > stamp(r['producer_time']['completed_at']):
                continue
        except (KeyError, TypeError, ValueError):
            continue
        good[v.get('object_id')] = v['sha256']
    return good if all(k in good for k in required_ids) else None


def strong(r, requirement, p, now):
    try:
        if (r.get('schema') != 'trade-delivery-receipt-v1' and r.get('schema_version') != 'trade-delivery-receipt-v1'):
            return False
        if (not safe(r.get('receipt_id')) or not safe(r.get('attempt_id'))
                or r.get('evidence_quality') != 'strong' or r.get('stage_status') not in ('success', 'failure')
                or r.get('code_identity', {}).get('sha') != requirement.get('code_sha', p['code_sha'])
                or r.get('config_identity', {}).get('sha256') != requirement.get('config_sha', p['config_sha'])):
            return False
        t = stamp(r['evaluated_at'])
        completed = stamp(r.get('producer_time', {}).get('completed_at'))
        from zoneinfo import ZoneInfo
        if (completed > t or t > now
                or completed.astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat() < r['session_date']):
            return False
        counts = r.get('counts', {})
        # These are actual business validation predicates, never rc/process totals.
        if (not isinstance(counts, dict) or (type(counts.get('inventory_complete')) is not int or counts['inventory_complete'] != 1)
                or not all(type(counts.get(k)) is int and counts[k] >= 0 for k in ('expected', 'validated', 'failed', 'unknown'))
                or counts['expected'] != counts['validated'] + counts['failed'] + counts['unknown']):
            return False
        for kind in ('inputs', 'outputs'):
            ids = requirement.get(kind)
            if not isinstance(ids, list) or not ids or not all(safe(v) for v in ids) or identities(r, kind, ids) is None:
                return False
        if r['stage_status'] == 'failure':
            return counts['failed'] > 0
        return counts['failed'] == counts['unknown'] == 0 and (counts['expected'] > 0 or requirement.get('allow_empty') is True)
    except (KeyError, TypeError, ValueError):
        return False


def batch_outcome(receipts, p, batch, chain, session, now):
    selected, missing = [], False
    for req in p['required']:
        candidates = [r for _, r in receipts if r.get('chain_id') == chain and r.get('session_date') == session
                      and r.get('batch_id') == batch and r.get('stage') == req['stage']
                      and r.get('object_id') == req['object_id'] and strong(r, req, p, now)]
        # Repeated identical receipt_ids collapse; conflicting ids cannot be resolved by filename/mtime.
        unique = {digest(r): r for r in candidates}
        if len(unique) > 1:
            return 'unknown', 'receipt_missing_or_ambiguous', []
        if not unique:
            missing = True
        else:
            selected.append(next(iter(unique.values())))
    # Explicit stage failure may be proven, but it is not a chain failure if a later attempt succeeded.
    # Ambiguous attempts above deliberately keep outcome unknown.
    if any(r['stage_status'] == 'failure' for r in selected):
        return 'failure', 'verified_failure', selected
    if missing:
        return 'unknown', 'receipt_missing_or_ambiguous', selected
    by_node = {(r['stage'], r['object_id']): r for r in selected}
    for edge in p['edges']:
        a, b = by_node[tuple(edge['from'])], by_node[tuple(edge['to'])]
        key = edge['object_id']
        av, bv = identities(a, 'outputs', [key]), identities(b, 'inputs', [key])
        if not av or not bv or av[key] != bv[key] or stamp(a['producer_time']['completed_at']) > stamp(b['producer_time']['completed_at']):
            return 'unknown', 'lineage_unverified', selected
    last = selected[-1]
    witness = last.get('consumer_witness', {})
    outs = identities(last, 'outputs', p['required'][-1]['outputs'])
    if (not isinstance(witness, dict) or witness.get('status') != 'success'
            or witness.get('consumer_scope') != p['required'][-1]['consumer_scope']
            or witness.get('batch_id') != batch or witness.get('session_date') != session
            or witness.get('output_sha256') not in outs.values()):
        return 'unknown', 'consumer_unverified', selected
    # Use actual receipt validation time, never current mutable artifact hashes.
    if max(stamp(r['producer_time']['completed_at']) for r in selected) > stamp(p['deadline_at']):
        return 'failure', 'verified_stale', selected
    return 'success', 'verified_delivery', selected


def control_identity(c, chain, session):
    core = {k: v for k, v in c.items() if k != 'sessions'}
    slots = [s.get('chains', {}).get(chain) for s in c.get('sessions', []) if s.get('date') == session]
    return digest({'control': core, 'chain': chain, 'session': session, 'inventory': slots})


def normalize(c, receipts, chain, session, now, source_complete=True):
    e = dict.fromkeys(KEYS)
    e.update(record_kind='delivery_v1', contract_id=c.get('contract_id', 'unconfigured'), chain_id=chain,
             session_date=session, batch_id=chain + ':' + session, measurement_kind=c.get('measurement_kind', 'unknown'), evaluated_at=now.isoformat().replace('+00:00', 'Z'),
             inventory_complete=False, reason='inventory_missing', strength='unknown')
    local = {'schema_version': 'benefit-observation-v1', 'measurement_kind': c.get('measurement_kind', 'unknown'),
             'evidence': e, 'receipt_proofs': [], 'source_receipts': [h for h, r in receipts if r.get('chain_id') == chain and r.get('session_date') == session], 'control_sha256': control_identity(c, chain, session), 'real_benefit_claim': False}
    try:
        validate_control(c)
        p = inventory(c, chain, session, now)
        if not source_complete:
            raise EvidenceError('source_incomplete')
        e.update(deadline_at=p['deadline_at'], code_sha=p['code_sha'], config_sha=p['config_sha'],
                 calendar_sha=c['calendar']['sha256'], expected=len(p['batches']), success=0, failure=0,
                 unknown=0, inventory_complete=True)
        outcomes, attempts = [], set()
        for batch in p['batches']:
            outcome, reason, used = batch_outcome(receipts, p, batch, chain, session, now) if source_complete else ('unknown', 'source_incomplete', [])
            e[outcome] += 1
            outcomes.append({'batch_id': batch, 'outcome': outcome, 'reason': reason})
            local['receipt_proofs'].extend(used)
            attempts.update(r['attempt_id'] for r in used)
        local['attempt_ids'] = sorted(attempts)
        # Wire batch_id denotes aggregate slot; detailed multi-batch IDs stay local.
        local.update(outcomes=outcomes, inventory_ref=p['inventory_id'])
        if e['unknown']:
            e.update(reason='evidence_incomplete', strength='partial' if e['success'] + e['failure'] else 'unknown')
        elif e['expected']:
            e['source_at'] = max(stamp(r['producer_time']['completed_at']) for r in local['receipt_proofs']).isoformat().replace('+00:00', 'Z')
            e.update(reason='verified_failure' if e['failure'] else 'verified_delivery', strength='verified')
        else:
            e.update(reason='empty_inventory', strength='unknown')
    except (KeyError, TypeError, ValueError, StopIteration, AttributeError):
        e.update(expected=None, success=None, failure=None, unknown=None,
                 inventory_complete=False, strength='unknown', source_at=None)
    local['source_receipts'] = sorted(set(local['source_receipts']))
    e['proof_sha'] = digest({k: v for k, v in local.items() if k != 'evidence'} | {'result': {k: v for k, v in e.items() if k not in ('evaluated_at', 'proof_sha')}})
    return local


def observations(reader):
    result = []
    for path in SOURCES:
        try:
            raw = reader.read(path)
            # Operational observations only; never delivery denominator or success.
            item = {'source_kind': 'notification_ledger' if path.endswith('jsonl') else 'run_summary',
                    'state': 'observed', 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}
            if path.endswith('jsonl'):
                item['records'] = sum(bool(line.strip()) for line in raw.splitlines())
            else:
                parsed = parse(raw)
                item['records'] = len(parsed) if isinstance(parsed, list) else None
            result.append(item)
        except (OSError, ValueError, RecursionError):
            result.append({'source_kind': 'notification_ledger' if path.endswith('jsonl') else 'run_summary', 'state': 'unknown'})
    return result


def sample(data_root, now=None, seconds=1.5, history=False, session_date=None):
    from zoneinfo import ZoneInfo
    now = now or datetime.now(timezone.utc)
    r = Reader(data_root, seconds)
    try:
        c = validate_control(parse(r.read(CONTROL)))
        dates = sorted(s['date'] for s in c['sessions'] if s['date'] <= now.astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat())
        dates = dates if history else dates[-2:]
        if session_date is not None:
            dates = [d for d in dates if d == session_date]
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RecursionError):
        c, dates = {}, []
    ops = observations(r)
    records, complete = [], True
    for session in dates:
        for chain in CHAINS:
            try:
                receipts, slot_complete = r.receipts(session, chain), True
            except (OSError, ValueError, RecursionError):
                receipts, slot_complete = [], False
            complete = complete and slot_complete
            records.append(normalize(c, receipts, chain, session, now, slot_complete))
    return {'schema_version': 'benefit-sample-v1', 'evaluated_at': now.isoformat().replace('+00:00', 'Z'),
            'status': 'observed' if records else 'not_ready', 'reason': 'sampled' if records else 'control_unconfigured',
            'control': c, 'observations': ops, 'records': records, 'source_complete': complete,
            'real_benefit_claim': False, 'history_import': history}


def wire(record):
    e = dict(record['evidence'])
    # Preserve the measurement boundary in the existing 20-field transport.
    # Diagnostic synthetic records never become real business measurements.
    kind = record.get('measurement_kind')
    if kind not in ('real', 'synthetic') or e.get('measurement_kind') != kind:
        kind = 'unknown'
    e['measurement_kind'] = kind
    real = kind == 'real'
    status = 'unknown'
    if real and e['strength'] == 'verified' and e['inventory_complete'] and e['expected']:
        status = 'warning' if e['failure'] else 'ok'
    return {'id': 'benefit:' + e['chain_id'] + ':' + e['session_date'],
            'name': 'Delivery validation', 'category': 'monitor', 'status': status,
            'observed_at': e['evaluated_at'], 'summary': 'Validated delivery evidence; descriptive outcomes only', 'evidence': e}


def persist(output_dir, result):
    """Local private immutable proof versions; duplicate sampling does not grow rows.

    A transaction protects concurrent samplers. Unavailability of persistence fails
    closed at the collector integration; it never turns a missing source green.
    """
    root = Path(output_dir)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Pin output directory, disallow symlink ancestors and sqlite auxiliary-file attacks.
    with Reader(root).directory('') as fd:
        s = os.fstat(fd)
        if s.st_uid != os.geteuid() or stat.S_IMODE(s.st_mode) & 0o077:
            raise EvidenceError('private_output')
        for name in ('benefits.sqlite3', 'benefits.sqlite3-journal', 'benefits.sqlite3-wal', 'benefits.sqlite3-shm'):
            try:
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError:
                continue
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600:
                raise EvidenceError('private_store')
        dbfile = root / 'benefits.sqlite3'
        newfd = os.open('benefits.sqlite3', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600, dir_fd=fd)
        os.close(newfd)
        conn = sqlite3.connect(dbfile, timeout=0.05)
        try:
            conn.execute('PRAGMA busy_timeout=50')
            conn.execute('CREATE TABLE IF NOT EXISTS observations (chain TEXT, session TEXT, proof TEXT, payload TEXT NOT NULL, PRIMARY KEY(chain,session,proof))')
            conn.execute('CREATE TABLE IF NOT EXISTS samples (proof TEXT PRIMARY KEY, payload TEXT NOT NULL, first_seen TEXT, last_seen TEXT)')
            with conn:
                metadata = {k: v for k, v in result.items() if k not in ('records', 'evaluated_at')}
                conn.execute('INSERT INTO samples VALUES (?,?,?,?) ON CONFLICT(proof) DO UPDATE SET last_seen=excluded.last_seen',
                             (digest(metadata), canonical(metadata).decode(), result.get('evaluated_at'), result.get('evaluated_at')))
                for record in result['records']:
                    e = record['evidence']
                    conn.execute('INSERT OR IGNORE INTO observations VALUES (?,?,?,?)',
                                 (e['chain_id'], e['session_date'], e['proof_sha'], canonical(record).decode()))
        finally:
            conn.close()


def export_periods(control, records, chain, as_of):
    """Export one population into the preserved 10/10 comparator schema.

    No observation is retrodated into an ops snapshot. Missing historical proof is
    unknown. Conflicting validated versions remain unknown, never last-row-wins.
    """
    from zoneinfo import ZoneInfo
    rollout = control.get('rollout', {})
    try:
        anchor = stamp(rollout['effective_at']).astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat()
    except (KeyError, ValueError, TypeError):
        anchor = None
    dates = control.get('calendar', {}).get('trading_days', [])
    result = {}
    for label in ('before', 'after'):
        wanted = ([d for d in dates if anchor and d < anchor][-10:] if label == 'before' else [d for d in dates if anchor and d > anchor][:10])
        p = {k: control.get(k) for k in ('contract_id', 'caliber_id', 'population_id', 'schedule_id', 'exclusion_policy_id', 'normalizer_sha', 'calendar', 'rollout', 'measurement_kind')}
        p['population_id'] = str(control.get('population_id')) + ':' + chain
        p.update(schema_version='delivery-benefits-v1', metric_id='chain_delivery_success',
                 code_sha=rollout.get(label + '_code_sha'), config_sha256=rollout.get(label + '_config_sha256'),
                 as_of=as_of, confounders=control.get('confounders', []), manual_work=None, days=[])
        for d in wanted:
            rows = [r for r in records if r['evidence']['chain_id'] == chain and r['evidence']['session_date'] == d
                    and r.get('control_sha256') == control_identity(control, chain, d) and stamp(r['evidence']['evaluated_at']) <= stamp(as_of)]
            unique = {r['evidence']['proof_sha']: r for r in rows if r['evidence']['strength'] == 'verified'}
            conflicting_partial_failure = bool(unique) and any(
                r['evidence']['strength'] == 'partial' and (r['evidence'].get('failure') or 0) > 0
                for r in rows)
            r = (next(iter(unique.values())) if len(unique) == 1 else (rows[0] if len(rows) == 1 else None))
            if conflicting_partial_failure:
                r = None  # known failure cannot be hidden behind earlier full success
            e = r['evidence'] if r else {}
            p['days'].append({'date': d, 'deadline_at': e.get('deadline_at'), 'closed': bool(e.get('deadline_at') and stamp(e['deadline_at']) <= stamp(as_of)),
                              'code_sha': e.get('code_sha'), 'caliber_id': p['caliber_id'], 'inventory_complete': e.get('inventory_complete', False),
                              'inventory_ref': r.get('inventory_ref') if r else None, 'outcome_ref': e.get('proof_sha'), 'scheduled': e.get('expected'),
                              'excluded': [], 'success': e.get('success'), 'failure': e.get('failure'), 'unknown': e.get('unknown')})
        result[label] = p
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('sample', 'import-history'):
        p = sub.add_parser(name)
        p.add_argument('--data-root', required=True)
        p.add_argument('--output-dir', required=True)
        p.add_argument('--session-date', help='Explicit historical partition; does not alter ops snapshot time')
    p = sub.add_parser('export')
    p.add_argument('--data-root', required=True)
    p.add_argument('--output-dir', required=True)
    p.add_argument('--chain', choices=CHAINS, required=True)
    p.add_argument('--as-of', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'export':
            control = validate_control(parse(Reader(args.data_root).read(CONTROL)))
            from urllib.parse import quote
            from zoneinfo import ZoneInfo
            anchor = stamp(control['rollout']['effective_at']).astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat()
            dates = control['calendar']['trading_days']
            wanted = [d for d in dates if d < anchor][-10:] + [d for d in dates if d > anchor][:10]
            # Query only the explicit study population, not the lifetime DB file.
            # Index (chain,session,proof) bounds lookup; never truncate versions and
            # pretend a complete population. Too many versions is not_ready.
            with Reader(args.output_dir).directory('') as directory:
                info = os.stat('benefits.sqlite3', dir_fd=directory, follow_symlinks=False)
                if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
                    raise EvidenceError('private_store')
                uri = 'file:' + quote(str(Path(args.output_dir).absolute() / 'benefits.sqlite3'), safe='/') + '?mode=ro'
                con = sqlite3.connect(uri, uri=True, timeout=0.05)
                try:
                    stop = time.monotonic() + 2
                    con.set_progress_handler(lambda: int(time.monotonic() > stop), 1000)
                    sql = 'SELECT payload FROM observations WHERE chain=? AND session IN (' + ','.join('?' for _ in wanted) + ') LIMIT 321'
                    rows = con.execute(sql, (args.chain, *wanted)).fetchall()
                    if len(rows) > 320 or sum(len(row[0]) for row in rows) > 32 * 1024 * 1024:
                        raise EvidenceError('export_limit')
                    records = [parse(row[0]) for row in rows]
                finally:
                    con.close()
            result = export_periods(control, records, args.chain, args.as_of)
        else:
            result = sample(args.data_root, history=args.command == 'import-history', session_date=args.session_date)
            persist(args.output_dir, result)
        print(json.dumps(result, allow_nan=False))
        return 2 if result.get('status') == 'not_ready' else 0
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error, AttributeError, RecursionError):
        print(json.dumps({'status': 'not_ready', 'reason': 'evidence_unavailable', 'real_benefit_claim': False}))
        return 2


if __name__ == '__main__':
    sys.exit(main())
