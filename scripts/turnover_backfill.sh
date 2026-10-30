#!/usr/bin/env bash
# turnover_backfill.sh - 换手率分布独立延后任务(#82 C6, 2026-09-09, 用户已拍板)
#
# 背景: turnover pipeline(a_turnover_mean/median/p90/p10/gt5_pct 写 daily_metric, baostock
#   增量 + cleanup_d3d2 计算)是 update_all 主链最大单块(90.8min)。用户拍板摘出主链,
#   改独立 launchd 延后 1-2h 跑(21:10), update_all 主链 175→~85min(实测 112-121min)。
#   副作用自动治好: update_lab 饿死(19:00 等 update_all 5400s 放弃) + C2 告警(阈值失真)。
# 本脚本 = launchd com.trade.turnover-backfill 的包装(参照 s06_snapshot.sh 模板):
#   ①caffeinate 防睡眠 ②交易日闸门(fail-open, force 绕过) ③进程互斥(独立锁 + 锁跳过通知)
#   ④等 update_all 主链结束(最多 1800s, 防并发 baostock/DB 锁)
#   ⑤pipeline.sh turnover(RUN_BAOSTOCK=1 由 pipeline.sh 内部设, 90.8min, 超时 7200s)
#   ⑥增量重导 overview.json + a-stock-{3m,6m,1y,3y,5y,all}.json(只重写换手率相关展示文件,
#     消费链 overview() 读 daily_metric 最新非空值, 缺当日=显示 T-1 不报错)
#   ⑦upload-intraday(overview/a-stock-3m/6m/1y)+ upload-data-large(3y/5y/all)上传 R2 + purge CF
#   ⑧失败 notify --severe(--dedup-key 1h 防轰炸); 成功静默(git 渠道随次日 17:50 deploy 追上)
# 日志: data/logs/turnover_backfill_launchd.log(固定名 append, 标准开始/结束行供
#   gen_schedule_stats standard 模式与 schedule_monitor 漏跑检查直读, 同 s06_snapshot 先例)
#
# #258 A1 (2026-10-17): 步骤⑦的两个 R2 步骤(外部阻塞 = 排队等 R2 上传锁)的**计时口径**修正
#   (与 #258 E1 在 s06_snapshot.sh/upload_r2.py 同款, 报告 §5-A1「逐字同形态」)。
#   病灶: 旧写法 `run_to 900 "$PY" scripts/upload_r2.py …` 量的是「进程启动→结束」整段墙钟
#   (**含排队等锁**), 撞上长持锁者时「等锁 870s + 工作 30s」就撞 900s(rc=124): 等锁吃掉工作预算。
#   修法: 预算拆两段各自独立计时 —— 等锁段 = R2_UPLOAD_LOCK_TIMEOUT(=R2_LOCK_WAIT_BUDGET 1800,
#   超时 fail-closed exit 1); 工作段 = R2_UPLOAD_WORK_TIMEOUT(=各步工作预算, 现行 600/2400),
#   计时起点 = 真正拿到锁之后(在 upload_r2.py 进程内 arm)。shell `run_to` 保留为外层兜底
#   (现行 2460/4260, 只兜「进程内计时器生效之前」的窗口), 口径与 E1 完全对齐。
#   ⚠ 依赖: 进程内工作预算来自 upload_r2.py 的 R2_UPLOAD_WORK_TIMEOUT 读取(#258 E1 声称提供,
#     实际 #364 才真正实现); 下方反查守卫会 grep 读取代码, 缺失即 FATAL。
#   ⚠ 外层墙: 本任务 unit `trade-turnover-backfill.service` 的 TimeoutStartUSec=infinity
#     (云上实测 `systemctl show -p TimeoutStartUSec` = infinity; 快照
#     docs/deploy/systemd-units-cloud-snapshot.txt), 故真正的外层墙在 shell(run_to), 不在 systemd。
# #364(2026-10-30): 现行数值 = upload-intraday 外层 2460(工作 600) / upload-data-large 外层 4260
#   (工作 2400), 详见下方「R2 步骤预算」段与第 4 步注释(含取证)。
# 用法: bash scripts/turnover_backfill.sh [force]
set -uo pipefail

