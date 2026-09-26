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
#   - 大 JSON 守卫(2026-09-26, feat/large-json-guard-sync): commit 前先刷 .gitignore 受管区块
#     + 调 large_json_excludes.py --check-staged 判定待提交变更是否超阈值(单文件大 JSON 未迁移 /
#     积压), 超阈值 → 跳过 commit/push 仅磁盘留档 + 告警; 与 staticdata_backup_async.sh 共用
#     同一守卫(消除双实现, 详见解法底部第3段注释)
#   - REPO/GIT_REPO/STATICDATA_REPO 环境变量可覆盖(同 deploy.sh L24/L512)
set -u

REPO="${REPO:-/Users/linhuichen/code/trade-data}"
GIT_REPO="${GIT_REPO:-/Users/linhuichen/code/trade}"
STATICDATA_REPO="${STATICDATA_REPO:-/Users/linhuichen/code/trade-data-signal-staticdata}"
# 云上单仓: 本机硬编码 staticdata 路径不存在时, 回退 GIT_REPO 派生的 sibling 路径
# (云上 GIT_REPO=/home/ubuntu/code/trade-data-signal -> ...-staticdata), 防云上静默跳过备份
# (2026-09-13 迁移残留修)。
if [ ! -d "$STATICDATA_REPO/.git" ] && [ -n "${GIT_REPO:-}" ] && [ -d "${GIT_REPO}-staticdata/.git" ]; then
  STATICDATA_REPO="${GIT_REPO}-staticdata"
fi
PY="${PY:-$REPO/.venv/bin/python}"
LOCK="/tmp/trade_deploy.lock"

# notify 测试钩子(2026-09-26, feat/staticdata-write-guard): STATICDATA_SYNC_NOTIFY_DRY_RUN=1 →
# notify 走 --dry-run(自验用, 不真发邮件/飞书), 与 async 的 STATICDATA_BACKUP_NOTIFY_DRY_RUN 同款做法。
_NOTIFY_DRY=()
if [ "${STATICDATA_SYNC_NOTIFY_DRY_RUN:-}" = "1" ]; then
  _NOTIFY_DRY=(--dry-run)
fi

# ── 持锁重入 ──
# 整个同步在 /tmp/trade_deploy.lock 内执行,避免并发写同一 staticdata git 仓库
# (git index.lock 冲突 + add 半截 JSON)。
#   默认阻塞等 deploy 完成再同步(与 deploy.sh/pipeline 串行化,防并发写)。
#   STATICDATA_SYNC_NONBLOCK=1 时用 with_lock.py --nb 非阻塞:锁被 deploy 占用即跳过本次,
#   不等待(用于高频 intraday 快照:灾备缺口由 etf deploy 的 staticdata 全量 rsync 兜底,
#   锁忙时跳过不阻塞快照流程,见 intraday_snapshot.sh 2.53 注释)。
if [ "${STATICDATA_SYNC_LOCKED:-}" != "1" ]; then
  export STATICDATA_SYNC_LOCKED=1
  if [ "${STATICDATA_SYNC_NONBLOCK:-}" = "1" ]; then
    exec "$PY" "$GIT_REPO/scripts/with_lock.py" --nb "$LOCK" bash "$0" "$@"
  else
    exec "$PY" "$GIT_REPO/scripts/with_lock.py" --block-timeout 3600 "$LOCK" bash "$0" "$@"
  fi
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
# 写权限守卫(2026-09-26, feat/staticdata-write-guard): staticdata git 写判定单一源
# staticdata_write_guard.py, 消除"mac 还是生产机"时代遗留的全量覆盖事故(见
# docs/ops/staticdata-mac-write-path-research-20260926.md)。调用点 = git 段最前(rsync 段已跑完,
# 数据已磁盘留档, git 写权限只影响是否 commit/push)。rc: 0=生产机(原逻辑不动) 1=非生产机默认
# 拒绝 2=内部错误。非生产机 + 显式 STATICDATA_ALLOW_PUSH=1 → 改走 --check-fresh 数据闸门(只增不
# 覆盖, 不用 git add -A, 只 add 守卫放行的清单)。
# 大 JSON 守卫(2026-09-26, feat/large-json-guard-sync): 与 staticdata_backup_async.sh 共用同一守卫
# 单一源 large_json_excludes.py, 消除双实现。顺序不能乱:
#   3.0 先刷 .gitignore 受管区块(必须在下面 git add 之前)——让新 >20MB 文件先被 ignore,
#       否则 `git add -A` 会把未进区块的大文件暂存, 而 .gitignore 移除不掉已暂存项, 下一轮就提交了
#       (缺口 B: default_mode 的 desired = tracked ∪ 区块已有 ∪ 磁盘未跟踪新大文件)。
#   3.1 git add(生产机=add -A; 非生产机显式放行=只 add 闸门放行清单)判退出码: add 失败 →
#       SYNC_FAIL=1 + 日志, 且不得进"无新变更"分支。
#   3.2 调 --check-staged 判定待提交变更是否超阈值: rc=1 → 跳过 commit/push 仅磁盘留档 + 告警;
#       rc=2(判定脚本自身异常)→ 日志 + SYNC_FAIL=1, 继续 commit(best-effort, 不为判定脚本 bug 阻塞灾备)。
# 保持 best-effort 契约: 任何失败只告警不阻塞调用方(脚本退出码恒 0)。
_GA_NEW_ADD=""   # 非生产机显式放行时, 闸门放行的 add 清单(一行一路径)
_GA_OK=0         # 守卫裁定: 0=走 git 段 1=跳过 git 段
_GAUTH_OUT=$("$PY" "$GIT_REPO/scripts/staticdata_write_guard.py" --check-write-auth --repo "$STATICDATA_REPO" 2>&1)
_GAUTH_RC=$?
if [ "$_GAUTH_RC" -eq 2 ]; then
  echo "⚠ staticdata 写权限判定异常(rc=2), 置 SYNC_FAIL=1, 按生产机继续(best-effort, 降级保守)"
  SYNC_FAIL=1
