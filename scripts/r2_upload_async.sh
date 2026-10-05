#!/usr/bin/env bash
# r2_upload_async.sh — 全量 R2 上传异步任务(2026-10-04 P1 主链有界化, 照 fund_nav_upload_async.sh 形态)
#
# 背景: deploy.sh 段1 的 R2 上传 17 条通道逐条串行(看门狗 900~7200s)阻塞主链:
#   10-04 update_all 段1(export+R2+rsync)10007s=2h48m 里 R2 上传占大头; 09-20 更达 10754s≈3h。
#   一次 R2 故障/周日 force_full 全量+verify-r2 ~3 万 key 对账, 能把整条 deploy 链压 2.8h。
#   P1 方案 = 上传拆出主链异步(systemd transient service 独立 cgroup, deploy 退出不清理),
#   主链不再被 R2 阻塞; 数据上线允许延迟 ≤1~2h(下一趟 deploy 的 R2 增量 + verify-r2 对账兜底)。
#
# 本脚本即异步上传本体(deploy.sh 触发; 云上 systemd-run / 本地 nohup fallback):
#   - 通道集合 + 看门狗估算 + 失败处理, 与 deploy.sh 原 R2 段完全一致(本脚本是唯一落点,
#     deploy.sh 不再串行跑 R2, 只触发本脚本)。可回退: R2_ASYNC_UPLOAD=0 时 deploy.sh 同步
#     跑本脚本(等同旧行为阻塞主链)。
#   - 失败必须告警(不静默): 先 verify-channels 轻量对账(2026-09-21 降噪) → 真缺口才 notify
#     --severe(不传 --alert-issue: latest.md 由 L46④ 的 send(severe=True) 自动镜像登记),
#     沿用现有告警链让 schedule_monitor 发现。
#   - 幂等: upload_r2.py 增量指纹(整文件 md5)+ checkpoint 断点续传, 重复跑安全; 并发触发由
#     with_lock --block-timeout 有界等待(防重复 PUT 放大 9 月 Class A 超免费额度事故): 锁在界内
#     释放则继续; 超界才跳过+留痕(r2_upload_skip_notify.sh 写并发跳过标记, 在跑实例收尾增量补跑,
#     消灭「某交易日数据因 async 跳过拖到下一趟 deploy」——2026-10-04 ③ 需求)。
#   - 周日 weekday==6 force_full 全量上传(漂移防护, 刻意设计)保留: 运行日=周日即全量,
#     本脚本不取消、不改为增量, 只改执行方式/时机。
#
# 日志: $REPO/data/logs/r2_upload_async_YYYYMMDD_HHMMSS.log
# 用法: 由 deploy.sh 自动触发; 也可手动: REPO=... GIT_REPO=... bash scripts/r2_upload_async.sh
set -u
# 不 set -e: 每通道显式判退出码, 失败累积 R2_FAIL 走收尾统一告警(与 deploy.sh 同款)。

REPO="${REPO:-/Users/linhuichen/code/trade-data}"
GIT_REPO="${GIT_REPO:-/Users/linhuichen/code/trade}"
PY="$REPO/.venv/bin/python"

# 进程互斥: 同日内重复触发(多 pipeline deploy 并发/force 重跑)不并发上传。
# 2026-10-04 ③ 有界等待取代整批跳过(--nb): 锁被占 = 另一 async 在跑, 等它在界内释放则继续
# (幂等增量, 直接传当前本地文件含更新 export); 超界才跳过+留痕(r2_upload_skip_notify.sh 写并发
# 跳过标记), 在跑实例收尾检测到标记增量补跑一次数据通道 —— 既保主链不被阻塞(async 脱离主链),
# 又消灭「某交易日数据因 async 跳过直到下一趟 deploy 才上 R2」(多趟 deploy 落同一 async 窗口时,
# 后到那趟的 export 可能在跑实例已传过的通道后落地 = 真缺口, 非纯去重)。等待有界
# (ASYNC_LOCK_WAIT_SEC 默认 600s), 不无限阻塞。用 with_lock.py(fcntl, mac/linux 通用,
# 同 fund_nav_upload_async); 钩子 r2_upload_skip_notify.sh 在跳过时留痕三处(deploy 日志
# DEPLOY_LOG env + data/logs/r2_upload_async_skip.log + latest.md, 正常降级不轰炸不发 --severe)。
if [ -z "${R2_UPLOAD_ASYNC_LOCKED:-}" ]; then
  exec "$PY" "$REPO/scripts/with_lock.py" \
    --block-timeout "${ASYNC_LOCK_WAIT_SEC:-600}" \
    --on-timeout "$REPO/scripts/r2_upload_skip_notify.sh" \
    /tmp/trade_r2_upload_async.lock \
    env R2_UPLOAD_ASYNC_LOCKED=1 bash "$0" "$@"
