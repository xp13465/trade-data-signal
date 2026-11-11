#!/usr/bin/env python3
"""隔离临时repo/文件；不导入业务notify，不使用网络或生产数据。"""
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
def load(name):
    spec=importlib.util.spec_from_file_location(name,HERE/(name+'.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module
m=load('history-cleanup');s=load('history-cleanup-scan');d=load('history-cleanup-date-index')


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name).resolve();self.root=self.base/'source';self.root.mkdir()

    def test_restore_all_bytes_permissions_symlinks_empty_dir(self):
        (self.root/'private').mkdir(mode=0o700)
        (self.root/'private/a').write_bytes(b'original\x00bytes');(self.root/'private/a').chmod(0o640)
        (self.root/'relative').symlink_to('private/a');(self.root/'absolute').symlink_to('/not-readable/outside')
        (self.root/'empty').mkdir(mode=0o750)
        names=['private','private/a','relative','absolute','empty']
        manifest,receipt=m.backup_restore(self.root,names,self.base/'archive')
        self.assertTrue(receipt['restore_verified'])
        self.assertEqual(manifest,m.manifest(self.base/'archive/restore-check',names))
        self.assertEqual((self.base/'archive/payload.tar').stat().st_mode&0o777,0o600)

    def test_reject_symlink_parent(self):
        (self.root/'link').symlink_to(self.base)
        with self.assertRaises(ValueError):m.manifest(self.root,['link/file'])

    def malicious(self,name,raw,expected):
        archive=self.base/'bad.tar'
        with tarfile.open(archive,'w') as t:
            info=tarfile.TarInfo(name);info.size=len(raw);t.addfile(info,io.BytesIO(raw))
        target=self.base/'restore';target.mkdir()
        with self.assertRaises((ValueError,RuntimeError)):m.restore_archive(archive,target,expected)

    def test_restore_traversal_rejected(self):
        self.malicious('../outside',b'bad',{})
        self.assertFalse((self.base/'outside').exists())

    def test_restore_corrupt_bytes_rejected(self):
        (self.root/'a').write_bytes(b'good')
        self.malicious('a',b'evil',m.manifest(self.root,['a']))

    def test_restore_missing_member_rejected(self):
        archive=self.base/'empty.tar'
        with tarfile.open(archive,'w'):pass
        (self.root/'a').write_bytes(b'a');target=self.base/'restore';target.mkdir()
        with self.assertRaises(RuntimeError):m.restore_archive(archive,target,m.manifest(self.root,['a']))

    def test_restore_nonempty_destination_rejected(self):
        (self.root/'a').write_bytes(b'a')
        with self.assertRaises(ValueError):m.restore_archive(self.base/'none',self.root,{})

    def test_restore_failure_prevents_verified_receipt(self):
        (self.root/'a').write_bytes(b'a')
        with patch.object(m,'restore_archive',side_effect=RuntimeError('injected restore failure')):
            with self.assertRaises(RuntimeError):m.backup_restore(self.root,['a'],self.base/'archive')
        self.assertFalse((self.base/'archive/verified.json').exists())
        self.assertEqual((self.root/'a').read_bytes(),b'a')


class AlertTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name).resolve();self.tree=self.base/m.ALERT_TREE
        alerts=self.tree/'data/alerts';alerts.mkdir(parents=True)
        self.latest=alerts/'latest.md'
        self.prefix=b'# Real original preface\nretain all text\n\n'
        self.block=b'---\n## [digest] 2026-11-10 09:18:09 test\n- test:h_existing\n'
        self.raw=self.prefix+self.block*3;self.latest.write_bytes(self.raw);self.latest.chmod(0o640)
        self.ledger=alerts/'suppression_ledger.jsonl';self.ledger.write_bytes(b'{"real":"ledger"}\n')
        self.ledger_before=m.manifest(self.tree,['data/alerts/suppression_ledger.jsonl'])
        self.dest=self.base/'backup'
        for p in [patch.object(m,'TREES',self.base),patch.object(m,'ALERT_HASH',m.sha(self.raw)),patch.object(m,'guard',return_value={'test_guard':True})]:
            p.start();self.addCleanup(p.stop)

    def test_dry_run_zero_write(self):
        result=m.quarantine(self.tree,self.dest)
        self.assertEqual(result['retain_prefix_bytes'],len(self.prefix))
        self.assertFalse(self.dest.exists());self.assertEqual(self.latest.read_bytes(),self.raw)
        self.assertFalse((self.latest.parent/'.latest.lock').exists())

    def test_apply_preserves_preface_ledger_mode_and_restores_original(self):
        r=m.quarantine(self.tree,self.dest,apply=True)
        self.assertTrue(r['applied']);self.assertEqual(self.latest.read_bytes(),self.prefix)
        self.assertEqual(self.latest.stat().st_mode&0o777,0o640)
        self.assertEqual(m.manifest(self.tree,self.ledger_before),self.ledger_before)
        self.assertEqual((self.dest/'restore-check/data/alerts/latest.md').read_bytes(),self.raw)
        self.assertEqual((self.dest/'removed-blocks.md').read_bytes(),self.block*3)

    def test_reject_changed_hash_without_write(self):
        changed=self.raw+b'actual alert';self.latest.write_bytes(changed)
        with self.assertRaises(ValueError):m.quarantine(self.tree,self.dest,apply=True)
        self.assertEqual(self.latest.read_bytes(),changed);self.assertFalse(self.dest.exists())

    def test_real_severe_blocks_never_deleted(self):
        changed=self.raw+b'---\n## [severe] 2026-11-10 actual production\nKEEP\n'
        self.latest.write_bytes(changed)
        with patch.object(m,'ALERT_HASH',m.sha(changed)):
            with self.assertRaises(ValueError):m.quarantine(self.tree,self.dest,apply=True)
        self.assertEqual(self.latest.read_bytes(),changed)

    def test_wrong_date_not_keyword_match(self):
        changed=self.raw.replace(b'09:18:09',b'09:18:10');self.latest.write_bytes(changed)
        with patch.object(m,'ALERT_HASH',m.sha(changed)):
            with self.assertRaises(ValueError):m.quarantine(self.tree,self.dest,apply=True)

    def test_restore_failure_prevents_alert_write(self):
        with patch.object(m,'restore_archive',side_effect=RuntimeError('restore failure')):
            with self.assertRaises(RuntimeError):m.quarantine(self.tree,self.dest,apply=True)
        self.assertEqual(self.latest.read_bytes(),self.raw)

    def test_cas_blocks_late_change(self):
        real=m.backup_restore
        def change(*a,**kw):
            result=real(*a,**kw);self.latest.write_bytes(self.raw+b'NEW REAL ALERT');return result
        with patch.object(m,'backup_restore',side_effect=change):
            with self.assertRaises(RuntimeError):m.quarantine(self.tree,self.dest,apply=True)
        self.assertEqual(self.latest.read_bytes(),self.raw+b'NEW REAL ALERT')

    def test_ledger_change_stops_quarantine(self):
        real=m.backup_restore
        def change(*a,**kw):
            result=real(*a,**kw);self.ledger.write_bytes(b'new real ledger');return result
        with patch.object(m,'backup_restore',side_effect=change):
            with self.assertRaises(RuntimeError):m.quarantine(self.tree,self.dest,apply=True)
        self.assertEqual(self.latest.read_bytes(),self.raw)

    def test_active_guard_stops_before_backup(self):
        with patch.object(m,'guard',side_effect=RuntimeError('writer active')):
            with self.assertRaises(RuntimeError):m.quarantine(self.tree,self.dest,apply=True)
        self.assertFalse(self.dest.exists());self.assertEqual(self.latest.read_bytes(),self.raw)

    def test_repeat_apply_refuses_and_keeps_preface(self):
        m.quarantine(self.tree,self.dest,apply=True)
        with self.assertRaises(ValueError):m.quarantine(self.tree,self.base/'again',apply=True)
        self.assertEqual(self.latest.read_bytes(),self.prefix)

    def test_symlink_lock_cannot_modify_outside_target(self):
        external=self.base/'outside';external.write_bytes(b'outside')
        (self.latest.parent/'.latest.lock').symlink_to(external)
        with self.assertRaisesRegex(ValueError,'lock不能'):m.quarantine(self.tree,self.dest,apply=True)
        self.assertEqual(external.read_bytes(),b'outside');self.assertEqual(self.latest.read_bytes(),self.raw)


class WorktreeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name).resolve();self.repo=self.base/'repo';self.repo.mkdir()
        m.git(self.repo,'init','-b','main');m.git(self.repo,'config','user.name','Isolated Test')
        m.git(self.repo,'config','user.email','isolated@example.invalid')
        m.git(self.repo,'config','core.hooksPath','/dev/null')
        (self.repo/'.gitignore').write_text('cache/\n');(self.repo/'tracked').write_text('kept')
        m.git(self.repo,'add','.');m.git(self.repo,'commit','-m','isolated fixture')
        self.head=m.git(self.repo,'rev-parse','HEAD').decode().strip()
        self.tree=self.base/'trees/codex-completed';m.git(self.repo,'worktree','add','-b','codex/completed',str(self.tree))
        (self.tree/'cache/empty').mkdir(parents=True);(self.tree/'cache/private').write_bytes(b'ignored original')
        (self.tree/'cache/symlink').symlink_to('private')
        self.dest=self.base/'backup';self.packets=self.base/'packets';self.packets.mkdir()
        for p in [patch.object(m,'REPO',self.repo),patch.object(m,'TREES',self.tree.parent),patch.object(m,'ALLOWED',{self.tree.name:self.head}),
                  patch.object(m,'PACKETS',self.packets),patch.object(m,'inactive'),
                  patch.object(m,'completion_evidence',return_value={'completion_evidence':'isolated reviewed receipt'})]:
            p.start();self.addCleanup(p.stop)

    def test_dryrun_retains_tree_ref_and_ignored(self):
        r=m.remove_worktree(self.tree,self.dest)
        self.assertIn('cache/empty',r['ignored']);self.assertIn('cache/symlink',r['ignored'])
        self.assertTrue(self.tree.exists());self.assertFalse(self.dest.exists())

    def test_normal_remove_keeps_branch_and_verified_ignored_restore(self):
        r=m.remove_worktree(self.tree,self.dest,apply=True)
        self.assertFalse(self.tree.exists());self.assertTrue(r['branch_retained'])
        self.assertEqual(m.git(self.repo,'rev-parse','codex/completed').decode().strip(),self.head)
        self.assertEqual((self.dest/'restore-check/cache/private').read_bytes(),b'ignored original')
        self.assertEqual(os.readlink(self.dest/'restore-check/cache/symlink'),'private')
        self.assertTrue((self.dest/'restore-check/cache/empty').is_dir())

    def test_dirty_retained(self):
        (self.tree/'tracked').write_text('dirty')
        with self.assertRaisesRegex(RuntimeError,'dirty/untracked'):m.remove_worktree(self.tree,self.dest,apply=True)
        self.assertFalse(self.dest.exists());self.assertTrue(self.tree.exists())

    def test_untracked_retained(self):
        (self.tree/'untracked').write_text('real untracked')
        with self.assertRaisesRegex(RuntimeError,'dirty/untracked'):m.remove_worktree(self.tree,self.dest,apply=True)

    def test_locked_retained(self):
        m.git(self.repo,'worktree','lock',str(self.tree))
        with self.assertRaisesRegex(RuntimeError,'登记/锁'):m.remove_worktree(self.tree,self.dest,apply=True)

    def test_new_head_retained(self):
        (self.tree/'tracked').write_text('changed');m.git(self.tree,'commit','-am','different head')
        with self.assertRaisesRegex(RuntimeError,'head变化'):m.remove_worktree(self.tree,self.dest,apply=True)

    def test_unmerged_head_retained(self):
        (self.tree/'tracked').write_text('changed');m.git(self.tree,'commit','-am','unmerged')
        with patch.object(m,'ALLOWED',{self.tree.name:m.git(self.tree,'rev-parse','HEAD').decode().strip()}):
            with self.assertRaises(RuntimeError):m.remove_worktree(self.tree,self.dest,apply=True)

    def test_owner_unknown_retained(self):
        with patch.object(m,'completion_evidence',side_effect=ValueError('no ownership completion evidence')):
            with self.assertRaises(ValueError):m.remove_worktree(self.tree,self.dest,apply=True)
        self.assertFalse(self.dest.exists())

    def test_final_packet_nested_ref_retained(self):
        (self.packets/'final.json').write_text(json.dumps({'code_ref':{'head':self.head}}))
        with self.assertRaises(ValueError):m.remove_worktree(self.tree,self.dest,apply=True)

    def test_nonallowlisted_tree_retained(self):
        with patch.object(m,'ALLOWED',{}):
            with self.assertRaisesRegex(ValueError,'非批准'):m.remove_worktree(self.tree,self.dest,apply=True)
        self.assertFalse(self.dest.exists())

    def test_restore_failure_prevents_remove(self):
        with patch.object(m,'restore_archive',side_effect=RuntimeError('restore failed')):
            with self.assertRaisesRegex(RuntimeError,'restore failed|二次核验'):m.remove_worktree(self.tree,self.dest,apply=True)
        self.assertTrue(self.tree.exists())

    def test_second_check_detects_ignored_change(self):
        real=m.backup_restore
        def change(*a,**kw):
            r=real(*a,**kw);(self.tree/'cache/private').write_bytes(b'new data');return r
        with patch.object(m,'backup_restore',side_effect=change):
            with self.assertRaisesRegex(RuntimeError,'restore failed|二次核验'):m.remove_worktree(self.tree,self.dest,apply=True)
        self.assertTrue(self.tree.exists())


