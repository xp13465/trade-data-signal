# 冻结 136 / DataGap 5：根因、可修依据与本次交付

- 授权：本次用户特批可实现，Claude 审合部署；指定 worktree / `codex/alert-freeze-20261109`；仅 commit、不 push。
- base：`8118feef3bbfdfdcde70e169e950749d3e5a408a`。
- **历史交易安全补好 0；136 缺冻、DataGap 5 缺交易仍未关闭。诊断修复不计作补好交易。**
- 机器报告：`/tmp/codex-reports/alert-rootfix-20261109/root-cause.json`（先于实施落盘，后追加只读证据）；同内容另存 `freeze-root-cause.json`，本任务证据范围见 `freeze-evidence-manifest.json`，不引用目录内其他并行任务产出。

## Findings

### 1. 至少六个事件的原行情 writer 来源与「首轮补入后不刷新」机制已有强证据

定位：`app/collector/intraday_snapshot.py:_backfill_signal_universe_tencent`。`have` 取**当天存在任意行**的指数，`missing = universe - have`；后续轮次不会重新请求这些指数。判据自 `fdc3b497f7`（9/11）存在，本次未改该文件。

真实备份点查：

| 改写前备份 | 行情键 | OHLC | source |
|---|---|---|---|
| 11/2 21:00，11/3 07:03 | 11/2 csi_000102 | 四价均 3105.86 | intraday_snapshot |
| 同上 | 11/2 gz_399365 | 四价均 10215.27 | intraday_snapshot |
| 11/4 21:00 | 11/4 csi_000102 | 四价均 3081.81 | intraday_snapshot |
| 同上 | 11/4 csi_000330 | 四价均 4647.47 | intraday_snapshot |
| 同上 | 11/4 csi_000673 | 四价均 2413.83 | intraday_snapshot |
| 同上 | 11/4 gz_399395 | 四价均 7302.27 | intraday_snapshot |

之后 11/3 或 11/5 21:00 备份均为 `source=collect`、有真实高低收价。11/2、11/4 的 09:25 原日志明确该函数补入目标指数，之后至 15:35、20:35 都记录「今日已覆盖，无可补缺口」。这些 id 在 `_SIGNAL_UNIVERSE_TENCENT_MAP`，不属于九核心指数/申万/THS 写入分支。10/28 的 09:25 日志也列出 csi_000102，后续轮次跳过；该日改写前数据库备份已不在本次保留窗口，不能补造旧 source。

独立反例执行真实 writer 函数：首轮提供 OHLC=100 并写入；第二轮提供收盘 110、高 111、低 99，函数返回 0，未再请求，库中仍为 100。这是**本地刷新条件缺陷**的证据，不能简单归因为「远端晚到」。原始远端 quote 未归档，不能断言当时远端收盘数据是否及时。

证据：`writer-source-backup-points.json`、`writer-intraday-log-trace.json`、`writer-reproducer-final.log`。

- trace：base 中上述函数 / `have` 与 `missing` / 对应六键备份；关联用户「修之前分析真正原因」，`origin=pre-existing`。
- verifier：`python3 scripts/diagnose_alert_freeze_writer_20261109.py`。
- expected：若同日实时行可刷新，应存 `[100,111,99,110]`。
- observed：`first_writes=1, second_writes=0, fixture_fetch_calls=1, observed_ohlc=[100,100,100,100], refreshed=false`，**exit 1（有意暴露未修缺陷）**。
- 处置：该 app 文件不在本次可写范围，**不修改**。Claude 可单独审查只刷新当天本源实时行、保留更强 collect 行、验证报价日期/时点的源头方案；不能用放宽历史冻结闸补偿。
- 证据边界：source 是模块级标记，不含逐行写入时间/原始 quote；备份、日志、映射、函数反例共同支持这六键；不把它外推为全部 18 键，尤其不据此认定申万四键的精确旧 writer。

### 2. 18 个事件有「历史行情改写 → 历史信号 appeared」持久证据，含 DataGap 5

136 键全部执行 `history_overwrite_audit` 的 **date 索引点查**，18 键有 signal appeared；这 18 个 (date,index) 全部有更早几分钟的 index_daily changed。`before_val/after_val` 顺序由 `app/history_audit.py:_IDX_VALUE_COLS` 确认是 open/high/low/close/pct_change/amount。

DataGap 5 精确时序：