fi

LOG="$REPO/data/logs/r2_upload_async_$(date +%Y%m%d_%H%M%S).log"
mkdir -p "$(dirname "$LOG")"
echo "=== r2_upload_async 开始 $(date '+%Y-%m-%d %H:%M:%S') ===" | tee -a "$LOG"
echo "REPO=$REPO GIT_REPO=$GIT_REPO" | tee -a "$LOG"

# 被看门狗超时 kill 的通道记录(#177 解静音: verify-channels 收尾对账时对这些通道保留告警,
# 不适用轻量对账静音——该通道本轮从未真正完成上传, 死循环下 R2 可能静默陈旧)。
R2_KILLED=""

# 加载 .env(PURGE_SECRET 等 Worker 凭证)到环境, 确保手动跑时子进程(upload_r2.py)能读
# PURGE_SECRET 调 /api/purge-cache 清 edge cache(与 deploy.sh 同款, 防手动触发丢凭证致 purge 失败)。
set -a
[ -f "$GIT_REPO/.env" ] && . "$GIT_REPO/.env"
[ -f "$REPO/.env" ] && . "$REPO/.env"
set +a

# ---- 看门狗换代(#174, 2026-10-05): 总存活时长判据废弃 -> 停滞判据(主)+ 低速判据(辅)+ 7200s 硬兜底 ----
# 业界(rclone --timeout / rsync --timeout / curl --speed-limit / systemd WatchdogSec)全按
# 「IO 停滞/无进展」判死, 不按「进程活了多久」—— 健康全量(如 1718 key 备份)只要日志在推进
# 就放行, 不被总时长误杀(根因: _backup_overwritten_keys 串行备份 ~2200s 被显式 900s 误杀 → 死循环)。
# 显式 ch_timeout(900/1800/7200)仅保留参数接口兼容调用点(必须从参数剥离数字, 否则会当子命令
# 传进 upload_r2.py), 不再作 kill 判据。upload_r2.py 打印的 R2_BYTES_TOTAL 估算行不再被消费。
_fmt_mtime() {
  # 文件 mtime 秒值(epoch): Linux stat -c %Y / macOS stat -f %m 兼容。失败回退 0。
  if stat -c %Y "$1" 2>/dev/null; then
    return 0
  fi
  stat -f %m "$1" 2>/dev/null || echo 0
  return 0
}

