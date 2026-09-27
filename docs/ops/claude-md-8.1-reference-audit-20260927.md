# 根 CLAUDE.md §8.1 引用审计(2026-09-27):一批引用仍把 §8.1 当「R2 架构」

> 触发:2026-09-27 做「根 CLAUDE.md §24 + §8.1 下沉」时,reviewer 独立审查顺带发现本仓多处把 `§8.1` 当作「R2 存储架构准则」引用,而根 §8.1 **自 2026-08-15 起已是「派单 prompt 必带定位锚点」**。
>
> §23.5 四件套:本报告(本体)+ 生成依据(grep 全量,复现段见文末)+ 配套 commit。**本报告只审计不改**——是否清理、何时清理由用户拍板(§23.7⑤ 发现历史遗留上报机制)。

## 1. 问题是什么

| 时间 | 根 CLAUDE.md §8.1 的实际内容 |
|---|---|
| ~2026-08-15 之前 | **R2 存储架构准则**(按数据类别不按大小) |
| **2026-08-15 起至今** | **派单 prompt 必带定位锚点**(优化 P0-4 加) |

R2 架构内容当时迁到了 `.claude/skills/role-implementer/SKILL.md` 的 **§3.1**(该节标题自带溯源:「R2 存储架构准则(**原 §8.1**,按数据类别不按大小)」)。

**但全仓大量引用没跟着改**,仍写「CLAUDE.md §8.1」指代 R2。后果:有人/agent 照 `docs/agent-quickstart.md` 去翻根 CLAUDE.md §8.1 找「走 R2 的判定」,会看到「派单 prompt 必带定位锚点」——**拿不到信息**。

**性质**:pre-existing(2026-08-15 起就存在),**非** 2026-09-27 下沉引入;下沉未加剧也未解决。

## 2. 分类总账

| 类 | 数量 | 处置建议 |
|---|---|---|
| A. 错引(把 §8.1 当 R2,需改) | 本仓 docs 14 处 + 本仓 scripts 14 处 | 统一改为「implementer skill §3.1」 |
| B. 正确引用(不动) | 9 处 | — |
| C. 不能碰 | 2 类 | — |
| D. 本次已顺手自纠 | 2 处 | 已完成(见 §5) |

## 3. A 类:错引清单(逐条,文件:行号)

### 3.1 本仓 docs(14 处)

| # | 位置 | 原文片段 |
|---|---|---|
| 1 | `docs/data-deploy-quickstart.md:4` | 「见 … + CLAUDE.md §8/§8.1/§9」 |
| 2 | `docs/data-deploy-quickstart.md:55` | 「**判断规则**(CLAUDE.md §8.1):」 |
| 3 | `docs/data-deploy-quickstart.md:212` | 「## 8. 何时用 R2 vs CF Static Assets(CLAUDE.md §8.1)」 |
| 4 | `docs/data-deploy-quickstart.md:225` | 「§8.1(R2 存储架构准则)」 |
| 5 | `docs/agent-quickstart.md:58` | 「不依赖 1MB 阈值**(§8.1)」 |
| 6 | `docs/agent-quickstart.md:79` | 「走 R2 的判定(§8.1,按数据类别不按单文件大小)」← **最典型** |
| 7 | `docs/staticdata-daily-brief-sync.md:22` | 「gitignore 排除的都是「大小无法进入 git」的类别(§8.1 R2 架构)」 |
| 8 | `docs/staticdata-daily-brief-sync.md:59` | 「(§8.1:小文件走 CF/staticdata 差异日志,R2 是公开分发…)」 |
| 9 | `docs/staticdata-daily-brief-sync.md:82` | 「不改 §8.1 大文件 gitignore 规则」 |
| 10 | `docs/staticdata-daily-brief-sync.md:97` | 「已补 CLAUDE.md §8.1(新数据类别必接 ①R2 上传 ②staticdata 同步)」 |
| 11 | `docs/chart-refactor-config-plan.md:178` | 「走 R2 大 range 架构 §8.1」 |
| 12 | `docs/r2-migration-implementation-report.md:39` | 「按数据类别(非按单文件大小)判断(§8.1):」 |
| 13 | `docs/chart-p2p3-data-source-research.md:47,63,103,113` | 「§8.1 按前缀建命令」×4 |
| 14 | `docs/kelly/toggle/kelly-loss-reduction-toggle-v2-plan.md:228,276` | 「(§8.1)」「前端走 R2 直链(§8.1)」 |

### 3.2 本仓 scripts / static-site(14 处)

| # | 位置 | 原文片段 |
|---|---|---|
| 15 | `scripts/upload_r2.py:1211,1317,1334,1352,1367,1386,1401` | 「§8.1 新类别按前缀建独立命令」×7(模块/函数 docstring) |
| 16 | `scripts/export_fund_score.py:17` | 「upload_r2.py upload-fund-score(§8.1 新类别按前缀命令)」 |
| 17 | `scripts/export_offshore_fund.py:14` | 同上句式 |
| 18 | `scripts/staticdata_sync.sh:5` | 「见 CLAUDE.md §8.1 + docs/staticdata-daily-brief-sync.md)」 |
| 19 | `scripts/intraday_snapshot.sh:188` | 「违反 §8.1 checklist「写 static-site/data 的生成器…」 |
| 20 | `static-site/export.py:968` | 「(§8.1:小文件 <5MB 总量走 CF 非 R2…)」 |

🔴 **注意**:`scripts/*` 全在**部署/采集链路上**,改注释虽零逻辑风险,但属生产脚本,须走 implementer + reviewer(§14 P0)。

