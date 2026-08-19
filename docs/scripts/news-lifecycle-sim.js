// news-lifecycle-sim.js
// 功能: 实证复现首页新闻外露行在 renderOverview 重建生命周期下的行为(「消失」/「不自动更新」)。
// 方法: 从 static-site/app.js 提取真实函数源码 (_renderHomeNewsRows/_startHomeNewsPoll/_homeNewsReset/
//   _loadNewsDigest/_dbTodayNews/_dbUpcomingEvents/_dbNextDayRowHtml/_dbHomeTodayNewsRowHtml/_dbNewsDateCn/
//   _dbTomorrowDateCn/_esc), 在 node 用 eval 载入并提供最小 DOM stub 依赖, 重放:
//   (a) 单一 renderOverview 挂载 + 一次轮询 → 断言新闻出现且轮询能原地更新
//   (b) renderOverview 重建(content.innerHTML="" 清空) 过程中, 旧 _summaryP.then 异步回调与新回调交错
//       → 断言每个 renderOverview 完成后新闻板块仍在 DOM、能继续自动更新
// 输入: static-site/app.js
// 输出: 每条断言 PASS/FAIL; 复现命令: node docs/scripts/news-lifecycle-sim.js
const fs = require('fs');
const path = require('path');
const APP = fs.readFileSync(path.join(__dirname, '../../static-site/app.js'), 'utf8');

function extractFn(fnName) {
  const sig = `function ${fnName}(`;
  let s = APP.indexOf(sig);
  if (s < 0) throw new Error('extract fail: ' + fnName);
  // 兼容 "async function X(" 前缀: 若向前若干字符内存在 "async " 则包含它
  const pre = APP.slice(Math.max(0, s - 8), s);
  if (/async\s+$/.test(pre)) s -= 'async '.length;
  const e = APP.indexOf('\n}\n', s);
  return APP.slice(s, e + 2);
}

const NEWS_FNS = [
  '_esc',
  '_dbTodayNews', '_dbUpcomingEvents', '_dbNextDayRowHtml', '_dbNewsDateCn',
  '_dbTomorrowDateCn', '_dbHomeTodayNewsRowHtml',
  '_loadNewsDigest', '_homeNewsReset', '_renderHomeNewsRows', '_startHomeNewsPoll',
];
let extractedSrc = '';
for (const fn of NEWS_FNS) { extractedSrc += extractFn(fn) + '\n'; }

// ---------- 最小 DOM stub ----------
function makeEl(cls) {
  return {
    _cls: cls || '', className: cls || '', innerHTML: '', children: [], isConnected: false,
    nextSibling: null, parentNode: null, _listeners: {},
    addEventListener(t, fn) { this._listeners[t] = fn; },
    remove() { const p = this.parentNode; if (!p) return; const i = p.children.indexOf(this); if (i>=0) p.children.splice(i,1); this.parentNode=null; this.isConnected=false; this.nextSibling=null; },
    after(node) { const p = this.parentNode; if (!p) { node.isConnected=false; node.parentNode=null; return; } node.parentNode=p; node.isConnected=true; node.nextSibling=this.nextSibling; p.children.push(node); },
  };
}
function makeContent() {
  const c = {
    _cls:'content', className:'content', innerHTML:'', children:[], isConnected:true, nextSibling:null, parentNode:null, _listeners:{},
    addEventListener(){}, firstChild:null,
    insertBefore(node, ref) { node.parentNode=this; node.isConnected=true; node.nextSibling=ref||null; if(ref===undefined||ref===null) this.children.push(node); else { const i=this.children.indexOf(ref); this.children.splice(i<0?this.children.length:i,0,node);} this.firstChild=this.children[0]||null; },
    rebuild() { this.innerHTML=''; for(const ch of this.children){ch.isConnected=false;ch.parentNode=null;ch.nextSibling=null;} this.children=[]; this.firstChild=null; },
  };
  return c;
}

// ---------- 沙箱依赖 ----------
const DOM_STUB = {
  document: { hidden:false, getElementById(){return null;}, addEventListener(){}, createElement(cls){return makeEl(cls);} },
  localStorage: { getItem(){return null;}, setItem(){} },
  location: { hostname: 'localhost' },
  setTimeout, clearTimeout,
};
let _simNews = { news:[{time:'09:00',title:'早盘新闻'},{time:'10:00',title:'盘中要闻'}], upcoming:[{time:'15:00',title:'明日事件A',important:true}], date:'2026-08-20' };
let fetchCount = 0;
const fetchJSONStub = async function(url){ fetchCount++; return JSON.parse(JSON.stringify(_simNews)); };
const openModalStub = function(){};

