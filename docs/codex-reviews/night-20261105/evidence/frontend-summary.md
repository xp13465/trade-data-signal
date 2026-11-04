# 前端辅助加载器正文超时实施摘要

源码已稳定。修改保留在指定 worktree，交主会话 review/commit；本 worker 未 commit、push、checkout、rebase、启动 Claude、真实网络请求或外发。

## 基线与改动路径

- worktree：`/Users/linhuichen/code/trade/.claude/worktrees/codex-frontend-timeouts-369-370`
- 分支：`codex/369-370-frontend-timeouts`
- 开工 HEAD：`37a4fa707`；已含 `origin/main aac5d19bd` 和先前 `04fd4a8c2`；开工工作区干净。
- 版本串前后均 `20261031-a654`，由主会话后续统一构建/发版。
- `static-site/lab.js`：仅 `_labKellyFetchTrades`（当前 L8679）内改动。
- `static-site/app.js`：仅 `_fundScoreApiFetch`（当前 L27802）和 `_fundScreenerApiFetch`（当前 L28721）内改动。
- 新增 `scripts/tests/test_frontend_aux_body_timeouts.cjs` 和同名 `.py` 包装。
- JS parser 分别移除授权函数后，HEAD 与当前文件其余部分逐字相同，见 `frontend-scope-verification.json`。
- 既有 27 例 cjs 和 py 包装均未修改。docs/index/CSS/min/SW/后端/版本号均未编辑；未动任何一跳生产函数。

## 实测依据与修复

旧实现 headers 到达就 clearTimeout，后面的 `return r.json()` 仍在读取正文时 timer 已不存在。测试直接提取并执行真实生产声明：唯一函数锚点 + `vm.Script` parser 判断完整函数；没有复制加载器实现，没有绝对 repo 路径，没有安装依赖。

新测试以原生 AbortController、Response、ReadableStream 模拟已收到部分 JSON 后正文停滞，用手动时钟推进既有预算；没有真实联网、没有等待实际 60 秒。

在生产源码修改前实跑最终 49 例：**41 通过、8 失败**。其中 5 个直接正文场景是 Kelly R2/CF/SSD 各 1 例和两个公募 API 各 1 例；另 3 个失败是同根因的 Kelly 三腿串行超时、无 SSD 的 CF 正文、真实 Retry caller 退避场景。失败的实际现象是时钟越过原预算后 signal 仍未 abort/请求仍 pending。

修复复用已有 Promise 链，将每腿清理放到跟随 JSON Promise 的 `finally`。无需新增 await/请求框架；成功、HTTP 错、JSON 错、网络错、headers/body 超时均统一清理，Kelly 前一腿清理后才开始下一腿。删去无副作用的 catch 重新抛出，保持错误对象/文案向上传递。

保持预算：Kelly 每腿 60000ms，R2→CF→SSD 三腿各自独立 controller；三腿正文全停滞虚拟耗时正好 **180000ms**。两个 API 仍各 15000ms。认证 headers、credentials、cache 参数、正常 payload、回退先后不变。

## 验证数字与命令

- `node --test scripts/tests/test_frontend_aux_body_timeouts.cjs scripts/tests/test_frontend_request_timeouts.cjs`：**76/76**（新增 49 + 既有 27），0 fail/cancelled/skipped。
- 最终测试再次放入临时目录，生产源改从开工 HEAD 只读取出：仍 **41/49 通过、8 失败**，证明最终测试对旧缺陷有判别力。临时目录使用系统 TemporaryDirectory 正常回收，未切换或覆写 worktree 源码。
- 两个定向 Python 包装：`python3 -m pytest -q -p no:cacheprovider scripts/tests/test_frontend_aux_body_timeouts.py scripts/tests/test_frontend_request_timeouts.py`：**2 passed in 1.33s**。
- 两个 JS 整文件 `node --check` 和 `git diff --check` 通过。
- 最后 Node 合跑从 `/tmp` cwd 执行，ROOT 由测试文件位置解析；可移植性不依赖 repo 的绝对路径。

覆盖：三条 Kelly 腿逐一正常/HTTP/坏 JSON/网络失败/headers 停滞/body 停滞；没有 SSD 映射；三腿串行停滞；真实 Retry caller 原 1000ms 退避；两个 API 主/备站认证与缓存参数；所有请求 timer 清理。手动时钟同时断言预算前 1ms 还未 abort、到预算即 abort。

