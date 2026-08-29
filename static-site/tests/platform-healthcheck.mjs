/**
 * 平台全面体检 - Playwright 白盒测试 (v2: 实际可测版)
 * 测试基准: main 分支最新 (含 S06/overfit 修复)
 * 服务器: http://localhost:8000
 */

import { chromium } from 'playwright';
import { execSync } from 'child_process';
import { writeFileSync } from 'fs';

const BASE_URL = process.env.BASE_URL || 'http://localhost:8000';
const results = { pass: [], fail: [], skip: [], codeReview: [] };

function record(phase, id, name, ok, detail) {
  const entry = { phase, id, name, ok, detail };
  if (ok) results.pass.push(entry); else results.fail.push(entry);
  console.log(ok ? `  PASS ${id}: ${name}` : `  FAIL ${id}: ${name} -- ${detail}`);
}

function skip(phase, id, name, reason) {
  results.skip.push({ phase, id, name, reason });
  console.log(`  SKIP ${id}: ${name} -- ${reason}`);
}

// ========== Phase 1: 数据层 curl 校验 ==========
console.log('\n=== Phase 1: 数据层 curl 校验 (P0) ===');

// A1: boot.json
try {
  const bootData = await fetch(`${BASE_URL}/data/boot.json`).then(r => r.json());
  const ovDate = bootData?.overview?.date;
  const missing = bootData?._meta?.missing;
  record('Phase1', 'A1', 'boot.json数据', !!ovDate && (!missing || missing.length === 0),
    `date=${ovDate}, missing=${JSON.stringify(missing)}`);
} catch (e) { record('Phase1', 'A1', 'boot.json数据', false, e.message); }

// A2: overview.json
try {
  const ovData = await fetch(`${BASE_URL}/data/overview.json`).then(r => r.json());
  const scores = ovData?.today?.scores || {};
  const scoreKeys = ['a_sentiment', 'cross_market', 'fear_greed', 'sentiment_csi1000',
    'sentiment_csi500', 'sentiment_cyb', 'sentiment_hs300', 'sentiment_kc50', 'sentiment_sz50'];
  const missingScores = scoreKeys.filter(k => !scores[k]);
  record('Phase1', 'A2', 'overview.json/scores', missingScores.length === 0,
    `date=${ovData?.date}, missing_scores=${missingScores.join(',')}`);
} catch (e) { record('Phase1', 'A2', 'overview.json/scores', false, e.message); }

// A3: intraday_snapshot.json
try {
  const idData = await fetch(`${BASE_URL}/data/intraday_snapshot.json`).then(r => r.json());
  const idxCount = idData?.indices?.length || 0;
  const af = idData?.amount_forecast;
  record('Phase1', 'A3', 'intraday_snapshot', idxCount >= 17,
    `indices=${idxCount}, amount_forecast=${af}, collected_at=${idData?.collected_at}`);
} catch (e) { record('Phase1', 'A3', 'intraday_snapshot', false, e.message); }

// A4: alert.json
try {
  const alData = await fetch(`${BASE_URL}/data/alert.json`).then(r => r.json());
  record('Phase1', 'A4', 'alert.json', !!alData?.date,
    `date=${alData?.date}, high_score=${alData?.high?.score}`);
} catch (e) { record('Phase1', 'A4', 'alert.json', false, e.message); }

// A5: notifications.json
try {
  const nfData = await fetch(`${BASE_URL}/data/notifications.json`).then(r => r.json());
  record('Phase1', 'A5', 'notifications.json', !!nfData?.date,
    `date=${nfData?.date}`);
} catch (e) { record('Phase1', 'A5', 'notifications.json', false, e.message); }

// A6: schedule_stats.json
try {
  const ssData = await fetch(`${BASE_URL}/data/schedule_stats.json`).then(r => r.json());
  const bad = ssData?.filter(x => [143, 133, 1].includes(x?.last_exit));
  record('Phase1', 'A6', 'schedule_stats.json', !bad || bad.length === 0,
    `len=${Array.isArray(ssData) ? ssData.length : 'N/A'}, bad_tasks=${bad?.map(b => b?.task).join(',')}`);
} catch (e) { record('Phase1', 'A6', 'schedule_stats.json', false, e.message); }

// A7: ad_line.json
try {
  const adData = await fetch(`${BASE_URL}/data/ad_line.json`).then(r => r.json());
  record('Phase1', 'A7', 'ad_line.json', adData?.data?.length > 0,
    `data_len=${adData?.data?.length}`);
} catch (e) { record('Phase1', 'A7', 'ad_line.json', false, e.message); }

