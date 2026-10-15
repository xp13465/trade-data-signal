# #263 审查关必修项修复记录(2026-10-15)

> 依据:`work-mode-standard/` 审查关报告(docs/ops/workmode-distill-review-20261015.md)④ 节 7 项建议 + ⑥ 主控处置。
> 分支:`feat/263-workmode-spec`(先合入路2 `feat/263-workmode-pitfalls`,审查关 §① 要求"必须同批合")。
> 全部改动为一行级小改,均在通用包 `work-mode-standard/` 内(路径不含 `.claude`,普通 Write/Edit)。

## 一、做了什么(逐项)

### 必修 3 项
1. `work-mode-standard/CLAUDE.md` §5.4⑥:「核心推荐 / 降亏过滤」→「核心推荐 / 过滤」(对齐同文件 §5.4 触发词行已用的通用写法)。
2. `work-mode-standard/docs/quality-flow.md` ⑥ 上线关:「具体时点见 `PROJECT-SPECIFIC.md` §5」→「§2『定时任务时点表』」。
   - 核模板:`templates/PROJECT-SPECIFIC.template.md` §2 = 定时任务时点表、§5 = 公示位清单 ⇒ 原指 §5 是断链,改 §2。
3. `work-mode-standard/CLAUDE.md` §5.4①:「以项目 `PROJECT-SPECIFIC.md` 的『测试基准锚点』节为准」→「以项目 `PROJECT-SPECIFIC.md` 的『权威数据源』节里『回测 / 测试基准定义』那行为准」。
   - 核模板:模板无「测试基准锚点」节;基准内容在 §3「权威数据源」的「回测 / 测试基准定义、复现数字」行 ⇒ 原引用断链,改成能对上目标的引用。

### 顺手 4 项
4. `work-mode-standard/docs/main-governance.md` §11(子 agent 卡死/重派):补 1 行「续跑同一任务必须延续原分支,不新开分支改 cherry-pick」。
   - 通用化措辞:无本项目分支名 / 路径 / 编号;写明根因(隔离 worktree 有 commit 不自动清理,占死原分支 → 续跑只能 cherry-pick → 原分支废弃 + 历史漂移);主控可见层(依据 ⑥⑤2)。
5. 30 个包内文件补文件末尾换行符(EOF newline)。
6. `work-mode-standard/README.md`:
   - §4 维护约定开头「本仓(被蒸馏项目)」→「来源项目」。
   - §7 避坑库指路块**之后**另起一行,加「域短名 ↔ 索引全名」对照(a~o 共 15 域,短名与 `lessons-index.md` / `pitfalls/` 域全名逐一对照)。**§7 原两行一字未动**(与避坑库对齐的接口约定)。
7. `work-mode-standard/skills/role-tester/SKILL.md` §6 教训蒸馏段:补「本角色相关域:c 测试自测验证 / b 通知告警 / e 数据产物一致性」,对齐其余 3 个 role skill 段首写法。

## 二、每项证据

| 项 | 证据 |
|---|---|
| 必修1 | `grep -rn 降亏 work-mode-standard/` → 0 命中 |
| 必修2 | 改后行:`…(具体时点见 PROJECT-SPECIFIC.md §2「定时任务时点表」)`;模板 §2 标题实测=定时任务时点表 |
| 必修3 | `grep -rn 测试基准锚点` 仅剩 2 处:CLAUDE.md §5.4 标题自身 + README 映射表行(均指本包节名,非模板引用) |
| 顺手4 | `main-governance.md:69` 新增该行;全文无本项目分支名/路径/编号 |
| 顺手5 | 30/30 末尾有换行(见下) |
| 顺手6 | `README.md:71`「来源项目」;`README.md:127` 新对照行;`README.md:123/125` 原文未变 |
| 顺手7 | `role-tester/SKILL.md:104` 段首含「本角色相关域:…」 |

## 三、自验四项

1. **引用可达**:全包 grep 跨文件引用(`PROJECT-SPECIFIC.md` / `lessons-index` / `pitfalls/*.md` / `skills/role-*` / `docs/*`)→ **0 处指向不存在的东西**。落点核对:15 个 `pitfalls/*.md` 文件名与 `lessons-index.md` 引用 **15/15** 对上;`role-researcher §3.1/§3.2`、`role-implementer §1.1/§2/§3/§6.5`、`role-reviewer §10.7/§10.8` 节锚点实测存在;`docs/agent-quickstart.md` / `docs/PROJECT-SPECIFIC.md` 均为 `<占位符>` 或目标项目路径(非包内文件)。
2. **残留扫描**(照审查报告 §③ 必查 1 命令面重扫,合并后 30 文件):`#NNN`=0、memory 引号 `[[ ]]`=0、`HH:MM`=0、`/Users/`=0、`.json/.db/.parquet`=0、URL=0;业务词「降亏」=0(原 1 处已修)。**结果 0**。
3. **EOF**:包内 `.md` 末尾换行 **30/30**(脚本复扫 `no_eof=0`)。
4. **git status**:`git status --porcelain` = 30 行,全为 `work-mode-standard/` 下文件;**无 `.claude/` 路径、无意外文件**。diff numstat 与预期一致(5 文件含内容改动,余 25 文件为纯换行;无多余改动)。
