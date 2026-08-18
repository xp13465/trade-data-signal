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

# 加载 .env（PURGE_SECRET 等 Worker 凭证）到环境，确保手动跑 deploy.sh 时子进程
# （upload_r2.py / export.py）能读到 PURGE_SECRET 调 /api/purge-cache 清 edge cache。
# 根治 2026-08-09 手动部署丢失 PURGE_SECRET 致 edge cache 不清、前端读旧版 4h 事故。
# set -a 自动 export；.env 内变量（R2_*/PURGE_SECRET）launchd/环境未预设，source 不冲突。
set -a
[ -f "$GIT_REPO/.env" ] && . "$GIT_REPO/.env"
[ -f "$REPO/.env" ] && . "$REPO/.env"
set +a

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

# 0.5 fetch origin main（后续 unmerged 检查 + rebase 需要）
# R2 阶段4a 后 static-site/data/ 全量移出 git（含 feed.xml，2026-08-10 也走 R2），
# 原 checkout intraday_snapshot/notifications.json 防通配带入已无效（文件 gitignored），
# DATA_FILES 改精确列表（min JS/CSS）不再通配 add，无残留带入风险。
git -C "$GIT_REPO" fetch origin main 2>&1 | tee -a "$LOG" || true

# 0.7 兜底：清理工作区残留 unmerged 状态（2026-07-31 根治，方案B 双保险）
# 根因：pop_rebase_stash bug（rebase 后 stash pop 冲突只 echo 不解决）曾留 unmerged 污染，
# 2026-07-31 05:00 us_stock_morning deploy.sh git commit 撞 unmerged exit 128 致 main 没推
# （730 信号 R2 已上线但 CF Workers ss.fx8.store / GH Pages sss.sugas.site 没拿到 730）。
# 此兜底在 fetch 后 export 前检测：static-site/data/* 的 unmerged 强制 reset HEAD + checkout origin/main 清理；
# 非数据文件 unmerged 则 exit 1 报警不继续（避免吞代码冲突）。
# R2 阶段4a 后 static-site/data/ 全 gitignored（含 feed.xml 2026-08-10 走 R2），不可能 unmerged。
UNMERGED=$(git -C "$GIT_REPO" diff --name-only --diff-filter=U 2>/dev/null)
if [ -n "$UNMERGED" ]; then
  NON_DATA_UNMERGED=""
  for _u in $UNMERGED; do
    case "$_u" in
      static-site/data/*)
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

# 项6: build 成功后同步新版 board_etf_map.json 到 static-site/data/（前端 R2 上传源，2026-08-18）。
# 背景: build_board_etf_map.py 只写 data/board_etf_map.json（export_overview 读它），但前端 R2 的
#   board_etf_map.json 由 upload-all-data 从 static-site/data/board_etf_map.json 上传。此前 static-site/data/
#   停留旧版，deploy 上传旧版 → 前端读旧版与 overview（读 data/ 新版）不一致（§22 一致性破坏）。
# 此步 build 成功后复制新版到 static-site/data/，消除时序不同步窗口：export --incremental 强制全量重算
#   overview（读 data/ 新版），前端 R2 的 board_etf_map 也是新版，三处一致。
# cp 失败不阻断（export 仍用 data/ 新版，仅前端 R2 board_etf_map 可能旧版，warn 提示）。
# ⚠ 目标必须用 $REPO（trade-data，upload 源）而非 $GIT_REPO（trade）：launchd 自动 deploy 在 trade-data 跑，
#   upload_r2.py STATIC_DIR=trade-data/static-site 从 $REPO 上传；cp 到 $GIT_REPO（trade）会被下方
#   rsync "$REPO/static-site/data/" -> "$GIT_REPO/static-site/data/" 用 trade-data 侧 8/9 旧版反覆盖（7e19a5bb6 项6 错位）。
cp "$REPO/data/board_etf_map.json" "$REPO/static-site/data/board_etf_map.json" 2>>"$LOG" \
  && echo "✓ board_etf_map.json 已同步到 static-site/data/（build 后自动联动，前端 R2 与 overview 一致）" | tee -a "$LOG" \
  || echo "⚠ 同步 board_etf_map.json 到 static-site/data/ 失败（不阻断，export 仍用 data/ 新版）" | tee -a "$LOG"

# 1. 导出 JSON
# ab#39 增量导出（2026-08-17 批次A）：--incremental 让 export 只重算源数据已变化的 JSON，
# 其余复用现有文件（消除全量 353 JSON 重复重算）。安全：仅当依赖表 MAX(date) 与上次 export 相同才跳过，
# 且 overview/signal_*/summary/futures 等必更白名单强制全量（防 8/14 "带日期跳过=静默旧数据"）。
# 手动跑 export.py 不带 --incremental = 全量，行为不变。
echo "→ 运行 export.py --incremental 生成静态 JSON ..." | tee -a "$LOG"
"$PY" "$EXPORT" --incremental 2>&1 | tee -a "$LOG"
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

