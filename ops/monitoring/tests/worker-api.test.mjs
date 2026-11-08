import test from 'node:test';
import assert from 'node:assert/strict';
import { DatabaseSync } from 'node:sqlite';
import { readFileSync, readdirSync } from 'node:fs';
import { createHmac } from 'node:crypto';
import handler, { opsScheduled } from '../../../worker/ops.js';
import BASELINE from '../../../worker/ops_baseline.js';
import authHandler, { getAdminUsers } from '../../../worker/auth.js';

// Real SQLite/JSON1/triggers/transactions, adapted to the documented D1 API.
// Separate Miniflare test verifies the real D1 binding; no remote credentials.
const migrationDir = new URL('../migrations/', import.meta.url);
const migration = readdirSync(migrationDir).filter(f => f.endsWith('.sql')).sort().map(f => readFileSync(new URL(f, migrationDir), 'utf8')).join('\n');
class SQLiteD1 {
  constructor(schema = migration) { this.sql = new DatabaseSync(':memory:'); this.sql.exec(schema); }
  withSession(mode) { assert.equal(mode, 'first-primary'); return this; }
  prepare(query) {
    const db = this.sql;
    function statement(args = []) {
      return {
        bind(...values) { return statement(values); },
        async first(column) { const row = db.prepare(query).get(...args); return row ? (column ? row[column] : { ...row }) : null; },
        all() { return { success: true, results: db.prepare(query).all(...args).map(r => ({ ...r })) }; },
        async run() { const meta = db.prepare(query).run(...args); return { success: true, results: [], meta }; },
      };
    }
    return statement();
  }
  async batch(stmts) {
    this.sql.exec('BEGIN IMMEDIATE');
    try { const rows = []; for (const s of stmts) rows.push(s.all()); this.sql.exec('COMMIT'); return rows; }
    catch (e) { this.sql.exec('ROLLBACK'); throw e; }
  }
}
const keys = { OPS_INGEST_TOKEN: 'fixture-ingest-only-0123456789', OPS_ADMIN_TOKEN: 'fixture-bootstrap-only-0123456789', SESSION_SECRET: 'fixture-session-secret', ADMIN_USERS: 'fixture:admin', OPS_ALERT_ENABLED: 'false' };
function session(uid, provider = 'fixture') {
  const body = Buffer.from(JSON.stringify({ provider, provider_uid: uid, user_id: uid, exp: Math.floor(Date.now() / 1000) + 3600 })).toString('base64url');
  return body + '.' + createHmac('sha256', keys.SESSION_SECRET).update(body).digest('base64url');
}
async function fixture(run, schema = migration) {
  const db = new SQLiteD1(schema); const realNow = Date.now; const realFetch = globalThis.fetch;
  let now = Date.UTC(2026, 10, 7, 10, 0); Date.now = () => now;
  globalThis.fetch = async () => { throw new Error('NETWORK_FORBIDDEN'); };
  const env = { ...keys, OPS_DB: db };
  const f = {
    db, env, advance(ms) { now += ms; }, now() { return now; },
    snapshot(status = 'ok', extra = {}) {
      const ts = new Date(now).toISOString();
      return { schema_version: 1, snapshot_id: crypto.randomUUID(), collector_id: 'fixture', collected_at: ts, code_ref: 'unknown', duration_ms: 20,
        coverage: { counts: { checked: 1 }, limitations: ['Fixture only'] }, checks: [
          { id: 'service:fixture', name: 'Fixture service', category: 'service', status, observed_at: ts, summary: 'Synthetic observation', evidence: { result: status, count: 1 } },
        ], ...extra };
    },
    async call(path = '/state', { role = 'admin', value, headers = {}, method = value === undefined ? 'GET' : 'POST', bindings = env } = {}) {
      const h = { 'Content-Type': 'application/json', ...headers };
      if (role === 'admin') h['X-Ops-Admin-Token'] = keys.OPS_ADMIN_TOKEN;
      if (role === 'ingest') h.Authorization = 'Bearer ' + keys.OPS_INGEST_TOKEN;
      if (role === 'member' || role === 'session') h.Cookie = 'session=' + session(role === 'session' ? 'admin' : 'member');
      const req = new Request('https://example.invalid/api/ops' + path, { method, headers: h, body: value === undefined ? undefined : typeof value === 'string' ? value : JSON.stringify(value) });
      const res = await handler(req, bindings, {});
      const result = await res.json();
      assert.match(res.headers.get('Cache-Control'), /no-store/); assert.equal(res.headers.get('Access-Control-Allow-Origin'), null);
      return { status: res.status, body: result };
    },
    async push(s) { return this.call('/ingest', { role: 'ingest', value: s }); },
    async scheduled() { await opsScheduled({ scheduledTime: now }, env, {}); },
  };
  try { await run(f); } finally { Date.now = realNow; globalThis.fetch = realFetch; db.sql.close(); }
}

