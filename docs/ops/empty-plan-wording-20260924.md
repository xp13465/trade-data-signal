# 「空计划」文案说清楚 —— 空因枚举展示实施报告(2026-09-24)

> 拍板(2026-09-24 用户):**不配**(不许动入样宇宙规则、不许 cgb_10y_etf 进可交易宇宙),但**把空计划文案说清楚** —— 用户看到空计划时知道**为什么空**。
> 本任务纯展示层 + 生成器元信息,不碰宇宙/评分/回测。上游根因:docs/ops/nextday-plan-empty-rootcause-20260924.md。

## 0. 结论摘要

- 后端生成器在空计划时写 `empty_reason`(枚举)+ 可选 `empty_detail`(细分)到 `nextday_plan.json`;前端 + 邮件读该字段展示人话原因,不再「前端/邮件硬编码猜一句」。
- 三种空因枚举(值域定稿,写进产物与本次报告):
  - `no_buy_signal` **当日没有任何买入信号**(BUY_SIGNALS 空)
  - `not_in_universe` **有买入信号但全部未入样**(无跟踪 ETF track_score;含被 AI 降亏过滤/双校验剔除等最终 kept 为空的细分)
  - `no_next_trading_day` **无下一交易日**(如假期前/交易日历末端)
  - `empty_detail` 细分:未入样宇宙 N 个 / 无匹配 top1 标的 N 个 / 被 AI 降亏过滤剔除 N 个 / 停牌/伪跳空剔除 N 个。
- 判定优先级:**no_next_trading_day > no_buy_signal > not_in_universe**(结构性原因优先)。
- 旧产物(无 `empty_reason`)前端优雅回退旧文案「当日无计划(空)」,不报错不显示 undefined。

## 1. 改动方案(7 级阶梯:复用现有过滤器、不动宇宙规则)

1. `scripts/nextday_plan_generator.py` `_build_plan_for_day` 加 `diag=None` 可选参数,**不改变返回结构**,在函数内回填空计划判定素材(buy_signals/not_in_universe/no_top1/fade_cut/blocked/no_next_trading_day)。快照回填调用点(L966 附近)不传 diag,零影响。
2. 新增纯函数 `_infer_empty_reason(diag)`(枚举判定)+ `_build_empty_detail(diag)`(人话细分)+ 常量 `_EMPTY_REASON_CN`(三种中文文案)。
3. 主链写盘空分支(L1004-1014)写 `empty_reason`(+ `empty_detail`),日志打「空计划原因」。
4. 邮件 body(L1240-1246)读 `empty_reason`/`empty_detail` 给准确原因(subject 保留「(空)」;飞书 notify.py 复用同一 subject/body,内容一致 §23.10)。
5. 前端 `static-site/lab.js` 主表提醒视图三处:新增 `_atEmptyReasonText(planDoc)` 读字段转人话,空组行内展示原因,旧产物回退。

硬约束遵守:未碰 build_board_etf_map.py / config/universe_rules.yaml / queries.py 入样逻辑;未让 cgb_10y_etf 进计划;未撞 `nextday_gap_check.py:142`(空计划跳过);自测全部写 /tmp,未覆盖生产 `data/nextday_plan.json`,未跑 `nextday_plan.sh` 真链路。

## 2. 逐处改动(文件:行号 + 前后文案)

### 2.1 后端 scripts/nextday_plan_generator.py

| 位置 | 改动 |
|---|---|
| L48 docstring | 产物结构补注空计划字段:`{date, empty:true, empty_reason: no_buy_signal\|not_in_universe\|no_next_trading_day, empty_detail?: 细分说明}` |
| L663-680 `_build_plan_for_day` 签名+docstring | 加 `diag=None` 可选参数;diag 非 None 时初始化 `{buy_signals,not_in_universe,no_top1,fade_cut,blocked,no_next_trading_day}` |
| L694-709 买信号循环 | 逐类计数:`buy_signals`(过 BUY_SIGNALS)/ `not_in_universe`(未入样)/ `no_top1`(无 top1 分数)/ `fade_cut`(AI 降亏过滤) |
| L732-733 无下一交易日 | `buy_date is None` → `diag["no_next_trading_day"] = True`(判定 `_next_trading_day` 结果,不改判定本身) |
| L777-788 双校验 | 停牌(prev_close<=0)/ 伪跳空(|gap|>20%)剔除 → `diag["blocked"] += 1` |
| L807-838 新增辅助 | `_EMPTY_REASON_CN` 三种中文文案 + `_infer_empty_reason`(优先级 无下一交易日>无买信号>未入样)+ `_build_empty_detail`(人话细分) |
| L1004-1014 主链写盘空分支 | 原:`plan_doc["empty"] = True` → 新:写 `empty = True` + `empty_reason = _infer_empty_reason(_diag)`(+ 有细分时写 `empty_detail`),日志打「空计划原因」 |
| L1240-1246 邮件 body | 原:`body = "明日无买入计划(无信号或 T 日非交易日)。"` → 新:`body = f"明日无买入计划。<br>原因: 信号日 {T} {_EMPTY_REASON_CN[...]}"`(+ 有 empty_detail 时追加 `<br>细分: {detail}`) |

