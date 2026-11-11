"""Execute the real shell in a private runtime tree, with all business I/O stubbed.

Real exporter/proof reader interface, real receipt code and temporary SQLite.
The only upload/notification executables in REPO are asserted fixture stubs.
"""
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime
from zoneinfo import ZoneInfo
import pytest

ROOT=Path(__file__).resolve().parents[2]


@pytest.mark.parametrize('mode', ['success','partial','wrong_hash','wrong_run','exit124','metadata_failure','stale_exports','wrong_values'])
def test_actual_shell_to_proof_reader(tmp_path, mode):
    repo=tmp_path/'runtime';scripts=repo/'scripts';scripts.mkdir(parents=True)
    (scripts/'lib').mkdir(); (repo/'data').mkdir(); (repo/'static-site/data').mkdir(parents=True)
    for name in ('turnover_backfill.sh','ops_business_evidence.py','delivery_evidence.py','r2_export_proof.py','ops_monitor.py','lib/repo_paths.sh'):
        shutil.copyfile(ROOT/'scripts'/name,scripts/name)
    # Assert outgoing commands are fixtures before executing any business shell.
    (scripts/'pipeline.sh').write_text('#!/bin/sh\n# OFFLINE_STUB\nexit 0\n')
    (scripts/'notify.py').write_text('"OFFLINE_STUB"\nfrom pathlib import Path\nPath("notify-called").write_text("stub only")\n')
    (scripts/'upload_r2.py').write_text('''"OFFLINE_STUB"
import os,sys,json
from pathlib import Path
from r2_export_proof import load_run_proof,proof_matches
from delivery_evidence import record_publication
root=Path(os.environ['REPO']); static=root/'static-site'
mode=os.environ['FIXTURE_MODE']; run=os.environ['OPS_BUSINESS_RUN']
proof=load_run_proof(os.environ['OPS_TURNOVER_PROOF'],run,static)
if mode=='metadata_failure':
    assert not proof
    sys.exit(0)
assert len(proof)==9, 'production STATIC_DIR contract must match shell proof'
assert all(proof_matches(static/'data'/name,(static/'data'/name).read_bytes(),proof,static) for name in proof)
scope=sys.argv[-1]
names=sorted(proof)[:6] if scope=='small' else sorted(proof)[6:]
with (root/'stub-upload-calls').open('a') as f: f.write(scope+'\\n')
for name in names:
    item=dict(proof[name])
    if mode=='wrong_hash': item['sha256']='0'*64
    result=record_publication(data_root=root,run_id='wrong' if mode=='wrong_run' else run,object_name=name,confirmed=not(mode=='partial' and scope=='large'),**item)
    assert result['status']=='written'
sys.exit(124 if mode=='exit124' else 0)
''')
    assert all('OFFLINE_STUB' in (scripts/n).read_text() for n in ('pipeline.sh','notify.py','upload_r2.py'))
    app=repo/'app';(app/'collector').mkdir(parents=True)
    (app/'__init__.py').write_text('');(app/'collector/__init__.py').write_text('')
    (app/'collector/fetchers.py').write_text('def load_config(): return {}\n')
    (app/'db.py').write_text('import sqlite3\ndef get_conn(): return sqlite3.connect("data/sentiment.db")\n')
    (repo/'static-site/export.py').write_text('''import os,json
from pathlib import Path
DATA_DIR=Path(os.environ['REPO'])/'static-site/data'
EXPORT_RANGES=['3m','6m','1y','3y','5y','all']
from datetime import datetime
from zoneinfo import ZoneInfo
DAY='20000101' if os.environ['FIXTURE_MODE']=='stale_exports' else datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d')
VALUE=2.0 if os.environ['FIXTURE_MODE']=='wrong_values' else 1.0
METRICS=['a_turnover_'+n for n in ('mean','median','p90','p10','gt5_pct')]
def write_json(path,value): path.write_text(json.dumps(value))
def export_overview(conn,cfg): return {'date':DAY,'today':{'metrics':[{'id':m,'date':DAY,'value':VALUE} for m in METRICS]},'signals_today':[], 'signals_meta':{}}
def export_a_stock(conn,cfg,rng): return {'metrics':{m:{'data':[{'date':DAY,'value':VALUE}]} for m in METRICS}}
def export_boot():
    overview=json.loads((DATA_DIR/'overview.json').read_text())
    copy=dict(overview);copy.pop('signals_today')
    write_json(DATA_DIR/'boot.json',{'overview':copy})
    write_json(DATA_DIR/'signals_today.json',{k:overview[k] for k in ('date','signals_today','signals_meta')})
''')
    day=datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d')
    con=sqlite3.connect(repo/'data/sentiment.db')
    con.execute('CREATE TABLE daily_metric(date TEXT,metric_id TEXT,value REAL)')
    con.executemany('INSERT INTO daily_metric VALUES(?,?,?)',[(day,'a_turnover_'+n,1.0) for n in ('mean','median','p90','p10','gt5_pct')]);con.commit();con.close()
    (repo/'sitecustomize.py').write_text('''import socket
def forbidden(*a,**k): raise AssertionError('EXTERNAL_NETWORK_FORBIDDEN')
socket.create_connection=forbidden
socket.socket.connect=forbidden
''')
    bindir=tmp_path/'bin';bindir.mkdir()
    (bindir/'uname').write_text('#!/bin/sh\necho Linux\n') # prevent mac caffeinate child
    (bindir/'pgrep').write_text('#!/bin/sh\nexit 1\n')
    for p in bindir.iterdir():p.chmod(0o755)
    env={k:v for k,v in os.environ.items() if not k.startswith(('R2_','OPS_','VERIFY_'))}
    env.update(REPO=str(repo),GIT_REPO=str(repo),PY=sys.executable,PYTHONPATH=str(repo)+os.pathsep+str(scripts),
               PATH=str(bindir)+os.pathsep+env['PATH'],TURNOVER_BACKFILL_LOCKED='1',OPS_DELIVERY_EVIDENCE_ENABLED='1',
               INVOCATION_ID='a'*32,FIXTURE_MODE=mode)
    if mode=='metadata_failure':
        (repo/'data/ops_delivery').write_text('blocked metadata destination')
    proc=subprocess.run(['bash',str(scripts/'turnover_backfill.sh'),'force'],cwd=repo,env=env,capture_output=True,timeout=20)
    log=(repo/'data/logs/turnover_backfill_launchd.log').read_text()
    assert proc.returncode==(124 if mode=='exit124' else 0),log[-3000:]
    if mode=='metadata_failure':
        assert 'metadata_failure' in log
        assert not (repo/'notify-called').exists()
        return
    proof=json.loads((repo/('data/ops_delivery/turnover-'+'a'*32+'.json')).read_text())
    assert proof['static_dir']==str(repo/'static-site')
    assert (repo/'stub-upload-calls').read_text()=='small\nlarge\n'
    receipt=json.loads((repo/'data/ops_delivery/index/turnover.json').read_text())
    assert receipt['attempt_id']=='a'*32
    assert receipt['counts']=={'expected':14,'validated':5 if mode in ('stale_exports','wrong_values') else 14}
    confirmed=receipt['consumer_witness']['confirmed']
    assert len(confirmed)==(9 if mode in ('success','exit124','stale_exports','wrong_values') else 6 if mode=='partial' else 0)
    assert receipt['stage_status']==('failure' if mode=='exit124' else 'success' if mode=='success' else 'unknown')
    assert (repo/'notify-called').exists()==(mode=='exit124')
