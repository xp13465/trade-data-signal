# 本地 Git 清理结果 · 2026-11-05

- 固定执行 cwd：`/Users/linhuichen/code/trade/.claude/worktrees/codex-collab-closeout-20261105`；未 checkout、改业务源码、commit、push、删除远端分支、kill 进程或主动发送通知。
- 永久私有备份：`/Users/linhuichen/code/trade-backups/20261105-codex-closeout-20261105T175548-390bd6`（0700）。standalone bundle SHA-256：`1637809ea636e718eff850bf79838eade4bb4c117f4ad363fd302868bd9745ed`。
- 空 bare 仓实际 fetch 成功，refs 精确一致；`fsck --full --strict` 成功；4 stash 与全部旧候选 SHA 的 commit/tree/blob 均有效。对象流式读取已完成，未生成解压副本、未重复扫描。
- 本地分支 39 → 6，`git branch -d` 删除 33 条；工作区 13 → 4，无 force 移除 9 个。每个移除工作区均完整 tar 归档、逐文件 SHA-256 与条目覆盖校验成功。
- 保留 main、全部 3 个 codex/*、未合 feat/fix-258-s06-budget，以及 `worktree-agent-a33753a60314dae35`（目录虽已不存在，进程 cwd 仍使用该路径）。远端所有 refs 保持原 SHA；未 prune/gc。
- 4 stash 保留原顺序，原始 reflog 字节哈希不变：a657 三产物与 main 相同；a655 被 a657 替代；两个 p2c rollback stash 与 main 文件 blob 相同。未发现独有测试补丁（包含 index/第三父节点核验）。备份成功不构成丢弃独有工作的授权。
- 3 个 fast-forward/direct-commit 工作区和 detached preissue，结合完成回执及独立 tip/祖先/状态/进程核验后归档移除；最初暂缓及补核记录保留。
- 精确 before/after、归档 SHA、跳过理由、实际命令见 cleanup.json；恢复命令见 cleanup-recovery.md / 备份 RESTORE.md。此摘要仅含 manifest 元数据；禁止将 bundle/tar/私有内容入 Git 或通知。
