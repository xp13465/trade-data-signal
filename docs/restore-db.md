# DB 恢复操作流程（restore-db.md）

> 本文档已合并到 [docs/backup-restore.md](backup-restore.md)（A7 2026-07-20 整理，补充备份机制 + 统一为「备份与恢复手册」）。
>
> 请前往 [backup-restore.md](backup-restore.md) 查看完整内容：
> - 一、备份机制（每日自动 17:50 后：本地热备 + R2 三层 + 恢复演练 + 失败告警）
> - 二、恢复场景
> - 三、从 R2 下载最新备份（`download-db`）
> - 四、完整性校验（`integrity_check` + `verify_backup.sh`）
> - 五、恢复到生产路径（停 launchd -> 覆盖 -> 删 WAL -> 自检 -> 重载）
> - 六、紧急注意事项
> - 七、相关脚本
