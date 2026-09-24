# 每日小结展示多指数四档状态 —— 可行性调研(家底 + 方案)

> 调研日期 2026-09-24,只读调研,未改任何代码。主控口径:最终目标 = 首页一张聚合卡片,把已有各指数四档聚合展示,不做可行性论证(判定已成立),产出家底/数据供给/卡片落点。

## 一、结论摘要

- **可行,且是纯展示、低代价**:8 个宽基指数(hs300/sh/sz/sz50/csi500/csi1000/cyb/kc50)的**四档状态后端全已算好、口径完全一致**,且已随 `index/{id}-all.json` 上线(R2),前端指数图四档色带在用。缺的只是「首页这张聚合卡片」+「把 8 个指数的最新档位喂给首页」。
- **kc50 有现成四档**(在 index/kc50-all.json,同口径算法),不是没做。9/24 真实值 = 上升期。
- **推荐做法**:overview.json 加一个新字段(8 宽基最新档位映射),renderOverview 在 banner 下方插一张聚合卡(渐变条分组,用户示意形态);现有沪深300 chip 完全不动。
- **不碰默认组合/AI推荐核心** → 不发版本、不动测试基准 v1.1.7。§23.7 冻结契约定性 = 纯新增展示(与 index_detail 注入 tiers 同先例,「只增不改」)。

## 二、家底清单(核心)

| 指数 | index_id | 四档计算位置 | 产物(四档所在) | 前端现在用了吗 |
|---|---|---|---|---|
| 沪深300 | hs300 | `_ai_macro_build_market_state`(app/queries.py:605,内联实现) | ① summary.json `market_state`(仅最新日)② market_tier_history.json(全史 2002 起)③ index/hs300-all.json `tiers` ④ signal_kelly_trades.json `market_tier`/`market_tier_all` | **是,首页 chip**(app.js:12186 `_renderMarketStateChip`)+ 指数图四档色带 + 凯利区过滤键 excludeSpecialBear |
| 创业板指 | cyb | `_ai_macro_build_cyb_tier`(app/queries.py:699)→ 共享 `_ai_macro_classify_tiers` | ① index/cyb-all.json `tiers` ② signal_kelly_trades.json `market_tier_cyb` | 凯利区过滤键 excludeSpecialBearCyb(app.js:3493,默认关)+ 指数图色带;**首页无** |
| 科创50 | kc50 | `_ai_macro_build_index_tiers`(app/queries.py:715)→ 共享函数 | index/kc50-all.json `tiers` | 指数图色带;**首页无** |
| 上证指数 | sh | `_ai_macro_build_index_tiers` | index/sh-all.json `tiers` | 指数图色带;**首页无** |
| 深证成指 | sz | `_ai_macro_build_index_tiers` | index/sz-all.json `tiers` | 指数图色带;**首页无** |
| 上证50 | sz50 | `_ai_macro_build_index_tiers` | index/sz50-all.json `tiers` | 指数图色带;**首页无** |
| 中证500 | csi500 | `_ai_macro_build_index_tiers` | index/csi500-all.json `tiers` | 指数图色带;**首页无** |
| 中证1000 | csi1000 | `_ai_macro_build_index_tiers` | index/csi1000-all.json `tiers` | 指数图色带;**首页无** |

- 8 宽基名单定义:`app/queries.py:2087` `_WIDE_BASE_TIER_IDS = {"hs300","sh","sz","csi500","cyb","sz50","csi1000","kc50"}`,在 `index_detail`(queries.py:2082)注入 tiers,`static-site/export.py:1375` 导出到 `index/{id}-all.json`(R2,44 个指数全历史大文件)。
- **口径一致性**:除 hs300 走内联实现外,其余 7 个全走共享纯函数 `_ai_macro_classify_tiers`(app/queries.py:667)。已逐字比对 hs300 内联段与共享函数的 4 条判定行(bull/bear/四档赋值),**逐字一致**(差异仅为共享函数无 ma60_bull 附加输出)。另 `app/compute/market_summary.py:81 _market_state_of`(summary.json chip 的数据源)判定规则也逐字一致(牛市·主升/上升期/熊市·主跌/下降期 + 极端回退上升期)。三处实现同规则,无分叉。
- **`market_tier_all` 语义**(已查实):= **hs300 四档,对所有 market(含 hk/global)无条件注入**;`market_tier` = hs300 四档×仅 A 股类注入(`scripts/signal_kelly_backtest.py:1561-1563`)。**不是"全市场综合档"**,命名易误读,语义就是沪深300。与 cyb 无关。
- 中文名映射(展示直接复用):`app/compute/position.py INDEX_NAMES`(sh=上证指数/sz=深证成指/hs300=沪深300/sz50=上证50/csi500=中证500/csi1000=中证1000/cyb=创业板指/kc50=科创50)+ 前端 `_INDEX_NAME_MAP`(app.js:1293)+ overview.json `indices_sparkline[].name`。

