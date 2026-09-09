// F3 首页 sim 弹窗首开联动验证(2026-09-09 review 复验修复后)
// 断言: 首开弹窗顶部增量 banner 即按预置降亏模式(s06)过滤, 显示「s06降亏 ... 过滤后 N/5 笔」,
// 而非修复前的「提前入账 5 笔」全量格式(modeId=null 未挂载)。
// 资源重定向: ss.fx8.store → 本地 8124(线上资源, route.fetch+route.fulfill, 协议须一致)。
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
try {
  const ctx = await browser.newContext();
  // 预置降亏模式记忆: tds_sim_fade_mode = {v:{mode:"s06"}, ts:now}(TTL 工具格式, common.js L930)
  await ctx.addInitScript(() => {
    try {
      localStorage.setItem("tds_sim_fade_mode", JSON.stringify({ v: { mode: "s06" }, ts: Date.now() }));
      localStorage.setItem("tds_sim_fade", "1");
      localStorage.setItem("onboarding_done", "1");
      localStorage.setItem("nt_intro_done", "1");
    } catch (e) {}
  });
  // 拦截产物: 把盘中日改为浏览器"今日"(产物实际 next_open_date=20260908 已过期 → 按活动判定不渲染,
  // 复现不了首开联动; 改写为今日可验证 F3 修复后的首开联动逻辑本身)。改写只影响本测试进程, 不动磁盘产物。
  await ctx.route(/\/data\/signal_kelly_trades_intraday\.json/, async (route) => {
    try {
      let body = JSON.parse(fs.readFileSync("/private/tmp/wt-increment/static-site/data/signal_kelly_trades_intraday.json", "utf8"));
      const d = new Date();
      const pad = (n) => (n < 10 ? "0" + n : "" + n);
      const todayS = "" + d.getFullYear() + pad(d.getMonth() + 1) + pad(d.getDate());
      body.generated_at = new Date().toISOString();
      body.intraday.next_open_date = todayS;
      await route.fulfill({ json: body, contentType: "application/json" });
    } catch (e) {
      await route.abort();
    }
  });
  await ctx.route(/^https:\/\/ss\.fx8\.store\//, async (route) => {
    const u = route.request().url();
    const rel = u.replace("https://ss.fx8.store", "");
    const local = BASE + rel;
    try {
      const resp = await route.fetch({ url: local });
      await route.fulfill({ response: resp });
    } catch (e) {
      await route.abort();
    }
  });
  const page = await ctx.newPage();
  const pageErrors = [];
  page.on("pageerror", (err) => pageErrors.push(String(err)));

  await page.goto(BASE + "/index.html", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1500);
  // 关 onboarding
  try {
    const skip = await page.$(".onboarding-skip");
    if (skip) { await skip.click(); await page.waitForTimeout(400); }
  } catch (e) {}

  // 等 AI 建议区渲染出 sim 回测按钮
  await page.waitForSelector(".sig-kbtn-sim", { timeout: 30000 });
  log("OK: .sig-kbtn-sim 已渲染");
  // 打开 sim 弹窗
  await page.click(".sig-kbtn-sim");
  await page.waitForSelector("#simBacktestModal:not(.hidden)", { timeout: 15000 });
  log("OK: sim 弹窗已打开");

  // 等增量视图渲染(anchor=.rule-modal-header 后插 id=kelly-intraday-view)
  await page.waitForSelector("#kelly-intraday-view", { timeout: 15000 });
  await page.waitForTimeout(600);

  // 读下拉实际值(证明挂载后首调读到非 null)
  const selVal = await page.$eval("#sim-fade-mode-sel", (el) => el.value).catch(() => null);
  log("sim-fade-mode-sel value = " + selVal);

  const bannerTxt = await page.$eval("#kelly-intraday-view .kelly-intraday-note", (el) => el.textContent).catch(() => null);
  log("BANNER: " + (bannerTxt || "").replace(/\s+/g, " "));

  // F3 核心断言: 首开 banner 含「s06降亏」且为「过滤后 N/5 笔」格式, 非「提前入账 5 笔」
  assert("首开增量按 s06 降亏过滤(含 's06' 降亏标注)", bannerTxt !== null && /s06\s*降亏|s06.*降亏/.test(bannerTxt), bannerTxt || "");
  assert("首开 banner 为过滤后格式(非提前入账)", bannerTxt !== null && /过滤后\s*\d+\/\d+\s*笔/.test(bannerTxt), bannerTxt || "");
  assert("首开 banner 不含全量格式(提前入账)", bannerTxt === null || !/提前入账\s*\d+\s*笔/.test(bannerTxt), bannerTxt || "");
  // 控件已挂载(值非空)= _bindSimBacktestControls 先于首调已执行
  assert("降亏下拉已挂载(selVal 非空)", !!selVal, String(selVal));
  assert("无页面 ReferenceError/JS 错误", pageErrors.length === 0, pageErrors.join(" || "));

  // 反向对照: 切到无记忆(清 tds_sim_fade_mode)再开 → 默认 new14 也应为过滤后(非提前入账)
  await page.evaluate(() => { try { localStorage.removeItem("tds_sim_fade_mode"); } catch (e) {} });
  await page.click("#simBacktestModal .rule-modal-close");
  await page.waitForTimeout(300);
  await page.click(".sig-kbtn-sim");
  await page.waitForSelector("#kelly-intraday-view", { timeout: 15000 });
  await page.waitForTimeout(500);
  const bannerTxt2 = await page.$eval("#kelly-intraday-view .kelly-intraday-note", (el) => el.textContent).catch(() => null);
  log("BANNER2(无记忆): " + (bannerTxt2 || "").replace(/\s+/g, " "));
  assert("无记忆场景同样为过滤后格式(默认档联动)", bannerTxt2 !== null && /过滤后\s*\d+\/\d+\s*笔/.test(bannerTxt2), bannerTxt2 || "");
} finally {
  await browser.close();
}

// 汇总
const fails = results.filter((r) => !r.pass);
log("\n==== 汇总 ====");
log("F3 断言 " + results.length + " 项, FAIL " + fails.length + " 项");
if (fails.length) { fails.forEach((f) => log("  FAIL " + f.name + " :: " + f.extra)); }
fs.writeFileSync("/tmp/f3-result.txt", out.join("\n"), "utf8");
process.exit(fails.length ? 1 : 0);
