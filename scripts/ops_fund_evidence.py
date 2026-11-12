"""Current-run NAV facts from producer memory; no DB, network or new SLA.

A committed UPSERT proves statement completion, not a full DB snapshot or public
NAV delivery. FOF ranges/cursor are attempts, and legal empty says nothing about
which day a source is obliged to publish. Publication stays explicitly unknown:
public_fund summary R2 proofs do not bind the NAV buckets to these collected rows.
"""
from __future__ import annotations

import argparse
import contextvars
import functools
import hashlib
import inspect
import os
import time
import types
import uuid

try:
    from . import ops_business_evidence as business
    from .delivery_evidence import (evidence_enabled, _canonical, _metadata_failure,
                                    receipt_root, loaded_code_identity, _validate)
except ImportError:  # direct scripts/ops_monitor.py / offline acceptance entry
    import ops_business_evidence as business
    from delivery_evidence import (evidence_enabled, _canonical, _metadata_failure,
                                   receipt_root, loaded_code_identity, _validate)

VERSION = 'fund-collection-v1'
_ACTIVE = contextvars.ContextVar('fund_collection', default=None)
MAX_WORK_SECONDS = 0.5  # total in-memory observation work, not an added I/O timeout


def assessment(receipt, root=None):
    """Report selected publication separately; never infer whole-pool health."""
    facts = receipt['consumer_witness'].get('fund_evidence')
    if not isinstance(facts, dict) or facts.get('version') != VERSION:
        return 'unknown', 'fund_collection_receipt_missing', {}
    if facts.get('metadata_failed'):
        return 'unknown', 'fund_metadata_incomplete', facts
    if facts.get('collection_status') == 'failure':
        return 'warning', 'fund_collection_failed', facts
    if root is not None:
        try:
            from .ops_nav_publication import inspect_scope
        except ImportError:
            from ops_nav_publication import inspect_scope
        facts = dict(facts, publication_check=inspect_scope(root, receipt))
        # Stage facts only: no source completeness/SLA/whole-pool health inferred.
        state = facts['publication_check']['state']
        return 'unknown', ('fund_publication_unverified' if state == 'unknown' else 'fund_scope_publication_'+state), facts
    return 'unknown', 'fund_publication_unverified', facts