# 1.2 入样宇宙规则对称校验(CLAUDE.md §23.6, 2026-08-14 用户定)
# 入样宇宙规则(哪些信号进凯利回测/首页AI建议)必须①显式声明(config/universe_rules.yaml)
# ②强制公示 ③1:1遵从 ④对称校验 ⑤变更联动。本步做④对称校验: 自动比对 overview._bt_in_universe
# ⟺ board_etf_map 重算 + 候选信号类型⊆白名单 + 回测交易无排除类别 + yaml排除类别⟺map实际缺失。
# 任一断言 FAIL → 非0退出阻断上线(同 §22 数据一致性校验逻辑)。
# config/scripts 在 trade-data 是 symlink 指向 trade, 故用 $REPO 相对路径与 check_data_integrity 一致。
echo "-> 运行 check_universe_alignment.py 入样宇宙规则对称校验 ..." | tee -a "$LOG"
"$PY" "$REPO/scripts/check_universe_alignment.py" --repo "$REPO" --deploy-mode 2>&1 | tee -a "$LOG"
UNIV_RC=${PIPESTATUS[0]}
if [ "$UNIV_RC" -ne 0 ]; then
  echo "✗ 入样宇宙规则校验失败(退出码 $UNIV_RC)，终止部署(§23.6 对称校验 FAIL 阻断上线)" | tee -a "$LOG"
  exit "$UNIV_RC"
fi
echo "✓ 入样宇宙规则校验通过" | tee -a "$LOG"

# 1.3 版本一致性校验(CLAUDE.md §24⑤, 2026-08-15 补; #48)
# 适配 #46 日期+批次版本串机制: index引用版本串格式/与sw批次一致/资源存在/min比源新,
# 任一 FAIL → 非0退出阻断上线(防孤儿快照再产生, 2026-08-14 全站白屏事故根因⑤)。
echo "-> 运行 check_version_consistency.py 版本一致性校验 ..." | tee -a "$LOG"
GIT_REPO="$GIT_REPO" "$PY" "$REPO/scripts/check_version_consistency.py" --site-dir "$GIT_REPO/static-site" --deploy-mode 2>&1 | tee -a "$LOG"
VER_RC=${PIPESTATUS[0]}
if [ "$VER_RC" -ne 0 ]; then
  echo "✗ 版本一致性校验失败(退出码 $VER_RC)，终止部署(§24⑤ FAIL 阻断上线)" | tee -a "$LOG"
  exit "$VER_RC"
fi
echo "✓ 版本一致性校验通过" | tee -a "$LOG"

