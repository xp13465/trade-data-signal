# thinking-proxy 配置切换/恢复 SOP(2026-08-16 落档)

> 目的:一次把「切代理端点 / 换 key / 恢复被搞乱的配置」做对,不卡死、不重复踩坑。
> 配套:`scripts/thinking-proxy-rollback.sh`(回退到直连)、`scripts/com.trade.thinking-proxy.plist`(launchd 守护)、`scripts/thinking_proxy.py`(代理本体)。

## 这套东西是什么(30 秒理解)

本地代理 thinking_proxy.py = 所有会话的"桥":
```
Claude Code → 127.0.0.1:8899(本地代理)→ 火山 agent plan(现网,api/plan)
```
代理负责 **per-role thinking(默认关 + 显式开,2026-08-19 升级)**:
- `flash` 请求 → 默认注入 `thinking:{type:disabled}` → 关深度思考(执行类,省 token);**仅当请求显式带 `{"thinking":{"type":"enabled"}}` 时放行思考**(按需开,日志 `explicit=True`)
- `think` 别名请求 → 不改注入 + 改写 model 为 flash 转发 → 保思考(判断类)
- 实测:agent plan / coding 端点认 `disabled` 字段,响应无 thinking 块 = 真关,非静默;`adaptive`(Claude Code 对 deepseek 默认发)按默认关处理(=ON 最费,必须注入掉)

## 关键原则(违反 = 卡死,血泪教训 L33 两次)

1. **主控直接改配置,绝不派"跑在代理链路上的 agent"改 key**。子 agent 改完 key,自己下一个请求就带着新 key 走旧代理 → 401 当场死,留半截脏配置,用户被迫手动重置(8/14、8/16 各栽一次)。
2. **改 settings.json 不影响运行中会话 env**(进程启动时已加载),改完必须**用户重启会话**才生效。
3. **先验证后交付**:主控侧改完,curl 双通路 200 通过,才让用户重启;重启后再核验运行证据,才算 done。

## 现网状态(2026-08-16 定)

| 项 | 值 |
|---|---|
| 端点 | 火山方舟 coding(ark.cn-beijing.volces.com:443/api/coding,2026-08-19 确认现网) |
| key | `ark-****`(现网值在 `~/.claude/settings.json` 与模板 `~/.claude/settings.json.tpl-proxy-full`,**禁止写进 git/文档**) |
| settings.json | 走代理 `http://127.0.0.1:8899` + MODEL=deepseek-v4-think + hooks(claude-says 飞书)+ CLAUDE_CODE_AUTO_COMPACT_WINDOW=1048576 |
| 代理进程 env | TTP_PROVIDER=ark / TTP_UPSTREAM_BASE=/api/coding / TTP_INJECT=1 / TTP_INJECT_MODELS=deepseek-v4-flash / TTP_ALIAS_MODELS=deepseek-v4-think / TTP_ALIAS_TARGET=deepseek-v4-flash |

> 火山方舟有 coding plan 和 agent plan 两个端点,**地址、token 都不同**,切换要整套换(key + 端点)。

## 切换/恢复全流程(按序走)

### Step 0 切前确认
向用户复述「要切到哪、改成什么、影响什么」,用户点头再动手(§23.7)。不确认不碰。

### Step 1 备份当前 settings
```bash
cp ~/.claude/settings.json ~/.claude/settings.json.bak-$(date +%Y%m%d-%H%M%S)
```

### Step 2 恢复完整代理版 settings(三选一)
- **A. 模板一键恢复(最常用,配置被搞乱时)**:当前完整版已固化在 `~/.claude/settings.json.tpl-proxy-full`(含 hooks+think+ark key+走代理)。
  ```bash
  cp ~/.claude/settings.json.tpl-proxy-full ~/.claude/settings.json
  ```
- **B. 只换 key(端点不变)**:python3 json 读写,保 hooks,只改 `env.ANTHROPIC_AUTH_TOKEN`。**不要**基于瘦身直连版(会丢 hooks / per-role thinking)。
- **C. 切换端点**:改 plist 的 `TTP_PROVIDER`(ark-plan | ark | official)+ 换对应 key,见 Step 3。

### Step 3 确认/重启代理进程(端点对才走)
```bash
# 看运行中代理 env(最硬证据)
ps eww -p $(pgrep -f thinking_proxy.py | head -1) | tr ' ' '\n' | grep '^TTP_'
# 期望: TTP_PROVIDER=ark-plan TTP_UPSTREAM_BASE=/api/plan TTP_INJECT=1
# 不对就改 plist 后重启:
#   launchctl unload /Users/linhuichen/code/trade/scripts/com.trade.thinking-proxy.plist
#   launchctl load   /Users/linhuichen/code/trade/scripts/com.trade.thinking-proxy.plist
```

