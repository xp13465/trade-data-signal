#!/usr/bin/env bash
# deploy.sh — 推送公网（导出 JSON + git push）
#
# 跑 static-site/export.py 生成静态 JSON（覆盖 static-site/data/），
# 然后 git add → 检查有无变更：有变更 commit（无变更跳过 commit）→
# **总是 git push**（最后一步，幂等：有未 push commit 就推，无则 up-to-date）。
#
# 幂等性：上次 commit 成功但 push 失败（网络中断等）→ 重跑 export 生成相同
# JSON → git add 无新变更 → 跳过 commit → git push 推未 push commit。✅
#
# 用法：
#   bash scripts/deploy.sh
#
# 日志：tee 到 data/logs/deploy_YYYYMMDD_HHMM.log
# 退出码：0=成功（commit+push 或 仅 push up-to-date）；非 0=export 或 push 失败。
set -u
# 不 set -e：每步显式判退出码，出错给清晰错误信息。

REPO=/Users/linhuichen/code/trade
PY="$REPO/.venv/bin/python"
EXPORT="$REPO/static-site/export.py"
LOGDIR="$REPO/data/logs"
STAMP=$(date +%Y%m%d_%H%M)
LOG="$LOGDIR/deploy_${STAMP}.log"
NAME="${1:-all}"   # 可选 pipeline 名（pipeline.sh 持锁调用时传入；无参=all）

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

# 3. 检查有无变更（cached diff 非空才 commit；无变更跳过 commit 但仍 push）
if git -C "$REPO" diff --cached --quiet; then
  echo "✓ 无新数据变更，跳过 commit（仍 push 推未 push commit）" | tee -a "$LOG"
else
  # 4. 有变更 → commit
  COMMIT_MSG="data update [$NAME] $(date +%Y-%m-%d_%H:%M)"
  echo "→ git commit: $COMMIT_MSG" | tee -a "$LOG"
  git -C "$REPO" commit -m "$COMMIT_MSG" 2>&1 | tee -a "$LOG"
  COMMIT_RC=${PIPESTATUS[0]}
  if [ "$COMMIT_RC" -ne 0 ]; then
    echo "✗ git commit 失败（退出码 $COMMIT_RC）" | tee -a "$LOG"
    exit "$COMMIT_RC"
  fi
fi

# 5. 总是 git push（幂等：有未 push commit 就推，无则 "Everything up-to-date"）
echo "→ git push ..." | tee -a "$LOG"
git -C "$REPO" push 2>&1 | tee -a "$LOG"
PUSH_RC=${PIPESTATUS[0]}
if [ "$PUSH_RC" -ne 0 ]; then
  echo "✗ git push 失败（退出码 $PUSH_RC）" | tee -a "$LOG"
  exit "$PUSH_RC"
fi

echo "✓ push 成功（Cloudflare wrangler deploy 将自动部署）" | tee -a "$LOG"
echo "=== deploy.sh 结束 $(date '+%Y-%m-%d %H:%M:%S') 退出码=0 ===" | tee -a "$LOG"
exit 0
