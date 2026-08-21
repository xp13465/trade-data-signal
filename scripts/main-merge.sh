#!/usr/bin/env bash
# =============================================================================
# main-merge.sh - push main 统一入口(防再犯机制 D, 2026-08-19 实施)
#
# 背景: 冲突覆盖根因 docs/conflict-overwrite-rootcause-2026-08-18.md(§五.D) +
#       诱因链 docs/conflict-overwrite-triggers-2026-08-18.md(缺口③ push 控制面分散)。
#       08-18 多 agent 各自直接 push main 缺 commit / deploy 非 main 分支 push HEAD:main
#       带上 feat commit(根因 §三.4)。本脚本把「merge + push main」收敛成唯一权威入口:
#       agent 只推 feat 分支, merge+push main 一律由主控走本脚本。
#
# 流程(严格按此, 任一 FAIL 即停不静默):
#   1. 校验入参 feat 分支名存在 + 当前在 main
#   2. §14 安全窗口检查: 盘后时点(15:35/16:00/17:50/20:35/22:00)拒绝 merge+push, 提示
#   3. git fetch origin + checkout main + 确认 main 已是最新
#   4. 校验 feat 分支 base 新鲜: 最近一次 rebase 基点距 origin/main 无净回退(调 check_version_progress)
#   5. merge feat(冲突即停报, 绝不静默 §23.11)
#   6. 若 feat 改了前端源码(8 源: app/lab/common/style/lab.css/purpose-notes/kelly-review-notes/kelly-reports-content, 与 build_min.py 对齐): 统一跑 build_min + bump_asset_version(版本串唯一权威入口, 机制 C)
#   7. §24⑤ 校验 index 引用 == 实际文件内容 md5(统一 bump 后内容哈希==引用)
#   8. 调 check_version_progress.py(A/B: 版本串倒退哨兵 + merge 净回退校验) → FAIL 阻断
#   9. commit(自动追加 Co-Authored-By) + push main
#
# 用法:
#   bash scripts/main-merge.sh <feat 分支名> [--dry-run]
#   --dry-run: 演练不真 merge/push(第 5/9 步跳过, 其余校验照跑)
#
# 依赖: scripts/check_version_progress.py(机制 A/B) + scripts/build_min.py + scripts/bump_asset_version.py(机制 C)
# =============================================================================
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
GIT="git -C $REPO"
PY="python3"

DRY_RUN=0
# --dry-run 可在任意位置出现(防手滑把 <feat> --dry-run 顺序写反被当真实运行 → 意外 push main)
# 用法正文写 <feat> [--dry-run], 但此处容忍任意位置, 提高安全性(§23.11 防意外)
case " $* " in
  *" --dry-run "*) DRY_RUN=1;;
esac
# 移除 --dry-run 保留 feat
ARGS=()
for a in "$@"; do
  if [[ "$a" != "--dry-run" ]]; then ARGS+=("$a"); fi
done
FEAT="${ARGS[0]:-}"
if [[ -z "$FEAT" ]]; then
  echo "✗ 用法: bash scripts/main-merge.sh <feat 分支名> [--dry-run]" >&2
  exit 2
fi

# 盘后定时任务时点(§14 安全窗口): 这些时刻 ±缓冲内不 merge+push main
DISK_AFTER_TIMES=("15:35" "16:00" "17:50" "20:35" "22:00")
# 缓冲分钟: update_all 17:50 启动后可能持续几分钟, 精确匹配会漏掉 17:51 push 放行
DISK_AFTER_BUFFER_MIN=5

current_time() {
  # Asia/Shanghai 时区 HH:MM
  TZ=Asia/Shanghai date +%H:%M
}