# 1.4 intraday_snapshot.json global_realtime 防覆盖检查（2026-07-31 德法角标三重根因修复）
# 根因：export.py 调 load_latest_snapshot 从 DB reload 生成 intraday_snapshot.json，
# 若 DB 镜像滞后或旧 snapshot 行无 global_realtime，reload 丢失 global_realtime 致前端德法角标无实时数据。
# 修复1已让 _save_db/load_latest_snapshot 补 global_realtime，此处加检查：
# export.py 后检查 intraday_snapshot.json 是否含 global_realtime，缺失则告警（R2 阶段4a 后
# origin/main 不再 tracked intraday_snapshot.json，原 git show 注入 fallback 已失效，仅告警）。
echo "-> 检查 intraday_snapshot.json global_realtime 防覆盖 ..." | tee -a "$LOG"
"$PY" - "$GIT_REPO" "$LOG" <<'PYEOF' 2>&1 | tee -a "$LOG" || true
import json, sys, os
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
# 缺失 global_realtime -> 告警（R2 阶段4a 后 origin/main 不再 tracked，无法从 git 恢复）
print("  ⚠ intraday_snapshot.json 缺 global_realtime（export.py reload 丢失？），下次 intraday_snapshot.sh 运行时自动补")
sys.exit(0)
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
# B1(2026-08-18): 传 GIT_REPO 让 build_min 从 git HEAD 读源生成 min（根治脏工作区覆盖），
# trade-data 跑时 BASE 非 git 仓库，必须靠环境变量定位 trade git 仓库。
GIT_REPO="$GIT_REPO" "$PY" "$REPO/scripts/build_min.py" 2>&1 | tee -a "$LOG"
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

echo "-> 上传 lab/trade_sim/index/industry/public_fund/offshore_fund/etf_score/data-large/all-data 到 R2 ..." | tee -a "$LOG"
# 阶段3：数据唯一走 R2，上传失败需 notify 告警让 schedule_monitor 发现
R2_FAIL=""
run_r2_upload "upload-lab" upload-lab || { echo "⚠ upload-lab 失败/超时,继续部署" | tee -a "$LOG"; R2_FAIL="$R2_FAIL upload-lab"; }
run_r2_upload "upload-trade-sim" upload-trade-sim || { echo "⚠ upload-trade-sim 失败/超时,继续部署" | tee -a "$LOG"; R2_FAIL="$R2_FAIL upload-trade-sim"; }
run_r2_upload "upload-trade-sim-json" upload-trade-sim-json || { echo "⚠ upload-trade-sim-json 失败/超时,继续部署" | tee -a "$LOG"; R2_FAIL="$R2_FAIL upload-trade-sim-json"; }
run_r2_upload "upload-index" upload-index || { echo "⚠ upload-index 失败/超时,继续部署" | tee -a "$LOG"; R2_FAIL="$R2_FAIL upload-index"; }
run_r2_upload "upload-industry" upload-industry || { echo "⚠ upload-industry 失败/超时,继续部署" | tee -a "$LOG"; R2_FAIL="$R2_FAIL upload-industry"; }
run_r2_upload "upload-public-fund" upload-public-fund || { echo "⚠ upload-public-fund 失败/超时,继续部署" | tee -a "$LOG"; R2_FAIL="$R2_FAIL upload-public-fund"; }
run_r2_upload "upload-offshore-fund" upload-offshore-fund || { echo "⚠ upload-offshore-fund 失败/超时,继续部署" | tee -a "$LOG"; R2_FAIL="$R2_FAIL upload-offshore-fund"; }
run_r2_upload "upload-etf-score" upload-etf-score || { echo "⚠ upload-etf-score 失败/超时,继续部署" | tee -a "$LOG"; R2_FAIL="$R2_FAIL upload-etf-score"; }
run_r2_upload "upload-data-large" upload-data-large || { echo "⚠ upload-data-large 失败/超时,继续部署" | tee -a "$LOG"; R2_FAIL="$R2_FAIL upload-data-large"; }
run_r2_upload "upload-all-data" upload-all-data || { echo "⚠ upload-all-data 失败/超时,继续部署" | tee -a "$LOG"; R2_FAIL="$R2_FAIL upload-all-data"; }
# feed.xml 走 R2（2026-08-10）：gen_rss 生成的 RSS 上传到 R2 data/feed.xml，不再 git push
run_r2_upload "upload-feed" upload-data-files feed.xml || { echo "⚠ upload feed.xml 失败/超时,继续部署" | tee -a "$LOG"; R2_FAIL="$R2_FAIL upload-feed"; }
if [ -n "$R2_FAIL" ]; then
  "$PY" "$REPO/scripts/notify.py" "[告警] deploy R2上传失败" "deploy.sh R2 上传失败:$R2_FAIL<br>前端可能读旧数据，需手动补刷: bash scripts/upload_r2.py upload-all-data<br>日志: $LOG" --severe --from-prefix "[告警]" --dedup-key deploy_r2_upload_fail --dedup-window 1800 2>&1 | tee -a "$LOG" || true
