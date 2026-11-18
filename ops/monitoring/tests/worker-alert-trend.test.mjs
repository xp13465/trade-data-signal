// admin/ops 每日告警量走势：worker 两条新路由的本地实测（真 Miniflare + 真迁移）。
// 覆盖证据用例：未登录 401 / 采集令牌 GET 403 / 管理员 200；payload 校验；
// 不变不写（96 轮/天 × 90 行必须挡住）；缺日合成 no_data；180 天保留清理。
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, mkdtempSync, mkdirSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { Miniflare, convertV4MiniflareOptions } from 'miniflare';
import handler, { opsScheduled } from '../../../worker/ops.js';

async function fixture() {
  const mf = new Miniflare(convertV4MiniflareOptions({ modules: true, compatibilityDate: '2026-11-07',
    script: 'export default { fetch() { return new Response("local D1 fixture only"); } }',
    d1Databases: { OPS_DB: 'ops-alert-daily-fixture' } }));
  const db = await mf.getD1Database('OPS_DB');
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
  const env = { OPS_DB: db, OPS_INGEST_TOKEN: 'trend-fixture-ingest', OPS_ADMIN_TOKEN: 'trend-fixture-admin', OPS_ALERT_ENABLED: 'false' };
  async function raw(path, { method = 'GET', auth = 'admin', body, headers = {} } = {}) {
    const authHeaders = auth === 'ingest' ? { Authorization: 'Bearer trend-fixture-ingest' }
      : auth === 'admin' ? { 'X-Ops-Admin-Token': 'trend-fixture-admin' } : {};
    const response = await handler(new Request('https://fixture.invalid/api/ops' + path, {
      method, headers: { 'Content-Type': 'application/json', ...authHeaders, ...headers },
      body: body === undefined ? undefined : JSON.stringify(body) }), env, {});
    return { status: response.status, body: await response.json() };
  }
  async function scheduleAt(wallTime) {
    const realNow = Date.now; Date.now = () => wallTime;
    try { await opsScheduled({ scheduledTime: wallTime }, env, {}); } finally { Date.now = realNow; }
  }
  return { mf, db, env, raw, scheduleAt };
}
// 下两行手造的是「线上报文（wire）形状」= worker 固定 6 键，用于鉴权/校验/幂等分支。
// 生产端真实形状另由下方 contract 测试用 alert_meter 实跑生成（2026-11-18 审查 P0-1：
// 只测手造 6 键会漏掉「生产者多带 no_data → 整批 400」的断裂）。
const row = (date, total, real, noise, escalation = 0, byTier = { notice: real, warning: noise }) => ({ date, total, real, noise, escalation, by_tier: byTier });
const payload = (days, computed_ms) => ({ computed_ms, days });

// 真跑生产端（alert_meter.py --trend --payload-out），返回本地走势产物 + 实际上报体。
// 不手造行、不手写投影：发送契约若漂移，下面 contract 测试必红。
function realTrendPayload(days) {
  const root = mkdtempSync(join(tmpdir(), 'trend-producer-'));
  const tree = join(root, 'tree');
  const ledger = join(tree, 'data', 'alerts', 'alert_ledger.jsonl');
  mkdirSync(dirname(ledger), { recursive: true });
  const rec = (day, tier, subject) => JSON.stringify({
    ts: `${day} 09:00:00`, group: 'alert', tier, subject, key: subject,
    source: 'fixture', channels: ['feishu'],
  });
  const lines = [];
  for (const [i, day] of days.entries()) {
    lines.push(rec(day, 'digest', `每日摘要 ${i}`));
    for (let k = 0; k <= i; k += 1) lines.push(rec(day, 'notice', `故障 ${i}-${k}`));
  }
  writeFileSync(ledger, lines.join('\n') + '\n');
  const repo = fileURLToPath(new URL('../../../', import.meta.url));
  const payloadPath = join(root, 'payload.json');
  execFileSync('python3', [join(repo, 'scripts', 'alert_meter.py'), '--trend',
    '--trees', tree, '--date', days.at(-1), '--payload-out', payloadPath],
  { cwd: repo, stdio: 'pipe', timeout: 60000 });
  return {
    trend: JSON.parse(readFileSync(join(tree, 'data', 'alerts', 'alert_trend.json'), 'utf8')),
    payload: JSON.parse(readFileSync(payloadPath, 'utf8')),
  };
}

