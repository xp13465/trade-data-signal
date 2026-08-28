# 调研:cc-switch → opencode.ai/zen/go 链路「关闭思考」+「缓存命中率」深度核查(2026-08-21)

> 触发:用户手动切换到 cc-switch 管理的 provider「OpenCode Go」(endpoint https://opencode.ai/zen/go),原 thinking_proxy 注入 `thinking:{type:disabled}` 省 token 策略是否还成立存疑;同日追加调研「缓存命中率差 + opencode 是否有专门优化项」。
> 结论口径一句话:**该端点上「关思考」结构性不可用(cc-switch 转换时丢弃 thinking 参数,opencode 对 deepseek-v4-flash 默认强制 reasoning ON 且无参数/无变体可关);缓存命中率低是网关缓存实现差异 + cache_control 被剥离所致,当前 ~23%,无配置项可救,唯一恢复途径是回退 thinking_proxy 官方链路。**

---

## 一、核心结论(先回答两个问题)

### 问题1:关思考还能不能用?
**不能(在 opencode.ai/zen/go 链路上,无法通过配置恢复)。** 铁证链:
1. Claude Code 对非已知模型 deepseek-v4-flash 永远发 `thinking:{type:"adaptive"}`(旧文档 §8.3 实测),而非 disabled。
2. cc-switch 对 claude 请求做 `openai_chat` 转换时 -> `transform::anthropic_to_openai_with_reasoning_content` 只对「支持 reasoning 的模型白名单(o-series / gpt-5+ / grok-4.5 / grok-build)」设置 `reasoning_effort`;**deepseek-v4-flash 不在白名单**,且 `thinking` 字段在转换结果里根本不存在(不映射、不透传)。
3. 因此发给 opencode 的请求体里**没有任何 reasoning/thinking 控制参数**。
4. opencode.ai/zen/go 对 deepseek-v4-flash **默认输出推理**(实测每次响应带 `reasoning` 字段,completion 16-72 tokens)。
5. 该平台模型列表无「无思考变体」(只有 deepseek-v4-flash / deepseek-v4-pro);实测 `reasoning_effort:none`、`thinking:{type:disabled}`、`reasoning:{enabled:false}` 全部无效。
6. 实测有效关法只有 `reasoning:{"effort":"none"}` 或 `chat_template_kwargs:{"thinking":false}`(completion_tokens 2、无 reasoning),但 **cc-switch 不会发这两个参数**,也没有任何 provider 配置入口能注入。

### 问题2:缓存命中率差,有没有专门优化项?
**没有可配项;当前命中率 ~23%(结构性低)。** 铁证链:
1. `cache_control`(Anthropic 缓存标记)**被 cc-switch 转换时剥掉**(源码单测确认转换后 `cache_control.is_none()`);OpenAI 兼容格式无 cache_creation 字段,故 `cache_creation=0`。
2. opencode.ai/zen/go 的缓存只有「Cached Read」价格($0.007/M off-peak,约 3% 全价),**无 Cached Write(表中 "-")** = 无 Anthropic 式显式缓存创建,只有 DeepSeek 底层的自动 prefix 缓存。
3. 实测相同 system 前缀连续两请求,第二个响应 `prompt_tokens_details` 仍为 `{}`,**网关不透传 deepseek 的缓存命中明细**,且命中率仅 ~22-27%(db 全天 127 请求 22.7%;主控当前会话 26.4%)。
4. 命中差距来源:切换前官方链路命中 0.978(08-19)vs 切换后 0.23-0.26,数量级下降约 4 倍。
5. 优化项排查:cc-switch 侧 optimizer/cache_injector 仅对 bedrock provider 生效(opencode 不是);OpenCode 表单 ExtraOptions/模型附加字段仅写 opencode 客户端自身配置,不注入 Claude Code 代理请求体;opencode 官方文档无任何缓存控制参数(仅价格表)。**无配置可调。**

---

## 二、端点接线与链路事实(证据)

| 项 | 值 | 证据 |
|---|---|---|
| 当前激活 provider | `4835da8a...` = 「OpenCode Go」 | `~/.cc-switch/settings.json` currentProviderClaude |
| API 格式 | `openai_chat`(Anthropic→OpenAI 转换) | `cc-switch.db providers.meta`: `{"apiFormat":"openai_chat",...}` |
| 上游端点 | `https://opencode.ai/zen/go/v1/chat/completions` | `cc-switch.log`:`[Claude] >>> 请求目标 ... model=deepseek-v4-flash` |
| Claude Code 侧 | `ANTHROPIC_BASE_URL=http://127.0.0.1:15721`(cc-switch 本地代理) | `~/.claude/settings.json` env |
| cc-switch 版本 | 3.19.2 | `/Applications/CC Switch.app` Info.plist |
| 模型档位 | 全部映射到 `deepseek-v4-flash` | settings.json / provider settings_config |
| 判断类别名 | `deepseek-v4-think`(Claude 侧请求 model) | proxy_request_logs.request_model |
| 上游模型 | 统一 `deepseek-v4-flash`(别名/opus/haiku 均改写) | proxy_request_logs.model |

thinking_proxy(8899)现状:进程还活着(PID 90379 监听 8899,plist 配置仍 TTP_PROVIDER=official),**已脱离链路**(settings 不再指向 8899),不产生作用。

---

## 三、关思考维度调研明细

### 3.1 转换层根因(源码,cc-switch github farion1231/cc-switch v3.19.2)
- `src-tauri/src/proxy/providers/claude.rs` L434:`"openai_chat"` 分支调用 `transform::anthropic_to_openai_with_reasoning_content`。
- `src-tauri/src/proxy/providers/transform.rs` L208-213:
  ```
  if supports_reasoning_effort(model) {
      if let Some(effort) = resolve_reasoning_effort(&body) {
          result["reasoning_effort"] = json!(effort);
      }
  }
  ```
- `supports_reasoning_effort`(L71-81)只认 o-series / gpt-5+ / grok-4.5 / grok-build`;**deepseek-v4-flash 不命中** -> 不设 reasoning_effort。
- `resolve_reasoning_effort`(L94-123):`disabled` / 缺失 -> `None`(单测 L1830-1832 明示)。
- 转换结果里不存在 `thinking` 键 -> anthropic 的 `thinking:{type:disabled}` **在转换层整体丢弃**。
- `forwarder.rs` L482-486: `thinking_optimizer::optimize` 仅在 `optimizer_config.enabled && is_bedrock_provider(provider)` 时执行,opencode 不满足。

### 3.2 opencode.ai/zen/go 实测(直接 curl /v1/chat/completions,2026-08-21)
| 传参 | 响应 reasoning 字段 | completion_tokens | 结论 |
|---|---|---|---|
| 不传(baseline) | 有("We need answer...") | 16-21 | ON |
| `thinking:{type:disabled}` | 有 | 9 | 无效 |
| `reasoning_effort:"none"` | 有 | 16-18 | 无效 |
| `reasoning:{enabled:false}` | 有 | 13 | 无效 |
| `reasoning_effort:"minimal"` | 有 | 18 | 无效 |
| `max_tokens:16`(限制预算) | 有(reasoning 独占预算,content 空) | 16 | 无效 |
| **`reasoning:{effort:"none"}`** | **无** | **2** | **真关** |
| **`chat_template_kwargs:{thinking:false}`** | **无** | **2** | **真关** |

模型列表(`/v1/models`):deepseek-v4-flash / deepseek-v4-pro 仅此两个 DeepSeek 模型,无 no-reasoning 变体。

### 3.3 关思考的可用路径判定
| 路径 | 可用? | 说明 |
|---|---|---|
| ① 模型名=无思考版 | 无此模型 | 模型列表无变体 |
| ② OpenAI 参数 reasoning_effort | 无效 | opencode 网关不认(或仅认 reasoning.effort 嵌套形式) |
| ③ `reasoning:{effort:"none"}` | **有效但需注入** | cc-switch 不注入,需改代理 |
| ④ 走 thinking_proxy(官方 anthropic) | 可用且已成熟 | 回退方案,per-role 注入 disabled 真关(旧文档 §8) |

---

## 四、缓存维度调研明细(追加)

### 4.1 cc-switch 是否透传 cache_control→否(剥除)
- transform.rs 单测(L948-1009 `test_anthropic_to_openai_strips_cache_control_from_merged_system`)明确:多个 system 块含 `cache_control:{type:"ephemeral"}` 合并后 `result["messages"][0].get("cache_control").is_none()` -> 被剥。

### 4.2 opencode 缓存行为(实测+文档)
- 文档 `https://opencode.ai/docs/zen/#pricing`:DeepSeek V4 Flash 行 = Input $0.22 / Output $0.66 / **Cached Read $0.007** / Cached Write "-"(off-peak);Peak 翻倍。有 Cached Read 价 => 存在前缀缓存读取;无 Cached Write => 无显式缓存创建(仅 DeepSeek 自动 prefix 缓存)。
- 实测相同 system 前缀连续请求,第 2 次 `usage.prompt_tokens_details:{}`(空),opencode 网关**不回传缓存命中明细**,也无命中迹象。
- 官方文档全页无任何缓存控制参数/cache_control 说明 -> 无 API 层可配项。

### 4.3 命中率数据(cc-switch db 与主控实测交叉)
- 全天(2026-08-20):127 请求,input 10,592,203,cache_read 2,402,560,creation 0 -> **命中率 22.7%**(/tmp/cc-switch-ro.db 副本查询)。
- 按请求来源分:claude-opus-4-8 类请求(59 次,7.0M input)命中仅 **6.5%**;deepseek-v4-think(52 次,3.1M)与 flash(16 次,0.5M)各 ~54%。
- 历史对比:切换前官方链路 08-19=0.9780(项目命中率统计脚本)vs 切换后 ~0.23-0.26,数量级差 ~4 倍。
- 主控当前会话实测:cache_read 2,436,096 / input 6,792,737 -> 26.4%;cache_creation=0(OpenAI 格式无此字段,cc-switch 无从解析)。

### 4.4 提升命中率可配项排查结论
- cc-switch:无(optimizer/cache_injector 仅 bedrock;cache_control 被剥;无 provider 级缓存参数)。
- opencode:无(文档无缓存 API;网关不透传命中明细)。
- DeepSeek 底层自动 prefix 缓存依赖字节前缀一致;cc-switch 转换时 system 块合并/剥离,前缀结构不保证与官方一致,加上 opencode 网关中转,命中率大幅劣化。
- **结论:该端点缓存命中率低是结构性,无法通过配置救回。**

---

## 五、推荐方案

### 方案 A(推荐):回退 thinking_proxy 官方链路 —— 同时恢复「关思考」+「高缓存命中」
- 操作:settings.json `ANTHROPIC_BASE_URL` 改回 `http://127.0.0.1:8899`;确认 plist `TTP_PROVIDER=official`(已是);agents frontmatter 别名(flash=执行注入 disabled / think=判断保思考)恢复;`launchctl load` 确认 8899 守护。
- 效果:执行类注入 `thinking:disabled` 真关(completion 1-3 token);判断类/主控保思考;官方 prefix 缓存命中恢复 ~98%(历史 0.978 实测)。
- 代价(P0,既有已知):代理挂=全站 claude 不可用;launchd KeepAlive 守护可缓解。
- 一键回退:`bash scripts/thinking-proxy-rollback.sh official`。

### 方案 B:留在 opencode 但改造本地代理(开发成本,非配置)
- 思路:新增/改造一个本地代理,收 Claude 的 /v1/messages -> 转 OpenAI chat -> 对 flash 注入 `reasoning:{effort:"none"}` -> 转发 `opencode.ai/zen/go`;对 think 别名注入 effort low/high 保思考;需处理 SSE 流式转发与 usage 回填。
- 优点:保留 opencode 网关(便宜/统一出口);缺点:要开发、维护,且 **缓存命中率低的问题仍无解(仍 23%)**。

### 方案 C:接受现状
- 全角色 reasoning ON(执行类也 ON,变慢变贵)+ 缓存 23%;简单执行类任务失去 3.8x 提速与 85% 输出省量的既有收益。

### 对 thinking_proxy 的处理
- 走 A:保持 8899 守护,不做改动,恢复其工作。
- 走 B:改装 8899 为 opencode 注入层(新增模式),或停用(launchctl unload + 保留脚本)。
- 当前它脱离链路空转,不造成费用,只占一个端口;建议走 A 直接复用。

---

## 六、成本/延迟影响评估(现行 opencode 链路)

| 项 | 数值 | 说明 |
|---|---|---|
| 输入全价(off-peak) | $0.22/M | deepseek-v4-flash, vs cached read $0.007/M(约 3%) |
| 输入全价(peak=北京 9-12/14-18) | $0.44/M | opencode 高峰 UTC 01-04 + 06-10 = 北京 9:00-12:00 / 14:00-18:00,与 DeepSeek 官方一致 |
| 当前命中率 | ~23% | 未命中部分按全价计,命中部分微价 |
| 单会话成本估算 | 当前会话 input ~6.8M,命中 26.4%:未命中 5.0M ≈ $1.1,命中 1.8M ≈ $0.013 | 若回退官方且命中 98%:未命中仅 0.14M,成本约降一个数量级 |
| 每请求多付推理输出 | baseline 16-72 token reasoning | 无法关闭时每轮固定多一段 reasoning 输出(执行类最伤) |
| 延迟 | 多一跳 cc-switch + opencode 网关 | reasoning 生成本身是串行,响应首 token 更慢 |

---

## 七、证据清单(供复核)

- 转换丢弃 thinking:`https://github.com/farion1231/cc-switch` `src-tauri/src/proxy/providers/transform.rs` L208-213 + L71-81 + 单测 L1830-1838。
- cache_control 剥离:同上 transform.rs 单测 L948-1009。
- 转换生产路径:`src-tauri/src/proxy/providers/claude.rs` L434-454。
- optimizer 仅 bedrock:`src-tauri/src/proxy/forwarder.rs` L482-486。
- 上游请求目标:`~/.cc-switch/logs/cc-switch.log`(2026-08-21 00:04 起)。
- provider 配置:`~/.cc-switch/cc-switch.db` providers.id=4835da8a(meta.apiFormat=openai_chat, endpoint https://opencode.ai/zen/go);proxy_request_logs(命中率数据)。
- opencode 官方文档:`https://opencode.ai/docs/zen/`(Endpoints/Pricing/Peak hours;无 reasoning/cache 控制参数)。
- 实测命令:见文末复现段。

---

## 复现

- 脚本/命令:
  1. 缓存命中率:`sqlite3 ~/.cc-switch/cc-switch.db "SELECT SUM(cache_read_tokens), SUM(input_tokens) FROM proxy_request_logs WHERE provider_id='4835da8a-5c0a-4827-b25b-42aff34a8d57'"`(db 运行中会锁,先 `cp` 副本再查)。
  2. opencode reasoning 实测定参:POST `https://opencode.ai/zen/go/v1/chat/completions`,Header `Authorization: Bearer <db 内 provider ANTHROPIC_AUTH_TOKEN>`,`{"model":"deepseek-v4-flash","messages":[{"role":"user","content":"17*23? only reply the number"}],<变参>}`;看 `choices[0].message.reasoning` 与 `usage.completion_tokens`。
  3. 模型列表:`curl -s https://opencode.ai/zen/go/v1/models -H "Authorization: Bearer <token>"`。
- 依赖:cc-switch.app 3.19.2 运行中(15721);opencode provider 激活;root 本地命令可访问 db/start 目录。
- 数据截止:2026-08-21 00:30(北京),opencode 文档抓取时刻同。
- 关键口径一句话:cc-switch 对 openai_chat 转换只给白名单模型(o/gpt-5+/grok)设 reasoning_effort,deepseek-v4-flash 不在白名单 -> thinking disabled 被丢弃;opencode 对 deepseek-flash 默认 reasoning ON 且无可配关闭项;cache_control 被剥 + 网关不透传命中明细 -> 命中率 ~23% 结构性低。

---

## 补充调研(2026-08-21 追补):底层缓存真实性 + 用户两方案核实(修正上节「结构性低/无解」判断)

> 触发:上节结论「缓存 ~23% 结构性低、无解」被用户新观察推翻(「并不是100%缓存用不到,有些请求用的很好」)。追补实测后**修正**:opencode 底层缓存真实且高效,命中率差的主因是「主控主会话上下文抖动打断前缀」,非网关能力缺陷。

### 修正结论一句话
**opencode 网关底层确实在做 DeepSeek 自动前缀缓存、确实按缓存读价省钱;上节「~23% 命中率、结构性低、无解」是主控主会话上下文抖动打出来的 cc-switch 统计口径,不是网关缺陷。提高命中率的手段全在「行为层(减少主会话前缀打断)」,配置/整流/插件层要么已就位(cc-switch 剥 cch=)、要么对这条链路不生效。**

### I. 底层缓存真实命中且省钱(直接 curl 黑盒复现)
| 测试 | 响应 usage | 结论 |
|---|---|---|
| 冷启动:28k-token 固定 system + Q1 | cached_tokens=0, prompt=28008 | 全价,miss 写入缓存 |
| 字节完全相同的第 2 发 | cached_tokens=27904, prompt=28008 | 99.6% 前缀命中 |
| 真实增量对话:system+Q1+A1,追加 Q2 | Q2 cached=29952/30027 | 99.8% 命中,仅 ~75 新 token 全价 |

- opencode 响应**透传 `usage.prompt_tokens_details.cached_tokens`**(非恒空;上节「恒空」只是主会话未命中请求恰为空)。cc-switch `openai_cache_read_tokens()`(usage/parser.rs L12-23)解析它 → 非零 cache_read 是 opencode 真实上报,非瞎估。
- 省钱证据:opencode 有 Cached Read 档($0.007/M off-peak ≈ 全价3%);按请求跟踪 cached_tokens 单独定价。诚实标注:该 key 响应 cost 恒 "0",`v1/usage` 只给配额不给账单明细,无法独立验算每笔扣费;但「命中按缓存读计」是发布定价+字段跟踪共同支撑。
- 配额副作用:opencode 对该 key 强 rolling 限流,连发会 403(rolling 63→72%,按小时重置),间隔 20-30s 恢复;脚本化压测会被掐,属正常限流非封禁。

### II. 主会话命中低 / 00:37 掉零 = 会话态前缀打断
cc-switch db 按请求来源分解(本窗口):
| 来源 | 请求数 | input | 命中率 | cache_read 特征 |
|---|---|---|---|---|
| claude-opus-4-8(主会话) | 67 | 8.2M | **5.8%** | 均值 7.1k/个(max 131k) |
| deepseek-v4-think(子agent) | 63 | 4.0M | **52.6%** | 小 input 带 36k-135k 缓存读 |
| deepseek-v4-flash(执行) | 16 | 0.53M | **53.8%** | 同上 |

- 子 agent 铁证:`input=202 cache_read=143104`、`input=432 cache_read=135424` —— 短请求骑在已稳定大前缀上命中 ~99%。**短前缀也能吃缓存,不存在"前缀太短够不到阈值"**(插件源码注释记 DeepSeek 最小命中 64 token,引第三方)。
- 主会话:input 均 12.3万/个,但 cache_read 均 7.1k → 只有开头极短稳定段命中,首个字节级分歧点后全 miss;偶发 131,328(99.8%)= 那轮前缀恰好全稳定。
- 00:37 掉零:db 时间轴 cache_read 从 00:37:15 连续归 0,同一时刻主会话 input 从 162,976 降到 153,133(被 compact/重排,变小非增大)→ 前缀被改写 → 从分歧点后全失效。会话态原因,非配置/网关变化(00:37 前后无配置/plist/重启改动)。**掉零=当前会话态,非永久**;`/clear`/`/compact` 后重起稳定前缀缓存即恢复(全新对话实测 cold=0→hot=99.6%,机制健在)。

### III. 用户两方案核实
**方案一 `CLAUDE_CODE_ATTRIBUTION_HEADER=0`:无效**
- 该 env 是 Claude Code 直连 Anthropic 场景的 attribution 头开关(changelog L169 明示 "direct Anthropic API connections")。
- attribution 是 HTTP header,不进 messages body;DeepSeek 前缀缓存 key 的是请求体字节 → header 变不影响前缀 → 开/关都改不了命中率。
- 真正会进 body、逐轮旋转破坏前缀的是 `x-anthropic-billing-header cch=<值>` 行,**cc-switch 已主动剥掉**(源码 transform.rs strip_leading_anthropic_billing_header,注释:"rotating cch= 每请求变化阻止 prefix 缓存复用 #2350")。→ 不值得实测。

**方案二 中间层/插件整流:cc-switch 已做关键整流,其余不生效**
- `opencode-deepseek-cache` 插件(npm @2.2.0,2026-06-04,MIT,含 dist: session-manager/system-transform/fingerprint/strategy-deepseek)——**实体为真非幻觉**;但**对本链路双重不生效**:①peerDependencies @opencode-ai/plugin,用 opencode 客户端 hooks,需 opencode CLI/desktop 进程;我们是 Claude Code→cc-switch→纯 HTTP API,无 opencode 客户端,插件不加载。②isApplicableDeepSeek() 硬编码只认官方端点 api.deepseek.com,opencode.ai 不匹配。
- cc-switch 已是「修前缀」角色:剥 cch= + 不注入 timestamp/UUID/session/排序 + 只合并多 system 块到 index 0(join \n);无对 body 其它动态内容(tool 输出的时间戳/cwd)的通用 normalize(那属会话内容,整流不了也不该整流)。
- 自建整流层(8899/15721 间插一层):成本=开发代理,收益有限,不推荐。

### IV. 可做/不可做清单
**可做(行为层,零成本,直接提命中)**:①主会话及时 /clear 或 /compact 固化稳定前缀(趁缓存热 compact 成本 ~10%,§5.5) ②长工具输出落盘不贴回 ③子 agent 只回结论不灌回全文 ④认清「统计难看≠多花钱」:子 agent(52-54%)确实在按缓存读省钱。
**不可做/已失效**:改配置/整流提命中无新增空间(cc-switch 已剥唯一 body 级动态前缀 cch=);`opencode-deepseek-cache` 插件不生效;attribution header 无效;自建整流层价值低。
**核心回答**:在「继续用 opencode + 不关思考」下,缓存命中率能改善——手段全在行为层(减少主会话前缀打断),配置/整流/插件层要么已就位要么不生效。

### 复现(追补)
- 直连 opencode 黑盒缓存:同一请求连发两次,看 cached_tokens 从 0→大(99%+);文件 /tmp/resp1.json(cold=0)/tmp/resp2.json(hot=27904/28008)/tmp/m1.resp/tmp/m2.resp(99.8%)。
- 命中率分解:`cp ~/.cc-switch/cc-switch.db /tmp/x.db; sqlite3 /tmp/x.db "SELECT request_model,COUNT(*),SUM(input_tokens),ROUND(100.0*SUM(cache_read_tokens)/SUM(input_tokens),1) FROM proxy_request_logs WHERE provider_id='4835da8a-5c0a-4827-b25b-42aff34a8d57' GROUP BY request_model"`(全时间 /tmp/ccr-ro-2.db)。
- cc-switch 剥 cch= 源码:https://github.com/farion1231/cc-switch transform.rs strip_leading_anthropic_billing_header(L12-36)+单测 L787-855;cache_injector 仅 bedrock(forwarder.rs L482-486)。
- 插件实体:https://registry.npmjs.org/opencode-deepseek-cache ;npm pack 看 dist + strategy/deepseek.js 注释(64-token/50x)。
- attribution 限直连:~/claude/cache/changelog.md L169。
- 数据截止:2026-08-21 01:00(北京)。
