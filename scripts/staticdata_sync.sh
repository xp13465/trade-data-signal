#!/usr/bin/env bash
# staticdata_sync.sh — 通用 staticdata 数据仓库同步(best-effort)
#
# staticdata 仓库 = trade-data-signal-staticdata(灾备第2层差异日志 / 数据留档 / 复原,
# 见 CLAUDE.md §8.1 + docs/staticdata-daily-brief-sync.md)。
# 原同步机制 = deploy.sh L507-558 每次 deploy 后全量 rsync。但「只写 static-site/data/
# + R2 上传、不跑 deploy.sh」的独立生成器(如 gen_daily_brief.py)不触发 deploy → staticdata
# 留旧版直到下次 deploy(同步时机缺口, docs/staticdata-daily-brief-sync.md §二)。
# 本脚本让这类生成器直接调用,统一同步(通用化,防同类再漏)。
#
# 用法:
#   bash scripts/staticdata_sync.sh <trigger> [--all] [--manifest] [file1.json ...]
#     <trigger>    commit message 里的触发名(生成器/pipeline 名,如 daily-brief)
#     --all        全量 rsync static-site/data/ → staticdata/data/(默认,同 deploy.sh L529)
#     --manifest   同时刷新 staticdata 仓库根 manifest.json 一并 commit(默认不刷)
#     文件列表     只同步指定 JSON(相对 static-site/data/ 的路径,如 daily_brief.json)
#
# 特性:
#   - 持 /tmp/trade_deploy.lock(阻塞)执行:防与 deploy.sh/pipeline 的 staticdata 段
#     并发写同一 git 仓库(git index.lock 冲突 + add 半截 JSON)
#   - best-effort: 任何失败只告警不阻塞调用方(退出码恒 0)
#   - 幂等: 无变更跳过 commit(同 deploy.sh L538)
#   - REPO/GIT_REPO/STATICDATA_REPO 环境变量可覆盖(同 deploy.sh L24/L512)
set -u

REPO="${REPO:-/Users/linhuichen/code/trade-data}"
GIT_REPO="${GIT_REPO:-/Users/linhuichen/code/trade}"
STATICDATA_REPO="${STATICDATA_REPO:-/Users/linhuichen/code/trade-data-signal-staticdata}"
PY="${PY:-$REPO/.venv/bin/python}"
LOCK="/tmp/trade_deploy.lock"

# ── 持锁重入 ──
# 整个同步在 /tmp/trade_deploy.lock 内执行(阻塞等 deploy 完成再同步),避免并发写。
if [ "${STATICDATA_SYNC_LOCKED:-}" != "1" ]; then
  export STATICDATA_SYNC_LOCKED=1
  exec "$PY" "$GIT_REPO/scripts/with_lock.py" "$LOCK" bash "$0" "$@"
fi

TRIGGER="${1:-manual}"
shift 2>/dev/null || true

MODE="all"
MANIFEST=0
for a in "$@"; do
  case "$a" in
    --all)      MODE="all" ;;
    --manifest) MANIFEST=1 ;;
    *)          MODE="files" ;;
  esac
done

if [ ! -d "$STATICDATA_REPO/.git" ]; then
  echo "⚠ staticdata 仓库不存在($STATICDATA_REPO),跳过同步"
  exit 0
fi

SYNC_FAIL=0

# 1. 复制数据产物(全量 rsync 或指定文件 cp)
if [ "$MODE" = "all" ]; then
  if ! rsync -a "$REPO/static-site/data/" "$STATICDATA_REPO/data/"; then
    echo "⚠ staticdata 全量 rsync 失败(best-effort)"
    SYNC_FAIL=1
  fi
else
  for a in "$@"; do
    case "$a" in
      --all|--manifest) continue ;;
    esac
    f="$a"
    if [ -f "$REPO/static-site/data/$f" ]; then
      # 目标父目录先确保存在(支持子目录路径如 news_digest/2026/2026-08-16.json,
      # 2026-08-16 新闻归档按年分目录; mkdir -p 幂等)
      mkdir -p "$(dirname "$STATICDATA_REPO/data/$f")"
      if ! cp "$REPO/static-site/data/$f" "$STATICDATA_REPO/data/$f"; then
        echo "⚠ staticdata cp 失败: $f"
        SYNC_FAIL=1
      fi
    else
      echo "⚠ staticdata_sync: 源文件不存在,跳过: $f"
    fi
  done
fi

# 2. 可选:刷新 manifest.json(保证 fetch_data.sh 一键复原索引新鲜)
if [ "$MANIFEST" = "1" ] && [ -f "$STATICDATA_REPO/gen_data_manifest.py" ]; then
  if ! "$PY" "$STATICDATA_REPO/gen_data_manifest.py"; then
    echo "⚠ staticdata manifest 刷新失败(best-effort)"
    SYNC_FAIL=1
  fi
fi

# 3. git commit + push(差异化日志,best-effort)
# add -A 与 deploy.sh 一致:staticdata 是纯镜像仓库,持锁下无并发写,全部未提交变更都应落库。
git -C "$STATICDATA_REPO" add -A 2>/dev/null || true
if git -C "$STATICDATA_REPO" diff --cached --quiet 2>/dev/null; then
  echo "✓ staticdata 无新变更,跳过 commit"
else
  _N=$(git -C "$STATICDATA_REPO" diff --cached --name-only | grep -c . || true)
  if ! git -C "$STATICDATA_REPO" commit -m "data backup [$TRIGGER] $(date +%Y-%m-%d_%H:%M) - ${_N} files" 2>/dev/null; then
    echo "⚠ staticdata commit 失败(best-effort)"
    SYNC_FAIL=1
  elif ! git -C "$STATICDATA_REPO" push origin main 2>/dev/null; then
    echo "⚠ staticdata push 失败(best-effort)"
    SYNC_FAIL=1
  fi
fi

if [ "$SYNC_FAIL" = "1" ]; then
  echo "⚠ staticdata 同步部分失败(best-effort,不阻塞调用方)"
  exit 0
fi
echo "✓ staticdata 同步完成"
exit 0
