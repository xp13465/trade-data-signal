#!/usr/bin/env bash
# test_resolve_repo.sh — scripts/lib/repo_paths.sh 单测(#195 批1,方案 §3.7 T1-T6)
#
# 全在 mktemp 沙箱:零网络 / 零外发(不调 notify、不碰 R2、不跑任何业务脚本),
# 不依赖 python3(仅造 dummy 可执行文件满足 -x 校验)。
#
# 覆盖:
#   T1  env 优先:REPO/GIT_REPO 已设 → 值逐字节不变(零改写)
#   T2  case A 推导:经 <REPO>/scripts symlink 调用 → REPO=repo-data, GIT_REPO=repo
#   T3  case B 推导:仓内直跑 → GIT_REPO=仓, REPO=姐妹 trade-data
#       T3b 容错回退:姐妹 trade-data 不存在 → REPO 回退 = GIT_REPO
#   T4  推导值校验失败 → fail-loud(exit 2 + stderr + 固定日志);RESOLVE_REPO_NO_EXIT=1 → rc=0 仅 warn
#   T5  空值 env(REPO="")视同缺失走推导(与 ${VAR:-} 同语义)
#   T6  无副作用:调用者仅新增 REPO/GIT_REPO 两变量;且 lib assign-only(未 export 子 shell 不可见,
#       调用者 export 后可见 = 原 export 语义可逐字节保留)
#
# 用法: bash scripts/tests/test_resolve_repo.sh   (rc=0 = 全过)
set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
LIB="$HERE/../lib/repo_paths.sh"
[ -f "$LIB" ] || { echo "找不到 $LIB"; exit 1; }

pass=0; fail=0
ok()  { echo "  PASS: $1"; pass=$((pass+1)); }
bad() { echo "  FAIL: $1"; fail=$((fail+1)); }

TMP="$(mktemp -d)"; TMP="$(cd "$TMP" && pwd -P)"
trap 'rm -rf "$TMP"' EXIT

# 造 dummy 可执行 python(满足 -x 校验,不真跑)
mk_venv() { mkdir -p "$1/.venv/bin"; printf '#!/bin/sh\nexit 0\n' > "$1/.venv/bin/python"; chmod +x "$1/.venv/bin/python"; }

# run_resolve <caller路径> [env 赋值...] → 打印两行(REPO / GIT_REPO);stderr 丢弃
run_resolve() {
  local caller="$1"; shift
  env -u REPO -u GIT_REPO -u PY "$@" bash -c '
    source "$1" || { echo LIB_MISSING >&2; exit 9; }
    resolve_repo "$2" 2>/dev/null
    printf "%s\n%s\n" "${REPO:-}" "${GIT_REPO:-}"
  ' _ "$LIB" "$caller"
}

echo "== T1 env 优先(零改写) =="
o1="$(run_resolve /nonexistent/whatever.sh REPO=/tmp/x-repo GIT_REPO=/tmp/x-git)"
exp1=$'/tmp/x-repo\n/tmp/x-git'
[ "$o1" = "$exp1" ] && ok "env 值逐字节保留(未推导/未改写)" || bad "o1=[$o1]"

echo "== T2 case A:经 <REPO>/scripts symlink 调用 =="
D2="$TMP/t2"; mkdir -p "$D2/repo/scripts" "$D2/repo-data"
mk_venv "$D2/repo-data"
ln -s "$D2/repo/scripts" "$D2/repo-data/scripts"
o2="$(run_resolve "$D2/repo-data/scripts/x.sh")"
exp2="$D2/repo-data
$D2/repo"
[ "$o2" = "$exp2" ] && ok "REPO=repo-data, GIT_REPO=repo(与 #194 patrol 同逻辑)" || bad "o2=[$o2]"

echo "== T3 case B:仓内直跑(姐妹 trade-data 存在) =="
D3="$TMP/t3"; mkdir -p "$D3/repo/scripts" "$D3/trade-data"
mk_venv "$D3/trade-data"
o3="$(run_resolve "$D3/repo/scripts/x.sh")"
exp3="$D3/trade-data
$D3/repo"
[ "$o3" = "$exp3" ] && ok "GIT_REPO=仓, REPO=姐妹 trade-data" || bad "o3=[$o3]"

echo "== T3b case B 容错回退:无姐妹 trade-data → REPO=GIT_REPO =="
D3b="$TMP/t3b"; mkdir -p "$D3b/myrepo/scripts"; mk_venv "$D3b/myrepo"
o3b="$(run_resolve "$D3b/myrepo/scripts/x.sh")"
exp3b="$D3b/myrepo
$D3b/myrepo"
[ "$o3b" = "$exp3b" ] && ok "回退 REPO=GIT_REPO=仓(防 clone 成 trade-data 名直跑)" || bad "o3b=[$o3b]"

