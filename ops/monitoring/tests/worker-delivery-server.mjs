// Loopback-only fault injector around the real handler and real SQLite triggers.
import http from 'node:http';
import { DatabaseSync } from 'node:sqlite';
import { readFileSync, readdirSync } from 'node:fs';
import { createHash } from 'node:crypto';
import handler from '../../../worker/ops.js';

const mode = process.argv[2];
const db = new DatabaseSync(':memory:');
const dir = new URL('../migrations/', import.meta.url);
for (const f of readdirSync(dir).filter(f => f.endsWith('.sql')).sort()) db.exec(readFileSync(new URL(f, dir), 'utf8'));
const binding = {
  withSession() { return this; },
  prepare(sql) {
    function statement(args = []) { return {
      bind(...values) { return statement(values); },
      async first() {
        if (mode === 'headfail' && attempts.length === 1 && sql.includes('SELECT (SELECT snapshot_id')) throw new Error('D1_ERROR: Network connection lost.');
        return db.prepare(sql).get(...args) ?? null;
      },
      async all() { return { success: true, results: db.prepare(sql).all(...args) }; },
    }; }
    return statement();
  },
  async batch(stmts) {
    db.exec('BEGIN IMMEDIATE');
    try { const rows = []; for (const s of stmts) rows.push(await s.all()); db.exec('COMMIT'); return rows; }
    catch (e) { db.exec('ROLLBACK'); throw e; }
  },
};
const attempts = [];
const server = http.createServer(async (req, res) => {
  if (req.url === '/test-state') {
    const count = table => db.prepare(`SELECT COUNT(*) n FROM ${table}`).get().n;
    res.end(JSON.stringify({ attempts, runs: count('ops_runs'), events: count('ops_events'), outbox: count('ops_outbox') })); return;
  }
  const chunks = []; for await (const chunk of req) chunks.push(chunk);
  const raw = Buffer.concat(chunks);
  attempts.push({ hash: createHash('sha256').update(raw).digest('hex'), id: JSON.parse(raw).snapshot_id });
  if (mode === 'hang' || (mode === 'timeoutfirst' && attempts.length === 1)) return;
  if (mode === 'slow503') await new Promise(resolve => setTimeout(resolve, 2800));
  if (['503first', 'always503', 'slow503', 'malicious', 'quota', 'config', 'constraint', 'overloaded', 'resource_limit', '400', '401', '403', '409', '500', '502first', '504first'].includes(mode) && (!mode.endsWith('first') || attempts.length === 1)) {
    res.statusCode = /^\d{3}$/.test(mode) ? Number(mode) : mode === '502first' ? 502 : mode === '504first' ? 504 : 503;
    res.end(JSON.stringify(mode === 'malicious' ? { error: 'Bearer injected-private /home/private SQL SELECT', error_kind: 'secret=unsafe' }
      : mode === 'quota' ? { error: 'ops_storage_unavailable', error_kind: 'storage_quota' }
      : mode === 'config' ? { error: 'ingest_not_configured', error_kind: 'configuration' }
      : ['constraint', 'overloaded', 'resource_limit'].includes(mode) ? { error: 'ops_storage_unavailable', error_kind: 'storage_' + mode }
      : { error: 'ops_storage_unavailable', error_kind: 'unknown' })); return;
  }
  const response = await handler(new Request('https://fixture.invalid/api/ops/ingest', {
    method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: req.headers.authorization || '' }, body: raw,
  }), { OPS_DB: binding, OPS_INGEST_TOKEN: 'fixture-token-0123456789', OPS_ALERT_ENABLED: 'false' }, {});
  if (mode === 'dropfirst' && attempts.length === 1) { req.socket.destroy(); return; }
  res.statusCode = response.status;
  res.end(mode === 'badack' ? JSON.stringify({ accepted: true, snapshot_id: 'wrong-id' })
    : mode === 'invalidjson' ? 'Bearer injected-private'
    : mode === 'duplicateack' ? `{"accepted":true,"accepted":false,"snapshot_id":"${JSON.parse(raw).snapshot_id}"}`
    : mode === 'hugeack' ? 'x'.repeat(4097) : await response.text());
});
server.listen(0, '127.0.0.1', () => process.stdout.write(JSON.stringify({ port: server.address().port }) + '\n'));
