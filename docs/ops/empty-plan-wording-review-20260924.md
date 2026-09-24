# 「空计划」文案说清楚 —— reviewer 独立审查报告(2026-09-24)

> 审查对象:feat 分支 `worktree-agent-aaaa97454818dc615`,commit `5560ce452`(base `c3d4a83a7` = origin/main)
> 审查人:reviewer(独立,不信实施自验,逐项自己跑)
> 结论:**PASS-with-conditions**(1 条条件:文案措辞修正,2 行)

## 0. 结论摘要

- 核心能力(三因判定 + 旧产物回退 + 飞书/邮件一致 + 不碰宇宙 + §24 合规)全部验证通过。
- **1 条条件**:`not_in_universe` 枚举的 headline 文案在「全部买信号被 AI 降亏过滤/停牌伪跳空剔除」时与真实原因不符(报错原因),违反用户铁律「文案说错原因=比不说更糟」。修法=改 2 处文案(后端 `_EMPTY_REASON_CN` + 前端 `_atEmptyReasonText`),不动枚举/优先级。
- 另 2 个低分项(<80)已滤:前后端渲染措辞未逐字同源;`no_next_trading_day` 在交易日历陈旧时措辞可能误标(属 pre-existing,非本次引入)。

## 1. 逐项验证(任务要求 8 项)

### 1.1 三因判定准确性(本次命门)

独立提取分支版纯函数(AST 从 `/tmp/nextday_plan_generator.py` 提取真函数体,非重写副本)实测 12/12 PASS:
- `no_next_priority`:`{buy_signals:1, no_next_trading_day:True}` → `no_next_trading_day` ✓
- `no_buy_signal`:`{buy_signals:0}` → `no_buy_signal` ✓
- `not_in_universe`:`{buy_signals:2, not_in_universe:2}` → `not_in_universe` ✓
- 空/None diag → `""` 回退 ✓
- **优先级判定成立**:无下一交易日 > 无买信号 > 未入样。当「既无买信号、又无下一交易日」同时成立报 `no_next_trading_day`,是结构性优先——无下一交易日时即使有信号也不出计划,该原因对用户最有用(告诉用户"明天不开市/日历末端"),两个原因都为真,不存在报错。
- 用户真实场景(9-23 cgb_10y_etf buy_aux/buy_special 未入样)→ `not_in_universe`,headline 文案与真实原因精准匹配 ✓

**疑点(即本报告唯一条件)**:当当日有买信号(≥1)且**全部**被 AI 降亏过滤剔除(`fade_cut`)或全部停牌/伪跳空剔除(`blocked`)、未入样=0 时,`_infer_empty_reason` 返回 `not_in_universe`,headline 显示「当日有买入信号但均无可跟踪的 ETF 标的(不入可交易宇宙)」——**该句是错的**(这些信号有跟踪 ETF 且入了样,只是被其他过滤剔除)。empty_detail 会补「被 AI 降亏过滤剔除 N 个」,但 headline 与 detail 自相矛盾。完整实测输出见 §3 Finding-1。

### 1.2 旧产物兼容(必须项,自己构造实测)

独立跑前端测试(vm 从分支版 lab.js 提取真实 `_atEmptyReasonText` 函数体)13/13 PASS,含:
- 旧产物 `{"date":"20260923","empty":true}`(无 empty_reason)→ 返回 `""` → 空行回退「当日无计划(空)」✓(不报错/不 undefined/不显示英文枚举)
- 非空 plan / null / undefined / 字符串 / 未知枚举 → 一律 `""` 不误标 ✓
- 三因枚举文案 + empty_detail 拼接逐字断言 ✓
- 空行三元组:有 reason →「当日无计划 · 原因」,无 reason →「当日无计划(空)」✓

### 1.3 §23.10 飞书抄送与邮件一致(易漏点)