test('alert-daily: auth matrix, validation, unchanged-no-write, no_data synthesis, retention', { timeout: 60000 }, async () => {
  const { mf, db, raw, scheduleAt } = await fixture();
  try {
    const now = Date.now();
    // 日期全部相对“运行日”推导（不写死日历字面量），隔天/隔年跑仍绿。
    const D = n => new Date(now + n * 86400000).toISOString().slice(0, 10);
    // 证据用例①：未登录 GET → 401；采集令牌 GET → 403（采集令牌无查看权）。
    assert.equal((await raw('/alert-daily?days=30', { auth: 'none' })).status, 401);
    const ingestGet = await raw('/alert-daily?days=30', { auth: 'ingest' });
    assert.equal(ingestGet.status, 403);
    assert.equal(ingestGet.body.error, 'ingest_has_no_viewer_privilege');
    // 空表：管理员 200，明确返回空窗口（前端显示「尚未收到」，不显示 0）。
    const empty = await raw('/alert-daily?days=30');
    assert.equal(empty.status, 200);
    assert.equal(empty.body.days_count, 0);
    assert.equal(empty.body.computed_ms, null);
    // POST 鉴权：无 bearer / 管理员令牌都不行，只认采集令牌。
    assert.equal((await raw('/alert-daily', { method: 'POST', auth: 'none', body: payload([row(D(0), 3, 2, 1)], now) })).status, 403);
    assert.equal((await raw('/alert-daily', { method: 'POST', auth: 'admin', body: payload([row(D(0), 3, 2, 1)], now) })).status, 403);
    // payload 校验：日期格式/日历、重复日、负数、真故障+噪音≠总数、天数上限、未知键。
    const bad = [
      payload([{ ...row('2026-02-30', 1, 1, 0) }], now),
      payload([{ ...row('2026-2-01', 1, 1, 0) }], now),
      payload([row(D(0), 3, 2, 1), row(D(0), 3, 2, 1)], now),
      payload([row(D(0), 3, 4, 1)], now),
      payload([row(D(0), 3, 2, -1)], now),
      payload([{ ...row(D(0), 1, 1, 0), extra: 1 }], now),
      payload([{ ...row(D(0), 1, 1, 0), by_tier: { 'Bad-Key': 1 } }], now),
      { computed_ms: now, days: [], extra: true },
      payload([row(D(0), 1, 1, 0)], now + 2 * 86400000),
    ];
    for (const body of bad) assert.equal((await raw('/alert-daily', { method: 'POST', auth: 'ingest', body })).status, 400);
    const tooMany = Array.from({ length: 91 }, (_, i) => row(D(-i), 1, 1, 0));
    assert.equal((await raw('/alert-daily', { method: 'POST', auth: 'ingest', body: payload(tooMany, now) })).status, 400);
    // 正常写入：最近三天（中间故意留前一天缺口，验证 no_data 合成）。
    const first = payload([row(D(-2), 4, 3, 1, 1), row(D(-1), 2, 0, 2, 0), row(D(0), 3, 2, 1, 0)], now);
    const created = await raw('/alert-daily', { method: 'POST', auth: 'ingest', body: first });
    assert.equal(created.status, 200);
    assert.deepEqual([created.body.received, created.body.changed, created.body.latest], [3, 3, D(0)]);
    const countRows = async () => (await db.prepare('SELECT COUNT(*) n FROM ops_alert_daily').first()).n;
    assert.equal(await countRows(), 3);
    // 证据用例④：连续两轮 POST 相同内容 → 行数不变、changed=0，只有最新一天 computed_ms 心跳前移。
    const second = await raw('/alert-daily', { method: 'POST', auth: 'ingest', body: payload(first.days, now + 60000) });
    assert.equal(second.status, 200);
    assert.deepEqual([second.body.changed, second.body.heartbeat], [0, true]);
    assert.equal(await countRows(), 3);
    const heartbeat = await db.prepare('SELECT computed_ms FROM ops_alert_daily WHERE date=?').bind(D(0)).first();
    assert.equal(heartbeat.computed_ms, now + 60000);
    const older = await raw('/alert-daily', { method: 'POST', auth: 'ingest', body: payload(first.days, now + 30000) });
    assert.equal(older.status, 200);
    assert.equal((await db.prepare('SELECT computed_ms FROM ops_alert_daily WHERE date=?').bind(D(0)).first()).computed_ms, now + 60000);
    // 内容变化才写：只改前一天一天。
    const third = await raw('/alert-daily', { method: 'POST', auth: 'ingest', body: payload([row(D(-1), 5, 3, 2, 1)], now + 90000) });
    assert.deepEqual([third.body.changed, third.body.heartbeat], [1, false]);
    assert.equal(await countRows(), 3);
    // 证据用例②：管理员 GET 返回连续 7 天（窗口终点 = 表内最新日期），缺日 no_data=true 且不补 0。
    const week = await raw('/alert-daily?days=7');
    assert.equal(week.status, 200);
    assert.equal(week.body.days_count, 7);
    assert.deepEqual(week.body.window, [D(-6), D(0)]);
    const missing = week.body.days.find(d => d.date === D(-3));
    assert.equal(missing.no_data, true);
    assert.equal(missing.total, null);
    assert.equal(missing.computed_ms, null);
    const today = week.body.days.at(-1);
    assert.deepEqual([today.no_data, today.total, today.real, today.noise, today.by_tier], [false, 3, 2, 1, { notice: 2, warning: 1 }]);
    assert.equal(week.body.days.find(d => d.date === D(-1)).total, 5);
    assert.equal(week.body.computed_ms, now + 90000);
    // days 参数：默认 30、上限 90、非法值 400。
    assert.equal((await raw('/alert-daily')).body.days_count, 30);
    assert.equal((await raw('/alert-daily?days=90')).body.days_count, 90);
    for (const q of ['days=0', 'days=91', 'days=abc', 'days=1.5']) assert.equal((await raw('/alert-daily?' + q)).status, 400);
    // 180 天保留：跑一次定时清理，181 天前的旧行删除、近期行保留（全部相对运行日推导）。
    await db.prepare('INSERT INTO ops_alert_daily VALUES(?,1,1,0,0,?,?)').bind(D(-181), '{}', now).run();
    assert.equal(await countRows(), 4);
    await scheduleAt(now);
    assert.equal(await countRows(), 3);
    const kept = await db.prepare('SELECT COUNT(*) n FROM ops_alert_daily WHERE date=?').bind(D(0)).first();
    assert.equal(kept.n, 1);
  } finally { await mf.dispose(); }
});