test('auth fails closed: member/ingest denied, strict provider UID and separate bootstrap', () => fixture(async f => {
  for (const role of [null, 'member', 'ingest']) assert.ok([401, 403].includes((await f.call('/state', { role })).status));
  assert.equal((await f.call('/state', { role: 'session' })).status, 200);
  f.env.ADMIN_USERS = 'admin'; assert.notEqual((await f.call('/state', { role: 'session' })).status, 200);
  f.env.ADMIN_USERS = 'other:admin'; assert.equal((await f.call('/state', { role: 'session' })).status, 403);
  assert.equal((await f.call('/state', { bindings: {} })).status, 503);
  assert.equal((await f.call('/state', { bindings: { ...f.env, OPS_INGEST_TOKEN: keys.OPS_ADMIN_TOKEN } })).status, 503);
  assert.equal((await f.call('/ingest', { value: f.snapshot() })).status, 403);
  for (const path of ['/state', '/knowledge', '/incidents', '/export', '/events', '/history']) assert.equal((await f.call(path, { role: 'ingest' })).status, 403);
}));

// Both handlers consume the same signed cookie; auth.me also resolves its KV user.
async function assertAdminParity(f, provider, uid, allowed, name = 'Synthetic user') {
  const cookie = 'session=' + session(uid, provider);
  const users = new Map([[`user:${provider}:${uid}`, JSON.stringify({
    id: `fixture-${uid}`, provider, provider_uid: uid, name, avatar: '',
  })]]);
  const bindings = { ...f.env, SUBSCRIBE_KV: { async get(key) { return users.get(key) ?? null; } } };
  const me = await authHandler(new Request('https://example.invalid/api/auth/me', {
    headers: { Cookie: cookie },
  }), bindings);
  assert.equal(me.status, 200);
  const body = await me.json();
  assert.equal(body.logged_in, true);
  assert.equal(body.user.is_admin, allowed, `${provider}:${uid} auth.me`);
  const ops = await f.call('/state', { role: null, headers: { Cookie: cookie }, bindings });
  if (allowed) assert.equal(ops.status, 200, `${provider}:${uid} ops`);
  else assert.ok([401, 403, 503].includes(ops.status), `${provider}:${uid} denied: ${ops.status}`);
}

test('legacy and supplemental administrators share exact auth.me/ops authorization', () => fixture(async f => {
  f.env.ADMIN_USERS = ' fixture:admin, github:700001 ';
  f.env.ADMIN_USERS_ADDITIONS = ' github:700002, , github:700003 ';
  assert.deepEqual(getAdminUsers(f.env), ['fixture:admin', 'github:700001', 'github:700002', 'github:700003']);
  await f.push(f.snapshot());
  for (const uid of ['700001', '700002', '700003']) await assertAdminParity(f, 'github', uid, true);
  await assertAdminParity(f, 'fixture', 'admin', true);
  for (const [provider, uid, name] of [
    ['github', '700004', '700002'], // Display name cannot substitute for provider UID.
    ['gitee', '700002', 'Synthetic user'],
    ['github', '0700002', 'Synthetic user'],
    ['github', '7000020', 'Synthetic user'],
    ['github', 'fixture-admin-login', 'Synthetic user'],
  ]) await assertAdminParity(f, provider, uid, false, name);
}));

test('ADDITIONS-only works without changing legacy secret and never authorizes ingest', () => fixture(async f => {
  delete f.env.ADMIN_USERS;
  f.env.ADMIN_USERS_ADDITIONS = ' github:700002 ';
  await assertAdminParity(f, 'github', '700002', true);
  const before = f.db.sql.prepare('SELECT COUNT(*) n FROM ops_runs').get().n;
  assert.equal((await f.call('/ingest', {
    role: null, headers: { Cookie: 'session=' + session('700002', 'github') }, value: f.snapshot(),
  })).status, 403);
  assert.equal(f.db.sql.prepare('SELECT COUNT(*) n FROM ops_runs').get().n, before);
  assert.equal((await f.push(f.snapshot())).status, 200);
  assert.equal((await f.call('/state', { role: 'ingest' })).status, 403);
}));

test('malformed allowlist values fail closed independently in both bindings', () => fixture(async f => {
  const malformed = [undefined, null, 700002, true, ['github:700002'],
    { identity: 'github:700002' }, '', '700002', 'github:', ':700002',
    'github:700002:extra', 'github:700002/extra', 'github:700002\nextra'];
  for (const field of ['ADMIN_USERS', 'ADMIN_USERS_ADDITIONS']) {
    for (const value of malformed) {
      delete f.env.ADMIN_USERS; delete f.env.ADMIN_USERS_ADDITIONS;
      f.env[field] = value;
      assert.deepEqual(getAdminUsers(f.env), []);
      await assertAdminParity(f, 'github', '700002', false);
    }
  }
  // A bad supplement cannot discard valid existing administrators (or vice versa).
  f.env.ADMIN_USERS = 'github:700001'; f.env.ADMIN_USERS_ADDITIONS = ['github:700002'];
  await assertAdminParity(f, 'github', '700001', true);
  await assertAdminParity(f, 'github', '700002', false);
  f.env.ADMIN_USERS = {}; f.env.ADMIN_USERS_ADDITIONS = 'github:700002';
  await assertAdminParity(f, 'github', '700002', true);
}));

