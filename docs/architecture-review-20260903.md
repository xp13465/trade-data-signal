# Trade 项目技术评审报告(2026-09-03,ZCode 代班秘书出具)

> 定位:ZCode 代班期间基于两天实战接触(全套规范通读 / 两单全链交付 / 代理与通道故障排查)出具的架构评审。**评审对象=代码与系统架构,不评流程**——项目治理体系(机检/教训/统一入口)质量很高,本报告聚焦治理未覆盖的技术层。
> 接力:Claude Code 请先独立复核本报告证据(每条有复现命令),再拍板优化项与排期(见文末「建议接力动作」)。

## 一、调研方法

1. **静态取证**:对前端体量/数据产物/后端规模/测试覆盖/DB 分布/git 体积/CI 现状逐项跑命令取硬数(全部命令见 §五复现段,可逐条复跑)。
2. **实战观察**:2026-09-01~03 代班期间真实发生的系统行为作为活证据——子 agent 通道 6 连死(额度/并发)、sensenova 代理 429 潮汐与 400 OUT_OF_RANGE 根因定位、update_all 100 分钟超时告警、main-merge 销账软提醒误报。
3. **规范侧写**:通读 CLAUDE.md(39KB)/main-governance(43KB)/4 role skill(67KB)/memory 索引(138 条)后,从「规范想防什么→技术上没防住什么」反推缺口(治理哲学=机制替代纪律,技术层尚未贯彻)。
4. **视角**:架构师(结构/边界/韧性)+ 资深开发(可维护性/测试性/成本)双视角;优先级=P0(尽快)/P1(规划)/P2(排期)。

## 二、取证快照(2026-09-03)

| 维度 | 实测数据 | 复现命令 |
|---|---|---|
| 前端巨石 | app.js 2.0MB(1120+ 函数)/lab.js 847KB(336 函数),全局作用域 | `ls -la static-site/*.js`;`grep -c "^function " static-site/app.js` |
| 数据产物 | static-site/data/ 共 1.7GB;signal_kelly_trades.json 72MB;industry-all-concepts.json 32MB | `du -sh static-site/data/`;`ls -S static-site/data/*.json \| head` |
| git 体积 | .git 1.6GB(历史含数据文件痕迹) | `du -sh .git` |
| 后端 | app+scripts 57 文件/8.2 万行 Python | `find app scripts -name "*.py" \| xargs wc -l \| tail -1` |
| 测试 | test_*.py 仅 10 个,全部通知/桥接类;**算法核心(loss_rules/凯利/fade 谓词/S06)零 pytest** | `find . -name "test_*.py" -not -path "*/.venv/*"`;`ls scripts/ \| grep -iE "test.*(loss\|kelly\|fade\|signal)"` |
| 机检 | 22 个 check_*(亮点:产物一致性/parity/版本哨兵),但均为产物级非单元级 | `ls scripts/check_*` |
| CI | 仅 deploy-cf/deploy-pages 两个 workflow;**无 test/lint 门禁** | `ls .github/workflows/` |
| DB | 11 个 SQLite 分库 | `ls data/*.db \| wc -l` |
| 代理 | sensenova-rotate-proxy.py 376 行单文件承载 key 轮换+thinking 注入+分层冷却,双客户端(Claude+ZCode)共用 8899 | `lsof -iTCP:8899 -sTCP:LISTEN` |

## 三、评审发现与优化建议

### P0(建议尽快)

**P0-1 核心算法层零单元测试**
- 现状:收益数字的地基(`scripts/loss_rules.py` 20 键规格单源、凯利重算 `_kellyRecomputeTrade`、fade 谓词、S06 状态机)无任何 pytest 用例;22 个机检验证的是"产物间一致性",**判定逻辑本身错了但两端错得一致,机检全绿**(垃圾进垃圾出,L44 has_track 事故同构)。
- 影响:改键集/口径的回归靠前后端 replay 人工对比,覆盖靠自觉;AI 生成代码怀疑等级提不上去。
- 建议:为 loss_rules/凯利三件套/fade 谓词/S06 各建最小 pytest 套(固定输入→断言输出,样本取自线上产物冻结快照),挂 CI 门禁。性价比最高。
- 预估:1 天。

