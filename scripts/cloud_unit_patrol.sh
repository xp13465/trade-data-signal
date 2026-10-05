#!/usr/bin/env bash
# cloud_unit_patrol.sh - 云上 systemd unit 直连巡检包装(#191,消 #189 闸门「快照陈旧」窗口)
#
# 背景(#191,出处 = #189 reviewer P2-1):
#   #189 挂的 main-merge 7.8 闸门锚的是仓库内【固化快照】
#   docs/deploy/systemd-units-cloud-snapshot.txt,只保证「doc §2 == 快照」,
#   **不保证「快照 == 云上当前 unit」**:云上手改 unit 却没刷快照时闸门照样绿 ⇒
#   之后重跑 gen_systemd_units 仍可能把 doc 旧值装回云上(#36 病根只是被关进一个
#   「快照陈旧」窗口)。本脚本 = 云上 trade-cloud-unit-patrol.timer 的包装,
#   **直连 /etc/systemd/system/trade-*.{service,timer} 真文件** → 与仓库快照逐字段
#   全量比对 → 漂移即 notify 告警,把三源(doc §2 / 快照 / 云上)真正闭合。
#
# 只报警不改生产(设计取舍见报告 docs/ops/191-cloud-unit-patrol-20261005.md §2):
#   - 不改任何 unit、不 enable/disable、不 git push(§8:main 只走 main-merge.sh)
#   - 漂移=人工事件:要么云上手改有误→回滚该 unit;要么有意改→刷新快照 + 对齐 doc §2 走 merge
#
# 时点(#14):08:27 —— 开盘前闲时,避开盘后 15:35/16:00/17:50/20:35/22:00 与
#   盘中 09:30-15:30;08 点档无其他 trade timer(最近 rzhb-backfill 08:00),
#   且避开 check-monitor-heartbeat 的 :11/:26/:41/:56 分钟位。
#   每日跑不限交易日:「快照==云上」是不变量,周末手改同样要抓。
#
# 判定/出口:systemd_timeout_gradient_audit.py --check-snapshot rc!=0(云上 vs 快照
#   漂移,或快照缺失/空)→ notify --severe(去重 6h);rc=0 静默(仅日志)。
#   仅告警不阻断(不在任何推送链上)。
#   日志:data/logs/cloud_unit_patrol_launchd.log(固定名 append;脚本自己写同名
#   *_launchd.log ⇒ unit 刻意不设 StandardOutput append,§1.4 例外条款)。
#
# 自测桩(生产不设,见 check_r2_consistency 先例):
#   CLOUD_UNIT_PATROL_ARBITER_DUMP=<path>  权威源改用该 dump(替代直连 /etc/systemd/system)
#   CLOUD_UNIT_PATROL_SNAPSHOT=<path>       快照路径覆盖
#   CLOUD_UNIT_PATROL_NOTIFY_DRYRUN=1       notify 加 --dry-run(不真发,自验用)
#   CLOUD_UNIT_PATROL_UNITS_DIR=<path>      权威 unit 目录覆盖(默认 /etc/systemd/system;自测/沙箱用)
#   CLOUD_UNIT_PATROL_FATAL_LOG=<path>      路径校验失败时的落盘日志(默认 ${TMPDIR:-/tmp}/cloud_unit_patrol_fatal.$(id -un).log)
#
# ── #194 路径加固(2026-10-05,#191 §0 亲验发现的「静默盲区」同族)──────────────
# 病灶:原第 36/37 行对 REPO/GIT_REPO 写死 mac 默认值(/Users/linhuichen/...),
#   生产靠 unit 的 Environment=REPO=/GIT_REPO= 兜住。一旦那两行 Environment 丢失
#   (重生成 unit 被覆盖 / 手改),脚本就拿 mac 路径去 cd / 调 python:rc=127,
#   且 **$PY 也源自坏 REPO ⇒ notify 一样调不动** ⇒「失败恰恰是最没声音的时候」。
# 修法(只动本文件,不扩面):
#   ① fail-fast:cd / 调 python **之前**校验 REPO、GIT_REPO、.venv/bin/python,
#      不成立即打印带「实际取值 + env/unit 配置可能丢失」提示到 stderr 并 exit≠0。
#   ② 去 mac 隐式默认:优先从 $0 推导(env 覆盖仍最高优先);推不出且 env 也没给
#      → 走 ①的 fail-fast,绝不「猜一个 mac 路径继续跑」。
#      推导依据:云上/mac 的 <REPO>/scripts 都是**指向 git 仓库 scripts/ 的 symlink**
#        (云 trade-data/scripts -> trade-data-signal/scripts;mac trade-data/scripts -> trade/scripts)
#        ⇒ $0 的 scripts 目录的**父目录** = REPO(数据/运行目录,含 .venv);
#          $0 的 scripts 目录**解析 symlink 后**的父目录 = GIT_REPO(git 仓,含 docs/deploy 快照)。
#   ③ 失败出口兜底:即使路径校验失败,该失败本身也有出口——stderr(unit 无 append
#      重定向 ⇒ 直接进 systemd journal)+ 固定位置日志 $_FATAL_LOG(不依赖坏 REPO)。
#   自测脚本:scripts/cloud_unit_patrol_selftest.sh(fail-fast / $0 推导 / 环境守卫 / bash -n)。
#
# ── #194-F2 环境守卫(2026-10-05,reviewer 实测事故根治)────────────────────────
# 事故:本脚本**云上专用**(直连 /etc/systemd/system)。在 mac/非云上跑它时,权威源
#   读不到(旧脚本 ∵ 目录不存在 → audit rc=2)→ 被当成「漂移」→ **真发出 1 邮件 +
#   1 飞书 severe**(reviewer 2026-10-05 用 main 旧版在 mac 上跑自测时真实发生)。
# 判据(仓库无先例,自定并明写):**权威源「存在且像真的」才允许巡检;不成立一律
#   只写日志 + exit 3,绝不调用 notify**。权威源与 systemd_timeout_gradient_audit.py
#   read_all_units 完全同源(避免「守卫看的源 ≠ 审计读的源」)——
#     ①生产模式(无 dump):unit 目录(默认 /etc/systemd/system)存在 且 含 trade-*.service
#     ②测试桩模式(CLOUD_UNIT_PATROL_ARBITER_DUMP 已设):dump 文件存在且非空;
#       **该模式纯诊断,永不发通知**(生产不设此桩,设了=有人在做测试,不该惊动用户)。
#   exit 3 非 0:让「巡检自身没跑成」在 systemd/监控里可见(不做静默 —— 与 #188 同精神)。
#
# ── #194-F3 失败出口可写性(2026-10-05,reviewer 实测)──────────────────────────
# 事故:出口②的 /tmp/cloud_unit_patrol_fatal.log 曾被 root 属主化(某次以 root 跑
#   留下 644 root 文件)→ 之后 ubuntu 身份 append 被拒 → 出口②降级失效。
# 修法:文件名带 $(id -un) 后缀(每用户独立,避开他人/root 残留),且出口①(stderr→
#   journal)恒在——即使文件写不进也有 journal 兜底。CLOUD_UNIT_PATROL_FATAL_LOG 可覆盖。
#
# 用法: bash scripts/cloud_unit_patrol.sh
set -u

