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

# export.py 末尾会自动走 R2 上传（用户规则：生成文件后直接走，不等超 300MB）。
# deploy.sh L123 自己跑 upload_r2.py 4 命令，故此处设 EXPORT_SKIP_R2=1 让 export.py 跳过，
# 避免重复跑 R2（deploy.sh 调 export.py 后自己跑 R2，重复上传浪费时间+带宽）。
export EXPORT_SKIP_R2=1

REPO="${REPO:-/Users/linhuichen/code/trade}"
GIT_REPO="${GIT_REPO:-/Users/linhuichen/code/trade}"   # git 始终在 trade 仓库(trade-data 不 git init,采集后 rsync 到 trade 上线)
PY="$REPO/.venv/bin/python"
EXPORT="$REPO/static-site/export.py"
LOGDIR="$REPO/data/logs"
STAMP=$(date +%Y%m%d_%H%M)
LOG="$LOGDIR/deploy_${STAMP}.log"
NAME="${1:-all}"   # 可选 pipeline 名（pipeline.sh 持锁调用时传入；无参=all）

mkdir -p "$LOGDIR"

echo "=== deploy.sh 开始 $(date '+%Y-%m-%d %H:%M:%S') ===" | tee "$LOG"

# 0. 时段闸门：交易日盘中 09:30-15:30 拒跑全量 export+deploy（防覆盖 intraday 实时版，事故 94c79041 根因）
# intraday_snapshot.sh 定时任务盘中每 30 分钟推 intraday_snapshot.json 到 main，
# 全量 deploy 会 export.py 重新生成 + git add 通配带入，易覆盖实时版。force 可绕过。
FORCE=0
case " $* " in *" force "*) FORCE=1;; esac
CURRENT_HM=$(date +%H%M)
IS_TRADING=$(cd "$REPO" && "$PY" -c "from app.calendar import is_trading_day; print(1 if is_trading_day() else 0)" 2>/dev/null || echo 0)
echo "时段闸门: IS_TRADING=${IS_TRADING} CURRENT_HM=$CURRENT_HM FORCE=$FORCE" | tee -a "$LOG"
if [ "$IS_TRADING" = "1" ] && [ "$CURRENT_HM" -ge 0930 ] && [ "$CURRENT_HM" -le 1530 ] && [ "$FORCE" != "1" ]; then
  echo "✗ 交易日盘中（09:30-15:30），拒跑全量 export+deploy（防覆盖 intraday 实时版；force 可绕过）" | tee -a "$LOG"
  exit 1
fi

# 0.5 防通配带入工作区残留旧版 intraday 文件（事故 94c79041 直接根因）
# deploy.sh git add static-site/data/ 通配会带入工作区任何残留文件。
# 跑 export.py 前先恢复 intraday_snapshot.json/.gz 到 origin/main 版（清工作区残留），再 unstage 保持 index 干净。
# export.py 随后重新生成覆盖；若 export.py 读滞后 DB 生成旧版（DB 不同步根因），此处无法防，需 symlink 方案。
echo "-> 恢复 intraday_snapshot.json/.gz 到 origin/main 版（防工作区残留带入通配 add）..." | tee -a "$LOG"
git -C "$GIT_REPO" fetch origin main 2>&1 | tee -a "$LOG" || true
git -C "$GIT_REPO" checkout origin/main -- static-site/data/intraday_snapshot.json static-site/data/intraday_snapshot.json.gz 2>/dev/null && \
  git -C "$GIT_REPO" reset HEAD -- static-site/data/intraday_snapshot.json static-site/data/intraday_snapshot.json.gz 2>/dev/null || true

# 1. 导出 JSON
echo "→ 运行 export.py 生成静态 JSON ..." | tee -a "$LOG"
"$PY" "$EXPORT" 2>&1 | tee -a "$LOG"
EXPORT_RC=${PIPESTATUS[0]}
if [ "$EXPORT_RC" -ne 0 ]; then
  echo "✗ export.py 失败(退出码 $EXPORT_RC)，终止部署" | tee -a "$LOG"
  exit "$EXPORT_RC"
fi
echo "✓ export.py 完成" | tee -a "$LOG"

