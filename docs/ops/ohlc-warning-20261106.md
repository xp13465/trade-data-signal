# OHLC 空窗口警告文案修正（2026-11-06）

本轮按用户明确授权，仅修改 `app/collector/etf_national_team.py` 的一个 `print` 文案，新增定向测试和本文档。基线为 `0907797bf101df8600fa49f14045a6d1c477de5d`，分支 `codex/alerts-followup-20261106`。没有部署、生产采集、数据修复或 commit/push。

## 原因与行为

原文“主源 sina+fallback mootdx 均返空，close/amount 将为 NULL”不能精确描述实际行为：

- 采集函数返回空列表时，真实 worker 原样返回；`_upsert_daily` 遍历零行，本轮不写 OHLC，已有行情保留。
- 原始主源可能有更早历史，只是全部早于 `start_yyyymmdd`，过滤后仍为空，不能称两个端点原响应都空。
- 后续份额写入只更新 `fund_share`：新日期可有份额而缺 OHLC；同日份额更新不会清掉已有行情。

新文案保留 `[ohlc] WARNING` 和代码，增加请求窗口 start，明确“本轮不写 OHLC、已有行情保留、新份额行可能缺行情”。触发条件、逐码次数、采集、回退、重试、字段转换及 SQL 全部不变；不新增例外或静音，不判断未上市。

依据为既有 `ohlc-code.json/md` 的完整代码链、真实日志与 runtime 精确查询；07:46:53+08 的生产快照中 11 码 `etf_daily` 均为 0 行，不能描述为已有历史被写 NULL。上市／首交易日期与源支持状态由父会话继续补证，本文不作定性。NaN／显式缺字段的通用 writer 边界没有与这 11 条警告关联的生产证据，仅保留为残余风险，本轮不修。

## 验证

从仓库根运行：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider scripts/tests/test_codex_ohlc_warning_20261106.py
```

结果：**57 passed**。测试不依赖研究 `/tmp` 数据、历史 git SHA 或本机凭据；先正控阻断网络、SMTP、子进程、生产 DB 和仓库写，再复制当前完整模块到 pytest 临时目录。实际调用 fetcher、两种 worker 和 `_upsert_daily`，不执行业务 pipeline 主体。fixture 自动恢复 env、sys.path、sys.modules 和补丁。

|边界维度|真实入口验证|结果|
|---|---|---|
|输入／状态／日期|11 码×已有或无历史×无数据或历史早于 start；空列表写0行、已有行情保留|44 PASS|
|上下游／新增份额|上述44例追加新份额日OHLC留空；既有日期份额更新保留OHLC|含于44例|
|回退／全史入口|沪深各一码×已有或无历史，实际全史worker沿用同一警告和空写行为|4 PASS|
|正常数据／极端值|沪深×主源或备源×成交额0或100；同输入原值返回、合法历史修订继续写入|8 PASS|
|重入／可见性|连续两次空请求产生两条 WARNING，未抑制或合并|1 PASS|
|并发|未新增并发测试：只改打印内容，所有采集／SQL／锁与原版完全一致|范围外|

旧研究阶段已在 `/tmp` 完整模块完成 22 状态×原版／候选／撤回，共66次数据控制：数据行为不变，文案准确性为0/22→22/22→0/22。此候选按冻结 SHA 逐字应用；新定向 pytest 验证实际工作树源码，不依赖该旧探针。

源码及测试通过无 pycache 的 `compile()` 语法检查；限定 `git diff --check` 通过。将唯一目标 `print` 的消息参数归一化后，原版和候选 AST 完全相同，确认只有打印内容改变。全量 pytest 按协调安排由父会话统一执行，本组未运行。

## 范围与冻结

唯一写集为业务模块、本测试、本文档。已完整读 canonical 角色、CLAUDE、协作协议及 implementer skill；本轮例外授权不改变默认只读角色。检查 pending 索引 #84 已完成，不扩采集；复用原警告入口一行，无新增框架或白名单，无算法／前端公示改动。原研究报告保持原字节，其它 worker 文件未触碰。

冻结报告 `/tmp/codex-reports/alerts-followup-20261106/ohlc-implementation.json` 含三文件 `files_sha256`、限定 diff SHA、定向原始日志和语法检查结果。生产真实双源值级一致性和这 11 码的上市交易期仍待父会话核实；合成正常输入的同值测试不替代这些实证。
