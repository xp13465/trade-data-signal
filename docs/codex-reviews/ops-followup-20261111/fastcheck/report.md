> 原始取证目录：`/tmp/codex-reports/ops-followup-20261111/fastcheck`，另有只读私有归档。下文原始响应、完整 JSON、merge-tree 和 fixture 引用均指该证据目录；仓库仅保存审计正文与脱敏结果。仓库日志统一换行并去除行尾空白，原始字节保存在私有证据目录。

# Findings

## [P1] FC-01 push 重试在快检后 rebase，未重验就再次 push — `61a56ce7f:scripts/main-merge.sh:895`

`origin=pre-existing` · `scope=in-scope`

**Impact**：并发更新 origin/main 导致第一次 push 被拒时，两侧各自有效的纯文档变更可经无冲突 rebase 组合成无效文档，第二次 push 绕过所有本地发布前检查。7.10 不能保证最终推送树满足三项快检。

**Why**：新增 7.10 只在 658–708 执行一次；原有 892–896 重试会在其后修改整个树并直接 push。当前 main 对应 811–815；该重试从 b74368b5a8731cb7d3c9a6bf69cd3c81ebd426d3 已存在，不归因为本次新引入的 set-e 回归。新增闸门未覆盖这条既有路径。

**Fix**：最小修复是 push 失败后停止，由主控更新基线后重新走完整入口；若保留自动 rebase，必须在新树上重跑所有会受树变化影响的检查再允许 push，不能只移动 7.10 到第一次 push 前。不得自动静音失败。

**Trace**：41c567e6aabbfec13af0d310bcc08df59194fdbf..61a56ce7fc037e0a9f8ce8aad018ee1c173edd95:scripts/main-merge.sh 新增 632–708（执行 658–708）；既有重试 61a56ce7fc037e0a9f8ce8aad018ee1c173edd95:892–896 / f35437a699d199076b5654dcde58780be89ee6b4:811–815；需求关联「不满足」。用户要求：Review ... full execution ordering ... Verify whether gate is before final gate-affecting file mutations

**Verifier**：`python3 /tmp/codex-reports/ops-followup-20261111/fastcheck/audit_harness.py ; inspect logs/retry_local_individual.log, logs/retry_upstream_individual.log, logs/retry_rebase_bypass.log`

**Expected**：rebase 改变文档后，重复 #499 应在第二次 push 前被重验拦下，或第一次 push 失败即退出。

**Observed**：真实当前 main 文档为基底；两条隔离 Git 分支各自三检通过；抽取的原样 7.10 + 原样 push 重试块在 set -euo pipefail 下执行。真实本地 rebase 成功、唯一一次快检后出现 SIMULATED_PUSH_ATTEMPT=2；事后 task_state rc=1，#499 在第 3、604 行重复。push/fetch 为本地桩，无网络/真实推送。

**简化建议**：复用完整入口：把 6 行自动 fetch/rebase/再 push 分支缩为约 4 行醒目错误+退出，约省 2 行并去掉未重验的第二发布路径；保留人工重跑而非复制三项快检。历史追踪已确认这是原始重试设计，修复需主控决定。

## [P2] FC-02 固定分支与两条集成基线都有文档合并冲突 — `61a56ce7f:docs/pending-features-index.md:551`

`origin=in-diff` · `scope=in-scope`

**Impact**：该固定 head 不是可直接无冲突合入的交付；选择整文件 theirs 会丢失当前 main 的 #379–382 和后续进展/恢复证据。

**Why**：分支在共同基线后追加 #378 与 NOTES 段，而 main/delivery 在相同位置已有不同后续记录。两次只读三树 merge-tree 都在 NOTES.md、docs/pending-features-index.md 产生冲突标记。脚本本身可直接取待审 blob；registry 文本合并没有冲突标记。

**Fix**：由 Claude 在实施分支解决两文件冲突：保留 current-main 的记录并加入 #378/7.10 补记，形成新的固定 head 后重验三项快检及集成检查；本审计不替主控消冲突。

