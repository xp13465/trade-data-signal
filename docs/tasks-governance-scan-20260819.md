# TASKS.md 全量待办状态核验报告（2026-08-19）

> 用途：TASKS.md 真正瘦身（任务治理）的判定依据。逐条核 64 个 `- [ ]` 待办真实状态，产出「已完成可关闭 / 真活跃需保留」三分类清单，含证据链。
> 触发：2026-08-19 用户定「TASKS.md 瘦身=任务治理（完成关闭/废弃删除/活跃保留），非文字压缩」；pending-index #78。
> 扫描范围：TASKS.md 全部 20 个 `##` 章节（790 行），64 条 `- [ ]` 待办。
> 方法论：代码 grep（static-site/app.js、lab.js、scripts/、app/）+ 数据产物验证（data/、static-site/data/ DB/JSON）+ git log commit 佐证 + pending-index 已排除清单交叉核。只读不改。

## 统计总览

- 总待办数：64
- 已完成可关闭：34
- 真活跃需保留（含部分完成/未实现）：30
- 废弃可删：0（无"方向变了/用户明确不要"条目；L207 验证结论=akshare 不可用已换源，归完成）
- ⚠️ 需人工复核：8 条（见文末清单）

---

## 一、已完成可关闭（34 条：代码/数据/线上已实现，勾没打）

### 飞书群处理块（5 条全完成）

| 待办 | 判定 | 证据 |
|---|---|---|
| L78 飞书 08-11 18:16 两句消息漏收是否可读回 | 已完成 | scripts/feishu_missed_fetch.py 漏收补拉（2026-08-14）+ listener P0-2 启动自动补拉（L846 _run_startup_missed_fetch），漏收根治 |
| L79 报告群处理规则（问询出处理答复+有改动转开发群） | 已完成 | feishu_ws_listener.py L25-27/L548-587：报告群用户消息抄送开发群+落盘进待办+即时回执 |
| L80 告警群处理规则（问询可能上升需求） | 已完成 | feishu_ws_listener.py L28-29/L585-587：告警群仅带需求前缀才抄送开发群（复用 _match_prefix） |
| L81 需求群硬编码（前缀判定是否必需） | 已完成 | feishu_ws_listener.py L737/781：白名单需求群免前缀直接落盘，非白名单群保留前缀过滤；pending-index #24 已标完成 |
| L84 终端发的待办同步到群 | 已完成 | hooks 抄送（commit 2d1b9206e，E17 0token 抄送方案）；TASKS L16 hooks 飞书抄送已补回（tpl-proxy-full 模板） |

### 全球指数盘中实时块（4 条完成 + 1 条部分）

| 待办 | 判定 | 证据 |
|---|---|---|
| L204 P1 采全球5指数实时（nikkei/kospi/ftse100/dax/cac40） | 已完成 | intraday_snapshot.py L319-341 `_GLOBAL_SPOT_CODES` 含 5 指数 + `_fetch_global_realtime_sina()`（L341）；commit bccef3383 |
| L205 P2 港股板块8个盘中实时 | 已完成 | `_GLOBAL_SPOT_CODES` 含 hsmogi/hsmbi/hsmpi/hscci/cshklre/cshklc/cshkdiv（7 港股系）+cesg10（L344-345 注释明确） |
| L207 前置验证 akshare index_global_spot_em | 已完成（结论=不可用，换源） | intraday_snapshot.py L315 注释：akshare 走东财 push2 本机连接被拒（RemoteDisconnected），改用新浪 hq.sinajs.cn 批量采 |
| L208 前端配套全球Tab角标 | 已完成 | app.js L7086 addGlobalRealtimeBadge + L7117 refreshGlobalRealtimeBadges + L15412 调用；commit 1e9d5d432 |
| L206 P2 亚洲其他（ASX200/NIFTY50） | 部分完成→真活跃 | ASX200(AS51)/SENSEX 已采（L327-328）；NIFTY50 明确不采（L352-353 注释"印度用 b_SENSEX 代表，NIFTY50 暂不采"）⚠️ 需用户确认可接受 |

### accum_nav 前复权修正块（14 条完成 + 2 条待复核 + 1 条占位）

