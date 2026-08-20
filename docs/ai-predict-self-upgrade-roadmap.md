# AI 预测体系自升级路线图（2026-08-20 定，用户授予自升级驱动权）

> 目的：承载 AI 预测体系（`scripts/gen_daily_brief.py` 每日 AI 速递）从「猜方向离谱」升级为「投顾式多因子方向研判 + 影响面图谱 + 反思因子自适应校准」的完整迭代路线。
> 定位：不是单份报告，是**迭代跟踪总纲**——每轮调研/实施/验证的成果、下一步、验证口径都挂在这份上，让 AI 预测持续变准（业界 AQuA「持久研究状态」哲学）。
> 职责：主控自主推进（用户 2026-08-20 授：「核心是看你自己自升级驱动，我只在关键处提醒点拨」）；仅在动核心功能默认值等方向性分叉时拉用户拍板（§23.7）。

---

## 一、为什么升级（一句话根因）
用户反馈"AI 预测越错越离谱"。三份调研证实**不是 AI 变笨，是三层缺环叠加**：
1. **核心锚误读**：期货机构持仓被当"全时段反向逆向"线性用（全时段仅 49.2% 无效）；正确形态=**转向日非对称**（转空日逆势看涨 66%、转空+均线多头 84%）。8/14/8/17 猜反正是把"转空"当偏空导致。
2. **反思不注入本质**：只记录"错了"（失败描述），没「归因到具体因子→调系数」；且 8/14 归因学错固化了错误。
3. **关键信号未用对**：影响面图谱缺失——行业联动/宏观共同因子/转向信号没进预测的调用逻辑。

详见根因报告 `docs/ai-predict-offtrack-rootcause-20260820.md`。

## 二、目标（北极星）
**影响面知识图谱**：AI 一看到某个消息/信号，就能瞬间定位它会扩散到哪（联动因子）、是否触发转向（转折因子），从而精准预测方向。用户原话：「你要挖掘出这些联动因子和转折因子，才能让你捕获一些消息就知道影响面，然后预测精准。」
已落成的图谱：`docs/ai-predict-direction-market-winning-signals-20260820.md`「影响面知识图谱」节（A 联动 L1-L10 / B 转折 T1-T8 / C 调用逻辑）。

## 三、已闭环调研（成果基线，勿重挖）
| 报告 | 核心结论 | 状态 |
|---|---|---|
| `docs/ai-predict-offtrack-rootcause-20260820.md` | 三层缺环根因 | ✅ 已落档 |
| `docs/ai-predict-direction-market-winning-signals-20260820.md` | 信号胜率榜+影响面图谱(311行,10脚本) | ✅ 已落档 |
| `docs/ai-predict-director-industry-method-20260820.md` | 业界多因子/背向修正/HMM/漂移监控(178行,36URL) | ✅ 已落档 |
| `docs/ai-predict-shadow-validate-20260820.md` | 方向锚/归因影子模式 7 天 A/B 验证(定义+协议+复现) | ✅ 已落档(实施期) |

**已确证方向锚（白名单）：**
- 任一强转向 OR → 次日涨 65%（n=254，逐年55/66/79）——喂预测首选合成器
- top20IC 转空+均线多头 → 84.2%（n=38，三年78/79/100）
- 机构转多族（IM/IH/中信IM）→ 64-66%（三年正）
- 非对称结构：**转空日逆势看涨**（全时段反向 49.2% 是错的用法）

**辅助印证（弱正，环境级）：**
- 美债10Y上行→黄金跌 60.8%（n=2244）；利率下行通道→A股54.5%+黄金57.0%双强
- 纳指隔夜→A股电子 55.7%；行业全跌反弹 59.3%；交割日 60.9%（不稳，只做波动提示）

**黑名单（别喂）：** 全时段中信逆向、情绪分/恐贪、美股整体隔夜→A股整体、日韩、超跌反弹、北向/两融增量、黄金/原油→A股行业、中美利差。

**待补数据（诚实标注）：** 美股行业ETF(XBI医药/XLK科技)、美元指数DXY、美联储议息日历、美国实际利率、期权隐波斜率、行业拥挤度。

## 四、实施路线（分轮，每轮验证再铺开）
### 第一步：方向锚改造 + A/B 验证（当前）
- **范围**：按图谱 C 节调用逻辑，改 `gen_daily_brief.py` prompt，显式加——
  - 转折因子：top20IC 转空/IM 转多/IH 转多 → "转空日逆势看涨、转多日顺势看涨"
  - 联动/背景：利率环境分档（降息通道 A股+黄金双强背景）
- **配置**：`daily_brief.yaml` 加开关（先默认关，线上行为不变，可 A/B）
- **验证**：离线回放 A/B（用 8/14/8/17/8/18 三个误判日，喂新 prompt 看方向是否修正）→ 可行性查证中（researcher）
- **不改**：状态机/HMM、打分制、漂移监控、反思因子校准（后续轮次）

