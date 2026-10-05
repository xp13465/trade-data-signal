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
#   CLOUD_UNIT_PATROL_FATAL_LOG=<path>      路径校验失败时的落盘日志(默认 ${TMPDIR:-/tmp}/cloud_unit_patrol_fatal.log)
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
#   自测脚本:scripts/cloud_unit_patrol_selftest.sh(fail-fast / $0 推导 / bash -n)。
#
# 用法: bash scripts/cloud_unit_patrol.sh
set -u

# ── 路径自解析(#194):env 覆盖 > 从 $0 推导 > fail-fast ──────────────────────
_self="$0"
case "$_self" in
  /*) : ;;
  *)  _self="$(pwd)/$_self" ;;   # 相对路径(手动 bash scripts/xxx.sh)→ 补 cwd
esac
_self_dir="$(dirname "$_self")"                                              # 本脚本所在 scripts 目录(未解 symlink)
_repo_derived="$(dirname "$_self_dir")"                                      # REPO 候选 = scripts 的父目录
_self_dir_real="$(cd "$_self_dir" 2>/dev/null && pwd -P || printf '%s' "$_self_dir")"   # 解 symlink 后的 scripts 目录
_gitrepo_derived="$(dirname "$_self_dir_real")"                              # GIT_REPO 候选 = 解 symlink 后 scripts 的父目录

export REPO="${REPO:-$_repo_derived}"
export GIT_REPO="${GIT_REPO:-$_gitrepo_derived}"

_FATAL_LOG="${CLOUD_UNIT_PATROL_FATAL_LOG:-${TMPDIR:-/tmp}/cloud_unit_patrol_fatal.log}"
_fatal() {
  # 失败出口:①stderr(bash 无条件处理)→ systemd journal ②固定位置日志(不依赖坏 REPO)
  local msg="[cloud_unit_patrol] FATAL: $*"
  printf '%s\n' "$msg" >&2
  printf '%s %s\n' "$(date '+%F %T')" "$msg" >> "$_FATAL_LOG" 2>/dev/null || true
  exit 2
}

# ── fail-fast 校验(cd / 调用 python 之前)────────────────────────────────────
[ -d "$REPO" ]     || _fatal "REPO 目录不存在: REPO='$REPO'($0 推导值='$_repo_derived')。systemd unit trade-cloud-unit-patrol.service 的 Environment=REPO= 或环境变量可能丢失/写错。"
[ -d "$GIT_REPO" ] || _fatal "GIT_REPO 目录不存在: GIT_REPO='$GIT_REPO'($0 推导值='$_gitrepo_derived')。unit 的 Environment=GIT_REPO= 或环境变量可能丢失/写错。"
PY="${PY:-$REPO/.venv/bin/python}"
[ -f "$REPO/.venv/bin/python" ] || _fatal "REPO 下缺 .venv/bin/python(REPO='$REPO')——REPO 可能指向了错误目录。"
[ -x "$PY" ] || _fatal "python 解释器不存在/不可执行: PY='$PY'(默认 \$REPO/.venv/bin/python)。REPO/PY 配置错误。"

LOGDIR="$REPO/data/logs"
mkdir -p "$LOGDIR" || _fatal "无法创建日志目录: $LOGDIR"
cd "$REPO" || _fatal "无法进入 REPO: $REPO"
LOG="$LOGDIR/cloud_unit_patrol_launchd.log"

SNAPSHOT="${CLOUD_UNIT_PATROL_SNAPSHOT:-$GIT_REPO/docs/deploy/systemd-units-cloud-snapshot.txt}"

echo "=== cloud_unit_patrol.sh 开始 $(date '+%F %T') ===" >> "$LOG"

# 权威源:默认直连云上真 unit(--units-dir /etc/systemd/system);自测桩可换 dump
AUDIT_ARGS=( --snapshot "$SNAPSHOT" --check-snapshot )
if [ -n "${CLOUD_UNIT_PATROL_ARBITER_DUMP:-}" ]; then
  AUDIT_ARGS=( --dump "$CLOUD_UNIT_PATROL_ARBITER_DUMP" "${AUDIT_ARGS[@]}" )
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
  echo "✗ 云上 unit 与仓库快照漂移 rc=${RC},发 severe 告警" >> "$LOG"
  NOTIFY_DRYRUN=""
  [ "${CLOUD_UNIT_PATROL_NOTIFY_DRYRUN:-}" = "1" ] && NOTIFY_DRYRUN="--dry-run"
  "$PY" scripts/notify.py "[告警] 云上 systemd unit 与仓库快照漂移" \
    "${BODY_ESC}<br>云上 /etc/systemd/system/trade-*.{service,timer} 与仓库快照 ${SNAPSHOT} 漂移(rc=${RC})。<br>处置:①云上手改有误→回滚该 unit(用 .bak 或对照快照)②有意改→刷新快照 + 对齐 doc §2 走 merge(否则后续重跑生成器可能把 doc 旧值装回云上)。<br>差异: unit | field | cloud | snapshot:<br>${DIFF_ESC}<br>脚本: scripts/cloud_unit_patrol.sh &nbsp;日志: ${LOG}" \
    --severe --from-prefix "[告警]" --dedup-key cloud_unit_patrol_drift --dedup-window 21600 $NOTIFY_DRYRUN 2>&1 | tee -a "$LOG" || true
fi

echo "=== cloud_unit_patrol.sh 结束 $(date '+%F %T') 退出码=$RC ===" >> "$LOG"
exit "$RC"