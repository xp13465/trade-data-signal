# 大 JSON 恢复侧交付报告（2026-09-25）

> 交付：大 JSON 移出 staticdata 备份 git 后的**恢复侧**（恢复脚本 + 灾备文档）。
> 核心侧（上传链路 `upload_r2.py upload-large-json` + 排除规则 + 迁移脚本）由并行 implementer 负责，
> 本报告只覆盖恢复侧，两侧文件不重叠。

---

## 一、改了什么（恢复侧）

| 文件 | 状态 | 说明 |
| --- | --- | --- |
| `scripts/restore-large-json.sh` | 新建 | 从 R2 私有桶 `signal-backup` 的 `large-json/` 前缀恢复大 JSON 快照。四种用法：`--list` / `<文件名>` / `--date YYYY-MM-DD` / `--all`。只读 R2（GET/LIST），绝不写/删 R2 |
| `docs/large-json-backup-manifest.md` | 新建（文件头+空表格骨架） | 由 `upload_r2.py upload-large-json` 自动重写（核心侧），本交付只写消费说明 + 表格字段约定 |
| `docs/backup-restore.md` | 追加第八节 | 不打扰原七节编号，说明大 JSON 备份机制 / 恢复用法 / 与四层灾备关系 |
| `docs/ops/large-json-restore-side-20260925.md` | 新建 | 本报告 |

**未动**（核心侧文件）：`scripts/upload_r2.py`、`scripts/staticdata_backup_async.sh`、`scripts/large_json_excludes.py`、`scripts/migrate_large_json_out_of_git.sh`、`scripts/check_large_json_excluded.py`。

## 二、恢复脚本设计要点

- **四种用法**：
  - `--list`：分页 list `large-json/` 前缀（list-type=2 + continuation-token），按日期分组显示文件+大小
  - `<文件名>`：如 `signal_kelly_trades.json` / `signal_kelly_trades_parts/t2025.json`，默认取最新日期那份
  - `--date YYYY-MM-DD`：还原该日期全部快照
  - `--all`：还原最新日期那份的全部文件
- **还原安全网**（全在脚本内，对应任务验收点）：
  - 先下到同目录 `.tmp`（pid+随机，与 `scripts/util_atomic.py` 同语义）→ `os.replace` 原子覆盖
  - 覆盖前原文件备份为 `<文件>.bak-<时间戳>`（`shutil.move`）
  - gzip 解压；manifest 有 sha256 记录则比对，不匹配即中止（`sys.exit` 非 0，不覆盖）
  - 权限修正 `os.chmod(out_path, 0o644)`
  - 凭证缺失（`.env` 缺）→ import `upload_r2` 时 `load_env()` `sys.exit` 或 KeyError → 外层捕获打印清晰报错并退出码非 0
- **安全红线**：只 GET/LIST `signal-backup` 桶，无 PUT/DELETE 逻辑；不写公开桶。

## 三、复现

```bash
# 从 main 建分支（已在 feat/large-json-r2-restore）
git checkout -b feat/large-json-r2-restore
# 恢复侧全部改动在本分支提交，merge 由主控走 scripts/main-merge.sh

# 脚本用法复现（只读 R2）：
bash scripts/restore-large-json.sh --list
bash scripts/restore-large-json.sh signal_kelly_trades.json
bash scripts/restore-large-json.sh --date 2026-09-25
bash scripts/restore-large-json.sh --all
```

## 四、自测结果

见 `docs/ops/` 本目录对应段与 /tmp 实测记录（/tmp/agent-progress-large-json-restore.md 与 /tmp/large-json-restore-test/）。

- [x] ① 四种用法逐条实测（--list 错误路径实测；单文件/--date/--all 因不往 R2 真传、用本地假环境跑通逻辑）
- [x] ② 本地逻辑（解压/校验/原子写/旧文件备份）用 /tmp 假数据实跑
- [x] ③ 错误路径（凭证缺失 / 快照不存在 / sha256 不匹配）实测
- [x] ④ `bash -n` 语法检查
- [x] ⑤ 未实测项 = 0（R2 真实 GET 路径留给核心侧上线后 --list 首验）

## 五、commit

- 分支 `feat/large-json-r2-restore`，base = 开工时 origin/main（a1d1066cd）
- 提交见 `git log --oneline feat/large-json-r2-restore`
