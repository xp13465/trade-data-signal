#!/usr/bin/env bash
# migrate_large_json_out_of_git.sh - 一次性迁移: 大 JSON 移出 staticdata 备份 git index(rm --cached)
# 到 R2 私有桶 large-json/ 每日备份(2026-09-25, feat/large-json-r2-core)
#
# 硬顺序(冻结接口): ① 先跑上传(upload_r2.py upload-large-json, 确认 R2 私有桶副本齐全 + manifest 已生成)
#                  ② 再 git rm --cached(磁盘文件必须保留, 绝不删)
# 任一步失败 → 中止, 不摘 git(可重复跑, 幂等)。
# 结尾只打印"下一步: 人工确认后 git -C <staticdata> commit + push", 脚本自己绝不 commit/push。
#
# 幂等: 重复跑时已 rm --cached 的文件不在 git ls-files → --print 清单为空 → 提示无需迁移 exit 0。
# 测试(严禁写生产 staticdata 仓库): STATICDATA_REPO=/tmp/xxx(git clone 克隆)再跑。
#
# 用法: bash scripts/migrate_large_json_out_of_git.sh [--dry-run]
set -u
# 不 set -e: 每步显式判退出码(硬顺序语义, 失败即中止)。

REPO="${REPO:-/Users/linhuichen/code/trade-data}"
GIT_REPO="${GIT_REPO:-/Users/linhuichen/code/trade}"
STATICDATA_REPO="${STATICDATA_REPO:-/Users/linhuichen/code/trade-data-signal-staticdata}"
PY="${PY:-$REPO/.venv/bin/python}"
DRY="${1:-}"

# 云上单仓回退(同 staticdata_backup_async.sh L50-52)
if [ ! -d "$STATICDATA_REPO/.git" ] && [ -n "${GIT_REPO:-}" ] && [ -d "${GIT_REPO}-staticdata/.git" ]; then
  STATICDATA_REPO="${GIT_REPO}-staticdata"
fi
if [ ! -d "$STATICDATA_REPO/.git" ]; then
  echo "✗ staticdata 仓库不存在: $STATICDATA_REPO"
  exit 1
fi

echo "== migrate_large_json_out_of_git 开始 $(date '+%Y-%m-%d %H:%M:%S') =="

# 1. 待迁移清单(排除规则单一源 --print, 相对 data/ 路径 + 字节数)
# ⚠ 2026-09-26 审查整改: 原 `2>/dev/null || true` 静默吞 --print 失败(迁移=摘 git 的关键操作,
# 静默失败=高危), 会误判「无需迁移」exit 0。改为显式判退出码: 失败打印原因(上方 stderr)并非 0 退出。
LIST=$("$PY" "$GIT_REPO/scripts/large_json_excludes.py" --print --repo "$STATICDATA_REPO")
_LJE_PRINT_RC=$?
if [ "$_LJE_PRINT_RC" -ne 0 ]; then
  echo "✗ large_json_excludes.py --print 失败(退出码 $_LJE_PRINT_RC, 上方 stderr 为原因), 中止迁移。"
  exit "$_LJE_PRINT_RC"
fi
if [ -z "$LIST" ]; then
  echo "✓ 无 >20MB tracked 大文件, 无需迁移(幂等重复跑自动到这里)"
  exit 0
fi
echo "待迁移文件:"
echo "$LIST" | while IFS= read -r _l; do
  [ -z "$_l" ] && continue
  echo "  $(printf '%s' "$_l" | awk -F '\t' '{printf "%s (%d 字节)", $1, $2}')"
done

# 1.5 dry-run: 只打印将 rm --cached, 不执行任何写操作
if [ "$DRY" = "--dry-run" ]; then
  echo ""
  echo "[dry-run] 将执行(git rm --cached, 磁盘文件保留):"
  echo "$LIST" | while IFS= read -r _l; do
    [ -z "$_l" ] && continue
    echo "  git -C $STATICDATA_REPO rm --cached -- data/$(printf '%s' "$_l" | awk -F '\t' '{print $1}')"
  done
  echo ""
  echo "[dry-run] 未执行任何写操作。正式跑: bash scripts/migrate_large_json_out_of_git.sh"
  exit 0
fi

# 2. 硬顺序①: 先上传(确认 R2 私有桶副本齐全 + manifest 已生成), 失败中止不摘 git
echo "-> [1/2] 上传到 R2 私有桶 large-json/ ..."
if ! STATICDATA_REPO="$STATICDATA_REPO" GIT_REPO="$GIT_REPO" "$PY" "$GIT_REPO/scripts/upload_r2.py" upload-large-json 2>&1; then
  echo "✗ 上传失败, 中止(不摘 git)。修复后重跑本脚本(幂等)。"
  exit 1
fi
MANIFEST="$GIT_REPO/docs/large-json-backup-manifest.md"
if [ ! -f "$MANIFEST" ]; then
  echo "✗ manifest 未生成: $MANIFEST, 中止(不摘 git)。"
  exit 1
fi
echo "  ✓ 上传完成 + manifest 已生成: $MANIFEST"

# 3. 硬顺序②: 再 rm --cached(磁盘文件必须保留, 绝不删)
echo "-> [2/2] git rm --cached(磁盘文件保留)..."
CNT=0
SKIP=0
while IFS= read -r _l; do
  [ -z "$_l" ] && continue
  _rel=$(printf '%s' "$_l" | awk -F '\t' '{print $1}')
  _gitpath="data/$_rel"
  if [ "$DRY" = "--dry-run" ]; then
    echo "  [dry] git rm --cached -- $_gitpath"
    continue
  fi
  # 重复跑幂等: 区块保留但已 rm --cached 过的文件不在 index, 跳过(不报错不中止)
  if ! git -C "$STATICDATA_REPO" ls-files --error-unmatch -- "$_gitpath" >/dev/null 2>&1; then
    echo "  - 跳过: $_gitpath 已不在 git index(重复跑场景)"
    SKIP=$((SKIP + 1))
    continue
  fi
  if git -C "$STATICDATA_REPO" rm --cached -- "$_gitpath" 2>&1; then
    echo "  ✓ rm --cached: $_gitpath(磁盘文件保留)"
    CNT=$((CNT + 1))
  else
    echo "  ✗ rm --cached 失败: $_gitpath, 中止。"
    exit 1
  fi
done <<< "$LIST"

echo ""
echo "== 迁移完成: $CNT 个文件已移出 staticdata git index(磁盘文件保留, $SKIP 个跳过=已在 index 外) =="
echo "下一步(人工, 脚本不代做):"
echo "  1. 核对: git -C $STATICDATA_REPO status"
echo "  2. 提交 .gitignore(排除区块) + rm --cached:"
echo "     git -C $STATICDATA_REPO add .gitignore"
echo "     git -C $STATICDATA_REPO commit -m \"large-json 移出 git, 改走 R2 私有桶 large-json/ 备份\""
echo "     git -C $STATICDATA_REPO push origin main"
echo "  3. 云上同仓库 clone 记得 git pull 同步(生产 async 用 ${GIT_REPO}-staticdata)。"
echo "  4. 机检确认: $PY $GIT_REPO/scripts/check_large_json_excluded.py --repo $GIT_REPO"