fi

# 1.9 末尾统一 purge 低频文件（决策清单项5+项8，2026-08-18）
# 低频文件(LOW_FREQ 3600s 档) CF 会把 max-age 拉长成 4h edge 残留，上传时 purge 若失败/漏跑
# 前端读最长 4h 旧版。此步 deploy 末尾统一 purge 低频档文件消除残留窗口（项5）。
# purge 失败告警：upload_r2.py purge_cache 内部已对「部分批失败/无 PURGE_SECRET」notify 告警（项8）；
# 命令自身失败/超时（如 HTTP 连接异常）由 run_r2_upload 失败分支在此 notify 兜底。
run_r2_upload "purge-low-freq" purge-low-freq || {
  echo "⚠ purge-low-freq 失败/超时, 低频文件 edge cache 可能残留 4h 旧版" | tee -a "$LOG"
  "$PY" "$REPO/scripts/notify.py" "[告警] deploy 末尾 purge 低频文件失败" \
    "deploy.sh 末尾统一 purge 低频文件失败(purge-low-freq 命令失败/超时)，CF edge cache 低频文件可能残留最长 4h 旧版。<br>建议手动重试: bash scripts/upload_r2.py purge-low-freq<br>日志: $LOG" \
    --severe --from-prefix "[告警]" --dedup-key deploy_purge_low_freq_fail --dedup-window 1800 2>&1 | tee -a "$LOG" || true
}

# 2. git add min JS/CSS（阶段3：数据走 R2，只 push 代码）
# 原数据 JSON 已由上面 R2 上传（upload-all-data 等）推到 R2，不再 git push。
# feed.xml 也走 R2（2026-08-10）：gen_rss 生成后 upload-data-files 上传 R2，不再 git push。
# 保留 push：min JS/CSS（代码，build_min.py 生成）。
echo "-> git add min JS/CSS（阶段3：数据走 R2，只 push 代码）..." | tee -a "$LOG"
DATA_FILES=()
# min JS/CSS（build_min.py 生成的全部 6 个 min 文件）
DATA_FILES+=( \
  "static-site/app.min.js" "static-site/lab.min.js" \
  "static-site/common.min.js" "static-site/purpose-notes.min.js" \
  "static-site/style.min.css" "static-site/lab.min.css")
# 精确文件列表 git add（部分文件不存在时 git 报 fatal 但继续，不影响其余 add；deploy 无 set -e 不阻塞）
git -C "$GIT_REPO" add "${DATA_FILES[@]}" 2>&1 | tee -a "$LOG" || true

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
# 5.0 B3(2026-08-18): push 前强制校验分支 == main，非 main 拒绝并告警退出。
#     根治 091f26e5b 事件: deploy 在非 main 分支跑时 push HEAD:main 会把 fix/feat commit 带上 main。
#     双保险: ①分支校验(非 main 拒绝) ②push 用显式 main:main(即使误在非 main 跑也不把当前分支带上去)。
CUR_BRANCH=$(git -C "$GIT_REPO" rev-parse --abbrev-ref HEAD)
if [ "$CUR_BRANCH" != "main" ]; then
  echo "✗ deploy 必须在 main 分支跑（当前分支: $CUR_BRANCH）" | tee -a "$LOG"
  echo "  请先切回 main 再跑 deploy，避免把 $CUR_BRANCH 分支 commit 带上 main" | tee -a "$LOG"
  exit 1
