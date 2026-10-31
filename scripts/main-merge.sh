#!/usr/bin/env bash
# =============================================================================
# main-merge.sh - push main 统一入口(防再犯机制 D, 2026-08-19 实施)
#
# 背景: 冲突覆盖根因 docs/conflict-overwrite-rootcause-2026-08-18.md(§五.D) +
#       诱因链 docs/conflict-overwrite-triggers-2026-08-18.md(缺口③ push 控制面分散)。
#       08-18 多 agent 各自直接 push main 缺 commit / deploy 非 main 分支 push HEAD:main
#       带上 feat commit(根因 §三.4)。本脚本把「merge + push main」收敛成唯一权威入口:
#       agent 只推 feat 分支, merge+push main 一律由主控走本脚本。
#
# 流程(严格按此, 任一 FAIL 即停不静默):
#   1. 校验入参 feat 分支名存在 + 当前在 main
#   2. §14 安全窗口检查: 盘后时点(15:35/16:00/17:50/20:35/22:00)拒绝 merge+push, 提示
#   3. git fetch origin + checkout main + 确认 main 已是最新
#   4. 校验 feat 分支 base 新鲜: 最近一次 rebase 基点距 origin/main 无净回退(调 check_version_progress)
#   5. merge feat(冲突即停报, 绝不静默 §23.11)
#   6. 若 feat 改了前端源码(9 源: app/lab/common/style/lab.css/purpose-notes/kelly-review-notes/kelly-reports-content/index.html): 统一跑 build_min + bump_asset_version(版本串唯一权威入口, 机制 C; index.html 改动触发统一 bump, build_min 无源变更自然产出不变);
#      触发 bump = 一次「发版」→ 打印「发版本时同步 work-mode-standard/ 通用包」软提醒(README §4 维护约定, 2026-10-15 拍板; 只提醒不阻断)
#   7. §24⑤ 校验 index 引用 == 实际文件内容 md5(统一 bump 后内容哈希==引用)
#   7.8b R2 上传锁超时梯度审计(2026-10-31 常态化): 内层锁等待/工作预算 vs 外层 systemd 墙,
#       仓库侧(脚本文面量 + 云上快照)FAIL 阻断; 云上侧由 trade-cloud-unit-patrol.timer 跑
#       --check-snapshot(真 unit 值)只告警。背景 = overfit_monitor 倒置漏网多天(L55/§22)。
#   7.9 L52 pre-merge 全量 pytest(2026-10-18 批3 挂): feat 改了 scripts/ 下任何源码 ⇒ 跑全量
#       `pytest -q scripts/tests/`(测试里有源码形状守卫, 源形状一变即红), FAIL 阻断本次 merge ——
#       把 L52 型红从「merge 后 CI 红在 main(#891)」前移到「merge 前 feat 上红」。约 150s。
#       逃生门 MAIN_MERGE_SKIP_PYTEST=1(跳时醒目日志, 不静默); 找不到带 pytest 的解释器 = 阻断。
#   7.7 console 洁净度哨兵(#133 复发防线, 2026-10-03 挂): 打线上真实 URL 验 0 CSP 违规 +
#       0 pageerror; 违规 exit1 阻断发版; 线上不可达 exit2 打醒目告警后放行; SKIP_CONSOLE_CLEAN=1 逃生门
#   8. 调 check_version_progress.py(A/B: 版本串倒退哨兵 + merge 净回退校验) → FAIL 阻断
#   8.5 pending-index 销账软提醒(只提醒不阻断不自动改, 2026-08-22 用户授权流程小机制)
#   9. commit(自动追加 Co-Authored-By) + push main
#   10. merge 即同步: push main 成功后自动 ssh 云上 git pull(2026-09-19 用户定, 根治「忘 pull」;
#       云上 /home/ubuntu/code/trade-data 手动 pull, 不 pull 不生效。失败不静默打醒目 [!!] 告警 + exit 6)
#   11. push main 后自动自查 CI 结论(2026-10-07 用户定): 轮询 GitHub Actions, 按 head_sha +
#       目标 workflow 匹配本次 push 的 CI run, 拉到 completed 结论: success 打印一行正常退出;
#       FAIL 醒目告警(run 编号/html_url/失败 job 名)+ 非零退出 exit 9(§23.11 绝不静默);
#       拿不到结论(网络/超时/无匹配)warn + 提示手动复核(不让 push 看起来失败)。
#       实现见 scripts/lib/ci_selfcheck.sh(独立 lib, 可单测);CI_SELFCHECK_SKIP=1 逃生门。
#
# 用法:
#   bash scripts/main-merge.sh <feat 分支名> [--dry-run]
#   --dry-run: 演练不真 merge/push(第 5/9 步跳过, 其余校验照跑)
#
# 依赖: scripts/check_version_progress.py(机制 A/B) + scripts/build_min.py + scripts/bump_asset_version.py(机制 C)
#       + scripts/lib/ci_selfcheck.sh(第 11 步 push 后 CI 自查)
# =============================================================================
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
GIT="git -C $REPO"
PY="python3"

# push 后 CI 自查(独立 lib, 可单测; 见 scripts/lib/ci_selfcheck.sh)。
# lib 缺失/语法坏不阻断 merge(降级为 warn 桩, 不静默), 避免自查机制本身把 push main 卡死。
# F2: 用 `eval ... || 桩` 而非 `if ! source ...`: bash 3.2(set -e)遇 source 打不开/解析失败
#     会在条件上下文里直接静默退出(桩/提示全不执行); eval 形式「在位/缺失/语法坏」三态均正确降级。
#     勿改子壳形式 `(source ...)`, 成功路径函数会留在子壳致父 shell 未定义。
# shellcheck source=lib/ci_selfcheck.sh
eval ". \"$REPO/scripts/lib/ci_selfcheck.sh\"" 2>/dev/null || \
  ci_selfcheck() { echo "⚠️ 缺 scripts/lib/ci_selfcheck.sh, 跳过 push 后 CI 自查(请手动核对 CI)" >&2; return 2; }

DRY_RUN=0
# --dry-run 可在任意位置出现(防手滑把 <feat> --dry-run 顺序写反被当真实运行 → 意外 push main)
# 用法正文写 <feat> [--dry-run], 但此处容忍任意位置, 提高安全性(§23.11 防意外)
case " $* " in
  *" --dry-run "*) DRY_RUN=1;;
esac
# 移除 --dry-run 保留 feat
ARGS=()
for a in "$@"; do
  if [[ "$a" != "--dry-run" ]]; then ARGS+=("$a"); fi
done
FEAT="${ARGS[0]:-}"
if [[ -z "$FEAT" ]]; then
  echo "✗ 用法: bash scripts/main-merge.sh <feat 分支名> [--dry-run]" >&2
  exit 2
