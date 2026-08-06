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

REPO="${REPO:-/Users/linhuichen/code/trade-data}"
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
# 跑 export.py 前先恢复 intraday_snapshot.json/.gz + notifications.json/.gz 到 origin/main 版（清工作区残留），再 unstage 保持 index 干净。
# export.py 随后重新生成覆盖；若 export.py 读滞后 DB 生成旧版（DB 不同步根因），此处无法防，需 symlink 方案。
# 2026-07-29 修复 a74 回归（commit 16110044）：a74 让 intraday_snapshot/export_notifications 生成 notifications.json/.gz，
# deploy.sh 原只恢复 intraday_snapshot 致 rebase 时 untracked notifications.json.gz checkout 冲突，futures+etf deploy 连续2天失败。
echo "-> 恢复 intraday_snapshot.json/.gz + notifications.json/.gz 到 origin/main 版（防工作区残留带入通配 add）..." | tee -a "$LOG"
git -C "$GIT_REPO" fetch origin main 2>&1 | tee -a "$LOG" || true
git -C "$GIT_REPO" checkout origin/main -- static-site/data/intraday_snapshot.json static-site/data/intraday_snapshot.json.gz static-site/data/notifications.json static-site/data/notifications.json.gz 2>/dev/null && \
  git -C "$GIT_REPO" reset HEAD -- static-site/data/intraday_snapshot.json static-site/data/intraday_snapshot.json.gz static-site/data/notifications.json static-site/data/notifications.json.gz 2>/dev/null || true