## 三、四档口径定义 + 防前视

- 四档:牛市·主升 / 上升期 / 下降期 / 熊市·主跌。
- 规则(共享函数 app/queries.py:660-694,与 market_summary.py:151-159 一致):
  - 牛市·主升 = close > MA200 且 多头排列(MA20>MA60>MA120)
  - 上升期 = close > MA200 且非多头
  - 熊市·主跌 = close < MA200 且 空头排列(MA20<MA60<MA120)
  - 下降期 = close < MA200 且非空头
  - 极端(c==MA200)= 上升期
- **防前视(§5.1⑥)**:判定只用到 ≤t 的收盘序列(MA = 截至 t 的最近 w 根收盘均值,rolling 非全期分位);t 日收盘后才能定 t 日档位。无全期分位、无未来数据参与。**PASS**。
- 盘中语义:summary.json 的 `market_state` 是最近已收盘交易日档位,`market_state_est`(盘中预估,仅 hs300)用当日实时价×昨日均线。8 宽基无盘中预估实现(见诚实标注)。

## 四、数据供给方案(把 8 宽基最新档位喂给首页)

现状:首页聚合卡要的数据(8 指数最新档位)**后端有算法、但没进首页数据源** —— overview.json 只有 `market_state`(hs300 单指数,且生产当前为 null,chip 数据实际走 summary.json)。8 宽基最新档位散在 8 个 index-all.json 大文件里(前端全拉不现实)。

推荐(主控已圈定方向,细化为两案):
- **A 案(推荐):overview.json 新增字段 `index_tiers`** = `{iid: {tier, date}}`,仅 8 宽基最新档位(可含 ma60_bull 可选)。生成点 = `queries.overview`(app/queries.py:1082)内 indices_sparkline 同段(1564 附近已有 8 宽基 index_daily 读取先例),复用 `_ai_macro_build_index_tiers` + `_ai_macro_tier_at` 取 ≤score_date 最近档位。前端 renderOverview 的 `r.index_tiers` 直接可用,零额外请求。
- **B 案(备选):独立小产物 `index_tiers_latest.json`**(如 market_tier_history.json 同款独立 export),不动 overview schema;代价=前端多一个 fetch(boot.json 未含,需加 URL)。
- **旧产物兼容**:overview.json 是 `static-site/export.py:756`「main 必更白名单首件」,deploy 必带;旧文件无 index_tiers → 前端 `r.index_tiers || null` 守卫,卡片不渲染、不崩(与现 `_renderMarketStateChip` 的 `!s.market_state` 守卫同模式)。
- **§22 三步同步**:overview.json 在 export.py:1004 导出 → deploy.sh 上传 R2 → 备站。算法改动重跑数据产物时,static-site/data + R2 + 备站三步齐即可,无第四展示位。

## 五、卡片落点与展示形态(含移动端)

**落点**:renderOverview(app.js:15108)的 banner(15211)之后、分时图(16380)之前,作为**首页第一张卡**插入.ov-2col 或独立 chart-card。移动端 768px 以下 ov-2col 变单列(style.css:1597),卡在 banner 下首屏可见,位置感强。

