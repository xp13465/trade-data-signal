// codex-002 low 补验: cols-item / fee input 需交互后才在 DOM(列选择器点开/明细弹窗打开), 单独实测
const { chromium } = require("playwright");
(async () => {
  const out = {};
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true, serviceWorkers: "block" });
  const mp = await ctx.newPage();
  await mp.route("**/signal_kelly_trades_parts/**", (route) => route.abort());
  await mp.goto("http://localhost:8123/index.html#lab?sub=sigkelly", { waitUntil: "domcontentloaded" });
  await mp.waitForTimeout(6000);
  // 打开明细弹窗(bottom-sheet) → 点「显示列」展开选择器 → 实测 cols-item 高度
  await mp.evaluate(() => { const r = document.querySelector(".lab-sigkelly-mopen"); if (r) r.click(); });
  await mp.waitForTimeout(2500);
  out.colsBtnH = await mp.evaluate(() => { const b = document.querySelector(".lab-sigkelly-cols-btn"); if (!b) return null; return Math.round(b.getBoundingClientRect().height * 10) / 10; });
  if (out.colsBtnH != null) {
    await mp.evaluate(() => { const b = document.querySelector(".lab-sigkelly-cols-btn"); if (b) b.click(); });
    await mp.waitForTimeout(500);
    out.colsItemHeights = await mp.evaluate(() =>
      [...document.querySelectorAll(".lab-sigkelly-cols-pop .lab-sigkelly-cols-item")].slice(0, 5).map((el) => Math.round(el.getBoundingClientRect().height * 10) / 10));
    // fee input: 弹窗内筛选输入框
    out.modalFeeInputH = await mp.evaluate(() => {
      const i = document.querySelector(".lab-sigkelly-modal-filters .lab-input");
      return i ? Math.round(i.getBoundingClientRect().height * 10) / 10 : null;
    });
  }
  await ctx.close(); await browser.close();
  console.log(JSON.stringify(out));
})().catch((e) => { console.error("FAIL", e); process.exit(1); });
