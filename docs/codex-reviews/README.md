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

## 备注

- rev-001 存在两轮(第一轮 17:55 前/第二轮全面复查),目录内为最终轮(磁盘最新版);两轮均 PASS。
- codex 沙箱环境限制:线上 curl 三站 http_code=000、Playwright 启动失败——该两项由内部 reviewer 覆盖,读报告时注意此边界。
- rev-002 对 check_universe_alignment 回退策略(static-site/data 优先 + data/ 兜底)的建议:当前可接受;未来若引入自动 deploy 链建议改 FAIL 防静默校验旧数据。