run_r2_upload() {
  local desc="$1"; shift
  local ch_timeout=""
  if [[ "${1:-}" =~ ^[0-9]+$ ]]; then
    ch_timeout="$1"; shift
  fi
  local tmp_log pid rc
  tmp_log=$(mktemp)
  "$PY" "$REPO/scripts/upload_r2.py" "$@" >"$tmp_log" 2>&1 &
  pid=$!
  # 主判据=停滞: 日志 mtime 超 N 秒(默认 300s=5min, 对齐 rclone --timeout 默认)无新增输出即判死。
  local _stall_secs="${R2_UPLOAD_STALL_SECS:-300}"
  local _last_mtime _now _slept _cur_mtime
  _last_mtime=$(_fmt_mtime "$tmp_log")
  _slept=0
  # 辅判据=低速: 每 60s 采样日志已传字节(形如 (12345B)), 近 5 分钟(连续 5 次采样)增量 < 1MB
  # 且属批量上传(total>10)即判死。小通道/对账通道(verify-r2 无 [N/M] 进度行、upload-feed 单文件)
  # 不适用, 靠停滞判据 + 7200s 硬兜底。备份阶段进度行不带 (sizeB)(看 upload_r2.py), 不会误判。
  local _batch_total=0 _upb=0 _low_last=0 _low_bad=0
  while kill -0 "$pid" 2>/dev/null; do
    sleep 5
    _slept=$((_slept + 5))
    _now=$(date +%s)
    _cur_mtime=$(_fmt_mtime "$tmp_log")
    [ "$_cur_mtime" -gt "$_last_mtime" ] && _last_mtime=$_cur_mtime
    if [ $((_now - _last_mtime)) -ge "$_stall_secs" ]; then
      echo "⚠ $desc 停滞 ${_stall_secs}s 无日志输出, kill pid=$pid" | tee -a "$LOG"
      R2_KILLED="$R2_KILLED $desc"
      kill -TERM "$pid" 2>/dev/null; sleep 2
      kill -KILL "$pid" 2>/dev/null || true
      wait "$pid" 2>/dev/null || true
      rm -f "$tmp_log"
      return 1
    fi
    if [ "$_slept" -ge 7200 ]; then
      echo "⚠ $desc 总时长超 7200s 硬兜底, kill pid=$pid" | tee -a "$LOG"
      R2_KILLED="$R2_KILLED $desc"
      kill -TERM "$pid" 2>/dev/null; sleep 2
      kill -KILL "$pid" 2>/dev/null || true
      wait "$pid" 2>/dev/null || true
      rm -f "$tmp_log"
      return 1
    fi
    if [ $((_slept % 60)) -eq 0 ]; then
      if [ "$_batch_total" -le 10 ]; then
        _batch_total=$(grep -Eo '\[[0-9]+/[0-9]+\]' "$tmp_log" 2>/dev/null | tail -1 | sed 's/.*\///; s/]//')
        [ -n "$_batch_total" ] || _batch_total=0
      fi
      _upb=$(grep -Eo '\([0-9]+B\)' "$tmp_log" 2>/dev/null | sed 's/(//; s/B)//' | awk '{s+=$1} END{print s+0}')
      if [ "$_batch_total" -gt 10 ] && [ $((_upb - _low_last)) -lt 1048576 ]; then
        _low_bad=$((_low_bad + 1))
      else
        _low_bad=0
      fi
      _low_last=$_upb
      if [ "$_low_bad" -ge 5 ]; then
        echo "⚠ $desc 低速(近5分钟字节增量<1MB), kill pid=$pid" | tee -a "$LOG"
        R2_KILLED="$R2_KILLED $desc"
        kill -TERM "$pid" 2>/dev/null; sleep 2
        kill -KILL "$pid" 2>/dev/null || true
        wait "$pid" 2>/dev/null || true
        rm -f "$tmp_log"
        return 1
      fi
    fi
  done
  wait "$pid"; rc=$?
  tail -1 "$tmp_log" | tee -a "$LOG"
  rm -f "$tmp_log"
  return "$rc"
}

echo "-> 上传 lab/trade_sim/index/industry/public_fund/etf_score/data-large/all-data/kelly-snapshots 到 R2 ..." | tee -a "$LOG"
# 阶段3：数据唯一走 R2，上传失败需 notify 告警让 schedule_monitor 发现(收尾统一告警见下方)
R2_FAIL=""

# 并发跳过标记(2026-10-04 ③): r2_upload_skip_notify.sh 在被跳过时写此文件, 本脚本(在跑实例)
# 收尾检测到 → 增量补跑数据通道一次, 覆盖被跳过那趟的新 export。单文件即可: 多次跳过只算一次,
# 补跑读取当前本地文件(含所有被跳过 export 的最新态), 幂等增量只传变化文件。
PENDING_FILE="${R2_UPLOAD_ASYNC_PENDING:-/tmp/trade_r2_upload_async.pending}"