// 2026-11-18 审查 P0-1 回归锁：用生产端**真实输出**喂路由，而不是手造 6 键。
// 原 bug：alert_meter 每行 7 键含 no_data → worker 固定键白名单整批 400 → 静默空转。
test('alert-daily contract: real alert_meter producer output accepted end-to-end', { timeout: 120000 }, async () => {
  const { mf, db, raw } = await fixture();
  try {
    const now = Date.now();
    const D = n => new Date(now + n * 86400000).toISOString().slice(0, 10);
    // 有数据的两天 + 中间一天缺口（验证缺日仍由端点合成，不被补 0）。
    const { trend, payload: produced } = realTrendPayload([D(-2), D(0)]);
    const dataDay = trend.days.find(d => !d.no_data);
    // 本地产物形状 = 7 键含 no_data（生产端真实形状，非手造）。
    assert.deepEqual(Object.keys(dataDay).sort(),
      ['by_tier', 'date', 'escalation', 'no_data', 'noise', 'real', 'total']);
    // 上报体 = 6 键投影、无 no_data、只含有数据的天。
    assert.equal(produced.days.length, 2);
    for (const r of produced.days) {
      assert.deepEqual(Object.keys(r).sort(),
        ['by_tier', 'date', 'escalation', 'noise', 'real', 'total']);
    }
    // 端到端：真实上报体 → 200 并落表（原 bug 在这里会 400 invalid_fields）。
    const sent = await raw('/alert-daily', {
      method: 'POST', auth: 'ingest', body: produced,
    });
    assert.equal(sent.status, 200);
    assert.equal(sent.body.received, 2);
    assert.equal(sent.body.changed, 2);
    // 落表值与 build_trend 真实输出逐日对账（total == real + noise 同源恒等式）。
    const stored = (await db.prepare(
      'SELECT date,total,real,noise,escalation,by_tier FROM ops_alert_daily').all()).results;
    for (const r of produced.days) {
      const src = trend.days.find(d => d.date === r.date);
      const got = stored.find(s => s.date === r.date);
      assert.deepEqual([got.total, got.real, got.noise, got.escalation, got.by_tier],
        [src.total, src.real, src.noise, src.escalation, JSON.stringify(src.by_tier)]);
      assert.equal(got.total, got.real + got.noise);
    }
    // GET 连续 3 天：中间缺口 no_data=true + null，绝不出现 0。
    const get = await raw('/alert-daily?days=3');
    assert.equal(get.status, 200);
    assert.deepEqual(get.body.window, [D(-2), D(0)]);
    const gap = get.body.days.find(d => d.date === D(-1));
    assert.equal(gap.no_data, true);
    assert.equal(gap.total, null);
  } finally { await mf.dispose(); }
});
