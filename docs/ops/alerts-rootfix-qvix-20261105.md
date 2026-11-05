# QVIX 历史覆盖根治：实施与验证（2026-11-05）

本轮依据用户明确授权，在 `codex/alerts-rootfix-20261105`、基线 `6f95913bf` 实施已冻结且独立 PASS 的 candidate-r2。三业务模块与已审候选逐字一致；无 schema 变更。此记录描述源码与离线验证，生产数据未修复、未重跑采集、未部署。

## 已证问题与证据边界

主源返回历史、缺目标日时，原 `_qvix_fallback(just_date=...)` 的 RV 分支可能返回全历史；原单批接口丢失各段来源，generic UPSERT 将不同算法的历史写回同一两键。主源全失败时回退全 RV 也存在历史覆盖路径。因此只修目标日筛选不足以根治。

生产小序列对比发现两键分别有 1650 / 2838 个历史值从主源切为 RV；既有离线原始算法实算、并与生产精确键集对齐的仅为两个 `g.a_qvix_*` 家族共 **433 个真实键**。其余 **568 个下游键未进行真实全量重算**，不能表述成 1001 键全量闭环。两输入同时截到 20261030 后仍复现该 433 键集合。21:00:01 备份早于当轮采集，不等于紧贴 21:35 的值快照。

20261102 的合法主源修订（22.44→19.27、16.67→15.90）须继续接受，不做整段历史回滚。`a_qvix_1000` 对应既有 50ETF 代理口径（`config/indicators.yaml`、`docs/qvix-rv/qvix-rv-fallback.md`）；本轮不改代理映射或策略语义。

## 源码契约与所有实际写路径

- `fetchers.collect_series_batches` 显式区分主源历史段与 fallback 段。`just_date` 限制只用于 `_qvix_fallback` 的各分支；主源合法历史不截成当天。主源全失败时允许 RV 全史补空日。
- fallback SSE/RV 通过同一辅助行校验，拒绝 None、NaN、Inf、坏日期/坏结构，并给诊断；实际 ETF/TDX/RV 异常只损失辅助补日，正常主源历史仍返回。目标日缺失不记成当日新鲜。RV=0 合法；有限负值保留既有边界，未增设正数政策。
- `runner.upsert_metric`、`runner.upsert_metrics_many` 在现有 `ON CONFLICT ... DO UPDATE WHERE` 内原子限制：传入两 QVIX 键且 source 为 sse/rv_local 时，只能插入空日，不能覆盖任何已有行。无需“先查缺失再 UPSERT”，无新增 TOCTOU 窗口。
- 主源仍可替换已知 proxy、修订已有主源；沿用原 manual/NULL 旧行保护。未知旧标签不猜来源、不执行存量回滚。fallback 之间也不提升或替换已存在行，日后主源补到可正常更正。
- 三条实际 caller 均迁移：`runner._collect_one_metric`、`index_backfill.backfill_series_metrics`、`index_backfill.backfill_history_gaps`。每段按自身 source 调同一个批量 writer。历史 gap 原 `MAX(date)` 门仍保留，不扩大任务职责。
- legacy `collect_series` 对 QVIX 明确拒绝混批旁路；非 QVIX（两融、us10y）继续返回既有三元组。检索生产 caller 后，保留的 legacy 调用为 `scripts/us_stock_morning.py` 的 us10y。

同类错误面清单即上述两种 SQL writer、三条实际 caller、主源缺当日及全失败两条回退路径；均有测试。共享 pending 索引未发现点名 QVIX 待办；本轮不为无关待办增加接口。已检查本组文件初始未被其他 worker 修改，未触碰其写集。

## 可移植定向测试

命令（从仓库根运行）：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider scripts/tests/test_codex_qvix_fallback.py
```

结果：**216 passed**。测试只复制当前完整源码模块到 pytest 临时目录，不依赖研究 `/tmp` 输入、历史 git SHA、真实 DB 或凭据。网络、SMTP、子进程、生产 DB、仓库写出口先做拒绝正控，再导入业务模块。env、sys.path、sys.modules 与补丁均由 fixture 恢复。

| 边界维度 | 场景 / 验证 | 结果 |
|---|---|---|
| 输入域 / 状态组合 | 原 36 矩阵：两键×三 caller×主源/混合/全失败/缺日/错日/主源纠错 | 36 PASS |
| 极端值 / 辅助故障 | 两键×三 caller×16 种异常/非有限/空/错日/部分有效/RV0/有限负值 | 96 PASS |
| 时序 / 日期 / 单位 | 主源全历史保留、fallback 仅目标日、scale 各段准确、legacy 旁路拒绝 | 2 PASS |
| 状态保护 | 单/批 writer×两键×两 fallback×6 类已存来源，含 manual/unknown/NULL | 48 PASS |
| 并发 / 重入 | 两独立连接：fallback 到达 SQL 前，权威行先插入并提交；单/批均不覆写 | 8 PASS |
| 非目标负控 | 两融/us10y legacy 与 batches 等价、三 caller 及原 writer 行为 | 12 PASS |
| 主源合法修订 | 单/批 writer×两键，各 600 行既有主源/proxy 可更正 | 4 PASS |
| 上下游依赖 | 实际 ETF→实际 TDX→实际 RV 双源失败，三 caller 保留主源；仅网络入口打桩 | 6 PASS |
| 极端值 / 排序 | 实际 ETF+RV 对倒序恒定有限价格算出合法0；Inf 产生的非有限辅助值拒入库 | 4 PASS |

原版→修复→撤回对照在独立临时树运行同一可移植测试：原版 132 FAIL → r2 132 PASS → 撤回原版 132 FAIL；r1 辅助异常矩阵 72 FAIL/24 PASS → r2 全绿 → 撤回 r1 72 FAIL/24 PASS。测试仓库源码全程保持 r2，没有实际撤回工作树。非有限上游为可达故障注入，不声称已在生产发生。

原始日志和可复算对照由 `/tmp/codex-reports/alerts-deep-20261105/implementation-qvix.json` 索引；其中包含五文件 `files_sha256`、限定 diff SHA、冻结候选与独立 PASS 报告 SHA。三模块哈希与 r2 冻结 manifest 相同。未跑全套 pytest，按协调要求留给 parent 在三组冻结后统一执行。

## 交付边界

本轮只改三业务模块、本测试和本文档；不 commit/push/checkout，不修改其它 worker 文件，不运行生产 collector/通知/DB，不修线上数据。写码复用点为原有 source 字段、现有单/批 UPSERT、三条现有 caller，无新 schema 或策略框架。前端算法、代理映射、历史冻结护栏与既有跨日提醒均未改。四个间接下游的真实全量重算、全量测试及上线验证由后续主会话安排，不作为本轮已完成项。