class Round:
    def __init__(self, root, object_id, code=None):
        self.root, self.object_id = root, object_id
        self.code = code or {'sha': 'unknown'}
        # Only daily's shell is allowed to supply a parent identity. FOF calls
        # within one Python process must each retain their own invocation facts.
        self.run = (os.environ.get('OPS_FUND_RUN') if object_id == 'public-fund' else None) or uuid.uuid4().hex
        self.started = (os.environ.get('OPS_FUND_STARTED') if object_id == 'public-fund' else None) or business.stamp(business.now())
        self.facts = {'version': VERSION, 'collection_status': 'unknown',
            'publication_status': 'unknown', 'publication_reason': 'NAV_rows_not_bound_to_public_bytes',
            'reason': 'not_attempted', 'scope': {}, 'counts': {}, 'samples': [], 'outcomes': [],
            'outcome_fields': ['fund_code', 'source', 'persistence', 'published_rows', 'committed_rows'],
            'range_details': 'ordered_digest_and_first_8_samples',
            'persistence_semantics': 'committed_UPSERT_input_not_DB_readback',
            'source_completeness': 'unknown', 'historical_completeness': 'unknown'}
        self.hashes = {k: hashlib.sha256() for k in ('source', 'committed', 'attempts')}
        self.sizes = dict.fromkeys(self.hashes, 0)
        self.work = 0.0
        self.nav_rows = {}
        self.record(finished=False)

    def digest(self, key, values):
        for value in values:
            if time.monotonic() >= self.observation_deadline:
                raise TimeoutError('fund observation work limit')
            raw = _canonical(value) + b'\n'
            self.hashes[key].update(raw)
            self.sizes[key] += len(raw)

    def apply(self, action, **data):
        c = self.facts['counts']
        if action == 'scope':
            self.facts['scope'].update(data)
            if 'selected_count' in data:
                c.update(selected=data['selected_count'], attempted=0, committed_targets=0,
                         published_rows=0, committed_rows=0, legal_empty=0, errors=0)
        elif action == 'reason':
            self.facts['reason'] = data['reason']
            if data.get('failure'):
                c['errors'] = c.get('errors', 0) + 1
        elif action == 'attempt':
            c['attempted'] = c.get('attempted', 0) + 1
            self.facts['outcomes'].append([data['fund_code'], 'not_observed', 'not_attempted', 0, 0])
            self.digest('attempts', [data])
        elif action == 'ranges':
            self.digest('attempts', [{'planned': data}])
            if len(self.facts['samples']) < 8:
                self.facts['samples'].append(data)
        elif action in ('range_attempt', 'range_return'):
            key = 'query_ranges_attempted' if action == 'range_attempt' else 'query_ranges_returned'
            c[key] = c.get(key, 0) + 1
            self.digest('attempts', [{action: data}])
        elif action in ('source', 'committed'):
            # Exactly the selected source/UPSERT inputs, not global MAX(date).
            rows = data['rows']
            if action == 'source':
                c['published_rows'] = c.get('published_rows', 0) + len(rows)
                if not rows:
                    c['legal_empty'] = c.get('legal_empty', 0) + 1
                if self.facts['outcomes']:
                    self.facts['outcomes'][-1][1] = 'published' if rows else 'legal_empty'
                    self.facts['outcomes'][-1][3] = len(rows)
            else:
                c['committed_rows'] = c.get('committed_rows', 0) + len(rows)
                c['committed_targets'] = c.get('committed_targets', 0) + 1
                self.facts['outcomes'][-1][2] = 'committed'
                self.facts['outcomes'][-1][4] = len(rows)
            self.digest(action, rows)
            if action == 'committed':
                self.capture_nav_rows(rows)
            self.facts['reason'] = 'source_observed'
        elif action == 'error':
            c['errors'] = c.get('errors', 0) + 1
            self.facts['reason'] = data['reason']
            if self.facts['outcomes']:
                last = self.facts['outcomes'][-1]
                if last[1] == 'not_observed':
                    last[1] = 'error'
                if last[2] != 'committed':
                    last[2] = 'failed'
        elif action == 'abort':
            self.facts['terminal_error'] = data['reason']
            self.facts['reason'] = data['reason']
        elif action == 'daily':
            # rows are already constructed for SQL. No second DB query or API.
            rows = data.pop('rows')
            self.facts['scope'].update(data)
            c.update(selected=len(rows), attempted=len(rows), committed_targets=0,
                     published_rows=0, committed_rows=0, legal_empty=0,
                     unpublished_rows=0, errors=0)
            for row in rows:
                self.digest('source', [row])
                c['published_rows' if row[3] is not None else 'unpublished_rows'] += 1
            self.facts['reason'] = 'selected_date_observed'
        elif action == 'daily_commit':
            # Same loaded rows were passed to the completed UPSERT transaction.
            self.digest('committed', data['rows'])
            self.capture_nav_rows(data['rows'])
            c['committed_rows'] = c['published_rows']
            c['committed_targets'] = c['selected']
            c['committed_statements'] = c['selected']

    def capture_nav_rows(self, rows):
        try:
            from .ops_nav_publication import normalized_row, MAX_INPUT_ROWS
        except ImportError:
            from ops_nav_publication import normalized_row, MAX_INPUT_ROWS
        for row in rows:
            if time.monotonic() >= self.observation_deadline or len(self.nav_rows) >= MAX_INPUT_ROWS:
                raise TimeoutError('NAV scope observation budget')
            value = normalized_row(row)
            if value is not None:
                key = (value[0], value[1])
                if key in self.nav_rows and self.nav_rows[key] != value:
                    raise ValueError('conflicting committed NAV scope')
                self.nav_rows[key] = value

    def record(self, *, finished=True):
        c = self.facts['counts']
        selected, attempted = c.get('selected', 0), c.get('attempted', 0)
        c['selected_not_attempted'] = max(0, selected - attempted)
        pool = self.facts['scope'].get('pool_count')
        if pool is not None:
            c['pool_not_attempted'] = max(0, pool - attempted)
        if finished:
            self.facts['collection_status'] = ('unknown' if self.facts.get('metadata_failed') else
                'failure' if c.get('errors', 0) or self.facts.get('terminal_error') else
                'scoped_committed' if selected and c.get('committed_targets') == selected else
                'legal_empty' if c.get('legal_empty') else 'unknown')
            if self.nav_rows and not self.facts.get('metadata_failed'):
                try:
                    from .ops_nav_publication import save_inputs
                except ImportError:
                    from ops_nav_publication import save_inputs
                finalization_started = time.monotonic()
                self.facts['publication_input'] = save_inputs(self.root, self.object_id, self.run, self.started, self.nav_rows)
                elapsed = time.monotonic() - finalization_started
                self.facts['publication_finalize_seconds'] = round(elapsed, 6)
                if elapsed > MAX_WORK_SECONDS:
                    # Preserve the transaction facts but do not certify metadata
                    # completed within budget. This cannot undo an I/O stall.
                    self.facts['publication_input'] = None
                    self.facts['publication_reason'] = 'metadata_finalize_budget'
        def identity(key):
            return {'object_id': key + '_observations', 'sha256': self.hashes[key].hexdigest(),
                    'size': self.sizes[key], 'identity_kind': 'ordered_loaded_rows', 'quality': 'stage_only'}
        return business.record_result(self.root, self.object_id, run_id=self.run, started_at=self.started,
            status='failure' if self.facts['collection_status'] == 'failure' else 'unknown',
            reason=self.facts['reason'] if self.facts['collection_status'] == 'failure' else 'fund_publication_unverified',
            inputs=[identity(k) for k in ('source', 'attempts') if self.sizes[k]],
            outputs=[identity('committed')] if self.sizes['committed'] else [],
            expected=selected, observed=c.get('committed_targets', 0), fund_evidence=self.facts,
            code=self.code,
            finished_at=business.stamp(business.now()) if finished else None)


