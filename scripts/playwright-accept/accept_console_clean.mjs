#!/usr/bin/env node
// console 洁净度验收：断言无 CSP 违规、无 JS 崩溃（让真告警浮出来）
// 用法: BASE_URL=https://ss.fx8.store node scripts/playwright-accept/accept_console_clean.mjs
import { createRequire } from "module";
const require = createRequire("/Users/linhuichen/code/trade/scripts/playwright-accept/");
const { chromium } = require("playwright");
const BASE = process.env.BASE_URL || "https://ss.fx8.store";
let pass = 0, fail = 0;
const ok = (n, c, d="") => { c ? pass++ : fail++; console.log(`${c?"PASS":"FAIL"}  ${n}${d?`  [${d}]`:""}`); };

async function run(width, isMobile, tag) {
  const ctx = await (await chromium.launch({ headless: true })).newContext({ viewport:{width,height:844}, isMobile, hasTouch:isMobile });
  const page = await ctx.newPage();
  const csp = [], errors = [], pageerrors = [];
  page.on("console", m => {
    const t = m.text();
    if (/Content Security Policy|violates the following/i.test(t)) csp.push(t.slice(0,160));
    else if (m.type() === "error") errors.push(t.slice(0,160));
  });
  page.on("pageerror", e => pageerrors.push(String(e).slice(0,160)));
  for (const tab of ["#overview","#market/a-stock","#lab?sub=sigkelly"]) {
    try { await page.goto(BASE+"/"+tab, { waitUntil:"domcontentloaded", timeout:60000 }); } catch(e){ errors.push("GOTO_FAIL "+String(e).slice(0,80)); }
    await page.waitForTimeout(5000);
  }
  console.log(`\n[${tag} ${width}] CSP违规=${csp.length} console.error=${errors.length} pageerror=${pageerrors.length}`);
  if (errors.length) console.log("  errors:", JSON.stringify([...new Set(errors)].slice(0,5)));
  if (csp.length) console.log("  csp样例:", csp[0]);
  ok(`${tag} 无 CSP 违规`, csp.length === 0, `n=${csp.length}`);
  ok(`${tag} 无 JS 崩溃(pageerror)`, pageerrors.length === 0, `n=${pageerrors.length}`);
  await ctx.close();
}
await run(390, true, "mobile");
await run(1280, false, "desktop");
console.log(`\n${fail===0?"✅ console 洁净":"❌ 有告警"}: pass=${pass} fail=${fail}`);
process.exit(fail===0?0:1);
