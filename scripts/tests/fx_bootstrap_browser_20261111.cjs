"use strict";
// Real index.html prefetch + complete app.js, with every request intercepted.
// No production variables/functions are replaced and no HTML fixture is edited.
const fs = require("node:fs"), path = require("node:path"), assert = require("node:assert/strict");
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const root = path.resolve(process.env.FX_SOURCE_ROOT || path.join(__dirname, "../.."), "static-site");
const evidence = process.env.FX_EVIDENCE_DIR;
const ids = ["cross_market", "fear_greed", "high_alert", "low_alert"];
const oldSignals = [
  { index_id: "g.usdcnh", signal: "sell", reason: "legacy FX" },
  { index_id: "s.cross_market", signal: "buy", reason: "legacy cross" },
  { index_id: "s.fear_greed", signal: "buy", reason: "legacy fear" },
  { index_id: "sh", signal: "buy", reason: "RSI=30, 情绪分=55[中性]" },
];
const cases = ["legacy-prefetch", "marked-prefetch", "legacy-prefetch-failed", "safe-boot-old-split",
  "embedded-legacy", "split-missing", "split-invalid", "split-empty", "split-failure-retry"];
const observations = [];
let checks = 0;
function equal(actual, expected, message) { assert.deepEqual(actual, expected, message); checks++; }
function independent(rows, empty = false) {
  equal(rows, empty ? [] : [{ index_id: "sh", signal: "buy", reason: "RSI=30" }]);
}

