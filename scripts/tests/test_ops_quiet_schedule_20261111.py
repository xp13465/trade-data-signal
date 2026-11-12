"""Offline replay of actual embedded monitor code; never run the shell body."""
import ast
import fcntl
import hashlib
import importlib.util
import json
import os
import re
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import textwrap
import types
from datetime import datetime, timedelta

import pytest

ROOT = Path(__file__).resolve().parents[2]
MONITOR = Path(os.environ.get('SCHEDULE_MONITOR_SH', ROOT / 'scripts/schedule_monitor.sh'))
TEXT = MONITOR.read_text().split("<<'PYEOF'", 1)[1].split('\n', 1)[1].split('\nPYEOF', 1)[0]
TREE = ast.parse(TEXT)


def source(name):
    node = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.get_source_segment(TEXT, node)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv('REPO', str(tmp_path))
    def blocked(*a, **kw):
        raise AssertionError('real external boundary forbidden')
    monkeypatch.setattr(socket.socket, 'connect', blocked)
    monkeypatch.setattr(socket, 'create_connection', blocked)
    monkeypatch.setattr(subprocess, 'Popen', blocked)
    with pytest.raises(AssertionError):
        socket.create_connection(('example.invalid', 443))
    with pytest.raises(AssertionError):
        subprocess.Popen(['notify-forbidden'])


def namespace(tmp_path):
    sys.path.insert(0, str(ROOT / 'scripts'))
    import alert_denoise_rules as adr
    ns = dict(datetime=datetime, timedelta=timedelta, Path=Path, os=os, re=re, json=json,
              tempfile=tempfile, time=time, fcntl=fcntl, hashlib=hashlib, sys=sys, subprocess=subprocess,
              REPO=tmp_path, LOG_DIR=tmp_path/'logs', ALERT_STATE_FILE=tmp_path/'data/alert_state.json',
              NOW=datetime(2026, 11, 11, 15, 30), adr=adr, alerts=[], recoveries=[],
              alert_state={}, seen_keys_this_run=set(), in_progress_tasks=set(),
              STATS_FRESH_WINDOW=timedelta(hours=24), _STATE_PRE={}, _ALERT_MAIL_COUNTER={'sent':0}, MONITOR_LOG=tmp_path/'monitor.log')
    # Definitions only. No production entry point, subprocess or module-level probes.
    for n in TREE.body:
        if isinstance(n, ast.FunctionDef):
            exec(compile(ast.Module(body=[n], type_ignores=[]), str(MONITOR), 'exec'), ns)
    for n in TREE.body:
        if isinstance(n, ast.Assign) and any(getattr(t,'id','') in {
            'DUR_THRESHOLDS','DUR_CONTINUOUS_THRESHOLD','DUR_IMMEDIATE_MULTIPLE',
            'DUR_BUFFER_MAX_AGE','STALE_EXIT_THRESHOLD','IN_PROGRESS_MAX_AGE','RECOVERY_COOLDOWN',
            'STATE_SHARED_FIELDS','STATE_ACK_FIELDS','STATE_NOTIFY_FIELDS','_IMPACT_MAP','_SUGGEST_MAP','_LOG_MAP','TASKS'} for t in n.targets):
            exec(compile(ast.Module(body=[n], type_ignores=[]), str(MONITOR),'exec'), ns)
    return ns


def dur_tick(ns, run='2026-11-11 15:02', duration=928):
    node = next(n for n in ast.walk(TREE) if isinstance(n, ast.If)
                and ast.unparse(n.test).startswith('_dur is not None'))
    ns.update(_dur=duration, _dur_task='intraday_snapshot', alerts=[],
              s=dict(task='intraday_snapshot', last_duration_sec=duration, last_run=run, last_exit=0))
    exec(compile(ast.Module(body=[node],type_ignores=[]), str(MONITOR),'exec'),ns)
    return ns['alerts']


def test_same_completed_run_is_one_observation_not_two_executions(tmp_path):
    ns=namespace(tmp_path)
    assert dur_tick(ns)==[]
    ns['NOW']+=timedelta(minutes=15)
    assert dur_tick(ns)==[]
    assert ns['alert_state']['intraday_snapshot|dur_buffer|900']['consecutive_count']==1


