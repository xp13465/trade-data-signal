#!/usr/bin/env node
/**
 * verify_fade_mode_ttl.mjs — AI降亏模式记忆 TTL 验收(2026-08-23 用户拍板)
 *
 * 【目的】验证模式记忆「18 小时滑动过期 + 四区域独立记忆体」行为:
 *   T1 过期回退: 写伪造 20 小时前 {mode:new14,ts} → reload → 下拉=p8(键被清)
 *   T2 TTL 内保持: 写当前 ts → reload → 保持 new14
 *   T3 滑动续期: lab 切两次模式, 键内 ts 单调增(每次切换刷新计时)
 *   T4 旧格式兼容: 写无 ts 的 {mode:new14}(TTL 上线前老用户数据)→ reload → 回 p8 且键被清
 *   T5 四键互不干预: lab 切 NEW14 → tds_sim_fade_mode 不存在; sim 切 p9 → tds_kelly_fade_mode 不存在
 *
 * 【用法】node verify_fade_mode_ttl.mjs <baseURL>
 * 【复现】python3 -m http.server 8123 -d <站点目录> && node verify_fade_mode_ttl.mjs http://localhost:8123
 * 【退出码】0=全 PASS; 1=有 FAIL
 */
'use strict';
import { chromium } from 'playwright';

const BASE = (process.argv[2] || 'http://localhost:8123').replace(/\/+$/, '');
const LAB_URL = BASE + '/#lab?sub=sigkelly';
const HOME_URL = BASE + '/';
const HOUR = 3600 * 1000;
const results = [];
const add = (name, pass, detail) => { results.push({ name, pass, detail }); console.log((pass ? '[PASS] ' : '[FAIL] ') + name + ' — ' + detail); };

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });

// 等 lab 页模式下拉出现(最多 60s, 冷加载 trades.json)
async function waitLabSel(p) {
  for (let i = 0; i < 120; i++) {
    await p.waitForTimeout(500);
    const r = await Promise.race([
      p.evaluate(() => !!document.getElementById('lab-kelly-fade-mode-sel')),
      new Promise((res) => setTimeout(() => res(false), 2500)),
    ]);
    if (r) return true;
  }
  return false;
}
const readKey = (p, k) => Promise.race([
  p.evaluate((key) => localStorage.getItem(key), k),
  new Promise((res) => setTimeout(() => res('__T__'), 2500)),
]);

// ── T1 过期回退 ──
{
  const p = await ctx.newPage();
  await p.addInitScript(() => { try { localStorage.clear(); } catch (e) {} });
  const stale = JSON.stringify({ mode: 'new14', ts: Date.now() - 20 * HOUR }); // >18h TTL(2026-08-23 二次拍板)
  await p.addInitScript((v) => { try { localStorage.setItem('tds_kelly_fade_mode', v); } catch (e) {} }, stale);
  await p.goto(LAB_URL, { waitUntil: 'domcontentloaded', timeout: 30000 }).catch(() => {});
  const ok = await waitLabSel(p);
  const sel = ok ? await Promise.race([p.evaluate(() => document.getElementById('lab-kelly-fade-mode-sel').value), new Promise((r) => setTimeout(() => r('__T__'), 2500))]) : '__NOSEL__';
  const keyAfter = await readKey(p, 'tds_kelly_fade_mode');
  add('T1 过期回退', sel === 'p8' && keyAfter === null, `sel=${sel} keyAfter=${keyAfter === null ? 'null(已清)' : String(keyAfter).slice(0, 50)} selReady=${ok}`);
  await p.close().catch(() => {});
}

