// Dedicated private operations API. See ops/monitoring/contract.md.
// D1 batch + triggers (0001_ops.sql) atomically persist runs/transitions/outbox.
// Official API: developers.cloudflare.com/d1/worker-api/d1-database/
import { getAdminUsers, getSessionUser } from './auth.js';
import BASELINE from './ops_baseline.js';
import { benefitStatements, benefitRunStatement, benefitsConfigured, benefitsRetain, benefitsRoute, benefitsExportTables } from './ops_benefits.js';

const BODY_LIMIT = 256 * 1024;
// 2 倍采集周期(15min cron→30min stale 阈值):留 15min 余量吸收 cron 抖动+冷启动,
// 避免采样年龄逼近周期即误判 stale。2026-11-08 随采集频率 5→15min 上调。
const AGE_MS = 1800000;
const FUTURE_MS = 120000;
const DAY = 86400000;
const MAX_ATTEMPTS = 5;
const enc = new TextEncoder();
const CATEGORIES = new Set(['service', 'timer', 'data', 'publication', 'backup', 'resource', 'monitor']);
const STATUSES = new Set(['ok', 'warning', 'critical', 'unknown']);
const UPDATE_FIELDS = ['expected_revision', 'workflow_status', 'root_cause_state', 'remediation_state', 'deployment_state', 'verification_state', 'observation_status', 'note', 'evidence_url'];