echo "== T4 推导值校验失败 → fail-loud(exit 2 + 固定日志) =="
D4="$TMP/t4"; mkdir -p "$D4/runtime" "$D4/gitrepo/scripts"
mk_venv "$D4/gitrepo"                       # gitrepo 有 venv,runtime 无 → 推导 REPO=runtime 校验失败
ln -s "$D4/gitrepo/scripts" "$D4/runtime/scripts"
cat > "$D4/gitrepo/scripts/t4_wrapper.sh" <<'EOS'
#!/usr/bin/env bash
source "$1" || { echo LIB_MISSING >&2; exit 9; }
resolve_repo "$0"
echo REACHED
EOS
TD4="$D4/tmpdir"; mkdir -p "$TD4"
FLOG="$TD4/resolve_repo_fatal.$(id -un).log"
o4="$(env -u REPO -u GIT_REPO -u RESOLVE_REPO_NO_EXIT TMPDIR="$TD4" bash "$D4/runtime/scripts/t4_wrapper.sh" "$LIB" 2>&1)"; r4=$?
{ [ "$r4" -eq 2 ] && printf '%s' "$o4" | grep -q 'FATAL' \
  && printf '%s' "$o4" | grep -q '\.venv/bin/python' \
  && [ -f "$FLOG" ] && grep -q 'FATAL' "$FLOG" \
  && ! printf '%s' "$o4" | grep -q 'REACHED'; } \
  && ok "exit=2, 含 .venv/bin/python, 固定日志已写, 未继续执行" \
  || bad "r4=$r4 out=[$o4] flog=[$(cat "$FLOG" 2>/dev/null)]"

o4b="$(env -u REPO -u GIT_REPO RESOLVE_REPO_NO_EXIT=1 TMPDIR="$TD4" bash "$D4/runtime/scripts/t4_wrapper.sh" "$LIB" 2>&1)"; r4b=$?
{ [ "$r4b" -eq 0 ] && printf '%s' "$o4b" | grep -q 'REACHED' \
  && printf '%s' "$o4b" | grep -q '降级为 warn'; } \
  && ok "RESOLVE_REPO_NO_EXIT=1 → rc=0 且仅 warn(逃生阀)" \
  || bad "r4b=$r4b out=[$o4b]"

echo "== T5 空值 env(REPO='')视同缺失走推导 =="
o5="$(run_resolve "$D3/repo/scripts/x.sh" REPO= GIT_REPO=)"
[ "$o5" = "$exp3" ] && ok "空串 env → 推导出与 case B 相同值(与 \${VAR:-} 同语义)" || bad "o5=[$o5]"

echo "== T6 无副作用(仅新增 REPO/GIT_REPO)+ assign-only export 语义 =="
# 6a 变量集合逐名 diff:对照/实验两次跑同一脚本(同形代码),唯一差别=是否调 resolve_repo,
#    避免 PIPESTATUS/before 等 shell 记账变量噪声。
cat > "$TMP/t6.sh" <<'EOS'
#!/usr/bin/env bash
source "$1" || { echo LIB_MISSING >&2; exit 9; }
[ "${2:-}" = resolve ] && resolve_repo "${3:-}" 2>/dev/null
compgen -v | sort
EOS
setA="$(env -u REPO -u GIT_REPO -u PY bash "$TMP/t6.sh" "$LIB")"
setB="$(env -u REPO -u GIT_REPO -u PY bash "$TMP/t6.sh" "$LIB" resolve "$D3/repo/scripts/x.sh")"
added="$(comm -13 <(printf '%s\n' "$setA") <(printf '%s\n' "$setB") | tr '\n' ',')"
[ "$added" = "GIT_REPO,REPO," ] \
  && ok "变量集合逐名 diff:仅新增 REPO/GIT_REPO" || bad "added=[$added]"

# 6b assign-only:lib 不 export,调用者按原语义 export 后子 shell 才可见
cat > "$TMP/t6b.sh" <<'EOS'
#!/usr/bin/env bash
source "$1" || { echo LIB_MISSING >&2; exit 9; }
resolve_repo "$2" 2>/dev/null
printf 'CHILD_BEFORE=%s\n' "$(bash -c 'printf %s "${REPO:-UNSET}"')"
export REPO GIT_REPO
printf 'CHILD_AFTER=%s\n' "$(bash -c 'printf %s "${REPO:-UNSET}"')"
EOS
o6="$(env -u REPO -u GIT_REPO -u PY bash "$TMP/t6b.sh" "$LIB" "$D3/repo/scripts/x.sh")"
printf '%s\n' "$o6" | grep -q '^CHILD_BEFORE=UNSET$' \
  && ok "lib assign-only:未 export → 子 shell 不可见(不擅自改 py 侧 os.environ 可见性)" || bad "child_before=[$o6]"
printf '%s\n' "$o6" | grep -q "^CHILD_AFTER=$D3/trade-data$" \
  && ok "调用者 export 后子 shell 可见(原 export 脚本语义可逐字节保留)" || bad "child_after=[$o6]"

echo "== 汇总: PASS=$pass FAIL=$fail =="
[ "$fail" -eq 0 ]