elif [ "$_GAUTH_RC" -eq 1 ]; then
  # 非生产机: 默认拒绝 git 写; 显式 STATICDATA_ALLOW_PUSH=1 → 数据闸门(只增不覆盖)。
  if [ "${STATICDATA_ALLOW_PUSH:-}" = "1" ]; then
    echo "⚠ 非生产机 + STATICDATA_ALLOW_PUSH=1: 走数据闸门(只增不覆盖)"
    _GATE_LIST=$("$PY" "$GIT_REPO/scripts/staticdata_write_guard.py" --check-fresh --repo "$STATICDATA_REPO" 2>/dev/null)
    _GATE_RC=$?
    if [ "$_GATE_RC" -eq 1 ]; then
      echo "⚠ 数据闸门拒绝($STATICDATA_REPO), 跳过 commit/push 仅磁盘留档: see guard log"
      "$PY" "$REPO/scripts/notify.py" "[通知] staticdata git 写被数据闸门拒绝(非生产机显式放行)" \
        "staticdata 同步(trigger=$TRIGGER) 非生产机显式 STATICDATA_ALLOW_PUSH=1, 但数据闸门拒绝(只增不覆盖: 本地旧于远端 / 重复触发 / fetch 失败)。<br>本次仅 rsync 磁盘留档未 commit/push。数据已磁盘留档, 不覆盖生产 DR 仓库。<br>日志见 guard stderr。" \
        --from-prefix "[通知]" --alert-issue "staticdata数据闸门拒绝非生产机写" \
        --dedup-key staticdata_sync_gate_reject --dedup-window 21600 "${_NOTIFY_DRY[@]+"${_NOTIFY_DRY[@]}"}" 2>/dev/null || true
    elif [ "$_GATE_RC" -eq 2 ]; then
      echo "⚠ 数据闸门内部错误(rc=2), 置 SYNC_FAIL=1, 跳过 commit/best-effort"
      "$PY" "$REPO/scripts/notify.py" "[告警] staticdata 数据闸门内部错误跳过 commit" \
        "staticdata 同步(trigger=$TRIGGER) 数据闸门内部错误(rc=2), 无法保证只增不覆盖 → 跳过 commit/push。<br>日志见 guard stderr 与本脚本 stdout。" \
        --from-prefix "[告警]" --alert-issue "staticdata数据闸门内部错误" \
        --dedup-key staticdata_sync_gate_error --dedup-window 21600 "${_NOTIFY_DRY[@]+"${_NOTIFY_DRY[@]}"}" 2>/dev/null || true
      SYNC_FAIL=1
    else
      _GA_NEW_ADD="$_GATE_LIST"
      _GA_OK=1
      echo "  [数据闸门] 放行 $(printf '%s\n' "$_GATE_LIST" | grep -c . || true) 项(仅新增/不旧覆盖)"
    fi
  else
    echo "⚠ 非生产机($STATICDATA_REPO): staticdata git 写被守卫拦截(rc=1), 跳过 commit/push, 仅 rsync 磁盘 + R2 留档"
    "$PY" "$REPO/scripts/notify.py" "[通知] 非生产机 staticdata git 写已跳过" \
      "staticdata 同步(trigger=$TRIGGER) 在本机(非生产机, 路径非 /home/ubuntu/)被 staticdata 写权限守卫拦截, 跳过 git commit/push。<br>数据仍已 rsync 磁盘留档 + R2 上传(灾备第1/2层不丢)。<br>如需从本机显式推合法数据: 设 STATICDATA_ALLOW_PUSH=1 重跑(走只增不覆盖数据闸门)。<br>仓库: $STATICDATA_REPO" \
      --from-prefix "[通知]" --alert-issue "非生产机staticdata git写被守卫拦截" \
      --dedup-key staticdata_sync_nonprod_skip --dedup-window 21600 "${_NOTIFY_DRY[@]+"${_NOTIFY_DRY[@]}"}" 2>/dev/null || true
    SYNC_FAIL=1
  fi
