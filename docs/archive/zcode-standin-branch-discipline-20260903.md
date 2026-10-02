# ZCode 专属分支纪律(2026-09-03,归档)

> 本文档是 `zcode/standin-charter` 分支独有的一段历史规范(commit `f5b25983d`,2026-09-03)的**归档副本**。
> 2026-10-03 worktree-cleanup 时,该分支按任务处置为「已处理、不 merge main」,故把 main 没有的这段独有内容抠出来落档,防历史规范丢失。
> 该分支同时把 main 的「2026-09-29 hook 机检收敛 / 云上 systemd timer」改回了旧描述(launchd),因此**不要 merge 它**,main 以更新版为准。

## 归档内容(原文,来自 .agents/zcode-standin/SKILL.md 新增行)

- **⚠️ ZCode 专属分支纪律(2026-09-03 用户定,对 ZCode 优先于上条)**:ZCode 的**所有**产出(功能代码/docs 报告/脚本收编/**本章程与 MEMORY 更新**)一律提交到 `zcode/*` 命名空间分支并 push;**ZCode 禁止直接 commit/push main**(2026-09-01~03 期间 8 笔直落 main 为历史存量,已 push 不回改 §23.11,靠 Co-Authored-By 尾注追溯)。`zcode/*` 分支何时 merge 进 main=由用户或 Claude Code 确认后走 main-merge.sh(或 Claude 主动合入),**ZCode 不自行合并自己的分支**。注意:本章程在 main 亦有历史版本(Claude 会改),我的更新落 zcode/* 分支后可能与 main 分叉,merge 时按互补保留(§23.11 非静默)

## 归档判定

- **对象**:`zcode/standin-charter` 分支(本地),独有 commit = `f5b25983d`(仅 1 行,加到 `.agents/zcode-standin/SKILL.md`)
- **为什么归档不 merge**:该 commit 含 main 没有的「ZCode 专属分支纪律」历史段;同分支其它内容(如把 main 的 2026-09-29 hook 机检收敛 / 云上 systemd timer)改回旧描述 → 合入会倒退,按任务定论「不要 merge」。
- **处理**:独有内容已抄录于此,分支标记「已处理」。未删除分支本身(不删分支引用),保持原状即可由主控后续决定是否清。

## 怎么恢复

若后续需要把这段纪律重新并入 main:修改 `.agents/zcode-standin/SKILL.md`,在 main 版对应位置(「分支纪律」小节下)插入本归档文件「归档内容」段即可。