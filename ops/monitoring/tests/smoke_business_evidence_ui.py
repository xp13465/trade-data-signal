"""Render actual ops HTML/JS/CSS with actual local collector output; all I/O routed.

No handcrafted DOM, production requests, credentials, deployment or notifications.
"""
import json
import hashlib
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'scripts'))
import ops_monitor as m
import r2_pending_context as q


def main():
    with tempfile.TemporaryDirectory(prefix='ops-browser-data-') as directory:
        root=Path(directory).resolve()
        flag=root/'pending'
        proof=root/'proof.json'
        proof.write_text(json.dumps({'version':1,'run_id':'browser-fixture','static_dir':str((root/'static-site').resolve()),
            'outputs':{'data/test.json':{'size':2,'sha256':hashlib.sha256(b'{}').hexdigest()}}}))
        q.enqueue(flag,root/'static-site',proof,'browser-fixture')
        cfg=SimpleNamespace(data_root=root,code_root=ROOT,total_timeout_seconds=20,command_timeout_seconds=1,collector_id='local-browser',r2_pending_flag=str(flag))
        c=m.Collector(cfg);c.assets();c.business_evidence();c.pending_publication()
        snapshot=c.snapshot();m.validate_snapshot(snapshot)
        # An unsafe string is deliberate hostile API data, never executable HTML.
        snapshot['checks'][0]['summary']='<img src=x onerror="window.__xss=1">'
        for check in snapshot['checks']:
            check['observation_status']='observed'
        state={'collector_status':'fresh','server_time':m.utc_now(),'latest':snapshot,'missing_checks':[]}
        seen=[]
        with sync_playwright() as pw:
            chrome=Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
            browser=pw.chromium.launch(headless=True,**({'executable_path':str(chrome)} if chrome.exists() else {}))
            try:
                for width in (390,1280):
                    page=browser.new_page(viewport={'width':width,'height':1000},service_workers='block')
                    page.set_default_timeout(8000);errors=[]
                    page.on('pageerror',lambda e: errors.append(str(e)))
                    def route(req):
                        from urllib.parse import urlparse
                        u=urlparse(req.request.url)
                        if u.hostname!='offline.invalid' or req.request.method!='GET':
                            seen.append(req.request.url);req.abort();return
                        if u.path.startswith('/api/ops/'):
                            req.fulfill(json=state if u.path=='/api/ops/state' else {})
                        elif u.path in ('/admin/ops.html','/admin/ops.js','/admin/ops.css'):
                            req.fulfill(path=str(ROOT/'static-site'/u.path.lstrip('/')))
                        else:
                            req.abort()
                    page.route('**/*',route)
                    page.goto('https://offline.invalid/admin/ops.html')
                    expect(page.locator('#private-shell')).to_be_visible()
                    page.locator('[data-tab="data"]').click()
                    row=page.locator('#data-live tbody tr').first
                    expect(row).to_contain_text('未知')
                    row.get_by_role('button',name='详情',exact=True).click()
                    expect(page.locator('#detail-body')).to_contain_text('业务发生时间')
                    expect(page.locator('#detail-body')).to_contain_text('下一份所需证据')
                    expect(page.locator('#detail-body')).to_contain_text('确认送达时间')
                    page.locator('#detail-dialog').evaluate('(d) => d.close()')
                    pending=page.locator('#data-live tbody tr').filter(has_text='R2 逐请求待发布队列')
                    expect(pending).to_contain_text('未知')
                    pending.get_by_role('button',name='详情',exact=True).click()
                    expect(page.locator('#detail-body')).to_contain_text('尚未被取入批次')
                    expect(page.locator('#detail-body')).to_contain_text('逐请求消费结果、当前线上文件哈希')
                    expect(page.locator('#detail-body')).to_contain_text('本次有界扫描完整')
                    assert page.evaluate('window.__xss') is None
                    assert not errors, errors
                    assert not seen, seen
                    out=Path(os.environ.get('OPS_UI_EVIDENCE_DIR','/tmp/codex-reports/ops-evidence-closeout-20261111/ui'))
                    out.mkdir(parents=True,exist_ok=True)
                    page.screenshot(path=str(out/f'business-ui-{width}.png'),full_page=False)
                    page.locator('#detail-dialog').evaluate('(d) => d.close()')
                    for name in ('公募日更 · 业务证据','FOF 净值 · 业务证据'):
                        fund=page.locator('#data-live tbody tr').filter(has_text=name)
                        expect(fund).to_contain_text('未知')
                        fund.get_by_role('button',name='详情',exact=True).click()
                        expect(page.locator('#detail-body')).to_contain_text('净值线上发布')
                        expect(page.locator('#detail-body')).to_contain_text('未取得本轮净值与公开文件的完整对应凭证')
                        page.locator('#detail-dialog').evaluate('(d) => d.close()')
                    page.close()
                print('PASS: actual ops HTML/JS/CSS; collector indices; desktop/mobile; unknown timestamps; XSS; zero external requests')
            finally:
                browser.close()


if __name__=='__main__':
    main()
