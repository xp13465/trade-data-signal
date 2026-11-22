/**
 * fade_mode_dd_helper.js — 降亏模式下拉「压缩折叠」后的选档 helper(2026-11-22)
 *
 * 背景: 2026-11-22 起降亏模式下拉改为「主列表 4 档(S06/A进攻王/NEW14/B均衡卡) + 更多模式(5 档·已收纳)折叠区」。
 *   原生 <select id=...> 仍是值源/兼容层(隐藏), 但 p8/p9/c9/new15/s06p1 五个档位在可见面板里收在折叠区,
 *   直接 page.selectOption / 直接点选项点不到 —— 本 helper 按真实用户路径操作: 点开面板 → (折叠区档位先展开折叠区) → 点该档。
 *
 * 用法:
 *   const { pickFadeMode } = require('./fade_mode_dd_helper');
 *   await pickFadeMode(page, 'sim-fade-mode-sel', 'p8');
 *
 * 断言语义不变: 仍是「用户选 p8 后, localStorage 记忆/表格重渲染/选中值 = p8」, 只把操作路径改成真实点击。
 */
async function pickFadeMode(page, selectId, modeId) {
  const wrap = page.locator('.tds-fade-mode-dd').filter({ has: page.locator('#' + selectId) }).first();
  if ((await wrap.count()) === 0) throw new Error('未找到降亏模式下拉容器: ' + selectId);

  const panelOpen = await page.evaluate((id) => {
    const s = document.getElementById(id);
    const w = s && s.closest('.tds-fade-mode-dd');
    const p = w && w.querySelector('.tds-fade-mode-panel');
    return !!(p && !p.hidden);
  }, selectId);
  if (!panelOpen) await wrap.locator('.tds-fade-mode-ddb').click();

  const inExtra = await page.evaluate((args) => {
    const s = document.getElementById(args.id);
    const w = s && s.closest('.tds-fade-mode-dd');
    const o = w && w.querySelector('[data-fade-mode-opt="' + args.mode + '"]');
    return !!(o && o.closest('.tds-fade-mode-extra'));
  }, { id: selectId, mode: modeId });
  if (inExtra) {
    const moreOpen = await page.evaluate((id) => {
      const s = document.getElementById(id);
      const w = s && s.closest('.tds-fade-mode-dd');
      const d = w && w.querySelector('.tds-fade-mode-more');
      return !!(d && d.open);
    }, selectId);
    if (!moreOpen) await wrap.locator('.tds-fade-mode-more-sum').click();
  }

  await wrap.locator('[data-fade-mode-opt="' + modeId + '"]').click();
  await page.waitForFunction((args) => {
    const s = document.getElementById(args.id);
    return !!s && s.value === args.mode;
  }, { id: selectId, mode: modeId }, { timeout: 10000 });
}

export { pickFadeMode };
