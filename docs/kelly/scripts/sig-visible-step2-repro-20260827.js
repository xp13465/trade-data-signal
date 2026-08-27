#!/usr/bin/env node
/**
 * 【用途】「仅显示可用信号」Step2 死码 bug 离线复现器(2026-08-27 fix sig-visible-scroll-fix 自测)
 *   用户实测 bug=开启开关后 csi_399976@20260817 buy_special 仍以「当日已满」(.sig-poscap-excluded,
 *   opacity .5 置灰)可见而非隐藏; 根因=app.js Step2 filter reassign 局部变量 filtered 是死赋值,
 *   渲染遍历的 groups/dates 从未更新 → 该隐藏层自上线起从未生效。
 * 【方法口径】复刻 _renderSignalGrid 的 Step1(fade+未入样本)/分组/keptMap 构建(popItems 人口、排除
 *   band_hold/sell/sell_stop_loss/not-in-universe、先滤降亏再取 top-K)/cellHtml poscap class 判定;
 *   fade 命中直接用后端单源 mode_votes(等价键集交集), S06 态按 kelly_mode_s06_state.json 按日期取基座。
 * 【输入依赖】$1=overview.json(默认 /Users/linhuichen/code/trade-data/static-site/data/overview.json)
 *   + 同目录 kelly_mode_s06_state.json(缺失时 S06 态走 fail-open)。
 * 【输出】四口径(new14/new15/a9/s06)下修复前后 399976@0817 可见性与全表 excluded 行数对比 + 边界断言。
 * 【复现】node docs/kelly/scripts/sig-visible-step2-repro-20260827.js
 * 【结论】before: new14/new15 态该行 excluded 可见且全表 158 行同类置灰可见; after: 全部归零隐藏;
 *   a9/S06 态走 fade 层(Step1)本就隐藏, 两层职责正交不变。
 */
const fs = require('fs');
const d = JSON.parse(fs.readFileSync(process.argv[2] || '/Users/linhuichen/code/trade-data/static-site/data/overview.json', 'utf8'));
const items = d.signals_today || [];
const todayDate = d.date;

// ---- mini 判定链(S06 快照从同名 json 读) ----
let s06 = null;
try { s06 = JSON.parse(fs.readFileSync('/Users/linhuichen/code/trade-data/static-site/data/kelly_mode_s06_state.json', 'utf8')); } catch (e) {}
const s06ByDate = {};
if (s06 && Array.isArray(s06.daily)) for (const row of s06.daily) s06ByDate[String(row.date).replace(/[^0-9]/g, '')] = row;
function baseForDate(dt) {
  if (!s06) return { ok: false, reason: 'not_loaded' };
  const r = s06ByDate[String(dt).replace(/[^0-9]/g, '')];
  if (!r) return { ok: false, reason: 'no_row_or_range' };
  if (r.effective_mode !== 'a9' && r.effective_mode !== 'new15') return { ok: false, reason: 'bad_mode' };
  return { ok: true, base: r.effective_mode };
}
// mode_votes 即「按该模式键集判命中」的后端单源结果(bull 键前端补判此处无 bull 态不影响本例)
function isAiFadeHit(it, mode) {
  const mv = it.ai_macro && it.ai_macro.mode_votes;
  if (!mv) return false;
  if (mode === 's06') {
    const r6 = baseForDate(it.date);
    if (!r6.ok) return false;           // fail-open
    return !!mv[r6.base];
  }
  return !!mv[mode];                    // new14/new15/a9...
}
const BUY_UNI = { buy: 1, buy_aux: 1, buy_special: 1, buy_backup: 1 };

// keptMap 构建(复刻 app.js: 人口=popItems 全量排除 band_hold/sell/sell_stop_loss/not-in-universe,
// 再滤 fade, 排序仅取 track_score DESC 近似——排序细节不影响"谁进/不进 top1 的成员判定", K=1)
function buildKeptMap(popItems, dates, mode) {
  const map = new Map();
  for (const dt of dates) {
    let dayItems = popItems.filter((it) => it.date === dt && it.signal !== 'band_hold'
      && it.signal !== 'sell' && it.signal !== 'sell_stop_loss' && it._bt_in_universe !== false);
    if (!dayItems.length) continue;
    dayItems = dayItems.filter((it) => !isAiFadeHit(it, mode));
    if (!dayItems.length) continue;
    dayItems.sort((a, b) => (topScore(b) - topScore(a)));
    map.set(dt, new Set(dayItems.slice(0, 1).map((s) => s.index_id + '|' + s.date + '|' + s.signal)));
  }
  return map;
}
function topScore(it) {
  const etfs = it.etfs || [];
  let m = -1;
  for (const e of etfs) { const s = typeof e.track_score === 'number' ? e.track_score : -1; if (s > m) m = s; }
  return m;
}