def test_distinct_completed_runs_and_extreme_runtime_still_alert(tmp_path):
    ns=namespace(tmp_path)
    assert dur_tick(ns,run='2026-11-11 10:00',duration=1000)==[]
    assert dur_tick(ns,run='2026-11-11 10:10',duration=1000)
    ns=namespace(tmp_path)
    assert dur_tick(ns,duration=1900)


def test_monitor_save_preserves_concurrent_ack_and_notify_receipt(tmp_path):
    ns=namespace(tmp_path);p=ns['ALERT_STATE_FILE'];p.parent.mkdir()
    old=dict(status='active',event_id='event-a',consecutive_count=3,first_seen='2026-11-11 10:00:00')
    ns['_STATE_PRE']={'task|fail':dict(old)}
    disk=dict(old,acknowledged='2026-11-11 15:00:00',ack_owner='oncall',ack_event_id='event-a',
              notified_at='2026-11-11 14:59:00',notified_event_id='event-a',notified_channels={'email':True})
    p.write_text(json.dumps({'task|fail':disk}))
    state={'task|fail':dict(old,consecutive_count=4)}
    ns['save_alert_state'](state)
    actual=json.loads(p.read_text())['task|fail']
    assert actual['ack_owner']=='oncall'
    assert actual['notified_channels']==disk['notified_channels']
    assert actual['consecutive_count']==4 and actual['status']=='active'


def test_same_fault_is_not_periodically_renotified_after_claim(tmp_path,monkeypatch):
    ns=namespace(tmp_path);ns['NOW']=datetime(2026,11,15,12)
    calls=[]
    def fake(args,**kw):
        calls.append(args)
        if '--result-file' in args:Path(args[args.index('--result-file')+1]).write_text('{"status":"digested"}')
        return types.SimpleNamespace(stdout='',stderr='',returncode=0)
    monkeypatch.setattr(subprocess,'run',fake)
    row=dict(status='active',event_id='e',first_seen='2026-11-01 00:00:00',
             first_alerted='2026-11-01 00:00:00',last_alerted='2026-11-01 00:00:00',
             notified_at='2026-11-01 00:00:00',notified_event_id='e',notified_channels={'email':True},acknowledged='2026-11-12 00:00:00',ack_owner='oncall',ack_event_id='e')
    ns['_active_escalate'](row,'task|fail','task failed')
    assert calls==[] and row['status']=='active'


def sender(ns, monkeypatch, status='sent', channels=None):
    calls=[]
    channels = {'email': True, 'telegram': False, 'feishu': True} if channels is None else channels
    def fake(cmd, **kw):
        assert str(ns['REPO']) in str(cmd[1]) and Path(cmd[1]).name == 'notify.py'
        assert kw.get('timeout') == 30
        refs=json.loads(cmd[cmd.index('--ops-event-refs')+1]);assert len(refs)==1
        ref=refs[0];calls.append((ref,cmd[2],cmd[3]))
        assert set(ref)=={'key','event_id','phase','source_run'}
        result={'status':status,'channels':channels,'event_results':[dict(ref,status=status,channels=channels)]}
        Path(cmd[cmd.index('--result-file')+1]).write_text(json.dumps(result))
        # This is the notify-owned receipt merge boundary, not the monitor state machine.
        if status in ('sent','partial') and any(channels.get(c) is True for c in ('email','telegram','feishu')):
            path=ns['ALERT_STATE_FILE'];state=json.loads(path.read_text());entry=state[ref['key']]
            if ref['phase']=='active':entry.update(notified_event_id=ref['event_id'],notified_at='2026-11-11 15:30:00',notified_channels=channels)
            else:
                field='last_recovery_notified' if ref['phase']=='recovery' else 'last_escalation_notified'
                entry.update({field:'2026-11-11 15:30:00',field+'_event_id':ref['event_id']})
            path.write_text(json.dumps(state))
        return types.SimpleNamespace(returncode=0,stdout='',stderr='')
    monkeypatch.setattr(subprocess,'run',fake)
    return calls


def new_failure(ns, key='overfit_monitor|unit_exit!=0|76', run='a'*32, event=None):
    row=dict(status='active',first_seen='2026-11-11 22:00:00',keyword='unit_exit=76',
             message='SEVERE: overfit_monitor publish verification failed',requires_action=True,source_run=run)
    if event:row['event_id']=event
    ns['alert_state'][key]=row
    ns['stats']=[dict(task=key.split('|')[0],last_run=run)]
    return row


