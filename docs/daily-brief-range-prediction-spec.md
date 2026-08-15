# AI 预测「方向+区间双命中」改造规格(2026-08-15 用户定)

> 本文件是 AI 预测(daily_brief)从「方向三态含糊预测」改为「方向+幅度区间双必填、区间命中」的**唯一实施规格**。实施/验收以此为准。用户原话背景见下。

## 背景:用户为什么砍
用户(2026-08-15)强烈不满:AI 预测只给 direction: up/down/flat 三态、无幅度区间,命中判定可圆回来(±0.5% 容忍带下 flat 预测涨跌都判命中=耍流氓/算命大师)。要求:
- "即然要预测出明确方向,还要给一个预测范围,比如涨0.1?0.2个点,方向必须固定,范围也可以微调,但是必须明确给出"
- "你给一堆长篇大论和多角色辩论,但是最简单最直接的方向和幅度数值都不给,导致判断命中逻辑也像黑盒"
- "如果范围过大或者预测不准 或者瞎扯淡。我要这个功能干嘛 直接砍了。反正前4天的使用体验非常不好。现在就是生死存亡的压测"

## 用户拍板的口径(AskUserQuestion 2026-08-15)
- **命中判定 = 区间命中**(用户选):预测给区间(如涨0.5~1.5%),实际涨跌幅**落进区间**才算命中;方向由区间体现(全正=涨/全负=跌/含0=平),不另设阈值。
- **区间约束 = 数值自由但宽度≤0.5%**(用户选,原话):"数值自由些。但约束区间范围 只能更小不能更大 最大不能超过0.5。比如1.5-3 这种不行。要么1.5-2 要么2.5-3。如果能1.5-1.6。或2.8-2.9 这样是最好的。区间范围越小才是真本事" → **硬约束 `hi - lo ≤ 0.5`**,越窄越好。
- **方向优先级 + flat 收紧(2026-08-15 用户补充,关键)**:用户原话"方向最优先要么正要么负。正常平盘0是很少见的 如果你要预测震荡。那么幅度范围最多只能0.2。比如+—0.1%。综合就是0.2。你可以缩小 才得更准 不能扩大了 要么直接给整和负"。**→ ① direction 优先给 up/down(正/负),flat(震荡)是少见情况不得偷懒 ② 若给 flat,区间宽度必须 ≤0.2(如 ±0.1%),不能宽于 0.2 ③ 正/负方向区间宽度可到 0.5(仍≤0.5 硬上限) ④ 区间越窄越好**。
- **板块区间 = 大盘+板块双命中**(用户选):除大盘指数区间,还预测领涨/领跌板块次日涨跌幅区间,次日用申万行业指数实际涨跌验证,大盘+板块全部区间命中才算整体命中。

## 核心一句话
**预测必须给「方向(由区间体现)+ 具体幅度区间」,区间宽度≤0.5%,命中=实际涨跌幅落进区间(大盘+板块双区间全中)。不再有"拿不准就 flat 不硬猜"的逃避通道。**

## 输出结构(新增字段)
```json
{
  "direction": "up|down|flat",          // 由区间推导,与区间一致;禁止"拿不准就flat"
  "range": {"lo": 0.5, "hi": 1.5},      // 大盘(上证指数)次日涨跌幅区间(%),必填,hi-lo≤0.5
  "sector_ranges": [                     // 板块区间,必填(1-3个)
    {"name": "中证1000", "lo": 1.0, "hi": 1.5}   // name 必须 ∈ 注入数据的行业/指数白名单
  ],
  "confidence": 60,                      // 沿用
  "confidence_reason": "1句把握度理由",  // 沿用
  "watch_list": [...], "risk_items": [...], "highlights": [...], "text": {...}  // 沿用
}
```

## 命中判定规则(唯一权威)
- **大盘命中**:次日上证 `sh` 实际涨跌幅 `pct ∈ [range.lo, range.hi]` → 大盘区间命中。
- **板块命中**:每个 sector_range 对应申万行业/指数次日实际涨跌幅 `∈ [lo, hi]` → 该板块命中;所有预测板块全中才算板块层命中。
- **整体命中** = 大盘区间命中 AND 板块层命中(用户要"大盘+板块双命中")。
- direction 由区间推导:lo>0→up, hi<0→down, 否则 flat(区间跨0含0→flat,但此时区间必须在±0.5内)。
- **老条目兼容**:历史条目(无 range)区间命中标 `N/A`(不算中不算不中),只保留方向命中;新口径只对新条目生效,不伪造历史。