class OpsError extends Error {
  constructor(status, code, kind) { super(code); this.status = status; this.code = code; this.kind = kind; }
}
function storageErrorKind(error) {
  // Inspect bounded text only to select literal categories. Never log the text,
  // cause, SQL, stack, request headers or bindings, even on unknown failures.
  const messages = [error?.message, error?.cause?.message].filter(v => typeof v === 'string').map(v => v.slice(0, 2048));
  const message = messages.join(' ');
  if (/maximum account storage limit|Exceeded maximum DB size|free tier daily row (?:read|write) limit/i.test(message)) return 'storage_quota';
  if (/D1_TYPE_ERROR|D1_COLUMN_NOTFOUND|no such (?:table|column)|No SQL statements detected/i.test(message)) return 'storage_configuration';
  if (/SQLITE_CONSTRAINT|(?:NOT NULL|UNIQUE|FOREIGN KEY|CHECK) constraint failed/i.test(message)) return 'storage_constraint';
  if (/D1 DB is overloaded/i.test(message)) return 'storage_overloaded';
  // Worker CPU/memory termination and D1 limits are different failure domains.
  // Require the documented D1 identity; generic resource text stays unknown.
  if (/D1 DB(?:'s isolate)? exceeded its (?:CPU time|memory) limit|D1 query result exceeded the maximum response size limit/i.test(message)) return 'storage_resource_limit';
  if (/Network connection lost\.|Replica disconnected from primary\.|Cannot resolve D1 DB due to transient issue on remote node\.|D1 DB reset because its code was updated\.|Internal error (?:while starting up|in) D1 DB storage caused object to be reset\./.test(message)) return 'storage_transient';
  return 'unknown';
}
function fail(status, code) { throw new OpsError(status, code); }
function response(body, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: {
    'Content-Type': 'application/json; charset=utf-8',
    'Cache-Control': 'no-store', 'Pragma': 'no-cache',
    'X-Content-Type-Options': 'nosniff', 'Cross-Origin-Resource-Policy': 'same-origin',
    'Vary': 'Cookie, Authorization, X-Ops-Admin-Token',
  } });
}
function object(v) { return v !== null && typeof v === 'object' && !Array.isArray(v); }
function exactKeys(v, keys) {
  if (!object(v) || Object.keys(v).some(k => !keys.includes(k))) fail(400, 'invalid_fields');
}
function text(v, max, empty = false) {
  if (typeof v !== 'string' || v.length > max || (!empty && !v.trim()) || /[\x00-\x08\x0b\x0c\x0e-\x1f]/.test(v)) fail(400, 'invalid_text');
  return v;
}
function safeText(v, max, empty = false) {
  text(v, max, empty);
  if (/(?:\/(?:tmp|private|Users|home|root|etc|var)\/|[A-Za-z]:\\|\.env\b|Bearer\s+\S+|https?:\/\/|-----BEGIN|[\w.+-]+@[\w.-]+\.[a-z]{2,}|(?:token|password|secret|webhook)\s*[:=])/i.test(v)) fail(400, 'unsafe_text');
  return v;
}
function integer(v, max = Number.MAX_SAFE_INTEGER) {
  if (!Number.isSafeInteger(v) || v < 0 || v > max) fail(400, 'invalid_integer');
  return v;
}
function utc(v) {
  if (typeof v !== 'string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$/.test(v) || !Number.isFinite(Date.parse(v))) fail(400, 'invalid_utc_time');
  const ms = Date.parse(v);
  if (new Date(ms).toISOString().slice(0, 19) !== v.slice(0, 19)) fail(400, 'invalid_utc_time');
  return ms;
}
function canonical(v) {
  if (Array.isArray(v)) return '[' + v.map(canonical).join(',') + ']';
  if (object(v)) return '{' + Object.keys(v).sort().map(k => JSON.stringify(k) + ':' + canonical(v[k])).join(',') + '}';
  return JSON.stringify(v);
}
async function digest(value) { return new Uint8Array(await crypto.subtle.digest('SHA-256', enc.encode(value))); }
async function sameSecret(actual, expected) {
  if (typeof actual !== 'string' || !actual || typeof expected !== 'string' || !expected || actual.length > 4096) return false;
  const [a, b] = await Promise.all([digest(actual), digest(expected)]);
  if (typeof crypto.subtle.timingSafeEqual === 'function') return crypto.subtle.timingSafeEqual(a, b);
  let diff = 0; for (let n = 0; n < a.length; n++) diff |= a[n] ^ b[n];
  return diff === 0;
}
function bearer(request) { return /^Bearer (\S+)$/i.exec(request.headers.get('Authorization') || '')?.[1] || ''; }
function binding(env) {
  if (!env.OPS_DB || typeof env.OPS_DB.prepare !== 'function' || typeof env.OPS_DB.batch !== 'function') fail(503, 'ops_storage_unavailable');
  // Primary-anchored sessions avoid replica lag for auth-adjacent revision/current reads.
  return typeof env.OPS_DB.withSession === 'function' ? env.OPS_DB.withSession('first-primary') : env.OPS_DB;
}
async function admin(request, env) {
  if (env.OPS_ADMIN_TOKEN && env.OPS_INGEST_TOKEN && await sameSecret(env.OPS_ADMIN_TOKEN, env.OPS_INGEST_TOKEN)) fail(503, 'ops_token_configuration_invalid');
  if (await sameSecret(bearer(request), env.OPS_INGEST_TOKEN)) fail(403, 'ingest_has_no_viewer_privilege');
  const token = request.headers.get('X-Ops-Admin-Token');
  if (token) {
    if (!await sameSecret(token, env.OPS_ADMIN_TOKEN)) fail(403, 'admin_required');
    return { actor: 'bootstrap-admin', session: false };
  }
  const allow = getAdminUsers(env);
  if (!allow.length) fail(env.OPS_ADMIN_TOKEN ? 401 : 503, env.OPS_ADMIN_TOKEN ? 'admin_required' : 'admin_not_configured');
  let user; try { user = await getSessionUser(request, env); } catch { fail(503, 'session_service_unavailable'); }
  if (!user) fail(401, 'admin_required');
  const identity = `${user.provider}:${user.providerUid}`;
  if (!allow.includes(identity)) fail(403, 'admin_required');
  return { actor: identity, session: true };
}
async function body(request) {
  if (request.headers.get('Content-Type')?.split(';')[0].trim().toLowerCase() !== 'application/json') fail(415, 'json_required');
  if (request.headers.get('Content-Encoding') && request.headers.get('Content-Encoding') !== 'identity') fail(415, 'content_encoding_unsupported');
  const len = request.headers.get('Content-Length');
  if (len && (!/^\d+$/.test(len) || Number(len) > BODY_LIMIT)) fail(413, 'body_too_large');
  if (!request.body) fail(400, 'body_required');
  const reader = request.body.getReader(); const parts = []; let total = 0;
  try {
    while (true) {
      const { done, value } = await reader.read(); if (done) break;
      total += value.byteLength;
      if (total > BODY_LIMIT) { await reader.cancel(); fail(413, 'body_too_large'); }
      parts.push(value);
    }
  } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(total); let at = 0;
  for (const part of parts) { bytes.set(part, at); at += part.byteLength; }
  try { return JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes)); } catch { fail(400, 'invalid_json'); }
}
function validateSnapshot(input, now) {
  exactKeys(input, ['schema_version', 'snapshot_id', 'collector_id', 'collected_at', 'code_ref', 'duration_ms', 'coverage', 'checks']);
  if (input.schema_version !== 1 || typeof input.snapshot_id !== 'string' || !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(input.snapshot_id)) fail(400, 'invalid_snapshot_id');
  // Reserved server source must never be forgeable by an ingest caller.
  if (typeof input.collector_id !== 'string' || input.collector_id === 'watchdog' || !/^[a-z0-9_-]{1,48}$/.test(input.collector_id)) fail(400, 'invalid_collector_id');
  if (typeof input.code_ref !== 'string' || (input.code_ref !== 'unknown' && !/^[a-f0-9]{40}$/.test(input.code_ref))) fail(400, 'invalid_code_ref');
  const collected = utc(input.collected_at);
  if (collected > now + FUTURE_MS || collected < now - AGE_MS) fail(400, 'snapshot_outside_time_window');
  integer(input.duration_ms, DAY);
  if (!Array.isArray(input.checks) || input.checks.length > 250) fail(400, 'invalid_checks');
  if (!object(input.coverage)) fail(400, 'invalid_coverage');
  exactKeys(input.coverage, ['counts', 'limitations']);
  const coverageCounts = input.coverage.counts;
  const limitations = input.coverage.limitations;
  if (!object(coverageCounts) || Object.keys(coverageCounts).length > 30 || !Array.isArray(limitations) || limitations.length > 20) fail(400, 'invalid_coverage');
  for (const [key, value] of Object.entries(coverageCounts)) { safeText(key, 64); integer(value); }
  for (const limitation of limitations) safeText(limitation, 400);
  const ids = new Set(); const counts = { ok: 0, warning: 0, critical: 0, unknown: 0 };
  const checks = input.checks.map(c => {
    exactKeys(c, ['id', 'name', 'category', 'status', 'observed_at', 'summary', 'evidence']);
    if (typeof c.id !== 'string' || !/^[a-zA-Z0-9:._-]{1,120}$/.test(c.id) || ids.has(c.id)) fail(400, 'invalid_check_id');
    ids.add(c.id); safeText(c.name, 160); safeText(c.summary, 400, true);
    if (!CATEGORIES.has(c.category) || !STATUSES.has(c.status)) fail(400, 'invalid_check_status');
    const observed = utc(c.observed_at);
    if (!object(c.evidence) || Object.keys(c.evidence).length > 20) fail(400, 'invalid_evidence');
    for (const [key, value] of Object.entries(c.evidence)) {
      if (!/^[A-Za-z][A-Za-z0-9_]{0,63}$/.test(key) || /(token|secret|password|credential|authorization|cookie|argv|env|path|log|email|webhook|stack)/i.test(key)) fail(400, 'unsafe_evidence_key');
      if (typeof value === 'string') { safeText(value, 400, true); if (/[\\/]/.test(value)) fail(400, 'evidence_paths_forbidden'); }
      else if (value !== null && typeof value !== 'boolean' && !(typeof value === 'number' && Number.isFinite(value))) fail(400, 'evidence_must_be_scalar');
    }
    const reason = observed > now + FUTURE_MS || observed > collected + FUTURE_MS ? 'future_observation' : observed < now - AGE_MS ? 'stale_observation' : 'observed';
    const nonReal = c.id.startsWith('benefit:') && (c.evidence.record_kind !== 'delivery_v1' || c.evidence.measurement_kind !== 'real');
    const businessExpired = c.id.startsWith('business:') && (!c.evidence.valid_until || !Number.isFinite(Date.parse(c.evidence.valid_until)) || Date.parse(c.evidence.valid_until) <= now);
    const status = reason === 'observed' && !nonReal && !businessExpired ? c.status : 'unknown'; counts[status]++;
    return { ...c, status, reported_status: c.status, observation_status: reason, _observed_ms: Math.min(observed, collected) };
  });
  return { snapshot: { ...input, checks }, counts, collected };
}
function stmt(db, sql, ...args) { return args.length ? db.prepare(sql).bind(...args) : db.prepare(sql); }
async function ingest(request, env, db, now, diagnostic) {
  if (!env.OPS_INGEST_TOKEN) fail(503, 'ingest_not_configured');
  if (env.OPS_ADMIN_TOKEN && await sameSecret(env.OPS_ADMIN_TOKEN, env.OPS_INGEST_TOKEN)) fail(503, 'ops_token_configuration_invalid');
  if (!await sameSecret(bearer(request), env.OPS_INGEST_TOKEN)) fail(403, 'ingest_required');
  const input = await body(request);
  // Hash the raw accepted input, before normalization; DB state cannot affect it.
  const hash = Array.from(await digest(canonical(input)), b => b.toString(16).padStart(2, '0')).join('');
  const { snapshot, counts, collected } = validateSnapshot(structuredClone(input), now);
  diagnostic.snapshot_id = snapshot.snapshot_id;
  let policy;
  try { policy = await stmt(db, 'SELECT version FROM ops_recovery_policy WHERE id=1').first(); }
  catch { throw new OpsError(503, 'ops_recovery_migration_required', 'storage_configuration'); }
  if (policy?.version !== 1) throw new OpsError(503, 'ops_recovery_migration_required', 'storage_configuration');
  // A conflicting replay fails a NOT NULL constraint inside the atomic batch.
  // Same-content duplicates perform no INSERT trigger/current-state work.
  try {
    const statements = [stmt(db, `INSERT INTO ops_runs VALUES(?,?,?,?,?,?,?,?)
      ON CONFLICT(snapshot_id) DO UPDATE SET content_hash=CASE WHEN ops_runs.content_hash=excluded.content_hash THEN ops_runs.content_hash ELSE NULL END`,
    snapshot.snapshot_id, hash, snapshot.collector_id, collected, now, snapshot.duration_ms, JSON.stringify(counts), JSON.stringify(snapshot))];
    let benefitWork = [];
    try {
      benefitWork = await benefitStatements(db, env, snapshot, now);
      if (benefitWork.length) statements.splice(0, 1, ...benefitWork, benefitRunStatement(db, snapshot, hash, collected, now));
    } catch { benefitWork = []; /* Optional measurement must not break ingest. */ }
    statements.push(...outboxPolicyStatements(db, env, now));
    try { await db.batch(statements); }
    catch (error) {
      if (!benefitWork.length) throw error;
      // D1 batches roll back on failure. Retry the original atomic ops transaction.
      const fallback = { ...snapshot, checks: snapshot.checks.map(c => c.id.startsWith('benefit:') ? { ...c, status: 'unknown', observation_status: 'measurement_storage_unavailable' } : c) };
      const fallbackCounts = { ok: 0, warning: 0, critical: 0, unknown: 0 };
      for (const check of fallback.checks) fallbackCounts[check.status]++;
      await db.batch([stmt(db, `INSERT INTO ops_runs VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(snapshot_id) DO UPDATE SET content_hash=CASE WHEN ops_runs.content_hash=excluded.content_hash THEN ops_runs.content_hash ELSE NULL END`, snapshot.snapshot_id, hash, snapshot.collector_id, collected, now, snapshot.duration_ms, JSON.stringify(fallbackCounts), JSON.stringify(fallback)), ...outboxPolicyStatements(db, env, now)]);
    }
  } catch (error) {
    let prior;
    try { prior = await stmt(db, 'SELECT content_hash FROM ops_runs WHERE snapshot_id=?', snapshot.snapshot_id).first(); }
    catch { /* Keep the original batch failure category if diagnosis also fails. */ }
    if (prior && prior.content_hash !== hash) fail(409, 'snapshot_id_conflict');
    throw new OpsError(503, 'ops_storage_unavailable', storageErrorKind(error));
  }
  const head = await stmt(db, 'SELECT (SELECT snapshot_id FROM ops_head WHERE id=1) snapshot_id,counts_json,received_ms FROM ops_runs WHERE snapshot_id=?', snapshot.snapshot_id).first();
  return response({ accepted: true, snapshot_id: snapshot.snapshot_id, ack_state: 'confirmed', received_at: iso(head?.received_ms), current: head?.snapshot_id === snapshot.snapshot_id, counts: head?.counts_json ? JSON.parse(head.counts_json) : counts });
}
function boundedLimit(url, defaultValue = 50) {
  const raw = url.searchParams.get('limit');
  if (raw === null) return defaultValue;
  if (!/^\d+$/.test(raw) || Number(raw) < 1 || Number(raw) > 200) fail(400, 'invalid_limit');
  return Number(raw);
}
function iso(ms) { return ms === null || ms === undefined ? null : new Date(ms).toISOString(); }
const EVENT_SQL = `SELECT e.*,o.status delivery_status,o.attempts,o.last_error,o.next_attempt_ms,o.delivered_ms
  FROM ops_events e LEFT JOIN ops_outbox o ON o.event_id=e.event_id`;
