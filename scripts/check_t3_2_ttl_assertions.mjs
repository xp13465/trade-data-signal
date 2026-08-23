#!/usr/bin/env node
// T3-2 二轮适配 TTL 断言(2026-08-23): 三键模式记忆(tds_home_fade_mode/tds_overfit_fade_mode/
// tds_overfit_bull_stop)读写全走 common.js 公共 TTL 工具(_TDS_FADE_TTL_MS=18h 单源)。
// 方法=vm 沙箱切片 app.js 真实函数(_readHomeFadeMode/_readOverfitFadeMode/_readOverfitBullStop)+
// common.js 真实工具(_tdsStoreWithTTL/_tdsLoadWithTTL), 测真实代码非复制品(与 check_*_parity.mjs 同方法论)。
// 复现: node scripts/check_t3_2_ttl_assertions.mjs   (无外部依赖; 输入=两份源码; 输出=A-G 断言全 PASS)
import fs from 'node:fs';
import vm from 'node:vm';

const appSrc = fs.readFileSync(new URL('../static-site/app.js', import.meta.url), 'utf8');
const comSrc = fs.readFileSync(new URL('../static-site/common.js', import.meta.url), 'utf8');

// ── 假 localStorage ──
function makeLS() {
  const m = new Map();
  return {
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => { m.set(k, String(v)); },
    removeItem: (k) => { m.delete(k); },
    _dump: () => Object.fromEntries(m),
  };
}

function slice(src, startMark, endMark) {
  const a = src.indexOf(startMark);
  if (a < 0) throw new Error('start not found: ' + startMark);
  const b = src.indexOf(endMark, a);
  if (b < 0) throw new Error('end not found: ' + endMark);
  return src.slice(a, b);
}

let now = 1_700_000_000_000;
const sandbox = {
  localStorage: makeLS(),
  Date: { now: () => now },           // 可控时钟(滑动过期/续期断言用)
  console,
};
sandbox.window = sandbox;
vm.createContext(sandbox);

// 注入 common.js 真实 TTL 工具段(从 var _TDS_FADE_TTL_MS 到 window 导出块之前)
const ttlSeg = slice(comSrc, 'var _TDS_FADE_TTL_MS', 'window._KELLY_FADE_LEGACY_SPECS');
vm.runInContext(ttlSeg + '\nwindow._tdsStoreWithTTL = _tdsStoreWithTTL; window._tdsLoadWithTTL = _tdsLoadWithTTL; window._TDS_FADE_TTL_MS = _TDS_FADE_TTL_MS;', sandbox);

// 注入 app.js 三个真实读取函数(含 typeof 守卫引用的 _tdsFadeModeById 桩)
vm.runInContext(`
  function _tdsFadeModeById(id){ return ["p8","p9","a9","b9","c9","new14","new18"].indexOf(id)>=0 ? {id} : null; }
`, sandbox);
vm.runInContext(slice(appSrc, 'function _readOverfitFadeMode()', 'async function _appendOverfitCard'), sandbox);
vm.runInContext(slice(appSrc, 'function _readHomeFadeMode()', 'let _sigTierByDate'), sandbox);

const run = (code) => vm.runInContext(code, sandbox);
let pass = 0, fail = 0;
function A(name, cond) { if (cond) { pass++; console.log('  PASS', name); } else { fail++; console.log('  FAIL', name); } }

console.log('A. 写入后 TTL 内读回有效');
run(`_tdsStoreWithTTL("tds_home_fade_mode", "new18"); _tdsStoreWithTTL("tds_overfit_fade_mode", "p9"); _tdsStoreWithTTL("tds_overfit_bull_stop", "1");`);
A('A1 home=new18', run('_readHomeFadeMode()') === 'new18');
A('A2 overfit=p9', run('_readOverfitFadeMode()') === 'p9');
A('A3 bullstop=true', run('_readOverfitBullStop()') === true);

