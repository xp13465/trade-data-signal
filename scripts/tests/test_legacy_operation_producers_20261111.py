"""Real operation entrypoints + notify CLI; only data/transport boundaries faked."""
import importlib.util
import io
import json
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
import subprocess
import sys

import pytest
from test_notify_ops_quiet_20261111 import box, SCRIPTS


@pytest.fixture
def runtime(box, monkeypatch):
    import ops_legacy_events as ops
    n, clock, _, wire, accepted, _, state, *_ = box
    root = box[-1]
    def run(cmd, **kw):
        assert Path(cmd[1]).name == 'notify.py', cmd
        assert kw['env']['REPO'] == str(root)
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = n.main(cmd[2:])
        return subprocess.CompletedProcess(cmd, rc, out.getvalue(), err.getvalue())
    monkeypatch.setattr(subprocess, 'run', run)
    monkeypatch.setattr(sys, 'argv', ['offline-producer'])
    for k in ('OPS_LEGACY_TASK', 'OPS_LEGACY_RUN', 'OPS_LEGACY_LOG'):
        monkeypatch.delenv(k, raising=False)
    return ops, box


def load(name):
    spec = importlib.util.spec_from_file_location('operation_' + name, SCRIPTS / (name + '.py'))
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    return m


def row(rt, task):
    ops, b = rt
    return b[6]()[ops.operation_key(task)]


def test_same_fault_partial_wrapper_retry_then_no_periodic_repeat(runtime):
    ops, b = runtime
    root, wire, accepted = b[-1], b[3], b[4]
    token = ops.begin_operation(root, 'nextday_plan')
    accepted.update(email=True, telegram=False, feishu=False)
    assert ops.complete_operation(root, 'nextday_plan', token, failed=True, detail='real child failure') == 'partial'
    first = row(runtime, 'nextday_plan')['event_id']
    accepted.update(telegram=True, feishu=True)
    assert ops.complete_operation(root, 'nextday_plan', token, failed=True, detail='wrapper rc1') == 'sent'
    assert [w['channel'] for w in wire] == ['email','telegram','feishu','telegram','feishu']
    assert row(runtime, 'nextday_plan')['message'] == 'real child failure'
    next_run = ops.begin_operation(root, 'nextday_plan')
    assert ops.complete_operation(root, 'nextday_plan', next_run, failed=True, detail='same failure') == 'suppressed'
    assert row(runtime, 'nextday_plan')['event_id'] == first and len(wire) == 5


def test_late_success_or_failure_cannot_overwrite_newer_result(runtime):
    ops, b = runtime; root=b[-1]
    a=ops.begin_operation(root, 'daily_summary')
    c=ops.begin_operation(root, 'daily_summary')
    ops.complete_operation(root,'daily_summary',c,failed=True,detail='new fault')
    before=row(runtime,'daily_summary')
    assert ops.complete_operation(root,'daily_summary',a,health='report_accepted')=='superseded'
    assert ops.complete_operation(root,'daily_summary',a,failed=True,detail='old failure')=='superseded'
    assert row(runtime,'daily_summary')==before and len(b[3])==3


def test_daily_actual_acceptance_recovers_new_fault_does_not_inherit_ack(runtime, monkeypatch):
    ops,b=runtime; m=load('daily_summary_email');root=b[-1]
    monkeypatch.setattr(m,'datetime',b[0].datetime)
    monkeypatch.setattr(m,'REPO',root)
    monkeypatch.setattr(m,'load_summary_item',lambda day:{'date':day})
    monkeypatch.setattr(m,'load_subscriptions',lambda:[])
    monkeypatch.setattr(m,'build_subject',lambda it:'business subscription retained')
    monkeypatch.setattr(m,'build_text',lambda *a:'body')
    monkeypatch.setattr(m,'build_html',lambda *a:'<p>body</p>')
    sent=[]; accepted=[False]
    monkeypatch.setattr(m,'send_report_to_feishu',lambda s,t:sent.append(s) or accepted[0])
    assert m._run_main('20261111',False)==1
    first=row(runtime,'daily_summary'); key=ops.operation_key('daily_summary')
    b[7]([{'key':key}],ack_event_id=first['event_id'],acknowledged='now')
    # No data rc0 and dry rendering do NOT recover.
    monkeypatch.setattr(m,'load_summary_item',lambda day:None)
    assert m._run_main('20261111',False)==0
    assert row(runtime,'daily_summary')['status']=='active'
    monkeypatch.setattr(m,'load_summary_item',lambda day:{'date':day})
    accepted[0]=True
    assert m._run_main('20261111',True)==0
    assert row(runtime,'daily_summary')['status']=='active'
    assert m._run_main('20261111',False)==0
    assert row(runtime,'daily_summary')['status']=='recovered'
    accepted[0]=False
    assert m._run_main('20261111',False)==1
    latest=row(runtime,'daily_summary')
    assert latest['event_id']!=first['event_id'] and 'ack_event_id' not in latest
    assert len(b[3])==6 and len(sent)==3


