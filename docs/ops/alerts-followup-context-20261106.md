# 告警上下文补齐（2026-11-06）

本次在独立分支修改告警正文及对应回归，不提交、不推送、不部署。基线为 `0907797bf101df8600fa49f14045a6d1c477de5d`。107 行差异、R2 持续脱节的业务根因均未在本次定案，原失败判定继续保留。

## 核实依据与改动

- DIR-03 仍成立。历史 `abfb819422` 要求失败通知点名原因，实际却只把备注机器行带入正文。本次从同一份校验报告提取已生成的 FAIL 明细，保留库、表、两端数量、连接/完整性/日期等原因，HTML 转义后拼入实际 Bash BODY。原备注行、行数/新鲜度阈值、FAIL 退出码保持不变。正常周频 SKIP 不发失败正文。
- DIR-04 仍成立。历史 `70a6c31ed8` 把 10 月 4 日的 114 案例写入通用模板，现在会污染本轮 131 等计数。本次只使用当轮模式、待核查总数、补传成功数；明确总数尚未区分缺失、内容差异和 HEAD 无有效结果，不能当作已确认缺失数，覆盖来源待验。
- stale 正文不再列固定 a-stock/overview/news/schedule 示例池，也不再把结果定性为“设计内无需处置”或特定链路失败。仅引用真实当轮对象、规模、连续轮数和补传结果；连续 16 轮仍须排查，补传不等于源头修复。
- `verify-channels` 对本轮未完成/没有有效检查的情况明确输出“待验，未确认缺口”，仍 exit 1。超时 kill 只说明上传进程未正常完成，不宣称 PUT 一定未执行。没有改变降噪、补传、阈值或去重行为。

保留原主题、类别/台账 key、86400 秒窗、通知参数和优先级/渠道；真实分类器验证 mass 仍为 `r2` / `r2_deploy`。旧主题中的“可能”仍是兼容用的假设性命名，正文明确不把它当来源结论。

## 旧需求到新需求的测试迁移

旧 223 测试曾按历史需求要求正文包含 `≈114`、10 月案例、固定台账池及双因解释。本轮用户明确撤销这些通用模板要求，改为“本轮动态事实、来源待核”。只迁移 renderer 的输入与 D 段原有 8 条文案判别；A/B/C/E 的超时、调用点、判别阈值、subject/key 及 dedup 覆盖逐字保留，33 条断言下限不变，没有删测试养绿。

## 验证

```sh
PYTHONPYCACHEPREFIX=/tmp/alert-context-lint-cache bash scripts/lint_scripts.sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 \
python3 -B -m pytest -q --noconftest -p no:cacheprovider \
scripts/tests/test_codex_alert_context_20261106.py \
scripts/tests/test_223_timeout_gradient_copy.py
```

全量 lint 两轮均为 `=== lint 全通过 ===`。最终两模块原样末行：

```text
24 passed in 0.88s
```

新 23 例单独的旧→修→撤回对照：

```text
坏版：20 failed, 3 passed in 2.13s
候选：23 passed in 0.94s
撤回：20 failed, 3 passed in 0.85s
```

实际执行嵌入式校验 Python、受控 Bash 解析/正文赋值片段及真实 R2 通知 AST，不执行下载/上传/通知主体；SQLite 仅使用临时样本，完整性非 OK 分支只替换 PRAGMA 返回值，其余查询真实执行。异常状态不写成确认缺失；测试同时覆盖 131 动态量级、四个真实对象形态和连续 16 轮。沿用已有测试的八类陷阱正控和 fixture 恢复；唯一允许的子进程是有限 Bash 正文片段，命令超时 5 秒。pytest/lint 外层分别限 25 秒，日志及编译缓存只落 `/tmp`。

没有运行整个 `scripts/tests`；该套由父会话统一一次。未发真实通知、未访问网络/R2、未读 `.env`，未写业务数据。

## 明确未闭合的边界

以下保留首轮冻结时的记录；第 2 项已按后续窄修授权闭合，验证见文末追加记录。首轮冻结报告不回写。

1. **本轮已闭环**：`scripts/r2_upload_async.sh` 外层非零分支已改为“轻量对账未通过，待核查”，保留 `LIGHT_CHECK_PENDING` 等实际详情；不再把待验/超时断言成确认缺失。subject、dedup key/window、退出行为未改。portable 测试实际执行外层 `finalize_verify`，同时覆盖无缺口不通知及 pending 不误报确认缺口。
2. 首轮测试发现：完全损坏、无法执行后续查询的 SQLite 文件，会在 `table_count` 抛 `DatabaseError`，校验载荷可能在机器结果输出前中断。首轮为 `1 failed, 21 passed in 0.82s`。这不是本次正文改动导致；本次没有放宽/改写校验或误算其为通过。已生成 FAIL 的正文覆盖已验证，突然中断路径仍需单独修复。
3. 已生成 BODY 保留全部已生成的 FAIL 明细，实际渠道截断/摘要可见性由另一任务处理；这里没有验证真实终端送达，也没有据此宣称告警已端到端根治。

文件哈希和原始日志索引见父会话的 `context-implementation.json`；这些剩余项均不应被“定向绿”掩盖。

## 追加：完全损坏 SQLite 仍输出失败载荷

用户后续授权只改本脚本、原 context 测试和本文档；`upload_r2.py` 由 Schrodinger 独占，本轮没有改动。修复前，真实非 SQLite 文件虽然已在完整性阶段记为 FAIL，后续表查询仍会抛 `DatabaseError`，中断机器结果输出；第二端连接失败还会遗留已打开的第一端连接。

现在每张表分别查询备份和本地端，SQLite 读取异常记录为 FAIL，保留库、表、两端文件、另一端数量和错误类型/原文，继续其余表及其余可校验库。只有正常的 `no such table` 仍返回原缺表状态，其它 `OperationalError` 不再冒充缺表。完整性检查和行数检查的连接均在 `finally` 关闭，包括查询异常和只成功连接一端的路径。行数与新鲜度阈值、原正常表缺失判定、通知参数/级别/台账 key 和最终失败退出码均保留。

新增 4 例回归：真实坏文件位于备份端、本地端、双端，以及第二端连接失败。前三例不替换 PRAGMA 或 SQLite 查询返回值；使用实际错误文件，并在其后的有效库制造真实行数差，检查该差异仍进入正文、其后的健康库仍被校验。连接记录器只继承真实 SQLite 连接记录关闭，分别验证全部 12 / 11 个已打开连接均关闭。继续复用外发、业务子进程、凭据读取、仓库写入陷阱及环境恢复；只允许原有限 Bash 正文片段，超时 5 秒。

本轮原样末行：

```text
修前新增用例：4 failed, 23 deselected in 0.18s
最终完整 context 模块：27 passed in 0.95s
最终测试撤回源码负控：4 failed, 23 deselected in 0.18s
lint：=== lint 全通过 ===
```

执行命令为原 context 模块的定向 pytest（`--noconftest -p no:cacheprovider`）及 `bash scripts/lint_scripts.sh`，外层超时均为 25 秒；编译缓存和日志只落 `/tmp`。没有运行整个 `scripts/tests`，没有执行下载/通知主体，没有网络或生产操作，也没有提交/推送。它证明损坏文件诊断可进入生成的 BODY，不代表真实渠道最终送达；107 行业务差异仍按原规则失败，未作根因结论。

新证据、真实载荷/正文样本和本轮三文件 SHA-256 另见 `/tmp/codex-reports/alerts-followup-20261106/context-corrupt-implementation.json` / `.md`；旧 `context-implementation.json/md` 保持字节不变。
