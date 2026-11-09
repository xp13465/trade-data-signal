# 发布前等待同一提交的 CI（实施说明，2026-11-10）

本次用户特批 Codex 在专属 `codex/ops-release-ci-gate-20261109` 分支实施、测试和 commit，**不 push、不部署**；Claude 最终独立审查、整合和 Linux CI 验收。固定 base 为 `314e94e67aba19f9e7cf5aaa299553118b3a2f5b`。用户最新授权覆盖索引 #372 的历史“不改”决定，本次不改索引、版本串或业务源码。

## 问题与可验证的预期

历史事故锚点为 `8840c79d70de4bf58376bcdbd9bc13239ad17781`：用户提供 CI Quality `42643233649` failure、Ops `42643233652` failure，同时 CF `42643233697` success、Pages `42643233655` success。本机尝试四次只读 REST 获取均为 URLError，浏览工具也无法打开这些 API URL，故这组运行状态**属于用户提供的证据，未冒充本次在线独立复核**。

最新同步：父任务报告 main 已到 `6e3b2ea06299d664cc67e676a0b73614d32f6634`，两套 CI success、Pages success、CF `42649615746` failure。**历史两红不是当前状态**；此次不诊断或处置 CF 生产故障。

源码独立核实：base 的 CF deploy 无 `needs`，Pages deploy 只 `needs: build`，三套 workflow 独立触发。CI 红不会影响原部署依赖图。预期改为：同 SHA CI 不成功就不能进入部署；CI 排队必须等；旧 SHA、旧 attempt、PR/fork 绿均不算；发布前 main 已前进必须阻断。测试同时保留旧结构反例及新结构/实际 helper 的拒绝行为。

## 最小实现与边界

- 两个部署保留原 `push/main`、原路径过滤、`workflow_dispatch`、构建、并发配置和实际部署步骤。新增只读 `ci-gate`；CF `needs: ci-gate`，Pages `needs: [build, ci-gate]`，Pages 构建仍可并行。
- 所有 checkout 固定 `${{ github.sha }}`，不持久化凭据。守卫还对比 `git rev-parse HEAD`、事件 SHA、源仓库身份、`refs/heads/main` 和 REST 当前 main。
- 共享 `scripts/check_release_ci_gate.py` 用标准库读 REST，复用已用于 CI 的 PyYAML 解析 Ops push 路径规则（BaseLoader 避免 YAML 1.1 把 `on` 读成布尔值）。两个门禁 job 及两个临发布复核共用这一实现。
- CI Quality 始终必需；Ops 在 push 精确 `before...sha` compare 命中原 push paths 或已有可信同 SHA 运行时必需。多 commit push 比较整个范围；不拿最后一个 parent 代替。
- 只有已确认的祖先比较、完整且少于 300 条文件记录、受支持的正向路径规则，才允许判定 Ops 未触发。rename 同时检查新旧路径。新分支零 before、manual 缺 before、非祖先比较、达到 300 文件上限、至少 1000 commits、未知规则均保守要求 Ops 成功。API 不可读、字段缺失和分页不完整直接拒绝。
- 路径匹配只支持仓库现用字面路径、单层 `*`、完整路径段 `**`；负向模式、`?`、字符类、组合 `a**b` 不猜语义，要求 Ops。没有把全部 docs-only 推送扩大为 Ops，也不重复启动 CI。
- workflow 文件名限定 REST 查询；head SHA、main 分支、push/manual 事件、源仓库/head 仓库和 workflow path 均校验。读取完整分页（1000 上限视作未知），按最近 `updated_at`、run ID、attempt 选取；较旧 run ID 的新重跑也能优先于较新 ID 的旧绿。再 GET run 的当前 attempt，禁止用 `/attempts/<旧绿>` 替代。非 success 终态均阻断。
- 已有运行的完成等待最多 2100 秒，job 40 分钟提供安装和网络余量；push 下必需运行不存在的发现等待单独限为 120 秒，manual 缺必需运行立即拒绝并提示补跑；等待包括 queued/pending/waiting/requested/in_progress。发布动作前再次运行同守卫 `--timeout 0`，防构建期间 main 前进、CI 被重跑或新运行失败；此复核不等待未完成 CI。

权限：新增仅 `actions: read`，原 `contents: read` 保留；gate job 显式限制两项只读权限。Pages 原 `pages: write` / `id-token: write`、CF 原 secret 和发布命令均保留。令牌仅以步骤环境变量传入，不输出环境或响应正文，成功输出只有 head 和安全摘要。没有 GitHub 写 API、workflow_run、新服务、定时器、审批流程、消费者或通知。

Ops 仅在 push/PR 原列表各登记四项：守卫、专用测试、两个部署 workflow。`ci.yml` 未改；原 Ops 测试范围不变，其全量脚本回归自然包含新测试。

## 人工补跑方法（这里不执行）

