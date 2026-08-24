#!/bin/bash
# lint_scripts.sh - 脚本静态检查（P0 稳定性 2026-07-20）
#
# 检查项（P0 简化版，shellcheck 留 P1）：
#   1) bash -n 语法检查 scripts/*.sh 所有文件
#   2) 全角/多字节字符位置扫描：$VAR 后紧跟非 ASCII 字节（bash 3.2 吞变量名病灶；
#      python3 实现——旧版 grep -nP 在 BSD grep 下 invalid option 被吞致机检空转，
#      2026-08-25 复活，扫 scripts/*.sh 和 scripts/*.py）
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
echo "=== 2) \$VAR 后紧跟非 ASCII 字节扫描（bash 3.2 多字节吞变量名病灶）==="
# 历史(2026-08-25 复活): 旧版用 grep -nP, macOS BSD grep(/usr/bin/grep)无 -P,
#   报 invalid option 被 2>/dev/null 吞 -> if 永假 -> 机检永远 0 命中空转显绿,
#   bash 3.2 多字节吞变量名病灶(8 处, commit 5ad22bfb1 修)存活至今才暴露。
#   开发 shell 里 grep 可能是 GNU/ugrep 有 -P, 本机测不出 -> 尺子必须跨环境自验(L42)。
# 现用 python3 内嵌实现(项目脚本环境必有 python3, BSD/GNU/launchd 行为一致):
#   只匹配「裸 \$var(无花括号)后紧跟非 ASCII 字节」——bash 3.2 会把多字节首字节
#   当变量名一部分吞掉, 产生 unbound variable 假象崩溃。
#   \${var}( 花括号形态=5ad22bfb1 修复批的官方根治形态(显式边界), 不命中(防假阳)。
python3 - "$SCRIPT_DIR" <<'PYEOF'
import re
import sys
from pathlib import Path

pat = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*[^\x00-\x7f]")
root = Path(sys.argv[1])
files = sorted(set(root.glob("*.sh")) | set(root.glob("*.py")))
hits = 0
for f in files:
    try:
        text = f.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        print(f"WARN: {f.name} 读取失败 {e}")
        continue
    for i, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("#"):
            continue  # 纯注释行不执行, 无 bash 词法风险(局限: 引号内 # 极罕见不覆盖)
        if pat.search(line):
            print(f"HIT {f.name}:{i}: {line.strip()[:160]}")
            hits += 1
print(f"扫描 {len(files)} 个文件, 命中 {hits} 行")
sys.exit(1 if hits else 0)
PYEOF
SCAN_RC=$?
if [ "$SCAN_RC" -ne 0 ]; then
    echo "FAIL: 发现 \$VAR 后紧跟非 ASCII 字节（bash 3.2 吞多字节首字节，见上 HIT 行）"
    FAIL=1
else
    echo "OK: 无 \$VAR+非ASCII 相邻模式"
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
