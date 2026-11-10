// Offline browser regression: actual ops page + actual homepage header/collection component.
// PLAYWRIGHT_MODULE=/path/to/playwright/index.js HC_UI_EVIDENCE=/tmp/... node <this file>
// Optional HC_OPS_FIXTURE=<saved state response> replays private evidence without committing it.
import { createRequire } from 'node:module';
import { readFileSync, mkdirSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import assert from 'node:assert/strict';
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = fileURLToPath(new URL('../../../', import.meta.url));
const out = process.env.HC_UI_EVIDENCE || '/tmp/healthcheck-ui-20261110';
mkdirSync(out, { recursive: true, mode: 0o700 });
const base = 'f35437a699d199076b5654dcde58780be89ee6b4';
const read = (p, before = false) => before
  ? execFileSync('git', ['show', `${base}:${p}`], { cwd: root, timeout: 10000, maxBuffer: 8e6 }).toString()
  : readFileSync(root + p, 'utf8');
const hashes = {};
for (const p of ['static-site/app.js', 'static-site/style.css', 'static-site/admin/ops.js']) {
  hashes[p] = createHash('sha256').update(read(p)).digest('hex');
  writeFileSync(out + '/' + p.split('/').pop(), read(p));
}
writeFileSync(out + '/source-hashes.json', JSON.stringify(hashes, null, 2));
let count = 0;
function ok(name, condition = true) { assert.ok(condition, name); console.log('PASS ' + name); count++; }
const browser = await chromium.launch({ headless: true });
const errors = [], blocked = [], modalLayering = [];
const now = new Date().toISOString();
const check = (id, status) => ({ id, name: id, category: 'service', status, observed_at: now, observation_status: 'observed', summary: id, evidence: {} });
const synthetic = { server_time: now, collector_status: 'fresh', latest: { collected_at: now, checks: [...Array.from({length: 12}, (_, i) => check(`unknown:${i}`, 'unknown')), check('critical:last', 'critical'), check('warning:last', 'warning'), check('normal', 'ok')] }, missing_checks: [] };
const saved = process.env.HC_OPS_FIXTURE ? JSON.parse(readFileSync(process.env.HC_OPS_FIXTURE)) : null;
const original = saved?.response || synthetic;
const originalOrder = JSON.stringify(original.latest.checks);
async function opsPage(width, before = false) {
  const context = await browser.newContext({ viewport: { width, height: 844 }, hasTouch: width < 600, serviceWorkers: 'block' });
  const page = await context.newPage(); page.setDefaultTimeout(6000);
  page.on('pageerror', e => errors.push(String(e)));
  let fixture = structuredClone(original);
  await page.route('**/*', route => {
    const u = new URL(route.request().url());
    if (u.hostname !== 'fixture.invalid' || route.request().method() !== 'GET') { blocked.push(u.href); return route.abort(); }
    if (u.pathname.startsWith('/api/ops/')) return route.fulfill({ json: u.pathname === '/api/ops/state' ? fixture : {} });
    if (['/admin/ops.html', '/admin/ops.css', '/admin/ops.js'].includes(u.pathname)) return route.fulfill({ body: read('static-site' + u.pathname, before), contentType: u.pathname.endsWith('.js') ? 'application/javascript' : u.pathname.endsWith('.css') ? 'text/css' : 'text/html' });
    return route.abort();
  });
  await page.goto('https://fixture.invalid/admin/ops.html');
  await page.locator('#private-shell').waitFor({ state: 'visible' });
  const attention = page.locator('.overview-grid > section').first();
  await page.screenshot({ path: `${out}/ops-${before ? 'before' : 'after'}-${width}.png` });
  if (!before) {
    const expected = fixture.latest.checks.filter(c => ['critical', 'warning'].includes(c.status));
    const visibleNames = await attention.locator(':scope > .activity .link-button').allTextContents();
    ok(`${width} all urgent checks visible`, expected.every(c => visibleNames.includes(c.name || c.id)));
    const statuses = await attention.locator(':scope > .activity .badge').allTextContents();
    ok(`${width} critical before warning before unknown`, statuses.indexOf('严重') < statuses.indexOf('警告') && statuses.indexOf('警告') < statuses.lastIndexOf('未知'));
    const more = attention.locator('.attention-more');
    await more.locator('summary').focus(); await page.keyboard.press('Enter');
    ok(`${width} keyboard expands all`, await more.getAttribute('open') !== null);
    ok(`${width} all non-ok represented`, await attention.locator('.activity-item').count() === fixture.latest.checks.filter(c => c.status !== 'ok').length);
    await more.locator('.link-button').first().click();
    ok(`${width} remaining unknown detail reachable`, await page.locator('#detail-dialog').isVisible());
    await page.locator('#detail-close').click();
    await page.locator('#refresh-button').click();
    await page.waitForFunction(() => !document.querySelector('#refresh-button').disabled);
    ok(`${width} refresh keeps expansion`, await attention.locator('.attention-more').getAttribute('open') !== null);
    await page.locator('#status-filter').selectOption('warning');
    ok(`${width} warning filter`, await attention.locator('.activity-item').count() === expected.filter(c => c.status === 'warning').length);
    await page.locator('#status-filter').selectOption('unknown');
    ok(`${width} unknown retained`, (await attention.locator('.badge').allTextContents()).every(s => s.includes('未知') || s.includes('运行中')));
    await page.locator('#status-filter').selectOption('all');
    await page.locator('#search-input').fill(expected[0].id);
    await page.waitForFunction(() => document.querySelectorAll('.overview-grid > section:first-child .activity-item').length === 1);
    ok(`${width} search retains reachability`);
    await page.locator('#search-input').fill('');
    await page.waitForFunction(() => document.querySelectorAll('.overview-grid > section:first-child .activity-item').length > 1);
    await page.locator('[data-tab="services"]').click();
    assert.deepEqual(await page.locator('#services-live .record-id').allTextContents(), fixture.latest.checks.filter(c => ['service', 'timer'].includes(c.category)).map(c => c.id));
    ok(`${width} overview sort preserves service table order`);
    await page.locator('[data-tab="data"]').click();
    assert.deepEqual(await page.locator('#data-live .record-id').allTextContents(), fixture.latest.checks.filter(c => ['data', 'publication', 'backup', 'resource', 'monitor'].includes(c.category)).map(c => c.id));
    ok(`${width} overview sort preserves data table order`);
    await page.locator('[data-tab="overview"]').click();
    // More than eight urgent checks must not crowd unknown out altogether.
    fixture = structuredClone(synthetic);
    fixture.latest.checks.push(...Array.from({ length: 10 }, (_, i) => check(`critical:extra:${i}`, 'critical')));
    await page.locator('#refresh-button').click();
    await page.waitForFunction(() => document.querySelectorAll('.overview-grid > section:first-child > .activity > .activity-item').length === 13);
    ok(`${width} >8 urgent all visible plus unknown`);
    fixture.collector_status = 'stale'; fixture.missing_checks = [check('missing:previous-critical', 'critical')];
    await page.locator('#refresh-button').click();
    await page.waitForFunction(() => !document.querySelector('.overview-grid > section:first-child .badge.critical'));
    ok(`${width} stale/missing never promoted OK`, await attention.locator('.badge.ok').count() === 0 && await attention.locator('.badge.unknown').count() === 26);
    if (width < 600) await attention.locator('summary').tap();
    else await attention.locator('summary').click();
    ok(`${width} touch/click expansion`, await attention.locator('.attention-more').getAttribute('open') !== null);
    ok(`${width} ops no horizontal overflow`, await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  }
  await context.close();
}
const health = { level: 'error', items: [{ metric_id: 'fixture_source', status: 'error', message: '离线来源异常样本' }] };
// Use the production modal constructors, DOM and open/close handlers. Only data,
// auth-state and notification-permission dependencies are isolated (no delivery/OAuth).
async function verifyModalLayers(page, app, width) {
  const section = (start, end) => {
    const a = app.indexOf(start), b = app.indexOf(end, a + start.length);
    assert.ok(a >= 0 && b > a, `modal source anchors: ${start}`);
    return app.slice(a, b);
  };
  const modalSource = [
    section('function openNotifySettingsModal()', 'function initNotifyButton()'),
    section("  const h5NotifyBtn = document.querySelector('.h5-notify-btn');", '  // 监听 SW notificationclick'),
    section('async function openShareModal()', '// === 配色皮肤切换 ==='),
    section('function _escAttr(s)', '// 汪汪队 day modal'),
    section('function _authLoginModalHtml(', '// 未登录点完整版'),
    section('function initAuthButton()', '// === 合规/完整视图切换'),
    section('function updateRulesContentHtml()', 'function _renderScheduleStats('),
    section('function initUpdateRules()', '// 通用"首次解释"弹窗')
  ].join('\n');
  await page.addScriptTag({ content: `
    const _notifyPerm = () => 'denied', _isIOS = () => false, _isStandalone = () => false;
    const _getCachedOverview = () => ({date:'20261110'}), fetchJSON = async () => null;
    const _receiveAuthToken = () => {}, fetchAuthState = () => {};
    const _loadScheduleStats = () => {}, _renderFreshnessInModal = () => {};
    const drawShareCard = () => { const c = document.createElement('canvas'); c.width=300; c.height=500; return c; };
    ${modalSource}
    initShareButton(); initAuthButton(); initUpdateRules();
  ` });
  await page.evaluate(() => {
    applyCollectTime('2026-11-10 19:45:06', { level: 'error', items: Array.from({length: 15}, (_, i) => ({
      metric_id: 'long_source_' + i, status: 'error', message: '离线长详情来源异常'.repeat(120)
    })) });
    document.querySelector('.h5-collect-alert').open = true;
  });
  for (const type of ['notify', 'share', 'login', 'update']) {
    const selectors = {
      notify: ['.notify-settings-modal', '.theme-modal-close'],
      share: ['#share-modal', '.rule-modal-close'],
      login: ['.auth-login-modal', '.theme-modal-close'],
      update: ['.update-rules-modal', '.rule-modal-close']
    };
    if (type === 'notify') await page.locator('.h5-notify-btn').tap();
    if (type === 'share') await page.locator('.h5-share-btn').tap();
    if (type === 'login') await page.locator('.h5-auth-btn').tap();
    // The update-rules icon is hidden on phones; trigger its real delegated handler.
    if (type === 'update') await page.locator('.pc-collect-time .update-rules-btn').evaluate(el => el.click());
    const [selector, closeSelector] = selectors[type];
    const modal = page.locator(selector);
    await modal.waitFor({ state: 'visible' });
    // Wait for actual modal animation completion, rather than probing a transient transform.
    await modal.evaluate(el => Promise.all(el.getAnimations().map(a => a.finished)));
    const hit = await modal.evaluate((el, closeSelector) => {
      const panel = document.querySelector('.h5-collect-alert-detail');
      const p = panel.getBoundingClientRect();
      const b = el.querySelector('.modal-body,.rule-modal-body').getBoundingClientRect();
      const close = el.querySelector(closeSelector), c = close.getBoundingClientRect();
      const left = Math.max(p.left, b.left), right = Math.min(p.right, b.right);
      const top = Math.max(p.top, b.top), bottom = Math.min(p.bottom, b.bottom);
      const samples = [];
      for (const fx of [.2,.5,.8]) for (const fy of [.2,.5,.8]) {
        const x = left + (right - left) * fx, y = top + (bottom - top) * fy;
        const target = document.elementFromPoint(x, y);
        samples.push({ x, y, topClass: target?.className, modalOwnsPoint: el.contains(target) });
      }
      const closeTop = document.elementFromPoint(c.x + c.width/2, c.y + c.height/2);
      return {
        longPanel: panel.scrollHeight > panel.clientHeight, overlap: right > left && bottom > top,
        panelZ: getComputedStyle(panel).zIndex, modalZ: getComputedStyle(el).zIndex,
        closeTop: closeTop?.className, closeHit: close.contains(closeTop), samples,
        bodyHit: samples.every(s => s.modalOwnsPoint), panelRect: p.toJSON(), modalBodyRect: b.toJSON()
      };
    }, closeSelector);
    await page.screenshot({ path: `${out}/modal-${type}-${width}.png` });
    let actionClicked = type !== 'notify', closed = false;
    if (hit.closeHit && hit.bodyHit) {
      if (type === 'notify') {
        const action = modal.locator('[data-action="recheck"]');
        const actionHit = await action.evaluate(el => { const b=el.getBoundingClientRect(); return el.contains(document.elementFromPoint(b.x+b.width/2,b.y+b.height/2)); });
        await action.tap(); // Real recheck handler only rerenders the denied permission fixture.
        actionClicked = actionHit && await modal.locator('[data-action="recheck"]').isVisible();
      }
      // Actual close handlers: touch for notification/share, keyboard for login/update.
      if (type === 'notify' || type === 'share') await modal.locator(closeSelector).tap();
      else { await modal.locator(closeSelector).focus(); await page.keyboard.press('Enter'); }
      closed = !await modal.isVisible();
    } else {
      // Cleanup only for the deliberately failing pre-fix replay; never use force clicks.
      await modal.evaluate(el => el.classList.add('hidden'));
    }
    const summary = page.locator('.h5-collect-alert > summary');
    await summary.focus(); await page.keyboard.press('Space');
    const collapsed = await page.locator('.h5-collect-alert').getAttribute('open') === null;
    await page.keyboard.press('Enter');
    const returned = collapsed && await page.locator('.h5-collect-alert').getAttribute('open') !== null;
    modalLayering.push({ width, type, ...hit, actionClicked, closed, returned,
      modalSourceSha256: createHash('sha256').update(modalSource).digest('hex') });
    writeFileSync(out + '/modal-layering.json', JSON.stringify(modalLayering, null, 2));
    console.log(`MODAL ${width} ${type} panelZ=${hit.panelZ} modalZ=${hit.modalZ} bodyHit=${hit.bodyHit} closeHit=${hit.closeHit} clicked=${actionClicked} closed=${closed} returned=${returned}`);
  }
}
async function homePage(width, before = false) {
  const context = await browser.newContext({ viewport: { width, height: 844 }, hasTouch: width < 600, serviceWorkers: 'block' });
  const page = await context.newPage(); page.setDefaultTimeout(6000); page.on('pageerror', e => errors.push(String(e)));
  const index = read('static-site/index.html', before);
  const header = index.match(/<header\b[\s\S]*?<\/header>/)[0];
  const styles = [...index.matchAll(/<style\b[^>]*>[\s\S]*?<\/style>/g)].map(x => x[0]).join('');
  const app = read('static-site/app.js', before);
  const component = app.slice(app.indexOf('const _UPDATE_RULES_ICON'), app.indexOf('async function fetchCollectTime()'));
  await page.route('**/*', route => {
    const u = new URL(route.request().url());
    if (u.hostname !== 'fixture.invalid' || route.request().method() !== 'GET') { blocked.push(u.href); return route.abort(); }
    if (u.pathname === '/style.css') return route.fulfill({ body: read('static-site/style.css', before), contentType: 'text/css' });
    return route.fulfill({ contentType: 'text/html', body: `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">${styles}<link rel="stylesheet" href="/style.css"></head><body>${header}<main>采集组件离线验收 · 不加载业务/通知</main></body></html>` });
  });
  await page.goto('https://fixture.invalid/');
  await page.addScriptTag({ content: `let _collectTimeBase = {}; let _intradayDynamicTime = ''; const state = {};\n${component}` });
  await page.evaluate(h => applyCollectTime('2026-11-10 19:45:06', h), health);
  const image = await page.screenshot({ path: `${out}/home-${before ? 'before' : 'after'}-${width}.png` });
  const dims = await page.locator('.h5-notify-btn').boundingBox();
  if (!before) {
    const entry = page.locator('.h5-collect-alert');
    if (width < 600) {
      ok(`${width} abnormal entry visible`, await entry.isVisible());
      ok(`${width} hidden time container remains hidden`, !await page.locator('.h5-collect-time').isVisible());
      await entry.locator('summary').tap();
      ok(`${width} touch opens same source/details`, (await entry.innerText()).includes('fixture_source') && (await entry.innerText()).includes('离线来源异常样本'));
      ok(`${width} accurate closed snapshot time`, (await entry.innerText()).includes('2026-11-10 19:45:06 · 收盘快照'));
      const box = await entry.locator('.h5-collect-alert-detail').boundingBox();
      ok(`${width} detail fits viewport`, box.x >= 0 && box.x + box.width <= width && box.y + box.height <= 844);
      await page.screenshot({ path: `${out}/home-detail-${width}.png` });
      await entry.locator('summary').focus(); await page.keyboard.press('Space');
      ok(`${width} keyboard closes`, await entry.getAttribute('open') === null);
      await page.keyboard.press('Enter'); ok(`${width} keyboard opens`, await entry.getAttribute('open') !== null);
      await page.evaluate(() => { state.intradaySnapshot = { is_closed: false }; _intradayDynamicTime = '2026-11-10 14:02:03'; _renderCollectTime(); });
      ok(`${width} dynamic time same source`, (await entry.innerText()).includes('2026-11-10 14:02:03 · 动态(1min)'));
      await page.evaluate(() => { _intradayDynamicTime = ''; _renderCollectTime(); });
      ok(`${width} intraday fallback`, (await entry.innerText()).includes('2026-11-10 19:45:06 · 动态(1min)'));
      await page.evaluate(h => applyCollectTime('', h), health);
      ok(`${width} missing timestamp honest`, (await entry.innerText()).includes('采集时间未知'));
      await page.evaluate(() => applyCollectTime('2026-11-10 19:50:00', { level: 'warn', items: [{ metric_id: 'warning_source', status: 'warn', message: '警告来源样本' }] }));
      ok(`${width} warning same component`, (await entry.innerText()).includes('采集告警 1 项') && (await entry.innerText()).includes('warning_source'));
      await page.evaluate(() => applyCollectTime('2026-11-10 19:51:00', { level: 'ok', items: [] }));
      ok(`${width} recovery removes stale badge`, await entry.count() === 0);
      await page.evaluate(() => applyCollectTime('2026-11-10 19:51:00', null));
      ok(`${width} missing health not false red`, await entry.count() === 0);
      await page.evaluate(h => { applyCollectTime('2026-11-10 19:52:00', h); applyCollectTime('2026-11-10 19:52:00', h); }, health);
      await page.setViewportSize({ width: 1440, height: 900 });
      ok(`${width} desktop hides mobile badge`, !await entry.isVisible());
      await page.setViewportSize({ width, height: 844 });
      ok(`${width} viewport switches no duplicates`, await entry.count() === 1 && await entry.isVisible());
      ok(`${width} home no horizontal overflow`, await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      await verifyModalLayers(page, app, width);
    } else {
      ok(`${width} desktop mobile entry hidden`, !await entry.isVisible());
      ok(`${width} desktop original health remains`, await page.locator('.pc-collect-time .collect-health[data-level="error"]').isVisible());
    }
  }
  await context.close(); return { image, dims };
}
try {
  for (const width of [390, 320, 1440]) {
    await opsPage(width, true); await opsPage(width);
    const before = await homePage(width, true), after = await homePage(width);
    assert.deepEqual(after.dims && [after.dims.width, after.dims.height], before.dims && [before.dims.width, before.dims.height]); ok(`${width} notification button dimensions unchanged`);
    if (width === 1440) ok('desktop header pixel-identical', before.image.equals(after.image));
  }
  for (const m of modalLayering) {
    ok(`${m.width} ${m.type} long-panel modal owns overlap and close`, m.longPanel && m.overlap && m.bodyHit && m.closeHit);
    ok(`${m.width} ${m.type} real controls click/close and detail keyboard return`, m.actionClicked && m.closed && m.returned);
  }
  ok('fixture order unchanged', JSON.stringify(original.latest.checks) === originalOrder);
  ok('zero browser errors', errors.length === 0);
  ok('no external requests/writes attempted', blocked.length === 0);
  writeFileSync(out + '/result.json', JSON.stringify({ passed: count, errors, blocked, hashes, coverage: 'ops full page; home actual header/collection + production modal constructors and handlers; data/auth/permission dependencies isolated from bootstrap' }, null, 2));
  console.log(`PASS HC03/HC04 ${count} assertions; local-only browser fixtures`);
} finally { await browser.close(); }
