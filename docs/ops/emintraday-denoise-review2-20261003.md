# emintraday-denoise Review2(复验)报告 — 2026-10-03

> 分支 `feat/emintraday-denoise-20261002`,commit `ec202edaa`(fast-forward push `a62563f5a..ec202edaa`)。
> 上一轮对 `a62563f5a` 出「不能 merge」三项 finding,本轮复验修复。独立复验,不采信 implementer 自述。
> reviewer:独立实跑 A/B 脚本(after/before 双侧)+ 单测 14 断言 + curl 腾讯港股接口 + git 逐位比对。

## 结论:可以 merge(代码层充分验证),10-05~07 首次港股开市日需实盘观察(见必查项2)

---

## 🔴 必查项1:HK 判定完备性 — PASS(置信 90)
- `_INDEX_MARKET[code]==="hk"` 覆盖**全部港股分时标的**:定义在 L12755-12757,`hsi/hstech/hscei` 3 个,与 `_INTRADAY_INDICES`(12 指数)/`_INDEX_TO_TENCENT_MINUTE` 一一对应,无遗漏(分时渲染只服务这 12 个)。
- `_inHkSession` = renderIntradaySection 新增局部变量:工作日(周一~五)+ 北京时间 9:30-16:00 判定,近似港股交易时段(含午休 12:00-13:00,边界保守)。错位日(工作日)能正确识别。
- 港股真休市(周末):页面 `_holiday` 兜底 collapsed → 不发请求(周末无回归,已由 F1 默认 mode=collapsed 佐证)。
- **代价(可接受,已在报告):**「工作日 A股休市 + 港股也休市」日(如 10-01 国庆、春节初一),`_inHkSession=true` → 页面展开,港股 3 code 恒放行发请求(约 3 个,腾讯返回最近交易日,快照兜底)。噪音量小,非死图,不白屏(三腿兜底)。
- 与 `_buildHealthSources`(L12298-12310,港股用 `hkIdx.is_closed===false` per-index 单独判):两处角色不同(展示标签 vs 请求守卫),**非同一函数同一口径**,但「港股不绑定 A股日历」精神一致。§22 无冲突(不同展示位语义本就不同)。

## 🔴 必查项2:测试强度 / merge 时机 — PASS(可 merge,需 10-05 观察,置信 95 逻辑层 / 85 数据源当日行为)
### 日期事实(独立核实)
- 今天 2026-10-03 **周六**(`date` 确认)。10-01 周四 / 10-02 周五 / 10-05~07 周一~周三。
- 港股国庆:10-01 休市,10-02 开市(周五,已过),10-05~07 开市(A股国庆休市,A股/港股错位日 = 本修复目标场景)。
### 机制层验证(独立实跑,与 implementer 声称逐项一致)
- **A/B `em_denoise_hk_ab.mjs`(我改路径独立实跑):**
  - after(F1):boot snap is_closed=true(sh=2026093016/hkHSI=2026093018,周六真实线上),点仅分时后新增:A股-THS=0 / A股-EM=[] / **HK-QQ=["hkHSI","hkHSTECH","hkHSCEI"]** → 港股放行 YES、A股休市不拉实时 YES。
  - before(F1,基线 a62563f5a app.js):HK-QQ=[] → 港股被短路冻结(原 bug 复现)。
  - after(F2):注入盘中 snap(is_closed=false)同帧点仅分时:A股 9 EM 全发起 + HK-QQ 3 → applyMode 用最新 snap YES。
  - before(F2):全 0 → 闭包旧 snap 拦截(原 bug 复现)。
- **单测 `test_mkt_closed_code.mjs` 14 断言全 PASS**(港股 3 放行 / A股 3 休市拦截 / 盘中不拦 / 周末 A股拦港股放行 / snap=null 不拦)。
- **数据源行为 curl 实测:** 腾讯 `web.ifzq.gtimg.cn/appstock/app/minute/query?code=hkHSI` 今日(周六)返回 `0930 24099.730 ...` = **最近交易日(10-02)分时**,证明"非交易日返回最近交易日"成立(implementer 声称验证)。
### 未实测项(诚实标注)
- **「港股开市日数据源返回当日数据」+ 端到端(10-05~07 港股实时曲线正确渲染)未实测**(今天/10-02 已过,无法复现开市日盘中)。置信度:腾讯港股接口按港交所日历返回,高置信(85)但非本环境实测。
- 失败模式:**降级无害**——数据源若异常,港股显示最近交易日旧数据 + "快照"标签(三腿兜底 `_fetchIntradayRenderSource` 东财→腾讯→中继,全失败走 `_renderSnapMinuteSeries`),不白屏、不死图。
### merge 时机结论
- 代码逻辑层充分验证(置信 95),失败模式无害(置信 85)。**可以 merge。**
- **但 10-05~07 是首次实盘场景,必须安排上线后观察**(人工/curl 看港股分时日期是否为当日),若异常降级为旧数据,10-05 晚可快速修复/revert。§23.15 完整性:非残缺版(代码逻辑完整,数据源行为异常属边界降级)。
- 若用户/主控要绝对稳妥,可选「等 10-05 实盘复验后 merge」:10-05 白天验证(港股盘中 9:30-16:00),23:00 后安全窗口 merge+deploy → 10-06 生效,丢 10-05 一天。权衡建议:现在 merge(10-05 当天生效覆盖 3 个开市日)+ 观察。

