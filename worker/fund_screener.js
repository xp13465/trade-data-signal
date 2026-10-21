// 公募基金筛选器查询 API（#266 一期, 2026-10-19）。
// 数据源: D1 trade-fund-score.fund_screener（scripts/sync_fund_screener_to_d1.sh 全量同步,
//   全市场 1 行/只, PK=fund_code; 每字段取「该基金最新可用分区」——评分字段取该基金最近一次
//   有 composite_score 的分区, 因此工作日行数不再缩到头部 2000 只）。
// 路由: GET /api/fund_screener（worker/headers.js 分发到此; 未登录 401）。
//
// 参数（全部白名单 → 服务端参数化 WHERE, 防注入）:
//   page/size   分页（默认 1 / 20, size 上限 100）
//   sort/dir    排序列白名单 + asc|desc
//   search      基金代码/名称模糊搜索（LIKE, % _ ' 转义）
//   types       基金类型多选（逗号分隔 → IN (...)）
//   purchase_status  申购状态多选（逗号分隔 → IN (...)）
//   company     基金公司精确匹配
//   min_<col>/max_<col>  数值区间条件（col 见 RANGE_FIELDS; 含 min_rating_any /
//               min_five_star_count / min_morningstar 三个「至少 N」型）
//   facets=1    附带面板数据: 类型分布/基金公司列表/申购状态分布/字段覆盖率（首屏或开面板时请求）
//   except=col  只算「另有 N 只因该字段缺失被排除」; 不传则对全部生效的区间字段逐字段算
//
// 响应: { date, built_at, fund_total, total, pages, page, size, missing:{col:n}, data:[...] }
//   missing = 「另有 N 只因该字段缺失被排除」: 对每个生效的区间字段, 统计**除该字段自身条件外**
//   其余条件全满足、但该字段为 NULL 的行数（前端逐条显式标注, 防 §23.6 入样宇宙静默缩水）。
//   口径注意: sharpe/sortino/calmar/information_ratio 列 = fund_score 的**近 3 年**值
//   （与 /api/fund_score 同源同口径）; max_drawdown_3y 为百分数（40.88 = 回撤 40.88%）。
import { jsonResponse, corsHeaders, getSessionUser } from './auth.js';

// ── 排序白名单（全部数值/文本列; 表内列名硬编码, 不来自请求） ──
export const SORTABLE = new Set([
  'composite_score', 'star_rating', 'score_return', 'score_risk_adjusted', 'score_drawdown',
  'score_stability', 'score_scale', 'score_fee', 'sharpe', 'sortino', 'calmar',
  'information_ratio', 'alpha', 'manager_score', 'm1_tenure', 'm2_scale', 'm3_perf_stability',
  'm4_drawdown', 'm5_coherence', 'm6_focus', 'kelly_fraction', 'half_kelly_position',
  'kelly_win_rate', 'kelly_win_loss_ratio', 'market_adjustment', 'final_suggestion',
  'data_completeness', 'scale', 'setup_years', 'management_fee', 'custody_fee', 'purchase_fee',
  'service_fee', 'return_1m', 'return_3m', 'return_6m', 'return_1y', 'return_2y', 'return_3y',
  'return_ytd', 'return_since_inception', 'volatility_1y', 'volatility_3y', 'max_drawdown_3y',
  'tenure_years', 'work_years', 'manager_scale', 'manager_best_return', 'rating_shanghai',
  'rating_cms', 'rating_jajx', 'rating_morningstar', 'rating_five_star_count', 'purchase_min',
  'daily_limit', 'fund_name', 'fund_type', 'setup_date',
]);

