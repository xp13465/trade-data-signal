// #266 一期: worker/fund_screener.js 的 buildFilter/whereOf 行为机检（node, 无浏览器）。
// 由 scripts/tests/test_266_fund_screener_contract.py 通过 `node <本文件>` 调用;
// 退出码 0 = 全过, 1 = 有 FAIL（CI 沿用既有的 node + pytest 环境, 不引入新依赖）。
// 覆盖: 区间条件 / 非法值忽略 / **注入不落 SQL 文本**（全部走 bind）/ LIKE 转义 /
//       多选 IN / 任一机构评级 / 排序白名单 / 空条件无 WHERE / 参数名唯一。
import { buildFilter, whereOf, SORTABLE, RANGE_FIELDS } from '../../worker/fund_screener.js';

function Q(obj) { return new URLSearchParams(obj); }
let fail = 0;
const check = (name, cond, extra) => {
  if (!cond) { fail++; console.log('FAIL ' + name + (extra === undefined ? '' : ' | ' + extra)); }
  else console.log('ok   ' + name);
};
const bindsOf = (conds) => conds.flatMap((c) => c.binds);

// 1) 区间条件（min/max → 参数化 WHERE）
let f = buildFilter(Q({ min_scale: '10', max_scale: '50' }));
check('range: 两条条件 sql', f.conds.length === 2
  && f.conds[0].sql === 'scale >= ?' && f.conds[1].sql === 'scale <= ?',
  JSON.stringify(f.conds.map((c) => c.sql)));
check('range: binds 数值化', JSON.stringify(bindsOf(f.conds)) === '[10,50]', JSON.stringify(bindsOf(f.conds)));
let w = whereOf(f.conds, 'scale');
check('whereOf: 剔除该字段自身条件 → 空 WHERE', w.sql === '' && w.binds.length === 0, w.sql);
w = whereOf(f.conds, null);
check('whereOf: 全条件 → WHERE ... AND ...', w.sql === 'WHERE scale >= ? AND scale <= ?', w.sql);

// 2) 非法值 → 忽略并记 invalid（不 500、不拼进 SQL）
f = buildFilter(Q({ min_scale: 'abc', min_sharpe: '1;DROP TABLE fund_screener' }));
check('invalid: 非数值条件被忽略', f.conds.length === 0, JSON.stringify(f.conds));
check('invalid: 两个参数名被记为 invalid',
  JSON.stringify(f.invalid) === '["min_scale","min_sharpe"]', JSON.stringify(f.invalid));

// 3) 注入: 任何请求值都不得出现在生成的 SQL 文本里（一律 bind）
const HOSTILE = ['1;DROP TABLE', "' OR 1=1 --", "%'--", "x');DELETE FROM fund_screener;--", 'fund_code ASC'];
let leak = 0;
for (const h of HOSTILE) {
  const r = buildFilter(Q({
    search: h, types: h, company: h, purchase_status: h, min_rating_any: h,
    min_scale: h, min_composite_score: h, max_return_1y: h,
  }));
  const sql = r.conds.map((c) => c.sql).join(' AND ');
  if (sql.indexOf(h) >= 0 || /DROP|DELETE/i.test(sql)) {
    leak++; console.log('FAIL 注入泄漏: ' + h + ' → ' + sql);
  }
  // 所有请求值必须出现在 binds 里（search/types/company 三条）, 且不落 SQL
  const b = JSON.stringify(bindsOf(r.conds));
  if (b.indexOf('DROP') >= 0 && sql.indexOf('DROP') >= 0) leak++;
}
check('injection: 全部请求值只走 bind, SQL 文本零泄漏', leak === 0, 'leak=' + leak);

// 4) LIKE 转义（\ % _ ' 全转义 + ESCAPE 子句）
f = buildFilter(Q({ search: "50%_a'b" }));
check('like: 转义 + ESCAPE', f.conds[0].sql === "(fund_code LIKE ? ESCAPE '\\' OR fund_name LIKE ? ESCAPE '\\')",
  f.conds[0].sql);
check('like: 绑定值转义正确', f.conds[0].binds[0] === "%50\\%\\_a\\'b%", f.conds[0].binds[0]);

// 5) 多选 → IN(?, ?) / 精确匹配 → 等值
f = buildFilter(Q({ types: '股票型, 混合型', purchase_status: '开放申购', company: '公司A' }));
check('multi: IN 占位符 + 值数一致',
  f.conds[0].sql === 'fund_type IN (?, ?)' && f.conds[0].binds.length === 2, JSON.stringify(f.conds[0]));
check('exact: fund_company = ?',
  f.conds.some((c) => c.sql === 'fund_company = ?' && c.binds[0] === '公司A'));

// 6) 「任一机构评级不低于 N」: 四列 COALESCE 取或（全空基金不入选）
f = buildFilter(Q({ min_rating_any: '4' }));
check('rating_any: COALESCE 四列取或 + 同值 4 个 bind',
  f.conds[0].sql === '(COALESCE(rating_shanghai, 0) >= ? OR COALESCE(rating_cms, 0) >= ? '
    + 'OR COALESCE(rating_jajx, 0) >= ? OR COALESCE(rating_morningstar, 0) >= ?)'
  && f.conds[0].binds.length === 4 && f.conds[0].binds.every((v) => v === 4),
  JSON.stringify(f.conds[0]));

// 7) 排序白名单（任意串不落 SQL → 回退默认列）
check('sortable: 白名单成员命中', SORTABLE.has('composite_score') && SORTABLE.has('sharpe'));
check('sortable: 非法排序键不在白名单', !SORTABLE.has('fund_code; DROP TABLE') && !SORTABLE.has(''));
check('sortable: 无重复登记（Set 语义）', new Set([...SORTABLE]).size === [...SORTABLE].length);

// 8) 空条件 → 无 WHERE（全市场列表）
f = buildFilter(Q({}));
check('empty: 无任何条件 + 无 WHERE', f.conds.length === 0 && whereOf(f.conds, null).sql === '');

// 9) 参数名唯一（前后端对齐机检的前提）
const names = RANGE_FIELDS.map((x) => x.name);
check('range: 字段名唯一', new Set(names).size === names.length, names.length);
check('range: name 与 col 一致（缺失计数按 col 剔条件）',
  RANGE_FIELDS.every((x) => x.name === x.col));
check('range: 数量 == 一期条件字段数', RANGE_FIELDS.length === 40, RANGE_FIELDS.length);

console.log(fail ? ('FAILED ' + fail) : 'ALLPASS');
process.exit(fail ? 1 : 0);