# 防脚本运行期间 mac 休眠(caffeinate 跟随脚本 PID, 退出自动结束)
if [ "$(uname -s)" = "Darwin" ]; then
    caffeinate -i -w $$ >/dev/null 2>&1 &
fi

# ⚠️ 必须 export(2026-08-26 手动裸跑事故根因): upload_r2.py 从 os.environ 读 REPO 派生
# STATIC_DIR, 只设 shell 变量不 export 时子进程读不到 → 回退 ROOT=trade 触发盘中守卫 abort。
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/lib/repo_paths.sh" || { echo "FATAL: repo_paths.sh missing" >&2; exit 2; }
resolve_repo "${BASH_SOURCE[0]}"
export REPO
export GIT_REPO
PY="${PY:-$REPO/.venv/bin/python}"
LOGDIR=$REPO/data/logs
LOG="$LOGDIR/turnover_backfill_launchd.log"
# #44 日志不可写隐患根治(同 s06_snapshot 先例): LOGDIR 不可创建/不可写或 $LOG 不可追加时,
# 非交互 bash 里 `>> "$LOG"` 重定向失败会让整条命令(含末尾 notify.py 告警)根本不执行 →
# 告警静默跳过。此处显式兜底: 落到 /tmp 保证可写的 fallback, 警告打到 stderr, 不静默吞告警。
if ! mkdir -p "$LOGDIR" 2>/dev/null || [ ! -w "$LOGDIR" ] || ! ( : >> "$LOG" ) 2>/dev/null; then
  LOG="/tmp/turnover_backfill_$(date +%s).log"
  echo "$(date '+%F %T') [turnover_backfill] 警告: 日志 $LOGDIR/turnover_backfill_launchd.log 不可写(磁盘满/权限), 改落 fallback $LOG" >&2
fi
cd "$REPO"
LOCK="/tmp/trade_turnover.lock"

# codex008 F5(P3②): 三段命令统一超时包装防挂死(macOS 无 coreutils timeout,
# fallback 链: timeout → gtimeout → perl alarm-exec)。超时按非零处理走既有 FAIL 告警链。
run_to() {
  local t="$1"
  shift
  if command -v timeout >/dev/null 2>&1; then
    timeout "$t" "$@"
  elif command -v gtimeout >/dev/null 2>&1; then
    gtimeout "$t" "$@"
  else
    perl -e 'alarm shift; exec @ARGV or exit 127' "$t" "$@"
  fi
}

# #364(2026-10-30)重定两个 R2 步骤的预算(按最坏路径复算, 见 #364 实施报告):
#   - upload-data-large 工作预算 900 → 2400。依据: 实测最坏 = 备份 1359 + 上传 665 ≈ 2024s,
#     2400 留 ~19% 余量; 且 2400 < 单文件理论最坏 3015s(5×600+15), 由 upload_r2.py 的内层
#     拦截点 a/b 在预算内打断, 不再被单文件理论值绑死。
#   - upload-data-large 外层兜底 2760 → 4260 = 等锁 1800 + 工作 2400 + 60 余量(必须写字面量:
#     梯度审计 systemd_timeout_gradient_audit.py 只认 `run_to <字面量>`)。
#   - upload-intraday 工作预算 600(= max(600, ceil(M*3)) 且 ≤1200; M = 实测纯工作耗时 ≈30–70s,
#     见 :180 一带取证注释), 外层兜底 2460 = 1800 + 600 + 60。
R2_LOCK_WAIT_BUDGET=1800
R2_WORK_BUDGET=2400
R2_WORK_BUDGET_INTRADAY=600
OUTER_LARGE=$((R2_LOCK_WAIT_BUDGET + R2_WORK_BUDGET + 60))              # 4260
OUTER_INTRADAY=$((R2_LOCK_WAIT_BUDGET + R2_WORK_BUDGET_INTRADAY + 60))  # 2460
# 梯度自检(**逐步骤各自校验**, #364): 每步的外层兜底必须严格大于「等锁 + 该步工作」,
# 否则合法等锁会被 shell 先杀 = #258/#364 倒挂原病复发。任一条倒挂 ⇒ FATAL exit 2。
if [ 4260 -le $((R2_LOCK_WAIT_BUDGET + R2_WORK_BUDGET)) ]; then
  echo "$(date '+%F %T') FATAL: upload-data-large 预算梯度倒挂(外层 4260 <= 等锁 ${R2_LOCK_WAIT_BUDGET} + 工作 ${R2_WORK_BUDGET}) —— 见 #364" >> "$LOG"
  exit 2