## 必查项3:A股行为不回归 — PASS(置信 90)
- A股休市日仍走快照渲染不发实时:after F1 A股-THS=0 ✓;单测 A股休市拦截 true ✓;`_isMarketClosedTodayForCode(cn)` 沿用顶层 `_isMarketClosedToday` 口径。
- 交易日盘中 A股正常拉实时:守卫对 A股沿用顶层(snap 今日 → 不拦),F2 注入盘中 snap 后 A股 9 EM 全发起 ✓。
- 周末 collapsed 保持:F1 默认 mode=collapsed(周六真实环境)✓。
- 唯一行为变化(非回归):工作日 A股休市 + 港股时段 → 页面从 collapsed 变展开(设计取舍,见必查项1)。

## 必查项4:Finding2/3 修复有效性 — PASS(置信 90)
- **Finding2:** `state.intradaySnapshot` 赋值点已验证:boot(L9803)/sessionStorage 恢复(L11592)/`fetchIntradaySnapshot` 成功(L11597,单例,含 `_doOverviewRefresh` race、`_doIntradayRefresh` L14007 前强制刷新、`_startMarketOpenCheck` tick 多路径更新)→ 是全局最新权威,比闭包 boot snap 新。修复有效。edge:9:15 前今日 snap 未生成时 curSnap 仍昨日(无解,开盘后自动更新+`_doIntradayRefresh` 1min 重渲染自愈)。
- **Finding3:** `_preOpenDelay` 9:15 前分支(3min/15s)已实现(L14493-14495),逻辑正确:9:15 前快检测保证交易日开盘切换不被拖慢,9:15 后 snap 仍昨日 = 确定节假日 → 30min 低频。节假日仅在 9:00-9:15 多几个请求(量小),无反向密集请求。

## 必查项5:rebase 链 `bd83f7c78` — PASS(置信 95,逐位比对)
- `git show bd83f7c78 --stat`:仅 2 文件(claude-work-mode/README.md + config-snapshots/2026-10-02.json),与 main `98e2998de` 的 stat 完全一致(作者/时间戳/文件)。
- **逐位 md5 对比:README.md `1e54ab6d…`(bd83f7c78) == `1e54ab6d…`(98e2998de);config-snapshots `da1aca35…` == `da1aca35…`。内容完全相同。**
- 无夹带(bd83f7c78 相对其父 a62563f5a 仅改这 2 文件)。merge 时同内容自动消解成立。

## 必查项6:其他 — PASS(置信 90)
- 无夹带:`git show ec202edaa --stat` 仅 6 文件(app.js 43 行 + 5 个测试脚本),与声称一致。feat tree `git ls-tree` 无 `_dbg_f2_probe.mjs`(untracked 未 commit)。
- 不自行 bump 版本串/不重建 min:ec202edaa 只改 app.js 源码未 bump,机制 C 由 main-merge.sh 统一处理(符合规范)。
- §21 公示:diff + 行无 score/权重/百分位等算法关键词;purpose-notes.js 无休市/分时渲染规则相关公示文案需同步。无同步项成立。
- §23.2 同类面:guard / `_holiday` / `_preOpenDelay` 三处同步改;`_buildHealthSources` 港股本就 per-index 判(不回归);市场开盘检测用 A股口径正确不涉港股。
- §15 老功能:12 指数分时主渲染路径未动;A股休市拦截保持;交易日盘中实时不回归。

## 低分项(<80)已滤(2 项)
1. 港股午休(12:00-13:00)`_inHkSession` 仍 true(9:30-16:00 连续窗口),午休请求返回旧数据——无害,纯降级。分值 <80。
2. 9:00-9:30 港股盘前打开页面 collapsed,9:30 开盘后需手动刷新/切模式才展开——边缘 UX,非 P0,分值 <80。

## 主控建议(一句话)
**可以 merge**;merge 后 10-05~07(周一~周三,A股休/港股开,首次实盘场景)必须安排观察港股分时是否当日实时,异常即降级为旧数据(无害,快照兜底),可 10-05 晚修复。
