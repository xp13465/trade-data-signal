"""Offline evidence contracts; REPO and all external effects are isolated."""
from datetime import datetime, timezone
from pathlib import Path
import importlib
import socket
import pytest
import json
from datetime import timedelta


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv('REPO', str(tmp_path))
    monkeypatch.setenv('OPS_DELIVERY_EVIDENCE_ENABLED', '1')
    monkeypatch.setattr(socket, 'create_connection', lambda *a, **k: pytest.fail('external I/O'))


@pytest.mark.parametrize('exhausted',[False,True])
def test_asset_unknown_explains_next_evidence(tmp_path, monkeypatch, exhausted):
    m = importlib.import_module('ops_monitor')
    from types import SimpleNamespace
    c = m.Collector(SimpleNamespace(data_root=tmp_path, code_root=tmp_path, total_timeout_seconds=20, command_timeout_seconds=2))
    if exhausted:
        def unavailable(): raise m.LimitError('fixture budget exhausted')
        monkeypatch.setattr(c.budget, 'remaining', unavailable)
    c.assets()
    rows = [v for v in c.checks if v['id'].startswith('data:')]
    assert len(rows) == 34
    assert all(v['evidence'].get('unknown_reason') and v['evidence'].get('next_evidence') for v in rows)


def test_active_service_is_not_completed_health():
    m = importlib.import_module('ops_monitor')
    row = m.unit_check('trade-overfit-monitor.service', {'LoadState': ['loaded'], 'ActiveState': ['activating'], 'SubState': ['start'], 'Result': ['success'], 'ExecMainStatus': ['0']})
    assert row['status'] == 'unknown'
    assert row['evidence']['execution_state'] == 'running'


def test_production_timer_projection_and_no_next_negative():
    m = importlib.import_module('ops_monitor')
    root=Path(__file__).resolve().parents[2]
    inventory=json.loads((root/'docs/ops/architecture/inventory/runtime_cloud.json').read_text())
    raw=next(r['runtime'] for r in inventory['records'] if r['id']=='cloud-timer:trade-overfit-monitor.timer')
    props={k: v if isinstance(v,list) else [v] for k,v in raw.items() if k in m.SAFE_PROPS}
    assert m.unit_check('trade-overfit-monitor.timer',props)['status']=='ok'
    props['NextElapseUSecRealtime']=[''];props['NextElapseUSecMonotonic']=['0']
    row=m.unit_check('trade-overfit-monitor.timer',props)
    assert row['status']=='unknown'
    assert row['evidence']['source_reason']=='active_timer_next_not_observed'


@pytest.fixture
def evidence(tmp_path, monkeypatch):
    e = importlib.import_module('ops_business_evidence')
    at = datetime(2026, 11, 11, 10, tzinfo=timezone.utc)
    monkeypatch.setattr(e, 'now', lambda: at)
    live = {k: [v] for k, v in dict(InvocationID='a'*32, ActiveState='inactive', SubState='dead', Result='success', ExecMainStatus='0').items()}
    ident = e.identity_for_bytes('overfit_monitor.json', b'new')
    args = dict(run_id='run-1', started_at=e.stamp(at-timedelta(minutes=5)), finished_at=e.stamp(at-timedelta(minutes=1)),
                status='success', inputs=[ident], outputs=[ident], confirmed=[ident], expected=2, observed=2,
                invocation_id='a'*32, code='b'*40, publication_run_id='generation-1')
    def put(**changes):
        return e.record_result(tmp_path, 'overfit', **dict(args, **changes))
    def assess():
        return e.assess(tmp_path, 'overfit', at, 'b'*40, live)
    return e, at, args, live, put, assess


def test_valid_receipt_and_bounded_collector(evidence, tmp_path, monkeypatch):
    e, at, args, live, put, assess = evidence
    assert put()['status'] == 'written'
    monkeypatch.setattr(e.sqlite3, 'connect', lambda *a, **k: pytest.fail('collector DB scan'))
    status, ev = assess()
    assert status == 'ok'
    assert ev['event_at'] == args['finished_at']
    assert ev['run_id'] == 'run-1'
    m = importlib.import_module('ops_monitor')
    from types import SimpleNamespace
    c = m.Collector(SimpleNamespace(data_root=tmp_path, code_root=tmp_path, total_timeout_seconds=20, command_timeout_seconds=1, collector_id='offline'), now=at)
    monkeypatch.setattr(m, 'code_ref', lambda root: 'b'*40)
    c.unit_observations['trade-overfit-monitor.service'] = live
    c.business_evidence()
    snapshot = c.snapshot()
    assert m.validate_snapshot(snapshot)
    assert len(snapshot['checks']) == 6
    assert next(c for c in snapshot['checks'] if c['id']=='business:overfit')['status']=='ok'
    assert str(tmp_path) not in json.dumps(snapshot)


