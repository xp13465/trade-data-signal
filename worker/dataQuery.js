// CF Workers 统一数据查询 API（/api/data/*，2026-08-17 新增，B 级新功能）。
// 为 UUMit 平台上架售卖金融情绪数据查询服务做基础。这是"结构化查询服务"：
// 数据本体仍公开（走原 /data/ URL），本 API 卖的是 latest/range/summary 加工能力。
//
// 能力：
//   GET /api/data/<category>/latest   —— 最新一天快照（几百字节，不拉全量）
//   GET /api/data/<category>/range    —— 时间区间切片 ?start=YYYYMMDD&end=YYYYMMDD
//   GET /api/data/<category>/summary  —— 跨类别聚合（恐贪+A股情绪+跨市场+大盘预警）
// 类别：sentiment（聚合 fear_greed+a_sentiment+cross_market）/ alert（大盘预警）/ signals（按标的）
//
// 鉴权：Authorization: Bearer <key> 或 X-API-Key: <key>；key 只存 hash 于 KV（api_key:<hash>）。
// 限流：按 key KV 计数（分钟 + 每日，默认 60 req/min、5000 req/day，超限 429）。
// 计量：每次鉴权通过按每 5 分钟聚合写 KV（api_usage:<hash>:<yyyyMMddHHmm/5>），供计费。
// 错误统一格式：{error:{code,message}}；401/403/404/429/400 各有语义。
// 未带 key 或无效 = 401，不降级为公开访问。
//
// 数据一致性（§22）：本 handler 只做"读源 JSON + 切片/取最新/聚合"，不加工出源文件没有的数字；
// 返回的每个数字都能从 static-site/data/ 源文件逐位对上。R2 key 复用 dataRewriteHandler 模式
// （key = pathname.slice(1) = "data/sentiment-3m.json"），R2 404 回退 ASSETS 静态兜底。

const CORS_HEADERS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-API-Key',
  'Access-Control-Max-Age': '86400',
};

// 类别路由表：加类别 = 加一行（§23.3 举一反三/扩展性）。每项声明源文件 R2 key + 读法。
// 首批已确认 5 类（sentiment 三字段 + alert + alert_analyze）；两融/ETF 二期加时在此加一行。
const CATEGORY_SOURCES = {
  // sentiment: 聚合 fear_greed/a_sentiment/cross_market 三个字段，源文件 sentiment-3m.json
  sentiment: {
    file: 'data/sentiment-3m.json',
    fields: ['fear_greed', 'a_sentiment', 'cross_market'], // latest/range 都只读这三字段
    summaryFields: ['fear_greed', 'a_sentiment', 'cross_market'],
  },
  // alert: 大盘预警，源文件 alert.json（含 date/high/low/history）
  alert: {
    file: 'data/alert.json',
  },
};

// 支持的 alert_analyze 标的（前端 static-site/data/alert_analyze_*.json 一一对应）。
// 缺 target 时返回此列表；二期两融/ETF 类别加行即可。
const KNOWN_ALERT_TARGETS = [
  '159845', '159915', '159919', '159922', '159952', '510050', '510300',
  '510310', '510500', '512100', '588000', 'sh', 'sz',
];

function jsonError(code, message, status) {
  return new Response(JSON.stringify({ error: { code, message } }), {
    status,
    headers: { 'Content-Type': 'application/json; charset=utf-8', ...CORS_HEADERS },
  });
}

function jsonOk(data) {
  return new Response(JSON.stringify(data), {
    status: 200,
    headers: { 'Content-Type': 'application/json; charset=utf-8', ...CORS_HEADERS },
  });
}

// 读取 R2 数据（复用 dataRewriteHandler 模式）：R2 key -> JSON，404/错误回退 ASSETS。
async function readJsonFile(env, request, key) {
  let text = null;
  try {
    const object = await env.R2_BUCKET.get(key);
    if (object) text = await object.text();
  } catch (e) {
    // R2 错误，回退 ASSETS
  }
  // 回退 ASSETS：直接请求 static-site 里的源文件路径（/data/<file>）
  if (text == null) {
    try {
      const filePath = '/' + key; // "data/sentiment-3m.json" -> "/data/sentiment-3m.json"
      const res = await env.ASSETS.fetch(new Request(request.url.origin + filePath, request));
      if (res.ok) text = await res.text();
    } catch (e) { /* ignore */ }
  }
  if (text == null) return null;
  try {
    return JSON.parse(text);
  } catch (e) {
    return null;
  }
}

