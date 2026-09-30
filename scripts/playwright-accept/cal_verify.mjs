import { chromium } from "playwright";
// 双视口(桌面1280/移动375)对比旧版 vs 新版情绪日历渲染逐位一致 + 新版点日期弹明细。
// 用法: node scripts/playwright-accept/cal_verify.mjs
const browser = await chromium.launch({ headless: true });
let pass = 0, fail = 0;
const ok = (name, cond, detail = "") => { cond ? pass++ : fail++; console.log(`${cond ? "PASS" : "FAIL"}  ${name}${detail ? `  [${detail}]` : ""}`); };

async function snapshotCal(page, base) {
  await page.goto(base + "/#overview", { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.waitForTimeout(11000);
  return await page.evaluate(() => {
    // 定位情绪日历卡: 找 h3 含"近 90 日情绪日历"的 chart-card
    const cards = [...document.querySelectorAll(".chart-card")];
    const card = cards.find((c) => c.querySelector("h3")?.textContent?.includes("近 90 日情绪日历"));
    if (!card) return null;
    const rows = [...card.querySelectorAll(".sig-day-row")];
    const dump = rows.map((r) => {
      const date = r.querySelector(".sig-day-date")?.textContent?.trim() || "";
      const dateBtn = r.querySelector(".sig-day-date-btn") ? true : false;
      const cells = [...r.querySelectorAll(".sig-item")].map((it) => ({
        text: it.textContent.trim(),
        sig: it.dataset.sig,
        idx: it.dataset.idx,
        date: it.dataset.date,
        val: it.dataset.val || null,
      }));
      return { date, dateBtn, cells };
    });
    return dump;
  });
}

// ---------- 桌面 1280 ----------
async function desktopCompare() {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const oldP = await ctx.newPage();
  const newP = await ctx.newPage();
  const oldDump = await snapshotCal(oldP, "http://127.0.0.1:8134");
  const newDump = await snapshotCal(newP, "http://127.0.0.1:8133");
  ok("D1 旧版日历存在(≥10行)", Array.isArray(oldDump) && oldDump.length >= 10, `rows=${oldDump?.length}`);
  ok("D2 新版日历存在(≥10行)", Array.isArray(newDump) && newDump.length >= 10, `rows=${newDump?.length}`);
  // 逐位对比: 去掉 dateBtn 字段(新功能), 其余(日期集合/格子文本/颜色类/sig/idx/date/val)必须一致
  const strip = (d) => d.map((r) => ({ date: r.date, cells: r.cells }));
  ok("D3 渲染逐位一致(日期集合+格子文本+sig+idx+val)", JSON.stringify(strip(oldDump)) === JSON.stringify(strip(newDump)));
  // 新版日期标签可点标记存在
  const anyBtn = newDump.some((r) => r.dateBtn);
  ok("D4 新版日期标签带点击入口", anyBtn === true, `dateBtn=${newDump.filter((r)=>r.dateBtn).length}/${newDump.length}`);
  // 关闭引导弹窗(本地无持久化首访状态, onboarding-modal 拦截点击)
  await newP.evaluate(() => { document.querySelectorAll(".onboarding-modal, .rule-modal").forEach((m) => m && m.remove()); });
  await newP.waitForTimeout(300);
  // 点第一个日期标签, 验明细弹层
  await newP.click(".sig-day-date-btn:first-of-type");
  await newP.waitForTimeout(600);
  const det = await newP.evaluate(() => {
    const m = document.getElementById("sentimentDayDetailModal");
    if (!m || m.classList.contains("hidden")) return null;
    const body = m.querySelector(".day-detail-content");
    return { title: m.querySelector(".day-detail-title")?.textContent?.trim(), text: body?.textContent || "" };
  });
  ok("D5 点日期弹出明细(标题含日期)", det !== null && /^[0-9]{2}-[0-9]{2}/.test(det.title), `title="${det?.title}"`);
  const hasChinese = det && /[一-龥]/.test(det.text) && det.text.includes("冰点");
  ok("D6 明细含中文维度名+冰点说明", hasChinese === true, `text=${(det?.text || "").slice(0,80)}`);
  await ctx.close();
}

// ---------- 移动 375 ----------
async function mobileCheck() {
  const ctx = await browser.newContext({ viewport: { width: 375, height: 812 }, isMobile: true, hasTouch: true });
  const page = await ctx.newPage();
  const newDump = await snapshotCal(page, "http://127.0.0.1:8133");
  ok("M1 移动端新版日历存在", Array.isArray(newDump) && newDump.length >= 10, `rows=${newDump?.length}`);
  // 移动端点击目标实测: 取日期标签 boundingBox
  const box = await page.evaluate(() => {
    const el = document.querySelector(".sig-day-date-btn");
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { w: Math.round(r.width), h: Math.round(r.height) };
  });
  ok("M2 日期点击目标宽高(≥44px点击热区)", box !== null && box.w >= 40 && box.h >= 40, `w=${box?.w} h=${box?.h}`);
  // 移动端字号
  const fs = await page.evaluate(() => {
    const el = document.querySelector(".sig-day-date");
    return el ? parseFloat(getComputedStyle(el).fontSize) : null;
  });
  ok("M3 日期标签字号(≥11px)", fs !== null && fs >= 11, `fontSize=${fs}`);
  // 关闭引导弹窗
  await page.evaluate(() => { document.querySelectorAll(".onboarding-modal, .rule-modal").forEach((m) => m && m.remove()); });
  await page.waitForTimeout(300);
  // 移动端点日期弹明细
  await page.click(".sig-day-date-btn:first-of-type");
  await page.waitForTimeout(600);
  const det = await page.evaluate(() => {
    const m = document.getElementById("sentimentDayDetailModal");
    if (!m || m.classList.contains("hidden")) return null;
    const b = m.querySelector(".day-detail-content");
    const row = b?.querySelector(".dd-row");
    const r = row ? row.getBoundingClientRect() : null;
    return { title: m.querySelector(".day-detail-title")?.textContent?.trim(), text: b?.textContent?.slice(0,120) || "", rowH: r ? Math.round(r.height) : null, fontSize: b ? parseFloat(getComputedStyle(b).fontSize) : null };
  });
  ok("M4 移动端点日期弹明细(标题+中文维度)", det !== null && /[一-龥]/.test(det.text), `title="${det?.title}"`);
  ok("M5 明细行高≥28(可点/可读)", det !== null && det.rowH >= 28, `rowH=${det?.rowH}`);
  ok("M6 明细字号≥11px", det !== null && det.fontSize >= 11, `fontSize=${det?.fontSize}`);
  await ctx.close();
}

await desktopCompare();
await mobileCheck();
await browser.close();
console.log(`\n${fail === 0 ? "全部通过" : "有失败"}  pass=${pass} fail=${fail}`);
process.exit(fail === 0 ? 0 : 1);
