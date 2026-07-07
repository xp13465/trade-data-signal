#!/usr/bin/env bash
# deploy.sh — 推送公网（导出 JSON + git push）
#
# 跑 static-site/export.py 生成静态 JSON（覆盖 static-site/data/），
# 然后 git add + 检查变更：有变更才 commit + push（Cloudflare Pages 自动部署），
# 无变更 skip。
#
# 用法：
#   bash scripts/deploy.sh
#
# 日志：tee 到 data/logs/deploy_YYYYMMDD_HHMM.log
# 退出码：0=成功（push 或 skip）；非 0=export 或 push 失败。
set -u
# 不 set -e：每步显式判退出码，出错给清晰错误信息。

REPO=/Users/linhuichen/code/trade
PY="$REPO/.venv/bin/python"
EXPORT="$REPO/static-site/export.py"
LOGDIR="$REPO/data/logs"
STAMP=$(date +%Y%m%d_%H%M)
LOG="$LOGDIR/deploy_${STAMP}.log"

mkdir -p "$LOGDIR"

echo "=== deploy.sh 开始 $(date '+%Y-%m-%d %H:%M:%S') ===" | tee "$LOG"

# 1. 导出 JSON
echo "→ 运行 export.py 生成静态 JSON ..." | tee -a "$LOG"
"$PY" "$EXPORT" 2>&1 | tee -a "$LOG"
EXPORT_RC=${PIPESTATUS[0]}
if [ "$EXPORT_RC" -ne 0 ]; then
  echo "✗ export.py 失败（退出码 $EXPORT_RC），终止部署" | tee -a "$LOG"
  exit "$EXPORT_RC"
fi
echo "✓ export.py 完成" | tee -a "$LOG"

# 2. git add 静态数据
echo "→ git add static-site/data/ ..." | tee -a "$LOG"
git -C "$REPO" add static-site/data/ 2>&1 | tee -a "$LOG"

# 3. 检查有无变更（cached diff 非空才 commit）
if git -C "$REPO" diff --cached --quiet; then
  echo "✓ 无数据变更，skip push" | tee -a "$LOG"
  echo "=== deploy.sh 结束 $(date '+%Y-%m-%d %H:%M:%S') 退出码=0 ===" | tee -a "$LOG"
  exit 0
fi

# 4. 有变更 → commit + push
COMMIT_MSG="data update $(date +%Y-%m-%d_%H:%M)"
echo "→ git commit: $COMMIT_MSG" | tee -a "$LOG"
git -C "$REPO" commit -m "$COMMIT_MSG" 2>&1 | tee -a "$LOG"
COMMIT_RC=${PIPESTATUS[0]}
if [ "$COMMIT_RC" -ne 0 ]; then
  echo "✗ git commit 失败（退出码 $COMMIT_RC）" | tee -a "$LOG"
  exit "$COMMIT_RC"
fi

echo "→ git push ..." | tee -a "$LOG"
git -C "$REPO" push 2>&1 | tee -a "$LOG"
PUSH_RC=${PIPESTATUS[0]}
if [ "$PUSH_RC" -ne 0 ]; then
  echo "✗ git push 失败（退出码 $PUSH_RC）" | tee -a "$LOG"
  exit "$PUSH_RC"
fi

echo "✓ push 成功（Cloudflare Pages 将自动部署）" | tee -a "$LOG"
echo "=== deploy.sh 结束 $(date '+%Y-%m-%d %H:%M:%S') 退出码=0 ===" | tee -a "$LOG"
exit 0