// ---- 时间 ----
// 限流/计量的「分钟/日」桶统一用 Asia/Shanghai（UTC+8）本地时，非 Worker 默认的 UTC：
// Worker 的 new Date() 返回 UTC（wrangler.jsonc 未设 time_zone），直接用会把「每日」桶在
// 08:00 北京时重置（UTC 午夜），与中国市场日界语义不符。此处 +8h 后取 UTC 分量即得北京时。
function beijingNow() {
  return new Date(Date.now() + 8 * 3600 * 1000);
}
function fmtTime(d, fmt) {
  const pad = n => String(n).padStart(2, '0');
  return fmt
    .replace('YYYY', String(d.getUTCFullYear()))
    .replace('MM', pad(d.getUTCMonth() + 1))
    .replace('DD', pad(d.getUTCDate()))
    .replace('HH', pad(d.getUTCHours()))
    .replace('mm', pad(d.getUTCMinutes()));
}

// ---- 鉴权 ----
// 取请求中的 key：Authorization: Bearer <key> 或 X-API-Key: <key>
function extractApiKey(request) {
  const auth = request.headers.get('Authorization') || '';
  if (auth.startsWith('Bearer ')) {
    const k = auth.slice(7).trim();
    if (k) return k;
  }
  return (request.headers.get('X-API-Key') || '').trim() || null;
}

// SHA-256 摘要（Web Crypto），key 只存 hash
async function hashKey(key) {
  const data = new TextEncoder().encode('api-key:' + key);
  const digest = await crypto.subtle.digest('SHA-256', data);
  return [...new Uint8Array(digest)].map(b => b.toString(16).padStart(2, '0')).join('');
}

// KV 计数（无 CAS，get+increment 允许少量误差）
async function kvIncr(env, k, ttlSeconds) {
  const cur = parseInt((await env.SUBSCRIBE_KV.get(k)) || '0', 10);
  const next = (isNaN(cur) ? 0 : cur) + 1;
  await env.SUBSCRIBE_KV.put(k, String(next), ttlSeconds ? { expirationTtl: ttlSeconds } : {});
  return next;
}

async function kvGetNum(env, k) {
  const v = await env.SUBSCRIBE_KV.get(k);
  const n = parseInt(v || '0', 10);
  return isNaN(n) ? 0 : n;
}

// 限流检查 + 计量，返回 null 通过 / 或错误 Response
// 配额可经 KV 覆盖（api_quota:<hash>:minute / :day），默认 60 req/min、5000 req/day。
async function enforceQuota(env, hash, category) {
  const now = beijingNow();
  const dayKey = fmtTime(now, 'YYYYMMDD');
  const minKey = fmtTime(now, 'YYYYMMDDHHmm');

  const minQuota = parseInt((await env.SUBSCRIBE_KV.get(`api_quota:${hash}:minute`)) || '60', 10) || 60;
  const dayQuota = parseInt((await env.SUBSCRIBE_KV.get(`api_quota:${hash}:day`)) || '5000', 10) || 5000;

  const minKeyFull = `api_usage_lim:${hash}:m:${minKey}`;
  const dayKeyFull = `api_usage_lim:${hash}:d:${dayKey}`;

  const mCount = await kvGetNum(env, minKeyFull);
  const dCount = await kvGetNum(env, dayKeyFull);
  if (mCount >= minQuota) {
    return jsonError('rate_limit', `分钟请求超限（每分钟上限 ${minQuota}，请稍后再试）`, 429);
  }
  if (dCount >= dayQuota) {
    return jsonError('rate_limit', `每日请求超限（每日上限 ${dayQuota}）`, 429);
  }
  await kvIncr(env, minKeyFull, 90);   // 分钟窗口 90s 残留容忍
  await kvIncr(env, dayKeyFull, 86400 + 60);
  return null;
}

