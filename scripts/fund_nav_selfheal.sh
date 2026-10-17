#!/usr/bin/env bash
# fund_nav_selfheal.sh — nav_bucket「DB 领先产物」自愈（deploy 过闸失败后的补救步，2026-10-13）
#
# 背景（根因全文: docs/ops/stale-navbucket-rootcause-20261013.md）:
#   nav_bucket 256 桶产物**一天只在 17:50 update_all 重出一次**（update_all.sh L101-107），
#   其余带 deploy 的链（public_fund_daily 16:30/17:00、backfill 16:35/21:00/02:00、
#   us_stock_morning 05:00、public_fund_full 22:00）只过闸**不重出**。一旦 DB 被改新
#   （当日采集写库 / 手工修复 / #251 回填）而产物未重出，到次日 17:50 之间**每个** deploy 的
#   fund_nav 校验必 FAIL ⇒ 「终止部署(4 类事故拦截)」+ severe 告警（10-12 22:41 修复 →
#   10-13 17:50 之间窗口长达约 19 小时，10-13 全天 deploy 全被掐死）。
#
# 自愈语义（只治「时序领先」，不治数据破损）:
#   探针判定方向为「DB 领先产物」 ⇒ 重出 nav_bucket（同源用更全的 DB 重建，数据只增不减）
#   ⇒ 增量重传 R2 变更桶（异步）⇒ 交调用方重跑校验定生死。
#   **反方向（DB 落后产物）绝不重出**：产物比 DB 新时重出 = 用坏数据覆盖好数据，会把真故障
#   洗成 PASS（掩盖而非自愈），必须照旧 FAIL 阻断。
#
# 退出码（调用方 deploy.sh 按此分支）:
#   0  = 已重出产物（重出命令 rc=0；R2 异步重传已触发）→ 调用方**必须重跑校验**定生死
#   10 = 未命中（非「DB 领先产物」方向），无需自愈
#   11 = 跳过：当前时刻落在 17:50 update_all 窗口内（§14 避撞）
#   12 = 命中但重出失败/超时（上界=1 次，不做第二次）→ 调用方走原终止逻辑
#   13 = dry-run：命中但按计划未执行
#   2  = 环境/探针异常（FATAL）
#
# 硬约束（2026-10-13 派单）:
#   ① **不放宽阻断语义** —— 重跑仍 FAIL 由 deploy.sh 原逻辑终止部署 + 告警（用户拍板保留）
#   ② 复用 scripts/with_lock.py 进程互斥（并发 deploy 段1 可并发，防两实例同时全量重出打 IO）
#      + 临近 17:50 update_all 窗口跳过（FUNDNAV_SELFHEAL_SKIP_BEGIN/END，默认 17:25-18:35）
#   ③ 上界：最多重出 1 次（本脚本天然一次）+ 单次**工作段**超时 FUNDNAV_SELFHEAL_TIMEOUT
#      （默认 900s；等锁段另计 FUNDNAV_SELFHEAL_LOCK_WAIT 默认 300s，见 #258 A2）
#   ④ 爆炸半径最小：只碰 nav_bucket（export_fund_nav + nav_bucket rsync + upload-fund-nav），
#      **绝不重出其它产物**（其它产物 deploy 链自己每日重出，无此窗口）
#
# #258 A2 (2026-10-17): 步骤③重出段的**计时口径**修正（与 #258 A1/E1 同族）。
#   病灶: 旧写法 `regen_with_timeout "$TIMEOUT"(=900) … with_lock.py --block-timeout 300 …`
#   量的是「进程启动→结束」整段墙钟（**含排队等锁**）；撞上并发实例长持锁时
#   「等锁 300s + 工作 620s」就已逼近 900s，等锁吃掉工作预算。
#   修法: 预算拆两段各自独立计时 —— 等锁段 = with_lock.py `--block-timeout $LOCK_WAIT_BUDGET`
#   （默认 300，口径未变，仍优雅跳过 exit 0）；工作段 = with_lock.py `--exec-timeout $TIMEOUT`
#   （默认 900，**未放宽**，计时起点 = 真正拿到锁之后，在 with_lock.py 进程内计时）。
#   shell 侧 `regen_with_timeout` 保留为**外层兜底** = 等锁 + 工作 + 60 余量（只兜
#   「内层计时器生效之前」的窗口），与 #258 A1/E1 口径对齐（内层 < 外层留梯度）。
#
# 测试注入（**仅供测试，生产禁设**；见 scripts/tests/test_fundnav_selfheal_dbday_20261013.py）:
#   FUNDNAV_SELFHEAL_NOW=HHMM         覆盖当前时刻（窗口判定用，免等真实时钟）
#   FUNDNAV_SELFHEAL_LOCK_WAIT=N      覆盖**等锁段**预算（默认 300s，with_lock --block-timeout）
#   FUNDNAV_SELFHEAL_EXPORT_CMD=...   覆盖重出命令（默认 $PY scripts/export_fund_nav.py）
#   FUNDNAV_SELFHEAL_ASYNC_UPLOAD=0   关闭 R2 异步重传（**自测必须设 0**，防真上传）
#   FUNDNAV_SELFHEAL_DRY_RUN=1        只探针+打印计划，不重出/不同步/不上传
#   FUNDNAV_SELFHEAL_DISABLE=1        总开关(生产止血/恢复用): 直接 exit 10(等价未命中)
set -u