fi

# 盘后定时任务时点(§14 安全窗口): 这些时刻 ±缓冲内不 merge+push main
DISK_AFTER_TIMES=("15:35" "16:00" "17:50" "20:35" "22:00")
# 缓冲分钟: update_all 17:50 启动后可能持续几分钟, 精确匹配会漏掉 17:51 push 放行
DISK_AFTER_BUFFER_MIN=5

current_time() {
  # Asia/Shanghai 时区 HH:MM
  TZ=Asia/Shanghai date +%H:%M
}

time_to_min() {
  # HH:MM → 当日分钟数(10# 防 08:xx 被当八进制)
  local hhmm="$1"
  local hh="${hhmm%%:*}" mm="${hhmm##*:}"
  echo $(( 10#$hh * 60 + 10#$mm ))
}

# 今日是否交易日(2026-09-19 用户定, 与 §8「休市可随时跑」口径对齐)
# 复用 trade/app/calendar.py 节假日历(周末+法定节假日休市; calendar 源缺失降级周末判断, 权威口径)
# 退出码: 0=交易日  1=非交易日  2=判断失败(import 异常/日历不可得)
# 判断失败必须与正常非交易日区分(正常非交易日 exit 1 放开; 失败 exit 2 由调用方按交易日保守拦, §14 P0 宁多拦不可漏拦)
is_trading_day_now() {
  # python 打印状态码(1=交易日 0=非交易日 2=异常), 函数再归一成退出码,
  # 避免 cd "$REPO" 失败(非0错误码==python 正常 sys.exit(1) 混淆)被误判为非交易日放开
  local out
  out="$( cd "$REPO" 2>/dev/null && "$PY" -c "
import sys, datetime as _dt
sys.path.insert(0, '$REPO')
try:
    from app.calendar import is_trading_day
    print(1 if is_trading_day(_dt.date.today()) else 0)
except Exception:
    print(2)
" 2>/dev/null )" || out=2
  case "$out" in
    1) return 0;;   # 交易日
    0) return 1;;   # 非交易日
    *) return 2;;   # 判断失败(cd失败/import异常/非预期输出)
  esac
}

check_disk_after() {
  # 非交易日(周末/节假日休市)跳过盘后时点闸, 与 §8「休市可随时跑」对齐
  # 交易日判断失败(exit 2)→ 按交易日保守处理照常检查盘后时点, 不放开(§14 P0)
  local trc=0
  is_trading_day_now || trc=$?
  if [[ "$trc" -eq 1 ]]; then
    echo "✓ §14 安全窗口: 今天非交易日(休市), 跳过盘后时点闸(§8 口径: 休市可随时跑)"
    return 0
  fi
  if [[ "$trc" -ne 0 ]]; then
    echo "⚠️ 今日交易日判断失败(exit $trc), 按交易日保守处理, 继续检查盘后时点闸(§14 P0 宁多拦不可漏拦)" >&2
  fi
  local now; now="$(current_time)"
  local now_min; now_min="$(time_to_min "$now")"
  local t t_min diff
  for t in "${DISK_AFTER_TIMES[@]}"; do
    t_min="$(time_to_min "$t")"
    diff=$(( now_min - t_min ))
    if [[ $diff -lt 0 ]]; then diff=$(( -diff )); fi
    if [[ "$diff" -le "$DISK_AFTER_BUFFER_MIN" ]]; then
      echo "✗ 当前时点 $now 落在盘后定时任务 $t ±${DISK_AFTER_BUFFER_MIN}min 缓冲窗口内, 拒绝 merge+push main(§14 生产稳定性 P0)" >&2
      echo "  建议挪到安全窗口 23:00 后或避开该时点再跑。" >&2
      exit 3
    fi
  done
  echo "✓ §14 安全窗口: 当前时点 $now 未撞盘后任务时点(±${DISK_AFTER_BUFFER_MIN}min)"
}

echo "=== main-merge.sh(push main 统一入口, 防再犯机制 D) ==="
echo "  repo   : $REPO"
echo "  feat   : $FEAT"
echo "  dry-run: $DRY_RUN"

# 1. 校验当前分支 + feat 分支存在
CUR_BRANCH="$($GIT branch --show-current)"
if [[ "$CUR_BRANCH" != "main" ]]; then
  echo "✗ 当前分支是 $CUR_BRANCH, 非 main。请先 checkout main 再跑本脚本" >&2
  exit 2
fi
if ! $GIT show-ref --verify --quiet "refs/heads/$FEAT"; then
  echo "✗ feat 分支 $FEAT 不存在(refs/heads/$FEAT)" >&2
  exit 2
fi

# 2. §14 安全窗口检查
check_disk_after

# 3. fetch + 确认 main 最新(区分 领先/落后/分叉 三态; 本地领先跳过 rebase; rebase 前查工作区干净)
echo "--- fetch origin ---"
$GIT fetch origin
LOCAL_MAIN="$($GIT rev-parse main)"
REMOTE_MAIN="$($GIT rev-parse origin/main)"
if [[ "$LOCAL_MAIN" == "$REMOTE_MAIN" ]]; then
  echo "✓ main 已与 origin/main 一致(${REMOTE_MAIN:0:8}), 无需 rebase"
elif $GIT merge-base --is-ancestor origin/main main 2>/dev/null; then
  # origin/main 是 main 祖先 → 本地领先(存在未 push 的本地 commit), rebase 是多余操作直接跳过
  LOCAL_AHEAD="$($GIT rev-list --count origin/main..main)"
  echo "✓ 本地 main 领先 origin/main ${LOCAL_AHEAD} commit(本地未 push), 跳过 rebase(多余操作)"
else
  # 落后 或 分叉 → 需 rebase; rebase 前显式查工作区干净
  if ! $GIT diff --quiet || ! $GIT diff --cached --quiet; then
    echo "✗ 需要 rebase 但工作区有未提交改动。请先处理工作区再跑本脚本" >&2
    echo "  绝不静默 stash/丢弃改动(§23.11): 请主控人工决定这些改动的去留" >&2
    echo "  --- 当前未提交改动 ---" >&2
    $GIT status --porcelain | head -20 >&2
    exit 6
  fi
  if $GIT merge-base --is-ancestor main origin/main 2>/dev/null; then
    echo "⚠️ 本地 main 落后 origin/main, 执行 rebase 快进(origin 已含本地没有的 commit)"
  else
    echo "⚠️ 本地 main 与 origin/main 分叉, 执行 rebase(可能产生冲突, 冲突即停不静默 §23.11)"
  fi
  if ! $GIT rebase origin/main; then
    echo "✗ rebase main 冲突/失败, 已 abort。请主控人工处理本地 main 未推送改动后, 再跑本脚本(§23.11 绝不静默)" >&2
    $GIT rebase --abort >/dev/null 2>&1 || true
    exit 7
  fi
  echo "✓ rebase 完成"