1. 确认要发布的 SHA 仍是 main 当前 head。在 Actions 找到该 SHA 的 CI Quality Gate，使用 **Re-run all jobs**；CI Quality 目前没有 workflow_dispatch，不能凭空 dispatch。若从来没有该 SHA 的 CI，必须通过主控正常 main 提交流程产生可验证的 CI，不能绕门禁。
2. Ops 运行失败则重跑；若 manual、未知 compare 或路径规则导致要求 Ops 但没有运行，在 Actions 的 **Operations monitoring checks → Run workflow → main** 手动补跑。同 SHA/main 的手动结果可以被守卫验证；有较晚活动的失败/排队运行时，不能拿更早的绿替代。
3. 两套必要 CI 成功后重跑部署 workflow；手动发布仍要求 Ops。main 已变动就发布新 main，不能把旧 head 部署到当前站点。

## 自测与七轴边界清单

全部新测试使用伪 REST/临时事件，不访问 GitHub、不真部署、不做生产网络故障注入。

| 维度 | 是否测及依据 |
| --- | --- |
| 输入域 | 测：push/manual、零 before、docs/代码路径、rename、未知路径语法，来自触发范围要求 |
| 状态组合 | 测：CI/可选 Ops，成功、失败、取消、超时、skipped/neutral、运行缺失，来自 fail-closed 要求 |
| 时序 | 测：多 commit push、排队后成功、等待超时、构建后 main 前进，来自整个 push 和临发布复核要求 |
| 上下游依赖 | 测：API 403/不可读/字段缺失，旧 needs 反例、新 needs 和固定 checkout，来自事故根因 |
| 极端值 | 测：299/300 文件、1000 commits、分页第二页、列表上限，来自 REST 截断要求 |
| 回退路径 | 测：无 before/未知路径只能要求 Ops；CLI 明确补跑提示，不允许缺结果跳过 |
| 并发与重入 | 测：当前 attempt 覆盖列表旧绿、新 run、旧 ID 新重跑、新 main；不做真实并发部署，父 Linux CI 验收平台行为 |

复用与精简：检查现有 `scripts/lib/ci_selfcheck.sh` 的目标是推送后告警，允许未知结论 warn，不能作为发布 fail-closed 守卫直接复用。使用标准库 HTTP/时间/JSON/正则，复用已有 PyYAML 依赖和原 Ops 路径列表；两个真实部署使用同一脚本，无额外配置源或服务抽象。

验证原始输出位置：`/tmp/release-gate-focused.log`、`/tmp/release-gate-full-pytest.log`（首次 42 秒中断）、`/tmp/release-gate-full-pytest-final.log`、`/tmp/release-gate-full-pytest-final.status.json`（被最终代码轮次替代）、`/tmp/release-gate-exact-full.log`、`/tmp/release-gate-exact-full.status.json`、`/tmp/release-gate-commit.log`。最终计数与固定 head 以原子 JSON 实施报告为准。全量回归在最后补“缺运行 120 秒／manual 立即拒绝”前已启动，按父要求保留该次收尾、不追加全量；最终行为以 71 项定向测试覆盖，最终 Linux CI 由父统一执行。

## 已知兼容风险与范围

- 只改两个 GitHub Actions 入口。CF 源文件注释声明外部 Git integration 仍可独立部署；本次未验证该外部配置的当前启用状态，也不改变生产设置。**不能据此宣称所有 CF 发布通道都受本守卫保护**，父任务应单独确认该范围。
- REST 观察与实际部署不是原子事务；发布前再次检查缩小竞态窗口，检查通过之后发生的新 push/CI 重跑仍可能与正在提交的部署重叠。两 workflow 保留既有并发策略，不宣称提供跨平台事务锁。
- 网络不可读、pip 安装失败、未知路径模式或大型 compare 会增加保守阻断；manual 需要 Ops 补跑。这是明确的 fail-closed 行为，非静默跳过。
- 本机 mac 测试不等于 Linux CI；作者不 push，父独立审查并安排最终 Linux CI。既有 CI 内部 continue-on-error 的含义不由本次改动重定义，守卫以 workflow success 为准。

## 官方契约（实施前已读取）

- [Workflow syntax：needs、permissions、paths 与 push 比较](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax)：needs 使部署依赖门禁结果；权限按 job 缩小；保留路径触发。
- [Workflow runs REST](https://docs.github.com/en/rest/actions/workflow-runs)：按 workflow 文件名、head_sha 查询，分页并读当前 run/attempt，需 Actions read。
- [Compare two commits](https://docs.github.com/en/rest/commits/commits#compare-two-commits)：`BASE...HEAD` API，文件列表只在第一页、整个比较最多 300 个文件；需 Contents read。
- [Get a reference](https://docs.github.com/en/rest/git/refs#get-a-reference)：`heads/main` 读取当前 ref，需 Contents read。
