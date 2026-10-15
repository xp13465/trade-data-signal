# #263 工作模式通用规范正文包(路1)交付报告 — 2026-10-14

> 交付物:仓内新目录 `work-mode-standard/`(通用规范正文包,与"避坑库"路并行的另一路)。
> 关键结构约定:**包内不放 `.claude/`,安装时才拷进目标项目的 `.claude/`**(规避前 4 任 agent 卡死的 `.claude/` 写入挂点)。
> commit `7b417fe05`(feat/263-workmode-spec),已 push 远端。

## 一、结论

- 本轮新增 11 个文件(README / 4 agents / 4 skills / 1 template / 旧包 2 处冻结留痕),全部一次 Write 写完、单一 commit、已 push feat 分支。
- 自验四项:**①残留扫描 = 0(新文件)**;**②文件树 + 行数全达标**;**③README 块 7 一字一致 PASS**;**④十月增量 8 点全部落位**(续跑延用原分支 1 点仅在角色 skill,见待处置)。
- 无残留后台任务(本轮无 `moved to the background` 事件)。

## 二、文件树 + 行数(上限对照)

```
work-mode-standard/
├── README.md                                    124 行(上限 200)✓
├── CLAUDE.md                                    285 行(已有,未改)
├── docs/  main-governance.md 232 / quality-flow.md 89 / role-based-context-design.md 114(已有,未改)
├── agents/  implementer 29 / reviewer 27 / researcher 25 / tester 26(上限 35)✓
├── skills/  role-implementer 147 / role-reviewer 150 / role-researcher 93 / role-tester 114(上限 150)✓
└── templates/PROJECT-SPECIFIC.template.md        72 行(上限 120)✓
```

## 三、自验四项

### ① 项目残留全文扫描(新文件 = 0)

| 扫描项(命令) | 命中 | 判定 |
|---|---|---|
| 域名/绝对路径/脚本名/产物目录:`grep -rInE "fx8\.store\|sugas\.site\|/Users/\|trade-data\|trade/\|main-merge\|deploy\.sh\|build_min\|bump_asset\|upload_r2\|export\.py\|check_signals\|purpose-notes\|board_etf_map\|sentiment\.db\|etf_national\|static-site"` | **0** | PASS |
| 时钟时点/市场代码:`grep -rInE "[0-9]{1,2}:[0-9]{2}\|09:30\|15:30\|17:50\|20:35\|23:00\|00[0-9]{4}"` | **0** | PASS |
| 业务词/编号/锚点:`grep -rInE "凯利\|Kelly\|kelly\|降亏\|track_score\|买卖点\|量子\|ETF\|v1\.[0-9]\|#2[0-9][0-9]\|memory \|docs/ops\|docs/archive\|docs/kelly\|L[0-9]{2}\|E[0-9]{2}\|ssd\.\|R2\|systemd\|launchd"` | 6 | 见下 |
| 前端文件/厂商:`grep -rInE "app\.js\|lab\.js\|style\.css\|sw\.js\|overview\.json\|DeepSeek\|商汤\|飞书"` | 1 | 通用词 |

- **新文件(本轮 Write 的 11 个)命中数 = 0**;以下 6 命中全在**已存在的** `CLAUDE.md` / `docs/*`(非本步文件):
  1. `docs/role-based-context-design.md:23/44/111` — "官方 memory 文档 / agent 记忆",通用技术词(指官方文档),保留
  2. `CLAUDE.md:256` / `docs/main-governance.md:176` — `<docs/archive/CLAUDE-errors-<月份>.md>`,**占位符形态**,合规
  3. `CLAUDE.md:86` — 「核心推荐 / 降亏过滤」类核心实用功能,**半业务词**,建议后续替换为 `<核心实用功能>`(见待处置)
- 前端文件 1 命中 = `skills/role-implementer/SKILL.md:26` 的 `.min.js` / `.min.css`(**通用构建后缀**,非项目文件),保留

### ② 文件树 + 行数
见上「二」,全部在上限内(角色文件按"比原仓精简"要求控制在 25~150 行)。

### ③ README 块 7 一字一致
`work-mode-standard/README.md:123` 与任务给定文本**逐字一致**:
> 避坑与经验正文在 `docs/pitfalls/<域>.md`(15 个域:a 多 agent 协作 / b 通知告警 / c 测试自测验证 / d git 分支合并 / e 数据产物一致性 / f 成本 token / g 派单任务调度 / h 调研防误判 / i 前端部署缓存 / j 删除备份安全 / k 生产运维平台 / l 数据源外部依赖 / m 回测数据科学口径 / n LLM 平台工具链 / o 沟通文档治理);一行一条的索引在 `docs/lessons-index.md`(158 条)。

### ④ 十月增量落点表(每条 → 新目录内文件:节)

| 增量规范 | 落点 |
|---|---|
| §5.7 方案 = 可证伪承诺 | `CLAUDE.md` §5.7 · `docs/quality-flow.md`(第②关)· `skills/role-researcher/SKILL.md` §2 · `skills/role-reviewer/SKILL.md` §10.7 |
| §5.8 上线前 6 道关 + 观察锚点 | `CLAUDE.md` §5.8 · `docs/quality-flow.md` |
| §25 删除前必备份 | `CLAUDE.md` §25 · `skills/role-implementer/SKILL.md` §10(指针) |
| CI 必须真绿 | `CLAUDE.md` §5.8 / §8 · `skills/role-implementer/SKILL.md` §3 · `skills/role-tester/SKILL.md` §5.3.1 |
| 边界完整性独立复核 | `skills/role-reviewer/SKILL.md` §10.8 · `CLAUDE.md` §5.8 · `agents/reviewer.md` |
| 边界维度穷举 | `skills/role-tester/SKILL.md` §5.3.1 · `agents/tester.md` |
| 续跑延用原 feat 分支 | `skills/role-implementer/SKILL.md` §3(见待处置:共享核心缺) |
| 应急止血不豁免时点 | `skills/role-implementer/SKILL.md` §3+§4 · `CLAUDE.md` §14 |

## 四、待主控处置(3 项,均属"已有文件"非本步范围)

1. **续跑延用原 feat 分支**:仅落在 `role-implementer` §3;**`CLAUDE.md` §0.2 三件套与 `docs/main-governance.md` 均无此条**(原仓 §0.2 有此 bullet)。建议主控决定是否补进共享核心 §0.2。
2. **`CLAUDE.md:86` 半业务词「核心推荐 / 降亏过滤」**:建议替换为 `<核心实用功能>` 占位符(一行改动)。
3. **`skills/role-*/SKILL.md` 教训蒸馏段已去锚点 id**(改为通用红线 + 指路 `docs/lessons-index.md`),与"通用版不写死状态型内容"一致;若主控希望保留极少数高价值锚点示例,需另定标准。

## 五、证据点

- 残留:见「三①」三条 grep 命令(结果 0 / 6 / 1)
- 行数:`wc -l` 输出见「二」
- README 块 7:`grep -n "避坑与经验正文" work-mode-standard/README.md` → 123
- 增量落点:`grep -rInE "5\.7|5\.8|§25|CI 必须真绿|边界完整性独立复核|边界维度|续跑|应急止血也" work-mode-standard/`(逐条命中见上表)
- git:`git log --oneline -1` → `7b417fe05`;push → `ecaf5cb62..7b417fe05 feat/263-workmode-spec`