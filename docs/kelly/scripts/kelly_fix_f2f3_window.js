// F2/F3 自验 v3: B 改断言 params-open class; C 打 overlay 实况
const { chromium } = require("playwright");
(async () => {
  const out = {};
  const browser = await chromium.launch();
  const mctx = await browser.newContext({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true, serviceWorkers: "block" });
  await mctx.addInitScript(() => { try { localStorage.removeItem("lab_sigkelly_params_open"); } catch (e) {} });
  const mp = await mctx.newPage();
  mp.on("pageerror", (e) => { out.pageError = String(e); });
  mp.on("console", (m) => { if (m.type() === "error") out.consoleErr = (out.consoleErr || []).concat(m.text().slice(0, 120)); });
  await mp.route("**/signal_kelly_trades_parts/lab_meta.json*", (route) => route.abort());
  await mp.route("**/signal_kelly_trades.json*", async (route) => { await new Promise((r) => setTimeout(r, 8000)); route.continue(); });
  await mp.goto("http://localhost:8123/index.html#lab?sub=sigkelly", { waitUntil: "domcontentloaded" });
  await mp.waitForTimeout(6000);
  out.B_params = await mp.evaluate(() => {
    const t = document.getElementById("lab-kelly-params-toggle");
    const openBody = document.querySelector(".lab-sigkelly-params-open");
    return { toggleText: t ? t.textContent : "NO_TOGGLE", hasOpenCls: !!openBody };
  });
  out.clickProbe = await mp.evaluate(() => {
    const rows = [...document.querySelectorAll(".lab-sigkelly-mopen")];
    return { count: rows.length, firstQuad: rows[0] ? rows[0].getAttribute("data-quad") : null };
  });
  await mp.evaluate(() => { const r = document.querySelector(".lab-sigkelly-mopen"); if (r) r.click(); });
  for (const t of [1500, 3000]) {
    await mp.waitForTimeout(t === 1500 ? 1500 : 1500);
    out[`t${t / 1000}s`] = await mp.evaluate(() => {
      const ov = document.querySelector("#lab-sigkelly-trades-overlay");
      if (!ov) return "NO_OVERLAY";
      if (ov.style.display === "none" || !ov.style.display) return { display: ov.style.display || "(empty)" };
      const note = [...ov.querySelectorAll(".lab-custom-note")].find((el) => el.textContent.includes("快速预览不可用"));
      return {
        display: ov.style.display,
        htmlHead: ov.querySelector(".lab-sigkelly-modal") ? ov.querySelector(".lab-sigkelly-modal").innerHTML.slice(0, 160) : "NO_MODAL",
        loading: !!ov.querySelector(".lab-sigkelly-modal-loading"),
        failNote: !!note,
      };
    });
  }
  await mctx.close();
  await browser.close();
  console.log(JSON.stringify(out, null, 1));
})().catch((e) => { console.error("SCRIPT_FAIL", e); process.exit(1); });
