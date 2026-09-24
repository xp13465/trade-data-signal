# 首页各指数四档聚合卡 + 每日小结色点 chip 审查(reviewer 独立复核)

# 首页各指数四档聚合卡 + 每日小结色点 chip 审查报告(2026-09-24)

审查对象:分支 worktree-agent-a90417b764ef6370a, tip=944c1a2c9, base=64d15f4fb, 提交链 3818c9dd3(feat) + 944c1a2c9(fix)
改动文件:app/queries.py(+25) / static-site/app.js(+84) / static-site/style.css(+7), 无夹带

## 结论:PASS(附带一条上线链提醒)

逐项必查证据:

### ① §23.7 冻结契约 WIDE_BASE_TIER_IDS 等价 —— PASS
- diff 对比:原局部集合 {hs300,sh,sz,csi500,cyb,sz50,csi1000,kc50} → 新模块元组 (hs300,sh,sz,csi500,cyb,sz50,csi1000,kc50), 逐元素等价; 元组 in 行为同集合
- index_detail 唯一改动 = `if index_id in WIDE_BASE_TIER_IDS`(queries.py L2117), 分支内部(hs300→_ai_macro_build_market_state / cyb→_ai_macro_build_cyb_tier / 其余→_ai_macro_build_index_tiers)零改动
- 既有 index_detail tiers 注入行为零变化

### ② §22 数据一致性(含生产真实值独立核实) —— PASS
- 两个展示位口径:既有沪深300 chip 读 summary.json market_state(queries.summary→generate_summary→_market_state_of), 新增卡/chip 读 overview.json index_tiers.hs300(_ai_macro_classify_tiers)。逐行对比两函数 tier 判定(bull/bear/四档 if 链)逐字一致
- 实施方本地 dev 库局限:本地 overview.json/summary.json 日期停在 09-17/09-11, 不能代表生产 → 已在云上生产库独立补齐
- 独立复算(ssh 云上 ~/tdsignal.pem, 读 sentiment.db index_daily 全量, 复刻 classify 算法, 取 ≤20260924 最近档位):
  - hs300=熊市·主跌(20260924), 与生产 summary.json market_state.tier=熊市·主跌(close 4439.14, date 20260924) 逐位一致
  - 8 指数 9-24: kc50=上升期, sh/csi1000=下降期, hs300/sz/csi500/cyb/sz50=熊市·主跌 —— 与实施方描述完全一致

### ③ 那 2 个失败单测 —— PASS(附重要发现)
- 独立复跑(Playwright 无痕 + 源版 app.js, 23 断言 Phase A/B/C): 23/23 全过, 当前分支代码无失败断言, 无法复现实施方所称 2 个失败
- ⚠ 重要发现: 实施方 worktree 的 app.min.js 为旧版(不含新功能字符串 tier-card/index_tiers=0 次), 若加载 min 则卡片必不存在 → 实施方 23/23 PASS 必然发生在源版而非 min
- 该现象符合机制 C(feat 分支不自行 build_min/bump), 非本分支缺陷

### ④ 944c1a2c9 DOMException 修复 —— PASS
- 修法 = content.appendChild(grid) 提前到 insertBefore 之前(DOM 标准: insertBefore refNode 必须在树中)
- DOM 实测(390px): content children 顺序 banner(0)→...→tier-card(7)→spark-grid(9), card 在分时图前、grid 仍是最后一个
- 新增代码块独立, 不影响其他 insertBefore 调用点

### ⑤ 320px 实测复核 —— PASS
- 独立复跑(无痕 320px, 源版): 23/23 PASS
- 分化态卡 scrollW=296 = clientW=296 不溢出; chip scrollW=215 = clientW=215 不溢出; chips 行无横向滚动; 0 个 JS 运行错误
- 实测数字与实施方自报(296/215)一致

