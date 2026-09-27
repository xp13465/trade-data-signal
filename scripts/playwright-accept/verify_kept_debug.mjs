import { chromium } from 'playwright';
const b = await chromium.launch({ headless: true });
const page = await b.newPage({ viewport:{width:1400,height:4000} });
await page.goto('https://ss.fx8.store', { waitUntil:'domcontentloaded', timeout:60000 });
await page.waitForTimeout(10000);
// For each sig-item, get day group + whether it has badges
const data = await page.evaluate(() => {
  const out = [];
  const items = document.querySelectorAll('.sig-item');
  for (const it of items) {
    const txt = (it.textContent||'').trim().slice(0,60).replace(/\s+/g,' ');
    const cls = it.className;
    out.push({ txt, hasOk: !!it.querySelector('.sig-poscap-ok'), hasFull: !!it.querySelector('.sig-poscap-full'), hasNotuni: !!it.querySelector('.sig-poscap-notunibadge'), hasWarn: !!it.querySelector('.sig-poscap-warnbadge'), hasHit: !!it.querySelector('.sig-ai-hit-badge'), cls: cls.slice(0,60) });
  }
  return out;
});
// group by day order: match date-like prefixes (MM-DD) from row text
let prevDate='';
let day=0;
for (const r of data) {
  console.log((r.hasOk?'[OK]':(r.hasFull?'[FULL]':(r.hasWarn?'[WARN]':(r.hasNotuni?'[NOTUNI]':(r.hasHit?'[HIT]':'')))))+' '+r.txt);
}
await b.close();
