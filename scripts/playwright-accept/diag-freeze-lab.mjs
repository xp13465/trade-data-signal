import { chromium } from 'playwright';
const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({
  userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36',
  viewport: { width: 1440, height: 2400 },
});
const page = await ctx.newPage();
await page.goto('https://ss.fx8.store/#lab?sub=sigkelly', { waitUntil: 'domcontentloaded', timeout: 90000 });
await page.waitForTimeout(10000);
const st = await page.evaluate(() => {
  return {
    title: document.title,
    url: location.href,
    hasLabSigKellyGroup: !!document.querySelector('.lab-sigkelly-group'),
    hasLabCustom: !!document.querySelector('.lab-sigkelly-all-group'),
    hasOnboarding: !!document.querySelector('.onboarding-modal, .rule-modal-overlay'),
    sigkellyBtns: Array.from(document.querySelectorAll('button')).map(b => (b.textContent || '').trim().slice(0, 20)).filter(t => t.length).slice(0, 40),
    loadingTxt: Array.from(document.querySelectorAll('.lab-custom-loading, .lab-sigkelly-all-loading')).map(x => x.textContent.trim().slice(0, 60)).slice(0, 3),
  };
});
console.log(JSON.stringify(st, null, 1));
await browser.close();