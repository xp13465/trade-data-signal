# OpenRouter 成本/速度优化调研报告(2026-08-23)

> 触发:用户切 openrouter 中转跑 Claude Code,点名三个方向(缓存命中率优化/子 agent 深度思考按需控制/关联网搜索额外收费)+授权自查额外方向。核心诉求=省 token、省钱、提速。
> 方法:官方 docs 7 篇 + 官方博客量化数据 + GitHub issue/社区交叉验证 + 本机配置现状只读核查。关联既有经验:memory `opencode-cache-think-findings`(缓存低命中主因=主会话上下文抖动)、`deepseek-thinking-perrole-proxy`、`claude-code-output-config-effort-400`(effort 藏 output_config.effort 的 400 坑)。
> 来源链接全量见文末;待验证项诚实标注见 §六。

## 零、本机现状(证据:`~/.claude/settings.json` + env)

| 项 | 现值 | 判读 |
|---|---|---|
| ANTHROPIC_BASE_URL | `https://openrouter.ai/api` | 直连 OR 的 Anthropic 兼容端点(Anthropic Skin),无中间代理 |
| 主模型/子agent | `stealth/ox-alpha` | 定价与缓存折扣未知(内部模型),待 Activity 页核实 |
| opus/sonnet/fable 档 | `z-ai/glm-5.2:free` / `nvidia/nemotron-3-ultra-550b-a55b:free` / `openrouter/free` | 已零成本 |
| 顶层 model | `"haiku"` 档 → 映射 ox-alpha | — |
| CLAUDE_EFFORT | `high`(env) | 主会话+子 agent 全局高思考 |
| ANTHROPIC_API_KEY | 未显式置空 | 当前 env 无此变量无实际冲突,但有隐患(清单#2) |
| AUTH_TOKEN | settings.json 明文存放 | 安全隐患(清单#2) |

## 一、方向1:缓存命中率(收益最大的一块)

**机制结论(官方文档确认)**:
1. **cache_control 生效且透传**:OpenRouter 对 Anthropic 支持顶层自动缓存和块级显式断点两种,Claude Code 原生请求自带的块级 cache_control 断点(system/tools/messages)经 Anthropic Skin 原样透传。社区证据:坏的是「再套一层代理」场景(Bifrost 曾静默剥掉 cache_control 致 0 命中),**直连 OpenRouter 的同一请求缓存正常**(github.com/maximhq/bifrost#3942:"identical request sent directly to OpenRouter worked fine")。本机是直连,无中间层,机制上应正常。
2. **定价倍率(Anthropic)**:写 1.25x(5分钟TTL)/ 2x(1小时TTL),**读 0.1x**(缓存命中只付一折 input 钱)。OpenRouter 不加价原样透传(FAQ:"no markup on inference pricing")。
3. **Sticky routing 自动开启**:缓存请求后自动把后续同会话请求钉回同一家 provider 保缓存;10 分钟空闲过期(每次成功请求重置);provider 挂了自动换下一家。
4. **会话识别方式**:默认按「首条 system 消息 + 首条非 system 消息」哈希。Claude Code 会话内这两条固定→天然粘住。子 agent 各有独立 system prompt→自然分会话互不干扰。**手动设 provider.order/sort 会禁用 sticky routing**(文档原文),重要反面约束。
5. **最小可缓存长度**:Sonnet 系 1024 tokens,Opus/Haiku 4.5 系 4096——低于就不缓存。

**官方量化收益**(博客《The Cheapest Token is a Cached One》2026-07-21):6 轮会话重复同样 10k token 前缀,无缓存=6.0x 成本,5min 缓存+sticky=**1.75x,约省 70%**。

**真实风险点(诚实标注)**:
- **10 分钟空闲过期**:人肉会话中途离开再回来,那轮要重新付 1.25x 写入。Claude Code 不发 `ttl:"1h"` 参数,无法替它改请求体→1 小时 TTL 在 Claude Code 场景**不可落地**(待验证:preset 能否覆盖消息级字段,大概率不能)。
- **验证方法(必做)**:OpenRouter Activity 页点开任一 generation 看 `cached_tokens` 和 `cache_discount`;或 curl `/api/v1/generation` API。命中>0 且 discount 转正=缓存在工作。所有优化的前提——先量化再动手(§5.1 数据说话)。

**提高命中的可行手段(全部零成本)**:
- 保持 CLAUDE.md / skills / agent 定义等前缀内容**稳定**——每改一次=全员缓存全冷(memory `opencode-cache-think-findings` 已验证一致);
- 会话尽量连续,长会话优于频繁开新会话(sticky 10 分钟窗口内最划算);
- 时间戳/动态内容别进前缀(官方博客 miss 四大原因之一);
- 不给模型加 provider.order / :floor / :nitro(都会禁用负载均衡/sticky,详见方向4)。

## 二、方向2:深度思考按需控制

1. OpenRouter 统一 `reasoning` 参数:`effort`(max/xhigh/high/medium/low/minimal/**none**)、`max_tokens`、`exclude`、`enabled`。Anthropic 映射公式(文档原文):`budget_tokens = max(min(max_tokens × effort_ratio, 128000), 1024)`,effort_ratio:max/xhigh=0.95、high=0.8、medium=0.5、low=0.2、minimal=0.1。
2. **关键纠偏:`exclude: true` 不省钱**。推理 token 照常生成、照常按输出计费,只是不在响应里显示("The model consumes the same number of tokens either way...")。省的只有传输体积。**真省 token 只有三条路:降 effort、关思考(none)、换便宜模型**。
3. **落地位置在客户端不在网关**:Claude Code 自己发 thinking 参数,Skin 原生透传;OpenRouter 侧没有「按子 agent 注入 reasoning 配置」的通道。控制点:
   - `MAX_THINKING_TOKENS=0` 或启动参数 `--thinking disabled` 可关思考——但**全局生效(含主会话和所有子 agent)**,且有已知坑:设高值会强开思考、子 agent 输出上限不同可能静默崩(github.com/anthropics/claude-code/issues#27429、#65785);
   - **effort 参数是现代正道**:官方文档明确建议 subagent 用 low("docs suggest low effort for subagents since they typically need speed/cost efficiency")。high→low 相当于 thinking budget 从 max_tokens 的 80% 降到 20%,thinking 占输出大头时输出费省一半以上;
   - 分角色差异(实施/测试关、reviewer/researcher 留):延续 memory `deepseek-thinking-perrole-proxy` 思路,但注意 400 坑(memory `claude-code-output-config-effort-400`:新版 effort 藏 `output_config.effort`)——直连 OpenRouter 时 Skin 对该字段的处理**待验证**;
   - 现状 CLAUDE_EFFORT=high 是全局的:日常主会话降到 medium、重活临时调回,是最简单的一档。

## 三、方向3:联网搜索收费

**结论:当前配置没有也不会产生这笔费用,零动作即安全。**
1. OpenRouter 服务端搜索只在**显式 opt-in** 时触发:`plugins:[{id:"web"}]`、`:online` 后缀(**FAQ 已标 deprecated**,替代品是新 server tool `openrouter:web_search`)、或 preset 里挂了 web 工具。不传任何这些=无插件无费用,**不需要显式 plugins:[]**。
2. 计费标准(若误触发):native 引擎按 provider 原生价透传(Anthropic web search 约 $10/千次量级);Exa $0.007/起;Parallel/Perplexity $0.001-0.005/次(web-search 文档 Pricing 节)。
3. **与 Claude Code 自带 WebSearch 完全独立**:Claude Code 的 WebSearch 是客户端工具(模型发调用→本地执行→结果回灌),只产生普通 token 计费,不走 OpenRouter 服务端插件。只要不用 :online 后缀、不自建挂 web 工具的 preset,服务端搜索费恒为零。社区也警告":online 贵且效果差"(aireiter.com 聚合 Reddit 反馈)。

## 四、方向4:额外方向自查

| 方向 | 结论 | 依据 |
|---|---|---|
| :floor 价格变体 | **不推荐用于 Claude Code 主链路**。flex 低价层只有 OpenAI/Google 提供,Anthropic 无 flex;且 sort 类设置会**禁用负载均衡+sticky routing,牺牲 70% 缓存收益换 10-30% 单价**(社区数据 aireiter.com),长会话代理场景净亏 | service-tiers/provider-routing 文档 |
| :nitro | 加价提速(priority tier),与省钱目标相反,不用 | service-tiers 文档 |
| fallback 静默切贵 | 默认路由在 provider 故障时会 fallback 到更贵端点(Reddit 常见坑),但也是可用性代价,接受即可,别用 order 锁死 | aireiter.com 聚合 |
| BYOK | PAYG 计划每月前 $25,000 list-price 用量零手续费,超出收 5%;BYOK key 永远优先路由。若有官方 Anthropic key 可评估接入(官方原生费率+几乎零中转成本),ox-alpha/free 模型不适用 | byok 文档(BYOK_FEE_PERCENTAGE=5, threshold=$25,000) |
| 充值手续费 | Stripe 5.5%(最低 $0.80),crypto 也有费;推理零加价无量贩折扣→省钱只能从用量和缓存下手 | FAQ |
| Zero Completion Insurance | 零 token 响应不收费(兜底知识) | llms.txt 索引 |
| 成本可视化 | 官方提供 Claude Code statusline 脚本实时显示累计花费+缓存折扣(claude-code-integration 文档 Cost Tracking 节) | github.com/OpenRouterTeam/openrouter-examples |

## 五、可立即执行的配置清单(按收益排序)

1. **【先做·量化基线】** 上 openrouter.ai/activity 点开几个 generation 记 `cached_tokens` 占比与 `cache_discount`——确认 ox-alpha 与 free 模型的缓存实况。数据说话,后续所有优化以此为准。(0 成本,10 分钟)
2. **【防坑】** settings.json env 补 `"ANTHROPIC_API_KEY": ""`(官方 Quick Start 要求,防未来 shell 残留真 key 时静默切直连计费);AUTH_TOKEN 建议挪 macOS keychain(`security find-generic-password` 方案,官方 Secret hygiene 段)——明文 key 本次调研已被读到过上下文,顺手轮换更稳。**需用户拍板后实施**。
3. **【省输出费】** CLAUDE_EFFORT 从 high 降 medium 作日常默认,重活临时调回;实施/测试类子 agent 派单按官方建议用 low effort。**不要用 exclude:true(不省钱)、不要 MAX_THINKING_TOKENS 设高值(全局强开思考+子 agent 崩溃风险)**。预期:thinking 相关输出费降 50%+(high 80%→low 20% budget)。**需用户拍板后实施**。
4. **【保缓存·行为纪律】** 前缀稳定(高频改动内容不进 CLAUDE.md/agent 定义前段)+ 会话连续(<10 分钟间隔)+ 少 spawn 小 agent(§5.5⑤ 本就有)。预期:多轮会话输入费最多省 70%(官方博客 6.0x→1.75x)。
5. **【不做清单(等于省)】** 不给任何模型加 :floor/:nitro/order(毁缓存);不用 :online(弃用+贵);不自建挂 web 工具的 preset。当前配置在这三项上已经是干净的,保持即可。
6. **【可选·中期】** 若拿到官方 Anthropic key,评估 BYOK(月 $25k 内零手续费、官方原生缓存费率、key 优先路由);ox-alpha 主力模型不受影响。
7. **【监控】** 装官方 cost statusline 或继续用 ccusage,让花费可见(看不见=管不住)。

## 六、待验证项(诚实标注)

① ox-alpha 实际单价与缓存折扣(Activity 页可查,需登录);② Claude Code 是否自发 session_id/x-session-id(现版无证据,不影响默认哈希粘性);③ preset 能否覆盖消息级 cache TTL(大概率不能);④ Anthropic Skin 对 `output_config.effort` 字段的透传行为(关联 memory `claude-code-output-config-effort-400`)。

## 复现

- 调研方式:WebFetch 官方 docs(下方链接)+ GitHub issues + 社区聚合,无本地脚本依赖;本机现状核查=`~/.claude/settings.json` 只读 + env 查看。
- 关键判定复核入口:OpenRouter Activity 页(generation 级 cached_tokens/cache_discount);缓存机制验证可 curl `/api/v1/generation?id=<generation_id>`。
- 数据版本:官方文档为 2026-08-23 时点快照;博客量化数据出自 openrouter.ai/blog/tutorials/prompt-caching-sticky-routing(2026-07-21)。

## 来源链接

- Prompt Caching: https://openrouter.ai/docs/features/prompt-caching
- 官方博客(量化对比): https://openrouter.ai/blog/tutorials/prompt-caching-sticky-routing
- Reasoning Tokens: https://openrouter.ai/docs/use-cases/reasoning-tokens
- Provider Routing: https://openrouter.ai/docs/features/provider-routing
- Service Tiers: https://openrouter.ai/docs/guides/features/service-tiers
- Web Search(计费): https://openrouter.ai/docs/features/web-search
- Claude Code 集成(Anthropic Skin/fast mode/statusline): https://openrouter.ai/docs/cookbook/coding-agents/claude-code-integration
- Presets: https://openrouter.ai/docs/guides/features/presets
- BYOK: https://openrouter.ai/docs/guides/overview/auth/byok
- FAQ(:online 弃用/5.5% 手续费/无加价): https://openrouter.ai/docs/faq
- Bifrost 剥 cache_control 案例: https://github.com/maximhq/bifrost/issues/3942
- sticky 与 TTL 解耦 issue: https://github.com/OpenRouterTeam/ai-sdk-provider/issues/499
- Claude Code thinking 控制: https://github.com/anthropics/claude-code/issues/65785 、#27429 、https://platform.claude.com/docs/en/build-with-claude/effort
- 社区价格聚合(:floor 10-30%/online 差评): https://aireiter.com/blog/openrouter-pricing-guide-2026
