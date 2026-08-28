import { chromium } from "playwright";

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));

await page.goto("http://127.0.0.1:8123", { waitUntil: "networkidle", timeout: 60000 });
await page.waitForTimeout(2000);

// 关弹窗
await page.evaluate(() => {
  document.querySelectorAll(".rule-modal-overlay, .rule-modal, .onboarding-modal").forEach(el => el.remove());
});

// 清除旧 localStorage（模拟 v1.1.5 用户残留 new14 记忆）
await page.evaluate(() => {
  localStorage.setItem("tds_kelly_fade_mode", JSON.stringify({ v: { mode: "new14" }, ts: Date.now() }));
});

// 刷新页面（触发初始化路径）
await page.reload({ waitUntil: "networkidle", timeout: 60000 });
await page.waitForTimeout(2000);
await page.evaluate(() => {
  document.querySelectorAll(".rule-modal-overlay, .rule-modal, .onboarding-modal").forEach(el => el.remove());
});

// 进凯利区
await page.click('button[data-tab="lab"]', { force: true });
await page.waitForTimeout(1000);
await page.click('button[data-sub="custom"]', { force: true });
await page.waitForTimeout(1000);
await page.evaluate(() => {
  const btns = document.querySelectorAll(".lab-subnav-child button");
  for (const b of btns) { if (b.textContent.includes("凯利")) { b.click(); break; } }
});
await page.waitForTimeout(8000);

// 检查：旧 new14 记忆是否被忽略，默认应是 S06
const info = await page.evaluate(() => ({
  dropdownVal: document.querySelector("#lab-kelly-fade-mode-sel")?.value || "NOT_FOUND",
  state: window.state?.labSigKellyFadeModeBase || "N/A",
  savedMode: (() => { try { return JSON.parse(localStorage.getItem("tds_kelly_fade_mode"))?.mode || localStorage.getItem("tds_kelly_fade_mode"); } catch(e) { return "err"; } })(),
  defaultMode: window._KELLY_FADE_DEFAULT_MODE,
}));

console.log("=== 验证结果 ===");
console.log("下拉框 selected:", info.dropdownVal);
console.log("state.labSigKellyFadeModeBase:", info.state);
console.log("localStorage 模式:", info.savedMode);
console.log("_KELLY_FADE_DEFAULT_MODE:", info.defaultMode);

if (info.dropdownVal === "s06" && info.state === "s06") {
  console.log("\n✅ PASS: 旧 new14 记忆被忽略，默认显示 S06");
} else {
  console.log("\n❌ FAIL: selected=" + info.dropdownVal + ", state=" + info.state);
}

// 再测：切换到 S06（已经是 S06 了，换到 new14 再换回 S06）
await page.selectOption("#lab-kelly-fade-mode-sel", "new14");
await page.waitForTimeout(3000);
const mid = await page.evaluate(() => ({
  value: document.querySelector("#lab-kelly-fade-mode-sel")?.value,
  state: window.state?.labSigKellyFadeModeBase,
}));
console.log("\n=== 切到 new14 后 ===");
console.log("selected:", mid.value, "state:", mid.state);

// 切回 S06
await page.selectOption("#lab-kelly-fade-mode-sel", "s06");
await page.waitForTimeout(10000);
const final_ = await page.evaluate(() => ({
  value: document.querySelector("#lab-kelly-fade-mode-sel")?.value,
  state: window.state?.labSigKellyFadeModeBase,
}));
console.log("\n=== 切回 S06 后 ===");
console.log("selected:", final_.value, "state:", final_.state);

if (final_.value === "s06" && final_.state === "s06") {
  console.log("\n✅ PASS: S06 切换正常，不下拉回弹");
} else {
  console.log("\n❌ FAIL: 切换后回弹 selected=" + final_.value);
}

if (errors.length) console.log("\n页面错误:", errors.slice(0, 3));
await page.screenshot({ path: "/tmp/s06-verify.png" });
await browser.close();