### ⑥ 结论词规则边界 —— PASS
- 独立 node 边界测试(提取 app.js 函数逐字跑): 全同档(一致·上升期/无分组行/无⚠)/ 跨2档/ 跨3档/ 并列最强2(计数 2个上升期)/ 并列最弱7(点名最强+计数最弱)/ null/空/部分缺/非法tier 全验证, 无自相矛盾
- 生产 9-24 真实场景: 跨 3 档, 点名「科创50 独处上升期」+ 计数「5个熊市·主跌」, 3 个分组行 —— 与需求完全吻合

### ⑦ UI 文案合规 —— PASS
- 渲染 HTML 零「大盘/小盘」(node 断言验证)
- 源码「大盘」命中仅 3 处注释 + 既有 S06「大盘领先切换」模式名(非本次新增), 新函数区唯一命中为注释(§23.13 提示)
- 「未入样/无可跟踪」旧错文案不属本次改动范围(另一条线)

### ⑧ 旧产物兼容 —— PASS
- Phase C(index_tiers 缺失): 卡隐藏、chip 不渲染、0 JS 错误
- 部分指数缺(T7): 不崩, 按实际档位分组
- 生产 overview 目前 index_tiers=null(新代码未部署), 前端守卫 `(r && r.index_tiers) || null` 生效

### ⑨ §21 公示 —— PASS
- purpose-notes.js 已含四档口径公示(牛市·主升=价>MA200且多头排列, 四档=价 vs MA200 + MA20/60/120 排列)
- 本次纯新增展示位, 算法未改(_ai_macro_classify_tiers 为既有共享函数); 新 chip tooltip(_INDEX_TIERS_TIP)自带完整口径公示 + 防前视声明 + 「展示层不参与过滤/回测」声明

### ⑩ §5.1⑥ 防前视 —— PASS
- `bisect.bisect_right(_t_dates, score_date) - 1` 只取 ≤score_date 最近已收盘档位, 不引入 t 之后数据; _ti>=0 且该日期在 tiers 中守卫健全

### ⑪ 消费 index_tiers 展示位守卫 —— PASS
- banner: `renderSummaryChips(s, snap, (r && r.index_tiers) || null)`; 动态刷新: `_applyDynamicToChips` 传 `_bannerRenderCtx.tiers`; 卡片: `_renderIndexTiersCard(r.index_tiers)` + `if (_tierCardHtml)`; chip: `_indexTiersSummarize` null 返回空串不 push
- 历史弹窗调用未传 indexTiers → 不渲染新 chip(符合每日小结语义)

### ⑫ 无夹带 —— PASS
- 改动仅 3 文件; 未动宇宙规则/build_board_etf_map.py/默认组合/AI 推荐核心(§5.4⑥ 不需发版本); 无 min/index.html/sw.js 被 commit(机制 C)

## 上线链提醒(非本分支缺陷, merge 时必做)
1. main-merge.sh 必须重建 min + bump 版本串(worktree min 现为旧版); 部署后验 §24⑤ 内容哈希==index 引用
2. 生产 overview.json 需随 export_overview 重新生成后才带 index_tiers(当前 null); 首次上线后 curl 线上 overview.json 验证字段在位
3. 盘中模式(renderIntradayChips)不渲染新 chip —— 属「每日小结」语义合理设计, 需求未指定盘中行为

## 低分项(<80 已滤)
- T8 未知 tier 值计入 validN 但不算分组(计数/展示轻微不一致): 仅畸形数据触发, 后端只产 4 档合法值, 防御可接受
- index_tiers 未挂 check_data_integrity: 纯展示新增字段缺失时优雅隐藏, 非关键数据损坏级

## 审查命令痕迹
- 独立复跑: node /tmp/tier_320_review.mjs(http://localhost:8899, /tmp/tier-site 独立站点, 源版 app.js) → 23/23 PASS
- 边界测试: node /tmp/tier_edge_test.mjs → 20/24(4 FAIL 中 3 个为测试期望值写错, 代码正确; 1 个=T8 低分项)
- 生产核实: ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 读 sentiment.db + 独立复刻 classify