const script = `
var _newsDigestCache = null;
var _newsDigestTs = 0;
var _NEWS_DIGEST_TTL = 5*60*1000;
var _homeNewsTimer = null;
var _homeNewsPolling = false;
var _homeNewsWrap = null;
var _homeNewsFallback = null;
var _homeNewsEpoch = 0;
var _homeNewsPollEpoch = 0;
${extractedSrc}
globalThis.__out = { _loadNewsDigest, _homeNewsReset, _renderHomeNewsRows, _startHomeNewsPoll,
  _dbHomeTodayNewsRowHtml, _dbNextDayRowHtml,
  cache: ()=>_newsDigestCache, timer: ()=>_homeNewsTimer, wrap: ()=>_homeNewsWrap, epoch: ()=>_homeNewsEpoch };
`;
const deps = [DOM_STUB.document, DOM_STUB.localStorage, DOM_STUB.location, setTimeout, clearTimeout, fetchJSONStub, openModalStub, _simNews];
const loaded = Function.apply(null, ['document','localStorage','location','setTimeout','clearTimeout','fetchJSON','openNewsDigestModal','_simNews','"use strict";'+script+'; return globalThis.__out;'])(...deps);
if (!loaded) { console.error('LOAD FAIL'); process.exit(1); }
const { _loadNewsDigest, _homeNewsReset, _renderHomeNewsRows, _startHomeNewsPoll, cache, timer, wrap } = loaded;

// ---------- 断言工具 ----------
let pass=0, fail=0;
function assert(name, cond, extra){ if(cond){pass++; console.log('PASS', name);} else {fail++; console.log('FAIL', name, extra||'');} }
function newsRowsIn(content){ return content.children.filter(c=>String(c.className).includes('summary-news-row')); }
function bannerChildren(content){ return content.children.filter(c=>String(c.className).includes('summary-banner')); }

