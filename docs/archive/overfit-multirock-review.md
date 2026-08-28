# overfit 监控卡多口径改动回归审查报告(a295, commit 12bf87e37)

- 审查人:reviewer agent | 日期:2026-08-16 | 改动分级:B(前端逻辑)+ C(后端数据产物)跨前后端
- 结论:**CONDITIONAL PASS** —— 无 P0;1 个 P1(help 公示文案悬空,需主控定夺补 UI 或改文案);若干 P2;数据一致性/前端上线/多口径数据完整性全部通过。

## 一、改动影响面清单(grep 引用面)
- 数据文件 `static-site/data/overfit_monitor.json`(32MB,br 1.7MB)唯一前端消费者 = `app.js _appendOverfitCard`(L1988 fetchJSON);`app.js L11278` 仅为注释,非第二消费者。无 lab.js/其他模块引用。
- 后端 `scripts/overfit_monitor.py` 为数据唯一生成源;`upload_r2.py L557-559` 有 overfit 强制 R2 例外;launchd `com.trade.overfit-monitor` 定时任务在。
- 全局符号 `_overfitState/_overfitDimLabels` 仅 overfit 卡内部使用,无外部引用。

## 二、P0 级问题
无。

## 三、P1 级问题(需主控定夺)
### P1-1 help modal「顶部综合分」公示文案与 UI 不一致
- 证据:`_overfitHelpModalHTML`(app.js L1554,本次 commit 新增)写「顶部卡片左上角综合风险分固定按 60 日口径显示(单一权威值,前端不重算)」。
- 但 grep 全前端:`overfit.current.risk_score` 无任何渲染消费点(仅数据层存在,供后端预警用);overfit 卡 HTML(标题区/fade 行/tip 行/两图)均无综合分单点数字。a294 旧版同样无此渲染。
- 影响:用户按 help 说明找「顶部综合分」找不到,公示承诺了 UI 不存在的东西(§21 公示 vs §22 一致性口径下,公示文案应与实际 UI 对齐)。
- 处理方向(不改代码,供主控选):①前端补渲染 `overfit.current.risk_score` 到卡片左上角(数据已具备)②改 help 文案去掉「顶部卡片左上角」描述,只保留「综合分/预警口径仍按 60 窗口」。
- 与「两图随口径」关系:用户要求两图随口径——准确率/风险分曲线确实按 `_overfitState.roll` 换 key 重算 ✓;顶部综合分固定 60 仅是后端数据层字段(current 恒 60 窗口),UI 未展示单点,故不存在「顶部单点不随口径」的 UI 矛盾。矛盾仅在 help 文案悬空。

## 四、P2 级问题(非阻断,建议修复/备注)
### P2-1 overfit-tip hoverpop 显示 `<b>` 字面量
- 证据:overfit-tip 的 data-tip 含 `<b>显示范围</b>` 等 HTML 标签;`_initTermPop` 对无 sigType/data-idx 的元素走 `pop.textContent = text`(app.js L3542 附近 else 分支)→ pop 里显示字面量 `<b>显示范围</b>` 而非加粗。功能可用,视觉瑕疵。修复=该 tip 去 `<b>` 或 show 分支支持 innerHTML 转义渲染。

### P2-2 冷请求性能:32MB 近 15s 超时上限
- 证据:curl 主站冷请求(edge 未缓存)实测 14.5s 返回,接近 fetchJSON 15s 超时(app.js L4846)。br 传输 1.7MB 正常路径可接受;前端异步加载(`_appendOverfitCard` 在 sigCard 后 append + await)不阻塞首页 ✓;SW network-first + CF edge max-age=14400(4h)缓存,冷请求频率低。边缘场景可能超时显示「监控数据加载失败」空态。

### P2-3 fetchJSON 先试 .json.gz 404
- 证据:static-site/data 与 R2 均无 overfit_monitor.json.gz;fetchJSON 对 `./data/*.json` 优先试 `.gz`(方案Y)→ 首次加载多一次 404 再 fallback .json。既有机制,非本次引入。

### P2-4 数据完整性校验不覆盖 overfit_monitor.json
- 证据:`check_data_integrity.py`(L55-68 清单)与 `check_r2_consistency.py`(L39-53 清单)均不含 overfit_monitor.json。32MB 大文件 C 级产物无自动校验拦截。既有状态非本次引入,建议补「该有的数据在不在 + 三处 etag/version 一致」。