# ── 路径自解析(#194/#195):env 覆盖 > 从 $0 推导(共享 lib)> fail-fast ─────────
# #195 批1:先前内联的 symlink 推导块收敛到 scripts/lib 的单点 resolve_repo(去重,行为不变),
#   原 export 语义保留。lib 在「推导值非法」时已 fail-loud(exit 2 + 固定日志);
#   下方 _fatal 校验负责本脚本语境化提示(unit Environment= 丢失等)。
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/lib/repo_paths.sh" || { echo "FATAL: repo_paths.sh missing" >&2; exit 2; }
resolve_repo "${BASH_SOURCE[0]}"
export REPO GIT_REPO

_FATAL_LOG="${CLOUD_UNIT_PATROL_FATAL_LOG:-${TMPDIR:-/tmp}/cloud_unit_patrol_fatal.$(id -un).log}"
_fatal() {
  # 失败出口:①stderr(bash 无条件处理)→ systemd journal ②固定位置日志(不依赖坏 REPO)
  local msg="[cloud_unit_patrol] FATAL: $*"
  printf '%s\n' "$msg" >&2
  printf '%s %s\n' "$(date '+%F %T')" "$msg" >> "$_FATAL_LOG" 2>/dev/null || true
  exit 2
}

# ── fail-fast 校验(cd / 调用 python 之前)────────────────────────────────────
[ -d "$REPO" ]     || _fatal "REPO 目录不存在: REPO='$REPO'。systemd unit trade-cloud-unit-patrol.service 的 Environment=REPO= 或环境变量可能丢失/写错。"
[ -d "$GIT_REPO" ] || _fatal "GIT_REPO 目录不存在: GIT_REPO='$GIT_REPO'。unit 的 Environment=GIT_REPO= 或环境变量可能丢失/写错。"
PY="${PY:-$REPO/.venv/bin/python}"
[ -f "$REPO/.venv/bin/python" ] || _fatal "REPO 下缺 .venv/bin/python(REPO='$REPO')——REPO 可能指向了错误目录。"
[ -x "$PY" ] || _fatal "python 解释器不存在/不可执行: PY='$PY'(默认 \$REPO/.venv/bin/python)。REPO/PY 配置错误。"

LOGDIR="$REPO/data/logs"
mkdir -p "$LOGDIR" || _fatal "无法创建日志目录: $LOGDIR"
cd "$REPO" || _fatal "无法进入 REPO: $REPO"
LOG="$LOGDIR/cloud_unit_patrol_launchd.log"

