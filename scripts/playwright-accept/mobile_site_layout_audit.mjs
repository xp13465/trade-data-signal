import fs from 'node:fs/promises';
import path from 'node:path';
import { chromium } from 'playwright';

const BASE_URL = process.env.BASE_URL || 'http://127.0.0.1:8125';
const OUTPUT_PATH = '/tmp/codex-reports/mobile-site-layout-audit.json';
const SHOT_DIR = '/tmp/codex-reports/mobile-site-layout-audit';
const WIDTHS = [320, 390, 430];

const marketSubtabs = ['a-stock', 'industry', 'hk', 'global'];
const sentimentSubtabs = ['market-temp', 'futures', 'national-team', 'public-fund'];
const fundSubtabs = ['etf', 'offshore'];
const labGroups = [
  { parent: 'scan', children: ['ablation', 'symmetry', 'paramscan'] },
  { parent: 'experiment', children: ['single', 'fusion'] },
  { parent: 'retest', children: [] },
  { parent: 'custom', children: ['aiwarn', 'aiscore', 'sigkelly'] },
];

const staticPaths = [
  { id: 'guide', path: '/guide.html' },
  { id: 'about', path: '/about.html' },
  { id: 'privacy', path: '/privacy.html' },
  { id: 'databrief', path: '/databrief.html' },
  ...[
    'trade_sim',
    'trade_sim_cac40',
    'trade_sim_kospi',
    'trade_sim_nikkei225',
    'trade_sim_g.cn10y',
    'trade_sim_g.oil',
    'trade_sim_g.usdcnh',
  ].map((id) => ({ id, path: `/${id}.html` })),
  { id: 'feedback-admin', path: '/admin/feedback.html' },
];

function slug(value) {
  return String(value).replace(/[^a-z0-9.-]+/gi, '_');
}

async function settle(page, milliseconds = 900) {
  await page.waitForTimeout(milliseconds);
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
}

async function waitForAuth(page) {
  await page.waitForFunction(() => window.__authState?.logged_in === true, undefined, { timeout: 8000 }).catch(() => {});
}

