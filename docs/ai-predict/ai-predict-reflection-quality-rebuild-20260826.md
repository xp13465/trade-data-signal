# AI 预测「历史反思校准」质量重构调研报告(2026-08-26)

> 调研触发:用户批评现状反思「只记错不反思」。原话锚点:「我看到的知识说错了和错在哪了 并没有任何和反思相关的 比如漏看了什么数据 漏的数据是可以印证实际的方向。或者就是 和实际结果对的上的预测因子因为什么原因导致权重没跟上而产生偏离。这些我觉得是真正的反思并且可以有校准方案的。而不是记录了一堆错。说这是反思校准」
> 主控追加拍板(2026-08-26):**影子模式一并重构融合,不做两版并行**(原话「反正现在2个版本数据都不好 也不存在什么对比问题了。还是先融合起来做出一版有用的以后。再考虑做对比来看看哪版本更好了」)。本报告方案框架按融合版给出。
> 只读调研,未改任何代码。角色=researcher。

## 一、结论(TL;DR)

1. **用户批评完全成立,三点逐一有代码级证据**:①注入文本就是错账罗列(`date:type(summary)` 拼接);②"因子归因"是 4 条硬编码 if-else 模板且线上默认关(从未生效过);③全程无"漏数据归因"维度——反思只看预测自己引用过的依据(risk_items),从不检查库里存在、能印证实际方向、但没进预测视野/没被采纳的数据。
2. **比"漏数据"更高频的病灶是"权重压制"**:失败样本里大量属于"利空证据全部在场(risk_items 引用了)、模型自己也写了'净空压制',但方向仍判反"。0821 是铁证(§二.4)。真反思必须同时覆盖 漏数据(missed_data)/权重压制(weight_suppressed)/因子失灵(factor_failed) 三类。
3. **影子模式机制是好骨架,直接升级为融合底座**:`record_shadow` 按日落因子 → `aggregate_shadow` 次日回填+分组聚算,把这张表从"只记方向锚 7 个字段"扩成"每日一行完整对账底稿"(预测侧+因子侧+实际侧+引用审计),反思生成从底稿读,旧 reflections 错账通道退役。
4. **deepseek 能产出归因+校准,前提是喂结构化对账表而非自由文本**:机械层(确定性代码)先做"引用审计"产出 missed_faces 清单和因子状态表,模型层只做归因判断与校准动作生成,输出走固定 schema(白名单枚举防幻觉)。生成时点放低谷(20:40 后)不触 §5.6 高峰价。
5. 工作量约 **3 个 implementer 日**,分 Phase1 融合底座 / Phase2 反思生成升级 / Phase3 前端统一展示三批派单;动 AI 推荐 prompt 注入内容按 §5.4⑥ 需发版本标记 + §23.14 codex 外审。

## 二、现状机制(问题 1:反思现在怎么生成)

### 2.1 生成链(全在 scripts/gen_daily_brief.py,4354 行)

| 环节 | 落点 | 干什么 |
|---|---|---|
| 失败样本落盘 | `record_reflections` L3393 → `_classify_failure` L3260 | 对已回填且失败的 history 条目做规则级归因:`failure_type ∈ {direction_fail/partial/range_imprecise/direction_only}` + `error_bps` + `expected_gap_summary`(错账文字)+ `factor_attribution`;幂等,时间隔离(backfilled_via < today) |
| "因子归因" | `_attribut_factor` L3209-3257 | **硬编码 4 条 if-else 模板**:L3纳指大跌压制看多 / 转空信号被当偏空 / T1顺势看涨强规则 / T1当日失效(+partial 归板块失真)。不是模型反思,是规则匹配 |
| 注入下次预测 | `build_reflection_inject` L3516 | 按 `_strict_hit_rate`(近30日严格口径,L3436)分四档(reinforce<50%/normal/light/success≥90%,L3451):注入文本 = `【历史反思校准(加强反思)】date:direction_fail(摘要);...` + 固定语气提示(L3560-3579)。**格式=纯错账罗列** |
| 因子归因回灌 | `build_attribut_inject` L3467 | 聚合 top3 误导因子生成「待规避因子」段;受 `cfg.reflection_factor_attribution_enabled` 栅,**yaml 默认 false(L193 setdefault)→ 线上从未注入过** |
| 前端产物 | `build_reflection_meta` L3587 → 写 meta.reflection L4235 | 与注入口径同源(walk-forward),随 daily_brief.json + history 归档 |
| 前端渲染 | static-site/app.js `_dbReflectionHtml` L25705-25720 | 「🔍 含历史反思校准」块:n 次/方向误判 N 次 + samples 列表(date+type 中文标签+summary 截 120 字),L25839 接入 |

