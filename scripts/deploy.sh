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
export REPO GIT_REPO   # #75 显式导出,确保 upload_r2.py 子进程继承 REPO(防缺省回退读 trade 旧库)
PY="$REPO/.venv/bin/python"
# NODE_BIN: node 二进制探测(1.2.3 段 check_overfit_recent_parity.mjs 用)。
# launchd 环境无 nvm PATH, 交互 shell 走 command -v, launchd 回退扫 ~/.nvm 版本目录取最新。
NODE_BIN="$(command -v node 2>/dev/null || true)"
if [ -z "$NODE_BIN" ]; then
  NODE_BIN="$(ls -1 "$HOME"/.nvm/versions/node/*/bin/node 2>/dev/null | sort -V | tail -1)"
fi
EXPORT="$REPO/static-site/export.py"
LOGDIR="$REPO/data/logs"
STAMP=$(date +%Y%m%d_%H%M)
LOG="$LOGDIR/deploy_${STAMP}.log"
# #149 方案①a(2026-10-02): 锁粒度拆分 — 两段式 exec(样板=scripts/staticdata_backup_async.sh 段1/段2)。
# 首次进入(不带 --git-phase)= 段1: export+校验+R2 上传+rsync(可并发, 不持 git 写锁);
# 段1 末尾 exec with_lock.py 重入本脚本(带 --git-phase)= 段2: 持锁只跑 git add/commit/push
# + 收尾(秒~分钟级), 根治「export+R2 长跑段占锁」#149 根因。①b(各 backfill 去掉外层 deploy
# 锁)落地后, trade_deploy.lock 只被 git 写段持用。
GIT_PHASE=0
if [ "${1:-}" = "--git-phase" ]; then
  GIT_PHASE=1
  shift
fi
NAME="${1:-all}"   # 可选 pipeline 名（pipeline.sh 持锁调用时传入；无参=all）

mkdir -p "$LOGDIR"
# 段2 git 写段专用锁: 默认 /tmp/trade_deploy.lock(与 staticdata async/sync 的 git 段同锁统一
# 串行全部 git 写); 测试隔离可经 DEPLOY_LOCK 覆写(见 149a 报告 §自测)。
LOCK="${DEPLOY_LOCK:-/tmp/trade_deploy.lock}"

# 加载 .env（PURGE_SECRET 等 Worker 凭证）到环境，确保手动跑 deploy.sh 时子进程
# （upload_r2.py / export.py）能读到 PURGE_SECRET 调 /api/purge-cache 清 edge cache。
# 根治 2026-08-09 手动部署丢失 PURGE_SECRET 致 edge cache 不清、前端读旧版 4h 事故。
# set -a 自动 export；.env 内变量（R2_*/PURGE_SECRET）launchd/环境未预设，source 不冲突。
set -a
[ -f "$GIT_REPO/.env" ] && . "$GIT_REPO/.env"
[ -f "$REPO/.env" ] && . "$REPO/.env"
set +a

# #149 方案①a: 段1 = 锁外 export/R2/rsync(可并发, 不持 git 写锁)。段2(--git-phase 重入)=
# 持 /tmp/trade_deploy.lock 只跑 git add/commit/push + 收尾(见下方 git 段注释)。
# ⚠ 149a 自测发现: git_fetch_timeout / git_push_timeout 必须定义在段1 if 之外(公共区)。
# 段2 重入进程整脚本重跑但跳过段1(if 为假), 函数若在 if 内定义则段2 调用报 command not
# found(rc=127)被误判 push/fetch 失败 → 走错误的重试/abort 分支(修正于 2026-10-02)。
# git fetch 超时保护(2026-09-15): 云上连 GitHub 22 端口间歇性卡死(ssh git@github.com
# git-upload-pack 曾卡 51 分钟死拽 /tmp/trade_deploy.lock, 连锁卡 staticdata_sync +
# trade-public-fund-daily 被 systemd 强杀), 给 git fetch 包超时兜底。
# macOS/Linux 无 timeout 命令, 用 bash 原生 background+sleep+kill(同 run_r2_upload 模式);
# git fetch 会 spawn ssh 子进程, 光杀 git 留 orphan ssh 继续卡, 故 pkill -P 连子进程一起杀。
# 返回 0=成功 / 124=超时 / 其他=失败。
git_fetch_timeout() {
  local limit="${1:-120}"
  local tmp_log pid slept rc
  tmp_log=$(mktemp)
  git -C "$GIT_REPO" fetch origin main >"$tmp_log" 2>&1 &
  pid=$!
  slept=0
  rc=""
  while kill -0 "$pid" 2>/dev/null; do
    sleep 5
    slept=$((slept + 5))
    if [ "$slept" -ge "$limit" ]; then
      echo "⚠ git fetch origin main 超 ${limit}s 未退出，kill pid=$pid 释放 deploy.lock" | tee -a "$LOG"
      pkill -TERM -P "$pid" 2>/dev/null || true
      kill -TERM "$pid" 2>/dev/null; sleep 2
      pkill -KILL -P "$pid" 2>/dev/null || true
      kill -KILL "$pid" 2>/dev/null || true
      wait "$pid" 2>/dev/null || true
      rc=124
      break
    fi
  done
  if [ -z "$rc" ]; then
    wait "$pid"; rc=$?
  fi
  tail -n 30 "$tmp_log" >> "$LOG" 2>/dev/null || true
  rm -f "$tmp_log"
  return "$rc"
}

# git push 超时保护(2026-09-15): 与 git_fetch_timeout 对称(同 background+sleep+kill 模式、
# 同 pkill -P 杀 ssh 子进程), 防 push 卡 GitHub 22 端口死拽 /tmp/trade_deploy.lock 连锁卡后续
# 所有 deploy。git push 同样 spawn ssh 子进程, 光杀 git 留 orphan ssh 继续卡, 故 pkill -P 连杀。
# 返回 0=成功 / 124=超时 / 其他=失败。
git_push_timeout() {
  local limit="${1:-120}"
  local tmp_log pid slept rc
  tmp_log=$(mktemp)
  git -C "$GIT_REPO" push origin main:main >"$tmp_log" 2>&1 &
  pid=$!
  slept=0
  rc=""
  while kill -0 "$pid" 2>/dev/null; do
    sleep 5
    slept=$((slept + 5))
    if [ "$slept" -ge "$limit" ]; then
      echo "⚠ git push origin main:main 超 ${limit}s 未退出，kill pid=$pid 释放 deploy.lock" | tee -a "$LOG"
      pkill -TERM -P "$pid" 2>/dev/null || true
      kill -TERM "$pid" 2>/dev/null; sleep 2
      pkill -KILL -P "$pid" 2>/dev/null || true
      kill -KILL "$pid" 2>/dev/null || true
      wait "$pid" 2>/dev/null || true
      rc=124
      break
    fi
  done
  if [ -z "$rc" ]; then
    wait "$pid"; rc=$?
  fi
  tail -n 30 "$tmp_log" >> "$LOG" 2>/dev/null || true
  rm -f "$tmp_log"
  return "$rc"
}

if [ "$GIT_PHASE" != "1" ]; then
echo "=== deploy.sh 段1(锁外 export+R2+rsync)开始 $(date '+%Y-%m-%d %H:%M:%S') ===" | tee "$LOG"

