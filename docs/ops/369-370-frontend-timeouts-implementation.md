# #369 / #370 前端请求超时修复

## 授权与交付边界

- 用户在明确分工后回复「可以 授权」，本轮临时由 Codex 实施 #369 / #370；Claude 负责独立审核、合并和部署。此授权不修改 Codex 的长期角色规范。
- 分支：`codex/369-370-frontend-timeouts`。开工基线：`8b2f291ab8d1782574cf0774f1686ef82b61527a`。
- 交付前同步到 `e05474a5ce897a96f299a57714a8618c5ec2478a`（含 S01/S02 注释与证据订正）；任务索引冲突按行处理，保留上游 #369 原始实测口径和其它行，只补 #369/#370 的实施状态。
- 独立工作区：`.claude/worktrees/codex-frontend-timeouts-369-370`，未修改主工作区。
- 只修请求生命周期；不改 CSS、布局、回测算法、数据、后台任务或发布流程。
- 未自行 bump 版本串或提交生成的 min 文件。合并由 Claude 通过 `main-merge.sh` 统一构建、bump、检查并上线。
- 版本串前后：`20261031-a654` → `20261031-a654`（功能分支保持，正式新串由 Claude 合并时分配）。

## 依据、实现与预期

### #369：无 Content-Length 的正文读取

`fetchJSONProgress()` 原来直接 `return resp.json()`，异步函数会先执行 `finally`，提前移除超时计时器和外部取消监听。响应头返回后，正文仍可无限等待，用户取消也不能传递到内部请求。

改成 `return await resp.json()`，在正文读取完成或失败后才清理。保持现有超时后 `fetchJSON()` 交接、外部取消不重试的语义。JSON 正文解析失败也进入原有异常回退；有 Content-Length 的流式分支保持原逻辑。

实际调用链自验还复现了一个取消缺口：损坏 JSON → `fetchJSON()` 主源 503 → SSD 正文停滞，此时外部取消只 abort 首腿，SSD 会继续等自身超时。为完整交付 #369 的取消语义，本分支同步修改 `app.js:fetchJSON()`：登记当前回退/竞速控制器，用户取消时全部中止，并阻止取消后启动下一腿；竞速产生的 AggregateError 在外部取消时归一为 AbortError。正常首腿超时仍可使用新的 SSD 控制器回退，正常竞速成功不变。URL、预算、缓存、in-flight 去重及其取消所有权保持。

影响面：`fetchLabFusionSimFullData()` 和 `fetchLabSimFullData()` 均调用该共享函数；调用方的 60000ms 参数及既有回退链不变。

### #370：主站 boot 预取

`index.html` 在主站/localhost 使用 `firstMs=0` 绕过计时器；`app.js` 的 `_bootJSON()` 等待该 Promise，主站挂起时到不了 SSD 备用或既有错误处理。

主站/localhost 首腿改为 15000ms，与 `fetchJSON()` 当前默认预算一致；备站首腿 8000ms、SSD 6000ms 保持。删除 `grab()` 的无期限旁路，计时器覆盖响应头和 JSON 正文。

**预取阶段**最大预算分别为主站 21000ms、备站 14000ms。预取两腿都失败后仍由 `_bootJSON()` 进入原有 `fetchJSON()` 链，该链另有预算；不能把前述数字当整页加载 SLA。

正常预取仍由一次 `_bootJSON()` 消费复用；URL、备用映射和备用站优先闩逻辑保持。F06 的真实修复载体是 index 内联脚本；app.js 本轮修改属于上述 #369 取消链，验收时分别核对。

## 复用与边界

复用已有 AbortController、finally 清理、grab/SSD 备用和 fetchJSON，不新增请求封装或依赖。两处原始根因为缺少 await 与无限首腿预算；同链路的辅助控制器取消登记一并补齐。

| 维度 | 本次覆盖 | 来源 |
| --- | --- | --- |
| 输入域 | 测：无长度/有长度 JSON、正常与损坏正文 | #369 正文分支 |
| 状态 | 测：正常、已取消、读取中取消、内部超时 | #369 超时与取消 |
| 时序 | 测：响应头停滞、响应头已到但正文停滞、完成后清理 | 两项 timer 生命周期 |
| 上下游 | 测：真实共享函数、HTML 预取与真实 `_bootJSON()` 消费、真实 fetchJSON 回退/竞速取消 | #369 实际调用链、#370 消费链 |
| 极端值 | 测：正文一直不结束、两条预取腿都挂起 | 两项挂起复现 |
| 回退 | 测：内部超时交接；用户取消不重试；SSD 成功/失败 | #369 交接、#370 SSD |
| 并发与复用 | 测：双腿竞速取消与正常胜出、预取+一次消费只有一个底层请求 | 辅助控制器改动、#370 复用 |

不测：多次 `_bootJSON()` 消费及多订阅者取消所有权（本次未改现有去重契约）；无 AbortController 的旧浏览器（现有加载器已依赖它）；全站视觉、Service Worker 升级和真实弱网时长（此分支不发版，需合并部署后另验）。不把这些范围写成已通过。

测试用手动计时器触发原始预算，避免靠几十毫秒的墙钟竞争判断超时；AbortController 为原生对象。pytest 包装将 Node 回归接入现有 CI 的 `scripts/tests/`，不引入新依赖。

## 实际验证记录

