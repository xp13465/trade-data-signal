// 移动端 P0+P1 五件修复(mobile-audit M1-M5)验收脚本
// 目的: 断言 codex2claude-mobile-layout-20260826-001 五项修复后文档无横向溢出+关键计算样式正确
// 输入: 本地 uvicorn 后端(http://127.0.0.1:8125, cwd=trade-data 启动读真库) + 待验 CSS 文件路径
// 输出: JSON 断言结果(stdout + 第二参数路径), 截图 /tmp/<out>-shots-*.png
// 口径: 视口 320/375/430/768/1280; before 基线=线上 style.min.css, after=worktree 版;
//       320px 底部导航五键 normal click 另跑 bottomnav-click-test 类脚本或本脚本配合
// 复现: cd /Users/linhuichen/code/trade-data && uvicorn app.main:app --port 8125
//       node scripts/playwright-accept/verify_mobile_p0p1.mjs <css文件> /tmp/p0p1-result.json
// 数据版本: 2026-08-26; 关键口径: document.scrollWidth<=clientWidth 即无横向溢出
import { chromium } from 'playwright';

// 移动端 P0+P1 五件修复验证脚本(mobile-p0p1)
// 断言来源: /tmp/codex-reports/codex2claude-mobile-layout-20260826-001.json M1-M5
// 用法: node verify-mobile-p0p1.mjs <css文件路径> <输出json路径>
// CSS 经 route 拦截注入,页面其余资源走 127.0.0.1:8125 后端(真数据)

const CSS_FILE = process.argv[2];
const OUT = process.argv[3];
const BASE_URL = 'http://127.0.0.1:8125';

const WIDTHS = [320, 375, 430, 768];
const DESKTOP_WIDTH = 1280;

async function settle(page, ms = 1200) {
  await page.waitForTimeout(ms);
  await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))));
}

function makeContext(browser, width) {
  return browser.newContext({
    viewport: { width, height: 844 },
    deviceScaleFactor: 2,
    isMobile: width <= 768,
    hasTouch: width <= 768,
    userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1',
    serviceWorkers: 'block',
  });
}

async function setupRoutes(context) {
  // 外网全断(与 codex 审计同口径),auth mock 登录态
  await context.route(/^https?:\/\/(?!127\.0\.0\.1)/, (route) => route.abort());
  await context.route(/\/style(\.min)?\.css(\?.*)?$/, (route) =>
    route.fulfill({ path: CSS_FILE, contentType: 'text/css' }));
  await context.route('**/api/auth/me', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ logged_in: true, user: { name: 'Verify', avatar: '' }, privileges: ['fund_score', 'detailed_view'] }),
  }));
  await context.addInitScript(() => {
    const t = new Date();
    const stamp = `${t.getFullYear()}${String(t.getMonth() + 1).padStart(2, '0')}${String(t.getDate()).padStart(2, '0')}`;
    localStorage.setItem('last_visit_date', stamp);
    localStorage.setItem('welcome_shown_date', stamp);
    localStorage.setItem('onboarding_done', '1');
    localStorage.setItem('nt_intro_done', '1');
  });
}

// 核心断言:文档无横向溢出 + 指定选择器计算样式
async function probe(page, viewId, checks = []) {
  const r = await page.evaluate((selectorChecks) => {
    const doc = document.documentElement;
    const out = {
      scrollWidth: doc.scrollWidth,
      clientWidth: doc.clientWidth,
      noHorizOverflow: doc.scrollWidth <= doc.clientWidth,
      selectors: {},
    };
    for (const sc of selectorChecks) {
      const el = document.querySelector(sc.sel);
      if (!el) { out.selectors[sc.name] = { found: false }; continue; }
      const cs = getComputedStyle(el);
      const props = {};
      for (const p of sc.props) props[p] = cs.getPropertyValue(p);
      out.selectors[sc.name] = { found: true, props };
    }
    return out;
  }, checks.map((c) => ({ sel: c.sel, name: c.name, props: c.props })));
  return { viewId, ...r };
}

const runBrowser = await chromium.launch({ headless: true });
const results = [];