// cellHtml 置灰 class 复刻(只关心 poscap 系):
function posCapClassOf(it, keptMap, mode) {
  const dt = it.date;
  if (!keptMap.has(dt)) return '';        // _posCapRank=null → 无 badge
  if (isAiFadeHit(it, mode)) return 'sig-ai-hit';      // fade 层删除线+置灰
  if (!(it.signal in BUY_UNI) || it._bt_in_universe === false || it.signal === 'band_hold') return '';
  const k = keptMap.get(dt);
  return (k && k.has(it.index_id + '|' + it.date + '|' + it.signal)) ? 'sig-poscap-kept' : 'sig-poscap-excluded';
}

// 主流程: 模拟 availOnlyOn=true, K=1, 无子筛选
function simulate(mode, step2Alive) {
  // Step1
  let filtered = items.filter((it) => !isAiFadeHit(it, mode) && it._bt_in_universe !== false);
  // 分组
  const groups = {};
  for (const it of filtered) (groups[it.date] = groups[it.date] || []).push(it);
  let dates = Object.keys(groups).sort((a, b) => (a < b ? 1 : -1));
  if (groups[todayDate] && dates[0] <= todayDate) dates = [todayDate, ...dates.filter((x) => x !== todayDate)];
  // keptMap(人口=全量 popItems, 与 app 一致: 构建发生在分组后、基于全量人口 filter date===dt)
  const popItems = items;
  const keptMap = buildKeptMap(popItems, dates, mode);
  // Step2: step2Alive=false 复刻死码(不作用于 groups); true=就地过滤
  if (step2Alive && keptMap) {
    for (const dt of dates) {
      groups[dt] = (groups[dt] || []).filter((it) => {
        if (!BUY_UNI[it.signal]) return true;
        const k = keptMap.get(dt);
        return !k || k.has(it.index_id + '|' + it.date + '|' + it.signal);
      });
      if (!groups[dt].length) delete groups[dt];
    }
    dates = dates.filter((x) => !!groups[x]);
  }
  // 渲染收口: 幸存行+class
  const visible = [];
  for (const dt of dates) for (const it of groups[dt]) visible.push({ it, cls: posCapClassOf(it, keptMap, mode) });
  return { dates, visible, keptMap };
}

for (const mode of ['new14', 'new15', 'a9', 's06']) {
  const before = simulate(mode, false);
  const after = simulate(mode, true);
  const f399976 = (sim) => sim.visible.find((v) => v.it.index_id === 'csi_399976' && v.it.date === '20260817');
  const b = f399976(before), a = f399976(after);
  const grayVisibleBefore = before.visible.filter((v) => v.cls === 'sig-poscap-excluded').length;
  const grayVisibleAfter = after.visible.filter((v) => v.cls === 'sig-poscap-excluded').length;
  console.log(`== mode=${mode} ==`);
  console.log(`  csi_399976@20260817 votes=${JSON.stringify((items.find(x => x.index_id==='csi_399976' && x.date==='20260817')||{}).ai_macro?.mode_votes)} base(s06)=${JSON.stringify(baseForDate('20260817'))}`);
  console.log(`  修复前: ${b ? `可见 class=${b.cls}` : '已隐藏(不可见)'}`);
  console.log(`  修复后: ${a ? `可见 class=${a.cls}` : '已隐藏(不可见)'}`);
  console.log(`  「当日已满」置灰且可见的行数: before=${grayVisibleBefore} after=${grayVisibleAfter}`);
  if (after.visible.some((v) => v.cls === 'sig-poscap-excluded')) { console.log('  ❌ FAIL: 修复后仍有 excluded 行可见'); process.exitCode = 1; }
}
// 边界断言: after 的 dates ⊆ before 的 dates 且今日组仍最前(若存在)
const sB = simulate('new14', false), sA = simulate('new14', true);
if (sA.dates.some((x) => !sB.dates.includes(x))) { console.log('❌ FAIL: after 出现 before 没有的日期'); process.exitCode = 1; }
if (sA.dates.length > sB.dates.length) { console.log('❌ FAIL: after 日期组比 before 多'); process.exitCode = 1; }
console.log(`dates 边界: before=${sB.dates.length} after=${sA.dates.length} 今日(${todayDate})位置 before=${sB.dates.indexOf(todayDate)} after=${sA.dates.indexOf(todayDate)}`);
console.log(process.exitCode === 1 ? 'RESULT: FAIL' : 'RESULT: PASS');