def test_real_event_sender_independent_same_domain_and_cross_day_receipts(tmp_path,monkeypatch):
    ns=namespace(tmp_path);calls=sender(ns,monkeypatch)
    a=new_failure(ns);b=new_failure(ns,'public_fund_daily|unit_exit!=0|124')
    b['message']='SEVERE: public_fund_daily source failed'
    assert ns['_quiet_route_alerts']([a['message'],b['message']])==[]
    assert len(calls)==2 and calls[0][0]['event_id']!=calls[1][0]['event_id']
    ns['NOW']+=timedelta(days=2)
    assert ns['_quiet_route_alerts']([a['message'],b['message']])==[]
    assert len(calls)==2 # no broad R2 domain window, no time-based re-first-send


@pytest.mark.parametrize('status,channels',[('failed',{}),('sent',{'deferred':True,'email':False,'telegram':False,'feishu':False}),('unknown',{})])
def test_no_actual_channel_receipt_no_fake_sent_or_recovery(tmp_path,monkeypatch,status,channels):
    ns=namespace(tmp_path);calls=sender(ns,monkeypatch,status,channels);row=new_failure(ns)
    ns['_quiet_route_alerts']([row['message']]);assert not row.get('notified_at')
    assert ns['_ALERT_MAIL_COUNTER']['sent']==0
    row.update(status='recovered',last_recovered='2026-11-11 22:10:00')
    assert ns['_quiet_route_recoveries']([])==[]
    assert len(calls)==1 and row['requires_action'] is False


def test_actual_receipt_recovery_once_and_new_event_no_inherited_receipt(tmp_path,monkeypatch):
    ns=namespace(tmp_path);calls=sender(ns,monkeypatch);row=new_failure(ns)
    ns['_quiet_route_alerts']([row['message']]);first=row['event_id']
    row.update(status='recovered',last_recovered='2026-11-11 22:10:00')
    ns['_quiet_route_recoveries']([]);ns['_quiet_route_recoveries']([])
    assert [v[0]['phase'] for v in calls]==['active','recovery']
    ns['_STATE_PRE']={k:dict(v) for k,v in ns['alert_state'].items()}
    row=new_failure(ns,run='b'*32);row['first_seen']='2026-11-12 22:00:00'
    ns['_quiet_route_alerts']([row['message']])
    assert row['event_id']!=first and len(calls)==3
    assert not row.get('acknowledged')


def test_unclaimed_escalates_once_and_ack_does_not_change_failure(tmp_path,monkeypatch):
    ns=namespace(tmp_path);calls=sender(ns,monkeypatch);row=new_failure(ns)
    ns['_quiet_route_alerts']([row['message']]);ns['NOW']=datetime(2026,11,13,12)
    ns['_active_escalate'](row,'overfit_monitor|unit_exit!=0|76','overfit')
    ns['NOW']+=timedelta(days=2)
    ns['_active_escalate'](row,'overfit_monitor|unit_exit!=0|76','overfit')
    assert [v[0]['phase'] for v in calls]==['active','escalation']
    assert row['status']=='active' and row['requires_action'] is True


def test_status_conclusion_runtime_switch_gates_and_baseline_delivery(tmp_path,monkeypatch):
    # 2026-11-12 回退基线语义(用户拍板): 状态说明邮件恢复完整实现, 不再是 internal_only 硬桩。
    ns=namespace(tmp_path)
    ns['CONCLUSION_STATUS_EMAIL_ENV']='MONITOR_CONCLUSION_STATUS_EMAIL'
    ns['CONCLUSION_STATUS_KEY_PREFIX']='conclusion_status|'
    ns['CONCLUSION_STATUS_SUBJECT_PREFIX']='[状态说明]'
    _pair = next(n for n in TREE.body if isinstance(n, ast.Assign)
                 and any(getattr(t,'id','')=='_CONCLUSION_PAIR_RE' for t in n.targets))
    exec(compile(ast.Module(body=[_pair],type_ignores=[]), str(MONITOR),'exec'), ns)
    from notify_sent import notify_sent
    ns['notify_sent']=notify_sent
    def forbidden(*a,**kw):pytest.fail('status-conclusion external notification')
    monkeypatch.setenv('MONITOR_CONCLUSION_STATUS_EMAIL','0')
    result=ns['_maybe_send_conclusion_status_email']('not OK: same known failure',0,{},ns['NOW'],forbidden,lambda s:None)
    assert result['reason']=='disabled' and result['sent'] is False
    monkeypatch.setenv('MONITOR_CONCLUSION_STATUS_EMAIL','1')
    calls=[];saves=[]
    def stub(cmd):
        calls.append(cmd)
        return '[notify] 汇总：已发出 email'
    result=ns['_maybe_send_conclusion_status_email']('not OK: same known failure',0,{},ns['NOW'],stub,lambda s:saves.append(s))
    assert result['sent'] is True and calls and saves


