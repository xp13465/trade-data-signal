// #97 冒烟: 抓桌面/移动 sigkelly 区 DOM 快照(事实层: 结构/几何)
const { chromium } = require('playwright');
(async () => {
  const mode = process.argv[2] || "desktop"; // desktop | mobile
  const out = process.argv[3] || ("/tmp/kelly-" + mode + ".json");
  const browser = await chromium.launch();
  const ctx = await browser.newContext(mode === "mobile"
    ? { viewport: { width: 390, height: 844 }, userAgent: "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15", isMobile: true, hasTouch: true, deviceScaleFactor: 3 }
    : { viewport: { width: 1280, height: 900 } });
  const page = await ctx.newPage();
  const errors = [];
  // #97 批次C: 网络请求监听(切片 vs 整包)
  const reqs = { slices: 0, sliceNames: [], full: 0 };
  page.on("request", r => {
    const u = r.url();
    if (u.includes("signal_kelly_trades_parts/lab_")) { reqs.slices++; if (reqs.sliceNames.length < 8) reqs.sliceNames.push(u.split("/").pop().split("?")[0]); }
    else if (u.includes("data/signal_kelly_trades.json")) reqs.full++;
  });
  await page.goto("http://127.0.0.1:8123/index.html#lab?sub=sigkelly", { waitUntil: "domcontentloaded" });
  await page.waitForSelector(".lab-sigkelly-card", { timeout: 30000 });
  // 等费率重算(初始 _kellyApplyFeeRecompute 拉 trades.json)收尾: loading 类消失
  // (mobile 模式跳过此等待——批次C 要在整包仍在下载时开弹窗触发切片预览快路径)
  if (mode === "desktop") {
    await page.waitForFunction(() => { const h = document.querySelector(".lab-sigkelly-host"); return h && !h.classList.contains("lab-custom-host--loading"); }, { timeout: 120000 });
  }
  await page.waitForTimeout(mode === "mobile" ? 400 : 1500);
  const res = { mode, errors, url: page.url() };
  // ① host 卡片区快照
  res.hostHtmlLen = await page.evaluate(() => { const h = document.querySelector(".lab-sigkelly-host"); return h ? h.outerHTML.length : -1; });
  res.hostHash = await page.evaluate(() => { const h = document.querySelector(".lab-sigkelly-host"); if (!h) return "-"; let s = h.outerHTML; let x = 0; for (let i = 0; i < s.length; i++) { x = ((x * 31) + s.charCodeAt(i)) | 0; } return "h" + (x >>> 0).toString(16); });
  if (mode === "desktop") {
    // 桌面基线: 存完整 host HTML + 弹窗 HTML
    res.hostHtml = await page.evaluate(() => document.querySelector(".lab-sigkelly-host").outerHTML);
    // 吸顶参数条遮挡行点击 → 直接调渲染函数开弹窗(同一入口)
    await page.evaluate(() => _openSigKellyTradesModal("rating_high", "A", "y1"));
    try { await page.waitForSelector(".lab-sigkelly-trades-table", { timeout: 120000 }); } catch(e) { res.modalErr = String(e).slice(0,200); }
    await page.waitForTimeout(1500);
    if (!res.modalErr) res.modalHtml = await page.evaluate(() => document.querySelector("#lab-sigkelly-trades-overlay .lab-sigkelly-modal").outerHTML);
  } else {
    // 移动: 结构断言
    res.asserts = {};
    // C0 批次C 时序: 不等整包, 卡片一出现立刻开弹窗 → 触发切片预览快路径(整包仍在后台懒加载)
    res.asserts.previewShown = "skipped";
    // 人为拖慢整包 5s 模拟移动端弱网 → 预览快路径必现(本地 localhost 整包太快会"整包先赢")
    await page.route("**/data/signal_kelly_trades.json*", async (r) => { await new Promise((s) => setTimeout(s, 5000)); await r.continue(); });
    try {
      await page.evaluate(() => _openSigKellyTradesModal("rating_high", "A", "y1"));
      // 预览态标志 = 弹窗内出现「快速预览」提示条(轮询抓取, 本地整包过快时可能"整包先赢"属预期降级)
      let previewSeen = false;
      try {
        await page.waitForFunction(() => { const o = document.getElementById("lab-sigkelly-trades-overlay"); return o && !!o.querySelector(".lab-custom-note"); }, { timeout: 8000 });
        previewSeen = true;
      } catch (e) {}
      // 等整包就绪替换为正式表(cols-btn 出现 = 正式表标志; 最长 150s)
      const t0 = Date.now();
      await page.waitForFunction(() => !!document.querySelector(".lab-sigkelly-cols-btn"), { timeout: 150000 });
      res.asserts.previewShown = previewSeen;
      res.asserts.previewToFullMs = Date.now() - t0;
      res.asserts.previewGoneAfterFull = await page.evaluate(() => {
        const n = document.querySelector("#lab-sigkelly-trades-overlay .lab-custom-note");
        return !n || !n.textContent.includes("快速预览");
      });
      // 稳定态再取卡片区断言(费率重算完成: host loading 消失)
      await page.waitForFunction(() => { const h = document.querySelector(".lab-sigkelly-host"); return h && !h.classList.contains("lab-custom-host--loading"); }, { timeout: 150000 });
      await page.waitForTimeout(1500);
    } catch (e) { res.asserts.previewErr = String(e).slice(0, 160); }
    // A1 卡片化: 无横向滚动宽表, 有 mrow 条目
    res.asserts.mrowCards = await page.evaluate(() => document.querySelectorAll(".lab-sigkelly-mrow").length);
    res.asserts.legacyWideTables = await page.evaluate(() => document.querySelectorAll(".lab-sigkelly-wide-table").length);
    // A2 4关键列直读
    res.asserts.kpiCellsFirstCard = await page.evaluate(() => { const c = document.querySelector(".lab-sigkelly-mrow-kpi"); return c ? c.children.length : -1; });
    // A3 details 展开存在且含10项
    res.asserts.detailItems = await page.evaluate(() => { const d = document.querySelector(".lab-sigkelly-mrow-detail .lab-sigkelly-kvgrid"); return d ? d.children.length : -1; });
    // A4 弹窗 sheet 化 + 列选择器(直接调渲染函数, 绕吸顶条遮挡)
    const mopen = await page.$(".lab-sigkelly-mopen");
    if (mopen) await mopen.click({ force: true });
    else await page.evaluate(() => _openSigKellyTradesModal("rating_high", "A", "y1"));
    try {
      await page.waitForSelector(".lab-sigkelly-trades-table", { timeout: 120000 });
      await page.waitForTimeout(1500);
      res.asserts.sheetClass = await page.evaluate(() => document.getElementById("lab-sigkelly-trades-overlay").className);
      res.asserts.sheetGeom = await page.evaluate(() => { const m = document.querySelector(".lab-sigkelly-modal"); const r = m.getBoundingClientRect(); return { w: Math.round(r.width), bottom: Math.round(r.bottom), vh: window.innerHeight }; });
      res.asserts.visibleCols = await page.evaluate(() => document.querySelectorAll(".lab-sigkelly-trades-table thead th").length);
      res.asserts.colsBtn = await page.evaluate(() => !!document.querySelector(".lab-sigkelly-cols-btn"));
      res.asserts.frozenFirstCol = await page.evaluate(() => { const th = document.querySelector(".lab-sigkelly-trades-table thead th"); return getComputedStyle(th).position; });
      // 列选择器交互: 勾一个隐藏列
      await page.click(".lab-sigkelly-cols-btn");
      await page.waitForTimeout(300);
      res.asserts.colsPopItems = await page.evaluate(() => document.querySelectorAll(".lab-sigkelly-cols-pop input[type=checkbox]").length);
      const cb = await page.$(".lab-sigkelly-cols-pop input[type=checkbox]:not(:checked)");
      if (cb) { await cb.click(); await page.waitForTimeout(400); }
      res.asserts.visibleColsAfterAdd = await page.evaluate(() => document.querySelectorAll(".lab-sigkelly-trades-table thead th").length);
      // 触控目标/iOS 输入字号(批次A联动断言)
      res.asserts.closeBtnH = await page.evaluate(() => Math.round(document.querySelector(".lab-sigkelly-modal-close").getBoundingClientRect().height));
      res.asserts.inputFont = await page.evaluate(() => getComputedStyle(document.querySelector(".lab-sigkelly-filter-etf")).fontSize);
      // 下拉关闭手势模拟: touch 从 modal-head 下滑 120px → overlay 关闭
      const head = await page.$(".lab-sigkelly-modal-head");
      const hb = await head.boundingBox();
      await page.touchscreen.tap(hb.x + hb.width / 2, hb.y + hb.height / 2).catch(() => {});
      res.asserts.gripPresent = await page.evaluate(() => !!document.querySelector(".lab-sigkelly-sheet-grip"));
    } catch (e) { res.modalErr = String(e).slice(0, 200); }
    // A5 几何: 卡片无横向溢出
    res.asserts.noHorizOverflow = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1);
  }
  res.net = reqs;
  require("fs").writeFileSync(out, JSON.stringify(res));
  console.log(mode, "errors=", errors.length, "hostHash=", res.hostHash || "-", "net[slices=", reqs.slices, "full=", reqs.full, "]", JSON.stringify(reqs.sliceNames.slice(0, 4)), JSON.stringify(res.asserts || {}));
  await browser.close();
})().catch(e => { console.error("FATAL", e.message); process.exit(1); });