fi
if [ 2460 -le $((R2_LOCK_WAIT_BUDGET + R2_WORK_BUDGET_INTRADAY)) ]; then
  echo "$(date '+%F %T') FATAL: upload-intraday 预算梯度倒挂(外层 2460 <= 等锁 ${R2_LOCK_WAIT_BUDGET} + 工作 ${R2_WORK_BUDGET_INTRADAY}) —— 见 #364" >> "$LOG"
  exit 2
fi
# 算式与 run_to 字面量必须一致(改一边漏另一边 = L55 的老病): 字面量改了这里就红。
if [ "$OUTER_LARGE" -ne 4260 ] || [ "$OUTER_INTRADAY" -ne 2460 ]; then
  echo "$(date '+%F %T') FATAL: 外层兜底算式(${OUTER_LARGE}/${OUTER_INTRADAY})与 run_to 字面量(4260/2460)不一致 —— 见 #364" >> "$LOG"
  exit 2
fi
# 反查守卫(#364): 「传了 env 但 python 压根不读」正是本次事故根因, 故不再只探测"变量名出现过",
# 而是要求 upload_r2.py 里真有读取代码。缺 ⇒ FATAL(改坏了就当场停, 不让倒挂重新上线)。
if ! grep -q 'os\.environ\.get("R2_UPLOAD_WORK_TIMEOUT"' "$REPO/scripts/upload_r2.py" 2>/dev/null; then
  echo "$(date '+%F %T') FATAL: upload_r2.py 未真正读取 R2_UPLOAD_WORK_TIMEOUT(已支持, 此处为防回退守卫) —— 内层工作预算会再次失效, 见 #364" >> "$LOG"
  exit 2
fi

# 进程互斥: 自包装经 with_lock.py --nb 持独立锁重跑自己, TURNOVER_BACKFILL_LOCKED=1 防递归。
# 锁被占(上一轮还在跑/手动补跑在跑) = --on-skip 发通知 + 写标准开始/结束行(防 schedule_monitor
# 误报漏跑), 然后 exit 0 跳过本轮。手动补跑场景跳过无常(补跑数据已覆盖), 定时场景跳过=当日
# turnover 缺失, 通知让用户知道(§23.11 不静默同精神)。
if [ -z "${TURNOVER_BACKFILL_LOCKED:-}" ]; then
  exec "$PY" "$REPO/scripts/with_lock.py" --nb --on-skip "$REPO/scripts/turnover_backfill_skip_notify.sh" "$LOCK" \
    env TURNOVER_BACKFILL_LOCKED=1 bash "$0" "$@"
fi

echo "=== turnover_backfill.sh 开始 $(date '+%F %T') ===" >> "$LOG"

# 交易日闸门(同 overfit_monitor.sh; 失败 fail-open 默认跑, 防日历源异常静默停更)
if [ "${1:-}" != "force" ]; then
  IS_TRADING=$("$PY" -c "from app.calendar import is_trading_day; print(1 if is_trading_day() else 0)" 2>/dev/null || echo 1)
  if [ "$IS_TRADING" != "1" ]; then
    echo "=== turnover_backfill.sh 结束（非交易日）$(date '+%F %T') ===" >> "$LOG"
    exit 0
  fi