**Trace**：41c567e6aabbfec13af0d310bcc08df59194fdbf..61a56ce7fc037e0a9f8ce8aad018ee1c173edd95:docs/pending-features-index.md:551; NOTES.md:8587–8593；需求关联「不满足」。用户要求：Also evaluate merge compatibility with current main by read-only git merge-tree if safe but no -w writing shared git

**Verifier**：`git merge-tree --trivial-merge 41c567e6aabbfec13af0d310bcc08df59194fdbf f35437a699d199076b5654dcde58780be89ee6b4 61a56ce7fc037e0a9f8ce8aad018ee1c173edd95; git merge-tree --trivial-merge 41c567e6aabbfec13af0d310bcc08df59194fdbf 0ad6556b58fabff4bce06ed291904f88b573c0f6 61a56ce7fc037e0a9f8ce8aad018ee1c173edd95`

**Expected**：可直接无冲突合入时不应出现 <<<<<<< / ======= / >>>>>>> 冲突标记。

**Observed**：两次命令均 rc=0，但各有 2 个文件冲突标记：NOTES.md、docs/pending-features-index.md。legacy --trivial-merge 的 rc=0 不代表无冲突。完整输出见 merge-tree-main.txt / merge-tree-delivery.txt。

# Open Questions / Residual Risks

- **全脚本 dry-run 非只读**（pre-existing）：61a56ce7fc037e0a9f8ce8aad018ee1c173edd95:216 无条件 fetch、239 条件 rebase、315 checkout main，未受 DRY_RUN 保护。7.10 自己只读且 FAIL 不阻断，但完整 --dry-run 不能用于本次只读审计；此处为静态边界说明，未执行完整入口。
- **dry-run 只查旧树**（in-diff）：61a56ce7fc037e0a9f8ce8aad018ee1c173edd95:324–325 跳过 merge，654–656 已披露边界；7.10 不因 dry-run 预测 feat 内容。dry_old_tree 仅证明当前 fixture 可通过，不声称合并预检。
- **显式逃生门**（in-diff）：只有 MAIN_MERGE_SKIP_FASTCHECK=1 跳过三检并醒目告警；true 不生效。MAIN_MERGE_SKIP_PYTEST 独立，不能代表快检跳过或通过。dry-run/skip 的 rc0 是允许继续，不是验证通过。
- **已披露覆盖盲点**（in-diff）：7.10 registry 自身行删除仍三检成功；独立复现，分支文档已准确披露，不重复列新缺陷。三项快检不是全部文档驱动 CI 规则的完备集。
- **WARN 不阻断**（pre-existing）：task_state 默认非 strict，超范围编号只 WARN 且 rc0；7.10 成功分支隐藏详细 stdout，只显示通过。warning_only 已复现，与 CI 默认退出码语义一致。
- **未提交文档/并发更改**（uncertain）：三检查读工作树，不把结果绑定到最终提交树。未覆盖未提交修复、外部并发写、定制 hook 等所有路径；不能以本 harness 排除这些剩余风险。

# Checks

固定 head `61a56ce7fc037e0a9f8ce8aad018ee1c173edd95`；current main `f35437a699d199076b5654dcde58780be89ee6b4`；delivery `0ad6556b58fabff4bce06ed291904f88b573c0f6`；共同基线 `41c567e6aabbfec13af0d310bcc08df59194fdbf`。

7.10 的 set-e 修复及常规纯文档拦截符合所测语义；保留1项P1既有排序缺口及1项P2集成冲突。24/24 harness断言符合预期，其中包含漏洞和盲点的成功复现，不是24项产品测试全绿。

复现：`python3 /tmp/codex-reports/ops-followup-20261111/fastcheck/audit_harness.py`。完整逐例退出码及期望见 [test-results.json](test-results.json)，日志见 `logs/`。最终完整执行计数：22 项快检相关用例 + 1 项真实隔离 Git rebase 的重试反例 + 1 项全脚本 bash -n = **24 项，24 断言符合预期，0 断言失败**。另执行 2 次只读 merge-tree；不计入 24 项。

