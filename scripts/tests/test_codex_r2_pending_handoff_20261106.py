"""Portable actual-shell handoff tests: full uploader CLI, real flock, filesystem-only S3 stub."""
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
ADAPTER = r'''
import ast,hashlib,importlib.util,json,os,sys,time,types
from pathlib import Path
sys.dont_write_bytecode=True
P=Path(os.environ['TEST_ROOT']).resolve();S=P/'source';sys.path.insert(0,str(S/'scripts'))
script,*args=sys.argv[1:];name=Path(script).name
if name in ('with_lock.py','r2_pending_context.py'):
 os.execv(sys.executable,[sys.executable,script]+args)
if name=='test-producer':
 import sqlite3
 from r2_export_proof import write_run_proof,output_record
 from delivery_evidence import capture_loaded
 from util_atomic import atomic_write_text
 ns={'Path':Path,'json':json,'os':os,'sqlite3':sqlite3,'DATA_DIR':S/'static-site/data','STATIC_DIR':S/'static-site','_EXPORT_RUN_OUTPUTS':{},'output_record':output_record,'atomic_write_text':atomic_write_text,'capture_loaded':capture_loaded,'load_site_config':lambda:{}}
 src=(S/'static-site/export.py').read_text();names={'write_json','export_boot','_json_default'}
 exec(compile(ast.Module(body=[n for n in ast.parse(src).body if isinstance(n,ast.FunctionDef) and n.name in names],type_ignores=[]),'actual producer writes','exec'),ns)
 run,extra,*rest=args
 file_run=rest[0] if rest else run
 ns['write_json'](ns['DATA_DIR']/'overview.json',{'run':run})
 ns['export_boot']()
 if extra!='none':ns['write_json'](ns['DATA_DIR']/extra,{'run':file_run})
 Path(os.environ['R2_EXPORT_PROOF_PATH']).parent.mkdir(parents=True,exist_ok=True)
 write_run_proof(os.environ['R2_EXPORT_PROOF_PATH'],run,S/'static-site',ns['_EXPORT_RUN_OUTPUTS']);sys.exit(0)
if name=='notify.py':
 with (P/'notifications.jsonl').open('a') as f:f.write(json.dumps(args)+'\n')
 sys.exit(0)
with (P/'calls.jsonl').open('a') as f:f.write(json.dumps({'name':name,'args':args,'run':os.environ.get('R2_EXPORT_RUN_ID'),'batch':os.environ.get('R2_EXPORT_PENDING_BATCH')})+'\n')
if args==['verify-channels','upload-lab']:
 print('LIGHT_CHECK_PENDING timeout awaiting verification' if os.environ.get('TEST_LIGHT_PENDING') else 'all complete')
 sys.exit(1 if os.environ.get('TEST_LIGHT_PENDING') else 0)
if args!=['upload-all-data']:
 if args==['verify-r2'] and os.environ.get('TEST_VERIFY_BLOCK'):
  (P/'at-verify').touch()
  end=time.monotonic()+10
  while not (P/'release-verify').exists():
   assert time.monotonic()<end,'verify coordination timed out';time.sleep(.01)
 if args==['upload-data-large'] and os.environ.get('TEST_BLOCK_DRAIN') and (P/'at-verify').exists():
  (P/'at-drain').touch();end=time.monotonic()+10
  while not (P/'release-drain').exists():
   assert time.monotonic()<end,'drain coordination timed out';time.sleep(.01)
 sys.exit(0)
# No HTTP, external subprocess, real .env or repository write is permitted inside full business module.
class Forbidden(BaseException):pass
def audit(event,args):
 if event in ('socket.connect','socket.getaddrinfo','subprocess.Popen','os.system','os.posix_spawn'):raise Forbidden(event)
 if event=='open':
  name,mode,flags=args
  if isinstance(name,int):return
  p=Path(name).resolve();write=(isinstance(mode,str) and any(x in mode for x in 'wax+')) or (isinstance(flags,int) and flags&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND))
  if (write or p.name=='.env') and not p.is_relative_to(P):raise Forbidden(str(p))
sys.addaudithook(audit)
old_exists=Path.exists;Path.exists=lambda self:False if self.name=='.env' and not self.resolve().is_relative_to(P) else old_exists(self)
spec=importlib.util.spec_from_file_location('actual_uploader',S/'scripts/upload_r2.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);Path.exists=old_exists
remote=P/'remote';remote.mkdir(exist_ok=True)
def request(method,key,payload=b'',**kw):
 assert method=='PUT';(remote/key.replace('/','__')).write_bytes(payload)
 with (P/'puts.jsonl').open('a') as f:f.write(json.dumps({'key':key,'sha256':hashlib.sha256(payload).hexdigest()})+'\n')
 return 200,b''
def head(key,**kw):
 p=remote/key.replace('/','__')
 if not p.exists():return (404,None,None) if kw.get('with_len') else (404,None)
 b=p.read_bytes();pair=(200,hashlib.md5(b).hexdigest());return pair+(len(b),) if kw.get('with_len') else pair
m.s3_request=request;m.s3_head=head;m.purge_cache=lambda *a:None;m._backup_overwritten_keys=lambda *a,**kw:(0,0,0,[]);m._channel_on_fail=lambda *a:None;m._is_production_writer=lambda:True;m._active_standalone_keys=lambda:{'data/boot.json','data/hk-3m.json','data/global-3m.json'}
node=next(n for n in ast.parse((S/'scripts/upload_r2.py').read_text()).body if isinstance(n,ast.If) and isinstance(n.test,ast.Compare) and any(isinstance(c,ast.Constant) and c.value=='__main__' for c in n.test.comparators))
sys.argv=['upload_r2.py']+args
try:exec(compile(ast.Module(body=node.body,type_ignores=[]),'actual uploader CLI','exec'),m.__dict__)
finally:
 if isinstance(m.__dict__.get('_lock'),int):m._release_r2_upload_lock(m._lock)
# Late request after this final snapshot must remain queued; no result/metadata deletion may erase it.
count=(P/'all-count');ordinal=int(count.read_text())+1 if count.exists() else 1;count.write_text(str(ordinal))
if os.environ.get('TEST_BLOCK_AFTER_ALLDATA')==str(ordinal):
 (P/'after-all-data').touch();end=time.monotonic()+10
 while not (P/'release-all-data').exists():
  assert time.monotonic()<end,'all-data coordination timed out';time.sleep(.01)
'''

class PendingHandoffTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='r2-pending-portable-')
        self.p = Path(self.temp.name).resolve(); self.s = self.p/'source'
        for rel in ['scripts/upload_r2.py','scripts/r2_upload_async.sh','scripts/r2_upload_skip_notify.sh','scripts/r2_pending_context.py','scripts/r2_export_proof.py','scripts/delivery_evidence.py','scripts/r2_lock_paths.py','scripts/util_atomic.py','scripts/with_lock.py','scripts/lib/repo_paths.sh','scripts/lib/upload_watchdog.sh','static-site/export.py']:
            dst=self.s/rel;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/rel,dst)
            if dst.suffix == '.sh': dst.chmod(0o755)
        # Relocate only the lockfile literal, so tests exercise the actual outer exec/timeout safely.
        q=self.s/'scripts/r2_upload_async.sh';q.write_text(q.read_text().replace('/tmp/trade_r2_upload_async.lock',str(self.p/'outer.lock')))
        (self.s/'static-site/data').mkdir();(self.s/'data/logs').mkdir(parents=True)
        (self.p/'bin').mkdir();(self.p/'tmp').mkdir();(self.s/'.venv/bin').mkdir(parents=True)
        (self.p/'adapter.py').write_text(ADAPTER)
        self.py=self.s/'.venv/bin/python';self.py.write_text('#!/bin/bash\nexec '+shlex_quote(sys.executable)+' '+shlex_quote(str(self.p/'adapter.py'))+' "$@"\n');self.py.chmod(0o755)
        sleep=self.p/'bin/sleep';sleep.write_text('#!/bin/bash\nexec /bin/sleep 0.02\n');sleep.chmod(0o755)
        (self.s/'.env').write_text('R2_BUCKET=fixture\nR2_S3_ENDPOINT=https://invalid.example\nR2_S3_ACCESS_KEY_ID=dummy\nR2_S3_SECRET_ACCESS_KEY=dummy\n')
        self.env=dict(os.environ,REPO=str(self.s),GIT_REPO=str(self.s),TEST_ROOT=str(self.p),TMPDIR=str(self.p/'tmp'),PATH=str(self.p/'bin')+':/usr/bin:/bin',R2_UPLOAD_ASYNC_PENDING=str(self.p/'pending'),R2_UPLOAD_LOCK=str(self.p/'global.lock'),R2_UPLOAD_SMALL_LOCK=str(self.p/'small.lock'),ALLOW_FULL_UPLOAD='1',R2_UPLOAD_LOCK_TIMEOUT='1',ASYNC_LOCK_WAIT_SEC='1',R2_UPLOAD_STALL_SECS='60000')
        for k in ['R2_EXPORT_PROOF_PATH','R2_EXPORT_RUN_ID','R2_UPLOAD_ASYNC_LOCKED','R2_EXPORT_PENDING_BATCH','R2_EXPORT_CONTEXT_RESULT_PATH']:self.env.pop(k,None)
        self.children=[];self.logs=[]
    def tearDown(self):
        for child in self.children:
            if child.poll() is None:child.kill();child.wait()
        for stream in self.logs:stream.close()
        self.temp.cleanup()
    def producer(self,run,extra='none',file_run=None):
        env=dict(self.env,R2_EXPORT_PROOF_PATH=str(self.p/f'proof-{run}/proof.json'),R2_EXPORT_RUN_ID=run)
        subprocess.run([str(self.py),'test-producer',run,extra]+([file_run] if file_run else []),env=env,check=True,capture_output=True,timeout=5)
        return env
    def worker(self,env=None,**extra):
        env=dict(self.env if env is None else env,**extra);log=(self.p/f'worker-{len(self.children)}.log').open('w');self.logs.append(log)
        child=subprocess.Popen(['/bin/bash',str(self.s/'scripts/r2_upload_async.sh')],env=env,stdout=log,stderr=subprocess.STDOUT);self.children.append(child);return child
    def wait_file(self,name,child=None):
        end=time.monotonic()+10
        while not (self.p/name).exists():
            if child is not None and child.poll() is not None:self.fail('worker stopped: '+''.join(q.read_text() for q in self.p.glob('worker-*.log')))
            self.assertLess(time.monotonic(),end,'coordination timeout '+name);time.sleep(.01)
    def finish(self,child):
        self.assertEqual(child.wait(timeout=10),0,''.join(q.read_text() for q in self.p.glob('worker-*.log')))
    def remote_run(self,name='boot.json'):
        body=json.loads((self.p/'remote'/('data__'+name)).read_text());return body['overview']['run'] if name=='boot.json' else body['run']
    def records(self):
        directory=Path(str(self.p/'pending')+'.contexts');return [json.loads(q.read_text()) for q in directory.glob('*.json')]
    def helper(self,env,action,*args,check=True):
        return subprocess.run([str(self.py),str(self.s/'scripts/r2_pending_context.py'),action,*args],env=env,capture_output=True,text=True,check=check,timeout=5)
    def test_two_actual_shell_producers_capture_new_proof_before_wait(self):
        a=self.producer('A','hk-3m.json');wa=self.worker(a,TEST_VERIFY_BLOCK='1');self.wait_file('at-verify',wa)
        self.assertEqual(self.remote_run(),'A')
        b=self.producer('B','global-3m.json');wb=self.worker(b);self.finish(wb) # actual with_lock timeout + actual skip hook
        row=next(r for r in self.records() if r['run_id']=='B');self.assertEqual(row['state'],'pending')
        self.assertFalse((self.p/'proof-B').exists());self.assertTrue(Path(row['proof_path']).exists())
        (self.p/'release-verify').touch();self.finish(wa)
        self.assertEqual(self.remote_run(),'B');self.assertEqual(self.remote_run('global-3m.json'),'B')
        self.assertEqual(next(r for r in self.records() if r['run_id']=='B')['state'],'done')
        self.assertEqual(int((self.p/'all-count').read_text()),2)
    def test_old_request_arrives_late_same_run_retry_and_missing_legacy(self):
        a=self.producer('A','hk-3m.json');b=self.producer('B','global-3m.json')
        self.helper(b,'enqueue');self.helper(a,'enqueue');self.helper(b,'enqueue')
        self.assertEqual(len(self.records()),2)
        worker=self.worker();self.finish(worker)
        self.assertEqual(self.remote_run(),'B');self.assertEqual(self.remote_run('global-3m.json'),'B')
        self.assertEqual(next(r for r in self.records() if r['run_id']=='A')['state'],'superseded')
        self.helper(b,'enqueue');self.assertFalse((self.p/'pending').exists())
        bad=dict(self.env,R2_EXPORT_RUN_ID='missing',R2_EXPORT_PROOF_PATH=str(self.p/'gone.json'))
        self.assertNotEqual(self.helper(bad,'enqueue',check=False).returncode,0)
        self.assertEqual(next(r for r in self.records() if r['run_id']=='missing')['state'],'missing')
        # Legacy/no-proof ordinary file still uploads, while a pending placeholder invents no shared proof.
        (self.s/'static-site/data/ordinary.json').write_text('{"run":"legacy"}')
        legacy=self.worker();self.finish(legacy)
        self.assertEqual(json.loads((self.p/'remote/data__ordinary.json').read_text())['run'],'legacy')
        self.assertEqual(next(r for r in self.records() if r['run_id']=='missing')['state'],'missing')
    def test_drain_long_channels_and_final_snapshot_late_arrival(self):
        a=self.producer('A','hk-3m.json');wa=self.worker(a,TEST_VERIFY_BLOCK='1',TEST_BLOCK_DRAIN='1',TEST_BLOCK_AFTER_ALLDATA='2');self.wait_file('at-verify',wa)
        b=self.producer('B','global-3m.json');wb=self.worker(b);self.finish(wb)
        (self.p/'release-verify').touch();self.wait_file('at-drain',wa)
        c=self.producer('C','global-3m.json');wc=self.worker(c);self.finish(wc)
        (self.p/'release-drain').touch();self.wait_file('after-all-data',wa)
        self.assertEqual(self.remote_run(),'C') # C during long prior channels joined same snapshot
        d=self.producer('D','global-3m.json');wd=self.worker(d);self.finish(wd)
        (self.p/'release-all-data').touch();self.finish(wa)
        row=next(r for r in self.records() if r['run_id']=='D');self.assertEqual(row['state'],'pending');self.assertTrue(Path(row['proof_path']).exists());self.assertTrue((self.p/'pending').exists())
        next_worker=self.worker();self.finish(next_worker)
        self.assertEqual(self.remote_run(),'D');self.assertEqual(self.remote_run('global-3m.json'),'D')
        self.assertEqual(next(r for r in self.records() if r['run_id']=='D')['state'],'done')
    def test_same_run_conflict_and_exact_ack_leave_later_record(self):
        a=self.producer('A','hk-3m.json');self.helper(a,'enqueue')
        batch=self.p/'batch.json';self.helper(a,'snapshot','--batch',str(batch))
        b=self.producer('B','global-3m.json');self.helper(b,'enqueue')
        old=json.loads(batch.read_text());row=old['records'][0]
        result=self.p/'result.json';result.write_text(json.dumps({'batch_id':old['batch_id'],'outcomes':[{'id':row['id'],'proof_sha256':'wrong','state':'done'}]}))
        self.helper(a,'finish','--batch',str(batch),'--result',str(result),'--phase-ok')
        self.assertTrue(all(r['state']=='pending' for r in self.records()))
        proof=Path(a['R2_EXPORT_PROOF_PATH']);j=json.loads(proof.read_text());j['outputs']['boot.json']['size']+=1;proof.write_text(json.dumps(j))
        self.assertNotEqual(self.helper(a,'enqueue',check=False).returncode,0)
        self.assertEqual(next(r for r in self.records() if r['run_id']=='A')['proof_sha256'],row['proof_sha256'])

    def test_legacy_claim_does_not_delete_later_touch(self):
        self.helper(self.env,'enqueue');batch=self.p/'legacy.json';self.helper(self.env,'snapshot','--batch',str(batch))
        self.assertFalse((self.p/'pending').exists());(self.p/'pending').touch()
        body=json.loads(batch.read_text());result=self.p/'legacy-result.json';result.write_text(json.dumps({'batch_id':body['batch_id'],'outcomes':[]}))
        self.helper(self.env,'finish','--batch',str(batch),'--result',str(result),'--phase-ok')
        self.assertTrue((self.p/'pending').exists())
        worker=self.worker();self.finish(worker);self.assertFalse((self.p/'pending').exists())

    def test_shared_equal_channel_state_still_confirms_remote_A_B_A(self):
        a=self.producer('A','hk-3m.json');self.finish(self.worker(a))
        b=self.producer('B','hk-3m.json')
        # Model the real independent intraday publisher changing remote after all-data's A state.
        shutil.copyfile(self.s/'static-site/data/hk-3m.json',self.p/'remote/data__hk-3m.json')
        c=self.producer('C','hk-3m.json',file_run='A')
        count=len((self.p/'puts.jsonl').read_text().splitlines())
        self.finish(self.worker(c));self.assertEqual(self.remote_run('hk-3m.json'),'A')
        later=[json.loads(line) for line in (self.p/'puts.jsonl').read_text().splitlines()[count:]]
        self.assertTrue(any(row['key']=='data/hk-3m.json' for row in later))

    def test_async_outer_light_check_message_is_neutral(self):
        # Execute the real finalize_verify shell function, using the same safe interpreter adapter.
        source=(self.s/'scripts/r2_upload_async.sh').read_text();a=source.index('finalize_verify() {');b=source.index('\n}\n',a)+3;body=source[a:b]
        sh=self.p/'check-finalize.sh';sh.write_text('PY='+shlex_quote(str(self.py))+'\nREPO='+shlex_quote(str(self.s))+'\nLOG='+shlex_quote(str(self.p/'finalize.log'))+'\nR2_FAIL=" upload-lab"\nR2_KILLED=""\nR2_KILL_CTX=""\n'+body+'\nfinalize_verify\n')
        subprocess.run(['/bin/bash',str(sh)],env=self.env,check=True,capture_output=True,timeout=5)
        self.assertFalse((self.p/'notifications.jsonl').exists())
        subprocess.run(['/bin/bash',str(sh)],env=dict(self.env,TEST_LIGHT_PENDING='1'),check=True,capture_output=True,timeout=5)
        messages=[json.loads(line) for line in (self.p/'notifications.jsonl').read_text().splitlines()]
        self.assertEqual(messages[0][0],'[告警] R2上传失败');self.assertIn('LIGHT_CHECK_PENDING',messages[0][1]);self.assertIn('轻量对账未通过，待核查',messages[0][1]);self.assertNotIn('轻量对账确认有缺口',messages[0][1]);self.assertIn('--dedup-key',messages[0]);self.assertIn('deploy_r2_upload_fail',messages[0])

def shlex_quote(s):
    import shlex
    return shlex.quote(s)

if __name__=='__main__':unittest.main()