source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/lib/repo_paths.sh" || { echo "FATAL: repo_paths.sh missing" >&2; exit 2; }
resolve_repo "${BASH_SOURCE[0]}"
export REPO GIT_REPO
PY="$REPO/.venv/bin/python"
CHECK="$REPO/scripts/check_data_integrity.py"
DATA_DIR="$REPO/static-site/data"
LOCK="${FUNDNAV_SELFHEAL_LOCK:-/tmp/trade_fund_nav_export.lock}"

NOW_HHMM="${FUNDNAV_SELFHEAL_NOW:-$(date +%H%M)}"
SKIP_BEGIN="${FUNDNAV_SELFHEAL_SKIP_BEGIN:-1725}"   # 17:25
SKIP_END="${FUNDNAV_SELFHEAL_SKIP_END:-1835}"       # 18:35
TIMEOUT="${FUNDNAV_SELFHEAL_TIMEOUT:-900}"          # 单次重出**工作段**超时 15min(计时起点=拿锁之后)
# #258 A2: 步骤③预算拆两段(口径与 #258 A1/E1 同款, 见文件头 #258 A2 段)。
#   等锁段 = with_lock.py --block-timeout(默认 300, 口径未变, 超界仍优雅跳过 exit 0);
#   工作段 = with_lock.py --exec-timeout(= TIMEOUT, 默认 900 **未放宽**, 计时起点 = 拿锁之后)。
#   shell 侧 regen_with_timeout 保留为**外层兜底** = 等锁 + 工作 + 60 余量(只兜内层计时器
#   生效之前 / 内层自身异常未退出的窗口), 满足「内层 < 外层留梯度」。
LOCK_WAIT_BUDGET="${FUNDNAV_SELFHEAL_LOCK_WAIT:-300}"
for _v in "$LOCK_WAIT_BUDGET" "$TIMEOUT"; do
  case "$_v" in
    ''|*[!0-9]*) echo "✗ FATAL: fund_nav_selfheal 预算需为非负整数(等锁=$LOCK_WAIT_BUDGET 工作=$TIMEOUT)" >&2; exit 2 ;;
  esac
done
SHELL_LIMIT=$((LOCK_WAIT_BUDGET + TIMEOUT + 60))
DRY_RUN="${FUNDNAV_SELFHEAL_DRY_RUN:-0}"
ASYNC_UPLOAD="${FUNDNAV_SELFHEAL_ASYNC_UPLOAD:-1}"

echo "=== fund_nav_selfheal 开始 $(date '+%Y-%m-%d %H:%M:%S') ==="
echo "  REPO=$REPO GIT_REPO=$GIT_REPO now=$NOW_HHMM skip_window=[$SKIP_BEGIN,$SKIP_END] 等锁预算=${LOCK_WAIT_BUDGET}s 工作预算=${TIMEOUT}s 外层兜底=${SHELL_LIMIT}s dry_run=$DRY_RUN async_upload=$ASYNC_UPLOAD"