### 2.2 实际落盘验证(data/daily_brief_reflections.json,2026-08-26 读)

- 10 条样本,failure_type 分布:`direction_fail×6 / direction_only×3 / range_imprecise×1`;
- 含 factor_attribution 仅 4 条(硬编码模板命中率 40%),detail 全为模板文案;
- 线上 static-site/data/daily_brief.json 的 meta.reflection:`tier=reinforce, hit_rate=0.0, n=10, dir_fail=6`——即当前处于"及格线以下",每次注入全部 10 条错账。

### 2.3 用户批评三点对照

| 用户批评 | 证据 |
|---|---|
| "只是记录了一堆错" | build_reflection_inject L3562 `body = " ;".join(lines)`,lines 元素=`f"{d}:{ft}({summary})"`——日期+类型+错账句,无任何归因链/校准动作 |
| 没有"漏看了什么数据,漏的数据可印证实际方向" | 全链路(grep reflect/factor_attribution/miss 无命中其他)无任何"比对库里数据面 vs 预测引用面"逻辑;expected_gap_summary(L3338-3349)只拼预测自己的 risk_items 前 3 条 |
| 没有"对的上的因子为什么权重没跟上" | _attribut_factor 只有 4 条模板,且 build_attribut_inject 默认关;模板外的失败(占 60%)零归因 |

### 2.4 权重压制型失败的活案例(20260821,§23.9 1:1)

history 20260821 条目(meta.direction="up",range 0.2~0.6,次日实际 -0.59% down):
- risk_items 5 条全是利空:「中信连续8日逆向净空3019手,机构top20净空7458手」「医药生物主力净流出-153.5亿」「腾落线-133864,涨跌比0.467,宽度偏弱」「解禁4264.59亿」「南向净流出76.3亿」;
- text.trend 自己写「期货净空压制,短期或震荡偏强」——**证据全在场、压制也看见了,结论仍 up**。
- 机械粗筛:近 12 条 history 中「direction=up 且实际非 up 且 risk_items 含利空词」= 3 天。
- 结论:真反思若只做"漏数据归因"会漏掉最高频病灶,**error_type 必须含 weight_suppressed**。

## 三、可用数据盘点(问题 2:手里有哪些面)

### 3.1 已注入预测视野(load_data L816-1365,当日值)

summary(情绪/恐贪/涨跌家数/涨停跌停/信号数)/signals_today/signal_stats_buy_top/signal_ranking/public_fund_industry/futures_acc_trend_tail+latest/conclusion/inst_ih_trend(中信/top20/国泰君安席位)/ETF汪汪队三件/funds 23 metric(两融/南北向/QVIX/轮动/换手/量比/成交额MA)/scores 8 情绪分/indices 8/middle_indices+cn10y/cross_market 13 全球期货/forex_commodity(usdcnh/利差/us10y/金银油)/lhb 龙虎榜/unlock_ipo 解禁IPO/daban 打板溢价/ind_flow 行业资金流 top5bottom5/positions 估值百分位/ad_line 腾落线/ma_cross 均线/calendar_hint/news 新闻增量。

### 3.2 DB 存在但未进预测视野(漏数据候选清单,trade-data/data/sentiment.db 实测)