| 信号键 | 原行情 changed | signal appeared |
|---|---|---|
| 20261028 csi_000102 buy | 10/29 17:59:32，close 3276.07 → 3335.87 | 10/29 18:01:01 |
| 20261028 sw_801770 buy | 10/29 17:57:06，close 5379.48 → 5493.52 | 10/29 18:01:01 |
| 20261102 csi_000102 buy | 11/3 17:57:41，close 3105.86 → 3155.19 | 11/3 17:59:09 |
| 20261102 gz_399365 buy | 11/3 17:56:34，close 10215.3 → 10380 | 11/3 17:59:09 |
| 20261104 csi_000102 buy | 11/5 17:55:14，close 3081.81 → 3240.09 | 11/5 17:56:48 |

其余 13 键及完整字段在 `all136-historical-audit.json` / `late18-index-input-audit.json`。四个 DataGap CSI/GZ 样本的 old OHLC 四价相等，申万通信是原 close 改写；不能将两种来源混为一类。

`signals.store()` 对全历史 DELETE+INSERT 重算，审计记录 appeared 表明前一次历史快照无该键；`_resolve_etf` 在日期已过、无精确/类型变体冻结时拒补。这解释了历史重算新增后的缺冻路径，**不是已证实的「及时生产已出现而冻结写盘失败」**。审计并非 first-ever 日志，不能排除更早出现后消失；时序关联也尚未逐键全输入截断复算证明某一次 OHLC 单改动足够产生信号。

### 3. 新增 17 个 THS 旧日期键：映射恢复暴露旧事件，非 11/8 当日新漏冻

- 11/1 21:00 备份已有其中 11 键，11/2 有 15，11/4 已 17/17；全部早于 11/8。
- 11/8 05:00 deploy 日志：六指数成分股为 0，overlap/holdings 跳过。
- 11/8 16:42 deploy 日志：MCU 439 / CPO 99 / 氢能 286 / 量子 85 / 汽车芯片 78 / 存储芯片 143 个成分，生成 overlap 与 holdings 候选。
- 05:04 guard 119 → 16:55 首份 136，差集正好这 17 键。

故「11/8 批量新入库、当日漏冻 17 次」已被备份证伪。映射恢复后，旧日期首次/再次进入当前可映射集合，触发原有历史拒补闸。日志中的候选恢复不等于有信号当日 map 快照，仍不能恢复当时应选 ETF。

证据：`nov8-log-and-snapshot.json`、`historical-deploy-trace.json`、上轮 `private/frozen-set-comparison.json`。

### 4. 136 的精确分组与不可恢复部分

`97 + 17 + 18 + 4 = 136`，互斥、不重复：

- 97：csi_000813，2012—2016。9/18 产品根因文档已经明确该指数当时 track_score=None、不进 best_etf、未冻，支持「映射/评分资格后来变化」解释；没有这 97 键逐键首次输入证据，不能全量定因或 accepted。
- 17：上述 THS 映射恢复。
- 18：上述历史 appeared / OHLC 改写链。
- 4：`20261009|csi_000330|buy_aux`、`20261009|csi_970070|buy_aux`、`20261009|sz_div|buy`、`20261105|dax|buy_special`，未取得足够因果证据。

最早冻结批次为 8/13 22:37、28083 键；当前两云树各 28629 键，但现值相同不能证明没有过覆盖。可见备份元数据没有逐日旧冻结/map 快照；signal_daily 本身没有 created_at。未运行生产回测/采集，不用今天的 map 表示历史。最新 Nov6 三个买信号已冻结沿用上轮证据，本轮没有重复六键存在性核验。

### 5. checker 候选宇宙不等于历史可交易资格；本次不改包含集合

三源核对：

| 来源 | 确认内容 | 限制 |
|---|---|---|
| UI `static-site/purpose-notes.js` 的 lab.sigkelly | 信号收盘后固化、次日开盘成交，评级分高/中/低 | 未明确说明无评级如何排除 |
| 产品 `docs/kelly/analysis/kelly-freeze-timespot-rootfix-20260918.md` | 旧日期无冻拒补、冻结优先、未评分指数原先不入 best_etf | 不是全部历史事件的时点记录 |
| 产品 `docs/kelly/position/kelly-nextday-open-backtest.md` §1.1/1.4 | 信号日NAV × 次日open/信号日close，伪跳空处理 | 当时分析报告不是后续每笔交易资格证明 |
| 现有 producer `_resolve_etf` / `_classify_buy_rows` / `_backtest_one` | 冻结/类型兜底优先、无10d score跳过、正价/close/伪跳空检查 | 不能据现值推断历史当时资格 |

真实函数隔离复现：checker 当前 best 可报 SEVERE，而 producer 历史无冻结返回 None；冻结有但无评级也跳过；零 open / 缺信号日 close / 伪跳空均返回 None。完整输入见 `contract-reproduction.json`。

