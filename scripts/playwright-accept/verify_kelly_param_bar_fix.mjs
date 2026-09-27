import fs from 'node:fs/promises';
import path from 'node:path';
import { chromium } from 'playwright';

const BASE_URL = process.env.BASE_URL || 'http://127.0.0.1:8124';
const OUTPUT_PATH = '/tmp/codex-reports/kelly-param-bar-fix-machine-check.json';
const SCREENSHOT_DIR = '/tmp/codex-reports/kelly-param-bar-fix';

const mobileWidths = [320, 375, 390, 414];
const desktopWidths = [768, 1024, 1280];

function approx(actual, expected, tolerance = 2) {
  return Math.abs(actual - expected) <= tolerance;
}

async function collectLayout(page) {
  return page.evaluate(() => {
    const rec = document.querySelector('.lab-sigkelly-toggle-group-rec');
    const poscap = document.querySelector('.lab-sigkelly-toggle-group-poscap');
    const paramsBody = document.querySelector('.lab-sigkelly-params-body');
    const detailButton = document.querySelector('#lab-kelly-ai-macro-btn');
    const moreBody = document.querySelector('.lab-sigkelly-toggle-more-body');

    if (!rec || !poscap) {
      return { present: false, docScrollWidth: document.documentElement.scrollWidth };
    }

    const recStyle = getComputedStyle(rec);
    const poscapStyle = getComputedStyle(poscap);
    const recRect = rec.getBoundingClientRect();
    const poscapRect = poscap.getBoundingClientRect();
    const recChildren = [...rec.children].map((child) => {
      const rect = child.getBoundingClientRect();
      const style = getComputedStyle(child);
      return {
        className: child.className,
        text: (child.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 160),
        width: rect.width,
        height: rect.height,
        left: rect.left,
        right: rect.right,
        whiteSpace: style.whiteSpace,
        overflowX: style.overflowX,
        overflowY: style.overflowY,
        scrollWidth: child.scrollWidth,
        clientWidth: child.clientWidth,
        overflowingDescendants: [...child.querySelectorAll('*')]
          .map((node) => {
            const childRect = node.getBoundingClientRect();
            const nodeStyle = getComputedStyle(node);
            return {
              tagName: node.tagName,
              className: String(node.className || ''),
              text: (node.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 120),
              left: childRect.left,
              right: childRect.right,
              width: childRect.width,
              whiteSpace: nodeStyle.whiteSpace,
              wordBreak: nodeStyle.wordBreak,
              overflowBeyondCell: childRect.right - rect.right,
            };
          })
          .filter((node) => node.overflowBeyondCell > 1)
          .sort((a, b) => b.overflowBeyondCell - a.overflowBeyondCell)
          .slice(0, 8),
      };
    });
    const poscapChildren = [...poscap.children].map((child) => {
      const rect = child.getBoundingClientRect();
      return { className: child.className, width: rect.width, height: rect.height, left: rect.left, right: rect.right };
    });
    const tier = rec.querySelector(':scope > .lab-sigkelly-toggle-tier');

    return {
      present: true,
      viewport: { width: window.innerWidth, height: window.innerHeight },
      docScrollWidth: document.documentElement.scrollWidth,
      bodyScrollWidth: document.body.scrollWidth,
      paramsOpen: paramsBody ? paramsBody.classList.contains('lab-sigkelly-params-open') : null,
      detailButtonText: detailButton?.textContent?.trim() || null,
      moreBodyVisible: !!moreBody && moreBody.offsetParent !== null && getComputedStyle(moreBody).display !== 'none',
      rec: {
        display: recStyle.display,
        gridTemplateColumns: recStyle.gridTemplateColumns,
        flexDirection: recStyle.flexDirection,
        gap: parseFloat(recStyle.columnGap || recStyle.gap) || 0,
        contentWidth: rec.clientWidth
          - parseFloat(recStyle.paddingLeft || '0')
          - parseFloat(recStyle.paddingRight || '0'),
        width: recRect.width,
        clientWidth: rec.clientWidth,
        height: recRect.height,
        children: recChildren,
      },
      poscap: {
        display: poscapStyle.display,
        flexDirection: poscapStyle.flexDirection,
        width: poscapRect.width,
        clientWidth: poscap.clientWidth,
        height: poscapRect.height,
        children: poscapChildren,
      },
      tier: tier ? { width: tier.getBoundingClientRect().width, height: tier.getBoundingClientRect().height } : null,
      horizontalOverflowNodes: [...document.querySelectorAll('body *')]
        .filter((node) => node.getBoundingClientRect().right > window.innerWidth + 2)
        .slice(0, 12)
        .map((node) => ({
          tagName: node.tagName,
          className: String(node.className || ''),
          right: Math.round(node.getBoundingClientRect().right),
          text: (node.textContent || '').trim().slice(0, 60),
        })),
    };
  });
}

