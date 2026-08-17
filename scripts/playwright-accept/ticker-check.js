#!/usr/bin/env node
/**
 * ticker-check.js — 首页「全球盘面跑马灯」验收脚本
 *
 * 目的:跑马灯专用验收(首页全球盘面跑马灯)。
 *
 * 已回填真实选择器(2026-08-17 实测确认):
 *   - 容器         .global-ticker
 *   - 滚动条       .gt-scroll(一行超宽 scrollWidth>clientWidth 即滚动)
 *   - 品种名称     .gt-name(无缝滚动复制2份 → 16 个节点,唯一品种 8 个)
 *   - 主数据源      push2delay.eastmoney.com(东财延迟行情)
 *
 * 用法:
 *   node ticker-check.js <URL> [--block 东财URL子串] [--wait <ms>]
 *     --block <子串>: 屏蔽主数据源(默认 push2delay.eastmoney.com),验证降级到备源。
 *
 * 复现:
 *   python3 -m http.server 8000 -d /Users/linhuichen/code/trade/static-site
 *   node ticker-check.js http://localhost:8000
 *   node ticker-check.js http://localhost:8000 --block push2delay.eastmoney.com
 */
'use strict';

const { execFileSync } = require('child_process');
const path = require('path');
const fs = require('fs');
const os = require('os');

const args = process.argv.slice(2);
if (args.length === 0 || args[0] === '--help' || args[0] === '-h') {
  console.log(`用法: node ticker-check.js <URL> [--block 东财URL子串] [--wait <ms>]

首页「全球盘面跑马灯」验收脚本。默认主数据源子串 = push2delay.eastmoney.com。
--block 传入时屏蔽主源,验证降级到备源(备源请求是否发出)。
回填清单见文件头 docstring。`);
  process.exit(args.length === 0 ? 1 : 0);
}

const url = args[0];
const accArgs = ['node', path.join(__dirname, 'accept.js'), url];

const BLOCK_DEFAULT = 'push2delay.eastmoney.com';
let blockArg = null;
let waitArg = null;
for (let i = 1; i < args.length; i++) {
  if (args[i] === '--block') { blockArg = args[++i] || BLOCK_DEFAULT; accArgs.push('--block', blockArg); }
  else if (args[i] === '--wait') { waitArg = args[++i]; accArgs.push('--wait', waitArg); }
  else { console.error(`[参数错误] 未知选项: ${args[i]}`); process.exit(1); }
}

// accept.js 主流程断言
accArgs.push(
  '--expect-request', 'index.html',
  '--assert', '.global-ticker|exists',            // 跑马灯容器存在
  '--assert', '.gt-name|count=16',                // 无缝滚动复制2份 → 16 个节点
  '--assert', '.global-ticker .gt-name:first-child|text=现货',  // 品种名称文本
  '--block-on-error'
);
if (!blockArg) {
  // 未屏蔽时断言主数据源发出
  accArgs.push('--expect-request', 'push2delay.eastmoney.com');
} else {
  // 已屏蔽主源 → 断言主源已失效(无有效响应,验证屏蔽生效)
  accArgs.push('--expect-request-missing', 'push2delay.eastmoney.com');
  // ★备源断言待回填★: 跑马灯降级备源 URL 子串(如腾讯 qt.gtimg.cn / gold-api)。
  // 当前实测(2026-08-17)block 东财后跑马灯 8 品种无备源请求、页面 error,
  // 说明跑马灯备源兜底尚未就位 —— 这是真实验收发现,待跑马灯实施 agent 回填备源
  // 子串并确认降级后(旧源失效 + 备源发出 + 无 error)才能 PASS。
  // 回填示例:
  //   accArgs.push('--expect-request', '<备源子串>');
  //   accArgs.push('--assert', '.global-ticker .gt-name:first-child|text=现货');
}

// 布局断言:.gt-scroll 滚动容器 scrollWidth > clientWidth(一行超宽才滚动)
const layoutCheck = `
(async () => {
  const { chromium } = require('playwright');
  const b = await chromium.launch({ headless: true });
  const p = await b.newPage();
  await p.goto(process.argv[2], { waitUntil: 'domcontentloaded' });
  ${waitArg ? `await p.waitForTimeout(${parseInt(waitArg,10)});` : ''}
  const el = p.locator('.gt-scroll');
  const n = await el.count();
  if (n === 0) { console.log('[断言 FAIL] 滚动容器 .gt-scroll 不存在'); await b.close(); process.exit(1); }
  const m = await el.first().evaluate(e => ({ sw: e.scrollWidth, cw: e.clientWidth }));
  const ok = m.sw > m.cw;
  console.log(ok ? '[断言 PASS] 滚动容器一行超宽 scrollWidth>clientWidth' : '[断言 FAIL] 未超宽(可能不滚动)', JSON.stringify(m));
  await b.close();
  process.exit(ok ? 0 : 1);
})();
`;
// 布局脚本放本目录(require playwright 需在本目录 node_modules 下),跑完删除
const tmp = path.join(__dirname, '.ticker-layout-check.tmp.js');
fs.writeFileSync(tmp, layoutCheck);
let layoutCode = 0;
try {
  execFileSync(process.execPath, [tmp, url], { stdio: 'inherit' });
} catch (e) {
  layoutCode = 1;
}
fs.unlinkSync(tmp);

// 跑 accept.js 主流程(execFileSync 传数组,不经 shell,避免断言内空格被拆参)
let accCode = 0;
try {
  execFileSync(process.execPath, accArgs.slice(1), { stdio: 'inherit', cwd: __dirname });
} catch (e) {
  accCode = 1;
}

process.exit(accCode || layoutCode);
