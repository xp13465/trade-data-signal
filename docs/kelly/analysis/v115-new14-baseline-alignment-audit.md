# v1.1.5 NEW14 基座对齐残留普查(main 588450cc3)

日期:2026-08-24 | 角色:researcher(只读扫描),主控落档 | 触发:用户拍板「邮件白名单 8 键=错误,反思根因+全站扫残留」(2026-08-24)

## 一、结论先行

- **行为级残留 2 处,都在 `scripts/check_signals.py` 邮件/飞书链路**:①L585 `AI_MACRO_KEYS` 白名单仍锁旧八键;②L596 `AI_MACRO_KEY_CN` 中文名映射缺 NEW14 的 10 个生产键(修了①还会英文键名裸奔)。
- **new15 分支(ed7814bae)零修复**:其 diff 全是 X1 新增(check_signals 只在 BACKUP_CN 加了 X1 中文名一行),上表残留 main 与 new15 共同存在,不能算成"分支已顺手处理"。
- **前端三消费点已对齐**:common.js 预设表 new14 keys 与 mine24 权威逐位一致;app.js 首页/监控卡、lab.js 凯利区回退全部引用 `_KELLY_FADE_DEFAULT_MODE` 单源。
- **数据面实证影响真实存在**:overview 注入层已在打新键命中(n1NorthOutflow 94 条/declinePhaseSpecial 47/r2bSpecialGlobal 31/p1LowDivBackup 26/t1LowTurnSpecial 8…),邮件白名单把这些命中**全部静默过滤**。
- **机检盲区确认**:现有 6 个校验脚本没有一个校验「默认档键集跨端一致」;最接近的 audit_bug_patterns D2 只对账 20 新键映射三处全等,不含 check_signals 两张表、不含默认档。

## 二、残留清单表

| # | 位置 | 现状 | 应为 | 影响 | new15 已修? |
|---|---|---|---|---|---|
| R1 | `scripts/check_signals.py:585` AI_MACRO_KEYS | 旧八键 set(n2Nov/exclSpecialBear/janMidRating/janMid/k2c5/r7May/exclAuxCross/greedy15),3 处消费(L711 候选过滤/L751 徽标过滤/L1975 日志统计) | 跟随当前默认档=new14 十四键生产键 | NEW14 命中信号邮件/飞书不标「AI降亏·建议回避」,且进 AI 建议 top-K 候选可被推「AI建议N」,首页同信号却灰显删除线 → §22 跨端不一致;反向 p8 对照档用户也被锁死在 v1.1.2 口径 | 否 |
| R2 | `scripts/check_signals.py:596-604` AI_MACRO_KEY_CN(+L590 BACKUP_CN) | 仅 10 键中文名;NEW14 的 r10May6NonMay/k3ConceptBuy/n1/t1/d1/q1/h1/m1/p1/r2b 共 10 键缺失;且 declinePhaseSpecial 是 NEW14 hist6 成员却登记在「备选」表 | 覆盖当前默认档全部键(L781 缺失回退裸奔英文键名) | 即使修 R1,徽标缘由也会显示英文原始键名;§23.10 邮件飞书一致性打折 | 否 |
| R3 | `README.md:101`(sim 弹窗段) | 「模式下拉:8键默认/9键/…」 | 「NEW14 默认(默认)/8键对照…」 | 用户按 README 操作认知错位(sim 弹窗实际默认已=new14,见 app.js L3482/L3622) | 否(diff 未触及该句) |
| R4 | `app/queries.py:494-517` 模块注释 + `_AI_MACRO_TOGGLE_NAMES` | 注释仍说「首页删除线=命中 8 键之一」「=8键+1类=9(v1.1.0)」「首页开关=tds_kelly_filters.aiMacro」;_AI_MACRO_TOGGLE_NAMES 全仓无消费点(死代码) | 注释改 new14 口径;死表删或标注废弃 | 误导下一个改这里的人(grep 锚点会先读到错误口径);无行为影响 | 否 |
| R5 | `static-site/app.js:2611/2629/2729/4610/4614/5445` 注释群 | 「固定 8 键白名单」「ai_macro.filters(8键)」「首页判定仍走固定 8 键」等 v1.1.5 前注释未清 | 同步 new14 口径(行为已迁 preset,仅注释滞后) | 同 R4,认知污染型 | 否 |
| R6 | `scripts/overfit_monitor.py:443-444` 注释 | 「默认 p8 走现有 bank 数字不变,仅非 p8 模式走组集」——T3-2 时点写的,现在默认已是 new14 | 改为「默认 new14 走组集;p8 对照走 filtered bank」 | 无行为影响(RECENT_KEYS L441 实际含 NEW14 全部键,组集数据齐);纯注释过时 | 否 |
| R7 | `static-site/purpose-notes.js:30`(「默认开=8键(主键四档)」句) | 夹在旧八键时代表述段中,缺「v1.1.4 及以前」限定词(前后文都有时代标注,仅此句裸奔) | 补时代限定词 | 低危,易误读为当前主口径 | 否 |