def observe(action, **data):
    current = _ACTIVE.get()
    if current is None or current.facts.get('metadata_failed'):
        return
    began = time.monotonic()
    try:
        if current.work >= MAX_WORK_SECONDS:
            raise TimeoutError('fund observation work limit')
        current.observation_deadline = began + MAX_WORK_SECONDS - current.work
        current.apply(action, **data)
    except Exception as exc:
        current.facts['metadata_failed'] = True
        _metadata_failure(exc)
    finally:
        current.work += time.monotonic() - began
        if current.work > MAX_WORK_SECONDS:
            current.facts['metadata_failed'] = True


def capture(object_id, root):
    """Metadata errors never change collector return/exception; dry-run is silent."""
    def decorate(fn):
        signature = inspect.signature(fn)
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            if not evidence_enabled() or signature.bind(*args, **kwargs).arguments.get('dry_run', False):
                return fn(*args, **kwargs)
            began = time.monotonic()
            try:
                current = Round(root(), object_id, producer_identity(fn, root()))
                current.setup_seconds = time.monotonic() - began
            except Exception as exc:
                _metadata_failure(exc)
                return fn(*args, **kwargs)
            token = _ACTIVE.set(current)
            try:
                return fn(*args, **kwargs)
            except BaseException as exc:
                observe('abort', reason=type(exc).__name__)
                raise
            finally:
                _ACTIVE.reset(token)
                try:
                    current.record()
                except Exception as exc:
                    _metadata_failure(exc)
        return wrapper
    return decorate


def producer_identity(fn, root):
    # Reuse the reviewed-manifest binding, including this helper's class methods.
    # A helper-only change must invalidate the loaded digest too. This function
    # object is introspected, never executed; no disk HEAD is substituted.
    namespace = dict(fn.__globals__)
    namespace.update({'fund.' + k: v for k, v in globals().items() if inspect.isfunction(v)})
    namespace.update({'fund.Round.' + k: v for k, v in vars(Round).items() if inspect.isfunction(v)})
    try:
        from . import ops_nav_publication as nav
    except ImportError:
        import ops_nav_publication as nav
    namespace.update({'nav.'+k: v for k, v in vars(nav).items() if inspect.isfunction(v)})
    return loaded_code_identity(types.FunctionType(fn.__code__, namespace), root)


def setup_seconds():
    """Charge FOF's opt-in setup to its existing absolute collection budget."""
    current = _ACTIVE.get()
    return current.setup_seconds if current is not None else 0.0


def shell_result(root, run, started, rc, reason):
    """Fixed current-run index only. rc0 never fabricates collection/publication."""
    if not evidence_enabled():
        return
    try:
        r = business.bounded_json(receipt_root(root) / 'index/public-fund.json')
        _validate(r)
        if (r['object_id'] != 'public-fund' or r['chain_id'] != 'ops_business' or
                r['attempt_id'] != run or r['producer_time']['started_at'] != started):
            raise ValueError('current collection receipt missing')
        facts = r['consumer_witness'].get('fund_evidence', {})
        facts.update(shell_rc=rc, shell_reason=reason)
        business.record_result(root, 'public-fund', run_id=run, started_at=started,
            status='failure' if rc or r['stage_status'] == 'failure' else 'unknown',
            reason=reason if rc else r['reason'], inputs=r['inputs'], outputs=r['outputs'],
            expected=r['counts']['expected'], observed=r['counts']['validated'],
            code=r['code_identity'],
            fund_evidence=facts, finished_at=business.stamp(business.now()))
    except Exception as exc:
        _metadata_failure(exc)
        business.record_result(root, 'public-fund', run_id=run, started_at=started,
            status='failure' if rc else 'unknown', reason=reason if rc else 'collection_not_observed',
            finished_at=business.stamp(business.now()))


def main():
    p = argparse.ArgumentParser()
    p.add_argument('action', choices=('begin', 'finish'))
    p.add_argument('--root', required=True)
    p.add_argument('--run', required=True)
    p.add_argument('--started', required=True)
    p.add_argument('--rc', type=int, default=0)
    p.add_argument('--reason', default='shell_completed')
    a = p.parse_args()
    if not evidence_enabled():
        return
    if a.action == 'begin':
        business.record_result(a.root, 'public-fund', run_id=a.run, started_at=a.started)
    else:
        shell_result(a.root, a.run, a.started, a.rc, a.reason)


if __name__ == '__main__':
    main()
