"""Actual complete nextday shell + actual Python main + notify, offline transport only."""
import json
import os
from pathlib import Path
import shutil

import pytest
from test_ops_quiet_producers_20261111 import runner, bounded_shell, SCRIPTS, DRIVER, transports, notifications

# Reuse existing audited subprocess dispatcher: no network/process creation after
# entry; all writes confined to temporary root. Actual producer source is imported
# with only external data/transport leaves replaced.
CHILD = r'''
if target.name in ("nextday_plan_generator.py", "nextday_gap_check.py"):
    if os.environ.get("TEST_CHILD_CRASH") == "1":
        sys.exit(2)  # before Python reports; real wrapper must cover it.
    import importlib.util
    sys.path.insert(0, str(Path(os.environ["TEST_SCRIPTS"]).parent))
    # Bare children do not load conftest; use its missing-only import shims.
    # No runtime HTTP API is provided, and DRIVER's audit traps remain active.
    sys.path.insert(0, str(Path(os.environ["TEST_SCRIPTS"]) / "tests"))
    from _ci_stubs import install_missing_third_party_stubs
    install_missing_third_party_stubs()
    spec = importlib.util.spec_from_file_location("real_producer", Path(os.environ.get("TEST_PRODUCER_SCRIPTS", os.environ["TEST_SCRIPTS"]))/target.name)
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    m.ROOT = m.REPO = m.GIT_REPO = root
    m._today = lambda: "20261111"
    if target.name == "nextday_plan_generator.py":
        m._load_json = lambda *a: {}
        m.appq._etf_freeze = lambda: {}
        m._etf_daily_dates = lambda *a: []  # actual early error rc2
    else:
        m._read_first = lambda paths, name: ({"plan":[{"buy_date":"20261111","etf_code":"1","prev_close":1}]} if name=="nextday_plan.json" else {"steps":[]}, None)
        m._recheck_stale_pending = lambda *a, **kw: False
        m._retry_plan = lambda *a, **kw: []
        m._fetch_opens = lambda *a, **kw: None  # actual failed validation rc2
        m._mark_unverified = lambda *a, **kw: None
        m._sync_r2_and_notify = lambda *a, **kw: (0,0)
    sys.argv = [str(target), *args]
    sys.exit(m.main())
'''


@pytest.fixture
def shell(runner):
    root, base = runner
    for name in ('nextday_plan.sh','nextday_gap_check.sh'):
        shutil.copyfile(Path(os.environ.get('LEGACY_BASELINE_DIR',str(SCRIPTS)))/name, root/'scripts'/name)
    (root/'scripts/lib').mkdir()
    shutil.copyfile(SCRIPTS/'lib/repo_paths.sh',root/'scripts/lib/repo_paths.sh')
    for command in ('dirname','basename','mkdir'):
        (root/'bin'/command).symlink_to(shutil.which(command))
    # Dispatcher loads actual ops and real notify first, then real producer.
    script = DRIVER.replace('assert target.name in ("notify.py", "ops_legacy_events.py")',
        'assert target.name in ("notify.py", "ops_legacy_events.py", "nextday_plan_generator.py", "nextday_gap_check.py")')
    script = script.replace('if target.name == "ops_legacy_events.py":\n', 'if target.name != "notify.py":\n')
    script = script.replace('    sys.exit(ops.main(args))', CHILD + '\n    sys.exit(ops.main(args))')
    # CHILD exits for actual producers; CLI exit belongs outside its conditional.
    script = script.replace('\n    sys.exit(ops.main(args))', '\nif target.name == "ops_legacy_events.py":\n    sys.exit(ops.main(args))')
    # Partial child transport + success on wrapper retry, persisted transport ledger.
    script = script.replace('        return True\n', '''        previous = [json.loads(line) for line in (root/"calls.jsonl").read_text().splitlines()]
        count = sum(r.get("channel") == name for r in previous)
        return not (os.environ.get("TEST_PARTIAL") == "1" and name != "email" and count == 1)
''',1)
    (root/'driver').write_text('#!'+ __import__('sys').executable + '\n'+script)
    def run(name, args=(), **env):
        proc=bounded_shell([base.bash,str(root/'scripts'/name),*args],{**base.env,'TEST_PRODUCER_SCRIPTS':os.environ.get('LEGACY_BASELINE_DIR',str(SCRIPTS)),**env},root)
        assert (root/'calls.jsonl').exists(), proc
        rec=[json.loads(l) for l in (root/'calls.jsonl').read_text().splitlines()]
        logs=''.join(p.read_text() for p in (root/'data/logs').glob('*.log'))
        assert 'Traceback' not in proc.stderr+logs, proc.stderr+logs
        return proc,rec
    return root, run


