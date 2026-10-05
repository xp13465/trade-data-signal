#!/bin/bash
# 独立最小复现 #200(reviewer 版): 抽真 update_all.sh 同段码 + rsync 真跑双态对照
# 禁端到端跑 update_all.sh; 本 harness 只 eval 真文件中 5 个片段
set -u
AFTER=/tmp/rev-silence/after/scripts/update_all.sh
BEFORE=/tmp/rev-silence/before/scripts/update_all.sh

mk_env() { # $1=work dir $2=mode
  rm -rf "$1"; mkdir -p "$1/repo/static-site/data/nav_bucket" "$1/repo/static-site/data" "$1/gitrepo/static-site/data"
  echo seed > "$1/repo/static-site/data/nav_bucket/f1"
  echo seed > "$1/repo/static-site/data/etf_score_list_a.json"
  echo seed > "$1/repo/static-site/data/fund_score_a.json"
  if [ "$2" = "fail" ]; then
    mkdir -p "$1/gitrepo/static-site/data/nav_bucket"
    touch "$1/gitrepo/static-site/data/etf_score_list_a.json" "$1/gitrepo/static-site/data/fund_score_a.json"
    chmod 500 "$1/gitrepo/static-site/data" "$1/gitrepo/static-site/data/nav_bucket"
  fi
}

run_after() { # $1=name $2=mode(fail|ok|single)
  local work="/tmp/rev-silence/t200/after-$1"
  mk_env "$work" "$2"
  local LOG="$work/log.txt" REPO="$work/repo" GIT_REPO="$work/gitrepo"
  [ "$2" = "single" ] && GIT_REPO="$REPO"
  if [ "$2" = "fail" ]; then
    # 裸跑对照: 同参数 rsync 直接跑, 拿真实 rc
    rsync -a --delete --checksum "$REPO/static-site/data/nav_bucket/" "$work/gitrepo/static-site/data/nav_bucket/" 2>/dev/null
    echo "[after/$1] bare_rsync_rc=$?"
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
  chmod -R 700 "$work" 2>/dev/null
}

run_before() { # $1=name $2=mode
  local work="/tmp/rev-silence/t200/before-$1"
  mk_env "$work" "$2"
  local LOG="$work/log.txt" REPO="$work/repo" GIT_REPO="$work/gitrepo"
  eval "$(sed -n '118,119p' "$BEFORE")"
  eval "$(sed -n '198,199p' "$BEFORE")"
  eval "$(sed -n '235,236p' "$BEFORE")"
  echo "[before/$1] echo_lines_in_log=$(grep -c 'rsync 同步失败' "$LOG" 2>/dev/null || echo 0)"
  echo "[before/$1] SEVERE-聚合区RSYNC判据数=$(sed -n '290,310p' "$BEFORE" | grep -c 'RSYNC' || true)"
  chmod -R 700 "$work" 2>/dev/null
}

echo "===== A. after 版三场景(真码 eval, rsync 真跑) ====="
( run_after fail fail )
( run_after ok ok )
( run_after single single )
echo
echo "===== B. before 版对照(病灶证明) ====="
( run_before fail fail )
echo
echo "===== C. 两版语法 ====="
bash -n "$AFTER" && echo "after bash -n OK"; bash -n "$BEFORE" && echo "before bash -n OK"
echo
echo "===== D. after 版聚合区 rsync 判据行(真实存在性) ====="
grep -n 'RSYNC_RC' "$AFTER"