**合法对照档提及(不算残留)**:common.js 预设表 p8/9键/a9/b9/c9 条目及 calWarn 标注、lab.js 「vs9键边际」数字口径、purpose-notes/README 的 v1.1.5 变更记录段与「8键(旧默认·对照)」回选描述——这些是对照档语境合法存在。

## 三、键集登记点全量表(18 处)

| 位置 | 形式 | 当前值 | 对齐? |
|---|---|---|---|
| docs/kelly/analysis/scripts/sim_window_loss_mining_20260822/data/mine24_compare.json `new_keys` | 权威键集(挖掘代号×14) | hist6+规则8 | 权威源 |
| scripts/loss_rules.py:126 `MINING_TO_PROD_KEY` / :149 `NEW_KEYS_PROD` | 映射单源+全量20键 | 20 键(设计=全量打标,非默认档层) | ✓不适用 |
| static-site/common.js:736-756 `_KELLY_FADE_MODE_PRESETS` | 7 模式 keys | new14 keys 与权威逐位一致(已核 14 键) | ✓ |
| static-site/common.js:757 `_KELLY_FADE_DEFAULT_MODE` | 默认档单源 | "new14" | ✓ |
| app.js:2671 `_readHomeFadeMode` 回退 | 默认档消费 | 引用单源 | ✓ |
| app.js:2100 `_readOverfitFadeMode` 回退 | 同上 | 引用单源 | ✓ |
| app.js:2612 `_AI_MACRO_FILTER_NAMES` | 中文名映射+兜底白名单 | 旧8键表保留;preset 不可用(老缓存 common.js)时回退遍历它=旧口径兜底(app.js:4330-4334) | ⚠已知边界,兜底路径仍8键 |
| app.js:2624 `_AI_MACRO_BACKUP_NAMES` | 备选+新键中文名 | 已含 20 新键中文名 | ✓ |
| lab.js:8769/9463/10096 回退 | 默认档消费 | 引用单源 | ✓ |
| lab.js:7267-7283 默认勾选迁移 + :8767 老用户 members 覆盖 | 冷启动防滞留八键 | 有覆盖逻辑 | ✓ |
| **check_signals.py:585 AI_MACRO_KEYS** | 白名单 set | **旧八键** | ✗R1 |
| **check_signals.py:596 KEY_CN / :590 BACKUP_CN** | 徽标中文名 | 缺10键 | ✗R2 |
| queries.py:494-517 注释+_AI_MACRO_TOGGLE_NAMES | 注释+死表 | 过时/无消费 | ✗R4 |
| queries.py `_ai_macro_hit_filters`/`_ai_macro_hit_new_keys` | 行为=无条件注入全部命中键 | 含新键 | ✓设计如此 |
| overfit_monitor.py:441 `RECENT_KEYS` | recent 打标键集合 | 26 键 ⊇ NEW14 | ✓(:443 注释过时=R6) |
| gen_kelly_loss_features.py | 规格快照全量 | 20 键遍历 RULE_SPECS | ✓不适用 |
| check_data_integrity.py:967-984 | 校验 meta.rules 键数=20 | 规格完整性 | ✓不校验默认档 |
| audit_bug_patterns.py(bug-pattern-audit-20260823/)D2 | 20 新键映射三处全等(common T1/app/lab) | main 复跑 PASS | 部分(盲区见下) |

## 四、机检盲区确认(逐个查过)

现有链内校验各管一段,**无一覆盖「默认档键集跨端一致」**:
- `check_loss_rules_vs_mining.py`:谓词/特征/阈值 vs 挖掘权威(三层),不管消费端白名单;
- `check_fade_predicate_parity.mjs`:lab/app 重放谓词迁移回归,不管 check_signals;
- `check_overfit_recent_parity.mjs` 断言 H:7 模式 keys ∪ bullstop ⊆ RECENT_KEYS——**唯一的预设↔后端键集断言**,但只管 overfit recent 块;
- `check_data_integrity.py`:kelly_loss_features.json 存在性+20 键规格;
- `audit_bug_patterns.py` D2:20 新键映射字面量三处全等(不含 check_signals 两张表、不含默认档 id、不含 preset↔mine24 权威比对;D2 用 `txt.find('"n2NorthOutConcept", "n2nout"')` 文本锚定,新增键时锚点脆弱);
- `check_universe_alignment.py`:管 _bt_in_universe 宇宙对称,不管降亏键。

