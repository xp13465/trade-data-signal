# HC18 — USD/CNH 合同隔离与当前消费阻断

本次交付完成代码隔离与当前消费防护，**没有恢复FX指标，也没有恢复跨市场分、恐贪分、全市场高位/低位预警**。本轮全部写者均标 `_fx_available=false`；排除FX后的内部部分分数不是完整评分，读方返回不可用。日线供应商收盘时区与日期语义仍缺第一方确认，不能宣称已根治或历史损益已纠正。

- 分支：`codex/ops-fx-contract-20261111`
- 基线：`0ad543ef41758be9d7102b42471489b24d0cb989`
- 独立工作树：`/Users/linhuichen/code/trade/.claude/worktrees/codex-ops-fx-contract-20261111`
- 最终完整提交/推送结果及文件清单：`/tmp/codex-reports/ops-backlog-20261111/fx/report.json`
- 原始证据目录：`/tmp/codex-reports/ops-backlog-20261111/fx/`
- 用户已明确授权实施及一跳扩展；不修改角色规范、主控文档、pending-index、原交接packet或ACK。

## 反例与第一方核验

先复现旧解析器再修改：`before.json` 中CNY近价被收、CNH被拒，字段不等样本[3]=7.1/[8]=7.2却输出最新价7.1/昨收7.2。此前独立调查的887行BOC旧值+1行6.6724污染见 `docs/codex-reviews/ops-followup-20261111/fx-identity/report.md`；本轮未读写生产数据库，也没有把全表除100。

第一方只读HTTP逐次有20秒curl上限、25秒进程上限；未运行真实collector。