# 1.4 刷新计划任务执行统计（gen_schedule_stats.py）已移到各任务脚本结尾（2026-07-24 方案A根治）：
#   原在 deploy.sh:72 跑时，调 deploy 的任务脚本（futures/lhb/etf 等）尚未写"结束"行，
#   gen_stats 解析当前任务 log 显示 pending（exit=null）。移到各任务脚本"结束"行后调用，
#   gen_stats 能读到完整"开始+结束"对，正确配对。各任务脚本：futures_backfill/lhb_backfill/
#   etf_national_team_backfill/update_lab/update_all 结尾 + rzhb_backfill(trap) + intraday_snapshot +
#   backfill_metrics 已各自调用。手动 deploy 不刷 schedule_stats（无任务脚本上下文），下次任务跑时刷新。

# 1.4b 生成 RSS feed.xml（读 summary_history.json，随 static-site/data/ 上线）
# 每次部署刷新，供 RSS 阅读器订阅当日收盘情绪。失败不阻断部署。
echo "-> 运行 gen_rss.py 生成 RSS feed.xml ..." | tee -a "$LOG"
"$PY" "$REPO/scripts/gen_rss.py" 2>&1 | tee -a "$LOG"
GENRSS_RC=${PIPESTATUS[0]}
if [ "$GENRSS_RC" -ne 0 ]; then
  echo "⚠ gen_rss.py 失败(退出码 $GENRSS_RC)，feed.xml 可能过期，继续部署" | tee -a "$LOG"
fi

# 1.5 重新生成 minified JS（确保 app.min.js/lab.min.js 与源 app.js/lab.js 同步）
# 安全网：dev 改了 app.js 源码但忘跑 build_min.py 时，此处补生成。
# build_min.py 失败不阻断数据部署（已有 min 文件仍可用），仅告警。
echo "→ 运行 build_min.py 重新生成 min JS ..." | tee -a "$LOG"
"$PY" "$REPO/scripts/build_min.py" 2>&1 | tee -a "$LOG"
BUILD_RC=${PIPESTATUS[0]}
if [ "$BUILD_RC" -ne 0 ]; then
  echo "⚠ build_min.py 失败(退出码 $BUILD_RC)，min JS 可能过期，继续数据部署" | tee -a "$LOG"
else
  echo "✓ build_min.py 完成" | tee -a "$LOG"
fi

# 1.6 rsync 静态 JSON 到 trade git 仓库（trade-data 架构：采集在 trade-data，git 上线在 trade）
# trade 跑时 REPO=GIT_REPO=trade，rsync 同路径 no-op；trade-data 跑时 rsync trade-data->trade。
# build_min.py 在 trade-data 可能失败（无 app.js 源），但 min JS 不影响数据上线（trade 已有 min JS）。
if [ "$REPO" != "$GIT_REPO" ]; then
  echo "-> rsync 静态 JSON: $REPO/static-site/data/ -> $GIT_REPO/static-site/data/ ..." | tee -a "$LOG"
  # --checksum：同 size+mtime 文件（如 schedule_stats.json）quick check 跳过致线上滞后，强制 MD5 比对根治
  rsync -a --checksum "$REPO/static-site/data/" "$GIT_REPO/static-site/data/" 2>&1 | tee -a "$LOG"
  RSYNC_RC=${PIPESTATUS[0]}
  if [ "$RSYNC_RC" -ne 0 ]; then
    echo "✗ rsync 失败(退出码 $RSYNC_RC)，终止部署" | tee -a "$LOG"
    exit "$RSYNC_RC"
  fi
  echo "✓ rsync 完成($REPO -> $GIT_REPO)" | tee -a "$LOG"
fi

# 1.7 rsync 采集 DB/数据到 trade 仓库（保持 trade/data/ 同步：诊断 + 手动从 trade 跑 deploy 能读最新 DB）
# 仅 trade-data 跑时触发（REPO != GIT_REPO）；排除 logs/（日志各自独立不互相同步）。
# 失败不阻断部署（static-site/data/ JSON 已上线，DB 同步仅兜底）。
if [ "$REPO" != "$GIT_REPO" ]; then
  echo "-> rsync 采集数据: $REPO/data/ -> $GIT_REPO/data/ (exclude logs) ..." | tee -a "$LOG"
  rsync -a --exclude=logs/ "$REPO/data/" "$GIT_REPO/data/" 2>&1 | tee -a "$LOG"
  RSYNC_DB_RC=${PIPESTATUS[0]}
  if [ "$RSYNC_DB_RC" -ne 0 ]; then
    echo "⚠ rsync data/ 失败(退出码 $RSYNC_DB_RC)，不阻断部署(static-site/data/ JSON 已上线)" | tee -a "$LOG"
  else
    echo "✓ rsync data/ 完成（DB 同步到 $GIT_REPO/data/）" | tee -a "$LOG"
  fi
