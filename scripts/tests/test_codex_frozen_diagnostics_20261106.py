"""真实guard函数的零外发隔离测试; 只在临时目录写诊断, 不运行业务主体。"""
import ast
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
from datetime import datetime

SOURCE = Path(os.environ.get('FROZEN_DIAGNOSTICS_SOURCE',
                             str(Path(__file__).resolve().parents[1] / 'signal_kelly_backtest.py')))
ATOMIC = Path(os.environ.get('FROZEN_DIAGNOSTICS_ATOMIC',
                             str(Path(__file__).resolve().parents[1] / 'util_atomic.py')))


class FrozenDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.calls = []
        self.err = io.StringIO()
        self.traps = []
        self.patches = contextlib.ExitStack()
        self.addCleanup(self.patches.close)
        def forbidden(*args, **kwargs):
            self.traps.append('outbound')
            raise AssertionError('真实网络/子进程被阻止')
        self.forbidden = forbidden
        self.patches.enter_context(patch.object(socket.socket, 'connect', forbidden))
        self.patches.enter_context(patch.object(subprocess, 'run', forbidden))
        fake = types.ModuleType('app.notify_hook')
        fake.send_alert = self.send_alert
        self.patches.enter_context(patch.dict(sys.modules, {'app.notify_hook': fake}))
        spec = importlib.util.spec_from_file_location('frozen_test_atomic', ATOMIC)
        atomic = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(atomic)
        names = {'_archive_frozen_missing_diagnostics', '_alert_frozen_missing',
                 '_load_frozen_missing_accepted', '_etf_freeze_path'}
        tree = ast.parse(SOURCE.read_text())
        self.ns = {'__file__': str(SOURCE), 'ROOT': str(self.root), 'os': os,
                   'sys': sys, 'json': json, 'datetime': datetime,
                   'atomic_write_json': atomic.atomic_write_json,
                   'FROZEN_MISSING_SEVERE_THRESHOLD': 10, 'KELLY_BUY_NEXTDAY': 1,
                   'ETF_FREEZE_PATH_ENV': 'SIGNAL_KELLY_ETF_FREEZE_PATH',
                   'FROZEN_MISSING_ACCEPTED_PATH': str(self.root / 'accepted.json')}
        exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef)
                                     and n.name in names], type_ignores=[]), str(SOURCE), 'exec'), self.ns)
        self.accepted = [('20260922', 'sz_div', 'buy')]
        self.events = {('20120517', f'candidate_{n:03d}', 'buy_aux') for n in range(118)}
        self.set_accepted(self.accepted)
        self.freeze = self.root / 'freeze.json'
        self.freeze.write_text('{"historical":"unchanged"}')
        self.freeze_before = self.freeze.read_bytes()
        self.patches.enter_context(patch.dict(os.environ, {'SIGNAL_KELLY_ETF_FREEZE_PATH': str(self.freeze)}))
        self.addCleanup(self.check_no_business_change)

    def check_no_business_change(self):
        self.assertEqual(self.freeze.read_bytes(), self.freeze_before)
        self.assertEqual(self.traps, [])

    def set_accepted(self, rows):
        (self.root / 'accepted.json').write_text(json.dumps({'accepted': ['|'.join(x) for x in rows]}))

    def send_alert(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return types.SimpleNamespace(rc=0, route='stubbed')

    def alert(self, events):
        before = (self.root / 'accepted.json').read_bytes()
        with contextlib.redirect_stderr(self.err):
            result = self.ns['_alert_frozen_missing'](events)
        self.assertEqual((self.root / 'accepted.json').read_bytes(), before)
        return result

    def files(self):
        return sorted((self.root / 'data/audit/frozen_missing').glob('*.json'))

    def test_full_118_and_exact_accepted(self):
        accepted = [('20260922', f'accepted_{i}', 'buy') for i in range(8)]
        self.set_accepted(accepted)
        self.assertIsNone(self.alert(self.events | set(accepted)))
        self.assertEqual(len(self.calls), 1)
        p, = self.files()
        data = json.loads(p.read_text())
        self.assertEqual(data['metadata_count'], 118)
        self.assertEqual(data['filtered_missing'], ['|'.join(x) for x in sorted(self.events)])
        self.assertEqual(data['accepted_hits'], ['|'.join(x) for x in sorted(accepted)])
        self.assertEqual(data['accepted_hit_count'], 8)
        self.assertEqual(data['freeze_path'], str(self.freeze.resolve()))
        self.assertEqual(data['hashes']['source_file_sha256_at_archive'], hashlib.sha256(SOURCE.read_bytes()).hexdigest())
        self.assertEqual(data['hashes']['signal_input_sha256'], 'unknown')
        args, kw = self.calls[0]
        sample = '; '.join('|'.join(x) for x in sorted(self.events)[:5])
        self.assertEqual(args, ('[kelly] 冻结表缺失历史信号事件 118 个',
            '回测拒绝补冻历史信号事件 118 个(冻结分时点防御闸触发)。'
            '冻结表缺失 118 个历史信号事件, 拒绝补冻已跳过, 请核查生产冻结流程。样例: ' + sample))
        self.assertEqual(kw, dict(dedup_key='signal_kelly_frozen_missing', dedup_window=3600,
            severe=True, from_prefix='[kelly]', feishu_group='alert', defer_digest=False,
            digest_category=None))
        self.assertNotIn(data['run_id'], ''.join(args))
        self.assertNotIn(str(p), ''.join(args))

    def test_no_events_or_all_accepted_write_nothing(self):
        self.alert(set())
        self.alert(set(self.accepted))
        self.assertEqual(self.files(), [])
        self.assertEqual(self.calls, [])
        self.assertFalse((self.root / 'data').exists())

    def test_accepted_exact_boundary_and_severity(self):
        original = self.accepted[0]
        changed = (original[0], original[1], 'buy_aux')
        self.alert({original, changed})
        d = json.loads(self.files()[0].read_text())
        self.assertEqual(d['filtered_missing'], ['|'.join(changed)])
        self.assertFalse(self.calls[-1][1]['severe'])
        self.assertTrue(self.calls[-1][1]['defer_digest'])
        self.assertEqual(self.calls[-1][1]['digest_category'], 'kelly_frozen_missing')
        self.alert(set(sorted(self.events)[:10]))
        self.assertTrue(self.calls[-1][1]['severe'])

    def test_repeat_never_overwrites(self):
        self.alert(self.events)
        old, = self.files()
        before = old.read_bytes()
        self.alert(self.events)
        self.assertEqual(len(self.files()), 2)
        self.assertEqual(old.read_bytes(), before)
        self.assertEqual(self.calls[0], self.calls[1])

    def test_uuid_collision_keeps_old_and_still_notifies(self):
        with patch('uuid.uuid4', return_value=types.SimpleNamespace(hex='fixed-run')):
            self.alert(self.events)
            old, = self.files()
            before = old.read_bytes()
            self.err.truncate(0); self.err.seek(0)
            self.alert(self.events)
        self.assertEqual(old.read_bytes(), before)
        self.assertEqual(len(self.files()), 1)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.err.getvalue().count('诊断归档失败'), 1)

    def test_write_failure_keeps_notification_and_return(self):
        def fail(*a, **k):
            raise PermissionError('injected')
        self.ns['atomic_write_json'] = fail
        self.assertIsNone(self.alert(self.events))
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.files(), [])
        self.assertEqual(self.err.getvalue().count('诊断归档失败'), 1)

    def test_override_mode_and_unknown_code_do_not_read_freeze(self):
        link = self.root / 'override-link.json'
        link.symlink_to(self.freeze)
        self.patches.enter_context(patch.dict(os.environ, {'SIGNAL_KELLY_ETF_FREEZE_PATH': str(link)}))
        self.ns['KELLY_BUY_NEXTDAY'] = 0
        self.ns['__file__'] = str(self.root / 'absent-code.py')
        self.alert(self.events)
        d = json.loads(self.files()[0].read_text())
        self.assertEqual(d['mode']['buy_price_basis'], 'signal_day_close')
        self.assertEqual(d['hashes']['source_file_sha256_at_archive'], 'unknown')
        self.assertEqual(d['freeze_path'], str(self.freeze.resolve()))

    def test_archive_failure_and_send_failure_keep_old_exit_behavior(self):
        self.ns['atomic_write_json'] = lambda *a, **k: (_ for _ in ()).throw(OSError('full'))
        module = sys.modules['app.notify_hook']
        module.send_alert = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('send stub failure'))
        self.assertIsNone(self.alert(self.events))
        self.assertEqual(self.err.getvalue().count('诊断归档失败'), 1)
        self.assertIn('冻结缺失告警调用异常: send stub failure', self.err.getvalue())

    def test_publication_sees_only_complete_json(self):
        real_link = os.link
        published = []
        def inspect_link(source, target):
            self.assertFalse(Path(target).exists())
            data = json.loads(Path(source).read_text())
            self.assertEqual(len(data['filtered_missing']), 118)
            self.assertEqual(data['metadata_count'], 118)
            self.assertEqual(Path(source).stat().st_mode & 0o777, 0o600)
            real_link(source, target)
            published.append(Path(target))
        with patch.object(os, 'link', inspect_link):
            self.alert(self.events)
        self.assertEqual(published, self.files())
        self.assertEqual(len(published), 1)

    def test_zero_outbound_positive_control(self):
        # 真实connect方法已替换; 正控只触达陷阱, 没有建立网络连接。
        with self.assertRaises(AssertionError):
            with socket.socket() as sock:
                sock.connect(('127.0.0.1', 1))
        self.assertEqual(self.traps, ['outbound'])
        self.traps.clear()