test('bounded/strict JSON: chunked oversize, stale/future, unsafe scalar evidence, baseline injection', () => fixture(async f => {
  assert.equal((await f.call('/ingest', { role: 'ingest', value: ' '.repeat(270000) })).status, 413);
  for (const offset of [-1800001, 120001]) {
    const s = f.snapshot(); s.collected_at = new Date(f.now() + offset).toISOString(); assert.equal((await f.push(s)).status, 400);
  }
  for (const evidence of [{ path: 'fixture' }, { result: '/tmp/private.json' }, { result: { nested: 'bad' } }, { result: 'a@example.invalid' }]) {
    const s = f.snapshot(); s.checks[0].evidence = evidence; assert.equal((await f.push(s)).status, 400);
  }
  assert.equal((await f.push({ ...f.snapshot(), baseline: {} })).status, 400);
  const extra = f.snapshot(); extra.limitations = []; assert.equal((await f.push(extra)).status, 400);
  const duplicate = f.snapshot(); duplicate.checks.push(duplicate.checks[0]); assert.equal((await f.push(duplicate)).status, 400);
  for (const field of ['snapshot_id', 'collector_id', 'code_ref']) {
    const s = f.snapshot(); s[field] = [s[field]]; assert.equal((await f.push(s)).status, 400);
  }
}));

test('snapshot idempotency/conflict and ordering preserve atomic events and latest', () => fixture(async f => {
  const first = f.snapshot(); assert.equal((await f.push(first)).status, 200);
  assert.equal((await f.call('/events')).body.events.length, 0);
  f.advance(1000); const bad = f.snapshot('critical'); assert.equal((await f.push(bad)).status, 200);
  assert.equal((await f.push(bad)).status, 200);
  const change = structuredClone(bad); change.checks[0].status = 'ok'; assert.equal((await f.push(change)).status, 409);
  assert.equal((await f.call('/events')).body.events.length, 1);
  const old = f.snapshot('ok', { collected_at: new Date(f.now() - 60000).toISOString() });
  assert.equal((await f.push(old)).status, 200);
  assert.equal((await f.call('/state')).body.latest.snapshot_id, bad.snapshot_id);
  assert.equal((await f.call('/events')).body.events.length, 1);
  assert.equal((await f.call('/history')).body.runs.length, 3);
}));

test('storage diagnostics whitelist causes and correlate without reflecting private text', () => fixture(async f => {
  const original = f.db.batch;
  const originalLog = console.error; const logs = [];
  console.error = value => logs.push(value);
  try {
    for (const [message, kind] of [
      ['D1_ERROR: Network connection lost.', 'storage_transient'],
      ["D1_ERROR: Your account has exceeded D1's free tier daily row write limit.", 'storage_quota'],
      ['D1_ERROR: no such table: private_table', 'storage_configuration'],
      ['NOT NULL constraint failed: ops_runs.content_hash', 'storage_constraint'],
      ['D1 DB is overloaded. Too many requests queued.', 'storage_overloaded'],
      ['D1 DB exceeded its CPU time limit and was reset.', 'storage_resource_limit'],
      ["D1 DB's isolate exceeded its memory limit and was reset.", 'storage_resource_limit'],
      ['D1 query result exceeded the maximum response size limit of 50 MB', 'storage_resource_limit'],
      ['Worker exceeded its CPU time limit', 'unknown'],
      ['Worker exceeded its memory limit', 'unknown'],
      ['Worker exceeded resource limits', 'unknown'],
      ['Memory limit would be exceeded before EOF', 'unknown'],
      ['Bearer injected-private /home/private SQL SELECT secret=bad', 'unknown'],
    ]) {
      f.db.batch = async () => { throw new Error(message, { cause: new Error('Bearer injected-private') }); };
      const s = f.snapshot(); const result = await f.push(s);
      assert.equal(result.status, 503); assert.equal(result.body.error_kind, kind);
      assert.equal(result.body.snapshot_id, s.snapshot_id);
      assert.match(result.body.request_id, /^[a-f0-9-]{36}$/);
      assert.equal(logs.at(-1).request_id, result.body.request_id);
      assert.equal(logs.at(-1).error_kind, kind);
      assert.deepEqual(Object.keys(logs.at(-1)).sort(), ['error', 'error_kind', 'event', 'request_id', 'snapshot_id']);
      assert.ok(!JSON.stringify([result, logs]).includes('injected-private'));
      assert.ok(!JSON.stringify([result, logs]).includes('private_table'));
    }
  } finally { console.error = originalLog; f.db.batch = original; }
}));