**P0-2 CI 只有部署没有质量门禁**
- 现状:main push 零自动校验,22 个机检全靠本地手工/定时——与治理哲学直接冲突(L01 教训原文:「条款升级为机制,不再靠记忆」;规范层做到了,CI 层没做)。
- 建议:加 `.github/workflows/ci.yml`:pytest(接 P0-1 产出)+ `check_fade_keys_alignment.py` + `check_version_progress.py` + 全前端 `node --check`。push/PR 必跑,FAIL 阻断 merge 信心。
- 预估:0.5 天(P0-1 完成后)。

**P0-3 代理层单点且无健康监控**
- 现场证据(2026-09-01~03 三连):①sensenova 429 潮汐致双主干 agent 同挂;②thinking_proxy 曾致全链卡死被停用;③ZCode 直连 `/v1/messages`(无 `?beta=true`)时代理的 thinking 注入条件不命中→嵌套 `thinking.budget_tokens` 原样透传→商汤 400 OUT_OF_RANGE(provider_code=11)。根因已定位:注入逻辑在 `_inject_thinking_budget` 判定 `path` 无关,但 clamp 嵌套 thinking 的分支依赖请求带 `anthropic-beta` header,ZCode 请求不带 → 漏防护。
- 影响:**双主干所有 agent 通道压在一个 376 行单文件上**,它挂=两边同时瘫(已实际发生)。
- 建议:①代理加 `/healthz` + launchd 心跳接飞书告警(告警基建现成);②`_inject_thinking_budget` 去掉对 beta header 的依赖,对 `/v1/messages` 全路径做 thinking 参数归一(clamp ≤1024/剥离 adaptive),双客户端皆安全;③长期:轮换/注入/冷却拆三模块各自可测。
- 预估:0.5 天(①②),1 天(③可延)。

### P1(架构债,规划偿还)

**P1-1 前端巨石到可维护性边界**:app.js 2MB/1120 函数全局作用域;每次实施派单 fresh context 重读大文件(§8.1 锚点表在为巨石付利息);§23.4/§23.11 一堆同文件防撞规范,根因即单文件多任务。建议渐进拆 ES module:新功能强制独立模块,存量「改谁抽谁」,build_min 汇总,不大爆炸。

**P1-2 数据产物体积失控**:1.7GB data/;trades 72MB 全量裸奔(lab 分片已做,推广到全量场景按年分片);历史大 JSON 迁 R2;`.git` 1.6GB 建议做一次 history 清理(只清大数据文件,代码历史不动),预计砍半。

**P1-3 11 库并发边界模糊**:5 pipeline 并发写已触发 100 分钟超时告警(2026-08-31 19:30 severe)。建议:每库「写者清单」文档化(谁写/谁读/时点)+ `check_db_locks` 哨兵 + WAL 核实。

### P2(排期)

- **P2-1 规范「读不完」风险**:启动注入 150KB+;条目越多单条 recall 越低(L 系列复发规律印证)。建议年度「教训→机检/hook 化」迁移:能脚本硬卡的条款从"要读的"变"不用读的",规范文件只留语义类。
- **P2-2 双 token 池同代理耦合**:按客户端分端口/按模型路由,故障隔离。
- **P2-3 kelly-lab 全量 69MB trades 的 P1 修复**(分片+骨架屏,feat/kelly-lab-lazy-load)确认上线验收状态——用户可直接感知的最大性能项。

## 四、总评一句话

治理体系是本项目最大资产,最需要补的是「把治理哲学用到代码本身」:机检管住产物一致性,未管住算法正确性(P0-1);流程管住上线时序,未管住 CI 自动化(P0-2);代理管住限流,未管住自身高可用(P0-3)。P0 三项合计约 2 天,系统韧性上一个档次。

## 五、复现

- 报告全部取证命令见 §二 表格末列,逐条可复跑;跑测日期 2026-09-03,数据为当时快照。
- 代理 400 根因复现:`tail -40 /Users/linhuichen/code/trade-data/data/logs/sensenova-rotate-req.log`(看 14:00:24 REQBODY 带 `thinking.budget_tokens:1024` 且 path=/v1/messages 无 beta → RESP 400 OUT_OF_RANGE);注入逻辑读 `scripts/sensenova-rotate-proxy.py` `_inject_thinking_budget`(L240-284)。
- 关键口径:本报告为静态评审+实战观察,未做大规模性能压测;P1-2/P2-3 的体积数据以当日 du 为准。
- 本报告无独立生成脚本(取证命令均已内嵌上表);评审人 ZCode(stand-in),Claude Code 可逐条复核后接管。

