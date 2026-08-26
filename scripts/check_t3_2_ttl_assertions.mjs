#!/usr/bin/env node
// T3-2 二轮适配 TTL 断言(2026-08-23): 三键模式记忆(tds_home_fade_mode/tds_overfit_fade_mode/
// tds_overfit_bull_stop)读写全走 common.js 公共 TTL 工具(_TDS_FADE_TTL_MS=18h 单源)。
// 方法=vm 沙箱切片 app.js 真实函数(_readHomeFadeMode/_readOverfitFadeMode)+
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

// 注入 app.js 真实读取函数(含 typeof 守卫引用的 _tdsFadeModeById 桩)
// v20260826(用户拍板): new18 已从 common.js _KELLY_FADE_MODE_PRESETS 下拉预设表移除(组成对比区卡与
// 后端 RECENT_KEYS 打标集保留)。真实 _tdsFadeModeById 查表返回 null → 四消费点读记忆校验失败自动回默认。
// 本脚本桩必须与真实预设表同口径: 白名单去掉 new18, 原「存 new18 读回 new18」断言改为「读回默认 new14」,
// 验证的正是「已下线模式记忆安全回退」这条用户路径(L44 同精神: 机检锚点跟实现走)。
// ⚠历史遗留清理(2026-08-26 实施批发现并上报): 4fa57af24(2026-08-24 删独立+1开关)漏改本脚本,
//   _readOverfitBullStop 在 app.js 已不存在 → 本脚本在 main 上 A3 即 ReferenceError 挂死。
//   本批随 new18 同步一并清除 bullstop 死断言(A3/C4/G3 半句+KEYS 表项), 脚本恢复可跑。
vm.runInContext(`
  function _tdsFadeModeById(id){ return ["p8","p9","a9","b9","c9","new14"].indexOf(id)>=0 ? {id} : null; }
`, sandbox);
vm.runInContext(slice(appSrc, 'function _readOverfitFadeMode()', 'async function _appendOverfitCard'), sandbox);
vm.runInContext(slice(appSrc, 'function _readHomeFadeMode()', 'let _sigTierByDate'), sandbox);

const run = (code) => vm.runInContext(code, sandbox);
let pass = 0, fail = 0;
function A(name, cond) { if (cond) { pass++; console.log('  PASS', name); } else { fail++; console.log('  FAIL', name); } }

console.log('A. 写入后 TTL 内读回有效');
run(`_tdsStoreWithTTL("tds_home_fade_mode", "new14"); _tdsStoreWithTTL("tds_overfit_fade_mode", "p9");`);
A('A1 home=new14', run('_readHomeFadeMode()') === 'new14');
A('A2 overfit=p9', run('_readOverfitFadeMode()') === 'p9');

console.log('B. 滑动续期=重新写入刷新 ts(推进 10h 再写, 再推 12h 仍有效=距末次写 12h<18h)');
now += 10 * 3600e3;
run(`_tdsStoreWithTTL("tds_home_fade_mode", "a9");`);
now += 12 * 3600e3;
A('B1 续期后仍 a9(总历时22h但末次写仅12h)', run('_readHomeFadeMode()') === 'a9');

console.log('C. 过期回退默认+清键(推进 19h>18h)');
now += 19 * 3600e3;
A('C1 home 回默认 new14', run('_readHomeFadeMode()') === 'new14');
A('C2 键已清', sandbox.localStorage.getItem('tds_home_fade_mode') === null);
A('C3 overfit 也过期回默认 new14', run('_readOverfitFadeMode()') === 'new14' && sandbox.localStorage.getItem('tds_overfit_fade_mode') === null);

console.log('D. 无 ts 旧格式(永久记忆遗留)→视为过期清掉');
sandbox.localStorage.setItem('tds_home_fade_mode', '"new14"'); // 旧裸值格式
A('D1 旧格式回默认 new14', run('_readHomeFadeMode()') === 'new14');
A('D2 旧格式已清', sandbox.localStorage.getItem('tds_home_fade_mode') === null);

console.log('E. 解析异常→回默认并清键');
sandbox.localStorage.setItem('tds_overfit_fade_mode', '{oops');
A('E1 脏数据回默认 new14', run('_readOverfitFadeMode()') === 'new14');
A('E2 脏数据已清', sandbox.localStorage.getItem('tds_overfit_fade_mode') === null);

console.log('F. 白名单外模式值→回 new14(TTL 工具返回了值, 但预设表校验拦截)');
run(`_tdsStoreWithTTL("tds_home_fade_mode", "hack99");`);
A('F1 白名单外回默认 new14', run('_readHomeFadeMode()') === 'new14');

console.log('F2. 已下线模式 new18(存了旧记忆)→校验失败自动回默认 new14(v20260826 下拉移除后的用户安全路径)');
run(`_tdsStoreWithTTL("tds_home_fade_mode", "new18"); _tdsStoreWithTTL("tds_overfit_fade_mode", "new18");`);
A('F2a home 存 new18 读回默认 new14', run('_readHomeFadeMode()') === 'new14');
A('F2b overfit 存 new18 读回默认 new14', run('_readOverfitFadeMode()') === 'new14');

console.log('G. 五键互不干预(本任务2模式键 + lab/sim 两键 + 总开关键; bullstop 键 2026-08-24 已随独立开关删除)');
const KEYS = ['tds_home_fade_mode', 'tds_overfit_fade_mode', 'tds_kelly_fade_mode', 'tds_sim_fade_mode', 'tds_overfit_fade'];
// 各键按真实形态存(模式键=白名单内 id / 总开关="1"/lab 键={mode} 对象), 白名单外会被 F 断言的校验拦截属预期
run(`_tdsStoreWithTTL("tds_home_fade_mode","a9"); _tdsStoreWithTTL("tds_overfit_fade_mode","p9"); _tdsStoreWithTTL("tds_kelly_fade_mode",{mode:"c9"}); _tdsStoreWithTTL("tds_sim_fade_mode","a9"); _tdsStoreWithTTL("tds_overfit_fade","1");`);
now += 5 * 3600e3; // 全部仍在 TTL 内
let allOk = true;
for (let i = 0; i < KEYS.length; i++) {
  const raw = sandbox.localStorage.getItem(KEYS[i]);
  const v = raw ? JSON.parse(raw) : null;
  if (!v || typeof v.ts !== 'number' || Math.abs(v.ts - (now - 5 * 3600e3)) > 0) { allOk = false; console.log('    ts 异常@', KEYS[i], raw); }
}
A('G1 五键 ts 全部独立写入无串扰', allOk);
A('G2 首页读自身记忆 a9 不受他键影响', run('_readHomeFadeMode()') === 'a9');
A('G3 监控卡读自身记忆 p9', run('_readOverfitFadeMode()') === 'p9');
run(`_tdsStoreWithTTL("tds_kelly_fade_mode", "b9");`); // 只动 lab 键
A('G4 改 lab 键不影响首页', run('_readHomeFadeMode()') === 'a9');
A('G5 改 lab 键不影响监控卡', run('_readOverfitFadeMode()') === 'p9');

console.log('\\n结果: PASS=' + pass + ' FAIL=' + fail);
process.exit(fail ? 1 : 0);