# 0. 时段闸门：交易日盘中 09:30-15:30 拒跑全量 export+deploy（防覆盖 intraday 实时版，事故 94c79041 根因）
# intraday_snapshot.sh 定时任务盘中每 30 分钟推 intraday_snapshot.json 到 main，
# 全量 deploy 会 export.py 重新生成 + git add 通配带入，易覆盖实时版。force 可绕过。
FORCE=0
case " $* " in *" force "*) FORCE=1;; esac
CURRENT_HM=$(date +%H%M)
# 判断失败时保守当交易日(echo 1=拦盘中)：盘中闸本意是「交易日盘中 09:30-15:30 不跑全量
# export+deploy」，判断失败(calendar import 异常/cd REPO 失败)若误放=可能覆盖 intraday
# 实时版；失败降级方向与 main-merge.sh is_trading_day_now(失败 exit 2 按交易日保守拦)同向(§14 P0)。
IS_TRADING=$(cd "$REPO" && "$PY" -c "from app.calendar import is_trading_day; print(1 if is_trading_day() else 0)" 2>/dev/null || echo 1)
echo "时段闸门: IS_TRADING=${IS_TRADING} CURRENT_HM=$CURRENT_HM FORCE=$FORCE" | tee -a "$LOG"
if [ "$IS_TRADING" = "1" ] && [ "$CURRENT_HM" -ge 0930 ] && [ "$CURRENT_HM" -le 1530 ] && [ "$FORCE" != "1" ]; then
  echo "✗ 交易日盘中（09:30-15:30），拒跑全量 export+deploy（防覆盖 intraday 实时版；force 可绕过）" | tee -a "$LOG"
  exit 1
fi

# 0.5 fetch origin main（后续 unmerged 检查 + rebase 需要）
# R2 阶段4a 后 static-site/data/ 全量移出 git（含 feed.xml，2026-08-10 也走 R2），
# 原 checkout intraday_snapshot/notifications.json 防通配带入已无效（文件 gitignored），
# DATA_FILES 改精确列表（min JS/CSS）不再通配 add，无残留带入风险。
# fetch 失败/超时不阻断（|| true 语义：fetch 仅同步远端供 unmerged 检查用，卡死就跳过继续）。
git_fetch_timeout "${GIT_FETCH_TIMEOUT:-120}" || echo "⚠ git fetch origin main 未成功（rc=$?），继续部署（unmerged 检查用本地 ref 兜底）" | tee -a "$LOG"

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
        echo "⚠ 清理 unmerged 数据文件: ${_u}（已 reset HEAD + checkout origin/main）" | tee -a "$LOG"
        ;;
      *)
        NON_DATA_UNMERGED="$NON_DATA_UNMERGED $_u"
        ;;
    esac
  done
  if [ -n "$NON_DATA_UNMERGED" ]; then
    echo "✗ 工作区有非数据文件 unmerged: ${NON_DATA_UNMERGED}，拒绝 deploy（需手动解决代码冲突）" | tee -a "$LOG"
    exit 1
  fi
fi

# 0.8 刷新 etf_index_map.json + board_etf_map.json（P2-新-G ETF 联动 tag 数据源）。
# gen_etf_index_map.py：akshare fund_etf_spot_em() 名称匹配反推 track_index_code，生成
#   data/etf_index_map.json（build_board_etf_map.py 输入，2026-08-06 事故修复新增）。
# build_board_etf_map.py：行业/概念关键词匹配 + 14 宽基/红利/港股指数代码精确匹配。
# 根因修复（2026-08-06）：etf_index_map.json 从未成功生成（生成脚本不存在），_load_etf_index_map_reverse
#   读不到只 warning + exit 0 静默失败，致 board_etf_map.json 14 宽基全空，首页"全部无 ETF"。
#   现前置 gen_etf_index_map.py 刷新输入，build_board_etf_map.py 失败时（2026-09-22 加固）:
#   降级为「board_etf_map 用旧版兜底 + 该文件跳过」而非终止整个 deploy（9/21 断档根因:
#   build 失败 exit 终止 deploy → export 没跑 → signal_kelly_trades 停更 2 天）。
#   原语义「防静默覆盖空 map」保留: build 失败绝不用空/坏 map 覆盖现有 board_etf_map.json
#   （build_board_etf_map.py 内部先写盘后校验, 失败时文件已写坏 → 必须 build 前备份 + 失败恢复）。
echo "-> 刷新 etf_index_map.json (gen 名称匹配反推 track_index_code) ..." | tee -a "$LOG"
"$PY" "$REPO/scripts/gen_etf_index_map.py" >> "$LOG" 2>&1 || {
  echo "⚠ gen_etf_index_map.py 失败(akshare 反爬/网络?)，build_board_etf_map.py 将走名称匹配兜底" | tee -a "$LOG"
}
echo "-> 刷新 board_etf_map.json (ETF 联动 tag 数据源) ..." | tee -a "$LOG"
# 2026-09-22 加固（9/21 断档根因）: build_board_etf_map.py 失败不再终止整个 deploy。
# 根因: build_board_etf_map.py 内部先 OUT.write_text 写盘后 14 宽基校验(exit 1)，
#   失败时 $REPO/data/board_etf_map.json 已被写成坏/空 map → 原逻辑 exit 终止 deploy 防它上线；
#   但连带 export 没跑 → signal_kelly_trades 停更。现改为: build 前备份旧 map，
#   build 失败 → 恢复旧版 + SKIP_MAP_SYNC=1（跳过项6/6.1 的 cp 与哈希，防坏 map 进 R2/双树），
#   不 exit，export/其余产物照常生成。防静默覆盖语义保留（坏 map 绝不覆盖现有文件）。
_BOARD_MAP_BAK="$REPO/data/board_etf_map.json.deploybak"
[ -f "$REPO/data/board_etf_map.json" ] && cp -p "$REPO/data/board_etf_map.json" "$_BOARD_MAP_BAK" 2>>"$LOG" || true
"$PY" "$REPO/scripts/build_board_etf_map.py" >> "$LOG" 2>&1
BUILD_RC=$?
SKIP_MAP_SYNC=0
MAP_STALE=0
if [ "$BUILD_RC" -ne 0 ]; then
  SKIP_MAP_SYNC=1
  MAP_STALE=1
  echo "✗ build_board_etf_map.py 失败(退出码 ${BUILD_RC}，14 宽基校验未过/akshare 兜底也失败)，board_etf_map 用旧版兜底，跳过该项更新（其余产物照常生成）" | tee -a "$LOG"
  if [ -f "$_BOARD_MAP_BAK" ]; then
    cp -p "$_BOARD_MAP_BAK" "$REPO/data/board_etf_map.json" 2>>"$LOG" \
      && echo "✓ board_etf_map.json 已从备份恢复旧版（build 失败前备份）" | tee -a "$LOG" \
      || { echo "✗ 恢复 board_etf_map.json 旧版备份失败（data/ 现为 build 失败写坏的 map），宁可终止 deploy 也绝不让坏 map 经 export.py 生成坏 overview 绕过 check 上线" | tee -a "$LOG"; exit 1; }
  else
    # 2026-09-22 F2 加固: 无备份可用（首次部署/备份 cp 失败）同样 exit 1——build 已失败时
    # data/board_etf_map.json 必为坏/空 map，继续 export 会用坏 map 生成 overview 绕过 check 上线。
    echo "✗ 无 board_etf_map.json 旧版备份可用（首次部署？），且 build 失败 data/ 已是坏 map，终止 deploy" | tee -a "$LOG"
    exit 1
  fi