console.log('B. 滑动续期=重新写入刷新 ts(推进 10h 再写, 再推 12h 仍有效=距末次写 12h<18h)');
now += 10 * 3600e3;
run(`_tdsStoreWithTTL("tds_home_fade_mode", "a9");`);
now += 12 * 3600e3;
A('B1 续期后仍 a9(总历时22h但末次写仅12h)', run('_readHomeFadeMode()') === 'a9');

console.log('C. 过期回退默认+清键(推进 19h>18h)');
now += 19 * 3600e3;
A('C1 home 回 p8', run('_readHomeFadeMode()') === 'p8');
A('C2 键已清', sandbox.localStorage.getItem('tds_home_fade_mode') === null);
A('C3 overfit 也过期回 p8', run('_readOverfitFadeMode()') === 'p8' && sandbox.localStorage.getItem('tds_overfit_fade_mode') === null);
A('C4 bullstop 过期回 false', run('_readOverfitBullStop()') === false && sandbox.localStorage.getItem('tds_overfit_bull_stop') === null);

console.log('D. 无 ts 旧格式(永久记忆遗留)→视为过期清掉');
sandbox.localStorage.setItem('tds_home_fade_mode', '"new14"'); // 旧裸值格式
A('D1 旧格式回 p8', run('_readHomeFadeMode()') === 'p8');
A('D2 旧格式已清', sandbox.localStorage.getItem('tds_home_fade_mode') === null);

console.log('E. 解析异常→回默认并清键');
sandbox.localStorage.setItem('tds_overfit_fade_mode', '{oops');
A('E1 脏数据回 p8', run('_readOverfitFadeMode()') === 'p8');
A('E2 脏数据已清', sandbox.localStorage.getItem('tds_overfit_fade_mode') === null);

console.log('F. 白名单外模式值→回 p8(TTL 工具返回了值, 但预设表校验拦截)');
run(`_tdsStoreWithTTL("tds_home_fade_mode", "hack99");`);
A('F1 白名单外回 p8', run('_readHomeFadeMode()') === 'p8');

console.log('G. 六键互不干预(本任务3键 + lab/sim 两键 + 总开关键)');
const KEYS = ['tds_home_fade_mode', 'tds_overfit_fade_mode', 'tds_overfit_bull_stop', 'tds_kelly_fade_mode', 'tds_sim_fade_mode', 'tds_overfit_fade'];
// 各键按真实形态存(模式键=白名单内 id / bullstop 与总开关="1"/lab 键={mode} 对象), 白名单外会被 F 断言的校验拦截属预期
run(`_tdsStoreWithTTL("tds_home_fade_mode","a9"); _tdsStoreWithTTL("tds_overfit_fade_mode","new18"); _tdsStoreWithTTL("tds_overfit_bull_stop","1"); _tdsStoreWithTTL("tds_kelly_fade_mode",{mode:"c9"}); _tdsStoreWithTTL("tds_sim_fade_mode","p9"); _tdsStoreWithTTL("tds_overfit_fade","1");`);
now += 5 * 3600e3; // 全部仍在 TTL 内
let allOk = true;
for (let i = 0; i < KEYS.length; i++) {
  const raw = sandbox.localStorage.getItem(KEYS[i]);
  const v = raw ? JSON.parse(raw) : null;
  if (!v || typeof v.ts !== 'number' || Math.abs(v.ts - (now - 5 * 3600e3)) > 0) { allOk = false; console.log('    ts 异常@', KEYS[i], raw); }
}
A('G1 六键 ts 全部独立写入无串扰', allOk);
A('G2 首页读自身记忆 a9 不受他键影响', run('_readHomeFadeMode()') === 'a9');
A('G3 监控卡读自身记忆 new18/bullstop=true', run('_readOverfitFadeMode()') === 'new18' && run('_readOverfitBullStop()') === true);
run(`_tdsStoreWithTTL("tds_kelly_fade_mode", "b9");`); // 只动 lab 键
A('G4 改 lab 键不影响首页', run('_readHomeFadeMode()') === 'a9');
A('G5 改 lab 键不影响监控卡', run('_readOverfitFadeMode()') === 'new18');

console.log('\\n结果: PASS=' + pass + ' FAIL=' + fail);
process.exit(fail ? 1 : 0);