| 待办 | 判定 | 证据 |
|---|---|---|
| L209 accum_nav 除权日不跳 | 已完成 | etf_daily 表 accum_nav 列存在；512000 除权后 close 0.515（20260818）但 accum_nav=1.0308 平滑连续 |
| L210 etf_daily 加 accum_nav 列+1520只回填 | 已完成 | etf_daily 1526 只全部有 accum_nav，覆盖率 100%（≥92% 达标）；trade 与 trade-data 双库一致 |
| L211 10处计算层改用 accum_nav | 已完成 | accum_nav 已用于 build_board_etf_map.py L712-726（相似度）/etf_national_team.py/queries.py/alert_score.py/signal_kelly_backtest.py/export_etf_score_list.py 等多处 |
| L212 159536 TE 用 accum_nav 不虚高 | 已完成 | build_board_etf_map.py L920-1012 5项指标（avg_dev/TE/IR/R²/roll_std）用 accum_nav 日收益率 diff；159536 生产 track_te=2.3259 |
| L213 check_data_integrity + reviewer P0 smoke | 已完成 | check_data_integrity.py L44-45 track_score 三版本一致性容差校验（防 159335 类事故） |
| L214 实时展示 close 保持未复权 | 已完成 | 前端 app.js 无 accum_nav 展示，只展示 close 原始价；accum_nav 仅后端计算用（交易视角不变） |
| L216 1140对中≥92% track_score 非None | 已完成 | board_etf_map.json 1374 对中 1289 非 None = 93.8% |
| L217 全量计算<10s | 已完成 | 待办自注"实测6.3s" |
| L218 board_etf_map.json<700KB | 已完成 | data/board_etf_map.json = 645,966B ≈ 630KB |
| L219 前端_etfMatchTags 双标签 | 已完成 | app.js L2091 _etfMatchTags：PC 显"跟踪分X + grade/max_err%"(双维度)，移动端简化（L2101-2110） |
| L220 排序按 track_score 降序 | 已完成 | board_etf_map _meta sort_by="track_score(降序,跟踪分最高在前;None排最后)" |
| L221 curl overview 含 track_score | 已完成 | overview.json track_score 出现 744 次 |
| L222 sw.js CACHE_VERSION bump | 已完成 | sw.js CACHE_VERSION='v6-20260819-a354'（版本链持续 bump） |
| L223 TE 用前复权价或 NAV | 已完成 | build_board_etf_map L952 用 accum_nav 日收益率；待办自注"主控已验收跳变✓"；512000 accum_nav 1.0308 连续 |
| L215 159536 track_score<70 非良好 | ⚠️ 需人工复核 | 线上 159536：track_score=72.2(>70)、grade=good、approx=True、track_avg_dev=0.1043；新算法已抓出 V 型尖刺（72.2 分+approx 标记），但生产值 72.2 非原型 65.3 也非<70 |
| L224 自身跟踪591对 avg_dev≤0.2% 分类 | ⚠️ 需人工复核 | build_board_etf_map L983-994 avg_dev 指标+track_avg_dev 字段已产出（159536=0.1043）+grade 分类(excellent<1%/good<5%/warn>=5%)已实现；但"591 对 avg_dev≤0.2%"精确阈值未在代码直接命中 |
| L225 待需求确认+方案设计后定 | ⚠️ 占位待办 | 无具体内容，需用户/主控确认是否有对应需求；无下文建议删除 |

### etf 通知（1 条完成）

| 待办 | 判定 | 证据 |
|---|---|---|
| L568 未来增强 etf 通知（🐾 进/离/放量弹窗） | 已完成 | app.js L9726/9736/9749 showNotification('🐾 ETF进场/离场/放量信号')，点通知弹汪汪队明细；export_notifications.py 读 etf_signal（commit 90b8e1ceb/057fa74ff） |

### 费率块已实现子项（4 条完成）

| 待办 | 判定 | 证据 |
|---|---|---|
| L615 滑点固定百分比（默认千1） | 已完成 | simulate_trade.py L45 SLIPPAGE=0.001（单边） |
| L620 弹窗内嵌费率配置面板 | 已完成 | app.js L23957 _SIM_FEE_PRESETS 6档（commission/min/slippage/transfer/stamp 5参数）+ L24464 弹窗费率按钮 |
| L624 bump sw.js + deploy + 3域名 | 已完成 | sw.js CACHE_VERSION 当前 a354；版本链持续 bump |
| L629 upload_r2 上传 trade_sim | 已完成 | R2 迁移完成；upload_r2.py 有 trade_sim/trade_sim_data 前缀上传（exclude_prefixes L616 含 trade_sim 独立前缀） |