fi
rm -f "$_BOARD_MAP_BAK"

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
# 2026-09-22 加固: build 失败(SKIP_MAP_SYNC=1)时跳过 cp——data/ 已恢复旧版，static-site/data/ 保持旧版，
#   R2 前端读旧版与 overview 仍一致(同一旧版)，且绝不把坏 map 带上线(防静默覆盖语义保留)。
if [ "$SKIP_MAP_SYNC" -eq 0 ]; then
cp "$REPO/data/board_etf_map.json" "$REPO/static-site/data/board_etf_map.json" 2>>"$LOG" \
  && echo "✓ board_etf_map.json 已同步到 static-site/data/（build 后自动联动，前端 R2 与 overview 一致）" | tee -a "$LOG" \
  || echo "⚠ 同步 board_etf_map.json 到 static-site/data/ 失败（不阻断，export 仍用 data/ 新版）" | tee -a "$LOG"
else
  echo "ℹ build_board_etf_map 失败，跳过 board_etf_map.json 同步到 static-site/data/（R2 前端保持旧版一致）" | tee -a "$LOG"
fi

# 项6.1: 双树单源对齐（2026-09-18 ④，3版本漂移根因②）——board_etf_map.json 同步到 $GIT_REPO/data/。
# 背景: queries.py _ETF_MAP_PATH = Path(__file__).absolute().parent.parent/"data"/"board_etf_map.json"
#   （L73 不 resolve symlink），从哪个树启动进程读哪个树 data/ → trade-data 与 trade-data-signal 双树
#   board_etf_map 分叉（机器人 91.5 vs 76.4 / a500 75.8 vs 83.3），冻结表 4 批 frozen_at 的 track_score
#   取各树自己注入值 → K=1 赢家 top1 漂移出 3 版本。
# 此步 build 成功后复制到 $GIT_REPO/data/（git 树），保证双树同源 + 哈希校验（§22 一致性）。
# ⚠ 与项6 不同: 项6 目标是 $REPO/static-site/data/（R2 上传源）；此处目标是 $GIT_REPO（trade 侧后端读的 data/）。
#   git 检查 gitignore 忽略 data/board_etf_map.json，cp 不产生新 commit（纯本机数据层对齐）。
# cp 后哈希校验，不一致丢 §22 一致性阻断（防后续从老树启动的进程读旧版再反向写冻结表）。
if [ "$SKIP_MAP_SYNC" -eq 0 ]; then
cp "$REPO/data/board_etf_map.json" "$GIT_REPO/data/board_etf_map.json" 2>>"$LOG" \
  && echo "✓ board_etf_map.json 已同步到 $GIT_REPO/data/（双树单源）" | tee -a "$LOG" \
  || echo "⚠ 同步 board_etf_map.json 到 $GIT_REPO/data/ 失败（不阻断，export 仍用 $REPO 新版）" | tee -a "$LOG"
_MAP_H1=$("$PY" -c "import hashlib,sys;print(hashlib.md5(open(sys.argv[1],'rb').read()).hexdigest())" "$REPO/data/board_etf_map.json" 2>/dev/null)
_MAP_H2=$("$PY" -c "import hashlib,sys;print(hashlib.md5(open(sys.argv[1],'rb').read()).hexdigest())" "$GIT_REPO/data/board_etf_map.json" 2>/dev/null)
if [ -n "$_MAP_H1" ] && [ -n "$_MAP_H2" ] && [ "$_MAP_H1" != "$_MAP_H2" ]; then
  echo "✗ board_etf_map.json 双树哈希不一致（$REPO=${_MAP_H1} vs $GIT_REPO=${_MAP_H2}），阻断 deploy（§22 双树单源）" | tee -a "$LOG"
  exit 1
fi
echo "✓ board_etf_map.json 双树哈希校验通过（${_MAP_H1}）" | tee -a "$LOG"
else
  echo "ℹ build_board_etf_map 失败，跳过双树单源同步与哈希校验（$GIT_REPO/data/ 保持旧版一致）" | tee -a "$LOG"
fi

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

# 1.0.2 accum_nav_map 每日刷新(#52, 2026-09-05): 数据源=etf_daily 主库(盘后采集已最新),
# 前端 simnetasset 净资产曲线 + G/H/I 强平日真实价(_gihRealizeRealForce)共用同一文件。
# 生成脚本输出 docs/kelly/position/scripts/accum_nav_map.json -> cp 到 $REPO static-site/data/
# (R2 上传源)。§22 三步由本 deploy 链闭环: 后续 upload-data-large/upload-all-data 传 R2 data/ 前缀
# + rsync 同步 trade git + git push。失败阻断(前端强平日真价/净资产曲线依赖, 防线上旧数据)。
echo "-> 生成 accum_nav_map.json ..." | tee -a "$LOG"
# 显式 REPO=$REPO 读主库(单仓下 REPO 即主库; 双仓下 REPO 默认 trade-data, 防 deploy 从 trade 手动跑时读到 rsync 镜像)
REPO="$REPO" "$PY" "$GIT_REPO/docs/kelly/position/scripts/export_accum_nav_map.py" --all 2>&1 | tee -a "$LOG"
ACCUM_RC=${PIPESTATUS[0]}
if [ "$ACCUM_RC" -ne 0 ]; then
  echo "✗ export_accum_nav_map.py 失败(退出码 $ACCUM_RC)，终止部署(前端 simnetasset 净资产曲线/强平日真价依赖)" | tee -a "$LOG"
  exit "$ACCUM_RC"
fi
cp "$GIT_REPO/docs/kelly/position/scripts/accum_nav_map.json" "$REPO/static-site/data/accum_nav_map.json" 2>>"$LOG" \
  && echo "✓ accum_nav_map.json 已同步到 static-site/data/(R2 上传源, 新鲜度由 check_data_integrity accum_nav_map_fresh 机检)" | tee -a "$LOG" \
  || { echo "✗ accum_nav_map.json 同步到 static-site/data/ 失败" | tee -a "$LOG"; exit 1; }
# per-ETF 拆分(2026-09-17 懒加载): 与全量同源同 dict, 一并 cp 到 R2 上传源; rm -rf 旧目录再 cp, 防退市/移除
# code 的陈旧文件残留触发 check_accum_nav_split_consistency「全量无此 code」FAIL(§5.4⑦ 同源对账)。
rm -rf "$REPO/static-site/data/accum_nav" 2>>"$LOG" || true
cp -R "$GIT_REPO/docs/kelly/position/scripts/accum_nav" "$REPO/static-site/data/accum_nav" 2>>"$LOG" \
  && echo "✓ accum_nav/ per-ETF 拆分已同步到 static-site/data/(R2 上传源, 同源对账由 check_accum_nav_split_consistency 机检)" | tee -a "$LOG" \
  || { echo "✗ accum_nav/ per-ETF 拆分同步到 static-site/data/ 失败" | tee -a "$LOG"; exit 1; }