// ── T2 TTL 内保持 ──
{
  const p = await ctx.newPage();
  await p.addInitScript(() => { try { localStorage.clear(); } catch (e) {} });
  const fresh = JSON.stringify({ v: { mode: 'new14' }, ts: Date.now() - 5 * 60 * 1000 }); // 5 分钟前=有效(真实存储格式={v,ts})
  await p.addInitScript((v) => { try { localStorage.setItem('tds_kelly_fade_mode', v); } catch (e) {} }, fresh);
  await p.goto(LAB_URL, { waitUntil: 'domcontentloaded', timeout: 30000 }).catch(() => {});
  const ok = await waitLabSel(p);
  const sel = ok ? await Promise.race([p.evaluate(() => document.getElementById('lab-kelly-fade-mode-sel').value), new Promise((r) => setTimeout(() => r('__T__'), 2500))]) : '__NOSEL__';
  add('T2 TTL内保持', sel === 'new14', `sel=${sel}(期望 new14)`);
  // ── T3 滑动续期: 切两次, ts 单调增 ──
  if (ok && sel === 'new14') {
    const ts1Raw = await readKey(p, 'tds_kelly_fade_mode');
    const ts1 = ts1Raw ? JSON.parse(ts1Raw).ts : -1;
    await p.waitForTimeout(1100);
    await Promise.race([
      p.evaluate(() => { const s = document.getElementById('lab-kelly-fade-mode-sel'); s.value = 'a9'; s.dispatchEvent(new Event('change', { bubbles: true })); }),
      new Promise((r) => setTimeout(r, 4000)),
    ]);
    await p.waitForTimeout(500);
    const ts2Raw = await readKey(p, 'tds_kelly_fade_mode');
    let ts2 = -1; try { ts2 = ts2Raw ? JSON.parse(ts2Raw).ts : -1; } catch (e) {}
    const fmtOk = ts2Raw ? (() => { try { const o = JSON.parse(ts2Raw); return o.v && o.v.mode === 'a9' && typeof o.ts === 'number'; } catch (e) { return false; } })() : false;
    add('T3 滑动续期', ts2 > ts1 && fmtOk, `ts1=${ts1} ts2=${ts2} 增=${ts2 > ts1} 格式={mode:a9,ts}= ${fmtOk}`);
  }
  await p.close().catch(() => {});
}

// ── T4 旧格式兼容(无 ts → 清键回 p8)──
{
  const p = await ctx.newPage();
  await p.addInitScript(() => { try { localStorage.clear(); } catch (e) {} });
  await p.addInitScript(() => { try { localStorage.setItem('tds_kelly_fade_mode', JSON.stringify({ mode: 'new14' })); } catch (e) {} });
  await p.goto(LAB_URL, { waitUntil: 'domcontentloaded', timeout: 30000 }).catch(() => {});
  const ok = await waitLabSel(p);
  const sel = ok ? await Promise.race([p.evaluate(() => document.getElementById('lab-kelly-fade-mode-sel').value), new Promise((r) => setTimeout(() => r('__T__'), 2500))]) : '__NOSEL__';
  const keyAfter = await readKey(p, 'tds_kelly_fade_mode');
  add('T4 旧格式兼容', sel === 'p8' && keyAfter === null, `sel=${sel} keyAfter=${keyAfter === null ? 'null(已清)' : String(keyAfter).slice(0, 40)}`);
  await p.close().catch(() => {});
}

