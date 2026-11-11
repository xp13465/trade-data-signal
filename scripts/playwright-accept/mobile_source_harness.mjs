// Actual project sources + immutable-in-process copies of real exported files.
// DATA_ROOT is optional. Without it, data requests go to the selected live site.
import fs from 'node:fs/promises';
import path from 'node:path';
import { createHash } from 'node:crypto';
const cache = new Map();
export const evidence = { files: [], unavailable: new Set() };
export async function installSources(page) {
  const source = process.env.SOURCE_ROOT;
  if (!source) return;
  const root = path.resolve(source, 'static-site');
  const data = process.env.DATA_ROOT && path.resolve(process.env.DATA_ROOT);
  async function read(root, name) {
    const filename = path.resolve(root, name);
    if (!filename.startsWith(root + path.sep)) throw new Error('path escape');
    if (!cache.has(filename)) {
      const body = await fs.readFile(filename);
      cache.set(filename, body);
      evidence.files.push({path: filename, bytes: body.length, sha256: createHash('sha256').update(body).digest('hex')});
    }
    return cache.get(filename);
  }
  await page.route('**/*', async route => {
    const url = new URL(route.request().url());
    const site = new URL(process.env.BASE_URL || 'https://ss.fx8.store');
    if (![site.hostname, 'ssd.fx8.store'].includes(url.hostname)) {
      if (!data) return route.continue();
      evidence.unavailable.add(url.origin + url.pathname);
      return route.abort();
    }
    let name = decodeURIComponent(url.pathname).replace(/^\//, '') || 'index.html';
    const isData = name.startsWith('data/') || name.startsWith('r2/') || url.hostname === 'ssd.fx8.store';
    if (isData && !data) return route.continue();
    if (name.startsWith('api/')) {
      if (!data) return route.continue();
      evidence.unavailable.add(url.pathname); return route.abort();
    }
    try {
      let body;
      if (isData) {
        name = name.replace(/^r2\//, '').replace(/^data\//, '').replace(/^trade_sim_data\//, 'trade_sim/');
        body = await read(data, name);
      } else {
        try { body = await read(root, name.replace(/\.min\.(js|css)$/, '.$1')); }
        catch { body = await read(root, name); }
      }
      const ext = path.extname(name);
      const types = {'.js':'application/javascript','.css':'text/css','.json':'application/json','.html':'text/html','.svg':'image/svg+xml','.png':'image/png','.ico':'image/x-icon'};
      await route.fulfill({status:200,contentType:types[ext] || 'application/octet-stream',body});
    } catch {
      evidence.unavailable.add(url.pathname);
      if (!data) return route.continue();
      await route.abort();
    }
  });
}
export async function dismissIntro(page) {
  const skip = page.locator('.onboarding-skip:visible');
  if (await skip.count()) await skip.first().click();
}
export async function saveEvidence(output, results) {
  if (!output) return;
  await fs.mkdir(path.dirname(output), { recursive: true });
  await fs.writeFile(output, JSON.stringify({scope:process.env.DATA_ROOT ? 'actual source / real local exports; not live deployment or device acceptance' : 'browser / live data',...results,files:evidence.files,unavailable:[...evidence.unavailable]},null,2)+'\n');
}