### 全站性能优化块（6 条完成）

| 待办 | 判定 | 证据 |
|---|---|---|
| L685 P1-6 首屏 fetch Promise.all 并行 | 已完成（被 boot.json 合并取代） | app.js L10451 boot 失败 fallback"原 P1-6 行为：Promise.all 三 fetch"；boot 成功单 fetch 覆盖 |
| L687 P1-8 首页 22 JSON 合并 boot.json | 已完成 | app.js L5171 "P1-8(2026-08-05): boot.json 首屏单 fetch 合并 11 个 JSON（请求数 22 -> 2）"；static-site/data/boot.json 存在(1.3MB) |
| L692 P2-12 9 sticky + IO rootMargin | 已完成 | app.js L19552 rootMargin:"300px" + L19915/L20106 scroll spy rootMargin "-15% 0px -70% 0px" |
| L693 P2-13 CSS transition 改指定属性 | 已完成 | style.css L319/L1106/L1526/L2084 will-change/contain（P2-13 注释标注） |
| L694 P2-14 分时图 11 echarts 改 SVG | 已完成 | app.js L4929 siteCfg("charts.lightweight") 默认 true + _lwSetup SVG 分支（_renderIntradayChart L8544） |
| L696 P2-16 update_all 东财封IP industry 换源 | 已完成 | direct.py L205-208 同花顺行业资金流第五源（data.10jqka.com.cn）+ industry_extras.py L142 主源换同花顺 stock_board_industry_index_ths |

---

## 二、真活跃需保留（30 条：部分完成/未实现，仍待跟进）

### 次日开盘（1 条，部分完成）

| 待办 | 判定 | 证据 |
|---|---|---|
| L77 真实跟信号操作口径确认 | 部分完成→真活跃 | ②SOP 已做：lab.js L9736-9737 "次日分批挂单SOP"按钮 + L9846 "次日买入玩法"文案（2026-08-15）；①前端展示/回测默认改次日开盘口径未做（默认仍当日收盘），pending #15 确认 lab.js 无次日开盘口径，待用户确认是否切 |

### 全球指数（1 条）

| 待办 | 判定 | 证据 |
|---|---|---|
| L206 P2 亚洲其他（ASX200/NIFTY50） | 部分完成→真活跃 | ASX200(AS51)/SENSEX 已采；NIFTY50 用 SENSEX 代表（L352-353 注释），⚠️ 需用户确认可接受 |

### 费率块未实现子项（14 条）

| 待办 | 判定 | 证据 |
|---|---|---|
| L612 simulate_trade 抽核心函数(fee_config) | 未实现 | simulate_trade.py 仍模块级常量（SLIPPAGE/TRANSFER_FEE_RATE），无 fee_config 参数 |
| L613 加印花税（卖出万5） | 部分 | 前端 _simSellWithFees L23996 stampDuty 已实现（_SIM_FEE_PRESETS stock_def stamp_duty_rate 0.0005）；后端 simulate_trade.py 无印花税（grep 印花 无输出） |
| L614 过户费3模式（沪深统一0.001%） | 未实现 | simulate_trade.py L47 仅沪市 TRANSFER_FEE_RATE_SH=0.00001(万0.1)，非沪深统一 0.001% 3 模式 |
| L616 费率对比函数 | 部分 | 前端 6 档预设可对比；后端无对比函数 |
| L617 FastAPI /api/trade_sim_recalc | 未实现 | app/main.py 无该路由（仅 /trade_sim.html L544） |
| L621 fee_config localStorage 持久化 | 未确认 | app.js L23550 feeParams 字段存在，grep 未直接命中 localStorage fee 持久化 ⚠️ |
| L622 重新回测按钮调 API | 未实现（前端重算代替） | 无 API 可调；L24504 _simOnFeeChange 前端重算 |
| L623 费率影响对比区块（对比表+双净值曲线） | 未确认 | 前端预设选择有；"默认vs当前 对比表+双净值曲线叠加"未 grep 到 ⚠️ |
| L627 修正 simulate_trade 印花税万5+过户费bug | 未实现 | 后端无印花税字段 |
| L628 全量重生 103 个 trade_sim JSON | 未实现 | 后端无印花税，JSON 无法含印花税字段 |
| L630 验证线上 R2 JSON 含印花税 | 未实现 | 后端无印花税字段 |
| L633 默认 vs 自定义费率对比正确性 | 部分 | 前端 6 档预设可对比；后端全量 JSON 未含印花税 |
| L634 双净值曲线叠加渲染 | 未确认 | 未 grep 到实现 ⚠️ |
| L635 3 域名验证 | 未确认 | 依赖前面实现 ⚠️ |