# 1.1 数据产物校验（4 类事故拦截：board_etf_map 全空 / boot.date 不一致 /
# amount_forecast 爆炸 / 关键文件丢失）。--deploy-mode 仅 fail 阻断（exit 1），
# warn 不阻断（exit 0），避免预存在 warn（etf_index_map 缺失等）阻塞所有 deploy。
# 2026-08-06 加：拦 "成交额卡显示昨日值"(boot 嵌旧 overview) / "9.52万亿爆炸" / "ETF 全空" 等事故。
echo "-> 运行 check_data_integrity.py 数据产物校验 ..." | tee -a "$LOG"
"$PY" "$REPO/scripts/check_data_integrity.py" --deploy-mode --data-dir "$REPO/static-site/data" 2>&1 | tee -a "$LOG"
CHECK_RC=${PIPESTATUS[0]}
if [ "$CHECK_RC" -ne 0 ]; then
  echo "✗ 数据产物校验失败(退出码 $CHECK_RC)，终止部署（4 类事故拦截）" | tee -a "$LOG"
  # export-guard L4 (2026-10-03): 校验失败升级 --severe 告警(事故 5 次 deploy 失败无人知)。
  "$PY" "$REPO/scripts/notify.py" "[告警] deploy 数据产物校验失败" "deploy.sh check_data_integrity FAIL(rc=$CHECK_RC), 已终止部署(4 类事故拦截)。日志: $LOG" --severe --from-prefix "[告警]" --dedup-key deploy_check_data_integrity_fail --dedup-window 21600 2>&1 | tee -a "$LOG" || true
  exit "$CHECK_RC"
fi
echo "✓ 数据产物校验通过" | tee -a "$LOG"

# 1.1.1 任务状态一致性机检(CLAUDE.md §23.12-1, 2026-09-06 用户拍板根治)
# 对账 A pending-index 编号完整性 / B TASKS 幽灵编号+残留关闭指针 / C 僵尸巡检 cron,
# 任一 FAIL → 非0退出阻断上线(任务状态唯一权威=pending-index, 各处置指针不写状态断言, 机检兜底)。
# 用 $GIT_REPO(trade 仓库): TASKS.md/.claude 只在 trade 树(trade-data 仅 docs 是 symlink,
# TASKS.md/.claude 非 symlink 不存在于 trade-data)。每日运行 = update_all 17:50 O1 统一 deploy 链,
# 与 check_data_integrity 完全同待遇(每日 + deploy 前双覆盖)。
echo "-> 运行 check_task_state.py 任务状态一致性机检 ..." | tee -a "$LOG"
"$PY" "$GIT_REPO/scripts/check_task_state.py" --repo "$GIT_REPO" --deploy-mode 2>&1 | tee -a "$LOG"
TASK_RC=${PIPESTATUS[0]}
if [ "$TASK_RC" -ne 0 ]; then
  echo "✗ 任务状态一致性机检失败(退出码 $TASK_RC)，终止部署(§23.12-1 FAIL 阻断上线)" | tee -a "$LOG"
  # export-guard L4 (2026-10-03): 校验失败升级 --severe 告警。
  "$PY" "$GIT_REPO/scripts/notify.py" "[告警] deploy 任务状态机检失败" "deploy.sh check_task_state FAIL(rc=$TASK_RC), 已终止部署(§23.12-1)。日志: $LOG" --severe --from-prefix "[告警]" --dedup-key deploy_check_task_state_fail --dedup-window 21600 2>&1 | tee -a "$LOG" || true
  exit "$TASK_RC"
fi
echo "✓ 任务状态一致性机检通过" | tee -a "$LOG"

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
  # export-guard L4 (2026-10-03): 校验失败升级 --severe 告警(同类闸门)。
  "$PY" "$REPO/scripts/notify.py" "[告警] deploy 入样宇宙规则校验失败" "deploy.sh check_universe_alignment FAIL(rc=$UNIV_RC), 已终止部署(§23.6)。日志: $LOG" --severe --from-prefix "[告警]" --dedup-key deploy_check_universe_fail --dedup-window 21600 2>&1 | tee -a "$LOG" || true
  exit "$UNIV_RC"
fi
echo "✓ 入样宇宙规则校验通过" | tee -a "$LOG"

# 1.2.1 AI降亏默认档键集跨端一致性机检(CLAUDE.md §22 代码内常量登记点 + §5.4⑥ 键集机检,
# 审计报告 docs/kelly/analysis/v115-new14-baseline-alignment-audit.md §五)。
# 默认档键集在 common.js preset / check_signals.py 白名单+中文名两表 / overfit_monitor RECENT_KEYS /
# app.js 兜底键集各有一份常量副本(v1.1.5 切 NEW14 漏 check_signals 即此病灶 R1/R2), 任一份漏同步
# =邮件不标「AI降亏·建议回避」而首页灰显删除线的跨端不一致。任一断言 FAIL → 非0退出阻断上线。
echo "-> 运行 check_fade_keys_alignment.py AI降亏默认档键集一致性机检 ..." | tee -a "$LOG"
"$PY" "$REPO/scripts/check_fade_keys_alignment.py" --repo "$REPO" --deploy-mode 2>&1 | tee -a "$LOG"
FADE_RC=${PIPESTATUS[0]}
if [ "$FADE_RC" -ne 0 ]; then
  echo "✗ AI降亏默认档键集一致性机检失败(退出码 $FADE_RC)，终止部署(§22 登记点机检 FAIL 阻断上线)" | tee -a "$LOG"
  exit "$FADE_RC"
fi
echo "✓ AI降亏默认档键集一致性机检通过" | tee -a "$LOG"

# 1.2.2 AI监控卡拆分产物结构校验(scripts/check_overfit_split_parity.py 结构模式, 2026-08-24 用户拍板)
# B件套拆分(commit 70163b663)曾误删主文件 filtered 挂载, 致「降亏开+无K档」默认路径(app.js _ovFade)
# 读到全信号人口而非过滤人口; 当时 parity 脚本未挂任何自动链故未拦(病灶 2026-08-24 tester 批定位)。
# 本步常驻拦截: 主文件必须含 accuracy/overfit/filtered/generated_at(filtered 键即本病灶断言),
# ext 含 by_k/filtered_by_k, 两文件 generated_at 对齐且 compact 序列化。
# 注意: 本地 static-site/data 两文件由 overfit_monitor.sh 打点产出(gitignore 不进 git),
# 若打点侧还是老版本产物(主文件无 filtered)本步会拦下——merge 后先跑一次 bash scripts/overfit_monitor.sh force 再 deploy。
# 任一 FAIL → 非0退出阻断上线。
echo "-> 运行 check_overfit_split_parity.py AI监控卡拆分产物结构校验 ..." | tee -a "$LOG"
"$PY" "$REPO/scripts/check_overfit_split_parity.py" --main "$REPO/static-site/data/overfit_monitor.json" --ext "$REPO/static-site/data/overfit_monitor_ext.json" 2>&1 | tee -a "$LOG"
OVP_RC=${PIPESTATUS[0]}
if [ "$OVP_RC" -ne 0 ]; then
  echo "✗ AI监控卡拆分产物结构校验失败(退出码 $OVP_RC)，终止部署(filtered/ext 键缺失或 compact 违规)" | tee -a "$LOG"
  exit "$OVP_RC"
fi
echo "✓ AI监控卡拆分产物结构校验通过" | tee -a "$LOG"

# 1.2.3 AI监控卡组集一致性校验(scripts/check_overfit_recent_parity.mjs, 2026-08-25 挂自动链)
# 病灶同类: 该脚本 2026-08-23 起就存在(18 断言: 组集函数 vs recent 明细独立复刻逐点对比),
# 但从未挂任何自动链——「校验存在≠校验生效」(filtered 键事故同款教训)。本步常驻拦截:
# 前端 _ovAggregateRecent(app.js 真实切片进 vm 沙箱)对生产 recent 明细的聚合结果,
# 与独立直数复刻逐位一致 + 7模式键完整性(recent.keys 漏列即 FAIL)。
# 输入=打点侧主文件($REPO/static-site/data/overfit_monitor.json 的 recent 块),
# 校验的前端源码=$GIT_REPO/static-site/app.js+common.js(即将上线代码本身)。
# node 探测失败/断言 FAIL → 非0退出阻断上线(fail-safe, 不静默跳过)。
if [ -z "$NODE_BIN" ] || [ ! -x "$NODE_BIN" ]; then
  echo "✗ 找不到可执行的 node(launchd PATH 与 ~/.nvm 均无)，AI监控卡组集校验无法执行，终止部署" | tee -a "$LOG"
  exit 1