fi
if [ "$_GAUTH_RC" -ne 1 ] || [ "$_GA_OK" = "1" ]; then
  # 进 git 段(生产机 / 守卫异常降级 / 非生产机显式放行通过数据闸门)
  if ! "$PY" "$GIT_REPO/scripts/large_json_excludes.py" --repo "$STATICDATA_REPO" 2>/dev/null; then
    echo "⚠ large_json_excludes.py 刷新 .gitignore 受管区块失败, 置 SYNC_FAIL=1, 继续(best-effort)"
    SYNC_FAIL=1
  fi
  _GIT_DONE=0
  if [ -n "$_GA_NEW_ADD" ]; then
    # 非生产机显式放行: 只 add 闸门放行清单(先 unstage 清空, 防残留已暂存项混入)
    _STAGE_FAIL=0
    if ! git -C "$STATICDATA_REPO" reset -q 2>/dev/null; then _STAGE_FAIL=1; fi
    _ALLOWED_COUNT=0
    while IFS= read -r _f; do
      [ -z "$_f" ] && continue
      if [ -e "$STATICDATA_REPO/$_f" ] || [ -L "$STATICDATA_REPO/$_f" ]; then
        if git -C "$STATICDATA_REPO" add -- "$_f" 2>/dev/null; then
          _ALLOWED_COUNT=$((_ALLOWED_COUNT + 1))
        else
          _STAGE_FAIL=1
        fi
      fi
    done <<EOF
$_GA_NEW_ADD
EOF
    if [ "$_STAGE_FAIL" = "1" ]; then
      echo "⚠ 数据闸门 add 阶段有失败项, 置 SYNC_FAIL=1, 按剩余成功项继续"
      SYNC_FAIL=1
    fi
    echo "  [数据闸门 add] 成功暂存 $_ALLOWED_COUNT 项(不用 git add -A, 防覆盖远端)"
    if [ "$_ALLOWED_COUNT" = "0" ]; then
      echo "✓ staticdata 数据闸门放行项全部落空,跳过 commit(仅磁盘留档)"
      _GIT_DONE=1
    fi
  else
    if ! git -C "$STATICDATA_REPO" add -A 2>/dev/null; then
      echo "⚠ git add 失败(staticdata 仓库 $STATICDATA_REPO), 置 SYNC_FAIL=1, 跳过 commit(git 历史缺口, 需人工排查)"
      SYNC_FAIL=1
      _GIT_DONE=1
    fi
  fi
  if [ "$_GIT_DONE" = "0" ] && git -C "$STATICDATA_REPO" diff --cached --quiet 2>/dev/null; then
    echo "✓ staticdata 无新变更,跳过 commit"
    _GIT_DONE=1
  fi
  if [ "$_GIT_DONE" = "0" ]; then
    # 与 async 守卫逐项同口径(diff-filter=d 排除已暂存删除 D, 2026-09-26 P1 自锁修复, 别改回去)
    _CS_OUT=$("$PY" "$GIT_REPO/scripts/large_json_excludes.py" --check-staged --repo "$STATICDATA_REPO" 2>/dev/null)
    _CS_RC=$?
    if [ "$_CS_RC" -eq 1 ]; then
      echo "⚠ 变更量超阈值, 跳过 commit/push 仅磁盘留档: $_CS_OUT"
      "$PY" "$REPO/scripts/notify.py" "[告警] staticdata 同步变更量超阈值跳过 commit" \
        "staticdata 同步(trigger=$TRIGGER) 变更量超阈值: $_CS_OUT<br>本次仅 rsync 磁盘留档未 commit/push(数据已留档, 次日 deploy 的 async 全量 rsync 会追平 git)。<br>若因大 JSON 未迁移: 请跑 bash scripts/migrate_large_json_out_of_git.sh 将其移出 staticdata git, 改走 R2 私有桶 large-json/ 每日备份。" \
        --from-prefix "[告警]" --alert-issue "staticdata同步变更量超阈值跳过commit" \
        --dedup-key staticdata_sync_oversize_skip --dedup-window 21600 "${_NOTIFY_DRY[@]+"${_NOTIFY_DRY[@]}"}" 2>/dev/null || true
      SYNC_FAIL=1
    else
      if [ "$_CS_RC" -eq 2 ]; then
        echo "⚠ --check-staged 判定异常(rc=2), 置 SYNC_FAIL=1, 继续 commit(best-effort, 守卫失效由 async 侧兜底)"
        SYNC_FAIL=1
      else
        echo "  [变更量] $_CS_OUT"
      fi
      _N=$(git -C "$STATICDATA_REPO" diff --cached --name-only | grep -c . || true)
      if ! git -C "$STATICDATA_REPO" commit -m "data backup [$TRIGGER] $(date +%Y-%m-%d_%H:%M) - ${_N} files" 2>/dev/null; then
        echo "⚠ staticdata commit 失败(best-effort)"
        SYNC_FAIL=1
      elif ! git -C "$STATICDATA_REPO" push origin main 2>/dev/null; then
        echo "⚠ staticdata push 失败(best-effort)"
        SYNC_FAIL=1
      fi
    fi
  fi
fi

if [ "$SYNC_FAIL" = "1" ]; then
  echo "⚠ staticdata 同步部分失败(best-effort,不阻塞调用方)"
  exit 0
fi
echo "✓ staticdata 同步完成"
exit 0
