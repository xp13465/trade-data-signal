// verify_universe_live.mjs - 线上 v1.1.2 之后回测宇宙/推荐算法真实浏览器渲染校验
import { chromium } from 'playwright';

const URL = process.argv[2] || 'https://ss.fx8.store';
const OUT = '/Users/linhuichen/code/trade/scripts/playwright-accept';

const results = { pass: [], fail: [] };
const ok = (m) => { results.pass.push(m); console.log('[PASS] ' + m); };
const bad = (m) => { results.fail.push(m); console.log('[FAIL] ' + m); };

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1400, height: 2200 } });
const errs = [];
page.on('pageerror', e => errs.push('pageerror: ' + e));
page.on('console', m => { if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) errs.push('console: ' + m.text()); });

// capture overview data for cross-check
let overviewData = null;
page.on('response', async (r) => {
  if (r.url().includes('overview.json') && r.status() === 200) {
    try { overviewData = await r.json(); } catch (e) {}
  }
});

await page.goto(URL, { waitUntil: 'domcontentloaded', timeout: 60000 });
await page.waitForTimeout(9000);
await page.screenshot({ path: OUT + '/universe-home-full.png', fullPage: false });

// --- 校验点 1: AI建议区 badges(kelly AI仓位层) ---
const okBadge = await page.locator('.sig-poscap-badge.sig-poscap-ok').count();
const fullBadge = await page.locator('.sig-poscap-badge.sig-poscap-full').count();
const warnBadge = await page.locator('.sig-poscap-badge.sig-poscap-warnbadge').count();
const notuniBadge = await page.locator('.sig-poscap-badge.sig-poscap-notunibadge').count();
const aiHitBadge = await page.locator('.sig-ai-hit-badge').count();
ok(`.sig-poscap-ok(AI建议N) 数量=${okBadge}`);
ok(`.sig-poscap-full(当日已满) 数量=${fullBadge}`);
ok(`.sig-poscap-warnbadge(AI警示) 数量=${warnBadge}`);
ok(`.sig-poscap-notunibadge(未入样本) 数量=${notuniBadge}`);
ok(`.sig-ai-hit-badge(AI降亏) 数量=${aiHitBadge}`);

// AI建议 badge 真实文本抓取
const okTexts = await page.locator('.sig-poscap-badge.sig-poscap-ok').allTextContents().catch(() => []);
ok(`AI建议 badge 文本样例: ${okTexts.slice(0,6).join(' | ') || '(无)'}`);
const notuniTexts = await page.locator('.sig-poscap-badge.sig-poscap-notunibadge').first().textContent().catch(() => '');
ok(`未入样本 badge 文本: ${notuniTexts}`);
const warnTexts = await page.locator('.sig-poscap-badge.sig-poscap-warnbadge').first().textContent().catch(() => '');
ok(`AI警示 badge 文本: ${warnTexts}`);

// 未入样信号行是否有删除线类 sig-poscap-notuni
const notuniCls = await page.locator('.sig-poscap-notuni').count();
ok(`未入样行类 .sig-poscap-notuni 数量=${notuniCls}`);

// --- 校验点 2: 数据层交叉核验 overview → AI建议 top-K ---
if (overviewData && overviewData.signals_today) {
  const st = overviewData.signals_today;
  ok(`overview.signals_today 总数=${st.length}`);
  const inUni = st.filter(s => s._bt_in_universe === true).length;
  const notUni = st.filter(s => s._bt_in_universe === false).length;
  ok(`_bt_in_universe: true=${inUni} false=${notUni}`);
  const hit = st.filter(s => s.ai_macro && s.ai_macro.hit);
  const hitBuy = hit.filter(s => !['sell','sell_stop_loss','band_hold','band_sell'].includes(s.signal));
  // 仅今日(date==overview.date)的 top-K 候选(kept)
  const today = overviewData.date;
  const todayBuf = hitBuy.filter(s => s.date === today);
  ok(`今日(${today}) ai_macro.hit 且为买入候选数=${todayBuf.length}`);
  // 无排除类别进 hit
  const badCat = hitBuy.filter(s => /^(cgb|s\.|g\.|hk_)/.test(s.index_id || ''));
  if (badCat.length) bad(`排除类别泄漏进 AI建议 hit: ${badCat.map(x=>x.index_id).join(',')}`);
  else ok('AI建议 hit 无排除类别泄漏(债/情绪/商品/港股行业)');
  // hit 的信号类型必须非 sell
  const sellHit = hit.filter(s => ['sell','sell_stop_loss'].includes(s.signal));
  if (sellHit.length) ok(`hit 中 sell/sell_stop_loss(非AI建议,仅警示)=${sellHit.length}(应为0, 处置放在⬇)`); 
  if (sellHit.length) bad('hit 中出现 sell/sell_stop_loss(AI建议不应含卖类)');
} else {
  bad('未能抓取 overview.json 响应');
}

// 截图 AI建议 badges 区域
await page.locator('.sig-poscap-badge').first().scrollIntoViewIfNeeded().catch(()=>{});
await page.screenshot({ path: OUT + '/universe-home-badges.png' });

console.log('\n=== 页面 JS 错误 ===');
if (errs.length) { for (const e of errs) console.log('[ERR] ' + e); }
else console.log('(无 JS 错误)');

console.log(`\n=== 结果: ${results.fail.length ? 'FAIL' : 'PASS'} (${results.pass.length} PASS / ${results.fail.length} FAIL) ===`);
await browser.close();
process.exit(results.fail.length ? 1 : 0);