def test_ack_real_cli_mutates_only_claim_not_business_or_notify(tmp_path,monkeypatch):
    spec=importlib.util.spec_from_file_location('quiet_ack',ROOT/'scripts/alert_ack.py');ack=importlib.util.module_from_spec(spec);spec.loader.exec_module(ack)
    p=tmp_path/'data/alert_state.json';p.parent.mkdir();original={'status':'active','event_id':'e','consecutive_count':7,'notified_at':'old','notified_channels':{'email':True}}
    p.write_text(json.dumps({'key':original}))
    monkeypatch.setattr(sys,'argv',['alert_ack.py','key','--owner','operator','--note','investigating'])
    assert ack.main()==0
    row=json.loads(p.read_text())['key'];assert all(row[k]==v for k,v in original.items())
    assert row['ack_event_id']=='e' and row['ack_owner']=='operator'
    monkeypatch.setattr(sys,'argv',['alert_ack.py','key','--clear']);assert ack.main()==0
    assert json.loads(p.read_text())['key']==original


def test_real_ack_main_between_monitor_read_and_save_is_preserved(tmp_path,monkeypatch):
    ns=namespace(tmp_path);key='overfit_monitor|unit_exit!=0|76'
    prior=dict(status='active',event_id='event-a',first_seen='2026-11-11 10:00:00',consecutive_count=3)
    path=ns['ALERT_STATE_FILE'];path.parent.mkdir();path.write_text(json.dumps({key:prior}))
    snapshot=ns['load_alert_state']();ns['_STATE_PRE']={key:dict(snapshot[key])}
    # Actual ACK CLI main reads/locks/writes the same file after monitor's read.
    ack_path=Path(os.environ.get('ALERT_ACK_SCRIPT',ROOT/'scripts/alert_ack.py'))
    spec=importlib.util.spec_from_file_location('quiet_ack_interleave',ack_path);ack=importlib.util.module_from_spec(spec);spec.loader.exec_module(ack)
    monkeypatch.setattr(ack,'REPO',tmp_path);monkeypatch.setattr(ack,'ALERT_STATE_FILE',path);monkeypatch.setattr(ack,'LOCK_FILE',path.parent/'.alert_state.lock')
    monkeypatch.setattr(sys,'argv',['alert_ack.py',key]);assert ack.main()==0
    acknowledged=json.loads(path.read_text())[key]['acknowledged']
    snapshot[key]['consecutive_count']=4;ns['save_alert_state'](snapshot)
    stored=json.loads(path.read_text())[key]
    assert stored['acknowledged']==acknowledged
    assert stored['status']=='active' and stored['consecutive_count']==4


def test_new_event_retires_ack_and_receipts_but_preserves_audit(tmp_path):
    ns=namespace(tmp_path);key='overfit_monitor|unit_exit!=0|76';path=ns['ALERT_STATE_FILE'];path.parent.mkdir()
    old=dict(status='recovered',event_id='old',first_seen='2026-11-10 21:40:00',
             acknowledged='2026-11-10 22:00:00',ack_owner='owner',ack_event_id='old',
             notified_at='2026-11-10 21:41:00',notified_event_id='old',notified_channels={'email':True})
    path.write_text(json.dumps({key:old}));ns['_STATE_PRE']={key:dict(old)}
    new=dict(status='active',event_id='new',first_seen='2026-11-11 21:40:00',requires_action=True)
    ns['save_alert_state']({key:new})
    row=json.loads(path.read_text())[key]
    assert not row.get('acknowledged') and not row.get('notified_at')
    assert row['previous_events'][-1]['event_id']=='old'
    assert row['previous_events'][-1]['ack_owner']=='owner'