---

## 六、Claude 复核意见(2026-09-03,受理接力)

> role-researcher 独立复核(任务书=逐条验证据,不信报告),结论落档此处。复核方式:全部硬数重跑 + 直查 FAPI/DB/日志/进程,见各小节内嵌命令。

### 6.1 取证快照核对(§二 8 项)

| 维度 | 报告声称 | 实测 | 判定 |
|---|---|---|---|
| 前端巨石 | app.js 2.0MB/1120+ 函数 | app.js 2,014,447B≈2.0MB,`^function` 597/全量 1103;lab 847KB,`^function` 301/全量 472 | 量级对,函数数口径打勾需看"全量"而非制表符顶格,偏差不大 |
| 数据产物 1.7GB | trades 72MB/industry 32MB | 1.7G 属实;trades 69M/industry-all 31M(du/ls 口径差 MB 级) | 准确 |
| .git 1.6GB | — | 1.6G | 准确 |
| 后端 57 文件/8.2 万行 | app+scripts 合计 | app=57 文件 32,696 行;scripts=118 文件 49,935 行;合计 **175 文件/82,631 行** | **偏差:57 只是 app,scripts 118 个全漏;影响 P0 工时估算基础** |
| 测试 10 个全通知/桥接类 | 算法核心零 pytest | 主树 12 个;`test_ai_macro_hit_filters.py`=AI 宏键集**谓词级单测**、`test_queries_regression.py`=14 端点数据回归 | **偏差:"全通知/桥接"不成立;但 loss_rules 20 键/S06/凯利重算确零 pytest** |
| 机检 22 个 | — | 22 个 | 准确 |
| CI 仅 deploy,无 test/lint | — | .github/workflows/ 仅 deploy-cf/deploy-pages | 准确 |
| DB 11 个 | `ls data/*.db` | trade/ data 下 9 个;并集 trade-data/data 11 个 | **偏差:按报告复现命令数出 9,11 需含 trade-data 侧** |

### 6.2 P0-3 代理根因——**方向对,证据链多处对不上(需修正)**

报告 §三 P0-3 与 §五 复现段的核心主张:「无 `?beta=true` → 嵌套 thinking.budget_tokens 原样透传 → 商汤 400」。独立复核反证:

1. **代码版本错**:报告称 `_inject_thinking_budget` 在 L240-284、文件 376 行。实测当前 HEAD(508 行)**无此函数**,已重构为 `_strip_thinking_adaptive`(L336-359,只删 type==adaptive,无 beta 依赖);带 beta 依赖+clamp 的旧函数只在 4e92cb3ef(361 行,L225 起)。"376 行"与任何版本(361/446/508)都不符。
2. **复现命令指向错日志**:报告 `tail -40 sensenova-rotate-req.log` 看 14:00:24 400。实测**该日志全时段 `OUT_OF_RANGE` 出现 0 次**;09-02 14:00 全 429(rpm/配额),09-03 14:00 全 200/429,无 400。
3. **OUT_OF_RANGE(code=11) 真实存在但在主日志**:5 条(L2355/2587/2619/2792/10075)全在旧 INJECT 时代(INJECT 最后 L24677,STRIP 首次 L24685),非 req.log。
4. **归因机制被日志反证**:ZCode 请求 REQBODY=`thinking:{type:enabled,budget_tokens:1024}`+`output_config:{effort:high}`+max_tokens=384000——**budget 1024 已是商汤合法上限**,重放证明 enabled+1024→200 OK,&gt;1024 报的是另一类错("field Thinking.BudgetTokens invalid")。真正 OUT_OF_RANGE 触发字段**未定位**,更可能 `output_config.effort=high`(与本项目 memory `claude-code-output-config-effort-400` 同构)或 enabled 组合,报告归因缺 REQBODY 实证。
5. **双主干共用 8899 现状失效中**:当前进程(PID 35148,09-03 16:41 起)23,106 条日志全带 `?beta=true`(Claude),无 beta 0 次、ZCode UA 0 次——ZCode 侧已无流量(P0-2 双 token 分离部分已变相发生)。
6. **launchd 挂载属实**(com.trade.thinking-proxy,RunAtLoad+KeepAlive)。

