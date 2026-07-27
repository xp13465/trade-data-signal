#!/bin/bash
# install_hooks.sh - 安装 pre-commit hook 到 .git/hooks/
#
# 用法：bash scripts/install_hooks.sh
# 复制 scripts/pre-commit（入库模板）到 .git/hooks/pre-commit + chmod +x。
# .git/hooks/ 不入库（本地配置），故入库模板在 scripts/pre-commit，本脚本负责安装。
set -uo pipefail

REPO="$(git rev-parse --show-toplevel)"
SRC="$REPO/scripts/pre-commit"
DST="$REPO/.git/hooks/pre-commit"

if [ ! -f "$SRC" ]; then
    echo "FAIL: $SRC 不存在" >&2
    exit 1
fi

cp "$SRC" "$DST"
chmod +x "$DST"
echo "已安装 pre-commit hook"
echo "  源:   $SRC"
echo "  目标: $DST"