@pytest.mark.parametrize('name,task',[('nextday_plan.sh','nextday_plan'),('nextday_gap_check.sh','nextday_gap')])
def test_real_wrapper_child_partial_then_retry_only_missing_channels(shell,name,task):
    root,run=shell
    p,r=run(name,TEST_PARTIAL='1')
    assert p.returncode==2
    assert [v['channel'] for v in transports(r)]==['email','telegram','feishu','telegram','feishu']
    calls=notifications(r)
    assert len(calls)==2 and all('--ops-event-refs' in c for c in calls)
    refs=[json.loads(c[c.index('--ops-event-refs')+1]) for c in calls]
    assert refs[0]==refs[1]
    p,r=run(name)
    assert p.returncode==2 and len(transports(r))==5  # same unresolved fault
    st=json.loads((root/'data/alert_state.json').read_text())['producer_'+task+'|operation']
    assert st['status']=='active' and all(st['notified_channels'].values())


@pytest.mark.parametrize('name',['nextday_plan.sh','nextday_gap_check.sh'])
def test_real_wrapper_fallback_without_python_report(shell,name):
    _,run=shell
    p,r=run(name,TEST_CHILD_CRASH='1')
    assert p.returncode==2 and len(transports(r))==3
    assert len(notifications(r))==1


@pytest.mark.parametrize('name',['nextday_plan.sh','nextday_gap_check.sh'])
@pytest.mark.parametrize('args,env', [(['--dry-run'],{}),([],{"TEST_TRADING":"0"})])
def test_real_wrapper_diagnostics_and_calendar_skip_cannot_recover(shell,name,args,env):
    root,run=shell
    run(name,TEST_CHILD_CRASH='1')
    before=(root/'data/alert_state.json').read_bytes()
    _,r=run(name,args=args,**env)
    assert (root/'data/alert_state.json').read_bytes()==before
    assert len(transports(r))==3


def test_nav_transient_passes_only_two_opt_in_switches():
    src=(SCRIPTS/'update_all.sh').read_text()
    start=src.index('sudo -n systemd-run --collect --unit="fund-nav-upload-')
    section=src[start:src.index('bash "$REPO/scripts/fund_nav_upload_async.sh"',start)]
    actual=[s.strip().rstrip(' \\') for s in section.splitlines() if '--setenv=OPS_' in s]
    assert actual==[
        '--setenv=OPS_DELIVERY_EVIDENCE_ENABLED="${OPS_DELIVERY_EVIDENCE_ENABLED:-0}"',
        '--setenv=OPS_NAV_PUBLIC_READBACK_ENABLED="${OPS_NAV_PUBLIC_READBACK_ENABLED:-0}"',
    ]


@pytest.mark.parametrize('name',['nextday_plan.sh','nextday_gap_check.sh'])
def test_real_date_backfill_failure_keeps_operational_alert(shell,name):
    root,run=shell
    p,r=run(name,args=['--date','20261111'],TEST_PARTIAL='1')
    assert p.returncode==2
    assert [v['channel'] for v in transports(r)]==['email','telegram','feishu','telegram','feishu']
    calls=notifications(r)
    assert len(calls)==2 and all('--ops-event-refs' in c for c in calls)