fi

RC_PIPE=0; RC_EXPORT=0; RC_R2=0; RC_R2L=0

# 1) 等 update_all 主链结束(摘出后主链 17:50+~115min≈19:45, 21:10 时通常已结束; 防御性等待
#    防并发 baostock 采集/DB 锁, 最多 1800s = 30min。等满仍在跑=update_all 卡死, 记录警告继续:
#    放弃本轮=当日 turnover 缺失更糟, 并发风险由 runner step try/except 兜底)
WAIT_ROUNDS=0
for _i in $(seq 1 180); do
  if ! pgrep -f "update_all\.sh" >/dev/null 2>&1; then
    break
  fi
  sleep 10
  WAIT_ROUNDS=$_i
done
echo "-> 等待 update_all 结束完成(rounds=${WAIT_ROUNDS}×10s)" >> "$LOG"

# 2) 跑 turnover pipeline(baostock 增量 + cleanup_d3d2 算 a_turnover 入 daily_metric;
#    RUN_BAOSTOCK=1 由 pipeline.sh 内部对 turnover 分支自动 export; 90.8min, 超时 7200s)
echo "-> 跑 pipeline.sh turnover(约 90min) ..." >> "$LOG"
run_to 7200 bash scripts/pipeline.sh turnover >> "$LOG" 2>&1
RC_PIPE=$?
if [ "$RC_PIPE" -ne 0 ]; then
  echo "✗ turnover pipeline 失败 rc=${RC_PIPE}" >> "$LOG"
else
  echo "✓ turnover pipeline 采集完成" >> "$LOG"
fi

# 3) 增量重导换手率相关展示文件(仅采集成功时; overview 必更白名单 + a-stock 6 range 全量重算,
#    同 export.py main 的 write_json 语义; 只写 REPO 主库树, git 渠道随次日 17:50 deploy 追上)
if [ "$RC_PIPE" -eq 0 ]; then
  echo "-> 增量重导 overview.json + a-stock-{3m,6m,1y,3y,5y,all}.json ..." >> "$LOG"
  run_to 900 "$PY" - <<'PYEOF' >> "$LOG" 2>&1
import importlib.util
import os
from pathlib import Path

ROOT = Path(os.environ["REPO"])
spec = importlib.util.spec_from_file_location("export", ROOT / "static-site" / "export.py")
export_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(export_mod)
from app.collector.fetchers import load_config
from app.db import get_conn

cfg = load_config()
conn = get_conn()
DATA_DIR = export_mod.DATA_DIR

export_mod.write_json(DATA_DIR / "overview.json", export_mod.export_overview(conn, cfg))
print("  overview.json 重导完成")
for _rng in export_mod.EXPORT_RANGES:
    export_mod.write_json(
        DATA_DIR / f"a-stock-{_rng}.json",
        export_mod.export_a_stock(conn, cfg, _rng),
    )
    print(f"  a-stock-{_rng}.json 重导完成")
conn.close()
PYEOF
  RC_EXPORT=$?
  if [ "$RC_EXPORT" -ne 0 ]; then
    echo "✗ 增量重导失败 rc=${RC_EXPORT}" >> "$LOG"
  fi
fi

