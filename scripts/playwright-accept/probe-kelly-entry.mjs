import { chromium } from 'playwright';
const url = process.env.URL || 'https://ss.fx8.store';
const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({
  userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36',
  viewport: { width: 1440, height: 2000 },
});
const page = await ctx.newPage();
page.on('console', m => { if (m.type()==='error') console.log('[console.error]', m.text().slice(0,200)); });
page.on('pageerror', e => console.log('[pageerror]', String(e).slice(0,300)));
try {
  const resp = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
  console.log('status=', resp && resp.status(), 'finalURL=', page.url());
  await page.waitForTimeout(8000);
  // 找 tabs / lab-subnav
  const tabs = await page.$$eval('.tabs button, .lab-subnav button, .lab-subnav-child button, .lab-sigkelly-bar', els => els.map(e => (e.className||'').slice(0,60) + ' | ' + (e.textContent||'').trim().slice(0,60)));
  console.log('TABS/SUBNav:');
  tabs.forEach(t => console.log('  ' + t));
  // 是否已有 sigkelly 内容
  const hasSig = await page.$$eval('.lab-sigkelly-wrap, .lab-sigkelly-all-group', els => els.length);
  console.log('has sigkelly content =', hasSig);
  // body 文本前500
  const bodyTxt = await page.evaluate(() => document.body.innerText.slice(0, 800));
  console.log('body text head:', bodyTxt.replace(/\n+/g,' | ').slice(0,500));
  // 找含"凯利"的按钮
  const kellyBtns = await page.$$eval('button, a, span', els => els.filter(e => /凯利|kelly/i.test(e.textContent||'')).slice(0,10).map(e => (e.tagName+'.'+(e.className||'').slice(0,40)+' | '+(e.textContent||'').trim().slice(0,50))));
  console.log('kelly-like buttons:');
  kellyBtns.forEach(b => console.log('  ' + b));
} catch(e) { console.log('ERR', String(e).slice(0,500)); }
await browser.close();
