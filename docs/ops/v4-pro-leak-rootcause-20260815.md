# 15:00-16:00 v4-pro 用量异常根因分析(2026-08-15)

## 现象

2026-08-15 15:00-16:00,火山方舟官方 token 统计/用量页出现 deepseek-v4-pro 用量。
设计意图是「零 v4-pro」(think 别名经代理改写 flash,判断类保思考走 flash 底,不产生 v4-pro)。

实际触发点:15:43-15:44(北京时区),一个 Claude Code 内置 **Explore subagent** 产生 12 次 API 请求,
全部被按 deepseek-v4-pro 计费。token 量级:输入 ~59,684 + 输出 ~8,282 + cache_read ~382,848。

## 根因(完整链条)

```
主会话 a84dd439 15:43:07 spawn Explore subagent(任务:定位首页布局卡片结构)
  → Explore 请求体 model = claude-opus-5(Claude Code 内置 Explore 类型 agent 的请求模型名)
  → 本地代理 thinking_proxy.py:claude-opus-5 既不匹配 INJECT_MODELS(deepseek-v4-flash)
      也不匹配 ALIAS_MODELS(deepseek-v4-think) → injected=False aliased=False,原样透传
  → 代理转发到 upstream(api.deepseek.com/anthropic,8-14 20:20:44 provider=official)
  → upstream 接受 claude-opus-5,实际按 v4-pro 处理,响应 model 回显 deepseek-v4-pro
  → Claude Code jsonl 记录 model=deepseek-v4-pro,官方/方舟计费 v4-pro
```

一句话:**代理的零 v4-pro 保证依赖「所有 model 名必须命中 INJECT 或 ALIAS 白名单」,
claude-opus-5 是第三个模型名,不在任何名单里 → 透传 → v4-pro 计费。**

## 影响

- 12 次请求,29 个 assistant 轮次(一个请求拆多条 jsonl 记录)按 v4-pro 计费。
- 总处理 token ≈ 450,814(input 59,684 + output 8,282 + cache_read 382,848)。
- 行为正常(Explore 正常完成任务并返回结论),纯成本影响,无功能异常。

## 证据(文件:位置 + 摘录)

### 1. 主会话 spawn Explore 调用链
`~/.claude/projects/-Users-linhuichen-code-trade/a84dd439-a03f-4342-b1ff-ccb39d49d75f.jsonl`
```
2026-08-15T07:43:07.372Z model=deepseek-v4-flash
  [tool_use:Agent {"description": "定位首页布局卡片结构",
   "prompt": "只读定位任务:摸清首页(index.html + app.js 渲染逻辑)的布局结构...用 Explore 方式,只输出结论不修改任何文件。"}]
```
(07:43 UTC = 15:43 北京)

### 2. Explore subagent 记录 model=deepseek-v4-pro
`~/.claude/projects/-Users-linhuichen-code-trade/a84dd439-a03f-4342-b1ff-ccb39d49d75f/subagents/agent-a2b38b2d62ff68b85.jsonl`
- meta.agentType = "Explore", 29 条 assistant 记录 model 全为 `deepseek-v4-pro`。
- 首条 07:43:10.574Z,末条 07:44:55.957Z(15:43:10-15:44:55 北京)。

### 3. 代理审计日志:同一批请求 model=claude-opus-5 透传
`/Users/linhuichen/code/trade-data/data/logs/thinking-proxy-req.log`
```
[2026-08-15 15:43:10] REQ POST /v1/messages?beta=true model=claude-opus-5->claude-opus-5 thinking={"type": "adaptive"} injected=False aliased=False
[2026-08-15 15:43:10] RESP 200 bytes=17215 has_thinking=True usage(in=12489 out=191 cc=0 cr=0 think=0)
... 共 12 条 REQ claude-opus-5,12 条 RESP 200
```

### 4. usage 逐条吻合(证明同一批请求)
| 代理 RESP in/out/cr | Explore jsonl usage |
|---|---|
| 15:43:10 in=12489 out=191 cr=0 | 07:43:10.574Z in:12489 out:191 cr:0 |
| 15:43:12 in=969 out=139 cr=12672 | 07:43:12.600Z in:969 out:139 cr:12672 |
| 15:43:16 in=1514 out=240 cr=13696 | 07:43:16.219Z in:1514 out:240 cr:13696 |
| 15:43:20 in=12883 out=226 cr=15360 | 07:43:20.519Z in:12883 out:226 cr=15360 |
| 15:43:22 in=1317 out=131 cr=28416 | 07:43:22.713Z in:1317 out:131 cr=28416 |
| 15:43:25 in=3049 out=130 cr=29824 | 07:43:25.580Z in:3049 out:130 cr=29824 |
| 15:43:28 in=5053 out=157 cr=32896 | 07:43:28.363Z in:5053 out:157 cr=32896 |
| 15:43:31 in=4850 out=173 cr=38016 | 07:43:31.027Z in:4850 out=173 cr=38016 |
| 15:43:34 in=5989 out=213 cr=43008 | 07:43:34.426Z in:5989 out=213 cr=43008 |
| 15:44:02 in=7765 out=2392 cr=49152 | 07:44:02.544Z in:7765 out:2392 cr:49152 |
| 15:44:07 in=1081 out=266 cr=59264 | 07:44:07.339Z in:1081 out:266 cr:59264 |
| 15:44:55 in=2725 out=4024 cr=60544 | 07:44:55.957Z in:2725 out:4024 cr:60544 |

