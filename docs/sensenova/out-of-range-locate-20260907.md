# OUT_OF_RANGE(code=11, 400)真因定位报告

- 日期:2026-09-07
- 触发任务:docs/architecture-review-20260903.md §6.2/6.4/6.5 P0-3 代理高可用 ①OUT_OF_RANGE 真因定位
- 结论一句话:**OUT_OF_RANGE 400 是商汤侧间歇性/时段性网关状态,不是任何稳定请求组合/header/key/path 触发** — 本次实测证伪了"output_config.effort=high 或 enabled 组合触发"的假设(architecture-review §6.2 归因),同组合在窗口外 200/429 稳定。

## 一、现象时间线(2026-09-07,本地代理 18897 测试实例)

| 时刻 | 池内可用 key | 请求特征 | 结果 |
|---|---|---|---|
| 15:30:06 | {1,3,7}(KEY2/4/5/6 冷却) | plain,单发 | 200 |
| 15:30:38 | {1,3,7} | plain,单发 | 200 |
| 15:31:12 | {1,2,3,6,7}(KEY2/6 恰好冷却恢复入池) | zcode 全头 + meta/sys,单发 | **400 OUT_OF_RANGE** |
| 15:31:55~15:40:16 | {1,2,3,5,6,7}(连发) | plain/zcode/加减头任意组合 | 全部 **400** |
| 15:42:17 | {1,2,3,5,6,7}(KEY4 until 15:50 冷) | 全部组合 | 全部 **400**,SKIP 只有 KEY4 |
| 15:45:43 | {1,2,3,5,6,7}(同池!) | plain | **200** |
| 15:49~15:56 | 全 7 key | probe 实例连发 97 次 | 全部 200 |
| 16:07~16:08 | 全 7 key | 直连单/双斜杠 A/B 42 次 | 200/429,零 400 |
| 16:10~16:11 | 全 7 key | 直连连发 30 轮(0.5s 间隔) | 21×200 + 9×429,零 400 |

**窗口:约 15:31~15:45(14 分钟),窗口内全池统一 400,窗口外同池/同组合稳定 200。**

400 响应原文(RESPERR 实证,63 bytes):
`{"error": {"code": 11,"message": "OUT_OF_RANGE","details": []}}`

窗口内 REQBODY(任意组合均 400,此处为带 meta/sys 的 267 bytes 款):
- `plain`: `{"model":"deepseek-v4-flash","max_tokens":384000,"thinking":{"type":"enabled","budget_tokens":1024},"output_config":{"effort":"high"},"messages":[{"role":"user","content":"hi"}]}`
- `zcode 全头`: 额外带 http-referer/user-agent/x-api-key/x-client-language/x-client-timezone/x-os-category/x-os-version/x-platform

## 二、变量隔离结论

| 候选触发变量 | 实证 | 结论 |
|---|---|---|
| `output_config.effort=high` | 同组合窗口外 16 轮直连 200/429 | **非稳定触发**(architecture-review §6.2 假设被证伪) |
| `thinking.type=enabled` + budget 1024 | 窗口外同款重放 200(mt=384000) | 非稳定触发(budget 1024 已是商汤合法上限,>1024 报的是"field Thinking.BudgetTokens invalid"另一类错) |
| `max_tokens=384000` | 窗口外 mt=32000~384000 全档无 400 | 非稳定触发 |
| zcode header 集 | 15:31:55 同刻 plain(带 400 请求)与 zhead 均 400;窗口外同头集 200 | 非触发 |
| header 双斜杠 path(`//v1/messages`) | 窗口外直连单/双斜杠 A/B 均无 400;probe 显示代理恒用双斜杠 | 非触发(但建议规范化,防商汤严格网关节点,见下) |
| 具体 key | **同一 key1/7:15:30 池内 200 → 15:40 池内 400 → 15:45 池内 200** | key 无关 |
| 池构成 | 15:42 与 15:45 同池 {1,2,3,5,6,7},结果 400 vs 200 | 池无关 |
| 高频连发 | 窗口外模拟连发 30 轮低 0.5s,零 400 | 非"连发触发 IP 风控"必然项(仍不能完全排除窗口内存在额外因素) |

## 三、根因判断

**商汤侧账户/网关间歇性时段状态**:窗口内请求全部被拦在配额检查之前(窗口内无任何 429,全是 400 OUT_OF_RANGE),说明网关在窗口对各 key 统一拒绝路由,而非配额/限流逻辑(那些会回 429)。与历史 5 条 OUT_OF_RANGE(architecture-review 记录,全在旧 INJECT 时代 L2355/2587/2619/2792/10075)同型 —— 该项目历史上长期间歇性存在,偶发在特定时段集中爆发,契合"商汤网关侧服务状态/节点切换"而非客户端可稳定复现的请求缺陷。

## 四、生产影响与修复建议(对应 §6.5 P0-3)

1. **400 code=11 纳入轮换(最大健壮性增量)**:现状 `_forward` 只在 `status==429` 或 400 且含 `thinking_budget` 时 continue 换 key,OUT_OF_RANGE 直接 break 把 400 甩给客户端。一旦商汤窗口期出现,所有 agent 集体报 400 挂死。**改造:400 且 body 含 `OUT_OF_RANGE` 也走 continue 换 key + 触发冷却退避**,窗口期自动换 key 重试,用户无感无挂死。
2. **path 规范化**:`UPSTREAM_BASE="/"` + `self.path` 拼出 `//v1/messages` 双斜杠,建议改为单斜杠(防御商汤严格节点)。
3. **enabled 型 clamp**:新版 `_strip_thinking_adaptive` 只删 adaptive,enabled 型(带 budget_tokens)原样转发;补 clamp budget_tokens>1024→1024(§6.4 缺口,本次重放确认 1024 为合法上限)。
4. **/healthz + 心跳告警**:实现 healthz 端点,心跳异常经 notify.py 接入 severe 镜像 latest.md(§6.5 ③)。

## 五、防重犯要点

- 排查 400 类错误不能只盯 req.log(memory: req.log 有 20MB 截断,历史 400 只活在无时间戳主日志)→ 本次用 18897 测试实例的 ttp-debug.log(带时间戳)做全量 RESP/REQBODY 关联。
- 归因前必须窗口内外 A/B + 同池对照,防"时段性污染"误判成 header/body 触发(bisect 前序轮次曾误以为 zcode header 触发,锚点基线法证伪)。

## 复现

- 复现脚本(死脚本,随报告落档,同目录):
  - `scripts/replay_out_of_range_ab.py`:单/双斜杠直连 A/B(42 次),验 path 无关
  - `scripts/replay_out_of_range_burst.py`:7 key 连发 30 轮,验组合/连发不触发 400
- 输入依赖:`/Users/linhuichen/code/trade-data/.env`(SENSENOVA_KEY1-7 真实 key)= 输出 stdout 状态逐行 + 汇总
- 重跑命令:`cd docs/sensenova/scripts && python3 replay_out_of_range_burst.py`(30 轮约 60s)
- 数据截止:2026-09-07 16:11 直连实测;窗口观测 15:31~15:45 为非交互式观测记录(届时无法再回放,以本报告时间线为准)
- 关键口径一句话:请求 = `model=deepseek-v4-flash, max_tokens=384000, thinking.type=enabled budget_tokens=1024, output_config.effort=high, messages=[hi]`;判断 400 = response body `{"error":{"code":11,"message":"OUT_OF_RANGE"}}` 63 bytes。
- 配套 commit:本报告 + `scripts/` 两脚本 + worktree 代理脚本修复(A②enabled clamp / A③healthz / 400 轮换)同批提交。