**形态(按用户渐变条分组示意)**:
- 标题:「宽基四档」+ 日期。
- 主体 = 四档分组条(最多 4 行),每行列该档位指数 chip(如「沪深300」「上证50」…);空档标「暂无」。
- 8 指数全同档 → 收成一行(直接显示「8 指数全部 · 熊市·主跌」),这是常态期的最省形态。
- 档位 chip 颜色复用 `_TIER_COLORS`(app.js:8770:牛市·主升#e6492e/上升期#f2a06e/下降期#8fc29a/熊市·主跌#2e8b57),红涨绿跌全站一致。
- ↑↓ 昨日档位(指数内当日升降):index-all tiers 是**前向填充**(index_detail 每日期取最近可用 tier,queries.py:2104-2112),倒数第二行可取 → 每指数可标「↑ 上升期 / ↓ 熊市·主跌」;缺昨日值则只显示今日档位。
- 分化提示(推荐顺带):卡内一行弱化字,如「⚠ 分化:沪深300 熊市·主跌 vs 科创50 上升期」,只在 8 指数跨 ≥2 档时出现(9/24 就跨 3 档)。

**移动端空间预算**(口 mobile-a11y-font-touch-live:字号≥11px、可点控件≥44px):
- 行高 26-28px(纯展示行,非点击控件,不受 44px 约束;若 chip 加 hover tooltip 则桌面可点,移动端点击区域用 padding 补足或不做跳转);
- 高度 ≈ 标题行 28px + 最多 4 档行 ×28px + 分化行 26px ≈ **160-190px**,低于现有移动端 .chart-card min-height 280px(style.css:3979),不会挤爆首屏。
- 现有 summary-chips 是 flex-wrap 12px chip(style.css:3008),同款样式直接复用;8 指数 4 档分布下每行最多 3-4 个 chip,375px 宽一行放 2-3 个,超长换行即可。

## 六、真实快照(2026-09-24,生产 R2 index-{id}-all.json 末条)

| 档位 | 指数 |
|---|---|
| 牛市·主升 | (无) |
| 上升期 | 科创50(kc50) |
| 下降期 | 上证指数(sh)、中证1000(csi1000) |
| 熊市·主跌 | 沪深300(hs300)、深证成指(sz)、上证50(sz50)、中证500(csi500)、创业板指(cyb) |

- 8 指数落在 3 档,真实呈现「大盘牛小盘不牛」式的分化;与用户举例(cyb 熊市·主跌、kc50 上升期)吻合。
- 同日 hs300 chip(生产 summary.json 9/24)="熊市·主跌",与 index/hs300-all.json 末条一致 → 聚合卡与现有 chip 同源同值,§22 多展示位一致有保障。
- 数据层 8 指数最新日全部 = 20260924,无滞后(云上 sentiment.db index_daily 核实,见附录)。

## 七、代价与风险

1. **默认组合/AI推荐核心**:完全不动(纯展示新卡,现有 chip/过滤键零改动)→ 不发中间版本、不动测试基准(memory test-baseline-v112-anchor,v1.1.7 无影响)。
2. **后端产物 schema**:overview.json 纯新增字段 index_tiers(不删改旧字段)→ §22 三步同步(export→R2→备站)+ 前端旧产物守卫。index_detail 已有同款「只增不改」先例(#73 注入 tiers,§23.7)。
3. **计算成本**:8 宽基最新档位 = 8 × 一次分类(每指数只取最近 ~201 根收盘),毫秒级;index_detail 全史四档(8 指数×全史)每天已在跑,无增量负担。
4. **§23.7 冻结契约**:定性 = 纯新增展示(同 index_detail tiers 先例「只增不改」),非改已上线展示行为;唯一注意 = 不能动现有 summary.json market_state 字段语义。
5. **前端**:app.js 改(加卡渲染)+ 版本串随内容强制刷新(§24:同 commit bump+build_min+校验);lab.js/common.js 不用动。

## 八、诚实标注

- **8 宽基盘中预估档位(est)无现成**:`market_state_est` 仅 hs300 有(market_summary.py:512)。聚合卡盘中展示建议沿用「最近已收盘档位」语义(与现有 hs300 chip 盘中显示昨日档位一致),不做盘中实时预估 —— 此点未深挖盘中链路,依据 summary.json 结构推断。
- **「大盘/小盘」分组无既有代码定义**:全仓 grep「大盘股/小盘股/大盘指数」无结果。若卡片要分「大盘/小盘」维度,需用户拍板口径(建议纯数据派生措辞:大盘=hs300/sh/sz/sz50,中小盘=csi500/csi1000/cyb/kc50;不参与任何过滤语义)。
- **bj50(北证50)**:index_daily 有数据(sparkline 名单含 bj50,app/queries.py:65),但不在 8 宽基四档名单。要加只需把 bj50 加进 `_WIDE_BASE_TIER_IDS` + 同函数算;bj50 数据长度未查(推断够 200 根,待实施前核实 MIN(date))。
- **hs300 内联实现是历史包袱**:与共享函数现逐字一致,但将来改共享函数 hs300 不会自动跟(两份副本)。本任务不动;建议后续低风险重构把 hs300 切到共享函数(不在本任务范围)。
- market_tier_history.json(market_tier_history,queries.py:760)是 hs300 全史四档,8 宽基无对应全史独立产物(但 index-all.json tiers 就是全史,够了)。

## 附录:证据点索引

- 8 宽基四档计算:app/queries.py:605(_ai_macro_build_market_state)/ 667(_ai_macro_classify_tiers)/ 699(cyb)/ 715(index_tiers)/ 2082-2112(index_detail 注入,名单 2087)
- summary.json market_state:app/compute/market_summary.py:81(_market_state_of)/ 579(generate_summary 输出)
- 首页 chip:static-site/app.js:12186(_renderMarketStateChip)/ 12241(renderSummaryChips push)/ 15211(banner 挂载)/ 15108(renderOverview)
- 前端色带:app.js:8770(_TIER_COLORS)/ 8780(_indexChartPrepare)/ 10107(大盘 tab 指数卡)/ 10547-10600(详情弹窗)
- cyb 过滤键:app.js:3493-3494 / common.js:711(tierCybIn 熊市·主跌/下降期)
- 产物导出:static-site/export.py:1375(index-{id}-all.json)/ 756(overview 必更白名单)/ 1004(overview 导出)/ 1194(summary.json)
- market_tier_all 语义:scripts/signal_kelly_backtest.py:1561-1563
- 生产快照:https://ss.fx8.store/r2/index/{hs300,cyb,kc50,csi500,sz50,csi1000,sh,sz}-all.json 末条(20260924)+ https://ss.fx8.store/data/summary.json market_state(20260924)
- 数据可得性(云上 sentiment.db,只读):8 指数 MIN(date)/COUNT/MAX(date) 均见报告第二节表 + 附录:hs300 20020104/6000行/20260924、kc50 20200102/1633行/20260924、csi1000 20141017/2906行/20260924(全部满足 MA200 ≥200 交易日)

---

## 九、小结精简版 chip(色点阵)—— 新增核查(2026-09-24 用户拍板形态)

用户定形态:小结里加一枚「色点阵 + 结论词」chip,与独立卡片并行;全同档出「一致·档位」,分化时点名最强/最弱;点击跳独立卡片。以下 4 点已核:

### 9.1 并列最强/最弱规则(建议,纯数据派生不自相矛盾)

- 档位序(强→弱):牛市·主升 > 上升期 > 下降期 > 熊市·主跌。
- 规则:
  - 8 指数仅 1 档(全同档)→ 出「一致·<档位名>」,不点名(同档点名自相矛盾)。
  - 最高档集合 |Smax|==1 且最低档集合 |Smin|==1 → 点名「<指数>主升 / <指数>主跌」。
  - |Smax|>1 或 |Smin|>1 → 用计数「N个<档位名>」(如「3个主升 / 4个主跌」),**不硬挑一个**(挑固定顺序第一个会造成"同档为什么点它不点它"的困惑)。
  - 边界(如 4 上升期 + 4 下降期)→ 「4个上升期 / 4个下降期」,自洽。
- 该规则只依赖档位数据本身,不引入任何未定义分组(§23.13 安全)。

### 9.2 色点阵固定顺序建议(显示惯例,非大小盘分类)

- **代码无既有大小盘分组**(上轮已核:全仓 grep「大盘股/小盘股」无定义)→ **UI 文案禁止出现「大盘/小盘」字样**,顺序只作显示惯例。
- 建议顺序(按市值从大盘蓝筹→小盘/成长,且与既有"8 A 股指数"集合先例同源):
  `hs300 → sz50 → sh → sz → csi500 → csi1000 → cyb → kc50`(沪深300/上证50 超大盘蓝筹 → 上证/深证全市场 → 中证500 中盘 → 中证1000 小盘 → 创业板/科创成长)。
- 依据:position.py POSITION_INDICES(app/compute/position.py:17)= [sh,sz,hs300,sz50,csi500,csi1000,cyb,kc50] 是"8 个 A 股指数"唯一既有集合先例(大盘位置感卡在用),微调把 hs300/sz50 提前以贴合"核心宽基在前";前端 _INDEX_NAME_MAP(app.js:1293)已有 8 指数中文名可直接映射。

### 9.3 宽度预算实测(2026-09-24,Playwright 无痕 320×800,线上首页实测)

- chips 容器(320px 视口)= **268px**;现有「沪深300 · 熊市·主跌」chip = 132px;现状 7 个 chip 总宽 842px(flex-wrap 本就多行)。
- 注入实测(色点 10px 圆点 + 2px margin,14px/点 ×8):
  - A 一致版「四档 ▮×8 一致·上升期」= **228px ✓ 单行放下(余 40px)**
  - B 分化点名版「四档 ▮×8 沪深300主升 / 创业板指主跌」= **318px ✗ 溢出 50px**
  - C 去前缀一致版 = **200px ✓**
  - D 去前缀分化版(用户示意同款,去「四档」)= **282px ✗ 仍溢出 14px**
- **320px 窄屏结论:分化点名版必须压缩**,推荐组合:
  a) 去掉「四档」前缀;b) 色点 10px→8px(总宽 112→80px,省 32px);c) 档名单字(主升/上升/下降/主跌,用户示意本就用单字)。
  → 分化版 ≈ **245px 单行放下(余 ~23px)**,一致版 ≈ 200px。