test('failed diagnostic read retains original batch cause; real schema failure is safe', () => fixture(async f => {
  const batch = f.db.batch; const prepare = f.db.prepare;
  const log = console.error; const logs = []; console.error = value => logs.push(value);
  try {
    f.db.batch = async () => { throw new Error('D1_ERROR', { cause: new Error('Network connection lost.') }); };
    f.db.prepare = query => {
      if (query.includes('SELECT content_hash')) throw new Error('Bearer injected-private');
      return prepare.call(f.db, query);
    };
    assert.equal((await f.push(f.snapshot())).body.error_kind, 'storage_transient');
    f.db.batch = batch; f.db.prepare = prepare;
    f.db.sql.exec('DROP TABLE ops_runs');
    const result = await f.push(f.snapshot());
    assert.equal(result.status, 503); assert.equal(result.body.error_kind, 'storage_configuration');
    assert.ok(!JSON.stringify([result, logs]).includes('injected-private'));
    assert.ok(!JSON.stringify([result, logs]).includes('no such table'));
  } finally { console.error = log; f.db.batch = batch; f.db.prepare = prepare; }
}));

test('OPS-R1 newer envelope cannot wash persistent critical status/evidence with an older ok observation', () => fixture(async f => {
  const first = f.snapshot('critical');
  first.checks[0].evidence = { marker: 'newer_critical_evidence' };
  first.checks[0].summary = 'Current critical observation';
  await f.push(first); f.advance(1000);
  const old = f.snapshot('ok'); old.checks[0].observed_at = new Date(f.now() - 2000).toISOString();
  old.checks[0].evidence = { marker: 'older_ok_evidence' };
  assert.equal((await f.push(old)).status, 200);
  const current = (await f.call('/state')).body;
  assert.equal(current.latest.snapshot_id, old.snapshot_id);
  assert.equal(current.latest.checks[0].status, 'critical');
  assert.equal(current.counts.critical, 1); assert.equal(current.counts.ok, 0);
  assert.deepEqual(current.latest.checks[0].evidence, first.checks[0].evidence);
  assert.equal(current.latest.checks[0].observed_at, first.checks[0].observed_at);
  assert.equal(current.latest.checks[0].current_snapshot_id, first.snapshot_id);
  assert.equal(current.events.filter(e => e.kind === 'recovery').length, 0);
  f.advance(1000); const recovery = f.snapshot('ok'); await f.push(recovery);
  const after = (await f.call('/state')).body;
  assert.equal(after.latest.checks[0].status, 'ok');
  assert.equal(after.latest.checks[0].current_snapshot_id, recovery.snapshot_id);
  assert.equal(after.events.filter(e => e.kind === 'recovery').length, 1);
}));

test('OPS-R1 migration backfills the previously elected critical observation, not the newer raw ok envelope', () => {
  const oldSchema = readdirSync(migrationDir).filter(f => /^000[12]_.*\.sql$/.test(f)).sort().map(f => readFileSync(new URL(f, migrationDir), 'utf8')).join('\n');
  return fixture(async f => {
    const critical = f.snapshot('critical'); critical.checks[0].evidence = { marker: 'before_migration' };
    await f.push(critical); f.advance(1000);
    const old = f.snapshot('ok'); old.checks[0].observed_at = new Date(f.now() - 2000).toISOString(); await f.push(old);
    f.db.sql.exec(readFileSync(new URL('0003_check_observation.sql', migrationDir), 'utf8'));
    const state = (await f.call('/state')).body;
    assert.equal(state.latest.checks[0].status, 'critical'); assert.equal(state.counts.ok, 0);
    assert.deepEqual(state.latest.checks[0].evidence, { marker: 'before_migration' });
    assert.equal(state.latest.checks[0].current_snapshot_id, critical.snapshot_id);
  }, oldSchema);
});

test('OPS-R2 continuing warning to critical preserves the sole unsent episode alert in explicit all scope', () => fixture(async f => {
  Object.assign(f.env, { OPS_ALERT_SCOPE: 'all', OPS_ALERT_ENABLED: 'true', OPS_ALERT_WEBHOOK: 'https://open.feishu.cn/open-apis/bot/v2/hook/fixture-hook-1234567890' });
  await f.push(f.snapshot('warning')); f.advance(1000); await f.push(f.snapshot('critical'));
  let sends = 0; globalThis.fetch = async () => { sends++; return Response.json({ code: 0 }); };
  await f.scheduled();
  const rows = f.db.sql.prepare('SELECT * FROM ops_outbox').all();
  assert.equal(rows.length, 1); assert.equal(rows[0].status, 'sent'); assert.equal(rows[0].attempts, 1); assert.equal(sends, 1);
  assert.equal(f.db.sql.prepare('SELECT status,problem_open FROM ops_check_state').get().status, 'critical');
  await f.scheduled(); assert.equal(sends, 1);
  f.advance(1000); await f.push(f.snapshot('ok')); await f.scheduled(); assert.equal(sends, 2);
}));