fi
echo "-> 运行 check_overfit_recent_parity.mjs AI监控卡组集一致性校验 ..." | tee -a "$LOG"
RECENT_JSON="$REPO/static-site/data/overfit_monitor.json" "$NODE_BIN" "$GIT_REPO/scripts/check_overfit_recent_parity.mjs" 2>&1 | tee -a "$LOG"
OVR_RC=${PIPESTATUS[0]}
if [ "$OVR_RC" -ne 0 ]; then
  echo "✗ AI监控卡组集一致性校验失败(退出码 $OVR_RC)，终止部署(组集聚合/recent.keys 完整性断言 FAIL)" | tee -a "$LOG"
  exit "$OVR_RC"
fi
echo "✓ AI监控卡组集一致性校验通过" | tee -a "$LOG"

# 1.2.4 critical-css 与 style.css 双源一致性机检(CLAUDE.md §24 + §22 一致性精神, 2026-09-23 建立)
# index.html <style id="critical-css"> 是首屏防 FOUC 的内联手抄样式, 移动端按钮样式与 style.css
# 同名 @media(max-width:768px) 块重复。历史: style.css 改过(安全区修复/字号a11y/44px触控)而
# critical-css 未同步, 形成静默漂移(header safe-area padding / collect-time字号 / period-bar top /
# bottomnav min-height 4 处)。本步常驻拦截: critical-css 每条规则(选择器+规范化声明集)必须能在
# style.css 全文件找到等值副本, 任一无等值 → FAIL 阻断上线(style.css 改漏同步 critical 即触发)。
# 校验源 = $GIT_REPO/static-site(即将上线的代码本身)。
echo "-> 运行 check_dual_src_sync.py critical-css 与 style.css 双源一致性机检 ..." | tee -a "$LOG"
"$PY" "$GIT_REPO/scripts/check-dual-src/check_dual_src_sync.py" --site-dir "$GIT_REPO/static-site" 2>&1 | tee -a "$LOG"
DDS_RC=${PIPESTATUS[0]}
if [ "$DDS_RC" -ne 0 ]; then
  echo "✗ critical-css 与 style.css 双源一致性机检失败(退出码 $DDS_RC)，终止部署(§24 双源防漂移 FAIL 阻断上线)" | tee -a "$LOG"
  exit "$DDS_RC"
fi
echo "✓ critical-css 与 style.css 双源一致性机检通过" | tee -a "$LOG"

# 1.3 版本一致性校验(CLAUDE.md §24⑤, 2026-08-15 补; #48)
# 适配 #46 日期+批次版本串机制: index引用版本串格式/与sw批次一致/资源存在/min比源新,
# 任一 FAIL → 非0退出阻断上线(防孤儿快照再产生, 2026-08-14 全站白屏事故根因⑤)。
echo "-> 运行 check_version_consistency.py 版本一致性校验 ..." | tee -a "$LOG"
GIT_REPO="$GIT_REPO" "$PY" "$REPO/scripts/check_version_consistency.py" --site-dir "$GIT_REPO/static-site" --deploy-mode 2>&1 | tee -a "$LOG"
VER_RC=${PIPESTATUS[0]}
if [ "$VER_RC" -ne 0 ]; then
  echo "✗ 版本一致性校验失败(退出码 $VER_RC)，终止部署(§24⑤ FAIL 阻断上线)" | tee -a "$LOG"
  # export-guard L4 (2026-10-03): 校验失败升级 --severe 告警。
  "$PY" "$REPO/scripts/notify.py" "[告警] deploy 版本一致性校验失败" "deploy.sh check_version_consistency FAIL(rc=$VER_RC), 已终止部署(§24⑤ 防孤儿快照)。日志: $LOG" --severe --from-prefix "[告警]" --dedup-key deploy_check_version_fail --dedup-window 21600 2>&1 | tee -a "$LOG" || true
  exit "$VER_RC"
fi
echo "✓ 版本一致性校验通过" | tee -a "$LOG"

# 1.3.1 etf_daily 占位残留混合行闸门(2026-09-08 P0 事故根因防御)
# 9/8 盘中全市场占位(accum_nav=1.5/open=1.49)被盘后 backfill 覆盖成「真实名+真实close+残留1.5」
# 混合行, 穿透全部现有检测, 回测 current_price 取 1.5 虚高收益率 80%+。本步常驻拦截:
# 只要 etf_daily 存在 etf_name<>etf_code 且 accum_nav=1.5/open=1.49 的行 → FAIL 阻断上线,
# 污染未清不放行(§23.15 上线必须完整版 / §22 数据一致性)。定时告警仍由 check_data_gap_alerts.sh
# 22:35 跑(含 dedup/ack/恢复通知), 本闸门只做只读断言。
echo "-> 运行 check_data_gap_alerts.py --deploy-mode 占位残留混合行闸门 ..." | tee -a "$LOG"
"$PY" "$REPO/scripts/check_data_gap_alerts.py" --repo "$REPO" --deploy-mode 2>&1 | tee -a "$LOG"
PH_RC=${PIPESTATUS[0]}
if [ "$PH_RC" -ne 0 ]; then
  echo "✗ 占位残留混合行闸门失败(退出码 $PH_RC)，终止部署(9/8 P0 污染未清, accum_nav=1.5 残留)" | tee -a "$LOG"
  # export-guard L4 (2026-10-03): 校验失败升级 --severe 告警(同类闸门)。
  "$PY" "$REPO/scripts/notify.py" "[告警] deploy 占位残留混合行闸门失败" "deploy.sh 占位残留混合行闸门 FAIL(rc=$PH_RC), 已终止部署(9/8 P0 污染未清, accum_nav=1.5 残留)。日志: $LOG" --severe --from-prefix "[告警]" --dedup-key deploy_check_placeholder_residue_fail --dedup-window 21600 2>&1 | tee -a "$LOG" || true
  exit "$PH_RC"
