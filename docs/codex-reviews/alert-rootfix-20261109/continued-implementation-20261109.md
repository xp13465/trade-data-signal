# 2026-11-09 授权接续实施记录

用户在明确“Codex 独立分支实现、测试、commit/push 与 CI，Claude 最终复核、合并和生产部署”的范围后回复“继续”。本次特批不改变日常只读外审角色。主工作树、main、Claude 工作树和生产数据均不由本次接续修改；共享 pending-index 仍为状态权威，本文件只记录本次证据。

## 接续已有成果

Claude 的冻结持久化修复及 F1/F2 收尾固定在 `06cde8d7371ae352bfde8a915b19b4cf3cb97750`。其工作树已有 `worker/ops_baseline.js` 的未提交生成结果，SHA-256 为 `5ebab425c7cccc4cd2ae36c44f3dad0bd5bb819084c0fbc5b27a61667dcb76db`。Codex 在自己的 `codex/ops-alert-rootfix-ci-20261109` 工作树使用同一既有生成器复现出完全相同的文件，保留 Claude 协作归因，没有另写生成逻辑或覆盖对方工作区。

旧 CI 分支通过正常 merge 纳入 `06c`；整合点 `84ad0f0d0534500688b9fa58751b2229459ce23a` 的 tree 与 `06c` 相同。派生模块修正为单文件提交 `76195fc24b41b8b02c2a606aa670834eef96f165`。六组原提交和冻结并发修复均保留在提交图中。

## 已证明的 CI 失败原因

Linux 运行 `42610034266` 的 systemd 249 兼容检查、运维定向测试和 Worker 测试通过，但 `python3 ops/monitoring/build_baseline.py --check` 以 2 退出，后续完整脚本与运维组合回归未执行。

F2 更新了 `docs/ops/architecture/inventory/data_assets.json`，并同步了 catalog 和 dashboard，却遗漏了另一个同源派生产物 `worker/ops_baseline.js`。只读固定 blob 对照证明：

- `8840` 的原始检查 exit 0；`06c` 的同一检查 exit 2，提示 server baseline differs。
- 生成器、configure 和其余八份输入未变；已提交模块仍对应旧输入。
- 差异只有 11 个叶字段：冻结表三处 evidence 的 location/code_ref/observed_at、write_contract，以及 data_assets 输入哈希。373 条源记录、370 个唯一记录保持不变。

这不是冻结并发逻辑再次失效，也没有证据表明是 Ubuntu 平台差异。修正复用既有生成入口，不手改派生 JSON，不降低检查标准。

## 生成和检查

```sh
python3 ops/monitoring/build_baseline.py --write-module
python3 ops/monitoring/build_baseline.py --check
```

改动 architecture inventory 时，除 `build_catalog.py --write` 外，也必须同步上述服务端模块。两套 `--check` 分别检查各自下游，不能互相替代。

本次本地生成后的 SHA-256 与 Claude 既有结果相同，11 个叶字段逐项、逐值吻合；baseline 检查 exit 0，11 个 Worker 模块语法检查通过，标准 pre-commit 实际执行且 exit 0。没有新增业务逻辑，因此未增加复述生成器行为的测试。

## Linux 与生产验收边界

baseline 阶段的固定 head 真实 Linux 运行由 `codex/ops-*` 分支推送触发现有工作流，该阶段没有修改 workflow、依赖或生产部署配置。须记录 `local-only`、`unit-compat` 两个 job 的实际结论，以及完整组合回归的原始末行。本文件不提前声明后续整合运行通过，最终结果与 head/SHA 在本轮不可变 master report 中固定后显式 publish。

原冻结并发 P1 在 `06c` 的独立复验为 34 项定向测试通过、四个真实双进程场景通过。历史 136 条缺冻、5 个交易缺口和 #373 两日缺备份没有因此恢复。NAV、指数稳定性和过拟合/指标跳变另做真实数据核查，不以任务 exit 0 或降低风险阈值销账。

生产自然轮次必须核实际运行版本。2026-11-09 22:18 的只读快照仍为旧版 `adfd77e7a`；21:00 备份和21:10 换手率服务的原生退出码均为 0，但这不代表本次尚未部署的六组代码生效，也不单凭退出码宣称全部产物交付通过。后续仍按 [验收清单](acceptance.md) 逐项留证，由 Claude 负责最终审合部署。

本轮私有证据根：`/tmp/codex-reports/alert-continue-authorized-20261109/`。原始失败、独立复验、前次交接和历史缺口边界均保留；不修改已经 publish 的报告文件。

## 接续业务缺陷与独立复核

1. **NAV 补采**：016989 的 Nov2 已有值却令 Nov3–6 的 NULL 被跳过，上游两条只读路径均已提供真实值。修正覆盖整个窗口及缺行，仅补缺不覆盖非空；500 只批次使用持久尝试轮转，空响应与异常也能推进到后批；`--fund-code` 可定向恢复，不推进全局轮转。最终分支点 `0c6de399f7565fa40016d7b644adfb74383d6cc8`。独立复核的预览锁截断 P2 已修；缺锁创建空协调文件是保留的互斥合同，不等同写库或游标推进。预览与恢复步骤见该项文档，本轮未在生产执行。
2. **过拟合交付**：云端 Nov9 已算出 74/red，而主/ext 公开数据仍停在 Nov6 的 70/red；旧上传超时后 rc0。现在精确上传两件，复用 data/global 锁和已有工作预算，整组回收超时子进程；实际上传失败与公开副本未确认分开返回。`publish-only` 不重新计算或重发模型预警，不能将公开缓存未确认说成 PUT 失败。最终分支点 `5b3ab1f3259deb7896e018677946660576041c77`。独立发现的 UTF-8 日志尾读 P2 已修并通过真实退出码/非法字节回归；历史具体 S3 卡点未证实，不宣称物理网络已根治。
3. **指数同源恢复**：基金入口单次网络错误直接返回 0；相同 SDK 在同机已可读 Nov9 三指数日线，历史 15 行 close/pct 与库逐值一致。复用现有原生恢复机制，并隔离全局 SDK 会话；中断半批丢弃后重查。没有搬用主库 intraday_snapshot 或引入另一行情源，原写库、指数映射及价格/涨跌口径保留。最终分支点 `e30d1c90a9482e754b802be202e9cd7d59b9875a`。独立发现的父退出后子查询存活 P2 已用匿名管道 EOF 生命周期守卫修复，mac alarm/早死/正常退出及旁观者均有实测。

