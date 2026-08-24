// #97 批次C 诊断: 弱网下开弹窗, 抓预览链路每步状态
const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, userAgent: "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)", isMobile: true, hasTouch: true, deviceScaleFactor: 3 });
  const page = await ctx.newPage();
  page.on("console", m => { if (m.type() === "error" || m.type() === "warning") console.log("[console]", m.text().slice(0, 200)); });
  const reqs = [];
  page.on("request", r => { const u = r.url(); if (u.includes("lab_meta") || u.includes("lab_rating") || u.includes("trades.json")) reqs.push((u.includes("ss.fx8.store") ? "R2 " : "CF ") + u.split("/").pop().split("?")[0]); });
  await page.goto("http://127.0.0.1:8123/index.html#lab?sub=sigkelly", { waitUntil: "domcontentloaded" });
  await page.waitForSelector(".lab-sigkelly-card", { timeout: 30000 });
  // 拖慢整包
  await page.route("**/data/signal_kelly_trades.json*", async (r) => { await new Promise((s) => setTimeout(s, 6000)); await r.continue(); });
  await page.waitForTimeout(400);
  const ret = page.evaluate(() => {
    window.__pvDone = null;
    return _openSigKellyTradesModal("rating_high", "A", "y1").then(() => "modal-done");
  });
  // 2s 后抓弹窗内容(此时应处预览态或loading)
  await page.waitForTimeout(2500);
  const snap = await page.evaluate(() => ({
    overlayHtmlHead: (document.querySelector("#lab-sigkelly-trades-overlay .lab-sigkelly-modal") || {}).textContent?.slice(0, 150) || "NO-MODAL",
    hasTable: !!document.querySelector("#lab-sigkelly-trades-overlay .lab-sigkelly-trades-table"),
    noteText: (document.querySelector("#lab-sigkelly-trades-overlay .lab-custom-note") || {}).textContent?.slice(0, 80) || "-",
    stateReady: !!window.state ? undefined : undefined,
  }));
  console.log("SNAP@2.5s:", JSON.stringify(snap));
  await ret;
  await page.waitForTimeout(7000);
  const snap2 = await page.evaluate(() => ({
    hasColsBtn: !!document.querySelector(".lab-sigkelly-cols-btn"),
    noteText: (document.querySelector("#lab-sigkelly-trades-overlay .lab-custom-note") || {}).textContent?.slice(0, 60) || "-",
    rows: document.querySelectorAll("#lab-sigkelly-trades-overlay .lab-sigkelly-trades-table tbody tr").length,
  }));
  console.log("SNAP@end:", JSON.stringify(snap2));
  console.log("REQS:", JSON.stringify(reqs));
  await browser.close();
})().catch(e => { console.error("FATAL", e.message); process.exit(1); });
