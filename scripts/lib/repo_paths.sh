#!/usr/bin/env bash
# repo_paths.sh — 共享 REPO / GIT_REPO 单点解析与校验(#195 批1)
#
# 病灶(详见 docs/ops/195-resolve-repo-plan-20261006.md):
#   全仓 57 个 shell 脚本以 `(REPO|GIT_REPO|TRADE_DIR):-/Users/linhuichen/...` 写死 mac
#   默认值,生产(云上)靠 systemd unit 的 `Environment=REPO=/GIT_REPO=` 兜住。一旦那两行
#   Environment 丢失/写错,脚本就拿 mac 路径去 cd / 调 `$PY`(=$REPO/.venv/bin/python)
#   ⇒ rc=127,且 **notify 也调不动**(发信链路同源于坏 REPO = 哑弹)⇒「失败恰恰是最没
#   声音的时候」。本 lib = 单点守卫:env 优先(零改写)> $0 双布局推导 > fail-loud。
#
#   推导为何能「自愈」:云上/mac 的 `<REPO>/scripts` **都是指向 git 仓 scripts/ 的 symlink**
#   (云 `trade-data/scripts -> trade-data-signal/scripts`;mac `trade-data/scripts -> trade/scripts`)
#   ⇒ $0 推导出的 REPO/GIT_REPO 与 unit env 值**逐字相同**。env 丢失时不仅「能报错」,
#   而是**直接继续正确跑**;推导也不成立时才 fail-loud,响铃交 #196 已上线的
#   check_failed_units.py(15min 扫 failed unit),lib **不重复造告警通道**。
#
# 用法(两行模板,只支持在脚本**顶层** source;exit 穿透管道子 shell 由调用方保证):
#   source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/lib/repo_paths.sh" \
#     || { echo "FATAL: repo_paths.sh missing" >&2; exit 2; }
#   resolve_repo "${BASH_SOURCE[0]}"
#   export REPO GIT_REPO            # 仅原本就是 export 的脚本保留(见下方「export 语义」)
#
# 契约(硬约束):
#   - lib 只 **assign**(REPO=/GIT_REPO=),**绝不 export** —— 由调用者按原语义决定是否 export,
#     这样 python 子进程的 os.environ 可见性与迁移前**逐字节一致**(py 侧 ≥12 处
#     os.environ.get("REPO", <mac默认>) 直接受影响,§3.6)。
#   - lib **绝不 notify/发告警/写 R2**(解析失败时 $PY 同源于坏 REPO = 哑弹)。
#   - env 提供值即便「看起来非法」也**只 warn 不 exit**(显式指令优先,可能指向 NFS / 延迟
#     挂载等边界形态);**推导值非法 = FATAL**(此刻脚本无论继续与否都必然坏)。
#   - 只定义 resolve_repo / _resolve_repo_fatal 两个符号,不污染调用者命名空间。
#
# 出口:
#   - 恒定一行 info 到 stderr:`resolve_repo: REPO=<v> (source=env|derived) GIT_REPO=<v> (source=...)`
#   - FATAL:exit 2 + stderr `[resolve_repo] FATAL: ...` + 追加一行到固定落点日志
#     `${TMPDIR:-/tmp}/resolve_repo_fatal.$(id -un).log`(防调用者 `2>/dev/null` 吞掉线索)。
#   - `RESOLVE_REPO_NO_EXIT=1` 时 FATAL 只 warn 不 exit(供单测/本机调试;生产 unit 不设)。