// A8: trade_sim_indices.json
try {
  const tsData = await fetch(`${BASE_URL}/data/trade_sim_indices.json`).then(r => r.json());
  record('Phase1', 'A8', 'trade_sim_indices.json', Array.isArray(tsData) && tsData.length >= 100,
    `len=${Array.isArray(tsData) ? tsData.length : 'N/A'}`);
} catch (e) { record('Phase1', 'A8', 'trade_sim_indices.json', false, e.message); }

// ========== Phase 2: Playwright 页面渲染 ==========
console.log('\n=== Phase 2: Playwright 页面渲染 ===');
{
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 }, ignoreHTTPSErrors: true });

  // B1: 各 tab 页面加载
  const tabs = ['overview', 'market', 'sentiment', 'fund', 'lab'];
  let tabOk = true;
  const tabDetails = [];

  for (const tab of tabs) {
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));

    try {
      await page.goto(`${BASE_URL}/?tab=${tab}`, { waitUntil: 'domcontentloaded', timeout: 20000 });
      await page.waitForTimeout(3000);
      const hasContent = await page.evaluate(() => document.body.textContent.length > 100);
      const hasErrors = errors.length > 0;
      if (!hasContent || hasErrors) tabOk = false;
      tabDetails.push(`${tab}:${hasContent ? 'ok' : 'empty'}${hasErrors ? '(' + errors.length + 'err)' : ''}`);
    } catch (e) {
      tabOk = false;
      tabDetails.push(`${tab}:${e.message.slice(0, 40)}`);
    }
    await page.close();
  }
  record('Phase2', 'B1', '各tab页面加载', tabOk, tabDetails.join('; '));

  // B2: S06 状态 (via _tdsS06State)
  {
    const page = await context.newPage();
    try {
      await page.goto(`${BASE_URL}/?tab=lab`, { waitUntil: 'domcontentloaded', timeout: 20000 });
      await page.waitForTimeout(5000);
      const s06 = await page.evaluate(() => window._tdsS06State);
      record('Phase2', 'B2', 'S06状态加载', !!s06 && !!s06.mode_id,
        `mode=${s06?.mode_id}, threshold=${s06?.threshold}, generated_at=${s06?.generated_at}`);
    } catch (e) { record('Phase2', 'B2', 'S06状态加载', false, e.message); }
    await page.close();
  }

  // B3: 无 console.error 错误
  {
    const page = await context.newPage();
    const consoleErrors = [];
    page.on('console', msg => { if (msg.type() === 'error') consoleErrors.push(msg.text().slice(0, 100)); });
    page.on('pageerror', e => consoleErrors.push(e.message.slice(0, 100)));

    try {
      await page.goto(`${BASE_URL}/?tab=lab`, { waitUntil: 'domcontentloaded', timeout: 20000 });
      await page.waitForTimeout(5000);
      record('Phase2', 'B3', '无console.error', consoleErrors.length === 0,
        consoleErrors.length === 0 ? '无错误' : `${consoleErrors.length}个错误: ${consoleErrors.slice(0,3).join('; ')}`);
    } catch (e) { record('Phase2', 'B3', '无console.error', false, e.message); }
    await page.close();
  }

  // B4: 凯利卡片 DOM 存在
  {
    const page = await context.newPage();
    try {
      await page.goto(`${BASE_URL}/?tab=lab`, { waitUntil: 'domcontentloaded', timeout: 20000 });
      await page.waitForTimeout(5000);
      // 进入凯利区
      await page.evaluate(() => {
        const btns = document.querySelectorAll('button');
        for (const b of btns) { if (b.textContent.includes('凯利')) { b.click(); break; } }
      });
      await page.waitForTimeout(3000);
      const cardCount = await page.evaluate(() => {
        return document.querySelectorAll('[class*="kelly"], [class*="sigkelly"]').length;
      });
      record('Phase2', 'B4', '凯利卡片DOM', cardCount > 0,
        `found ${cardCount} elements`);
    } catch (e) { record('Phase2', 'B4', '凯利卡片DOM', false, e.message); }
    await page.close();
  }

  await browser.close();
}

// ========== Phase 3: 后端脚本校验 ==========
console.log('\n=== Phase 3: 后端脚本校验 ===');