fi

# 1.8 上传 lab/*.json + trade_sim/*.html + index/ + industry/ 到 R2
# (R2 全迁后 index/industry/trade_sim 前端从 R2 读;lab 已在 R2;双源过渡也刷 R2 保最新)
#
# R2 上传超时监控（A3，2026-07-23）：upload_r2 卡 TCP SYN_SENT 会持 deploy.lock
# 阻塞后续 update_all（2026-07-23 实测卡 8分20秒，主控 kill 释放锁）。
# macOS 无 timeout/gtimeout 命令，用 bash 原生 background+sleep+kill 实现：
# 后台跑 upload_r2，每 5s 探活，超 R2_UPLOAD_TIMEOUT（默认 300s=5min）即 kill 释放锁。
R2_UPLOAD_TIMEOUT="${R2_UPLOAD_TIMEOUT:-300}"
run_r2_upload() {
  local desc="$1"; shift
  local tmp_log pid slept rc
  tmp_log=$(mktemp)
  "$PY" "$REPO/scripts/upload_r2.py" "$@" >"$tmp_log" 2>&1 &
  pid=$!
  slept=0
  while kill -0 "$pid" 2>/dev/null; do
    sleep 5
    slept=$((slept + 5))
    if [ "$slept" -ge "$R2_UPLOAD_TIMEOUT" ]; then
      echo "⚠ $desc 超 ${R2_UPLOAD_TIMEOUT}s 未退出，kill pid=$pid 释放 deploy.lock" | tee -a "$LOG"
      kill -TERM "$pid" 2>/dev/null; sleep 2
      kill -KILL "$pid" 2>/dev/null || true
      wait "$pid" 2>/dev/null || true
      rm -f "$tmp_log"
      return 1
    fi
  done
  wait "$pid"; rc=$?
  tail -1 "$tmp_log" | tee -a "$LOG"
  rm -f "$tmp_log"
  return "$rc"
}

echo "-> 上传 lab/trade_sim/index/industry/data-large 到 R2 ..." | tee -a "$LOG"
run_r2_upload "upload-lab" upload-lab || echo "⚠ upload-lab 失败/超时,继续部署" | tee -a "$LOG"
run_r2_upload "upload-trade-sim" upload-trade-sim || echo "⚠ upload-trade-sim 失败/超时,继续部署" | tee -a "$LOG"
run_r2_upload "upload-trade-sim-json" upload-trade-sim-json || echo "⚠ upload-trade-sim-json 失败/超时,继续部署" | tee -a "$LOG"
run_r2_upload "upload-index" upload-index || echo "⚠ upload-index 失败/超时,继续部署" | tee -a "$LOG"
run_r2_upload "upload-industry" upload-industry || echo "⚠ upload-industry 失败/超时,继续部署" | tee -a "$LOG"
run_r2_upload "upload-data-large" upload-data-large || echo "⚠ upload-data-large 失败/超时,继续部署" | tee -a "$LOG"

# 2. git add 静态数据 + min JS（精确文件列表，根治通配带入残留旧文件）
# 2026-07-20 intraday 回退事故根因：原 `git add static-site/data/` 目录级通配会带入
# 工作区任何残留文件（含 export.py 不再生成的废弃残留，如 etf_national_team-1m.json）。
# 改为精确文件列表：只 add export.py + deploy.sh 生成/上线的 JSON（+ .gz 副本）+ min JS。
# - export.py: overview, tab×6ranges, industry 拆分, 单文件, etf_national_team×6ranges(无1m)
# - 各任务脚本结尾: gen_schedule_stats(schedule_stats) [2026-07-24 方案A从 deploy.sh 移出]
# - deploy.sh: gen_rss(feed.xml), build_min(app/lab.min.js)
# - update_all.sh/update_lab.sh 靠 deploy 上线: alert, etf_score_list, lab_*(4个)
# - alert_analyze_*.json 动态(40宽基+行业，新增品种自动覆盖)，用前缀通配(只匹配 alert_analyze_ 前缀)
# - 不含: etf_national_team-1m.json(废弃), index/industry-*-indices/lab/trade_sim/(.gitignore R2托管)
# - 不含: tab 大 range all/5y/3y + global-extras-all（R2 托管，.gitignore 移出，前端 dataUrl() 路由）
echo "-> git add 精确文件列表（export.py + deploy.sh 生成 JSON + min JS）..." | tee -a "$LOG"
DATA_FILES=()
# tab × 小 range 3m/6m/1y（大 range all/5y/3y + global-extras-all 已 R2 托管，.gitignore 移出减 ~58M）
for _tab in a-stock hk global sentiment; do
  for _rng in 3m 6m 1y; do
    DATA_FILES+=("static-site/data/${_tab}-${_rng}.json" "static-site/data/${_tab}-${_rng}.json.gz")
  done
