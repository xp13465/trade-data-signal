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
#   超时 fail-closed exit 1); 工作段 = R2_UPLOAD_WORK_TIMEOUT(=各步工作预算, 现行 900/3120),
#   计时起点 = 真正拿到锁之后(在 upload_r2.py 进程内 arm)。shell `run_to` 保留为外层兜底
#   (现行 2760/4980, 只兜「进程内计时器生效之前」的窗口), 口径与 E1 完全对齐。
#   ⚠ 依赖: 进程内工作预算来自 upload_r2.py 的 R2_UPLOAD_WORK_TIMEOUT 读取(#258 E1 声称提供,
#     实际 #364 才真正实现); 下方反查守卫会 grep 读取代码, 缺失记 WARN 不阻断(见 S5 说明)。
#   ⚠ 外层墙: 本任务 unit `trade-turnover-backfill.service` 的 TimeoutStartUSec=infinity
#     (云上实测 `systemctl show -p TimeoutStartUSec` = infinity; 快照
#     docs/deploy/systemd-units-cloud-snapshot.txt), 故真正的外层墙在 shell(run_to), 不在 systemd。
# #364(2026-10-30): 二版现行数值 = upload-intraday 外层 2760(工作 900, 用户拍板) /
#   upload-data-large 外层 4980(工作 3120, 按 10-20 实测纯工作复算)。一版曾是 2460(600)/4260(2400),
#   详见下方「R2 步骤预算」段与第 4 步注释(含取证)。
# #364 三轮(2026-10-30): ①预算自检 FATAL 补告警 + 标准「结束」行(旧版直接 exit 2 ⇒ 无声死);
#   ②补绝对值区间断言(R2_WORK_BUDGET ∈ [2400,3600] / R2_WORK_BUDGET_INTRADAY ∈ [600,1800]),
#   防「三者一起缩水」时关系式全绿。
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

# #364(2026-10-30)重定两个 R2 步骤的预算(按最坏路径复算, 取证见 #364 实施报告):
#   - upload-data-large 工作预算 900 → 2400 → **3120**(二版, 按实测纯工作复算):
#     云上 10-20 晚 `[data-large] ✓ 上传完成 23/23, 耗时 2574.8s` —— 该「耗时」的计时起点 =
#     `_incremental_upload` 入口(在**拿到锁之后** arm), 即**纯工作**(指纹扫描 + 备份 + 上传),
#     同晚 data-large 段零等锁心跳(≈无排队) ⇒ 2574.8 × 1.2 = 3089.8 → 按 60s 向上取整 = **3120**。
#     口径: ceil(max(实测纯工作最坏 × 1.2) / 60) * 60, 下限 2400 / 上限 3600。
#     (一版取 2400 反而 < 2574.8 = 会把正常夜误杀, 故抬到 3120。)
#   - upload-data-large 外层兜底 2760 → 4260 → **4980** = 等锁 1800 + 工作 3120 + 60 余量
#     (必须写字面量: 梯度审计 systemd_timeout_gradient_audit.py 只认 `run_to <字面量>`)。
#   - upload-intraday 工作预算 900(用户 2026-10-30 拍板; 一版 600)。取证 = 拿到锁后的纯工作
#     ≈49–73s(见第 4 步注释), 900 是在 max(600, ceil(M*3)) 之上的「有日志的保险」, 不是新证据。
#     外层兜底 2460 → **2760** = 1800 + 900 + 60 —— 恰好等于 #364 改前的旧值 ⇒
#     对外层可容忍总时长**零变更**; 新增的只是「内层到期必打一行日志」的保险
#     (改前内层无声、外层先杀 ⇒ 43 分钟黑屏)。
R2_LOCK_WAIT_BUDGET=1800
R2_WORK_BUDGET=3120
R2_WORK_BUDGET_INTRADAY=900
OUTER_LARGE=$((R2_LOCK_WAIT_BUDGET + R2_WORK_BUDGET + 60))              # 4980
OUTER_INTRADAY=$((R2_LOCK_WAIT_BUDGET + R2_WORK_BUDGET_INTRADAY + 60))  # 2760

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

