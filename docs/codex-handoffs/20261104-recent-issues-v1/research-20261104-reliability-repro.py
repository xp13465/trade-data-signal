#!/usr/bin/env python3
"""Offline AST harness: original function bodies; synthetic DB; no repo writes/import side effects."""
import ast, argparse, contextlib, io, json, sqlite3, sys, tempfile, time, types
from datetime import date, timedelta
from pathlib import Path
ROOT=Path('/Users/linhuichen/code/trade')
SOURCE=ROOT/'scripts/collect_fof_nav.py'
tree=ast.parse(SOURCE.read_text())
keep=[]
for node in tree.body:
    if isinstance(node, (ast.FunctionDef,ast.AsyncFunctionDef)) and node.name in {'collect','main'}:
        keep.append(node)
    elif isinstance(node, ast.Assign) and any(isinstance(t,ast.Name) and t.id in {'BATCH_SIZE','SELECT_SQL','UPSERT_SQL'} for t in node.targets):
        keep.append(node)
mod=ast.fix_missing_locations(ast.Module(body=keep,type_ignores=[]))
class FrozenDate(date):
    @classmethod
    def today(cls):return cls(2026,11,4)
result={}
with tempfile.TemporaryDirectory(dir='/tmp', prefix='trade-reliability-') as tmp:
    p=Path(tmp)/'test.db'
    def conn(): return sqlite3.connect(p)
    c=conn(); c.executescript('CREATE TABLE fund_basic(fund_code TEXT PRIMARY KEY,fund_name TEXT,fund_type TEXT); CREATE TABLE fund_daily_nav(date TEXT,fund_code TEXT,fund_name TEXT,unit_nav REAL,acc_nav REAL,prev_unit_nav REAL,nav_change_pct REAL,PRIMARY KEY(date,fund_code));');c.close()
    ns={'__name__':'isolated_collect','date':FrozenDate,'timedelta':timedelta,'argparse':argparse,'sys':sys,'time':types.SimpleNamespace(time=time.time,sleep=lambda _:None),'get_conn':conn,'init_db':lambda:None,'_acquire_lock':lambda **_:True,'RATE_LIMIT':0}
    exec(compile(mod,str(SOURCE),'exec'),ns)
    c=conn();c.execute('INSERT INTO fund_basic VALUES(?,?,?)',('005827','synthetic FOF','FOF-稳健型'));c.execute('INSERT INTO fund_daily_nav(date,fund_code,unit_nav) VALUES(?,?,?)',('20261029','005827',1.0));c.execute('INSERT INTO fund_daily_nav(date,fund_code,unit_nav) VALUES(?,?,?)',('20261102','005827',None));c.commit();c.close()
    called=[]
    def fetch(code,*_):
        called.append(code)
        return [{'date':'20261102','fund_code':code,'unit_nav':1.2,'acc_nav':1.2,'prev_unit_nav':1.0,'nav_change_pct':20.0}]
    ns['fetch_lsjz']=fetch
    log=io.StringIO()
    with contextlib.redirect_stdout(log): n=ns['collect']()
    c=conn(); nav=c.execute('SELECT unit_nav FROM fund_daily_nav WHERE date=?',('20261102',)).fetchone()[0];c.close()
    result['known_skip']={'written':n,'api_calls':called,'new_date_nav':nav,'log':log.getvalue()}
    assert called==[] and nav is None
    c=conn();c.execute('DELETE FROM fund_daily_nav');c.commit();c.close()
    def fail(*_):raise TimeoutError('offline simulated request timeout')
    ns['fetch_lsjz']=fail
    old_argv=sys.argv;sys.argv=['collect_fof_nav.py'];out=io.StringIO();err=io.StringIO()
    try:
        with contextlib.redirect_stdout(out),contextlib.redirect_stderr(err): rc=ns['main']()
    finally:sys.argv=old_argv
    result['all_network_failure']={'main_return':rc,'stdout':out.getvalue(),'stderr':err.getvalue()}
    assert rc==0 and 'fail=1' in out.getvalue() and 'FAIL' in out.getvalue()