## 4. B 类:正确引用(不要误改)

| 位置 | 为什么正确 |
|---|---|
| `.claude/skills/role-implementer/SKILL.md:75`、`claude-work-mode/.../SKILL.md:48` | 「R2 存储架构准则(**原** §8.1)」= 自己的历史溯源标注 |
| `.claude/skills/role-reviewer/SKILL.md:33` | 「数据完整性校验(原 §15 ① + **§8.1**)」= 溯源旧编号 |
| `docs/main-governance.md:129` | 「(原根 CLAUDE.md §8.1,2026-09-27 下沉至此)」= 本次新增的溯源 |
| `docs/claude-md-slim-audit-20260912.md:27,70,119,132` | 历史审计快照,其中「§8.1 **派单 prompt 必带定位锚点**」指的是新的 |
| `docs/context-optimization-20260906.md:123`、`docs/architecture-review-20260903.md:50` | 「§8.1 锚点表」= **派单锚点**,正确 |
| `CLAUDE.md:109`(§18 表 L43 行) | 「主控只做派单锚点 grep(§8.1)」= 派单锚点,正确 |
| `claude-work-mode/README.md:159-160` | 🔎 **该 README 已有对照表**,明确区分「§8.1 派单定位锚点」与「§8.1 R2→ implementer §3.1」两义 |

## 5. C 类:不能碰

| 位置 | 理由 |
|---|---|
| `docs/market-state/kelly-fourtier-v2-multi-index-stability.md:127`「详见 §8.1」 | 是**该报告自己内部的节号**,与 CLAUDE.md 无关。误改即引入错误 |
| `docs/archive/**`(含 `claude-md-reorganize-plan.md`、`feedxml-architecture-review.md`、`TASKS-history-archive-*.md`、`CLAUDE-errors-2026-08.md`) | 历史归档,反映当时事实,改了=篡改历史 |
| `NOTES.md:6400,6744,6931` | **历史日志**,记录当时(§8.1 还=R2 的时期)的事实。同 archive 理由,**建议不改** |
| `claude-work-mode/**`、`collab-standard-claude/**`、`collab-standard-codex/**` | **独立同步仓**(工作模式模板),有自己的同步节奏;改动需单开一轮并覆盖完整构成(§L41 教训) |

## 6. D 类:本次已顺手自纠(2 处,在 2026-09-27 下沉 commit 内)

| 位置 | 改前 | 改后 |
|---|---|---|
| `CLAUDE.md:143`(§22 机制段) | `**(§18 索引 16/18 + §8.1 checklist 同此)` | `**(§18 索引 16/18 + R2 checklist 见 implementer skill §3.1)` |
| `CLAUDE.md:148`(§8) | `(R2 架构 §8.1 全文见 implementer skill §3.1)` | `(R2 架构准则全文见 implementer skill §3.1)` |

**为什么只改这 2 处**:它们是**根文件内部自相矛盾**(读者在根文件里按「§8.1」找 R2 会撞到派单锚点),且本次正在编辑同一文件,顺手自纠属同一次编辑的一致性;其余 28 处跨文件/跨仓,超出本次任务范围,按 §23.7⑤ **上报用户拍板**,不自行扩大。

## 7. 建议处置(排期建议,待用户拍板)

| 批次 | 范围 | 风险 | 建议 |
|---|---|---|---|
| ① 高频操作文档 | `docs/data-deploy-quickstart.md` + `docs/agent-quickstart.md`(6 处) | 零(纯文档) | **优先**——这两份是「操作速查」,用户/agent 最常翻,错引危害最大 |
| ② 其余本仓 docs | 8 处 | 零 | 随后 |
| ③ 本仓 scripts 注释 | 14 处 | 零逻辑,但属生产脚本 → 走 implementer+reviewer | 随后 |
| ④ 外部同步仓 | 3 个仓 | 需覆盖完整构成(§L41) | 单开一轮 |

**统一改法**:`§8.1` → `implementer skill §3.1`(或「R2 架构准则」直呼其名,不带节号)。

## 8. 复现段

```bash
# 全量列出本仓(排除 archive / 外部同步仓)的 §8.1 引用
grep -rn "§8\.1" --include="*.md" --include="*.sh" --include="*.js" --include="*.py" . \
  | grep -v "/docs/archive/" | grep -v "^./docs/archive"

# 判定每个引用属于 R2 还是派单锚点:看上下文关键词
#   R2 类:含「按前缀」「按类别」「大文件」「R2 上传」「gitignore」「走 R2」
#   派单类:含「锚点」「定位」「grep」(如 CLAUDE.md:109、claude-md-slim-audit)

# 确认根 §8.1 当前真实内容(应为派单锚点)
grep -n "^## 8.1" CLAUDE.md

# 确认 R2 架构现址
grep -n "R2 存储架构准则" .claude/skills/role-implementer/SKILL.md   # → §3.1「原 §8.1」
```

## 9. 关联

- 起因任务:2026-09-27 根 CLAUDE.md 瘦身(§24 + §8.1 下沉),commit `c9cd7d912`(下沉本体)+ `2ae94bab3`(验收整改 + 根文件 2 处自纠)
- 发现者:reviewer 独立审查(必查项④「举一反三:找漏网引用」)
- 相关规范:§23.7⑤(发现历史遗留必须上报)、§23.8(skill 维护同步)、§22(多展示位一致性的精神延伸:同一符号两义会致误解)
- 同类先例:`docs/claude-md-slim-audit-20260912.md`(§8.1 章节边界审计)、`claude-work-mode/README.md:159-160`(已有的两义对照表)