test('OPS-R3 delayed older scheduledTime cannot recover an unchanged stale collector or send a recovery', () => fixture(async f => {
  Object.assign(f.env, { OPS_ALERT_SCOPE: 'watchdog', OPS_ALERT_ENABLED: 'true', OPS_ALERT_WEBHOOK: 'https://open.feishu.cn/open-apis/bot/v2/hook/fixture-hook-1234567890' });
  const sent = []; globalThis.fetch = async (_url, options) => { sent.push(JSON.parse(options.body).content.text); return Response.json({ code: 0 }); };
  const first = f.snapshot(); const initial = f.now(); await f.push(first);
  f.advance(1801000); await f.scheduled();
  const changed = f.db.sql.prepare('SELECT changed_ms FROM ops_watchdog').get().changed_ms;
  await opsScheduled({ scheduledTime: initial + 600000 }, f.env, {});
  const current = (await f.call('/state')).body;
  assert.equal(current.collector_status, 'stale'); assert.equal(current.watchdog.status, 'stale');
  assert.equal(current.latest.snapshot_id, first.snapshot_id);
  assert.equal(f.db.sql.prepare('SELECT changed_ms FROM ops_watchdog').get().changed_ms, changed);
  assert.equal(current.events.filter(e => e.source === 'watchdog' && e.kind === 'recovery').length, 0);
  assert.equal(sent.length, 1); assert.ok(sent.every(t => !t.startsWith('【恢复】')));
  f.advance(1000); await f.push(f.snapshot()); await f.scheduled();
  assert.equal((await f.call('/state')).body.watchdog.status, 'fresh'); assert.equal(sent.length, 2);
}));

test('same open problem unknown/critical and downgrade do not page; recovery exactly one transition', () => fixture(async f => {
  await f.push(f.snapshot('critical'));
  for (const status of ['unknown', 'critical', 'warning', 'ok', 'ok']) { f.advance(1000); await f.push(f.snapshot(status)); }
  const events = (await f.call('/events')).body.events;
  assert.equal(events.filter(e => e.kind === 'alert').length, 1);
  assert.equal(events.filter(e => e.kind === 'recovery').length, 1);
  assert.equal(f.db.sql.prepare('SELECT problem_open FROM ops_check_state').get().problem_open, 0);
  assert.equal(f.db.sql.prepare('SELECT COUNT(*) n FROM ops_outbox').get().n, 2);
}));

test('new envelope with stale/future checks stays unknown; omission preserves problem and exposes missing', () => fixture(async f => {
  await f.push(f.snapshot('critical')); f.advance(1000);
  const missing = f.snapshot('ok', { checks: [], coverage: { counts: { checked: 0 }, limitations: ['Missing check'] } });
  assert.equal((await f.push(missing)).status, 200);
  let state = (await f.call('/state')).body;
  assert.equal(state.collector_status, 'fresh'); assert.equal(state.missing_checks.length, 1);
  assert.equal(state.missing_checks[0].problem_open, true); assert.equal(state.missing_checks[0].status, 'unknown');
  for (const offset of [-1900000, 1000000]) {
    f.advance(1000); const s = f.snapshot(); s.checks[0].observed_at = new Date(f.now() + offset).toISOString(); await f.push(s);
    state = (await f.call('/state')).body; assert.equal(state.latest.checks[0].status, 'unknown');
    assert.equal(f.db.sql.prepare('SELECT problem_open FROM ops_check_state').get().problem_open, 1);
  }
  assert.equal((await f.call('/events')).body.events.filter(e => e.kind === 'recovery').length, 0);
}));

test('cron uses wall clock independently; no snapshot unknown, stale once, fresh recovery', () => fixture(async f => {
  await f.scheduled(); assert.equal((await f.call('/state')).body.collector_status, 'unknown');
  await f.push(f.snapshot()); f.advance(1801000);
  await f.scheduled(); await f.scheduled();
  let events = (await f.call('/events')).body.events;
  assert.equal(events.filter(e => e.source === 'watchdog' && e.kind === 'alert').length, 1);
  await f.push(f.snapshot()); events = (await f.call('/events')).body.events;
  assert.equal(events.filter(e => e.source === 'watchdog' && e.kind === 'recovery').length, 1);
}));

test('no first snapshot across three cron ticks: durable grace then one overdue alert and first-upload recovery', () => fixture(async f => {
  Object.assign(f.env, { OPS_ALERT_ENABLED: 'true', OPS_ALERT_WEBHOOK: 'https://open.feishu.cn/open-apis/bot/v2/hook/fixture-hook-1234567890' });
  let sends = 0; globalThis.fetch = async () => { sends++; return Response.json({ code: 0 }); };
  const started = f.now();
  await f.scheduled();
  let state = (await f.call('/state')).body;
  assert.equal(state.watchdog.status, 'unknown'); assert.equal(state.bootstrap_overdue, false);
  assert.equal(state.watchdog.first_seen_at, new Date(started).toISOString());
  f.advance(15 * 60000); await f.scheduled();
  state = (await f.call('/state')).body;
  assert.equal(state.watchdog.status, 'unknown'); assert.equal(sends, 0);
  f.advance(16 * 60000); await f.scheduled();
  state = (await f.call('/state')).body;
  assert.equal(state.collector_status, 'unknown'); assert.equal(state.latest, null);
  assert.equal(state.bootstrap_overdue, true); assert.equal(state.watchdog.status, 'stale'); assert.equal(sends, 1);
  f.advance(5 * 60000); await f.scheduled(); assert.equal(sends, 1);
  assert.equal(f.db.sql.prepare('SELECT first_seen_ms FROM ops_watchdog').get().first_seen_ms, started);
  await f.push(f.snapshot()); await f.scheduled();
  state = (await f.call('/state')).body;
  assert.equal(state.watchdog.status, 'fresh'); assert.equal(state.collector_status, 'fresh'); assert.equal(state.bootstrap_overdue, false);
  assert.equal(sends, 2);
  const events = (await f.call('/events')).body.events.filter(e => e.source === 'watchdog');
  assert.equal(events.filter(e => e.kind === 'alert').length, 1);
  assert.equal(events.filter(e => e.kind === 'recovery').length, 1);
}));

