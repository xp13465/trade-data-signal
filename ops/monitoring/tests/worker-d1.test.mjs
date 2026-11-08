import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { Miniflare, convertV4MiniflareOptions } from 'miniflare';
import handler, { opsScheduled } from '../../../worker/ops.js';

test('actual local Miniflare D1: migration, atomic concurrency, watchdog, CAS and backup', { timeout: 30000 }, async () => {
  const mf = new Miniflare(convertV4MiniflareOptions({ modules: true, compatibilityDate: '2026-11-07',
    script: 'export default { fetch() { return new Response("local D1 fixture only"); } }',
    d1Databases: { OPS_DB: 'ops-isolated-fixture' } }));
  try {
    const db = await mf.getD1Database('OPS_DB');
    // D1.exec separates statements by line; prepare each complete migration unit,
    // preserving CREATE TRIGGER bodies as one SQLite statement.
    const dir = new URL('../migrations/', import.meta.url);
    const sql = readdirSync(dir).filter(f => f.endsWith('.sql')).sort().map(f => readFileSync(new URL(f, dir), 'utf8')).join('\n');
    let unit = ''; let trigger = false;
    for (const raw of sql.split('\n')) {
      const line = raw.trim(); if (!line || line.startsWith('--')) continue;
      if (/^CREATE TRIGGER/.test(line)) trigger = true;
      unit += raw + '\n';
      if ((!trigger && line.endsWith(';')) || (trigger && line === 'END;')) {
        await db.prepare(unit).run(); unit = ''; trigger = false;
      }
    }
    assert.equal(unit, '');
    const env = { OPS_DB: db, OPS_INGEST_TOKEN: 'd1-fixture-ingest', OPS_ADMIN_TOKEN: 'd1-fixture-admin', OPS_ALERT_ENABLED: 'false' };
    const now = Date.now();
    async function scheduleAt(wallTime, scheduledTime = wallTime) {
      // Simulate execution time itself; scheduledTime is not a freshness clock.
      const realNow = Date.now; Date.now = () => wallTime;
      try { await opsScheduled({ scheduledTime }, env, {}); } finally { Date.now = realNow; }
    }
    async function call(path, value, role = value ? 'ingest' : 'admin', headers = {}) {
      const auth = role === 'ingest' ? { Authorization: 'Bearer d1-fixture-ingest' } : { 'X-Ops-Admin-Token': 'd1-fixture-admin' };
      const response = await handler(new Request('https://fixture.invalid/api/ops' + path, { method: value ? 'POST' : 'GET',
        headers: { 'Content-Type': 'application/json', ...auth, ...headers }, body: value ? JSON.stringify(value) : undefined }), env, {});
      return { status: response.status, body: await response.json() };
    }
    const snapshot = (status, offset) => { const at = new Date(now + offset).toISOString(); return {
      schema_version: 1, snapshot_id: crypto.randomUUID(), collector_id: 'd1-fixture', collected_at: at, code_ref: 'unknown', duration_ms: 1,
      coverage: { counts: { checks: 1 }, limitations: ['Local D1 fixture only'] },
      checks: [{ id: 'service:test', name: 'Local fixture', category: 'service', status, observed_at: at, summary: 'Synthetic observation', evidence: { value: status } }],
    }; };
    // Three real D1 cron transactions before any successful upload.
    await scheduleAt(now - 31 * 60000);
    assert.equal((await call('/state')).body.watchdog.status, 'unknown');
    await scheduleAt(now - 16 * 60000);
    assert.equal((await call('/state')).body.bootstrap_overdue, false);
    await scheduleAt(now);
    assert.equal((await call('/state')).body.bootstrap_overdue, true);
    assert.equal((await call('/state')).body.collector_status, 'unknown');
    const s = snapshot('critical', 0);
    const concurrent = await Promise.all([call('/ingest', s), call('/ingest', s)]);
    assert.deepEqual(concurrent.map(r => r.status), [200, 200]);
    assert.equal((await call('/events')).body.events.filter(e => e.source === 'd1-fixture').length, 1);
    assert.equal((await call('/state')).body.watchdog.status, 'fresh');
    assert.equal((await call('/state')).body.bootstrap_overdue, false);
    const oldObservation = snapshot('ok', 500);
    oldObservation.checks[0].observed_at = new Date(now - 1000).toISOString();
    oldObservation.checks[0].evidence = { value: 'older_ok' };
    assert.equal((await call('/ingest', oldObservation)).status, 200);
    const protectedState = (await call('/state')).body;
    assert.equal(protectedState.latest.checks[0].status, 'critical');
    assert.equal(protectedState.counts.critical, 1);
    assert.equal(protectedState.latest.checks[0].evidence.value, 'critical');
    assert.equal(protectedState.latest.checks[0].current_snapshot_id, s.snapshot_id);
    const wrong = structuredClone(s); wrong.checks[0].status = 'ok'; assert.equal((await call('/ingest', wrong)).status, 409);
    const newer = snapshot('ok', 1000); assert.equal((await call('/ingest', newer)).status, 200);
    assert.equal((await call('/ingest', snapshot('critical', -1000))).status, 200);
    assert.equal((await call('/state')).body.latest.snapshot_id, newer.snapshot_id);
    const item = (await call('/incidents')).body.incidents[0];
    const update = { expected_revision: 0, workflow_status: 'investigating', root_cause_state: 'unknown', remediation_state: 'pending',
      deployment_state: 'pending', verification_state: 'pending', observation_status: 'pending', note: 'Fixture only', evidence_url: '' };
    const path = '/incidents/' + encodeURIComponent(item.id);
    const edits = await Promise.all([call(path, update, 'admin', { 'X-Ops-Intent': 'update' }), call(path, update, 'admin', { 'X-Ops-Intent': 'update' })]);
    assert.deepEqual(edits.map(r => r.status).sort(), [200, 409]);
    assert.equal((await call('/incidents')).body.revisions.length, 1);
    await scheduleAt(now + 1900000);
    assert.equal((await call('/events')).body.events.filter(e => e.source === 'watchdog' && e.status === 'stale').length, 2);
    const recoveryCount = (await call('/events')).body.events.filter(e => e.source === 'watchdog' && e.kind === 'recovery').length;
    await scheduleAt(now + 1900000, now + 600000);
    assert.equal((await call('/state')).body.watchdog.status, 'stale');
    assert.equal((await call('/events')).body.events.filter(e => e.source === 'watchdog' && e.kind === 'recovery').length, recoveryCount);
    await scheduleAt(now + 32 * 86400000);
    assert.equal((await call('/state')).body.latest.snapshot_id, newer.snapshot_id);
    const backup = await call('/export'); assert.equal(backup.status, 200); assert.equal(backup.body.runs.length, 1);
  } finally { await mf.dispose(); }
});
