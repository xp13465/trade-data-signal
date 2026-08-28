# v1.1.0 九规则全站审计:AI降亏/入样/推荐/过滤模块 7 vs 9 核对

> 审计日期:2026-08-15(周五) 22:40 左右;审计人:reviewer agent(独立审计,纯只读,不改代码不推 main)
> 基准:v1.1.0 推荐最优组合 = **9 规则 = 8 键 + 1 类** = AI宏 5+3+1 =
> 基础5[n2NovSpecialIndustry/excludeSpecialBear/janMidRating/janMidSpecial/**k2c5HkChase**] + 核心3[r7MayReinforced/excludeAuxCross/greedy15] + 1类回测剔除(债类/波段不入宇宙 `_bt_in_universe`)
> 对比对象:v1.0.0 = 7 规则 = 基础4+核心3(无 K2C5,无样本外剔除显式计入)
> 审计时分支:`feat/k2c5-v110`(5 个未 push main commit,最新 fee7a21d0「首页AI降亏删除线命中判定对齐v1.1.0基准(8键+1类=9)」)

## 0. 审计结论一句话

**代码层(queries.py/app.js/lab.js)已全部对齐 9 规则(8键+1类),无缺键;但数据产物 `static-site/data/overview.json`(本地+线上主站 ss.fx8.store 均同)仍按补齐前旧代码生成,17 条港股 buy_special/buy_backup 信号漏标 `k2c5HkChase`,需重跑 export 才对齐——这是唯一核心缺口,属「补齐后未重跑数据产物」,非代码缺口。**

另 2 处公示文案(common.js / purpose-notes.js)的「7 键/4+3+1」描述漏 K2C5,属 §22 展示层不一致(轻)。

---

## 1. 全站清单:逐模块 7/9 核对(文件:行号 + 当前落 7 还是 9 + 缺什么 + 证据)

### 1.1 后端判定层

| 模块 | 位置 | 落 7/9 | 证据 |
|---|---|---|---|
| queries.py `_ai_macro_hit_filters`(首页 AI宏命中判定) | app/queries.py L606-676 | **9(8键)** | 8 键谓词完整:k2c5HkChase 在 L634-641(`_sig in ("buy_special","buy_backup") and _mkt in ("mkt_hk","mkt_hk_industry")`);模块注释 L487-500 明确「基础5+核心3=8键,+1类剔除走 _bt_in_universe = 9(v1.1.0)」;仅买信号守卫 L610-615 |
| queries.py `_bt_in_universe` 注入 | app/queries.py L856 | **9(1类)** | `_s["_bt_in_universe"] = any(track_score is not None for etfs)`,等价回测 _build_best_etf,§23.6 1:1 |
| queries.py overview ai_macro 注入 | app/queries.py L1017-1035 | **9** | 每条信号注入 `ai_macro:{hit, filters}`,ctx 含 market_map/rating/track_score/is_bull |
| 后端 k2c5 谓词 vs 凯利区象限一致性 | queries.py L634-641 + indicators.yaml | **9** | 港股宽基 hsi/hscei/hstech→mkt_hk,港股行业 hk_*→mkt_hk_industry;lab.js mktD 读象限(hk_industry 并 hk),两处谓词等价(已验证) |

### 1.2 前端判定/展示层

| 模块 | 位置 | 落 7/9 | 证据 |
|---|---|---|---|
| app.js `_AI_MACRO_FILTER_NAMES` | static-site/app.js L1969-1978 | **9(8键)** | 含 `k2c5HkChase: "港股追涨剔除"`(L1974) |
| app.js `_isAiFadeHit`(首页降亏删线判定) | static-site/app.js L2348-2350 | **9** | 读后端注入 `it.ai_macro.filters` + `_aiOnMembers`(L2339 固定 8 键全开),不自行重算(§23.6 合规) |
| app.js 首页 AI建议 top-K 候选 | static-site/app.js L2396-2401 | **9** | `it._bt_in_universe !== false` 过滤(未入样不进 AI建议) |
| app.js 当日已满/未入样本渲染 | static-site/app.js L2494 + L2416-2419 | **9** | 当日已满判 `_bt_in_universe !== false`;未入样本 `_bt_in_universe===false`=删线+灰显+「未入样本」标注 |
| lab.js `_kellyDefaultFilters` | static-site/lab.js L7253-7290 | **9(8键)** | L7282 `k2c5HkChase: true, k3ConceptBuy: false`(K2C5 默认开) |
| lab.js K2C5 谓词(凯利区降亏过滤) | static-site/lab.js L7521 | **9** | `if (filters.k2c5HkChase && (_sig3 === "buy_special" || _sig3 === "buy_backup") && _mktD3 === "hk") return false;`(与后端等价) |
| lab.js K2C5 toggle 定义+公示 | static-site/lab.js L8860-8861 | **9** | toggle key `k2c5HkChase`、「⭐默认开(v1.1.0)」,tip 含 5+3+1/基础5/穷举报告链接 |
| lab.js AI宏总开关公示 | static-site/lab.js L9018 | **9** | 「AI宏5+3+1(2026-08-15 定名基础5)…K2C5 港股追涨并入基础5」 |
| lab.js AI仓位建议 tooltip | static-site/lab.js L9028 | **9** | 「AI宏5+3+1: 基础5=基础4+K2C5 港股追涨, 加核心3; +1=回测剔除」 |
| lab.js 默认组合公示 | static-site/lab.js L9754 | **9** | 「AI宏5+3+1=基础5+核心3+1类, 5=基础5键降亏推荐=基础4+K2C5 港股追涨剔除」 |

### 1.3 数据产物层

| 产物 | 位置 | 落 7/9 | 证据 |
|---|---|---|---|
| **overview.json(核心缺口)** | static-site/data/overview.json(本地 + 线上 ss.fx8.store 同值) | **7(缺 K2C5)** | 17 条港股 buy_special/buy_backup 信号 `ai_macro.filters=[]`(应命中 k2c5HkChase);全部 filter keys 只有 excludeSpecialBear;生成时间 21:41 < queries.py 修改 22:18 → 补齐前产物,需重跑 export |
| signal_kelly_trades.json(回测交易) | static-site/data/signal_kelly_trades.json | **9(数据层天然全宇宙)** | mkt_hk 象限 2934 条含 buy_special/buy_backup 1431 条;回测数据=全宇宙,降亏 8 键是前端/查询层过滤,数据层无需重跑(前端 K2C5 键会滤这 1431 条) |
| signal_kelly_backtest.json(回测统计) | static-site/data/signal_kelly_backtest.json | **9(同左)** | 象限统计含全宇宙,降亏过滤在前端实时重算 |
| board_etf_map.json(入样映射) | data/board_etf_map.json | **9(1类剔除)** | check_universe_alignment.py assertion1/4 PASS:排除类别(债/情绪/商品/港股行业/空数组)全部正确 absent/empty_array |

### 1.4 配置/校验层

| 模块 | 位置 | 落 7/9 | 证据 |
|---|---|---|---|
| config/universe_rules.yaml | config/universe_rules.yaml | **9(1类剔除)** | 入样白名单/依赖/排除类别/自我ETF例外齐全;K2C5 是降亏键非宇宙规则,不入 yaml 合理(§23.6 只管入样宇宙) |
| check_universe_alignment.py | scripts/check_universe_alignment.py | **PASS** | 4 断言全 PASS(197 信号 _bt_in_universe 一致/候选⊆白名单/177,096 笔交易无排除类别/排除类别正确) |

### 1.5 公示文案层

| 模块 | 位置 | 落 7/9 | 证据 |
|---|---|---|---|
| purpose-notes.js 降亏过滤公示 | static-site/purpose-notes.js(降亏过滤段) | **9(基本)+1处漏** | 主体含「AI宏5+3+1=基础5+核心3…默认组合含 K2C5」✓;**但「与降亏同开仅推荐默认组合(AI降亏过滤: excludeSpecialBear/J1/J2/n2NovSpecialIndustry/r7MayReinforced/excludeAuxCross/greedy15)」列举 7 键漏 K2C5** |
| common.js 静态快照 tooltip/文案 | static-site/common.js L477(注释)/L530/L544(快照文案)/L549(tooltip) | **7(文案)** | 「AI降亏过滤默认 AI宏4+3+1」「当前降亏勾选(AI降亏过滤 7 键)」→ 应 5+3+1/8键 |

### 1.6 已排除(不构成停 7)

| 模块 | 原因 |
|---|---|
| kelly-review-notes.js / kelly-reports-content.js | 历史报告快照(3AI 对比/历史决策),7 键旧口径是报告原文,§23.5 报告不改 |
| sw.js | 缓存版本相关,无关判定 |
| lab.js 内多行「7键」注释 | 结构性描述(「高亮7键=基础4+核心3 + K2C5 独立在市场组」),非漏 K2C5,见 L8949-8959 |
| scripts/signal_kelly_backtest.py | 回测层无降亏 toggle(全宇宙),K2C5 是前端/查询层键,正确 |
| scripts/build_board_etf_map.py / overfit_monitor.py | 无 k2c5(前者管入样映射,后者管过拟合监控),不涉及降亏键 |

---

## 2. 四分类汇总

### A. 已对齐 9(8键+1类)— 12 处
queries.py 判定层(3)、app.js 判定/展示层(5)、lab.js 凯利区(5)、universe_rules.yaml、check_universe_alignment.py、purpose-notes.js 主体(见 §1.1/1.2/1.4/1.5)

### B. 仍停留 7(缺 K2C5)— 1 处核心
**overview.json 数据产物(本地+线上主站)**:17 条港股 buy_special/buy_backup 信号漏标 k2c5HkChase(§1.3)

### C. 仍停留 7(缺样本外剔除)— 0 处
样本外剔除(1类,`_bt_in_universe`)全站已对齐:queries.py L856 注入 + app.js 全消费点判 `_bt_in_universe` + check_universe_alignment PASS + universe_rules.yaml 声明完整。**无缺。**

### D. 无法判定(需补齐后看)— 1 处
线上备站 **sss.sugas.site**(curl 返回 9,379 字节非 JSON,疑 CF 缓存/HTML 错误页)与 **s.sugas.site**(返回 0 信号):数据产物状态无法确认,需 deploy 后复核。

---

## 3. 「补齐后自动对齐」vs「独立缺口」标注

| 缺口 | 类型 | 说明 |
|---|---|---|
| overview.json 漏 k2c5HkChase(17 条港股买信号) | **补齐后需重跑数据产物** | implementer 已 commit 代码(fee7a21d0)但未重跑 export;queries.py 22:18 改,overview.json 21:41 生成。重跑 export(queries.py overview())后这 17 条自动命中 k2c5HkChase(已用当前代码逐条验证应命中=True)。**属 implementer 收尾必做,做完即自动对齐** |
| common.js「7 键/4+3+1」文案(4 处) | **独立缺口(补齐后仍漏)** | 纯文案,tooltip/注释写旧口径,不影响判定;需单独改文案(4+3+1→5+3+1,7 键→8 键) |
| purpose-notes.js「与降亏同开仅推荐默认组合」列举漏 K2C5 | **独立缺口(补齐后仍漏)** | 列举 7 键缺 k2c5HkChase,需补 |
| 线上备站 sss/s.sugas 数据状态 | **独立复核项** | deploy 后需 curl 复核备站 overview 是否含 k2c5 |

---

## 4. 疑似 bug/历史遗留(待用户确认)

### 4.1 K2C5 未纳入 AI宏总开关联动与持久化(lab.js,设计观察)
- 位置:static-site/lab.js L8714-8717 `_kellyPersistMemberKeys` = 仅 7 键(基础4+核心3),**不含 k2c5HkChase**;L8729 `_kellyAiMacroMembers` 同 7 键。
- 影响:
  1. **AI宏总开关**(aiMacro)勾选/取消只联动 7 键,**不联动 K2C5**(K2C5 独立在市场组 toggle,默认开不受总开关影响)。用户拍板「v1.1.0 = 9 规则 = AI宏 5+3+1」,但 UI 上「AI宏总开关」实际控制 7 键 + K2C5 独立 → 「AI宏」语义与开关范围有偏差。
  2. **K2C5 状态不持久化**:`_kellyPersistFilters`(L8732)用 7 键存 members,`k2c5HkChase` 不写入 localStorage `tds_kelly_filters`。labSigKellyFilters 是内存态(L8585 每次从 `_kellyDefaultFilters` 重建)→ 用户手动关 K2C5 后刷新页面即恢复默认开。与 7 键(持久化)行为不一致。
- 证明链路:现象=K2C5 开关状态刷新即丢 + AI宏总开关不控制 K2C5;根因=`_kellyPersistMemberKeys` 未含 k2c5HkChase + 持久化只遍历该 7 键数组;影响=用户无法持久化「关 K2C5」偏好,且「AI宏总开关」名实略偏;修复方向=把 k2c5HkChase 纳入 persist keys + 总开关联动(或明确「K2C5 独立不联动」为用户预期)。
- 状态:**待用户确认**——若「K2C5 独立默认开不受总开关联动」是用户拍板设计,则非 bug(仅持久化不一致值得修);若用户预期「AI宏总开关=9 规则全控」,则需补联动。

### 4.2 后端 price_bin 子条件在 overview 信号级降级(已知设计,非 bug)
- 位置:app/queries.py L496-500(模块注释)。
- 影响:K2C5 外,r7MayReinforced 的 (05+vlow)/(03+周二+high)、greedy15 的 step5/9/14 等含 price_bin(ETF 买入价分位)子条件,在 overview 信号级**不参与命中**(无价格字段)→ 首页 AI降亏对这些信号「漏标不误标」(保守)。凯利区交易级完整判定。
- 状态:已知设计,§22 粒度降级,已在注释诚实标注。**非本次 v1.1.0 引入,不阻塞上线**,但需知悉首页 AI降亏命中数是信号级保守口径。

---

## 5. 上线前待办(按优先级)

1. **[必须,implementer 收尾] 重跑 export 生成新 overview.json**:queries.py 已对齐,重跑后 17 条港股买信号自动标 k2c5HkChase;§22 三步同步(static-site+R2+CF)后,本地与线上主站一致。
2. **[必须] 线上备站复核**:deploy 后 curl sss.sugas.site / s.sugas.site 确认 overview 含 k2c5 且非 0 信号(§22 三站一致)。
3. **[轻] common.js 4 处文案 + purpose-notes.js 1 处列举**:4+3+1→5+3+1、7 键→8 键、补 k2c5HkChase(§21 公示同步)。
4. **[待用户确认] K2C5 是否纳入 AI宏总开关联动/持久化**(见 §4.1)。

## 复现

- **复现「overview.json 缺 k2c5 命中」**:
  ```
  python3 -c "
  import json
  d = json.load(open('static-site/data/overview.json'))
  sigs = d.get('signals_today', [])
  hk = [s for s in sigs if s.get('signal') in ('buy_special','buy_backup') and (s.get('index_id','').startswith('hk') or s.get('index_id') in ('hsi','hscei','hstech'))]
  print(len(hk), sum(1 for s in hk if 'k2c5HkChase' in s.get('ai_macro',{}).get('filters',[])))
  # 输出: 17 0(17 条港股买信号, 0 条命中 k2c5)
  "
  ```
  用当前 queries.py 代码对同批信号重算(k2c5 谓词 L634-641),17 条全部应命中=True。
- **复现「check_universe_alignment PASS(1类剔除已对齐)」**:`python3 scripts/check_universe_alignment.py`(4 断言全 PASS)
- **数据版本**:overview.json `collected_at=20260815 21:30:36`(signals_today 197);trades/backtest `generated_at=2026-08-15 21:41`;queries.py 修改 2026-08-15 22:18(fee7a21d0)
- **审计基线**:v1.1.0 基准 = AI宏 5+3+1 = 8键+1类(§5.4 测试基准锚点);代码分支 feat/k2c5-v110