**✅ 第一步实施记录（2026-08-20,implementer）**
- **prompt 加方向锚语义教学**（改造落点）：
  - `gen_daily_brief.py` 新增 `_compute_direction_anchor(db_path,date)`（按 date 从 sentiment.db 只读取：futures_position 转向日 net_chg 检测/日均线多头/index_daily sh vs ma20/daily_metric us10y·gold·nq_chg·利率通道）+ `_direction_anchor_semantics(factors)`（转中文教学段）。
  - 注入两处系统提示（栅 `cfg.direction_anchor_enabled`）：
    - `build_prompt` sys_text（单 prompt 主链路）`9a.【方向锚】`
    - `build_editor_messages` sys_text（多角色主编链路）`{next_rule+1}.【方向锚】`
  - 语义=转折因子 T 主权重（转多顺势看涨 64-66% / 转空逆势看涨 84%+65%）+ 联动/压制因子 L 辅助（美债10Y→黄金/利率通道背景/nq_chg 纳指大跌压制看多）。
  - **T/L 必须一起加**（核心设计）：只加 T 不加 L，8/14 改对但 8/18 改错（8/18 nq_chg=-1.302 压制转多），已在语义段显式标注 L3 压过 T1。
- **config 开关**：`daily_brief.yaml` `direction_anchor_enabled: false`（默认关=线上 prompt 逐字不变，可 A/B）。
- **独立回放脚本** `scripts/replay_direction_anchor.py`（方案A 零侵入）：`--date --direction-anchor on/off --no-call --dump [--multi]`，复用 build_prompt/build_editor_messages/call_deepseek/parse_ai_output，**绝不 write_outputs/不通知/不上传/不写 history**（障碍②绕过）。`--no-call` 0 成本 dry 校验方向锚语义是否进 sys_text。
- **dry 自验（--no-call）**：三样本 8/14（top20IC转空-1293+均线多头→逆势 up）8/17（国泰综合+3447转多→顺势 up）8/18（中信综合+4858转多+**L3 nq=-1.30 压制看多→应 down**）方向锚语义均正确注入；off 开关下 dump sys_text 无『方向锚』=线上 prompt 逐字一致。
- **✅ 离线回放 A/B 验证（2026-08-20 18:03 高峰后跑完，单 prompt off/on 三样本）**：
  | 样本 | 实际 | off(原prompt) | on(方向锚) | 效果 |
  |---|---|---|---|---|
  | 8/14 | up +1.41 | down ❌ | down ❌ | 未修正 |
  | 8/17 | flat +0.19 | down ❌ | **up ✔** | **修正** |
  | 8/18 | down -2.40 | down ✔ | down ✔（引用L3压制转多） | 保持对+更稳 |
  - **结论**：方向锚对 2/3 有效（8/17 修正、8/18 L3 纳指压制 T1 转多=方向锚设计关键验证点通过），8/14 未修正（模型读到"机构转空+均线多头矛盾"但受量价齐跌强空覆盖，仍判 down）。
  - **迭代点**：8/14 暴露 prompt 语义教学边界——80%+ 逆势锚被模型当"参考"而非"倾向结论"，量价齐跌可覆盖。下一迭代把方向锚从"参考"提升为"倾向性结论"（机构转空+均线多头→应明确偏涨，除非强反证）。
  - **诚实标注**：3 样本为方向性前测非统计显著；严格 A/B 需真实交易日 7 天。
- **key 依赖 note**：回放脚本需 DEEPSEEK 变量加载自 `../trade-data/.env`（本仓库 .env 无 key），跑前 `set -a; source ../trade-data/.env; set +a`。

**✅ 反思=因子归因回灌实施记录（2026-08-20,implementer,提前落地「后续轮次3」TA Reflector 内核）**
- **动机**：用户质疑「只肤浅套用 TradingAgents 多 agent 辩论」。TA 价值内核=反思不只记"错了"，而是把错归因到某方/某因子→调该方 memory→回灌下次辩论上下文。我们旧反思只规则级归因（failure_type+一句 summary），没归因到具体误导因子，也没回灌该因子近期表现。
- **实现（commit 9a47bae97）**：`gen_daily_brief.py` 新增 `_attribut_factor`（失败日复用 `_compute_direction_anchor` 现算当日因子，归因到 L3纳指大跌压制看多/转空信号被当偏空/T1顺势看涨或均线多头强规则/T1当日失效/板块层失真，落盘 `factor_attribution`）+ `build_attribut_inject`（聚合 top 误导因子+连续出错倾向，生成「待规避因子」约束段叠加进 `build_reflection_inject`）。config 开关 `reflection_factor_attribution_enabled: false` 默认关=线上注入逐字不变。与方向锚互补不互斥（同源同 DB 只读）。
- **README 措辞修正**：AI 速递编排受 TradingAgents-CN/原版多智能体辩论架构启发，但预测所用方向锚信号胜率/因子权重为自研 8 年数据挖掘成果，非抄；致敬 TradingAgents 段保留。
- **自验**：真实 DB 三样本 8/18→L3纳指大跌压制看多（nq=-1.302）、8/17/8/14→转空信号被当偏空+T1顺势看涨，归因与方向锚回放结论一致；cfg 无开关 key 与显式 False 时注入文本逐字一致（off 线上不变）；on 聚合归因段正确。详见 `docs/ai-predict-reflection-factor-attribution-20260820.md`。

