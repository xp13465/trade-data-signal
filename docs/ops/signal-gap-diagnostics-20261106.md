# 信号→交易缺口：同轮诊断补证（2026-11-06）

本次只补充 `check_kelly_coverage` 已检测异常的正文和私有归档。诊断不证明历史应成交，也不修复或回填业务数据。

## 前后语义边界

| 项目 | 改前 | 改后 |
| --- | --- | --- |
| 候选 | 当前 universe/best ETF、已有 trades、最近信号窗口 | 保持原逻辑，不扩大检测人群 |
| blocked / 深度 / 降级 | 当前候选下一窗口交易日 NAV/open，以及原精确 freeze hit / 同日 trades 规则 | 原原因返回值和判定保持；诊断不参与判定 |
| 通知 | 原 key、level、title/subject、去重、ack、恢复和退出码 | 保持原逻辑；只追加正文 |
| 价格解释 | 当前 best ETF 价齐容易被理解为历史应该产生 trade | 原结果明确标记“仅当前候选”；另列冻结 ETF 的观测，历史应成交仍为 unknown |
| 保存 | 无完整同轮诊断归档 | `data/audit/signal_gap_diagnostics/<uuid>.json`，完整已检测异常集合，正文预览 10 条 |

## 与真实 producer 的一跳合同

`signal_kelly_backtest._resolve_etf` 先按排除类别剪枝，查 `_signal_key(date,iid,sig)` 精确键；非 None 即返回冻结值。否则 `_freeze_fallback` 按日期/指数索引及实际 `_SIG_RANK` 处理信号类型漂移，再进入当前映射及历史补冻防御闸。

checker 只解释本轮已加载 freeze 的精确键，不复制兜底排序或选择算法。`observed_exact_freeze_key` 只记录当前输入中实际存在的键。仅当精确 entry 为 dict 且 code 为六位 ASCII 数字字符串时，`resolved_freeze_key` 才记录 checker 这个输入中的精确键；无效 code（含数字、布尔、数组、空值、非 ASCII 或非六位格式）一律为 `unknown`，不转换字符串伪装有效 ETF。`producer_resolution` 无条件为 `unknown`，不把 checker 观察冒充真实 producer 解析结果；精确值缺失时写 `unknown` 并标记兜底尚未评估；不能声称“producer 也无冻结”。精确值无有效 code 时冻结 ETF 仍为 `unknown`；六位格式有效仅表示输入格式符合，不证明 ETF 存在或实际可成交。`exact_freeze_key_present` 另行区分空值/缺键。

checker 既有 freeze 加载路径优先 `static-site/data/`，再 `data/`；producer 则为环境覆盖路径或 `ROOT/data/`。本次不改加载优先级，不读取环境覆盖目标；诊断明确缺少 producer 输入身份，因此精确命中也只是 checker 本轮冻结输入的证据。

`_classify_buy_rows` 还要求已加载 `signal_stats[iid][sig]['10d']['score']`，再调用 `_backtest_one`。后者在默认次日开盘口径需要信号日有效 NAV/close、producer NAV 日期序列中的后续日 open，并有占位、伪跳空、费用、持仓价等条件。checker 未加载这些 producer 上下文，不能靠两个窗口日价齐推断成交。评级和历史 producer 资格明确为 `unknown`；已有资格证据仅为 checker 当前 universe 入选。

## 证据、资源与完整性

- 原查询观察的当前候选下一日 NAV/open 随同原查询结果保存；缺库不是价齐证据。
- 前 32 条异常可在原只读连接上补两个冻结 ETF 点查：信号日、窗口下一交易日 NAV/open/close。后者不是 producer 已解析的 next NAV-date。
- 每条最多两个 `EXPLAIN QUERY PLAN` 和两个 `SELECT ... LIMIT 2`；要求计划同时含代码和日期等值 SEARCH，否则记 `unknown_no_point_index`，不扫描历史。出现重复行、缺列、缺记录、占位行有明确状态。
- 完整异常集全部保存，不因 32 条补证预算和 10 条正文预览截断。`records_complete` 仅指本轮 checker 已检测异常，不表示全部历史/全部业务异常已审计。超预算项保留 key、精确 freeze、当前候选及原检测价证据，额外价格为 unknown。
- 不新开诊断 DB 连接，不扫描/哈希 DB 或冻结全历史，不重载 trades，不加载 signal_stats。逐条观察复用连接，但不是 producer 的事务快照。全部未传入 producer/input 指纹为 `unknown`。
- 沿用 `atomic_write_json(..., mode=0o600)` 在唯一 staging 目录先写、flush/fsync、replace；再 `os.link` 原子发布到 UUID 文件名，已存在目标绝不覆盖。staging 最终清理。
- 目录缺失会尝试创建；不可写、JSON 序列化、原子写或 link 失败只记录 stderr，保留原 Finding 和告警路由/退出语义。正文 JSON 预览若遇非 JSON 的 SQLite 值也降为 unknown，不阻断原告警。本轮覆盖检查若无异常则无归档。诊断归档也会随直接 coverage 调用生成，包括主入口 dry-run；原通知/state 的 dry-run 行为不改。
- 归档是本地私有取证，不上传、不通知新渠道；不改 freeze、accepted、DB 或生产产物。未加保留期自动清理任务。

## 隔离验证与复核

`test_codex_signal_gap_diagnostics_20261106.py` 使用 stdlib unittest，从 AST 只载入定义及所需常量，不 import checker/producer/notify 业务入口。每个用例在载入业务定义之前正控 socket/process/DNS 外发陷阱；所有 DB 和通知 state/归档均位于临时目录。原 `_notify` 与 `run_alerts` 保留，替换的只有 subprocess 传输返回值，不能声称真实送达。

运行定向验证（外层执行器设超时不超过 30 秒）：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s scripts/tests -p test_codex_signal_gap_diagnostics_20261106.py -v
```

可设 `SIGNALDIAG_BASELINE_SOURCE` 指向事先导出的基线 checker 源码，比较候选/通知/去重等未改函数 AST，以及不同价格/冻结输入下的原原因、blocked、key/等级/title。未提供该变量时仍执行具体已知行为断言，但不声称做过基线源码对比。

关键反例：临时数据的当前候选 NEW（510300）的 20260907 NAV/open 为 1.2/1.1；精确冻结 OLD（159001）的 20260904 NAV 为 NULL、20260907 open 为 NULL。原检测会给“已具备次日价仍无 trade”；新诊断展示两个 ETF 的证据及 unknown，不把当前价齐等同于历史应成交。

另有预算外完整性、同标冻结降级、T-1 缺价降级、真实解析器精确/漂移兜底合同、复合索引缺失、schema 缺列、占位过滤、归档权限/唯一/禁止覆盖/不可写、原通知失败重试/成功去重/恢复、空集合负控。

未执行真实 compute/backtest、任何真实网络/SSH/通知/上传/采集、业务全量 CLI 或全量 tests/lint；既有 FAPI 内存测试 NOT_ALL_GREEN 不在本次范围。没有改门限/skip，没有 commit/push。后续交 Claude 复核本工作树差异。
