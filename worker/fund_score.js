// 场外基金评分全量查询 API（#79 方案C step4, 2026-08-22）。
// 数据源: D1 trade-fund-score.fund_score（scripts/sync_fund_score_to_d1.sh 全量同步,
//   最新 score_date 全市场 ≈27418 只, 含 fund_basic 扩展字段）。
// 路由: GET /api/fund_score（worker/headers.js 分发到此）。
//
// 参数:
//   page    页码, 默认 1（>=1）
//   size    每页条数, 默认 20, 上限 100
//   type    fund_type 精确筛选, 空或 "all" = 不筛
//   sort    排序列白名单: composite_score(默认)/half_kelly_position/final_suggestion/
//           sharpe/manager_score/star_rating/score_drawdown/score_stability
//   dir     asc/desc（默认 desc）
//   search  按基金代码/名称模糊搜索（LIKE, % _ ' 转义）
//
// 鉴权: 复用 auth.js session/Bearer 双模式 getSessionUser（与 /api/auth/me 同模式）。
//   基金评分为登录特权（PRIVILEGES_LOGGED_IN 含 'fund_score', 见 auth.js L42）:
//   未登录返回 401 {detail}, 登录后放行。前端 fetchJSON 带 credentials 同源 cookie。
// 响应: { date, method?, total, pages, page, size, data:[43字段...] }
//   date/method 取 sync_meta 表（score_date / score_method 随行数据）。
import { jsonResponse, corsHeaders, getSessionUser } from './auth.js';

const SORTABLE = new Set([
  'composite_score', 'half_kelly_position', 'final_suggestion',
  'sharpe', 'manager_score', 'star_rating', 'score_drawdown', 'score_stability',
]);

// LIKE 转义: \ % _
function escapeLike(s) {
  return s.replace(/[\\%_']/g, (ch) => '\\' + ch);
}

async function readMeta(env) {
  try {
    const { results } = await env.FUND_SCORE_DB
      .prepare('SELECT key, value FROM sync_meta')
      .all();
    const m = {};
    for (const r of results || []) m[r.key] = r.value;
    return m;
  } catch {
    return {};
  }
}

export default async function fundScoreHandler(request, env) {
  if (request.method === 'OPTIONS') {
    return new Response(null, { status: 204, headers: corsHeaders(request) });
  }
  if (request.method !== 'GET') {
    return jsonResponse({ detail: 'Method Not Allowed' }, 405, { request });
  }

  // 鉴权: 登录用户特权（未登录 401; 前端有 fund_score_top.json fallback 不白屏）
  const session = await getSessionUser(request, env);
  if (!session) {
    return jsonResponse(
      { detail: '未登录（基金评分为登录用户特权）' }, 401, { request });
  }

  const url = new URL(request.url);
  const q = url.searchParams;

  // 分页参数（size 上限 100 防 D1 全表拉取）
  let page = parseInt(q.get('page') || '1', 10);
  if (!Number.isFinite(page) || page < 1) page = 1;
  let size = parseInt(q.get('size') || '20', 10);
  if (!Number.isFinite(size) || size < 1) size = 20;
  if (size > 100) size = 100;

  // 排序参数（列名白名单拼接, 方向二选一, 防注入）
  const sort = SORTABLE.has(q.get('sort')) ? q.get('sort') : 'composite_score';
  const dir = q.get('dir') === 'asc' ? 'ASC' : 'DESC';

  // 筛选/搜索参数
  const type = (q.get('type') || '').trim();
  const search = (q.get('search') || '').trim();

  const where = [];
  const binds = [];
  if (type && type !== 'all') {
    where.push('fund_type = ?');
    binds.push(type);
  }
  if (search) {
    const like = '%' + escapeLike(search) + '%';
    where.push("(fund_code LIKE ? ESCAPE '\\' OR fund_name LIKE ? ESCAPE '\\')");
    binds.push(like, like);
  }
  const whereSql = where.length ? 'WHERE ' + where.join(' AND ') : '';

  try {
    // total（同 WHERE 条件计数, 前端算页数）
    const countRow = await env.FUND_SCORE_DB
      .prepare(`SELECT COUNT(*) AS n FROM fund_score ${whereSql}`)
      .bind(...binds)
      .first();
    const total = (countRow && countRow.n) || 0;
    const pages = Math.max(1, Math.ceil(total / size));
    if (page > pages) page = pages;

    const offset = (page - 1) * size;
    const { results } = await env.FUND_SCORE_DB
      .prepare(
        `SELECT * FROM fund_score ${whereSql} `
        + `ORDER BY ${sort} ${dir}, fund_code ASC LIMIT ? OFFSET ?`)
      .bind(...binds, size, offset)
      .all();

    const meta = await readMeta(env);
    // method 从首行取（score_method 随行同步, 如 v1.0_20260720）
    const method = (results && results[0] && results[0].score_method) || null;
    const payload = {
      date: meta.score_date || null,
      synced_at: meta.synced_at || null,
      total,
      pages,
      page,
      size,
      method,
      data: results || [],
    };
    // 类型分布（工具栏下拉）: types=1 且第一页时附全量 GROUP BY（省一次重复聚合）
    if (q.get('types') === '1' && page === 1) {
      try {
        const tc = await env.FUND_SCORE_DB
          .prepare('SELECT fund_type AS type, COUNT(*) AS n FROM fund_score '
            + "WHERE fund_type IS NOT NULL AND fund_type != '' "
            + 'GROUP BY fund_type ORDER BY n DESC')
          .all();
        payload.type_counts = (tc.results || []).map((r) => ({ type: r.type, n: r.n }));
      } catch {
        payload.type_counts = [];
      }
    }
    return jsonResponse(payload, 200, { request });
  } catch (e) {
    return jsonResponse(
      { detail: 'D1 查询失败: ' + ((e && e.message) || String(e)) }, 500, { request });
  }
}
