#!/usr/bin/env bash
# cloud_unit_patrol_selftest.sh - cloud_unit_patrol.sh #194 加固自测(无副作用,全在 mktemp 沙箱)
#
# 覆盖:
#   T0 bash -n 语法
#   T1   fail-fast: REPO 指向不存在路径 → exit≠0 + stderr 清晰提示 + 固定位置日志落一行
#   T2   fail-fast: GIT_REPO 指向不存在路径 → exit≠0
#   T3   fail-fast: REPO 下缺 .venv/bin/python → exit≠0
#   T4   $0 推导(经 scripts/lib 共享 lib): 造 <runtime>/scripts -> <gitrepo>/scripts 的 symlink
#        布局,不带 REPO/GIT_REPO env 直跑(audit 桩 rc=0)→ lib 推导 REPO=runtime / GIT_REPO=gitrepo,
#        日志落 runtime(#195 批1:推导实现由「patrol 内联」改判为「共享 lib」,断言结论不变)
#   T5   环境守卫(#194-F2): 权威 unit 目录不存在(非云上/开发机)→ exit 3 且 **绝不调用 notify**
#   T6   环境守卫不误伤: unit 目录像云上(含 trade-*.service)且 audit 报漂移 → notify 被调用(可达)
#   T7   dump 诊断模式(#194-F2): ARBITER_DUMP 非空 + 漂移 → 仍不发通知(仅日志)
#   T8   R2 锁/超时梯度告警通道(2026-10-31 常态化的第二段): systemd 审计 PASS 但 R2 梯度 FAIL
#        → notify 可达, 且带独立去重键 r2_lock_gradient_drift(与 systemd 漂移键互不吞)
#   T9   R2 梯度在 dump 诊断模式同样不发通知(仅日志)
#   F3   固定日志路径带 $(id -un) 后缀(每用户独立,避开 root 残留)—— 由 T1 的落盘路径间接覆盖
#
# 用法: bash scripts/cloud_unit_patrol_selftest.sh
set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
SCRIPT="$HERE/cloud_unit_patrol.sh"
[ -f "$SCRIPT" ] || { echo "找不到 $SCRIPT"; exit 1; }

pass=0; fail=0
ok()  { echo "  PASS: $1"; pass=$((pass+1)); }
bad() { echo "  FAIL: $1"; fail=$((fail+1)); }
TMP="$(mktemp -d)"; TMP="$(cd "$TMP" && pwd -P)"
trap 'rm -rf "$TMP"' EXIT

echo "== T0 bash -n =="
if bash -n "$SCRIPT"; then ok "bash -n 无语法错误"; else bad "bash -n 报错"; fi

# ── 造「一切正常」的沙箱布局(供各用例只打坏一个量)────────────────────────────
GOOD="$TMP/good"
mkdir -p "$GOOD/runtime/data/logs" "$GOOD/runtime/.venv/bin" "$GOOD/gitrepo/scripts"
ln -s "$GOOD/gitrepo/scripts" "$GOOD/runtime/scripts"
ln -s "$(command -v python3 2>/dev/null || echo /usr/bin/python3)" "$GOOD/runtime/.venv/bin/python"

run_patrol() {  # $1=REPO $2=GIT_REPO $3=fatal_log
  CLOUD_UNIT_PATROL_FATAL_LOG="$3" \
  env -u PY -u CLOUD_UNIT_PATROL_ARBITER_DUMP -u CLOUD_UNIT_PATROL_SNAPSHOT -u CLOUD_UNIT_PATROL_UNITS_DIR \
      REPO="$1" GIT_REPO="$2" bash "$SCRIPT" 2>&1
}

echo "== T1 fail-fast: REPO 不存在 =="
f1="$TMP/f1.log"
o1="$(run_patrol /nonexistent/repo-xyz "$GOOD/gitrepo" "$f1")"; r1=$?
{ [ "$r1" -ne 0 ] && printf '%s' "$o1" | grep -q "REPO 目录不存在" \
  && printf '%s' "$o1" | grep -q "Environment=REPO=" && grep -q "REPO 目录不存在" "$f1"; } \
  && ok "exit=$r1, stderr+固定日志(#194-F3 带 id -un 后缀)均含清晰提示" \
  || bad "r1=$r1 out=[$o1] f1=[$(cat "$f1" 2>/dev/null)]"

echo "== T2 fail-fast: GIT_REPO 不存在 =="
f2="$TMP/f2.log"
o2="$(run_patrol "$GOOD/runtime" /nonexistent/gitrepo-xyz "$f2")"; r2=$?
{ [ "$r2" -ne 0 ] && printf '%s' "$o2" | grep -q "GIT_REPO 目录不存在" && grep -q "GIT_REPO 目录不存在" "$f2"; } \
  && ok "exit=$r2, 提示含 GIT_REPO + 固定日志有行" || bad "r2=$r2 out=[$o2]"