test('fake watchdog transport positively exposes Chinese alert/recovery and honest delivery caveats', () => fixture(async f => {
  Object.assign(f.env, { OPS_ALERT_ENABLED: 'true', OPS_ALERT_WEBHOOK: 'https://open.feishu.cn/open-apis/bot/v2/hook/fixture-hook-1234567890' });
  const bodies = [];
  globalThis.fetch = async (_url, options) => { bodies.push(JSON.parse(options.body)); return Response.json({ code: 0 }); };
  await f.push(f.snapshot()); f.advance(1801000); await f.scheduled();
  assert.equal(bodies.length, 1); assert.equal(bodies[0].msg_type, 'text');
  assert.match(bodies[0].content.text, /^【告警】采集链超过30分钟未收到采样/);
  assert.match(bodies[0].content.text, /当前业务状态仍待核实/);
  f.advance(1000); await f.push(f.snapshot()); await f.scheduled();
  assert.equal(bodies.length, 2);
  assert.match(bodies[1].content.text, /^【恢复】采集链已恢复采样/);
  assert.match(bodies[1].content.text, /只代表重新收到采样，不等于业务故障已根治/);
  const events = (await f.call('/events')).body.events.filter(e => e.source === 'watchdog');
  for (const body of bodies) {
    assert.match(body.content.text, /事件编号：[a-f0-9]{32}/);
    assert.match(body.content.text, /回执超时，重试可能重复送达/);
    assert.ok(events.some(e => body.content.text.includes(e.event_id) && e.delivery_status === 'sent'));
    assert.doesNotMatch(body.content.text, /Operations |delivery may repeat/);
  }
}));

test('retention keeps last complete head evidence beyond30d, prunes other payloads/summaries', () => fixture(async f => {
  const a = f.snapshot(); await f.push(a); f.advance(1000); const b = f.snapshot('warning'); await f.push(b);
  f.advance(2 * 86400000); await f.scheduled();
  assert.equal(f.db.sql.prepare('SELECT snapshot_json FROM ops_runs WHERE snapshot_id=?').get(a.snapshot_id).snapshot_json, null);
  assert.ok(f.db.sql.prepare('SELECT snapshot_json FROM ops_runs WHERE snapshot_id=?').get(b.snapshot_id).snapshot_json);
  f.advance(31 * 86400000); await f.scheduled();
  assert.equal((await f.call('/history')).body.runs.length, 1);
  const state = (await f.call('/state')).body;
  assert.equal(state.latest.snapshot_id, b.snapshot_id); assert.equal(state.collector_status, 'stale'); assert.equal(state.latest.checks[0].status, 'unknown');
}));

function updateValue(revision = 0) { return { expected_revision: revision, workflow_status: '观察中', root_cause_state: 'unknown', remediation_state: 'fixture', deployment_state: 'not_deployed', verification_state: 'pending', observation_status: 'pending', note: 'Local fixture only', evidence_url: '' }; }
test('manual overrides optimistic CAS/audit, complete immutable baseline issues, no auto closure or CSRF', () => fixture(async f => {
  const before = (await f.call('/incidents')).body;
  assert.deepEqual(before.incidents.map(i => i.id).sort(), BASELINE.records.filter(r => r.kind === 'incident').map(r => r.id).sort());
  const item = before.incidents[0]; const path = '/incidents/' + encodeURIComponent(item.id); const headers = { 'X-Ops-Intent': 'update', Origin: 'https://example.invalid' };
  assert.equal((await f.call(path, { role: 'ingest', value: updateValue(), headers })).status, 403);
  assert.equal((await f.call(path, { role: 'session', value: updateValue(), headers: { ...headers, Origin: 'https://evil.invalid' } })).status, 403);
  assert.equal((await f.call(path, { value: updateValue(), headers })).status, 200);
  assert.equal((await f.call(path, { value: updateValue(), headers })).status, 409);
  const close = { ...updateValue(1), workflow_status: 'closed' };
  assert.equal((await f.call(path, { value: close, headers })).status, 400);
  assert.equal((await f.call(path, { value: { ...close, verification_state: 'verified', observation_status: 'observed', evidence_url: 'https://example.invalid/evidence' }, headers })).status, 200);
  const after = (await f.call('/incidents')).body; const edited = after.incidents.find(i => i.id === item.id);
  assert.deepEqual(edited.baseline, item.baseline); assert.equal(edited.revision, 2); assert.equal(after.revisions.length, 2);
  await f.push(f.snapshot('ok')); assert.equal((await f.call('/incidents')).body.incidents.find(i => i.id === item.id).revision, 2);
}));