**✅ 影子模式验证实施记录（2026-08-20,implementer,用户拍板"7 真实交易日用数据决定开/不开/改"）**
- **动机**：方向锚/归因都已合入但全默认关——"关着=一点数据都不采"；用户要 7 天真实 A/B，必须先有影子旁路把"方向锚会预测什么方向"逐日落盘，次日回填实际，聚算命中率再拍板。契约全文 `docs/ai-predict-shadow-validate-20260820.md`。
- **实现**：
  1. `gen_daily_brief.py` 新增 `_shadow_lean(factors)`（与 `_direction_anchor_semantics`/**`_attribut_factor`** 同源同因子字段合成 lean：任一强转多→up；强转空→逆势 up；L3 纳指大跌→压过看多打回 flat；无T+均线多头→soft up；均无→flat）+ `record_shadow(date,cfg,db,repo)`（按 date 旁路落盘 `data/brief_shadow.json`，幂等去重老日期保留）。
  2. `main()` load_data 后新增旁路调用（无论方向锚开关开否都算一次，写在 AI 生成前保证 AI 降级也有影子样本）；`_compute_direction_anchor` 加同 (db,date) FIFO 缓存，影子+实列同键只读一次 DB（"不算双份"）。
  3. `scripts/aggregate_shadow.py`（新建）：回填影子记录下一交易日 sh 实际方向（index_daily，HIT_THRESHOLD=0.5 同 `_actual_direction` 口径，幂等）+ 聚算（命中率/按lean分桶/top误导向量/flat空转单列），支持 `--date` 单日对账、无 DB/无下一交易日落空不硬判。
  4. `config/daily_brief.yaml` 加 `shadow_mode_enabled: true`（默认开=收集数据，但只控制旁路落盘，不注入线上——线上仍由 direction/reflection 两闸决定，默认关=prompt 逐字不变）。
- **零注入自验证据**：`direction_anchor_enabled=false` 时 dump `build_prompt` sys_text，`方向锚/T2/T3逆势看涨/压制信号/转空/shadow` 全 False（影子串零泄漏，线上文本逐字一致）。
- **影子语义与实列同源证据**：影子 lean 与回放/归因读同一批 `turns(MA)/ma_bull/nq_chg/nq_open_low/rate_down_channel` ，8/19 真实样本 to_short×4 且无 L3 → lean=up("T2/T3转空×4(逆势看涨8/14·8/17)")，与语义"转空逆势看涨"逐字同构。
- **待 7 天数据决策**：满 7 真实交易日后跑 `python scripts/aggregate_shadow.py` 最终聚算，主控报用户拍板开/不开/改（shadow 不影响线上默认，§5.4⑥ 未发版本）。

### 后续轮次（每轮独立验证，不一口吞）
1. **打分制合成**（华泰 A₂ 分层投票，每信号+1/0/-1，只留方向不带仓位）
2. **状态识别**：先四子路径状态依赖（追高/抄底/追空/逃顶），进阶 HMM 状态机
3. **反思=因子自适应校准**（用户哲学核心）：每次猜错→归因到误导因子→调该因子系数（连续错降权/改方向、连续对升权）——业界漂移监控60日滚动+在线回放衰减同构
4. **辅助印证降级**：交割日→波动提示、波浪→背景标签、国家队→底部确认、亚太→极端预警
5. **仓位=凯利×状态置信度**（衔接 §5.4 测试基准锚点）

## 五、自升级驱动纪律（用户授，主控须持）
1. **不干等指令**：按证据推演下一步，主动推进；调研闭环即判断"最该先动哪个抓手、怎么验证"。
2. **主动暴露不确定/风险**：样本少、离线回放非严格A/B、玄学因子幸存者偏差……主动说清，不粉饰（§5.1④诚实标注）。
3. **边做边沉淀**：每轮落档 `docs/ai-predict-*`，update 本路线图，形成可复用研究状态。
4. **关键处才拉拍板**：仅动核心功能默认值等方向性分叉（§23.7）问用户；实施细节自行推进。
5. **测试基准**：本体系升级属 AI 预测核心（§5.4⑥动核心必发版本）；涉及回测/验证落当前基准 memory `test-baseline-v112-anchor`。

## 六、复现/追踪
- 各报告复现段见各自 md；信号挖掘脚本在 `docs/ai-predict-direction-market-winning-signals-20260820/scripts/`。
- 本路线图为跟踪总纲，每轮实施完毕后 update；不重挖已闭环调研。
- 相关既有文档：`docs/daily-brief-research.md` / `docs/ai-predict-self-growth.md` / `docs/ai-predict-inject-research.md` / `docs/ai-predict-multiagent-plan.md`。