async function auditLayout(page) {
  await page.evaluate(() => window.scrollTo(0, 0));
  await settle(page, 350);
  return page.evaluate(() => {
    const doc = document.documentElement;
    const viewportWidth = doc.clientWidth;
    const viewportHeight = window.innerHeight;
    const isVisible = (element) => {
      const rect = element.getBoundingClientRect();
      const style = getComputedStyle(element);
      return rect.width > 0 && rect.height > 0
        && style.visibility !== 'hidden' && style.display !== 'none'
        && Number(style.opacity || '1') > 0.05;
    };
    const describe = (element) => ({
      tag: element.tagName.toLowerCase(),
      className: String(element.className || '').slice(0, 160),
      id: element.id || '',
      text: (element.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 110),
      rect: (({ left, top, right, bottom, width, height }) => ({ left, top, right, bottom, width, height }))(element.getBoundingClientRect()),
    });

    const scrollableAncestor = (element) => {
      let node = element.parentElement;
      while (node && node !== document.body) {
        const style = getComputedStyle(node);
        if (['auto', 'scroll', 'hidden'].includes(style.overflowX)) return node;
        node = node.parentElement;
      }
      return null;
    };

    const hardOverflow = [];
    const containedOverflow = [];
    for (const element of document.querySelectorAll('body *')) {
      if (!isVisible(element) || ['HTML', 'BODY'].includes(element.tagName)) continue;
      const rect = element.getBoundingClientRect();
      if (rect.right <= viewportWidth + 2 && rect.left >= -2) continue;
      const item = { ...describe(element), overflowRight: Math.round(rect.right - viewportWidth) };
      const container = scrollableAncestor(element);
      if (container) {
        const containerStyle = getComputedStyle(container);
        const touchScrollable = /(auto|scroll)/.test(containerStyle.overflowX);
        const entry = {
          ...item,
          container: describe(container),
          touchScrollable,
          containerScrollWidth: container.scrollWidth,
          containerClientWidth: container.clientWidth,
        };
        if (touchScrollable) {
          if (containedOverflow.length < 24) containedOverflow.push(entry);
        } else if (hardOverflow.length < 24) {
          hardOverflow.push({ ...entry, reason: 'overflowing non-scrollable ancestor' });
        }
      } else if (hardOverflow.length < 24) {
        hardOverflow.push({ ...item, reason: 'no scroll container' });
      }
    }

    const interactiveSelector = 'button,a,input,select,textarea,[role="button"]';
    const tinyControls = [];
    const zeroControls = [];
    const coveredControls = [];
    const smallText = [];
    for (const element of document.querySelectorAll(interactiveSelector)) {
      const rect = element.getBoundingClientRect();
      const style = getComputedStyle(element);
      if (!isVisible(element)) continue;
      const item = describe(element);
      if (rect.width < 1 || rect.height < 1) zeroControls.push(item);
      else if (rect.width < 24 || rect.height < 24) tinyControls.push(item);
      if (rect.width > 10 && rect.height > 10 && rect.top >= 0 && rect.left >= 0
          && rect.right <= viewportWidth && rect.bottom <= viewportHeight) {
        const actual = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
        if (actual && !element.contains(actual) && !actual.contains(element)) {
          let layer = actual;
          while (layer && layer !== document.body) {
            const layerStyle = getComputedStyle(layer);
            if ((layerStyle.position === 'fixed' || layerStyle.position === 'sticky') && !layer.contains(element)) {
              coveredControls.push({ ...item, coverLayer: describe(layer) });
              break;
            }
            layer = layer.parentElement;
          }
        }
      }
    }

    for (const element of document.querySelectorAll('body *')) {
      if (!isVisible(element) || element.children.length > 2) continue;
      const hasDirectText = [...element.childNodes].some((node) => node.nodeType === Node.TEXT_NODE && node.textContent.trim());
      if (!hasDirectText) continue;
      const fontSize = parseFloat(getComputedStyle(element).fontSize);
      if (fontSize > 0 && fontSize < 10 && smallText.length < 30) smallText.push({ ...describe(element), fontSize });
    }

    const clipped = [];
    for (const element of document.querySelectorAll('body *')) {
      if (!isVisible(element)) continue;
      const style = getComputedStyle(element);
      const xClipped = element.scrollWidth > element.clientWidth + 6 && ['hidden', 'clip'].includes(style.overflowX);
      const yClipped = element.scrollHeight > element.clientHeight + 8 && ['hidden', 'clip'].includes(style.overflowY);
      if ((xClipped || yClipped) && clipped.length < 36) {
        clipped.push({
          ...describe(element),
          scrollWidth: element.scrollWidth,
          clientWidth: element.clientWidth,
          scrollHeight: element.scrollHeight,
          clientHeight: element.clientHeight,
          overflowX: style.overflowX,
          overflowY: style.overflowY,
        });
      }
    }

    const brokenImages = [...document.querySelectorAll('img')]
      .filter((image) => image.complete && image.naturalWidth === 0 && isVisible(image))
      .map(describe)
      .slice(0, 20);

    const chartIssues = [];
    for (const canvas of document.querySelectorAll('canvas')) {
      if (!isVisible(canvas)) continue;
      const rect = canvas.getBoundingClientRect();
      const parent = canvas.parentElement;
      const parentRect = parent?.getBoundingClientRect();
      if (!parentRect) continue;
      if (rect.width > parentRect.width + 4 || rect.height < 40 || rect.width < 40) {
        chartIssues.push({ ...describe(canvas), parent: describe(parent), width: rect.width, height: rect.height, parentWidth: parentRect.width });
      }
    }

    const wideTables = [...document.querySelectorAll('table')]
      .filter((table) => isVisible(table) && table.getBoundingClientRect().width > table.parentElement.clientWidth + 4)
      .map((table) => ({ ...describe(table), width: table.getBoundingClientRect().width, parentWidth: table.parentElement.clientWidth }))
      .slice(0, 20);

    const fixedLayers = [...document.querySelectorAll('body *')]
      .filter((element) => {
        if (!isVisible(element)) return false;
        const style = getComputedStyle(element);
        return ['fixed', 'sticky'].includes(style.position);
      })
      .map((element) => {
        const style = getComputedStyle(element);
        return { ...describe(element), position: style.position, zIndex: style.zIndex };
      })
      .slice(0, 40);

    let bottomNavIssue = null;
    const bottomNav = document.querySelector('.h5-bottomnav');
    if (bottomNav && isVisible(bottomNav)) {
      const navRect = bottomNav.getBoundingClientRect();
      const navTopAbsolute = navRect.top + window.scrollY;
      let maxContentBottom = 0;
      let lowest = null;
      for (const element of document.querySelectorAll('main *')) {
        if (!isVisible(element) || element.children.length) continue;
        const bottom = element.getBoundingClientRect().bottom + window.scrollY;
        if (bottom > maxContentBottom) {
          maxContentBottom = bottom;
          lowest = describe(element);
        }
      }
      if (maxContentBottom > navTopAbsolute + 4) {
        bottomNavIssue = { navTopAbsolute, maxContentBottom, overlap: maxContentBottom - navTopAbsolute, lowest };
      }
    }

    return {
      title: document.title,
      url: location.href,
      viewport: { configuredWidth: window.innerWidth, width: viewportWidth, height: viewportHeight },
      document: {
        scrollWidth: doc.scrollWidth,
        clientWidth: doc.clientWidth,
        scrollHeight: doc.scrollHeight,
        bodyClasses: document.body.className,
      },
      counts: {
        hardOverflow: hardOverflow.length,
        containedOverflow: containedOverflow.length,
        tinyControls: tinyControls.length,
        zeroControls: zeroControls.length,
        coveredControls: coveredControls.length,
        smallText: smallText.length,
        clipped: clipped.length,
        brokenImages: brokenImages.length,
        chartIssues: chartIssues.length,
        wideTables: wideTables.length,
      },
      hardOverflow,
      containedOverflow,
      tinyControls: tinyControls.slice(0, 30),
      zeroControls: zeroControls.slice(0, 20),
      coveredControls: coveredControls.slice(0, 30),
      smallText,
      clipped,
      brokenImages,
      chartIssues: chartIssues.slice(0, 20),
      wideTables,
      fixedLayers,
      bottomNavIssue,
    };
  });
}