### Step 4 curl 双通路验证(主控侧,不重启会话,不通过不交付)
```bash
KEY=$(python3 -c "import json;print(json.load(open('/Users/linhuichen/.claude/settings.json'))['env']['ANTHROPIC_AUTH_TOKEN'])")
# 通路1: flash → 期望 200 + 日志 injected=True
curl -s -o /dev/null -w "flash HTTP %{http_code}\n" -X POST http://127.0.0.1:8899/v1/messages \
  -H "Content-Type: application/json" -H "x-api-key: $KEY" -H "anthropic-version: 2023-06-01" \
  -d '{"model":"deepseek-v4-flash","max_tokens":1,"messages":[{"role":"user","content":"hi"}]}'
# 通路2: think 别名 → 期望 200 + 日志 aliased=True
curl -s -o /dev/null -w "think HTTP %{http_code}\n" -X POST http://127.0.0.1:8899/v1/messages \
  -H "Content-Type: application/json" -H "x-api-key: $KEY" -H "anthropic-version: 2023-06-01" \
  -d '{"model":"deepseek-v4-think","max_tokens":1,"messages":[{"role":"user","content":"hi"}]}'
# 通路3(按需 thinking): flash 显式 enabled → 期望 200 + 日志 explicit=True(不注入,放行思考)
curl -s -o /dev/null -w "flash-enabled HTTP %{http_code}\n" -X POST http://127.0.0.1:8899/v1/messages \
  -H "Content-Type: application/json" -H "x-api-key: $KEY" -H "anthropic-version: 2023-06-01" \
  -d '{"model":"deepseek-v4-flash","thinking":{"type":"enabled","budget_tokens":1024},"max_tokens":8,"messages":[{"role":"user","content":"hi"}]}'
# 看标记
grep REQ /Users/linhuichen/code/trade-data/data/logs/thinking-proxy-req.log | tail -4
# 期望: flash...injected=True / think...aliased=True / flash+enabled...explicit=True
```
> 响应体对照(更强证据):think / flash+enabled 返回含 `"type":"thinking"` 块,flash 默认返回**无** thinking 块只有 text——同模型同端点,差别只在是否注入 disabled,证明真关真开。

### Step 5 让用户重启会话
改 settings 只对**新启动的会话**生效。明确告诉用户「重启会话验证」。

### Step 6 重启后核验运行证据(才算 done)
```bash
tail -6 /Users/linhuichen/code/trade-data/data/logs/thinking-proxy-req.log | grep -E 'REQ|RESP'
# 期望出现重启后的新请求流: think→aliased=True(保思考)/ flash→injected=True(关思考),HTTP 200
# 再复查 settings.json 的 hooks/COMPACT/BASE_URL 都在
```

## 卡死排查表

| 症状 | 排查/解法 |
|---|---|
| `Your api key ... is invalid`(401) | key 与端点不匹配:ark key 只能打火山端点,打官方 api.deepseek.com 必 401。按 Step 3 核对代理 upstream。 |
| 会话不可用 / 代理挂了 | `launchctl list \| grep trade` + `pgrep -f thinking_proxy.py`。KeepAlive 应自动拉起,手动 `launchctl load plist` 兜底。 |
| 飞书没抄送 / hooks 没生效 | settings.json 有 `hooks.Stop`?重启过会话没?(hooks 只有新会话加载) |
| think 直发 404 / UnsupportedModel | agent plan 不认 think 名,必须走代理改写;直连时改 MODEL=flash-ga 或恢复代理。 |
| 注入/别名标记不符 | env 没刷新:重启代理(plist unload/load)。 |
| 配置改坏了要急救 | Step 2-A 模板一键恢复 → Step 3/4 验证 → Step 5 重启。 |

## 回退(放弃代理,回直连)
```bash
bash scripts/thinking-proxy-rollback.sh          # 还原火山 agent plan 直连(现网默认)
bash scripts/thinking-proxy-rollback.sh official # 官方直连
bash scripts/thinking-proxy-rollback.sh ark      # 方舟 coding 直连
```
> 回退=直连,thinking 默认 ON;agents 里 flash/think 别名在直连下会 404,需改 model: inherit。

## 落档时间线
- 2026-08-16:切火山 agent plan 端点(api/plan)+ 新 plan key;两次栽「子 agent 改 key 自杀」后固化本 SOP + 完整版模板;模板 `~/.claude/settings.json.tpl-proxy-full`。
- 2026-08-19:按需 thinking 升级(用户定「默认关+显式开」):thinking_proxy.py 注入逻辑改为——flash 默认注入 disabled,仅请求显式 `thinking.type=enabled` 时放行思考(`explicit=True`),adaptive 仍按默认关;think 别名保思考照旧。备份 `thinking_proxy.py.bak-20260819-on-demand`。现网端点确认为 coding(api/coding,ark)。