### P2-5 10 口径细维度空态(数据特性,非 bug)
- 证据:10 日窗口 + 细分维度末点 n 常 <20:grade.high actual[10] n=5、sell_stop_loss actual[10] n=5 → 前端正确显示「XX 10日滚动窗口样本不足(n<20)」空态(有 guard,不画误导曲线)。total 10口径 n=113 ✓。help 未明说此场景,用户切 10 口径+高评级可能意外看到空态。

## 五、已通过项(逐项证据)
| 审查点 | 结果 | 证据 |
|---|---|---|
| §22 三处一致性 | PASS | 本地 static-site/data md5 `dfb2b5f9ca8b1012ec6d15d54296cd57` == staticdata 仓库 md5 == R2 etag `W/"dfb2b5f9..."`;三处 version=v2, generated_at=2026-08-16 15:43, daily_by_win/rolling 均 5 窗口(10/15/30/60/100) |
| 主站 vs R2 直链 | PASS | ss.fx8.store/data 200+br+同 etag;ssd.fx8.store/data 200+br+同 etag+同 version |
| 前端展示层上线(§24 三查③) | PASS | 线上 app.min.js?v=a295 md5 == 本地(7498bfe3...),含 `data-overfit-roll`/`统计口径`/`180日`;index.html 版本串 a295;sw.js CACHE_VERSION v6-a295 |
| by_k/filtered_by_k 各 K 档 | PASS | by_k[1..4].accuracy.rolling.backtest 均 5 窗口;filtered_by_k[1] 同 |
| by_signal/by_grade 各维度 | PASS | buy/buy_aux/buy_special/buy_backup bt+act 5 窗口;sell/sell_stop_loss 仅 act(bt 空=预期,前端 btEmpty 单曲线);high/mid/low 5 窗口 |
| daily_by_dim | PASS | grade.{high,mid,low} 与 sig_type.{buy,sell,sell_stop_loss} 均 5 窗口 |
| 布局重排点击绑定 | PASS | win/roll/grade/sig/k 五类按钮均在 card click 委托(card.addEventListener L1920),rollBtn 新增分支 L1933;active 初始态正确(win=60/roll=60/grade/sig=null) |
| 空态文案 `${roll}日` | PASS | L1661「该维度 60日滚动窗口样本不足(n<20)」,roll=数字正确拼「N日」 |
| 预警/告警逻辑 | PASS | `evaluate_alerts` 用 bank_raw overfit.current(固定 60 窗口)+ prev.daily(固定 60,`overfit.daily` 未变);SURFACE_DAYS 200 不影响 current/最近 daily 序列;WINDOWS 变更不波及 d1 计算(`calc_d1_deviation(act_roll.get(60),bt_roll.get(60),60)` 的 60 仍在 WINDOWS 中) |
| 备站影响(§23.7) | PASS | 备站 data/ 404 是既有架构缺陷(overview.json 也 404);前端 fetchJSON 备站主动域名重写 `./data/* → https://ss.fx8.store/data/`(app.js L4826+),overfit_monitor.json 在备站走主站回源可拉到;本次未新增备站数据依赖 |
| §23.7 冻结契约 | PASS | 改动均为 a295 用户确认需求(新增 180 档/新增统计口径/布局重排/tip 精简);默认行为不变(win 默认 60, roll 默认 60);无夹带未确认历史功能调整 |
| §21 公示 | PASS(除 P1-1) | help modal + overfit-tip data-tip + 卡头注释均同步 5 口径;purpose-notes.js 无 overfit 条目(overfit 卡非独立 tab,公示落在卡内 tooltip+help 弹窗) |
| §23.2/23.3 同类覆盖 | PASS | overfit_monitor.json 单一消费者,无同类消费点遗漏;无其他读 rolling 60 单窗口的前端代码 |
| 定时任务 | PASS | launchd com.trade.overfit-monitor 在,21:40 盘后打点会用新代码重跑生成 5 口径 |

## 六、结论
- **上线判断**:CONDITIONAL PASS。数据层/前端逻辑/一致性全部通过,无 P0。P1 为公示文案悬空(help 说「顶部综合分」但 UI 无此单点),不属数据错误,不阻断上线但需主控明确处理方向;若用户本意就是要顶部综合分单点显示(help 已如此承诺),则属实施漏做 UI,需补渲染后复审。
- **备站 404 处理**:不需处理,既有架构缺陷且被前端主站回源重写规避,本次不加重。
- **顶部综合分固定 60 与「两图随口径」**:不矛盾(见 P1-1 说明)。
- **关键产出**:数据产物三处一致 + 5 口径全维度完整 + 预警安全 + 前端逻辑正确;唯一需要主控拍板的即 P1-1 文案/UI 二选一。