class ReadonlyTests(unittest.TestCase):
    def test_actual_open_handle_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'writer';p.write_bytes(b'x')
            with p.open('ab'):
                with self.assertRaises(RuntimeError):m.inactive(Path(tmp))

    def test_command_timeout_collected(self):
        with self.assertRaises(subprocess.TimeoutExpired):m.command([sys.executable,'-c','import time;time.sleep(5)'],timeout=.1)

    def test_actual_cwd_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=subprocess.Popen([sys.executable,'-c','import signal,time;signal.alarm(4);print("ready",flush=True);time.sleep(3)'],cwd=tmp,stdout=subprocess.PIPE)
            try:
                self.assertEqual(p.stdout.readline().strip(),b'ready')
                with self.assertRaises(RuntimeError):m.inactive(Path(tmp))
            finally:
                p.kill();p.communicate(timeout=5)

    def test_mentions_are_not_originals(self):
        data=s.inspect(json.dumps({'missing':s.KEYS,'generated_at':'2026-11-11'}).encode())
        self.assertEqual(data['mentions'],s.KEYS);self.assertEqual(data['candidate_records'],{})
        self.assertEqual(data['source_time'],{'generated_at':'2026-11-11'})

    def test_candidate_still_requires_authenticity_review(self):
        data=s.inspect(json.dumps({'entries':{s.KEYS[0]:{'rating':1}},'frozen_at':'2026-11-04'}).encode())
        self.assertEqual(set(data['candidate_records']),{s.KEYS[0]})

    def test_bounded_scan_and_source_times(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'freeze.json';p.write_text('{"entries":[]}')
            r=s.scan([str(p)]*202)
            self.assertEqual(r['candidates_omitted_by_limit'],2);self.assertEqual(len(r['files']),200)
            self.assertIn('mtime_ns',r['files'][0]);self.assertEqual(r['files'][0]['source_time'],{})
            with patch.object(s,'MAX_FILE',1):self.assertEqual(s.scan([str(p)])['files'],[])

    def test_archive_scans_without_extracting(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'history.tar'
            raw=json.dumps({'missing':s.KEYS}).encode()
            with tarfile.open(p,'w') as t:
                info=tarfile.TarInfo('../frozen.json');info.size=len(raw);info.mtime=1793779200
                t.addfile(info,io.BytesIO(raw))
            r=s.scan([str(p)])
            self.assertTrue(r['archives'][0]['complete_listing'])
            self.assertEqual(r['archives'][0]['members'][0]['candidate_records'],{})
            self.assertEqual(sorted(x.name for x in Path(tmp).iterdir()),['history.tar'])

    def test_date_index_distinguishes_exact_and_same_date_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'freeze_20261104.json'
            alternative='20261104|csi_000102|buy_special'
            p.write_text(json.dumps({'entries':{alternative:{'synthetic':True}},'created_at':'2026-11-04'}))
            r=d.run([tmp],[])
            self.assertEqual(r['files'][0]['exact_candidates'],{})
            self.assertEqual(r['files'][0]['date_index_keys'][d.KEYS[0]],[alternative])
            self.assertEqual(r['files'][0]['source_time'],{'created_at':'2026-11-04'})


if __name__=='__main__':
    signal.alarm(100)
    unittest.main(verbosity=2)