fi
echo "→ git push（分支校验通过: main）..." | tee -a "$LOG"
git -C "$GIT_REPO" push origin main:main 2>&1 | tee -a "$LOG"
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
    # notifications.json：deploy.sh 精确 git add DATA_FILES 列表不含它致 feat commit 里 untracked，
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
                static-site/data/*)
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
      git -C "$GIT_REPO" push origin main:main 2>&1 | tee -a "$LOG"
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
      # 根因：并发 deploy push 后本地 rebase origin/main 撞 static-site/data/*.json
      # 数据文件冲突(git 无法三方合并) -> rebase abort -> push 永久失败 ->
      # futures_backfill log_anomaly 持续告警(7-28 21:00 事故)。
      # 数据文件每次 export 全量覆盖不需合并，取 theirs(本地最新)。
      # rebase 语义：ours=origin/main(基底) theirs=本地commit(重放)=最新数据
      CONFLICTED=$(git -C "$GIT_REPO" diff --name-only --diff-filter=U 2>/dev/null)
      if [ -n "$CONFLICTED" ]; then
        NON_DATA_CONFLICTS=""
        for f in $CONFLICTED; do
          case "$f" in
            static-site/data/*)
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
          # intraday/futures data commit，rebase 多个连续 .json 冲突，单次 --continue
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
                static-site/data/*)
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
            git -C "$GIT_REPO" push origin main:main 2>&1 | tee -a "$LOG"
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

# === staticdata 备份（best-effort，失败不阻塞 deploy）===
# 灾备第2层：每次 deploy 后 commit+push 差异化日志到 staticdata git 仓库
# 备份内容：DB原件(本地) + 配置(脱敏) + 小JSON(差异跟踪)
# DB 因>100MB 不进 git（git-lfs 未装），仅 rsync 到本地 staticdata/db/ 作备份
# 灾备第3层（R2 私有桶 gz 快照）是 DB 的云端备份
STATICDATA_REPO="${STATICDATA_REPO:-/Users/linhuichen/code/trade-data-signal-staticdata}"
if [ -d "$STATICDATA_REPO/.git" ]; then
  echo "-> staticdata 备份（best-effort）..." | tee -a "$LOG"
  STATICDATA_FAIL=0

  # 1. rsync DB原件到 staticdata/db/（本地备份，不进 git，.gitignore 排除 db/*.db）
  rsync -a "$REPO/data/"*.db "$STATICDATA_REPO/db/" 2>&1 | tee -a "$LOG" || {
    echo "⚠ staticdata DB rsync 失败,不阻塞 deploy" | tee -a "$LOG"
    STATICDATA_FAIL=1
  }

  # 2. rsync 配置（wrangler.jsonc + launchd plist 模板脱敏）
  cp "$GIT_REPO/wrangler.jsonc" "$STATICDATA_REPO/config/wrangler.jsonc" 2>/dev/null || true
  for _plist in ~/Library/LaunchAgents/com.trade.*.plist; do
    [ -f "$_plist" ] && sed 's|/Users/linhuichen|/Users/USER|g' "$_plist" > "$STATICDATA_REPO/config/launchd/$(basename "$_plist")" 2>/dev/null || true
  done

  # 3. rsync 全量 JSON 到 staticdata（全量备份，DB 不在此目录）
  rsync -a \
    "$REPO/static-site/data/" "$STATICDATA_REPO/data/" 2>&1 | tee -a "$LOG" || {
    echo "⚠ staticdata JSON rsync 失败,不阻塞 deploy" | tee -a "$LOG"
    STATICDATA_FAIL=1
  }

  # 4. git commit + push（差异化日志，best-effort）
  git -C "$STATICDATA_REPO" add -A 2>&1 | tee -a "$LOG" || true
  if git -C "$STATICDATA_REPO" diff --cached --quiet 2>/dev/null; then
    echo "✓ staticdata 无新变更,跳过 commit" | tee -a "$LOG"
  else
    # commit message 详细化：标题含触发 pipeline 名($NAME) + 变更文件数；body 按顶层目录分类计数 top5
    _CHANGED=$(git -C "$STATICDATA_REPO" diff --cached --name-only)
    _N=$(printf '%s\n' "$_CHANGED" | grep -c .)
    _BODY=$(printf '%s\n' "$_CHANGED" | sed 's|/.*||' | sort | uniq -c | sort -rn | head -5 | awk '{printf "%s %s\n", $2, $1}')
    git -C "$STATICDATA_REPO" commit -m "data backup [$NAME] $(date +%Y-%m-%d_%H:%M) - ${_N} files" -m "$_BODY" 2>&1 | tee -a "$LOG" || true
    git -C "$STATICDATA_REPO" push origin main 2>&1 | tee -a "$LOG" || {
      echo "⚠ staticdata push 失败,不阻塞 deploy" | tee -a "$LOG"
      STATICDATA_FAIL=1
    }
  fi

  if [ "$STATICDATA_FAIL" = "1" ]; then
    "$PY" "$REPO/scripts/notify.py" "[告警] staticdata备份失败" "deploy.sh staticdata备份部分失败,不阻塞deploy<br>日志: $LOG" --severe --from-prefix "[告警]" --dedup-key staticdata_backup_fail --dedup-window 1800 2>&1 | tee -a "$LOG" || true
  else
    echo "✓ staticdata 备份完成" | tee -a "$LOG"
  fi
else
  echo "⚠ staticdata 仓库不存在($STATICDATA_REPO),跳过备份" | tee -a "$LOG"
fi

# === feishu listener 重启（P2 关键，2026-08-11 稳定性修复）===
# 代码 commit 后 listener 跑旧代码直到手动重启（曾 6966c4501 commit/23:09 才重启）。
# 方案：feishu 相关脚本（listener/补拉/notify）mtime 比上次重启标记新 → 自动 kickstart 重启
# 长连接进程（启动时自带 missed_fetch 补拉重启窗口漏收，不丢消息）。只对代码变更重启，
# 避免每次数据 deploy 都重启长连接（§14 生产稳定性：不必要重启最小化）。
_FEISHU_LISTENER_LABEL="com.trade.feishu-listener"
_FEISHU_RESTART_MARKER="${TMPDIR:-/tmp}/feishu_listener_restarted"
_FEISHU_SCRIPTS=(
  "$GIT_REPO/scripts/feishu_ws_listener.py"
  "$GIT_REPO/scripts/feishu_missed_fetch.py"
  "$GIT_REPO/scripts/notify.py"
)
_FEISHU_NEED_RESTART=0
for _f in "${_FEISHU_SCRIPTS[@]}"; do
  if [ -f "$_f" ] && { [ ! -f "$_FEISHU_RESTART_MARKER" ] || [ "$_f" -nt "$_FEISHU_RESTART_MARKER" ]; }; then
    _FEISHU_NEED_RESTART=1
  fi
done
if [ "$_FEISHU_NEED_RESTART" = "1" ]; then
  if launchctl list 2>/dev/null | grep -q "$_FEISHU_LISTENER_LABEL"; then
    echo "→ feishu listener 代码有变更，重启 listener（启动自动补拉漏收，不丢消息）..." | tee -a "$LOG"
    launchctl kickstart -k "gui/$(id -u)/$_FEISHU_LISTENER_LABEL" 2>&1 | tee -a "$LOG" || {
      echo "⚠ feishu listener 重启失败（不阻塞 deploy，注意手动重启）" | tee -a "$LOG"
    }
    touch "$_FEISHU_RESTART_MARKER"
  else
    echo "→ feishu listener 未运行（launchd 未加载？），跳过重启（KeepAlive 会拉起）" | tee -a "$LOG"
    touch "$_FEISHU_RESTART_MARKER"
  fi
else
  echo "→ feishu listener 无代码变更，跳过重启" | tee -a "$LOG"
fi

echo "=== deploy.sh 结束 $(date '+%Y-%m-%d %H:%M:%S') 退出码=0 ===" | tee -a "$LOG"
exit 0