function assertMobile(layout, width) {
  const failures = [];
  if (!layout.present) failures.push('Kelly parameter groups were not rendered');
  if (!layout.paramsOpen) failures.push('parameter body is not open');

  if (layout.rec.display !== 'grid') failures.push(`rec display=${layout.rec.display}, expected grid`);
  const columns = layout.rec.gridTemplateColumns.split(/\s+/).filter(Boolean).map(parseFloat);
  if (columns.length !== 2 || columns.some((value) => !Number.isFinite(value))) {
    failures.push(`rec gridTemplateColumns=${layout.rec.gridTemplateColumns}`);
  } else if (!approx(columns[0], columns[1], 2)) {
    failures.push(`unequal rec columns: ${columns.join('x')}`);
  } else if (!approx(columns[0], layout.rec.contentWidth / 2 - layout.rec.gap / 2, 3)) {
    failures.push(`rec columns do not fill content box: ${columns.join('x')}, content=${layout.rec.contentWidth}`);
  }

  if (layout.poscap.display !== 'flex' || layout.poscap.flexDirection !== 'column') {
    failures.push(`poscap=${layout.poscap.display}/${layout.poscap.flexDirection}, expected flex column`);
  }

  if (layout.tier) {
    if (layout.tier.width > layout.rec.contentWidth + 2 || layout.tier.width < layout.rec.contentWidth * 0.9) {
      failures.push(`tier width=${layout.tier.width}, rec content=${layout.rec.contentWidth}`);
    }
  } else {
    failures.push('tier row missing');
  }

  const tallChild = layout.rec.children.find((child) => child.height > 120);
  if (tallChild) failures.push(`over-tall rec child ${tallChild.className}: ${tallChild.height}px`);
  const visuallyClippedChild = layout.rec.children.find((child) => child.overflowingDescendants.length > 0);
  if (visuallyClippedChild) {
    failures.push(`rec child visually overflows cell: ${JSON.stringify(visuallyClippedChild.overflowingDescendants)}`);
  }

  for (const child of layout.poscap.children) {
    if (child.width > layout.poscap.clientWidth + 2) {
      failures.push(`poscap child exceeds container: ${child.className}, ${child.width} vs ${layout.poscap.clientWidth}`);
    }
  }

  if (layout.docScrollWidth > layout.viewport.width + 2) {
    failures.push(`document scrollWidth=${layout.docScrollWidth} > viewport=${layout.viewport.width}`);
  }
  return { width, failures, layout };
}

function assertDesktop(layout, width) {
  const failures = [];
  if (layout.rec.display !== 'flex') failures.push(`desktop ${width}: rec display=${layout.rec.display}, expected flex`);
  if (layout.rec.flexDirection !== 'row') failures.push(`desktop ${width}: rec direction=${layout.rec.flexDirection}, expected row`);
  if (layout.poscap.display !== 'flex' || layout.poscap.flexDirection !== 'row') {
    failures.push(`desktop ${width}: poscap=${layout.poscap.display}/${layout.poscap.flexDirection}, expected flex row`);
  }
  if (layout.docScrollWidth > layout.viewport.width + 2) {
    failures.push(`desktop ${width}: document scrollWidth=${layout.docScrollWidth} > viewport=${layout.viewport.width}`);
  }
  return { width, failures, layout };
}