# ⓪ 总开关(2026-10-13 加, 止血/恢复用): FUNDNAV_SELFHEAL_DISABLE=1 ⇒ 等价「未命中」(exit 10),
#    调用方走原终止逻辑, 行为回到改动前(无需改代码/无需回滚)。恢复路径全文见
#    docs/ops/deploy-fundnav-selfheal-20261013.md「恢复路径」。
if [ "${FUNDNAV_SELFHEAL_DISABLE:-0}" = "1" ]; then
  echo "→ 自愈已由 FUNDNAV_SELFHEAL_DISABLE=1 关闭(走原终止逻辑; 见 docs/ops/deploy-fundnav-selfheal-20261013.md)"
  exit 10
fi

# ① 窗口闸：17:50 update_all 窗口内跳自愈（§14 生产稳定 P0：不与定时链撞车）
#    依据：窗口内那条链**自己**刚在 deploy 之前全量重出过产物（update_all.sh L101-107 先
#    export_fund_nav 再 L152 deploy），此刻重出 = 重复全量 + 与链内 export/异步上传撞 IO。
#    且若刚重出仍 FAIL，属「DB 破损」而非「DB 领先产物」，重出救不了（C2 第三口径会给出原因）。
#    保守取 17:25-18:35（update_all 17:50 起，链内 export~2min + deploy + 异步上传，全程 <40min）。
if [ "$NOW_HHMM" -ge "$SKIP_BEGIN" ] && [ "$NOW_HHMM" -le "$SKIP_END" ]; then
  echo "→ 跳过自愈: 当前 $NOW_HHMM 落在 17:50 update_all 窗口 [$SKIP_BEGIN,$SKIP_END] 内(§14 避撞，只告警不自愈)"
  exit 11
fi

# ② 探针：只认「DB 领先产物」方向（反方向绝不重出，见头部注释）
"$PY" "$CHECK" --fundnav-stale-probe --data-dir "$DATA_DIR"
PROBE_RC=$?
case "$PROBE_RC" in
  0)  echo "→ 未命中「DB 领先产物」，无需自愈"; exit 10 ;;
  3)  echo "→ 命中「DB 领先产物」，进入自愈" ;;
  *)  echo "✗ 探针异常 rc=${PROBE_RC}（不自愈，交调用方走原终止逻辑）"; exit 2 ;;
esac

if [ "$DRY_RUN" = "1" ]; then
  echo "[dry-run] 计划: 重出 nav_bucket(with_lock $LOCK, 等锁预算 ${LOCK_WAIT_BUDGET}s / 工作预算 ${TIMEOUT}s / 外层兜底 ${SHELL_LIMIT}s) + rsync 镜像树 + 异步重传 R2；本轮不执行"
  exit 13
fi

# ③ 重出 nav_bucket（互斥 + 两段预算，上界 1 次）
#    with_lock.py --block-timeout $LOCK_WAIT_BUDGET：并发实例（deploy 段1 可并发）先有界等锁，
#    界内释放则继续；超界优雅跳过（exit 0，不当作崩溃）。
#    with_lock.py --exec-timeout $TIMEOUT（#258 A2）：持锁**执行段**预算，计时起点 = 真正拿到锁
#    之后 ⇒ 排队等锁时长不再挤占工作预算（旧口径 bug：300s 等锁 + 620s 工作就撞外层 900s）。
#    跳过 / 失败由 ④ 复核探针 + 调用方重跑校验兜底定生死。
GEN_CMD=("$PY" "$REPO/scripts/export_fund_nav.py")
if [ -n "${FUNDNAV_SELFHEAL_EXPORT_CMD:-}" ]; then
  echo "  ⚠ 使用 FUNDNAV_SELFHEAL_EXPORT_CMD 覆盖重出命令（仅测试路径）: ${FUNDNAV_SELFHEAL_EXPORT_CMD}"
  GEN_CMD=(bash -c "${FUNDNAV_SELFHEAL_EXPORT_CMD}")
fi