- `node --test --test-reporter=tap scripts/tests/test_frontend_request_timeouts.cjs`：27/27，通过。旧 lab/index 对照为 11 通过 / 11 失败；补真实 fetchJSON 组合后，旧 app.js 恰好 3 个取消用例失败。反向验证证明测试能检出两处原始问题及辅助腿取消缺口。
- Playwright 本地真实 HTTP/原生 fetch：Chromium 147.0.7727.15，桌面 1440×900 和手机视口 390×844，共 14/14。覆盖头部/正文挂起、用户取消、SSD 正文阶段取消、正常返回与 boot 预取复用；无外网请求，服务/悬挂响应/连接全部释放。取证于 rebase 前，四份生产源码 SHA256 与 rebase 后文件逐一相等。
- 浏览器计时器按 0.02 倍缩放并记录原始预算；这是生命周期验证，不是 15 秒真实弱网性能基准。WebKit 未安装，Safari/真机未验；不能用手机视口结果替代这些兼容性验收。
- 实施自查发现 SC-01 后已修正并补测；续查原生 Response 的 11 个边界及额外 Chromium 3 个场景通过。它是实施自检，不能代替 Claude 独立审查。
- 使用现有 `scripts/build_min.py` 的 `_minify_js_content`，对最终 app.js/lab.js 构建 `/tmp` 候选产物，再 `node --check`：两者通过；候选大小分别为 1,093,504 / 568,287 字节。没有写入仓库 min 文件，没有把语法检查当作上线验证。
- `check_task_state.py --repo "$PWD" --deploy-mode --skip-zombie-crons`：2 OK、0 warn、0 fail。`check_version_consistency.py --checks 1,2`、app/lab/验收脚本语法和 `git diff --check` 通过；校验3（正式源/min 一致）留到 Claude 统一构建时执行。
- 第一轮完整 pytest（两处原始修复、尚未补 app.js 取消链）：2280 passed / 3 skipped / 1 warning，295.93s。最终版本完整回归另记于下项，不沿用首轮结果冒充最终验证。
- 最终完整 pytest（含 app.js 取消链、同步 main 后）：`python3 -m pytest -q scripts/tests/ -p no:cacheprovider`，2280 passed / 3 skipped / 1 warning，331.44s，退出码0；源码测试前后 SHA256 一致。3 条为跳过，非失败；warning 是既有 `bump_asset_version.py:84` 的转义字符弃用提示。使用隔离 .env/dummy R2，网络标记测试关闭，未读取生产凭据。
- 上述为本地 macOS、Python 3.11.0 / pytest 9.1.1、Node 25.7.0 的结果；尚未取得本次分支 GitHub CI 或合并点 CI 结论。不能据此提前宣告线上修复完成。

定向脚本、pytest 包装及浏览器验收脚本均随分支提交；本机原始日志/JSON/截图保存在 `/tmp/codex-reports/implementation-369-370/`（非永久归档）。关键证据为 `node-green.log`、`pytest-final-full.log`、`pytest-final-result.json`、`browser-final/summary.json`、`selfcheck-followup.json`、`min-build-result.json`。需要保留原始附件时，Claude 可在复核时归档，不另起自动编辑消费者。

复跑入口（仓库已有 Python 测试依赖、Node；浏览器入口复用已有 Playwright，不下载浏览器）：

```bash
node --test --test-reporter=tap scripts/tests/test_frontend_request_timeouts.cjs
python3 -m pytest -q scripts/tests/test_frontend_request_timeouts.py
# NODE_PATH 指向已有 playwright 所在 node_modules；FRONTEND_EVIDENCE_DIR 可指定独立输出目录
NODE_PATH=/path/to/node_modules node scripts/playwright-accept/accept_frontend_request_timeouts.mjs
```

## 同类排查与范围外事项

- index 的 grab 返回 Promise 链并在最终 finally 清理，本次补预算即可，不需要复制一套正文读取器。
- `fetchJSONProgress()` 的三条 fallback 返回原 `fetchJSON(url, timeoutMs, signal)`；后者自有预算，本次补齐该 signal 在辅助腿上的传播，不把第一条请求的 timer 延长到它上面。
- 同类扫描还看到 `_labKellyFetchTrades()` 的三条分片腿，以及 app.js 的 `_fundScoreApiFetch()`、`_fundScreenerApiFetch()`，存在正文读取前清除计时器的存量写法。这些是其它入口，需 Claude 另行复核；本次未修改，不声称全站所有加载器均已修复。
- 同模块 #326 的域名/目录映射及 #327 的错误上报、版本收敛保持；不引入旧 `feat/fix-258-s06-budget` 分支的前端差异。
- 开工时所有现存工作区在 lab.js/index.html/app.js 均无未提交修改，未见活跃前端实施分支。

## Claude 接续检查

1. 审核此分支最终提交，而非用 Codex 自测代替独立审查。
2. 合并前核对最新 main。本分支已基于证据订正提交 `e05474a5c`；后续若主控更新任务索引，按三方内容保留各方有效信息，不整文件覆盖。
3. 通过统一入口重建 app.min.js、lab.min.js 并一次性 bump/SW 更新；本分支版本串仍为 `20261031-a654`。
4. 部署后核对实际 index 修复和 app/lab min 内容、引用与缓存；云上同步须遵守镜像结束等既定条件。
5. 当前任务状态仍由 pending-index 的 #369/#370 两行维护。本报告为本次实现证据，不建立另一份活跃任务台账。