@pytest.mark.parametrize('args',[['--dry-run'],['--test-open','000001:1'],['--no-r2'],['--no-notify']])
def test_disabled_modes_never_mutate_or_emit(runtime,monkeypatch,args):
    ops,b=runtime;root=b[-1]
    token=ops.begin_operation(root,'nextday_gap')
    ops.complete_operation(root,'nextday_gap',token,failed=True,detail='old fault')
    before=row(runtime,'nextday_gap')
    @ops.tracked_operation('nextday_gap',repo=lambda:root)
    def actual_wrapper():
        ops.operation_failure('test fault','not production')
        ops.operation_health('targets_verified_no_write')
        return 0
    monkeypatch.setattr(sys,'argv',['producer',*args])
    assert actual_wrapper()==0
    assert row(runtime,'nextday_gap')==before and len(b[3])==3


def test_gap_full_entry_prices_without_original_scope_and_noop_stay_unknown(runtime,monkeypatch):
    ops,b=runtime;root=b[-1];m=load('nextday_gap_check')
    monkeypatch.setattr(m,'REPO',root); monkeypatch.setattr(m,'ROOT',root); monkeypatch.setattr(m,'GIT_REPO',root)
    monkeypatch.setattr(m,'_today',lambda:'20261111')
    plan={'plan':[{'buy_date':'20261111','etf_code':'000001','prev_close':1}]}
    monkeypatch.setattr(m,'_read_first',lambda paths,name:(plan if name=='nextday_plan.json' else {'steps':[]},None))
    monkeypatch.setattr(m,'_recheck_stale_pending',lambda *a,**k:False)
    monkeypatch.setattr(m,'_fetch_opens',lambda *a,**k:{'000001':1})
    token=ops.begin_operation(root,'nextday_gap')
    ops.complete_operation(root,'nextday_gap',token,failed=True,detail='open missing',kind='validation')
    assert m.main()==0
    assert row(runtime,'nextday_gap')['status']=='active'
    assert row(runtime,'nextday_gap')['run_result']=='unknown'
    token=ops.begin_operation(root,'nextday_gap')
    ops.complete_operation(root,'nextday_gap',token,failed=True,detail='upload failure',kind='execution')
    assert m.main()==0
    assert row(runtime,'nextday_gap')['status']=='active'  # verified prices cannot repair publication
    plan['plan']=[]
    assert m.main()==0 and row(runtime,'nextday_gap')['status']=='active'


def test_corrupt_state_fails_visible_without_overwrite(runtime):
    ops,b=runtime;root=b[-1]
    path=root/'data/alert_state.json';path.write_text('{bad')
    assert ops.complete_operation(root,'update_all','missing',failed=True,detail='real fault')=='unknown'
    assert len(b[3])==3 and path.read_text()=='{bad'


def test_unknown_success_never_retires_plan_or_update_fault(runtime):
    ops,b=runtime;root=b[-1]
    for task in ('update_all','nextday_plan'):
        token=ops.begin_operation(root,task)
        ops.complete_operation(root,task,token,failed=True,detail='publish failure')
        token=ops.begin_operation(root,task)
        assert ops.complete_operation(root,task,token,detail='rc0')=='unknown'
        assert row(runtime,task)['status']=='active'