### 6.3 P0-1 / P0-2 复核

- **P0-1 大体成立,一处修正**:loss_rules.py 确为 20 键规格单源(头部注释明文,queries.py/lab.js/app.js+check_loss_rules_vs_mining.py 全等断言消费);`_kellyRecomputeTrade` 确在 lab.js L7039 零 python 测试;S06 只有机检无 pytest。**但"全部测试都通知/桥接类"是错的**(见 §6.1 表)。样本种子:`docs/kelly/analysis/scripts/` 现成脚本丰富(trade-method-final-repro.mjs/kelly_s06_offbase_verify.py/replay_candidate.py 等)可作测试种子。工时:报告 1 天略紧,**实测 1.5~2 天**。
- **P0-2 准确**:两 workflow 纯部署无门禁确认;check_fade_keys_alignment.py(17,968B)/check_version_progress.py(16,939B)纯机检可挂,另有 check_loss_rules_vs_mining.py/check_fade_predicate_parity.mjs 适合。工时 0.5 天合理。

### 6.4 报告漏掉的新缺口(比"证据错"更要紧)

1. **新版 `_strip_thinking_adaptive` 只处理 type==adaptive,`type==enabled` 原样转发**(文件注释明文)——若 enabled 型请求回归仍无防护,这是 P0-3 修复的实际存量缺口。
2. **OUT_OF_RANGE 真实触发字段未定位**(output_config.effort?enabled+max_tokens?),归因链缺实证。
3. **req.log 有 20MB 留尾截断**(LOG_MAX_BYTES/LOG_KEEP_TAIL_BYTES),历史 400 只活在无时间戳主日志——**后续排查必须 req.log+主日志两文件同看,单看 req.log 会漏**(报告唯一复现命令恰好指向会漏的文件)。

### 6.5 拍板结论(P0 优先级/顺序,已含工时)

按「收益/成本/耦合」取序:**P0-2 → P0-1 → P0-3**。

- **P0-2 CI 质量门禁(0.5 天,先做)**:CI 是全部机检的唯一盲区,上 ci.yml 挂现有 check_* 池(>5 个可挂,不新写),当天可 DONE,且 P0-1 产出 pytest 直接进同一 workflow,无返工。
- **P0-1 算法 pytest(1.5~2 天)**:loss_rules 20 键(43 谓词,可套 check_loss_rules_vs_mining 数据作输入)+ S06 状态 + 凯利三件套;AI 宏键集已有单测省一部分。
- **P0-3 代理高可用(0.5~1 天,最后)**:报告 ②"去 beta 依赖"已由新版代码完成大半,剩余=①定位 OUT_OF_RANGE 真因(output_config.effort/thinking.enabled 实测)②enabled 类型归一或剥离 ③/healthz+launchd 心跳(报告 ①)。②会影响**本会话(Claude 自己)当前正在走的代理路径**,必须先隔离测试(port)再改,故放最后且单独派单。
- **待用户确认项**:P0-3 ③加了 healthz+心跳后,代理告警接入 notify 线(severe 镜像 latest.md 防旁路,memory `alert-triage-event-driven-scan`)。

### 6.6 复现(复核方)

```bash
# 证据链复现(逐条对应 §6.2)
git show --stat 4e92cb3ef | head -5                      # 旧版 _inject_thinking_budget(361行)
grep -n "_strip_thinking_adaptive\|budget_tokens\|enabled" scripts/sensenova-rotate-proxy.py | head -20  # 新版 L336-359
tail -40 ~/code/trade-data/data/logs/sensenova-rotate-req.log   # 全时段 429 无 400(复核点 2)
grep -n "OUT_OF_RANGE\|L24677\|L24685" ~/code/trade-data/data/logs/sensenova-rotate.log | head   # 5条全在旧INJECT时代
ps aux | grep sensenova-rotate | grep -v grep            # PID 35148 启动 16:41,RUNNING
ls data/*.db | wc -l                                      # 9(报告复现命令同口径)
find app scripts -name "*.py" | xargs wc -l | tail -1     # 175 文件 82,631 行
```

确定性:**复核独立于报告结论,凡与报告冲突处以本节省 hard 数字(数据均本日 09-03 实跑)为准。**
