#!/usr/bin/env bash
# =============================================================================
# ci_selfcheck.sh — push main 后自动自查 GitHub Actions CI 结论
#                   (main-merge.sh 单点实现, 2026-10-07 用户定)
#
# 【背景】2026-10-07 发现 CI(quality-gate-static)自某次 merge 起持续 FAIL 而无人察觉
#   (mac 本机自测绿 ≠ CI Linux 绿: 两边环境不同, 本机过的 CI 未必过)。用户定:
#   **每次 push main 必须自动拉一遍 CI 结论, FAIL 立即暴露**, 不靠人肉想起来看 Actions 页面。
#
# 【契约】
#   - public 仓免鉴权: 禁 token / 禁 `curl -v|-i`(防 token 泄漏, memory
#     curl-v-leaks-auth-token)。只读: GET 两个 endpoint, 绝不写 GitHub 状态。
#   - 轮询: CI run 创建有几十秒延迟 ⇒ 按 head_sha 匹配本次 push 的 main commit,
#     间隔 CI_POLL_INTERVAL 秒, 总上限 CI_POLL_MAX_WAIT 秒。
#   - **workflow 过滤(必要, 非可选)**: 同一次 push 会并发触发多个 workflow
#     (CI Quality Gate / Deploy to GitHub Pages / Deploy CF), 共享同一 head_sha;
#     只按 head_sha 匹配会误取 deploy 的 run ⇒ 必须限定目标 workflow(名字或 path 末段)。
#   - 返回码(调用方据此决策, 不静默 §23.11):
#       0 = CI success
#       1 = CI 非 success(failure / cancelled / timed_out ...) → 调用方以非零退出暴露
#       2 = 未取得结论(网络失败 / 超时 / 未匹配到目标 run) → 打 warn 提示手动复核,
#           不让「push 成功」看起来失败, 但也不静默
#
# 【可单测(不真打网/不 push)】CI_CURL_BIN 可指向 stub 脚本替换 curl(static-only 自测);
#   CI_SELFCHECK_SKIP=1 逃生门(跳过并打醒目提示)。
#
# 【用法】source 本 lib → 调 `ci_selfcheck <已 push 的 commit sha>`。
#   只在脚本顶层 source(与 scripts/lib/repo_paths.sh 同约定)。
# =============================================================================

CI_REPO_SLUG="${CI_REPO_SLUG:-xp13465/trade-data-signal}"
CI_API_BASE="${CI_API_BASE:-https://api.github.com}"
# 目标 workflow(默认 CI 门禁; 同 push 的 deploy-* run 共享 head_sha, 必须靠此过滤区分)
CI_WORKFLOW_NAME="${CI_WORKFLOW_NAME:-CI Quality Gate}"
CI_WORKFLOW_PATH="${CI_WORKFLOW_PATH:-.github/workflows/ci.yml}"
CI_POLL_INTERVAL="${CI_POLL_INTERVAL:-15}"      # 轮询间隔(秒)
CI_POLL_MAX_WAIT="${CI_POLL_MAX_WAIT:-480}"     # 总上限(秒), 默认 8 分钟
CI_CURL_BIN="${CI_CURL_BIN:-curl}"              # 单测注入点(stub 命令替换 curl)
CI_SELFCHECK_SKIP="${CI_SELFCHECK_SKIP:-0}"     # =1 跳过自查(逃生门)
CI_CURL_MAX_TIME="${CI_CURL_MAX_TIME:-20}"      # 单次 HTTP 超时(秒)

# 内部: GET 一个 URL 到 stdout(失败返回非零)。禁 -v/-i(防 token 泄漏)。
_ci_fetch() {
  local url="$1"
  "$CI_CURL_BIN" -s --max-time "$CI_CURL_MAX_TIME" "$url"
}

# 内部: 从 runs JSON(stdin)里找匹配「目标 sha + 目标 workflow」的 run,
#        命中 → 打印 TSV: "<id>\t<status>\t<conclusion>\t<run_number>\t<html_url>";
#        无命中 → "NORUN"; JSON 解析失败 → "PARSE_ERR"。
#        sha 匹配: 全等 / 目标含 run 前 8 位兜底(本次 push sha 与 run.head_sha 应全等)。
_ci_pick_run() {
  local target_sha="$1"
  local py
  py=$(cat <<'PYEOF'
import json, sys
target = sys.argv[1]
wf_name = sys.argv[2]
wf_path = sys.argv[3]
wf_file = wf_path.rsplit("/", 1)[-1]
try:
    d = json.load(sys.stdin)
except Exception:
    print("PARSE_ERR"); sys.exit(0)
for r in (d.get("workflow_runs") or []):
    sha = r.get("head_sha") or ""
    if not (sha == target or sha.startswith(target) or (len(target) >= 8 and target.startswith(sha[:8]))):
        continue
    nm = r.get("name") or ""
    pth = r.get("path") or ""
    if nm == wf_name or pth == wf_path or pth.endswith("/" + wf_file):
        print("\t".join(str(r.get(k) or "") for k in ("id", "status", "conclusion", "run_number", "html_url")))
        sys.exit(0)
print("NORUN")
PYEOF
)
  # 脚本经 -c 传入, JSON 经 stdin 管道(勿用 `python3 - <<HEREDOC`, heredoc 会顶掉 stdin)
  "${PY:-python3}" -c "$py" "$target_sha" "$CI_WORKFLOW_NAME" "$CI_WORKFLOW_PATH"
}