| 数据面 | 库内位置 | 当日值在库? | 未注入原因(代码注释) |
|---|---|---|---|
| 新高新低(a_nh_20d/a_nl_20d/a_nh_52w/a_nl_52w/a_nhnl_52w/details) | daily_metric,8712 条至 20260826 | 是 | load_data guard 注释明写「大面积0拦截(新高新低本次不注入)」(L1219 附近) |
| 概念板块日线(pct_change/net_inflow) | board_daily 表(date/board_type/board_name/pct_change/net_inflow) | 是 | load_data 完全未读该表(industry_heatmap_top 走 overview.json 申万行业) |
| 可转债(cov_count/cov_premium_median) | daily_metric,38 条 | 是 | 未列入注入清单 |
| 股息率 a_div_yield | daily_metric,5257 条 | 是(至0825) | 未列入 |
| 预估成交额 a_amount_forecast/换手中位 a_turnover_median/p10/a_turnover_rate | daily_metric | 是 | 未列入(forecast 有 hover 展示但未给 AI) |
| 行业换手率 ind_turn_sw_* | daily_metric | 停更(20260710 起) | guard 停更自动跳过(合理) |
| 盘中分时(intraday_snapshot/intraday_amount_history/signal_intraday_log) | 独立表 | 是(盘中) | 20:40 生成时点用不上盘中当日全量,历史日可回看 |
| 席位逐品种明细 futures_ih_detail_acc | 独立表 | 是 | 只注入了 futures.json 聚合版 |
| 情绪分自身历史百分位 | score_daily 全史 | 是 | 只给当日值;周期定位规则让模型引 positions 估值百分位,情绪分百分位没算给它 |

> 口径提醒(§23.13):上表是"未注入面"事实清单;"哪些值得补注入/补审计"属实施拍板项,建议 Phase1 先全量快照进底稿(成本≈0,都是站内已有),由引用审计数据说话再决定谁升格为注入面。

### 3.3 因子状态现有落盘位置

- `data/brief_shadow.json`:每日 `{date, pred_shadow(lean), strength, basis[], factors:{turns[](逐 role/variety 的 net_chg/turn_type/run), ma_bull, rate_down_channel, us10y, gold, nq_chg, nq_open_low}, actual{next_date, actual_sh_pct, actual_direction}}`;
- `static-site/data/daily_brief_history.json`:每条 meta(range/index_ranges/sector_ranges/risk_items/highlights/confidence/text 四段/direction_call/hit 回填三层);
- 两张表按 date 可 1:1 join = 底稿雏形已齐。

## 四、影子模式融合(问题 3 + 主控追加拍板)

### 4.1 影子通道现状(可复用资产)

| 组件 | 落点 | 评价 |
|---|---|---|
| record_shadow | gen_daily_brief.py L474,主流程 L4041 调用(20:40 生成前,AI 降级也照记) | 计算逻辑(_compute_direction_anchor 同源缓存)保留价值高 |
| 回填对账 | aggregate_shadow.py `_reconcile` L88-121:找下一真实交易日回填 actual,幂等,pct 未入库不硬判留待补(R1 修复) | 幂等/断档防护成熟,直接搬 |
| 分组聚算 | `_aggregate` L123-160:by_lean 分桶命中率 + basis 因子 split("×")[0] 分组 top_mislead_factors | 扩展维度即可复用 |
| 调度挂载 | run_daily_brief.sh L48-54 尾部(gen 后调 aggregate,R1 挂载);launchd 无独立槽位(launchctl list + plist grep 实证无) | 保留改参数即可 |
| md 渲染 | shadow_track_md.update_shadow_track_md(双调用点:gen L4049 附近 + aggregate main),产物 docs/ai-predict-shadow-track.md | 融合后停用或改渲染底稿 |
| 会话 durable cron d40be623 | 属主控会话 CronList 管理,launchctl 不可见(本 agent 无法查),需主控自查处置 | 见 §六处置清单 |
| 开局战绩 | brief_shadow.json 5 记录,已回填 4 条全 miss(0819 up→flat/0820 up→flat/0821 up→down/0824 up→flat)= 0/4 | 即主控说的"两版都不好",作新反思机制的首批活案例 |

### 4.2 融合设计:单一底稿表(Phase1 核心)

新产物 `data/brief_ledger.json`(JSON 数组,每日一行,与现有产物形态一致便于前端/R2 链路):

