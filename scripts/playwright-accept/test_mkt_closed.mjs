// 单测 _isMarketClosedToday 逻辑(从 app.js 复制函数体, 与源码逐字一致)
// 今日 2026-10-02, _bjTodayStr() = "20261002"
function _isMarketClosedToday(snap) {
  if (!snap || snap.is_closed !== true) return false;
  const _shIdx = snap.indices ? snap.indices.find((i) => i.code === "sh000001") : null;
  const _snapDate = _shIdx ? (_shIdx.datetime || "").slice(0, 8) : "";
  return _snapDate !== "20261002";
}
function assert(name, got, exp) {
  console.log((got === exp ? "PASS" : "FAIL") + "  " + name + " => " + got + (got === exp ? "" : " (期望 " + exp + ")"));
}
// ① 盘中: is_closed=false -> 不短路(返回 false)
assert("盘中 is_closed=false", _isMarketClosedToday({ is_closed: false, indices: [] }), false);
// ② 交易日盘后: is_closed=true + datetime 今日(YYYYMMDDHHmmss 无分隔符) -> 不短路(用户看当天分时)
assert("交易日盘后 snap今日", _isMarketClosedToday({ is_closed: true, indices: [{ code: "sh000001", datetime: "20261002150000" }] }), false);
// ③ 休市: is_closed=true + datetime 非今日(节前, 线上真实格式 YYYYMMDDHHmmss 无分隔符) -> 短路
assert("休市日 snap节前", _isMarketClosedToday({ is_closed: true, indices: [{ code: "sh000001", datetime: "20260930161500" }] }), true);
// ④ snap 为 null -> 不短路(保守, 宁拉不短)
assert("snap=null", _isMarketClosedToday(null), false);
// ⑤ 周末(snap 周五非今日, 线上真实格式) -> 短路
assert("周末 snap周五", _isMarketClosedToday({ is_closed: true, indices: [{ code: "sh000001", datetime: "20260925150000" }] }), true);