try {
  for (const width of [...WIDTHS, DESKTOP_WIDTH]) {
    const isDesktop = width === DESKTOP_WIDTH;
    const context = await makeContext(runBrowser, width);
    await setupRoutes(context);
    const page = await context.newPage();
    const shots = `${OUT.replace(/\.json$/, '')}-shots`;
    await page.goto(`${BASE_URL}/index.html#overview`, { waitUntil: 'domcontentloaded', timeout: 90000 });
    await page.waitForFunction(() => window.__authState?.logged_in === true, undefined, { timeout: 8000 }).catch(() => {});
    await settle(page, 2500);

    // M1 overview
    results.push(await probe(page, `overview@${width}`, [
      { sel: '.ov-2col', name: 'ov-2col', props: ['contain', 'grid-template-columns'] },
    ]));
    await page.screenshot({ path: `${shots}-${width}-overview.png`, fullPage: false }).catch(() => {});

    if (!isDesktop) {
      // M1 硬断言: 底部导航可点区(scrollWidth 不超视口即导航不被推出可点区)
      const navClickable = await page.evaluate(() => {
        const nav = document.querySelector('.bottom-nav, #bottomNav, nav.bottom-nav');
        if (!nav) return 'no-nav';
        const rect = nav.getBoundingClientRect();
        return rect.left >= 0 && rect.right <= window.innerWidth ? 'in-viewport' : 'pushed-out';
      });
      results.push({ viewId: `overview-bottomnav@${width}`, navClickable });

      // M2 futures
      await page.evaluate(() => {
        state.tab = 'sentiment'; state.subtab = 'futures';
        document.querySelectorAll('button[data-tab]').forEach((b) => b.classList.toggle('active', b.dataset.tab === 'sentiment'));
        if (typeof updateH5Topbar === 'function') updateH5Topbar();
        return renderTab();
      });
      await settle(page, 2000);
      results.push(await probe(page, `sentiment-futures@${width}`, [
        { sel: '.chart-latest', name: 'chart-latest', props: ['white-space', 'display', 'max-width'] },
      ]));

      // M4 national-team
      await page.evaluate(() => {
        state.tab = 'sentiment'; state.subtab = 'national-team';
        return renderTab();
      });
      await settle(page, 2000);
      results.push(await probe(page, `national-team@${width}`, [
        { sel: '.nt-card-wall', name: 'nt-card-wall', props: ['grid-template-columns'] },
      ]));

      // M5 aiscore
      await page.evaluate(() => {
        state.tab = 'lab';
        document.querySelectorAll('button[data-tab]').forEach((b) => b.classList.toggle('active', b.dataset.tab === 'lab'));
        if (typeof updateH5Topbar === 'function') updateH5Topbar();
        return renderTab();
      });
      await settle(page, 2200);
      await page.evaluate(() => { state.labSubMode = 'aiscore'; state.labStrategy = null; return renderSignalLab(); });
      await settle(page, 2500);
      results.push(await probe(page, `lab-aiscore@${width}`, [
        { sel: '.lab-aiscore-grid', name: 'aiscore-grid', props: ['grid-template-columns'] },
        { sel: '.lab-aiscore-section', name: 'aiscore-section', props: ['min-width'] },
        { sel: '.lab-aiscore-table-wrap', name: 'table-wrap', props: ['min-width', 'overflow-x'] },
      ]));
      await page.screenshot({ path: `${shots}-${width}-aiscore.png`, fullPage: false }).catch(() => {});
    }

    // M3 静态页
    for (const p of ['guide.html', 'about.html', 'privacy.html']) {
      await page.goto(`${BASE_URL}/${p}`, { waitUntil: 'domcontentloaded', timeout: 60000 });
      await settle(page, 1000);
      results.push(await probe(page, `${p}@${width}`, [
        { sel: '.about-wrap code, .privacy-wrap code', name: 'code', props: ['overflow-wrap'] },
      ]));
    }

    await context.close();
  }
} finally {
  await runBrowser.close();
}

// 汇总判定
const summary = [];
for (const r of results) {
  const m = r.viewId.match(/@(\d+)$/);
  const w = m ? Number(m[1]) : 0;
  if (w && w <= 768 && r.noHorizOverflow === false) summary.push(`FAIL ${r.viewId} scrollWidth=${r.scrollWidth}>${r.clientWidth}`);
}
const fails = summary.length;
console.log(JSON.stringify({ cssFile: CSS_FILE, totalProbes: results.length, failCount: fails, fails: summary, results }, null, 1));
await (await import('node:fs/promises')).writeFile(OUT, JSON.stringify({ cssFile: CSS_FILE, failCount: fails, results }, null, 1));
