#!/usr/bin/env python3
"""Local browser fixtures for schedule display; no Worker or production requests."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[3]
RUNNING = '运行中（待完成）'
OPEN = '此前问题未证实恢复'
SUMMARY = 'Scheduled unit is running; completion not yet observed'


def main():
    passed = []
    with sync_playwright() as pw:
        chrome = Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
        browser = pw.chromium.launch(headless=True, **({'executable_path': str(chrome)} if chrome.exists() else {}))
        for width in (1440, 390):
            page = browser.new_page(viewport={'width': width, 'height': 1000})
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            now = datetime.now(timezone.utc)
            def stamp(minutes=0):
                return (now - timedelta(minutes=minutes)).isoformat()
            check = dict(id='schedule:fixture', name='调度测试', category='service', status='unknown', observation_status='observed', observed_at=stamp(), summary=SUMMARY, evidence={'execution_state': 'running'}, problem_open=False)
            fixture = {'collector_status': 'fresh', 'server_time': stamp(), 'latest': {'collected_at': stamp(), 'checks': [check]}, 'missing_checks': []}
            def route(request):
                path = request.request.url.split('fixture.invalid', 1)[1].split('?', 1)[0]
                if path.startswith('/api/ops/'):
                    body = fixture if path == '/api/ops/state' else {}
                    request.fulfill(json=body)
                elif path in ('/admin/ops.html', '/admin/ops.js', '/admin/ops.css'):
                    request.fulfill(path=str(ROOT / 'static-site' / path.lstrip('/')))
                else:
                    request.abort()
            page.route('**/*', route)
            def verify(name, running=False, opened=False, stale=False, expected_summary=None):
                label = RUNNING if running else '未覆盖 · 未知' if fixture['missing_checks'] else '未知'
                page.goto('https://fixture.invalid/admin/ops.html')
                expect(page.locator('#private-shell')).to_be_visible()
                attention = page.locator('#overview-content .activity-item').first
                expect(attention.locator('.badge')).to_have_text(label)
                assert (OPEN in attention.inner_text()) == opened
                if stale:
                    expect(page.locator('#global-notice')).to_contain_text('30 分钟')
                    assert '15 分钟' not in page.locator('#global-notice').inner_text()
                page.locator('[data-tab="services"]').click()
                row = page.locator('#services-live tbody tr').first
                expect(row.locator('.badge')).to_have_text(label)
                assert (OPEN in row.inner_text()) == opened
                if expected_summary:
                    expect(row).to_contain_text(expected_summary)
                row.get_by_role('button', name='详情', exact=True).click()
                current = page.locator('#detail-body dd').nth(1)
                expect(current.locator('.badge')).to_have_text(label)
                assert (OPEN in current.inner_text()) == opened
                if expected_summary:
                    expect(page.locator('#detail-body')).to_contain_text(expected_summary)
                # Running remains styled and filtered as the wire unknown state.
                assert current.locator('.badge.unknown').count() == 1
                page.locator('#detail-close').click()
                page.locator('#status-filter').select_option('unknown')
                expect(page.locator('#services-live tbody tr').first).to_contain_text('调度测试')
                assert not errors, errors
                passed.append(f'{width}: {name}')
            verify('observed running', running=True, expected_summary='调度任务正在运行；尚未观察到执行完成。')
            check['problem_open'] = True
            verify('running preserves open problem', running=True, opened=True)
            fixture['latest']['collected_at'] = stamp(31)
            verify('age stale', opened=True, stale=True)
            fixture['latest']['collected_at'] = stamp(20)
            verify('20 minutes still fresh', running=True, opened=True)
            fixture['collector_status'] = 'stale'
            verify('explicit collector stale', opened=True, stale=True)
            fixture['collector_status'] = 'fresh'
            for observation in ('expired', 'missing', None):
                check['observation_status'] = observation
                verify(f'not observed: {observation}', opened=True)
            check['observation_status'] = 'observed'
            fixture['latest']['checks'] = []
            fixture['missing_checks'] = [check.copy()]
            verify('missing coverage retains problem', opened=True)
            fixture['missing_checks'] = []
            fixture['latest']['checks'] = [check]
            check['evidence'] = {}
            check['problem_open'] = False
            check['summary'] = 'Scheduled round completed after derived snapshot; data correctness not checked'
            verify('completed summary translation without success inference', expected_summary='调度轮次已在统计快照之后完成；尚未检查数据是否正确。')
            page.close()
        browser.close()
    print(json.dumps({'passed': len(passed), 'checks': passed, 'production_requests': 0}, ensure_ascii=False))


if __name__ == '__main__':
    main()