## 改动点(按文件)
### A. scripts/gen_daily_brief.py
- **prompt 改造**(build_prompt sys_text ~L613-650 + 主编版 L965-1025 + 角色版):删"拿不准就 flat 不硬猜方向";新增 range/sector_ranges JSON schema;强指令:必须给区间、方向必须明确、区间宽度≤0.5%、板块名必须∈注入白名单。
- **解析**(parse_ai_output ~L720-800):解析 range/sector_ranges;硬校验 lo≤hi、hi-lo≤0.5、lo/hi 合理范围(如 -5~5 内);缺 range → 整条降级标注(不静默 flat 化);direction 由区间推导并校验一致。
- **命中判定**(backfill_hits L1135-1175 + reclassify_all_hits L1178-1197 + _actual_direction L1125-1132):改为区间命中;加载 sh + 板块指数次日 pct;hit 结构加 `range_hit`/`sector_hits`。
- **数据锚定**(load_data ~L275-278):industry_heatmap_top 附 sw_ id,作板块名白名单。
- **历史重算**:老条目无 range → 区间命中 N/A;新口径只对新条目生效。
- **版本/规则版/最小版/mock**:补 range 字段。
- **run_log + notify 邮件/飞书**:加 range 展示。

### B. static-site/app.js(AI 预测卡片展示 ~L20827-21051)
- `_dbDirLabel`:方向徽标后追加区间展示(如"预计 +0.5~1.5%")。
- `_dbHitHtml`:命中徽标升级:✅方向+区间 / 仅方向 / ❌未中 / 区间N/A。
- `_dbActualHtml`:次日上证 X% 旁加预测区间对比。
- `_dbBriefDetailHtml`:详情加大盘区间 + 板块区间区块。
- `_renderDailyBriefStats`:**删 L21049 旧的"±0.5%容忍带"公示**,改写区间双命中新口径;命中率加区间命中率维度。

### C. purpose-notes.js / 公示(§21)
- AI 预测相关说明同步区间双命中口径(若 purpose-notes 有 daily_brief 说明段)。

## 验收口径
1. prompt 含区间强指令(无"拿不准就flat")
2. 输出 JSON 含 range + sector_ranges,宽度≤0.5
3. 命中=区间命中(大盘+板块双命中)
4. 前端展示区间 + 区间命中徽标,删旧容忍带公示
5. 历史老条目区间命中 N/A,不伪造
6. 生成 1 条新预测自验(手动跑 gen_daily_brief.py 或 --test 模式)
7. §21/§22 公示同步
8. README 若提及 AI 预测口径,同步更新
9. commit+push+§0 验 3 查(代码链/数据层/前端展示层)

## 相关记忆
- memory daily-brief-deepseek.md(deepseek 用法)
- memory reply-colloquial-chinese.md(用户要求口语化,但这是实施规格,可书面)

---

# 三、三层命中扩展: 中间层 7 个全押(2026-08-15 用户/主控拍板,本规格追加)

> 在原「大盘+板块」两层基础上扩为**三层: 大盘(上证)+ 中间层(7个全押)+ 板块(申万行业)**。
> 中间层 = 6 个宽基指数(涨跌幅%)+ 10年国债(收益率变化基点)。**整体命中 = 大盘 AND 中间层(7全中) AND 板块**。

## 中间层数据源表(唯一事实源)
| name | type | index_id / 数据源 | 预测口径 | 次日验证 |
|---|---|---|---|---|
| 深证成指 | index | `sz` | index_daily `pct_change`,涨跌幅% | 次日 pct ∈ [lo,hi] |
| 创业板指 | index | `cyb` | index_daily `pct_change`,涨跌幅% | 次日 pct ∈ [lo,hi] |
| 科创50 | index | `kc50` | index_daily `pct_change`,涨跌幅% | 次日 pct ∈ [lo,hi] |
| 北证50 | index | `bj50` | index_daily `pct_change`,涨跌幅% | 次日 pct ∈ [lo,hi] |
| 恒生指数 | index | `hsi` | index_daily `pct_change`,涨跌幅% | 次日 pct ∈ [lo,hi] |
| 恒生科技 | index | `hstech` | index_daily `pct_change`,涨跌幅% | 次日 pct ∈ [lo,hi] |
| 10年国债 | yield | `cn10y`(daily_metric `cn10y`) | **次日收益率变化基点**(1基点=0.01%) | (次日 cn10y − 当日 cn10y)×100 ∈ [lo,hi] |

- 7 个全在 `data/sentiment.db`;6 宽基在 `index_daily`(最新 `20260814`),10年国债在 `daily_metric`(`cn10y`,`20260814`=1.6964,前一日 1.7032)。
- **10年国债用收益率形态**: 预测**次日收益率变化基点区间**(如 +1~-1),命中 = 次日收益率 − 当日收益率(×100)→ 落在区间。**不是涨跌幅%**。
- 基点口径: **基点是次日收益率 − 当日收益率**;生成日周五(预测下周一)取下一交易日的 cn10y。

