#!/bin/bash
# 独立最小复现 #200(reviewer v2): fail 构造=镜像目标子目录缺失+父目录不可写(rsync mkdir 真失败)
set -u
AFTER=/tmp/rev-silence/after/scripts/update_all.sh

mk_env() {
  rm -rf "$1"; mkdir -p "$1/repo/static-site/data/nav_bucket" "$1/repo/static-site/data" "$1/gitrepo/static-site/data"
  echo seed1 > "$1/repo/static-site/data/nav_bucket/f1"
  echo seed2 > "$1/repo/static-site/data/etf_score_list_a.json"
  echo seed3 > "$1/repo/static-site/data/fund_score_a.json"
  if [ "$2" = "fail" ]; then chmod 500 "$1/gitrepo/static-site/data"; fi
}

run_after() {
  local work="/tmp/rev-silence/t200v2/after-$1"
  mk_env "$work" "$2"
  local LOG="$work/log.txt" REPO="$work/repo" GIT_REPO="$work/gitrepo"
  [ "$2" = "single" ] && GIT_REPO="$REPO"
  if [ "$2" = "fail" ]; then
    rsync -a --delete --checksum "$REPO/static-site/data/nav_bucket/" "$work/gitrepo/static-site/data/nav_bucket/" 2>/dev/null
    echo "[after/$1] bare_rsync_nav_rc=$?"
  fi
  eval "$(sed -n '119,121p' "$AFTER")"
  eval "$(sed -n '201,203p' "$AFTER")"
  eval "$(sed -n '240,242p' "$AFTER")"
  local NAV="${FUND_NAV_RSYNC_RC:-<unset>}" LIST="${SCORE_LIST_RSYNC_RC:-<unset>}" FUND="${FUND_SCORE_RSYNC_RC:-<unset>}"
  local SEVERE=0
  eval "$(sed -n '313,315p' "$AFTER")"
  local ISSUE="base:"
  if [ "$SEVERE" -eq 1 ]; then eval "$(sed -n '345,347p' "$AFTER")"; fi
  echo "[after/$1] nav_rc=$NAV list_rc=$LIST fund_rc=$FUND SEVERE=$SEVERE"
  echo "[after/$1] ISSUE=[$ISSUE]"
  echo "[after/$1] echo_lines_in_log=$(grep -c 'rsync 同步失败' "$LOG" 2>/dev/null || echo 0)"
  # 二次确认: nav 目标是否被创建(失败时应未创建)
  echo "[after/$1] nav_target_created=$([ -e "$GIT_REPO/static-site/data/nav_bucket" ] && echo YES || echo NO)"
  chmod -R 700 "$work" 2>/dev/null
}

echo "===== after 版三场景(fail 构造=v2) ====="
( run_after fail fail )
( run_after ok ok )
( run_after single single )
echo "===== 结论判定 ====="