SNAPSHOT="${CLOUD_UNIT_PATROL_SNAPSHOT:-$GIT_REPO/docs/deploy/systemd-units-cloud-snapshot.txt}"

# ── 环境守卫(#194-F2):权威源存在且像真的才巡检;否则只日志 + exit 3,绝不 notify ──
# 判据见脚本头;权威源与 audit 的 read_all_units 同源,避免「守卫看的源 ≠ 审计读的源」。
_UNITS_DIR="${CLOUD_UNIT_PATROL_UNITS_DIR:-/etc/systemd/system}"
if [ -n "${CLOUD_UNIT_PATROL_ARBITER_DUMP:-}" ]; then
  _MODE=dump; _SRC="$CLOUD_UNIT_PATROL_ARBITER_DUMP"; _NOTIFY=0; _SRC_KIND="dump 文件"  # dump=诊断,永不通知
else
  _MODE=units; _SRC="$_UNITS_DIR"; _NOTIFY=1; _SRC_KIND="unit 目录"                      # 生产/沙箱,可通知
fi
_env_ok() {
  if [ "$_MODE" = dump ]; then
    [ -s "$_SRC" ]
  else
    [ -d "$_SRC" ] && ls "$_SRC"/trade-*.service >/dev/null 2>&1
  fi
}
if ! _env_ok; then
  _skip="非云上巡检环境:${_SRC_KIND} '$_SRC' 不存在或为空(判据:unit 目录须含 trade-*.service / dump 须非空)。本脚本云上专用,开发机/容器跑它会把空权威源误判成漂移;本次不巡检、不发通知。"
  printf '[cloud_unit_patrol] SKIP: %s\n' "$_skip" >&2
  { echo "=== cloud_unit_patrol.sh 开始 $(date '+%F %T') ==="
    echo "[skip] $_skip"
    echo "=== cloud_unit_patrol.sh 结束 $(date '+%F %T') 退出码=3(环境守卫跳过) ==="; } >> "$LOG"
  exit 3
fi

echo "=== cloud_unit_patrol.sh 开始 $(date '+%F %T') ===" >> "$LOG"

# 权威源:默认直连云上真 unit(--units-dir);自测桩可换 dump(--dump 优先于 --units-dir)
AUDIT_ARGS=( --snapshot "$SNAPSHOT" --check-snapshot --units-dir "$_UNITS_DIR" )
if [ "$_MODE" = dump ]; then
  AUDIT_ARGS=( --dump "$_SRC" "${AUDIT_ARGS[@]}" )
fi

OUT="$("$PY" scripts/systemd_timeout_gradient_audit.py "${AUDIT_ARGS[@]}" 2>&1)"
RC=$?
printf '%s\n' "$OUT" >> "$LOG"

if [ "$RC" -ne 0 ]; then
  # 摘录差异段(表头「unit …」起)进告警正文;换行折成 |(邮件体单段)
  BODY="$(printf '%s\n' "$OUT" | head -1)"
  DIFF="$(printf '%s\n' "$OUT" | sed -n '/^unit /,$p' | head -12 | tr '\n' '|')"
  BODY_ESC="$(printf '%s' "$BODY" | sed 's/&/\&amp;/g; s/</\&lt;/g')"
  DIFF_ESC="$(printf '%s' "$DIFF" | sed 's/&/\&amp;/g; s/</\&lt;/g')"
  if [ "$_NOTIFY" = 1 ]; then
    echo "✗ 云上 unit 与仓库快照漂移 rc=${RC},发 severe 告警" >> "$LOG"
    NOTIFY_DRYRUN=""
    [ "${CLOUD_UNIT_PATROL_NOTIFY_DRYRUN:-}" = "1" ] && NOTIFY_DRYRUN="--dry-run"
    "$PY" scripts/notify.py "[告警] 云上 systemd unit 与仓库快照漂移" \
      "${BODY_ESC}<br>云上 /etc/systemd/system/trade-*.{service,timer} 与仓库快照 ${SNAPSHOT} 漂移(rc=${RC})。<br>处置:①云上手改有误→回滚该 unit(用 .bak 或对照快照)②有意改→刷新快照 + 对齐 doc §2 走 merge(否则后续重跑生成器可能把 doc 旧值装回云上)。<br>差异: unit | field | cloud | snapshot:<br>${DIFF_ESC}<br>脚本: scripts/cloud_unit_patrol.sh &nbsp;日志: ${LOG}" \
      --severe --from-prefix "[告警]" --dedup-key cloud_unit_patrol_drift --dedup-window 21600 $NOTIFY_DRYRUN 2>&1 | tee -a "$LOG" || true
  else
    echo "✗ 漂移 rc=${RC},但当前为 dump 诊断模式(#194-F2),不发通知(仅日志)" >> "$LOG"
  fi
fi

echo "=== cloud_unit_patrol.sh 结束 $(date '+%F %T') 退出码=$RC ===" >> "$LOG"
exit "$RC"