test('outbox disabled history stays disabled on enable; no real fetch', () => fixture(async f => {
  f.env.OPS_ALERT_SCOPE = 'all';
  await f.push(f.snapshot('critical'));
  assert.equal(f.db.sql.prepare('SELECT status FROM ops_outbox').get().status, 'disabled');
  Object.assign(f.env, { OPS_ALERT_SCOPE: 'all', OPS_ALERT_ENABLED: 'true', OPS_ALERT_WEBHOOK: 'https://open.feishu.cn/open-apis/bot/v2/hook/fixture-hook-1234567890' });
  let sends = 0; globalThis.fetch = async () => { sends++; return Response.json({ code: 0 }); };
  await f.scheduled(); assert.equal(sends, 0);
}));

test('default watchdog scope records two same-root service/timer faults without duplicate direct pages', () => fixture(async f => {
  Object.assign(f.env, { OPS_ALERT_ENABLED: 'true', OPS_ALERT_WEBHOOK: 'https://open.feishu.cn/open-apis/bot/v2/hook/fixture-hook-1234567890' });
  const s = f.snapshot('critical');
  s.checks[0].id = 'service:turnover';
  s.checks.push({ ...s.checks[0], id: 'timer:turnover', category: 'timer', status: 'warning' });
  s.coverage.counts.checked = 2;
  let sends = 0; globalThis.fetch = async () => { sends++; return Response.json({ code: 0 }); };
  assert.equal((await f.push(s)).status, 200);
  const state = (await f.call('/state')).body;
  assert.equal(state.latest.checks.length, 2); assert.equal(state.counts.critical, 1); assert.equal(state.counts.warning, 1);
  const business = (await f.call('/events')).body.events;
  assert.equal(business.length, 2);
  for (const event of business) {
    assert.equal(event.delivery_status, 'suppressed');
    assert.equal(event.last_error, 'existing_alert_chain_owns_business_paging');
  }
  await f.scheduled(); assert.equal(sends, 0);
  // Independent collector loss still pages exactly once through the new chain.
  f.advance(1801000); await f.scheduled(); await f.scheduled(); assert.equal(sends, 1);
  const sent = f.db.sql.prepare("SELECT e.source FROM ops_outbox o JOIN ops_events e ON e.event_id=o.event_id WHERE o.status='sent'").all();
  assert.deepEqual(sent.map(r => r.source), ['watchdog']);
}));

test('disabled default still suppresses business; scope all is explicit and never replays suppression', () => fixture(async f => {
  await f.push(f.snapshot('critical'));
  assert.equal(f.db.sql.prepare('SELECT status,last_error FROM ops_outbox').get().status, 'suppressed');
  assert.equal(f.db.sql.prepare('SELECT status,last_error FROM ops_outbox').get().last_error, 'existing_alert_chain_owns_business_paging');
  let sends = 0; globalThis.fetch = async () => { sends++; return Response.json({ code: 0 }); };
  Object.assign(f.env, { OPS_ALERT_SCOPE: 'all', OPS_ALERT_ENABLED: 'true', OPS_ALERT_WEBHOOK: 'https://open.feishu.cn/open-apis/bot/v2/hook/fixture-hook-1234567890' });
  await f.scheduled(); assert.equal(sends, 0);
  f.advance(1000); await f.push(f.snapshot('ok')); await f.scheduled(); assert.equal(sends, 1);
}));

test('invalid alert scope fails closed and ingest cannot forge the reserved watchdog source', () => fixture(async f => {
  let sends = 0; globalThis.fetch = async () => { sends++; return Response.json({ code: 0 }); };
  const spoof = f.snapshot('critical', { collector_id: 'watchdog' });
  assert.equal((await f.push(spoof)).status, 400);
  Object.assign(f.env, { OPS_ALERT_ENABLED: 'true', OPS_ALERT_WEBHOOK: 'https://open.feishu.cn/open-apis/bot/v2/hook/fixture-hook-1234567890' });
  for (const scope of ['', 'ALL', 'business', true]) {
    f.env.OPS_ALERT_SCOPE = scope;
    f.advance(1000); await f.push(f.snapshot('critical'));
    f.advance(1801000); await f.scheduled(); assert.equal(sends, 0);
  }
  const disabled = f.db.sql.prepare("SELECT * FROM ops_outbox WHERE status='disabled'").all();
  assert.ok(disabled.length); assert.ok(disabled.every(x => x.last_error === 'invalid_alert_scope'));
}));

