# 第二版进展追加：定向结果与未关闭的验收

本段追加在第一版提交 `727e35b65ece5c1d202a866edbe804fcce83cea3` 之后，原版审计、21 类状态和历史结论不回写。**这是进展归档，尚非收口终版**；先等父提供真实部署、CI、最终独立审查与逐键恢复证据，再追加终版。各项状态权威仍在 pending-index。

## 实现与审查分层

| 对象 | 已有证据 | 尚不支持的结论 |
|---|---|---|
| #380 测试隔离 | `ace115157617eceb0d1abd20c41cdeab4fb9b503`；作者定向 `22 passed in 0.39s`；缺 ALERTS_FILE/digest lock/digest state/REPO env/恢复补丁五种变异各 `1 failed` 真红 | 作者全量 420s 超时，rc124，已有失败/错误标记，尾部 `.................F.F.......`，无完整汇总。不能称全绿或验收通过 |
| #379 preupload 统计 | `25dccda35abea3ec96a39355abc35231d3534cdf`；作者定向 `119 passed in 4.70s` | 父派单时作者 full 进行中；本轮核证的执行报告已更新为 rc1/494.3s，尾部 FileNotFoundError：pytest 会话临时仓库路径不存在，没有完整 pytest 汇总。不推断谁删除路径，也不据此归因业务缺陷；不称全量通过 |
| 原父整合内审 | `integration-review.json` 对固定 `36b8a7e58d93dd9930ff020623d7cd849131df83` 给 PASS；局部 `74 passed in 2.31s` | 不是最终新三 P2 通过，不替代后来 head 的全量、独立审查、CI 或生产验收 |
| 新父整合 | `52b0ed5f58cccc899ba8bd52fb20ae52798994fa` 含原 4d、main41c 及 ace115/25dcc；文档归档侧已用祖先关系核对 | “包含两支”不等于最终合审部署成功；4d 的旧 CI 计数也不能移贴 |

以上均按作者/审查方证据归档，本分支没有重跑业务测试套件或真实通知器。12 份输入已另存私有固定快照，避免父报告后续推进改变本版身份；仅文件名/字节数/hash 入 [progress-v2-evidence.json](progress-v2-evidence.json)。

## #381：独立的 R2 结果契约项

已核对 37 个本地分支、7 种索引 blob 及全部现存 worktree：最大现号 #380，未见 #381；索引同类搜索未发现本结果契约已立项。#353/#354 的排队/同域互锁继续沿用，新增 **#381 `R2-PURGE-RESULT`（P2）** 单独承接结果契约，不把它混为改锁必修。

固定源为 `52b0ed5f58cccc899ba8bd52fb20ae52798994fa`：

- `scripts/upload_r2.py:2682–2813`，`purge_cache`：真实函数 AST 故障注入中，缺 secret 与全部批次 HTTP503 两例均返回 `None`、不抛异常。
- 同文件 `:3405–3424`，`cmd_purge_low_freq` 忽略返回结果；`scripts/r2_upload_async.sh:399–418` 的 purge 失败处理不进入最终非零结果，末尾固定 `exit 0`。函数动态反例与 CLI/async 静态追踪分开记，不冒称本分支执行过业务链。
- Boyle 已在同任务转实施，依据 `ops-closeout-plan.json`；最终结果应区分完整成功、合法空清单成功、缺凭证及失败批，保留运行/失败清单身份，继续后续有界补传并最终报告失败。具体实施与独立审查结果尚未落到本版。

**父已收窄方案边界：先证明 `invalidate-before-publish`（缓存失效早于对象发布）的排序安全。** 独立 cache 锁在旧方案里只是候选，未证并发上传/清理顺序安全前，不把它列为必修或宣称可直接拆锁。缺 `PURGE_SECRET` 是合成输入反例，不是在宣称线上 secret 缺失。现有 intraday/purge 失败清单也不能因为候选实施或总链 rc0 销账。

`progress-v2.json` 保留此 P2 的 trace/verifier、精确源锚点与期望；故障反例证据 hash 是 `375f02efccad6f36aea0dc6b2cb48980984113d33da30f7b49ae7b8c9ad0d4b4`。不复制原始消息、私密群 ID 或凭证。

## 恢复与 #375

Rawls 的只读来源核证已证明 **016989 的 Nov3–6 四日净值、hs300/csi500/gem 的 Nov9 数据在现有可信源可得**，可进入受控恢复准备；没有据此关闭 #333/#257。实际恢复须部署身份、生产前备份、白名单/锁/差异与逐键结果，不能用 source ready 代替生产已恢复。

`159501`/`159513` 两 ETF 的现有生产净值供应源（天天基金历史接口和原采集器使用的源）均只到 **Nov6**，无 Nov9 累计净值；状态为**上游待发布**，不以旧值、OHLC 或当前映射造数，也不外推“全世界均未公布”。现有真实 freeze 与 NULL 保留，相关历史/T0 问题不销账。源原文留私有目录，本仓只留归一化日期/键/状态与 hash。

**#375 继续 OPEN**：父补查现有 Git credential 不可用、Chrome 桥连通失败；这只证明取得原错误的通道受限。仍无原始失败错误，不推断原部署问题由凭证导致，不擅改凭证或部署配置。

## 复现与后续

报告本体 [progress-v2.json](progress-v2.json)、生成脚本 [generate_progress_v2.py](generate_progress_v2.py)、本复现段组成追加版三件套。默认输入为 `/tmp/codex-reports/alert-takeover-20261110/docs-source-snapshot/progress-v2/`，缺原件时不能声称重跑证据校验：

```bash
python3 -c 'import subprocess; subprocess.run(["python3","-B","docs/codex-reviews/alert-takeover-20261110/generate_progress_v2.py","--check"], timeout=30, check=True)'
python3 -c 'import subprocess; subprocess.run(["python3","scripts/check_task_state.py","--skip-zombie-crons"], timeout=30, check=True)'
```

生成器逐一验 12 输入的 hash 后仅提取允许字段，不复制原始源日志、SSH 命令、消息正文或凭证，不运行外部业务。父后续须提供最终完整 head、原样全量测试汇总、独立审查、同 SHA 真实 CI、main/云/Worker 部署身份和逐键恢复证据后，另追加终版。本次同分支只文档提交，不 push/main merge，不销账。
