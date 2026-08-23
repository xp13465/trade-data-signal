// 精确复现路径探针(主控转用户路径 2026-08-23): 首页 sim 弹窗切 NEW14 → dump 全部 localStorage
// 验证: sim 的选择是否经由任何键(tds_kelly_filters / tds_kelly_fade_mode / 其他)污染 lab 启动态。
import { chromium } from "playwright";

const BASE = process.argv[2] || "http://localhost:8123";
const HOME_URL = BASE.replace(/\/+$/, "") + "/";
const out = {};

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const p = await ctx.newPage();
await p.addInitScript(() => { try { localStorage.clear(); } catch (e) {} });
await p.goto(HOME_URL, { waitUntil: "domcontentloaded", timeout: 30000 }).catch(() => {});
await p.waitForTimeout(3000);

// 打开 sim 弹窗
const openR = await Promise.race([
  p.evaluate(() => { const b = document.querySelector(".sig-kbtn-sim"); if (!b) return "no-btn"; b.click(); return "clicked"; }),
  new Promise((res) => setTimeout(() => res("timeout"), 10000)),
]);
await p.waitForTimeout(2500);

// sim 切 new14
const setR = await Promise.race([
  p.evaluate(() => {
    const s = document.getElementById("sim-fade-mode-sel");
    if (!s) return "no-sim-sel";
    s.value = "new14";
    s.dispatchEvent(new Event("change", { bubbles: true }));
    return "set-new14";
  }),
  new Promise((res) => setTimeout(() => res("timeout"), 8000)),
]);
await p.waitForTimeout(2000);
out.step1_open_set = { openR, setR };

// dump 全部 localStorage
out.ls_after_sim_new14 = await Promise.race([
  p.evaluate(() => {
    const o = {};
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (/tds_|kelly|fade/i.test(k)) o[k] = (localStorage.getItem(k) || "").slice(0, 400);
    }
    return o;
  }),
  new Promise((res) => setTimeout(() => res("__T__"), 5000)),
]);

// 关弹窗 → 再 dump(关弹窗动作是否也写)
await Promise.race([
  p.evaluate(() => { const m = document.getElementById("simBacktestModal"); if (m) { m.classList.add("hidden"); return 1; } return 0; }),
  new Promise((res) => setTimeout(res, 4000)),
]);
out.ls_after_close = await Promise.race([
  p.evaluate(() => {
    const o = {};
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (/tds_|kelly|fade/i.test(k)) o[k] = (localStorage.getItem(k) || "").slice(0, 400);
    }
    return o;
  }),
  new Promise((res) => setTimeout(() => res("__T__"), 5000)),
]);

// 直接导航到 lab 页(模拟"切到 lab 页"), 读 lab 启动后的实际生效 filters + 模式下拉值
await p.goto("about:blank");
await p.goto(BASE.replace(/\/+$/, "") + "/#lab?sub=sigkelly", { waitUntil: "domcontentloaded", timeout: 30000 }).catch(() => {});
let labState = "not-ready";
for (let i = 0; i < 60; i++) {
  await p.waitForTimeout(1000);
  const r = await Promise.race([
    p.evaluate(() => {
      const sel = document.getElementById("lab-kelly-fade-mode-sel");
      if (!sel) return "wait";
      const on = [];
      document.querySelectorAll(".lab-sigkelly-toggle-cb").forEach((cb) => { if (cb.checked && cb.dataset && cb.dataset.k) on.push(cb.dataset.k); });
      return JSON.stringify({ modeSel: sel.value, checkedCount: on.length, onKeys: on.slice(0, 30) });
    }),
    new Promise((res) => setTimeout(() => res("__T__"), 2500)),
  ]);
  if (r !== "wait" && r !== "__T__") { labState = r; break; }
}
out.lab_after_nav = labState;

await browser.close();
console.log(JSON.stringify(out, null, 2));