function eventRow(r) { return { ...r, created_at: iso(r.created_ms), next_attempt_at: iso(r.next_attempt_ms), delivered_at: iso(r.delivered_ms) }; }
async function events(db, limit) { return (await stmt(db, EVENT_SQL + ' ORDER BY e.created_ms DESC,e.event_id DESC LIMIT ?', limit).all()).results.map(eventRow); }
async function state(db, now) {
  const results = await db.batch([
    stmt(db, 'SELECT h.collected_ms,r.snapshot_json,r.snapshot_id,r.received_ms FROM ops_head h LEFT JOIN ops_runs r ON r.snapshot_id=h.snapshot_id WHERE h.id=1'),
    stmt(db, 'SELECT * FROM ops_check_state ORDER BY updated_ms DESC,collector_id,check_id LIMIT 501'),
    stmt(db, 'SELECT COUNT(*) total FROM ops_check_state'),
    stmt(db, 'SELECT status,COUNT(*) total FROM ops_outbox GROUP BY status'),
    stmt(db, 'SELECT status,changed_ms,first_seen_ms FROM ops_watchdog WHERE id=1'),
  ]);
  const head = results[0].results[0]; const latest = head?.snapshot_json ? JSON.parse(head.snapshot_json) : null;
  if (latest) latest.received_at = iso(head.received_ms);
  const freshness = !head ? 'unknown' : now - head.collected_ms > AGE_MS ? 'stale' : 'fresh';
  const persisted = new Map(results[1].results.map(c => [`${c.collector_id}:${c.check_id}`, c]));
  if (latest) latest.checks = latest.checks.map(c => {
    const current = persisted.get(`${latest.collector_id}:${c.id}`);
    if (!current) return { ...c, status: 'unknown', observation_status: 'current_state_unavailable' };
    // The existing SQL clock is authoritative for both status AND provenance.
    // A newer envelope can contain an older observation; never reuse its ok or
    // evidence when SQL deliberately retained a newer critical observation.
    const proof = current.observation_json ? JSON.parse(current.observation_json) : null;
    const stale = now - current.observed_ms > AGE_MS || (c.id.startsWith('business:') && (!proof?.evidence?.valid_until || Date.parse(proof.evidence.valid_until) <= now));
    const retained = current.snapshot_id !== latest.snapshot_id;
    return { ...(proof || { id: c.id, category: c.category }), name: current.name,
      status: stale ? 'unknown' : current.status, summary: current.summary,
      evidence: proof?.evidence || {}, observed_at: proof?.observed_at || iso(current.observed_ms),
      _observed_ms: current.observed_ms, current_snapshot_id: current.snapshot_id, problem_open: !!current.problem_open,
      observation_status: stale ? 'stale_observation' : !proof ? 'current_evidence_unavailable' : retained ? 'retained_current_observation' : proof.observation_status,
      ...(retained ? { received_observation: { snapshot_id: latest.snapshot_id, observed_at: c.observed_at,
        reported_status: c.reported_status, status: c.status } } : {}),
    };
  });
  const present = new Set(latest?.checks.map(c => `${latest.collector_id}:${c.id}`) || []);
  const prior = results[1].results.slice(0, 500).filter(c => !present.has(`${c.collector_id}:${c.check_id}`)).map(c => ({
    id: c.check_id, collector_id: c.collector_id, name: c.name, status: 'unknown',
    previous_status: c.status, problem_open: !!c.problem_open, observed_at: iso(c.observed_ms),
    observation_status: c.collected_ms === head?.collected_ms ? 'missing_from_latest' : 'not_in_latest_coverage',
    summary: 'Not present in latest snapshot coverage; not a recovery',
  }));
  const counts = { ok: 0, warning: 0, critical: 0, unknown: prior.length };
  for (const c of latest?.checks || []) counts[c.status]++;
  const watchdog = results[4].results[0];
  const bootstrapOverdue = !head && watchdog?.status === 'stale';
  return { schema_version: 1, server_time: iso(now), latest, collector_status: freshness, counts,
    bootstrap_overdue: bootstrapOverdue,
    watchdog: watchdog ? { status: watchdog.status, first_seen_at: iso(watchdog.first_seen_ms), changed_at: iso(watchdog.changed_ms),
      bootstrap_overdue: bootstrapOverdue, scope: 'Monitoring establishment/freshness only; not business failure' } : { status: 'unknown', first_seen_at: null, bootstrap_overdue: false },
    missing_checks: prior, coverage: { tracked_checks: results[2].results[0].total, prior_returned: prior.length,
      prior_list_truncated: results[1].results.length > 500, limitation: 'Counts cover returned current/missing checks; collector freshness is separate from business health' },
    delivery: results[3].results, events: await events(db, 50) };
}
function baselineIncidents() { return BASELINE.records.filter(r => r.kind === 'incident' || r.id.startsWith('incident:')); }
async function incidents(db) {
  const [overrides, revisions] = await db.batch([
    stmt(db, 'SELECT * FROM ops_incident_overrides'),
    stmt(db, 'SELECT * FROM ops_incident_revisions ORDER BY updated_ms DESC,incident_id,revision DESC LIMIT 200'),
  ]);
  const map = new Map(overrides.results.map(r => [r.incident_id, r]));
  return { incidents: baselineIncidents().map(b => {
    const row = map.get(b.id); const override = row ? JSON.parse(row.override_json) : null;
    return { ...b, baseline: b, override, revision: row?.revision || 0, effective: override ? { ...b, ...override } : b };
  }), revisions: revisions.results.map(r => ({ ...r, override: JSON.parse(r.override_json), updated_at: iso(r.updated_ms) })), revisions_limit: 200 };
}
async function updateIncident(request, db, auth, id, now) {
  if (!baselineIncidents().some(i => i.id === id)) fail(404, 'incident_not_found');
  if (request.headers.get('X-Ops-Intent') !== 'update') fail(403, 'update_intent_required');
  const origin = request.headers.get('Origin');
  if ((auth.session && !origin) || (origin && origin !== new URL(request.url).origin)) fail(403, 'same_origin_required');
  const value = await body(request); exactKeys(value, UPDATE_FIELDS); integer(value.expected_revision);
  for (const key of UPDATE_FIELDS.filter(k => !['expected_revision', 'evidence_url'].includes(k))) safeText(value[key], key === 'note' ? 2000 : 160, key === 'note');
  text(value.evidence_url, 500, true);
  if (value.evidence_url) {
    let url; try { url = new URL(value.evidence_url); } catch { fail(400, 'invalid_evidence_url'); }
    if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hostname === 'localhost' || /^[\d.]+$/.test(url.hostname) || /\/(tmp|private|Users|home|root)\/|\.env\b|\/open-apis\/bot\//i.test(url.pathname)) fail(400, 'invalid_evidence_url');
  }
  if (/(?:closed|resolved|结案|关闭|已解决|已完成|已恢复)/i.test(value.workflow_status) && (!value.evidence_url || !value.note.trim() ||
    !['verified', 'passed', 'scoped_pass', '已验证', '通过', '已验收'].includes(value.verification_state) || !['observed', 'passed', 'complete', '已观察', '观察通过'].includes(value.observation_status))) fail(400, 'closure_evidence_required');
  const next = { ...value }; delete next.expected_revision;
  const result = await stmt(db, `INSERT INTO ops_incident_overrides(incident_id,revision,override_json,updated_ms,actor)
    SELECT ?,1,?,?,? WHERE ?=0 OR EXISTS(SELECT 1 FROM ops_incident_overrides WHERE incident_id=? AND revision=?)
    ON CONFLICT(incident_id) DO UPDATE SET revision=ops_incident_overrides.revision+1,
    override_json=excluded.override_json,updated_ms=excluded.updated_ms,actor=excluded.actor
    WHERE ops_incident_overrides.revision=? RETURNING revision`,
  id, JSON.stringify(next), now, auth.actor, value.expected_revision, id, value.expected_revision, value.expected_revision).first();
  if (!result) fail(409, 'incident_revision_conflict');
  return response({ incident_id: id, revision: result.revision, override: next });
}
async function exportBackup(db, now, env) {
  // Keyset pagination streams all retained rows, bounded by captured rowid
  // watermarks. Existing row updates across pages are not a transaction snapshot.
  const tables = [
    ['runs', 'ops_runs', 'snapshot_id'], ['events', 'ops_events', 'event_id'],
    ['outbox', 'ops_outbox', 'event_id'], ['check_state', 'ops_check_state', "collector_id || ':' || check_id"],
    ['overrides', 'ops_incident_overrides', 'incident_id'],
    ['revisions', 'ops_incident_revisions', "incident_id || ':' || printf('%012d',revision)"],
    ['head', 'ops_head', 'CAST(id AS TEXT)'], ['watchdog', 'ops_watchdog', 'CAST(id AS TEXT)'],
  ];
  if (await benefitsConfigured(db, env)) tables.push(...benefitsExportTables());
  const iterator = (async function* () {
    const watermarks = await db.batch(tables.map(([, table]) => stmt(db, `SELECT COALESCE(MAX(rowid),0) watermark FROM ${table}`)));
    yield JSON.stringify({ schema_version: 1, exported_at: iso(now), baseline: BASELINE,
      consistency: 'Paginated retained-state export; concurrent changes may span pages; not a transaction snapshot' }).slice(0, -1);
    for (const [i, [name, table, key]] of tables.entries()) {
      yield `,${JSON.stringify(name)}:[`; let after = ''; let first = true;
      while (true) {
        const rows = (await stmt(db, `SELECT *,${key} AS export_key FROM ${table} WHERE ${key}>? AND rowid<=? ORDER BY ${key} LIMIT 20`, after, watermarks[i].results[0].watermark).all()).results;
        if (!rows.length) break;
        for (const row of rows) { after = row.export_key; delete row.export_key; yield (first ? '' : ',') + JSON.stringify(row); first = false; }
      }
      yield ']';
    }
    yield '}';
  })();
  return new Response(new ReadableStream({ async pull(controller) {
    try { const result = await iterator.next(); if (result.done) controller.close(); else controller.enqueue(enc.encode(result.value)); }
    catch { controller.error(new Error('ops_backup_read_failed')); }
  }, async cancel() { await iterator.return(); } }), { headers: {
    'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store',
    'Content-Disposition': 'attachment; filename="ops-private-backup.json"', 'X-Content-Type-Options': 'nosniff',
    'Cross-Origin-Resource-Policy': 'same-origin',
  } });
}

