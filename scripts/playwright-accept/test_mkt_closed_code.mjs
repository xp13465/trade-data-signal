// 单测 _isMarketClosedTodayForCode(从 app.js 源码逐字复制函数体, 与源码一致, §5.4⑦同构对账)
// 今日按系统时钟(UTC+8), 快照日期用相对昨日(-1天)/周五(-3天)构造。
function _bjTodayStr() {
  const _d = new Date(Date.now() + 8 * 3600000);
  return _d.getUTCFullYear() + String(_d.getUTCMonth() + 1).padStart(2, "0") + String(_d.getUTCDate()).padStart(2, "0");
}
// 与源码 _INDEX_MARKET 一致(hk 三只: hsi/hstech/hscei)
const _INDEX_MARKET = {};
["sh","sz","hs300","sz50","cyb","kc50","bj50","csi500","csi1000"].forEach((k) => _INDEX_MARKET[k] = "cn");
["hsi","hstech","hscei"].forEach((k) => _INDEX_MARKET[k] = "hk");

function _isMarketClosedToday(snap) {
  if (!snap || snap.is_closed !== true) return false; // 盘中(is_closed=false)恒不拦截
  const _shIdx = snap.indices ? snap.indices.find((i) => i.code === "sh000001") : null;
  const _snapDate = _shIdx ? (_shIdx.datetime || "").slice(0, 8) : "";
  return _snapDate !== _bjTodayStr();
}
function _isMarketClosedTodayForCode(snap, code) {
  if (_INDEX_MARKET[code] === "hk") return false; // 港股: 恒放行实时
  return _isMarketClosedToday(snap);              // A股/其他: 沿用顶层休市口径
}

// 相对日期工具: 距今日 offset 天的 YYYYMMDD(仅日期段; 含 datetime 完整串用 offset+固定时间)
function _dayStr(offset) {
  const _d = new Date(Date.now() + 8 * 3600000);
  _d.setUTCDate(_d.getUTCDate() + offset);
  return _d.getUTCFullYear() + String(_d.getUTCMonth() + 1).padStart(2, "0") + String(_d.getUTCDate()).padStart(2, "0");
}
let fail = 0;
function assert(name, got, exp) {
  const ok = got === exp;
  if (!ok) fail++;
  console.log((ok ? "PASS" : "FAIL") + "  " + name + " => " + got + (ok ? "" : " (期望 " + exp + ")"));
}

const yesterday = _dayStr(-1); // A股休市错位日: 快照停在上一交易日(A股 10-01~10-07 休市, 港股照常开)
const friday = _dayStr(-3);    // 周末: 快照停在周五

// ========== Finding1 核心: A股休市错位日, 港股必须放行实时 ==========
// 场景: snap.is_closed=true(A股休市) + sh000001 datetime=昨日。改前 _isMarketClosedToday=true 会无差别短路所有 code,
// 改后 _isMarketClosedTodayForCode 对港股恒返回 false(放行实时)。
const holidaySnap = { is_closed: true, indices: [
  { code: "sh000001", datetime: yesterday + "161500" },
  { code: "hkHSI", datetime: yesterday + "183127", is_closed: true },
] };
assert("[Finding1-FAIL→PASS] 港股hsi(A股休市错位日)放行实时", _isMarketClosedTodayForCode(holidaySnap, "hsi"), false);
assert("[Finding1] 港股hstech放行实时", _isMarketClosedTodayForCode(holidaySnap, "hstech"), false);
assert("[Finding1] 港股hscei放行实时", _isMarketClosedTodayForCode(holidaySnap, "hscei"), false);
assert("[Finding1-A股不回归] A股sh(A股休市)仍拦截走快照", _isMarketClosedTodayForCode(holidaySnap, "sh"), true);
assert("[Finding1-A股不回归] A股sz仍拦截", _isMarketClosedTodayForCode(holidaySnap, "sz"), true);
assert("[Finding1-A股不回归] A股hs300仍拦截", _isMarketClosedTodayForCode(holidaySnap, "hs300"), true);

// ========== 盘中(is_closed=false)恒不拦截(全市场) ==========
const intradaySnap = { is_closed: false, indices: [{ code: "sh000001", datetime: _bjTodayStr() + "103000" }] };
assert("盘中 is_closed=false, A股sh不拦截", _isMarketClosedTodayForCode(intradaySnap, "sh"), false);
assert("盘中 is_closed=false, 港股hsi不拦截", _isMarketClosedTodayForCode(intradaySnap, "hsi"), false);

// ========== 交易日盘后(snap今日)不拦(A股老行为) ==========
const afterCloseSnap = { is_closed: true, indices: [{ code: "sh000001", datetime: _bjTodayStr() + "150000" }] };
assert("交易日盘后 snap今日, A股sh不拦截", _isMarketClosedTodayForCode(afterCloseSnap, "sh"), false);
assert("交易日盘后 snap今日, 港股hsi不拦截", _isMarketClosedTodayForCode(afterCloseSnap, "hsi"), false);

// ========== 周末(snap周五) ==========
const weekendSnap = { is_closed: true, indices: [{ code: "sh000001", datetime: friday + "161500" }] };
assert("周末, A股sh拦截走快照", _isMarketClosedTodayForCode(weekendSnap, "sh"), true);
assert("周末, 港股hsi放行实时", _isMarketClosedTodayForCode(weekendSnap, "hsi"), false);

// ========== snap=null ==========
assert("snap=null 不拦截", _isMarketClosedTodayForCode(null, "sh"), false);
assert("snap=null 港股不拦截", _isMarketClosedTodayForCode(null, "hsi"), false);

console.log(fail === 0 ? "\n全部 PASS" : "\n有 " + fail + " 个 FAIL");
process.exit(fail === 0 ? 0 : 1);
