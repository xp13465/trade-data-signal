#!/bin/bash
# restore-r2-backup.sh —— 从 R2 私有备份桶 decommissioned/ 前缀恢复退役归档
#
# 目的：本地大件/historical .bak 清理后数据本体只存 R2(私有桶 decommissioned/,git 只留
#       manifest+本恢复脚本)。需要还原已清理的本地文件时用本脚本一键拉回。
# 用法：
#   bash scripts/restore-r2-backup.sh [--bucket <桶名>] [--out-dir <目录>] <key_name>
#     从 decommissioned/<key_name> 下载 → 写入 <out-dir>/<key_name 去 .gz>(默认 out-dir=data/)
#     key_name 不带 decommissioned/ 前缀(即 manifest 表格里的 R2 key 末段)。
#     例：bash scripts/restore-r2-backup.sh etf_national_team.db.bak-backfill-20260728-232308.gz
#         → 还原 data/etf_national_team.db.bak-backfill-20260728-232308
#     tar.gz 包还原后为 .tar(如 decommissioned-small-baks-20260903.tar.gz → .tar)，
#       再 tar -xf 解出包内 .bak 明细(见 docs/decommissioned-backups.md「## 恢复」)。
#
#   --bucket <桶名>  显式钉桶：只在指定桶查找(不回落)。用于已知对象所在桶时跳过探测。
#   --out-dir <目录> 输出目录(默认 data/)。测试/演练时指临时目录, 避免覆盖本地源文件。
#
# 桶路由(结构解, 2026-10-08 修)：decommissioned/ 对象跨桶分布 —— #178(2026-10-05)前写入的
#   历史归档在老桶 signal-backup legacy，#178 后新写入落新桶 signal-backup2(独立账号)。
#   ⇒ **默认桶探测**: 依次 GET 候选桶, 命中即用(先 BACKUP_BUCKET, 404 回落老 legacy 桶)。
#   候选桶顺序可用 env 扩展, 对将来第三个桶零代码改动:
#     R2_LEGACY_BACKUP_BUCKET      老 legacy 桶名(默认 signal-backup)
#     R2_RESTORE_BUCKET_FALLBACKS  逗号分隔追加桶(在默认两桶之后按序探测)
#   非 404 的硬错误(403/5xx 等)不回落, 立即响亮失败(§23.11 异常绝不静默)。
#
# 依赖：python3(调 scripts/upload_r2.py 的 s3_request,SigV4 签名+凭证复用,不新起连接)。
#        凭证从 .env / 环境变量读(upload_r2 模块 import 时 load_env)。
# 输出文件位置：<out-dir>/<key_name 去 .gz>(默认与清理前原文件名一致, data/ 下)
# 复现命令：与 docs/decommissioned-backups.md「## 恢复」节一致。

set -euo pipefail
cd "$(dirname "$0")/.."   # 定位到仓库根(trade/)，data/ 在其下

usage() {
  echo "用法: bash scripts/restore-r2-backup.sh [--bucket <桶名>] [--out-dir <目录>] <key_name>" >&2
  echo "  key_name 不带 decommissioned/ 前缀, 例: etf_national_team.db.bak-backfill-20260728-232308.gz" >&2
  echo "  --bucket   显式钉桶(不回落; 默认自动探测 新桶→老 legacy 桶)" >&2
  echo "  --out-dir  输出目录(默认 data/; 测试时可指临时目录避免覆盖本地源)" >&2
}

BUCKET_OVERRIDE=""
OUT_DIR="data"
while [ $# -gt 0 ]; do
  case "$1" in
    -b|--bucket)
      [ $# -ge 2 ] || { echo "✗ --bucket 缺参数" >&2; usage; exit 2; }
      BUCKET_OVERRIDE="$2"; shift 2 ;;
    --bucket=*) BUCKET_OVERRIDE="${1#*=}"; shift ;;
    -o|--out-dir)
      [ $# -ge 2 ] || { echo "✗ --out-dir 缺参数" >&2; usage; exit 2; }
      OUT_DIR="$2"; shift 2 ;;
    --out-dir=*) OUT_DIR="${1#*=}"; shift ;;
    -h|--help) usage; exit 0 ;;
    --) shift; break ;;
    -*) echo "✗ 未知选项: $1" >&2; usage; exit 2 ;;
    *) break ;;
  esac