done
# global-extras-all 已 R2 托管（upload-data-large 上传，前端 dataUrl() 路由），不进 git
# industry: 仅 meta 留 git（3m/6m/1y 单文件 + all/5y/3y-concepts 已 R2 托管，.gitignore 移出减 ~24M）
# industry-*-meta 是 4KB 小文件，留 git 作元数据参考；前端 meta 也从 R2 读但 git 带冗余可忽略
for _rng in all 5y 3y; do
  DATA_FILES+=("static-site/data/industry-${_rng}-meta.json" "static-site/data/industry-${_rng}-meta.json.gz")
done
# etf_national_team × 小 range 1m/3m/6m/1y（大 range all/5y/3y 已 R2 托管）+ quarterly + holders
# 1m 由 pipeline_daily export_json_files 生成(非 export.py),deploy git add 工作区最新版
for _rng in 1m 3m 6m 1y; do
  DATA_FILES+=("static-site/data/etf_national_team-${_rng}.json" "static-site/data/etf_national_team-${_rng}.json.gz")
done
DATA_FILES+=("static-site/data/etf_national_team_quarterly.json" "static-site/data/etf_national_team_quarterly.json.gz")
DATA_FILES+=("static-site/data/etf_national_team_holders.json" "static-site/data/etf_national_team_holders.json.gz")
# 单文件（export.py 生成 + deploy/update_all/update_lab 生成）
for _f in overview futures ad_line volume_ratio position \
          summary summary_history signal_freq signal_stats \
          rotation new_high_low ma_alignment intraday_snapshot \
          schedule_stats alert etf_score_list \
          lab_ablation lab_cost_compare lab_param_scan lab_short_symmetry; do
  DATA_FILES+=("static-site/data/${_f}.json" "static-site/data/${_f}.json.gz")
done
# feed.xml（gen_rss.py 生成，非 .json）+ min JS
DATA_FILES+=("static-site/data/feed.xml" "static-site/app.min.js" "static-site/lab.min.js")
# 精确文件列表 git add（部分文件不存在时 git 报 fatal 但继续，不影响其余 add；deploy 无 set -e 不阻塞）
git -C "$GIT_REPO" add "${DATA_FILES[@]}" 2>&1 | tee -a "$LOG" || true
# alert_analyze_*.json 动态列表（40 宽基+行业，新增品种自动覆盖），前缀通配只匹配 alert_analyze_
git -C "$GIT_REPO" add static-site/data/alert_analyze_*.json static-site/data/alert_analyze_*.json.gz 2>&1 | tee -a "$LOG" || true

# 3. 检查有无变更（cached diff 非空才 commit；无变更跳过 commit 但仍 push）
if git -C "$GIT_REPO" diff --cached --quiet; then
  echo "✓ 无新数据变更，跳过 commit（仍 push 推未 push commit）" | tee -a "$LOG"
else
  # 4. 有变更 → commit
  COMMIT_MSG="data update [$NAME] $(date +%Y-%m-%d_%H:%M)"
  echo "→ git commit: $COMMIT_MSG" | tee -a "$LOG"
  git -C "$GIT_REPO" commit -m "$COMMIT_MSG" 2>&1 | tee -a "$LOG"
  COMMIT_RC=${PIPESTATUS[0]}
  if [ "$COMMIT_RC" -ne 0 ]; then
    echo "✗ git commit 失败(退出码 $COMMIT_RC)" | tee -a "$LOG"
    exit "$COMMIT_RC"
  fi
fi