# 数据上传通道(不含 verify-r2/purge-low-freq: 对账/清理非「新数据上线」, 补跑无需重复)。
# 初次与并发跳过补跑共用; run_r2_upload 看门狗估算口径与 deploy.sh 原 R2 段完全一致(见上)。
upload_data_channels() {
  run_r2_upload "upload-lab" 900 upload-lab || { echo "⚠ upload-lab 失败/超时,继续" | tee -a "$LOG"; R2_FAIL="$R2_FAIL upload-lab"; }
  run_r2_upload "upload-trade-sim" 900 upload-trade-sim || { echo "⚠ upload-trade-sim 失败/超时,继续" | tee -a "$LOG"; R2_FAIL="$R2_FAIL upload-trade-sim"; }
  # 2026-09-15 R2 上传增量化(设计文档 §3.5): trade-sim-json 全量 370MB@4.2Mbps=739s+连接开销,
  # 900s 周日/首跑全量偏紧(09-14 17:50 update_all exit 143 事故根因之一), 放宽 1800s 留 2 倍余量(仿 fund-nav)。
  run_r2_upload "upload-trade-sim-json" 1800 upload-trade-sim-json || { echo "⚠ upload-trade-sim-json 失败/超时,继续" | tee -a "$LOG"; R2_FAIL="$R2_FAIL upload-trade-sim-json"; }
  run_r2_upload "upload-index" 900 upload-index || { echo "⚠ upload-index 失败/超时,继续" | tee -a "$LOG"; R2_FAIL="$R2_FAIL upload-index"; }
  # ETF 全史日K etf/{code}-all.json -> R2 etf/ 前缀(#10 ETF弹窗长历史, 2026-08-22; 1532只~87MB, 8线程并发)
  # 2026-08-23: 改增量上传(upload_r2.py 状态清单只传变化文件)+ 本通道超时放宽 900s(根治间歇超时告警);
  # 首跑/每周日强制全量一次防状态漂移, 增量正常秒级~分钟级完成。
  run_r2_upload "upload-etf-hist" 900 upload-etf-hist || { echo "⚠ upload-etf-hist 失败/超时,继续" | tee -a "$LOG"; R2_FAIL="$R2_FAIL upload-etf-hist"; }
  # 基金全史净值 nav_bucket/{xx}.json(256 桶) -> R2 nav_bucket/ 前缀(#11 基金弹窗净值走势, 2026-08-25;
  # 2026-09-23 桶化 §9B: PUT 次数固定 256 上传耗时有界)。
  run_r2_upload "upload-accum-nav" 900 upload-accum-nav || { echo "⚠ upload-accum-nav 失败/超时,继续" | tee -a "$LOG"; R2_FAIL="$R2_FAIL upload-accum-nav"; }
  run_r2_upload "upload-industry" 900 upload-industry || { echo "⚠ upload-industry 失败/超时,继续" | tee -a "$LOG"; R2_FAIL="$R2_FAIL upload-industry"; }
  run_r2_upload "upload-public-fund" 900 upload-public-fund || { echo "⚠ upload-public-fund 失败/超时,继续" | tee -a "$LOG"; R2_FAIL="$R2_FAIL upload-public-fund"; }
  run_r2_upload "upload-etf-score" 900 upload-etf-score || { echo "⚠ upload-etf-score 失败/超时,继续" | tee -a "$LOG"; R2_FAIL="$R2_FAIL upload-etf-score"; }
  # 2026-09-23 ③ + 2026-09-24 P2-sdc 补齐: upload-data-large / upload-kelly-parts / upload-kelly-parts-sdc
  # 改走「按字节量估算超时」(run_r2_upload 不传第二参): 9-23 21:00 backfill_evening 近全量 190MB
  # (跨境 ~150KB/s 需 950-1270s)被固定 900s 看门狗 kill → 27 个 R2 缺口。增量字节小→估算超时小。
  run_r2_upload "upload-data-large" upload-data-large || { echo "⚠ upload-data-large 失败/超时,继续" | tee -a "$LOG"; R2_FAIL="$R2_FAIL upload-data-large"; }
  run_r2_upload "upload-kelly-parts" upload-kelly-parts || { echo "⚠ upload-kelly-parts 失败/超时,继续" | tee -a "$LOG"; R2_FAIL="$R2_FAIL upload-kelly-parts"; }
  run_r2_upload "upload-kelly-parts-sdc" upload-kelly-parts-sdc || { echo "⚠ upload-kelly-parts-sdc 失败/超时,继续" | tee -a "$LOG"; R2_FAIL="$R2_FAIL upload-kelly-parts-sdc"; }
  run_r2_upload "upload-all-data" 900 upload-all-data || { echo "⚠ upload-all-data 失败/超时,继续" | tee -a "$LOG"; R2_FAIL="$R2_FAIL upload-all-data"; }
  run_r2_upload "upload-kelly-snapshots" 900 upload-kelly-snapshots || { echo "⚠ upload-kelly-snapshots 失败/超时,继续" | tee -a "$LOG"; R2_FAIL="$R2_FAIL upload-kelly-snapshots"; }
  # feed.xml 走 R2（2026-08-10）：gen_rss 生成的 RSS 上传到 R2 data/feed.xml，不再 git push
  run_r2_upload "upload-feed" 900 upload-data-files feed.xml || { echo "⚠ upload feed.xml 失败/超时,继续" | tee -a "$LOG"; R2_FAIL="$R2_FAIL upload-feed"; }
}