(async () => {
  const browser = await chromium.launch({ headless: true, args: ["--disable-background-networking"] });
  try {
    for (const name of cases) {
      const safe = name === "safe-boot-old-split", marked = name === "marked-prefetch";
      const scores = Object.fromEntries(ids.map(sid => [sid, { value: safe ? null : 99,
        is_freeze: safe ? null : 1, components: marked ? { _fx_contract: "fx-excluded-v1", _fx_available: true } : {} }]));
      scores.a_sentiment = { value: 0, is_freeze: 1 };
      const overview = { date: "20261111", today: { scores, metrics: [] },
        recent_freeze: [{ date: "20261110", score_id: "fear_greed" }, { date: "20261110", score_id: "a_sentiment" }] };
      if (name === "embedded-legacy") overview.signals_today = oldSignals;
      const alert = { date: "20261111", high: { score: 99, triggered: true, level: "旧高危", dims: [] },
        low: { score: 99, triggered: true, level: "旧机遇", dims: [] } };
      if (marked || safe) alert.fx_contract = "fx-excluded-v1";
      const summary = { date: "20261111", fear_greed_value: 99, summary: "旧恐贪99摘要" };
      if (marked || safe) Object.assign(summary, { fx_contract: "fx-excluded-v1", summary: "独立摘要" });
      const boot = { overview, alert, summary, signal_stats: { "g.usdcnh": { buy: { n: 20 } }, sh: { buy: { n: 20 } } } };
      const requests = [], errors = [];
      let bootRequests = 0, recovered = false;
      const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, serviceWorkers: "block" });
      try {
        await ctx.route("**/*", async route => {
          const u = new URL(route.request().url()), key = path.basename(u.pathname);
          requests.push({ host: u.host, path: u.pathname });
          if (key === "boot.json") {
            bootRequests++;
            if (name === "legacy-prefetch-failed" && bootRequests <= 2) return route.fulfill({ status: 503, body: "unavailable" });
            return route.fulfill({ contentType: "application/json", body: JSON.stringify(boot) });
          }
          if (key.endsWith(".json")) {
            if (name === "split-failure-retry" && !recovered && ["signals_today.json", "overview.json"].includes(key)) {
              return route.fulfill({ status: 503, body: "unavailable" });
            }
            if (name === "split-missing" && key === "signals_today.json") return route.fulfill({ status: 404, body: "missing" });
            const split = { signals_today: name === "split-empty" ? [] : name === "split-invalid" ? {} : oldSignals,
              signals_meta: { date: "20261111", source: "fixture" } };
            const fallback = { ...overview, signals_today: oldSignals, signals_meta: { date: "20261111", source: "fallback" } };
            const data = { "signals_today.json": split, "overview.json": fallback, "alert.json": alert, "summary.json": summary }[key] || {};
            return route.fulfill({ contentType: "application/json", body: JSON.stringify(data) });
          }
          if (u.host !== "localhost:8765") return route.abort();
          let rel = u.pathname === "/" ? "index.html" : u.pathname.replace(/^\//, "");
          // Exercise checked-in source, not a previously built/minified release.
          if (rel === "app.min.js") rel = "app.js";
          const file = path.resolve(root, rel);
          if (!file.startsWith(root + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) return route.abort();
          return route.fulfill({ path: file, contentType: rel.endsWith(".js") ? "text/javascript" : rel.endsWith(".css") ? "text/css" : rel.endsWith(".html") ? "text/html" : undefined });
        });
        const page = await ctx.newPage();
        page.on("pageerror", e => errors.push(String(e)));
        await page.clock.install({ time: new Date("2026-11-11T08:30:00+08:00") });
        await page.goto("http://localhost:8765/", { waitUntil: "domcontentloaded", timeout: 12000 });
        await page.waitForFunction(() => typeof fetchBoot === "function", null, { timeout: 10000 });
        const first = await page.evaluate(async () => {
          await fetchBoot();
          const early = JSON.parse(JSON.stringify(_bootData));
          const rows = await _ensureSignalsToday(_bootData.overview);
          return { early, rows, loaded: JSON.parse(JSON.stringify(_bootData)) };
        });
        const initialSignalRequests = requests.filter(r => r.path === "/data/signals_today.json").length;
        if (name === "split-failure-retry") {
          equal(first.rows, null, "both unavailable paths return unknown, not a fake empty success");
          equal(first.loaded.overview.signals_today, undefined);
          recovered = true;
          await page.evaluate(() => _ensureSignalsToday(_bootData.overview));
        }
        const beforeReuse = requests.length;
        const result = await page.evaluate(async rawRows => {
          const a = { signals_meta: { original: true } }, b = {};
          const joined = await Promise.all([_ensureSignalsToday(a), _ensureSignalsToday(b)]);
          const embedded = { signals_today: rawRows };
          const embeddedRows = await _ensureSignalsToday(embedded);
          const host = document.createElement("section"); document.body.appendChild(host);
          await renderAlertBar(host);
          return { loaded: JSON.parse(JSON.stringify(_bootData)), stats: state.signalStats,
            cached: _getCachedOverview(), a, b, joined, embedded, embeddedRows,
            alertText: host.innerText, alertBars: host.querySelectorAll(".alert-bar").length };
        }, oldSignals);
        observations.push({ case: name, first, result, bootRequests, errors, requests, all_requests_intercepted: true });
        for (const source of [first.early.overview, result.loaded.overview, result.cached]) {
          for (const sid of ids) {
            equal(source.today.scores[sid].value, null);
            equal(source.today.scores[sid].is_freeze, null);
          }
          equal(source.today.scores.a_sentiment.value, 0, "real independent zero survives");
          equal(source.recent_freeze.map(r => r.score_id), ["a_sentiment"]);
        }
        equal(result.loaded.alert.high.score, null);
        equal(result.loaded.alert.high.triggered, false);
        equal(result.loaded.summary.fear_greed_value, null);
        equal(Object.keys(result.stats), ["sh"]);
        equal(result.alertBars, 0);
        assert.match(result.alertText, /风险预警不可用/); checks++;
        assert.doesNotMatch(result.alertText, /99|50|中性/); checks++;
        const empty = name === "split-empty";
        independent(result.loaded.overview.signals_today, empty);
        for (const rows of [result.a.signals_today, result.b.signals_today, ...result.joined]) independent(rows, empty);
        independent(result.embeddedRows); independent(result.embedded.signals_today);
        equal(result.a.signals_meta, { original: true });
        equal(result.b.signals_meta.date, "20261111");
        equal(errors, []);
        if (name === "embedded-legacy") equal(initialSignalRequests, 0, "embedded signals require no initial split fetch");
        equal(requests.slice(beforeReuse).filter(r => r.path === "/data/signals_today.json").length,
          name === "embedded-legacy" ? 1 : 0, "inflight/settled request is shared by both new overview objects");
        if (name === "legacy-prefetch-failed") assert.ok(bootRequests >= 3, "real HTML two-leg failure reaches fetchJSON fallback");
        if (name === "split-empty") equal(requests.filter(r => r.path === "/data/overview.json").length, 0, "valid empty does not fall back to old nonempty signals");
        if (evidence && ["legacy-prefetch", "safe-boot-old-split"].includes(name)) await page.screenshot({ path: path.join(evidence, name + ".png"), fullPage: true });
      } finally { await ctx.close(); }
    }
    console.log(`FX bootstrap browser: ${cases.length} real-page scenarios, ${checks} assertions passed; prefetch/fallback/split/cache/retry; pageerrors=0; no external network`);
  } finally {
    if (evidence) fs.writeFileSync(path.join(evidence, "bootstrap-observations.json"), JSON.stringify(observations, null, 2));
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