```
{
  "date": "20260821",
  "pred_side":   { // 从 history meta 搬:date+1 日由 gen 写入
    "version", "direction_call", "range", "index_ranges", "sector_ranges",
    "confidence", "confidence_reason", "risk_items", "highlights",
    "text": {review/trend/watch/risk}
  },
  "factor_side": { // record_shadow 扩展写入
    "anchor": {turns[], ma_bull, rate_down_channel, us10y, gold, nq_chg, nq_open_low},
    "shadow_lean", "shadow_basis[]",
    "extra_faces": {nhnl_20d:[nh,nl], board_top:{name:pct,net_inflow}×10,
                     cov_premium, div_yield, amount_forecast, sentiment_pctile}
                     // 未注入面当日快照,供"漏数据归因"判定用,成本≈0
  },
  "actual_side": { // 次日对账器回填(aggregate._reconcile 口径扩展)
    "next_date", "actual_sh_pct", "actual_direction",
    "middle_actuals{}", "sector_actuals[]" // backfill_hits 已算,搬运
  },
  "hit": { "direction", "range_hit", "middle_hits[]", "sector_hits[](含raw_hit/eff带)", "direction_call_hit" },
  "cite_audit": { // 引用审计(机械层,确定性代码,Phase2)
    "referenced_faces": ["ind_flow.医药生物","funds.hk_south", ...], // 预测文本锚定比对命中面
    "missed_faces": [{"face":"nhnl_20d","value":"nh=820/nl=1500","align":"印证down"}, ...]
  }
}
```

要点:
- **写入时机**:pred_side/factor_side 当日 20:40 gen 时写;actual/hit/cite_audit 次日 17:50 采集后由对账器回填(run_daily_brief.sh 已挂的尾部调用点不变);
- **时间隔离天然成立**:反思 T 的素材=T-1 及更早行(actual 已回填),沿用 backfilled_via < date 语义;
- **防前视**:extra_faces 快照只存 ≤T 收盘数据(17:50 update_all 已入库,20:40 写入合法,同 R2 板块带宽口径先例);
- **迁移**:brief_shadow.json 既有 5 条(4 回填)一次性并入 ledger,0/4 战绩如实保留当首批活案例;reflections.json 10 条失败样本按 date 反向挂接 ledger 行(它们本就来自同一 history)。

## 五、反思生成升级与 deepseek prompt 设计(问题 4)

### 5.1 两层架构(机械层管事实,模型层管归因)

**机械层(确定性 Python,不靠模型,可机检)**:
1. 引用审计:预测 text 四段+risk_items+highlights 拼接后,对各数据面的特征 token(行业名/指标名/具体数值如"-153.5")做锚定比对 → referenced_faces / missed_faces;
2. 因子对账表:_compute_direction_anchor 因子语义方向 vs 实际方向,逐因子标「同向印证/反向失效/未参与」(扩展 aggregate._aggregate 的 split("×")[0] 分组思路到逐因子逐日);
3. 近期聚合:每因子近 N=10/30 日命中率、连续误导次数(by-factor 滚动,expanding 口径防前视 §5.1⑥)。

**模型层(deepseek 二次调用,输入结构化对账表)**:

```
system: 你是预测复盘审计员。输入是某次失败预测的结构化对账底稿(预测回顾/当日因子状态/
实际方向/未引用数据面清单/各因子近期命中率)。禁止编造底稿外的数据。输出合法 JSON。

user: {
  "ledger": <上述底稿行>,
  "factor_recent": {"T1转多": {"n":12,"hit_rate":0.42,"miss_streak":3}, ...},
  "missed_faces": [...],          // 机械层产出,模型只能从中选,不得虚构
  "factor_whitelist": ["T1转多","T2/T3转空","均线多头","L3纳指大跌","南向资金",
                       "行业资金流","市场宽度","龙虎榜机构","估值位置","新闻事件",...] // 枚举防幻觉
}

输出 schema(强制):
{"reflections": [{
  "error_type": "missed_data | weight_suppressed | factor_failed | other",  // 枚举
  "factor": "<白名单内>",
  "evidence_chain": ["底稿里的具体数值→指向down", ...],     // ≥2 步,必须引底稿数值
  "calibration_action": "下次该因子出现X态时,<具体可执行动作>"
}]}
```