test('outbox leases avoid concurrent send; future retry bounded; expiry/supersession suppressed', () => fixture(async f => {
  Object.assign(f.env, { OPS_ALERT_SCOPE: 'all', OPS_ALERT_ENABLED: 'true', OPS_ALERT_WEBHOOK: 'https://open.feishu.cn/open-apis/bot/v2/hook/fixture-hook-1234567890' });
  await f.push(f.snapshot('critical')); let sends = 0;
  globalThis.fetch = async () => { sends++; await new Promise(resolve => setTimeout(resolve, 5)); return Response.json({ code: 0 }); };
  await Promise.all([f.scheduled(), f.scheduled()]); assert.equal(sends, 1);
  assert.equal(f.db.sql.prepare('SELECT status FROM ops_outbox').get().status, 'sent');
  // Separate problem episode: failure then recovery before send suppresses failure.
  f.advance(1000); await f.push(f.snapshot('ok')); f.advance(1000); await f.push(f.snapshot('critical'));
  await f.scheduled(); assert.equal(sends, 2);
  assert.ok(f.db.sql.prepare("SELECT COUNT(*) n FROM ops_outbox WHERE status='suppressed'").get().n >= 1);
  f.advance(1000); await f.push(f.snapshot('ok')); f.advance(3600001); await f.scheduled();
  assert.equal(sends, 3); // only new watchdog stale alert; old recovery was suppressed
}));

test('outbox delivery errors persist bounded retry status; rejected host never fetched', () => fixture(async f => {
  Object.assign(f.env, { OPS_ALERT_SCOPE: 'all', OPS_ALERT_ENABLED: 'true', OPS_ALERT_WEBHOOK: 'https://open.feishu.cn/open-apis/bot/v2/hook/fixture-hook-1234567890' });
  await f.push(f.snapshot('critical')); let sends = 0;
  globalThis.fetch = async () => { sends++; return Response.json({ code: 123 }); };
  for (let i = 0; i < 6; i++) { await f.scheduled(); f.advance(3600000); }
  const outbox = f.db.sql.prepare("SELECT * FROM ops_outbox WHERE event_id=(SELECT event_id FROM ops_events WHERE source='fixture' AND kind='alert' LIMIT 1)").get();
  // Old delivery becomes suppressed instead of an obsolete alert after1h.
  assert.ok(['pending', 'suppressed', 'failed'].includes(outbox.status)); assert.ok(outbox.attempts <= 5);
  f.env.OPS_ALERT_WEBHOOK = 'https://attacker.invalid/open-apis/bot/v2/hook/fixture-hook-1234567890';
  const before = sends; await f.scheduled(); assert.equal(sends, before);
}));

test('outbox stops after five real attempts while observations remain current', () => fixture(async f => {
  Object.assign(f.env, { OPS_ALERT_SCOPE: 'all', OPS_ALERT_ENABLED: 'true', OPS_ALERT_WEBHOOK: 'https://open.feishu.cn/open-apis/bot/v2/hook/fixture-hook-1234567890' });
  let sends = 0; globalThis.fetch = async () => { sends++; throw new Error('Ambiguous fake timeout'); };
  await f.push(f.snapshot('critical'));
  for (const step of [0, 120000, 240000, 480000, 960000]) {
    f.advance(step); await f.push(f.snapshot('critical')); await f.scheduled();
  }
  assert.equal(sends, 5);
  assert.equal(f.db.sql.prepare('SELECT status FROM ops_outbox').get().status, 'failed');
  f.advance(120000); await f.push(f.snapshot('critical')); await f.scheduled(); assert.equal(sends, 5);
  assert.equal((await f.call('/events')).body.events.filter(e => e.kind === 'alert').length, 1);
}));

test('delayed cron cannot backdate delivery lease or defer ready outbox work', () => fixture(async f => {
  Object.assign(f.env, { OPS_ALERT_SCOPE: 'all', OPS_ALERT_ENABLED: 'true', OPS_ALERT_WEBHOOK: 'https://open.feishu.cn/open-apis/bot/v2/hook/fixture-hook-1234567890' });
  await f.push(f.snapshot('critical')); let calls = 0;
  globalThis.fetch = async () => {
    calls++;
    assert.equal(f.db.sql.prepare("SELECT lease_until_ms FROM ops_outbox WHERE status='sending'").get().lease_until_ms, f.now() + 60000);
    return Response.json({ code: 0 });
  };
  await opsScheduled({ scheduledTime: f.now() - 120000 }, f.env, {});
  assert.equal(calls, 1);
}));

test('export streams private retained database plus all nine sanitized baseline inventories', () => fixture(async f => {
  await f.push(f.snapshot('warning'));
  const exported = await f.call('/export'); assert.equal(exported.status, 200);
  assert.equal(exported.body.runs.length, 1); assert.equal(exported.body.baseline.records.length, BASELINE.records.length);
  const knowledge = (await f.call('/knowledge')).body;
  assert.ok(knowledge.records.length >= 368);
  assert.doesNotMatch(JSON.stringify(knowledge), /\/(?:tmp|Users|home\/ubuntu)\//);
  assert.ok(knowledge.records.some(r => r.kind === 'incident'));
  assert.equal((await f.call('/history?limit=99999')).status, 400);
}));