fi
echo "✓ main 位于 origin/main(${REMOTE_MAIN:0:8}) 之上"

# 4. 校验 feat 分支 base 新鲜(缺口① 事前防线): feat 的 base 是否落后 origin/main 过多
#    用 merge-base 看 feat 相对 origin/main 的落后 commit 数; 落后过多则提示先 rebase
FEAT_MERGE_BASE="$($GIT merge-base origin/main "$FEAT")"
BEHIND_COUNT="$($GIT rev-list --count "$FEAT_MERGE_BASE"..origin/main)"
echo "  feat($FEAT) merge-base=$($GIT rev-parse "$FEAT" | cut -c1-8), 相对 origin/main 落后 $BEHIND_COUNT commit"
if [[ "$BEHIND_COUNT" -gt 0 ]]; then
  echo "⚠️ feat 分支 $FEAT 相对 origin/main 落后 $BEHIND_COUNT commit, base 可能不新鲜"
  echo "  建议: git fetch origin && git -C $REPO rebase origin/main (在 feat 分支上) 后再 merge"
  echo "  (缺口① base 新鲜度事前校验: base 落后仍可继续, 但 merge 前请确认无冲突/无净回退)"
fi

# 4.5 记录 merge 前 origin/main 位置(供 8.5 步销账提醒划定「本次 merge 带入的 commit」范围; fetch/rebase 后已定型)
PRE_MERGE_BASE="$($GIT rev-parse origin/main)"

# 5. merge feat(冲突即停, 绝不静默 §23.11)
echo "--- merge $FEAT into main ---"
echo "  checkout main"
$GIT checkout main
MERGE_MSG="merge(feat/$FEAT): 统一入口合并 $FEAT 入 main"
if [[ "$DRY_RUN" == "1" ]]; then
  echo "  [dry-run] 跳过实际 merge"
else
  if ! $GIT merge "$FEAT" --no-edit -m "$MERGE_MSG"; then
    echo "✗ merge 冲突(或失败), 已停下。绝不静默 resolve(§23.11)" >&2
    echo "  请主控人工处理冲突后, 再重跑本脚本或手动 commit" >&2
    exit 4
  fi
  echo "✓ merge 成功(无冲突)"
fi

# 6. 若 feat 改了前端源码, 统一 build_min + bump(机制 C 版本串唯一权威入口)
#    检测: feat 相对 origin/main 是否触碰关键源文件
#    ⚠️ 产物清单必须与 scripts/build_min.py 全量对齐(8 对):
#      common/purpose-notes/kelly-review-notes/kelly-reports-content/app/lab 的 .min.js
#      + style.min.css + lab.min.css。
#    缺失任何源(尤其 3 个 notes 公示文件, §21 典型场景只改 purpose-notes.js)= 检测不到→不 bump→公示不上线。
# index.html 也在内(§24② 对齐, 2026-09-06): feat 只改 index.html(如 #99 toast changelog)
#   = 前端源码改动, 必须统一 bump → SW 才提示更新。build_min 对纯 index.html 改动无源变更
#   自然产出不变只跑 bump_asset_version.py(重写 index.html ?v= + sw.js CACHE_VERSION)。
SRC_FILES=("app.js" "lab.js" "common.js" "style.css" "lab.css" \
           "purpose-notes.js" "kelly-review-notes.js" "kelly-reports-content.js" \
           "index.html")
CHANGED_SRC=""
for src in "${SRC_FILES[@]}"; do
  if $GIT diff --quiet "origin/main...$FEAT" -- "static-site/$src" 2>/dev/null; then
    :
  else
    CHANGED_SRC="$CHANGED_SRC $src"
  fi
done

if [[ -n "$CHANGED_SRC" ]]; then
  echo "--- feat 触碰前端源码:$CHANGED_SRC, 统一 build_min + bump(版本串唯一权威入口) ---"
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "  [dry-run] 跳过 build_min/bump"
  else
    ( cd "$REPO" && "$PY" scripts/build_min.py )
    ( cd "$REPO" && "$PY" scripts/bump_asset_version.py )
    # bump 后 main 工作区 index.html/min 已变, 需要 commit 才走后续校验
    echo "  ✓ build_min + bump 完成, 待 commit"
  fi

  # 发版本时同步通用包 — 软提醒(README §4 维护约定, 2026-10-15 用户拍板; 只提醒不阻断不自动改)
  #   触发点 = 本次「确实 bump 版本」的分支(CHANGED_SRC 非空, 与上面第 6 步 bump 判定同一条件):
  #   本次 merge 触发版本 bump = 一次「发版」, 提醒顺手同步仓内通用包 work-mode-standard/
  #   (其 README §4「维护约定」: 来源项目每次发版本时把「同步通用包」当发版清单一项)。
  #   未触发 bump(未触碰前端源码)则不打该行; 纯输出, 对控制流零影响(不改退出码/不阻断/不加失败路径)。
  #   dry-run 也打印(演练预览发版提示), 便于本地验证本提醒分支。
  echo ""
  echo "⚠ 本次发版(触发版本 bump):记得同步 work-mode-standard/ 通用包(README §4 维护约定:发版本时同步)"
  echo ""
else
  echo "  feat 未触碰前端源码(9 源: app/lab/common/style/lab.css/purpose-notes/kelly-review-notes/kelly-reports-content/index.html), 跳过统一 bump"
fi

# ---- 6.5 changelog 补登自动同步(#83 C8, 2026-09-09 用户拍板): bump 后保证 changelog.json 必有该版本条目 ----
# 背景: 2026-09-08 O1 deploy 被 check_changelog_current_version 拦截(static-site/changelog.json 缺
#   新版本串条目, update_all_20260908_1750.log L1429), 人工补登才放行(deploy_20260908_2307.log
#   L683)。根因 = bump 版本串(main-merge.sh 统一 bump)与 changelog 补登是两条链路, 改代码忘记补登
#   就断链 → 本步把补登并入 bump 流程(用户拍板 #83)。
# 判定: 与 check_data_integrity.check_changelog_current_version 同源 = index.html lab-asset-url
#   meta 的 ?v=<ver> 必须在 changelog.json 有非空 list 条目(check 只在缺失时 FAIL 阻断, 存在即 PASS)。
# 条目来源: feat 分支 HEAD commit 标题(feat 最后一次功能 commit 的 message 第一行), 提取不到给
#   占位「版本发布」——check 要求「存在」条目即可 PASS, 不缺行即可(说明可后续手工润色)。
# 兼容: 已登记条目(bump 前已手工补登或本分支已补)= 跳过不动, pre-main-merge 手工补登仍可用;
#   未 bump 版本串(上面 CHANGED_SRC 为空)也跑一遍补登 → 历史断链(老版本无条目)一并兜底修复。
if [[ "$DRY_RUN" == "1" ]]; then
  echo "  [dry-run] 跳过 changelog 补登"