# Real monitoring module, with only synthetic systemd and /tmp output paths.
from datetime import datetime
sys.path.insert(0,str(ROOT/'scripts'))
import gen_schedule_stats as gss
with tempfile.TemporaryDirectory(dir='/tmp', prefix='trade-monitor-reliability-') as td:
    p=Path(td);logs=p/'logs';logs.mkdir()
    (logs/'fof_nav_collect_20261104_2110.log').write_text(result['all_network_failure']['stdout'])
    frozen=datetime(2026,11,4,21,20)
    def fake_systemd(unit):
        return {'LoadState':'loaded','ActiveState':'inactive','Result':'success','ExecMainCode':'1','ExecMainStatus':'0','ExecMainStartTimestamp':'2026-11-04 21:10:00','ExecMainExitTimestamp':'2026-11-04 21:11:00','LastTriggerUSec':'2026-11-04 21:10:00','NextElapseUSecRealtime':'2026-11-05 21:10:00','InvocationID':'isolated-research'}
    old_mode=gss.ut.exit_source_mode
    gss.ut.exit_source_mode=lambda:'systemd'
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            gss.build(log_dir=logs,out=p/'stats.json',now=frozen,unit_reader=fake_systemd,ledger_path=p/'absent-ledger.json')
    finally:gss.ut.exit_source_mode=old_mode
    row=next(r for r in json.loads((p/'stats.json').read_text()) if r['task']=='fof_nav_collect')
    item={k:row[k] for k in ['task','last_exit','log_anomaly','unit_exit','unit_timer_health','exit_source']}
    item['fof_in_LOG_TASKS']='fof_nav_collect' in gss.LOG_TASKS
    item['FAIL_line_matches_ANOMALY_RE']=bool(gss.ANOMALY_RE.search(result['all_network_failure']['stdout']))
    result['monitor_on_synthetic_all_failure']=item
    assert row['last_exit']==0 and not row['log_anomaly'] and 'fof_nav_collect' not in gss.LOG_TASKS

# Concurrent digest producers: force both read-before-append windows, no send APIs.
import hashlib, os, re, threading
from concurrent.futures import ThreadPoolExecutor
notify_src=ROOT/'scripts/notify.py'
ntree=ast.parse(notify_src.read_text())
names={'_append_jsonl','_parse_buffer_lines','_ledger_key_of','_absorb_to_digest','_bump_digest_hits'}
nmod=ast.fix_missing_locations(ast.Module(body=[n for n in ntree.body if isinstance(n,ast.FunctionDef) and n.name in names],type_ignores=[]))
with tempfile.TemporaryDirectory(dir='/tmp', prefix='trade-digest-reliability-') as td:
    p=Path(td)/'digest.jsonl';p.touch()
    ns2={'Path':Path,'json':json,'os':os,'sys':sys,'datetime':datetime,'hashlib':hashlib,'re':re,'time':time,'ALERT_DIGEST_FILE':p,'DIGEST_ENTRY_BODY_LIMIT':3000}
    exec(compile(nmod,str(notify_src),'exec'),ns2)
    original_append=ns2['_append_jsonl'];barrier=threading.Barrier(2)
    def overlap_append(path,rec):
        barrier.wait(timeout=3)
        return original_append(path,rec)
    ns2['_append_jsonl']=overlap_append
    def producer(_):return ns2['_absorb_to_digest']('[恢复] synthetic','same event',key='same-key',category='recovery',bump_hits=True)
    with ThreadPoolExecutor(max_workers=2) as pool: answers=list(pool.map(producer,range(2)))
    entries=[json.loads(x) for x in p.read_text().splitlines()]
    result['digest_concurrent_same_key']={'returns':answers,'rows':len(entries),'keys':[x['key'] for x in entries],'hits':[x['hits'] for x in entries]}
    assert all(answers) and len(entries)==2 and len(set(x['key'] for x in entries))==1

# R2 domain barrier-open fault; only /tmp lock files, zero upload/network.
import fcntl
r2src=ROOT/'scripts/upload_r2.py'
r2tree=ast.parse(r2src.read_text())
rmod=ast.fix_missing_locations(ast.Module(body=[n for n in r2tree.body if isinstance(n,ast.FunctionDef) and n.name=='_acquire_r2_upload_lock'],type_ignores=[]))
with tempfile.TemporaryDirectory(dir='/tmp', prefix='trade-r2-lock-reliability-') as td:
    domain=Path(td)/'data.lock';global_p=Path(td)/'global.lock';opened=[]
    def fake_open(path,*args):
        if Path(path)==global_p:raise PermissionError('offline simulated barrier permissions')
        fd=os.open(path,*args);opened.append(fd);return fd
    os_proxy=types.SimpleNamespace(environ={},open=fake_open,close=os.close,O_CREAT=os.O_CREAT,O_RDWR=os.O_RDWR)
    ns3={'Path':Path,'os':os_proxy,'sys':sys,'time':time,'fcntl':fcntl,'_lock_domain':lambda:'data','_domain_upload_lock_path':lambda _:domain,'_global_upload_lock_path':lambda:global_p,'_BARRIER_FDS':{},'_R2_LOCK_HEARTBEAT_SECS':30}
    exec(compile(rmod,str(r2src),'exec'),ns3)
    out=io.StringIO()
    try:
        with contextlib.redirect_stderr(out):
            try:ns3['_acquire_r2_upload_lock'](timeout=0)
            except Exception as e:result['r2_barrier_open_fault']={'exception':type(e).__name__,'message':str(e),'stderr':out.getvalue()}
    finally:
        for fd in opened:
            try:os.close(fd)
            except OSError:pass
    assert result['r2_barrier_open_fault']['exception']=='IndexError'
print(json.dumps(result,ensure_ascii=False,indent=2))
