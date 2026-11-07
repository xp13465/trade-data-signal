import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const code = fs.readFileSync(new URL('../../../static-site/sw.js', import.meta.url), 'utf8');
function runtime(offline = false) {
  const handlers = {};
  const calls = [];
  const context = {
    self: { location: { origin: 'https://example.invalid' }, addEventListener(type, fn) { handlers[type] = fn; } },
    URL, Request, Response, Headers, console, Promise,
    fetch(req, options) { calls.push(options); return offline ? Promise.reject(new Error('offline fixture')) : Promise.resolve(new Response('network-only')); },
    caches: new Proxy({}, { get() { throw new Error('Private operations must never read/write browser caches'); } }),
  };
  vm.runInNewContext(code, context);
  return { handlers, calls };
}
for (const path of ['/api/ops/state','/api/ops/export','/admin/ops.html','/admin/ops.js?v=new','/admin/ops.css']) {
  test(`private route ${path} bypasses SW storage`, async () => {
    const {handlers,calls}=runtime(); let result;
    handlers.fetch({ request: {method:'GET',url:'https://example.invalid'+path,mode:'navigate'}, respondWith(p) {result=p;} });
    assert.equal(await (await result).text(),'network-only');
    assert.equal(calls[0].cache,'no-store');
  });
}
test('offline operations never fall back to stale private content',async()=>{
  const {handlers}=runtime(true);let result;
  handlers.fetch({request:{method:'GET',url:'https://example.invalid/api/ops/state'},respondWith(p){result=p;}});
  await assert.rejects(result,/offline fixture/);
});
