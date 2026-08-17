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
    shape: 'sentiment',
  },
  // alert: 大盘预警，源文件 alert.json（含 date/high/low/history）
  alert: {
    file: 'data/alert.json',
    shape: 'alert',
  },
  // ---- 2026-08-17 一次性加满 12 类 ----
  // market: 综合评分/信号灯/今日信号，源 overview.json（单日快照）
  market: { file: 'data/overview.json', shape: 'market' },
  // a_stock: 只暴露 metrics 宽度指标（上涨家数/涨停等），绝不暴露 indices 原始行情（合规红线）
  a_stock: { file: 'data/a-stock-3m.json', shape: 'a_stock' },
  // rotation: 板块轮动速度（data 数组按日期）
  rotation: { file: 'data/rotation.json', shape: 'array' },
  // position: 各大指数点位+分位数（positions 快照数组）
  position: { file: 'data/position.json', shape: 'position' },
  // ma_alignment: 多头/空头/金叉死叉家数（data 数组按日期）
  ma_alignment: { file: 'data/ma_alignment.json', shape: 'array' },
  // volume_ratio: 全市场量能（data 数组按日期）
  volume_ratio: { file: 'data/volume_ratio.json', shape: 'array' },
  // new_high_low: 52周/20日新高新低家数（data 数组按日期）
  new_high_low: { file: 'data/new_high_low.json', shape: 'array' },
  // futures: 机构多空持仓/多空比（summary + positions_ratio）
  futures: { file: 'data/futures.json', shape: 'futures' },
  // signal_freq: 买卖信号频率（monthly_avg/year_count/total_count 聚合）
  signal_freq: { file: 'data/signal_freq.json', shape: 'signal_freq' },
  // fund_score: 基金评分 top 列表（80KB 小文件）
  fund_score: { file: 'data/fund_score_top.json', shape: 'fund_score' },
  // etf_score: ETF 评分列表（P0-2 拆分三文件，走 handleCategory 特殊分支读 buy/sell/hold；file 仅为元信息）
  etf_score: { file: 'data/etf_score_list_buy.json', shape: 'etf_score' },
  // etf_national_team: 国家队 ETF 持仓（etfs 数组）
  etf_national_team: { file: 'data/etf_national_team-1y.json', shape: 'etf_national_team' },
  // ---- 2026-08-17 第二批上架：AI 预测 + ETF 快捷挑选（UUMit 数据广场按次售卖）----
  // ai_prediction: AI 每日预测（daily_brief.json meta+text）+ 预测基准日对应新闻（news_digest/<date>.json）
  ai_prediction: { file: 'data/daily_brief.json', shape: 'ai_prediction' },
  // etf_pick: ETF 评分快捷返回（buy/sell/hold 三文件，?count=N 默认5 上限10，挑不同档位）
  etf_pick: { file: 'data/etf_score_list_buy.json', shape: 'etf_pick' },
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

// ---- 大文件「数组头部」读取器（etf_score_list_hold.json 17MB，Worker 读全量会超时/烧内存）----
// 只读文件头部 maxBytes 字节（R2 range / ASSETS Range），定位 "<listField>": [ 后，
// 扫描提取前 n 个完整对象（处理字符串内括号/转义），拼成 {"<listField>":[...]} 再 JSON.parse。
// 返回 { field, items, truncated }；文件不存在/解析失败返回 null。
async function readJsonListHead(env, request, key, listField, n, maxBytes) {
  const text = await readJsonHead(env, request, key, maxBytes);
  if (text == null) return null;
  const arr = extractArrayHead(text, listField, n);
  if (arr == null) return null;
  let parsed = null;
  try {
    // arr.json = "[ {...objN} "（缺闭合 ]），补上闭合括号再解析
    parsed = JSON.parse(`{"${listField}":${arr.json}]}`);
  } catch (e) {
    parsed = null;
  }
  return parsed ? { items: parsed[listField], truncated: arr.truncated } : null;
}