设计原则:
- error_type/factor 双枚举白名单,模型只做选择与串联,幻觉空间压到最小;
- evidence_chain 要求逐步引底稿数值(§23.9:1:1 举例既是教学也是自查);
- calibration_action 必须是「条件→动作」句式,能被下一轮注入直接消费(如"risk_items 利空条数≥3 且无单一强多头信号时,禁止单独依 T1 转多变 up,需区间下移一档");
- 成本:每失败样本一次 flash 档调用,量小(失败频率 ~50%),20:40 低谷时段不触 §5.6 高峰价;也可挪次日 21:00 后与回填同批跑。

### 5.2 注入替换

build_reflection_inject 的错账罗列段(`date:type(summary)` 循环)替换为:
- 上一次同型错误的 calibration_action(≤3 条,直接指令);
- 因子近期命中率表(factor_recent,模型可见自己该信谁);
- 保留:walk-forward 时间隔离/scrub 合规/优秀档不注入/REFLECTION_INJECT_ENV 总闸。

## 六、实施方案与旧通道处置(问题 5)

### 6.1 分阶段(按主控拍板,Phase1 即融合底座)

| 阶段 | 内容 | 改动文件 | 预估 |
|---|---|---|---|
| Phase1 融合底座 | brief_ledger.json 结构+双端写入(gen 扩展 record_shadow→record_ledger);对账器(aggregate_shadow 改造,CLI 兼容 --date/--json);brief_shadow/reflections 存量并迁;run_daily_brief.sh 尾部调用改造 | scripts/gen_daily_brief.py、scripts/aggregate_shadow.py(或新 brief_ledger.py)、scripts/run_daily_brief.sh、迁移脚本一份(docs/ai-predict/scripts/) | 1 个 implementer 日 |
| Phase2 反思生成升级 | 机械层引用审计+因子对账聚合;deepseek 二次调用(schema 校验失败重试1次);build_reflection_inject 替换;废弃 build_attribut_inject+yaml 开关清理 | 同上 + config/daily_brief.yaml | 1~1.5 日 |
| Phase3 前端统一展示 | meta.reflection 升级(error_type/evidence_chain/calibration_action);app.js _dbReflectionHtml 三段式渲染(§23.9 白话+场景+1:1);算法公示同步(§21);build_min+bump 走 main-merge | static-site/app.js、purpose-notes.js 公示点核查 | 0.5 日 |

验收钩子:Phase1 出报告附「底稿行 vs history/shadow 双源一致性机检」;Phase2 附「10 条存量失败样本全量重生成反思的人工抽验」;Phase3 附线上 curl 字段+min 串验证(§8 三查)。

### 6.2 旧通道处置清单(保留/停用逐项)

| 组件 | 处置 | 理由 |
|---|---|---|
| record_shadow/_compute_direction_anchor/_shadow_lean | **保留计算逻辑**,落盘目标改为 ledger(或内部复用) | 方向锚因子计算是验证过的资产(R4 对称分支刚修) |
| brief_shadow.json | 停止新写,存量并入 ledger 后文件归档保留(可逆 §5.3) | 单一底稿原则 |
| aggregate_shadow.py | 改造为 ledger 对账器(CLI 兼容),run_daily_brief.sh L53 调用点保留 | 回填/幂等逻辑成熟 |
| shadow_track_md.py + docs/ai-predict-shadow-track.md | 渲染链停用;md 若仍有观察价值改为由 ledger 渲染(实施时定),README 活文档例外清单同步 | 避免双产物漂移(§22) |
| reflections.json + _classify_failure 规则级归因 | 保留为「失败样本明细」派生产物(从 ledger 重算),错账罗列注入格式废除 | 明细仍有审计价值 |
| build_attribut_inject + reflection_factor_attribution_enabled(yaml) | 废弃删除(含 setdefault L193/L490 登记点 grep 清理) | 被真归因替代,防双机制 |
| cron d40be623(主控会话 durable) | launchctl 不可见,主控 CronList 自查:若为"每日合 main/影子对账"类则随融合调整后删除 | 本 agent 权限不可达,上报主控 |
| config/daily_brief.yaml direction_anchor_enabled/shadow_mode_enabled | 融合后合并语义(建议保留 direction_anchor 注入开关独立,shadow_mode_enabled 并入 ledger 开关) | 减少开关矩阵 |

### 6.3 风险与合规注意