# 4) 上传 R2 + purge CF edge(§22 N 缓存同步; upload-intraday 覆盖 overview/a-stock-3m/6m/1y,
#    upload-data-large 兜底大 range 3y/5y/all; 失败仅告警不阻断——git 渠道随次日 deploy 追上)
if [ "$RC_EXPORT" -eq 0 ]; then
  echo "-> 上传 R2(upload-intraday + upload-data-large) ..." >> "$LOG"
  # #364: 等锁段/工作段两预算各自独立计时; 外层兜底只兜「进程内计时器生效之前」的窗口。
  #   upload-intraday 内层工作预算 600s 的取证(云上 data/logs/turnover_backfill_launchd.log):
  #     · 段耗时大头是**等锁**(心跳行「⏳ 等待 R2 上传锁 Ns」每 30s 一行, 10-23 有 22 行≈660s),
  #       内层预算按口径**不含等锁**, 故 M 取「拿到锁后的纯工作耗时」;
  #     · 用 (脚本结束 - 重导结束) 减去 data-large 实测总耗时可得残差, 包括重导+工作+purge:
  #       10-23=72.7s / 10-26=65.9s / 10-27=73s / 10-28=49.6s / 10-29=48s
  #       (10-29 由 rc=124 反推 data-large 起点 22:01:24, 与结束 22:47:24 逐秒吻合)
  #       ⇒ 纯工作 M ≤ ~73s(上界还含 7 个展示文件重导与 purge);
  #     · 取 max(600, ceil(M*3)) 且 ≤1200 ⇒ **600**。
  #   历史警惕: 10-17 前旧口径下 intraday 曾跑到 ~450–900s(10-13 撞 900s 上限), 故不取更小值。
  run_to 2460 env R2_UPLOAD_LOCK_TIMEOUT="$R2_LOCK_WAIT_BUDGET" R2_UPLOAD_WORK_TIMEOUT="$R2_WORK_BUDGET_INTRADAY" R2_UPLOAD_LOCK_DOMAIN=data \
    "$PY" scripts/upload_r2.py upload-intraday >> "$LOG" 2>&1
  RC_R2=$?
  [ "$RC_R2" -ne 0 ] && echo "⚠ upload-intraday R2 同步失败 rc=${RC_R2}(git 渠道随次日 deploy 追上)" >> "$LOG"
  run_to 4260 env R2_UPLOAD_LOCK_TIMEOUT="$R2_LOCK_WAIT_BUDGET" R2_UPLOAD_WORK_TIMEOUT="$R2_WORK_BUDGET" R2_UPLOAD_LOCK_DOMAIN=data \
    "$PY" scripts/upload_r2.py upload-data-large >> "$LOG" 2>&1
  RC_R2L=$?
  [ "$RC_R2L" -ne 0 ] && echo "⚠ upload-data-large R2 同步失败 rc=${RC_R2L}(git 渠道随次日 deploy 追上)" >> "$LOG"
fi

FINAL_RC=$RC_PIPE
[ "$FINAL_RC" -eq 0 ] && FINAL_RC=$RC_EXPORT
[ "$FINAL_RC" -eq 0 ] && FINAL_RC=$RC_R2
[ "$FINAL_RC" -eq 0 ] && FINAL_RC=$RC_R2L

if [ "$FINAL_RC" -ne 0 ]; then
  "$PY" scripts/notify.py \
    "[告警] turnover 独立任务链路异常 pipe=$RC_PIPE export=$RC_EXPORT r2=$RC_R2 r2large=$RC_R2L $(date '+%m-%d %H:%M')" \
    "turnover 独立延后任务(21:10)四段(pipeline 采集 / 增量重导 overview+a-stock / upload-intraday / upload-data-large)任一失败, 当日 a_turnover_* 数据可能缺失或未上线。<br>日志: $LOG (尾部 50 行)<br>影响: 首页折叠区/A股走势图换手率读 T-1(缺当日不报错, 前端 T1_COLLECT_DEADLINE 18:00 会标红色异常至数据上线)。" \
    --severe --from-prefix "[告警]" \
    --alert-issue "turnover 独立任务链路异常" --alert-log "$LOG" \
    --dedup-key turnover_backfill_fail --dedup-window 3600 2>&1 | tee -a "$LOG" || true
fi

echo "=== turnover_backfill.sh 结束 $(date '+%F %T') 退出码=$FINAL_RC ===" >> "$LOG"
exit "$FINAL_RC"