@pytest.mark.parametrize('change,reason', [
    ({'valid_until':'2026-11-11T09:59:00Z'}, 'expired_or_invalid_time'),
    ({'business_date':'2026-11-10'}, 'business_date_mismatch'),
    ({'invocation_id':'c'*32}, 'invocation_not_verified'),
    ({'code':'c'*40}, 'code_ref_mismatch'),
    ({'observed':1}, 'coverage_or_completion_unverified'),
    ({'confirmed':[]}, 'hash_or_confirmation_missing'),
    ({'confirmed':[{'object_id':'overfit_monitor.json','sha256':'0'*64,'size':3}]}, 'hash_or_confirmation_missing'),
    ({'finished_at':None}, 'completion_missing'),
    ({'publication_run_id':None}, 'generation_unverified'),
])
def test_negative_receipts(evidence, change, reason):
    *_, put, assess = evidence
    assert put(**change)['status']=='written'
    status, ev = assess()
    assert status == 'unknown'
    assert ev['unknown_reason'] == reason


@pytest.mark.parametrize('active,code,expected', [('activating','0','unknown'),('failed','124','warning'),('inactive','124','warning')])
def test_running_and_exit124_do_not_recover(evidence, active, code, expected):
    _, _, _, live, put, assess = evidence
    put()
    live.update(ActiveState=[active], ExecMainStatus=[code])
    assert assess()[0] == expected


def test_new_failure_not_overwritten_by_old_success(evidence):
    e, at, args, _, put, assess = evidence
    put(status='failure', run_id='new', started_at=e.stamp(at-timedelta(minutes=2)))
    put()  # Older invocation finishes later: must not replace new failure.
    assert assess()[0] == 'warning'
    assert assess()[1]['run_id'] == 'new'


def test_metadata_write_failure_inert(evidence, monkeypatch):
    e, _, _, _, put, _ = evidence
    monkeypatch.setattr(e, 'write_index', lambda *a: (_ for _ in ()).throw(OSError('secret data')))
    assert put()['status'] == 'metadata_failure'


def test_publication_contract_matches_run_hash_and_confirmation(tmp_path, monkeypatch):
    e = importlib.import_module('ops_business_evidence')
    d = importlib.import_module('delivery_evidence')
    from r2_export_proof import output_record
    payload = b'new'; outputs = {'overview.json':output_record(payload)}
    started = e.stamp(e.now()-timedelta(minutes=1))
    args = dict(data_root=tmp_path, run_id='run-1', object_name='overview.json', **outputs['overview.json'])
    assert d.record_publication(**args, confirmed=False)['status']=='written'
    assert e.publication_confirmations(tmp_path,'run-1', outputs, started)=={}
    assert d.record_publication(**args, confirmed=True)['status']=='written'
    assert e.publication_confirmations(tmp_path,'run-1', outputs, started)==outputs
    assert e.publication_confirmations(tmp_path,'wrong', outputs, started)=={}
    assert e.publication_confirmations(tmp_path,'run-1', {'overview.json':output_record(b'bad')}, started)=={}
    assert d.record_publication(**args, confirmed=False)['status']=='written'
    assert e.publication_confirmations(tmp_path,'run-1', outputs, started)=={}
    assert d.record_publication(**dict(args,object_name='../bad.json'), confirmed=True)['status']=='metadata_failure'
    monkeypatch.setenv('OPS_DELIVERY_EVIDENCE_ENABLED','0')
    assert d.record_publication(**args, confirmed=True)['status']=='disabled'