def test_added_failure_class_cannot_inherit_old_ack(runtime):
    ops,b=runtime;root=b[-1];task='nextday_gap';key=ops.operation_key(task)
    token=ops.begin_operation(root,task)
    ops.complete_operation(root,task,token,failed=True,detail='missing prices',kind='validation')
    old=row(runtime,task)['event_id']
    b[7]([{'key':key}],ack_event_id=old,acknowledged='yes')
    token=ops.begin_operation(root,task)
    assert ops.complete_operation(root,task,token,failed=True,detail='new upload failure',kind='execution')=='sent'
    assert row(runtime,task)['event_id']!=old
    assert 'ack_event_id' not in row(runtime,task) and len(b[3])==6
    assert set(row(runtime,task)['fault_kinds'])=={'validation','execution'}


def test_delayed_completion_thread_does_not_overwrite_new_failure(runtime):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    ops,b=runtime;root=b[-1];task='daily_summary'
    old=ops.begin_operation(root,task)
    ready,release=threading.Event(),threading.Event()
    def delayed():
        ready.set();assert release.wait(5)
        return ops.complete_operation(root,task,old,health='report_accepted')
    with ThreadPoolExecutor(max_workers=1) as pool:
        future=pool.submit(delayed);assert ready.wait(5)
        new=ops.begin_operation(root,task)
        ops.complete_operation(root,task,new,failed=True,detail='newest failure')
        before=row(runtime,task)
        release.set();assert future.result(5)=='superseded'
    assert row(runtime,task)==before and len(b[3])==3


def test_no_result_file_despite_rc0_and_success_text_is_unknown(runtime,monkeypatch):
    ops,b=runtime
    monkeypatch.setattr(subprocess,'run',lambda cmd,**kw:subprocess.CompletedProcess(cmd,0,'sent',''))
    token=ops.begin_operation(b[-1],'nextday_plan')
    assert ops.complete_operation(b[-1],'nextday_plan',token,failed=True,detail='fault')=='unknown'
    assert row(runtime,'nextday_plan')['status']=='active'
    assert not row(runtime,'nextday_plan').get('notified_event_id')


def test_missing_state_or_malformed_old_entry_cannot_silence_failure(runtime):
    ops,b=runtime;root=b[-1];task='update_all';key=ops.operation_key(task)
    for value in ({}, {key:{'status':'active','event_id':'old','ack_event_id':'old','acknowledged':True}}):
        (root/'data/alert_state.json').write_text(json.dumps(value))
        token=ops.begin_operation(root,task)
        assert ops.complete_operation(root,task,token,failed=True,detail='real fault')=='sent'
        assert 'ack_event_id' not in row(runtime,task)
    assert len(b[3])==6


def test_rc0_unknown_does_not_touch_legacy_noref_queue(runtime):
    ops,b=runtime;root=b[-1]
    p=root/'data/alerts/warning_buffer.jsonl'
    legacy=b'{"subject":"nextday failure","body":"no trustworthy identity"}\n'
    p.write_bytes(legacy)
    token=ops.begin_operation(root,'nextday_plan')
    assert ops.complete_operation(root,'nextday_plan',token,detail='rc0 no proof')=='unknown'
    assert p.read_bytes()==legacy
    assert row(runtime,'nextday_plan')['run_result']=='unknown'


def test_real_gap_stale_marker_cannot_certify_recovery(runtime,monkeypatch):
    ops,b=runtime;root=b[-1];m=load('nextday_gap_check')
    m.REPO=m.ROOT=m.GIT_REPO=root
    m._today=lambda:'20261111'
    plan={'plan':[{'buy_date':'20261111','etf_code':'1','prev_close':1}]}
    steps={'steps':[{'date':'20261111','etf_code':'1','action':'buy','status':'pending','status_text':'伪跳空校验未完成(待人工)'}]}
    m._read_first=lambda paths,name:(plan if name=='nextday_plan.json' else steps,None)
    m._recheck_stale_pending=lambda *a,**kw:False
    m._fetch_opens=lambda *a,**kw:{'1':1}
    token=ops.begin_operation(root,'nextday_gap')
    ops.complete_operation(root,'nextday_gap',token,failed=True,detail='old price missing',kind='validation')
    assert m.main()==0
    assert row(runtime,'nextday_gap')['status']=='active'
    assert row(runtime,'nextday_gap')['run_result']=='unknown'