resolve_repo() {
  local caller="${1:-}"
  local _raw_dir="" _real_dir="" _derived_repo="" _derived_git="" _sib=""

  # ── 布局推导(§3.2):逻辑路径(raw)vs 物理路径(real)判 symlink ────────────────
  if [ -n "$caller" ]; then
    _raw_dir="$(cd -- "$(dirname -- "$caller")" 2>/dev/null && pwd || true)"
    _real_dir="$(cd -- "$(dirname -- "$caller")" 2>/dev/null && pwd -P || true)"
  fi
  if [ -n "$_raw_dir" ] && [ -n "$_real_dir" ] && [ "$_raw_dir" != "$_real_dir" ]; then
    # case A: 经 <REPO>/scripts symlink 调用(云上/mac 生产常态)
    _derived_repo="$(dirname -- "$_raw_dir")"
    _derived_git="$(dirname -- "$_real_dir")"
  elif [ -n "$_real_dir" ]; then
    # case B: 仓内直跑(raw==real,或无法判定)—— GIT_REPO=仓,REPO=姐妹 trade-data
    #         (不存在则回退 GIT_REPO 本身,防有人 clone 成 trade-data 目录名直跑)
    _derived_git="$(dirname -- "$_real_dir")"
    _sib="$(dirname -- "$_derived_git")/trade-data"
    if [ -d "$_sib" ]; then _derived_repo="$_sib"; else _derived_repo="$_derived_git"; fi
  fi

  # ── env 优先、零改写;缺失/为空(与 ${VAR:-} 同语义)才用推导值 ──────────────────
  local _src_repo=env _src_git=env
  if [ -z "${REPO:-}" ]; then REPO="$_derived_repo"; _src_repo=derived; fi
  if [ -z "${GIT_REPO:-}" ]; then GIT_REPO="$_derived_git"; _src_git=derived; fi

  printf 'resolve_repo: REPO=%s (source=%s) GIT_REPO=%s (source=%s)\n' \
    "${REPO:-}" "$_src_repo" "${GIT_REPO:-}" "$_src_git" >&2

  # ── 校验(§3.3):推导值失败=FATAL;env 提供值失败=warn 不 exit ─────────────────
  if [ ! -d "${REPO:-}" ]; then
    if [ "$_src_repo" = derived ]; then
      _resolve_repo_fatal "REPO 目录不存在: REPO='${REPO:-}'(来源=derived;env/unit 的 REPO 可能丢失或写错)"
    else
      printf 'resolve_repo: WARN REPO 目录不存在但来源=env, 原样保留不 exit: REPO=%s\n' "${REPO:-}" >&2
    fi
  fi
  if [ ! -d "${GIT_REPO:-}" ]; then
    if [ "$_src_git" = derived ]; then
      _resolve_repo_fatal "GIT_REPO 目录不存在: GIT_REPO='${GIT_REPO:-}'(来源=derived;env/unit 的 GIT_REPO 可能丢失或写错)"
    else
      printf 'resolve_repo: WARN GIT_REPO 目录不存在但来源=env, 原样保留不 exit: GIT_REPO=%s\n' "${GIT_REPO:-}" >&2
    fi
  fi
  if [ ! -x "${REPO:-}/.venv/bin/python" ]; then
    if [ "$_src_repo" = derived ]; then
      _resolve_repo_fatal "REPO 下缺 .venv/bin/python 或不可执行: REPO='${REPO:-}'(来源=derived;REPO 可能指向了错误目录)"
    else
      printf 'resolve_repo: WARN REPO/.venv/bin/python 不可执行但来源=env, 原样保留不 exit: REPO=%s\n' "${REPO:-}" >&2
    fi
  fi
}

_resolve_repo_fatal() {
  # 失败出口:①stderr(unit 无 append 重定向 ⇒ 直接进 systemd journal)②固定位置日志(不依赖坏 REPO)
  local msg="[resolve_repo] FATAL: $*"
  printf '%s\n' "$msg" >&2
  printf '%s %s\n' "$(date '+%F %T')" "$msg" >> "${TMPDIR:-/tmp}/resolve_repo_fatal.$(id -un).log" 2>/dev/null || true
  if [ "${RESOLVE_REPO_NO_EXIT:-}" = "1" ]; then
    printf 'resolve_repo: RESOLVE_REPO_NO_EXIT=1, FATAL 降级为 warn, 不 exit\n' >&2
    return 0
  fi
  exit 2
}
