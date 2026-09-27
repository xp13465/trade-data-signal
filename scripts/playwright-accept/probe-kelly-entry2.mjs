import { chromium } from 'playwright';
const url = process.env.URL || 'https://ss.fx8.store';
const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({
  userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36',
  viewport: { width: 1440, height: 2200 },
});
const page = await ctx.newPage();
page.on('pageerror', e => console.log('[pageerror]', String(e).slice(0,200)));
try {
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForTimeout(5000);
  // 点击「策略实验」
  const clicked = await page.evaluate(() => {
    const btn = Array.from(document.querySelectorAll('button')).find(b => (b.textContent||'').includes('策略实验'));
    if (btn) { btn.click(); return true; } return false;
  });
  console.log('clicked 策略实验 =', clicked);
  await page.waitForTimeout(3000);
  const subnav = await page.$$eval('.lab-subnav button, .lab-subnav-child button', els => els.map(e => (e.className||'').slice(0,50)+' | '+(e.textContent||'').trim().slice(0,50)));
  console.log('SUBNAV:');
  subnav.forEach(s => console.log('  '+s));
  // 含凯利的子tab
  const kellyTabs = await page.$$eval('button', els => els.filter(e=>/凯利|sigkelly/i.test(e.textContent||'')).map(e=>(e.className||'').slice(0,40)+' | '+(e.textContent||'').trim().slice(0,60)));
  console.log('kelly tabs:');
  kellyTabs.forEach(t=>console.log('  '+t));
  const hasSig = await page.$$eval('.lab-sigkelly-wrap, .lab-sigkelly-all-group, .lab-sigkelly-bar', els=>els.length);
  console.log('has sigkelly =', hasSig);
  const bodyTxt = await page.evaluate(()=>document.body.innerText.slice(0,400));
  console.log('body:', bodyTxt.replace(/\n+/g,' | ').slice(0,300));
} catch(e) { console.log('ERR', String(e).slice(0,500)); }
await browser.close();