async function clickFirstVisible(page, selector) {
  const locator = page.locator(selector).locator('visible=true').first();
  await locator.waitFor({ state: 'visible', timeout: 12000 });
  await locator.click({ force: true, timeout: 5000 }).catch(async (error) => {
    await locator.evaluate((element) => element.click());
    console.warn(`forced click for ${selector}: ${error.message.split('\n')[0]}`);
  });
}

async function switchMainTab(page, tab, subtab) {
  await page.evaluate(({ targetTab, targetSubtab }) => {
    state.tab = targetTab;
    state.subtab = targetSubtab;
    document.querySelectorAll('button[data-tab]').forEach((button) => {
      button.classList.toggle('active', button.dataset.tab === targetTab);
    });
    if (typeof updateH5Topbar === 'function') updateH5Topbar();
    return renderTab();
  }, { targetTab: tab, targetSubtab: subtab });
}

async function switchLabSub(page, submode) {
  await page.evaluate((target) => {
    state.labSubMode = target;
    state.labStrategy = null;
    return renderSignalLab();
  }, submode);
}

async function runWidth(browser, width) {
  const context = await browser.newContext({
    viewport: { width, height: 844 },
    deviceScaleFactor: 2,
    isMobile: true,
    hasTouch: true,
    userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1',
    serviceWorkers: 'block',
  });
  await context.route(/^https?:\/\/(?!127\.0\.0\.1)/, async (route) => route.abort());
  await context.route('**/api/auth/me', async (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      logged_in: true,
      user: { name: 'Mobile Audit', avatar: '' },
      privileges: ['fund_score', 'detailed_view'],
    }),
  }));
  await context.addInitScript(() => {
    const today = new Date();
    const stamp = `${today.getFullYear()}${String(today.getMonth() + 1).padStart(2, '0')}${String(today.getDate()).padStart(2, '0')}`;
    localStorage.setItem('last_visit_date', stamp);
    localStorage.setItem('welcome_shown_date', stamp);
    localStorage.setItem('onboarding_done', '1');
    localStorage.setItem('nt_intro_done', '1');
  });

  const page = await context.newPage();
  const pageErrors = [];
  const consoleErrors = [];
  const localRequestFailures = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));
  page.on('console', (message) => {
    if (message.type() === 'error' && !message.text().includes('Failed to load resource')) consoleErrors.push(message.text());
  });
  page.on('requestfailed', (request) => {
    if (request.url().startsWith(BASE_URL)) localRequestFailures.push(`${request.url()} ${request.failure()?.errorText}`);
  });

  const results = [];
  const shoot = async (viewId, layout) => {
    const file = path.join(SHOT_DIR, `${width}-${slug(viewId)}.jpg`);
    await page.screenshot({ path: file, fullPage: true, type: 'jpeg', quality: 65 });
    return file;
  };

  await page.goto(`${BASE_URL}/index.html#overview`, { waitUntil: 'domcontentloaded', timeout: 90000 });
  await waitForAuth(page);
  await settle(page, 2200);

  const auditCurrent = async (viewId) => {
    const layout = await auditLayout(page);
    const screenshot = await shoot(viewId, layout);
    results.push({ viewId, screenshot, runtime: { pageErrors: [...pageErrors], consoleErrors: [...consoleErrors], localRequestFailures: [...localRequestFailures] }, layout });
  };

  await auditCurrent('overview');

  const walkMainTab = async (tab, subtabs) => {
    await switchMainTab(page, tab, subtabs[0]);
    await settle(page, 2000);
    await auditCurrent(`${tab}/${subtabs[0]}`);
    for (const subtab of subtabs.slice(1)) {
      await switchMainTab(page, tab, subtab);
      await settle(page, 1800);
      await auditCurrent(`${tab}/${subtab}`);
    }
  };

  await walkMainTab('market', marketSubtabs);
  await walkMainTab('sentiment', sentimentSubtabs);
  await walkMainTab('fund', fundSubtabs);

  await page.evaluate(() => {
    state.tab = 'lab';
    document.querySelectorAll('button[data-tab]').forEach((button) => {
      button.classList.toggle('active', button.dataset.tab === 'lab');
    });
    if (typeof updateH5Topbar === 'function') updateH5Topbar();
    return renderTab();
  });
  await settle(page, 2500);
  for (const group of labGroups) {
    for (const child of group.children) {
      await switchLabSub(page, child);
      await settle(page, child === 'sigkelly' ? 4500 : 2000);
      await auditCurrent(`lab/${child}`);
    }
  }

  for (const item of staticPaths) {
    pageErrors.length = 0;
    consoleErrors.length = 0;
    localRequestFailures.length = 0;
    await page.goto(`${BASE_URL}${item.path}`, { waitUntil: 'domcontentloaded', timeout: 60000 });
    await settle(page, 1500);
    await auditCurrent(item.id);
  }

  await context.close();
  return results;
}

