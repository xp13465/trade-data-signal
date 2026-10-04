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
#     --severe + --alert-issue(写 data/alerts/latest.md), 沿用现有告警链让 schedule_monitor 发现。
#   - 幂等: upload_r2.py 增量指纹(整文件 md5)+ checkpoint 断点续传, 重复跑安全; 并发触发由
#     with_lock --nb 跳过(防重复 PUT 放大 9 月 Class A 超免费额度事故; 跳过=已在跑那趟负责完成)。
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

# 进程互斥: 同日内重复触发(多 pipeline deploy 并发/force 重跑)不并发上传。锁跳过=已有在跑,
# 那趟会负责完成+告警; 上传幂等+checkpoint+verify-r2 对账, 本次跳过不丢数据(下一趟 deploy 的
# R2 增量会上新 export)。用 with_lock.py --nb(fcntl, mac/linux 通用, 同 fund_nav_upload_async)。
if [ -z "${R2_UPLOAD_ASYNC_LOCKED:-}" ]; then
  exec "$PY" "$REPO/scripts/with_lock.py" --nb /tmp/trade_r2_upload_async.lock \
    env R2_UPLOAD_ASYNC_LOCKED=1 bash "$0" "$@"
fi

LOG="$REPO/data/logs/r2_upload_async_$(date +%Y%m%d_%H%M%S).log"
mkdir -p "$(dirname "$LOG")"
echo "=== r2_upload_async 开始 $(date '+%Y-%m-%d %H:%M:%S') ===" | tee -a "$LOG"
echo "REPO=$REPO GIT_REPO=$GIT_REPO" | tee -a "$LOG"

# 加载 .env(PURGE_SECRET 等 Worker 凭证)到环境, 确保手动跑时子进程(upload_r2.py)能读
# PURGE_SECRET 调 /api/purge-cache 清 edge cache(与 deploy.sh 同款, 防手动触发丢凭证致 purge 失败)。
set -a
[ -f "$GIT_REPO/.env" ] && . "$GIT_REPO/.env"
[ -f "$REPO/.env" ] && . "$REPO/.env"
set +a

# ---- 与 deploy.sh run_r2_upload 同款(唯一落点; 看门狗估算口径 150KB/s × 2 + 240s 固定开销,
# 上限 7200s; 显式通道值优先; 估算失败回退固定 900s, 2026-09-24 P2-估算回退根治) ----
run_r2_upload() {
  local desc="$1"; shift
  local ch_timeout=""
  if [[ "${1:-}" =~ ^[0-9]+$ ]]; then
    ch_timeout="$1"; shift
  fi
  local tmp_log pid slept rc
  tmp_log=$(mktemp)
  "$PY" "$REPO/scripts/upload_r2.py" "$@" >"$tmp_log" 2>&1 &
  pid=$!
  local est_limit=0 r2bytes=""
  local _i
  for _i in $(seq 1 40); do
    r2bytes=$(grep -Eo 'R2_BYTES_TOTAL=[0-9]+' "$tmp_log" 2>/dev/null | tail -1 | cut -d= -f2)
    [ -n "$r2bytes" ] && break
    if ! kill -0 "$pid" 2>/dev/null && ! grep -q "R2_BYTES_TOTAL" "$tmp_log" 2>/dev/null; then
      break  # 进程已退出且非增量命令(未打印字节量行) → 不用再空等
    fi
    sleep 0.5
  done
  if [ -n "$r2bytes" ] && [[ "$r2bytes" =~ ^[0-9]+$ ]] && [ "$r2bytes" -gt 0 ] 2>/dev/null; then
    est_limit=$(( r2bytes / 150000 * 2 + 240 ))
    est_limit=$(( est_limit > 7200 ? 7200 : est_limit ))
    est_limit=$(( est_limit < 300 ? 300 : est_limit ))
  fi
  local ch_limit
  if [ -n "$ch_timeout" ]; then
    ch_limit="$ch_timeout"
  elif [ "$est_limit" -gt 0 ]; then
    ch_limit="$est_limit"
  else
    ch_limit=900
  fi
  slept=0
  while kill -0 "$pid" 2>/dev/null; do
    sleep 5
    slept=$((slept + 5))
    if [ "$slept" -ge "$ch_limit" ]; then
      echo "⚠ $desc 超 ${ch_limit}s(估算/显式)未退出，kill pid=$pid" | tee -a "$LOG"
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

echo "-> 上传 lab/trade_sim/index/industry/public_fund/etf_score/data-large/all-data/kelly-snapshots 到 R2 ..." | tee -a "$LOG"
# 阶段3：数据唯一走 R2，上传失败需 notify 告警让 schedule_monitor 发现(收尾统一告警见下方)
R2_FAIL=""
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

# 收尾统一告警(与 deploy.sh 段2 R2_FAIL 段同款, 2026-09-11 噪音根治 + 2026-09-21 verify-channels 降噪):
# 通道失败先做轻量对账(verify-channels 抽查最新关键文件 R2 HEAD vs 本地 md5/size, keep-alive 复用)。
# 对账全通过 → 普通日志不告警(噪音: 看门狗超时 kill 数据已传完); 真缺口/verify-r2 本身失败 → --severe 告警。
if [ -n "$R2_FAIL" ]; then
  echo "⚠ R2 上传有失败通道:$R2_FAIL (异步跑完, 收尾统一告警)" | tee -a "$LOG"
  "$PY" "$REPO/scripts/upload_r2.py" verify-channels $R2_FAIL > /tmp/r2_verify_channels_async.log 2>&1
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

echo "=== r2_upload_async 结束 $(date '+%Y-%m-%d %H:%M:%S') 退出码=0 ===" | tee -a "$LOG"
exit 0