取消实证执行实际 `fetchJSONProgress → fetchJSON` callee：正常正文取消、HTTP/JSON 失败后正文取消、超时交接后的 CF/SSD 正文取消、预取消、SSD 优先竞速同时取消，均没有取消后新请求/重试，并核对原生 abort 监听与在途 Map 已清。另核对真实 fetchJSON 的正常 payload/成功缓存/在途去重。

**这三个辅助加载器自身没有外部 signal 或用户 cancel 入口**，生产 caller 也未传信号。没有为测试增加不可达的取消 API；Kelly 的内部 timeout 后重试仍按原有 Retry caller 逻辑处理。

## 同类扫描与边界

扫描命令：`rg -n --glob '*.js' --glob '!*.min.js' 'clearTimeout|setTimeout.{0,100}abort|return (resp|response|r)\.json\(' static-site`，并读涉及 timer 的函数及 caller；另扫 JS/HTML 全部 `clearTimeout` 和 index 内联请求。覆盖 rg 可见的 **17 个非 min JS/HTML 源文件**，不涵盖 gitignored 数据/生成产物。原始命中见 `frontend-pattern-scan.log`。

| 模式 | 结论 |
| --- | --- |
| `_labKellyFetchTrades` R2/CF/SSD，两个 fund API | 已确认且可达的同根因，共三个函数五条腿，本轮已修 |
| `fetchJSONProgress` 无长度正文 | 先前 04fd4a8c2 已 await；本轮真实链取消验证通过 |
| `fetchJSON` 普通/回退/竞速正文 | 清理前已 await；实际 callee 取消/缓存验证通过 |
| lab 三个 EnsureFull、app 分时/批量请求、跑马灯 `_gtAbort` 消费点 | 已 await 正文/下游加载后 finally 清理，不是提前清 timer |
| common `_gihNavFetchFn` | 原生 AbortSignal.timeout，没有收到 headers 就撤销 signal 的逻辑 |
| inline-init 探活 | 请求 method=HEAD，仅检查状态与类型，没有 JSON 正文消费 |
| index boot 预取 | 既有链的 finally 等 json()，未改；既有 27 定向用例通过 |

本次覆盖中**没有另外确认且可达的同根因授权外项**，无需扩大修改。单纯缺少超时的裸 fetch 与本次提前清 timer 根因不同，未据此新增问题或擅改。

七轴边界：输入域（正常/HTTP/坏 JSON/网络，测）；状态组合（主备认证/无 SSD/缓存与在途，测）；时序（预算前后/部分正文/交接取消，测）；上下游依赖（真实 Retry 和真实 fallback callee，测）；极端值（三腿全停滞/预取消，测）；回退路径（三源顺序/无 SSD，测）；并发重入（真实去重和竞速取消，测）。大数据吞吐、浏览器真实 HTTP 流、完整页面视觉不由本定向 Node 测试结论外推。

## 假阳性与限制

- 初版监听计数包装无法反映原生 `{once:true}` 自动移除，导致多报 1 项失败；已改用 `node:events.getEventListeners` 真读原生监听。初版日志保留 `frontend-red-harness-initial.log`，该失败不是生产缺陷。最终红数为 8，绿数为 49。
- 只读范围核验初次碰到 Node execFileSync 默认输出缓冲上限 ENOBUFS；增加本地读取 maxBuffer 后完成逐字范围核验，未涉及源码变更。
- 不声称已经观测到线上真实正文卡死；证明的是在真实生产函数遇到构造的可达流停滞时，旧代码越过预算仍挂起、新代码在原预算 abort。
- 浏览器 worker 后续验证，主会话后续统一完整 pytest/候选 min 构建；本 worker 未执行这些步骤，也未部署。
- 后续发现工作区存在别人新增的 `docs/codex-reviews/night-20261105/`，未写、未覆盖、未删除，不包含在本 worker 交付文件中。

原始日志：`frontend-red.log`、`frontend-red-final-tests.log`、`frontend-green.log`、`frontend-existing-baseline.log`、`frontend-combined.log`、`frontend-pytest.log`。机器核验：`frontend-verification.json`、`frontend-scope-verification.json`。生产 diff：`frontend-final-diff.log`。进度：`frontend-progress.md`。