export default async function opsHandler(request, env, ctx) {
  const diagnostic = { request_id: crypto.randomUUID() };
  try {
    const url = new URL(request.url); const now = Date.now(); const db = binding(env);
    if (url.pathname === '/api/ops/ingest' && request.method === 'POST') return await ingest(request, env, db, now, diagnostic);
    const auth = await admin(request, env);
    if (url.pathname === '/api/ops/benefits' || url.pathname.startsWith('/api/ops/benefits/')) return await benefitsRoute(request, db, env, auth, now, { fail, response, body, safeText, exactKeys, integer, boundedLimit });
    if (request.method === 'GET') {
      switch (url.pathname) {
        case '/api/ops/state': return response(await state(db, now));
        case '/api/ops/history': return response({ runs: (await stmt(db, 'SELECT snapshot_id,collector_id,collected_ms,received_ms,counts_json,duration_ms FROM ops_runs ORDER BY collected_ms DESC,snapshot_id DESC LIMIT ?', boundedLimit(url)).all()).results.map(r => ({ ...r, collected_at: iso(r.collected_ms), received_at: iso(r.received_ms), counts: JSON.parse(r.counts_json) })) });
        case '/api/ops/events': return response({ events: await events(db, boundedLimit(url)) });
        case '/api/ops/knowledge': return response(BASELINE);
        case '/api/ops/incidents': return response(await incidents(db));
        case '/api/ops/export': return exportBackup(db, now, env);
        default: fail(404, 'ops_route_not_found');
      }
    }
    if (request.method === 'POST' && url.pathname.startsWith('/api/ops/incidents/')) {
      let id; try { id = decodeURIComponent(url.pathname.slice('/api/ops/incidents/'.length)); } catch { fail(400, 'invalid_incident_id'); }
      return await updateIncident(request, db, auth, id, now);
    }
    fail(405, 'method_not_allowed');
  } catch (error) {
    const known = error instanceof OpsError;
    const status = known ? error.status : 503;
    const code = known ? error.code : 'ops_storage_or_service_unavailable';
    if (status < 500) return response({ error: code }, status);
    const configCodes = ['ops_storage_unavailable', 'ingest_not_configured', 'ops_token_configuration_invalid', 'admin_not_configured'];
    const error_kind = known ? error.kind || (configCodes.includes(code) ? 'configuration' : 'unknown') : storageErrorKind(error);
    const safe = { error: code, error_kind, ...diagnostic };
    console.error({ event: 'ops_request_failed', ...safe });
    return response(safe, status);
  }
}

