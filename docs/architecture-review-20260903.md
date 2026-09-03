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