# ---- R2 步骤的预算自检(#364 二版; 位置见 S5 说明: 采集与重导都已完成、数据已落盘,
#      这里拦的只是「注定要被外层先杀的上传」——静态断言不该在采集前把一晚数据全废掉) ----
# 病灶(一版): 旧自检拿写死的 4260/2460 与常量算式比 ⇒ 有人把调用处的 `run_to 4260` 改成 2000
#   (真倒挂)自检照样全过 = 守卫名不副实。现改为 **grep 本脚本自身**, 抽出每个步骤调用处真实的
#   `run_to <N>` 数字再比: 抽不到 / 抽到多个 / 抽到的不是数字 ⇒ 一律 FATAL(宁可红, 不许静默放过)。
# 注意: `$0` 在 with_lock.py 重跑自己时仍是本脚本路径, 但这里用 BASH_SOURCE[0] 更稳(重跑发生在
#   自检之后的 exec 处, 且 V10 变异跑的是临时副本, 两者取值都指向「正在跑的这个文件」)。
_self_src="${BASH_SOURCE[0]}"
# S1(#364 三轮): FATAL 不许「无声死」。旧版直接 exit 2, 跳过末尾的 notify.py 与「结束」行;
#   而 turnover 不在 schedule_monitor.sh 的 DUR_THRESHOLDS 里 ⇒ 「进行中超时」也不报 ⇒
#   一晚没传上 R2 只能靠 systemd failed / 次日数据陈旧才发现。这里照抄末尾失败路径的文案口径
#   补一条 severe 告警 + 写标准「结束」行(gen_schedule_stats / 漏跑检查直读该行)。
#   告警四元组(必声明, 缺一不上线): 默认 tier=severe / dedup window=3600s /
#   聚合域=turnover_backfill_budget_fatal(与链路失败键 turnover_backfill_fail 分开:
#   预算自检失败是配置错, 不是链路偶发) / 首报策略=立即(无静默期)。
_r2_budget_fatal() {
  local msg="$1"
  echo "$(date '+%F %T') FATAL: $msg —— 见 #364" >> "$LOG"
  echo "FATAL: $msg" >&2
  "$PY" scripts/notify.py \
    "[告警] turnover 预算自检 FATAL ${msg} $(date '+%m-%d %H:%M')" \
    "turnover 独立延后任务(21:10)的 R2 预算自检在开跑上传前失败: ${msg}。<br>已中止本轮 R2 上传(数据已落盘 REPO 主库树, git 渠道随次日 17:50 deploy 追上)。<br>日志: $LOG (尾部 50 行)<br>影响: 当日 a_turnover_* 相关文件可能未同步到 R2, 首页折叠区/A股走势图换手率读 T-1(缺当日不报错, 前端 T1_COLLECT_DEADLINE 18:00 会标红色异常至数据上线)。" \
    --severe --from-prefix "[告警]" \
    --alert-issue "turnover 预算自检 FATAL" --alert-log "$LOG" \
    --dedup-key turnover_backfill_budget_fatal --dedup-window 3600 2>&1 | tee -a "$LOG" || true
  echo "=== turnover_backfill.sh 结束 $(date '+%F %T') 退出码=2（预算自检 FATAL）===" >> "$LOG"
  exit 2
}
# S3(#364 三轮): 绝对数值区间断言。关系式「外层 = 等锁 + 工作 + 60」只钉相对关系,
#   三者一起缩水/膨胀时全绿(如工作 3120→1200、外层 4980→3060, 见 V5 变异)。区间与上方
#   预算注释同源: data-large 工作 ∈ [2400, 3600](下限 2400 = 实测纯工作 2574.8 的保守下限;
#   上限 3600 见上方口径), intraday 工作 ∈ [600, 1800](下限 600 = max(600, ceil(M*3));
#   上限 1800 = 等锁预算同量级, 再大等于把「有日志的保险」变成第二道等锁)。
_r2_check_ranges() {
  local v
  v=$R2_WORK_BUDGET
  case "$v" in ''|*[!0-9]*) _r2_budget_fatal "R2_WORK_BUDGET 不是整数(实得 '${v}')" ;; esac
  if [ "$v" -lt 2400 ] || [ "$v" -gt 3600 ]; then
    _r2_budget_fatal "R2_WORK_BUDGET=$v 越出区间 [2400, 3600](绝对值缩水/膨胀, 关系式仍可能成立)"
  fi
  v=$R2_WORK_BUDGET_INTRADAY
  case "$v" in ''|*[!0-9]*) _r2_budget_fatal "R2_WORK_BUDGET_INTRADAY 不是整数(实得 '${v}')" ;; esac
  if [ "$v" -lt 600 ] || [ "$v" -gt 1800 ]; then
    _r2_budget_fatal "R2_WORK_BUDGET_INTRADAY=$v 越出区间 [600, 1800](绝对值缩水/膨胀, 关系式仍可能成立)"
  fi
}
# 抽某一步调用处的「行号:run_to 字面量」行(以该步的工作预算变量名区分两步)
_r2_step_run_to() {
  local work_var="$1"
  grep -nE "^[[:space:]]*run_to [0-9]+ env R2_UPLOAD_LOCK_TIMEOUT=\"\\\$R2_LOCK_WAIT_BUDGET\" R2_UPLOAD_WORK_TIMEOUT=\"\\\$$work_var\"" "$_self_src"
}
# $1=步骤名 $2=工作预算变量名 $3=该步工作预算值 $4=算式算出的外层兜底值
_r2_check_step() {
  local name="$1" wvar="$2" work="$3" expect="$4" rows n lit
  rows=$(_r2_step_run_to "$wvar")
  n=$(printf '%s' "$rows" | grep -c .)
  if [ "$n" -ne 1 ]; then
    _r2_budget_fatal "${name} 调用处的 run_to 抽不到或抽到多个(实得 ${n} 处), 无法校验梯度"
  fi
  lit=$(printf '%s\n' "$rows" | sed -E 's/^[0-9]+:[[:space:]]*run_to ([0-9]+) .*/\1/')
  case "$lit" in
    ''|*[!0-9]*) _r2_budget_fatal "${name} 调用处的 run_to 抽到的不是数字(实得 '${lit}')" ;;
  esac
  if [ "$lit" -le "$((R2_LOCK_WAIT_BUDGET + work))" ]; then
    _r2_budget_fatal "${name} 预算梯度倒挂(外层 ${lit} <= 等锁 ${R2_LOCK_WAIT_BUDGET} + 工作 ${work})"
  fi
  if [ "$lit" -ne "$expect" ]; then
    _r2_budget_fatal "${name} 外层兜底字面量 ${lit} 与算式 ${expect}(= 等锁 + 工作 + 60)不一致(改一边漏另一边)"
  fi
}

