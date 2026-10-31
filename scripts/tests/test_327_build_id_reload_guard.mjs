// #327 P0 BUILD_ID 不一致循环 reload 防护·inline-init.js 防循环单测（2026-10-31）。
//
// 背景: __build.json 陈旧（a653）vs index meta（a654）→ inline-init.js 比对不一致 → reload
//   → reload 后 __build.json 仍 a653 → 循环 reload 白屏。防循环: 单 tab 同一不一致签名
//   (metaBid|fetchBid) 只 reload 一次, 之后 sessionStorage 标记阻断 + console.warn。
//
// 覆盖（证据用例）:
//   1 首次不一致 → 探活就绪 → reload 一次 + 写 sessionStorage 标记 feBuildIdReloadSig
//   2 reload 后（同 sessionStorage）仍不一致 → 不重复 reload, console.warn
//   3 一致时不 reload（不写标记）
//   4 新签名（不一致值变化）不受旧标记阻断 → 允许 reload 一次
//
// 纯 node vm 沙箱, 不依赖浏览器; inline-init.js 整段 IIFE 在 mock 全局里求值。
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';

const ROOT = new URL('../../', import.meta.url);
const SRC = readFileSync(new URL('static-site/inline-init.js', ROOT), 'utf8');

function makeSandbox({ metaBid, buildId }) {
  const store = new Map();
  const state = { reloadCount: 0, warns: [], _now: 1_700_000_000_000, _pendingTimers: [], _pendingIdle: [] };
  const sessionStorageApi = {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => { store.set(k, String(v)); },
    removeItem: (k) => { store.delete(k); },
  };
  const sandbox = {
    window: { addEventListener() {}, attachEvent() {}, _hmt: [] },
    document: {
      querySelector(sel) {
        if (sel === 'meta[name="build-id"]') return metaBid ? { content: metaBid } : null;
        return null;
      },
      documentElement: { classList: { add() {} } },
      addEventListener() {},
      getElementsByTagName() { return [{ parentNode: { insertBefore() {} } }]; },
    },
    navigator: { userAgent: 'test-ua', sendBeacon: () => true },
    location: { reload: () => { state.reloadCount++; } },
    sessionStorage: sessionStorageApi,
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    fetch(url) {
      if (url === '/__build.json') {
        return Promise.resolve({ status: 200, json: () => Promise.resolve({ build_id: buildId }) });
      }
      if (url === './app.min.js') {
        return Promise.resolve({ status: 200, headers: { get: (h) => (h === 'content-type' ? 'application/javascript' : null) } });
      }
      return Promise.resolve({ status: 404, headers: { get: () => null } });
    },
    console: { warn: (...a) => { state.warns.push(a.join(' ')); }, log() {}, error() {} },
    Date: Object.assign(class extends Date {}, { now: () => state._now }),
    setTimeout: (cb) => { state._pendingTimers.push(cb); },
    clearTimeout() {},
    requestIdleCallback: (cb) => { state._pendingIdle.push(cb); },
    requestAnimationFrame: (cb) => { state._pendingIdle.push(cb); },
    addEventListener() {},
    JSON, Math, parseInt, String, Array, Object, Promise, Error, RegExp,
  };
  sandbox.globalThis = sandbox;
  sandbox.self = sandbox;
  state._store = store;
  state._sessionStorageApi = sessionStorageApi;
  return { sandbox, state };
}

async function runScript(metaBid, buildId, sharedStore) {
  const { sandbox, state } = makeSandbox({ metaBid, buildId });
  if (sharedStore) {
    // 复用上一 tab 的 sessionStorage（模拟 reload 不清 sessionStorage）
    const api = {
      getItem: (k) => (sharedStore.has(k) ? sharedStore.get(k) : null),
      setItem: (k, v) => { sharedStore.set(k, String(v)); },
      removeItem: (k) => { sharedStore.delete(k); },
    };
    sandbox.sessionStorage = api;
    state._store = sharedStore;
  }
  const ctx = vm.createContext(sandbox);
  vm.runInContext(SRC, ctx);
  // flush timers + idle, 让 fetch 微任务 resolve; 推进时间使 _idleEnough 通过（IDLE_DELAY_MS=5000）
  state._now += 10_000;
  for (const cb of state._pendingTimers.splice(0)) cb();
  await Promise.resolve(); await Promise.resolve();
  for (const cb of state._pendingIdle.splice(0)) cb();
  await Promise.resolve(); await Promise.resolve();
  for (const cb of state._pendingIdle.splice(0)) cb();
  await Promise.resolve();
  for (const cb of state._pendingTimers.splice(0)) cb();
  await Promise.resolve();
  return { state };
}

test('case1+2 mismatch reloads once then blocks repeat on persistent stale', async () => {
  const r1 = await runScript('20261031-a654', '20261029-a653');
  assert.equal(r1.state.reloadCount, 1, `首次应 reload 1 次, 实际 ${r1.state.reloadCount}`);
  const guardRaw = r1.state._store.get('feBuildIdReloadSig');
  assert.ok(guardRaw, '首次 reload 后应写 sessionStorage 标记 feBuildIdReloadSig');
  const guard = JSON.parse(guardRaw);
  assert.equal(guard.sig, '20261031-a654|20261029-a653', `标记 sig 应为 mismatch 签名, 实际 ${guard.sig}`);

  // reload 后新页面, 复用 sessionStorage, 仍不一致 → 不 reload + warn
  const r2 = await runScript('20261031-a654', '20261029-a653', r1.state._store);
  assert.equal(r2.state.reloadCount, 0, `二次应不 reload, 实际 reload ${r2.state.reloadCount} 次`);
  assert.ok(r2.state.warns.length > 0, '二次不一致应 console.warn 提示暂停 reload');
});

test('case3 match no reload no guard', async () => {
  const r = await runScript('20261031-a654', '20261031-a654');
  assert.equal(r.state.reloadCount, 0, `一致时不应 reload, 实际 ${r.state.reloadCount}`);
  assert.ok(!r.state._store.get('feBuildIdReloadSig'), '一致时不应写标记');
});

test('case4 new mismatch sig bypasses old guard reloads once', async () => {
  const r1 = await runScript('20261031-a654', '20261029-a653');
  assert.equal(r1.state.reloadCount, 1, `首次应 reload 1 次, 实际 ${r1.state.reloadCount}`);
  // 新签名: a654 vs a655 → 旧标记(a654|a653)不阻断 → 允许 reload 一次
  const r2 = await runScript('20261031-a654', '20261031-a655', r1.state._store);
  assert.equal(r2.state.reloadCount, 1, `新签名应 reload 1 次, 实际 ${r2.state.reloadCount}`);
});