else
  echo "--- changelog 补登自动同步(#83 C8) ---"
  export CHANGELOG_REPO="$REPO" CHANGELOG_IDX="$REPO/static-site/index.html" \
         CHANGELOG_PATH="$REPO/static-site/changelog.json" CHANGELOG_FEAT="$FEAT"
  if "$PY" - <<'PYEOF'
import json, os, re, subprocess, sys
from pathlib import Path

idx = Path(os.environ["CHANGELOG_IDX"])
chg = Path(os.environ["CHANGELOG_PATH"])
feat = os.environ.get("CHANGELOG_FEAT", "")
repo = os.environ.get("CHANGELOG_REPO", "")

if not idx.exists() or not chg.exists():
    print(f"⚠ changelog 补登跳过: index.html({idx.exists()}) 或 changelog.json({chg.exists()}) 不存在")
    sys.exit(0)
text = idx.read_text(encoding="utf-8", errors="replace")
m = re.search(r'meta name=["\']lab-asset-url["\'][^>]*content=["\'][^"\']*[?&]v=([^&"\']+)', text)
if not m:
    print("⚠ changelog 补登跳过: index.html 未找到 lab-asset-url 版本串")
    sys.exit(0)
ver = m.group(1).strip()
data = json.loads(chg.read_text(encoding="utf-8", errors="replace"))
have = data.get(ver)
if isinstance(have, list) and have:
    print(f"✓ changelog.json 已登记 {ver}({len(have)} 条), 无需补登")
    sys.exit(0)
# 条目说明: feat 分支 HEAD commit 标题(取不到给占位「版本发布」)
msg = ""
try:
    out = subprocess.run(["git", "-C", repo, "log", "-1", "--format=%s", feat],
                         capture_output=True, text=True, timeout=10)
    msg = (out.stdout or "").strip()
except Exception:
    msg = ""
if not msg:
    msg = "版本发布"