fi
echo "✓ 占位残留混合行闸门通过" | tee -a "$LOG"

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
  echo "-> rsync 采集数据: $REPO/data/ -> $GIT_REPO/data/ (exclude logs + 告警状态文件 + 4 tracked 种子) ..." | tee -a "$LOG"
  # 2026-09-29 告警降噪(改动6): 排除告警状态文件, 防双树(REPO 数据树 + GIT_REPO git 树)
  # 各维护一份 data/notify_dedup.json / alert_state.json 被 rsync -a 覆盖互相丢 key
  # (dedup 失效根因, 09-28 sigkelly_snapshot_stagnation 同 key 24h 内 2 次)。
  # 状态文件以 REPO(trade-data)侧为准, 不跨树同步; 排除后单源写, dedup 窗口可靠。
  # 2026-10-02 #119: 排除代码仓 git tracked 的 4 个 clone 种子文件(index_etf_map.json /
  # stock_codes.json / trade.db / trade_dates.txt)。这 4 文件是 bootstrap 文档
  # (docs/deploy/migration-data-bootstrap-plan-20260912.md L41/72-74/118)定的新机 clone 种子,
  # 云上被 rsync 覆盖写 → git status data/ 变 M 脏 → 下次 git pull 被挡(#119/#115/#118 同源)。
  # 不能脱跟踪(trade_dates.txt 有真实代码仓 fallback 消费方 nextday_plan_generator.py:169-170
  # ROOT/data resolve; 脱跟踪=新机 clone 不再自带种子)。改为 rsync --exclude: 数据仓(REPO)侧
  # 继续正常生成/刷新这些文件(gen_etf_index_map.py / stock_daily.py codes / app/calendar.py
  # refresh_trade_dates / trade.db 0B 占位), 代码仓(GIT_REPO)侧保留 clone 种子不再被覆盖写;
  # 运行期消费方优先读 REPO 数据仓侧新版(_trade_calendar_dates 遍历 db_path.parent→ROOT/data
  # →REPO/data, 数据仓侧先命中), 种子语义不破坏。
  rsync -a --exclude=logs/ --exclude=notify_dedup.json --exclude=alert_state.json \
        --exclude=alerts/ --exclude=warning_* --exclude=backups/ \
        --exclude=index_etf_map.json --exclude=stock_codes.json \
        --exclude=trade.db --exclude=trade_dates.txt \
        "$REPO/data/" "$GIT_REPO/data/" 2>&1 | tee -a "$LOG"
  RSYNC_DB_RC=${PIPESTATUS[0]}
  if [ "$RSYNC_DB_RC" -ne 0 ]; then
    echo "⚠ rsync data/ 失败(退出码 $RSYNC_DB_RC)，不阻断部署(static-site/data/ JSON 已上线)" | tee -a "$LOG"
  else
    echo "✓ rsync data/ 完成（DB 同步到 $GIT_REPO/data/）" | tee -a "$LOG"
  fi
fi

# 1.8 上传 lab/*.json + trade_sim/*.html + index/ + industry/ 等到 R2 —— 已异步化(2026-10-04 P1)
# (R2 全迁后 index/industry/trade_sim 前端从 R2 读;lab 已在 R2;双源过渡也刷 R2 保最新)
#
# 2026-10-04 P1 主链有界化: 原 17 条 R2 通道逐条串行(看门狗 900~7200s, 含按字节估算)阻塞主链
# (10-04 update_all 段1 10007s≈2h48m / 09-20 10754s≈3h, R2 上传占大头)。现拆出主链异步:
# 上传本体+看门狗估算+失败告警(verify-channels 轻量对账→真缺口才 --severe)全部收敛到
# scripts/r2_upload_async.sh(本脚本唯一落点)。deploy.sh 只触发 async(云上 systemd-run 独立
# cgroup / 本地 nohup), 不再同步串行跑 R2。幂等+增量指纹+with_lock --nb 互斥(并发触发跳过,
# 防重复 PUT 放大 9 月 Class A 超免费额度事故); 周日 weekday==6 force_full 全量漂移防护保留。
# 数据上线允许延迟 ≤1~2h(下一趟 deploy 的 R2 增量 + verify-r2 对账兜底)。
# ⚠ 可回退: 环境变量 R2_ASYNC_UPLOAD=0 → 同步串行跑 r2_upload_async.sh(等同旧行为阻塞主链)。

echo "-> 触发 R2 上传(异步, 拆出主链等待区间; 上传本体+看门狗+失败告警见 scripts/r2_upload_async.sh)..." | tee -a "$LOG"
if [ "${R2_ASYNC_UPLOAD:-1}" = "0" ]; then
  # 可回退开关(2026-10-04 P1): R2_ASYNC_UPLOAD=0 → 同步串行跑 async 脚本本体(等同旧行为阻塞主链)。
  echo "  → R2_ASYNC_UPLOAD=0, 同步串行上传(回退开关, 阻塞主链)" | tee -a "$LOG"
  REPO="$REPO" GIT_REPO="$GIT_REPO" bash "$GIT_REPO/scripts/r2_upload_async.sh" 2>&1 | tee -a "$LOG"
  _R2RC="${PIPESTATUS[0]:-0}"
  if [ "$_R2RC" -ne 0 ]; then
    echo "⚠ r2_upload_async.sh 同步模式退出码 $_R2RC(失败/超时告警已由脚本自身负责)" | tee -a "$LOG"
  fi
  unset _R2RC
else
  # 异步触发(默认): 云上 systemd transient service(独立 cgroup, deploy 退出不清理); 本地 nohup fallback。
  # async 持 /tmp/trade_r2_upload_async.lock(--block-timeout 默认 600s, 2026-10-04 ③ 取代原 --nb):
  # 并发触发(多 pipeline deploy 并发/force 重跑)先有界等待; 锁在界内释放则继续(幂等增量);
  # 超界才跳过+留痕(r2_upload_skip_notify.sh 写并发跳过标记, 在跑实例收尾增量补跑数据通道一次),
  # 保证「某交易日数据因 async 跳过」同日内补上 R2, 不拖到下一趟 deploy。
  # 锁跳过留痕(2026-10-04 P1 修 review F1): DEPLOY_LOG env 传给 async, async 被跳过时
  # r2_upload_skip_notify.sh 往本 deploy 日志写显式一行 + 落 latest.md + 写并发跳过标记(不再只进 journal)。
  if command -v systemd-run >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
    sudo -n systemd-run --collect --unit="r2-upload-$(date +%H%M%S)" \
      --uid="$(id -u)" --gid="$(id -g)" \
      --setenv=REPO="$REPO" --setenv=GIT_REPO="$GIT_REPO" --setenv=DEPLOY_LOG="$LOG" \
      bash "$GIT_REPO/scripts/r2_upload_async.sh" 2>&1 | tee -a "$LOG"
    # 无 pipefail 下管道退出码=tee(恒 0), 必须取 PIPESTATUS[0] 判 systemd-run 真实成败(同 staticdata 改1 C-4)。
    _R2RC="${PIPESTATUS[0]:-0}"
    if [ "$_R2RC" -ne 0 ]; then
      # C-1(2026-09-25 实测): 云上 deploy 调用方 unit KillMode=control-group, deploy 退出时
      # systemd 连带杀同 cgroup 的 nohup 子进程 → nohup 兜底不可靠, 不加, 走 alert-only。
      echo "⚠ R2 上传异步触发失败(systemd-run rc=$_R2RC), 需手动补跑: REPO=$REPO GIT_REPO=$GIT_REPO bash $GIT_REPO/scripts/r2_upload_async.sh" | tee -a "$LOG"
      "$PY" "$REPO/scripts/notify.py" "[告警] R2上传异步触发失败" \
        "deploy 触发 R2 上传异步任务失败(systemd-run rc=$_R2RC), R2 数据可能停摆。<br>需手动补跑(云上直接粘贴执行): REPO=$REPO GIT_REPO=$GIT_REPO bash $GIT_REPO/scripts/r2_upload_async.sh<br>日志: $LOG" \
        --severe --from-prefix "[告警]" --alert-issue "R2上传异步触发失败" --alert-log "$LOG" \
        --dedup-key r2_upload_trigger_fail --dedup-window 1800 2>&1 | tee -a "$LOG" || true
    fi
    unset _R2RC
  elif [ -d /run/systemd/system ]; then
    # 有 systemd 在跑(Linux, /run/systemd/system 存在)但 sudo -n 不可用 → 走 alert-only, 不加 nohup
    # (C-1: 同 cgroup nohup 子进程随 deploy 退出被连带杀)。
    echo "⚠ R2 上传异步触发失败(systemd-run 不可用但 systemd 在跑), 需手动补跑: REPO=$REPO GIT_REPO=$GIT_REPO bash $GIT_REPO/scripts/r2_upload_async.sh" | tee -a "$LOG"
    "$PY" "$REPO/scripts/notify.py" "[告警] R2上传异步触发失败" \
      "deploy 触发 R2 上传异步任务失败(systemd-run 不可用但 systemd 在跑), R2 数据可能停摆。<br>需手动补跑(云上直接粘贴执行): REPO=$REPO GIT_REPO=$GIT_REPO bash $GIT_REPO/scripts/r2_upload_async.sh<br>日志: $LOG" \
      --severe --from-prefix "[告警]" --alert-issue "R2上传异步触发失败" --alert-log "$LOG" \
      --dedup-key r2_upload_trigger_fail --dedup-window 1800 2>&1 | tee -a "$LOG" || true
  else
    # 无 systemd(本地 mac 开发): nohup 脱离 SIGHUP 后台跑(尽力而为; macOS 无 setsid 命令, 不依赖它)。
    # async 本体日志独立写 data/logs/r2_upload_async_*.log, 此处追加一份到 deploy LOG 便于追踪。
    # DEPLOY_LOG env 同时传给 async(锁跳过留痕用, 见上方 F1 注释)。
    DEPLOY_LOG="$LOG" nohup bash "$GIT_REPO/scripts/r2_upload_async.sh" >> "$LOG" 2>&1 &
    echo "  → R2 上传已后台触发(nohup fallback, 非 systemd 环境)" | tee -a "$LOG"
  fi
