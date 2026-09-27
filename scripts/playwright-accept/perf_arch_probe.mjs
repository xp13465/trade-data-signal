import { chromium, devices } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';

const URL = process.env.PERF_URL || 'https://ss.fx8.store/';
const OUT = process.env.PERF_OUT || '/tmp/codex-reports/perf-live-measurement-20260826.json';

function round(value, digits = 1) {
  if (value == null || Number.isNaN(value)) return null;
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
}

async function installObservers(page) {
  await page.addInitScript(() => {
    window.__perf = { lcp: 0, cls: 0, longTasks: [], events: [], shifts: [], resourcesStartedAt: performance.now() };
    new PerformanceObserver(list => {
      const entries = list.getEntries();
      if (entries.length) window.__perf.lcp = entries.at(-1).startTime;
    }).observe({ type: 'largest-contentful-paint', buffered: true });
    new PerformanceObserver(list => {
      for (const entry of list.getEntries()) {
        if (entry.hadRecentInput) continue;
        window.__perf.cls += entry.value;
        if (entry.value >= 0.02) {
          window.__perf.shifts.push({
            time: Math.round(entry.startTime),
            value: Number(entry.value.toFixed(4)),
            sources: (entry.sources || []).map(source => ({
              node: source.node?.nodeName || null,
              className: String(source.node?.className || '').slice(0, 160),
              id: source.node?.id || null,
              text: String(source.node?.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 100),
              previousRect: source.previousRect,
              currentRect: source.currentRect,
            })),
          });
        }
      }
    }).observe({ type: 'layout-shift', buffered: true });
    new PerformanceObserver(list => {
      for (const entry of list.getEntries()) window.__perf.longTasks.push({ start: Math.round(entry.startTime), duration: Math.round(entry.duration) });
    }).observe({ type: 'longtask', buffered: true });
    new PerformanceObserver(list => {
      for (const entry of list.getEntries()) if (entry.duration >= 50) window.__perf.events.push({ name: entry.name, start: Math.round(entry.startTime), duration: Math.round(entry.duration), interactionId: entry.interactionId || null });
    }).observe({ type: 'event', buffered: true });
  });
}

async function collectPage(page, label, extra = {}) {
  const metrics = await page.evaluate(() => {
    const nav = performance.getEntriesByType('navigation')[0];
    const paint = Object.fromEntries(performance.getEntriesByType('paint').map(item => [item.name, item.startTime]));
    const resources = performance.getEntriesByType('resource').map(entry => ({
      name: entry.name,
      initiatorType: entry.initiatorType,
      duration: Math.round(entry.duration),
      transferSize: entry.transferSize || 0,
      encodedBodySize: entry.encodedBodySize || 0,
      decodedBodySize: entry.decodedBodySize || 0,
    }));
    const group = (predicate) => {
      const rows = resources.filter(predicate);
      return {
        count: rows.length,
        transferBytes: rows.reduce((sum, row) => sum + row.transferSize, 0),
        decodedBytes: rows.reduce((sum, row) => sum + row.decodedBodySize, 0),
        maxDuration: rows.reduce((max, row) => Math.max(max, row.duration), 0),
      };
    };
    return {
      url: location.href,
      navigation: nav ? {
        ttfb: Math.round(nav.responseStart),
        domInteractive: Math.round(nav.domInteractive),
        domContentLoaded: Math.round(nav.domContentLoadedEventEnd),
        loadEvent: Math.round(nav.loadEventEnd),
        transferSize: nav.transferSize || 0,
      } : null,
      fcp: Math.round(paint['first-contentful-paint'] || 0),
      lcp: Math.round(window.__perf.lcp || 0),
      cls: Number((window.__perf.cls || 0).toFixed(4)),
      largestShifts: [...window.__perf.shifts].sort((a, b) => b.value - a.value).slice(0, 10),
      tbt: Math.round(window.__perf.longTasks.reduce((sum, task) => sum + Math.max(0, task.duration - 50), 0)),
      longTaskCount: window.__perf.longTasks.length,
      longTaskTotal: Math.round(window.__perf.longTasks.reduce((sum, task) => sum + task.duration, 0)),
      slowEvents: window.__perf.events.filter(event => event.duration >= 100).slice(-20),
      domNodes: document.getElementsByTagName('*').length,
      heapMB: performance.memory ? Math.round(performance.memory.usedJSHeapSize / 1048576) : null,
      totals: {
        all: group(() => true),
        script: group(row => row.name.endsWith('.js') || row.initiatorType === 'script'),
        css: group(row => row.name.endsWith('.css') || row.initiatorType === 'link'),
        json: group(row => row.name.includes('.json')),
        fetch: group(row => row.initiatorType === 'fetch' || row.initiatorType === 'xmlhttprequest'),
      },
      largestResources: [...resources].sort((a, b) => b.transferSize - a.transferSize).slice(0, 25),
      slowestResources: [...resources].sort((a, b) => b.duration - a.duration).slice(0, 20),
    };
  });
  return { label, ...extra, ...metrics };
}