// ── 区间条件字段（min_X / max_X）; name = 请求参数名中的 X, col = 表列名 ──
export const RANGE_FIELDS = [
  // 基础
  { name: 'scale', col: 'scale' }, { name: 'setup_years', col: 'setup_years' },
  // 收益（fund_performance 该基金最新日）
  { name: 'return_1m', col: 'return_1m' }, { name: 'return_3m', col: 'return_3m' },
  { name: 'return_6m', col: 'return_6m' }, { name: 'return_1y', col: 'return_1y' },
  { name: 'return_3y', col: 'return_3y' }, { name: 'return_ytd', col: 'return_ytd' },
  { name: 'return_since_inception', col: 'return_since_inception' },
  // 风险（3y 口径; vol 另有 1y）
  { name: 'volatility_1y', col: 'volatility_1y' }, { name: 'volatility_3y', col: 'volatility_3y' },
  { name: 'max_drawdown_3y', col: 'max_drawdown_3y' },
  { name: 'sharpe', col: 'sharpe' }, { name: 'sortino', col: 'sortino' },
  { name: 'calmar', col: 'calmar' }, { name: 'information_ratio', col: 'information_ratio' },
  // 评分（含 6 维子分）
  { name: 'composite_score', col: 'composite_score' }, { name: 'star_rating', col: 'star_rating' },
  { name: 'score_return', col: 'score_return' },
  { name: 'score_risk_adjusted', col: 'score_risk_adjusted' },
  { name: 'score_drawdown', col: 'score_drawdown' },
  { name: 'score_stability', col: 'score_stability' },
  { name: 'score_scale', col: 'score_scale' }, { name: 'score_fee', col: 'score_fee' },
  // 经理
  { name: 'manager_score', col: 'manager_score' }, { name: 'tenure_years', col: 'tenure_years' },
  { name: 'work_years', col: 'work_years' }, { name: 'manager_scale', col: 'manager_scale' },
  { name: 'manager_best_return', col: 'manager_best_return' },
  // 费用
  { name: 'management_fee', col: 'management_fee' },
  { name: 'custody_fee', col: 'custody_fee' }, { name: 'purchase_fee', col: 'purchase_fee' },
  { name: 'service_fee', col: 'service_fee' },
  // 评级
  { name: 'rating_shanghai', col: 'rating_shanghai' }, { name: 'rating_cms', col: 'rating_cms' },
  { name: 'rating_jajx', col: 'rating_jajx' },
  { name: 'rating_morningstar', col: 'rating_morningstar' },
  { name: 'rating_five_star_count', col: 'rating_five_star_count' },
  // 仓位
  { name: 'half_kelly_position', col: 'half_kelly_position' },
  { name: 'final_suggestion', col: 'final_suggestion' },
];

// 「任一机构评级 ≥ N」型（三列取或; 全空则该基金不入选）
export const RATING_ANY_COLS = ['rating_shanghai', 'rating_cms', 'rating_jajx', 'rating_morningstar'];

// 多选字段（逗号分隔 → IN）与精确匹配字段
export const MULTI_FIELDS = [{ param: 'types', col: 'fund_type' },
                             { param: 'purchase_status', col: 'purchase_status' }];
export const EXACT_FIELDS = [{ param: 'company', col: 'fund_company' }];

// 覆盖率/缺失计数只对「区间条件字段」有意义（多选/精确匹配字段本身无空值语义）
export const FILTER_PARAM_FIELDS = RANGE_FIELDS.map((f) => f.name).concat(['rating_any']);

const COVERAGE_COLS = RANGE_FIELDS.map((f) => f.col).concat(['fund_company']);

