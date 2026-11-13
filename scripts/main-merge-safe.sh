#!/usr/bin/env bash
# =============================================================================
# main-merge-safe.sh - main-merge.sh 的调用包装(退出码防吞, 2026-11-13)
#
# 背景: 调用方曾用 `bash scripts/main-merge.sh X > log 2>&1; echo ...` 或
#       `... | tail` 这类写法, 行尾命令是 echo/tail ⇒ 拿到的是行尾命令的 rc
#       (恒 0), main-merge.sh 闸门的真实退出码(失败=非 0)被吞, 只认了
#       "启动成功/日志横幅"。2026-11-13 Codex 核查 filter 1/5 确认闸门本体正确,
#       问题在调用包装 ⇒ 本脚本只修包装层, **不改 main-merge.sh 一行**。
#
# 用法:
#   bash scripts/main-merge-safe.sh <feat 分支名> [logfile]
#     logfile 缺省 = /tmp/main-merge-<feat 去掉斜杠>-<YYYYmmdd-HHMMSS>.log
#
# 行为:
#   - 按脚本自身位置定位同目录的 main-merge.sh, 执行并透传分支名;
#   - stdout+stderr 全量落日志文件, 同时 tee 透传终端;
#   - 用 PIPESTATUS[0] 取 main-merge.sh 本体的真实退出码, 末行显式打印
#     `=== main-merge 真实退出码: <rc> (日志: <path>) ===` 并以同一 rc 退出;
#   - 参数缺失 / 不在 git 仓库 / 分支不存在 ⇒ 非零退出并说明, 不静默(§23.11)。
#
# 值班约定(on-call convention, 后来者必读):
#   跑 main-merge 一律走本包装, 禁止再写会吞 rc 的行尾 `; echo` / `| tail`;
#   若必须直接调 main-merge.sh, 结尾用 `rc=$?` 先取值再输出, 绝不让
#   echo/tail 成为脚本/命令行的最后一条命令。
# =============================================================================
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
MAIN_MERGE="$SCRIPT_DIR/main-merge.sh"

if [[ $# -lt 1 || -z "$1" ]]; then
  echo "[main-merge-safe] 参数缺失。用法: bash scripts/main-merge-safe.sh <feat 分支名> [logfile]" >&2
  exit 3
fi
FEAT="$1"

if [[ ! -f "$MAIN_MERGE" ]]; then
  echo "[main-merge-safe] 找不到闸门本体: $MAIN_MERGE(本脚本必须与 main-merge.sh 同目录部署)" >&2
  exit 3
fi

# 前置校验: 在 git 仓库内 + 分支存在(本地或 origin); 不存在=说明+非零退出, 不静默
if ! git -C "$REPO" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "[main-merge-safe] $REPO 不是 git 仓库, 拒绝执行" >&2
  exit 3
fi
if ! git -C "$REPO" show-ref --verify --quiet "refs/heads/$FEAT" \
   && ! git -C "$REPO" show-ref --verify --quiet "refs/remotes/origin/$FEAT"; then
  echo "[main-merge-safe] 分支不存在(本地 refs/heads 与 origin 均无): $FEAT" >&2
  exit 3
fi

# 日志: 显式传入 or 默认 /tmp/main-merge-<feat 去斜杠>-<时间戳>.log
if [[ $# -ge 2 && -n "$2" ]]; then
  LOG="$2"
else
  FEAT_SAFE="${FEAT//\//-}"
  LOG="/tmp/main-merge-${FEAT_SAFE}-$(date +%Y%m%d-%H%M%S).log"
fi

# 不用 set -e / pipefail: 管道失败要被捕获而不是当场退出。
# tee 全量透传终端 + 落日志; PIPESTATUS[0] = main-merge.sh 本体的真实 rc
# (不用 `$?`: echo/tee 之后取 $? 拿到的是行尾命令的 rc, 闸门失败会被吞——
#  本脚本存在的唯一理由就是这一行, 见头部背景)。
bash "$MAIN_MERGE" "$FEAT" 2>&1 | tee "$LOG"
# 注: macOS bash 3.2 下任何赋值语句都会使 PIPESTATUS 失效(set -u 直接报 unbound),
#     必须用一条数组拷贝把两个 rc 一次性取出, 再拆读。
PS=( "${PIPESTATUS[@]}" ); RC="${PS[0]}"; TEE_RC="${PS[1]}"

if [[ "$TEE_RC" -ne 0 ]]; then
  # tee 失败不覆盖闸门 rc, 但必须不静默(§23.11)
  echo "[main-merge-safe][!!] tee 写日志疑似失败(rc=$TEE_RC, 日志: $LOG), 输出可能未完整落盘" >&2
fi

SUMMARY="=== main-merge 真实退出码: $RC (日志: $LOG) ==="
echo "$SUMMARY"
echo "$SUMMARY" >> "$LOG" 2>/dev/null || echo "[main-merge-safe][!!] 摘要行写回日志失败(不影响退出码传递)" >&2
exit "$RC"