def test_older_completed_success_cannot_clear_newer_slow_run(tmp_path):
    ns=namespace(tmp_path);dur_tick(ns,run='2026-11-11 15:02')
    dur_tick(ns,run='2026-11-11 14:02',duration=10)
    assert ns['alert_state']['intraday_snapshot|dur_buffer|900']['status']=='pending'
    dur_tick(ns,run='2026-11-11 14:02')
    dur_tick(ns,run='2026-11-11 15:02')
    assert ns['alert_state']['intraday_snapshot|dur_buffer|900']['consecutive_count']==1


def test_real_unit_detection_to_state_refs_and_channel_receipt(tmp_path,monkeypatch):
    ns=namespace(tmp_path);calls=sender(ns,monkeypatch)
    import unit_truth as ut
    ns['ut']=ut;ns['UNIT_REGISTRY']=[];ns['UNIT_STATES']={};ns['_unit_stats_by_task']={};ns['UNIT_FAILURES']=[]
    for task,unit,code,inv in [('public_fund_daily','trade-public-fund-daily.service',124,'a'*32),
                                ('overfit_monitor','trade-overfit-monitor.service',76,'b'*32)]:
        props={'LoadState':'loaded','ActiveState':'failed','Result':'exit-code','ExecMainCode':'1',
               'ExecMainStatus':str(code),'ExecMainStartTimestamp':'Wed 2026-11-11 14:00:00 CST',
               'ExecMainExitTimestamp':'Wed 2026-11-11 14:05:00 CST','InvocationID':inv}
        ns['UNIT_REGISTRY'].append({'task':task,'unit':unit})
        ns['UNIT_STATES'][unit]=ut.derive_unit_state(unit,props)
    block=next(n for n in ast.walk(TREE) if isinstance(n,ast.For) and isinstance(n.iter,ast.Call)
               and getattr(n.iter.func,'id','')=='_unit_alert_events')
    exec(compile(ast.Module(body=[block],type_ignores=[]),str(MONITOR),'exec'),ns)
    assert len(ns['alerts'])==2 and len(ns['UNIT_FAILURES'])==2
    ns['_quiet_route_alerts'](ns['alerts'])
    assert len(calls)==2
    assert {c[0]['source_run'] for c in calls}=={'a'*32,'b'*32}
    disk=json.loads(ns['ALERT_STATE_FILE'].read_text())
    assert all(v['requires_action'] is True and ns['_quiet_notified'](v) for v in disk.values())


