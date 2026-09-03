# codex 外部 review 报告归档

外部 reviewer(codex)对本项目做的独立交叉验证报告,经 `scripts/codex-review-request.sh` 发起、
git ref 通道回传,原文 JSON 落本目录归档(§23.5 塞入即归类)。协作机制/请求协议见
`docs/codex-collab-protocol.md`,发起脚本 `scripts/codex-review-request.sh`,回传脚本 `scripts/codex-review-report.sh`。

**新报告入场即在本索引追加一行**,不攒。

## 索引

| 日期 | request_id | 审计范围(一句话) | verdict | 发现数 | 处置指向 |
|---|---|---|---|---|---|
| 2026-08-24 | rev-20260824-001 | v1.1.4→aabafdcc4 深度交叉验证(第二轮):has_track 四源统一/键集机检/bj50 兜底关停影响面/QTH 防前视/数据完整性 | PASS | 4(P2×3+P3×1) | ①QTH 全史快照=已知设计取舍 → 本批 scripts/loss_rules.py QTH 定义处注释落档;②integrity a_fund_north_quarterly FAIL 归因「列名不匹配」被实证纠伪(全历史无 metric_name,base 同版逐字相同,本地实跑 ok)→ 本批 scripts/check_data_integrity.py 诊断信息补强(db 路径入 msg+锁竞争专项提示);③bj50 残留 1476 笔(trades 含 has_track/G 卡 41 笔)→ 已知技术债,下次重跑回测自然清除,待 TASKS 登记;④X1 扩围数字口径差异(8099→9962 vs 实际 1982)→ fix-plan 文档标注口径;⑤lab.js new15「作废待重算」标注 → 穷举重算后 follow-up 移除 |
| 2026-08-24 | rev-20260824-002 | 增量审(v1.1.6 前最后合入三批纯文档/脚本):check_universe_alignment trades 路径根修/codex 协作协议四项/has_track P0 教训全链落档 | PASS | 1(P3) | tester skill 缺 §23.13 三源引用挂接 → 本批 .claude/skills/role-tester/SKILL.md L47 行尾已补「+ CLAUDE.md §23.13」,与 implementer/reviewer/researcher 拉齐 |
| 2026-08-24 | audit-perf-and-alerts-20260824 | 全项目代码级漏洞/内存泄漏/重复调用/异常引用 + 交互性能优化 + 告警噪音分析(59条告警54条自愈=91.5%噪音率) | 报告(无verdict,发现待处置) | 8(P0×1+P1×4+P2×3)+告警降噪5条建议 | 待主控派单处置:①P0 lab.js 62MB trades全量加载(切片/超时) ②P1 addEventListener泄漏237:3/innerHTML+=循环重建/queries.py连接未finally关/9处裸except无日志 ③P2 scroll未节流5处/CSS top/left动画5处/boot.json 2.4MB拆分 ④告警阈值建议(intraday连续3次/push最终失败才报/ws_stale加ack/update_all阈值100→120min评估) |
| 2026-09-01 | (对话式评审,非ref通道) | Karpathy Skills 开源项目评估(用户直接问 codex):是否直接用/蒸馏;Claude 校验 codex 准确性+双方汇总 | N/A(评审评估) | codex 提 2 条 review schema 建议(trace/verifier) | ①结论:不直接用不蒸馏(codex+Claude 一致),但 2 条 per-finding 规则(trace/verifier)值得采纳 ②codex 2 处修正:无测试套件说过头(有针对性单测)/落地点应扩到双 reviewer skill(§23.3) ③**待用户拍板是否采纳改协议/skill**。落档 karpathy-skills-evaluation-20260901.md |
| 2026-09-01 | (蒸馏落地,非ref通道) | ponytail 开源项目蒸馏落地(用户拍板蒸馏而非装 plugin):按 4 角色把 7级阶梯/删除清单/懒但安全/量化影响接进现有 skill | N/A(蒸馏落地) | 4 文件+codex-reviewer 共 5 处 | implementer §6.5 / reviewer §10.6 + codex-reviewer 同内容 / tester §5.4 / researcher §3.2,全「纯新增」+§23.8 关联规范源标注。落档 ponytail-distill-20260901.md |
| 2026-09-01 | (对话式实测,非ref通道) | CodeGraph 开源项目实测评估(主控本地实测,非转述 codex):唯一命名 callers/impact 准,但 3 硬伤(2MB app.js 静默跳过/通用短名同名污染/函数内局部符号不可查)+ 对回测口径漂移无直接帮助(结构非语义) | N/A(实测评估) | 3 硬伤+1 无效痛点 | 结论:值得装但改装,只用于定位不当影响面依据,先 codex 外审用不装 MCP;遗留问题=1MB 上限配置项待查。落档 codegraph-eval-20260901.md |

## 备注

- rev-001 存在两轮(第一轮 17:55 前/第二轮全面复查),目录内为最终轮(磁盘最新版);两轮均 PASS。
- codex 沙箱环境限制:线上 curl 三站 http_code=000、Playwright 启动失败——该两项由内部 reviewer 覆盖,读报告时注意此边界。
- rev-002 对 check_universe_alignment 回退策略(static-site/data 优先 + data/ 兜底)的建议:当前可接受;未来若引入自动 deploy 链建议改 FAIL 防静默校验旧数据。
