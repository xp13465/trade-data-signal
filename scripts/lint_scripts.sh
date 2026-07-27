#!/bin/bash
# lint_scripts.sh - 脚本静态检查（P0 稳定性 2026-07-20）
#
# 检查项（P0 简化版，shellcheck 留 P1）：
#   1) bash -n 语法检查 scripts/*.sh 所有文件
#   2) 全角字符代码位置扫描：grep -nP 找 $VAR 后紧跟全角括号（bug2 模式）
#      在 scripts/*.sh 和 scripts/*.py（intraday_snapshot.sh 全角括号事故根因）
#   3) python3 -m py_compile 检查 scripts/*.py
#
# 任一失败 exit 1（pre-commit hook 调本脚本，失败阻止 commit）。
# 用法：bash scripts/lint_scripts.sh
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FAIL=0

echo "=== 1) bash -n 语法检查 scripts/*.sh ==="
for f in "$SCRIPT_DIR"/*.sh; do
    [ -f "$f" ] || continue
    if ! bash -n "$f"; then
        echo "FAIL: $f"
        FAIL=1
    else
        echo "OK: $(basename "$f")"
    fi
done

echo ""
echo "=== 2) 全角括号扫描（\$VAR 后紧跟全角括号，bug2 模式）==="
# 全角左括号 FF08=（，全角右括号 FF09=）
# 匹配 $var）/ ${var}（ 等变量后紧跟全角括号（shell 解析错事故根因）
FULLWIDTH_HITS=0
for f in "$SCRIPT_DIR"/*.sh "$SCRIPT_DIR"/*.py; do
    [ -f "$f" ] || continue
    # grep -nP PCRE，\$\{?\w+\}? 匹配 $var 或 ${var}，[\x{FF08}\x{FF09}] 匹配全角括号
    if grep -nP '\$\{?\w+\}?[\x{FF08}\x{FF09}]' "$f" 2>/dev/null; then
        echo "FAIL: $(basename "$f") 含 $VAR 后紧跟全角括号（会导致 shell 解析错）"
        FAIL=1
        FULLWIDTH_HITS=$((FULLWIDTH_HITS + 1))
    fi
done
if [ "$FULLWIDTH_HITS" -eq 0 ]; then
    echo "OK: 无 \$VAR+全角括号 模式"
fi

echo ""
echo "=== 3) python3 -m py_compile 检查 scripts/*.py ==="
PY=${PYTHON:-python3}
for f in "$SCRIPT_DIR"/*.py; do
    [ -f "$f" ] || continue
    if ! "$PY" -m py_compile "$f" 2>/dev/null; then
        echo "FAIL: $(basename "$f")"
        "$PY" -m py_compile "$f"  # 重新跑显示错误
        FAIL=1
    else
        echo "OK: $(basename "$f")"
    fi
done

echo ""
if [ "$FAIL" -ne 0 ]; then
    echo "=== lint 失败 ==="
    exit 1
fi
echo "=== lint 全通过 ==="
exit 0