done

if [ $# -ne 1 ]; then
  usage
  exit 2
fi
KEY_NAME="$1"

REPO="${REPO:-$(pwd)}"
ROOT_ABS="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PYTHON:-python3}"

echo "还原 decommissioned/${KEY_NAME} → ${OUT_DIR}/ ..."
RESTORE_KEY_NAME="$KEY_NAME" RESTORE_BUCKET_OVERRIDE="$BUCKET_OVERRIDE" RESTORE_OUT_DIR="$OUT_DIR" \
"$PY" - <<'PYEOF'
import os, sys, gzip
sys.path.insert(0, "scripts")
import upload_r2  # import 时 load_env() 载入凭证

key_name = os.environ["RESTORE_KEY_NAME"]
key = f"decommissioned/{key_name}"
override = os.environ.get("RESTORE_BUCKET_OVERRIDE", "").strip()
out_dir = os.environ.get("RESTORE_OUT_DIR", "data").rstrip("/") or "data"


def candidates():
    """decommissioned/ 候选桶(按序探测, 结构解)。

    override 非空 → 只探测该桶(显式钉桶)。
    否则: 现行默认 BACKUP_BUCKET(新桶) → 老 legacy 桶(env R2_LEGACY_BACKUP_BUCKET, 默认
    signal-backup) → env R2_RESTORE_BUCKET_FALLBACKS 逗号分隔追加的任意桶(将来第三个桶)。
    去重保序。
    """
    if override:
        return [override]
    cands = [upload_r2.BACKUP_BUCKET,
             os.environ.get("R2_LEGACY_BACKUP_BUCKET", "signal-backup")]
    cands += os.environ.get("R2_RESTORE_BUCKET_FALLBACKS", "").split(",")
    out, seen = [], set()
    for b in cands:
        b = b.strip()
        if b and b not in seen:
            seen.add(b)
            out.append(b)
    return out


tried = []
hit = None
data = b""
for bkt in candidates():
    status, body = upload_r2.s3_request("GET", key, bucket=bkt)
    tried.append((bkt, status))
    if status == 200:
        hit, data = bkt, body
        break
    if status == 404:
        continue
    # 非 404 硬错误(403/5xx 等): 不静默回落, 立即响亮失败
    sys.exit(f"✗ 下载失败 {bkt}/{key} status={status} "
             f"{body.decode('utf-8', errors='replace')[:300]}")

if hit is None:
    detail = ", ".join(f"{b}={s}" for b, s in tried)
    sys.exit(f"✗ 目标对象在所有候选桶均不存在(全部 404): {key}\n"
             f"  探测结果: {detail}\n"
             f"  提示: 用 --bucket <桶名> 显式指定, 或设 R2_LEGACY_BACKUP_BUCKET / "
             f"R2_RESTORE_BUCKET_FALLBACKS 扩展候选桶")

# 输出名 = key_name 去 .gz;tar.gz 只解一层 gzip(保持 .tar)
out_name = key_name[:-3] if key_name.endswith(".gz") else key_name
os.makedirs(out_dir, exist_ok=True)
out_path = os.path.join(out_dir, out_name)
payload = gzip.decompress(data) if key_name.endswith((".gz", ".tar.gz")) else data
with open(out_path, "wb") as f:
    f.write(payload)
print(f"✓ 命中桶 {hit} | 还原 {len(data)}B(网络) → {out_path} ({len(payload)}B)")
PYEOF
echo "还原完成: ${OUT_DIR}/$(echo "$KEY_NAME" | sed 's/\.gz$//')"