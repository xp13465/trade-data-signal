// codex-002 修复自验:
//   M: meta 返回 {groups:{}}(空清单) → 预览应走 catch 出红条(不再静默)
//   L: cols-item / mrow-detail summary / fee input 高度 ≥44
//   D: 桌面 hostHash 与基线对照(同数据源 fix 版 vs HEAD 版)
const { chromium } = require("playwright");
function hostHash(s) { let x = 5381; for (let i = 0; i < s.length; i++) x = ((x * 31) + s.charCodeAt(i)) | 0; return (x >>> 0).toString(16); }
(async () => {
  const out = {};
  const browser = await chromium.launch();

  // ---- D: 桌面 ----
  {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, serviceWorkers: "block" });
    const p = await ctx.newPage();
    p.on("pageerror", (e) => { out.D_pageError = String(e); });
    await p.goto("http://localhost:8123/index.html#lab?sub=sigkelly", { waitUntil: "domcontentloaded" });
    await p.waitForTimeout(6000);
    out.D_hostHash = hostHash(await p.evaluate(() => { const el = document.querySelector(".lab-sigkelly-host"); return el ? el.outerHTML : "NO_HOST"; }));
    // D 补充: 桌面 fee input 高度不受断点影响(应为 22px 基础值)
    out.D_feeInputH = await p.evaluate(() => { const i = document.querySelector(".lab-sigkelly-fee-custom .lab-input"); return i ? i.getBoundingClientRect().height : null; });
    await ctx.close();
  }

  // ---- M+L: 移动 ----
  {
    const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true, serviceWorkers: "block" });
    await ctx.addInitScript(() => { try { localStorage.removeItem("lab_sigkelly_params_open"); } catch (e) {} });
    const mp = await ctx.newPage();
    mp.on("pageerror", (e) => { out.M_pageError = String(e); });
    // M 场景: meta 正常返回但 groups 为空对象(codex 点名的「空 groups」场景)
    await mp.route("**/signal_kelly_trades_parts/lab_meta.json*", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ generated_at: "2026-08-25 09:00", fields: ["a"], period_cutoffs: {}, groups: {} }) }));
    await mp.route("**/data/signal_kelly_trades.json*", async (route) => { await new Promise((r) => setTimeout(r, 5000)); route.continue(); });
    await mp.goto("http://localhost:8123/index.html#lab?sub=sigkelly", { waitUntil: "domcontentloaded" });
    await mp.waitForTimeout(6000);
    // L: 触控目标实测
    out.L_touch = await mp.evaluate(() => {
      const h = (sel) => { const el = document.querySelector(sel); if (!el) return null; const r = el.getBoundingClientRect(); return Math.round(r.height * 10) / 10; };
      return { summary: h(".lab-sigkelly-mrow-detail summary"), colsItem: h(".lab-sigkelly-cols-item"), feeInput: h(".lab-sigkelly-fee-custom .lab-input") };
    });
    // M: 打开明细弹窗 → 空 groups 应出红条
    await mp.evaluate(() => { const r = document.querySelector(".lab-sigkelly-mopen"); if (r) r.click(); });
    await mp.waitForTimeout(2000);
    out.M_emptyGroups = await mp.evaluate(() => {
      const ov = document.querySelector("#lab-sigkelly-trades-overlay");
      if (!ov || ov.style.display === "none") return "OVERLAY_CLOSED";
      const note = [...ov.querySelectorAll(".lab-custom-note")].find((el) => el.textContent.includes("快速预览不可用"));
      return { failNote: !!note, text: note ? note.textContent.slice(0, 26) : null, loading: !!ov.querySelector(".lab-sigkelly-modal-loading") };
    });
    await ctx.close();
  }
  await browser.close();
  console.log(JSON.stringify(out, null, 1));
})().catch((e) => { console.error("FAIL", e); process.exit(1); });