# 4) 上传 R2 + purge CF edge(§22 N 缓存同步; upload-intraday 覆盖 overview/a-stock-3m/6m/1y,
#    upload-data-large 兜底大 range 3y/5y/all; 失败仅告警不阻断——git 渠道随次日 deploy 追上)
if [ "$RC_EXPORT" -eq 0 ]; then
  # 倒挂自检(逐步骤各自校验): 任一条倒挂/越界 ⇒ FATAL(此时数据已落盘, 由退出码告警接管)。
  _r2_check_ranges
  _r2_check_step "upload-intraday" "R2_WORK_BUDGET_INTRADAY" "$R2_WORK_BUDGET_INTRADAY" "$OUTER_INTRADAY"
  _r2_check_step "upload-data-large" "R2_WORK_BUDGET" "$R2_WORK_BUDGET" "$OUTER_LARGE"
  # 反查守卫(#364, S5 降级为 WARN 不 exit): 「传了 env 但 python 压根不读」= 回到改前行为(只是内层
  #   保险失效), 脚本仍能正常上传; 为此拒传 R2 是过度反应 ⇒ 记录后继续, 由巡检/审查兜底。
  if ! grep -q 'os\.environ\.get("R2_UPLOAD_WORK_TIMEOUT"' "$REPO/scripts/upload_r2.py" 2>/dev/null; then
    echo "$(date '+%F %T') WARN: upload_r2.py 未读取 R2_UPLOAD_WORK_TIMEOUT(内层工作预算失效, 行为回到改前, 不阻断上传) —— 见 #364" >> "$LOG"
  fi
  echo "-> 上传 R2(upload-intraday + upload-data-large) ..." >> "$LOG"
  # #364: 等锁段/工作段两预算各自独立计时; 外层兜底只兜「进程内计时器生效之前」的窗口。
  #   upload-intraday 内层工作预算 900s(用户 2026-10-30 拍板; 一版曾按纯工作取证取 600):
  #     · 段耗时大头是**等锁**(心跳行「⏳ 等待 R2 上传锁 Ns」每 30s 一行, 10-23 有 22 行≈660s),
  #       内层预算按口径**不含等锁**, 故 M 取「拿到锁后的纯工作耗时」;
  #     · 用 (脚本结束 - 重导结束) 减去 data-large 实测总耗时可得残差, 包括重导+工作+purge:
  #       10-23=72.7s / 10-26=65.9s / 10-27=73s / 10-28=49.6s / 10-29=48s
  #       (10-29 由 rc=124 反推 data-large 起点 22:01:24, 与结束 22:47:24 逐秒吻合)
  #       ⇒ 纯工作 M ≤ ~73s(上界还含 7 个展示文件重导与 purge);
  #     · 按 M 算只需 max(600, ceil(M*3)) ≈ 600, 但 900 = 用户拍板的「有日志的保险」值:
  #       多给的 5 分钟只花在极端慢链路上, 换来回的是「到期必有一行可 grep 日志」,
  #       且外层 2760 与改前旧值相等 ⇒ 对外层可容忍总时长零变更。
  #   历史警惕: 10-17 前旧口径下 intraday 曾跑到 ~450–900s(10-13 撞 900s 上限), 故不取更小值。
  run_to 2760 env R2_UPLOAD_LOCK_TIMEOUT="$R2_LOCK_WAIT_BUDGET" R2_UPLOAD_WORK_TIMEOUT="$R2_WORK_BUDGET_INTRADAY" R2_UPLOAD_LOCK_DOMAIN=data \
    "$PY" scripts/upload_r2.py upload-intraday >> "$LOG" 2>&1
  RC_R2=$?
  [ "$RC_R2" -ne 0 ] && echo "⚠ upload-intraday R2 同步失败 rc=${RC_R2}(git 渠道随次日 deploy 追上)" >> "$LOG"
  run_to 4980 env R2_UPLOAD_LOCK_TIMEOUT="$R2_LOCK_WAIT_BUDGET" R2_UPLOAD_WORK_TIMEOUT="$R2_WORK_BUDGET" R2_UPLOAD_LOCK_DOMAIN=data \
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
