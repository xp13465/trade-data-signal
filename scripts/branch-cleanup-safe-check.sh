#!/bin/bash
# scripts/branch-cleanup-safe-check.sh
# 三重验证:祖先关系 + merge commit + tip 提交
# 用法: bash scripts/branch-cleanup-safe-check.sh [--delete]

set -euo pipefail

MODE="${1:-check}"  # check 或 delete

echo "🔍 分支安全检查脚本"
echo "模式: $MODE"
echo ""

# 获取已合并到 main 的远端分支(不含 main 本身)
MERGED_BRANCHES=$(git branch -r --merged origin/main 2>/dev/null | grep -vE "^\s*origin/main$" | sed 's|^  origin/||' || echo "")

if [ -z "$MERGED_BRANCHES" ]; then
    echo "✅ 没有已合并的远端分支需要检查"
    exit 0
fi

TOTAL=0
SAFE_COUNT=0
UNSAFE_COUNT=0

echo "📊 开始检查 $(echo "$MERGED_BRANCHES" | wc -l) 个已合并的远端分支..."
echo ""

# 清空记录文件
> /tmp/safe_to_delete.txt
> /tmp/need_manual_check.txt

while IFS= read -r branch; do
    [ -z "$branch" ] && continue
    TOTAL=$((TOTAL + 1))

    # 标准化分支名(处理特殊字符)
    branch_escaped=$(echo "$branch" | sed 's/[][*?]/\&/g')

    # 方法 1: 祖先关系检查
    if git merge-base --is-ancestor "origin/$branch_escaped" origin/main 2>/dev/null; then
        echo "✅ $branch (方法1:祖先关系)"
        echo "$branch" >> /tmp/safe_to_delete.txt
        SAFE_COUNT=$((SAFE_COUNT + 1))
        continue
    fi

    # 方法 2: merge commit 存在检查
    merge_line=$(git log --oneline origin/main --grep="$branch_escaped" 2>/dev/null | head -1)
    if [ -n "$merge_line" ]; then
        echo "✅ $branch (方法2:merge commit - $merge_line)"
        echo "$branch" >> /tmp/safe_to_delete.txt
        SAFE_COUNT=$((SAFE_COUNT + 1))
        continue
    fi

    # 方法 3: tip 提交检查
    tip=$(git rev-parse "origin/$branch_escaped" 2>/dev/null)
    if [ -n "$tip" ] && git log --oneline origin/main 2>/dev/null | grep -q "${tip:0:12}"; then
        echo "✅ $branch (方法3:tip在main中)"
        echo "$branch" >> /tmp/safe_to_delete.txt
        SAFE_COUNT=$((SAFE_COUNT + 1))
        continue
    fi

    # 全部失败,需要人工检查
    echo "⚠️  $branch (需要人工检查)"
    echo "$branch" >> /tmp/need_manual_check.txt
    UNSAFE_COUNT=$((UNSAFE_COUNT + 1))

done <<< "$MERGED_BRANCHES"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📊 检查完成汇总:"
echo "   总计检查: $TOTAL 个分支"
echo "   ✅ 可安全删除: $SAFE_COUNT 个"
echo "   ⚠️  需要人工检查: $UNSAFE_COUNT 个"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# 输出结果文件位置
echo ""
echo "📁 结果文件:"
echo "   可安全删除: /tmp/safe_to_delete.txt"
echo "   需要人工检查: /tmp/need_manual_check.txt"
echo ""

# 如果有需要人工检查的,显示详情
if [ $UNSAFE_COUNT -gt 0 ]; then
    echo "⚠️ 需要人工检查的分支:"
    cat /tmp/need_manual_check.txt
    echo ""
fi

# 如果是删除模式,执行删除
if [ "$MODE" = "delete" ] && [ $UNSAFE_COUNT -eq 0 ]; then
    echo ""
    echo "🚀 执行删除..."
    while IFS= read -r branch; do
        [ -z "$branch" ] && continue
        echo "   删除: $branch"
        git push origin --delete "$branch" 2>&1 | grep -E "deleted|Error|error" || true
    done < /tmp/safe_to_delete.txt
    echo "✅ 删除完成"
elif [ "$MODE" = "delete" ] && [ $UNSAFE_COUNT -gt 0 ]; then
    echo "⚠️ 有 $UNSAFE_COUNT 个分支需要人工检查,跳过删除"
fi

# 返回值
if [ $UNSAFE_COUNT -eq 0 ]; then
    exit 0
else
    exit 1
fi
