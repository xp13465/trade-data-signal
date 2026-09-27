# 大 JSON 备份清单(large-json-backup-manifest)——指针说明

> **本文件已不是"当前清单",只是指针**(2026-09-27, #115 归属决策)。

## 当前清单在哪

**已迁至 staticdata 备份仓库**:

```
<staticdata 备份仓库>/docs/large-json-backup-manifest.md
```

- staticdata 备份仓库默认路径:
  - 本机 mac:`/Users/linhuichen/code/trade-data-signal-staticdata`
  - 云上生产:`/home/ubuntu/code/trade-data-signal-staticdata`(即 `${GIT_REPO}-staticdata`)
  - 运行时可用 `STATICDATA_REPO` 环境变量覆盖。
- 由 `scripts/upload_r2.py upload-large-json` 自动重写(每次上传跑完即刷新, 勿手工编辑)。

**为什么迁走**:该清单原本写在 trade 仓库 `docs/` 下, 而每日备份 async/sync 提交的是 **staticdata 仓库**
——没有任何环节提交 trade 侧这份文件, 且表体是每日快照索引(内容天然天天变), 导致每次 async 跑完
trade 仓库必留一个 M 脏文件。迁到 staticdata 仓库后, async/sync 的 `git add -A` 自然提交它, trade 侧
不再有脏文件。

## 恢复脚本兼容

`scripts/restore-large-json.sh` 已**双路径兼容**:先读 staticdata 仓库新路径, 读不到回退 trade 仓库旧路径
(历史快照见 git 历史, 即本文件的旧版本)。两处都能读, 无需手工指定。

## 恢复入口不变

`bash scripts/restore-large-json.sh <文件名|--list|--date YYYY-MM-DD|--all> [--target <dir>]`
详见 `docs/backup-restore.md` 第八节。
