// 内存泄漏量化探针(2026-08-23 P0③ 用户报「网页让浏览器内存占用异常」)
// 三场景 × performance.memory(JS heap) 采样, 每点先 CDP HeapProfiler.collectGarbage 强制 GC
// —— GC 后仍持续单调涨不回落 = 泄漏实锤(排除正常垃圾堆积干扰)。
//   S1 页面静置 5 分钟(基线, 10 点×30s)
//   S2 sim 回测弹窗开关 20 次(监听器/池缓存/DOM 重建)
//   S3 lab 7 模式连切 10 轮(重算大数组/桶缓存)
// 用法: node mem_probe.mjs <baseURL> --out /tmp/mem-before.json
import { chromium } from "playwright";
import { writeFileSync } from "fs";

const BASE = process.argv[2] || "http://localhost:8123";
const oi = process.argv.indexOf("--out");
const OUT = oi > 0 ? process.argv[oi + 1] : "/tmp/mem-probe.json";
const LAB_URL = BASE + "/index.html#lab?sub=sigkelly";
const HOME_URL = BASE + "/index.html";
const MODES7 = ["p9", "a9", "b9", "c9", "new14", "new18", "p8"];
const out = { base: BASE, scenes: {} };

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await ctx.newPage();
await page.addInitScript(() => { try { localStorage.clear(); } catch (e) {} });
const client = await ctx.newCDPSession(page);

async function gc() {
  try { await client.send("HeapProfiler.collectGarbage"); } catch (e) {}
  await page.waitForTimeout(300).catch(() => {});
}
async function heapMB() {
  try {
    const r = await Promise.race([
      page.evaluate(() => Math.round(performance.memory.usedJSHeapSize / 1048576 * 10) / 10),
      new Promise((res) => setTimeout(() => res(-1), 3000)),
    ]);
    return r;
  } catch (e) { return -1; }
}

// ── S1 静置 5 分钟 ──
{
  await page.goto(HOME_URL, { waitUntil: "domcontentloaded", timeout: 30000 }).catch(() => {});
  await page.waitForTimeout(6000);
  const pts = [];
  for (let i = 0; i < 10; i++) {
    await gc();
    pts.push({ t: i * 30, mb: await heapMB() });
    if (i < 9) await page.waitForTimeout(30000).catch(() => {});
  }
  out.scenes.S1_idle_5min = { points: pts };
}

// ── S2 sim 弹窗开关 20 次 ──
{
  const openR = await Promise.race([
    page.evaluate(() => { const b = document.querySelector(".sig-kbtn-sim"); if (b) { b.click(); return "ok"; } return "no-btn"; }),
    new Promise((res) => setTimeout(() => res("timeout"), 8000)),
  ]);
  await page.waitForTimeout(2500);
  const pts = [];
  for (let i = 1; i <= 20; i++) {
    // 开
    await Promise.race([
      page.evaluate(() => { const b = document.querySelector(".sig-kbtn-sim"); if (b && document.getElementById("simBacktestModal").classList.contains("hidden")) b.click(); return 1; }),
      new Promise((res) => setTimeout(res, 5000)),
    ]);
    await page.waitForTimeout(2200);
    // 关
    await Promise.race([
      page.evaluate(() => { const m = document.getElementById("simBacktestModal"); const c = m && (m.querySelector(".rule-modal-close")); if (c) c.click(); else if (m) m.classList.add("hidden"); return 1; }),
      new Promise((res) => setTimeout(res, 4000)),
    ]);
    await page.waitForTimeout(700);
    await gc();
    pts.push({ n: i, mb: await heapMB() });
  }
  out.scenes.S2_sim_toggle_20 = { openFirst: openR, points: pts };
}

// ── S3 lab 7 模式连切 10 轮 ──
{
  await page.goto("about:blank"); // 强制断开同文档: 首页→/#lab 只差 hash 会被当同文档导航, lab 页代码不跑(下拉永不出现)
  await page.waitForTimeout(500);
  await page.goto(LAB_URL, { waitUntil: "domcontentloaded", timeout: 30000 }).catch(() => {});
  // 等模式下拉出现(bar 渲染完成)
  let ready = false;
  for (let i = 0; i < 90; i++) {
    await page.waitForTimeout(1000);
    const r = await Promise.race([
      page.evaluate(() => !!document.getElementById("lab-kelly-fade-mode-sel")),
      new Promise((res) => setTimeout(() => res(false), 2500)),
    ]);
    if (r) { ready = true; break; }
  }
  const pts = [];
  if (ready) {
    await page.waitForTimeout(4000); // 等首轮重算稳定
    await gc();
    pts.push({ round: 0, mb: await heapMB() });
    for (let rd = 1; rd <= 10; rd++) {
      for (const m of MODES7) {
        await Promise.race([
          page.evaluate((mm) => {
            const s = document.getElementById("lab-kelly-fade-mode-sel");
            if (!s) return "no";
            s.value = mm;
            s.dispatchEvent(new Event("change", { bubbles: true }));
            return "ok";
          }, m),
          new Promise((res) => setTimeout(res, 4000)),
        ]);
        await page.waitForTimeout(1100);
      }
      await gc();
      pts.push({ round: rd, mb: await heapMB() });
    }
  }
  out.scenes.S3_lab_switch_10rounds = { selectReady: ready, points: pts };
}

await browser.close();
writeFileSync(OUT, JSON.stringify(out, null, 2));
console.log(JSON.stringify(out.scenes, null, 1));
