"""Disk-backed export/boot contract tests; no business imports, DB or R2 IO.

Only original function ASTs execute. Query results are synthetic; export_boot
reads/writes real temporary JSON files. Upload captures the files at the gate.
"""
import ast
from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).absolute().parents[2]
RANGES = ('3m', '6m', '1y', '3y', '5y', 'all')
FILES = ['overview.json', 'boot.json', 'signals_today.json'] + [
    f'a-stock-{rng}.json' for rng in RANGES
]
OVERVIEW = {
    'date': '2026-11-06',
    'today': {'metrics': {'a_bj_width_up_ratio': 0.73}},
    'a_bj_width_up_ratio_6m': [0.41, 0.73],
    'signals_today': [{'code': 'fixture', 'signal': 'buy'}],
    'signals_meta': {'generated_at': 'new-round', 'count': 1},
}


def functions(path, names, namespace):
    """Do not import export.py: its top-level imports connect business modules."""
    tree = ast.parse((ROOT / path).read_text(encoding='utf-8'))
    selected = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    if {n.name for n in selected} != set(names):
        raise AssertionError('original functions missing: ' + path)
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(ROOT / path), 'exec'), namespace)
    return namespace


class BootContractTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='fapi-boot-contract-')
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name)
        self.uploads = []
        self.ranges = []
        self.boot_calls = 0
        self.fault = None
        self.conn, self.cfg = object(), object()
        # Stale files already on disk must not pass as this round's outputs.
        for name in FILES:
            self.write(self.data / name, {'stale': True})
        self.boot_ns = functions('static-site/export.py', {'export_boot'}, {
            'DATA_DIR': self.data, 'json': json, 'write_json': self.write,
            'load_site_config': lambda: {'fixture_config': True},
        })
        exp = SimpleNamespace(
            DATA_DIR=self.data, EXPORT_RANGES=RANGES, write_json=self.write,
            export_overview=self.overview, export_a_stock=self.a_stock,
            export_boot=self.boot, load_config=lambda: self.cfg,
            get_conn=lambda: self.conn,
        )
        self.run_ns = functions('scripts/fapi_bj_width_export.py', {'_export_products', 'main'}, {
            'exp': exp, 'json': json, 'sys': SimpleNamespace(argv=['fixture']),
            'REPO': self.data, '_now': lambda: 'fixture', '_upload_r2': self.upload,
        })

    def write(self, path, payload):
        if self.fault == 'signals_soft_failure' and path.name == 'signals_today.json':
            raise OSError('synthetic signals write failure')
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
        return path.stat().st_size

    def read(self, name):
        return json.loads((self.data / name).read_text(encoding='utf-8'))

    def overview(self, conn, cfg):
        self.assertIs(conn, self.conn)
        self.assertIs(cfg, self.cfg)
        if self.fault == 'overview_exception':
            raise ValueError('synthetic query failure')
        return deepcopy(OVERVIEW)

    def a_stock(self, conn, cfg, rng):
        self.assertIs(conn, self.conn)
        self.assertIs(cfg, self.cfg)
        self.ranges.append(rng)
        if self.fault == 'range_exception:' + rng:
            raise ValueError('synthetic range query failure')
        return {'range': rng, 'metrics': {'a_bj_width_up_ratio': [0.41, 0.73]}}

    def boot(self):
        self.boot_calls += 1
        if self.fault == 'boot_exception':
            raise OSError('synthetic boot failure')
        if self.fault == 'boot_silent_noop':
            return None  # Both stale derived files remain, without an exception.
        result = self.boot_ns['export_boot']()
        if self.fault in ('boot_missing', 'signals_missing'):
            (self.data / ('boot.json' if self.fault == 'boot_missing' else 'signals_today.json')).unlink()
        elif self.fault and self.fault.startswith('boot_mismatch:'):
            payload = self.read('boot.json')
            field = self.fault.split(':')[1]
            if field == 'signals_today':
                payload['overview'][field] = deepcopy(OVERVIEW[field])
            else:
                payload['overview'][field] = 'stale'
            self.write(self.data / 'boot.json', payload)
        elif self.fault and self.fault.startswith('signals_mismatch:'):
            payload = self.read('signals_today.json')
            payload[self.fault.split(':')[1]] = 'stale'
            self.write(self.data / 'signals_today.json', payload)
        return result

    def upload(self, files):
        # Capture actual serialized outputs, not merely a mock call count.
        self.uploads.append((list(files), {name: self.read(name) for name in files}))
        return True

    def run_export(self, no_upload=False):
        self.run_ns['sys'].argv = ['fixture'] + (['--no-upload'] if no_upload else [])
        self.output = io.StringIO()
        with redirect_stdout(self.output):
            return self.run_ns['main']()

    def assert_products(self):
        self.assertEqual(self.read('overview.json'), OVERVIEW)
        expected = deepcopy(OVERVIEW)
        del expected['signals_today']
        boot = self.read('boot.json')
        self.assertEqual(boot['overview'], expected)
        self.assertNotIn('signals_today', boot['overview'])
        self.assertEqual(boot['config'], {'fixture_config': True})
        self.assertEqual(self.read('signals_today.json'), {
            key: OVERVIEW[key] for key in ('date', 'signals_today', 'signals_meta')
        })
        for rng in RANGES:
            self.assertEqual(self.read(f'a-stock-{rng}.json'), {
                'range': rng, 'metrics': {'a_bj_width_up_ratio': [0.41, 0.73]}
            })
        self.assertEqual(set(p.name for p in self.data.iterdir()), set(FILES))
        self.assertEqual(self.ranges, list(RANGES))

    def test_success_uploads_exact_nine_current_products(self):
        self.assertEqual(self.run_export(), 0)
        self.assert_products()
        self.assertEqual(self.boot_calls, 1)
        self.assertEqual(len(self.uploads), 1)
        names, payloads = self.uploads[0]
        self.assertEqual(names, FILES)
        self.assertEqual(len(set(names)), 9)
        self.assertEqual(payloads, {name: self.read(name) for name in FILES})

    def test_no_upload_still_writes_all_nine_products(self):
        self.assertEqual(self.run_export(no_upload=True), 0)
        self.assert_products()
        self.assertEqual(self.boot_calls, 1)
        self.assertEqual(self.uploads, [])

    def assert_blocked(self, fault, no_upload=False):
        self.fault = fault
        self.assertEqual(self.run_export(no_upload=no_upload), 1, fault)
        self.assertEqual(self.uploads, [], fault)
        self.assertIn('不上传 R2', self.output.getvalue())

    def test_boot_overview_mismatches_block_upload(self):
        for field in ('date', 'today', 'signals_meta', 'signals_today'):
            with self.subTest(field=field):
                self.assert_blocked('boot_mismatch:' + field)

    def test_signals_mismatches_block_upload(self):
        for field in ('date', 'signals_today', 'signals_meta'):
            with self.subTest(field=field):
                self.assert_blocked('signals_mismatch:' + field)

    def test_missing_derived_products_block_upload(self):
        for fault in ('boot_missing', 'signals_missing'):
            with self.subTest(fault=fault):
                self.assert_blocked(fault)

    def test_real_boot_soft_failure_with_old_signals_blocks_upload(self):
        self.assert_blocked('signals_soft_failure')
        self.assertIn('保留 boot 内嵌副本', self.output.getvalue())
        self.assertEqual(self.read('signals_today.json'), {'stale': True})
        self.assertEqual(self.read('boot.json')['overview']['signals_today'], OVERVIEW['signals_today'])

    def test_silent_noop_cannot_upload_old_derived_products(self):
        self.assert_blocked('boot_silent_noop')
        self.assertEqual(self.read('boot.json'), {'stale': True})

    def test_boot_exception_blocks_upload(self):
        self.assert_blocked('boot_exception')

    def test_original_overview_exception_skips_boot_and_upload(self):
        self.assert_blocked('overview_exception')
        self.assertEqual(self.boot_calls, 0)
        self.assertEqual(self.read('overview.json'), {'stale': True})

    def test_each_original_range_exception_skips_boot_and_upload(self):
        for rng in RANGES:
            with self.subTest(rng=rng):
                self.assert_blocked('range_exception:' + rng)
                self.assertEqual(self.boot_calls, 0)

    def test_no_upload_does_not_hide_contract_failure(self):
        self.assert_blocked('boot_missing', no_upload=True)


if __name__ == '__main__':
    unittest.main()
