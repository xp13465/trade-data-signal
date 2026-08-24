#!/bin/bash
# codex-review-request.sh — Claude 主控用此脚本向 Codex 派发 review 任务
# 用法: echo '<json>' | bash scripts/codex-review-request.sh <request_id>
set -euo pipefail

REQUEST_ID="${1:?用法: codex-review-request.sh <request_id>}"

if [ -t 0 ]; then
    echo "错误：请通过 stdin 提供 JSON 内容" >&2
    exit 1
fi

BLOB_SHA=$(git hash-object -w --stdin)
REF="refs/codex/req/${REQUEST_ID}"
git update-ref "$REF" "$BLOB_SHA"

echo "✅ request 已写入"
echo "  ref: $REF"
echo "  sha: $BLOB_SHA"
echo "  id:  $REQUEST_ID"
