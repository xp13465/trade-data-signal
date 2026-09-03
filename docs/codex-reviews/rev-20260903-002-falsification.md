# codex rev-20260903-002 报告 P0/P1 证伪评估

> 主控按用户指示「由 claude code 直接评估这次 P0/P1 是否真的成立」对 codex 外审报告的
> 3 个 P0/P1 逐点核实,结论:**三处全部不成立(误报)**。本档记录证据链,供 codex 反查、
> 防同类幻觉复发。原始报告:`docs/codex-reviews/rev-20260903-002.json`(v1.1.14..main 24 commits 抽审,verdict=BLOCKED)。

## 逐点核实

### P0-01 kimi-k3 代理「SSE 流式响应伪造」 — 不成立 ❌
- **codex 声称**:`grep 命中 __event_stream_payload 硬编码占位符`,内部 SSE 响应被重写伪造。
- **证据**:
  - 全仓 `grep -rn "__event_stream_payload\|event_stream_payload"` **零命中**;
  - 全 git 历史 `git log --all -p -S "__event_stream_payload" -- scripts/` **零命中**(从未存在过该符号);
  - v4-flash 代理 `scripts/sensenova-rotate-proxy.py` 同样零命中;
  - kimi 代理 `_do_upstream`(L252-270)直接 `resp.read()` 取上游 body 原样返回,
    Handler `_forward` 末尾 `self.wfile.write(resp_body)` 原样回写,无任何 SSE 组装/重写/占位拼接逻辑;
  - `data:` / `[DONE]` / `choices` 等 SSE 特征串全脚本零组装。
- **判定**:符号不存在、逻辑纯透传,「伪造 SSE」无事实依据。

### P1-01 R2 恢复脚本可执行位缺失 — 不成立 ❌
- **codex 声称**:`git ls-files -s` 显示 mode 100644,无 100755 位,直接调用会失败。
- **证据**:
  - 入库 commit `8c3992117`:`git ls-tree 8c3992117 scripts/restore-r2-backup.sh` → **100755**;
  - 当前 HEAD:`git ls-tree HEAD scripts/restore-r2-backup.sh` → **100755**;
  - 磁盘 `ls -la`: `-rwxr-xr-x`。
  - 执行位从入库起就在,codex 看到的 100644 与仓库事实不符。
- **判定**:可执行位存在,直接调用可正常执行。

### P1-02 agent_inbox_watcher HTTP 模式无鉴权 / SSRF 风险 — 不成立 ❌
- **codex 声称**:HTTP 模式无 Origin/Token 校验,「本机回环之外存在 SSRF/滥用风险」。
- **证据**:
  - `agent_inbox_watcher.py` 全文件无任何入站 HTTP 服务
    (无 `HTTPServer`/`BaseHTTPRequestHandler`/`serve_forever`/`listen`/`accept`/`socket` 监听);
  - 该进程是**纯出站**驱动:轮询 `/tmp/codex-reports/signals/` 本地信号文件 → 调 OpenRouter API
    (`call_openrouter_codex`,URL 固定 `https://openrouter.ai/api/v1/chat/completions`);
  - 无监听端口即无「本机回环之外」可达面,SSRF 前提不成立。
- **判定**:出站进程被误判为入站服务,SSRF/滥用面不存在。

### 附带:P2-01「watch_filter/agent_inbox_watcher 双 watcher 共存」 — 落空 ❌
- 全仓 `grep -rln "watch_filter" scripts/` **零文件**,该文件不存在,双 watcher 说法无对象。

## 结论

| 项 | codex 结论 | 实际 | 判定 |
|---|---|---|---|
| P0-01 kimi SSE 伪造 | FAIL | 全仓全史无此符号,纯透传 | 误报 |
| P1-01 R2 执行位 | FAIL(100644) | 入库即 100755,磁盘 rwxr-xr-x | 误报 |
| P1-02 watcher HTTP 鉴权 | UNCERTAIN(SSRF) | 无入站服务,纯出站 | 误报 |
| P2-01 双 watcher | OPEN | watch_filter 不存在 | 落空 |

**处置**:外审 BLOCKED 无成立的 P0/P1,v1.1.15 tag 不因外审阻塞。
内审(reviewer)PASS + 外审硬项证伪,版本链齐全,打 v1.1.15 已执行。

**根因反思**:codex 报告疑似「看了不存在的符号 / 漏看执行位 / 把出站进程当入站服务」,
与 2026-09-01 codegraph 实测评估的「结构非语义、易错判」同类。外部评审结论必须经主控
证据核验后才采信,不直接照单全收(§0 验收铁律 + §23.7⑤ 上报用户)。