// 读取文件头部 maxBytes 字节文本（R2 range -> ASSETS Range 兜底）
async function readJsonHead(env, request, key, maxBytes) {
  try {
    const object = await env.R2_BUCKET.get(key, { range: { length: maxBytes } });
    if (object && object.body) {
      // R2 range 返回对象（httpEtag 可能为空但 size/body 可用）
      const size = object.size != null ? object.size : maxBytes;
      const reader = object.body.getReader();
      let out = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        out += new TextDecoder().decode(value, { stream: true });
        if (out.length >= maxBytes) break;
      }
      if (out.length) return out;
    }
  } catch (e) { /* 回退 ASSETS */ }
  try {
    const filePath = '/' + key;
    const res = await env.ASSETS.fetch(new Request(request.url.origin + filePath, {
      ...request,
      headers: { ...request.headers, Range: `bytes=0-${maxBytes - 1}` },
    }));
    if (res.ok) {
      const buf = await res.arrayBuffer();
      const txt = new TextDecoder().decode(buf);
      if (txt.length) return txt;
    }
  } catch (e) { /* ignore */ }
  return null;
}

// 从头部文本提取 "<listField>": [ ... ] 的前 n 个完整对象。
// 返回 { json: "[...]"（合法数组片段）, truncated: bool }；找不到字段/数组返回 null。
function extractArrayHead(text, listField, n) {
  const marker = `"${listField}":`;
  const fi = text.indexOf(marker);
  if (fi < 0) return null;
  const openBracket = text.indexOf('[', fi);
  if (openBracket < 0) return null;
  let i = openBracket + 1;
  const len = text.length;
  let depth = 0;         // {} 嵌套深度
  let inStr = false;
  let escape = false;
  let count = 0;
  let lastObjEnd = -1;   // 最后一个完整对象结束的 } 下标
  while (i < len) {
    const c = text[i];
    if (inStr) {
      if (escape) { escape = false; }
      else if (c === '\\') { escape = true; }
      else if (c === '"') { inStr = false; }
    } else {
      if (c === '"') { inStr = true; }
      else if (c === '{') { depth++; }
      else if (c === '}') {
        depth--;
        if (depth === 0) {
          // 完成一个顶层对象
          lastObjEnd = i;
          count++;
          if (count >= n) break;
        }
      }
    }
    i++;
  }
  if (lastObjEnd < 0) return null;
  const truncated = count < n;
  return { json: text.slice(openBracket, lastObjEnd + 1), truncated };
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

// summary：跨类别聚合今日值（按组聚合设计）。
// 只聚合「轻量状态组」小文件（sentiment/alert/market/signal_freq）——一次请求拿到今日市场全景概览，
// 不拉大文件（etf_score 17MB / etf_national_team / fund_score / futures 等走各自 latest 单独查，
// 避免 summary 每次调用都读全量大数据文件）。分组设计见 docs/api-data-query.md「summary 按组聚合」。
async function summaryHandler(request, env) {
  const senti = await readJsonFile(env, request, 'data/sentiment-3m.json');
  const alert = await readJsonFile(env, request, 'data/alert.json');
  const overview = await readJsonFile(env, request, 'data/overview.json');
  const sigfreq = await readJsonFile(env, request, 'data/signal_freq.json');
  const out = { generated_at: new Date().toISOString(), group: 'lightweight_status' };
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
  if (overview) {
    out.market = {
      date: overview.date,
      scores: overview.scores || null,
      signals_today: (overview.signals_today || []).map(s => ({ date: s.date, index_id: s.index_id, signal: s.signal, name: s.name, reason: s.reason })),
    };
  } else {
    out.market = null;
  }
  if (sigfreq) {
    out.signal_freq = sigfreq;
  } else {
    out.signal_freq = null;
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

  // 多文件/组合类 category 走专用 handler（不依赖单一 obj 预读）
  if (category === 'etf_score') {
    return shapeEtfScore(request, env, action, url);
  }
  if (category === 'etf_pick') {
    return shapeEtfPick(request, env, action, url);
  }
  if (category === 'ai_prediction') {
    return shapeAiPrediction(request, env, action, url);
  }

  const obj = await readJsonFile(env, request, src.file);
  if (!obj) return jsonError('data_unavailable', '数据源暂不可用', 503);

  // 新增 shape 类别（market/a_stock/rotation/.../etf_national_team）走 handleShaped
  if (src.shape && src.shape !== 'sentiment' && src.shape !== 'alert') {
    return handleShaped(request, env, category, action, url, obj);
  }

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

// ---- 通用数组切片（rotation/ma_alignment/volume_ratio/new_high_low 等 data 数组按日期）----
// obj.data = [{date, ...}],在 [start,end] 闭区间切片
function sliceDateArray(arr, start, end) {
  if (!Array.isArray(arr)) return [];
  let slice = arr;
  if (start) slice = slice.filter(r => (r.date || '').replace(/-/g, '') >= start);
  if (end) slice = slice.filter(r => (r.date || '').replace(/-/g, '') <= end);
  return slice;
}

// ---- 各 shape 的 latest/range 实现（2026-08-17 一次性加满）----

// market: overview.json 单日快照
function shapeMarket(action, obj, url) {
  if (action === 'latest') {
    return jsonOk({ date: obj.date, scores: obj.scores || null, signals_today: obj.signals_today || [] });
  }
  // range：overview 是单日文件，返回当日快照
  if (action === 'range') {
    return jsonOk({ date: obj.date, scores: obj.scores || null, signals_today: obj.signals_today || [] });
  }
  return jsonError('bad_request', `market 类别不支持操作: ${action}`, 400);
}

// a_stock: 只暴露 metrics 宽度指标（每指标 {name,unit,data:[{date,value}]}），绝不暴露 indices
function shapeAStock(action, obj, url) {
  const metrics = obj.metrics || {};
  const keys = Object.keys(metrics);
  if (action === 'latest') {
    const out = {};
    for (const k of keys) {
      const m = metrics[k];
      const arr = m && Array.isArray(m.data) ? m.data : [];
      out[k] = arr.length ? { name: m.name, unit: m.unit, date: arr[arr.length - 1].date, value: arr[arr.length - 1].value } : { name: m && m.name, unit: m && m.unit, value: null };
    }
    return jsonOk({ metrics: out });
  }
  if (action === 'range') {
    const start = (url.searchParams.get('start') || '').replace(/-/g, '') || null;
    const end = (url.searchParams.get('end') || '').replace(/-/g, '') || null;
    const out = {};
    for (const k of keys) {
      const m = metrics[k];
      out[k] = { name: m && m.name, unit: m && m.unit, data: sliceDateArray(m && m.data, start, end) };
    }
    return jsonOk({ metrics: out });
  }
  return jsonError('bad_request', `a_stock 类别不支持操作: ${action}`, 400);
}

// array shape（rotation/ma_alignment/volume_ratio/new_high_low）: data 数组按日期
function shapeArray(action, obj, url) {
  if (action === 'latest') {
    const data = Array.isArray(obj.data) ? obj.data : [];
    return jsonOk({ date: data.length ? data[data.length - 1].date : null, latest: data.length ? data[data.length - 1] : null });
  }
  if (action === 'range') {
    const start = (url.searchParams.get('start') || '').replace(/-/g, '') || null;
    const end = (url.searchParams.get('end') || '').replace(/-/g, '') || null;
    return jsonOk({ data: sliceDateArray(obj.data, start, end) });
  }
  return jsonError('bad_request', `类别不支持操作: ${action}`, 400);
}

// position: positions 快照数组（非时间序列，latest 返回全部）
function shapePosition(action, obj) {
  if (action === 'latest' || action === 'range') {
    return jsonOk({ positions: obj.positions || [] });
  }
  return jsonError('bad_request', `position 类别不支持操作: ${action}`, 400);
}

// futures: summary + 最新持仓/多空比
function shapeFutures(action, obj, url) {
  if (action === 'latest') {
    const pos = Array.isArray(obj.positions) ? obj.positions : [];
    const ratio = Array.isArray(obj.positions_ratio) ? obj.positions_ratio : [];
    return jsonOk({
      summary: obj.summary || null,
      latest_positions: pos.length ? pos[pos.length - 1] : null,
      latest_positions_ratio: ratio.length ? ratio[ratio.length - 1] : null,
    });
  }
  if (action === 'range') {
    const start = (url.searchParams.get('start') || '').replace(/-/g, '') || null;
    const end = (url.searchParams.get('end') || '').replace(/-/g, '') || null;
    return jsonOk({
      positions: sliceDateArray(obj.positions, start, end),
      positions_ratio: sliceDateArray(obj.positions_ratio, start, end),
    });
  }
  return jsonError('bad_request', `futures 类别不支持操作: ${action}`, 400);
}

// signal_freq: 买卖信号频率聚合（monthly_avg/year_count/total_count 等全字段）
function shapeSignalFreq(action, obj) {
  if (action === 'latest' || action === 'range') {
    return jsonOk(obj);
  }
  return jsonError('bad_request', `signal_freq 类别不支持操作: ${action}`, 400);
}

// fund_score: 基金评分 top 列表（80KB 小文件）
function shapeFundScore(action, obj) {
  if (action === 'latest' || action === 'range') {
    return jsonOk({ date: obj.date, count: obj.count, method: obj.method, data: obj.data || [] });
  }
  return jsonError('bad_request', `fund_score 类别不支持操作: ${action}`, 400);
}

// etf_score: ETF 评分列表（buy/sell/hold 拆分三文件，P0-2 后旧单文件 etf_score_list.json 已停更）
// 只读各文件头部（?limit=N 防读全量，默认 20 最大 100；hold 17MB 走 readJsonListHead 切片）。
// 保持旧响应结构 {date, updated_at, limit, total:{buy,sell,hold}, buy_list, sell_list, hold_list} 兼容。
async function shapeEtfScore(request, env, action, url) {
  let limit = 20;
  const l = parseInt((url.searchParams.get('limit') || ''), 10);
  if (!isNaN(l) && l > 0) limit = Math.min(l, 100);
  // 头部读取上限：每条带 30 行 ohlc 约 16KB，limit 条需 limit*17KB 余量
  const headBytes = Math.max(limit * 20 * 1024, 300 * 1024);

  // buy 文件 ~2MB 可读全量拿顶层 meta(date/updated_at/counts) + buy_list；sell/hold 读头部切片
  const [buyFull, sell, hold] = await Promise.all([
    readJsonFile(env, request, 'data/etf_score_list_buy.json'),
    readJsonListHead(env, request, 'data/etf_score_list_sell.json', 'sell_list', limit, headBytes),
    readJsonListHead(env, request, 'data/etf_score_list_hold.json', 'hold_list', limit, headBytes),
  ]);
  if (!buyFull && !sell && !hold) return jsonError('data_unavailable', '数据源暂不可用', 503);

  const buyList = (buyFull && Array.isArray(buyFull.buy_list) ? buyFull.buy_list : []).slice(0, limit);
  if (action === 'latest' || action === 'range') {
    return jsonOk({
      date: buyFull ? (buyFull.date || null) : null,
      updated_at: buyFull ? (buyFull.updated_at || null) : null,
      limit,
      total: {
        buy: buyFull ? (buyFull.buy_count || null) : null,
        sell: buyFull ? (buyFull.sell_count || null) : null,
        hold: buyFull ? (buyFull.hold_count || null) : null,
      },
      buy_list: buyList,
      sell_list: (sell && sell.items) || [],
      hold_list: (hold && hold.items) || [],
    });
  }
  return jsonError('bad_request', `etf_score 类别不支持操作: ${action}`, 400);
}

// 按该列表 score 的 min-max 三等分判档位（high/mid/low），只读源数据不加工新数字
function gradeOf(score, lo, hi) {
  if (score == null || hi === lo) return 'mid';
  const third = (hi - lo) / 3;
  if (score >= hi - third) return 'high';
  if (score <= lo + third) return 'low';
  return 'mid';
}

// 评分卡字段白名单（去除 ohlc 30 行大数组，保留评分卡核心；字段全部直读源文件，§22 不加工）
const ETF_PICK_FIELDS = ['etf_code', 'name', 'score', 'hands', 'amt_pct', 'dims', 'dim_hits', 'data_thresholds', 'history_analogy', 'confidence', 'sell_action', 'is_national_team'];

// etf_pick: ETF 评分快捷返回（buy/sell/hold 三文件，?count=N 默认5 上限10，挑不同档位）
// 口径（§23.3/§22）：按「买入/卖出/持有 + 评分档位(high/mid/low)+ 汪汪队」挑不同档位，
// 默认 buy 优先、sell 次之、hold 补充；hold 17MB 只读头部高评分切片，仅作补充档位。
async function shapeEtfPick(request, env, action, url) {
  let count = 5;
  const c = parseInt((url.searchParams.get('count') || ''), 10);
  if (!isNaN(c) && c > 0) count = Math.min(c, 10);
  if (action !== 'latest' && action !== 'range') {
    return jsonError('bad_request', `etf_pick 类别不支持操作: ${action}（仅支持 latest/range）`, 400);
  }
  // hold 头部读取量：count 只补充用，读约 600KB 覆盖高评分若干（含汪汪队）
  const headBytes = 600 * 1024;
  const [buyFull, sellFull, holdHead] = await Promise.all([
    readJsonFile(env, request, 'data/etf_score_list_buy.json'),
    readJsonFile(env, request, 'data/etf_score_list_sell.json'),
    readJsonListHead(env, request, 'data/etf_score_list_hold.json', 'hold_list', count * 2, headBytes),
  ]);
  const meta = buyFull || sellFull;

  const toCand = (rec, category, lo, hi) => {
    if (!rec) return null;
    const grade = gradeOf(rec.score, lo, hi);
    const pick = {};
    for (const f of ETF_PICK_FIELDS) if (rec[f] !== undefined) pick[f] = rec[f];
    pick.category = category;
    pick.grade = grade;
    return pick;
  };

  const buyList = (buyFull && Array.isArray(buyFull.buy_list)) ? buyFull.buy_list : [];
  const sellList = (sellFull && Array.isArray(sellFull.sell_list)) ? sellFull.sell_list : [];
  const holdList = (holdHead && holdHead.items) || [];

  const bScores = buyList.map(x => x.score).filter(v => v != null);
  const sScores = sellList.map(x => x.score).filter(v => v != null);
  const hScores = holdList.map(x => x.score).filter(v => v != null);
  const bRange = bScores.length ? [Math.min(...bScores), Math.max(...bScores)] : [0, 100];
  const sRange = sScores.length ? [Math.min(...sScores), Math.max(...sScores)] : [0, 100];
  const hRange = hScores.length ? [Math.min(...hScores), Math.max(...hScores)] : [0, 100];

  // 候选池：buy -> sell -> hold（优先级），组内按 score 降序
  const pool = [
    ...buyList.map(r => toCand(r, 'buy', bRange[0], bRange[1])).filter(Boolean).sort((a, b) => (b.score || 0) - (a.score || 0)),
    ...sellList.map(r => toCand(r, 'sell', sRange[0], sRange[1])).filter(Boolean).sort((a, b) => (b.score || 0) - (a.score || 0)),
    ...holdList.map(r => toCand(r, 'hold', hRange[0], hRange[1])).filter(Boolean).sort((a, b) => (b.score || 0) - (a.score || 0)),
  ];

  // 按 (category, grade, is_national_team) 去重挑选，保证不同档位；不足则按优先级补足到 count
  const chosen = [];
  const used = new Set();
  for (const cand of pool) {
    if (chosen.length >= count) break;
    const key = `${cand.category}|${cand.grade}|${cand.is_national_team ? 'nt' : 'normal'}`;
    if (!used.has(key)) {
      used.add(key);
      chosen.push(cand);
    }
  }
  // 若去重后仍不足 count（档位组合有限），从候选池补充（可重复档位）
  if (chosen.length < count) {
    for (const cand of pool) {
      if (chosen.length >= count) break;
      if (!chosen.includes(cand)) chosen.push(cand);
    }
  }
  return jsonOk({
    date: meta ? (meta.date || null) : null,
    updated_at: meta ? (meta.updated_at || null) : null,
    count: chosen.length,
    total: meta ? { buy: meta.buy_count || null, sell: meta.sell_count || null, hold: meta.hold_count || null } : null,
    picks: chosen,
  });
}

// ai_prediction: AI 每日预测 + 预测基准日对应新闻（任务1，纯读，低成本）
// 新闻对齐（§22/§23.6）：daily_brief.meta.date 是预测基准日（如 20260814），对应新闻是
// news_digest/2026/<date>.json（基准日当天），不是"请求当天"。该日期文件不存在时附最近一份并标注。
async function shapeAiPrediction(request, env, action, url) {
  if (action !== 'latest' && action !== 'range') {
    return jsonError('bad_request', `ai_prediction 类别不支持操作: ${action}（仅支持 latest/range）`, 400);
  }
  const brief = await readJsonFile(env, request, 'data/daily_brief.json');
  if (!brief) return jsonError('data_unavailable', '数据源暂不可用', 503);

  const baseDate = (brief.meta && brief.meta.date) || null; // "20260814"
  const baseDash = baseDate ? `${baseDate.slice(0, 4)}-${baseDate.slice(4, 6)}-${baseDate.slice(6, 8)}` : null;

  let news = null;
  let news_note = null;
  if (baseDash) {
    const exact = await readJsonFile(env, request, `data/news_digest/2026/${baseDash}.json`);
    if (exact) {
      news = { date: exact.date || baseDash, sources: exact.sources || null, news: exact.news || [], upcoming: exact.upcoming || [] };
    }
  }
  if (!news) {
    // 基准日新闻文件不存在 -> 查 _index 找「<= 基准日」最接近的历史日（防 lookahead，绝不取未来新闻），并标注
    const idx = await readJsonFile(env, request, 'data/news_digest/_index.json');
    let nearest = null;
    if (idx && Array.isArray(idx.days)) {
      const target = (baseDash || '').replace(/-/g, '');
      const days = idx.days.filter(d => d && d.path);
      const le = days
        .filter(d => (d.date || '').replace(/-/g, '') <= target)
        .sort((a, b) => (b.date || '').localeCompare(a.date || ''));
      if (le.length) nearest = le[0];
      // le 为空（无 <= 基准日的历史归档）则不取未来新闻，走下方 news_note 标注
    }
    if (nearest && nearest.path) {
      const fallback = await readJsonFile(env, request, `data/${nearest.path}`);
      if (fallback) {
        news = { date: fallback.date || nearest.date, sources: fallback.sources || null, news: fallback.news || [], upcoming: fallback.upcoming || [] };
        news_note = `预测基准日 ${baseDash} 无对应新闻归档，已附最近一份（${fallback.date || nearest.date}）`;
      } else {
        news_note = `预测基准日 ${baseDash} 无对应新闻归档且无可用替代`;
      }
    } else {
      news_note = `预测基准日 ${baseDash} 无对应新闻归档`;
    }
  }
  return jsonOk({
    date: baseDash,
    meta: brief.meta || null,
    text: brief.text || null,
    disclaimer: brief.disclaimer || null,
    generated_at: brief.generated_at || null,
    news,
    news_note,
  });
}

// etf_national_team: 国家队 ETF 持仓（etfs 数组）
function shapeEtfNationalTeam(action, obj) {
  if (action === 'latest' || action === 'range') {
    return jsonOk({ updated_at: obj.updated_at, etfs: obj.etfs || [] });
  }
  return jsonError('bad_request', `etf_national_team 类别不支持操作: ${action}`, 400);
}

// 按 shape 分派到对应提取器；无 shape 的（sentiment/alert）走 handleCategory 既有逻辑
function handleShaped(request, env, category, action, url, obj) {
  const src = CATEGORY_SOURCES[category];
  const shape = src.shape;
  if (shape === 'sentiment' || shape === 'alert') return null; // 交给既有逻辑
  const map = {
    market: shapeMarket,
    a_stock: shapeAStock,
    array: shapeArray,
    position: shapePosition,
    futures: shapeFutures,
    signal_freq: shapeSignalFreq,
    fund_score: shapeFundScore,
    etf_national_team: shapeEtfNationalTeam,
    // 注：etf_score / etf_pick / ai_prediction 走 handleCategory 特殊分支（读多文件/组合数据），不入本 map
  };
  const fn = map[shape];
  if (!fn) return jsonError('bad_request', `类别 ${category} shape 未实现`, 500);
  return fn(action, obj, url);
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
