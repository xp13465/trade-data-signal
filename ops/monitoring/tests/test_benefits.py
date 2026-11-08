"""SYNTHETIC controls only. No production artifacts, business jobs or networking."""
import copy
from datetime import datetime, timezone, timedelta
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from ops.monitoring import benefits as b

CHAIN = 'market_signal_freeze_plan'
DAY = '2026-11-06'
NOW = datetime(2026, 11, 7, tzinfo=timezone.utc)


def fixture():
    """Explicit synthetic approved-policy and immutable receipt facts."""
    dates = ['2026-11-05', DAY]
    req = [dict(stage=stage, object_id=stage + '_validator', inputs=[inp], outputs=[out])
           for stage, inp, out in [('signal', 'raw', 'signal_result'), ('freeze', 'signal_result', 'freeze_result'), ('plan', 'freeze_result', 'plan_result')]]
    req[-1]['consumer_scope'] = 'synthetic_reader'
    p = dict(inventory_complete=True, inventory_id='synthetic-inventory', code_sha='a' * 40,
             config_sha='b' * 64, deadline_at=DAY + 'T12:00:00Z', batches=[CHAIN + ':' + DAY], required=req,
             edges=[{'from': ['signal', 'signal_validator'], 'to': ['freeze', 'freeze_validator'], 'object_id': 'signal_result'},
                    {'from': ['freeze', 'freeze_validator'], 'to': ['plan', 'plan_validator'], 'object_id': 'freeze_result'}])
    c = dict(schema_version='benefits-control-v1', measurement_kind='synthetic', contract_id='synthetic-contract',
             caliber_id='synthetic-caliber', population_id='synthetic-population', schedule_id='synthetic-schedule',
             exclusion_policy_id='synthetic-none', normalizer_sha='e' * 40,
             policy={'reviewed': True, 'approval_sha256': 'c' * 64, 'approved_at': '2026-11-01T00:00:00Z'},
             calendar={'verified_complete': True, 'source_ref': 'synthetic://calendar-not-exchange', 'timezone': 'Asia/Shanghai',
                       'trading_days': dates, 'sha256': hashlib.sha256(json.dumps(dates, separators=(',', ':')).encode()).hexdigest()},
             sessions=[{'date': DAY, 'chains': {CHAIN: p}}],
             rollout={'effective_at': '2026-11-02T00:00:00Z', 'evidence_ref': 'synthetic://rollout',
                      'before_code_sha': 'f'*40, 'after_code_sha': 'a'*40,
                      'before_config_sha256': 'f'*64, 'after_config_sha256': 'b'*64})
    receipts = []
    for i, r in enumerate(req):
        t = DAY + f'T0{7+i}:00:00Z'
        def ident(k):
            return dict(object_id=k, sha256=b.digest(k), session_date=DAY, quality='strong', observed_at=t)
        receipt = dict(schema='trade-delivery-receipt-v1', receipt_id='synthetic-' + r['stage'],
                       chain_id=CHAIN, session_date=DAY, stage=r['stage'], object_id=r['object_id'],
                       batch_id=CHAIN + ':' + DAY, attempt_id='synthetic-process-' + str(i), evaluated_at=t,
                       producer_time={'completed_at': t}, stage_status='success', reason='synthetic_validation',
                       evidence_quality='strong', code_identity={'sha': 'a'*40}, config_identity={'sha256': 'b'*64},
                       inputs=[ident(k) for k in r['inputs']], outputs=[ident(k) for k in r['outputs']],
                       counts=dict(inventory_complete=1, expected=1, validated=1, failed=0, unknown=0),
                       consumer_witness={'status': 'unknown'})
        receipts.append((b.digest(receipt), receipt))
    receipts[-1][1]['consumer_witness'] = dict(status='success', session_date=DAY, batch_id=CHAIN + ':' + DAY,
                                            output_sha256=receipts[-1][1]['outputs'][0]['sha256'], consumer_scope='synthetic_reader')
    receipts = [(b.digest(r), r) for _, r in receipts]
    return c, receipts