def test_real_gap_recheck_sync_failure_is_visible_even_when_business_rc0(runtime,monkeypatch):
    ops,b=runtime;root=b[-1];m=load('nextday_gap_check')
    m.REPO=m.ROOT=m.GIT_REPO=root
    m._today=lambda:'20261111'
    m._read_first=lambda paths,name:({'plan':[]} if name=='nextday_plan.json' else {'steps':[]},None)
    m._recheck_stale_pending=lambda *a,**kw:True
    m._persist_steps=lambda *a,**kw:None
    m._sync_r2_and_notify=lambda *a,**kw:(1,0)
    assert m.main()==0  # preserve original business exit contract
    assert row(runtime,'nextday_gap')['status']=='active' and len(b[3])==3


@pytest.mark.parametrize('task,args,expected',[
 ('nextday_plan',['--date','20200101'],(True,False)),
 ('nextday_plan',['--date=20200101'],(True,False)),
 ('nextday_plan',['--no-backfill'],(True,False)),
 ('nextday_plan',['--repair-backfill'],(True,False)),
 ('nextday_gap',['--date','20200101'],(True,False)),
 ('nextday_gap',['--no-retry'],(True,False)),
 ('nextday_gap',['--retry-targets','09:28:00,09:31:00'],(True,True)),
 ('nextday_gap',['--recheck-pending'],(True,False)),
 ('nextday_gap',['--test-open=1:1'],(False,False)),
 ('daily_summary',['20200101'],(True,False)),
 ('daily_summary',['--mode=main'],(True,True)),
 ('daily_summary',['--dry-run'],(False,False)),
])
def test_explicit_mode_alert_vs_recovery_permissions(runtime,task,args,expected):
    assert runtime[0].operation_mode(task,args)==expected


def test_actual_exception_details_and_history_cannot_recover(runtime,monkeypatch):
    # app.collector.base has an import-time SWS DNS probe. Replace that leaf
    # explicitly; every other network/process trap from box remains active.
    import socket
    def dns(host,port,*a,**kw):
        assert host == 'www.swsresearch.com' and port == 443
        return [(socket.AF_INET,socket.SOCK_STREAM,6,'',('127.0.0.1',port))]
    monkeypatch.setattr(socket,'getaddrinfo',dns)
    ops,b=runtime;root=b[-1];m=load('nextday_plan_generator')
    m.REPO=m.ROOT=m.GIT_REPO=root
    def broken(*a):
        raise ValueError('precise input fault')
    m._load_json=broken
    monkeypatch.setattr(sys,'argv',['nextday_plan_generator.py','--date','20200101'])
    with pytest.raises(ValueError,match='precise input fault'):
        m.main()
    r=row(runtime,'nextday_plan')
    assert 'ValueError: precise input fault' in r['message']
    assert 'Traceback' in r['message'] and 'nextday_plan_launchd.log' in r['message']
    assert len(b[3])==3
    token=ops.begin_operation(root,'nextday_gap')
    ops.complete_operation(root,'nextday_gap',token,failed=True,detail='current fault',kind='validation')
    @ops.tracked_operation('nextday_gap',repo=lambda:root)
    def history():
        ops.operation_health('targets_verified_no_write')
        return 0
    assert history()==0
    assert row(runtime,'nextday_gap')['status']=='active'
    assert row(runtime,'nextday_gap')['run_result']=='unknown'


def test_current_prices_cannot_close_unscoped_historical_asset_fault(runtime):
    ops,b=runtime;root=b[-1];task='nextday_gap'
    token=ops.begin_operation(root,task)
    ops.complete_operation(root,task,token,failed=True,
        detail='执行日 20261110 ETF_A 缺真实开盘价，旧产物仍待人工',kind='validation')
    token=ops.begin_operation(root,task)
    assert ops.complete_operation(root,task,token,
        health='targets_verified_no_write',detail='20261111 ETF_B 当前校验通过')=='unknown'
    assert row(runtime,task)['status']=='active'
