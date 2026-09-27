import { chromium } from 'playwright';
const b = await chromium.launch({ headless: true });
const page = await b.newPage({ viewport:{width:1400,height:4000} });
await page.goto('https://ss.fx8.store', { waitUntil:'domcontentloaded', timeout:60000 });
await page.waitForTimeout(10000);
const rows = await page.evaluate(() => {
  const out=[];
  document.querySelectorAll('.sig-item').forEach(it=>{
    const t=(it.textContent||'');
    if(/CAC40|标普|纳斯达克|道琼|德国DAX/.test(t)) {
      out.push({ txt: t.replace(/\s+/g,' ').trim().slice(0,70), cls: it.className.slice(0,70), hasOk: !!it.querySelector('.sig-poscap-ok'), hasHit: !!it.querySelector('.sig-ai-hit-badge'), hasNotuni: !!it.querySelector('.sig-poscap-notunibadge'), sigKept: it.classList.contains('sig-poscap-kept'), sigNotuni: it.classList.contains('sig-poscap-notuni'), dash: it.classList.contains('sig-poscap-notuni-dash') });
    }
  });
  return out;
});
for (const r of rows) console.log(JSON.stringify(r));
await b.close();