async function loadScenario(browser, label, options = {}) {
  const context = await browser.newContext(options.contextOptions);
  if (options.userAgentSuffix) {
    await context.setExtraHTTPHeaders({ 'user-agent': undefined });
  }
  const page = await context.newPage();
  await installObservers(page);
  const consoleErrors = [];
  const pageErrors = [];
  const failedRequests = [];
  page.on('console', message => { if (message.type() === 'error') consoleErrors.push(message.text().slice(0, 500)); });
  page.on('pageerror', error => pageErrors.push(String(error).slice(0, 500)));
  page.on('requestfailed', request => failedRequests.push({ url: request.url(), failure: request.failure()?.errorText }));
  const started = Date.now();
  await page.goto(URL, { waitUntil: 'load', timeout: 60000 });
  await page.waitForLoadState('networkidle', { timeout: options.networkIdleTimeout || 15000 }).catch(() => {});
  await page.waitForTimeout(1000);
  const cold = await collectPage(page, label, { elapsedMs: Date.now() - started, consoleErrors, pageErrors, failedRequests: failedRequests.slice(0, 20) });
  const result = { cold };

  if (options.warmReload) {
    const warmPage = await context.newPage();
    await installObservers(warmPage);
    const warmStarted = Date.now();
    await warmPage.goto(URL, { waitUntil: 'load', timeout: 60000 });
    await warmPage.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => {});
    await warmPage.waitForTimeout(800);
    result.warm = await collectPage(warmPage, `${label}:warm`, { elapsedMs: Date.now() - warmStarted });
    result.serviceWorkers = await context.serviceWorkers().map(worker => ({ url: worker.url() }));
    await interactions(warmPage, result.warm);
    await warmPage.close();
  }
  await context.close();
  return result;
}

async function interactions(page, result) {
  result.interactions = [];
  const onboardingSkip = page.locator('.onboarding-skip').first();
  if (await onboardingSkip.isVisible().catch(() => false)) {
    await onboardingSkip.click({ timeout: 2000 }).catch(() => {});
    await page.waitForTimeout(300);
  }
  const desktopNav = await page.locator('nav.tabs').isVisible().catch(() => false);
  const navSelector = desktopNav ? 'nav.tabs' : 'nav.h5-bottomnav';
  const authenticated = await page.evaluate(() => Boolean(window.__authState?.logged_in));
  const tabNames = desktopNav
    ? (authenticated ? ['market', 'sentiment', 'fund', 'lab'] : ['market', 'sentiment', 'lab'])
    : ['market', 'sentiment', 'lab'];
  for (const tab of tabNames) {
    const locator = page.locator(`${navSelector} button[data-tab="${tab}"]`).first();
    if (!await locator.isVisible().catch(() => false)) continue;
    await page.evaluate(() => {
      window.__perf.longTasks = [];
      window.__interactionProbe = { start: null, firstMutationMs: null, mutations: 0 };
      const observer = new MutationObserver(mutations => {
        window.__interactionProbe.mutations += mutations.length;
        if (window.__interactionProbe.firstMutationMs == null) {
          window.__interactionProbe.firstMutationMs = Math.round(performance.now() - window.__interactionProbe.start);
        }
      });
      window.__interactionObserver = observer;
      observer.observe(document.getElementById('content'), { childList: true, subtree: true, attributes: true });
    });
    const started = Date.now();
    await page.evaluate(() => { window.__interactionProbe.start = performance.now(); });
    await locator.click();
    await page.waitForFunction(() => window.__interactionProbe?.firstMutationMs != null, null, { timeout: 5000 }).catch(() => {});
    await page.waitForTimeout(2500);
    const sample = await page.evaluate(() => ({
      longTasks: window.__perf.longTasks,
      domNodes: document.getElementsByTagName('*').length,
      activeTab: document.querySelector('nav.tabs button.active')?.dataset.tab || document.querySelector('nav.h5-bottomnav button.active')?.dataset.tab || null,
      firstMutationMs: window.__interactionProbe?.firstMutationMs ?? null,
      mutations: window.__interactionProbe?.mutations || 0,
    }));
    await page.evaluate(() => window.__interactionObserver?.disconnect());
    await page.evaluate(() => document.querySelectorAll('.modal.auth-login-modal').forEach(modal => modal.remove()));
    result.interactions.push({
      action: `tab:${tab}`,
      wallMs: Date.now() - started,
      timeToFirstDomChangeMs: sample.firstMutationMs,
      mutations: sample.mutations,
      maxLongTaskMs: sample.longTasks.reduce((max, task) => Math.max(max, task.duration), 0),
      longTaskCount: sample.longTasks.length,
      tbt: Math.round(sample.longTasks.reduce((sum, task) => sum + Math.max(0, task.duration - 50), 0)),
      domNodes: sample.domNodes,
      activeTab: sample.activeTab,
    });
  }
}

const browser = await chromium.launch({ headless: true });
try {
  const report = {
    measuredAt: new Date().toISOString(),
    url: URL,
    environment: { tool: 'Playwright Chromium', headless: true },
    desktop: await loadScenario(browser, 'desktop:cold+warm', {
      warmReload: true,
      contextOptions: { viewport: { width: 1440, height: 900 }, locale: 'zh-CN' },
    }),
    mobile: await loadScenario(browser, 'mobile:cold+warm', {
      warmReload: true,
      contextOptions: { ...devices['iPhone 13'], locale: 'zh-CN' },
    }),
  };
  fs.mkdirSync(path.dirname(OUT), { recursive: true });
  fs.writeFileSync(`${OUT}.tmp`, JSON.stringify(report, null, 2));
  fs.renameSync(`${OUT}.tmp`, OUT);
  console.log(JSON.stringify(report, null, 2));
} finally {
  await browser.close();
}
