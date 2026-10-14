# 用词整改:禁用英文行话,首个 `smoke` → 「冒烟测试」(2026-10-14)

> 触发:用户当天原话 —— 「不要用这样的名词了。直接冒烟测试或者更好理解的描述 说人话就是要让大家一看就懂 并不是只有专业人士才能看懂」。
> 规范落点:根 `CLAUDE.md` **§6 新增第 3 条「说人话:规范/文档/界面里的词,一眼能懂」**(禁裸英文黑话 / 判据=外行能否读懂 / 例外=代码标识符不动 / 历史不追改 / 验收口径)。

## 一、替换规则

| 命中形态 | 处理 | 例 |
|---|---|---|
| 裸词 `smoke` / `Smoke`(前后是空格、中文、括号、`/`) | → **冒烟测试** | `跑 smoke` → `跑冒烟测试`、`P0 smoke` → `P0 冒烟测试`、`smoke 清单` → `冒烟测试清单` |
| **代码标识符**(前一字符是 `-` `_` `/`,或后一字符是 `-` `_` `.`) | **原样保留** | `docs/smoke-checklist.md`、`*-smoke.cjs`、`dbbrief_interaction_smoke.sh`、`smoke_results` 字段、`p0_smoke_{id}_fail` 去重键 |

## 二、改动文件清单(13 个「活规范 / 活文档」)

| 文件 | 命中 |
|---|---|
| `CLAUDE.md` | 4 |
| `README.md` | 2 |
| `.claude/agents/reviewer.md` | 3 |
| `.claude/agents/tester.md` | 4 |
| `.claude/skills/role-reviewer/SKILL.md` | 7 |
| `.claude/skills/role-tester/SKILL.md` | 5 |
| `docs/main-governance.md` | 9 |
| `docs/agent-quickstart.md` | 2 |
| `docs/site-deployment.md` | 5 |
| `docs/72h-monitor-plan.md` | 6 |
| `docs/test-suite-spec.md` | 3 |
| `docs/codex-collab-protocol.md` | 5 |
| `docs/smoke-checklist.md`(文件内措辞) | 7 |

## 三、明确**不动**的对象(及理由)

- **代码标识符 / 路径 / 字段名 / 去重键**:`docs/smoke-checklist.md`(路径)、`*.cjs` / `*.js` / `*_smoke.sh`(脚本名)、`smoke_results`(codex 协议 JSON 字段)、`p0_smoke_{id}_fail`(告警去重键)—— 改了断链断引用,属机器标识不属"给人读的话"。
- **台账 / 历史报告 / 归档**:`NOTES.md`(7)、`TASKS.md` 历史块、`docs/pending-features-index.md` 历史条目、`docs/ops/*`(21+ 份)、`docs/archive/*`、`docs/kelly/analysis/*` —— 这些是**过去发生过的事实记录**,回溯改写等于篡改历史(§6 新规第 ④ 条明令不追改)。
- **脚本源码**:`scripts/monitor_72h.sh`(10 处)、`static-site/app.js`(5 处)等 —— 属代码层,不在本次"文档措辞"范围。

## 四、自检结果

- 活文件残留扫描:剩余 `smoke` 命中**全部**为上述标识符/字段名(逐条已在 `git diff` 中核对)。
- 乱码自检:本次批量替换首轮曾用 `perl -CSD` 造成**双编码乱码**(`åçæµè¯`),当场以字节级重写修复;全仓 `*.md/*.js/*.py` 扫描 `å` = **0 命中**。
- 空格自检:`冒烟测试 清单` 这类多余空格已合并为 `冒烟测试清单`。

## 五、遗留 / 恢复

- **镜像仓待同步**:`claude-work-mode/`、`collab-standard-claude/`、`collab-standard-codex/` 三处是同规范的**分发副本**,本次未动(它们是独立仓的复制件,按 L41「同步要全量」另批处理)。**待办**。
- **恢复方式**:纯文本替换,`git revert <本 commit>` 即回退;无数据产物、无缓存、无线上影响。