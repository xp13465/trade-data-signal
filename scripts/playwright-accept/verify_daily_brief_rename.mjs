// 前端 rule 版渲染验证(Playwright 无痕浏览器,零 localStorage)
import { chromium } from 'playwright';

const BASE = 'http://localhost:8137/';
const results = [];
const check = (name, cond, extra = '') => {
  results.push({ name, pass: !!cond, extra });
};

const browser = await chromium.launch();
const ctx = await browser.newContext(); // 无痕,零 localStorage
const page = await ctx.newPage();
const errors = [];
page.on('pageerror', (e) => errors.push(String(e)));
page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });

try {
  await page.goto(BASE, { waitUntil: 'networkidle', timeout: 60000 });
} catch (e) {
  check('页面加载', false, String(e).slice(0, 200));
  console.log(JSON.stringify(results, null, 2));
  await browser.close();
  process.exit(1);
}

// 1. 首页 banner 按钮文本应为「📋 每日速递」(非「🤖 AI 预测」)
await page.waitForSelector('.summary-ai-btn', { timeout: 30000 }).catch(() => {});
const btnText = await page.$eval('.summary-ai-btn', (el) => el.textContent.trim()).catch(() => '');
check('首页按钮文本=每日速递', btnText.includes('每日速递'), `btn="${btnText}"`);
check('首页按钮不含AI预测', !btnText.includes('AI'), `btn="${btnText}"`);

// 2. 点击按钮打开弹窗
await page.click('.summary-ai-btn').catch(() => {});
await page.waitForSelector('#dailyBriefModal:not(.hidden)', { timeout: 15000 }).catch(() => {});
const modalVisible = await page.$eval('#dailyBriefModal', (el) => !el.classList.contains('hidden')).catch(() => false);
check('弹窗打开', !!modalVisible);

// 3. 弹窗 header 文本
const header = await page.$eval('#dailyBriefModal h3', (el) => el.textContent.trim()).catch(() => '');
check('弹窗标题=每日速递', header.includes('每日速递'), `h3="${header}"`);
check('弹窗标题不含AI', !header.includes('AI'), `h3="${header}"`);

// 4. 历史列表加载(第一条最新条目)与版本徽标
await page.waitForSelector('.summary-history-list .db-item', { timeout: 20000 }).catch(() => {});
const firstBadge = await page.$eval('.summary-history-list .db-item .db-ver', (el) => el.textContent.trim()).catch(() => '');
check('最新条目版本徽标=规则版', firstBadge.includes('规则版'), `badge="${firstBadge}"`);
check('最新条目徽标非降级版', !firstBadge.includes('降级'), `badge="${firstBadge}"`);

// 5. 弹窗内全文不应出现「🤖 AI预测」硬编码标题(历史旧 AI 条目的徽标如"多角色"除外)
const bodyText = await page.$eval('#dailyBriefModal', (el) => el.textContent).catch(() => '');
check('弹窗无"每日AI预测"标题', !bodyText.includes('每日AI预测'), '');
check('弹窗无"AI预测命中率"', !bodyText.includes('AI预测命中率'), '');

// 6. 命中率统计标题应为「每日速递命中率」
const statsTitle = await page.$eval('.db-stats-title', (el) => el.textContent.trim()).catch(() => '');
check('命中率标题=每日速递命中率', statsTitle.includes('每日速递命中率'), `title="${statsTitle}"`);

// 7. 首页按钮 title 提示
const btnTitle = await page.$eval('.summary-ai-btn', (el) => el.getAttribute('title') || '').catch(() => '');
check('按钮title=每日速递', btnTitle.includes('每日速递'), `title="${btnTitle}"`);

// 8. 页面 JS 错误
check('无 JS 运行错误', errors.length === 0, errors.slice(0, 3).join(' | '));

await browser.close();

for (const r of results) {
  console.log(`${r.pass ? 'PASS' : 'FAIL'}  ${r.name}${r.extra ? '  → ' + r.extra : ''}`);
}
const failN = results.filter((r) => !r.pass).length;
console.log(`\n${results.length - failN}/${results.length} passed`);
process.exit(failN ? 1 : 0);
