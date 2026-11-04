'use strict';
// Independent fault injection; reads current repository functions, performs no network or repository writes.
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const repo = process.argv[2] || '/Users/linhuichen/code/trade';
const lab = fs.readFileSync(path.join(repo, 'static-site/lab.js'), 'utf8');
const start = lab.indexOf('async function fetchJSONProgress(');
const end = lab.indexOf('// 加载完整数据(trades/equity_curve/tw/ew)', start);
if (start < 0 || end < 0) throw Error('Cannot locate current function');
const code = lab.slice(start, end);
async function progressCase(cancel) {
  const outer = new AbortController();
  let inner, fallbackCalls = 0, activeTimers = 0;
  const ctx = {
    console, AbortController,
    setTimeout(fn, ms) { activeTimers++; return setTimeout(() => { activeTimers--; fn(); }, ms); },
    clearTimeout(id) { activeTimers--; clearTimeout(id); },
    fetchJSON: async () => { fallbackCalls++; return { fallback: true }; },
    // Headers are immediate; absent Content-Length; body never completes unless aborted.
    fetch: async (_url, opts) => {
      inner = opts.signal;
      return { ok: true, headers: { get: () => null }, json: () => new Promise((_resolve, reject) => {
        inner.addEventListener('abort', () => { const e = Error('body aborted'); e.name = 'AbortError'; reject(e); }, { once: true });
      }) };
    }
  };
  vm.createContext(ctx); vm.runInContext(code, ctx);
  const promise = ctx.fetchJSONProgress('https://example.invalid/lab_sim_sh_full.json', () => {}, outer.signal, 20);
  if (cancel) setTimeout(() => outer.abort(), 5);
  const result = await Promise.race([
    promise.then(() => 'resolved', e => 'rejected:' + e.name),
    new Promise(resolve => setTimeout(() => resolve('PENDING_AFTER_80MS'), 80))
  ]);
  console.log(JSON.stringify({ case: cancel ? 'external_abort_after_headers' : 'timeout_after_headers', timeoutMs: 20, contentLength: null, result, outerAborted: outer.signal.aborted, innerAborted: inner.aborted, activeTimers, fallbackCalls }));
}
async function bootCase() {
  const html = fs.readFileSync(path.join(repo, 'static-site/index.html'), 'utf8');
  const app = fs.readFileSync(path.join(repo, 'static-site/app.js'), 'utf8');
  const script = html.match(/<script>\s*([\s\S]*?)<\/script>/)[1];
  const fn = app.slice(app.indexOf('async function _bootJSON()'), app.indexOf('// C3(2026-10-17'));
  const calls = [], timers = []; let fallbacks = 0;
  const ctx = { location: { hostname: 'ss.fx8.store' }, window: {}, AbortController, console,
    fetch(url, opts) { calls.push({ url, signalAttached: !!opts.signal }); return new Promise(() => {}); },
    setTimeout(_fn, ms) { timers.push(ms); return 1; }, clearTimeout() {},
    fetchJSON: async () => { fallbacks++; return {}; }
  };
  vm.createContext(ctx); vm.runInContext(script + '\n' + fn, ctx);
  const result = await Promise.race([ctx._bootJSON().then(() => 'settled'), new Promise(r => setTimeout(() => r('PENDING_AFTER_40MS'), 40))]);
  console.log(JSON.stringify({ case: 'main_boot_hanging_fetch', calls, timers, fallbacks, result }));
}
(async () => { await progressCase(false); await progressCase(true); await bootCase(); })().catch(e => { console.error(e); process.exitCode = 1; });