### 场外基金方案C全量化（8 步，主体未实现）

| 待办 | 判定 | 证据 |
|---|---|---|
| L656 步骤1 export_fund_score 补字段 | 未实现 | export_fund_score.py L51-57 查询字段无 fund_company/fund_manager/setup_date 等扩展字段 |
| L657 步骤2 手动触发 weekly 全量评分 | 部分 | pf_score_weekly.sh L37 compute_all_scores(top_n=None) 调度已建；当前 fund_score.json count=2000（非 27418），全量导出未落地 |
| L658 步骤3 D1 创建 + sync 脚本 | 未实现 | worker/ 无 d1 binding，无 sync_fund_score_to_d1.sh |
| L659 步骤4 worker/fund_score.js | 未实现 | worker/ 目录无 fund_score.js（dataQuery.js L62 是统一查询 API 读 fund_score_top.json，非分页 worker） |
| L660 步骤5 前端分页 fetch | 未实现 | renderOffshoreFund 仍读 fund_score_top.json 静态文件 |
| L661 步骤6 点击弹窗5区块 | 未实现 | 未实施（ETF 评分弹窗 openEtfScoreDetailModal 已有，场外基金详情未做） |
| L662 步骤7 build_min+bump+deploy | 未实现 | — |
| L663 步骤8 调度确认+线上验证 | 未实现 | — |

### 性能块未实现子项（3 条）

| 待办 | 判定 | 证据 |
|---|---|---|
| L690 P2-10 app.js code-splitting | 部分 | app.js L26265 requestIdleCallback 延迟非首屏 init 已做；按 tab 拆 chunk 未做 |
| L691 P2-11 大盘 tab 30+ echarts 改 SVG | 未实现 | renderAStock L15055 内部 L16112 仍 echarts.init；全 app.js 35 处 echarts.init |
| L695 P2-15 offshore_fund 85MB 清理 | 部分 | 已走 R2（upload_r2.py L541 cmd_upload_offshore_fund，update_all.sh L169 调用）；本地 static-site/data/offshore_fund_*.json 仍 ~150MB 未删，update_all.sh L164 仍跑 export_offshore_fund.py 未停 |

---

## 三、废弃可删（0 条）

无。唯一接近的 L207（akshare 前置验证）结论为"akshare 不可用、改新浪源"，验证本身已完成，归已完成可关闭。L225（占位"待需求确认+方案设计后定"）无具体内容，若用户确认无对应需求可删除。

---

## ⚠️ 需人工复核清单（8 条，拿不准/证据不足，主控/用户重点看）

| 待办 | 疑点 | 建议 |
|---|---|---|
| L215 159536 track_score 验证 | 生产 72.2（>70）非预期<70，但 approx=True 已标；新算法是否达"抓出 V 型尖刺"目标需确认 | 请用户/主控确认可关闭 |
| L224 avg_dev≤0.2% 分类阈值 | avg_dev 指标+字段已产出，但"591 对≤0.2%"精确阈值未在代码直接命中 | 请主控 grep 确认阈值细节或直接关闭 |
| L225 占位待办 | "待需求确认+方案设计后定"无内容 | 请用户确认是否有对应需求，无则删除 |
| L206 NIFTY50 | 用 SENSEX 代表（b_NIFTY 仅 6 字段不可用），是否可接受 | 请用户确认或保留 |
| L621 fee_config localStorage | grep 未直接命中持久化逻辑 | 请主控确认 |
| L623 费率影响对比区块 | "对比表+双净值曲线叠加"未 grep 到 | 请主控确认是否已做 |
| L634 双净值曲线叠加 | 未 grep 到实现 | 请主控确认 |
| L635 3 域名验证 | 依赖前端对比区块是否实现 | 请主控确认 |