# 5. 总是 git push（幂等：有未 push commit 就推，无则 "Everything up-to-date"）
echo "→ git push ..." | tee -a "$LOG"
git -C "$GIT_REPO" push origin HEAD:main 2>&1 | tee -a "$LOG"
# :-1 防御 set -u 未绑定（macOS bash 3.2 数组边界用例）；默认失败不掩盖真实 rc（区别于旧 :-0）
PUSH_RC=${PIPESTATUS[0]:-1}
if [ "$PUSH_RC" -ne 0 ]; then
  # 可能是并发竞争 non-fast-forward：fetch 后确认 HEAD 是否已被推到 origin/main
  git -C "$GIT_REPO" fetch origin main 2>&1 | tee -a "$LOG" || true
  if git -C "$GIT_REPO" merge-base --is-ancestor HEAD origin/main 2>/dev/null; then
    echo "⚠ push 返回 $PUSH_RC 但 HEAD 已在 origin/main（并发 deploy 已推送），视为幂等成功" | tee -a "$LOG"
    PUSH_RC=0
  else
    # 本地落后 origin/main（并发 deploy 已推新 commit）：rebase 到 origin/main 后重试 push 一次。
    # 数据 JSON 提交通常不冲突；冲突则 abort 保持工作区干净，退出待人工 rebase 后重跑。
    echo "-> 本地落后 origin/main，rebase 后重试 push ..." | tee -a "$LOG"
    # 2026-07-24 stash预防（事故根因：工作区有 tracked M 文件如 signal_stats.json/
    # sw_components.json/TASKS.md 时，rebase 报 "cannot rebase: you have unstaged changes" 失败）：
    # rebase 前自动 stash tracked M 文件，rebase 后两条路径（成功 push 后 / 失败 abort 后）都 pop 恢复。
    # 只 stash tracked M（不加 -u），不碰 untracked DB（sentiment.db/etf_national_team.db 已 gitignore）。
    STASH_CNT_BEFORE=$(git -C "$GIT_REPO" stash list 2>/dev/null | wc -l | tr -d ' ')
    git -C "$GIT_REPO" stash push -m "deploy.sh-rebase-$(date +%Y%m%d_%H%M%S)" 2>&1 | tee -a "$LOG" || true
    STASH_CNT_AFTER=$(git -C "$GIT_REPO" stash list 2>/dev/null | wc -l | tr -d ' ')
    REBASE_STASHED=0
    if [ "$STASH_CNT_AFTER" -gt "$STASH_CNT_BEFORE" ]; then
      REBASE_STASHED=1
      echo "✓ rebase 前已 stash 工作区 tracked M 文件（stash@{0}）" | tee -a "$LOG"
    else
      echo "  工作区无 tracked M 文件需 stash（或 stash 无变化跳过）" | tee -a "$LOG"
    fi
    # rebase 后恢复 stash 的 helper（pop 冲突则保留 stash 待手动处理，不阻塞 push）
    pop_rebase_stash() {
      if [ "$REBASE_STASHED" = "1" ]; then
        git -C "$GIT_REPO" stash pop 2>&1 | tee -a "$LOG" \
          || echo "⚠ stash pop 失败/冲突，保留 stash@{0} 待手动 git stash pop" | tee -a "$LOG"
      fi
    }
    git -C "$GIT_REPO" rebase origin/main 2>&1 | tee -a "$LOG"
    REBASE_RC=${PIPESTATUS[0]:-1}
    if [ "$REBASE_RC" -eq 0 ]; then
      git -C "$GIT_REPO" push origin HEAD:main 2>&1 | tee -a "$LOG"
      PUSH_RC=${PIPESTATUS[0]:-1}
      pop_rebase_stash   # push 后恢复工作区 M 文件（无论 push 成功失败都 pop）
      if [ "$PUSH_RC" -eq 0 ]; then
        echo "✓ rebase + 重试 push 成功" | tee -a "$LOG"
      else
        echo "✗ rebase 后重试 push 仍失败(退出码 $PUSH_RC)" | tee -a "$LOG"
        exit "$PUSH_RC"
      fi
    else
      git -C "$GIT_REPO" rebase --abort 2>/dev/null || true
      pop_rebase_stash   # abort 后恢复工作区 M 文件（已回到 rebase 前状态，pop 安全）
      echo "✗ rebase origin/main 失败（可能数据 JSON 冲突），已 abort 保持工作区干净。" | tee -a "$LOG"
      echo "  请手动：git -C $GIT_REPO fetch origin && git -C $GIT_REPO rebase origin/main，解决冲突后重跑 deploy.sh" | tee -a "$LOG"
      exit 1
    fi
  fi
fi

echo "✓ push 成功（MaoziYun 自动拉取 git main 部署，有拉取延迟 + max-age=1200 缓存；wrangler 未安装，worker/headers.js 待迁 CF Workers 后手动 wrangler deploy）" | tee -a "$LOG"
echo "=== deploy.sh 结束 $(date '+%Y-%m-%d %H:%M:%S') 退出码=0 ===" | tee -a "$LOG"
exit 0
