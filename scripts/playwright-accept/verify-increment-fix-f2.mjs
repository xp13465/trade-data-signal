// F2 页面级验证(2026-09-09 review 复验修复后)
// 构造带 high 行的盘中产物(rating 列 2 行改 high), 验证:
//  s06p1·K1 → top-K 前剔 high(mid/low 递补) → banner '过滤后 N/5 笔' 且 N < 5(与主档 _simRenderOnce 同源剔除)
//  s06·K1  → 不剔(Δ=0 铁律) → banner N=5(全量)
// 对照组: modeId 缺失(fadeOff) → 无降亏标注(非 s06p1)且 nKept 不因 strip 减少
import { chromium } from "playwright";
import fs from "node:fs";

const BASE = "http://127.0.0.1:8124";
const out = [];
const results = [];
function log(...a) { const s = a.join(" "); out.push(s); console.log(s); }
function assert(name, cond, extra) {
  results.push({ name, pass: !!cond, extra: extra || "" });
  log((cond ? "PASS " : "FAIL ") + name + (cond ? "" : "  <- " + (extra || "")));
}

const browser = await chromium.launch();
async function scan(fadeMode, fadeOn, label) {
  const ctx = await browser.newContext();
  await ctx.addInitScript(([fm, on]) => {
    try {
      if (fm) localStorage.setItem("tds_sim_fade_mode", JSON.stringify({ v: { mode: fm }, ts: Date.now() }));
      else localStorage.removeItem("tds_sim_fade_mode");
      localStorage.setItem("tds_sim_fade", on ? "1" : "0");
      localStorage.setItem("onboarding_done", "1");
      localStorage.setItem("nt_intro_done", "1");
    } catch (e) {}
  }, [fadeMode, fadeOn]);
  // 构造 high 行: 读盘产物 → 前 2 行 rating 改 high
  await ctx.route(/\/data\/signal_kelly_trades_intraday\.json/, async (route) => {
    try {
      let body = JSON.parse(fs.readFileSync("/private/tmp/wt-increment/static-site/data/signal_kelly_trades_intraday.json", "utf8"));
      const d = new Date();
      const pad = (n) => (n < 10 ? "0" + n : "" + n);
      const todayS = "" + d.getFullYear() + pad(d.getMonth() + 1) + pad(d.getDate());
      body.intraday.next_open_date = todayS;
      const fi = body.fields.indexOf("rating");
      for (const qk in body.quadrants) {
        for (const m in body.quadrants[qk]) {
          const arr = body.quadrants[qk][m];
          for (let i = 0; i < arr.length; i++) arr[i][fi] = "high";
        }
      }
      await route.fulfill({ json: body, contentType: "application/json" });
    } catch (e) { await route.abort(); }
  });
  await ctx.route(/^https:\/\/ss\.fx8\.store\//, async (route) => {
    const u = route.request().url();
    const rel = u.replace("https://ss.fx8.store", "");
    try {
      const resp = await route.fetch({ url: BASE + rel });
      await route.fulfill({ response: resp });
    } catch (e) { await route.abort(); }
  });
  const page = await ctx.newPage();
  const pageErrors = [];
  page.on("pageerror", (e) => pageErrors.push(String(e)));
  await page.goto(BASE + "/index.html", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1500);
  try {
    const skip = await page.$(".onboarding-skip");
    if (skip) { await skip.click(); await page.waitForTimeout(400); }
  } catch (e) {}
  await page.waitForSelector(".sig-kbtn-sim", { timeout: 30000 });
  await page.click(".sig-kbtn-sim");
  await page.waitForSelector("#simBacktestModal:not(.hidden)", { timeout: 15000 });
  await page.waitForSelector("#kelly-intraday-view", { timeout: 15000 });
  await page.waitForTimeout(600);
  const selVal = await page.$eval("#sim-fade-mode-sel", (el) => el.value).catch(() => null);
  const bannerTxt = await page.$eval("#kelly-intraday-view .kelly-intraday-note", (el) => el.textContent).catch(() => null);
  const nRows = await page.$$eval("#kelly-intraday-view tbody tr", (trs) => trs.length).catch(() => -1);
  log("[" + label + "] sel=" + selVal + " rows=" + nRows + " pageErrors=" + pageErrors.length);
  if (bannerTxt) log("  " + bannerTxt.replace(/\s+/g, " "));
  await ctx.close();
  return { label, bannerTxt, nRows, pageErrors };
}

const A = await scan("s06p1", true, "s06p1·K1(剔 high)");
const B = await scan("s06", true, "s06·K1(不剔对照)");
const C = await scan(null, false, "fadeOff(无降亏对照)");

// F2 断言
function match(t, re) { return t ? re.test(t) : false; }
assert("s06p1 bekilt: 含 s06p1 降亏标注", match(A.bannerTxt, /s06p1\s*降亏/), A.bannerTxt || "");
assert("s06p1 bekilt: 过滤后 N/n 笔", match(A.bannerTxt, /过滤后\s*(\d+)\/5\s*笔/), A.bannerTxt || "");
const nA = match(A.bannerTxt, /过滤后\s*(\d+)\/5\s*笔/) ? parseInt(A.bannerTxt.match(/过滤后\s*(\d+)\/5\s*笔/)[1], 10) : 5;
const nB = match(B.bannerTxt, /过滤后\s*(\d+)\/5\s*笔/) ? parseInt(B.bannerTxt.match(/过滤后\s*(\d+)\/5\s*笔/)[1], 10) : 0;
assert("s06p1 strips high: nKept < 5", nA < 5, "nKept=" + nA);
assert("s06 não strip(Δ=0 铁律, s06 档不因 K1 剔 high)", nB > 0 && nA < nB, "A=" + nA + " B=" + nB);
assert("s06p1 nKept < s06 nKept(递补差异可见)", nA < nB, "A=" + nA + " B=" + nB);
assert("s06 不因 K1 剔 high(保留 s06 过滤后全部)", nB > 0, "s06 nKept=" + nB);
assert("fadeOff 无降亏标注", C.bannerTxt === null || !/\s降亏/.test(C.bannerTxt), C.bannerTxt || "");
assert("三场景均无 JS 错误", A.pageErrors.length + B.pageErrors.length + C.pageErrors.length === 0,
  [A.pageErrors, B.pageErrors, C.pageErrors].join(" || "));

await browser.close();

const fails = results.filter((r) => !r.pass);
log("\n==== 汇总 ====");
log("F2 页面级 " + results.length + " 项, FAIL " + fails.length + " 项");
if (fails.length) fails.forEach((f) => log("  FAIL " + f.name + " :: " + f.extra));
fs.writeFileSync("/tmp/f2-result.txt", out.join("\n"), "utf8");
process.exit(fails.length ? 1 : 0);