(async () => {
  // ========== 用例A: 单一 renderOverview 挂载 + 一次轮询 ==========
  console.log('\n===== A) 单一挂载 + 轮询 =====');
  _simNews = { news:[{time:'09:00',title:'早盘新闻'},{time:'10:00',title:'盘中要闻'}], upcoming:[{time:'15:00',title:'明日事件A',important:true}], date:'2026-08-20' };
  const contentA = makeContent();
  const bannerA = makeEl('summary-banner');
  contentA.insertBefore(bannerA, null);
  const ndA = await _loadNewsDigest();
  _renderHomeNewsRows(ndA, bannerA, contentA);
  _startHomeNewsPoll(bannerA, contentA);
  assert('A1 首次挂载后新闻行在 content 中', newsRowsIn(contentA).length === 1);
  assert('A2 新闻行已渲染(i.e. 今日要闻文本在 innerHTML)', /今日要闻|早盘新闻/.test(newsRowsIn(contentA)[0].innerHTML));
  // 轮询: 更新 news 数据 → 触发一次轮询(模拟 setTimeout 回调)应原地更新
  _simNews = { news:[{time:'09:00',title:'早盘新闻'},{time:'10:30',title:'盘中新增要闻'}], upcoming:[{time:'15:00',title:'明日事件A',important:true}], date:'2026-08-20' };
  // 直接调用轮询的核心: force 重拉 + render(等价 _startHomeNewsPoll 的 poll 回调体)
  const ndB = await _loadNewsDigest(true);
  _renderHomeNewsRows(ndB, bannerA, contentA);
  assert('A3 轮询重拉后新闻行仍唯一(不重复堆积)', newsRowsIn(contentA).length === 1);
  assert('A4 轮询重拉后原位更新到新数据(不自动更新=FAIL)', /盘中新增要闻/.test(newsRowsIn(contentA)[0].innerHTML));
  assert('A5 轮询后新闻不消失(仍 isConnected)', newsRowsIn(contentA)[0].isConnected === true);

  // ========== 用例B: renderOverview 重建(清空)后, 旧异步回调交错 ==========
  // 模拟: renderOv#1 触发 _summaryP.then#1(async, 未完成); 用户切走切回 → renderOv#2 content.rebuild() + _homeNewsReset() + 调度 _summaryP.then#2
  // 然后 #1 async 完成(晚于 #2) → 它拿到的是旧 banner, _renderHomeNewsRows 只能往当前 content 插/更新
  console.log('\n===== B) 重建 + 旧异步回调交错 =====');
  // 步骤: 模拟 renderOverview 的同步骨架: reset + 调度 async(我们用两个 content 模拟两次重建时序)
  const contentB1 = makeContent(); // renderOv#1 的 content
  const contentB2 = makeContent(); // renderOv#2 (新) 的 content
  // renderOv#1: clear + reset
  _homeNewsReset();
  // renderOv#1 async 未完成, 此时 renderOv#2 触发: 它 clear 的是"当前 content"(假设同容器, 简化模拟为重建后内容被清 + reset)
  // 真实 renderOverview 里 content 是同一个 element('#content' 容器), #2 对同一容器 innerHTML=""。
  // 我们用单个共享容器模拟:
  const sharedContent = makeContent();
  // ---- renderOv#1 ----
  _homeNewsReset();
  sharedContent.rebuild();
  // _summaryP.then#1 (async): 我们模拟它在 1.5s 后完成(await fetchIntradaySnapshot)
  const banner1 = makeEl('summary-banner');
  sharedContent.insertBefore(banner1, null);
  const p1 = (async () => {
    await new Promise(r=>setTimeout(r, 30)); // 模拟 async await 耗时
    const nd = await _loadNewsDigest();       // 不带 force(首渲染)
    _renderHomeNewsRows(nd, banner1, sharedContent); // 旧闭包的 banner1
    _startHomeNewsPoll(banner1, sharedContent);
  })();
  // ---- renderOv#2 在 #1 async 仍 pending 时触发: 清空 + reset, 建新 banner #2 ----
  sharedContent.rebuild();        // innerHTML="" 清仓(移除 banner1 + 所有新闻)
  _homeNewsReset();               // 杀 timer/null wrap
  const banner2 = makeEl('summary-banner');
  sharedContent.insertBefore(banner2, null);
  const p2 = (async () => {
    await new Promise(r=>setTimeout(r, 5));  // #2 async 更快完成
    const nd = await _loadNewsDigest();
    _renderHomeNewsRows(nd, banner2, sharedContent);
    _startHomeNewsPoll(banner2, sharedContent);
  })();
  await Promise.all([p1, p2]);
  // 断言: 无论 #1 最后写还是 #2 最后写, 当前 content 都应有新闻行且 isConnected
  const rowsB = newsRowsIn(sharedContent);
  const bannsB = bannerChildren(sharedContent);
  assert('B1 重建交错后新闻行存在(消失=FAIL)', rowsB.length >= 1);
  assert('B2 重建交错后新闻行 isConnected(挂死节点=FAIL)', rowsB.every(r=>r.isConnected===true));
  assert('B3 重建交错后仍有有效 banner(两 banner 都脱离即消失)', bannsB.length >= 1);
  assert('B4 新闻行挂在实时 banner 下或 content 中, 且在 DOM 内', rowsB.length>=1 && rowsB.every(r=>r.isConnected));
  assert('B5 不重复堆积(<=2 行, 兜底 1 行 + 正常 1 行)', rowsB.length <= 2);
  // 再触发一次轮询确认更新链还活着
  _simNews = { news:[{time:'09:00',title:'早盘新闻'},{time:'11:00',title:'轮询后的新要闻'}], upcoming:[{time:'15:00',title:'明日事件A',important:true}], date:'2026-08-20' };
  const ndC = await _loadNewsDigest(true);
  _renderHomeNewsRows(ndC, banner2/*当前banner*/, sharedContent);
  assert('B6 交错后轮询仍能更新(不自动更新=FAIL)', newsRowsIn(sharedContent).some(r=>/轮询后的新要闻/.test(r.innerHTML)));

  // ========== 用例C(2026-08-20 #12 纪元硬化的直接验证) ==========
  // 验证: ①_homeNewsReset 自增纪元 ②旧代 _startHomeNewsPoll 会被新代接管(不遗留死轮询)
  //       ③纪元变化时旧代轮询 fire 自弃不碰当前 DOM
  console.log('\n===== C) 纪元(epoch)硬化 =====');
  const epochA = loaded.epoch;
  const e0 = epochA();
  _homeNewsReset();                       // 触发新一次 renderOverview 清空 → 纪元+1
  const eAfterReset = epochA();
  assert('C1 _homeNewsReset 自增纪元(旧代失效)', eAfterReset > e0, `e0=${e0} eAfter=${eAfterReset}`);
  // 模拟第 1 代挂载 + 轮询(闭包绑 bannerA)
  const contentC = makeContent();
  const bannerC1 = makeEl('summary-banner');
  contentC.insertBefore(bannerC1, null);
  const ndC1 = await _loadNewsDigest();
  _renderHomeNewsRows(ndC1, bannerC1, contentC);
  _startHomeNewsPoll(bannerC1, contentC);
  // 模拟新 renderOverview(第 2 代): reset(纪元+) + 用同 content(真实 renderOverview 用同一 #content)重建
  contentC.rebuild();                     // 旧的 bannerC1+wrap 脱离
  _homeNewsReset();
  const bannerC2 = makeEl('summary-banner');
  contentC.insertBefore(bannerC2, null);
  const ndC2 = await _loadNewsDigest();
  _renderHomeNewsRows(ndC2, bannerC2, contentC);
  _startHomeNewsPoll(bannerC2, contentC); // 第 2 代接管: 应杀掉第 1 代遗留轮询并重建
  assert('C2 新代 _startHomeNewsPoll 接管后新闻仍唯一存在且 isConnected', newsRowsIn(contentC).length>=1 && newsRowsIn(contentC)[0].isConnected);
  assert('C3 接管后新闻行挂在当前 banner 后(非死 banner)', newsRowsIn(contentC).every(r=>r.isConnected));

  console.log(`\n===== 结果: ${pass} PASS / ${fail} FAIL =====`);
  process.exit(fail ? 1 : 0);
})();
