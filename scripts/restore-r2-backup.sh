#!/bin/bash
# restore-r2-backup.sh —— 从 R2 signal-backup 私有桶 decommissioned/ 前缀恢复退役归档
#
# 目的：本地大件/historical .bak 清理后数据本体只存 R2(私有桶 decommissioned/,git 只留
#       manifest+本恢复脚本)。需要还原已清理的本地文件时用本脚本一键拉回。
# 用法：
#   bash scripts/restore-r2-backup.sh <key_name>
#     从 signal-backup 桶下载 decommissioned/<key_name> → 写入 data/<key_name 去 .gz>
#     key_name 不带 decommissioned/ 前缀(即 manifest 表格里的 R2 key 末段)。
#     例：bash scripts/restore-r2-backup.sh etf_national_team.db.bak-backfill-20260728-232308.gz
#         → 还原 data/etf_national_team.db.bak-backfill-20260728-232308
#     tar.gz 包还原后为 .tar(如 decommissioned-small-baks-20260903.tar.gz → .tar)，
#       再 tar -xf 解出包内 .bak 明细(见 docs/decommissioned-backups.md「## 恢复」)。
# 依赖：python3(调 scripts/upload_r2.py 的 s3_request,SigV4 签名+凭证复用，不新起连接)。
#        凭证从 .env / 环境变量读(upload_r2 模块 import 时 load_env)。
# 输出文件位置：data/<key_name 去 .gz>(与清理前原文件名一致)
# 复现命令：与 docs/decommissioned-backups.md「## 恢复」节一致。

set -euo pipefail
cd "$(dirname "$0")/.."   # 定位到仓库根(trade/)，data/ 在其下

if [ $# -ne 1 ]; then
  echo "用法: bash scripts/restore-r2-backup.sh <key_name>" >&2
  echo "  key_name 不带 decommissioned/ 前缀, 例: etf_national_team.db.bak-backfill-20260728-232308.gz" >&2
  exit 2
fi
KEY_NAME="$1"

REPO="${REPO:-$(pwd)}"
ROOT_ABS="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PYTHON:-python3}"

echo "从 signal-backup/decommissioned/${KEY_NAME} 还原 → data/ ..."
"$PY" - "$KEY_NAME" <<'PYEOF'
import sys, gzip
sys.path.insert(0, "scripts")
import upload_r2  # import 时 load_env() 载入凭证

key_name = sys.argv[1]
key = f"decommissioned/{key_name}"
status, data = upload_r2.s3_request("GET", key, bucket=upload_r2.BACKUP_BUCKET)
if status != 200:
    sys.exit(f"✗ 下载失败 {key} status={status} {data.decode('utf-8', errors='replace')[:300]}")

# 输出名 = key_name 去 .gz;tar.gz 只解一层 gzip(保持 .tar)
out_name = key_name[:-3] if key_name.endswith(".gz") else key_name
out_path = f"data/{out_name}"
payload = gzip.decompress(data) if key_name.endswith((".gz", ".tar.gz")) else data
with open(out_path, "wb") as f:
    f.write(payload)
print(f"✓ 还原 {len(data)}B(网络) → {out_path} ({len(payload)}B)")
PYEOF
echo "还原完成: data/$(echo "$KEY_NAME" | sed 's/\.gz$//')"