- 备选:接受 flex-wrap 换行(现状已多行),282px 仅溢出 14px 视觉可容忍;或 D 版保留但色点缩 8px 即达标。

### 9.4 数据共用(一次请求两处渲染)

- 小结 chip 与独立卡片**共用同一份 overview.json 新字段 `index_tiers`**:首页 boot.json 已合并 overview(renderOverview L15116),小结 chip 渲染在 _summaryP.then(banner,15211)处即可读 `_bootData.overview.index_tiers`;独立卡片读 `r.index_tiers`。**零额外请求,同一数据源两视图同值,§22 一致性天然成立**。
- 现有小结 chip(沪深300 market_state)数据源是 summary.json;新色点阵 chip 读 overview.json —— 两枚 chip 并存,各自语义(沪深300 详细 tooltip 卡 vs 8 指数速览)不冲突。

## 十、第二轮补充:真实快照(2026-09-24,两张视图共用)

| 指数 | 档位 | 色点(按建议顺序) |
|---|---|---|
| 沪深300 | 熊市·主跌 | ▮ 绿 |
| 上证50 | 熊市·主跌 | ▮ 绿 |
| 上证指数 | 下降期 | ▮ 浅绿 |
| 深证成指 | 熊市·主跌 | ▮ 绿 |
| 中证500 | 熊市·主跌 | ▮ 绿 |
| 中证1000 | 下降期 | ▮ 浅绿 |
| 创业板指 | 熊市·主跌 | ▮ 绿 |
| 科创50 | 上升期 | ▮ 橙 |