regen_with_timeout() {
  local limit="$1"; shift
  local tmp_log pid slept rc
  tmp_log=$(mktemp)
  "$@" >"$tmp_log" 2>&1 &
  pid=$!
  slept=0
  rc=""
  while kill -0 "$pid" 2>/dev/null; do
    sleep 5
    slept=$((slept + 5))
    if [ "$slept" -ge "$limit" ]; then
      echo "⚠ 重出 nav_bucket 外层兜底超 ${limit}s 未退出（等锁+工作+余量；内层预算应更早触发，本条只兜内层失效），kill pid=${pid}（上界=1 次，不重试）"
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
  tail -n 20 "$tmp_log"
  rm -f "$tmp_log"
  return "$rc"
}

echo "→ 重出 nav_bucket（互斥锁 $LOCK, 等锁预算 ${LOCK_WAIT_BUDGET}s / 工作预算 ${TIMEOUT}s, 最多 1 次）..."
regen_with_timeout "$SHELL_LIMIT" "$PY" "$REPO/scripts/with_lock.py" --block-timeout "$LOCK_WAIT_BUDGET" --exec-timeout "$TIMEOUT" "$LOCK" "${GEN_CMD[@]}"
REGEN_RC=$?
if [ "$REGEN_RC" -ne 0 ]; then
  echo "✗ 自愈重出失败/超时（rc=${REGEN_RC}，上界=1 不重试）→ 交调用方走原终止逻辑"
  exit 12
fi
echo "✓ 重出完成（rc=0）"

# ④ 复核探针（重出后是否已不再「DB 领先」）。仅作日志/可观测，**不改变退出码**：
#    真值由调用方重跑完整校验定夺（探针抽样与校验抽样各自随机，任一方单独判生杀会误判）。
"$PY" "$CHECK" --fundnav-stale-probe --data-dir "$DATA_DIR"
POST_RC=$?
if [ "$POST_RC" -eq 0 ]; then
  echo "  → 复核: 探针已转 0（不再 DB 领先）"
else
  echo "  ⚠ 复核: 探针仍 rc=${POST_RC}（可能并发实例持锁/产物未变），交调用方重跑校验定夺"
fi

# ⑤ 镜像树同步（§22 三步：与 update_all 同款，单仓 no-op）。只同步 nav_bucket 子目录。
if [ "$REPO" != "$GIT_REPO" ]; then
  rsync -a --delete --checksum "$REPO/static-site/data/nav_bucket/" "$GIT_REPO/static-site/data/nav_bucket/" \
    || echo "⚠ nav_bucket rsync 到镜像树失败（不影响 R2 上传源=REPO 树，deploy 后续 rsync 会再试）"
fi

# ⑥ R2 增量重传（异步；关闭开关供自测/排障）
if [ "$ASYNC_UPLOAD" = "0" ]; then
  echo "→ R2 异步重传已关闭（FUNDNAV_SELFHEAL_ASYNC_UPLOAD=0），跳过"
else
  echo "→ 触发 fund-nav R2 增量重传（异步）..."
  if command -v systemd-run >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
    sudo -n systemd-run --collect --unit="fund-nav-selfheal-$(date +%H%M%S)" \
      --uid="$(id -u)" --gid="$(id -g)" \
      --setenv=REPO="$REPO" --setenv=GIT_REPO="$GIT_REPO" \
      bash "$REPO/scripts/fund_nav_upload_async.sh" || \
      echo "⚠ 自愈后异步重传触发失败(systemd-run)，需手动补跑: cd $REPO && python scripts/upload_r2.py upload-fund-nav"
  else
    # 无 systemd（本地开发）: nohup 尽力而为。云上 deploy 调用方 unit KillMode=control-group 会
    # 连带杀同 cgroup 的 nohup 子进程（update_all 同款结论），云上走 systemd-run 分支，不依赖本支。
    nohup bash "$REPO/scripts/fund_nav_upload_async.sh" >>"$REPO/data/logs/fund_nav_selfheal_upload.log" 2>&1 &
    echo "  → 异步重传已后台触发（nohup fallback，非 systemd 环境）"
  fi
fi

echo "=== fund_nav_selfheal 完成 $(date '+%Y-%m-%d %H:%M:%S')（产物已重出，请调用方重跑校验）==="
exit 0