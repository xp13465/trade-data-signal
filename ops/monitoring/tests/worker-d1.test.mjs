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
    // The actual D1 binding must enforce invocation recovery inside its write
    // transaction even when the newer failure commits after a request has read
    // policy and before that request starts its batch.
    const severe = (status, inv, offset, start) => {
      const v=snapshot(status,offset),c=v.checks[0];c.id='cloud-service:trade-overfit-monitor.service';
      c.evidence={execution_state:status==='ok'?'completed':'failed',unit_result:status==='ok'?'success':'exit-code',
        exit_code:status==='ok'?0:124,invocation_id:inv.repeat(32),
        last_start_utc:new Date(now+start).toISOString(),last_exit_utc:c.observed_at};return v;
    };
    await call('/ingest',severe('critical','a',2000,1900));
    const candidate=severe('ok','b',4000,2100), failure=severe('critical','c',3000,2200);
    let intercepted=false,release,entered;
    const paused=new Promise(resolve=>entered=resolve),resume=new Promise(resolve=>release=resolve);
    env.OPS_DB={prepare:db.prepare.bind(db),batch:db.batch.bind(db),withSession(mode){const session=db.withSession(mode);return {
      prepare:session.prepare.bind(session),async batch(statements){
        if(!intercepted){intercepted=true;entered();await resume;}
        return session.batch(statements);
      }
    };}};
    const pending=call('/ingest',candidate);await paused;
    assert.equal((await call('/ingest',failure)).status,200);release();
    assert.equal((await pending).body.counts.ok,0);env.OPS_DB=db;
    assert.equal((await call('/state')).body.latest.checks[0].problem_open,true);
    const recovered=severe('ok','d',5000,4500);
    const recoveredAck=await call('/ingest',recovered);assert.equal(recoveredAck.status,200);
    assert.equal((await call('/state')).body.latest.checks[0].problem_open,false);
    const replays=await Promise.all([call('/ingest',recovered),call('/ingest',recovered),call('/ingest',failure)]);
    assert.ok(replays.every(r=>r.status===200));
    assert.equal(replays[0].body.received_at,recoveredAck.body.received_at);
    assert.equal((await call('/state')).body.latest.checks[0].problem_open,false);
    // Independent review negatives, using actual D1 JSON types and both IDs.
    let offset=6000;
    for(const id of ['cloud-service:trade-public-fund-daily.service','cloud-service:trade-overfit-monitor.service']){
      const noProof=severe('ok','a',offset,offset-100);noProof.checks[0].id=id;noProof.checks[0].evidence={};
      assert.equal((await call('/ingest',noProof)).body.counts.ok,0);
      offset+=1000;
      const critical=severe('critical','a',offset,offset-100);critical.checks[0].id=id;await call('/ingest',critical);
      offset+=1000;
      const warning=severe('warning','b',offset,offset-100);warning.checks[0].id=id;delete warning.checks[0].evidence.execution_state;await call('/ingest',warning);
      offset+=1000;
      const stale=severe('ok','c',offset,offset-1500);stale.checks[0].id=id;
      assert.equal((await call('/ingest',stale)).body.counts.ok,0);
      const typed=severe('ok','d',offset+100,offset+50);typed.checks[0].id=id;typed.checks[0].evidence.exit_code=false;
      assert.equal((await call('/ingest',typed)).body.counts.ok,0);
      assert.equal((await call('/state')).body.latest.checks[0].problem_open,true);
      offset+=1000;
    }
    // Real D1 exception/cause formatting must never leak SQL or injected text.
    await db.prepare("CREATE TRIGGER ops_fixture_failure BEFORE INSERT ON ops_runs BEGIN SELECT RAISE(ABORT, 'Bearer injected-private /home/private'); END").run();
    const originalLog = console.error; const safeLogs = []; console.error = value => safeLogs.push(value);
    try {
      const rejected = await call('/ingest', snapshot('critical', 0));
      // RAISE(ABORT) is a real SQLITE_CONSTRAINT in D1, even with private text.
      assert.equal(rejected.status, 503); assert.equal(rejected.body.error_kind, 'storage_constraint');
      assert.ok(!JSON.stringify([rejected, safeLogs]).includes('injected-private'));
      assert.equal(safeLogs[0].request_id, rejected.body.request_id);
    } finally { console.error = originalLog; }
  } finally { await mf.dispose(); }
});