const browser = await chromium.launch({ headless: true });
try {
  await fs.mkdir(SHOT_DIR, { recursive: true });
  const allResults = [];
  for (const width of WIDTHS) {
    console.log(`auditing width=${width}`);
    allResults.push(...await runWidth(browser, width));
  }

  const passed = allResults.every((result) => result.layout.document.scrollWidth <= result.layout.viewport.width + 2
    && result.layout.counts.hardOverflow === 0
    && result.layout.counts.zeroControls === 0
    && result.layout.counts.brokenImages === 0
    && result.layout.counts.chartIssues === 0
    && result.runtime.pageErrors.length === 0
    && result.runtime.localRequestFailures.length === 0);

  const summaryByView = {};
  for (const result of allResults) {
    const key = result.viewId;
    summaryByView[key] ||= { viewId: key, widths: {} };
    summaryByView[key].widths[result.layout.configuredViewportWidth || result.layout.viewport.width] = {
      passed: result.layout.document.scrollWidth <= result.layout.viewport.width + 2
        && result.layout.counts.hardOverflow === 0
        && result.layout.counts.zeroControls === 0
        && result.layout.counts.brokenImages === 0
        && result.layout.counts.chartIssues === 0,
      ...result.layout.counts,
      docScrollWidth: result.layout.document.scrollWidth,
      viewportWidth: result.layout.viewport.width,
    };
  }

  const output = {
    generatedAt: new Date().toISOString(),
    baseUrl: BASE_URL,
    passed,
    widths: WIDTHS,
    viewCount: Object.keys(summaryByView).length,
    summary: Object.values(summaryByView),
    results: allResults,
  };
  const temporaryPath = `${OUTPUT_PATH}.tmp`;
  await fs.writeFile(temporaryPath, `${JSON.stringify(output, null, 2)}\n`, 'utf8');
  await fs.rename(temporaryPath, OUTPUT_PATH);
  console.log(JSON.stringify({ passed, viewCount: output.viewCount, report: OUTPUT_PATH }, null, 2));
  if (!passed) process.exitCode = 1;
} finally {
  await browser.close();
}