echo "== T3 fail-fast: 缺 .venv/bin/python =="
NOVENV="$TMP/novenv"; mkdir -p "$NOVENV/runtime/data/logs" "$NOVENV/gitrepo/scripts"
o3="$(run_patrol "$NOVENV/runtime" "$NOVENV/gitrepo" "$TMP/f3.log")"; r3=$?
{ [ "$r3" -ne 0 ] && printf '%s' "$o3" | grep -q ".venv/bin/python"; } \
  && ok "exit=$r3, 提示含 .venv/bin/python" || bad "r3=$r3 out=[$o3]"

# ── 造完整沙箱(audit 桩 + notify 哨兵桩 + unit 目录),供 T4-T7 ────────────────
mk_sbx() {  # $1=目录
  local D="$1"
  mkdir -p "$D/runtime/data/logs" "$D/runtime/.venv/bin" "$D/gitrepo/scripts" \
           "$D/gitrepo/docs/deploy" "$D/units"
  ln -s "$D/gitrepo/scripts" "$D/runtime/scripts"
  cp "$SCRIPT" "$D/gitrepo/scripts/cloud_unit_patrol.sh"
  mkdir -p "$D/gitrepo/scripts/lib"
  cp "$HERE/lib/repo_paths.sh" "$D/gitrepo/scripts/lib/repo_paths.sh"   # #195:patrol 改 source 共享 lib
  ln -s "$(command -v python3)" "$D/runtime/.venv/bin/python"
  : > "$D/gitrepo/docs/deploy/systemd-units-cloud-snapshot.txt"
  : > "$D/units/trade-mock.service"          # 让环境守卫判定「像云上」
  # audit 桩:回显 --snapshot 下游(GIT_REPO 派生值),rc 由 MOCK_AUDIT_RC 控制
  cat > "$D/gitrepo/scripts/systemd_timeout_gradient_audit.py" <<'PY'
import os, sys
args = sys.argv[1:]
snap = args[args.index("--snapshot") + 1] if "--snapshot" in args else "(none)"
print("unit mock | TimeoutStartSec | cloud=600 | snapshot=90  (snapshot=%s)" % snap)
sys.exit(int(os.environ.get("MOCK_AUDIT_RC", "0")))
PY
  # R2 梯度审计桩(2026-10-31 第二段): rc 由 MOCK_R2_AUDIT_RC 控制, 回显真值源
  cat > "$D/gitrepo/scripts/r2_lock_gradient_audit.py" <<'PY'
import os, sys
args = sys.argv[1:]
src = "(none)"
if "--dump" in args:
    src = args[args.index("--dump") + 1]
elif "--units-dir" in args:
    src = args[args.index("--units-dir") + 1]
print("R2 合计 47 个调用点: PASS=47 WAIVED=0 FAIL=0 (外层真值源 = %s)" % src)
sys.exit(int(os.environ.get("MOCK_R2_AUDIT_RC", "0")))
PY
  # notify 桩:被调用则写哨兵文件(用于判定「是否外发通知」), 并记录 argv(判定去重键)
  cat > "$D/gitrepo/scripts/notify.py" <<'PY'
import os, sys
s = os.environ.get("NOTIFY_SENTINEL")
if s:
    with open(s, "a") as f:
        f.write("notify-called " + " ".join(sys.argv[1:]) + "\n")
sys.exit(0)
PY
}

# run_sbx <D> <MOCK_AUDIT_RC> <extra env...>  → 走 runtime/scripts symlink,不带 REPO/GIT_REPO
run_sbx() {
  local D="$1" rc="$2"; shift 2
  env -u REPO -u GIT_REPO -u PY -u CLOUD_UNIT_PATROL_SNAPSHOT \
      CLOUD_UNIT_PATROL_FATAL_LOG="$D/fatal.log" \
      NOTIFY_SENTINEL="$D/notify.sentinel" \
      MOCK_AUDIT_RC="$rc" \
      "$@" \
      bash "$D/runtime/scripts/cloud_unit_patrol.sh" 2>&1
}