function alertScope(env) {
  const scope = env.OPS_ALERT_SCOPE ?? 'watchdog';
  return scope === 'watchdog' || scope === 'all' ? scope : null;
}
function outboxConfiguration(env) {
  const scope = alertScope(env);
  if (!scope) return { scope, reason: 'invalid_alert_scope' };
  if (env.OPS_ALERT_ENABLED !== 'true') return { scope, reason: 'alerts_disabled' };
  let url; try { url = new URL(env.OPS_ALERT_WEBHOOK); } catch { return { scope, reason: 'webhook_not_configured' }; }
  if (url.protocol !== 'https:' || url.hostname !== 'open.feishu.cn' || url.port || url.username || url.password || url.search || url.hash || !/^\/open-apis\/bot\/v2\/hook\/[A-Za-z0-9-]{16,128}$/.test(url.pathname)) return { scope, reason: 'webhook_configuration_invalid' };
  return { scope, url };
}
function outboxPolicyStatements(db, env, now) {
  const config = outboxConfiguration(env); const statements = [stmt(db, `UPDATE ops_outbox SET status='suppressed',last_error='measurement_not_paging_owner'
    WHERE status IN ('pending','disabled','sending','suppressed') AND EXISTS(SELECT 1 FROM ops_events e WHERE e.event_id=ops_outbox.event_id AND e.check_id LIKE 'benefit:%')`)];
  // Existing business notify/monitor chains own paging by default. A service and
  // timer reporting the same turnover fault remain two observations, zero new
  // direct pages. Explicit scope=all is a Claude-reviewed deployment opt-in.
  if (config.scope === 'watchdog') statements.push(stmt(db, `UPDATE ops_outbox
    SET status='suppressed',last_error='existing_alert_chain_owns_business_paging'
    WHERE (status IN ('pending','disabled') OR (status='sending' AND lease_until_ms<=?))
    AND EXISTS(SELECT 1 FROM ops_events e WHERE e.event_id=ops_outbox.event_id AND e.source<>'watchdog')`, now));
  if (!config.url) statements.push(stmt(db, `UPDATE ops_outbox SET status='disabled',last_error=?
    WHERE status='pending' OR (status='sending' AND lease_until_ms<=?)`, config.reason, now));
  return statements;
}
async function deliverOutbox(db, env) {
  // Delivery leases/retries use wall time, not a delayed cron's scheduledTime.
  // Otherwise overlapping delayed invocations could prematurely steal a lease.
  const now = Date.now();
  const config = outboxConfiguration(env);
  const policy = outboxPolicyStatements(db, env, now);
  if (policy.length) await db.batch(policy);
  if (!config.url) {
    return;
  }
  const url = config.url;
  // Enabling alerts never replays disabled history. Old/superseded pending work
  // becomes visibly suppressed, not a burst of obsolete failure notifications.
  await stmt(db, `UPDATE ops_outbox SET status='suppressed',last_error='expired_or_superseded'
    WHERE (status='pending' OR (status='sending' AND lease_until_ms<=?)) AND (created_ms<? OR EXISTS(
      SELECT 1 FROM ops_events newer JOIN ops_events original ON original.event_id=ops_outbox.event_id
      WHERE newer.source=original.source AND newer.check_id=original.check_id AND newer.rowid>original.rowid
      AND newer.kind IN ('alert','recovery')))`, now, now - 3600000).run();
  const deadline = Date.now() + 25000;
  for (let n = 0; n < 4 && Date.now() < deadline; n++) {
    const token = crypto.randomUUID();
    const row = await stmt(db, `UPDATE ops_outbox SET status='sending',lease_token=?,lease_until_ms=?,attempts=attempts+1,last_attempt_ms=?
      WHERE event_id=(SELECT event_id FROM ops_outbox WHERE attempts<? AND next_attempt_ms<=? AND
      (status='pending' OR (status='sending' AND lease_until_ms<=?)) AND
      NOT EXISTS(SELECT 1 FROM ops_events e WHERE e.event_id=ops_outbox.event_id AND e.check_id LIKE 'benefit:%') AND
      (?='all' OR EXISTS(SELECT 1 FROM ops_events e WHERE e.event_id=ops_outbox.event_id AND e.source='watchdog'))
      ORDER BY next_attempt_ms,event_id LIMIT 1)
      AND attempts<? AND (status='pending' OR (status='sending' AND lease_until_ms<=?)) RETURNING *`, token, now + 60000, now, MAX_ATTEMPTS, now, now, config.scope, MAX_ATTEMPTS, now).first();
    if (!row) break;
    const event = await stmt(db, 'SELECT * FROM ops_events WHERE event_id=?', row.event_id).first();
    let sent = false; let error = 'transport_error';
    const abort = new AbortController(); const timer = setTimeout(() => abort.abort(), Math.min(5000, Math.max(1, deadline - Date.now())));
    try {
      const result = await fetch(url.href, { method: 'POST', redirect: 'error', signal: abort.signal,
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ msg_type: 'text', content: {
          text: `${event.kind === 'recovery' ? '【恢复】' : '【告警】'}${event.source === 'watchdog'
            ? event.kind === 'recovery'
              ? '采集链已恢复采样。\n本次恢复只代表重新收到采样，不等于业务故障已根治。'
              : '采集链超过30分钟未收到采样。\n请检查采集与上报链路；当前业务状态仍待核实。'
            : `运行检查：${event.check_id}，状态：${event.status}\n${event.summary.slice(0, 240)}`
          }\n事件编号：${event.event_id}\n如回执超时，重试可能重复送达；可按事件编号核对。`,
        } }) });
      if (result.ok && result.body) {
        const reader = result.body.getReader(); let size = 0; const chunks = [];
        try {
          while (true) { const v = await reader.read(); if (v.done) break; size += v.value.length; if (size > 4096) { await reader.cancel(); break; } chunks.push(v.value); }
        } finally { reader.releaseLock(); }
        if (size <= 4096) {
          const bytes = new Uint8Array(size); let i = 0; for (const v of chunks) { bytes.set(v, i); i += v.length; }
          const ack = JSON.parse(new TextDecoder().decode(bytes)); sent = ack.code === 0; error = sent ? '' : 'webhook_rejected';
        } else error = 'webhook_response_too_large';
      } else { await result.body?.cancel(); error = 'webhook_http_error'; }
    } catch { /* bounded retries; ambiguous network failures can duplicate delivery */ }
    finally { clearTimeout(timer); }
    await stmt(db, `UPDATE ops_outbox SET status=?,delivered_ms=?,last_error=?,next_attempt_ms=?,lease_token=NULL,lease_until_ms=0
      WHERE event_id=? AND lease_token=?`, sent ? 'sent' : row.attempts >= MAX_ATTEMPTS ? 'failed' : 'pending', sent ? now : null,
    sent ? null : error, now + Math.min(3600000, 60000 * 2 ** row.attempts), row.event_id, token).run();
  }
}