## 五、根因分析

**① reviewer 三方比对为何漏邮件链路**:v1.1.5 切换的实施面=common/lab/app 三前端文件+queries/overfit_monitor 打标层;reviewer 回归口径是「改动文件±其直接消费方」,check_signals.py 是 overview 的下游广播消费者且本次 diff 零触碰,不在改动清单里就不会被打开。而它的键集常量是 v1.1.2 时代抄的一份独立副本(v1.1.2 时它与前端白名单同源,此后前端迁 preset 单源、它原地冻结)。§22 的「N 展示位一致」在实践中被操作成「数据产物+缓存」三步同步,代码内键集常量从未被当作一致性对象盘点过——这是第 2 次同构病灶(audit_bug_patterns D1 的 FIELD 21列 vs TRADE_FIELDS 24列就是同类:同一事实在两处各存一份字面量,漂移无人盯)。

**② 登记点分布**:见第三节表,共 18 处,其中真正的「独立副本风险点」=check_signals 两张表(R1/R2)+app.js 兜底白名单;其余要么单源引用、要么全量层不涉及默认档。

**③ 规范缺口定位**:
- §22 措辞「N 文件+N 缓存同步」没把**代码内常量登记点**列为同步对象 → 本该拦住的第一道;
- §5.4⑥ 发版联动清单=「基准定义+前端默认值+公示+README」,缺「后端消费端白名单/键集常量」项 → check_signals 正是这个漏网项;
- §23.6 管 _bt_in_universe 的 1:1 遵从,「AI降亏键集跟随默认档」不在其 5 项验收里;
- §21 公示管文案不管行为常量。四条都差半步,合起来就是盲区。

**④ 防再犯机检建议**(新增 `scripts/check_fade_keys_alignment.py`,参照 check_universe_alignment.py 纯读产物+源码文本抽取模式,挂 deploy/check_data_integrity 同链,FAIL 阻断):
1. 权威比对:mine24_compare.json new_keys → loss_rules.MINING_TO_PROD_KEY 映射 == common.js new14 preset keys(正则抽 preset 块),逐位相等;
2. 白名单比对:`AI_MACRO_KEYS`(ast 解析或正则抽 set 字面量)⊇ 当前默认档生产键集(允许超集以容 p8 兼容期,最终目标=相等);
3. 徽标映射覆盖:`AI_MACRO_KEY_CN ∪ AI_MACRO_BACKUP_CN` ⊇ 默认档生产键全集(防英文裸奔);
4. 默认档单源:common.js `_KELLY_FADE_DEFAULT_MODE` 值唯一,grep app/lab 无硬编码 `"p8"` 兜底字面量(D2 式文本扫描);
5. 复用 ov-parity 断言 H 结论或直接内联 RECENT_KEYS ⊇ 默认档键集;
6. 把 D2 的文本锚定改为符号名切片(防新增键时锚点失效)。

## 六、复现

```bash
# 权威键集
python3 -c "import json;print(json.load(open('docs/kelly/analysis/scripts/sim_window_loss_mining_20260822/data/mine24_compare.json'))['new_keys'])"
# 映射单源+默认档
sed -n '126,152p' scripts/loss_rules.py; sed -n '742,757p' static-site/common.js
# 残留 R1/R2
sed -n '578,604p' scripts/check_signals.py
# 注入层新键命中实况(数据面证据)
python3 -c "import json,collections;d=json.load(open('static-site/data/overview.json'));c=collections.Counter(k for s in d['signals_today'] for k in (s.get('ai_macro') or {}).get('filters') or []);[print(k,v) for k,v in c.most_common()]"
# new15 分支未修佐证
git diff main...feat/new15-tier-none -- scripts/check_signals.py   # 仅 BACKUP_CN 加 X1 一行
# 现有 D2 机检现状(PASS 但范围不含 check_signals)
python3 scripts/bug-pattern-audit-20260823/audit_bug_patterns.py
```

数据截止:main 588450cc3 工作区(2026-08-24);关键口径:v1.1.5 标准=默认基座 NEW14(hist6+规则8),p8 为可手选对照档。