上述三项最终固定 head 的独立复核均无遗留 P0/P1/P2。NAV 锁与指数函数共用 `app/collector/public_fund.py`；整合不是整文件覆盖，已独立比较 AST：最终模块精确等于指数分支模块加 NAV `_acquire_lock`，其余节点保持。NAV/overfit 文件也逐字节等于各自通过复核的版本。完整 Linux 组合回归仍按最终整合 head 另验，局部通过数不相加成全量通过数。

## 历史取证的实际完成边界

已补查云上已知备份/镜像目录、小 manifest、R2 日/周/月列表和小归档，并对精确历史前缀补查。两份 Claude 小归档各完整枚举 346 项，没有目标业务文件；新取得的历史信号与前次字节一致，不能当作新增可恢复 T0 证据。Nov3 早间周/月 public_fund 备份只确认元数据，不能替代 Nov1/2 原件。136 条缺冻、5 条交易缺口和 #373 均未因此销账。

为核 Nov3 A/F 指标突变，进一步在本机取回并解析两份完整交易候选，候选对比已执行；第三件精确 key 的 HEAD 当时返回 404。两份独立复算的指纹均不匹配目标 Nov2/3 快照，候选 n 为1549→1574，而目标为1549→1572，不能将候选增删或收益变化写成那天的权威原因。没有经生产云服务器转发大文件，没有修改收益、策略或历史快照；仍需可配对的生产运行身份/输入内容哈希。

当前 74/red 按原四维权重计算成立，真实高风险预警保留。2026-11-09 22:15 监控失败的实际记录为 TimeoutError，其快照 ID 在随后只读 OPS_DB 主库查询时未见；不能据这一例声称全因 D1 配额或已经送达。上线恢复、D1 完整 UTC 日与这些历史问题继续分别留证。

## 跨日收口与发布保护

Claude 已将冻结并发修复和相同 baseline 纳入 main `6e3b2ea06299d664cc67e676a0b73614d32f6634`；本接续分支正常 merge 纳入该主分支提交，没有覆盖对方工作树。该 main 的 Quality/Ops 两套 CI 通过、Pages 发布成功，CF 发布 `42649615746` 失败；公共 API 仅能证明 deploy 步骤 exit1，未提供具体 stderr，原因待有权限的 Actions 日志核实。

第一轮接续整合 `314e94e67aba19f9e7cf5aaa299553118b3a2f5b` 的真实 Linux run `42648725977` 为 4085 tests / 1 failure / 0 errors / 7 skipped。失败是新增 NAV 跨进程测试的裸子进程缺父 conftest 导入垫片，在相同依赖的最小 Python 环境复现为缺 `requests`。原分支追加 `b1f20bca27d96db15a07230f7bed0d9e0f7d6f9e`，仅修测试启动及文档；生产源码 SHA 和原公平续跑断言保持。旧红记录、最小环境红绿和独立增量复核另存，不用本地通过替代最终 Linux。

另一个实际历史问题是 main `8840` 的 Quality/Ops 均失败、CF/Pages 却成功；四个原始 run 状态由父任务直接读取 GitHub 公共 API 留证。该版本部署依赖图未接 CI，故新增 [同提交 CI 门禁](release-ci-gate.md)，限定同 SHA、可信 main、当前 attempt 成功，并在实际发布前复核。此处有意修改两个部署 workflow 及必要的 Ops 路径登记，与前述只同步 baseline 的阶段不同；不直接改生产配置。外部 CF Git integration 和检查到发布之间的竞态边界保留，不能宣称跨平台原子发布。

00:00 自然监控 snapshot `0c59e8cf-da8d-4059-9f92-da2d120b0f04` 原生 rc0，日志 delivery_ok=true/HTTP200，随后只读 OPS_DB 主库查询命中同一 ID。此轮投递已实证，不外推全部故障关闭。追加三项代码及各自然链验收继续按 [跨日验收交接](final-acceptance-20261110.md) 执行。

第二轮整合 `21c2780d547b1d7e4961a3945a413fc5233379ce` 的 Linux run `42654876589` 为 4156 tests / 2 failures / 0 errors / 7 skipped：NAV 重启用例已通过，新发布守卫遗漏现有机检登记表而被两个 registry 自检正确拦住。未改 checker、测试或豁免规则；原发布门禁分支追加 `3b7559258bea20389afc85eca6b1f9d774ff0ca3`，仅在 `docs/ops/machine-check-registry.md` 在运表新增一行七栏生命周期登记。修前主检/变异自检为 2 failed / 1 passed，修后与原71项发布门禁合跑 74 passed；首次排版放在表外仍红的中间记录也保留。最终整合另跑真实 Linux，不将这次局部通过当最终 CI。

同原分支另在 Ops workflow 的 push/PR 路径各精确登记 `docs/ops/machine-check-registry.md`，让这个实际机检输入后续修改会触发原检查，不扩大一般 docs-only 运行范围。新接线后相关组合仍为 74 passed；旧验证与失败文件不覆盖。