主链 L972-973 调用处:`_diag = {}` + `plan = _build_plan_for_day(..., diag=_diag)`(改动,已含在上表)。

### 2.2 前端 static-site/lab.js

| 位置(最终行号) | 改动 |
|---|---|
| L14762-14782 新增 `_atEmptyReasonText(planDoc)` | 读 `doc.empty_reason` 转人话:`no_buy_signal`→「无任何买入信号,按规则不出买入计划」;`not_in_universe`→「有买入信号但均无可跟踪的 ETF 标的(不入可交易宇宙),按规则不出买入计划」;`no_next_trading_day`→「之后无下一交易日(如假期前),按规则不出买入计划」;前置「信号日 {date}」+ 附 empty_detail;旧产物/未知枚举/非空计划一律返回 `""`(**回退关键**) |
| L14885-14886 `_atRender` | `const t0EmptyReason / t1EmptyReason = _atEmptyReasonText(planDoc)`(仅当该组为空时使用) |
| L14895/14909 `_atRender` groups 注入 | T0/T1 group 加 `emptyReason: r0Empty/r1Empty ? ... : ""` |
| L14795-14798 `_atRemindGroupHtml` 空行 | 原:`当日无计划(空)` → 新:`当日无计划 · {reason}`(有 reason 时);无 reason(旧产物)保持 `当日无计划(空)` 原样 |
| L14192-14195 顶部文档注释 | 数据结构注释补空计划 `empty_reason`/`empty_detail` 字段与回退语义 |

label(「🟢 今日 · 无计划」/「🟢 最近交易日 · 无计划」/「🔜 下一交易日 · 无计划」)保持简洁,原因在组内空行完整展示(信号日日期 + 原因 + 细分),用户一眼能读到「为什么空」。

## 3. §21 算法公示核查

本改动**不是算法改动**(未动 track_score/评分/权重/匹配规则/入样宇宙),不触发 §21。已核前端涉「实操步骤」的公示文案:
- lab.js L14191 数据源注释:「纯读展示, 不重算算法, §21 公示」——已顺带更新注释含新字段,无需改公示正文。
- lab.js L14909 sub 文案:「提醒视图 · 最近交易日+下一交易日 · …(读 nextday_plan + auto_trade_steps, 纯展示不重算算法)」——与本改动一致,**无涉及需改**。

## 4. §23.3 举一反三清单(「无计划 / (空)」全站展示位遍历)

| # | 展示位/消费点 | 是否渲染「无计划/(空)」 | 覆盖结果 |
|---|---|---|---|
| 1 | lab.js 主表提醒视图 L14795-14798「当日无计划(空)」行 | 是(用户点名) | **已改** 加 empty_reason 人话原因 |
| 2 | lab.js 主表 T0 label L14895「🟢 今日/最近交易日 · 无计划」 | 是(用户点名) | 已核:label 保持简洁,原因在组内空行展示(同日期可见) |
| 3 | lab.js 主表 T1 label「🔜 下一交易日 · 无计划」 | 是(用户点名) | 已核:同上(空行展示同一信号日原因) |
| 4 | lab.js「查看全部计划」弹窗(主表外) | 否:基于 plan+steps 历史明细,空计划日本身无行,弹窗不渲染空日 | **无需改**(非空计划提示位) |
| 5 | lab.js L14891/L14893 兜底文案(整个视图无数据) | 极端兜底(序列空/两组都空),非空计划日语义 | **无需改** |
| 6 | app.js 首页 | grep 无「无计划」渲染;L2612 是信号冻结快照(不同功能) | **无需改** |
| 7 | common.js | grep 无「无计划」 | **无需改** |
| 8 | 邮件 notify(生成器 L1240-1246) | subject「明日买入计划 {T}(空)」+ body 原笼统文案 | **已改** body 读 empty_reason 给准确原因 |
| 9 | 飞书通知 | notify.py 复用同一 subject/body(§23.10 内容一致) | 自动一致,**无需改** |
| 10 | nextday_gap_check.py:142 | 空计划跳过日志 | **不改**(任务明确别改它,已确认) |
| 11 | check_data_integrity.py check_nextday_plan | 只校验 date 合法 + 结构 {date, plan[]\|empty:true} | **无需改**(新增字段被忽略,已读代码确认 L1944-2003) |
| 12 | check_r2_consistency.py / gen_schedule_stats.py | 调度/一致性登记,无渲染文案 | **无需改** |