# 收尾统一告警(与 deploy.sh 段2 R2_FAIL 段同款, 2026-09-11 噪音根治 + 2026-09-21 verify-channels 降噪):
# 通道失败先做轻量对账(verify-channels 抽查最新关键文件 R2 HEAD vs 本地 md5/size, keep-alive 复用)。
# 对账全通过 → 普通日志不告警(噪音: 看门狗超时 kill 数据已传完); 真缺口/verify-r2 本身失败 → --severe 告警。
finalize_verify() {
  if [ -n "$R2_FAIL" ]; then
    echo "⚠ R2 上传有失败通道:$R2_FAIL (异步跑完, 收尾统一告警)" | tee -a "$LOG"
    # #177: R2_KILLED 传给 verify-channels, 被看门狗超时 kill 的通道不适用轻量对账静音, 保留告警。
    R2_KILLED="$R2_KILLED" "$PY" "$REPO/scripts/upload_r2.py" verify-channels $R2_FAIL > /tmp/r2_verify_channels_async.log 2>&1
    _vc_rc=$?
    if [ "$_vc_rc" -eq 0 ]; then
      echo "✓ R2 失败通道轻量对账通过(数据完整, 疑似看门狗超时噪音, 不告警):$R2_FAIL" | tee -a "$LOG"
    else
      echo "✗ R2 失败通道轻量对账发现缺口(verify-channels rc=$_vc_rc, 照常告警):$R2_FAIL" | tee -a "$LOG"
      _vc_tail="$(tail -8 /tmp/r2_verify_channels_async.log 2>/dev/null | sed 's/</\&lt;/g; s/>/\&gt;/g' | tr '\n' ' ')"
      "$PY" "$REPO/scripts/notify.py" "[告警] R2上传失败" "r2_upload_async.sh R2 上传部分通道失败(轻量对账确认有缺口):$R2_FAIL<br>上传已在异步任务跑完, 请人工确认失败通道文件是否已补传/需手动补刷: bash scripts/upload_r2.py upload-all-data<br>verify-channels 详情: $([ -n "$_vc_tail" ] && echo "$_vc_tail" || echo 无输出)<br>日志: $LOG" --severe --from-prefix "[告警]" --dedup-key deploy_r2_upload_fail --dedup-window 21600 2>&1 | tee -a "$LOG" || true
      unset _vc_rc _vc_tail
    fi
  fi
}

# 初次: 数据通道 + verify-r2 对账 + purge 收尾
upload_data_channels
# 2026-09-15 层3 防漏传机检(设计文档 §3.4): 周期全量对账, 周日全量+平日增量自适应。
# 2026-09-21 R2 根治: watchdog 1800→7200(周日全量 ~3万 key 逐个 HEAD + keep-alive 复用省握手)。
# 周日 force_full 全量由 upload_r2.py weekday==6 触发(漂移防护, 本脚本不取消)。
run_r2_upload "verify-r2" 7200 verify-r2 || { echo "⚠ verify-r2 失败/超时,继续" | tee -a "$LOG"; R2_FAIL="$R2_FAIL verify-r2"; }
# 末尾统一 purge 低频文件(决策清单项5+项8, 2026-08-18): 低频文件(LOW_FREQ 3600s 档) CF 会把
# max-age 拉长成 4h edge 残留, 上传时 purge 若失败/漏跑前端读最长 4h 旧版。purge 失败独立告警。
run_r2_upload "purge-low-freq" 900 purge-low-freq || {
  echo "⚠ purge-low-freq 失败/超时, 低频文件 edge cache 可能残留 4h 旧版" | tee -a "$LOG"
  "$PY" "$REPO/scripts/notify.py" "[告警] R2 末尾 purge 低频文件失败" \
    "r2_upload_async.sh 末尾统一 purge 低频文件失败(purge-low-freq 命令失败/超时)，CF edge cache 低频文件可能残留最长 4h 旧版。<br>建议手动重试: bash scripts/upload_r2.py purge-low-freq<br>日志: $LOG" \
    --severe --from-prefix "[告警]" --dedup-key deploy_purge_low_freq_fail --dedup-window 1800 2>&1 | tee -a "$LOG" || true
}
finalize_verify

# 并发跳过补跑(2026-10-04 ③): 有 async 在本次运行期间被锁跳过 → 其 export 可能含本实例
# 已传通道之后落地的新文件 → 增量补跑数据通道一次(幂等只传变化文件, 不含 verify/purge)。
# 单标记语义: 任意次跳过 = 补跑一次读当前本地文件, 覆盖全部被跳过 export 的最新态。
if [ -f "$PENDING_FILE" ]; then
  echo "→ 检测到并发跳过标记 $PENDING_FILE, 增量补跑数据通道一次(覆盖被跳过那趟的新 export)" | tee -a "$LOG"
  rm -f "$PENDING_FILE"
  upload_data_channels
  finalize_verify
fi

echo "=== r2_upload_async 结束 $(date '+%Y-%m-%d %H:%M:%S') 退出码=0 ===" | tee -a "$LOG"
exit 0