# 内部: 从 jobs JSON(stdin)提取「非 success/skipped」的 job 名, 逗号分隔(用于 FAIL 告警)。
_ci_failed_jobs() {
  local py
  py=$(cat <<'PYEOF'
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    print(""); sys.exit(0)
bad = []
for j in (d.get("jobs") or []):
    c = j.get("conclusion")
    if c not in ("success", "skipped"):
        bad.append(f"{j.get('name')}({c or '未完成'})")
print(", ".join(bad))
PYEOF
)
  "${PY:-python3}" -c "$py"
}

# 出口: ci_selfcheck <commit sha>; 返回 0(success)/1(FAIL)/2(未取得结论)
ci_selfcheck() {
  local target_sha="${1:-}"

  if [ "$CI_SELFCHECK_SKIP" = "1" ]; then
    echo ""
    echo "  ⏭ CI 自查已跳过(CI_SELFCHECK_SKIP=1 逃生门): 本次 push 未自动复核 CI 结论,"
    echo "     请手动核对: curl -s 'https://api.github.com/repos/$CI_REPO_SLUG/actions/runs?per_page=5'"
    echo ""
    return 2
  fi
  if [ -z "$target_sha" ]; then
    echo "⚠️ [CI 自查] 未提供 commit sha, 跳过自查(请手动核对 CI)" >&2
    return 2
  fi

  local short="${target_sha:0:8}"
  echo "--- 11. push main 后自动自查 CI 结论(2026-10-07 用户定, §23.11 不静默) ---"
  echo "  轮询 GitHub Actions: 仓=$CI_REPO_SLUG 目标=$short workflow='$CI_WORKFLOW_NAME'"
  echo "  间隔=${CI_POLL_INTERVAL}s 上限=${CI_POLL_MAX_WAIT}s"

  local runs_url="$CI_API_BASE/repos/$CI_REPO_SLUG/actions/runs?per_page=5"
  local deadline=$(( $(date +%s) + CI_POLL_MAX_WAIT ))
  local json pick run_id status conclusion run_number run_html
  local done=0
  while :; do
    json="$(_ci_fetch "$runs_url" 2>/dev/null)" || json=""
    if [ -z "$json" ]; then
      echo "  · CI API 暂不可达(网络失败/超时), ${CI_POLL_INTERVAL}s 后重试..."
    else
      pick="$(printf '%s' "$json" | _ci_pick_run "$target_sha" 2>/dev/null || true)"
      if [ "$pick" = "NORUN" ] || [ "$pick" = "PARSE_ERR" ] || [ -z "$pick" ]; then
        echo "  · 未匹配到目标 commit $short 的 '$CI_WORKFLOW_NAME' run(CI 创建有延迟), ${CI_POLL_INTERVAL}s 后重试..."
      else
        # F1: 用 cut -f 按 TAB 切分 —— 不用 read: 未完成 run 的 conclusion 为 null(空字段),
        # 空 TAB 会被 read 当 IFS 空白折叠 ⇒ 字段左移(run_number 误取 html_url)。
        run_id="$(printf '%s' "$pick" | cut -f1)"; status="$(printf '%s' "$pick" | cut -f2)"; conclusion="$(printf '%s' "$pick" | cut -f3)"
        run_number="$(printf '%s' "$pick" | cut -f4)"; run_html="$(printf '%s' "$pick" | cut -f5)"
        if [ "$status" = "completed" ]; then
          done=1
          break
        fi
        echo "  · CI run #$run_number(status=$status, 未完成), ${CI_POLL_INTERVAL}s 后重试..."
      fi
    fi
    if [ "$(date +%s)" -ge "$deadline" ]; then
      break
    fi
    sleep "$CI_POLL_INTERVAL"
  done

  # ── 未取得结论(超时 / 全程网络失败 / 始终无匹配) ──────────────────────────
  if [ "$done" != "1" ]; then
    echo ""
    echo "  ⚠️ CI 自查未取得结论(超时 ${CI_POLL_MAX_WAIT}s / 网络不可达 / 未匹配到 CI run)"
    echo "     —— 本次 push main 已成功, 但 CI 结论未验证(不判 push 失败, 但请务必手动复核)"
    echo "     手动复核: curl -s 'https://api.github.com/repos/$CI_REPO_SLUG/actions/runs?per_page=5'"
    echo "       或直接看 https://github.com/$CI_REPO_SLUG/actions"
    echo ""
    return 2
  fi

  # ── 拿到 completed run ────────────────────────────────────────────────────
  if [ "$conclusion" = "success" ]; then
    echo "✓ CI 结论 success(run #$run_number)"
    return 0
  fi

  # FAIL: 取失败 job 名 + 醒目告警 + 非零返回(调用方据此 exit 非零, §23.11 绝不静默)
  local jobs_url="$CI_API_BASE/repos/$CI_REPO_SLUG/actions/runs/$run_id/jobs"
  local jobs_json failed_jobs=""
  jobs_json="$(_ci_fetch "$jobs_url" 2>/dev/null || true)"
  if [ -n "$jobs_json" ]; then
    failed_jobs="$(printf '%s' "$jobs_json" | _ci_failed_jobs 2>/dev/null || true)"
  fi
  echo "" >&2
  echo "  ██████████████████████████████████████████████████████████████████████" >&2
  echo "  [!!] CI 门禁 FAIL: run #$run_number 结论 = $conclusion" >&2
  echo "       run: $run_html" >&2
  if [ -n "$failed_jobs" ]; then
    echo "       失败 job: $failed_jobs" >&2
  else
    echo "       失败 job: (未能取得 jobs 明细, 请打开上方 run 链接查看)" >&2
  fi
  echo "  ██████████████████████████████████████████████████████████████████████" >&2
  echo "" >&2
  echo "✗ main 已 push 成功, 但 CI 门禁结论非 success ⇒ 请主控立即派修(§23.11 绝不静默)" >&2
  return 1
}