// LIKE 转义: \ % _
function escapeLike(s) {
  return s.replace(/[\\%_']/g, (ch) => '\\' + ch);
}

function num(v) {
  if (v === null || v === undefined || v === '') return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function csv(v) {
  return String(v || '').split(',').map((s) => s.trim()).filter((s) => s !== '');
}

// 纯函数: 请求 query → { conds, invalid }（conds 每项 { field, sql, binds }）
//   field = 该条件归属的表列（供「另有 N 只因该字段缺失被排除」按字段剔除自身条件用）;
//   sql/binds 只由白名单列名 + 参数占位符构成, 请求值一律走 bind（防注入）。
export function buildFilter(q) {
  const conds = [];
  const invalid = [];

  for (const { name, col } of RANGE_FIELDS) {
    const lo = num(q.get('min_' + name));
    const hi = num(q.get('max_' + name));
    if (q.get('min_' + name) !== null && lo === null) invalid.push('min_' + name);
    if (q.get('max_' + name) !== null && hi === null) invalid.push('max_' + name);
    if (lo !== null) conds.push({ field: col, sql: `${col} >= ?`, binds: [lo] });
    if (hi !== null) conds.push({ field: col, sql: `${col} <= ?`, binds: [hi] });
  }

  const ratingAny = num(q.get('min_rating_any'));
  if (q.get('min_rating_any') !== null && ratingAny === null) invalid.push('min_rating_any');
  if (ratingAny !== null) {
    conds.push({
      field: 'rating_any',
      sql: '(' + RATING_ANY_COLS.map((c) => `COALESCE(${c}, 0) >= ?`).join(' OR ') + ')',
      binds: RATING_ANY_COLS.map(() => ratingAny),
    });
  }

  for (const { param, col } of MULTI_FIELDS) {
    const vals = csv(q.get(param));
    if (vals.length) {
      conds.push({
        field: col,
        sql: `${col} IN (${vals.map(() => '?').join(', ')})`,
        binds: vals,
      });
    }
  }
  for (const { param, col } of EXACT_FIELDS) {
    const v = (q.get(param) || '').trim();
    if (v) conds.push({ field: col, sql: `${col} = ?`, binds: [v] });
  }

  const search = (q.get('search') || '').trim();
  if (search) {
    const like = '%' + escapeLike(search) + '%';
    conds.push({
      field: null, // 搜索不参与「字段缺失」统计
      sql: "(fund_code LIKE ? ESCAPE '\\' OR fund_name LIKE ? ESCAPE '\\')",
      binds: [like, like],
    });
  }
  return { conds, invalid };
}

// 由 conds 组装 WHERE（可排除某字段自身的条件, 供缺失计数用）
export function whereOf(conds, excludeField) {
  const use = excludeField ? conds.filter((c) => c.field !== excludeField) : conds;
  return {
    sql: use.length ? 'WHERE ' + use.map((c) => c.sql).join(' AND ') : '',
    binds: use.flatMap((c) => c.binds),
  };
}

// 注: 同表列名在白名单里出现两次（scale/fund_name 等已在上面 SORTABLE 中列出）, Set 去重无害。

async function readMeta(env) {
  try {
    const { results } = await env.FUND_SCORE_DB.prepare('SELECT key, value FROM screener_meta').all();
    const m = {};
    for (const r of results || []) {
      try { m[r.key] = JSON.parse(r.value); } catch { m[r.key] = r.value; }
    }
    return m;
  } catch {
    return {};
  }
}

export default async function fundScreenerHandler(request, env) {
  if (request.method === 'OPTIONS') {
    return new Response(null, { status: 204, headers: corsHeaders(request) });
  }
  if (request.method !== 'GET') {
    return jsonResponse({ detail: 'Method Not Allowed' }, 405, { request });
  }

  // 鉴权: 与 /api/fund_score 同档（登录用户特权; 未登录 401, 前端走 Top100 降级态）
  const session = await getSessionUser(request, env);
  if (!session) {
    return jsonResponse({ detail: '未登录（基金筛选为登录用户特权）' }, 401, { request });
  }

  const q = new URL(request.url).searchParams;

  let page = parseInt(q.get('page') || '1', 10);
  if (!Number.isFinite(page) || page < 1) page = 1;
  let size = parseInt(q.get('size') || '20', 10);
  if (!Number.isFinite(size) || size < 1) size = 20;
  if (size > 100) size = 100;

  const sort = SORTABLE.has(q.get('sort')) ? q.get('sort') : 'composite_score';
  const dir = q.get('dir') === 'asc' ? 'ASC' : 'DESC';

  const { conds, invalid } = buildFilter(q);
  const { sql: whereSql, binds } = whereOf(conds, null);

  // 生效的区间字段（逐个算「另有 N 只因该字段缺失被排除」; 可用 except= 只算一个）
  const onlyField = (q.get('except') || '').trim();
  const activeFields = [];
  for (const { col } of RANGE_FIELDS) {
    if (!conds.some((c) => c.field === col)) continue;
    if (onlyField && onlyField !== col) continue;
    activeFields.push(col);
  }
  if (conds.some((c) => c.field === 'rating_any')
      && (!onlyField || onlyField === 'rating_any')) {
    activeFields.push('rating_any');
  }

  try {
    const countRow = await env.FUND_SCORE_DB
      .prepare(`SELECT COUNT(*) AS n FROM fund_screener ${whereSql}`)
      .bind(...binds)
      .first();
    const total = (countRow && countRow.n) || 0;
    const pages = Math.max(1, Math.ceil(total / size));
    if (page > pages) page = pages;
    const offset = (page - 1) * size;

    const [rowsRes, meta, ...missingRes] = await Promise.all([
      env.FUND_SCORE_DB
        .prepare(`SELECT * FROM fund_screener ${whereSql} `
          + `ORDER BY ${sort} ${dir}, fund_code ASC LIMIT ? OFFSET ?`)
        .bind(...binds, size, offset)
        .all(),
      readMeta(env),
      // 逐字段缺失计数: 除该字段自身条件外的全部条件 + 该字段 IS NULL
      ...activeFields.map((col) => {
        const w = whereOf(conds, col); // 剔除该字段自身的条件, 其余条件全带上
        const nullPred = col === 'rating_any'
          ? '(' + RATING_ANY_COLS.map((c) => `${c} IS NULL`).join(' AND ') + ')'
          : `${col} IS NULL`;
        const pre = w.sql ? `${w.sql} AND ` : 'WHERE ';
        return env.FUND_SCORE_DB
          .prepare(`SELECT COUNT(*) AS n FROM fund_screener ${pre}${nullPred}`)
          .bind(...w.binds)
          .first();
      }),
    ]);

    const missing = {};
    activeFields.forEach((col, i) => {
      missing[col] = (missingRes[i] && missingRes[i].n) || 0;
    });

    const payload = {
      date: (meta.source_dates && meta.source_dates.score_latest) || null,
      built_at: meta.built_at || null,
      fund_total: meta.fund_total || null,
      total,
      pages,
      page,
      size,
      missing,
      data: (rowsRes && rowsRes.results) || [],
    };
    if (invalid.length) payload.invalid_params = invalid;

    // 面板数据（类型分布/公司列表/申购状态分布/覆盖率）只在显式请求时附带
    if (q.get('facets') === '1') {
      const cov = meta.coverage || {};
      const coverage = {};
      for (const col of COVERAGE_COLS) coverage[col] = cov[col] || 0;
      const [types, companies, statuses] = await Promise.all([
        env.FUND_SCORE_DB.prepare(
          "SELECT fund_type AS k, COUNT(*) AS n FROM fund_screener "
          + "WHERE fund_type IS NOT NULL AND fund_type != '' GROUP BY fund_type ORDER BY n DESC").all(),
        env.FUND_SCORE_DB.prepare(
          'SELECT fund_company AS k, COUNT(*) AS n FROM fund_screener '
          + 'WHERE fund_company IS NOT NULL AND fund_company != \'\' '
          + 'GROUP BY fund_company ORDER BY n DESC LIMIT 500').all(),
        env.FUND_SCORE_DB.prepare(
          "SELECT purchase_status AS k, COUNT(*) AS n FROM fund_screener "
          + "WHERE purchase_status IS NOT NULL AND purchase_status != '' "
          + 'GROUP BY purchase_status ORDER BY n DESC').all(),
      ]);
      payload.facets = {
        type_counts: ((types && types.results) || []).map((r) => ({ type: r.k, n: r.n })),
        company_counts: ((companies && companies.results) || []).map((r) => ({ company: r.k, n: r.n })),
        purchase_status_counts: ((statuses && statuses.results) || []).map((r) => ({ status: r.k, n: r.n })),
        coverage,
        fund_total: meta.fund_total || null,
      };
    }
    return jsonResponse(payload, 200, { request });
  } catch (e) {
    return jsonResponse(
      { detail: 'D1 查询失败: ' + ((e && e.message) || String(e)) }, 500, { request });
  }
}