当前 checker 尚用 current best、未载评级，不能据「价齐」宣布历史应交易；也不能把全部候选判为假警。无足够独立来源确认完整排除契约，**候选集合、等级、阈值、冻结/评级/定价策略均不改**。独立 frozen_missing 告警保留。

## 本次最小实现与三验

实施前报告已落盘，三验只对以下诊断问题成立：

1. 旧 guard 归档输入 hash/latest 固定 unknown；真实加载输入与保存后文件无法区分。根因位于 `_archive_frozen_missing_diagnostics`；现在 `compute` 在首次解析/内存补冻之前，抓加载 freeze / best_etf / effective buy_rows / signal_stats 的 canonical JSON hash 和数量、latest；归档再追加保存成功/失败结果。**不是磁盘字节 hash**，map 明示为 resolved best_etf，不伪装原 map 文件。未提供 context 的旧调用仍写 unknown，取证失败不吞原告警。
2. checker 正文与 WARN 标题将未查 accepted 的候选称「已知接受缺口」，并建议直接补价重跑。修正为当前映射候选、资格待核，明确精确 accepted 登记才算接受，先核历史 ETF 选择；保留候选、告警 key/等级/dedup/独立缺冻信号。

没有修改 `_resolve_etf`、`_classify_buy_rows`、`_backtest_one`、`_build_best_etf`、checker 候选/原因/stale/宇宙/降级门控；10 个函数 AST 与 base 完全相同，证据 `semantic-guard-check.json`。

新增诊断工具仅在临时 SQLite 样本中执行 writer 定义，不执行生产入口/网络/真实采集；exit 1 有意证明范围外缺陷仍在，不能当作修复通过。

## Checks

- 定向：`python3 -m pytest -q --tb=short scripts/tests/test_alert_freeze_rootcause_20261109.py scripts/tests/test_codex_frozen_diagnostics_20261106.py scripts/tests/test_codex_signal_gap_diagnostics_20261106.py`。
- **原始末行：`32 passed, 21 subtests passed in 1.02s`**；`targeted-tests-final.log`（最后一次仅为标题资格表述补测，未重复全量）。
- 全量唯一一轮：`python3 -m pytest -q --tb=short scripts/tests/`，240 秒有界。运行至约 79% 触及总时限，回收进程组，**exit 124，无完成汇总，不算 PASS**；原始日志 `full-pytest.log`。按用户要求不重复全量，由父整合源码后统一执行。
- 测试覆盖：加载对象身份在内存新增/磁盘替换后不漂移；诊断序列化失败仍拒补；真实 compute 编排的保存成功/失败状态；三个历史截止点映射恢复后不补冻；checker 真实告警仍可见且不冒称接受。既有告警出口/去重/恢复/失败隔离测试通过。
- 防前视：无分位数/特征库改动；三个隔离历史截止点只用该时点已有映射可冻，后来恢复映射仍拒补旧日期。未做全历史策略重算，不宣称全系统防前视验收。
- 七轴：输入域（可JSON/不可JSON）测；状态（冻结空/新增/历史缺失）测；时序（解析前/磁盘后变/映射恢复）测；依赖（保存失败）测；极值（旧日期/无最新日）测；回退（无context→unknown）测；并发（归档不可覆盖由既有用例测），未测实际生产竞争，不推断生产部署结果。
- 阶梯：复用现有 archive、原子写与告警路径，hash 用标准库；新工具直接执行原 writer 函数，无第二套策略。pending 索引只读检查；不写共享索引/CLAUDE/app/source其他文件，不碰 ops/d1/gen_schedule_stats，不 push/不部署。

## Verdict / Open questions

**历史恢复 BLOCKED；本次交付为诊断来源修复与可复核根因证据，待 Claude 审合，整合全量未完成。**

- 优先根治已证实的 writer 首填后不刷新机制，但由拥有该 app 文件的任务实施；要验证新报价真实时点和源优先级，不能无条件覆盖 collect 行。
- 申万旧合成值的精确历史 writer、THS 映射首次可用、97 老键/4 余键的首次输入、冻结持久化/覆盖历史仍缺证据。
- 每笔恢复均须可信的当时 ETF 选择或冻结记录；当信号实际直到次日收盘后才出现，还须明确它无法按过去次日开盘成交，不能伪造跟单历史。
- 当前 136/5 不全 accepted、不降级消音、不改阈值、不重冻。**业务缺口仍 136 / 5，交易补好仍 0。**
