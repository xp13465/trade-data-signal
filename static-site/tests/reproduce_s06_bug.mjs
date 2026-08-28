/**
 * reproduce_s06_bug.mjs - 复现 S06 切换后下拉框回弹到 new14 的 bug
 *
 * 用法: node reproduce_s06_bug.mjs http://127.0.0.1:8123
 */
import { chromium } from "playwright";

const BASE = process.argv[2] || "http://127.0.0.1:8123";

async function main() {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await ctx.newPage();

  const errors = [];
  page.on("pageerror", (err) => errors.push(err.message));

  console.log(`=== 打开首页 ===`);
  await page.goto(BASE, { waitUntil: "networkidle", timeout: 60000 });
  await page.waitForTimeout(2000);

  // 1. 清除 localStorage
  console.log("\n=== 1. 清除 localStorage 模式记忆 ===");
  await page.evaluate(() => {
    localStorage.removeItem("tds_kelly_fade_mode");
  });

  // 刷新
  await page.reload({ waitUntil: "networkidle", timeout: 60000 });
  await page.waitForTimeout(2000);

  // 2. 关闭 onboarding 弹窗（如果有）
  console.log("\n=== 2. 关闭 onboarding 弹窗 ===");
  await page.evaluate(() => {
    const overlay = document.querySelector(".rule-modal-overlay");
    if (overlay) overlay.click();
    const closeBtn = document.querySelector(".rule-modal .close-btn, .onboarding-modal .close-btn, .rule-float-btn");
    if (closeBtn) closeBtn.click();
    // 移除弹窗 DOM
    document.querySelectorAll(".rule-modal-overlay, .rule-modal, .onboarding-modal").forEach(el => el.remove());
  });
  await page.waitForTimeout(500);

  // 点击"策略实验"tab
  console.log("\n=== 3. 切换到策略实验 tab ===");
  const labTab = await page.$('button[data-tab="lab"]');
  if (!labTab) {
    console.log("❌ 找不到策略实验 tab");
    await browser.close();
    return;
  }
  await labTab.click();
  await page.waitForTimeout(5000); // 等待凯利数据加载

  // 4. 检查下拉框是否存在
  console.log("\n=== 4. 检查下拉框 ===");
  const dropInfo = await page.evaluate(() => {
    const sel = document.querySelector("#lab-kelly-fade-mode-sel");
    if (!sel) return { found: false };
    return {
      found: true,
      value: sel.value,
      options: Array.from(sel.options).map(o => ({ v: o.value, s: o.selected, t: o.textContent.substring(0, 30) })),
      state: window.state ? window.state.labSigKellyFadeModeBase : "NO_STATE",
      defaultMode: window._KELLY_FADE_DEFAULT_MODE,
      savedMode: (() => {
        try { const r = localStorage.getItem("tds_kelly_fade_mode"); return r ? JSON.parse(r) : null; } catch(e) { return null; }
      })(),
    };
  });
  console.log("下拉框:", JSON.stringify(dropInfo, null, 2));

  if (!dropInfo.found) {
    console.log("❌ 下拉框不存在，凯利区可能未加载");
    await page.screenshot({ path: "/tmp/s06-no-dropdown.png", fullPage: false });
    await browser.close();
    return;
  }

  // 5. 尝试切换到 S06
  console.log("\n=== 5. 切换到 S06 ===");
  const beforeSwitch = await page.evaluate(() => {
    const sel = document.querySelector("#lab-kelly-fade-mode-sel");
    return { value: sel?.value, state: window.state?.labSigKellyFadeModeBase };
  });
  console.log("切换前:", JSON.stringify(beforeSwitch));

  // 选择 S06
  await page.selectOption("#lab-kelly-fade-mode-sel", "s06");
  await page.waitForTimeout(1000);

  const midSwitch = await page.evaluate(() => {
    const sel = document.querySelector("#lab-kelly-fade-mode-sel");
    return {
      value: sel?.value,
      state: window.state?.labSigKellyFadeModeBase,
      savedMode: (() => { try { const r = localStorage.getItem("tds_kelly_fade_mode"); return r ? JSON.parse(r) : null; } catch(e) { return null; } })(),
    };
  });
  console.log("切换后(1s):", JSON.stringify(midSwitch));

  // 等待异步完成
  await page.waitForTimeout(8000);

  const afterSwitch = await page.evaluate(() => {
    const sel = document.querySelector("#lab-kelly-fade-mode-sel");
    return {
      value: sel?.value,
      state: window.state?.labSigKellyFadeModeBase,
      savedMode: (() => { try { const r = localStorage.getItem("tds_kelly_fade_mode"); return r ? JSON.parse(r) : null; } catch(e) { return null; } })(),
      s06Status: typeof window._tdsS06Status === "function" ? window._tdsS06Status() : null,
    };
  });
  console.log("切换后(8s):", JSON.stringify(afterSwitch, null, 2));

  // 截图
  await page.screenshot({ path: "/tmp/s06-after-switch.png", fullPage: false });

  // 6. 总结
  console.log("\n=== 6. 总结 ===");
  if (afterSwitch.value === "s06" && afterSwitch.state === "s06") {
    console.log("✅ S06 切换正常！selected=s06, state=s06");
  } else {
    console.log(`❌ BUG: selected=${afterSwitch.value}, state=${afterSwitch.state}`);
    if (afterSwitch.value !== "s06") console.log("   → 下拉框回弹了");
    if (afterSwitch.state !== "s06") console.log("   → state.labSigKellyFadeModeBase 未保持 s06");
  }

  if (errors.length > 0) {
    console.log("\n页面错误:");
    errors.forEach(e => console.log("  ERROR:", e));
  }

  await browser.close();
}

main().catch(e => { console.error("FATAL:", e); process.exit(1); });
