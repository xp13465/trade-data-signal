// Bug A/B 复现探针 v2(2026-08-23 P0 双 bug)
// Bug A: lab 模式下拉卡死 —— 假设=renderSigKellyLab 特征就绪补渲 .then 无跃迁守卫 → 无限自递归渲染风暴。
//        R1=带 tds_kelly_fade_mode={mode:p9} 记忆刷新; R2=冷启动特征 JSON 在途时切 p9。
//        判定=PerformanceObserver longtask 总量/次数(渲染风暴=连绵 longtask)+Node 侧冻结探针。
// Bug B: C=sim 切 p9 → 关闭重开 sim 读值 + lab 键; D=lab 切 new14 → 开 sim 读值。
// 用法: node repro_fade_bugs.mjs <baseURL> [--feat-delay-ms N]
import { chromium } from "playwright";
import { writeFileSync } from "fs";

const BASE = process.argv[2] || "http://localhost:8123";
const tag = BASE.includes("localhost") ? "local" : "live";
const fdi = process.argv.indexOf("--feat-delay-ms");
const featDelay = fdi > 0 ? parseInt(process.argv[fdi + 1], 10) : 0;
const LAB_URL = BASE.replace(/\/+$/, "") + "/#lab?sub=sigkelly"; // 线上 ss.fx8.store /index.html 会 307 到根且丢 hash → 统一根路径+hash
const HOME_URL = BASE.replace(/\/+$/, "") + "/";
const out = { base: BASE, featDelay, scenarios: {} };

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
if (featDelay > 0) {
  await ctx.route(/kelly_loss_features\.json/, async (route) => {
    await new Promise((r) => setTimeout(r, featDelay));
    return route.continue();
  });
}

// longtask 采集注入(先于业务脚本)
const LT_INIT = () => {
  window.__lt = [];
  try {
    new PerformanceObserver((l) => {
      for (const e of l.getEntries()) window.__lt.push({ s: Math.round(e.startTime), d: Math.round(e.duration) });
    }).observe({ entryTypes: ["longtask"] });
  } catch (e) {}
};
const ltSummary = (arr) => ({
  count: arr.length,
  totalMs: arr.reduce((m, e) => m + e.d, 0),
  maxMs: arr.reduce((m, e) => Math.max(m, e.d), 0),
  over200: arr.filter((e) => e.d > 200).length,
});
async function ltTake(p) {
  try { return await Promise.race([p.evaluate(() => { const a = window.__lt || []; window.__lt = []; return a; }), new Promise((r) => setTimeout(() => r([]), 2000))]); }
  catch (e) { return []; }
}
// Node 侧冻结探针
async function probeFrozen(p, ms = 1200) {
  const t0 = Date.now();
  let done = false;
  const timer = setTimeout(() => { done = true; }, ms);
  try {
    const r = await Promise.race([
      p.evaluate(() => ({ cards: document.querySelectorAll(".sig-kelly-card").length })),
      new Promise((res) => { const iv = setInterval(() => { if (done) { clearInterval(iv); res(null); } }, 50); }),
    ]);
    clearTimeout(timer);
    return { frozen: !r, ms: Date.now() - t0 };
  } catch (e) { clearTimeout(timer); return { frozen: true, ms: Date.now() - t0, err: String(e).slice(0, 60) }; }
}
async function evalT(p, fn, arg, ms = 6000) {
  return await Promise.race([p.evaluate(fn, arg), new Promise((res) => setTimeout(() => res("__TIMEOUT__"), ms))]);
}

// ── R1: 带 p9 记忆刷新 lab 页 ──
{
  const p = await ctx.newPage();
  await p.addInitScript(LT_INIT);
  await p.addInitScript(() => { try { localStorage.setItem("tds_kelly_fade_mode", JSON.stringify({ mode: "new14" })); } catch (e) {} });
  await p.goto(LAB_URL, { waitUntil: "domcontentloaded", timeout: 30000 }).catch(() => {});
  const probes = [];
  const lts = [];
  for (let i = 0; i < 14; i++) { await p.waitForTimeout(2000).catch(() => {}); probes.push(await probeFrozen(p)); lts.push(...(await ltTake(p))); }
  out.scenarios.R1_memory_new14_refresh = { probes: probes.map((x) => (x.frozen ? "F" : ".")) .join(""), lt: ltSummary(lts) };
  await p.close().catch(() => {});
}