time_to_min() {
  # HH:MM → 当日分钟数(10# 防 08:xx 被当八进制)
  local hhmm="$1"
  local hh="${hhmm%%:*}" mm="${hhmm##*:}"
  echo $(( 10#$hh * 60 + 10#$mm ))
}

check_disk_after() {
  local now; now="$(current_time)"
  local now_min; now_min="$(time_to_min "$now")"
  local t t_min diff
  for t in "${DISK_AFTER_TIMES[@]}"; do
    t_min="$(time_to_min "$t")"
    diff=$(( now_min - t_min ))
    if [[ $diff -lt 0 ]]; then diff=$(( -diff )); fi
    if [[ "$diff" -le "$DISK_AFTER_BUFFER_MIN" ]]; then
      echo "✗ 当前时点 $now 落在盘后定时任务 $t ±${DISK_AFTER_BUFFER_MIN}min 缓冲窗口内, 拒绝 merge+push main(§14 生产稳定性 P0)" >&2
      echo "  建议挪到安全窗口 23:00 后或避开该时点再跑。" >&2
      exit 3
    fi
  done
  echo "✓ §14 安全窗口: 当前时点 $now 未撞盘后任务时点(±${DISK_AFTER_BUFFER_MIN}min)"
}

echo "=== main-merge.sh(push main 统一入口, 防再犯机制 D) ==="
echo "  repo   : $REPO"
echo "  feat   : $FEAT"
echo "  dry-run: $DRY_RUN"

# 1. 校验当前分支 + feat 分支存在
CUR_BRANCH="$($GIT branch --show-current)"
if [[ "$CUR_BRANCH" != "main" ]]; then
  echo "✗ 当前分支是 $CUR_BRANCH, 非 main。请先 checkout main 再跑本脚本" >&2
  exit 2
fi
if ! $GIT show-ref --verify --quiet "refs/heads/$FEAT"; then
  echo "✗ feat 分支 $FEAT 不存在(refs/heads/$FEAT)" >&2
  exit 2
fi

# 2. §14 安全窗口检查
check_disk_after

# 3. fetch + 确认 main 最新(区分 领先/落后/分叉 三态; 本地领先跳过 rebase; rebase 前查工作区干净)
echo "--- fetch origin ---"
$GIT fetch origin
LOCAL_MAIN="$($GIT rev-parse main)"
REMOTE_MAIN="$($GIT rev-parse origin/main)"
if [[ "$LOCAL_MAIN" == "$REMOTE_MAIN" ]]; then
  echo "✓ main 已与 origin/main 一致(${REMOTE_MAIN:0:8}), 无需 rebase"
elif $GIT merge-base --is-ancestor origin/main main 2>/dev/null; then
  # origin/main 是 main 祖先 → 本地领先(存在未 push 的本地 commit), rebase 是多余操作直接跳过
  LOCAL_AHEAD="$($GIT rev-list --count origin/main..main)"
  echo "✓ 本地 main 领先 origin/main ${LOCAL_AHEAD} commit(本地未 push), 跳过 rebase(多余操作)"
else
  # 落后 或 分叉 → 需 rebase; rebase 前显式查工作区干净
  if ! $GIT diff --quiet || ! $GIT diff --cached --quiet; then
    echo "✗ 需要 rebase 但工作区有未提交改动。请先处理工作区再跑本脚本" >&2
    echo "  绝不静默 stash/丢弃改动(§23.11): 请主控人工决定这些改动的去留" >&2
    echo "  --- 当前未提交改动 ---" >&2
    $GIT status --porcelain | head -20 >&2
    exit 6
  fi
  if $GIT merge-base --is-ancestor main origin/main 2>/dev/null; then
    echo "⚠️ 本地 main 落后 origin/main, 执行 rebase 快进(origin 已含本地没有的 commit)"
  else
    echo "⚠️ 本地 main 与 origin/main 分叉, 执行 rebase(可能产生冲突, 冲突即停不静默 §23.11)"
  fi
  if ! $GIT rebase origin/main; then
    echo "✗ rebase main 冲突/失败, 已 abort。请主控人工处理本地 main 未推送改动后, 再跑本脚本(§23.11 绝不静默)" >&2
    $GIT rebase --abort >/dev/null 2>&1 || true
    exit 7
  fi
  echo "✓ rebase 完成"
fi
echo "✓ main 位于 origin/main(${REMOTE_MAIN:0:8}) 之上"

# 4. 校验 feat 分支 base 新鲜(缺口① 事前防线): feat 的 base 是否落后 origin/main 过多
#    用 merge-base 看 feat 相对 origin/main 的落后 commit 数; 落后过多则提示先 rebase
FEAT_MERGE_BASE="$($GIT merge-base origin/main "$FEAT")"
BEHIND_COUNT="$($GIT rev-list --count "$FEAT_MERGE_BASE"..origin/main)"
echo "  feat($FEAT) merge-base=$($GIT rev-parse "$FEAT" | cut -c1-8), 相对 origin/main 落后 $BEHIND_COUNT commit"
if [[ "$BEHIND_COUNT" -gt 0 ]]; then
  echo "⚠️ feat 分支 $FEAT 相对 origin/main 落后 $BEHIND_COUNT commit, base 可能不新鲜"
  echo "  建议: git fetch origin && git -C $REPO rebase origin/main (在 feat 分支上) 后再 merge"
  echo "  (缺口① base 新鲜度事前校验: base 落后仍可继续, 但 merge 前请确认无冲突/无净回退)"
fi

# 5. merge feat(冲突即停, 绝不静默 §23.11)
echo "--- merge $FEAT into main ---"
echo "  checkout main"
$GIT checkout main
MERGE_MSG="merge(feat/$FEAT): 统一入口合并 $FEAT 入 main"
if [[ "$DRY_RUN" == "1" ]]; then
  echo "  [dry-run] 跳过实际 merge"
else
  if ! $GIT merge "$FEAT" --no-edit -m "$MERGE_MSG"; then
    echo "✗ merge 冲突(或失败), 已停下。绝不静默 resolve(§23.11)" >&2
    echo "  请主控人工处理冲突后, 再重跑本脚本或手动 commit" >&2
    exit 4
  fi
  echo "✓ merge 成功(无冲突)"
fi

# 6. 若 feat 改了前端源码, 统一 build_min + bump(机制 C 版本串唯一权威入口)
#    检测: feat 相对 origin/main 是否触碰关键源文件
#    ⚠️ 产物清单必须与 scripts/build_min.py 全量对齐(8 对):
#      common/purpose-notes/kelly-review-notes/kelly-reports-content/app/lab 的 .min.js
#      + style.min.css + lab.min.css。
#    缺失任何源(尤其 3 个 notes 公示文件, §21 典型场景只改 purpose-notes.js)= 检测不到→不 bump→公示不上线。
SRC_FILES=("app.js" "lab.js" "common.js" "style.css" "lab.css" \
           "purpose-notes.js" "kelly-review-notes.js" "kelly-reports-content.js")
CHANGED_SRC=""
for src in "${SRC_FILES[@]}"; do
  if $GIT diff --quiet "origin/main...$FEAT" -- "static-site/$src" 2>/dev/null; then
    :
  else
    CHANGED_SRC="$CHANGED_SRC $src"
  fi
done

if [[ -n "$CHANGED_SRC" ]]; then
  echo "--- feat 触碰前端源码:$CHANGED_SRC, 统一 build_min + bump(版本串唯一权威入口) ---"
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "  [dry-run] 跳过 build_min/bump"
  else
    ( cd "$REPO" && "$PY" scripts/build_min.py )
    ( cd "$REPO" && "$PY" scripts/bump_asset_version.py )
    # bump 后 main 工作区 index.html/min 已变, 需要 commit 才走后续校验
    echo "  ✓ build_min + bump 完成, 待 commit"
  fi
else
  echo "  feat 未触碰前端源码(8 源: app/lab/common/style/lab.css/purpose-notes/kelly-review-notes/kelly-reports-content), 跳过统一 bump"
fi

# 7. §24⑤ 校验 index 引用版本串 == 实际文件内容 md5
#    这里用 check_version_progress.py 的 A 任务承担(版本串 ≥ 祖先天花板 + 源码 diff 必须前进);
#    §24⑤ 的「内容哈希==引用」由 bump 脚本自身保证(每次 bump 强制换新串)。
echo "--- §24⑤ 版本串/净回退校验(机制 A/B) ---"
if [[ "$DRY_RUN" == "1" ]]; then
  echo "  [dry-run] 跳过 check_version_progress"
else
  if ! "$PY" "$REPO/scripts/check_version_progress.py" --site-dir "$REPO/static-site" --repo "$REPO" --deploy-mode; then
    echo "✗ 版本串倒退/净回退校验 FAIL, 阻断上线(§24⑤/§23.11)" >&2
    exit 1
  fi
fi

# 8. commit(自动追加 Co-Authored-By) + push main
if [[ "$DRY_RUN" == "1" ]]; then
  echo "[dry-run] 跳过 commit + push main"
  echo "=== dry-run 演练完成(未实际 merge/push) ==="
  exit 0
fi

echo "--- commit + push main ---"
if ! $GIT diff --cached --quiet; then
  # merge 本身已有 index 变更(merge commit 已生成), 不重复 add
  :
fi
# 若 bump 后工作区有未暂存变更(第 6 步 build_min/bump 产生的 min/html/sw.js 变更), 需 add
# ⚠️ 13 个 bump 产物全量 add(与 bump_asset_version.py 实际写入对齐):
#    8 个 min 产物(common/purpose-notes/kelly-review-notes/kelly-reports-content/app/lab
#    的 .min.js + style.min.css + lab.min.css)
#    + 4 个 html(index/about/guide/privacy——bump 脚本对 static-site/*.html 全量 glob,
#    当前含 ?v= 引用会被写入的就是这 4 个; 其余 8 个 html(databrief/trade_sim*)无资源引用
#    不会被写入, 不列) + sw.js。
#    漏 add = 版本串更新残留工作区进不了 git, 线上引用旧版本串(CSS 一变即 §24 孤儿快照断链;
#    2026-08-22 凌晨两次 merge 后 about/guide/privacy 均复现, main 7cb8208a0 手工补提交)。
# ⚠️ 判断条件只盯 bump 产物 diff, 不用整个工作区 diff(2026-08-19 实测卡死根因):
#    工作区若存在与本次 merge 无关的未提交改动(如 claude-work-mode/README.md 由
#    token-cache-stats 定时任务追加命中率走势产生), 全工作区 diff 会误入本分支,
#    而 bump 产物本次无变更 → git commit 空提交失败 exit 1(set -e 下卡住整个 merge)。
BUMP_PRODUCTS=(static-site/app.min.js static-site/lab.min.js static-site/common.min.js \
               static-site/purpose-notes.min.js static-site/kelly-review-notes.min.js \
               static-site/kelly-reports-content.min.js \
               static-site/style.min.css static-site/lab.min.css \
               static-site/index.html static-site/about.html \
               static-site/guide.html static-site/privacy.html \
               static-site/sw.js)
if ! $GIT diff --quiet -- "${BUMP_PRODUCTS[@]}"; then
  $GIT add "${BUMP_PRODUCTS[@]}"
  $GIT commit -m "build(统一bump): main-merge.sh 统一 build_min+bump 版本串(机制C, feat=$FEAT)

Co-Authored-By: Claude <noreply@anthropic.com>"
fi

# merge commit 若未生成(pure bump 无 merge?)确保有 commit; 这里以 merge 已生成 commit 为准
# push main
if ! $GIT push origin main; then
  echo "✗ push main 失败(可能 non-fast-forward)。优先 git fetch + rebase origin/main + 重试(§8 不 force)" >&2
  $GIT fetch origin
  $GIT rebase origin/main || { echo "✗ rebase 失败, 已 abort, 请人工处理" >&2; $GIT rebase --abort; exit 5; }
  $GIT push origin main
fi
echo "✓ push main 成功"
echo "=== main-merge.sh 完成(feat=$FEAT 已合入并推送 main) ==="
