"use strict";

// 2026-11-24 MA3连3日(post)凯利区开关: 行为单测 + 代码形状守卫。
// 行为部分直接抽取生产函数 _kellyMa3PostDrops 执行(不复制逻辑, 防第二份实现漂移 §5.4⑦);
// 形状部分锁死 post 口径的代码顺序(先选 K 再剔除)、独立键默认关、缓存签名、公示数字与首页一致。
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const test = require("node:test");

const ROOT = path.resolve(__dirname, "../..");
const lab = fs.readFileSync(path.join(ROOT, "static-site/lab.js"), "utf8");
const notes = fs.readFileSync(path.join(ROOT, "static-site/purpose-notes.js"), "utf8");

// 用 JS parser 确认完整声明(与 test_frontend_aux_body_timeouts.cjs 同款提取器), 防注释/字符串里的大括号误截断
function declaration(source, name) {
  const matches = [...source.matchAll(new RegExp("\\b(?:async\\s+)?function\\s+" + name + "\\s*\\(", "g"))];
  assert.equal(matches.length, 1, "唯一函数锚点: " + name);
  const start = matches[0].index;
  for (let end = source.indexOf("}", start); end >= 0; end = source.indexOf("}", end + 1)) {
    const code = source.slice(start, end + 1);
    try { new vm.Script(code); return code; } catch (error) {
      if (!(error instanceof SyntaxError)) throw error;
    }
  }
  throw new Error("无法提取生产函数: " + name);
}

const drops = vm.runInNewContext("(" + declaration(lab, "_kellyMa3PostDrops") + ")", {});
const FIDX = { ma3: 2, signal_date: 0, etf_code: 1 };

test("行级命中(hit)在开关打开时被剔除", () => {
  assert.equal(drops(["20260105", "510300", "hit"], FIDX, true), true);
});

test("开关关闭时一律不剔(默认关=行为与现在逐位一致)", () => {
  assert.equal(drops(["20260105", "510300", "hit"], FIDX, false), false);
  assert.equal(drops(["20260105", "510300", "hit"], FIDX, undefined), false);
});

test("miss / na 都放行(na=数据不足保守不误伤)", () => {
  assert.equal(drops(["20260105", "510300", "miss"], FIDX, true), false);
  assert.equal(drops(["20260105", "510300", "na"], FIDX, true), false);
  assert.equal(drops(["20260105", "510300", ""], FIDX, true), false);
  assert.equal(drops(["20260105", "510300", null], FIDX, true), false);
});

test("产物未含 ma3 列(旧版产物)时不剔, 不退化成误杀", () => {
  assert.equal(drops(["20260105", "510300", "hit"], { signal_date: 0 }, true), false);
  assert.equal(drops(["20260105", "510300", "hit"], {}, true), false);
  assert.equal(drops(null, FIDX, true), false);
});

test("post 口径代码顺序: 先按 _pk 选 K, 再剔 MA3 命中(顺序颠倒即退化成 pre/补位口径)", () => {
  const start = lab.indexOf("toggledByMode[modeKey] = rawTrades.filter");
  assert.ok(start > 0, "找到阶段1过滤块");
  const end = lab.indexOf("await _kellyYield();", start);
  const block = lab.slice(start, end);
  const kept = block.indexOf("_pk && !_pk[_kellyBaseKey");
  const ma3 = block.indexOf("_kellyMa3PostDrops");
  assert.ok(kept > 0 && ma3 > 0, "两个谓词都在同一过滤块内");
  assert.ok(kept < ma3, "K 选样必须排在 MA3 剔除之前(post = 先选 K 再剔除, 不补位)");
});

test("K 选样集合在 MA3 过滤之前构建(MA3 不得影响 top-K 选样)", () => {
  const keptBuild = lab.indexOf("posCapKept = _kellyPositionCapKeptKeys(basePool");
  const filterLoop = lab.indexOf("toggledByMode[modeKey] = rawTrades.filter");
  assert.ok(keptBuild > 0 && filterLoop > 0);
  assert.ok(keptBuild < filterLoop, "posCapKept 必须先于过滤循环计算");
});

test("MA3 开关态并入顶层缓存签名(切换强制重算, 不命中脏缓存)", () => {
  assert.match(lab, /\+ "\|ma3post=" \+ \(_ma3PostActive \? "1" : "0"\)/);
});

test("独立键 tds_kelly_ma3_post 默认关(只有 === \"1\" 才算开)", () => {
  assert.match(lab, /localStorage\.getItem\("tds_kelly_ma3_post"\) === "1"/);
  assert.match(lab, /localStorage\.setItem\("tds_kelly_ma3_post", on \? "1" : "0"\)/);
  // 独立键不得混进 tds_kelly_filters 的成员持久化(与 AI降亏正交)
  const persist = lab.slice(lab.indexOf("function _kellyPersistFilters()"), lab.indexOf("function _kellyRefreshAiMacroState"));
  assert.ok(!persist.includes("ma3"), "tds_kelly_filters 持久化不得写 MA3 键");
});

test("开关不退出动态基座态(keepS06: true), 且重置一键回默认关", () => {
  assert.match(lab, /_kellySetMa3Post\(ma3PostCb\.checked\);[\s\S]{0,160}_kellyOnFilterChange\(\{ keepS06: true \}\)/);
  assert.match(lab, /_kellySetSharedPosCap\(true, 1\);[\s\S]{0,200}_kellySetMa3Post\(false\)/);
});

test("开关渲染带 NEW 角标, 且 lab.js 不残留旧 🆕 字符", () => {
  assert.match(lab, /class="hot-new-badge"/);
  assert.ok(!lab.includes("🆕"), "不得残留旧版 🆕 字符(统一用 .hot-new-badge)");
});

test("产物缺 ma3 列时渲染层可见提示, 不静默假装过滤", () => {
  assert.match(lab, /回测产物未含 ma3 列，暂不生效/);
  assert.match(lab, /result\.__ma3Post = \{ on: _ma3PostOn, active: _ma3PostActive \}/);
});

function noteText(key) {
  const start = notes.indexOf('"' + key + '":');
  assert.ok(start > 0, "找到公示条目: " + key);
  const open = notes.indexOf("'", start);
  const closes = [notes.indexOf("',\n", open), notes.indexOf("'\n", open)].filter((v) => v > open);
  const close = Math.min(...closes);
  assert.ok(open > start && Number.isFinite(close), "公示条目为单引号字符串: " + key);
  return notes.slice(open + 1, close);
}

test("lab.ma3post 公示存在且关键口径数字与首页 home.ma3filter 一致(§22 多展示位一致)", () => {
  const labNote = noteText("lab.ma3post");
  const homeNote = noteText("home.ma3filter");
  for (const fig of ["93.9%", "49.9%", "88.4%", "28.7%", "47.27", "38.12", "97.7"]) {
    assert.ok(labNote.includes(fig), "lab 公示缺少关键数字 " + fig);
    assert.ok(homeNote.includes(fig), "首页公示缺少关键数字 " + fig);
  }
  for (const phrase of ["先选 K 再剔除", "不补位", "默认关", "99 笔", "7 笔未平仓", "没有跨过 30%"]) {
    assert.ok(labNote.includes(phrase), "lab 公示缺少口径说明: " + phrase);
  }
  assert.ok(labNote.includes("app/ma3.py"), "公示须写明命中判定单源");
  assert.ok(labNote.includes("绝不用 T+1"), "公示须写明防前视口径");
});
