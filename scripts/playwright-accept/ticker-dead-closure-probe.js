#!/usr/bin/env node
/**
 * ticker-dead-closure-probe.js — 死闭包轮询守卫根治自证(一次性探针)
 *
 * 目的:证明「切 tab 重建首页 ≥2 次后,旧闭包的行情轮询/渲染不再作用于已脱离 DOM 的死 wrap」。
 * 原理:跑马灯 _gtTick 每次会写死 wrap 的 title + classList(gt-degraded),这是死闭包副作用最直接的检测信号。
 *      探针用 MutationObserver 观察所有曾出现的 .global-ticker 节点:
 *         —— 节点仍在 DOM(活闭包):正常,由活闭包维护
 *         —— 节点已 detached(被 renderOverview 重建移除=死 wrap):若还收到 attributes mutation
 *              = 旧死闭包仍在操作它(修复前每 30s 改一次 title/class) = 白耗未根治
 * 判定:多次切 tab 重建后,所有 detached 死 wrap 的 post-detached mutation 计数应为 0(守卫已终止死闭包,
 *      不再摸死节点)。等待窗口跨过 30s tick 周期,确保"无守卫会改、有守卫不会改"可区分。
 *
 * 用法:
 *   node ticker-dead-closure-probe.js <URL>
 *   需本地静态站或线上;本探针为自证用,不并入常驻验收。
 */
'use strict';

const { chromium } = require('playwright');

const url = process.argv[2] || 'http://localhost:8000';

(async () => {
  const b = await chromium.launch({ headless: true });
  try {
    const p = await b.newPage();
    const errors = [];
    p.on('pageerror', e => errors.push('pageerror: ' + e.message));
    p.on('console', m => { if (m.type() === 'error') errors.push('console-error: ' + m.text()); });

    // 单一 init script:追踪所有 .global-ticker 节点的 detached 后 mutation
    await p.addInitScript(() => {
      window.__gtWatchers = {}; // seq -> {detachedMutated, connected}
      window.__gtSeqCounter = 0;
      function watchTickers() {
        document.querySelectorAll('.global-ticker').forEach(el => {
          if (el.__gtSeq) return;
          const seq = ++window.__gtSeqCounter;
          el.__gtSeq = seq;
          window.__gtWatchers[seq] = { detachedMutated: 0, connected: true, samples: [] };
          new MutationObserver(muts => {
            const w = window.__gtWatchers[el.__gtSeq];
            if (el.isConnected) return;
            w.detachedMutated++;
            if (w.samples.length < 5) {
              const rec = muts[0];
              w.samples.push({
                type: rec.type,
                attr: rec.attributeName,
                target: rec.target === el ? 'wrap' : rec.target.className || rec.target.tagName,
                time: Date.now(),
              });
            }
          }).observe(el, { attributes: true, childList: true, subtree: true, characterData: true });
        });
      }
      function syncConnected() {
        Object.keys(window.__gtWatchers).forEach(k => {
          let connected = false;
          document.querySelectorAll('.global-ticker').forEach(el => { if (el.__gtSeq === +k) connected = true; });
          window.__gtWatchers[k].connected = connected;
        });
      }
      window.__gtProbe = () => {
        watchTickers(); syncConnected();
        const detached = Object.entries(window.__gtWatchers).filter(([, w]) => !w.connected);
        let sum = 0;
        const per = detached.map(([k, w]) => {
          sum += w.detachedMutated;
          return `#${k}:${w.detachedMutated}[${w.samples.map(s => s.type + (s.attr ? '/' + s.attr : '') + '@' + s.target).join(',')}]`;
        }).join(' ');
        return {
          known: window.__gtSeqCounter,
          inDom: document.querySelectorAll('.global-ticker').length,
          detached: detached.length,
          detachedMutated: sum,
          per,
        };
      };
      setInterval(() => { __gtProbe(); }, 400); // 后台维持 watcher 状态更新
    });

    await p.goto(url, { waitUntil: 'domcontentloaded' });
    await p.waitForTimeout(3000);
    const closeModal = async () => {
      const n = await p.locator('.rule-modal-close').count();
      if (n) { await p.evaluate(() => document.querySelectorAll('.rule-modal-close').forEach(x => x.click())); await p.waitForTimeout(300); }
    };
    await closeModal();

    async function probe(label) {
      const s = await p.evaluate(() => window.__gtProbe());
      console.log(`${label}  known=${s.known} inDom=${s.inDom} detached=${s.detached} detachedMutated=${s.detachedMutated} ${s.per}`);
      return s;
    }

    await probe('\n首载:');
    for (let i = 1; i <= 3; i++) {
      await p.evaluate(() => { const b = document.querySelector('button[data-tab="market"]'); if (b) b.click(); });
      await p.waitForTimeout(1500);
      await p.evaluate(() => { const b = document.querySelector('button[data-tab="overview"]'); if (b) b.click(); });
      await p.waitForTimeout(31000); // 跨 30s tick 周期
      await closeModal();
      await probe(`重建${i}次:`);
    }

    console.log('\n===== 判定 =====');
    if (errors.length) { console.log('[FAIL] 页面有报错: ' + errors.join(' | ')); process.exit(1); }
    const fin = await p.evaluate(() => window.__gtProbe());
    if (fin.detachedMutated === 0) {
      console.log(`[PASS] ${fin.detached} 个死 wrap 均 detachedMutated=0,死闭包守卫已终止,不再摸死节点、无白耗`);
    } else {
      console.log(`[FAIL] 死 wrap 仍有 ${fin.detachedMutated} 次 detached 后 mutation,死闭包仍在操作死节点 = 守卫未彻底`);
      process.exit(1);
    }
  } finally { await b.close(); }
})().catch(e => { console.error('[FATAL] ' + (e && e.stack || e)); process.exit(1); });