def test_ack_holds_real_lock_while_monitor_save_waits(tmp_path,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    ns=namespace(tmp_path);key='task|failed';path=ns['ALERT_STATE_FILE'];path.parent.mkdir()
    initial={key:dict(status='active',event_id='e',first_seen='2026-11-11 10:00:00',consecutive_count=1)}
    path.write_text(json.dumps(initial));snapshot=ns['load_alert_state']();ns['_STATE_PRE']=json.loads(json.dumps(initial))
    spec=importlib.util.spec_from_file_location('quiet_ack_locked',ROOT/'scripts/alert_ack.py');ack=importlib.util.module_from_spec(spec);spec.loader.exec_module(ack)
    monkeypatch.setattr(sys,'argv',['alert_ack.py',key,'--owner','responder'])
    held=threading.Event();release=threading.Event();original=ack._save_atomic
    def hold_then_save(state):
        held.set();assert release.wait(1);original(state)
    monkeypatch.setattr(ack,'_save_atomic',hold_then_save)
    with ThreadPoolExecutor(max_workers=2) as pool:
        claim=pool.submit(ack.main);assert held.wait(1)
        snapshot[key]['consecutive_count']=2
        saved=pool.submit(ns['save_alert_state'],snapshot)
        try:
            time.sleep(.03);assert not saved.done()
        finally:release.set()
        assert claim.result(2)==0 and saved.result(2) is True
    row=json.loads(path.read_text())[key]
    assert row['ack_owner']=='responder' and row['consecutive_count']==2 and row['status']=='active'


def test_known_new_run_not_hidden_by_old_recovery_cooldown(tmp_path):
    ns=namespace(tmp_path)
    old={'status':'recovered','source_run':'2026-11-11 14:00','last_recovered':'2026-11-11 15:29:00'}
    assert ns['_recurrence_suppressed'](old,'2026-11-11 14:00') is True
    assert ns['_recurrence_suppressed'](old,'2026-11-11 15:00') is False
    assert ns['_recurrence_suppressed'](old,None) is False


def test_transient_lock_before_existing_escalation_boundary_only_internal(tmp_path):
    ns=namespace(tmp_path)
    start=TEXT.index('            _r2_skip_cnt = s.get("r2_skip_count")')
    end=TEXT.index('        # P2(2026-09-24 r2 终审)',start)
    ns.update(R2_SKIP_CONTINUOUS_THRESHOLD=3,R2_SKIP_OBS_WINDOW=timedelta(minutes=30),
              R2_SKIP_TRANSIENT_TASKS=('gen_daily_brief','fetch_news'),R2_SKIP_ESCALATE_ROUNDS=6)
    code=compile(textwrap.dedent(TEXT[start:end]),str(MONITOR),'exec')
    for n in range(1,7):
        at=datetime(2026,11,11,10)+timedelta(minutes=30*n)
        ns['NOW']=at+timedelta(minutes=1)
        ns['s']={'task':'fetch_news','last_run':at.strftime('%Y-%m-%d %H:%M'),'r2_round_id':at.isoformat(),
                 'r2_skip_count':1,'last_exit':0}
        exec(code,ns)
        if n<6:assert ns['alerts']==[]
    assert len(ns['alerts'])==1 and ns['alert_state']['fetch_news|r2_skip_alert']['requires_action'] is True


@pytest.mark.parametrize('inv,code,source,valid',[('a'*32,124,'systemd',True),
    (None,124,'systemd',False),('2026-11-11 14:00',124,'systemd',False),
    ('a'*32,False,'systemd',False),('a'*32,0,'systemd',False),('a'*32,124,'ledger',False)])
def test_core_cfu_refs_require_actual_invocation_and_exit(tmp_path,inv,code,source,valid):
    ns=namespace(tmp_path);key=f'public_fund_daily|unit_exit!=0|{code}'
    new_failure(ns,key,run=inv)
    ns['UNIT_STATES']={'trade-public-fund-daily.service':{'invocation_id':inv,'code':code,'source':source}}
    refs=ns['_quiet_core_unit_refs']()
    assert bool(refs) is valid
    if valid:
        ref=refs['trade-public-fund-daily.service'];assert ref['source_run']==inv and ref['exit_code']==124
        disk=json.loads(ns['ALERT_STATE_FILE'].read_text());assert disk[key]['event_id']==ref['event_id']
    else:
        ns['stats']=[{'task':'public_fund_daily','last_run':'2026-11-11 14:00'}]
        if not inv or len(str(inv))!=32:assert ns['_quiet_source_run'](key,ns['alert_state'][key]) is None


def test_cfu_no_ownership_transfer_when_persist_fails(tmp_path):
    ns=namespace(tmp_path);new_failure(ns,'public_fund_daily|unit_exit!=0|124')
    ns['UNIT_STATES']={'trade-public-fund-daily.service':{'invocation_id':'a'*32,'code':124,'source':'systemd'}}
    ns['save_alert_state']=lambda state:False
    assert ns['_quiet_core_unit_refs']()=={}


def test_concurrent_claim_and_independent_event_survive_monitor_snapshot(tmp_path):
    ns=namespace(tmp_path);path=ns['ALERT_STATE_FILE'];path.parent.mkdir()
    row={'status':'active','event_id':'e','first_seen':'2026-11-11 10:00:00'}
    ns['_STATE_PRE']={'key':dict(row)};snapshot={'key':dict(row)}
    claim={'event_id':'e','phase':'active','attempt_id':'sender','expires_at':'2026-11-11T10:03:00Z'}
    path.write_text(json.dumps({'key':dict(row,notification_claim=claim),'independent':{'status':'active','event_id':'other'}}))
    ns['save_alert_state'](snapshot)
    disk=json.loads(path.read_text())
    assert disk['key']['notification_claim']==claim and disk['independent']['event_id']=='other'


def test_pending_new_incident_retains_previous_closed_audit(tmp_path):
    ns=namespace(tmp_path);path=ns['ALERT_STATE_FILE'];path.parent.mkdir()
    old={'event_id':'old','status':'recovered','first_seen':'2026-11-10 10:00:00','ack_owner':'before'}
    path.write_text(json.dumps({'fetch_news|r2_skip_alert':old}));ns['_STATE_PRE']={'fetch_news|r2_skip_alert':old}
    state={'fetch_news|r2_skip_alert':{'status':'pending','first_seen':'2026-11-11 10:00:00','requires_action':False}}
    ns['save_alert_state'](state);new=state['fetch_news|r2_skip_alert']
    assert new['event_id']!='old' and not new.get('ack_owner')
    assert new['previous_events'][0]['ack_owner']=='before'
    ns['save_alert_state'](state)
    assert len(state['fetch_news|r2_skip_alert']['previous_events'])==1


@pytest.mark.parametrize('truth', [{}, {'source':'systemd','code':None,'invocation_id':'b'*32},
    {'source':'systemd','code':76,'invocation_id':'b'*32},
    {'source':'systemd','code':0,'invocation_id':'a'*32},
    {'source':'ledger','code':0,'invocation_id':'b'*32},
    {'source':'systemd','code':0,'active_state':'active','invocation_id':'b'*32}])
def test_core_unseen_failure_not_recovered_by_missing_or_old_truth(tmp_path,truth):
    ns=namespace(tmp_path);key='overfit_monitor|unit_exit!=0|76'
    row=new_failure(ns,event='core-e');ns['UNIT_STATES']={'trade-overfit-monitor.service':truth}
    ns['CONCLUSION_STATUS_KEY_PREFIX']='conclusion_status|'
    loop=next(n for n in TREE.body if isinstance(n,ast.For) and ast.unparse(n.target)=='(_key, _info)')
    exec(compile(ast.Module(body=[loop],type_ignores=[]),str(MONITOR),'exec'),ns)
    assert row['status']=='active' and row['requires_action'] is True


def test_core_new_verified_success_recovers_exit_only(tmp_path):
    ns=namespace(tmp_path);key='overfit_monitor|unit_exit!=0|76'
    row=new_failure(ns,event='core-e');ns['UNIT_STATES']={'trade-overfit-monitor.service':
        {'source':'systemd','code':0,'active_state':'inactive','invocation_id':'b'*32}}
    ns['CONCLUSION_STATUS_KEY_PREFIX']='conclusion_status|'
    loop=next(n for n in TREE.body if isinstance(n,ast.For) and ast.unparse(n.target)=='(_key, _info)')
    exec(compile(ast.Module(body=[loop],type_ignores=[]),str(MONITOR),'exec'),ns)
    assert row['status']=='recovered'  # exit status only, no NAV/content assertion


def test_notify_owned_config_health_survives_schedule_observation_and_stale_save(tmp_path):
    ns=namespace(tmp_path);key='notify|feishu_config_missing';path=ns['ALERT_STATE_FILE'];path.parent.mkdir()
    row={'status':'active','event_id':'notify-e','requires_action':True,'first_seen':'2026-11-11 10:00:00'}
    ns['alert_state']={key:dict(row)};ns['_STATE_PRE']={key:dict(row)}
    ns['CONCLUSION_STATUS_KEY_PREFIX']='conclusion_status|'
    loop=next(n for n in TREE.body if isinstance(n,ast.For) and ast.unparse(n.target)=='(_key, _info)')
    exec(compile(ast.Module(body=[loop],type_ignores=[]),str(MONITOR),'exec'),ns)
    assert ns['alert_state'][key]['status']=='active'  # schedule never checked this condition
    disk=dict(row,status='recovered',requires_action=False)
    path.write_text(json.dumps({key:disk}))
    ns['save_alert_state'](ns['alert_state'])
    assert json.loads(path.read_text())[key]==disk


def test_legacy_notification_history_migrates_as_unknown_audit(tmp_path):
    ns=namespace(tmp_path);key='task|fail';path=ns['ALERT_STATE_FILE'];path.parent.mkdir()
    row={'status':'active','first_seen':'2026-11-10 10:00:00','acknowledged':'old',
         'notified_at':'old-unverified','message':'SEVERE: task failure'}
    ns['_STATE_PRE']={key:dict(row)};path.write_text(json.dumps({key:row}))
    ns['save_alert_state']({key:row})
    stored=json.loads(path.read_text())[key]
    assert 'acknowledged' not in stored and 'notified_at' not in stored
    assert stored['previous_events'][-1]['notified_at']=='old-unverified'
    assert 'event_id' not in stored['previous_events'][-1]
