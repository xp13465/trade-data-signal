// SYNTHETIC ONLY. Local full Worker bundle + native Miniflare D1, no browser.
// Used exclusively by smoke_benefits_pipeline.py; no production config/env reads.
import { build } from 'esbuild';
import { Miniflare, convertV4MiniflareOptions } from 'miniflare';
import { readFileSync, readdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createInterface } from 'node:readline';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../../..');
const configPath = resolve(root, 'ops/monitoring/wrangler.local.jsonc');
const config = JSON.parse(readFileSync(configPath, 'utf8'));
if (config.name !== 'trade-ops-local') throw new Error('Expected local config');
for (const type of ['kv_namespaces', 'r2_buckets', 'd1_databases']) {
  if ((config[type] || []).some(binding => binding.remote !== false)) throw new Error('Remote binding forbidden');
}
if (resolve(dirname(configPath), config.main) !== resolve(root, 'worker/headers.js')) throw new Error('Expected actual Worker');
const temporary = process.argv[2];
if (!temporary) throw new Error('Temporary persistence required');
const bundle = await build({entryPoints: [resolve(root, 'worker/headers.js')], bundle: true,
  format: 'esm', platform: 'browser', write: false, logLevel: 'silent'});
let externalRequests = 0;
const mf = new Miniflare(convertV4MiniflareOptions({
  modules: true, compatibilityDate: config.compatibility_date,
  script: bundle.outputFiles[0].text, host: '127.0.0.1', port: 0,
  d1Databases: Object.fromEntries(config.d1_databases.map(b => [b.binding, b.database_id])),
  kvNamespaces: config.kv_namespaces.map(b => b.binding),
  r2Buckets: config.r2_buckets.map(b => b.binding),
  d1Persist: resolve(temporary, 'd1'), kvPersist: resolve(temporary, 'kv'), r2Persist: resolve(temporary, 'r2'),
  bindings: {OPS_ADMIN_TOKEN: 'synthetic-admin-benefits-pipeline',
    OPS_INGEST_TOKEN: 'synthetic-ingest-benefits-pipeline', OPS_BENEFITS_ENABLED: 'true',
    OPS_ALERT_SCOPE: 'all', OPS_ALERT_ENABLED: 'false'},
  outboundService: () => { externalRequests++; return new Response('External requests forbidden by synthetic fixture', {status: 599}); },
}));
let closing = false;
async function stop() {
  if (closing) return;
  closing = true;
  await mf.dispose();
  process.exit(0);
}
process.on('SIGTERM', stop);
process.on('SIGINT', stop);
try {
  const db = await mf.getD1Database('OPS_DB');
  const dir = resolve(root, 'ops/monitoring/migrations');
  let unit = '', trigger = false;
  const migrations = readdirSync(dir).filter(f => /^\d+.*\.sql$/.test(f)).sort();
  for (const file of migrations) {
    for (const raw of readFileSync(resolve(dir, file), 'utf8').split('\n')) {
      const line = raw.trim();
      if (!line || line.startsWith('--')) continue;
      if (line.startsWith('CREATE TRIGGER')) trigger = true;
      unit += raw + '\n';
      if ((!trigger && line.endsWith(';')) || (trigger && line === 'END;')) {
        await db.prepare(unit).run(); unit = ''; trigger = false;
      }
    }
  }
  if (unit) throw new Error('Incomplete migration statement');
  const origin = (await mf.ready).origin;
  process.stdout.write(JSON.stringify({ready: true, origin, migrations, remote: false}) + '\n');
  const input = createInterface({input: process.stdin});
  for await (const line of input) {
    const command = JSON.parse(line);
    if (command.op === 'stop') break;
    if (command.op !== 'stats') throw new Error('Unknown fixture operation');
    const counts = {};
    for (const name of ['ops_runs', 'ops_benefit_current', 'ops_benefit_audit']) {
      counts[name] = (await db.prepare('SELECT count(*) AS n FROM ' + name).first()).n;
    }
    const kinds = (await db.prepare("SELECT COALESCE(json_extract(record_json,'$.measurement_kind'),'unknown') AS kind,count(*) AS n FROM ops_benefit_current GROUP BY kind").all()).results;
    process.stdout.write(JSON.stringify({counts, kinds, external_requests: externalRequests, remote: false}) + '\n');
  }
} finally {
  await stop();
}
