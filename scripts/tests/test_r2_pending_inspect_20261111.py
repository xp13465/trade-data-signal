"""Offline real-file diagnostics: actual lifecycle; adversarial files and read races."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import r2_pending_context as api

NOW = 1000.0


class InspectTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='r2-inspect-')
        self.home = Path(self.temp.name).resolve()
        self.root = self.home / 'site'
        self.root.mkdir()
        self.flag = self.home / 'pending'
        self.directory = Path(str(self.flag) + '.contexts')

    def tearDown(self):
        self.temp.cleanup()

    def enqueue(self, run='run-a', created=900, root=None):
        root = root or self.root
        proof = self.home / (run + '.proof')
        proof.write_text(json.dumps({'version': 1, 'run_id': run, 'static_dir': str(root),
            'outputs': {'boot.json': {'size': 2, 'sha256': hashlib.sha256(b'{}').hexdigest()}}}))
        with patch.object(api.time, 'time', return_value=created):
            return api.enqueue(self.flag, root, proof, run)

    def change(self, row, **changes):
        row = dict(row, **changes)
        (self.directory / (row['id'] + '.json')).write_text(json.dumps(row))
        return row

    def proof_change(self, row, value):
        old = Path(row['proof_path'])
        raw = json.dumps(value).encode()
        digest = hashlib.sha256(raw).hexdigest()
        new = self.directory / (row['id'] + '.' + digest + '.proof')
        old.unlink()
        new.write_bytes(raw)
        new.chmod(0o600)
        return self.change(row, proof_sha256=digest, proof_path=str(new))

    def inspect(self, **kwargs):
        return api.inspect_contexts(self.flag, self.root, now=NOW, **kwargs)

    def terminal(self, state='done'):
        row = self.enqueue()
        batch = self.home / 'batch.json'
        with patch.object(api.time, 'time', return_value=950):
            snapshot = api.snapshot(self.flag, self.root, batch)
        result = self.home / 'result.json'
        result.write_text(json.dumps({'batch_id': snapshot['batch_id'], 'outcomes': [
            {'id': row['id'], 'proof_sha256': row['proof_sha256'], 'state': state}]}))
        with patch.object(api.time, 'time', return_value=975):
            outcome = api.finish(self.flag, self.root, batch, result, True)
        self.assertEqual(outcome['consumed'], [row['id']])
        return row

    def fingerprint(self):
        return {str(p.relative_to(self.home)): (p.lstat().st_mode, p.lstat().st_mtime_ns,
            p.lstat().st_ctime_ns, p.read_bytes() if p.is_file() else None)
            for p in self.home.rglob('*')}

    def test_pending_real_id_age_no_sla_or_side_effects(self):
        row = self.enqueue()
        before = self.fingerprint()
        result = self.inspect()
        self.assertEqual(before, self.fingerprint())
        self.assertEqual(result['status'], 'unknown')
        self.assertEqual(result['reason'], 'pending_without_deadline_contract')
        self.assertEqual(result['inspection_status'], 'complete')
        actual, = result['records']
        self.assertEqual(actual['id'], row['id'])
        self.assertEqual(actual['run_id'], 'run-a')
        self.assertEqual(actual['proof_integrity'], 'verified_owned_copy')
        self.assertEqual(actual['consumption_status'], 'not_offered')
        self.assertEqual(actual['wait_seconds'], 100)
        self.assertEqual(actual['deadline_status'], 'unknown')
        self.assertEqual(result['summary']['oldest_wait_seconds'], 100)
        self.assertNotIn(str(self.home), json.dumps(result))

    def test_offered_is_not_consumed_and_age_is_not_reset(self):
        self.enqueue()
        with patch.object(api.time, 'time', return_value=950):
            api.snapshot(self.flag, self.root, self.home / 'batch.json')
        row, = self.inspect()['records']
        self.assertEqual(row['consumption_status'], 'offered')
        self.assertEqual(row['wait_seconds'], 100)
        self.assertEqual(row['since_last_offer_seconds'], 50)

    def test_done_and_superseded_retired_proof_are_legal_not_public_verification(self):
        for state in ('done', 'superseded'):
            with self.subTest(state=state):
                row = self.terminal(state)
                result = self.inspect()
                actual, = result['records']
                self.assertFalse(Path(row['proof_path']).exists())
                self.assertEqual(result['status'], 'empty')
                self.assertEqual(result['inspection_status'], 'complete')
                self.assertEqual(actual['proof_integrity'], 'retired')
                self.assertEqual(actual['consumption_status'], state)
                self.assertEqual(actual['wait_seconds'], 75)
                self.assertEqual(actual['since_last_offer_seconds'], 25)
                self.assertEqual(actual['public_bytes_status'], 'unknown')
                (self.directory / (row['id'] + '.json')).unlink()

    def test_terminal_existing_but_corrupt_proof_is_not_ignored(self):
        row = self.terminal()
        Path(row['proof_path']).write_bytes(b'bad')
        Path(row['proof_path']).chmod(0o600)
        result = self.inspect()
        self.assertEqual(result['status'], 'warning')
        self.assertIn('proof_hash_mismatch', result['records'][0]['issues'])

    def test_missing_directory_and_lock_do_not_create_anything(self):
        self.assertEqual(self.inspect()['status'], 'unknown')
        self.assertFalse(self.directory.exists())
        self.directory.mkdir(mode=0o700)
        self.assertEqual(self.inspect()['inspection_status'], 'unavailable')
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_empty_existing_contexts_is_only_no_pending(self):
        api.enqueue(self.flag, self.root, None, None)
        result = self.inspect()
        self.assertEqual(result['status'], 'empty')
        self.assertEqual(result['reason'], 'no_pending_requests_observed')
        self.assertEqual(result['health'], 'unknown')
        self.assertTrue(self.flag.exists())

    def test_missing_proof_pending_and_placeholder(self):
        row = self.enqueue()
        Path(row['proof_path']).unlink()
        with self.assertRaises(ValueError):
            api.enqueue(self.flag, self.root, self.home / 'absent', 'missing-run')
        result = self.inspect()
        self.assertNotEqual(result['status'], 'empty')
        self.assertEqual(result['summary']['proof_invalid_count'], 2)
        self.assertEqual({r['proof_integrity'] for r in result['records']}, {'missing'})

    def test_invalid_json_identity_and_states(self):
        row = self.enqueue()
        path = self.directory / (row['id'] + '.json')
        samples = [b'{', b'[]', b'{"version":1,"version":1}',
                   json.dumps(dict(row, id='invented')).encode(),
                   json.dumps(dict(row, state=['pending'])).encode()]
        for raw in samples:
            with self.subTest(raw=raw):
                path.write_bytes(raw)
                result = self.inspect()
                self.assertEqual(result['status'], 'warning')
                self.assertEqual(result['inspection_status'], 'incomplete')

    def test_bad_proof_identity_outputs_and_hash(self):
        row = self.enqueue()
        proof = json.loads(Path(row['proof_path']).read_text())
        for changes in ({'run_id': 'wrong'}, {'outputs': {}}, {'outputs': {'../secret': {}}},
                        {'outputs': {'boot.json': {'size': True, 'sha256': 'a' * 64}}},
                        {'outputs': {'boot.json': {'size': 2, 'sha256': 'bad'}}}):
            with self.subTest(changes=changes):
                row = self.proof_change(row, dict(proof, **changes))
                result = self.inspect()
                self.assertEqual(result['status'], 'warning')
                self.assertEqual(result['records'][0]['proof_integrity'], 'invalid')
        Path(row['proof_path']).write_bytes(b'corrupt')
        self.assertIn('proof_hash_mismatch', self.inspect()['records'][0]['issues'])

    def test_future_nonfinite_and_reversed_timestamps(self):
        original = self.enqueue()
        for changes in ({'created_at': 1001}, {'created_at': True}, {'created_at': 10 ** 400},
                        {'created_at': float('nan')}, {'offered_at': float('inf')},
                        {'offered_at': 1001}, {'offered_at': 899}, {'created_at': None},
                        {'completed_at': 950}):
            with self.subTest(changes=changes):
                self.change(original, **changes)
                result = self.inspect()
                actual = result['records'][0]
                json.dumps(result, allow_nan=False)
                self.assertEqual(result['status'], 'warning')
                self.assertIsNone(actual['wait_seconds'])
                self.assertIn('invalid_or_future_timestamp', actual['issues'])

    def test_terminal_missing_future_or_before_offer_time_is_invalid(self):
        row = self.terminal()
        original = json.loads((self.directory / (row['id'] + '.json')).read_text())
        for value in (None, 1001, 949):
            self.change(original, completed_at=value)
            result = self.inspect()
            self.assertEqual(result['status'], 'warning')
            self.assertEqual(result['records'][0]['proof_integrity'], 'retired')
            self.assertIsNone(result['records'][0]['wait_seconds'])

    def test_explicit_but_unrecognized_deadline_is_not_an_invented_contract(self):
        row = self.enqueue()
        self.change(row, deadline=901, sla_seconds=1, timeout=1, dedup_window=1)
        actual = self.inspect()['records'][0]
        self.assertEqual(actual['deadline_status'], 'unknown')
        self.assertEqual(actual['deadline_reason'], 'no_explicit_request_contract')

    def test_record_and_entry_budget_are_partial_not_totals(self):
        self.enqueue('a')
        self.enqueue('b')
        result = self.inspect(limit=1)
        self.assertTrue(result['truncated'])
        self.assertEqual(result['status'], 'unknown')
        self.assertEqual(result['counts']['pending'], 1)
        with patch.object(api, 'INSPECT_MAX_ENTRIES', 1):
            result = self.inspect()
            self.assertTrue(result['truncated'])
            self.assertLessEqual(result['entries_scanned'], 1)
        for limit in (0, 129, True):
            with self.assertRaises(ValueError):
                self.inspect(limit=limit)

    def test_time_budget_stops_scan(self):
        self.enqueue()
        with patch.object(api.time, 'monotonic', side_effect=[0, 6, 6]):
            result = self.inspect()
        self.assertTrue(result['truncated'])
        self.assertEqual(result['status'], 'unknown')

    def test_caller_budget_zero_does_no_io_and_small_budget_truncates(self):
        with patch.object(api.os, 'open', side_effect=AssertionError('must not read')):
            report = self.inspect(budget_seconds=0)
        self.assertEqual(report['status'], 'unknown')
        self.assertIn('inspection_budget_exhausted', report['issues'])
        self.enqueue()
        with patch.object(api.time, 'monotonic', side_effect=[0, .11, .11]):
            report = self.inspect(budget_seconds=.1)
        self.assertEqual(report['status'], 'unknown')
        self.assertTrue(report['truncated'])
        self.assertEqual(report['limits']['seconds'], .1)
        for budget in (-1, 6, True, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                self.inspect(budget_seconds=budget)

    def test_other_root_not_returned_or_counted_but_uses_budget(self):
        self.enqueue(root=self.home / 'other')
        result = self.inspect()
        self.assertEqual(result['records'], [])
        self.assertEqual(result['counts']['pending'], 0)
        self.assertEqual(result['other_root_records'], 1)
        self.assertEqual(result['records_scanned'], 1)

    def test_record_and_proof_size_caps(self):
        row = self.enqueue()
        for file, cap in ((Path(row['proof_path']), api.INSPECT_PROOF_BYTES),
                          (self.directory / (row['id'] + '.json'), api.INSPECT_RECORD_BYTES)):
            file.write_bytes(b'x' * (cap + 1))
            result = self.inspect()
            self.assertEqual(result['status'], 'warning')
            self.assertIn('file_too_large', result['records'][0]['issues'])

    def test_proof_path_traversal_and_absolute_outside_are_never_opened(self):
        row = self.enqueue()
        original_open = os.open
        external = self.home / 'private'
        external.write_text('secret')
        for value in (str(external), '../private', str(self.directory / '..' / 'private')):
            self.change(row, proof_path=value)
            with patch.object(api.os, 'open', wraps=original_open) as opened:
                result = self.inspect()
            self.assertIn('unsafe_proof_path', result['records'][0]['issues'])
            self.assertFalse(any(str(call.args[0]) == str(external) for call in opened.call_args_list))

    def test_symlink_record_proof_lock_directory_and_ancestor(self):
        row = self.enqueue()
        for path in (Path(row['proof_path']), self.directory / (row['id'] + '.json'),
                     self.directory / '.lock'):
            saved = path.with_suffix(path.suffix + '.saved')
            path.rename(saved)
            path.symlink_to(saved)
            result = self.inspect()
            self.assertEqual(result['status'], 'unknown')
            path.unlink()
            saved.rename(path)
        moved = self.home / 'moved'
        self.directory.rename(moved)
        self.directory.symlink_to(moved, target_is_directory=True)
        self.assertEqual(self.inspect()['status'], 'unknown')
        alias = self.home / 'alias'
        alias.symlink_to(self.home, target_is_directory=True)
        self.assertEqual(api.inspect_contexts(alias / 'pending', self.root)['status'], 'unknown')
        self.assertEqual(api.inspect_contexts(self.home / '..' / 'pending', self.root)['status'], 'unknown')

    def test_hardlinks_permissions_and_fifo_are_not_read(self):
        row = self.enqueue()
        proof = Path(row['proof_path'])
        link = self.home / 'hardlink'
        os.link(proof, link)
        self.assertIn('unsafe_file', self.inspect()['records'][0]['issues'])
        link.unlink()
        proof.chmod(0o644)
        self.assertIn('unsafe_file', self.inspect()['records'][0]['issues'])
        proof.unlink()
        os.mkfifo(proof, 0o600)
        self.assertIn('unsafe_file', self.inspect()['records'][0]['issues'])
        self.directory.chmod(0o777)
        self.assertEqual(self.inspect()['status'], 'unknown')

    def test_real_writer_lock_busy_is_immediate_unknown(self):
        self.enqueue()
        with api._locked(self.flag):
            result = self.inspect()
        self.assertEqual(result['status'], 'unknown')
        self.assertEqual(result['inspection_status'], 'unavailable')

    def test_inplace_mutation_and_replacement_during_read(self):
        row = self.enqueue()
        path = self.directory / (row['id'] + '.json')
        original = api._inspect_regular
        for replacement in (False, True):
            self.change(row)
            changed = False
            def mutate(info, private=True):
                nonlocal changed
                original(info, private)
                if private and not changed:
                    changed = True
                    if replacement:
                        alternate = self.home / 'alternate'
                        alternate.write_text(path.read_text())
                        alternate.chmod(0o600)
                        os.replace(alternate, path)
                    else:
                        path.write_text(path.read_text() + ' ')
            with patch.object(api, '_inspect_regular', side_effect=mutate):
                result = self.inspect()
            self.assertEqual(result['status'], 'unknown')
            self.assertIn('changed_during_read', result['records'][0]['issues'])

    def test_record_replaced_after_read_is_unknown(self):
        row = self.enqueue()
        original = api._inspect_row
        def replace_after(*args):
            result = original(*args)
            api.atomic_write_json(self.directory / (row['id'] + '.json'), row, mode=0o600)
            return result
        with patch.object(api, '_inspect_row', side_effect=replace_after):
            result = self.inspect()
        self.assertEqual(result['status'], 'unknown')
        self.assertIn('changed_during_inspection', result['issues'])

    def test_directory_swapped_after_read_is_unknown(self):
        self.enqueue()
        original = api._inspect_row
        def swap(*args):
            result = original(*args)
            self.directory.rename(self.home / 'moved')
            self.directory.mkdir(mode=0o700)
            return result
        with patch.object(api, '_inspect_row', side_effect=swap):
            result = self.inspect()
        self.assertEqual(result['status'], 'unknown')

    def test_retired_proof_reappearing_is_unknown(self):
        row = self.terminal()
        original = api._inspect_row
        def reappear(*args):
            result = original(*args)
            Path(row['proof_path']).write_bytes(b'changed')
            return result
        with patch.object(api, '_inspect_row', side_effect=reappear):
            result = self.inspect()
        self.assertEqual(result['status'], 'unknown')

    def test_scalar_projection_is_private_free_and_bounded(self):
        self.enqueue()
        report = self.inspect()
        summary = api.project_observation(report)
        self.assertEqual(summary, report['summary'])
        self.assertLessEqual(len(summary), 20)
        for key, value in summary.items():
            self.assertFalse(any(word in key for word in ('path', 'log', 'email', 'env', 'token')))
            self.assertTrue(value is None or type(value) in (str, int, float, bool))
            if isinstance(value, str):
                self.assertLessEqual(len(value), 400)
                self.assertNotIn('/', value)
                self.assertNotIn('\\', value)

    def test_cli_under_audit_guard_no_writes_network_or_subprocess(self):
        self.enqueue()
        guard = r'''
import os,runpy,sys
sys.dont_write_bytecode=True
sys.path.insert(0,sys.argv[1])
def audit(event,args):
    if event.startswith('socket.') or event in ('subprocess.Popen','os.system','os.posix_spawn','os.fork','os.exec'):
        raise AssertionError(event)
    if event in ('os.mkdir','os.remove','os.rename','os.chmod','os.link','os.symlink','os.truncate','os.utime'):
        raise AssertionError(event)
    if event=='open':
        name,mode,flags=args
        if isinstance(flags,int) and flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND):
            raise AssertionError('write')
sys.addaudithook(audit)
script=sys.argv[1]+'/r2_pending_context.py'
sys.argv=[script,'inspect']
runpy.run_path(script,run_name='__main__')
'''
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', REPO=str(self.home),
                   R2_UPLOAD_ASYNC_PENDING=str(self.flag))
        # CLI root convention is REPO/static-site; inspect our actual root through that convention.
        self.root.rename(self.home / 'static-site')
        # Register the canonical CLI root without mutating an existing request identity.
        self.enqueue('cli', root=self.home / 'static-site')
        before = self.fingerprint()
        result = subprocess.run([sys.executable, '-c', guard, str(SCRIPTS)], env=env,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'unknown')
        self.assertEqual(before, self.fingerprint())
        (self.directory / '.lock').unlink()
        result = subprocess.run([sys.executable, '-c', guard, str(SCRIPTS)], env=env,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'unknown')


if __name__ == '__main__':
    unittest.main()
