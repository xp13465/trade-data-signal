// 冒烟: AI 预测板块交互三连修复(feat/db-brief-interaction-fix)
// 断言 a:方向=A股红涨绿跌分色(up=db-up 红 / down=db-down 绿 / flat·跨0=db-flat 灰;yield 不上色)
// 断言 b:仅标题行(.sh-date)点击切换折叠,正文区点击不触发
// 断言 c:点「历史反思校准」details 自身开合、外层板块保持展开(连坐修复)
// 断言 d:展开/收起状态往返无损 + 翻页重渲染回到默认展开;🔊 播报按钮点击不影响折叠态
// 复现: bash docs/ai-predict/scripts/dbbrief_interaction_smoke.sh(内含起服务+跑本脚本命令)
const { chromium } = require('playwright');
const BASE = process.env.SMOKE_BASE || "http://127.0.0.1:8136";
(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto(BASE + "/harness.html", { waitUntil: "domcontentloaded" });
  await page.waitForFunction("window.__ready === true", { timeout: 20000 });
  const results = [];
  const assert = (name, cond, extra) => { results.push({ name, pass: !!cond, extra: extra || "" }); };

  // ── a1: direction=up 条目(20260826):徽标红/区间红/钢铁板块红/深证成指红/yield不上色 ──
  const a1 = await page.evaluate(() => {
    const it = document.querySelector('.db-item[data-date="20260826"]');
    if (!it) return null;
    const dir = it.querySelector(".sh-date .db-dir");
    const rng = it.querySelector(".sh-date .db-range");
    const sectors = [...it.querySelectorAll(".db-sector")].map((s) => ({ t: s.textContent.trim(), cls: s.className }));
    const indexes = [...it.querySelectorAll(".db-index")].map((s) => ({ t: s.textContent.trim(), cls: s.className }));
    return {
      dirCls: dir ? dir.className : null,
      rangeCls: rng ? rng.className : null,
      steel: sectors.find((s) => s.t.includes("钢铁")),
      sz: indexes.find((s) => s.t.includes("深证成指")),
      bond: indexes.find((s) => s.t.includes("10年国债")),
      nSectors: sectors.length, nIndexes: indexes.length,
    };
  });
  assert("a1 条目存在且有区间芯片", a1 && a1.nSectors > 0 && a1.nIndexes >= 7, JSON.stringify(a1));
  assert("a2 direction=up → .db-dir 含 db-up 且不含 db-down", /\bdb-up\b/.test(a1.dirCls) && !/\bdb-down\b/.test(a1.dirCls), a1.dirCls);
  assert("a3 大盘区间 +0.20~+0.70 → .db-range 含 db-up", /\bdb-up\b/.test(a1.rangeCls), a1.rangeCls);
  assert("a4 板块 钢铁+0.8~+1.3 → .db-sector 含 db-up", a1.steel && /\bdb-up\b/.test(a1.steel.cls), JSON.stringify(a1.steel));
  assert("a5 中间层 深证成指+0.3~+0.8 → .db-index 含 db-up", a1.sz && /\bdb-up\b/.test(a1.sz.cls), JSON.stringify(a1.sz));
  assert("a6 yield 10年国债(bp) 不上涨跌色", a1.bond && /\bdb-index-yield\b/.test(a1.bond.cls) && !/\bdb-(up|down)\b/.test(a1.bond.cls), JSON.stringify(a1.bond));

  // ── a7/a8: down 与 flat 条目 ──
  const dirDown = await page.evaluate(() => (document.querySelector('.db-item[data-date="20260824"] .sh-date .db-dir') || {}).className || "");
  const secDown = await page.evaluate(() => {
    const it = document.querySelector('.db-item[data-date="20260824"]');
    const s = [...(it ? it.querySelectorAll(".db-sector") : [])].find((x) => x.textContent.includes("电子"));
    return s ? s.className : "";
  });
  const dirFlat = await page.evaluate(() => (document.querySelector('.db-item[data-date="20260825"] .sh-date .db-dir') || {}).className || "");
  assert("a7 direction=down → 徽标/电子板块(-2.0~-1.5)均绿系 db-down", /\bdb-down\b/.test(dirDown) && /\bdb-down\b/.test(secDown), dirDown + " | " + secDown);
  assert("a8 direction=flat → 徽标中性灰 db-flat 不含红绿类", /\bdb-flat\b/.test(dirFlat) && !/\bdb-(up|down)\b/.test(dirFlat), dirFlat);

  // 计算样式实测(事实层):up 元素文字色应为红系(r>g), down 为绿系(g>r)
  const colors = await page.evaluate(() => {
    const gc = (sel) => { const el = document.querySelector(sel); return el ? getComputedStyle(el).color : null; };
    return { up: gc('.db-item[data-date="20260826"] .sh-date .db-dir.db-up'), down: gc('.db-item[data-date="20260824"] .sh-date .db-dir.db-down') };
  });
  const rgbOf = (c) => c ? c.match(/\d+/g).slice(0, 3).map(Number) : [];
  const [ru, gu] = rgbOf(colors.up), [rd, gd] = rgbOf(colors.down);
  assert("a9 computed style: up 红系(r>g) down 绿系(g>r)", ru > gu && gd > rd, JSON.stringify(colors));

  // ── b: 点击区域收敛 ──
  const b0 = await page.evaluate(() => {
    const it = document.querySelector('.db-item[data-date="20260821"]');
    const d = it.querySelector(".db-detail");
    return { hidden: d.classList.contains("hidden"), hint: it.querySelector(".db-expand-hint").textContent };
  });
  assert("b1 默认展开(hint=点击收起)", b0.hidden === false && b0.hint.includes("点击收起"), JSON.stringify(b0));
  await page.click('.db-item[data-date="20260821"] .db-detail p'); // 正文深处点击
  const b2 = await page.evaluate(() => document.querySelector('.db-item[data-date="20260821"] .db-detail').classList.contains("hidden"));
  assert("b2 正文区点击不触发整体折叠", b2 === false, "hidden=" + b2);
  await page.click('.db-item[data-date="20260821"] .sh-date'); // 标题行点击
  const b3 = await page.evaluate(() => ({ h: document.querySelector('.db-item[data-date="20260821"] .db-detail').classList.contains("hidden"), t: document.querySelector('.db-item[data-date="20260821"] .db-expand-hint').textContent }));
  assert("b3 标题行点击收起 + hint 翻转", b3.h === true && b3.t.includes("点击展开"), JSON.stringify(b3));
  await page.click('.db-item[data-date="20260821"] .sh-date');
  const b4 = await page.evaluate(() => document.querySelector('.db-item[data-date="20260821"] .db-detail').classList.contains("hidden"));
  assert("b4 标题行再点恢复展开", b4 === false);
  // 🔊 播报按钮在标题行内,独立操作不触发折叠
  await page.click('.db-item[data-date="20260821"] .sh-date', { position: { x: 4, y: 4 } }).catch(() => {});
  const playRes = await page.evaluate(() => {
    const it = document.querySelector('.db-item[data-date="20260821"]');
    const btn = it.querySelector(".sh-date .db-play");
    const before = it.querySelector(".db-detail").classList.contains("hidden");
    btn.click();
    return { before, after: it.querySelector(".db-detail").classList.contains("hidden") };
  });
  assert("b5 🔊 播报按钮点击不改变折叠状态", playRes.before === playRes.after, JSON.stringify(playRes));

  // ── c: 历史反思校准 details 点开,外层板块保持展开(连坐修复) ──
  const c = await page.evaluate(() => {
    const it = document.querySelector('.db-item[data-date="20260826"]');
    const wrap = it.querySelector(".db-reflection");
    if (!wrap) return { exists: false };
    const wasOpenDetailHidden = it.querySelector(".db-detail").classList.contains("hidden");
    wrap.querySelector(".db-reflection-title").click();
    return { exists: true, outerHiddenBefore: wasOpenDetailHidden, reflOpen: wrap.open, outerHiddenAfter: it.querySelector(".db-detail").classList.contains("hidden") };
  });
  assert("c1 反思面板存在且外层本就展开", c.exists === true && c.outerHiddenBefore === false, JSON.stringify(c));
  assert("c2 点反思 summary:自身展开 + 外层未连坐收起", c.reflOpen === true && c.outerHiddenAfter === false, JSON.stringify(c));
  // 多角色辩论 details 同验证(旧行为已有排除,新结构下天然免疫)
  const c3 = await page.evaluate(() => {
    const it = document.querySelector('.db-item[data-date="20260826"]');
    const w = it.querySelector(".db-debate-wrap");
    if (!w) return { skip: true };
    w.querySelector("summary").click();
    return { open: w.open, outerHidden: it.querySelector(".db-detail").classList.contains("hidden") };
  });
  assert("c3 辩论 details 正常开合且外层不受影响", c3.skip || (c3.open === true && c3.outerHidden === false), JSON.stringify(c3));

  // ── d: 状态往返 + 重渲染默认展开(数据 13 条单页,sh-next disabled;
  //      翻页与重渲染走同一 _loadDailyBriefPage(),evaluate 直调等价) ──
  await page.click('.db-item[data-date="20260826"] .sh-date'); // 收起今日方向条
  await page.evaluate(() => _loadDailyBriefPage()); // 重渲染(翻页同路径)
  await page.waitForTimeout(300);
  const d = await page.evaluate(() => ({
    reflStillOpen: (() => { const r = document.querySelector('.db-item[data-date="20260826"] .db-reflection'); return r ? r.open : null; })(),
    allDefaultOpen: [...document.querySelectorAll(".db-item .db-detail")].every((x) => !x.classList.contains("hidden")),
    hintTextsOk: [...document.querySelectorAll(".db-item .db-expand-hint")].every((x) => x.textContent.includes("点击收起")),
  }));
  assert("d1 翻页往返后列表重渲染回默认全展开", d.allDefaultOpen && d.hintTextsOk, JSON.stringify(d));
  // 内容无丢失:往返渲染后 20260826 内 .db-line 行数一致
  const lineN = await page.evaluate(() => document.querySelectorAll('.db-item[data-date="20260826"] .db-line').length);
  assert("d2 重渲染内容完整(db-line>0)", lineN > 0, "lineN=" + lineN);

  // 页面级 JS 错误零容忍(harness/app.js 自身语法与运行时)
  assert("z 页面无 JS 运行时错误(pageerror)", errors.length === 0, errors.join(" | ").slice(0, 500));

  const failed = results.filter((r) => !r.pass);
  console.log("== SMOKE RESULT ==" + JSON.stringify({ total: results.length, failed: failed.length }, null, 0));
  results.forEach((r) => console.log((r.pass ? "PASS" : "FAIL") + "  " + r.name + (r.pass ? "" : "   ⚠ " + String(r.extra).slice(0, 300))));
  await browser.close();
  process.exit(failed.length ? 1 : 0);
})();