- §5.4⑥:动 AI 推荐 prompt 注入内容=动核心实用功能,发版本标记(v1.1.7 编号与 bj50 剪枝撞车与否由主控定),基准 memory 同步;
- §23.14:三个 Phase 各 feat 完成 push 后必发 codex 外审;
- §23.7:本重构经用户 2026-08-26 拍板(批评原文+融合拍板),prompt 输出变化属已确认改动;
- §22:meta.reflection 结构变化,daily_brief.json/history/R2/static-site 三步同步+前端容错老条目(无新键优雅降级,现模式已具备);
- deepseek 二次调用失败不阻塞主链(同 tts 模式:失败置 null,前端降级显示机械层对账表)。

## 七、已验证方法/数据源清单

- 读码:scripts/gen_daily_brief.py(L190-200 开关/L216-330 方向锚/L392-527 影子/L816-1365 load_data/L3203-3640 反思全家/L4020-4260 主流程编排);scripts/aggregate_shadow.py 全文;scripts/shadow_track_md.py;static-site/app.js L25695-25851;
- 数据产物:data/daily_brief_reflections.json(10 样本实测)、data/brief_shadow.json(5 记录实测)、static-site/data/daily_brief.json(meta.reflection tier=reinforce hit_rate=0.0)、daily_brief_history.json(12 条,0821 逐字段核);
- DB:trade-data/data/sentiment.db(17 表/187 metric 全列,board_daily 结构实测,新高新低/可转债/股息率当日值在库确认);
- 调度:launchctl list + ~/Library/LaunchAgents plist grep(无 shadow 独立槽位实证);run_daily_brief.sh L48-54(R1 挂载点);
- 旧文档:docs/ai-predict/ai-predict-reflection-factor-attribution-20260820.md、ai-predict-four-improvements-20260824.md(R1-R4)、ai-predict-shadow-track.md。

## 复现

```bash
# ① 反思落盘结构与因子归因占比
python3 -c "
import json; d=json.load(open('/Users/linhuichen/code/trade/data/daily_brief_reflections.json'))
print(len(d['samples']), [s['failure_type'] for s in d['samples']])
print(sum(1 for s in d['samples'] if s.get('factor_attribution')))"
# ② 线上 meta.reflection
python3 -c "
import json; m=json.load(open('/Users/linhuichen/code/trade/static-site/data/daily_brief.json'))['meta']['reflection']
print(m['tier'], m['hit_rate'], m['n'])"
# ③ 影子对账(0/4 开局)
REPO=/Users/linhuichen/code/trade-data python3 scripts/aggregate_shadow.py
# ④ 未注入面在库确认
python3 - <<'EOF'
import sqlite3
c=sqlite3.connect('file:/Users/linhuichen/code/trade-data/data/sentiment.db?mode=ro',uri=True)
print(list(c.execute("SELECT metric_id,value FROM daily_metric WHERE date='20260826' AND metric_id IN ('a_nh_20d','a_nl_20d','cov_premium_median')")))
print(list(c.execute('SELECT * FROM board_daily ORDER BY date DESC LIMIT 3')))
EOF
# ⑤ 权重压制粗筛(history 12 条)
python3 -c "
import json
h=json.load(open('/Users/linhuichen/code/trade/static-site/data/daily_brief_history.json'))
items=h if isinstance(h,list) else h.get('items') or []
neg=['流出','净空','承压','偏弱','恐慌']
print(sum(1 for it in items if (it.get('meta') or {}).get('direction')=='up'
  and ((it['meta'].get('hit') or {}).get('direction') is False)
  and any(w in json.dumps(it['meta'].get('risk_items'),ensure_ascii=False) for w in neg)))"
```

数据截止:2026-08-26(sentiment.db 当日 19:15 版;brief_history 12 条至 0825)。关键口径一句话:反思现状=规则级 failure_type 错账注入(build_reflection_inject)+4 模板硬编码归因(默认关);重构=影子骨架升格为每日底稿 ledger(预测侧+因子侧+实际侧+引用审计)→ 机械审计+deepseek 归因(missed_data/weight_suppressed/factor_failed 三型+calibration_action)→ 注入与前端统一换血,旧 shadow/reflections 双通道融合为一。
