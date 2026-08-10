#!/usr/bin/env bash
# =============================================================================
# release_db.sh — 把 SQLite 数据库归档包上传到 GitHub Release(开源完整化)
#
# 前置: 本机已装 gh CLI 且已登录(gh auth login);否则无法自动上传。
#        (或改用下方 curl + GITHUB_TOKEN 方式)
#
# 用法:
#   bash scripts/release_db.sh                    # 创建 db-archive-YYYY-MM-DD release 并上传 4 个 tar.gz
#   bash scripts/release_db.sh --manifest-only   # 只更新 manifest uploaded=true,不执行上传(已手动传过时)
#
# 资产来源: data/release/*.tar.gz (gen_data_manifest.py 生成 manifest 时 sha256 与之对应)
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RELEASE_DIR="$ROOT/data/release"
REPO="xp13465/trade-data-signal"
TAG="db-archive-$(date +%Y-%m-%d)"

cd "$ROOT"

if [ "${1:-}" = "--manifest-only" ]; then
  echo "只更新 manifest uploaded=true(假设 Release 已手动上传)…"
  python3 - "$TAG" <<'PY'
import json, sys
p = "data/manifest.json"
m = json.load(open(p))
for d in m.get("databases", []):
    d["uploaded"] = True
    d["url"] = d["url"].replace("/db-archive/", f"/{sys.argv[1]}/")
json.dump(m, open(p, "w"), ensure_ascii=False, separators=(",", ":"))
print("manifest databases.uploaded=true")
PY
  exit 0
fi

if ! command -v gh >/dev/null 2>&1; then
  echo "✗ gh CLI 未安装。请先: brew install gh && gh auth login" >&2
  echo "  或用 GITHUB_TOKEN 方式(见下方注释):" >&2
  echo '    curl -fsSL -X POST -H "Authorization: Bearer $GITHUB_TOKEN" \' >&2
  echo "      https://api.github.com/repos/$REPO/releases \ " >&2
  echo '      -d "{\"tag_name\":\"'"$TAG"'\",\"name\":\"DB Archive '"$TAG"'\",\"draft\":true}"' >&2
  exit 1
fi

# 检查资产存在
for f in "$RELEASE_DIR"/*.tar.gz; do
  [ -e "$f" ] || { echo "✗ 无归档包: $RELEASE_DIR/*.tar.gz(先跑 backup_db 打包)" >&2; exit 1; }
done

echo "═══ 创建 Release $TAG 并上传 DB 归档 ═══"
gh release create "$TAG" "$RELEASE_DIR"/*.tar.gz \
  --repo "$REPO" \
  --title "DB Archive $TAG" \
  --notes "tdsignal 原始 SQLite 数据库归档(CC BY 4.0)。包含 sentiment / etf_national_team / stock_daily / public_fund 4 库。完整性校验见 data/manifest.json databases.sha256。"

echo "✓ Release $TAG 已创建并上传"
python3 - "$TAG" <<'PY'
import json, sys
p = "data/manifest.json"
m = json.load(open(p))
for d in m.get("databases", []):
    d["uploaded"] = True
    d["url"] = d["url"].replace("/db-archive/", f"/{sys.argv[1]}/")
json.dump(m, open(p, "w"), ensure_ascii=False, separators=(",", ":"))
print("✓ manifest databases.uploaded=true, tag=" + sys.argv[1])
PY