// ── T5 四键互不干预 ──
{
  // 注意: 本场景跨多次导航(lab→首页), 不能挂每导航执行的 localStorage.clear init script
  // (会在第二次 goto 时清掉 lab 刚写的键, 制造假阴性); 新建 context 天然无存储=干净起步。
  const ctx5 = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const p = await ctx5.newPage();
  // lab 切 NEW14 → sim/home/overfit 三键零出现
  await p.goto(LAB_URL, { waitUntil: 'domcontentloaded', timeout: 30000 }).catch(() => {});
  const okLab = await waitLabSel(p);
  if (okLab) {
    await Promise.race([
      p.evaluate(() => { const s = document.getElementById('lab-kelly-fade-mode-sel'); s.value = 'new14'; s.dispatchEvent(new Event('change', { bubbles: true })); }),
      new Promise((r) => setTimeout(r, 4000)),
    ]);
    await p.waitForTimeout(400);
  }
  await p.waitForTimeout(2500); // 等切模式触发的全量重算完成, 防 evaluate 排队读到 race 占位值
  const afterLab = await readKey(p, 'tds_kelly_fade_mode');
  const simKey = await readKey(p, 'tds_sim_fade_mode');
  const homeKey = await readKey(p, 'tds_home_fade_mode');
  const ovKey = await readKey(p, 'tds_overfit_fade_mode');
  let afterLabMode = '?'; try { const _o = JSON.parse(afterLab); afterLabMode = (_o && _o.v && _o.v.mode) || _o.mode; } catch (e) {}
  add('T5a lab切NEW只写自己键', okLab && afterLabMode === 'new14' && simKey === null && homeKey === null && ovKey === null,
    `lab.mode=${afterLabMode} sim=${simKey === null ? 'null' : 'WRITTEN!'} home=${homeKey === null ? 'null' : 'WRITTEN!'} overfit=${ovKey === null ? 'null' : 'WRITTEN!'}`);

  // sim 弹窗切 p9 → 只写 tds_sim_fade_mode, lab 键不变
  await p.goto(HOME_URL, { waitUntil: 'domcontentloaded', timeout: 30000 }).catch(() => {});
  await p.waitForTimeout(2500);
  const openR = await Promise.race([
    p.evaluate(() => { const b = document.querySelector('.sig-kbtn-sim'); if (!b) return 'no-btn'; b.click(); return 'clicked'; }),
    new Promise((res) => setTimeout(() => res('timeout'), 10000)),
  ]);
  await p.waitForTimeout(2000);
  const setR = await Promise.race([
    p.evaluate(() => {
      const s = document.getElementById('sim-fade-mode-sel');
      if (!s) return 'no-sim-sel';
      s.value = 'p9';
      s.dispatchEvent(new Event('change', { bubbles: true }));
      return 'set-p9';
    }),
    new Promise((res) => setTimeout(() => res('timeout'), 8000)),
  ]);
  await p.waitForTimeout(600);
  const simKeyAfter = await readKey(p, 'tds_sim_fade_mode');
  const labKeyAfter = await readKey(p, 'tds_kelly_fade_mode');
  let simMode = '?'; try { const _o = JSON.parse(simKeyAfter); simMode = (_o && _o.v && _o.v.mode) || _o.mode; } catch (e) {}
  let labKeyModeAfter = '?'; try { const _o = JSON.parse(labKeyAfter); labKeyModeAfter = (_o && _o.v && _o.v.mode) || _o.mode; } catch (e) {}
  add('T5b sim切p9只写sim键+lab键不变', setR === 'set-p9' && simMode === 'p9' && labKeyModeAfter === 'new14',
    `open=${openR} set=${setR} simKey.mode=${simMode} lab键mode=${labKeyModeAfter}(应仍=new14 未被 sim 触碰)`);

  // sim 关闭重开(TTL 内)= 显示上次所选 p9(记忆体语义, 非 T3-1 强制重置)
  await Promise.race([
    p.evaluate(() => { const m = document.getElementById('simBacktestModal'); if (m) m.classList.add('hidden'); }),
    new Promise((r) => setTimeout(r, 3000)),
  ]);
  await p.waitForTimeout(300);
  const openR2 = await Promise.race([
    p.evaluate(() => { const b = document.querySelector('.sig-kbtn-sim'); if (!b) return 'no-btn'; b.click(); return 'clicked'; }),
    new Promise((res) => setTimeout(() => res('timeout'), 8000)),
  ]);
  await p.waitForTimeout(1500);
  const reopenVal = await Promise.race([
    p.evaluate(() => { const s = document.getElementById('sim-fade-mode-sel'); return s ? s.value : 'no-sel'; }),
    new Promise((res) => setTimeout(() => res('__T__'), 4000)),
  ]);
  add('T6 sim重开显示上次所选(记忆体)', openR2 === 'clicked' && reopenVal === 'p9', `reopen值=${reopenVal}(期望 p9; T3-1 旧设计强制 p8 已按用户拍板废弃)`);

  await p.close().catch(() => {});
  await ctx5.close().catch(() => {});
}

await browser.close();
const fails = results.filter((r) => !r.pass);
console.log(`\n===== 总结: ${results.length - fails.length}/${results.length} PASS =====`);
process.exit(fails.length ? 1 : 0);