def test_turnover_real_rows_and_existing_export_proof(tmp_path, monkeypatch):
    e = importlib.import_module('ops_business_evidence')
    d = importlib.import_module('delivery_evidence')
    from r2_export_proof import write_run_proof, output_record
    import sqlite3
    (tmp_path/'data').mkdir(); output=tmp_path/'static-site/data'; output.mkdir(parents=True)
    con=sqlite3.connect(tmp_path/'data/sentiment.db')
    con.execute('CREATE TABLE daily_metric(date TEXT,metric_id TEXT,value REAL)')
    day=e.now().astimezone(e.ZONE).strftime('%Y%m%d')
    con.executemany('INSERT INTO daily_metric VALUES(?,?,?)', [(day,m,1.25) for m in e.METRICS]);con.commit();con.close()
    started=e.stamp(e.now()-timedelta(minutes=1))
    proof=tmp_path/'proof.json'; monkeypatch.setenv('OPS_TURNOVER_PROOF',str(proof))
    ov={'date':day,'today':{'metrics':[{'id':m,'date':day,'value':1.25} for m in e.METRICS]},'signals_today':[],'signals_meta':{}}
    boot=dict(ov);boot.pop('signals_today')
    bodies={'overview.json':ov,'boot.json':{'overview':boot},'signals_today.json':{k:ov[k] for k in ('date','signals_today','signals_meta')}}
    bodies.update({name:{'metrics':{m:{'data':[{'date':day,'value':1.25}]} for m in e.METRICS}} for name in e.TURNOVER[3:]})
    outputs={}
    for name,body in bodies.items():
        payload=json.dumps(body).encode();(output/name).write_bytes(payload);outputs[name]=output_record(payload)
    write_run_proof(proof,'turn-1',output.parent,outputs)
    for name, identity in outputs.items():
        d.record_publication(data_root=tmp_path,run_id='turn-1',object_name=name,confirmed=True,**identity)
    result=e.turnover_result(tmp_path,'turn-1',started,0)
    assert result['status']=='written'
    receipt=e.bounded_json(e.receipt_root(tmp_path)/'index/turnover.json')
    assert receipt['counts']=={'expected':14,'validated':14}
    assert len(receipt['consumer_witness']['confirmed'])==9
    # Missing actual table cannot be hidden by existing successful export proof.
    con=sqlite3.connect(tmp_path/'data/sentiment.db');con.execute('DROP TABLE daily_metric');con.close()
    e.turnover_result(tmp_path,'turn-1',started,0)
    assert e.bounded_json(e.receipt_root(tmp_path)/'index/turnover.json')['stage_status']=='unknown'


@pytest.mark.parametrize('token,valid', [('Z',True),('0'+'_.:-ab'*21,True),('A'*128,True),
                                        ('a'*129,False),('_bad',False),(':bad',False),('a/b',False)])
def test_collector_publication_generation_contract(evidence, token, valid):
    e, at, args, live, put, assess=evidence
    put(publication_run_id=token)
    status,ev=assess()
    assert (status=='ok') is valid
    if not valid: assert ev['unknown_reason']=='generation_unverified'


def test_binding_candidate_requires_new_natural_receipt_not_old_rewrite(tmp_path,monkeypatch):
    import subprocess
    import sys
    import hashlib
    e=importlib.import_module('ops_business_evidence');d=importlib.import_module('delivery_evidence')
    at=e.now();clock=[at];monkeypatch.setattr(e,'now',lambda:clock[0])
    identities=[e.identity_for_bytes(name,b'fixture') for name in e.OVERFIT]
    args=dict(run_id='natural-first',started_at=e.stamp(at-timedelta(minutes=5)),finished_at=e.stamp(at-timedelta(minutes=1)),
              status='success',inputs=identities,outputs=identities,confirmed=identities,expected=2,observed=2,
              invocation_id='a'*32,publication_run_id='first-generation')
    first=e.record_result(tmp_path,'overfit',**args);assert first['status']=='written'
    index=d.receipt_root(tmp_path)/'index/overfit.json';before=index.read_bytes();r=e.bounded_json(index)
    receipt=d.receipt_root(tmp_path)/'receipts'/r['session_date']/'ops_business'/(r['receipt_id']+'.json')
    original=receipt.read_bytes();assert r['code_identity']['sha']=='unknown'
    live={k:[v] for k,v in dict(InvocationID='a'*32,ActiveState='inactive',SubState='dead',Result='success',ExecMainStatus='0').items()}
    commit='b'*40;assert e.assess(tmp_path,'overfit',at,commit,live)[0]=='unknown'
    result=subprocess.run([sys.executable,str(Path(d.__file__)),'binding-candidate','--data-root',str(tmp_path),
                           '--code-sha',commit,'--receipt',str(receipt),hashlib.sha256(original).hexdigest()],
                          text=True,capture_output=True,timeout=5,check=True)
    candidate=json.loads(result.stdout);assert candidate['reviewed'] is False
    assert candidate['loaded_module_sha256']==[r['code_identity']['module_sha256']]
    assert not (d.receipt_root(tmp_path)/'producer-identity.json').exists()
    # Synthetic approval fixture only, never a production approval/install path.
    candidate['reviewed']=True
    manifest=d.receipt_root(tmp_path)/'producer-identity.json';manifest.write_text(json.dumps(candidate));manifest.chmod(0o600)
    assert index.read_bytes()==before and receipt.read_bytes()==original
    assert e.assess(tmp_path,'overfit',at,commit,live)[0]=='unknown'
    clock[0]=at+timedelta(seconds=1);live['InvocationID']=['c'*32]
    args.update(run_id='natural-next',invocation_id='c'*32,started_at=e.stamp(at-timedelta(seconds=30)),
                finished_at=e.stamp(at),publication_run_id='next-generation')
    assert e.record_result(tmp_path,'overfit',**args)['status']=='written'
    assert e.assess(tmp_path,'overfit',clock[0],commit,live)[0]=='ok'
    assert receipt.read_bytes()==original  # immutable old proof is not relabelled
