// CDP 精确 heap 曲线(四问③): 修复前版带 new14 记忆启动 lab, 用 Performance.getMetrics
// (浏览器进程侧, 不受主线程饿死影响)每秒采 JSHeapUsedSize + DOMNodes + JSEventListeners。
import { chromium } from "playwright";
import { writeFileSync } from "fs";

const BASE = process.argv[2] || "http://localhost:8124";
const OUT = process.argv[3] || "/tmp/heap-cdp.json";
const MAXS = parseInt(process.argv[4] || "30", 10);
const LAB_URL = BASE.replace(/\/+$/, "") + "/#lab?sub=sigkelly";

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await ctx.newPage();
await page.addInitScript(() => { try { localStorage.setItem("tds_kelly_fade_mode", JSON.stringify({ mode: "new14" })); } catch (e) {} });
const client = await ctx.newCDPSession(page);
await client.send("Performance.enable");
await page.goto(LAB_URL, { waitUntil: "domcontentloaded", timeout: 30000 }).catch(() => {});

const pts = [];
for (let i = 0; i < MAXS; i++) {
  try {
    const m = await client.send("Performance.getMetrics");
    const get = (n) => { const x = m.metrics.find((e) => e.name === n); return x ? x.value : -1; };
    pts.push({
      t_s: i + 1,
      heapMB: Math.round(get("JSHeapUsedSize") / 1048576 * 10) / 10,
      domNodes: get("Nodes"),
      jsListeners: get("JSEventListeners"),
      documents: get("Documents"),
    });
  } catch (e) { pts.push({ t_s: i + 1, err: String(e).slice(0, 50) }); }
  await page.waitForTimeout(1000);
}
await browser.close();
writeFileSync(OUT, JSON.stringify({ base: BASE, points: pts }, null, 1));
// 摘要打印
const heaps = pts.map((p) => p.heapMB).filter((x) => x > 0);
console.log("首=" + heaps[0] + "MB 末=" + heaps[heaps.length - 1] + "MB 峰=" + Math.max(...heaps) + "MB 点数=" + heaps.length);
console.log("序列MB: " + heaps.join(","));
const last = pts[pts.length - 1];
console.log("末点: domNodes=" + last.domNodes + " jsListeners=" + last.jsListeners + " documents=" + last.documents);
