#!/usr/bin/env python3
"""Exercise the real local Workers/D1 runtime. Never reads production credentials."""
from __future__ import annotations
import argparse
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone

ROOT = Path(__file__).resolve().parents[3]
WRANGLER = ROOT / 'node_modules/wrangler/bin/wrangler.js'
CONFIG = ROOT / 'ops/monitoring/wrangler.local.jsonc'

def stamp(seconds=0):
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat().replace('+00:00', 'Z')

def session(secret, uid):
    def b64(data): return base64.urlsafe_b64encode(data).decode().rstrip('=')
    body = b64(json.dumps({'provider': 'fixture', 'provider_uid': uid, 'user_id': uid, 'exp': int(time.time())+3600}).encode())
    return body+'.'+b64(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--browser', action='store_true')
    parser.add_argument('--snapshot-file', type=Path, help='Optional read-only real observation to validate against local ingest')
    args = parser.parse_args()
    config = json.loads(CONFIG.read_text())
    for kind in ('kv_namespaces', 'r2_buckets', 'd1_databases'):
        if any(b.get('remote') is not False for b in config.get(kind, [])):
            raise RuntimeError('local-only bindings required')
    if config['name'] != 'trade-ops-local': raise RuntimeError('local worker required')
    results = []
    def check(name, value):
        if not value: raise AssertionError(name)
        results.append(name)
    with tempfile.TemporaryDirectory(prefix='trade-ops-local-') as temp:
        base = Path(temp)
        ingest, admin, ss = (secrets.token_urlsafe(36) for _ in range(3))
        envfile = base / 'local.env'
        envfile.write_text(f'OPS_INGEST_TOKEN={ingest}\nOPS_ADMIN_TOKEN={admin}\nSESSION_SECRET={ss}\nADMIN_USERS=fixture:admin\nOPS_ALERT_ENABLED=false\n')
        envfile.chmod(0o600)
        env = {**os.environ, 'WRANGLER_SEND_METRICS': 'false', 'CLOUDFLARE_LOAD_DEV_VARS_FROM_DOT_ENV': 'true', 'CLOUDFLARE_INCLUDE_PROCESS_ENV': 'false'}
        # Explicit env-file and local config: no default .env or remote namespaces.
        common = ['node', str(WRANGLER)]
        flags = ['--config', str(CONFIG), '--env-file', str(envfile)]
        persist = base / 'state'
        with (base / 'runtime.log').open('w+') as logs:
            migration = subprocess.run(common + ['d1', 'migrations', 'apply', 'OPS_DB', '--local', '--persist-to', str(persist)] + flags, cwd=ROOT, env=env, stdout=logs, stderr=logs, input='y\n', text=True, timeout=90)
            if migration.returncode:
                logs.flush(); logs.seek(0)
                detail = logs.read()
                for value in (ingest, admin, ss): detail = detail.replace(value, '[redacted]')
                raise RuntimeError('local migration failed: '+detail[-3500:])
            with socket.socket() as sock:
                sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
            origin = f'http://127.0.0.1:{port}'
            process = subprocess.Popen(common + ['dev', '--local', '--ip', '127.0.0.1', '--port', str(port), '--persist-to', str(persist), '--test-scheduled', '--log-level', 'error'] + flags, cwd=ROOT, env=env, stdout=logs, stderr=logs)
            def call(path, method='GET', body=None, role='admin', headers=None):
                h = {'Content-Type': 'application/json'}
                if role == 'admin': h['X-Ops-Admin-Token'] = admin
                elif role == 'ingest': h['Authorization'] = 'Bearer '+ingest
                elif role in ('member', 'session-admin'): h['Cookie'] = 'session='+session(ss,'admin' if role=='session-admin' else 'member')
                h.update(headers or {})
                raw = body if isinstance(body, bytes) else (json.dumps(body).encode() if body is not None else None)
                request = urllib.request.Request(origin+path, raw, h, method=method)
                try: response = urllib.request.urlopen(request, timeout=10)
                except urllib.error.HTTPError as error: response = error
                with response:
                    data = response.read(2*1024*1024)
                    try: data = json.loads(data)
                    except (ValueError, UnicodeDecodeError): pass
                    return response.status, dict(response.headers), data
            try:
                deadline = time.monotonic()+40
                while True:
                    try:
                        status, _, _ = call('/api/ops/state',role=None)
                        break
                    except (OSError, urllib.error.URLError):
                        if process.poll() is not None or time.monotonic()>deadline: raise RuntimeError('local Worker failed to start')
                        time.sleep(.15)
                for role in (None, 'member', 'ingest'):
                    denied = call('/api/ops/state',role=role)
                    check('private read denied '+str(role)+' '+str(denied[0])+' '+str(denied[2]), denied[0] in (401,403))
                status, headers, state = call('/api/ops/state')
                check('empty state unknown', status==200 and state['latest'] is None and state['collector_status']=='unknown')
                check('private no-store/no CORS', 'no-store' in headers.get('Cache-Control','') and 'Access-Control-Allow-Origin' not in headers)
                check('allowlisted session admin', call('/api/ops/state',role='session-admin')[0]==200)
                def snapshot(status='ok', seconds=0):
                    ts=stamp(seconds)
                    return {'schema_version':1,'snapshot_id':str(uuid.uuid4()),'collector_id':'smoke','collected_at':ts,'code_ref':'d4238f5b24aa1aa5632dd5fed1098ce9fbdb3620','duration_ms':30,'coverage':{'counts':{'observed':1},'limitations':['local fixture; not production evidence']},'checks':[{'id':'service:smoke','name':'Fixture service','category':'service','status':status,'observed_at':ts,'summary':'Local runtime fixture','evidence':{'result':'fixture','exit_code':0 if status=='ok' else 2}}]}
                ok=snapshot(seconds=-4)
                check('viewer cannot ingest',call('/api/ops/ingest','POST',ok)[0] in (401,403))
                check('ingest succeeds',call('/api/ops/ingest','POST',ok,'ingest')[0] in (200,201,202))
                failed=snapshot('critical',-3)
                check('failure ingest',call('/api/ops/ingest','POST',failed,'ingest')[0] in (200,201,202))
                before=call('/api/ops/events')[2]['events']
                check('duplicate upload idempotent',call('/api/ops/ingest','POST',failed,'ingest')[0] in (200,201,202) and len(call('/api/ops/events')[2]['events'])==len(before))
                changed=json.loads(json.dumps(failed));changed['checks'][0]['status']='ok'
                check('conflicting snapshot rejected',call('/api/ops/ingest','POST',changed,'ingest')[0]==409)
                older=snapshot('ok',-60)
                check('out-of-order accepted safely',call('/api/ops/ingest','POST',older,'ingest')[0] in (200,201,202))
                state=call('/api/ops/state')[2]
                check('older upload cannot regress latest',state['latest']['snapshot_id']==failed['snapshot_id'])
                recovered=snapshot('ok',-1)
                check('recovery accepted',call('/api/ops/ingest','POST',recovered,'ingest')[0] in (200,201,202))
                events=call('/api/ops/events')[2]['events']
                check('failure and recovery recorded', len(events)>=2)
                check('future evidence rejected',call('/api/ops/ingest','POST',snapshot(seconds=3600),'ingest')[0] in (400,422))
                check('oversized ingest rejected',call('/api/ops/ingest','POST',b' '*270000,'ingest')[0]==413)
                history=call('/api/ops/history')[2]['runs']
                check('persistent run history',len(history)==4)
                # An envelope clock cannot override a newer observation clock.
                known_bad=snapshot('critical')
                known_bad['collector_id']='clock-fixture';known_bad['checks'][0]['id']='service:clock-fixture'
                check('current observation stored',call('/api/ops/ingest','POST',known_bad,'ingest')[0]==200)
                older_check=snapshot('ok',.05)
                older_check['collector_id']='clock-fixture';older_check['checks'][0]['id']='service:clock-fixture'
                older_check['checks'][0]['observed_at']=stamp(-10)
                check('new envelope old check accepted safely',call('/api/ops/ingest','POST',older_check,'ingest')[0]==200)
                current=call('/api/ops/state')[2]
                check('API does not hide known critical behind old OK',current['latest']['checks'][0]['status']=='critical' and current['counts']['critical']>=1)
                # Run the actual deployed CLI against empty local source fixtures.
                # Unknown coverage must still pass the real server safety contract.
                source_data=base/'source-data';source_data.mkdir(mode=0o700)
                token_file=base/'ingest.token';token_file.write_text(ingest);token_file.chmod(0o600)
                collector_config=base/'collector.json'
                collector_config.write_text(json.dumps({'collector_id':'smoke-cli','code_root':str(ROOT),'data_root':str(source_data),'output_dir':str(base/'collected'),'ingest_url':origin+'/api/ops/ingest','secret_file':str(token_file),'total_timeout_seconds':20,'command_timeout_seconds':1}))
                cli=subprocess.run(['python3',str(ROOT/'scripts/ops_monitor.py'),'--config',str(collector_config),'--once','--test-local-http'],cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=32)
                check('real collector CLI uploads accepted snapshot '+cli.stderr[-150:],cli.returncode==0)
                state=call('/api/ops/state')[2]
                check('real collector covers registry and data groups',state['latest']['collector_id']=='smoke-cli' and state['latest']['coverage']['counts'].get('registry_services')==45 and state['latest']['coverage']['counts'].get('asset_groups')==34)
                check('partial source failure remains unknown',state['counts']['unknown']>0)
                if args.snapshot_file:
                    raw=args.snapshot_file.read_bytes()
                    observed=json.loads(raw)
                    check('real cloud observation accepted by local API',call('/api/ops/ingest','POST',observed,'ingest')[0] in (200,201,202))
                knowledge=call('/api/ops/knowledge')[2]
                check('full versioned knowledge',len(knowledge['records'])>=360)
                check('private host paths removed','/tmp/' not in json.dumps(knowledge) and '/home/ubuntu/' not in json.dumps(knowledge))
                issues=call('/api/ops/incidents')[2]['incidents']
                check('recent incidents present',len(issues)>=18)
                item=issues[0]; issueid=item['id']
                from urllib.parse import quote
                update={'expected_revision':item.get('revision',0),'workflow_status':'observing','root_cause_state':'保留原调查结论','remediation_state':'本地演练','deployment_state':'未部署','verification_state':'本地验证','observation_status':'pending','note':'local smoke only','evidence_url':'https://example.invalid/local-evidence'}
                path='/api/ops/incidents/'+quote(issueid,safe='')
                h={'X-Ops-Intent':'update','Origin':origin}
                check('ingest cannot edit incidents',call(path,'POST',update,'ingest',h)[0] in (401,403))
                check('incident revision stored',call(path,'POST',update,'admin',h)[0] in (200,201))
                check('optimistic conflict protected',call(path,'POST',update,'admin',h)[0]==409)
                check('cross-origin write denied',call(path,'POST',{**update,'expected_revision':1},'session-admin',{'Origin':'https://attacker.invalid','X-Ops-Intent':'update'})[0] in (401,403))
                check('private export available',call('/api/ops/export')[0]==200)
                check('scheduled watchdog executes',call('/cdn-cgi/local/scheduled?format=json',role=None)[0]==200)
                status, shellheaders, shell=call('/admin/ops.html',role=None)
                check('empty public shell no private snapshot',status==200 and isinstance(shell,bytes) and b'Fixture service' not in shell)
                check('admin code uncached','no-store' in shellheaders.get('Cache-Control',''))
                if args.browser:
                    from playwright.sync_api import sync_playwright
                    with sync_playwright() as pw:
                        browser=pw.chromium.launch(executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless=True)
                        for width,height in ((1440,1000),(390,844)):
                            page=browser.new_page(viewport={'width':width,'height':height})
                            errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                            page.goto(origin+'/admin/ops.html')
                            # Valid same-origin admin session; no token in URLs or browser storage.
                            page.context.add_cookies([{'name':'session','value':session(ss,'admin'),'domain':'127.0.0.1','path':'/'}])
                            page.reload();page.wait_for_timeout(1500)
                            check(f'browser {width} no JS error',not errors)
                            check(f'browser {width} no page overflow',page.evaluate('document.documentElement.scrollWidth <= innerWidth+1'))
                            check(f'browser {width} authenticated data rendered',page.locator('#private-shell').is_visible() and len(page.locator('#overview-content').inner_text())>200)
                            check(f'browser {width} no token persisted',page.evaluate('localStorage.length === 0 && sessionStorage.length === 0'))
                            if args.report:
                                page.screenshot(path=str(args.report.with_name(f'ops-{width}.png')),full_page=True)
                            page.locator('[data-tab="services"]').click()
                            check(f'browser {width} service drilldown',page.locator('#services-live table').count()>0)
                            page.locator('#services-live .link-button').first.click()
                            check(f'browser {width} evidence detail',page.locator('#detail-dialog').is_visible())
                            page.locator('#detail-close').click()
                            page.locator('[data-tab="architecture"]').click()
                            check(f'browser {width} architecture has edges',page.locator('#graph .graph-edge').count()>0)
                            page.locator('#graph .graph-node').first.click()
                            check(f'browser {width} architecture navigation',page.locator('#detail-dialog').is_visible())
                            page.locator('#detail-close').click()
                            page.locator('#search-input').fill('no-such-record-zzzz')
                            page.wait_for_timeout(200)
                            check(f'browser {width} search empty state',page.locator('#knowledge-list .empty').count()>0)
                            page.locator('#search-input').fill('')
                            page.wait_for_timeout(200)
                            page.locator('[data-tab="incidents"]').click()
                            page.get_by_role('button',name='详情 / 更新',exact=True).first.click()
                            page.get_by_role('button',name='人工更新 / 追加证据',exact=True).click()
                            page.locator('[name="workflow_status"]').select_option('observing')
                            page.locator('[name="note"]').fill('Local browser verification only')
                            with page.expect_response(lambda r:'/api/ops/incidents/' in r.url and r.request.method=='POST') as saved:
                                page.locator('#edit-save').click()
                            check(f'browser {width} incident update accepted',saved.value.status==200)
                            page.wait_for_timeout(300)
                            if page.locator('#detail-dialog').is_visible(): page.locator('#detail-close').click()
                            # Simulate session expiry: no private DOM may survive a401.
                            page.route('**/api/ops/**',lambda route:route.fulfill(status=401,content_type='application/json',body='{"error":"fixture_expired"}'))
                            page.locator('#refresh-button').click()
                            page.locator('#auth-gate').wait_for(state='visible')
                            check(f'browser {width} auth expiry clears private state',page.locator('#private-shell').is_hidden() and all(not t.strip() for t in page.locator('.private-content').all_text_contents()))
                            check(f'browser {width} full interactions no JS error',not errors)
                            page.close()
                        browser.close()
                print(json.dumps({'passed':len(results),'checks':results,'production_writes':0,'real_notifications':0},ensure_ascii=False))
                if args.report:
                    args.report.parent.mkdir(parents=True,exist_ok=True)
                    args.report.write_text(json.dumps({'passed':len(results),'checks':results,'production_writes':0,'real_notifications':0},ensure_ascii=False,indent=2)+'\n');args.report.chmod(0o600)
            finally:
                import sys
                if sys.exc_info()[0] and args.report:
                    logs.flush(); logs.seek(0); detail = logs.read()
                    for value in (ingest, admin, ss): detail = detail.replace(value, '[redacted]')
                    runtime_report = args.report.with_suffix('.runtime.log')
                    runtime_report.parent.mkdir(parents=True,exist_ok=True)
                    runtime_report.write_text(detail);runtime_report.chmod(0o600)
                process.terminate()
                try: process.wait(timeout=8)
                except subprocess.TimeoutExpired: process.kill();process.wait()

if __name__=='__main__': main()
