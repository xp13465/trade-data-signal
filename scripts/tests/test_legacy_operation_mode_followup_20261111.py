"""Independent-review regressions: real shell abbreviations and explicit daily argv."""
import json
import sys

import pytest
from test_legacy_operation_producers_20261111 import box, runtime, load, row
from test_legacy_operation_shell_20261111 import runner, shell, transports, notifications


@pytest.mark.parametrize('name,args',[
 ('nextday_plan.sh',['--dry']),
 ('nextday_gap_check.sh',['--dry']),
 ('nextday_plan.sh',['--no-not']),
 ('nextday_gap_check.sh',['--no-not']),
 ('nextday_gap_check.sh',['--test-o','1:1']),
 ('nextday_gap_check.sh',['--test-o=1:1']),
])
@pytest.mark.parametrize('prior_fault',[False,True])
def test_abbreviated_diagnostic_real_shell_never_alerts_or_mutates(shell,name,args,prior_fault):
    root,run=shell
    if prior_fault:
        run(name,TEST_CHILD_CRASH='1')
    state=root/'data/alert_state.json'
    before=state.read_bytes() if state.exists() else None
    proc,records=run(name,args=args)
    assert proc.returncode==2  # actual diagnostic child failure, not mocked shell exit
    assert (state.read_bytes() if state.exists() else None)==before
    assert len(transports(records))==(3 if prior_fault else 0)


def daily_fixture(runtime,monkeypatch):
    ops,b=runtime;root=b[-1];m=load('daily_summary_email')
    monkeypatch.setattr(m,'REPO',root)
    monkeypatch.setattr(m,'datetime',b[0].datetime)
    source=root/'summary_history.json'
    source.write_text(json.dumps({'items':[{'date':v,'fx_contract':'fx-excluded-v1'} for v in ['20200101','20261111','20990101']]}))
    monkeypatch.setattr(m,'SUMMARY_SRC',source)  # real date-selecting loader
    monkeypatch.setattr(m,'load_subscriptions',lambda:[])
    monkeypatch.setattr(m,'build_subject',lambda it:'report '+it['date'])
    monkeypatch.setattr(m,'build_text',lambda *a:'business body')
    monkeypatch.setattr(m,'build_html',lambda *a:'business html')
    sent=[]
    monkeypatch.setattr(m,'send_report_to_feishu',lambda subject,body:sent.append(subject) or True)
    token=ops.begin_operation(root,'daily_summary')
    ops.complete_operation(root,'daily_summary',token,failed=True,detail='current report missing')
    assert sys.argv==['offline-producer']
    return m,sent


@pytest.mark.parametrize('date',['20200101','20990101'])
@pytest.mark.parametrize('entry',['main_argv','direct_positional','direct_keywords'])
def test_historical_real_daily_arguments_never_recover_current(runtime,monkeypatch,date,entry):
    m,sent=daily_fixture(runtime,monkeypatch)
    old=row(runtime,'daily_summary')['event_id']
    if entry=='main_argv':
        rc=m.main([date])
    elif entry=='direct_positional':
        rc=m._run_main(date,False)
    else:
        rc=m._run_main(date=date,dry_run=False)
    assert rc==0 and sent==['report '+date]  # historical business report preserved
    st=row(runtime,'daily_summary')
    assert st['status']=='active' and st['event_id']==old and st['run_result']=='unknown'


@pytest.mark.parametrize('entry',['main_argv','direct_positional','direct_keywords'])
def test_current_real_daily_report_still_recovers(runtime,monkeypatch,entry):
    m,sent=daily_fixture(runtime,monkeypatch)
    if entry=='main_argv':
        rc=m.main([])
    elif entry=='direct_positional':
        rc=m._run_main('20261111',False)
    else:
        rc=m._run_main(date='20261111',dry_run=False)
    assert rc==0 and sent==['report 20261111']
    assert row(runtime,'daily_summary')['status']=='recovered'


@pytest.mark.parametrize('argv',[['--dry'],['--mode','supplement']])
def test_explicit_daily_dry_or_other_mode_never_recovers(runtime,monkeypatch,argv):
    m,sent=daily_fixture(runtime,monkeypatch)
    monkeypatch.setattr(m,'_is_trading_day',lambda:False)
    before=row(runtime,'daily_summary')
    assert m.main(argv)==0
    assert row(runtime,'daily_summary')==before and not sent


@pytest.mark.parametrize('name',['nextday_plan.sh','nextday_gap_check.sh'])
def test_begin_metadata_failure_is_not_disabled_and_keeps_real_fallback(shell,name):
    root,run=shell
    state=root/'data/alert_state.json'
    state.write_bytes(b'{broken state')
    proc,records=run(name)
    assert proc.returncode==2 and state.read_bytes()==b'{broken state'
    calls=notifications(records)
    assert calls and len(transports(records))>=3
    assert all('--ops-event-refs' not in c and '--dedup-window' in c for c in calls)
    assert all(c[c.index('--tier')+1]=='critical' for c in calls)


@pytest.mark.parametrize('name',['nextday_plan.sh','nextday_gap_check.sh'])
def test_invalid_real_shell_arguments_are_not_mislabeled_diagnostic(shell,name):
    _,run=shell
    proc,records=run(name,args=['--unsupported-mode'])
    assert proc.returncode==2 and len(transports(records))==3
    assert '--ops-event-refs' in notifications(records)[0]


@pytest.mark.parametrize('name,task',[
 ('nextday_plan.sh','nextday_plan'),('nextday_gap_check.sh','nextday_gap'),
])
@pytest.mark.parametrize('flag',['--help','-h','--he','--h'])
@pytest.mark.parametrize('pending_execution',[False,True])
def test_real_help_is_inert_and_preserves_pending_failure_token(shell,runner,name,task,flag,pending_execution):
    from test_ops_quiet_producers_20261111 import bounded_shell
    root,run=shell
    runner_root,base=runner
    assert root==runner_root
    def cli(action,*args):
        return bounded_shell([str(root/'driver'),str(root/'scripts/ops_legacy_events.py'),
                              action,'--repo',str(root),'--task',task,*args],base.env,root)
    state=root/'data/alert_state.json'
    token=None
    if pending_execution:
        begin=cli('begin')
        assert begin.returncode==0
        token=begin.stdout.strip()
        assert token and json.loads(state.read_text())['producer_'+task+'|operation']['producer_run']==token
    before=state.read_bytes() if state.exists() else None
    proc,records=run(name,args=[flag])
    after_help=state.read_bytes() if state.exists() else None
    assert proc.returncode==0 and not transports(records)
    if token:
        # Real pending execution completes AFTER real help, using the real CLI.
        failure=cli('fail','--run',token,'--detail','genuine in-flight failure')
        assert failure.returncode==0 and 'superseded' not in failure.stdout
        st=json.loads(state.read_text())['producer_'+task+'|operation']
        assert st['status']=='active' and st['requires_action'] is True
        assert st['notified_event_id']==st['event_id'] and all(st['notified_channels'].values())
        records=[json.loads(line) for line in (root/'calls.jsonl').read_text().splitlines()]
        assert len(transports(records))==3
    assert after_help==before  # no create, token replacement or byte-level state change


@pytest.mark.parametrize('name',['nextday_plan.sh','nextday_gap_check.sh'])
@pytest.mark.parametrize('flag',['--help=value','--he=value','--h=value','-h=value'])
def test_invalid_help_value_remains_fail_visible(shell,name,flag):
    _,run=shell
    proc,records=run(name,args=[flag])
    assert proc.returncode==2 and len(transports(records))==3
    assert '--ops-event-refs' in notifications(records)[0]