- [Sina USD/CNH页面](https://finance.sina.com.cn/money/forex/hq/USDCNH.shtml)：绑定 `fx_susdcnh`。
- [页面字段代码](https://n.sinaimg.cn/finance/forex_n/getData_20241021.js?v=20241021)：显示价[8]、昨收spj[3]，不是反向取值。`sina-fields.raw`留存原件。
- [第一方K线SDK](https://finance.sina.com.cn/sinafinancesdk/js/datas/k.js)：日线记录date/open/low/high/close；不能据未充分解释的SDK参数推定实际close时区。
- [第一方实时报价](https://hq.sinajs.cn/list=fx_susdcnh)：`sina-hq.raw`保留名称、代码、非等价字段样本。
- [第一方日线API](https://vip.stock.finance.sina.com.cn/forex/api/jsonp.php/fx_history/NewForexService.getDayKLine?symbol=fx_susdcnh)：`sina-day-candidate.raw`为完整未裁剪回包，2026-11-11T08:10:13.930302+08:00采样，SHA256 `daadb29322be0e19bc5d556e1c211da224e2b0c0c5233990dccb7b8768101053`。

两份已存真实日线回包分别截止11/09与11/10，均不含11/11当日行；这两次有限样本不能证明接口通常是否含当日K线。实现已支持**校验OHLC后排除当日未完成行**，回执记录 `excluded_dates=[{date,reason:current_day_unfinished}]`，不丢弃其余历史。未来日期、重复日期（包括重复当日）、非法OHLC仍整批拒绝。用完整真实原件重复导入3132行，最新源日20261110，`excluded_dates=[]`；未为通过校验裁样本。

另复现首页真实KPI链 `cross_market_6m → ntIndexSparkline → _ntSparkGeom` 的 `Number(null)=0`，`spark-before.json`输出 `[0,0]`。修复后SVG/ECharts都保留空值，不画零线；有效0仍正常绘制，缺口不跨接。

## 合同与写入隔离

产品仍是离岸人民币USD/CNH，每1USD兑CNH，不改为BOC/CNY，不调交易阈值。专用模块 `app/fx_contract.py`管理：品种/基础币/报价币/每1单位/价类型/source_id/contract_version/as_of/source_timezone。

- `usdcnh.sina_quote.v1`：仅provider_latest实时报价。严格匹配CNH代码和名称、字段[8]/[3]，同源日且源时间0–900秒，拒未来/过期/跨日/时区不符/缺来源/单位混入；真实跳变不自动除100。并发条件UPSERT仅允许更新源时间更晚的报价，相同样本幂等，旧源时间不覆盖。
- `usdcnh.sina_day_candidate.v1`：只在独立候选库。source含日线合同、provider日期、`as_of_precision=day`、`source_timezone=unverified`、第一方URL、fetch时间与原件SHA256。不假造精确收盘时间，不与实时价混序列。
- `python -m app.collector.fx_history`仅离线导入指定原件，输出须专用staging库且精确标记/表结构；拒绝应用库和软链。事务内冲突整批回滚。旧原始历史无更新/删除。
- 预热分别报20/60/90/120样本窗口；不足窗口为false，超过7天的日期缺口重新计尾部窗口。该规则只是样本数检查，**不代表交易日完整性已认证**。真实3132条已满足数量窗口，但仍`active=false`，原因`daily_close_timezone_unverified`。
- 通用collector拒绝写legacy/isolated FX key；config停用旧BOC路径。signals固定列表现在尊重enabled，且FX即使误设enabled=true仍被计算入口拦截。

## 暂不可用范围与产品影响

| 对象 | 当前行为 | 原历史 |
| --- | --- | --- |
| `usdcnh`、`g.usdcnh` | 指标/历史线/信号/策略统计不可用；UI明确旧历史待重建 | daily_metric与signal_daily原件保留 |
| `cross_market`、`fear_greed` | 所有未验证历史及本轮部分重算均读为None，图线空点；`s.cross_market/s.fear_greed`不参与当前信号/统计 | 旧数值/冻结标志/更新时间不被部分重算覆盖 |
| `high_alert`、`low_alert`（全市场） | 即使其余维度够用也因cross/fear缺失返回NaN；导出null、数据不足、triggered=false | 旧高低预警/冻结记录保留，当前日历/近期预警展示排除 |
| signal消费/导出 | normalize、queries（含cache）、overview、sentiment、global、轻量extras、signal_stats/freq、market_summary、通知reader均过滤旧FX及两种衍生信号 | 不重写已发通知；不改冻结交易账本 |
| 首页/市场/通知前端 | fetchJSON成功与缓存、boot/旧JSON、KPI/tooltip/迷你图、信号日历都保持unknown；不会Number(null)=0、不会填50/中性/安全 | 原数据文件不删除，历史摘要标不可用 |
| 摘要与日报 | 未带新版本的旧摘要缓存不再进入当前摘要通知/日报；须先由新代码重建summary。RSS历史条目仍保留日期但显示不可用 | 原summary_history文件、已发邮件/飞书不改 |
| 次日计划与单品种模拟 | 当前计划排除FX候选；simulate_trade全量跳过FX，直接请求FX/两类衍生模拟会明确拒绝重建 | 已生成模拟结果/历史交易归档保留，不视为已校正 |

新`cross/fear`内部诊断值可以保留在新版本行中，但`_fx_available=false`，任何当前评分消费者均不得拿这些值当完整市场分。未带版本或缺覆盖证明的旧值也一律不可用；单独切enabled不会恢复。

独立CNH实时跑马灯使用`133.USDCNH`，本次代码条目与base完全一致（`ticker-preserved.json`），与指标隔离。其它独立A股/per-index情绪分、非FX指标继续显示。单标的ETF高低评分与全市场high/low不是同一数据源，本次没有改变其策略权重、阈值或其既有仓位算法的中性后备参数；已核其不把本次全市场None作为输入。日报规则自己的confidence=50也不是被替代的FX/市场评分，本轮未改其产品定义。

交易冻结/持仓/原始历史账本、Kelly历史回放/补账及已生成交易归档没有迁移或重算。本交付不宣称这些历史结果正确、也不据本次停用抹除历史事件；旧跨市场数字在独立指数reason中的软注释从当前展示移除，独立触发本身保留。

## 恢复条件（尚未满足）

1. 第一方确认USD/CNH日线的收盘价类型、源日期/收盘时区和未完成日规则；固定已验证来源版本。
2. 用隔离历史完成交易日/缺口与所有实际技术窗口检查（不仅样本数量），对照同合同报价；保留冲突/排除回执，不能把BOC全表除100冒充CNH。
3. 在隔离数据根重算FX及完整cross/fear/high/low，提供前后信号差异和历史影响清单；保持阈值不变，不回写既有持仓/冻结/已发事件。
4. 父任务与Claude复核后另作明确激活变更：读写合同接通、完整覆盖标记与版本、当前信号过滤/冻结日历/前端guard同步更新。**本轮没有生产激活开关，也不能仅把`_fx_available`改true或enabled打开就视为验证完成。**
5. 父任务整合时统一构建前端、更新资产版本、重建当前导出并清缓存，再做部署后真实页面/自然轮次验证。此工作树只验证源码，本轮未构建/发布`app.min.js`；当前index版本仍`20261108-a660`。

## 验证与证据

测试隔离REPO/GIT_REPO到临时根；新增测试自动拒绝socket DNS/connect与子进程外发。所有DB、生成JSON均在tmp_path或上述/tmp证据目录。实际算法/查询/导出函数执行，取证装饰器按需stub；没有运行真实collector/邮件/飞书/生产发布。

- 真实链A：污染legacy序列→真实normalize/rolling→cross.compute/store→guarded score→signals.compute→queries.global_market→static-site.export.export_global。旧120行FX及旧sell仍在DB，但当前导出无旧信号，旧冻结score值/更新时间未变。
- 真实链B：SQLite默认tuple连接→实际signal计数→实际8+8维与加权算法→compute_alert_scores→export_alert.export_for_date→原子alert.json。其它维度确实可算分作为负控，完整性缺失仍null、不触发；旧99/冻结原件保留。
- 其它正负控：CNY/CNH近价、单位/价类型/缺source、源过期/未来/不同日、价格字段不等、14.4真实跳变不归一、19/20、59/60、89/90、119/120预热边界、gap、导入冲突回滚/幂等、当日排除与未来日拒绝、旧缓存、通知阈值、计划入口、真实Row/tuple差异。
- 浏览器执行实际fetch/cache/renderGlobal、SVG/ECharts spark、旧boot/通知/summary_history防护，390×844与1440×900截图，路由拒绝外部网络。不是线上全站或真机验收。

命令：

```sh
REPO=/tmp/fx-tests-data GIT_REPO=/tmp/fx-tests-data /Users/linhuichen/code/trade/.venv/bin/python -m pytest -q scripts/tests/test_fx_contract_20261111.py scripts/tests/test_codex_qvix_fallback.py scripts/tests/test_signal_universe_refresh_20261109.py
PLAYWRIGHT_MODULE=/Users/linhuichen/code/trade/scripts/playwright-accept/node_modules/playwright FX_EVIDENCE_DIR=/tmp/codex-reports/ops-backlog-20261111/fx node scripts/tests/fx_contract_browser_20261111.cjs
```

执行时均由外层Python Popen进程组设总timeout（pytest90秒/browser55秒），超时killpg并wait回收；日志落/tmp，小摘要回传。完整原始末行：

```text
347 passed in 6.95s
FX browser: 37 assertions passed; actual fetch/cache/renderGlobal; no external network
```

Python变更源码compile、`node --check static-site/app.js`、`git diff --check`通过。早期失败原日志保留，包括取证stub/AST环境与browser helper缺失，修复后复跑通过；没有隐去失败。未执行仓库全量测试；父任务负责全量整合及最终Claude复核。

## 修改文件（仅本任务）

- `app/alert_score.py`
- `app/collector/fx_history.py`
- `app/collector/gold_night.py`
- `app/collector/intraday_snapshot.py`
- `app/collector/runner.py`
- `app/compute/cross.py`
- `app/compute/fear_greed.py`
- `app/compute/market_summary.py`
- `app/compute/normalize.py`
- `app/compute/signal_stats.py`
- `app/compute/signals.py`
- `app/fx_contract.py`
- `app/queries.py`
- `config/indicators.yaml`
- `docs/codex-reviews/ops-backlog-20261111/fx.md`
- `scripts/check_signals.py`
- `scripts/daily_summary_email.py`
- `scripts/export_alert.py`
- `scripts/export_notifications.py`
- `scripts/gen_daily_brief.py`
- `scripts/gen_rss.py`
- `scripts/nextday_plan_generator.py`
- `scripts/simulate_trade.py`
- `scripts/tests/fx_contract_browser_20261111.cjs`
- `scripts/tests/test_fx_contract_20261111.py`
- `static-site/app.js`
- `static-site/export.py`
