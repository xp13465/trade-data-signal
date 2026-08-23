// 内存暴涨曲线探针(四问③): 在【修复前】版本上复现 R1(带 new14 记忆启动 lab),
// 每 500ms 采样 JS heap + DOM 节点数 + 卡片数, 拿暴涨速率与构成证据。
// 用法: node probe_heap_explosion.mjs <baseURL> <out.json> [maxSeconds]
import { chromium } from "playwright";
import { writeFileSync } from "fs";

const BASE = process.argv[2] || "http://localhost:8124";
const OUT = process.argv[3] || "/tmp/heap-explosion.json";
const MAXS = parseInt(process.argv[4] || "25", 10);
const LAB_URL = BASE.replace(/\/+$/, "") + "/#lab?sub=sigkelly";

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await ctx.newPage();
await page.addInitScript(() => { try { localStorage.setItem("tds_kelly_fade_mode", JSON.stringify({ mode: "new14" })); } catch (e) {} });
await page.goto(LAB_URL, { waitUntil: "domcontentloaded", timeout: 30000 }).catch(() => {});
// 先等首渲完成(trades 64MB parse+首渲, 最多 30s), 再采暴涨曲线
for (let i = 0; i < 60; i++) {
  await page.waitForTimeout(500);
  const ok = await Promise.race([
    page.evaluate(() => document.querySelectorAll(".sig-kelly-card").length > 0 || !!document.querySelector(".lab-sigkelly-toggle-cb")),
    new Promise((res) => setTimeout(() => res(false), 1500)),
  ]);
  if (ok) break;
}

const pts = [];
for (let i = 0; i < MAXS * 2; i++) {
  const r = await Promise.race([
    page.evaluate(() => ({
      t: performance.now(),
      mb: Math.round(performance.memory.usedJSHeapSize / 1048576),
      domNodes: document.getElementsByTagName("*").length,
      cards: document.querySelectorAll(".sig-kelly-card").length,
      toggles: document.querySelectorAll(".lab-sigkelly-toggle-cb").length,
    })),
    new Promise((res) => setTimeout(() => res(null), 1500)),
  ]);
  if (!r) { pts.push({ frozen: true, t_s: Math.round(i * 0.5 * 10) / 10 }); break; } // 主线程饿死=evaluate 不返回
  pts.push(r);
  await page.waitForTimeout(400);
}
await browser.close();
writeFileSync(OUT, JSON.stringify({ base: BASE, points: pts }, null, 1));
console.log(JSON.stringify(pts.slice(0, 6), null, 0));
console.log("...total points:", pts.length, " last:", JSON.stringify(pts[pts.length - 1]));