fi

# 1.10 防再犯机制 A/B：版本串倒退哨兵 + merge 净回退校验（2026-08-18）
# 背景（docs/conflict-overwrite-rootcause-2026-08-18.md）：bf8841966(四档收窄,a350)被 e3fa985c3
# (首页要闻,旧base,a349)静默覆盖，merge 无冲突静默吃掉 app.js 改动，最早可见信号=版本串 a350→a349 倒退，
# 但无任何环节校验。本步在 push main 之前（安全网阶段）校验：
#   A. 版本串必须 ≥ 最近 first-parent 链天花板（倒退=大概率旧base提交,可能静默覆盖最近改动）
#   B. 版本串未前进且内容净回退到历史旧 commit = 静默回退
# 任一 FAIL → 非0退出阻断上线（§23.11 发现问题绝不静默吞掉）。
echo "-> 运行 check_version_progress.py 版本串倒退/净回退校验（防再犯机制 A/B）..." | tee -a "$LOG"
"$PY" "$REPO/scripts/check_version_progress.py" --site-dir "$GIT_REPO/static-site" --repo "$GIT_REPO" --deploy-mode 2>&1 | tee -a "$LOG"
PROG_RC=${PIPESTATUS[0]}
if [ "$PROG_RC" -ne 0 ]; then
  echo "✗ 版本串倒退/净回退校验失败(退出码 $PROG_RC)，终止部署(防再犯机制 A/B FAIL 阻断上线, 2026-08-18 §23.11)" | tee -a "$LOG"
  exit "$PROG_RC"
fi
echo "✓ 版本串倒退/净回退校验通过（防再犯机制 A/B）" | tee -a "$LOG"

# #149 方案①a: 段1 完成 → 重入持锁只跑 git 段(段2)。
# 传状态给重入进程: DEPLOY_MAP_STALE(board_etf_map 旧版兜底标志)。R2 上传已异步化(2026-10-04 P1),
# 不再有 R2_FAIL 累积(R2 失败告警由 scripts/r2_upload_async.sh 自身负责, 见其收尾 verify-channels 段)。
# async/sync 的 git 段已持同一把 trade_deploy.lock, deploy 段2 与它们同队列串行(秒~分钟级),
# 彻底消除「export+R2 长跑段占锁」#149 根因。LOG 经重入整脚本重跑沿用同一文件(顶部重新定义)。
export DEPLOY_MAP_STALE="${MAP_STALE:-0}"
exec "$PY" "$GIT_REPO/scripts/with_lock.py" --block-timeout "${GIT_LOCK_TIMEOUT:-3600}" "$LOCK" bash "$0" --git-phase "$@"
fi

# === 段2: git add/commit/push + 收尾(重入进程, 已持 /tmp/trade_deploy.lock) ===
# 重入进程整脚本重跑, 段1 被上方 if 跳过(true 分支为空); 此处恢复段1 累积状态。
MAP_STALE="${DEPLOY_MAP_STALE:-0}"
echo "=== deploy.sh 段2(锁内 git add/commit/push)开始 $(date '+%Y-%m-%d %H:%M:%S') ===" | tee -a "$LOG"

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
  # ⚠ macOS 系统 bash 3.2 + set -u 下, $VAR 后紧跟多字节字符(如全角括号)会把其首字节
  #   吞进变量名 → "VAR）: unbound variable" 报错文案本身崩掉(2026-08-25 实测复现,
  #   /bin/bash 3.2.57 最小用例 echo "$X）" rc=127)。变量一律加 {} 显式边界。
  echo "✗ deploy 必须在 main 分支跑（当前分支: ${CUR_BRANCH}）" | tee -a "$LOG"
  echo "  请先切回 main 再跑 deploy，避免把 ${CUR_BRANCH} 分支 commit 带上 main" | tee -a "$LOG"
  exit 1
fi
echo "→ git push（分支校验通过: main）..." | tee -a "$LOG"
git_push_timeout "${GIT_PUSH_TIMEOUT:-120}"
# push rc：0=成功 / 124=超时 / 其他=失败；超时已在函数内 kill git+ssh 释放 deploy.lock
PUSH_RC=$?
if [ "$PUSH_RC" -ne 0 ]; then
  # 可能是并发竞争 non-fast-forward：fetch 后确认 HEAD 是否已被推到 origin/main
  # 同 L70 超时保护：避免此处 fetch 卡 GitHub 22 端口死拽 deploy.lock
  git_fetch_timeout "${GIT_FETCH_TIMEOUT:-120}" || echo "⚠ push 重试路径 git fetch 未成功（rc=$?），用本地 origin/main ref 判断" | tee -a "$LOG"
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
      git_push_timeout "${GIT_PUSH_TIMEOUT:-120}"
      PUSH_RC=$?
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
            git_push_timeout "${GIT_PUSH_TIMEOUT:-120}"
            PUSH_RC=$?
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

