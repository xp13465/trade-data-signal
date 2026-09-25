# 大 JSON 私有桶备份清单(large-json-backup-manifest.md)

> 本文件是 **staticdata 备份大 JSON 移出 git 后** 的 R2 快照索引：7 个 >20MB JSON(共 319MB)
> 已从 staticdata 备份仓库的 git 跟踪移出(备份天天 `skip_oversize` 不 commit 的根因)，改走
> R2 私有桶 `signal-backup` 的 `large-json/` 前缀版本化快照。
> 本文件**由 `upload_r2.py upload-large-json` 自动重写,勿手工编辑**；恢复请用
> `scripts/restore-large-json.sh`(详见 `docs/backup-restore.md` 第八节)。
>
> 相关脚本：`scripts/upload_r2.py`(上传,活脚本)/ `scripts/restore-large-json.sh`(恢复入口)。

---

## 一、机制一句话

- R2 私有桶：`signal-backup`(与 DB 备份同桶不同前缀)
- key 格式：`large-json/<YYYY-MM-DD>/<相对 data/ 的路径>.gz`
  - 例：`large-json/2026-09-25/signal_kelly_trades.json.gz`
  - 例：`large-json/2026-09-25/signal_kelly_trades_parts/t2025.json.gz`
- 保留档位：日档 14 天 + 周档(周日那份)8 周 + 月档(每月 1 号那份)12 个月
- 恢复：`bash scripts/restore-large-json.sh <文件名|--list|--date YYYY-MM-DD|--all>`
  - 还原时先下同目录 `.tmp` 再原子覆盖，覆盖前旧文件备份为 `<文件>.bak-<时间戳>`，
    本清单有 sha256 记录的会比对，不匹配即中止。

---

## 二、快照明细

| R2 key(signal-backup/large-json/) | 日期 | 原相对路径(还原到 data/ 下) | 大小(B) | sha256(64位) |
| --- | --- | --- | --- | --- |
| <!-- 由 upload_r2.py upload-large-json 自动填写，勿手工编辑 --> |  |  |  |  |