同类错误面(§23.2 精神):所有读 nextday_plan.json 的展示位 = `_atPlanRows`(读 plan 数组)/ `_atRender` / `_atAllModalRender` / `_atBuildDays`,空 plan 时均不渲染行,不受 empty_reason 影响;唯一写盘点和唯一邮件点都在生成器主链,均已在根因点修改(一处守卫,不逐调用点打补丁)。

## 5. 三种原因自测证据(§23.2②)

### 5.1 纯函数判定自测(/tmp/test_empty_reason.py,14 断言 ALL-PASS)
- 无下一交易日(优先级最高):diag `{buy_signals:1, no_next_trading_day:True}` → `no_next_trading_day` PASS
- 当日无买信号:diag `{buy_signals:0}` → `no_buy_signal` PASS
- 有买信号全未入样:diag `{buy_signals:2, not_in_universe:2}` → `not_in_universe` PASS
- 有买信号被降亏全剔:diag `{buy_signals:1, fade_cut:1}` → `not_in_universe`(大类) PASS
- 空 diag / None → `""` 回退 PASS
- empty_detail 细分(单类/多类/空):逐字断言 PASS

### 5.2 端到端真实主链(--dry-run,只读 DB 不落盘)
`REPO=trade-data python scripts/nextday_plan_generator.py --date 20260924 --dry-run`:
```
[nextday_plan] T=20260924 signal_daily 信号(排除 s.*)=0
[nextday_plan] 空计划原因: empty_reason=no_buy_signal empty_detail=(无)
[nextday_plan] DRY-RUN: 不落盘不 R2 不通知
  "date": "20260924", "today": "20260924", "is_trading_day": true,
  "next_trading_day": "20260928", "empty": true, "empty_reason": "no_buy_signal"
```
**产物结构完整,PASS**;dry-run 零落盘(PASS)。

### 5.3 前端同构对账自测(/tmp/test_empty_reason.js,8 断言 ALL-PASS)
node + vm 从 lab.js **真实提取** `_atEmptyReasonText` 函数体(非同构副本),输入三种空因产物逐字断言文案:
- `no_next_trading_day` 产物 → 「信号日 20260923 之后无下一交易日(如假期前),按规则不出买入计划」PASS
- `no_buy_signal` 产物 → 「信号日 20260924 无任何买入信号,按规则不出买入计划」PASS
- `not_in_universe` + empty_detail 产物 → 「信号日 20260923 有买入信号但均无可跟踪的 ETF 标的(不入可交易宇宙),按规则不出买入计划;未入样宇宙(无跟踪 ETF) 2 个」PASS

### 5.4 语法
`python3 -m py_compile scripts/nextday_plan_generator.py` OK;`node --check static-site/lab.js` OK。

## 6. 旧产物回退自测

线上现存旧产物 `{"date":"20260923","empty":true}`(无 empty_reason)——前端 `_atEmptyReasonText`:
- 旧产物(empty=true 无 empty_reason)→ `""` → 空行回退「当日无计划(空)」**PASS**
- 非空计划(plan 存在)→ `""` 不误标 **PASS**
- null / 非对象 / 未知枚举(未来新原因)→ `""` 不报错不显示 undefined **PASS**
三组断言见 /tmp/test_empty_reason.js 用例 4-7 ALL-PASS。

## 7. base commit + 版本串

- base commit(开工基于 origin/main HEAD):`c3d4a83a7` docs(ops): 落档 9-24 两份调研报告
- 改动前版本串:`20260924-a614`(lab.min.js?/app.min.js?/sw.js CACHE_VERSION `v6-20260924-a614` 同源)
- **本 agent 未自行 bump 版本串**(§24 机制 C),版本串统一由主控 merge 走 main-merge.sh 重建 min+bump。
- 本次改动文件:`scripts/nextday_plan_generator.py`(后端生成器)+ `static-site/lab.js`(前端源码)+ 本报告。
---

## 8. 修订段(reviewer Finding-1 文案修正,2026-09-24 二次实施)

### 8.1 问题(reviewer 判定 must-fix,置信~85)
原 `not_in_universe` 文案「当日有买入信号但均无可跟踪的 ETF 标的(不入可交易宇宙)」**语义错误**:
当有买信号但全部被 **AI 降亏过滤剔除(fade_cut)** 或 **停牌/伪跳空剔除(blocked)** 时,这些信号**有**跟踪 ETF、也**入了样**,只是被其他过滤剔除——
headline 说"不入可交易宇宙"与 detail「被 AI 降亏过滤剔除 3 个」**自相矛盾**(用户铁律:文案说错原因比不说更糟)。
实测复现:`reason: not_in_universe | headline: 当日有买入信号但均无可跟踪的 ETF 标的(不入可交易宇宙), 按规则不出买入计划 | detail: 被 AI 降亏过滤剔除 3 个`。

