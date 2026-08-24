const { chromium } = require("playwright");
(async () => {
  const out = {};
  const browser = await chromium.launch();
  const mctx = await browser.newContext({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true, serviceWorkers: "block" });
  await mctx.addInitScript(() => { try { localStorage.removeItem("lab_sigkelly_params_open"); } catch (e) {} });
  const mp = await mctx.newPage();
  mp.on("pageerror", (e) => { out.pageError = String(e); });
  await mp.route("**/signal_kelly_trades_parts/lab_meta.json*", (route) => route.abort());
  await mp.route("**/signal_kelly_trades.json*", async (route) => { await new Promise((r) => setTimeout(r, 5000)); route.continue(); });
  await mp.goto("http://localhost:8123/index.html#lab?sub=sigkelly", { waitUntil: "domcontentloaded" });
  await mp.waitForTimeout(6000);
  await mp.evaluate(() => { const r = document.querySelector(".lab-sigkelly-mopen"); if (r) r.click(); });
  await mp.waitForTimeout(1500);
  out.t15_failNote = await mp.evaluate(() => !![...document.querySelectorAll("#lab-sigkelly-trades-overlay .lab-custom-note")].find((el) => el.textContent.includes("快速预览不可用")));
  await mp.waitForTimeout(9000);
  out.t105 = await mp.evaluate(() => {
    const ov = document.querySelector("#lab-sigkelly-trades-overlay");
    return {
      table: !!(ov && ov.querySelector(".lab-sigkelly-trades-table")),
      staleNote: !!([...(ov ? ov.querySelectorAll(".lab-custom-note") : [])].find((el) => el.textContent.includes("快速预览不可用"))),
    };
  });
  await mctx.close(); await browser.close();
  console.log(JSON.stringify(out));
})().catch((e) => { console.error("FAIL", e); process.exit(1); });
