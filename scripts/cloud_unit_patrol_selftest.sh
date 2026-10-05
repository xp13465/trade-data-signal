#!/usr/bin/env bash
# cloud_unit_patrol_selftest.sh - cloud_unit_patrol.sh #194 路径加固自测(无副作用,全在 mktemp 沙箱)
#
# 覆盖:
#   T0 bash -n 语法
#   T1 fail-fast: REPO 指向不存在路径 → exit≠0 + stderr 有清晰提示 + 固定位置日志落一行
#   T2 fail-fast: GIT_REPO 指向不存在路径 → exit≠0
#   T3 fail-fast: REPO 下缺 .venv/bin/python → exit≠0
#   T4 $0 推导: 造 <runtime>/scripts -> <gitrepo>/scripts 的 symlink 布局,不带 REPO/GIT_REPO
#      env 直跑 → 自动推导出 REPO=runtime / GIT_REPO=gitrepo,audit 桩 rc=0,日志落在 runtime
#   (T1-T3 均用假的但存在的 REPO/GIT_REPO/.venv 组合,精确把某个量打坏)
#
# 用法: bash scripts/cloud_unit_patrol_selftest.sh
set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
SCRIPT="$HERE/cloud_unit_patrol.sh"
[ -f "$SCRIPT" ] || { echo "找不到 $SCRIPT"; exit 1; }

pass=0; fail=0
ok()   { echo "  PASS: $1"; pass=$((pass+1)); }
bad()  { echo "  FAIL: $1"; fail=$((fail+1)); }
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "== T0 bash -n =="
if bash -n "$SCRIPT"; then ok "bash -n 无语法错误"; else bad "bash -n 报错"; fi

# ── 造一份「一切正常」的沙箱布局(供 T1-T3 在正确基线上只打坏一个量)────────────
GOOD="$TMP/good"
mkdir -p "$GOOD/runtime/data/logs" "$GOOD/runtime/.venv/bin" "$GOOD/gitrepo/scripts"
ln -s "$GOOD/gitrepo/scripts" "$GOOD/runtime/scripts"
ln -s "$(command -v python3 2>/dev/null || echo /usr/bin/python3)" "$GOOD/runtime/.venv/bin/python"

run_patrol() {  # $1=REPO $2=GIT_REPO $3=fatal_log  剩余 env 由调用方 CLOUD_UNIT_PATROL_* 传入
  CLOUD_UNIT_PATROL_FATAL_LOG="$3" \
  env -u PY -u CLOUD_UNIT_PATROL_ARBITER_DUMP -u CLOUD_UNIT_PATROL_SNAPSHOT \
      REPO="$1" GIT_REPO="$2" bash "$SCRIPT" 2>&1
}

echo "== T1 fail-fast: REPO 不存在 =="
f1="$TMP/f1.log"
o1="$(run_patrol /nonexistent/repo-xyz "$GOOD/gitrepo" "$f1")"; r1=$?
{ [ "$r1" -ne 0 ] && \
  printf '%s' "$o1" | grep -q "REPO 目录不存在" && \
  printf '%s' "$o1" | grep -q "Environment=REPO=" && \
  grep -q "REPO 目录不存在" "$f1"; } && ok "exit=$r1, stderr+固定日志均含清晰提示" || bad "r1=$r1 out=[$o1] f1=[$(cat "$f1" 2>/dev/null)]"

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

echo "== T4 \$0 推导(不带 REPO/GIT_REPO env,走 symlink 布局) =="
if command -v python3 >/dev/null 2>&1; then
  D="$TMP/derive"
  mkdir -p "$D/runtime/data/logs" "$D/runtime/.venv/bin" "$D/gitrepo/scripts" "$D/gitrepo/docs/deploy"
  D="$(cd "$D" && pwd -P)"   # 归一物理路径(macOS /var -> /private/var;脚本内部 cd+pwd -P 亦然)
  ln -s "$D/gitrepo/scripts" "$D/runtime/scripts"
  cp "$SCRIPT" "$D/gitrepo/scripts/cloud_unit_patrol.sh"
  ln -s "$(command -v python3)" "$D/runtime/.venv/bin/python"
  # audit 桩:回显收到的 --snapshot(= GIT_REPO 派生值的下游),恒 rc=0
  # 用单引号 heredoc 防变量展开
  cat > "$D/gitrepo/scripts/systemd_timeout_gradient_audit.py" <<'PY'
import sys
args = sys.argv[1:]
snap = args[args.index("--snapshot") + 1] if "--snapshot" in args else "(none)"
print("✓ mock audit ok snapshot=%s" % snap)
sys.exit(0)
PY
  o4="$(CLOUD_UNIT_PATROL_FATAL_LOG="$TMP/f4.log" \
        env -u REPO -u GIT_REPO -u PY -u CLOUD_UNIT_PATROL_ARBITER_DUMP -u CLOUD_UNIT_PATROL_SNAPSHOT \
        bash "$D/runtime/scripts/cloud_unit_patrol.sh" 2>&1)"; r4=$?
  log4="$D/runtime/data/logs/cloud_unit_patrol_launchd.log"
  # 注意:脚本把 audit 输出写进 $LOG(非 stdout),故断言读日志文件而非 $o4
  { [ "$r4" -eq 0 ] && [ -f "$log4" ] && \
    grep -q "mock audit ok" "$log4" && \
    grep -q "snapshot=$D/gitrepo/docs/deploy" "$log4"; } \
    && ok "exit=0, 推导出 REPO=runtime(日志落位)+ GIT_REPO=gitrepo(snapshot 路径正确)" \
    || bad "r4=$r4 out=[$o4] log4=[$(cat "$log4" 2>/dev/null | tr '\n' '|')]"
else
  echo "  SKIP: 本机无 python3,T4 推导测跳过(云上/CI 有 python 时再跑)"
fi

echo "== 汇总: PASS=$pass FAIL=$fail =="
[ "$fail" -eq 0 ]