# === staticdata 备份（异步触发，2026-09-25 pending #110 主链有界化）===
# 灾备第2层：每次 deploy 后 commit+push 差异化日志到 staticdata git 仓库。
# 原实现同步跑在 deploy 主链上, 实测 31-35min(9-24 占主链 ~50%)/固定开销 ~20min(9-25 只变
# 58 文件仍 22min), 是 update_all 主链最大耗时单点 → 拆出主链异步执行: 本段仅触发 + 立即返回,
# 备份本体见 scripts/staticdata_backup_async.sh(含云上路径回退/积压超阈值跳过 commit 兜底/
# 失败 notify --severe 告警/step 打点, 不静默)。deploy 全部调用方(update_all/etf_national_team_
# backfill/futures_backfill/public_fund_daily/lhb_backfill/rzhb_backfill/public_fund_full/
# public_fund_quarterly 等)零改动全覆盖。
# 云上走 systemd transient service(独立 cgroup, deploy 退出不清理); 触发失败/有 systemd 在跑
# 一律 alert-only(C-1 实测 KillMode=control-group 下 nohup 子进程随 deploy 退出被连带杀, 不加 nohup),
# 告警 + 补全 env 的手动补跑提示(改1 C-4); 本地无 systemd(mac) → nohup fallback。
# async 持 /tmp/trade_deploy.lock 阻塞: 本段触发时锁仍被 deploy 持有 → async 等到 deploy 退出
# (秒级)再开跑, 零并发写 staticdata git 仓库; 多次触发 → with_lock 排队, 不并发堆叠。
echo "-> 触发 staticdata 备份(异步, 拆出主链等待区间)..." | tee -a "$LOG"
if command -v systemd-run >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
  sudo -n systemd-run --collect --unit="staticdata-backup-$(date +%H%M%S)" \
    --uid="$(id -u)" --gid="$(id -g)" \
    --setenv=REPO="$REPO" --setenv=GIT_REPO="$GIT_REPO" \
    bash "$GIT_REPO/scripts/staticdata_backup_async.sh" "$NAME" 2>&1 | tee -a "$LOG"
  # 无 pipefail 下管道退出码=tee(恒 0), 必须取 PIPESTATUS[0] 判 systemd-run 真实成败(改1 C-4)。
  _SDRUN_RC="${PIPESTATUS[0]:-0}"
  if [ "$_SDRUN_RC" -ne 0 ]; then
    # C-1(2026-09-25 实测): 云上 deploy 调用方 unit KillMode=control-group, deploy 退出时
    # systemd 连带杀同 cgroup 的 nohup 子进程 → nohup 兜底不可靠, 不加, 走 alert-only。
    # C-4: 手动补跑提示补全 env(REPO/GIT_REPO), 云上可直接粘贴执行。
    echo "⚠ staticdata 备份异步触发失败(systemd-run rc=$_SDRUN_RC), 需手动补跑: REPO=$REPO GIT_REPO=$GIT_REPO bash $GIT_REPO/scripts/staticdata_backup_async.sh $NAME" | tee -a "$LOG"
    "$PY" "$REPO/scripts/notify.py" "[告警] staticdata备份异步触发失败" \
      "deploy 触发 staticdata 备份异步任务失败(systemd-run rc=$_SDRUN_RC), 备份可能停摆。<br>需手动补跑(云上直接粘贴执行): REPO=$REPO GIT_REPO=$GIT_REPO bash $GIT_REPO/scripts/staticdata_backup_async.sh $NAME<br>日志: $LOG" \
      --severe --from-prefix "[告警]" --alert-issue "staticdata备份异步触发失败" --alert-log "$LOG" \
      --dedup-key staticdata_backup_trigger_fail --dedup-window 1800 2>&1 | tee -a "$LOG" || true
  fi
else
  # C-1(2026-09-25 实测): 云上 deploy 调用方 unit KillMode=control-group, deploy 退出时 systemd
  # 连带杀同 cgroup 的 nohup 子进程 → 有 systemd 在跑(Linux, /run/systemd/system 存在)的环境
  # 不加 nohup, 走 alert-only(云上 sudo -n 不可用时 /run/systemd/system 仍在 → 正确落入本层);
  # 无 systemd(本地 mac 开发)的 nohup 脱离 SIGHUP 是可靠的, 恢复 nohup fallback 不发告警
  # (防本地每次跑 deploy.sh 都发 --severe 刷屏)。
  if [ -d /run/systemd/system ]; then
    echo "⚠ staticdata 备份异步触发失败(systemd-run 不可用但 systemd 在跑), 需手动补跑: REPO=$REPO GIT_REPO=$GIT_REPO bash $GIT_REPO/scripts/staticdata_backup_async.sh $NAME" | tee -a "$LOG"
    "$PY" "$REPO/scripts/notify.py" "[告警] staticdata备份异步触发失败" \
      "deploy 触发 staticdata 备份异步任务失败(systemd-run 不可用但 systemd 在跑), 备份可能停摆。<br>需手动补跑(云上直接粘贴执行): REPO=$REPO GIT_REPO=$GIT_REPO bash $GIT_REPO/scripts/staticdata_backup_async.sh $NAME<br>日志: $LOG" \
      --severe --from-prefix "[告警]" --alert-issue "staticdata备份异步触发失败" --alert-log "$LOG" \
      --dedup-key staticdata_backup_trigger_fail --dedup-window 1800 2>&1 | tee -a "$LOG" || true
  else
    # 无 systemd(本地开发): nohup 脱离 SIGHUP 后台跑(尽力而为; macOS 无 setsid 命令, 不依赖它)
    nohup bash "$GIT_REPO/scripts/staticdata_backup_async.sh" "$NAME" >> "$LOG" 2>&1 &
    echo "  → staticdata 备份已后台触发(nohup fallback, 非 systemd 环境)" | tee -a "$LOG"
  fi
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

# === R2 上传失败告警(2026-10-04 P1 已随异步化迁出) ===
# R2 上传已拆出主链异步(scripts/r2_upload_async.sh), 失败告警由该脚本自身收尾统一负责
# (verify-channels 轻量对账→真缺口才 --severe, 2026-09-11 噪音根治同款逻辑保留在 async
# 脚本内; async 不传 --alert-issue, latest.md 由 L46④ 的 send(severe=True) 自动镜像登记,
# 无需重复覆盖写——注释与 r2_upload_async.sh 实际调用参数一致)。deploy.sh 段2 不再有
# R2_FAIL 状态与告警块, 只留 board_etf_map 兜底告警。

# === board_etf_map 旧版兜底告警(收尾段, 2026-09-22 F1) ===
# build_board_etf_map.py 失败时已降级为「恢复旧版 + SKIP_MAP_SYNC=1」继续其余产物(deploy 整体 rc=0),
# 但告警通道此前静默——akshare 反爬/构建持续失败时, deploy 每天照跑旧版 map 却无人知情。
# 此处延迟到收尾发(走到这里=deploy 整体成功), 带 --dedup-key 防 akshare 反爬持续时每次 deploy 轰炸。
# 不影响 exit 0 与其余产物生成(纯告警)。
if [ "$MAP_STALE" -eq 1 ]; then
  echo "⚠ board_etf_map 用旧版兜底(build_board_etf_map.py 失败), 收尾统一告警" | tee -a "$LOG"
  "$PY" "$REPO/scripts/notify.py" "[告警] board_etf_map 旧版兜底" "deploy.sh build_board_etf_map.py 构建失败(14 宽基校验未过/东财+新浪+腾讯行情源均失败), board_etf_map 已用旧版兜底, deploy 其余产物照常生成(rc=0)。<br>旧版兜底期间前端 ETF 联动 tag 可能落后, 需人工核查行情数据源(东财 fund_etf_spot_em 被反爬 + 新浪/腾讯兜底均失败? / build 脚本): 脚本: $REPO/scripts/build_board_etf_map.py<br>日志: $LOG" --severe --from-prefix "[告警]" --dedup-key board_etf_map_stale --dedup-window 21600 2>&1 | tee -a "$LOG" || true
fi

echo "=== deploy.sh 结束 $(date '+%Y-%m-%d %H:%M:%S') 退出码=0 ===" | tee -a "$LOG"
exit 0