// 计量：每 5 分钟聚合写 KV（api_usage:<hash>:<yyyyMMddHH + 5min桶>），供计费拉取。
async function recordUsage(env, hash, category) {
  const now = beijingNow();
  const bucket = Math.floor(now.getUTCMinutes() / 5) * 5; // 0/5/10/.../55
  const key = `api_usage:${hash}:${fmtTime(now, 'YYYYMMDDHH')}${String(bucket).padStart(2, '0')}`;
  try {
    const cur = await env.SUBSCRIBE_KV.get(key);
    let arr = [];
    if (cur) {
      try { arr = JSON.parse(cur); } catch (e) { arr = []; }
      if (!Array.isArray(arr)) arr = [];
    }
    arr.push({ category, ts: new Date().toISOString() });
    // 简单截断防单桶过大（KV value 上限 25MB，安全起见截 1000 条/桶）
    if (arr.length > 1000) arr = arr.slice(-1000);
    await env.SUBSCRIBE_KV.put(key, JSON.stringify(arr), { expirationTtl: 86400 * 90 });
  } catch (e) { /* 计量失败不阻断查询 */ }
}

// ---- 数据加工 ----
// 最新一天快照：从字段列表取每条记录的最后一条，扁平为 {字段名: {date,value,...}} 不含全量
function latestSnapshot(fields, obj) {
  const out = {};
  for (const f of fields) {
    const arr = obj[f];
    if (Array.isArray(arr) && arr.length) {
      out[f] = arr[arr.length - 1];
    } else {
      out[f] = null;
    }
  }
  return out;
}

// range 切片：字段列表在 [start,end] 闭区间的记录。start/end 为 'YYYYMMDD' 或 null。
function rangeSlice(fields, obj, start, end) {
  const out = {};
  for (const f of fields) {
    const arr = obj[f];
    if (!Array.isArray(arr)) { out[f] = []; continue; }
    let slice = arr;
    if (start) {
      const s = start.replace(/-/g, '');
      slice = slice.filter(r => (r.date || '').replace(/-/g, '') >= s);
    }
    if (end) {
      const e = end.replace(/-/g, '');
      slice = slice.filter(r => (r.date || '').replace(/-/g, '') <= e);
    }
    out[f] = slice;
  }
  return out;
}

function latestDateOf(arr) {
  if (!Array.isArray(arr) || !arr.length) return null;
  return arr[arr.length - 1].date || null;
}

// summary：跨类别聚合今日值（恐贪+A股情绪+跨市场+大盘预警）
async function summaryHandler(request, env) {
  const senti = await readJsonFile(env, request, 'data/sentiment-3m.json');
  const alert = await readJsonFile(env, request, 'data/alert.json');
  const out = { generated_at: new Date().toISOString() };
  if (senti) {
    const s = latestSnapshot(['fear_greed', 'a_sentiment', 'cross_market'], senti);
    out.sentiment = { date: latestDateOf(senti.fear_greed), ...s };
  } else {
    out.sentiment = null;
  }
  if (alert && alert.date) {
    out.alert = {
      date: alert.date,
      high: alert.high ? { score: alert.high.score, level: alert.high.level, triggered: alert.high.triggered } : null,
      low: alert.low ? { score: alert.low.score, level: alert.low.level, triggered: alert.low.triggered } : null,
    };
  } else {
    out.alert = null;
  }
  return jsonOk(out);
}