data.setdefault(ver, []).append(msg)
# 保持 ensure_ascii=True + indent=2 与现有文件风格一致(现有文件中文为 \uXXXX 转义)
chg.write_text(json.dumps(data, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
print(f"✓ changelog.json 补登 {ver}: {msg}")
sys.exit(0)
PYEOF
  then
    if ! $GIT diff --quiet -- static-site/changelog.json; then
      echo "  ✓ changelog.json 已更新, 将随 bump 产物一起 commit"
    else
      echo "  · changelog.json 无变更(已登记或无需补登)"
    fi
  else
    echo "✗ changelog 补登脚本异常, 请人工检查(§23.11 不静默; 不阻断 merge 主流程, 但上线 check 会 FAIL)" >&2
  fi
fi

# 7. §24⑤ 校验 index 引用版本串 == 实际文件内容 md5
#    这里用 check_version_progress.py 的 A 任务承担(版本串 ≥ 祖先天花板 + 源码 diff 必须前进);
#    §24⑤ 的「内容哈希==引用」由 bump 脚本自身保证(每次 bump 强制换新串)。
echo "--- §24⑤ 版本串/净回退校验(机制 A/B) ---"
if [[ "$DRY_RUN" == "1" ]]; then
  echo "  [dry-run] 跳过 check_version_progress"
else
  if ! "$PY" "$REPO/scripts/check_version_progress.py" --site-dir "$REPO/static-site" --repo "$REPO" --deploy-mode; then
    echo "✗ 版本串倒退/净回退校验 FAIL, 阻断上线(§24⑤/§23.11)" >&2
    exit 1
  fi
fi

# 7.5 critical-css 与 style.css 双源一致性机检(§24 + §22 一致性精神, 2026-09-23 主控补充挂主入口)
#     背景: 该机检原只挂 deploy.sh 1.2.4(数据上线链, 当天 17:50 update_all 才跑)。但
#     「改 style.css 忘同步 critical-css」的典型路径是 push main 走本脚本(代码上线链),
#     漂移不会被立即拦, 要等当天 17:50 数据 deploy 才 FAIL——且那时 FAIL 拦的是数据上线(风险倒挂)。
#     本步前置拦截: 在真正 push main 之前跑同一机检, 复用 scripts/check-dual-src/check_dual_src_sync.py
#     (单点实现双入口调用, 不复制逻辑)。校验源 = $REPO/static-site(merge 后+bump 前的即将上线代码)。
#     注: 与第 7 步 check_version_progress 同处 merge 后/bump 后、push 前;deploy.sh 1.2.4 仍保留,
#     双入口互为兜底(代码上线链立即拦, 数据上线链仍拦)。
echo "--- critical-css 与 style.css 双源一致性机检(挂主入口, §24 双源防漂移) ---"
if [[ "$DRY_RUN" == "1" ]]; then
  echo "  [dry-run] 跳过 check_dual_src_sync"
else
  if ! "$PY" "$REPO/scripts/check-dual-src/check_dual_src_sync.py" --site-dir "$REPO/static-site"; then
    echo "✗ critical-css 与 style.css 双源一致性机检 FAIL, 阻断 merge(§24 双源防漂移)" >&2
    exit 1
  fi
  echo "✓ critical-css 与 style.css 双源一致性机检通过"
fi

# 7.6 文档「时点/调度口径」一致性机检(§22 一致性铁律 + B 线 launchd 扫除根治, 2026-09-29 挂主入口)
#     背景: launchd → 云上 systemd timer 迁移后, 文档口径曾 4 轮 FAIL(改邻行漏紧邻行, 人眼扫必然漏)。
#     触发词: 任何文档含 launchd·launchctl·LaunchAgents·15:33·废弃 unit 名的改动都该在 merge 前被拦。
#     逻辑: 扫 $REPO/docs/**/*.md + .claude/**/*.md + README.md, 命中过时口径(现行文档断言 launchd/15:33
#            现行迁移前的旧时点)且不在豁免上下文即 FAIL。豁免=历史快照(文件名带日期/清单内)/显式标记
#            <!-- staleness-ok -->/行内迁移对照与本机工具上下文词(详见脚本头注释)。
echo "--- 文档时点/调度口径一致性机检(§22 + B 线 launchd 扫除) ---"
if [[ "$DRY_RUN" == "1" ]]; then
  echo "  [dry-run] 跳过 check_doc_staleness"
else
  if ! "$PY" "$REPO/scripts/check_doc_staleness.py" --root "$REPO"; then
    echo "✗ 文档时点/调度口径一致性机检 FAIL, 阻断 merge(§22 一致性铁律, 修复指引见上方命中行)" >&2
    exit 1
  fi
  echo "✓ 文档时点/调度口径一致性机检通过"
fi

# 7.8 systemd 生成源 vs 云上快照一致性机检(#189 生成源防漂移, 2026-10-05 挂主入口)
#     背景: scripts/gen_systemd_units.py 以 docs/deploy/systemd-units-20260912.md §2 的 ini 块为
#     生成源。「doc §2 值 ≠ 云上实值」时, 任何人重跑生成器并装回云上就会静默回退云上手管配置
#     (实例: 迁移批旧 TimeoutStartSec 与 #36 收口后的云上 30 处不一致, 重跑=把超时收口打回去)。
#     校验源 = docs/deploy/systemd-units-cloud-snapshot.txt(云上 unit dump 固化快照, @@@FILE: 格式);
#     逐字段全量比对 doc §2 生成物 vs 快照, 任一不一致 FAIL 阻断。刷新快照见报告/docs/ops。
echo "--- systemd 生成源 vs 云上快照一致性机检(#189, §22 生成源防漂移) ---"
if [[ "$DRY_RUN" == "1" ]]; then
  echo "  [dry-run] 跳过 systemd 生成源一致性机检"
else
  if ! "$PY" "$REPO/scripts/systemd_timeout_gradient_audit.py" \
        --dump "$REPO/docs/deploy/systemd-units-cloud-snapshot.txt" --check-doc; then
    echo "✗ systemd 生成源(doc §2)与云上快照不一致, 阻断 merge(#189, 修复: 对齐 doc §2 或刷新快照)" >&2
    exit 1
  fi
fi

# 7.8b R2 上传锁域/超时梯度审计(2026-10-31 常态化, L55 同类: overfit 倒置漏网多天)
#     背景: scripts/r2_lock_gradient_audit.py(2026-10-28 建)只被 pytest 间接覆盖, 无自动闸门 ⇒
#     「内层工作预算 ≥ 外层 systemd 墙」这类倒置能静默上线(overfit_monitor 960 vs 360 实例)。
#     本步跑仓库侧(--check-doc = 脚本文面量 + 仓库云上快照), FAIL 阻断 merge; 云上真值侧由
#     trade-cloud-unit-patrol.timer 跑 --check-snapshot, 只告警不改生产。只读静态, 不跑上传。
echo "--- R2 上传锁域/超时梯度审计(L55, --check-doc) ---"
if [[ "$DRY_RUN" == "1" ]]; then
  echo "  [dry-run] 跳过 R2 超时梯度审计"
else
  if ! "$PY" "$REPO/scripts/r2_lock_gradient_audit.py" --check-doc --quiet; then
    echo "✗ R2 上传锁域/超时梯度审计 FAIL, 阻断 merge(L55: 修内层预算或外层 TimeoutStartSec, 四副本同步)" >&2
    exit 1
  fi
  echo "✓ R2 上传锁域/超时梯度审计通过"
fi

# 7.9 L52 pre-merge 全量 pytest(scripts/ 有改动时;2026-10-18 批3 挂主入口, 教训 L52)
#     背景: 改 `scripts/` **任何源码**后自验必须含**全量** `pytest -q scripts/tests/` —— tests/ 里存在
#     「源码形状守卫」(grep 生产源文件字面量, 实测 21 个文件), 源形状一变守卫即红; 本机只跑「相关
#     用例绿」≠ 全绿。CI 侧全量 pytest 早就有了(⑧), 但它跑在 **merge 之后** ⇒ 红在 main 上(#891)。
#     本步把这道红前移到 **push main 之前**(local main 上红, 护住远端 main; red-first 精神): 检出
#     scripts/ 变更 → 跑全量 pytest, FAIL 阻断本次 push main(远端 main 不入红)。
#     爆炸半径(memory gate-position-blast-radius): 本地脚本, 失败=主控这次 merge 停一次(正是目的);
#     位置在 **merge 之后、push main 之前** ⇒ 失败时 local main 已含本次 merge = 半完成态, 由主控处置
#     (memory main-merge-fail-leaves-half-merged-main: 重跑 main-merge.sh 即恢复), 不拖 deploy 链。
#     成本: 全量 ~150s, merge 频率低(每天个位数), 可接受。
#     逃生门: MAIN_MERGE_SKIP_PYTEST=1(与 CI_SELFCHECK_SKIP 同模式), 跳时打醒目日志, **不静默**。
#     找解释器: $MAIN_MERGE_PYTEST_PY > $REPO/.venv/bin/python3 > python3(依次试 import pytest);
#     一个都找不到 ⇒ **阻断**(找不到 = 这道门没跑 = 未验证; 拒绝静默放行, §18 L49 空转闸门教训)。
echo "--- L52 pre-merge 全量 pytest(scripts/ 有改动时, §18 L52) ---"
CHANGED_SCRIPTS="$($GIT diff --name-only "origin/main...$FEAT" -- scripts/ 2>/dev/null || true)"
if [[ -z "$CHANGED_SCRIPTS" ]]; then
  echo "  scripts/ 无变更 → 跳过全量 pytest(L52 只针对源码面; 文档/前端改动不触发)"
elif [[ "$DRY_RUN" == "1" ]]; then
  echo "  [dry-run] 检出 scripts/ 变更 $(printf '%s\n' "$CHANGED_SCRIPTS" | wc -l | tr -d ' ') 个 → 跳过全量 pytest"
else
  PYTEST_PY=""
  for cand in "${MAIN_MERGE_PYTEST_PY:-}" "$REPO/.venv/bin/python3" "$(command -v python3 || true)"; do
    [[ -n "$cand" && -x "$cand" ]] || continue
    if "$cand" -c 'import pytest' >/dev/null 2>&1; then PYTEST_PY="$cand"; break; fi
  done
  if [[ -z "$PYTEST_PY" ]]; then
    echo "" >&2
    echo "  ████████████████████████████████████████████████████████████████" >&2
    echo "  [!!] 找不到带 pytest 的解释器 ⇒ L52 门无法执行 = 未验证, 拒绝静默放行" >&2
    echo "       (试过: \$MAIN_MERGE_PYTEST_PY / $REPO/.venv/bin/python3 / python3)" >&2
    echo "       修法: 装 pytest, 或 export MAIN_MERGE_PYTEST_PY=<带 pytest 的解释器>;" >&2
    echo "             确需跳过: MAIN_MERGE_SKIP_PYTEST=1(跳时打醒目日志)" >&2
    echo "  ████████████████████████████████████████████████████████████████" >&2
    exit 1
  fi
  if [[ "${MAIN_MERGE_SKIP_PYTEST:-0}" == "1" ]]; then
    echo ""
    echo "  ████████████████████████████████████████████████████████████████"
    echo "  [!!] MAIN_MERGE_SKIP_PYTEST=1(逃生门): 本次 merge 已跳过全量 pytest"
    echo "       —— 改过 scripts/ 却没跑全量 = 可能把 L52 型红(#891 源码形状守卫)直接带进 main,"
    echo "          CI ⑧ 会兜底但红在 main 上; 请记得事后补跑:"
    echo "          $PYTEST_PY -m pytest -q $REPO/scripts/tests/"
    echo "  ████████████████████████████████████████████████████████████████"
    echo ""
  else
    echo "  检出 scripts/ 变更, 跑全量 pytest(解释器: $PYTEST_PY)…"
    if ! "$PYTEST_PY" -m pytest -q "$REPO/scripts/tests/"; then
      echo "✗ 全量 pytest 红, 阻断 merge(§18 L52: 形状守卫可能与改动同批红, 先修好再 merge)" >&2
      exit 1
    fi
    echo "  ✓ 全量 pytest 绿"
  fi
fi

# 7.7 console 洁净度哨兵(#133 复发防线, 2026-10-03 挂发版验收)
#     背景: #133(两份 CSP connect-src 逐字拉平, merge b4c95c2e0)新增 accept_console_clean.mjs
#     哨兵(判 0 CSP 违规 + 0 pageerror), 但一直没进验收链, 防复发靠人肉想起来跑。挂本入口:
#     每次发版(merge main)自动打线上真实 URL 校验, 防 CSP 白名单回归让 console 噪音淹没真告警。
#     退出码语义(见脚本头): 0=PASS 1=FAIL(违规, 阻断) 2=UNREACHABLE(线上不可达, 放行+醒目提示)。
#     逃生门: SKIP_CONSOLE_CLEAN=1 跳过(线上临时抖动/合规豁免时用), 触发必打醒目提示, 不静默。
#     不可达 vs 违规(2026-10-03 决策): 违规(exit 1)阻断发版——真故障必须先修; 不可达(exit 2)
#     打醒目告警后放行——哨兵打的是「当前线上」=上一个发版, 一次 CDN/网络抖动不该把代码发版
#     锁死, 且 main-merge 本身 push 依赖网络, 若真全网断 push 也会失败自然拦; 但主控须知晓
#     本次未验证线上洁净度(线上有 #133 类问题会在下次硬拦截)。
#     注意: 新代码的 CSP 白名单(worker/headers.js)是单独部署链, 哨兵验的是已上线状态——
#     它是#133 复发防线的一环, 不是唯一机制。
echo "--- console 洁净度哨兵(#133 复发防线, 打线上真实 URL, 约 1 分钟) ---"
if [[ "$DRY_RUN" == "1" ]]; then
  echo "  [dry-run] 跳过 console 洁净度哨兵"
elif [[ "${SKIP_CONSOLE_CLEAN:-0}" == "1" ]]; then
  echo ""
  echo "  ████████████████████████████████████████████████████████████████████"
  echo "  [!!] SKIP_CONSOLE_CLEAN=1(逃生门): 本次发版已跳过 console 洁净度检查"
  echo "       —— 线上 console 洁净度未验证, 请记得事后补跑:"
  echo "       node $REPO/scripts/playwright-accept/accept_console_clean.mjs"
  echo "  ████████████████████████████████████████████████████████████████████"
  echo ""
elif ! command -v node >/dev/null 2>&1; then
  echo "" >&2
  echo "  ████████████████████████████████████████████████████████████████████" >&2
  echo "  [!!] node 不可用: console 洁净度哨兵本次未执行(不阻断发版)" >&2
  echo "       —— 线上 console 洁净度未验证; 手动可跑:" >&2
  echo "       BASE_URL=https://ss.fx8.store node scripts/playwright-accept/accept_console_clean.mjs" >&2
  echo "  ████████████████████████████████████████████████████████████████████" >&2
  echo "" >&2
else
  CC_RC=0
  ( cd "$REPO" && BASE_URL="${BASE_URL:-https://ss.fx8.store}" node scripts/playwright-accept/accept_console_clean.mjs ) || CC_RC=$?
  if [[ "$CC_RC" -eq 0 ]]; then
    echo "✓ console 洁净度 PASS(0 CSP 违规 + 0 pageerror)"
  elif [[ "$CC_RC" -eq 1 ]]; then
    echo "✗ console 洁净度 FAIL: 线上检测到 CSP 违规 / pageerror, 阻断发版(#133 复发防线)" >&2
    echo "  请根据上方哨兵输出(违规路由/视口/样例文本)先修复再重跑; 确系误判/临时抖动可 SKIP_CONSOLE_CLEAN=1 逃生" >&2
    exit 1
  else
    echo "" >&2
    echo "  ████████████████████████████████████████████████████████████████████" >&2
    echo "  [UNREACHABLE] console 洁净度哨兵: 线上不可达/未能完整校验(exit $CC_RC), 放行本次发版" >&2
    echo "       —— 本次发版未验证线上 console 洁净度, 建议事后确认线上是否恢复正常" >&2
    echo "       —— 若连续多次发版均 UNREACHABLE, 请人工核查线上可用性(哨兵可能形同虚设)" >&2
    echo "  ████████████████████████████████████████████████████████████████████" >&2
    echo "" >&2
  fi
fi

# 8.5 pending-index 销账软提醒(2026-08-22 用户授权流程小机制: 只提醒不阻断不自动改文件)
#     背景: merge 进 main 的 commit message 常引用 docs/pending-features-index.md 的 #NN 编号但没人顺手销账。
#     逻辑: 从本次 merge 带入的 commit message(标题+body, 范围=merge 前 origin/main..HEAD)提取 #编号,
#           对照 pending-index 该编号是否仍以活跃形式出现——词边界精确匹配(#15 不误配 #150),
#           先剔除 ~~…~~ 划线墓碑段再查(墓碑=已销账不算活跃);命中则 echo 提醒。dry-run 跳过。
#     提取口径(2026-10-16 修误报 + 补链式丢尾): 编号后紧跟字母/数字的不算引用——「审计#2a」不再被截成 2
#           去对账(旧口径 `grep -oE '#[0-9]+'` 会把 #2a 吃成 2 ⇒ 对上索引里无关的 #2 ⇒ 误报)。
#           相邻引用(#12#34#56 / #174#176#177 这类链)先拆空格再提取: 单遍 sed 只拆开前一对,
#           且 grep -o 会把后一处的 `#` 当上一匹配的结束符吃掉 ⇒ 3+ 链丢尾(#12#34#56 只出 12 34)。
#           故改为**不动点循环**: 反复把每个「数字#数字」拆成「数字 #数字」直到不再变化, 链上每号都保留。
#           已知让步: 任务号+包后缀连写(如 #264c)整串不算引用 ⇒ 该号不被提取。此让步与 #2a 同形
#           (编号紧跟字母, 机制上无法区分); 实测 main 已有 chore/fix(#264c) 这类以连写为唯一引用、
#           而 #264 仍活跃的 commit ⇒ 该类引用新口径下静默不提醒, 属软提醒机制可容忍的已知让步(#264c 不作支持)。
#     回归用例(改这段时手跑; static-only, 抽本段+假 git 喂 stdin, 不 source 整脚本):
#           ①重放 `git log --format=%B 98ada5d4f..10b180df1` 过本行管道 ⇒ 输出空(旧版出「2」)
#           ②喂 `fix #2a 审计#3 见 #15 与 #150 #264 包3 #264c` ⇒ `3 15 150 264`
#           ③同输入喂下方 for 循环 + 两行假 pending-index(`| 264 | 活跃 |` / `> 本模块 #1/#2/#7 已完成`)
#           ⇒ 只提醒 264、不再提醒 2
#           ④chain `#12#34#56` ⇒ `12 34 56`(8dea30f23 版只出 `12 34`, 丢尾)
#           ⑤quad `#5#7#9#11` ⇒ `5 7 9 11`; `#174#176#177` ⇒ `174 176 177`(真实历史形态, 8dea30f23 版丢尾)
#           ⑥`bash -n scripts/main-merge.sh`。
#           ⑦非法 UTF-8 字节输入(喂 `printf 'fix \x80\x81\n'`): BSD sed 报 illegal byte sequence,
#             循环内 sed 已加 `|| true` 兜住 ⇒ rc=0 / REFS 空(修复前 rc=1, set -e 中止在 push 之前)。
#           (未加 pytest: 本段依赖 grep/sed/sort 的实际行为, 本机是 BSD 工具链、CI 是 GNU,
#            在本机无法证明两者同构 ⇒ 不加 CI 常驻测试, 改为上方手跑用例; 详见修复单报告。)
if [[ "$DRY_RUN" == "1" ]]; then
  echo "  [dry-run] 跳过 pending-index 销账提醒"
else
  PENDING_IDX="$REPO/docs/pending-features-index.md"
  HIT_NUMS=""
  if [[ -f "$PENDING_IDX" ]]; then
    # 提取编号去重升序(|| true 防 grep 空匹配非零退出触发 set -e)
    #   口径与理由见上方 8.5 顶注释; 先不动点循环把相邻引用拆成 "#12 #34 #56"(反复拆到不再变化),
    #   再逐段提取——单遍 sed + grep -o 会把 3+ 链的尾号丢掉(见顶注释)。
    _REF_TXT="$($GIT log --format=%B "$PRE_MERGE_BASE"..HEAD 2>/dev/null || true)"
    while :; do
      # || true: 非法 UTF-8 字节输入会让 BSD sed 报 illegal byte sequence(rc=1); 不兜住则 set -e 会在
      # merge 之后 / push main 之前中止脚本, 留「本地已 merge 未 push」半完成态 —— 兜住即降级为空结果继续走。
      _REF_SPLIT="$(printf '%s\n' "$_REF_TXT" | sed -E 's/([0-9])#([0-9])/\1 #\2/g' || true)"
      if [[ "$_REF_SPLIT" == "$_REF_TXT" ]]; then break; fi
      _REF_TXT="$_REF_SPLIT"
    done
    REF_NUMS="$(printf '%s\n' "$_REF_TXT" \
      | grep -oE '#[0-9]+([^0-9A-Za-z]|$)' \
      | sed 's/[^0-9]//g' | sort -un || true)"
    for n in $REF_NUMS; do
      # 活跃判定(两种活跃形态任一命中即算): ①行内词边界精确 #n 引用(#15 不误配 #150)
      #   ②表格行首列裸编号 | n |(pending-index 主表行的主键形态)
      # 先 sed 剔除 ~~…~~ 划线墓碑段再查(墓碑=已销账不算活跃);日期/普通数字不受影响(锚定 # 或 | )
      _pat='(^|[^0-9])#'"${n}"'([^0-9]|$)|(^[[:space:]]*[|][[:space:]]*'"${n}"'[[:space:]]*[|])'
      if grep -E "$_pat" "$PENDING_IDX" 2>/dev/null \
          | sed -E 's/~~[^~]*~~//g' \
          | grep -qE "$_pat"; then
        HIT_NUMS="$HIT_NUMS #${n}"
      fi
    done
  fi
  if [[ -n "$HIT_NUMS" ]]; then
    echo ""
    echo "ℹ️ 销账软提醒(pending-index 对账, 只提醒不阻断): 本次 merge 带入的 commit 引用了${HIT_NUMS}"
    echo "   以上编号在 docs/pending-features-index.md 仍以活跃形式出现, 考虑顺手销账(移 done-list / 标完成)。"
    echo ""
  else
    echo "✓ pending-index 销账对账: 本次 merge 无仍活跃的 #编号引用(或无引用/索引文件不在)"
  fi
fi

# 9. commit(自动追加 Co-Authored-By) + push main
if [[ "$DRY_RUN" == "1" ]]; then
  echo "[dry-run] 跳过 commit + push main"
  echo "=== dry-run 演练完成(未实际 merge/push) ==="
  exit 0
fi

echo "--- commit + push main ---"
if ! $GIT diff --cached --quiet; then
  # merge 本身已有 index 变更(merge commit 已生成), 不重复 add
  :
fi
# 若 bump 后工作区有未暂存变更(第 6 步 build_min/bump 产生的 min/html/sw.js 变更), 需 add
# ⚠️ bump 阶段产物全量 add(与 bump_asset_version.py 实际写入对齐):
#    8 个 min 产物(common/purpose-notes/kelly-review-notes/kelly-reports-content/app/lab
#    的 .min.js + style.min.css + lab.min.css)
#    + 4 个 html(index/about/guide/privacy——bump 脚本对 static-site/*.html 全量 glob,
#    当前含 ?v= 引用会被写入的就是这 4 个; 其余 8 个 html(databrief/trade_sim*)无资源引用
#    不会被写入, 不列) + sw.js
#    + static-site/changelog.json(#83 C8, 2026-09-09): 第 6.5 步 changelog 补登产物, 同属
#    bump 阶段待 commit 文件, 并入本数组随第 9 步一起 add+commit)。
#    漏 add = 版本串更新残留工作区进不了 git, 线上引用旧版本串(CSS 一变即 §24 孤儿快照断链;
#    2026-08-22 凌晨两次 merge 后 about/guide/privacy 均复现, main 7cb8208a0 手工补提交)。
# ⚠️ 判断条件只盯 bump 产物 diff, 不用整个工作区 diff(2026-08-19 实测卡死根因):
#    工作区若存在与本次 merge 无关的未提交改动(如 claude-work-mode/README.md 由
#    token-cache-stats 定时任务追加命中率走势产生), 全工作区 diff 会误入本分支,
#    而 bump 产物本次无变更 → git commit 空提交失败 exit 1(set -e 下卡住整个 merge)。
BUMP_PRODUCTS=(static-site/app.min.js static-site/lab.min.js static-site/common.min.js \
               static-site/purpose-notes.min.js static-site/kelly-review-notes.min.js \
               static-site/kelly-reports-content.min.js \
               static-site/style.min.css static-site/lab.min.css \
               static-site/index.html static-site/about.html \
               static-site/guide.html static-site/privacy.html \
               static-site/sw.js static-site/changelog.json)
if ! $GIT diff --quiet -- "${BUMP_PRODUCTS[@]}"; then
  $GIT add "${BUMP_PRODUCTS[@]}"
  $GIT commit -m "build(统一bump): main-merge.sh 统一 build_min+bump 版本串(机制C, feat=$FEAT)

Co-Authored-By: Claude <noreply@anthropic.com>"
fi

# merge commit 若未生成(pure bump 无 merge?)确保有 commit; 这里以 merge 已生成 commit 为准
# push main
if ! $GIT push origin main; then
  echo "✗ push main 失败(可能 non-fast-forward)。优先 git fetch + rebase origin/main + 重试(§8 不 force)" >&2
  $GIT fetch origin
  $GIT rebase origin/main || { echo "✗ rebase 失败, 已 abort, 请人工处理" >&2; $GIT rebase --abort; exit 5; }
  $GIT push origin main
fi
echo "✓ push main 成功"

# 10. merge 即同步: push main 成功后自动 ssh 云上 git pull(2026-09-19 用户定, 根治「忘 pull」)
#     背景: 云上 trade-data 是手动 git pull, 不 pull 不生效(如 check_data_integrity.py 改查 R2 的
#           commit 3f245e446 合入 origin/main 后, 云上不 pull 就仍跑旧校验, 用户已拍板根治)。
#     说明: 云上 /home/ubuntu/code/trade-data 的 scripts 等目录是 symlink 指向真实 git 仓库
#           /home/ubuntu/code/trade-data-signal(2026-09-15 阶段4b 单仓路径, 原 /opt/trade;
#           memory trade-data-code-dirs-are-symlinks)。pull 必须在真实 git 仓库内执行,
#           故 cd 进 $CLOUD_GIT_REPO。ssh 必须带 -i ~/tdsignal.pem(非默认 id_rsa,
#           memory ssh-cloud-uses-tdsignal-pem)。失败不静默(§23.11): 醒目 [!!] 告警 + 非零退出。
CLOUD_SSH_HOST="ubuntu@122.51.111.173"
CLOUD_SSH_KEY="$HOME/tdsignal.pem"
CLOUD_GIT_REPO="/home/ubuntu/code/trade-data-signal"
sync_cloud_pull() {
  echo "--- 10. merge 即同步: ssh 云上 git pull($CLOUD_GIT_REPO) ---"
  if [[ ! -f "$CLOUD_SSH_KEY" ]]; then
    echo "[!!] 云上代码同步失败: 本机私钥 $CLOUD_SSH_KEY 不存在" >&2
    echo "    请主控手动执行: ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'cd $CLOUD_GIT_REPO && git pull origin main'" >&2
    return 1
  fi
  local out rc=0
  # 注意: set -e 下命令替换非零会触发退出, 用 || rc=$? 接住 ssh 退出码再自行判断
  out="$(ssh -o ConnectTimeout=15 -i "$CLOUD_SSH_KEY" "$CLOUD_SSH_HOST" "cd $CLOUD_GIT_REPO && git pull origin main" 2>&1)" || rc=$?
  if [[ $rc -ne 0 ]]; then
    echo ""
    echo "  ██████████████████████████████████████████████████████████████████████" >&2
    echo "  [!!] 云上代码同步失败(ssh 退出码=$rc), 生产校验脚本仍是旧版" >&2
    echo "      main 已 push 成功, 但云上未 pull, 请主控立即手动同步:" >&2
    echo "      ssh -i $CLOUD_SSH_KEY $CLOUD_SSH_HOST 'cd $CLOUD_GIT_REPO && git pull origin main'" >&2
    echo "     ssh 输出如下:" >&2
    echo "    --------------------------------------------------------------" >&2
    echo "$out" | sed 's/^/    /' >&2
    echo "    --------------------------------------------------------------" >&2
    echo "  ██████████████████████████████████████████████████████████████████████" >&2
    echo ""
    return 1
  fi
  # 成功: 回显 pull 结果(Updating/Already up to date/Fast-forward)
  echo "$out" | sed 's/^/    /'
  local cloud_head
  cloud_head="$(ssh -o ConnectTimeout=15 -i "$CLOUD_SSH_KEY" "$CLOUD_SSH_HOST" "git -C $CLOUD_GIT_REPO rev-parse --short HEAD" 2>/dev/null || echo '?')"
  echo "✓ 云上已同步到 origin/main($cloud_head)"
  return 0
}
sync_cloud_pull || { echo "✗ main 已 push 但云上同步失败, 见上方 [!!] 告警。请手动 ssh pull 后人工补同步(§23.11 不静默)" >&2; exit 6; }

# 11. push main 后自动自查 CI 结论(2026-10-07 用户定, 防「CI FAIL 无人察觉」)
#     放在云上同步之后(§14 生产同步优先, 不被最长 8 分钟的 CI 轮询阻塞);
#     作为最后一步: FAIL 时以非零退出把「CI 门禁红」暴露给主控(§23.11 绝不静默),
#     但 main 已 push + 云上已同步, 不影响本次上线动作本身。
#     注意: 本步只在真实 push(非 dry-run)后执行 —— dry-run 在 push 前已 exit 0。
PUSHED_SHA="$($GIT rev-parse HEAD)"
echo "--- 11. push main 后自动自查 CI 结论(commit=${PUSHED_SHA:0:8}) ---"
CI_RC=0
ci_selfcheck "$PUSHED_SHA" || CI_RC=$?
if [[ "$CI_RC" -eq 1 ]]; then
  echo "=== main-merge.sh: main 已 push 且云上已同步, 但 CI 门禁 FAIL(feat=$FEAT) ⇒ 请主控立即派修 ===" >&2
  exit 9
fi
if [[ "$CI_RC" -eq 2 ]]; then
  echo "=== main-merge.sh 完成(feat=$FEAT 已合入并推送 main, 云上已同步; ⚠️ CI 结论未取得, 见上方提示) ==="
else
  echo "=== main-merge.sh 完成(feat=$FEAT 已合入并推送 main, 云上已同步, CI success) ==="
fi