- 色点阵 = ▮▮▮▮▮▮▮▮ 绿绿绿浅绿绿绿浅绿橙(杂色=分化);8 指数跨 3 档。
- 结论词(按 9.1 规则):最高档集合=科创50(上升期,1 个),最低档集合=5 个熊市·主跌 → **「科创50上升 / 5个熊市·主跌」**(点名最强+计数最弱,不自相矛盾)。
- 小结 chip 文案(压缩后,≈245px):`▮▮▮▮▮▮▮▮ 科创50上升/5个熊市·主跌`。

## 十一、第二轮补充:诚实标注

- 9.3 实测基于线上首页现状(.summary-chips 容器宽度与现有 7 chip 布局),新 chip 若放 summary-chips 同一容器,flex-wrap 会按现状多行排列,单行 245px 版本在最窄 320px 可单行放(实测);390/430px 更宽(如需要可加测,推断宽松)。
- 色点 8px 建议未实测(10px 实测基础上按比例估算 112→80px),实施时用 8px 圆点再验一次 320px。
- chip 点击跳独立卡片:移动端可点目标建议 min-height 28px + 全 chip 区域可点(现有 summary-chip 高约 24px,非 44px 口径);若严格按 mobile-a11y「可点≥44px」,需给 chip 加 padding 或接受略小目标,此点请用户/主控定夺(装饰色点类既有口径可豁免)。