echo "== T4 \$0 推导(经共享 lib;不带 REPO/GIT_REPO env,走 symlink 布局;unit 目录像云上) =="
if command -v python3 >/dev/null 2>&1; then
  D4="$TMP/d4"; mk_sbx "$D4"
  o4="$(run_sbx "$D4" 0 CLOUD_UNIT_PATROL_UNITS_DIR="$D4/units")"; r4=$?
  log4="$D4/runtime/data/logs/cloud_unit_patrol_launchd.log"
  { [ "$r4" -eq 0 ] && [ -f "$log4" ] && grep -q "unit mock" "$log4" \
    && grep -q "snapshot=$D4/gitrepo/docs/deploy" "$log4"; } \
    && ok "exit=0, 推导 REPO=runtime(日志落位)+ GIT_REPO=gitrepo(snapshot 路径正确)" \
    || bad "r4=$r4 out=[$o4] log4=[$(tr '\n' '|' < "$log4" 2>/dev/null)]"

  echo "== T5 环境守卫: 权威源不存在(非云上)→ exit 3 且绝不 notify =="
  D5="$TMP/d5"; mk_sbx "$D5"
  o5="$(run_sbx "$D5" 1 CLOUD_UNIT_PATROL_UNITS_DIR="$D5/nonexistent")"; r5=$?
  log5="$D5/runtime/data/logs/cloud_unit_patrol_launchd.log"
  { [ "$r5" -eq 3 ] && [ ! -f "$D5/notify.sentinel" ] \
    && printf '%s' "$o5" | grep -q "SKIP" && grep -q "\[skip\]" "$log5"; } \
    && ok "exit=3, 零通知(sentinel 不存在), 日志/ stderr 均标 SKIP" \
    || bad "r5=$r5 sentinel=$([ -f "$D5/notify.sentinel" ] && echo EXISTS || echo none) out=[$o5]"

  echo "== T6 环境守卫不误伤: 像云上 + 漂移 → notify 可达 =="
  D6="$TMP/d6"; mk_sbx "$D6"
  o6="$(run_sbx "$D6" 1 CLOUD_UNIT_PATROL_UNITS_DIR="$D6/units")"; r6=$?
  log6="$D6/runtime/data/logs/cloud_unit_patrol_launchd.log"
  { [ "$r6" -ne 0 ] && [ "$r6" -ne 3 ] && [ -f "$D6/notify.sentinel" ] && grep -q "发 severe 告警" "$log6"; } \
    && ok "exit=$r6, notify 已调用(sentinel 存在)⇒ 云上样环境漂移仍能告警,未被守卫误伤" \
    || bad "r6=$r6 sentinel=$([ -f "$D6/notify.sentinel" ] && echo EXISTS || echo none) out=[$o6]"

  echo "== T7 dump 诊断模式: ARBITER_DUMP 非空 + 漂移 → 仍不发通知 =="
  D7="$TMP/d7"; mk_sbx "$D7"
  printf '@@@FILE:trade-mock.service\n[Service]\nTimeoutStartSec=600\n' > "$D7/dump.txt"
  o7="$(run_sbx "$D7" 1 CLOUD_UNIT_PATROL_ARBITER_DUMP="$D7/dump.txt")"; r7=$?
  log7="$D7/runtime/data/logs/cloud_unit_patrol_launchd.log"
  { [ "$r7" -ne 0 ] && [ ! -f "$D7/notify.sentinel" ] && grep -q "dump 诊断模式" "$log7"; } \
    && ok "exit=$r7, 零通知, 日志标 dump 诊断模式" \
    || bad "r7=$r7 sentinel=$([ -f "$D7/notify.sentinel" ] && echo EXISTS || echo none) out=[$o7]"

  echo "== T8 R2 梯度告警通道: systemd 审计 PASS + R2 梯度 FAIL → notify 可达且键独立 =="
  D8="$TMP/d8"; mk_sbx "$D8"
  o8="$(run_sbx "$D8" 0 CLOUD_UNIT_PATROL_UNITS_DIR="$D8/units" MOCK_R2_AUDIT_RC=1)"; r8=$?
  log8="$D8/runtime/data/logs/cloud_unit_patrol_launchd.log"
  { [ "$r8" -eq 1 ] && [ -f "$D8/notify.sentinel" ] \
    && grep -q "r2_lock_gradient_drift" "$D8/notify.sentinel" \
    && grep -q "R2 上传锁/超时梯度 FAIL" "$log8"; } \
    && ok "exit=$r8, notify 已调用(独立去重键 r2_lock_gradient_drift)" \
    || bad "r8=$r8 sentinel=[$(cat "$D8/notify.sentinel" 2>/dev/null | tr '\n' '|')] out=[$o8]"

  echo "== T9 dump 诊断模式 + R2 梯度 FAIL → 不发通知(仅日志) =="
  D9="$TMP/d9"; mk_sbx "$D9"
  printf '@@@FILE:trade-mock.service\n[Service]\nTimeoutStartSec=600\n' > "$D9/dump.txt"
  o9="$(run_sbx "$D9" 0 CLOUD_UNIT_PATROL_ARBITER_DUMP="$D9/dump.txt" MOCK_R2_AUDIT_RC=1)"; r9=$?
  log9="$D9/runtime/data/logs/cloud_unit_patrol_launchd.log"
  { [ "$r9" -eq 1 ] && [ ! -f "$D9/notify.sentinel" ] && grep -q "R2 梯度 FAIL rc=1" "$log9"; } \
    && ok "exit=$r9, 零通知, 日志标 R2 dump 诊断模式" \
    || bad "r9=$r9 sentinel=$([ -f "$D9/notify.sentinel" ] && echo EXISTS || echo none) out=[$o9]"
else
  echo "  SKIP: 本机无 python3,T4-T7 跳过(云上/CI 有 python 时再跑)"
fi

echo "== 汇总: PASS=$pass FAIL=$fail =="
[ "$fail" -eq 0 ]