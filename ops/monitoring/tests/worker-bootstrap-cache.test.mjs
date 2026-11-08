// Actual Worker entrypoint, synthetic bindings only. No network or dependencies.
import test from 'node:test';
import assert from 'node:assert/strict';
import worker from '../../../worker/headers.js';

const ORIGIN = 'https://fixture.invalid';
const fresh = JSON.stringify({ round: 'new', value: 732 / 5189 });
const stale = JSON.stringify({ round: 'old' });

async function fixture(run, { cacheHit = true, r2 = 'ok' } = {}) {
  const original = Object.getOwnPropertyDescriptor(globalThis, 'caches');
  const calls = { match: [], put: [], get: [], assets: [], pending: [] };
  Object.defineProperty(globalThis, 'caches', { configurable: true, value: { default: {
    async match(request) {
      calls.match.push(request.url);
      // If bootstrap code ever checks the cache, this old response is served.
      return cacheHit ? new Response(stale, { headers: {
        'Cache-Control': 'public, max-age=3600', ETag: '"old"',
      } }) : undefined;
    },
    async put(request, response) {
      calls.put.push({ url: request.url, body: await response.text(), cc: response.headers.get('Cache-Control') });
    },
  } } });
  const env = {
    R2_BUCKET: { async get(key) {
      calls.get.push(key);
      if (r2 === 'error') throw new Error('synthetic R2 unavailable');
      if (r2 === 'missing') return null;
      return {
        body: fresh, httpEtag: '"new"',
        writeHttpMetadata(headers) {
          headers.set('Content-Type', 'application/json');
          // Stored object metadata must not override the route freshness policy.
          headers.set('Cache-Control', 'public, max-age=14400');
        },
      };
    } },
    ASSETS: { async fetch(request) {
      calls.assets.push(request.url);
      return new Response('synthetic asset fallback', { status: 200 });
    } },
  };
  const ctx = { waitUntil(promise) { calls.pending.push(promise); } };
  const fetchPath = path => worker.fetch(new Request(ORIGIN + path), env, ctx);
  try {
    await run({ calls, fetchPath });
    await Promise.all(calls.pending);
  } finally {
    if (original) Object.defineProperty(globalThis, 'caches', original);
    else delete globalThis.caches;
  }
}

function assertNoCache(calls) {
  assert.deepEqual(calls.match, [], 'must not look up stale cache');
  assert.deepEqual(calls.put, [], 'must not cache response');
  assert.equal(calls.pending.length, 0, 'must not schedule cache write');
}

for (const name of ['overview', 'boot', 'signals_today']) {
  for (const prefix of ['/data/', '/r2/data/']) {
    for (const suffix of ['', '?v=synthetic']) {
      const path = `${prefix}${name}.json${suffix}`;
      test(`bootstrap ${path} ignores old cache and returns R2 no-store`, () => fixture(async ({ calls, fetchPath }) => {
        // Repeat same URL: each read must reach R2, rather than warm a cache.
        for (let i = 0; i < 2; i++) {
          const response = await fetchPath(path);
          assert.equal(response.status, 200);
          assert.equal(await response.text(), fresh);
          assert.equal(response.headers.get('ETag'), '"new"');
          assert.equal(response.headers.get('Cache-Control'), 'no-store, max-age=0');
          assert.equal(response.headers.get('Access-Control-Allow-Origin'), '*');
        }
        assert.deepEqual(calls.get, [`data/${name}.json`, `data/${name}.json`]);
        assert.deepEqual(calls.assets, []);
        assertNoCache(calls);
      }));
    }
  }
}

for (const prefix of ['/data/', '/r2/data/']) {
  const path = `${prefix}a-stock-all.json`;
  test(`historical ${path} still serves cache hit at original 3600`, () => fixture(async ({ calls, fetchPath }) => {
    const response = await fetchPath(path + '?v=synthetic');
    assert.equal(await response.text(), stale);
    assert.equal(response.headers.get('Cache-Control'), 'public, max-age=3600');
    assert.equal(response.headers.get('Access-Control-Allow-Origin'), '*');
    assert.deepEqual(calls.match, [ORIGIN + path], 'historical cache key still strips query');
    assert.deepEqual(calls.get, []);
    assert.deepEqual(calls.put, []);
  }));
  test(`historical ${path} still caches R2 miss response at original 3600`, () => fixture(async ({ calls, fetchPath }) => {
    const response = await fetchPath(path);
    assert.equal(await response.text(), fresh);
    assert.equal(response.headers.get('Cache-Control'), 'public, max-age=3600');
    assert.deepEqual(calls.get, ['data/a-stock-all.json']);
    await Promise.all(calls.pending);
    assert.deepEqual(calls.put, [{ url: ORIGIN + path, body: fresh, cc: 'public, max-age=3600' }]);
  }, { cacheHit: false }));
}

for (const path of ['/r2/fund_nav/fixture.json', '/r2/nav_bucket/00.json']) {
  test(`existing ${path} keeps bypass and no-store`, () => fixture(async ({ calls, fetchPath }) => {
    const response = await fetchPath(path);
    assert.equal(await response.text(), fresh);
    assert.equal(response.headers.get('Cache-Control'), 'no-store, max-age=0');
    assert.equal(response.headers.get('Access-Control-Allow-Origin'), '*');
    assert.deepEqual(calls.get, [path.slice(4)]);
    assertNoCache(calls);
  }));
}

for (const mode of ['missing', 'error']) {
  test(`bootstrap R2 alias ${mode} does not serve stale cache or assets`, () => fixture(async ({ calls, fetchPath }) => {
    const response = await fetchPath('/r2/data/boot.json');
    assert.equal(response.status, mode === 'missing' ? 404 : 502);
    assert.notEqual(await response.text(), stale);
    assert.deepEqual(calls.get, ['data/boot.json']);
    assert.deepEqual(calls.assets, []);
    assertNoCache(calls);
  }, { r2: mode }));
  test(`bootstrap canonical ${mode} preserves ASSETS fallback without caching`, () => fixture(async ({ calls, fetchPath }) => {
    const response = await fetchPath('/data/boot.json');
    assert.equal(response.status, 200);
    assert.equal(await response.text(), 'synthetic asset fallback');
    assert.equal(response.headers.get('Cache-Control'), 'no-store, max-age=0');
    assert.equal(response.headers.get('Access-Control-Allow-Origin'), '*');
    assert.deepEqual(calls.assets, [ORIGIN + '/data/boot.json']);
    assertNoCache(calls);
  }, { r2: mode }));
}