## 全执行顺序（固定 head 行号）

- `55; 161–352` **入口 → 同步 → merge**：set -euo pipefail；同步基线/feat；真实 merge 后脚本改变时 exec resume。当前 main 已有自更新逻辑，因此正常安装后应加载新 7.10；仅静态追踪，未运行整入口。
- `368–478` **build/bump/changelog**：已知源码产物写入在快检前；主要写 min/html/sw/__build/changelog，不改三检的 ledger/TASKS/pending 读集合。
- `480–630` **其它前置门禁与 pytest**：前置校验可能提前阻断；7.9 检测不到 scripts 变更时跳过 pytest。7.10 在其后无路径过滤，pure_docs 反例证明可拦文档错误。
- `658–708` **7.10**：三条脚本默认根均解析到 REPO；与当前 main/delivery 的三条脚本字节一致。if/else 安全捕获失败码并继续执行剩余项目，统一 exit11，dry-run仅告警，skip=1明确绕过。
- `722–887` **console/销账提醒/commit**：console 是线上只读探测；pending 提醒只读；bump 产物 staging/commit 在快检后。已读当前已安装 pre-commit 与固定模板：对 staged sh/py 执行 lint，无文档自动修复。普通无并发路径未发现这些阶段会改三检文档。
- `892–896` **push失败 → fetch/rebase → 再 push**：最后一个已证的 gate-affecting 树修改在 7.10 后；新树无重验。FC-01。
- `900–961` **云同步与CI自查**：发生在 push 后，不提供 push 前阻断保证；未执行。

## 限制

- 未执行真实 main-merge.sh；没有共享 Git refs/source/index 更新，没有 main mutation、真实 fetch/push/rebase、网络、通知、ACK、publish、子代理或 live telemetry。唯一 Git 写操作在本目录的隔离合成仓。
- 不是完整生产路径或完整 CI/pytest 验收：没有运行上游全量 pytest、build/bump、其余前置校验、在线 console、云同步或 CI 自查。作者 commit 中的 3736 等历史数字没有纳入本次通过数。
- 测试用了 200 份精确固定提交文件副本（含真实当前 main 的 ledger/ownership/TASKS/pending/registry/CI 文档、全部非 tests check_*.py 和登记挂点文件），不是整个仓库。三条校验脚本无需 Git 历史；retry 反例另用完整本地合成历史，不冒充生产提交历史。
- reconciled_main/reconciled_delivery 仅在临时 fixture 保留当前文档并加入 registry 行与 #378，同时替换为固定 head 的 main-merge；不等于实际 merge、冲突处理交付或完整合并树。NOTES 不在三校验读集合，未在该候选 fixture 中合成其最终文案。
- merge-tree 使用无写对象的 legacy --trivial-merge 三树模式；未执行现代 ort 真实 merge，结果只作为文本冲突/兼容性证据，非可发布树或实际合入结果。
- 仅 Bash 3.2.57 / Python 3.11.0 本机验证；未运行 Linux Bash/CI。完整 harness 最终一次为 24 项；之前有两次搭建中止（/tmp 在 macOS resolve 到 /private/tmp 的断言、ledger 固定计数初值错误），第二次在前 6 项后停止，均已更正，不另算通过数量。

# Verdict

**BLOCKED（仅本范围）**。既有重试排序缺口尚未处置，固定分支还有两处文档冲突。不能据局部 harness 给完整生产路径、最终合并树或 delivery 独立 PASS。
# Summary

set-e 修复有效，正常纯文档错误可前移拦截；但快检早于失败重试中的最后一次树修改。所有产物仅在指定 `/tmp` 目录，源码、共享 refs、原 packets 均未修改；未发送通知/ACK/publish。
