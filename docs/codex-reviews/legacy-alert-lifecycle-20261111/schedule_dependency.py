"""Read-only extraction of actual schedule functions, temp-only state, zero subprocess."""
import copy, fcntl, hashlib, json, os, sys, tempfile, time
from datetime import datetime, timedelta
from pathlib import Path
ROOT=Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'scripts'))
from ops_legacy_events import observe
import alert_denoise_rules as adr
source=(ROOT/'scripts/schedule_monitor.sh').read_text()
with tempfile.TemporaryDirectory(prefix='legacy-schedule-dependency-') as temp:
    root=Path(temp); statepath=root/'data/alert_state.json'
    key='producer_heartbeat|offline'
    def fault(): return {'action': True, 'message': 'still missing heartbeat'}
    observe(root,key,fault)
    st=json.loads(statepath.read_text())
    env=dict(globals(), alert_state=st, NOW=datetime.now(), seen_keys_this_run=set(),
        in_progress_tasks=set(), recoveries=[], CONCLUSION_STATUS_KEY_PREFIX='monitor_conclusion|',
        RECOVERY_COOLDOWN=timedelta(hours=6), _recovery_cooldown_ok=lambda *a:False,
        ALERT_STATE_FILE=statepath, _STATE_PRE=copy.deepcopy(st))
    block=source[source.index('for _key, _info in list(alert_state.items()):'):source.index('# 2026-08-24 孤儿告警回收')]
    exec(compile(block,'schedule-recovery-real-source','exec'),env)
    assert st[key]['status']=='recovered'
    print('DEPENDENCY_REPRODUCED: schedule falsely recovers unobserved external producer')
    old_snapshot=copy.deepcopy(st)
    observe(root,key,lambda:{'action':False,'message':'actual healthy observation'})
    observe(root,key,fault)
    new_id=json.loads(statepath.read_text())[key]['event_id']
    section=source[source.index('STATE_ACK_FIELDS ='):source.index('def _diff_transition')]
    exec(compile(section,'schedule-save-real-source','exec'),env)
    assert env['save_alert_state'](old_snapshot)
    now=json.loads(statepath.read_text())[key]
    assert now['event_id'] != new_id and now['status']=='recovered'
    print('DEPENDENCY_REPRODUCED: stale schedule snapshot overwrites new producer event')