- `scripts/nextday_plan_generator.py` 空计划邮件 body 改为「明日无买入计划。<br>原因:信号日 {T} {empty_reason 中文}」(+可选 `<br>细分:`)。
- `notify.py send()` 同一 subject+body 走邮件(HTML)+ 飞书(text,`_html_to_text` 拍平)+ Telegram,follow 群 text 模式,`send_feishu` 用 `log_text = f"{subject}\n\n{_html_to_text(body)}"` 全量送达。**内容一致,格式适配(HTML→text),§23.10 满足**。
- `check_signals.py` 无独立空计划文案(grep 零命中),不涉同步。

### 1.4 §23.3 举一反三(独立 grep 复核)

独立 grep(`无计划`/`(空)`/`空计划`/`.empty`),排除 min.js:
- `static-site/app.js` / `common.js` / `purpose-notes.js`:**零命中**(实施方 #6/#7 属实)。
- `static-site/lab.js`:`planDoc` 消费点 = `_atPlanRows`/`_atTradeDates`/`_atBuildDays`/`_atAllModalRender`/`_atRender`,`.empty` 只有改动的 2 处(T0/T1 group);弹窗空态文案是「暂无实操计划」(不同语义,非空计划日提示位)。
- `scripts/check_data_integrity.py`:`empty:true` 为合法态,新增字段被忽略(已读 L2030-2050)。`check_r2_consistency.py` 三版本指纹同态比对(生成器三目标同写同一 plan_doc,指纹一致)。`nextday_gap_check.py:145` 只读 `empty` 标志。`gen_schedule_stats.py` 无渲染文案。
- 结论:全站 12 个消费点核对属实,无遗漏渲染位。

### 1.5 不碰宇宙规则(独立核 diff)

- `git diff --name-only c3d4a83a7 origin/<分支>` = 恰好 3 文件:`docs/ops/empty-plan-wording-20260924.md` / `scripts/nextday_plan_generator.py` / `static-site/lab.js`。
- 无 `build_board_etf_map.py` / `config/universe_rules.yaml` / `app/queries.py` 改动。cgb_10y_etf 入样判定链(`_bt_in_universe` → 无跟踪 ETF → `not_in_universe`)未动,仍进不了计划。**无夹带**。

### 1.6 §24 前端铁律

- 分支 diff 无 `bump_asset_version.py`/`build_min.py`/`sw.js`/`index.html` 改动:实施方未自行 bump,min 重建+版本串 bump 留给主控 main-merge.sh ✓
- base commit = `c3d4a83a7`(= 当前 origin/main HEAD)✓;改动前版本串 `20260924-a614` 已核(index.html 引用 + sw.js `CACHE_VERSION=v6-20260924-a614`)✓

### 1.7 §23.15 完整版

- 独立跑分支版 dry-run(临时 worktree + 主树 venv,只读不落盘):`--date 20260924` 产出 `"empty":true, "empty_reason":"no_buy_signal"` ✓
- 三因 + empty_detail 均能正确产出:AST 实测三枚举 + 细分全过;前端三文案全过;dry-run 端到端验证 no_buy_signal。**非"先上一种"**。

### 1.8 §23.11

- diff 范围 = 声称的 3 文件,无版本串倒退、无静默覆盖、无 reset/force。✓

## 2. 回归安全(§15)

- `_build_plan_for_day` 加 `diag=None` 可选参数,签名向后兼容;回填/快照重演调用点(L888/L1024)不传 diag → 零影响(已核 3 个调用点)。
- 数据就绪 gate 走 fail-closed(return 2 告警),空分支只在真空计划到达,不会被 gate 错误填成 no_buy_signal。
- 新字段纯加法,`check_data_integrity`/`check_r2_consistency`/`nextday_gap_check` 读 `empty`/plan 标志不受影响。
- 原子写 `atomic_write_json` 保持。

## 3. Finding 明细

### Finding-1(条件,必须修才能 merge)[置信 ~85]
- **现象**:当日有买信号且全部被 AI 降亏过滤/停牌伪跳空剔除时,headline 报「均无可跟踪的 ETF 标的(不入可交易宇宙)」= 报错原因(headline 与 detail 自相矛盾)。
- **trace**:`diff_range`= `scripts/nextday_plan_generator.py` `_infer_empty_reason` + `_EMPTY_REASON_CN["not_in_universe"]`(L807-838);`static-site/lab.js` `_atEmptyReasonText` not_in_universe 分支(L14762-14782)。`linkage`=满足(空计划文案说清楚的本体)。`user_request`=用户 2026-09-24 拍板「把空计划文案说清楚」+ 根 CLAUDE.md「文案说错原因=比不说更糟」。
- **verifier**:`command`= `python3 /tmp/review_empty_reason_py_test.py`(AST 提取真函数体);`expected`= fade-cut 全剔 diag 应给出真实原因;`observed`=`reason: not_in_universe | headline: 当日有买入信号但均无可跟踪的 ETF 标的(不入可交易宇宙), 按规则不出买入计划 | detail: 被 AI 降亏过滤剔除 3 个`(headline 与 detail 矛盾,实测复现)。
- **频率**:需「所有买信号全被剔除」才触发;信号日通常买信号仅 1-3 条,风险日被 S06 降亏过滤全切是现实可能(空计划触发路径④本身被生成器文档列为设计态)。
- **最小修法(2 行文案,不动枚举/优先级/结构)**:
  - 后端 `_EMPTY_REASON_CN["not_in_universe"]` 改通用兜底措辞,例如:「当日有买入信号但均未进入买入计划(未入样/被过滤/被剔除), 按规则不出买入计划」;
  - 前端 `_atEmptyReasonText` 同分支同文案(去「当日」:「有买入信号但均未进入买入计划(未入样/被过滤/被剔除),按规则不出买入计划」)。
  - 邮件 body + 前端读同一字段,改一处文案即两展示位同修。

## 4. 低分项已滤(<80,附明细防黑箱)

- **前后端渲染措辞未逐字同源**:`_EMPTY_REASON_CN` 与 `_atEmptyReasonText` 三因中文措辞微差(后端带「当日」+全角逗号带空格,前端去「当日」)。不构成 §22 数据层违规(enum+detail 数值同源一致),仅渲染措辞差异,实施/维护时两处需同改。[~40]
- **`no_next_trading_day` 在 trade_dates.txt 陈旧时措辞可能误标「假期前/日历末端」**:真实原因是数据未更新。属 pre-existing(旧代码同样走空计划),非本次引入;`trade_dates.txt` 日常维护良好,风险低。走 §23.7⑤ 上报通道说明,不作为 finding。[~35]
- **dry-run 首跑用错文件(主树 base 版无 empty_reason)**:本报告已用分支版重跑修正,记录供后续 reviewer 防同类。[自省]

## 5. 审查证据文件(全部 /tmp,只读)

- `/tmp/review_empty_reason_test.mjs`(前端 13 断言,13/13 PASS)
- `/tmp/review_empty_reason_py_test.py`(后端 12 断言,12/12 PASS)
- `/tmp/lab.js` / `/tmp/nextday_plan_generator.py`(分支版只读副本)
- dry-run 独立验证:临时 worktree `/tmp/review-wt-5560ce452`(已 remove)跑 `--date 20260924 --dry-run` 产出 `empty_reason=no_buy_signal`。

## 6. 审查结论

**PASS-with-conditions**。
- 必改(才能 merge):Finding-1 两处文案措辞(后端 `_EMPTY_REASON_CN["not_in_universe"]` + 前端 `_atEmptyReasonText` 同分支),改完用户看到任何空计划原因都不会自相矛盾。
- 其余全部 PASS(三因判定、优先级、旧产物回退、飞书/邮件一致、§23.3 穷尽、宇宙规则未动、§24 合规、§23.15 完整、§23.11 干净)。