---

## 与 pending-index 交叉核（防重复派）

- 全球指数盘中实时 15 指数已在 pending-index【已排除清单】"其他"段标"已上线" → L204/205/208 佐证完成。
- 飞书需求群硬编码 pending #24 已标完成 → L81 佐证。
- 凯利次日开盘口径 pending #15 状态"未派（lab.js 无次日开盘口径）" → L77 ① 未做，真活跃。
- 场外基金阶段1 评分引擎+阶段2 UI 已在已排除清单 → 与方案C（全量化 8 步）是不同工作，方案C 主体未做。

## ## 复现

- 脚本/命令（逐条核验用，均在本仓库根目录跑）：
  - 待办定位：`grep -n '^\s*- \[ \]' TASKS.md`
  - 全球指数：`grep -n '_GLOBAL_SPOT_CODES\|_fetch_global_realtime_sina' app/collector/intraday_snapshot.py` + `grep -n 'addGlobalRealtimeBadge' static-site/app.js`
  - accum_nav 数据：`python3 -c "import sqlite3; c=sqlite3.connect('data/etf_national_team.db'); print(c.execute('SELECT COUNT(DISTINCT etf_code) FROM etf_daily WHERE accum_nav IS NOT NULL').fetchone())"` + `SELECT date,close,accum_nav FROM etf_daily WHERE etf_code='512000' ORDER BY date DESC LIMIT 3`
  - track_score 覆盖率：`python3 -c "import json; d=json.load(open('static-site/data/board_etf_map.json')); ...count track_score non-None..."`
  - 飞书群处理：`grep -n '白名单\|_match_prefix\|maybe_forward_user_message' scripts/feishu_ws_listener.py`
  - etf 通知：`grep -n '🐾\|showNotification' static-site/app.js`
  - 费率：`grep -n '_SIM_FEE_PRESETS\|stampDuty' static-site/app.js` + `grep -n '印花\|stamp_tax' scripts/simulate_trade.py`（后端无印花税）
  - 场外方案C：`ls worker/`（无 fund_score.js）+ `grep -n 'top_n' scripts/export_fund_score.py`
  - 性能：`grep -n 'P1-8\|boot.json' static-site/app.js` + `grep -c 'echarts.init' static-site/app.js`（35 处）
- 数据截止日期：2026-08-19（board_etf_map.json/overview.json 17:10、etf_daily DB 20260818/19、fund_score.json 16:00 生成）
- 关键口径：判定"已完成"= 代码 grep 命中 + 数据产物生效 +（尽量）commit 佐证，三重至少两重成立；"部分完成"= 半数以上子项未实现或前后端不一致；"真活跃"= 明确等待用户确认/排期/大工程搁置。

---

## 用户拍板记录(2026-08-19,主控记)

### 已拍板 4 条(用户:没啥用就关/删)
| 待办 | 用户拍板 | 处置 |
|---|---|---|
| L215 159536 track_score 验证 | "没啥用就关了吧" | 关闭(#11 时勾掉) |
| L224 avg_dev≤0.2% 阈值 | "没啥用就关了吧" | 关闭(#11 时勾掉) |
| L225 占位待办(无内容) | "没啥用就删了吧" | 删除 |
| L206 NIFTY50 | "没啥用不要了" | 关闭(接受 SENSEX 代表) |

### 待 8/18 费率改造收尾再拍(费率对比区块相关,状态随 #18 变化)
| 待办 | 说明 |
|---|---|
| L621 fee_config localStorage 持久化 | #18 预生成静态方案落地后确认 |
| L623 费率影响对比区块 | 同上 |
| L634 双净值曲线叠加 | 同上 |
| L635 3 域名验证 | 依赖上面实现,部署后验 |

### 执行方式
#11(implementer 按清单处理)攒到 #18 费率改造收尾后一次跑,避免对 TASKS.md 反复改动(§5.3 核心保障)。