## 输出结构补充(index_ranges 字段)
```json
{
  "index_ranges": [               // 中间层7个全押,必填全部7个;缺任意1个 → 中间层不完整(degrade)
    {"name": "深证成指", "lo": 0.5, "hi": 1.0, "type": "index", "index_id": "sz"},   // 涨跌幅%,宽度≤0.5、|·|≤5
    {"name": "10年国债", "lo": 1, "hi": -1, "type": "yield", "index_id": null},       // 收益率变化基点,±带,宽度≤3、|·|≤3
    // ... 其余 5 个宽基同格式
  ]
}
```
- name 必须 ∈ 中间层白名单(7个);前6 `type=index`(宽度≤0.5、|·|≤5),第7个 `type=yield`(宽度≤3bp、|lo/hi|≤3)。
- `lo/hi` 若 lo>hi(±带如 +1~-1)解析时**归一化为 lo≤hi**(即 -1~+1),命中用 min≤val≤max。
- **缺任意一个白名单项 → 中间层不完整**:整条 `degrade`(middle_hits=None,不硬判不算不中),不静默只给部分。

## 命中判定(三层,唯一权威)
- **中间层命中**: 6 宽基次日 `pct ∈ [lo,hi]` 各自命中 + 10年国债 基点 ∈ [lo,hi] 命中;**7 个全中才 middle_hit=true**;任一 N/A → middle_hit=None(不硬判,不伪造)。
- **整体命中** = 大盘区间命中 AND 中间层(7全中) AND 板块层(全中);任一层 N/A → 整体 None(标"层级N/A")。
- direction(向后兼容字段)= 新区间条目时代表"整体三层命中"。

## 改动点补充(中间层条目)
### A. scripts/gen_daily_brief.py
- `MIDDLE_INDEX_MAP`(name→type)+ `MIDDLE_NAME_TO_ID`(name→index_id)+ `MIDDLE_NAMES`;`_parse_index_ranges`(仿 `_parse_sector_ranges`,白名单+按 type 宽度校验+±带归一化)。
- `load_data`: 注入 `middle_indices`(6宽基当日 pct)+ `cn10y`(当日收益率)。
- `build_prompt`/`build_editor_messages`: JSON schema 加 `index_ranges`;强指令必须输出全部7个中间层;user 消息加"中间层白名单" + "中间层当日数据"。
- `backfill_hits`: 加载 6 宽基次日 pct map + `_load_cn10y_map`;新增 `middle_hits` 逐指数验证;整体 `direction = range_hit AND middle_hit AND board_hit`(任一层 N/A → None)。
- `reclassify_all_hits`: 从已落盘 `middle_hits` 重算 `middle_hit`(不重新查库)。
- 版本/规则版/最小版/mock: 补 `index_ranges`(mock 给满 7 个,规则/最小版空数组)。
- `run_log`(index_count)+ `notify`(邮件/飞书"中间层7个全押"展示)。

### B. static-site/app.js
- `_dbBriefDetailHtml`: 加大盘区间后、板块区间前插 **indexBlock**(中间层7押区块);type=yield 展示"收益率变化 +1~-1bp",不套涨跌幅%。
- `_dbHitHtml`: 三层命中徽标;老条目(无 index_ranges)中间层 N/A 不报错。
- `_dbActualHtml`: 实际对比加中间层 7 押中几摘要。
- `_renderDailyBriefStats`: 公示说明改三层口径。
- 举一反三: `_dbBriefDetailHtml`/`_dbHitHtml`/`_dbActualHtml` 被首页今日概览(aiBlock ~L20707)与 AI 预测弹窗历史列表(~L21038)共用,改一处两处生效;老条目(无 index_ranges)显示非空/不报错已验证。

### C. 公示(§21)/README
- `_renderDailyBriefStats` 公示文本已改三层口径;首页 AI 预测按钮 tooltip 保持通用文案。
- README「AI 预测」段同步三层命中表述。

## 验收补充(三层)
1. 中间层 7 全押 + 三层命中公式正确。
2. cn10y 收益率变化基点口径正确(次日 cn10y − 当日 cn10y)×100,周五跨周末取下一交易日。
3. 老条目(无 index_ranges)中间层 N/A 不伪造、不算不命中。
4. mock/test 模式输出结构验证过(7 个 index_ranges 含 cn10y yield 基点)。
5. 版本串同 commit bump(§24);线上三查过。