// 默认类别处理（sentiment/alert）：按 action 分派
async function handleCategory(request, env, category, action, url) {
  const src = CATEGORY_SOURCES[category];
  if (!src) return jsonError('not_found', `未知类别: ${category}`, 404);

  if (action === 'summary') {
    return summaryHandler(request, env); // 跨类别聚合
  }

  const obj = await readJsonFile(env, request, src.file);
  if (!obj) return jsonError('data_unavailable', '数据源暂不可用', 503);

  if (category === 'alert') {
    // alert 结构特殊（date/high/low/history 非字段数组）
    if (action === 'latest') {
      return jsonOk({ date: obj.date, high: obj.high, low: obj.low, generated_at: obj.generated_at || null });
    }
    if (action === 'range') {
      const start = (url.searchParams.get('start') || '').replace(/-/g, '') || null;
      const end = (url.searchParams.get('end') || '').replace(/-/g, '') || null;
      const history = Array.isArray(obj.history) ? obj.history : [];
      let slice = history;
      if (start) slice = slice.filter(r => (r.date || '').replace(/-/g, '') >= start);
      if (end) slice = slice.filter(r => (r.date || '').replace(/-/g, '') <= end);
      return jsonOk({ date: obj.date, history: slice });
    }
    return jsonError('bad_request', `alert 类别不支持操作: ${action}`, 400);
  }

  // sentiment: 聚合字段
  if (action === 'latest') {
    return jsonOk({ date: latestDateOf(obj[src.fields[0]]), ...latestSnapshot(src.fields, obj) });
  }
  if (action === 'range') {
    const start = (url.searchParams.get('start') || '').replace(/-/g, '') || null;
    const end = (url.searchParams.get('end') || '').replace(/-/g, '') || null;
    return jsonOk(rangeSlice(src.fields, obj, start, end));
  }
  return jsonError('bad_request', `类别 ${category} 不支持操作: ${action}`, 400);
}

// signals: 按标的读 alert_analyze_<target>.json；缺 target 返回支持列表
async function handleSignals(request, env, action, url) {
  const target = (url.searchParams.get('target') || '').trim();
  if (!target) {
    return jsonOk({ supported_targets: KNOWN_ALERT_TARGETS, message: '请带 ?target=<标的id> 查询' });
  }
  const obj = await readJsonFile(env, request, `data/alert_analyze_${target}.json`);
  if (!obj) {
    return jsonError('not_found', `标的 ${target} 无技术信号分解数据（支持列表见 /api/data/signals 无 target 调用）`, 404);
  }
  if (action === 'latest') {
    return jsonOk({
      target_id: obj.target_id,
      target_name: obj.target_name,
      target_type: obj.target_type,
      alert: obj.alert,
      reason: obj.reason,
    });
  }
  // signals 是单标的快照（alert/reason 非时间序列），不支持 range
  return jsonError('bad_request', `signals 类别不支持操作: ${action}（仅支持 latest）`, 400);
}

// 入口：/api/data/<category>/<action>
export default async function dataQueryHandler(request, env) {
  // CORS preflight
  if (request.method === 'OPTIONS') {
    return new Response(null, { status: 204, headers: CORS_HEADERS });
  }
  if (request.method !== 'GET') {
    return jsonError('method_not_allowed', '仅支持 GET', 405);
  }

  const url = new URL(request.url);
  // pathname 形如 /api/data/sentiment/latest；也支持跨类别聚合 /api/data/summary（1 段）
  const rest = url.pathname.replace(/^\/api\/data\//, '');
  const parts = rest.split('/').filter(Boolean);
  const isCrossSummary = parts.length === 1 && parts[0] === 'summary';
  if (!isCrossSummary && parts.length !== 2) {
    return jsonError('bad_request', '用法: /api/data/<category>/<latest|range|summary> 或 /api/data/summary', 400);
  }
  const category = isCrossSummary ? 'summary' : parts[0];
  const action = isCrossSummary ? 'summary' : parts[1];
  if (action !== 'latest' && action !== 'range' && action !== 'summary') {
    return jsonError('bad_request', `不支持的操作: ${action}（可选 latest/range/summary）`, 400);
  }

  // 鉴权：未带 key 或无效 = 401，不降级公开
  const key = extractApiKey(request);
  if (!key) {
    return jsonError('unauthorized', '缺少 API key（Authorization: Bearer <key> 或 X-API-Key: <key>）', 401);
  }
  const hash = await hashKey(key);
  const stored = await env.SUBSCRIBE_KV.get(`api_key:${hash}`);
  if (!stored) {
    return jsonError('unauthorized', 'API key 无效', 401);
  }

  // 限流
  const quotaErr = await enforceQuota(env, hash, category);
  if (quotaErr) return quotaErr;

  // 计量（鉴权通过才计，每 5 分钟聚合）
  await recordUsage(env, hash, category);

  // 分发
  if (category === 'signals') {
    return handleSignals(request, env, action, url);
  }
  if (category === 'summary') {
    // 跨类别聚合：恐贪+A股情绪+跨市场+大盘预警今日值
    return summaryHandler(request, env);
  }
  return handleCategory(request, env, category, action, url);
}
