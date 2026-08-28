# v1.1.0 K2C5 上线审查(补齐后在线复审)

> 审查日期:2026-08-15(周五) 23:0x 左右;审查人:reviewer agent(独立只读,不改代码不推 main)
> 审查对象:`feat/k2c5-v110` 分支 v1.1.0 上线前审查(commit 2cf4093f1 收口后状态)
> 基准:v1.1.0 = **9 规则 = 8 键 + 1 类** = AI宏 5+3+1 =
> 基础5[n2NovSpecialIndustry/excludeSpecialBear/janMidRating/janMidSpecial/**k2c5HkChase**] + 核心3[r7MayReinforced/excludeAuxCross/greedy15] + 1类回测剔除(债类/波段不入宇宙 `_bt_in_universe`)
> 前置审计:`docs/kelly/analysis/kelly-v110-nine-rule-audit.md`(补齐前,发现 overview.json 漏标 K2C5 等缺口)

## 0. 结论

**PASS(有条件)**:代码层 + 数据产物层已全部对齐 v1.1.0 九规则,上轮核心缺口(overview.json 漏标 k2c5)已重跑修复,check 全 PASS,版本串/一致性/公示全部到位。4 个 P2 级问题(1 个过度标注 + 1 个展示文案不一致 + 1 处注释残留 + 1 项部署待办)不阻塞上线,建议下一迭代收口。

**上线动作**:merge `feat/k2c5-v110` → main → `bash scripts/deploy.sh` 推 a266 前端 + 数据(线上前端现仍为 a260,未部署)→ 部署后验三站。

---

## 1. 上轮审计缺口修复确认(对照 kelly-v110-nine-rule-audit.md)

| 上轮缺口 | 本轮状态 | 证据 |
|---|---|---|
| overview.json 漏标 k2c5(17 条港股买信号 filters 为空) | **已修复(2cf4093f1 数据补标)** | overview.json 现 17 条命中 `k2c5HkChase`,5 入样(hsi/hscei)+12 未入样(hk_cesg10 等);本地 vs 线上主站同值 |
| common.js「4+3+1/7键」文案 4 处 | **已修复** | `grep -c "4+3+1\|7键\|7 键" static-site/common.js` = 0 |
| purpose-notes.js「与降亏同开仅推荐默认组合」列举漏 K2C5 | **已修复** | purpose-notes.js @7929 段:「5+3+1=8键+1类, 5=基础5: n2NovSpecialIndustry/excludeSpecialBear/janMidRating/janMidSpecial + K2C5 港股追涨剔除」 |
| K2C5 未纳入 AI宏总开关联动/持久化 | **已修复(2cf4093f1)** | `_kellyPersistMemberKeys`(lab.js L8714-8718)含 k2c5HkChase;`_kellyAiMacroMembers`(L8730)= persist 派生 → 总开关 8 键联动 + localStorage 持久化 8 键 |

## 2. 8 项审查逐项结果

### 2.1 后端 queries.py(K2C5 谓词 / _bt_in_universe / hk_industry)
- K2C5 谓词:`app/queries.py` L637-641 `_sig in ("buy_special","buy_backup") and _mkt in ("mkt_hk","mkt_hk_industry")` → 追加 k2c5HkChase。**⚠ 发现过度标注问题(见 §3 P2-1)**
- `_bt_in_universe` 注入:queries.py L856 `any(track_score is not None ...)`,等价回测 _build_best_etf(§23.6 1:1 合规)
- ai_macro 注入:queries.py L1034-1035 每条信号注入 `ai_macro:{hit,filters}`
- **结论:功能正确,判定范围偏宽(见 P2-1)**

### 2.2 前端 lab.js 联动一致性(AI宏总开关+K2C5 / 持久化 / 双开关矛盾)
- 默认 filters:lab.js L7282 `k2c5HkChase: true, k3ConceptBuy: false`
- 全月掩码:L7374 `k2c5HkChase: 0x1FFF`
- K2C5 谓词:L7521 `filters.k2c5HkChase && (_sig3==="buy_special"||_sig3==="buy_backup") && _mktD3==="hk"` —— **判 `_mktD3==="hk"`,只匹配 `mkt_hk` 象限(实际仅 hsi/hscei/hstech)**
- 持久化 + 总开关联动:L8714-8730 8 成员全含 k2c5 → 三态/badge 由 8 键派生 ✓
- **结论:前端内部自洽;与后端判定范围不一致(见 P2-1)**

### 2.3 §22 数据一致性(overview / 首页删除线 / lab 默认组合 / 回测入样)
- overview.json:本地 vs 线上主站 ss.fx8.store **完全相同**(date=20260814,signals_today=197,k2c5 hit=17,collected_at=20260815 21:30:36)
- trades.json:本地 vs 线上相同(mkt_hk A=326,generated_at=2026-08-15 21:41)
- 回测象限:signal_kelly_trades.json quadrants keys 只有 `mkt_hk`(无 `mkt_hk_industry`),内含 index_id = {hsi,hscei,hstech}(回测 MARKET_QUAD_MAP L127-130 把 hk/hk_industry 都并 mkt_hk,但 hk_industry 信号未入样无 trade)
- **结论:数据三处一致 ✓;唯一语义差异见 P2-1(首页标未入样 hk_industry 为 AI降亏)**

### 2.4 §21 公示同步(5+3+1/8键/v1.1.0)
- lab.js L9019 aiMacroLabelHTML:5+3+1/基础5/8键+1类 大段 tooltip ✓
- lab.js L8862 K2C5 toggle tip:5+3+1 定义+穷举报告链接+诚实标注 G 双口径 ✓
- purpose-notes.js @7929/@8158:5+3+1=8键+1类 ✓
- common.js/app.js:0 处 4+3+1/7键 残留 ✓
- **结论:公示已对齐 5+3+1;K2C5 的 G 模式 b0/b1 口径分裂已诚实标注 ✓**

### 2.5 §24 版本串(index.html ?v= 与 sw.js CACHE_VERSION)
- index.html 16 处 `?v=20260815-a266`;sw.js `CACHE_VERSION = 'v6-20260815-a266'` —— 全站一致 ✓
- min 文件:app.min.js/lab.min.js 含 `k2c5HkChase`;common.min.js 含 5+3+1 ✓
- JS 语法:app.js/lab.js/common.js/purpose-notes.js 4 文件 node --check 全 OK ✓
- **⚠ 线上前端仍是 a260(a266 未部署)→ merge 后必须 deploy.sh**

### 2.6 §23.6 宇宙规则(check_universe_alignment.py)
- `python3 scripts/check_universe_alignment.py` → **4 断言全 PASS**(197 信号 _bt_in_universe 一致/候选⊆白名单/177,096 笔交易无排除类别/排除类别正确)
- config/universe_rules.yaml:buy_whitelist/excluded_categories 声明完整
- **结论:PASS**

### 2.7 §15 回归风险(改坏老功能 vs 预期变更)
- **预期变更**(v1.1.0 设计,非回归):首页 hsi/hscei buy_special 现标「AI降亏」删除线(K2C5 默认开);凯利区默认滤港股宽基 buy_special/buy_backup;AI宏总开关文案 4+3+1→5+3+1;基础4+核心3 老键行为不变
- **无意外破坏**:回测数据层未动(全宇宙);trades/backtest 未重跑=兼容;老 toggle 谓词未改
- **结论:无意外破坏**

### 2.8 数据产物本地 vs 线上同步
- overview/trades 本地=线上主站 ✓;备站 sss/s.sugas 需 deploy 后复核(上轮 D 项,部署后 curl 验)

---

## 3. 问题清单(全部 P2,不阻塞上线)

### P2-1 后端 K2C5 过度标注未入样 hk_industry 信号(queries.py L640)
- **现象**:overview 17 条 k2c5 命中中,12 条是未入样 hk_industry 信号(hk_cesg10/hk_cshkdiv/hk_cshklc/hk_hscci/hk_hsmbi/hk_hsmogi),首页标「AI降亏(港股追涨剔除)」而非「未入样本」
- **根因**:queries.py L637-641 判 `_mkt in ("mkt_hk","mkt_hk_industry")` 两值。实现者注释前提「回测 MARKET_QUAD_MAP 把 hk_industry 并 mkt_hk → 回测侧命中 K2C5」**有误**:回测确实把 market in (hk,hk_industry) 并 mkt_hk 象限,但 hk_industry 信号从未入样(§23.6 排除类别,board_etf_map 无 key 无 track_score),故 signal_kelly_trades.json 的 mkt_hk 象限只有 {hsi,hscei,hstech},**回测侧根本无 hk_industry trade 可被 K2C5 过滤**。后端判两值=over-flag(防漏标意图导致过度标注)
- **影响**:①12 条未入样信号从「未入样本」标注变「AI降亏」,语义不准确(它们并非"被 K2C5 过滤",而是从未入样)②与凯利区 K2C5 实际过滤范围(hsi/hscei/hstech)不一致 ③AI建议 top-K 不受影响(有 `_bt_in_universe !== false` 守卫 app.js L2396-2401)④删除线+灰显两种标注共有,决策影响趋同
- **修复方向**(下一迭代):queries.py L640 只判 `_mkt in ("mkt_hk",)`,与 lab.js L7521 `_mktD3==="hk"` 对齐,重跑 export → hk_industry 信号回到「未入样本」标注。同时修该处误导性注释

### P2-2 默认推荐高亮区文案「高亮8键含K2C5」vs 实际只有 7 键(lab.js L8956)
- recZoneHTML 标题(L8956)「高亮8键=基础5+核心3(含K2C5港股追涨)」,但 `_kellyRecFlags`(rec:true)只含 7 键(K2C5 无 rec:true,L8861 只有 warn),K2C5 在市场组独立 toggle(折叠区)
- 有注释说明是有意设计(L8951「高亮区不重渲染它,它在市场组独立toggle」),但用户视觉数与文案对不上
- **修复方向**:文案改「高亮7键+市场组K2C5」或把 K2C5 渲染进高亮区(二选一,需用户确认布局偏好)

### P2-3 注释残留「7键/4+3+1」(lab.js 纯注释,无功能影响)
- L8728/L8915/L8919/L9011/L9024/L9137/L9140/L9145/L9565/L9574 等历史注释仍写 7 键;L9652 是历史报告快照不改
- 不影响任何判定/渲染,顺手清理即可

### P2-4 线上前端仍为 a260(a266 未部署)— 上线必做
- merge + `bash scripts/deploy.sh` 推 a266 前端 + overview/trades 数据;部署后 curl 验 index `?v=20260815-a266` + overview.json k2c5 hit=17 + 备站 sss/s.sugas 非 0 信号

---

## 4. 回归区分总结

| 类型 | 项 | 判定 |
|---|---|---|
| 预期行为变更(v1.1.0 设计) | 首页 hsi/hscei buy_special 标 AI降亏删除线;凯利区默认滤港股宽基追涨;文案 4+3+1→5+3+1 | 合规 |
| 数据层兼容 | trades/backtest 未重跑,回测全宇宙数据不变,前端实时过滤 | 合规 |
| 老键兼容 | 基础4+核心3 谓词未改,行为不变 | 合规 |
| 意外破坏 | 无 | 通过 |

---

## 复现

- **复现「overview 17 条 k2c5 命中含 12 条未入样 hk_industry」**:
  ```
  python3 -c "
  import json
  d=json.load(open('static-site/data/overview.json'))
  k2=[s for s in d.get('signals_today',[]) if 'k2c5HkChase' in s.get('ai_macro',{}).get('filters',[])]
  uni=[s for s in k2 if s.get('_bt_in_universe')==True]
  print(len(k2), len(uni), sorted(set(s['index_id'] for s in k2 if s not in uni)))
  # 输出: 17 5 [hk_cesg10,hk_cshkdiv,hk_cshklc,hk_hscci,hk_hsmbi,hk_hsmogi]
  "
  ```
- **复现「mkt_hk 象限只有 hsi/hscei/hstech」**:
  ```
  python3 -c "
  import json
  td=json.load(open('static-site/data/signal_kelly_trades.json'))
  q=td['quadrants']['mkt_hk']; fidx={k:i for i,k in enumerate(td['fields'])}
  ids=set()
  for mode,arr in q.items():
      for t in arr: ids.add(t[fidx['index_id']])
  print(sorted(ids))  # ['hscei','hsi','hstech']
  "
  ```
- **复现「check_universe_alignment PASS」**:`python3 scripts/check_universe_alignment.py`(4 断言全 PASS)
- **复现「版本串一致」**:`grep -c "v=20260815-a266" static-site/index.html`(=16)+ `grep CACHE_VERSION static-site/sw.js`(v6-20260815-a266)
- **数据版本**:overview.json `collected_at=20260815 21:30:36`(signals_today 197);trades.json `generated_at=2026-08-15 21:41`;分支 feat/k2c5-v110 最新 commit 2cf4093f1
- **审查基线**:v1.1.0 基准 = AI宏 5+3+1 = 8键+1类(§5.4 测试基准锚点)