# 0.7 兜底：清理工作区残留 unmerged 状态（2026-07-31 根治，方案B 双保险）
# 根因：pop_rebase_stash bug（rebase 后 stash pop 冲突只 echo 不解决）曾留 unmerged 污染，
# 2026-07-31 05:00 us_stock_morning deploy.sh git commit 撞 unmerged exit 128 致 main 没推
# （730 信号 R2 已上线但 CF Workers ss.fx8.store / GH Pages sss.sugas.site 没拿到 730）。
# 此兜底在 fetch 后 export 前检测：static-site/data/* 的 unmerged 强制 reset HEAD + checkout origin/main 清理；
# 非数据文件 unmerged 则 exit 1 报警不继续（避免吞代码冲突）。
UNMERGED=$(git -C "$GIT_REPO" diff --name-only --diff-filter=U 2>/dev/null)
if [ -n "$UNMERGED" ]; then
  NON_DATA_UNMERGED=""
  for _u in $UNMERGED; do
    case "$_u" in
      static-site/data/*.json|static-site/data/*.gz)
        git -C "$GIT_REPO" reset HEAD -- "$_u" 2>/dev/null || true
        git -C "$GIT_REPO" checkout origin/main -- "$_u" 2>&1 | tee -a "$LOG"
        echo "⚠ 清理 unmerged 数据文件: $_u（已 reset HEAD + checkout origin/main）" | tee -a "$LOG"
        ;;
      *)
        NON_DATA_UNMERGED="$NON_DATA_UNMERGED $_u"
        ;;
    esac
  done
  if [ -n "$NON_DATA_UNMERGED" ]; then
    echo "✗ 工作区有非数据文件 unmerged: $NON_DATA_UNMERGED，拒绝 deploy（需手动解决代码冲突）" | tee -a "$LOG"
    exit 1
  fi
fi

# 0.8 刷新 etf_index_map.json + board_etf_map.json（P2-新-G ETF 联动 tag 数据源）。
# gen_etf_index_map.py：akshare fund_etf_spot_em() 名称匹配反推 track_index_code，生成
#   data/etf_index_map.json（build_board_etf_map.py 输入，2026-08-06 事故修复新增）。
# build_board_etf_map.py：行业/概念关键词匹配 + 14 宽基/红利/港股指数代码精确匹配。
# 根因修复（2026-08-06）：etf_index_map.json 从未成功生成（生成脚本不存在），_load_etf_index_map_reverse
#   读不到只 warning + exit 0 静默失败，致 board_etf_map.json 14 宽基全空，首页"全部无 ETF"。
#   现前置 gen_etf_index_map.py 刷新输入，build_board_etf_map.py 失败 exit 1 阻断 deploy
#   （不再"继续用旧 map"静默覆盖空数组），且内置 akshare 名称匹配兜底 + 14 宽基校验。
echo "-> 刷新 etf_index_map.json (gen 名称匹配反推 track_index_code) ..." | tee -a "$LOG"
"$PY" "$REPO/scripts/gen_etf_index_map.py" >> "$LOG" 2>&1 || {
  echo "⚠ gen_etf_index_map.py 失败(akshare 反爬/网络?)，build_board_etf_map.py 将走名称匹配兜底" | tee -a "$LOG"
}
echo "-> 刷新 board_etf_map.json (ETF 联动 tag 数据源) ..." | tee -a "$LOG"
"$PY" "$REPO/scripts/build_board_etf_map.py" >> "$LOG" 2>&1
BUILD_RC=$?
if [ "$BUILD_RC" -ne 0 ]; then
  echo "✗ build_board_etf_map.py 失败(退出码 $BUILD_RC，14 宽基校验未过/akshare 兜底也失败)，终止 deploy（防静默覆盖空 map）" | tee -a "$LOG"
  exit "$BUILD_RC"
fi

# 1. 导出 JSON
echo "→ 运行 export.py 生成静态 JSON ..." | tee -a "$LOG"
"$PY" "$EXPORT" 2>&1 | tee -a "$LOG"
EXPORT_RC=${PIPESTATUS[0]}
if [ "$EXPORT_RC" -ne 0 ]; then
  echo "✗ export.py 失败(退出码 $EXPORT_RC)，终止部署" | tee -a "$LOG"
  exit "$EXPORT_RC"
fi
echo "✓ export.py 完成" | tee -a "$LOG"

# 1.1 数据产物校验（4 类事故拦截：board_etf_map 全空 / boot.date 不一致 /
# amount_forecast 爆炸 / 关键文件丢失）。--deploy-mode 仅 fail 阻断（exit 1），
# warn 不阻断（exit 0），避免预存在 warn（etf_index_map 缺失等）阻塞所有 deploy。
# 2026-08-06 加：拦 "成交额卡显示昨日值"(boot 嵌旧 overview) / "9.52万亿爆炸" / "ETF 全空" 等事故。
echo "-> 运行 check_data_integrity.py 数据产物校验 ..." | tee -a "$LOG"
"$PY" "$REPO/scripts/check_data_integrity.py" --deploy-mode --data-dir "$REPO/static-site/data" 2>&1 | tee -a "$LOG"
CHECK_RC=${PIPESTATUS[0]}
if [ "$CHECK_RC" -ne 0 ]; then
  echo "✗ 数据产物校验失败(退出码 $CHECK_RC)，终止部署（4 类事故拦截）" | tee -a "$LOG"
  exit "$CHECK_RC"
fi
echo "✓ 数据产物校验通过" | tee -a "$LOG"

# 1.3 intraday_snapshot.json global_realtime 防覆盖（2026-07-31 德法角标三重根因修复）
# 根因：export.py 调 load_latest_snapshot 从 DB reload 生成 intraday_snapshot.json，
# 若 DB 镜像滞后（trade/data/sentiment.db 未同步 trade-data 主库）或旧 snapshot 行
# 无 global_realtime，reload 丢失 global_realtime 致前端德法角标无实时数据。
# 修复1已让 _save_db/load_latest_snapshot 补 global_realtime，此处加兜底：
# export.py 后检查 intraday_snapshot.json 是否含 global_realtime，缺失则从 origin/main
# 版本（intraday_snapshot.sh 推的实时版）提取 global_realtime 注入，防 deploy 覆盖丢失。
echo "-> 检查 intraday_snapshot.json global_realtime 防覆盖 ..." | tee -a "$LOG"
"$PY" - "$GIT_REPO" "$LOG" <<'PYEOF' 2>&1 | tee -a "$LOG" || true
import json, sys, subprocess, tempfile, os
repo, log = sys.argv[1], sys.argv[2]
path = os.path.join(repo, "static-site/data/intraday_snapshot.json")
try:
    with open(path, encoding="utf-8") as f:
        snap = json.load(f)
except Exception as e:
    print(f"  ⚠ 读取 intraday_snapshot.json 失败: {e}，跳过 global_realtime 检查")
    sys.exit(0)
if snap.get("global_realtime"):
    n = len(snap["global_realtime"])
    print(f"  ✓ intraday_snapshot.json 已含 global_realtime ({n} 个指数)，无需补")
    sys.exit(0)
# 缺失 global_realtime -> 从 origin/main 版提取
print("  ⚠ intraday_snapshot.json 缺 global_realtime，尝试从 origin/main 版提取注入...", flush=True)
try:
    content = subprocess.run(
        ["git", "-C", repo, "show", "origin/main:static-site/data/intraday_snapshot.json"],
        capture_output=True, text=True, timeout=30
    ).stdout
    origin_snap = json.loads(content)
except Exception as e:
    print(f"  ⚠ 无法从 origin/main 提取 intraday_snapshot.json: {e}，跳过（不阻断）")
    sys.exit(0)
gr = origin_snap.get("global_realtime")
if not gr:
    print("  ⚠ origin/main 版也无 global_realtime，跳过（intraday_snapshot.sh 下次推送时补）")
    sys.exit(0)
# 注入 global_realtime 到当前 snap 并写回
snap["global_realtime"] = gr
with open(path, "w", encoding="utf-8") as f:
    json.dump(snap, f, ensure_ascii=False, separators=(",", ":"))
# 同步 .gz
import gzip
gz_path = path + ".gz"
with gzip.open(gz_path, "wt", encoding="utf-8") as f:
    json.dump(snap, f, ensure_ascii=False, separators=(",", ":"))
print(f"  ✓ 已从 origin/main 提取 global_realtime ({len(gr)} 个指数) 注入 intraday_snapshot.json + .gz")
PYEOF

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
run_r2_upload "upload-public-fund" upload-public-fund || echo "⚠ upload-public-fund 失败/超时,继续部署" | tee -a "$LOG"
run_r2_upload "upload-etf-score" upload-etf-score || echo "⚠ upload-etf-score 失败/超时,继续部署" | tee -a "$LOG"
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
# industry: 仅 meta 留 git（3m/6m/1y 单文件 + all/5y/3y 单文件 + all/5y/3y-concepts 已 R2 托管，.gitignore 移出减 ~24M）
# 2026-07-25 补 industry-{all,5y,3y}.json 单文件漏移（5y/all 已 untracked，3y 仍 tracked 致 7/24
# 20:07 etf deploy rebase 撞 unstaged M 失败，stash 56770911 兜底但根因未除，现 git rm --cached 根治）
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
# public_fund 7 个 JSON（export.py L410-441 生成，collector public_fund.py export_json_files 也生成同款；
# collector 采集后 deploy.sh public-fund 推送上线。仿 etf_national_team 模式，7 类各 .json + .gz）
# 2026-07-20 补 industry_fund_map(原漏)+ manuf_subind_fund_map(方案C Step5 新增子行业下钻到基金)
# 2026-07-24 补 position_backtest(G功能 88 魔咒历史回测+极值标注, 独立计算非 7 元组)
# 2026-07-20 补 holding_concentration_ts(N功能抱团集中度历史时序10期, 独立计算非 7 元组)
# 2026-08-02 补 scale_change_ts(N功能全量规模变动时序113期, summary.scale_change_history 只20期不够)
# 2026-08-02 补 industry_rotation_ts(F功能行业轮动时序50期27行业, 独立计算非 7 元组)
# 2026-08-02 补 position_estimate(方案A 今日预估仓位+历史时序, 净值回归反推+lg校准, 88魔咒图"今日预估"点)
# 2026-08-02 补 sw_industry_alloc(申万一级反查口径行业配置, 前端"行业配置"卡第四档 'sw' 切换, 独立计算非 7 元组)
for _pf in summary holdings industry top20 asset_alloc industry_fund_map manuf_subind_fund_map position_backtest holding_concentration_ts scale_change_ts industry_rotation_ts position_estimate sw_industry_alloc; do
  DATA_FILES+=("static-site/data/public_fund_${_pf}.json" "static-site/data/public_fund_${_pf}.json.gz")
done
# 单文件（export.py 生成 + deploy/update_all/update_lab 生成）
# trade_sim_indices: export.py 生成单文件(非 R2 托管的 trade_sim/ 目录), 需入 git 否则 .gz 404
# futures_acc_trend: 期货同向准确度每日趋势(方案A, export_futures_acc_trend 生成,
#   读 futures_ih_detail_acc 表 1851 行 ~370KB, 单文件无 -all/-5y/-3y 拆分, 走 CF 不走 R2)
# futures_acc_conclusion: 期货同向准确度规律结论(4条规律+当前触发状态, export_futures_acc_conclusion 生成,
#   每日刷新幂等覆盖, 单文件~2KB 走 CF 不走 R2)
# P0-2 (2026-08-05): etf_score_list 拆 3 JSON (buy/sell/hold), .json 走 R2(.gitignore),
#   .gz 留 git(CF 兜底/备份); 原 etf_score_list 单文件已废弃
for _f in boot overview futures futures_acc_trend futures_acc_conclusion ad_line volume_ratio position \
          summary summary_history signal_freq signal_stats \
          rotation new_high_low ma_alignment intraday_snapshot \
          alert etf_score_list_buy etf_score_list_sell etf_score_list_hold trade_sim_indices \
          lab_ablation lab_cost_compare lab_param_scan lab_short_symmetry; do
  DATA_FILES+=("static-site/data/${_f}.json" "static-site/data/${_f}.json.gz")
done
# feed.xml（gen_rss.py 生成，非 .json）+ min JS/CSS（build_min.py 生成的全部 6 个 min 文件，
# 2026-07-20 修复：原仅 add app.min.js/lab.min.js，漏 style.min.css/common.min.js/purpose-notes.min.js/lab.min.css，
# 致改 CSS 后 style.min.css 不上线；9b98425c 手动补的根因根治）
DATA_FILES+=("static-site/data/feed.xml" \
  "static-site/app.min.js" "static-site/lab.min.js" \
  "static-site/common.min.js" "static-site/purpose-notes.min.js" \
  "static-site/style.min.css" "static-site/lab.min.css")
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
    # 全仓库 stash tracked M + untracked（--include-untracked 不加 pathspec），覆盖根目录 tracked M
    # 文件（如 08-买卖点策略深度回测.md/signal_stats.json/TASKS.md）+ static-site/data/ 下所有变更。
    # 根 data/ 的 DB（sentiment.db/etf_national_team.db 已 gitignore）不会被 stash。
    # 2026-07-29 修复（etf 21:30 兜底 deploy 失败根因）：原 stash 不加 -u，untracked 文件留工作区，
    # rebase origin/main checkout 撞 origin/main 有 tracked 但工作区 untracked 的同名文件（如
    # notifications.json.gz：deploy.sh 精确 git add DATA_FILES 列表不含它致 feat commit 里 untracked，
    # 但 intraday-snapshot 全量 add push 到 origin/main 成 tracked）-> "untracked working tree files
    # would be overwritten by checkout" -> rebase abort -> push 永久失败。加 -u 根治：rebase 前把
    # 全仓库 untracked + tracked M 全 stash 走，工作区干净，rebase 不撞 untracked。
    # 2026-07-30 修复：原 stash 加 pathspec `-- static-site/data/` 限目录，漏根目录 tracked M 文件，
    # rebase 报 "cannot rebase: you have unstaged changes" 退出，自动 rebase 没触发，push non-fast-forward
    # 失败。去 pathspec 后 stash 全仓库 tracked M + untracked，rebase 能正常进行。
    STASH_CNT_BEFORE=$(git -C "$GIT_REPO" stash list 2>/dev/null | wc -l | tr -d ' ')
    git -C "$GIT_REPO" stash push --include-untracked -m "deploy.sh-rebase-$(date +%Y%m%d_%H%M%S)" 2>&1 | tee -a "$LOG" || true
    STASH_CNT_AFTER=$(git -C "$GIT_REPO" stash list 2>/dev/null | wc -l | tr -d ' ')
    REBASE_STASHED=0
    if [ "$STASH_CNT_AFTER" -gt "$STASH_CNT_BEFORE" ]; then
      REBASE_STASHED=1
      echo "✓ rebase 前已 stash 全仓库 tracked M + untracked 文件（stash@{0}）" | tee -a "$LOG"
    else
      echo "  工作区无 tracked M/untracked 文件需 stash（或 stash 无变化跳过）" | tee -a "$LOG"
    fi
    # rebase 后恢复 stash 的 helper
    # 2026-07-31 根治：原版 pop 失败只 echo 不解决，留 unmerged 状态污染下次 deploy，
    # 05:00 us_stock_morning deploy.sh git commit 撞 unmerged exit 128 致 main 没推(730 信号 R2 已上线但 CF/GH 主站没拿到)。
    # 数据文件(schedule_stats.json 有独立 push_schedule_stats.sh 兜底、其他 export.py 重新生成)冲突自动解决：
    # 取 theirs(stash 内容=rebase 前工作区版本，数据文件会被下次任务脚本重新生成覆盖)+ add + drop；
    # 非数据文件冲突(如非 static-site/data/ 的代码文件)保留 stash 待手动不自动解决(避免吞代码改动)。
    pop_rebase_stash() {
      if [ "$REBASE_STASHED" = "1" ]; then
        local pop_out pop_rc
        pop_out=$(git -C "$GIT_REPO" stash pop 2>&1)
        pop_rc=$?
        echo "$pop_out" | tee -a "$LOG"
        if [ "$pop_rc" -ne 0 ]; then
          local conflicted non_data f
          conflicted=$(git -C "$GIT_REPO" diff --name-only --diff-filter=U 2>/dev/null)
          if [ -n "$conflicted" ]; then
            non_data=""
            for f in $conflicted; do
              case "$f" in
                static-site/data/*.json|static-site/data/*.gz)
                  git -C "$GIT_REPO" checkout --theirs -- "$f" 2>&1 | tee -a "$LOG"
                  git -C "$GIT_REPO" add -- "$f" 2>&1 | tee -a "$LOG"
                  ;;
                *)
                  non_data="$non_data $f"
                  ;;
              esac
            done
            if [ -z "$non_data" ]; then
              # 全是数据文件冲突，已解决；pop 冲突时 stash 仍保留，手动 drop
              git -C "$GIT_REPO" stash drop 2>&1 | tee -a "$LOG"
              echo "✓ stash pop 数据文件冲突已自动解决(--theirs)，stash 已 drop" | tee -a "$LOG"
            else
              # 有非数据文件冲突，保留 stash 待手动 git stash pop
              echo "⚠ stash pop 有非数据文件冲突($non_data)，保留 stash@{0} 待手动 git stash pop" | tee -a "$LOG"
            fi
          else
            echo "⚠ stash pop 失败(无冲突文件信息)，保留 stash@{0} 待手动处理" | tee -a "$LOG"
          fi
        fi
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
      # 2026-07-29 修复：rebase 失败时自动解决 static-site/data/ 数据文件冲突
      # 根因：并发 deploy push 后本地 rebase origin/main 撞 static-site/data/*.gz
      # 二进制冲突(git 无法三方合并) -> rebase abort -> push 永久失败 ->
      # futures_backfill log_anomaly 持续告警(7-28 21:00 事故)。
      # 数据文件每次 export 全量覆盖不需合并，取 theirs(本地最新)。
      # rebase 语义：ours=origin/main(基底) theirs=本地commit(重放)=最新数据
      CONFLICTED=$(git -C "$GIT_REPO" diff --name-only --diff-filter=U 2>/dev/null)
      if [ -n "$CONFLICTED" ]; then
        NON_DATA_CONFLICTS=""
        for f in $CONFLICTED; do
          case "$f" in
            static-site/data/*.json|static-site/data/*.gz)
              git -C "$GIT_REPO" checkout --theirs -- "$f" 2>&1 | tee -a "$LOG"
              git -C "$GIT_REPO" add -- "$f" 2>&1 | tee -a "$LOG"
              ;;
            *)
              NON_DATA_CONFLICTS="$NON_DATA_CONFLICTS $f"
              ;;
          esac
        done
        if [ -z "$NON_DATA_CONFLICTS" ]; then
          # 全是数据文件冲突，已用 theirs(本地最新) 解决，进入循环处理后续连续冲突
          # 根因(2026-08-05)：feat 长期跑定时任务积累 data commit，origin/main 有
          # intraday/futures data commit，rebase 多个连续 .gz 冲突，单次 --continue
          # 后下个 commit 又冲突 -> 直接 abort -> deploy 永久失败。
          # 修复：while 循环 checkout --theirs + git add + rebase --continue，直到
          # rebase 完成或遇非数据冲突(代码文件)才 abort，最大 10 次防死循环。
          echo "-> rebase 数据文件冲突已自动解决(--theirs=本地最新 export)，continue..." | tee -a "$LOG"
          REBASE_DONE=0
          ATTEMPT=0
          MAX_ATTEMPTS=10
          while [ "$ATTEMPT" -lt "$MAX_ATTEMPTS" ]; do
            ATTEMPT=$((ATTEMPT + 1))
            GIT_EDITOR=true git -C "$GIT_REPO" rebase --continue 2>&1 | tee -a "$LOG"
            CONTINUE_RC=${PIPESTATUS[0]:-1}
            if [ "$CONTINUE_RC" -eq 0 ]; then
              REBASE_DONE=1
              break
            fi
            # rebase --continue 失败：检查是否又是纯数据文件冲突
            CONFLICTED2=$(git -C "$GIT_REPO" diff --name-only --diff-filter=U 2>/dev/null)
            if [ -z "$CONFLICTED2" ]; then
              # 非冲突类失败(可能是编辑器/其他错误)，保守 abort 等人工处理
              git -C "$GIT_REPO" rebase --abort 2>/dev/null || true
              pop_rebase_stash
              echo "✗ rebase --continue 失败(无冲突文件信息，退出码 $CONTINUE_RC)，已 abort" | tee -a "$LOG"
              echo "  请手动：git -C $GIT_REPO rebase origin/main，解决冲突后重跑 deploy.sh" | tee -a "$LOG"
              exit 1
            fi
            NON_DATA2=""
            for f in $CONFLICTED2; do
              case "$f" in
                static-site/data/*.json|static-site/data/*.gz)
                  git -C "$GIT_REPO" checkout --theirs -- "$f" 2>&1 | tee -a "$LOG"
                  git -C "$GIT_REPO" add -- "$f" 2>&1 | tee -a "$LOG"
                  ;;
                *)
                  NON_DATA2="$NON_DATA2 $f"
                  ;;
              esac
            done
            if [ -n "$NON_DATA2" ]; then
              # 遇非数据冲突(代码文件冲突)，保守 abort 等人工处理
              git -C "$GIT_REPO" rebase --abort 2>/dev/null || true
              pop_rebase_stash
              echo "✗ rebase --continue 后遇非数据文件冲突($NON_DATA2)，已 abort" | tee -a "$LOG"
              echo "  请手动：git -C $GIT_REPO rebase origin/main，解决冲突后重跑 deploy.sh" | tee -a "$LOG"
              exit 1
            fi
            # 纯数据冲突已用 theirs 解决，循环继续 rebase --continue
            echo "-> 第 $ATTEMPT 次循环：数据冲突已解决(--theirs=本地最新)，继续 rebase..." | tee -a "$LOG"
          done
          if [ "$REBASE_DONE" -eq 1 ]; then
            git -C "$GIT_REPO" push origin HEAD:main 2>&1 | tee -a "$LOG"
            PUSH_RC=${PIPESTATUS[0]:-1}
            pop_rebase_stash
            if [ "$PUSH_RC" -eq 0 ]; then
              echo "✓ rebase(数据冲突 --theirs, 循环 $ATTEMPT 次) + 重试 push 成功" | tee -a "$LOG"
            else
              echo "✗ rebase --continue 后重试 push 仍失败(退出码 $PUSH_RC)" | tee -a "$LOG"
              exit "$PUSH_RC"
            fi
          else
            # 循环达上限仍失败，保守 abort
            git -C "$GIT_REPO" rebase --abort 2>/dev/null || true
            pop_rebase_stash
            echo "✗ rebase --continue 循环达上限($MAX_ATTEMPTS 次)仍失败，已 abort" | tee -a "$LOG"
            echo "  请手动：git -C $GIT_REPO rebase origin/main，解决冲突后重跑 deploy.sh" | tee -a "$LOG"
            exit 1
          fi
        else
          # 有非数据文件冲突，保守 abort
          git -C "$GIT_REPO" rebase --abort 2>/dev/null || true
          pop_rebase_stash   # abort 后恢复工作区 M 文件（已回到 rebase 前状态，pop 安全）
          echo "✗ rebase 有非数据文件冲突($NON_DATA_CONFLICTS)，已 abort 保持工作区干净。" | tee -a "$LOG"
          echo "  请手动：git -C $GIT_REPO fetch origin && git -C $GIT_REPO rebase origin/main，解决冲突后重跑 deploy.sh" | tee -a "$LOG"
          exit 1
        fi
      else
        # 无冲突文件信息(可能是其他 rebase 错误)，保守 abort
        git -C "$GIT_REPO" rebase --abort 2>/dev/null || true
        pop_rebase_stash   # abort 后恢复工作区 M 文件（已回到 rebase 前状态，pop 安全）
        echo "✗ rebase origin/main 失败(无冲突文件信息，退出码 $REBASE_RC)，已 abort 保持工作区干净。" | tee -a "$LOG"
        echo "  请手动：git -C $GIT_REPO fetch origin && git -C $GIT_REPO rebase origin/main，解决冲突后重跑 deploy.sh" | tee -a "$LOG"
        exit 1
      fi
    fi
  fi
fi

echo "✓ push 成功（MaoziYun 自动拉取 git main 部署，有拉取延迟 + max-age=1200 缓存；wrangler 未安装，worker/headers.js 待迁 CF Workers 后手动 wrangler deploy）" | tee -a "$LOG"
echo "=== deploy.sh 结束 $(date '+%Y-%m-%d %H:%M:%S') 退出码=0 ===" | tee -a "$LOG"
exit 0