export async function opsScheduled(controller, env, ctx) {
  // OPS-R3: freshness is an execution-time observation. An old scheduledTime
  // cannot recover an unchanged stale head or backdate its current-state clock.
  const now = Date.now();
  const db = binding(env);
  // Independent cron observes absence/staleness even when collector cannot push.
  await db.batch([
    stmt(db, `INSERT INTO ops_watchdog(id,status,changed_ms,first_seen_ms) SELECT 1,
      CASE WHEN NOT EXISTS(SELECT 1 FROM ops_head) THEN
        CASE WHEN COALESCE((SELECT first_seen_ms FROM ops_watchdog WHERE id=1),?)<? THEN 'stale' ELSE 'unknown' END
      WHEN (SELECT collected_ms FROM ops_head WHERE id=1)<? THEN 'stale' ELSE 'fresh' END,?,?
      ON CONFLICT(id) DO UPDATE SET status=excluded.status,
        changed_ms=CASE WHEN ops_watchdog.status<>excluded.status THEN excluded.changed_ms ELSE ops_watchdog.changed_ms END,
        first_seen_ms=COALESCE(ops_watchdog.first_seen_ms,excluded.first_seen_ms)
      WHERE excluded.changed_ms>=ops_watchdog.changed_ms`, now, now - AGE_MS, now - AGE_MS, now, now),
    stmt(db, "UPDATE ops_check_state SET status='unknown',summary='Observation expired; not a recovery',updated_ms=? WHERE observed_ms<? AND status<>'unknown'", now, now - AGE_MS),
    stmt(db, 'UPDATE ops_runs SET snapshot_json=NULL WHERE received_ms<? AND snapshot_json IS NOT NULL AND snapshot_id NOT IN(SELECT snapshot_id FROM ops_head)', now - DAY),
    stmt(db, 'DELETE FROM ops_runs WHERE received_ms<? AND snapshot_id NOT IN(SELECT snapshot_id FROM ops_head)', now - 30 * DAY),
    stmt(db, 'DELETE FROM ops_outbox WHERE created_ms<?', now - 90 * DAY),
    stmt(db, 'DELETE FROM ops_events WHERE created_ms<?', now - 90 * DAY),
    stmt(db, 'DELETE FROM ops_incident_revisions WHERE updated_ms<?', now - 90 * DAY),
    stmt(db, 'DELETE FROM ops_check_state WHERE updated_ms<?', now - 90 * DAY),
    stmt(db, "UPDATE ops_outbox SET status='failed',last_error='lease_expired_after_retry_limit',lease_token=NULL WHERE status='sending' AND lease_until_ms<=? AND attempts>=?", now, MAX_ATTEMPTS),
  ]);
  try { await benefitsRetain(db, env, now); } catch { /* Original cron remains independent. */ }
  await deliverOutbox(db, env);
}