def write_fixture(root, c, receipts):
    control = root / b.CONTROL
    control.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    control.write_bytes(b.canonical(c))
    for session in c['sessions']:
        for chain in b.CHAINS:
            (root / b.RECEIPTS / session['date'] / chain).mkdir(mode=0o700, parents=True, exist_ok=True)
    for _, r in receipts:
        p = root / b.RECEIPTS / r['session_date'] / r['chain_id'] / (r['receipt_id'] + '.json')
        p.write_bytes(b.canonical(r))
        p.chmod(0o600)


class BenefitsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='synthetic-benefits-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.c, self.receipts = fixture()

    def norm(self, **kw):
        return b.normalize(self.c, self.receipts, CHAIN, DAY, NOW, **kw)

    def test_valid_chain_different_processes_and_source_clock(self):
        e = self.norm()['evidence']
        self.assertEqual((e['success'], e['failure'], e['unknown']), (1, 0, 0))
        self.assertEqual(e['source_at'], DAY + 'T09:00:00Z')
        self.assertEqual(e['evaluated_at'], NOW.isoformat().replace('+00:00', 'Z'))
        self.assertNotIn('attempt_id', e)
        self.assertEqual(len(self.norm()['attempt_ids']), 3)
        self.assertEqual(b.wire(self.norm())['status'], 'unknown')
        self.assertEqual(b.wire(self.norm())['evidence']['measurement_kind'], 'synthetic')
        self.assertEqual(b.wire(dict(self.norm(), measurement_kind='real'))['status'], 'unknown')
        self.assertEqual(b.wire(dict(self.norm(), measurement_kind='real'))['evidence']['measurement_kind'], 'unknown')

    def test_missing_consumer_is_unknown(self):
        self.receipts[-1][1]['consumer_witness'] = {'status': 'unknown'}
        self.assertEqual(self.norm()['evidence']['unknown'], 1)

    def test_same_day_incompatible_digest_is_unknown(self):
        self.receipts[1][1]['inputs'][0]['sha256'] = '0' * 64
        self.assertEqual(self.norm()['evidence']['unknown'], 1)

    def test_untrusted_identity_and_stage_only_are_unknown(self):
        for key, val in [('evidence_quality', 'stage_only'), ('code_identity', {'sha': 'unknown'})]:
            c, receipts = fixture()
            receipts[0][1][key] = val
            got = b.normalize(c, receipts, CHAIN, DAY, NOW)
            self.assertEqual(got['evidence']['unknown'], 1)

    def test_deadline_closed_and_final_day_late_is_failure(self):
        self.receipts[-1][1]['producer_time']['completed_at'] = DAY + 'T13:00:00Z'
        self.receipts[-1][1]['evaluated_at'] = DAY + 'T13:00:00Z'
        self.assertEqual(self.norm()['evidence']['failure'], 1)
        self.assertEqual(self.norm()['outcomes'][0]['reason'], 'verified_stale')

    def test_future_deadline_no_green(self):
        self.c['sessions'][0]['chains'][CHAIN]['deadline_at'] = '2026-11-08T00:00:00Z'
        self.assertIsNone(self.norm()['evidence']['expected'])

    def test_missing_inventory_and_truncated_sources_are_null(self):
        self.assertIsNone(self.norm(source_complete=False)['evidence']['expected'])
        self.c['sessions'][0]['chains'][CHAIN]['inventory_complete'] = False
        self.assertIsNone(self.norm()['evidence']['success'])

    def test_failure_without_later_stages_is_validated_failure(self):
        self.receipts = self.receipts[:1]
        self.receipts[0][1]['stage_status'] = 'failure'
        self.receipts[0][1]['counts'].update(failed=1, validated=0)
        self.assertEqual(self.norm()['evidence']['failure'], 1)

    def test_ambiguous_attempts_not_stitched(self):
        r = copy.deepcopy(self.receipts[0][1]); r['attempt_id'] = 'synthetic-other'
        self.receipts.append((b.digest(r), r))
        self.assertEqual(self.norm()['evidence']['unknown'], 1)

    def test_duplicate_receipts_and_resampling_idempotent(self):
        original = self.norm()
        self.receipts += self.receipts[:1]
        newer = b.normalize(self.c, self.receipts, CHAIN, DAY, datetime(2026, 11, 8, tzinfo=timezone.utc))
        self.assertEqual(original['evidence']['proof_sha'], newer['evidence']['proof_sha'])
        b.persist(self.root / 'out', {'records': [original]})
        b.persist(self.root / 'out', {'records': [newer]})
        con = sqlite3.connect(self.root / 'out/benefits.sqlite3')
        self.addCleanup(con.close)
        self.assertEqual(con.execute('SELECT count(*) FROM observations').fetchone()[0], 1)

    def test_concurrent_persistence_no_lost_or_duplicate_facts(self):
        result = {'records': [self.norm()]}
        b.persist(self.root / 'out', result)
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _: b.persist(self.root / 'out', result), range(8)))
        con = sqlite3.connect(self.root / 'out/benefits.sqlite3'); self.addCleanup(con.close)
        self.assertEqual(con.execute('SELECT count(*) FROM observations').fetchone()[0], 1)

    def test_partitioning_ignores_lifetime_history(self):
        write_fixture(self.root, self.c, self.receipts)
        old = self.root / b.RECEIPTS / '2025-01-01'
        old.mkdir()
        for i in range(300):
            (old / f'{i}.json').write_text('not-current-evidence')
        result = b.sample(self.root, now=NOW)
        self.assertEqual(result['records'][0]['evidence']['success'], 1)

    def test_oversize_and_symlink_are_unknown(self):
        write_fixture(self.root, self.c, self.receipts)
        p = self.root / b.RECEIPTS / DAY / CHAIN / 'oversize.json'
        p.write_bytes(b' ' * (b.MAX_FILE + 1))
        self.assertIsNone(b.sample(self.root, now=NOW)['records'][0]['evidence']['expected'])
        p.unlink(); p.symlink_to(self.root / b.CONTROL)
        self.assertIsNone(b.sample(self.root, now=NOW)['records'][0]['evidence']['expected'])

    def test_symlink_parent_rejected(self):
        write_fixture(self.root, self.c, self.receipts)
        partition = self.root / b.RECEIPTS / DAY / CHAIN
        partition.rename(partition.with_name('moved'))
        partition.symlink_to(partition.with_name('moved'), target_is_directory=True)
        self.assertIsNone(b.sample(self.root, now=NOW)['records'][0]['evidence']['expected'])

    def test_limit_does_not_pick_arbitrary_latest(self):
        write_fixture(self.root, self.c, self.receipts)
        slot = self.root / b.RECEIPTS / DAY / CHAIN
        for i in range(129):
            (slot / f'{i}.json').write_text('{}')
        self.assertIsNone(b.sample(self.root, now=NOW)['records'][0]['evidence']['expected'])

    def test_expired_reader_and_no_policy_not_ready(self):
        with self.assertRaises(b.EvidenceError):
            b.Reader(self.root, seconds=-1).read(b.CONTROL)
        self.assertEqual(b.sample(self.root, now=NOW)['status'], 'not_ready')
        write_fixture(self.root, self.c, self.receipts)
        with patch.object(b.Reader, 'remaining', side_effect=b.EvidenceError('budget')):
            self.assertEqual(b.sample(self.root, now=NOW)['status'], 'not_ready')

    def test_latest_two_declared_sessions_only(self):
        for d in ('2026-11-04', '2026-11-05'):
            self.c['sessions'].append({'date': d, 'chains': {}})
        self.c['calendar']['trading_days'] = ['2026-11-04', '2026-11-05', DAY]
        self.c['calendar']['sha256'] = hashlib.sha256(json.dumps(self.c['calendar']['trading_days'], separators=(',', ':')).encode()).hexdigest()
        write_fixture(self.root, self.c, self.receipts)
        result = b.sample(self.root, now=NOW)
        self.assertEqual(len(result['records']), 6)
        self.assertEqual({r['evidence']['session_date'] for r in result['records']}, {'2026-11-05', DAY})

    def test_wire_fits_existing_validator_and_no_private_data(self):
        spec = importlib.util.spec_from_file_location('benefits_ops_monitor', ROOT / 'scripts/ops_monitor.py')
        m = importlib.util.module_from_spec(spec); sys.modules[spec.name] = m; spec.loader.exec_module(m)
        snapshot = m.Collector(m.Settings()).snapshot()
        snapshot['checks'] = [b.wire(self.norm())]
        payload = m.validate_snapshot(snapshot)
        self.assertEqual(len(self.norm()['evidence']), 20)
        self.assertNotIn(str(self.root).encode(), payload)
        self.assertNotIn(b'consumer_witness', payload)

    def test_old_config_compatible_and_upload_reserve(self):
        spec = importlib.util.spec_from_file_location('benefits_ops_monitor2', ROOT / 'scripts/ops_monitor.py')
        m = importlib.util.module_from_spec(spec); sys.modules[spec.name] = m; spec.loader.exec_module(m)
        cfg_path = self.root / 'old.json'; cfg_path.write_text('{}')
        cfg = m.Settings.load(cfg_path)
        self.assertFalse(cfg.benefits_enabled)
        cfg.benefits_enabled = True
        seen = []
        def fake_benefits(cfg, budget):
            seen.append(budget.deadline - budget.started)
            raise TimeoutError()
        def fake_network(budget, *args, **kw):
            self.assertGreater(budget.remaining(), 8)
            return {'ok': True}
        cfg.output_dir = str(self.root / 'out')
        with patch.object(m.Collector, 'collect', lambda collector: collector.snapshot()), patch.object(m, 'benefits_bounded', fake_benefits), patch.object(m, 'network_bounded', fake_network):
            report, code = m.run_once(cfg)
        self.assertEqual(len(seen), 1)
        # 20s 总预算仍须为上传保留 8s；浮点相减按 100ns 精度比较。
        # 曾观测到 12.000000000000455s，误差约 4.6e-13s，远小于 1e-7s。
        self.assertAlmostEqual(seen[0], 12, places=7)
        self.assertEqual(code, 0)
        self.assertTrue(report['delivery']['ok'])

    def test_partial_known_failure_cannot_hide_behind_older_verified_success(self):
        c, rs = fixture()
        p = c['sessions'][0]['chains'][CHAIN]
        second = CHAIN + ':' + DAY + ':second'
        p['batches'].append(second)
        extra = copy.deepcopy(rs)
        for _, r in extra:
            r['batch_id'] = second
            r['receipt_id'] += '-second'
            if r['consumer_witness']['status'] == 'success':
                r['consumer_witness']['batch_id'] = second
        old = b.normalize(c, rs + [(b.digest(r), r) for _, r in extra], CHAIN, DAY, NOW)
        self.assertEqual(old['evidence']['success'], 2)
        bad = copy.deepcopy(rs[0][1])
        bad.update(stage_status='failure', evaluated_at=DAY + 'T11:00:00Z')
        bad['producer_time']['completed_at'] = bad['evaluated_at']
        bad['counts'].update(failed=1, validated=0)
        newer = b.normalize(c, [(b.digest(bad), bad)], CHAIN, DAY, NOW)
        self.assertEqual((newer['evidence']['failure'], newer['evidence']['unknown']), (1, 1))
        got = b.export_periods(c, [old, newer], CHAIN, NOW.isoformat())
        row = next(row for row in got['after']['days'] if row['date'] == DAY)
        self.assertIsNone(row['success'])
        self.assertFalse(row['inventory_complete'])

    def test_twenty_session_persistence_export_and_comparator(self):
        from ops.monitoring.tests.test_benefits_compare import fixture as comparison_fixture
        from ops.monitoring.compare_benefits import compare
        pair = comparison_fixture()
        c = copy.deepcopy(self.c)
        c['calendar'] = pair['before']['calendar']
        c['rollout'] = pair['before']['rollout']
        c['policy']['approved_at'] = '2026-10-01T00:00:00Z'
        c['sessions'] = []
        for label in ('before', 'after'):
            for row in pair[label]['days']:
                p = copy.deepcopy(self.c['sessions'][0]['chains'][CHAIN])
                d = row['date']
                p.update(code_sha=pair[label]['code_sha'], config_sha=pair[label]['config_sha256'],
                         deadline_at=d + 'T12:00:00Z', batches=[CHAIN + ':' + d])
                c['sessions'].append({'date': d, 'chains': {CHAIN: p}})
        now = datetime(2026, 11, 17, tzinfo=timezone.utc)
        records = []
        for slot in c['sessions']:
            rs = copy.deepcopy(self.receipts)
            d, p = slot['date'], slot['chains'][CHAIN]
            for _, r in rs:
                r.update(session_date=d, batch_id=CHAIN + ':' + d)
                r['evaluated_at'] = d + r['evaluated_at'][10:]
                r['producer_time']['completed_at'] = r['evaluated_at']
                r['code_identity']['sha'] = p['code_sha']
                r['config_identity']['sha256'] = p['config_sha']
                for v in r['inputs'] + r['outputs']:
                    v.update(session_date=d, observed_at=r['evaluated_at'])
                if r['consumer_witness']['status'] == 'success':
                    r['consumer_witness'].update(session_date=d, batch_id=CHAIN + ':' + d)
            records.append(b.normalize(c, [(b.digest(r), r) for _, r in rs], CHAIN, d, now))
        self.assertTrue(all(r['evidence']['success'] == 1 for r in records))
        b.persist(self.root / 'out', {'records': records})
        control = self.root / b.CONTROL
        control.parent.mkdir(parents=True)
        control.write_bytes(b.canonical(c))
        export = subprocess.run([sys.executable, str(ROOT / 'ops/monitoring/benefits.py'), 'export',
                                 '--data-root', str(self.root), '--output-dir', str(self.root / 'out'),
                                 '--chain', CHAIN, '--as-of', now.isoformat()], capture_output=True, text=True, timeout=5)
        self.assertEqual(export.returncode, 0, export.stdout + export.stderr)
        periods = json.loads(export.stdout)
        result = compare(periods['before'], periods['after'], allow_synthetic=True)
        self.assertEqual(result['status'], 'ready', result['not_ready_reasons'])
        self.assertFalse(result['real_benefit_claim'])
        self.assertEqual(result['before']['raw_totals']['denominator'], 10)
        # New unknown evidence does not erase a unique verified historical fact.
        unknown = b.normalize(c, [], CHAIN, c['sessions'][0]['date'], now)
        periods = b.export_periods(c, records + [unknown], CHAIN, now.isoformat())
        self.assertEqual(periods['before']['days'][0]['success'], 1)
        c['sessions'].append({'date': '2099-01-01', 'chains': {}})
        self.assertEqual(b.export_periods(c, records, CHAIN, now.isoformat())['before']['days'][0]['success'], 1)

    def test_actual_producer_hooks_to_normalizer_and_missing_witness(self):
        # Real original backtest main/_build_outputs AST, actual atomic writer,
        # run proof and isolated-reader validator. Only engine inputs/stats and
        # reviewed installation binding are synthetic. No hand-written emit.
        from scripts.tests.test_delivery_evidence_20261107 import build_hook_fixture
        with patch.object(socket, 'create_connection', side_effect=AssertionError('network forbidden')), patch.object(subprocess, 'run', side_effect=AssertionError('business command or notify forbidden')):
            c, pairs, session, policy = build_hook_fixture(self.root)
        chain = 'backtest_publish_consume'
        closed = max(b.stamp(r['producer_time']['completed_at']) for _, r in pairs) + timedelta(seconds=1)
        policy['deadline_at'] = closed.isoformat()
        c['calendar']['trading_days'] = [session]
        c['calendar']['sha256'] = hashlib.sha256(json.dumps([session], separators=(',', ':')).encode()).hexdigest()
        b.validate_control(c)
        evaluation = closed + timedelta(seconds=1)  # explicit synthetic as-of
        got = b.normalize(c, pairs, chain, session, evaluation)
        self.assertEqual(got['evidence']['success'], 1, got)
        self.assertEqual(b.wire(got)['status'], 'unknown')
        self.assertEqual(b.wire(got)['evidence']['measurement_kind'], 'synthetic')
        no_consumer = [(h, r) for h, r in pairs if r['stage'] != 'consumer']
        self.assertEqual(b.normalize(c, no_consumer, chain, session, evaluation)['evidence']['unknown'], 1)
        policy['required'][-1]['consumer_scope'] = 'production_browser'
        self.assertEqual(b.normalize(c, pairs, chain, session, evaluation)['evidence']['unknown'], 1)
        policy['required'][-1]['consumer_scope'] = 'isolated_local_reader'
        (self.root / b.CONTROL).write_bytes(b.canonical(c))
        sampled = b.sample(self.root, now=evaluation)
        row = next(r for r in sampled['records'] if r['evidence']['chain_id'] == chain)
        self.assertEqual(row['evidence']['success'], 1)

    def test_real_collector_child_collect_only_with_synthetic_evidence(self):
        write_fixture(self.root, self.c, self.receipts)
        (self.root / 'code').mkdir()
        cfg = dict(code_root=str(self.root / 'code'), data_root=str(self.root),
                   output_dir=str(self.root / 'out'), benefits_enabled=True)
        config = self.root / 'collector.json'
        config.write_text(json.dumps(cfg))
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/ops_monitor.py'),
                                 '--config', str(config), '--collect-only'],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        snap = json.loads((self.root / 'out/snapshot.json').read_text())
        checks = [c for c in snap['checks'] if c['id'].startswith('benefit:')]
        self.assertEqual(len(checks), 3)
        self.assertEqual(checks[0]['status'], 'unknown')
        self.assertEqual(checks[0]['evidence']['measurement_kind'], 'synthetic')
        self.assertTrue((self.root / 'out/benefits.sqlite3').exists())

    def test_stalled_evidence_child_is_killed_within_budget(self):
        spec = importlib.util.spec_from_file_location('benefits_ops_timeout', ROOT / 'scripts/ops_monitor.py')
        m = importlib.util.module_from_spec(spec); sys.modules[spec.name] = m; spec.loader.exec_module(m)
        if 'fork' not in m.multiprocessing.get_all_start_methods():
            self.skipTest('fork-only isolated stalled-child control')
        context = m.multiprocessing.get_context('fork')
        def blocked(*args):
            time.sleep(30)
        started = time.monotonic()
        with patch.object(m, '_benefits_worker', blocked), patch.object(m.multiprocessing, 'get_context', return_value=context):
            result = m.benefits_bounded(m.Settings(), m.Budget(0.3))
        self.assertEqual(result, [])
        self.assertLess(time.monotonic() - started, 1)

    def test_snapshot_limit_never_displaces_old_checks(self):
        spec = importlib.util.spec_from_file_location('benefits_ops_monitor3', ROOT / 'scripts/ops_monitor.py')
        m = importlib.util.module_from_spec(spec); sys.modules[spec.name] = m; spec.loader.exec_module(m)
        s = m.Collector(m.Settings()).snapshot()
        s['checks'] = [m.check('existing:' + str(i), 'monitor', 'unknown', 'synthetic') for i in range(249)]
        original = copy.deepcopy(s['checks'])
        with patch.object(m, 'benefits_bounded', return_value=[b.wire(self.norm())]):
            m.append_benefits(s, m.Settings(), m.Budget())
        self.assertEqual(s['checks'], original)


if __name__ == '__main__':
    unittest.main()