12 组 usage 完全一致,12 个唯一请求,非巧合。

### 5. 代理重写逻辑(为什么 claude-opus-5 漏网)
`/Users/linhuichen/code/trade/scripts/thinking_proxy.py`
- L57 `INJECT_MODELS = ... "deepseek-v4-flash"`  → 只匹配 flash
- L61 `ALIAS_MODELS = ... "deepseek-v4-think"`   → 只匹配 think 别名
- L85-94:`if model_field: if any(INJECT): 注入 disabled; elif any(ALIAS): 改写 flash`
  任何 model 不在两列表 → 不注入不改写,原样透传(injected=False aliased=False)。

### 6. 代理 upstream = 官方 api.deepseek.com(排除方舟直连)
`/Users/linhuichen/code/trade/scripts/com.trade.thinking-proxy.plist` L32-33 TTP_PROVIDER=official;
`thinking-proxy-req.log` 最后一条启动记录:
```
[2026-08-14 20:20:44] proxy listening ... provider=official ... -> https://api.deepseek.com/anthropic
```
代理自 8-14 20:20:44 起未重启(req.log 无 8-15 启动记录),15:43 流量全部经此进程转发到官方端点。

## 诚实标注(口径说明)

1. **唯一 v4-pro 来源 = Explore subagent**:全仓 grep 2026-08-15 的 v4-pro 记录,仅
   `agent-a2b38b2d62ff68b85.jsonl`(Explore,15:43)一条。另一疑似 v4-pro 的
   `agent-adefa48139e350486.jsonl` 核实为 **deepseek-v4-flash**(17:07,代理流量 flash/think,非 v4-pro)。
2. **「方舟统计 vs 官方端点」**:本地证据显示请求打到官方 api.deepseek.com/anthropic。用户看到的
   v4-pro 用量在「火山方舟官方 token 统计」页——若官方 DeepSeek 开放平台与火山方舟共享统计口径,
   则同一批请求两边都可见;本地无法进一步验证平台侧归属,属待确认项,不影响根因结论。
3. **claude-opus-5 为何被官方接受并计费 v4-pro**:官方端点对未知 model 名宽松处理(RESP 200 + usage 完整),
   响应 model 回显 deepseek-v4-pro(Claude Code jsonl 记录依据)。具体映射规则属官方黑盒,未做实测(只读约束)。

## 修复建议(待用户确认,不自行改)

| 方案 | 做法 | 效果 | 风险 |
|---|---|---|---|
| A. 最小改动 | `TTP_ALIAS_MODELS` 追加 `claude-opus-5`(→ 改写成 flash) | 立即止血,Explore 走 flash | 只堵一个名字,未来新模型名仍漏网 |
| B. 根治(推荐) | 代理加「未知模型兜底」:model 不命中 INJECT/ALIAS 时默认改写 flash + 日志告警(不再原样透传) | 任何新模型名都不会漏网计费 v4-pro | 改变未知模型行为(现为透传→后为 flash),需确认无「故意用 v4-pro」场景 |
| C. 源头 | 主控派只读定位类任务不用 Explore 方式,改用普通 subagent(frontmatter 钉 deepseek-v4-flash/think) | 从调度侧避免触发 | 治标,其他触发 Explore 的场景仍在 |

> 联动:改代理逻辑属生产变更,须走 §23.7 用户确认;改后须重载 launchd + 复现验证(见下节)。

## 复现

- **脚本路径**:无独立脚本,复现 = 两条命令对拍(排查命令即复现步骤)。
- **输入依赖**:
  - `/Users/linhuichen/code/trade-data/data/logs/thinking-proxy-req.log`(代理审计日志)
  - `~/.claude/projects/-Users-linhuichen-code-trade/a84dd439-a03f-4342-b1ff-ccb39d49d75f/subagents/agent-a2b38b2d62ff68b85.jsonl`(Explore subagent 会话)
- **重跑命令**:
  ```
  # 1) 查代理 15:43-15:44 claude-opus-5 透传(应为 12 REQ + 12 RESP 200)
  grep -E "2026-08-15 15:4[0-9]" /Users/linhuichen/code/trade-data/data/logs/thinking-proxy-req.log | grep claude-opus-5
  # 2) 查 Explore subagent 记录的 model(应全为 deepseek-v4-pro)
  grep -o '"model":"[^"]*"' ~/.claude/projects/-Users-linhuichen-code-trade/a84dd439-a03f-4342-b1ff-ccb39d49d75f/subagents/agent-a2b38b2d62ff68b85.jsonl | sort | uniq -c
  # 3) 对拍 usage:步骤1的 RESP in/out/cr 应与步骤2 jsonl assistant usage 逐条相等(见证据表)
  ```
- **数据截止日期**:2026-08-15 15:44:55(北京);日志最新见 8-15 22:54。
- **关键口径一句话**:Explore subagent 请求体 model=claude-opus-5,不在代理 INJECT/ALIAS 白名单,
  被原样透传到官方端点,按 v4-pro 计费;jsonl 记录的 v4-pro 来自官方响应 model 回显。