### 8.2 改法(纯文案,2 处字符串;diff 仅此 2 行)
| 文件 | 位置 | 改动 |
|---|---|---|
| scripts/nextday_plan_generator.py | `_EMPTY_REASON_CN["not_in_universe"]`(L810) | 「当日有买入信号但均未进入买入计划(未入样/被过滤/被剔除), 按规则不出买入计划」 |
| static-site/lab.js | `_atEmptyReasonText`(L14770) | 「有买入信号但均未进入买入计划(未入样/被过滤/被剔除), 按规则不出买入计划」(同后端去掉「当日」,逐字一致) |

**未动**:`_infer_empty_reason` 枚举值/优先级(无下一交易日>无买信号>未入样)、`_build_empty_detail` 数值口径、宇宙规则/queries.py/build_board_etf_map.py、不 bump 版本串不 build_min(机制 C)。

### 8.3 修复链标注(旧文案保留可反查)
- 旧文案「当日有买入信号但均无可跟踪的 ETF 标的(不入可交易宇宙)」在 git 历史 `d6547fe50` 的父版本(commit `5560ce452` 及 rebase 后 `d6547fe50` 上一版)可 `git show <旧commit>:scripts/nextday_plan_generator.py` 反查。
- 本次修订 commit:`<见下方 git log>`(baseline `d6547fe50` 之上追加)。

### 8.4 同类错误面清单(§23.2③ 全部 empty_reason 展示位,逐项确认改后一致)
| # | 展示位 | 位置 | 消费方式 | 改后结果 |
|---|---|---|---|---|
| 1 | 后端邮件正文 body | scripts/nextday_plan_generator.py L1223-1228 | 读 `_EMPTY_REASON_CN.get(plan_doc.empty_reason)` 同源字典 | 自动跟随新文案,无硬编码,PASS |
| 2 | 前端组空行(提醒视图唯一真实渲染点) | static-site/lab.js L14796-14798 | `g.emptyReason`(来自 `_atEmptyReasonText`) | 新文案渲染,PASS |
| 3 | 前端 T0 空计划 label | lab.js L14885/L14895 | `_atEmptyReasonText(planDoc)` | 经同一函数,自动跟随,PASS |
| 4 | 前端 T1 空计划 label | lab.js L14886/L14909 | `_atEmptyReasonText(planDoc)` | 经同一函数,自动跟随,PASS |
- 独立 grep 确认**无第 4 处**渲染点:`grep -rn "empty_reason\|_atEmptyReasonText" lab.js/app.js/common.js` 仅以上;「查看全部计划」弹窗(_atAllModalRender)与 common.js/app.js 无 empty_reason 渲染位;`grep "无可跟踪的 ETF 标的\|不入可交易宇宙"` 全前端源码零残留。
- 邮件与飞书同 body(notify.py,§23.10),一处 body 双通道一致。

### 8.5 §21 算法公示检查
`grep -n "无可跟踪\|不入可交易宇宙" static-site/purpose-notes.js` 无结果;本次为**纯原因文案**修改,不涉及算法/数值/匹配规则,purpose-notes.js + app.js/lab.js 算法公示点未触及。**已 grep,无涉及**。

### 8.6 自验逐项结果(全部 PASS)
| # | 项目 | 结果 |
|---|---|---|
| 1 | 三因枚举全跑:no_next_trading_day / no_buy_signal / not_in_universe 各造输入 | 均输出正确 headline(见下方输出) |
| 2 | 复现 case:有买信号但全被 fade_cut 剔除(3 个) | headline「均未进入买入计划(未入样/被过滤/被剔除)」+ detail「被 AI 降亏过滤剔除 3 个」**不再自相矛盾** |
| 3 | blocked 剔除同类 | headline 同上 + detail「停牌/伪跳空剔除 1 个」一致 |
| 4 | 旧产物兼容 `{"date":"20260923","empty":true}` 无 empty_reason | 前端 `_atEmptyReasonText` 返回 `""` → 回退「当日无计划(空)」不报错 |
| 5 | 前后端文案逐字一致(去「当日」后同一句) | `python` 断言 PASS(含空格逐字一致) |
| 6 | 语法 | `py_compile` OK + `node --check lab.js` OK |

自验输出摘录:
```
=== 自验2(复现 case) ===
reason=not_in_universe
headline: 当日有买入信号但均未进入买入计划(未入样/被过滤/被剔除), 按规则不出买入计划
detail  : 被 AI 降亏过滤剔除 3 个
自相矛盾? 无(不再矛盾)
=== 自验5(逐字一致) ===
后端去当日: 有买入信号但均未进入买入计划(未入样/被过滤/被剔除), 按规则不出买入计划
前端句    : 有买入信号但均未进入买入计划(未入样/被过滤/被剔除), 按规则不出买入计划
逐字一致? PASS
```