// ── R2: 冷启动(p8)特征 JSON 在途时切 p9 ──
{
  const p = await ctx.newPage();
  await p.addInitScript(LT_INIT);
  await p.addInitScript(() => { try { localStorage.clear(); } catch (e) {} });
  await p.goto(LAB_URL, { waitUntil: "domcontentloaded", timeout: 30000 }).catch(() => {});
  // 轮询等模式下拉出现(bar 渲染后才有), 出现立即切 p9(此时特征 JSON 仍在延迟窗口=竞态复现)
  let clickR = "sel-never-appeared";
  for (let i = 0; i < 60; i++) {
    await p.waitForTimeout(500);
    const r = await evalT(p, () => {
      const s = document.getElementById("lab-kelly-fade-mode-sel");
      if (!s) return "wait";
      s.value = "new14";
      s.dispatchEvent(new Event("change", { bubbles: true }));
      return "switched";
    }, null, 2500);
    if (r === "switched") { clickR = "switched@t=" + (i * 0.5).toFixed(1) + "s"; break; }
  }
  const probes = [];
  const lts = [];
  for (let i = 0; i < 14; i++) { await p.waitForTimeout(2000).catch(() => {}); probes.push(await probeFrozen(p)); lts.push(...(await ltTake(p))); }
  out.scenarios.R2_cold_switch_p9 = { clickR, probes: probes.map((x) => (x.frozen ? "F" : ".")).join(""), lt: ltSummary(lts) };
  await p.close().catch(() => {});
}

// ── C(Bug B): sim 切 p9 → 关闭重开 sim 读值 + lab 键 ──
{
  const p = await ctx.newPage();
  await p.addInitScript(() => { try { localStorage.clear(); } catch (e) {} });
  await p.goto(HOME_URL, { waitUntil: "domcontentloaded", timeout: 30000 }).catch(() => {});
  await p.waitForTimeout(2500);
  const openR = await evalT(p, () => { const b = document.querySelector(".sig-kbtn-sim"); if (!b) return "no-btn"; b.click(); return "clicked"; }, null, 8000);
  await p.waitForTimeout(1500);
  const setR = await evalT(p, () => {
    const s = document.getElementById("sim-fade-mode-sel");
    if (!s) return "no-sim-sel";
    s.value = "p9";
    s.dispatchEvent(new Event("change", { bubbles: true }));
    return "sim-set-p9";
  }, null, 10000);
  await p.waitForTimeout(1000);
  const lsMid = await evalT(p, () => localStorage.getItem("tds_kelly_fade_mode"), null, 3000);
  // 关闭弹窗(点遮罩/关闭按钮), 重开读值
  await evalT(p, () => {
    const m = document.getElementById("simBacktestModal");
    const c = m && (m.querySelector(".sim-close") || m.querySelector("[data-close]") || m.querySelector(".modal-close"));
    if (c) { c.click(); return "closed-btn"; }
    if (m) { m.classList.add("hidden"); return "closed-force"; }
    return "no-modal";
  }, null, 4000);
  await p.waitForTimeout(600);
  await evalT(p, () => { const b = document.querySelector(".sig-kbtn-sim"); if (b) b.click(); return "reopen"; }, null, 6000);
  await p.waitForTimeout(1500);
  const simValReopen = await evalT(p, () => (document.getElementById("sim-fade-mode-sel") || {}).value || null, null, 4000);
  out.scenarios.C_sim_p9_close_reopen = { openR, setR, lsMid, simValReopen };
  await p.close().catch(() => {});
}

// ── D(Bug B): lab 切 new14 → 开 sim 读值(反向独立性) ──
{
  const p = await ctx.newPage();
  await p.addInitScript(() => { try { localStorage.clear(); } catch (e) {} });
  await p.goto(LAB_URL, { waitUntil: "domcontentloaded", timeout: 30000 }).catch(() => {});
  let switched = "sel-never-appeared";
  for (let i = 0; i < 60; i++) {
    await p.waitForTimeout(500);
    switched = await evalT(p, () => {
      const s = document.getElementById("lab-kelly-fade-mode-sel");
      if (!s) return "wait";
      s.value = "new14";
      s.dispatchEvent(new Event("change", { bubbles: true }));
      return "lab-set-new14";
    }, null, 2500);
    if (switched === "lab-set-new14") break;
  }
  await p.waitForTimeout(1500);
  const lsLab = await evalT(p, () => localStorage.getItem("tds_kelly_fade_mode"), null, 3000);
  await p.goto(HOME_URL, { waitUntil: "domcontentloaded", timeout: 30000 }).catch(() => {});
  await p.waitForTimeout(2500);
  await evalT(p, () => { const b = document.querySelector(".sig-kbtn-sim"); if (b) b.click(); return "open"; }, null, 6000);
  await p.waitForTimeout(1500);
  const simVal = await evalT(p, () => (document.getElementById("sim-fade-mode-sel") || {}).value || null, null, 4000);
  out.scenarios.D_lab_new14_sim_open = { switched, lsLab, simValOnOpen: simVal };
  await p.close().catch(() => {});
}

await browser.close();
writeFileSync("/tmp/bp-repro-" + tag + ".json", JSON.stringify(out, null, 2));
console.log(JSON.stringify(out.scenarios, null, 1));