// C1: check_data_integrity.py
try {
  const integrity = execSync('python3 scripts/check_data_integrity.py 2>&1', {
    encoding: 'utf8', timeout: 60000
  });
  const failCount = (integrity.match(/✗/g) || []).length;
  const okCount = (integrity.match(/✓/g) || []).length;
  const warnCount = (integrity.match(/⚠/g) || []).length;
  const summary = integrity.match(/汇总: (.+)/)?.[1] || '';
  record('Phase3', 'C1', 'check_data_integrity', failCount === 0,
    `${summary} (ok=${okCount}, warn=${warnCount}, fail=${failCount})`);
} catch (e) {
  const output = (e.stdout || '') + (e.stderr || '');
  const failCount = (output.match(/✗/g) || []).length;
  record('Phase3', 'C1', 'check_data_integrity', false, `exit=${e.status}, fails=${failCount}, output=${output.slice(0, 300)}`);
}

// C2: check_overfit_recent_parity.mjs
try {
  const parity = execSync('cd /Users/linhuichen/code/trade && node scripts/check_overfit_recent_parity.mjs 2>&1', {
    encoding: 'utf8', timeout: 30000
  });
  const hasFail = parity.includes('FAIL');
  record('Phase3', 'C2', 'check_overfit_recent_parity', !hasFail, parity.slice(0, 300));
} catch (e) {
  const output = (e.stdout || '') + (e.stderr || '');
  record('Phase3', 'C2', 'check_overfit_recent_parity', false, output.slice(0, 300));
}

// ========== Phase 4: 代码审查(只读) ==========
console.log('\n=== Phase 4: 代码审查 ===');

// D1: check_overfit_recent_parity.mjs 改动
try {
  const diff = execSync('cd /Users/linhuichen/code/trade && git diff scripts/check_overfit_recent_parity.mjs 2>&1', {
    encoding: 'utf8', timeout: 10000
  });
  if (diff.length > 10) {
    results.codeReview.push({
      file: 'scripts/check_overfit_recent_parity.mjs',
      issue: `有未提交改动 (${diff.split('\n').filter(l=>l.startsWith('+')).length}行新增)`,
      suggestion: '确认改动正确并提交'
    });
    console.log(`  审查: check_overfit_recent_parity.mjs 有未提交改动`);
  } else {
    console.log('  审查: check_overfit_recent_parity.mjs 无未提交改动');
    record('Phase4', 'D1', 'check_overfit无未提交改动', true, '无改动');
  }
} catch (e) {
  console.log('  审查: git diff 失败');
  record('Phase4', 'D1', 'check_overfit无未提交改动', false, e.message);
}

// D2: S06 状态检查
try {
  const s06 = execSync('cd /Users/linhuichen/code/trade && python3 scripts/check_s06_state.py 2>&1 || true', {
    encoding: 'utf8', timeout: 15000
  });
  const s06Ok = !s06.includes('FAIL');
  record('Phase4', 'D2', 'check_s06_state', s06Ok, s06.slice(0, 300));
} catch (e) {
  record('Phase4', 'D2', 'check_s06_state', false, e.message);
}

// ========== 生成报告 ==========
await browser.close().catch(() => {});

const totalTests = results.pass.length + results.fail.length + results.skip.length;
const report = `# 平台全面体检报告 (2026-08-29)

## 测试概览
- 总测试数: ${totalTests}
- 通过: ${results.pass.length}
- 失败: ${results.fail.length}
- 跳过: ${results.skip.length}

## 失败项详情
${results.fail.length === 0 ? '无失败项' : '| # | 模块 | 测试点 | 失败原因 | 严重度 |\n|---|------|--------|---------|--------|\n' + results.fail.map((f, i) => `| ${i+1} | ${f.phase} | ${f.name} | ${f.detail} | - |`).join('\n')}

## 跳过项
${results.skip.length === 0 ? '无跳过项' : results.skip.map(s => `- ${s.id}: ${s.name} (${s.reason})`).join('\n')}

## 代码审查发现
${results.codeReview.length === 0 ? '无发现问题' : '| # | 文件 | 问题 | 建议 |\n|---|------|------|------|\n' + results.codeReview.map((r, i) => `| ${i+1} | ${r.file} | ${r.issue} | ${r.suggestion} |`).join('\n')}

## 通过项清单
${results.pass.map(p => `- ${p.id}: ${p.name} (${p.detail})`).join('\n')}
`;

writeFileSync('/tmp/platform-healthcheck-report.md', report);
console.log('\n=== 报告已写入 /tmp/platform-healthcheck-report.md ===');
console.log(`\n=== 最终结果: ${results.pass.length} PASS / ${results.fail.length} FAIL / ${results.skip.length} SKIP ===`);