const browser = await chromium.launch({ headless: true });
try {
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 },
    deviceScaleFactor: 2,
    isMobile: true,
    hasTouch: true,
    userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1',
    serviceWorkers: 'block',
  });
  await context.route(/^(?!.*127\.0\.0\.1)/, (route) => route.abort());
  await context.addInitScript(() => {
    localStorage.setItem('lab_sigkelly_params_open', '1');
  });

  const page = await context.newPage();
  const consoleErrors = [];
  const localRequestFailures = [];
  page.on('pageerror', (error) => consoleErrors.push(`pageerror: ${error.message}`));
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text());
  });
  page.on('requestfailed', (request) => {
    if (request.url().startsWith(BASE_URL)) {
      localRequestFailures.push(`${request.url()} ${request.failure()?.errorText}`);
    }
  });

  await page.goto(`${BASE_URL}/index.html#lab?sub=sigkelly`, { waitUntil: 'domcontentloaded', timeout: 90000 });
  await page.waitForSelector('.lab-sigkelly-toggle-group-rec', { state: 'attached', timeout: 90000 });
  const initialParamState = await page.evaluate(() => ({
    storedValue: localStorage.getItem('lab_sigkelly_params_open'),
    bodyClasses: document.querySelector('.lab-sigkelly-params-body')?.className || null,
    buttonText: document.querySelector('#lab-kelly-params-toggle')?.textContent?.trim() || null,
    recVisible: !!document.querySelector('.lab-sigkelly-toggle-group-rec')?.offsetParent,
    recRect: document.querySelector('.lab-sigkelly-toggle-group-rec')?.getBoundingClientRect().toJSON() || null,
    recAncestors: (() => {
      let node = document.querySelector('.lab-sigkelly-toggle-group-rec')?.parentElement;
      const chain = [];
      while (node && chain.length < 12) {
        const style = getComputedStyle(node);
        chain.push({
          tagName: node.tagName,
          className: String(node.className || ''),
          display: style.display,
          visibility: style.visibility,
          rect: node.getBoundingClientRect().toJSON(),
        });
        node = node.parentElement;
      }
      return chain;
    })(),
  }));
  if (!initialParamState.recVisible) {
    await page.evaluate(() => document.querySelector('#lab-kelly-ai-macro-btn')?.click());
    await page.waitForSelector('.lab-sigkelly-toggle-group-rec', { state: 'visible', timeout: 15000 });
  }
  await page.waitForSelector('.lab-sigkelly-toggle-group-poscap', { state: 'attached', timeout: 10000 });

  await fs.mkdir(SCREENSHOT_DIR, { recursive: true });
  const mobileResults = [];
  let expandedDetail = !initialParamState.recVisible;
  for (const width of mobileWidths) {
    await page.setViewportSize({ width, height: 844 });
    await page.waitForTimeout(250);
    let layout = await collectLayout(page);

    if (!expandedDetail) {
      await page.evaluate(() => document.querySelector('#lab-kelly-ai-macro-btn')?.click());
      await page.waitForFunction(() => {
        const button = document.querySelector('#lab-kelly-ai-macro-btn');
        const body = document.querySelector('.lab-sigkelly-toggle-more-body');
        return button?.textContent?.includes('收起') && body && body.offsetParent !== null;
      }, undefined, { timeout: 15000 });
      expandedDetail = true;
      layout = await collectLayout(page);
    }

    const result = assertMobile(layout, width);
    mobileResults.push(result);
    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, `mobile-${width}${expandedDetail ? '-detail-open' : ''}.png`),
      fullPage: true,
    });
  }

  const desktopResults = [];
  for (const width of desktopWidths) {
    await page.setViewportSize({ width, height: 900 });
    await page.waitForTimeout(300);
    const layout = await collectLayout(page);
    const result = assertDesktop(layout, width);
    desktopResults.push(result);
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, `desktop-${width}.png`), fullPage: true });
  }

  const passed = [...mobileResults, ...desktopResults].every((result) => result.failures.length === 0)
    && localRequestFailures.length === 0
    && !consoleErrors.some((message) => !message.startsWith('Failed to load resource: net::ERR_FAILED'));

  const output = {
    generatedAt: new Date().toISOString(),
    baseUrl: BASE_URL,
    url: page.url(),
    passed,
    summary: {
      mobileChecks: mobileResults.length,
      desktopChecks: desktopWidths.length,
      failures: [...mobileResults, ...desktopResults].flatMap((result) => result.failures),
      consoleErrors,
      localRequestFailures,
    },
    mobileResults: mobileResults.map(({ width, failures, layout }) => ({ width, failures, snapshot: layout })),
    desktopResults: desktopResults.map(({ width, failures, layout }) => ({ width, failures, snapshot: layout })),
  };

  const temporaryPath = `${OUTPUT_PATH}.tmp`;
  await fs.writeFile(temporaryPath, `${JSON.stringify(output, null, 2)}\n`, 'utf8');
  await fs.rename(temporaryPath, OUTPUT_PATH);
  console.log(JSON.stringify(output.summary, null, 2));
  console.log(`report=${OUTPUT_PATH}`);
  if (!passed) process.exitCode = 1;
} finally {
  await browser.close();
}
